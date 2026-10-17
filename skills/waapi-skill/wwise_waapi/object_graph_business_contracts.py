"""Closed business contracts for named object graphs and curve operations."""

from __future__ import annotations

from typing import Any

from .business_declarations import SUPPORTED_BUSINESS_KINDS, SUPPORTED_WWISE_VERSIONS
from .business_fields import ACTION_DURATION_FIELDS, ACTION_DURATION_SEMANTICS, OBJECT_BUSINESS_FIELD_TYPES
from .metadata_condition_contracts import existing_field_condition_contract


OBJECT_GRAPH_BUSINESS_CONTRACT = "waapi-skill.object-graph-business/v1"
OBJECT_GRAPH_BUSINESS_OPERATIONS = (
    "object.create",
    "object.createPlugin",
    "object.set",
    "object.setRTPC",
)

OBJECT_CREATE_BUSINESS_VALUE_TYPES = {
    name: value_type
    for name, value_type in OBJECT_BUSINESS_FIELD_TYPES.items()
    if name not in ACTION_DURATION_FIELDS
}

ACTION_CREATION_BOUNDARY = {
    "status": "unsupported_by_skill_interface",
    "reason": "event_parent_and_derived_action_identity_require_a_dedicated_creation_contract",
    "existing_object_edits": "supported_through_object_set_or_metadata_operations",
}

_SUPPORTED_VERSIONS = {
    "object.create": SUPPORTED_WWISE_VERSIONS,
    "object.createPlugin": ("2022.1", "2023.1", "2024.1", "2025.1"),
    "object.set": ("2022.1", "2023.1", "2024.1", "2025.1"),
    "object.setRTPC": ("2022.1", "2023.1", "2024.1", "2025.1"),
}


