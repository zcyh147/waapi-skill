"""Fresh Agent runner for the deep host/UI/Debug Business Adapter."""

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
from tests.semantic.support.codex_eval_protocol_v3 import (
    build_host_ui_debug_business_transaction_steps,
)
from tests.semantic.support.codex_host_ui_debug_business_profile import (
    OPERATION,
    HostUiDebugBusinessUnit,
)


OUTCOME_CONTRACT = "waapi-skill.host-ui-debug-business-agent-outcome/v1"
HostUiDebugBusinessAgentOptions = BusinessAgentOptions


@dataclass(frozen=True, slots=True)
class HostUiDebugBusinessRuntime:
    fixture_path: Path
    output_file: Path
    prompt: str
    request: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class HostUiDebugBusinessAgentOutcome:
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


def prepare_host_ui_debug_business_runtime(
    unit: HostUiDebugBusinessUnit,
    root: str | Path,
) -> HostUiDebugBusinessRuntime:
    runtime_root = Path(root).expanduser().resolve(strict=False)
    runtime_root.mkdir(parents=True, exist_ok=False)
    project_path = runtime_root / "project" / "SemanticProject.wproj"
    project_path.parent.mkdir()
    project_path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n',
        encoding="utf-8",
    )
    output_file = runtime_root / "output" / "FreshAgentTone.wav"
    output_file.parent.mkdir()
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
    prompt = unit.prompt_template.format_map({"output_file": str(output_file)})
    steps = build_host_ui_debug_business_transaction_steps(
        version=unit.version,
        label="tx01",
        output_file=str(output_file),
    )
    request = steps[-1].expected_operation_request
    assert request is not None
    return HostUiDebugBusinessRuntime(
        fixture_path=fixture_path,
        output_file=output_file,
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


def _preview_is_closed_host_plan(
    records: Sequence[Any],
    *,
    runtime: HostUiDebugBusinessRuntime,
) -> bool:
    previews = [record for record in records if record.step_name == "tx01.preview"]
    if len(previews) != 1 or not isinstance(previews[0].payload, Mapping):
        return False
    agent_result = previews[0].payload.get("agent_result")
    request = agent_result.get("request") if isinstance(agent_result, Mapping) else None
    return request == runtime.request


def _host_ui_debug_business_run_spec(
    unit: HostUiDebugBusinessUnit,
) -> BusinessAgentRunSpec:
    return BusinessAgentRunSpec(
        prepare_runtime=prepare_host_ui_debug_business_runtime,
        build_steps=lambda runtime: build_host_ui_debug_business_transaction_steps(
            version=unit.version,
            label="tx01",
            output_file=str(runtime.output_file),
        ),
        transaction_count=lambda _runtime: 1,
        preview_gates=lambda expected, runtime, result, evidence: {
            "preview_reported": _final_response_reports_preview(
                result.final_response,
                markers=expected.final_markers,
            ),
            "closed_host_plan_request": _preview_is_closed_host_plan(
                evidence.records,
                runtime=runtime,
            ),
        },
        outcome_factory=HostUiDebugBusinessAgentOutcome,
        optional_initial_operations_discovery_operation=OPERATION,
    )


def run_host_ui_debug_business_agent_unit(
    unit: HostUiDebugBusinessUnit,
    *,
    scenario_root: Path,
    options: HostUiDebugBusinessAgentOptions,
) -> HostUiDebugBusinessAgentOutcome:
    return run_business_agent_unit(
        unit,
        scenario_root=scenario_root,
        options=options,
        spec=_host_ui_debug_business_run_spec(unit),
    )


__all__ = [
    "HostUiDebugBusinessAgentOptions",
    "HostUiDebugBusinessAgentOutcome",
    "HostUiDebugBusinessRuntime",
    "prepare_host_ui_debug_business_runtime",
    "run_host_ui_debug_business_agent_unit",
]
