"""Compact CLI envelope for exact tabular and Lua artifact plans."""

from __future__ import annotations

import argparse
import json
import math
from typing import Any


class ExactArtifactBusinessCliError(ValueError):
    """One complete exact-artifact declaration is malformed."""


def add_exact_artifact_plan_arguments(parser: argparse.ArgumentParser) -> None:
    """Attach all closed high-level flags to the shared declaration command."""

    parser.add_argument("--table-file")
    parser.add_argument("--location-handle")
    parser.add_argument("--language")
    parser.add_argument("--mode", choices=("create", "reimport", "replace"))
    add_source_control = parser.add_mutually_exclusive_group()
    add_source_control.add_argument(
        "--add-to-source-control",
        dest="add_to_source_control",
        action="store_true",
    )
    add_source_control.add_argument(
        "--no-add-to-source-control",
        dest="add_to_source_control",
        action="store_false",
    )
    check_out = parser.add_mutually_exclusive_group()
    check_out.add_argument(
        "--check-out-from-source-control",
        dest="check_out_from_source_control",
        action="store_true",
    )
    check_out.add_argument(
        "--no-check-out-from-source-control",
        dest="check_out_from_source_control",
        action="store_false",
    )
    parser.set_defaults(
        add_to_source_control=None,
        check_out_from_source_control=None,
    )
    parser.add_argument("--script-file")
    parser.add_argument("--lua-source")
    parser.add_argument("--io-root")
    parser.add_argument(
        "--argument",
        action="append",
        nargs=3,
        default=[],
        metavar=("KEY", "TYPE", "VALUE"),
    )
    parser.add_argument("--watchdog-seconds", type=int)


def exact_artifact_plan_from_namespace(
    args: argparse.Namespace,
    *,
    operation: str,
) -> dict[str, Any]:
    """Build one operation-specific plan without exposing native loader keys."""

    all_fields = {
        "table_file",
        "location_handle",
        "language",
        "mode",
        "add_to_source_control",
        "check_out_from_source_control",
        "script_file",
        "lua_source",
        "io_root",
        "argument",
        "watchdog_seconds",
    }
    allowed = {
        "audio.importTabDelimited": {
            "table_file",
            "location_handle",
            "language",
            "mode",
            "add_to_source_control",
            "check_out_from_source_control",
        },
        "lua.executeCliFile": {
            "script_file",
            "argument",
            "watchdog_seconds",
        },
        "lua.executeCoreFile": {"script_file", "argument"},
        "lua.executeCoreInline": {
            "lua_source",
            "io_root",
            "argument",
        },
    }.get(operation)
    if allowed is None:
        raise ExactArtifactBusinessCliError(
            "unsupported exact-artifact operation"
        )

    def supplied(name: str) -> bool:
        value = getattr(args, name)
        return value is not None and value != []

    unexpected = sorted(name for name in all_fields - allowed if supplied(name))
    if unexpected:
        raise ExactArtifactBusinessCliError(
            f"{operation} does not accept {unexpected[0].replace('_', '-')}"
        )

    arguments = {}
    for key, value_type, raw_value in args.argument:
        if key in arguments:
            raise ExactArtifactBusinessCliError(
                "one Lua argument key was supplied twice"
            )
        arguments[key] = _typed_value(value_type, raw_value)

    if operation == "audio.importTabDelimited":
        plan: dict[str, Any] = {
            "table_file": args.table_file,
            "location_handle": args.location_handle,
            "language": args.language,
        }
        for field in (
            "mode",
            "add_to_source_control",
            "check_out_from_source_control",
        ):
            value = getattr(args, field)
            if value is not None:
                plan[field] = value
        return plan
    if operation in {"lua.executeCliFile", "lua.executeCoreFile"}:
        plan = {"script_file": args.script_file}
    else:
        plan = {"lua_source": args.lua_source, "io_root": args.io_root}
    if arguments:
        plan["arguments"] = arguments
    if args.watchdog_seconds is not None:
        plan["watchdog_seconds"] = args.watchdog_seconds
    return plan


def _typed_value(value_type: str, raw_value: str) -> Any:
    if value_type == "string":
        return raw_value
    try:
        value = json.loads(raw_value)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ExactArtifactBusinessCliError(
            "Lua argument values must use string or strict JSON syntax"
        ) from exc
    if value_type == "boolean" and type(value) is not bool:
        raise ExactArtifactBusinessCliError("boolean argument must be true or false")
    if value_type == "integer" and (
        isinstance(value, bool) or not isinstance(value, int)
    ):
        raise ExactArtifactBusinessCliError("integer argument must be a JSON integer")
    if value_type == "number" and (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or isinstance(value, float)
        and not math.isfinite(value)
    ):
        raise ExactArtifactBusinessCliError("number argument must be finite")
    if value_type == "json" and not isinstance(value, (dict, list)):
        raise ExactArtifactBusinessCliError(
            "json argument must be one object or array"
        )
    if value_type == "null" and value is not None:
        raise ExactArtifactBusinessCliError("null argument must be null")
    if value_type not in {"boolean", "integer", "number", "json", "null"}:
        raise ExactArtifactBusinessCliError(
            "argument type must be string, boolean, integer, number, json, or null"
        )
    return value


__all__ = [
    "ExactArtifactBusinessCliError",
    "add_exact_artifact_plan_arguments",
    "exact_artifact_plan_from_namespace",
]
