"""Closed business contracts for Core runtime inspection and control."""

from __future__ import annotations

from typing import Any


RUNTIME_INSPECTION_BUSINESS_CONTRACT = (
    "waapi-skill.runtime-inspection-business/v1"
)
LOG_GET_URI = "ak.wwise.core.log.get"
_ALL_VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
_V2023_PLUS = ("2023.1", "2024.1", "2025.1")
_V2024_PLUS = ("2024.1", "2025.1")

PROFILER_GET_AUDIO_OBJECTS_URI = "ak.wwise.core.profiler.getAudioObjects"
PROFILER_GET_BUSSES_URI = "ak.wwise.core.profiler.getBusses"
PROFILER_GET_CURSOR_TIME_URI = "ak.wwise.core.profiler.getCursorTime"
PROFILER_GET_RTPS_URI = "ak.wwise.core.profiler.getRTPCs"
PROFILER_GET_VOICES_URI = "ak.wwise.core.profiler.getVoices"
PROFILER_GET_CPU_USAGE_URI = "ak.wwise.core.profiler.getCpuUsage"
PROFILER_GET_LOADED_MEDIA_URI = "ak.wwise.core.profiler.getLoadedMedia"
PROFILER_GET_PERFORMANCE_MONITOR_URI = (
    "ak.wwise.core.profiler.getPerformanceMonitor"
)
PROFILER_GET_STREAMED_MEDIA_URI = "ak.wwise.core.profiler.getStreamedMedia"
PROFILER_GET_METERS_URI = "ak.wwise.core.profiler.getMeters"
TRANSPORT_GET_STATE_URI = "ak.wwise.core.transport.getState"

_PROFILER_ROW_READS = {
    PROFILER_GET_AUDIO_OBJECTS_URI: _ALL_VERSIONS,
    PROFILER_GET_BUSSES_URI: _ALL_VERSIONS,
    PROFILER_GET_RTPS_URI: _ALL_VERSIONS,
    PROFILER_GET_VOICES_URI: _ALL_VERSIONS,
    PROFILER_GET_CPU_USAGE_URI: _V2023_PLUS,
    PROFILER_GET_LOADED_MEDIA_URI: _V2023_PLUS,
    PROFILER_GET_PERFORMANCE_MONITOR_URI: _V2023_PLUS,
    PROFILER_GET_STREAMED_MEDIA_URI: _V2023_PLUS,
    PROFILER_GET_METERS_URI: _V2024_PLUS,
}

_CONTRACTS: dict[str, dict[str, Any]] = {
    LOG_GET_URI: {
        "versions": _ALL_VERSIONS,
        "required_fields": ("log_channel",),
        "optional_fields": ("max_results",),
        "field_types": {
            "log_channel": "wwise_log_view",
            "max_results": "bounded_result_limit",
        },
        "input_forms": {
            "log_channel": {"flag": "--log-channel", "repeatable": False},
            "max_results": {"flag": "--max-results", "repeatable": False},
        },
    },
    PROFILER_GET_CURSOR_TIME_URI: {
        "versions": _ALL_VERSIONS,
        "required_fields": ("profiler_cursor",),
        "optional_fields": (),
        "field_types": {
            "profiler_cursor": "profiler_cursor_choice",
        },
        "input_forms": {
            "profiler_cursor": {"flag": "--profiler-cursor", "repeatable": False},
        },
    },
    TRANSPORT_GET_STATE_URI: {
        "versions": _ALL_VERSIONS,
        "required_fields": ("transport_handle",),
        "optional_fields": (),
        "field_types": {"transport_handle": "gateway_transport_session_handle"},
        "input_forms": {
            "transport_handle": {"flag": "--transport-handle", "repeatable": False},
        },
    },
}

