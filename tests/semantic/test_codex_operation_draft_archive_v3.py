from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from tests.semantic.support.codex_gateway_broker import (
    DraftActionJsonArgument,
    DraftActionResponseBinding,
    ExpectedGatewayStep,
    ResponseBinding,
    SemanticJsonArgument,
)
from tests.semantic.support.codex_operation_draft_archive_v3 import (
    ComposerArchiveError,
    classify_composer_failure_stage,
    validate_operation_draft_archive,
)
from wwise_waapi.canonical import canonical_sha256
from wwise_waapi.operation_composer import composition_projection
from wwise_waapi.operation_drafts import OperationDraftRecord, OperationDraftStore
from wwise_waapi.transaction_cleanup import transaction_cleanup_payload
from wwise_waapi.transactions import (
    TransactionState,
    TransactionStore,
    new_transaction_id,
)


ACTION_CONTRACT = "waapi-skill.operation-draft-action/v1"
GATEWAY_CONTRACT = "waapi-skill.gateway-result/v1"
OBJECT_ID = "{11111111-1111-1111-1111-111111111111}"


def _draft_payload(
    command: str,
    record: OperationDraftRecord,
    *,
    task_authority: str | None = None,
) -> dict[str, Any]:
    projection = composition_projection(
        record.operation,
        record.version,
        record.composition or {},
    )
    payload = {
        "contract": GATEWAY_CONTRACT,
        "ok": True,
        "command": command,
        "draft": {
            "draft_id": record.draft_id,
            "revision": record.revision,
            "lifecycle_state": record.state.value,
            "binding": {
                "operation": record.operation,
                "version": record.version,
                "schema_digest": record.schema_digest,
            },
            **projection,
        },
    }
    if task_authority is not None:
        payload["task_authority"] = task_authority
    return payload


def _record(
    step: ExpectedGatewayStep,
    arguments: list[str],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "step_name": step.name,
        "gateway_arguments": [step.subcommand, *arguments],
        "payload": copy.deepcopy(dict(payload)),
        "succeeded": True,
    }


