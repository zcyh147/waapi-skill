"""Closed business declarations for schema, test-tone, and UI project routes."""

from __future__ import annotations

from typing import Any


HOST_UI_DEBUG_BUSINESS_CONTRACT = "waapi-skill.host-ui-debug-business/v1"
ALL_VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")

HOST_UI_DEBUG_BUSINESS_LANES: dict[str, tuple[str, ...]] = {
    "ak.wwise.waapi.getSchema": ALL_VERSIONS,
    "ak.wwise.debug.generateToneWAV": ("2023.1", "2024.1", "2025.1"),
    "ak.wwise.ui.project.open": ("2021.1", "2022.1", "2023.1"),
    "ak.wwise.ui.project.close": ("2021.1", "2022.1", "2023.1"),
    "ak.wwise.ui.project.create": ("2023.1",),
}
HOST_UI_DEBUG_BUSINESS_OPERATIONS = tuple(sorted(HOST_UI_DEBUG_BUSINESS_LANES))
HOST_UI_DEBUG_DRAFT_OPERATIONS = tuple(
    operation
    for operation in HOST_UI_DEBUG_BUSINESS_OPERATIONS
    if operation != "ak.wwise.waapi.getSchema"
)

WAVEFORM_CHOICES = ("silence", "sine", "triangle", "square", "white_noise")
BIT_DEPTH_CHOICES = ("int16", "float32")
CHANNEL_LAYOUT_CHOICES = (
    "0.1",
    "1.0",
    "2.0",
    "2.1",
    "3.0",
    "4.0",
    "5.1",
    "7.1",
    "5.1.2",
    "7.1.2",
    "7.1.4",
    "Ambisonics 1st order",
    "Ambisonics 2nd order",
    "Ambisonics 3rd order",
    "Ambisonics 4th order",
    "Ambisonics 5th order",
)
PROJECT_POLICY_CHOICES = ("migrate", "fail")
BASE_PLATFORM_CHOICES = (
    "Android",
    "iOS",
    "Linux",
    "Mac",
    "Switch",
    "Ounce",
    "PS4",
    "PS5",
    "Windows",
    "XboxOne",
    "XboxSeriesX",
    "Web",
    "OpenHarmony",
)


def host_ui_debug_business_versions(operation: str) -> tuple[str, ...]:
    try:
        return HOST_UI_DEBUG_BUSINESS_LANES[operation]
    except KeyError as exc:
        raise ValueError("unsupported host/UI/Debug business operation") from exc


def host_ui_debug_business_contract_data(
    operation: str,
    version: str,
) -> dict[str, Any]:
    versions = host_ui_debug_business_versions(operation)
    if version not in versions:
        raise ValueError("host/UI/Debug operation is unavailable in this version")
    required, optional, field_types = _fields(operation, version)
    public_fields = [*required, *optional]
    return {
        "contract": HOST_UI_DEBUG_BUSINESS_CONTRACT,
        "operation": operation,
        "version": version,
        "input_mode": (
            "bounded_business_read"
            if operation == "ak.wwise.waapi.getSchema"
            else "business_declaration"
        ),
        "execution_shape": (
            "bounded_read"
            if operation == "ak.wwise.waapi.getSchema"
            else "isolated_transaction"
        ),
        "start": {
            "subcommand": (
                "waapi-schema"
                if operation == "ak.wwise.waapi.getSchema"
                else "draft-start"
            ),
            **(
                {"gateway_argv_prefix": ["waapi-schema"]}
                if operation == "ak.wwise.waapi.getSchema"
                else {"gateway_argv": ["draft-start", operation]}
            ),
            "copy_exactly": True,
            "append_arguments": "forbidden",
        },
        "binding": {
            "available": False,
            "roles": [],
            "role_required": False,
            "identity": "none",
        },
        "declaration": {
            "subcommand": (
                "waapi-schema"
                if operation == "ak.wwise.waapi.getSchema"
                else "draft-declare-host-plan"
            ),
            "settings_field": "host_ui_debug_plan",
            "submit_once": True,
            "required_fields": required,
            "optional_fields": optional,
            "public_fields": public_fields,
            "field_types": field_types,
            "input_forms": {
                field: _input_form(field, field_types[field])
                for field in public_fields
            },
        },
        "responsibility_split": _responsibility(operation),
        "gateway_derivations": _derivations(operation),
        "legacy_typed_call_public": False,
        "legacy_native_request_public": False,
        "safety": {
            "immutable_preview": operation != "ak.wwise.waapi.getSchema",
            "single_execute": operation != "ak.wwise.waapi.getSchema",
            "bounded_direct_read": operation == "ak.wwise.waapi.getSchema",
            "authoring_host_required": operation.startswith("ak.wwise.ui."),
            "isolated_io_audit": operation
            in {
                "ak.wwise.debug.generateToneWAV",
                "ak.wwise.ui.project.create",
                "ak.wwise.ui.project.open",
            },
            "native_request_fields": "gateway_owned",
        },
    }


def host_ui_debug_business_catalog_rows() -> tuple[dict[str, Any], ...]:
    descriptions = {
        "ak.wwise.waapi.getSchema": "read one exact WAAPI schema",
        "ak.wwise.debug.generateToneWAV": "generate one bounded test tone file",
        "ak.wwise.ui.project.open": "open one exact Authoring project",
        "ak.wwise.ui.project.close": "close the current Authoring project",
        "ak.wwise.ui.project.create": "create one exact Authoring project",
    }
    return tuple(
        {
            "api": operation,
            "intent": descriptions[operation],
            "supported_versions": list(host_ui_debug_business_versions(operation)),
        }
        for operation in HOST_UI_DEBUG_BUSINESS_OPERATIONS
    )


