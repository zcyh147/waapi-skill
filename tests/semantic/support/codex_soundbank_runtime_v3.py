"""Trusted fixture, materializer, and oracle for the 25 v3 SoundBank cases.

This module belongs to the fresh-Codex campaign runner.  It is deliberately
not part of the Skill and none of its hidden identities, filesystem snapshots,
or direct-WAAPI setup methods are exposed to the evaluated model.

The public flow is:

``build_soundbank_blueprint``
    Consume the reviewed ``asset_spec`` and allocate a fresh, bounded asset
    and output layout.

``PreparedSoundBankRuntime.prepare``
    Materialize the scenario-owned Wwise fixture through a closed backend,
    resolve live GUID/short-id values, write immutable inputs, and capture the
    hidden before snapshot.

``render_prompt`` / ``operation_requests`` / ``topic_plan``
    Return only the reviewed model-visible values and packaged gateway plans.

``verify_*``
    Compare live Wwise state and complete bounded filesystem trees against an
    independent oracle.  Result-schema success is never accepted as business
    state proof.

The module never starts Codex or Wwise.  A caller must supply an already
running scenario-owned Wwise project and must leave project/process teardown
to :mod:`codex_scenario_lifecycle_v3`.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import stat
import struct
import uuid
import wave
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Literal, Protocol

from .codex_eval_bundle_v3 import OnlineScenario
from wwise_waapi.operation_soundbank import parse_soundbank_definition_file

try:  # ``pwd`` is not available on Windows, where Wine drive mapping is unnecessary.
    import pwd
except ImportError:  # pragma: no cover - exercised only on native Windows hosts
    pwd = None  # type: ignore[assignment]


SUPPORTED_VERSION = "2022.1"
OPERATION_REQUEST_CONTRACT = "waapi-skill.operation-request/v1"
SOUNDBANK_RUNTIME_CONTRACT = "waapi-skill.soundbank-eval-runtime/v3"
SOUNDBANK_TOPIC = "ak.wwise.core.soundbank.generated"
SOUNDBANK_TOPIC_RETURN_FIELDS = ("id", "name", "type", "path")
SOUNDBANK_APIS = frozenset(
    {
        "ak.wwise.core.soundbank.generate",
        SOUNDBANK_TOPIC,
        "ak.wwise.core.soundbank.processDefinitionFiles",
        "ak.wwise.core.soundbank.convertExternalSources",
        "ak.wwise.core.soundbank.setInclusions",
    }
)
EXPECTED_SCENARIO_COUNT = 25
PROCESS_REFUSAL_ID = "O22-SB-PROCESS-DEF-05"
PROCESS_REFUSAL_ERROR_CODE = "AMBIGUOUS_IDENTITY"
PROCESS_REFUSAL_ABSENT_IDENTITIES = (
    ("refusal_absent:event", "Event", "Retired_Event_2049"),
    ("refusal_absent:soundbank", "SoundBank", "Retired_Content"),
)
DEFINITION_IDENTITY_MATERIALIZATION = MappingProxyType(
    {
        "name": "runner_writes_double_quoted_literal_name",
        "guid": "runner_queries_guid",
        "decimal_short_id": "runner_queries_decimal_short_id",
        "hexadecimal_short_id": "runner_queries_hexadecimal_short_id",
    }
)

ACTOR_DWU = r"\Actor-Mixer Hierarchy\Default Work Unit"
EVENT_DWU = r"\Events\Default Work Unit"
SOUNDBANK_DWU = r"\SoundBanks\Default Work Unit"
MASTER_DWU = r"\Master-Mixer Hierarchy\Default Work Unit"
MASTER_AUDIO_BUS = MASTER_DWU + r"\Master Audio Bus"
CONVERSION_DWU = r"\Conversion Settings\Default Work Unit"
DIALOGUE_DWU = r"\Dynamic Dialogue\Default Work Unit"
EFFECT_DWU = r"\Effects\Default Work Unit"
EFFECT_TEMPLATE_PATH = (
    r"\Effects\Factory Effects\Wwise Peak Limiter\Radio_Squish"
)
EFFECT_TEMPLATE_PARENT = EFFECT_TEMPLATE_PATH.rsplit("\\", 1)[0]

GUID_RE = re.compile(
    r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$"
)
SAFE_SEGMENT_RE = re.compile(r"^[^\\/\x00-\x1f<>:\"|?*]+$")
ALLOWED_FILTERS = frozenset({"events", "structures", "media"})
CANONICAL_LANGUAGE = {
    "Chinese": "Chinese(PRC)",
    "English": "English(US)",
    "Japanese": "Japanese",
    "SFX": "SFX",
}
SETUP_EVENT_ACTION = "Play"
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_TREE_FILES = 8192
OBJECT_FIELDS = ("id", "name", "type", "path", "parent", "shortId", "notes")
MEDIA_OBJECT_FIELDS = (
    *OBJECT_FIELDS,
    "OutputBus",
    "activeSource",
    "sound:originalWavFilePath",
    "audioSource:language",
)
# ``AudioFileSource`` rows have an Authoring GUID and a Media ID, but no Wwise
# object Short ID (the persisted .wwu shape is ``MediaIDList/MediaID``).  The
# ``mediaId`` WAAPI/WAQL accessor was added in Wwise 2022.1.9, before the pinned
# 2022.1.19 lane used by this suite.  Keep it separate from ``shortId`` so the
# generated .wem oracle can never silently substitute the parent Sound's ID.
MEDIA_SOURCE_FIELDS = (
    *OBJECT_FIELDS,
    "mediaId",
    "originalFilePath",
    "audioSource:language",
)


class SoundBankRuntimeError(RuntimeError):
    """The trusted SoundBank fixture or its oracle failed closed."""


DirectWaapiCall = Callable[[str, Mapping[str, Any], Mapping[str, Any]], Any]


@dataclass(frozen=True, slots=True)
class FileProof:
    path: str
    relative_path: str
    size: int
    sha256: str
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class TreeEntry:
    relative_path: str
    size: int
    sha256: str
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class ObjectFixture:
    key: str
    name: str
    object_type: str
    parent_path: str
    path: str
    owned: bool = True
    template_path: str | None = None


@dataclass(frozen=True, slots=True)
class MediaFixture:
    key: str
    wav_path: Path
    sound_path: str
    event_path: str
    language: str
    duration_ms: int
    frequency_hz: int
    soundbank_names: tuple[str, ...]
    output_bus_path: str
    import_operation: Literal["createNew", "useExisting"] = "createNew"
    create_event: bool = True


@dataclass(frozen=True, slots=True)
class EventGraphState:
    event_id: str
    action_ids: tuple[str, ...]
    target_ids: tuple[str, ...]
    action_types: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class MediaSourceState:
    fixture_key: str
    sound_id: str
    source_id: str
    media_id: int
    language: str
    copied_file: FileProof


@dataclass(frozen=True, slots=True)
class InclusionRow:
    object_key: str
    object_name: str
    filters: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SoundBankFixture:
    name: str
    path: str
    project_object_mode: str
    inclusions: tuple[InclusionRow, ...]
    control: bool = False


@dataclass(frozen=True, slots=True)
class DefinitionRowPlan:
    soundbank: str
    directive: str
    object_key: str
    object_name: str
    object_type: str
    identity_format: str
    identity_materialization: str
    filters: tuple[str, ...]
    resolution: str


@dataclass(frozen=True, slots=True)
class DefinitionDocumentPlan:
    name: str
    path: Path
    rows: tuple[DefinitionRowPlan, ...]


@dataclass(frozen=True, slots=True)
class ExternalSourceRow:
    source_path: Path
    conversion: str | None
    destination: str
    analysis_types: int | None


@dataclass(frozen=True, slots=True)
class ExternalSourceDocument:
    name: str
    path: Path
    rows: tuple[ExternalSourceRow, ...]


@dataclass(frozen=True, slots=True)
class ExpectedArtifact:
    kind: Literal["bank", "media", "external", "init", "control"]
    path: Path
    soundbank: str | None
    platform: str | None
    language: str | None
    required_change: bool


@dataclass(frozen=True, slots=True)
class TopicExpectedEvent:
    soundbank_name: str
    platform_name: str
    language_name: str | None
    soundbank_id: str | None = None
    platform_id: str | None = None
    language_id: str | None = None

    @property
    def key(self) -> tuple[str, str, str | None]:
        if (
            self.soundbank_id is None
            or GUID_RE.fullmatch(self.soundbank_id) is None
            or self.platform_id is None
            or GUID_RE.fullmatch(self.platform_id) is None
            or (
                self.language_name is not None
                and (
                    self.language_id is None
                    or GUID_RE.fullmatch(self.language_id) is None
                )
            )
        ):
            raise SoundBankRuntimeError(
                "topic oracle identity is not bound to hidden canonical GUIDs"
            )
        return (
            self.soundbank_id.casefold(),
            self.platform_id.casefold(),
            self.language_id.casefold() if self.language_id is not None else None,
        )


@dataclass(frozen=True, slots=True)
class TopicPublisher:
    operation_request: Mapping[str, Any]
    expected_events: tuple[TopicExpectedEvent, ...]


@dataclass(frozen=True, slots=True)
class TopicPlan:
    topic: str
    event_count: int
    match: Mapping[str, Any] | None
    options: Mapping[str, Any]
    expected_events: tuple[TopicExpectedEvent, ...]
    publishers: tuple[TopicPublisher, ...]
    subscribe_before_publish: bool
    init_generated_before_subscribe: bool
    reject_n_plus_one: bool

    def gateway_arguments(self) -> Mapping[str, Any]:
        arguments: dict[str, Any] = {
            "api": self.topic,
            "event_count": self.event_count,
            "options": dict(self.options),
        }
        if self.match is not None:
            arguments["match"] = dict(self.match)
        return MappingProxyType(arguments)


@dataclass(frozen=True, slots=True)
class SoundBankBlueprint:
    scenario_id: str
    api: str
    version: str
    scenario: OnlineScenario
    sandbox_project: Path
    sandbox_root: Path
    io_root: Path
    asset_root: Path
    output_root: Path
    asset_spec: Mapping[str, Any]
    object_fixtures: tuple[ObjectFixture, ...]
    media_fixtures: tuple[MediaFixture, ...]
    soundbanks: tuple[SoundBankFixture, ...]
    definitions: tuple[DefinitionDocumentPlan, ...]
    external_documents: tuple[ExternalSourceDocument, ...]
    expected_primary_dispatch_count: int
    zero_dispatch_error_code: str | None


@dataclass(frozen=True, slots=True)
class MaterializedSoundBankCase:
    blueprint: SoundBankBlueprint
    visible_values: Mapping[str, str]
    prompt_sources: Mapping[str, Any]
    operation_requests: tuple[Mapping[str, Any], ...]
    topic_plan: TopicPlan | None
    input_files: tuple[FileProof, ...]
    expected_artifacts: tuple[ExpectedArtifact, ...]
    allowed_dynamic_artifact_roots: tuple[Path, ...]
    object_ids: Mapping[str, str]
    short_ids: Mapping[str, int]
    media_ids: Mapping[str, int]
    platform_ids: Mapping[str, str]
    language_ids: Mapping[str, str]

    @property
    def scenario_id(self) -> str:
        return self.blueprint.scenario_id

    def render_prompt(self) -> str:
        return self.blueprint.scenario.render_prompt(self.visible_values)


@dataclass(frozen=True, slots=True)
class ObjectState:
    key: str
    id: str | None
    path: str
    object_type: str | None


@dataclass(frozen=True, slots=True)
class BankState:
    name: str
    id: str | None
    inclusions: tuple[tuple[str, tuple[str, ...]], ...]


@dataclass(frozen=True, slots=True)
class SoundBankSnapshot:
    scenario_id: str
    objects: tuple[ObjectState, ...]
    banks: tuple[BankState, ...]
    project_files: tuple[TreeEntry, ...]
    input_files: tuple[FileProof, ...]
    output_files: tuple[TreeEntry, ...]


@dataclass(frozen=True, slots=True)
class SoundBankVerification:
    scenario_id: str
    phase: str
    passed: bool
    failures: tuple[str, ...]
    before: SoundBankSnapshot
    after: SoundBankSnapshot

    def assert_passed(self) -> None:
        if not self.passed:
            raise SoundBankRuntimeError(
                f"{self.scenario_id} {self.phase} failed: " + "; ".join(self.failures)
            )


@dataclass(frozen=True, slots=True)
class TopicVerification:
    scenario_id: str
    passed: bool
    failures: tuple[str, ...]
    observed_keys: tuple[tuple[str, str, str | None], ...]
    expected_keys: tuple[tuple[str, str, str | None], ...]

    def assert_passed(self) -> None:
        if not self.passed:
            raise SoundBankRuntimeError(
                f"{self.scenario_id} topic verification failed: "
                + "; ".join(self.failures)
            )


class SoundBankRuntimeBackend(Protocol):
    """Closed trusted seam.  Never pass this object to the evaluated model."""

    def get_project_info(self) -> Mapping[str, Any]: ...

    def read_objects(
        self,
        *,
        path: str | None = None,
        object_id: str | int | None = None,
        object_type: str | None = None,
        name: str | None = None,
        fields: Sequence[str] = OBJECT_FIELDS,
        language: str | None = None,
    ) -> tuple[Mapping[str, Any], ...]: ...

    def create_object(self, fixture: ObjectFixture) -> str: ...

    def import_media(self, fixture: MediaFixture) -> tuple[str, ...]: ...

    def read_event_graph(self, path: str) -> EventGraphState | None: ...

    def set_inclusions(
        self,
        soundbank_id: str,
        mode: str,
        rows: Sequence[tuple[str, Sequence[str]]],
    ) -> None: ...

    def read_inclusions(self, soundbank_id: str) -> tuple[Mapping[str, Any], ...]: ...

    def save_project(self) -> None: ...

    def generate_for_setup(self, args: Mapping[str, Any]) -> None: ...

    def delete_object(self, object_id: str) -> None: ...


class ClosedDirectWaapiSoundBankBackend:
    """Direct-WAAPI runner adapter with no public generic-call escape hatch."""

    _CREATE_TYPES = frozenset(
        {
            "ActorMixer",
            "AuxBus",
            "Bus",
            "Conversion",
            "DialogueEvent",
            "Effect",
            "Event",
            "Folder",
            "PhysicalFolder",
            "SoundBank",
        }
    )

    def __init__(self, call: DirectWaapiCall) -> None:
        if not callable(call):
            raise TypeError("call must be callable")
        self._call = call

    def get_project_info(self) -> Mapping[str, Any]:
        result = self._call("ak.wwise.core.getProjectInfo", {}, {})
        if not isinstance(result, Mapping):
            raise SoundBankRuntimeError("getProjectInfo must return an object")
        return dict(result)

    def read_objects(
        self,
        *,
        path: str | None = None,
        object_id: str | int | None = None,
        object_type: str | None = None,
        name: str | None = None,
        fields: Sequence[str] = OBJECT_FIELDS,
        language: str | None = None,
    ) -> tuple[Mapping[str, Any], ...]:
        selectors = sum(
            value is not None
            for value in (path, object_id, object_type if name is not None else None)
        )
        if selectors != 1 or (object_type is None) != (name is None):
            raise SoundBankRuntimeError("object read requires one closed selector")
        if path is not None:
            args: dict[str, Any] = {"from": {"path": [_wwise_path(path, "path")]}}
        elif object_id is not None:
            args = {"from": {"id": [object_id]}}
        else:
            assert object_type is not None and name is not None
            if object_type not in self._CREATE_TYPES:
                raise SoundBankRuntimeError("typed-name read uses an unreviewed type")
            args = {
                "waql": f"from type {object_type} where name = "
                + json.dumps(_text(name, "name"), ensure_ascii=False)
                + " take 2"
            }
        options: dict[str, Any] = {"return": list(_fields(fields))}
        if language is not None:
            options["language"] = _canonical_language(language)
        result = self._call(
            "ak.wwise.core.object.get",
            args,
            options,
        )
        return _result_rows(result, "object.get")

    def create_object(self, fixture: ObjectFixture) -> str:
        if fixture.object_type not in self._CREATE_TYPES:
            raise SoundBankRuntimeError(
                f"setup object type is not closed: {fixture.object_type!r}"
            )
        if fixture.template_path is not None:
            if fixture.object_type != "Effect":
                raise SoundBankRuntimeError(
                    "only an Effect fixture may use the closed template-copy path"
                )
            templates = self.read_objects(
                path=fixture.template_path,
                fields=OBJECT_FIELDS,
            )
            if len(templates) != 1 or templates[0].get("type") != "Effect":
                raise SoundBankRuntimeError(
                    f"Effect template did not resolve exactly: {fixture.template_path}"
                )
            template_id = _guid(templates[0].get("id"), "Effect template id")
            result = self._call(
                "ak.wwise.core.object.copy",
                {
                    "object": template_id,
                    "parent": _wwise_path(fixture.parent_path, "parent_path"),
                    "onNameConflict": "fail",
                },
                {},
            )
            if not isinstance(result, Mapping):
                raise SoundBankRuntimeError("object.copy must return an object")
            object_id = _guid(result.get("id"), "object.copy id")
            renamed = self._call(
                "ak.wwise.core.object.setName",
                {"object": object_id, "value": _segment(fixture.name, "name")},
                {},
            )
            if renamed is not None and not isinstance(renamed, Mapping):
                raise SoundBankRuntimeError(
                    "object.setName must return an object or null"
                )
            return object_id
        if fixture.object_type == "Effect":
            raise SoundBankRuntimeError(
                "Effect setup requires the reviewed factory template"
            )
        result = self._call(
            "ak.wwise.core.object.create",
            {
                "parent": _wwise_path(fixture.parent_path, "parent_path"),
                "type": fixture.object_type,
                "name": _segment(fixture.name, "name"),
                "onNameConflict": "fail",
                "autoAddToSourceControl": False,
            },
            {},
        )
        if not isinstance(result, Mapping):
            raise SoundBankRuntimeError("object.create must return an object")
        return _guid(result.get("id"), "object.create id")

    def import_media(self, fixture: MediaFixture) -> tuple[str, ...]:
        proof = _file_proof(fixture.wav_path, fixture.wav_path.parent)
        if fixture.import_operation not in {"createNew", "useExisting"}:
            raise SoundBankRuntimeError(
                f"unreviewed media import operation: {fixture.import_operation}"
            )
        object_type = (
            "Sound SFX"
            if _canonical_language(fixture.language) == "SFX"
            else "Sound Voice"
        )
        if fixture.import_operation == "useExisting":
            logical_sound_path, wire_sound_path = _typed_existing_import_path(
                fixture.sound_path,
                object_type=object_type,
            )
        else:
            logical_sound_path = _wwise_path(fixture.sound_path, "sound_path")
            wire_sound_path = logical_sound_path
        sound_rows_before = self.read_objects(
            path=logical_sound_path,
            fields=MEDIA_OBJECT_FIELDS,
        )
        event_rows = self.read_objects(
            path=fixture.event_path,
            fields=OBJECT_FIELDS,
        )
        if len(sound_rows_before) > 1:
            raise SoundBankRuntimeError(
                f"audio.import Sound path is ambiguous: {fixture.sound_path}"
            )
        if len(event_rows) > 1:
            raise SoundBankRuntimeError(
                f"audio.import Event path is ambiguous: {fixture.event_path}"
            )
        if fixture.import_operation == "createNew":
            if not fixture.create_event:
                raise SoundBankRuntimeError(
                    "localized createNew setup must create its Event once"
                )
            if sound_rows_before:
                raise SoundBankRuntimeError(
                    f"localized createNew Sound already exists: {fixture.sound_path}"
                )
            if event_rows:
                raise SoundBankRuntimeError(
                    f"localized createNew Event already exists: {fixture.event_path}"
                )
        elif fixture.import_operation == "useExisting":
            if fixture.create_event:
                raise SoundBankRuntimeError(
                    "localized useExisting setup must not recreate its Event"
                )
            if len(sound_rows_before) != 1 or not str(
                sound_rows_before[0].get("type", "")
            ).startswith("Sound"):
                raise SoundBankRuntimeError(
                    f"localized useExisting Sound is absent: {fixture.sound_path}"
                )
            if len(event_rows) != 1:
                raise SoundBankRuntimeError(
                    f"localized useExisting Event is absent: {fixture.event_path}"
                )
        if event_rows and event_rows[0].get("type") != "Event":
            raise SoundBankRuntimeError(
                f"audio.import Event path has the wrong type: {fixture.event_path}"
            )
        import_row: dict[str, Any] = {
            "audioFile": proof.path,
            "objectPath": wire_sound_path,
            "importLanguage": fixture.language,
        }
        if fixture.import_operation == "createNew":
            import_row.update(
                {
                    "objectType": object_type,
                    # Wwise's audio-import Event grammar is
                    # ``<absolute Event path>@<action>``.  A bare path is
                    # schema-valid (the reflected field is a string) but
                    # Wwise 2022.1 emits an invalid empty-action warning.
                    "event": _setup_event_value(fixture.event_path),
                    "@IsStreamingEnabled": True,
                }
            )
        result = self._call(
            "ak.wwise.core.audio.import",
            {
                "importOperation": fixture.import_operation,
                # The useExisting row intentionally contains only these three
                # fields.  Wwise 2022 rejects object/event creation columns on
                # a localized addition even when it says they are ignored.
                "imports": [import_row],
                "autoAddToSourceControl": False,
            },
            {"return": list(MEDIA_SOURCE_FIELDS)},
        )
        rows = _result_rows(result, "audio.import", key="objects")
        ids = tuple(
            _guid(row.get("id"), "audio.import object id")
            for row in rows
            if row.get("id") is not None
        )
        if not ids:
            raise SoundBankRuntimeError("audio.import setup returned no identities")
        sounds = self.read_objects(
            path=logical_sound_path,
            fields=MEDIA_OBJECT_FIELDS,
            language=fixture.language,
        )
        busses = self.read_objects(
            path=fixture.output_bus_path,
            fields=OBJECT_FIELDS,
        )
        if len(sounds) != 1 or not str(sounds[0].get("type", "")).startswith("Sound"):
            raise SoundBankRuntimeError(
                f"audio.import Sound did not resolve exactly: {fixture.sound_path}"
            )
        if len(busses) != 1 or busses[0].get("type") != "Bus":
            raise SoundBankRuntimeError(
                f"audio.import output Bus did not resolve exactly: {fixture.output_bus_path}"
            )
        sound_id = _guid(sounds[0].get("id"), "imported Sound id")
        bus_id = _guid(busses[0].get("id"), "output Bus id")
        if fixture.import_operation == "createNew":
            # Wwise accepts an OutputBus reference on a Sound while leaving it
            # inherited unless the same object's override is enabled first.
            # Keep this runner-owned fixture setup aligned with the production
            # reference activation contract; the later exact readback remains
            # the success proof.
            override_result = self._call(
                "ak.wwise.core.object.setProperty",
                {
                    "object": sound_id,
                    "property": "OverrideOutput",
                    "value": True,
                },
                {},
            )
            if override_result is not None and not isinstance(
                override_result, Mapping
            ):
                raise SoundBankRuntimeError(
                    "object.setProperty must return an object or null"
                )
            reference_result = self._call(
                "ak.wwise.core.object.setReference",
                {
                    "object": sound_id,
                    "reference": "OutputBus",
                    "value": bus_id,
                },
                {},
            )
            if reference_result is not None and not isinstance(
                reference_result, Mapping
            ):
                raise SoundBankRuntimeError(
                    "object.setReference must return an object or null"
                )
        else:
            before_id = _guid(
                sound_rows_before[0].get("id"),
                "existing localized Sound id",
            )
            event_id_before = _guid(
                event_rows[0].get("id"),
                "existing localized Event id",
            )
            event_rows_after = self.read_objects(
                path=fixture.event_path,
                fields=OBJECT_FIELDS,
            )
            if len(event_rows_after) != 1:
                raise SoundBankRuntimeError(
                    f"localized useExisting removed or duplicated the Event: "
                    f"{fixture.event_path}"
                )
            event_id_after = _guid(
                event_rows_after[0].get("id"),
                "localized Event id after useExisting",
            )
            if not _same_identity(sound_id, before_id):
                raise SoundBankRuntimeError(
                    f"localized useExisting changed the logical Sound GUID: {fixture.sound_path}"
                )
            if not _same_identity(event_id_after, event_id_before):
                raise SoundBankRuntimeError(
                    f"localized useExisting changed the Event GUID: {fixture.event_path}"
                )
            output_bus = _payload_identity(sounds[0].get("OutputBus"))
            if output_bus is None or not _same_identity(output_bus, bus_id):
                raise SoundBankRuntimeError(
                    f"localized useExisting changed the reviewed OutputBus: {fixture.sound_path}"
                )
        return ids

    def read_event_graph(self, path: str) -> EventGraphState | None:
        event_path = _wwise_path(path, "event_path")
        event_rows = self.read_objects(path=event_path, fields=OBJECT_FIELDS)
        if len(event_rows) > 1:
            raise SoundBankRuntimeError(f"Event path is ambiguous: {event_path}")
        if not event_rows:
            return None
        if event_rows[0].get("type") != "Event":
            raise SoundBankRuntimeError(f"Event path has the wrong type: {event_path}")
        event_id = _guid(event_rows[0].get("id"), "Event id")
        result = self._call(
            "ak.wwise.core.object.get",
            {
                "from": {"id": [event_id]},
                "transform": [{"select": ["children"]}],
            },
            {"return": ["id", "type", "ActionType", "Target"]},
        )
        rows = _result_rows(result, "Event children")
        actions: list[tuple[str, str, int]] = []
        for row in rows:
            if str(row.get("type")) != "Action":
                raise SoundBankRuntimeError(
                    f"Event has a non-Action direct child: {event_path}"
                )
            action_id = _guid(row.get("id"), "Action id")
            target = _payload_identity(row.get("Target"))
            if target is None:
                raise SoundBankRuntimeError(f"Event Action lacks Target: {event_path}")
            action_type = _positive_int(row.get("ActionType"), "ActionType")
            actions.append((action_id, _guid(target, "Action Target"), action_type))
        actions.sort(key=lambda row: row[0].casefold())
        return EventGraphState(
            event_id,
            tuple(row[0] for row in actions),
            tuple(row[1] for row in actions),
            tuple(row[2] for row in actions),
        )

    def set_inclusions(
        self,
        soundbank_id: str,
        mode: str,
        rows: Sequence[tuple[str, Sequence[str]]],
    ) -> None:
        if mode not in {"add", "remove", "replace"}:
            raise SoundBankRuntimeError("invalid setup inclusion mode")
        payload = [
            {
                "object": _guid(object_id, "inclusion object id"),
                "filter": list(_filters(filters)),
            }
            for object_id, filters in rows
        ]
        result = self._call(
            "ak.wwise.core.soundbank.setInclusions",
            {
                "soundbank": _guid(soundbank_id, "soundbank id"),
                "operation": mode,
                "inclusions": payload,
            },
            {},
        )
        if result is not None and not isinstance(result, Mapping):
            raise SoundBankRuntimeError("setInclusions result must be object or null")

    def read_inclusions(self, soundbank_id: str) -> tuple[Mapping[str, Any], ...]:
        result = self._call(
            "ak.wwise.core.soundbank.getInclusions",
            {"soundbank": _guid(soundbank_id, "soundbank id")},
            {},
        )
        return _result_rows(result, "soundbank.getInclusions", key="inclusions")

    def save_project(self) -> None:
        result = self._call("ak.wwise.core.project.save", {}, {})
        if result is not None and not isinstance(result, Mapping):
            raise SoundBankRuntimeError("project.save result must be object or null")

    def generate_for_setup(self, args: Mapping[str, Any]) -> None:
        allowed = {
            "soundbanks",
            "platforms",
            "languages",
            "skipLanguages",
            "writeToDisk",
            "rebuildSoundBanks",
            "clearAudioFileCache",
            "rebuildInitBank",
        }
        if set(args) - allowed or args.get("writeToDisk") is not True:
            raise SoundBankRuntimeError("setup generate request escaped its closed schema")
        result = self._call("ak.wwise.core.soundbank.generate", dict(args), {})
        if not isinstance(result, Mapping):
            raise SoundBankRuntimeError("setup soundbank.generate must return an object")
        logs = result.get("logs", [])
        if not isinstance(logs, list) or any(
            isinstance(row, Mapping)
            and str(row.get("severity", "")).casefold() in {"error", "fatal"}
            for row in logs
        ):
            raise SoundBankRuntimeError("setup soundbank.generate reported an error")

    def delete_object(self, object_id: str) -> None:
        result = self._call(
            "ak.wwise.core.object.delete",
            {"object": _guid(object_id, "cleanup object id")},
            {},
        )
        if result is not None and not isinstance(result, Mapping):
            raise SoundBankRuntimeError("object.delete result must be object or null")


def build_soundbank_blueprint(
    scenario: OnlineScenario,
    *,
    version: str,
    sandbox_project: str | Path,
    io_root: str | Path,
    asset_root: str | Path,
) -> SoundBankBlueprint:
    """Allocate deterministic local assets for one reviewed SoundBank case.

    ``asset_root`` must be a new descendant of ``io_root``.  The active project
    must also be below ``io_root`` so the named operations can attest one common
    scenario-owned I/O authority.  The function performs no WAAPI calls.
    """

    if scenario.api not in SOUNDBANK_APIS:
        raise SoundBankRuntimeError(f"unsupported SoundBank scenario API: {scenario.api}")
    if version != SUPPORTED_VERSION or version not in scenario.versions:
        raise SoundBankRuntimeError(
            f"{scenario.id} SoundBank runtime is pinned to Wwise {SUPPORTED_VERSION}"
        )
    project_candidate = Path(sandbox_project).expanduser()
    if project_candidate.is_symlink():
        raise SoundBankRuntimeError("sandbox_project must not be a symlink")
    project = project_candidate.resolve(strict=True)
    if not project.is_file() or project.suffix.casefold() != ".wproj":
        raise SoundBankRuntimeError("sandbox_project must be a real .wproj file")
    owned_candidate = Path(io_root).expanduser()
    if owned_candidate.is_symlink():
        raise SoundBankRuntimeError("io_root must not be a symlink")
    owned = owned_candidate.resolve(strict=True)
    if not owned.is_dir():
        raise SoundBankRuntimeError("io_root must be a real existing directory")
    _require_under(project, owned, "sandbox_project")
    assets = Path(asset_root).expanduser().resolve(strict=False)
    _require_under(assets, owned, "asset_root")
    if assets.exists():
        raise SoundBankRuntimeError(
            f"SoundBank asset root already exists and cannot be reused: {assets}"
        )
    assets.mkdir(parents=True, exist_ok=False)
    output = owned / "io" / "soundbank-v3" / scenario.id
    _require_under(output, owned, "output_root")
    if output.exists():
        raise SoundBankRuntimeError(
            f"SoundBank output root already exists and cannot be reused: {output}"
        )
    output.mkdir(parents=True, exist_ok=False)
    for child in ("media", "documents"):
        (assets / child).mkdir(exist_ok=False)

    raw_spec = scenario.fixture.get("asset_spec")
    if not isinstance(raw_spec, Mapping):
        raise SoundBankRuntimeError(f"{scenario.id} lacks a reviewed asset_spec")
    spec = MappingProxyType(_json_clone(raw_spec))
    operation = spec.get("operation")
    expected_operation = {
        "ak.wwise.core.soundbank.generate": "generate",
        SOUNDBANK_TOPIC: "observeGenerated",
        "ak.wwise.core.soundbank.processDefinitionFiles": "processDefinitionFiles",
        "ak.wwise.core.soundbank.convertExternalSources": "convertExternalSources",
        "ak.wwise.core.soundbank.setInclusions": "setInclusions",
    }[scenario.api]
    if operation != expected_operation:
        raise SoundBankRuntimeError(
            f"{scenario.id} asset operation drifted: {operation!r}"
        )

    objects: list[ObjectFixture] = []
    media: list[MediaFixture] = []
    banks: list[SoundBankFixture] = []
    definitions: list[DefinitionDocumentPlan] = []
    external_documents: list[ExternalSourceDocument] = []

    if scenario.api in {"ak.wwise.core.soundbank.generate", SOUNDBANK_TOPIC}:
        _compile_generation_fixture(
            scenario,
            spec,
            assets,
            objects=objects,
            media=media,
            banks=banks,
        )
    elif scenario.api == "ak.wwise.core.soundbank.processDefinitionFiles":
        _compile_definition_fixture(
            scenario,
            spec,
            assets,
            objects=objects,
            banks=banks,
            definitions=definitions,
        )
    elif scenario.api == "ak.wwise.core.soundbank.convertExternalSources":
        _compile_external_fixture(
            scenario,
            spec,
            project.parent,
            assets,
            output,
            objects=objects,
            external_documents=external_documents,
        )
    else:
        _compile_set_inclusions_fixture(
            scenario,
            spec,
            objects=objects,
            banks=banks,
        )

    objects = list(_dedupe_object_fixtures(objects))
    _validate_fixture_uniqueness(objects, media, banks)
    zero_code = PROCESS_REFUSAL_ERROR_CODE if scenario.id == PROCESS_REFUSAL_ID else None
    if (scenario.primary_dispatch.count == 0) != (zero_code is not None):
        raise SoundBankRuntimeError(
            f"{scenario.id} zero-dispatch/refusal contract is inconsistent"
        )
    return SoundBankBlueprint(
        scenario_id=scenario.id,
        api=scenario.api,
        version=version,
        scenario=scenario,
        sandbox_project=project,
        sandbox_root=project.parent,
        io_root=owned,
        asset_root=assets,
        output_root=output,
        asset_spec=spec,
        object_fixtures=tuple(objects),
        media_fixtures=tuple(media),
        soundbanks=tuple(banks),
        definitions=tuple(definitions),
        external_documents=tuple(external_documents),
        expected_primary_dispatch_count=scenario.primary_dispatch.count,
        zero_dispatch_error_code=zero_code,
    )


def _compile_generation_fixture(
    scenario: OnlineScenario,
    spec: Mapping[str, Any],
    assets: Path,
    *,
    objects: list[ObjectFixture],
    media: list[MediaFixture],
    banks: list[SoundBankFixture],
) -> None:
    manifest = _mapping(spec.get("fixture_manifest"), "fixture_manifest")
    raw_banks = _mapping_rows(manifest.get("soundbanks"), "fixture_manifest.soundbanks")
    prefix = _fixture_prefix(scenario.id)
    profile = _segment(manifest.get("profile"), "fixture_manifest.profile")
    has_explicit_logical_paths = any(
        "object_path" in raw_media
        for raw_bank in raw_banks
        for raw_media in _mapping_rows(
            raw_bank.get("media"),
            f"{raw_bank.get('name', 'soundbank')}.media",
        )
    )
    # The two localized SoundBank fixtures declare their shared logical Sound
    # paths in the suite itself.  Give those paths a deterministic parent that
    # can be independently checked from the profile; retain the historical
    # scenario-id parent for every nonlocalized fixture.
    actor_root_name = profile if has_explicit_logical_paths else prefix
    actor_parent = f"{ACTOR_DWU}\\{actor_root_name}"
    objects.append(
        ObjectFixture(
            "fixture.actor_root",
            actor_root_name,
            "ActorMixer",
            ACTOR_DWU,
            actor_parent,
        )
    )
    for raw_bank in raw_banks:
        name = _segment(raw_bank.get("name"), "soundbank.name")
        mode = _text(raw_bank.get("project_object_mode"), "project_object_mode")
        if mode not in {"existing_soundbank", "temporary_request_only"}:
            raise SoundBankRuntimeError(f"unreviewed project object mode: {mode}")
        event_rows = _mapping_rows(raw_bank.get("events"), f"{name}.events")
        dependency_rows = _mapping_rows(
            raw_bank.get("dependencies"), f"{name}.dependencies"
        )
        output_busses = [
            _wwise_path(row.get("object_path"), "dependency.object_path")
            for row in dependency_rows
            if row.get("type") == "Bus"
        ]
        if len(output_busses) != 1:
            raise SoundBankRuntimeError(
                f"{scenario.id} {name} requires exactly one reviewed output Bus"
            )
        output_bus_path = output_busses[0]
        event_to_media: dict[str, list[str]] = {}
        for raw_media in _mapping_rows(raw_bank.get("media"), f"{name}.media"):
            key = _text(raw_media.get("key"), f"{name}.media.key")
            event_name = _segment(raw_media.get("event"), f"{name}.media.event")
            matching_events = [
                event
                for event in event_rows
                if event.get("name") == event_name
            ]
            if len(matching_events) != 1:
                raise SoundBankRuntimeError(
                    f"{scenario.id} media event {event_name!r} is not unique"
                )
            event_path = _wwise_path(
                matching_events[0].get("object_path"), f"{name}.event.path"
            )
            language = _canonical_language(
                _text(raw_media.get("language"), f"{name}.media.language")
            )
            wav_path = assets / "media" / _safe_filename(
                _text(raw_media.get("relative_wav"), f"{name}.media.relative_wav")
            )
            duration_ms = _positive_int(raw_media.get("duration_ms"), "duration_ms")
            frequency = _positive_int(raw_media.get("frequency_hz"), "frequency_hz")
            _write_deterministic_wav(
                wav_path,
                seed=f"{scenario.id}:{key}:{language}",
                duration_ms=duration_ms,
                frequency_hz=frequency,
            )
            layout_keys = {"object_path", "import_operation", "create_event"}
            present_layout = layout_keys.intersection(raw_media)
            if present_layout and present_layout != layout_keys:
                raise SoundBankRuntimeError(
                    f"{scenario.id} localized media layout is incomplete: {key}"
                )
            if present_layout:
                sound_path = _wwise_path(
                    raw_media.get("object_path"),
                    f"{name}.media.object_path",
                )
                if (
                    not sound_path.startswith(actor_parent + "\\")
                    or "\\" in sound_path.removeprefix(actor_parent + "\\")
                ):
                    raise SoundBankRuntimeError(
                        f"{scenario.id} logical Sound escapes its fixture profile: {sound_path}"
                    )
                import_operation = _text(
                    raw_media.get("import_operation"),
                    f"{name}.media.import_operation",
                )
                if import_operation not in {"createNew", "useExisting"}:
                    raise SoundBankRuntimeError(
                        f"{scenario.id} has an unreviewed media import operation"
                    )
                create_event = raw_media.get("create_event")
                if not isinstance(create_event, bool):
                    raise SoundBankRuntimeError(
                        f"{scenario.id} localized create_event must be boolean"
                    )
            else:
                sound_path = f"{actor_parent}\\{_segment(key, 'media.key')}"
                import_operation = "createNew"
                create_event = True
            media.append(
                MediaFixture(
                    key=key,
                    wav_path=wav_path,
                    sound_path=sound_path,
                    event_path=event_path,
                    language=language,
                    duration_ms=duration_ms,
                    frequency_hz=frequency,
                    soundbank_names=(name,),
                    output_bus_path=output_bus_path,
                    import_operation=import_operation,
                    create_event=create_event,
                )
            )
            event_to_media.setdefault(event_name, []).append(key)
        inclusion_rows = tuple(
            InclusionRow(
                object_key=f"event:{_segment(event.get('name'), 'event.name')}",
                object_name=_segment(event.get("name"), "event.name"),
                filters=("events", "structures", "media"),
            )
            for event in event_rows
        )
        bank_path = f"{SOUNDBANK_DWU}\\{name}"
        banks.append(
            SoundBankFixture(name, bank_path, mode, inclusion_rows, control=False)
        )
        if mode == "existing_soundbank":
            objects.append(
                ObjectFixture(f"bank:{name}", name, "SoundBank", SOUNDBANK_DWU, bank_path)
            )

        for dependency in dependency_rows:
            path = _wwise_path(dependency.get("object_path"), "dependency.object_path")
            dep_type = _text(dependency.get("type"), "dependency.type")
            dep_name = path.rsplit("\\", 1)[-1]
            owned = path != MASTER_AUDIO_BUS
            objects.append(
                ObjectFixture(
                    f"dependency:{dep_type}:{dep_name}",
                    dep_name,
                    dep_type,
                    path.rsplit("\\", 1)[0],
                    path,
                    owned=owned,
                )
            )

    for control in _string_rows(manifest.get("control_soundbanks"), "control_soundbanks"):
        path = f"{SOUNDBANK_DWU}\\{control}"
        banks.append(SoundBankFixture(control, path, "existing_soundbank", (), True))
        objects.append(
            ObjectFixture(f"control_bank:{control}", control, "SoundBank", SOUNDBANK_DWU, path)
        )


def _compile_definition_fixture(
    scenario: OnlineScenario,
    spec: Mapping[str, Any],
    assets: Path,
    *,
    objects: list[ObjectFixture],
    banks: list[SoundBankFixture],
    definitions: list[DefinitionDocumentPlan],
) -> None:
    target_names: list[str] = []
    for raw_file in _mapping_rows(spec.get("files"), "files"):
        name = _safe_filename(_text(raw_file.get("name"), "files.name"))
        if not name.casefold().endswith((".tsv", ".txt")):
            raise SoundBankRuntimeError("Definition file must use .tsv or .txt")
        encoding = raw_file.get("encoding")
        if encoding != "utf-8_no_bom":
            raise SoundBankRuntimeError("Definition file encoding contract drifted")
        rows: list[DefinitionRowPlan] = []
        for index, raw in enumerate(_mapping_rows(raw_file.get("rows"), f"{name}.rows")):
            bank_name = _segment(raw.get("soundbank"), "definition.soundbank")
            directive = _text(raw.get("directive"), "definition.directive")
            identity = _segment(raw.get("identity"), "definition.identity")
            identity_format = _text(raw.get("identity_format"), "identity_format")
            materialization = _text(
                raw.get("identity_materialization"), "identity_materialization"
            )
            if (
                identity_format not in DEFINITION_IDENTITY_MATERIALIZATION
                or materialization
                != DEFINITION_IDENTITY_MATERIALIZATION[identity_format]
            ):
                raise SoundBankRuntimeError(
                    "Definition identity materialization contract drifted"
                )
            resolution = _text(raw.get("resolution"), "resolution")
            filters = _definition_filters(raw.get("filters"), directive=directive)
            object_type, parent = _definition_object_type(directive)
            key = f"definition:{index}:{identity}"
            rows.append(
                DefinitionRowPlan(
                    bank_name,
                    directive,
                    key,
                    identity,
                    object_type,
                    identity_format,
                    materialization,
                    filters,
                    resolution,
                )
            )
            if resolution == "unique":
                if object_type == "Effect":
                    objects.append(
                        ObjectFixture(
                            "dependency:effect-template",
                            "Radio_Squish",
                            "Effect",
                            EFFECT_TEMPLATE_PARENT,
                            EFFECT_TEMPLATE_PATH,
                            owned=False,
                        )
                    )
                objects.append(
                    ObjectFixture(
                        key,
                        identity,
                        object_type,
                        parent,
                        f"{parent}\\{identity}",
                        template_path=(
                            EFFECT_TEMPLATE_PATH if object_type == "Effect" else None
                        ),
                    )
                )
            elif resolution != "unknown":
                raise SoundBankRuntimeError("Definition resolution must be unique or unknown")
            target_names.append(bank_name)
        definitions.append(
            DefinitionDocumentPlan(name, assets / "documents" / name, tuple(rows))
        )

    if scenario.id != PROCESS_REFUSAL_ID:
        for bank_name in _unique(target_names):
            path = f"{SOUNDBANK_DWU}\\{bank_name}"
            banks.append(SoundBankFixture(bank_name, path, "existing_soundbank", ()))
            objects.append(
                ObjectFixture(f"bank:{bank_name}", bank_name, "SoundBank", SOUNDBANK_DWU, path)
            )
        control = {
            "O22-SB-PROCESS-DEF-01": "Release_Control",
            "O22-SB-PROCESS-DEF-02": "Special_Control",
            "O22-SB-PROCESS-DEF-03": "Legacy_Control",
            "O22-SB-PROCESS-DEF-04": "Release_Control",
        }.get(scenario.id)
        if control is None:
            raise SoundBankRuntimeError("unknown processDefinitionFiles scenario")
        path = f"{SOUNDBANK_DWU}\\{control}"
        banks.append(SoundBankFixture(control, path, "existing_soundbank", (), True))
        objects.append(
            ObjectFixture(f"control_bank:{control}", control, "SoundBank", SOUNDBANK_DWU, path)
        )

        if scenario.id == "O22-SB-PROCESS-DEF-04":
            debug = ObjectFixture(
                "definition:debug-before",
                "Play_Debug_Loop",
                "Event",
                EVENT_DWU,
                f"{EVENT_DWU}\\Play_Debug_Loop",
            )
            objects.append(debug)
            bank_index = next(
                index for index, value in enumerate(banks) if value.name == "Release_Core"
            )
            banks[bank_index] = replace(
                banks[bank_index],
                inclusions=(
                    InclusionRow(
                        debug.key,
                        debug.name,
                        ("events", "structures", "media"),
                    ),
                ),
            )


def _compile_external_fixture(
    scenario: OnlineScenario,
    spec: Mapping[str, Any],
    project_root: Path,
    assets: Path,
    output_root: Path,
    *,
    objects: list[ObjectFixture],
    external_documents: list[ExternalSourceDocument],
) -> None:
    media_root = assets / "media"
    document_by_name: dict[str, ExternalSourceDocument] = {}
    for raw_doc in _mapping_rows(spec.get("documents"), "documents"):
        name = _safe_filename(_text(raw_doc.get("name"), "documents.name"))
        if not name.casefold().endswith(".wsources") or raw_doc.get("schema_version") != 1:
            raise SoundBankRuntimeError("External Sources document contract drifted")
        rows: list[ExternalSourceRow] = []
        for index, raw in enumerate(_mapping_rows(raw_doc.get("entries"), f"{name}.entries")):
            relative = _safe_relative_path(raw.get("path"), f"{name}.entries[{index}].path")
            source = media_root.joinpath(*PurePosixPath(relative).parts)
            _write_deterministic_wav(
                source,
                seed=f"{scenario.id}:{relative}",
                duration_ms=220 + index * 17,
                frequency_hz=180 + index * 29,
            )
            conversion = raw.get("conversion")
            if conversion is not None:
                conversion = _segment(conversion, "conversion")
                path = f"{CONVERSION_DWU}\\{conversion}"
                objects.append(
                    ObjectFixture(
                        f"conversion:{conversion}",
                        conversion,
                        "Conversion",
                        CONVERSION_DWU,
                        path,
                    )
                )
            destination = raw.get("destination")
            if destination is None:
                destination = str(PurePosixPath(relative).with_suffix(".wem"))
            destination = _safe_relative_path(destination, "destination")
            if not destination.casefold().endswith(".wem"):
                destination = str(PurePosixPath(destination).with_suffix(".wem"))
            analysis = raw.get("analysis_types")
            if analysis is not None and analysis not in {0, 2, 4, 6}:
                raise SoundBankRuntimeError("AnalysisTypes escaped the reviewed set")
            rows.append(ExternalSourceRow(source, conversion, destination, analysis))
        path = assets / "documents" / name
        _write_wsources(
            path,
            media_root=media_root,
            project_root=project_root,
            rows=rows,
        )
        document = ExternalSourceDocument(name, path, tuple(rows))
        document_by_name[name] = document
        external_documents.append(document)

    for job in _mapping_rows(spec.get("jobs"), "jobs"):
        document_name = _text(job.get("document"), "jobs.document")
        if document_name not in document_by_name:
            raise SoundBankRuntimeError("External Sources job references an unknown document")
        _segment(job.get("platform"), "jobs.platform")
        _safe_filename(_text(job.get("output_key"), "jobs.output_key"))


def _compile_set_inclusions_fixture(
    scenario: OnlineScenario,
    spec: Mapping[str, Any],
    *,
    objects: list[ObjectFixture],
    banks: list[SoundBankFixture],
) -> None:
    mode = spec.get("mode")
    if mode not in {"add", "remove", "replace"}:
        raise SoundBankRuntimeError("setInclusions mode escaped the reviewed set")
    bank_name = _segment(spec.get("soundbank"), "soundbank")
    raw_before = _mapping_rows(spec.get("before"), "before")
    raw_requested = _mapping_rows(spec.get("requested"), "requested")
    raw_expected = _mapping_rows(spec.get("expected_after"), "expected_after")
    all_rows = [*raw_before, *raw_requested, *raw_expected]
    fixture_by_name: dict[str, ObjectFixture] = {}
    for raw in all_rows:
        name = _segment(raw.get("object"), "inclusion.object")
        if name in fixture_by_name:
            continue
        object_type, parent = _inclusion_object_type(name)
        fixture = ObjectFixture(
            f"inclusion:{name}",
            name,
            object_type,
            parent,
            f"{parent}\\{name}",
        )
        fixture_by_name[name] = fixture
        objects.append(fixture)
    before = tuple(
        InclusionRow(
            fixture_by_name[_text(raw.get("object"), "before.object")].key,
            _text(raw.get("object"), "before.object"),
            _filters(raw.get("filters")),
        )
        for raw in raw_before
    )
    expected = tuple(
        (
            _text(raw.get("object"), "expected.object"),
            _filters(raw.get("filters")),
        )
        for raw in raw_expected
    )
    if expected != _apply_named_inclusion_mode(raw_before, raw_requested, str(mode)):
        raise SoundBankRuntimeError(
            f"{scenario.id} expected_after does not follow the declared inclusion mode"
        )
    bank_path = f"{SOUNDBANK_DWU}\\{bank_name}"
    banks.append(SoundBankFixture(bank_name, bank_path, "existing_soundbank", before))
    objects.append(
        ObjectFixture(f"bank:{bank_name}", bank_name, "SoundBank", SOUNDBANK_DWU, bank_path)
    )
    for control in _string_rows(spec.get("control_soundbanks"), "control_soundbanks"):
        path = f"{SOUNDBANK_DWU}\\{control}"
        banks.append(SoundBankFixture(control, path, "existing_soundbank", (), True))
        objects.append(
            ObjectFixture(f"control_bank:{control}", control, "SoundBank", SOUNDBANK_DWU, path)
        )


def _validate_fixture_uniqueness(
    objects: Sequence[ObjectFixture],
    media: Sequence[MediaFixture],
    banks: Sequence[SoundBankFixture],
) -> None:
    owned_paths = [row.path.casefold() for row in objects if row.owned]
    if len(owned_paths) != len(set(owned_paths)):
        duplicates = sorted(key for key, count in Counter(owned_paths).items() if count > 1)
        raise SoundBankRuntimeError(f"fixture object paths are not unique: {duplicates}")
    media_keys = [row.key for row in media]
    if len(media_keys) != len(set(media_keys)):
        raise SoundBankRuntimeError("fixture media keys are not unique")
    bank_names = [row.name.casefold() for row in banks]
    if len(bank_names) != len(set(bank_names)):
        raise SoundBankRuntimeError("fixture SoundBank names are not unique")


class PreparedSoundBankRuntime:
    """Single-use trusted runtime bound to one fresh scenario project."""

    def __init__(
        self,
        blueprint: SoundBankBlueprint,
        backend: SoundBankRuntimeBackend,
    ) -> None:
        self.blueprint = blueprint
        self.backend = backend
        self.materialized: MaterializedSoundBankCase | None = None
        self.hidden_before: SoundBankSnapshot | None = None
        self._created_ids: list[str] = []
        self._closed = False

    def prepare(self) -> MaterializedSoundBankCase:
        if self.materialized is not None or self.hidden_before is not None or self._closed:
            raise SoundBankRuntimeError("SoundBank runtime is single-use")
        project_info = _validate_project_info(
            self.backend.get_project_info(),
            blueprint=self.blueprint,
        )
        if self.blueprint.scenario_id == PROCESS_REFUSAL_ID:
            for _key, object_type, name in PROCESS_REFUSAL_ABSENT_IDENTITIES:
                rows = self.backend.read_objects(
                    object_type=object_type,
                    name=name,
                    fields=OBJECT_FIELDS,
                )
                if rows:
                    raise SoundBankRuntimeError(
                        "refusal fixture identity exists before setup: "
                        f"{object_type} {name!r}"
                    )
        object_ids: dict[str, str] = {}
        short_ids: dict[str, int] = {}
        media_ids: dict[str, int] = {}

        # A fixture path that already exists would make before-state ownership
        # ambiguous.  Reviewed dependencies are the only non-owned exceptions.
        for fixture in self.blueprint.object_fixtures:
            rows = self.backend.read_objects(path=fixture.path, fields=OBJECT_FIELDS)
            if fixture.owned and rows:
                raise SoundBankRuntimeError(
                    f"scenario-owned Wwise path exists before setup: {fixture.path}"
                )
            if not fixture.owned:
                if len(rows) != 1:
                    raise SoundBankRuntimeError(
                        f"required project dependency is not unique: {fixture.path}"
                    )
                object_id, short_id = _row_identity(rows[0], fixture.path)
                object_ids[fixture.key] = object_id
                short_ids[fixture.key] = short_id

        declared_sounds: dict[str, str] = {}
        checked_media_paths: dict[str, str] = {}
        for fixture in self.blueprint.media_fixtures:
            sound_key = fixture.sound_path.casefold()
            event_key = fixture.event_path.casefold()
            declared_event = declared_sounds.get(sound_key)
            if fixture.import_operation == "createNew":
                if declared_event is not None:
                    raise SoundBankRuntimeError(
                        f"localized createNew repeats a logical Sound: {fixture.sound_path}"
                    )
                if not fixture.create_event:
                    raise SoundBankRuntimeError(
                        "localized createNew must create its Event"
                    )
                declared_sounds[sound_key] = event_key
            elif fixture.import_operation == "useExisting":
                if declared_event != event_key:
                    raise SoundBankRuntimeError(
                        "localized useExisting must follow the createNew row for the "
                        f"same logical Sound/Event: {fixture.sound_path}"
                    )
                if fixture.create_event:
                    raise SoundBankRuntimeError(
                        "localized useExisting must not recreate its Event"
                    )
            else:
                raise SoundBankRuntimeError(
                    f"unreviewed media import operation: {fixture.import_operation}"
                )
            for kind, path in (("Sound", fixture.sound_path), ("Event", fixture.event_path)):
                previous = checked_media_paths.get(path.casefold())
                if previous is not None:
                    if previous != kind:
                        raise SoundBankRuntimeError(
                            f"media fixture path is reused incompatibly: {path}"
                        )
                    continue
                checked_media_paths[path.casefold()] = kind
                if self.backend.read_objects(path=path, fields=OBJECT_FIELDS):
                    raise SoundBankRuntimeError(
                        f"scenario-owned media {kind} path exists before setup: {path}"
                    )

        for fixture in self.blueprint.object_fixtures:
            if not fixture.owned:
                continue
            object_id = self.backend.create_object(fixture)
            self._created_ids.append(object_id)
            rows = self.backend.read_objects(path=fixture.path, fields=OBJECT_FIELDS)
            if len(rows) != 1:
                raise SoundBankRuntimeError(
                    f"created fixture did not resolve once: {fixture.path}"
                )
            if fixture.object_type == "Conversion":
                # Wwise 2022 Conversion ShareSets are authoring identities and
                # may not expose an object Short ID.  External Source documents
                # bind them by reviewed name, so requiring an unrelated
                # SoundEngine identity blocks a valid fixture before the API is
                # tested.  Still validate a present value strictly.
                live_id = _row_guid(rows[0], fixture.path)
                short_id = _optional_row_short_id(rows[0], fixture.path)
            else:
                live_id, short_id = _row_identity(rows[0], fixture.path)
            if not _same_identity(live_id, object_id):
                raise SoundBankRuntimeError(
                    f"created fixture identity mismatch: {fixture.path}"
                )
            if str(rows[0].get("type")) != fixture.object_type:
                raise SoundBankRuntimeError(
                    f"created fixture type mismatch: {fixture.path}"
                )
            object_ids[fixture.key] = live_id
            if short_id is not None:
                short_ids[fixture.key] = short_id

        logical_sound_ids: dict[str, str] = {}
        event_graphs: dict[str, EventGraphState] = {}
        for fixture in self.blueprint.media_fixtures:
            imported_ids = self.backend.import_media(fixture)
            self._created_ids.extend(imported_ids)
            sound_rows = self.backend.read_objects(
                path=fixture.sound_path,
                fields=MEDIA_OBJECT_FIELDS,
                language=fixture.language,
            )
            event_rows = self.backend.read_objects(
                path=fixture.event_path,
                fields=OBJECT_FIELDS,
            )
            if len(sound_rows) != 1 or len(event_rows) != 1:
                raise SoundBankRuntimeError(
                    f"media setup did not create exact Sound/Event: {fixture.key}"
                )
            sound_id, sound_short = _row_identity(sound_rows[0], fixture.sound_path)
            event_id, event_short = _row_identity(event_rows[0], fixture.event_path)
            sound_key = fixture.sound_path.casefold()
            previous_sound_id = logical_sound_ids.setdefault(sound_key, sound_id)
            if not _same_identity(previous_sound_id, sound_id):
                raise SoundBankRuntimeError(
                    f"localized Sound GUID drifted across languages: {fixture.sound_path}"
                )
            event_graph = self.backend.read_event_graph(fixture.event_path)
            if event_graph is None:
                raise SoundBankRuntimeError(
                    f"media setup Event graph is absent: {fixture.event_path}"
                )
            if not _same_identity(event_graph.event_id, event_id):
                raise SoundBankRuntimeError(
                    f"media setup Event GUID drifted: {fixture.event_path}"
                )
            if (
                event_graph.action_types != (1,)
                or len(event_graph.action_ids) != 1
                or len(event_graph.target_ids) != 1
                or not _same_identity(event_graph.target_ids[0], sound_id)
            ):
                raise SoundBankRuntimeError(
                    f"media setup did not prove one Play Action targeting its logical Sound: "
                    f"{fixture.event_path}"
                )
            event_key = fixture.event_path.casefold()
            previous_graph = event_graphs.setdefault(event_key, event_graph)
            if previous_graph != event_graph:
                raise SoundBankRuntimeError(
                    f"localized useExisting changed Event/Action/target GUIDs: "
                    f"{fixture.event_path}"
                )
            bus_rows = self.backend.read_objects(
                path=fixture.output_bus_path,
                fields=OBJECT_FIELDS,
            )
            if len(bus_rows) != 1:
                raise SoundBankRuntimeError(
                    f"media output Bus did not resolve once: {fixture.output_bus_path}"
                )
            bus_id, _ = _row_identity(bus_rows[0], fixture.output_bus_path)
            output_bus = _payload_identity(sound_rows[0].get("OutputBus"))
            if output_bus is None or not _same_identity(output_bus, bus_id):
                raise SoundBankRuntimeError(
                    f"media setup did not bind the reviewed OutputBus: {fixture.key}"
                )
            # Wwise return rows have varied by version/build.  The exact-path
            # readback is the ownership authority, so always bind both roots
            # into cleanup even if audio.import omitted one from its result.
            self._created_ids.extend((sound_id, event_id))
            object_ids[f"media:{fixture.key}"] = sound_id
            short_ids[f"media:{fixture.key}"] = sound_short
            object_ids[f"event:{event_rows[0].get('name')}"] = event_id
            short_ids[f"event:{event_rows[0].get('name')}"] = event_short
            object_ids[
                f"event_action:{event_rows[0].get('name')}"
            ] = event_graph.action_ids[0]

            media_source_rows: list[Mapping[str, Any]] = []
            for imported_id in imported_ids:
                rows = self.backend.read_objects(
                    object_id=imported_id,
                    fields=MEDIA_SOURCE_FIELDS,
                    language=fixture.language,
                )
                if len(rows) != 1:
                    continue
                row_type = str(rows[0].get("type", ""))
                if row_type in {"AudioFileSource", "Audio Source"}:
                    media_source_rows.append(rows[0])
            if len(media_source_rows) != 1:
                raise SoundBankRuntimeError(
                    f"media fixture {fixture.key} must bind exactly one imported "
                    f"AudioFileSource; got {len(media_source_rows)}"
                )
            source_row = media_source_rows[0]
            source_id, media_id = _row_media_identity(
                source_row, f"media source {fixture.key}"
            )
            source_parent = _payload_identity(source_row.get("parent"))
            if source_parent is None or not _same_identity(source_parent, sound_id):
                raise SoundBankRuntimeError(
                    f"media source {fixture.key} parent does not match imported Sound"
                )
            source_state = _read_media_source_state(
                self.backend,
                fixture,
                sandbox_root=self.blueprint.sandbox_root,
            )
            if not _same_identity(source_state.sound_id, sound_id):
                raise SoundBankRuntimeError(
                    f"localized activeSource Sound identity mismatch: {fixture.key}"
                )
            if not _same_identity(source_state.source_id, source_id):
                raise SoundBankRuntimeError(
                    f"localized activeSource does not identify the imported source: "
                    f"{fixture.key}"
                )
            if source_state.media_id != media_id:
                raise SoundBankRuntimeError(
                    f"localized activeSource Media ID mismatch: {fixture.key}"
                )
            expected_language = _canonical_language(fixture.language)
            if source_state.language != expected_language:
                raise SoundBankRuntimeError(
                    f"localized AudioFileSource language mismatch for {fixture.key}: "
                    f"expected {expected_language}, got {source_state.language}"
                )
            input_proof = _file_proof(fixture.wav_path, fixture.wav_path.parent)
            if source_state.copied_file.sha256 != input_proof.sha256:
                raise SoundBankRuntimeError(
                    f"localized copied WAV bytes differ from the sealed input: "
                    f"{fixture.key}"
                )
            object_ids[f"media_source:{fixture.key}"] = source_id
            media_ids[fixture.key] = media_id

        # Every existing fixture Bank receives its reviewed pre-state.  Topic
        # and generation cases bind Event identities produced by audio.import;
        # Definition and setInclusions cases bind setup object identities.
        for bank in self.blueprint.soundbanks:
            if bank.project_object_mode != "existing_soundbank":
                continue
            bank_id = object_ids.get(f"bank:{bank.name}") or object_ids.get(
                f"control_bank:{bank.name}"
            )
            if bank_id is None:
                raise SoundBankRuntimeError(
                    f"fixture SoundBank lacks a live identity: {bank.name}"
                )
            initial = [
                (_require_key(object_ids, row.object_key), row.filters)
                for row in bank.inclusions
            ]
            if initial:
                self.backend.set_inclusions(bank_id, "replace", initial)

        self.backend.save_project()
        platform_ids = _project_identity_map(project_info.get("platforms"), "platform")
        language_ids = _project_identity_map(project_info.get("languages"), "language")
        _add_language_aliases(language_ids)

        if self.blueprint.api == SOUNDBANK_TOPIC:
            _generate_topic_init(
                self.blueprint,
                self.backend,
                project_info,
            )

        materialized = _materialize_bound_case(
            self.blueprint,
            project_info=project_info,
            object_ids=object_ids,
            short_ids=short_ids,
            media_ids=media_ids,
            platform_ids=platform_ids,
            language_ids=language_ids,
        )
        _assert_materialized_case(materialized)
        self.materialized = materialized
        before = self.snapshot()
        _validate_before_state(materialized, before)
        self.hidden_before = before
        return materialized

    def render_prompt(self) -> str:
        return self._require_materialized().render_prompt()

    @property
    def operation_requests(self) -> tuple[Mapping[str, Any], ...]:
        return self._require_materialized().operation_requests

    @property
    def topic_plan(self) -> TopicPlan | None:
        return self._require_materialized().topic_plan

    def snapshot(self, *, save: bool = False) -> SoundBankSnapshot:
        materialized = self._require_materialized()
        if self._closed:
            raise SoundBankRuntimeError("SoundBank runtime is closed")
        if save:
            self.backend.save_project()
        objects: list[ObjectState] = []
        for fixture in materialized.blueprint.object_fixtures:
            rows = self.backend.read_objects(path=fixture.path, fields=OBJECT_FIELDS)
            if len(rows) > 1:
                raise SoundBankRuntimeError(
                    f"fixture path resolved more than once: {fixture.path}"
                )
            if rows:
                if fixture.object_type == "Conversion":
                    object_id = _row_guid(rows[0], fixture.path)
                    _optional_row_short_id(rows[0], fixture.path)
                else:
                    object_id, _ = _row_identity(rows[0], fixture.path)
                object_type = str(rows[0].get("type"))
            else:
                object_id = None
                object_type = None
            objects.append(ObjectState(fixture.key, object_id, fixture.path, object_type))

        # Audio-import-created Events and Sounds are not all explicit object
        # fixtures, so they are captured independently by exact path.
        for fixture in materialized.blueprint.media_fixtures:
            for label, path in (
                (f"media:{fixture.key}", fixture.sound_path),
                (f"event:{fixture.key}", fixture.event_path),
            ):
                rows = self.backend.read_objects(path=path, fields=OBJECT_FIELDS)
                if len(rows) > 1:
                    raise SoundBankRuntimeError(f"media fixture path is ambiguous: {path}")
                if rows:
                    object_id, _ = _row_identity(rows[0], path)
                    object_type = str(rows[0].get("type"))
                else:
                    object_id = None
                    object_type = None
                objects.append(ObjectState(label, object_id, path, object_type))

        # Every requested language has its own active AudioFileSource even
        # when the three rows share one logical Sound.  Seal that language
        # binding and the copied Originals file proof into the existing object
        # snapshot so source switching, language drift, path movement, or byte
        # tampering is visible without expanding the archived snapshot schema.
        for fixture in materialized.blueprint.media_fixtures:
            source = _read_media_source_state(
                self.backend,
                fixture,
                sandbox_root=materialized.blueprint.sandbox_root,
            )
            proof = source.copied_file
            objects.append(
                ObjectState(
                    f"localized_source:{fixture.key}",
                    source.source_id,
                    f"{fixture.sound_path}@ActiveSource[{fixture.language}]",
                    json.dumps(
                        {
                            "kind": "AudioFileSource",
                            "sound_id": source.sound_id,
                            "media_id": source.media_id,
                            "language": source.language,
                            "copied_relative_path": proof.relative_path,
                            "copied_size": proof.size,
                            "copied_sha256": proof.sha256,
                            "copied_mtime_ns": proof.mtime_ns,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                )
            )

        # Seal the Event's single Play Action and its exact target GUID as part
        # of the existing object snapshot.  This keeps the archive schema
        # unchanged while making Action recreation or retargeting visible to
        # preview and post-generation equality checks.
        event_paths = sorted(
            {fixture.event_path for fixture in materialized.blueprint.media_fixtures},
            key=str.casefold,
        )
        for event_path in event_paths:
            graph = self.backend.read_event_graph(event_path)
            if graph is None:
                continue
            if not (
                len(graph.action_ids)
                == len(graph.target_ids)
                == len(graph.action_types)
            ):
                raise SoundBankRuntimeError(
                    f"Event graph cardinality is inconsistent: {event_path}"
                )
            for index, (action_id, target_id, action_type) in enumerate(
                zip(
                    graph.action_ids,
                    graph.target_ids,
                    graph.action_types,
                    strict=True,
                )
            ):
                objects.append(
                    ObjectState(
                        f"event_action:{event_path}:{index}",
                        action_id,
                        f"{event_path}@Action[{index}]",
                        f"Action:{action_type}",
                    )
                )
                objects.append(
                    ObjectState(
                        f"event_target:{event_path}:{index}",
                        target_id,
                        f"{event_path}@Target[{index}]",
                        "Target",
                    )
                )

        # PROCESS-DEF-05 is valuable only if both the source Event and target
        # SoundBank are independently proven absent.  Preserve those typed-name
        # reads in every snapshot so zero-dispatch verification also catches a
        # partially-created target that was never part of the owned fixture tree.
        if materialized.scenario_id == PROCESS_REFUSAL_ID:
            for key, expected_type, name in PROCESS_REFUSAL_ABSENT_IDENTITIES:
                rows = self.backend.read_objects(
                    object_type=expected_type,
                    name=name,
                    fields=OBJECT_FIELDS,
                )
                if len(rows) > 1:
                    raise SoundBankRuntimeError(
                        f"refusal identity is ambiguous: {expected_type} {name!r}"
                    )
                if rows:
                    object_id, _ = _row_identity(rows[0], name)
                    object_type = str(rows[0].get("type"))
                else:
                    object_id = None
                    object_type = None
                objects.append(
                    ObjectState(
                        key,
                        object_id,
                        f"typed-name:{expected_type}:{name}",
                        object_type,
                    )
                )

        bank_states: list[BankState] = []
        for bank in materialized.blueprint.soundbanks:
            rows = self.backend.read_objects(
                object_type="SoundBank",
                name=bank.name,
                fields=OBJECT_FIELDS,
            )
            if len(rows) > 1:
                raise SoundBankRuntimeError(f"SoundBank name is ambiguous: {bank.name}")
            if not rows:
                bank_states.append(BankState(bank.name, None, ()))
                continue
            bank_id, _ = _row_identity(rows[0], bank.name)
            inclusion_rows = _normalize_live_inclusions(
                self.backend.read_inclusions(bank_id)
            )
            bank_states.append(BankState(bank.name, bank_id, inclusion_rows))

        return SoundBankSnapshot(
            scenario_id=materialized.scenario_id,
            objects=tuple(sorted(objects, key=lambda row: (row.path, row.key))),
            banks=tuple(sorted(bank_states, key=lambda row: row.name.casefold())),
            project_files=_tree_entries(
                materialized.blueprint.sandbox_root,
                include=lambda path: path.suffix.casefold() in {".wproj", ".wwu"},
            ),
            input_files=tuple(
                _file_proof(Path(proof.path), materialized.blueprint.io_root)
                for proof in materialized.input_files
            ),
            output_files=_tree_entries(
                materialized.blueprint.io_root,
                include=lambda path: _is_output_file(path, materialized),
            ),
        )

    def verify_preview_unchanged(self) -> SoundBankVerification:
        before = self._require_before()
        after = self.snapshot()
        failures = _snapshot_drift(before, after)
        return SoundBankVerification(
            before.scenario_id,
            "preview",
            not failures,
            tuple(failures),
            before,
            after,
        )

    def verify_zero_dispatch(
        self,
        structured_error: Mapping[str, Any],
    ) -> SoundBankVerification:
        materialized = self._require_materialized()
        if materialized.blueprint.zero_dispatch_error_code is None:
            raise SoundBankRuntimeError("zero-dispatch verifier used for a writable case")
        before = self._require_before()
        after = self.snapshot()
        failures = _snapshot_drift(before, after)
        if structured_error.get("contract") != "waapi-skill.gateway-result/v1":
            failures.append("refusal did not use the gateway result contract")
        if structured_error.get("ok") is not False:
            failures.append("refusal result was not a structured failure")
        if structured_error.get("status") != "error":
            failures.append("refusal result status was not error")
        actual_code = structured_error.get("error_code")
        if actual_code is None and isinstance(structured_error.get("error"), Mapping):
            actual_code = structured_error["error"].get("code")
        if actual_code != materialized.blueprint.zero_dispatch_error_code:
            failures.append(
                "refusal error code mismatch: "
                f"expected {materialized.blueprint.zero_dispatch_error_code}, got {actual_code}"
            )
        if structured_error.get("command") != "preview":
            failures.append("refusal was not produced by the exact gateway preview command")
        return SoundBankVerification(
            before.scenario_id,
            "zero_dispatch",
            not failures,
            tuple(failures),
            before,
            after,
        )

    def verify_after_execution(self) -> SoundBankVerification:
        materialized = self._require_materialized()
        if materialized.blueprint.expected_primary_dispatch_count == 0:
            raise SoundBankRuntimeError("refusal case must use verify_zero_dispatch")
        if materialized.blueprint.api == SOUNDBANK_TOPIC:
            raise SoundBankRuntimeError("topic case must use verify_topic")
        before = self._require_before()
        after = self.snapshot(save=True)
        failures = _validate_after_state(materialized, before, after)
        return SoundBankVerification(
            before.scenario_id,
            "after_execution",
            not failures,
            tuple(failures),
            before,
            after,
        )

    def verify_topic(
        self,
        payloads: Sequence[Mapping[str, Any]],
    ) -> tuple[TopicVerification, SoundBankVerification]:
        materialized = self._require_materialized()
        plan = materialized.topic_plan
        if plan is None:
            raise SoundBankRuntimeError("topic verifier used for a function case")
        topic_verification = verify_topic_payloads(
            materialized.scenario_id,
            plan,
            payloads,
            control_soundbanks=tuple(
                bank.name for bank in materialized.blueprint.soundbanks if bank.control
            ),
        )
        before = self._require_before()
        after = self.snapshot()
        failures = _validate_after_state(materialized, before, after)
        artifact_verification = SoundBankVerification(
            before.scenario_id,
            "topic_artifacts",
            not failures,
            tuple(failures),
            before,
            after,
        )
        return topic_verification, artifact_verification

    def cleanup_success(self) -> tuple[str, ...]:
        materialized = self._require_materialized()
        if self._closed:
            raise SoundBankRuntimeError("SoundBank runtime is already closed")
        deleted: list[str] = []
        for object_id in reversed(_unique(self._created_ids)):
            rows = self.backend.read_objects(object_id=object_id, fields=OBJECT_FIELDS)
            if rows:
                self.backend.delete_object(object_id)
                deleted.append(object_id)
        self.backend.save_project()
        residual = [
            fixture.path
            for fixture in materialized.blueprint.object_fixtures
            if fixture.owned
            and self.backend.read_objects(path=fixture.path, fields=OBJECT_FIELDS)
        ]
        residual.extend(
            path
            for fixture in materialized.blueprint.media_fixtures
            for path in (fixture.sound_path, fixture.event_path)
            if self.backend.read_objects(path=path, fields=OBJECT_FIELDS)
        )
        if residual:
            raise SoundBankRuntimeError(f"SoundBank cleanup left Wwise paths: {residual}")
        for root in (materialized.blueprint.asset_root, materialized.blueprint.output_root):
            _require_under(root, materialized.blueprint.io_root, "cleanup root")
            if root.exists():
                if root.is_symlink():
                    raise SoundBankRuntimeError("cleanup root became a symlink")
                shutil.rmtree(root)
            if root.exists():
                raise SoundBankRuntimeError(f"cleanup root still exists: {root}")
        self._closed = True
        return tuple(deleted)

    def _require_materialized(self) -> MaterializedSoundBankCase:
        if self.materialized is None:
            raise SoundBankRuntimeError("SoundBank runtime has not been prepared")
        return self.materialized

    def _require_before(self) -> SoundBankSnapshot:
        if self.hidden_before is None:
            raise SoundBankRuntimeError("SoundBank runtime has no before snapshot")
        return self.hidden_before


def prepare_soundbank_runtime(
    scenario: OnlineScenario,
    *,
    version: str,
    sandbox_project: str | Path,
    io_root: str | Path,
    asset_root: str | Path,
    backend: SoundBankRuntimeBackend,
) -> PreparedSoundBankRuntime:
    """Build and prepare one engine-consumable SoundBank runtime."""

    runtime = PreparedSoundBankRuntime(
        build_soundbank_blueprint(
            scenario,
            version=version,
            sandbox_project=sandbox_project,
            io_root=io_root,
            asset_root=asset_root,
        ),
        backend,
    )
    runtime.prepare()
    return runtime


def verify_topic_payloads(
    scenario_id: str,
    plan: TopicPlan,
    payloads: Sequence[Mapping[str, Any]],
    *,
    control_soundbanks: Sequence[str] = (),
) -> TopicVerification:
    """Validate the exact hidden GUID/platform/language event multiset."""

    failures: list[str] = []
    observed: list[tuple[str, str, str | None]] = []
    if len(payloads) != plan.event_count:
        failures.append(
            f"topic event cardinality mismatch: expected {plan.event_count}, got {len(payloads)}"
        )
    control_names = {name.casefold() for name in control_soundbanks}
    expected_by_key = {row.key: row for row in plan.expected_events}
    if len(expected_by_key) != len(plan.expected_events):
        failures.append("topic plan contains duplicate hidden identity cells")
    for index, payload in enumerate(payloads):
        if not isinstance(payload, Mapping):
            failures.append(f"topic payload {index} is not an object")
            continue
        if "soundbank" not in payload or "platform" not in payload:
            failures.append(f"topic payload {index} lacks soundbank/platform")
            continue
        soundbank = _strict_topic_payload_identity(
            payload.get("soundbank"),
            context=f"topic payload {index}.soundbank",
            failures=failures,
        )
        platform = _strict_topic_payload_identity(
            payload.get("platform"),
            context=f"topic payload {index}.platform",
            failures=failures,
        )
        raw_language = payload.get("language")
        language = (
            _strict_topic_payload_identity(
                raw_language,
                context=f"topic payload {index}.language",
                failures=failures,
            )
            if raw_language is not None
            else None
        )
        if soundbank is None or platform is None:
            continue
        if raw_language is not None and language is None:
            continue
        soundbank_id, soundbank_name = soundbank
        platform_id, platform_name = platform
        language_id = language[0] if language is not None else None
        language_name = language[1] if language is not None else None
        if (
            soundbank_name.casefold() in control_names
            or soundbank_name.casefold() == "init"
        ):
            failures.append(f"topic payload {index} is an Init/control notification")
        key = (
            soundbank_id.casefold(),
            platform_id.casefold(),
            language_id.casefold() if language_id else None,
        )
        expected_row = expected_by_key.get(key)
        if expected_row is not None:
            if soundbank_name.casefold() != expected_row.soundbank_name.casefold():
                failures.append(
                    f"topic payload {index} soundbank name does not match its hidden GUID"
                )
            if platform_name.casefold() != expected_row.platform_name.casefold():
                failures.append(
                    f"topic payload {index} platform name does not match its hidden GUID"
                )
            expected_language_name = expected_row.language_name
            if (
                expected_language_name is None
                and language_name is not None
            ) or (
                expected_language_name is not None
                and (
                    language_name is None
                    or language_name.casefold() != expected_language_name.casefold()
                )
            ):
                failures.append(
                    f"topic payload {index} language name does not match its hidden GUID"
                )
        observed.append(key)
    expected = [row.key for row in plan.expected_events]
    if Counter(observed) != Counter(expected):
        failures.append(
            "topic event identity multiset mismatch: "
            f"expected={sorted(expected)} observed={sorted(observed)}"
        )
    if len(observed) != len(set(observed)):
        failures.append("topic payloads contain a duplicate identity cell")
    return TopicVerification(
        scenario_id,
        not failures,
        tuple(failures),
        tuple(observed),
        tuple(expected),
    )


def _materialize_bound_case(
    blueprint: SoundBankBlueprint,
    *,
    project_info: Mapping[str, Any],
    object_ids: Mapping[str, str],
    short_ids: Mapping[str, int],
    media_ids: Mapping[str, int],
    platform_ids: Mapping[str, str],
    language_ids: Mapping[str, str],
) -> MaterializedSoundBankCase:
    spec = blueprint.asset_spec
    visible: dict[str, str]
    prompt_sources: dict[str, Any] = {}
    requests: tuple[Mapping[str, Any], ...]
    topic_plan: TopicPlan | None = None
    expected_artifacts: list[ExpectedArtifact] = []
    allowed_dynamic_artifact_roots: list[Path] = []

    if blueprint.api == "ak.wwise.core.soundbank.generate":
        arguments = _generation_operation_arguments(
            _mapping(spec.get("request"), "request"),
            io_root=blueprint.io_root,
            object_ids=object_ids,
        )
        requests = (_operation_request(blueprint.version, "soundbank.generate", arguments),)
        expected_artifacts.extend(
            _generation_artifacts(
                blueprint,
                project_info,
                [spec["request"]],
                media_ids,
            )
        )
        _materialize_preexisting_artifacts(blueprint, project_info, expected_artifacts)
        allowed_dynamic_artifact_roots.append(
            _generation_cache_root(blueprint, project_info)
        )
        project_info_projection = build_soundbank_generation_prompt_projection(
            project_info,
            arguments,
            io_root=blueprint.io_root,
        )
        visible = {
            "generation_request": _visible_json(arguments),
            "build_locations": _visible_json(
                render_soundbank_generation_build_locations(
                    project_info_projection,
                    io_root=blueprint.io_root,
                )
            ),
        }
        prompt_sources["soundbank_generate_project_info"] = project_info_projection
    elif blueprint.api == SOUNDBANK_TOPIC:
        publishers: list[TopicPublisher] = []
        all_expected: list[TopicExpectedEvent] = []
        raw_publishers = _mapping_rows(spec.get("publisher_requests"), "publisher_requests")
        for raw in raw_publishers:
            if raw.get("rebuildInitBank") is not False:
                raise SoundBankRuntimeError(
                    "topic publisher must preserve the pre-generated Init"
                )
            raw_without_events = {
                key: value for key, value in raw.items() if key != "expected_events"
            }
            arguments = _generation_operation_arguments(
                raw_without_events,
                io_root=blueprint.io_root,
                object_ids=object_ids,
            )
            expected_rows = tuple(
                _bind_topic_event(
                    row,
                    object_ids=object_ids,
                    platform_ids=platform_ids,
                    language_ids=language_ids,
                )
                for row in _mapping_rows(raw.get("expected_events"), "expected_events")
            )
            publishers.append(
                TopicPublisher(
                    _operation_request(
                        blueprint.version,
                        "soundbank.generate",
                        arguments,
                    ),
                    expected_rows,
                )
            )
            all_expected.extend(expected_rows)
        event_count = _positive_int(spec.get("expected_topic_event_count"), "event_count")
        if len(all_expected) != event_count:
            raise SoundBankRuntimeError(
                "topic expected event count does not equal publisher event rows"
            )
        topic_match = _common_topic_match(all_expected)
        topic_plan = TopicPlan(
            SOUNDBANK_TOPIC,
            event_count,
            MappingProxyType(topic_match) if topic_match is not None else None,
            MappingProxyType({"return": list(SOUNDBANK_TOPIC_RETURN_FIELDS)}),
            tuple(all_expected),
            tuple(publishers),
            subscribe_before_publish=True,
            init_generated_before_subscribe=True,
            reject_n_plus_one=True,
        )
        requests = ()
        expected_artifacts.extend(
            _generation_artifacts(
                blueprint,
                project_info,
                raw_publishers,
                media_ids,
            )
        )
        _materialize_preexisting_artifacts(blueprint, project_info, expected_artifacts)
        allowed_dynamic_artifact_roots.append(
            _generation_cache_root(blueprint, project_info)
        )
        visible = {}
    elif blueprint.api == "ak.wwise.core.soundbank.processDefinitionFiles":
        file_proofs = _materialize_definition_documents(
            blueprint,
            object_ids=object_ids,
            short_ids=short_ids,
        )
        arguments = {
            "files": [proof.path for proof in file_proofs],
            "io_root": str(blueprint.io_root),
        }
        requests = (
            _operation_request(
                blueprint.version,
                "soundbank.processDefinitionFiles",
                arguments,
            ),
        )
        visible = {
            "definition_files": _visible_json(arguments["files"]),
            "io_root": str(blueprint.io_root),
        }
    elif blueprint.api == "ak.wwise.core.soundbank.convertExternalSources":
        sources: list[dict[str, str]] = []
        by_name = {row.name: row for row in blueprint.external_documents}
        for job in _mapping_rows(spec.get("jobs"), "jobs"):
            document = by_name[_text(job.get("document"), "jobs.document")]
            platform = _project_name(
                _text(job.get("platform"), "jobs.platform"),
                project_info.get("platforms"),
                aliases=("name", "baseName"),
            )
            output_key = _safe_filename(_text(job.get("output_key"), "output_key"))
            root = blueprint.output_root / output_key
            root.mkdir(parents=True, exist_ok=False)
            sources.append(
                {
                    "input": str(document.path),
                    "platform": platform,
                    "output": str(root),
                }
            )
            for row in document.rows:
                expected_artifacts.append(
                    ExpectedArtifact(
                        "external",
                        root.joinpath(*PurePosixPath(row.destination).parts),
                        None,
                        platform,
                        None,
                        True,
                    )
                )
        arguments = {"sources": sources, "io_root": str(blueprint.io_root)}
        requests = (
            _operation_request(
                blueprint.version,
                "soundbank.convertExternalSources",
                arguments,
            ),
        )
        visible = {"source_jobs": _visible_json(sources)}
    else:
        bank_name = _text(spec.get("soundbank"), "soundbank")
        bank = next(row for row in blueprint.soundbanks if row.name == bank_name)
        inclusions = [
            {
                "object": {
                    "kind": "path",
                    "value": _fixture_for_inclusion_name(blueprint, _text(row.get("object"), "object")).path,
                },
                "filters": list(_filters(row.get("filters"))),
            }
            for row in _mapping_rows(spec.get("requested"), "requested")
        ]
        arguments = {
            "soundbank": {"kind": "path", "value": bank.path},
            "mode": _text(spec.get("mode"), "mode"),
            "inclusions": inclusions,
        }
        requests = (
            _operation_request(
                blueprint.version,
                "soundbank.setInclusions",
                arguments,
            ),
        )
        visible = {
            "soundbank_path": bank.path,
            "inclusion_changes": _visible_json(
                {"mode": arguments["mode"], "inclusions": inclusions}
            ),
        }

    expected_visible = {row.name for row in blueprint.scenario.visible_inputs}
    if set(visible) != expected_visible:
        raise SoundBankRuntimeError(
            f"{blueprint.scenario_id} visible input drift: "
            f"expected={sorted(expected_visible)} actual={sorted(visible)}"
        )
    inputs = _collect_input_proofs(blueprint)
    return MaterializedSoundBankCase(
        blueprint,
        MappingProxyType(dict(visible)),
        MappingProxyType(_json_clone(prompt_sources)),
        tuple(requests),
        topic_plan,
        inputs,
        _dedupe_artifacts(expected_artifacts),
        tuple(sorted(set(allowed_dynamic_artifact_roots), key=str)),
        MappingProxyType(dict(object_ids)),
        MappingProxyType(dict(short_ids)),
        MappingProxyType(dict(media_ids)),
        MappingProxyType(dict(platform_ids)),
        MappingProxyType(dict(language_ids)),
    )


def _generation_operation_arguments(
    raw: Mapping[str, Any],
    *,
    io_root: Path,
    object_ids: Mapping[str, str],
) -> dict[str, Any]:
    soundbanks: list[dict[str, Any]] = []
    for bank in _mapping_rows(raw.get("soundbanks"), "soundbanks"):
        item: dict[str, Any] = {
            "name": _segment(bank.get("name"), "soundbank.name"),
            "artifact_expectation": _text(
                bank.get("artifact_expectation"), "artifact_expectation"
            ),
        }
        if item["artifact_expectation"] not in {"nonlocalized", "localized", "mixed"}:
            raise SoundBankRuntimeError("unreviewed SoundBank artifact expectation")
        if "rebuild" in bank:
            item["rebuild"] = _boolean(bank.get("rebuild"), "rebuild")
        if "events" in bank:
            item["events"] = [
                {
                    "kind": "id",
                    "value": _require_key(object_ids, f"event:{_segment(name, 'event')}")
                }
                for name in _string_rows(bank.get("events"), "soundbank.events")
            ]
        if "inclusions" in bank:
            values = _string_rows(bank.get("inclusions"), "soundbank.inclusions")
            if any(value not in {"event", "structure", "media"} for value in values):
                raise SoundBankRuntimeError("generate inclusions escaped the reviewed set")
            item["inclusions"] = values
        soundbanks.append(item)
    arguments: dict[str, Any] = {
        "soundbanks": soundbanks,
        "platforms": _string_rows(raw.get("platforms"), "platforms"),
        "skip_languages": _boolean(raw.get("skipLanguages"), "skipLanguages"),
        "write_to_disk": _boolean(raw.get("writeToDisk"), "writeToDisk"),
        "io_root": str(io_root),
    }
    if arguments["write_to_disk"] is not True:
        raise SoundBankRuntimeError("SoundBank eval requires writeToDisk=true")
    if "languages" in raw:
        arguments["languages"] = [
            _canonical_language(value)
            for value in _string_rows(raw.get("languages"), "languages")
        ]
    for camel, snake in (
        ("rebuildSoundBanks", "rebuild_soundbanks"),
        ("clearAudioFileCache", "clear_audio_file_cache"),
        ("rebuildInitBank", "rebuild_init_bank"),
    ):
        if camel in raw:
            arguments[snake] = _boolean(raw.get(camel), camel)
    return arguments


def _materialize_definition_documents(
    blueprint: SoundBankBlueprint,
    *,
    object_ids: Mapping[str, str],
    short_ids: Mapping[str, int],
) -> tuple[FileProof, ...]:
    proofs: list[FileProof] = []
    for document in blueprint.definitions:
        if document.path.exists():
            raise SoundBankRuntimeError("Definition document existed before finalization")
        lines: list[str] = []
        expected_rows: list[dict[str, Any]] = []
        for row in document.rows:
            if row.resolution == "unknown":
                identity_value = row.object_name
            elif row.identity_format == "name":
                identity_value = row.object_name
            elif row.identity_format == "guid":
                identity_value = _require_key(object_ids, row.object_key)
            elif row.identity_format == "decimal_short_id":
                identity_value = str(_require_int_key(short_ids, row.object_key))
            elif row.identity_format == "hexadecimal_short_id":
                identity_value = f"0x{_require_int_key(short_ids, row.object_key):08X}"
            else:
                raise SoundBankRuntimeError(
                    f"unsupported Definition identity format: {row.identity_format}"
                )
            raw_cells = [row.soundbank]
            if row.directive.startswith("-"):
                raw_cells.extend((row.directive, identity_value))
            else:
                raw_cells.append(identity_value)
            raw_cells.extend(row.filters)
            if any(
                not cell
                or cell != cell.strip()
                or any(char in cell for char in ('\t', '\r', '\n', '"', '\x00'))
                for cell in raw_cells
            ):
                raise SoundBankRuntimeError("Definition TSV contains an unsafe cell")
            identity = (
                f'"{identity_value}"'
                if row.identity_format == "name"
                else identity_value
            )
            cells = [row.soundbank]
            if row.directive.startswith("-"):
                cells.extend((row.directive, identity))
            else:
                cells.append(identity)
            cells.extend(row.filters)
            lines.append("\t".join(cells))
            if row.identity_format == "name":
                parsed_identity: dict[str, Any] = {
                    "kind": "name",
                    "value": identity_value,
                }
            elif row.identity_format == "guid":
                parsed_identity = {"kind": "guid", "value": identity_value}
            else:
                parsed_identity = {
                    "kind": "short_id",
                    "value": int(identity_value, 0),
                    "source_format": (
                        "decimal"
                        if row.identity_format == "decimal_short_id"
                        else "hexadecimal"
                    ),
                }
            expected_rows.append(
                {
                    "soundbank": row.soundbank,
                    "definition_keyword": row.directive,
                    "object_type": row.object_type,
                    "identity": parsed_identity,
                    "filters": list(_waapi_filters(row.filters)),
                }
            )
        data = ("\n".join(lines) + "\n").encode("utf-8")
        if data.startswith(b"\xef\xbb\xbf") or b"\r" in data:
            raise SoundBankRuntimeError("Definition TSV serialization drifted")
        with document.path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            parsed = parse_soundbank_definition_file(document.path)
        except Exception as exc:
            raise SoundBankRuntimeError(
                f"materialized Definition failed parser validation: {document.name}"
            ) from exc
        actual_rows = parsed.get("rows")
        if not isinstance(actual_rows, list) or len(actual_rows) != len(expected_rows):
            raise SoundBankRuntimeError(
                f"materialized Definition row count drifted: {document.name}"
            )
        for expected, actual in zip(expected_rows, actual_rows, strict=True):
            if any(actual.get(key) != value for key, value in expected.items()):
                raise SoundBankRuntimeError(
                    f"materialized Definition identity or filters drifted: {document.name}"
                )
        proofs.append(_file_proof(document.path, blueprint.io_root))
    return tuple(proofs)


def _bind_topic_event(
    raw: Mapping[str, Any],
    *,
    object_ids: Mapping[str, str],
    platform_ids: Mapping[str, str],
    language_ids: Mapping[str, str],
) -> TopicExpectedEvent:
    bank = _segment(raw.get("soundbank"), "topic.soundbank")
    platform = _text(raw.get("platform"), "topic.platform")
    language = raw.get("language")
    canonical_language = None if language is None else _canonical_language(_text(language, "topic.language"))
    return TopicExpectedEvent(
        bank,
        platform,
        canonical_language,
        _require_key(object_ids, f"bank:{bank}"),
        _project_identity(platform_ids, platform, "platform"),
        _project_identity(language_ids, canonical_language, "language")
        if canonical_language is not None
        else None,
    )


def _common_topic_match(
    rows: Sequence[TopicExpectedEvent],
) -> dict[str, Any] | None:
    if not rows:
        raise SoundBankRuntimeError("topic plan requires expected events")
    result: dict[str, Any] = {}
    bank_names = {row.soundbank_name for row in rows}
    platform_names = {row.platform_name for row in rows}
    if len(bank_names) == 1:
        result["soundbank"] = {"name": next(iter(bank_names))}
    if len(platform_names) == 1:
        result["platform"] = {"name": next(iter(platform_names))}
    return result or None


def _generation_artifacts(
    blueprint: SoundBankBlueprint,
    project_info: Mapping[str, Any],
    raw_requests: Sequence[Mapping[str, Any]],
    media_ids: Mapping[str, int],
) -> tuple[ExpectedArtifact, ...]:
    artifacts: list[ExpectedArtifact] = []
    platform_rows = _mapping_rows(project_info.get("platforms"), "project.platforms")
    media_by_bank: dict[str, list[MediaFixture]] = {}
    for media in blueprint.media_fixtures:
        for bank in media.soundbank_names:
            media_by_bank.setdefault(bank, []).append(media)

    for raw_request in raw_requests:
        platforms = [
            _project_row(name, platform_rows, aliases=("name", "baseName"))
            for name in _string_rows(raw_request.get("platforms"), "platforms")
        ]
        skip_languages = _boolean(raw_request.get("skipLanguages"), "skipLanguages")
        languages = (
            []
            if skip_languages
            else [
                _canonical_language(name)
                for name in _string_rows(raw_request.get("languages"), "languages")
            ]
        )
        for raw_bank in _mapping_rows(raw_request.get("soundbanks"), "soundbanks"):
            bank_name = _segment(raw_bank.get("name"), "soundbank.name")
            expectation = _text(raw_bank.get("artifact_expectation"), "artifact_expectation")
            for platform in platforms:
                platform_name = _text(platform.get("name"), "platform.name")
                bank_root = Path(
                    _text(platform.get("soundBankPath"), "platform.soundBankPath")
                ).expanduser().resolve(strict=False)
                copied_root = Path(
                    _text(platform.get("copiedMediaPath"), "platform.copiedMediaPath")
                ).expanduser().resolve(strict=False)
                _require_under(bank_root, blueprint.io_root, "soundBankPath")
                _require_under(copied_root, blueprint.io_root, "copiedMediaPath")
                bank_languages = languages if expectation in {"localized", "mixed"} else [None]
                for language in bank_languages:
                    path = bank_root
                    if language is not None:
                        path = path / language
                    artifacts.append(
                        ExpectedArtifact(
                            "bank",
                            path / f"{bank_name}.bnk",
                            bank_name,
                            platform_name,
                            language,
                            True,
                        )
                    )
                for media in media_by_bank.get(bank_name, []):
                    if media.language != "SFX" and languages and media.language not in languages:
                        continue
                    media_id = media_ids.get(media.key)
                    if media_id is None:
                        raise SoundBankRuntimeError(
                            f"media fixture lacks a live Media ID: {media.key}"
                        )
                    media_path = copied_root
                    language = None if media.language == "SFX" else media.language
                    if language is not None:
                        media_path = media_path / language
                    artifacts.append(
                        ExpectedArtifact(
                            "media",
                            media_path / f"{media_id}.wem",
                            bank_name,
                            platform_name,
                            language,
                            True,
                        )
                    )

    requested_names = {
        _text(bank.get("name"), "soundbank.name")
        for request in raw_requests
        for bank in _mapping_rows(request.get("soundbanks"), "soundbanks")
    }
    requested_platforms = {
        _text(name, "platform")
        for request in raw_requests
        for name in _string_rows(request.get("platforms"), "platforms")
    }
    for control in (bank for bank in blueprint.soundbanks if bank.control):
        for platform_name in requested_platforms:
            platform = _project_row(platform_name, platform_rows, aliases=("name", "baseName"))
            root = Path(_text(platform.get("soundBankPath"), "soundBankPath")).resolve(
                strict=False
            )
            artifacts.append(
                ExpectedArtifact(
                    "control",
                    root / f"{control.name}.bnk",
                    control.name,
                    _text(platform.get("name"), "platform.name"),
                    None,
                    False,
                )
            )
    if "Init" not in requested_names:
        for platform_name in requested_platforms:
            platform = _project_row(platform_name, platform_rows, aliases=("name", "baseName"))
            root = Path(_text(platform.get("soundBankPath"), "soundBankPath")).resolve(
                strict=False
            )
            artifacts.append(
                ExpectedArtifact(
                    "init",
                    root / "Init.bnk",
                    "Init",
                    _text(platform.get("name"), "platform.name"),
                    None,
                    False,
                )
            )
    return _dedupe_artifacts(artifacts)


def _materialize_preexisting_artifacts(
    blueprint: SoundBankBlueprint,
    project_info: Mapping[str, Any],
    artifacts: Sequence[ExpectedArtifact],
) -> None:
    manifest = _mapping(blueprint.asset_spec.get("fixture_manifest"), "fixture_manifest")
    rows = _mapping_rows(manifest.get("preexisting_artifacts"), "preexisting_artifacts")
    for index, row in enumerate(rows):
        bank = _text(row.get("soundbank"), "preexisting.soundbank")
        platform = _text(row.get("platform"), "preexisting.platform")
        language = row.get("language")
        if language is not None:
            language = _canonical_language(_text(language, "preexisting.language"))
        matches = [
            artifact
            for artifact in artifacts
            if artifact.kind == "bank"
            and artifact.soundbank == bank
            and artifact.platform in {platform, _project_name(platform, project_info.get("platforms"), aliases=("name", "baseName"))}
            and artifact.language == language
        ]
        if len(matches) != 1:
            raise SoundBankRuntimeError(
                f"preexisting artifact did not bind uniquely: {row}"
            )
        path = matches[0].path
        _require_under(path, blueprint.io_root, "preexisting artifact")
        path.parent.mkdir(parents=True, exist_ok=True)
        data = (
            b"BKHD-V3-STALE\x00"
            + hashlib.sha256(f"{blueprint.scenario_id}:{index}".encode()).digest()
        )
        path.write_bytes(data)
        if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
            raise SoundBankRuntimeError("preexisting artifact materialization failed")


def _generate_topic_init(
    blueprint: SoundBankBlueprint,
    backend: SoundBankRuntimeBackend,
    project_info: Mapping[str, Any],
) -> None:
    publishers = _mapping_rows(
        blueprint.asset_spec.get("publisher_requests"), "publisher_requests"
    )
    platform_names = _unique(
        name
        for publisher in publishers
        for name in _string_rows(publisher.get("platforms"), "platforms")
    )
    canonical = [
        _project_name(name, project_info.get("platforms"), aliases=("name", "baseName"))
        for name in platform_names
    ]
    control_names = [
        bank.name for bank in blueprint.soundbanks if bank.control
    ]
    if not control_names:
        raise SoundBankRuntimeError(
            "topic Init pre-generation requires an explicit control SoundBank"
        )
    target_names = {
        bank.name.casefold() for bank in blueprint.soundbanks if not bank.control
    }
    if any(name.casefold() in target_names for name in control_names):
        raise SoundBankRuntimeError(
            "topic Init pre-generation control scope overlaps a publisher target"
        )
    backend.generate_for_setup(
        {
            # An empty SoundBank array means all user SoundBanks to real Wwise
            # 2022.1.  That used to generate the publisher targets before the
            # subscription existed and made the later topic wait nondeterministic.
            # Generate only the declared controls while rebuilding Init so every
            # target Bank remains absent (apart from an explicit stale-artifact
            # fixture) until the ACK-bound publisher runs.
            "soundbanks": [
                {"name": name, "rebuild": True} for name in control_names
            ],
            "platforms": canonical,
            "skipLanguages": True,
            "writeToDisk": True,
            "rebuildSoundBanks": False,
            "clearAudioFileCache": False,
            "rebuildInitBank": True,
        }
    )
    platform_rows = _mapping_rows(project_info.get("platforms"), "project.platforms")
    missing: list[str] = []
    for name in canonical:
        row = _project_row(name, platform_rows, aliases=("name", "baseName"))
        root = Path(_text(row.get("soundBankPath"), "soundBankPath"))
        for filename, field in (
            ("Init.bnk", "Init artifact"),
            *((f"{control}.bnk", "control SoundBank artifact") for control in control_names),
        ):
            path = root / filename
            _require_under(path, blueprint.io_root, field)
            if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
                missing.append(str(path))
    if missing:
        raise SoundBankRuntimeError(
            "runner-owned control/Init pre-generation lacks non-empty "
            f"artifact(s): {missing}"
        )


def build_soundbank_generation_prompt_projection(
    project_info: Mapping[str, Any],
    arguments: Mapping[str, Any],
    *,
    io_root: Path,
) -> Mapping[str, Any]:
    """Keep only the validated live fields needed to render build locations.

    The projection deliberately excludes GUIDs, short IDs, and every oracle-only
    field.  It is suitable for sealing as pre-Codex provenance and can be fed
    back into :func:`render_soundbank_generation_build_locations` without a
    second live WAAPI call.
    """

    rows = _mapping_rows(project_info.get("platforms"), "project.platforms")
    project_path = _text(project_info.get("path"), "project.path")
    cache_path = _text(
        _mapping(project_info.get("directories"), "directories").get("cache"),
        "directories.cache",
    )
    _require_under(Path(project_path).resolve(strict=False), io_root, "project.path")
    _require_under(Path(cache_path).resolve(strict=False), io_root, "directories.cache")
    result: dict[str, Any] = {
        "path": project_path,
        "directories": {"cache": cache_path},
        "platforms": [],
    }
    for name in _string_rows(arguments.get("platforms"), "arguments.platforms"):
        row = _project_row(name, rows, aliases=("name", "baseName"))
        soundbank_path = _text(row.get("soundBankPath"), "soundBankPath")
        copied_media_path = _text(row.get("copiedMediaPath"), "copiedMediaPath")
        _require_under(
            Path(soundbank_path).resolve(strict=False),
            io_root,
            "platform.soundBankPath",
        )
        _require_under(
            Path(copied_media_path).resolve(strict=False),
            io_root,
            "platform.copiedMediaPath",
        )
        result["platforms"].append(
            {
                "name": _text(row.get("name"), "platform.name"),
                "soundBankPath": soundbank_path,
                "copiedMediaPath": copied_media_path,
            }
        )
    return _json_clone(result)


def render_soundbank_generation_build_locations(
    projection: Mapping[str, Any],
    *,
    io_root: Path,
) -> Mapping[str, Any]:
    """Render the model-visible aliases from one closed live projection."""

    if set(projection) != {"path", "directories", "platforms"}:
        raise SoundBankRuntimeError("SoundBank prompt projection fields drifted")
    directories = _mapping(projection.get("directories"), "directories")
    if set(directories) != {"cache"}:
        raise SoundBankRuntimeError("SoundBank prompt directory projection drifted")
    result: dict[str, Any] = {
        "project": _natural_display_path(
            _text(projection.get("path"), "project.path"), io_root
        ),
        "cache": _natural_display_path(
            _text(directories.get("cache"), "directories.cache"), io_root
        ),
        "platforms": [],
    }
    for index, raw in enumerate(
        _mapping_rows(projection.get("platforms"), "project.platforms")
    ):
        if set(raw) != {"name", "soundBankPath", "copiedMediaPath"}:
            raise SoundBankRuntimeError(
                f"SoundBank prompt platform projection {index} drifted"
            )
        result["platforms"].append(
            {
                "name": _text(raw.get("name"), "platform.name"),
                "soundBankPath": _natural_display_path(
                    _text(raw.get("soundBankPath"), "soundBankPath"), io_root
                ),
                "copiedMediaPath": _natural_display_path(
                    _text(raw.get("copiedMediaPath"), "copiedMediaPath"), io_root
                ),
            }
        )
    return result


def _build_locations(
    project_info: Mapping[str, Any],
    arguments: Mapping[str, Any],
    *,
    io_root: Path,
) -> Mapping[str, Any]:
    """Compatibility wrapper retained for focused runtime tests."""

    return render_soundbank_generation_build_locations(
        build_soundbank_generation_prompt_projection(
            project_info,
            arguments,
            io_root=io_root,
        ),
        io_root=io_root,
    )


def _generation_cache_root(
    blueprint: SoundBankBlueprint,
    project_info: Mapping[str, Any],
) -> Path:
    cache_root = Path(
        _text(
            _mapping(project_info.get("directories"), "directories").get("cache"),
            "directories.cache",
        )
    ).resolve(strict=False)
    _require_under(cache_root, blueprint.io_root, "dynamic cache root")
    return cache_root


def _collect_input_proofs(blueprint: SoundBankBlueprint) -> tuple[FileProof, ...]:
    paths = [fixture.wav_path for fixture in blueprint.media_fixtures]
    paths.extend(document.path for document in blueprint.definitions)
    for document in blueprint.external_documents:
        paths.append(document.path)
        paths.extend(row.source_path for row in document.rows)
    unique_paths = sorted(set(paths), key=lambda path: str(path))
    return tuple(_file_proof(path, blueprint.io_root) for path in unique_paths)


def _assert_materialized_case(case: MaterializedSoundBankCase) -> None:
    blueprint = case.blueprint
    if blueprint.api == SOUNDBANK_TOPIC:
        if case.operation_requests or case.topic_plan is None:
            raise SoundBankRuntimeError("topic case has an invalid execution shape")
    else:
        if len(case.operation_requests) != 1 or case.topic_plan is not None:
            raise SoundBankRuntimeError("function case has an invalid execution shape")
    for request in case.operation_requests:
        if set(request) != {"contract", "version", "operation", "arguments"}:
            raise SoundBankRuntimeError("operation request is not closed")
        if request["contract"] != OPERATION_REQUEST_CONTRACT:
            raise SoundBankRuntimeError("operation request contract drifted")
        if request["version"] != blueprint.version:
            raise SoundBankRuntimeError("operation request version drifted")
    for proof in case.input_files:
        actual = _file_proof(Path(proof.path), blueprint.io_root)
        if actual != proof:
            raise SoundBankRuntimeError("input proof changed during materialization")
    case.render_prompt()


def _validate_before_state(
    case: MaterializedSoundBankCase,
    before: SoundBankSnapshot,
) -> None:
    failures: list[str] = []
    for fixture in case.blueprint.object_fixtures:
        state = next(row for row in before.objects if row.key == fixture.key)
        if state.id is None:
            failures.append(f"fixture object absent before prompt: {fixture.path}")
        elif state.object_type != fixture.object_type:
            failures.append(f"fixture object type mismatch before prompt: {fixture.path}")
    for bank in case.blueprint.soundbanks:
        state = next(row for row in before.banks if row.name == bank.name)
        if bank.project_object_mode == "temporary_request_only":
            if state.id is not None:
                failures.append(f"temporary request-only Bank already exists: {bank.name}")
            continue
        if state.id is None:
            failures.append(f"fixture SoundBank absent before prompt: {bank.name}")
            continue
        expected = tuple(
            sorted(
                (
                    _require_key(case.object_ids, row.object_key).casefold(),
                    tuple(sorted(row.filters)),
                )
                for row in bank.inclusions
            )
        )
        if state.inclusions != expected:
            failures.append(f"fixture SoundBank pre-state mismatch: {bank.name}")
    if case.blueprint.scenario_id == PROCESS_REFUSAL_ID:
        absent = {
            row.key: row for row in before.objects if row.key.startswith("refusal_absent:")
        }
        for key, object_type, name in PROCESS_REFUSAL_ABSENT_IDENTITIES:
            state = absent.get(key)
            if state is None:
                failures.append(
                    f"refusal absence proof is missing: {object_type} {name!r}"
                )
            elif state.id is not None:
                failures.append(
                    f"refusal identity exists before preview: {object_type} {name!r}"
                )
    if case.blueprint.api == SOUNDBANK_TOPIC:
        before_outputs = {row.relative_path: row for row in before.output_files}
        manifest = _mapping(
            case.blueprint.asset_spec.get("fixture_manifest"),
            "fixture_manifest",
        )
        explicit_preexisting = {
            (
                _text(row.get("soundbank"), "preexisting.soundbank").casefold(),
                _text(row.get("platform"), "preexisting.platform").casefold(),
                (
                    _text(row.get("language"), "preexisting.language").casefold()
                    if row.get("language") is not None
                    else None
                ),
            )
            for row in _mapping_rows(
                manifest.get("preexisting_artifacts"),
                "preexisting_artifacts",
            )
        }
        for artifact in case.expected_artifacts:
            relative = artifact.path.resolve(strict=False).relative_to(
                case.blueprint.io_root
            ).as_posix()
            old = before_outputs.get(relative)
            if artifact.kind in {"init", "control"}:
                if old is None or old.size <= 0:
                    failures.append(
                        f"topic fixture lacks a sealed non-empty {artifact.kind} "
                        f"artifact: {relative}"
                    )
                continue
            allowed_preexisting = artifact.kind == "bank" and (
                (artifact.soundbank or "").casefold(),
                (artifact.platform or "").casefold(),
                artifact.language.casefold() if artifact.language is not None else None,
            ) in explicit_preexisting
            if allowed_preexisting:
                if old is None or old.size <= 0:
                    failures.append(
                        "topic fixture lacks its declared stale target artifact: "
                        f"{relative}"
                    )
            elif old is not None:
                failures.append(
                    "topic publisher target existed before subscription: "
                    f"{relative}"
                )
    if failures:
        raise SoundBankRuntimeError(
            f"{case.scenario_id} before-state proof failed: " + "; ".join(failures)
        )


def _validate_after_state(
    case: MaterializedSoundBankCase,
    before: SoundBankSnapshot,
    after: SoundBankSnapshot,
) -> list[str]:
    failures: list[str] = []
    if before.input_files != after.input_files:
        failures.append("SoundBank input WAV/document proof changed")
    before_outputs = {row.relative_path: row for row in before.output_files}
    after_outputs = {row.relative_path: row for row in after.output_files}
    for artifact in case.expected_artifacts:
        relative = artifact.path.resolve(strict=False).relative_to(
            case.blueprint.io_root
        ).as_posix()
        old = before_outputs.get(relative)
        new = after_outputs.get(relative)
        if artifact.kind == "control" or (
            artifact.kind == "init" and case.blueprint.api == SOUNDBANK_TOPIC
        ):
            if old != new:
                failures.append(
                    f"{artifact.kind} artifact changed outside requested scope: {relative}"
                )
            continue
        if artifact.kind == "init":
            # Function generation may create/update Init as Wwise's automatic
            # byproduct even with rebuildInitBank=false.  It is permitted but
            # never required and, when present, must still be a real non-empty
            # artifact.  Topic publishers instead use the sealed branch above.
            if new is not None and new.size <= 0:
                failures.append(f"automatic Init artifact is empty: {relative}")
            continue
        if new is None or new.size <= 0:
            failures.append(f"expected non-empty {artifact.kind} artifact is absent: {relative}")
        elif artifact.required_change and old == new:
            failures.append(f"expected {artifact.kind} artifact did not change: {relative}")

    before_banks = {row.name: row for row in before.banks}
    after_banks = {row.name: row for row in after.banks}
    for bank in case.blueprint.soundbanks:
        old = before_banks[bank.name]
        new = after_banks[bank.name]
        if bank.control and old != new:
            failures.append(f"control SoundBank state changed: {bank.name}")

    if case.blueprint.api == "ak.wwise.core.soundbank.setInclusions":
        if before.objects != after.objects:
            failures.append("setInclusions changed the fixture object tree")
        spec = case.blueprint.asset_spec
        name = _text(spec.get("soundbank"), "soundbank")
        old = before_banks[name]
        new = after_banks[name]
        if old.id != new.id:
            failures.append("setInclusions changed the target SoundBank GUID")
        expected = tuple(
            sorted(
                (
                    _require_key(
                        case.object_ids,
                        _fixture_for_inclusion_name(
                            case.blueprint, _text(row.get("object"), "object")
                        ).key,
                    ).casefold(),
                    tuple(sorted(_filters(row.get("filters")))),
                )
                for row in _mapping_rows(spec.get("expected_after"), "expected_after")
            )
        )
        if new.inclusions != expected:
            failures.append("setInclusions target state does not equal expected_after")
    elif case.blueprint.api == "ak.wwise.core.soundbank.processDefinitionFiles":
        if before.objects != after.objects:
            failures.append("Definition processing changed the fixture object tree")
        expected_by_bank: dict[str, dict[str, tuple[str, ...]]] = {}
        for document in case.blueprint.definitions:
            for row in document.rows:
                if row.resolution != "unique":
                    continue
                expected_by_bank.setdefault(
                    row.soundbank,
                    {
                        object_id: filters
                        for object_id, filters in before_banks[row.soundbank].inclusions
                    },
                )[_require_key(case.object_ids, row.object_key).casefold()] = tuple(
                    sorted(_waapi_filters(row.filters))
                )
        for name, rows_by_object in expected_by_bank.items():
            old = before_banks[name]
            new = after_banks[name]
            if old.id != new.id:
                failures.append(f"Definition processing changed target GUID: {name}")
            if new.inclusions != tuple(sorted(rows_by_object.items())):
                failures.append(f"Definition target inclusions mismatch: {name}")
    elif case.blueprint.api in {
        "ak.wwise.core.soundbank.generate",
        SOUNDBANK_TOPIC,
        "ak.wwise.core.soundbank.convertExternalSources",
    }:
        if before.project_files != after.project_files:
            failures.append("artifact operation changed saved project/Work Unit files")
        if before.objects != after.objects:
            failures.append("artifact operation changed the project object fixture")
        if before.banks != after.banks:
            failures.append("artifact operation changed SoundBank inclusion state")

        # The hidden tree includes every .bnk/.wem under the case authority,
        # not merely paths named in the prompt.  Only reviewed target artifacts
        # may be created or changed; Init, controls, and N+1 byproducts fail.
        allowed_changed = {
            artifact.path.resolve(strict=False)
            .relative_to(case.blueprint.io_root)
            .as_posix()
            for artifact in case.expected_artifacts
            if artifact.required_change
            and artifact.path.suffix.casefold() in {".bnk", ".wem"}
        }
        managed_external_indexes = {
            (artifact.path.resolve(strict=False).parent / "Wwise.dat")
            .relative_to(case.blueprint.io_root)
            .as_posix()
            for artifact in case.expected_artifacts
            if case.blueprint.api
            == "ak.wwise.core.soundbank.convertExternalSources"
            and artifact.kind == "external"
        }
        allowed_changed.update(managed_external_indexes)
        if case.blueprint.api == "ak.wwise.core.soundbank.generate":
            allowed_changed.update(
                artifact.path.resolve(strict=False)
                .relative_to(case.blueprint.io_root)
                .as_posix()
                for artifact in case.expected_artifacts
                if artifact.kind == "init"
            )
        for relative in sorted(set(before_outputs) | set(after_outputs)):
            relative_path = Path(relative)
            if (
                relative_path.suffix.casefold() not in {".bnk", ".wem"}
                and relative_path.name != "Wwise.dat"
            ):
                continue
            if before_outputs.get(relative) != after_outputs.get(relative):
                absolute = case.blueprint.io_root / PurePosixPath(relative)
                dynamically_allowed = any(
                    absolute.resolve(strict=False) == root
                    or root in absolute.resolve(strict=False).parents
                    for root in case.allowed_dynamic_artifact_roots
                )
                if dynamically_allowed:
                    if (
                        relative_path.suffix.casefold() != ".wem"
                        and relative_path.name != "Wwise.dat"
                    ):
                        failures.append(
                            f"dynamic cache artifact type is not allowed: {relative}"
                        )
                    elif after_outputs.get(relative) is None:
                        failures.append(
                            f"dynamic cache artifact was removed: {relative}"
                        )
                    elif before_outputs.get(relative) is not None:
                        failures.append(
                            f"preexisting dynamic cache artifact changed: {relative}"
                        )
                    elif after_outputs[relative].size <= 0:
                        failures.append(f"dynamic cache artifact is empty: {relative}")
                elif relative not in allowed_changed:
                    failures.append(
                        f"unreviewed SoundBank artifact changed: {relative}"
                    )

    if case.blueprint.api == "ak.wwise.core.soundbank.convertExternalSources":
        allowed = {
            artifact.path.resolve(strict=False).relative_to(case.blueprint.io_root).as_posix()
            for artifact in case.expected_artifacts
            if artifact.kind == "external"
        }
        managed_external_indexes = {
            (artifact.path.resolve(strict=False).parent / "Wwise.dat")
            .relative_to(case.blueprint.io_root)
            .as_posix()
            for artifact in case.expected_artifacts
            if artifact.kind == "external"
        }
        for relative in managed_external_indexes:
            current = after_outputs.get(relative)
            if current is None:
                failures.append(f"managed External Sources index is absent: {relative}")
            elif current.size <= 0:
                failures.append(f"managed External Sources index is empty: {relative}")
            elif before_outputs.get(relative) is not None:
                failures.append(
                    f"managed External Sources index was not newly created: {relative}"
                )
        for relative in set(after_outputs) - set(before_outputs):
            if relative not in allowed and relative not in managed_external_indexes:
                failures.append(f"unreviewed External Sources output: {relative}")
    return failures


def _snapshot_drift(
    before: SoundBankSnapshot,
    after: SoundBankSnapshot,
) -> list[str]:
    failures: list[str] = []
    for field in ("objects", "banks", "project_files", "input_files", "output_files"):
        if getattr(before, field) != getattr(after, field):
            failures.append(f"preview changed hidden {field}")
    return failures


def _validate_project_info(
    value: Mapping[str, Any],
    *,
    blueprint: SoundBankBlueprint,
) -> Mapping[str, Any]:
    info = _mapping(value, "project_info")
    project_candidate = _localize_wwise_host_path(
        _text(info.get("path"), "project_info.path"),
        "project_info.path",
    )
    if project_candidate.is_symlink():
        raise SoundBankRuntimeError("getProjectInfo project path is a symlink")
    project_path = project_candidate.resolve(strict=True)
    if project_path != blueprint.sandbox_project:
        raise SoundBankRuntimeError(
            "getProjectInfo does not identify the scenario-owned project"
        )
    if info.get("isDirty") is not False:
        raise SoundBankRuntimeError("SoundBank fixture project must be saved and clean")
    directories = _mapping(info.get("directories"), "project_info.directories")
    normalized_directories = dict(directories)
    for field in ("root", "cache", "soundBankOutputRoot"):
        path = _localize_wwise_host_path(
            _text(directories.get(field), f"directories.{field}"),
            f"directories.{field}",
        ).resolve(
            strict=False
        )
        _require_under(path, blueprint.io_root, f"directories.{field}")
        normalized_directories[field] = str(path)
    platforms = _mapping_rows(info.get("platforms"), "project_info.platforms")
    if not platforms:
        raise SoundBankRuntimeError("project_info has no platforms")
    normalized_platforms: list[dict[str, Any]] = []
    for row in platforms:
        _guid(row.get("id"), "platform.id")
        _text(row.get("name"), "platform.name")
        normalized_row = dict(row)
        for field in ("soundBankPath", "copiedMediaPath"):
            path = _localize_wwise_host_path(
                _text(row.get(field), f"platform.{field}"),
                f"platform.{field}",
            ).resolve(strict=False)
            _require_under(path, blueprint.io_root, f"platform.{field}")
            path.mkdir(parents=True, exist_ok=True)
            normalized_row[field] = str(path)
        normalized_platforms.append(normalized_row)
    languages = _mapping_rows(info.get("languages"), "project_info.languages")
    if not languages:
        raise SoundBankRuntimeError("project_info has no languages")
    for row in languages:
        _guid(row.get("id"), "language.id")
        _text(row.get("name"), "language.name")
    normalized = dict(info)
    normalized["path"] = str(project_path)
    normalized["directories"] = normalized_directories
    normalized["platforms"] = normalized_platforms
    return normalized


def _localize_wwise_host_path(value: str, field: str) -> Path:
    """Map Wwise/Wine virtual-drive paths before touching the host filesystem.

    Wine Wwise commonly reports host paths as ``Y:\\...`` (the account home)
    or ``Z:\\...`` (the POSIX root).  On a POSIX runner, ``pathlib.Path``
    treats that complete Windows spelling as one filename; a later stat can
    therefore raise ``ENAMETOOLONG`` instead of proving project ownership.
    """

    normalized = value.replace("\\", "/")
    drive_match = re.fullmatch(r"([A-Za-z]):/(.*)", normalized)
    if os.name != "nt" and drive_match is not None:
        drive = drive_match.group(1).upper()
        suffix = drive_match.group(2)
        if drive == "Z":
            path = Path("/") / suffix
        elif drive == "Y":
            if pwd is None:  # pragma: no cover - native Windows skips this branch
                raise SoundBankRuntimeError(
                    f"{field} uses a Wine Y: drive but the host account home is unavailable"
                )
            try:
                path = Path(pwd.getpwuid(os.getuid()).pw_dir) / suffix
            except (KeyError, OSError) as exc:
                raise SoundBankRuntimeError(
                    f"{field} Wine Y: drive could not be mapped to the host account home"
                ) from exc
        else:
            raise SoundBankRuntimeError(
                f"{field} uses unmappable Wine drive {drive}:"
            )
    else:
        path = Path(normalized).expanduser()
    if not path.is_absolute():
        raise SoundBankRuntimeError(f"{field} must be an absolute host path")
    return path


def _read_media_source_state(
    backend: SoundBankRuntimeBackend,
    fixture: MediaFixture,
    *,
    sandbox_root: Path,
) -> MediaSourceState:
    """Resolve one language-scoped Sound to its exact active copied source."""

    requested_language = _canonical_language(fixture.language)
    sounds = backend.read_objects(
        path=fixture.sound_path,
        fields=MEDIA_OBJECT_FIELDS,
        language=requested_language,
    )
    if len(sounds) != 1:
        raise SoundBankRuntimeError(
            f"localized Sound did not resolve exactly for {requested_language}: "
            f"{fixture.sound_path}"
        )
    sound = sounds[0]
    sound_id, _ = _row_identity(
        sound,
        f"localized Sound {fixture.key} ({requested_language})",
    )
    active_source = _payload_identity(sound.get("activeSource"))
    if active_source is None:
        raise SoundBankRuntimeError(
            f"localized Sound lacks activeSource for {requested_language}: "
            f"{fixture.sound_path}"
        )
    active_source_id = _guid(
        active_source,
        f"localized Sound {fixture.key} activeSource",
    )
    sources = backend.read_objects(
        object_id=active_source_id,
        fields=MEDIA_SOURCE_FIELDS,
        language=requested_language,
    )
    if len(sources) != 1:
        raise SoundBankRuntimeError(
            f"localized activeSource did not resolve exactly for {requested_language}: "
            f"{fixture.key}"
        )
    source = sources[0]
    if str(source.get("type", "")) not in {"AudioFileSource", "Audio Source"}:
        raise SoundBankRuntimeError(
            f"localized activeSource has the wrong type: {fixture.key}"
        )
    source_id, media_id = _row_media_identity(
        source,
        f"localized activeSource {fixture.key}",
    )
    if not _same_identity(source_id, active_source_id):
        raise SoundBankRuntimeError(
            f"localized activeSource identity drifted: {fixture.key}"
        )
    parent_id = _payload_identity(source.get("parent"))
    if parent_id is None or not _same_identity(parent_id, sound_id):
        raise SoundBankRuntimeError(
            f"localized activeSource parent differs from its logical Sound: "
            f"{fixture.key}"
        )
    raw_language = source.get("audioSource:language")
    if raw_language is None:
        raw_language = sound.get("audioSource:language")
    actual_language = _language_name(raw_language, f"media source {fixture.key}.language")
    copied_path = source.get("originalFilePath")
    if copied_path is None:
        copied_path = sound.get("sound:originalWavFilePath")
    copied_file = _copied_original_file_proof(
        copied_path,
        sandbox_root=sandbox_root,
    )
    return MediaSourceState(
        fixture.key,
        sound_id,
        source_id,
        media_id,
        actual_language,
        copied_file,
    )


def _language_name(value: Any, field: str) -> str:
    if isinstance(value, Mapping):
        value = value.get("name")
    return _canonical_language(_text(value, field))


def _copied_original_file_proof(
    value: Any,
    *,
    sandbox_root: Path,
) -> FileProof:
    """Seal one copied WAV below the exact case-owned Originals directory.

    ``originalFilePath`` is an absolute live-Wwise accessor.  Resolve only
    native absolute paths and the two reviewed Wine mappings, reject lexical
    traversal and every symlink component, then prove that lexical and real
    paths identify the same regular file below ``<case>/Originals``.
    """

    candidate = _localize_copied_original_path(value)
    root = sandbox_root.resolve(strict=True)
    originals = root / "Originals"
    try:
        originals_metadata = os.lstat(originals)
    except OSError as exc:
        raise SoundBankRuntimeError(
            f"case-owned Originals root is unavailable: {originals}"
        ) from exc
    if stat.S_ISLNK(originals_metadata.st_mode) or not stat.S_ISDIR(
        originals_metadata.st_mode
    ):
        raise SoundBankRuntimeError(
            f"case-owned Originals root must be a non-symlink directory: {originals}"
        )
    try:
        lexical_relative = candidate.relative_to(originals)
    except ValueError as exc:
        raise SoundBankRuntimeError(
            f"copied WAV escapes the case-owned Originals root: {candidate}"
        ) from exc
    if not lexical_relative.parts:
        raise SoundBankRuntimeError("copied WAV resolves to the Originals directory")

    current = originals
    for part in lexical_relative.parts:
        current /= part
        try:
            metadata = os.lstat(current)
        except OSError as exc:
            raise SoundBankRuntimeError(
                f"copied WAV path component is unavailable: {current}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise SoundBankRuntimeError(
                f"copied WAV path contains a symlink: {current}"
            )
    if not stat.S_ISREG(metadata.st_mode):
        raise SoundBankRuntimeError(f"copied WAV is not a regular file: {current}")

    resolved_originals = originals.resolve(strict=True)
    resolved_candidate = candidate.resolve(strict=True)
    try:
        resolved_relative = resolved_candidate.relative_to(resolved_originals)
    except ValueError as exc:
        raise SoundBankRuntimeError(
            f"copied WAV resolves outside the case-owned Originals root: {candidate}"
        ) from exc
    if tuple(lexical_relative.parts) != tuple(resolved_relative.parts):
        raise SoundBankRuntimeError(
            f"copied WAV path changed during containment proof: {candidate}"
        )
    return _file_proof(resolved_candidate, root)


def _localize_copied_original_path(value: Any) -> Path:
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        raise SoundBankRuntimeError(
            "copied WAV requires a non-empty absolute path string"
        )
    normalized = value.replace("\\", "/")
    if normalized.startswith("//"):
        raise SoundBankRuntimeError("copied WAV uses an unmappable UNC path")

    if os.name == "nt":  # pragma: no cover - exercised on native Windows
        drive_match = re.fullmatch(r"([A-Za-z]):/(.*)", normalized)
        if drive_match is None:
            raise SoundBankRuntimeError(
                "copied WAV must be a native Windows drive-absolute path"
            )
        parts = drive_match.group(2).split("/")
        if any(part in {"", ".", ".."} or part.startswith("~") for part in parts):
            raise SoundBankRuntimeError(
                "copied WAV contains an unsafe host path component"
            )
        candidate = Path(value)
        if not candidate.is_absolute():
            raise SoundBankRuntimeError(
                "copied WAV must localize to an absolute host path"
            )
        return candidate

    drive_prefix = re.match(r"^[A-Za-z]:", normalized)
    drive_match = re.fullmatch(r"([A-Za-z]):/(.*)", normalized)
    if drive_prefix is not None:
        if drive_match is None:
            raise SoundBankRuntimeError(
                "copied WAV has an unsafe Wine drive spelling"
            )
        drive = drive_match.group(1).upper()
        suffix = drive_match.group(2)
        if drive == "Z":
            base = Path("/")
        elif drive == "Y":
            if pwd is None:
                raise SoundBankRuntimeError(
                    "copied WAV uses Wine Y: but the login home is unavailable"
                )
            try:
                base = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve(strict=True)
            except (KeyError, OSError) as exc:
                raise SoundBankRuntimeError(
                    "copied WAV Wine Y: could not be mapped to the login home"
                ) from exc
        else:
            raise SoundBankRuntimeError(
                f"copied WAV uses unmappable Wine drive {drive}:"
            )
    else:
        if not normalized.startswith("/"):
            raise SoundBankRuntimeError(
                "copied WAV must be an absolute host path"
            )
        base = Path("/")
        suffix = normalized[1:]
    parts = suffix.split("/")
    if any(part in {"", ".", ".."} or part.startswith("~") for part in parts):
        raise SoundBankRuntimeError(
            "copied WAV contains an unsafe host path component"
        )
    candidate = base.joinpath(*parts)
    if not candidate.is_absolute():
        raise SoundBankRuntimeError(
            "copied WAV must localize to an absolute host path"
        )
    return candidate


def _project_identity_map(value: Any, field: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in _mapping_rows(value, f"project.{field}s"):
        object_id = _guid(row.get("id"), f"{field}.id")
        for key in ("id", "name", "baseName", "shortName"):
            raw = row.get(key)
            if isinstance(raw, str) and raw:
                normalized = raw.casefold()
                if normalized in result and not _same_identity(result[normalized], object_id):
                    raise SoundBankRuntimeError(
                        f"project {field} alias is ambiguous: {raw}"
                    )
                result[normalized] = object_id
    return result


def _add_language_aliases(values: dict[str, str]) -> None:
    for alias, canonical in CANONICAL_LANGUAGE.items():
        if canonical.casefold() in values:
            values[alias.casefold()] = values[canonical.casefold()]


def _project_identity(values: Mapping[str, str], name: str | None, field: str) -> str:
    if name is None:
        raise SoundBankRuntimeError(f"{field} name is missing")
    try:
        return values[name.casefold()]
    except KeyError as exc:
        raise SoundBankRuntimeError(f"project {field} is unavailable: {name!r}") from exc


def _project_row(
    name: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    aliases: Sequence[str],
) -> Mapping[str, Any]:
    matches = [
        row
        for row in rows
        if any(
            isinstance(row.get(alias), str)
            and str(row[alias]).casefold() == name.casefold()
            for alias in aliases
        )
    ]
    if len(matches) != 1:
        raise SoundBankRuntimeError(
            f"project identity {name!r} did not resolve once; rows={len(matches)}"
        )
    return matches[0]


def _project_name(value: str, rows: Any, *, aliases: Sequence[str]) -> str:
    row = _project_row(value, _mapping_rows(rows, "project identities"), aliases=aliases)
    return _text(row.get("name"), "project identity name")


def _row_guid(row: Mapping[str, Any], label: str) -> str:
    return _guid(row.get("id"), f"{label}.id")


def _optional_row_short_id(row: Mapping[str, Any], label: str) -> int | None:
    short = row.get("shortId")
    if short is None:
        return None
    if isinstance(short, str) and short.isdecimal():
        short = int(short)
    if isinstance(short, bool) or not isinstance(short, int) or not 0 <= short <= 0xFFFFFFFF:
        raise SoundBankRuntimeError(f"{label} has no bounded uint32 shortId")
    return short


def _row_identity(row: Mapping[str, Any], label: str) -> tuple[str, int]:
    object_id = _row_guid(row, label)
    short = _optional_row_short_id(row, label)
    if short is None:
        raise SoundBankRuntimeError(f"{label} has no bounded uint32 shortId")
    return object_id, short


def _row_media_identity(row: Mapping[str, Any], label: str) -> tuple[str, int]:
    """Return an Audio Source's Authoring GUID and Sound Engine Media ID."""

    object_id = _guid(row.get("id"), f"{label}.id")
    media_id = row.get("mediaId")
    if isinstance(media_id, str) and media_id.isdecimal():
        media_id = int(media_id)
    if (
        isinstance(media_id, bool)
        or not isinstance(media_id, int)
        or not 0 <= media_id <= 0xFFFFFFFF
    ):
        raise SoundBankRuntimeError(f"{label} has no bounded uint32 mediaId")
    return object_id, media_id


