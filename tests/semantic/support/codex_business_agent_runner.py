"""Shared production-Gateway lifecycle for closed Business Agent profiles."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from tests.semantic.support.codex_gateway_broker import (
    CodexGatewayBroker,
    ExpectedGatewayStep,
)
from tests.semantic.support.codex_harness import (
    CodexCliTask,
    CodexHarnessConfig,
    WindowsPowerShellCoreHost,
    gateway_continuation_binding_errors,
    prepare_workspace_skill_install,
    recoverable_preprocess_attempt_indexes,
    semantic_task_developer_instructions,
)
from tests.semantic.support.codex_task_runner_v3 import (
    _gateway_candidate_argvs,
    _gateway_candidate_records,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ENV = "WAAPI_BUSINESS_AGENT_FIXTURE"
WAAPI_SHIM_ROOT = (
    REPO_ROOT / "tests" / "semantic" / "data" / "business-agent" / "waapi-shim"
)


@dataclass(frozen=True, slots=True)
class BusinessAgentOptions:
    skill_source: Path
    codex_binary: Path
    auth_json: Path
    model: str
    reasoning_effort: str
    service_tier: str
    timeout_seconds: float
    windows_powershell_core_host: WindowsPowerShellCoreHost | None = None


@dataclass(frozen=True, slots=True)
class BusinessAgentRunSpec:
    prepare_runtime: Callable[[Any, Path], Any]
    build_steps: Callable[[Any], Sequence[Any]]
    transaction_count: Callable[[Any], int]
    preview_gates: Callable[[Any, Any, Any, Any], Mapping[str, bool]]
    outcome_factory: Callable[..., Any]
    optional_initial_operations_discovery_operation: str | None = None
    prepare_broker_state: Callable[[Any, Path], None] | None = None
    allow_compound_checked_child_handoff: bool = False
    optional_initial_query_object_arguments: (
        Callable[[Any], Sequence[str]] | None
    ) = None
    requires_initial_operations_discovery: bool = False


def _only_expected_business_commands(
    facts: Any,
    gateway_argvs: Sequence[Sequence[str]],
) -> bool:
    records = facts.command_records
    recoverable = recoverable_preprocess_attempt_indexes(records)
    effective_count = len(records) - len(recoverable)
    return (
        not facts.unexpected_commands
        and effective_count
        == len(gateway_argvs) + len(facts.allowed_read_commands)
    )


def _expected_gateway_subcommands(
    steps: Sequence[Any],
    *,
    optional_initial_operations_discovery_operation: str | None,
    optional_initial_query_object_arguments: Sequence[str] | None = None,
) -> tuple[str, ...]:
    prefix = (
        ("operations",)
        if optional_initial_operations_discovery_operation is not None
        else ()
    )
    query_prefix = (
        ("query-object",)
        if optional_initial_query_object_arguments is not None
        else ()
    )
    return tuple(
        dict.fromkeys(
            (*prefix, *query_prefix, *(step.subcommand for step in steps))
        )
    )


def business_agent_optional_operations_discovery(
    unit: Any,
    *,
    explicit: str | None,
    steps: Sequence[Any] = (),
) -> str | None:
    """Permit the one Skill-documented discovery hop for natural-language intent."""

    if steps and getattr(steps[0], "subcommand", None) == "operations":
        return None
    if explicit is not None:
        return explicit
    operation = getattr(unit, "operation", None)
    if isinstance(operation, str) and operation:
        return operation
    if steps:
        first = steps[0]
        arguments = getattr(first, "arguments", ())
        if (
            getattr(first, "subcommand", None)
            in {"operation-schema", "request-schema"}
            and isinstance(arguments, tuple)
            and len(arguments) == 1
            and isinstance(arguments[0], str)
            and arguments[0]
        ):
            return arguments[0]
    return None


def business_agent_required_operations_steps(
    unit: Any,
    *,
    steps: Sequence[Any],
    explicit: str | None,
) -> tuple[Any, ...]:
    """Put one catalog read before every new natural-language schema route."""

    reviewed = tuple(steps)
    if not reviewed or getattr(reviewed[0], "subcommand", None) == "operations":
        return reviewed
    target = business_agent_optional_operations_discovery(
        unit,
        explicit=explicit,
        steps=reviewed,
    )
    if target is None:
        return reviewed
    first_name = getattr(reviewed[0], "name", "business.schema")
    label = first_name.rsplit(".", 1)[0]
    return (
        ExpectedGatewayStep(
            name=f"{label}.operations",
            subcommand="operations",
        ),
        *reviewed,
    )


def run_business_agent_unit(
    unit: Any,
    *,
    scenario_root: Path,
    options: BusinessAgentOptions,
    spec: BusinessAgentRunSpec,
) -> Any:
    """Run one fresh task through the shared Broker-owned Preview boundary."""

    root = Path(scenario_root).expanduser().resolve(strict=False)
    evidence = root / "evidence"
    task_root = evidence / "codex-task"
    workspace = task_root / "agent-workspace"
    evidence.mkdir(parents=True, exist_ok=False)
    skill_install = prepare_workspace_skill_install(workspace, options.skill_source)
    runtime = spec.prepare_runtime(unit, task_root / "runtime")
    built_steps = tuple(spec.build_steps(runtime))
    steps = (
        business_agent_required_operations_steps(
            unit,
            steps=built_steps,
            explicit=spec.optional_initial_operations_discovery_operation,
        )
        if spec.requires_initial_operations_discovery
        else built_steps
    )
    optional_operations_discovery = (
        business_agent_optional_operations_discovery(
            unit,
            explicit=spec.optional_initial_operations_discovery_operation,
            steps=built_steps,
        )
        if not spec.requires_initial_operations_discovery
        else None
    )
    optional_query_arguments = (
        None
        if spec.optional_initial_query_object_arguments is None
        else tuple(spec.optional_initial_query_object_arguments(runtime))
    )
    runner_environment = dict(os.environ)
    runner_environment.update(
        {
            "PYTHONPATH": os.pathsep.join(
                (
                    str(WAAPI_SHIM_ROOT),
                    str(REPO_ROOT),
                    str(REPO_ROOT / "skills/waapi-skill"),
                )
            ),
            FIXTURE_ENV: str(runtime.fixture_path),
            "WWISE_VERSION": unit.version,
            "WWISE_WAAPI_HOST": "127.0.0.1",
            "WWISE_WAAPI_PORT": "31337",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    broker = CodexGatewayBroker(
        skill_source=options.skill_source,
        invocation_skill_source=skill_install,
        expected_steps=steps,
        expected_wwise_version=unit.version,
        project_modification_policy="ask_before_changes",
        runner_environment=runner_environment,
        working_root=task_root / "broker",
        transport="tcp",
        runner_timeout_seconds=max(120.0, options.timeout_seconds),
        optional_initial_operations_discovery_operation=(
            optional_operations_discovery
        ),
        optional_initial_query_object_arguments=optional_query_arguments,
    )
    developer_instructions = semantic_task_developer_instructions(
        options.skill_source / "scripts" / "run.py",
        task_skill_source=skill_install,
        expected_skill_reads=(("SKILL.md", "references/waapi-operate.md"),),
    )
    config = CodexHarnessConfig(
        workspace=workspace,
        skill_source=options.skill_source,
        codex_binary=options.codex_binary,
        windows_powershell_core_host=options.windows_powershell_core_host,
        auth_json=options.auth_json,
        model=options.model,
        reasoning_effort=options.reasoning_effort,
        service_tier=options.service_tier,
        timeout_seconds=options.timeout_seconds,
        expected_gateway_subcommands=_expected_gateway_subcommands(
            steps,
            optional_initial_operations_discovery_operation=(
                optional_operations_discovery
            ),
            optional_initial_query_object_arguments=optional_query_arguments,
        ),
        expected_wwise_version=unit.version,
        sandbox_mode="workspace-write",
        allow_output_write=False,
        network_access=True,
        developer_instructions=developer_instructions,
    )
    with broker:
        if spec.prepare_broker_state is not None:
            spec.prepare_broker_state(runtime, broker.state_directory)
        with CodexCliTask(config, extra_env=broker.model_environment_overrides()) as task:
            result = task.run_initial(runtime.prompt, output_dir=task_root / "turn-01")
        broker_evidence = broker.evidence()
        argvs = _gateway_candidate_argvs(
            result,
            skill_source=skill_install,
            alternate_skill_sources=(options.skill_source,),
            expected_wwise_version=unit.version,
        )
        gateway_records = _gateway_candidate_records(
            result,
            skill_source=skill_install,
            alternate_skill_sources=(options.skill_source,),
            expected_wwise_version=unit.version,
        )
        reconciliation = broker.reconcile(argvs)
        continuation_errors = gateway_continuation_binding_errors(
            gateway_records,
            broker_evidence.accepted_records,
            platform_name=(
                "nt"
                if options.windows_powershell_core_host is not None
                else "posix"
            ),
            windows_powershell_core_host=(
                options.windows_powershell_core_host
            ),
            allow_compound_checked_child_handoff=(
                spec.allow_compound_checked_child_handoff
            ),
        )

    facts = result.command_facts
    gates = {
        "codex_exit_zero": result.exit_status == 0 and not result.timed_out,
        "fresh_thread": bool(result.thread_id),
        "broker_passed": broker_evidence.passed,
        "exact_protocol": (
            broker_evidence.passed
            and reconciliation.passed
            and not continuation_errors
        ),
        "production_skill_read": facts.skill_read
        and set(facts.skill_read_files) == {"SKILL.md", "references/waapi-operate.md"},
        "no_unexpected_commands": _only_expected_business_commands(facts, argvs),
        "no_inline_python": not facts.inline_python_commands,
        "no_direct_waapi": not facts.direct_waapi_client_commands,
        "no_workspace_changes": result.file_change_count == 0,
        "skill_unchanged": result.skill_tree_unchanged,
        **dict(spec.preview_gates(unit, runtime, result, broker_evidence)),
        "no_execute": all(step.subcommand != "execute" for step in steps)
        and not any(
            record.gateway_arguments[:1] == ("execute",)
            for record in broker_evidence.records
        ),
    }
    errors = [name for name, passed in gates.items() if not passed]
    outcome = spec.outcome_factory(
        scenario_id=unit.unit_id,
        version=unit.version,
        status="PASS" if not errors else "FAIL",
        reason="" if not errors else "failed gates: " + ", ".join(errors),
        thread_id=result.thread_id,
        gates=gates,
        command_count=len(argvs),
        transaction_count=spec.transaction_count(runtime),
        production_gateway=True,
        wwise_started=False,
        final_response=result.final_response,
    )
    for path, payload in (
        (evidence / "broker-evidence.json", broker_evidence.as_dict(include_output=False)),
        (evidence / "broker-reconciliation.json", asdict(reconciliation)),
        (evidence / "codex-result-facts.json", result.facts_dict()),
        (evidence / "outcome.json", outcome.as_dict()),
        (root / "outcome.json", outcome.as_dict()),
    ):
        path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    return outcome


__all__ = [
    "BusinessAgentOptions",
    "BusinessAgentRunSpec",
    "run_business_agent_unit",
]
