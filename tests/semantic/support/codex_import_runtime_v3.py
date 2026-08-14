"""Runner-owned live fixture and oracle for the ten v3 import scenarios.

The evaluated Codex task only receives the values already exposed by
``MaterializedImportCase.visible_values``.  Live GUIDs, saved project XML,
copied Originals hashes, and the direct WAAPI connection remain in this
trusted runner module.

The module has two seams:

* :class:`ImportRuntimeBackend` is a small injectable protocol used by unit
  tests and by the scenario runner.
* :class:`ClosedDirectWaapiBackend` is the real adapter.  It exposes no generic
  ``call`` method and emits only the closed read/setup/save/cleanup shapes
  required by this fixture.

It never starts Codex or Wwise.  The caller must pass an already-running,
scenario-owned Wwise project copy and must let the outer scenario lifecycle
quarantine failed or indeterminate sandboxes.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from types import MappingProxyType
from typing import Any, Protocol

from .codex_eval_bundle_v3 import OnlineScenario
from .codex_import_assets_v3 import (
    MaterializedFile,
    MaterializedImportCase,
    canonical_wwise_language,
    compound_dynamic_modes_by_row,
)
from .codex_host_paths import (
    ReflectedHostPathError,
    parse_posix_absolute_path,
    parse_windows_drive_path,
)
from .codex_version_layout_v3 import (
    CodexVersionLayoutError,
    get_codex_version_layout_v3,
)

try:  # ``pwd`` is unavailable on native Windows, where Wine mapping is unused.
    import pwd
except ImportError:  # pragma: no cover - native Windows skips Wine mapping
    pwd = None  # type: ignore[assignment]


IMPORT_APIS = frozenset(
    {"ak.wwise.core.audio.import", "ak.wwise.core.audio.importTabDelimited"}
)
SUPPORTED_VERSION = "2022.1"
COMPOUND_SUPPORTED_VERSIONS = ("2022.1", "2025.1")
PROFILE_CROSS_VERSION_SCENARIOS = MappingProxyType(
    {
        "O22-AUDIO-IMPORT-02": ("2021.1",),
        "O22-AUDIO-TAB-04": ("2025.1",),
    }
)


def import_runtime_version_is_reviewed(
    scenario_id: str,
    version: str,
    *,
    compound: bool,
) -> bool:
    if compound:
        return version in COMPOUND_SUPPORTED_VERSIONS
    return version == SUPPORTED_VERSION or version in PROFILE_CROSS_VERSION_SCENARIOS.get(
        scenario_id,
        (),
    )
ACTOR_DWU = r"\Actor-Mixer Hierarchy\Default Work Unit"
EVENTS_DWU = r"\Events\Default Work Unit"
GUID_RE = re.compile(
    r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$"
)
TYPED_SEGMENT_RE = re.compile(r"^<([^<>]+)>([^<>]+)$")
MAX_OBJECT_ROWS = 256
MAX_PROJECT_XML_FILES = 512
MAX_TREE_FILES = 4096
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_DYNAMIC_FIELDS = 32
MAX_REFERENCE_FIXTURES = 8
LIVE_METADATA_TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
OBJECT_FIELDS = (
    "id",
    "name",
    "type",
    "path",
    "parent",
    "notes",
    "activeSource",
    "originalFilePath",
    "sound:originalWavFilePath",
    "audioSource:language",
)
OBJECT_FIELDS_2021 = tuple(
    field
    for field in OBJECT_FIELDS
    if field not in {"activeSource", "originalFilePath"}
)
AUDIO_SOURCE_FIELDS = (
    "id",
    "name",
    "type",
    "path",
    "parent",
    "notes",
    "originalFilePath",
    "audioSource:language",
)
AUDIO_SOURCE_FIELDS_2021 = tuple(
    field for field in AUDIO_SOURCE_FIELDS if field != "originalFilePath"
) + ("originalWavFilePath",)
EVENT_FIELDS = ("id", "name", "type", "path", "parent", "notes")
ACTION_FIELDS = (*EVENT_FIELDS, "ActionType", "Target")
PLAY_ACTION_TYPE = 1


class ImportRuntimeError(RuntimeError):
    """The runner-owned import fixture or independent oracle failed closed."""


DirectWaapiCall = Callable[
    [str, Mapping[str, Any], Mapping[str, Any]], Any
]


@dataclass(frozen=True, slots=True)
class ImportParentPlan:
    path: str
    parent_path: str
    name: str
    object_type: str


@dataclass(frozen=True, slots=True)
class ImportRowPlan:
    row_key: str
    target_path: str
    setup_object_path: str
    object_type: str
    language: str
    source_file: MaterializedFile
    pre_state_file: MaterializedFile | None
    pre_state_existence: str
    pre_state_guid_key: str | None
    pre_state_notes: str | None
    import_operation: str
    guid_policy: str
    originals_subfolder: str | None
    notes: str | None
    audio_source_notes: str | None
    event_path: str | None
    event_action: str | None
    expected_properties: tuple["ImportPropertyExpectation", ...] = ()
    expected_references: tuple["ImportReferenceExpectation", ...] = ()
    preserve_property_tokens: tuple[str, ...] = ()
    preserve_reference_tokens: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ImportPropertyExpectation:
    name: str
    value: Any
    metadata_type: str
    source: str


@dataclass(frozen=True, slots=True)
class ImportReferenceExpectation:
    name: str
    target_id: str
    target_fixture: str
    activation_properties: tuple[ImportPropertyExpectation, ...]


@dataclass(frozen=True, slots=True)
class ImportReferenceFixtureState:
    key: str
    path: str
    id: str
    type: str
    parent_id: str | None


@dataclass(frozen=True, slots=True)
class ImportReferenceFixtureCleanup:
    scenario_id: str
    deleted_paths: tuple[str, ...]
    paths_absent: bool
    already_clean: bool


@dataclass(frozen=True, slots=True)
class ImportRuntimePlan:
    scenario_id: str
    api: str
    version: str
    sandbox_project: Path
    sandbox_root: Path
    asset_root: Path
    parents: tuple[ImportParentPlan, ...]
    rows: tuple[ImportRowPlan, ...]
    event_paths: tuple[str, ...]
    operation_requests: tuple[Mapping[str, Any], ...]
    visible_values: Mapping[str, str]
    expected_primary_dispatch_count: int
    actor_dwu: str = ACTOR_DWU
    events_dwu: str = EVENTS_DWU
    main_bus_path: str | None = None
    main_bus_id: str | None = None
    reference_fixtures: tuple[ImportReferenceFixtureState, ...] = ()
    metadata_binding: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class FileProof:
    path: str
    relative_path: str | None
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ImportAudioSourceState:
    id: str
    language: str
    notes: str | None
    original_file: FileProof
    original_relative_path: str | None


@dataclass(frozen=True, slots=True)
class ImportObjectState:
    id: str
    name: str
    type: str
    path: str
    parent_id: str | None
    notes: str | None
    audio_source: ImportAudioSourceState | None


@dataclass(frozen=True, slots=True)
class ImportRowState:
    row_key: str
    target_path: str
    language: str
    object: ImportObjectState | None


@dataclass(frozen=True, slots=True)
class ImportEventState:
    path: str
    id: str | None
    action_id: str | None
    action_type: int | None
    target: Any
    child_count: int


@dataclass(frozen=True, slots=True)
class XmlIdentityEvidence:
    guid: str
    relative_file: str
    element_tag: str
    name: str | None


@dataclass(frozen=True, slots=True)
class ImportRuntimeSnapshot:
    scenario_id: str
    rows: tuple[ImportRowState, ...]
    events: tuple[ImportEventState, ...]
    project_xml_files: tuple[FileProof, ...]
    originals_files: tuple[FileProof, ...]
    input_files: tuple[tuple[str, bool, int | None, str | None], ...]
    xml_identities: tuple[XmlIdentityEvidence, ...]

    def row(self, row_key: str) -> ImportRowState:
        matches = tuple(item for item in self.rows if item.row_key == row_key)
        if len(matches) != 1:
            raise ImportRuntimeError(
                f"snapshot row {row_key!r} did not resolve exactly once"
            )
        return matches[0]


@dataclass(frozen=True, slots=True)
class ImportPropertyState:
    name: str
    value: Any


@dataclass(frozen=True, slots=True)
class ImportReferenceState:
    name: str
    target_id: str | None


@dataclass(frozen=True, slots=True)
class ImportCompoundRowState:
    row_key: str
    target_path: str
    properties: tuple[ImportPropertyState, ...]
    references: tuple[ImportReferenceState, ...]


@dataclass(frozen=True, slots=True)
class ImportCompoundRuntimeSnapshot:
    """Independent dynamic-field evidence layered over the legacy snapshot."""

    scenario_id: str
    business: ImportRuntimeSnapshot
    rows: tuple[ImportCompoundRowState, ...]
    reference_fixtures: tuple[ImportReferenceFixtureState, ...]
    main_bus: ImportReferenceFixtureState

    def row(self, row_key: str) -> ImportCompoundRowState:
        matches = tuple(item for item in self.rows if item.row_key == row_key)
        if len(matches) != 1:
            raise ImportRuntimeError(
                f"compound snapshot row {row_key!r} did not resolve exactly once"
            )
        return matches[0]


@dataclass(frozen=True, slots=True)
class ImportRuntimeVerification:
    scenario_id: str
    phase: str
    passed: bool
    failures: tuple[str, ...]
    before: ImportRuntimeSnapshot | ImportCompoundRuntimeSnapshot
    after: ImportRuntimeSnapshot | ImportCompoundRuntimeSnapshot

    def assert_passed(self) -> None:
        if not self.passed:
            raise ImportRuntimeError(
                f"{self.scenario_id} {self.phase} verification failed: "
                + "; ".join(self.failures)
            )


@dataclass(frozen=True, slots=True)
class ImportRuntimeCleanup:
    scenario_id: str
    deleted_root_paths: tuple[str, ...]
    assets_removed: bool
    paths_absent: bool


@dataclass(frozen=True, slots=True)
class SetupImport:
    object_path: str
    object_type: str
    language: str
    audio_file: Path
    import_operation: str
    originals_subfolder: str | None
    notes: str | None
    audio_source_notes: str | None


class ImportRuntimeBackend(Protocol):
    """Trusted runner seam; never pass an implementation to the model."""

    def read_objects(
        self,
        *,
        path: str | None = None,
        object_id: str | None = None,
        fields: Sequence[str] = OBJECT_FIELDS,
        language: str | None = None,
    ) -> tuple[Mapping[str, Any], ...]: ...

    def read_direct_children(
        self,
        object_id: str,
        *,
        fields: Sequence[str],
    ) -> tuple[Mapping[str, Any], ...]: ...

    def setup_create_parent(
        self, *, parent_path: str, object_type: str, name: str
    ) -> str: ...

    def setup_create_reference_bus(self, *, parent_path: str, name: str) -> str: ...

    def read_bound_values(
        self,
        *,
        path: str,
        names: Sequence[str],
    ) -> tuple[Mapping[str, Any], ...]: ...

    def setup_import(self, request: SetupImport) -> None: ...

    def save_project(self) -> None: ...

    def cleanup_delete(self, object_id: str) -> None: ...


class ClosedDirectWaapiBackend:
    """Strict direct-WAAPI adapter for trusted setup/read/save/cleanup only."""

    def __init__(self, call: DirectWaapiCall, *, version: str = "2022.1") -> None:
        if not callable(call):
            raise TypeError("call must be callable")
        self._call = call
        self._version = _required_text(version, "version")

    def read_objects(
        self,
        *,
        path: str | None = None,
        object_id: str | None = None,
        fields: Sequence[str] = OBJECT_FIELDS,
        language: str | None = None,
    ) -> tuple[Mapping[str, Any], ...]:
        if (path is None) == (object_id is None):
            raise ImportRuntimeError("direct object read requires exactly one selector")
        selector = "path" if path is not None else "id"
        value = path if path is not None else object_id
        if not isinstance(value, str) or not value:
            raise ImportRuntimeError("direct object read selector must be non-empty")
        return_fields = _validated_fields(fields)
        options: dict[str, Any] = {"return": list(return_fields)}
        if language is not None:
            options["language"] = _required_text(language, "language")
        result = self._call(
            "ak.wwise.core.object.get",
            {"from": {selector: [value]}},
            options,
        )
        return _result_rows(result, context="object.get")

    def read_direct_children(
        self,
        object_id: str,
        *,
        fields: Sequence[str],
    ) -> tuple[Mapping[str, Any], ...]:
        object_id = _required_guid(object_id, "object_id")
        result = self._call(
            "ak.wwise.core.object.get",
            {
                "from": {"id": [object_id]},
                "transform": [{"select": ["children"]}],
            },
            {"return": list(_validated_fields(fields))},
        )
        return _result_rows(result, context="object.get children")

    def setup_create_parent(
        self, *, parent_path: str, object_type: str, name: str
    ) -> str:
        if object_type not in {"Folder", "ActorMixer", "RandomSequenceContainer"}:
            raise ImportRuntimeError(
                f"setup parent type is outside the closed import fixture: {object_type!r}"
            )
        result = self._call(
            "ak.wwise.core.object.create",
            {
                "parent": _required_wwise_path(parent_path, "parent_path"),
                "type": object_type,
                "name": _required_text(name, "name"),
                "onNameConflict": "fail",
            },
            {},
        )
        if not isinstance(result, Mapping):
            raise ImportRuntimeError("object.create setup result must be an object")
        return _required_guid(result.get("id"), "object.create result id")

    def setup_create_reference_bus(self, *, parent_path: str, name: str) -> str:
        result = self._call(
            "ak.wwise.core.object.create",
            {
                "parent": _required_wwise_path(parent_path, "parent_path"),
                "type": "Bus",
                "name": _required_text(name, "name"),
                "onNameConflict": "fail",
            },
            {},
        )
        if not isinstance(result, Mapping):
            raise ImportRuntimeError(
                "reference Bus object.create result must be an object"
            )
        return _required_guid(result.get("id"), "reference Bus result id")

    def read_bound_values(
        self,
        *,
        path: str,
        names: Sequence[str],
    ) -> tuple[Mapping[str, Any], ...]:
        tokens = _validated_dynamic_tokens(names)
        result = self._call(
            "ak.wwise.core.object.get",
            {"from": {"path": [_required_wwise_path(path, "path")]}},
            {
                "return": [
                    "id",
                    "path",
                    *[f"@{name}" for name in tokens],
                ]
            },
        )
        return _result_rows(result, context="object.get bound values")

    def setup_import(self, request: SetupImport) -> None:
        source = _regular_file_proof(request.audio_file, relative_to=None)
        if request.import_operation not in {"createNew", "useExisting"}:
            raise ImportRuntimeError(
                "fixture setup import_operation must be createNew or useExisting"
            )
        localized_existing_wire = (
            request.import_operation == "useExisting"
            and request.language.casefold() != "sfx"
        )
        if localized_existing_wire and any(
            value is not None
            for value in (
                request.originals_subfolder,
                request.notes,
                request.audio_source_notes,
            )
        ):
            raise ImportRuntimeError(
                "localized useExisting fixture setup accepts only audioFile, "
                "objectPath, and importLanguage"
            )
        row: dict[str, Any] = {
            "audioFile": source.path,
            "objectPath": _required_wwise_path(request.object_path, "object_path"),
            "importLanguage": _required_text(request.language, "language"),
        }
        if not localized_existing_wire:
            row["objectType"] = _required_text(request.object_type, "object_type")
        if request.originals_subfolder is not None:
            row["originalsSubFolder"] = _required_text(
                request.originals_subfolder, "originals_subfolder"
            )
        if request.notes is not None:
            row["notes"] = str(request.notes)
        if request.audio_source_notes is not None:
            row["audioSourceNotes"] = str(request.audio_source_notes)
        result = self._call(
            "ak.wwise.core.audio.import",
            {
                "importOperation": request.import_operation,
                "imports": [row],
                "autoAddToSourceControl": False,
            },
            {
                "return": list(
                    OBJECT_FIELDS_2021
                    if self._version == "2021.1"
                    else OBJECT_FIELDS
                )
            },
        )
        if not isinstance(result, Mapping):
            raise ImportRuntimeError("audio.import setup result must be an object")

    def save_project(self) -> None:
        result = self._call("ak.wwise.core.project.save", {}, {})
        if result is not None and not isinstance(result, Mapping):
            raise ImportRuntimeError("project.save result must be an object or null")

    def cleanup_delete(self, object_id: str) -> None:
        result = self._call(
            "ak.wwise.core.object.delete",
            {"object": _required_guid(object_id, "cleanup object id")},
            {},
        )
        if result is not None and not isinstance(result, Mapping):
            raise ImportRuntimeError("object.delete cleanup result must be an object or null")


class PreparedImportReferenceFixtures:
    """Two-phase owner for compound import Bus fixtures.

    The fixture must exist before live metadata is bound.  The Agent-facing
    request uses its exact reviewed Bus path, while the independent oracle
    retains the resolved GUID.  Once adopted by ``PreparedImportRuntime``,
    cleanup ownership moves to that runtime.  Before adoption, callers may use
    ``cleanup_emergency`` on any failure path.
    """

    def __init__(
        self,
        *,
        scenario_id: str,
        version: str,
        materialized_fingerprint: tuple[tuple[str, str, bool, int | None, str | None], ...],
        expected_paths: Mapping[str, str],
        fixtures: Sequence[ImportReferenceFixtureState],
        main_bus: ImportReferenceFixtureState,
        backend: ImportRuntimeBackend,
    ) -> None:
        self.scenario_id = scenario_id
        self.version = version
        self._materialized_fingerprint = materialized_fingerprint
        self.expected_paths = MappingProxyType(dict(expected_paths))
        self.fixtures = tuple(fixtures)
        self.main_bus = main_bus
        self.reference_targets = MappingProxyType(
            {
                item.key: MappingProxyType({"kind": "id", "value": item.id})
                for item in self.fixtures
            }
        )
        self.request_reference_targets = MappingProxyType(
            {
                item.key: MappingProxyType({"kind": "path", "value": item.path})
                for item in self.fixtures
            }
        )
        self._backend = backend
        self._adopted = False
        self._cleaned = False

    @property
    def adopted(self) -> bool:
        return self._adopted

    @property
    def cleaned(self) -> bool:
        return self._cleaned

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(item.path for item in self.fixtures)

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(item.id for item in self.fixtures)

    def adopt(
        self,
        *,
        scenario: OnlineScenario,
        materialized: MaterializedImportCase,
    ) -> None:
        if self._cleaned:
            raise ImportRuntimeError("cleaned import reference fixtures cannot be adopted")
        if self._adopted:
            raise ImportRuntimeError("import reference fixtures are already adopted")
        _validate_reference_fixture_handle(
            self,
            scenario=scenario,
            materialized=materialized,
        )
        self._adopted = True

    def cleanup_emergency(self) -> ImportReferenceFixtureCleanup:
        """Idempotently remove unadopted fixtures after a setup/binding error."""

        if self._adopted:
            raise ImportRuntimeError(
                "adopted import reference fixtures are owned by the import runtime"
            )
        return self._cleanup(already_clean=self._cleaned)

    def _cleanup_adopted(self) -> ImportReferenceFixtureCleanup:
        if not self._adopted:
            raise ImportRuntimeError(
                "import runtime cannot clean reference fixtures it did not adopt"
            )
        return self._cleanup(already_clean=self._cleaned)

    def _cleanup(self, *, already_clean: bool) -> ImportReferenceFixtureCleanup:
        if not self._cleaned:
            for item in reversed(self.fixtures):
                if self._backend.read_objects(path=item.path, fields=EVENT_FIELDS):
                    self._backend.cleanup_delete(item.id)
            self._backend.save_project()
            self._cleaned = True
        absent = all(
            not self._backend.read_objects(path=item.path, fields=EVENT_FIELDS)
            for item in self.fixtures
        )
        if not absent:
            raise ImportRuntimeError("compound import reference fixture cleanup failed")
        return ImportReferenceFixtureCleanup(
            scenario_id=self.scenario_id,
            deleted_paths=self.paths,
            paths_absent=True,
            already_clean=already_clean,
        )


def prepare_import_reference_fixtures(
    scenario: OnlineScenario,
    staged: MaterializedImportCase,
    *,
    version: str,
    backend: ImportRuntimeBackend,
) -> PreparedImportReferenceFixtures:
    """Create and independently prove the unique Bus targets for one case."""

    if (
        staged.compound_spec is None
        or not staged.requires_metadata_binding
        or staged.operation_requests
        or staged.metadata_binding is not None
    ):
        raise ImportRuntimeError(
            "reference fixtures require one unbound compound import case"
        )
    if scenario.id != staged.scenario_id or scenario.versions != (version,):
        raise ImportRuntimeError(
            "compound reference fixture scenario/version identity is misbound"
        )
    if version not in COMPOUND_SUPPORTED_VERSIONS:
        raise ImportRuntimeError(
            f"compound import reference fixtures do not support Wwise {version}"
        )
    paths = dict(staged.reference_fixture_paths)
    if (
        not 1 <= len(paths) <= MAX_REFERENCE_FIXTURES
        or len(paths) != len(set(paths.values()))
    ):
        raise ImportRuntimeError(
            "compound import requires 1..8 unique reference fixture paths"
        )
    try:
        layout = get_codex_version_layout_v3(version)
    except CodexVersionLayoutError as exc:
        raise ImportRuntimeError(str(exc)) from exc

    busses_dwu_rows = backend.read_objects(
        path=layout.busses_dwu,
        fields=EVENT_FIELDS,
    )
    main_bus_rows = backend.read_objects(
        path=layout.main_bus,
        fields=EVENT_FIELDS,
    )
    if len(busses_dwu_rows) != 1 or busses_dwu_rows[0].get("path") != layout.busses_dwu:
        raise ImportRuntimeError(
            f"required Busses work unit is unavailable: {layout.busses_dwu}"
        )
    if len(main_bus_rows) != 1 or main_bus_rows[0].get("path") != layout.main_bus:
        raise ImportRuntimeError(
            f"required default main Bus is unavailable: {layout.main_bus}"
        )
    busses_dwu_id = _required_guid(
        busses_dwu_rows[0].get("id"),
        "Busses work unit id",
    )
    main_bus = _reference_fixture_state(
        "__default_main_bus__",
        layout.main_bus,
        main_bus_rows[0],
        expected_type="Bus",
    )
    if not _same_guid(main_bus.parent_id, busses_dwu_id):
        raise ImportRuntimeError("default main Bus parent differs from the Busses work unit")

    created: list[ImportReferenceFixtureState] = []
    try:
        for key, path in sorted(paths.items()):
            path = _required_wwise_path(path, f"reference fixture {key} path")
            parent_path, name = path.rsplit("\\", 1)
            if parent_path != layout.busses_dwu:
                raise ImportRuntimeError(
                    f"reference fixture {key!r} is outside the reviewed Busses work unit"
                )
            if backend.read_objects(path=path, fields=EVENT_FIELDS):
                raise ImportRuntimeError(
                    f"compound reference fixture path already exists: {path}"
                )
            object_id = backend.setup_create_reference_bus(
                parent_path=parent_path,
                name=name,
            )
            rows = backend.read_objects(path=path, fields=EVENT_FIELDS)
            if len(rows) != 1:
                raise ImportRuntimeError(
                    f"reference Bus did not resolve exactly once: {path}"
                )
            state = _reference_fixture_state(
                key,
                path,
                rows[0],
                expected_type="Bus",
            )
            if (
                not _same_guid(state.id, object_id)
                or not _same_guid(state.parent_id, busses_dwu_id)
            ):
                raise ImportRuntimeError(
                    f"reference Bus identity/parent readback drifted: {path}"
                )
            if _same_guid(state.id, main_bus.id):
                raise ImportRuntimeError(
                    f"reference Bus unexpectedly aliases the default main Bus: {path}"
                )
            created.append(state)
        if len({item.id.casefold() for item in created}) != len(created):
            raise ImportRuntimeError("reference Bus fixtures do not have unique GUIDs")
        backend.save_project()
    except Exception as exc:
        cleanup_errors: list[str] = []
        for item in reversed(created):
            try:
                backend.cleanup_delete(item.id)
            except Exception as cleanup_exc:  # pragma: no cover - real failure quarantine
                cleanup_errors.append(str(cleanup_exc))
        try:
            backend.save_project()
        except Exception as cleanup_exc:  # pragma: no cover - real failure quarantine
            cleanup_errors.append(str(cleanup_exc))
        if cleanup_errors:
            raise ImportRuntimeError(
                f"reference Bus setup failed ({exc}); rollback failed: "
                + "; ".join(cleanup_errors)
            ) from exc
        raise

    return PreparedImportReferenceFixtures(
        scenario_id=scenario.id,
        version=version,
        materialized_fingerprint=_materialized_handle_fingerprint(staged),
        expected_paths=paths,
        fixtures=created,
        main_bus=main_bus,
        backend=backend,
    )


class PreparedImportRuntime:
    """Single-use trusted fixture/oracle bound to one scenario project copy."""

    def __init__(
        self,
        *,
        scenario: OnlineScenario,
        materialized: MaterializedImportCase,
        plan: ImportRuntimePlan,
        backend: ImportRuntimeBackend,
        reference_fixtures: PreparedImportReferenceFixtures | None = None,
    ) -> None:
        self.scenario = scenario
        self.materialized = materialized
        self.plan = plan
        self.backend = backend
        self.reference_fixtures = reference_fixtures
        self.hidden_before: (
            ImportRuntimeSnapshot | ImportCompoundRuntimeSnapshot | None
        ) = None
        self._created_parent_ids: dict[str, str] = {}
        self._closed = False

    def render_prompt(self) -> str:
        """Render only reviewed model-visible inputs; no hidden identity is used."""

        return self.scenario.render_prompt(self.plan.visible_values)

    def prepare(self) -> "PreparedImportRuntime":
        if self.hidden_before is not None or self._closed:
            raise ImportRuntimeError("import runtime is single-use")
        _assert_materialized_inputs(self.materialized)
        roots = {self.plan.actor_dwu}
        if self.plan.event_paths:
            roots.add(self.plan.events_dwu)
        for root in sorted(roots):
            rows = self.backend.read_objects(path=root, fields=EVENT_FIELDS)
            if len(rows) != 1 or rows[0].get("path") != root:
                raise ImportRuntimeError(f"required Wwise fixture root is unavailable: {root}")

        if self.plan.metadata_binding is not None:
            if self.reference_fixtures is None or not self.reference_fixtures.adopted:
                raise ImportRuntimeError(
                    "compound import runtime lacks adopted reference fixtures"
                )
            failures = _validate_reference_fixture_snapshot(
                self.plan,
                self._snapshot_reference_fixtures(),
            )
            if failures:
                raise ImportRuntimeError(
                    "compound reference fixture proof failed: " + "; ".join(failures)
                )

        reserved_paths = [parent.path for parent in self.plan.parents]
        reserved_paths.extend(row.target_path for row in self.plan.rows)
        reserved_paths.extend(self.plan.event_paths)
        for path in _unique(reserved_paths):
            if self.backend.read_objects(path=path, fields=EVENT_FIELDS):
                raise ImportRuntimeError(
                    f"scenario-owned import path already exists before setup: {path}"
                )

        for parent in self.plan.parents:
            object_id = self.backend.setup_create_parent(
                parent_path=parent.parent_path,
                object_type=parent.object_type,
                name=parent.name,
            )
            rows = self.backend.read_objects(path=parent.path, fields=EVENT_FIELDS)
            if len(rows) != 1 or not _same_guid(rows[0].get("id"), object_id):
                raise ImportRuntimeError(
                    f"setup parent did not resolve at its exact path: {parent.path}"
                )
            if not _object_type_matches(rows[0].get("type"), parent.object_type):
                raise ImportRuntimeError(
                    f"setup parent reflected the wrong type at {parent.path}"
                )
            self._created_parent_ids[parent.path] = object_id

        setup_target_paths: set[str] = set()
        for row in self.plan.rows:
            if row.pre_state_existence != "existing":
                continue
            if row.pre_state_file is None:
                raise ImportRuntimeError(
                    f"{row.row_key} existing pre-state has no sealed media file"
                )
            target_key = row.target_path.casefold()
            first_language_for_target = target_key not in setup_target_paths
            self.backend.setup_import(
                SetupImport(
                    object_path=row.setup_object_path,
                    object_type=row.object_type,
                    language=row.language,
                    audio_file=row.pre_state_file.path,
                    import_operation=(
                        "createNew" if first_language_for_target else "useExisting"
                    ),
                    originals_subfolder=(
                        row.originals_subfolder if first_language_for_target else None
                    ),
                    # Notes belong to the shared Sound object, not to one
                    # localized AudioFileSource.  Set them only while creating
                    # the absent baseline target; later language rows must not
                    # replay a non-audio object mutation through useExisting.
                    notes=row.pre_state_notes if first_language_for_target else None,
                    audio_source_notes=None,
                )
            )
            setup_target_paths.add(target_key)

        self.backend.save_project()
        before = self.snapshot()
        before_business = _business_snapshot(before)
        failures = _validate_before(self.plan, before_business)
        failures.extend(
            _validate_saved_xml(self.plan, before_business, before=True)
        )
        if isinstance(before, ImportCompoundRuntimeSnapshot):
            failures.extend(
                _validate_reference_fixture_snapshot(
                    self.plan,
                    (before.reference_fixtures, before.main_bus),
                )
            )
        if failures:
            raise ImportRuntimeError(
                f"{self.plan.scenario_id} fixture setup proof failed: "
                + "; ".join(failures)
            )
        self.hidden_before = before
        return self

    def snapshot(
        self, *, save: bool = False
    ) -> ImportRuntimeSnapshot | ImportCompoundRuntimeSnapshot:
        if self._closed:
            raise ImportRuntimeError("import runtime is closed")
        if save:
            self.backend.save_project()
        business = self._snapshot_business()
        if self.plan.metadata_binding is None:
            return business
        fixtures, main_bus = self._snapshot_reference_fixtures()
        return ImportCompoundRuntimeSnapshot(
            scenario_id=self.plan.scenario_id,
            business=business,
            rows=tuple(
                self._snapshot_compound_row(
                    row,
                    business.row(row.row_key),
                )
                for row in self.plan.rows
            ),
            reference_fixtures=fixtures,
            main_bus=main_bus,
        )

    def _snapshot_business(self) -> ImportRuntimeSnapshot:
        rows = tuple(self._snapshot_row(row) for row in self.plan.rows)
        events = tuple(self._snapshot_event(path) for path in self.plan.event_paths)
        xml_files = _tree_proofs(
            self.plan.sandbox_root,
            include=lambda path: path.suffix.casefold() in {".wproj", ".wwu"},
            limit=MAX_PROJECT_XML_FILES,
        )
        originals = _tree_proofs(
            self.plan.sandbox_root,
            include=_is_originals_file,
            limit=MAX_TREE_FILES,
        )
        identities = _xml_identity_evidence(
            self.plan.sandbox_root,
            xml_files,
        )
        return ImportRuntimeSnapshot(
            scenario_id=self.plan.scenario_id,
            rows=rows,
            events=events,
            project_xml_files=xml_files,
            originals_files=originals,
            input_files=_input_file_state(self.materialized),
            xml_identities=identities,
        )

    def verify_preview_unchanged(self) -> ImportRuntimeVerification:
        before = self._require_before()
        after = self.snapshot()
        failures = _snapshot_drift(before, after)
        return ImportRuntimeVerification(
            scenario_id=self.plan.scenario_id,
            phase="preview",
            passed=not failures,
            failures=tuple(failures),
            before=before,
            after=after,
        )

    def verify_zero_dispatch_unchanged(self) -> ImportRuntimeVerification:
        if self.plan.expected_primary_dispatch_count != 0:
            raise ImportRuntimeError(
                "zero-dispatch verification is only valid for a refusal scenario"
            )
        before = self._require_before()
        after = self.snapshot()
        failures = _snapshot_drift(before, after)
        return ImportRuntimeVerification(
            scenario_id=self.plan.scenario_id,
            phase="zero_dispatch",
            passed=not failures,
            failures=tuple(failures),
            before=before,
            after=after,
        )

    def verify_after_execution(self) -> ImportRuntimeVerification:
        if self.plan.expected_primary_dispatch_count == 0:
            raise ImportRuntimeError(
                "zero-dispatch refusal must use verify_zero_dispatch_unchanged"
            )
        before = self._require_before()
        after = self.snapshot(save=True)
        before_business = _business_snapshot(before)
        after_business = _business_snapshot(after)
        failures = _validate_after(
            self.plan,
            before_business,
            after_business,
            self.backend,
        )
        failures.extend(
            _validate_saved_xml(
                self.plan,
                after_business,
                before=False,
                old=before_business,
            )
        )
        failures.extend(_validate_inputs_unchanged(before_business, after_business))
        if self.plan.metadata_binding is not None:
            if (
                not isinstance(before, ImportCompoundRuntimeSnapshot)
                or not isinstance(after, ImportCompoundRuntimeSnapshot)
            ):
                failures.append("compound import lost its dynamic-field snapshot")
            else:
                failures.extend(_validate_compound_after(self.plan, before, after))
        return ImportRuntimeVerification(
            scenario_id=self.plan.scenario_id,
            phase="after_execution",
            passed=not failures,
            failures=tuple(failures),
            before=before,
            after=after,
        )

    def cleanup_success(self, *, remove_assets: bool = True) -> ImportRuntimeCleanup:
        if self._closed:
            raise ImportRuntimeError("import runtime is already closed")
        root_paths = tuple(
            parent.path
            for parent in self.plan.parents
            if parent.parent_path in {self.plan.actor_dwu, self.plan.events_dwu}
        )
        for path in sorted(root_paths, key=_path_depth, reverse=True):
            object_id = self._created_parent_ids.get(path)
            if object_id is None:
                raise ImportRuntimeError(f"owned cleanup root lacks an identity: {path}")
            self.backend.cleanup_delete(object_id)
        self.backend.save_project()
        absent = all(
            not self.backend.read_objects(path=path, fields=EVENT_FIELDS)
            for path in root_paths
        )
        if not absent:
            raise ImportRuntimeError("import fixture cleanup left owned object roots")

        if self.reference_fixtures is not None:
            reference_cleanup = self.reference_fixtures._cleanup_adopted()
            if not reference_cleanup.paths_absent:
                raise ImportRuntimeError(
                    "import fixture cleanup left owned reference Bus fixtures"
                )

        assets_removed = not self.plan.asset_root.exists()
        if remove_assets and self.plan.asset_root.exists():
            _assert_safe_asset_cleanup_root(self.plan.asset_root, self.plan.sandbox_root)
            shutil.rmtree(self.plan.asset_root)
            assets_removed = not self.plan.asset_root.exists()
            if not assets_removed:
                raise ImportRuntimeError("import fixture asset root was not removed")
        self._closed = True
        return ImportRuntimeCleanup(
            scenario_id=self.plan.scenario_id,
            deleted_root_paths=root_paths,
            assets_removed=assets_removed,
            paths_absent=absent,
        )

    def _cleanup_failed_prepare(self) -> tuple[str, ...]:
        """Best-effort rollback after fixture ownership has transferred.

        ``prepare_import_runtime`` adopts compound Bus fixtures immediately
        before calling ``prepare``.  A failure inside ``prepare`` therefore
        cannot be delegated back to the pre-adoption emergency cleanup lane.
        Keep rollback internal so callers never receive a handle whose cleanup
        ownership is stranded between the two phases.
        """

        failures: list[str] = []
        root_paths = tuple(
            parent.path
            for parent in self.plan.parents
            if parent.parent_path in {self.plan.actor_dwu, self.plan.events_dwu}
        )
        for path in sorted(root_paths, key=_path_depth, reverse=True):
            object_id = self._created_parent_ids.get(path)
            if object_id is None:
                continue
            try:
                if self.backend.read_objects(path=path, fields=EVENT_FIELDS):
                    self.backend.cleanup_delete(object_id)
            except Exception as exc:  # pragma: no cover - real failure quarantine
                failures.append(f"owned root {path}: {exc}")
        try:
            self.backend.save_project()
        except Exception as exc:  # pragma: no cover - real failure quarantine
            failures.append(f"project save after owned-root cleanup: {exc}")

        if self.reference_fixtures is not None:
            try:
                self.reference_fixtures._cleanup_adopted()
            except Exception as exc:  # pragma: no cover - real failure quarantine
                failures.append(f"reference Bus cleanup: {exc}")

        if self.plan.asset_root.exists():
            try:
                _assert_safe_asset_cleanup_root(
                    self.plan.asset_root,
                    self.plan.sandbox_root,
                )
                shutil.rmtree(self.plan.asset_root)
            except Exception as exc:  # pragma: no cover - real failure quarantine
                failures.append(f"asset cleanup: {exc}")
        self._closed = True
        return tuple(failures)

    def _require_before(
        self,
    ) -> ImportRuntimeSnapshot | ImportCompoundRuntimeSnapshot:
        if self.hidden_before is None:
            raise ImportRuntimeError("import runtime fixture has not been prepared")
        return self.hidden_before

    def _snapshot_reference_fixtures(
        self,
    ) -> tuple[
        tuple[ImportReferenceFixtureState, ...],
        ImportReferenceFixtureState,
    ]:
        if self.reference_fixtures is None:
            raise ImportRuntimeError("compound reference fixtures are unavailable")
        fixtures: list[ImportReferenceFixtureState] = []
        for expected in self.reference_fixtures.fixtures:
            rows = self.backend.read_objects(path=expected.path, fields=EVENT_FIELDS)
            if len(rows) != 1:
                raise ImportRuntimeError(
                    f"reference Bus did not resolve exactly once: {expected.path}"
                )
            fixtures.append(
                _reference_fixture_state(
                    expected.key,
                    expected.path,
                    rows[0],
                    expected_type="Bus",
                )
            )
        main = self.reference_fixtures.main_bus
        main_rows = self.backend.read_objects(path=main.path, fields=EVENT_FIELDS)
        if len(main_rows) != 1:
            raise ImportRuntimeError(
                f"default main Bus did not resolve exactly once: {main.path}"
            )
        return tuple(fixtures), _reference_fixture_state(
            main.key,
            main.path,
            main_rows[0],
            expected_type="Bus",
        )

    def _snapshot_compound_row(
        self,
        plan: ImportRowPlan,
        business_row: ImportRowState,
    ) -> ImportCompoundRowState:
        property_tokens = (
            tuple(item.name for item in plan.expected_properties)
            or plan.preserve_property_tokens
        )
        reference_tokens = (
            tuple(item.name for item in plan.expected_references)
            or plan.preserve_reference_tokens
        )
        names = _unique(
            property_tokens + reference_tokens
        )
        if not names:
            return ImportCompoundRowState(
                row_key=plan.row_key,
                target_path=plan.target_path,
                properties=(),
                references=(),
            )
        rows = self.backend.read_bound_values(path=plan.target_path, names=names)
        if len(rows) > 1:
            raise ImportRuntimeError(
                f"compound target resolved more than once: {plan.target_path}"
            )
        if not rows:
            if plan.preserve_property_tokens or plan.preserve_reference_tokens:
                raise ImportRuntimeError(
                    f"preserved compound target is absent: {plan.target_path}"
                )
            return ImportCompoundRowState(
                row_key=plan.row_key,
                target_path=plan.target_path,
                properties=(),
                references=(),
            )
        raw = rows[0]
        raw_id = _identity_value(raw.get("id"))
        raw_path = raw.get("path")
        business_object = business_row.object
        if (
            business_object is None
            or raw_path != plan.target_path
            or not _same_guid(raw_id, business_object.id)
        ):
            raise ImportRuntimeError(
                f"compound bound-value identity/path differs from business row: "
                f"{plan.target_path}"
            )
        missing_tokens = [
            name
            for name in names
            if name not in raw and f"@{name}" not in raw
        ]
        if missing_tokens:
            raise ImportRuntimeError(
                f"compound bound-value read omitted tokens: {missing_tokens}"
            )
        properties = tuple(
            ImportPropertyState(name, _field_value(raw, name))
            for name in property_tokens
        )
        if plan.preserve_property_tokens and any(
            not _is_json_scalar(item.value) for item in properties
        ):
            raise ImportRuntimeError(
                f"preserved compound property readback is not JSON-scalar: "
                f"{plan.target_path}"
            )
        references: list[ImportReferenceState] = []
        for name in reference_tokens:
            raw_value = _field_value(raw, name)
            target_id = _identity_value(raw_value)
            if (
                plan.preserve_reference_tokens
                and raw_value is not None
                and target_id is None
            ):
                raise ImportRuntimeError(
                    f"preserved compound reference readback is not a GUID/null: "
                    f"{plan.target_path} @{name}"
                )
            references.append(ImportReferenceState(name, target_id))
        return ImportCompoundRowState(
            row_key=plan.row_key,
            target_path=plan.target_path,
            properties=properties,
            references=tuple(references),
        )

    def _snapshot_row(self, plan: ImportRowPlan) -> ImportRowState:
        rows = self.backend.read_objects(
            path=plan.target_path,
            fields=(
                OBJECT_FIELDS_2021
                if self.plan.version == "2021.1"
                else OBJECT_FIELDS
            ),
            language=plan.language,
        )
        if len(rows) > 1:
            raise ImportRuntimeError(
                f"import target path resolved more than once: {plan.target_path}"
            )
        value = None if not rows else self._object_state(rows[0], plan.language)
        return ImportRowState(
            row_key=plan.row_key,
            target_path=plan.target_path,
            language=plan.language,
            object=value,
        )

    def _object_state(
        self, row: Mapping[str, Any], language: str
    ) -> ImportObjectState:
        object_id = _required_guid(row.get("id"), "object id")
        path = _required_wwise_path(row.get("path"), "object path")
        active_source = _identity_value(_field_value(row, "activeSource"))
        source_state: ImportAudioSourceState | None = None
        if self.plan.version == "2021.1":
            direct_sources = tuple(
                source
                for source in self.backend.read_direct_children(
                    object_id,
                    fields=AUDIO_SOURCE_FIELDS_2021,
                )
                if _object_type_matches(source.get("type"), "AudioFileSource")
                and _same_guid(_identity_value(source.get("parent")), object_id)
                and _language_name(_field_value(source, "audioSource:language"))
                == language
            )
            if len(direct_sources) != 1:
                raise ImportRuntimeError(
                    "2021 import target must have exactly one direct AudioFileSource "
                    f"for {language}: {path}"
                )
            active_source = _required_guid(
                direct_sources[0].get("id"),
                "2021 direct Audio Source id",
            )
        if active_source is not None:
            source_rows = (
                direct_sources
                if self.plan.version == "2021.1"
                else self.backend.read_objects(
                    object_id=active_source,
                    fields=AUDIO_SOURCE_FIELDS,
                    language=language,
                )
            )
            if len(source_rows) != 1:
                raise ImportRuntimeError(
                    f"active Audio Source {active_source} did not resolve exactly once"
                )
            source = source_rows[0]
            source_id = _required_guid(source.get("id"), "Audio Source id")
            copied = _field_value(source, "originalFilePath")
            if copied is None:
                copied = _field_value(source, "originalWavFilePath")
            if copied is None:
                copied = _field_value(row, "originalFilePath")
            if copied is None:
                copied = _field_value(row, "sound:originalWavFilePath")
            proof, original_relative_path = _copied_original_evidence(
                copied,
                project_root=self.plan.sandbox_root,
            )
            actual_language = _language_name(
                _field_value(source, "audioSource:language")
            )
            if actual_language is None:
                actual_language = _language_name(
                    _field_value(row, "audioSource:language")
                )
            source_state = ImportAudioSourceState(
                id=source_id,
                language=actual_language or "",
                notes=_optional_text(_field_value(source, "notes")),
                original_file=proof,
                original_relative_path=original_relative_path,
            )
        return ImportObjectState(
            id=object_id,
            name=_required_text(row.get("name"), "object name"),
            type=_required_text(row.get("type"), "object type"),
            path=path,
            parent_id=_identity_value(row.get("parent")),
            notes=_optional_text(_field_value(row, "notes")),
            audio_source=source_state,
        )

    def _snapshot_event(self, path: str) -> ImportEventState:
        rows = self.backend.read_objects(path=path, fields=EVENT_FIELDS)
        if len(rows) > 1:
            raise ImportRuntimeError(f"Event path resolved more than once: {path}")
        if not rows:
            return ImportEventState(path, None, None, None, None, 0)
        event_id = _required_guid(rows[0].get("id"), "Event id")
        children = self.backend.read_direct_children(event_id, fields=ACTION_FIELDS)
        if len(children) == 1:
            child = children[0]
            action_id = _required_guid(child.get("id"), "Action id")
            action_type = _integer_value(_field_value(child, "ActionType"))
            target = _field_value(child, "Target")
        else:
            action_id = None
            action_type = None
            target = None
        return ImportEventState(
            path=path,
            id=event_id,
            action_id=action_id,
            action_type=action_type,
            target=target,
            child_count=len(children),
        )


def build_import_runtime_plan(
    scenario: OnlineScenario,
    materialized: MaterializedImportCase,
    *,
    sandbox_project: str | Path,
    reference_fixtures: PreparedImportReferenceFixtures | None = None,
) -> ImportRuntimePlan:
    """Bind reviewed rows and immutable files without making a live call."""

    if scenario.api not in IMPORT_APIS:
        raise ImportRuntimeError(f"unsupported import runtime API: {scenario.api}")
    if len(scenario.versions) != 1:
        raise ImportRuntimeError("import runtime requires one exact Wwise version")
    version = scenario.versions[0]
    compound = materialized.compound_spec is not None
    if not import_runtime_version_is_reviewed(
        scenario.id,
        version,
        compound=compound,
    ):
        raise ImportRuntimeError(
            f"{scenario.id} import runtime does not support Wwise {version}"
        )
    if compound:
        if materialized.requires_metadata_binding or materialized.metadata_binding is None:
            raise ImportRuntimeError(
                "compound import runtime requires a completed live metadata binding"
            )
        if reference_fixtures is None:
            raise ImportRuntimeError(
                "compound import runtime requires prepared reference Bus fixtures"
            )
        _validate_reference_fixture_handle(
            reference_fixtures,
            scenario=scenario,
            materialized=materialized,
        )
    elif reference_fixtures is not None:
        raise ImportRuntimeError(
            "ordinary 2022 import cases cannot adopt reference Bus fixtures"
        )
    if scenario.id != materialized.scenario_id:
        raise ImportRuntimeError("scenario/materialized import identity mismatch")
    if materialized.expected_primary_dispatch_count != scenario.primary_dispatch.count:
        raise ImportRuntimeError("materialized primary dispatch count drifted")
    project_input = Path(sandbox_project).expanduser()
    if project_input.is_symlink():
        raise ImportRuntimeError("sandbox_project must not be a symlink")
    project = project_input.resolve(strict=True)
    if not project.is_file() or project.suffix.casefold() != ".wproj":
        raise ImportRuntimeError("sandbox_project must be a real .wproj file")
    sandbox_root = project.parent
    asset_root = _derive_asset_root(materialized)
    source_by_key = {item.key: item for item in materialized.source_files}
    pre_by_key = {item.key: item for item in materialized.pre_state_files}
    if len(source_by_key) != len(materialized.source_files):
        raise ImportRuntimeError("materialized source keys are not unique")
    if len(pre_by_key) != len(materialized.pre_state_files):
        raise ImportRuntimeError("materialized pre-state keys are not unique")
    try:
        layout = get_codex_version_layout_v3(version)
    except CodexVersionLayoutError as exc:
        raise ImportRuntimeError(str(exc)) from exc

    asset_spec = scenario.fixture.get("asset_spec")
    if not isinstance(asset_spec, Mapping):
        raise ImportRuntimeError("scenario import asset specification is missing")
    if scenario.api == "ak.wwise.core.audio.import":
        if len(materialized.operation_requests) != 1:
            raise ImportRuntimeError(
                "audio.import runtime requires one sealed operation request"
            )
        arguments = materialized.operation_requests[0].get("arguments")
        if not isinstance(arguments, Mapping):
            raise ImportRuntimeError("audio.import request arguments are missing")
        direct_operation = _required_text(
            arguments.get("import_operation"),
            "audio.import request import_operation",
        )
        operation_by_table = {"__audio_import__": direct_operation}
        tab_import_location = None
    else:
        raw_tables = asset_spec.get("tsv")
        if not isinstance(raw_tables, list):
            raise ImportRuntimeError("tab import table specification is missing")
        tab_import_location = _tab_import_location(materialized)
        operation_by_table = {}
        for index, table in enumerate(raw_tables):
            if not isinstance(table, Mapping):
                raise ImportRuntimeError(f"tsv[{index}] must be an object")
            table_name = _required_text(table.get("name"), f"tsv[{index}].name")
            operation_by_table[table_name] = _required_text(
                table.get("import_operation"),
                f"tsv[{index}].import_operation",
            )
    if (
        len(operation_by_table) == 0
        or any(
            operation not in {"createNew", "useExisting", "replaceExisting"}
            for operation in operation_by_table.values()
        )
    ):
        raise ImportRuntimeError("reviewed import operations are malformed")

    parent_types: dict[str, str] = {}
    if tab_import_location is not None:
        # A tab-delimited Object Path is relative to importLocation.  The table
        # owns every relative ancestor and Wwise must create those ancestors as
        # part of the primary dispatch.  Pre-creating them in fixture setup
        # makes createNew resolve the collision by appending ``_01``.  Prepare
        # only the importLocation itself (and its ancestors); existing target
        # baselines add their deeper parents below.
        _collect_parent_types(
            tab_import_location + "\\__waapi_skill_import_leaf__",
            root=layout.actor_default_work_unit,
            typed={},
            destination=parent_types,
        )
    rows: list[ImportRowPlan] = []
    event_paths: list[str] = []
    for raw in materialized.expected_rows:
        row_key = _required_text(raw.get("row_key"), "row_key")
        source_key = _required_text(raw.get("source_key"), f"{row_key}.source_key")
        try:
            source_file = source_by_key[source_key]
        except KeyError as exc:
            raise ImportRuntimeError(
                f"{row_key} references an unknown materialized source"
            ) from exc
        target_path = _required_wwise_path(raw.get("target_path"), f"{row_key}.target_path")
        object_type = _required_text(raw.get("object_type"), f"{row_key}.object_type")
        language = canonical_wwise_language(
            _required_text(raw.get("language"), f"{row_key}.language")
        )
        typed = _typed_path_map(raw.get("object_path"), target_path=target_path)
        if tab_import_location is None:
            _collect_parent_types(
                target_path,
                root=layout.actor_default_work_unit,
                typed=typed,
                destination=parent_types,
            )
        elif not target_path.casefold().startswith(
            (tab_import_location + "\\").casefold()
        ):
            raise ImportRuntimeError(
                f"{row_key}.target_path is outside import_location"
            )
        setup_object_path = _typed_final_path(target_path, object_type)
        pre_state = raw.get("pre_state")
        if not isinstance(pre_state, Mapping):
            raise ImportRuntimeError(f"{row_key}.pre_state must be an object")
        existence = _required_text(
            pre_state.get("existence"), f"{row_key}.pre_state.existence"
        )
        if tab_import_location is not None and existence == "existing":
            _collect_parent_types(
                target_path,
                root=layout.actor_default_work_unit,
                typed=typed,
                destination=parent_types,
            )
        media_key = pre_state.get("media_sha256_key")
        if media_key is None:
            pre_file = None
        else:
            try:
                pre_file = pre_by_key[
                    _required_text(media_key, f"{row_key}.pre_state.media_sha256_key")
                ]
            except KeyError as exc:
                raise ImportRuntimeError(
                    f"{row_key} references an unknown pre-state media proof"
                ) from exc
        event = raw.get("event")
        if event is None:
            event_path = None
            event_action = None
        elif isinstance(event, Mapping):
            event_path = _required_wwise_path(
                event.get("path"), f"{row_key}.event.path"
            )
            event_action = _required_text(
                event.get("action"), f"{row_key}.event.action"
            )
            if event_action != "Play":
                raise ImportRuntimeError(
                    "the ten core import cases only review Play Event actions"
                )
            event_paths.append(event_path)
            _collect_parent_types(
                event_path,
                root=EVENTS_DWU,
                typed={},
                destination=parent_types,
            )
        else:
            raise ImportRuntimeError(f"{row_key}.event must be null or an object")
        guid_key = pre_state.get("guid_key")
        table_key = (
            "__audio_import__"
            if scenario.api == "ak.wwise.core.audio.import"
            else _required_text(raw.get("tsv_name"), f"{row_key}.tsv_name")
        )
        try:
            import_operation = operation_by_table[table_key]
        except KeyError as exc:
            raise ImportRuntimeError(
                f"{row_key} references an unknown import operation"
            ) from exc
        originals_subfolder = _optional_text(raw.get("originals_subfolder"))
        if (
            language == "SFX"
            and originals_subfolder is not None
            and re.split(r"[\\/]", originals_subfolder, maxsplit=1)[0].casefold()
            == "sfx"
        ):
            raise ImportRuntimeError(
                f"{row_key}.originals_subfolder must be relative to Wwise's "
                "automatic Originals/SFX base"
            )
        requested_notes = _optional_text(raw.get("notes"))
        requested_audio_source_notes = _optional_text(
            raw.get("audio_source_notes")
        )
        expected_properties, expected_references = _row_dynamic_expectations(
            materialized,
            raw,
            reference_fixtures=reference_fixtures,
        )
        guid_policy = _required_text(
            raw.get("guid_policy"),
            f"{row_key}.guid_policy",
        )
        preserve_property_tokens: tuple[str, ...] = ()
        preserve_reference_tokens: tuple[str, ...] = ()
        if raw.get("compound_dynamic_mode") == "preserve":
            if (
                scenario.api != "ak.wwise.core.audio.importTabDelimited"
                or import_operation != "useExisting"
                or existence != "existing"
                or guid_policy != "preserve_existing_guid"
                or expected_properties
                or expected_references
            ):
                raise ImportRuntimeError(
                    f"{row_key} compound preserve mode is only valid for an "
                    "existing useExisting tab-import row with a preserved GUID"
                )
            if (
                pre_file is None
                or not pre_file.present
                or not isinstance(pre_file.sha256, str)
                or not source_file.present
                or not isinstance(source_file.sha256, str)
            ):
                raise ImportRuntimeError(
                    f"{row_key} compound preserve row lacks sealed old/new media"
                )
            if pre_file.sha256 == source_file.sha256:
                raise ImportRuntimeError(
                    f"{row_key} compound preserve row old/new media hashes are equal"
                )
            (
                preserve_property_tokens,
                preserve_reference_tokens,
            ) = _live_bound_preservation_tokens(materialized.metadata_binding)
        if (
            existence == "existing"
            and import_operation == "useExisting"
            and requested_notes is not None
            and requested_audio_source_notes is not None
        ):
            raise ImportRuntimeError(
                f"{row_key} cannot seal both Notes fields onto one existing "
                "useExisting AudioFileSource"
            )
        rows.append(
            ImportRowPlan(
                row_key=row_key,
                target_path=target_path,
                setup_object_path=setup_object_path,
                object_type=object_type,
                language=language,
                source_file=source_file,
                pre_state_file=pre_file,
                pre_state_existence=existence,
                pre_state_guid_key=(
                    None
                    if guid_key is None
                    else _required_text(guid_key, f"{row_key}.pre_state.guid_key")
                ),
                pre_state_notes=_optional_text(pre_state.get("notes")),
                import_operation=import_operation,
                guid_policy=guid_policy,
                originals_subfolder=originals_subfolder,
                notes=requested_notes,
                audio_source_notes=requested_audio_source_notes,
                event_path=event_path,
                event_action=event_action,
                expected_properties=expected_properties,
                expected_references=expected_references,
                preserve_property_tokens=preserve_property_tokens,
                preserve_reference_tokens=preserve_reference_tokens,
            )
        )

    parents = tuple(
        ImportParentPlan(
            path=path,
            parent_path=path.rsplit("\\", 1)[0],
            name=path.rsplit("\\", 1)[1],
            object_type=parent_types[path],
        )
        for path in sorted(parent_types, key=lambda value: (_path_depth(value), value))
    )
    return ImportRuntimePlan(
        scenario_id=scenario.id,
        api=scenario.api,
        version=version,
        sandbox_project=project,
        sandbox_root=sandbox_root,
        asset_root=asset_root,
        parents=parents,
        rows=tuple(rows),
        event_paths=_unique(event_paths),
        operation_requests=tuple(
            MappingProxyType(dict(request)) for request in materialized.operation_requests
        ),
        visible_values=MappingProxyType(dict(materialized.visible_values)),
        expected_primary_dispatch_count=materialized.expected_primary_dispatch_count,
        actor_dwu=layout.actor_default_work_unit,
        events_dwu=EVENTS_DWU,
        main_bus_path=(
            reference_fixtures.main_bus.path
            if reference_fixtures is not None
            else None
        ),
        main_bus_id=(
            reference_fixtures.main_bus.id
            if reference_fixtures is not None
            else None
        ),
        reference_fixtures=(
            reference_fixtures.fixtures
            if reference_fixtures is not None
            else ()
        ),
        metadata_binding=(
            _freeze_mapping(materialized.metadata_binding)
            if materialized.metadata_binding is not None
            else None
        ),
    )


def prepare_import_runtime(
    scenario: OnlineScenario,
    materialized: MaterializedImportCase,
    *,
    sandbox_project: str | Path,
    backend: ImportRuntimeBackend,
    reference_fixtures: PreparedImportReferenceFixtures | None = None,
) -> PreparedImportRuntime:
    """Set up and seal one import fixture on an already-running Wwise copy."""

    plan = build_import_runtime_plan(
        scenario,
        materialized,
        sandbox_project=sandbox_project,
        reference_fixtures=reference_fixtures,
    )
    runtime = PreparedImportRuntime(
        scenario=scenario,
        materialized=materialized,
        plan=plan,
        backend=backend,
        reference_fixtures=reference_fixtures,
    )
    if reference_fixtures is not None:
        reference_fixtures.adopt(
            scenario=scenario,
            materialized=materialized,
        )
    try:
        return runtime.prepare()
    except Exception as setup_error:
        cleanup_failures = runtime._cleanup_failed_prepare()
        if cleanup_failures:
            raise ImportRuntimeError(
                "import fixture setup failed "
                f"({setup_error}); adopted fixture rollback failed: "
                + "; ".join(cleanup_failures)
            ) from setup_error
        raise


def _tab_import_location(materialized: MaterializedImportCase) -> str:
    locations: set[str] = set()
    for request in materialized.operation_requests:
        arguments = request.get("arguments")
        location = arguments.get("import_location") if isinstance(arguments, Mapping) else None
        if (
            not isinstance(location, Mapping)
            or set(location) != {"kind", "value"}
            or location.get("kind") != "path"
        ):
            raise ImportRuntimeError(
                "tab import request lacks one closed path import_location"
            )
        locations.add(
            _required_wwise_path(
                location.get("value"),
                "tab import request import_location",
            )
        )
    if len(locations) != 1:
        raise ImportRuntimeError(
            "tab import requests do not share one exact import_location"
        )
    return locations.pop()


def _row_dynamic_expectations(
    materialized: MaterializedImportCase,
    row: Mapping[str, Any],
    *,
    reference_fixtures: PreparedImportReferenceFixtures | None,
) -> tuple[
    tuple[ImportPropertyExpectation, ...],
    tuple[ImportReferenceExpectation, ...],
]:
    if materialized.compound_spec is None:
        if any(
            key in row
            for key in (
                "compound_effective_properties",
                "compound_effective_references",
                "compound_media_kind",
                "compound_dynamic_mode",
            )
        ):
            raise ImportRuntimeError(
                "ordinary import row unexpectedly contains compound expectations"
            )
        return (), ()
    if reference_fixtures is None:
        raise ImportRuntimeError(
            "compound dynamic expectations require reference fixtures"
        )
    binding = materialized.metadata_binding
    if not isinstance(binding, Mapping):
        raise ImportRuntimeError("compound metadata binding is unavailable")
    selected = binding.get("selected")
    bound_targets = binding.get("reference_targets")
    if not isinstance(selected, Mapping) or not isinstance(bound_targets, Mapping):
        raise ImportRuntimeError("compound metadata binding is malformed")

    selected_property_names: set[str] = set()
    selected_reference_names: set[str] = set()
    dependency_names: set[str] = set()
    for value in selected.values():
        if not isinstance(value, Mapping):
            raise ImportRuntimeError("compound selected metadata row is malformed")
        name = _validated_dynamic_token(value.get("name"))
        kind = value.get("kind")
        if kind == "property":
            selected_property_names.add(name)
        elif kind == "reference":
            selected_reference_names.add(name)
        else:
            raise ImportRuntimeError("compound selected metadata kind is unsupported")
        dependencies = value.get("same_object_dependencies")
        if not isinstance(dependencies, list):
            raise ImportRuntimeError("compound dependency metadata is malformed")
        for dependency in dependencies:
            if not isinstance(dependency, Mapping):
                raise ImportRuntimeError("compound dependency row is malformed")
            dependency_names.add(_validated_dynamic_token(dependency.get("name")))

    raw_properties = row.get("compound_effective_properties")
    raw_references = row.get("compound_effective_references")
    row_key = _required_text(row.get("row_key"), "compound row_key")
    dynamic_modes = compound_dynamic_modes_by_row(
        materialized.compound_spec,
        materialized.expected_rows,
    )
    sealed_mode = row.get("compound_dynamic_mode")
    expected_mode = dynamic_modes.get(row_key)
    if (
        sealed_mode not in {"mutate", "preserve"}
        or sealed_mode != expected_mode
    ):
        raise ImportRuntimeError(
            f"{row_key} compound dynamic mode differs from the reviewed case spec"
        )
    if not isinstance(raw_properties, list) or not isinstance(raw_references, list):
        raise ImportRuntimeError(
            "bound compound row lacks dynamic property/reference expectations"
        )
    properties: list[ImportPropertyExpectation] = []
    seen_properties: set[str] = set()
    for raw in raw_properties:
        if not isinstance(raw, Mapping) or set(raw) != {
            "name",
            "value",
            "metadata_type",
            "source",
        }:
            raise ImportRuntimeError("compound property expectation is not closed")
        name = _validated_dynamic_token(raw.get("name"))
        source = _required_text(raw.get("source"), f"{name}.source")
        allowed_names = (
            dependency_names
            if source == "reference_dependency"
            else selected_property_names
        )
        if name not in allowed_names:
            raise ImportRuntimeError(
                f"compound property {name!r} is absent from live metadata binding"
            )
        value = raw.get("value")
        if not _is_json_scalar(value):
            raise ImportRuntimeError(
                f"compound property {name!r} has a non-scalar expected value"
            )
        if source == "reference_dependency" and value is not True:
            raise ImportRuntimeError(
                f"compound activation property {name!r} must be exactly true"
            )
        metadata_type = _required_text(
            raw.get("metadata_type"),
            f"{name}.metadata_type",
        )
        key = name.casefold()
        if key in seen_properties:
            raise ImportRuntimeError(
                f"compound row repeats property expectation {name!r}"
            )
        seen_properties.add(key)
        properties.append(
            ImportPropertyExpectation(
                name=name,
                value=value,
                metadata_type=metadata_type,
                source=source,
            )
        )

    fixtures_by_key = {item.key: item for item in reference_fixtures.fixtures}
    references: list[ImportReferenceExpectation] = []
    seen_references: set[str] = set()
    for raw in raw_references:
        if not isinstance(raw, Mapping) or set(raw) != {
            "name",
            "target",
            "target_fixture",
            "activation_properties",
        }:
            raise ImportRuntimeError("compound reference expectation is not closed")
        name = _validated_dynamic_token(raw.get("name"))
        if name not in selected_reference_names:
            raise ImportRuntimeError(
                f"compound reference {name!r} is absent from live metadata binding"
            )
        fixture_key = _required_text(
            raw.get("target_fixture"),
            f"{name}.target_fixture",
        )
        fixture = fixtures_by_key.get(fixture_key)
        target = raw.get("target")
        if (
            fixture is None
            or not isinstance(target, Mapping)
            or set(target) != {"kind", "value"}
            or target.get("kind") != "path"
            or target.get("value") != fixture.path
        ):
            raise ImportRuntimeError(
                f"compound reference {name!r} target is not its reviewed Bus path"
            )
        bound_target = bound_targets.get(fixture_key)
        if (
            not isinstance(bound_target, Mapping)
            or set(bound_target) != {"kind", "value"}
            or bound_target.get("kind") != "path"
            or bound_target.get("value") != fixture.path
        ):
            raise ImportRuntimeError(
                f"compound reference fixture {fixture_key!r} differs from metadata binding"
            )
        activation_names: list[str] = []
        activation = raw.get("activation_properties")
        if not isinstance(activation, list) or not activation:
            raise ImportRuntimeError(
                f"compound reference {name!r} lacks activation-property evidence"
            )
        for value in activation:
            if not isinstance(value, Mapping):
                raise ImportRuntimeError(
                    f"compound reference {name!r} activation row is malformed"
                )
            activation_name = _validated_dynamic_token(value.get("name"))
            if activation_name not in dependency_names or value.get("value") is not True:
                raise ImportRuntimeError(
                    f"compound reference {name!r} activation property is not live-bound"
                )
            activation_names.append(activation_name)
        property_by_name = {item.name.casefold(): item for item in properties}
        activation_expectations: list[ImportPropertyExpectation] = []
        for activation_name in activation_names:
            expected = property_by_name.get(activation_name.casefold())
            if expected is None or expected.value is not True:
                raise ImportRuntimeError(
                    f"compound reference {name!r} activation property is not expected"
                )
            activation_expectations.append(expected)
        key = name.casefold()
        if key in seen_references:
            raise ImportRuntimeError(
                f"compound row repeats reference expectation {name!r}"
            )
        seen_references.add(key)
        references.append(
            ImportReferenceExpectation(
                name=name,
                target_id=fixture.id,
                target_fixture=fixture.key,
                activation_properties=tuple(activation_expectations),
            )
        )
    if bool(properties) != bool(references):
        raise ImportRuntimeError(
            "compound import row must seal property and reference expectations "
            "together or omit both"
        )
    if sealed_mode == "mutate" and not properties:
        raise ImportRuntimeError(
            f"{row_key} compound mutate row requires dynamic expectations"
        )
    if sealed_mode == "preserve" and properties:
        raise ImportRuntimeError(
            f"{row_key} compound preserve row must omit dynamic expectations"
        )
    return tuple(properties), tuple(references)


def _live_bound_preservation_tokens(
    binding: Mapping[str, Any] | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Derive the exact preserve oracle surface from one live metadata binding."""

    if not isinstance(binding, Mapping):
        raise ImportRuntimeError(
            "compound preserve mode requires a live metadata binding"
        )
    selected = binding.get("selected")
    if not isinstance(selected, Mapping) or not selected:
        raise ImportRuntimeError(
            "compound preserve metadata selection is unavailable"
        )

    property_names: list[str] = []
    reference_names: list[str] = []
    for value in selected.values():
        if not isinstance(value, Mapping):
            raise ImportRuntimeError(
                "compound preserve selected metadata row is malformed"
            )
        name = _validated_dynamic_token(value.get("name"))
        kind = value.get("kind")
        if kind == "property":
            property_names.append(name)
        elif kind == "reference":
            reference_names.append(name)
        else:
            raise ImportRuntimeError(
                "compound preserve selected metadata kind is unsupported"
            )
        dependencies = value.get("same_object_dependencies")
        if not isinstance(dependencies, list):
            raise ImportRuntimeError(
                "compound preserve dependency metadata is malformed"
            )
        for dependency in dependencies:
            if (
                not isinstance(dependency, Mapping)
                or dependency.get("kind") != "property"
            ):
                raise ImportRuntimeError(
                    "compound preserve dependency is not a property"
                )
            property_names.append(
                _validated_dynamic_token(dependency.get("name"))
            )

    properties = _unique(property_names)
    references = _unique(reference_names)
    if (
        not properties
        or not references
        or len(properties) + len(references) > MAX_DYNAMIC_FIELDS
        or set(name.casefold() for name in properties)
        & set(name.casefold() for name in references)
    ):
        raise ImportRuntimeError(
            "compound preserve metadata tokens are incomplete or ambiguous"
        )
    return properties, references


