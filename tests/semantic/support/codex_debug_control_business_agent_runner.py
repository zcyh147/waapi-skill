"""Fresh Agent runner for one safe named Debug Business Adapter Preview."""

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
from tests.semantic.support.codex_debug_control_business_profile import (
    DebugControlBusinessUnit,
)
from tests.semantic.support.codex_eval_protocol_v3 import (
    build_debug_control_business_transaction_steps,
)


OUTCOME_CONTRACT = "waapi-skill.debug-control-business-agent-outcome/v1"
DebugControlBusinessAgentOptions = BusinessAgentOptions


@dataclass(frozen=True, slots=True)
class DebugControlBusinessRuntime:
    fixture_path: Path
    prompt: str
    request: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class DebugControlBusinessAgentOutcome:
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


def prepare_debug_control_business_runtime(
    unit: DebugControlBusinessUnit,
    root: str | Path,
) -> DebugControlBusinessRuntime:
    runtime_root = Path(root).expanduser().resolve(strict=False)
    runtime_root.mkdir(parents=True, exist_ok=False)
    project_path = runtime_root / "project" / "SemanticProject.wproj"
    project_path.parent.mkdir()
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
    steps = build_debug_control_business_transaction_steps(
        version=unit.version,
        label="tx01",
        enabled=True,
    )
    request = steps[-1].expected_operation_request
    assert isinstance(request, Mapping)
    return DebugControlBusinessRuntime(
        fixture_path=fixture_path,
        prompt=unit.prompt_template,
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


def _preview_is_closed_debug_intent(
    records: Sequence[Any],
    *,
    runtime: DebugControlBusinessRuntime,
) -> bool:
    previews = [record for record in records if record.step_name == "tx01.preview"]
    if len(previews) != 1 or not isinstance(previews[0].payload, Mapping):
        return False
    agent_result = previews[0].payload.get("agent_result")
    request = agent_result.get("request") if isinstance(agent_result, Mapping) else None
    return request == runtime.request


def _debug_control_business_run_spec(
    unit: DebugControlBusinessUnit,
) -> BusinessAgentRunSpec:
    return BusinessAgentRunSpec(
        prepare_runtime=prepare_debug_control_business_runtime,
        build_steps=lambda _runtime: build_debug_control_business_transaction_steps(
            version=unit.version,
            label="tx01",
            enabled=True,
        ),
        transaction_count=lambda _runtime: 1,
        preview_gates=lambda expected, runtime, result, evidence: {
            "preview_reported": _final_response_reports_preview(
                result.final_response,
                markers=expected.final_markers,
            ),
            "closed_debug_intent": _preview_is_closed_debug_intent(
                evidence.records,
                runtime=runtime,
            ),
        },
        outcome_factory=DebugControlBusinessAgentOutcome,
        optional_initial_operations_discovery_operation=unit.operation,
    )


def run_debug_control_business_agent_unit(
    unit: DebugControlBusinessUnit,
    *,
    scenario_root: Path,
    options: DebugControlBusinessAgentOptions,
) -> DebugControlBusinessAgentOutcome:
    return run_business_agent_unit(
        unit,
        scenario_root=scenario_root,
        options=options,
        spec=_debug_control_business_run_spec(unit),
    )


__all__ = [
    "DebugControlBusinessAgentOptions",
    "DebugControlBusinessAgentOutcome",
    "DebugControlBusinessRuntime",
    "prepare_debug_control_business_runtime",
    "run_debug_control_business_agent_unit",
]
