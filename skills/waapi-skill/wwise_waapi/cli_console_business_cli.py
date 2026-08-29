"""Compact argv envelope for complete CLI/Console business plans."""

from __future__ import annotations

import argparse
from typing import Any

from .cli_console_business_contracts import cli_console_business_contract_data


class CliConsoleBusinessCliError(ValueError):
    """One CLI/Console declaration does not match its disclosed contract."""


def add_cli_console_plan_arguments(parser: argparse.ArgumentParser) -> None:
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


def cli_console_plan_from_namespace(
    args: argparse.Namespace,
    *,
    operation: str,
    version: str,
) -> dict[str, Any]:
    contract = cli_console_business_contract_data(operation, version)
    field_types = contract["declaration"]["field_types"]
    result: dict[str, Any] = {}

    def field_type(name: str) -> str:
        try:
            return str(field_types[name])
        except KeyError as exc:
            raise CliConsoleBusinessCliError(
                f"{name} is not disclosed for {operation} in Wwise {version}"
            ) from exc

    def put(name: str, value: Any) -> None:
        if name in result:
            raise CliConsoleBusinessCliError(f"{name} was supplied twice")
        result[name] = value

    scalar_types = {
        "exact_project_file",
        "exact_file",
        "exact_output_file",
        "exact_directory",
        "exact_or_relative_output_directory",
        "installed_base_platform_name",
        "new_platform_name",
        "existing_platform_name",
        "console_verbosity",
        "source_control_policy",
        "wwise_dat_policy",
        "decoded_media_policy",
        "dump_content",
        "import_mode",
        "language_name",
        "exact_license_text",
        "migration_policy",
        "nonnegative_integer",
        "port_0_through_65535",
        "client_count_0_through_100",
    }
    list_types = {
        "platform_name_list",
        "language_name_list",
        "exact_file_list",
        "soundbank_name_or_exact_file_list",
        "network_address_list",
        "http_origin_list",
    }
    mapping_types = {
        "platform_file_mappings",
        "platform_directory_mappings",
        "platform_exact_or_relative_directory_mappings",
        "platform_creation_mappings",
    }
    for name, raw in args.value:
        value_type = field_type(name)
        if value_type not in scalar_types:
            raise CliConsoleBusinessCliError(
                f"{name} does not use the --value input form"
            )
        value: Any = raw
        if value_type in {
            "nonnegative_integer",
            "port_0_through_65535",
            "client_count_0_through_100",
        }:
            try:
                value = int(raw)
            except ValueError as exc:
                raise CliConsoleBusinessCliError(
                    f"{name} requires one whole number"
                ) from exc
            if str(value) != raw and not (value == 0 and raw == "-0"):
                raise CliConsoleBusinessCliError(
                    f"{name} requires one canonical whole number"
                )
        put(name, value)
    for name, value in args.item:
        if field_type(name) not in list_types:
            raise CliConsoleBusinessCliError(
                f"{name} does not use the --item input form"
            )
        current = result.setdefault(name, [])
        if not isinstance(current, list):
            raise CliConsoleBusinessCliError(f"{name} uses conflicting input forms")
        current.append(value)
    for name, key, value in args.mapping:
        if field_type(name) not in mapping_types:
            raise CliConsoleBusinessCliError(
                f"{name} does not use the --mapping input form"
            )
        current = result.setdefault(name, [])
        if not isinstance(current, list):
            raise CliConsoleBusinessCliError(f"{name} uses conflicting input forms")
        current.append([key, value])
    for name, raw in args.toggle:
        if field_type(name) != "boolean":
            raise CliConsoleBusinessCliError(
                f"{name} does not use the --toggle input form"
            )
        if raw not in {"enable", "disable"}:
            raise CliConsoleBusinessCliError(
                f"{name} toggle requires enable or disable"
            )
        put(name, raw == "enable")
    return result


__all__ = [
    "CliConsoleBusinessCliError",
    "add_cli_console_plan_arguments",
    "cli_console_plan_from_namespace",
]
