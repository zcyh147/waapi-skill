"""Audio import semantic builders that prepare WAAPI payloads without dispatch."""

from __future__ import annotations

import csv
import io
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from wwise_waapi.dispatcher import DEFAULT_WWISE_VERSION  # pyright: ignore[reportMissingImports]

from .common import (  # pyright: ignore[reportMissingImports]
    BuilderContext,
    BuilderFamily,
    ManifestSchemaLoader,
    SemanticEnvelope,
    SemanticErrorCode,
    SemanticPreview,
    SemanticValidationError,
    SourceNoteChecker,
)
from .container_suitability import (  # pyright: ignore[reportMissingImports]
    ContainerSuitabilityResult,
    assess_writable_container_suitability,
)
from .schema import SemanticSchemaValidator  # pyright: ignore[reportMissingImports]
from .source_notes import SemanticSourceNoteChecker  # pyright: ignore[reportMissingImports]


AUDIO_IMPORT_URI = "ak.wwise.core.audio.import"
AUDIO_IMPORT_TAB_DELIMITED_URI = "ak.wwise.core.audio.importTabDelimited"
AUDIO_IMPORTED_TOPIC_URI = "ak.wwise.core.audio.imported"
DEFAULT_IMPORT_RETURN_FIELDS = ("id", "name", "type", "path")
SUPPORTED_IMPORT_OPERATIONS = ("createNew", "useExisting", "replaceExisting")
SUPPORTED_IMPORT_ITEM_FIELDS = {
    "audioFile",
    "audioFileBase64",
    "audioSourceNotes",
    "dialogueEvent",
    "event",
    "importLanguage",
    "importLocation",
    "notes",
    "objectPath",
    "objectType",
    "originalsSubFolder",
}
TAB_DELIMITED_COLUMNS = (
    "Audio File",
    "Object Path",
    "Object Type",
    "OriginalsSubFolder",
    "Notes",
)


@dataclass(slots=True, frozen=True)
class ImportItem:
    """One import command inside ``ak.wwise.core.audio.import``."""

    object_path: str
    object_type: str | None = None
    audio_file: str | Path | None = None
    audio_file_base64: str | None = None
    import_language: str | None = None
    originals_subfolder: str | None = None
    notes: str | None = None
    audio_source_notes: str | None = None
    properties: Mapping[str, Any] = field(default_factory=dict)
    overrides: Mapping[str, Any] = field(default_factory=dict)

    def as_import(self) -> dict[str, Any]:
        item: dict[str, Any] = {"objectPath": _non_empty_string("object_path", self.object_path)}
        _set_optional_string(item, "objectType", self.object_type)
        _set_optional_path(item, "audioFile", self.audio_file)
        _set_optional_string(item, "audioFileBase64", self.audio_file_base64)
        _set_optional_string(item, "importLanguage", self.import_language)
        _set_optional_string(item, "originalsSubFolder", self.originals_subfolder)
        _set_optional_string(item, "notes", self.notes)
        _set_optional_string(item, "audioSourceNotes", self.audio_source_notes)
        item.update(_normalized_overrides(self.overrides, context="import item overrides"))
        item.update(_normalized_property_assignments(self.properties, context="import item properties"))
        _validate_import_item(item)
        return item


@dataclass(slots=True, frozen=True)
class TabDelimitedImportPlan:
    """Deterministic tab-delimited import-file plan; it writes only through its explicit helper."""

    columns: tuple[str, ...]
    rows: tuple[Mapping[str, str], ...]
    newline: str = "\n"
    encoding: str = "utf-8"
    filename: str = "wwise-waapi-import.tsv"

    def render(self) -> str:
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=list(self.columns), delimiter="\t", lineterminator=self.newline, extrasaction="ignore")
        writer.writeheader()
        for row in self.rows:
            writer.writerow({column: row.get(column, "") for column in self.columns})
        return output.getvalue()

    def as_dict(self) -> dict[str, Any]:
        return {
            "columns": list(self.columns),
            "rows": [dict(row) for row in self.rows],
            "newline": self.newline,
            "encoding": self.encoding,
            "filename": self.filename,
            "content_preview": self.render(),
            "writes_file_by_default": False,
        }

    def write_to_temp(self, directory: str | Path) -> Path:
        root = Path(directory).resolve()
        temp_root = Path(tempfile.gettempdir()).resolve()
        if root != temp_root and temp_root not in root.parents:
            raise SemanticValidationError(
                SemanticErrorCode.DESTRUCTIVE_GATE_REQUIRED,
                "Tab-delimited import plans may only be materialized under the system temp directory.",
                details={"directory": str(root), "temp_root": str(temp_root)},
            )
        root.mkdir(parents=True, exist_ok=True)
        path = root / self.filename
        path.write_text(self.render(), encoding=self.encoding, newline="")
        return path


