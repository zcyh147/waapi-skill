"""Closed business contracts for Core runtime inspection and control."""

from __future__ import annotations

from typing import Any

from .subscriptions import DEFAULT_WAIT_TIMEOUT, MAX_WAIT_EVENT_COUNT


RUNTIME_INSPECTION_BUSINESS_CONTRACT = (
    "waapi-skill.runtime-inspection-business/v1"
)
RUNTIME_CONTROL_BUSINESS_CONTRACT = "waapi-skill.runtime-control-business/v1"
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
PROFILER_ENABLE_DATA_URI = "ak.wwise.core.profiler.enableProfilerData"
PROFILER_CAPTURE_DATA_VERIFICATION = {
    "strategy": "native_result_schema_only",
    "enabled_settings_verified": False,
    "empty_effect_verified": False,
    "repeated_data_set_resolution_verified": False,
    "prior_settings_restoration_verified": False,
    "boundary": "Native acknowledgment does not establish final enabled settings, empty-list effects, repeated-data-set resolution, or prior-setting restoration.",
}
PROFILER_REGISTER_METER_URI = "ak.wwise.core.profiler.registerMeter"
PROFILER_SAVE_CAPTURE_URI = "ak.wwise.core.profiler.saveCapture"
PROFILER_UNREGISTER_METER_URI = "ak.wwise.core.profiler.unregisterMeter"
PROFILER_MOVE_CURSOR_URI = "ak.wwise.core.profiler.moveCursor"
PROFILER_SET_CURSOR_TIME_URI = "ak.wwise.core.profiler.setCursorTime"
LOG_ADD_ITEM_URI = "ak.wwise.core.log.addItem"
LOG_CLEAR_URI = "ak.wwise.core.log.clear"
CONSOLE_LOG_ADD_OBSERVER = {
    'topic': 'ak.wwise.core.log.itemAdded',
    'ordering': 'subscribe_before_one_add; unsubscribe_before_execute_returns',
    'wait_seconds': DEFAULT_WAIT_TIMEOUT,
    'maximum_events': MAX_WAIT_EVENT_COUNT,
    'maximum_event_bytes': 64 * 1024,
    'matching': 'exact_sealed_channel_message_severity',
    'boundary': 'One matching addition event; no exclusive writer, continuing channel contents, entry identity, or prior-state restoration proof.',
}
REMOTE_CONNECT_URI = "ak.wwise.core.remote.connect"
TRANSPORT_CREATE_URI = "ak.wwise.core.transport.create"
TRANSPORT_DESTROY_URI = "ak.wwise.core.transport.destroy"
TRANSPORT_EXECUTE_ACTION_URI = "ak.wwise.core.transport.executeAction"
TRANSPORT_GET_STATE_URI = "ak.wwise.core.transport.getState"
TRANSPORT_PREPARE_URI = "ak.wwise.core.transport.prepare"
TRANSPORT_USE_ORIGINALS_URI = "ak.wwise.core.transport.useOriginals"

PROFILER_CURSOR_MEANINGS = {"capture-latest": "capture", "user-cursor": "user"}

BASE_LOG_CHANNEL_MEANINGS = {
    "soundbank-generation": "soundbankGenerate",
    "audio-conversion": "conversion",
    "platform-settings-copy": "copyPlatformSettings",
    "waapi": "waapi",
    "project-load": "projectLoad",
    "general": "general",
}

LATER_LOG_CHANNEL_MEANINGS = {
    **BASE_LOG_CHANNEL_MEANINGS,
    "source-control": "sourceControl",
    "lua": "lua",
}

PROFILER_CURSOR_MOVE_MEANINGS = {
    "first-frame": "first",
    "last-frame": "last",
    "next-frame": "next",
    "previous-frame": "previous",
}

LOG_SEVERITY_MEANINGS = {
    "message": "Message",
    "warning": "Warning",
    "error": "Error",
    "fatal": "Fatal Error",
}

AUDITION_ACTION_MEANINGS = {
    "play": "play",
    "stop": "stop",
    "pause": "pause",
    "toggle-play-stop": "playStop",
    "play-directly": "playDirectly",
}

MAX_PROFILER_RESULT_FIELDS = 64

