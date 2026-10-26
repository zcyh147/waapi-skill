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
            "all_user_soundbanks",
            "write_to_disk",
            "skip_languages",
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
                "minItems": 0,
                "maxItems": 64,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["artifact_expectation"],
                    "oneOf": [{"required": ["soundbank_handle"]}, {"required": ["name"]}],
                    "properties": {
                        "soundbank_handle": _HANDLE,
                        "name": {"type": "string", "pattern": r"^[A-Za-z_][A-Za-z0-9_]*$", "description": "Temporary bank name; must not collide with a live SoundBank. Use this name as the bank selection key for nested Event/AuxBus/inclusion choices."},
                        "artifact_expectation": {
                            "type": "string",
                            "enum": ["nonlocalized", "localized", "mixed"],
                        },
                        "rebuild": {"type": "boolean"},
                        "event_handles": {
                            "type": "array",
                            "minItems": 0,
                            "maxItems": 256,
                            "items": _HANDLE,
                        },
                        "aux_bus_handles": {
                            "type": "array",
                            "minItems": 0,
                            "maxItems": 256,
                            "items": _HANDLE,
                        },
                        "inclusions": {**_FILTERS, "minItems": 0},
                    },
                },
            },
            "all_user_soundbanks": {"type": "string", "enum": ["nonlocalized", "localized", "mixed"],
                "description": "Generate all live user SoundBanks using this common expected artifact layout; soundbanks must be empty. Preview binds at most 64 live banks and rejects selection drift. 2023–25 dispatch an empty native list; 2021–22 enumerate that exact bounded live selection because their reflection does not document empty-list meaning."},
            "write_to_disk": {"oneOf": [{"type": "boolean"}, {"const": "native-default"}],
                "default": True, "description": "Public default true preserves file generation. false explicitly selects memory generation; native-default omits native writeToDisk (documented false). Memory mode checks only the bounded result schema, diagnostics and input/output guards; it never verifies bank data or delivered artifacts. To receive memory data, establish the existing Gateway soundbank.generated Topic workflow before generation."},
            "skip_languages": {"oneOf": [{"type": "boolean"}, {"const": "native-default"}],
                "description": "Public default derives from artifact layout for compatibility. Explicit true suppresses localized banks; false enables selected/all project languages; native-default omits native skipLanguages. Omitted languages select all live project languages without synthesizing a native languages array."},
            "platforms": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "items": {"type": "string", "minLength": 1},
            },
            "languages": {
                "type": "array",
                "minItems": 0,
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
    result = {
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

    if operation == "soundbank.generate":
        result["verification_modes"] = {
            "files": "Each declared bank/platform/language artifact must be independently nonempty and changed; source and owned-I/O guards remain mandatory.",
            "memory": "Only the bounded reflected call result and diagnostics are checked; business_state_verified=false. No bank data is returned or captured by this transaction.",
            "memory_data_observation": {"before_generation": "Use the existing Gateway topic-schema and stream-topic workflow for ak.wwise.core.soundbank.generated before generation; the generation call cannot reconstruct missed events.",
                "topic_schema_argv": ["topic-schema", "ak.wwise.core.soundbank.generated"],
                "transaction_captures_topic_data": False},
        }
    return result


__all__ = [
    "SOUNDBANK_BUSINESS_CONTRACT",
    "SOUNDBANK_BUSINESS_OPERATIONS",
    "soundbank_business_contract_data",
]
