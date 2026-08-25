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
            "stable_fields": {
                "loop": "infinite",
                "notes": "string",
                "volume_db": "number",
            },
            "semantic_kinds": list(SUPPORTED_BUSINESS_KINDS),
            "planned_parent": "copy_previous_declaration_result_handle",
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
    "object_graph_business_contract_data",
]
