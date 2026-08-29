"""Closed business declarations for Wwise CLI and Console project operations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


CLI_CONSOLE_BUSINESS_CONTRACT = "waapi-skill.cli-console-business/v1"
ALL_VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
VERSIONS_2022_PLUS = ("2022.1", "2023.1", "2024.1", "2025.1")
VERSIONS_2023_PLUS = ("2023.1", "2024.1", "2025.1")


_COMMON_TYPES: dict[str, str] = {
    "project_file": "exact_project_file",
    "verbosity": "console_verbosity",
    "stop_on_load_issues": "boolean",
    "source_control": "source_control_policy",
}


def _row(
    versions: tuple[str, ...],
    required: tuple[str, ...],
    optional: tuple[str, ...],
    field_types: dict[str, str],
    *,
    optional_by_version: dict[str, tuple[str, ...]] | None = None,
    constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "versions": versions,
        "required": required,
        "optional": optional,
        "optional_by_version": optional_by_version or {},
        "field_types": field_types,
        "constraints": constraints or {},
    }


_CONTRACTS: dict[str, dict[str, Any]] = {
    "ak.wwise.cli.addNewPlatform": _row(
        ALL_VERSIONS,
        ("project_file", "base_platform", "platform_name"),
        ("copy_settings_from_platform",),
        {
            "project_file": "exact_project_file",
            "base_platform": "installed_base_platform_name",
            "platform_name": "new_platform_name",
            "copy_settings_from_platform": "existing_platform_name",
        },
    ),
    "ak.wwise.cli.convertExternalSource": _row(
        ALL_VERSIONS,
        ("project_file",),
        (
            "platforms",
            "source_files",
            "source_files_by_platform",
            "output_directory",
            "output_directories_by_platform",
            "wwise_dat",
            "verbosity",
        ),
        {
            **_COMMON_TYPES,
            "platforms": "platform_name_list",
            "source_files": "exact_file_list",
            "source_files_by_platform": "platform_file_mappings",
            "output_directory": "exact_directory",
            "output_directories_by_platform": "platform_directory_mappings",
            "wwise_dat": "wwise_dat_policy",
        },
        optional_by_version={
            "2024.1": tuple(
                field
                for field in (
                    "platforms",
                    "source_files",
                    "source_files_by_platform",
                    "output_directory",
                    "output_directories_by_platform",
                    "verbosity",
                )
            ),
            "2025.1": tuple(
                field
                for field in (
                    "platforms",
                    "source_files",
                    "source_files_by_platform",
                    "output_directory",
                    "output_directories_by_platform",
                    "verbosity",
                )
            ),
        },
        constraints={
            "mutually_exclusive": [["output_directory", "output_directories_by_platform"]],
            "wwise_2022_source_limit": "one source file per platform per transaction",
        },
    ),
    "ak.wwise.cli.createNewProject": _row(
        ALL_VERSIONS,
        ("project_file",),
        ("platforms", "verbosity"),
        {**_COMMON_TYPES, "platforms": "platform_name_list"},
    ),
    "ak.wwise.cli.dumpObjects": _row(
        ALL_VERSIONS,
        ("project_file", "output_file"),
        ("content", "include_session_objects"),
        {
            "project_file": "exact_project_file",
            "output_file": "exact_output_file",
            "content": "dump_content",
            "include_session_objects": "boolean",
        },
    ),
    "ak.wwise.cli.generateSoundbank": _row(
        ALL_VERSIONS,
        ("project_file",),
        (
            "soundbanks",
            "platforms",
            "languages",
            "skip_languages",
            "cache_directory",
            "clear_converted_media_cache",
            "stop_on_load_issues",
            "continue_on_error",
            "audio_sources_from_project_originals",
            "generate_header",
            "header_directory",
            "definition_files",
            "import_language",
            "tabular_import_files",
            "tabular_import_mode",
            "license_text",
            "license_file",
            "decoded_media",
            "wwise_dat",
            "source_control",
            "external_source_output_directory",
            "output_directories_by_platform",
            "root_output_directory",
            "soundbank_directories_by_platform",
            "external_source_files",
            "external_source_files_by_platform",
            "save_project",
            "readable_soundbanks",
            "stable_guids",
            "use_user_overrides",
            "verbosity",
        ),
        {
            **_COMMON_TYPES,
            "soundbanks": "soundbank_name_or_exact_file_list",
            "platforms": "platform_name_list",
            "languages": "language_name_list",
            "skip_languages": "boolean",
            "cache_directory": "exact_or_relative_output_directory",
            "clear_converted_media_cache": "boolean",
            "continue_on_error": "boolean",
            "audio_sources_from_project_originals": "boolean",
            "generate_header": "boolean",
            "header_directory": "exact_or_relative_output_directory",
            "definition_files": "exact_file_list",
            "import_language": "language_name",
            "tabular_import_files": "exact_file_list",
            "tabular_import_mode": "import_mode",
            "license_text": "exact_license_text",
            "license_file": "exact_file",
            "decoded_media": "decoded_media_policy",
            "wwise_dat": "wwise_dat_policy",
            "external_source_output_directory": "exact_directory",
            "output_directories_by_platform": "platform_directory_mappings",
            "root_output_directory": "exact_or_relative_output_directory",
            "soundbank_directories_by_platform": "platform_exact_or_relative_directory_mappings",
            "external_source_files": "exact_file_list",
            "external_source_files_by_platform": "platform_file_mappings",
            "save_project": "boolean",
            "readable_soundbanks": "boolean",
            "stable_guids": "boolean",
            "use_user_overrides": "boolean",
        },
        optional_by_version={
            "2021.1": tuple(
                field
                for field in (
                    "soundbanks", "platforms", "languages", "skip_languages",
                    "cache_directory", "clear_converted_media_cache",
                    "stop_on_load_issues", "continue_on_error",
                    "audio_sources_from_project_originals", "generate_header",
                    "header_directory", "definition_files", "import_language",
                    "tabular_import_files", "tabular_import_mode", "license_text",
                    "decoded_media", "wwise_dat", "external_source_output_directory",
                    "output_directories_by_platform", "soundbank_directories_by_platform",
                    "external_source_files", "external_source_files_by_platform",
                    "save_project", "readable_soundbanks", "stable_guids", "verbosity",
                )
            ),
            "2022.1": tuple(
                field
                for field in (
                    "soundbanks", "platforms", "languages", "skip_languages",
                    "cache_directory", "clear_converted_media_cache",
                    "stop_on_load_issues", "continue_on_error",
                    "audio_sources_from_project_originals", "generate_header",
                    "header_directory", "definition_files", "import_language",
                    "tabular_import_files", "tabular_import_mode", "license_text",
                    "decoded_media", "wwise_dat", "source_control",
                    "external_source_output_directory", "output_directories_by_platform",
                    "root_output_directory", "soundbank_directories_by_platform",
                    "external_source_files", "external_source_files_by_platform",
                    "save_project", "readable_soundbanks", "stable_guids",
                    "use_user_overrides", "verbosity",
                )
            ),
            "2023.1": tuple(
                field
                for field in (
                    "soundbanks", "platforms", "languages", "skip_languages",
                    "cache_directory", "clear_converted_media_cache",
                    "stop_on_load_issues", "continue_on_error",
                    "audio_sources_from_project_originals", "generate_header",
                    "header_directory", "definition_files", "import_language",
                    "tabular_import_files", "tabular_import_mode", "license_text",
                    "license_file", "decoded_media", "wwise_dat", "source_control",
                    "external_source_output_directory", "output_directories_by_platform",
                    "root_output_directory", "soundbank_directories_by_platform",
                    "external_source_files", "external_source_files_by_platform",
                    "save_project", "readable_soundbanks", "stable_guids",
                    "use_user_overrides", "verbosity",
                )
            ),
            "2024.1": tuple(
                field
                for field in (
                    "soundbanks", "platforms", "languages", "skip_languages",
                    "cache_directory", "clear_converted_media_cache",
                    "stop_on_load_issues", "continue_on_error",
                    "audio_sources_from_project_originals", "generate_header",
                    "header_directory", "definition_files", "import_language",
                    "tabular_import_files", "tabular_import_mode", "license_text",
                    "license_file", "decoded_media", "source_control",
                    "external_source_output_directory", "output_directories_by_platform",
                    "root_output_directory", "soundbank_directories_by_platform",
                    "external_source_files", "external_source_files_by_platform",
                    "save_project", "readable_soundbanks", "stable_guids",
                    "use_user_overrides", "verbosity",
                )
            ),
            "2025.1": tuple(
                field
                for field in (
                    "soundbanks", "platforms", "languages", "skip_languages",
                    "cache_directory", "clear_converted_media_cache",
                    "stop_on_load_issues", "continue_on_error",
                    "audio_sources_from_project_originals", "generate_header",
                    "header_directory", "definition_files", "import_language",
                    "tabular_import_files", "tabular_import_mode", "license_text",
                    "license_file", "decoded_media", "source_control",
                    "external_source_output_directory", "output_directories_by_platform",
                    "root_output_directory", "soundbank_directories_by_platform",
                    "external_source_files", "external_source_files_by_platform",
                    "save_project", "readable_soundbanks", "stable_guids",
                    "use_user_overrides", "verbosity",
                )
            ),
        },
        constraints={
            "mutually_exclusive": [
                ["license_text", "license_file"],
                ["external_source_output_directory", "output_directories_by_platform"],
            ],
            "custom_commands": "prohibited",
        },
    ),
    "ak.wwise.cli.migrate": _row(
        ALL_VERSIONS,
        ("project_file",),
        ("stop_on_load_issues", "source_control", "verbosity"),
        _COMMON_TYPES,
        optional_by_version={
            "2021.1": ("stop_on_load_issues", "verbosity"),
            "2022.1": ("stop_on_load_issues", "verbosity"),
        },
    ),
    "ak.wwise.cli.moveMediaIdsToSingleFile": _row(
        ALL_VERSIONS, ("project_file",), (), {"project_file": "exact_project_file"}
    ),
    "ak.wwise.cli.moveMediaIdsToWorkUnits": _row(
        ALL_VERSIONS, ("project_file",), (), {"project_file": "exact_project_file"}
    ),
    "ak.wwise.cli.updateMediaIdsInSingleFile": _row(
        ALL_VERSIONS, ("project_file",), (), {"project_file": "exact_project_file"}
    ),
    "ak.wwise.cli.tabDelimitedImport": _row(
        ALL_VERSIONS,
        ("project_file", "table_file"),
        (
            "audio_sources_from_project_originals",
            "continue_on_error",
            "import_language",
            "tabular_import_mode",
            "source_control",
            "verbosity",
        ),
        {
            **_COMMON_TYPES,
            "table_file": "exact_file",
            "audio_sources_from_project_originals": "boolean",
            "continue_on_error": "boolean",
            "import_language": "language_name",
            "tabular_import_mode": "import_mode",
        },
        optional_by_version={
            "2021.1": (
                "audio_sources_from_project_originals", "continue_on_error",
                "import_language", "tabular_import_mode", "verbosity",
            ),
            "2022.1": (
                "audio_sources_from_project_originals", "continue_on_error",
                "import_language", "tabular_import_mode", "verbosity",
            ),
        },
        constraints={"custom_commands": "prohibited"},
    ),
    "ak.wwise.cli.verify": _row(
        VERSIONS_2022_PLUS,
        ("project_file",),
        ("stop_on_load_issues", "verbosity"),
        _COMMON_TYPES,
    ),
    "ak.wwise.cli.waapiServer": _row(
        ALL_VERSIONS,
        (),
        (
            "project_file",
            "allowed_addresses",
            "allowed_origins",
            "wamp_port",
            "http_port",
            "wamp_max_clients",
            "http_max_clients",
            "allow_project_migration",
            "source_control",
            "watchdog_seconds",
            "verbosity",
        ),
        {
            **_COMMON_TYPES,
            "allowed_addresses": "network_address_list",
            "allowed_origins": "http_origin_list",
            "wamp_port": "port_0_through_65535",
            "http_port": "port_0_through_65535",
            "wamp_max_clients": "client_count_0_through_100",
            "http_max_clients": "client_count_0_through_100",
            "allow_project_migration": "boolean",
            "watchdog_seconds": "nonnegative_integer",
        },
        optional_by_version={
            "2021.1": (
                "allowed_addresses", "allowed_origins", "wamp_port", "http_port",
                "wamp_max_clients", "http_max_clients", "allow_project_migration",
                "verbosity",
            ),
            "2022.1": (
                "allowed_addresses", "allowed_origins", "wamp_port", "http_port",
                "wamp_max_clients", "http_max_clients", "allow_project_migration",
                "verbosity",
            ),
            "2023.1": (
                "project_file", "allowed_addresses", "allowed_origins", "wamp_port",
                "http_port", "wamp_max_clients", "http_max_clients",
                "allow_project_migration", "source_control", "verbosity",
            ),
        },
    ),
    "ak.wwise.console.project.create": _row(
        VERSIONS_2023_PLUS,
        ("project_file",),
        ("languages", "platforms"),
        {
            "project_file": "exact_project_file",
            "languages": "language_name_list",
            "platforms": "platform_creation_mappings",
        },
    ),
    "ak.wwise.console.project.open": _row(
        VERSIONS_2023_PLUS,
        ("project_file",),
        ("auto_checkout", "migration_policy"),
        {
            "project_file": "exact_project_file",
            "auto_checkout": "boolean",
            "migration_policy": "migration_policy",
        },
    ),
}


_NATIVE_FIELD_OWNERSHIP: dict[str, dict[str, tuple[str, ...]]] = {
    "ak.wwise.cli.addNewPlatform": {
        "project_file": ("project",),
        "base_platform": ("new-platform-base",),
        "platform_name": ("new-platform-name",),
        "copy_settings_from_platform": ("copy-from-platform",),
    },
    "ak.wwise.cli.convertExternalSource": {
        "project_file": ("project",),
        "platforms": ("platform",),
        "source_files": ("source-file",),
        "source_files_by_platform": ("source-by-platform",),
        "output_directory": ("output",),
        "output_directories_by_platform": ("output",),
        "wwise_dat": ("no-wwise-dat",),
        "verbosity": ("quiet", "verbose"),
    },
    "ak.wwise.cli.createNewProject": {
        "project_file": ("project",),
        "platforms": ("platform",),
        "verbosity": ("quiet", "verbose"),
    },
    "ak.wwise.cli.dumpObjects": {
        "project_file": ("project",),
        "output_file": ("output",),
        "content": ("content",),
        "include_session_objects": ("no-session",),
    },
    "ak.wwise.cli.generateSoundbank": {
        "project_file": ("project",),
        "soundbanks": ("bank",),
        "platforms": ("platform",),
        "languages": ("language",),
        "skip_languages": ("skip-languages",),
        "cache_directory": ("cache",),
        "clear_converted_media_cache": ("clear-audio-file-cache",),
        "stop_on_load_issues": ("abort-on-load-issues",),
        "continue_on_error": ("continue-on-error",),
        "audio_sources_from_project_originals": ("audio-source-from-original",),
        "generate_header": ("header-file",),
        "header_directory": ("header-file-path",),
        "definition_files": ("import-definition-file",),
        "import_language": ("import-language",),
        "tabular_import_files": ("tab-delimited-import-file",),
        "tabular_import_mode": ("tab-delimited-operation",),
        "license_text": ("license",),
        "license_file": ("license-file",),
        "decoded_media": ("no-decode",),
        "wwise_dat": ("no-wwise-dat",),
        "source_control": ("no-source-control",),
        "external_source_output_directory": ("output",),
        "output_directories_by_platform": ("output",),
        "root_output_directory": ("root-output-path",),
        "soundbank_directories_by_platform": ("soundbank-path",),
        "external_source_files": ("source-file",),
        "external_source_files_by_platform": ("source-by-platform",),
        "save_project": ("save",),
        "readable_soundbanks": ("readable-soundbanks",),
        "stable_guids": ("use-stable-guid",),
        "use_user_overrides": ("use-user-overrides",),
        "verbosity": ("quiet", "verbose"),
    },
    "ak.wwise.cli.migrate": {
        "project_file": ("project",),
        "stop_on_load_issues": ("abort-on-load-issues",),
        "source_control": ("no-source-control",),
        "verbosity": ("quiet", "verbose"),
    },
    "ak.wwise.cli.moveMediaIdsToSingleFile": {"project_file": ("project",)},
    "ak.wwise.cli.moveMediaIdsToWorkUnits": {"project_file": ("project",)},
    "ak.wwise.cli.updateMediaIdsInSingleFile": {"project_file": ("project",)},
    "ak.wwise.cli.tabDelimitedImport": {
        "project_file": ("project",),
        "table_file": ("tab-delimited-import-file",),
        "audio_sources_from_project_originals": ("audio-source-from-original",),
        "continue_on_error": ("continue-on-error",),
        "import_language": ("import-language",),
        "tabular_import_mode": ("tab-delimited-operation",),
        "source_control": ("no-source-control",),
        "verbosity": ("quiet", "verbose"),
    },
    "ak.wwise.cli.verify": {
        "project_file": ("project",),
        "stop_on_load_issues": ("abort-on-load-issues",),
        "verbosity": ("quiet", "verbose"),
    },
    "ak.wwise.cli.waapiServer": {
        "project_file": ("project",),
        "allowed_addresses": ("allowed-addr",),
        "allowed_origins": ("allowed-origin",),
        "wamp_port": ("wamp-port",),
        "http_port": ("http-port",),
        "wamp_max_clients": ("wamp-max-clients",),
        "http_max_clients": ("http-max-clients",),
        "allow_project_migration": ("allow-migration",),
        "source_control": ("no-source-control",),
        "watchdog_seconds": ("watchdog-timeout",),
        "verbosity": ("quiet", "verbose"),
    },
    "ak.wwise.console.project.create": {
        "project_file": ("path",),
        "languages": ("languages",),
        "platforms": ("platforms",),
    },
    "ak.wwise.console.project.open": {
        "project_file": ("path",),
        "auto_checkout": ("autoCheckOutToSourceControl",),
        "migration_policy": ("onMigrationRequired",),
    },
}

_PROHIBITED_NATIVE_FIELDS: dict[str, tuple[str, ...]] = {
    "ak.wwise.cli.generateSoundbank": (
        "custom-global-closing-cmd",
        "custom-global-opening-cmd",
        "custom-post-gen-cmd",
        "custom-pre-gen-cmd",
    ),
    "ak.wwise.cli.tabDelimitedImport": (
        "custom-global-closing-cmd",
        "custom-global-opening-cmd",
    ),
}


CLI_CONSOLE_BUSINESS_OPERATIONS = tuple(sorted(_CONTRACTS))


def cli_console_business_catalog_rows() -> tuple[dict[str, Any], ...]:
    """List the deep project/build routes for offline intent selection."""

    intents = {
        "ak.wwise.cli.addNewPlatform": "add one project platform from a supported base platform",
        "ak.wwise.cli.convertExternalSource": "convert exact external-source definition files for selected platforms",
        "ak.wwise.cli.createNewProject": "create a new Wwise project through WwiseConsole",
        "ak.wwise.cli.dumpObjects": "write a deterministic project object dump",
        "ak.wwise.cli.generateSoundbank": "generate SoundBanks and related build artifacts through WwiseConsole",
        "ak.wwise.cli.migrate": "migrate one exact Wwise project",
        "ak.wwise.cli.moveMediaIdsToSingleFile": "move project media IDs into the single-file layout",
        "ak.wwise.cli.moveMediaIdsToWorkUnits": "move project media IDs into Work Units",
        "ak.wwise.cli.tabDelimitedImport": "process one existing tab-delimited import through WwiseConsole",
        "ak.wwise.cli.updateMediaIdsInSingleFile": "update the project single-file media ID layout",
        "ak.wwise.cli.verify": "verify one exact Wwise project without changing its business content",
        "ak.wwise.cli.waapiServer": "start a bounded WwiseConsole WAAPI server configuration",
        "ak.wwise.console.project.create": "create and open a project through the Console project API",
        "ak.wwise.console.project.open": "open one exact project with a closed migration policy",
    }
    return tuple(
        {
            "api": operation,
            "intent": intents[operation],
            "supported_versions": list(cli_console_business_versions(operation)),
            "host_requirement": "wwise-console",
        }
        for operation in CLI_CONSOLE_BUSINESS_OPERATIONS
    )


def cli_console_business_versions(operation: str) -> tuple[str, ...]:
    try:
        return tuple(_CONTRACTS[operation]["versions"])
    except KeyError as exc:
        raise ValueError("unsupported CLI/Console business operation") from exc


def cli_console_native_field_ownership(
    operation: str,
    version: str,
) -> dict[str, Any]:
    """Return the internal exhaustive reflected-field assignment for audit."""

    contract = cli_console_business_contract_data(operation, version)
    public_fields = set(contract["declaration"]["public_fields"])
    ownership = _NATIVE_FIELD_OWNERSHIP[operation]
    return {
        "owned": {
            field: list(ownership[field])
            for field in sorted(public_fields)
        },
        "prohibited": list(_PROHIBITED_NATIVE_FIELDS.get(operation, ())),
    }


def cli_console_business_contract_data(
    operation: str,
    version: str,
) -> dict[str, Any]:
    try:
        row = _CONTRACTS[operation]
    except KeyError as exc:
        raise ValueError("unsupported CLI/Console business operation") from exc
    if version not in row["versions"]:
        raise ValueError("CLI/Console operation is unavailable in this version")
    required = list(row["required"])
    if operation == "ak.wwise.cli.waapiServer" and version in {"2021.1", "2022.1"}:
        required = ["project_file"]
    optional = list(row["optional_by_version"].get(version, row["optional"]))
    optional = [field for field in optional if field not in required]
    public_fields = [*required, *optional]
    field_types = {
        field: row["field_types"][field]
        for field in public_fields
    }
    return {
        "contract": CLI_CONSOLE_BUSINESS_CONTRACT,
        "operation": operation,
        "version": version,
        "input_mode": "business_declaration",
        "execution_shape": "isolated_transaction",
        "host_requirement": "wwise-console",
        "start": {
            "subcommand": "draft-start",
            "gateway_argv": ["draft-start", operation],
            "copy_exactly": True,
            "append_arguments": "forbidden",
        },
        "binding": {
            "available": False,
            "roles": [],
            "role_required": False,
            "identity": "none",
            "validation": "exact_artifact_and_manifest_schema",
        },
        "declaration": {
            "subcommand": "draft-declare-cli-console-plan",
            "settings_field": "cli_console_plan",
            "submit_once": True,
            "required_fields": required,
            "optional_fields": optional,
            "public_fields": public_fields,
            "field_types": field_types,
            "input_forms": {
                field: _input_form(field, field_types[field])
                for field in public_fields
            },
            **(
                {"constraints": deepcopy(row["constraints"])}
                if row["constraints"]
                else {}
            ),
        },
        "gateway_derivations": [
            "native_option_names_and_negative_flags",
            "version_specific_field_availability",
            "platform_mapping_arrays_and_order",
            "isolated_io_root_and_exact_path_audit",
            "shell_safe_continuation",
            "immutable_preview_authorization_and_verification",
        ],
        "exact_user_artifacts": [
            field
            for field, field_type in field_types.items()
            if "exact_" in field_type or field_type.endswith("_mappings")
        ],
        "legacy_typed_call_public": False,
        "legacy_native_option_assembly_public": False,
        "safety": {
            "custom_commands": "prohibited",
            "immutable_preview": True,
            "single_execute": True,
            "isolated_io_audit": True,
            "native_request_fields": "gateway_owned",
        },
    }


def _input_form(field: str, field_type: str) -> dict[str, Any]:
    if field_type in {
        "platform_name_list",
        "language_name_list",
        "exact_file_list",
        "soundbank_name_or_exact_file_list",
        "network_address_list",
        "http_origin_list",
    }:
        return {"flag": "--item", "arguments": [field, "<value>"], "repeatable": True}
    if field_type.endswith("_mappings"):
        return {
            "flag": "--mapping",
            "arguments": [field, "<key>", "<value>"],
            "repeatable": True,
        }
    if field_type == "boolean":
        return {
            "flag": "--toggle",
            "arguments": [field, "enable|disable"],
            "repeatable": False,
        }
    return {"flag": "--value", "arguments": [field, "<value>"], "repeatable": False}


__all__ = [
    "CLI_CONSOLE_BUSINESS_CONTRACT",
    "CLI_CONSOLE_BUSINESS_OPERATIONS",
    "cli_console_business_catalog_rows",
    "cli_console_business_contract_data",
    "cli_console_business_versions",
    "cli_console_native_field_ownership",
]
