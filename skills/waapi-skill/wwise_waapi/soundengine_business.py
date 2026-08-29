"""Compile closed SoundEngine business declarations into native requests."""

from __future__ import annotations

from typing import Any, Mapping

from .business_declaration_state import BusinessDeclarationSession
from .business_declarations import business_repair
from .canonical import canonical_sha256
from .operation_registry import parse_operation_request
from .soundengine_business_contracts import (
    POST_MONITOR_MESSAGE_URI,
    POST_EVENT_URI,
    REGISTER_GAME_OBJECT_URI,
    UNREGISTER_GAME_OBJECT_URI,
    soundengine_control_business_contract_data,
)


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
    allowed_setting_sets = (
        {"soundengine_plan"},
        {"soundengine_plan", "runtime_game_object_binding"},
    )
    if set(session.settings) not in allowed_setting_sets:
        raise business_repair(
            "SOUNDENGINE_PLAN_INCOMPLETE",
            field="soundengine_plan",
            action="submit the one complete Gateway-disclosed SoundEngine plan",
        )
    plan = session.settings["soundengine_plan"]
    game_object_binding = session.settings.get("runtime_game_object_binding")
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
