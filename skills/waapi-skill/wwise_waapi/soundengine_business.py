"""Compile closed SoundEngine business declarations into native requests."""

from __future__ import annotations

from math import isfinite
from typing import Any, Mapping

from .business_declaration_state import BusinessDeclarationSession
from .business_declarations import business_repair
from .canonical import canonical_sha256
from .operation_registry import parse_operation_request
from .soundengine_business_contracts import (
    EXECUTE_ACTION_ON_EVENT_URI,
    LOAD_BANK_URI,
    POST_MONITOR_MESSAGE_URI,
    POST_EVENT_URI,
    POST_TRIGGER_URI,
    REGISTER_GAME_OBJECT_URI,
    RESET_GAME_PARAMETER_URI,
    SEEK_ON_EVENT_URI,
    SET_DEFAULT_LISTENERS_URI,
    SET_AUX_SENDS_URI,
    SET_GAME_PARAMETER_URI,
    SET_LISTENERS_URI,
    SET_LISTENER_SPATIALIZATION_URI,
    SET_MULTIPLE_POSITIONS_URI,
    SET_OBSTRUCTION_OCCLUSION_URI,
    SET_OUTPUT_BUS_VOLUME_URI,
    SET_POSITION_URI,
    SET_SCALING_FACTOR_URI,
    SET_STATE_URI,
    SET_SWITCH_URI,
    STOP_ALL_URI,
    STOP_PLAYING_ID_URI,
    UNLOAD_BANK_URI,
    UNREGISTER_GAME_OBJECT_URI,
    soundengine_control_business_contract_data,
)


_FADE_CURVES = {
    "Log3": 0,
    "Sine": 1,
    "Log1": 2,
    "InvSCurve": 3,
    "Linear": 4,
    "SCurve": 5,
    "Exp1": 6,
    "SineRecip": 7,
    "Exp3": 8,
}
_EVENT_ACTIONS = {
    "Stop": 0,
    "Pause": 1,
    "Resume": 2,
    "Break": 3,
    "ReleaseEnvelope": 4,
}
_INVALID_GAME_OBJECT = 0xFFFFFFFFFFFFFFFF
_INVALID_PLAYING_ID = 0
_MULTI_POSITION_MODES = {
    "SingleSource": 0,
    "MultiSources": 1,
    "MultiDirections": 2,
}
_SPEAKER_MASKS = {
    "FL": 0x1,
    "FR": 0x2,
    "C": 0x4,
    "LFE": 0x8,
    "BL": 0x10,
    "BR": 0x20,
    "BC": 0x100,
    "SL": 0x200,
    "SR": 0x400,
    "TOP": 0x800,
    "HFL": 0x1000,
    "HFC": 0x2000,
    "HFR": 0x4000,
    "HBL": 0x8000,
    "HBC": 0x10000,
    "HBR": 0x20000,
    "HSL": 0x40000,
    "HSR": 0x80000,
}
_STANDARD_CHANNEL_LAYOUTS = {
    "1.0": ("C",),
    "1.1": ("C", "LFE"),
    "2.0": ("FL", "FR"),
    "2.1": ("FL", "FR", "LFE"),
    "3.0": ("FL", "FR", "C"),
    "3.1": ("FL", "FR", "C", "LFE"),
    "4.0": ("FL", "FR", "SL", "SR"),
    "4.1": ("FL", "FR", "SL", "SR", "LFE"),
    "5.0": ("FL", "FR", "C", "SL", "SR"),
    "5.1": ("FL", "FR", "C", "SL", "SR", "LFE"),
    "6.0": ("FL", "FR", "BL", "BR", "SL", "SR"),
    "6.1": ("FL", "FR", "BL", "BR", "SL", "SR", "LFE"),
    "7.0": ("FL", "FR", "C", "BL", "BR", "SL", "SR"),
    "7.1": ("FL", "FR", "C", "BL", "BR", "SL", "SR", "LFE"),
}
_AMBISONIC_CHANNEL_COUNTS = frozenset((1, 4, 9, 16, 25, 36))
_HEIGHT_SIDE_SPEAKER_VERSIONS = frozenset(("2024.1", "2025.1"))


def _runtime_game_object_id(
    bindings: object,
    handle: object,
    *,
    field: str,
) -> int:
    if not isinstance(handle, str) or not isinstance(bindings, Mapping):
        raise business_repair(
            "GAME_OBJECT_HANDLE_INVALID",
            field=field,
            action="copy one active game object handle from a Gateway result",
        )
    record = bindings.get(handle)
    game_object_id = record.get("game_object_id") if isinstance(record, Mapping) else None
    if (
        isinstance(game_object_id, bool)
        or not isinstance(game_object_id, int)
        or not 0 <= game_object_id <= 0xFFFFFFFFFFFFFFDF
    ):
        raise business_repair(
            "GAME_OBJECT_HANDLE_INVALID",
            field=field,
            action="bind the active game object handle again",
        )
    return game_object_id


def _position_frame(values: object) -> dict[str, dict[str, float]]:
    if (
        not isinstance(values, list)
        or len(values) != 9
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(value)
            for value in values
        )
    ):
        raise business_repair(
            "POSITION_FRAME_INVALID",
            field="position_frame",
            action="provide nine finite numbers in position, front, top order",
        )
    numbers = [float(value) for value in values]
    front = numbers[3:6]
    top = numbers[6:9]
    cross = (
        front[1] * top[2] - front[2] * top[1],
        front[2] * top[0] - front[0] * top[2],
        front[0] * top[1] - front[1] * top[0],
    )
    if (
        sum(value * value for value in front) <= 1e-12
        or sum(value * value for value in top) <= 1e-12
        or sum(value * value for value in cross) <= 1e-12
    ):
        raise business_repair(
            "POSITION_ORIENTATION_INVALID",
            field="position_frame",
            action="provide nonzero, nonparallel front and top orientation vectors",
        )
    return {
        "position": {"x": numbers[0], "y": numbers[1], "z": numbers[2]},
        "orientationFront": {"x": front[0], "y": front[1], "z": front[2]},
        "orientationTop": {"x": top[0], "y": top[1], "z": top[2]},
    }


def _finite_decibels(
    value: object,
    *,
    error_code: str,
    field: str,
    action: str,
) -> float:
    try:
        decibels = float(value)
    except (TypeError, ValueError) as exc:
        raise business_repair(
            error_code,
            field=field,
            action=action,
        ) from exc
    if not isfinite(decibels) or not -200 <= decibels <= 200:
        raise business_repair(
            error_code,
            field=field,
            action=action,
        )
    return decibels