def _validate_reference_fixture_handle(
    handle: PreparedImportReferenceFixtures,
    *,
    scenario: OnlineScenario,
    materialized: MaterializedImportCase,
) -> None:
    if not isinstance(handle, PreparedImportReferenceFixtures):
        raise ImportRuntimeError("reference fixture handle has the wrong type")
    if handle.cleaned:
        raise ImportRuntimeError("reference fixture handle is already cleaned")
    if (
        handle.scenario_id != scenario.id
        or handle.version not in COMPOUND_SUPPORTED_VERSIONS
        or scenario.versions != (handle.version,)
        or materialized.scenario_id != handle.scenario_id
    ):
        raise ImportRuntimeError("reference fixture handle identity/version is misbound")
    if dict(materialized.reference_fixture_paths) != dict(handle.expected_paths):
        raise ImportRuntimeError("reference fixture paths differ from the staged case")
    if (
        _materialized_handle_fingerprint(materialized)
        != handle._materialized_fingerprint
    ):
        raise ImportRuntimeError(
            "reference fixture handle belongs to a different materialized asset set"
        )
    binding = materialized.metadata_binding
    if not isinstance(binding, Mapping):
        raise ImportRuntimeError("reference fixtures require a bound compound import")
    targets = binding.get("reference_targets")
    if (
        not isinstance(targets, Mapping)
        or set(targets) != set(handle.request_reference_targets)
    ):
        raise ImportRuntimeError("reference fixture target keys differ from metadata binding")
    for key, expected in handle.request_reference_targets.items():
        actual = targets.get(key)
        if (
            not isinstance(actual, Mapping)
            or set(actual) != {"kind", "value"}
            or actual.get("kind") != "path"
            or actual.get("value") != expected.get("value")
        ):
            raise ImportRuntimeError(
                f"reference fixture {key!r} path differs from metadata binding"
            )
    if (
        any(_same_guid(item.id, handle.main_bus.id) for item in handle.fixtures)
        or len({item.id.casefold() for item in handle.fixtures}) != len(handle.fixtures)
    ):
        raise ImportRuntimeError(
            "reference fixture GUIDs are not unique from the default main Bus"
        )


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    def freeze(item: Any) -> Any:
        if isinstance(item, Mapping):
            return MappingProxyType({str(key): freeze(child) for key, child in item.items()})
        if isinstance(item, list):
            return tuple(freeze(child) for child in item)
        if item is None or type(item) in {str, int, float, bool}:
            return item
        raise ImportRuntimeError(
            f"metadata binding contains non-JSON value {type(item).__name__}"
        )

    result = freeze(value)
    assert isinstance(result, Mapping)
    return result


