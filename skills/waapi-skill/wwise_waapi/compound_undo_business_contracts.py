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
        operation_uses_business_declaration,
    )
    from .typed_operations import compound_child_operations

    all_children = sorted(compound_child_operations(version))
    eligible = [
        operation
        for operation in all_children
        if not operation.startswith("ak.")
        and operation_uses_business_declaration(operation, version)
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
            "child_input": "ordered_checked_closed_draft_snapshot",
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
            "generic_typed_child_operations": [
                operation for operation in all_children if operation.startswith("ak.")
            ],
            "generic_child_boundary": (
                "generic child parameters remain owned by their separate #57 "
                "migration family; this Adapter accepts only their checked "
                "closed Draft snapshot"
            ),
            "native_request_input": "forbidden",
            "child_call_handle_input": "forbidden",
            "action_ordering_grammar": "forbidden",
        },
        "responsibility_split": {
            "agent": (
                "choose_the_display_name_and_user_requested_business_sequence_"
                "of_already_checked_closed_child_drafts"
            ),
            "gateway": (
                "snapshot_child_requests_derive_schema_bindings_fixed_native_"
                "phase_dependency_order_revisions_and_one_preview"
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
            "immutable_preview": True,
            "single_execute": True,
        },
    }


__all__ = [
    "COMPOUND_UNDO_BUSINESS_CONTRACT",
    "compound_undo_business_contract_data",
]
