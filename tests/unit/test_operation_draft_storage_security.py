from __future__ import annotations

import errno
import json
import multiprocessing
import os
import shutil
import stat
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

import wwise_waapi.operation_drafts as draft_module
from tests.support.platform_filesystem import create_symlink_or_skip
from wwise_waapi.operation_drafts import (  # pyright: ignore[reportMissingImports]
    DEFAULT_OPERATION_DRAFT_TERMINAL_RETENTION_SECONDS,
    DEFAULT_OPERATION_DRAFT_STALE_TEMP_SECONDS,
    MAX_ACTIVE_OPERATION_DRAFTS,
    MAX_MANAGED_OPERATION_DRAFT_ENTRIES,
    MAX_OPERATION_DRAFT_RECORD_BYTES,
    OPERATION_DRAFT_LIMITS,
    OPERATION_DRAFT_LIMITS_DIGEST,
    OperationDraftLimitExceeded,
    OperationDraftLockUnavailable,
    OperationDraftNotAvailable,
    OperationDraftRevisionConflict,
    OperationDraftState,
    OperationDraftStorageCorruption,
    OperationDraftStore,
)


def _cross_process_context() -> multiprocessing.context.BaseContext:
    return multiprocessing.get_context("spawn" if os.name == "nt" else "fork")


def _tree_regular_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class _StatWithChangedCtime:
    def __init__(self, metadata: os.stat_result) -> None:
        self._metadata = metadata
        self.st_ctime_ns = metadata.st_ctime_ns + 7_845_600

    def __getattr__(self, name: str) -> Any:
        return getattr(self._metadata, name)


def _race_cancel(
    state_dir: str,
    draft_id: str,
    task_authority: str,
    ready: Any,
    results: Any,
) -> None:
    store = OperationDraftStore(Path(state_dir))
    if not ready.wait(timeout=5):
        results.put(("unexpected", "start timeout"))
        return
    try:
        record = store.cancel(
            draft_id,
            task_authority=task_authority,
            expected_revision=1,
        )
    except OperationDraftRevisionConflict as exc:
        results.put(("stale", exc.details))
    except BaseException as exc:
        results.put(("unexpected", type(exc).__name__, str(exc)))
    else:
        results.put(("committed", record.revision, record.state.value))


def _race_start(
    state_dir: str,
    ready: Any,
    results: Any,
) -> None:
    store = OperationDraftStore(Path(state_dir))
    if not ready.wait(timeout=5):
        results.put(("unexpected", "start timeout"))
        return
    try:
        started = store.start(
            operation="object.set",
            version="2022.1",
            schema_digest="8" * 64,
        )
    except OperationDraftLimitExceeded as exc:
        results.put(("full", exc.details))
    except BaseException as exc:
        results.put(("unexpected", type(exc).__name__, str(exc)))
    else:
        results.put(("started", started.record.revision))


def test_windows_ctime_drift_does_not_reject_an_unchanged_new_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_fstat = draft_module.os.fstat

    monkeypatch.setattr(
        draft_module,
        "_record_snapshot_platform_name",
        lambda: "nt",
        raising=False,
    )
    monkeypatch.setattr(
        draft_module.os,
        "fstat",
        lambda descriptor: _StatWithChangedCtime(real_fstat(descriptor)),
    )

    store = OperationDraftStore(tmp_path)
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="a" * 64,
    )
    reopened = OperationDraftStore(tmp_path).inspect(
        started.draft_id,
        task_authority=started.task_authority,
    )

    assert reopened == started.record