def _materialized_handle_fingerprint(
    materialized: MaterializedImportCase,
) -> tuple[tuple[str, str, bool, int | None, str | None], ...]:
    return tuple(
        sorted(
            (
                item.key,
                str(item.path),
                item.present,
                item.size,
                item.sha256,
            )
            for item in (
                *materialized.source_files,
                *materialized.pre_state_files,
            )
        )
    )


def _validate_before(
    plan: ImportRuntimePlan, snapshot: ImportRuntimeSnapshot
) -> list[str]:
    failures: list[str] = []
    guid_by_key: dict[str, str] = {}
    for row_plan, row_state in zip(plan.rows, snapshot.rows, strict=True):
        state = row_state.object
        if row_plan.pre_state_existence == "absent":
            if state is not None:
                failures.append(f"{row_plan.row_key} expected an absent baseline")
            continue
        if row_plan.pre_state_existence != "existing":
            failures.append(
                f"{row_plan.row_key} has unsupported pre-state {row_plan.pre_state_existence!r}"
            )
            continue
        if state is None:
            failures.append(f"{row_plan.row_key} existing baseline did not resolve")
            continue
        if not _object_type_matches(state.type, row_plan.object_type):
            failures.append(f"{row_plan.row_key} baseline type mismatch")
        if state.notes != row_plan.pre_state_notes:
            failures.append(f"{row_plan.row_key} baseline Notes mismatch")
        if state.audio_source is None or row_plan.pre_state_file is None:
            failures.append(f"{row_plan.row_key} baseline Audio Source is missing")
        else:
            if state.audio_source.language != row_plan.language:
                failures.append(f"{row_plan.row_key} baseline language mismatch")
            if state.audio_source.original_file.sha256 != row_plan.pre_state_file.sha256:
                failures.append(f"{row_plan.row_key} baseline media hash mismatch")
        if row_plan.pre_state_guid_key is None:
            failures.append(f"{row_plan.row_key} existing baseline lacks a GUID key")
        else:
            previous = guid_by_key.setdefault(row_plan.pre_state_guid_key, state.id)
            if not _same_guid(previous, state.id):
                failures.append(
                    f"{row_plan.row_key} shared baseline GUID key changed identity"
                )
    if any(event.id is not None for event in snapshot.events):
        failures.append("fixture Event controls were not absent before execution")
    return failures


