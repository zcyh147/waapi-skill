"""Closed fixture, broker request, lifecycle, and oracle for 20 v3 CLI cases.

The four ``ak.wwise.cli`` functions covered here are still executed by the
evaluated Codex task through one immutable ``waapi.call`` transaction.  This
module never executes the requested business operation on the model's behalf.

The trusted runner owns three strictly separated process phases:

* an optional project-loaded setup server used only to build the fixture;
* a fresh case-owned business-host server which receives the one broker-approved
  transaction; and
* an optional project-loaded read-only oracle server after the business server
  has exited.

Every process command is the exact argv produced by
``build_wwise_console_command``.  Shell execution, extra arguments, custom Wwise
commands, residual processes, source-template drift, ambiguous dispatches, and
unbounded output all fail closed.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import shutil
import struct
import wave
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Literal, Protocol

from tests.semantic.support.codex_eval_bundle_v3 import OnlineScenario
from tests.semantic.support.codex_eval_protocol_v3 import (
    V3GatewayProtocol,
    build_transaction_protocol,
)
from tests.semantic.support.codex_host_paths import (
    ReflectedHostPathError,
    WindowsDrivePath,
    parse_posix_absolute_path,
    parse_windows_drive_path,
)
from wwise_waapi.operation_soundbank import parse_soundbank_definition_file
from wwise_waapi.platform_paths import build_wwise_console_command

try:  # ``pwd`` is unavailable on native Windows, where Wine mapping is not used.
    import pwd
except ImportError:  # pragma: no cover - native Windows hosts skip this branch
    pwd = None  # type: ignore[assignment]


CLI_RUNTIME_CONTRACT = "waapi-skill.codex-cli-runtime/v3"
OPERATION_REQUEST_CONTRACT = "waapi-skill.operation-request/v1"
SUPPORTED_VERSION = "2022.1"
CLI_APIS = MappingProxyType(
    {
        "ak.wwise.cli.generateSoundbank": "generateSoundbank",
        "ak.wwise.cli.tabDelimitedImport": "tabDelimitedImport",
        "ak.wwise.cli.convertExternalSource": "convertExternalSource",
        "ak.wwise.cli.migrate": "migrate",
    }
)
REVIEWED_2022_PROCESS_RESULT_URIS = frozenset(CLI_APIS)
EXPECTED_CLI_SCENARIO_COUNT = 20
SETUP_EVENT_ACTION = "Play"
MIGRATION_SOURCE_ROOT = (
    Path(__file__).resolve().parents[2] / "_org" / "2021.1"
)
MAX_TREE_FILES = 8192
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_LOG_BYTES = 1024 * 1024
MAX_OBJECTS = 512
GUID_RE = re.compile(
    r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$"
)
SAFE_SEGMENT_RE = re.compile(r'^[^\\/\x00-\x1f<>:"|?*]+$')
_FATAL_RE = re.compile(r"(?:^|\b)(?:fatal|unresolved\s+reference)(?:\b|$)", re.I)
_CREATE_TYPES = frozenset(
    {"ActorMixer", "Bus", "Event", "Folder", "SoundBank", "WorkUnit"}
)
_GENERATED_PROJECT_SUFFIXES = frozenset(
    {
        ".akd",
        ".bnk",
        ".log",
        ".prof",
        ".profraw",
        ".validationcache",
        ".wem",
        ".wsettings",
    }
)
_GENERATED_PROJECT_NAMES = frozenset(
    {".ds_store", "incrementalsoundbankdata.xml"}
)
_GENERATED_PROJECT_DIRECTORY_NAMES = frozenset(
    {
        ".backup",
        ".cache",
        ".claude",
        ".pytest_cache",
        "generatedsoundbanks",
        "logs",
        "profiler",
        "temp",
        "wwiseaudiocache",
    }
)
_OBJECT_FIELDS = (
    "id",
    "name",
    "type",
    "path",
    "parent",
    "notes",
    "shortId",
    "activeSource",
    "originalFilePath",
    "sound:originalWavFilePath",
    "audioSource:language",
)


class CliRuntimeError(RuntimeError):
    """A CLI fixture, lifecycle, dispatch, or business oracle failed closed."""


DirectWaapiCall = Callable[
    [str, Mapping[str, Any], Mapping[str, Any]], Any
]


@dataclass(frozen=True, slots=True)
class FileProof:
    path: str
    relative_path: str
    size: int
    sha256: str
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class TreeProof:
    root: str
    files: tuple[FileProof, ...]
    sha256: str

    def by_relative_path(self) -> dict[str, FileProof]:
        return {item.relative_path: item for item in self.files}


@dataclass(frozen=True, slots=True)
class SoundbanksInfoRecord:
    platform: str
    bank: str
    language: str
    relative_path: str
    media: tuple[tuple[str, str], ...]
    events: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CliObjectRecord:
    path: str
    object_id: str
    object_type: str
    name: str
    parent_id: str | None = None
    language: str | None = None
    source_path: str | None = None
    source_sha256: str | None = None
    notes: str | None = None
    short_id: int | None = None


@dataclass(frozen=True, slots=True)
class CliEventRecord:
    path: str
    object_id: str
    action_ids: tuple[str, ...]
    target_ids: tuple[str, ...]
    action_types: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SetupAudioImport:
    audio_file: Path
    object_path: str
    object_type: str
    language: str
    notes: str | None = None
    event_path: str | None = None
    import_operation: str = "createNew"


class CliRuntimeBackend(Protocol):
    """Closed trusted setup/readback seam; never expose it to Codex."""

    def get_context(self) -> Mapping[str, Any]: ...

    def read_object(self, path: str) -> CliObjectRecord | None: ...

    def read_localized_object(
        self,
        path: str,
        *,
        language: str,
    ) -> CliObjectRecord | None: ...

    def read_event(self, path: str) -> CliEventRecord | None: ...

    def ensure_object(self, *, path: str, object_type: str) -> CliObjectRecord: ...

    def import_audio(self, request: SetupAudioImport) -> CliObjectRecord: ...

    def replace_soundbank_inclusions(
        self,
        *,
        soundbank_path: str,
        event_paths: Sequence[str],
        filters: Sequence[str],
    ) -> None: ...

    def save_project(self) -> None: ...


class ClosedDirectCliBackend:
    """Direct WAAPI setup/readback adapter with no generic public call method."""

    def __init__(self, call: DirectWaapiCall) -> None:
        if not callable(call):
            raise TypeError("call must be callable")
        self._call = call

    def get_context(self) -> Mapping[str, Any]:
        info = self._call("ak.wwise.core.getInfo", {}, {})
        project = self._call("ak.wwise.core.getProjectInfo", {}, {})
        if not isinstance(info, Mapping) or not isinstance(project, Mapping):
            raise CliRuntimeError("closed backend context calls must return objects")
        return MappingProxyType({"info": dict(info), "project": dict(project)})

    def read_object(self, path: str) -> CliObjectRecord | None:
        return self._read_object(path, language=None)

    def read_localized_object(
        self,
        path: str,
        *,
        language: str,
    ) -> CliObjectRecord | None:
        requested_language = _canonical_language(language)
        record = self._read_object(path, language=requested_language)
        if record is not None and not _language_matches(
            record.language,
            requested_language,
        ):
            raise CliRuntimeError(
                f"localized Audio Source language mismatch for {path}: "
                f"{requested_language}"
            )
        return record

    def _read_object(
        self,
        path: str,
        *,
        language: str | None,
    ) -> CliObjectRecord | None:
        rows = self._read_rows(
            {"from": {"path": [_wwise_path(path)]}},
            _OBJECT_FIELDS,
            language=language,
        )
        if len(rows) > 1:
            raise CliRuntimeError(f"object path resolved more than once: {path}")
        if not rows:
            return None
        row = rows[0]
        object_id = _guid(row.get("id"), "object id")
        active_source = row.get("activeSource")
        source_row: Mapping[str, Any] | None = None
        source_id = _identity_value(active_source)
        if source_id:
            source_rows = self._read_rows(
                {"from": {"id": [source_id]}},
                _OBJECT_FIELDS,
                language=language,
            )
            if len(source_rows) != 1:
                raise CliRuntimeError(
                    f"active source for {path} did not resolve exactly once"
                )
            source_row = source_rows[0]
        source_path = _first_text(source_row or {}, "originalFilePath")
        if source_path is None:
            source_path = _first_text(
                row,
                "originalFilePath",
                "sound:originalWavFilePath",
            )
        source_sha = None
        if source_path:
            source_file = _localize_waapi_host_path(
                source_path,
                field="active source path",
            ).resolve(strict=True)
            if not source_file.is_file():
                raise CliRuntimeError("active source path is not a regular file")
            source_path = str(source_file)
            source_sha = _file_sha256(source_file)
        object_type = _type_name(row.get("type"))
        reflected_language: str | None = None
        source_language = (
            source_row.get("audioSource:language")
            if source_row is not None
            else None
        )
        if source_language is not None:
            reflected_language = _language_name(
                source_language,
                "active source language",
            )
        elif row.get("audioSource:language") is not None:
            reflected_language = _language_name(
                row["audioSource:language"],
                "Sound active source language",
            )
        return CliObjectRecord(
            path=_required_text(row.get("path"), "object path"),
            object_id=object_id,
            object_type=object_type,
            name=_required_text(row.get("name"), "object name"),
            parent_id=_identity_value(row.get("parent")),
            language=reflected_language,
            source_path=source_path,
            source_sha256=source_sha,
            notes=_optional_text(row.get("notes")),
            short_id=_optional_int(row.get("shortId")),
        )

    def read_event(self, path: str) -> CliEventRecord | None:
        event = self.read_object(path)
        if event is None:
            return None
        children = self._read_rows(
            {
                "from": {"id": [event.object_id]},
                "transform": [{"select": ["children"]}],
            },
            ("id", "type", "ActionType", "Target"),
        )
        action_ids: list[str] = []
        target_ids: list[str] = []
        action_types: list[int] = []
        for row in children:
            if _type_name(row.get("type")) != "Action":
                raise CliRuntimeError(f"event {path} has a non-Action direct child")
            action_ids.append(_guid(row.get("id"), "action id"))
            target = _identity_value(row.get("Target"))
            if not target:
                raise CliRuntimeError(f"event {path} Action lacks Target")
            target_ids.append(_guid(target, "action target"))
            action_types.append(_required_int(row.get("ActionType"), "ActionType"))
        return CliEventRecord(
            path=path,
            object_id=event.object_id,
            action_ids=tuple(action_ids),
            target_ids=tuple(target_ids),
            action_types=tuple(action_types),
        )

    def ensure_object(self, *, path: str, object_type: str) -> CliObjectRecord:
        if object_type not in _CREATE_TYPES:
            raise CliRuntimeError(f"setup type is not closed: {object_type}")
        normalized = _wwise_path(path)
        existing = self.read_object(normalized)
        if existing is not None:
            if not _types_equivalent(existing.object_type, object_type):
                raise CliRuntimeError(
                    f"existing setup object has wrong type: {path} "
                    f"({existing.object_type} != {object_type})"
                )
            return existing
        parent, name = _split_wwise_path(normalized)
        result = self._call(
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
            raise CliRuntimeError("object.create setup result must be an object")
        created = self.read_object(normalized)
        if created is None or created.object_id != _guid(result.get("id"), "created id"):
            raise CliRuntimeError(f"created setup object did not read back: {path}")
        return created

    def import_audio(self, request: SetupAudioImport) -> CliObjectRecord:
        source = _regular_file(request.audio_file, field="setup audio_file")
        if request.import_operation not in {"createNew", "useExisting", "replaceExisting"}:
            raise CliRuntimeError("setup import operation is not closed")
        object_type = _required_text(request.object_type, "object type")
        language = _canonical_language(_required_text(request.language, "language"))
        if request.import_operation == "useExisting":
            object_path, wire_object_path = _typed_existing_import_path(
                request.object_path,
                object_type=object_type,
                language=language,
            )
        else:
            object_path = _wwise_path(request.object_path)
            wire_object_path = object_path
        row: dict[str, Any] = {
            "audioFile": str(source),
            "objectPath": wire_object_path,
            "importLanguage": language,
        }
        if request.import_operation == "useExisting":
            # Wwise 2022 localization accepts only the audio-file addition for
            # an existing Voice.  Object creation/update columns are reported
            # as an invalid localization operation even though Wwise says they
            # will be ignored, so keep the wire row deliberately minimal.
            if request.notes is not None or request.event_path is not None:
                raise CliRuntimeError(
                    "localized useExisting setup accepts only an audio-file addition"
                )
        else:
            row["objectType"] = object_type
            if request.notes is not None:
                row["notes"] = str(request.notes)
            if request.event_path is not None:
                row["event"] = _setup_event_value(request.event_path)
        result = self._call(
            "ak.wwise.core.audio.import",
            {
                "importOperation": request.import_operation,
                "imports": [row],
                "autoAddToSourceControl": False,
            },
            {"return": list(_OBJECT_FIELDS)},
        )
        _result_rows(result, "audio.import", key="objects")
        imported = self.read_localized_object(
            object_path,
            language=language,
        )
        if imported is None:
            raise CliRuntimeError(f"setup import target is absent: {object_path}")
        return imported

    def replace_soundbank_inclusions(
        self,
        *,
        soundbank_path: str,
        event_paths: Sequence[str],
        filters: Sequence[str],
    ) -> None:
        bank = self.read_object(soundbank_path)
        if bank is None or bank.object_type != "SoundBank":
            raise CliRuntimeError("setup SoundBank does not resolve exactly")
        normalized_filters = tuple(filters)
        if not normalized_filters or not set(normalized_filters).issubset(
            {"events", "structures", "media"}
        ):
            raise CliRuntimeError("setup inclusion filters escaped the closed set")
        events: list[dict[str, Any]] = []
        for path in event_paths:
            event = self.read_event(path)
            if event is None:
                raise CliRuntimeError(f"setup Event is absent: {path}")
            events.append(
                {"object": event.object_id, "filter": list(normalized_filters)}
            )
        result = self._call(
            "ak.wwise.core.soundbank.setInclusions",
            {
                "soundbank": bank.object_id,
                "operation": "replace",
                "inclusions": events,
            },
            {},
        )
        if result is not None and not isinstance(result, Mapping):
            raise CliRuntimeError("setInclusions setup result must be object or null")

    def save_project(self) -> None:
        result = self._call("ak.wwise.core.project.save", {}, {})
        if result is not None and not isinstance(result, Mapping):
            raise CliRuntimeError("project.save setup result must be object or null")

    def _read_rows(
        self,
        args: Mapping[str, Any],
        fields: Sequence[str],
        *,
        language: str | None = None,
    ) -> tuple[Mapping[str, Any], ...]:
        options: dict[str, Any] = {
            "return": list(_unique_texts(fields, "return fields")),
        }
        if language is not None:
            options["language"] = _canonical_language(language)
        result = self._call(
            "ak.wwise.core.object.get",
            dict(args),
            options,
        )
        return _result_rows(result, "object.get")


ProcessRole = Literal["setup", "business", "oracle"]


@dataclass(frozen=True, slots=True)
class ProcessPhaseSpec:
    role: ProcessRole
    argv: tuple[str, ...]
    cwd: str | None
    project_path: str | None
    required: bool
    read_only_oracle: bool

    def validate_evidence(self, evidence: "ProcessPhaseEvidence") -> tuple[str, ...]:
        failures: list[str] = []
        if evidence.role != self.role:
            failures.append(f"{self.role} evidence role mismatch")
        if evidence.argv != self.argv:
            failures.append(f"{self.role} WwiseConsole argv mismatch")
        if evidence.cwd != self.cwd:
            failures.append(f"{self.role} WwiseConsole cwd mismatch")
        if evidence.shell is not False:
            failures.append(f"{self.role} WwiseConsole must use shell=False")
        if not evidence.started or not evidence.ready:
            failures.append(f"{self.role} WwiseConsole readiness was not proven")
        if not evidence.process_exited:
            failures.append(f"{self.role} WwiseConsole did not exit")
        if evidence.residual_pids:
            failures.append(f"{self.role} retained residual WwiseConsole processes")
        if evidence.shutdown_error:
            failures.append(f"{self.role} WwiseConsole shutdown failed")
        if self.project_path is not None:
            observed = evidence.open_project_path
            if observed is not None and _resolve(observed) != _resolve(self.project_path):
                failures.append(f"{self.role} opened the wrong project")
        elif evidence.open_project_path is not None:
            failures.append(f"{self.role} server unexpectedly loaded a project")
        return tuple(failures)


@dataclass(frozen=True, slots=True)
class ProcessPhaseEvidence:
    role: ProcessRole
    argv: tuple[str, ...]
    cwd: str | None
    shell: bool
    started: bool
    ready: bool
    process_exited: bool
    residual_pids: tuple[int, ...] = ()
    shutdown_error: str | None = None
    open_project_path: str | None = None
    returncode: int | None = None
    natural_exit_before_shutdown: bool = False
    runner_shutdown_requested: bool = False


@dataclass(frozen=True, slots=True)
class CliLifecyclePlan:
    setup: ProcessPhaseSpec | None
    business: ProcessPhaseSpec
    oracle: ProcessPhaseSpec | None
    business_disconnect_may_occur: bool

    @property
    def phases(self) -> tuple[ProcessPhaseSpec, ...]:
        return tuple(
            phase
            for phase in (self.setup, self.business, self.oracle)
            if phase is not None
        )


@dataclass(frozen=True, slots=True)
class CliDispatchEvidence:
    api: str
    primary_dispatch_count: int
    dispatch_started: bool
    dispatch_completed: bool
    gateway_verify_state: str | None
    process_result: int | None
    connection_lost: bool
    connection_lost_after_dispatch: bool
    stdout: str = ""
    stderr: str = ""
    classified_load_issues: tuple[str, ...] = ()
    unclassified_load_issues: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExpectedOutput:
    kind: Literal["bank", "automatic", "external"]
    path: Path
    platform: str | None
    business_name: str
    required_change: bool


@dataclass(frozen=True, slots=True)
class AnchorInventory:
    key: str
    identity: tuple[str, str, str, tuple[str, str, str] | None]
    semantic_rows: tuple[tuple[Any, ...], ...]
    reference_rows: tuple[tuple[Any, ...], ...]


@dataclass(frozen=True, slots=True)
class CliRuntimeSnapshot:
    project_tree: TreeProof
    source_template_tree: TreeProof
    asset_tree: TreeProof
    output_tree: TreeProof
    objects: tuple[CliObjectRecord, ...]
    events: tuple[CliEventRecord, ...]
    migration_inventory: tuple[AnchorInventory, ...]
    project_version: str | None


@dataclass(frozen=True, slots=True)
class CliRuntimeVerification:
    scenario_id: str
    phase: str
    passed: bool
    failures: tuple[str, ...]
    before: CliRuntimeSnapshot
    after: CliRuntimeSnapshot

    def assert_passed(self) -> None:
        if not self.passed:
            raise CliRuntimeError(
                f"{self.scenario_id} {self.phase} verification failed: "
                + "; ".join(self.failures)
            )


@dataclass(frozen=True, slots=True)
class CliRuntimePlan:
    scenario: OnlineScenario
    version: str
    operation: str
    case_root: Path
    project_path: Path
    project_root: Path
    business_server_project_path: Path
    source_template_root: Path
    asset_root: Path
    io_root: Path
    asset_spec: Mapping[str, Any]

    @property
    def requires_setup(self) -> bool:
        return self.operation in {"generateSoundbank", "tabDelimitedImport"}

    @property
    def requires_oracle(self) -> bool:
        return self.operation in {"tabDelimitedImport", "migrate"}

    @property
    def business_disconnect_may_occur(self) -> bool:
        return self.operation == "migrate"

    def lifecycle_plan(
        self,
        *,
        console_path: Path,
        business_port: int,
        setup_port: int | None = None,
        oracle_port: int | None = None,
    ) -> CliLifecyclePlan:
        console = _regular_file(console_path, field="console_path", executable=True)
        ports = [business_port]
        if self.requires_setup:
            if setup_port is None:
                raise CliRuntimeError("setup lifecycle requires a dedicated port")
            ports.append(setup_port)
        elif setup_port is not None:
            raise CliRuntimeError("setup port supplied for a static CLI fixture")
        if self.requires_oracle:
            if oracle_port is None:
                raise CliRuntimeError("oracle lifecycle requires a dedicated port")
            ports.append(oracle_port)
        elif oracle_port is not None:
            raise CliRuntimeError("oracle port supplied for a no-reopen CLI fixture")
        if len(ports) != len(set(ports)) or any(
            not isinstance(port, int)
            or isinstance(port, bool)
            or not 1 <= port <= 65535
            for port in ports
        ):
            raise CliRuntimeError("CLI lifecycle ports must be distinct valid integers")
        if self.business_server_project_path == self.project_path:
            raise CliRuntimeError("CLI business control project must differ from target")
        if self.case_root not in self.business_server_project_path.parents:
            raise CliRuntimeError("CLI business control project must be case-owned")

        setup = (
            _phase_spec(
                "setup",
                console,
                setup_port,
                project_path=self.project_path,
                cwd=self.case_root,
            )
            if self.requires_setup
            else None
        )
        # WwiseConsole 2022.1 requires a project while starting waapi-server.
        # Every CLI operation receives a separate case-owned control project,
        # leaving the operation target exclusively in the immutable request.
        business = _phase_spec(
            "business",
            console,
            business_port,
            project_path=self.business_server_project_path,
            cwd=self.case_root,
        )
        oracle = (
            _phase_spec(
                "oracle",
                console,
                oracle_port,
                project_path=self.project_path,
                cwd=self.case_root,
                read_only_oracle=True,
            )
            if self.requires_oracle
            else None
        )
        return CliLifecyclePlan(
            setup=setup,
            business=business,
            oracle=oracle,
            business_disconnect_may_occur=self.business_disconnect_may_occur,
        )


@dataclass(slots=True)
class PreparedCliRuntime:
    plan: CliRuntimePlan
    root_bindings: Mapping[str, Path]
    visible_values: Mapping[str, str]
    input_proofs: tuple[FileProof, ...]
    expected_outputs: tuple[ExpectedOutput, ...]
    control_output_paths: tuple[Path, ...]
    _gateway_args: Mapping[str, Any] | None
    _before: CliRuntimeSnapshot | None = None
    _setup_objects: tuple[CliObjectRecord, ...] = ()
    _setup_events: tuple[CliEventRecord, ...] = ()
    _tab_before_by_path: Mapping[str, CliObjectRecord | None] | None = None
    _control_before: Mapping[str, CliObjectRecord | CliEventRecord] | None = None

    @property
    def before(self) -> CliRuntimeSnapshot:
        if self._before is None:
            raise CliRuntimeError("CLI before snapshot has not been sealed")
        return self._before

    @property
    def lifecycle_contract(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "contract": CLI_RUNTIME_CONTRACT,
                "setup_required": self.plan.requires_setup,
                "business_server_project": str(self.plan.business_server_project_path),
                "oracle_required": self.plan.requires_oracle,
                "phase_order": [
                    role
                    for role, enabled in (
                        ("setup", self.plan.requires_setup),
                        ("business", True),
                        ("oracle", self.plan.requires_oracle),
                    )
                    if enabled
                ],
                "residual_process_policy": "any_residual_is_blocked",
                "business_disconnect_may_occur": self.plan.business_disconnect_may_occur,
            }
        )

    def prepare_setup(self, backend: CliRuntimeBackend) -> "PreparedCliRuntime":
        if not self.plan.requires_setup:
            raise CliRuntimeError("this CLI scenario has no live setup phase")
        if self._setup_objects or self._setup_events:
            raise CliRuntimeError("CLI setup is single-use")
        _assert_backend_context(
            backend.get_context(),
            version=self.plan.version,
            project_path=self.plan.project_path,
        )
        if self.plan.operation == "generateSoundbank":
            objects, events = self._prepare_generate(backend)
        else:
            objects, events = self._prepare_tab(backend)
        backend.save_project()
        self._setup_objects = objects
        self._setup_events = events
        # Definitions use runner-resolved Event GUIDs, so their request becomes
        # available only after closed setup materialization.
        if self.plan.operation == "generateSoundbank":
            self._finish_generate_definitions(backend)
            self._gateway_args = _gateway_args_for_materialized(self)
            self.visible_values = MappingProxyType(
                _visible_values_for_materialized(self)
            )
        return self

    def seal_before(
        self,
        *,
        lifecycle: CliLifecyclePlan,
        setup_evidence: ProcessPhaseEvidence | None = None,
    ) -> CliRuntimeSnapshot:
        if self._before is not None:
            raise CliRuntimeError("CLI before snapshot is already sealed")
        if self.plan.requires_setup:
            if not self._setup_objects and not self._setup_events:
                raise CliRuntimeError("setup fixture was not prepared")
            if lifecycle.setup is None or setup_evidence is None:
                raise CliRuntimeError("setup process ownership proof is missing")
            failures = lifecycle.setup.validate_evidence(setup_evidence)
            if failures:
                raise CliRuntimeError("; ".join(failures))
        elif setup_evidence is not None or lifecycle.setup is not None:
            raise CliRuntimeError("unexpected setup process evidence")
        self._before = self.snapshot(backend=None)
        return self._before

    def render_prompt(self) -> str:
        if self._before is None:
            raise CliRuntimeError("prompt cannot be rendered before setup is sealed")
        return self.plan.scenario.render_prompt(self.visible_values)

    def operation_request(self) -> Mapping[str, Any]:
        if self._before is None:
            raise CliRuntimeError("operation request cannot be exposed before setup is sealed")
        if self._gateway_args is None:
            raise CliRuntimeError("CLI operation request is not fully materialized")
        return MappingProxyType(
            {
                "contract": OPERATION_REQUEST_CONTRACT,
                "version": self.plan.version,
                "operation": "waapi.call",
                "arguments": {
                    "api": self.plan.scenario.api,
                    "args": dict(self._gateway_args),
                    "options": {},
                    "io_root": str(_derive_public_cli_io_root(self)),
                },
            }
        )

    def request_provenance(self) -> Mapping[str, str]:
        """Explain how every model-authored request field is reachable.

        This is review evidence, not a scenario-id request selector.  Paths and
        business choices come from the natural prompt; only the four public
        deterministic derivation rules documented in ``waapi-operate.md`` may
        add a value.
        """

        if self._gateway_args is None:
            raise CliRuntimeError("CLI request provenance requires materialized args")
        return MappingProxyType(_public_cli_request_provenance(self))

    def gateway_protocol(self) -> V3GatewayProtocol:
        return build_transaction_protocol(
            (self.operation_request(),),
            # Migration's execute result is terminal at the gateway boundary:
            # a caller-owned reopened-project oracle, not generic verify, is
            # authoritative whether its control host remains alive or exits.
            terminal_execute=self.plan.business_disconnect_may_occur,
        )

    def snapshot(
        self,
        *,
        backend: CliRuntimeBackend | None,
    ) -> CliRuntimeSnapshot:
        objects: list[CliObjectRecord] = []
        events: list[CliEventRecord] = []
        if (
            backend is None
            and self.plan.operation == "tabDelimitedImport"
            and self._tab_before_by_path is not None
            and self._control_before is not None
        ):
            objects.extend(
                value
                for value in self._tab_before_by_path.values()
                if value is not None
            )
            objects.extend(
                value
                for value in self._control_before.values()
                if isinstance(value, CliObjectRecord)
            )
            events.extend(
                value
                for value in self._control_before.values()
                if isinstance(value, CliEventRecord)
            )
        elif backend is not None and self.plan.operation == "tabDelimitedImport":
            expected = self.plan.asset_spec["expected"]
            for row in expected["objects"]:
                value = backend.read_localized_object(
                    str(row["path"]),
                    language=_canonical_language(str(row["language"])),
                )
                if value is not None:
                    objects.append(value)
                event_name = row.get("event")
                if event_name:
                    event_path = rf"\Events\Default Work Unit\{event_name}"
                    value_event = backend.read_event(event_path)
                    if value_event is not None:
                        events.append(value_event)
            for control_path in expected["controls"]:
                if str(control_path).startswith("\\Events\\"):
                    value_event = backend.read_event(str(control_path))
                    if value_event is not None:
                        events.append(value_event)
                else:
                    value = backend.read_object(str(control_path))
                    if value is not None:
                        objects.append(value)
        migration_inventory: tuple[AnchorInventory, ...] = ()
        if self.plan.operation == "migrate":
            migration_inventory = _migration_inventory(
                self.plan.project_root,
                self.plan.asset_spec,
            )
        return CliRuntimeSnapshot(
            project_tree=_tree_proof(self.plan.project_root),
            source_template_tree=_tree_proof(self.plan.source_template_root),
            asset_tree=_tree_proof(self.plan.asset_root),
            output_tree=_tree_proof(self.plan.io_root),
            objects=tuple(sorted(objects, key=lambda item: item.path)),
            events=tuple(sorted(events, key=lambda item: item.path)),
            migration_inventory=migration_inventory,
            project_version=_project_document_version(self.plan.project_path),
        )

    def verify_preview_unchanged(self) -> CliRuntimeVerification:
        before = self.before
        after = self.snapshot(backend=None)
        failures: list[str] = []
        if after.project_tree != before.project_tree:
            failures.append("project changed during immutable preview")
        if after.source_template_tree != before.source_template_tree:
            failures.append("source template changed during immutable preview")
        if after.asset_tree != before.asset_tree:
            failures.append("CLI input assets changed during immutable preview")
        if after.output_tree != before.output_tree:
            failures.append("CLI output tree changed during immutable preview")
        return CliRuntimeVerification(
            scenario_id=self.plan.scenario.id,
            phase="preview",
            passed=not failures,
            failures=tuple(failures),
            before=before,
            after=after,
        )

    def verify_after(
        self,
        *,
        dispatch: CliDispatchEvidence,
        lifecycle: CliLifecyclePlan,
        business_evidence: ProcessPhaseEvidence,
        oracle_backend: CliRuntimeBackend | None = None,
        oracle_evidence: ProcessPhaseEvidence | None = None,
    ) -> CliRuntimeVerification:
        failures = list(_dispatch_failures(self.plan, dispatch, business_evidence))
        failures.extend(lifecycle.business.validate_evidence(business_evidence))
        if self.plan.requires_oracle:
            if lifecycle.oracle is None or oracle_backend is None or oracle_evidence is None:
                failures.append("required read-only oracle lifecycle is missing")
            else:
                failures.extend(lifecycle.oracle.validate_evidence(oracle_evidence))
                try:
                    _assert_backend_context(
                        oracle_backend.get_context(),
                        version=self.plan.version,
                        project_path=self.plan.project_path,
                    )
                except CliRuntimeError as exc:
                    failures.append(str(exc))
        elif oracle_backend is not None or oracle_evidence is not None or lifecycle.oracle is not None:
            failures.append("unexpected oracle lifecycle for this CLI operation")

        after = self.snapshot(backend=oracle_backend)
        before = self.before
        if after.source_template_tree != before.source_template_tree:
            failures.append("immutable source project/template changed")
        if (
            self.plan.operation != "convertExternalSource"
            and after.asset_tree != before.asset_tree
        ):
            failures.append("CLI input assets changed")
        elif (
            self.plan.operation == "convertExternalSource"
            and not _convert_asset_tree_is_closed(before.asset_tree, after.asset_tree)
        ):
            failures.append("CLI input assets changed outside sealed Wwise .akd side effects")
        if self.plan.operation == "convertExternalSource":
            failures.extend(self._verify_convert(before, after))
        elif self.plan.operation == "generateSoundbank":
            failures.extend(self._verify_generate(before, after))
        elif self.plan.operation == "tabDelimitedImport":
            failures.extend(self._verify_tab(after, oracle_backend))
        elif self.plan.operation == "migrate":
            failures.extend(self._verify_migration(before, after))
        else:  # pragma: no cover - builder closes the operation set.
            failures.append("unknown CLI operation")
        return CliRuntimeVerification(
            scenario_id=self.plan.scenario.id,
            phase="after",
            passed=not failures,
            failures=tuple(failures),
            before=before,
            after=after,
        )

    def _prepare_generate(
        self,
        backend: CliRuntimeBackend,
    ) -> tuple[tuple[CliObjectRecord, ...], tuple[CliEventRecord, ...]]:
        manifest = self.plan.asset_spec["fixture_manifest"]
        profile = _segment(str(manifest["profile"]))
        actor_parent = rf"\Actor-Mixer Hierarchy\Default Work Unit\V3 CLI\{profile}"
        _ensure_chain(
            backend,
            actor_parent,
            root=r"\Actor-Mixer Hierarchy\Default Work Unit",
            object_type="ActorMixer",
        )
        wav_by_key = {
            proof.relative_path.rsplit("/", 1)[-1]: Path(proof.path)
            for proof in self.input_proofs
            if proof.relative_path.startswith("wav/")
        }
        objects: list[CliObjectRecord] = []
        events: list[CliEventRecord] = []
        imported_object_ids: dict[str, str] = {}
        captured_event_ids: dict[str, str] = {}
        for bank in manifest["soundbanks"]:
            bank_events = {row["name"]: row["object_path"] for row in bank["events"]}
            for media in bank["media"]:
                event_path = str(bank_events[media["event"]])
                event_parent, _ = _split_wwise_path(event_path)
                _ensure_chain(
                    backend,
                    event_parent,
                    root=r"\Events\Default Work Unit",
                    object_type="Folder",
                )
                explicit_object_path = media.get("object_path")
                sound_path = (
                    _wwise_path(str(explicit_object_path))
                    if explicit_object_path is not None
                    else actor_parent + "\\" + _segment(str(media["key"]))
                )
                if not sound_path.startswith(actor_parent + "\\"):
                    raise CliRuntimeError(
                        "localized Sound path escaped its case profile"
                    )
                import_operation = str(media.get("import_operation", "createNew"))
                create_event = media.get("create_event", True)
                if not isinstance(create_event, bool):
                    raise CliRuntimeError("localized create_event must be boolean")
                existing = backend.read_object(sound_path)
                if import_operation == "createNew":
                    if existing is not None:
                        raise CliRuntimeError(
                            f"localized createNew Sound already exists: {sound_path}"
                        )
                    if create_event and backend.read_event(event_path) is not None:
                        raise CliRuntimeError(
                            f"localized createNew Event already exists: {event_path}"
                        )
                elif import_operation == "useExisting":
                    if existing is None:
                        raise CliRuntimeError(
                            f"localized useExisting Sound is absent: {sound_path}"
                        )
                    if create_event:
                        raise CliRuntimeError(
                            "localized useExisting import must not recreate its Event"
                        )
                else:
                    raise CliRuntimeError(
                        f"unreviewed generated-fixture import operation: {import_operation}"
                    )
                wav_name = PurePosixPath(str(media["relative_wav"])).name
                try:
                    wav_path = wav_by_key[wav_name]
                except KeyError as exc:
                    raise CliRuntimeError(f"missing generated fixture WAV: {wav_name}") from exc
                imported = backend.import_audio(
                    SetupAudioImport(
                        audio_file=wav_path,
                        object_path=sound_path,
                        object_type="Sound Voice" if media["language"] != "SFX" else "Sound SFX",
                        language=str(media["language"]),
                        notes=(
                            f"{self.plan.scenario.id}:{media['key']}"
                            if import_operation == "createNew"
                            else None
                        ),
                        event_path=event_path if create_event else None,
                        import_operation=import_operation,
                    )
                )
                if existing is not None and imported.object_id != existing.object_id:
                    raise CliRuntimeError(
                        f"localized useExisting changed the logical Sound GUID: {sound_path}"
                    )
                requested_language = _canonical_language(str(media["language"]))
                localized = backend.read_localized_object(
                    sound_path,
                    language=requested_language,
                )
                if localized is None or localized.object_id != imported.object_id:
                    raise CliRuntimeError(
                        f"localized Sound identity did not read back for {requested_language}: "
                        f"{sound_path}"
                    )
                if not _language_matches(localized.language, requested_language):
                    raise CliRuntimeError(
                        f"localized Audio Source language mismatch for {sound_path}: "
                        f"{requested_language}"
                    )
                expected_source_sha = _file_sha256(wav_path)
                if localized.source_sha256 != expected_source_sha:
                    raise CliRuntimeError(
                        f"localized Audio Source bytes mismatch for {sound_path}: "
                        f"{requested_language}"
                    )
                if localized.source_path is None:
                    raise CliRuntimeError(
                        f"localized Audio Source lacks an Originals path: {sound_path}"
                    )
                copied_source = Path(localized.source_path).resolve(strict=True)
                originals_root = (self.plan.project_root / "Originals").resolve(
                    strict=True
                )
                if (
                    originals_root not in copied_source.parents
                    or copied_source.name != wav_path.name
                ):
                    raise CliRuntimeError(
                        f"localized Audio Source escaped its exact Originals binding: "
                        f"{sound_path} ({requested_language})"
                    )
                event = backend.read_event(event_path)
                if event is None or len(event.action_ids) != 1 or event.action_types != (1,):
                    raise CliRuntimeError(f"setup Event did not prove one Play Action: {event_path}")
                if event.target_ids != (imported.object_id,):
                    raise CliRuntimeError(f"setup Event target mismatch: {event_path}")
                previous_object_id = imported_object_ids.setdefault(
                    sound_path,
                    imported.object_id,
                )
                if previous_object_id != imported.object_id:
                    raise CliRuntimeError(
                        f"generated fixture Sound GUID drifted across languages: {sound_path}"
                    )
                if sound_path not in {item.path for item in objects}:
                    objects.append(imported)
                previous_event_id = captured_event_ids.setdefault(
                    event_path,
                    event.object_id,
                )
                if previous_event_id != event.object_id:
                    raise CliRuntimeError(
                        f"generated fixture Event GUID drifted: {event_path}"
                    )
                if event_path not in {item.path for item in events}:
                    events.append(event)
            for dependency in bank["dependencies"]:
                dependency_path = str(dependency["object_path"])
                dependency_type = str(dependency["type"])
                value = backend.ensure_object(
                    path=dependency_path,
                    object_type=dependency_type,
                )
                if not _types_equivalent(value.object_type, dependency_type):
                    raise CliRuntimeError("SoundBank fixture dependency is absent or wrong type")
                objects.append(value)
            bank_path = rf"\SoundBanks\Default Work Unit\{bank['name']}"
            if bank["project_object_mode"] == "existing_soundbank":
                bank_object = backend.ensure_object(
                    path=bank_path,
                    object_type="SoundBank",
                )
                backend.replace_soundbank_inclusions(
                    soundbank_path=bank_path,
                    event_paths=tuple(str(row["object_path"]) for row in bank["events"]),
                    filters=("events", "structures", "media"),
                )
                objects.append(bank_object)
            elif bank["project_object_mode"] == "temporary_request_only":
                if backend.read_object(bank_path) is not None:
                    raise CliRuntimeError("temporary definition SoundBank already exists")
            else:
                raise CliRuntimeError("unreviewed SoundBank project object mode")
        for name in manifest["control_soundbanks"]:
            objects.append(
                backend.ensure_object(
                    path=rf"\SoundBanks\Default Work Unit\{name}",
                    object_type="SoundBank",
                )
            )
        return tuple(objects), tuple(events)

    def _finish_generate_definitions(self, backend: CliRuntimeBackend) -> None:
        definitions = self.plan.asset_spec["assets"]["definition_files"]
        if not definitions:
            return
        definition_root = self.plan.asset_root / "definitions"
        definition_root.mkdir(parents=True, exist_ok=True)
        for definition in definitions:
            destination = _contained_file(definition_root, str(definition["name"]))
            lines: list[str] = []
            expected_rows: list[dict[str, Any]] = []
            for row in definition["rows"]:
                directive = str(row["directive"])
                resolved = (
                    backend.read_event(str(row["identity"]))
                    if directive == "Event"
                    else backend.read_object(str(row["identity"]))
                )
                if resolved is None:
                    raise CliRuntimeError(
                        f"definition identity did not resolve: {row['identity']}"
                    )
                cells = [str(row["soundbank"])]
                if directive.startswith("-"):
                    cells.append(directive)
                cells.extend(
                    [
                        resolved.object_id,
                        *[str(value) for value in row["filters"]],
                    ]
                )
                if any(any(token in cell for token in ("\t", "\r", "\n", '"')) for cell in cells):
                    raise CliRuntimeError("definition row is not safely serializable")
                lines.append("\t".join(cells))
                expected_rows.append(
                    {
                        "soundbank": str(row["soundbank"]),
                        "definition_keyword": directive,
                        "identity": {
                            "kind": "guid",
                            "value": _guid(
                                resolved.object_id,
                                "materialized definition identity",
                            ),
                        },
                        "filters": [
                            {
                                "Event": "events",
                                "Structure": "structures",
                                "Media": "media",
                            }[str(value)]
                            for value in row["filters"]
                        ],
                    }
                )
            destination.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")
            try:
                parsed = parse_soundbank_definition_file(destination)
            except Exception as exc:
                raise CliRuntimeError(
                    f"materialized SoundBank Definition failed parser validation: {destination.name}"
                ) from exc
            parsed_rows = parsed.get("rows")
            if not isinstance(parsed_rows, list) or len(parsed_rows) != len(expected_rows):
                raise CliRuntimeError(
                    f"materialized SoundBank Definition row count drifted: {destination.name}"
                )
            for expected, actual in zip(expected_rows, parsed_rows, strict=True):
                if any(actual.get(key) != value for key, value in expected.items()):
                    raise CliRuntimeError(
                        f"materialized SoundBank Definition identity/filters drifted: {destination.name}"
                    )
        self.input_proofs = _collect_input_proofs(self.plan.asset_root)

    def _prepare_tab(
        self,
        backend: CliRuntimeBackend,
    ) -> tuple[tuple[CliObjectRecord, ...], tuple[CliEventRecord, ...]]:
        spec = self.plan.asset_spec
        assets = spec["assets"]
        expected = spec["expected"]
        top = _segment(str(assets["existing_top_level_work_unit"]))
        top_path = rf"\Actor-Mixer Hierarchy\{top}"
        backend.ensure_object(path=top_path, object_type="WorkUnit")
        for row in expected.get("hierarchy", []):
            _ensure_chain(
                backend,
                str(row["path"]),
                root=top_path,
                object_type="ActorMixer",
            )
        for row in expected["objects"]:
            parent, _ = _split_wwise_path(str(row["path"]))
            _ensure_chain(
                backend,
                parent,
                root=top_path,
                object_type="ActorMixer",
            )
        controls: dict[str, CliObjectRecord | CliEventRecord] = {}
        for raw_path in expected["controls"]:
            path = str(raw_path)
            parent, _ = _split_wwise_path(path)
            if path.startswith("\\Events\\"):
                _ensure_chain(
                    backend,
                    parent,
                    root=r"\Events\Default Work Unit",
                    object_type="Folder",
                )
                obj = backend.ensure_object(path=path, object_type="Event")
                event = backend.read_event(path)
                if event is None:
                    raise CliRuntimeError("control Event did not read back")
                controls[path] = event
                _ = obj
            else:
                control_parts = path.split("\\")
                if (
                    len(control_parts) < 4
                    or control_parts[0] != ""
                    or control_parts[1] != "Actor-Mixer Hierarchy"
                ):
                    raise CliRuntimeError("tab import control escaped Actor-Mixer Hierarchy")
                control_root = rf"\Actor-Mixer Hierarchy\{_segment(control_parts[2])}"
                backend.ensure_object(path=control_root, object_type="WorkUnit")
                _ensure_chain(
                    backend,
                    parent,
                    root=control_root,
                    object_type="ActorMixer",
                )
                controls[path] = backend.ensure_object(path=path, object_type="ActorMixer")

        wav_by_key = _tab_wav_paths(self)
        before: dict[str, CliObjectRecord | None] = {}
        imported: list[CliObjectRecord] = []
        for row in expected["objects"]:
            path = str(row["path"])
            policy = str(row["guid_policy"])
            requested_language = _canonical_language(str(row["language"]))
            existing = backend.read_localized_object(
                path,
                language=requested_language,
            )
            if policy in {"preserved", "replaced"}:
                if existing is None:
                    prestate = _prestate_wav_path(self, str(row["source_key"]))
                    existing = backend.import_audio(
                        SetupAudioImport(
                            audio_file=prestate,
                            object_path=path,
                            object_type=str(row["type"]),
                            language=str(row["language"]),
                            notes=f"before:{self.plan.scenario.id}:{row['source_key']}",
                            import_operation="createNew",
                        )
                    )
                    existing = backend.read_localized_object(
                        path,
                        language=requested_language,
                    )
                    if existing is None:
                        raise CliRuntimeError(
                            f"localized tab baseline did not read back: {path} "
                            f"({requested_language})"
                        )
                if not _language_matches(existing.language, requested_language):
                    raise CliRuntimeError(
                        f"localized tab baseline language mismatch: {path} "
                        f"({requested_language})"
                    )
                before[path] = existing
                imported.append(existing)
            elif policy == "new_unique":
                if existing is not None:
                    raise CliRuntimeError(f"new target already exists before CLI import: {path}")
                before[path] = None
            else:
                raise CliRuntimeError("unreviewed tab GUID policy")
            if str(row["source_key"]) not in wav_by_key:
                raise CliRuntimeError("tab row references an unknown WAV")
        self._tab_before_by_path = MappingProxyType(before)
        self._control_before = MappingProxyType(controls)
        return tuple(imported) + tuple(
            value for value in controls.values() if isinstance(value, CliObjectRecord)
        ), tuple(
            value for value in controls.values() if isinstance(value, CliEventRecord)
        )

    def _verify_convert(
        self,
        before: CliRuntimeSnapshot,
        after: CliRuntimeSnapshot,
    ) -> tuple[str, ...]:
        failures: list[str] = []
        if not _convert_project_tree_is_closed(
            before.project_tree,
            after.project_tree,
            project_path=self.plan.project_path,
        ):
            failures.append("convertExternalSource changed the project copy")
        expected = {str(item.path): item for item in self.expected_outputs}
        before_files = before.output_tree.by_relative_path()
        after_files = after.output_tree.by_relative_path()
        expected_rel = {
            item.path.relative_to(self.plan.io_root).as_posix() for item in expected.values()
        }
        actual_wem = {
            relative for relative in after_files if relative.casefold().endswith(".wem")
        }
        control_rel = {
            path.relative_to(self.plan.io_root).as_posix() for path in self.control_output_paths
        }
        if actual_wem != expected_rel | control_rel:
            failures.append("external-source WEM set does not exactly match the reviewed destinations")
        for item in expected.values():
            proof = _proof_if_file(item.path, self.plan.io_root)
            if proof is None or not _valid_riff(item.path):
                failures.append(f"missing, empty, or invalid WEM: {item.path}")
                continue
            relative = item.path.relative_to(self.plan.io_root).as_posix()
            old = before_files.get(relative)
            if item.required_change and old is not None and old.sha256 == proof.sha256:
                failures.append(f"target WEM was not rebuilt: {item.path}")
        for path in self.control_output_paths:
            relative = path.relative_to(self.plan.io_root).as_posix()
            if before_files.get(relative) != after_files.get(relative):
                failures.append(f"unrelated control output changed: {path}")
        return tuple(failures)

    def _verify_generate(
        self,
        before: CliRuntimeSnapshot,
        after: CliRuntimeSnapshot,
    ) -> tuple[str, ...]:
        failures: list[str] = []
        if _authored_project_projection(after.project_tree) != _authored_project_projection(
            before.project_tree
        ):
            failures.append(
                "generateSoundbank changed the project authored content although save=false"
            )
        expected_banks = {
            item.path.relative_to(self.plan.io_root).as_posix()
            for item in self.expected_outputs
            if item.kind in {"bank", "automatic"} and item.path.suffix.casefold() == ".bnk"
        }
        actual_banks = {
            item.relative_path
            for item in after.output_tree.files
            if item.relative_path.casefold().endswith(".bnk")
        }
        if actual_banks != expected_banks:
            failures.append("generated SoundBank file set is not exact")
        before_files = before.output_tree.by_relative_path()
        for item in self.expected_outputs:
            proof = _proof_if_file(item.path, self.plan.io_root)
            if proof is None:
                failures.append(f"required generated artifact is missing: {item.path}")
                continue
            if item.path.suffix.casefold() == ".bnk" and not _valid_bank(item.path):
                failures.append(f"generated SoundBank header is invalid: {item.path}")
            if item.required_change:
                old = before_files.get(item.path.relative_to(self.plan.io_root).as_posix())
                if old is not None and old.sha256 == proof.sha256:
                    failures.append(f"stale generated artifact was not replaced: {item.path}")
        expected = self.plan.asset_spec["expected"]
        absent = {str(value).casefold() for value in expected["absent_banks"]}
        for proof in after.output_tree.files:
            if Path(proof.relative_path).stem.casefold() in absent and Path(proof.relative_path).suffix.casefold() in {".bnk", ".rbnk"}:
                failures.append(f"unrequested SoundBank was generated: {proof.relative_path}")
        info_names, info_text, info_records = _read_soundbanks_info(self.plan.io_root)
        expected_names = {
            str(value).casefold() for value in self.plan.asset_spec["request"]["banks"]
        }
        if not expected_names.issubset(info_names):
            failures.append("SoundbanksInfo does not identify every requested Bank")
        event_names = {
            str(event["name"]).casefold()
            for bank in self.plan.asset_spec["fixture_manifest"]["soundbanks"]
            for event in bank["events"]
        }
        if event_names and not all(name in info_text for name in event_names):
            failures.append("SoundbanksInfo does not prove every fixture Event")
        failures.extend(_localized_soundbanks_info_failures(self.plan.asset_spec, info_records))
        rebuild_seeds = _generate_rebuild_seed_paths(
            self.plan.asset_spec,
            self.root_bindings,
        )
        if rebuild_seeds is not None:
            cache_seed, header_seed = rebuild_seeds
            cache_relative = cache_seed.relative_to(self.plan.io_root).as_posix()
            header_relative = header_seed.relative_to(self.plan.io_root).as_posix()
            after_files = after.output_tree.by_relative_path()
            if cache_relative not in before_files or cache_relative in after_files:
                failures.append("stale audio-cache marker was not proven cleared")
            old_header = before_files.get(header_relative)
            new_header = after_files.get(header_relative)
            if (
                old_header is None
                or new_header is None
                or new_header.size <= 0
                or old_header.sha256 == new_header.sha256
            ):
                failures.append("project header was not proven rebuilt from its stale seed")
            actual_headers = {
                proof.relative_path
                for proof in after.output_tree.files
                if Path(proof.relative_path).name.casefold() == "wwise_ids.h"
            }
            if actual_headers != {header_relative}:
                failures.append("project header location is not exact")
        return tuple(failures)

    def _verify_tab(
        self,
        after: CliRuntimeSnapshot,
        backend: CliRuntimeBackend | None,
    ) -> tuple[str, ...]:
        failures: list[str] = []
        if backend is None or self._tab_before_by_path is None or self._control_before is None:
            return ("tab-delimited oracle state is missing",)
        if after.project_tree == self.before.project_tree:
            failures.append("tabDelimitedImport did not change the project tree")
        post_by_path = {item.path: item for item in after.objects}
        wav_by_key = _tab_wav_paths(self)
        for row in self.plan.asset_spec["expected"]["objects"]:
            path = str(row["path"])
            post = post_by_path.get(path)
            if post is None:
                failures.append(f"imported object is absent: {path}")
                continue
            if not _types_equivalent(post.object_type, str(row["type"])):
                failures.append(f"imported object type mismatch: {path}")
            expected_language = _canonical_language(str(row["language"]))
            if not _language_matches(post.language, expected_language):
                failures.append(f"imported object language mismatch: {path}")
            expected_sha = _file_sha256(wav_by_key[str(row["source_key"])])
            if post.source_sha256 != expected_sha:
                failures.append(f"imported source binding mismatch: {path}")
            old = self._tab_before_by_path[path]
            policy = str(row["guid_policy"])
            if policy == "preserved" and (old is None or old.object_id != post.object_id):
                failures.append(f"preserved object GUID changed: {path}")
            if policy == "replaced" and (old is None or old.object_id == post.object_id):
                failures.append(f"replaced object GUID was not replaced: {path}")
            if policy == "new_unique" and old is not None:
                failures.append(f"new object unexpectedly existed before import: {path}")
            event_name = row.get("event")
            if event_name:
                event_path = rf"\Events\Default Work Unit\{event_name}"
                event = backend.read_event(event_path)
                if event is None or event.action_types != (1,) or event.target_ids != (post.object_id,):
                    failures.append(f"created Play Event/Action binding mismatch: {event_path}")
        for path, old in self._control_before.items():
            current: CliObjectRecord | CliEventRecord | None
            if isinstance(old, CliEventRecord):
                current = backend.read_event(path)
            else:
                current = backend.read_object(path)
            if current != old:
                failures.append(f"tab import control object changed: {path}")
        xml_files = tuple(
            item for item in after.project_tree.files if item.relative_path.casefold().endswith((".wwu", ".wproj"))
        )
        if not xml_files:
            failures.append("tab import produced no readable Wwise XML evidence")
        return tuple(failures)

    def _verify_migration(
        self,
        before: CliRuntimeSnapshot,
        after: CliRuntimeSnapshot,
    ) -> tuple[str, ...]:
        failures: list[str] = []
        if after.project_tree == before.project_tree:
            failures.append("migrate did not change the case-owned project copy")
        if after.project_version is None or not after.project_version.startswith("v2022.1"):
            failures.append("migrated project does not declare Wwise 2022.1")
        if after.migration_inventory != before.migration_inventory:
            failures.append("selected migration identity/property/reference inventory drifted")
        # A migration backup is permitted only below the case-owned project root.
        for path in self.plan.project_root.rglob("*"):
            if path.is_symlink():
                failures.append("migration output contains a symlink")
                break
        return tuple(failures)


def build_cli_runtime_plan(
    scenario: OnlineScenario,
    *,
    version: str,
    case_root: Path,
    project_path: Path,
    source_template_root: Path | None = None,
) -> CliRuntimePlan:
    """Build one closed plan from an approved v3 CLI scenario."""

    try:
        operation = CLI_APIS[scenario.api]
    except KeyError as exc:
        raise CliRuntimeError(f"unsupported heavy CLI API: {scenario.api}") from exc
    if version != SUPPORTED_VERSION or version not in scenario.versions:
        raise CliRuntimeError(f"{scenario.id} is not runnable in Wwise {version}")
    if scenario.protocol != "preview_confirm" or scenario.primary_dispatch.count != 1:
        raise CliRuntimeError("heavy CLI scenarios require one previewed primary dispatch")
    spec = scenario.fixture.get("asset_spec")
    if not isinstance(spec, Mapping) or spec.get("operation") != operation:
        raise CliRuntimeError("scenario lacks its reviewed CLI asset specification")
    root = Path(case_root).expanduser().resolve(strict=False)
    project = Path(project_path).expanduser().resolve(strict=False)
    if root == project or root not in project.parents or project.suffix.casefold() != ".wproj":
        raise CliRuntimeError("CLI project must be an absolute case-owned .wproj")
    project_root = project.parent
    business_server_project = root / "business-host" / project.name
    if business_server_project == project:
        raise CliRuntimeError("CLI business control project must differ from target")
    asset_root = root / "cli-assets"
    io_root = root / "cli-io"
    if operation == "migrate":
        source = MIGRATION_SOURCE_ROOT.resolve(strict=True)
        if source_template_root is not None and Path(source_template_root).resolve(strict=True) != source:
            raise CliRuntimeError("migration source must be the sealed 2021.1 fixture")
        if project.exists() or project_root.exists():
            raise CliRuntimeError("migration destination project tree must not already exist")
    else:
        if not project.is_file() or project.is_symlink():
            raise CliRuntimeError("non-migration CLI project copy must already exist")
        if source_template_root is None:
            raise CliRuntimeError("non-migration CLI plan requires its immutable source template")
        source = Path(source_template_root).expanduser().resolve(strict=True)
        if not source.is_dir() or source == project_root:
            raise CliRuntimeError("CLI source template must be a separate directory")
    for path in (root, project_root if project_root.exists() else root):
        _reject_symlink_ancestors(path, stop=root.parent)
    return CliRuntimePlan(
        scenario=scenario,
        version=version,
        operation=operation,
        case_root=root,
        project_path=project,
        project_root=project_root,
        business_server_project_path=business_server_project,
        source_template_root=source,
        asset_root=asset_root,
        io_root=io_root,
        asset_spec=MappingProxyType(dict(spec)),
    )


def materialize_cli_runtime(plan: CliRuntimePlan) -> PreparedCliRuntime:
    """Write deterministic static assets and the migration project copy."""

    plan.case_root.mkdir(parents=True, exist_ok=True)
    if plan.asset_root.exists() or plan.io_root.exists():
        raise CliRuntimeError("CLI asset/output roots already exist and cannot be reused")
    if plan.operation == "migrate":
        _verify_migration_source_manifest(plan.source_template_root)
        shutil.copytree(plan.source_template_root, plan.project_root, symlinks=False)
        if plan.project_path != plan.project_root / "SampleProject.wproj":
            raise CliRuntimeError("migration destination project name must remain SampleProject.wproj")
    plan.asset_root.mkdir(parents=True, exist_ok=False)
    plan.io_root.mkdir(parents=True, exist_ok=False)
    root_bindings: dict[str, Path] = {}
    visible: dict[str, str] = {"project_path": str(plan.project_path)}
    expected_outputs: tuple[ExpectedOutput, ...] = ()
    controls: tuple[Path, ...] = ()
    if plan.operation == "convertExternalSource":
        root_bindings, visible, expected_outputs, controls = _materialize_convert(plan)
    elif plan.operation == "generateSoundbank":
        root_bindings, visible, expected_outputs = _materialize_generate(plan)
    elif plan.operation == "tabDelimitedImport":
        root_bindings, visible = _materialize_tab(plan)
    elif plan.operation == "migrate":
        root_bindings = {"case_root": plan.case_root}
    else:  # pragma: no cover
        raise CliRuntimeError("unknown CLI operation")
    prepared = PreparedCliRuntime(
        plan=plan,
        root_bindings=MappingProxyType(root_bindings),
        visible_values=MappingProxyType(visible),
        input_proofs=_collect_input_proofs(plan.asset_root),
        expected_outputs=expected_outputs,
        control_output_paths=controls,
        _gateway_args=None,
    )
    if not (plan.operation == "generateSoundbank" and plan.asset_spec["assets"]["definition_files"]):
        prepared._gateway_args = _gateway_args_for_materialized(prepared)
    return prepared


def all_cli_scenarios(scenarios: Sequence[OnlineScenario]) -> tuple[OnlineScenario, ...]:
    result = tuple(case for case in scenarios if case.api in CLI_APIS)
    counts = Counter(case.api for case in result)
    if len(result) != EXPECTED_CLI_SCENARIO_COUNT or counts != Counter(
        {api: 5 for api in CLI_APIS}
    ):
        raise CliRuntimeError(f"heavy CLI scenario set drifted: {counts}")
    return result


def _materialize_convert(
    plan: CliRuntimePlan,
) -> tuple[dict[str, Path], dict[str, str], tuple[ExpectedOutput, ...], tuple[Path, ...]]:
    spec = plan.asset_spec
    wav_root = plan.asset_root / "wav"
    manifest_root = plan.asset_root / "manifests"
    wav_root.mkdir()
    manifest_root.mkdir()
    wav_by_name: dict[str, Path] = {}
    for row in spec["assets"]["wav"]["files"]:
        path = _contained_file(wav_root, str(row["name"]))
        _write_pcm_wav(path, duration_ms=int(row["duration_ms"]), frequency_hz=int(row["frequency_hz"]))
        wav_by_name[str(row["name"]).replace("\\", "/")] = path
    manifests: dict[str, Path] = {}
    relative_wav_root = os.path.relpath(wav_root, start=plan.project_root)
    if (plan.project_root / relative_wav_root).resolve() != wav_root.resolve():
        raise CliRuntimeError("External Source relative Root did not resolve to the sealed WAV root")
    wire_wav_root = relative_wav_root.replace("/", "\\")
    for document in spec["assets"]["wsources"]:
        name = str(document["name"])
        path = _contained_file(manifest_root, name)
        root = ET.Element(
            "ExternalSourcesList",
            {"SchemaVersion": "1", "Root": wire_wav_root},
        )
        for row in document["entries"]:
            source = str(row["path"]).replace("\\", "/")
            if source not in wav_by_name:
                raise CliRuntimeError("External Source manifest references an unknown WAV")
            attrs = {"Path": source}
            if row.get("conversion") is not None:
                attrs["Conversion"] = str(row["conversion"])
            if row.get("destination") is not None:
                attrs["Destination"] = str(row["destination"])
            if row.get("analysis_types") is not None:
                attrs["AnalysisTypes"] = str(row["analysis_types"])
            ET.SubElement(root, "Source", attrs)
        ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
        manifests[name] = path
    request = spec["request"]
    root_bindings: dict[str, Path] = {}
    visible = {"project_path": str(plan.project_path)}
    for output in request["outputs"]:
        key = str(output["root_key"])
        if key in root_bindings:
            continue
        if len(request["outputs"]) == 1:
            path = plan.io_root / "output"
        else:
            path = plan.io_root / str(output["platform"]).casefold()
        path.mkdir(parents=True, exist_ok=False)
        root_bindings[key] = path
    for binding in request["bindings"]:
        for name in binding["manifests"]:
            if str(name) not in manifests:
                raise CliRuntimeError("request binding references an unknown manifest")
    manifest_names = [str(row["name"]) for row in spec["assets"]["wsources"]]
    if len(manifest_names) == 1:
        visible["source_list_path"] = str(manifests[manifest_names[0]])
    else:
        declared_inputs = {item.name for item in plan.scenario.visible_inputs}
        for name in manifest_names:
            bound_platforms = tuple(
                str(binding["platform"])
                for binding in request["bindings"]
                if name in {str(value) for value in binding["manifests"]}
            )
            candidates = [f"{Path(name).stem}_source_list"]
            if len(bound_platforms) == 1:
                candidates.append(f"{bound_platforms[0].casefold()}_source_list")
            prompt_keys = tuple(
                candidate for candidate in candidates if candidate in declared_inputs
            )
            if len(prompt_keys) != 1:
                raise CliRuntimeError(
                    "External Source manifest does not map to one closed visible input"
                )
            prompt_key = prompt_keys[0]
            visible[prompt_key] = str(manifests[name])
    if len(request["outputs"]) == 1:
        visible["output_directory"] = str(
            root_bindings[str(request["outputs"][0]["root_key"])]
        )
    else:
        for output in request["outputs"]:
            visible[f"{str(output['platform']).casefold()}_output_directory"] = str(
                root_bindings[str(output["root_key"])]
            )
    expected: list[ExpectedOutput] = []
    for row in spec["expected"]["outputs"]:
        output = next(
            value for value in request["outputs"] if value["platform"] == row["platform"]
        )
        destination = _contained_file(
            root_bindings[str(output["root_key"])],
            str(row["relative_path"]),
        )
        expected.append(
            ExpectedOutput(
                kind="external",
                path=destination,
                platform=str(row["platform"]),
                business_name=str(row["source_path"]),
                required_change=True,
            )
        )
    controls: list[Path] = []
    if plan.scenario.id == "O22-CLI-CONVERT-EXTERNAL-05":
        output_root = root_bindings["prepopulated_output"]
        for item in expected:
            _write_marker_riff(item.path, f"stale:{item.path.name}")
        control = output_root / "5199.wem"
        _write_marker_riff(control, "unrelated-control")
        controls.append(control)
    return root_bindings, visible, tuple(expected), tuple(controls)


def _materialize_generate(
    plan: CliRuntimePlan,
) -> tuple[dict[str, Path], dict[str, str], tuple[ExpectedOutput, ...]]:
    spec = plan.asset_spec
    request = spec["request"]
    wav_root = plan.asset_root / "wav"
    wav_root.mkdir()
    for bank in spec["fixture_manifest"]["soundbanks"]:
        for media in bank["media"]:
            path = _contained_file(wav_root, str(media["relative_wav"]))
            if path.exists():
                raise CliRuntimeError("duplicate SoundBank fixture WAV path")
            _write_pcm_wav(path, duration_ms=int(media["duration_ms"]), frequency_hz=int(media["frequency_hz"]))
    root_bindings: dict[str, Path] = {}
    visible = {"project_path": str(plan.project_path)}
    visible_output = plan.io_root / "output"
    visible_output.mkdir()
    root_bindings["output_directory"] = visible_output
    visible["output_directory"] = str(visible_output)
    bindings = request["path_bindings"]
    for key in bindings["fixture_owned_root_keys"]:
        key_text = str(key)
        if key_text == "case_cache_directory":
            path = visible_output / ".waapi-skill-cache"
            path.mkdir(parents=True, exist_ok=False)
        elif key_text == "case_root_output_directory":
            path = visible_output
        else:
            raise CliRuntimeError(
                f"unreviewed prompt-derived SoundBank root key: {key_text}"
            )
        root_bindings[key_text] = path
    for prompt_key, directory in (
        ("cache_directory", "cache"),
        ("root_output_directory", "root-output"),
    ):
        if any(
            str(binding["root_key"]) == prompt_key
            for binding in (bindings["cache"], bindings["root_output_path"])
        ):
            path = plan.io_root / directory
            path.mkdir(parents=True, exist_ok=False)
            root_bindings[prompt_key] = path
            visible[prompt_key] = str(path)
    for binding in bindings["soundbank_paths"]:
        root_bindings.setdefault(str(binding["root_key"]), visible_output)
        _resolve_binding(root_bindings, binding).mkdir(parents=True, exist_ok=True)
    bank_list = spec["assets"]["bank_list"]
    if bank_list is not None:
        path = _contained_file(plan.asset_root / "lists", str(bank_list["name"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(str(value) for value in bank_list["entries"]) + "\n", encoding="utf-8", newline="")
        root_bindings["bank_list_path"] = path
        visible["bank_list_path"] = str(path)
    definitions = spec["assets"]["definition_files"]
    if definitions:
        for definition, key in zip(
            definitions,
            ("ui_definition_file", "gameplay_definition_file"),
            strict=True,
        ):
            path = _contained_file(plan.asset_root / "definitions", str(definition["name"]))
            root_bindings[key] = path
            visible[key] = str(path)
    expected: list[ExpectedOutput] = []
    platform_outputs = {
        str(binding["platform"]): _resolve_binding(root_bindings, binding)
        for binding in bindings["soundbank_paths"]
    }
    for row in spec["expected"]["bank_artifacts"]:
        root = platform_outputs[str(row["platform"])]
        language = row["language"]
        relative = (
            PurePosixPath(str(language)) / f"{row['bank']}{row['extension']}"
            if language is not None
            else PurePosixPath(f"{row['bank']}{row['extension']}")
        )
        expected.append(
            ExpectedOutput(
                kind="bank",
                path=_contained_file(root, relative.as_posix()),
                platform=str(row["platform"]),
                business_name=str(row["bank"]),
                required_change=True,
            )
        )
    root_output = _resolve_binding(root_bindings, bindings["root_output_path"])
    rebuild_seeds = _generate_rebuild_seed_paths(spec, root_bindings)
    if rebuild_seeds is not None:
        cache_seed, header_seed = rebuild_seeds
        seed_spec = spec["fixture_manifest"]["rebuild_seeds"]
        _write_marker_riff(cache_seed, str(seed_spec["cache"]["marker"]))
        header_seed.parent.mkdir(parents=True, exist_ok=True)
        header_seed.write_text(
            str(seed_spec["header"]["marker"]) + "\n",
            encoding="utf-8",
            newline="",
        )
    for row in spec["expected"]["automatic_artifacts"]:
        if row["location"] == "platform_output":
            root = platform_outputs[str(row["platform"])]
        elif row["location"] == "root_output":
            root = root_output
        else:
            raise CliRuntimeError("unknown automatic artifact location")
        expected.append(
            ExpectedOutput(
                kind="automatic",
                path=_contained_file(root, str(row["name"])),
                platform=str(row["platform"]) if row["platform"] is not None else None,
                business_name=str(row["name"]),
                required_change=True,
            )
        )
    for stale in spec["fixture_manifest"]["preexisting_artifacts"]:
        match = next(
            item
            for item in expected
            if item.kind == "bank"
            and item.business_name == stale["soundbank"]
            and item.platform == stale["platform"]
        )
        _write_marker_bank(match.path, f"stale:{match.business_name}:{match.platform}")
    return root_bindings, visible, tuple(expected)


def _generate_rebuild_seed_paths(
    spec: Mapping[str, Any],
    root_bindings: Mapping[str, Path],
) -> tuple[Path, Path] | None:
    seeds = spec["fixture_manifest"].get("rebuild_seeds")
    if seeds is None:
        return None
    bindings = spec["request"]["path_bindings"]
    cache_root = _resolve_binding(root_bindings, bindings["cache"])
    header_root = _resolve_binding(root_bindings, bindings["root_output_path"])
    return (
        _contained_file(cache_root, str(seeds["cache"]["relative_path"])),
        _contained_file(header_root, str(seeds["header"]["relative_path"])),
    )


def _materialize_tab(
    plan: CliRuntimePlan,
) -> tuple[dict[str, Path], dict[str, str]]:
    spec = plan.asset_spec
    wav_root = plan.asset_root / "wav"
    prestate_root = plan.asset_root / "prestate"
    table_root = plan.asset_root / "tables"
    wav_root.mkdir()
    prestate_root.mkdir()
    table_root.mkdir()
    wav_by_key: dict[str, Path] = {}
    for row in spec["assets"]["wav"]["files"]:
        key = str(row["key"])
        path = _contained_file(wav_root, str(row["name"]))
        _write_pcm_wav(path, duration_ms=int(row["duration_ms"]), frequency_hz=int(row["frequency_hz"]))
        wav_by_key[key] = path
        prestate = _contained_file(prestate_root, f"{key}.wav")
        _write_pcm_wav(
            prestate,
            duration_ms=int(row["duration_ms"]) + 113,
            frequency_hz=int(row["frequency_hz"]) + 37,
        )
    table = spec["assets"]["tsv"]
    table_path = _contained_file(table_root, str(table["name"]))
    headers = tuple(str(value) for value in table["headers"])
    expected_by_path = {
        str(row["path"]): row for row in spec["expected"]["objects"]
    }
    with table_path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(headers)
        for row in table["rows"]:
            object_path = str(row["object_path"])
            expected_row = expected_by_path[object_path]
            import_language = _canonical_language(
                str(spec["request"]["import_language"])
            )
            localized_existing = (
                spec["request"]["import_operation"] == "useExisting"
                and import_language != "SFX"
                and expected_row["guid_policy"] in {"preserved", "replaced"}
            )
            wire_object_path = object_path
            if localized_existing:
                _, wire_object_path = _typed_existing_import_path(
                    object_path,
                    object_type=str(row["object_type"]),
                    language=import_language,
                )
            cells: list[str] = []
            for header in headers:
                if header == "Audio File":
                    cells.append(str(wav_by_key[str(row["source_key"])]))
                elif header == "Object Path":
                    cells.append(wire_object_path)
                elif header == "Object Type":
                    cells.append("" if localized_existing else str(row["object_type"]))
                elif header == "Event":
                    cells.append("" if localized_existing else str(row.get("event") or ""))
                elif header == "Notes":
                    cells.append("" if localized_existing else str(row.get("notes") or ""))
                else:
                    raise CliRuntimeError(f"unreviewed CLI TSV header: {header}")
            writer.writerow(cells)
    return (
        {"import_file": table_path},
        {"project_path": str(plan.project_path), "import_file": str(table_path)},
    )


def _gateway_args_for_materialized(runtime: PreparedCliRuntime) -> Mapping[str, Any]:
    plan = runtime.plan
    spec = plan.asset_spec
    request = spec["request"]
    args: dict[str, Any] = {"project": str(plan.project_path)}
    if plan.operation == "convertExternalSource":
        args["platform"] = list(request["platforms"])
        manifest_paths = {
            str(row["name"]): runtime.plan.asset_root / "manifests" / str(row["name"])
            for row in spec["assets"]["wsources"]
        }
        if request["source_mode"] == "source_file":
            names = tuple(str(value) for value in request["bindings"][0]["manifests"])
            args["source-file"] = _string_or_list(tuple(str(manifest_paths[name]) for name in names))
        else:
            pairs = tuple(
                (str(binding["platform"]), str(manifest_paths[str(name)]))
                for binding in request["bindings"]
                for name in binding["manifests"]
            )
            args["source-by-platform"] = _platform_pairs(pairs)
        output_pairs = tuple(
            (str(row["platform"]), str(runtime.root_bindings[str(row["root_key"])]))
            for row in request["outputs"]
        )
        output_mode = request["output_mode"]
        if output_mode == "platform_pair":
            if len(output_pairs) != 1:
                raise CliRuntimeError(
                    "convertExternalSource platform_pair requires exactly one output"
                )
        elif output_mode == "platform_pair_array":
            if len(output_pairs) < 2:
                raise CliRuntimeError(
                    "convertExternalSource platform_pair_array requires multiple outputs"
                )
        else:
            raise CliRuntimeError(
                "convertExternalSource output mapping mode is not reviewed"
            )
        # A scalar --output PATH makes Wwise append the platform directory.
        # These prompts expose each platform's final physical root, so even one
        # platform must use the reflected flat [PLATFORM, PATH] mapping shape.
        args["output"] = _platform_pairs(output_pairs)
    elif plan.operation == "generateSoundbank":
        if request["bank_selector"] == "absolute_utf8_list_file":
            args["bank"] = str(runtime.root_bindings["bank_list_path"])
        else:
            args["bank"] = _string_or_list(tuple(str(value) for value in request["banks"]))
        args["platform"] = list(request["platforms"])
        if request["languages"]:
            args["language"] = _string_or_list(tuple(str(value) for value in request["languages"]))
        if request["skip_languages"]:
            args["skip-languages"] = True
        if request["clear_audio_file_cache"]:
            args["clear-audio-file-cache"] = True
        if request["header_file"]:
            args["header-file"] = True
        if request["save"]:
            args["save"] = True
        if request["continue_on_error"]:
            args["continue-on-error"] = True
        bindings = request["path_bindings"]
        args["soundbank-path"] = _platform_pairs(
            tuple(
                (str(row["platform"]), str(_resolve_binding(runtime.root_bindings, row)))
                for row in bindings["soundbank_paths"]
            )
        )
        args["cache"] = str(_resolve_binding(runtime.root_bindings, bindings["cache"]))
        args["root-output-path"] = str(
            _resolve_binding(runtime.root_bindings, bindings["root_output_path"])
        )
        definitions = spec["assets"]["definition_files"]
        if definitions:
            args["import-definition-file"] = _string_or_list(
                tuple(str(runtime.root_bindings[key]) for key in ("ui_definition_file", "gameplay_definition_file"))
            )
    elif plan.operation == "tabDelimitedImport":
        args.update(
            {
                "tab-delimited-import-file": str(runtime.root_bindings["import_file"]),
                "tab-delimited-operation": str(request["import_operation"]),
                "import-language": _canonical_language(str(request["import_language"])),
            }
        )
        if request["audio_source_from_original"]:
            args["audio-source-from-original"] = True
        if request["continue_on_error"]:
            args["continue-on-error"] = True
    elif plan.operation == "migrate":
        if request["abort_on_load_issues"]:
            args["abort-on-load-issues"] = True
    forbidden = {
        "custom-global-closing-cmd",
        "custom-global-opening-cmd",
        "custom-post-gen-cmd",
        "custom-pre-gen-cmd",
    }
    if forbidden.intersection(args):
        raise CliRuntimeError("custom command field escaped the CLI builder")
    return MappingProxyType(args)


def _visible_values_for_materialized(runtime: PreparedCliRuntime) -> dict[str, str]:
    result = dict(runtime.visible_values)
    for key in ("ui_definition_file", "gameplay_definition_file"):
        if key in runtime.root_bindings:
            result[key] = str(runtime.root_bindings[key])
    expected = {item.name for item in runtime.plan.scenario.visible_inputs}
    if set(result) != expected:
        raise CliRuntimeError(
            f"visible prompt inputs do not match reviewed placeholders: "
            f"expected={sorted(expected)} actual={sorted(result)}"
        )
    return result


def _derive_public_cli_io_root(runtime: PreparedCliRuntime) -> Path:
    """Apply the documented product rule for an isolated CLI write root."""

    args = runtime._gateway_args
    if args is None:
        raise CliRuntimeError("CLI io_root cannot be derived before request materialization")
    operation = runtime.plan.operation
    if operation in {"tabDelimitedImport", "migrate"}:
        return runtime.plan.project_path.parent.resolve(strict=True)
    if operation == "convertExternalSource":
        roots = _cli_path_values(args.get("output"), field="output")
    elif operation == "generateSoundbank":
        roots = [
            *_cli_path_values(args.get("soundbank-path"), field="soundbank-path"),
            *_cli_path_values(args.get("cache"), field="cache"),
            *_cli_path_values(args.get("root-output-path"), field="root-output-path"),
        ]
    else:  # pragma: no cover - the plan closes the operation set.
        raise CliRuntimeError("unknown CLI io_root derivation")
    if not roots:
        raise CliRuntimeError("CLI isolated request has no explicit write root")
    common = Path(os.path.commonpath([str(path) for path in roots])).resolve(
        strict=True
    )
    if common == Path(common.anchor):
        raise CliRuntimeError(
            "CLI write roots have only the filesystem root as a common ancestor"
        )
    if any(common != path and common not in path.parents for path in roots):
        raise CliRuntimeError("CLI write-root common ancestor is inconsistent")
    return common


def _cli_path_values(value: Any, *, field: str) -> list[Path]:
    if isinstance(value, str):
        return [_resolve(value)]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if (
            len(value) == 2
            and isinstance(value[0], str)
            and isinstance(value[1], str)
        ):
            return [_resolve(value[1])]
        result: list[Path] = []
        for row in value:
            if (
                not isinstance(row, Sequence)
                or isinstance(row, (str, bytes, bytearray))
                or len(row) != 2
                or not isinstance(row[1], str)
            ):
                raise CliRuntimeError(f"CLI {field} path mapping is not closed")
            result.append(_resolve(row[1]))
        return result
    raise CliRuntimeError(f"CLI {field} path value is not closed")


def _public_cli_request_provenance(
    runtime: PreparedCliRuntime,
) -> dict[str, str]:
    args = runtime._gateway_args
    if args is None:  # pragma: no cover - caller checks first.
        raise CliRuntimeError("CLI request provenance lacks args")
    provenance = {
        "/contract": "fixed public operation-request/v1 contract",
        "/version": "connected/configured Wwise adapter version",
        "/operation": "catalog-declared waapi.call transaction route",
        "/arguments/api": "natural request selects the reflected ak.wwise.cli URI",
        "/arguments/options": "reflected CLI options schema is the fixed empty object",
        "/arguments/io_root": (
            "documented deterministic isolated-root rule; never a hidden case root"
        ),
    }
    prompt_fields: dict[str, str]
    if runtime.plan.operation == "convertExternalSource":
        prompt_fields = {
            "project": "natural prompt project_path",
            "platform": "natural prompt platform names",
            "source-file": "natural prompt shared .wsources path(s)",
            "source-by-platform": "natural prompt platform-to-.wsources bindings",
            "output": "natural prompt output root(s) and platform bindings",
        }
    elif runtime.plan.operation == "generateSoundbank":
        prompt_fields = {
            "project": "natural prompt project_path",
            "bank": "natural prompt Bank names or visible Bank-list path; Init is automatic",
            "platform": "natural prompt platform names",
            "language": "natural prompt explicit language names",
            "skip-languages": "natural prompt explicitly requests non-localized-only output",
            "clear-audio-file-cache": "natural prompt explicitly requests clearing the dedicated cache",
            "header-file": "natural prompt explicitly requests Wwise_IDs.h",
            "save": "natural prompt explicitly requests saving the project",
            "continue-on-error": "natural prompt explicitly requests continue-on-error",
            "soundbank-path": "documented output-root rule: one platform uses the root; multiple use root/platform",
            "cache": "visible dedicated cache or documented output/.waapi-skill-cache default",
            "root-output-path": "visible project-output root or documented output-root default",
            "import-definition-file": "natural prompt visible definition file path(s)",
        }
    elif runtime.plan.operation == "tabDelimitedImport":
        prompt_fields = {
            "project": "natural prompt project_path",
            "tab-delimited-import-file": "natural prompt import_file",
            "tab-delimited-operation": "natural prompt createNew/useExisting/replaceExisting intent",
            "import-language": "natural prompt explicit Wwise language",
            "audio-source-from-original": "natural prompt explicitly requests original-source mode",
            "continue-on-error": "natural prompt explicitly requests continue-on-error",
        }
    else:
        prompt_fields = {
            "project": "natural prompt project_path",
            "abort-on-load-issues": "natural prompt explicitly requests abort-on-load-issues",
        }
    unknown = sorted(set(args) - set(prompt_fields))
    if unknown:
        raise CliRuntimeError(
            "CLI request contains fields with no public prompt mapping: "
            + ", ".join(unknown)
        )
    for field in args:
        provenance[f"/arguments/args/{field}"] = prompt_fields[field]
    return provenance


def _dispatch_failures(
    plan: CliRuntimePlan,
    dispatch: CliDispatchEvidence,
    business: ProcessPhaseEvidence,
) -> tuple[str, ...]:
    failures: list[str] = []
    if dispatch.api != plan.scenario.api:
        failures.append("business dispatch used the wrong CLI URI")
    if dispatch.primary_dispatch_count != 1:
        failures.append("business CLI URI was not dispatched exactly once")
    if not dispatch.dispatch_started:
        failures.append("business CLI dispatch was not proven to start")
    if business.natural_exit_before_shutdown and not plan.business_disconnect_may_occur:
        failures.append("business WAAPI server exited unexpectedly before runner shutdown")
    if dispatch.connection_lost:
        if not plan.business_disconnect_may_occur:
            failures.append("unexpected WAAPI server disconnect")
        elif not dispatch.connection_lost_after_dispatch:
            failures.append("migration disconnect occurred before primary dispatch")
        if not business.natural_exit_before_shutdown:
            failures.append("migration disconnect was not a natural server exit")
        if business.runner_shutdown_requested:
            failures.append("runner shutdown cannot prove a migration disconnect")
        if not business.process_exited:
            failures.append("migration disconnect lacks final server exit proof")
        if business.returncode not in {0, 2}:
            failures.append("migration server exit code is not successful/warnings-only")
        if dispatch.process_result != 0 and not _is_reviewed_2022_warnings_only_result(
            version=plan.version,
            api=plan.scenario.api,
            process_result=dispatch.process_result,
        ):
            failures.append("CLI process result is neither success nor reviewed warnings-only")
    else:
        if not dispatch.dispatch_completed:
            failures.append("business CLI dispatch completion is ambiguous")
        if dispatch.process_result != 0 and not _is_reviewed_2022_warnings_only_result(
            version=plan.version,
            api=plan.scenario.api,
            process_result=dispatch.process_result,
        ):
            failures.append("CLI process result is neither success nor reviewed warnings-only")
        verified_states = {
            "verified",
            "verification_complete",
            "result_schema_checked",
        }
        terminal_migration_states = {"executed_unverified", "indeterminate"}
        if plan.operation == "migrate":
            verified_states.update(terminal_migration_states)
        if dispatch.gateway_verify_state not in verified_states:
            failures.append("generic transaction result-schema verification is not terminal")
    logs = dispatch.stdout + "\n" + dispatch.stderr
    if len(logs.encode("utf-8", errors="replace")) > MAX_LOG_BYTES:
        failures.append("CLI process log exceeded the bounded evidence ceiling")
    if _FATAL_RE.search(logs):
        failures.append("CLI process log contains fatal or unresolved-reference evidence")
    if dispatch.unclassified_load_issues:
        failures.append("CLI process retained unclassified project load issues")
    return tuple(failures)


def _is_reviewed_2022_warnings_only_result(
    *,
    version: str,
    api: str,
    process_result: int | None,
) -> bool:
    """Recognize the exact Wwise 2022.1 ``processResultCli`` warning value.

    Wwise 2022.1's shipped ``WwiseAuthoringAPI.json`` defines 0 as success,
    1 as at least one error, and 2 as warnings only.  Keep that meaning closed
    to the four reviewed 2022.1 CLI URIs; the surrounding business oracle must
    still pass before a scenario can pass.
    """

    return (
        version == SUPPORTED_VERSION
        and api in REVIEWED_2022_PROCESS_RESULT_URIS
        and process_result == 2
    )


def _tree_matches_with_allowed_additions(
    before: TreeProof,
    after: TreeProof,
    *,
    allowed_additions: frozenset[str],
) -> bool:
    if before.root != after.root:
        return False
    before_files = before.by_relative_path()
    after_files = after.by_relative_path()
    if len(before_files) != len(before.files) or len(after_files) != len(after.files):
        return False
    if any(after_files.get(relative) != proof for relative, proof in before_files.items()):
        return False
    additions = frozenset(after_files) - frozenset(before_files)
    return additions.issubset(allowed_additions)


def _convert_asset_tree_is_closed(before: TreeProof, after: TreeProof) -> bool:
    """Allow only Wwise 2022.1 analysis files bound to sealed WAV siblings."""

    before_files = before.by_relative_path()
    allowed = frozenset(
        PurePosixPath(relative).with_suffix(".akd").as_posix()
        for relative in before_files
        if PurePosixPath(relative).suffix.casefold() == ".wav"
    )
    if not _tree_matches_with_allowed_additions(
        before,
        after,
        allowed_additions=allowed,
    ):
        return False
    additions = frozenset(after.by_relative_path()) - frozenset(before_files)
    for relative in additions:
        proof = after.by_relative_path()[relative]
        try:
            data = Path(proof.path).read_bytes()
        except OSError:
            return False
        if proof.size < 24 or len(data) != proof.size or data[:4] != b"\r\x00\x00\x00":
            return False
    return True


def _convert_project_tree_is_closed(
    before: TreeProof,
    after: TreeProof,
    *,
    project_path: Path,
) -> bool:
    """Allow only the two sealed Wwise/Wine project-load artifacts."""

    settings_relative = f"{project_path.stem}.crossover.wsettings"
    allowed = frozenset({".cache/CacheVersion", settings_relative})
    if not _tree_matches_with_allowed_additions(
        before,
        after,
        allowed_additions=allowed,
    ):
        return False
    before_files = before.by_relative_path()
    after_files = after.by_relative_path()
    additions = frozenset(after_files) - frozenset(before_files)
    cache = after_files.get(".cache/CacheVersion") if ".cache/CacheVersion" in additions else None
    if cache is not None:
        try:
            cache_bytes = Path(cache.path).read_bytes()
        except OSError:
            return False
        if cache.size != 4 or cache_bytes != b"F\x00\x00\x00":
            return False
    settings = after_files.get(settings_relative) if settings_relative in additions else None
    if settings is not None:
        try:
            root = ET.parse(settings.path).getroot()
        except (OSError, ET.ParseError):
            return False
        if (
            root.tag != "WwiseDocument"
            or root.attrib.get("Type") != "UserProjectSettings"
        ):
            return False
    return True


def _phase_spec(
    role: ProcessRole,
    console: Path,
    port: int | None,
    *,
    project_path: Path | None,
    cwd: Path,
    read_only_oracle: bool = False,
) -> ProcessPhaseSpec:
    if port is None:
        raise CliRuntimeError(f"{role} port is required")
    argv = tuple(
        build_wwise_console_command(
            console,
            port,
            project_path=project_path,
            extra_args=(),
        )
    )
    expected = (
        str(console),
        "waapi-server",
        *((str(project_path),) if project_path is not None else ()),
        "--wamp-port",
        str(port),
        "--http-port",
        "0",
    )
    if argv != expected:
        raise CliRuntimeError("WwiseConsole command builder drifted from the closed argv")
    return ProcessPhaseSpec(
        role=role,
        argv=argv,
        cwd=str(cwd),
        project_path=str(project_path) if project_path is not None else None,
        required=True,
        read_only_oracle=read_only_oracle,
    )


def _assert_backend_context(
    value: Mapping[str, Any],
    *,
    version: str,
    project_path: Path,
) -> None:
    if not isinstance(value, Mapping):
        raise CliRuntimeError("backend context must be an object")
    info = value.get("info", value)
    project = value.get("project", value)
    if not isinstance(info, Mapping) or not isinstance(project, Mapping):
        raise CliRuntimeError("backend context lacks info/project objects")
    version_row = info.get("version")
    if isinstance(version_row, Mapping):
        # Real Wwise getInfo uses ``year`` for the product generation and
        # ``major`` for its first release component (for example
        # year=2022, major=1, minor=19).  Keep the reflected/fake legacy shape
        # (major=2022, minor=1) readable as well.
        year = version_row.get("year")
        major = version_row.get("major")
        minor = version_row.get("minor")
        observed_version = (
            f"{year}.{major}"
            if isinstance(year, int)
            and not isinstance(year, bool)
            and isinstance(major, int)
            and not isinstance(major, bool)
            else f"{major}.{minor}"
        )
    else:
        observed_version = str(info.get("version") or info.get("wwiseVersion") or "")
    if observed_version != version and not observed_version.startswith(version + "."):
        raise CliRuntimeError(f"oracle/setup backend uses wrong Wwise version: {observed_version}")
    observed_path = _first_text(project, "path", "projectPath", "project")
    if observed_path is None:
        raise CliRuntimeError("oracle/setup backend context lacks a usable project path")
    if _localize_waapi_host_path(
        observed_path,
        field="backend project path",
    ).resolve(strict=False) != project_path.resolve(strict=False):
        raise CliRuntimeError("oracle/setup backend opened the wrong project")


def _migration_inventory(root: Path, spec: Mapping[str, Any]) -> tuple[AnchorInventory, ...]:
    assets = spec["assets"]
    profile = str(assets["profile"])
    scoped = spec["expected"].get("comparison_scope")
    result: list[AnchorInventory] = []
    for anchor in assets["anchors"]:
        source = _contained_existing_file(root, str(anchor["source_file"]))
        source_tree = _safe_xml(source)
        parent_map = {child: parent for parent in source_tree.iter() for child in parent}
        matches = [
            element
            for element in source_tree.iter()
            if element.tag == anchor["kind"]
            and element.attrib.get("ID") == anchor["guid"]
            and element.attrib.get("Name") == anchor["name"]
        ]
        if len(matches) != 1:
            raise CliRuntimeError("migration anchor did not resolve exactly once")
        node = matches[0]
        parent = parent_map.get(node)
        parent_identity = (
            (
                parent.tag,
                str(parent.attrib.get("Name") or ""),
                str(parent.attrib.get("ID") or ""),
            )
            if parent is not None
            else None
        )
        required_tags = set(str(value) for value in anchor["required_descendant_tags"])
        if profile == "project_platform_conversion_binding_graph" and scoped:
            selected = _scoped_migration_elements(
                node,
                parent_map,
                scoped,
            )
            semantic_rows = tuple(
                _semantic_element_row(element, index)
                for index, element in enumerate(selected)
            )
        else:
            selected = tuple(
                element
                for element in node.iter()
                if element is node
                or element.tag in required_tags
                or element.tag == "Property"
                or element.tag.endswith("Ref")
            )
            semantic_rows = tuple(
                _semantic_element_row(element, index)
                for index, element in enumerate(selected)
            )
        required_refs = set(str(value) for value in anchor["required_reference_names"])
        reference_rows: list[tuple[Any, ...]] = []
        for relative in anchor["scope_files"]:
            document = _safe_xml(_contained_existing_file(root, str(relative)))
            document_parent_map = {
                child: parent for parent in document.iter() for child in parent
            }
            for element in document.iter():
                if element.tag.endswith("Ref") and element.attrib.get("Name") in required_refs:
                    graph = (
                        _rtpc_graph_signature(element, document_parent_map)
                        if profile == "car_engine_rtpc_curve_graph"
                        else None
                    )
                    if graph is None:
                        reference_rows.append(
                            (
                                str(relative),
                                "reference",
                                *_semantic_element_signature(element),
                            )
                        )
                    else:
                        reference_rows.append(
                            (str(relative), "rtpc_graph", graph)
                        )
        result.append(
            AnchorInventory(
                key=f"{anchor['kind']}|{anchor['guid']}",
                identity=(
                    str(node.tag),
                    str(node.attrib.get("Name") or ""),
                    str(node.attrib.get("ID") or ""),
                    parent_identity,
                ),
                semantic_rows=semantic_rows,
                reference_rows=tuple(sorted(reference_rows)),
            )
        )
    return tuple(result)


def _scoped_migration_elements(
    node: ET.Element,
    parent_map: Mapping[ET.Element, ET.Element],
    scoped: Mapping[str, Any],
) -> tuple[ET.Element, ...]:
    allowed_properties = set(
        str(value)
        for value in (
            scoped["project_property_names"]
            if node.tag == "Project"
            else scoped["conversion_property_names"]
        )
    )
    project_tags = (
        set(str(value) for value in scoped["project_descendant_tags"])
        if node.tag == "Project"
        else set()
    )
    include_plugins = bool(scoped["include_conversion_plugin_inventory"])
    selected: list[ET.Element] = []
    for element in node.iter():
        if element.tag in project_tags:
            selected.append(element)
            continue
        if element.tag == "Property":
            if element.attrib.get("Name") in allowed_properties:
                selected.append(element)
            continue
        if element.tag == "Value":
            ancestor = parent_map.get(element)
            while ancestor is not None and ancestor is not node:
                if ancestor.tag == "Property":
                    if ancestor.attrib.get("Name") in allowed_properties:
                        selected.append(element)
                    break
                ancestor = parent_map.get(ancestor)
            continue
        if (
            node.tag == "Conversion"
            and include_plugins
            and element.tag in {"ConversionPluginInfo", "ConversionPlugin"}
        ):
            selected.append(element)
    return tuple(selected)


def _rtpc_graph_signature(
    reference: ET.Element,
    parent_map: Mapping[ET.Element, ET.Element],
) -> tuple[Any, ...] | None:
    rtpc = reference
    while rtpc.tag != "RTPC":
        parent = parent_map.get(rtpc)
        if parent is None:
            return None
        rtpc = parent
    legacy_properties: list[ET.Element] = []
    ancestor = parent_map.get(rtpc)
    while ancestor is not None:
        if ancestor.tag == "Property":
            legacy_properties.append(ancestor)
        if ancestor.attrib.get("ID"):
            break
        ancestor = parent_map.get(ancestor)
    if len(legacy_properties) > 1:
        raise CliRuntimeError("RTPC graph has ambiguous legacy controlled Properties")

    property_name_rows = tuple(
        element
        for element in rtpc.iter("Property")
        if element.attrib.get("Name") == "PropertyName"
    )
    if len(property_name_rows) > 1:
        raise CliRuntimeError("RTPC graph has ambiguous serialized PropertyName rows")
    legacy_name = (
        str(legacy_properties[0].attrib.get("Name") or "")
        if legacy_properties
        else ""
    )
    serialized_name = (
        str(property_name_rows[0].attrib.get("Value") or "")
        if property_name_rows
        else ""
    )
    if legacy_name and serialized_name and legacy_name != serialized_name:
        raise CliRuntimeError("RTPC graph controlled Property representations disagree")
    controlled_property_name = legacy_name or serialized_name
    if not controlled_property_name:
        raise CliRuntimeError("RTPC graph lacks its controlled Property")

    owner = parent_map.get(rtpc)
    while owner is not None and not owner.attrib.get("ID"):
        owner = parent_map.get(owner)
    if owner is None:
        raise CliRuntimeError("RTPC graph lacks its authored object owner")

    control_references = tuple(
        element
        for element in rtpc.iter()
        if element.tag.endswith("Ref")
        and _has_named_reference_ancestor(
            element,
            rtpc=rtpc,
            parent_map=parent_map,
            reference_name="ControlInput",
        )
    )
    if len(control_references) != 1 or control_references[0] is not reference:
        raise CliRuntimeError("RTPC graph lacks one exact ControlInput reference")

    curves = tuple(rtpc.iter("Curve"))
    if not curves:
        raise CliRuntimeError("RTPC graph lacks its Curve")
    return (
        (
            "owner",
            str(owner.tag),
            str(owner.attrib.get("Name") or ""),
            str(owner.attrib.get("ID") or ""),
        ),
        ("controlled_property", controlled_property_name),
        ("control_input", *_semantic_element_signature(reference)),
        (
            "rtpc",
            *_semantic_element_signature(rtpc),
        ),
        ("curves", tuple(_normalized_curve_signature(curve) for curve in curves)),
    )


def _has_named_reference_ancestor(
    element: ET.Element,
    *,
    rtpc: ET.Element,
    parent_map: Mapping[ET.Element, ET.Element],
    reference_name: str,
) -> bool:
    ancestor = parent_map.get(element)
    while ancestor is not None and ancestor is not rtpc:
        if (
            ancestor.tag == "Reference"
            and ancestor.attrib.get("Name") == reference_name
        ):
            return True
        ancestor = parent_map.get(ancestor)
    return False


def _normalized_curve_signature(curve: ET.Element) -> tuple[Any, ...]:
    flags_properties = tuple(
        element
        for element in curve.iter("Property")
        if element.attrib.get("Name") == "Flags"
    )
    if len(flags_properties) != 1:
        raise CliRuntimeError("RTPC Curve lacks one exact Flags Property")
    points: list[tuple[tuple[str, str], ...]] = []
    for point in curve.iter("Point"):
        children = tuple(point)
        tags = tuple(child.tag for child in children)
        if tags not in {
            ("XPos", "YPos", "Flags"),
            ("XPos", "YPos", "Flags", "SegmentShape"),
        }:
            raise CliRuntimeError("RTPC Curve Point shape is not closed")
        values = tuple(" ".join((child.text or "").split()) for child in children)
        if any(not value for value in values):
            raise CliRuntimeError("RTPC Curve Point contains an empty value")
        points.append(tuple(zip(tags, values, strict=True)))
    if not points:
        raise CliRuntimeError("RTPC Curve lacks points")
    return (
        *_semantic_element_signature(curve),
        ("flags", *_semantic_element_signature(flags_properties[0])),
        ("points", tuple(points)),
    )


def _semantic_element_row(element: ET.Element, index: int) -> tuple[Any, ...]:
    return (index, *_semantic_element_signature(element))


def _semantic_element_signature(element: ET.Element) -> tuple[Any, ...]:
    attrs = tuple(
        sorted(
            (str(key), str(value))
            for key, value in element.attrib.items()
            if key not in {"WwiseVersion", "WwiseBuild", "SchemaVersion"}
        )
    )
    text = " ".join((element.text or "").split())
    values = tuple(
        " ".join((child.text or "").split())
        for child in element
        if child.tag == "Value"
    )
    return (str(element.tag), attrs, text, values)


def _verify_migration_source_manifest(root: Path) -> None:
    manifest_path = root / "fixture-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("algorithm") != "sha256" or manifest.get("file_count") != 66:
        raise CliRuntimeError("sealed migration fixture manifest shape drifted")
    rows = manifest.get("files")
    if not isinstance(rows, list) or len(rows) != 66:
        raise CliRuntimeError("sealed migration fixture file inventory drifted")
    aggregate = hashlib.sha256()
    actual_paths: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise CliRuntimeError("migration manifest row is not an object")
        relative = str(row.get("path") or "")
        path = _contained_existing_file(root, relative)
        digest = _file_sha256(path)
        if row.get("bytes") != path.stat().st_size or row.get("sha256") != digest:
            raise CliRuntimeError("migration source payload does not match sealed manifest")
        actual_paths.append(relative)
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(digest.encode("ascii"))
        aggregate.update(b"\0")
    if aggregate.hexdigest() != "51b1d8abfee6c296e184446a89069c011db56e50c50463f5f9036c37766fde4d":
        raise CliRuntimeError("migration fixture aggregate digest drifted")
    if len(set(actual_paths)) != len(actual_paths):
        raise CliRuntimeError("migration fixture manifest contains duplicate paths")
    metadata_path = root / "fixture-metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    hash_strategy = metadata.get("hash_strategy")
    if not isinstance(hash_strategy, Mapping) or hash_strategy.get(
        "manifest_digest"
    ) != aggregate.hexdigest() or hash_strategy.get("file_count") != len(actual_paths):
        raise CliRuntimeError("migration fixture metadata does not bind the manifest")
    observed_files: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise CliRuntimeError("sealed migration fixture contains a symlink")
        if path.is_file():
            observed_files.add(path.relative_to(root).as_posix())
    expected_files = set(actual_paths) | {
        "fixture-manifest.json",
        "fixture-metadata.json",
    }
    if observed_files != expected_files:
        raise CliRuntimeError("sealed migration fixture contains unreviewed files")


def _tree_proof(root: Path) -> TreeProof:
    resolved = root.resolve(strict=True)
    if not resolved.is_dir() or resolved.is_symlink():
        raise CliRuntimeError(f"tree proof root is not a regular directory: {resolved}")
    files: list[FileProof] = []
    for path in sorted(resolved.rglob("*"), key=lambda value: value.relative_to(resolved).as_posix()):
        if path.is_symlink():
            raise CliRuntimeError(f"tree proof contains a symlink: {path}")
        if not path.is_file():
            continue
        if len(files) >= MAX_TREE_FILES:
            raise CliRuntimeError("tree proof exceeded its file-count ceiling")
        stat = path.stat()
        if stat.st_size > MAX_FILE_BYTES:
            raise CliRuntimeError("tree proof contains an oversized file")
        files.append(
            FileProof(
                path=str(path),
                relative_path=path.relative_to(resolved).as_posix(),
                size=stat.st_size,
                sha256=_file_sha256(path),
                mtime_ns=stat.st_mtime_ns,
            )
        )
    digest = hashlib.sha256()
    for item in files:
        digest.update(item.relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(item.size).encode("ascii"))
        digest.update(b"\0")
        digest.update(item.sha256.encode("ascii"))
        digest.update(b"\0")
    return TreeProof(root=str(resolved), files=tuple(files), sha256=digest.hexdigest())


def _authored_project_projection(
    tree: TreeProof,
) -> tuple[tuple[str, int, str], ...]:
    """Return the project content that Wwise ``save=false`` must preserve.

    WwiseConsole may create analysis data and local caches while generating a
    SoundBank even when it does not save authored project data.  Keep the full
    ``TreeProof`` in campaign evidence, but exclude only the closed set of
    generated paths already excluded by the committed fixture policy when
    deciding whether authored content changed.  Modification times are not
    authored content and therefore are intentionally absent from this
    projection.
    """

    rows: list[tuple[str, int, str]] = []
    for item in tree.files:
        if _is_generated_project_relative_path(item.relative_path):
            continue
        rows.append((item.relative_path, item.size, item.sha256))
    return tuple(rows)


def authored_project_archive_projection(
    tree: Mapping[str, Any],
) -> tuple[tuple[str, int, str], ...]:
    """Project the authored content from one validated JSON ``TreeProof``."""

    files = tree.get("files")
    if not isinstance(files, list):
        raise CliRuntimeError("archived project tree files must be an array")
    rows: list[tuple[str, int, str]] = []
    for item in files:
        if not isinstance(item, Mapping):
            raise CliRuntimeError("archived project tree file must be an object")
        relative_path = item.get("relative_path")
        size = item.get("size")
        sha256 = item.get("sha256")
        if (
            not isinstance(relative_path, str)
            or not relative_path
            or type(size) is not int
            or not isinstance(sha256, str)
        ):
            raise CliRuntimeError("archived project tree file is malformed")
        if _is_generated_project_relative_path(relative_path):
            continue
        rows.append((relative_path, size, sha256))
    return tuple(rows)


def _is_generated_project_relative_path(relative_path: str) -> bool:
    relative = PurePosixPath(relative_path)
    folded_parts = tuple(part.casefold() for part in relative.parts)
    return (
        any(
            part in _GENERATED_PROJECT_DIRECTORY_NAMES
            for part in folded_parts[:-1]
        )
        or relative.name.casefold() in _GENERATED_PROJECT_NAMES
        or relative.suffix.casefold() in _GENERATED_PROJECT_SUFFIXES
    )


def _collect_input_proofs(root: Path) -> tuple[FileProof, ...]:
    return _tree_proof(root).files


def _read_soundbanks_info(
    root: Path,
) -> tuple[set[str], str, tuple[SoundbanksInfoRecord, ...]]:
    candidates = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.name.casefold() in {"soundbanksinfo.xml", "soundbanksinfo.json"}
    )
    if not candidates:
        return set(), "", ()
    names: set[str] = set()
    text_parts: list[str] = []
    records: list[SoundbanksInfoRecord] = []
    for path in candidates:
        if path.stat().st_size > 16 * 1024 * 1024:
            raise CliRuntimeError("SoundbanksInfo evidence is oversized")
        text = path.read_text(encoding="utf-8")
        text_parts.append(text.casefold())
        if path.suffix.casefold() == ".json":
            payload = json.loads(text)
            for value in _walk_json(payload):
                if isinstance(value, str):
                    names.add(value.casefold())
        else:
            document = _safe_xml(path)
            for element in document.iter():
                if element.tag.casefold() in {"shortname", "name"} and element.text:
                    names.add(element.text.strip().casefold())
                for key in ("Name", "ShortName"):
                    if element.attrib.get(key):
                        names.add(str(element.attrib[key]).casefold())
            platform = _required_text(
                document.attrib.get("Platform"),
                "SoundbanksInfo Platform",
            )
            for bank in document.findall("./SoundBanks/SoundBank"):
                short_name = _required_xml_child_text(
                    bank,
                    "ShortName",
                    "SoundbanksInfo SoundBank ShortName",
                )
                language = _required_text(
                    bank.attrib.get("Language"),
                    "SoundbanksInfo SoundBank Language",
                )
                relative_path = _normalized_metadata_path(
                    _required_xml_child_text(
                        bank,
                        "Path",
                        "SoundbanksInfo SoundBank Path",
                    )
                )
                media: list[tuple[str, str]] = []
                for media_file in bank.findall("./Media/File"):
                    media.append(
                        (
                            _required_xml_child_text(
                                media_file,
                                "ShortName",
                                "SoundbanksInfo media ShortName",
                            ),
                            _required_text(
                                media_file.attrib.get("Language"),
                                "SoundbanksInfo media Language",
                            ),
                        )
                    )
                events = tuple(
                    sorted(
                        _required_text(
                            event.attrib.get("Name"),
                            "SoundbanksInfo Event Name",
                        )
                        for event in bank.findall("./Events/Event")
                    )
                )
                records.append(
                    SoundbanksInfoRecord(
                        platform=platform,
                        bank=short_name,
                        language=language,
                        relative_path=relative_path,
                        media=tuple(sorted(media)),
                        events=events,
                    )
                )
    return names, "\n".join(text_parts), tuple(records)


def _localized_soundbanks_info_failures(
    spec: Mapping[str, Any],
    records: Sequence[SoundbanksInfoRecord],
) -> tuple[str, ...]:
    localized_artifacts = tuple(
        row for row in spec["expected"]["bank_artifacts"] if row["language"] is not None
    )
    if not localized_artifacts:
        return ()

    requested_banks = {str(value) for value in spec["request"]["banks"]}
    expected_keys = {
        (
            str(row["platform"]),
            str(row["bank"]),
            _canonical_language(str(row["language"])),
        )
        for row in localized_artifacts
    }
    relevant_records = tuple(record for record in records if record.bank in requested_banks)
    actual_keys = {
        (record.platform, record.bank, record.language) for record in relevant_records
    }
    failures: list[str] = []
    if actual_keys != expected_keys or len(relevant_records) != len(actual_keys):
        failures.append(
            "SoundbanksInfo localized Bank/language manifest is not exact"
        )
        return tuple(failures)

    fixture_banks = {
        str(bank["name"]): bank for bank in spec["fixture_manifest"]["soundbanks"]
    }
    for record in relevant_records:
        key = (record.platform, record.bank, record.language)
        bank = fixture_banks[record.bank]
        expected_path = f"{record.language}/{record.bank}.bnk"
        if record.relative_path != expected_path:
            failures.append(
                f"SoundbanksInfo localized Bank path mismatch: {key!r}"
            )
        expected_media = {
            (
                PurePosixPath(str(media["relative_wav"])).name,
                _canonical_language(str(media["language"])),
            )
            for media in bank["media"]
            if _canonical_language(str(media["language"])) == record.language
        }
        if set(record.media) != expected_media or len(record.media) != len(expected_media):
            failures.append(
                f"SoundbanksInfo localized media manifest mismatch: {key!r}"
            )
        expected_events = {str(event["name"]) for event in bank["events"]}
        if set(record.events) != expected_events or len(record.events) != len(expected_events):
            failures.append(
                f"SoundbanksInfo localized Event manifest mismatch: {key!r}"
            )
    return tuple(failures)


def _required_xml_child_text(element: ET.Element, tag: str, field: str) -> str:
    child = element.find(tag)
    return _required_text(child.text if child is not None else None, field)


def _normalized_metadata_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise CliRuntimeError("SoundbanksInfo SoundBank Path is not a safe relative path")
    return path.as_posix()


def _walk_json(value: Any) -> Sequence[Any]:
    result: list[Any] = [value]
    if isinstance(value, Mapping):
        for child in value.values():
            result.extend(_walk_json(child))
    elif isinstance(value, list):
        for child in value:
            result.extend(_walk_json(child))
    return result


def _project_document_version(project: Path) -> str | None:
    try:
        root = _safe_xml(project)
    except (CliRuntimeError, FileNotFoundError):
        return None
    return root.attrib.get("WwiseVersion")


def _safe_xml(path: Path) -> ET.Element:
    data = path.read_bytes()
    if len(data) > MAX_FILE_BYTES or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper() or b"\x00" in data:
        raise CliRuntimeError(f"unsafe or oversized XML evidence: {path}")
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise CliRuntimeError(f"malformed XML evidence: {path}: {exc}") from exc


def _ensure_chain(
    backend: CliRuntimeBackend,
    target: str,
    *,
    root: str,
    object_type: str,
) -> None:
    target_path = _wwise_path(target)
    root_path = _wwise_path(root)
    if target_path == root_path:
        if backend.read_object(root_path) is None:
            raise CliRuntimeError(f"fixture root is absent: {root_path}")
        return
    prefix = root_path + "\\"
    if not target_path.startswith(prefix):
        raise CliRuntimeError("fixture path escaped its declared Wwise root")
    current = root_path
    if backend.read_object(current) is None:
        raise CliRuntimeError(f"fixture root is absent: {current}")
    for segment in target_path[len(prefix) :].split("\\"):
        current += "\\" + _segment(segment)
        backend.ensure_object(path=current, object_type=object_type)


def _tab_wav_paths(runtime: PreparedCliRuntime) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for row in runtime.plan.asset_spec["assets"]["wav"]["files"]:
        result[str(row["key"])] = _contained_existing_file(
            runtime.plan.asset_root / "wav",
            str(row["name"]),
        )
    return result


def _prestate_wav_path(runtime: PreparedCliRuntime, key: str) -> Path:
    return _contained_existing_file(runtime.plan.asset_root / "prestate", f"{key}.wav")


def _resolve_binding(bindings: Mapping[str, Path], row: Mapping[str, Any]) -> Path:
    key = str(row["root_key"])
    try:
        root = bindings[key]
    except KeyError as exc:
        raise CliRuntimeError(f"unresolved CLI root binding: {key}") from exc
    relative = str(row["relative_path"])
    if relative == ".":
        return root
    return _contained_path(root, relative)


def _platform_pairs(values: Sequence[tuple[str, str]]) -> list[str] | list[list[str]]:
    if not values:
        raise CliRuntimeError("platform mapping must not be empty")
    normalized = [[_required_text(platform, "platform"), _required_text(value, "platform value")] for platform, value in values]
    return normalized[0] if len(normalized) == 1 else normalized


def _string_or_list(values: Sequence[str]) -> str | list[str]:
    normalized = list(_unique_texts(values, "CLI values"))
    if not normalized:
        raise CliRuntimeError("CLI string/list value must not be empty")
    return normalized[0] if len(normalized) == 1 else normalized


def _write_pcm_wav(path: Path, *, duration_ms: int, frequency_hz: int) -> None:
    if duration_ms <= 0 or frequency_hz <= 0:
        raise CliRuntimeError("deterministic WAV signal parameters must be positive")
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 48_000
    frame_count = max(1, round(sample_rate * duration_ms / 1000))
    amplitude = 0.2 * 32767
    frames = bytearray()
    for index in range(frame_count):
        sample = int(amplitude * math.sin(2.0 * math.pi * frequency_hz * index / sample_rate))
        frames.extend(struct.pack("<h", sample))
    if path.exists():
        raise CliRuntimeError(f"refusing to overwrite deterministic WAV fixture: {path}")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(frames))


def _write_marker_riff(path: Path, marker: str) -> None:
    payload = marker.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF" + len(payload).to_bytes(4, "little") + b"WAVE" + payload)


def _write_marker_bank(path: Path, marker: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"BKHD" + marker.encode("utf-8"))


def _valid_riff(path: Path) -> bool:
    try:
        data = path.read_bytes()[:12]
    except OSError:
        return False
    return len(data) >= 12 and data[:4] in {b"RIFF", b"RIFX"} and data[8:12] == b"WAVE"


def _valid_bank(path: Path) -> bool:
    try:
        return path.stat().st_size > 4 and path.read_bytes()[:4] == b"BKHD"
    except OSError:
        return False


def _proof_if_file(path: Path, root: Path) -> FileProof | None:
    if not path.is_file() or path.is_symlink():
        return None
    stat = path.stat()
    if stat.st_size <= 0 or stat.st_size > MAX_FILE_BYTES:
        return None
    return FileProof(
        path=str(path),
        relative_path=path.relative_to(root).as_posix(),
        size=stat.st_size,
        sha256=_file_sha256(path),
        mtime_ns=stat.st_mtime_ns,
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_file(path: Path, *, field: str, executable: bool = False) -> Path:
    resolved = Path(path).expanduser().resolve(strict=True)
    if not resolved.is_file() or resolved.is_symlink():
        raise CliRuntimeError(f"{field} must be a regular non-symlink file")
    if executable and not os.access(resolved, os.X_OK):
        raise CliRuntimeError(f"{field} must be executable")
    return resolved


def _contained_file(root: Path, relative: str) -> Path:
    return _contained_path(root, relative)


def _contained_existing_file(root: Path, relative: str) -> Path:
    path = _contained_path(root, relative).resolve(strict=True)
    if not path.is_file() or path.is_symlink():
        raise CliRuntimeError(f"contained path is not a regular file: {relative}")
    return path


def _contained_path(root: Path, relative: str) -> Path:
    base = root.resolve(strict=False)
    pure = PurePosixPath(relative.replace("\\", "/"))
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise CliRuntimeError(f"path is not a safe contained relative path: {relative!r}")
    path = base.joinpath(*pure.parts).resolve(strict=False)
    if base not in path.parents:
        raise CliRuntimeError("contained path escaped its root")
    return path


def _reject_symlink_ancestors(path: Path, *, stop: Path) -> None:
    current = path
    stop_resolved = stop.resolve(strict=False)
    while True:
        if current.exists() and current.is_symlink():
            raise CliRuntimeError(f"CLI path contains a symlink ancestor: {current}")
        if current.resolve(strict=False) == stop_resolved or current.parent == current:
            return
        current = current.parent


def _resolve(value: str | Path) -> Path:
    return Path(value).expanduser().resolve(strict=False)


def _localize_waapi_host_path(value: str, *, field: str) -> Path:
    """Convert one live WAAPI filesystem path to an exact trusted host path.

    The CLI oracle is launched through Wine on POSIX hosts.  ``getProjectInfo``
    and object source accessors consequently report the account-home and
    filesystem-root mappings as ``Y:\\...`` and ``Z:\\...`` respectively.
    Only those two Wine drives are trusted.  Lexical traversal, UNC spellings,
    symlink traversal, and paths that are not absolute fail before filesystem
    reads so a Windows spelling can never be treated as one long POSIX name.
    """

    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise CliRuntimeError(f"{field} must be a non-empty path string")

    try:
        windows_path = parse_windows_drive_path(value)
    except ReflectedHostPathError as exc:
        raise CliRuntimeError(f"{field} has an unsafe Windows path") from exc
    containment_root: Path | None = None
    if windows_path is not None:
        drive = windows_path.drive
        parts = windows_path.relative_parts
        native_drive_root = _native_windows_drive_root(windows_path)
        if drive == "Y" and (os.name != "nt" or pwd is not None):
            containment_root = _resolved_account_home(field=field)
            path = containment_root.joinpath(*parts)
        elif native_drive_root is not None:
            containment_root = native_drive_root
            path = Path(windows_path.pure)
        elif drive == "Z":
            if os.name == "nt":
                raise CliRuntimeError(
                    f"{field} uses Wine Z: on a native Windows host"
                )
            containment_root = Path("/")
            path = containment_root.joinpath(*parts)
        elif drive == "Y":
            raise CliRuntimeError(
                f"{field} uses an unavailable native Windows drive Y:"
            )
        else:
            raise CliRuntimeError(f"{field} uses unmappable Wine drive {drive}:")
    else:
        try:
            posix_path = parse_posix_absolute_path(value)
        except ReflectedHostPathError as exc:
            raise CliRuntimeError(
                f"{field} must be an absolute host path"
            ) from exc
        path = Path(posix_path)
    if not path.is_absolute():
        raise CliRuntimeError(f"{field} must be an absolute host path")
    if containment_root is None:
        containment_root = Path(path.anchor)
    try:
        relative_parts = path.relative_to(containment_root).parts
    except ValueError as exc:
        raise CliRuntimeError(f"{field} escaped its mapped host root") from exc
    current = containment_root
    for part in relative_parts:
        current = current / part
        if current.is_symlink():
            raise CliRuntimeError(f"{field} contains a symlink component")
    try:
        resolved = path.resolve(strict=False)
    except OSError as exc:
        raise CliRuntimeError(f"{field} could not be resolved on this host") from exc
    try:
        resolved.relative_to(containment_root.resolve(strict=False))
    except ValueError as exc:
        raise CliRuntimeError(f"{field} escaped its mapped host root") from exc
    return resolved


def _native_windows_drive_root(value: WindowsDrivePath) -> Path | None:
    """Return an available native drive root, otherwise leave it unprobed.

    On Windows, a real mapped ``Y:`` or ``Z:`` drive wins over the historical
    Wine aliases.  An absent drive is never passed to ``Path.resolve``.
    """

    if os.name != "nt":
        return None
    root = Path(value.pure.anchor)
    try:
        return root if root.is_dir() else None
    except OSError:
        return None


def _resolved_account_home(*, field: str) -> Path:
    """Resolve the immutable OS account home for a Wine ``Y:`` mapping."""

    if pwd is None:
        raise CliRuntimeError(
            f"{field} Wine Y: mapping is unavailable on this host"
        )
    try:
        getuid = getattr(os, "getuid", None)
        uid = getuid() if callable(getuid) else None
        home = Path(pwd.getpwuid(uid).pw_dir)
        resolved = home.resolve(strict=True)
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError) as exc:
        raise CliRuntimeError(
            f"{field} Wine Y: drive could not be mapped to the host account home"
        ) from exc
    if not resolved.is_dir():
        raise CliRuntimeError(
            f"{field} Wine Y: drive account home is not a directory"
        )
    return resolved


def _wwise_path(value: str) -> str:
    text = _required_text(value, "Wwise path")
    if not text.startswith("\\") or text.endswith("\\") or "\\\\" in text:
        raise CliRuntimeError(f"invalid absolute Wwise path: {value!r}")
    for segment in text[1:].split("\\"):
        _segment(segment)
    return text


def _setup_event_value(event_path: str) -> str:
    """Encode one closed setup Event using Wwise's path-and-action grammar."""

    path = _wwise_path(event_path)
    if "@" in path:
        raise CliRuntimeError("event_path must not embed an Event action")
    return f"{path}@{SETUP_EVENT_ACTION}"


