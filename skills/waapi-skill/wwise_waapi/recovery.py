"""Bounded recovery guidance; never authorization or an automatic retry engine."""
from collections.abc import Mapping
from typing import Any

RECOVERY_CONTRACT = "waapi-skill.recovery/v1"
PREWRITE_GUARD_REJECTION = {
    "contract": "waapi-skill.write-dispatch-evidence/v1",
    "status": "not_started",
    "reason": "confirmed_prewrite_guard_rejection",
}
READ_COMMANDS = frozenset({"query-object", "metadata", "status", "selected", "buses",
    "project-default-work-units", "profiler-game-objects", "profiler-voice-contributions",
    "core-call", "debug-wal-tree", "debug-validate-call", "waapi-schema"})


def cleanup_complete(payload: object, depth: int = 0) -> bool:
    if not isinstance(payload, Mapping):
        return True
    if depth > 8 or payload.get("cleanup_pending") is True or payload.get("cleanup_failure") is not None:
        return False
    if payload.get("status") in {"cleanup_failed", "cleanup_unproven", "pending"}:
        return False
    for key in ("details", "call", "cleanup", "transport_cleanup", "timeout"):
        value = payload.get(key)
        if key in {"cleanup", "transport_cleanup"} and isinstance(value, Mapping) and value.get("status") in {"failed", "unknown"}:
            return False
        if not cleanup_complete(value, depth + 1):
            return False
    return True


def recovery_receipt(
    payload: Mapping[str, Any], *, policy: str, command_routing_started: bool = False
) -> dict[str, Any] | None:
    command = payload.get("command")
    failed = payload.get("ok") is False
    state = payload.get("state")
    status = payload.get("status")
    no_match = command in READ_COMMANDS and (payload.get("count") == 0 or status in {
        "not_found", "needs_clarification", "no_match"})
    outcome = "no_project_write_in_this_invocation"
    actions = ["refine_read", "page_discovery", "inspect_configuration", "reconnect_once"]
    if state in {"indeterminate", "executing"} or status in {"indeterminate", "execution_in_progress"}:
        stage, outcome = "unknown_write_outcome", "unknown"
        actions = ["inspect_transaction", "independent_read_only_diagnosis"]
    elif payload.get("executed") is True or state in {"executed_unverified", "verified", "verification_failed", "result_schema_checked"}:
        stage = "known_write_outcome"
        outcome = "verified" if payload.get("verified") is True else "executed_not_business_verified"
        actions = ["inspect_transaction", "independent_read_only_diagnosis"]
        if command == "execute" and status == "executed_unverified":
            actions.append("follow_returned_verification")
    elif (failed and command == "execute" and state == "repreview_required"
          and status == "repreview_required"
          and payload.get("write_dispatch") == PREWRITE_GUARD_REJECTION):
        stage = "pre_dispatch_rejection"
        actions = ["inspect_transaction", "independent_read_only_diagnosis"]
        if policy in {"ask_before_changes", "allow_changes"}:
            actions.append("prepare_new_preview")
    elif failed and not command_routing_started:
        stage = "pre_dispatch_rejection"
        if command in {"execute", "verify", "transaction-show", "confirm", "reject"}:
            outcome = "prior_transaction_outcome_not_established_by_this_rejection"
            actions = ["inspect_configuration", "inspect_transaction", "independent_read_only_diagnosis"]
    elif failed and command in READ_COMMANDS:
        stage = "read_failure"
    elif failed and command in {"execute", "verify"}:
        stage, outcome = "unknown_write_outcome", "unknown"
        actions = ["inspect_transaction", "independent_read_only_diagnosis"]
    elif failed:
        stage = "preparation_rejection"
        actions = ["refine_read", "page_discovery", "inspect_configuration", "prepare_new_preview"]
    elif no_match:
        stage = "read_no_match"
    else:
        return None
    call = payload.get("call")
    code = payload.get("error_code") or (call.get("error_code") if isinstance(call, Mapping) else None)
    boundary = code in {"AUTHORING_HOST_REQUIRED", "CONSOLE_HOST_REQUIRED", "LOCAL_WAAPI_HOST_REQUIRED",
                        "API_NOT_FOUND", "MANIFEST_NOT_FOUND", "UNSUPPORTED_BY_SKILL_INTERFACE",
                        "ORIGINAL_FILE_REFERENCE_SCAN_INCOMPLETE"}
    if boundary:
        stage, actions = "explicit_boundary", ["report_explicit_boundary"]
    clean = cleanup_complete(payload)
    return {
        "contract": RECOVERY_CONTRACT,
        "stage": stage,
        "project_write_outcome": outcome,
        "modification_policy": policy,
        "read_only_continuation_allowed": clean and not boundary,
        "cleanup_complete": clean,
        "additional_read_permission_required": False,
        "scope": "existing_authorized_task_only",
        "actions": actions if clean else ["report_cleanup_boundary"],
        "max_reconnect_attempts": 1 if clean and not boundary else 0,
        "service_start_requires_existing_task_authorization": True,
        "original_write_replay_allowed": False,
        "next_change": {"read_only": "blocked", "ask_before_changes": "preview_then_explicit_confirmation",
                        "allow_changes": "preview_then_policy_authorization"}.get(policy, "configure_policy_first"),
    }
