"""Closed business contracts for simple existing-object lifecycle changes."""

from __future__ import annotations

from typing import Any

from .business_declarations import SUPPORTED_WWISE_VERSIONS
from .operation_import import AUTO_CHECK_OUT_TO_SOURCE_CONTROL_VERSIONS


OBJECT_LIFECYCLE_BUSINESS_CONTRACT = (
    "waapi-skill.object-lifecycle-business/v1"
)

_DECLARATIONS: dict[str, dict[str, Any]] = {
    "object.copy": {
        "required_fields": ["object_handle", "parent_handle"],
        "optional_fields": [
            "name_conflict",
            "add_to_source_control",
            "check_out_from_source_control",
        ],
        "field_types": {
            "object_handle": "bound_object_handle",
            "parent_handle": "bound_object_handle",
            "name_conflict": "fail_or_rename",
            "add_to_source_control": "boolean",
            "check_out_from_source_control": "boolean",
        },
    },
    "object.delete": {
        "required_fields": ["object_handle"],
        "optional_fields": ["check_out_from_source_control"],
        "field_types": {
            "object_handle": "bound_object_handle",
            "check_out_from_source_control": "boolean",
        },
    },
    "object.move": {
        "required_fields": ["object_handle", "parent_handle"],
        "optional_fields": [
            "name_conflict",
            "check_out_from_source_control",
        ],
        "field_types": {
            "object_handle": "bound_object_handle",
            "parent_handle": "bound_object_handle",
            "name_conflict": "fail_or_rename",
            "check_out_from_source_control": "boolean",
        },
    },
    "object.setName": {
        "required_fields": ["object_handle", "new_name"],
        "optional_fields": [],
        "field_types": {
            "object_handle": "bound_object_handle",
            "new_name": "string",
        },
    },
    "object.setNotes": {
        "required_fields": ["object_handle", "notes"],
        "optional_fields": [],
        "field_types": {
            "object_handle": "bound_object_handle",
            "notes": "string",
        },
    },
}


def object_lifecycle_business_contract_data(
    operation: str,
    version: str,
) -> dict[str, Any]:
    """Return the small public business shape for one exact operation lane."""

    if operation not in _DECLARATIONS:
        raise ValueError("unsupported object lifecycle business operation")
    if version not in SUPPORTED_WWISE_VERSIONS:
        raise ValueError("unsupported Wwise version")
    source = _DECLARATIONS[operation]
    optional_fields = list(source["optional_fields"])
    field_types = dict(source["field_types"])
    source_control_available = version in AUTO_CHECK_OUT_TO_SOURCE_CONTROL_VERSIONS
    if not source_control_available:
        for field in (
            "add_to_source_control",
            "check_out_from_source_control",
        ):
            if field in optional_fields:
                optional_fields.remove(field)
            field_types.pop(field, None)
    add_to_source_control_available = (
        source_control_available and operation == "object.copy"
    )
    return {
        "contract": OBJECT_LIFECYCLE_BUSINESS_CONTRACT,
        "operation": operation,
        "version": version,
        "input_mode": "business_declaration",
        "start": {
            "subcommand": "draft-start",
            "gateway_argv": ["draft-start", operation],
            "copy_exactly": True,
            "append_arguments": "forbidden",
        },
        "binding": {
            "subcommand": "draft-bind-object",
            "roles": ["object", "parent"]
            if operation in {"object.copy", "object.move"}
            else ["object"],
            "result": "copy_the_returned_bound_object_handle",
        },
        "declaration": {
            "subcommand": "draft-declare-object-change",
            "required_fields": list(source["required_fields"]),
            "optional_fields": optional_fields,
            "field_types": field_types,
        },
        "gateway_derivations": [
            "closed_object_identity",
            "native_request",
            "dependency_order",
            "preview_change_intent",
            "continuation",
        ],
        "legacy_inline_typed_public": False,
        "safety": {
            "immutable_preview": True,
            "single_execute": True,
            "object_revalidation": "exact_guid_name_type_path",
        },
        "version_features": {
            "add_to_source_control": add_to_source_control_available,
            "check_out_from_source_control": source_control_available,
        },
    }


__all__ = [
    "OBJECT_LIFECYCLE_BUSINESS_CONTRACT",
    "object_lifecycle_business_contract_data",
]
