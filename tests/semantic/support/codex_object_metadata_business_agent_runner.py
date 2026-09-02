"""Fresh Agent runner for one bound object-reference repair Preview."""

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
    build_object_metadata_business_transaction_steps,
)
from tests.semantic.support.codex_object_metadata_business_profile import (
    ObjectMetadataBusinessUnit,
)


OUTCOME_CONTRACT = "waapi-skill.object-metadata-business-agent-outcome/v1"
ObjectMetadataBusinessAgentOptions = BusinessAgentOptions


@dataclass(frozen=True, slots=True)
class ObjectMetadataBusinessRuntime:
    fixture_path: Path
    prompt: str
    request: Mapping[str, Any]
    source_id: str
    target_id: str
    field_meaning: str
    source_path: str
    target_path: str


@dataclass(frozen=True, slots=True)
class ObjectMetadataBusinessAgentOutcome:
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


def prepare_object_metadata_business_runtime(
    unit: ObjectMetadataBusinessUnit,
    root: str | Path,
) -> ObjectMetadataBusinessRuntime:
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
                "objects": [dict(unit.source), dict(unit.target)],
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
        {
            "source_path": str(unit.source["path"]),
            "target_path": str(unit.target["path"]),
            "field_meaning": unit.field_meaning,
        }
    )
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": unit.version,
        "operation": unit.operation,
        "arguments": {
            "object": {"kind": "id", "value": str(unit.source["id"])},
            "reference": unit.native_reference,
            "target": {"kind": "id", "value": str(unit.target["id"])},
        },
    }
    return ObjectMetadataBusinessRuntime(
        fixture_path=fixture_path,
        prompt=prompt,
        request=request,
        source_id=str(unit.source["id"]),
        target_id=str(unit.target["id"]),
        field_meaning=unit.field_meaning,
        source_path=str(unit.source["path"]),
        target_path=str(unit.target["path"]),
    )


def build_preview_only_metadata_steps(runtime: ObjectMetadataBusinessRuntime) -> tuple[Any, ...]:
    return build_object_metadata_business_transaction_steps(
        runtime.request,
        label="tx01",
        field_meaning=runtime.field_meaning,
        object_selector={"kind": "path", "value": runtime.source_path},
        target_selector={"kind": "path", "value": runtime.target_path},
        discover_before_target=True,
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


def _preview_uses_closed_guids(
    records: Sequence[Any],
    *,
    source_id: str,
    target_id: str,
) -> bool:
    previews = [record for record in records if record.step_name == "tx01.preview"]
    if len(previews) != 1 or not isinstance(previews[0].payload, Mapping):
        return False
    agent_result = previews[0].payload.get("agent_result")
    request = agent_result.get("request") if isinstance(agent_result, Mapping) else None
    arguments = request.get("arguments") if isinstance(request, Mapping) else None
    return bool(
        isinstance(arguments, Mapping)
        and arguments.get("object") == {"kind": "id", "value": source_id}
        and arguments.get("target") == {"kind": "id", "value": target_id}
    )


def _uses_business_meaning_and_handle(records: Sequence[Any], *, meaning: str) -> bool:
    discovered = [record for record in records if record.step_name == "tx01.discover-field"]
    declared = [record for record in records if record.step_name == "tx01.declare-field-change"]
    if len(discovered) != 1 or len(declared) != 1:
        return False
    discover_argv = discovered[0].gateway_arguments
    declare_argv = declared[0].gateway_arguments
    return bool(
        "--meaning" in discover_argv
        and meaning in discover_argv
        and "--token" not in discover_argv
        and "--field-handle" in declare_argv
        and "OutputBus" not in discover_argv
        and "OutputBus" not in declare_argv
    )


def run_object_metadata_business_agent_unit(
    unit: ObjectMetadataBusinessUnit,
    *,
    scenario_root: Path,
    options: ObjectMetadataBusinessAgentOptions,
) -> ObjectMetadataBusinessAgentOutcome:
    return run_business_agent_unit(
        unit,
        scenario_root=scenario_root,
        options=options,
        spec=BusinessAgentRunSpec(
            prepare_runtime=prepare_object_metadata_business_runtime,
            build_steps=build_preview_only_metadata_steps,
            transaction_count=lambda _runtime: 1,
            preview_gates=_object_metadata_preview_gates,
            outcome_factory=ObjectMetadataBusinessAgentOutcome,
            requires_initial_operations_discovery=False,
        ),
    )


def _object_metadata_preview_gates(
    unit: ObjectMetadataBusinessUnit,
    runtime: ObjectMetadataBusinessRuntime,
    result: Any,
    broker_evidence: Any,
) -> Mapping[str, bool]:
    return {
        "preview_reported": _final_response_reports_preview(
            result.final_response,
            markers=unit.final_markers,
        ),
        "canonical_guid_request": _preview_uses_closed_guids(
            broker_evidence.records,
            source_id=runtime.source_id,
            target_id=runtime.target_id,
        ),
        "business_meaning_and_opaque_handle": _uses_business_meaning_and_handle(
            broker_evidence.records,
            meaning=runtime.field_meaning,
        ),
    }


__all__ = [
    "ObjectMetadataBusinessAgentOptions", "ObjectMetadataBusinessAgentOutcome",
    "ObjectMetadataBusinessRuntime", "build_preview_only_metadata_steps",
    "prepare_object_metadata_business_runtime", "run_object_metadata_business_agent_unit",
]
