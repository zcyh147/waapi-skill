"""Resource-backed semantic builder source-note validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from wwise_waapi.dispatcher import DEFAULT_WWISE_VERSION
from wwise_waapi.versions import is_explicit_fail_closed_version  # pyright: ignore[reportMissingImports]

from .common import BuilderFamily, SemanticErrorCode, SemanticValidationError, SourceNoteCheck


SKILL_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = SKILL_ROOT.parents[1]
DEFAULT_SEMANTIC_SOURCE_ROOT = SKILL_ROOT / "resources" / "semantic"
DEFAULT_SEMANTIC_SOURCE_NOTES = DEFAULT_SEMANTIC_SOURCE_ROOT / DEFAULT_WWISE_VERSION / "source_notes.json"

EXPECTED_SOURCE_NOTE_URI_INVENTORY: dict[str, tuple[str, ...]] = {
    BuilderFamily.QUERY.value: ("ak.wwise.core.object.get",),
    BuilderFamily.OBJECT_MUTATION.value: (
        "ak.wwise.core.object.create",
        "ak.wwise.core.object.set",
        "ak.wwise.core.object.delete",
        "ak.wwise.core.object.copy",
        "ak.wwise.core.object.move",
        "ak.wwise.core.object.diff",
        "ak.wwise.core.object.pasteProperties",
        "ak.wwise.core.undo.beginGroup",
        "ak.wwise.core.undo.endGroup",
        "ak.wwise.core.undo.undo",
    ),
    BuilderFamily.PROPERTY_REFERENCE.value: (
        "ak.wwise.core.object.getTypes",
        "ak.wwise.core.object.getPropertyAndReferenceNames",
        "ak.wwise.core.object.getPropertyInfo",
        "ak.wwise.core.object.isPropertyEnabled",
        "ak.wwise.core.object.getAttenuationCurve",
        "ak.wwise.core.object.setName",
        "ak.wwise.core.object.setNotes",
        "ak.wwise.core.object.setProperty",
        "ak.wwise.core.object.setReference",
        "ak.wwise.core.object.setRandomizer",
        "ak.wwise.core.object.setAttenuationCurve",
    ),
    BuilderFamily.IMPORT.value: (
        "ak.wwise.core.audio.import",
        "ak.wwise.core.audio.importTabDelimited",
        "ak.wwise.core.audio.imported",
    ),
    BuilderFamily.SOUNDBANK.value: (
        "ak.wwise.core.soundbank.getInclusions",
        "ak.wwise.core.soundbank.setInclusions",
        "ak.wwise.core.soundbank.generate",
        "ak.wwise.core.soundbank.convertExternalSources",
        "ak.wwise.core.soundbank.processDefinitionFiles",
        "ak.wwise.core.soundbank.generated",
        "ak.wwise.core.soundbank.generationDone",
    ),
    BuilderFamily.SWITCHCONTAINER.value: (
        "ak.wwise.core.switchContainer.getAssignments",
        "ak.wwise.core.switchContainer.addAssignment",
        "ak.wwise.core.switchContainer.removeAssignment",
        "ak.wwise.core.switchContainer.assignmentAdded",
        "ak.wwise.core.switchContainer.assignmentRemoved",
    ),
}
VERSION_SPECIFIC_SOURCE_NOTE_URI_ADDITIONS: dict[str, dict[str, tuple[str, ...]]] = {
    "2024.1": {BuilderFamily.PROPERTY_REFERENCE.value: ("ak.wwise.core.object.isLinked",)},
    "2025.1": {BuilderFamily.PROPERTY_REFERENCE.value: ("ak.wwise.core.object.isLinked",)},
}

REQUIRED_SOURCE_NOTE_FIELDS = (
    "family",
    "status",
    "version_target",
    "official_urls",
    "source_urls",
    "endpoints",
    "required_fields",
    "optional_fields",
    "return_shape",
    "destructive_behavior",
    "ambiguity_constraints",
    "unsupported_cases",
    "cited_required_fields",
)

GROUNDING_STATUS = "grounded"
FAIL_CLOSED_STATUS = "fail-closed"


@dataclass(slots=True, frozen=True)
class SemanticSourceNoteResource:
    """Parsed semantic source-note resource bundle."""

    version: str
    notes: Mapping[str, Mapping[str, Any]]
    root: Path


class SemanticSourceNoteChecker:
    """Validate persisted source notes before semantic builders are allowed."""

    def __init__(
        self,
        resource_path: Path | None = None,
    ) -> None:
        self.resource_path = resource_path

    def check(self, family: str, version: str = DEFAULT_WWISE_VERSION) -> SourceNoteCheck:
        try:
            family_value = BuilderFamily(family).value
        except ValueError:
            return SourceNoteCheck(
                False,
                family,
                version=version,
                reason=f"Semantic source note family is not supported: {family}",
                error_code=SemanticErrorCode.MISSING_SOURCE_NOTE,
            )

        try:
            resource = load_semantic_source_notes(self._resource_path_for(version), expected_version=version)
        except SemanticValidationError as exc:
            return SourceNoteCheck(
                False,
                family_value,
                version=version,
                reason=exc.message,
                error_code=exc.error_code,
            )

        if resource.version != version:
            return SourceNoteCheck(
                False,
                family_value,
                version=version,
                reason=f"Semantic source-note resource is for {resource.version}, expected {version}.",
                error_code=SemanticErrorCode.SOURCE_NOTE_INCOMPLETE,
            )
        note = resource.notes.get(family_value)
        if note is None:
            return SourceNoteCheck(
                False,
                family_value,
                version=version,
                reason=f"Semantic source note is missing for builder family {family_value!r}.",
                error_code=SemanticErrorCode.MISSING_SOURCE_NOTE,
            )

        missing = _missing_note_fields(note)
        if missing:
            return SourceNoteCheck(
                False,
                family_value,
                version=version,
                missing_fields=missing,
                reason="Semantic source note is incomplete.",
                error_code=SemanticErrorCode.SOURCE_NOTE_INCOMPLETE,
            )
        incomplete = _incomplete_note_values(note, family_value, version)
        if incomplete:
            return SourceNoteCheck(
                False,
                family_value,
                version=version,
                missing_fields=incomplete,
                reason="Semantic source note is incomplete.",
                error_code=SemanticErrorCode.SOURCE_NOTE_INCOMPLETE,
            )

        required_fields = _string_tuple(note["required_fields"])
        cited_fields = _string_tuple(note["cited_required_fields"])
        uncited = tuple(field for field in required_fields if field not in cited_fields)
        if uncited:
            return SourceNoteCheck(
                False,
                family_value,
                version=version,
                cited_fields=cited_fields,
                uncited_fields=uncited,
                reason="Semantic source note has uncited required fields.",
                error_code=SemanticErrorCode.SOURCE_NOTE_UNCITED_FIELD,
            )

        return SourceNoteCheck(
            True,
            family_value,
            version=version,
            cited_fields=cited_fields,
            reason="Semantic source note is grounded.",
        )

    def _resource_path_for(self, version: str) -> Path:
        if self.resource_path is not None:
            return self.resource_path
        if is_explicit_fail_closed_version(version):
            return DEFAULT_SEMANTIC_SOURCE_ROOT / version / "source_notes.json"
        return DEFAULT_SEMANTIC_SOURCE_NOTES


def load_semantic_source_notes(
    resource_path: Path = DEFAULT_SEMANTIC_SOURCE_NOTES,
    *,
    expected_version: str | None = None,
) -> SemanticSourceNoteResource:
    """Load the semantic source-note resource or raise a typed validation error."""

    if not resource_path.exists():
        details = {"resource_path": str(resource_path)}
        if expected_version is not None:
            details["version"] = expected_version
        raise SemanticValidationError(
            SemanticErrorCode.MISSING_SOURCE_NOTE,
            f"Semantic source-note resource is missing: {resource_path}",
            details=details,
        )
    try:
        data = json.loads(resource_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SemanticValidationError(
            SemanticErrorCode.SOURCE_NOTE_INCOMPLETE,
            f"Semantic source-note resource could not be read: {exc}",
        ) from exc
    if not isinstance(data, Mapping):
        raise SemanticValidationError(SemanticErrorCode.SOURCE_NOTE_INCOMPLETE, "Semantic source-note resource must be an object.")
    notes = data.get("notes")
    if not isinstance(notes, Mapping):
        raise SemanticValidationError(SemanticErrorCode.SOURCE_NOTE_INCOMPLETE, "Semantic source-note resource lacks notes.")
    return SemanticSourceNoteResource(
        version=str(data.get("version", "")),
        notes={str(key): value for key, value in notes.items() if isinstance(value, Mapping)},
        root=_semantic_evidence_root(resource_path),
    )


def source_note_uri_inventory(resource_path: Path = DEFAULT_SEMANTIC_SOURCE_NOTES) -> dict[str, tuple[str, ...]]:
    """Return family URI inventory and fail on duplicate/missing/excluded families."""

    resource = load_semantic_source_notes(resource_path)
    expected = tuple(family.value for family in BuilderFamily)
    actual = tuple(resource.notes.keys())
    if set(actual) != set(expected):
        raise SemanticValidationError(
            SemanticErrorCode.SOURCE_NOTE_INCOMPLETE,
            "Semantic source-note families do not match the builder family inventory.",
            details={"expected": list(expected), "actual": list(actual)},
        )

    inventory: dict[str, tuple[str, ...]] = {}
    for family in expected:
        endpoints = _string_tuple(resource.notes[family].get("endpoints"))
        expected_endpoints = EXPECTED_SOURCE_NOTE_URI_INVENTORY[family] + VERSION_SPECIFIC_SOURCE_NOTE_URI_ADDITIONS.get(
            resource.version, {}
        ).get(family, ())
        if not endpoints or len(endpoints) != len(set(endpoints)) or endpoints != expected_endpoints:
            raise SemanticValidationError(
                SemanticErrorCode.SOURCE_NOTE_INCOMPLETE,
                f"Semantic source-note URI inventory is invalid for {family}.",
                details={"family": family, "expected": list(expected_endpoints), "endpoints": list(endpoints)},
            )
        inventory[family] = endpoints
    return inventory


def _semantic_evidence_root(resource_path: Path) -> Path:
    resolved = resource_path.resolve()
    if (
        resolved.name == "source_notes.json"
        and len(resolved.parents) >= 4
        and resolved.parents[1].name == "semantic"
        and resolved.parents[2].name == "resources"
    ):
        return resolved.parents[3]
    return REPO_ROOT



def _missing_note_fields(note: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(field for field in REQUIRED_SOURCE_NOTE_FIELDS if field not in note)


def _incomplete_note_values(note: Mapping[str, Any], family: str, version: str) -> tuple[str, ...]:
    missing: list[str] = []
    if note.get("family") != family:
        missing.append("family")
    if note.get("status") != GROUNDING_STATUS:
        missing.append("status")
    if note.get("version_target") != version:
        missing.append("version_target")
    for key in (
        "official_urls",
        "source_urls",
        "endpoints",
        "required_fields",
        "return_shape",
        "destructive_behavior",
        "ambiguity_constraints",
        "unsupported_cases",
        "cited_required_fields",
    ):
        value = note.get(key)
        if isinstance(value, str):
            if not value.strip():
                missing.append(key)
        elif isinstance(value, list):
            if not value or not all(isinstance(item, str) and item.strip() for item in value):
                missing.append(key)
        elif not value:
            missing.append(key)
    endpoints = _string_tuple(note.get("endpoints"))
    if endpoints and len(endpoints) != len(set(endpoints)):
        missing.append("endpoints")
    return tuple(missing)


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item.strip())
