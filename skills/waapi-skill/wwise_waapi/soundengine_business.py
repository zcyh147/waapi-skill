"""Compile closed SoundEngine business declarations into native requests."""

from __future__ import annotations

from typing import Any, Mapping

from .business_declaration_state import BusinessDeclarationSession
from .business_declarations import business_repair
from .canonical import canonical_sha256
from .operation_registry import parse_operation_request
from .soundengine_business_contracts import (
    EXECUTE_ACTION_ON_EVENT_URI,
    POST_MONITOR_MESSAGE_URI,
    POST_EVENT_URI,
    REGISTER_GAME_OBJECT_URI,
    STOP_ALL_URI,
    STOP_PLAYING_ID_URI,
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
        "runtime_playing_binding",
    } or "soundengine_plan" not in session.settings:
        raise business_repair(
            "SOUNDENGINE_PLAN_INCOMPLETE",
            field="soundengine_plan",
            action="submit the one complete Gateway-disclosed SoundEngine plan",
        )
    plan = session.settings["soundengine_plan"]
    game_object_binding = session.settings.get("runtime_game_object_binding")
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