def _sealed_archive(
    root: Path,
) -> tuple[Path, tuple[ExpectedGatewayStep, ...], list[dict[str, Any]]]:
    state_dir = root / "state"
    schema_digest = "a" * 64
    composer_digest = "b" * 64
    draft_store = OperationDraftStore(state_dir)
    started = draft_store.start(
        operation="object.set",
        version="2022.1",
        schema_digest=schema_digest,
        composer_digest=composer_digest,
    )
    add_action = {
        "contract": ACTION_CONTRACT,
        "action": "add_target",
        "selector": {"kind": "id", "value": OBJECT_ID},
    }
    targeted = draft_store.apply_action(
        started.draft_id,
        task_authority=started.task_authority,
        expected_revision=1,
        schema_digest=schema_digest,
        composer_digest=composer_digest,
        action=add_action,
    )
    target_handle = targeted.composition["targets"][0]["handle"]
    property_action = {
        "contract": ACTION_CONTRACT,
        "action": "set_property",
        "target_handle": target_handle,
        "name": "Volume",
        "value": -3,
    }
    changed = draft_store.apply_action(
        started.draft_id,
        task_authority=started.task_authority,
        expected_revision=2,
        schema_digest=schema_digest,
        composer_digest=composer_digest,
        action=property_action,
    )
    materialized = draft_store.materialize_request(
        started.draft_id,
        task_authority=started.task_authority,
        expected_revision=3,
        schema_digest=schema_digest,
        composer_digest=composer_digest,
    )
    project_guard = {"contract": "test-project-guard/v1", "project": "sandbox"}
    checked = draft_store.record_check(
        started.draft_id,
        task_authority=started.task_authority,
        expected_revision=3,
        schema_digest=schema_digest,
        composer_digest=composer_digest,
        request_digest=materialized.request_digest,
        project_guard=project_guard,
        runtime_guard_fingerprint="c" * 64,
        prepared_digest="d" * 64,
    )
    transaction_id = new_transaction_id()
    reservation = draft_store.reserve_seal(
        started.draft_id,
        task_authority=started.task_authority,
        expected_revision=4,
        schema_digest=schema_digest,
        composer_digest=composer_digest,
        transaction_id=transaction_id,
        apply=True,
        ttl_seconds=300,
        policy="ask_before_changes",
    )
    prepared_operation = {
        "request": dict(reservation.request),
        "cleanup": {"kind": "none"},
    }
    preview_cleanup = transaction_cleanup_payload(
        prepared_operation,
        phase="preview",
    )
    cleanup = transaction_cleanup_payload(
        prepared_operation,
        phase="verified",
        execution_result={},
    )
    artifact = {
        "request": dict(reservation.request),
        "prepared_operation": prepared_operation,
        "project_guard": dict(project_guard),
    }
    transaction_store = TransactionStore(state_dir)
    transaction_store.create_preview(transaction_id, artifact)
    awaiting = transaction_store.submit_for_confirmation(transaction_id)
    sealed = draft_store.commit_seal(
        started.draft_id,
        task_authority=started.task_authority,
        source_revision=reservation.source_revision,
        transaction_id=transaction_id,
        artifact_hash=awaiting.artifact_hash,
        transaction_state=awaiting.state.value,
    )
    snapshot = transaction_store.load_snapshot(transaction_id)
    assert snapshot.confirmation_token is not None
    confirmed = transaction_store.confirm(
        transaction_id,
        confirmation_token=snapshot.confirmation_token,
    )
    transaction_store.begin_execution(
        transaction_id,
        expected_authorization=confirmed.state,
    )
    transaction_store.mark_executed_unverified(transaction_id)
    verified = transaction_store.record_verification(
        transaction_id,
        TransactionState.VERIFIED,
        details={"verification": {"status": "verified"}},
    )

    start_step = ExpectedGatewayStep("draft.start", "draft-start", ("object.set",))
    target_step = ExpectedGatewayStep(
        "draft.target",
        "draft-apply",
        (
            ResponseBinding("draft.start", "/draft/draft_id"),
            "--task-authority",
            ResponseBinding("draft.start", "/task_authority"),
            "--expected-revision",
            ResponseBinding("draft.start", "/draft/revision"),
            "--action-json",
            DraftActionJsonArgument(add_action),
        ),
    )
    property_step = ExpectedGatewayStep(
        "draft.property",
        "draft-apply",
        (
            ResponseBinding("draft.start", "/draft/draft_id"),
            "--task-authority",
            ResponseBinding("draft.start", "/task_authority"),
            "--expected-revision",
            ResponseBinding("draft.target", "/draft/revision"),
            "--action-json",
            DraftActionJsonArgument(
                {
                    key: value
                    for key, value in property_action.items()
                    if key != "target_handle"
                },
                response_bindings=(
                    DraftActionResponseBinding(
                        "/target_handle",
                        "draft.target",
                        "/draft/current_facts/0/handle",
                    ),
                ),
            ),
        ),
    )
    check_step = ExpectedGatewayStep(
        "draft.check",
        "draft-check",
        (
            ResponseBinding("draft.start", "/draft/draft_id"),
            "--task-authority",
            ResponseBinding("draft.start", "/task_authority"),
            "--expected-revision",
            ResponseBinding("draft.property", "/draft/revision"),
        ),
    )
    preview_step = ExpectedGatewayStep(
        "draft.preview",
        "preview-from-draft",
        (
            ResponseBinding("draft.start", "/draft/draft_id"),
            "--task-authority",
            ResponseBinding("draft.start", "/task_authority"),
            "--expected-revision",
            ResponseBinding("draft.check", "/draft/revision"),
            "--apply",
            "--ttl",
            "300",
        ),
    )
    show_step = ExpectedGatewayStep(
        "draft.show",
        "transaction-show",
        (ResponseBinding("draft.preview", "/transaction_id"), "--summary-only"),
    )
    confirm_step = ExpectedGatewayStep(
        "draft.confirm",
        "confirm",
        (ResponseBinding("draft.show", "/transaction_id"),),
    )
    execute_step = ExpectedGatewayStep(
        "draft.execute",
        "execute",
        (ResponseBinding("draft.confirm", "/transaction_id"),),
    )
    verify_step = ExpectedGatewayStep(
        "draft.verify",
        "verify",
        (ResponseBinding("draft.execute", "/transaction_id"),),
    )
    steps = (
        start_step,
        target_step,
        property_step,
        check_step,
        preview_step,
        show_step,
        confirm_step,
        execute_step,
        verify_step,
    )
    preview_agent_result = {
        "operation": "object.set",
        "transaction_id": transaction_id,
        "artifact_hash": awaiting.artifact_hash,
        "state": awaiting.state.value,
        "executed": False,
        "request": dict(reservation.request),
        "cleanup": preview_cleanup,
    }
    records = [
        _record(start_step, ["object.set"], _draft_payload(
            "draft-start", started.record, task_authority=started.task_authority
        )),
        _record(
            target_step,
            [
                started.draft_id,
                "--task-authority",
                started.task_authority,
                "--expected-revision",
                "1",
                "--action-json",
                json.dumps(add_action),
            ],
            _draft_payload("draft-apply", targeted),
        ),
        _record(
            property_step,
            [
                started.draft_id,
                "--task-authority",
                started.task_authority,
                "--expected-revision",
                "2",
                "--action-json",
                json.dumps(property_action),
            ],
            _draft_payload("draft-apply", changed),
        ),
        _record(
            check_step,
            [
                started.draft_id,
                "--task-authority",
                started.task_authority,
                "--expected-revision",
                "3",
            ],
            _draft_payload("draft-check", checked),
        ),
        _record(
            preview_step,
            [
                started.draft_id,
                "--task-authority",
                started.task_authority,
                "--expected-revision",
                "4",
                "--apply",
                "--ttl",
                "300",
            ],
            {
                "contract": GATEWAY_CONTRACT,
                "ok": True,
                "command": "preview-from-draft",
                "transaction_id": transaction_id,
                "artifact_hash": awaiting.artifact_hash,
                "state": awaiting.state.value,
        "cleanup": preview_cleanup,
                "agent_result": preview_agent_result,
            },
        ),
        _record(
            show_step,
            [transaction_id, "--summary-only"],
            {
                "contract": GATEWAY_CONTRACT,
                "ok": True,
                "command": "transaction-show",
                "transaction_id": transaction_id,
            },
        ),
        _record(
            confirm_step,
            [transaction_id],
            {
                "contract": GATEWAY_CONTRACT,
                "ok": True,
                "command": "confirm",
                "transaction_id": transaction_id,
            },
        ),
        _record(
            execute_step,
            [transaction_id],
            {
                "contract": GATEWAY_CONTRACT,
                "ok": True,
                "command": "execute",
                "transaction_id": transaction_id,
            },
        ),
        _record(
            verify_step,
            [transaction_id],
            {
                "contract": GATEWAY_CONTRACT,
                "ok": True,
                "command": "verify",
                "transaction_id": transaction_id,
                "state": verified.state.value,
                "cleanup": cleanup,
                "verification": {"status": "verified"},
                "agent_result": {
                    **preview_agent_result,
                    "state": verified.state.value,
                    "executed": True,
                    "verified": True,
                    "cleanup": cleanup,
                },
            },
        ),
    ]
    assert sealed.revision == 6
    return state_dir, steps, records


