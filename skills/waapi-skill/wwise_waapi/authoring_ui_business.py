"""Compile Authoring UI business declarations into canonical requests."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from .authoring_ui_business_contracts import AUTHORING_UI_BUSINESS_OPERATIONS
from .business_declaration_state import BusinessDeclarationSession
from .business_declarations import business_repair
from .operation_ui_commands import (
    MAX_ARGUMENT_TOKEN_CHARS,
    MAX_ARGUMENT_TOKENS,
    MAX_COMMAND_FILES,
    MAX_COMMAND_ID_CHARS,
    MAX_COMMANDS_PER_PLAN,
    MAX_DEFAULT_SHORTCUT_CHARS,
    MAX_DISPLAY_NAME_CHARS,
    MAX_LUA_MODULE_DIRECTORIES,
    MAX_LUA_SELECTED_RETURN_CHARS,
    MAX_LUA_SELECTED_RETURN_FIELDS,
    MAX_MENU_SEGMENT_CHARS,
    MAX_MENU_SEGMENTS,
    MAX_OBJECT_ARGUMENTS,
    MAX_OBJECT_ARGUMENT_CHARS,
    MAX_OBJECT_TYPES,
    MAX_OBJECT_TYPE_CHARS,
    MAX_PATH_CHARS,
    MAX_PLATFORM_ARGUMENTS,
    MAX_PLATFORM_ARGUMENT_CHARS,
    START_MODES,
    UNREGISTER_EXISTING_ACKNOWLEDGEMENT,
    USER_SUPPLIED_SOURCE_AUTHORITY,
)


def authoring_ui_business_is_complete(
    operation: str,
    session: BusinessDeclarationSession,
) -> bool:
    if set(session.settings) != {"ui_plan"}:
        return False
    plan = session.settings.get("ui_plan")
    if not isinstance(plan, Mapping):
        return False
    if operation != "ui.commands.register":
        return True
    expected = plan.get("command_count")
    commands = plan.get("commands")
    return (
        type(expected) is int
        and isinstance(commands, list)
        and expected == len(commands)
    )


def materialize_authoring_ui_business_request(
    operation: str,
    session: BusinessDeclarationSession,
) -> Mapping[str, Any]:
    if operation not in AUTHORING_UI_BUSINESS_OPERATIONS:
        raise ValueError("unsupported Authoring UI business operation")
    if not isinstance(session, BusinessDeclarationSession):
        raise TypeError("session must be BusinessDeclarationSession")
    if set(session.settings) != {"ui_plan"}:
        raise _repair(session, "BUSINESS_DECLARATION_INCOMPLETE", "ui_plan")
    raw = session.settings["ui_plan"]
    if not isinstance(raw, Mapping):
        raise _repair(session, "INVALID_ARGUMENT", "ui_plan")
    plan = dict(raw)
    if operation == "ui.captureScreen":
        arguments = _capture_arguments(session, plan)
    elif operation == "ui.commands.execute":
        arguments = _execute_arguments(session, plan)
    elif operation == "ui.commands.register":
        arguments = _register_arguments(session, plan)
    else:
        arguments = _unregister_arguments(session, plan)
    return {
        "contract": "waapi-skill.operation-request/v1",
        "version": session.context.wwise_version,
        "operation": operation,
        "arguments": arguments,
    }


def append_authoring_ui_command(
    session: BusinessDeclarationSession,
    command: Mapping[str, Any],
) -> BusinessDeclarationSession:
    raw = session.settings.get("ui_plan")
    if not isinstance(raw, Mapping):
        raise _repair(session, "BUSINESS_DECLARATION_INCOMPLETE", "ui_plan")
    plan = dict(raw)
    expected = plan.get("command_count")
    commands = plan.get("commands")
    if (
        type(expected) is not int
        or not 1 <= expected <= MAX_COMMANDS_PER_PLAN
        or not isinstance(commands, list)
        or len(commands) >= expected
    ):
        raise _repair(session, "BUSINESS_DECLARATION_COMPLETE", "commands")
    candidate = [*commands, dict(command)]
    keys = [row.get("key") for row in candidate if isinstance(row, Mapping)]
    if len(keys) != len(candidate) or any(not isinstance(key, str) for key in keys):
        raise _repair(session, "INVALID_ARGUMENT", "commands[].key")
    if len({str(key).casefold() for key in keys}) != len(keys):
        raise _repair(session, "DUPLICATE_BUSINESS_KEY", "commands[].key")
    candidate_session = session.with_settings(
        {"ui_plan": {**plan, "commands": candidate}}
    )
    validate_authoring_ui_business_session(
        "ui.commands.register",
        candidate_session,
    )
    return candidate_session


def validate_authoring_ui_business_session(
    operation: str,
    session: BusinessDeclarationSession,
) -> None:
    """Validate one complete plan or one bounded registration prefix."""

    if operation != "ui.commands.register":
        materialize_authoring_ui_business_request(operation, session)
        return
    raw = session.settings.get("ui_plan")
    if not isinstance(raw, Mapping):
        raise _repair(session, "BUSINESS_DECLARATION_INCOMPLETE", "ui_plan")
    plan = dict(raw)
    _exact_fields(
        session,
        plan,
        allowed={"command_count", "commands"},
        required={"command_count", "commands"},
    )
    expected = plan["command_count"]
    commands = plan["commands"]
    if (
        type(expected) is not int
        or not 1 <= expected <= MAX_COMMANDS_PER_PLAN
        or not isinstance(commands, list)
        or len(commands) > expected
    ):
        raise _repair(session, "INVALID_ARGUMENT", "commands")
    _registration_commands(session, commands)


def _capture_arguments(
    session: BusinessDeclarationSession,
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    allowed = {"view_name", "view_channel", "rectangle"}
    _exact_fields(session, plan, allowed=allowed)
    result: dict[str, Any] = {}
    if "view_name" in plan:
        result["view_name"] = _text(session, plan["view_name"], "view_name")
    if "view_channel" in plan:
        channel = plan["view_channel"]
        if type(channel) is not int or channel not in {1, 2, 3, 4}:
            raise _repair(session, "INVALID_ARGUMENT", "view_channel")
        result["view_channel"] = channel
    if "rectangle" in plan:
        rect = plan["rectangle"]
        if not isinstance(rect, Mapping) or set(rect) != {"x", "y", "width", "height"}:
            raise _repair(session, "INVALID_ARGUMENT", "rectangle")
        values: dict[str, int] = {}
        for field in ("x", "y", "width", "height"):
            value = rect[field]
            minimum = 1 if field in {"width", "height"} else 0
            if type(value) is not int or value < minimum:
                raise _repair(session, "INVALID_ARGUMENT", f"rectangle.{field}")
            values[field] = value
        result["rect"] = values
    return result


def _execute_arguments(
    session: BusinessDeclarationSession,
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    allowed = {"command_id", "objects", "platforms", "value", "files"}
    _exact_fields(session, plan, allowed=allowed, required={"command_id"})
    result: dict[str, Any] = {
        "command": _text(
            session,
            plan["command_id"],
            "command_id",
            maximum=MAX_COMMAND_ID_CHARS,
        )
    }
    limits = {
        "objects": (MAX_OBJECT_ARGUMENTS, MAX_OBJECT_ARGUMENT_CHARS),
        "platforms": (
            MAX_PLATFORM_ARGUMENTS,
            MAX_PLATFORM_ARGUMENT_CHARS,
        ),
        "files": (MAX_COMMAND_FILES, MAX_PATH_CHARS),
    }
    for field, (limit, maximum) in limits.items():
        if field not in plan:
            continue
        if field == "files" and session.context.wwise_version != "2025.1":
            raise _repair(session, "VERSION_BEHAVIOR_BOUNDARY", field)
        result[field] = _strings(
            session,
            plan[field],
            field,
            limit=limit,
            maximum=maximum,
        )
    if "value" in plan:
        value = plan["value"]
        if value is not None and type(value) not in {str, bool, int, float}:
            raise _repair(session, "INVALID_ARGUMENT", "value")
        try:
            json.dumps(value, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise _repair(session, "INVALID_ARGUMENT", "value") from exc
        result["value"] = value
    return result


def _register_arguments(
    session: BusinessDeclarationSession,
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    _exact_fields(
        session,
        plan,
        allowed={"command_count", "commands"},
        required={"command_count", "commands"},
    )
    expected = plan["command_count"]
    commands = plan["commands"]
    if (
        type(expected) is not int
        or not 1 <= expected <= MAX_COMMANDS_PER_PLAN
        or not isinstance(commands, list)
        or len(commands) != expected
    ):
        raise _repair(session, "BUSINESS_DECLARATION_INCOMPLETE", "commands")
    native, exact_paths = _registration_commands(session, commands)
    result: dict[str, Any] = {"commands": native}
    if exact_paths:
        result["source_authority"] = USER_SUPPLIED_SOURCE_AUTHORITY
    return result


def _registration_commands(
    session: BusinessDeclarationSession,
    commands: Sequence[Any],
) -> tuple[list[dict[str, Any]], bool]:
    native: list[dict[str, Any]] = []
    exact_paths = False
    keys: set[str] = set()
    for index, raw in enumerate(commands):
        if not isinstance(raw, Mapping):
            raise _repair(session, "INVALID_ARGUMENT", f"commands[{index}]")
        row = dict(raw)
        _exact_fields(
            session,
            row,
            allowed={
                "key",
                "display_name",
                "handler",
                "default_shortcut",
                "context_menu",
                "main_menu",
            },
            required={"key", "display_name", "handler"},
        )
        key = _text(session, row["key"], f"commands[{index}].key", maximum=128)
        folded = key.casefold()
        if folded in keys:
            raise _repair(session, "DUPLICATE_BUSINESS_KEY", f"commands[{index}].key")
        keys.add(folded)
        handler = _handler(session, row["handler"], index=index)
        exact_paths = exact_paths or handler["kind"] in {"program", "lua_script"}
        item: dict[str, Any] = {
            "id": authoring_ui_command_id(session, key),
            "display_name": _text(
                session,
                row["display_name"],
                f"commands[{index}].display_name",
                maximum=MAX_DISPLAY_NAME_CHARS,
            ),
            "handler": handler,
        }
        if "default_shortcut" in row:
            item["default_shortcut"] = _text(
                session,
                row["default_shortcut"],
                f"commands[{index}].default_shortcut",
                maximum=MAX_DEFAULT_SHORTCUT_CHARS,
                allow_empty=True,
            )
        if "context_menu" in row:
            item["context_menu"] = _context_menu(
                session,
                row["context_menu"],
                index=index,
            )
        if "main_menu" in row:
            item["main_menu"] = _main_menu(
                session,
                row["main_menu"],
                index=index,
            )
        native.append(item)
    return native, exact_paths


def _unregister_arguments(
    session: BusinessDeclarationSession,
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    allowed = {
        "registered_command_keys",
        "existing_command_ids",
        "confirm_unknown_ownership",
    }
    _exact_fields(session, plan, allowed=allowed)
    if "registered_command_keys" in plan:
        if set(plan) != {"registered_command_keys"}:
            raise _repair(session, "INVALID_ARGUMENT", "ui_plan")
        ids = [
            authoring_ui_command_id(session, key)
            for key in _strings(
                session,
                plan["registered_command_keys"],
                "registered_command_keys",
                limit=MAX_COMMANDS_PER_PLAN,
                maximum=128,
            )
        ]
    else:
        if set(plan) != {"existing_command_ids", "confirm_unknown_ownership"}:
            raise _repair(session, "INVALID_ARGUMENT", "ui_plan")
        if plan["confirm_unknown_ownership"] is not True:
            raise _repair(session, "EXPLICIT_CONFIRMATION_REQUIRED", "confirm_unknown_ownership")
        ids = _strings(
            session,
            plan["existing_command_ids"],
            "existing_command_ids",
            limit=MAX_COMMANDS_PER_PLAN,
            maximum=MAX_COMMAND_ID_CHARS,
        )
    return {
        "command_ids": ids,
        "acknowledgement": UNREGISTER_EXISTING_ACKNOWLEDGEMENT,
    }


def _handler(
    session: BusinessDeclarationSession,
    raw: Any,
    *,
    index: int,
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise _repair(session, "INVALID_ARGUMENT", f"commands[{index}].handler")
    handler = dict(raw)
    kind = handler.get("kind")
    allowed_by_kind = {
        "notification": {"kind"},
        "program": {
            "kind",
            "program_path",
            "argument_tokens",
            "working_directory",
            "start_mode",
            "redirect_outputs",
        },
        "lua_script": {
            "kind",
            "lua_script_path",
            "argument_tokens",
            "working_directory",
            "start_mode",
            "lua_module_directories",
            "lua_selected_return",
        },
    }
    required_by_kind = {
        "notification": {"kind"},
        "program": {"kind", "program_path"},
        "lua_script": {"kind", "lua_script_path"},
    }
    if kind not in allowed_by_kind:
        raise _repair(session, "INVALID_ARGUMENT", f"commands[{index}].handler.kind")
    if kind == "lua_script" and session.context.wwise_version in {"2021.1", "2022.1"}:
        raise _repair(session, "VERSION_BEHAVIOR_BOUNDARY", f"commands[{index}].handler.kind")
    _exact_fields(
        session,
        handler,
        allowed=allowed_by_kind[str(kind)],
        required=required_by_kind[str(kind)],
    )
    result = dict(handler)
    if kind in {"program", "lua_script"}:
        path_field = "program_path" if kind == "program" else "lua_script_path"
        result[path_field] = _text(
            session,
            handler[path_field],
            f"commands[{index}].handler.{path_field}",
            maximum=MAX_PATH_CHARS,
        )
        tokens = _strings(
            session,
            handler.get("argument_tokens", []),
            f"commands[{index}].handler.argument_tokens",
            limit=MAX_ARGUMENT_TOKENS,
            maximum=MAX_ARGUMENT_TOKEN_CHARS,
            allow_empty=True,
            allow_duplicates=True,
            allow_empty_items=True,
        )
        if kind == "program" and tokens:
            raise _repair(
                session,
                "PROGRAM_ARGUMENTS_UNSUPPORTED",
                f"commands[{index}].handler.argument_tokens",
            )
        result["argument_tokens"] = tokens
        start_mode = handler.get(
            "start_mode",
            "SingleSelectionSingleProcess",
        )
        if start_mode not in START_MODES:
            raise _repair(
                session,
                "INVALID_ARGUMENT",
                f"commands[{index}].handler.start_mode",
            )
        result["start_mode"] = start_mode
        if "working_directory" in handler:
            result["working_directory"] = _text(
                session,
                handler["working_directory"],
                f"commands[{index}].handler.working_directory",
                maximum=MAX_PATH_CHARS,
            )
    if kind == "program":
        redirect = handler.get("redirect_outputs", False)
        if type(redirect) is not bool:
            raise _repair(
                session,
                "INVALID_ARGUMENT",
                f"commands[{index}].handler.redirect_outputs",
            )
        result["redirect_outputs"] = redirect
    if kind == "lua_script":
        result["lua_module_directories"] = _strings(
            session,
            handler.get("lua_module_directories", []),
            f"commands[{index}].handler.lua_module_directories",
            limit=MAX_LUA_MODULE_DIRECTORIES,
            maximum=MAX_PATH_CHARS,
            allow_empty=True,
        )
        result["lua_selected_return"] = _strings(
            session,
            handler.get("lua_selected_return", []),
            f"commands[{index}].handler.lua_selected_return",
            limit=MAX_LUA_SELECTED_RETURN_FIELDS,
            maximum=MAX_LUA_SELECTED_RETURN_CHARS,
            allow_empty=True,
        )
    return result


def _context_menu(
    session: BusinessDeclarationSession,
    raw: Any,
    *,
    index: int,
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise _repair(session, "INVALID_ARGUMENT", f"commands[{index}].context_menu")
    value = dict(raw)
    _exact_fields(
        session,
        value,
        allowed={"base_path", "visible_for", "enabled_for"},
    )
    result: dict[str, Any] = {}
    if "base_path" in value:
        result["base_path"] = _menu_segments(
            session,
            value["base_path"],
            f"commands[{index}].context_menu.base_path",
            allow_empty=True,
        )
    for field in ("visible_for", "enabled_for"):
        if field in value:
            rows = _strings(
                session,
                value[field],
                f"commands[{index}].context_menu.{field}",
                limit=MAX_OBJECT_TYPES,
                maximum=MAX_OBJECT_TYPE_CHARS,
                allow_empty=True,
            )
            if any("," in row for row in rows):
                raise _repair(
                    session,
                    "INVALID_ARGUMENT",
                    f"commands[{index}].context_menu.{field}",
                )
            result[field] = rows
    return result


def _main_menu(
    session: BusinessDeclarationSession,
    raw: Any,
    *,
    index: int,
) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != {"base_path"}:
        raise _repair(session, "INVALID_ARGUMENT", f"commands[{index}].main_menu")
    return {
        "base_path": _menu_segments(
            session,
            raw["base_path"],
            f"commands[{index}].main_menu.base_path",
            allow_empty=False,
        )
    }


def _menu_segments(
    session: BusinessDeclarationSession,
    raw: Any,
    field: str,
    *,
    allow_empty: bool,
) -> list[str]:
    rows = _strings(
        session,
        raw,
        field,
        limit=MAX_MENU_SEGMENTS,
        maximum=MAX_MENU_SEGMENT_CHARS,
        allow_empty=allow_empty,
        allow_duplicates=True,
    )
    if any("/" in row or "\\" in row for row in rows):
        raise _repair(session, "INVALID_ARGUMENT", field)
    return rows


def authoring_ui_command_id(
    session: BusinessDeclarationSession,
    key: str,
) -> str:
    normalized = _text(session, key, "command_key", maximum=128)
    slug = re.sub(r"[^a-z0-9]+", ".", normalized.casefold()).strip(".")
    if not slug:
        slug = "command"
    slug = slug[:48].rstrip(".")
    digest = hashlib.sha256(
        f"{session.context.project_id}\0{normalized.casefold()}".encode("utf-8")
    ).hexdigest()[:16]
    return f"waapi.skill.{slug}.{digest}"


def _exact_fields(
    session: BusinessDeclarationSession,
    value: Mapping[str, Any],
    *,
    allowed: set[str],
    required: set[str] | None = None,
) -> None:
    missing = set(required or ()) - set(value)
    unexpected = set(value) - allowed
    if missing or unexpected:
        raise business_repair(
            "INVALID_ARGUMENT",
            field="ui_plan",
            draft_revision=session.revision,
            action="use exactly the disclosed Authoring UI business fields",
            missing_fields=sorted(missing),
            unexpected_fields=sorted(unexpected),
        )


def _text(
    session: BusinessDeclarationSession,
    value: Any,
    field: str,
    *,
    maximum: int = 4096,
    allow_empty: bool = False,
) -> str:
    if (
        not isinstance(value, str)
        or not allow_empty and not value
        or value != value.strip()
        or len(value) > maximum
    ):
        raise _repair(session, "INVALID_ARGUMENT", field)
    return value


def _strings(
    session: BusinessDeclarationSession,
    value: Any,
    field: str,
    *,
    limit: int = 64,
    maximum: int = 4096,
    allow_empty: bool = False,
    allow_duplicates: bool = False,
    allow_empty_items: bool = False,
) -> list[str]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) > limit
        or not allow_empty and not value
    ):
        raise _repair(session, "INVALID_ARGUMENT", field)
    rows = [
        _text(
            session,
            row,
            field,
            maximum=maximum,
            allow_empty=allow_empty_items,
        )
        for row in value
    ]
    if not allow_duplicates and len({row.casefold() for row in rows}) != len(rows):
        raise _repair(session, "DUPLICATE_ARGUMENT", field)
    return rows


def _repair(
    session: BusinessDeclarationSession,
    error_code: str,
    field: str,
):
    return business_repair(
        error_code,
        field=field,
        draft_revision=session.revision,
        action="correct the closed Authoring UI business declaration",
    )


__all__ = [
    "append_authoring_ui_command",
    "authoring_ui_business_is_complete",
    "authoring_ui_command_id",
    "materialize_authoring_ui_business_request",
    "validate_authoring_ui_business_session",
]