def _compile_named_offsets(
    raw_offsets: object,
    *,
    speakers: tuple[str, ...],
) -> list[float]:
    if not isinstance(raw_offsets, list) or len(raw_offsets) > len(speakers):
        raise business_repair(
            "SPEAKER_OFFSET_LIST_INVALID",
            field="speaker_offsets_db",
            action="provide at most one decibel offset per speaker in the layout",
        )
    offsets: dict[str, float] = {}
    for row in raw_offsets:
        if not isinstance(row, list) or len(row) != 2:
            raise business_repair(
                "SPEAKER_OFFSET_INVALID",
                field="speaker_offsets_db",
                action="provide each offset as one speaker name and decibel value",
            )
        speaker, raw_db = row
        if not isinstance(speaker, str) or speaker not in speakers or speaker in offsets:
            raise business_repair(
                "SPEAKER_OFFSET_INVALID",
                field="speaker_offsets_db",
                allowed_speakers=list(speakers),
                action="use each layout speaker at most once with -200..200 dB",
            )
        offsets[speaker] = _finite_decibels(
            raw_db,
            error_code="SPEAKER_OFFSET_INVALID",
            field="speaker_offsets_db",
            action="use each layout speaker at most once with -200..200 dB",
        )
    return [offsets.get(speaker, 0.0) for speaker in speakers]


def _compile_indexed_offsets(raw_offsets: object, *, channel_count: int) -> list[float]:
    if not isinstance(raw_offsets, list) or len(raw_offsets) > channel_count:
        raise business_repair(
            "CHANNEL_OFFSET_LIST_INVALID",
            field="channel_offsets_db",
            action="provide at most one decibel offset per one-based channel index",
        )
    offsets: dict[int, float] = {}
    for row in raw_offsets:
        if not isinstance(row, list) or len(row) != 2:
            raise business_repair(
                "CHANNEL_OFFSET_INVALID",
                field="channel_offsets_db",
                action="provide each offset as one one-based channel index and decibel value",
            )
        raw_index, raw_db = row
        try:
            index = int(raw_index)
        except (TypeError, ValueError) as exc:
            raise business_repair(
                "CHANNEL_OFFSET_INVALID",
                field="channel_offsets_db",
                action="use each one-based channel index at most once",
            ) from exc
        if str(index) != str(raw_index).strip() or not 1 <= index <= channel_count or index in offsets:
            raise business_repair(
                "CHANNEL_OFFSET_INVALID",
                field="channel_offsets_db",
                channel_count=channel_count,
                action="use each one-based channel index at most once",
            )
        offsets[index] = _finite_decibels(
            raw_db,
            error_code="CHANNEL_OFFSET_INVALID",
            field="channel_offsets_db",
            action="provide a finite -200..200 dB value for each changed channel",
        )
    return [offsets.get(index, 0.0) for index in range(1, channel_count + 1)]


def _compile_listener_spatialization(
    plan: Mapping[str, Any],
    game_object_bindings: object,
    *,
    version: str,
) -> dict[str, Any]:
    required = {"listener_handle", "spatialization"}
    optional = {
        "channel_layout",
        "channel_layout_kind",
        "channel_speakers",
        "channel_count",
        "speaker_offsets_db",
        "channel_offsets_db",
    }
    if not required <= set(plan) or set(plan) - (required | optional):
        raise business_repair(
            "SOUNDENGINE_PLAN_FIELDS_INVALID",
            field="soundengine_plan",
            required=sorted(required),
            optional=sorted(optional),
            action="submit exactly the fields disclosed for this SoundEngine command",
        )
    spatialization = plan.get("spatialization")
    if spatialization not in {"enabled", "disabled"}:
        raise business_repair(
            "BUSINESS_VALUE_INVALID",
            field="spatialization",
            allowed=["enabled", "disabled"],
            action="copy one disclosed spatialization state exactly",
        )

    preset = plan.get("channel_layout")
    kind = plan.get("channel_layout_kind")
    if (preset is None) == (kind is None):
        raise business_repair(
            "CHANNEL_LAYOUT_DESCRIPTOR_INVALID",
            field="channel_layout",
            action="provide exactly one standard preset or one Wwise channel layout kind",
        )
    raw_speakers = plan.get("channel_speakers")
    raw_count = plan.get("channel_count")
    raw_speaker_offsets = plan.get("speaker_offsets_db", [])
    raw_channel_offsets = plan.get("channel_offsets_db", [])

    if preset is not None:
        speakers = _STANDARD_CHANNEL_LAYOUTS.get(preset)
        if speakers is None:
            raise business_repair(
                "BUSINESS_VALUE_INVALID",
                field="channel_layout",
                allowed=list(_STANDARD_CHANNEL_LAYOUTS),
                action="copy one disclosed Wwise standard channel layout exactly",
            )
        if raw_speakers is not None or raw_count is not None or raw_channel_offsets:
            raise business_repair(
                "CHANNEL_LAYOUT_DESCRIPTOR_INVALID",
                field="channel_layout",
                action="combine a standard preset only with optional named speaker offsets",
            )
        channel_mask = sum(_SPEAKER_MASKS[speaker] for speaker in speakers)
        channel_config = len(speakers) | (1 << 8) | (channel_mask << 12)
        volume_offsets = _compile_named_offsets(
            raw_speaker_offsets,
            speakers=speakers,
        )
    elif kind == "Standard":
        if (
            not isinstance(raw_speakers, list)
            or not raw_speakers
            or raw_count is not None
            or raw_channel_offsets
            or any(not isinstance(speaker, str) for speaker in raw_speakers)
            or len(set(raw_speakers)) != len(raw_speakers)
            or any(speaker not in _SPEAKER_MASKS for speaker in raw_speakers)
            or (
                version not in _HEIGHT_SIDE_SPEAKER_VERSIONS
                and any(speaker in {"HSL", "HSR"} for speaker in raw_speakers)
            )
        ):
            raise business_repair(
                "STANDARD_CHANNEL_SPEAKERS_INVALID",
                field="channel_speakers",
                allowed_speakers=[
                    speaker
                    for speaker in _SPEAKER_MASKS
                    if version in _HEIGHT_SIDE_SPEAKER_VERSIONS
                    or speaker not in {"HSL", "HSR"}
                ],
                action="provide each version-supported Wwise speaker name once",
            )
        ordered = tuple(
            sorted(
                (speaker for speaker in raw_speakers if speaker != "LFE"),
                key=_SPEAKER_MASKS.__getitem__,
            )
            + (["LFE"] if "LFE" in raw_speakers else [])
        )
        channel_mask = sum(_SPEAKER_MASKS[speaker] for speaker in ordered)
        channel_config = len(ordered) | (1 << 8) | (channel_mask << 12)
        volume_offsets = _compile_named_offsets(
            raw_speaker_offsets,
            speakers=ordered,
        )
    elif kind in {"Anonymous", "Ambisonic"}:
        if (
            isinstance(raw_count, bool)
            or not isinstance(raw_count, int)
            or not 1 <= raw_count <= 255
            or raw_speakers is not None
            or raw_speaker_offsets
            or (kind == "Ambisonic" and raw_count not in _AMBISONIC_CHANNEL_COUNTS)
        ):
            raise business_repair(
                "CHANNEL_COUNT_INVALID",
                field="channel_count",
                allowed=(
                    sorted(_AMBISONIC_CHANNEL_COUNTS)
                    if kind == "Ambisonic"
                    else "1..255"
                ),
                action="provide a valid channel count for the selected Wwise layout kind",
            )
        channel_config = raw_count | ((2 if kind == "Ambisonic" else 0) << 8)
        volume_offsets = _compile_indexed_offsets(
            raw_channel_offsets,
            channel_count=raw_count,
        )
    elif kind == "Objects":
        if (
            raw_speakers is not None
            or raw_count is not None
            or raw_speaker_offsets
            or raw_channel_offsets
        ):
            raise business_repair(
                "OBJECT_CHANNEL_LAYOUT_INVALID",
                field="channel_layout_kind",
                action="use Objects without fixed speakers, channel count, or offsets",
            )
        channel_config = 3 << 8
        volume_offsets = []
    else:
        raise business_repair(
            "CHANNEL_LAYOUT_KIND_INVALID",
            field="channel_layout_kind",
            allowed=["Standard", "Anonymous", "Ambisonic", "Objects"],
            action="copy one disclosed Wwise channel layout kind exactly",
        )

    return {
        "listener": _runtime_game_object_id(
            game_object_bindings,
            plan.get("listener_handle"),
            field="listener_handle",
        ),
        "spatialized": spatialization == "enabled",
        "channelConfig": channel_config,
        "volumeOffsets": volume_offsets,
    }


