"""Closed business contracts for SoundBank planning operations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .business_declarations import SUPPORTED_WWISE_VERSIONS


SOUNDBANK_BUSINESS_CONTRACT = "waapi-skill.soundbank-business/v1"
SOUNDBANK_BUSINESS_OPERATIONS = (
    "soundbank.convertExternalSources",
    "soundbank.generate",
    "soundbank.processDefinitionFiles",
    "soundbank.setInclusions",
)
_POST_2021_OPERATIONS = frozenset(
    {
        "soundbank.convertExternalSources",
        "soundbank.processDefinitionFiles",
    }
)

_DECLARATIONS: dict[str, dict[str, Any]] = {
    "soundbank.generate": {
        "required_fields": ["soundbanks", "platforms", "io_root"],
        "optional_fields": [
            "languages",
            "rebuild_soundbanks",
            "clear_audio_file_cache",
            "rebuild_init_bank",
        ],
        "binding_roles": ["soundbank", "event", "aux_bus"],
        "exact_artifacts": ["io_root"],
    },
    "soundbank.setInclusions": {
        "required_fields": ["soundbank_handle", "mode", "inclusions"],
        "optional_fields": [],
        "binding_roles": ["soundbank", "inclusion_object"],
        "exact_artifacts": [],
    },
    "soundbank.convertExternalSources": {
        "required_fields": ["sources", "io_root"],
        "optional_fields": [],
        "binding_roles": [],
        "exact_artifacts": ["sources[].input", "sources[].output", "io_root"],
    },
    "soundbank.processDefinitionFiles": {
        "required_fields": ["files", "io_root"],
        "optional_fields": [],
        "binding_roles": [],
        "exact_artifacts": ["files[]", "io_root"],
    },
}

_HANDLE = {"type": "string", "pattern": r"^boh1-[0-9a-f]{32}$"}
_FILTERS = {
    "type": "array",
    "minItems": 1,
    "maxItems": 3,
    "uniqueItems": True,
    "items": {
        "type": "string",
        "enum": ["events", "structures", "media"],
    },
}
_DECLARATION_SCHEMAS: dict[str, dict[str, Any]] = {
    "soundbank.generate": {
        "type": "object",
        "additionalProperties": False,
        "required": ["soundbanks", "platforms", "io_root"],
        "properties": {
            "soundbanks": {
                "type": "array",
                "minItems": 1,
                "maxItems": 64,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "soundbank_handle",
                        "artifact_expectation",
                    ],
                    "properties": {
                        "soundbank_handle": _HANDLE,
                        "artifact_expectation": {
                            "type": "string",
                            "enum": ["nonlocalized", "localized", "mixed"],
                        },
                        "rebuild": {"type": "boolean"},
                        "event_handles": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 256,
                            "items": _HANDLE,
                        },
                        "aux_bus_handles": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 256,
                            "items": _HANDLE,
                        },
                        "inclusions": _FILTERS,
                    },
                },
            },
            "platforms": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "items": {"type": "string", "minLength": 1},
            },
            "languages": {
                "type": "array",
                "minItems": 1,
                "maxItems": 64,
                "items": {"type": "string", "minLength": 1},
            },
            "rebuild_soundbanks": {"type": "boolean"},
            "clear_audio_file_cache": {"type": "boolean"},
            "rebuild_init_bank": {"type": "boolean"},
            "io_root": {"type": "string", "minLength": 1},
        },
    },
    "soundbank.setInclusions": {
        "type": "object",
        "additionalProperties": False,
        "required": ["soundbank_handle", "mode", "inclusions"],
        "properties": {
            "soundbank_handle": _HANDLE,
            "mode": {
                "type": "string",
                "enum": ["add", "remove", "replace"],
            },
            "inclusions": {
                "type": "array",
                "maxItems": 128,
                "emptyAllowedWhen": {"mode": "replace"},
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["object_handle", "filters"],
                    "properties": {
                        "object_handle": _HANDLE,
                        "filters": _FILTERS,
                    },
                },
            },
        },
    },
    "soundbank.convertExternalSources": {
        "type": "object",
        "additionalProperties": False,
        "required": ["sources", "io_root"],
        "properties": {
            "sources": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["input", "platform", "output"],
                    "properties": {
                        "input": {"type": "string", "minLength": 1},
                        "platform": {"type": "string", "minLength": 1},
                        "output": {"type": "string", "minLength": 1},
                    },
                },
            },
            "io_root": {"type": "string", "minLength": 1},
        },
    },
    "soundbank.processDefinitionFiles": {
        "type": "object",
        "additionalProperties": False,
        "required": ["files", "io_root"],
        "properties": {
            "files": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "items": {"type": "string", "minLength": 1},
            },
            "io_root": {"type": "string", "minLength": 1},
        },
    },
}


def soundbank_business_contract_data(
    operation: str,
    version: str,
) -> dict[str, Any]:
    """Return one high-level SoundBank plan contract for an exact lane."""

    if operation not in SOUNDBANK_BUSINESS_OPERATIONS:
        raise ValueError("unsupported SoundBank business operation")
    if version not in SUPPORTED_WWISE_VERSIONS or (
        version == "2021.1" and operation in _POST_2021_OPERATIONS
    ):
        raise ValueError("unsupported Wwise version for SoundBank operation")
    declaration = _DECLARATIONS[operation]
    return {
        "contract": SOUNDBANK_BUSINESS_CONTRACT,
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
            "roles": list(declaration["binding_roles"]),
            "role_required": bool(declaration["binding_roles"]),
            "identity": "live_bound_object_handle",
            "validation": "exact_guid_name_type_path",
        },
        "declaration": {
            "subcommand": "draft-declare-soundbank-plan",
            "required_fields": list(declaration["required_fields"]),
            "optional_fields": list(declaration["optional_fields"]),
            "settings_field": "soundbank_plan",
            "submit_once": True,
            "schema": deepcopy(_DECLARATION_SCHEMAS[operation]),
        },
        "exact_user_artifacts": list(declaration["exact_artifacts"]),
        "gateway_derivations": [
            "native_object_paths_and_identity_selectors",
            "wire_types_and_request_envelope",
            "dependency_order_and_batch_layout",
            "language_skip_and_artifact_plan",
        ],
        "legacy_composer_public": False,
        "legacy_inline_typed_public": False,
        "safety": {
            "immutable_preview": True,
            "single_execute": True,
            "object_revalidation": "exact_guid_name_type_path",
            "file_revalidation": "exact_path_size_mtime_sha256",
            "artifact_verification": "operation_specific",
        },
    }


__all__ = [
    "SOUNDBANK_BUSINESS_CONTRACT",
    "SOUNDBANK_BUSINESS_OPERATIONS",
    "soundbank_business_contract_data",
]