def _validate_after(
    plan: ImportRuntimePlan,
    before: ImportRuntimeSnapshot,
    after: ImportRuntimeSnapshot,
    backend: ImportRuntimeBackend,
) -> list[str]:
    failures: list[str] = []
    actual_ids: dict[str, str] = {}
    for row_plan in plan.rows:
        old = before.row(row_plan.row_key).object
        new = after.row(row_plan.row_key).object
        policy = row_plan.guid_policy
        if policy == "remain_absent_no_guid":
            if new is not None:
                failures.append(f"{row_plan.row_key} refusal target was created")
            continue
        if new is None:
            failures.append(f"{row_plan.row_key} imported target is absent")
            continue
        if new.path != row_plan.target_path:
            failures.append(f"{row_plan.row_key} target path mismatch")
        if not _object_type_matches(new.type, row_plan.object_type):
            failures.append(f"{row_plan.row_key} reflected type mismatch")
        existing_use_existing = (
            row_plan.import_operation == "useExisting" and old is not None
        )
        expected_target_notes = (
            old.notes if existing_use_existing else row_plan.notes
        )
        if (
            expected_target_notes is None
            and old is not None
            and policy
            in {"preserve_existing_guid", "preserve_shared_existing_guid"}
        ):
            expected_target_notes = old.notes
        if _normalized_optional_notes(new.notes) != _normalized_optional_notes(
            expected_target_notes
        ):
            failures.append(f"{row_plan.row_key} Notes mismatch")
        if new.audio_source is None:
            failures.append(f"{row_plan.row_key} has no active Audio Source")
        else:
            if new.audio_source.language != row_plan.language:
                failures.append(f"{row_plan.row_key} language mismatch")
            if new.audio_source.original_file.sha256 != row_plan.source_file.sha256:
                failures.append(f"{row_plan.row_key} copied Originals hash mismatch")
            if not _subfolder_matches(
                new.audio_source.original_relative_path,
                row_plan.originals_subfolder,
            ):
                failures.append(f"{row_plan.row_key} Originals subfolder mismatch")
            expected_source_notes = (
                row_plan.notes
                if existing_use_existing and row_plan.notes is not None
                else row_plan.audio_source_notes
            )
            if _normalized_optional_notes(
                new.audio_source.notes
            ) != _normalized_optional_notes(expected_source_notes):
                failures.append(f"{row_plan.row_key} Audio Source Notes mismatch")

        if policy in {"preserve_existing_guid", "preserve_shared_existing_guid"}:
            if old is None or not _same_guid(old.id, new.id):
                failures.append(f"{row_plan.row_key} did not preserve the existing GUID")
        elif policy == "replace_with_distinct_guid":
            if old is None or _same_guid(old.id, new.id):
                failures.append(f"{row_plan.row_key} did not replace the old GUID")
            elif backend.read_objects(object_id=old.id, fields=EVENT_FIELDS):
                failures.append(f"{row_plan.row_key} old GUID still resolves after replace")
        elif policy in {"create_new_unique_guid", "create_once_then_preserve_shared_guid"}:
            if old is not None:
                failures.append(f"{row_plan.row_key} expected an absent baseline")
        else:
            failures.append(f"{row_plan.row_key} has an unsupported GUID policy {policy!r}")
        prior_id = actual_ids.setdefault(row_plan.target_path.casefold(), new.id)
        if not _same_guid(prior_id, new.id):
            failures.append(
                f"{row_plan.row_key} localized rows did not preserve one object GUID"
            )

    distinct_ids = {
        path: object_id for path, object_id in actual_ids.items()
    }
    if len({value.casefold() for value in distinct_ids.values()}) != len(distinct_ids):
        failures.append("distinct import target paths share one GUID")

    for row_plan in plan.rows:
        state = after.row(row_plan.row_key).object
        if row_plan.event_path is None or state is None:
            continue
        event = next(item for item in after.events if item.path == row_plan.event_path)
        if event.id is None or event.child_count != 1 or event.action_id is None:
            failures.append(f"{row_plan.row_key} Event does not contain exactly one Action")
            continue
        if event.action_type != PLAY_ACTION_TYPE:
            failures.append(f"{row_plan.row_key} Event Action type is not Play")
        if not _target_matches(event.target, state.id, state.path):
            failures.append(f"{row_plan.row_key} Event Action target mismatch")

    # Exact sibling readback catches automatic name conflict suffixes such as
    # ``_1`` without relying on the gateway's own verification result.
    checked: set[str] = set()
    for row_plan in plan.rows:
        key = row_plan.target_path.casefold()
        if key in checked or row_plan.guid_policy == "remain_absent_no_guid":
            continue
        checked.add(key)
        parent_path, name = row_plan.target_path.rsplit("\\", 1)
        parents = backend.read_objects(path=parent_path, fields=EVENT_FIELDS)
        if len(parents) != 1:
            failures.append(f"{row_plan.row_key} target parent did not resolve once")
            continue
        parent_id = _identity_value(parents[0].get("id"))
        if parent_id is None:
            failures.append(f"{row_plan.row_key} target parent lacks a GUID")
            continue
        siblings = backend.read_direct_children(parent_id, fields=EVENT_FIELDS)
        prefix = name.casefold()
        collisions = [
            item
            for item in siblings
            if isinstance(item.get("name"), str)
            and str(item["name"]).casefold().startswith(prefix)
        ]
        if len(collisions) != 1 or collisions[0].get("path") != row_plan.target_path:
            failures.append(f"{row_plan.row_key} has an automatic-numbering collision")
    return failures


