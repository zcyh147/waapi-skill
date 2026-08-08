"""Closed real-Wwise runtime for the interactive-weather integration workflow.

The evaluated Codex task sees only the packaged gateway protocol.  This module
owns fixture setup, live metadata closure, hidden snapshots, transaction
checkpoints, and cleanup for the reviewed 2022.1/2025.1 weather workflow.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import stat
import struct
import wave
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from tests.semantic.support.codex_eval_protocol_v3 import (
    V3GatewayProtocol,
    build_transaction_protocol,
    metadata_candidate_limit,
)
from tests.semantic.support.codex_gateway_broker import (
    ExpectedGatewayStep,
    GatewayDerivedReferenceActivationAllowance,
    MetadataBoundJsonArgument,
    MetadataQueryArgument,
    MetadataTokenProjection,
    SemanticJsonArgument,
    project_required_metadata_tokens,
)
from tests.semantic.support.codex_filesystem_security import path_is_link_or_reparse
from tests.semantic.support.codex_integration_paths_v2 import (
    IntegrationOriginalPathError,
    localize_copied_original_path,
)
from tests.semantic.support.codex_version_layout_v3 import (
    get_codex_version_layout_v3,
)
from tests.semantic.support.codex_workflow_business_plan_v3 import (
    WorkflowBusinessPlanSections,
    compile_workflow_business_plan_sections,
)
from wwise_waapi.metadata_discovery import (
    discover_metadata,
)


WEATHER_WORKFLOW_ID = "interactive_weather_build"
OPERATION_REQUEST_CONTRACT = "waapi-skill.operation-request/v1"
EVENTS_DWU = r"\Events\Default Work Unit"
RAIN_PARAMETER_PATH = r"\Game Parameters\Ambience\Rain_Intensity"
SOUND_TOKENS = (
    "IsLoopingEnabled",
    "IsLoopingInfinite",
    "IgnoreParentMaxSoundInstance",
    "UseMaxSoundPerInstance",
    "MaxSoundPerInstance",
    "Volume",
    "OutputBus",
)
ACTION_TOKENS = ("FadeTime", "Delay")
RTPC_TOKENS = ("Volume",)
SOUND_METADATA_QUERIES = (
    "looping enabled",
    "looping infinite",
    "ignore parent playback limit",
    "sound instance limit enabled",
    "maximum sound instances per object",
    "volume",
    "output bus routing",
)
ACTION_METADATA_QUERIES = ("fade time", "delay")
RTPC_METADATA_QUERIES = ("volume",)
RTPC_READ_LIMIT = 128
RTPC_POINTS = (
    MappingProxyType({"x": 0.0, "y": -48.0, "shape": "Linear"}),
    MappingProxyType({"x": 50.0, "y": -12.0, "shape": "Linear"}),
    MappingProxyType({"x": 100.0, "y": 0.0, "shape": "Linear"}),
)


class IntegrationWeatherRuntimeError(RuntimeError):
    """The weather workflow could not produce trustworthy evidence."""


DirectCall = Callable[[str, Mapping[str, Any], Mapping[str, Any]], Any]


@dataclass(frozen=True, slots=True)
class WeatherTarget:
    key: str
    name: str
    logical_path: str
    event_path: str
    source_path: Path
    volume: float
    looping: bool
    instance_limit: int
    fade_time: float
    delay: float


@dataclass(frozen=True, slots=True)
class WorkflowVerification:
    workflow_id: str
    phase: str
    passed: bool
    failures: tuple[str, ...]
    evidence: Mapping[str, Any]

    def assert_passed(self) -> None:
        if not self.passed:
            raise IntegrationWeatherRuntimeError(
                f"{self.phase} verification failed: {list(self.failures)}"
            )


@dataclass(frozen=True, slots=True)
class PreparedWeatherWorkflow:
    workflow_id: str
    prompt: str
    visible_values: Mapping[str, str]
    prompt_sources: Mapping[str, Any]
    protocol: V3GatewayProtocol
    typed_sections: WorkflowBusinessPlanSections
    required_reference: str
    expected_dispatches: tuple[tuple[str, int], ...]
    snapshot: Callable[[], Mapping[str, Any]]
    observe_payload: Callable[[ExpectedGatewayStep, Mapping[str, Any]], None]
    verify_turn: Callable[[int, Any], WorkflowVerification]
    verify_final: Callable[[Mapping[str, Any] | None, Any], WorkflowVerification]
    cleanup_success: Callable[[], Mapping[str, Any]]


def prepare_weather_workflow(
    scenario: Any,
    *,
    version: str,
    scenario_root: Path,
    owned_root: Path,
    sandbox_project_root: Path,
    direct: DirectCall,
) -> PreparedWeatherWorkflow:
    """Materialize and seal the five-Sound weather workflow."""

    workflow_id = str(
        getattr(
            scenario,
            "workflow_id",
            getattr(scenario, "scenario_family", getattr(scenario, "id", "")),
        )
    )
    if workflow_id != WEATHER_WORKFLOW_ID:
        raise IntegrationWeatherRuntimeError(
            f"weather runtime received another workflow: {workflow_id!r}"
        )
    if version not in {"2022.1", "2025.1"}:
        raise IntegrationWeatherRuntimeError(
            f"weather runtime does not support Wwise {version}"
        )
    layout = get_codex_version_layout_v3(version)
    root = Path(scenario_root).resolve(strict=True)
    owned = Path(owned_root).resolve(strict=True)
    if owned != (root / "owned").resolve(strict=True):
        raise IntegrationWeatherRuntimeError(
            "weather owned root differs from the scenario authority"
        )
    sandbox_input = Path(sandbox_project_root)
    try:
        sandbox_metadata = sandbox_input.lstat()
        sandbox = sandbox_input.resolve(strict=True)
    except OSError as exc:
        raise IntegrationWeatherRuntimeError(
            "weather sandbox project root is unavailable"
        ) from exc
    if (
        path_is_link_or_reparse(sandbox_input, metadata=sandbox_metadata)
        or not stat.S_ISDIR(sandbox_metadata.st_mode)
        or sandbox == owned
        or owned not in sandbox.parents
    ):
        raise IntegrationWeatherRuntimeError(
            "weather sandbox project root is outside the scenario authority"
        )

    source_root = owned / "weather" / "sources"
    source_root.mkdir(parents=True, exist_ok=False)
    weather_root = f"{layout.containers_dwu}\\IntegrationLab"
    weather_bus = f"{layout.busses_dwu}\\Weather_Bus"
    event_root = f"{EVENTS_DWU}\\Integration_Weather"
    _require_exact_absence(direct, weather_root)
    _require_exact_absence(direct, weather_bus)
    _require_exact_absence(direct, event_root)
    parameter = _read_exact(
        direct,
        RAIN_PARAMETER_PATH,
        ("id", "name", "type", "path"),
    )
    if _type_token(parameter.get("type")) != "gameparameter":
        raise IntegrationWeatherRuntimeError(
            f"{RAIN_PARAMETER_PATH} is not a GameParameter"
        )

    created_ids = (
        _create_object(
            direct,
            parent=layout.containers_dwu,
            object_type="ActorMixer",
            name="IntegrationLab",
        ),
        _create_object(
            direct,
            parent=layout.busses_dwu,
            object_type="Bus",
            name="Weather_Bus",
        ),
        _create_object(
            direct,
            parent=EVENTS_DWU,
            object_type="Folder",
            name="Integration_Weather",
        ),
    )

    target_specs = (
        (
            "rain_bed",
            "Rain_Bed",
            r"<Actor-Mixer>Weather_Interactive\<Actor-Mixer>Rain\<Sound>Rain_Bed",
            -4.0,
            True,
            2,
            0.25,
            0.0,
            263,
            613,
        ),
        (
            "wind_bed",
            "Wind_Bed",
            r"<Actor-Mixer>Weather_Interactive\<Actor-Mixer>Wind\<Sound>Wind_Bed",
            -6.0,
            True,
            2,
            0.4,
            0.1,
            337,
            677,
        ),
        (
            "thunder_near",
            "Thunder_Near",
            r"<Actor-Mixer>Weather_Interactive\<Random Container>Thunder\<Sound>Thunder_Near",
            -2.0,
            True,
            1,
            0.05,
            0.0,
            421,
            733,
        ),
        (
            "thunder_mid",
            "Thunder_Mid",
            r"<Actor-Mixer>Weather_Interactive\<Random Container>Thunder\<Sound>Thunder_Mid",
            -8.0,
            True,
            1,
            0.12,
            0.08,
            487,
            797,
        ),
        (
            "thunder_far",
            "Thunder_Far",
            r"<Actor-Mixer>Weather_Interactive\<Random Container>Thunder\<Sound>Thunder_Far",
            -14.0,
            True,
            1,
            0.25,
            0.16,
            557,
            863,
        ),
    )
    targets: list[WeatherTarget] = []
    for (
        key,
        name,
        typed_relative,
        volume,
        looping,
        instance_limit,
        fade_time,
        delay,
        frequency,
        duration,
    ) in target_specs:
        source_path = source_root / f"{key}.wav"
        _write_wav(
            source_path,
            frequency_hz=frequency,
            duration_ms=duration,
        )
        logical_relative = _strip_typed_segments(typed_relative)
        targets.append(
            WeatherTarget(
                key=key,
                name=name,
                logical_path=f"{weather_root}\\{logical_relative}",
                event_path=f"{event_root}\\Play_{name}",
                source_path=source_path,
                volume=volume,
                looping=looping,
                instance_limit=instance_limit,
                fade_time=fade_time,
                delay=delay,
            )
        )

    sound_metadata, _ = _discover(
        direct,
        object_type="Sound",
        queries=SOUND_METADATA_QUERIES,
        required_tokens=SOUND_TOKENS,
    )
    sound_dependency_properties = _metadata_dependency_properties(
        sound_metadata,
        selected_tokens=SOUND_TOKENS,
    )
    selected_sound_tokens = {token.casefold() for token in SOUND_TOKENS}
    sound_required_tokens = (
        *SOUND_TOKENS,
        *(
            str(item["name"])
            for item in sound_dependency_properties
            if str(item["name"]).casefold() not in selected_sound_tokens
        ),
    )
    sound_projection = tuple(
        project_required_metadata_tokens(
            sound_metadata,
            object_type="Sound",
            required_tokens=sound_required_tokens,
        )
    )
    action_metadata, action_projection = _discover(
        direct,
        object_type="Action",
        queries=ACTION_METADATA_QUERIES,
        required_tokens=ACTION_TOKENS,
    )
    # The first transaction's live Sound discovery already proves the exact
    # Volume token.  Reuse that evidence for the hidden plan record instead of
    # teaching the evaluated Agent to repeat the same discovery before RTPC.
    rtpc_metadata = sound_metadata

    import_request = _weather_import_request(
        version,
        targets=targets,
        weather_root=weather_root,
        weather_bus=weather_bus,
        dependency_properties=sound_dependency_properties,
    )
    sound_activation_allowances = (
        _gateway_derived_reference_activation_allowances(
            sound_metadata,
            selected_tokens=SOUND_TOKENS,
            expected_request=import_request,
        )
    )
    action_request = _weather_action_request(version, targets=targets)
    rtpc_request = _weather_rtpc_request(
        version,
        target=targets[0],
        control_input=RAIN_PARAMETER_PATH,
    )
    protocol = _build_metadata_workflow_protocol(
        (import_request, action_request, rtpc_request),
        metadata=(
            (
                "Sound",
                SOUND_METADATA_QUERIES,
                sound_required_tokens,
                sound_projection,
                "audio_import_v1",
            ),
            (
                "Action",
                ACTION_METADATA_QUERIES,
                ACTION_TOKENS,
                action_projection,
                "object_set_v1",
            ),
            None,
        ),
        gateway_derived_reference_activations=(
            sound_activation_allowances,
            (),
            (),
        ),
    )
    visible_values = MappingProxyType(
        {
            "weather_source_directory": str(source_root),
            "weather_root_path": weather_root,
            "weather_event_root_path": event_root,
            "weather_game_parameter_path": RAIN_PARAMETER_PATH,
            "weather_bus_path": weather_bus,
        }
    )
    prompt = scenario.render_prompt(visible_values)
    if not isinstance(prompt, str) or not prompt.strip():
        raise IntegrationWeatherRuntimeError("weather prompt did not render")

    state = _WeatherState(
        workflow_id=workflow_id,
        version=version,
        direct=direct,
        weather_root=weather_root,
        weather_bus=weather_bus,
        event_root=event_root,
        parameter_path=RAIN_PARAMETER_PATH,
        containers=_weather_container_specs(weather_root),
        targets=tuple(targets),
        created_ids=created_ids,
        source_root=source_root,
        sandbox_root=sandbox,
        source_proofs=MappingProxyType(
            {
                target.key: _file_proof(target.source_path)
                for target in targets
            }
        ),
    )
    before = state.snapshot()
    if any(before["targets"][target.key]["object"] is not None for target in targets):
        raise IntegrationWeatherRuntimeError(
            "weather target unexpectedly exists before the first preview"
        )

    typed_sections = compile_workflow_business_plan_sections(
        workflow_id=workflow_id,
        transactions=_weather_plan_transactions(),
        workflow_steps=_workflow_plan_steps(
            protocol,
            transaction_phases=(
                "import_weather_assets",
                "configure_event_actions",
                "bind_rain_intensity_rtpc",
            ),
        ),
        diagnostic_evidence=(),
        live_bindings={
            "version": version,
            "weather_root": before["weather_root"],
            "event_root": before["event_root"],
            "weather_bus": before["weather_bus"],
            "rain_parameter": before["rain_parameter"],
            "source_files": before["source_files"],
            "metadata": {
                "sound": _metadata_digest(sound_metadata),
                "action": _metadata_digest(action_metadata),
                "rtpc": _metadata_digest(rtpc_metadata),
            },
        },
        transaction_expectations=(
            {
                "transaction_id": "tx01",
                "expectation": {
                    "five_sounds": [target.logical_path for target in targets],
                    "five_play_events": [target.event_path for target in targets],
                    "media_sources": "one unique AudioFileSource per Sound",
                    "sound_properties_and_bus": True,
                },
            },
            {
                "transaction_id": "tx02",
                "expectation": {
                    "action_properties": {
                        target.event_path: {
                            "FadeTime": target.fade_time,
                            "Delay": target.delay,
                        }
                        for target in targets
                    },
                    "action_type_and_target_preserved": True,
                },
            },
            {
                "transaction_id": "tx03",
                "expectation": {
                    "object": targets[0].logical_path,
                    "property": "Volume",
                    "control_input": RAIN_PARAMETER_PATH,
                    "points": [dict(point) for point in RTPC_POINTS],
                },
            },
        ),
    )

    def observe_payload(
        step: ExpectedGatewayStep,
        _payload: Mapping[str, Any],
    ) -> None:
        if step.name == "tx01.verify":
            state.verify_import().assert_passed()
            state.verify_protected(before).assert_passed()
        elif step.name == "tx02.verify":
            state.verify_actions().assert_passed()
            state.verify_protected(before).assert_passed()

    def verify_turn(turn_index: int, _result: Any) -> WorkflowVerification:
        if turn_index == 1:
            return _verification_from_snapshot(
                workflow_id,
                "turn_01_preview_only",
                before,
                state.snapshot(),
            )
        return WorkflowVerification(
            workflow_id,
            f"turn_{turn_index:02d}",
            True,
            (),
            MappingProxyType({"checked": True}),
        )

    def verify_final(
        _payload: Mapping[str, Any] | None,
        _result: Any,
    ) -> WorkflowVerification:
        import_check = state.verify_import()
        action_check = state.verify_actions()
        rtpc_check = state.verify_rtpc()
        protected_check = state.verify_protected(before)
        failures = (
            *import_check.failures,
            *action_check.failures,
            *rtpc_check.failures,
            *protected_check.failures,
        )
        return WorkflowVerification(
            workflow_id,
            "workflow_complete",
            not failures,
            tuple(failures),
            MappingProxyType(
                {
                    "transactions": [
                        _verification_record(import_check),
                        _verification_record(action_check),
                        _verification_record(rtpc_check),
                        _verification_record(protected_check),
                    ],
                    "final_snapshot_sha256": _json_sha256(state.snapshot()),
                }
            ),
        )

    return PreparedWeatherWorkflow(
        workflow_id=workflow_id,
        prompt=prompt,
        visible_values=visible_values,
        prompt_sources=MappingProxyType(
            {
                "integration_visible_inputs": {
                    key: value for key, value in visible_values.items()
                }
            }
        ),
        protocol=protocol,
        typed_sections=typed_sections,
        required_reference="references/waapi-operate.md",
        expected_dispatches=(
            ("ak.wwise.core.audio.import", 1),
            ("ak.wwise.core.object.set", 2),
        ),
        snapshot=state.snapshot,
        observe_payload=observe_payload,
        verify_turn=verify_turn,
        verify_final=verify_final,
        cleanup_success=state.cleanup_success,
    )


@dataclass(slots=True)
class _WeatherState:
    workflow_id: str
    version: str
    direct: DirectCall
    weather_root: str
    weather_bus: str
    event_root: str
    parameter_path: str
    containers: tuple[tuple[str, str, str], ...]
    targets: tuple[WeatherTarget, ...]
    created_ids: tuple[str, ...]
    source_root: Path
    sandbox_root: Path
    source_proofs: Mapping[str, Mapping[str, Any]]
    cleaned: bool = False

    def snapshot(self) -> Mapping[str, Any]:
        target_rows: dict[str, Any] = {}
        for target in self.targets:
            object_row = _read_optional(
                self.direct,
                target.logical_path,
                (
                    "id",
                    "name",
                    "type",
                    "path",
                    "parent",
                    "@IsLoopingEnabled",
                    "@IsLoopingInfinite",
                    "@IgnoreParentMaxSoundInstance",
                    "@UseMaxSoundPerInstance",
                    "@MaxSoundPerInstance",
                    "@Volume",
                    "OutputBus",
                ),
            )
            event_row = _read_optional(
                self.direct,
                target.event_path,
                ("id", "name", "type", "path", "parent", "childrenCount"),
            )
            actions = (
                _read_children(
                    self.direct,
                    str(event_row["id"]),
                    (
                        "id",
                        "name",
                        "type",
                        "path",
                        "parent",
                        "ActionType",
                        "Target",
                        "@FadeTime",
                        "@Delay",
                    ),
                )
                if event_row is not None
                else ()
            )
            sources = (
                _read_children(
                    self.direct,
                    str(object_row["id"]),
                    (
                        "id",
                        "name",
                        "type",
                        "path",
                        "parent",
                        "originalFilePath",
                        "audioSource:language",
                    ),
                )
                if object_row is not None
                else ()
            )
            rtpcs = (
                _read_rtpcs(self.direct, str(object_row["id"]))
                if object_row is not None
                else ()
            )
            target_rows[target.key] = {
                "object": object_row,
                "event": event_row,
                "actions": list(actions),
                "sources": list(sources),
                "rtpcs": list(rtpcs),
            }
        return MappingProxyType(
            {
                "workflow_id": self.workflow_id,
                "version": self.version,
                "weather_root": _read_optional(
                    self.direct,
                    self.weather_root,
                    ("id", "name", "type", "path", "parent"),
                ),
                "weather_bus": _read_optional(
                    self.direct,
                    self.weather_bus,
                    ("id", "name", "type", "path", "parent", "@Volume"),
                ),
                "event_root": _read_optional(
                    self.direct,
                    self.event_root,
                    ("id", "name", "type", "path", "parent"),
                ),
                "rain_parameter": _read_optional(
                    self.direct,
                    self.parameter_path,
                    ("id", "name", "type", "path", "parent"),
                ),
                "containers": {
                    path: _read_optional(
                        self.direct,
                        path,
                        ("id", "name", "type", "path", "parent"),
                    )
                    for path, _object_type, _parent in self.containers
                },
                "targets": target_rows,
                "source_files": {
                    target.key: _file_proof(target.source_path)
                    for target in self.targets
                },
            }
        )

    def verify_import(self) -> WorkflowVerification:
        snapshot = self.snapshot()
        failures: list[str] = []
        bus_id = _identity(snapshot["weather_bus"])
        container_rows = snapshot["containers"]
        for path, object_type, parent_path in self.containers:
            row = container_rows.get(path)
            parent = (
                snapshot["weather_root"]
                if parent_path == self.weather_root
                else container_rows.get(parent_path)
            )
            actual_type = _type_token(
                row.get("type") if isinstance(row, Mapping) else None
            )
            accepted_types = (
                {"actormixer", "propertycontainer"}
                if object_type == "ActorMixer"
                else {_type_token(object_type)}
            )
            if (
                not isinstance(row, Mapping)
                or row.get("path") != path
                or actual_type not in accepted_types
                or not isinstance(parent, Mapping)
                or _identity(row.get("parent")) != _identity(parent)
            ):
                failures.append(f"{path} container type or parent differs")
        for target in self.targets:
            row = snapshot["targets"][target.key]
            obj = row["object"]
            event = row["event"]
            actions = row["actions"]
            sources = row["sources"]
            if not isinstance(obj, Mapping):
                failures.append(f"{target.name} Sound is absent")
                continue
            if (
                obj.get("path") != target.logical_path
                or _type_token(obj.get("type")) != "sound"
                or _number(obj.get("@Volume")) != target.volume
                or _bool(obj.get("@IgnoreParentMaxSoundInstance")) is not True
                or _bool(obj.get("@UseMaxSoundPerInstance")) is not True
                or _integer(obj.get("@MaxSoundPerInstance"))
                != target.instance_limit
                or _identity(obj.get("OutputBus")) != bus_id
            ):
                failures.append(f"{target.name} Sound fields or OutputBus differ")
            if (
                _bool(obj.get("@IsLoopingEnabled")) is not True
                or _bool(obj.get("@IsLoopingInfinite")) is not True
            ):
                failures.append(f"{target.name} looping state differs")
            parent_path = target.logical_path.rpartition("\\")[0]
            if (
                _identity(obj.get("parent"))
                != _identity(container_rows.get(parent_path))
            ):
                failures.append(f"{target.name} Sound parent differs")
            if (
                not isinstance(event, Mapping)
                or event.get("path") != target.event_path
                or _type_token(event.get("type")) != "event"
                or _identity(event.get("parent"))
                != _identity(snapshot["event_root"])
            ):
                failures.append(f"Play_{target.name} Event is absent")
            if (
                len(actions) != 1
                or _type_token(actions[0].get("type")) != "action"
                or _integer(actions[0].get("ActionType")) != 1
                or _identity(actions[0].get("Target")) != _identity(obj)
            ):
                failures.append(f"Play_{target.name} Action graph differs")
            audio_sources = [
                item
                for item in sources
                if _type_token(item.get("type")) == "audiofilesource"
            ]
            if len(audio_sources) != 1:
                failures.append(f"{target.name} AudioFileSource is not unique")
            else:
                source = audio_sources[0]
                source_language = _name_value(
                    source.get("audioSource:language")
                )
                original_path = source.get("originalFilePath")
                if source_language != "SFX":
                    failures.append(
                        f"{target.name} AudioFileSource file or language differs"
                    )
                    continue
                try:
                    copied_proof = _copied_original_proof(
                        original_path,
                        sandbox_root=self.sandbox_root,
                    )
                except IntegrationWeatherRuntimeError:
                    failures.append(
                        f"{target.name} copied Original is unavailable"
                    )
                    continue
                if (
                    Path(str(copied_proof["path"])).name
                    != target.source_path.name
                ):
                    failures.append(
                        f"{target.name} AudioFileSource file or language differs"
                    )
                elif (
                    copied_proof["sha256"]
                    != self.source_proofs[target.key]["sha256"]
                ):
                    failures.append(
                        f"{target.name} copied Original content differs"
                    )
        if _plain(snapshot["source_files"]) != _plain(self.source_proofs):
            failures.append("weather source fixture files changed")
        return WorkflowVerification(
            self.workflow_id,
            "import_weather_assets",
            not failures,
            tuple(failures),
            MappingProxyType({"snapshot_sha256": _json_sha256(snapshot)}),
        )

    def verify_actions(self) -> WorkflowVerification:
        snapshot = self.snapshot()
        failures: list[str] = []
        for target in self.targets:
            row = snapshot["targets"][target.key]
            obj = row["object"]
            actions = row["actions"]
            if not isinstance(obj, Mapping) or len(actions) != 1:
                failures.append(f"{target.name} Action graph is unavailable")
                continue
            action = actions[0]
            if (
                _number(action.get("@FadeTime")) != target.fade_time
                or _number(action.get("@Delay")) != target.delay
                or _integer(action.get("ActionType")) != 1
                or _identity(action.get("Target")) != _identity(obj)
            ):
                failures.append(
                    f"Play_{target.name} FadeTime, Delay, or target differs"
                )
        return WorkflowVerification(
            self.workflow_id,
            "configure_event_actions",
            not failures,
            tuple(failures),
            MappingProxyType({"snapshot_sha256": _json_sha256(snapshot)}),
        )

    def verify_rtpc(self) -> WorkflowVerification:
        snapshot = self.snapshot()
        failures: list[str] = []
        rain = snapshot["targets"]["rain_bed"]
        parameter_id = _identity(snapshot["rain_parameter"])
        matching = [
            row
            for row in rain["rtpcs"]
            if row.get("@PropertyName") == "Volume"
            and _identity(row.get("@ControlInput")) == parameter_id
        ]
        if len(matching) != 1:
            failures.append("Rain_Bed Volume RTPC is absent or ambiguous")
        else:
            points = matching[0].get("@Curve", {}).get("points")
            if _normalize_points(points) != tuple(dict(point) for point in RTPC_POINTS):
                failures.append("Rain_Bed Volume RTPC points differ")
        return WorkflowVerification(
            self.workflow_id,
            "bind_rain_intensity_rtpc",
            not failures,
            tuple(failures),
            MappingProxyType({"snapshot_sha256": _json_sha256(snapshot)}),
        )

    def verify_protected(
        self,
        before: Mapping[str, Any],
    ) -> WorkflowVerification:
        snapshot = self.snapshot()
        protected_fields = (
            "weather_bus",
            "rain_parameter",
            "source_files",
        )
        failures = tuple(
            f"protected {field} changed"
            for field in protected_fields
            if _plain(snapshot.get(field)) != _plain(before.get(field))
        )
        return WorkflowVerification(
            self.workflow_id,
            "protected_state",
            not failures,
            failures,
            MappingProxyType(
                {
                    "before_sha256": _json_sha256(
                        {
                            field: before.get(field)
                            for field in protected_fields
                        }
                    ),
                    "after_sha256": _json_sha256(
                        {
                            field: snapshot.get(field)
                            for field in protected_fields
                        }
                    ),
                }
            ),
        )

    def cleanup_success(self) -> Mapping[str, Any]:
        if self.cleaned:
            raise IntegrationWeatherRuntimeError(
                "weather cleanup cannot run more than once"
            )
        deleted: list[str] = []
        for object_id in reversed(self.created_ids):
            if _read_optional_by_id(
                self.direct,
                object_id,
                ("id", "path"),
            ) is not None:
                _delete_object(self.direct, object_id)
                deleted.append(object_id)
        _save_project(self.direct)
        residual = [
            path
            for path in (self.weather_root, self.weather_bus, self.event_root)
            if _read_optional(self.direct, path, ("id", "path")) is not None
        ]
        if residual:
            raise IntegrationWeatherRuntimeError(
                f"weather cleanup left Wwise paths: {residual}"
            )
        if self.source_root.exists():
            shutil.rmtree(self.source_root)
        self.cleaned = True
        return MappingProxyType(
            {
                "workflow_id": self.workflow_id,
                "deleted_object_ids": deleted,
                "source_root_removed": not self.source_root.exists(),
            }
        )


def _weather_import_request(
    version: str,
    *,
    targets: Sequence[WeatherTarget],
    weather_root: str,
    weather_bus: str,
    dependency_properties: Sequence[Mapping[str, Any]] = (),
) -> Mapping[str, Any]:
    imports: list[dict[str, Any]] = [
        {"object_path": path, "object_type": object_type}
        for path, object_type, _parent in _weather_container_specs(weather_root)
    ]
    for target in targets:
        properties = [
            {"name": "IsLoopingEnabled", "value": True},
            {"name": "IsLoopingInfinite", "value": True},
            {
                "name": "IgnoreParentMaxSoundInstance",
                "value": True,
            },
            {"name": "UseMaxSoundPerInstance", "value": True},
            {
                "name": "MaxSoundPerInstance",
                "value": target.instance_limit,
            },
            {"name": "Volume", "value": target.volume},
        ]
        _merge_required_properties(
            properties,
            dependency_properties,
            owner=target.name,
        )
        imports.append(
            {
                "object_path": target.logical_path,
                "object_type": "Sound",
                "audio_file": str(target.source_path),
                "import_language": "SFX",
                "event": {"path": target.event_path, "action": "Play"},
                "properties": properties,
                "references": [
                    {
                        "name": "OutputBus",
                        "target": {"kind": "path", "value": weather_bus},
                    }
                ],
            }
        )
    return MappingProxyType(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": version,
            "operation": "audio.import",
            "arguments": {
                "imports": imports,
                "import_operation": "createNew",
            },
        }
    )


def _weather_container_specs(
    weather_root: str,
) -> tuple[tuple[str, str, str], ...]:
    interactive_root = f"{weather_root}\\Weather_Interactive"
    return (
        (interactive_root, "ActorMixer", weather_root),
        (f"{interactive_root}\\Rain", "ActorMixer", interactive_root),
        (f"{interactive_root}\\Wind", "ActorMixer", interactive_root),
        (
            f"{interactive_root}\\Thunder",
            "RandomSequenceContainer",
            interactive_root,
        ),
    )


def _weather_action_request(
    version: str,
    *,
    targets: Sequence[WeatherTarget],
) -> Mapping[str, Any]:
    return MappingProxyType(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": version,
            "operation": "object.set",
            "arguments": {
                "objects": [
                    {
                        "object": {
                            "kind": "direct-child",
                            "parent": {
                                "kind": "path",
                                "value": target.event_path,
                            },
                            "type": "Action",
                        },
                        "properties": [
                            {
                                "name": "FadeTime",
                                "value": target.fade_time,
                            },
                            {"name": "Delay", "value": target.delay},
                        ],
                    }
                    for target in targets
                ],
                "on_name_conflict": "fail",
            },
        }
    )


def _weather_rtpc_request(
    version: str,
    *,
    target: WeatherTarget,
    control_input: str,
) -> Mapping[str, Any]:
    return MappingProxyType(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": version,
            "operation": "object.setRTPC",
            "arguments": {
                "object": {"kind": "path", "value": target.logical_path},
                "property": "Volume",
                "control_input": {
                    "kind": "path",
                    "value": control_input,
                },
                "points": [dict(point) for point in RTPC_POINTS],
                "mode": "add_or_replace",
            },
        }
    )


def _build_metadata_workflow_protocol(
    requests: Sequence[Mapping[str, Any]],
    *,
    metadata: Sequence[
        (
            tuple[
                str,
                Sequence[str],
                Sequence[str],
                Sequence[MetadataTokenProjection],
                str,
            ]
            | None
        )
    ],
    gateway_derived_reference_activations: Sequence[
        Sequence[GatewayDerivedReferenceActivationAllowance]
    ]
    | None = None,
) -> V3GatewayProtocol:
    if len(requests) != len(metadata):
        raise IntegrationWeatherRuntimeError(
            "weather metadata/request transaction count differs"
        )
    if gateway_derived_reference_activations is None:
        gateway_derived_reference_activations = tuple(
            () for _request in requests
        )
    if len(requests) != len(gateway_derived_reference_activations):
        raise IntegrationWeatherRuntimeError(
            "weather derived-activation/request transaction count differs"
        )
    metadata_reuse_by_tx: dict[
        str,
        tuple[
            str,
            str,
            tuple[str, ...],
            tuple[MetadataTokenProjection, ...],
            str,
        ],
    ] = {}
    for index, row in enumerate(metadata):
        if row is not None:
            continue
        request = requests[index]
        arguments = request.get("arguments")
        property_token = (
            arguments.get("property")
            if isinstance(arguments, Mapping)
            else None
        )
        prior_sources = tuple(
            (source_index, prior)
            for source_index, prior in enumerate(metadata[:index])
            if prior is not None
            and isinstance(property_token, str)
            and property_token.casefold()
            in {str(token).casefold() for token in prior[2]}
        )
        if (
            index != 2
            or request.get("operation") != "object.setRTPC"
            or not isinstance(property_token, str)
            or len(prior_sources) != 1
        ):
            raise IntegrationWeatherRuntimeError(
                "weather may omit discovery only for tx03 object.setRTPC "
                "when its exact property token was proved by prior live metadata"
            )
        if gateway_derived_reference_activations[index]:
            raise IntegrationWeatherRuntimeError(
                "weather metadata-reuse transaction cannot carry "
                "gateway-derived reference activations"
            )
        source_index, source = prior_sources[0]
        source_object_type, _queries, _tokens, source_projection, _equivalence = (
            source
        )
        reused_projection = tuple(
            item
            for item in source_projection
            if item.name.casefold() == property_token.casefold()
        )
        if len(reused_projection) != 1:
            raise IntegrationWeatherRuntimeError(
                "weather RTPC property lacks one exact prior live metadata projection"
            )
        metadata_reuse_by_tx[f"tx{index + 1:02d}"] = (
            f"tx{source_index + 1:02d}.metadata",
            source_object_type,
            (property_token,),
            reused_projection,
            "object_set_rtpc_v1",
        )
    base = build_transaction_protocol(requests)
    metadata_by_tx = {
        f"tx{index:02d}": row
        for index, row in enumerate(metadata, start=1)
    }
    steps: list[ExpectedGatewayStep] = []
    for step in base.steps:
        prefix = step.name.split(".", 1)[0]
        if step.subcommand == "operation-schema":
            metadata_row = metadata_by_tx[prefix]
            if metadata_row is None:
                steps.append(step)
                continue
            (
                object_type,
                queries,
                _tokens,
                _projection,
                _equivalence,
            ) = metadata_row
            arguments: list[Any] = [
                "discover",
                "--object-type",
                object_type,
            ]
            for query in queries:
                arguments.extend(("--query", MetadataQueryArgument(query)))
            candidate_limit = metadata_candidate_limit(queries)
            arguments.extend(
                (
                    "--limit",
                    str(candidate_limit),
                )
            )
            metadata_step = ExpectedGatewayStep(
                name=f"{prefix}.metadata",
                subcommand="metadata",
                arguments=tuple(arguments),
            )
            transaction_index = int(prefix[2:]) - 1
            operation = requests[transaction_index].get("operation")
            if operation in {"object.create", "object.set"}:
                steps.extend((step, metadata_step))
            else:
                steps.extend((metadata_step, step))
            continue
        if step.subcommand == "preview":
            if (
                len(step.arguments) != 3
                or step.arguments[:2] != ("--apply", "--request-json")
                or not isinstance(step.arguments[2], SemanticJsonArgument)
            ):
                raise IntegrationWeatherRuntimeError(
                    "weather transaction preview topology drifted"
                )
            metadata_row = metadata_by_tx[prefix]
            if metadata_row is not None:
                (
                    object_type,
                    _queries,
                    tokens,
                    projection,
                    equivalence,
                ) = metadata_row
                step = replace(
                    step,
                    arguments=(
                        "--apply",
                        "--request-json",
                        MetadataBoundJsonArgument(
                            expected=step.arguments[2].expected,
                            metadata_step=f"{prefix}.metadata",
                            object_type=object_type,
                            required_tokens=tuple(tokens),
                            expected_required_token_projection=tuple(projection),
                            equivalence=equivalence,
                            gateway_derived_reference_activations=tuple(
                                gateway_derived_reference_activations[
                                    int(prefix[2:]) - 1
                                ]
                            ),
                        ),
                    ),
                )
            else:
                (
                    metadata_step,
                    object_type,
                    tokens,
                    projection,
                    equivalence,
                ) = metadata_reuse_by_tx[prefix]
                step = replace(
                    step,
                    arguments=(
                        "--apply",
                        "--request-json",
                        MetadataBoundJsonArgument(
                            expected=step.arguments[2].expected,
                            metadata_step=metadata_step,
                            object_type=object_type,
                            required_tokens=tokens,
                            expected_required_token_projection=projection,
                            equivalence=equivalence,
                        ),
                    ),
                )
        steps.append(step)
    prefixes = tuple(
        base_prefix
        + sum(
            candidate.subcommand == "operation-schema"
            and metadata_by_tx[
                candidate.name.split(".", 1)[0]
            ]
            is not None
            for candidate in base.steps[:base_prefix]
        )
        for base_prefix in base.turn_prefix_counts
    )
    return V3GatewayProtocol(
        tuple(steps),
        prefixes,
        commutative_read_only_step_groups=(
            ("tx02.operation-schema", "tx02.metadata"),
        ),
    )


def _weather_plan_transactions() -> tuple[Mapping[str, Any], ...]:
    return (
        {
            "transaction_id": "tx01",
            "api": "ak.wwise.core.audio.import",
            "operation": "audio.import",
            "phase": "import_weather_assets",
            "primary_step": "tx01.execute",
        },
        {
            "transaction_id": "tx02",
            "api": "ak.wwise.core.object.set",
            "operation": "object.set",
            "phase": "configure_event_actions",
            "primary_step": "tx02.execute",
        },
        {
            "transaction_id": "tx03",
            "api": "ak.wwise.core.object.set",
            "operation": "object.setRTPC",
            "phase": "bind_rain_intensity_rtpc",
            "primary_step": "tx03.execute",
        },
    )


def _workflow_plan_steps(
    protocol: V3GatewayProtocol,
    *,
    transaction_phases: Sequence[str],
) -> tuple[Mapping[str, Any], ...]:
    transactions = _weather_plan_transactions()
    transaction_by_id = {
        row["transaction_id"]: row for row in transactions
    }
    result: list[Mapping[str, Any]] = []
    kind_by_subcommand = {
        "operation-schema": "operation_schema",
        "preview": "preview",
        "transaction-show": "transaction_show",
        "confirm": "confirm",
        "execute": "execute",
        "verify": "verify",
    }
    for step in protocol.steps:
        tx_id = step.name.split(".", 1)[0] if step.name.startswith("tx") else None
        if tx_id in transaction_by_id and step.subcommand in kind_by_subcommand:
            transaction = transaction_by_id[tx_id]
            result.append(
                {
                    "name": step.name,
                    "kind": kind_by_subcommand[step.subcommand],
                    "phase": transaction["phase"],
                    "transaction_id": tx_id,
                    "api": transaction["api"],
                }
            )
        else:
            index = int(tx_id[2:]) - 1 if tx_id in transaction_by_id else 0
            result.append(
                {
                    "name": step.name,
                    "kind": "checkpoint",
                    "phase": transaction_phases[index],
                    "transaction_id": None,
                    "api": None,
                }
            )
    result.append(
        {
            "name": "cleanup.success",
            "kind": "cleanup",
            "phase": "cleanup",
            "transaction_id": None,
            "api": None,
        }
    )
    return tuple(result)


def _discover(
    direct: DirectCall,
    *,
    object_type: str,
    queries: Sequence[str],
    required_tokens: Sequence[str],
) -> tuple[Mapping[str, Any], tuple[MetadataTokenProjection, ...]]:
    result = discover_metadata(
        read_call=direct,
        queries=queries,
        object_type=object_type,
        limit=metadata_candidate_limit(queries),
    ).as_dict()
    resolved = result.get("scope", {}).get("resolved", {})
    if not isinstance(resolved, Mapping) or resolved.get("name") != object_type:
        raise IntegrationWeatherRuntimeError(
            f"live metadata did not resolve exact {object_type}"
        )
    projection = tuple(
        project_required_metadata_tokens(
            result,
            object_type=object_type,
            required_tokens=required_tokens,
        )
    )
    return MappingProxyType(dict(result)), projection


def _metadata_dependency_properties(
    result: Mapping[str, Any],
    *,
    selected_tokens: Sequence[str],
) -> tuple[Mapping[str, Any], ...]:
    """Return exact same-object dependency values proven by live discovery.

    The workflow oracle must follow the same dependency-closure contract shown
    to the evaluated agent.  It therefore derives names and values from the
    current Wwise result instead of hard-coding version-specific property
    tokens.  Every selected field and recursively required dependency must be
    present exactly once in the closed discovery result.
    """

    if (
        result.get("dependency_closure_complete") is not True
        or result.get("unresolved_dependencies") != []
    ):
        raise IntegrationWeatherRuntimeError(
            "weather metadata dependency closure is incomplete"
        )

    rows_by_name: dict[str, Mapping[str, Any]] = {}
    for collection in ("candidates", "dependency_candidates"):
        rows = result.get(collection)
        if not isinstance(rows, list):
            raise IntegrationWeatherRuntimeError(
                f"weather metadata {collection} is malformed"
            )
        for row in rows:
            name = row.get("name") if isinstance(row, Mapping) else None
            if (
                not isinstance(name, str)
                or not name
                or name != name.strip()
                or name.startswith("@")
            ):
                raise IntegrationWeatherRuntimeError(
                    f"weather metadata {collection} has an invalid name"
                )
            key = name.casefold()
            if key in rows_by_name:
                raise IntegrationWeatherRuntimeError(
                    f"weather metadata repeats candidate {name!r}"
                )
            rows_by_name[key] = row

    queue = list(selected_tokens)
    visited: set[str] = set()
    required: dict[str, tuple[str, Any]] = {}
    while queue:
        owner_name = queue.pop(0)
        owner_key = owner_name.casefold()
        if owner_key in visited:
            continue
        owner = rows_by_name.get(owner_key)
        if owner is None or owner.get("name") != owner_name:
            raise IntegrationWeatherRuntimeError(
                f"weather metadata lacks exact selected token {owner_name!r}"
            )
        visited.add(owner_key)
        requirements = owner.get("dependency_requirements")
        if not isinstance(requirements, list):
            raise IntegrationWeatherRuntimeError(
                f"weather metadata dependencies for {owner_name!r} are malformed"
            )
        for requirement in requirements:
            property_name = (
                requirement.get("property")
                if isinstance(requirement, Mapping)
                else None
            )
            required_values = (
                requirement.get("required_values")
                if isinstance(requirement, Mapping)
                else None
            )
            if (
                not isinstance(property_name, str)
                or not property_name
                or property_name != property_name.strip()
                or property_name.startswith("@")
                or not isinstance(required_values, list)
                or len(required_values) != 1
            ):
                raise IntegrationWeatherRuntimeError(
                    f"weather metadata dependency for {owner_name!r} "
                    "does not prove one exact property value"
                )
            dependency = rows_by_name.get(property_name.casefold())
            if (
                dependency is None
                or dependency.get("name") != property_name
                or dependency.get("kind") != "property"
            ):
                raise IntegrationWeatherRuntimeError(
                    f"weather metadata dependency {property_name!r} "
                    "is not one exact property candidate"
                )
            value = required_values[0]
            try:
                value_key = json.dumps(
                    value,
                    allow_nan=False,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            except (TypeError, ValueError) as exc:
                raise IntegrationWeatherRuntimeError(
                    f"weather metadata dependency {property_name!r} "
                    "has a non-JSON value"
                ) from exc
            previous = required.get(property_name.casefold())
            if previous is not None:
                previous_key = json.dumps(
                    previous[1],
                    allow_nan=False,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if previous[0] != property_name or previous_key != value_key:
                    raise IntegrationWeatherRuntimeError(
                        f"weather metadata dependency {property_name!r} conflicts"
                    )
            else:
                required[property_name.casefold()] = (property_name, value)
            queue.append(property_name)

    return tuple(
        MappingProxyType({"name": name, "value": value})
        for name, value in required.values()
    )


def _gateway_derived_reference_activation_allowances(
    result: Mapping[str, Any],
    *,
    selected_tokens: Sequence[str],
    expected_request: Mapping[str, Any],
) -> tuple[GatewayDerivedReferenceActivationAllowance, ...]:
    """Bind supported live reference activators to exact expected import rows."""

    if (
        result.get("dependency_closure_complete") is not True
        or result.get("unresolved_dependencies") != []
    ):
        raise IntegrationWeatherRuntimeError(
            "weather metadata dependency closure is incomplete"
        )
    rows_by_name: dict[str, Mapping[str, Any]] = {}
    for collection in ("candidates", "dependency_candidates"):
        rows = result.get(collection)
        if not isinstance(rows, list):
            raise IntegrationWeatherRuntimeError(
                f"weather metadata {collection} is malformed"
            )
        for row in rows:
            name = row.get("name") if isinstance(row, Mapping) else None
            if (
                not isinstance(name, str)
                or not name
                or name != name.strip()
                or name.startswith("@")
            ):
                raise IntegrationWeatherRuntimeError(
                    f"weather metadata {collection} has an invalid name"
                )
            key = name.casefold()
            if key in rows_by_name:
                raise IntegrationWeatherRuntimeError(
                    f"weather metadata repeats candidate {name!r}"
                )
            rows_by_name[key] = row

    arguments = expected_request.get("arguments")
    imports = (
        arguments.get("imports")
        if isinstance(arguments, Mapping)
        else None
    )
    defaults = (
        arguments.get("defaults", {})
        if isinstance(arguments, Mapping)
        else None
    )
    if not isinstance(imports, list) or not isinstance(defaults, Mapping):
        raise IntegrationWeatherRuntimeError(
            "weather expected audio.import request is malformed"
        )

    supported_fields = {
        "action",
        "context",
        "property",
        "type",
        "required_values",
    }
    allowances: list[GatewayDerivedReferenceActivationAllowance] = []
    for selected_name in selected_tokens:
        selected = rows_by_name.get(selected_name.casefold())
        if selected is None or selected.get("name") != selected_name:
            raise IntegrationWeatherRuntimeError(
                f"weather metadata lacks exact selected token {selected_name!r}"
            )
        if selected.get("kind") != "reference":
            continue
        requirements = selected.get("dependency_requirements")
        if not isinstance(requirements, list):
            raise IntegrationWeatherRuntimeError(
                f"weather metadata dependencies for {selected_name!r} "
                "are malformed"
            )
        for requirement in requirements:
            if (
                not isinstance(requirement, Mapping)
                or set(requirement) != supported_fields
                or requirement.get("type") != "override"
                or requirement.get("action") != "Enable"
                or requirement.get("context") != "Self"
                or not isinstance(requirement.get("property"), str)
                or requirement.get("required_values") != [True]
                or type(requirement["required_values"][0]) is not bool
            ):
                continue
            property_name = str(requirement["property"])
            dependency = rows_by_name.get(property_name.casefold())
            metadata = (
                dependency.get("metadata")
                if isinstance(dependency, Mapping)
                else None
            )
            if (
                dependency is None
                or dependency.get("name") != property_name
                or dependency.get("kind") != "property"
                or not isinstance(metadata, Mapping)
                or str(metadata.get("type", "")).casefold()
                not in {"bool", "boolean"}
            ):
                raise IntegrationWeatherRuntimeError(
                    f"weather reference activation {property_name!r} is not "
                    "one exact live Boolean property"
                )
            for row_index, row in enumerate(imports):
                if not isinstance(row, Mapping):
                    raise IntegrationWeatherRuntimeError(
                        "weather expected audio.import row is malformed"
                    )
                references = row.get("references", [])
                properties = row.get("properties", [])
                if not isinstance(references, list) or not isinstance(
                    properties,
                    list,
                ):
                    raise IntegrationWeatherRuntimeError(
                        "weather expected audio.import named fields are malformed"
                    )
                matching_references = [
                    item
                    for item in references
                    if isinstance(item, Mapping)
                    and item.get("name") == selected_name
                ]
                if not matching_references:
                    continue
                matching_properties = [
                    item
                    for item in properties
                    if isinstance(item, Mapping)
                    and item.get("name") == property_name
                ]
                if (
                    len(matching_references) != 1
                    or len(matching_properties) != 1
                    or matching_properties[0].get("value") is not True
                ):
                    raise IntegrationWeatherRuntimeError(
                        f"weather expected row {row_index} does not bind "
                        f"{selected_name!r} to activation {property_name!r}"
                    )
                allowances.append(
                    GatewayDerivedReferenceActivationAllowance(
                        row_index=row_index,
                        property_name=property_name,
                        property_value=True,
                        reference_name=selected_name,
                    )
                )
    return tuple(allowances)


def _merge_required_properties(
    properties: list[dict[str, Any]],
    dependencies: Sequence[Mapping[str, Any]],
    *,
    owner: str,
) -> None:
    """Merge live-proven dependencies without overriding user values."""

    by_name = {
        str(item.get("name")).casefold(): item
        for item in properties
        if isinstance(item.get("name"), str)
    }
    for dependency in dependencies:
        name = dependency.get("name")
        if not isinstance(name, str) or set(dependency) != {"name", "value"}:
            raise IntegrationWeatherRuntimeError(
                f"{owner} has a malformed live metadata dependency"
            )
        current = by_name.get(name.casefold())
        if current is None:
            item = {"name": name, "value": dependency.get("value")}
            properties.append(item)
            by_name[name.casefold()] = item
            continue
        if current.get("name") != name or current.get("value") != dependency.get(
            "value"
        ):
            raise IntegrationWeatherRuntimeError(
                f"{owner} conflicts with live dependency {name!r}"
            )


def _create_object(
    direct: DirectCall,
    *,
    parent: str,
    object_type: str,
    name: str,
) -> str:
    result = direct(
        "ak.wwise.core.object.create",
        {
            "parent": parent,
            "type": object_type,
            "name": name,
            "onNameConflict": "fail",
            "autoAddToSourceControl": False,
        },
        {},
    )
    if not isinstance(result, Mapping):
        raise IntegrationWeatherRuntimeError("fixture object.create returned no object")
    return _require_guid(result.get("id"), f"created {name} id")


def _delete_object(direct: DirectCall, object_id: str) -> None:
    result = direct(
        "ak.wwise.core.object.delete",
        {"object": _require_guid(object_id, "cleanup id")},
        {},
    )
    if result is not None and not isinstance(result, Mapping):
        raise IntegrationWeatherRuntimeError(
            "fixture object.delete returned an invalid result"
        )


def _save_project(direct: DirectCall) -> None:
    result = direct("ak.wwise.core.project.save", {}, {})
    if result is not None and not isinstance(result, Mapping):
        raise IntegrationWeatherRuntimeError(
            "fixture project.save returned an invalid result"
        )


def _read_exact(
    direct: DirectCall,
    path: str,
    fields: Sequence[str],
) -> Mapping[str, Any]:
    rows = _read_path_rows(direct, path, fields)
    if len(rows) != 1:
        raise IntegrationWeatherRuntimeError(
            f"Wwise path did not resolve exactly once: {path}"
        )
    return rows[0]


def _read_optional(
    direct: DirectCall,
    path: str,
    fields: Sequence[str],
) -> Mapping[str, Any] | None:
    rows = _read_path_rows(direct, path, fields)
    if len(rows) > 1:
        raise IntegrationWeatherRuntimeError(
            f"Wwise path is ambiguous: {path}"
        )
    return rows[0] if rows else None


def _read_optional_by_id(
    direct: DirectCall,
    object_id: str,
    fields: Sequence[str],
) -> Mapping[str, Any] | None:
    result = direct(
        "ak.wwise.core.object.get",
        {"from": {"id": [_require_guid(object_id, "object id")]}},
        {"return": list(fields)},
    )
    rows = _result_rows(result)
    if len(rows) > 1:
        raise IntegrationWeatherRuntimeError("Wwise object id is ambiguous")
    return rows[0] if rows else None


def _read_path_rows(
    direct: DirectCall,
    path: str,
    fields: Sequence[str],
) -> tuple[Mapping[str, Any], ...]:
    result = direct(
        "ak.wwise.core.object.get",
        {"from": {"path": [path]}},
        {"return": list(fields)},
    )
    return _result_rows(result)


def _read_children(
    direct: DirectCall,
    object_id: str,
    fields: Sequence[str],
) -> tuple[Mapping[str, Any], ...]:
    result = direct(
        "ak.wwise.core.object.get",
        {
            "from": {"id": [_require_guid(object_id, "parent object id")]},
            "transform": [{"select": ["children"]}],
        },
        {"return": list(fields)},
    )
    return _result_rows(result)


def _read_rtpcs(
    direct: DirectCall,
    object_id: str,
) -> tuple[Mapping[str, Any], ...]:
    owner_id = _require_guid(object_id, "RTPC owner id")
    owner_result = direct(
        "ak.wwise.core.object.get",
        {"from": {"id": [owner_id]}},
        {"return": ["id", "@RTPC"]},
    )
    owner_rows = _result_rows(owner_result)
    if (
        len(owner_rows) != 1
        or _identity(owner_rows[0].get("id")) != owner_id.casefold()
    ):
        raise IntegrationWeatherRuntimeError(
            "RTPC owner did not resolve exactly once"
        )
    owner_row = owner_rows[0]
    if "@RTPC" not in owner_row:
        return ()
    raw_references = owner_row["@RTPC"]
    if not isinstance(raw_references, list):
        raise IntegrationWeatherRuntimeError(
            "RTPC owner did not return an @RTPC array"
        )
    if len(raw_references) > RTPC_READ_LIMIT:
        raise IntegrationWeatherRuntimeError(
            "RTPC owner exceeds the hidden observation limit"
        )
    reference_ids: list[str] = []
    reference_keys: set[str] = set()
    for index, reference in enumerate(raw_references):
        reference_id = (
            reference.get("id")
            if isinstance(reference, Mapping)
            else None
        )
        try:
            canonical_id = _require_guid(
                reference_id,
                f"RTPC reference {index} id",
            )
        except IntegrationWeatherRuntimeError as exc:
            raise IntegrationWeatherRuntimeError(
                "RTPC owner returned an invalid list entry"
            ) from exc
        key = canonical_id.casefold()
        if key in reference_keys:
            raise IntegrationWeatherRuntimeError(
                "RTPC owner returned a duplicate list entry"
            )
        reference_keys.add(key)
        reference_ids.append(canonical_id)
    if not reference_ids:
        return ()

    result = direct(
        "ak.wwise.core.object.get",
        {"from": {"id": reference_ids}},
        {
            "return": [
                "id",
                "name",
                "type",
                "path",
                "notes",
                "@PropertyName",
                "@ControlInput",
                "@Curve",
            ]
        },
    )
    rows = _result_rows(result)
    rows_by_id: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(rows):
        try:
            row_id = _require_guid(row.get("id"), f"RTPC row {index} id")
        except IntegrationWeatherRuntimeError as exc:
            raise IntegrationWeatherRuntimeError(
                "RTPC detail readback returned an invalid row"
            ) from exc
        key = row_id.casefold()
        if key in rows_by_id:
            raise IntegrationWeatherRuntimeError(
                "RTPC detail readback returned a duplicate GUID"
            )
        if _type_token(row.get("type")) != "rtpc":
            raise IntegrationWeatherRuntimeError(
                "RTPC detail readback returned another object type"
            )
        rows_by_id[key] = row
    if set(rows_by_id) != reference_keys:
        raise IntegrationWeatherRuntimeError(
            "RTPC detail readback differs from the owner list"
        )
    return tuple(rows_by_id[value.casefold()] for value in reference_ids)


def _result_rows(result: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(result, Mapping):
        raise IntegrationWeatherRuntimeError("object.get returned no object")
    rows = result.get("return")
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise IntegrationWeatherRuntimeError("object.get rows are invalid")
    return tuple(MappingProxyType(dict(row)) for row in rows)


def _require_exact_absence(direct: DirectCall, path: str) -> None:
    if _read_optional(direct, path, ("id", "path")) is not None:
        raise IntegrationWeatherRuntimeError(
            f"scenario-owned Wwise path already exists: {path}"
        )


def _write_wav(
    path: Path,
    *,
    frequency_hz: int,
    duration_ms: int,
) -> None:
    if path.exists() or path.is_symlink():
        raise IntegrationWeatherRuntimeError(
            f"weather source path is not fresh: {path}"
        )
    sample_rate = 48_000
    sample_count = max(1, sample_rate * duration_ms // 1000)
    frames = bytearray()
    for index in range(sample_count):
        value = int(
            math.sin(2.0 * math.pi * frequency_hz * index / sample_rate)
            * 8191
        )
        frames.extend(struct.pack("<h", value))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(frames))


def _strip_typed_segments(value: str) -> str:
    parts: list[str] = []
    for segment in value.split("\\"):
        if not segment:
            continue
        if segment.startswith("<") and ">" in segment:
            segment = segment.split(">", 1)[1]
        if not segment:
            raise IntegrationWeatherRuntimeError(
                "typed weather path has an empty logical segment"
            )
        parts.append(segment)
    return "\\".join(parts)


def _file_proof(path: Path) -> Mapping[str, Any]:
    candidate = Path(path).resolve(strict=True)
    if not candidate.is_file() or candidate.is_symlink():
        raise IntegrationWeatherRuntimeError(
            f"weather source is not a regular file: {candidate}"
        )
    payload = candidate.read_bytes()
    return MappingProxyType(
        {
            "path": str(candidate),
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    )


def _copied_original_proof(
    value: Any,
    *,
    sandbox_root: Path,
    account_home: Path | None = None,
) -> Mapping[str, Any]:
    """Prove one Wwise-reported Original inside this workflow's sandbox."""

    try:
        candidate = localize_copied_original_path(
            value,
            account_home=account_home,
        )
    except IntegrationOriginalPathError as exc:
        raise IntegrationWeatherRuntimeError(str(exc)) from exc
    try:
        root_input = Path(sandbox_root)
        root_metadata = root_input.lstat()
        if (
            path_is_link_or_reparse(root_input, metadata=root_metadata)
            or not stat.S_ISDIR(root_metadata.st_mode)
        ):
            raise IntegrationWeatherRuntimeError(
                "weather sandbox root is not a real directory"
            )
        root = root_input.resolve(strict=True)
        originals = root / "Originals"
        originals_metadata = originals.lstat()
    except IntegrationWeatherRuntimeError:
        raise
    except OSError as exc:
        raise IntegrationWeatherRuntimeError(
            "weather copied Originals root is unavailable"
        ) from exc
    if (
        path_is_link_or_reparse(originals, metadata=originals_metadata)
        or not stat.S_ISDIR(originals_metadata.st_mode)
    ):
        raise IntegrationWeatherRuntimeError(
            "weather copied Originals root is not a real directory"
        )
    try:
        lexical_relative = candidate.relative_to(root)
    except ValueError as exc:
        raise IntegrationWeatherRuntimeError(
            "weather copied Original escapes the sandbox"
        ) from exc
    if (
        not lexical_relative.parts
        or Path(lexical_relative.parts[0]) != Path("Originals")
    ):
        raise IntegrationWeatherRuntimeError(
            "weather copied Original is outside sandbox Originals"
        )
    current = root
    for part in lexical_relative.parts:
        current /= part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise IntegrationWeatherRuntimeError(
                f"weather copied Original path is unavailable: {current}"
            ) from exc
        if path_is_link_or_reparse(current, metadata=metadata):
            raise IntegrationWeatherRuntimeError(
                f"weather copied Original path contains a link: {current}"
            )
    try:
        resolved = candidate.resolve(strict=True)
        resolved_relative = resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise IntegrationWeatherRuntimeError(
            "weather copied Original resolves outside the sandbox"
        ) from exc
    if Path(*resolved_relative.parts) != Path(*lexical_relative.parts):
        raise IntegrationWeatherRuntimeError(
            "weather copied Original changed during containment proof"
        )
    return _file_proof(resolved)