def test_posix_ctime_drift_still_rejects_a_changed_record_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_fstat = draft_module.os.fstat

    monkeypatch.setattr(
        draft_module,
        "_record_snapshot_platform_name",
        lambda: "posix",
    )
    monkeypatch.setattr(
        draft_module.os,
        "fstat",
        lambda descriptor: _StatWithChangedCtime(real_fstat(descriptor)),
    )

    store = OperationDraftStore(tmp_path)
    with pytest.raises(OperationDraftStorageCorruption, match="changed while"):
        store.start(
            operation="object.set",
            version="2022.1",
            schema_digest="a" * 64,
        )


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode contract")
def test_shared_state_root_may_be_readable_but_draft_store_remains_private(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "shared-state"
    state_dir.mkdir(mode=0o755)
    state_dir.chmod(0o755)

    store = OperationDraftStore(state_dir)
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="f" * 64,
    )

    assert started.record.revision == 1
    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o755
    assert stat.S_IMODE(store.store_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(store.records_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(store.locks_dir.stat().st_mode) == 0o700


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode contract")
def test_shared_state_root_rejects_group_or_other_write_access(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "writable-state"
    state_dir.mkdir(mode=0o777)
    state_dir.chmod(0o777)

    with pytest.raises(OperationDraftStorageCorruption, match="writable"):
        OperationDraftStore(state_dir)


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode contract")
def test_shared_state_root_permission_drift_is_rejected_before_record_access(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "shared-state"
    state_dir.mkdir(mode=0o755)
    state_dir.chmod(0o755)
    store = OperationDraftStore(state_dir)
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="f" * 64,
    )
    record_path = store.records_dir / f"{started.draft_id}.json"
    before = record_path.read_bytes()

    state_dir.chmod(0o777)

    with pytest.raises(OperationDraftStorageCorruption, match="re-attested"):
        store.inspect(
            started.draft_id,
            task_authority=started.task_authority,
        )
    assert record_path.read_bytes() == before


def test_cross_process_revision_cas_commits_once_and_rejects_the_loser_as_stale(
    tmp_path: Path,
) -> None:
    store = OperationDraftStore(tmp_path)
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="a" * 64,
    )
    context = _cross_process_context()
    ready = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_race_cancel,
            args=(
                str(tmp_path),
                started.draft_id,
                started.task_authority,
                ready,
                results,
            ),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    ready.set()
    outcomes = [results.get(timeout=10) for _ in processes]
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    assert sorted(outcome[0] for outcome in outcomes) == ["committed", "stale"]
    assert next(outcome for outcome in outcomes if outcome[0] == "committed") == (
        "committed",
        2,
        "cancelled",
    )
    assert next(outcome for outcome in outcomes if outcome[0] == "stale") == (
        "stale",
        {"expected_revision": 1, "actual_revision": 2},
    )
    final = store.inspect(
        started.draft_id,
        task_authority=started.task_authority,
    )
    assert final.state is OperationDraftState.CANCELLED
    assert final.revision == 2
    durable = json.loads(next(store.records_dir.glob("*.json")).read_text(encoding="utf-8"))
    assert len(durable["audit"]) == 2
    assert durable["audit"][1]["previous_event_hash"] == durable["audit"][0][
        "event_hash"
    ]


def test_missing_draft_probes_cannot_grow_per_draft_lock_state(
    tmp_path: Path,
) -> None:
    store = OperationDraftStore(tmp_path)
    authority = "da1-" + ("0" * 40)

    for suffix in range(8):
        draft_id = f"od1-{suffix:032x}"
        with pytest.raises(OperationDraftNotAvailable):
            store.inspect(draft_id, task_authority=authority)

    assert [path.name for path in store.locks_dir.iterdir()] == [
        "store-admission.lock"
    ]


def test_record_digest_and_audit_reject_byte_tamper_without_leaking_authority(
    tmp_path: Path,
) -> None:
    store = OperationDraftStore(tmp_path)
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="b" * 64,
    )
    record_path = next(store.records_dir.glob("*.json"))
    durable = json.loads(record_path.read_text(encoding="utf-8"))

    assert len(durable["record_digest"]) == 64
    assert durable["audit"][0]["event_type"] == "started"
    assert durable["audit"][0]["revision"] == 1
    assert durable["audit"][0]["previous_event_hash"] == ""
    assert durable["limits_digest"] == OPERATION_DRAFT_LIMITS_DIGEST
    durable["version"] = "2025.1"
    record_path.write_text(json.dumps(durable), encoding="utf-8")

    with pytest.raises(OperationDraftNotAvailable) as tampered:
        store.inspect(
            started.draft_id,
            task_authority=started.task_authority,
        )
    with pytest.raises(OperationDraftNotAvailable) as missing:
        store.inspect(
            "od1-00000000000000000000000000000000",
            task_authority=started.task_authority,
        )
    assert tampered.value.as_dict() == missing.value.as_dict()


@pytest.mark.parametrize("tamper_kind", ("whitespace", "reordered", "duplicate-key"))
def test_logically_equivalent_noncanonical_record_bytes_are_rejected(
    tmp_path: Path,
    tamper_kind: str,
) -> None:
    store = OperationDraftStore(tmp_path)
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="b" * 64,
    )
    record_path = store.records_dir / f"{started.draft_id}.json"
    original = record_path.read_bytes()
    durable = json.loads(original)
    if tamper_kind == "whitespace":
        tampered = original + b" "
    elif tamper_kind == "reordered":
        tampered = json.dumps(
            dict(reversed(tuple(durable.items()))),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    else:
        tampered = b'{"version":"2022.1",' + original[1:]
    record_path.write_bytes(tampered)

    with pytest.raises(OperationDraftNotAvailable):
        store.inspect(
            started.draft_id,
            task_authority=started.task_authority,
        )

    assert record_path.read_bytes() == tampered


def test_record_payload_must_match_its_durable_filename_before_expiry_work(
    tmp_path: Path,
) -> None:
    created = datetime(2026, 8, 9, tzinfo=timezone.utc)
    store = OperationDraftStore(tmp_path)
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="b" * 64,
        now=created,
    )
    original_path = store.records_dir / f"{started.draft_id}.json"
    copied_id = "od1-" + ("f" * 32)
    assert copied_id != started.draft_id
    copied_path = store.records_dir / f"{copied_id}.json"
    copied_path.write_bytes(original_path.read_bytes())
    copied_path.chmod(0o600)
    before = {
        original_path: original_path.read_bytes(),
        copied_path: copied_path.read_bytes(),
    }

    with pytest.raises(OperationDraftNotAvailable):
        store.inspect(
            copied_id,
            task_authority=started.task_authority,
            now=created + timedelta(days=2),
        )

    assert {path: path.read_bytes() for path in before} == before


def test_all_draft_resource_ceilings_are_fixed_finite_and_registry_independent() -> None:
    assert OPERATION_DRAFT_LIMITS.as_dict() == {
        "contract": "waapi-skill.operation-draft-limits/v1",
        "active_drafts": 32,
        "managed_entries": 128,
        "actions": 16384,
        "rows": 128,
        "fields_per_row": 64,
        "record_bytes": 1048576,
        "evidence_bytes": 262144,
        "result_bytes": 262144,
        "ttl_seconds": 86400,
        "terminal_retention_seconds": 86400,
        "stale_temp_seconds": 300,
        "lock_timeout_seconds": 5,
    }
    assert len(OPERATION_DRAFT_LIMITS_DIGEST) == 64


def test_oversized_record_is_rejected_before_unbounded_json_decode(tmp_path: Path) -> None:
    store = OperationDraftStore(tmp_path)
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="c" * 64,
    )
    record_path = next(store.records_dir.glob("*.json"))
    record_path.write_bytes(b"{" + (b" " * MAX_OPERATION_DRAFT_RECORD_BYTES) + b"}")

    with pytest.raises(OperationDraftNotAvailable):
        store.inspect(
            started.draft_id,
            task_authority=started.task_authority,
        )


def test_deep_json_is_bounded_as_non_enumerable_or_store_corruption(
    tmp_path: Path,
) -> None:
    store = OperationDraftStore(tmp_path)
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="c" * 64,
    )
    record_path = store.records_dir / f"{started.draft_id}.json"
    deeply_nested = (b"[" * 2_000) + b"0" + (b"]" * 2_000)
    record_path.write_bytes(deeply_nested)

    with pytest.raises(OperationDraftNotAvailable):
        store.inspect(
            started.draft_id,
            task_authority=started.task_authority,
        )
    with pytest.raises(OperationDraftStorageCorruption, match="validated|cleanup"):
        store.start(
            operation="object.set",
            version="2022.1",
            schema_digest="c" * 64,
        )


