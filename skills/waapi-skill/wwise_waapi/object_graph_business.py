"""Compile closed named object outcomes into canonical object operations."""

from __future__ import annotations

import math
from typing import Any, Mapping

from .business_declaration_state import (
    BusinessDeclaration,
    BusinessDeclarationSession,
)
from .business_declarations import (
    BusinessDeclarationError,
    NewDescendantTarget,
    business_repair,
    resolve_semantic_kind,
)
from .object_graph_business_contracts import object_graph_business_contract_data
from .operation_registry import parse_operation_request


_CREATE_FIELDS = frozenset({"loop", "notes", "volume_db"})


def _repair(
    session: BusinessDeclarationSession,
    error_code: str,
    *,
    field: str,
    action: str,
    **details: Any,
) -> BusinessDeclarationError:
    return business_repair(
        error_code,
        field=field,
        draft_revision=session.revision,
        action=action,
        **details,
    )


def _create_type(
    session: BusinessDeclarationSession,
    kind_name: str,
) -> str:
    if kind_name.startswith("bth1-"):
        return session.handles.resolve_type(kind_name).name
    version = session.context.wwise_version
    kind = resolve_semantic_kind(kind_name, version=version)
    if kind.name in {"sound-sfx", "sound-voice"}:
        return "Sound"
    return kind.native_object_type


def _compile_create_fields(
    session: BusinessDeclarationSession,
    declaration: BusinessDeclaration,
) -> dict[str, Any]:
    fields = dict(declaration.fields)
    unexpected = sorted(set(fields) - _CREATE_FIELDS)
    if unexpected:
        raise _repair(
            session,
            "OBJECT_GRAPH_FIELD_UNAVAILABLE",
            field=unexpected[0],
            choices=sorted(_CREATE_FIELDS),
            action="use one disclosed object graph business field",
        )
    compiled: dict[str, Any] = {}
    notes = fields.get("notes")
    if notes is not None:
        if not isinstance(notes, str):
            raise _repair(
                session,
                "FIELD_VALUE_TYPE_MISMATCH",
                field="notes",
                action="provide exact note text or omit it",
            )
        compiled["notes"] = notes
    properties: list[dict[str, Any]] = []
    if "loop" in fields:
        if fields["loop"] != "infinite":
            raise _repair(
                session,
                "FIELD_VALUE_UNAVAILABLE",
                field="loop",
                choices=["infinite"],
                action="choose Infinite or omit looping",
            )
        properties.extend(
            [
                {"name": "IsLoopingEnabled", "value": True},
                {"name": "IsLoopingInfinite", "value": True},
            ]
        )
    if "volume_db" in fields:
        value = fields["volume_db"]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or not -200.0 <= float(value) <= 200.0
        ):
            raise _repair(
                session,
                "FIELD_VALUE_OUT_OF_RANGE",
                field="volume_db",
                valid_range={"minimum": -200.0, "maximum": 200.0},
                action="provide a finite volume in decibels",
            )
        properties.append({"name": "Volume", "value": float(value)})
    if properties:
        compiled["properties"] = properties
    return compiled


def _materialize_create(
    session: BusinessDeclarationSession,
) -> dict[str, Any]:
    if not session.declarations:
        raise _repair(
            session,
            "BUSINESS_DECLARATION_INCOMPLETE",
            field="declarations",
            action="declare one complete named object hierarchy",
        )
    declarations = {row.result_handle: row for row in session.declarations}
    if len(declarations) != len(session.declarations):  # pragma: no cover
        raise RuntimeError("object graph result handles must be unique")
    roots: list[BusinessDeclaration] = []
    children: dict[str, list[BusinessDeclaration]] = {}
    for row in session.declarations:
        if not isinstance(row.target, NewDescendantTarget):
            raise _repair(
                session,
                "TARGET_FORM_INVALID",
                field="target",
                action="object.create accepts only named new-object declarations",
            )
        parent_handle = row.target.parent_handle
        if parent_handle in declarations:
            children.setdefault(parent_handle, []).append(row)
        else:
            session.handles.resolve_object(parent_handle)
            roots.append(row)
    if len(roots) != 1:
        raise _repair(
            session,
            "OBJECT_CREATE_ROOT_COUNT_INVALID",
            field="declarations",
            root_count=len(roots),
            action="declare exactly one new root and its descendants",
        )

    def compile_node(row: BusinessDeclaration) -> dict[str, Any]:
        assert isinstance(row.target, NewDescendantTarget)
        node = {
            "type": _create_type(session, row.target.kind),
            "name": row.target.name,
            **_compile_create_fields(session, row),
        }
        child_rows = children.get(row.result_handle, [])
        if child_rows:
            node["children"] = [compile_node(child) for child in child_rows]
        return node

    root = roots[0]
    assert isinstance(root.target, NewDescendantTarget)
    parent = session.handles.resolve_object(root.target.parent_handle)
    root_node = compile_node(root)
    arguments: dict[str, Any] = {
        "parent": {"kind": "id", "value": parent.object_id},
        **root_node,
    }
    return parse_operation_request(
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": session.context.wwise_version,
            "operation": "object.create",
            "arguments": arguments,
        },
        expected_version=session.context.wwise_version,
    ).as_dict()


def materialize_object_graph_business_request(
    operation: str,
    session: BusinessDeclarationSession,
) -> Mapping[str, Any]:
    """Compile one object graph business session without public native fields."""

    if not isinstance(session, BusinessDeclarationSession):
        raise TypeError("session must be BusinessDeclarationSession")
    object_graph_business_contract_data(operation, session.context.wwise_version)
    if operation == "object.create":
        return _materialize_create(session)
    raise ValueError("object graph business operation is not migrated yet")


__all__ = ["materialize_object_graph_business_request"]
