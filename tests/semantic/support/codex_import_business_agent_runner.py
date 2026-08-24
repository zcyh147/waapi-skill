"""Fresh Agent runner for the packaged audio.import business interface."""

from __future__ import annotations

import json
import os
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_eval_protocol_v3 import (
    build_audio_import_composer_transaction_steps,
)
from tests.semantic.support.codex_gateway_broker import CodexGatewayBroker
from tests.semantic.support.codex_harness import (
    CodexCliTask,
    CodexHarnessConfig,
    WindowsPowerShellCoreHost,
    prepare_workspace_skill_install,
    semantic_task_developer_instructions,
)
from tests.semantic.support.codex_import_business_profile import ImportBusinessUnit
from tests.semantic.support.codex_task_runner_v3 import _gateway_candidate_argvs


OUTCOME_CONTRACT = "waapi-skill.audio-import-business-agent-outcome/v1"
FIXTURE_ENV = "WAAPI_AUDIO_IMPORT_BUSINESS_FIXTURE"
REPO_ROOT = Path(__file__).resolve().parents[3]
WAAPI_SHIM_ROOT = (
    REPO_ROOT
    / "tests"
    / "semantic"
    / "data"
    / "audio-import-business"
    / "waapi-shim"
)
_REPORT_MINUS_TRANSLATION = str.maketrans(
    {
        "\N{MINUS SIGN}": "-",
        "\N{SMALL HYPHEN-MINUS}": "-",
        "\N{FULLWIDTH HYPHEN-MINUS}": "-",
    }
)


@dataclass(frozen=True, slots=True)
class ImportBusinessAgentOptions:
    skill_source: Path
    codex_binary: Path
    auth_json: Path
    model: str
    reasoning_effort: str
    service_tier: str
    timeout_seconds: float
    windows_powershell_core_host: WindowsPowerShellCoreHost | None = None


@dataclass(frozen=True, slots=True)
class ImportBusinessRuntime:
    fixture_path: Path
    prompt: str
    requests: tuple[Mapping[str, Any], ...]
    media_paths: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class ImportBusinessAgentOutcome:
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


def _business_protocol_is_exact(
    broker_evidence: Any,
    reconciliation: Any,
) -> bool:
    """Trust the Broker's dependency-aware ordering proof exactly once."""

    return bool(broker_evidence.passed and reconciliation.passed)


def _final_response_reports_preview(
    final_response: str,
    *,
    markers: Sequence[str],
) -> bool:
    """Accept a semantic prose summary or the exact machine Preview payload."""

    normalized = final_response.translate(_REPORT_MINUS_TRANSLATION).casefold()
    normalized_markers = tuple(
        marker.translate(_REPORT_MINUS_TRANSLATION).casefold()
        for marker in markers
    )
    if any(marker in normalized for marker in normalized_markers) and (
        "预览" in normalized or "preview" in normalized
    ):
        return True
    try:
        payload = json.loads(final_response)
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(payload, Mapping):
        return False
    request = payload.get("request")
    return bool(
        payload.get("operation") == "audio.import"
        and payload.get("state") == "awaiting_confirmation"
        and payload.get("executed") is False
        and isinstance(request, Mapping)
        and request.get("contract") == "waapi-skill.operation-request/v1"
        and request.get("operation") == "audio.import"
    )


def prepare_import_business_runtime(
    unit: ImportBusinessUnit,
    root: str | Path,
) -> ImportBusinessRuntime:
    runtime_root = Path(root).expanduser().resolve(strict=False)
    runtime_root.mkdir(parents=True, exist_ok=False)
    media_root = runtime_root / "media"
    media_root.mkdir()
    media_names = tuple(sorted(_media_names(unit.transactions)))
    media_paths = tuple(media_root / name for name in media_names)
    for path in media_paths:
        _write_silent_wav(path)
    media_by_name = {path.name: path for path in media_paths}
    requests = tuple(
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": unit.version,
            "operation": "audio.import",
            "arguments": _resolve_media_tokens(
                transaction["arguments"],
                media_by_name,
            ),
        }
        for transaction in unit.transactions
    )
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
                "objects": [dict(row) for row in unit.objects],
                "fields": [dict(row) for row in unit.fields],
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    prompt_values = {
        **{f"media_{path.stem}": str(path) for path in media_paths},
        **{f"path_{row['role']}": str(row["path"]) for row in unit.objects},
    }
    try:
        prompt = unit.prompt_template.format_map(prompt_values)
    except KeyError as exc:
        raise ValueError(f"audio import business prompt placeholder is unresolved: {exc}") from exc
    return ImportBusinessRuntime(
        fixture_path=fixture_path,
        prompt=prompt,
        requests=requests,
        media_paths=media_paths,
    )