PROFILER_RETURN_VIEWS = {
    PROFILER_GET_AUDIO_OBJECTS_URI: {
        "summary": (
            "audioObjectID",
            "audioObjectName",
            "busPipelineID",
            "busName",
            "gameObjectName",
            "rmsMeter",
            "peakMeter",
        ),
        "identity": (
            "audioObjectID",
            "audioObjectName",
            "busPipelineID",
            "busGUID",
            "busName",
            "gameObjectID",
            "gameObjectName",
            "instigatorPipelineID",
        ),
        "diagnostics": (
            "audioObjectID",
            "audioObjectName",
            "busPipelineID",
            "busGUID",
            "busName",
            "gameObjectID",
            "gameObjectName",
            "instigatorPipelineID",
            "effectPluginName",
            "spatializationMode",
            "x",
            "y",
            "z",
            "spread",
            "focus",
            "channelConfig",
            "metadata",
            "rmsMeter",
            "peakMeter",
        ),
    },
    PROFILER_GET_BUSSES_URI: {
        "summary": (
            "pipelineID",
            "objectName",
            "gameObjectName",
            "volume",
            "downstreamGain",
            "voiceCount",
            "depth",
        ),
        "identity": (
            "pipelineID",
            "objectGUID",
            "objectName",
            "gameObjectID",
            "gameObjectName",
        ),
        "diagnostics": (
            "pipelineID",
            "mixBusID",
            "objectGUID",
            "objectName",
            "gameObjectID",
            "gameObjectName",
            "deviceID",
            "volume",
            "downstreamGain",
            "voiceCount",
            "depth",
        ),
    },
    PROFILER_GET_VOICES_URI: {
        "summary": (
            "pipelineID",
            "objectName",
            "gameObjectName",
            "baseVolume",
            "isStarted",
            "isVirtual",
        ),
        "identity": (
            "pipelineID",
            "playingID",
            "objectGUID",
            "objectName",
            "playTargetGUID",
            "playTargetName",
            "gameObjectID",
            "gameObjectName",
        ),
        "diagnostics": (
            "pipelineID",
            "playingID",
            "soundID",
            "gameObjectID",
            "gameObjectName",
            "objectGUID",
            "objectName",
            "playTargetID",
            "playTargetGUID",
            "playTargetName",
            "baseVolume",
            "gameAuxSendVolume",
            "envelope",
            "normalizationGain",
            "lowPassFilter",
            "highPassFilter",
            "priority",
            "isStarted",
            "isVirtual",
            "isForcedVirtual",
        ),
    },
}

TRANSPORT_SCOPE_CHOICES = ("one-transport", "all-active")
AUDITION_MEDIA_CHOICES = ("originals", "converted")


def profiler_return_views(operation: str, version: str) -> dict[str, tuple[str, ...] | None]:
    """Five pinned definitions own the projection deltas, not URI equality."""
    views = dict(PROFILER_RETURN_VIEWS[operation])
    if operation == PROFILER_GET_AUDIO_OBJECTS_URI:
        views["diagnostics"] = (*views["diagnostics"], "busID", "effectClassID", "effectIndex")
    if operation == PROFILER_GET_BUSSES_URI:
        views["diagnostics"] = (*views["diagnostics"], "mixerID" if version in {"2021.1", "2022.1"} else "effectCount")
    views["capture-defaults"] = None
    views["empty-selection"] = ()
    return views


def profiler_result_field_choices(operation: str, version: str) -> tuple[str, ...]:
    """Closed choices matching the version's complete pinned return vocabulary."""
    return profiler_return_views(operation, version)["diagnostics"]


