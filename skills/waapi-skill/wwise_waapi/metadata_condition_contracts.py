"""Public condition guidance shared by existing-object business operations."""

from __future__ import annotations

from typing import Any


def existing_field_condition_contract(version: str) -> dict[str, Any]:
    """Describe the implemented planner without exposing native request inputs."""
    return {
        "contract": "waapi-skill.existing-field-conditions/v1",
        "owner": "gateway",
        "scope": "selected_existing_object_property_edits_and_reference_assignments",
        "metadata_source": "fresh_exact_object_and_field_metadata",
        "conditions": {
            "property": {
                "action": "Enable", "context": "Self", "restrictions": ["enum", "range"],
                "satisfied_value": "preserve_exact_native_value",
                "multiple_choices": "require_explicit_user_value_when_current_value_does_not_satisfy",
                "accumulated_conditions": "intersect_before_selecting_a_value",
            },
            "override": {
                "action": "Enable", "context": "Self", "property_type": ["bool", "boolean"],
                "required_value": True, "exact_self_marker": "terminal_switch",
            },
            "reference": {
                "action": "Enable", "context": "Self", "condition": "referenceIsSet_boolean",
                "target": "explicit_user_selected_bound_object_or_separate_clear_preview",
                "satisfied_identity": "preserve_and_revalidate_canonical_GUID_or_native_null",
            },
            "visibility": {
                "action": "Show", "contexts": ["Self", "Parent", "AssocParent"],
                "conditions": "validated_property_or_reference_presence_condition",
                "prerequisite_write": False,
            },
            "association_owner": {
                "action": "Enable", "context": "AssocParent", "source_type": "ObjectSettingAssociation",
                "relationship": "live_canonical_owner_GUID", "owner_type": "SwitchContainer",
                "controller": "exact_live_property_with_satisfied_recursive_Self_closure",
                "recursive_prerequisites": ["property", "override", "reference"],
                "owner_values": "preserve_revalidate_and_verify_without_derived_owner_writes",
                "missing_identity_or_relationship": "stop_without_inference",
            },
        },
        "when_unsatisfied": {
            "single_field_operation": "separately_preview_each_disclosed_prerequisite_using_its_live_Field_Handle",
            "atomic_object_set": "derive_only_unique_same_object_scalar_values_or_use_explicit_selected_field_values",
            "after_repair": "create_a_fresh_Preview_after_verified_prerequisites",
        },
        "atomic_batch_alternative": "object.set" if version != "2021.1" else None,
        "safety": {
            "related_object_writes": "separately_preview_and_authorize",
            "hidden_followup_writes": False,
            "revalidate": ["identities", "relationships", "metadata", "prerequisite_values"],
            "verify_prerequisites_after_execution": True,
            "unknown_conditions_cycles_or_conflicts": "reject_before_dispatch",
            "maximum_depth": 8, "maximum_fields": 16, "maximum_related_conditions": 16,
        },
    }