@dataclass(slots=True, frozen=True)
class ImportBuilder:
    """Build source-grounded audio import previews without calling Wwise."""

    version: str = DEFAULT_WWISE_VERSION
    source_note_checker: SourceNoteChecker | None = None
    manifest_loader: ManifestSchemaLoader = field(default_factory=ManifestSchemaLoader)

    def audio_import(
        self,
        imports: Sequence[ImportItem | Mapping[str, Any]],
        *,
        import_operation: str | None = None,
        defaults: Mapping[str, Any] | None = None,
        auto_add_to_source_control: bool | None = None,
        auto_check_out_to_source_control: bool | None = None,
        return_fields: Sequence[str] = DEFAULT_IMPORT_RETURN_FIELDS,
    ) -> SemanticPreview:
        item_targets = [_coerce_import_item_with_target(index, item) for index, item in enumerate(imports)]
        if not item_targets:
            raise SemanticValidationError(SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH, "audio.import requires at least one import item.")
        items = [item for item, _target_identity in item_targets]
        target_identities = {f"imports[{index}].objectPath": target_identity for index, (_item, target_identity) in enumerate(item_targets)}
        args: dict[str, Any] = {"imports": items}
        if import_operation is not None:
            args["importOperation"] = _import_operation(import_operation)
        if defaults is not None:
            args["default"] = _normalized_defaults(defaults)
        if auto_add_to_source_control is not None:
            if not isinstance(auto_add_to_source_control, bool):
                raise SemanticValidationError(SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH, "autoAddToSourceControl must be a boolean.")
            args["autoAddToSourceControl"] = auto_add_to_source_control
        if auto_check_out_to_source_control is not None:
            if not isinstance(auto_check_out_to_source_control, bool):
                raise SemanticValidationError(SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH, "autoCheckOutToSourceControl must be a boolean.")
            args["autoCheckOutToSourceControl"] = auto_check_out_to_source_control
        return self._build_preview(AUDIO_IMPORT_URI, args, _return_options(return_fields), "audio-import-objects", target_identities=target_identities)

    def import_tab_delimited(
        self,
        *,
        import_location: str | int | None,
        import_language: str,
        import_operation: str,
        import_file: str | Path | None = None,
        plan: TabDelimitedImportPlan | None = None,
        auto_add_to_source_control: bool | None = None,
        auto_check_out_to_source_control: bool | None = None,
        return_fields: Sequence[str] = DEFAULT_IMPORT_RETURN_FIELDS,
    ) -> SemanticPreview:
        if import_file is None and plan is None:
            raise SemanticValidationError(
                SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
                "importTabDelimited requires an explicit import_file path or a deterministic plan to materialize later.",
            )
        args: dict[str, Any] = {
            "importLanguage": _non_empty_string("import_language", import_language),
            "importOperation": _import_operation(import_operation),
            "importFile": str(import_file) if import_file is not None else plan_filename(plan),
        }
        target_identities: dict[str, Any] = {}
        if import_location is not None:
            _require_object_arg("import_location", import_location)
            target_identities["importLocation"] = _require_writable_import_target("import_location", import_location)
            args["importLocation"] = import_location
        if auto_add_to_source_control is not None:
            if not isinstance(auto_add_to_source_control, bool):
                raise SemanticValidationError(SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH, "autoAddToSourceControl must be a boolean.")
            args["autoAddToSourceControl"] = auto_add_to_source_control
        if auto_check_out_to_source_control is not None:
            if not isinstance(auto_check_out_to_source_control, bool):
                raise SemanticValidationError(SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH, "autoCheckOutToSourceControl must be a boolean.")
            args["autoCheckOutToSourceControl"] = auto_check_out_to_source_control
        metadata_extra = {"tab_delimited_plan": plan.as_dict()} if plan is not None else {}
        return self._build_preview(
            AUDIO_IMPORT_TAB_DELIMITED_URI,
            args,
            _return_options(return_fields),
            "tab-delimited-import-objects",
            metadata_extra,
            target_identities=target_identities,
        )

    def imported_topic(self, *, return_fields: Sequence[str] = DEFAULT_IMPORT_RETURN_FIELDS) -> SemanticPreview:
        return self._build_preview(AUDIO_IMPORTED_TOPIC_URI, {}, _return_options(return_fields), "audio-imported-topic")

    def _build_preview(
        self,
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
        expectation: str,
        metadata_extra: Mapping[str, Any] | None = None,
        target_identities: Mapping[str, Any] | None = None,
    ) -> SemanticPreview:
        context = BuilderContext(
            BuilderFamily.IMPORT,
            version=self.version,
            source_note_checker=self.source_note_checker or SemanticSourceNoteChecker(),
            manifest_loader=self.manifest_loader,
        )
        context.require_supported_family()
        source_note = context.require_source_note()
        validation = SemanticSchemaValidator(manifest_loader=context.manifest_loader, version=context.version).validate(uri, args, options)
        metadata = {
            "builder_family": BuilderFamily.IMPORT.value,
            "source_note": source_note.as_dict(),
            "schema_validation": validation.as_dict(),
            "return_expectation": _return_expectation(expectation),
            "destructive_behavior": "preview-only; caller must provide live/destructive gate before dispatch",
            **dict(metadata_extra or {}),
        }
        preview_target_identity = _preview_target_identity(target_identities or {})
        if preview_target_identity["roles"]:
            metadata["preview_target_identity"] = preview_target_identity
        result_readback_binding = _import_result_readback_binding(uri)
        metadata["execution_result_readback_binding"] = result_readback_binding
        envelope = SemanticEnvelope(
            uri,
            args=dict(args),
            options=dict(options),
            metadata=metadata,
        )
        return SemanticPreview(
            envelope=envelope,
            source_note_family=BuilderFamily.IMPORT.value,
            version=self.version,
            # The imported object ids do not exist until this envelope has
            # executed.  Emitting a SemanticReadbackPlan here would either
            # replay the destructive import or expose an unbound pseudo-call.
            readback_plan=(),
            evidence_plan=(
                {"kind": "source-note", "family": BuilderFamily.IMPORT.value, "status": source_note.as_dict()},
                {"kind": "schema", "validation": validation.as_dict()},
                {"kind": "execution-result-readback-binding", **result_readback_binding},
                {"kind": "cleanup-source-immutability", "requires_sandbox": True, "refuse_source_outputs": True},
                {"kind": "artifact-evidence", "capture": ["import-result", "object-readback", "cleanup", "source-immutability"]},
            ),
            requires_destructive_gate=True,
        )


