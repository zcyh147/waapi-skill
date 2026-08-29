"""Fresh Agent runner for the deep CLI/Console Business Adapter."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_business_agent_runner import (
    BusinessAgentOptions,
    BusinessAgentRunSpec,
    run_business_agent_unit,
)
from tests.semantic.support.codex_cli_console_business_profile import (
    OPERATION,
    OUTPUT_DIRECTORY,
    CliConsoleBusinessUnit,
)
from tests.semantic.support.codex_eval_protocol_v3 import (
    build_cli_console_business_transaction_steps,
)


OUTCOME_CONTRACT = "waapi-skill.cli-console-business-agent-outcome/v1"
CliConsoleBusinessAgentOptions = BusinessAgentOptions


@dataclass(frozen=True, slots=True)
class CliConsoleBusinessRuntime:
    fixture_path: Path
    project_path: Path
    prompt: str
    request: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class CliConsoleBusinessAgentOutcome:
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


def prepare_cli_console_business_runtime(
    unit: CliConsoleBusinessUnit,
    root: str | Path,
) -> CliConsoleBusinessRuntime:
    runtime_root = Path(root).expanduser().resolve(strict=False)
    runtime_root.mkdir(parents=True, exist_ok=False)
    project_path = runtime_root / "project" / "SemanticProject.wproj"
    project_path.parent.mkdir()
    for name in ("Originals", "GeneratedSoundBanks", "Commands", ".cache"):
        (project_path.parent / name).mkdir()
    project_path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n',
        encoding="utf-8",
    )
    fixture_path = runtime_root / "waapi-fixture.json"
    fixture_path.write_text(
        json.dumps(
            {
                "version": unit.version,
                "platform": "windows" if os.name == "nt" else "macosx",
                "process_path": str(runtime_root / "WwiseConsole"),
                "project_path": str(project_path),
                "objects": [],
                "fields": [],
                "assignments": [],
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    prompt = unit.prompt_template.format_map({"project_file": str(project_path)})
    steps = build_cli_console_business_transaction_steps(
        api=unit.operation,
        version=unit.version,
        label="tx01",
        project_file=str(project_path),
        output_directory=OUTPUT_DIRECTORY,
    )
    request = steps[-1].expected_operation_request
    assert request is not None
    return CliConsoleBusinessRuntime(
        fixture_path=fixture_path,
        project_path=project_path,
        prompt=prompt,
        request=request,
    )


def _final_response_reports_preview(
    final_response: str,
    *,
    markers: Sequence[str],
) -> bool:
    normalized = final_response.casefold()
    return all(marker.casefold() in normalized for marker in markers) and (
        "预览" in normalized or "preview" in normalized
    )


def _preview_is_closed_cli_console(
    records: Sequence[Any],
    *,
    runtime: CliConsoleBusinessRuntime,
) -> bool:
    previews = [record for record in records if record.step_name == "tx01.preview"]
    if len(previews) != 1 or not isinstance(previews[0].payload, Mapping):
        return False
    agent_result = previews[0].payload.get("agent_result")
    request = agent_result.get("request") if isinstance(agent_result, Mapping) else None
    return request == runtime.request


def _cli_console_business_run_spec(
    unit: CliConsoleBusinessUnit,
) -> BusinessAgentRunSpec:
    return BusinessAgentRunSpec(
        prepare_runtime=prepare_cli_console_business_runtime,
        build_steps=lambda runtime: build_cli_console_business_transaction_steps(
            api=unit.operation,
            version=unit.version,
            label="tx01",
            project_file=str(runtime.project_path),
            output_directory=OUTPUT_DIRECTORY,
        ),
        transaction_count=lambda _runtime: 1,
        preview_gates=lambda expected, runtime, result, evidence: {
            "preview_reported": _final_response_reports_preview(
                result.final_response,
                markers=expected.final_markers,
            ),
            "closed_cli_console_request": _preview_is_closed_cli_console(
                evidence.records,
                runtime=runtime,
            ),
        },
        outcome_factory=CliConsoleBusinessAgentOutcome,
        optional_initial_operations_discovery_operation=OPERATION,
    )


def run_cli_console_business_agent_unit(
    unit: CliConsoleBusinessUnit,
    *,
    scenario_root: Path,
    options: CliConsoleBusinessAgentOptions,
) -> CliConsoleBusinessAgentOutcome:
    return run_business_agent_unit(
        unit,
        scenario_root=scenario_root,
        options=options,
        spec=_cli_console_business_run_spec(unit),
    )


__all__ = [
    "CliConsoleBusinessAgentOptions",
    "CliConsoleBusinessAgentOutcome",
    "CliConsoleBusinessRuntime",
    "prepare_cli_console_business_runtime",
    "run_cli_console_business_agent_unit",
]
