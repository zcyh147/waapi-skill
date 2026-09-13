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
    ExistingObjectTarget,
    NewDescendantTarget,
    business_repair,
    resolve_semantic_kind,
)
from .object_graph_business_contracts import object_graph_business_contract_data
from .business_fields import ACTION_DURATION_FIELDS, OBJECT_BUSINESS_FIELD_TYPES
from .operation_object import (
    DEFAULT_MAX_CHILDREN_PER_NODE,
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_FIELDS_PER_NODE,
    DEFAULT_MAX_NAME_LENGTH,
    DEFAULT_MAX_NODES,
    normalize_object_list_name,
)
from .operation_plugin import (
    MAX_PLUGIN_NAME_LENGTH,
    MAX_PLUGIN_NOTES_LENGTH,
    MAX_PLUGIN_PROPERTIES,
)
from .object_capabilities import (
    object_child_capability,
    object_identity_semantics,
)
from .operation_registry import parse_operation_request


_CREATE_FIELDS = frozenset(
    {
        *OBJECT_BUSINESS_FIELD_TYPES,
        "field_values",
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
_SET_NODE_EXTENSION_FIELDS = frozenset(
    {
        "language",
        "list_behavior",
        "media_files",
        "object_list",
        "platform",
    }
)
_RTPC_FIELDS = frozenset(
    {
        "control_input_handle",
        "curve_points",
        "field_handle",
        "mode",
        "notes",
    }
)
_RTPC_SHAPES = frozenset(
    {
        "Constant",
        "Linear",
        "Log3",
        "Log2",
        "Log1",
        "InvertedSCurve",
        "SCurve",
        "Exp1",
        "Exp2",
        "Exp3",
    }
)


def _validate_declaration_graph_limits(
    session: BusinessDeclarationSession,
    *,
    include_existing_targets: bool,
) -> None:
    """Fail at the business seam before the native tree normalizer runs."""

    new_rows = {
        row.result_handle: row
        for row in session.declarations
        if isinstance(row.target, NewDescendantTarget)
    }
    existing_count = sum(
        isinstance(row.target, ExistingObjectTarget)
        for row in session.declarations
    )
    node_count = len(new_rows) + (existing_count if include_existing_targets else 0)
    if node_count > DEFAULT_MAX_NODES:
        raise _repair(
            session,
            "OBJECT_GRAPH_NODE_LIMIT_EXCEEDED",
            field="declarations",
            count=node_count,
            limit=DEFAULT_MAX_NODES,
            action="split the requested object graph into bounded atomic batches",
        )

    children_by_parent: dict[str, int] = {}
    depth_by_handle: dict[str, int] = {}
    for handle, row in new_rows.items():
        assert isinstance(row.target, NewDescendantTarget)
        parent_handle = row.target.parent_handle
        children_by_parent[parent_handle] = children_by_parent.get(parent_handle, 0) + 1
        if children_by_parent[parent_handle] > DEFAULT_MAX_CHILDREN_PER_NODE:
            raise _repair(
                session,
                "OBJECT_GRAPH_CHILD_LIMIT_EXCEEDED",
                field="declarations",
                count=children_by_parent[parent_handle],
                limit=DEFAULT_MAX_CHILDREN_PER_NODE,
                action="split this parent's requested children into bounded work",
            )
        depth = depth_by_handle.get(parent_handle, 0) + 1
        depth_by_handle[handle] = depth
        if depth > DEFAULT_MAX_DEPTH:
            raise _repair(
                session,
                "OBJECT_GRAPH_DEPTH_LIMIT_EXCEEDED",
                field="declarations",
                depth=depth,
                limit=DEFAULT_MAX_DEPTH,
                action="flatten or split the requested hierarchy",
            )
        if len(row.target.name) > DEFAULT_MAX_NAME_LENGTH:
            raise _repair(
                session,
                "OBJECT_GRAPH_NAME_LIMIT_EXCEEDED",
                field="name",
                limit=DEFAULT_MAX_NAME_LENGTH,
                action="provide a shorter Wwise object name",
            )


def _validate_compiled_field_limit(
    session: BusinessDeclarationSession,
    *,
    properties: list[dict[str, Any]],
    references: list[dict[str, Any]],
) -> None:
    count = len(properties) + len(references)
    if count > DEFAULT_MAX_FIELDS_PER_NODE:
        raise _repair(
            session,
            "OBJECT_GRAPH_FIELD_LIMIT_EXCEEDED",
            field="field_values",
            count=count,
            limit=DEFAULT_MAX_FIELDS_PER_NODE,
            action="split the requested field changes into a bounded batch",
        )


def _object_type_token(value: Any) -> str:
    return "".join(
        character
        for character in str(value).casefold()
        if character.isalnum()
    )


def _derived_game_sync_list(parent_type: Any, child_type: Any) -> str | None:
    pair = (_object_type_token(parent_type), _object_type_token(child_type))
    return {
        ("stategroup", "state"): "States",
        ("switchgroup", "switch"): "Switches",
    }.get(pair)


def _validate_specialized_relationship(
    session: BusinessDeclarationSession,
    *,
    parent_type: Any,
    child_type: Any,
) -> str | None:
    derived = _derived_game_sync_list(parent_type, child_type)
    capability = object_child_capability(
        version=session.context.wwise_version,
        parent_type=parent_type,
        child_types=(child_type,),
    )
    if not capability.writable_parent:
        raise _repair(
            session,
            "INVALID_CREATE_PARENT_TYPE",
            field="parent_handle",
            actual_type=str(parent_type),
            allowed_types=list(capability.allowed_parent_types),
            version=session.context.wwise_version,
            action="choose one bound Wwise container that can own new children",
        )
    if capability.invalid_child_types:
        if capability.allowed_child_types:
            raise _repair(
                session,
                "INVALID_CREATE_CHILD_TYPE_FOR_PARENT",
                field="kind",
                parent_type=str(parent_type),
                invalid_child_types=list(capability.invalid_child_types),
                allowed_child_types=list(capability.allowed_child_types),
                action="choose the reviewed child kind for this Wwise parent",
            )
        required_parents = capability.required_parent_types_for(str(child_type))
        raise _repair(
            session,
            "INVALID_CREATE_PARENT_TYPE_FOR_CHILD",
            field="parent_handle",
            actual_parent_type=str(parent_type),
            child_type=str(child_type),
            allowed_parent_types=list(required_parents),
            action="bind the reviewed Wwise parent type for this child kind",
        )
    return derived


def _compile_object_set_import(
    session: BusinessDeclarationSession,
    raw_files: Any,
) -> dict[str, Any]:
    if session.context.wwise_version not in {"2023.1", "2024.1", "2025.1"}:
        raise _repair(
            session,
            "OBJECT_SET_IMPORT_UNAVAILABLE",
            field="media_files",
            choices=["2023.1", "2024.1", "2025.1"],
            action="use audio.import for Wwise 2022.1 or run this batch on a supported lane",
        )
    if not isinstance(raw_files, list) or not 1 <= len(raw_files) <= 16:
        raise _repair(
            session,
            "OBJECT_SET_IMPORT_FILE_LIMIT_INVALID",
            field="media_files",
            valid_range={"minimum": 1, "maximum": 16},
            action="provide a bounded non-empty media file list",
        )
    files: list[dict[str, Any]] = []
    allowed = {
        "inline_wav",
        "kind",
        "language",
        "media_file",
        "originals_subfolder",
    }
    for index, raw in enumerate(raw_files):
        if not isinstance(raw, Mapping) or set(raw) - allowed:
            raise _repair(
                session,
                "OBJECT_SET_IMPORT_FILE_INVALID",
                field=f"media_files[{index}]",
                choices=sorted(allowed),
                action="provide only the disclosed exact media artifact and business fields",
            )
        has_file = "media_file" in raw
        has_inline = "inline_wav" in raw
        if has_file == has_inline:
            raise _repair(
                session,
                "OBJECT_SET_IMPORT_SOURCE_INVALID",
                field=f"media_files[{index}]",
                action="provide exactly one media_file or inline_wav artifact",
            )
        source_name = "audio_file" if has_file else "audio_file_base64"
        source = raw["media_file" if has_file else "inline_wav"]
        if not isinstance(source, str) or not source:
            raise _repair(
                session,
                "FIELD_VALUE_TYPE_MISMATCH",
                field=f"media_files[{index}]",
                action="copy the exact non-empty media artifact",
            )
        compiled: dict[str, Any] = {source_name: source}
        for public_name, native_name in (
            ("originals_subfolder", "originals_subfolder"),
            ("language", "language"),
        ):
            value = raw.get(public_name)
            if value is not None:
                if not isinstance(value, str) or not value:
                    raise _repair(
                        session,
                        "FIELD_VALUE_TYPE_MISMATCH",
                        field=f"media_files[{index}].{public_name}",
                        action=f"provide one non-empty {public_name} string",
                    )
                compiled[native_name] = value
        kind = raw.get("kind")
        if kind is not None:
            if not isinstance(kind, str):
                raise _repair(
                    session,
                    "FIELD_VALUE_TYPE_MISMATCH",
                    field=f"media_files[{index}].kind",
                    action="choose one stable semantic kind or discovered type handle",
                )
            compiled["object_type"] = _resolve_native_object_type(session, kind)
        files.append(compiled)
    return {"files": files}


def _compile_set_new_node(
    session: BusinessDeclarationSession,
    declaration: BusinessDeclaration,
) -> tuple[dict[str, Any], str | None, str | None]:
    assert isinstance(declaration.target, NewDescendantTarget)
    fields = dict(declaration.fields)
    extension_fields = {
        name: fields.pop(name)
        for name in tuple(fields)
        if name in _SET_NODE_EXTENSION_FIELDS
    }
    base = BusinessDeclaration(
        declaration_id=declaration.declaration_id,
        result_handle=declaration.result_handle,
        target=declaration.target,
        fields=fields,
    )
    node = {
        "type": _resolve_native_object_type(session, declaration.target.kind),
        "name": declaration.target.name,
        **_compile_create_fields(session, base),
    }
    platform = extension_fields.get("platform")
    if platform is not None:
        if not isinstance(platform, str) or not platform.strip():
            raise _repair(
                session,
                "FIELD_VALUE_TYPE_MISMATCH",
                field="platform",
                action="provide one exact user-requested Wwise platform",
            )
        node["platform"] = platform
    language = extension_fields.get("language")
    if language is not None:
        semantic_kind = declaration.target.kind
        is_sound = _object_type_token(node["type"]) == "sound"
        if (
            not isinstance(language, str)
            or not language
            or language.casefold() == "sfx"
            or not is_sound
            or semantic_kind == "sound-sfx"
        ):
            raise _repair(
                session,
                "OBJECT_SET_VOICE_LANGUAGE_INVALID",
                field="language",
                action="provide one exact non-SFX Project language for a Sound Voice",
            )
        node["language"] = language
    elif declaration.target.kind == "sound-voice":
        raise _repair(
            session,
            "OBJECT_SET_VOICE_LANGUAGE_REQUIRED",
            field="language",
            action="provide the exact Project language for the new Sound Voice",
        )
    if "media_files" in extension_fields:
        node["import"] = _compile_object_set_import(
            session,
            extension_fields["media_files"],
        )
    object_list = extension_fields.get("object_list")
    if object_list is not None:
        try:
            object_list = normalize_object_list_name(
                object_list,
                request_path="$.business.object_list",
            )
        except Exception as exc:
            raise _repair(
                session,
                "OBJECT_SET_LIST_NAME_INVALID",
                field="object_list",
                action="provide one exact Wwise object-list name without an @ prefix",
            ) from exc
    list_behavior = extension_fields.get("list_behavior")
    if list_behavior is not None and list_behavior not in {"append", "replace-all"}:
        raise _repair(
            session,
            "FIELD_VALUE_UNAVAILABLE",
            field="list_behavior",
            choices=["append", "replace-all"],
            action="choose one disclosed per-target object-list outcome",
        )
    if list_behavior is not None and object_list is None:
        raise _repair(
            session,
            "OBJECT_SET_LIST_NAME_REQUIRED",
            field="object_list",
            action="name the exact object list governed by this per-target outcome",
        )
    return node, object_list, list_behavior


def _apply_row_list_behavior(
    session: BusinessDeclarationSession,
    row: dict[str, Any],
    behavior: str | None,
) -> None:
    if behavior is None:
        return
    native = "append" if behavior == "append" else "replaceAll"
    existing = row.get("list_mode")
    if existing is not None and existing != native:
        raise _repair(
            session,
            "OBJECT_SET_LIST_BEHAVIOR_CONFLICT",
            field="list_behavior",
            choices=["append", "replace-all"],
            action="use one per-target list behavior for every list on that object",
        )
    row["list_mode"] = native


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


def _resolve_native_object_type(
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
    for field_name, token in ACTION_DURATION_FIELDS.items():
        if field_name not in fields:
            continue
        target = declaration.target
        object_type = (
            session.handles.resolve_object(target.object_handle).object_type
            if isinstance(target, ExistingObjectTarget)
            else _resolve_native_object_type(session, target.kind)
        )
        if object_type != "Action":
            raise _repair(session, "BUSINESS_FIELD_SCOPE_MISMATCH", field=field_name,
                          action="use Action duration fields only on Action objects")
        value = fields[field_name]
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0):
            raise _repair(session, "FIELD_VALUE_OUT_OF_RANGE", field=field_name,
                          action="provide a finite nonnegative duration in milliseconds")
        properties.append({"name": token, "value": float(value) / 1000.0})
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
    if "ignore_parent_instance_limit" in fields:
        value = fields["ignore_parent_instance_limit"]
        if type(value) is not bool:
            raise _repair(
                session,
                "FIELD_VALUE_TYPE_MISMATCH",
                field="ignore_parent_instance_limit",
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
    _validate_compiled_field_limit(
        session,
        properties=properties,
        references=references,
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
    _validate_declaration_graph_limits(
        session,
        include_existing_targets=False,
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
        if row.target.kind == "sound-voice":
            raise _repair(
                session,
                "OBJECT_CREATE_VOICE_UNAVAILABLE",
                field="kind",
                choices=["audio.import", "object.set"],
                action=(
                    "use audio.import for a media outcome or object.set with an "
                    "exact Project language for a new Sound Voice"
                ),
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
            "type": _resolve_native_object_type(session, row.target.kind),
            "name": row.target.name,
            **_compile_create_fields(session, row),
        }
        child_rows = children.get(row.result_handle, [])
        if child_rows:
            for child in child_rows:
                assert isinstance(child.target, NewDescendantTarget)
                _validate_specialized_relationship(
                    session,
                    parent_type=node["type"],
                    child_type=_resolve_native_object_type(
                        session,
                        child.target.kind,
                    ),
                )
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
    game_sync_list = _validate_specialized_relationship(
        session,
        parent_type=parent.object_type,
        child_type=root_node["type"],
    )
    if game_sync_list is not None:
        if arguments.get("on_name_conflict") == "replace":
            raise _repair(
                session,
                "OBJECT_CREATE_LIST_REPLACE_UNAVAILABLE",
                field="name_conflict",
                choices=["fail", "rename", "merge"],
                action="use object.set replace-all for destructive object-list replacement",
            )
        arguments["list"] = game_sync_list
    return parse_operation_request(
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": session.context.wwise_version,
            "operation": "object.create",
            "arguments": arguments,
        },
        expected_version=session.context.wwise_version,
    ).as_dict()


def _materialize_create_plugin(
    session: BusinessDeclarationSession,
) -> dict[str, Any]:
    if len(session.declarations) != 1:
        raise _repair(
            session,
            "DECLARATION_COUNT_INVALID",
            field="declarations",
            count=len(session.declarations),
            action="declare exactly one plug-in creation outcome",
        )
    declaration = session.declarations[0]
    if not isinstance(declaration.target, ExistingObjectTarget):
        raise _repair(
            session,
            "TARGET_FORM_INVALID",
            field="object_handle",
            action="bind the exact plug-in owner object",
        )
    fields = dict(declaration.fields)
    required = {"plugin_name", "plugin_role", "plugin_type_handle"}
    optional = {"field_values", "language", "notes", "platform"}
    missing = sorted(required - set(fields))
    unexpected = sorted(set(fields) - required - optional)
    if missing:
        raise _repair(
            session,
            "REQUIRED_FIELD_MISSING",
            field=missing[0],
            missing=missing,
            action="submit one complete plug-in business declaration",
        )
    if unexpected:
        raise _repair(
            session,
            "OBJECT_GRAPH_FIELD_UNAVAILABLE",
            field=unexpected[0],
            action="use only the disclosed plug-in business fields",
        )
    role = fields["plugin_role"]
    if role not in {"source", "effect"}:
        raise _repair(
            session,
            "FIELD_VALUE_UNAVAILABLE",
            field="plugin_role",
            choices=["source", "effect"],
            action="choose the requested Wwise plug-in role",
        )
    type_handle = session.handles.resolve_type(fields["plugin_type_handle"])
    accepted_categories = (
        {"source"} if role == "source" else {"effect", "audiodevice"}
    )
    if type_handle.type_category.casefold() not in accepted_categories:
        raise _repair(
            session,
            "TYPE_HANDLE_ROLE_MISMATCH",
            field="plugin_type_handle",
            rejected_handle=type_handle.handle,
            expected_role=role,
            action="discover a plug-in type for the exact requested role",
        )
    plugin_name = fields["plugin_name"]
    if (
        not isinstance(plugin_name, str)
        or not plugin_name
        or len(plugin_name) > MAX_PLUGIN_NAME_LENGTH
        or any(character in plugin_name for character in "\\/:*?\"<>|")
    ):
        raise _repair(
            session,
            "PLUGIN_NAME_INVALID",
            field="plugin_name",
            limit=MAX_PLUGIN_NAME_LENGTH,
            action="provide one bounded plug-in name without path syntax",
        )
    target = session.handles.resolve_object(declaration.target.object_handle)
    plugin: dict[str, Any] = {
        "kind": role,
        "name": plugin_name,
        "class_id": type_handle.class_id,
    }
    for name in ("notes", "platform"):
        value = fields.get(name)
        if value is not None:
            if not isinstance(value, str):
                raise _repair(
                    session,
                    "FIELD_VALUE_TYPE_MISMATCH",
                    field=name,
                    action=f"provide one exact {name} string",
                )
            if name == "notes" and len(value) > MAX_PLUGIN_NOTES_LENGTH:
                raise _repair(
                    session,
                    "PLUGIN_NOTES_LIMIT_EXCEEDED",
                    field="notes",
                    limit=MAX_PLUGIN_NOTES_LENGTH,
                    action="provide shorter exact plug-in notes",
                )
            plugin[name] = value
    language = fields.get("language")
    if language is not None:
        if role != "source":
            raise _repair(
                session,
                "BUSINESS_FIELD_UNAVAILABLE",
                field="language",
                action="omit language for an Effect plug-in",
            )
        if not isinstance(language, str) or not language:
            raise _repair(
                session,
                "FIELD_VALUE_TYPE_MISMATCH",
                field="language",
                action="provide one exact Wwise Source language",
            )
        if (
            target.object_type.casefold() == "sound"
            and target.semantic_kind != "sound-voice"
        ):
            raise _repair(
                session,
                "PLUGIN_LANGUAGE_UNAVAILABLE",
                field="language",
                action="omit language for a Source on a Sound SFX",
            )
        if language.casefold() == "sfx":
            raise _repair(
                session,
                "PLUGIN_LANGUAGE_INVALID",
                field="language",
                action="provide one exact non-SFX Project language for a Sound Voice",
            )
        plugin["language"] = language
    dynamic = fields.get("field_values", {})
    if not isinstance(dynamic, Mapping):
        raise _repair(
            session,
            "FIELD_VALUE_TYPE_MISMATCH",
            field="field_values",
            action="provide one bounded Field Handle to business value map",
        )
    properties: list[dict[str, Any]] = []
    for handle, business_value in dynamic.items():
        field = session.handles.bound_field(handle)
        if (
            field.scope_kind != "class"
            or field.scope_value not in {type_handle.class_id, type_handle.name}
            or field.field_kind != "property"
        ):
            raise _repair(
                session,
                "FIELD_HANDLE_SCOPE_MISMATCH",
                field="field_values",
                rejected_handle=field.handle,
                action="discover the property for the selected plug-in type",
            )
        properties.append(
            {
                "name": field.token,
                "value": session.handles.validate_field_value(
                    field,
                    business_value,
                ),
            }
        )
    if len(properties) > MAX_PLUGIN_PROPERTIES:
        raise _repair(
            session,
            "PLUGIN_PROPERTY_LIMIT_EXCEEDED",
            field="field_values",
            count=len(properties),
            limit=MAX_PLUGIN_PROPERTIES,
            action="split plug-in property work into a bounded request",
        )
    if properties:
        plugin["properties"] = properties
    return parse_operation_request(
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": session.context.wwise_version,
            "operation": "object.createPlugin",
            "arguments": {
                "target": {"kind": "id", "value": target.object_id},
                "plugin": plugin,
            },
        },
        expected_version=session.context.wwise_version,
    ).as_dict()


def _compile_existing_set_fields(
    session: BusinessDeclarationSession,
    declaration: BusinessDeclaration,
) -> dict[str, Any]:
    assert isinstance(declaration.target, ExistingObjectTarget)
    source = session.handles.resolve_object(declaration.target.object_handle)
    fields = dict(declaration.fields)
    allowed = {
        *_CREATE_FIELDS,
        "clear_object_lists",
        "list_behavior",
        "media_files",
        "new_name",
        "platform",
    }
    unexpected = sorted(set(fields) - allowed)
    if unexpected:
        raise _repair(
            session,
            "OBJECT_GRAPH_FIELD_UNAVAILABLE",
            field=unexpected[0],
            action="use one disclosed bulk object business field",
        )
    stable_fields = {
        name: value
        for name, value in fields.items()
        if name
        not in {
            "clear_object_lists",
            "field_values",
            "list_behavior",
            "media_files",
            "new_name",
            "platform",
        }
    }
    stable_declaration = BusinessDeclaration(
        declaration_id=declaration.declaration_id,
        result_handle=declaration.result_handle,
        target=declaration.target,
        fields=stable_fields,
    )
    compiled = _compile_create_fields(session, stable_declaration)
    if "new_name" in fields:
        semantics = object_identity_semantics(source.object_type)
        if not semantics.mutable_intrinsic_name:
            raise _repair(
                session,
                "DERIVED_OBJECT_NAME_BOUNDARY",
                field="new_name",
                object_type=source.object_type,
                name_mode=semantics.name_mode,
                display_identity_source=semantics.display_identity_source,
                object_handle=source.handle,
                action=(
                    "remove new_name and keep only outcomes supported by this "
                    "bound Wwise object type"
                ),
            )
        new_name = fields["new_name"]
        if not isinstance(new_name, str) or not new_name:
            raise _repair(
                session,
                "FIELD_VALUE_TYPE_MISMATCH",
                field="new_name",
                action="provide one non-empty new object name",
            )
        compiled["name"] = new_name
    platform = fields.get("platform")
    if platform is not None:
        if not isinstance(platform, str) or not platform.strip():
            raise _repair(
                session,
                "FIELD_VALUE_TYPE_MISMATCH",
                field="platform",
                action="provide one exact user-requested Wwise platform",
            )
        compiled["platform"] = platform
    if "media_files" in fields:
        compiled["import"] = _compile_object_set_import(
            session,
            fields["media_files"],
        )
    list_behavior = fields.get("list_behavior")
    if list_behavior is not None and list_behavior not in {"append", "replace-all"}:
        raise _repair(
            session,
            "FIELD_VALUE_UNAVAILABLE",
            field="list_behavior",
            choices=["append", "replace-all"],
            action="choose one disclosed per-target object-list outcome",
        )
    raw_clears = fields.get("clear_object_lists")
    if raw_clears is not None:
        if (
            not isinstance(raw_clears, list)
            or not 1 <= len(raw_clears) <= DEFAULT_MAX_CHILDREN_PER_NODE
        ):
            raise _repair(
                session,
                "OBJECT_SET_LIST_CLEAR_LIMIT_INVALID",
                field="clear_object_lists",
                valid_range={
                    "minimum": 1,
                    "maximum": DEFAULT_MAX_CHILDREN_PER_NODE,
                },
                action="provide one bounded non-empty exact object-list name set",
            )
        if list_behavior != "replace-all":
            raise _repair(
                session,
                "OBJECT_SET_EMPTY_LIST_REQUIRES_REPLACE",
                field="list_behavior",
                action="choose replace-all before clearing an exact object list",
            )
        names: list[str] = []
        for index, value in enumerate(raw_clears):
            try:
                name = normalize_object_list_name(
                    value,
                    request_path=f"$.business.clear_object_lists[{index}]",
                )
            except Exception as exc:
                raise _repair(
                    session,
                    "OBJECT_SET_LIST_NAME_INVALID",
                    field="clear_object_lists",
                    action="provide exact Wwise object-list names without @ prefixes",
                ) from exc
            if name.casefold() in {item.casefold() for item in names}:
                raise _repair(
                    session,
                    "OBJECT_SET_LIST_DUPLICATE",
                    field="clear_object_lists",
                    action="name each exact object list once",
                )
            names.append(name)
        compiled["lists"] = [
            {"name": name, "objects": []}
            for name in names
        ]
    if list_behavior is not None:
        compiled["list_mode"] = (
            "append" if list_behavior == "append" else "replaceAll"
        )
    properties = list(compiled.pop("properties", []))
    references = list(compiled.pop("references", []))
    used_tokens = {row["name"] for row in (*properties, *references)}
    platforms: set[str | int] = set()
    dynamic = fields.get("field_values", {})
    if not isinstance(dynamic, Mapping):
        raise _repair(
            session,
            "FIELD_VALUE_TYPE_MISMATCH",
            field="field_values",
            action="provide one bounded Field Handle to business value map",
        )
    for handle, business_value in dynamic.items():
        field = session.handles.bound_field(handle)
        if (
            field.scope_kind != "object"
            or str(field.scope_value).upper() != source.object_id.upper()
        ):
            raise _repair(
                session,
                "FIELD_HANDLE_SCOPE_MISMATCH",
                field="field_values",
                rejected_handle=field.handle,
                action="discover each field for its exact bulk-set target",
            )
        if field.token in used_tokens:
            raise _repair(
                session,
                "OBJECT_GRAPH_FIELD_CONFLICT",
                field="field_values",
                action="set one business meaning through one field only",
            )
        used_tokens.add(field.token)
        if field.platform is not None:
            platforms.add(field.platform)
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
    _validate_compiled_field_limit(
        session,
        properties=properties,
        references=references,
    )
    if len(platforms) > 1:
        raise _repair(
            session,
            "OBJECT_SET_PLATFORM_CONFLICT",
            field="field_values",
            platforms=sorted(str(value) for value in platforms),
            action="use one platform view per exact object in this atomic batch",
        )
    if platforms:
        discovered_platform = next(iter(platforms))
        if "platform" in compiled and compiled["platform"] != discovered_platform:
            raise _repair(
                session,
                "OBJECT_SET_PLATFORM_CONFLICT",
                field="platform",
                platforms=[compiled["platform"], discovered_platform],
                action="use the same exact platform for the row and its discovered fields",
            )
        compiled["platform"] = discovered_platform
    if properties:
        compiled["properties"] = properties
    if references:
        compiled["references"] = references
    return compiled


def _materialize_set(
    session: BusinessDeclarationSession,
) -> dict[str, Any]:
    if not session.declarations:
        raise _repair(
            session,
            "BUSINESS_DECLARATION_INCOMPLETE",
            field="declarations",
            action="declare at least one bulk object outcome",
        )
    _validate_declaration_graph_limits(
        session,
        include_existing_targets=True,
    )
    new_by_result = {
        row.result_handle: row
        for row in session.declarations
        if isinstance(row.target, NewDescendantTarget)
    }
    planned_children: dict[str, list[BusinessDeclaration]] = {}
    root_new: list[BusinessDeclaration] = []
    for row in new_by_result.values():
        assert isinstance(row.target, NewDescendantTarget)
        if row.target.parent_handle in new_by_result:
            planned_children.setdefault(row.target.parent_handle, []).append(row)
        else:
            root_new.append(row)

    def compile_node(
        row: BusinessDeclaration,
        *,
        allow_object_list: bool,
    ) -> tuple[dict[str, Any], str | None, str | None]:
        assert isinstance(row.target, NewDescendantTarget)
        node, object_list, list_behavior = _compile_set_new_node(session, row)
        if not allow_object_list and object_list is not None:
            raise _repair(
                session,
                "OBJECT_SET_NESTED_LIST_UNAVAILABLE",
                field="object_list",
                action="put object-list roots directly under one bound existing owner",
            )
        descendants = planned_children.get(row.result_handle, [])
        if descendants:
            for child in descendants:
                assert isinstance(child.target, NewDescendantTarget)
                _validate_specialized_relationship(
                    session,
                    parent_type=node["type"],
                    child_type=_resolve_native_object_type(
                        session,
                        child.target.kind,
                    ),
                )
            node["children"] = [
                compile_node(child, allow_object_list=False)[0]
                for child in descendants
            ]
        return node, object_list, list_behavior

    rows: list[dict[str, Any]] = []
    rows_by_handle: dict[str, dict[str, Any]] = {}
    for declaration in session.declarations:
        if not isinstance(declaration.target, ExistingObjectTarget):
            continue
        handle = declaration.target.object_handle
        if handle in rows_by_handle:
            raise _repair(
                session,
                "OBJECT_SET_TARGET_DUPLICATE",
                field="object_handle",
                action="combine one exact object's outcomes in one declaration",
            )
        source = session.handles.resolve_object(handle)
        row = {
            "object": {"kind": "id", "value": source.object_id},
            **_compile_existing_set_fields(session, declaration),
        }
        rows_by_handle[handle] = row
        rows.append(row)
    for declaration in root_new:
        assert isinstance(declaration.target, NewDescendantTarget)
        parent_handle = declaration.target.parent_handle
        parent = session.handles.resolve_object(parent_handle)
        row = rows_by_handle.get(parent_handle)
        if row is None:
            row = {"object": {"kind": "id", "value": parent.object_id}}
            rows_by_handle[parent_handle] = row
            rows.append(row)
        node, object_list, list_behavior = compile_node(
            declaration,
            allow_object_list=True,
        )
        specialized = _validate_specialized_relationship(
            session,
            parent_type=parent.object_type,
            child_type=node["type"],
        )
        if specialized is not None and object_list not in {None, specialized}:
            raise _repair(
                session,
                "OBJECT_GRAPH_RELATIONSHIP_INVALID",
                field="object_list",
                choices=[specialized],
                action="use the canonical Wwise Game Sync list for this value kind",
            )
        effective_list = object_list or specialized
        if effective_list is None:
            row.setdefault("children", []).append(node)
        else:
            _apply_row_list_behavior(session, row, list_behavior)
            lists = row.setdefault("lists", [])
            existing = next(
                (item for item in lists if item["name"] == effective_list),
                None,
            )
            if existing is None:
                existing = {"name": effective_list, "objects": []}
                lists.append(existing)
            existing["objects"].append(node)
    for row in rows:
        if set(row) <= {"object", "list_mode"}:
            raise _repair(
                session,
                "BUSINESS_DECLARATION_INCOMPLETE",
                field="declarations",
                action="give every exact target at least one requested outcome",
            )
    settings = dict(session.settings)
    allowed_settings = {"add_to_source_control", "list_behavior", "name_conflict"}
    unexpected_settings = sorted(set(settings) - allowed_settings)
    if unexpected_settings:
        raise _repair(
            session,
            "OBJECT_GRAPH_SETTING_UNAVAILABLE",
            field=unexpected_settings[0],
            action="use one disclosed object.set batch setting",
        )
    arguments: dict[str, Any] = {"objects": rows}
    conflict = settings.get("name_conflict", "fail")
    if conflict not in {"fail", "rename", "merge"}:
        raise _repair(
            session,
            "FIELD_VALUE_UNAVAILABLE",
            field="name_conflict",
            choices=["fail", "rename", "merge"],
            action="choose one disclosed child collision outcome",
        )
    if conflict != "fail":
        arguments["on_name_conflict"] = conflict
    list_behavior = settings.get("list_behavior", "append")
    if list_behavior not in {"append", "replace-all"}:
        raise _repair(
            session,
            "FIELD_VALUE_UNAVAILABLE",
            field="list_behavior",
            choices=["append", "replace-all"],
            action="choose one disclosed object-list outcome",
        )
    if list_behavior == "replace-all":
        arguments["list_mode"] = "replaceAll"
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
            arguments["auto_add_to_source_control"] = True
    return parse_operation_request(
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": session.context.wwise_version,
            "operation": "object.set",
            "arguments": arguments,
        },
        expected_version=session.context.wwise_version,
    ).as_dict()


def _materialize_set_rtpc(
    session: BusinessDeclarationSession,
) -> dict[str, Any]:
    if len(session.declarations) != 1:
        raise _repair(
            session,
            "DECLARATION_COUNT_INVALID",
            field="declarations",
            count=len(session.declarations),
            action="declare exactly one RTPC curve outcome",
        )
    declaration = session.declarations[0]
    if not isinstance(declaration.target, ExistingObjectTarget):
        raise _repair(
            session,
            "TARGET_FORM_INVALID",
            field="object_handle",
            action="bind the exact RTPC owner object",
        )
    fields = dict(declaration.fields)
    required = {"control_input_handle", "curve_points", "field_handle"}
    optional = {"mode", "notes"}
    missing = sorted(required - set(fields))
    unexpected = sorted(set(fields) - required - optional)
    if missing:
        raise _repair(
            session,
            "REQUIRED_FIELD_MISSING",
            field=missing[0],
            missing=missing,
            action="submit one complete RTPC business declaration",
        )
    if unexpected:
        raise _repair(
            session,
            "OBJECT_GRAPH_FIELD_UNAVAILABLE",
            field=unexpected[0],
            action="use only the disclosed RTPC business fields",
        )
    target = session.handles.resolve_object(declaration.target.object_handle)
    control = session.handles.resolve_object(fields["control_input_handle"])
    control_token = "".join(
        character
        for character in control.object_type.casefold()
        if character.isalnum()
    )
    if control_token not in {
        "gameparameter",
        "midiparameter",
        "modulatorlfo",
        "modulatorenvelope",
        "modulatortime",
    }:
        raise _repair(
            session,
            "CONTROL_INPUT_TYPE_MISMATCH",
            field="control_input_handle",
            actual_type=control.object_type,
            action="choose a bound Game Parameter, MIDI parameter, or Modulator",
        )
    field = session.handles.bound_field(fields["field_handle"])
    if (
        field.scope_kind != "object"
        or str(field.scope_value).upper() != target.object_id.upper()
        or field.field_kind != "property"
    ):
        raise _repair(
            session,
            "FIELD_HANDLE_SCOPE_MISMATCH",
            field="field_handle",
            rejected_handle=field.handle,
            action="discover the RTPC property for the exact owner object",
        )
    raw_points = fields["curve_points"]
    if (
        not isinstance(raw_points, list)
        or not 1 <= len(raw_points) <= 256
    ):
        raise _repair(
            session,
            "RTPC_POINT_LIMIT_INVALID",
            field="curve_points",
            valid_range={"minimum": 1, "maximum": 256},
            action="provide a bounded non-empty curve",
        )
    points: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_points):
        if not isinstance(raw, Mapping) or set(raw) != {"x", "y", "shape"}:
            raise _repair(
                session,
                "RTPC_POINT_INVALID",
                field=f"curve_points[{index}]",
                action="provide x, y, and one disclosed Wwise curve shape",
            )
        x = raw["x"]
        y = raw["y"]
        shape = raw["shape"]
        if (
            isinstance(x, bool)
            or not isinstance(x, (int, float))
            or not math.isfinite(float(x))
            or isinstance(y, bool)
            or not isinstance(y, (int, float))
            or not math.isfinite(float(y))
            or shape not in _RTPC_SHAPES
        ):
            raise _repair(
                session,
                "RTPC_POINT_INVALID",
                field=f"curve_points[{index}]",
                choices=sorted(_RTPC_SHAPES),
                action="provide finite x/y values and one disclosed Wwise shape",
            )
        session.handles.validate_field_value(field, y)
        points.append({"x": x, "y": y, "shape": shape})
    # Wwise stores shape on the outgoing segment and canonicalizes the terminal
    # point to Linear because it has no following segment.  Own that wire
    # detail here so the immutable Preview and live readback remain identical.
    points[-1] = {**points[-1], "shape": "Linear"}
    mode = fields.get("mode", "add-or-update")
    if mode not in {"add-only", "add-or-update"}:
        raise _repair(
            session,
            "FIELD_VALUE_UNAVAILABLE",
            field="mode",
            choices=["add-only", "add-or-update"],
            action="choose whether an exact existing curve may be updated",
        )
    arguments: dict[str, Any] = {
        "object": {"kind": "id", "value": target.object_id},
        "property": field.token,
        "control_input": {"kind": "id", "value": control.object_id},
        "points": points,
        "mode": "add" if mode == "add-only" else "add_or_replace",
    }
    notes = fields.get("notes")
    if notes is not None:
        if not isinstance(notes, str):
            raise _repair(
                session,
                "FIELD_VALUE_TYPE_MISMATCH",
                field="notes",
                action="provide exact RTPC notes or omit them",
            )
        arguments["notes"] = notes
    return parse_operation_request(
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": session.context.wwise_version,
            "operation": "object.setRTPC",
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
    if operation == "object.createPlugin":
        return _materialize_create_plugin(session)
    if operation == "object.setRTPC":
        return _materialize_set_rtpc(session)
    if operation == "object.set":
        return _materialize_set(session)
    raise ValueError("object graph business operation is not migrated yet")


__all__ = ["materialize_object_graph_business_request"]