def build_audio_import_preview(imports: Sequence[ImportItem | Mapping[str, Any]], **kwargs: Any) -> SemanticPreview:
    return _builder_from_kwargs(kwargs).audio_import(imports, **kwargs)


def build_import_tab_delimited_preview(**kwargs: Any) -> SemanticPreview:
    return _builder_from_kwargs(kwargs).import_tab_delimited(**kwargs)


def expect_audio_imported_topic(**kwargs: Any) -> SemanticPreview:
    return _builder_from_kwargs(kwargs).imported_topic(**kwargs)


def _builder_from_kwargs(kwargs: dict[str, Any]) -> ImportBuilder:
    return ImportBuilder(
        version=kwargs.pop("version", DEFAULT_WWISE_VERSION),
        source_note_checker=kwargs.pop("source_note_checker", None),
    )


def build_object_path(root: str, *segments: str | tuple[str, str]) -> str:
    """Compose Wwise paths using backslashes and optional ``<ObjectType>Name`` segments."""

    path = _root_path(root)
    parts: list[str] = []
    for segment in segments:
        if isinstance(segment, tuple):
            if len(segment) != 2:
                raise SemanticValidationError(SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH, "Object path typed segments require object type and name.")
            parts.append(f"<{_segment_value('object_type', segment[0])}>{_segment_value('name', segment[1])}")
        else:
            parts.append(_segment_value("segment", segment))
    return "\\".join((path, *parts)) if parts else path


def tab_delimited_plan(items: Sequence[ImportItem | Mapping[str, Any]], *, filename: str = "wwise-waapi-import.tsv") -> TabDelimitedImportPlan:
    rows: list[Mapping[str, str]] = []
    for item in items:
        normalized = _coerce_import_item(item)
        rows.append(
            {
                "Audio File": str(normalized.get("audioFile", "")),
                "Object Path": str(normalized["objectPath"]),
                "Object Type": str(normalized.get("objectType", "")),
                "OriginalsSubFolder": str(normalized.get("originalsSubFolder", "")),
                "Notes": str(normalized.get("notes", "")),
            }
        )
    return TabDelimitedImportPlan(columns=TAB_DELIMITED_COLUMNS, rows=tuple(rows), filename=_safe_filename(filename))