def test_bounded_record_reader_handles_short_regular_file_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = OperationDraftStore(tmp_path)
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="c" * 64,
    )
    real_read = draft_module.os.read

    def short_read(descriptor: int, maximum: int) -> bytes:
        return real_read(descriptor, min(maximum, 17))

    monkeypatch.setattr(draft_module.os, "read", short_read)

    assert store.inspect(
        started.draft_id,
        task_authority=started.task_authority,
    ) == started.record


@pytest.mark.parametrize(
    "invalid_change",
    (
        {"expires_at": "2026-08-09T00:00:00.000000Z"},
        {"updated_at": "2026-08-08T23:59:59.000000Z"},
        {"terminal_at": "2026-08-09T00:00:00.000000Z"},
        {"created_at": "2026-08-09T00:00:00+00:00"},
        {"created_at": 123},
    ),
)
def test_validly_rehashed_record_still_rejects_impossible_lifetime_state(
    tmp_path: Path,
    invalid_change: dict[str, Any],
) -> None:
    created = datetime(2026, 8, 9, tzinfo=timezone.utc)
    store = OperationDraftStore(tmp_path)
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="c" * 64,
        now=created,
    )
    invalid = replace(started.record, **invalid_change)
    record_path = store.records_dir / f"{started.draft_id}.json"
    record_path.write_bytes(draft_module.canonical_json_bytes(invalid.as_durable_dict()))

    with pytest.raises(OperationDraftNotAvailable):
        store.inspect(
            started.draft_id,
            task_authority=started.task_authority,
            now=created,
        )


@pytest.mark.parametrize(
    "tamper_kind",
    ("bool-index", "non-string-type", "started-terminal", "post-terminal", "time-reversal"),
)
def test_validly_rehashed_audit_still_enforces_lifecycle_semantics(
    tmp_path: Path,
    tamper_kind: str,
) -> None:
    created = datetime(2026, 8, 9, tzinfo=timezone.utc)
    store = OperationDraftStore(tmp_path)
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="c" * 64,
        now=created,
    )
    durable = started.record.as_durable_dict()
    created_at = started.record.created_at

    if tamper_kind in {"bool-index", "non-string-type", "started-terminal"}:
        event = dict(durable["audit"][0])
        if tamper_kind == "bool-index":
            event["sequence"] = True
            event["revision"] = True
        elif tamper_kind == "non-string-type":
            event["event_type"] = 7
        else:
            event["to_state"] = OperationDraftState.CANCELLED.value
            durable["state"] = OperationDraftState.CANCELLED.value
            durable["terminal_at"] = created_at
        event_material = dict(event)
        del event_material["event_hash"]
        event["event_hash"] = draft_module.canonical_sha256(event_material)
        durable["audit"] = [event]
    elif tamper_kind == "post-terminal":
        cancelled = store.cancel(
            started.draft_id,
            task_authority=started.task_authority,
            expected_revision=1,
            now=created + timedelta(seconds=1),
        )
        durable = cancelled.as_durable_dict()
        terminal_event = durable["audit"][-1]
        later = draft_module._build_audit_event(
            draft_id=started.draft_id,
            sequence=3,
            revision=3,
            event_type="action_applied",
            from_state=OperationDraftState.CANCELLED,
            to_state=OperationDraftState.EDITABLE,
            timestamp=draft_module._timestamp(created + timedelta(seconds=2)),
            previous_event_hash=terminal_event["event_hash"],
        )
        durable["audit"].append(later)
        durable["revision"] = 3
        durable["state"] = OperationDraftState.EDITABLE.value
        durable["terminal_at"] = None
        durable["updated_at"] = later["timestamp"]
    else:
        event_two = draft_module._build_audit_event(
            draft_id=started.draft_id,
            sequence=2,
            revision=2,
            event_type="action_applied",
            from_state=OperationDraftState.EDITABLE,
            to_state=OperationDraftState.EDITABLE,
            timestamp=draft_module._timestamp(created + timedelta(seconds=2)),
            previous_event_hash=durable["audit"][-1]["event_hash"],
        )
        event_three = draft_module._build_audit_event(
            draft_id=started.draft_id,
            sequence=3,
            revision=3,
            event_type="action_applied",
            from_state=OperationDraftState.EDITABLE,
            to_state=OperationDraftState.EDITABLE,
            timestamp=draft_module._timestamp(created + timedelta(seconds=1)),
            previous_event_hash=event_two["event_hash"],
        )
        durable["audit"].extend((event_two, event_three))
        durable["revision"] = 3
        durable["updated_at"] = event_three["timestamp"]

    digest_material = dict(durable)
    del digest_material["record_digest"]
    durable["record_digest"] = draft_module._record_digest(digest_material)
    record_path = store.records_dir / f"{started.draft_id}.json"
    record_path.write_bytes(draft_module.canonical_json_bytes(durable))

    with pytest.raises(OperationDraftNotAvailable):
        store.inspect(
            started.draft_id,
            task_authority=started.task_authority,
            now=created + timedelta(seconds=3),
        )


def test_active_draft_admission_is_fixed_and_terminal_gc_is_bounded(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 9, tzinfo=timezone.utc)
    store = OperationDraftStore(tmp_path)
    starts = [
        store.start(
            operation="object.set",
            version="2022.1",
            schema_digest="d" * 64,
            now=now,
        )
        for _ in range(MAX_ACTIVE_OPERATION_DRAFTS)
    ]
    before = {
        path.name: path.read_bytes() for path in store.records_dir.glob("*.json")
    }

    with pytest.raises(OperationDraftLimitExceeded) as full:
        store.start(
            operation="object.set",
            version="2022.1",
            schema_digest="d" * 64,
            now=now,
        )
    assert full.value.details == {
        "active_drafts": MAX_ACTIVE_OPERATION_DRAFTS,
        "limit": MAX_ACTIVE_OPERATION_DRAFTS,
    }
    assert {
        path.name: path.read_bytes() for path in store.records_dir.glob("*.json")
    } == before

    cancelled = store.cancel(
        starts[0].draft_id,
        task_authority=starts[0].task_authority,
        expected_revision=1,
        now=now + timedelta(seconds=1),
    )
    replacement = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="d" * 64,
        now=now + timedelta(seconds=2),
    )
    assert replacement.record.state is OperationDraftState.EDITABLE
    cancelled_path = store.records_dir / f"{cancelled.draft_id}.json"
    assert cancelled_path.is_file()

    store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="d" * 64,
        now=now
        + timedelta(
            seconds=DEFAULT_OPERATION_DRAFT_TERMINAL_RETENTION_SECONDS + 2
        ),
    )
    assert not cancelled_path.exists()


