"""Compile bound property/reference meanings into closed object mutations."""

from __future__ import annotations

from typing import Any, Mapping

from .business_declaration_state import BusinessDeclarationSession
from .business_declarations import (
    BoundFieldHandle,
    BusinessDeclarationError,
    ExistingObjectTarget,
    business_repair,
)
from .object_metadata_business_contracts import (
    object_metadata_business_contract_data,
)
from .operation_registry import parse_operation_request


_NATIVE_FIELD_NAMES = {
    "object",
    "property",
    "reference",
    "platform",
    "value",
    "target",
    "linked",
}


def _object_for_handle(
    session: BusinessDeclarationSession,
    handle: str,
    *,
    field: str,
) -> Any:
    try:
        return session.handles.resolve_object(handle)
    except BusinessDeclarationError as exc:
        repair = dict(exc.repair)
        repair["field"] = field
        repair["action"] = "bind the exact object and copy its returned handle"
        raise BusinessDeclarationError(repair) from exc
    except Exception as exc:
        raise business_repair(
            "OBJECT_HANDLE_NOT_AVAILABLE",
            field=field,
            action="bind the exact object and copy its returned handle",
        ) from exc


def _field_for_handle(
    session: BusinessDeclarationSession,
    handle: Any,
    *,
    object_id: str,
) -> BoundFieldHandle:
    try:
        field = session.handles.bound_field(handle)
    except BusinessDeclarationError:
        raise
    except Exception as exc:
        raise business_repair(
            "FIELD_HANDLE_NOT_AVAILABLE",
            field="field_handle",
            action="discover the field in this task and copy its returned handle",
        ) from exc
    if field.scope_kind != "object" or str(field.scope_value).upper() != object_id.upper():
        raise business_repair(
            "FIELD_HANDLE_SCOPE_MISMATCH",
            field="field_handle",
            rejected_handle=field.handle,
            action="discover the field for the exact target object",
        )
    return field


def _require_fields(
    operation: str,
    version: str,
    fields: Mapping[str, Any],
) -> dict[str, Any]:
    contract = object_metadata_business_contract_data(operation, version)[
        "declaration"
    ]
    required = set(contract["required_fields"]) - {"object_handle"}
    actual = set(fields)
    missing = sorted(required - actual)
    if missing:
        raise business_repair(
            "REQUIRED_FIELD_MISSING",
            field=missing[0],
            missing=missing,
            action="submit one complete disclosed field-change declaration",
        )
    native = sorted(actual & _NATIVE_FIELD_NAMES)
    if native:
        raise business_repair(
            "NATIVE_FIELD_FORBIDDEN",
            field=native[0],
            action="supply only the disclosed high-level field outcome",
        )
    unexpected = sorted(actual - required)
    if unexpected:
        raise business_repair(
            "BUSINESS_FIELD_UNAVAILABLE",
            field=unexpected[0],
            unexpected=unexpected,
            action="use only the fields disclosed by operation-schema",
        )
    return dict(fields)


def _require_field_kind(
    field: BoundFieldHandle,
    expected: str,
) -> None:
    if field.field_kind != expected:
        raise business_repair(
            "FIELD_HANDLE_KIND_MISMATCH",
            field="field_handle",
            rejected_handle=field.handle,
            expected_kind=expected,
            actual_kind=field.field_kind,
            action=f"choose one bound {expected} field handle",
        )


def materialize_object_metadata_business_request(
    operation: str,
    session: BusinessDeclarationSession,
) -> dict[str, Any]:
    """Compile one checked field outcome without public native field tokens."""

    if not isinstance(session, BusinessDeclarationSession):
        raise TypeError("session must be BusinessDeclarationSession")
    version = session.context.wwise_version
    object_metadata_business_contract_data(operation, version)
    if len(session.declarations) != 1:
        raise business_repair(
            "DECLARATION_COUNT_INVALID",
            field="declaration",
            count=len(session.declarations),
            action="submit exactly one field-change declaration",
        )
    declaration = session.declarations[0]
    if not isinstance(declaration.target, ExistingObjectTarget):
        raise business_repair(
            "TARGET_FORM_INVALID",
            field="object_handle",
            action="bind the existing target object and use its returned handle",
        )
    source = _object_for_handle(
        session,
        declaration.target.object_handle,
        field="object_handle",
    )
    fields = _require_fields(operation, version, declaration.fields)
    field = _field_for_handle(
        session,
        fields.pop("field_handle"),
        object_id=source.object_id,
    )
    arguments: dict[str, Any] = {
        "object": {"kind": "id", "value": source.object_id},
    }
    if operation == "object.setProperty":
        _require_field_kind(field, "property")
        arguments.update(
            {
                "property": field.token,
                "value": session.handles.validate_field_value(
                    field,
                    fields.pop("business_value"),
                ),
            }
        )
    elif operation == "object.setReference":
        _require_field_kind(field, "reference")
        outcome = fields.pop("reference_outcome")
        if outcome == "clear":
            target = None
        else:
            session.handles.validate_field_value(field, outcome)
            bound_target = _object_for_handle(
                session,
                outcome,
                field="reference_outcome",
            )
            target = {"kind": "id", "value": bound_target.object_id}
        arguments.update(
            {
                "reference": field.token,
                "target": target,
            }
        )
    else:
        if field.platform is None:
            raise business_repair(
                "FIELD_PLATFORM_REQUIRED",
                field="field_handle",
                rejected_handle=field.handle,
                action="discover the field for the explicit target platform",
            )
        link_state = fields.pop("link_state")
        if link_state not in {"linked", "unlinked"}:
            raise business_repair(
                "BUSINESS_VALUE_INVALID",
                field="link_state",
                choices=["linked", "unlinked"],
                action="choose one disclosed Wwise link state",
            )
        arguments.update(
            {
                "property": field.token,
                "platform": field.platform,
                "linked": link_state == "linked",
            }
        )
    if field.platform is not None and operation != "object.setLinked":
        arguments["platform"] = field.platform
    if fields:  # pragma: no cover - contract and mapping evolve together
        raise RuntimeError("object metadata business fields are not compiled")
    return parse_operation_request(
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": version,
            "operation": operation,
            "arguments": arguments,
        },
        expected_version=version,
    ).as_dict()


__all__ = ["materialize_object_metadata_business_request"]