def write_tab_delimited_import_file(plan: TabDelimitedImportPlan, directory: str | Path) -> Path:
    return plan.write_to_temp(directory)


def plan_filename(plan: TabDelimitedImportPlan | None) -> str:
    assert plan is not None
    return f"<materialize:{plan.filename}>"


def _coerce_import_item(item: ImportItem | Mapping[str, Any]) -> dict[str, Any]:
    return _coerce_import_item_with_target(0, item)[0]


def _coerce_import_item_with_target(index: int, item: ImportItem | Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if isinstance(item, ImportItem):
        normalized = item.as_import()
    else:
        normalized = _normalized_overrides(item, context="import item")
        _validate_import_item(normalized)
    target_identity = _import_item_target_identity(index, normalized)
    return normalized, target_identity


def _validate_import_item(item: Mapping[str, Any]) -> None:
    if "objectPath" not in item:
        raise SemanticValidationError(SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH, "Each audio import item requires objectPath.")
    object_path = _non_empty_string("objectPath", item["objectPath"])
    _require_writable_import_target("objectPath", object_path)
    sources = tuple(key for key in ("audioFile", "audioFileBase64") if key in item and _has_value(item[key]))
    if len(sources) > 1:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "Audio import items must specify audioFile or audioFileBase64, not both.",
            details={"sources": list(sources)},
        )
    unknown = tuple(sorted(key for key in item if not _allowed_import_field(key)))
    if unknown:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED,
            "Unsupported audio import item fields.",
            details={"unknown_fields": list(unknown)},
        )
    if "switchAssignation" in item:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED,
            "switchAssignation is not supported by semantic import builders because source notes do not allow Switch Container state constraints.",
            details={"field": "switchAssignation"},
        )


def _normalized_defaults(defaults: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _normalized_overrides(defaults, context="import defaults")
    if "objectPath" in normalized:
        raise SemanticValidationError(SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH, "Import defaults must not provide objectPath; set it per import item.")
    return normalized


def _normalized_overrides(values: Mapping[str, Any], *, context: str) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in values.items():
        key_text = str(key)
        if key_text == "switchAssignation":
            raise SemanticValidationError(SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED, "switchAssignation is unsupported by import builders.")
        if key_text.startswith("@@"):
            raise SemanticValidationError(
                SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED,
                "Constrained references are not supported by import builders; only @Property assignments are allowed.",
                details={"field": key_text, "context": context},
            )
        if key_text.startswith("@"):
            _property_key(key_text, context=context)
        elif not _allowed_import_field(key_text):
            raise SemanticValidationError(
                SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED,
                "Unsupported import field.",
                details={"field": key_text, "context": context},
            )
        normalized[key_text] = _path_to_string(value)
    return normalized


def _normalized_property_assignments(values: Mapping[str, Any], *, context: str) -> dict[str, Any]:
    return {_property_key(str(key), context=context): _path_to_string(value) for key, value in values.items()}


def _property_key(key: str, *, context: str) -> str:
    if not key.startswith("@") or key.startswith("@@") or len(key) == 1 or not all(character.isalnum() or character in ("_", ":") for character in key[1:]):
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED,
            "Import builders allow only @Property assignments, not constrained references or malformed keys.",
            details={"field": key, "context": context},
        )
    return key


def _allowed_import_field(key: str) -> bool:
    return key in SUPPORTED_IMPORT_ITEM_FIELDS or key.startswith("@")


def _import_operation(value: str) -> str:
    text = _non_empty_string("import_operation", value)
    if text not in SUPPORTED_IMPORT_OPERATIONS:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "Unsupported importOperation.",
            details={"importOperation": text, "supported": list(SUPPORTED_IMPORT_OPERATIONS)},
        )
    return text


def _return_options(return_fields: Sequence[str]) -> dict[str, Any]:
    if not return_fields or not all(isinstance(field, str) and field for field in return_fields):
        raise SemanticValidationError(SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH, "Import previews require explicit non-empty return fields.")
    return {"return": list(return_fields)}


def _return_expectation(kind: str) -> dict[str, Any]:
    return {
        "parser": "parse_imported_objects_result",
        "shape": "object-with-objects-array" if kind != "audio-imported-topic" else "topic-payload-with-objects-array",
        "required_fields": ["objects"],
        "kind": kind,
    }