def test_composer_archive_reconstructs_actions_request_preview_and_cleanup(
    tmp_path: Path,
) -> None:
    state_dir, steps, records = _sealed_archive(tmp_path)

    evidence = validate_operation_draft_archive(
        state_directory=state_dir,
        steps=steps,
        broker_records=records,
    )

    assert evidence is not None
    assert evidence["lifecycle_state"] == "sealed"
    assert [row["action"] for row in evidence["actions"]] == [
        "add_target",
        "set_property",
    ]
    assert evidence["final_revision"] == 6
    assert evidence["canonical_request"]["operation"] == "object.set"
    assert evidence["canonical_request_sha256"] == canonical_sha256(
        evidence["canonical_request"]
    )
    assert evidence["preview_binding"]["transaction_final_state"] == "verified"
    assert evidence["cleanup_outcome"]["status"] == "not_required"


def test_composer_archive_ignores_other_legacy_transaction_payloads(
    tmp_path: Path,
) -> None:
    state_dir, steps, records = _sealed_archive(tmp_path)
    legacy_request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "audio.import",
        "arguments": {"imports": []},
    }
    legacy_preview = ExpectedGatewayStep(
        "legacy.preview",
        "preview",
        (
            "--request-json",
            SemanticJsonArgument(legacy_request),
        ),
    )
    legacy_show = ExpectedGatewayStep(
        "legacy.show",
        "transaction-show",
        ("tx-unrelated", "--summary-only"),
    )
    mixed_steps = (legacy_preview, legacy_show, *steps)
    mixed_records = [
        _record(
            legacy_preview,
            ["--request-json", json.dumps(legacy_request)],
            {
                "contract": GATEWAY_CONTRACT,
                "ok": True,
                "command": "preview",
                "transaction_id": "tx-unrelated",
            },
        ),
        _record(
            legacy_show,
            ["tx-unrelated", "--summary-only"],
            {
                "contract": GATEWAY_CONTRACT,
                "ok": True,
                "command": "transaction-show",
                "transaction_id": "tx-unrelated",
            },
        ),
        *records,
    ]

    evidence = validate_operation_draft_archive(
        state_directory=state_dir,
        steps=mixed_steps,
        broker_records=mixed_records,
    )

    assert evidence is not None
    assert evidence["preview_binding"]["transaction_final_state"] == "verified"
    assert evidence["canonical_request"]["operation"] == "object.set"


