"""Schema-aware semantic validation helpers for reflected WAAPI resources."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from wwise_waapi.dispatcher import DEFAULT_WWISE_VERSION

from .common import BuilderFamily, ManifestSchemaLoader, SemanticErrorCode, SemanticValidationError
from .source_notes import DEFAULT_SEMANTIC_SOURCE_NOTES, DEFAULT_SEMANTIC_SOURCE_ROOT, load_semantic_source_notes


SEMANTIC_CONSTRAINT_FACTS_SIZE_LIMIT = 4096


@dataclass(slots=True, frozen=True)
class SchemaValidationResult:
    """Successful conservative validation evidence for one semantic payload."""

    uri: str
    version: str = DEFAULT_WWISE_VERSION
    required_fields: tuple[str, ...] = ()
    required_families: tuple[tuple[str, ...], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "version": self.version,
            "required_fields": list(self.required_fields),
            "required_families": [list(family) for family in self.required_families],
        }


@dataclass(slots=True, frozen=True)
class SemanticConstraintFacts:
    """Compact task-scoped WAAPI facts for one URI/family pair."""

    uri: str
    family: str
    version: str = DEFAULT_WWISE_VERSION
    required_args: tuple[str, ...] = ()
    required_arg_families: tuple[tuple[str, ...], ...] = ()
    supported_args: tuple[str, ...] = ()
    supported_options: tuple[str, ...] = ()
    identity_shape: tuple[str, ...] = ()
    property_hints: tuple[str, ...] = ()
    result_shape: str = ""
    result_fields: tuple[str, ...] = ()
    mutation_hints: tuple[str, ...] = ()
    source_priority: tuple[str, ...] = ()
    provenance: tuple[Mapping[str, Any], ...] = ()
    size_ceiling: int = SEMANTIC_CONSTRAINT_FACTS_SIZE_LIMIT

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "uri": self.uri,
            "family": self.family,
            "version": self.version,
            "required_args": list(self.required_args),
            "required_arg_families": [list(family) for family in self.required_arg_families],
            "supported_args": list(self.supported_args),
            "supported_options": list(self.supported_options),
            "identity_shape": list(self.identity_shape),
            "property_hints": list(self.property_hints),
            "result_shape": self.result_shape,
            "result_fields": list(self.result_fields),
            "mutation_hints": list(self.mutation_hints),
            "source_priority": list(self.source_priority),
            "provenance": [dict(item) for item in self.provenance],
            "size_ceiling": self.size_ceiling,
        }
        _ensure_constraint_facts_size(payload, self.uri, self.version, self.size_ceiling)
        return payload


@dataclass(slots=True, frozen=True)
class SemanticSchemaValidator:
    """Validate builder payloads against manifest-backed schemas without dispatching."""

    manifest_loader: ManifestSchemaLoader = field(default_factory=ManifestSchemaLoader)
    version: str = DEFAULT_WWISE_VERSION

    def require_supported_version(self) -> None:
        self.manifest_loader.load_manifest(self.version)

    def schema_for(self, uri: str) -> Mapping[str, Any]:
        self.require_supported_version()
        return self.manifest_loader.schema_for(uri, self.version)

    def validate(self, uri: str, args: Mapping[str, Any] | None = None, options: Mapping[str, Any] | None = None) -> SchemaValidationResult:
        schema = self.schema_for(uri)
        arg_payload = dict(args or {})
        option_payload = dict(options or {})
        args_schema = _mapping_or_empty(schema.get("argsSchema"))
        options_schema = _mapping_or_empty(schema.get("optionsSchema"))

        required_fields = _required_fields(args_schema)
        missing = tuple(field for field in required_fields if field not in arg_payload)
        if missing:
            raise _schema_error(uri, self.version, f"WAAPI URI {uri!r} is missing required args: {', '.join(missing)}", missing_args=missing)

        required_families = _required_families(args_schema)
        _validate_required_alternatives(uri, self.version, args_schema, arg_payload)

        _reject_unknown_fields(uri, self.version, "args", args_schema, arg_payload)
        _reject_unknown_fields(uri, self.version, "options", options_schema, option_payload)
        _validate_known_types(uri, self.version, "args", args_schema, arg_payload)
        _validate_known_types(uri, self.version, "options", options_schema, option_payload)

        return SchemaValidationResult(uri=uri, version=self.version, required_fields=required_fields, required_families=required_families)


def validate_semantic_payload(
    uri: str,
    args: Mapping[str, Any] | None = None,
    options: Mapping[str, Any] | None = None,
    *,
    version: str = DEFAULT_WWISE_VERSION,
    manifest_loader: ManifestSchemaLoader | None = None,
) -> SchemaValidationResult:
    """Validate one semantic payload using existing manifest/resource conventions."""

    validator = SemanticSchemaValidator(manifest_loader=manifest_loader or ManifestSchemaLoader(), version=version)
    return validator.validate(uri, args=args, options=options)


def extract_semantic_constraint_facts(
    uri: str,
    family: BuilderFamily | str,
    *,
    version: str = DEFAULT_WWISE_VERSION,
    manifest_loader: ManifestSchemaLoader | None = None,
    source_note_path: Path | None = None,
    operator_allows_official_docs: bool = False,
) -> SemanticConstraintFacts:
    """Return bounded source-grounded facts for exactly one WAAPI URI."""

    family_value = _builder_family_value(family)
    note_path = source_note_path or _source_note_path_for_version(version)
    resource = load_semantic_source_notes(note_path, expected_version=version)
    if resource.version != version:
        raise SemanticValidationError(
            SemanticErrorCode.SOURCE_NOTE_INCOMPLETE,
            f"Semantic source-note resource is for {resource.version}, expected {version}.",
            details={"version": version, "resource_version": resource.version},
        )
    note = resource.notes.get(family_value)
    if note is None:
        raise SemanticValidationError(
            SemanticErrorCode.MISSING_SOURCE_NOTE,
            f"Semantic source note is missing for builder family {family_value!r}.",
            details={"family": family_value, "version": version},
        )
    endpoints = _string_tuple(note.get("endpoints"))
    if uri not in endpoints:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            f"WAAPI URI {uri!r} is not in semantic source-note family {family_value!r}.",
            details={"uri": uri, "family": family_value, "version": version},
        )

    loader = manifest_loader or ManifestSchemaLoader()
    loader.load_manifest(version)
    schema = loader.schema_for(uri, version)
    args_schema = _mapping_or_empty(schema.get("argsSchema"))
    options_schema = _mapping_or_empty(schema.get("optionsSchema"))
    result_schema = _mapping_or_empty(schema.get("resultSchema"))

    supported_args = _property_names(args_schema)
    supported_options = _merge_unique(_note_options(note), _property_names(options_schema))
    required_args = _merge_unique(_required_fields(args_schema), _note_required_args_for_uri(note, uri))
    required_arg_families = _required_families(args_schema)
    identity_shape = _identity_shape(args_schema)
    property_hints = _property_hints(note, supported_options)
    result_fields = _property_names(result_schema)
    mutation_hints = _mutation_hints(note)
    provenance = _constraint_provenance(
        uri,
        family_value,
        version,
        note_path,
        note,
        operator_allows_official_docs=operator_allows_official_docs,
    )
    facts = SemanticConstraintFacts(
        uri=uri,
        family=family_value,
        version=version,
        required_args=required_args,
        required_arg_families=required_arg_families,
        supported_args=supported_args,
        supported_options=supported_options,
        identity_shape=identity_shape,
        property_hints=property_hints,
        result_shape=_compact_text(str(note.get("return_shape", ""))),
        result_fields=result_fields,
        mutation_hints=mutation_hints,
        source_priority=(
            "packaged-semantic-source-notes",
            "local-versioned-manifest",
            "targeted-uri-schema",
            "official-docs-explicit-only" if operator_allows_official_docs else "official-docs-excluded-by-policy",
        ),
        provenance=provenance,
    )
    facts.as_dict()
    return facts


def _mapping_or_empty(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _builder_family_value(family: BuilderFamily | str) -> str:
    family_value = family.value if isinstance(family, BuilderFamily) else str(family)
    try:
        return BuilderFamily(family_value).value
    except ValueError as exc:
        raise SemanticValidationError(
            SemanticErrorCode.UNSUPPORTED_BUILDER_FAMILY,
            f"Unsupported semantic builder family: {family_value}",
            details={"family": family_value},
        ) from exc


def _source_note_path_for_version(version: str) -> Path:
    if version == DEFAULT_WWISE_VERSION:
        return DEFAULT_SEMANTIC_SOURCE_NOTES
    return DEFAULT_SEMANTIC_SOURCE_ROOT / version / "source_notes.json"


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def _merge_unique(*groups: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    merged: list[str] = []
    for group in groups:
        for item in group:
            if item in seen:
                continue
            seen.add(item)
            merged.append(item)
    return tuple(merged)


def _property_names(schema: Mapping[str, Any]) -> tuple[str, ...]:
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return ()
    return tuple(str(name) for name in properties if isinstance(name, str))


def _note_required_args_for_uri(note: Mapping[str, Any], uri: str) -> tuple[str, ...]:
    prefix = f"{uri}:"
    required: list[str] = []
    for item in _string_tuple(note.get("required_fields")):
        if not item.startswith(prefix):
            continue
        value = item[len(prefix) :].strip()
        if value and value != "no required fields":
            required.append(value)
    return tuple(required)


def _note_options(note: Mapping[str, Any]) -> tuple[str, ...]:
    options: list[str] = []
    for item in _string_tuple(note.get("optional_fields")):
        if item.startswith("options."):
            options.append(item.removeprefix("options."))
        elif item in {"platform", "onNameConflict", "listMode", "autoAddToSourceControl", "importLocation"}:
            options.append(item)
    return tuple(options)


def _identity_shape(schema: Mapping[str, Any]) -> tuple[str, ...]:
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return ()
    shapes: list[str] = []
    if "waql" in properties:
        shapes.append("waql")
    for key in ("object", "parent", "target", "source"):
        if key in properties:
            shapes.append(key)
    from_schema = properties.get("from")
    if isinstance(from_schema, Mapping):
        for branch in _schema_branches(from_schema):
            for required in _required_fields(branch):
                shapes.append(f"from.{required}")
    return _merge_unique(tuple(shapes))


def _schema_branches(schema: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    branches: list[Mapping[str, Any]] = []
    for key in ("oneOf", "anyOf"):
        entries = schema.get(key)
        if not isinstance(entries, list):
            continue
        branches.extend(_mapping_or_empty(entry) for entry in entries)
    return tuple(branches)


def _property_hints(note: Mapping[str, Any], supported_options: tuple[str, ...]) -> tuple[str, ...]:
    hints: list[str] = []
    if "return" in supported_options:
        hints.append("options.return selects returned object properties")
    for item in _string_tuple(note.get("optional_fields")):
        if "propert" in item.lower() or "reference" in item.lower():
            hints.append(_compact_text(item))
    return _merge_unique(tuple(hints))


def _mutation_hints(note: Mapping[str, Any]) -> tuple[str, ...]:
    destructive = _compact_text(str(note.get("destructive_behavior", "")))
    if not destructive:
        return ()
    lowered = destructive.lower()
    mode = "read-only" if "read-only" in lowered else "mutating" if "mutating" in lowered else "behavior"
    return (f"{mode}: {destructive}",)


def _constraint_provenance(
    uri: str,
    family: str,
    version: str,
    note_path: Path,
    note: Mapping[str, Any],
    *,
    operator_allows_official_docs: bool,
) -> tuple[Mapping[str, Any], ...]:
    provenance: list[Mapping[str, Any]] = [
        {
            "source": "packaged-semantic-source-notes",
            "family": family,
            "version": version,
            "path": _compact_resource_path(note_path),
            "fields": ["required_fields", "optional_fields", "return_shape", "destructive_behavior"],
        },
        {
            "source": "local-versioned-manifest",
            "version": version,
            "path": f"resources/manifest/{version}/manifest.json",
        },
        {
            "source": "targeted-uri-schema",
            "version": version,
            "uri": uri,
            "path": f"resources/manifest/{version}/schemas.json#{uri}",
            "facts": ["args", "options", "result"],
        },
    ]
    if operator_allows_official_docs:
        provenance.append(
            {
                "source": "official-docs",
                "status": "explicitly-allowed-by-operator-policy",
                "urls": list(_string_tuple(note.get("official_urls")))[:2],
            }
        )
    return tuple(provenance)


def _compact_resource_path(path: Path) -> str:
    parts = path.parts
    if "resources" in parts:
        index = parts.index("resources")
        return "/".join(parts[index:])
    return path.name


def _compact_text(value: str, limit: int = 320) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _ensure_constraint_facts_size(payload: Mapping[str, Any], uri: str, version: str, size_ceiling: int) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded) > size_ceiling:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            f"Semantic constraint facts for WAAPI URI {uri!r} exceeded the compact size ceiling.",
            details={"uri": uri, "version": version, "size": len(encoded), "size_ceiling": size_ceiling},
        )


def _required_fields(schema: Mapping[str, Any]) -> tuple[str, ...]:
    required = schema.get("required")
    if not isinstance(required, list):
        return ()
    return tuple(str(field) for field in required if isinstance(field, str))


def _required_families(schema: Mapping[str, Any]) -> tuple[tuple[str, ...], ...]:
    families: list[tuple[str, ...]] = []
    for key in ("oneOf", "anyOf"):
        entries = schema.get(key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            family = _required_fields(_mapping_or_empty(entry))
            if family:
                families.append(family)
    return tuple(families)


def _validate_required_alternatives(uri: str, version: str, schema: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
    for key, policy in (("oneOf", "exactly one"), ("anyOf", "at least one")):
        entries = schema.get(key)
        if not isinstance(entries, list):
            continue
        alternatives = tuple(_required_fields(_mapping_or_empty(entry)) for entry in entries)
        alternatives = tuple(fields for fields in alternatives if fields)
        if not alternatives:
            continue
        matches = tuple(fields for fields in alternatives if all(field in payload for field in fields))
        if key == "oneOf" and len(matches) != 1:
            raise _schema_error(
                uri,
                version,
                f"WAAPI URI {uri!r} must satisfy exactly one required args branch.",
                required_policy=policy,
                required_alternatives=alternatives,
                matched_alternatives=matches,
            )
        if key == "anyOf" and not matches:
            raise _schema_error(
                uri,
                version,
                f"WAAPI URI {uri!r} must satisfy at least one required args branch.",
                required_policy=policy,
                required_alternatives=alternatives,
                matched_alternatives=matches,
            )


def _reject_unknown_fields(uri: str, version: str, section: str, schema: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
    if schema.get("additionalProperties") is not False:
        return
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return
    unknown = tuple(sorted(field for field in payload if field not in properties))
    if unknown:
        raise _schema_error(uri, version, f"WAAPI URI {uri!r} has unsupported {section} fields: {', '.join(unknown)}", unknown_fields=unknown, section=section)


def _validate_known_types(uri: str, version: str, section: str, schema: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return
    for field, value in payload.items():
        field_schema = properties.get(field)
        if not isinstance(field_schema, Mapping):
            continue
        expected = field_schema.get("type")
        if not isinstance(expected, str) or not _type_mismatch(expected, value):
            continue
        raise _schema_error(
            uri,
            version,
            f"WAAPI URI {uri!r} field {field!r} expected {expected}, got {type(value).__name__}.",
            section=section,
            field=field,
            expected_type=expected,
            actual_type=type(value).__name__,
        )


def _type_mismatch(expected: str, value: Any) -> bool:
    if expected == "object":
        return not isinstance(value, Mapping)
    if expected == "array":
        return not isinstance(value, list)
    if expected == "string":
        return not isinstance(value, str)
    if expected == "integer":
        return not isinstance(value, int) or isinstance(value, bool)
    if expected == "number":
        return not isinstance(value, (int, float)) or isinstance(value, bool)
    if expected == "boolean":
        return not isinstance(value, bool)
    return False


def _schema_error(uri: str, version: str, message: str, **details: Any) -> SemanticValidationError:
    return SemanticValidationError(
        SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
        message,
        details={"uri": uri, "version": version, **_json_safe_details(details)},
    )


def _json_safe_details(details: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in details.items():
        if isinstance(value, tuple):
            result[key] = [list(item) if isinstance(item, tuple) else item for item in value]
        else:
            result[key] = value
    return result