def materialize_soundengine_control_business_request(
    operation: str,
    session: BusinessDeclarationSession,
) -> dict[str, Any]:
    if not isinstance(session, BusinessDeclarationSession):
        raise TypeError("session must be BusinessDeclarationSession")
    contract = soundengine_control_business_contract_data(
        operation,
        session.context.wwise_version,
    )
    if not set(session.settings) <= {
        "soundengine_plan",
        "runtime_game_object_binding",
        "runtime_game_object_bindings",
        "runtime_playing_binding",
    } or "soundengine_plan" not in session.settings:
        raise business_repair(
            "SOUNDENGINE_PLAN_INCOMPLETE",
            field="soundengine_plan",
            action="submit the one complete Gateway-disclosed SoundEngine plan",
        )
    plan = session.settings["soundengine_plan"]
    game_object_binding = session.settings.get("runtime_game_object_binding")
    game_object_bindings = session.settings.get("runtime_game_object_bindings", {})
    playing_binding = session.settings.get("runtime_playing_binding")
    if not isinstance(plan, Mapping):
        raise business_repair(
            "SOUNDENGINE_PLAN_INVALID",
            field="soundengine_plan",
            action="submit one closed SoundEngine plan",
        )
    if operation == POST_MONITOR_MESSAGE_URI:
        if set(plan) != {"monitor_message"}:
            raise business_repair(
                "SOUNDENGINE_PLAN_FIELDS_INVALID",
                field="soundengine_plan",
                required=["monitor_message"],
                optional=[],
                action="submit exactly the fields disclosed for this SoundEngine command",
            )
        message = plan.get("monitor_message")
        if (
            not isinstance(message, str)
            or not message
            or "\x00" in message
            or len(message.encode("utf-8")) > 16 * 1024
        ):
            raise business_repair(
                "BUSINESS_VALUE_INVALID",
                field="monitor_message",
                action="provide one nonempty exact message up to 16384 UTF-8 bytes",
            )
        native_args = {"message": message}
    elif operation == POST_EVENT_URI:
        required = set(contract["declaration"]["required_fields"])
        optional = set(contract["declaration"]["optional_fields"])
        if not required <= set(plan) or set(plan) - (required | optional):
            raise business_repair(
                "SOUNDENGINE_PLAN_FIELDS_INVALID",
                field="soundengine_plan",
                required=sorted(required),
                optional=sorted(optional),
                action="submit exactly the fields disclosed for this SoundEngine command",
            )
        event_handle = plan.get("event_handle")
        if not isinstance(event_handle, str):
            raise business_repair(
                "REQUIRED_FIELD_MISSING",
                field="event_handle",
                action="bind the exact Event and copy its returned handle",
            )
        event = session.handles.resolve_object(event_handle)
        if event.role != "event" or event.object_type != "Event":
            raise business_repair(
                "BOUND_OBJECT_ROLE_MISMATCH",
                field="event_handle",
                expected_role="event",
                allowed_types=["Event"],
                actual_role=event.role,
                actual_type=event.object_type,
                action="copy the handle returned for the Event role",
            )
        native_args = {"event": event.object_id}
        game_object_handle = plan.get("game_object_handle")
        if game_object_handle is not None:
            if (
                not isinstance(game_object_handle, str)
                or not isinstance(game_object_binding, Mapping)
                or game_object_binding.get("handle") != game_object_handle
            ):
                raise business_repair(
                    "GAME_OBJECT_HANDLE_INVALID",
                    field="game_object_handle",
                    action="copy one active game object handle from a Gateway result",
                )
            game_object_id = game_object_binding.get("game_object_id")
            if (
                isinstance(game_object_id, bool)
                or not isinstance(game_object_id, int)
                or not 0 <= game_object_id <= 0xFFFFFFFFFFFFFFDF
            ):
                raise business_repair(
                    "GAME_OBJECT_HANDLE_INVALID",
                    field="game_object_handle",
                    action="bind the active handle again",
                )
            native_args["gameObject"] = game_object_id
        elif game_object_binding is not None:
            raise business_repair(
                "SOUNDENGINE_PLAN_FIELDS_INVALID",
                field="game_object_handle",
                action="omit stale game object binding state",
            )
    elif operation == REGISTER_GAME_OBJECT_URI:
        if set(plan) != {"game_object_name"}:
            raise business_repair(
                "SOUNDENGINE_PLAN_FIELDS_INVALID",
                field="soundengine_plan",
                required=["game_object_name"],
                optional=[],
                action="submit exactly the fields disclosed for this SoundEngine command",
            )
        name = plan.get("game_object_name")
        if (
            not isinstance(name, str)
            or not name
            or "\x00" in name
            or len(name.encode("utf-8")) > 512
        ):
            raise business_repair(
                "BUSINESS_VALUE_INVALID",
                field="game_object_name",
                action="provide one nonempty exact name up to 512 UTF-8 bytes",
            )
        identity_digest = canonical_sha256(
            {
                "contract": "waapi-skill.soundengine-game-object-id/v1",
                "context": session.context.as_binding_dict(),
                "name": name,
            }
        )
        game_object_id = int(identity_digest[:16], 16) & 0x7FFFFFFFFFFFFFFF
        native_args = {
            "gameObject": game_object_id or 1,
            "name": name,
        }
    elif operation == EXECUTE_ACTION_ON_EVENT_URI:
        required = {"event_handle", "action"}
        optional = {"game_object_handle", "fade_duration_ms", "fade_curve"}
        if not required <= set(plan) or set(plan) - (required | optional):
            raise business_repair(
                "SOUNDENGINE_PLAN_FIELDS_INVALID",
                field="soundengine_plan",
                required=sorted(required),
                optional=sorted(optional),
                action="submit exactly the fields disclosed for this SoundEngine command",
            )
        event_handle = plan.get("event_handle")
        if not isinstance(event_handle, str):
            raise business_repair(
                "REQUIRED_FIELD_MISSING",
                field="event_handle",
                action="bind the exact Event and copy its returned handle",
            )
        event = session.handles.resolve_object(event_handle)
        if event.role != "event" or event.object_type != "Event":
            raise business_repair(
                "BOUND_OBJECT_ROLE_MISMATCH",
                field="event_handle",
                expected_role="event",
                allowed_types=["Event"],
                actual_role=event.role,
                actual_type=event.object_type,
                action="copy the handle returned for the Event role",
            )
        action_name = plan.get("action")
        if action_name not in _EVENT_ACTIONS:
            raise business_repair(
                "BUSINESS_VALUE_INVALID",
                field="action",
                allowed=list(_EVENT_ACTIONS),
                action="copy one disclosed Wwise Event action name exactly",
            )
        game_object_id = _INVALID_GAME_OBJECT
        game_object_handle = plan.get("game_object_handle")
        if game_object_handle is not None:
            if (
                not isinstance(game_object_handle, str)
                or not isinstance(game_object_binding, Mapping)
                or game_object_binding.get("handle") != game_object_handle
            ):
                raise business_repair(
                    "GAME_OBJECT_HANDLE_INVALID",
                    field="game_object_handle",
                    action="copy one active game object handle from a Gateway result",
                )
            game_object_id = game_object_binding.get("game_object_id")
            if (
                isinstance(game_object_id, bool)
                or not isinstance(game_object_id, int)
                or not 0 <= game_object_id <= 0xFFFFFFFFFFFFFFDF
            ):
                raise business_repair(
                    "GAME_OBJECT_HANDLE_INVALID",
                    field="game_object_handle",
                    action="bind the active handle again",
                )
        fade_duration_ms = plan.get("fade_duration_ms", 0)
        if (
            isinstance(fade_duration_ms, bool)
            or not isinstance(fade_duration_ms, int)
            or not 0 <= fade_duration_ms <= 0x7FFFFFFF
        ):
            raise business_repair(
                "BUSINESS_VALUE_INVALID",
                field="fade_duration_ms",
                action="provide a whole millisecond duration from 0 through 2147483647",
            )
        fade_curve = plan.get("fade_curve", "Linear")
        if fade_curve not in _FADE_CURVES:
            raise business_repair(
                "BUSINESS_VALUE_INVALID",
                field="fade_curve",
                allowed=list(_FADE_CURVES),
                action="copy one disclosed Wwise fade curve name exactly",
            )
        native_args = {
            "event": event.object_id,
            "actionType": _EVENT_ACTIONS[action_name],
            "gameObject": game_object_id,
            "transitionDuration": fade_duration_ms,
            "fadeCurve": _FADE_CURVES[fade_curve],
        }
    elif operation == STOP_ALL_URI:
        if set(plan) - {"game_object_handle"}:
            raise business_repair(
                "SOUNDENGINE_PLAN_FIELDS_INVALID",
                field="soundengine_plan",
                required=[],
                optional=["game_object_handle"],
                action="submit exactly the fields disclosed for this SoundEngine command",
            )
        game_object_handle = plan.get("game_object_handle")
        if game_object_handle is None:
            game_object_id = _INVALID_GAME_OBJECT
        else:
            if (
                not isinstance(game_object_handle, str)
                or not isinstance(game_object_binding, Mapping)
                or game_object_binding.get("handle") != game_object_handle
            ):
                raise business_repair(
                    "GAME_OBJECT_HANDLE_INVALID",
                    field="game_object_handle",
                    action="copy one active game object handle from a Gateway result",
                )
            game_object_id = game_object_binding.get("game_object_id")
            if (
                isinstance(game_object_id, bool)
                or not isinstance(game_object_id, int)
                or not 0 <= game_object_id <= 0xFFFFFFFFFFFFFFDF
            ):
                raise business_repair(
                    "GAME_OBJECT_HANDLE_INVALID",
                    field="game_object_handle",
                    action="bind the active handle again",
                )
        native_args = {"gameObject": game_object_id}
    elif operation == SEEK_ON_EVENT_URI:
        allowed = {
            "event_handle",
            "game_object_handle",
            "playing_handle",
            "position_ms",
            "position_percent",
            "nearest_marker",
        }
        if "event_handle" not in plan or set(plan) - allowed:
            raise business_repair(
                "SOUNDENGINE_PLAN_FIELDS_INVALID",
                field="soundengine_plan",
                required=["event_handle"],
                optional=sorted(allowed - {"event_handle"}),
                action="submit exactly the fields disclosed for this SoundEngine command",
            )
        position_fields = {
            field for field in ("position_ms", "position_percent") if field in plan
        }
        if len(position_fields) != 1:
            raise business_repair(
                "SOUNDENGINE_SEEK_TARGET_INVALID",
                field="position",
                exactly_one_of=["position_ms", "position_percent"],
                action="provide exactly one absolute millisecond or percentage position",
            )
        event_handle = plan.get("event_handle")
        if not isinstance(event_handle, str):
            raise business_repair(
                "REQUIRED_FIELD_MISSING",
                field="event_handle",
                action="bind the exact Event and copy its returned handle",
            )
        event = session.handles.resolve_object(event_handle)
        if event.role != "event" or event.object_type != "Event":
            raise business_repair(
                "BOUND_OBJECT_ROLE_MISMATCH",
                field="event_handle",
                expected_role="event",
                allowed_types=["Event"],
                actual_role=event.role,
                actual_type=event.object_type,
                action="copy the handle returned for the Event role",
            )
        game_object_id = _INVALID_GAME_OBJECT
        playing_id = _INVALID_PLAYING_ID
        game_object_handle = plan.get("game_object_handle")
        playing_handle = plan.get("playing_handle")
        if game_object_handle is not None and playing_handle is not None:
            raise business_repair(
                "SOUNDENGINE_SEEK_SCOPE_AMBIGUOUS",
                field="playing_handle",
                action="use a playing handle for one instance or a game object handle for that scope, not both",
            )
        if playing_handle is not None:
            if (
                not isinstance(playing_handle, str)
                or not isinstance(playing_binding, Mapping)
                or playing_binding.get("handle") != playing_handle
            ):
                raise business_repair(
                    "PLAYING_HANDLE_INVALID",
                    field="playing_handle",
                    action="copy one active playing handle from a Gateway postEvent result",
                )
            playing_id = playing_binding.get("playing_id")
            if (
                isinstance(playing_id, bool)
                or not isinstance(playing_id, int)
                or not 1 <= playing_id <= 0xFFFFFFFF
                or playing_binding.get("event_id") != event.object_id
            ):
                raise business_repair(
                    "PLAYING_HANDLE_EVENT_MISMATCH",
                    field="playing_handle",
                    action="use a playing handle issued for the bound Event",
                )
        elif game_object_handle is not None:
            if (
                not isinstance(game_object_handle, str)
                or not isinstance(game_object_binding, Mapping)
                or game_object_binding.get("handle") != game_object_handle
            ):
                raise business_repair(
                    "GAME_OBJECT_HANDLE_INVALID",
                    field="game_object_handle",
                    action="copy one active game object handle from a Gateway result",
                )
            game_object_id = game_object_binding.get("game_object_id")
            if (
                isinstance(game_object_id, bool)
                or not isinstance(game_object_id, int)
                or not 0 <= game_object_id <= 0xFFFFFFFFFFFFFFDF
            ):
                raise business_repair(
                    "GAME_OBJECT_HANDLE_INVALID",
                    field="game_object_handle",
                    action="bind the active handle again",
                )
        nearest_marker = plan.get("nearest_marker", False)
        if not isinstance(nearest_marker, bool):
            raise business_repair(
                "BUSINESS_VALUE_INVALID",
                field="nearest_marker",
                action="provide a boolean marker preference",
            )
        native_args: dict[str, Any] = {
            "event": event.object_id,
            "gameObject": game_object_id,
            "seekToNearestMarker": nearest_marker,
            "playingId": playing_id,
        }
        if "position_ms" in position_fields:
            position_ms = plan.get("position_ms")
            if (
                isinstance(position_ms, bool)
                or not isinstance(position_ms, int)
                or not 0 <= position_ms <= 0x7FFFFFFF
            ):
                raise business_repair(
                    "BUSINESS_VALUE_INVALID",
                    field="position_ms",
                    action="provide whole milliseconds from 0 through 2147483647",
                )
            native_args["position"] = position_ms
        else:
            position_percent = plan.get("position_percent")
            if (
                isinstance(position_percent, bool)
                or not isinstance(position_percent, (int, float))
                or not 0 <= position_percent <= 100
            ):
                raise business_repair(
                    "BUSINESS_VALUE_INVALID",
                    field="position_percent",
                    action="provide a percentage from 0 through 100",
                )
            native_args["percent"] = position_percent / 100.0
    elif operation == SET_STATE_URI:
        if set(plan) != {"state_group_handle", "state_handle"}:
            raise business_repair(
                "SOUNDENGINE_PLAN_FIELDS_INVALID",
                field="soundengine_plan",
                required=["state_group_handle", "state_handle"],
                optional=[],
                action="submit exactly the fields disclosed for this SoundEngine command",
            )
        state_group_handle = plan.get("state_group_handle")
        state_handle = plan.get("state_handle")
        if not isinstance(state_group_handle, str) or not isinstance(
            state_handle, str
        ):
            raise business_repair(
                "REQUIRED_FIELD_MISSING",
                field="state_group_handle",
                action="bind the exact State Group and State and copy both returned handles",
            )
        state_group = session.handles.resolve_object(state_group_handle)
        state = session.handles.resolve_object(state_handle)
        if (
            state_group.role != "state_group"
            or state_group.object_type != "StateGroup"
            or state.role != "state"
            or state.object_type != "State"
        ):
            raise business_repair(
                "BOUND_OBJECT_ROLE_MISMATCH",
                field="state_handle",
                expected_roles=["state_group", "state"],
                allowed_types=["StateGroup", "State"],
                action="copy the handles returned for the State Group and State roles",
            )
        if state.path.rsplit("\\", 1)[0] != state_group.path:
            raise business_repair(
                "STATE_GROUP_RELATIONSHIP_MISMATCH",
                field="state_handle",
                action="bind a State that is a direct child of the bound State Group",
            )
        native_args = {
            "stateGroup": state_group.object_id,
            "state": state.object_id,
        }
    elif operation == SET_SWITCH_URI:
        required = set(contract["declaration"]["required_fields"])
        optional = set(contract["declaration"]["optional_fields"])
        if not required <= set(plan) or set(plan) - (required | optional):
            raise business_repair(
                "SOUNDENGINE_PLAN_FIELDS_INVALID",
                field="soundengine_plan",
                required=sorted(required),
                optional=sorted(optional),
                action="submit exactly the fields disclosed for this SoundEngine command",
            )
        switch_group_handle = plan.get("switch_group_handle")
        switch_handle = plan.get("switch_handle")
        if not isinstance(switch_group_handle, str) or not isinstance(
            switch_handle, str
        ):
            raise business_repair(
                "REQUIRED_FIELD_MISSING",
                field="switch_group_handle",
                action="bind the exact Switch Group and Switch and copy both returned handles",
            )
        switch_group = session.handles.resolve_object(switch_group_handle)
        switch = session.handles.resolve_object(switch_handle)
        if (
            switch_group.role != "switch_group"
            or switch_group.object_type != "SwitchGroup"
            or switch.role != "switch"
            or switch.object_type != "Switch"
        ):
            raise business_repair(
                "BOUND_OBJECT_ROLE_MISMATCH",
                field="switch_handle",
                expected_roles=["switch_group", "switch"],
                allowed_types=["SwitchGroup", "Switch"],
                action="copy the handles returned for the Switch Group and Switch roles",
            )
        if switch.path.rsplit("\\", 1)[0] != switch_group.path:
            raise business_repair(
                "SWITCH_GROUP_RELATIONSHIP_MISMATCH",
                field="switch_handle",
                action="bind a Switch that is a direct child of the bound Switch Group",
            )
        native_args = {
            "switchGroup": switch_group.object_id,
            "switchState": switch.object_id,
        }
        game_object_handle = plan.get("game_object_handle")
        if game_object_handle is not None:
            if (
                not isinstance(game_object_handle, str)
                or not isinstance(game_object_binding, Mapping)
                or game_object_binding.get("handle") != game_object_handle
            ):
                raise business_repair(
                    "GAME_OBJECT_HANDLE_INVALID",
                    field="game_object_handle",
                    action="copy one active game object handle from a Gateway result",
                )
            game_object_id = game_object_binding.get("game_object_id")
            if (
                isinstance(game_object_id, bool)
                or not isinstance(game_object_id, int)
                or not 0 <= game_object_id <= 0xFFFFFFFFFFFFFFDF
            ):
                raise business_repair(
                    "GAME_OBJECT_HANDLE_INVALID",
                    field="game_object_handle",
                    action="bind the active handle again",
                )
            native_args["gameObject"] = game_object_id
    elif operation == POST_TRIGGER_URI:
        required = set(contract["declaration"]["required_fields"])
        optional = set(contract["declaration"]["optional_fields"])
        if not required <= set(plan) or set(plan) - (required | optional):
            raise business_repair(
                "SOUNDENGINE_PLAN_FIELDS_INVALID",
                field="soundengine_plan",
                required=sorted(required),
                optional=sorted(optional),
                action="submit exactly the fields disclosed for this SoundEngine command",
            )
        trigger_handle = plan.get("trigger_handle")
        if not isinstance(trigger_handle, str):
            raise business_repair(
                "REQUIRED_FIELD_MISSING",
                field="trigger_handle",
                action="bind the exact Trigger and copy its returned handle",
            )
        trigger = session.handles.resolve_object(trigger_handle)
        if trigger.role != "trigger" or trigger.object_type != "Trigger":
            raise business_repair(
                "BOUND_OBJECT_ROLE_MISMATCH",
                field="trigger_handle",
                expected_role="trigger",
                allowed_types=["Trigger"],
                actual_role=trigger.role,
                actual_type=trigger.object_type,
                action="copy the handle returned for the Trigger role",
            )
        native_args = {"trigger": trigger.object_id}
        game_object_handle = plan.get("game_object_handle")
        if game_object_handle is not None:
            if (
                not isinstance(game_object_handle, str)
                or not isinstance(game_object_binding, Mapping)
                or game_object_binding.get("handle") != game_object_handle
            ):
                raise business_repair(
                    "GAME_OBJECT_HANDLE_INVALID",
                    field="game_object_handle",
                    action="copy one active game object handle from a Gateway result",
                )
            game_object_id = game_object_binding.get("game_object_id")
            if (
                isinstance(game_object_id, bool)
                or not isinstance(game_object_id, int)
                or not 0 <= game_object_id <= 0xFFFFFFFFFFFFFFDF
            ):
                raise business_repair(
                    "GAME_OBJECT_HANDLE_INVALID",
                    field="game_object_handle",
                    action="bind the active handle again",
                )
            native_args["gameObject"] = game_object_id
    elif operation in {SET_GAME_PARAMETER_URI, RESET_GAME_PARAMETER_URI}:
        required = set(contract["declaration"]["required_fields"])
        optional = set(contract["declaration"]["optional_fields"])
        if not required <= set(plan) or set(plan) - (required | optional):
            raise business_repair(
                "SOUNDENGINE_PLAN_FIELDS_INVALID",
                field="soundengine_plan",
                required=sorted(required),
                optional=sorted(optional),
                action="submit exactly the fields disclosed for this SoundEngine command",
            )
        parameter_handle = plan.get("game_parameter_handle")
        if not isinstance(parameter_handle, str):
            raise business_repair(
                "REQUIRED_FIELD_MISSING",
                field="game_parameter_handle",
                action="bind the exact Game Parameter and copy its returned handle",
            )
        parameter = session.handles.resolve_object(parameter_handle)
        if (
            parameter.role != "game_parameter"
            or parameter.object_type != "GameParameter"
        ):
            raise business_repair(
                "BOUND_OBJECT_ROLE_MISMATCH",
                field="game_parameter_handle",
                expected_role="game_parameter",
                allowed_types=["GameParameter"],
                actual_role=parameter.role,
                actual_type=parameter.object_type,
                action="copy the handle returned for the Game Parameter role",
            )
        native_args = {"rtpc": parameter.object_id}
        if operation == SET_GAME_PARAMETER_URI:
            value = plan.get("value")
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
            ):
                raise business_repair(
                    "BUSINESS_VALUE_INVALID",
                    field="value",
                    action="provide one finite Game Parameter value",
                )
            native_args["value"] = value
        game_object_handle = plan.get("game_object_handle")
        if game_object_handle is not None:
            if (
                not isinstance(game_object_handle, str)
                or not isinstance(game_object_binding, Mapping)
                or game_object_binding.get("handle") != game_object_handle
            ):
                raise business_repair(
                    "GAME_OBJECT_HANDLE_INVALID",
                    field="game_object_handle",
                    action="copy one active game object handle from a Gateway result",
                )
            game_object_id = game_object_binding.get("game_object_id")
            if (
                isinstance(game_object_id, bool)
                or not isinstance(game_object_id, int)
                or not 0 <= game_object_id <= 0xFFFFFFFFFFFFFFDF
            ):
                raise business_repair(
                    "GAME_OBJECT_HANDLE_INVALID",
                    field="game_object_handle",
                    action="bind the active handle again",
                )
            native_args["gameObject"] = game_object_id
    elif operation in {LOAD_BANK_URI, UNLOAD_BANK_URI}:
        if set(plan) != {"sound_bank_handle"}:
            raise business_repair(
                "SOUNDENGINE_PLAN_FIELDS_INVALID",
                field="soundengine_plan",
                required=["sound_bank_handle"],
                optional=[],
                action="submit exactly the fields disclosed for this SoundEngine command",
            )
        sound_bank_handle = plan.get("sound_bank_handle")
        if not isinstance(sound_bank_handle, str):
            raise business_repair(
                "REQUIRED_FIELD_MISSING",
                field="sound_bank_handle",
                action="bind the exact SoundBank and copy its returned handle",
            )
        sound_bank = session.handles.resolve_object(sound_bank_handle)
        if (
            sound_bank.role != "sound_bank"
            or sound_bank.object_type != "SoundBank"
        ):
            raise business_repair(
                "BOUND_OBJECT_ROLE_MISMATCH",
                field="sound_bank_handle",
                expected_role="sound_bank",
                allowed_types=["SoundBank"],
                actual_role=sound_bank.role,
                actual_type=sound_bank.object_type,
                action="copy the handle returned for the SoundBank role",
            )
        native_args = {"soundBank": sound_bank.object_id}
    elif operation == SET_DEFAULT_LISTENERS_URI:
        if set(plan) - {"listener_handles", "clear_listeners"}:
            raise business_repair(
                "SOUNDENGINE_PLAN_FIELDS_INVALID",
                field="soundengine_plan",
                required=[],
                optional=["listener_handles", "clear_listeners"],
                action="submit exactly the fields disclosed for this SoundEngine command",
            )
        handles = plan.get("listener_handles")
        clear = plan.get("clear_listeners")
        if (handles is None) == (clear is None) or (
            clear is not None and clear is not True
        ):
            raise business_repair(
                "LISTENER_SET_INVALID",
                field="listener_handles",
                action="provide listener handles or the explicit clear-listeners intent, not both",
            )
        if handles is not None and (
            not isinstance(handles, list)
            or not 1 <= len(handles) <= 64
            or len(set(handles)) != len(handles)
        ):
            raise business_repair(
                "LISTENER_SET_INVALID",
                field="listener_handles",
                action="provide 1 through 64 distinct active listener handles",
            )
        native_args = {
            "listeners": [] if clear else [
                _runtime_game_object_id(
                    game_object_bindings, handle, field="listener_handles"
                )
                for handle in handles
            ]
        }
    elif operation == SET_LISTENERS_URI:
        if "emitter_handle" not in plan or set(plan) - {
            "emitter_handle",
            "listener_handles",
            "clear_listeners",
        }:
            raise business_repair(
                "SOUNDENGINE_PLAN_FIELDS_INVALID",
                field="soundengine_plan",
                required=["emitter_handle"],
                optional=["listener_handles", "clear_listeners"],
                action="submit exactly the fields disclosed for this SoundEngine command",
            )
        handles = plan.get("listener_handles")
        clear = plan.get("clear_listeners")
        if (handles is None) == (clear is None) or (
            clear is not None and clear is not True
        ):
            raise business_repair(
                "LISTENER_SET_INVALID",
                field="listener_handles",
                action="provide listener handles or the explicit clear-listeners intent, not both",
            )
        if handles is not None and (
            not isinstance(handles, list)
            or not 1 <= len(handles) <= 64
            or len(set(handles)) != len(handles)
        ):
            raise business_repair(
                "LISTENER_SET_INVALID",
                field="listener_handles",
                action="provide 1 through 64 distinct active listener handles",
            )
        native_args = {
            "emitter": _runtime_game_object_id(
                game_object_bindings,
                plan.get("emitter_handle"),
                field="emitter_handle",
            ),
            "listeners": [] if clear else [
                _runtime_game_object_id(
                    game_object_bindings, handle, field="listener_handles"
                )
                for handle in handles
            ],
        }
    elif operation == SET_POSITION_URI:
        if set(plan) != {"game_object_handle", "position_frame"}:
            raise business_repair(
                "SOUNDENGINE_PLAN_FIELDS_INVALID",
                field="soundengine_plan",
                required=["game_object_handle", "position_frame"],
                optional=[],
                action="submit exactly the fields disclosed for this SoundEngine command",
            )
        if not isinstance(game_object_binding, Mapping):
            raise business_repair(
                "GAME_OBJECT_HANDLE_INVALID",
                field="game_object_handle",
                action="copy one active game object handle from a Gateway result",
            )
        native_args = {
            "gameObject": game_object_binding.get("game_object_id"),
            "position": _position_frame(plan.get("position_frame")),
        }
    elif operation == SET_MULTIPLE_POSITIONS_URI:
        if set(plan) != {
            "game_object_handle",
            "position_frames",
            "multi_position_mode",
        }:
            raise business_repair(
                "SOUNDENGINE_PLAN_FIELDS_INVALID",
                field="soundengine_plan",
                required=[
                    "game_object_handle",
                    "position_frames",
                    "multi_position_mode",
                ],
                optional=[],
                action="submit exactly the fields disclosed for this SoundEngine command",
            )
        frames = plan.get("position_frames")
        if not isinstance(frames, list) or not 1 <= len(frames) <= 256:
            raise business_repair(
                "POSITION_FRAME_LIST_INVALID",
                field="position_frames",
                action="provide 1 through 256 complete position frames",
            )
        mode = plan.get("multi_position_mode")
        if mode not in _MULTI_POSITION_MODES:
            raise business_repair(
                "BUSINESS_VALUE_INVALID",
                field="multi_position_mode",
                allowed=list(_MULTI_POSITION_MODES),
                action="copy one disclosed Wwise multi-position mode exactly",
            )
        if not isinstance(game_object_binding, Mapping):
            raise business_repair(
                "GAME_OBJECT_HANDLE_INVALID",
                field="game_object_handle",
                action="copy one active game object handle from a Gateway result",
            )
        native_args = {
            "gameObject": game_object_binding.get("game_object_id"),
            "positions": [
                {"position": _position_frame(frame)} for frame in frames
            ],
            "multiPositionType": _MULTI_POSITION_MODES[mode],
        }
    elif operation == SET_OBSTRUCTION_OCCLUSION_URI:
        if set(plan) != {
            "emitter_handle",
            "listener_handle",
            "obstruction_percent",
            "occlusion_percent",
        }:
            raise business_repair(
                "SOUNDENGINE_PLAN_FIELDS_INVALID",
                field="soundengine_plan",
                required=[
                    "emitter_handle",
                    "listener_handle",
                    "obstruction_percent",
                    "occlusion_percent",
                ],
                optional=[],
                action="submit exactly the fields disclosed for this SoundEngine command",
            )
        obstruction = plan.get("obstruction_percent")
        occlusion = plan.get("occlusion_percent")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(value)
            or not 0 <= value <= 100
            for value in (obstruction, occlusion)
        ):
            raise business_repair(
                "BUSINESS_VALUE_INVALID",
                field="obstruction_percent",
                action="provide obstruction and occlusion percentages from 0 through 100",
            )
        native_args = {
            "emitter": _runtime_game_object_id(
                game_object_bindings,
                plan.get("emitter_handle"),
                field="emitter_handle",
            ),
            "listener": _runtime_game_object_id(
                game_object_bindings,
                plan.get("listener_handle"),
                field="listener_handle",
            ),
            "obstructionLevel": obstruction / 100.0,
            "occlusionLevel": occlusion / 100.0,
        }
    elif operation == SET_SCALING_FACTOR_URI:
        if set(plan) != {"game_object_handle", "attenuation_scale_percent"}:
            raise business_repair(
                "SOUNDENGINE_PLAN_FIELDS_INVALID",
                field="soundengine_plan",
                required=["game_object_handle", "attenuation_scale_percent"],
                optional=[],
                action="submit exactly the fields disclosed for this SoundEngine command",
            )
        scale = plan.get("attenuation_scale_percent")
        if (
            isinstance(scale, bool)
            or not isinstance(scale, (int, float))
            or not isfinite(scale)
            or scale <= 0
        ):
            raise business_repair(
                "BUSINESS_VALUE_INVALID",
                field="attenuation_scale_percent",
                action="provide one positive finite attenuation scale percentage",
            )
        if not isinstance(game_object_binding, Mapping):
            raise business_repair(
                "GAME_OBJECT_HANDLE_INVALID",
                field="game_object_handle",
                action="copy one active game object handle from a Gateway result",
            )
        native_args = {
            "gameObject": game_object_binding.get("game_object_id"),
            "attenuationScalingFactor": scale / 100.0,
        }
    elif operation == SET_OUTPUT_BUS_VOLUME_URI:
        if set(plan) != {"emitter_handle", "listener_handle", "volume_db"}:
            raise business_repair(
                "SOUNDENGINE_PLAN_FIELDS_INVALID",
                field="soundengine_plan",
                required=["emitter_handle", "listener_handle", "volume_db"],
                optional=[],
                action="submit exactly the fields disclosed for this SoundEngine command",
            )
        volume_db = plan.get("volume_db")
        if (
            isinstance(volume_db, bool)
            or not isinstance(volume_db, (int, float))
            or not isfinite(volume_db)
            or not -200 <= volume_db <= 200
        ):
            raise business_repair(
                "BUSINESS_VALUE_INVALID",
                field="volume_db",
                action="provide finite decibels from -200 through 200",
            )
        native_args = {
            "emitter": _runtime_game_object_id(
                game_object_bindings,
                plan.get("emitter_handle"),
                field="emitter_handle",
            ),
            "listener": _runtime_game_object_id(
                game_object_bindings,
                plan.get("listener_handle"),
                field="listener_handle",
            ),
            "controlValue": 10.0 ** (volume_db / 20.0),
        }
    elif operation == SET_LISTENER_SPATIALIZATION_URI:
        native_args = _compile_listener_spatialization(
            plan,
            game_object_bindings,
            version=session.context.wwise_version,
        )
    elif operation == SET_AUX_SENDS_URI:
        if "emitter_handle" not in plan or set(plan) - {
            "emitter_handle",
            "aux_sends",
            "clear_aux_sends",
        }:
            raise business_repair(
                "SOUNDENGINE_PLAN_FIELDS_INVALID",
                field="soundengine_plan",
                required=["emitter_handle"],
                optional=["aux_sends", "clear_aux_sends"],
                action="submit exactly the fields disclosed for this SoundEngine command",
            )
        rows = plan.get("aux_sends")
        clear = plan.get("clear_aux_sends")
        if (rows is None) == (clear is None) or (
            clear is not None and clear is not True
        ):
            raise business_repair(
                "AUX_SEND_LIST_INVALID",
                field="aux_sends",
                action="provide auxiliary send rows or explicit clear-aux-sends intent, not both",
            )
        if rows is not None and (
            not isinstance(rows, list) or not 1 <= len(rows) <= 4
        ):
            raise business_repair(
                "AUX_SEND_LIST_INVALID",
                field="aux_sends",
                action="provide 1 through 4 complete auxiliary send rows",
            )
        native_rows = []
        seen: set[tuple[int, str]] = set()
        for row in rows or []:
            if not isinstance(row, list) or len(row) != 3:
                raise business_repair(
                    "AUX_SEND_ROW_INVALID",
                    field="aux_sends",
                    action="provide listener handle, Aux Bus handle, and send percentage",
                )
            listener_handle, aux_bus_handle, raw_percent = row
            listener_id = _runtime_game_object_id(
                game_object_bindings,
                listener_handle,
                field="aux_sends.listener_handle",
            )
            if not isinstance(aux_bus_handle, str):
                raise business_repair(
                    "AUX_SEND_ROW_INVALID",
                    field="aux_sends.aux_bus_handle",
                    action="bind the exact Aux Bus and copy its returned handle",
                )
            aux_bus = session.handles.resolve_object(aux_bus_handle)
            if aux_bus.role != "aux_bus" or aux_bus.object_type != "AuxBus":
                raise business_repair(
                    "BOUND_OBJECT_ROLE_MISMATCH",
                    field="aux_sends.aux_bus_handle",
                    expected_role="aux_bus",
                    allowed_types=["AuxBus"],
                    actual_role=aux_bus.role,
                    actual_type=aux_bus.object_type,
                    action="copy a handle returned for the Aux Bus role",
                )
            try:
                send_percent = float(raw_percent)
            except (TypeError, ValueError) as exc:
                raise business_repair(
                    "AUX_SEND_ROW_INVALID",
                    field="aux_sends.send_percent",
                    action="provide a percentage from 0 through 100",
                ) from exc
            identity = (listener_id, aux_bus.object_id)
            if (
                not isfinite(send_percent)
                or not 0 <= send_percent <= 100
                or identity in seen
            ):
                raise business_repair(
                    "AUX_SEND_ROW_INVALID",
                    field="aux_sends",
                    action="use each listener and Aux Bus pair once with 0..100 percent",
                )
            seen.add(identity)
            native_rows.append(
                {
                    "listener": listener_id,
                    "auxBus": aux_bus.object_id,
                    "controlValue": send_percent / 100.0,
                }
            )
        native_args = {
            "gameObject": _runtime_game_object_id(
                game_object_bindings,
                plan.get("emitter_handle"),
                field="emitter_handle",
            ),
            "auxSendValues": native_rows,
        }
    elif operation == UNREGISTER_GAME_OBJECT_URI:
        if set(plan) != {"game_object_handle"}:
            raise business_repair(
                "SOUNDENGINE_PLAN_FIELDS_INVALID",
                field="soundengine_plan",
                required=["game_object_handle"],
                optional=[],
                action="submit exactly the fields disclosed for this SoundEngine command",
            )
        handle = plan.get("game_object_handle")
        if (
            not isinstance(handle, str)
            or not isinstance(game_object_binding, Mapping)
            or game_object_binding.get("handle") != handle
        ):
            raise business_repair(
                "GAME_OBJECT_HANDLE_INVALID",
                field="game_object_handle",
                action="copy one active game object handle from a Gateway result",
            )
        game_object_id = game_object_binding.get("game_object_id")
        if (
            isinstance(game_object_id, bool)
            or not isinstance(game_object_id, int)
            or not 0 <= game_object_id <= 0xFFFFFFFFFFFFFFDF
        ):
            raise business_repair(
                "GAME_OBJECT_HANDLE_INVALID",
                field="game_object_handle",
                action="bind the active handle again",
            )
        native_args = {"gameObject": game_object_id}
    elif operation == STOP_PLAYING_ID_URI:
        required = {"playing_handle"}
        optional = {"fade_duration_ms", "fade_curve"}
        if not required <= set(plan) or set(plan) - (required | optional):
            raise business_repair(
                "SOUNDENGINE_PLAN_FIELDS_INVALID",
                field="soundengine_plan",
                required=sorted(required),
                optional=sorted(optional),
                action="submit exactly the fields disclosed for this SoundEngine command",
            )
        handle = plan.get("playing_handle")
        if (
            not isinstance(handle, str)
            or not isinstance(playing_binding, Mapping)
            or playing_binding.get("handle") != handle
        ):
            raise business_repair(
                "PLAYING_HANDLE_INVALID",
                field="playing_handle",
                action="copy one active playing handle from a Gateway postEvent result",
            )
        playing_id = playing_binding.get("playing_id")
        if (
            isinstance(playing_id, bool)
            or not isinstance(playing_id, int)
            or not 1 <= playing_id <= 0xFFFFFFFF
        ):
            raise business_repair(
                "PLAYING_HANDLE_INVALID",
                field="playing_handle",
                action="bind the active playing handle again",
            )
        fade_duration_ms = plan.get("fade_duration_ms", 0)
        if (
            isinstance(fade_duration_ms, bool)
            or not isinstance(fade_duration_ms, int)
            or not 0 <= fade_duration_ms <= 0x7FFFFFFF
        ):
            raise business_repair(
                "BUSINESS_VALUE_INVALID",
                field="fade_duration_ms",
                action="provide a whole millisecond duration from 0 through 2147483647",
            )
        fade_curve = plan.get("fade_curve", "Linear")
        if fade_curve not in _FADE_CURVES:
            raise business_repair(
                "BUSINESS_VALUE_INVALID",
                field="fade_curve",
                allowed=list(_FADE_CURVES),
                action="copy one disclosed Wwise fade curve name exactly",
            )
        native_args = {
            "playingId": playing_id,
            "transitionDuration": fade_duration_ms,
            "fadeCurve": _FADE_CURVES[fade_curve],
        }
    else:  # pragma: no cover - contract registry invariant
        raise ValueError("unsupported SoundEngine business operation")
    return parse_operation_request(
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": session.context.wwise_version,
            "operation": "waapi.call",
            "arguments": {
                "api": operation,
                "args": native_args,
                "options": {},
            },
        },
        expected_version=session.context.wwise_version,
    ).as_dict()


__all__ = ["materialize_soundengine_control_business_request"]
