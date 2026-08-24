"""Generated lossless-cutover inventory for the legacy ``audio.import`` Composer."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .business_declarations import SUPPORTED_WWISE_VERSIONS
from .canonical import canonical_sha256, strict_json_copy
from .operation_composer import operation_composer_contract
from .operation_registry import audio_import_composer_fragment_contract


AUDIO_IMPORT_MIGRATION_INVENTORY_CONTRACT = (
    "waapi-skill.audio-import-business-migration/v1"
)
AUDIO_IMPORT_MIGRATION_RESOURCE = (
    Path(__file__).resolve().parents[1]
    / "resources"
    / "business"
    / "audio-import-migration.json"
)
MIGRATION_DESTINATION_KINDS = frozenset(
    {
        "stable_business_field",
        "gateway_derivation",
        "live_field_handle",
        "bound_object_handle",
        "exact_user_artifact",
        "closed_adapter",
        "prohibited_boundary",
    }
)

_REQUEST_OPTION_MIGRATION: Mapping[str, Mapping[str, Any]] = {
    "import_operation": {
        "destination_kind": "stable_business_field",
        "destination": "mode",
        "ownership": "user_when_explicit_else_gateway_unique_derivation",
        "omission": "derive_only_unique_mode_else_repair",
    },
    "auto_add_to_source_control": {
        "destination_kind": "stable_business_field",
        "destination": "add_to_source_control",
        "ownership": "user_explicit_batch_setting",
        "omission": "gateway_native_default_false",
    },
    "auto_check_out_to_source_control": {
        "destination_kind": "stable_business_field",
        "destination": "check_out_from_source_control",
        "ownership": "user_explicit_batch_setting",
        "omission": "gateway_version_default_false_or_absent",
    },
}

_ROW_FIELD_MIGRATION: Mapping[str, Mapping[str, Any]] = {
    "audio_file": {
        "destination_kind": "exact_user_artifact",
        "destination": "media_file",
        "ownership": "user_selected_regular_file",
        "omission": "preserve_omission_for_structure_only_declaration",
    },
    "audio_file_base64": {
        "destination_kind": "exact_user_artifact",
        "destination": "inline_wav",
        "ownership": "user_owned_opaque_inline_wav",
        "omission": "preserve_omission",
    },
    "audio_source_notes": {
        "destination_kind": "stable_business_field",
        "destination": "audio_source_notes",
        "ownership": "user_explicit_business_text",
        "omission": "preserve_omission",
    },
    "dialogue_event": {
        "destination_kind": "closed_adapter",
        "destination": "dialogue_event_directive",
        "ownership": "exact_user_requested_native_directive_only",
        "omission": "preserve_omission",
    },
    "event": {
        "destination_kind": "closed_adapter",
        "destination": "event_declaration",
        "ownership": "bound_event_parent_name_and_business_action",
        "omission": "preserve_omission",
    },
    "import_language": {
        "destination_kind": "stable_business_field",
        "destination": "language",
        "ownership": "user_explicit_or_project_validated_sfx_consequence",
        "omission": "required_for_media_unless_uniquely_derived",
    },
    "import_location": {
        "destination_kind": "gateway_derivation",
        "destination": "target_parent_handle",
        "ownership": "gateway_from_target_parent_or_exact_user_handle",
        "omission": "derive_from_target_form",
    },
    "notes": {
        "destination_kind": "stable_business_field",
        "destination": "notes",
        "ownership": "user_explicit_business_text",
        "omission": "preserve_omission",
    },
    "object_path": {
        "destination_kind": "gateway_derivation",
        "destination": "canonical_object_path",
        "ownership": "gateway_from_parent_handle_name_and_kind",
        "omission": "not_a_model_input",
    },
    "object_type": {
        "destination_kind": "gateway_derivation",
        "destination": "native_object_type",
        "ownership": "gateway_from_semantic_kind_and_version",
        "omission": "not_a_model_input",
    },
    "originals_subfolder": {
        "destination_kind": "stable_business_field",
        "destination": "originals_subfolder",
        "ownership": "user_explicit_relative_destination",
        "omission": "preserve_omission",
    },
    "properties": {
        "destination_kind": "live_field_handle",
        "destination": "property_field_values",
        "ownership": "live_metadata_bound_field_handle_and_typed_value",
        "omission": "preserve_omission",
    },
    "references": {
        "destination_kind": "live_field_handle",
        "destination": "reference_field_values",
        "ownership": "live_metadata_bound_field_and_object_handles",
        "omission": "preserve_omission",
    },
    "switch_assignment": {
        "destination_kind": "stable_business_field",
        "destination": "switch_value",
        "ownership": "user_business_value_with_gateway_context_binding",
        "omission": "preserve_omission",
    },
}

_NESTED_FIELD_MIGRATION: Mapping[str, Mapping[str, Any]] = {
    "audio_file_base64.relative_path": {
        "destination_kind": "exact_user_artifact",
        "destination": "inline_wav.relative_path",
    },
    "audio_file_base64.base64": {
        "destination_kind": "exact_user_artifact",
        "destination": "inline_wav.opaque_base64",
    },
    "event.action": {
        "destination_kind": "stable_business_field",
        "destination": "event_action",
    },
    "event.path": {
        "destination_kind": "bound_object_handle",
        "destination": "bound_event_parent_handle",
    },
    "import_location.kind": {
        "destination_kind": "gateway_derivation",
        "destination": "target_parent_handle.form",
    },
    "import_location.value": {
        "destination_kind": "bound_object_handle",
        "destination": "target_parent_handle",
    },
    "import_location.type": {
        "destination_kind": "gateway_derivation",
        "destination": "bound_parent_expected_type",
    },
    "import_location.name": {
        "destination_kind": "gateway_derivation",
        "destination": "bound_parent_exact_name",
    },
    "import_location.parent": {
        "destination_kind": "bound_object_handle",
        "destination": "bound_parent_scope_handle",
    },
    "properties[].name": {
        "destination_kind": "live_field_handle",
        "destination": "field_handle",
    },
    "properties[].value": {
        "destination_kind": "stable_business_field",
        "destination": "typed_field_value",
    },
    "references[].name": {
        "destination_kind": "live_field_handle",
        "destination": "field_handle",
    },
    "references[].target": {
        "destination_kind": "bound_object_handle",
        "destination": "bound_object_handle",
    },
}

_ACTION_MIGRATION: Mapping[str, Mapping[str, Any]] = {
    "set_import_operation": {
        "destination_kind": "stable_business_field",
        "destination": "batch.mode",
    },
    "set_import_option": {
        "destination_kind": "stable_business_field",
        "destination": "batch.settings",
    },
    "clear_import_option": {
        "destination_kind": "stable_business_field",
        "destination": "batch.settings.omit",
    },
    "set_import_default": {
        "destination_kind": "stable_business_field",
        "destination": "batch.explicit_defaults",
    },
    "clear_import_default": {
        "destination_kind": "stable_business_field",
        "destination": "batch.explicit_defaults.omit",
    },
    "add_import_row": {
        "destination_kind": "stable_business_field",
        "destination": "declaration.add",
    },
    "set_import_row_field": {
        "destination_kind": "stable_business_field",
        "destination": "declaration.revise",
    },
    "clear_import_row_field": {
        "destination_kind": "stable_business_field",
        "destination": "declaration.revise_with_omission",
    },
    "remove_import_row": {
        "destination_kind": "stable_business_field",
        "destination": "declaration.remove",
    },
}

_SAFETY_RULES = (
    "one immutable Preview per current business revision",
    "at most one dispatch and no automatic retry",
    "every existing object and dynamic field is revalidated before Preview",
    "regular files and inline WAV data retain immutable bounded evidence",
    "create, re-import, and explicit replacement never mix ambiguously",
    "localized existing targets retain their proven field boundary",
    "every derived target and requested business state is verified after dispatch",
    "native paths, wire types, metadata scopes, order, batches, and shell quoting are Gateway-owned",
)


def build_audio_import_migration_inventory() -> dict[str, Any]:
    """Generate the exact five-version old-to-deep cutover inventory."""

    lanes = [_build_lane(version) for version in SUPPORTED_WWISE_VERSIONS]
    payload: dict[str, Any] = {
        "contract": AUDIO_IMPORT_MIGRATION_INVENTORY_CONTRACT,
        "operation": "audio.import",
        "versions": list(SUPPORTED_WWISE_VERSIONS),
        "destination_kinds": sorted(MIGRATION_DESTINATION_KINDS),
        "lanes": lanes,
        "cutover_policy": {
            "status": "deep_business_interface_public",
            "public_input_mode": "business_declaration",
            "old_interface": "retired_from_gateway_and_agent_contracts",
            "legacy_internal_role": "sealed_archive_compatibility_only",
            "fallback": False,
            "historical_evidence": "frozen_commits_only",
        },
    }
    payload["inventory_digest"] = canonical_sha256(payload)
    return strict_json_copy(payload)


def _build_lane(version: str) -> dict[str, Any]:
    fragments = audio_import_composer_fragment_contract(version)
    composer = operation_composer_contract("audio.import", version)
    option_names = set(fragments["request_options"])
    row_names = set(fragments["row_fields"])
    action_names = set(composer["actions"])
    _require_exact_coverage(
        "request option", option_names, set(_REQUEST_OPTION_MIGRATION)
    )
    _require_exact_coverage("row field", row_names, set(_ROW_FIELD_MIGRATION))
    _require_exact_coverage("action", action_names, set(_ACTION_MIGRATION))
    return {
        "version": version,
        "request_options": [
            _source_row(
                name,
                _REQUEST_OPTION_MIGRATION[name],
                source_contract=fragments["request_options"][name],
                available=_available_in_version(
                    fragments["request_options"][name], version
                ),
            )
            for name in sorted(option_names)
        ],
        "row_fields": [
            _source_row(
                name,
                _ROW_FIELD_MIGRATION[name],
                source_contract=fragments["row_fields"][name],
                available=True,
            )
            for name in sorted(row_names)
        ],
        "nested_fields": [
            _source_row(name, row, source_contract=None, available=True)
            for name, row in sorted(_NESTED_FIELD_MIGRATION.items())
        ],
        "actions": [
            _source_row(
                name,
                _ACTION_MIGRATION[name],
                source_contract=composer["action_shapes"].get(name),
                available=True,
            )
            for name in sorted(action_names)
        ],
        "safety_rules": list(_SAFETY_RULES),
        "limits": {
            "source": "registry_contract",
            **strict_json_copy(fragments["limits"]),
        },
        "source_schema_digest": fragments["source_schema_digest"],
        "source_composer_digest": canonical_sha256(composer),
    }


def _source_row(
    source: str,
    migration: Mapping[str, Any],
    *,
    source_contract: Mapping[str, Any] | None,
    available: bool,
) -> dict[str, Any]:
    destination_kind = migration.get("destination_kind")
    if destination_kind not in MIGRATION_DESTINATION_KINDS:
        raise RuntimeError(f"{source} has an invalid migration destination")
    return {
        "source": source,
        **strict_json_copy(dict(migration)),
        "available": available,
        "cutover": "remove_old_model_input",
        "source_contract_digest": (
            None if source_contract is None else canonical_sha256(source_contract)
        ),
    }


def _available_in_version(contract: Mapping[str, Any], version: str) -> bool:
    supported = contract.get("supported_versions")
    return not isinstance(supported, list) or version in supported


def _require_exact_coverage(
    label: str,
    actual: set[str],
    classified: set[str],
) -> None:
    if actual != classified:
        raise RuntimeError(
            f"audio.import {label} migration coverage changed: "
            f"missing={sorted(actual - classified)!r}, stale={sorted(classified - actual)!r}"
        )


__all__ = [
    "AUDIO_IMPORT_MIGRATION_INVENTORY_CONTRACT",
    "AUDIO_IMPORT_MIGRATION_RESOURCE",
    "MIGRATION_DESTINATION_KINDS",
    "build_audio_import_migration_inventory",
]
