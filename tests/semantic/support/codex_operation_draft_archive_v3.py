"""Strict offline evidence replay for Composer-backed semantic protocols."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from wwise_waapi.canonical import canonical_json_bytes, canonical_sha256
from wwise_waapi.operation_composer import (
    OperationComposerError,
    apply_composer_action,
    composition_projection,
    new_composition,
)
from wwise_waapi.operation_drafts import (
    OperationDraftError,
    OperationDraftState,
    load_operation_draft_archive_record,
    operation_draft_authority_digest,
)
from wwise_waapi.transaction_cleanup import transaction_cleanup_payload
from wwise_waapi.transactions import (
    TransactionError,
    load_transaction_archive_snapshot,
)


COMPOSER_ARCHIVE_CONTRACT = "waapi-skill.codex-composer-archive/v1"
MAX_COMPOSER_ARCHIVE_ACTIONS = 512
MAX_COMPOSER_ARCHIVE_ACTION_BYTES = 32 * 1024
MAX_COMPOSER_ARCHIVE_BYTES = 1024 * 1024
_DRAFT_SUBCOMMANDS = frozenset(
    {
        "draft-start",
        "draft-inspect",
        "draft-apply",
        "draft-check",
        "draft-cancel",
        "preview-from-draft",
    }
)


class ComposerArchiveError(RuntimeError):
    """Composer evidence is missing, inconsistent, or not replayable."""


def classify_composer_failure_stage(subcommand: str) -> str:
    if subcommand in {
        "draft-start",
        "draft-inspect",
        "draft-apply",
        "draft-check",
        "draft-cancel",
    }:
        return "draft"
    if subcommand in {
        "preview-from-draft",
        "transaction-show",
        "confirm",
        "reject",
    }:
        return "preview"
    if subcommand == "execute":
        return "execute"
    if subcommand == "verify":
        return "verify"
    return "broker"


def _fail(message: str) -> None:
    raise ComposerArchiveError(message)


def _mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{label} must be an object")
    return value


def _verification_projection_matches_journal(
    projected: Any,
    journal: Any,
) -> bool:
    """Bind the bounded stdout verification summary to full journal evidence."""

    if projected == journal:
        return True
    if not isinstance(projected, Mapping) or not isinstance(journal, Mapping):
        return False
    expected_keys = {
        "summary_contract",
        "contract",
        "operation",
        "status",
        "ok",
        "verification_strength",
        "business_state_verified",
        "assertion_count",
        "passed_assertion_count",
        "failed_assertion_count",
        "assertions_canonical_sha256",
        "readback_count",
        "readbacks_canonical_sha256",
        "canonical_sha256",
        "full_evidence_in_stdout",
    }
    if set(projected) != expected_keys:
        return False
    assertions = journal.get("assertions")
    readbacks = journal.get("readbacks")
    if not isinstance(assertions, list) or not isinstance(readbacks, list):
        return False
    if any(not isinstance(row, Mapping) for row in assertions):
        return False
    passed = sum(row.get("passed") is True for row in assertions)
    expected = {
        "summary_contract": "waapi-skill.transaction-verification-result-summary/v1",
        "contract": journal.get("contract"),
        "operation": journal.get("operation"),
        "status": journal.get("status"),
        "ok": journal.get("ok"),
        "verification_strength": journal.get("verification_strength"),
        "business_state_verified": journal.get("business_state_verified"),
        "assertion_count": len(assertions),
        "passed_assertion_count": passed,
        "failed_assertion_count": len(assertions) - passed,
        "assertions_canonical_sha256": canonical_sha256(assertions),
        "readback_count": len(readbacks),
        "readbacks_canonical_sha256": canonical_sha256(readbacks),
        "canonical_sha256": canonical_sha256(journal),
        "full_evidence_in_stdout": False,
    }
    if any(
        type(projected[name]) is not int
        for name in (
            "assertion_count",
            "passed_assertion_count",
            "failed_assertion_count",
            "readback_count",
        )
    ):
        return False
    return projected == expected


def _record_payload(record: Mapping[str, Any], *, index: int) -> Mapping[str, Any]:
    if record.get("succeeded") is False:
        _fail(f"Composer Broker record {index} did not succeed")
    payload = _mapping(record.get("payload"), label=f"Composer Broker payload {index}")
    if (
        payload.get("contract") != "waapi-skill.gateway-result/v1"
        or payload.get("ok") is not True
    ):
        _fail(f"Composer Broker payload {index} is not one successful Gateway result")
    return payload


def _gateway_arguments(record: Mapping[str, Any], *, index: int) -> tuple[str, ...]:
    value = record.get("gateway_arguments")
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(item, str) for item in value
    ):
        _fail(f"Composer Broker argv {index} is invalid")
    return tuple(value)


def _subcommand_arguments(argv: tuple[str, ...], subcommand: str) -> tuple[str, ...]:
    indexes = [index for index, value in enumerate(argv) if value == subcommand]
    if len(indexes) != 1:
        _fail(f"Composer Broker argv does not contain exactly one {subcommand!r}")
    return argv[indexes[0] + 1 :]


def _option(arguments: tuple[str, ...], name: str) -> str:
    indexes = [index for index, value in enumerate(arguments) if value == name]
    if len(indexes) != 1 or indexes[0] + 1 >= len(arguments):
        _fail(f"Composer argv is missing one exact {name} value")
    return arguments[indexes[0] + 1]


def _strict_action(arguments: tuple[str, ...]) -> Mapping[str, Any]:
    raw = _option(arguments, "--action-json")
    if len(raw.encode("utf-8")) > MAX_COMPOSER_ARCHIVE_ACTION_BYTES:
        _fail("Composer action exceeds its archive byte ceiling")
    try:
        action = json.loads(raw)
    except (json.JSONDecodeError, RecursionError, UnicodeError) as exc:
        raise ComposerArchiveError("Composer action is not strict JSON") from exc
    if not isinstance(action, Mapping):
        _fail("Composer action must be a JSON object")
    return dict(action)


def _handles(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        handle = value.get("handle")
        if isinstance(handle, str):
            found.add(handle)
        for child in value.values():
            found.update(_handles(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_handles(child))
    return found


def _handle_factory(handles: set[str]) -> tuple[Callable[[], str], list[str]]:
    remaining = sorted(handles)

    def create() -> str:
        if not remaining:
            raise OperationComposerError("Archived action is missing its generated handle.")
        return remaining.pop(0)

    return create, remaining


def _compact_action_projection(
    draft: Mapping[str, Any],
) -> tuple[str, set[str], set[str], Mapping[str, Any]]:
    result = _mapping(
        draft.get("action_result"),
        label="compact Composer action result",
    )
    summary = _mapping(
        draft.get("current_facts_summary"),
        label="compact Composer facts summary",
    )
    created = result.get("created_handles")
    affected = result.get("affected_handles")
    if (
        set(result)
        != {"contract", "action", "created_handles", "affected_handles"}
        or result.get("contract")
        != "waapi-skill.operation-draft-action-result/v1"
        or not isinstance(result.get("action"), str)
        or not isinstance(created, list)
        or not isinstance(affected, list)
        or not all(isinstance(handle, str) for handle in (*created, *affected))
        or len(set(created)) != len(created)
        or len(set(affected)) != len(affected)
        or set(summary)
        != {
            "contract",
            "target_count",
            "handle_count",
            "canonical_sha256",
        }
        or summary.get("contract")
        != "waapi-skill.operation-draft-facts-summary/v1"
        or type(summary.get("target_count")) is not int
        or type(summary.get("handle_count")) is not int
        or summary["target_count"] < 0
        or summary["handle_count"] < 0
        or not isinstance(summary.get("canonical_sha256"), str)
        or len(summary["canonical_sha256"]) != 64
        or "current_facts" in draft
    ):
        _fail("Compact Composer action projection is invalid")
    return str(result["action"]), set(created), set(affected), summary


def _draft_projection(payload: Mapping[str, Any], *, command: str) -> Mapping[str, Any]:
    if payload.get("command") != command:
        _fail(f"Composer payload command does not match {command!r}")
    return _mapping(payload.get("draft"), label=f"{command} Draft projection")


def _require_projection(
    draft: Mapping[str, Any],
    *,
    draft_id: str,
    revision: int,
    lifecycle_state: str,
    operation: str,
    version: str,
    schema_digest: str,
    projection: Mapping[str, Any],
) -> None:
    if (
        draft.get("draft_id") != draft_id
        or draft.get("revision") != revision
        or draft.get("lifecycle_state") != lifecycle_state
        or draft.get("binding")
        != {
            "operation": operation,
            "version": version,
            "schema_digest": schema_digest,
        }
    ):
        _fail("Composer Draft response does not match its immutable binding")
    for key, value in projection.items():
        if draft.get(key) != value:
            _fail(f"Composer Draft response {key!r} does not replay from its actions")


def validate_operation_draft_archive(
    *,
    state_directory: Path,
    steps: Sequence[Any],
    broker_records: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    """Rebuild one Composer flow from Broker facts and frozen local state."""

    draft_steps = [step for step in steps if step.subcommand in _DRAFT_SUBCOMMANDS]
    if not draft_steps:
        return None
    try:
        return _validate_operation_draft_archive(
            state_directory=state_directory,
            steps=steps,
            broker_records=broker_records,
        )
    except ComposerArchiveError:
        raise
    except (
        OperationComposerError,
        OperationDraftError,
        TransactionError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        raise ComposerArchiveError(f"Composer archive replay failed: {exc}") from exc


def _validate_operation_draft_archive(
    *,
    state_directory: Path,
    steps: Sequence[Any],
    broker_records: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    if len(steps) != len(broker_records):
        _fail("Composer Broker record count does not match the sealed protocol")
    starts = [step for step in steps if step.subcommand == "draft-start"]
    if len(starts) != 1:
        _fail("Composer protocol must contain exactly one draft-start")

    payloads: list[Mapping[str, Any]] = []
    arguments_by_step: list[tuple[str, ...]] = []
    for index, (step, raw_record) in enumerate(zip(steps, broker_records), start=1):
        record = _mapping(raw_record, label=f"Composer Broker record {index}")
        if record.get("step_name") != step.name:
            _fail(f"Composer Broker record {index} is out of order")
        argv = _gateway_arguments(record, index=index)
        arguments = _subcommand_arguments(argv, step.subcommand)
        payload = _record_payload(record, index=index)
        if payload.get("command") != step.subcommand:
            _fail(f"Composer Broker payload {index} command is inconsistent")
        payloads.append(payload)
        arguments_by_step.append(arguments)

    start_index = next(
        index for index, step in enumerate(steps) if step.subcommand == "draft-start"
    )
    start_payload = payloads[start_index]
    start_draft = _draft_projection(start_payload, command="draft-start")
    draft_id = start_draft.get("draft_id")
    authority = start_payload.get("task_authority")
    binding = _mapping(start_draft.get("binding"), label="draft-start binding")
    operation = binding.get("operation")
    version = binding.get("version")
    schema_digest = binding.get("schema_digest")
    if not all(isinstance(value, str) and value for value in (
        draft_id,
        authority,
        operation,
        version,
        schema_digest,
    )):
        _fail("draft-start evidence is missing its issued binding")

    durable = load_operation_draft_archive_record(state_directory, draft_id)
    if (
        durable.operation != operation
        or durable.version != version
        or durable.schema_digest != schema_digest
        or durable.authority_digest != operation_draft_authority_digest(authority)
    ):
        _fail("Durable Draft binding does not match draft-start evidence")
    if durable.composer_digest is None or durable.composition is None:
        _fail("Composer archive is missing its durable composition binding")

    composition = new_composition(operation, version)
    projection = composition_projection(operation, version, composition)
    _require_projection(
        start_draft,
        draft_id=draft_id,
        revision=1,
        lifecycle_state="editable",
        operation=operation,
        version=version,
        schema_digest=schema_digest,
        projection=projection,
    )
    revision = 1
    action_rows: list[dict[str, Any]] = []
    expected_audit_types = ["started"]
    checked_payload: Mapping[str, Any] | None = None
    preview_payload: Mapping[str, Any] | None = None

    for step, payload, arguments in zip(steps, payloads, arguments_by_step):
        if step.subcommand == "draft-start":
            continue
        if step.subcommand == "draft-apply":
            if len(action_rows) >= MAX_COMPOSER_ARCHIVE_ACTIONS:
                _fail("Composer archive action count exceeds its fixed ceiling")
            action = _strict_action(arguments)
            response_draft = _draft_projection(payload, command="draft-apply")
            response_facts = response_draft.get("current_facts")
            compact: tuple[str, set[str], set[str], Mapping[str, Any]] | None = None
            if isinstance(response_facts, list):
                new_handles = _handles(response_facts) - _handles(
                    composition_projection(operation, version, composition)[
                        "current_facts"
                    ]
                )
            else:
                compact = _compact_action_projection(response_draft)
                new_handles = compact[1]
            factory, unused_handles = _handle_factory(new_handles)
            composition, action_name = apply_composer_action(
                operation,
                version,
                composition,
                action,
                handle_factory=factory,
            )
            if unused_handles:
                _fail("Composer action response disclosed an unexplained handle")
            revision += 1
            projection = composition_projection(operation, version, composition)
            if compact is None:
                _require_projection(
                    response_draft,
                    draft_id=draft_id,
                    revision=revision,
                    lifecycle_state="editable",
                    operation=operation,
                    version=version,
                    schema_digest=schema_digest,
                    projection=projection,
                )
            else:
                compact_action, _created, affected, summary = compact
                expected_affected = {
                    value
                    for key, value in action.items()
                    if key.endswith("_handle") and isinstance(value, str)
                }
                facts = projection["current_facts"]
                if (
                    compact_action != action_name
                    or affected != expected_affected
                    or summary["target_count"] != len(facts)
                    or summary["handle_count"] != len(_handles(facts))
                    or summary["canonical_sha256"] != canonical_sha256(facts)
                ):
                    _fail("Compact Composer action summary does not replay")
            action_rows.append(
                {
                    "step_name": step.name,
                    "revision": revision,
                    "action": action_name,
                    "action_sha256": canonical_sha256(action),
                    "action_request": action,
                }
            )
            expected_audit_types.append(f"action.{action_name}")
        elif step.subcommand == "draft-inspect":
            response_draft = _draft_projection(payload, command="draft-inspect")
            _require_projection(
                response_draft,
                draft_id=draft_id,
                revision=revision,
                lifecycle_state="editable",
                operation=operation,
                version=version,
                schema_digest=schema_digest,
                projection=composition_projection(operation, version, composition),
            )
        elif step.subcommand == "draft-check":
            revision += 1
            response_draft = _draft_projection(payload, command="draft-check")
            checked_projection = composition_projection(
                operation,
                version,
                composition,
            )
            if isinstance(response_draft.get("check"), Mapping):
                checked_projection["allowed_actions"] = [
                    action
                    for action in checked_projection["allowed_actions"]
                    if action != "check"
                ]
                checked_projection["allowed_actions"].extend(
                    ["check", "preview-from-draft"]
                )
            _require_projection(
                response_draft,
                draft_id=draft_id,
                revision=revision,
                lifecycle_state="editable",
                operation=operation,
                version=version,
                schema_digest=schema_digest,
                projection=checked_projection,
            )
            expected_audit_types.append("checked")
            checked_payload = response_draft
        elif step.subcommand == "draft-cancel":
            revision += 1
            response_draft = _draft_projection(payload, command="draft-cancel")
            _require_projection(
                response_draft,
                draft_id=draft_id,
                revision=revision,
                lifecycle_state="cancelled",
                operation=operation,
                version=version,
                schema_digest=schema_digest,
                projection=composition_projection(operation, version, composition),
            )
            expected_audit_types.append("cancelled")
        elif step.subcommand == "preview-from-draft":
            preview_payload = payload

    if durable.composition != composition:
        _fail("Durable Draft composition does not replay from the archived actions")
    actual_audit_types = [event["event_type"] for event in durable.audit]
    if preview_payload is not None:
        expected_audit_types.extend(("seal_reserved", "sealed"))
        revision += 2
    if actual_audit_types != expected_audit_types or durable.revision != revision:
        _fail("Durable Draft audit does not match the archived action sequence")
    if durable.state is OperationDraftState.CANCELLED:
        canonical = None
        preview_binding = None
        cleanup = None
    else:
        if (
            preview_payload is None
            or checked_payload is None
            or durable.state is not OperationDraftState.SEALED
            or durable.seal is None
            or durable.check is None
        ):
            _fail("Composer archive is missing check or sealed Preview evidence")
        canonical = durable.seal["request"]
        transaction_id = durable.seal["transaction_id"]
        artifact_hash = durable.seal["artifact_hash"]
        if (
            preview_payload.get("transaction_id") != transaction_id
            or preview_payload.get("artifact_hash") != artifact_hash
            or preview_payload.get("state") != durable.seal["transaction_state"]
        ):
            _fail("Composer Preview response does not match the durable seal")
        preview_agent = _mapping(
            preview_payload.get("agent_result"),
            label="Composer Preview agent_result",
        )
        if (
            preview_agent.get("request") != canonical
            or preview_agent.get("transaction_id") != transaction_id
            or preview_agent.get("artifact_hash") != artifact_hash
            or (
                "cleanup" in preview_payload
                and preview_agent.get("cleanup") != preview_payload["cleanup"]
            )
        ):
            _fail("Composer Preview agent_result is not bound to the canonical request")

        transaction = load_transaction_archive_snapshot(state_directory, transaction_id)
        artifact = _mapping(transaction.preview.artifact, label="Composer Preview artifact")
        prepared = _mapping(
            artifact.get("prepared_operation"),
            label="Composer prepared operation",
        )
        if (
            transaction.preview.artifact_hash != artifact_hash
            or artifact.get("request") != canonical
            or prepared.get("request") != canonical
        ):
            _fail("Composer transaction artifact is not canonical-request equivalent")
        expected_preview_cleanup = transaction_cleanup_payload(
            prepared,
            phase="preview",
        )
        if preview_payload.get("cleanup") != expected_preview_cleanup:
            _fail("Composer Preview cleanup does not replay from its immutable spec")
        preview_step = next(
            step for step in steps if step.subcommand == "preview-from-draft"
        )
        draft_label = preview_step.name.split(".", 1)[0]
        transaction_payloads = [
            payload
            for step, payload in zip(steps, payloads)
            if step.name.startswith(f"{draft_label}.")
            and step.subcommand
            in {"transaction-show", "confirm", "reject", "execute", "verify"}
        ]
        if any(payload.get("transaction_id") != transaction_id for payload in transaction_payloads):
            _fail("Composer transaction commands do not share the sealed transaction ID")
        for parent in transaction_payloads:
            if "agent_result" not in parent:
                continue
            agent_result = _mapping(
                parent["agent_result"],
                label="Composer transaction agent_result",
            )
            if (
                agent_result.get("request") != canonical
                or agent_result.get("transaction_id") != transaction_id
                or agent_result.get("artifact_hash") != artifact_hash
            ):
                _fail("Composer transaction agent_result drifted from its sealed request")
            if "cleanup" in parent and agent_result.get("cleanup") != parent["cleanup"]:
                _fail("Composer transaction cleanup projections disagree")
        cleanup = None
        for payload in reversed(transaction_payloads):
            if "cleanup" in payload:
                cleanup = payload["cleanup"]
                break
        execution_result: Mapping[str, Any] = {}
        for event in transaction.events:
            if event.get("event_type") != "execution_completed":
                continue
            details = event.get("details")
            if isinstance(details, Mapping) and isinstance(
                details.get("dispatch_result"), Mapping
            ):
                execution_result = details["dispatch_result"]
        final_event_type = transaction.events[-1].get("event_type")
        cleanup_phase = (
            "verified"
            if final_event_type == "verification_recorded"
            else "indeterminate"
            if final_event_type == "execution_indeterminate"
            else "execution_cancelled"
            if final_event_type == "execution_cancelled"
            else "executed"
            if final_event_type == "execution_completed"
            else "preview"
        )
        expected_cleanup = transaction_cleanup_payload(
            prepared,
            phase=cleanup_phase,
            execution_result=execution_result,
        )
        if cleanup != expected_cleanup:
            _fail("Composer cleanup outcome does not replay from its immutable spec")
        final_event_details = _mapping(
            transaction.events[-1].get("details"),
            label="Composer final transaction event details",
        )
        final_transaction_payload = transaction_payloads[-1] if transaction_payloads else {}
        if (
            "verification" in final_transaction_payload
            and not _verification_projection_matches_journal(
                final_transaction_payload["verification"],
                final_event_details.get("verification"),
            )
        ):
            _fail("Composer verification result does not match the transaction journal")
        preview_binding = {
            "transaction_id": transaction_id,
            "artifact_hash": artifact_hash,
            "transaction_final_state": transaction.record.state.value,
            "transaction_event_count": len(transaction.events),
            "transaction_last_event_hash": transaction.record.last_event_hash,
            "cleanup_spec_sha256": canonical_sha256(
                prepared.get("cleanup", {"kind": "none"})
            ),
        }

    evidence: dict[str, Any] = {
        "contract": COMPOSER_ARCHIVE_CONTRACT,
        "draft_id": draft_id,
        "operation": operation,
        "version": version,
        "lifecycle_state": durable.state.value,
        "final_revision": durable.revision,
        "schema_digest": durable.schema_digest,
        "composer_digest": durable.composer_digest,
        "limits_digest": durable.limits_digest,
        "actions": action_rows,
        "check": durable.check,
        "canonical_request": canonical,
        "canonical_request_sha256": (
            None if canonical is None else canonical_sha256(canonical)
        ),
        "preview_binding": preview_binding,
        "cleanup_outcome": cleanup,
    }
    if len(canonical_json_bytes(evidence)) > MAX_COMPOSER_ARCHIVE_BYTES:
        _fail("Composer evidence exceeds its fixed archive byte ceiling")
    return evidence