def _business_snapshot(
    value: ImportRuntimeSnapshot | ImportCompoundRuntimeSnapshot,
) -> ImportRuntimeSnapshot:
    if isinstance(value, ImportRuntimeSnapshot):
        return value
    if isinstance(value, ImportCompoundRuntimeSnapshot):
        return value.business
    raise ImportRuntimeError("import snapshot has an unsupported type")


def _validate_reference_fixture_snapshot(
    plan: ImportRuntimePlan,
    value: tuple[
        tuple[ImportReferenceFixtureState, ...],
        ImportReferenceFixtureState,
    ],
) -> list[str]:
    fixtures, main_bus = value
    failures: list[str] = []
    if plan.main_bus_id is None or plan.main_bus_path is None:
        return ["compound plan lacks the default main Bus identity"]
    if (
        main_bus.path != plan.main_bus_path
        or not _same_guid(main_bus.id, plan.main_bus_id)
        or not _object_type_matches(main_bus.type, "Bus")
    ):
        failures.append("default main Bus identity/type/path drifted")
    expected = {item.key: item for item in plan.reference_fixtures}
    actual = {item.key: item for item in fixtures}
    if set(actual) != set(expected):
        failures.append("reference Bus fixture keys drifted")
        return failures
    seen_ids: set[str] = set()
    for key, sealed in expected.items():
        observed = actual[key]
        if (
            observed.path != sealed.path
            or not _same_guid(observed.id, sealed.id)
            or observed.parent_id is None
            or not _same_guid(observed.parent_id, sealed.parent_id)
            or not _object_type_matches(observed.type, "Bus")
        ):
            failures.append(f"reference Bus fixture {key!r} identity/type/path drifted")
        if _same_guid(observed.id, main_bus.id):
            failures.append(f"reference Bus fixture {key!r} aliases the default main Bus")
        folded = observed.id.casefold()
        if folded in seen_ids:
            failures.append("reference Bus fixture GUIDs are not unique")
        seen_ids.add(folded)
    return failures


