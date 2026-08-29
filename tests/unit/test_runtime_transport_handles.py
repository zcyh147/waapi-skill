from __future__ import annotations

from pathlib import Path

import pytest

from wwise_waapi.canonical import canonical_sha256
from wwise_waapi.runtime_transport_handles import (
    RuntimeTransportContext,
    RuntimeTransportHandleError,
    RuntimeTransportHandleStore,
)


def _context(*, project_id: str = "{11111111-1111-1111-1111-111111111111}") -> RuntimeTransportContext:
    return RuntimeTransportContext(
        endpoint_url="ws://127.0.0.1:8080/waapi",
        project_id=project_id,
        project_path="C:/Project/SampleProject.wproj",
        wwise_version="2025.1",
        wwise_build="v2025.1.0.1",
    )


def test_transport_handle_is_opaque_and_resolves_only_from_its_store(tmp_path: Path) -> None:
    store = RuntimeTransportHandleStore(
        tmp_path,
        token_bytes=lambda size: b"a" * size,
    )
    live_row = {"transport": 74, "object": "{11111111-1111-1111-1111-111111111111}"}
    issued = store.issue(
        transport_id=74,
        context=_context(),
        source_transaction_id="tx1-00000000000000000000",
        source_artifact_hash="b" * 64,
        transport_row_sha256=canonical_sha256(live_row),
    )

    assert issued.handle == "trh1-" + "61" * 16
    assert "0000004a" not in issued.handle
    assert store.resolve(issued.handle, context=_context()) == issued
    assert store.resolve_native_id(74, context=_context()) == issued
    store.validate_live_row(issued, live_row)

    with pytest.raises(RuntimeTransportHandleError) as stale:
        store.validate_live_row(issued, {**live_row, "object": "different"})
    assert stale.value.error_code == "TRANSPORT_HANDLE_STALE"

    with pytest.raises(RuntimeTransportHandleError) as exc:
        store.resolve("transport-session-0000004a", context=_context())
    assert exc.value.error_code == "TRANSPORT_HANDLE_INVALID"


def test_transport_handle_is_bound_to_exact_live_context(tmp_path: Path) -> None:
    store = RuntimeTransportHandleStore(tmp_path)
    issued = store.issue(
        transport_id=74,
        context=_context(),
        source_transaction_id="tx1-00000000000000000000",
        source_artifact_hash="c" * 64,
        transport_row_sha256="d" * 64,
    )

    with pytest.raises(RuntimeTransportHandleError) as exc:
        store.resolve(
            issued.handle,
            context=_context(project_id="{22222222-2222-2222-2222-222222222222}"),
        )
    assert exc.value.error_code == "TRANSPORT_HANDLE_CONTEXT_DRIFT"


def test_retired_handle_cannot_target_a_reused_native_transport_id(tmp_path: Path) -> None:
    tokens = iter((b"a" * 16, b"b" * 16))
    store = RuntimeTransportHandleStore(
        tmp_path,
        token_bytes=lambda _size: next(tokens),
    )
    first = store.issue(
        transport_id=74,
        context=_context(),
        source_transaction_id="tx1-00000000000000000000",
        source_artifact_hash="d" * 64,
        transport_row_sha256="e" * 64,
    )
    assert store.retire_native_id(74, context=_context()) == (first.handle,)
    second = store.issue(
        transport_id=74,
        context=_context(),
        source_transaction_id="tx1-11111111111111111111",
        source_artifact_hash="e" * 64,
        transport_row_sha256="f" * 64,
    )

    with pytest.raises(RuntimeTransportHandleError) as exc:
        store.resolve(first.handle, context=_context())
    assert exc.value.error_code == "TRANSPORT_HANDLE_RETIRED"
    assert store.resolve(second.handle, context=_context()) == second