def test_cross_process_admission_never_exceeds_active_draft_ceiling(
    tmp_path: Path,
) -> None:
    store = OperationDraftStore(tmp_path)
    for _ in range(MAX_ACTIVE_OPERATION_DRAFTS - 1):
        store.start(
            operation="object.set",
            version="2022.1",
            schema_digest="8" * 64,
        )
    context = _cross_process_context()
    ready = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_race_start,
            args=(str(tmp_path), ready, results),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    ready.set()
    outcomes = [results.get(timeout=10) for _ in processes]
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    assert sorted(outcome[0] for outcome in outcomes) == ["full", "started"]
    assert len(list(store.records_dir.glob("*.json"))) == MAX_ACTIVE_OPERATION_DRAFTS


def test_managed_entry_scan_is_bounded_and_unknown_entries_fail_closed(
    tmp_path: Path,
) -> None:
    store = OperationDraftStore(tmp_path / "bounded")
    for index in range(MAX_MANAGED_OPERATION_DRAFT_ENTRIES + 1):
        temporary = store.records_dir / (
            f".od1-{'0' * 28}{index:04x}.json.{'a' * 16}.tmp"
        )
        temporary.write_bytes(b"{}")
        temporary.chmod(0o600)

    with pytest.raises(OperationDraftLimitExceeded) as too_many:
        store.start(
            operation="object.set",
            version="2022.1",
            schema_digest="9" * 64,
        )
    assert too_many.value.details == {
        "managed_entries_at_least": MAX_MANAGED_OPERATION_DRAFT_ENTRIES + 1,
        "limit": MAX_MANAGED_OPERATION_DRAFT_ENTRIES,
    }

    ordinary = OperationDraftStore(tmp_path / "unknown")
    foreign = ordinary.records_dir / "foreign.txt"
    foreign.write_text("do not delete", encoding="utf-8")
    foreign.chmod(0o600)
    with pytest.raises(OperationDraftStorageCorruption, match="unmanaged"):
        ordinary.start(
            operation="object.set",
            version="2022.1",
            schema_digest="9" * 64,
        )
    assert foreign.read_text(encoding="utf-8") == "do not delete"


def test_start_reserves_capacity_for_its_new_record_after_cleanup(
    tmp_path: Path,
) -> None:
    store = OperationDraftStore(tmp_path)
    for index in range(MAX_MANAGED_OPERATION_DRAFT_ENTRIES):
        temporary = store.records_dir / (
            f".od1-{'0' * 28}{index:04x}.json.{'b' * 16}.tmp"
        )
        temporary.write_bytes(b"{}")
        temporary.chmod(0o600)
    before = {
        path.name: path.read_bytes() for path in store.records_dir.iterdir()
    }

    with pytest.raises(OperationDraftLimitExceeded) as full:
        store.start(
            operation="object.set",
            version="2022.1",
            schema_digest="9" * 64,
        )

    assert full.value.details == {
        "managed_entries_at_least": MAX_MANAGED_OPERATION_DRAFT_ENTRIES + 1,
        "limit": MAX_MANAGED_OPERATION_DRAFT_ENTRIES,
    }
    assert {
        path.name: path.read_bytes() for path in store.records_dir.iterdir()
    } == before


def test_store_and_managed_files_reject_links_without_touching_their_targets(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    linked_root = tmp_path / "linked-state"
    create_symlink_or_skip(linked_root, outside, target_is_directory=True)
    with pytest.raises(OperationDraftStorageCorruption, match="link|reparse"):
        OperationDraftStore(linked_root)
    assert list(outside.iterdir()) == []

    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)
    linked_store = state_dir / "operation-drafts-v1"
    create_symlink_or_skip(linked_store, outside, target_is_directory=True)
    with pytest.raises(OperationDraftStorageCorruption, match="link|reparse"):
        OperationDraftStore(state_dir)
    assert list(outside.iterdir()) == []

    store = OperationDraftStore(tmp_path / "ordinary")
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="e" * 64,
    )
    record_path = store.records_dir / f"{started.draft_id}.json"
    external_record = tmp_path / "external-record.json"
    external_bytes = record_path.read_bytes()
    external_record.write_bytes(external_bytes)
    record_path.unlink()
    create_symlink_or_skip(record_path, external_record)

    with pytest.raises(OperationDraftNotAvailable):
        store.inspect(
            started.draft_id,
            task_authority=started.task_authority,
        )
    assert external_record.read_bytes() == external_bytes


@pytest.mark.parametrize(
    "directory_name",
    ("state", "store", "records", "locks"),
)
def test_post_construction_managed_directory_replacement_is_rejected(
    tmp_path: Path,
    directory_name: str,
) -> None:
    state_dir = tmp_path / "state"
    store = OperationDraftStore(state_dir)
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="e" * 64,
    )
    target = {
        "state": state_dir,
        "store": store.store_dir,
        "records": store.records_dir,
        "locks": store.locks_dir,
    }[directory_name]
    original = tmp_path / f"original-{directory_name}"
    target.rename(original)
    shutil.copytree(original, target)

    with pytest.raises(OperationDraftStorageCorruption, match="directory|identity"):
        store.inspect(
            started.draft_id,
            task_authority=started.task_authority,
        )


def test_lock_acquisition_rechecks_directory_identity_before_store_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = OperationDraftStore(tmp_path / "state")
    original = tmp_path / "original-locks"
    replacement_bytes: dict[str, bytes] = {}

    class SwapAfterAcquireBackend:
        @staticmethod
        def acquire(_handle: Any) -> None:
            store.locks_dir.rename(original)
            shutil.copytree(original, store.locks_dir)
            replacement_bytes.update(_tree_regular_bytes(store.locks_dir))

        @staticmethod
        def release(_handle: Any) -> None:
            return None

    monkeypatch.setattr(
        draft_module,
        "_select_lock_backend",
        lambda _platform_name: SwapAfterAcquireBackend(),
    )

    with pytest.raises(OperationDraftStorageCorruption, match="directory|identity"):
        store.start(
            operation="object.set",
            version="2022.1",
            schema_digest="e" * 64,
        )

    assert list(store.records_dir.iterdir()) == []
    assert _tree_regular_bytes(store.locks_dir) == replacement_bytes