PROFILER_CAPTURE_DATA_CHOICES = {
    "2021.1": (
        "api-calls", "audio-objects", "auxiliary-sends", "cpu", "inactive-game-syncs",
        "listeners", "loaded-media", "markers", "memory", "meters", "music-transitions",
        "obstruction-occlusion", "output", "prepared-events", "prepared-game-syncs",
        "soundbanks", "spatial-audio", "streaming", "streaming-device", "voice-inspector",
        "voices",
    ),
    "2022.1": (
        "api-calls", "audio-objects", "auxiliary-sends", "cpu", "game-syncs",
        "interactive-music", "listeners", "loaded-media", "markers", "memory", "meters",
        "obstruction-occlusion", "output", "prepared-events", "prepared-game-syncs",
        "soundbanks", "spatial-audio", "streaming", "streaming-device", "voice-inspector",
        "voices",
    ),
    "2023.1": (
        "api-calls", "audio-objects", "auxiliary-sends", "cpu", "game-syncs",
        "interactive-music", "listeners", "loaded-media", "markers", "memory", "meters",
        "obstruction-occlusion", "prepared-events", "prepared-game-syncs", "soundbanks",
        "spatial-audio", "spatial-audio-raycasting", "streaming", "streaming-device",
        "voice-inspector", "voices",
    ),
    "2024.1": (
        "api-calls", "audio-objects", "auxiliary-sends", "cpu", "game-syncs",
        "interactive-music", "listeners", "loaded-media", "markers", "memory", "meters",
        "obstruction-occlusion", "prepared-game-syncs", "prepared-objects", "soundbanks",
        "spatial-audio", "spatial-audio-raycasting", "streaming", "streaming-device",
        "voice-inspector", "voices",
    ),
    "2025.1": (
        "api-calls", "audio-objects", "auxiliary-sends", "cpu", "customer-support-data",
        "game-syncs", "interactive-music", "listeners", "loaded-media", "markers", "memory",
        "meters", "obstruction-occlusion", "prepared-game-syncs", "prepared-objects",
        "soundbanks", "spatial-audio", "spatial-audio-raycasting", "streaming",
        "streaming-device", "voice-inspector", "voices",
    ),
}

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
    PROFILER_MOVE_CURSOR_URI: {
        "versions": ("2025.1",),
        "execution_shape": "draft_mutation",
        "required_fields": ("cursor_move",),
        "optional_fields": (),
        "field_types": {"cursor_move": "profiler_frame_move"},
        "input_forms": {
            "cursor_move": {"flag": "--cursor-move", "repeatable": False},
        },
    },
    PROFILER_SET_CURSOR_TIME_URI: {
        "versions": ("2025.1",),
        "execution_shape": "draft_mutation",
        "required_fields": ("cursor_target_ms",),
        "optional_fields": (),
        "field_types": {"cursor_target_ms": "signed_integer_milliseconds"},
        "input_forms": {
            "cursor_target_ms": {
                "flag": "--cursor-target-ms",
                "repeatable": False,
            },
        },
    },
    PROFILER_ENABLE_DATA_URI: {
        "versions": _ALL_VERSIONS,
        "execution_shape": "draft_mutation",
        "required_fields": ("capture_data_changes",),
        "optional_fields": (),
        "field_types": {
            "capture_data_changes": "profiler_capture_data_enablement_changes"
        },
        "input_forms": {
            "capture_data_changes": {
                "flag": "--capture-data",
                "repeatable": True,
                "empty_flag": "--capture-data-empty",
                "empty_flag_exclusive_with": "--capture-data",
                "values_per_occurrence": 2,
            },
        },
    },
    LOG_ADD_ITEM_URI: {
        "versions": _V2023_PLUS,
        "execution_shape": "draft_mutation",
        "required_fields": ("message",),
        "optional_fields": ("log_channel", "severity"),
        "field_types": {
            "message": "bounded_exact_log_message",
            "log_channel": "wwise_log_view",
            "severity": "message_warning_error_or_fatal",
        },
        "input_forms": {
            "message": {"flag": "--message", "repeatable": False},
            "log_channel": {"flag": "--log-channel", "repeatable": False},
            "severity": {"flag": "--severity", "repeatable": False},
        },
    },
    LOG_CLEAR_URI: {
        "versions": _V2023_PLUS,
        "execution_shape": "draft_mutation",
        "required_fields": ("log_channel",),
        "optional_fields": (),
        "field_types": {"log_channel": "wwise_log_view"},
        "input_forms": {
            "log_channel": {"flag": "--log-channel", "repeatable": False},
        },
    },
    REMOTE_CONNECT_URI: {
        "versions": _ALL_VERSIONS,
        "execution_shape": "draft_mutation",
        "required_fields": ("remote_host",),
        "optional_fields": ("application_name", "command_port", "notification_port"),
        "optional_fields_by_version": {
            "2021.1": ("application_name", "command_port", "notification_port"),
        },
        "field_types": {
            "remote_host": "exact_remote_host_or_capture",
            "application_name": "exact_remote_application_name",
            "command_port": "tcp_port",
            "notification_port": "tcp_port",
        },
        "input_forms": {
            "remote_host": {"flag": "--remote-host", "repeatable": False},
            "application_name": {"flag": "--application-name", "repeatable": False},
            "command_port": {"flag": "--command-port", "repeatable": False},
            "notification_port": {"flag": "--notification-port", "repeatable": False},
        },
    },
    TRANSPORT_CREATE_URI: {
        "versions": _ALL_VERSIONS,
        "execution_shape": "draft_mutation",
        "roles": ("target",),
        "required_fields": ("target_handle",),
        "optional_fields": ("game_object_id",),
        "field_types": {
            "target_handle": "bound_authoring_object_handle",
            "game_object_id": "runtime_game_object_id",
        },
        "input_forms": {
            "target_handle": {"flag": "--target-handle", "repeatable": False},
            "game_object_id": {"flag": "--game-object-id", "repeatable": False},
        },
    },
    TRANSPORT_DESTROY_URI: {
        "versions": _ALL_VERSIONS,
        "execution_shape": "draft_mutation",
        "required_fields": ("transport_handle",),
        "optional_fields": (),
        "field_types": {"transport_handle": "gateway_transport_session_handle"},
        "input_forms": {
            "transport_handle": {"flag": "--transport-handle", "repeatable": False},
        },
    },
    TRANSPORT_EXECUTE_ACTION_URI: {
        "versions": _ALL_VERSIONS,
        "execution_shape": "draft_mutation",
        "required_fields": ("audition_action", "transport_scope"),
        "optional_fields": ("transport_handle",),
        "field_types": {
            "audition_action": "play_stop_pause_toggle_or_play_directly",
            "transport_scope": "one_transport_or_all_active",
            "transport_handle": "gateway_transport_session_handle",
        },
        "input_forms": {
            "audition_action": {"flag": "--audition-action", "repeatable": False},
            "transport_scope": {"flag": "--transport-scope", "repeatable": False},
            "transport_handle": {"flag": "--transport-handle", "repeatable": False},
        },
    },
    TRANSPORT_PREPARE_URI: {
        "versions": ("2022.1", "2023.1", "2024.1", "2025.1"),
        "execution_shape": "draft_mutation",
        "roles": ("target",),
        "required_fields": ("target_handle",),
        "optional_fields": (),
        "field_types": {"target_handle": "bound_authoring_object_handle"},
        "input_forms": {
            "target_handle": {"flag": "--target-handle", "repeatable": False},
        },
    },
    TRANSPORT_USE_ORIGINALS_URI: {
        "versions": _V2023_PLUS,
        "execution_shape": "draft_mutation",
        "required_fields": ("audition_media",),
        "optional_fields": (),
        "field_types": {"audition_media": "originals_or_converted"},
        "input_forms": {
            "audition_media": {"flag": "--audition-media", "repeatable": False},
        },
    },
    PROFILER_SAVE_CAPTURE_URI: {
        "versions": _V2023_PLUS,
        "execution_shape": "draft_mutation",
        "required_fields": ("capture_output_directory", "capture_name"),
        "optional_fields": (),
        "field_types": {
            "capture_output_directory": "exact_authorized_host_directory",
            "capture_name": "host_valid_profiler_capture_name",
        },
        "input_forms": {
            "capture_output_directory": {"flag": "--capture-output-directory", "repeatable": False},
            "capture_name": {"flag": "--capture-name", "repeatable": False},
        },
    },
    PROFILER_REGISTER_METER_URI: {
        "versions": _V2024_PLUS,
        "execution_shape": "draft_mutation",
        "roles": ("meter_object",),
        "required_fields": ("meter_object_handle",),
        "optional_fields": (),
        "field_types": {"meter_object_handle": "bound_meter_object_handle"},
        "input_forms": {
            "meter_object_handle": {"flag": "--meter-object-handle", "repeatable": False},
        },
    },
    PROFILER_UNREGISTER_METER_URI: {
        "versions": _V2024_PLUS,
        "execution_shape": "draft_mutation",
        "roles": ("meter_object",),
        "required_fields": ("meter_object_handle",),
        "optional_fields": (),
        "field_types": {"meter_object_handle": "bound_meter_object_handle"},
        "input_forms": {
            "meter_object_handle": {"flag": "--meter-object-handle", "repeatable": False},
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
        _optional.extend(("result_view", "result_fields"))
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
            **({"result_fields": "ordered_disclosed_profiler_field_choices"} if "result_fields" in _optional else {}),
            **({"bus_instance_handle": "gateway_profiler_bus_handle"} if "bus_instance_handle" in _optional else {}),
            **({"voice_instance_handle": "gateway_profiler_voice_handle"} if "voice_instance_handle" in _optional else {}),
            "max_results": "bounded_result_limit",
        },
        "input_forms": {
            "profiler_position": {"flag": "--profiler-position", "repeatable": False},
            **({"result_view": {"flag": "--result-view", "repeatable": False}} if "result_view" in _optional else {}),
            **({"result_fields": {"flag": "--result-field", "repeatable": True,
                "minimum_items": 1, "maximum_items": MAX_PROFILER_RESULT_FIELDS,
                "bound_owner": "Gateway request resource policy",
                "order_preserved": True, "repetitions_preserved": True,
                "mutually_exclusive_with": ["result_view"]}} if "result_fields" in _optional else {}),
            **({"bus_instance_handle": {"flag": "--bus-instance-handle", "repeatable": False}} if "bus_instance_handle" in _optional else {}),
            **({"voice_instance_handle": {"flag": "--voice-instance-handle", "repeatable": False}} if "voice_instance_handle" in _optional else {}),
            "max_results": {"flag": "--max-results", "repeatable": False},
        },
    }

