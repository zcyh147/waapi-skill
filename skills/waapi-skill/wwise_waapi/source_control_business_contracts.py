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
            "max_results",
        ),
        "field_types": {
            "usage_scope": "source_file_usage_scope",
            "originals_folder": "safe_originals_relative_folder",
            "recursive": "boolean",
            "include_usage_objects": "boolean",
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