def _typed_existing_import_path(
    value: str,
    *,
    object_type: str,
    language: str,
) -> tuple[str, str]:
    raw_path = _required_text(value, "localized useExisting object_path")
    if "<" in raw_path or ">" in raw_path:
        raise CliRuntimeError(
            "localized useExisting object_path must be an untyped canonical path"
        )
    canonical_path = _wwise_path(raw_path)
    if object_type not in {"Sound Voice", "Sound SFX"}:
        raise CliRuntimeError(
            "localized useExisting object_type must be closed as Sound Voice or Sound SFX"
        )
    expected_type = "Sound SFX" if language == "SFX" else "Sound Voice"
    if object_type != expected_type:
        raise CliRuntimeError(
            "localized useExisting object_type is ambiguous for importLanguage"
        )
    parent, name = _split_wwise_path(canonical_path)
    return canonical_path, f"{parent}\\<{object_type}>{name}"


def _split_wwise_path(value: str) -> tuple[str, str]:
    path = _wwise_path(value)
    parent, separator, name = path.rpartition("\\")
    if not separator or not parent or not name:
        raise CliRuntimeError("Wwise path has no creatable parent")
    return parent, _segment(name)


def _segment(value: str) -> str:
    text = _required_text(value, "Wwise name")
    if not SAFE_SEGMENT_RE.fullmatch(text):
        raise CliRuntimeError(f"unsafe Wwise path segment: {value!r}")
    return text


