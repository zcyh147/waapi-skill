"""Scenario-scoped fresh Codex task execution for the V3 heavy suite."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from tests.semantic.support.codex_business_oracle_plan_v3 import (
    BUSINESS_ORACLE_PLAN_FILE,
    BusinessOraclePlanEvidence,
    BusinessOraclePlanError,
    business_family_for_api,
    read_business_oracle_plan_envelope,
)
from tests.semantic.support.codex_eval_bundle_v3 import OnlineScenario
from tests.semantic.support.codex_eval_protocol_v3 import V3GatewayProtocol
from tests.semantic.support.codex_gateway_broker import (
    CodexGatewayBroker,
    GatewayBrokerEvidence,
    GatewayBrokerReconciliation,
    TrustedSubscriptionAckObserver,
    TrustedSubscriptionAckSpec,
    TrustedStepObserver,
    TrustedStepPreObserver,
    gateway_step_sequence_matches,
)
from tests.semantic.support.codex_gateway_contracts import (
    task_local_runner_matches_normalized,
)
from tests.semantic.support.codex_filesystem_security import write_utf8_text_bytes
from tests.semantic.support.codex_harness import (
    CodexCliTask,
    CodexCommandRecord,
    CodexGatewayErrorExpectation,
    CodexHarnessConfig,
    CodexHarnessError,
    CodexInfrastructureError,
    CodexInfrastructureFailure,
    CodexRunResult,
    WindowsPowerShellCoreHost,
    gateway_continuation_binding_errors,
    normalized_gateway_command_argv,
    prepare_workspace_skill_install,
    recoverable_preprocess_attempt_indexes,
    semantic_task_developer_instructions,
)
from tests.semantic.support.codex_prompt_provenance_v3 import (
    PROMPT_MATERIALIZATION_RECEIPT_CONTRACT,
    PROMPT_MATERIALIZATION_RECEIPT_FILE,
    PROMPT_PROVENANCE_FILE,
    prompt_materialization_receipt,
    read_prompt_provenance,
)
from tests.semantic.support.codex_prompt_asset_reads_v3 import (
    PromptAssetReadError,
    remove_validated_command_occurrences,
    validated_prompt_asset_cat_commands,
)
from tests.semantic.support.codex_typed_draft_evidence_v3 import (
    TypedDraftEvidenceError,
    classify_composer_failure_stage,
    validate_typed_draft_evidence,
)


TASK_RESULT_CONTRACT = "waapi-skill.codex-semantic-task-result/v5"
TASK_INFRASTRUCTURE_FAILURE_CONTRACT = (
    "waapi-skill.codex-semantic-task-infrastructure-failure/v3"
)
TASK_COMMAND_LIFECYCLE_FAILURE_CONTRACT = (
    "waapi-skill.codex-semantic-command-lifecycle-failure/v1"
)
TASK_GATE_FAILURE_CONTRACT = "waapi-skill.codex-semantic-task-gate-failure/v1"
PROMPT_MATERIALIZATION_CONTRACT = PROMPT_MATERIALIZATION_RECEIPT_CONTRACT
PROMPT_MATERIALIZATION_FILE = PROMPT_MATERIALIZATION_RECEIPT_FILE
_CODEX_INFRASTRUCTURE_CATEGORIES = frozenset(
    {
        "authentication",
        "quota_or_rate_limit",
        "service_unavailable",
        "timeout_before_agent_action",
        "turn_failed_before_agent_action",
    }
)
_PACKAGED_LANE_REFERENCES = frozenset(
    {
        "references/waapi-coverage.md",
        "references/waapi-operate.md",
        "references/waapi-query.md",
        "references/waapi-setup.md",
    }
)


class V3TaskRunnerError(RuntimeError):
    """The fresh task failed a harness/broker invariant."""

    def __init__(self, message: str, *, thread_id: str | None = None) -> None:
        super().__init__(message)
        self.thread_id = thread_id


class V3CommandLifecycleError(CodexHarnessError):
    """Codex ended a turn while one or more command items were incomplete."""


@dataclass(frozen=True, slots=True)
class V3TurnGrade:
    index: int
    prompt_sha256: str
    broker_prefix_count: int
    reconciliation: GatewayBrokerReconciliation
    common_gates: Mapping[str, bool]
    errors: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return (
            self.reconciliation.passed
            and bool(self.common_gates)
            and all(self.common_gates.values())
            and not self.errors
        )


@dataclass(frozen=True, slots=True)
class V3TaskRun:
    scenario_id: str
    version: str
    task_root: Path
    thread_id: str
    turns: tuple[CodexRunResult, ...]
    turn_grades: tuple[V3TurnGrade, ...]
    broker_evidence: GatewayBrokerEvidence
    broker_protocol_passed: bool = False

    @property
    def passed(self) -> bool:
        return (
            (self.broker_evidence.passed or self.broker_protocol_passed)
            and all(item.passed for item in self.turn_grades)
        )

    @property
    def terminal_indeterminate(self) -> bool:
        return (
            bool(getattr(self.broker_evidence, "terminal_indeterminate", False))
            and bool(self.turn_grades)
            and all(item.passed for item in self.turn_grades)
        )

    @property
    def final_response(self) -> str:
        return self.turns[-1].final_response if self.turns else ""


TurnObserver = Callable[[int, CodexRunResult, GatewayBrokerEvidence], None]


def run_v3_codex_task(
    *,
    scenario_id: str,
    version: str,
    scenario: OnlineScenario,
    prompts: Sequence[str],
    protocol: V3GatewayProtocol,
    task_root: Path,
    skill_source: Path,
    codex_binary: Path,
    auth_json: Path,
    model: str,
    reasoning_effort: str,
    service_tier: str,
    timeout_seconds: float,
    runner_environment: Mapping[str, str],
    required_reference: str | None,
    business_oracle_plan: BusinessOraclePlanEvidence,
    windows_powershell_core_host: WindowsPowerShellCoreHost | None = None,
    turn_reference_schedule: Sequence[Sequence[str]] | None = None,
    trusted_subscription_ack: TrustedSubscriptionAckSpec | None = None,
    trusted_subscription_ack_observer: TrustedSubscriptionAckObserver | None = None,
    trusted_step_pre_observer: TrustedStepPreObserver | None = None,
    trusted_step_observer: TrustedStepObserver | None = None,
    turn_observer: TurnObserver | None = None,
    project_modification_policy: str = "ask_before_changes",
    expected_primary_dispatch_count: int | None = None,
    developer_instructions: str = "",
) -> V3TaskRun:
    """Run every natural turn in one exact, memory-isolated Codex thread."""

    prompt_values = tuple(str(prompt) for prompt in prompts)
    if len(prompt_values) != len(protocol.turn_prefix_counts):
        raise V3TaskRunnerError(
            "prompt count must equal protocol turn-boundary count: "
            f"prompts={len(prompt_values)} prefixes={len(protocol.turn_prefix_counts)}"
        )
    expected_skill_reads = _normalize_turn_reference_schedule(
        prompt_count=len(prompt_values),
        required_reference=required_reference,
        turn_reference_schedule=turn_reference_schedule,
    )
    root = Path(task_root).expanduser().resolve(strict=False)
    if (
        root.name != "codex-task"
        or root.parent.name != "evidence"
        or root.parent.parent / "evidence" / PROMPT_PROVENANCE_FILE
        != root.parent / PROMPT_PROVENANCE_FILE
    ):
        raise V3TaskRunnerError(
            "task root must be the fixed scenario_root/evidence/codex-task path"
        )
    if root.exists():
        raise V3TaskRunnerError(f"fresh task root already exists: {root}")
    if scenario.id != scenario_id or version not in scenario.versions:
        raise V3TaskRunnerError("task scenario/version identity is misbound")
    root.mkdir(parents=True, exist_ok=False)
    provenance = read_prompt_provenance(
        root.parent / PROMPT_PROVENANCE_FILE,
        scenario=scenario,
        version=version,
        scenario_root=root.parent.parent,
        expected_prompts=prompt_values,
        expected_protocol=protocol,
        require_paths=True,
    )
    plan_payload = business_oracle_plan.payload
    expected_family = business_family_for_api(str(scenario.api))
    expected_runner = "cli" if expected_family == "cli" else "project"
    primary_dispatch = getattr(scenario, "primary_dispatch", None)
    scenario_primary_count = getattr(primary_dispatch, "count", None)
    expected_primary_count = (
        scenario_primary_count
        if expected_primary_dispatch_count is None
        else expected_primary_dispatch_count
    )
    if (
        business_oracle_plan.path != root.parent / BUSINESS_ORACLE_PLAN_FILE
        or plan_payload.get("scenario_id") != scenario_id
        or plan_payload.get("version") != version
        or plan_payload.get("api") != scenario.api
        or plan_payload.get("runner") != expected_runner
        or plan_payload.get("family") != expected_family
        or plan_payload.get("scenario_root") != str(root.parent.parent)
        or plan_payload.get("protocol_sha256")
        != provenance.payload["protocol"]["sha256"]
        or plan_payload.get("provenance_sha256") != provenance.sha256
        or type(expected_primary_count) is not int
        or expected_primary_count < 0
        or plan_payload.get("primary_dispatch_count") != expected_primary_count
    ):
        raise V3TaskRunnerError(
            "business-oracle plan common identity is not bound to the task"
        )
    try:
        sealed_plan = read_business_oracle_plan_envelope(
            business_oracle_plan.path,
            scenario_id=scenario_id,
            version=version,
            api=str(scenario.api),
            runner=expected_runner,
            family=expected_family,
            scenario_root=root.parent.parent,
            fixture_spec=plan_payload["fixture_spec"],
            protocol_sha256=provenance.payload["protocol"]["sha256"],
            provenance_sha256=provenance.sha256,
            primary_dispatch_count=expected_primary_count,
        )
    except (BusinessOraclePlanError, KeyError, TypeError) as exc:
        raise V3TaskRunnerError(
            f"business-oracle plan cannot be independently re-read: {exc}"
        ) from exc
    if (
        sealed_plan.path != business_oracle_plan.path
        or sealed_plan.sha256 != business_oracle_plan.sha256
        or sealed_plan.payload != business_oracle_plan.payload
    ):
        raise V3TaskRunnerError(
            "business-oracle plan evidence changed before task startup"
        )
    prompt_materialization_path = _archive_prompt_materialization(
        root,
        provenance=provenance,
        business_oracle_plan=sealed_plan,
    )
    workspace = root / "agent-workspace"
    skill_install = _prepare_agent_workspace(workspace, skill_source)
    sealed_developer_instructions = (
        semantic_task_developer_instructions(
            skill_source / "scripts" / "run.py",
            task_skill_source=skill_install,
            expected_skill_reads=expected_skill_reads,
            base_developer_instructions=developer_instructions,
        )
        if developer_instructions
        else ""
    )
    broker_root = root / "broker"
    results: list[CodexRunResult] = []
    grades: list[V3TurnGrade] = []
    cumulative_gateway_argvs: list[tuple[str, ...]] = []
    cumulative_gateway_records: list[CodexCommandRecord] = []
    previous_prefix = 0
    broker_evidence: GatewayBrokerEvidence | None = None
    infrastructure_error: CodexInfrastructureError | None = None

    subcommands = _ordered_unique(step.subcommand for step in protocol.steps)
    gateway_errors = tuple(
        CodexGatewayErrorExpectation(
            command=step.expected_result_command,
            error_code=step.expected_error_code,
        )
        for step in protocol.steps
        if step.allowed_exit_codes == (2,)
    )
    config = CodexHarnessConfig(
        workspace=workspace,
        skill_source=skill_source,
        codex_binary=codex_binary,
        windows_powershell_core_host=windows_powershell_core_host,
        auth_json=auth_json,
        model=model,
        reasoning_effort=reasoning_effort,
        service_tier=service_tier,
        timeout_seconds=timeout_seconds,
        expected_gateway_subcommands=subcommands,
        expected_wwise_version=version,
        sandbox_mode="workspace-write",
        allow_output_write=False,
        network_access=True,
        expected_gateway_errors=gateway_errors,
        developer_instructions=sealed_developer_instructions,
    )
    broker = CodexGatewayBroker(
        skill_source=skill_source,
        invocation_skill_source=skill_install,
        expected_steps=protocol.steps,
        commutative_read_only_step_groups=(
            protocol.commutative_read_only_step_groups
        ),
        commutative_composer_setup_step_groups=(
            protocol.commutative_composer_setup_step_groups
        ),
        optional_topic_schema_step_groups=(
            protocol.optional_topic_schema_step_groups
        ),
        optional_query_schema_step_names=(
            protocol.optional_query_schema_step_names
        ),
        expected_wwise_version=version,
        project_modification_policy=project_modification_policy,
        runner_environment=runner_environment,
        working_root=broker_root,
        transport="tcp",
        runner_timeout_seconds=max(120.0, timeout_seconds),
        trusted_step_pre_observer=trusted_step_pre_observer,
        trusted_step_observer=trusted_step_observer,
        trusted_subscription_ack=trusted_subscription_ack,
        trusted_subscription_ack_observer=trusted_subscription_ack_observer,
        optional_initial_query_schema=(
            protocol.optional_initial_query_schema
            and not protocol.optional_query_schema_step_names
        ),
    )
    try:
        with broker:
            with CodexCliTask(config, extra_env=broker.model_environment_overrides()) as task:
                for turn_index, (prompt, expected_prefix) in enumerate(
                    zip(prompt_values, protocol.turn_prefix_counts, strict=True),
                    start=1,
                ):
                    output_dir = root / "turns" / f"turn-{turn_index:02d}"
                    try:
                        result = (
                            task.run_initial(prompt, output_dir=output_dir)
                            if turn_index == 1
                            else task.run_followup(prompt, output_dir=output_dir)
                        )
                    except CodexInfrastructureError as exc:
                        # Snapshot the trusted broker before either context is
                        # allowed to unwind.  A failed archive is deliberately
                        # not suppressed: without complete fixed-path evidence,
                        # the caller must not treat this task as retryable.
                        failure_broker_evidence = broker.evidence()
                        _validate_infrastructure_failure(
                            prompt=prompt,
                            result=exc.result,
                            failure=exc.failure,
                            broker_evidence=failure_broker_evidence,
                            expected_step_names=tuple(
                                step.name for step in protocol.steps
                            ),
                            previous_broker_prefix=previous_prefix,
                            allow_complete_prefix_failure=(
                                bool(protocol.allowed_turn_prefix_counts)
                                and previous_prefix == len(protocol.steps)
                                and expected_prefix == previous_prefix
                            ),
                        )
                        _archive_infrastructure_failure(
                            root,
                            output_dir=output_dir,
                            scenario_id=scenario_id,
                            version=version,
                            turn_index=turn_index,
                            expected_turn_count=len(prompt_values),
                            prior_completed_turn_count=len(results),
                            previous_broker_prefix=previous_prefix,
                            expected_failed_turn_prefix=expected_prefix,
                            prior_thread_id=(results[0].thread_id if results else None),
                            prompt=prompt,
                            result=exc.result,
                            failure=exc.failure,
                            broker_evidence=failure_broker_evidence,
                            prompt_materialization_path=prompt_materialization_path,
                        )
                        infrastructure_error = exc
                        break
                    results.append(result)
                    turn_gateway = _gateway_candidate_argvs(
                        result,
                        skill_source=skill_install,
                        alternate_skill_sources=(skill_source,),
                        expected_wwise_version=version,
                    )
                    turn_gateway_records = _gateway_candidate_records(
                        result,
                        skill_source=skill_install,
                        alternate_skill_sources=(skill_source,),
                        expected_wwise_version=version,
                    )
                    cumulative_gateway_argvs.extend(turn_gateway)
                    cumulative_gateway_records.extend(turn_gateway_records)
                    broker_evidence = broker.evidence()
                    terminal_indeterminate = bool(
                        getattr(broker_evidence, "terminal_indeterminate", False)
                    )
                    actual_prefix = len(broker_evidence.consumed_step_names)
                    allowed_prefixes = protocol.allowed_prefixes_for_turn(
                        turn_index
                    )
                    effective_prefix = (
                        actual_prefix
                        if terminal_indeterminate
                        or protocol.allowed_turn_prefix_counts
                        else expected_prefix
                    )
                    prefix_errors: list[str] = []
                    if (
                        not terminal_indeterminate
                        and effective_prefix not in allowed_prefixes
                    ):
                        prefix_errors.append(
                            "broker prefix is outside the allowed turn choices: "
                            f"observed={effective_prefix} allowed={allowed_prefixes!r}"
                        )
                    if effective_prefix < previous_prefix:
                        prefix_errors.append(
                            "broker prefix moved backwards across Codex turns"
                        )
                    if effective_prefix < 1:
                        reconciliation = GatewayBrokerReconciliation(
                            passed=False,
                            observed_command_count=len(cumulative_gateway_argvs),
                            accepted_record_count=len(
                                broker_evidence.accepted_records
                            ),
                            errors=tuple(
                                prefix_errors
                                or ("broker consumed no expected gateway step",)
                            ),
                        )
                    else:
                        raw_reconciliation = broker.reconcile_prefix(
                            cumulative_gateway_argvs,
                            expected_step_count=effective_prefix,
                        )
                        reconciliation = _bind_gateway_prefix_reconciliation(
                            raw_reconciliation,
                            command_records=cumulative_gateway_records,
                            broker_evidence=broker_evidence,
                            prefix_errors=prefix_errors,
                            windows_powershell_core_host=(
                                windows_powershell_core_host
                            ),
                        )
                    terminal_execute_exit2_count = _terminal_execute_exit2_count(
                        protocol,
                        broker_evidence,
                        start=previous_prefix,
                        stop=effective_prefix,
                    )
                    errors, gates = _grade_common_turn(
                        result,
                        turn_index=turn_index,
                        required_reference=required_reference,
                        expected_skill_reads=expected_skill_reads[
                            turn_index - 1
                        ],
                        expected_gateway_count=effective_prefix - previous_prefix,
                        expected_terminal_execute_exit2_count=(
                            terminal_execute_exit2_count
                        ),
                        prompt_provenance=provenance,
                    )
                    grade = V3TurnGrade(
                        index=turn_index,
                        prompt_sha256=_sha256_text(prompt),
                        broker_prefix_count=effective_prefix,
                        reconciliation=reconciliation,
                        common_gates=gates,
                        errors=errors,
                    )
                    grades.append(grade)
                    _archive_turn(output_dir, prompt=prompt, result=result, grade=grade)
                    if result.session_audit.incomplete_command_count:
                        _archive_command_lifecycle_failure(
                            root,
                            output_dir=output_dir,
                            scenario_id=scenario_id,
                            version=version,
                            turn_index=turn_index,
                            expected_turn_count=len(prompt_values),
                            prompt=prompt,
                            result=result,
                            broker_evidence=broker_evidence,
                        )
                        raise V3CommandLifecycleError(
                            f"{scenario_id} turn {turn_index} ended with "
                            f"{result.session_audit.incomplete_command_count} "
                            "incomplete Codex command lifecycle item(s); the "
                            "scenario is blocked and must use a fresh sandbox"
                        )
                    if not grade.passed:
                        common_failures = errors or tuple(
                            key for key, value in gates.items() if not value
                        )
                        _archive_task_gate_failure(
                            root,
                            scenario_id=scenario_id,
                            version=version,
                            failed_turn_index=turn_index,
                            expected_turn_count=len(prompt_values),
                            thread_id=result.thread_id,
                            grade=grade,
                            broker_evidence=broker_evidence,
                            prompt_materialization_path=(
                                prompt_materialization_path
                            ),
                            gateway_failure_stage=(
                                _composer_failure_stage(
                                    protocol,
                                    broker_evidence,
                                )
                            ),
                        )
                        raise V3TaskRunnerError(
                            f"{scenario_id} turn {turn_index} failed task gates: "
                            f"common={common_failures}; "
                            f"reconciliation={grade.reconciliation.errors}",
                            thread_id=result.thread_id,
                        )
                    if turn_observer is not None:
                        turn_observer(turn_index, result, broker_evidence)
                    previous_prefix = effective_prefix
                    if terminal_indeterminate:
                        break
            if infrastructure_error is None:
                broker_evidence = broker.evidence()
        if infrastructure_error is not None:
            raise infrastructure_error
    finally:
        if workspace.exists():
            shutil.rmtree(workspace, ignore_errors=False)

    if broker_evidence is None:
        raise V3TaskRunnerError("fresh task completed without broker evidence")
    run = V3TaskRun(
        scenario_id=scenario_id,
        version=version,
        task_root=root,
        thread_id=results[0].thread_id if results else "",
        turns=tuple(results),
        turn_grades=tuple(grades),
        broker_evidence=broker_evidence,
        broker_protocol_passed=_broker_terminal_protocol_passed(
            protocol,
            broker_evidence,
        ),
    )
    task_result = {
        "contract": TASK_RESULT_CONTRACT,
        "scenario_id": scenario_id,
        "version": version,
        "thread_id": run.thread_id,
        "turn_count": len(run.turns),
        "passed": run.passed,
        "prompt_materialization_sha256": _sha256_file(
            prompt_materialization_path
        ),
        "broker": run.broker_evidence.as_dict(include_output=False),
        "turn_grades": [
            {
                **asdict(item),
                "passed": item.passed,
            }
            for item in run.turn_grades
        ],
    }
    if any(
        step.subcommand.startswith("draft-")
        or step.subcommand == "preview-from-draft"
        for step in protocol.steps
    ):
        broker_payload = run.broker_evidence.as_dict(include_output=False)
        broker_records = broker_payload["records"]
        steps_by_name = {step.name: step for step in protocol.steps}
        try:
            composer_evidence = validate_typed_draft_evidence(
                state_directory=root / "broker" / "state",
                steps=tuple(
                    steps_by_name[str(record["step_name"])]
                    for record in broker_records
                ),
                broker_records=broker_records,
            )
        except (TypedDraftEvidenceError, KeyError) as exc:
            raise V3TaskRunnerError(
                f"Composer task evidence cannot be sealed: {exc}",
                thread_id=run.thread_id,
            ) from exc
        if composer_evidence is None:
            raise V3TaskRunnerError(
                "Composer protocol completed without Composer evidence",
                thread_id=run.thread_id,
            )
        task_result["composer_evidence"] = composer_evidence
    if protocol.allowed_turn_prefix_counts:
        task_result["protocol_terminal_passed"] = run.broker_protocol_passed
        task_result["accepted_terminal_prefixes"] = list(
            protocol.accepted_terminal_prefixes
        )
    _write_json(root / "task-result.json", task_result)
    return run


def _broker_terminal_protocol_passed(
    protocol: V3GatewayProtocol,
    evidence: GatewayBrokerEvidence,
) -> bool:
    """Accept only one sealed complete protocol or declared optional prefix."""

    consumed_count = len(evidence.consumed_step_names)
    if consumed_count not in protocol.accepted_terminal_prefixes:
        return False
    if protocol.optional_query_schema_step_names:
        protocol_names = tuple(step.name for step in protocol.steps)
        optional_names = set(protocol.optional_query_schema_step_names)
        selected_names = evidence.expected_step_names
        if (
            not selected_names
            or selected_names[-1] != protocol_names[-1]
            or any(name not in optional_names for name in selected_names[:-1])
            or len(selected_names) != len(set(selected_names))
        ):
            return False
        return bool(
            evidence.consumed_step_names == selected_names
            and len(evidence.records) == len(selected_names)
            and tuple(record.step_name for record in evidence.records)
            == selected_names
            and not evidence.rejected_records
            and all(record.succeeded for record in evidence.records)
            and evidence.complete
            and evidence.passed
            and evidence.terminal_state == "COMPLETE"
        )
    if protocol.optional_initial_query_schema:
        protocol_names = tuple(step.name for step in protocol.steps)
        selected_names = evidence.expected_step_names
        if selected_names not in {protocol_names, protocol_names[1:]}:
            return False
        return bool(
            evidence.consumed_step_names == selected_names
            and len(evidence.records) == len(selected_names)
            and tuple(record.step_name for record in evidence.records)
            == selected_names
            and not evidence.rejected_records
            and all(record.succeeded for record in evidence.records)
            and evidence.complete
            and evidence.passed
            and evidence.terminal_state == "COMPLETE"
        )
    if protocol.optional_topic_schema_step_groups:
        protocol_names = tuple(step.name for step in protocol.steps)
        optional_names = {
            name
            for group in protocol.optional_topic_schema_step_groups
            for name in group
        }
        selected_names = evidence.expected_step_names
        selected_optional = tuple(
            name for name in selected_names if name in optional_names
        )
        mandatory_names = tuple(
            name for name in protocol_names if name not in optional_names
        )
        if (
            tuple(name for name in selected_names if name not in optional_names)
            != mandatory_names
            or len(selected_names) != len(set(selected_names))
            or any(name not in protocol_names for name in selected_names)
            or any(name not in optional_names for name in selected_optional)
        ):
            return False
        return bool(
            evidence.consumed_step_names == selected_names
            and len(evidence.records) == len(selected_names)
            and tuple(record.step_name for record in evidence.records)
            == selected_names
            and not evidence.rejected_records
            and all(record.succeeded for record in evidence.records)
            and evidence.complete
            and evidence.passed
            and evidence.terminal_state == "COMPLETE"
        )
    expected_names = tuple(
        step.name for step in protocol.steps[:consumed_count]
    )
    if (
        evidence.commutative_read_only_step_groups
        != protocol.commutative_read_only_step_groups
        or evidence.commutative_composer_setup_step_groups
        != protocol.commutative_composer_setup_step_groups
        or not gateway_step_sequence_matches(
            expected_names,
            evidence.consumed_step_names,
            protocol.commutative_read_only_step_groups,
            protocol.commutative_composer_setup_step_groups,
        )
        or len(evidence.records) != consumed_count
        or tuple(record.step_name for record in evidence.records)
        != evidence.consumed_step_names
        or evidence.rejected_records
        or not all(record.succeeded for record in evidence.records)
    ):
        return False
    if consumed_count == len(protocol.steps):
        return evidence.passed
    return (
        protocol.allowed_turn_prefix_counts
        and not evidence.complete
        and evidence.terminal_state == "RUNNING"
    )


def _grade_common_turn(
    result: CodexRunResult,
    *,
    turn_index: int,
    required_reference: str | None,
    expected_skill_reads: Sequence[str] | None = None,
    expected_gateway_count: int,
    expected_terminal_execute_exit2_count: int = 0,
    prompt_provenance: Any | None = None,
) -> tuple[tuple[str, ...], dict[str, bool]]:
    facts = result.command_facts
    allowed_reads = tuple(facts.allowed_read_commands)
    read_files = tuple(facts.skill_read_files)
    expected_reads = (
        tuple(expected_skill_reads)
        if expected_skill_reads is not None
        else (
            (
                ("SKILL.md", required_reference)
                if required_reference is not None
                else ("SKILL.md",)
            )
            if turn_index == 1
            else ()
        )
    )
    records = facts.command_records
    recoverable_read_indexes = frozenset(
        recoverable_preprocess_attempt_indexes(records)
    )
    effective_records = tuple(
        record
        for index, record in enumerate(records)
        if index not in recoverable_read_indexes
    )
    gateway_count = len(facts.gateway_attempt_commands)
    try:
        prompt_asset_reads = validated_prompt_asset_cat_commands(
            records,
            provenance=prompt_provenance,
            turn_index=turn_index,
        )
    except PromptAssetReadError:
        prompt_asset_reads = ()
    terminal_unexpected = remove_validated_command_occurrences(
        facts.unexpected_commands,
        prompt_asset_reads,
    )
    non_gateway_unexpected = remove_validated_command_occurrences(
        facts.non_gateway_unexpected_commands,
        prompt_asset_reads,
    )
    expected_terminal_unexpected = (
        len(terminal_unexpected) == expected_terminal_execute_exit2_count
        and all(
            command in facts.gateway_attempt_commands
            for command in terminal_unexpected
        )
    )
    gates = {
        "memory_isolated": result.isolation_audit.passed and not result.prompt_audit.has_memory,
        "one_completed_turn": (
            result.exit_status == 0
            and not result.timed_out
            and result.session_audit.passed
            and result.file_change_count == 0
        ),
        "one_target_skill": result.prompt_audit.passed,
        "no_collaboration": result.collab_call_count == 0,
        "skill_reads_exact": read_files == expected_reads and len(allowed_reads) == len(read_files),
        "read_prefix_exact": tuple(
            record.command for record in effective_records[: len(allowed_reads)]
        )
        == allowed_reads,
        "gateway_count_exact": gateway_count == expected_gateway_count,
        "no_other_commands": (
            len(effective_records)
            == len(allowed_reads)
            + len(prompt_asset_reads)
            + expected_gateway_count
        ),
        "no_discovery": not facts.discovery_commands,
        "no_direct_waapi": not facts.direct_waapi_client_commands,
        "no_write_like": not facts.write_like_commands,
        "no_unexpected_commands": (
            expected_terminal_unexpected
            and not non_gateway_unexpected
        ),
        "no_files_changed": (
            not result.created_files
            and not result.modified_files
            and not result.deleted_files
            and not result.created_source_files
            and not result.modified_source_files
            and not result.deleted_source_files
            and result.skill_tree_unchanged
        ),
    }
    errors = tuple(key for key, value in gates.items() if not value)
    return errors, gates


def _normalize_turn_reference_schedule(
    *,
    prompt_count: int,
    required_reference: str | None,
    turn_reference_schedule: Sequence[Sequence[str]] | None,
) -> tuple[tuple[str, ...], ...]:
    """Close per-turn lane reads while preserving the historical default.

    Callers schedule lane references only.  The runner owns the mandatory
    initial ``SKILL.md`` read, so it cannot be moved to a resumed turn or
    accidentally omitted.  A lane reference may appear at most once in the
    task, matching the Skill's conversation-scoped read contract.
    """

    if type(prompt_count) is not int or prompt_count < 1:
        raise V3TaskRunnerError("prompt_count must be a positive integer")
    if required_reference is not None and (
        not isinstance(required_reference, str)
        or required_reference not in _PACKAGED_LANE_REFERENCES
    ):
        raise V3TaskRunnerError(
            "required_reference must be one packaged waapi lane reference or None"
        )
    if required_reference is None:
        if turn_reference_schedule is not None:
            raise V3TaskRunnerError(
                "a SKILL-only task must not schedule lane references"
            )
        reference_rows = ((),) * prompt_count
        return (("SKILL.md",), *reference_rows[1:])
    if turn_reference_schedule is None:
        reference_rows: tuple[tuple[str, ...], ...] = (
            ((required_reference,),) + ((),) * (prompt_count - 1)
        )
    else:
        if isinstance(turn_reference_schedule, (str, bytes)):
            raise V3TaskRunnerError(
                "turn_reference_schedule must contain one row per prompt"
            )
        try:
            schedule_length = len(turn_reference_schedule)
        except TypeError as exc:
            raise V3TaskRunnerError(
                "turn_reference_schedule must contain one row per prompt"
            ) from exc
        if schedule_length != prompt_count:
            raise V3TaskRunnerError(
                "turn_reference_schedule must contain one row per prompt"
            )
        normalized_rows: list[tuple[str, ...]] = []
        seen: set[str] = set()
        for raw_row in turn_reference_schedule:
            if isinstance(raw_row, (str, bytes)):
                raise V3TaskRunnerError(
                    "turn_reference_schedule rows must be reference sequences"
                )
            try:
                row = tuple(raw_row)
            except TypeError as exc:
                raise V3TaskRunnerError(
                    "turn_reference_schedule rows must be reference sequences"
                ) from exc
            if len(row) > 1:
                raise V3TaskRunnerError(
                    "each Codex turn may read at most one waapi lane reference"
                )
            for reference in row:
                if (
                    not isinstance(reference, str)
                    or reference not in _PACKAGED_LANE_REFERENCES
                ):
                    raise V3TaskRunnerError(
                        "turn_reference_schedule contains an unreviewed reference"
                    )
                if reference in seen:
                    raise V3TaskRunnerError(
                        "a waapi lane reference may be read only once per task"
                    )
                seen.add(reference)
            normalized_rows.append(row)
        reference_rows = tuple(normalized_rows)
        if reference_rows[0] != (required_reference,):
            raise V3TaskRunnerError(
                "turn 1 must read the required_reference lane"
            )
    return (
        ("SKILL.md", *reference_rows[0]),
        *reference_rows[1:],
    )


def _terminal_execute_exit2_count(
    protocol: V3GatewayProtocol,
    evidence: GatewayBrokerEvidence,
    *,
    start: int,
    stop: int,
) -> int:
    expected = {
        step.name
        for step in protocol.steps[start:stop]
        if step.subcommand == "execute" and step.allowed_exit_codes == (0, 2)
    }
    if not expected:
        return 0
    records = {
        record.step_name: record
        for record in evidence.records
        if record.step_name in expected
    }
    return sum(
        record.succeeded and record.runner_exit_code == 2
        for record in records.values()
    )


def _gateway_candidate_argvs(
    result: CodexRunResult,
    *,
    skill_source: Path,
    alternate_skill_sources: Sequence[Path] = (),
    expected_wwise_version: str,
) -> tuple[tuple[str, ...], ...]:
    expected_runners = tuple(dict.fromkeys(
        os.path.abspath(os.fspath(source / "scripts" / "run.py"))
        for source in (skill_source, *alternate_skill_sources)
    ))
    records = result.command_facts.command_records
    recoverable_indexes = frozenset(
        recoverable_preprocess_attempt_indexes(records)
    )
    candidates: list[tuple[str, ...]] = []
    for index, record in enumerate(records):
        if index in recoverable_indexes:
            continue
        argv = normalized_gateway_command_argv(
            record.argv,
            expected_wwise_version=expected_wwise_version,
        )
        runner = _candidate_runner_path(argv, expected_runners=expected_runners)
        if runner is not None:
            candidates.append((argv[0], runner, *argv[2:]))
    return tuple(candidates)


def _gateway_candidate_records(
    result: CodexRunResult,
    *,
    skill_source: Path,
    alternate_skill_sources: Sequence[Path] = (),
    expected_wwise_version: str,
) -> tuple[CodexCommandRecord, ...]:
    """Keep raw Codex records for response-derived continuation binding."""

    expected_runners = tuple(dict.fromkeys(
        os.path.abspath(os.fspath(source / "scripts" / "run.py"))
        for source in (skill_source, *alternate_skill_sources)
    ))
    records = result.command_facts.command_records
    recoverable_indexes = frozenset(
        recoverable_preprocess_attempt_indexes(records)
    )
    candidates: list[CodexCommandRecord] = []
    for index, record in enumerate(records):
        if index in recoverable_indexes:
            continue
        argv = normalized_gateway_command_argv(
            record.argv,
            expected_wwise_version=expected_wwise_version,
        )
        if _candidate_runner_path(argv, expected_runners=expected_runners) is not None:
            candidates.append(record)
    return tuple(candidates)


def _candidate_runner_path(
    argv: Sequence[str],
    *,
    expected_runners: Sequence[str],
) -> str | None:
    if len(argv) < 4 or argv[2] != "gateway.py":
        return None
    supplied = Path(argv[1]).expanduser()
    if supplied.is_absolute():
        normalized = os.path.abspath(os.fspath(supplied))
        return normalized if normalized in expected_runners else None
    return next(
        (
            expected
            for expected in expected_runners
            if task_local_runner_matches_normalized(argv[1], expected)
        ),
        None,
    )


def _bind_gateway_prefix_reconciliation(
    raw_reconciliation: GatewayBrokerReconciliation,
    *,
    command_records: Sequence[CodexCommandRecord],
    broker_evidence: GatewayBrokerEvidence,
    prefix_errors: Sequence[str] = (),
    windows_powershell_core_host: WindowsPowerShellCoreHost | None = None,
    platform_name: str | None = None,
) -> GatewayBrokerReconciliation:
    """Add exact response-derived command binding to argv reconciliation."""

    continuation_errors = gateway_continuation_binding_errors(
        command_records,
        broker_evidence.accepted_records,
        platform_name=platform_name,
        windows_powershell_core_host=windows_powershell_core_host,
    )
    return GatewayBrokerReconciliation(
        passed=(
            raw_reconciliation.passed
            and not prefix_errors
            and not continuation_errors
        ),
        observed_command_count=raw_reconciliation.observed_command_count,
        accepted_record_count=raw_reconciliation.accepted_record_count,
        errors=(
            *raw_reconciliation.errors,
            *prefix_errors,
            *continuation_errors,
        ),
    )


def _prepare_agent_workspace(
    workspace: Path,
    skill_source: Path,
    *,
    platform_name: str | None = None,
) -> Path:
    return prepare_workspace_skill_install(
        workspace,
        skill_source,
        platform_name=platform_name,
    )


def _archive_turn(
    output_dir: Path,
    *,
    prompt: str,
    result: CodexRunResult,
    grade: V3TurnGrade,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_utf8_text_bytes(output_dir / "prompt.txt", prompt + "\n")
    write_utf8_text_bytes(output_dir / "events.jsonl", result.stdout)
    write_utf8_text_bytes(output_dir / "stderr.txt", result.stderr)
    write_utf8_text_bytes(output_dir / "final.txt", result.final_response + "\n")
    _write_json(output_dir / "codex-facts.json", result.facts_dict())
    _write_json(
        output_dir / "turn-grade.json",
        {**asdict(grade), "passed": grade.passed},
    )


def _archive_command_lifecycle_failure(
    root: Path,
    *,
    output_dir: Path,
    scenario_id: str,
    version: str,
    turn_index: int,
    expected_turn_count: int,
    prompt: str,
    result: CodexRunResult,
    broker_evidence: GatewayBrokerEvidence,
) -> None:
    """Seal an unmatched Codex command lifecycle as non-retryable BLOCKED.

    The command may already have affected the disposable Wwise sandbox, so
    this is intentionally distinct from the pre-agent infrastructure contract.
    The caller must quarantine the scenario and start a fresh lifecycle.
    """

    anomalies = _command_lifecycle_anomalies(result.stdout)
    if not anomalies:
        raise V3TaskRunnerError(
            "incomplete command count cannot be reconstructed from Codex events"
        )
    broker_path = root / "command-lifecycle-broker-evidence.json"
    _write_json(broker_path, broker_evidence.as_dict(include_output=False))
    artifact_paths = (
        output_dir / "prompt.txt",
        output_dir / "events.jsonl",
        output_dir / "stderr.txt",
        output_dir / "final.txt",
        output_dir / "codex-facts.json",
        output_dir / "turn-grade.json",
        broker_path,
    )
    _write_json(
        root / "command-lifecycle-failure.json",
        {
            "contract": TASK_COMMAND_LIFECYCLE_FAILURE_CONTRACT,
            "scenario_id": scenario_id,
            "version": version,
            "failed_turn_index": turn_index,
            "expected_turn_count": expected_turn_count,
            "prompt_sha256": _sha256_text(prompt),
            "incomplete_command_count": (
                result.session_audit.incomplete_command_count
            ),
            "anomalies": anomalies,
            "non_retryable": True,
            "fresh_sandbox_required": True,
            "artifact_sha256": {
                path.relative_to(root).as_posix(): _sha256_file(path)
                for path in artifact_paths
            },
        },
    )


def _archive_task_gate_failure(
    root: Path,
    *,
    scenario_id: str,
    version: str,
    failed_turn_index: int,
    expected_turn_count: int,
    thread_id: str,
    grade: V3TurnGrade,
    broker_evidence: GatewayBrokerEvidence,
    prompt_materialization_path: Path,
    gateway_failure_stage: str | None = None,
) -> None:
    """Archive bounded diagnostics without changing the semantic verdict."""

    broker_path = root / "task-gate-broker-evidence.json"
    _write_json(broker_path, broker_evidence.as_dict(include_output=False))
    turn_artifacts = tuple(
        root / "turns" / f"turn-{index:02d}" / filename
        for index in range(1, failed_turn_index + 1)
        for filename in (
            "prompt.txt",
            "events.jsonl",
            "stderr.txt",
            "final.txt",
            "codex-facts.json",
            "turn-grade.json",
        )
    )
    artifact_paths = (
        prompt_materialization_path,
        *turn_artifacts,
        broker_path,
    )
    missing = tuple(
        path.relative_to(root).as_posix()
        for path in artifact_paths
        if not path.is_file()
    )
    if missing:
        raise V3TaskRunnerError(
            "task-gate diagnostic archive is incomplete: " + ", ".join(missing)
        )
    payload = {
        "contract": TASK_GATE_FAILURE_CONTRACT,
        "scenario_id": scenario_id,
        "version": version,
        "failed_turn_index": failed_turn_index,
        "expected_turn_count": expected_turn_count,
        "thread_id": thread_id,
        "prompt_sha256": grade.prompt_sha256,
        "broker_prefix_count": grade.broker_prefix_count,
        "reconciliation": asdict(grade.reconciliation),
        "failed_common_gates": [
            key for key, passed in grade.common_gates.items() if not passed
        ],
        "grade_errors": list(grade.errors),
        "diagnostic_only": True,
        "artifact_sha256": {
            path.relative_to(root).as_posix(): _sha256_file(path)
            for path in artifact_paths
        },
    }
    if gateway_failure_stage is not None:
        payload["gateway_failure_stage"] = gateway_failure_stage
    _write_json(root / "task-gate-failure.json", payload)


def _composer_failure_stage(
    protocol: V3GatewayProtocol,
    broker_evidence: GatewayBrokerEvidence,
) -> str | None:
    if not any(
        step.subcommand.startswith("draft-")
        or step.subcommand == "preview-from-draft"
        for step in protocol.steps
    ):
        return None
    steps_by_name = {step.name: step for step in protocol.steps}
    if broker_evidence.records:
        final_name = broker_evidence.records[-1].step_name
        if final_name in steps_by_name and not broker_evidence.records[-1].succeeded:
            return classify_composer_failure_stage(
                steps_by_name[final_name].subcommand
            )
    next_index = len(broker_evidence.consumed_step_names)
    subcommand = (
        protocol.steps[next_index].subcommand
        if next_index < len(protocol.steps)
        else protocol.steps[-1].subcommand
    )
    return classify_composer_failure_stage(subcommand)


def _command_lifecycle_anomalies(stdout: str) -> list[dict[str, Any]]:
    phases: dict[str, dict[str, Mapping[str, Any]]] = {
        "item.started": {},
        "item.completed": {},
    }
    anonymous: list[dict[str, Any]] = []
    for event_index, line in enumerate(stdout.splitlines(), start=1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        event_type = event.get("type") if isinstance(event, Mapping) else None
        item = event.get("item") if isinstance(event, Mapping) else None
        if (
            event_type not in phases
            or not isinstance(item, Mapping)
            or item.get("type") != "command_execution"
        ):
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            anonymous.append(
                {
                    "event_index": event_index,
                    "phase": event_type,
                    "item_id": None,
                    "command": str(item.get("command") or ""),
                    "status": str(item.get("status") or ""),
                }
            )
            continue
        phases[event_type][item_id] = item
    started = phases["item.started"]
    completed = phases["item.completed"]
    anomalies = list(anonymous)
    for item_id in sorted(set(started) ^ set(completed)):
        phase = (
            "started_without_completed"
            if item_id in started
            else "completed_without_started"
        )
        item = started.get(item_id) or completed[item_id]
        anomalies.append(
            {
                "event_index": None,
                "phase": phase,
                "item_id": item_id,
                "command": str(item.get("command") or ""),
                "status": str(item.get("status") or ""),
            }
        )
    return anomalies


def _archive_infrastructure_failure(
    root: Path,
    *,
    output_dir: Path,
    scenario_id: str,
    version: str,
    turn_index: int,
    expected_turn_count: int,
    prior_completed_turn_count: int,
    previous_broker_prefix: int,
    expected_failed_turn_prefix: int,
    prior_thread_id: str | None,
    prompt: str,
    result: CodexRunResult,
    failure: CodexInfrastructureFailure,
    broker_evidence: GatewayBrokerEvidence,
    prompt_materialization_path: Path,
) -> None:
    """Seal a pre-agent Codex failure without persisting exception prose."""

    output_dir.mkdir(parents=True, exist_ok=True)
    failed_turn_files = {
        "prompt.txt": prompt + "\n",
        "events.jsonl": result.stdout,
        "stderr.txt": result.stderr,
        "final.txt": result.final_response + "\n",
    }
    for name, value in failed_turn_files.items():
        write_utf8_text_bytes(output_dir / name, value)
    _write_json(output_dir / "codex-facts.json", result.facts_dict())

    broker_path = root / "broker-evidence.json"
    _write_json(broker_path, broker_evidence.as_dict(include_output=False))

    artifact_paths = (
        prompt_materialization_path,
        output_dir / "prompt.txt",
        output_dir / "events.jsonl",
        output_dir / "stderr.txt",
        output_dir / "final.txt",
        output_dir / "codex-facts.json",
        broker_path,
    )
    artifact_sha256 = {
        path.relative_to(root).as_posix(): _sha256_file(path)
        for path in artifact_paths
    }
    _write_json(
        root / "infrastructure-failure.json",
        {
            "contract": TASK_INFRASTRUCTURE_FAILURE_CONTRACT,
            "scenario_id": scenario_id,
            "version": version,
            "failed_turn_index": turn_index,
            "expected_turn_count": expected_turn_count,
            "prior_completed_turn_count": prior_completed_turn_count,
            "previous_broker_prefix": previous_broker_prefix,
            "expected_failed_turn_prefix": expected_failed_turn_prefix,
            "prior_thread_id": prior_thread_id,
            "prompt_sha256": _sha256_text(prompt),
            "failure": {
                "category": failure.category,
                "turn_failed": failure.turn_failed,
                "timed_out": failure.timed_out,
                "agent_item_event_count": failure.agent_item_event_count,
            },
            "artifact_sha256": artifact_sha256,
        },
    )


def _archive_prompt_materialization(
    root: Path,
    *,
    provenance: Any,
    business_oracle_plan: BusinessOraclePlanEvidence,
) -> Path:
    """Archive one receipt joining the fixed prompt and business plan."""

    path = root / PROMPT_MATERIALIZATION_FILE
    _write_json(
        path,
        prompt_materialization_receipt(
            provenance,
            business_oracle_plan=business_oracle_plan,
        ),
    )
    return path


def _validate_infrastructure_failure(
    *,
    prompt: str,
    result: CodexRunResult,
    failure: CodexInfrastructureFailure,
    broker_evidence: GatewayBrokerEvidence,
    expected_step_names: tuple[str, ...],
    previous_broker_prefix: int,
    allow_complete_prefix_failure: bool = False,
) -> None:
    """Prove the infrastructure failure preceded every model-side action."""

    facts = result.command_facts
    session = result.session_audit
    command_collections = (
        facts.commands,
        facts.inline_python_commands,
        facts.direct_waapi_client_commands,
        facts.write_like_commands,
        facts.gateway_commands,
        facts.discovery_commands,
        facts.command_records,
        facts.gateway_attempt_commands,
        facts.gateway_subcommands,
        facts.gateway_results,
        facts.gateway_evidence_apis,
        facts.allowed_read_commands,
        facts.skill_read_files,
        facts.unexpected_commands,
        facts.non_gateway_unexpected_commands,
    )
    file_collections = (
        result.created_files,
        result.modified_files,
        result.deleted_files,
        result.created_source_files,
        result.modified_source_files,
        result.deleted_source_files,
    )
    expected_prefix_names = expected_step_names[:previous_broker_prefix]
    broker_records = broker_evidence.records
    gates = {
        "failure_shape": (
            failure.category in _CODEX_INFRASTRUCTURE_CATEGORIES
            and type(failure.turn_failed) is bool
            and type(failure.timed_out) is bool
            and type(failure.agent_item_event_count) is int
        ),
        "failure_pre_agent": failure.agent_item_event_count == 0,
        "failure_timeout_consistent": failure.timed_out is result.timed_out,
        "command_facts_empty": (
            all(not values for values in command_collections)
            and not facts.skill_read
            and not facts.gateway_before_discovery
        ),
        "session_has_no_actions": (
            session.collab_call_count == 0
            and session.file_change_count == 0
            and session.command_started_count == 0
            and session.command_completed_count == 0
            and session.incomplete_command_count == 0
            and not session.unexpected_item_types
        ),
        "result_has_no_actions": (
            result.collab_call_count == 0
            and result.file_change_count == 0
            and result.final_response == ""
            and all(not values for values in file_collections)
        ),
        "jsonl_valid": session.invalid_json_line_count == 0,
        "prompt_isolated": (
            result.prompt_audit.passed
            and not result.prompt_audit.has_memory
            and result.isolation_audit.passed
        ),
        "prompt_bound": bool(prompt),
        "skill_tree_unchanged": (
            result.skill_tree_unchanged
            and _is_sha256(result.skill_tree_sha256_before)
            and result.skill_tree_sha256_before == result.skill_tree_sha256_after
        ),
        "broker_expected_steps_exact": (
            broker_evidence.expected_step_names == expected_step_names
        ),
        "broker_prefix_exact": (
            0 <= previous_broker_prefix <= len(expected_step_names)
            and gateway_step_sequence_matches(
                expected_prefix_names,
                broker_evidence.consumed_step_names,
                broker_evidence.commutative_read_only_step_groups,
                broker_evidence.commutative_composer_setup_step_groups,
            )
            and len(broker_records) == previous_broker_prefix
            and tuple(record.step_name for record in broker_records)
            == broker_evidence.consumed_step_names
            and all(record.succeeded for record in broker_records)
            and (
                (
                    allow_complete_prefix_failure
                    and previous_broker_prefix == len(expected_step_names)
                    and broker_evidence.complete
                    and broker_evidence.passed
                    and broker_evidence.terminal_state == "COMPLETE"
                )
                or (
                    not allow_complete_prefix_failure
                    and previous_broker_prefix < len(expected_step_names)
                    and not broker_evidence.complete
                    and not broker_evidence.passed
                    and broker_evidence.terminal_state == "RUNNING"
                )
            )
        ),
    }
    failures = tuple(name for name, passed in gates.items() if not passed)
    if failures:
        raise V3TaskRunnerError(
            "Codex infrastructure failure lacks clean pre-agent proof: "
            + ", ".join(failures)
        )


def _ordered_unique(values: Sequence[str] | Any) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return tuple(result)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_utf8_text_bytes(
        path,
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2, default=str)
        + "\n",
    )


__all__ = [
    "PROMPT_MATERIALIZATION_CONTRACT",
    "PROMPT_MATERIALIZATION_FILE",
    "TASK_COMMAND_LIFECYCLE_FAILURE_CONTRACT",
    "TASK_GATE_FAILURE_CONTRACT",
    "TASK_INFRASTRUCTURE_FAILURE_CONTRACT",
    "TASK_RESULT_CONTRACT",
    "V3CommandLifecycleError",
    "V3TaskRun",
    "V3TaskRunnerError",
    "V3TurnGrade",
    "run_v3_codex_task",
]
