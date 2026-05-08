"""Shared semantic builder contracts that never dispatch WAAPI calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol

from wwise_waapi.dispatcher import DEFAULT_WWISE_VERSION, DispatcherRequest
from wwise_waapi.manifest import ManifestResourceMissingError, ManifestStore


DEFAULT_MANIFEST_ROOT = Path(__file__).resolve().parents[2] / "resources" / "manifest"
DEFAULT_WORK_UNIT_NAME = "Default Work Unit"
KNOWN_WWISE_MANAGEMENT_ROOTS = frozenset(
    {
        "Actor-Mixer Hierarchy",
        "Master-Mixer Hierarchy",
        "Interactive Music Hierarchy",
        "Dynamic Dialogue",
        "SoundBanks",
        "Switches",
        "States",
        "Triggers",
        "Attenuations",
        "Effects",
        "Events",
        "Game Parameters",
        "Conversion Settings",
        "Audio Devices",
        "Control Surface Sessions",
        "Modulators",
        "Presets",
        "Queries",
        "Mixing Sessions",
        "Metadata",
        "Soundcaster Sessions",
        "Virtual Acoustics",
        "Containers",
        "Busses",
        "Devices",
        "Sidechain Mixes",
    }
)


class SemanticErrorCode(str, Enum):
    """Typed semantic builder validation codes shared by family builders."""

    MISSING_SOURCE_NOTE = "MISSING_SOURCE_NOTE"
    SOURCE_NOTE_INCOMPLETE = "SOURCE_NOTE_INCOMPLETE"
    SOURCE_NOTE_WRONG_NOTEBOOK = "SOURCE_NOTE_WRONG_NOTEBOOK"
    SOURCE_NOTE_UNCITED_FIELD = "SOURCE_NOTE_UNCITED_FIELD"
    UNSUPPORTED_WWISE_VERSION = "UNSUPPORTED_WWISE_VERSION"
    AMBIGUOUS_OBJECT_IDENTITY = "AMBIGUOUS_OBJECT_IDENTITY"
    SEMANTIC_SCHEMA_MISMATCH = "SEMANTIC_SCHEMA_MISMATCH"
    SEMANTIC_PROPERTY_UNSUPPORTED = "SEMANTIC_PROPERTY_UNSUPPORTED"
    UNSUPPORTED_BUILDER_FAMILY = "UNSUPPORTED_BUILDER_FAMILY"
    DESTRUCTIVE_GATE_REQUIRED = "DESTRUCTIVE_GATE_REQUIRED"
    SEMANTIC_CONTAINER_UNSUITABLE = "SEMANTIC_CONTAINER_UNSUITABLE"


class BuilderFamily(str, Enum):
    """Semantic builder family identifiers used in previews and source notes."""

    QUERY = "query"
    OBJECT_MUTATION = "object-mutation"
    PROPERTY_REFERENCE = "property-reference"
    IMPORT = "import"
    SOUNDBANK = "soundbank"
    SWITCHCONTAINER = "switchcontainer"


class SemanticValidationError(ValueError):
    """Machine-readable semantic builder validation failure."""

    def __init__(
        self,
        error_code: SemanticErrorCode | str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.error_code = SemanticErrorCode(error_code)
        self.details = dict(details or {})
        super().__init__(message)

    @property
    def message(self) -> str:
        return str(self)

    def as_dict(self) -> dict[str, Any]:
        return {"error_code": self.error_code.value, "message": self.message, "details": dict(self.details)}


@dataclass(slots=True, frozen=True)
class SourceNoteCheck:
    """Adapter result for source-note validation owned outside this package."""

    allowed: bool
    family: str
    version: str = DEFAULT_WWISE_VERSION
    cited_fields: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    uncited_fields: tuple[str, ...] = ()
    reason: str = ""
    error_code: SemanticErrorCode | str | None = None

    def semantic_error_code(self) -> SemanticErrorCode:
        if self.error_code is not None:
            return SemanticErrorCode(self.error_code)
        if self.missing_fields:
            return SemanticErrorCode.SOURCE_NOTE_INCOMPLETE
        if self.uncited_fields:
            return SemanticErrorCode.SOURCE_NOTE_UNCITED_FIELD
        return SemanticErrorCode.MISSING_SOURCE_NOTE

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "family": self.family,
            "version": self.version,
            "cited_fields": list(self.cited_fields),
            "missing_fields": list(self.missing_fields),
            "uncited_fields": list(self.uncited_fields),
            "reason": self.reason,
            "error_code": self.error_code.value if isinstance(self.error_code, SemanticErrorCode) else self.error_code,
        }


class SourceNoteChecker(Protocol):
    """Minimal source-note checker adapter; concrete resources are Task 0 owned."""

    def check(self, family: str, version: str = DEFAULT_WWISE_VERSION) -> SourceNoteCheck:
        """Validate source-note evidence for a builder family."""
        ...


@dataclass(slots=True, frozen=True)
class SemanticReadbackPlan:
    """Planned post-dispatch readback evidence for later live verification."""

    uri: str
    args: Mapping[str, Any] = field(default_factory=dict)
    options: Mapping[str, Any] = field(default_factory=dict)
    description: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "args": dict(self.args),
            "options": dict(self.options),
            "description": self.description,
        }


@dataclass(slots=True, frozen=True)
class SemanticEnvelope:
    """Dispatcher-ready WAAPI payload plus semantic metadata kept out of args/options."""

    uri: str
    args: Mapping[str, Any] = field(default_factory=dict)
    options: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def dispatch_payload(self) -> dict[str, Any]:
        return {"uri": self.uri, "args": dict(self.args), "options": dict(self.options)}

    def as_dict(self) -> dict[str, Any]:
        return {**self.dispatch_payload(), "metadata": dict(self.metadata)}

    def to_dispatcher_request(self, *, version: str = DEFAULT_WWISE_VERSION, dry_run: bool = True) -> DispatcherRequest:
        return DispatcherRequest(
            api=self.uri,
            version=version,
            args=dict(self.args),
            options=dict(self.options),
            dry_run=dry_run,
        )


@dataclass(slots=True, frozen=True)
class SemanticPreview:
    """Serializable semantic build preview; it intentionally performs no dispatch."""

    envelope: SemanticEnvelope
    source_note_family: str
    version: str = DEFAULT_WWISE_VERSION
    readback_plan: tuple[SemanticReadbackPlan, ...] = ()
    evidence_plan: tuple[Mapping[str, Any], ...] = ()
    requires_destructive_gate: bool = False
    raw_dispatch_allowed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "source_note_family": self.source_note_family,
            "requires_destructive_gate": self.requires_destructive_gate,
            "raw_dispatch_allowed": self.raw_dispatch_allowed,
            "envelope": self.envelope.as_dict(),
            "readback_plan": [plan.as_dict() for plan in self.readback_plan],
            "evidence_plan": [dict(item) for item in self.evidence_plan],
        }

    def dispatch_payload(self) -> dict[str, Any]:
        return self.envelope.dispatch_payload()

    def to_dispatcher_request(self) -> DispatcherRequest:
        return self.envelope.to_dispatcher_request(version=self.version, dry_run=True)


@dataclass(slots=True, frozen=True)
class ManifestSchemaLoader:
    """Manifest/schema lookup adapter using the generated resource store conventions."""

    manifest_store: ManifestStore = field(default_factory=lambda: ManifestStore(root=DEFAULT_MANIFEST_ROOT))

    def load_manifest(self, version: str = DEFAULT_WWISE_VERSION) -> dict[str, Any]:
        try:
            manifest = self.manifest_store.load(version)
        except ManifestResourceMissingError as exc:
            raise SemanticValidationError(
                SemanticErrorCode.UNSUPPORTED_WWISE_VERSION,
                f"Unsupported Wwise version for semantic builders: {version}",
                details={"version": version, "resource_path": str(exc.path)},
            ) from exc
        if not manifest:
            raise SemanticValidationError(
                SemanticErrorCode.UNSUPPORTED_WWISE_VERSION,
                f"Unsupported Wwise version for semantic builders: {version}",
                details={"version": version},
            )
        return manifest

    def schema_for(self, uri: str, version: str = DEFAULT_WWISE_VERSION) -> Mapping[str, Any]:
        manifest = self.load_manifest(version)
        for entry in manifest.get("schemas", []):
            if not isinstance(entry, Mapping) or entry.get("uri") != uri:
                continue
            schema = entry.get("schema")
            if isinstance(schema, Mapping):
                return schema
            break
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            f"No usable schema for WAAPI URI {uri!r} in manifest {version}",
            details=_schema_absence_details(uri, version),
        )


@dataclass(slots=True, frozen=True)
class BuilderContext:
    """Shared dependency bundle passed to future semantic family builders."""

    family: BuilderFamily | str
    version: str = DEFAULT_WWISE_VERSION
    source_note_checker: SourceNoteChecker | None = None
    manifest_loader: ManifestSchemaLoader = field(default_factory=ManifestSchemaLoader)

    @property
    def family_value(self) -> str:
        return self.family.value if isinstance(self.family, BuilderFamily) else str(self.family)

    def require_supported_family(self) -> None:
        try:
            BuilderFamily(self.family_value)
        except ValueError as exc:
            raise SemanticValidationError(
                SemanticErrorCode.UNSUPPORTED_BUILDER_FAMILY,
                f"Unsupported semantic builder family: {self.family_value}",
                details={"family": self.family_value},
            ) from exc

    def require_source_note(self) -> SourceNoteCheck:
        return require_source_note(self.source_note_checker, self.family_value, self.version)

    def load_manifest(self) -> dict[str, Any]:
        return self.manifest_loader.load_manifest(self.version)

    def schema_for(self, uri: str) -> Mapping[str, Any]:
        return self.manifest_loader.schema_for(uri, self.version)


def require_source_note(
    checker: SourceNoteChecker | None,
    family: BuilderFamily | str,
    version: str = DEFAULT_WWISE_VERSION,
) -> SourceNoteCheck:
    """Validate a source note through an adapter without owning note resources."""

    family_value = family.value if isinstance(family, BuilderFamily) else str(family)
    if checker is None:
        raise SemanticValidationError(
            SemanticErrorCode.MISSING_SOURCE_NOTE,
            f"Semantic source note is required for builder family {family_value!r}",
            details={"family": family_value, "version": version},
        )
    status = checker.check(family_value, version)
    if not status.allowed:
        raise SemanticValidationError(
            status.semantic_error_code(),
            status.reason or f"Semantic source note is not valid for builder family {family_value!r}",
            details=status.as_dict(),
        )
    return status


def _schema_absence_details(uri: str, version: str) -> dict[str, Any]:
    details: dict[str, Any] = {
        "uri": uri,
        "version": version,
        "status": "unsupported",
        "schema_status": "absent-from-version-manifest",
        "fallback_allowed": False,
    }
    try:
        from wwise_waapi.deferred_registry import DeferredRegistry

        entry = DeferredRegistry.load_default(version).get(uri)
    except (FileNotFoundError, KeyError, ValueError):
        entry = None
    if entry is not None:
        details["status"] = "deferred"
        details["deferred_registry"] = entry.as_dict()
    return details


def split_wwise_path(path: str) -> tuple[str, ...]:
    return tuple(segment for segment in path.split("\\") if segment)


def candidate_writable_child_container(path: str) -> str | None:
    segments = split_wwise_path(path)
    if not segments:
        return None
    root = segments[0]
    if root not in KNOWN_WWISE_MANAGEMENT_ROOTS:
        return None
    if len(segments) == 1:
        return f"\\{root}\\{DEFAULT_WORK_UNIT_NAME}"
    second = segments[1]
    if second == DEFAULT_WORK_UNIT_NAME:
        return None
    if second.startswith("<"):
        return "\\" + "\\".join((root, DEFAULT_WORK_UNIT_NAME, *segments[1:]))
    return None
