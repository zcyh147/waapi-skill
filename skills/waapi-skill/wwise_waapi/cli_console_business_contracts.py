"""Closed business declarations for Wwise CLI and Console project operations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .console_project_operations import (
    CLI_PROJECT_FILE_URIS, MAX_MODEL_FILES, MAX_MODEL_DIRECTORIES, MAX_MODEL_DEPTH, MAX_MODEL_ENTRIES, MAX_MODEL_BYTES, MAX_MODEL_SNAPSHOT_BYTES, MAX_PROJECT_FILE_BYTES, MAX_PROJECT_XML_NODES,
    MAX_PROJECT_XML_DEPTH, MAX_PROJECT_DECLARATION_ROWS, MAX_MISSING_PROJECT_DIRECTORIES,
    MAX_OBJECT_DUMP_JSON_DEPTH,
)


CLI_CONSOLE_BUSINESS_CONTRACT = "waapi-skill.cli-console-business/v1"
ALL_VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
VERSIONS_2022_PLUS = ("2022.1", "2023.1", "2024.1", "2025.1")
VERSIONS_2023_PLUS = ("2023.1", "2024.1", "2025.1")

CLI_CONSOLE_ENUM_CHOICES: dict[str, tuple[str, ...]] = {
    "soundbank_scope": ("all", "selected"),
    "verbosity": ("normal", "quiet", "verbose"),
    "source_control": ("disabled", "enabled"),
    "wwise_dat": ("omit", "write"),
    "decoded_media": ("omit", "write"),
    "tabular_import_mode": ("create", "replace", "reuse"),
    "content": ("names", "property_sets"),
    "migration_policy": ("fail", "migrate"),
}


_COMMON_TYPES: dict[str, str] = {
    "project_file": "exact_project_file",
    "verbosity": "console_verbosity",
    "stop_on_load_issues": "boolean",
    "source_control": "source_control_policy",
}

_EXPLICIT_EMPTY_COLLECTIONS = {
    "ak.wwise.cli.createNewProject": ("platforms",),
    "ak.wwise.console.project.create": ("platforms", "languages"),
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
        ("project_file", "soundbank_scope"),
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
            "soundbank_scope": "soundbank_scope",
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
        "soundbank_scope": (),
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
        "ak.wwise.cli.addNewPlatform": "add one project platform",
        "ak.wwise.cli.convertExternalSource": "convert external sources",
        "ak.wwise.cli.createNewProject": "create a project through WwiseConsole",
        "ak.wwise.cli.dumpObjects": "dump project objects",
        "ak.wwise.cli.generateSoundbank": "generate SoundBanks and build artifacts",
        "ak.wwise.cli.migrate": "migrate a project",
        "ak.wwise.cli.moveMediaIdsToSingleFile": "move media IDs to one file",
        "ak.wwise.cli.moveMediaIdsToWorkUnits": "move media IDs to Work Units",
        "ak.wwise.cli.tabDelimitedImport": "process a tab-delimited import",
        "ak.wwise.cli.updateMediaIdsInSingleFile": "update single-file media IDs",
        "ak.wwise.cli.verify": "verify a project",
        "ak.wwise.cli.waapiServer": "run a bounded WAAPI server",
        "ak.wwise.console.project.create": "create and open a project",
        "ak.wwise.console.project.open": "open a project with migration policy",
    }
    return tuple(
        {
            "api": operation,
            "intent": intents[operation],
            "supported_versions": list(cli_console_business_versions(operation)),
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


def platform_creation_choices(version: str) -> list[str]:
    """Disclose the pinned native enum, without claiming installed availability."""
    from .schema_inventory import load_definition_graph, resolve_schema_reference

    graph = load_definition_graph(version)
    target = resolve_schema_reference('#/definitions/platformToCreateArg',
        root_schema={}, graph=graph).target
    choices = target['properties']['basePlatform']['enum']
    if not isinstance(choices, list) or not choices or any(not isinstance(value, str) for value in choices):
        raise ValueError('Pinned platform creation choices are malformed')
    return list(choices)


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
    constraints = deepcopy(row["constraints"])
    if operation == "ak.wwise.cli.addNewPlatform" and version == "2025.1":
        # This default is explicit in the pinned 2025 native field description;
        # earlier lanes do not establish the same omission semantics.
        required.remove("platform_name")
        optional.insert(0, "platform_name")
        constraints["platform_name_when_omitted"] = "use the base_platform name"
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
                field: _input_form(field, field_types[field], allow_empty=field in _EXPLICIT_EMPTY_COLLECTIONS.get(operation, ()), version=version)
                for field in public_fields
            },
            **({"explicit_empty_collections": list(_EXPLICIT_EMPTY_COLLECTIONS[operation])}
               if operation in _EXPLICIT_EMPTY_COLLECTIONS else {}),
            **(
                {"constraints": constraints}
                if constraints
                else {}
            ),
        },
        **({"result_semantics": {
            "documented_process_outcomes": {"0": "success", "1": "errors_with_possible_partial_effects", "2": "warnings_only"},
            "earlier_media_id_empty_result": "no_process_outcome_reported",
            **({"observed_process_result": {
                "compatibility_rule": "console-media-single-observed-process-result/v1",
                "scope": "matching_2021_to_2023_Console_moveMediaIdsToSingleFile",
                "accepted_shapes": ["empty_object_without_process_outcome", "result_integer_0_1_or_2"],
                "original_reflected_schema": "preserved; compatibility_requires_exact_source_digest",
            }} if operation == 'ak.wwise.cli.moveMediaIdsToSingleFile' and version in {'2021.1', '2022.1', '2023.1'} else {}),
            "unknown_outcome": "executed_unverified_no_automatic_retry",
            "file_effect_verification": "independent_observation_required",
        }} if operation in CLI_PROJECT_FILE_URIS else {}),
        **({'effect_verification': {
            'saved_project': 'bounded_UTF8_WPROJ_and_live_transition_identity',
            'requested_fields': ['platforms', 'languages', 'first_language_is_default'],
            'explicit_empty_effect': 'native_semantics_unresolved_no_business_acceptance',
            'limits': {'project_bytes': MAX_PROJECT_FILE_BYTES, 'xml_nodes': MAX_PROJECT_XML_NODES,
                'xml_depth': MAX_PROJECT_XML_DEPTH, 'platform_or_language_rows': MAX_PROJECT_DECLARATION_ROWS,
                'missing_project_directories': MAX_MISSING_PROJECT_DIRECTORIES},
        }} if operation == 'ak.wwise.console.project.create' else {}),
        **({'effect_verification': {
            'input_binding': 'bounded_saved_WPROJ_GUID_name_and_exact_file_proof_revalidated_before_dispatch',
            'live_effect': 'exact_requested_project_path_and_saved_GUID_name_match',
            'older_project_input': 'permitted_under_declared_migration_policy_without_assuming_migration_success',
            'limits': {'project_bytes': MAX_PROJECT_FILE_BYTES, 'xml_nodes': MAX_PROJECT_XML_NODES,
                'xml_depth': MAX_PROJECT_XML_DEPTH},
        }} if operation == 'ak.wwise.console.project.open' else {}),
        **({'project_start_state': {
            'loaded_project': 'optional',
            'absence_evidence': 'successful_bounded_Project_query_zero_rows_or_exact_native_no_project_loaded_with_attested_Console_runtime',
            'binding': 'selected_configuration_and_Wwise_session_process_version_remain_exact',
        }} if operation in {'ak.wwise.console.project.open', 'ak.wwise.console.project.create'} else {}),
        **({'effect_verification': {
            'saved_project': 'bounded_UTF8_WPROJ_without_post_terminal_native_calls',
            'requested_fields': ['exact_destination_project_name', 'platforms'],
            'language_default': 'not_inferred_from_Console_create',
            'explicit_empty_effect': 'native_semantics_unresolved_no_business_acceptance',
            'limits': {'project_bytes': MAX_PROJECT_FILE_BYTES, 'xml_nodes': MAX_PROJECT_XML_NODES,
                'xml_depth': MAX_PROJECT_XML_DEPTH, 'platform_or_language_rows': MAX_PROJECT_DECLARATION_ROWS,
                'missing_project_directories': MAX_MISSING_PROJECT_DIRECTORIES},
        }} if operation == 'ak.wwise.cli.createNewProject' else {}),
        **({'effect_verification': {
            'saved_project_and_work_units': 'bounded_UTF8_XML_exact_name_base_and_preserved_model',
            'copy_settings': 'compare_explicit_platform_values_in_all_observed_WPROJ_and_WWU_files',
            'inherited_or_elided_copy_values': 'unresolved_no_business_acceptance_without_native_evidence',
            'preexisting_unregistered_platform_values': 'unresolved_no_business_acceptance',
            'prewrite_inputs': 'all_observed_files_and_root_identity_must_match_Preview',
            'post_terminal_native_calls': 'none',
            'limits': {'model_files': MAX_MODEL_FILES, 'model_directories': MAX_MODEL_DIRECTORIES, 'model_depth': MAX_MODEL_DEPTH,
                'model_entries': MAX_MODEL_ENTRIES, 'model_total_bytes': MAX_MODEL_BYTES,
                'model_snapshot_bytes': MAX_MODEL_SNAPSHOT_BYTES, 'file_bytes': MAX_PROJECT_FILE_BYTES,
                'xml_nodes_per_file': MAX_PROJECT_XML_NODES, 'xml_depth': MAX_PROJECT_XML_DEPTH},
        }} if operation == 'ak.wwise.cli.addNewPlatform' else {}),
        **({'effect_verification': {
            'output_artifact': 'stable_confined_bounded_UTF8_JSON',
            'native_object_model_content_and_session_representation': 'unresolved_no_business_acceptance',
            'source_project': 'bytes_and_directory_identity_preserved',
            'limits': {'file_bytes': MAX_PROJECT_FILE_BYTES, 'json_work': 'linear_in_bounded_artifact_bytes',
                'json_depth': MAX_OBJECT_DUMP_JSON_DEPTH},
        }} if operation == 'ak.wwise.cli.dumpObjects' else {}),
        **({'effect_verification': {
            'saved_project': 'target_Wwise_version_and_preserved_project_identity_platforms_languages',
            'saved_model': 'all_observed_Work_Units_object_media_identities_and_header_independent_XML',
            'native_model_transformations': 'partial_until_transformation_semantics_are_established',
            'unchanged_artifact': 'partial_without_observed_save',
            'post_terminal_native_calls': 'none',
        }} if operation == 'ak.wwise.cli.migrate' else {}),
        **({'effect_verification': {
            'mapping_file': 'owned_project_name_mediaid_stable_bounded_bytes_if_present',
            'mapping_container_format': 'five_version_observed_Wwise_MediaIDs_XML; unknown_container_remains_unverified',
            'work_units': ('bounded_saved_MediaIDList_observation; disclosed_optional_empty_None_CustomState_additions; strict_remaining_model'
                if operation == 'ak.wwise.cli.moveMediaIdsToSingleFile'
                else 'bounded_saved_MediaIDList_observation_and_preservation_outside_media_storage'),
            'central_mapping_record_representation': (
                'exact_source_GUID_language_ID_and_name_file_and_all_media_ID_attributes; no_remaining_Work_Unit_IDs; exact_project_storage_mode'
                if operation == 'ak.wwise.cli.moveMediaIdsToSingleFile'
                else 'Preview_central_records_equal_resulting_Work_Unit_source_GUID_language_file_and_all_media_ID_attributes; '
                    'exact_disabled_project_storage_mode; central_file_removal_not_required'
                if operation == 'ak.wwise.cli.moveMediaIdsToWorkUnits'
                else 'existing_file_matches_exact_saved_source_media_records; already_central_uses_Preview_records; '
                    'Work_Unit_media_and_storage_mode_preserved; absent_file_stays_absent'),
            'source_kinds': ['AudioFileSource', 'MidiFileSource', 'PluginMediaSource'],
            **({'optional_saved_none_state_materialization': {
                'force_save_scope': 'all_project_work_units',
                'preview': 'exact_source_proven_saved_owner_group_unique_None_state_bindings',
                'outcome': 'may_persist_zero_or_one_fresh_empty_CustomState_record_per_binding; actual_saved_GUIDs_and_ShortIDs_reported',
                'preservation': 'every_old_identity_value_order_and_all_remaining_model_content',
                'source': 'resources/semantic/' + version + '/none_state_materialization.json',
                'inevitable': False,
                'detail': {'command': 'transaction-show',
                    'fixed_views': ['eligible-bindings', 'actual-additions'],
                    'selector': '--none-state-outcome', 'artifact_binding': '--outcome-artifact-hash',
                    'actual_event_binding': '--outcome-event-hash', 'page': '--outcome-page',
                    'continuation': 'copy_exact_generated_command; offline_read_only; no_confirmation_or_execution',
                    'limits': {'entries_per_page': 64, 'detail_bytes': 16384, 'gateway_page_bytes': 32768}},
            }} if operation == 'ak.wwise.cli.moveMediaIdsToSingleFile' else {}),
            'generated_platform_hashes': 'bounded_observation_only; not_conversion_correctness_proof',
            'post_terminal_native_calls': 'none',
        }} if operation in {'ak.wwise.cli.moveMediaIdsToSingleFile', 'ak.wwise.cli.moveMediaIdsToWorkUnits',
            'ak.wwise.cli.updateMediaIdsInSingleFile'} else {}),
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


def _input_form(field: str, field_type: str, *, allow_empty=False, version=None) -> dict[str, Any]:
    if field_type in {
        "platform_name_list",
        "language_name_list",
        "exact_file_list",
        "soundbank_name_or_exact_file_list",
        "network_address_list",
        "http_origin_list",
    }:
        result = {"flag": "--item", "arguments": [field, "<value>"], "repeatable": True}
        if allow_empty:
            result["empty_form"] = {"flag": "--empty", "arguments": [field], "repeatable": False}
        return result
    if field_type.endswith("_mappings"):
        result = {
            "flag": "--mapping",
            "arguments": [field, "<key>", "<value>"],
            "repeatable": True,
        }
        if field_type == "platform_creation_mappings":
            result['base_platform_choices'] = platform_creation_choices(version)
            result['choice_scope'] = 'pinned_schema_values_not_installed_availability'
            result['row_order'] = 'preserve_declaration_order_across_named_and_unnamed_forms'
            result["unnamed_platform_form"] = {"flag": "--item", "arguments": [field, "<base_platform>"], "repeatable": True}
            result["meaning"] = "One base platform per unnamed row, or base platform and explicit name per mapping; the same base may have distinct named rows. Omission preserves the native project default."
        if allow_empty:
            result["empty_form"] = {"flag": "--empty", "arguments": [field], "repeatable": False}
        return result
    if field_type == "boolean":
        return {
            "flag": "--toggle",
            "arguments": [field, "enable|disable"],
            "repeatable": False,
        }
    result = {
        "flag": "--value",
        "arguments": [field, "<value>"],
        "repeatable": False,
    }
    if field in CLI_CONSOLE_ENUM_CHOICES:
        result["choices"] = list(CLI_CONSOLE_ENUM_CHOICES[field])
    return result


__all__ = [
    "CLI_CONSOLE_BUSINESS_CONTRACT",
    "CLI_CONSOLE_BUSINESS_OPERATIONS",
    "CLI_CONSOLE_ENUM_CHOICES",
    "cli_console_business_catalog_rows",
    "cli_console_business_contract_data",
    "cli_console_business_versions",
    "cli_console_native_field_ownership",
]
