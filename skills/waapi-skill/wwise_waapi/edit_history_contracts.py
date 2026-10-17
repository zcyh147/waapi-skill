"""Pinned standalone history choices, separate from empty native results."""
HISTORY_VERSIONS = {
    "ak.wwise.core.undo.undo": ("2022.1", "2023.1", "2024.1", "2025.1"),
    "ak.wwise.core.undo.redo": ("2023.1", "2024.1", "2025.1"),
}


def history_declaration() -> dict:
    return {"history_scope": {"choices": ["latest_project_history"],
        "meaning": "operate_on_the_current_project_latest_native_history_entry"},
        "expectation_receipt": {"required": False, "meaning": "owned_successfully_verified_receipt_for_expected_state_readback_only",
            "native_entry_selection": False, "initial_observers": ["object.setNotes", "object.setName", "object.setProperty_exact_GUID_platform_view", "waapi.undoGroup_of_recoverable_children"],
            "remaining_observers": ["property_receipt_current_or_named_platform_original_view_certification",
                "references_and_other_recoverable_receipt_kinds_remain_edit_history_implementation_work"]},
        "stack_head_observed": False, "outside_scope_preservation_observed": False,
        "automatic_retry": False, "automatic_compensation": False,
        "verification": "with_expectation_readback_must_match; without_expectation_result_schema_only; empty_native_result_is_not_effect_proof"}
