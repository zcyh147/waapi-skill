from __future__ import annotations

import os
from pathlib import Path

import pytest
import wwise_waapi.runtime_game_object_handles as game_object_handles

from wwise_waapi.runtime_game_object_handles import (
    RuntimeGameObjectContext,
    RuntimeGameObjectHandleError,
    RuntimeGameObjectHandleStore,
)


def _context() -> RuntimeGameObjectContext:
    return RuntimeGameObjectContext(
        endpoint_url="ws://127.0.0.1:8080/waapi",
        project_id="{11111111-1111-1111-1111-111111111111}",
        project_path="C:/Project/SampleProject.wproj",
        wwise_version="2025.1",
        wwise_build="v2025.1.0.1",
    )


def _issue(
    store: RuntimeGameObjectHandleStore,
    *,
    game_object_id: int = 74,
):
    return store.issue(
        game_object_id=game_object_id,
        game_object_name=f"Game Object {game_object_id}",
        context=_context(),
        source_transaction_id=f"tx1-{game_object_id:020d}",
        source_artifact_hash="a" * 64,
    )


def test_game_object_handle_store_has_a_fail_closed_record_ceiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(game_object_handles, "_MAX_RECORDS", 2)
    store = RuntimeGameObjectHandleStore(tmp_path)
    _issue(store, game_object_id=1)
    _issue(store, game_object_id=2)

    with pytest.raises(RuntimeGameObjectHandleError) as limited:
        _issue(store, game_object_id=3)
    assert limited.value.error_code == "GAME_OBJECT_HANDLE_STORE_LIMIT"


def test_game_object_handle_store_rejects_an_oversized_record_before_reading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = RuntimeGameObjectHandleStore(tmp_path)
    issued = _issue(store)
    monkeypatch.setattr(game_object_handles, "_MAX_RECORD_BYTES", 64)
    path = store.records / f"{issued.handle}.json"
    path.write_bytes(b"{" + (b" " * 64) + b"}")

    with pytest.raises(RuntimeGameObjectHandleError) as corrupt:
        store.resolve(issued.handle, context=_context())
    assert corrupt.value.error_code == "GAME_OBJECT_HANDLE_STORE_CORRUPT"


def test_game_object_handle_native_scan_fails_before_an_unbounded_directory_walk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(game_object_handles, "_MAX_RECORDS", 1)
    store = RuntimeGameObjectHandleStore(tmp_path)
    issued = _issue(store)
    extra = store.records / "goh1-00000000000000000000000000000000.json"
    extra.write_bytes((store.records / f"{issued.handle}.json").read_bytes())

    with pytest.raises(RuntimeGameObjectHandleError) as limited:
        store.resolve_native_id(issued.game_object_id, context=_context())
    assert limited.value.error_code == "GAME_OBJECT_HANDLE_STORE_LIMIT"


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink hierarchy proof")
@pytest.mark.parametrize("linked_component", ("state_dir", "root", "records"))
def test_game_object_handle_store_rejects_every_symlinked_storage_component(
    tmp_path: Path,
    linked_component: str,
) -> None:
    external = tmp_path / "external"
    external.mkdir()
    state_dir = tmp_path / "state"
    if linked_component == "state_dir":
        state_dir.symlink_to(external, target_is_directory=True)
    else:
        state_dir.mkdir()
        root = state_dir / "soundengine-game-object-handles-v1"
        if linked_component == "root":
            root.symlink_to(external, target_is_directory=True)
        else:
            root.mkdir()
            (root / "records").symlink_to(external, target_is_directory=True)

    with pytest.raises(RuntimeGameObjectHandleError) as corrupt:
        RuntimeGameObjectHandleStore(state_dir)
    assert corrupt.value.error_code == "GAME_OBJECT_HANDLE_STORE_CORRUPT"
