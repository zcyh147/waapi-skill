"""Fresh Agent runner for one Weather object.create Business Preview."""

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
    build_object_graph_business_transaction_steps,
)
from tests.semantic.support.codex_object_graph_business_profile import (
    ObjectGraphBusinessUnit,
)


OUTCOME_CONTRACT = "waapi-skill.object-graph-business-agent-outcome/v1"
ObjectGraphBusinessAgentOptions = BusinessAgentOptions


@dataclass(frozen=True, slots=True)
class ObjectGraphBusinessRuntime:
    fixture_path: Path
    prompt: str
    request: Mapping[str, Any]
    parent_path: str


@dataclass(frozen=True, slots=True)
class ObjectGraphBusinessAgentOutcome:
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


def object_graph_business_request(unit: ObjectGraphBusinessUnit) -> dict[str, Any]:
    return {
        "contract": "waapi-skill.operation-request/v1",
        "version": unit.version,
        "operation": "object.create",
        "arguments": {
            "parent": {"kind": "id", "value": str(unit.parent["id"])},
            "type": "ActorMixer",
            "name": unit.root_name,
            "children": [
                {
                    "type": "Sound",
                    "name": str(sound["name"]),
                    "properties": [
                        {"name": "IsLoopingEnabled", "value": True},
                        {"name": "IsLoopingInfinite", "value": True},
                        {"name": "Volume", "value": float(sound["volume_db"])},
                    ],
                }
                for sound in unit.sounds
            ],
        },
    }


def prepare_object_graph_business_runtime(
    unit: ObjectGraphBusinessUnit,
    root: str | Path,
) -> ObjectGraphBusinessRuntime:
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
                "objects": [dict(unit.parent)],
                "types": ["ActorMixer", "Sound"],
                "fields": [],
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    parent_path = str(unit.parent["path"])
    return ObjectGraphBusinessRuntime(
        fixture_path=fixture_path,
        prompt=unit.prompt_template.format_map({"parent_path": parent_path}),
        request=object_graph_business_request(unit),
        parent_path=parent_path,
    )


def build_preview_only_object_graph_steps(
    runtime: ObjectGraphBusinessRuntime,
) -> tuple[Any, ...]:
    return build_object_graph_business_transaction_steps(
        runtime.request,
        label="tx01",
        parent_selector={"kind": "path", "value": runtime.parent_path},
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


def _preview_matches_request(
    records: Sequence[Any],
    *,
    expected: Mapping[str, Any],
) -> bool:
    previews = [record for record in records if record.step_name == "tx01.preview"]
    if len(previews) != 1 or not isinstance(previews[0].payload, Mapping):
        return False
    agent_result = previews[0].payload.get("agent_result")
    request = agent_result.get("request") if isinstance(agent_result, Mapping) else None
    return request == expected


def _uses_only_business_graph_facts(records: Sequence[Any]) -> bool:
    declarations = [
        record.gateway_arguments
        for record in records
        if record.step_name.startswith("tx01.declare-")
    ]
    serialized = json.dumps(declarations, ensure_ascii=False)
    return bool(
        len(declarations) == 3
        and "actor-mixer" in serialized
        and serialized.count("sound-sfx") == 2
        and serialized.count("volume_db") == 2
        and serialized.count("infinite") == 2
        and all(
            token not in serialized
            for token in ("ActorMixer", "IsLoopingEnabled", "IsLoopingInfinite")
        )
    )


def run_object_graph_business_agent_unit(
    unit: ObjectGraphBusinessUnit,
    *,
    scenario_root: Path,
    options: ObjectGraphBusinessAgentOptions,
) -> ObjectGraphBusinessAgentOutcome:
    return run_business_agent_unit(
        unit,
        scenario_root=scenario_root,
        options=options,
        spec=BusinessAgentRunSpec(
            prepare_runtime=prepare_object_graph_business_runtime,
            build_steps=build_preview_only_object_graph_steps,
            transaction_count=lambda _runtime: 1,
            preview_gates=_object_graph_preview_gates,
            outcome_factory=ObjectGraphBusinessAgentOutcome,
        ),
    )


def _object_graph_preview_gates(
    unit: ObjectGraphBusinessUnit,
    runtime: ObjectGraphBusinessRuntime,
    result: Any,
    broker_evidence: Any,
) -> Mapping[str, bool]:
    return {
        "preview_reported": _final_response_reports_preview(
            result.final_response,
            markers=unit.final_markers,
        ),
        "canonical_business_request": _preview_matches_request(
            broker_evidence.records,
            expected=runtime.request,
        ),
        "business_graph_facts_only": _uses_only_business_graph_facts(
            broker_evidence.records
        ),
    }


__all__ = [
    "ObjectGraphBusinessAgentOptions", "ObjectGraphBusinessAgentOutcome",
    "ObjectGraphBusinessRuntime", "build_preview_only_object_graph_steps",
    "object_graph_business_request", "prepare_object_graph_business_runtime",
    "run_object_graph_business_agent_unit",
]