def _normalize_live_inclusions(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    normalized: list[tuple[str, tuple[str, ...]]] = []
    for index, row in enumerate(rows):
        raw_object = row.get("object")
        if isinstance(raw_object, Mapping):
            raw_object = raw_object.get("id")
        object_id = _guid(raw_object, f"inclusions[{index}].object")
        raw_filters = row.get("filter")
        if raw_filters is None:
            raw_filters = row.get("filters")
        filters = _filters(raw_filters)
        normalized.append((object_id.casefold(), tuple(sorted(filters))))
    if len({row[0] for row in normalized}) != len(normalized):
        raise SoundBankRuntimeError("live SoundBank inclusions contain duplicate objects")
    return tuple(sorted(normalized))


def _tree_entries(
    root: Path,
    *,
    include: Callable[[Path], bool],
) -> tuple[TreeEntry, ...]:
    candidate = root.expanduser()
    if candidate.is_symlink():
        raise SoundBankRuntimeError(f"tree root must not be a symlink: {candidate}")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_dir():
        raise SoundBankRuntimeError(f"tree root must be a real directory: {resolved}")
    entries: list[TreeEntry] = []
    for current, directory_names, file_names in os.walk(resolved, followlinks=False):
        current_path = Path(current)
        for name in list(directory_names):
            path = current_path / name
            if path.is_symlink():
                raise SoundBankRuntimeError(f"tree contains a symlink directory: {path}")
        for name in file_names:
            path = current_path / name
            if path.is_symlink():
                raise SoundBankRuntimeError(f"tree contains a symlink file: {path}")
            if not include(path):
                continue
            stat = path.stat()
            if not path.is_file() or stat.st_size > MAX_FILE_BYTES:
                raise SoundBankRuntimeError(f"tree file is unbounded or not regular: {path}")
            entries.append(
                TreeEntry(
                    path.relative_to(resolved).as_posix(),
                    stat.st_size,
                    _sha256_file(path),
                    stat.st_mtime_ns,
                )
            )
            if len(entries) > MAX_TREE_FILES:
                raise SoundBankRuntimeError("bounded tree file limit exceeded")
    return tuple(sorted(entries, key=lambda row: row.relative_path))


def _is_output_file(path: Path, case: MaterializedSoundBankCase) -> bool:
    suffix = path.suffix.casefold()
    if suffix in {".bnk", ".wem"} or path.name == "Wwise.dat":
        return True
    expected = {artifact.path.resolve(strict=False) for artifact in case.expected_artifacts}
    return path.resolve(strict=False) in expected


def _file_proof(path: Path, relative_to: Path) -> FileProof:
    candidate = path.expanduser()
    if candidate.is_symlink():
        raise SoundBankRuntimeError(f"input must not be a symlink: {candidate}")
    absolute = candidate.resolve(strict=True)
    root = relative_to.expanduser().resolve(strict=True)
    _require_under(absolute, root, "file proof")
    if not absolute.is_file():
        raise SoundBankRuntimeError(f"input must be a regular non-symlink: {absolute}")
    stat = absolute.stat()
    if stat.st_size <= 0 or stat.st_size > MAX_FILE_BYTES:
        raise SoundBankRuntimeError(f"input has an invalid size: {absolute}")
    return FileProof(
        str(absolute),
        absolute.relative_to(root).as_posix(),
        stat.st_size,
        _sha256_file(absolute),
        stat.st_mtime_ns,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_deterministic_wav(
    path: Path,
    *,
    seed: str,
    duration_ms: int,
    frequency_hz: int,
) -> None:
    if path.exists():
        raise SoundBankRuntimeError(f"deterministic WAV path is reused: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 48_000
    frames = max(1, sample_rate * duration_ms // 1000)
    phase = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16) / 2**32
    amplitude = 8_000 + int(phase * 5_000)
    payload = bytearray()
    for index in range(frames):
        value = int(
            amplitude
            * math.sin(2.0 * math.pi * frequency_hz * (index / sample_rate + phase))
        )
        payload.extend(struct.pack("<h", max(-32768, min(32767, value))))
    with path.open("xb") as raw:
        with wave.open(raw, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(bytes(payload))


def _write_wsources(
    path: Path,
    *,
    media_root: Path,
    project_root: Path,
    rows: Sequence[ExternalSourceRow],
) -> None:
    if path.exists() or not rows:
        raise SoundBankRuntimeError("External Sources document path is reused or empty")
    root_value = os.path.relpath(media_root, project_root).replace(os.sep, "/")
    root = ET.Element(
        "ExternalSourcesList",
        {"SchemaVersion": "1", "Root": root_value},
    )
    seen: set[str] = set()
    for row in rows:
        source_relative = row.source_path.resolve(strict=True).relative_to(
            media_root.resolve(strict=True)
        ).as_posix()
        attributes = {"Path": source_relative}
        if row.conversion is not None:
            attributes["Conversion"] = row.conversion
        attributes["Destination"] = row.destination
        if row.analysis_types is not None:
            attributes["AnalysisTypes"] = str(row.analysis_types)
        key = row.destination.casefold()
        if key in seen:
            raise SoundBankRuntimeError("External Sources destinations are not unique")
        seen.add(key)
        ET.SubElement(root, "Source", attributes)
    ET.indent(root, space="  ")
    data = ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data or b"\x00" in data:
        raise SoundBankRuntimeError("unsafe External Sources XML serialization")
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _definition_object_type(directive: str) -> tuple[str, str]:
    mapping = {
        "Event": ("Event", EVENT_DWU),
        "-AuxBus": ("AuxBus", MASTER_AUDIO_BUS),
        "-DialogueEvent": ("DialogueEvent", DIALOGUE_DWU),
        # WAAPI reports and creates Effect ShareSets with object type
        # ``Effect``; ``-EffectShareset`` is the Definition-file directive.
        "-EffectShareset": ("Effect", EFFECT_DWU),
    }
    try:
        return mapping[directive]
    except KeyError as exc:
        raise SoundBankRuntimeError(
            f"unsupported Definition directive: {directive!r}"
        ) from exc


def _definition_filters(value: Any, *, directive: str) -> tuple[str, ...]:
    filters = _string_rows(value, "definition.filters")
    allowed = {
        "Event": {"Event", "Structure", "Media"},
        "-DialogueEvent": {"Event", "Structure", "Media"},
        "-AuxBus": {"Structure", "Media"},
        "-EffectShareset": {"Structure", "Media"},
    }.get(directive)
    if allowed is None or not filters or set(filters) - allowed or len(filters) != len(set(filters)):
        raise SoundBankRuntimeError("Definition filters escaped the directive contract")
    return filters


def _waapi_filters(values: Sequence[str]) -> tuple[str, ...]:
    mapping = {"Event": "events", "Structure": "structures", "Media": "media"}
    try:
        return tuple(mapping[value] for value in values)
    except KeyError as exc:
        raise SoundBankRuntimeError("Definition filter is not normalized") from exc


def _inclusion_object_type(name: str) -> tuple[str, str]:
    if name.startswith("Master_"):
        return "Bus", MASTER_DWU
    if name.endswith("_Aux") or name == "Review_Aux":
        return "AuxBus", MASTER_AUDIO_BUS
    return "Event", EVENT_DWU


def _apply_named_inclusion_mode(
    raw_before: Sequence[Mapping[str, Any]],
    raw_requested: Sequence[Mapping[str, Any]],
    mode: str,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    before = {
        _text(row.get("object"), "before.object"): _filters(row.get("filters"))
        for row in raw_before
    }
    requested = {
        _text(row.get("object"), "requested.object"): _filters(row.get("filters"))
        for row in raw_requested
    }
    if mode == "replace":
        result = requested
    elif mode == "add":
        result = {**before, **requested}
    elif mode == "remove":
        if any(before.get(key) != value for key, value in requested.items()):
            raise SoundBankRuntimeError("remove request does not match live before rows")
        result = {key: value for key, value in before.items() if key not in requested}
    else:
        raise SoundBankRuntimeError("invalid inclusion mode")
    return tuple((key, value) for key, value in result.items())


def _fixture_for_inclusion_name(
    blueprint: SoundBankBlueprint,
    name: str,
) -> ObjectFixture:
    matches = [
        fixture
        for fixture in blueprint.object_fixtures
        if fixture.key == f"inclusion:{name}"
    ]
    if len(matches) != 1:
        raise SoundBankRuntimeError(f"inclusion object fixture is not unique: {name}")
    return matches[0]


def _dedupe_object_fixtures(
    fixtures: Sequence[ObjectFixture],
) -> tuple[ObjectFixture, ...]:
    by_path: dict[str, ObjectFixture] = {}
    for fixture in fixtures:
        key = fixture.path.casefold()
        previous = by_path.get(key)
        if previous is None:
            by_path[key] = fixture
            continue
        if (
            previous.name,
            previous.object_type,
            previous.parent_path,
            previous.owned,
            previous.template_path,
        ) != (
            fixture.name,
            fixture.object_type,
            fixture.parent_path,
            fixture.owned,
            fixture.template_path,
        ):
            raise SoundBankRuntimeError(
                f"conflicting object fixture path: {fixture.path}"
            )
    return tuple(by_path.values())


def _dedupe_artifacts(
    artifacts: Sequence[ExpectedArtifact],
) -> tuple[ExpectedArtifact, ...]:
    by_path: dict[str, ExpectedArtifact] = {}
    for artifact in artifacts:
        key = str(artifact.path.resolve(strict=False)).casefold()
        previous = by_path.get(key)
        if previous is not None and previous != artifact:
            raise SoundBankRuntimeError(
                f"conflicting expected artifact path: {artifact.path}"
            )
        by_path[key] = artifact
    return tuple(sorted(by_path.values(), key=lambda row: str(row.path)))


def _operation_request(
    version: str,
    operation: str,
    arguments: Mapping[str, Any],
) -> Mapping[str, Any]:
    return MappingProxyType(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": version,
            "operation": operation,
            "arguments": _json_clone(arguments),
        }
    )


def _strict_topic_payload_identity(
    value: Any,
    *,
    context: str,
    failures: list[str],
) -> tuple[str, str] | None:
    """Return the hidden GUID and display name for one topic identity.

    The broker deliberately matches on prompt-visible names.  The trusted
    business oracle is stricter: a name-only payload must never be accepted as
    proof that the notification belongs to the runner-owned object/platform.
    """

    if not isinstance(value, Mapping):
        failures.append(f"{context} is not an identity object")
        return None
    raw_id = value.get("id")
    raw_name = value.get("name")
    if not isinstance(raw_id, str) or GUID_RE.fullmatch(raw_id) is None:
        failures.append(f"{context}.id is not a canonical GUID")
        return None
    if not isinstance(raw_name, str) or not raw_name:
        failures.append(f"{context}.name is absent")
        return None
    return raw_id, raw_name


def _payload_identity(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key in ("id", "name", "shortName", "baseName"):
            raw = value.get(key)
            if isinstance(raw, (str, int)) and not isinstance(raw, bool):
                return str(raw)
        return None
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        return str(value)
    return None


def _result_rows(
    value: Any,
    context: str,
    *,
    key: str = "return",
) -> tuple[Mapping[str, Any], ...]:
    if value is None and key == "return":
        return ()
    if not isinstance(value, Mapping):
        raise SoundBankRuntimeError(f"{context} must return an object")
    rows = value.get(key)
    if rows is None and key == "return":
        return ()
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        raise SoundBankRuntimeError(f"{context}.{key} must be an object array")
    return tuple(dict(row) for row in rows)


def _canonical_language(value: str) -> str:
    if value in CANONICAL_LANGUAGE:
        return CANONICAL_LANGUAGE[value]
    if value in CANONICAL_LANGUAGE.values():
        return value
    raise SoundBankRuntimeError(f"unreviewed Wwise language: {value!r}")


def _filters(value: Any) -> tuple[str, ...]:
    rows = _string_rows(value, "filters")
    if not rows or len(rows) != len(set(rows)) or set(rows) - ALLOWED_FILTERS:
        raise SoundBankRuntimeError("inclusion filters escaped the closed set")
    return tuple(rows)


def _fields(value: Sequence[str]) -> tuple[str, ...]:
    result = tuple(value)
    if not result or len(result) != len(set(result)) or any(
        not isinstance(item, str) or not item for item in result
    ):
        raise SoundBankRuntimeError("WAAPI return fields are invalid")
    allowed = {*MEDIA_OBJECT_FIELDS, *MEDIA_SOURCE_FIELDS}
    if set(result) - allowed:
        raise SoundBankRuntimeError("WAAPI return fields escaped the closed set")
    return result


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SoundBankRuntimeError(f"{field} must be an object")
    return value


def _mapping_rows(value: Any, field: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list) or not all(isinstance(row, Mapping) for row in value):
        raise SoundBankRuntimeError(f"{field} must be an object array")
    return tuple(value)


def _string_rows(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value or not all(
        isinstance(row, str) and row for row in value
    ):
        raise SoundBankRuntimeError(f"{field} must be a non-empty string array")
    if len(value) != len(set(value)):
        raise SoundBankRuntimeError(f"{field} must not contain duplicates")
    return tuple(value)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise SoundBankRuntimeError(f"{field} must be a non-empty normalized string")
    return value


def _segment(value: Any, field: str) -> str:
    result = _text(value, field)
    if not SAFE_SEGMENT_RE.fullmatch(result) or result in {".", ".."}:
        raise SoundBankRuntimeError(f"{field} is not a safe Wwise/path segment")
    return result


def _wwise_path(value: Any, field: str) -> str:
    result = _text(value, field)
    if not result.startswith("\\") or result.endswith("\\") or "\\\\" in result:
        raise SoundBankRuntimeError(f"{field} must be an absolute Wwise object path")
    for segment in result[1:].split("\\"):
        _segment(segment, field)
    return result


def _setup_event_value(event_path: str) -> str:
    """Encode the reviewed setup Event as Wwise's path-and-action value."""

    path = _wwise_path(event_path, "event_path")
    if "@" in path:
        raise SoundBankRuntimeError("event_path must not embed an Event action")
    return f"{path}@{SETUP_EVENT_ACTION}"


def _typed_existing_import_path(
    value: str,
    *,
    object_type: str,
) -> tuple[str, str]:
    """Return canonical readback and typed wire paths for ``useExisting``.

    Wwise 2022 resolves an untyped final segment as a Virtual Folder in this
    audio-import shape.  Keep the typed grammar private to the wire payload:
    every identity/readback check continues to use the logical Sound path.
    """

    raw_path = _text(value, "localized useExisting object_path")
    if "<" in raw_path or ">" in raw_path:
        raise SoundBankRuntimeError(
            "localized useExisting object_path must be an untyped canonical path"
        )
    canonical_path = _wwise_path(raw_path, "localized useExisting object_path")
    if object_type not in {"Sound Voice", "Sound SFX"}:
        raise SoundBankRuntimeError(
            "localized useExisting object_type must be closed as Sound Voice or Sound SFX"
        )
    parent, separator, name = canonical_path.rpartition("\\")
    if not separator or not parent or not name:
        raise SoundBankRuntimeError(
            "localized useExisting object_path has no creatable parent"
        )
    return canonical_path, f"{parent}\\<{object_type}>{_segment(name, 'sound name')}"


def _safe_filename(value: str) -> str:
    result = _segment(value, "filename")
    if Path(result).name != result:
        raise SoundBankRuntimeError("filename must not contain a directory")
    return result


def _safe_relative_path(value: Any, field: str) -> str:
    result = _text(value, field).replace("\\", "/")
    path = PurePosixPath(result)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise SoundBankRuntimeError(f"{field} must be a safe relative path")
    for part in path.parts:
        _segment(part, field)
    return path.as_posix()


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SoundBankRuntimeError(f"{field} must be a positive integer")
    return value


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise SoundBankRuntimeError(f"{field} must be a boolean")
    return value


def _guid(value: Any, field: str) -> str:
    if not isinstance(value, str) or not GUID_RE.fullmatch(value):
        raise SoundBankRuntimeError(f"{field} must be a canonical GUID")
    return value.upper()


def _same_identity(left: Any, right: Any) -> bool:
    return str(left).casefold() == str(right).casefold()


def _require_under(path: Path, root: Path, field: str) -> None:
    resolved_path = path.expanduser().resolve(strict=False)
    resolved_root = root.expanduser().resolve(strict=False)
    if resolved_path == resolved_root or resolved_root not in resolved_path.parents:
        raise SoundBankRuntimeError(f"{field} escapes the scenario-owned I/O root")


def _require_key(values: Mapping[str, str], key: str) -> str:
    try:
        return values[key]
    except KeyError as exc:
        raise SoundBankRuntimeError(f"missing live fixture identity: {key}") from exc


def _require_int_key(values: Mapping[str, int], key: str) -> int:
    try:
        return values[key]
    except KeyError as exc:
        raise SoundBankRuntimeError(f"missing live fixture short ID: {key}") from exc


def _fixture_prefix(scenario_id: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_]", "_", scenario_id)
    return f"V3_{token}"[:63]


def _visible_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _natural_display_path(value: str, io_root: Path) -> str:
    """Show a useful case-local path without leaking harness vocabulary.

    The v3 natural-prompt linter intentionally rejects words such as
    ``sandbox`` and ``runner`` even when they occur incidentally in a temporary
    directory name.  Operation requests retain the exact absolute path; this
    model-visible location is only an explanatory alias.
    """

    path = Path(value).expanduser().resolve(strict=False)
    # Successful semantic cases remove their owned tree after this projection
    # has been sealed.  The renderer is intentionally lexical so campaign
    # verify-only can reproduce the alias from the archived, prevalidated
    # projection without reopening deleted project files.
    root = io_root.expanduser().resolve(strict=False)
    _require_under(path, root, "display path")
    relative = path.relative_to(root).as_posix()
    return re.sub(
        r"(?i)(runner|fixture|sandbox|oracle|harness)",
        "case",
        f"$CASE_ROOT/{relative}",
    )


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _unique(values: Sequence[Any] | Any) -> list[Any]:
    result: list[Any] = []
    seen: set[Any] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


__all__ = [
    "BankState",
    "ClosedDirectWaapiSoundBankBackend",
    "DefinitionDocumentPlan",
    "DefinitionRowPlan",
    "EFFECT_TEMPLATE_PATH",
    "EventGraphState",
    "EXPECTED_SCENARIO_COUNT",
    "ExpectedArtifact",
    "ExternalSourceDocument",
    "ExternalSourceRow",
    "FileProof",
    "InclusionRow",
    "MaterializedSoundBankCase",
    "MEDIA_OBJECT_FIELDS",
    "MEDIA_SOURCE_FIELDS",
    "MediaFixture",
    "MediaSourceState",
    "ObjectFixture",
    "ObjectState",
    "OPERATION_REQUEST_CONTRACT",
    "PreparedSoundBankRuntime",
    "PROCESS_REFUSAL_ERROR_CODE",
    "PROCESS_REFUSAL_ID",
    "SOUNDBANK_APIS",
    "SOUNDBANK_RUNTIME_CONTRACT",
    "SOUNDBANK_TOPIC",
    "SOUNDBANK_TOPIC_RETURN_FIELDS",
    "SoundBankBlueprint",
    "SoundBankFixture",
    "SoundBankRuntimeBackend",
    "SoundBankRuntimeError",
    "SoundBankSnapshot",
    "SoundBankVerification",
    "TopicExpectedEvent",
    "TopicPlan",
    "TopicPublisher",
    "TopicVerification",
    "TreeEntry",
    "build_soundbank_blueprint",
    "build_soundbank_generation_prompt_projection",
    "prepare_soundbank_runtime",
    "render_soundbank_generation_build_locations",
    "verify_topic_payloads",
]
