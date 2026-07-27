from __future__ import annotations

import json
import shutil
import time
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

from tests.semantic.support.codex_transaction_seal import (
    PREVIEW_SEAL_CONTRACT,
    PREVIEW_SEAL_EVIDENCE_CONTRACT,
    PreviewTransactionSeal,
    TransactionSealError,
    create_preview_seal,
    parse_preview_seal,
    serialize_preview_seal,
    validate_transaction_show_confirmation_against_store,
    verify_preview_seal,
)
from wwise_waapi.canonical import canonical_sha256
from wwise_waapi.operation_registry import OPERATION_REQUEST_CONTRACT
from wwise_waapi.transaction_runtime import (
    PROJECT_GUARD_CONTRACT,
    RUNTIME_GUARD_CONTRACT,
    TRANSACTION_PREVIEW_CONTRACT,
)
from wwise_waapi.transactions import TransactionState, TransactionStore


GUID = "{11111111-1111-1111-1111-111111111111}"
CREATED_AT = "2026-07-14T06:00:00.000000Z"
EXPIRES_AT = "2026-07-14T06:30:00.000000Z"


def _artifact(*, omit: str | None = None) -> dict[str, Any]:
    project_body = {
        "endpoint": {
            "host": "127.0.0.1",
            "port": 31337,
            "url": "ws://127.0.0.1:31337/waapi",
        },
        "version": "2022.1",
        "wwise": {
            "displayName": "Wwise",
            "isCommandLine": True,
            "version": {"year": 2022, "major": 1, "minor": 19, "build": 8584},
        },
        "project": {
            "id": "{project}",
            "name": "SampleProject",
            "path": "/tmp/SampleProject.wproj",
        },
    }
    runtime_body = {
        "version": "2022.1",
        "files": {"wwise_waapi/operation_registry.py": "a" * 64},
    }
    request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "object.setNotes",
        "arguments": {"object": {"kind": "id", "value": GUID}, "value": "after"},
    }
    artifact: dict[str, Any] = {
        "contract": TRANSACTION_PREVIEW_CONTRACT,
        "request": request,
        "prepared_operation": {
            "contract": "waapi-skill.prepared-operation/v1",
            "operation": "object.setNotes",
        },
        "project_guard": {
            "contract": PROJECT_GUARD_CONTRACT,
            **project_body,
            "fingerprint": canonical_sha256(project_body),
        },
        "runtime_guard": {
            "contract": RUNTIME_GUARD_CONTRACT,
            **runtime_body,
            "fingerprint": canonical_sha256(runtime_body),
        },
        "created_at": CREATED_AT,
        "expires_at": EXPIRES_AT,
        "execution_policy": {
            "requires_authorization": True,
            "accepted_authorization_modes": [
                "explicit_confirmation",
                "policy_authorization",
            ],
            "authorization_selected_at_preview": True,
            "automatic_retry_allowed": False,
            "revalidate_project_guard": True,
            "revalidate_runtime_guard": True,
            "revalidate_resolved_roles": True,
            "post_execution_verification_required": True,
        },
    }
    if omit is not None:
        del artifact[omit]
    return artifact


def _awaiting_store(state_directory: Path, transaction_id: str = "tx-sealed") -> TransactionStore:
    store = TransactionStore(state_directory)
    store.create_preview(transaction_id, _artifact())
    store.submit_for_confirmation(transaction_id)
    return store


def _preview_path(state_directory: Path, transaction_id: str = "tx-sealed") -> Path:
    return state_directory / "transactions" / transaction_id / "preview.json"


def _events_path(state_directory: Path, transaction_id: str = "tx-sealed") -> Path:
    return state_directory / "transactions" / transaction_id / "events.jsonl"


def test_confirmation_binding_matches_current_and_historical_journal_head(
    tmp_path: Path,
) -> None:
    store = _awaiting_store(tmp_path)
    snapshot = store.load_snapshot("tx-sealed")
    assert snapshot.confirmation_token is not None
    payload = {
        "contract": "waapi-skill.gateway-result/v1",
        "ok": True,
        "command": "transaction-show",
        "transaction_id": "tx-sealed",
        "artifact_hash": snapshot.preview.artifact_hash,
        "state": "awaiting_confirmation",
        "confirmation": {
            "contract": "waapi-skill.confirmation-binding/v1",
            "token": snapshot.confirmation_token,
            "binding": {
                "material_contract": "waapi-skill.confirmation-token-material/v1",
                "transaction_id": "tx-sealed",
                "artifact_hash": snapshot.preview.artifact_hash,
                "state": "awaiting_confirmation",
                "event_sequence": snapshot.record.event_sequence,
                "last_event_hash": snapshot.record.last_event_hash,
            },
        },
    }

    evidence = validate_transaction_show_confirmation_against_store(
        payload,
        tmp_path,
    )
    assert evidence["event_sequence"] == snapshot.record.event_sequence

    store.confirm("tx-sealed", confirmation_token=snapshot.confirmation_token)
    assert (
        validate_transaction_show_confirmation_against_store(payload, tmp_path)
        == evidence
    )

    tampered = json.loads(json.dumps(payload))
    tampered["confirmation"]["binding"]["last_event_hash"] = "c" * 64
    with pytest.raises(TransactionSealError, match="confirmation"):
        validate_transaction_show_confirmation_against_store(tampered, tmp_path)


