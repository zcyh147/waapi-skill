"""Closed business contracts for named object graphs and curve operations."""

from __future__ import annotations

from typing import Any

from .business_declarations import SUPPORTED_BUSINESS_KINDS, SUPPORTED_WWISE_VERSIONS


OBJECT_GRAPH_BUSINESS_CONTRACT = "waapi-skill.object-graph-business/v1"
OBJECT_GRAPH_BUSINESS_OPERATIONS = (
    "object.create",
    "object.createPlugin",
    "object.set",
    "object.setRTPC",
)

OBJECT_CREATE_BUSINESS_VALUE_TYPES = {
    "loop": "string",
    "max_instances": "integer",
    "notes": "string",
    "output_bus": "reference",
    "override_parent_instance_limit": "boolean",
    "volume_db": "number",
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
                "properties": "class_scoped_field_handles",
            },
            "type_discovery": {
                "subcommand": "draft-discover-types",
                "roles": ["source", "effect"],
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
                    "field_values",
                    "language",
                    "notes",
                    "platform",
                ],
                "field_value_types": {
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
                "metadata_property_tokens",
                "native_request",
                "preview_change_intent",
                "continuation",
            ],
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
            "declaration": {
                "subcommands": ["draft-declare-existing", "draft-declare-new"],
                "existing_required_fields": ["object_handle"],
                "new_required_fields": ["parent_handle", "name", "kind"],
                "optional_fields": [
                    "field_values",
                    "language",
                    "list_behavior",
                    "loop",
                    "max_instances",
                    "media_files",
                    "new_name",
                    "notes",
                    "object_list",
                    "output_bus",
                    "override_parent_instance_limit",
                    "platform",
                    "volume_db",
                ],
                "field_value_types": {
                    **OBJECT_CREATE_BUSINESS_VALUE_TYPES,
                    "language": "string",
                    "list_behavior": "string",
                    "new_name": "string",
                    "object_list": "string",
                    "platform": "string",
                },
            },
            "object_list_declaration": {
                "member_fields": {
                    "object_list": "exact_user_owned_wwise_object_list_name",
                    "list_behavior": ["append", "replace-all"],
                },
                "clear_subcommand": "draft-clear-object-list",
                "clear_fields": [
                    "declaration_id",
                    "object_handle",
                    "list_name",
                ],
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
                "name_conflict": ["fail", "rename", "merge"],
                "list_behavior": ["append", "replace-all"],
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
            "stable_fields": dict(OBJECT_CREATE_BUSINESS_VALUE_TYPES),
            "field_value_types": dict(OBJECT_CREATE_BUSINESS_VALUE_TYPES),
            "bound_field_handle_container": "field_values",
            "semantic_kinds": list(SUPPORTED_BUSINESS_KINDS),
            "planned_parent": "copy_previous_declaration_result_handle",
        },
        "settings": {
            "name_conflict": ["fail", "rename", "merge", "replace"],
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
