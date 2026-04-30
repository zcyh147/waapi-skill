"""Schema-aware semantic validation helpers for reflected WAAPI resources."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from wwise_waapi.dispatcher import DEFAULT_WWISE_VERSION

from .common import ManifestSchemaLoader, SemanticErrorCode, SemanticValidationError


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
        missing_families = tuple(family for family in required_families if not any(field in arg_payload for field in family))
        if missing_families:
            raise _schema_error(
                uri,
                self.version,
                f"WAAPI URI {uri!r} is missing one required arg family.",
                missing_arg_families=missing_families,
            )

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


def _mapping_or_empty(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


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
        family = tuple(field for entry in entries for field in _required_fields(_mapping_or_empty(entry)))
        if family:
            families.append(family)
    return tuple(families)


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
