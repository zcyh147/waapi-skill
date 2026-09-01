"""Fresh Agent runner for the closed Switch assignment Business Adapter."""

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
    build_switch_assignment_business_transaction_steps,
)
from tests.semantic.support.codex_switch_assignment_business_profile import (
    SwitchAssignmentBusinessUnit,
)


OUTCOME_CONTRACT = "waapi-skill.switch-assignment-business-agent-outcome/v1"

SwitchAssignmentBusinessAgentOptions = BusinessAgentOptions


@dataclass(frozen=True, slots=True)
class SwitchAssignmentBusinessRuntime:
    fixture_path: Path
    prompt: str
    request: Mapping[str, Any]
    expected_ids: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class SwitchAssignmentBusinessAgentOutcome:
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


def prepare_switch_assignment_business_runtime(
    unit: SwitchAssignmentBusinessUnit,
    root: str | Path,
) -> SwitchAssignmentBusinessRuntime:
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
    objects = [dict(unit.objects[role]) for role in unit.objects]
    container = objects[0]
    container["SwitchGroupOrStateGroup"] = {
        "id": unit.objects["group"]["id"]
    }
    fixture_path = runtime_root / "waapi-fixture.json"
    fixture_path.write_text(
        json.dumps(
            {
                "version": unit.version,
                "platform": "windows" if os.name == "nt" else "macosx",
                "process_path": str(runtime_root / "WwiseConsole"),
                "project_path": str(project_path),
                "objects": objects,
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
    prompt = unit.prompt_template.format_map(
        {
            f"{role}_path": unit.objects[role]["path"]
            for role in ("switch_container", "child", "state_or_switch")
        }
    )
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": unit.version,
        "operation": unit.operation,
        "arguments": {
            role: {"kind": "path", "value": unit.objects[role]["path"]}
            for role in ("switch_container", "child", "state_or_switch")
        },
    }
    return SwitchAssignmentBusinessRuntime(
        fixture_path=fixture_path,
        prompt=prompt,
        request=request,
        expected_ids={
            role: unit.objects[role]["id"]
            for role in ("switch_container", "child", "state_or_switch")
        },
    )


def build_preview_only_switch_assignment_steps(
    request: Mapping[str, Any],
) -> tuple[Any, ...]:
    return build_switch_assignment_business_transaction_steps(
        request,
        label="tx01",
    )


def _final_response_reports_preview(
    final_response: str,
    *,
    operation: str,
    markers: Sequence[str],
) -> bool:
    del markers
    normalized = final_response.casefold()
    if "预览" in normalized or "preview" in normalized:
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
        and request.get("operation") == operation
    )


def _preview_uses_three_closed_guids(
    records: Sequence[Any],
    *,
    expected_ids: Mapping[str, str],
) -> bool:
    previews = [record for record in records if record.step_name == "tx01.preview"]
    if len(previews) != 1 or not isinstance(previews[0].payload, Mapping):
        return False
    agent_result = previews[0].payload.get("agent_result")
    request = agent_result.get("request") if isinstance(agent_result, Mapping) else None
    arguments = request.get("arguments") if isinstance(request, Mapping) else None
    return bool(
        isinstance(arguments, Mapping)
        and all(
            arguments.get(role) == {"kind": "id", "value": object_id}
            for role, object_id in expected_ids.items()
        )
    )


def run_switch_assignment_business_agent_unit(
    unit: SwitchAssignmentBusinessUnit,
    *,
    scenario_root: Path,
    options: SwitchAssignmentBusinessAgentOptions,
) -> SwitchAssignmentBusinessAgentOutcome:
    return run_business_agent_unit(
        unit,
        scenario_root=scenario_root,
        options=options,
        spec=BusinessAgentRunSpec(
            prepare_runtime=prepare_switch_assignment_business_runtime,
            build_steps=lambda runtime: build_preview_only_switch_assignment_steps(
                runtime.request
            ),
            transaction_count=lambda _runtime: 1,
            preview_gates=_switch_assignment_preview_gates,
            outcome_factory=SwitchAssignmentBusinessAgentOutcome,
        ),
    )


def _switch_assignment_preview_gates(
    unit: SwitchAssignmentBusinessUnit,
    runtime: SwitchAssignmentBusinessRuntime,
    result: Any,
    broker_evidence: Any,
) -> Mapping[str, bool]:
    return {
        "preview_reported": _final_response_reports_preview(
            result.final_response,
            operation=unit.operation,
            markers=unit.final_markers,
        ),
        "canonical_guid_request": _preview_uses_three_closed_guids(
            broker_evidence.records,
            expected_ids=runtime.expected_ids,
        ),
    }


__all__ = [
    "SwitchAssignmentBusinessAgentOptions",
    "SwitchAssignmentBusinessAgentOutcome",
    "SwitchAssignmentBusinessRuntime",
    "build_preview_only_switch_assignment_steps",
    "prepare_switch_assignment_business_runtime",
    "run_switch_assignment_business_agent_unit",
]
