"""Compile and project closed Core runtime-inspection business reads."""

from __future__ import annotations

import re
from typing import Any, Mapping

from .business_declaration_state import BusinessDeclarationSession
from .business_declarations import business_repair
from .host_paths import HostPathError, parse_absolute_host_path, parse_relative_host_path
from .operation_registry import parse_operation_request
from .runtime_inspection_business_contracts import (
    LOG_GET_URI,
    LOG_ADD_ITEM_URI,
    LOG_CLEAR_URI,
    PROFILER_CAPTURE_DATA_CHOICES,
    PROFILER_ENABLE_DATA_URI,
    PROFILER_GET_AUDIO_OBJECTS_URI,
    PROFILER_GET_BUSSES_URI,
    PROFILER_GET_CURSOR_TIME_URI,
    PROFILER_GET_VOICES_URI,
    PROFILER_MOVE_CURSOR_URI,
    PROFILER_REGISTER_METER_URI,
    PROFILER_SAVE_CAPTURE_URI,
    PROFILER_SET_CURSOR_TIME_URI,
    PROFILER_UNREGISTER_METER_URI,
    REMOTE_CONNECT_URI,
    TRANSPORT_CREATE_URI,
    TRANSPORT_DESTROY_URI,
    TRANSPORT_EXECUTE_ACTION_URI,
    TRANSPORT_GET_STATE_URI,
    TRANSPORT_PREPARE_URI,
    TRANSPORT_USE_ORIGINALS_URI,
    runtime_inspection_business_contract_data,
)


class RuntimeInspectionBusinessError(ValueError):
    pass


_BASE_LOG_CHANNELS = {
    "soundbank-generation": "soundbankGenerate",
    "audio-conversion": "conversion",
    "platform-settings-copy": "copyPlatformSettings",
    "waapi": "waapi",
    "project-load": "projectLoad",
    "general": "general",
}
_LATER_LOG_CHANNELS = {
    **_BASE_LOG_CHANNELS,
    "source-control": "sourceControl",
    "lua": "lua",
}
_PROFILER_CURSORS = {
    "capture-latest": "capture",
    "user-cursor": "user",
}
_PROFILER_BUS_HANDLE = re.compile(r"^bus-instance-([0-9a-f]{8})$")
_PROFILER_VOICE_HANDLE = re.compile(r"^voice-instance-([0-9a-f]{8})$")
_TRANSPORT_HANDLE = re.compile(r"^transport-session-([0-9a-f]{8})$")
_CURSOR_MOVES = {
    "first-frame": "first",
    "last-frame": "last",
    "next-frame": "next",
    "previous-frame": "previous",
}
_LOG_SEVERITIES = {
    "message": "Message",
    "warning": "Warning",
    "error": "Error",
    "fatal": "Fatal Error",
}
_AUDITION_ACTIONS = {
    "play": "play",
    "stop": "stop",
    "pause": "pause",
    "toggle-play-stop": "playStop",
    "play-directly": "playDirectly",
}
_CAPTURE_DATA_NATIVE_BASE = {
    "api-calls": "apiCalls",
    "audio-objects": "audioObjects",
    "auxiliary-sends": "auxiliarySends",
    "cpu": "cpu",
    "customer-support-data": "customerSupportData",
    "interactive-music": "interactiveMusic",
    "listeners": "listener",
    "loaded-media": "loadedMedia",
    "markers": "markersNotification",
    "memory": "memory",
    "meters": "meter",
    "music-transitions": "musicTransitions",
    "obstruction-occlusion": "obstructionOcclusion",
    "output": "output",
    "prepared-events": "preparedEvents",
    "prepared-game-syncs": "preparedGameSyncs",
    "prepared-objects": "preparedObjects",
    "spatial-audio": "spatialAudio",
    "spatial-audio-raycasting": "spatialAudioRaycasting",
    "streaming": "stream",
    "streaming-device": "streamingDevice",
    "voice-inspector": "voiceInspector",
    "voices": "voices",
}


def _capture_data_native(version: str, value: str) -> str:
    if value == "soundbanks":
        return "soundBanks" if version in {"2021.1", "2022.1"} else "soundbanks"
    if value == "inactive-game-syncs":
        return "inactiveGameSyncs"
    if value == "game-syncs":
        return "gameSyncs"
    return _CAPTURE_DATA_NATIVE_BASE[value]