def test_lock_path_identity_is_rechecked_after_acquisition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = OperationDraftStore(tmp_path / "state")
    lock_path = store.locks_dir / "store-admission.lock"
    original_lock = tmp_path / "original-admission.lock"

    class SwapLockFileAfterAcquireBackend:
        @staticmethod
        def acquire(_handle: Any) -> None:
            lock_path.rename(original_lock)
            lock_path.write_bytes(b"")
            lock_path.chmod(0o600)

        @staticmethod
        def release(_handle: Any) -> None:
            return None

    monkeypatch.setattr(
        draft_module,
        "_select_lock_backend",
        lambda _platform_name: SwapLockFileAfterAcquireBackend(),
    )

    with pytest.raises(OperationDraftStorageCorruption, match="path changed|identity"):
        store.start(
            operation="object.set",
            version="2022.1",
            schema_digest="e" * 64,
        )

    assert list(store.records_dir.iterdir()) == []
    assert lock_path.read_bytes() == b""
    assert original_lock.read_bytes() == b""


def test_record_read_rechecks_directory_identity_before_first_byte(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = OperationDraftStore(tmp_path / "state")
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="e" * 64,
    )
    original = tmp_path / "original-records"
    replacement_bytes: dict[str, bytes] = {}
    real_require_opened = draft_module._require_opened_private_regular_file
    switched = False

    def swap_after_record_open(
        path: Path,
        *,
        descriptor: int,
        label: str,
    ) -> os.stat_result:
        nonlocal switched
        metadata = real_require_opened(
            path,
            descriptor=descriptor,
            label=label,
        )
        if not switched and label == "Operation Draft record":
            switched = True
            store.records_dir.rename(original)
            shutil.copytree(original, store.records_dir)
            replacement_bytes.update(_tree_regular_bytes(store.records_dir))
        return metadata

    monkeypatch.setattr(
        draft_module,
        "_require_opened_private_regular_file",
        swap_after_record_open,
    )
    monkeypatch.setattr(
        draft_module.os,
        "read",
        lambda _descriptor, _maximum: pytest.fail(
            "record bytes were read after directory substitution"
        ),
    )

    with pytest.raises(OperationDraftStorageCorruption, match="directory|identity"):
        store.inspect(
            started.draft_id,
            task_authority=started.task_authority,
        )

    assert _tree_regular_bytes(store.records_dir) == replacement_bytes


def test_record_write_rechecks_directory_identity_before_first_byte(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = OperationDraftStore(tmp_path / "state")
    original = tmp_path / "original-records"
    replacement_bytes: dict[str, bytes] = {}
    real_require_opened = draft_module._require_opened_private_regular_file
    switched = False

    def swap_after_record_open(
        path: Path,
        *,
        descriptor: int,
        label: str,
    ) -> os.stat_result:
        nonlocal switched
        metadata = real_require_opened(
            path,
            descriptor=descriptor,
            label=label,
        )
        if not switched and label == "Operation Draft record":
            switched = True
            store.records_dir.rename(original)
            shutil.copytree(original, store.records_dir)
            replacement_bytes.update(_tree_regular_bytes(store.records_dir))
        return metadata

    monkeypatch.setattr(
        draft_module,
        "_require_opened_private_regular_file",
        swap_after_record_open,
    )

    with pytest.raises(OperationDraftStorageCorruption, match="directory|identity"):
        store.start(
            operation="object.set",
            version="2022.1",
            schema_digest="e" * 64,
        )

    assert _tree_regular_bytes(store.records_dir) == replacement_bytes
    assert set(replacement_bytes.values()) == {b""}


def test_write_error_after_directory_swap_does_not_cleanup_the_substitute_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = OperationDraftStore(tmp_path / "state")
    original = tmp_path / "original-records"
    replacement_bytes: dict[str, bytes] = {}

    def swap_then_fail_fsync(_descriptor: int) -> None:
        store.records_dir.rename(original)
        shutil.copytree(original, store.records_dir)
        replacement_bytes.update(_tree_regular_bytes(store.records_dir))
        raise OSError("synthetic fsync failure after directory substitution")

    monkeypatch.setattr(draft_module.os, "fsync", swap_then_fail_fsync)

    with pytest.raises(OperationDraftStorageCorruption, match="directory|identity"):
        store.start(
            operation="object.set",
            version="2022.1",
            schema_digest="e" * 64,
        )

    assert _tree_regular_bytes(store.records_dir) == replacement_bytes


def test_initial_publish_rechecks_record_path_after_file_fsync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = OperationDraftStore(tmp_path / "state")
    original_record = tmp_path / "original-initial-record.json"
    substitute_bytes = b"SUBSTITUTE-INITIAL-RECORD"
    swapped = False

    def swap_record_during_fsync(_descriptor: int) -> None:
        nonlocal swapped
        if not swapped:
            swapped = True
            record_path = next(store.records_dir.glob("*.json"))
            record_path.rename(original_record)
            record_path.write_bytes(substitute_bytes)
            record_path.chmod(0o600)

    monkeypatch.setattr(draft_module.os, "fsync", swap_record_during_fsync)

    with pytest.raises(
        OperationDraftStorageCorruption,
        match="path changed|identity changed",
    ):
        store.start(
            operation="object.set",
            version="2022.1",
            schema_digest="e" * 64,
        )

    assert original_record.is_file()
    assert next(store.records_dir.glob("*.json")).read_bytes() == substitute_bytes


def test_atomic_replace_rechecks_temporary_file_identity_before_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = OperationDraftStore(tmp_path)
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="e" * 64,
    )
    record_path = store.records_dir / f"{started.draft_id}.json"
    old_record_bytes = record_path.read_bytes()
    original_temporary = tmp_path / "original-revision-temp.json"
    real_read = draft_module._read_bounded_record_snapshot
    swapped = False

    def replace_temporary_before_validation(
        path: Path,
        *,
        attest_directories: Any,
    ) -> Any:
        nonlocal swapped
        if not swapped and path.name.startswith(".") and path.suffix == ".tmp":
            swapped = True
            path.rename(original_temporary)
            path.write_bytes(original_temporary.read_bytes())
            path.chmod(0o600)
        return real_read(path, attest_directories=attest_directories)

    monkeypatch.setattr(
        draft_module,
        "_read_bounded_record_snapshot",
        replace_temporary_before_validation,
    )

    with pytest.raises(OperationDraftStorageCorruption, match="temporary|identity"):
        store.cancel(
            started.draft_id,
            task_authority=started.task_authority,
            expected_revision=1,
        )

    assert record_path.read_bytes() == old_record_bytes
    assert original_temporary.is_file()


