from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.operation_drafts import (  # pyright: ignore[reportMissingImports]
    DEFAULT_OPERATION_DRAFT_TERMINAL_RETENTION_SECONDS,
    DEFAULT_OPERATION_DRAFT_TTL_SECONDS,
    OperationDraftExpired,
    OperationDraftInvalidTransition,
    OperationDraftNotAvailable,
    OperationDraftRevisionConflict,
    OperationDraftState,
    OperationDraftStorageCorruption,
    OperationDraftStore,
    parse_operation_draft_archive_bytes,
)
from wwise_waapi.canonical import canonical_json_bytes


def _historical_create_record(store, created, *, terminal_state=None):
    old = store.start(
        operation="object.create", version="2022.1",
        schema_digest="a" * 64, composer_digest="b" * 64, now=created,
    )
    record = old.record
    if terminal_state == "cancelled":
        record = store.cancel(
            old.draft_id, task_authority=old.task_authority,
            expected_revision=1, now=created + timedelta(seconds=1),
        )
    elif terminal_state == "expired":
        with pytest.raises(OperationDraftExpired):
            store.inspect(
                old.draft_id, task_authority=old.task_authority,
                now=created + timedelta(seconds=DEFAULT_OPERATION_DRAFT_TTL_SECONDS),
            )
        payload = json.loads((store.records_dir / f"{old.draft_id}.json").read_bytes())
        # Parse before installing the retired composition.
        record = parse_operation_draft_archive_bytes(
            canonical_json_bytes(payload), expected_draft_id=old.draft_id,
        )
    # Historical generic typed object.create shape from 1fd2949^; never executable.
    historical = replace(record, composition={
        "contract": "waapi-skill.operation-composition/v1",
        "typed_request_schema_digest": "c" * 64,
        "facts": [],
    })
    old_path = store.records_dir / f"{old.draft_id}.json"
    old_path.write_bytes(canonical_json_bytes(historical.as_durable_dict()))
    return old, historical, old_path


@pytest.mark.parametrize("terminal_state", [None, "expired", "cancelled"])
def test_expired_historical_composition_does_not_block_a_new_draft(
    tmp_path, terminal_state,
) -> None:
    created = datetime(2026, 8, 9, tzinfo=timezone.utc)
    store = OperationDraftStore(tmp_path)
    _, _, old_path = _historical_create_record(
        store, created, terminal_state=terminal_state,
    )

    new = store.start(
        operation="object.set", version="2025.1", schema_digest="d" * 64,
        now=created + timedelta(seconds=(
            DEFAULT_OPERATION_DRAFT_TTL_SECONDS
            + DEFAULT_OPERATION_DRAFT_TERMINAL_RETENTION_SECONDS
        )),
    )

    assert new.record.state is OperationDraftState.EDITABLE
    assert new.record.version == "2025.1"
    assert not old_path.exists()


@pytest.mark.parametrize("age_seconds", [
    1,
    DEFAULT_OPERATION_DRAFT_TTL_SECONDS,
    DEFAULT_OPERATION_DRAFT_TTL_SECONDS
    + DEFAULT_OPERATION_DRAFT_TERMINAL_RETENTION_SECONDS - 1,
])
def test_retained_historical_composition_still_blocks_creation(tmp_path, age_seconds):
    created = datetime(2026, 8, 9, tzinfo=timezone.utc)
    store = OperationDraftStore(tmp_path)
    old, _, old_path = _historical_create_record(store, created)
    before = old_path.read_bytes()
    with pytest.raises(OperationDraftStorageCorruption) as failure:
        store.start(
            operation="object.set", version="2025.1", schema_digest="d" * 64,
            now=created + timedelta(seconds=age_seconds),
        )
    assert failure.value.details == {
        "draft_id": old.draft_id, "stage": "business_content",
    }
    assert old_path.read_bytes() == before
    assert len(list(store.records_dir.glob("*.json"))) == 1


@pytest.mark.parametrize("defect", [
    "digest", "time", "lifetime", "identity", "state", "audit", "noncanonical",
    "hard_link",
])
def test_cleanup_rejects_unsafe_expired_envelopes(tmp_path, defect):
    created = datetime(2026, 8, 9, tzinfo=timezone.utc)
    store = OperationDraftStore(tmp_path)
    old, historical, old_path = _historical_create_record(store, created)
    if defect == "time":
        historical = replace(historical, expires_at="invalid-time")
    elif defect == "lifetime":
        historical = replace(historical, expires_at="2026-08-09T00:00:01.000000Z")
    elif defect == "identity":
        historical = replace(historical, draft_id="od1-" + "0" * 32)
    elif defect == "state":
        historical = replace(historical, state=OperationDraftState.EXPIRED)
    elif defect == "audit":
        historical = replace(historical, audit=())
    payload = historical.as_durable_dict()
    if defect == "digest":
        payload["record_digest"] = "0" * 64
    data = canonical_json_bytes(payload)
    if defect == "noncanonical":
        data += b"\n"
    old_path.write_bytes(data)
    if defect == "hard_link":
        os.link(old_path, tmp_path / "preserved-copy.json")
    with pytest.raises(OperationDraftStorageCorruption) as failure:
        store.start(
            operation="object.set", version="2025.1", schema_digest="d" * 64,
            now=created + timedelta(days=3),
        )
    assert failure.value.details == {
        "draft_id": old.draft_id,
        "stage": "file_safety" if defect == "hard_link" else "storage_envelope",
    }
    assert old_path.read_bytes() == data


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


def test_editable_draft_expires_at_its_fixed_lifetime_and_cannot_resume(
    tmp_path,
) -> None:
    created = datetime(2026, 8, 9, 1, 2, 3, tzinfo=timezone.utc)
    store = OperationDraftStore(tmp_path)
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="c" * 64,
        now=created,
    )

    expected_expiry = created + timedelta(
        seconds=DEFAULT_OPERATION_DRAFT_TTL_SECONDS
    )
    assert started.record.expires_at == expected_expiry.isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")
    assert store.inspect(
        started.draft_id,
        task_authority=started.task_authority,
        now=expected_expiry - timedelta(microseconds=1),
    ).state is OperationDraftState.EDITABLE

    with pytest.raises(OperationDraftExpired) as expired:
        store.inspect(
            started.draft_id,
            task_authority=started.task_authority,
            now=expected_expiry,
        )
    assert expired.value.as_dict() == {
        "error_code": "OPERATION_DRAFT_EXPIRED",
        "message": "Operation Draft expired and cannot be resumed.",
        "details": {},
    }

    durable = json.loads(next(tmp_path.rglob("*.json")).read_text(encoding="utf-8"))
    assert durable["state"] == "expired"
    assert durable["revision"] == 2
    assert durable["terminal_at"] == started.record.expires_at

    with pytest.raises(OperationDraftExpired):
        store.cancel(
            started.draft_id,
            task_authority=started.task_authority,
            expected_revision=1,
            now=expected_expiry + timedelta(seconds=1),
        )
