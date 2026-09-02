"""Fresh Agent runner for current object lifecycle Business Declarations."""

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
    build_object_lifecycle_business_transaction_steps,
)
from tests.semantic.support.codex_object_lifecycle_business_profile import (
    ObjectLifecycleBusinessUnit,
)


OUTCOME_CONTRACT = "waapi-skill.object-lifecycle-business-agent-outcome/v1"


ObjectLifecycleBusinessAgentOptions = BusinessAgentOptions


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
    return run_business_agent_unit(
        unit,
        scenario_root=scenario_root,
        options=options,
        spec=BusinessAgentRunSpec(
            prepare_runtime=prepare_object_lifecycle_business_runtime,
            build_steps=lambda runtime: build_preview_only_lifecycle_steps(
                runtime.request
            ),
            transaction_count=lambda _runtime: 1,
            preview_gates=_object_lifecycle_preview_gates,
            outcome_factory=ObjectLifecycleBusinessAgentOutcome,
            requires_initial_operations_discovery=False,
            optional_initial_operations_discovery_operation=unit.operation,
        ),
    )


def _object_lifecycle_preview_gates(
    unit: ObjectLifecycleBusinessUnit,
    runtime: ObjectLifecycleBusinessRuntime,
    result: Any,
    broker_evidence: Any,
) -> Mapping[str, bool]:
    return {
        "preview_reported": _final_response_reports_preview(
            result.final_response,
            operation=unit.operation,
            markers=unit.final_markers,
        ),
        "canonical_guid_request": _preview_uses_closed_guid(
            broker_evidence.records,
            object_id=runtime.object_id,
        ),
    }


__all__ = [
    "ObjectLifecycleBusinessAgentOptions", "ObjectLifecycleBusinessAgentOutcome",
    "ObjectLifecycleBusinessRuntime", "build_preview_only_lifecycle_steps",
    "prepare_object_lifecycle_business_runtime", "run_object_lifecycle_business_agent_unit",
]