def test_phase_a_seal_is_immutable_closed_json_and_verifies_awaiting_state(tmp_path: Path) -> None:
    _awaiting_store(tmp_path)

    seal = create_preview_seal(tmp_path, "tx-sealed")
    evidence = verify_preview_seal(
        tmp_path,
        "tx-sealed",
        seal,
        allowed_states={TransactionState.AWAITING_CONFIRMATION},
    )
    encoded = serialize_preview_seal(seal)

    assert seal.contract == PREVIEW_SEAL_CONTRACT
    assert seal.state == "awaiting_confirmation"
    assert seal.state_directory == str(tmp_path)
    assert seal.preview_file_size == _preview_path(tmp_path).stat().st_size
    assert len(seal.preview_json_sha256) == 64
    assert len(seal.events_jsonl_sha256) == 64
    assert seal.project_guard_fingerprint == _artifact()["project_guard"]["fingerprint"]
    assert seal.runtime_guard_fingerprint == _artifact()["runtime_guard"]["fingerprint"]
    assert seal.request_canonical_sha256 == canonical_sha256(_artifact()["request"])
    assert evidence.contract == PREVIEW_SEAL_EVIDENCE_CONTRACT
    assert evidence.state == "awaiting_confirmation"
    assert parse_preview_seal(encoded) == seal
    assert PreviewTransactionSeal.from_json(encoded.encode("utf-8")) == seal
    with pytest.raises(FrozenInstanceError):
        seal.state = "confirmed"  # type: ignore[misc]


def test_seal_creation_requires_awaiting_confirmation_and_complete_artifact(tmp_path: Path) -> None:
    store = TransactionStore(tmp_path / "draft")
    store.create_preview("tx-draft", _artifact())
    with pytest.raises(TransactionSealError, match="only be created in awaiting_confirmation"):
        create_preview_seal(tmp_path / "draft", "tx-draft")

    incomplete = TransactionStore(tmp_path / "incomplete")
    incomplete.create_preview("tx-incomplete", _artifact(omit="expires_at"))
    incomplete.submit_for_confirmation("tx-incomplete")
    with pytest.raises(TransactionSealError, match="missing=.*expires_at"):
        create_preview_seal(tmp_path / "incomplete", "tx-incomplete")


def test_confirm_and_verified_state_progression_preserves_phase_a_preview(tmp_path: Path) -> None:
    store = _awaiting_store(tmp_path)
    seal = create_preview_seal(tmp_path, "tx-sealed")
    preview_before = _preview_path(tmp_path).read_bytes()

    store.confirm("tx-sealed", artifact_hash=seal.artifact_hash)
    confirmed = verify_preview_seal(
        tmp_path,
        "tx-sealed",
        seal,
        allowed_states={TransactionState.CONFIRMED},
    )
    store.begin_execution(
        "tx-sealed",
        expected_authorization=TransactionState.CONFIRMED,
    )
    executing = verify_preview_seal(
        tmp_path,
        "tx-sealed",
        seal,
        allowed_states={TransactionState.EXECUTING},
    )
    store.mark_executed_unverified("tx-sealed")
    store.record_verification("tx-sealed", TransactionState.VERIFIED)
    verified = verify_preview_seal(
        tmp_path,
        "tx-sealed",
        seal,
        allowed_states={TransactionState.VERIFIED},
    )

    assert confirmed.state == "confirmed"
    assert executing.state == "executing"
    assert verified.state == "verified"
    assert confirmed.event_sequence == seal.event_sequence + 1
    assert verified.event_sequence == seal.event_sequence + 4
    assert verified.events_jsonl_sha256 != seal.events_jsonl_sha256
    assert verified.preview_json_sha256 == seal.preview_json_sha256
    assert _preview_path(tmp_path).read_bytes() == preview_before


def test_preview_write_then_restore_is_detected_by_ctime(tmp_path: Path) -> None:
    _awaiting_store(tmp_path)
    seal = create_preview_seal(tmp_path, "tx-sealed")
    path = _preview_path(tmp_path)
    original = path.read_bytes()
    old_ctime = path.stat().st_ctime_ns
    time.sleep(0.01)
    path.write_bytes(original)

    assert path.read_bytes() == original
    assert path.stat().st_ctime_ns != old_ctime
    with pytest.raises(TransactionSealError, match="preview.json ctime drift"):
        verify_preview_seal(
            tmp_path,
            "tx-sealed",
            seal,
            allowed_states={TransactionState.AWAITING_CONFIRMATION},
        )


