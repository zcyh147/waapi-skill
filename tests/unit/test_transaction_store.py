from __future__ import annotations

import errno
import json
import math
import multiprocessing
import os
from pathlib import Path
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

import wwise_waapi.transactions as transaction_module
from tests.support.platform_filesystem import create_symlink_or_skip
from wwise_waapi.canonical import canonical_json, canonical_json_bytes, canonical_sha256, sha256_hex
from wwise_waapi.transactions import (
    ArtifactIntegrityError,
    ConfirmationTokenMismatch,
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
    confirmation_token_for,
    new_transaction_id,
    resolve_state_directory,
    validate_confirmation_token,
    validate_transaction_id,
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


def _race_draft_authorization(
    state_dir: str,
    transaction_id: str,
    mode: str,
    ready: Any,
    results: Any,
) -> None:
    store = TransactionStore(Path(state_dir))
    ready.wait(timeout=5)
    try:
        if mode == "policy":
            record = store.authorize_by_policy(
                transaction_id,
                policy="allow_changes",
                authority="caller_asserted_current_user_imperative",
            )
        else:
            record = store.submit_for_confirmation(transaction_id)
    except (InvalidTransition, StateConflict):
        results.put(("rejected", mode))
    else:
        results.put(("committed", record.state.value))


def _race_create_preview(
    state_dir: str,
    transaction_id: str,
    contender: str,
    ready: Any,
    results: Any,
) -> None:
    store = TransactionStore(Path(state_dir))
    if not ready.wait(timeout=5):
        results.put(
            ("unexpected", contender, "TimeoutError", "start signal was not received")
        )
        return
    try:
        record = store.create_preview(transaction_id, {"contender": contender})
    except PreviewAlreadyExists:
        results.put(("already_exists", contender))
    except BaseException as exc:
        results.put(("unexpected", contender, type(exc).__name__, str(exc)))
    else:
        results.put(("created", contender, record.state.value))


def _cross_process_context() -> multiprocessing.context.BaseContext:
    return multiprocessing.get_context("spawn" if os.name == "nt" else "fork")


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


@pytest.mark.parametrize(
    ("random_value", "encoded"),
    [
        (0, "0" * 20),
        (1, ("0" * 19) + "1"),
        ((1 << 100) - 1, "z" * 20),
    ],
)
def test_new_transaction_id_uses_exact_100_bit_crockford_encoding(
    monkeypatch,
    random_value: int,
    encoded: str,
) -> None:
    requested_bits: list[int] = []

    def fake_randbits(bits: int) -> int:
        requested_bits.append(bits)
        return random_value

    monkeypatch.setattr(transaction_module.secrets, "randbits", fake_randbits)

    transaction_id = new_transaction_id()

    assert transaction_id == f"tx1-{encoded}"
    assert requested_bits == [100]
    assert validate_transaction_id(transaction_id) == transaction_id


@pytest.mark.parametrize(
    "transaction_id",
    [
        "tx1-",
        f"tx1-{'0' * 19}",
        f"tx1-{'0' * 21}",
        "tx1-0123456789ABCDEFGHJK",
        f"tx1-{'0' * 19}i",
        f"tx1-{'0' * 19}u",
        f"tx1-{'0' * 19}-",
    ],
)
def test_malformed_tx1_ids_are_rejected_before_creating_a_lock(
    tmp_path,
    transaction_id: str,
) -> None:
    store = TransactionStore(tmp_path)

    with pytest.raises(UnsafeTransactionId, match="tx1"):
        store.load(transaction_id)

    assert list(store.locks_dir.iterdir()) == []


def test_legacy_transaction_ids_remain_compatible(tmp_path) -> None:
    legacy_transaction_id = f"tx-{'a' * 32}"
    store = TransactionStore(tmp_path)

    record = store.create_preview(legacy_transaction_id, {"legacy": True})

    assert validate_transaction_id(legacy_transaction_id) == legacy_transaction_id
    assert store.load(legacy_transaction_id) == record


def test_confirmation_token_has_stable_120_bit_crockford_contract() -> None:
    token = confirmation_token_for(
        transaction_id=f"tx1-{'0' * 20}",
        artifact_hash="a" * 64,
        state=TransactionState.AWAITING_CONFIRMATION,
        event_sequence=2,
        last_event_hash="b" * 64,
    )

    assert token == "ct1-wxjn6v2daavzssxm2x59pe24"
    assert validate_confirmation_token(token) == token


@pytest.mark.parametrize(
    "confirmation_token",
    [
        "ct1-",
        f"ct1-{'0' * 23}",
        f"ct1-{'0' * 25}",
        f"ct1-{'0' * 23}i",
        f"ct1-{'0' * 23}u",
        f"ct1-{'0' * 23}-",
        f"ct1-{'A' * 24}",
        f"ct2-{'0' * 24}",
    ],
)
def test_malformed_confirmation_tokens_are_rejected_before_locking(
    tmp_path: Path,
    confirmation_token: str,
) -> None:
    store = TransactionStore(tmp_path)

    with pytest.raises(ConfirmationTokenMismatch, match="ct1"):
        store.confirm("tx-never-created", confirmation_token=confirmation_token)

    assert list(store.locks_dir.iterdir()) == []


def test_confirmation_token_binds_every_durable_material_field() -> None:
    base = {
        "transaction_id": f"tx1-{'0' * 20}",
        "artifact_hash": "a" * 64,
        "state": TransactionState.AWAITING_CONFIRMATION,
        "event_sequence": 2,
        "last_event_hash": "b" * 64,
    }
    original = confirmation_token_for(**base)
    variants = (
        {**base, "transaction_id": f"tx1-{'1' * 20}"},
        {**base, "artifact_hash": "c" * 64},
        {**base, "event_sequence": 3},
        {**base, "last_event_hash": "d" * 64},
    )

    assert all(confirmation_token_for(**variant) != original for variant in variants)
    with pytest.raises(StateConflict, match="awaiting confirmation"):
        confirmation_token_for(
            **{**base, "state": TransactionState.CONFIRMED}
        )


def test_atomic_snapshot_token_confirms_once_and_replay_fails_closed(
    tmp_path: Path,
) -> None:
    store = TransactionStore(tmp_path)
    transaction_id = "tx-token-once"
    created = store.create_preview(transaction_id, {"operation": "rename"})
    awaiting = store.submit_for_confirmation(transaction_id)

    snapshot = store.load_snapshot(transaction_id)

    assert snapshot.preview.artifact_hash == created.artifact_hash
    assert snapshot.record == awaiting
    assert snapshot.events[-1]["event_hash"] == awaiting.last_event_hash
    assert snapshot.confirmation_token is not None
    assert validate_confirmation_token(snapshot.confirmation_token) == (
        snapshot.confirmation_token
    )
    confirmed = store.confirm(
        transaction_id,
        confirmation_token=snapshot.confirmation_token,
    )
    assert confirmed.state is TransactionState.CONFIRMED
    with pytest.raises(StateConflict, match="caller expected"):
        store.confirm(
            transaction_id,
            confirmation_token=snapshot.confirmation_token,
        )
    assert len(store.read_events(transaction_id)) == 3


def test_confirmation_token_mismatch_and_cross_transaction_use_do_not_mutate(
    tmp_path: Path,
) -> None:
    store = TransactionStore(tmp_path)
    transaction_ids = ("tx-token-a", "tx-token-b")
    for transaction_id in transaction_ids:
        store.create_preview(transaction_id, {"transaction": transaction_id})
        store.submit_for_confirmation(transaction_id)
    token_a = store.load_snapshot(transaction_ids[0]).confirmation_token
    token_b = store.load_snapshot(transaction_ids[1]).confirmation_token
    assert token_a is not None and token_b is not None and token_a != token_b
    wrong_character = "0" if token_a[-1] != "0" else "1"
    mistyped_token = f"{token_a[:-1]}{wrong_character}"

    for transaction_id, token in (
        (transaction_ids[0], mistyped_token),
        (transaction_ids[0], token_b),
    ):
        with pytest.raises(ConfirmationTokenMismatch, match="does not match"):
            store.confirm(transaction_id, confirmation_token=token)
        assert (
            store.load(transaction_id).state
            is TransactionState.AWAITING_CONFIRMATION
        )
        assert len(store.read_events(transaction_id)) == 2


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
    assert (
        store.begin_execution(
            "tx-verified",
            expected_authorization=TransactionState.CONFIRMED,
        ).state
        is TransactionState.EXECUTING
    )
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


def test_policy_authorized_execute_verify_state_machine_and_journal(tmp_path) -> None:
    store = TransactionStore(tmp_path)
    created = store.create_preview(
        "tx-policy-authorized",
        {"operation": "object.setNotes"},
    )

    authorized = store.authorize_by_policy(
        "tx-policy-authorized",
        policy="allow_changes",
        authority="caller_asserted_current_user_imperative",
    )
    snapshot = store.load_snapshot("tx-policy-authorized")

    assert authorized.state is TransactionState.POLICY_AUTHORIZED
    assert snapshot.confirmation_token is None
    authorization_event = snapshot.events[-1]
    assert authorization_event["event_type"] == "policy_authorized"
    assert authorization_event["from_state"] == "draft"
    assert authorization_event["to_state"] == "policy_authorized"
    assert authorization_event["artifact_hash"] == created.artifact_hash
    assert authorization_event["previous_event_hash"] == snapshot.events[0]["event_hash"]
    assert authorization_event["event_hash"] == authorized.last_event_hash
    assert authorization_event["details"] == {
        "authority": "caller_asserted_current_user_imperative",
        "explicit_confirmation": False,
        "policy": "allow_changes",
    }

    executing = store.begin_execution(
        "tx-policy-authorized",
        expected_authorization=TransactionState.POLICY_AUTHORIZED,
    )
    assert executing.state is TransactionState.EXECUTING
    assert store.mark_executed_unverified(
        "tx-policy-authorized"
    ).state is TransactionState.EXECUTED_UNVERIFIED
    final = store.record_verification("tx-policy-authorized", "verified")

    assert final.state is TransactionState.VERIFIED
    events = store.read_events("tx-policy-authorized")
    assert [event["to_state"] for event in events] == [
        "draft",
        "policy_authorized",
        "executing",
        "executed_unverified",
        "verified",
    ]
    assert events[2]["from_state"] == "policy_authorized"


@pytest.mark.parametrize(
    ("field", "value", "error_type"),
    [
        ("policy", None, TypeError),
        ("policy", "", ValueError),
        ("policy", "   ", ValueError),
        ("authority", 7, TypeError),
        ("authority", "", ValueError),
        ("authority", "\t", ValueError),
    ],
)
def test_policy_authorization_requires_non_empty_string_evidence(
    tmp_path,
    field,
    value,
    error_type,
) -> None:
    store = TransactionStore(tmp_path)
    store.create_preview("tx-policy-input", {"operation": "object.setNotes"})
    arguments = {
        "policy": "allow_changes",
        "authority": "caller_asserted_current_user_imperative",
    }
    arguments[field] = value

    with pytest.raises(error_type, match=field):
        store.authorize_by_policy("tx-policy-input", **arguments)

    assert store.load("tx-policy-input").state is TransactionState.DRAFT
    assert len(store.read_events("tx-policy-input")) == 1


def test_execution_requires_one_explicit_matching_authorization_state(tmp_path) -> None:
    store = TransactionStore(tmp_path)
    confirmed = store.create_preview("tx-confirmed-auth", {"mode": "confirm"})
    store.submit_for_confirmation("tx-confirmed-auth")
    store.confirm("tx-confirmed-auth", artifact_hash=confirmed.artifact_hash)

    with pytest.raises(TypeError, match="expected_authorization"):
        store.begin_execution("tx-confirmed-auth")  # type: ignore[call-arg]
    with pytest.raises(InvalidTransition, match="confirmed.*policy_authorized"):
        store.begin_execution(
            "tx-confirmed-auth",
            expected_authorization=TransactionState.DRAFT,
        )
    with pytest.raises(StateConflict, match="caller expected 'policy_authorized'"):
        store.begin_execution(
            "tx-confirmed-auth",
            expected_authorization=TransactionState.POLICY_AUTHORIZED,
        )
    assert (
        store.begin_execution(
            "tx-confirmed-auth",
            expected_authorization=TransactionState.CONFIRMED,
        ).state
        is TransactionState.EXECUTING
    )

    policy = store.create_preview("tx-policy-auth", {"mode": "policy"})
    store.authorize_by_policy(
        "tx-policy-auth",
        policy="allow_changes",
        authority="caller_asserted_current_user_imperative",
    )
    with pytest.raises(StateConflict, match="caller expected 'confirmed'"):
        store.begin_execution(
            "tx-policy-auth",
            expected_authorization=TransactionState.CONFIRMED,
        )
    with pytest.raises(StateConflict, match="caller expected 'awaiting_confirmation'"):
        store.confirm("tx-policy-auth", artifact_hash=policy.artifact_hash)
    assert (
        store.begin_execution(
            "tx-policy-auth",
            expected_authorization=TransactionState.POLICY_AUTHORIZED,
        ).state
        is TransactionState.EXECUTING
    )


def test_policy_authorized_transaction_can_require_repreview(tmp_path) -> None:
    store = TransactionStore(tmp_path)
    store.create_preview("tx-policy-repreview", {"operation": "object.create"})
    store.authorize_by_policy(
        "tx-policy-repreview",
        policy="allow_changes",
        authority="caller_asserted_current_user_imperative",
    )

    record = store.require_repreview(
        "tx-policy-repreview",
        expected_authorization=TransactionState.POLICY_AUTHORIZED,
        details={"reason": "policy changed before dispatch"},
    )

    assert record.state is TransactionState.REPREVIEW_REQUIRED
    assert store.read_events("tx-policy-repreview")[-1]["details"] == {
        "reason": "policy changed before dispatch"
    }


def test_execution_result_can_be_recovered_from_hash_chained_journal(tmp_path) -> None:
    store = TransactionStore(tmp_path)
    created = store.create_preview("tx-result", {"operation": "object.create"})
    store.submit_for_confirmation("tx-result")
    store.confirm("tx-result", artifact_hash=created.artifact_hash)
    store.begin_execution(
        "tx-result",
        expected_authorization=TransactionState.CONFIRMED,
    )
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


def test_result_schema_checked_is_a_distinct_terminal_success_state(tmp_path) -> None:
    store = TransactionStore(tmp_path)
    created = store.create_preview("tx-schema", {"operation": "waapi.call"})
    store.submit_for_confirmation("tx-schema")
    store.confirm("tx-schema", artifact_hash=created.artifact_hash)
    store.begin_execution(
        "tx-schema",
        expected_authorization=TransactionState.CONFIRMED,
    )
    store.mark_executed_unverified("tx-schema")

    final = store.record_verification(
        "tx-schema",
        TransactionState.RESULT_SCHEMA_CHECKED,
        details={"verification_strength": "partial_reflected_schema"},
    )

    assert final.state is TransactionState.RESULT_SCHEMA_CHECKED
    assert store.read_events("tx-schema")[-1]["to_state"] == "result_schema_checked"
    with pytest.raises(InvalidTransition, match="terminal"):
        store.transition("tx-schema", TransactionState.VERIFIED)


def test_execution_cancelled_is_a_truthful_terminal_non_verification_state(tmp_path) -> None:
    store = TransactionStore(tmp_path)
    created = store.create_preview("tx-cancelled", {"operation": "waapi.undoGroup"})
    store.submit_for_confirmation("tx-cancelled")
    store.confirm("tx-cancelled", artifact_hash=created.artifact_hash)
    store.begin_execution(
        "tx-cancelled",
        expected_authorization=TransactionState.CONFIRMED,
    )

    final = store.mark_execution_cancelled(
        "tx-cancelled",
        details={"rollback_verified": False, "automatic_retry": False},
    )

    assert final.state is TransactionState.EXECUTION_CANCELLED
    event = store.read_events("tx-cancelled")[-1]
    assert event["event_type"] == "execution_cancelled"
    assert event["details"]["rollback_verified"] is False
    with pytest.raises(InvalidTransition, match="terminal"):
        store.transition("tx-cancelled", TransactionState.EXECUTING)


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
    store.begin_execution(
        transaction_id,
        expected_authorization=TransactionState.CONFIRMED,
    )
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
    store.begin_execution(
        "tx-indeterminate",
        expected_authorization=TransactionState.CONFIRMED,
    )
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
    with pytest.raises(ValueError, match="exactly one"):
        store.confirm("tx-inputs")
    with pytest.raises(ValueError, match="exactly one"):
        store.confirm(
            "tx-inputs",
            artifact_hash="a" * 64,
            confirmation_token=f"ct1-{'0' * 24}",
        )


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


def test_policy_authorization_evidence_is_bound_by_the_event_hash(tmp_path) -> None:
    store = TransactionStore(tmp_path)
    store.create_preview("tx-policy-event-tampered", {"safe": True})
    store.authorize_by_policy(
        "tx-policy-event-tampered",
        policy="allow_changes",
        authority="caller_asserted_current_user_imperative",
    )
    events_path = (
        tmp_path
        / "transactions"
        / "tx-policy-event-tampered"
        / "events.jsonl"
    )
    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
    ]
    events[-1]["details"]["authority"] = "injected"
    events_path.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(StateCorruptionError, match="Event hash mismatch"):
        store.load("tx-policy-event-tampered")


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
    create_symlink_or_skip(
        state_with_link / "transactions",
        external,
        target_is_directory=True,
    )
    with pytest.raises(StateCorruptionError, match="Store directory cannot be a symlink"):
        TransactionStore(state_with_link)

    store = TransactionStore(tmp_path / "normal-store")
    create_symlink_or_skip(store.locks_dir / "tx-lock-link.lock", external / "lock")
    with pytest.raises(StateCorruptionError, match="lock cannot be a symlink"):
        store.create_preview("tx-lock-link", {"safe": True})

    create_symlink_or_skip(
        store.transactions_dir / "tx-dir-link",
        external,
        target_is_directory=True,
    )
    with pytest.raises(StateCorruptionError, match="directory cannot be a symlink"):
        store.create_preview("tx-dir-link", {"safe": True})


