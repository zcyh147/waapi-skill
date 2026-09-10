"""Compile Switch Container assignment roles into closed requests."""

from __future__ import annotations

from typing import Any

from .business_declaration_state import BusinessDeclarationSession
from .business_declarations import (
    ExistingObjectTarget,
    bound_object_identity_for_handle,
    business_repair,
)
from .operation_registry import parse_operation_request
from .switch_assignment_business_contracts import (
    switch_assignment_business_contract_data,
)


_BUSINESS_FIELDS = {"child_handle", "state_or_switch_handle"}
_NATIVE_FIELDS = {"switch_container", "child", "state_or_switch"}


def materialize_switch_assignment_business_request(
    operation: str,
    session: BusinessDeclarationSession,
) -> dict[str, Any]:
    """Compile one three-role assignment without public native selectors."""

    if not isinstance(session, BusinessDeclarationSession):
        raise TypeError("session must be BusinessDeclarationSession")
    version = session.context.wwise_version
    switch_assignment_business_contract_data(operation, version)
    if len(session.declarations) != 1:
        raise business_repair(
            "DECLARATION_COUNT_INVALID",
            field="declaration",
            count=len(session.declarations),
            action="submit exactly one Switch Container assignment outcome",
        )
    declaration = session.declarations[0]
    if not isinstance(declaration.target, ExistingObjectTarget):
        raise business_repair(
            "TARGET_FORM_INVALID",
            field="switch_container_handle",
            action="bind the existing Switch Container and copy its handle",
        )
    fields = dict(declaration.fields)
    native = sorted(set(fields) & _NATIVE_FIELDS)
    if native:
        raise business_repair(
            "NATIVE_FIELD_FORBIDDEN",
            field=native[0],
            action="supply only the three returned business object handles",
        )
    missing = sorted(_BUSINESS_FIELDS - set(fields))
    unexpected = sorted(set(fields) - _BUSINESS_FIELDS)
    if missing:
        raise business_repair(
            "REQUIRED_FIELD_MISSING",
            field=missing[0],
            missing=missing,
            action="submit one complete three-role assignment declaration",
        )
    if unexpected:
        raise business_repair(
            "BUSINESS_FIELD_UNAVAILABLE",
            field=unexpected[0],
            unexpected=unexpected,
            action="use only the fields disclosed by operation-schema",
        )
    arguments = {
        "switch_container": bound_object_identity_for_handle(
            session.handles,
            declaration.target.object_handle,
            field="switch_container_handle",
            action=(
                "bind the exact relationship object and copy its returned handle"
            ),
        ),
        "child": bound_object_identity_for_handle(
            session.handles,
            fields["child_handle"],
            field="child_handle",
            action=(
                "bind the exact relationship object and copy its returned handle"
            ),
        ),
        "state_or_switch": bound_object_identity_for_handle(
            session.handles,
            fields["state_or_switch_handle"],
            field="state_or_switch_handle",
            action=(
                "bind the exact relationship object and copy its returned handle"
            ),
        ),
    }
    return parse_operation_request(
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": version,
            "operation": operation,
            "arguments": arguments,
        },
        expected_version=version,
    ).as_dict()


__all__ = ["materialize_switch_assignment_business_request"]