def _validate_compound_after(
    plan: ImportRuntimePlan,
    before: ImportCompoundRuntimeSnapshot,
    after: ImportCompoundRuntimeSnapshot,
) -> list[str]:
    failures = _validate_reference_fixture_snapshot(
        plan,
        (after.reference_fixtures, after.main_bus),
    )
    if (
        before.reference_fixtures != after.reference_fixtures
        or before.main_bus != after.main_bus
    ):
        failures.append("reference Bus fixture state changed during import")
    expected_fixture_ids = {
        item.key: item.id for item in plan.reference_fixtures
    }
    for row_plan in plan.rows:
        before_state = before.row(row_plan.row_key)
        state = after.row(row_plan.row_key)
        if state.target_path != row_plan.target_path:
            failures.append(f"{row_plan.row_key} compound target path drifted")
            continue
        actual_properties = {item.name: item.value for item in state.properties}
        if len(actual_properties) != len(state.properties):
            failures.append(f"{row_plan.row_key} repeats dynamic property readback")
        actual_references = {
            item.name: item.target_id for item in state.references
        }
        if len(actual_references) != len(state.references):
            failures.append(f"{row_plan.row_key} repeats dynamic reference readback")

        if (
            row_plan.preserve_property_tokens
            or row_plan.preserve_reference_tokens
        ):
            before_properties = {
                item.name: item.value for item in before_state.properties
            }
            before_references = {
                item.name: item.target_id for item in before_state.references
            }
            expected_property_names = set(row_plan.preserve_property_tokens)
            expected_reference_names = set(row_plan.preserve_reference_tokens)
            if (
                len(before_properties) != len(before_state.properties)
                or set(before_properties) != expected_property_names
                or set(actual_properties) != expected_property_names
            ):
                failures.append(
                    f"{row_plan.row_key} preserved property token set is incomplete"
                )
            else:
                for name, old_value in before_properties.items():
                    new_value = actual_properties[name]
                    if (
                        type(old_value) is not type(new_value)
                        or old_value != new_value
                    ):
                        failures.append(
                            f"{row_plan.row_key} @{name} changed during media replacement"
                        )
            if (
                len(before_references) != len(before_state.references)
                or set(before_references) != expected_reference_names
                or set(actual_references) != expected_reference_names
            ):
                failures.append(
                    f"{row_plan.row_key} preserved reference token set is incomplete"
                )
            else:
                for name, old_value in before_references.items():
                    new_value = actual_references[name]
                    if not (
                        old_value is None
                        and new_value is None
                        or _same_guid(old_value, new_value)
                    ):
                        failures.append(
                            f"{row_plan.row_key} @{name} changed during media replacement"
                        )
            continue

        for expected in row_plan.expected_properties:
            if expected.name not in actual_properties:
                failures.append(
                    f"{row_plan.row_key} lacks @{expected.name} readback"
                )
                continue
            if actual_properties[expected.name] != expected.value:
                failures.append(
                    f"{row_plan.row_key} @{expected.name} value mismatch"
                )

        for expected in row_plan.expected_references:
            actual_id = actual_references.get(expected.name)
            fixture_id = expected_fixture_ids.get(expected.target_fixture)
            if (
                fixture_id is None
                or not _same_guid(expected.target_id, fixture_id)
                or not _same_guid(actual_id, fixture_id)
            ):
                failures.append(
                    f"{row_plan.row_key} @{expected.name} target GUID mismatch"
                )
            if plan.main_bus_id is None or _same_guid(actual_id, plan.main_bus_id):
                failures.append(
                    f"{row_plan.row_key} @{expected.name} still uses the default main Bus"
                )
            for activation in expected.activation_properties:
                if actual_properties.get(activation.name) is not True:
                    failures.append(
                        f"{row_plan.row_key} @{activation.name} does not prove "
                        f"a local @{expected.name} override"
                    )
    return failures