_READ_OPERATIONS = frozenset(
    {LOG_GET_URI, PROFILER_GET_CURSOR_TIME_URI, TRANSPORT_GET_STATE_URI}
    | set(_PROFILER_ROW_READS)
)
_CONTROL_OPERATIONS = frozenset(
    {
        LOG_ADD_ITEM_URI,
        LOG_CLEAR_URI,
        PROFILER_ENABLE_DATA_URI,
        PROFILER_MOVE_CURSOR_URI,
        PROFILER_REGISTER_METER_URI,
        PROFILER_SAVE_CAPTURE_URI,
        PROFILER_SET_CURSOR_TIME_URI,
        PROFILER_UNREGISTER_METER_URI,
        REMOTE_CONNECT_URI,
        TRANSPORT_CREATE_URI,
        TRANSPORT_DESTROY_URI,
        TRANSPORT_EXECUTE_ACTION_URI,
        TRANSPORT_PREPARE_URI,
        TRANSPORT_USE_ORIGINALS_URI,
    }
)


def runtime_inspection_business_operations() -> frozenset[str]:
    return frozenset(_CONTRACTS)


def runtime_inspection_business_read_operations() -> frozenset[str]:
    return _READ_OPERATIONS


def runtime_control_business_operations() -> frozenset[str]:
    return _CONTROL_OPERATIONS


