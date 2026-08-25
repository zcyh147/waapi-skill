"""Registry-owned public contract data for the deep ``audio.import`` Adapter."""

from __future__ import annotations

from typing import Any

from .business_declarations import SUPPORTED_BUSINESS_KINDS, SUPPORTED_WWISE_VERSIONS


AUDIO_IMPORT_BUSINESS_CONTRACT = "waapi-skill.audio-import-business/v1"
AUDIO_IMPORT_BUSINESS_SETTING_FIELDS = (
    "add_to_source_control",
    "check_out_from_source_control",
    "defaults",
    "mode",
)
AUDIO_IMPORT_BUSINESS_VALUE_TYPES = {
    "audio_source_notes": "string",
    "dialogue_event_directive": "string",
    "inline_wav": "string",
    "language": "string",
    "loop": "string",
    "max_instances": "integer",
    "media_file": "string",
    "notes": "string",
    "originals_subfolder": "string",
    "output_bus": "reference",
    "override_parent_instance_limit": "boolean",
    "switch_value": "string",
    "volume_db": "number",
}
AUDIO_IMPORT_BUSINESS_DECLARATION_FIELDS = (
    *tuple(AUDIO_IMPORT_BUSINESS_VALUE_TYPES),
    "event",
    "field_values",
)
AUDIO_IMPORT_BUSINESS_MODES = {
    "create": "createNew",
    "reimport": "useExisting",
    "replace": "replaceExisting",
}
AUDIO_IMPORT_EVENT_ACTIONS = ("Break", "Pause", "Play", "Resume", "Seek", "Stop")
AUDIO_IMPORT_BUSINESS_COMMANDS = (
    "draft-bind-object",
    "draft-bind-field",
    "draft-business-configure",
    "draft-declare-new",
    "draft-declare-existing",
    "draft-revise-declaration",
    "draft-remove-declaration",
    "draft-check",
    "preview-from-draft",
)


def audio_import_business_contract_data(version: str) -> dict[str, Any]:
    """Return the closed versioned shape consumed by Registry publication."""

    if version not in SUPPORTED_WWISE_VERSIONS:
        raise ValueError("unsupported Wwise version")
    return {
        "contract": AUDIO_IMPORT_BUSINESS_CONTRACT,
        "operation": "audio.import",
        "version": version,
        "input_mode": "business_declaration",
        "settings": list(AUDIO_IMPORT_BUSINESS_SETTING_FIELDS),
        "declaration_fields": sorted(AUDIO_IMPORT_BUSINESS_DECLARATION_FIELDS),
        "field_value_types": dict(AUDIO_IMPORT_BUSINESS_VALUE_TYPES),
        "semantic_kinds": list(SUPPORTED_BUSINESS_KINDS),
        "modes": sorted(AUDIO_IMPORT_BUSINESS_MODES),
        "event_actions": list(AUDIO_IMPORT_EVENT_ACTIONS),
        "gateway_derivations": [
            "canonical_object_path",
            "native_object_type",
            "sfx_import_language",
            "target_parent_handle",
            "unique_name_to_object_handle",
            "dependency_order",
            "batch_layout",
            "native_request",
            "continuation",
        ],
        "live_handles": [
            "bound_object_handle",
            "field_handle",
            "typed_field_value",
        ],
        "exact_user_artifacts": ["media_file", "inline_wav"],
        "commands": list(AUDIO_IMPORT_BUSINESS_COMMANDS),
        "start": {
            "subcommand": "draft-start",
            "gateway_argv": ["draft-start", "audio.import"],
            "copy_exactly": True,
            "append_arguments": "forbidden",
            "preview_change_intent": "gateway_inferred_from_checked_business_draft",
            "first_required_phase": (
                "bind_only_handle_typed_business_objects_then_configure_and_declare"
            ),
        },
        "field_transport": {
            "literal_fields": sorted(
                name
                for name, value_type in AUDIO_IMPORT_BUSINESS_VALUE_TYPES.items()
                if value_type != "reference"
            ),
            "bound_object_handle_fields": ["output_bus"],
            "bound_field_handle_container": "field_values",
            "dedicated_declaration_parameters": {
                "switch_value": "--switch-value",
            },
            "generic_declaration_field_exclusions": ["switch_value"],
            "reference_value_rule": (
                "copy_one_bound_object_handle_never_a_path_or_name"
            ),
            "switch_value_rule": "copy_the_user_requested_switch_value_name",
            "language_rule": (
                "derive_SFX_from_sound-sfx_else_copy_exact_project_language"
            ),
        },
        "declaration_discipline": {
            "task_local_id": "bounded_unique_not_business_data",
            "known_user_fields": "complete_on_first_submission",
            "revise_only_for": "correction_or_late_discovered_fact",
            "check_only_after": "all_user_requested_declarations_are_complete",
        },
        "legacy_shallow_composer_public": False,
        "safety": {
            "immutable_preview": True,
            "single_execute": True,
            "object_revalidation": "exact_guid_name_type_path",
            "field_revalidation": "exact_scope_token_metadata_platform",
            "legacy_shallow_composer_public": False,
        },
        "version_features": {
            "check_out_from_source_control": version
            in {"2023.1", "2024.1", "2025.1"},
        },
    }


__all__ = [
    "AUDIO_IMPORT_BUSINESS_COMMANDS",
    "AUDIO_IMPORT_BUSINESS_CONTRACT",
    "AUDIO_IMPORT_BUSINESS_DECLARATION_FIELDS",
    "AUDIO_IMPORT_BUSINESS_MODES",
    "AUDIO_IMPORT_BUSINESS_SETTING_FIELDS",
    "AUDIO_IMPORT_BUSINESS_VALUE_TYPES",
    "AUDIO_IMPORT_EVENT_ACTIONS",
    "audio_import_business_contract_data",
]
