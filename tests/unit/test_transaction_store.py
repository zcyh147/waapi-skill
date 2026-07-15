from __future__ import annotations

import json
import math
import multiprocessing
import os
from pathlib import Path
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.canonical import canonical_json, canonical_json_bytes, canonical_sha256, sha256_hex
from wwise_waapi.transactions import (
    ArtifactIntegrityError,
    FileLockUnavailable,
    InvalidTransition,
    PreviewAlreadyExists,
    StateConflict,
    StateCorruptionError,
    StateDirectoryNotConfigured,
    TransactionNotFound,
    TransactionState,
    TransactionStore,
    UnsafeTransactionId,
    resolve_state_directory,
)


def _race_transition(state_dir: str, transaction_id: str, target: str, ready: Any, results: Any) -> None:
    store = TransactionStore(Path(state_dir))
    ready.wait(timeout=5)
    try:
        record = store.transition(transaction_id, target)
    except InvalidTransition:
        results.put(("rejected", target))
    else:
        results.put(("committed", record.state.value))


def _preview_path(state_dir: Path, transaction_id: str) -> Path:
    return state_dir / "transactions" / transaction_id / "preview.json"


def _state_path(state_dir: Path, transaction_id: str) -> Path:
    return state_dir / "transactions" / transaction_id / "state.json"


