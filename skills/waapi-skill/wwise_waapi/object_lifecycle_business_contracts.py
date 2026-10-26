"""Closed business contracts for simple existing-object lifecycle changes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .business_declarations import SUPPORTED_WWISE_VERSIONS
from .operation_import import AUTO_CHECK_OUT_TO_SOURCE_CONTROL_VERSIONS


OBJECT_LIFECYCLE_BUSINESS_CONTRACT = (
    "waapi-skill.object-lifecycle-business/v1"
)

_DECLARATIONS: dict[str, dict[str, Any]] = {
    "object.copy": {
        "required_fields": [],
        "optional_fields": [
            "name_conflict",
            "add_to_source_control",
            "check_out_from_source_control",
        ],
        "field_types": {
            "name_conflict": "fail_or_rename_or_replace",
            "add_to_source_control": "boolean",
            "check_out_from_source_control": "boolean",
        },
    },
    "object.delete": {
        "required_fields": [],
        "optional_fields": ["check_out_from_source_control"],
        "field_types": {
            "check_out_from_source_control": "boolean",
        },
    },
    "object.move": {
        "required_fields": [],
        "optional_fields": [
            "name_conflict",
            "check_out_from_source_control",
        ],
        "field_types": {
            "name_conflict": "fail_or_rename_or_replace",
            "check_out_from_source_control": "boolean",
        },
    },
    "object.setName": {
        "required_fields": ["new_name"],
        "optional_fields": [],
        "field_types": {
            "new_name": "string",
        },
    },
    "object.setNotes": {
        "required_fields": ["notes"],
        "optional_fields": [],
        "field_types": {
            "notes": "string",
        },
    },
}


def object_name_native_limitations(version: str) -> list[dict[str, Any]]:
    """Retain the exact observed rejection without classifying other contexts."""
    if version != "2025.1":
        return []
    path = Path(__file__).resolve().parents[1] / "references" / "semantic" / version / "playlist-slot-name-native-boundary.json"
    with path.open("rb") as source:
        raw = source.read(8193)
    if len(raw) > 8192 or hashlib.sha256(raw).hexdigest() != "6393d057eda59214e1e540195f0cdd0c279dc8a23e30fa0f0fa1ed2815c3438d":
        raise ValueError("Pinned PlaylistSlot native name-boundary source changed")
    return [json.loads(raw)]


def object_lifecycle_business_contract_data(
    operation: str,
    version: str,
) -> dict[str, Any]:
    """Return the small public business shape for one exact operation lane."""

    if operation not in _DECLARATIONS:
        raise ValueError("unsupported object lifecycle business operation")
    if version not in SUPPORTED_WWISE_VERSIONS:
        raise ValueError("unsupported Wwise version")
    source = _DECLARATIONS[operation]
    optional_fields = list(source["optional_fields"])
    field_types = dict(source["field_types"])
    source_control_available = version in AUTO_CHECK_OUT_TO_SOURCE_CONTROL_VERSIONS
    if not source_control_available:
        for field in (
            "add_to_source_control",
            "check_out_from_source_control",
        ):
            if field in optional_fields:
                optional_fields.remove(field)
            field_types.pop(field, None)
    add_to_source_control_available = (
        source_control_available and operation == "object.copy"
    )
    return {
        "contract": OBJECT_LIFECYCLE_BUSINESS_CONTRACT,
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
            "roles": ["object", "parent"]
            if operation in {"object.copy", "object.move"}
            else ["object"],
            "role_required": operation in {"object.copy", "object.move"},
            "result": "gateway_stores_the_bound_role;_no_handle_is_a_declaration_input",
        },
        "declaration": {
            "subcommand": "draft-declare-object-change",
            "required_fields": list(source["required_fields"]),
            "optional_fields": optional_fields,
            "field_types": field_types,
        },
        "gateway_derivations": [
            "closed_object_identity",
            "native_request",
            "dependency_order",
            "preview_change_intent",
            "continuation",
        ],
        "legacy_inline_typed_public": False,
        **({"native_name_limitations": object_name_native_limitations(version)}
            if operation == "object.setName" else {}),
        "safety": {
            "immutable_preview": True,
            "single_execute": True,
            "object_revalidation": "exact_guid_name_type_path",
            **({"destination": {
                "admission": "exact_live_parent_and_versioned_parent_child_compatibility_independent_of_WorkUnit_name",
                "protected": "Project_and_management_roots_remain_prohibited",
                "existing_Source": "exact_Sound_parent_plus_unique_live_Source_category_or_pinned_file_Source_class;_class_and_identity_revalidated",
                "boundary": "existing_object_transfer_admission_is_not_plugin_construction_or_complete_plugin_copy_proof",
            }, "replace": {
                "authorization": "explicit_name_conflict_replace_and_exact_destination",
                "preview": "complete_bounded_source_and_replaced_subtree",
                "revalidation": "identities_topology_notes_and_discovered_default_view_fields",
                "verification": "source_copy_or_move_identity_and_topology_values_and_all_replaced_guid_absence",
                "verification_boundary": "indeterminate_until_unlinked_platform_and_owned_list_plugin_state_are_observed",
                "maximum_subtree_nodes": 128,
            }} if operation in {"object.copy", "object.move"} else {}),
        },
        "version_features": {
            "add_to_source_control": add_to_source_control_available,
            "check_out_from_source_control": source_control_available,
        },
    }


__all__ = [
    "OBJECT_LIFECYCLE_BUSINESS_CONTRACT",
    "object_lifecycle_business_contract_data",
    "object_name_native_limitations",
]
