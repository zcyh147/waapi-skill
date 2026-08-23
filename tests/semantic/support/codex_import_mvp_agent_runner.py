"""Fresh memory-off Codex runner for the test-only #52 import MVP."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from tests.semantic.support.codex_gateway_broker import (
    CodexGatewayBroker,
    ExpectedGatewayStep,
)
from tests.semantic.support.codex_harness import (
    CodexCliTask,
    CodexHarnessConfig,
    WindowsPowerShellCoreHost,
    prepare_workspace_skill_install,
    semantic_task_developer_instructions,
)
from tests.semantic.support.codex_import_mvp_profile import ImportMvpUnit
from tests.semantic.support.codex_import_mvp_fake_gateway import (
    RUNTIME_ROOT_ENV,
    SKILL_ROOT_ENV,
    VERSION_ENV,
    prepare_import_mvp_runtime,
)
from tests.semantic.support.codex_task_runner_v3 import _gateway_candidate_argvs


OUTCOME_CONTRACT = "waapi-skill.deep-interface-mvp-agent-outcome/v1"
REPO_ROOT = Path(__file__).resolve().parents[3]
_NO_EXECUTION_MARKERS = (
    "未执行",
    "未实际导入",
    "未修改",
    "没有修改",
    "no execution",
    "not executed",
    "no changes",
)


@dataclass(frozen=True, slots=True)
class ImportMvpAgentOptions:
    skill_source: Path
    codex_binary: Path
    auth_json: Path
    model: str
    reasoning_effort: str
    service_tier: str
    timeout_seconds: float
    windows_powershell_core_host: WindowsPowerShellCoreHost | None = None


@dataclass(frozen=True, slots=True)
class ImportMvpAgentOutcome:
    scenario_id: str
    version: str
    status: str
    reason: str
    thread_id: str
    gates: Mapping[str, bool]
    command_count: int
    final_response: str

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def as_dict(self) -> dict[str, Any]:
        return {"contract": OUTCOME_CONTRACT, **asdict(self)}


def import_mvp_developer_instructions(
    *,
    skill_source: Path,
    skill_install: Path,
) -> str:
    """Seal the standard one-time Skill bootstrap for the MVP task."""

    return semantic_task_developer_instructions(
        skill_source / "scripts" / "run.py",
        task_skill_source=skill_install,
        expected_skill_reads=(("SKILL.md",),),
    )


def preview_was_reported(
    *,
    final_response: str,
    expected_markers: tuple[str, ...],
    broker_records: tuple[Any, ...],
) -> bool:
    """Grade business content without requiring one fixed prose rendering."""

    if not broker_records:
        return False
    preview_results: list[Mapping[str, Any]] = []
    for record in broker_records:
        if getattr(record, "step_name", "").split("-")[-2:] != ["mvp", "preview"]:
            continue
        payload = getattr(record, "payload", None)
        result = payload.get("agent_result") if isinstance(payload, Mapping) else None
        if not isinstance(result, Mapping):
            return False
        preview_results.append(result)
    if (
        not preview_results
        or getattr(broker_records[-1], "step_name", "").split("-")[-2:]
        != ["mvp", "preview"]
        or any(result.get("wwise_mutated") is not False for result in preview_results)
        or any(
            not isinstance(result.get("preview"), list)
            or not all(isinstance(line, str) for line in result["preview"])
            for result in preview_results
        )
    ):
        return False
    combined = (
        final_response
        + "\n"
        + "\n".join(
            line
            for result in preview_results
            for line in result["preview"]
        )
    ).casefold()
    return all(marker.casefold() in combined for marker in expected_markers) and any(
        marker in final_response.casefold() for marker in _NO_EXECUTION_MARKERS
    )


def mvp_command_set_is_closed(
    *,
    command_facts: Any,
    gateway_argvs: tuple[tuple[str, ...], ...],
    reconciliation_passed: bool,
) -> bool:
    """Accept only the Skill read plus authenticated test-Gateway commands."""

    return (
        reconciliation_passed
        and len(command_facts.command_records)
        == len(gateway_argvs) + len(command_facts.allowed_read_commands)
        and not command_facts.discovery_commands
        and not command_facts.write_like_commands
    )


def run_import_mvp_agent_unit(
    unit: ImportMvpUnit,
    *,
    scenario_root: Path,
    options: ImportMvpAgentOptions,
) -> ImportMvpAgentOutcome:
    root = Path(scenario_root).expanduser().resolve(strict=False)
    evidence = root / "evidence"
    task_root = evidence / "codex-task"
    workspace = task_root / "agent-workspace"
    evidence.mkdir(parents=True, exist_ok=False)
    skill_install = prepare_workspace_skill_install(workspace, options.skill_source)
    runtime_root = prepare_import_mvp_runtime(task_root / "mvp-runtime")
    steps = tuple(
        ExpectedGatewayStep(
            name=f"step-{index:02d}-{command[0]}",
            subcommand=command[0],
            arguments=tuple(command[1:]),
        )
        for index, command in enumerate(unit.commands, start=1)
    )
    broker = CodexGatewayBroker(
        skill_source=options.skill_source,
        invocation_skill_source=skill_install,
        expected_steps=steps,
        expected_wwise_version=unit.version,
        project_modification_policy="read_only",
        runner_environment={
            "PYTHONPATH": os.pathsep.join(
                (
                    str(REPO_ROOT),
                    str(REPO_ROOT / "skills/waapi-skill"),
                )
            ),
            RUNTIME_ROOT_ENV: str(runtime_root),
            SKILL_ROOT_ENV: str(REPO_ROOT / "skills/waapi-skill"),
            VERSION_ENV: unit.version,
        },
        working_root=task_root / "broker",
        transport="tcp",
        runner_timeout_seconds=max(120.0, options.timeout_seconds),
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
        expected_gateway_subcommands=tuple(command[0] for command in unit.commands),
        expected_wwise_version=unit.version,
        sandbox_mode="workspace-write",
        allow_output_write=False,
        network_access=True,
        developer_instructions=import_mvp_developer_instructions(
            skill_source=options.skill_source,
            skill_install=skill_install,
        ),
    )
    with broker:
        with CodexCliTask(config, extra_env=broker.model_environment_overrides()) as task:
            result = task.run_initial(unit.prompt, output_dir=task_root / "turn-01")
        broker_evidence = broker.evidence()
        argvs = _gateway_candidate_argvs(
            result,
            skill_source=skill_install,
            alternate_skill_sources=(options.skill_source,),
            expected_wwise_version=unit.version,
        )
        reconciliation = broker.reconcile(argvs)

    facts = result.command_facts
    # The production command classifier intentionally knows only public
    # Gateway subcommands, so this test-only Skill's ``mvp-*`` commands appear
    # in its generic inline-Python bucket.  Broker reconciliation is the
    # stronger authority here: every non-read command must be one of the exact
    # authenticated MVP argv records, with no room for an extra shell command.
    closed_command_set = mvp_command_set_is_closed(
        command_facts=facts,
        gateway_argvs=argvs,
        reconciliation_passed=reconciliation.passed,
    )
    gates = {
        "codex_exit_zero": result.exit_status == 0 and not result.timed_out,
        "fresh_thread": bool(result.thread_id),
        "broker_passed": broker_evidence.passed,
        "exact_protocol": reconciliation.passed
        and tuple(broker_evidence.consumed_step_names)
        == tuple(step.name for step in steps),
        "skill_read_once": facts.skill_read and len(facts.skill_read_files) == 1,
        "no_unexpected_commands": closed_command_set,
        "no_inline_python": closed_command_set,
        "no_direct_waapi": not facts.direct_waapi_client_commands,
        "no_workspace_changes": result.file_change_count == 0,
        "skill_unchanged": result.skill_tree_unchanged,
        "preview_reported": preview_was_reported(
            final_response=result.final_response,
            expected_markers=unit.final_markers,
            broker_records=broker_evidence.records,
        ),
    }
    errors = [name for name, passed in gates.items() if not passed]
    outcome = ImportMvpAgentOutcome(
        scenario_id=unit.unit_id,
        version=unit.version,
        status="PASS" if not errors else "FAIL",
        reason="" if not errors else "failed gates: " + ", ".join(errors),
        thread_id=result.thread_id,
        gates=gates,
        command_count=len(argvs),
        final_response=result.final_response,
    )
    (evidence / "broker-evidence.json").write_text(
        json.dumps(
            broker_evidence.as_dict(include_output=False),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (evidence / "broker-reconciliation.json").write_text(
        json.dumps(asdict(reconciliation), ensure_ascii=False, sort_keys=True, indent=2)
        + "\n",
        encoding="utf-8",
    )
    (evidence / "codex-result-facts.json").write_text(
        json.dumps(result.facts_dict(), ensure_ascii=False, sort_keys=True, indent=2)
        + "\n",
        encoding="utf-8",
    )
    (evidence / "outcome.json").write_text(
        json.dumps(outcome.as_dict(), ensure_ascii=False, sort_keys=True, indent=2)
        + "\n",
        encoding="utf-8",
    )
    (root / "outcome.json").write_text(
        json.dumps(outcome.as_dict(), ensure_ascii=False, sort_keys=True, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return outcome


__all__ = [
    "ImportMvpAgentOptions",
    "ImportMvpAgentOutcome",
    "OUTCOME_CONTRACT",
    "import_mvp_developer_instructions",
    "mvp_command_set_is_closed",
    "preview_was_reported",
    "run_import_mvp_agent_unit",
]
