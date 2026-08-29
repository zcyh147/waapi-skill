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
    SET_STATE_URI,
    SET_SWITCH_URI,
    SET_GAME_PARAMETER_URI,
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