def test_orphaned_draft_lock_is_cleaned_under_the_admission_lock(
    tmp_path: Path,
) -> None:
    store = OperationDraftStore(tmp_path)
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="e" * 64,
    )
    store.cancel(
        started.draft_id,
        task_authority=started.task_authority,
        expected_revision=1,
    )
    record_path = store.records_dir / f"{started.draft_id}.json"
    lock_path = store.locks_dir / f"{started.draft_id}.lock"
    record_path.unlink()
    lock_path.write_bytes(b"")
    lock_path.chmod(0o600)
    assert lock_path.is_file()

    store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="e" * 64,
    )

    assert not lock_path.exists()


def test_locks_directory_is_included_in_the_managed_entry_ceiling(
    tmp_path: Path,
) -> None:
    store = OperationDraftStore(tmp_path)
    for index in range(MAX_MANAGED_OPERATION_DRAFT_ENTRIES):
        lock_path = store.locks_dir / f"od1-{index:032x}.lock"
        lock_path.write_bytes(b"")
        lock_path.chmod(0o600)

    with pytest.raises(OperationDraftLimitExceeded) as too_many:
        store.start(
            operation="object.set",
            version="2022.1",
            schema_digest="e" * 64,
        )

    assert too_many.value.details == {
        "managed_entries_at_least": MAX_MANAGED_OPERATION_DRAFT_ENTRIES + 1,
        "limit": MAX_MANAGED_OPERATION_DRAFT_ENTRIES,
    }


@pytest.mark.skipif(os.name == "nt", reason="POSIX hard-link/mode matrix")
def test_posix_store_is_private_and_rejects_hard_linked_records(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    store = OperationDraftStore(state_dir)
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="f" * 64,
    )
    record_path = store.records_dir / f"{started.draft_id}.json"

    for directory in (state_dir, store.store_dir, store.records_dir, store.locks_dir):
        assert stat.S_IMODE(directory.stat().st_mode) & 0o077 == 0
    assert stat.S_IMODE(record_path.stat().st_mode) & 0o077 == 0
    assert all(
        stat.S_IMODE(path.stat().st_mode) & 0o077 == 0
        for path in store.locks_dir.iterdir()
    )

    hard_link = tmp_path / "record-hard-link.json"
    os.link(record_path, hard_link)
    with pytest.raises(OperationDraftNotAvailable):
        store.inspect(
            started.draft_id,
            task_authority=started.task_authority,
        )


def test_simulated_windows_reparse_record_is_rejected_off_host(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = OperationDraftStore(tmp_path)
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="1" * 64,
    )
    record_path = store.records_dir / f"{started.draft_id}.json"
    real_is_junction = getattr(Path, "is_junction", lambda _self: False)
    monkeypatch.setattr(
        Path,
        "is_junction",
        lambda self: self == record_path or real_is_junction(self),
        raising=False,
    )

    with pytest.raises(OperationDraftNotAvailable):
        store.inspect(
            started.draft_id,
            task_authority=started.task_authority,
        )


def test_linked_lock_fails_closed_without_modifying_external_bytes(
    tmp_path: Path,
) -> None:
    store = OperationDraftStore(tmp_path / "state")
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="2" * 64,
    )
    lock_path = store.locks_dir / "store-admission.lock"
    external = tmp_path / "external.lock"
    original = b"outside-lock"
    external.write_bytes(original)
    lock_path.unlink()
    create_symlink_or_skip(lock_path, external)

    with pytest.raises(OperationDraftStorageCorruption, match="link|reparse"):
        store.inspect(
            started.draft_id,
            task_authority=started.task_authority,
        )
    assert external.read_bytes() == original


def test_stale_crash_temp_is_removed_but_fresh_temp_is_never_promoted(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 9, tzinfo=timezone.utc)
    store = OperationDraftStore(tmp_path)
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="3" * 64,
        now=now,
    )
    record_path = store.records_dir / f"{started.draft_id}.json"
    stale = store.records_dir / f".{record_path.name}.{'a' * 16}.tmp"
    stale.write_bytes(record_path.read_bytes())
    stale.chmod(0o600)
    stale_epoch = now.timestamp() - DEFAULT_OPERATION_DRAFT_STALE_TEMP_SECONDS - 1
    os.utime(stale, (stale_epoch, stale_epoch))

    store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="3" * 64,
        now=now,
    )
    assert not stale.exists()

    fresh = store.records_dir / f".{record_path.name}.{'b' * 16}.tmp"
    fresh.write_bytes(record_path.read_bytes())
    fresh.chmod(0o600)
    fresh_epoch = now.timestamp() - DEFAULT_OPERATION_DRAFT_STALE_TEMP_SECONDS + 1
    os.utime(fresh, (fresh_epoch, fresh_epoch))
    before = record_path.read_bytes()

    store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="3" * 64,
        now=now,
    )
    assert fresh.is_file()
    assert record_path.read_bytes() == before


def test_publish_detects_post_replace_tamper_and_never_reports_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = OperationDraftStore(tmp_path)
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="4" * 64,
    )
    real_replace = draft_module.os.replace

    def replace_then_tamper(source: Path, target: Path) -> None:
        real_replace(source, target)
        target.write_bytes(target.read_bytes() + b" ")

    monkeypatch.setattr(draft_module.os, "replace", replace_then_tamper)

    with pytest.raises(OperationDraftStorageCorruption, match="changed|publish"):
        store.cancel(
            started.draft_id,
            task_authority=started.task_authority,
            expected_revision=1,
        )


