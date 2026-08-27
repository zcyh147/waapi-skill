"""CLI parsing for closed Authoring UI business declarations."""

from __future__ import annotations

import argparse
import json
import math
from typing import Any


class AuthoringUiBusinessCliError(ValueError):
    pass


def add_authoring_ui_plan_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--command-count", type=int)
    parser.add_argument("--view-name")
    parser.add_argument("--view-channel", type=int)
    parser.add_argument("--rect", nargs=4, type=int, metavar=("X", "Y", "WIDTH", "HEIGHT"))
    parser.add_argument("--command-id")
    parser.add_argument("--command-object", action="append", default=[])
    parser.add_argument("--command-platform", action="append", default=[])
    parser.add_argument("--command-file", action="append", default=[])
    parser.add_argument("--value", nargs=2, metavar=("TYPE", "VALUE"))
    parser.add_argument("--registered-command-key", action="append", default=[])
    parser.add_argument("--existing-command-id", action="append", default=[])
    parser.add_argument("--confirm-unknown-ownership", action="store_true")


def add_authoring_ui_command_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--key", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument(
        "--handler-kind",
        required=True,
        choices=("notification", "program", "lua_script"),
    )
    parser.add_argument("--handler-path")
    parser.add_argument("--argument-token", action="append", default=[])
    parser.add_argument("--working-directory")
    parser.add_argument("--start-mode")
    parser.add_argument("--redirect-outputs", action="store_true")
    parser.add_argument("--lua-module-directory", action="append", default=[])
    parser.add_argument("--lua-selected-return", action="append", default=[])
    parser.add_argument("--default-shortcut")
    parser.add_argument("--context-menu-segment", action="append", default=[])
    parser.add_argument("--context-visible-for", action="append", default=[])
    parser.add_argument("--context-enabled-for", action="append", default=[])
    parser.add_argument("--main-menu-segment", action="append", default=[])


def authoring_ui_plan_from_namespace(
    args: argparse.Namespace,
    *,
    operation: str,
) -> dict[str, Any]:
    if operation == "ui.captureScreen":
        plan: dict[str, Any] = {}
        if args.view_name is not None:
            plan["view_name"] = args.view_name
        if args.view_channel is not None:
            plan["view_channel"] = args.view_channel
        if args.rect is not None:
            plan["rectangle"] = dict(zip(("x", "y", "width", "height"), args.rect))
        _forbid(args, operation, {"view_name", "view_channel", "rect"})
        return plan
    if operation == "ui.commands.execute":
        if args.command_id is None:
            raise AuthoringUiBusinessCliError("execute requires --command-id")
        plan = {"command_id": args.command_id}
        for attribute, field in (
            ("command_object", "objects"),
            ("command_platform", "platforms"),
            ("command_file", "files"),
        ):
            values = getattr(args, attribute)
            if values:
                plan[field] = values
        if args.value is not None:
            plan["value"] = _typed_value(*args.value)
        _forbid(
            args,
            operation,
            {"command_id", "command_object", "command_platform", "command_file", "value"},
        )
        return plan
    if operation == "ui.commands.register":
        if args.command_count is None:
            raise AuthoringUiBusinessCliError("register requires --command-count")
        _forbid(args, operation, {"command_count"})
        return {"command_count": args.command_count, "commands": []}
    registered = list(args.registered_command_key)
    existing = list(args.existing_command_id)
    if bool(registered) == bool(existing):
        raise AuthoringUiBusinessCliError(
            "unregister requires exactly one registered-key or existing-ID mode"
        )
    if registered:
        if args.confirm_unknown_ownership:
            raise AuthoringUiBusinessCliError(
                "registered-key mode does not accept unknown-ownership confirmation"
            )
        plan = {"registered_command_keys": registered}
    else:
        if not args.confirm_unknown_ownership:
            raise AuthoringUiBusinessCliError(
                "existing-ID mode requires --confirm-unknown-ownership"
            )
        plan = {
            "existing_command_ids": existing,
            "confirm_unknown_ownership": True,
        }
    _forbid(
        args,
        operation,
        {"registered_command_key", "existing_command_id", "confirm_unknown_ownership"},
    )
    return plan