def test_platform_lock_serializes_cross_process_state_race(tmp_path) -> None:
    store = TransactionStore(tmp_path)
    store.create_preview("tx-race", {"race": True})
    store.submit_for_confirmation("tx-race")
    context = _cross_process_context()
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


def test_platform_lock_serializes_competing_draft_authorization_paths(tmp_path) -> None:
    store = TransactionStore(tmp_path)
    store.create_preview("tx-authorization-race", {"race": True})
    context = _cross_process_context()
    ready = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_race_draft_authorization,
            args=(
                str(tmp_path),
                "tx-authorization-race",
                mode,
                ready,
                results,
            ),
        )
        for mode in ("confirmation", "policy")
    ]
    for process in processes:
        process.start()
    ready.set()
    outcomes = [results.get(timeout=10) for _ in processes]
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    assert sorted(result[0] for result in outcomes) == ["committed", "rejected"]
    record = store.load("tx-authorization-race")
    assert record.state in {
        TransactionState.AWAITING_CONFIRMATION,
        TransactionState.POLICY_AUTHORIZED,
    }
    events = store.read_events("tx-authorization-race")
    assert len(events) == 2
    assert events[-1]["event_type"] in {
        "confirmation_requested",
        "policy_authorized",
    }


def test_platform_lock_serializes_first_concurrent_preview_creation(tmp_path) -> None:
    store = TransactionStore(tmp_path)
    transaction_id = "tx-first-preview-race"
    lock_path = store.locks_dir / f"{transaction_id}.lock"
    assert not lock_path.exists()

    context = _cross_process_context()
    ready = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_race_create_preview,
            args=(str(tmp_path), transaction_id, contender, ready, results),
        )
        for contender in ("first", "second")
    ]
    for process in processes:
        process.start()
    ready.set()
    outcomes = [results.get(timeout=10) for _ in processes]
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    assert sorted(outcome[0] for outcome in outcomes) == ["already_exists", "created"]
    winner = next(outcome[1] for outcome in outcomes if outcome[0] == "created")
    preview = store.load_preview(transaction_id)
    assert preview.artifact == {"contender": winner}
    assert len(store.read_events(transaction_id)) == 1