def test_publish_detects_same_bytes_target_inode_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = OperationDraftStore(tmp_path)
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="4" * 64,
    )
    displaced = tmp_path / "displaced-published-record.json"
    real_replace = draft_module.os.replace

    def replace_then_substitute(source: Path, target: Path) -> None:
        real_replace(source, target)
        target.rename(displaced)
        target.write_bytes(displaced.read_bytes())
        target.chmod(0o600)

    monkeypatch.setattr(draft_module.os, "replace", replace_then_substitute)

    with pytest.raises(OperationDraftStorageCorruption, match="publish"):
        store.cancel(
            started.draft_id,
            task_authority=started.task_authority,
            expected_revision=1,
        )

    assert displaced.is_file()


def test_publish_failure_preserves_old_revision_digest_audit_and_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = OperationDraftStore(tmp_path)
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="a" * 64,
    )
    record_path = store.records_dir / f"{started.draft_id}.json"
    before = record_path.read_bytes()

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("synthetic publish failure")

    monkeypatch.setattr(draft_module.os, "replace", fail_replace)
    with pytest.raises(OperationDraftStorageCorruption, match="publish"):
        store.cancel(
            started.draft_id,
            task_authority=started.task_authority,
            expected_revision=1,
        )

    assert record_path.read_bytes() == before
    assert not list(store.records_dir.glob(".*.tmp"))
    current = store.inspect(
        started.draft_id,
        task_authority=started.task_authority,
    )
    assert current.revision == 1
    assert len(current.audit) == 1


def test_revision_publish_rejects_record_tamper_after_validated_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = OperationDraftStore(tmp_path)
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="a" * 64,
    )
    record_path = store.records_dir / f"{started.draft_id}.json"
    attacker_bytes = b"ATTACKER-BYTES"
    real_replace = draft_module._replace

    def tamper_after_load(
        path: Path,
        payload: dict[str, Any],
        *,
        expected_previous_bytes: bytes,
        expected_previous_metadata: os.stat_result,
        attest_directories: Any,
    ) -> None:
        path.write_bytes(attacker_bytes)
        real_replace(
            path,
            payload,
            expected_previous_bytes=expected_previous_bytes,
            expected_previous_metadata=expected_previous_metadata,
            attest_directories=attest_directories,
        )

    monkeypatch.setattr(draft_module, "_replace", tamper_after_load)

    with pytest.raises(OperationDraftStorageCorruption, match="changed|revision"):
        store.cancel(
            started.draft_id,
            task_authority=started.task_authority,
            expected_revision=1,
        )

    assert record_path.read_bytes() == attacker_bytes


def test_revision_publish_rejects_same_bytes_on_a_replacement_inode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = OperationDraftStore(tmp_path)
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="a" * 64,
    )
    record_path = store.records_dir / f"{started.draft_id}.json"
    original_path = tmp_path / "original-record.json"
    original_bytes = record_path.read_bytes()
    real_replace = draft_module._replace

    def replace_inode_after_load(
        path: Path,
        payload: dict[str, Any],
        *,
        expected_previous_bytes: bytes,
        expected_previous_metadata: os.stat_result,
        attest_directories: Any,
    ) -> None:
        path.rename(original_path)
        path.write_bytes(original_path.read_bytes())
        path.chmod(0o600)
        real_replace(
            path,
            payload,
            expected_previous_bytes=expected_previous_bytes,
            expected_previous_metadata=expected_previous_metadata,
            attest_directories=attest_directories,
        )

    monkeypatch.setattr(draft_module, "_replace", replace_inode_after_load)

    with pytest.raises(OperationDraftStorageCorruption, match="changed|revision"):
        store.cancel(
            started.draft_id,
            task_authority=started.task_authority,
            expected_revision=1,
        )

    assert record_path.read_bytes() == original_bytes
    assert original_path.read_bytes() == original_bytes


def test_gc_unlink_rejects_a_substitute_file_after_lifecycle_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = datetime(2026, 8, 9, tzinfo=timezone.utc)
    store = OperationDraftStore(tmp_path)
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="a" * 64,
        now=created,
    )
    store.cancel(
        started.draft_id,
        task_authority=started.task_authority,
        expected_revision=1,
        now=created + timedelta(seconds=1),
    )
    record_path = store.records_dir / f"{started.draft_id}.json"
    original_path = tmp_path / "gc-original-record.json"
    substitute_bytes = b"SUBSTITUTE-RECORD"
    real_unlink = store._unlink_managed_file
    swapped = False

    def swap_before_unlink(
        path: Path,
        *,
        label: str,
        expected_metadata: os.stat_result,
        expected_bytes: bytes | None = None,
    ) -> None:
        nonlocal swapped
        if not swapped and label == "Operation Draft record":
            swapped = True
            path.rename(original_path)
            path.write_bytes(substitute_bytes)
            path.chmod(0o600)
        real_unlink(
            path,
            label=label,
            expected_metadata=expected_metadata,
            expected_bytes=expected_bytes,
        )

    monkeypatch.setattr(store, "_unlink_managed_file", swap_before_unlink)

    with pytest.raises(OperationDraftStorageCorruption, match="identity|changed"):
        store.start(
            operation="object.set",
            version="2022.1",
            schema_digest="a" * 64,
            now=created
            + timedelta(
                seconds=DEFAULT_OPERATION_DRAFT_TERMINAL_RETENTION_SECONDS + 2
            ),
        )

    assert record_path.read_bytes() == substitute_bytes
    assert original_path.is_file()


def test_clock_rollback_cannot_publish_an_invalid_revision(
    tmp_path: Path,
) -> None:
    created = datetime(2026, 8, 9, tzinfo=timezone.utc)
    store = OperationDraftStore(tmp_path)
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="a" * 64,
        now=created,
    )
    record_path = store.records_dir / f"{started.draft_id}.json"
    before = record_path.read_bytes()

    with pytest.raises(OperationDraftStorageCorruption, match="clock|lifetime"):
        store.cancel(
            started.draft_id,
            task_authority=started.task_authority,
            expected_revision=1,
            now=created - timedelta(microseconds=1),
        )

    assert record_path.read_bytes() == before