def authoring_ui_command_from_namespace(args: argparse.Namespace) -> dict[str, Any]:
    kind = args.handler_kind
    if kind == "notification":
        if args.handler_path is not None:
            raise AuthoringUiBusinessCliError(
                "notification handlers do not accept --handler-path"
            )
        handler: dict[str, Any] = {"kind": kind}
    else:
        if args.handler_path is None:
            raise AuthoringUiBusinessCliError(
                f"{kind} handlers require --handler-path"
            )
        handler = {
            "kind": kind,
            "program_path" if kind == "program" else "lua_script_path": args.handler_path,
        }
        if kind == "lua_script" and args.argument_token:
            handler["argument_tokens"] = list(args.argument_token)
        if args.working_directory is not None:
            handler["working_directory"] = args.working_directory
        if args.start_mode is not None:
            handler["start_mode"] = args.start_mode
        if kind == "program" and args.redirect_outputs:
            handler["redirect_outputs"] = True
        if kind == "lua_script":
            if args.lua_module_directory:
                handler["lua_module_directories"] = list(args.lua_module_directory)
            if args.lua_selected_return:
                handler["lua_selected_return"] = list(args.lua_selected_return)
    if kind != "program" and args.redirect_outputs:
        raise AuthoringUiBusinessCliError(
            "--redirect-outputs is available only for program handlers"
        )
    if kind != "lua_script" and args.argument_token:
        raise AuthoringUiBusinessCliError(
            "--argument-token is available only for lua_script handlers; "
            "parameterized programs require a dedicated closed adapter"
        )
    if kind != "lua_script" and (
        args.lua_module_directory or args.lua_selected_return
    ):
        raise AuthoringUiBusinessCliError(
            "Lua module/return fields require a lua_script handler"
        )
    command: dict[str, Any] = {
        "key": args.key,
        "display_name": args.display_name,
        "handler": handler,
    }
    if args.default_shortcut is not None:
        command["default_shortcut"] = args.default_shortcut
    if args.context_menu_segment or args.context_visible_for or args.context_enabled_for:
        context: dict[str, Any] = {}
        if args.context_menu_segment:
            context["base_path"] = list(args.context_menu_segment)
        if args.context_visible_for:
            context["visible_for"] = list(args.context_visible_for)
        if args.context_enabled_for:
            context["enabled_for"] = list(args.context_enabled_for)
        command["context_menu"] = context
    if args.main_menu_segment:
        command["main_menu"] = {"base_path": list(args.main_menu_segment)}
    return command


def _typed_value(kind: str, raw: str) -> Any:
    if kind == "string":
        return raw
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AuthoringUiBusinessCliError("command value must be strict JSON") from exc
    if kind == "boolean" and type(value) is not bool:
        raise AuthoringUiBusinessCliError("boolean value must be true or false")
    if kind == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
        raise AuthoringUiBusinessCliError("integer value must be a JSON integer")
    if kind == "number" and (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or isinstance(value, float)
        and not math.isfinite(value)
    ):
        raise AuthoringUiBusinessCliError("number value must be finite")
    if kind == "null" and value is not None:
        raise AuthoringUiBusinessCliError("null value must be null")
    if kind not in {"boolean", "integer", "number", "null"}:
        raise AuthoringUiBusinessCliError(
            "value type must be string, boolean, integer, number, or null"
        )
    return value


def _forbid(
    args: argparse.Namespace,
    operation: str,
    allowed: set[str],
) -> None:
    common = {
        "command_count",
        "view_name",
        "view_channel",
        "rect",
        "command_id",
        "command_object",
        "command_platform",
        "command_file",
        "value",
        "registered_command_key",
        "existing_command_id",
        "confirm_unknown_ownership",
    }
    present = {
        name
        for name in common - allowed
        if getattr(args, name, None) not in (None, [], False)
    }
    if present:
        raise AuthoringUiBusinessCliError(
            f"{operation} does not accept: {', '.join(sorted(present))}"
        )


__all__ = [
    "AuthoringUiBusinessCliError",
    "add_authoring_ui_command_arguments",
    "add_authoring_ui_plan_arguments",
    "authoring_ui_command_from_namespace",
    "authoring_ui_plan_from_namespace",
]
