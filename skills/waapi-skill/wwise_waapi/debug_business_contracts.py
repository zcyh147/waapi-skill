"""Closed business declarations for named Debug host controls."""

from __future__ import annotations

from typing import Any

from .business_declarations import SUPPORTED_WWISE_VERSIONS


DEBUG_BUSINESS_CONTRACT = "waapi-skill.debug-business/v1"
DEBUG_BUSINESS_LANES = {
    "debug.setAsserts": SUPPORTED_WWISE_VERSIONS,
    "debug.setAutomationMode": SUPPORTED_WWISE_VERSIONS,
    "debug.restartWaapiServers": ("2023.1", "2024.1", "2025.1"),
    "debug.testAssert": SUPPORTED_WWISE_VERSIONS,
    "debug.testCrash": SUPPORTED_WWISE_VERSIONS,
}
DEBUG_BOOLEAN_OPERATIONS = frozenset(
    {"debug.setAsserts", "debug.setAutomationMode"}
)
DEBUG_TERMINAL_OPERATIONS = frozenset(
    {"debug.restartWaapiServers", "debug.testAssert", "debug.testCrash"}
)


def debug_business_contract_data(operation: str, version: str) -> dict[str, Any]:
    versions = DEBUG_BUSINESS_LANES.get(operation)
    if versions is None:
        raise ValueError("unsupported Debug business operation")
    if version not in versions:
        raise ValueError("unsupported Debug operation version")
    boolean = operation in DEBUG_BOOLEAN_OPERATIONS
    return {
        "contract": DEBUG_BUSINESS_CONTRACT,
        "operation": operation,
        "version": version,
        "input_mode": "business_declaration",
        "start": {
            "subcommand": "draft-start",
            "gateway_argv": ["draft-start", operation],
            "copy_exactly": True,
            "append_arguments": "forbidden",
        },
        "binding": {"available": False, "roles": [], "role_required": False},
        "declaration": {
            "subcommand": "draft-declare-debug-intent",
            "settings_field": "debug_intent",
            "submit_once": True,
            "business_values_required": boolean,
            "public_fields": ["enabled"] if boolean else [],
            "choices": ["--enable", "--disable"] if boolean else [],
            "native_request_fields": "forbidden",
        },
        "responsibility_split": {
            "agent": (
                "choose_the_requested_enabled_or_disabled_business_outcome"
                if boolean
                else "select_the_exact_deliberate_host_control_requested_by_the_user"
            ),
            "gateway": (
                "derive_native_boolean_envelope_result_schema_boundary_and_nonretry_policy"
                if boolean
                else "derive_fixed_native_envelope_authorization_terminal_journal_"
                "disconnect_interpretation_and_nonretry_boundary"
            ),
        },
        "gateway_derivations": (
            [
                "native_uri_boolean_args_and_empty_options",
                "process_wide_no_state_getter_boundary",
                "result_schema_verification",
                "automatic_retry_forbidden",
            ]
            if boolean
            else [
                "native_uri_and_empty_options",
                "fixed_internal_host_control_marker",
                "explicit_confirmation_boundary",
                "terminal_dispatch_journal",
                "disconnect_interpretation",
                "automatic_retry_forbidden",
            ]
        ),
        "legacy_inline_typed_public": False,
        "legacy_composer_public": False,
        "safety": {
            "immutable_preview": True,
            "single_execute": True,
            "automatic_retry": False,
            "reconnect_and_repeat": False,
            "explicit_confirmation_only": operation in DEBUG_TERMINAL_OPERATIONS,
            "terminal_result": operation in DEBUG_TERMINAL_OPERATIONS,
            "real_crash_required": False,
        },
    }


__all__ = [
    "DEBUG_BOOLEAN_OPERATIONS",
    "DEBUG_BUSINESS_CONTRACT",
    "DEBUG_BUSINESS_LANES",
    "DEBUG_TERMINAL_OPERATIONS",
    "debug_business_contract_data",
]