def test_canonical_json_and_sha256_contract() -> None:
    left = {"z": "音频", "a": [3, {"b": True}]}
    right = {"a": [3, {"b": True}], "z": "音频"}

    assert canonical_json(left) == '{"a":[3,{"b":true}],"z":"音频"}'
    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert canonical_sha256(left) == canonical_sha256(right)
    assert sha256_hex(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    with pytest.raises(ValueError, match="Out of range float values"):
        canonical_json({"bad": math.nan})
    with pytest.raises(TypeError, match="must be bytes"):
        sha256_hex("abc")  # type: ignore[arg-type]


def test_state_directory_uses_explicit_path_then_environment(tmp_path, monkeypatch) -> None:
    environment_path = tmp_path / "from-env"
    monkeypatch.setenv("WAAPI_SKILL_STATE_DIR", str(environment_path))

    assert resolve_state_directory() == environment_path.resolve()
    assert resolve_state_directory(tmp_path / "explicit") == (tmp_path / "explicit").resolve()
    with pytest.raises(TypeError, match="pathlib.Path"):
        resolve_state_directory(str(tmp_path))  # type: ignore[arg-type]

    monkeypatch.delenv("WAAPI_SKILL_STATE_DIR")
    with pytest.raises(StateDirectoryNotConfigured, match="WAAPI_SKILL_STATE_DIR"):
        resolve_state_directory()


@pytest.mark.parametrize(
    "transaction_id",
    ["", ".hidden", "../escape", "a/b", r"a\\b", "space id", "é", "a" * 129],
)
def test_transaction_ids_cannot_escape_state_root(tmp_path, transaction_id) -> None:
    store = TransactionStore(tmp_path)

    with pytest.raises(UnsafeTransactionId):
        store.create_preview(transaction_id, {"plan": []})


def test_preview_is_atomic_write_once_and_events_are_canonical_jsonl(tmp_path) -> None:
    store = TransactionStore(tmp_path)
    artifact = {"steps": [{"api": "ak.wwise.core.object.setName", "name": "风"}], "version": "2025.1"}

    record = store.create_preview("tx-001", artifact)
    preview = store.load_preview("tx-001")
    events = store.read_events("tx-001")

    assert record.state is TransactionState.DRAFT
    assert preview.artifact == artifact
    assert preview.artifact_hash == canonical_sha256(artifact)
    assert events[0]["event_type"] == "preview_created"
    assert events[0]["to_state"] == "draft"
    assert events[0]["event_hash"] == record.last_event_hash
    event_line = (tmp_path / "transactions" / "tx-001" / "events.jsonl").read_bytes()
    assert event_line == canonical_json_bytes(events[0]) + b"\n"
    assert not list((tmp_path / "transactions").glob("*.tmp"))
    assert not list((tmp_path / "transactions" / "tx-001").glob("*.tmp"))

    with pytest.raises(PreviewAlreadyExists, match="immutable"):
        store.create_preview("tx-001", {"replacement": True})
    assert store.load_preview("tx-001").artifact == artifact


def test_full_confirm_execute_verify_state_machine(tmp_path) -> None:
    store = TransactionStore(tmp_path)
    created = store.create_preview("tx-verified", {"operation": "rename", "target": "{GUID}"})

    assert store.submit_for_confirmation("tx-verified").state is TransactionState.AWAITING_CONFIRMATION
    assert store.confirm("tx-verified", artifact_hash=created.artifact_hash).state is TransactionState.CONFIRMED
    assert store.begin_execution("tx-verified").state is TransactionState.EXECUTING
    assert store.mark_executed_unverified("tx-verified").state is TransactionState.EXECUTED_UNVERIFIED
    final = store.record_verification(
        "tx-verified", "verified", details={"readback": {"name": "NewName"}}
    )

    assert final.state is TransactionState.VERIFIED
    assert final.event_sequence == 6
    events = store.read_events("tx-verified")
    assert [event["to_state"] for event in events] == [
        "draft",
        "awaiting_confirmation",
        "confirmed",
        "executing",
        "executed_unverified",
        "verified",
    ]
    assert events[-1]["details"] == {"readback": {"name": "NewName"}}


def test_execution_result_can_be_recovered_from_hash_chained_journal(tmp_path) -> None:
    store = TransactionStore(tmp_path)
    created = store.create_preview("tx-result", {"operation": "object.create"})
    store.submit_for_confirmation("tx-result")
    store.confirm("tx-result", artifact_hash=created.artifact_hash)
    store.begin_execution("tx-result")
    store.mark_executed_unverified(
        "tx-result",
        details={"dispatch_result": {"id": "{created-guid}"}, "attempt": 1},
    )

    execution_event = store.read_events("tx-result")[-1]

    assert execution_event["event_type"] == "execution_completed"
    assert execution_event["details"] == {
        "attempt": 1,
        "dispatch_result": {"id": "{created-guid}"},
    }


@pytest.mark.parametrize(
    "outcome",
    [
        TransactionState.VERIFICATION_FAILED,
        TransactionState.INDETERMINATE,
        TransactionState.REPREVIEW_REQUIRED,
    ],
)
def test_post_execution_verification_branches_are_closed(tmp_path, outcome) -> None:
    store = TransactionStore(tmp_path)
    transaction_id = f"tx-{outcome.value}"
    created = store.create_preview(transaction_id, {"outcome": outcome.value})
    store.submit_for_confirmation(transaction_id)
    store.confirm(transaction_id, artifact_hash=created.artifact_hash)
    store.begin_execution(transaction_id)
    store.mark_executed_unverified(transaction_id)

    assert store.record_verification(transaction_id, outcome).state is outcome
    with pytest.raises(InvalidTransition, match="terminal"):
        store.transition(transaction_id, TransactionState.VERIFIED)


def test_rejected_indeterminate_and_repreview_paths(tmp_path) -> None:
    store = TransactionStore(tmp_path)

    store.create_preview("tx-rejected", {"x": 1})
    store.submit_for_confirmation("tx-rejected")
    assert store.reject("tx-rejected", details={"reason": "user"}).state is TransactionState.REJECTED

    created = store.create_preview("tx-indeterminate", {"x": 2})
    store.submit_for_confirmation("tx-indeterminate")
    store.confirm("tx-indeterminate", artifact_hash=created.artifact_hash)
    store.begin_execution("tx-indeterminate")
    assert store.mark_execution_indeterminate("tx-indeterminate").state is TransactionState.INDETERMINATE

    created = store.create_preview("tx-repreview", {"x": 3})
    store.submit_for_confirmation("tx-repreview")
    store.confirm("tx-repreview", artifact_hash=created.artifact_hash)
    assert store.require_repreview("tx-repreview").state is TransactionState.REPREVIEW_REQUIRED


def test_illegal_transitions_expected_state_and_confirmation_hash_are_rejected(tmp_path) -> None:
    store = TransactionStore(tmp_path)
    created = store.create_preview("tx-guarded", {"steps": [1]})

    with pytest.raises(InvalidTransition, match="draft.*executing"):
        store.transition("tx-guarded", "executing")
    with pytest.raises(StateConflict, match="caller expected"):
        store.transition("tx-guarded", "awaiting_confirmation", expected_state="confirmed")
    store.submit_for_confirmation("tx-guarded")
    with pytest.raises(ArtifactIntegrityError, match="does not match"):
        store.confirm("tx-guarded", artifact_hash="0" * 64)
    assert store.load("tx-guarded").state is TransactionState.AWAITING_CONFIRMATION
    assert store.confirm("tx-guarded", artifact_hash=created.artifact_hash).state is TransactionState.CONFIRMED

    with pytest.raises(InvalidTransition, match="verification outcome"):
        store.record_verification("tx-guarded", "executing")


def test_transition_input_validation_is_explicit(tmp_path) -> None:
    store = TransactionStore(tmp_path)
    store.create_preview("tx-inputs", {"steps": []})

    with pytest.raises(InvalidTransition, match="recognized transaction state"):
        store.transition("tx-inputs", "not-a-state")
    with pytest.raises(ValueError, match="event_type"):
        store.transition("tx-inputs", "awaiting_confirmation", event_type="")
    with pytest.raises(TypeError, match="expected_artifact_hash"):
        store.transition("tx-inputs", "awaiting_confirmation", expected_artifact_hash=42)  # type: ignore[arg-type]
    store.submit_for_confirmation("tx-inputs")
    with pytest.raises(ValueError, match="artifact_hash"):
        store.confirm("tx-inputs", artifact_hash="")


def test_preview_artifact_tampering_is_detected_before_transition(tmp_path) -> None:
    store = TransactionStore(tmp_path)
    store.create_preview("tx-tampered", {"target": "Original"})
    store.submit_for_confirmation("tx-tampered")
    preview_path = _preview_path(tmp_path, "tx-tampered")
    payload = json.loads(preview_path.read_text(encoding="utf-8"))
    payload["artifact"]["target"] = "Injected"
    preview_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ArtifactIntegrityError, match="hash mismatch"):
        store.verify_artifact("tx-tampered")
    with pytest.raises(ArtifactIntegrityError, match="hash mismatch"):
        store.transition("tx-tampered", "confirmed")


