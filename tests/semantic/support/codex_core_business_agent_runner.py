"""Fresh Agent runner for the generic Core Business Adapter."""

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
from tests.semantic.support.codex_core_business_profile import CoreBusinessUnit
from tests.semantic.support.codex_eval_protocol_v3 import (
    build_core_business_transaction_steps,
)


OUTCOME_CONTRACT = "waapi-skill.core-business-agent-outcome/v1"
CoreBusinessAgentOptions = BusinessAgentOptions


@dataclass(frozen=True, slots=True)
class CoreBusinessRuntime:
    fixture_path: Path
    prompt: str
    request: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class CoreBusinessAgentOutcome:
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


def prepare_core_business_runtime(
    unit: CoreBusinessUnit,
    root: str | Path,
) -> CoreBusinessRuntime:
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
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": unit.version,
        "operation": "waapi.call",
        "arguments": {
            "api": unit.operation,
            "args": {"autoCheckOutToSourceControl": False},
            "options": {},
        },
    }
    return CoreBusinessRuntime(
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


def _preview_is_closed_core_call(records: Sequence[Any]) -> bool:
    previews = [record for record in records if record.step_name == "tx01.preview"]
    if len(previews) != 1 or not isinstance(previews[0].payload, Mapping):
        return False
    agent_result = previews[0].payload.get("agent_result")
    request = agent_result.get("request") if isinstance(agent_result, Mapping) else None
    return bool(
        isinstance(request, Mapping)
        and request.get("operation") == "waapi.call"
        and request.get("arguments", {}).get("api")
        == "ak.wwise.core.project.save"
    )


def _core_business_run_spec(unit: CoreBusinessUnit) -> BusinessAgentRunSpec:
    return BusinessAgentRunSpec(
        prepare_runtime=prepare_core_business_runtime,
        build_steps=lambda runtime: build_core_business_transaction_steps(
            api=unit.operation,
            version=unit.version,
            label="tx01",
        ),
        transaction_count=lambda _runtime: 1,
        preview_gates=lambda expected, _runtime, result, evidence: {
            "preview_reported": _final_response_reports_preview(
                result.final_response,
                markers=expected.final_markers,
            ),
            "closed_core_request": _preview_is_closed_core_call(
                evidence.records
            ),
        },
        outcome_factory=CoreBusinessAgentOutcome,
        optional_initial_operations_discovery_operation=unit.operation,
    )


def run_core_business_agent_unit(
    unit: CoreBusinessUnit,
    *,
    scenario_root: Path,
    options: CoreBusinessAgentOptions,
) -> CoreBusinessAgentOutcome:
    return run_business_agent_unit(
        unit,
        scenario_root=scenario_root,
        options=options,
        spec=_core_business_run_spec(unit),
    )


__all__ = [
    "CoreBusinessAgentOptions",
    "CoreBusinessAgentOutcome",
    "CoreBusinessRuntime",
    "prepare_core_business_runtime",
    "run_core_business_agent_unit",
]
