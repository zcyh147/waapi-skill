from __future__ import annotations

import json

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.operation_drafts import (  # pyright: ignore[reportMissingImports]
    OperationDraftInvalidTransition,
    OperationDraftNotAvailable,
    OperationDraftRevisionConflict,
    OperationDraftState,
    OperationDraftStore,
)


def test_gateway_issued_task_capability_survives_a_new_cli_process_without_leaking(
    tmp_path,
) -> None:
    first_process = OperationDraftStore(tmp_path)

    started = first_process.start(
        operation="object.set",
        version="2022.1",
        schema_digest="a" * 64,
    )

    assert started.record.state is OperationDraftState.EDITABLE
    assert started.record.revision == 1
    assert started.record.operation == "object.set"
    assert started.record.version == "2022.1"
    assert started.record.schema_digest == "a" * 64
    assert started.draft_id.startswith("od1-")
    assert started.task_authority.startswith("da1-")
    durable_documents = list(tmp_path.rglob("*.json"))
    assert len(durable_documents) == 1
    assert started.task_authority not in json.dumps(
        json.loads(durable_documents[0].read_text(encoding="utf-8")),
        ensure_ascii=False,
    )

    second_process = OperationDraftStore(tmp_path)
    inspected = second_process.inspect(
        started.draft_id,
        task_authority=started.task_authority,
    )

    assert inspected == started.record

    another_task = first_process.start(
        operation="object.set",
        version="2022.1",
        schema_digest="a" * 64,
    )
    with pytest.raises(OperationDraftNotAvailable) as wrong_task:
        second_process.inspect(
            started.draft_id,
            task_authority=another_task.task_authority,
        )
    with pytest.raises(OperationDraftNotAvailable) as missing:
        second_process.inspect(
            "od1-00000000000000000000000000000000",
            task_authority=another_task.task_authority,
        )

    assert wrong_task.value.as_dict() == missing.value.as_dict()


def test_cancel_is_revision_bound_atomic_and_terminal(tmp_path) -> None:
    store = OperationDraftStore(tmp_path)
    started = store.start(
        operation="object.set",
        version="2025.1",
        schema_digest="b" * 64,
    )
    record_path = next(tmp_path.rglob("*.json"))
    original_bytes = record_path.read_bytes()

    with pytest.raises(OperationDraftNotAvailable):
        store.cancel(
            started.draft_id,
            task_authority="da1-" + ("0" * 40),
            expected_revision=1,
        )
    assert record_path.read_bytes() == original_bytes

    with pytest.raises(OperationDraftRevisionConflict) as stale:
        store.cancel(
            started.draft_id,
            task_authority=started.task_authority,
            expected_revision=2,
        )
    assert stale.value.details == {"expected_revision": 2, "actual_revision": 1}
    assert record_path.read_bytes() == original_bytes

    cancelled = store.cancel(
        started.draft_id,
        task_authority=started.task_authority,
        expected_revision=1,
    )
    assert cancelled.state is OperationDraftState.CANCELLED
    assert cancelled.revision == 2
    assert store.inspect(
        started.draft_id,
        task_authority=started.task_authority,
    ) == cancelled

    cancelled_bytes = record_path.read_bytes()
    with pytest.raises(OperationDraftInvalidTransition):
        store.cancel(
            started.draft_id,
            task_authority=started.task_authority,
            expected_revision=2,
        )
    assert record_path.read_bytes() == cancelled_bytes