def _import_result_readback_binding(uri: str) -> dict[str, Any]:
    """Describe the deferred result-to-readback binding without a pseudo-call."""

    return {
        "source": {"uri": uri, "result_path": "objects[].id"},
        "target": {
            "uri": "ak.wwise.core.object.get",
            "argument_path": "args.from.id[0]",
            "options": {"return": list(DEFAULT_IMPORT_RETURN_FIELDS)},
        },
        "fan_out": {"mode": "one-call-per-value", "value_contract": "wwise-guid"},
        "requires_source_result": True,
        "executable_before_binding": False,
        "must_execute_after": uri,
    }


def _root_path(root: str) -> str:
    value = _non_empty_string("root", root).strip("\\")
    if not value:
        raise SemanticValidationError(SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH, "Object path root must contain at least one hierarchy segment.")
    return "\\" + "\\".join(_segment_value("root segment", part) for part in value.split("\\") if part)


def _segment_value(name: str, value: str) -> str:
    text = _non_empty_string(name, value)
    if "\\" in text:
        raise SemanticValidationError(SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH, "Object path segments must not contain backslashes.", details={"segment": text})
    return text


def _set_optional_string(target: dict[str, Any], key: str, value: str | None) -> None:
    if value is not None:
        target[key] = _non_empty_string(key, value)


def _set_optional_path(target: dict[str, Any], key: str, value: str | Path | None) -> None:
    if value is not None:
        target[key] = _non_empty_string(key, str(value))


def _non_empty_string(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SemanticValidationError(SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH, f"{name} must be a non-empty string.")
    return value


def _require_object_arg(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (str, int)) or (isinstance(value, str) and not value.strip()):
        raise SemanticValidationError(SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH, f"{name} must be a non-empty object id/name/path value.")


def _require_writable_import_target(field: str, value: str | int) -> dict[str, Any]:
    suitability_target: str | int = value
    if field == "import_location" and isinstance(value, str) and not value.startswith("\\"):
        suitability_target = 0
    suitability = assess_writable_container_suitability(suitability_target)
    if suitability.valid:
        return _target_identity_from_value(field, value, suitability)
    raise _container_error(
        f"{field} must target a writable child container instead of the target path {value!r}.",
        field=field,
        invalid_target=value,
        suitability=suitability,
    )


def _import_item_target_identity(index: int, item: Mapping[str, Any]) -> dict[str, Any]:
    object_path = _non_empty_string("objectPath", item["objectPath"])
    return _require_writable_import_target(f"imports[{index}].objectPath", object_path)


def _preview_target_identity(target_identities: Mapping[str, Any]) -> dict[str, Any]:
    roles = {str(role): dict(identity) for role, identity in target_identities.items() if isinstance(identity, Mapping)}
    return {
        "roles": roles,
        "authorized_execution": {
            "required": True,
            "abort_on_mismatch": True,
            "mismatch_status": "repreview_required",
            "reason": "authorized execution must reuse the preview-resolved target identity",
        },
    }


def _target_identity_from_value(field: str, value: str | int, suitability: ContainerSuitabilityResult) -> dict[str, Any]:
    target = {
        "field": field,
        "object": value,
        "target_key": [str(value)],
        "container_suitability": suitability.as_dict(),
        "candidate_targets": list(suitability.candidate_targets),
    }
    if suitability.resolved_identity is not None:
        target["candidate_resolved_identity"] = dict(suitability.resolved_identity)
    return target


def _container_error(message: str, *, field: str, invalid_target: str | int, suitability: ContainerSuitabilityResult) -> SemanticValidationError:
    details: dict[str, Any] = {
        "field": field,
        "invalid_target": invalid_target,
        "container_suitability": suitability.as_dict(),
        "candidate_targets": list(suitability.candidate_targets),
        "requires_user_confirmation": suitability.requires_user_confirmation,
        "requires_live_verification": suitability.requires_live_verification,
        "reason_code": suitability.reason,
    }
    if isinstance(invalid_target, str):
        details["invalid_target_path"] = invalid_target
    if suitability.candidate_targets:
        details["candidate_writable_parent"] = suitability.candidate_targets[0]
    return SemanticValidationError(SemanticErrorCode.SEMANTIC_CONTAINER_UNSUITABLE, message, details=details)


def _has_value(value: Any) -> bool:
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def _path_to_string(value: Any) -> Any:
    return str(value) if isinstance(value, Path) else value


def _safe_filename(value: str) -> str:
    name = _non_empty_string("filename", value)
    if Path(name).name != name:
        raise SemanticValidationError(SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH, "Tab-delimited plan filename must not include directories.")
    return name
