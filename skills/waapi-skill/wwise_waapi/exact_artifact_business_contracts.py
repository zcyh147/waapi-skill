"""Closed contracts for exact tabular and Lua artifact operations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .builders.debug_lua import (
    MAX_LUA_SOURCE_BYTES,
    MAX_LUA_WA_ARGS_BYTES,
    MAX_LUA_WA_ARGS_KEYS,
)
from .business_declarations import SUPPORTED_WWISE_VERSIONS


EXACT_ARTIFACT_BUSINESS_CONTRACT = "waapi-skill.exact-artifact-business/v1"
EXACT_ARTIFACT_BUSINESS_OPERATIONS = (
    "audio.importTabDelimited",
    "lua.executeCliFile",
    "lua.executeCoreFile",
    "lua.executeCoreInline",
)

_VERSIONS = {
    "audio.importTabDelimited": SUPPORTED_WWISE_VERSIONS,
    "lua.executeCliFile": SUPPORTED_WWISE_VERSIONS[2:],
    "lua.executeCoreFile": SUPPORTED_WWISE_VERSIONS[2:],
    "lua.executeCoreInline": ("2025.1",),
}
_REQUIRED_FIELDS = {
    "audio.importTabDelimited": [
        "table_file",
        "location_handle",
        "language",
    ],
    "lua.executeCliFile": ["script_file"],
    "lua.executeCoreFile": ["script_file"],
    "lua.executeCoreInline": ["lua_source", "io_root"],
}
_BINDING_ROLES = {
    "audio.importTabDelimited": ["import_location"],
    "lua.executeCliFile": [],
    "lua.executeCoreFile": [],
    "lua.executeCoreInline": [],
}

_STRICT_JSON_VALUE_SCHEMA: dict[str, Any] = {
    "anyOf": [
        {"type": "null"},
        {"type": "boolean"},
        {"type": "string"},
        {"type": "integer"},
        {"type": "number", "finite": True},
        {
            "type": "array",
            "items": {"$ref": "#/$defs/strictJsonValue"},
        },
        {
            "type": "object",
            "additionalProperties": {
                "$ref": "#/$defs/strictJsonValue",
            },
        },
    ]
}


def exact_artifact_business_contract_data(
    operation: str,
    version: str,
) -> dict[str, Any]:
    """Return the singular high-level declaration for one exact lane."""

    if operation not in EXACT_ARTIFACT_BUSINESS_OPERATIONS:
        raise ValueError("unsupported exact-artifact operation")
    if version not in _VERSIONS[operation]:
        raise ValueError("unsupported Wwise version for exact-artifact operation")
    schema = _schema(operation, version)
    public_fields = list(schema["properties"])
    required = _REQUIRED_FIELDS[operation]
    return {
        "contract": EXACT_ARTIFACT_BUSINESS_CONTRACT,
        "operation": operation,
        "version": version,
        "input_mode": "business_declaration",
        "start": {
            "subcommand": "draft-start",
            "gateway_argv": ["draft-start", operation],
            "copy_exactly": True,
            "append_arguments": "forbidden",
        },
        "binding": {
            "subcommand": "draft-bind-object",
            "roles": list(_BINDING_ROLES[operation]),
            "role_required": bool(_BINDING_ROLES[operation]),
            "available": bool(_BINDING_ROLES[operation]),
            "identity": "live_bound_object_handle",
            "validation": "exact_guid_name_type_path",
        },
        "declaration": {
            "subcommand": "draft-declare-artifact-plan",
            "settings_field": "artifact_plan",
            "submit_once": True,
            "required_fields": list(required),
            "optional_fields": sorted(set(public_fields) - set(required)),
            "public_fields": list(public_fields),
            "schema": deepcopy(schema),
        },
        "exact_user_artifacts": (
            ["table_file"]
            if operation == "audio.importTabDelimited"
            else ["script_file", "arguments"]
            if operation.endswith("File")
            else ["lua_source", "io_root", "arguments"]
        ),
        "gateway_derivations": [
            "source_authority_and_io_root",
            "native_loader_fields",
            "native_mode_and_identity_selector",
            "request_order_and_serialization",
            "bounded_file_or_source_evidence",
        ],
        "legacy_composer_public": False,
        "legacy_inline_typed_public": False,
        "safety": {
            "immutable_preview": True,
            "single_execute": True,
            "file_revalidation": "exact_path_size_mtime_sha256",
            "source_preservation": "exact_utf8_bytes",
            "loader_reserved_keys": "gateway_owned",
        },
    }


def _schema(operation: str, version: str) -> dict[str, Any]:
    properties: dict[str, Any]
    if operation == "audio.importTabDelimited":
        properties = {
            "table_file": {"type": "string", "minLength": 1},
            "location_handle": {
                "type": "string",
                "pattern": r"^boh1-[0-9a-f]{32}$",
            },
            "language": {"type": "string", "minLength": 1},
            "mode": {
                "type": "string",
                "enum": ["create", "reimport", "replace"],
            },
            "add_to_source_control": {"type": "boolean"},
        }
        if version in {"2023.1", "2024.1", "2025.1"}:
            properties["check_out_from_source_control"] = {"type": "boolean"}
    else:
        properties = {
            "arguments": {
                "type": "object",
                "maxProperties": MAX_LUA_WA_ARGS_KEYS,
                "maximumBytes": MAX_LUA_WA_ARGS_BYTES,
                "additionalProperties": {
                    "$ref": "#/$defs/strictJsonValue",
                },
            }
        }
        if operation.endswith("File"):
            properties["script_file"] = {"type": "string", "minLength": 1}
            if operation == "lua.executeCliFile" and version in {
                "2024.1",
                "2025.1",
            }:
                properties["watchdog_seconds"] = {
                    "type": "integer",
                    "minimum": 0,
                }
        else:
            properties.update(
                {
                    "lua_source": {
                        "type": "string",
                        "minLength": 1,
                        "maximumBytes": MAX_LUA_SOURCE_BYTES,
                    },
                    "io_root": {"type": "string", "minLength": 1},
                }
            )
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": list(_REQUIRED_FIELDS[operation]),
        "properties": properties,
    }
    if operation.startswith("lua."):
        schema["$defs"] = {
            "strictJsonValue": deepcopy(_STRICT_JSON_VALUE_SCHEMA),
        }
    return schema


__all__ = [
    "EXACT_ARTIFACT_BUSINESS_CONTRACT",
    "EXACT_ARTIFACT_BUSINESS_OPERATIONS",
    "exact_artifact_business_contract_data",
]
