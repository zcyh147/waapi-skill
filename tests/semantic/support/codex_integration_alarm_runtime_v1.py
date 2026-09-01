"""Trusted fixture and oracle for the Alarm integration workflow.

The evaluated model receives only the rendered visible values and the closed
gateway protocol.  Direct WAAPI is retained by a runner-owned private session
for setup, readback, verification, and cleanup; it is never part of a prompt or
serialized model input.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import struct
import wave
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

from tests.semantic.support.codex_eval_protocol_v3 import (
    OPERATION_REQUEST_CONTRACT,
    V3GatewayProtocol,
    build_metadata_transaction_protocol,
)
from tests.semantic.support.codex_gateway_broker import (
    ExactArgumentAlternatives,
    ExpectedGatewayStep,
    MetadataTokenProjection,
    ResponseBinding,
    ResponseBindingOrExactArgument,
)
from tests.semantic.support.codex_version_layout_v3 import (
    get_codex_version_layout_v3,
)


ALARM_WORKFLOW_ID = "alarm_diagnose_and_repair"
ALARM_FIXTURE_ADAPTER = "alarm_reference_fixture_v1"
SUPPORTED_VERSIONS = frozenset({"2022.1", "2025.1"})
OBJECT_GET_API = "ak.wwise.core.object.get"
SET_REFERENCE_API = "ak.wwise.core.object.setReference"

ACTOR_DWU = r"\Actor-Mixer Hierarchy\Default Work Unit"
EVENT_DWU = r"\Events\Default Work Unit"
MASTER_BUS = (
    r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus"
)
ACTOR_LAB = ACTOR_DWU + r"\IntegrationLab"
ALARM_ACTOR_ROOT = ACTOR_LAB + r"\Alarm"
EVENT_LAB = EVENT_DWU + r"\IntegrationLab"
ALARM_EVENT_ROOT = EVENT_LAB + r"\Alarm"

ALARM_SOUND_PATH = ALARM_ACTOR_ROOT + r"\Generator_Alarm"
ALARM_EVENT_PATH = ALARM_EVENT_ROOT + r"\Play_Generator_Alarm"
DEAD_BUS_PATH = MASTER_BUS + r"\Diagnostic_Dead_Bus"
TARGET_BUS_PATH = MASTER_BUS + r"\SFX_Machinery"
DECOY_SOUND_PATHS = (
    ALARM_ACTOR_ROOT + r"\Generator_Alarm_Backup",
    ALARM_ACTOR_ROOT + r"\Generator_Alarms",
)
DECOY_EVENT_PATHS = (
    ALARM_EVENT_ROOT + r"\Play_Generator_Alarm_Backup",
    ALARM_EVENT_ROOT + r"\Play_Generator_Alarms",
)
DECOY_BUS_PATHS = (
    MASTER_BUS + r"\Diagnostic_Dead_Bus_Backup",
    MASTER_BUS + r"\SFX_Machinery_Legacy",
)

_GUID_RE = re.compile(
    r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$"
)
_BASE_FIELDS = ("id", "name", "type", "path", "parent", "shortId", "notes")
_SOUND_FIELDS = (
    *_BASE_FIELDS,
    "@Volume",
    "@Pitch",
    "OverrideOutput",
    "@UseMaxSoundPerInstance",
    "@MaxSoundPerInstance",
    "OutputBus",
    "activeSource",
)
_EVENT_FIELDS = _BASE_FIELDS
_ACTION_FIELDS = (*_BASE_FIELDS, "ActionType", "Target")
_SOURCE_FIELDS = (
    *_BASE_FIELDS,
    "originalFilePath",
    "audioSource:language",
)
_BUS_FIELDS = (*_BASE_FIELDS, "@Volume")
_FIXED_FIELDS = _BASE_FIELDS
_MAX_RESULT_ROWS = 32
_DIAGNOSTIC_EVENT_FIELDS = ("id", "name", "type", "path")
_DIAGNOSTIC_ACTION_FIELDS = (
    "id",
    "name",
    "type",
    "path",
    "ActionType",
    "Target",
)
_DIAGNOSTIC_SOUND_FIELDS = (
    "id",
    "name",
    "type",
    "path",
    "OverrideOutput",
    "activeSource",
    "OutputBus",
)
_DIAGNOSTIC_SOURCE_FIELDS = (
    "id",
    "name",
    "type",
    "path",
    "originalFilePath",
    "audioSource:language",
)
_DIAGNOSTIC_BUS_FIELDS = ("id", "name", "type", "path", "@Volume")


class AlarmIntegrationRuntimeError(RuntimeError):
    """The Alarm fixture, protocol, or business oracle failed closed."""


@dataclass(frozen=True, slots=True)
class AlarmFixturePaths:
    actor_dwu: str
    event_dwu: str
    master_bus: str
    actor_lab: str
    actor_root: str
    event_lab: str
    event_root: str
    sound: str
    event: str
    dead_bus: str
    target_bus: str
    decoy_sounds: tuple[str, str]
    decoy_events: tuple[str, str]
    decoy_buses: tuple[str, str]

    @property
    def owned_paths(self) -> tuple[str, ...]:
        return (
            self.actor_lab,
            self.actor_root,
            self.event_lab,
            self.event_root,
            self.sound,
            self.event,
            *self.decoy_sounds,
            *self.decoy_events,
            self.dead_bus,
            self.target_bus,
            *self.decoy_buses,
        )

    @property
    def cleanup_roots(self) -> tuple[str, ...]:
        """Top-level owned objects whose deletion removes the whole fixture."""

        return (
            self.actor_lab,
            self.event_lab,
            self.dead_bus,
            self.target_bus,
            *self.decoy_buses,
        )


def alarm_fixture_paths(version: str) -> AlarmFixturePaths:
    """Return the reviewed Alarm paths for one supported Wwise layout."""

    if version not in SUPPORTED_VERSIONS:
        raise AlarmIntegrationRuntimeError(
            f"Alarm integration version is unsupported: {version!r}"
        )
    layout = get_codex_version_layout_v3(version)
    actor_dwu = layout.containers_dwu
    master_bus = layout.main_bus
    actor_lab = actor_dwu + r"\IntegrationLab"
    actor_root = actor_lab + r"\Alarm"
    event_lab = EVENT_DWU + r"\IntegrationLab"
    event_root = event_lab + r"\Alarm"
    return AlarmFixturePaths(
        actor_dwu=actor_dwu,
        event_dwu=EVENT_DWU,
        master_bus=master_bus,
        actor_lab=actor_lab,
        actor_root=actor_root,
        event_lab=event_lab,
        event_root=event_root,
        sound=actor_root + r"\Generator_Alarm",
        event=event_root + r"\Play_Generator_Alarm",
        dead_bus=master_bus + r"\Diagnostic_Dead_Bus",
        target_bus=master_bus + r"\SFX_Machinery",
        decoy_sounds=(
            actor_root + r"\Generator_Alarm_Backup",
            actor_root + r"\Generator_Alarms",
        ),
        decoy_events=(
            event_root + r"\Play_Generator_Alarm_Backup",
            event_root + r"\Play_Generator_Alarms",
        ),
        decoy_buses=(
            master_bus + r"\Diagnostic_Dead_Bus_Backup",
            master_bus + r"\SFX_Machinery_Legacy",
        ),
    )


DirectWaapiCall = Callable[[str, Mapping[str, Any], Mapping[str, Any]], Any]


class AlarmRuntimePaths(Protocol):
    """The path subset supplied by ``ScenarioRuntime`` and fake tests."""

    scenario_root: Path
    asset_root: Path
    io_root: Path


@dataclass(frozen=True, slots=True)
class AlarmFileProof:
    path: str
    size: int
    sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size": self.size,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class AlarmObjectState:
    key: str
    object_id: str
    name: str
    object_type: str
    path: str
    parent_id: str | None
    details: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "object_id": self.object_id,
            "name": self.name,
            "object_type": self.object_type,
            "path": self.path,
            "parent_id": self.parent_id,
            "details": _plain(self.details),
        }


@dataclass(frozen=True, slots=True)
class AlarmSnapshot:
    workflow_id: str
    version: str
    objects: tuple[AlarmObjectState, ...]
    input_files: tuple[AlarmFileProof, ...]
    digest: str

    def by_key(self) -> dict[str, AlarmObjectState]:
        return {row.key: row for row in self.objects}

    def as_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "version": self.version,
            "objects": [row.as_dict() for row in self.objects],
            "input_files": [row.as_dict() for row in self.input_files],
            "digest": self.digest,
        }


@dataclass(frozen=True, slots=True)
class AlarmVerification:
    phase: str
    passed: bool
    failures: tuple[str, ...]
    before: AlarmSnapshot
    after: AlarmSnapshot | None
    changed_fields: tuple[str, ...]

    def assert_passed(self) -> None:
        if not self.passed:
            raise AlarmIntegrationRuntimeError(
                f"{self.phase} failed: " + "; ".join(self.failures)
            )


@dataclass(frozen=True, slots=True)
class AlarmCleanupProof:
    passed: bool
    already_clean: bool
    removed_paths: tuple[str, ...]
    remaining_paths: tuple[str, ...]
    failures: tuple[str, ...]

    def assert_passed(self) -> None:
        if not self.passed:
            raise AlarmIntegrationRuntimeError(
                "Alarm cleanup failed: " + "; ".join(self.failures)
            )


@dataclass(frozen=True, slots=True)
class AlarmExpectedDispatch:
    api: str
    count: int
    effect: str


@dataclass(frozen=True, slots=True)
class AlarmOracleRequirement:
    phase: str
    subject: str
    expectation: str


VerifyTurn = Callable[[int, Any | None], AlarmVerification]
VerifyFinal = Callable[[Mapping[str, Any] | None, Any | None], AlarmVerification]
Cleanup = Callable[[], AlarmCleanupProof]
Snapshot = Callable[[], AlarmSnapshot]
ObservePayload = Callable[[ExpectedGatewayStep, Mapping[str, Any]], None]


@dataclass(frozen=True, slots=True)
class PreparedAlarmIntegrationRuntime:
    """Frozen runner seam.  Do not serialize the callback fields to the model."""

    workflow_id: str
    version: str
    visible_values: Mapping[str, str]
    protocol: V3GatewayProtocol
    snapshot: Snapshot
    before_snapshot: AlarmSnapshot
    verify_turn: VerifyTurn
    verify_final: VerifyFinal
    cleanup: Cleanup
    observe_payload: ObservePayload
    expected_dispatches: tuple[AlarmExpectedDispatch, ...]
    oracle_requirements: tuple[AlarmOracleRequirement, ...]
    operation_request: Mapping[str, Any]


def prepare_alarm_integration_runtime(
    workflow: Any,
    scenario: Any,
    *,
    version: str,
    paths: AlarmRuntimePaths,
    direct_call: DirectWaapiCall,
) -> PreparedAlarmIntegrationRuntime:
    """Materialize one Alarm fixture and return its closed three-turn runtime."""

    _validate_reviewed_inputs(workflow, scenario, version, direct_call)
    scenario_root, asset_root, _io_root = _validate_runtime_paths(paths)
    fixture_paths = alarm_fixture_paths(version)
    backend = _ClosedAlarmBackend(direct_call)
    session = _AlarmFixtureSession(
        backend=backend,
        version=version,
        fixture_paths=fixture_paths,
        scenario_root=scenario_root,
        asset_root=asset_root,
    )
    try:
        before, operation_request = session.prepare()
        protocol = _alarm_protocol(
            fixture_paths=fixture_paths,
            operation_request=operation_request,
        )
    except BaseException as exc:
        try:
            cleanup_proof = session.cleanup()
        except BaseException as cleanup_exc:
            raise AlarmIntegrationRuntimeError(
                "Alarm fixture preparation failed and cleanup raised "
                f"{type(cleanup_exc).__name__}: {cleanup_exc}"
            ) from exc
        if not cleanup_proof.passed:
            cleanup_detail = "; ".join(
                (*cleanup_proof.failures, *cleanup_proof.remaining_paths)
            )
            raise AlarmIntegrationRuntimeError(
                "Alarm fixture preparation failed and cleanup was incomplete: "
                f"{cleanup_detail}"
            ) from exc
        raise

    return PreparedAlarmIntegrationRuntime(
        workflow_id=ALARM_WORKFLOW_ID,
        version=version,
        visible_values=MappingProxyType(
            {
                "alarm_event_path": fixture_paths.event,
                "alarm_target_bus_path": fixture_paths.target_bus,
            }
        ),
        protocol=protocol,
        snapshot=session.snapshot,
        before_snapshot=before,
        verify_turn=session.verify_turn,
        verify_final=session.verify_final,
        cleanup=session.cleanup,
        observe_payload=session.observe_payload,
        expected_dispatches=(
            AlarmExpectedDispatch(
                SET_REFERENCE_API,
                1,
                "replace only Generator_Alarm.OutputBus with SFX_Machinery",
            ),
        ),
        oracle_requirements=_oracle_requirements(),
        operation_request=_freeze_json(operation_request),
    )


class _ClosedAlarmBackend:
    """Fixed runner-only WAAPI calls with no generic public dispatch method."""

    _CREATE_TYPES = frozenset({"Folder", "ActorMixer", "Bus"})

    def __init__(self, call: DirectWaapiCall) -> None:
        if not callable(call):
            raise TypeError("direct_call must be callable")
        self.__call = call

    def read_path(
        self,
        path: str,
        *,
        fields: Sequence[str],
    ) -> tuple[Mapping[str, Any], ...]:
        return self._read(
            {"from": {"path": [_wwise_path(path, "path")]}},
            fields,
            "object.get path",
        )

    def read_id(
        self,
        object_id: str,
        *,
        fields: Sequence[str],
    ) -> tuple[Mapping[str, Any], ...]:
        return self._read(
            {"from": {"id": [_guid(object_id, "object id")]}},
            fields,
            "object.get id",
        )

    def read_children(
        self,
        object_id: str,
        *,
        fields: Sequence[str],
    ) -> tuple[Mapping[str, Any], ...]:
        return self._read(
            {
                "from": {"id": [_guid(object_id, "parent id")]},
                "transform": [{"select": ["children"]}],
            },
            fields,
            "object.get children",
        )

    def _read(
        self,
        args: Mapping[str, Any],
        fields: Sequence[str],
        label: str,
    ) -> tuple[Mapping[str, Any], ...]:
        return_fields = _return_fields(fields)
        result = self.__call(
            OBJECT_GET_API,
            dict(args),
            {"return": list(return_fields)},
        )
        if not isinstance(result, Mapping):
            raise AlarmIntegrationRuntimeError(f"{label} result is not an object")
        rows = result.get("return")
        if not isinstance(rows, list) or len(rows) > _MAX_RESULT_ROWS:
            raise AlarmIntegrationRuntimeError(f"{label} rows are invalid or unbounded")
        if any(not isinstance(row, Mapping) for row in rows):
            raise AlarmIntegrationRuntimeError(f"{label} contains a non-object row")
        return tuple(dict(row) for row in rows)

    def create(self, *, parent: str, object_type: str, name: str) -> str:
        if object_type not in self._CREATE_TYPES:
            raise AlarmIntegrationRuntimeError(
                f"Alarm setup type is not closed: {object_type!r}"
            )
        result = self.__call(
            "ak.wwise.core.object.create",
            {
                "parent": _wwise_path(parent, "parent"),
                "type": object_type,
                "name": _segment(name, "name"),
                "onNameConflict": "fail",
                "autoAddToSourceControl": False,
            },
            {},
        )
        if not isinstance(result, Mapping):
            raise AlarmIntegrationRuntimeError("object.create result is not an object")
        return _guid(result.get("id"), "created object id")

    def import_sound_event(
        self,
        *,
        audio_file: Path,
        sound_path: str,
        event_path: str,
    ) -> None:
        proof = _file_proof(audio_file)
        parent, separator, name = sound_path.rpartition("\\")
        if not separator or not parent:
            raise AlarmIntegrationRuntimeError("Alarm Sound path has no parent")
        event_value = _wwise_path(event_path, "event path") + "@Play"
        result = self.__call(
            "ak.wwise.core.audio.import",
            {
                "importOperation": "createNew",
                "imports": [
                    {
                        "audioFile": proof.path,
                        "objectPath": (
                            f"{_wwise_path(parent, 'sound parent')}"
                            f"\\<Sound SFX>{_segment(name, 'sound name')}"
                        ),
                        "objectType": "Sound SFX",
                        "importLanguage": "SFX",
                        "event": event_value,
                        "@IsStreamingEnabled": True,
                    }
                ],
                "autoAddToSourceControl": False,
            },
            {"return": ["id", "name", "type", "path", "parent"]},
        )
        if not isinstance(result, Mapping) or not isinstance(
            result.get("objects"), list
        ):
            raise AlarmIntegrationRuntimeError("audio.import result is invalid")

    def set_property(self, object_id: str, name: str, value: Any) -> None:
        if name not in {
            "Volume",
            "Pitch",
            "OverrideOutput",
            "UseMaxSoundPerInstance",
            "MaxSoundPerInstance",
        }:
            raise AlarmIntegrationRuntimeError(
                f"Alarm setup property is not closed: {name!r}"
            )
        if value is None or isinstance(value, (dict, list, tuple)):
            raise AlarmIntegrationRuntimeError("Alarm setup property value is invalid")
        result = self.__call(
            "ak.wwise.core.object.setProperty",
            {
                "object": _guid(object_id, "property object id"),
                "property": name,
                "value": value,
            },
            {},
        )
        if result is not None and not isinstance(result, Mapping):
            raise AlarmIntegrationRuntimeError(
                "object.setProperty result must be an object or null"
            )

    def set_reference(
        self,
        object_id: str,
        reference: str,
        target_id: str,
    ) -> None:
        if reference != "OutputBus":
            raise AlarmIntegrationRuntimeError(
                "Alarm setup may set only the OutputBus reference"
            )
        result = self.__call(
            SET_REFERENCE_API,
            {
                "object": _guid(object_id, "reference object id"),
                "reference": reference,
                "value": _guid(target_id, "reference target id"),
            },
            {},
        )
        if result is not None and not isinstance(result, Mapping):
            raise AlarmIntegrationRuntimeError(
                "object.setReference result must be an object or null"
            )

    def save(self) -> None:
        result = self.__call("ak.wwise.core.project.save", {}, {})
        if result is not None and not isinstance(result, Mapping):
            raise AlarmIntegrationRuntimeError(
                "project.save result must be an object or null"
            )

    def delete(self, object_id: str) -> None:
        result = self.__call(
            "ak.wwise.core.object.delete",
            {"object": _guid(object_id, "cleanup object id")},
            {},
        )
        if result is not None and not isinstance(result, Mapping):
            raise AlarmIntegrationRuntimeError(
                "object.delete result must be an object or null"
            )


class _AlarmFixtureSession:
    def __init__(
        self,
        *,
        backend: _ClosedAlarmBackend,
        version: str,
        fixture_paths: AlarmFixturePaths,
        scenario_root: Path,
        asset_root: Path,
    ) -> None:
        self.backend = backend
        self.version = version
        self.fixture_paths = fixture_paths
        self.scenario_root = scenario_root
        self.asset_root = asset_root
        self.before: AlarmSnapshot | None = None
        self._top_level_ids: list[tuple[str, str]] = []
        self._input_files: list[Path] = []
        self._cleaned = False

    def prepare(self) -> tuple[AlarmSnapshot, dict[str, Any]]:
        if self.before is not None or self._cleaned:
            raise AlarmIntegrationRuntimeError("Alarm runtime is single-use")
        fixture = self.fixture_paths
        for path in fixture.owned_paths:
            if self.backend.read_path(path, fields=_BASE_FIELDS):
                raise AlarmIntegrationRuntimeError(
                    f"scenario-owned Alarm path already exists: {path}"
                )

        actor_lab_id = self.backend.create(
            parent=fixture.actor_dwu,
            object_type="Folder",
            name="IntegrationLab",
        )
        self._top_level_ids.append((fixture.actor_lab, actor_lab_id))
        self.backend.create(
            parent=fixture.actor_lab,
            object_type="ActorMixer",
            name="Alarm",
        )
        event_lab_id = self.backend.create(
            parent=fixture.event_dwu,
            object_type="Folder",
            name="IntegrationLab",
        )
        self._top_level_ids.append((fixture.event_lab, event_lab_id))
        self.backend.create(
            parent=fixture.event_lab,
            object_type="Folder",
            name="Alarm",
        )

        bus_specs = (
            (fixture.dead_bus, "Diagnostic_Dead_Bus", -96.0),
            (fixture.target_bus, "SFX_Machinery", 0.0),
            (fixture.decoy_buses[0], "Diagnostic_Dead_Bus_Backup", -72.0),
            (fixture.decoy_buses[1], "SFX_Machinery_Legacy", -6.0),
        )
        bus_ids: dict[str, str] = {}
        for path, name, volume in bus_specs:
            bus_id = self.backend.create(
                parent=fixture.master_bus,
                object_type="Bus",
                name=name,
            )
            self._top_level_ids.append((path, bus_id))
            self.backend.set_property(bus_id, "Volume", volume)
            bus_ids[path] = bus_id

        source_root = self.asset_root / "alarm-fixture"
        source_root.mkdir(parents=True, exist_ok=False)
        media_specs = (
            (
                fixture.sound,
                fixture.event,
                "generator_alarm.wav",
                431,
                397,
            ),
            (
                fixture.decoy_sounds[0],
                fixture.decoy_events[0],
                "generator_alarm_backup.wav",
                467,
                457,
            ),
            (
                fixture.decoy_sounds[1],
                fixture.decoy_events[1],
                "generator_alarms.wav",
                503,
                521,
            ),
        )
        for sound_path, event_path, file_name, duration_ms, frequency_hz in media_specs:
            wav_path = source_root / file_name
            _write_deterministic_wav(
                wav_path,
                duration_ms=duration_ms,
                frequency_hz=frequency_hz,
            )
            self._input_files.append(wav_path)
            self.backend.import_sound_event(
                audio_file=wav_path,
                sound_path=sound_path,
                event_path=event_path,
            )

        primary_sound_id = _one_id(
            self.backend.read_path(fixture.sound, fields=_SOUND_FIELDS),
            fixture.sound,
        )
        self._configure_sound(
            primary_sound_id,
            volume=0.0,
            pitch=0.0,
            maximum_instances=3,
            output_bus_id=bus_ids[fixture.dead_bus],
        )
        for index, sound_path in enumerate(fixture.decoy_sounds):
            sound_id = _one_id(
                self.backend.read_path(sound_path, fields=_SOUND_FIELDS),
                sound_path,
            )
            self._configure_sound(
                sound_id,
                volume=-3.0 - index,
                pitch=1.0 + index,
                maximum_instances=4 + index,
                output_bus_id=bus_ids[fixture.decoy_buses[index]],
            )
        self.backend.save()

        before = self._capture_snapshot()
        _validate_alarm_baseline(before)
        self.before = before
        operation_request = {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": self.version,
            "operation": "object.setReference",
            "arguments": {
                "object": {
                    "kind": "id",
                    "value": before.by_key()["sound"].object_id,
                },
                "reference": "OutputBus",
                "target": {
                    "kind": "id",
                    "value": before.by_key()["target_bus"].object_id,
                },
            },
        }
        return before, operation_request

    def _configure_sound(
        self,
        sound_id: str,
        *,
        volume: float,
        pitch: float,
        maximum_instances: int,
        output_bus_id: str,
    ) -> None:
        self.backend.set_property(sound_id, "Volume", volume)
        self.backend.set_property(sound_id, "Pitch", pitch)
        self.backend.set_property(sound_id, "UseMaxSoundPerInstance", True)
        self.backend.set_property(
            sound_id,
            "MaxSoundPerInstance",
            maximum_instances,
        )
        self.backend.set_property(sound_id, "OverrideOutput", True)
        self.backend.set_reference(sound_id, "OutputBus", output_bus_id)

    def _capture_snapshot(self) -> AlarmSnapshot:
        fixture = self.fixture_paths
        rows: list[AlarmObjectState] = []
        fixed_specs = (
            ("control_actor_dwu", fixture.actor_dwu, "fixed"),
            ("control_event_dwu", fixture.event_dwu, "fixed"),
            ("control_master_bus", fixture.master_bus, "bus"),
            ("actor_lab", fixture.actor_lab, "fixed"),
            ("actor_root", fixture.actor_root, "fixed"),
            ("event_lab", fixture.event_lab, "fixed"),
            ("event_root", fixture.event_root, "fixed"),
            ("event", fixture.event, "event"),
            ("sound", fixture.sound, "sound"),
            ("dead_bus", fixture.dead_bus, "bus"),
            ("target_bus", fixture.target_bus, "bus"),
            ("decoy_bus_1", fixture.decoy_buses[0], "bus"),
            ("decoy_bus_2", fixture.decoy_buses[1], "bus"),
            ("decoy_event_1", fixture.decoy_events[0], "event"),
            ("decoy_event_2", fixture.decoy_events[1], "event"),
            ("decoy_sound_1", fixture.decoy_sounds[0], "sound"),
            ("decoy_sound_2", fixture.decoy_sounds[1], "sound"),
        )
        fixed_by_key: dict[str, AlarmObjectState] = {}
        for key, path, kind in fixed_specs:
            fields = _fields_for_kind(kind)
            raw = _one_row(self.backend.read_path(path, fields=fields), path)
            state = _state(key, raw, kind=kind)
            rows.append(state)
            fixed_by_key[key] = state

        graph_specs = (
            ("event", "action", "sound", "source"),
            ("decoy_event_1", "decoy_action_1", "decoy_sound_1", "decoy_source_1"),
            ("decoy_event_2", "decoy_action_2", "decoy_sound_2", "decoy_source_2"),
        )
        for event_key, action_key, sound_key, source_key in graph_specs:
            event = fixed_by_key[event_key]
            action_raw = _one_row(
                self.backend.read_children(
                    event.object_id,
                    fields=_ACTION_FIELDS,
                ),
                f"{event.path} direct children",
            )
            action = _state(action_key, action_raw, kind="action")
            rows.append(action)
            sound = fixed_by_key[sound_key]
            source_id = sound.details.get("active_source_id")
            if not isinstance(source_id, str):
                raise AlarmIntegrationRuntimeError(
                    f"{sound.path} lacks an active AudioFileSource identity"
                )
            source_raw = _one_row(
                self.backend.read_id(source_id, fields=_SOURCE_FIELDS),
                f"{sound.path} active source",
            )
            source = _state(source_key, source_raw, kind="source")
            rows.append(source)

        proofs = tuple(_file_proof(path) for path in self._input_files)
        serial = {
            "workflow_id": ALARM_WORKFLOW_ID,
            "version": self.version,
            "objects": [row.as_dict() for row in rows],
            "input_files": [row.as_dict() for row in proofs],
        }
        return AlarmSnapshot(
            workflow_id=ALARM_WORKFLOW_ID,
            version=self.version,
            objects=tuple(rows),
            input_files=proofs,
            digest=_sha256(serial),
        )

    def verify_turn(
        self,
        turn_index: int,
        _result: Any | None = None,
    ) -> AlarmVerification:
        if type(turn_index) is not int or turn_index not in {1, 2}:
            raise AlarmIntegrationRuntimeError(
                "Alarm turn verification supports only diagnosis turn 1 "
                "and preview turn 2"
            )
        before = self._require_before()
        phase = "diagnosis_read_only" if turn_index == 1 else "preview_no_change"
        try:
            after = self._capture_snapshot()
        except AlarmIntegrationRuntimeError as exc:
            return AlarmVerification(
                phase,
                False,
                (str(exc),),
                before,
                None,
                (),
            )
        failures = () if after == before else (
            f"turn {turn_index} changed the sealed Alarm snapshot",
        )
        return AlarmVerification(
            phase,
            not failures,
            failures,
            before,
            after,
            _changed_fields(before, after),
        )

    def snapshot(self) -> AlarmSnapshot:
        """Capture the current closed graph for runner-owned observation."""

        self._require_before()
        return self._capture_snapshot()

    def observe_payload(
        self,
        step: ExpectedGatewayStep,
        payload: Mapping[str, Any],
    ) -> None:
        """Validate every agent-visible diagnostic row against the sealed graph."""

        if not step.name.startswith("diag."):
            return
        before = self._require_before()
        if (
            step.subcommand != "query-object"
            or payload.get("ok") is not True
            or payload.get("command") != "query-object"
        ):
            raise AlarmIntegrationRuntimeError(
                f"{step.name} did not return one successful bounded query-object payload"
            )
        objects = payload.get("objects")
        count = payload.get("count")
        if (
            not isinstance(objects, list)
            or type(count) is not int
            or count != len(objects)
            or len(objects) > _MAX_RESULT_ROWS
            or any(not isinstance(row, Mapping) for row in objects)
        ):
            raise AlarmIntegrationRuntimeError(
                f"{step.name} returned malformed or unbounded diagnostic rows"
            )

        rows = before.by_key()
        expected = {
            "diag.event": ("event", "event"),
            "diag.action": ("action", "action"),
            "diag.sound": ("sound", "sound"),
            "diag.source": ("source", "source"),
            "diag.dead_bus": ("dead_bus", "bus"),
            "diag.target_bus": ("target_bus", "bus"),
        }
        try:
            key, kind = expected[step.name]
        except KeyError as exc:
            raise AlarmIntegrationRuntimeError(
                f"unexpected Alarm diagnostic step: {step.name}"
            ) from exc
        if len(objects) != 1:
            raise AlarmIntegrationRuntimeError(
                f"{step.name} must resolve exactly one object"
            )
        if _diagnostic_projection(objects[0], kind=kind) != (
            _diagnostic_projection_from_state(rows[key], kind=kind)
        ):
            raise AlarmIntegrationRuntimeError(
                f"{step.name} differs from the sealed {key} evidence"
            )

    def verify_final(
        self,
        _gateway_payload: Mapping[str, Any] | None = None,
        _result: Any | None = None,
    ) -> AlarmVerification:
        before = self._require_before()
        try:
            after = self._capture_snapshot()
        except AlarmIntegrationRuntimeError as exc:
            return AlarmVerification(
                "after_repair",
                False,
                (str(exc),),
                before,
                None,
                (),
            )
        failures = _final_failures(before, after)
        return AlarmVerification(
            "after_repair",
            not failures,
            tuple(failures),
            before,
            after,
            _changed_fields(before, after),
        )

    def cleanup(self) -> AlarmCleanupProof:
        if self._cleaned:
            return AlarmCleanupProof(True, True, (), (), ())
        failures: list[str] = []
        removed: list[str] = []
        cleanup_targets = list(self._top_level_ids)
        known_ids = {object_id.casefold() for _path, object_id in cleanup_targets}
        for path in self.fixture_paths.cleanup_roots:
            try:
                rows = self.backend.read_path(path, fields=("id", "path"))
            except BaseException as exc:
                failures.append(
                    f"{path} recovery readback: {type(exc).__name__}: {exc}"
                )
                continue
            if not rows:
                continue
            try:
                recovered_id = _one_id(rows, f"{path} cleanup recovery")
            except BaseException as exc:
                failures.append(
                    f"{path} recovery identity: {type(exc).__name__}: {exc}"
                )
                continue
            if recovered_id.casefold() not in known_ids:
                cleanup_targets.append((path, recovered_id))
                known_ids.add(recovered_id.casefold())

        for path, object_id in reversed(cleanup_targets):
            try:
                self.backend.delete(object_id)
            except BaseException as exc:  # cleanup must preserve every failure
                failures.append(f"{path}: {type(exc).__name__}: {exc}")
            else:
                removed.append(path)
        if cleanup_targets:
            try:
                self.backend.save()
            except BaseException as exc:
                failures.append(f"project.save: {type(exc).__name__}: {exc}")

        remaining: list[str] = []
        for path in self.fixture_paths.owned_paths:
            try:
                present = bool(self.backend.read_path(path, fields=_BASE_FIELDS))
            except BaseException as exc:
                failures.append(f"{path} readback: {type(exc).__name__}: {exc}")
                present = True
            if present:
                remaining.append(path)

        source_root = self.asset_root / "alarm-fixture"
        if source_root.exists() or source_root.is_symlink():
            try:
                if source_root.is_symlink():
                    raise AlarmIntegrationRuntimeError(
                        "Alarm source root became a symlink"
                    )
                for child in source_root.iterdir():
                    metadata = os.lstat(child)
                    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(
                        metadata.st_mode
                    ):
                        raise AlarmIntegrationRuntimeError(
                            f"unexpected Alarm source entry: {child}"
                        )
                    child.unlink()
                source_root.rmdir()
            except BaseException as exc:
                failures.append(
                    f"local assets: {type(exc).__name__}: {exc}"
                )
        self._cleaned = not failures and not remaining
        return AlarmCleanupProof(
            passed=self._cleaned,
            already_clean=False,
            removed_paths=tuple(removed),
            remaining_paths=tuple(remaining),
            failures=tuple(failures),
        )

    def _require_before(self) -> AlarmSnapshot:
        if self.before is None:
            raise AlarmIntegrationRuntimeError("Alarm fixture was not prepared")
        if self._cleaned:
            raise AlarmIntegrationRuntimeError("Alarm fixture is already clean")
        return self.before


def _alarm_protocol(
    *,
    fixture_paths: AlarmFixturePaths,
    operation_request: Mapping[str, Any],
) -> V3GatewayProtocol:
    diagnostic_steps = (
        _query_step(
            "diag.event",
            source=("--path", fixture_paths.event),
            take=None,
            fields=_DIAGNOSTIC_EVENT_FIELDS,
        ),
        _query_step(
            "diag.action",
            source=(
                ExactArgumentAlternatives(("--object-id", "--path")),
                ResponseBindingOrExactArgument(
                    binding=ResponseBinding("diag.event", "/objects/0/id"),
                    exact_values=(fixture_paths.event,),
                ),
            ),
            selects=("children",),
            take=100,
            fields=_DIAGNOSTIC_ACTION_FIELDS,
        ),
        _query_step(
            "diag.sound",
            source=(
                "--object-id",
                ResponseBinding("diag.action", "/objects/0/target/id"),
            ),
            take=None,
            fields=_DIAGNOSTIC_SOUND_FIELDS,
        ),
        _query_step(
            "diag.source",
            source=(
                "--object-id",
                ResponseBinding("diag.sound", "/objects/0/active_source/id"),
            ),
            take=None,
            fields=_DIAGNOSTIC_SOURCE_FIELDS,
        ),
        _query_step(
            "diag.dead_bus",
            source=(
                "--object-id",
                ResponseBinding("diag.sound", "/objects/0/output_bus/id"),
            ),
            take=None,
            fields=_DIAGNOSTIC_BUS_FIELDS,
        ),
        _query_step(
            "diag.target_bus",
            source=("--path", fixture_paths.target_bus),
            take=None,
            fields=_DIAGNOSTIC_BUS_FIELDS,
        ),
    )
    request_arguments = operation_request.get("arguments")
    object_selector = (
        request_arguments.get("object")
        if isinstance(request_arguments, Mapping)
        else None
    )
    object_identity = (
        object_selector.get("value")
        if isinstance(object_selector, Mapping)
        and object_selector.get("kind") == "id"
        else None
    )
    if not isinstance(object_identity, str) or not object_identity:
        raise AlarmIntegrationRuntimeError(
            "Alarm transaction metadata lacks its exact Sound identity"
        )
    transaction = build_metadata_transaction_protocol(
        (operation_request,),
        object_type="Sound",
        object_identity=object_identity,
        metadata_queries=("output bus",),
        required_tokens=("OutputBus",),
        expected_required_token_projection=(
            MetadataTokenProjection("OutputBus", "reference", ""),
        ),
        schema_first=True,
    )
    steps = (*diagnostic_steps, *transaction.steps)
    diagnostic_count = len(diagnostic_steps)
    return V3GatewayProtocol(
        steps=steps,
        commutative_read_only_step_groups=(
            ("diag.source", "diag.dead_bus", "diag.target_bus"),
        ),
        turn_prefix_counts=(
            diagnostic_count,
            diagnostic_count + transaction.turn_prefix_counts[0],
            diagnostic_count + transaction.turn_prefix_counts[1],
        ),
    )


def _query_step(
    name: str,
    *,
    source: tuple[str, Any],
    take: int | None,
    fields: Sequence[str],
    selects: Sequence[str] = (),
):
    arguments: list[Any] = ["query-object", source[0], source[1]]
    for select in selects:
        arguments.extend(("--select", select))
    if take is not None:
        arguments.extend(("--take", str(take)))
    for field in fields:
        arguments.extend(("--return-field", field))
    return ExpectedGatewayStep(
        name=name,
        subcommand="query-object",
        arguments=tuple(arguments[1:]),
    )


def _oracle_requirements() -> tuple[AlarmOracleRequirement, ...]:
    return (
        AlarmOracleRequirement(
            "diagnosis",
            "event",
            "Play_Generator_Alarm resolves once and keeps its GUID and path",
        ),
        AlarmOracleRequirement(
            "diagnosis",
            "action",
            (
                "the Event has one direct Action, ActionType is Play, and its "
                "Target is the exact Generator_Alarm GUID"
            ),
        ),
        AlarmOracleRequirement(
            "diagnosis",
            "sound",
            (
                "Generator_Alarm has Volume=0, OverrideOutput=true, one active "
                "AudioFileSource, and OutputBus=Diagnostic_Dead_Bus"
            ),
        ),
        AlarmOracleRequirement(
            "diagnosis",
            "audio_source",
            "the active source is an AudioFileSource parented by Generator_Alarm",
        ),
        AlarmOracleRequirement(
            "diagnosis",
            "buses",
            (
                "Diagnostic_Dead_Bus is -96 dB and SFX_Machinery is 0 dB; "
                "similarly named buses are excluded"
            ),
        ),
        AlarmOracleRequirement(
            "turn_1",
            "read_only_snapshot",
            "the complete snapshot after diagnosis is byte-for-byte unchanged",
        ),
        AlarmOracleRequirement(
            "preview",
            "preview_snapshot",
            "operation-schema and preview do not change any Wwise object",
        ),
        AlarmOracleRequirement(
            "after",
            "repair_delta",
            (
                "only Generator_Alarm.OutputBus changes to SFX_Machinery; all "
                "GUIDs, properties, controls, chain objects, and decoys remain exact"
            ),
        ),
        AlarmOracleRequirement(
            "cleanup",
            "owned_state",
            "all scenario-owned Wwise objects and local WAV files are absent",
        ),
    )


def _validate_reviewed_inputs(
    workflow: Any,
    scenario: Any,
    version: str,
    direct_call: DirectWaapiCall,
) -> None:
    if version not in SUPPORTED_VERSIONS:
        raise AlarmIntegrationRuntimeError(
            f"Alarm integration version is unsupported: {version!r}"
        )
    if not callable(direct_call):
        raise TypeError("direct_call must be callable")
    if getattr(workflow, "id", None) != ALARM_WORKFLOW_ID:
        raise AlarmIntegrationRuntimeError("wrong integration workflow for Alarm")
    if version not in tuple(getattr(workflow, "versions", ())):
        raise AlarmIntegrationRuntimeError("Alarm workflow/version are misbound")
    fixture = getattr(workflow, "fixture", None)
    if getattr(fixture, "adapter", None) != ALARM_FIXTURE_ADAPTER:
        raise AlarmIntegrationRuntimeError("Alarm fixture adapter drifted")
    transactions = tuple(getattr(workflow, "transactions", ()))
    if len(transactions) != 1:
        raise AlarmIntegrationRuntimeError("Alarm workflow requires one transaction")
    transaction = transactions[0]
    if (
        getattr(transaction, "index", None) != 1
        or getattr(transaction, "operation", None) != "object.setReference"
        or getattr(transaction, "api", None) != SET_REFERENCE_API
        or getattr(transaction, "preview_turn", None) != 2
        or getattr(transaction, "confirmation_turn", None) != 3
    ):
        raise AlarmIntegrationRuntimeError("Alarm transaction topology drifted")
    turns = tuple(getattr(workflow, "turns", ()))
    if tuple(getattr(turn, "kind", None) for turn in turns) != (
        "diagnosis_request",
        "change_request",
        "confirmation",
    ):
        raise AlarmIntegrationRuntimeError("Alarm turn topology drifted")
    visible_input_names = tuple(
        getattr(item, "name", None)
        for item in getattr(workflow, "visible_inputs", ())
    )
    if visible_input_names != ("alarm_event_path", "alarm_target_bus_path"):
        raise AlarmIntegrationRuntimeError("Alarm visible inputs drifted")
    if (
        getattr(scenario, "scenario_family", None) != ALARM_WORKFLOW_ID
        or getattr(scenario, "api", None) != SET_REFERENCE_API
        or tuple(getattr(scenario, "versions", ())) != (version,)
    ):
        raise AlarmIntegrationRuntimeError("Alarm scenario proxy is misbound")


def _validate_runtime_paths(
    paths: AlarmRuntimePaths,
) -> tuple[Path, Path, Path]:
    values: list[Path] = []
    for name in ("scenario_root", "asset_root", "io_root"):
        raw = getattr(paths, name, None)
        if raw is None:
            raise AlarmIntegrationRuntimeError(
                f"Alarm runtime paths omit {name}"
            )
        path = Path(os.path.abspath(os.fspath(Path(raw).expanduser())))
        values.append(path)
    scenario_root, asset_root, io_root = values
    _real_directory(scenario_root, "scenario_root")
    _real_directory(asset_root, "asset_root")
    _real_directory(io_root, "io_root")
    for name, path in (("asset_root", asset_root), ("io_root", io_root)):
        if path == scenario_root or scenario_root not in path.parents:
            raise AlarmIntegrationRuntimeError(
                f"{name} must be a strict descendant of scenario_root"
            )
    return scenario_root, asset_root, io_root


def _real_directory(path: Path, name: str) -> None:
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise AlarmIntegrationRuntimeError(
            f"{name} cannot be inspected: {exc}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise AlarmIntegrationRuntimeError(f"{name} must be a real directory")


def _validate_alarm_baseline(snapshot: AlarmSnapshot) -> None:
    rows = snapshot.by_key()
    required = {
        "control_actor_dwu",
        "control_event_dwu",
        "control_master_bus",
        "actor_lab",
        "actor_root",
        "event_lab",
        "event_root",
        "event",
        "action",
        "sound",
        "source",
        "dead_bus",
        "target_bus",
        "decoy_bus_1",
        "decoy_bus_2",
        "decoy_event_1",
        "decoy_event_2",
        "decoy_action_1",
        "decoy_action_2",
        "decoy_sound_1",
        "decoy_sound_2",
        "decoy_source_1",
        "decoy_source_2",
    }
    if set(rows) != required or len(rows) != len(snapshot.objects):
        raise AlarmIntegrationRuntimeError(
            "Alarm snapshot keys are incomplete or duplicated"
        )
    event, action, sound, source = (
        rows["event"],
        rows["action"],
        rows["sound"],
        rows["source"],
    )
    if event.object_type != "Event":
        raise AlarmIntegrationRuntimeError("Alarm Event has the wrong type")
    if (
        action.object_type != "Action"
        or action.parent_id != event.object_id
        or action.details.get("action_type") != 1
        or action.details.get("target_id") != sound.object_id
    ):
        raise AlarmIntegrationRuntimeError(
            "Alarm Event does not have one exact Play Action to Generator_Alarm"
        )
    if not sound.object_type.startswith("Sound"):
        raise AlarmIntegrationRuntimeError("Generator_Alarm is not a Sound")
    if (
        sound.details.get("volume") not in {0, 0.0}
        or sound.details.get("pitch") not in {0, 0.0}
        or sound.details.get("override_output") is not True
        or sound.details.get("use_max_sound_per_instance") is not True
        or sound.details.get("max_sound_per_instance") != 3
        or sound.details.get("output_bus_id") != rows["dead_bus"].object_id
        or sound.details.get("active_source_id") != source.object_id
    ):
        raise AlarmIntegrationRuntimeError(
            "Generator_Alarm baseline properties or references drifted"
        )
    if (
        source.object_type not in {"AudioFileSource", "Audio Source"}
        or source.parent_id != sound.object_id
    ):
        raise AlarmIntegrationRuntimeError(
            "Generator_Alarm active source is not its AudioFileSource"
        )
    if (
        rows["dead_bus"].object_type != "Bus"
        or rows["dead_bus"].details.get("volume") != -96.0
        or rows["target_bus"].object_type != "Bus"
        or rows["target_bus"].details.get("volume") not in {0, 0.0}
    ):
        raise AlarmIntegrationRuntimeError("Alarm Bus level baseline drifted")
    primary_ids = {
        event.object_id,
        action.object_id,
        sound.object_id,
        source.object_id,
        rows["dead_bus"].object_id,
        rows["target_bus"].object_id,
    }
    decoy_ids = {
        rows[key].object_id
        for key in rows
        if key.startswith("decoy_")
    }
    if primary_ids & decoy_ids or len(decoy_ids) != 10:
        raise AlarmIntegrationRuntimeError(
            "Alarm primary and decoy identities are not distinct"
        )
    for index in (1, 2):
        decoy_event = rows[f"decoy_event_{index}"]
        decoy_action = rows[f"decoy_action_{index}"]
        decoy_sound = rows[f"decoy_sound_{index}"]
        decoy_source = rows[f"decoy_source_{index}"]
        if (
            decoy_action.parent_id != decoy_event.object_id
            or decoy_action.details.get("action_type") != 1
            or decoy_action.details.get("target_id") != decoy_sound.object_id
            or decoy_sound.details.get("active_source_id")
            != decoy_source.object_id
            or decoy_sound.details.get("output_bus_id")
            != rows[f"decoy_bus_{index}"].object_id
        ):
            raise AlarmIntegrationRuntimeError(
                f"Alarm decoy graph {index} is malformed"
            )


def _final_failures(
    before: AlarmSnapshot,
    after: AlarmSnapshot,
) -> list[str]:
    failures: list[str] = []
    if (
        before.workflow_id != after.workflow_id
        or before.version != after.version
        or before.input_files != after.input_files
    ):
        failures.append("Alarm workflow identity or immutable inputs changed")
    before_rows = before.by_key()
    after_rows = after.by_key()
    if set(before_rows) != set(after_rows):
        failures.append("Alarm object key set changed")
        return failures
    target_id = before_rows["target_bus"].object_id
    dead_id = before_rows["dead_bus"].object_id
    for key in before_rows:
        old = before_rows[key]
        new = after_rows[key]
        if key != "sound":
            if old != new:
                failures.append(f"{key}: protected object changed")
            continue
        if (
            old.key != new.key
            or old.object_id != new.object_id
            or old.name != new.name
            or old.object_type != new.object_type
            or old.path != new.path
            or old.parent_id != new.parent_id
        ):
            failures.append("sound: identity or hierarchy changed")
        old_details = _plain(old.details)
        new_details = _plain(new.details)
        old_bus = old_details.pop("output_bus_id", None)
        new_bus = new_details.pop("output_bus_id", None)
        if old_bus != dead_id:
            failures.append("sound: before OutputBus was not Diagnostic_Dead_Bus")
        if new_bus != target_id:
            failures.append("sound: OutputBus is not SFX_Machinery")
        if old_details != new_details:
            failures.append("sound: a non-OutputBus field changed")
    return failures


def _changed_fields(
    before: AlarmSnapshot,
    after: AlarmSnapshot,
) -> tuple[str, ...]:
    changed: list[str] = []
    before_rows = before.by_key()
    after_rows = after.by_key()
    for key in sorted(set(before_rows) | set(after_rows)):
        old = before_rows.get(key)
        new = after_rows.get(key)
        if old is None or new is None:
            changed.append(f"{key}.__presence__")
            continue
        for field in (
            "object_id",
            "name",
            "object_type",
            "path",
            "parent_id",
        ):
            if getattr(old, field) != getattr(new, field):
                changed.append(f"{key}.{field}")
        old_details = _plain(old.details)
        new_details = _plain(new.details)
        for field in sorted(set(old_details) | set(new_details)):
            if old_details.get(field) != new_details.get(field):
                changed.append(f"{key}.details.{field}")
    if before.input_files != after.input_files:
        changed.append("input_files")
    return tuple(changed)


def _fields_for_kind(kind: str) -> tuple[str, ...]:
    values = {
        "fixed": _FIXED_FIELDS,
        "event": _EVENT_FIELDS,
        "sound": _SOUND_FIELDS,
        "bus": _BUS_FIELDS,
        "action": _ACTION_FIELDS,
        "source": _SOURCE_FIELDS,
    }
    try:
        return values[kind]
    except KeyError as exc:
        raise AlarmIntegrationRuntimeError(
            f"unknown Alarm snapshot kind: {kind}"
        ) from exc


def _state(
    key: str,
    row: Mapping[str, Any],
    *,
    kind: str,
) -> AlarmObjectState:
    object_id = _guid(row.get("id"), f"{key} id")
    raw_name = row.get("name")
    name = (
        ""
        if kind == "action" and raw_name == ""
        else _text(raw_name, f"{key} name")
    )
    object_type = _text(row.get("type"), f"{key} type")
    path = _wwise_path(row.get("path"), f"{key} path")
    parent_id = _optional_identity(row.get("parent"), f"{key} parent")
    details: dict[str, Any] = {
        "short_id": _optional_plain_int(row.get("shortId"), f"{key} shortId"),
        "notes": "" if row.get("notes") is None else str(row.get("notes")),
    }
    if kind == "sound":
        details.update(
            {
                "volume": _optional_number(row.get("@Volume"), f"{key} Volume"),
                "pitch": _optional_number(row.get("@Pitch"), f"{key} Pitch"),
                "override_output": _bool_alias(
                    row,
                    "OverrideOutput",
                    "@OverrideOutput",
                    f"{key} OverrideOutput",
                ),
                "use_max_sound_per_instance": _optional_bool(
                    row.get("@UseMaxSoundPerInstance"),
                    f"{key} UseMaxSoundPerInstance",
                ),
                "max_sound_per_instance": _optional_plain_int(
                    row.get("@MaxSoundPerInstance"),
                    f"{key} MaxSoundPerInstance",
                ),
                "output_bus_id": _optional_identity(
                    row.get("OutputBus"),
                    f"{key} OutputBus",
                ),
                "active_source_id": _optional_identity(
                    row.get("activeSource"),
                    f"{key} activeSource",
                ),
            }
        )
    elif kind == "bus":
        details["volume"] = _optional_number(
            row.get("@Volume"),
            f"{key} Volume",
        )
    elif kind == "action":
        details.update(
            {
                "action_type": _optional_plain_int(
                    row.get("ActionType"),
                    f"{key} ActionType",
                ),
                "target_id": _optional_identity(
                    row.get("Target"),
                    f"{key} Target",
                ),
            }
        )
    elif kind == "source":
        details.update(
            {
                "original_file_path": _optional_text(
                    row.get("originalFilePath")
                ),
                "language": _language(row.get("audioSource:language")),
            }
        )
    return AlarmObjectState(
        key=key,
        object_id=object_id,
        name=name,
        object_type=object_type,
        path=path,
        parent_id=parent_id,
        details=_freeze_json(details),
    )


def _diagnostic_projection(
    row: Mapping[str, Any],
    *,
    kind: str,
) -> Mapping[str, Any]:
    raw_name = row.get("name")
    name = (
        ""
        if kind == "action" and raw_name == ""
        else _text(raw_name, f"diagnostic {kind} name")
    )
    result: dict[str, Any] = {
        "id": _guid(row.get("id"), f"diagnostic {kind} id"),
        "name": name,
        "type": _text(row.get("type"), f"diagnostic {kind} type"),
        "path": _wwise_path(row.get("path"), f"diagnostic {kind} path"),
    }
    if kind == "action":
        native_action_type = row.get("ActionType")
        business_action_type = row.get("action_type")
        if (
            native_action_type is not None
            and business_action_type is not None
            and native_action_type != business_action_type
        ):
            raise AlarmIntegrationRuntimeError(
                "diagnostic ActionType aliases disagree"
            )
        native_target = row.get("Target")
        business_target = row.get("target")
        if (
            native_target is not None
            and business_target is not None
            and native_target != business_target
        ):
            raise AlarmIntegrationRuntimeError(
                "diagnostic Target aliases disagree"
            )
        result.update(
            {
                "action_type": _optional_plain_int(
                    (
                        native_action_type
                        if native_action_type is not None
                        else business_action_type
                    ),
                    "diagnostic ActionType",
                ),
                "target_id": _optional_identity(
                    native_target if native_target is not None else business_target,
                    "diagnostic Target",
                ),
            }
        )
    elif kind == "sound":
        native_override_output = _bool_alias(
            row,
            "OverrideOutput",
            "@OverrideOutput",
            "diagnostic OverrideOutput",
        )
        override_output = _coalesced_alias(
            native_override_output,
            _optional_bool(
                row.get("override_output"),
                "diagnostic override_output",
            ),
            "diagnostic OverrideOutput",
        )
        active_source = _coalesced_alias(
            row.get("activeSource"),
            row.get("active_source"),
            "diagnostic activeSource",
        )
        output_bus = _coalesced_alias(
            row.get("OutputBus"),
            row.get("output_bus"),
            "diagnostic OutputBus",
        )
        result.update(
            {
                "override_output": override_output,
                "active_source_id": _optional_identity(
                    active_source,
                    "diagnostic activeSource",
                ),
                "output_bus_id": _optional_identity(
                    output_bus,
                    "diagnostic OutputBus",
                ),
            }
        )
    elif kind == "source":
        original_file_path = _coalesced_alias(
            row.get("originalFilePath"),
            row.get("original_file_path"),
            "diagnostic originalFilePath",
        )
        source_language = _coalesced_alias(
            row.get("audioSource:language"),
            row.get("source_language"),
            "diagnostic source language",
        )
        result.update(
            {
                "original_file_path": _optional_text(
                    original_file_path
                ),
                "language": _language(source_language),
            }
        )
    elif kind == "bus":
        volume = _coalesced_alias(
            row.get("@Volume"),
            row.get("volume_db"),
            "diagnostic Bus Volume",
        )
        result["volume"] = _optional_number(
            volume,
            "diagnostic Bus Volume",
        )
    elif kind != "event":
        raise AlarmIntegrationRuntimeError(
            f"unknown Alarm diagnostic kind: {kind}"
        )
    return MappingProxyType(result)


def _diagnostic_projection_from_state(
    state: AlarmObjectState,
    *,
    kind: str,
) -> Mapping[str, Any]:
    result: dict[str, Any] = {
        "id": state.object_id,
        "name": state.name,
        "type": state.object_type,
        "path": state.path,
    }
    details = state.details
    if kind == "action":
        result.update(
            {
                "action_type": details["action_type"],
                "target_id": details["target_id"],
            }
        )
    elif kind == "sound":
        result.update(
            {
                "override_output": details["override_output"],
                "active_source_id": details["active_source_id"],
                "output_bus_id": details["output_bus_id"],
            }
        )
    elif kind == "source":
        result.update(
            {
                "original_file_path": details["original_file_path"],
                "language": details["language"],
            }
        )
    elif kind == "bus":
        result["volume"] = details["volume"]
    elif kind != "event":
        raise AlarmIntegrationRuntimeError(
            f"unknown Alarm diagnostic kind: {kind}"
        )
    return MappingProxyType(result)


def _one_row(
    rows: Sequence[Mapping[str, Any]],
    label: str,
) -> Mapping[str, Any]:
    if len(rows) != 1:
        raise AlarmIntegrationRuntimeError(
            f"{label} must resolve exactly once; got {len(rows)}"
        )
    return rows[0]


def _one_id(rows: Sequence[Mapping[str, Any]], label: str) -> str:
    return _guid(_one_row(rows, label).get("id"), f"{label} id")


def _return_fields(fields: Sequence[str]) -> tuple[str, ...]:
    result = tuple(fields)
    if (
        not result
        or len(result) != len(set(result))
        or any(type(field) is not str or not field for field in result)
    ):
        raise AlarmIntegrationRuntimeError("Alarm return fields are invalid")
    return result


def _optional_identity(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        value = value.get("id")
    return _guid(value, label)


def _guid(value: Any, label: str) -> str:
    if type(value) is not str or _GUID_RE.fullmatch(value) is None:
        raise AlarmIntegrationRuntimeError(f"{label} is not a canonical GUID")
    return value.upper()


def _wwise_path(value: Any, label: str) -> str:
    result = _text(value, label)
    if (
        not result.startswith("\\")
        or result.endswith("\\")
        or "\\\\" in result
        or "\x00" in result
    ):
        raise AlarmIntegrationRuntimeError(
            f"{label} is not an absolute Wwise path"
        )
    return result


def _segment(value: Any, label: str) -> str:
    result = _text(value, label)
    if any(character in result for character in '\\/\x00<>:"|?*'):
        raise AlarmIntegrationRuntimeError(f"{label} is not a safe Wwise segment")
    return result


def _text(value: Any, label: str) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or any(ord(character) < 32 for character in value)
    ):
        raise AlarmIntegrationRuntimeError(f"{label} is not normalized text")
    return value


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return _text(value, "optional text")


def _language(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        value = value.get("name")
    return _text(value, "source language")


def _optional_plain_int(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int:
        raise AlarmIntegrationRuntimeError(f"{label} is not a plain integer")
    return value


def _optional_number(value: Any, label: str) -> int | float | None:
    if value is None:
        return None
    if type(value) not in {int, float} or (
        type(value) is float and not math.isfinite(value)
    ):
        raise AlarmIntegrationRuntimeError(f"{label} is not a finite number")
    return value


def _optional_bool(value: Any, label: str) -> bool | None:
    if value is None:
        return None
    if type(value) is not bool:
        raise AlarmIntegrationRuntimeError(f"{label} is not a boolean")
    return value


def _bool_alias(
    row: Mapping[str, Any],
    first: str,
    second: str,
    label: str,
) -> bool | None:
    values = [
        _optional_bool(row.get(name), label)
        for name in (first, second)
        if row.get(name) is not None
    ]
    if not values:
        return None
    if len(set(values)) != 1:
        raise AlarmIntegrationRuntimeError(f"{label} aliases disagree")
    return values[0]


def _coalesced_alias(first: Any, second: Any, label: str) -> Any:
    """Accept one native/business alias and reject contradictory dual values."""

    if first is not None and second is not None and first != second:
        raise AlarmIntegrationRuntimeError(f"{label} aliases disagree")
    return first if first is not None else second


def _file_proof(path: Path) -> AlarmFileProof:
    absolute = Path(os.path.abspath(os.fspath(path)))
    try:
        metadata = os.lstat(absolute)
    except OSError as exc:
        raise AlarmIntegrationRuntimeError(
            f"Alarm input file cannot be inspected: {exc}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise AlarmIntegrationRuntimeError(
            f"Alarm input file is not a real regular file: {absolute}"
        )
    digest = hashlib.sha256()
    with absolute.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return AlarmFileProof(
        path=str(absolute),
        size=metadata.st_size,
        sha256=digest.hexdigest(),
    )


def _write_deterministic_wav(
    path: Path,
    *,
    duration_ms: int,
    frequency_hz: int,
) -> None:
    if path.exists() or path.is_symlink():
        raise AlarmIntegrationRuntimeError(
            f"fresh Alarm WAV already exists: {path}"
        )
    if not 100 <= duration_ms <= 2000 or not 100 <= frequency_hz <= 2000:
        raise AlarmIntegrationRuntimeError("Alarm WAV parameters are out of range")
    sample_rate = 16_000
    frame_count = sample_rate * duration_ms // 1000
    payload = bytearray()
    for index in range(frame_count):
        # A deterministic low-amplitude square wave avoids platform-dependent
        # floating-point sine implementations while remaining a valid source.
        period = max(2, sample_rate // frequency_hz)
        value = 4096 if index % period < period // 2 else -4096
        payload.extend(struct.pack("<h", value))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(payload))


def _sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _plain(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if value is None or type(value) in {str, int, float, bool}:
        return value
    raise AlarmIntegrationRuntimeError(
        f"Alarm runtime value is not JSON: {type(value).__name__}"
    )


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


__all__ = [
    "ACTOR_LAB",
    "ALARM_ACTOR_ROOT",
    "ALARM_EVENT_PATH",
    "ALARM_EVENT_ROOT",
    "ALARM_FIXTURE_ADAPTER",
    "ALARM_SOUND_PATH",
    "ALARM_WORKFLOW_ID",
    "AlarmCleanupProof",
    "AlarmExpectedDispatch",
    "AlarmFileProof",
    "AlarmFixturePaths",
    "AlarmIntegrationRuntimeError",
    "AlarmObjectState",
    "AlarmOracleRequirement",
    "AlarmRuntimePaths",
    "AlarmSnapshot",
    "AlarmVerification",
    "DEAD_BUS_PATH",
    "DECOY_BUS_PATHS",
    "DECOY_EVENT_PATHS",
    "DECOY_SOUND_PATHS",
    "PreparedAlarmIntegrationRuntime",
    "SUPPORTED_VERSIONS",
    "TARGET_BUS_PATH",
    "alarm_fixture_paths",
    "prepare_alarm_integration_runtime",
]
