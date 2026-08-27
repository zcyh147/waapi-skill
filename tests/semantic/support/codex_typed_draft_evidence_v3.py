"""Strict current typed-Draft evidence validation for semantic protocols."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from tests.semantic.support.codex_gateway_broker import (
    DraftTypedActionArgument,
    DraftTypedActionBatchArgument,
    GatewayInvocationError,
    dependency_free_draft_action_block,
    draft_compact_action_result,
    project_required_metadata_tokens,
)
from tests.semantic.support.codex_gateway_contracts import gateway_payload_contracts

from wwise_waapi.canonical import canonical_json_bytes, canonical_sha256
from wwise_waapi.business_adapters import business_adapter
from wwise_waapi.business_declaration_state import BusinessDeclarationSession
from wwise_waapi.operation_composer import (
    OperationComposerError,
    apply_composer_action,
    composition_projection,
    materialize_operation_request,
    new_composition,
    operation_composer_contract,
    operation_draft_construction_boundary,
    operation_draft_public_projection,
    parse_typed_action_cli_arguments,
    parse_typed_action_cli_argument_sequence,
)
from wwise_waapi.operation_drafts import (
    OperationDraftError,
    OperationDraftRecord,
    OperationDraftState,
    load_operation_draft_archive_records,
    operation_draft_authority_digest,
)
from wwise_waapi.operation_registry import operation_uses_business_declaration
from wwise_waapi.transaction_cleanup import transaction_cleanup_payload
from wwise_waapi.transactions import (
    TransactionError,
    load_transaction_archive_snapshot,
)
from wwise_waapi.typed_requests import request_contract


TYPED_DRAFT_EVIDENCE_CONTRACT = "waapi-skill.codex-typed-draft-evidence/v1"
BUSINESS_DRAFT_EVIDENCE_CONTRACT = (
    "waapi-skill.codex-business-draft-evidence/v1"
)
MAX_TYPED_DRAFT_EVIDENCE_ACTIONS = 512
MAX_TYPED_DRAFT_EVIDENCE_BYTES = 1024 * 1024
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
_BUSINESS_DRAFT_EVENT_OPTIONS = {
    "draft-start": frozenset({"started"}),
    "draft-add-media": frozenset({"declaration.revised"}),
    "draft-bind-field": frozenset({"handles.bound"}),
    "draft-bind-object": frozenset({"handles.bound"}),
    "draft-business-configure": frozenset({"settings.revised"}),
    "draft-declare-import-batch": frozenset({"declaration.batch-added"}),
    "draft-clear-object-list": frozenset(
        {"declaration.added", "declaration.revised"}
    ),
    "draft-declare-existing": frozenset({"declaration.added"}),
    "draft-declare-field-change": frozenset({"declaration.added"}),
    "draft-declare-new": frozenset({"declaration.added"}),
    "draft-declare-object-change": frozenset({"declaration.added"}),
    "draft-declare-rtpc": frozenset({"declaration.added"}),
    "draft-declare-switch-assignment": frozenset({"declaration.added"}),
    "draft-declare-soundbank-plan": frozenset({"settings.revised"}),
    "draft-declare-artifact-plan": frozenset({"settings.revised"}),
    "draft-declare-ui-plan": frozenset({"settings.revised"}),
    "draft-add-ui-command": frozenset({"settings.revised"}),
    "draft-discover-fields": frozenset({"handles.bound"}),
    "draft-discover-types": frozenset({"handles.bound"}),
    "draft-remove-declaration": frozenset({"declaration.removed"}),
    "draft-revise-declaration": frozenset({"declaration.revised"}),
    "draft-check": frozenset({"checked"}),
    "preview-from-draft": frozenset({"seal_reserved", "sealed"}),
    "draft-cancel": frozenset({"cancelled"}),
}


class TypedDraftEvidenceError(RuntimeError):
    """Current typed-Draft evidence is inconsistent or not replayable."""


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
    raise TypedDraftEvidenceError(message)


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


def _record_payload(
    record: Mapping[str, Any],
    *,
    index: int,
    subcommand: str,
) -> Mapping[str, Any]:
    if record.get("succeeded") is False:
        _fail(f"Composer Broker record {index} did not succeed")
    payload = _mapping(record.get("payload"), label=f"Composer Broker payload {index}")
    if (
        payload.get("contract") not in gateway_payload_contracts(subcommand)
        or payload.get("ok") is not True
    ):
        _fail(f"Composer Broker payload {index} has an invalid success contract")
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


def _strict_action(
    arguments: tuple[str, ...],
    *,
    operation: str,
    version: str,
) -> Mapping[str, Any]:
    contract = operation_composer_contract(operation, version)
    limits = _mapping(contract.get("limits"), label="Composer contract limits")
    action_bytes = limits.get("action_bytes")
    if type(action_bytes) is not int or action_bytes <= 0:
        _fail("Composer contract is missing its action byte ceiling")
    if "--action-json" in arguments:
        _fail("Current typed-Draft evidence cannot contain historical action JSON")
    try:
        facts_index = arguments.index("--facts")
        action = parse_typed_action_cli_arguments(arguments[facts_index + 1 :])
    except (OperationComposerError, ValueError) as exc:
        raise TypedDraftEvidenceError("Composer typed action argv is invalid") from exc
    try:
        canonical_action_size = len(canonical_json_bytes(action))
    except (RecursionError, TypeError, UnicodeError, ValueError) as exc:
        raise TypedDraftEvidenceError("Composer typed action is not canonical") from exc
    if canonical_action_size > action_bytes:
        _fail("Composer action exceeds its archive byte ceiling")
    if not isinstance(action, Mapping):
        _fail("Composer action must be a JSON object")
    return dict(action)


def _strict_actions(
    arguments: tuple[str, ...],
    *,
    operation: str,
    version: str,
) -> tuple[Mapping[str, Any], ...]:
    if "--action-json" in arguments:
        _fail("Current typed-Draft evidence cannot contain historical action JSON")
    try:
        facts_index = arguments.index("--facts")
        actions = parse_typed_action_cli_argument_sequence(
            arguments[facts_index + 1 :]
        )
    except (OperationComposerError, ValueError) as exc:
        raise TypedDraftEvidenceError("Composer typed action argv is invalid") from exc
    contract = operation_composer_contract(operation, version)
    limits = _mapping(contract.get("limits"), label="Composer contract limits")
    action_bytes = limits.get("action_bytes")
    if type(action_bytes) is not int or action_bytes <= 0:
        _fail("Composer contract is missing its action byte ceiling")
    result: list[Mapping[str, Any]] = []
    for action in actions:
        if len(canonical_json_bytes(action)) > action_bytes:
            _fail("Composer action exceeds its archive byte ceiling")
        result.append(dict(action))
    return tuple(result)


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


def _handles_in_order(value: Any) -> tuple[str, ...]:
    found: list[str] = []
    seen: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            handle = item.get("handle")
            if isinstance(handle, str) and handle not in seen:
                seen.add(handle)
                found.append(handle)
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return tuple(found)


def _handle_factory(handles: set[str]) -> tuple[Callable[[], str], list[str]]:
    remaining = sorted(handles)

    def create() -> str:
        if not remaining:
            raise OperationComposerError("Archived action is missing its generated handle.")
        return remaining.pop(0)

    return create, remaining


def _compact_action_projection(
    draft: Mapping[str, Any],
    *,
    read_only: bool = False,
) -> tuple[str, set[str], set[str], Mapping[str, Any]]:
    expected_integrity = {
        "complete": True,
        "truncated": False,
        "projection": "action_delta_and_draft_receipt",
        "compact_projection_is_not_truncation": True,
        "construction_boundary": operation_draft_construction_boundary(
            read_only=read_only
        ),
    }
    if draft.get("response_integrity") != expected_integrity:
        _fail("Compact Composer action response integrity does not replay")
    try:
        return draft_compact_action_result(draft)
    except GatewayInvocationError as exc:
        raise TypedDraftEvidenceError(
            "Compact Composer action projection is invalid"
        ) from exc


def _compact_checked_projection(
    draft: Mapping[str, Any],
    *,
    current_facts: list[Any],
    read_only: bool = False,
) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    summary = _mapping(
        draft.get("current_facts_summary"),
        label="checked Composer facts summary",
    )
    integrity = _mapping(
        draft.get("response_integrity"),
        label="checked Composer response integrity",
    )
    expected_summary = {
        "contract": "waapi-skill.operation-draft-facts-summary/v1",
        "target_count": len(current_facts),
        "handle_count": len(_handles(current_facts)),
        "canonical_sha256": canonical_sha256(current_facts),
    }
    expected_integrity = {
        "complete": True,
        "truncated": False,
        "projection": "checked_draft_receipt",
        "compact_projection_is_not_truncation": True,
        "draft_inspect_required_before_preview": False,
    }
    expected_construction_state = {
        "draft_complete": True,
        "preview_created": False,
        "required_next_phase": "preview-from-draft",
        "execute_returned_next_command_exactly": True,
        "construction_boundary": operation_draft_construction_boundary(
            read_only=read_only
        ),
    }
    if (
        "current_facts" in draft
        or summary != expected_summary
        or integrity != expected_integrity
        or draft.get("construction_state") != expected_construction_state
    ):
        _fail("Compact Composer check receipt does not replay")
    return expected_summary, expected_integrity, expected_construction_state


def _direct_read_binding(
    payload: Mapping[str, Any],
    *,
    operation: str,
    version: str,
    schema_digest: str,
    canonical_request: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Validate and seal one read-only Draft terminal without a Draft write."""

    arguments = canonical_request.get("arguments")
    if (
        canonical_request.get("operation") != "waapi.call"
        or canonical_request.get("version") != version
        or not isinstance(arguments, Mapping)
        or arguments.get("api") != operation
        or not isinstance(arguments.get("args"), Mapping)
        or not isinstance(arguments.get("options"), Mapping)
    ):
        _fail("read-only Draft result does not replay one canonical typed call")
    if payload.get("typed_request") != {
        "contract": "waapi-skill.typed-request/v1",
        "schema_digest": schema_digest,
    }:
        _fail("read-only Draft result differs from its typed request binding")
    call = payload.get("call")
    if (
        payload.get("ok") is not True
        or payload.get("status") != "ok"
        or payload.get("api_attempted") != operation
        or not isinstance(call, Mapping)
        or call.get("api") != operation
        or call.get("version") != version
        or call.get("ok") is not True
        or call.get("dry_run") is not False
        or not isinstance(call.get("evidence_path"), str)
        or not call["evidence_path"]
    ):
        _fail("read-only Draft result differs from its exact live call binding")
    validation = payload.get("schema_validation")
    request_validation = (
        validation.get("request") if isinstance(validation, Mapping) else None
    )
    result_validation = (
        validation.get("result") if isinstance(validation, Mapping) else None
    )
    if any(
        not isinstance(row, Mapping)
        or row.get("uri") != operation
        or row.get("version") != version
        for row in (request_validation, result_validation)
    ):
        _fail("read-only Draft result differs from its schema validation binding")
    if "agent_result" not in payload:
        _fail("read-only Draft result must contain its exact agent_result")
    post_filter = payload.get("post_filter")
    return {
        "api": operation,
        "canonical_request_sha256": canonical_sha256(canonical_request),
        "call_evidence_path": call["evidence_path"],
        "call_sha256": canonical_sha256(call),
        "schema_validation_sha256": canonical_sha256(validation),
        "post_filter_sha256": (
            None if post_filter is None else canonical_sha256(post_filter)
        ),
        "agent_result_sha256": canonical_sha256(payload["agent_result"]),
    }


