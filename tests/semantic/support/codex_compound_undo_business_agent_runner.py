"""Fresh Agent runner for one checked-child compound Undo Preview."""

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
from tests.semantic.support.codex_compound_undo_business_profile import (
    CompoundUndoBusinessUnit,
)
from tests.semantic.support.codex_eval_protocol_v3 import (
    CompoundUndoChildExpectation,
    build_compound_undo_business_transaction_steps,
)


OUTCOME_CONTRACT = "waapi-skill.compound-undo-business-agent-outcome/v1"
CompoundUndoBusinessAgentOptions = BusinessAgentOptions


@dataclass(frozen=True, slots=True)
class CompoundUndoBusinessRuntime:
    fixture_path: Path
    prompt: str
    children: tuple[CompoundUndoChildExpectation, ...]
    display_name: str
    object_id: str


@dataclass(frozen=True, slots=True)
class CompoundUndoBusinessAgentOutcome:
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


def prepare_compound_undo_business_runtime(
    unit: CompoundUndoBusinessUnit,
    root: str | Path,
) -> CompoundUndoBusinessRuntime:
    runtime_root = Path(root).expanduser().resolve(strict=False)
    runtime_root.mkdir(parents=True, exist_ok=False)
    project_path = runtime_root / "project" / "SemanticProject.wproj"
    project_path.parent.mkdir()
    for name in ("Originals", "GeneratedSoundBanks", "Commands", ".cache"):
        (project_path.parent / name).mkdir()
    project_path.write_text(
        "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n",
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
    object_id = str(unit.object["id"])
    object_path = str(unit.object["path"])
    children = compound_undo_business_child_expectations(unit)
    return CompoundUndoBusinessRuntime(
        fixture_path=fixture_path,
        prompt=unit.prompt_template.format_map(
            {
                "object_path": object_path,
                "notes_value": unit.notes_value,
                "name_value": unit.name_value,
                "display_name": unit.display_name,
            }
        ),
        children=children,
        display_name=unit.display_name,
        object_id=object_id,
    )


def compound_undo_business_child_expectations(
    unit: CompoundUndoBusinessUnit,
) -> tuple[CompoundUndoChildExpectation, ...]:
    """Build the one shared runner and campaign oracle for both child Drafts."""

    object_id = str(unit.object["id"])
    object_path = str(unit.object["path"])
    requests = (
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": unit.version,
            "operation": "object.setNotes",
            "arguments": {
                "object": {"kind": "id", "value": object_id},
                "value": unit.notes_value,
            },
        },
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": unit.version,
            "operation": "object.setName",
            "arguments": {
                "object": {"kind": "id", "value": object_id},
                "value": unit.name_value,
            },
        },
    )
    return tuple(
        CompoundUndoChildExpectation(
            request=request,
            selector={"kind": "path", "value": object_path},
        )
        for request in requests
    )


def build_preview_only_compound_undo_steps(
    runtime: CompoundUndoBusinessRuntime,
) -> tuple[Any, ...]:
    return build_compound_undo_business_transaction_steps(
        runtime.children,
        display_name=runtime.display_name,
        label="tx03",
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


def _preview_is_one_closed_compound_request(
    records: Sequence[Any],
    *,
    object_id: str,
) -> bool:
    previews = [record for record in records if record.step_name == "tx03.preview"]
    if len(previews) != 1 or not isinstance(previews[0].payload, Mapping):
        return False
    agent_result = previews[0].payload.get("agent_result")
    request = agent_result.get("request") if isinstance(agent_result, Mapping) else None
    arguments = request.get("arguments") if isinstance(request, Mapping) else None
    calls = arguments.get("calls") if isinstance(arguments, Mapping) else None
    if (
        request.get("operation") != "waapi.undoGroup"
        if isinstance(request, Mapping)
        else True
    ) or not isinstance(calls, list) or len(calls) != 2:
        return False
    child_requests = [
        row.get("request") if isinstance(row, Mapping) else None for row in calls
    ]
    return [
        child.get("operation") if isinstance(child, Mapping) else None
        for child in child_requests
    ] == ["object.setNotes", "object.setName"] and all(
        isinstance(child, Mapping)
        and isinstance(child.get("arguments"), Mapping)
        and child["arguments"].get("object")
        == {"kind": "id", "value": object_id}
        for child in child_requests
    )


def run_compound_undo_business_agent_unit(
    unit: CompoundUndoBusinessUnit,
    *,
    scenario_root: Path,
    options: CompoundUndoBusinessAgentOptions,
) -> CompoundUndoBusinessAgentOutcome:
    return run_business_agent_unit(
        unit,
        scenario_root=scenario_root,
        options=options,
        spec=_compound_undo_business_run_spec(),
    )


def _compound_undo_business_run_spec() -> BusinessAgentRunSpec:
    return BusinessAgentRunSpec(
        prepare_runtime=prepare_compound_undo_business_runtime,
        build_steps=build_preview_only_compound_undo_steps,
        transaction_count=lambda _runtime: 1,
        preview_gates=_compound_undo_preview_gates,
        outcome_factory=CompoundUndoBusinessAgentOutcome,
        optional_initial_operations_discovery_operation="waapi.undoGroup",
        allow_compound_checked_child_handoff=True,
    )


def _compound_undo_preview_gates(
    unit: CompoundUndoBusinessUnit,
    runtime: CompoundUndoBusinessRuntime,
    result: Any,
    broker_evidence: Any,
) -> Mapping[str, bool]:
    return {
        "preview_reported": _final_response_reports_preview(
            result.final_response,
            markers=unit.final_markers,
        ),
        "one_compound_preview": _preview_is_one_closed_compound_request(
            broker_evidence.records,
            object_id=runtime.object_id,
        ),
        "children_checked_without_child_previews": all(
            record.step_name not in {"tx01.preview", "tx02.preview"}
            for record in broker_evidence.records
        ),
    }


__all__ = [
    "CompoundUndoBusinessAgentOptions",
    "CompoundUndoBusinessAgentOutcome",
    "CompoundUndoBusinessRuntime",
    "build_preview_only_compound_undo_steps",
    "compound_undo_business_child_expectations",
    "prepare_compound_undo_business_runtime",
    "run_compound_undo_business_agent_unit",
]