def _verification_from_snapshot(
    workflow_id: str,
    phase: str,
    expected: Mapping[str, Any],
    observed: Mapping[str, Any],
) -> WorkflowVerification:
    passed = _plain(expected) == _plain(observed)
    return WorkflowVerification(
        workflow_id,
        phase,
        passed,
        () if passed else ("hidden project snapshot changed",),
        MappingProxyType(
            {
                "expected_sha256": _json_sha256(expected),
                "observed_sha256": _json_sha256(observed),
            }
        ),
    )


def _verification_record(value: WorkflowVerification) -> Mapping[str, Any]:
    return MappingProxyType(
        {
            "phase": value.phase,
            "passed": value.passed,
            "failures": list(value.failures),
            "evidence": _plain(value.evidence),
        }
    )


def _metadata_digest(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(
        {
            "sha256": _json_sha256(value),
            "candidate_count": len(value.get("candidates", ())),
        }
    )


def _normalize_points(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    result: list[Mapping[str, Any]] = []
    for row in value:
        if not isinstance(row, Mapping):
            return ()
        x = _number(row.get("x"))
        y = _number(row.get("y"))
        shape = row.get("shape")
        if x is None or y is None or not isinstance(shape, str):
            return ()
        result.append({"x": x, "y": y, "shape": shape})
    return tuple(result)


def _identity(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key in ("id", "object"):
            nested = value.get(key)
            if isinstance(nested, str):
                return nested.casefold()
    if isinstance(value, str):
        return value.casefold()
    return None


def _name_value(value: Any) -> str | None:
    if isinstance(value, Mapping):
        value = value.get("name")
    return value if isinstance(value, str) and value else None


def _require_guid(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 38
        or value[0] != "{"
        or value[-1] != "}"
    ):
        raise IntegrationWeatherRuntimeError(
            f"{field} is not a canonical Wwise GUID"
        )
    return value


def _type_token(value: Any) -> str:
    return "".join(
        character for character in str(value).casefold() if character.isalnum()
    )


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _json_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _plain(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


__all__ = [
    "IntegrationWeatherRuntimeError",
    "PreparedWeatherWorkflow",
    "WorkflowVerification",
    "prepare_weather_workflow",
]