for _operation, _versions in _PROFILER_ROW_READS.items():
    _optional = ["max_results"]
    if _operation in {
        PROFILER_GET_AUDIO_OBJECTS_URI,
        PROFILER_GET_BUSSES_URI,
        PROFILER_GET_VOICES_URI,
    }:
        _optional.append("result_view")
    if _operation in {PROFILER_GET_AUDIO_OBJECTS_URI, PROFILER_GET_BUSSES_URI}:
        _optional.append("bus_instance_handle")
    if _operation == PROFILER_GET_VOICES_URI:
        _optional.append("voice_instance_handle")
    _CONTRACTS[_operation] = {
        "versions": _versions,
        "required_fields": ("profiler_position",),
        "optional_fields": tuple(_optional),
        "field_types": {
            "profiler_position": "capture_latest_user_cursor_or_milliseconds",
            **({"result_view": "summary_identity_or_diagnostics"} if "result_view" in _optional else {}),
            **({"bus_instance_handle": "gateway_profiler_bus_handle"} if "bus_instance_handle" in _optional else {}),
            **({"voice_instance_handle": "gateway_profiler_voice_handle"} if "voice_instance_handle" in _optional else {}),
            "max_results": "bounded_result_limit",
        },
        "input_forms": {
            "profiler_position": {"flag": "--profiler-position", "repeatable": False},
            **({"result_view": {"flag": "--result-view", "repeatable": False}} if "result_view" in _optional else {}),
            **({"bus_instance_handle": {"flag": "--bus-instance-handle", "repeatable": False}} if "bus_instance_handle" in _optional else {}),
            **({"voice_instance_handle": {"flag": "--voice-instance-handle", "repeatable": False}} if "voice_instance_handle" in _optional else {}),
            "max_results": {"flag": "--max-results", "repeatable": False},
        },
    }


def runtime_inspection_business_operations() -> frozenset[str]:
    return frozenset(_CONTRACTS)


def runtime_inspection_business_read_operations() -> frozenset[str]:
    return frozenset(_CONTRACTS)


def runtime_inspection_business_versions(operation: str) -> tuple[str, ...]:
    try:
        return tuple(_CONTRACTS[operation]["versions"])
    except KeyError as exc:
        raise ValueError("unsupported runtime-inspection business operation") from exc


def runtime_inspection_business_catalog_rows() -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "api": operation,
            "intent": (
                "read one bounded Wwise log view in user-facing channel terms"
                if operation == LOG_GET_URI
                else "read one Authoring audition transport state from its Gateway handle"
                if operation == TRANSPORT_GET_STATE_URI
                else "read bounded Profiler state from a named time position and result view"
            ),
            "supported_versions": list(runtime_inspection_business_versions(operation)),
        }
        for operation in sorted(_CONTRACTS)
    )


def runtime_inspection_business_contract_data(
    operation: str,
    version: str,
) -> dict[str, Any]:
    try:
        row = _CONTRACTS[operation]
    except KeyError as exc:
        raise ValueError("unsupported runtime-inspection business operation") from exc
    if version not in row["versions"]:
        raise ValueError("runtime-inspection operation is unavailable in this version")
    return {
        "contract": RUNTIME_INSPECTION_BUSINESS_CONTRACT,
        "operation": operation,
        "version": version,
        "input_mode": "business_declaration",
        "execution_shape": "bounded_read",
        "start": {
            "subcommand": "core-call",
            "gateway_argv_prefix": ["core-call", operation],
        },
        "declaration": {
            "subcommand": "core-call",
            "required_fields": list(row["required_fields"]),
            "optional_fields": list(row["optional_fields"]),
            "field_types": dict(row["field_types"]),
            "input_forms": dict(row["input_forms"]),
        },
        "gateway_derivations": [
            "versioned_native_log_channel" if operation == LOG_GET_URI else "native_profiler_time",
            *( ["native_result_projection", "pipeline_handle"] if operation in _PROFILER_ROW_READS else [] ),
            "native_request",
            "result_projection",
            "result_bound",
            "continuation",
        ],
        "legacy_typed_call_public": False,
    }


__all__ = [
    "LOG_GET_URI",
    "PROFILER_GET_AUDIO_OBJECTS_URI",
    "PROFILER_GET_BUSSES_URI",
    "PROFILER_GET_CPU_USAGE_URI",
    "PROFILER_GET_CURSOR_TIME_URI",
    "PROFILER_GET_LOADED_MEDIA_URI",
    "PROFILER_GET_METERS_URI",
    "PROFILER_GET_PERFORMANCE_MONITOR_URI",
    "PROFILER_GET_RTPS_URI",
    "PROFILER_GET_STREAMED_MEDIA_URI",
    "PROFILER_GET_VOICES_URI",
    "TRANSPORT_GET_STATE_URI",
    "RUNTIME_INSPECTION_BUSINESS_CONTRACT",
    "runtime_inspection_business_catalog_rows",
    "runtime_inspection_business_contract_data",
    "runtime_inspection_business_operations",
    "runtime_inspection_business_read_operations",
    "runtime_inspection_business_versions",
]