@pytest.mark.parametrize(
    "tamper",
    (
        "delete_action",
        "inject_action",
        "reorder",
        "revision",
        "request",
        "preview",
        "cleanup",
        "state",
        "delete_event",
        "reorder_event",
    ),
)
def test_composer_archive_tampering_fails_closed(
    tmp_path: Path,
    tamper: str,
) -> None:
    state_dir, steps, records = _sealed_archive(tmp_path)
    changed = copy.deepcopy(records)
    if tamper == "delete_action":
        del changed[2]
    elif tamper == "inject_action":
        changed.insert(2, copy.deepcopy(changed[1]))
    elif tamper == "reorder":
        changed[1], changed[2] = changed[2], changed[1]
    elif tamper == "revision":
        changed[2]["payload"]["draft"]["revision"] = 99
    elif tamper == "request":
        changed[4]["payload"]["agent_result"]["request"]["arguments"]["objects"][0][
            "properties"
        ][0]["value"] = -2
    elif tamper == "preview":
        changed[4]["payload"]["artifact_hash"] = "f" * 64
    elif tamper == "cleanup":
        changed[-1]["payload"]["agent_result"]["cleanup"]["status"] = "pending"
    elif tamper == "state":
        state_path = next((state_dir / "transactions").rglob("state.json"))
        state_path.write_bytes(state_path.read_bytes() + b" ")
    else:
        events_path = next((state_dir / "transactions").rglob("events.jsonl"))
        lines = events_path.read_bytes().splitlines(keepends=True)
        if tamper == "delete_event":
            del lines[-2]
        else:
            lines[1], lines[2] = lines[2], lines[1]
        events_path.write_bytes(b"".join(lines))

    with pytest.raises(ComposerArchiveError):
        validate_operation_draft_archive(
            state_directory=state_dir,
            steps=steps,
            broker_records=changed,
        )


def test_legacy_archive_requires_no_composer_projection(tmp_path: Path) -> None:
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.set",
        "arguments": {"objects": []},
    }
    steps = (
        ExpectedGatewayStep(
            "legacy.preview",
            "preview",
            ("--request-json", SemanticJsonArgument(request)),
        ),
    )

    assert validate_operation_draft_archive(
        state_directory=tmp_path / "missing",
        steps=steps,
        broker_records=(),
    ) is None


@pytest.mark.parametrize(
    ("subcommand", "expected"),
    (
        ("draft-apply", "draft"),
        ("preview-from-draft", "preview"),
        ("execute", "execute"),
        ("verify", "verify"),
        ("query-object", "broker"),
    ),
)
def test_composer_failure_stage_is_explicit(
    subcommand: str,
    expected: str,
) -> None:
    assert classify_composer_failure_stage(subcommand) == expected