def runtime_inspection_business_versions(operation: str) -> tuple[str, ...]:
    try:
        return tuple(_CONTRACTS[operation]["versions"])
    except KeyError as exc:
        raise ValueError("unsupported runtime-inspection business operation") from exc


def runtime_transport_requires_authoring(operation: str, version: str) -> bool:
    """Require Authoring for transport outside the packaged 2025.1 Console scope."""
    return operation.startswith("ak.wwise.core.transport.") and version != "2025.1"


def runtime_inspection_business_catalog_rows() -> tuple[dict[str, Any], ...]:
    def intent(operation: str) -> str:
        if operation == LOG_GET_URI:
            return "read one bounded Wwise log view in user-facing channel terms"
        if operation == LOG_ADD_ITEM_URI:
            return "add one message to a named Authoring Log view"
        if operation == LOG_CLEAR_URI:
            return "clear one named Authoring Log view"
        if operation.startswith("ak.wwise.core.remote."):
            return "connect Authoring to one exact remote runtime or Profiler capture"
        if operation.startswith("ak.wwise.core.transport."):
            return "create, inspect, or control a versioned audition transport"
        if operation in _CONTROL_OPERATIONS:
            return "configure or control one named Profiler capture, cursor, meter, or file outcome"
        return "read bounded Profiler state from a named time position and result view"

    return tuple(
        {
            "api": operation,
            "intent": intent(operation),
            "supported_versions": list(runtime_inspection_business_versions(operation)),
            **({"console_versions": ["2025.1"]}
                if operation.startswith("ak.wwise.core.transport.") else {}),
            "host_requirement": (
                "wwise-authoring"
                if operation.startswith("ak.wwise.core.remote.")
                else "wwise-console-or-authoring"
            ),
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
    optional_fields = tuple(
        row.get("optional_fields_by_version", {}).get(
            version,
            row["optional_fields"],
        )
    )
    meter_contract = None
    if operation == PROFILER_GET_METERS_URI:
        from .profiler_meter_objects import meter_object_contract
        meter_contract = meter_object_contract(version)
        optional_fields = (*optional_fields, *meter_contract['fields'])
    exposed_fields = set(row["required_fields"]) | set(optional_fields)
    roles = tuple(row.get("roles", ()))
    role_field = {
        "target": "target_handle",
        "meter_object": "meter_object_handle",
    }
    execution_shape = row.get("execution_shape", "bounded_read")
    bounded_read = execution_shape == "bounded_read"
    capture_verification = {}
    if operation == PROFILER_SAVE_CAPTURE_URI:
        from .operation_soundbank import MAX_TREE_FILES, MAX_TREE_ENTRIES, MAX_TREE_TOTAL_BYTES, MAX_TREE_FILE_BYTES, MAX_TREE_DEPTH
        capture_verification = {"verification": {
            "requires_created_or_content_changed_nonempty_file": True,
            "capture_format_validity_verified": False,
            "capture_content_completeness_verified": False,
            "preservation": "bounded output-directory regular-file contents; no outside-directory observation",
            "path_protection": "exact authorized destination, non-link regular file, unchanged Preview and directory identities",
            "resource_bound_owner": "Gateway artifact observation policy, not native capture limits",
            "resource_bounds": {"max_files": MAX_TREE_FILES, "max_entries": MAX_TREE_ENTRIES,
                "max_total_bytes": MAX_TREE_TOTAL_BYTES, "max_file_bytes": MAX_TREE_FILE_BYTES,
                "max_depth": MAX_TREE_DEPTH},
        }}
    value_choices = {}
    field_meanings = {
        "log_channel": BASE_LOG_CHANNEL_MEANINGS if version in {"2021.1", "2022.1"} else LATER_LOG_CHANNEL_MEANINGS,
        "cursor_move": PROFILER_CURSOR_MOVE_MEANINGS,
        "severity": LOG_SEVERITY_MEANINGS,
        "audition_action": AUDITION_ACTION_MEANINGS,
        "transport_scope": TRANSPORT_SCOPE_CHOICES,
        "audition_media": AUDITION_MEDIA_CHOICES,
    }
    for field, meanings in field_meanings.items():
        if field in exposed_fields:
            value_choices[field] = list(meanings)
    if "result_view" in exposed_fields:
        value_choices["result_view"] = list(profiler_return_views(operation, version))
        value_choices["result_fields"] = list(profiler_result_field_choices(operation, version))
    if "profiler_cursor" in exposed_fields:
        value_choices["profiler_cursor"] = list(PROFILER_CURSOR_MEANINGS)
    if operation == PROFILER_ENABLE_DATA_URI:
        value_choices.update({
            "capture_data_changes.data_set": list(PROFILER_CAPTURE_DATA_CHOICES[version]),
            "capture_data_changes.outcome": ["enable", "disable"],
        })
    if operation.startswith("ak.wwise.core.log."):
        derivations = [
            "versioned_native_log_channel",
            *(["native_log_severity"] if operation == LOG_ADD_ITEM_URI else []),
            "native_request",
        ]
    elif operation.startswith("ak.wwise.core.remote."):
        derivations = [
            "versioned_remote_selector",
            "native_port_pair",
            "native_request",
            "remote_connection_verification",
            "disconnect_cleanup",
        ]
    elif operation.startswith("ak.wwise.core.transport."):
        derivations = [
            "bound_authoring_object_identity",
            "live_transport_handle",
            "native_audition_action",
            "native_request",
            "transport_verification",
            "transport_cleanup",
        ]
    else:
        derivations = [
            "native_profiler_time_or_cursor_action",
            "versioned_capture_data_rows",
            "bound_meter_identity",
            "capture_output_path",
            *(
                ["native_result_projection", "pipeline_handle"]
                if operation in _PROFILER_ROW_READS
                else []
            ),
            "native_request",
        ]
    start = (
        {
            "subcommand": "core-call",
            "gateway_argv_prefix": ["core-call", operation],
        }
        if bounded_read
        else {
            "subcommand": "draft-start",
            "gateway_argv": ["draft-start", operation],
            "copy_exactly": True,
            "append_arguments": "forbidden",
        }
    )
    return {
        "contract": (
            RUNTIME_INSPECTION_BUSINESS_CONTRACT
            if bounded_read
            else RUNTIME_CONTROL_BUSINESS_CONTRACT
        ),
        "operation": operation,
        "version": version,
        "input_mode": "business_declaration",
        "execution_shape": execution_shape,
        "host_requirement": (
            "wwise-authoring"
            if operation.startswith("ak.wwise.core.remote.")
            or runtime_transport_requires_authoring(operation, version)
            else "wwise-console-or-authoring"
        ),
        "start": start,
        **({"result_delivery": {
            "mode": "immutable_bounded_observation",
            "page_size": "max_results is a presentation page size, not a total result limit",
            "continuation": "Copy agent_result.next_command exactly; pages read the retained observation without a new native call",
            "lifetime_seconds": 900,
            "large_rows": "Complete JSON row fragments with character offsets and reconstruction instructions",
            "pipeline_handles": "Gateway-issued capture-observation selectors; exact configuration, project, host, frozen time and identity are revalidated",
            "observation_boundary": "Capture rows are not instantaneous SoundEngine resource authority; identical externally replaced captures cannot be distinguished without a native capture generation",
            "resource_bounds": {"snapshot_bytes": 2 * 1024 * 1024, "total_storage_bytes": 16 * 1024 * 1024, "records": 128},
        }} if operation in _PROFILER_ROW_READS or operation == LOG_GET_URI else {}),
        "declaration": {
            "subcommand": (
                "core-call"
                if bounded_read
                else "draft-declare-runtime-control-plan"
            ),
            "required_fields": list(row["required_fields"]),
            "optional_fields": list(optional_fields),
            **capture_verification,
            "field_types": {
                name: value
                for name, value in row["field_types"].items()
                if name in exposed_fields
            } | ({name:detail['type'] for name,detail in meter_contract['fields'].items()} if meter_contract else {}),
            "input_forms": {
                name: {
                    **value,
                    **({"range": [0, 65535]} if operation == REMOTE_CONNECT_URI and name in {"command_port", "notification_port"} else {}),
                    **({"value_forms": {
                        "named": list(PROFILER_CURSOR_MEANINGS),
                        "integer_milliseconds": {"minimum": 0, "encoding": "ASCII decimal string", "maximum_input_bytes": 1024, "bound_owner": "Gateway request resource policy"},
                    }} if name == "profiler_position" else {}),
                }
                for name, value in row["input_forms"].items()
                if name in exposed_fields
            } | (meter_contract['fields'] if meter_contract else {}),
            **({'meter_object_projection':meter_contract} if meter_contract else {}),
            **({"field_semantics": {"capture_data_changes": {
                "preserve_rows_and_order": True,
                "missing_input": "required; use the explicit empty flag to submit zero rows",
                "empty_effect": "unspecified_by_native_documentation",
                "repeated_data_set_resolution": "unspecified_by_native_documentation",
                "native_legality_established_by_schema": False,
                "enable_default": "explicit enable represents the documented omitted-true native default",
            }}, "verification": dict(PROFILER_CAPTURE_DATA_VERIFICATION)} if operation == PROFILER_ENABLE_DATA_URI else {}),
            **({"field_semantics": {"cursor_target_ms": {
                "units": "signed integer milliseconds",
                "negative_value_meaning": "not_specified_by_native_documentation",
                "native_legality_established_by_schema": False,
                "native_snapping": "the returned time may differ from the requested time",
            }}, "verification": {
                "observer": PROFILER_GET_CURSOR_TIME_URI,
                "cursor": "user",
                "comparison": "returned_time_not_requested_time",
                "boundary": "One available user-cursor observation must match the returned snapped time; unavailable or changed observations do not verify the effect. Continuing position and capture completeness remain unverified.",
            }} if operation == PROFILER_SET_CURSOR_TIME_URI else {}),
            **({"field_semantics": {"audition_action": {
                "play": "play the selected scope; a later stopped state cannot disprove transient playback",
                "stop": "stop the selected scope; a stopped read is an observed postcondition, not proof of causality",
                "pause": "toggle pause/resume; a stopped target remains stopped",
                "toggle-play-stop": "toggle play/stop; a paused target becomes playing",
                "play-directly": "observe playing in the selected scope; restart position and acoustic output are unverified",
            }}, "verification": {
                "state_observer": "ak.wwise.core.transport.getState",
                "target_observer": "ak.wwise.core.transport.getList",
                "maximum_targets": 64,
                "scope": "Preview associations and toggle prestate are revalidated before execution; all-active binds the bounded target list",
                "boundary": "One later state observation per target; no continuous playback, causal or atomic snapshot guarantee. Missing transient play remains unverified; state does not establish acoustic output, restart position or prior global audition-mode restoration.",
            }} if operation == TRANSPORT_EXECUTE_ACTION_URI else {}),
            **({"verification": {
                "observer": LOG_GET_URI,
                "maximum_channel_items": 1000,
                "maximum_channel_bytes": 64 * 1024,
                "prestate": "complete selected channel at Preview, revalidated before execution; drift requires a new Preview",
                "row_identity": "none; messageId and time are not treated as unique or ordered",
                "add_effect": "matching message/severity multiplicity increases from prestate",
                "clear_effect": "prior complete row contents absent at one observation; new messages can remain",
                "unresolved": "oversized, unchanged matching multiplicity, indistinguishable prior rows, or unavailable readback never prove effect",
                "console_effect": "getter is documented empty; add uses a bounded execute-time addition event; clear effect remains unverified",
                "console_add_observer": dict(CONSOLE_LOG_ADD_OBSERVER),
                "console_clear_boundary": "Acknowledgment only: the Console getter is empty and the addition-only Topic cannot prove prior contents disappeared.",
                "concurrency": "no exclusive causation, atomic clear, permanent emptiness or unrelated-channel observation claim",
            }} if operation in {LOG_ADD_ITEM_URI, LOG_CLEAR_URI} else {}),
            **({"field_semantics": {
                "notification_port": {
                    "native_effect": "paired_notification_port" if version == "2021.1" else "unused",
                    "selector_used_by_native": version == "2021.1",
                    "target_identity_evidence": False,
                    "requirement": "paired with command_port and application_name" if version == "2021.1" else "accepted and preserved; no target or notification effect is promised",
                },
                "remote_host": {"identity": "exact native console.host observation; no DNS, computer-name or IP alias inference"},
                "command_port": {"identity": "fresh discovery descriptors provide corroboration only; connected status exposes neither port nor a proven process-unique key"},
            }, "verification": {
                "status_observer": "ak.wwise.core.remote.getConnectionStatus",
                "port_observer": "ak.wwise.core.remote.getAvailableConsoles",
                "maximum_discovered_consoles": 256,
                "port_effect": "unknown even for one matching discovery row; never infer connected-instance identity or claim complete port verification",
                "unresolved_identity": "partial_remote_target_observation; never full business verification",
            }} if operation == REMOTE_CONNECT_URI else {}),
            **({"value_choices": value_choices} if value_choices else {}),
            **({"result_view_meanings": {
                "summary": "Curated capture-frame names and measurements",
                "identity": "Capture-frame object and instance identities",
                "diagnostics": "Every field in this version's reflected projection definition",
                "capture-defaults": "Use Wwise's default projection by omitting field selection",
                "empty-selection": "Submit an explicit empty field selection",
            }} if "result_view" in exposed_fields else {}),
            **({"result_fields_meaning": {
                "selection": "Repeat one disclosed field choice per flag; preserve requested order and repetitions",
                "projection": "Only requested fields actually reported by Wwise; missing fields remain omitted and no identity fields are appended",
                "instance_handles": "Issued only when the native observation reports the complete valid instance identity basis",
                "no_selection": "Omitting both selection forms retains the summary preset; capture-defaults omits selection and empty-selection submits an empty list",
            }} if "result_fields" in exposed_fields else {}),
        },
        **(
            {}
            if bounded_read
            else {
                "binding": {
                    "available": bool(roles),
                    "roles": list(roles),
                    "role_fields": [
                        {
                            "role": role,
                            "field": role_field[role],
                            "cardinality": "exactly_one",
                        }
                        for role in roles
                    ],
                    "role_required": bool(roles),
                    "identity": "live_bound_object_handle" if roles else "none",
                    "validation": "exact_guid_name_type_path" if roles else "none",
                }
            }
        ),
        "gateway_derivations": [
            *derivations,
            "result_projection",
            "result_bound",
            *([] if bounded_read else ["preview", "authorization", "verification"]),
            "continuation",
        ],
        "legacy_typed_call_public": False,
        **(
            {}
            if bounded_read
            else {
                "safety": {
                    "preview": "immutable_before_execution",
                    "authorization": "normal_transaction_policy",
                    "automatic_retry": False,
                    "lifecycle_cleanup": "packaged_when_operation_has_companion",
                    "native_request_input": "forbidden",
                }
            }
        ),
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
    "PROFILER_MOVE_CURSOR_URI",
    "PROFILER_SET_CURSOR_TIME_URI",
    "RUNTIME_CONTROL_BUSINESS_CONTRACT",
    "TRANSPORT_GET_STATE_URI",
    "RUNTIME_INSPECTION_BUSINESS_CONTRACT",
    "runtime_inspection_business_catalog_rows",
    "runtime_inspection_business_contract_data",
    "runtime_inspection_business_operations",
    "runtime_inspection_business_read_operations",
    "runtime_control_business_operations",
    "runtime_inspection_business_versions",
]
