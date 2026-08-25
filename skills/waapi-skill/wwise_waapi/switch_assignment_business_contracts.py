"""Closed business contracts for Switch Container assignment outcomes."""

from __future__ import annotations

from typing import Any

from .business_declarations import SUPPORTED_WWISE_VERSIONS


SWITCH_ASSIGNMENT_BUSINESS_CONTRACT = (
    "waapi-skill.switch-assignment-business/v1"
)
SWITCH_ASSIGNMENT_BUSINESS_OPERATIONS = (
    "switchContainer.addAssignment",
    "switchContainer.removeAssignment",
)


def switch_assignment_business_contract_data(
    operation: str,
    version: str,
) -> dict[str, Any]:
    """Return the three-role assignment contract for one exact lane."""

    if operation not in SWITCH_ASSIGNMENT_BUSINESS_OPERATIONS:
        raise ValueError("unsupported Switch Container assignment operation")
    if version not in SUPPORTED_WWISE_VERSIONS:
        raise ValueError("unsupported Wwise version for Switch assignment")
    outcome = (
        "add"
        if operation == "switchContainer.addAssignment"
        else "remove"
    )
    return {
        "contract": SWITCH_ASSIGNMENT_BUSINESS_CONTRACT,
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
            "roles": [
                "switch_container",
                "child",
                "state_or_switch",
            ],
            "identity": "live_bound_object_handle",
            "validation": "exact_guid_name_type_path",
        },
        "declaration": {
            "subcommand": "draft-declare-switch-assignment",
            "required_fields": [
                "switch_container_handle",
                "child_handle",
                "state_or_switch_handle",
            ],
            "outcome": outcome,
        },
        "gateway_derivations": [
            "exact_guid_relationship",
            "relationship_preconditions",
            "native_request",
            "preview_change_intent",
            "verification_readback",
            "continuation",
        ],
        "legacy_inline_typed_public": False,
        "safety": {
            "immutable_preview": True,
            "single_execute": True,
            "object_revalidation": "exact_guid_name_type_path",
            "relationship_readback": "exact_assignment_pair",
        },
    }


__all__ = [
    "SWITCH_ASSIGNMENT_BUSINESS_CONTRACT",
    "SWITCH_ASSIGNMENT_BUSINESS_OPERATIONS",
    "switch_assignment_business_contract_data",
]