def _required_text(value: Any, *, field: str, maximum_bytes: int = 1024) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > maximum_bytes
        or "\x00" in value
    ):
        raise business_repair(
            "BUSINESS_VALUE_INVALID",
            field=field,
            action=f"provide one nonempty exact value up to {maximum_bytes} UTF-8 bytes",
        )
    return value


def _bound_role(
    session: BusinessDeclarationSession,
    value: Any,
    *,
    field: str,
    role: str,
    allowed_types: frozenset[str] | None = None,
) -> Any:
    if not isinstance(value, str):
        raise business_repair(
            "REQUIRED_FIELD_MISSING",
            field=field,
            action=f"bind the exact {role} and copy its returned handle",
        )
    bound = session.handles.resolve_object(value)
    if bound.role != role or (
        allowed_types is not None and bound.object_type not in allowed_types
    ):
        raise business_repair(
            "BOUND_OBJECT_ROLE_MISMATCH",
            field=field,
            expected_role=role,
            allowed_types=sorted(allowed_types) if allowed_types is not None else None,
            actual_role=bound.role,
            actual_type=bound.object_type,
            action=f"copy the handle returned for the {role} role",
        )
    return bound


def _port(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise business_repair(
            "BUSINESS_VALUE_INVALID",
            field=field,
            action="provide an integer TCP port from 1 to 65535",
        )
    return value
_PROFILER_RETURN_VIEWS = {
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


def _result_limit(max_results: int | None) -> int:
    limit = 100 if max_results is None else max_results
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise RuntimeInspectionBusinessError(
            "max_results must be an integer from 1 to 1000"
        )
    return limit


def _profiler_time(value: str | None) -> str | int:
    if value in _PROFILER_CURSORS:
        return _PROFILER_CURSORS[str(value)]
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        milliseconds = int(value)
        if milliseconds <= 2_147_483_647:
            return milliseconds
    raise RuntimeInspectionBusinessError(
        "profiler_position must be capture-latest, user-cursor, or non-negative "
        "integer milliseconds up to 2147483647"
    )


def _pipeline_id(value: str | None, *, kind: str) -> int | None:
    if value is None:
        return None
    pattern = _PROFILER_BUS_HANDLE if kind == "bus" else _PROFILER_VOICE_HANDLE
    match = pattern.fullmatch(value)
    if match is None:
        raise RuntimeInspectionBusinessError(
            f"{kind}_instance_handle must be copied exactly from a Gateway Profiler result"
        )
    pipeline_id = int(match.group(1), 16)
    if pipeline_id == 0:
        raise RuntimeInspectionBusinessError(
            f"{kind}_instance_handle must identify a non-zero live instance"
        )
    return pipeline_id


def profiler_pipeline_id_from_handle(value: str, *, kind: str) -> int:
    if kind not in {"bus", "voice"}:
        raise ValueError("Profiler pipeline handle kind must be bus or voice")
    pipeline_id = _pipeline_id(value, kind=kind)
    assert pipeline_id is not None
    return pipeline_id


def _pipeline_handle(value: Any, *, kind: str) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 0xFFFFFFFF:
        return None
    return f"{kind}-instance-{value:08x}"


def _transport_id(value: str | None) -> int:
    match = _TRANSPORT_HANDLE.fullmatch(value or "")
    if match is None:
        raise RuntimeInspectionBusinessError(
            "transport_handle must be copied exactly from a Gateway transport result"
        )
    transport_id = int(match.group(1), 16)
    if transport_id == 0:
        raise RuntimeInspectionBusinessError(
            "transport_handle must identify a non-zero live transport"
        )
    return transport_id


def materialize_runtime_inspection_business_request(
    operation: str,
    version: str,
    *,
    log_channel: str | None,
    max_results: int | None,
    profiler_position: str | None = None,
    profiler_cursor: str | None = None,
    result_view: str | None = None,
    bus_instance_handle: str | None = None,
    voice_instance_handle: str | None = None,
    transport_handle: str | None = None,
) -> tuple[dict[str, Any], int, dict[str, Any]]:
    limit = _result_limit(max_results)
    if operation == LOG_GET_URI:
        if any(
            value is not None
            for value in (
                profiler_position,
                profiler_cursor,
                result_view,
                bus_instance_handle,
                voice_instance_handle,
                transport_handle,
            )
        ):
            raise RuntimeInspectionBusinessError(
                "log.get accepts only log_channel and max_results"
            )
        channels = (
            _BASE_LOG_CHANNELS
            if version in {"2021.1", "2022.1"}
            else _LATER_LOG_CHANNELS
        )
        native_channel = channels.get(log_channel or "")
        if native_channel is None:
            raise RuntimeInspectionBusinessError(
                "log_channel must be one available Wwise log view: "
                + ", ".join(sorted(channels))
            )
        return (
            {"api": operation, "args": {"channel": native_channel}, "options": {}},
            limit,
            {"log_channel": str(log_channel)},
        )
    if operation == PROFILER_GET_CURSOR_TIME_URI:
        if any(
            value is not None
            for value in (
                log_channel,
                max_results,
                profiler_position,
                result_view,
                bus_instance_handle,
                voice_instance_handle,
                transport_handle,
            )
        ):
            raise RuntimeInspectionBusinessError(
                "getCursorTime accepts only profiler_cursor"
            )
        native_cursor = _PROFILER_CURSORS.get(profiler_cursor or "")
        if native_cursor is None:
            raise RuntimeInspectionBusinessError(
                "profiler_cursor must be capture-latest or user-cursor"
            )
        return (
            {"api": operation, "args": {"cursor": native_cursor}, "options": {}},
            1,
            {"profiler_cursor": str(profiler_cursor)},
        )
    if operation == TRANSPORT_GET_STATE_URI:
        if any(
            value is not None
            for value in (
                log_channel,
                max_results,
                profiler_position,
                profiler_cursor,
                result_view,
                bus_instance_handle,
                voice_instance_handle,
            )
        ):
            raise RuntimeInspectionBusinessError(
                "transport.getState accepts only transport_handle"
            )
        return (
            {
                "api": operation,
                "args": {"transport": _transport_id(transport_handle)},
                "options": {},
            },
            1,
            {"transport_handle": str(transport_handle)},
        )
    native_time = _profiler_time(profiler_position)
    if log_channel is not None or profiler_cursor is not None:
        raise RuntimeInspectionBusinessError(
            "Profiler row reads do not accept log_channel or profiler_cursor"
        )
    if transport_handle is not None:
        raise RuntimeInspectionBusinessError(
            "Profiler reads do not accept transport_handle"
        )
    args: dict[str, Any] = {"time": native_time}
    options: dict[str, Any] = {}
    if operation in _PROFILER_RETURN_VIEWS:
        view = "summary" if result_view is None else result_view
        projection = _PROFILER_RETURN_VIEWS[operation].get(view)
        if projection is None:
            raise RuntimeInspectionBusinessError(
                "result_view must be summary, identity, or diagnostics"
            )
        options["return"] = list(projection)
    elif result_view is not None:
        raise RuntimeInspectionBusinessError(
            "result_view is not accepted by this fixed-shape Profiler read"
        )
    if operation in {PROFILER_GET_AUDIO_OBJECTS_URI, PROFILER_GET_BUSSES_URI}:
        bus_pipeline_id = _pipeline_id(bus_instance_handle, kind="bus")
        if bus_pipeline_id is not None:
            args["busPipelineID"] = bus_pipeline_id
    elif bus_instance_handle is not None:
        raise RuntimeInspectionBusinessError(
            "bus_instance_handle is not accepted by this Profiler read"
        )
    if operation == PROFILER_GET_VOICES_URI:
        voice_pipeline_id = _pipeline_id(voice_instance_handle, kind="voice")
        if voice_pipeline_id is not None:
            args["voicePipelineID"] = voice_pipeline_id
    elif voice_instance_handle is not None:
        raise RuntimeInspectionBusinessError(
            "voice_instance_handle is not accepted by this Profiler read"
        )
    return (
        {"api": operation, "args": args, "options": options},
        limit,
        {
            "profiler_position": str(profiler_position),
            **({"result_view": "summary" if result_view is None else result_view} if operation in _PROFILER_RETURN_VIEWS else {}),
            **({"bus_instance_handle": bus_instance_handle} if bus_instance_handle is not None else {}),
            **({"voice_instance_handle": voice_instance_handle} if voice_instance_handle is not None else {}),
        },
    )


def normalize_runtime_inspection_result(
    operation: str,
    result: Any,
    *,
    business_request: Mapping[str, Any],
    max_results: int,
) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise RuntimeInspectionBusinessError("runtime inspection result is malformed")
    if operation == PROFILER_GET_CURSOR_TIME_URI:
        position = result.get("return")
        if position == -1:
            return {
                "profiler_cursor": business_request["profiler_cursor"],
                "available": False,
                "position_ms": None,
            }
        if isinstance(position, bool) or not isinstance(position, int) or position < 0:
            raise RuntimeInspectionBusinessError(
                "Profiler cursor result must contain -1 or non-negative integer milliseconds"
            )
        return {
            "profiler_cursor": business_request["profiler_cursor"],
            "available": True,
            "position_ms": position,
        }
    if operation == TRANSPORT_GET_STATE_URI:
        state = result.get("state")
        if state not in {"playing", "stopped", "paused"}:
            raise RuntimeInspectionBusinessError(
                "transport result must contain playing, stopped, or paused state"
            )
        return {
            "transport_handle": business_request["transport_handle"],
            "state": state,
        }
    source_field = "items" if operation == LOG_GET_URI else (
        "meters" if operation.endswith(".getMeters") else "return"
    )
    rows = result.get(source_field)
    if not isinstance(rows, list) or any(not isinstance(item, Mapping) for item in rows):
        raise RuntimeInspectionBusinessError(
            f"runtime inspection result must contain a {source_field} array"
        )
    selected = [dict(item) for item in rows[-max_results:]]
    if operation in {PROFILER_GET_BUSSES_URI, PROFILER_GET_AUDIO_OBJECTS_URI}:
        native_field = "pipelineID" if operation == PROFILER_GET_BUSSES_URI else "busPipelineID"
        for item in selected:
            handle = _pipeline_handle(item.get(native_field), kind="bus")
            if handle is not None:
                item["bus_instance_handle"] = handle
            if business_request.get("result_view") != "diagnostics":
                item.pop(native_field, None)
    if operation == PROFILER_GET_VOICES_URI:
        for item in selected:
            handle = _pipeline_handle(item.get("pipelineID"), kind="voice")
            if handle is not None:
                item["voice_instance_handle"] = handle
            if business_request.get("result_view") != "diagnostics":
                item.pop("pipelineID", None)
    return {
        **(
            {"channel": business_request["log_channel"]}
            if operation == LOG_GET_URI
            else {"profiler_position": business_request["profiler_position"]}
        ),
        source_field: selected,
        "returned_count": len(selected),
        "truncated": len(rows) > len(selected),
    }


def materialize_runtime_control_business_request(
    operation: str,
    session: BusinessDeclarationSession,
) -> dict[str, Any]:
    if not isinstance(session, BusinessDeclarationSession):
        raise TypeError("session must be BusinessDeclarationSession")
    runtime_inspection_business_contract_data(
        operation,
        session.context.wwise_version,
    )
    if set(session.settings) != {"runtime_control_plan"}:
        raise business_repair(
            "RUNTIME_CONTROL_PLAN_INCOMPLETE",
            field="runtime_control_plan",
            action="submit the one complete Gateway-disclosed runtime control plan",
        )
    plan = session.settings["runtime_control_plan"]
    if not isinstance(plan, Mapping):
        raise business_repair(
            "RUNTIME_CONTROL_PLAN_INVALID",
            field="runtime_control_plan",
            action="submit one closed runtime control plan",
        )
    version = session.context.wwise_version
    io_root: str | None = None

    def require_fields(required: set[str], optional: set[str] | None = None) -> None:
        allowed = required | (optional or set())
        if not required <= set(plan) or set(plan) - allowed:
            raise business_repair(
                "RUNTIME_CONTROL_PLAN_FIELDS_INVALID",
                field="runtime_control_plan",
                required=sorted(required),
                optional=sorted(optional or set()),
                action="submit exactly the fields disclosed for this runtime control",
            )

    if operation == PROFILER_MOVE_CURSOR_URI:
        require_fields({"cursor_move"})
        native_move = _CURSOR_MOVES.get(plan.get("cursor_move"))
        if native_move is None:
            raise business_repair(
                "BUSINESS_ENUM_INVALID",
                field="cursor_move",
                choices=sorted(_CURSOR_MOVES),
                action="choose one disclosed Profiler frame move",
            )
        args = {"position": native_move}
    elif operation == PROFILER_SET_CURSOR_TIME_URI:
        require_fields({"cursor_target_ms"})
        target = plan.get("cursor_target_ms")
        if (
            isinstance(target, bool)
            or not isinstance(target, int)
            or not 0 <= target <= 2_147_483_647
        ):
            raise business_repair(
                "BUSINESS_VALUE_INVALID",
                field="cursor_target_ms",
                action="provide non-negative integer milliseconds up to 2147483647",
            )
        args = {"time": target}
    elif operation == PROFILER_ENABLE_DATA_URI:
        require_fields({"capture_data_changes"})
        capture_data = plan.get("capture_data_changes")
        if (
            not isinstance(capture_data, list)
            or not capture_data
            or any(
                not isinstance(value, list)
                or len(value) != 2
                or not all(isinstance(item, str) for item in value)
                for value in capture_data
            )
            or len({value[0] for value in capture_data}) != len(capture_data)
            or any(
                value[0] not in PROFILER_CAPTURE_DATA_CHOICES[version]
                or value[1] not in {"enable", "disable"}
                for value in capture_data
            )
        ):
            raise business_repair(
                "BUSINESS_ENUM_INVALID",
                field="capture_data_changes",
                choices=list(PROFILER_CAPTURE_DATA_CHOICES[version]),
                outcomes=["enable", "disable"],
                action="choose distinct available data sets and each desired enablement outcome",
            )
        args = {
            "dataTypes": [
                {
                    "dataType": _capture_data_native(version, value[0]),
                    "enable": value[1] == "enable",
                }
                for value in capture_data
            ]
        }
    elif operation == LOG_ADD_ITEM_URI:
        require_fields({"message"}, {"log_channel", "severity"})
        message = _required_text(
            plan.get("message"),
            field="message",
            maximum_bytes=16 * 1024,
        )
        channel = plan.get("log_channel", "general")
        native_channel = _LATER_LOG_CHANNELS.get(channel)
        severity = _LOG_SEVERITIES.get(plan.get("severity", "message"))
        if native_channel is None:
            raise business_repair(
                "BUSINESS_ENUM_INVALID",
                field="log_channel",
                choices=sorted(_LATER_LOG_CHANNELS),
                action="choose one disclosed Wwise log view",
            )
        if severity is None:
            raise business_repair(
                "BUSINESS_ENUM_INVALID",
                field="severity",
                choices=sorted(_LOG_SEVERITIES),
                action="choose one disclosed log severity",
            )
        args = {"message": message, "channel": native_channel, "severity": severity}
    elif operation == LOG_CLEAR_URI:
        require_fields({"log_channel"})
        native_channel = _LATER_LOG_CHANNELS.get(plan.get("log_channel"))
        if native_channel is None:
            raise business_repair(
                "BUSINESS_ENUM_INVALID",
                field="log_channel",
                choices=sorted(_LATER_LOG_CHANNELS),
                action="choose the exact log view to clear",
            )
        args = {"channel": native_channel}
    elif operation == REMOTE_CONNECT_URI:
        allowed_optional = {"application_name", "command_port"}
        if version == "2021.1":
            allowed_optional.add("notification_port")
        require_fields({"remote_host"}, allowed_optional)
        args = {
            "host": _required_text(plan.get("remote_host"), field="remote_host")
        }
        app_name = plan.get("application_name")
        command_port = plan.get("command_port")
        notification_port = plan.get("notification_port")
        if app_name is not None:
            args["appName"] = _required_text(
                app_name,
                field="application_name",
            )
        if command_port is not None:
            if app_name is None:
                raise business_repair(
                    "REMOTE_TARGET_INCOMPLETE",
                    field="application_name",
                    action="provide application_name whenever command_port is selected",
                )
            args["commandPort"] = _port(command_port, field="command_port")
        if version == "2021.1":
            if (command_port is None) != (notification_port is None):
                raise business_repair(
                    "REMOTE_TARGET_INCOMPLETE",
                    field="notification_port",
                    action="provide both command_port and notification_port or omit both",
                )
            if notification_port is not None:
                args["notificationPort"] = _port(
                    notification_port,
                    field="notification_port",
                )
    elif operation in {TRANSPORT_CREATE_URI, TRANSPORT_PREPARE_URI}:
        optional = {"game_object_id"} if operation == TRANSPORT_CREATE_URI else set()
        require_fields({"target_handle"}, optional)
        target = _bound_role(
            session,
            plan.get("target_handle"),
            field="target_handle",
            role="target",
        )
        args = {"object": target.object_id}
        if "game_object_id" in plan:
            game_object_id = plan["game_object_id"]
            if (
                isinstance(game_object_id, bool)
                or not isinstance(game_object_id, int)
                or not 0 <= game_object_id <= 0xFFFFFFFFFFFFFFFF
            ):
                raise business_repair(
                    "BUSINESS_VALUE_INVALID",
                    field="game_object_id",
                    action="provide one unsigned 64-bit runtime Game Object ID",
                )
            args["gameObject"] = game_object_id
    elif operation == TRANSPORT_DESTROY_URI:
        require_fields({"transport_handle"})
        args = {"transport": _transport_id(plan.get("transport_handle"))}
    elif operation == TRANSPORT_EXECUTE_ACTION_URI:
        require_fields(
            {"audition_action", "transport_scope"},
            {"transport_handle"},
        )
        action = _AUDITION_ACTIONS.get(plan.get("audition_action"))
        if action is None:
            raise business_repair(
                "BUSINESS_ENUM_INVALID",
                field="audition_action",
                choices=sorted(_AUDITION_ACTIONS),
                action="choose one disclosed Authoring audition action",
            )
        scope = plan.get("transport_scope")
        args = {"action": action}
        if scope == "one-transport":
            args["transport"] = _transport_id(plan.get("transport_handle"))
        elif scope == "all-active":
            if "transport_handle" in plan:
                raise business_repair(
                    "BUSINESS_VALUE_CONFLICT",
                    field="transport_handle",
                    action="omit transport_handle for all-active scope",
                )
        else:
            raise business_repair(
                "BUSINESS_ENUM_INVALID",
                field="transport_scope",
                choices=["all-active", "one-transport"],
                action="choose one transport or all active transports",
            )
    elif operation == TRANSPORT_USE_ORIGINALS_URI:
        require_fields({"audition_media"})
        media = plan.get("audition_media")
        if media not in {"originals", "converted"}:
            raise business_repair(
                "BUSINESS_ENUM_INVALID",
                field="audition_media",
                choices=["converted", "originals"],
                action="choose the media used for Authoring audition",
            )
        args = {"enable": media == "originals"}
    elif operation in {PROFILER_REGISTER_METER_URI, PROFILER_UNREGISTER_METER_URI}:
        require_fields({"meter_object_handle"})
        meter_object = _bound_role(
            session,
            plan.get("meter_object_handle"),
            field="meter_object_handle",
            role="meter_object",
            allowed_types=frozenset({"Bus", "AuxBus", "AudioDevice"}),
        )
        args = {"object": meter_object.object_id}
    elif operation == PROFILER_SAVE_CAPTURE_URI:
        require_fields({"capture_output_directory", "capture_name"})
        try:
            directory = parse_absolute_host_path(
                plan.get("capture_output_directory"),
                allow_trailing_separator=True,
            )
        except HostPathError as exc:
            raise business_repair(
                exc.error_code,
                field="capture_output_directory_or_name",
                action="provide one exact absolute output directory and one portable file name",
            ) from exc
        raw_name = plan.get("capture_name")
        if directory.flavor == "posix":
            if (
                not isinstance(raw_name, str)
                or not raw_name
                or raw_name != raw_name.strip()
                or raw_name in {".", ".."}
                or "/" in raw_name
                or "\x00" in raw_name
            ):
                raise business_repair(
                    "INVALID_HOST_PATH",
                    field="capture_name",
                    action="provide one exact POSIX file name without a slash",
                )
            file_name = raw_name
        else:
            try:
                capture_name = parse_relative_host_path(raw_name)
            except HostPathError as exc:
                raise business_repair(
                    exc.error_code,
                    field="capture_name",
                    action="provide one valid Windows file name without directories",
                ) from exc
            if len(capture_name.components) != 1:
                raise business_repair(
                    "INVALID_HOST_PATH",
                    field="capture_name",
                    action="provide one file name without directory separators",
                )
            file_name = capture_name.components[0]
        if not file_name.casefold().endswith(".prof"):
            file_name += ".prof"
        io_root = str(directory.pure_path)
        args = {"file": str(directory.pure_path / file_name)}
    else:  # pragma: no cover - contract registry invariant
        raise ValueError("unsupported runtime control operation")
    return parse_operation_request(
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": session.context.wwise_version,
            "operation": "waapi.call",
            "arguments": {
                "api": operation,
                "args": args,
                "options": {},
                **({"io_root": io_root} if io_root is not None else {}),
            },
        },
        expected_version=session.context.wwise_version,
    ).as_dict()


__all__ = [
    "RuntimeInspectionBusinessError",
    "materialize_runtime_inspection_business_request",
    "materialize_runtime_control_business_request",
    "normalize_runtime_inspection_result",
    "profiler_pipeline_id_from_handle",
]