def test_event_journal_tampering_is_rejected_by_production_integrity_load(tmp_path: Path) -> None:
    _awaiting_store(tmp_path)
    seal = create_preview_seal(tmp_path, "tx-sealed")
    path = _events_path(tmp_path)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[-1]["details"] = {"injected": True}
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    with pytest.raises(TransactionSealError, match="Production TransactionStore rejected.*Event hash mismatch"):
        verify_preview_seal(
            tmp_path,
            "tx-sealed",
            seal,
            allowed_states={TransactionState.AWAITING_CONFIRMATION},
        )


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("transaction_id", "tx-other", "Transaction id drift"),
        ("artifact_hash", "0" * 64, "artifact hash drift"),
        ("project_guard_fingerprint", "1" * 64, "project guard fingerprint drift"),
        ("runtime_guard_fingerprint", "2" * 64, "runtime guard fingerprint drift"),
        ("request_canonical_sha256", "3" * 64, "request canonical SHA-256 drift"),
    ],
)
def test_wrong_transaction_hash_or_guard_bindings_fail_closed(
    tmp_path: Path,
    field: str,
    replacement: str,
    message: str,
) -> None:
    _awaiting_store(tmp_path)
    seal = create_preview_seal(tmp_path, "tx-sealed")
    drifted = replace(seal, **{field: replacement})

    with pytest.raises(TransactionSealError, match=message):
        verify_preview_seal(
            tmp_path,
            "tx-sealed",
            drifted,
            allowed_states={TransactionState.AWAITING_CONFIRMATION},
        )


def test_seal_json_rejects_unknown_missing_duplicate_and_wrong_contract_fields(tmp_path: Path) -> None:
    _awaiting_store(tmp_path)
    seal = create_preview_seal(tmp_path, "tx-sealed")

    unknown = seal.as_dict()
    unknown["surprise"] = True
    with pytest.raises(TransactionSealError, match="unknown=.*surprise"):
        parse_preview_seal(json.dumps(unknown))

    missing = seal.as_dict()
    del missing["expires_at"]
    with pytest.raises(TransactionSealError, match="missing=.*expires_at"):
        parse_preview_seal(json.dumps(missing))

    wrong_contract = seal.as_dict()
    wrong_contract["contract"] = "waapi-skill.codex-transaction-preview-seal/v999"
    with pytest.raises(TransactionSealError, match="Unsupported preview seal contract"):
        parse_preview_seal(json.dumps(wrong_contract))

    duplicate = serialize_preview_seal(seal)[:-1] + ',"state":"awaiting_confirmation"}'
    with pytest.raises(TransactionSealError, match="duplicate JSON key"):
        parse_preview_seal(duplicate)


def test_symlinked_preview_and_state_root_are_rejected(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    _awaiting_store(state_root)
    seal = create_preview_seal(state_root, "tx-sealed")
    preview = _preview_path(state_root)
    external = tmp_path / "external-preview.json"
    external.write_bytes(preview.read_bytes())
    preview.unlink()
    preview.symlink_to(external)

    with pytest.raises(TransactionSealError, match="preview.json cannot be a symlink"):
        verify_preview_seal(
            state_root,
            "tx-sealed",
            seal,
            allowed_states={TransactionState.AWAITING_CONFIRMATION},
        )

    root_link = tmp_path / "state-link"
    root_link.symlink_to(state_root, target_is_directory=True)
    with pytest.raises(TransactionSealError, match="State-directory symlink"):
        create_preview_seal(root_link, "tx-sealed")


def test_state_directory_path_drift_and_non_explicit_allowed_states_fail(tmp_path: Path) -> None:
    original = tmp_path / "original"
    copied = tmp_path / "copied"
    _awaiting_store(original)
    seal = create_preview_seal(original, "tx-sealed")
    shutil.copytree(original, copied)

    with pytest.raises(TransactionSealError, match="State-directory path drift"):
        verify_preview_seal(
            copied,
            "tx-sealed",
            seal,
            allowed_states={TransactionState.AWAITING_CONFIRMATION},
        )
    with pytest.raises(TransactionSealError, match="non-empty and explicit"):
        verify_preview_seal(original, "tx-sealed", seal, allowed_states=set())
    with pytest.raises(TransactionSealError, match="not a string"):
        verify_preview_seal(
            original,
            "tx-sealed",
            seal,
            allowed_states="awaiting_confirmation",  # type: ignore[arg-type]
        )


def test_unknown_state_envelope_field_fails_even_when_transaction_store_accepts_it(tmp_path: Path) -> None:
    _awaiting_store(tmp_path)
    state_path = tmp_path / "transactions" / "tx-sealed" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["runner_owned"] = False
    state_path.write_text(json.dumps(state), encoding="utf-8")

    # Production validates all known state/journal fields; the seal layer also
    # closes the envelope against forward/hostile unknown fields.
    assert TransactionStore(tmp_path).load("tx-sealed").state is TransactionState.AWAITING_CONFIRMATION
    with pytest.raises(TransactionSealError, match="state.json.*unknown=.*runner_owned"):
        create_preview_seal(tmp_path, "tx-sealed")
