"""Fresh Agent runner for current object lifecycle Business Declarations."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_eval_protocol_v3 import (
    build_object_lifecycle_business_transaction_steps,
)
from tests.semantic.support.codex_gateway_broker import CodexGatewayBroker
from tests.semantic.support.codex_harness import (
    CodexCliTask,
    CodexHarnessConfig,
    WindowsPowerShellCoreHost,
    prepare_workspace_skill_install,
    semantic_task_developer_instructions,
)
from tests.semantic.support.codex_object_lifecycle_business_profile import (
    ObjectLifecycleBusinessUnit,
)
from tests.semantic.support.codex_task_runner_v3 import _gateway_candidate_argvs


OUTCOME_CONTRACT = "waapi-skill.object-lifecycle-business-agent-outcome/v1"
FIXTURE_ENV = "WAAPI_AUDIO_IMPORT_BUSINESS_FIXTURE"
REPO_ROOT = Path(__file__).resolve().parents[3]
WAAPI_SHIM_ROOT = (
    REPO_ROOT / "tests" / "semantic" / "data" / "audio-import-business" / "waapi-shim"
)


@dataclass(frozen=True, slots=True)
class ObjectLifecycleBusinessAgentOptions:
    skill_source: Path
    codex_binary: Path
    auth_json: Path
    model: str
    reasoning_effort: str
    service_tier: str
    timeout_seconds: float
    windows_powershell_core_host: WindowsPowerShellCoreHost | None = None


@dataclass(frozen=True, slots=True)
class ObjectLifecycleBusinessRuntime:
    fixture_path: Path
    prompt: str
    request: Mapping[str, Any]
    object_id: str
    object_path: str


@dataclass(frozen=True, slots=True)
class ObjectLifecycleBusinessAgentOutcome:
    scenario_id: str
    version: str
    status: str
    reason: str
    thread_id: str
    gates: Mapping[str, bool]
    command_count: int
    transaction_count: int
    production_gateway: bool
    wwise_started: bool
    final_response: str

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def as_dict(self) -> dict[str, Any]:
        return {"contract": OUTCOME_CONTRACT, **asdict(self)}


def prepare_object_lifecycle_business_runtime(
    unit: ObjectLifecycleBusinessUnit,
    root: str | Path,
) -> ObjectLifecycleBusinessRuntime:
    runtime_root = Path(root).expanduser().resolve(strict=False)
    runtime_root.mkdir(parents=True, exist_ok=False)
    project_path = runtime_root / "project" / "SemanticProject.wproj"
    project_path.parent.mkdir()
    for name in ("Originals", "GeneratedSoundBanks", "Commands", ".cache"):
        (project_path.parent / name).mkdir()
    project_path.write_text("<?xml version=\"1.0\" encoding=\"utf-8\"?>\n", encoding="utf-8")
    fixture_path = runtime_root / "waapi-fixture.json"
    fixture_path.write_text(
        json.dumps(
            {
                "version": unit.version,
                "platform": "windows" if os.name == "nt" else "macosx",
                "process_path": str(runtime_root / "WwiseConsole"),
                "project_path": str(project_path),
                "objects": [dict(unit.object)],
                "fields": [],
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    prompt = unit.prompt_template.format_map(
        {"object_path": str(unit.object["path"]), "value": unit.value or ""}
    )
    arguments: dict[str, Any] = {
        "object": {"kind": "path", "value": str(unit.object["path"])}
    }
    if unit.value is not None:
        arguments["value"] = unit.value
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": unit.version,
        "operation": unit.operation,
        "arguments": arguments,
    }
    return ObjectLifecycleBusinessRuntime(
        fixture_path=fixture_path,
        prompt=prompt,
        request=request,
        object_id=str(unit.object["id"]),
        object_path=str(unit.object["path"]),
    )


def build_preview_only_lifecycle_steps(request: Mapping[str, Any]) -> tuple[Any, ...]:
    return build_object_lifecycle_business_transaction_steps(request, label="tx01")


def _final_response_reports_preview(
    final_response: str,
    *,
    operation: str,
    markers: Sequence[str],
) -> bool:
    normalized = final_response.casefold()
    if any(marker.casefold() in normalized for marker in markers) and (
        "预览" in normalized or "preview" in normalized
    ):
        return True
    try:
        payload = json.loads(final_response)
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(payload, Mapping):
        return False
    if isinstance(payload.get("agent_result"), Mapping):
        payload = payload["agent_result"]
    request = payload.get("request")
    return bool(
        payload.get("operation") == operation
        and payload.get("state") == "awaiting_confirmation"
        and payload.get("executed") is False
        and isinstance(request, Mapping)
        and request.get("contract") == "waapi-skill.operation-request/v1"
        and request.get("operation") == operation
    )


def _preview_uses_closed_guid(
    records: Sequence[Any],
    *,
    object_id: str,
) -> bool:
    previews = [record for record in records if record.step_name == "tx01.preview"]
    if len(previews) != 1 or not isinstance(previews[0].payload, Mapping):
        return False
    agent_result = previews[0].payload.get("agent_result")
    request = agent_result.get("request") if isinstance(agent_result, Mapping) else None
    arguments = request.get("arguments") if isinstance(request, Mapping) else None
    identity = arguments.get("object") if isinstance(arguments, Mapping) else None
    return identity == {"kind": "id", "value": object_id}


def run_object_lifecycle_business_agent_unit(
    unit: ObjectLifecycleBusinessUnit,
    *,
    scenario_root: Path,
    options: ObjectLifecycleBusinessAgentOptions,
) -> ObjectLifecycleBusinessAgentOutcome:
    root = Path(scenario_root).expanduser().resolve(strict=False)
    evidence = root / "evidence"
    task_root = evidence / "codex-task"
    workspace = task_root / "agent-workspace"
    evidence.mkdir(parents=True, exist_ok=False)
    skill_install = prepare_workspace_skill_install(workspace, options.skill_source)
    runtime = prepare_object_lifecycle_business_runtime(unit, task_root / "runtime")
    steps = build_preview_only_lifecycle_steps(runtime.request)
    runner_environment = dict(os.environ)
    runner_environment.update(
        {
            "PYTHONPATH": os.pathsep.join(
                (str(WAAPI_SHIM_ROOT), str(REPO_ROOT), str(REPO_ROOT / "skills/waapi-skill"))
            ),
            FIXTURE_ENV: str(runtime.fixture_path),
            "WWISE_VERSION": unit.version,
            "WWISE_WAAPI_HOST": "127.0.0.1",
            "WWISE_WAAPI_PORT": "31337",
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
        expected_gateway_subcommands=tuple(step.subcommand for step in steps),
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
        "preview_reported": _final_response_reports_preview(
            result.final_response,
            operation=unit.operation,
            markers=unit.final_markers,
        ),
        "canonical_guid_request": _preview_uses_closed_guid(
            broker_evidence.records,
            object_id=runtime.object_id,
        ),
        "no_execute": not any(
            record.gateway_arguments[:1] == ("execute",)
            for record in broker_evidence.records
        ),
    }
    errors = [name for name, passed in gates.items() if not passed]
    outcome = ObjectLifecycleBusinessAgentOutcome(
        scenario_id=unit.unit_id,
        version=unit.version,
        status="PASS" if not errors else "FAIL",
        reason="" if not errors else "failed gates: " + ", ".join(errors),
        thread_id=result.thread_id,
        gates=gates,
        command_count=len(argvs),
        transaction_count=1,
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
    "ObjectLifecycleBusinessAgentOptions", "ObjectLifecycleBusinessAgentOutcome",
    "ObjectLifecycleBusinessRuntime", "build_preview_only_lifecycle_steps",
    "prepare_object_lifecycle_business_runtime", "run_object_lifecycle_business_agent_unit",
]