def _draft_projection(payload: Mapping[str, Any], *, command: str) -> Mapping[str, Any]:
    if payload.get("command") != command:
        _fail(f"Composer payload command does not match {command!r}")
    return _mapping(payload.get("draft"), label=f"{command} Draft projection")


def _canonical_typed_action(
    action: Mapping[str, Any],
) -> tuple[Mapping[str, Any], str]:
    submitted_name = action.get("action")
    if not isinstance(submitted_name, str) or not submitted_name:
        _fail("Composer archive action name is invalid")
    return action, submitted_name


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
    expected_projection = dict(projection)
    if lifecycle_state != "editable" and isinstance(
        expected_projection.get("allowed_actions"), list
    ):
        expected_projection["allowed_actions"] = []
    expected_projection = operation_draft_public_projection(expected_projection)
    if not all(
        draft.get(key) == value for key, value in expected_projection.items()
    ):
        mismatched = next(
            (
                key
                for key, value in expected_projection.items()
                if draft.get(key) != value
            ),
            "projection",
        )
        _fail(
            f"Composer Draft response {mismatched!r} does not replay from its actions"
        )


def validate_typed_draft_evidence(
    *,
    state_directory: Path,
    steps: Sequence[Any],
    broker_records: Sequence[Mapping[str, Any]],
    allow_cleaned_file_evidence: bool = False,
) -> Mapping[str, Any] | None:
    """Rebuild one Composer flow from Broker facts and frozen local state."""

    draft_steps = [step for step in steps if step.subcommand in _DRAFT_SUBCOMMANDS]
    if not draft_steps:
        return None
    try:
        if len(steps) != len(broker_records):
            _fail("Composer Broker record count does not match the sealed protocol")
        draft_ids: list[str] = []
        for index, (step, raw_record) in enumerate(
            zip(steps, broker_records, strict=False),
            start=1,
        ):
            if step.subcommand != "draft-start":
                continue
            record = _mapping(raw_record, label=f"Composer Broker record {index}")
            payload = _record_payload(
                record,
                index=index,
                subcommand=step.subcommand,
            )
            draft = _draft_projection(payload, command="draft-start")
            draft_id = draft.get("draft_id")
            if not isinstance(draft_id, str) or not draft_id:
                _fail("draft-start evidence is missing its issued Draft id")
            draft_ids.append(draft_id)
        durable_records = (
            load_operation_draft_archive_records(
                state_directory,
                draft_ids,
                allow_cleaned_file_evidence=allow_cleaned_file_evidence,
            )
            if draft_ids
            else {}
        )
        return _validate_typed_draft_evidence(
            state_directory=state_directory,
            steps=steps,
            broker_records=broker_records,
            durable_records=durable_records,
            allow_cleaned_file_evidence=allow_cleaned_file_evidence,
        )
    except TypedDraftEvidenceError:
        raise
    except (
        OperationComposerError,
        OperationDraftError,
        TransactionError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        raise TypedDraftEvidenceError(f"Composer archive replay failed: {exc}") from exc


def _composer_flow_step_indexes(
    steps: Sequence[Any],
    prefix: str,
) -> tuple[int, ...]:
    """Keep one Composer flow together with its exact external metadata proofs."""

    owned_indexes = tuple(
        index
        for index, step in enumerate(steps)
        if step.name == prefix or step.name.startswith(f"{prefix}.")
    )
    dependency_names: set[str] = set()
    for index in owned_indexes:
        step = steps[index]
        step_binding = getattr(step, "metadata_binding", None)
        if step_binding is not None:
            dependency_names.add(step_binding.step)
        for argument in step.arguments:
            expected_actions = (
                (argument,)
                if isinstance(argument, DraftTypedActionArgument)
                else (
                    argument.actions
                    if isinstance(argument, DraftTypedActionBatchArgument)
                    else ()
                )
            )
            dependency_names.update(
                action.metadata_binding.step
                for action in expected_actions
                if action.metadata_binding is not None
            )
    return tuple(
        index
        for index, step in enumerate(steps)
        if index in owned_indexes or step.name in dependency_names
    )


def _validate_business_draft_evidence(
    *,
    operation: str,
    version: str,
    schema_digest: str,
    draft_id: str,
    durable: OperationDraftRecord,
    steps: Sequence[Any],
    payloads: Sequence[Mapping[str, Any]],
    allow_cleaned_file_evidence: bool,
) -> Mapping[str, Any]:
    event_options: list[frozenset[str]] = []
    response_revisions: list[int] = []
    preview_payload: Mapping[str, Any] | None = None
    for step, payload in zip(steps, payloads, strict=True):
        options = _BUSINESS_DRAFT_EVENT_OPTIONS.get(step.subcommand)
        if options is not None:
            event_options.extend(
                (options, options)
                if step.subcommand == "preview-from-draft"
                else (options,)
            )
        if step.subcommand == "preview-from-draft":
            preview_payload = payload
        raw_draft = payload.get("draft")
        if not isinstance(raw_draft, Mapping):
            continue
        binding = _mapping(
            raw_draft.get("binding"),
            label=f"{step.subcommand} business Draft binding",
        )
        revision = raw_draft.get("revision")
        if (
            raw_draft.get("contract") != "waapi-skill.operation-draft/v1"
            or raw_draft.get("draft_id") != draft_id
            or binding
            != {
                "operation": operation,
                "version": version,
                "schema_digest": schema_digest,
            }
            or isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 1
        ):
            _fail("Business Draft response does not preserve its immutable binding")
        response_revisions.append(revision)
        integrity = raw_draft.get("response_integrity")
        if integrity is not None and (
            not isinstance(integrity, Mapping)
            or integrity.get("complete") is not True
            or integrity.get("truncated") is not False
        ):
            _fail("Business Draft compact response integrity is invalid")

    audit_types = tuple(str(event["event_type"]) for event in durable.audit)
    if (
        len(audit_types) != len(event_options)
        or any(
            event_type not in allowed
            for event_type, allowed in zip(audit_types, event_options, strict=True)
        )
        or durable.revision != len(audit_types)
        or any(
            later <= earlier
            for earlier, later in zip(
                response_revisions,
                response_revisions[1:],
                strict=False,
            )
        )
        or any(revision > durable.revision for revision in response_revisions)
    ):
        _fail("Durable Business Draft audit does not match the Broker command sequence")

    if durable.composition is None:
        _fail("Business Draft archive is missing its durable composition")
    raw_session = durable.composition.get("business_session")
    if raw_session is None:
        session = None
        canonical_request = None
        session_summary = None
    else:
        if not isinstance(raw_session, Mapping):
            _fail("Business Draft session is not an object")
        try:
            session = BusinessDeclarationSession.from_dict(raw_session)
            canonical_request = _materialize_archived_business_request(
                operation,
                session,
                allow_cleaned_file_evidence=allow_cleaned_file_evidence,
            )
        except (TypeError, ValueError) as exc:
            raise TypedDraftEvidenceError(
                "Business Draft declarations cannot replay their canonical request"
            ) from exc
        session_summary = {
            "revision": session.revision,
            "declaration_count": len(session.declarations),
            "canonical_sha256": canonical_sha256(raw_session),
        }

    if durable.check is not None:
        if (
            canonical_request is None
            or durable.check.get("request_digest")
            != canonical_sha256(canonical_request)
        ):
            _fail("Business Draft check is not bound to its canonical request")
    if durable.seal is not None:
        if (
            canonical_request is None
            or durable.seal.get("request") != canonical_request
            or preview_payload is None
            or preview_payload.get("transaction_id")
            != durable.seal.get("transaction_id")
            or preview_payload.get("artifact_hash")
            != durable.seal.get("artifact_hash")
        ):
            _fail("Business Draft Preview is not bound to its durable canonical request")
        preview_binding: Mapping[str, Any] | None = {
            "transaction_id": durable.seal["transaction_id"],
            "artifact_hash": durable.seal["artifact_hash"],
            "transaction_state": durable.seal["transaction_state"],
        }
    else:
        preview_binding = None

    evidence = {
        "contract": BUSINESS_DRAFT_EVIDENCE_CONTRACT,
        "draft_id": draft_id,
        "operation": operation,
        "version": version,
        "schema_digest": schema_digest,
        "lifecycle_state": durable.state.value,
        "revision": durable.revision,
        "command_count": len(steps),
        "command_sequence": [step.subcommand for step in steps],
        "audit_types": list(audit_types),
        "business_session": session_summary,
        "canonical_request": canonical_request,
        "preview_binding": preview_binding,
        "archive_sha256": canonical_sha256(
            {
                "composition": durable.composition,
                "audit": list(durable.audit),
                "check": durable.check,
                "seal": durable.seal,
            }
        ),
    }
    if len(canonical_json_bytes(evidence)) > MAX_TYPED_DRAFT_EVIDENCE_BYTES:
        _fail("Business Draft evidence exceeds its fixed archive byte ceiling")
    return evidence


def _materialize_archived_business_request(
    operation: str,
    session: BusinessDeclarationSession,
    *,
    allow_cleaned_file_evidence: bool,
) -> Mapping[str, Any]:
    """Apply cleaned-file replay only to an Adapter that owns that aperture."""

    adapter = business_adapter(operation)
    return adapter.materialize(
        session,
        allow_cleaned_file_evidence=(
            allow_cleaned_file_evidence
            and adapter.supports_cleaned_file_evidence
        ),
    )


def _validate_typed_draft_evidence(
    *,
    state_directory: Path,
    steps: Sequence[Any],
    broker_records: Sequence[Mapping[str, Any]],
    durable_records: Mapping[str, OperationDraftRecord],
    allow_cleaned_file_evidence: bool = False,
) -> Mapping[str, Any]:
    if len(steps) != len(broker_records):
        _fail("Composer Broker record count does not match the sealed protocol")
    starts = [step for step in steps if step.subcommand == "draft-start"]
    if len(starts) > 1:
        prefixes: list[str] = []
        for start in starts:
            suffix = ".draft-start"
            if not start.name.endswith(suffix):
                _fail("Multi-Composer draft-start names must have one flow prefix")
            prefix = start.name[: -len(suffix)]
            if not prefix or prefix in prefixes:
                _fail("Multi-Composer flow prefixes must be unique")
            prefixes.append(prefix)
        flows: list[Mapping[str, Any]] = []
        for prefix in prefixes:
            indexes = _composer_flow_step_indexes(steps, prefix)
            if not indexes:
                _fail("Multi-Composer flow has no archived steps")
            flows.append(
                _validate_typed_draft_evidence(
                    state_directory=state_directory,
                    steps=tuple(steps[index] for index in indexes),
                    broker_records=tuple(broker_records[index] for index in indexes),
                    durable_records=durable_records,
                    allow_cleaned_file_evidence=allow_cleaned_file_evidence,
                )
            )
        evidence = {
            "contract": TYPED_DRAFT_EVIDENCE_CONTRACT,
            "flow_count": len(flows),
            "flows": flows,
            "flows_sha256": canonical_sha256(flows),
        }
        if len(canonical_json_bytes(evidence)) > MAX_TYPED_DRAFT_EVIDENCE_BYTES:
            _fail("Composer evidence exceeds its fixed archive byte ceiling")
        return evidence
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
        payload = _record_payload(
            record,
            index=index,
            subcommand=step.subcommand,
        )
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

    durable = durable_records.get(draft_id)
    if durable is None:
        _fail("Composer Draft archive is missing its bound record")
    if (
        durable.operation != operation
        or durable.version != version
        or durable.schema_digest != schema_digest
        or durable.authority_digest != operation_draft_authority_digest(authority)
    ):
        _fail("Durable Draft binding does not match draft-start evidence")
    if durable.composer_digest is None or durable.composition is None:
        _fail("Composer archive is missing its durable composition binding")

    if operation_uses_business_declaration(operation, version):
        return _validate_business_draft_evidence(
            operation=operation,
            version=version,
            schema_digest=schema_digest,
            draft_id=draft_id,
            durable=durable,
            steps=steps,
            payloads=payloads,
            allow_cleaned_file_evidence=allow_cleaned_file_evidence,
        )

    composition = new_composition(operation, version)
    read_only_draft = (
        operation.startswith("ak.")
        and request_contract(version, operation).effect == "read"
    )

    rebatchable_action_indexes: set[int] = set()
    action_index = 0
    while action_index < len(steps):
        block = dependency_free_draft_action_block(steps, action_index)
        if block is None:
            action_index += 1
            continue
        block_indexes, block_expected_actions = block
        actual_count = sum(
            len(
                _strict_actions(
                    arguments_by_step[index],
                    operation=operation,
                    version=version,
                )
            )
            for index in block_indexes
        )
        if actual_count != len(block_expected_actions):
            _fail(
                "Composer archive dependency-free action block count drifted"
            )
        rebatchable_action_indexes.update(block_indexes)
        action_index = block_indexes[-1] + 1

    def project(value: Mapping[str, Any]) -> dict[str, Any]:
        return composition_projection(
            operation,
            version,
            value,
            allow_cleaned_file_evidence=allow_cleaned_file_evidence,
        )

    projection = project(composition)
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
    direct_read_binding: Mapping[str, Any] | None = None

    for step_index, (step, payload, arguments) in enumerate(
        zip(steps, payloads, arguments_by_step)
    ):
        if step.subcommand == "draft-start":
            continue
        if step.subcommand == "draft-apply":
            actions = _strict_actions(
                arguments,
                operation=operation,
                version=version,
            )
            if len(action_rows) + len(actions) > MAX_TYPED_DRAFT_EVIDENCE_ACTIONS:
                _fail("Composer archive action count exceeds its fixed ceiling")
            expected_argument = step.arguments[-1]
            expected_actions = (
                (expected_argument,)
                if isinstance(expected_argument, DraftTypedActionArgument)
                else (
                    expected_argument.actions
                    if isinstance(expected_argument, DraftTypedActionBatchArgument)
                    else ()
                )
            )
            if not expected_actions or (
                len(expected_actions) != len(actions)
                and step_index not in rebatchable_action_indexes
            ):
                _fail("Composer archive action lacks its typed protocol argument")
            for metadata_binding in (
                expected.metadata_binding
                for expected in expected_actions
                if expected.metadata_binding is not None
            ):
                source_indexes = tuple(
                    index
                    for index, candidate in enumerate(steps)
                    if candidate.name == metadata_binding.step
                    and candidate.subcommand == "metadata"
                )
                if len(source_indexes) != 1:
                    _fail("Composer archive metadata source is unavailable")
                source_step = steps[source_indexes[0]]
                if (
                    len(source_step.arguments) < 3
                    or source_step.arguments[1] not in {"--object-type", "--object"}
                    or not isinstance(source_step.arguments[2], str)
                ):
                    _fail("Composer archive metadata scope is invalid")
                try:
                    source_projection = project_required_metadata_tokens(
                        payloads[source_indexes[0]],
                        object_type=metadata_binding.object_type,
                        required_tokens=metadata_binding.required_tokens,
                        scope_flag=source_step.arguments[1],
                        scope_value=source_step.arguments[2],
                    )
                except GatewayInvocationError as exc:
                    raise TypedDraftEvidenceError(
                        "Composer archive metadata source is invalid"
                    ) from exc
                if (
                    metadata_binding.expected_projection is not None
                    and source_projection != metadata_binding.expected_projection
                ):
                    _fail("Composer archive metadata projection drifted")
            response_draft = _draft_projection(payload, command="draft-apply")
            response_facts = response_draft.get("current_facts")
            compact: tuple[str, set[str], set[str], Mapping[str, Any]] | None = None
            if isinstance(response_facts, list):
                new_handles = _handles(response_facts) - _handles(
                    project(composition)["current_facts"]
                )
                ordered_handles = [
                    handle
                    for handle in _handles_in_order(response_facts)
                    if handle in new_handles
                ]
            else:
                compact = _compact_action_projection(
                    response_draft,
                    read_only=read_only_draft,
                )
                new_handles = compact[1]
                result = _mapping(
                    response_draft.get("action_result"),
                    label="compact Composer action result",
                )
                ordered_handles = list(result.get("created_handles", []))
                if set(ordered_handles) != new_handles:
                    _fail("Compact Composer created-handle order is invalid")
            remaining_handles = list(ordered_handles)

            def factory() -> str:
                if not remaining_handles:
                    _fail("Composer action response lacks one created handle")
                return remaining_handles.pop(0)

            action_results: list[tuple[Mapping[str, Any], str, str]] = []
            for action in actions:
                replay_action, submitted_action_name = _canonical_typed_action(action)
                composition, action_name = apply_composer_action(
                    operation,
                    version,
                    composition,
                    replay_action,
                    handle_factory=factory,
                    allow_cleaned_file_evidence=allow_cleaned_file_evidence,
                )
                action_results.append((action, submitted_action_name, action_name))
            if remaining_handles:
                _fail("Composer action response disclosed an unexplained handle")
            revision += len(actions)
            projection = project(composition)
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
                    for action in actions
                    for key, value in action.items()
                    if key.endswith("_handle") and isinstance(value, str)
                }
                facts = projection["current_facts"]
                if (
                    compact_action
                    not in (
                        {"batch"}
                        if len(actions) > 1
                        else {action_results[0][1], action_results[0][2]}
                    )
                    or affected != expected_affected
                    or summary["target_count"] != len(facts)
                    or summary["handle_count"] != len(_handles(facts))
                    or summary["canonical_sha256"] != canonical_sha256(facts)
                ):
                    _fail("Compact Composer action summary does not replay")
            first_revision = revision - len(actions) + 1
            for offset, (action, submitted_action_name, _action_name) in enumerate(
                action_results
            ):
                action_rows.append(
                    {
                        "step_name": step.name,
                        "revision": first_revision + offset,
                        "action": submitted_action_name,
                        "action_sha256": canonical_sha256(action),
                        "action_request": action,
                    }
                )
                expected_audit_types.append(f"action.{submitted_action_name}")
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
                projection=project(composition),
            )
        elif step.subcommand == "draft-check":
            if read_only_draft:
                try:
                    canonical_read_request = materialize_operation_request(
                        operation,
                        version,
                        composition,
                    )
                except OperationComposerError as exc:
                    raise TypedDraftEvidenceError(
                        "read-only Draft canonical request cannot be materialized"
                    ) from exc
                direct_read_binding = _direct_read_binding(
                    payload,
                    operation=operation,
                    version=version,
                    schema_digest=schema_digest,
                    canonical_request=canonical_read_request,
                )
                checked_payload = payload
                continue
            revision += 1
            response_draft = _draft_projection(payload, command="draft-check")
            checked_projection = project(composition)
            if isinstance(response_draft.get("check"), Mapping):
                checked_projection["allowed_actions"] = [
                    action
                    for action in checked_projection["allowed_actions"]
                    if action != "check"
                ]
                checked_projection["allowed_actions"].extend(
                    ["check", "preview-from-draft"]
                )
            if "current_facts" not in response_draft:
                current_facts = checked_projection.pop("current_facts")
                if not isinstance(current_facts, list):
                    _fail("Checked Composer replay lacks bounded current facts")
                summary, integrity, construction_state = _compact_checked_projection(
                    response_draft,
                    current_facts=current_facts,
                    read_only=read_only_draft,
                )
                checked_projection["current_facts_summary"] = summary
                checked_projection["response_integrity"] = integrity
                checked_projection["construction_state"] = construction_state
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
                projection=project(composition),
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
    elif read_only_draft:
        if (
            checked_payload is None
            or direct_read_binding is None
            or preview_payload is not None
            or durable.state is not OperationDraftState.EDITABLE
            or durable.check is not None
            or durable.seal is not None
        ):
            _fail("read-only Draft archive has an invalid direct-result terminal")
        try:
            canonical = materialize_operation_request(
                operation,
                version,
                composition,
            )
        except OperationComposerError as exc:
            raise TypedDraftEvidenceError(
                "read-only Draft canonical request cannot be materialized"
            ) from exc
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
        "contract": TYPED_DRAFT_EVIDENCE_CONTRACT,
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
        **(
            {"direct_read_binding": direct_read_binding}
            if direct_read_binding is not None
            else {}
        ),
    }
    if len(canonical_json_bytes(evidence)) > MAX_TYPED_DRAFT_EVIDENCE_BYTES:
        _fail("Composer evidence exceeds its fixed archive byte ceiling")
    return evidence
