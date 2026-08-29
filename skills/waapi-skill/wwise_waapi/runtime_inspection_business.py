"""Compile and project closed Core runtime-inspection business reads."""

from __future__ import annotations

import re
from typing import Any, Mapping

from .runtime_inspection_business_contracts import (
    LOG_GET_URI,
    PROFILER_GET_AUDIO_OBJECTS_URI,
    PROFILER_GET_BUSSES_URI,
    PROFILER_GET_CURSOR_TIME_URI,
    PROFILER_GET_VOICES_URI,
    TRANSPORT_GET_STATE_URI,
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
        if isinstance(position, bool) or not isinstance(position, int) or position < 0:
            raise RuntimeInspectionBusinessError(
                "Profiler cursor result must contain non-negative integer milliseconds"
            )
        return {
            "profiler_cursor": business_request["profiler_cursor"],
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
    if operation == PROFILER_GET_VOICES_URI:
        for item in selected:
            handle = _pipeline_handle(item.get("pipelineID"), kind="voice")
            if handle is not None:
                item["voice_instance_handle"] = handle
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


__all__ = [
    "RuntimeInspectionBusinessError",
    "materialize_runtime_inspection_business_request",
    "normalize_runtime_inspection_result",
]
