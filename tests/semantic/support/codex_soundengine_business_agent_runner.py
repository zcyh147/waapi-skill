"""Fresh Agent runner for SoundEngine parameter-closure Previews."""

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
    build_soundengine_business_transaction_steps,
)
from tests.semantic.support.codex_soundengine_business_profile import (
    EVENT_ID,
    EVENT_NAME,
    GAME_OBJECT_NAME,
    LISTENER_HANDLE,
    LISTENER_ID,
    MONITOR_MESSAGE,
    SoundEngineBusinessUnit,
)
from wwise_waapi.canonical import canonical_json_bytes, canonical_sha256
from wwise_waapi.runtime_game_object_handles import (
    RuntimeGameObjectContext,
    RuntimeGameObjectHandleRecord,
)


OUTCOME_CONTRACT = "waapi-skill.soundengine-business-agent-outcome/v1"
SoundEngineBusinessAgentOptions = BusinessAgentOptions


@dataclass(frozen=True, slots=True)
class SoundEngineBusinessRuntime:
    fixture_path: Path
    project_path: Path
    unit_id: str
    prompt: str
    request: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class SoundEngineBusinessAgentOutcome:
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


def prepare_soundengine_business_runtime(
    unit: SoundEngineBusinessUnit,
    root: str | Path,
) -> SoundEngineBusinessRuntime:
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
    objects = (
        [
            {
                "id": EVENT_ID,
                "name": EVENT_NAME,
                "type": "Event",
                "path": rf"\Events\Default Work Unit\{EVENT_NAME}",
            }
        ]
        if unit.operation == "ak.soundengine.executeActionOnEvent"
        else []
    )
    fixture_path.write_text(
        json.dumps(
            {
                "version": unit.version,
                "platform": "windows" if os.name == "nt" else "macosx",
                "process_path": str(runtime_root / "WwiseAuthoring"),
                "project_path": str(project_path),
                "is_command_line": False,
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
    steps = build_soundengine_business_transaction_steps(
        version=unit.version,
        label="tx01",
        operation=unit.operation,
        monitor_message=MONITOR_MESSAGE,
        game_object_name=GAME_OBJECT_NAME,
        event_id=EVENT_ID,
        event_name=EVENT_NAME,
        listener_handle=LISTENER_HANDLE,
        listener_id=LISTENER_ID,
    )
    request = steps[-1].expected_operation_request
    if request is None:
        request = {
            "contract": "waapi-skill.operation-request/v1",
            "version": unit.version,
            "operation": "waapi.call",
            "arguments": {
                "api": unit.operation,
                "args": {"name": GAME_OBJECT_NAME},
                "options": {},
            },
        }
    return SoundEngineBusinessRuntime(
        fixture_path=fixture_path,
        project_path=project_path,
        unit_id=unit.unit_id,
        prompt=unit.prompt_template,
        request=request,
    )


def prepare_soundengine_business_broker_state(
    runtime: SoundEngineBusinessRuntime,
    state_dir: Path,
) -> None:
    if runtime.unit_id != "SOUND22-LISTENER-PREVIEW":
        return
    context = RuntimeGameObjectContext(
        endpoint_url="ws://127.0.0.1:31337/waapi",
        project_id="{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
        project_path=str(runtime.project_path),
        wwise_version="2022.1",
        wwise_build="v2022.1.0.1",
    )
    binding = {
        "game_object_id": LISTENER_ID,
        "game_object_name": "Seeded Fresh Listener",
        "context": context.binding_dict(),
        "source_transaction_id": "fixture-soundengine-listener",
        "source_artifact_hash": "a" * 64,
    }
    record = RuntimeGameObjectHandleRecord(
        handle=LISTENER_HANDLE,
        game_object_id=LISTENER_ID,
        game_object_name="Seeded Fresh Listener",
        context=context,
        source_transaction_id="fixture-soundengine-listener",
        source_artifact_hash="a" * 64,
        binding_digest=canonical_sha256(binding),
    )
    records = state_dir / "soundengine-game-object-handles-v1" / "records"
    records.mkdir(parents=True, exist_ok=False)
    (records / f"{LISTENER_HANDLE}.json").write_bytes(
        canonical_json_bytes(record.as_dict())
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


def _preview_is_closed_soundengine(
    records: Sequence[Any],
    *,
    runtime: SoundEngineBusinessRuntime,
) -> bool:
    previews = [record for record in records if record.step_name == "tx01.preview"]
    if len(previews) != 1 or not isinstance(previews[0].payload, Mapping):
        return False
    agent_result = previews[0].payload.get("agent_result")
    request = agent_result.get("request") if isinstance(agent_result, Mapping) else None
    if not isinstance(request, Mapping) or request.get("operation") != "waapi.call":
        return False
    arguments = request.get("arguments")
    expected = runtime.request.get("arguments")
    if not isinstance(arguments, Mapping) or not isinstance(expected, Mapping):
        return False
    if arguments.get("api") != expected.get("api") or arguments.get("options") != {}:
        return False
    if runtime.unit_id == "SOUND22-GAME-OBJECT-PREVIEW":
        args = arguments.get("args")
        return bool(
            isinstance(args, Mapping)
            and args.get("name") == GAME_OBJECT_NAME
            and isinstance(args.get("gameObject"), int)
            and not isinstance(args.get("gameObject"), bool)
        )
    return arguments == expected


def _build_soundengine_steps(
    unit: SoundEngineBusinessUnit,
) -> Sequence[Any]:
    return build_soundengine_business_transaction_steps(
        version=unit.version,
        label="tx01",
        operation=unit.operation,
        monitor_message=MONITOR_MESSAGE,
        game_object_name=GAME_OBJECT_NAME,
        event_id=EVENT_ID,
        event_name=EVENT_NAME,
        listener_handle=LISTENER_HANDLE,
        listener_id=LISTENER_ID,
    )


def _soundengine_business_run_spec(
    unit: SoundEngineBusinessUnit,
) -> BusinessAgentRunSpec:
    return BusinessAgentRunSpec(
        prepare_runtime=prepare_soundengine_business_runtime,
        build_steps=lambda _runtime: _build_soundengine_steps(unit),
        transaction_count=lambda _runtime: 1,
        preview_gates=lambda expected, _runtime, result, evidence: {
            "preview_reported": _final_response_reports_preview(
                result.final_response,
                markers=expected.final_markers,
            ),
            "closed_soundengine_request": _preview_is_closed_soundengine(
                evidence.records,
                runtime=_runtime,
            ),
        },
        outcome_factory=SoundEngineBusinessAgentOutcome,
        optional_initial_operations_discovery_operation=unit.operation,
        prepare_broker_state=prepare_soundengine_business_broker_state,
    )


def run_soundengine_business_agent_unit(
    unit: SoundEngineBusinessUnit,
    *,
    scenario_root: Path,
    options: SoundEngineBusinessAgentOptions,
) -> SoundEngineBusinessAgentOutcome:
    return run_business_agent_unit(
        unit,
        scenario_root=scenario_root,
        options=options,
        spec=_soundengine_business_run_spec(unit),
    )


__all__ = [
    "SoundEngineBusinessAgentOptions",
    "SoundEngineBusinessAgentOutcome",
    "SoundEngineBusinessRuntime",
    "prepare_soundengine_business_runtime",
    "prepare_soundengine_business_broker_state",
    "run_soundengine_business_agent_unit",
]