def _validate_saved_xml(
    plan: ImportRuntimePlan,
    snapshot: ImportRuntimeSnapshot,
    *,
    before: bool,
    old: ImportRuntimeSnapshot | None = None,
) -> list[str]:
    failures: list[str] = []
    if not snapshot.project_xml_files:
        return ["saved sandbox has no .wproj/.wwu evidence"]
    counts: dict[str, int] = {}
    for identity in snapshot.xml_identities:
        counts[identity.guid.casefold()] = counts.get(identity.guid.casefold(), 0) + 1
    for row_plan, row_state in zip(plan.rows, snapshot.rows, strict=True):
        state = row_state.object
        should_exist = (
            row_plan.pre_state_existence == "existing"
            if before
            else row_plan.guid_policy != "remain_absent_no_guid"
        )
        if should_exist and state is not None:
            # Wwise writes references to an imported Sound's GUID in Event
            # ObjectRef elements (and potentially other reference sites).
            # Those references do not duplicate the Sound definition.  Count
            # only the exact object-definition element, just as Audio Sources
            # below count only AudioFileSource rather than ActiveSource.
            definition_tag = _create_type(row_plan.object_type).casefold()
            definition_count = sum(
                1
                for identity in snapshot.xml_identities
                if identity.guid.casefold() == state.id.casefold()
                and identity.element_tag.casefold() == definition_tag
            )
            if definition_count != 1:
                failures.append(
                    f"{row_plan.row_key} GUID is not persisted once in saved XML"
                )
        if state is not None and state.audio_source is not None:
            source_id = state.audio_source.id.casefold()
            # A saved Wwise work unit records an Audio Source identity both on
            # its defining ``AudioFileSource`` element and on one or more
            # ``ActiveSource`` reference elements.  Only the defining element
            # proves that the source object itself was persisted exactly once;
            # counting references as duplicate definitions rejects valid live
            # Wwise XML.
            source_definition_count = sum(
                1
                for identity in snapshot.xml_identities
                if identity.guid.casefold() == source_id
                and identity.element_tag.casefold() == "audiofilesource"
            )
            if source_definition_count != 1:
                failures.append(
                    f"{row_plan.row_key} Audio Source GUID is not persisted once in XML"
                )
    if not before and old is not None:
        for row_plan in plan.rows:
            if row_plan.guid_policy != "replace_with_distinct_guid":
                continue
            old_state = old.row(row_plan.row_key).object
            if old_state is not None and counts.get(old_state.id.casefold(), 0) != 0:
                failures.append(f"{row_plan.row_key} old GUID remains in saved XML")
        for event in snapshot.events:
            for label, value in (("Event", event.id), ("Action", event.action_id)):
                if value is not None and counts.get(value.casefold()) != 1:
                    failures.append(f"{event.path} {label} GUID is not persisted once in XML")
    return failures


def _snapshot_drift(
    before: ImportRuntimeSnapshot | ImportCompoundRuntimeSnapshot,
    after: ImportRuntimeSnapshot | ImportCompoundRuntimeSnapshot,
) -> list[str]:
    if isinstance(before, ImportCompoundRuntimeSnapshot) or isinstance(
        after,
        ImportCompoundRuntimeSnapshot,
    ):
        if not isinstance(before, ImportCompoundRuntimeSnapshot) or not isinstance(
            after,
            ImportCompoundRuntimeSnapshot,
        ):
            return ["compound snapshot type changed before confirmation"]
        failures: list[str] = []
        if before.business != after.business:
            failures.append("business state changed before confirmation")
        if before.rows != after.rows:
            failures.append("dynamic property/reference state changed before confirmation")
        if before.reference_fixtures != after.reference_fixtures:
            failures.append("reference Bus fixtures changed before confirmation")
        if before.main_bus != after.main_bus:
            failures.append("default main Bus changed before confirmation")
        return failures
    failures: list[str] = []
    for field in (
        "rows",
        "events",
        "project_xml_files",
        "originals_files",
        "input_files",
        "xml_identities",
    ):
        if getattr(before, field) != getattr(after, field):
            failures.append(f"{field} changed before confirmation")
    return failures


def _validate_inputs_unchanged(
    before: ImportRuntimeSnapshot, after: ImportRuntimeSnapshot
) -> list[str]:
    return [] if before.input_files == after.input_files else ["runner input files changed"]


def _collect_parent_types(
    target_path: str,
    *,
    root: str,
    typed: Mapping[str, str],
    destination: dict[str, str],
) -> None:
    if not target_path.casefold().startswith((root + "\\").casefold()):
        raise ImportRuntimeError(f"import path is outside its reviewed root: {target_path}")
    suffix = target_path[len(root) + 1 :]
    parts = suffix.split("\\")
    current = root
    for part in parts[:-1]:
        current += "\\" + part
        object_type = typed.get(current, "Folder")
        previous = destination.setdefault(current, object_type)
        if previous != object_type:
            raise ImportRuntimeError(
                f"conflicting parent types for {current}: {previous}/{object_type}"
            )


def _typed_path_map(value: Any, *, target_path: str) -> dict[str, str]:
    if not isinstance(value, str) or not value:
        raise ImportRuntimeError("reviewed import row lacks object_path")
    # Tab rows are relative to importLocation; their final typed segment is not
    # used for parent materialization.  Full paths carry reviewed parent types.
    if not value.startswith("\\"):
        return {}
    current = ""
    result: dict[str, str] = {}
    normalized_parts: list[str] = []
    for raw in value.split("\\")[1:]:
        match = TYPED_SEGMENT_RE.fullmatch(raw)
        if match:
            raw_type, name = match.groups()
            object_type = _create_type(raw_type)
        else:
            name = raw
            object_type = None
        if not name:
            raise ImportRuntimeError("typed import path contains an empty segment")
        normalized_parts.append(name)
        current = "\\" + "\\".join(normalized_parts)
        if object_type is not None:
            result[current] = object_type
    normalized = "\\" + "\\".join(normalized_parts)
    if normalized != target_path:
        raise ImportRuntimeError(
            f"typed import path does not normalize to target: {value!r}"
        )
    return result


def _typed_final_path(target_path: str, object_type: str) -> str:
    parent, name = target_path.rsplit("\\", 1)
    return f"{parent}\\<{object_type}>{name}"


def _create_type(value: str) -> str:
    token = re.sub(r"[^a-z0-9]", "", value.casefold())
    if token in {"folder", "virtualfolder"}:
        return "Folder"
    if token == "actormixer":
        return "ActorMixer"
    if token == "randomcontainer":
        return "RandomSequenceContainer"
    # Final Sound types are intentionally ignored by parent collection.
    if token in {"sound", "soundsfx", "soundvoice"}:
        return "Sound"
    raise ImportRuntimeError(f"unreviewed typed import object: {value!r}")


def _derive_asset_root(materialized: MaterializedImportCase) -> Path:
    files = (
        *materialized.source_files,
        *materialized.pre_state_files,
        *materialized.tab_files,
    )
    if not files:
        raise ImportRuntimeError("materialized import case has no owned files")
    candidates: set[Path] = set()
    for item in files:
        for parent in item.path.parents:
            if parent.name == "sources" and (parent.parent / "pre-state").is_dir() and (
                parent.parent / "tables"
            ).is_dir():
                candidates.add(parent.parent.resolve(strict=True))
    if len(candidates) != 1:
        raise ImportRuntimeError("could not derive one sealed import asset root")
    root = candidates.pop()
    for item in files:
        if not _path_is_under(item.path, root):
            raise ImportRuntimeError("materialized file escapes its asset root")
    return root


def _assert_materialized_inputs(materialized: MaterializedImportCase) -> None:
    for item in (
        *materialized.source_files,
        *materialized.pre_state_files,
        *materialized.tab_files,
    ):
        if item.present:
            proof = _regular_file_proof(item.path, relative_to=None)
            if proof.size != item.size or proof.sha256 != item.sha256:
                raise ImportRuntimeError(f"sealed input changed: {item.path}")
        elif item.path.exists() or item.path.is_symlink():
            raise ImportRuntimeError(f"intentionally absent input appeared: {item.path}")


def _input_file_state(
    materialized: MaterializedImportCase,
) -> tuple[tuple[str, bool, int | None, str | None], ...]:
    result: list[tuple[str, bool, int | None, str | None]] = []
    for item in (
        *materialized.source_files,
        *materialized.pre_state_files,
        *materialized.tab_files,
    ):
        if item.present:
            proof = _regular_file_proof(item.path, relative_to=None)
            result.append((str(item.path), True, proof.size, proof.sha256))
        else:
            result.append((str(item.path), False, None, None))
    return tuple(sorted(result))


def _tree_proofs(
    root: Path,
    *,
    include: Callable[[Path], bool],
    limit: int,
) -> tuple[FileProof, ...]:
    result: list[FileProof] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ImportRuntimeError(f"sandbox evidence contains a symlink: {path}")
        if not path.is_file() or not include(path):
            continue
        result.append(_regular_file_proof(path, relative_to=root, require_contained=True))
        if len(result) > limit:
            raise ImportRuntimeError("sandbox evidence file count exceeded its bound")
    return tuple(result)


def _is_originals_file(path: Path) -> bool:
    return any(part.casefold() == "originals" for part in path.parts)


def _xml_identity_evidence(
    root: Path, xml_files: Sequence[FileProof]
) -> tuple[XmlIdentityEvidence, ...]:
    result: list[XmlIdentityEvidence] = []
    for proof in xml_files:
        path = Path(proof.path)
        try:
            tree = ET.parse(path)
        except (ET.ParseError, OSError) as exc:
            raise ImportRuntimeError(f"cannot parse saved Wwise XML {path}: {exc}") from exc
        for element in tree.iter():
            identity = None
            for key, value in element.attrib.items():
                if key.rsplit("}", 1)[-1].casefold() in {"id", "guid"} and GUID_RE.fullmatch(value):
                    identity = value
                    break
            if identity is None:
                continue
            name = next(
                (
                    value
                    for key, value in element.attrib.items()
                    if key.rsplit("}", 1)[-1].casefold() in {"name", "shortname"}
                ),
                None,
            )
            result.append(
                XmlIdentityEvidence(
                    guid=identity,
                    relative_file=str(path.relative_to(root)),
                    element_tag=element.tag.rsplit("}", 1)[-1],
                    name=name,
                )
            )
    return tuple(sorted(result, key=lambda item: (item.guid.casefold(), item.relative_file, item.element_tag)))


def _regular_file_proof(
    value: Any,
    *,
    relative_to: Path | None,
    require_contained: bool = False,
) -> FileProof:
    if not isinstance(value, (str, os.PathLike)):
        raise ImportRuntimeError("file proof requires a path")
    candidate = Path(value).expanduser()
    if candidate.is_symlink():
        raise ImportRuntimeError(f"file proof refuses a symlink: {candidate}")
    path = candidate.resolve(strict=True)
    if not path.is_file():
        raise ImportRuntimeError(f"file proof requires a regular file: {path}")
    before = path.stat()
    size = before.st_size
    if size > MAX_FILE_BYTES:
        raise ImportRuntimeError(f"file exceeds the import evidence bound: {path}")
    relative: str | None = None
    if relative_to is not None:
        base = relative_to.resolve(strict=True)
        if require_contained and not _path_is_under(path, base):
            raise ImportRuntimeError(f"copied original escapes the scenario project: {path}")
        if _path_is_under(path, base):
            relative = path.relative_to(base).as_posix()
    sha256 = _sha256(path)
    after = path.stat()
    stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if any(getattr(before, name) != getattr(after, name) for name in stable_fields):
        raise ImportRuntimeError(f"file changed while it was being sealed: {path}")
    return FileProof(
        path=str(path),
        relative_path=relative,
        size=size,
        sha256=sha256,
    )


