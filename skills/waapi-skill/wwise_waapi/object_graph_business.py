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


_CREATE_FIELDS = frozenset(
    {
        "field_values",
        "loop",
        "max_instances",
        "notes",
        "output_bus",
        "override_parent_instance_limit",
        "volume_db",
    }
)
_CREATE_SETTINGS = frozenset(
    {
        "add_to_source_control",
        "name_conflict",
        "platform",
        "replace_owner_handle",
    }
)


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
    references: list[dict[str, Any]] = []
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
    if "max_instances" in fields:
        value = fields["max_instances"]
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 1 <= value <= 1_000_000
        ):
            raise _repair(
                session,
                "FIELD_VALUE_OUT_OF_RANGE",
                field="max_instances",
                valid_range={"minimum": 1, "maximum": 1_000_000},
                action="provide a positive bounded instance count",
            )
        properties.extend(
            [
                {"name": "UseMaxSoundPerInstance", "value": True},
                {"name": "MaxSoundPerInstance", "value": value},
            ]
        )
    if "override_parent_instance_limit" in fields:
        value = fields["override_parent_instance_limit"]
        if type(value) is not bool:
            raise _repair(
                session,
                "FIELD_VALUE_TYPE_MISMATCH",
                field="override_parent_instance_limit",
                action="provide true or false",
            )
        properties.append(
            {"name": "IgnoreParentMaxSoundInstance", "value": value}
        )
    if "output_bus" in fields:
        bus = session.handles.resolve_object(fields["output_bus"])
        if bus.object_type.casefold().replace(" ", "") not in {
            "bus",
            "audiobus",
            "auxbus",
            "auxiliarybus",
        }:
            raise _repair(
                session,
                "REFERENCE_TARGET_TYPE_MISMATCH",
                field="output_bus",
                allowed_target_types=["Bus", "AuxBus"],
                action="choose one exact bound output bus",
            )
        references.append(
            {
                "name": "OutputBus",
                "target": {"kind": "id", "value": bus.object_id},
            }
        )
    dynamic = fields.get("field_values", {})
    if not isinstance(dynamic, Mapping):
        raise _repair(
            session,
            "FIELD_VALUE_TYPE_MISMATCH",
            field="field_values",
            action="provide one bounded Field Handle to business value map",
        )
    if isinstance(declaration.target, NewDescendantTarget):
        if declaration.target.kind.startswith("bth1-"):
            bound_type = session.handles.resolve_type(declaration.target.kind)
            valid_scopes: set[str | int] = {
                bound_type.class_id,
                bound_type.name,
            }
        else:
            kind = resolve_semantic_kind(
                declaration.target.kind,
                version=session.context.wwise_version,
            )
            valid_scopes = {kind.metadata_object_type}
    else:  # pragma: no cover - object.create target guard owns this
        valid_scopes = set()
    used_tokens = {row["name"] for row in (*properties, *references)}
    for handle, business_value in dynamic.items():
        field = session.handles.bound_field(handle)
        if field.scope_kind != "class" or field.scope_value not in valid_scopes:
            raise _repair(
                session,
                "FIELD_HANDLE_SCOPE_MISMATCH",
                field="field_values",
                rejected_handle=field.handle,
                action="discover the field for this exact declared object kind",
            )
        if field.token in used_tokens:
            raise _repair(
                session,
                "OBJECT_GRAPH_FIELD_CONFLICT",
                field="field_values",
                action="set one business meaning through one field only",
            )
        used_tokens.add(field.token)
        normalized = session.handles.validate_field_value(field, business_value)
        if field.field_kind == "property":
            properties.append({"name": field.token, "value": normalized})
        else:
            target = session.handles.resolve_object(normalized)
            references.append(
                {
                    "name": field.token,
                    "target": {"kind": "id", "value": target.object_id},
                }
            )
    if properties:
        compiled["properties"] = properties
    if references:
        compiled["references"] = references
    return compiled


def _compile_create_settings(
    session: BusinessDeclarationSession,
) -> dict[str, Any]:
    settings = dict(session.settings)
    unexpected = sorted(set(settings) - _CREATE_SETTINGS)
    if unexpected:
        raise _repair(
            session,
            "OBJECT_GRAPH_SETTING_UNAVAILABLE",
            field=unexpected[0],
            choices=sorted(_CREATE_SETTINGS),
            action="use one disclosed object graph setting",
        )
    compiled: dict[str, Any] = {}
    conflict = settings.get("name_conflict", "fail")
    if conflict not in {"fail", "rename", "merge", "replace"}:
        raise _repair(
            session,
            "FIELD_VALUE_UNAVAILABLE",
            field="name_conflict",
            choices=["fail", "rename", "merge", "replace"],
            action="choose the user-requested name collision outcome",
        )
    if conflict != "fail":
        compiled["on_name_conflict"] = conflict
    replace_owner = settings.get("replace_owner_handle")
    if conflict == "replace":
        if not isinstance(replace_owner, str):
            raise _repair(
                session,
                "REPLACE_OWNERSHIP_REQUIRED",
                field="replace_owner_handle",
                action="bind the exact reviewed replacement owner",
            )
        owner = session.handles.resolve_object(replace_owner)
        compiled["replace_owned_root"] = {
            "kind": "id",
            "value": owner.object_id,
        }
    elif replace_owner is not None:
        raise _repair(
            session,
            "BUSINESS_FIELD_UNAVAILABLE",
            field="replace_owner_handle",
            action="omit replacement ownership unless replace was explicit",
        )
    add_to_source = settings.get("add_to_source_control")
    if add_to_source is not None:
        if type(add_to_source) is not bool:
            raise _repair(
                session,
                "FIELD_VALUE_TYPE_MISMATCH",
                field="add_to_source_control",
                action="provide true or false",
            )
        if add_to_source:
            compiled["auto_add_to_source_control"] = True
    platform = settings.get("platform")
    if platform is not None:
        if not isinstance(platform, str) or not platform.strip():
            raise _repair(
                session,
                "FIELD_VALUE_TYPE_MISMATCH",
                field="platform",
                action="provide one exact user-requested Wwise platform",
            )
        compiled["platform"] = platform
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
        **_compile_create_settings(session),
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