def test_missing_posix_lock_backend_fails_closed(tmp_path, monkeypatch) -> None:
    store = TransactionStore(tmp_path)
    monkeypatch.setattr(transaction_module, "_fcntl", None)
    monkeypatch.setattr(transaction_module, "_lock_platform_name", lambda: "posix")

    with pytest.raises(FileLockUnavailable, match=r"fcntl\.flock.*will not run unlocked"):
        store.create_preview("tx-no-lock", {"unsafe": False})


def test_missing_windows_lock_backend_fails_closed(tmp_path, monkeypatch) -> None:
    store = TransactionStore(tmp_path)
    monkeypatch.setattr(transaction_module, "_msvcrt", None)
    monkeypatch.setattr(transaction_module, "_lock_platform_name", lambda: "nt")

    with pytest.raises(FileLockUnavailable, match=r"msvcrt\.locking.*will not run unlocked"):
        store.create_preview("tx-no-windows-lock", {"unsafe": False})

    assert list(store.locks_dir.iterdir()) == []


def test_windows_lock_backend_uses_byte_zero_beyond_eof_and_releases(tmp_path, monkeypatch) -> None:
    class FakeMsvcrt:
        LK_NBLCK = 1
        LK_UNLCK = 2

        def __init__(self) -> None:
            self.calls: list[tuple[int, int, int, int]] = []

        def locking(self, fd: int, mode: int, byte_count: int) -> None:
            self.calls.append(
                (
                    mode,
                    byte_count,
                    os.lseek(fd, 0, os.SEEK_CUR),
                    os.fstat(fd).st_size,
                )
            )

    fake_msvcrt = FakeMsvcrt()
    monkeypatch.setattr(transaction_module, "_msvcrt", fake_msvcrt)
    monkeypatch.setattr(transaction_module, "_lock_platform_name", lambda: "nt")
    store = TransactionStore(tmp_path)

    store.create_preview("tx-windows-lock", {"safe": True})

    assert fake_msvcrt.calls == [
        (fake_msvcrt.LK_NBLCK, 1, 0, 0),
        (fake_msvcrt.LK_UNLCK, 1, 0, 0),
    ]
    assert (store.locks_dir / "tx-windows-lock.lock").read_bytes() == b""


