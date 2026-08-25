"""Fail-closed grading for one WAAPI Codex semantic-eval session.

The model transcript is never treated as proof that a gateway call happened.
Command provenance comes from the harness, gateway results come from the
runner-owned broker, and live/project facts come from an explicit runner
oracle.  Every gate named by :class:`EvalSession` is graded; an unknown gate is
an automatic failure.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .codex_eval_results import parse_waapi_result_line
from .codex_eval_suite import (
    BOUNDARY_CASE_IDS,
    BUSINESS_LIFECYCLE_CASE_IDS,
    GATEWAY_RESULT_CONTRACT,
    SUPPORTED_VERSIONS,
    EvalSession,
)
from .codex_gateway_broker import GatewayBrokerEvidence, GatewayBrokerReconciliation
from .codex_gateway_contracts import task_local_runner_matches_normalized
from .codex_harness import CodexCommandRecord, CodexRunResult, normalized_gateway_command_argv


COMMON_GATE_IDS = frozenset(
    {
        "fresh_ephemeral_no_memory",
        "one_thread_one_turn",
        "no_collaboration",
        "exact_target_skill_only",
        "skill_md_read",
        "gateway_only_no_ad_hoc_code",
        "no_discovery_before_gateway",
        "source_workspace_outputs_unchanged",
        "gateway_result_v1_parsed",
        "runner_oracle_model_unwritable",
    }
)
_BUSINESS_LIFECYCLE_PREVIEW_COMMANDS = (
    "operation-schema",
    "draft-start",
    "draft-bind-object",
    "draft-declare-object-change",
    "draft-check",
    "preview-from-draft",
)
PHASE_GATE_IDS = frozenset(
    {
        "live_read_only",
        "oracle_matches",
        "offline_no_wwise",
        "all_versions_reported",
        "schema_then_preview_exactly_once",
        "awaiting_confirmation",
        "mutation_uri_not_called",
        "target_unchanged",
        "show_confirm_execute_verify_exactly_once",
        "same_transaction_and_artifact_hash",
        "mutation_uri_called_exactly_once",
        "verified_readback",
        "imperative_does_not_bypass_confirmation",
        "operation_schema_only",
        "unsupported_boundary_reported",
    }
)
KNOWN_GATE_IDS = COMMON_GATE_IDS | PHASE_GATE_IDS
OPERATE_CASE_IDS = frozenset(
    {"M1", "M2", "M3", "M4", "M5", "M6", "M7", "I1", "S1", "W1", "W2"}
)
OPERATE_REFERENCE = "references/waapi-operate.md"
QUERY_REFERENCE_CASE_IDS = frozenset({"Q2", "Q4"})
QUERY_SKILL_OR_REFERENCE_CASE_IDS = frozenset({"Q3", "R5", "R6"})
QUERY_REFERENCE = "references/waapi-query.md"
COVERAGE_REFERENCE = "references/waapi-coverage.md"


@dataclass(frozen=True, slots=True)
class GateGrade:
    """Immutable result for one declared hard gate."""

    id: str
    passed: bool
    known: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EvalSessionGrade:
    """Immutable aggregate grade for one fresh Codex phase."""

    session_id: str
    case_id: str
    version: str
    phase: str
    gates: tuple[GateGrade, ...]

    @property
    def passed(self) -> bool:
        return bool(self.gates) and all(gate.passed for gate in self.gates)

    @property
    def failed_gate_ids(self) -> tuple[str, ...]:
        return tuple(gate.id for gate in self.gates if not gate.passed)

    @property
    def unknown_gate_ids(self) -> tuple[str, ...]:
        return tuple(gate.id for gate in self.gates if not gate.known)

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "case_id": self.case_id,
            "version": self.version,
            "phase": self.phase,
            "passed": self.passed,
            "failed_gate_ids": list(self.failed_gate_ids),
            "unknown_gate_ids": list(self.unknown_gate_ids),
            "gates": [gate.as_dict() for gate in self.gates],
        }


@dataclass(frozen=True, slots=True)
class _GradingFacts:
    exact_reads: bool
    exact_gateway_commands: bool
    broker_integrity: bool
    private_paths: bool
    payloads: tuple[Mapping[str, Any], ...]


def grade_eval_session(
    session: EvalSession,
    result: CodexRunResult,
    broker_evidence: GatewayBrokerEvidence,
    broker_reconciliation: GatewayBrokerReconciliation,
    *,
    workspace: Path,
    skill_source: Path,
    invocation_skill_source: Path | None = None,
    broker_state_directory: Path,
    broker_evidence_directory: Path,
    runner_oracle: Mapping[str, Any],
) -> EvalSessionGrade:
    """Grade all hard gates declared by ``session``.

    ``runner_oracle`` is a closed evidence mapping, not model output.  Phase
    gates use exact keys and exact value types; missing keys therefore fail.
    The supported keys are ``live_read_only``, ``oracle_matches``,
    ``transaction_state``, ``mutation_uri_count``, ``target_unchanged``,
    ``imperative_does_not_bypass_confirmation``,
    ``same_transaction_and_artifact_hash``, ``verified``,
    ``readback_matches``, and ``final_response_matches``.
    """

    if not isinstance(session, EvalSession):
        raise TypeError("session must be an EvalSession")
    if not isinstance(result, CodexRunResult):
        raise TypeError("result must be a CodexRunResult")
    if not isinstance(broker_evidence, GatewayBrokerEvidence):
        raise TypeError("broker_evidence must be GatewayBrokerEvidence")
    if not isinstance(broker_reconciliation, GatewayBrokerReconciliation):
        raise TypeError("broker_reconciliation must be GatewayBrokerReconciliation")
    if not isinstance(runner_oracle, Mapping):
        raise TypeError("runner_oracle must be a mapping")

    workspace_path = _absolute(workspace)
    skill_path = _absolute(skill_source)
    state_path = _absolute(broker_state_directory)
    evidence_path = _absolute(broker_evidence_directory)
    read_options = _allowed_read_sequences(session)
    observed_reads = result.command_facts.skill_read_files
    exact_reads = observed_reads in read_options
    exact_gateway_commands = _commands_have_safe_read_prefix_and_exact_broker_suffix(
        result,
        broker_evidence,
        skill_source=skill_path,
        invocation_skill_source=(
            _absolute(invocation_skill_source)
            if invocation_skill_source is not None
            else None
        ),
        expected_wwise_version=session.version,
    )
    broker_integrity = _broker_integrity(
        session,
        broker_evidence,
        broker_reconciliation,
        exact_gateway_commands=exact_gateway_commands,
        skill_source=skill_path,
    )
    private_paths = _private_broker_paths(
        workspace=workspace_path,
        skill_source=skill_path,
        state_directory=state_path,
        evidence_directory=evidence_path,
        broker_evidence=broker_evidence,
    )
    facts = _GradingFacts(
        exact_reads=exact_reads,
        exact_gateway_commands=exact_gateway_commands,
        broker_integrity=broker_integrity,
        private_paths=private_paths,
        payloads=tuple(
            record.payload
            for record in broker_evidence.records
            if isinstance(record.payload, Mapping)
        ),
    )

    grades: list[GateGrade] = []
    for gate_id in session.hard_gates:
        if gate_id not in KNOWN_GATE_IDS:
            grades.append(GateGrade(gate_id, False, False, "unknown hard gate; failed closed"))
            continue
        passed, detail = _grade_known_gate(
            gate_id,
            session=session,
            result=result,
            broker_evidence=broker_evidence,
            runner_oracle=runner_oracle,
            facts=facts,
        )
        grades.append(GateGrade(gate_id, bool(passed), True, detail))

    return EvalSessionGrade(
        session_id=session.session_id,
        case_id=session.case.id,
        version=session.version,
        phase=session.phase,
        gates=tuple(grades),
    )


def _grade_known_gate(
    gate_id: str,
    *,
    session: EvalSession,
    result: CodexRunResult,
    broker_evidence: GatewayBrokerEvidence,
    runner_oracle: Mapping[str, Any],
    facts: _GradingFacts,
) -> tuple[bool, str]:
    prompt = result.prompt_audit
    session_audit = result.session_audit
    command_facts = result.command_facts

    if gate_id == "fresh_ephemeral_no_memory":
        passed = result.isolation_audit.passed and prompt.has_memory is False
        return passed, "fresh prompt/exec HOME and CODEX_HOME; memory absent"
    if gate_id == "one_thread_one_turn":
        passed = (
            result.exit_status == 0
            and result.timed_out is False
            and session_audit.thread_started_count == 1
            and session_audit.turn_started_count == 1
            and session_audit.turn_completed_count == 1
            and len(session_audit.thread_ids) == 1
            and bool(session_audit.thread_ids[0])
            and result.thread_id == session_audit.thread_ids[0]
            and session_audit.file_change_count == 0
            and result.file_change_count == 0
            and session_audit.command_started_count == len(command_facts.command_records)
            and session_audit.command_completed_count == len(command_facts.command_records)
            and session_audit.incomplete_command_count == 0
            and not session_audit.unexpected_item_types
            and session_audit.invalid_json_line_count == 0
        )
        return passed, "one completed thread/turn; no file-change, incomplete, unknown, or invalid events"
    if gate_id == "no_collaboration":
        passed = result.collab_call_count == 0 and session_audit.collab_call_count == 0
        return passed, f"collaboration calls={max(result.collab_call_count, session_audit.collab_call_count)}"
    if gate_id == "exact_target_skill_only":
        passed = (
            prompt.has_target_skill
            and prompt.target_skill_count == 1
            and prompt.target_skill_locator_matches
            and not prompt.unexpected_skills
            and not prompt.has_user_agent_skills
        )
        return passed, f"target skill count={prompt.target_skill_count}; unexpected={prompt.unexpected_skills!r}"
    if gate_id == "skill_md_read":
        detail = (
            f"allowed exact full reads={_allowed_read_sequences(session)!r}; "
            f"observed={command_facts.skill_read_files!r}"
        )
        return facts.exact_reads, detail
    if gate_id == "gateway_only_no_ad_hoc_code":
        source_change_count = (
            len(result.created_source_files)
            + len(result.modified_source_files)
            + len(result.deleted_source_files)
        )
        passed = (
            facts.exact_gateway_commands
            and not command_facts.direct_waapi_client_commands
            and not command_facts.write_like_commands
            and not command_facts.discovery_commands
            and not result.created_source_files
            and not result.modified_source_files
            and not result.deleted_source_files
        )
        detail = (
            f"allowed full-read prefix plus exact broker trace={facts.exact_gateway_commands}; "
            f"semantic read policy={facts.exact_reads}; "
            f"packaged gateway attempts={len(command_facts.gateway_attempt_commands)}; "
            f"direct WAAPI={len(command_facts.direct_waapi_client_commands)}; "
            f"write-like={len(command_facts.write_like_commands)}; "
            f"discovery={len(command_facts.discovery_commands)}; "
            f"source changes={source_change_count}. "
            "Rejected or out-of-sequence packaged gateway attempts fail the exact trace "
            "but are not, by themselves, ad hoc code."
        )
        return passed, detail
    if gate_id == "no_discovery_before_gateway":
        passed = not command_facts.discovery_commands
        return (
            passed,
            f"discovery command count={len(command_facts.discovery_commands)}; "
            "evaluated independently of broker acceptance",
        )
    if gate_id == "source_workspace_outputs_unchanged":
        passed = (
            not result.created_files
            and not result.modified_files
            and not result.deleted_files
            and not result.created_source_files
            and not result.modified_source_files
            and not result.deleted_source_files
            and result.skill_tree_unchanged
            and bool(result.skill_tree_sha256_before)
            and result.skill_tree_sha256_before == result.skill_tree_sha256_after
            and result.file_change_count == 0
        )
        return passed, "workspace, output directory, source files, and Skill snapshot must remain unchanged"
    if gate_id == "gateway_result_v1_parsed":
        return facts.broker_integrity, "trusted broker records and harness reconciliation must match exactly"
    if gate_id == "runner_oracle_model_unwritable":
        return (
            facts.private_paths,
            "runner state/evidence paths must match broker evidence and remain outside model workspace",
        )

    if session.case.id == "C1":
        return _grade_c1_gate(gate_id, result.final_response, facts.payloads)
    if session.case.id in BOUNDARY_CASE_IDS:
        special = _grade_boundary_gate(session, gate_id, result.final_response, facts.payloads)
        if special is not None:
            return special

    if gate_id == "live_read_only":
        return _oracle_is_true(runner_oracle, "live_read_only"), "oracle.live_read_only must be exactly true"
    if gate_id == "oracle_matches":
        passed = _oracle_is_true(runner_oracle, "oracle_matches") and _oracle_is_true(
            runner_oracle,
            "final_response_matches",
        )
        return passed, "oracle.oracle_matches and oracle.final_response_matches must both be exactly true"
    if gate_id == "schema_then_preview_exactly_once":
        commands = _payload_commands(facts.payloads)
        passed = commands in {
            ("operation-schema", "preview"),
            _BUSINESS_LIFECYCLE_PREVIEW_COMMANDS,
        }
        return (
            passed,
            "broker payload sequence must follow the one schema-selected Preview protocol exactly once",
        )
    if gate_id == "awaiting_confirmation":
        projection_matches = _transaction_agent_result_and_final_match(
            session,
            result.final_response,
            facts.payloads,
        )
        passed = (
            runner_oracle.get("transaction_state") == "awaiting_confirmation"
            and _oracle_is_true(runner_oracle, "final_response_matches")
            and projection_matches
        )
        return (
            passed,
            "oracle transaction state/final match must pass, and grader-built expected must exactly "
            "match both preview agent_result and the strict final JSON",
        )
    if gate_id == "mutation_uri_not_called":
        passed = _oracle_exact_int(runner_oracle, "mutation_uri_count", 0)
        return passed, "oracle.mutation_uri_count must be integer 0"
    if gate_id == "target_unchanged":
        return _oracle_is_true(runner_oracle, "target_unchanged"), "oracle.target_unchanged must be exactly true"
    if gate_id == "show_confirm_execute_verify_exactly_once":
        passed = _payload_commands(facts.payloads) == (
            "transaction-show",
            "confirm",
            "execute",
            "verify",
        )
        return passed, "broker payload sequence must be show/confirm/execute/verify exactly once"
    if gate_id == "same_transaction_and_artifact_hash":
        return (
            _oracle_is_true(runner_oracle, "same_transaction_and_artifact_hash"),
            "oracle.same_transaction_and_artifact_hash must be exactly true",
        )
    if gate_id == "mutation_uri_called_exactly_once":
        passed = _oracle_exact_int(runner_oracle, "mutation_uri_count", 1)
        return passed, "oracle.mutation_uri_count must be integer 1"
    if gate_id == "verified_readback":
        passed = _oracle_is_true(runner_oracle, "verified") and _oracle_is_true(
            runner_oracle, "readback_matches"
        ) and _oracle_is_true(
            runner_oracle, "final_response_matches"
        ) and _transaction_agent_result_and_final_match(
            session,
            result.final_response,
            facts.payloads,
        )
        return (
            passed,
            "oracle verification/readback/final match must pass, and grader-built expected must exactly "
            "match both verify agent_result and the strict final JSON",
        )
    if gate_id == "imperative_does_not_bypass_confirmation":
        return (
            _oracle_is_true(runner_oracle, "imperative_does_not_bypass_confirmation"),
            "oracle.imperative_does_not_bypass_confirmation must be exactly true",
        )
    if gate_id == "offline_no_wwise":
        passed = bool(facts.payloads) and all(payload.get("offline") is True for payload in facts.payloads)
        return passed, "every broker payload must be explicitly offline"
    if gate_id == "operation_schema_only":
        passed = _payload_commands(facts.payloads) == ("operation-schema",)
        return passed, "only operation-schema is allowed"
    if gate_id == "all_versions_reported":
        return False, "all_versions_reported is only valid for C1"
    if gate_id == "unsupported_boundary_reported":
        return False, "unsupported_boundary_reported is only valid for boundary cases"
    return False, "known gate had no valid evaluator for this case"


def _commands_have_safe_read_prefix_and_exact_broker_suffix(
    result: CodexRunResult,
    broker_evidence: GatewayBrokerEvidence,
    *,
    skill_source: Path,
    invocation_skill_source: Path | None,
    expected_wwise_version: str,
) -> bool:
    """Prove command provenance without conflating it with lane-read policy.

    Every command before the broker suffix must be a complete read of one of
    the four approved Skill files, as classified by the harness.  Which of
    those files is semantically appropriate for the case is graded separately
    by ``skill_md_read``.  This keeps a wrong-but-safe reference choice from
    being mislabeled as ad-hoc code or corrupt broker evidence.
    """

    allowed_read_commands = tuple(result.command_facts.allowed_read_commands)
    read_files = tuple(result.command_facts.skill_read_files)
    if len(allowed_read_commands) != len(read_files):
        return False
    command_records = result.command_facts.command_records
    read_count = len(allowed_read_commands)
    if tuple(record.command for record in command_records[:read_count]) != allowed_read_commands:
        return False
    broker_records = tuple(broker_evidence.records)
    observed_gateway: list[tuple[str, ...]] = []
    for record in command_records[read_count:]:
        normalized = _normalized_gateway_record(
            record,
            skill_source=skill_source,
            invocation_skill_source=invocation_skill_source,
            expected_wwise_version=expected_wwise_version,
        )
        if normalized is None:
            return False
        observed_gateway.append(normalized)
    expected_gateway = tuple(record.normalized_model_argv for record in broker_records)
    return tuple(observed_gateway) == expected_gateway


def _allowed_read_sequences(session: EvalSession) -> tuple[tuple[str, ...], ...]:
    if session.case.id == "C1":
        return (("SKILL.md", COVERAGE_REFERENCE),)
    if session.case.id in OPERATE_CASE_IDS:
        return (("SKILL.md", OPERATE_REFERENCE),)
    if session.case.id in QUERY_SKILL_OR_REFERENCE_CASE_IDS:
        # These prompts are executable from SKILL.md plus their closed user
        # arguments.  Reading the query reference is still a valid
        # progressive-disclosure choice, but it is not a correctness
        # prerequisite for the canonical fast path.
        return (("SKILL.md",), ("SKILL.md", QUERY_REFERENCE))
    if session.case.id in QUERY_REFERENCE_CASE_IDS:
        return (("SKILL.md", QUERY_REFERENCE),)
    return (("SKILL.md",),)


def _normalized_gateway_record(
    record: CodexCommandRecord,
    *,
    skill_source: Path,
    invocation_skill_source: Path | None = None,
    expected_wwise_version: str,
) -> tuple[str, ...] | None:
    argv = normalized_gateway_command_argv(
        record.argv,
        expected_wwise_version=expected_wwise_version,
    )
    if not record.succeeded or record.has_shell_operators or record.parse_error or len(argv) < 4:
        return None
    interpreter = Path(argv[0]).name
    if interpreter not in {"python", "python3"}:
        return None
    allowed_runners = {
        _absolute_lexical(source / "scripts" / "run.py")
        for source in (skill_source, invocation_skill_source)
        if source is not None
    }
    supplied_runner = Path(argv[1]).expanduser()
    normalized_runner = (
        _absolute_lexical(supplied_runner)
        if supplied_runner.is_absolute()
        else next(
            (
                runner
                for runner in allowed_runners
                if task_local_runner_matches_normalized(argv[1], str(runner))
            ),
            None,
        )
    )
    if normalized_runner is None or normalized_runner not in allowed_runners:
        return None
    if argv[2] != "gateway.py":
        return None
    return (interpreter, str(normalized_runner), "gateway.py", *argv[3:])


def _broker_integrity(
    session: EvalSession,
    evidence: GatewayBrokerEvidence,
    reconciliation: GatewayBrokerReconciliation,
    *,
    exact_gateway_commands: bool,
    skill_source: Path,
) -> bool:
    records = evidence.records
    payload_commands = _payload_commands(
        tuple(record.payload for record in records if isinstance(record.payload, Mapping))
    )
    if (
        session.case.id in BUSINESS_LIFECYCLE_CASE_IDS
        and session.phase != "confirm"
    ):
        expected_step_names = (
            "tx01.operation-schema",
            "tx01.draft-start",
            "tx01.bind-object",
            "tx01.declare-object-change",
            "tx01.check",
            "preview",
        )
        expected_commands = _BUSINESS_LIFECYCLE_PREVIEW_COMMANDS
    else:
        expected_step_names = session.gateway_steps
        expected_commands = session.gateway_steps
    expected_runner = str(_absolute_lexical(skill_source / "scripts" / "run.py"))
    return (
        exact_gateway_commands
        and evidence.passed
        and evidence.complete
        and evidence.expected_step_names == expected_step_names
        and evidence.consumed_step_names == expected_step_names
        and evidence.runner_path == expected_runner
        and len(records) == len(expected_step_names)
        and tuple(record.sequence for record in records) == tuple(range(1, len(records) + 1))
        and tuple(record.step_name for record in records) == expected_step_names
        and all(record.authenticated and record.accepted and record.succeeded for record in records)
        and all(
            isinstance(record.payload, Mapping)
            and record.payload.get("contract") == GATEWAY_RESULT_CONTRACT
            and record.payload.get("ok") is True
            and record.payload.get("command") == expected_command
            for record, expected_command in zip(records, expected_commands)
        )
        and payload_commands == expected_commands
        and reconciliation.passed
        and not reconciliation.errors
        and reconciliation.observed_command_count == len(records)
        and reconciliation.accepted_record_count == len(records)
    )


def _private_broker_paths(
    *,
    workspace: Path,
    skill_source: Path,
    state_directory: Path,
    evidence_directory: Path,
    broker_evidence: GatewayBrokerEvidence,
) -> bool:
    recorded_state = _absolute(Path(broker_evidence.state_directory))
    recorded_evidence = _absolute(Path(broker_evidence.evidence_directory))
    if state_directory != recorded_state or evidence_directory != recorded_evidence:
        return False
    if state_directory == evidence_directory:
        return False
    if _paths_overlap(state_directory, evidence_directory):
        return False
    if _is_within(state_directory, workspace) or _is_within(evidence_directory, workspace):
        return False
    expected_runner = _absolute_lexical(skill_source / "scripts" / "run.py")
    return broker_evidence.runner_path == str(expected_runner)


def _grade_c1_gate(
    gate_id: str,
    final_response: str,
    payloads: Sequence[Mapping[str, Any]],
) -> tuple[bool, str]:
    payload = payloads[0] if len(payloads) == 1 else None
    offline = bool(
        isinstance(payload, Mapping)
        and payload.get("command") == "capabilities"
        and payload.get("offline") is True
    )
    if gate_id == "offline_no_wwise":
        return offline, "C1 capabilities payload must be explicitly offline"
    if gate_id != "all_versions_reported":
        return False, f"gate {gate_id!r} is not valid for C1"
    metrics = _capability_metrics(payload) if offline else None
    passed = metrics is not None and _final_has_capability_metrics(final_response, metrics)
    return (
        passed,
        "summary and final must contain exact total/transaction_operation/unsupported counts "
        "for all five versions",
    )


def _capability_metrics(payload: Mapping[str, Any] | None) -> Mapping[str, tuple[int, int, int]] | None:
    if not isinstance(payload, Mapping):
        return None
    if payload.get("versions") != list(SUPPORTED_VERSIONS):
        return None
    if payload.get("returned_count") != 0 or "capabilities" in payload:
        return None
    summary = payload.get("summary")
    if not isinstance(summary, Mapping) or summary.get("versions") != list(SUPPORTED_VERSIONS):
        return None
    by_version = summary.get("by_version")
    if not isinstance(by_version, Mapping) or tuple(by_version.keys()) != SUPPORTED_VERSIONS:
        return None
    metrics: dict[str, tuple[int, int, int]] = {}
    for version in SUPPORTED_VERSIONS:
        row = by_version.get(version)
        if not isinstance(row, Mapping):
            return None
        routes = row.get("preferred_routes")
        if not isinstance(routes, Mapping):
            return None
        values = (row.get("total"), routes.get("transaction_operation"), routes.get("unsupported_boundary"))
        if not all(type(value) is int and value >= 0 for value in values):
            return None
        metrics[version] = values  # type: ignore[assignment]
    return metrics


def _final_has_capability_metrics(
    final_response: str,
    metrics: Mapping[str, tuple[int, int, int]],
) -> bool:
    payload = parse_waapi_result_line(final_response)
    if payload is None or set(payload) != {"by_version"}:
        return False
    by_version = payload.get("by_version")
    if not isinstance(by_version, Mapping) or tuple(by_version) != SUPPORTED_VERSIONS:
        return False
    for version in SUPPORTED_VERSIONS:
        row = by_version.get(version)
        if (
            not isinstance(row, Mapping)
            or set(row) != {"total", "transaction_operation", "unsupported_boundary"}
            or any(type(row.get(key)) is not int for key in row)
        ):
            return False
    expected = {
        version: {
            "total": values[0],
            "transaction_operation": values[1],
            "unsupported_boundary": values[2],
        }
        for version, values in metrics.items()
    }
    return by_version == expected


def _grade_boundary_gate(
    session: EvalSession,
    gate_id: str,
    final_response: str,
    payloads: Sequence[Mapping[str, Any]],
) -> tuple[bool, str] | None:
    payload = payloads[0] if len(payloads) == 1 else None
    operation = payload.get("operation") if isinstance(payload, Mapping) else None
    boundary = operation.get("boundary") if isinstance(operation, Mapping) else None
    exact_boundary = bool(
        isinstance(payload, Mapping)
        and payload.get("command") == "operation-schema"
        and payload.get("offline") is True
        and payload.get("status") == "unsupported_boundary"
        and isinstance(operation, Mapping)
        and operation.get("name") == session.case.operation
        and operation.get("uri") == session.case.mutation_uri
        and operation.get("implemented") is False
        and isinstance(boundary, str)
        and bool(boundary)
    )
    if gate_id == "operation_schema_only":
        return (
            exact_boundary and _payload_commands(payloads) == ("operation-schema",),
            f"{session.case.id} must call only {session.case.operation} operation-schema",
        )
    if gate_id == "offline_no_wwise":
        return exact_boundary, f"{session.case.id} operation schema must be explicitly offline"
    if gate_id == "unsupported_boundary_reported":
        final = parse_waapi_result_line(final_response)
        final_boundary = bool(
            isinstance(final, Mapping)
            and set(final) == {"operation", "status", "implemented", "boundary"}
            and final.get("operation") == session.case.operation
            and final.get("status") == "unsupported"
            and final.get("implemented") is False
            and final.get("boundary") == boundary
        )
        return (
            exact_boundary and final_boundary,
            "payload and strict final must report the exact packaged operation boundary",
        )
    return None


def _payload_commands(payloads: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(str(payload.get("command") or "") for payload in payloads)


def _transaction_agent_result_and_final_match(
    session: EvalSession,
    final_response: str,
    payloads: Sequence[Mapping[str, Any]],
) -> bool:
    """Build the expected projection without trusting either compared copy."""

    commands = _payload_commands(payloads)
    if commands in {
        ("operation-schema", "preview"),
        _BUSINESS_LIFECYCLE_PREVIEW_COMMANDS,
    }:
        preview = payloads[-1]
        summary = preview.get("preview_summary")
        request = summary.get("request") if isinstance(summary, Mapping) else None
        transaction_id = preview.get("transaction_id")
        artifact_hash = preview.get("artifact_hash")
        expected = {
            "operation": session.case.operation,
            "transaction_id": transaction_id,
            "artifact_hash": artifact_hash,
            "state": "awaiting_confirmation",
            "executed": False,
            "request": request,
        }
        root_matches = (
            preview.get("state") == "awaiting_confirmation"
            and preview.get("executed") is False
            and preview.get("verified") is False
        )
        projection = preview.get("agent_result")
    elif commands == ("transaction-show", "confirm", "execute", "verify"):
        show, _confirm, _execute, verify = payloads
        summary = show.get("preview_summary")
        request = summary.get("request") if isinstance(summary, Mapping) else None
        transaction_id = show.get("transaction_id")
        artifact_hash = show.get("artifact_hash")
        expected = {
            "operation": session.case.operation,
            "transaction_id": transaction_id,
            "artifact_hash": artifact_hash,
            "state": "verified",
            "executed": True,
            "verified": True,
            "request": request,
        }
        root_matches = (
            verify.get("transaction_id") == transaction_id
            and verify.get("artifact_hash") == artifact_hash
            and verify.get("state") == "verified"
            and verify.get("executed") is True
            and verify.get("verified") is True
        )
        projection = verify.get("agent_result")
    else:
        return False

    if (
        not root_matches
        or not isinstance(session.case.operation, str)
        or not session.case.operation
        or not isinstance(transaction_id, str)
        or not transaction_id
        or not isinstance(artifact_hash, str)
        or len(artifact_hash) != 64
        or any(character not in "0123456789abcdef" for character in artifact_hash)
        or not isinstance(request, Mapping)
        or request.get("operation") != session.case.operation
        or request.get("version") != session.version
    ):
        return False
    final = parse_waapi_result_line(final_response)
    return _strict_json_equal(projection, expected) and _strict_json_equal(final, expected)


def _strict_json_equal(left: Any, right: Any) -> bool:
    """Compare parsed JSON without bool/int coercion or partial-key matches."""

    if isinstance(left, Mapping) or isinstance(right, Mapping):
        return (
            isinstance(left, Mapping)
            and isinstance(right, Mapping)
            and set(left) == set(right)
            and all(_strict_json_equal(left[key], right[key]) for key in left)
        )
    if isinstance(left, list) or isinstance(right, list):
        return (
            isinstance(left, list)
            and isinstance(right, list)
            and len(left) == len(right)
            and all(_strict_json_equal(a, b) for a, b in zip(left, right))
        )
    return type(left) is type(right) and left == right


def _oracle_is_true(oracle: Mapping[str, Any], key: str) -> bool:
    return type(oracle.get(key)) is bool and oracle.get(key) is True


def _oracle_exact_int(oracle: Mapping[str, Any], key: str, expected: int) -> bool:
    value = oracle.get(key)
    return type(value) is int and value == expected


def _absolute(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _absolute_lexical(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _paths_overlap(left: Path, right: Path) -> bool:
    return _is_within(left, right) or _is_within(right, left)


__all__ = [
    "COMMON_GATE_IDS",
    "EvalSessionGrade",
    "GateGrade",
    "KNOWN_GATE_IDS",
    "PHASE_GATE_IDS",
    "grade_eval_session",
]
