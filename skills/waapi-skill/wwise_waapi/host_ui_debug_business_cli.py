"""Compact CLI envelope for host/UI/Debug business plans."""

from __future__ import annotations

import argparse
import json
import math
from typing import Any

from .host_ui_debug_business_contracts import host_ui_debug_business_contract_data


class HostUiDebugBusinessCliError(ValueError):
    """One host/UI/Debug declaration does not match its disclosed contract."""


def add_host_ui_debug_plan_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--value",
        action="append",
        nargs=2,
        default=[],
        metavar=("BUSINESS_FIELD", "VALUE"),
    )
    parser.add_argument(
        "--item",
        action="append",
        nargs=2,
        default=[],
        metavar=("BUSINESS_COLLECTION", "VALUE"),
    )
    parser.add_argument(
        "--mapping",
        action="append",
        nargs=3,
        default=[],
        metavar=("BUSINESS_MAPPING", "KEY", "VALUE"),
    )
    parser.add_argument(
        "--toggle",
        action="append",
        nargs=2,
        default=[],
        metavar=("BUSINESS_FIELD", "ENABLE_OR_DISABLE"),
    )
    parser.add_argument(
        "--marker",
        action="append",
        nargs="+",
        default=[],
        metavar="POSITION_SECONDS_OR_EXACT_LABEL",
    )


def host_ui_debug_plan_from_namespace(
    args: argparse.Namespace,
    *,
    operation: str,
    version: str,
) -> dict[str, Any]:
    contract = host_ui_debug_business_contract_data(operation, version)
    field_types = contract["declaration"]["field_types"]
    result: dict[str, Any] = {}

    def field_type(name: str) -> str:
        try:
            return str(field_types[name])
        except KeyError as exc:
            raise HostUiDebugBusinessCliError(
                f"{name} is not disclosed for {operation} in Wwise {version}"
            ) from exc

    def put(name: str, value: Any) -> None:
        if name in result:
            raise HostUiDebugBusinessCliError(f"{name} was supplied twice")
        result[name] = value

    scalar_types = {
        "exact_waapi_uri",
        "exact_wav_file",
        "exact_project_file",
        "waveform",
        "frequency_hz",
        "channel_layout",
        "bit_depth",
        "sample_rate_hz",
        "nonnegative_seconds",
        "sustain_db",
        "project_policy",
    }
    number_types = {
        "frequency_hz",
        "sample_rate_hz",
        "nonnegative_seconds",
        "sustain_db",
    }
    for name, raw in args.value:
        value_type = field_type(name)
        if value_type not in scalar_types:
            raise HostUiDebugBusinessCliError(
                f"{name} does not use the --value input form"
            )
        value: Any = raw
        if value_type in number_types:
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise HostUiDebugBusinessCliError(
                    f"{name} requires one JSON number"
                ) from exc
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise HostUiDebugBusinessCliError(
                    f"{name} requires one finite JSON number"
                )
        put(name, value)
    for name, raw in args.item:
        value_type = field_type(name)
        if value_type not in {"language_name_list", "channel_index_list"}:
            raise HostUiDebugBusinessCliError(
                f"{name} does not use the --item input form"
            )
        value: Any = raw
        if value_type == "channel_index_list":
            try:
                value = int(raw)
            except ValueError as exc:
                raise HostUiDebugBusinessCliError(
                    f"{name} requires whole-number channel indexes"
                ) from exc
            if str(value) != raw and not (value == 0 and raw == "-0"):
                raise HostUiDebugBusinessCliError(
                    f"{name} requires canonical whole-number channel indexes"
                )
        current = result.setdefault(name, [])
        if not isinstance(current, list):
            raise HostUiDebugBusinessCliError(f"{name} uses conflicting input forms")
        current.append(value)
    for name, key, value in args.mapping:
        if field_type(name) != "platform_creation_mappings":
            raise HostUiDebugBusinessCliError(
                f"{name} does not use the --mapping input form"
            )
        current = result.setdefault(name, [])
        if not isinstance(current, list):
            raise HostUiDebugBusinessCliError(f"{name} uses conflicting input forms")
        current.append([key, value])
    for name, raw in args.toggle:
        if field_type(name) != "boolean":
            raise HostUiDebugBusinessCliError(
                f"{name} does not use the --toggle input form"
            )
        if raw not in {"enable", "disable"}:
            raise HostUiDebugBusinessCliError(
                f"{name} toggle requires enable or disable"
            )
        put(name, raw == "enable")
    if args.marker:
        if field_type("markers") != "tone_marker_list":
            raise HostUiDebugBusinessCliError(
                "markers do not use the --marker input form in this version"
            )
        markers: list[dict[str, Any]] = []
        for values in args.marker:
            if len(values) not in {1, 2}:
                raise HostUiDebugBusinessCliError(
                    "--marker requires POSITION_SECONDS and optional one exact label token"
                )
            try:
                position = json.loads(values[0])
            except json.JSONDecodeError as exc:
                raise HostUiDebugBusinessCliError(
                    "--marker position must be one JSON number"
                ) from exc
            if (
                isinstance(position, bool)
                or not isinstance(position, (int, float))
                or not math.isfinite(position)
            ):
                raise HostUiDebugBusinessCliError(
                    "--marker position must be one finite JSON number"
                )
            marker: dict[str, Any] = {"position_seconds": position}
            if len(values) == 2:
                marker["label"] = values[1]
            markers.append(marker)
        put("markers", markers)
    return result


__all__ = [
    "HostUiDebugBusinessCliError",
    "add_host_ui_debug_plan_arguments",
    "host_ui_debug_plan_from_namespace",
]
