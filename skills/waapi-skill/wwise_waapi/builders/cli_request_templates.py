"""Manifest-backed request constraints for the four reviewed Wwise CLI routes.

The public result is deliberately *not* a JSON request with placeholder values.
It describes the exact operation-envelope paths, reflected argument fields, and
isolated-I/O boundary so an agent can collect real user values before building
an immutable preview.  Keeping this as constraints-only data prevents a model
from copying an illustrative payload and accidentally executing it.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS


CLI_REQUEST_TEMPLATE_CONTRACT = "waapi-skill.cli-request-template/v1"
CLI_REQUEST_TEMPLATE_SET_CONTRACT = "waapi-skill.cli-request-template-set/v1"
CLI_REQUEST_TEMPLATE_URIS = (
    "ak.wwise.cli.generateSoundbank",
    "ak.wwise.cli.tabDelimitedImport",
    "ak.wwise.cli.convertExternalSource",
    "ak.wwise.cli.migrate",
)

_OPERATION_REQUEST_CONTRACT = "waapi-skill.operation-request/v1"
_ALL_VERSIONS = frozenset(SUPPORTED_WWISE_VERSION_KEYS)
_VERSIONS_2022_PLUS = frozenset({"2022.1", "2023.1", "2024.1", "2025.1"})
_VERSIONS_2023_PLUS = frozenset({"2023.1", "2024.1", "2025.1"})
_VERSIONS_BEFORE_2024 = frozenset({"2021.1", "2022.1", "2023.1"})

# These are invariants over the packaged reflected schemas, not substitute
# documentation.  A manifest refresh that changes one of the reviewed deltas
# fails closed until the public template is reviewed again.
_REVIEWED_VERSION_FIELD_PRESENCE: Mapping[
    str, Mapping[str, frozenset[str]]
] = {
    "ak.wwise.cli.generateSoundbank": {
        "no-source-control": _VERSIONS_2022_PLUS,
        "root-output-path": _VERSIONS_2022_PLUS,
        # This is the exact reflected field name.  ``use-user-settings`` is not
        # present in any supported manifest and must never be invented.
        "use-user-overrides": _VERSIONS_2022_PLUS,
        "license-file": _VERSIONS_2023_PLUS,
        "no-wwise-dat": _VERSIONS_BEFORE_2024,
    },
    "ak.wwise.cli.tabDelimitedImport": {
        "no-source-control": _VERSIONS_2023_PLUS,
    },
    "ak.wwise.cli.convertExternalSource": {
        "no-wwise-dat": _VERSIONS_BEFORE_2024,
    },
    "ak.wwise.cli.migrate": {
        "no-source-control": _VERSIONS_2023_PLUS,
    },
}

_EXPECTED_REQUIRED_FIELDS: Mapping[str, tuple[str, ...]] = {
    "ak.wwise.cli.generateSoundbank": ("project",),
    "ak.wwise.cli.tabDelimitedImport": (
        "project",
        "tab-delimited-import-file",
    ),
    "ak.wwise.cli.convertExternalSource": ("project",),
    "ak.wwise.cli.migrate": ("project",),
}

_IO_ROOT_RULES: Mapping[str, Mapping[str, Any]] = {
    "ak.wwise.cli.generateSoundbank": {
        "derivation": (
            "deepest common absolute ancestor of every resolved explicit write "
            "path in soundbank-path, cache, root-output-path, header-file-path, "
            "and output that is present"
        ),
        "implicit_write_boundary": (
            "SoundBank generation may also write Wwise-managed bank, media, and "
            "cache artifacts whose physical confinement is not claimed"
        ),
    },
    "ak.wwise.cli.tabDelimitedImport": {
        "derivation": "absolute directory containing the case-owned project file",
        "implicit_write_boundary": (
            "the project and imported work-unit/media content are mutation "
            "targets inside the isolated case"
        ),
    },
    "ak.wwise.cli.convertExternalSource": {
        "derivation": (
            "deepest common absolute ancestor of every explicit output "
            "directory; require a narrower common root when that is only the "
            "filesystem root"
        ),
        "implicit_write_boundary": (
            "conversion may use Wwise-managed output locations when output is "
            "omitted, so physical confinement is not claimed for implicit writes"
        ),
    },
    "ak.wwise.cli.migrate": {
        "derivation": "absolute directory containing the case-owned project file",
        "implicit_write_boundary": (
            "migration rewrites the isolated project and has no automatic retry"
        ),
    },
}


class CliRequestTemplateError(ValueError):
    """Fail-closed packaged-schema/template inconsistency."""

    error_code = "CLI_REQUEST_TEMPLATE_INVALID"


def is_cli_request_template_uri(uri: str) -> bool:
    """Return whether ``uri`` owns one reviewed constraints-only template."""

    return uri in CLI_REQUEST_TEMPLATE_URIS


def build_cli_request_template(
    *,
    version: str,
    uri: str,
    schema: Mapping[str, Any],
    forbidden_fields: Sequence[str] = (),
) -> dict[str, Any]:
    """Build one non-executable, version-aware CLI request constraint record."""

    if version not in _ALL_VERSIONS:
        raise CliRequestTemplateError(
            f"Unsupported Wwise version for CLI request template: {version!r}"
        )
    if uri not in CLI_REQUEST_TEMPLATE_URIS:
        raise CliRequestTemplateError(
            f"No reviewed CLI request template exists for {uri!r}"
        )

    args_schema = _require_mapping(schema.get("argsSchema"), "argsSchema", uri, version)
    options_schema = _require_mapping(
        schema.get("optionsSchema"), "optionsSchema", uri, version
    )
    _require_closed_object_schema(args_schema, "argsSchema", uri, version)
    _require_closed_object_schema(options_schema, "optionsSchema", uri, version)

    properties = _require_mapping(
        args_schema.get("properties"), "argsSchema.properties", uri, version
    )
    reflected_fields = tuple(
        sorted(name for name in properties if isinstance(name, str))
    )
    if len(reflected_fields) != len(properties):
        raise CliRequestTemplateError(
            f"{uri!r} in Wwise {version} has a non-string reflected argument field"
        )
    required_fields = _required_fields(args_schema, uri=uri, version=version)
    unknown_required = tuple(
        field for field in required_fields if field not in properties
    )
    if unknown_required:
        raise CliRequestTemplateError(
            f"{uri!r} in Wwise {version} requires fields absent from its "
            f"properties: {', '.join(unknown_required)}"
        )
    expected_required = _EXPECTED_REQUIRED_FIELDS[uri]
    if required_fields != expected_required:
        raise CliRequestTemplateError(
            f"{uri!r} in Wwise {version} changed its reviewed required fields: "
            f"expected {expected_required!r}, found {required_fields!r}"
        )

    option_properties = _require_mapping(
        options_schema.get("properties"),
        "optionsSchema.properties",
        uri,
        version,
    )
    option_required = _required_fields(
        options_schema,
        uri=uri,
        version=version,
    )
    if option_properties or option_required:
        raise CliRequestTemplateError(
            f"{uri!r} in Wwise {version} no longer has the reviewed exact-empty "
            "options contract"
        )

    _validate_reviewed_version_deltas(
        version=version,
        uri=uri,
        reflected_fields=frozenset(reflected_fields),
    )
    reflected_forbidden = tuple(
        sorted(field for field in set(forbidden_fields) if field in properties)
    )
    unknown_forbidden = tuple(
        sorted(field for field in set(forbidden_fields) if field not in properties)
    )
    if unknown_forbidden:
        raise CliRequestTemplateError(
            f"{uri!r} in Wwise {version} declares blocked fields absent from its "
            f"manifest schema: {', '.join(unknown_forbidden)}"
        )
    accepted_fields = tuple(
        field for field in reflected_fields if field not in reflected_forbidden
    )
    field_constraints = {
        field: _compact_field_constraint(
            _require_mapping(
                properties[field],
                f"argsSchema.properties.{field}",
                uri,
                version,
            )
        )
        for field in reflected_fields
    }
    delta_fields = _REVIEWED_VERSION_FIELD_PRESENCE[uri]

    return {
        "contract": CLI_REQUEST_TEMPLATE_CONTRACT,
        "status": "constraints_only_not_executable",
        "version": version,
        "api": uri,
        "operation": "waapi.call",
        "request_paths": {
            "contract": {
                "path": "$.contract",
                "const": _OPERATION_REQUEST_CONTRACT,
            },
            "version": {"path": "$.version", "const": version},
            "operation": {"path": "$.operation", "const": "waapi.call"},
            "api": {"path": "$.arguments.api", "const": uri},
            "args": {
                "path": "$.arguments.args",
                "constraint_source": "packaged reflected argsSchema",
            },
            "options": {"path": "$.arguments.options", "const": {}},
            "io_root": {
                "path": "$.arguments.io_root",
                "type": "string",
                "required": True,
                "absolute": True,
                **dict(_IO_ROOT_RULES[uri]),
            },
        },
        "args_constraints": {
            "type": "object",
            "additional_properties": False,
            "required_fields": list(required_fields),
            "reflected_fields": list(reflected_fields),
            "accepted_fields": list(accepted_fields),
            "blocked_fields": list(reflected_forbidden),
            "fields": field_constraints,
        },
        "version_delta_fields": {
            "available": sorted(field for field in delta_fields if field in properties),
            "absent": sorted(field for field in delta_fields if field not in properties),
        },
        "materialization_policy": {
            "directly_executable": False,
            "payload_values_included": False,
            "assemble_only_after_user_values_are_complete": True,
            "manifest_field_names_only": True,
            "unknown_fields": "reject_before_preview",
            "missing_required_fields": "reject_before_preview",
            "blocked_fields": "reject_before_preview",
            "placeholder_values": "not_provided",
        },
    }


def build_cli_request_template_set(
    *,
    version: str | None,
    schemas: Mapping[str, Mapping[str, Any]] | None = None,
    forbidden_fields_by_uri: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    """Build the four-template set or a version-required boundary."""

    if version is None:
        return {
            "contract": CLI_REQUEST_TEMPLATE_SET_CONTRACT,
            "status": "version_required",
            "version": None,
            "apis": list(CLI_REQUEST_TEMPLATE_URIS),
            "templates": {},
        }
    if version not in _ALL_VERSIONS:
        raise CliRequestTemplateError(
            f"Unsupported Wwise version for CLI request templates: {version!r}"
        )
    if schemas is None:
        raise CliRequestTemplateError(
            "Packaged reflected schemas are required for a versioned CLI template set"
        )
    blocked = forbidden_fields_by_uri or {}
    missing = tuple(uri for uri in CLI_REQUEST_TEMPLATE_URIS if uri not in schemas)
    if missing:
        raise CliRequestTemplateError(
            f"Wwise {version} is missing reviewed CLI schemas: {', '.join(missing)}"
        )
    detailed_templates = [
        build_cli_request_template(
            version=version,
            uri=uri,
            schema=schemas[uri],
            forbidden_fields=blocked.get(uri, ()),
        )
        for uri in CLI_REQUEST_TEMPLATE_URIS
    ]
    templates = {
        template["api"]: {
            "required": template["args_constraints"]["required_fields"],
            "blocked": template["args_constraints"]["blocked_fields"],
            "version_delta_fields": {
                **{
                    field: True
                    for field in template["version_delta_fields"]["available"]
                },
                **{
                    field: False
                    for field in template["version_delta_fields"]["absent"]
                },
            },
        }
        for template in detailed_templates
    }
    return {
        "contract": CLI_REQUEST_TEMPLATE_SET_CONTRACT,
        "status": "ready",
        "version": version,
        "templates": templates,
        "policy": {
            "directly_executable": False,
            "detail": "run describe for the exact API",
        },
    }


def _require_mapping(
    value: Any,
    field: str,
    uri: str,
    version: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CliRequestTemplateError(
            f"{uri!r} in Wwise {version} has no usable {field} object"
        )
    return value


def _require_closed_object_schema(
    schema: Mapping[str, Any],
    field: str,
    uri: str,
    version: str,
) -> None:
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise CliRequestTemplateError(
            f"{uri!r} in Wwise {version} no longer has a closed object {field}"
        )


def _required_fields(
    schema: Mapping[str, Any],
    *,
    uri: str,
    version: str,
) -> tuple[str, ...]:
    raw = schema.get("required")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise CliRequestTemplateError(
            f"{uri!r} in Wwise {version} has a malformed required-field list"
        )
    if any(not isinstance(field, str) or not field for field in raw):
        raise CliRequestTemplateError(
            f"{uri!r} in Wwise {version} has an invalid required-field name"
        )
    if len(set(raw)) != len(raw):
        raise CliRequestTemplateError(
            f"{uri!r} in Wwise {version} has duplicate required fields"
        )
    return tuple(raw)


def _validate_reviewed_version_deltas(
    *,
    version: str,
    uri: str,
    reflected_fields: frozenset[str],
) -> None:
    if "use-user-settings" in reflected_fields:
        raise CliRequestTemplateError(
            f"{uri!r} in Wwise {version} unexpectedly exposes the unreviewed "
            "'use-user-settings' spelling"
        )
    for field, expected_versions in _REVIEWED_VERSION_FIELD_PRESENCE[uri].items():
        expected = version in expected_versions
        actual = field in reflected_fields
        if actual != expected:
            availability = "present" if expected else "absent"
            raise CliRequestTemplateError(
                f"{uri!r} field {field!r} in Wwise {version} must be "
                f"{availability} under the reviewed version contract"
            )


def _compact_field_constraint(schema: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(schema.get("$ref"), str):
        result["schema_ref"] = schema["$ref"]
    for key in (
        "type",
        "format",
        "pattern",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "uniqueItems",
        "const",
    ):
        if key in schema:
            result[key] = schema[key]
    enum = schema.get("enum")
    if isinstance(enum, list):
        result["enum"] = list(enum)
    one_of = schema.get("oneOf")
    if isinstance(one_of, list):
        result["one_of"] = [
            _compact_union_variant(item)
            for item in one_of
            if isinstance(item, Mapping)
        ]
    synopsis = schema.get("synopsis")
    if isinstance(synopsis, list):
        result["cli_synopsis"] = [
            item for item in synopsis if isinstance(item, str)
        ]
    if not result:
        result["shape"] = "reflected_schema_has_no_inline_constraints"
    return result


def _compact_union_variant(schema: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(schema.get("$ref"), str):
        result["schema_ref"] = schema["$ref"]
    if "type" in schema:
        result["type"] = schema["type"]
    if isinstance(schema.get("enum"), list):
        result["enum"] = list(schema["enum"])
    return result or {"shape": "unresolved_reflected_variant"}