def _canonical_language(value: str) -> str:
    aliases = {
        "Chinese": "Chinese(PRC)",
        "Chinese(PRC)": "Chinese(PRC)",
        "English": "English(US)",
        "English(US)": "English(US)",
        "Japanese": "Japanese",
        "SFX": "SFX",
    }
    try:
        return aliases[value]
    except KeyError as exc:
        raise CliRuntimeError(f"unreviewed Wwise language alias: {value!r}") from exc


def _language_matches(value: str | None, expected: str) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        return _canonical_language(value) == _canonical_language(expected)
    except CliRuntimeError:
        return False


def _language_name(value: Any, field: str) -> str:
    if isinstance(value, str):
        if value and value.strip() == value:
            return value
        raise CliRuntimeError(f"{field} must be a non-empty exact language name")
    if not isinstance(value, Mapping):
        raise CliRuntimeError(
            f"{field} must be a string or a language identity mapping"
        )
    candidates = [value[key] for key in ("name", "value") if key in value]
    if not candidates or any(
        not isinstance(candidate, str)
        or not candidate
        or candidate.strip() != candidate
        for candidate in candidates
    ):
        raise CliRuntimeError(
            f"{field} identity must expose a non-empty exact name or value"
        )
    if len(set(candidates)) != 1:
        raise CliRuntimeError(f"{field} identity names are inconsistent")
    return candidates[0]


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise CliRuntimeError(f"{field} must be a non-empty string")
    return value


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _first_text(row: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _required_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise CliRuntimeError(f"{field} must be an integer")
    return value


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return _required_int(value, "optional integer")


def _unique_texts(values: Sequence[str], field: str) -> tuple[str, ...]:
    result = tuple(_required_text(value, field) for value in values)
    if len(result) != len(set(result)):
        raise CliRuntimeError(f"{field} contains duplicates")
    return result


def _guid(value: Any, field: str) -> str:
    text = _identity_value(value)
    if not text or not GUID_RE.fullmatch(text):
        raise CliRuntimeError(f"{field} must be one GUID")
    return text.upper()


def _identity_value(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key in ("id", "value"):
            nested = value.get(key)
            if isinstance(nested, str) and nested:
                return nested
        return None
    if isinstance(value, str) and value:
        return value
    return None


def _type_name(value: Any) -> str:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, Mapping):
        for key in ("name", "type"):
            nested = value.get(key)
            if isinstance(nested, str) and nested:
                return nested
    raise CliRuntimeError("object type is not a string")


def _types_equivalent(observed: str, expected: str) -> bool:
    if observed == expected:
        return True
    if expected in {"Sound SFX", "Sound Voice"} and observed == "Sound":
        return True
    return False


def _result_rows(
    result: Any,
    label: str,
    *,
    key: str = "return",
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(result, Mapping):
        raise CliRuntimeError(f"{label} result must be an object")
    rows = result.get(key, [])
    if not isinstance(rows, list) or len(rows) > MAX_OBJECTS or any(not isinstance(row, Mapping) for row in rows):
        raise CliRuntimeError(f"{label} returned an invalid or oversized row array")
    return tuple(dict(row) for row in rows)


__all__ = [
    "CLI_APIS",
    "CLI_RUNTIME_CONTRACT",
    "EXPECTED_CLI_SCENARIO_COUNT",
    "AnchorInventory",
    "CliDispatchEvidence",
    "CliEventRecord",
    "CliLifecyclePlan",
    "CliObjectRecord",
    "CliRuntimeBackend",
    "CliRuntimeError",
    "CliRuntimePlan",
    "CliRuntimeSnapshot",
    "CliRuntimeVerification",
    "ClosedDirectCliBackend",
    "FileProof",
    "PreparedCliRuntime",
    "ProcessPhaseEvidence",
    "ProcessPhaseSpec",
    "SetupAudioImport",
    "TreeProof",
    "all_cli_scenarios",
    "authored_project_archive_projection",
    "build_cli_runtime_plan",
    "materialize_cli_runtime",
]