def test_windows_lock_retries_only_recognized_contention(tmp_path, monkeypatch) -> None:
    class FakeMsvcrt:
        LK_NBLCK = 1
        LK_UNLCK = 2

        def __init__(self) -> None:
            self.acquire_attempts = 0

        def locking(self, _fd: int, mode: int, _byte_count: int) -> None:
            if mode == self.LK_NBLCK:
                self.acquire_attempts += 1
                if self.acquire_attempts == 1:
                    raise OSError(errno.EACCES, "owned by another process")

    fake_msvcrt = FakeMsvcrt()
    sleeps: list[float] = []
    monkeypatch.setattr(transaction_module, "_msvcrt", fake_msvcrt)
    monkeypatch.setattr(transaction_module, "_lock_platform_name", lambda: "nt")
    monkeypatch.setattr(transaction_module.time, "sleep", sleeps.append)
    store = TransactionStore(tmp_path)

    store.create_preview("tx-windows-contention", {"safe": True})

    assert fake_msvcrt.acquire_attempts == 2
    assert sleeps == [transaction_module._WINDOWS_LOCK_RETRY_SECONDS]


def test_windows_lock_contention_classifier_is_narrow() -> None:
    lock_violation = OSError(errno.EIO, "Windows lock violation")
    lock_violation.winerror = transaction_module._WINDOWS_LOCK_VIOLATION

    assert transaction_module._is_windows_lock_contention(
        OSError(errno.EACCES, "access denied")
    )
    assert transaction_module._is_windows_lock_contention(
        OSError(errno.EDEADLK, "deadlock")
    )
    assert transaction_module._is_windows_lock_contention(lock_violation)
    assert not transaction_module._is_windows_lock_contention(
        OSError(errno.EBADF, "invalid handle")
    )