def _copied_original_evidence(
    value: Any,
    *,
    project_root: Path,
) -> tuple[FileProof, str]:
    """Seal one copied Original and derive its canonical project-relative path.

    Wwise 2022.1 does not expose ``originalRelativeFilePath`` through
    ``object.get``.  The absolute copied-file accessor remains authoritative,
    so derive the relative evidence only after proving that the lexical and
    resolved path both stay below the case-owned ``Originals`` directory and
    that no path component is a symlink.
    """

    candidate = _localize_waapi_original_path(
        value,
        wine_z_root=None if os.name == "nt" else Path("/"),
    )

    root = project_root.resolve(strict=True)
    originals = root / "Originals"
    try:
        originals_meta = os.lstat(originals)
    except OSError as exc:
        raise ImportRuntimeError(
            f"case-owned Originals root is unavailable: {originals}"
        ) from exc
    if stat.S_ISLNK(originals_meta.st_mode) or not stat.S_ISDIR(
        originals_meta.st_mode
    ):
        raise ImportRuntimeError(
            f"case-owned Originals root must be a non-symlink directory: {originals}"
        )

    try:
        lexical_relative = candidate.relative_to(originals)
    except ValueError as exc:
        raise ImportRuntimeError(
            f"copied original escapes the case-owned Originals root: {candidate}"
        ) from exc
    if not lexical_relative.parts:
        raise ImportRuntimeError("copied original resolves to the Originals directory")

    current = originals
    for part in lexical_relative.parts:
        current /= part
        try:
            metadata = os.lstat(current)
        except OSError as exc:
            raise ImportRuntimeError(
                f"copied original path component is unavailable: {current}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise ImportRuntimeError(
                f"copied original path contains a symlink: {current}"
            )

    resolved_originals = originals.resolve(strict=True)
    resolved_candidate = candidate.resolve(strict=True)
    try:
        resolved_relative = resolved_candidate.relative_to(resolved_originals)
    except ValueError as exc:
        raise ImportRuntimeError(
            f"copied original resolves outside the case-owned Originals root: {candidate}"
        ) from exc
    if tuple(lexical_relative.parts) != tuple(resolved_relative.parts):
        raise ImportRuntimeError(
            f"copied original path changed during containment proof: {candidate}"
        )

    proof = _regular_file_proof(
        resolved_candidate,
        relative_to=root,
        require_contained=True,
    )
    relative = resolved_relative.as_posix()
    if not relative or relative == "." or relative.startswith("../"):
        raise ImportRuntimeError("copied original relative path is not canonical")
    return proof, relative


def _localize_waapi_original_path(
    value: Any,
    *,
    wine_z_root: Path | None = None,
) -> Path:
    """Map only POSIX absolute paths and the two reviewed Wine drives.

    Wwise running through Wine reports the login-account home as ``Y:`` and
    the POSIX filesystem root as ``Z:``.  Reject every other Windows/UNC or
    relative spelling before the case-owned ``Originals`` containment proof.
    """

    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        raise ImportRuntimeError(
            "copied original requires a non-empty absolute path string"
        )

    try:
        windows_path = parse_windows_drive_path(value)
    except ReflectedHostPathError as exc:
        raise ImportRuntimeError(
            "copied original has an unsafe Windows drive spelling"
        ) from exc
    if windows_path is not None:
        drive = windows_path.drive
        parts = windows_path.relative_parts
        native = Path(windows_path.pure) if os.name == "nt" else None
        native_root_available = (
            native is not None and _available_directory(Path(native.anchor))
        )
        if native_root_available:
            return native
        if drive == "Z" and wine_z_root is not None:
            base = Path(wine_z_root)
        elif drive == "Y" and (os.name != "nt" or pwd is not None):
            base = _resolved_login_home()
        elif drive == "Z":
            if wine_z_root is None:
                if os.name == "nt":
                    raise ImportRuntimeError(
                        "copied original Wine Z: has no native root mapping"
                    )
                base = Path("/")
        elif drive == "Y":
            raise ImportRuntimeError(
                "copied original uses an unavailable native Windows drive Y:"
            )
        else:
            raise ImportRuntimeError(
                f"copied original uses unmappable Wine drive {drive}:"
            )
        candidate = base.joinpath(*parts)
    else:
        try:
            candidate = Path(parse_posix_absolute_path(value))
        except ReflectedHostPathError as exc:
            raise ImportRuntimeError(
                "copied original must be an absolute host path"
            ) from exc
    if not candidate.is_absolute():  # defensive on unusual pathlib platforms
        raise ImportRuntimeError("copied original must localize to an absolute path")
    return candidate


def _validated_native_windows_original_path(value: str) -> PureWindowsPath:
    """Validate one native-Windows drive-absolute path without host I/O."""

    try:
        parsed = parse_windows_drive_path(value)
    except ReflectedHostPathError as exc:
        raise ImportRuntimeError(
            "copied original must be a native Windows drive-absolute path"
        ) from exc
    if parsed is None:
        raise ImportRuntimeError(
            "copied original must be a native Windows drive-absolute path"
        )
    return parsed.pure


def _available_directory(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _resolved_login_home() -> Path:
    if pwd is None:
        raise ImportRuntimeError(
            "copied original Wine Y: mapping is unavailable on this host"
        )
    try:
        getuid = getattr(os, "getuid", None)
        uid = getuid() if callable(getuid) else None
        home = Path(pwd.getpwuid(uid).pw_dir)
        resolved = home.resolve(strict=True)
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError) as exc:
        raise ImportRuntimeError(
            "copied original Wine Y: could not be mapped to the login home"
        ) from exc
    if not resolved.is_dir():
        raise ImportRuntimeError(
            "copied original Wine Y: login home is not a directory"
        )
    return resolved


def _result_rows(value: Any, *, context: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Mapping):
        raise ImportRuntimeError(f"{context} result must be an object")
    rows = value.get("return")
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        raise ImportRuntimeError(f"{context} result must contain a mapping array")
    if len(rows) > MAX_OBJECT_ROWS:
        raise ImportRuntimeError(f"{context} result exceeded its row bound")
    return tuple(dict(row) for row in rows)


def _validated_fields(fields: Sequence[str]) -> tuple[str, ...]:
    if isinstance(fields, (str, bytes)):
        raise ImportRuntimeError("return fields must be a sequence")
    values = tuple(fields)
    allowed = frozenset(
        {
            *OBJECT_FIELDS,
            *OBJECT_FIELDS_2021,
            *AUDIO_SOURCE_FIELDS,
            *AUDIO_SOURCE_FIELDS_2021,
            *ACTION_FIELDS,
        }
    )
    if not values or len(values) != len(set(values)) or any(value not in allowed for value in values):
        raise ImportRuntimeError("direct read fields are outside the closed import oracle")
    return values


def _validated_dynamic_token(value: Any) -> str:
    if (
        not isinstance(value, str)
        or LIVE_METADATA_TOKEN_RE.fullmatch(value) is None
        or value.startswith("@")
    ):
        raise ImportRuntimeError("live metadata token is invalid")
    return value


def _validated_dynamic_tokens(names: Sequence[str]) -> tuple[str, ...]:
    if isinstance(names, (str, bytes)):
        raise ImportRuntimeError("dynamic field names must be a sequence")
    values = tuple(_validated_dynamic_token(value) for value in names)
    if (
        not values
        or len(values) > MAX_DYNAMIC_FIELDS
        or len({value.casefold() for value in values}) != len(values)
    ):
        raise ImportRuntimeError(
            "dynamic field names must contain 1..32 unique live tokens"
        )
    return values


def _reference_fixture_state(
    key: str,
    path: str,
    value: Mapping[str, Any],
    *,
    expected_type: str,
) -> ImportReferenceFixtureState:
    state = ImportReferenceFixtureState(
        key=_required_text(key, "reference fixture key"),
        path=_required_wwise_path(value.get("path"), "reference fixture path"),
        id=_required_guid(value.get("id"), "reference fixture id"),
        type=_required_text(value.get("type"), "reference fixture type"),
        parent_id=_identity_value(value.get("parent")),
    )
    if state.path != path or not _object_type_matches(state.type, expected_type):
        raise ImportRuntimeError(
            f"reference fixture {key!r} path/type readback drifted"
        )
    return state


def _object_type_matches(actual: Any, requested: str) -> bool:
    if not isinstance(actual, str):
        return False
    normalize = lambda value: re.sub(r"[^a-z0-9]", "", value.casefold())
    actual_token = normalize(actual)
    requested_token = normalize(requested)
    aliases = {
        "soundsfx": {"sound", "soundsfx"},
        "soundvoice": {"sound", "soundvoice"},
        "virtualfolder": {"folder", "virtualfolder"},
        "folder": {"folder", "virtualfolder"},
        "actormixer": {"actormixer", "propertycontainer"},
        "bus": {"bus", "audiobus"},
        "auxbus": {"auxbus"},
        "randomsequencecontainer": {
            "randomcontainer",
            "randomsequencecontainer",
        },
    }
    return actual_token in aliases.get(requested_token, {requested_token})


def _is_json_scalar(value: Any) -> bool:
    return value is None or type(value) in {str, int, float, bool}


def _subfolder_matches(actual: str | None, expected: str | None) -> bool:
    if expected is None:
        return True
    if actual is None:
        return False
    actual_parts = [part.casefold() for part in re.split(r"[\\/]", actual) if part]
    expected_parts = [part.casefold() for part in re.split(r"[\\/]", expected) if part]
    if len(actual_parts) < len(expected_parts) + 1:
        return False
    return actual_parts[-len(expected_parts) - 1 : -1] == expected_parts


def _target_matches(value: Any, expected_id: str, expected_path: str) -> bool:
    if isinstance(value, Mapping):
        compared = False
        if "id" in value:
            compared = True
            if not _same_guid(value.get("id"), expected_id):
                return False
        if "path" in value:
            compared = True
            if value.get("path") != expected_path:
                return False
        if "object" in value:
            compared = True
            if not _target_matches(value.get("object"), expected_id, expected_path):
                return False
        return compared
    if isinstance(value, str):
        return _same_guid(value, expected_id) or value == expected_path
    return False


def _language_name(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        for key in ("name", "displayName", "shortName"):
            if isinstance(value.get(key), str):
                return str(value[key])
    return None


def _field_value(row: Mapping[str, Any], key: str) -> Any:
    if key in row:
        return row[key]
    at_key = "@" + key
    if at_key in row:
        return row[at_key]
    return None


def _identity_value(value: Any) -> str | None:
    if isinstance(value, str) and GUID_RE.fullmatch(value):
        return value
    if isinstance(value, Mapping):
        for key in ("id", "object"):
            result = _identity_value(value.get(key))
            if result is not None:
                return result
    return None


def _integer_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _required_guid(value: Any, field: str) -> str:
    if not isinstance(value, str) or not GUID_RE.fullmatch(value):
        raise ImportRuntimeError(f"{field} must be a canonical Wwise GUID")
    return value


def _required_wwise_path(value: Any, field: str) -> str:
    text = _required_text(value, field)
    if not text.startswith("\\") or text.endswith("\\") or "\\\\" in text:
        raise ImportRuntimeError(f"{field} must be an absolute Wwise path")
    return text


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or any(ch in value for ch in ("\x00", "\r", "\n")):
        raise ImportRuntimeError(f"{field} must be a non-empty bounded string")
    return value


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ImportRuntimeError("optional text must be a string or null")
    return value


def _normalized_optional_notes(value: str | None) -> str | None:
    """Treat Wwise's two readback representations of an absent note equally."""

    return None if value in (None, "") else value


def _same_guid(left: Any, right: Any) -> bool:
    return isinstance(left, str) and isinstance(right, str) and left.casefold() == right.casefold()


def _unique(values: Sequence[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if key not in seen:
            result.append(value)
            seen.add(key)
    return tuple(result)


def _path_depth(value: str) -> int:
    return len([part for part in value.split("\\") if part])


def _path_is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def _assert_safe_asset_cleanup_root(asset_root: Path, sandbox_root: Path) -> None:
    if asset_root.is_symlink():
        raise ImportRuntimeError("refusing symlink import asset cleanup root")
    root = asset_root.resolve(strict=True)
    sandbox = sandbox_root.resolve(strict=True)
    if root in {sandbox, sandbox.parent, Path.home().resolve()} or _path_is_under(sandbox, root):
        raise ImportRuntimeError("refusing unsafe import asset cleanup root")
    if not all((root / name).is_dir() for name in ("sources", "pre-state", "tables")):
        raise ImportRuntimeError("import asset cleanup root lacks its sealed layout")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "COMPOUND_SUPPORTED_VERSIONS",
    "PROFILE_CROSS_VERSION_SCENARIOS",
    "ClosedDirectWaapiBackend",
    "FileProof",
    "ImportAudioSourceState",
    "ImportCompoundRowState",
    "ImportCompoundRuntimeSnapshot",
    "ImportEventState",
    "ImportObjectState",
    "ImportParentPlan",
    "ImportPropertyExpectation",
    "ImportPropertyState",
    "ImportReferenceExpectation",
    "ImportReferenceFixtureCleanup",
    "ImportReferenceFixtureState",
    "ImportReferenceState",
    "ImportRowPlan",
    "ImportRowState",
    "ImportRuntimeBackend",
    "ImportRuntimeCleanup",
    "ImportRuntimeError",
    "ImportRuntimePlan",
    "ImportRuntimeSnapshot",
    "ImportRuntimeVerification",
    "PreparedImportReferenceFixtures",
    "PreparedImportRuntime",
    "SetupImport",
    "XmlIdentityEvidence",
    "build_import_runtime_plan",
    "import_runtime_version_is_reviewed",
    "prepare_import_reference_fixtures",
    "prepare_import_runtime",
]