@pytest.mark.parametrize(
    ("field", "replacement", "error_type", "message"),
    [
        ("schema_version", 999, StateCorruptionError, "Unsupported preview schema"),
        ("transaction_id", "tx-other", ArtifactIntegrityError, "transaction id mismatch"),
        ("artifact", None, StateCorruptionError, "artifact fields are missing"),
        ("created_at", "", StateCorruptionError, "created_at is missing"),
    ],
)
def test_malformed_preview_envelopes_fail_closed(tmp_path, field, replacement, error_type, message) -> None:
    store = TransactionStore(tmp_path)
    transaction_id = f"tx-preview-{field}"
    store.create_preview(transaction_id, {"safe": True})
    path = _preview_path(tmp_path, transaction_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if field == "artifact":
        del payload[field]
    else:
        payload[field] = replacement
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(error_type, match=message):
        store.load_preview(transaction_id)


@pytest.mark.parametrize(
    ("field", "replacement", "error_type", "message"),
    [
        ("schema_version", 999, StateCorruptionError, "Unsupported transaction state schema"),
        ("transaction_id", "tx-other", StateCorruptionError, "state id"),
        ("state", "unknown", StateCorruptionError, "recognized transaction state"),
        ("artifact_hash", "0" * 64, ArtifactIntegrityError, "does not match preview"),
        ("created_at", "", StateCorruptionError, "created_at is missing"),
        ("updated_at", "", StateCorruptionError, "updated_at is missing"),
        ("event_sequence", True, StateCorruptionError, "positive integer"),
        ("last_event_hash", "", StateCorruptionError, "last_event_hash is missing"),
    ],
)
def test_malformed_state_envelopes_fail_closed(tmp_path, field, replacement, error_type, message) -> None:
    store = TransactionStore(tmp_path)
    transaction_id = f"tx-state-{field.replace('_', '-')}"
    store.create_preview(transaction_id, {"safe": True})
    path = _state_path(tmp_path, transaction_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[field] = replacement
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(error_type, match=message):
        store.load(transaction_id)


def test_event_journal_tampering_is_detected(tmp_path) -> None:
    store = TransactionStore(tmp_path)
    store.create_preview("tx-event-tampered", {"safe": True})
    store.submit_for_confirmation("tx-event-tampered")
    events_path = tmp_path / "transactions" / "tx-event-tampered" / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    events[-1]["details"] = {"injected": True}
    events_path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")

    with pytest.raises(StateCorruptionError, match="Event hash mismatch"):
        store.load("tx-event-tampered")


@pytest.mark.parametrize(
    ("raw_events", "message"),
    [("\n", "Blank event"), ("{\n", "Invalid event JSON"), ("[]\n", "Event must be an object")],
)
def test_malformed_event_jsonl_fails_closed(tmp_path, raw_events, message) -> None:
    store = TransactionStore(tmp_path)
    store.create_preview("tx-bad-events", {"safe": True})
    path = tmp_path / "transactions" / "tx-bad-events" / "events.jsonl"
    path.write_text(raw_events, encoding="utf-8")

    with pytest.raises(StateCorruptionError, match=message):
        store.read_events("tx-bad-events")


def test_missing_artifact_files_report_transaction_not_found(tmp_path) -> None:
    store = TransactionStore(tmp_path)
    with pytest.raises(TransactionNotFound, match="does not exist"):
        store.load("tx-missing")

    store.create_preview("tx-missing-events", {"safe": True})
    (tmp_path / "transactions" / "tx-missing-events" / "events.jsonl").unlink()
    with pytest.raises(TransactionNotFound, match="no events"):
        store.read_events("tx-missing-events")


def test_symlinked_store_components_fail_closed(tmp_path) -> None:
    external = tmp_path / "external"
    external.mkdir()
    state_with_link = tmp_path / "linked-store"
    state_with_link.mkdir()
    (state_with_link / "transactions").symlink_to(external, target_is_directory=True)
    with pytest.raises(StateCorruptionError, match="Store directory cannot be a symlink"):
        TransactionStore(state_with_link)

    store = TransactionStore(tmp_path / "normal-store")
    (store.locks_dir / "tx-lock-link.lock").symlink_to(external / "lock")
    with pytest.raises(StateCorruptionError, match="lock cannot be a symlink"):
        store.create_preview("tx-lock-link", {"safe": True})

    (store.transactions_dir / "tx-dir-link").symlink_to(external, target_is_directory=True)
    with pytest.raises(StateCorruptionError, match="directory cannot be a symlink"):
        store.create_preview("tx-dir-link", {"safe": True})


@pytest.mark.skipif(os.name == "nt", reason="fcntl race test is POSIX-only")
def test_fcntl_lock_serializes_cross_process_state_race(tmp_path) -> None:
    store = TransactionStore(tmp_path)
    store.create_preview("tx-race", {"race": True})
    store.submit_for_confirmation("tx-race")
    context = multiprocessing.get_context("fork")
    ready = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_race_transition,
            args=(str(tmp_path), "tx-race", target, ready, results),
        )
        for target in ("confirmed", "rejected")
    ]
    for process in processes:
        process.start()
    ready.set()
    outcomes = [results.get(timeout=10) for _ in processes]
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    assert sorted(result[0] for result in outcomes) == ["committed", "rejected"]
    assert store.load("tx-race").state.value in {"confirmed", "rejected"}
    assert len(store.read_events("tx-race")) == 3