def _fields(
    operation: str,
    version: str,
) -> tuple[list[str], list[str], dict[str, str]]:
    if operation == "ak.wwise.waapi.getSchema":
        optional = ["include_examples"] if version in {"2024.1", "2025.1"} else []
        return ["target_uri"], optional, {
            "target_uri": "exact_waapi_uri",
            "include_examples": "boolean",
        }
    if operation == "ak.wwise.debug.generateToneWAV":
        optional = [
            "waveform",
            "frequency_hz",
            "channel_layout",
            "bit_depth",
            "sample_rate_hz",
            "attack_seconds",
            "sustain_seconds",
            "release_seconds",
            "sustain_db",
        ]
        if version in {"2024.1", "2025.1"}:
            optional.extend(["anonymous_channels", "waveform_channels"])
        if version == "2025.1":
            optional.append("markers")
        return ["output_file"], optional, {
            "output_file": "exact_wav_file",
            "waveform": "waveform",
            "frequency_hz": "frequency_hz",
            "channel_layout": "channel_layout",
            "bit_depth": "bit_depth",
            "sample_rate_hz": "sample_rate_hz",
            "attack_seconds": "nonnegative_seconds",
            "sustain_seconds": "nonnegative_seconds",
            "release_seconds": "nonnegative_seconds",
            "sustain_db": "sustain_db",
            "anonymous_channels": "boolean",
            "waveform_channels": "channel_index_list",
            "markers": "tone_marker_list",
        }
    if operation == "ak.wwise.ui.project.open":
        optional = ["discard_unsaved_current_project", "upgrade_policy"]
        if version == "2023.1":
            optional.extend(["migration_policy", "auto_checkout"])
        return ["project_file"], optional, {
            "project_file": "exact_project_file",
            "discard_unsaved_current_project": "boolean",
            "upgrade_policy": "project_policy",
            "migration_policy": "project_policy",
            "auto_checkout": "boolean",
        }
    if operation == "ak.wwise.ui.project.close":
        return [], ["discard_unsaved_changes"], {
            "discard_unsaved_changes": "boolean"
        }
    return ["project_file"], ["languages", "platforms"], {
        "project_file": "exact_project_file",
        "languages": "language_name_list",
        "platforms": "platform_creation_mappings",
    }


def _input_form(field: str, field_type: str) -> dict[str, Any]:
    if field_type == "boolean":
        return {
            "flag": "--toggle",
            "arguments": [field, "enable|disable"],
            "repeatable": False,
        }
    if field_type in {"language_name_list", "channel_index_list"}:
        result: dict[str, Any] = {
            "flag": "--item",
            "arguments": [field, "<value>"],
            "repeatable": True,
        }
        if field_type == "channel_index_list":
            result["range"] = [0, 63]
        return result
    if field_type == "platform_creation_mappings":
        return {
            "flag": "--mapping",
            "arguments": [field, "<base-platform>", "<project-platform-name>"],
            "repeatable": True,
            "key_choices": list(BASE_PLATFORM_CHOICES),
        }
    if field_type == "tone_marker_list":
        return {
            "flag": "--marker",
            "arguments": ["<position-seconds>", "[exact-label]"],
            "repeatable": True,
        }
    result = {
        "flag": "--value",
        "arguments": [field, "<value>"],
        "repeatable": False,
    }
    choices = {
        "waveform": WAVEFORM_CHOICES,
        "channel_layout": CHANNEL_LAYOUT_CHOICES,
        "bit_depth": BIT_DEPTH_CHOICES,
        "project_policy": PROJECT_POLICY_CHOICES,
    }.get(field_type)
    if choices is not None:
        result["choices"] = list(choices)
    ranges = {
        "frequency_hz": [1, 22000],
        "sample_rate_hz": [300, 192000],
        "nonnegative_seconds": [0, None],
        "sustain_db": [-100, 0],
    }
    if field_type in ranges:
        result["range"] = ranges[field_type]
    return result


def _responsibility(operation: str) -> dict[str, str]:
    if operation == "ak.wwise.waapi.getSchema":
        agent = "provide_one_exact_schema_target_and_the_requested_example_outcome"
    elif operation == "ak.wwise.debug.generateToneWAV":
        agent = "provide_the_test_tone_file_and_audio_outcomes_in_business_units"
    else:
        agent = "provide_the_exact_project_artifact_and_requested_authoring_outcome"
    return {
        "agent": agent,
        "gateway": (
            "derive_versioned_native_fields_bitmasks_platform_objects_io_policy_"
            "project_transition_preview_and_verification"
        ),
    }


def _derivations(operation: str) -> list[str]:
    shared = ["version_specific_field_availability", "native_request_shape"]
    if operation == "ak.wwise.waapi.getSchema":
        return [*shared, "bounded_direct_read_and_result_limit"]
    if operation == "ak.wwise.debug.generateToneWAV":
        return [
            *shared,
            "waveform_spelling_and_channel_bitmask",
            "isolated_output_root",
            "immutable_preview_and_result_verification",
        ]
    return [
        *shared,
        "authoring_host_and_project_transition_guard",
        "isolated_project_root_when_applicable",
        "immutable_preview_and_result_verification",
    ]


__all__ = [
    "HOST_UI_DEBUG_BUSINESS_CONTRACT",
    "HOST_UI_DEBUG_DRAFT_OPERATIONS",
    "HOST_UI_DEBUG_BUSINESS_LANES",
    "HOST_UI_DEBUG_BUSINESS_OPERATIONS",
    "host_ui_debug_business_catalog_rows",
    "host_ui_debug_business_contract_data",
    "host_ui_debug_business_versions",
]