def test_clock_rollback_before_a_later_edit_timestamp_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = datetime(2026, 8, 9, tzinfo=timezone.utc)
    store = OperationDraftStore(tmp_path)
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="a" * 64,
        now=created,
    )
    simulated_later_edit = replace(
        started.record,
        revision=2,
        updated_at=draft_module._timestamp(created + timedelta(seconds=10)),
    )
    record_path = store.records_dir / f"{started.draft_id}.json"
    simulated_loaded = draft_module._LoadedOperationDraft(
        record=simulated_later_edit,
        durable_bytes=record_path.read_bytes(),
        metadata=record_path.lstat(),
    )
    monkeypatch.setattr(
        store,
        "_load_available",
        lambda _draft_id: simulated_loaded,
    )

    with pytest.raises(OperationDraftStorageCorruption, match="clock|lifetime"):
        store.cancel(
            started.draft_id,
            task_authority=started.task_authority,
            expected_revision=2,
            now=created + timedelta(seconds=5),
        )


def test_missing_lock_backend_fails_before_draft_state_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = OperationDraftStore(tmp_path)
    monkeypatch.setattr(draft_module, "_fcntl", None)
    monkeypatch.setattr(draft_module, "_lock_platform_name", lambda: "posix")

    with pytest.raises(OperationDraftLockUnavailable, match="will not run unlocked"):
        store.start(
            operation="object.set",
            version="2022.1",
            schema_digest="5" * 64,
        )
    assert list(store.records_dir.iterdir()) == []


@pytest.mark.parametrize("platform_name", ("posix", "nt"))
def test_lock_contention_has_one_fixed_finite_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform_name: str,
) -> None:
    class ContendedFcntl:
        LOCK_EX = 1
        LOCK_UN = 2
        LOCK_NB = 4

        @staticmethod
        def flock(_descriptor: int, operation: int) -> None:
            if operation != ContendedFcntl.LOCK_UN:
                raise OSError(errno.EAGAIN, "synthetic POSIX contention")

    class EventuallyAvailableMsvcrt:
        LK_NBLCK = 1
        LK_UNLCK = 2

        def __init__(self) -> None:
            self.attempts = 0

        def locking(self, _descriptor: int, mode: int, _byte_count: int) -> None:
            if mode == self.LK_NBLCK:
                self.attempts += 1
                if self.attempts < 3:
                    raise OSError(errno.EACCES, "synthetic Windows contention")

    monotonic_values = iter(
        (0.0, float(draft_module.DEFAULT_OPERATION_DRAFT_LOCK_TIMEOUT_SECONDS))
    )
    monkeypatch.setattr(draft_module.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(draft_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(draft_module, "_lock_platform_name", lambda: platform_name)
    if platform_name == "posix":
        monkeypatch.setattr(draft_module, "_fcntl", ContendedFcntl())
    else:
        monkeypatch.setattr(draft_module, "_msvcrt", EventuallyAvailableMsvcrt())
    store = OperationDraftStore(tmp_path)

    with pytest.raises(OperationDraftLockUnavailable, match="timed out") as timeout:
        store.start(
            operation="object.set",
            version="2022.1",
            schema_digest="5" * 64,
        )

    assert timeout.value.details == {
        "timeout_seconds": draft_module.DEFAULT_OPERATION_DRAFT_LOCK_TIMEOUT_SECONDS
    }
    assert list(store.records_dir.iterdir()) == []


def test_simulated_windows_lock_uses_byte_zero_retries_contention_and_releases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeMsvcrt:
        LK_NBLCK = 1
        LK_UNLCK = 2

        def __init__(self) -> None:
            self.acquire_attempts = 0
            self.calls: list[tuple[int, int, int, int]] = []

        def locking(self, descriptor: int, mode: int, byte_count: int) -> None:
            self.calls.append(
                (
                    mode,
                    byte_count,
                    os.lseek(descriptor, 0, os.SEEK_CUR),
                    os.fstat(descriptor).st_size,
                )
            )
            if mode == self.LK_NBLCK:
                self.acquire_attempts += 1
                if self.acquire_attempts == 1:
                    raise OSError(errno.EACCES, "owned by another process")

    fake = FakeMsvcrt()
    sleeps: list[float] = []
    monkeypatch.setattr(draft_module, "_msvcrt", fake)
    monkeypatch.setattr(draft_module, "_lock_platform_name", lambda: "nt")
    monkeypatch.setattr(draft_module.time, "sleep", sleeps.append)
    store = OperationDraftStore(tmp_path)

    store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="6" * 64,
    )

    assert fake.calls == [
        (fake.LK_NBLCK, 1, 0, 0),
        (fake.LK_NBLCK, 1, 0, 0),
        (fake.LK_UNLCK, 1, 0, 0),
    ]
    assert sleeps == [draft_module._WINDOWS_LOCK_RETRY_SECONDS]
    assert (store.locks_dir / "store-admission.lock").read_bytes() == b""


def test_simulated_windows_non_contention_lock_error_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeMsvcrt:
        LK_NBLCK = 1
        LK_UNLCK = 2

        @staticmethod
        def locking(_descriptor: int, mode: int, _byte_count: int) -> None:
            if mode == FakeMsvcrt.LK_NBLCK:
                raise OSError(errno.EBADF, "invalid lock handle")

    monkeypatch.setattr(draft_module, "_msvcrt", FakeMsvcrt())
    monkeypatch.setattr(draft_module, "_lock_platform_name", lambda: "nt")
    store = OperationDraftStore(tmp_path)

    with pytest.raises(OperationDraftLockUnavailable, match="msvcrt.locking"):
        store.start(
            operation="object.set",
            version="2022.1",
            schema_digest="7" * 64,
        )


def test_release_failure_cannot_turn_a_committed_revision_into_a_false_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CloseFallbackBackend:
        @staticmethod
        def acquire(_handle: Any) -> None:
            return None

        @staticmethod
        def release(_handle: Any) -> None:
            raise OperationDraftLockUnavailable("synthetic explicit unlock failure")

    store = OperationDraftStore(tmp_path)
    monkeypatch.setattr(
        draft_module,
        "_select_lock_backend",
        lambda _platform_name: CloseFallbackBackend(),
    )

    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest="7" * 64,
    )
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
