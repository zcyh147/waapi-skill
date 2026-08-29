"""Compile high-level CLI/Console intent into one canonical native request."""

from __future__ import annotations

import ntpath
import posixpath
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from .business_declaration_state import BusinessDeclarationSession
from .business_declarations import business_repair
from .canonical import canonical_json_bytes
from .cli_console_business_contracts import (
    CLI_CONSOLE_BUSINESS_OPERATIONS,
    cli_console_business_contract_data,
)
from .operation_registry import parse_operation_request


_IMPORT_MODES = {
    "create": "createNew",
    "reuse": "useExisting",
    "replace": "replaceExisting",
}
_ENUMS = {
    "verbosity": {"normal", "quiet", "verbose"},
    "source_control": {"enabled", "disabled"},
    "wwise_dat": {"write", "omit"},
    "decoded_media": {"write", "omit"},
    "tabular_import_mode": set(_IMPORT_MODES),
    "content": {"names", "property_sets"},
    "migration_policy": {"migrate", "fail"},
}
_LIST_TYPES = {
    "platform_name_list",
    "language_name_list",
    "exact_file_list",
    "soundbank_name_or_exact_file_list",
    "network_address_list",
    "http_origin_list",
}
_MAPPING_TYPES = {
    "platform_file_mappings",
    "platform_directory_mappings",
    "platform_exact_or_relative_directory_mappings",
    "platform_creation_mappings",
}
MAX_CLI_CONSOLE_PLAN_BYTES = 256 * 1024
MAX_CLI_CONSOLE_COLLECTION_ITEMS = 128
MAX_CLI_CONSOLE_PATH_BYTES = 4_096
MAX_CLI_CONSOLE_VALUE_BYTES = 8_192
MAX_CLI_CONSOLE_LICENSE_BYTES = 64 * 1024


def materialize_cli_console_business_request(
    operation: str,
    session: BusinessDeclarationSession,
) -> Mapping[str, Any]:
    """Return one internally validated waapi.call request for a deep plan."""

    if operation not in CLI_CONSOLE_BUSINESS_OPERATIONS:
        raise ValueError("unsupported CLI/Console business operation")
    if not isinstance(session, BusinessDeclarationSession):
        raise TypeError("session must be BusinessDeclarationSession")
    if set(session.settings) != {"cli_console_plan"}:
        raise _repair(
            session,
            "BUSINESS_DECLARATION_INCOMPLETE",
            field="cli_console_plan",
            action="submit one complete disclosed CLI or Console plan",
        )
    raw_plan = session.settings["cli_console_plan"]
    if not isinstance(raw_plan, Mapping):
        raise _repair(
            session,
            "INVALID_ARGUMENT",
            field="cli_console_plan",
            action="submit one structured CLI or Console plan",
        )
    plan = dict(raw_plan)
    try:
        plan_size = len(canonical_json_bytes(plan))
    except (TypeError, ValueError) as exc:
        raise _repair(
            session,
            "INVALID_ARGUMENT",
            field="cli_console_plan",
            action="use one strict JSON business plan",
        ) from exc
    if plan_size > MAX_CLI_CONSOLE_PLAN_BYTES:
        raise _repair(
            session,
            "BUSINESS_PLAN_TOO_LARGE",
            field="cli_console_plan",
            action="split the work into separately previewed bounded operations",
            size_bytes=plan_size,
            limit_bytes=MAX_CLI_CONSOLE_PLAN_BYTES,
        )
    contract = cli_console_business_contract_data(
        operation,
        session.context.wwise_version,
    )
    declaration = contract["declaration"]
    required = set(declaration["required_fields"])
    allowed = set(declaration["public_fields"])
    missing = sorted(field for field in required if field not in plan)
    unexpected = sorted(set(plan) - allowed)
    if missing or unexpected:
        field = unexpected[0] if unexpected else missing[0]
        raise _repair(
            session,
            "INVALID_ARGUMENT",
            field=field,
            action="use exactly the fields disclosed for this operation and version",
            missing_fields=missing,
            unexpected_fields=unexpected,
        )
    _validate_constraints(session, plan, declaration.get("constraints", {}))
    normalized = _normalize_plan(
        session,
        plan,
        declaration["field_types"],
    )
    native_args = _native_args(operation, normalized)
    try:
        io_root = _derive_io_root(operation, normalized)
    except ValueError as exc:
        raise _repair(
            session,
            "INVALID_ARGUMENT",
            field="cli_console_plan",
            action="keep every explicit write path in one filesystem style and root",
        ) from exc
    arguments: dict[str, Any] = {
        "api": operation,
        "args": native_args,
        "options": {},
    }
    if io_root is not None:
        arguments["io_root"] = io_root
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": session.context.wwise_version,
        "operation": "waapi.call",
        "arguments": arguments,
    }
    parse_operation_request(request, expected_version=session.context.wwise_version)
    return request