def test_windows_lock_non_contention_error_fails_closed(tmp_path, monkeypatch) -> None:
    class FakeMsvcrt:
        LK_NBLCK = 1
        LK_UNLCK = 2

        @staticmethod
        def locking(_fd: int, mode: int, _byte_count: int) -> None:
            if mode == FakeMsvcrt.LK_NBLCK:
                raise OSError(errno.EBADF, "invalid lock handle")

    monkeypatch.setattr(transaction_module, "_msvcrt", FakeMsvcrt())
    monkeypatch.setattr(transaction_module, "_lock_platform_name", lambda: "nt")
    store = TransactionStore(tmp_path)

    with pytest.raises(FileLockUnavailable, match="could not acquire.*msvcrt"):
        store.create_preview("tx-windows-bad-handle", {"safe": True})


def test_windows_unlock_failure_does_not_mask_body_error(tmp_path, monkeypatch) -> None:
    class FakeMsvcrt:
        LK_NBLCK = 1
        LK_UNLCK = 2

        @staticmethod
        def locking(_fd: int, mode: int, _byte_count: int) -> None:
            if mode == FakeMsvcrt.LK_UNLCK:
                raise OSError(errno.EBADF, "invalid lock handle")

    class BodyError(RuntimeError):
        pass

    monkeypatch.setattr(transaction_module, "_msvcrt", FakeMsvcrt())
    monkeypatch.setattr(transaction_module, "_lock_platform_name", lambda: "nt")
    store = TransactionStore(tmp_path)

    with pytest.raises(BodyError, match="transaction body failed"):
        with store._transaction_lock("tx-windows-body-error"):
            raise BodyError("transaction body failed")


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
