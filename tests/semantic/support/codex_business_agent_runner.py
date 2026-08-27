"""Shared production-Gateway lifecycle for closed Business Agent profiles."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from tests.semantic.support.codex_gateway_broker import CodexGatewayBroker
from tests.semantic.support.codex_harness import (
    CodexCliTask,
    CodexHarnessConfig,
    WindowsPowerShellCoreHost,
    prepare_workspace_skill_install,
    semantic_task_developer_instructions,
)
from tests.semantic.support.codex_task_runner_v3 import _gateway_candidate_argvs


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
    allow_optional_initial_operations_discovery: bool = False


def _expected_gateway_subcommands(
    steps: Sequence[Any],
    *,
    allow_optional_initial_operations_discovery: bool,
) -> tuple[str, ...]:
    prefix = (
        ("operations",)
        if allow_optional_initial_operations_discovery
        else ()
    )
    return tuple(dict.fromkeys((*prefix, *(step.subcommand for step in steps))))


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
    steps = tuple(spec.build_steps(runtime))
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
        allow_optional_initial_operations_discovery=(
            spec.allow_optional_initial_operations_discovery
        ),
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
            allow_optional_initial_operations_discovery=(
                spec.allow_optional_initial_operations_discovery
            ),
        ),
        expected_wwise_version=unit.version,
        sandbox_mode="workspace-write",
        allow_output_write=False,
        network_access=True,
        developer_instructions=developer_instructions,
    )
    with broker:
        with CodexCliTask(config, extra_env=broker.model_environment_overrides()) as task:
            result = task.run_initial(runtime.prompt, output_dir=task_root / "turn-01")
        broker_evidence = broker.evidence()
        argvs = _gateway_candidate_argvs(
            result,
            skill_source=skill_install,
            alternate_skill_sources=(options.skill_source,),
            expected_wwise_version=unit.version,
        )
        reconciliation = broker.reconcile(argvs)

    facts = result.command_facts
    gates = {
        "codex_exit_zero": result.exit_status == 0 and not result.timed_out,
        "fresh_thread": bool(result.thread_id),
        "broker_passed": broker_evidence.passed,
        "exact_protocol": broker_evidence.passed and reconciliation.passed,
        "production_skill_read": facts.skill_read
        and set(facts.skill_read_files) == {"SKILL.md", "references/waapi-operate.md"},
        "no_unexpected_commands": len(facts.command_records)
        == len(argvs) + len(facts.allowed_read_commands),
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