def test_missing_fcntl_fails_closed_with_windows_boundary_message(tmp_path, monkeypatch) -> None:
    import wwise_waapi.transactions as transactions

    store = TransactionStore(tmp_path)
    monkeypatch.setattr(transactions, "_fcntl", None)

    with pytest.raises(FileLockUnavailable, match="macOS/Linux.*Windows"):
        store.create_preview("tx-no-lock", {"unsafe": False})


def test_journal_ahead_state_is_repaired_after_interrupted_materialization(tmp_path) -> None:
    store = TransactionStore(tmp_path)
    store.create_preview("tx-repair", {"repair": True})
    store.submit_for_confirmation("tx-repair")
    durable_after_submit = json.loads(_state_path(tmp_path, "tx-repair").read_text(encoding="utf-8"))

    created_state = dict(durable_after_submit)
    first_event = store.read_events("tx-repair")[0]
    created_state.update(
        {
            "event_sequence": 1,
            "last_event_hash": first_event["event_hash"],
            "state": "draft",
            "updated_at": first_event["timestamp"],
        }
    )
    _state_path(tmp_path, "tx-repair").write_text(json.dumps(created_state), encoding="utf-8")

    repaired = store.load("tx-repair")

    assert repaired.state is TransactionState.AWAITING_CONFIRMATION
    assert repaired.event_sequence == 2
    assert json.loads(_state_path(tmp_path, "tx-repair").read_text(encoding="utf-8"))["state"] == "awaiting_confirmation"