def object_graph_business_contract_data(
    operation: str,
    version: str,
) -> dict[str, Any]:
    """Return the operation-local business interface for one exact lane."""

    if operation not in OBJECT_GRAPH_BUSINESS_OPERATIONS:
        raise ValueError("unsupported object graph business operation")
    if version not in _SUPPORTED_VERSIONS[operation]:
        raise ValueError("unsupported Wwise version for object graph operation")
    if operation == "object.createPlugin":
        return {
            "contract": OBJECT_GRAPH_BUSINESS_CONTRACT,
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
                "target": "bound_object_handle",
                "plugin_type": "live_discovered_type_handle",
                "properties_and_references": "class_scoped_field_handles",
                "placement_targets": {
                    "owner": "compatible audio object; never a Work Unit",
                    "shareset": "WorkUnit under Effects, Audio Devices, or Metadata for the exact Effect, Sink, or Metadata class",
                },
            },
            "type_discovery": {
                "subcommand": "draft-discover-types",
                "roles": ["source", "effect", "sink", "metadata"],
                "result": "copy_one_gateway_returned_type_handle",
            },
            "declaration": {
                "subcommand": "draft-declare-existing",
                "required_fields": [
                    "object_handle",
                    "plugin_role",
                    "plugin_name",
                    "plugin_type_handle",
                ],
                "optional_fields": [
                    "plugin_placement",
                    "field_values",
                    "language",
                    "notes",
                    "platform",
                ],
                "placement": {
                    "owner": "attach a local Source or Effect to a compatible audio object",
                    "shareset": "create an independent Effect, AudioDevice, or Metadata child in its matching hierarchy",
                    "default": "owner",
                },
                "field_value_types": {
                    "plugin_placement": "string",
                    "language": "string",
                    "notes": "string",
                    "platform": "string",
                    "plugin_name": "string",
                    "plugin_role": "string",
                    "plugin_type_handle": "string",
                },
            },
            "gateway_derivations": [
                "plugin_class_id",
                "versioned_plugin_topology",
                "metadata_property_and_reference_tokens",
                "native_request",
                "preview_change_intent",
                "continuation",
            ],
            "plugin_kind_routes": {
                "SourcePlugin": {"role": "source", "placement": ["owner"], "native_type": "Source"},
                "EffectPlugin": {"role": "effect", "placement": ["owner", "shareset"], "native_type": "Effect"},
                "SinkPlugin": {"role": "sink", "placement": ["shareset"], "native_type": "AudioDevice", "hierarchy": "Audio Devices"},
                "MetadataPlugin": {"role": "metadata", "placement": ["shareset"], "native_type": "Metadata", "hierarchy": "Metadata",
                    "owner_local_placement": {"status": "missing_implementation", "tracking_issue": 179}},
                "ConversionPlugin": {"discovery_role": "conversion", "native_type": "Conversion",
                    "attachment": {"request_schema_command": ["request-schema", "ak.wwise.core.audio.setConversionPlugin"],
                        "supported_versions": ["2024.1", "2025.1"]},
                    "older_version_alternatives": {"status": "unresolved_native_mapping", "tracking_issue": 179}},
            },
            "version_boundaries": {"2021.1": {"creation": "missing_implementation", "tracking_issue": 179,
                "reason": "The older create schema lacks classId and object.set is absent; alternative native construction still requires matching evidence."}},
            "legacy_shallow_composer_public": False,
            "safety": {
                "immutable_preview": True,
                "single_execute": True,
                "type_revalidation": "exact_live_catalog_row",
                "field_revalidation": "exact_class_metadata",
            },
        }
    if operation == "object.setRTPC":
        return {
            "contract": OBJECT_GRAPH_BUSINESS_CONTRACT,
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
                "object": "bound_object_handle",
                "control_input": "bound_object_handle",
                "property": "live_discovered_field_handle",
            },
            "field_discovery": {
                "subcommand": "draft-discover-fields",
                "input": "user_facing_property_meaning",
                "result": "copy_one_gateway_returned_property_handle",
                "native_property_token": "forbidden",
            },
            "declaration": {
                "subcommand": "draft-declare-rtpc",
                "required_fields": [
                    "object_handle",
                    "field_handle",
                    "control_input_handle",
                    "curve_points",
                ],
                "optional_fields": ["mode", "notes"],
                "mode_values": ["add-only", "add-or-update"],
                "point_fields": ["x", "y", "shape"],
                "shape_semantics": "outgoing_segment",
                "terminal_shape": "gateway_normalized_to_Linear",
                "point_shapes": [
                    "Constant",
                    "Linear",
                    "Log3",
                    "Log2",
                    "Log1",
                    "InvertedSCurve",
                    "SCurve",
                    "Exp1",
                    "Exp2",
                    "Exp3",
                ],
                "point_limit": 256,
            },
            "gateway_derivations": [
                "native_property_token",
                "control_input_identity",
                "rtpc_list_row",
                "add_or_replace_mode",
                "native_request",
                "preview_change_intent",
                "continuation",
            ],
            "legacy_shallow_composer_public": False,
            "safety": {
                "immutable_preview": True,
                "single_execute": True,
                "object_revalidation": "exact_guid_name_type_path",
                "field_revalidation": "exact_object_metadata",
            },
        }
    if operation == "object.set":
        return {
            "activation_prerequisites": existing_field_condition_contract(version),
            "contract": OBJECT_GRAPH_BUSINESS_CONTRACT,
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
                "existing_targets": "bound_object_handles",
                "new_descendants": "bound_or_planned_parent_handles",
                "fields": "live_discovered_field_handles",
                "long_tail_types": "live_discovered_type_handles",
            },
            "field_discovery": {
                "subcommand": "draft-discover-fields",
                "input": "one_to_eight_distinct_user_facing_meanings",
                "scope": "one_bound_target_or_declared_semantic_kind",
                "result": (
                    "one_ordered_meaning_result_with_bounded_candidates_per_input"
                ),
                "native_property_or_reference_token": "forbidden",
            },
            "declaration": {
                "subcommands": [
                    "draft-declare-existing",
                    "draft-declare-existing-batch",
                    "draft-declare-new",
                ],
                "existing_batch": {
                    "maximum_rows": 8,
                    "field_input": "fixed_business_fields_or_selected_scoped_field_handles",
                    "business_quantities": {
                        "action_time": {
                            "accepted_units": ["seconds", "milliseconds"],
                            "canonical_unit": "seconds",
                        }
                    },
                    "metadata_revalidation": "each_exact_bound_object",
                    "atomic_revision": True,
                },
                "existing_required_fields": ["object_handle"],
                "new_required_fields": ["parent_handle", "name", "kind"],
                "optional_fields": [
                    "field_values",
                    "language",
                    "list_behavior",
                    "loop",
                    "max_instances",
                    "media_files",
                    "name_conflict",
                    "new_name",
                    "notes",
                    "object_list",
                    "output_bus",
                    "ignore_parent_instance_limit",
                    "platform",
                    "volume_db",
                    "fade_time_ms",
                    "delay_ms",
                ],
                "field_value_types": {
                    **OBJECT_BUSINESS_FIELD_TYPES,
                    "language": "string",
                    "list_behavior": "string",
                    "name_conflict": "string",
                    "new_name": "string",
                    "object_list": "string",
                    "platform": "string",
                },
                "field_semantics": ACTION_DURATION_SEMANTICS,
                "existing_target_choices": {
                    "name_conflict": ["fail", "rename", "merge", "replace"],
                    "scope": "new_children_and_list_members_of_this_existing_target",
                    "overrides": "batch_name_conflict",
                },
            },
            "object_list_declaration": {
                "member_fields": {
                    "object_list": "exact_user_owned_wwise_object_list_name",
                    "list_behavior": ["append", "replace-all"],
                },
                "recursive_placement": "bound_or_planned_parent_handles;_ordinary_children_and_owned_lists_may_nest",
                "list_behavior_scope": "one_inherited_existing_target_row;_conflicting_descendant_choices_are_rejected",
                "clear_subcommand": "draft-clear-object-list",
                "clear_fields": [
                    "declaration_id",
                    "object_handle",
                    "list_name",
                ],
                "clear_owner": "bound_object_handle_or_matching_planned_declaration_result_handle",
                "native_at_prefix": "forbidden",
                "empty_clear_requires": "replace-all",
            },
            "media_declaration": {
                "subcommand": "draft-add-media",
                "source_forms": ["media-file", "inline-wav"],
                "optional_fields": [
                    "kind",
                    "language",
                    "originals_subfolder",
                ],
                "exact_user_artifacts": ["media_file", "inline_wav"],
                "native_import_fragment_input": "forbidden",
                "supported_versions": ["2023.1", "2024.1", "2025.1"],
            },
            "settings": {
                "name_conflict": ["fail", "rename", "merge", "replace"],
                "list_behavior": ["append", "replace-all"],
                "platform": "exact_user_requested_platform;_per_target_platform_overrides",
                "add_to_source_control": "boolean",
            },
            "gateway_derivations": [
                "target_rows",
                "recursive_children",
                "native_object_types",
                "metadata_tokens",
                "platform_views",
                "dependency_order",
                "batch_layout",
                "object_list_rows",
                "per_target_list_mode",
                "native_request",
                "preview_change_intent",
                "continuation",
            ],
            "legacy_shallow_composer_public": False,
            "creation_boundaries": {"Action": dict(ACTION_CREATION_BOUNDARY)},
            "safety": {
                "immutable_preview": True,
                "single_execute": True,
                "object_revalidation": "exact_guid_name_type_path",
                "field_revalidation": "exact_scope_metadata_platform",
            },
        }
    if operation != "object.create":
        raise ValueError("object graph business operation is not migrated yet")
    return {
        "contract": OBJECT_GRAPH_BUSINESS_CONTRACT,
        "operation": operation,
        "version": version,
        "input_mode": "business_declaration",
        "start": {
            "subcommand": "draft-start",
            "gateway_argv": ["draft-start", operation],
            "copy_exactly": True,
            "append_arguments": "forbidden",
        },
        "declaration": {
            "subcommand": "draft-declare-new",
            "target_fields": ["parent_handle", "name", "kind"],
            "stable_fields": {**OBJECT_CREATE_BUSINESS_VALUE_TYPES, "object_list": "string"},
            "field_semantics": {},
            "field_value_types": {**OBJECT_CREATE_BUSINESS_VALUE_TYPES, "object_list": "string"},
            "object_list": {
                "scope": "new_root_only",
                "input": "exact_user_owned_wwise_object_list_name_without_at_prefix",
                "placement": "owned_list_instead_of_hierarchy_child",
                "descendants": "ordinary_recursive_children",
            },
            "bound_field_handle_container": "field_values",
            "semantic_kinds": list(SUPPORTED_BUSINESS_KINDS),
            "planned_parent": "copy_previous_declaration_result_handle",
        },
        "settings": {
            "name_conflict": ["fail", "rename", "merge", "replace"],
            "merge_existing_same_name_root": (
                "bind_exact_existing_root_direct_parent_then_declare_root_name_"
                "once_with_merge"
            ),
            "replace_owner_handle": "required_only_for_explicit_replace",
            "platform": "exact_user_requested_platform",
            "add_to_source_control": "boolean",
        },
        "type_discovery": {
            "subcommand": "draft-discover-types",
            "input": "user_facing_meaning",
            "roles": ["object"],
            "result": "copy_one_gateway_returned_type_handle",
            "native_type_or_class_id_input": "forbidden_unless_exact_user_artifact",
        },
        "gateway_derivations": [
            "native_object_type",
            "recursive_object_tree",
            "canonical_parent_identity",
            "property_tokens",
            "dependency_order",
            "native_request",
            "preview_change_intent",
            "continuation",
        ],
        "legacy_shallow_composer_public": False,
        "creation_boundaries": {"Action": dict(ACTION_CREATION_BOUNDARY)},
        "safety": {
            "immutable_preview": True,
            "single_execute": True,
            "object_revalidation": "exact_guid_name_type_path",
        },
    }


__all__ = [
    "OBJECT_GRAPH_BUSINESS_CONTRACT",
    "OBJECT_GRAPH_BUSINESS_OPERATIONS",
    "OBJECT_CREATE_BUSINESS_VALUE_TYPES",
    "object_graph_business_contract_data",
]
