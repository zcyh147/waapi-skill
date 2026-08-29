from __future__ import annotations

import json
from pathlib import Path

import pytest
import wwise_waapi.runtime_playing_handles as playing_handles

from wwise_waapi.runtime_game_object_handles import RuntimeGameObjectContext
from wwise_waapi.runtime_playing_handles import (
    RuntimePlayingHandleError,
    RuntimePlayingHandleStore,
)


def _context(
    *,
    project_id: str = "{11111111-1111-1111-1111-111111111111}",
) -> RuntimeGameObjectContext:
    return RuntimeGameObjectContext(
        endpoint_url="ws://127.0.0.1:8080/waapi",
        project_id=project_id,
        project_path="C:/Project/SampleProject.wproj",
        wwise_version="2025.1",
        wwise_build="v2025.1.0.1",
    )


def _issue(
    store: RuntimePlayingHandleStore,
    *,
    playing_id: int = 74,
):
    return store.issue(
        playing_id=playing_id,
        event_id="{22222222-2222-2222-2222-222222222222}",
        game_object_id=42,
        context=_context(),
        source_transaction_id="tx1-00000000000000000000",
        source_artifact_hash="a" * 64,
    )


def test_playing_handle_is_opaque_context_bound_and_retired_once(
    tmp_path: Path,
) -> None:
    store = RuntimePlayingHandleStore(tmp_path)
    issued = _issue(store)

    assert issued.handle.startswith("plh1-")
    assert len(issued.handle) == len("plh1-") + 32
    assert issued.handle != "plh1-74"
    assert store.resolve(issued.handle, context=_context()) == issued
    assert store.resolve_native_id(74, context=_context()) == issued

    with pytest.raises(RuntimePlayingHandleError) as drifted:
        store.resolve(
            issued.handle,
            context=_context(
                project_id="{33333333-3333-3333-3333-333333333333}"
            ),
        )
    assert drifted.value.error_code == "PLAYING_HANDLE_CONTEXT_DRIFT"

    assert store.retire_native_id(74, context=_context()) == (issued.handle,)
    with pytest.raises(RuntimePlayingHandleError) as retired:
        store.resolve(issued.handle, context=_context())
    assert retired.value.error_code == "PLAYING_HANDLE_RETIRED"
    assert store.retire_native_id(74, context=_context()) == ()


@pytest.mark.parametrize("playing_id", (0, -1, True, 0x100000000))
def test_playing_handle_rejects_nonstarted_or_invalid_native_ids(
    tmp_path: Path,
    playing_id: object,
) -> None:
    store = RuntimePlayingHandleStore(tmp_path)
    with pytest.raises(RuntimePlayingHandleError) as rejected:
        store.issue(
            playing_id=playing_id,
            event_id="{22222222-2222-2222-2222-222222222222}",
            game_object_id=None,
            context=_context(),
            source_transaction_id="tx1-00000000000000000000",
            source_artifact_hash="a" * 64,
        )
    assert rejected.value.error_code == "PLAYING_HANDLE_NOT_STARTED"


def test_playing_handle_store_rejects_tampered_sealed_record(tmp_path: Path) -> None:
    store = RuntimePlayingHandleStore(tmp_path)
    issued = _issue(store)
    path = store.records / f"{issued.handle}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["playing_id"] = 75
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimePlayingHandleError) as corrupt:
        store.resolve(issued.handle, context=_context())
    assert corrupt.value.error_code == "PLAYING_HANDLE_STORE_CORRUPT"


def test_playing_handle_store_has_a_fail_closed_active_record_ceiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(playing_handles, "_MAX_RECORDS", 2)
    store = RuntimePlayingHandleStore(tmp_path)
    _issue(store, playing_id=1)
    _issue(store, playing_id=2)

    with pytest.raises(RuntimePlayingHandleError) as limited:
        _issue(store, playing_id=3)
    assert limited.value.error_code == "PLAYING_HANDLE_STORE_LIMIT"
