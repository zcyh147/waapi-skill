"""Closed business contract for one ordered compound Undo plan."""

from __future__ import annotations

from typing import Any

from .business_declarations import SUPPORTED_WWISE_VERSIONS


COMPOUND_UNDO_BUSINESS_CONTRACT = "waapi-skill.compound-undo-business/v1"


def compound_undo_business_contract_data(version: str) -> dict[str, Any]:
    if version not in SUPPORTED_WWISE_VERSIONS:
        raise ValueError("unsupported Wwise version")
    from .operation_registry import (
        UNDO_GROUP_MAX_CALLS,
        UNDO_GROUP_MAX_DISPLAY_NAME_LENGTH,
    )
    from .typed_operations import (
        compound_business_child_operations,
        compound_child_operations,
    )

    all_children = sorted(compound_child_operations(version))
    eligible = sorted(compound_business_child_operations(version))
    prohibited_generic = [
        operation for operation in all_children if operation.startswith("ak.")
    ]
    return {
        "contract": COMPOUND_UNDO_BUSINESS_CONTRACT,
        "operation": "waapi.undoGroup",
        "version": version,
        "input_mode": "business_declaration",
        "start": {
            "subcommand": "draft-start",
            "gateway_argv": ["draft-start", "waapi.undoGroup"],
            "copy_exactly": True,
            "append_arguments": "forbidden",
        },
        "binding": {"available": False, "roles": [], "role_required": False},
        "declaration": {
            "subcommand": "draft-declare-undo-plan",
            "settings_field": "undo_plan",
            "submit_once": True,
            "required_fields": ["display_name", "child_drafts"],
            "optional_fields": ["failure_cancellation"],
            "failure_cancellation": {
                "cli": "--failure-cancellation <choice>",
                "choices": (["native-default"] if version in {"2021.1", "2022.1"}
                            else ["undo-changes", "preserve-changes", "native-default"]),
                "default": "native-default" if version in {"2021.1", "2022.1"} else "undo-changes",
                "native-default": "omit cancelGroup.undo; older-version rollback meaning is not inferred",
                "preserve-changes": "explicit cancelGroup.undo=false; 2023.1-2025.1 only",
                "undo-changes": "explicit cancelGroup.undo=true; restoration requires separate bounded readback",
            },
            "child_input": (
                "ordered_parent_owned_checked_closed_draft_snapshot"
            ),
            "child_start": {
                "subcommand": "draft-start-undo-child",
                "caller_input": "one eligible child operation name",
                "parent_binding": "gateway_owned_copy_ready_prefix",
                "checked_handoff": "returns_to_parent",
                "preview": "forbidden",
            },
            "child_count": {"minimum": 1, "maximum": UNDO_GROUP_MAX_CALLS},
            "display_name": {
                "minimum_characters": 1,
                "maximum_characters": UNDO_GROUP_MAX_DISPLAY_NAME_LENGTH,
            },
            "business_sequence": {
                "caller_owned": True,
                "meaning": "user_requested_relative_child_outcome_sequence",
                "native_dependency_edges_input": "forbidden",
            },
            "eligible_child_operations": eligible,
            "child_observation_scope": {
                "object.create": "complete_ordinary_new_fail_mode_hierarchy_with_actual_node_identity_class_parent_notes_fields_and_membership",
                **({"object.set": "existing_only_scalar_existing_reference_or_null_name_and_notes_fields"}
                    if version != "2021.1" else {}),
                "render_effects": "explicit_and_induced_existing_fields_plus_complete_original_chain",
                "graph_list_merge_replace_restoration": "remaining_same_parent_implementation_obligation",
                "created_graph_ancestor_rename": "exact_intent_GUID_bound_ancestor_components_and_phase_reference_arguments;_new_object_collision_names_and_phase_reference_dependencies_remain_same_parent",
                "history_receipt": "actual_parent_execution_phase_and_child_verification_range_hash_association",
            },
            "prohibited_generic_child_operations": prohibited_generic,
            "generic_child_boundary": (
                "prohibited_until_the_separate_#57_business_migration_supplies_"
                "closed_parameters_and_business_outcome_verification"
            ),
            "native_request_input": "forbidden",
            "child_call_handle_input": "forbidden",
            "action_ordering_grammar": "forbidden",
        },
        "responsibility_split": {
            "agent": (
                "choose_the_display_name_child_business_operations_and_user_"
                "requested_business_sequence"
            ),
            "gateway": (
                "own_parent_child_handoffs_snapshot_child_requests_derive_"
                "schema_bindings_fixed_native_phase_dependency_order_"
                "revisions_and_one_parent_preview"
            ),
        },
        "gateway_derivations": [
            "immutable_child_request_snapshots",
            "child_schema_digests",
            "child_handles",
            "native_phase_dependency_order",
            "batch_and_revision_mechanics",
            "begin_end_cancel_native_calls",
            "single_immutable_preview",
        ],
        "snapshot_boundary": {
            "source_child_must_be_checked": True,
            "later_child_draft_changes_affect_parent": False,
            "parent_owns_canonical_snapshot": True,
        },
        "legacy_composer_public": False,
        "legacy_child_schema_public": False,
        "legacy_action_grammar_public": False,
        "safety": {
            "same_connection": True,
            "nested_undo_group": "forbidden",
            "automatic_retry": False,
            "inner_failure_attempts_cancel": True,
            "cancel_is_not_rollback_verification": True,
            "cancellation_observation": {
                "scope": "sealed_child_preflight_readbacks_only",
                "maximum_distinct_reads": 128,
                "maximum_report_bytes": 32768,
                "original_read_results": "immutable_preview_and_dispatcher_evidence",
                "missing_affected_prestate": "incomplete; never restoration proof",
                "group_lifetime_and_external_effects": "not_verified_by_this_observation",
            },
            "every_eligible_child_requires_business_state_verification": True,
            "overlapping_final_outcomes": "reject_before_preview",
            "field_platform_scope": {
                "selector_spelling_proves_independence": False,
                "current_platform_observer": ("unimplemented_for_pinned_lane" if version == "2021.1"
                                              else "getProjectInfo.currentPlatformId"),
                "linked_state_observer": ("object.isLinked" if version in {"2023.1", "2024.1", "2025.1"}
                                          else "not_in_pinned_catalog"),
                "independent_property_children": "distinct_exact_platforms_with_live_unlinked_evidence",
                "execution_guard": "recheck_current_platform_name_bindings_and_observed_linkage",
                "reference_omission": "not_inferred_as_property_current_platform",
                "unknown_effective_scope": "guarded_before_preview; remains_implementation_obligation",
            },
            "immutable_preview": True,
            "single_execute": True,
        },
    }


__all__ = [
    "COMPOUND_UNDO_BUSINESS_CONTRACT",
    "compound_undo_business_contract_data",
]
