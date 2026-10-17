"""Closed source-control contracts and the credential/provider boundary."""

from __future__ import annotations

from typing import Any


SOURCE_CONTROL_BUSINESS_CONTRACT = "waapi-skill.source-control-business/v1"
SOURCE_CONTROL_PREFIX = "ak.wwise.core.sourceControl."
SOURCE_CONTROL_ADD_URI = SOURCE_CONTROL_PREFIX + "add"
SOURCE_CONTROL_CHECK_OUT_URI = SOURCE_CONTROL_PREFIX + "checkOut"
SOURCE_CONTROL_COMMIT_URI = SOURCE_CONTROL_PREFIX + "commit"
SOURCE_CONTROL_DELETE_URI = SOURCE_CONTROL_PREFIX + "delete"
SOURCE_CONTROL_GET_SOURCE_FILES_URI = SOURCE_CONTROL_PREFIX + "getSourceFiles"
SOURCE_CONTROL_GET_STATUS_URI = SOURCE_CONTROL_PREFIX + "getStatus"
SOURCE_CONTROL_MOVE_URI = SOURCE_CONTROL_PREFIX + "move"
SOURCE_CONTROL_REVERT_URI = SOURCE_CONTROL_PREFIX + "revert"
SOURCE_CONTROL_SET_PROVIDER_URI = SOURCE_CONTROL_PREFIX + "setProvider"

_VERSIONS = ("2023.1", "2024.1", "2025.1")
_CONTRACTS: dict[str, dict[str, Any]] = {
    SOURCE_CONTROL_GET_SOURCE_FILES_URI: {
        "execution_shape": "isolated_draft_external",
        "required_fields": (),
        "optional_fields": (
            "usage_scope",
            "originals_folder",
            "recursive",
            "include_usage_objects",
            "usage_outputs",
            "max_results",
        ),
        "field_types": {
            "usage_scope": "source_file_usage_scope",
            "originals_folder": "safe_originals_relative_folder",
            "recursive": "boolean",
            "include_usage_objects": "boolean",
            "usage_outputs": "source_file_usage_business_outputs",
            "max_results": "bounded_result_count",
        },
    },
    SOURCE_CONTROL_GET_STATUS_URI: {
        "execution_shape": "isolated_draft_external",
        "required_fields": ("files",),
        "optional_fields": ("io_root",),
        "field_types": {
            "files": "source_control_file_locators",
            "io_root": "exact_user_io_root",
        },
    },
    SOURCE_CONTROL_ADD_URI: {
        "execution_shape": "isolated_draft_external",
        "required_fields": ("files",),
        "optional_fields": ("io_root",),
        "field_types": {
            "files": "source_control_file_locators",
            "io_root": "exact_user_io_root",
        },
    },
    SOURCE_CONTROL_CHECK_OUT_URI: {
        "execution_shape": "isolated_draft_external",
        "required_fields": ("files",),
        "optional_fields": ("io_root",),
        "field_types": {
            "files": "source_control_file_locators",
            "io_root": "exact_user_io_root",
        },
    },
    SOURCE_CONTROL_COMMIT_URI: {
        "execution_shape": "isolated_draft_external",
        "required_fields": ("files", "commit_message"),
        "optional_fields": ("io_root",),
        "field_types": {
            "files": "source_control_file_locators",
            "commit_message": "source_control_commit_message",
            "io_root": "exact_user_io_root",
        },
    },
    SOURCE_CONTROL_DELETE_URI: {
        "execution_shape": "isolated_draft_external",
        "required_fields": ("files",),
        "optional_fields": ("io_root",),
        "field_types": {
            "files": "source_control_file_locators",
            "io_root": "exact_user_io_root",
        },
    },
    SOURCE_CONTROL_MOVE_URI: {
        "execution_shape": "isolated_draft_external",
        "required_fields": ("moves",),
        "optional_fields": ("io_root",),
        "field_types": {
            "moves": "source_control_move_pairs",
            "io_root": "exact_user_io_root",
        },
    },
    SOURCE_CONTROL_REVERT_URI: {
        "execution_shape": "isolated_draft_external",
        "required_fields": ("files",),
        "optional_fields": ("io_root",),
        "field_types": {
            "files": "source_control_file_locators",
            "io_root": "exact_user_io_root",
        },
    },
    SOURCE_CONTROL_SET_PROVIDER_URI: {
        "execution_shape": "prohibited_boundary",
        "required_fields": (),
        "optional_fields": (),
        "field_types": {},
    },
}
_INTENTS = {
    SOURCE_CONTROL_ADD_URI: "Add exact project files to the active source-control provider.",
    SOURCE_CONTROL_CHECK_OUT_URI: "Check out exact project files for editing.",
    SOURCE_CONTROL_COMMIT_URI: "Commit exact project files with one explicit message.",
    SOURCE_CONTROL_DELETE_URI: "Delete exact project files through source control.",
    SOURCE_CONTROL_GET_SOURCE_FILES_URI: (
        "List a bounded set of Wwise source files by business usage scope."
    ),
    SOURCE_CONTROL_GET_STATUS_URI: (
        "Read bounded source-control status for exact project files."
    ),
    SOURCE_CONTROL_MOVE_URI: "Move exact project files through source control.",
    SOURCE_CONTROL_REVERT_URI: "Revert exact project files through source control.",
    SOURCE_CONTROL_SET_PROVIDER_URI: (
        "Configure a human-owned source-control provider and credentials."
    ),
}


