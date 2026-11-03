"""Closed business contracts for one existing-object metadata field edit."""

from __future__ import annotations

from typing import Any

from .business_declarations import SUPPORTED_WWISE_VERSIONS
from .metadata_condition_contracts import existing_field_condition_contract


OBJECT_METADATA_BUSINESS_CONTRACT = "waapi-skill.object-metadata-business/v1"
OBJECT_METADATA_BUSINESS_OPERATIONS = (
    "object.setProperty",
    "object.setReference",
    "object.setLinked",
)

_SUPPORTED_VERSIONS = {
    "object.setProperty": SUPPORTED_WWISE_VERSIONS,
    "object.setReference": SUPPORTED_WWISE_VERSIONS,
    "object.setLinked": ("2023.1", "2024.1", "2025.1"),
}

_DECLARATIONS: dict[str, dict[str, Any]] = {
    "object.setProperty": {
        "required_fields": ["object_handle", "field_handle", "business_value"],
        "field_types": {
            "object_handle": "bound_object_handle_or_switch_child_context_handle",
            "field_handle": "bound_property_handle",
            "business_value": "live_metadata_typed_scalar",
        },
    },
    "object.setReference": {
        "required_fields": ["object_handle", "field_handle", "reference_outcome"],
        "field_types": {
            "object_handle": "bound_object_handle",
            "field_handle": "bound_reference_handle",
            "reference_outcome": "bound_object_handle_or_clear",
        },
    },
    "object.setLinked": {
        "required_fields": ["object_handle", "field_handle", "link_state"],
        "field_types": {
            "object_handle": "bound_object_handle",
            "field_handle": "bound_unlinkable_field_handle",
            "link_state": "linked_or_unlinked",
        },
    },
}


def object_metadata_business_contract_data(
    operation: str,
    version: str,
) -> dict[str, Any]:
    """Return the small public shape for one property/reference/link edit."""

    if operation not in _DECLARATIONS:
        raise ValueError("unsupported object metadata business operation")
    if version not in _SUPPORTED_VERSIONS[operation]:
        raise ValueError("unsupported Wwise version for object metadata operation")
    declaration = _DECLARATIONS[operation]
    return {
        "contract": OBJECT_METADATA_BUSINESS_CONTRACT,
        "operation": operation,
        **({"new_owned_ControlInput_requires_object.set_Business_Draft": {
            "start": ["draft-start", "object.set"], "declaration": "draft-declare-field-change",
            "scope": "new_custom_LFO_Envelope_Time_owned_by_existing_RTPC; scalar_native_setReference_contract_unchanged",
            "versions": ["2022.1", "2023.1", "2024.1", "2025.1"], "tracking_issue": 180}}
           if operation == "object.setReference" else {}),
        "version": version,
        "input_mode": "business_declaration",
        "start": {
            "subcommand": "draft-start",
            "gateway_argv": ["draft-start", operation],
            "copy_exactly": True,
            "append_arguments": "forbidden",
        },
        "object_binding": {
            "subcommand": "draft-bind-object",
            "roles": (
                ["object", "reference_target"]
                if operation == "object.setReference"
                else ["object"]
            ),
            "result": "copy_the_returned_bound_object_handle",
        },
        **({"structural_property_target": {
            "subcommand": "draft-bind-switch-child-context",
            "required_fields": ["owner_handle", "child_handle"],
            "scope": "exact SwitchContainer owner and its directly bound child; Gateway derives the child context GUID",
            "result": "copy bound_context.handle as object_handle for metadata-authorized scalar property discovery",
            "native_identity": "preserved without inventing an absent native type",
            "history_recovery": {"status": "owned_receipt_observation_only", "tracking_issue": 192,
                "undo_versions": ["2022.1", "2023.1", "2024.1", "2025.1"],
                "redo_versions": ["2023.1", "2024.1", "2025.1"],
                "requires": ["verified_property_receipt", "unchanged_structural_and_condition_proofs",
                    "certified_platform_or_nonlinkable_no_platform_value_view"],
                "stack_head_observed": False, "automatic_retry": False},
        }} if operation == "object.setProperty" else {}),
        "field_discovery": {
            "subcommand": "draft-discover-fields",
            "input": "user_facing_meaning",
            "scope": "bound_target_object",
            "platform": (
                "required_and_sealed_into_handle"
                if operation == "object.setLinked"
                else "optional_and_sealed_into_handle"
            ),
            "result": "copy_one_gateway_returned_field_handle",
            "ambiguous_result": "choose_one_bounded_candidate_handle_or_refine_meaning",
        },
        **({"activation_prerequisites": existing_field_condition_contract(version)}
           if operation in {"object.setProperty", "object.setReference"} else {}),
        "declaration": {
            "subcommand": "draft-declare-field-change",
            "required_fields": list(declaration["required_fields"]),
            "optional_fields": [],
            "field_types": dict(declaration["field_types"]),
        },
        "gateway_derivations": [
            "closed_object_identity",
            "exact_live_field_binding",
            "typed_business_value",
            "native_request",
            "preview_change_intent",
            "continuation",
        ],
        "legacy_inline_typed_public": False,
        "safety": {
            "immutable_preview": True,
            "single_execute": True,
            "object_revalidation": ("ordinary_exact_guid_name_type_path_or_structural_owner_child_context_proof"
                if operation == "object.setProperty" else "exact_guid_name_type_path"),
            "field_revalidation": "exact_scope_token_metadata_platform",
        },
    }


__all__ = [
    "OBJECT_METADATA_BUSINESS_CONTRACT",
    "OBJECT_METADATA_BUSINESS_OPERATIONS",
    "object_metadata_business_contract_data",
]
