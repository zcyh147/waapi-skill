"""Compile simple existing-object business declarations into closed requests."""

from __future__ import annotations

from typing import Any, Mapping

from .business_declaration_state import BusinessDeclarationSession
from .business_declarations import ExistingObjectTarget, business_repair
from .object_lifecycle_business_contracts import (
    object_lifecycle_business_contract_data,
)
from .operation_registry import parse_operation_request


_NATIVE_FIELD_NAMES = {
    "object",
    "parent",
    "value",
    "on_name_conflict",
    "auto_add_to_source_control",
    "auto_check_out_to_source_control",
}


def _identity_for_handle(
    session: BusinessDeclarationSession,
    handle: str,
    *,
    field: str,
) -> dict[str, str]:
    try:
        bound = session.handles.resolve_object(handle)
    except Exception as exc:
        if hasattr(exc, "repair"):
            raise
        raise business_repair(
            "OBJECT_HANDLE_NOT_AVAILABLE",
            field=field,
            action="bind the exact object and copy its returned handle",
        ) from exc
    return {"kind": "id", "value": bound.object_id}


def _require_business_fields(
    operation: str,
    version: str,
    fields: Mapping[str, Any],
) -> dict[str, Any]:
    contract = object_lifecycle_business_contract_data(operation, version)[
        "declaration"
    ]
    required = set(contract["required_fields"]) - {"object_handle"}
    optional = set(contract["optional_fields"]) - {"object_handle"}
    actual = set(fields)
    missing = sorted(required - actual)
    unexpected = sorted(actual - required - optional)
    if missing:
        raise business_repair(
            "REQUIRED_FIELD_MISSING",
            field=missing[0],
            missing=missing,
            action="submit one complete disclosed object-change declaration",
        )
    if actual & _NATIVE_FIELD_NAMES:
        raise business_repair(
            "NATIVE_FIELD_FORBIDDEN",
            field=sorted(actual & _NATIVE_FIELD_NAMES)[0],
            action="supply the corresponding high-level business field",
        )
    if unexpected:
        raise business_repair(
            "BUSINESS_FIELD_UNAVAILABLE",
            field=unexpected[0],
            unexpected=unexpected,
            action="use only the fields disclosed by operation-schema",
        )
    return dict(fields)


def materialize_object_lifecycle_business_request(
    operation: str,
    session: BusinessDeclarationSession,
) -> dict[str, Any]:
    """Compile one checked declaration without exposing native WAAPI fields."""

    if not isinstance(session, BusinessDeclarationSession):
        raise TypeError("session must be BusinessDeclarationSession")
    version = session.context.wwise_version
    object_lifecycle_business_contract_data(operation, version)
    if len(session.declarations) != 1:
        raise business_repair(
            "DECLARATION_COUNT_INVALID",
            field="declaration",
            count=len(session.declarations),
            action="submit exactly one object-change declaration",
        )
    declaration = session.declarations[0]
    if not isinstance(declaration.target, ExistingObjectTarget):
        raise business_repair(
            "TARGET_FORM_INVALID",
            field="object_handle",
            action="bind the existing object and use its returned handle",
        )
    fields = _require_business_fields(
        operation,
        version,
        declaration.fields,
    )
    arguments: dict[str, Any] = {
        "object": _identity_for_handle(
            session,
            declaration.target.object_handle,
            field="object_handle",
        )
    }
    if operation in {"object.copy", "object.move"}:
        arguments["parent"] = _identity_for_handle(
            session,
            fields.pop("parent_handle"),
            field="parent_handle",
        )
    if operation == "object.setName":
        arguments["value"] = fields.pop("new_name")
    elif operation == "object.setNotes":
        arguments["value"] = fields.pop("notes")
    if "name_conflict" in fields:
        arguments["on_name_conflict"] = fields.pop("name_conflict")
    if "add_to_source_control" in fields:
        arguments["auto_add_to_source_control"] = fields.pop(
            "add_to_source_control"
        )
    if "check_out_from_source_control" in fields:
        arguments["auto_check_out_to_source_control"] = fields.pop(
            "check_out_from_source_control"
        )
    if fields:  # pragma: no cover - contract and mapping must evolve together
        raise RuntimeError("object lifecycle business fields are not compiled")
    return parse_operation_request(
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": version,
            "operation": operation,
            "arguments": arguments,
        },
        expected_version=version,
    ).as_dict()


__all__ = ["materialize_object_lifecycle_business_request"]