def build_preview_only_business_steps(
    requests: Sequence[Mapping[str, Any]],
) -> tuple[Any, ...]:
    steps: list[Any] = []
    for index, request in enumerate(requests, start=1):
        transaction_steps = build_audio_import_composer_transaction_steps(
            request,
            label=f"tx{index:02d}",
        )
        preview_index = next(
            position
            for position, step in enumerate(transaction_steps)
            if step.subcommand == "preview-from-draft"
        )
        steps.extend(transaction_steps[: preview_index + 1])
    return tuple(steps)


def run_import_business_agent_unit(
    unit: ImportBusinessUnit,
    *,
    scenario_root: Path,
    options: ImportBusinessAgentOptions,
) -> ImportBusinessAgentOutcome:
    root = Path(scenario_root).expanduser().resolve(strict=False)
    evidence = root / "evidence"
    task_root = evidence / "codex-task"
    workspace = task_root / "agent-workspace"
    evidence.mkdir(parents=True, exist_ok=False)
    skill_install = prepare_workspace_skill_install(workspace, options.skill_source)
    runtime = prepare_import_business_runtime(unit, task_root / "runtime")
    steps = build_preview_only_business_steps(runtime.requests)
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
    preview_reported = _final_response_reports_preview(
        result.final_response,
        markers=unit.final_markers,
    )
    preview_count = sum(
        record.step_name is not None and record.step_name.endswith(".preview")
        for record in broker_evidence.records
    )
    gates = {
        "codex_exit_zero": result.exit_status == 0 and not result.timed_out,
        "fresh_thread": bool(result.thread_id),
        "broker_passed": broker_evidence.passed,
        "exact_protocol": _business_protocol_is_exact(
            broker_evidence,
            reconciliation,
        ),
        "production_skill_read": facts.skill_read
        and set(facts.skill_read_files)
        == {"SKILL.md", "references/waapi-operate.md"},
        "no_unexpected_commands": len(facts.command_records)
        == len(argvs) + len(facts.allowed_read_commands),
        "no_inline_python": not facts.inline_python_commands,
        "no_direct_waapi": not facts.direct_waapi_client_commands,
        "no_workspace_changes": result.file_change_count == 0,
        "skill_unchanged": result.skill_tree_unchanged,
        "all_previews_reported": preview_count == len(runtime.requests)
        and preview_reported,
        "no_execute": all(step.subcommand != "execute" for step in steps)
        and not any(record.gateway_arguments[:1] == ("execute",) for record in broker_evidence.records),
    }
    errors = [name for name, passed in gates.items() if not passed]
    outcome = ImportBusinessAgentOutcome(
        scenario_id=unit.unit_id,
        version=unit.version,
        status="PASS" if not errors else "FAIL",
        reason="" if not errors else "failed gates: " + ", ".join(errors),
        thread_id=result.thread_id,
        gates=gates,
        command_count=len(argvs),
        transaction_count=len(runtime.requests),
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


def _media_names(transactions: Sequence[Mapping[str, Any]]) -> set[str]:
    names: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for nested in value.values():
                visit(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                visit(nested)
        elif isinstance(value, str) and value.startswith("media://"):
            name = value.removeprefix("media://")
            if not name or "/" in name or "\\" in name:
                raise ValueError("audio import business media token is invalid")
            names.add(name)

    visit(transactions)
    return names


def _resolve_media_tokens(value: Any, media_by_name: Mapping[str, Path]) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _resolve_media_tokens(nested, media_by_name) for key, nested in value.items()}
    if isinstance(value, list):
        return [_resolve_media_tokens(nested, media_by_name) for nested in value]
    if isinstance(value, str) and value.startswith("media://"):
        return str(media_by_name[value.removeprefix("media://")])
    return value


def _write_silent_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(48000)
        stream.writeframes(b"\x00\x00" * 32)


__all__ = [
    "FIXTURE_ENV", "ImportBusinessAgentOptions", "ImportBusinessAgentOutcome",
    "ImportBusinessRuntime", "OUTCOME_CONTRACT", "build_preview_only_business_steps",
    "prepare_import_business_runtime", "run_import_business_agent_unit",
]