def source_control_business_operations() -> frozenset[str]:
    return frozenset(_CONTRACTS)


def source_control_business_read_operations() -> frozenset[str]:
    return frozenset({SOURCE_CONTROL_GET_SOURCE_FILES_URI, SOURCE_CONTROL_GET_STATUS_URI})


def source_control_business_draft_operations() -> frozenset[str]:
    return frozenset(
        operation
        for operation, row in _CONTRACTS.items()
        if row["execution_shape"] == "isolated_draft_external"
    )


def source_control_business_versions(operation: str) -> tuple[str, ...]:
    if operation not in _CONTRACTS:
        raise ValueError("unsupported source-control business operation")
    return _VERSIONS


def source_control_business_catalog_rows() -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "api": operation,
            "intent": _INTENTS[operation],
            "supported_versions": list(source_control_business_versions(operation)),
        }
        for operation in sorted(_CONTRACTS)
    )


def source_control_business_contract_data(
    operation: str,
    version: str,
) -> dict[str, Any]:
    try:
        row = _CONTRACTS[operation]
    except KeyError as exc:
        raise ValueError("unsupported source-control business operation") from exc
    if version not in _VERSIONS:
        raise ValueError("source-control operation is unavailable in this version")
    shape = row["execution_shape"]
    payload: dict[str, Any] = {
        "contract": SOURCE_CONTROL_BUSINESS_CONTRACT,
        "operation": operation,
        "version": version,
        "input_mode": "business_declaration",
        "execution_shape": shape,
        "declaration": {
            "required_fields": list(row["required_fields"]),
            "optional_fields": list(row["optional_fields"]),
            "field_types": dict(row["field_types"]),
            "file_locator_forms": [
                "project-relative",
                "originals-relative",
                "exact-user-path-under-io-root",
            ],
        },
        "binding": {
            "roles": [],
            "role_required": False,
            "identity": "exact_file_locator_or_live_project_root",
        },
        "native_request_input": "forbidden",
        "legacy_typed_call_public": False,
        "safety": {
            "path_localization": "gateway_owned_pathlib",
            "symlink_and_reparse": "forbidden",
            "result_bound": True,
            "automatic_retry": False,
        },
    }
    if operation not in {SOURCE_CONTROL_GET_SOURCE_FILES_URI, SOURCE_CONTROL_MOVE_URI, SOURCE_CONTROL_SET_PROVIDER_URI}:
        payload["binding"]["identity"] = "exact_file_locator_or_bound_object_file_accessor"
        payload["declaration"]["required_fields"].remove("files")
        payload["declaration"]["optional_fields"].extend(("files", "object_files"))
        payload["declaration"]["field_types"]["object_files"] = "bound_object_file_scopes"
        from .source_control_object_files import MAX_SOURCE_CONTROL_OBJECT_SCOPES
        payload["declaration"]["object_file_scopes"] = {
            "containing-file": {"cli": "--object-file <Object Handle>", "derived_from": "filePath"},
            "original-media": {"cli": "--original-media-object <AudioFileSource Handle>", "derived_from": "originalFilePath",
                               "sound_source_and_language_selection": "unfinished; bind the exact AudioFileSource instead"},
            "maximum_scopes": MAX_SOURCE_CONTROL_OBJECT_SCOPES,
            "file_input": "one_or_more_file_locators_or_object_file_scopes",
            "binding": "GUID_name_type_path_exact_accessor_and_ordinary_file_stat_rechecked_before_execution",
            "file_stat_scope": "device_inode_size_mtime_mode; not_file_content_or_provider_effect_proof",
        }
    if operation == SOURCE_CONTROL_GET_SOURCE_FILES_URI:
        from .object_query_outputs import available_query_outputs
        payload["declaration"]["usage_output_choices"] = {
            name: {"result_field": native}
            for name, (native, _business) in available_query_outputs(version).items()
        }
        payload["declaration"]["usage_outputs"] = {
            "cli": "--usage-output <disclosed-business-output> (repeatable)",
            "implies_include_usage_objects": True,
            "explicit_no_usage_objects": "conflicts_with_nonempty_usage_outputs",
            "identity_fields": ["id", "name", "type", "path"],
            "result": "native usage fields retained exactly; missing and explicit null remain distinct",
            "availability": "versioned output vocabulary; applicability to each usage object remains native-observed",
        }
    if shape == "prohibited_boundary":
        payload["boundary"] = {
            "error_code": "SOURCE_CONTROL_PROVIDER_CONFIGURATION_REQUIRED",
            "reason": (
                "Provider selection and credentials belong to the human-owned "
                "Wwise Project Settings or an approved local credential workflow."
            ),
            "secrets_in_argv": "forbidden",
            "custom_provider_escape_hatch": "forbidden",
        }
        return payload
    if operation == SOURCE_CONTROL_GET_STATUS_URI:
        from .source_control_status_read import MAX_STATUS_FILES, MAX_STATUS_NATIVE_BYTES, MAX_STATUS_REPORT_BYTES, MAX_STATUS_ROWS
        payload["read_alternative"] = {"subcommand": "core-call",
            "gateway_argv_prefix": ["core-call", operation], "append_only_disclosed_business_fields": True,
            "file_locators": ["--project-file <relative-path>", "--originals-file <relative-path>",
                              "--exact-file <absolute-path> --io-root <approved-root>"],
            "maximum_files": MAX_STATUS_FILES, "native_bytes_per_call": MAX_STATUS_NATIVE_BYTES,
            "maximum_report_bytes": MAX_STATUS_REPORT_BYTES, "maximum_status_and_log_rows": MAX_STATUS_ROWS,
            "deadline": "one_shared_finite_Gateway_timeout; no_per_file_reset",
            "native_call_scope": "one_exact_file_per_call; native response preserved within that file call",
            "policy": "read_only_permitted", "provider_identity_and_effects": "not_verified",
            "incomplete_or_overflow": "partial_or_failure; never_complete_pass"}
    payload["start"] = {
        "subcommand": "draft-start",
        "gateway_argv": ["draft-start", operation],
        "copy_exactly": True,
        "append_arguments": "forbidden",
    }
    payload["gateway_derivations"] = [
        "live_project_and_originals_roots",
        "absolute_native_file_paths",
        "path_pair_alignment",
        "native_request",
        "exact_object_file_accessors_when_selected",
        "ordinary_file_stat_binding_when_selected",
        "result_projection_and_limit",
        "continuation",
    ]
    return payload


__all__ = [
    "SOURCE_CONTROL_ADD_URI",
    "SOURCE_CONTROL_BUSINESS_CONTRACT",
    "SOURCE_CONTROL_CHECK_OUT_URI",
    "SOURCE_CONTROL_COMMIT_URI",
    "SOURCE_CONTROL_DELETE_URI",
    "SOURCE_CONTROL_GET_SOURCE_FILES_URI",
    "SOURCE_CONTROL_GET_STATUS_URI",
    "SOURCE_CONTROL_MOVE_URI",
    "SOURCE_CONTROL_REVERT_URI",
    "SOURCE_CONTROL_SET_PROVIDER_URI",
    "source_control_business_catalog_rows",
    "source_control_business_contract_data",
    "source_control_business_draft_operations",
    "source_control_business_operations",
    "source_control_business_read_operations",
    "source_control_business_versions",
]