def _validate_constraints(
    session: BusinessDeclarationSession,
    plan: Mapping[str, Any],
    constraints: object,
) -> None:
    if not isinstance(constraints, Mapping):
        return
    for group in constraints.get("mutually_exclusive", []):
        if not isinstance(group, list):
            continue
        supplied = [field for field in group if field in plan]
        if len(supplied) > 1:
            raise _repair(
                session,
                "INVALID_ARGUMENT",
                field=supplied[1],
                action="choose only one disclosed alternative",
                mutually_exclusive=group,
            )


def _normalize_plan(
    session: BusinessDeclarationSession,
    plan: Mapping[str, Any],
    field_types: Mapping[str, str],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field, raw in plan.items():
        field_type = field_types[field]
        if field_type == "boolean":
            if type(raw) is not bool:
                raise _invalid(session, field, "provide a JSON boolean")
            result[field] = raw
            continue
        if field_type in {
            "nonnegative_integer",
            "port_0_through_65535",
            "client_count_0_through_100",
        }:
            if isinstance(raw, bool) or not isinstance(raw, int):
                raise _invalid(session, field, "provide one whole number")
            maximum = 65535 if field_type.startswith("port_") else 100 if field_type.startswith("client_") else None
            if raw < 0 or maximum is not None and raw > maximum:
                raise _invalid(session, field, "provide a value inside the disclosed range")
            result[field] = raw
            continue
        if field in _ENUMS:
            if not isinstance(raw, str) or raw not in _ENUMS[field]:
                raise _invalid(
                    session,
                    field,
                    "choose one disclosed business value",
                    choices=sorted(_ENUMS[field]),
                )
            result[field] = raw
            continue
        if field_type in _LIST_TYPES:
            if (
                not isinstance(raw, list)
                or not raw
                or len(raw) > MAX_CLI_CONSOLE_COLLECTION_ITEMS
            ):
                raise _invalid(session, field, "provide one or more exact values")
            values: list[str] = []
            for value in raw:
                values.append(_nonempty_string(session, field, value))
            if len(set(values)) != len(values):
                raise _invalid(session, field, "remove duplicate values")
            if field_type == "network_address_list" and any("," in value for value in values):
                raise _invalid(session, field, "provide one address per item without commas")
            if field_type == "http_origin_list" and any("," in value for value in values):
                raise _invalid(session, field, "provide one origin per item without commas")
            if field_type == "exact_file_list":
                for value in values:
                    _absolute_path(session, field, value)
            result[field] = values
            continue
        if field_type in _MAPPING_TYPES:
            if (
                not isinstance(raw, list)
                or not raw
                or len(raw) > MAX_CLI_CONSOLE_COLLECTION_ITEMS
            ):
                raise _invalid(session, field, "provide one or more key/value mappings")
            rows: list[list[str]] = []
            keys: set[str] = set()
            for row in raw:
                if not isinstance(row, list) or len(row) != 2:
                    raise _invalid(session, field, "provide each mapping as [key, value]")
                key = _nonempty_string(session, field, row[0])
                value = _nonempty_string(session, field, row[1])
                if key.casefold() in keys:
                    raise _invalid(session, field, "provide each mapping key once")
                keys.add(key.casefold())
                if field_type in {"platform_file_mappings", "platform_directory_mappings"}:
                    _absolute_path(session, field, value)
                rows.append([key, value])
            result[field] = rows
            continue
        value = _nonempty_string(session, field, raw)
        maximum_bytes = (
            MAX_CLI_CONSOLE_LICENSE_BYTES
            if field_type == "exact_license_text"
            else MAX_CLI_CONSOLE_PATH_BYTES
            if "file" in field_type or "directory" in field_type
            else MAX_CLI_CONSOLE_VALUE_BYTES
        )
        if len(value.encode("utf-8")) > maximum_bytes:
            raise _invalid(
                session,
                field,
                "shorten the exact value to the disclosed byte ceiling",
                limit_bytes=maximum_bytes,
            )
        if field_type in {
            "exact_project_file",
            "exact_file",
            "exact_output_file",
            "exact_directory",
        }:
            _absolute_path(session, field, value)
        if field_type == "soundbank_name_or_exact_file_list":  # handled above
            raise AssertionError("unreachable")
        result[field] = value
    return result


def _native_args(operation: str, plan: Mapping[str, Any]) -> dict[str, Any]:
    args: dict[str, Any] = {}

    def copy(public: str, native: str) -> None:
        if public in plan:
            args[native] = plan[public]

    project_native = "path" if operation.startswith("ak.wwise.console.project.") else "project"
    copy("project_file", project_native)
    if operation == "ak.wwise.cli.addNewPlatform":
        copy("base_platform", "new-platform-base")
        copy("platform_name", "new-platform-name")
        copy("copy_settings_from_platform", "copy-from-platform")
    elif operation == "ak.wwise.cli.convertExternalSource":
        copy("platforms", "platform")
        copy("source_files", "source-file")
        copy("source_files_by_platform", "source-by-platform")
        copy("output_directory", "output")
        copy("output_directories_by_platform", "output")
        _negative_policy(plan, args, "wwise_dat", "no-wwise-dat", "omit")
        _verbosity(plan, args)
    elif operation == "ak.wwise.cli.createNewProject":
        copy("platforms", "platform")
        _verbosity(plan, args)
    elif operation == "ak.wwise.cli.dumpObjects":
        copy("output_file", "output")
        if "content" in plan:
            args["content"] = {"names": "name", "property_sets": "propertyset"}[str(plan["content"])]
        if plan.get("include_session_objects") is False:
            args["no-session"] = True
    elif operation == "ak.wwise.cli.generateSoundbank":
        mapping = {
            "soundbanks": "bank",
            "platforms": "platform",
            "languages": "language",
            "skip_languages": "skip-languages",
            "cache_directory": "cache",
            "clear_converted_media_cache": "clear-audio-file-cache",
            "stop_on_load_issues": "abort-on-load-issues",
            "continue_on_error": "continue-on-error",
            "audio_sources_from_project_originals": "audio-source-from-original",
            "generate_header": "header-file",
            "header_directory": "header-file-path",
            "definition_files": "import-definition-file",
            "import_language": "import-language",
            "tabular_import_files": "tab-delimited-import-file",
            "license_text": "license",
            "license_file": "license-file",
            "external_source_output_directory": "output",
            "output_directories_by_platform": "output",
            "root_output_directory": "root-output-path",
            "soundbank_directories_by_platform": "soundbank-path",
            "external_source_files": "source-file",
            "external_source_files_by_platform": "source-by-platform",
            "save_project": "save",
            "readable_soundbanks": "readable-soundbanks",
            "stable_guids": "use-stable-guid",
            "use_user_overrides": "use-user-overrides",
        }
        for public, native in mapping.items():
            copy(public, native)
        if "tabular_import_mode" in plan:
            args["tab-delimited-operation"] = _IMPORT_MODES[str(plan["tabular_import_mode"])]
        _negative_policy(plan, args, "decoded_media", "no-decode", "omit")
        _negative_policy(plan, args, "wwise_dat", "no-wwise-dat", "omit")
        _negative_policy(plan, args, "source_control", "no-source-control", "disabled")
        _verbosity(plan, args)
    elif operation == "ak.wwise.cli.migrate":
        copy("stop_on_load_issues", "abort-on-load-issues")
        _negative_policy(plan, args, "source_control", "no-source-control", "disabled")
        _verbosity(plan, args)
    elif operation == "ak.wwise.cli.tabDelimitedImport":
        copy("table_file", "tab-delimited-import-file")
        copy("audio_sources_from_project_originals", "audio-source-from-original")
        copy("continue_on_error", "continue-on-error")
        copy("import_language", "import-language")
        if "tabular_import_mode" in plan:
            args["tab-delimited-operation"] = _IMPORT_MODES[str(plan["tabular_import_mode"])]
        _negative_policy(plan, args, "source_control", "no-source-control", "disabled")
        _verbosity(plan, args)
    elif operation == "ak.wwise.cli.verify":
        copy("stop_on_load_issues", "abort-on-load-issues")
        _verbosity(plan, args)
    elif operation == "ak.wwise.cli.waapiServer":
        if "allowed_addresses" in plan:
            args["allowed-addr"] = ",".join(plan["allowed_addresses"])
        if "allowed_origins" in plan:
            args["allowed-origin"] = ",".join(plan["allowed_origins"])
        for public, native in (
            ("wamp_port", "wamp-port"),
            ("http_port", "http-port"),
            ("wamp_max_clients", "wamp-max-clients"),
            ("http_max_clients", "http-max-clients"),
            ("allow_project_migration", "allow-migration"),
            ("watchdog_seconds", "watchdog-timeout"),
        ):
            copy(public, native)
        _negative_policy(plan, args, "source_control", "no-source-control", "disabled")
        _verbosity(plan, args)
    elif operation == "ak.wwise.console.project.create":
        copy("languages", "languages")
        if "platforms" in plan:
            args["platforms"] = [
                {"basePlatform": base, "name": name}
                for base, name in plan["platforms"]
            ]
    elif operation == "ak.wwise.console.project.open":
        copy("auto_checkout", "autoCheckOutToSourceControl")
        copy("migration_policy", "onMigrationRequired")
    return args


def _negative_policy(
    plan: Mapping[str, Any],
    args: dict[str, Any],
    public: str,
    native: str,
    negative_value: str,
) -> None:
    if public in plan and plan[public] == negative_value:
        args[native] = True


def _verbosity(plan: Mapping[str, Any], args: dict[str, Any]) -> None:
    value = plan.get("verbosity")
    if value in {"quiet", "verbose"}:
        args[str(value)] = True


def _derive_io_root(operation: str, plan: Mapping[str, Any]) -> str | None:
    project = plan.get("project_file")
    write_paths: list[tuple[str, bool]] = []
    project_write = operation in {
        "ak.wwise.cli.addNewPlatform",
        "ak.wwise.cli.createNewProject",
        "ak.wwise.cli.migrate",
        "ak.wwise.cli.moveMediaIdsToSingleFile",
        "ak.wwise.cli.moveMediaIdsToWorkUnits",
        "ak.wwise.cli.tabDelimitedImport",
        "ak.wwise.cli.updateMediaIdsInSingleFile",
        "ak.wwise.console.project.create",
        "ak.wwise.console.project.open",
    } or operation == "ak.wwise.cli.generateSoundbank" and plan.get("save_project") is True
    if isinstance(project, str) and project_write:
        write_paths.append((project, False))
    if operation == "ak.wwise.cli.dumpObjects":
        write_paths.append((str(plan["output_file"]), False))
    for field in (
        "output_directory",
        "external_source_output_directory",
        "root_output_directory",
        "cache_directory",
        "header_directory",
    ):
        value = plan.get(field)
        if isinstance(value, str) and _is_absolute(value):
            write_paths.append((value, True))
    for field in ("output_directories_by_platform", "soundbank_directories_by_platform"):
        rows = plan.get(field)
        if isinstance(rows, list):
            write_paths.extend(
                (str(row[1]), True)
                for row in rows
                if _is_absolute(str(row[1]))
            )
    if write_paths:
        return _common_root(write_paths)
    if operation in {
        "ak.wwise.cli.convertExternalSource",
        "ak.wwise.cli.generateSoundbank",
    } and isinstance(project, str):
        return _parent(project)
    if operation == "ak.wwise.cli.waapiServer" and plan.get("allow_project_migration") is True and isinstance(project, str):
        return _parent(project)
    return None


def _common_root(paths: list[tuple[str, bool]]) -> str:
    normalized: list[str] = []
    style: str | None = None
    for value, directory in paths:
        current_style = "windows" if _is_windows_absolute(value) else "posix"
        if style is not None and style != current_style:
            raise ValueError("write paths use mixed filesystem styles")
        style = current_style
        normalized.append(value if directory else _parent(value))
    module = ntpath if style == "windows" else posixpath
    return module.normpath(module.commonpath(normalized))


def _parent(value: str) -> str:
    module = ntpath if _is_windows_absolute(value) else posixpath
    return module.dirname(module.normpath(value))


def _is_windows_absolute(value: str) -> bool:
    return PureWindowsPath(value).is_absolute() and not PurePosixPath(value).is_absolute()


def _is_absolute(value: str) -> bool:
    return PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()


def _absolute_path(
    session: BusinessDeclarationSession,
    field: str,
    value: str,
) -> None:
    if "\x00" in value or not _is_absolute(value):
        raise _invalid(session, field, "provide one exact absolute filesystem path")


def _nonempty_string(
    session: BusinessDeclarationSession,
    field: str,
    value: object,
) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise _invalid(session, field, "provide one nonempty exact string")
    return value


def _invalid(
    session: BusinessDeclarationSession,
    field: str,
    action: str,
    **details: Any,
):
    return _repair(
        session,
        "INVALID_ARGUMENT",
        field=field,
        action=action,
        **details,
    )


def _repair(
    session: BusinessDeclarationSession,
    error_code: str,
    *,
    field: str,
    action: str,
    **details: Any,
):
    return business_repair(
        error_code,
        field=field,
        action=action,
        draft_revision=session.revision,
        **details,
    )


__all__ = [
    "MAX_CLI_CONSOLE_COLLECTION_ITEMS",
    "MAX_CLI_CONSOLE_PLAN_BYTES",
    "materialize_cli_console_business_request",
]
