"""Compile closed named object outcomes into canonical object operations."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Mapping

from .business_declaration_state import (
    BusinessDeclaration,
    BusinessDeclarationSession,
)
from .business_declarations import (
    BusinessDeclarationError,
    ExistingObjectTarget,
    NewDescendantTarget,
    AnonymousListTarget,
    OwnedRtpcTarget,
    business_repair,
    resolve_semantic_kind,
    require_bound_name_mutability,
)
from .object_graph_business_contracts import object_graph_business_contract_data
from .documented_list_fields import resolve_list_choice, resolve_planned_list_evidence
from .planned_references import compile_result_reference, graph_result_bindings, order_result_rows
from .business_fields import ACTION_DURATION_FIELDS, OBJECT_BUSINESS_FIELD_TYPES
from .operation_object import (
    DEFAULT_MAX_CHILDREN_PER_NODE,
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_FIELDS_PER_NODE,
    DEFAULT_MAX_NAME_LENGTH,
    DEFAULT_MAX_NODES,
    OBJECT_SET_REFERENCE_ARRAY_VERSIONS,
    RTPC_POINT_SHAPES,
    normalize_object_list_name,
    normalize_curve_points,
)
from .operation_plugin import (
    MAX_PLUGIN_NAME_LENGTH,
    MAX_PLUGIN_NOTES_LENGTH,
    MAX_PLUGIN_PROPERTIES,
    PLUGIN_KINDS,
    PLUGIN_TYPE_CATEGORIES,
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
        "clear_object_lists",
        "language",
        "list_behavior",
        "media_files",
        "object_list",
        "platform",
        "plugin_placement",
    }
)
_RTPC_FIELDS = frozenset(
    {
        "control_input_handle",
        "new_control_input",
        "curve_points",
        "field_handle",
        "mode",
        "notes",
    }
)
_RTPC_SHAPES = RTPC_POINT_SHAPES


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
    node_count = len(new_rows) + sum(isinstance(row.target, OwnedRtpcTarget) for row in session.declarations) + (existing_count if include_existing_targets else 0)
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


def _validate_specialized_relationship(
    session: BusinessDeclarationSession,
    *,
    parent_type: Any,
    child_type: Any,
) -> None:
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


def _compile_list_name(session, value, *, owner_handle):
    if not isinstance(value, str) or not value.startswith("bfh1-"):
        value = normalize_object_list_name(value, request_path="$.business.object_list")
    planned = any(row.result_handle == owner_handle and isinstance(row.target, NewDescendantTarget)
        for row in session.declarations)
    if planned:
        return resolve_planned_list_evidence(session, value, owner_handle=owner_handle)["declaration"]["name"]
    if value.startswith("bfh1-"):
        return resolve_list_choice(session, value, owner_id=session.handles.resolve_object(owner_handle).object_id).token
    return normalize_object_list_name(value, request_path="$.business.object_list")


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
        **_compile_create_fields(session, base,
            allow_reference_arrays=session.context.wwise_version in OBJECT_SET_REFERENCE_ARRAY_VERSIONS,
            allow_inline_curve=True),
    }
    placement = extension_fields.get("plugin_placement")
    if placement is not None:
        kind = session.handles.resolve_type(declaration.target.kind)
        role = kind.type_category.casefold()
        if role not in {"effect", "source"} or placement not in ({"owner"} if role == "source" else {"shareset", "owner"}):
            raise _repair(session, "TYPE_HANDLE_ROLE_MISMATCH", field="plugin_placement", action="select an Effect Type Handle with a disclosed placement or a Source Type Handle with owner placement")
        node["plugin"] = {"kind": role, "placement": placement, "name": declaration.target.name,
            "class_id": kind.class_id, "properties": node.get("properties", []),
            **({"notes": node["notes"]} if "notes" in node else {})}
    if isinstance(declaration.target, AnonymousListTarget):
        if extension_fields.get("object_list") is None:
            raise _repair(session, "ANONYMOUS_LIST_PLACEMENT_INVALID", field="object_list", action="select the certified owning List Field Handle")
        node["anonymous"] = True
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
            or (not is_sound and node.get("plugin", {}).get("kind") != "source")
            or semantic_kind == "sound-sfx"
        ):
            raise _repair(
                session,
                "OBJECT_SET_VOICE_LANGUAGE_INVALID",
                field="language",
                action="provide one exact non-SFX Project language for a Sound Voice",
            )
        if node.get("plugin", {}).get("kind") == "source":
            node["plugin"]["language"] = language
        else:
            node["language"] = language
    if node.get("plugin", {}).get("kind") == "source" and platform is not None:
        node["plugin"]["platform"] = platform
    if "media_files" in extension_fields:
        node["import"] = _compile_object_set_import(
            session,
            extension_fields["media_files"],
        )
    object_list = extension_fields.get("object_list")
    if object_list is not None:
        try:
            object_list = _compile_list_name(session, object_list, owner_handle=declaration.target.parent_handle)
        except BusinessDeclarationError:
            raise
        except (ValueError, TypeError) as exc:
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
    clears = extension_fields.get("clear_object_lists")
    if clears is not None:
        if not isinstance(clears, list) or not 1 <= len(clears) <= DEFAULT_MAX_CHILDREN_PER_NODE:
            raise _repair(session, "OBJECT_SET_LIST_CLEAR_LIMIT_INVALID", field="clear_object_lists",
                          action="name a bounded nonempty set of owned lists to clear")
        if list_behavior != "replace-all":
            raise _repair(session, "OBJECT_SET_EMPTY_LIST_REQUIRES_REPLACE", field="list_behavior",
                          action="choose replace-all before clearing an owned list")
        names = []
        for name in clears:
            try:
                names.append(_compile_list_name(session, name, owner_handle=declaration.result_handle))
            except BusinessDeclarationError:
                raise
            except (ValueError, TypeError) as exc:
                raise _repair(session, "OBJECT_SET_LIST_NAME_INVALID", field="clear_object_lists",
                              action="provide exact owned-list names without an @ prefix") from exc
        if len({name.casefold() for name in names}) != len(names):
            raise _repair(session, "OBJECT_SET_LIST_DUPLICATE", field="clear_object_lists", action="name each list once")
        node["lists"] = [{"name": name, "objects": []} for name in names]
    if list_behavior is not None and object_list is None and clears is None:
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
        native_type = session.handles.resolve_type(kind_name).name
        if native_type == "Action":
            raise _repair(
                session,
                "ACTION_CREATION_UNAVAILABLE",
                field="kind",
                action=(
                    "Action creation requires a dedicated Event-parent and derived-identity "
                    "contract; existing Actions can still be edited through object.set "
                    "or the metadata operations"
                ),
            )
        bound = session.handles.resolve_type(kind_name)
        return {"effect": "Effect", "source": "Source"}.get(bound.type_category.casefold(), native_type)
    version = session.context.wwise_version
    kind = resolve_semantic_kind(kind_name, version=version)
    if kind.name in {"sound-sfx", "sound-voice"}:
        return "Sound"
    return kind.native_object_type


def _compile_graph_field_reference(session: BusinessDeclarationSession, field: Any, value: Any, *,
                                   allow_arrays: bool, allow_inline_curve: bool) -> dict[str, Any]:
    if isinstance(value, list) and not allow_arrays:
        raise _repair(session, "NATIVE_VALUE_UNION_UNAVAILABLE", field="field_values",
                      action="string reference arrays require the pinned object.set 2023.1-2025.1 alternative; choose one bound reference or null in this lane")
    if isinstance(value, list) and field.field_kind != "list":
        raise _repair(session, "REFERENCE_LIST_EVIDENCE_REQUIRED", field="field_values",
                      action="discover this exact class's documented Lists; scalar Reference metadata does not certify array assignment")
    if field.field_kind == "list" and not isinstance(value, list):
        raise _repair(session, "LIST_VALUE_REQUIRES_BOUND_OBJECT_ARRAY", field="field_values",
                      action="use an array of selected existing Object Handles, or the owned-list construction/clear declaration")
    if isinstance(value, Mapping) and not allow_inline_curve:
        raise _repair(session, "NATIVE_VALUE_UNION_UNAVAILABLE", field="field_values",
                      action="object.create accepts one bound reference or null; complex reference values belong to available object.set lanes")
    if isinstance(value, Mapping):
        if set(value) == {"new_control_input_business"}:
            if field.scope_kind != "object" or field.field_kind != "reference" or field.token != "ControlInput":
                raise _repair(session, "INVALID_CONTROL_INPUT_PLACEMENT", field="field_values",
                    action="select the exact existing RTPC Control Input Reference Field Handle")
            from .owned_control_inputs import compile_owned_control_input
            return {"name": field.token, "target": compile_owned_control_input(session, value["new_control_input_business"])}
        if set(value) != {"curve_points"}:
            raise _repair(session, "INLINE_CURVE_INPUT_INVALID", field="field_values",
                          action="provide only curve_points; native type, IDs and field tokens remain Gateway-owned")
        points = normalize_curve_points(value["curve_points"], request_path="$.business.curve_points")
        return {"name": field.token, "target": {"curve_points": [point.as_dict() for point in points]}}
    if value is None:
        return {"name": field.token, "target": None}
    values = value if isinstance(value, list) else [value]
    if len(values) > DEFAULT_MAX_FIELDS_PER_NODE:
        raise _repair(session, "OBJECT_GRAPH_REFERENCE_LIMIT_EXCEEDED", field="field_values",
                      action="split the reference array into a bounded request")
    identities = []
    for item in values:
        if isinstance(item, str) and item.startswith("bnh1-") and field.field_kind == "reference":
            identities.append(compile_result_reference(session, field, item, native_type=_resolve_native_object_type))
            continue
        handle = (session.handles.resolve_object(item).handle if field.field_kind == "list"
                  else session.handles.validate_field_value(field, item))
        target = session.handles.resolve_object(handle)
        identities.append({"kind": "id", "value": target.object_id})
    return {"name": field.token, "target": identities if isinstance(value, list) else identities[0]}


def _apply_sound_kind_fields(session, declaration, properties):
    """Bind Voice meaning to its documented Sound scalar, not a wire alias."""
    target = declaration.target
    if not isinstance(target, NewDescendantTarget) or target.kind.startswith("bth1-"):
        return
    kind = resolve_semantic_kind(target.kind, version=session.context.wwise_version).name
    if kind not in {"sound-sfx", "sound-voice"}:
        return
    voice = kind == "sound-voice"
    explicit = [row for row in properties if row["name"].casefold() == "isvoice"]
    if any(row["value"] is not voice for row in explicit):
        raise _repair(session, "SOUND_KIND_FIELD_CONFLICT", field="field_values",
            action="choose a Sound kind consistent with the explicitly selected IsVoice value")
    if voice and not explicit:
        properties.append({"name": "IsVoice", "value": True})


def _compile_create_fields(
    session: BusinessDeclarationSession,
    declaration: BusinessDeclaration,
    *, allow_reference_arrays: bool = False,
    allow_inline_curve: bool = False,
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
    if "output_bus" in fields and isinstance(fields["output_bus"], str) and fields["output_bus"].startswith("bnh1-"):
        from types import SimpleNamespace
        reference = compile_result_reference(session, SimpleNamespace(token="OutputBus"), fields["output_bus"],
            native_type=_resolve_native_object_type, allowed_types=["Bus", "AudioBus", "AuxBus", "AuxiliaryBus"])
        references.append({"name": "OutputBus", "target": reference})
    elif "output_bus" in fields:
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
        if isinstance(business_value, Mapping) and "new_control_input_business" in business_value:
            raise _repair(session, "INVALID_CONTROL_INPUT_PLACEMENT", field="field_values", action="bind the exact existing RTPC for an owned Control Input replacement")
        if field.token in used_tokens:
            raise _repair(
                session,
                "OBJECT_GRAPH_FIELD_CONFLICT",
                field="field_values",
                action="set one business meaning through one field only",
            )
        used_tokens.add(field.token)
        if field.field_kind == "property":
            normalized = session.handles.validate_field_value(field, business_value)
            properties.append({"name": field.token, "value": normalized})
        else:
            references.append(_compile_graph_field_reference(session, field, business_value,
                allow_arrays=allow_reference_arrays, allow_inline_curve=allow_inline_curve))
    _apply_sound_kind_fields(session, declaration, properties)
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

    node_result_handles = {}

    def compile_node(row: BusinessDeclaration) -> dict[str, Any]:
        assert isinstance(row.target, NewDescendantTarget)
        fields = dict(row.fields)
        object_list = fields.pop("object_list", None)
        if object_list is not None and row is not roots[0]:
            raise _repair(
                session,
                "OBJECT_CREATE_DESCENDANT_LIST_UNAVAILABLE",
                field="object_list",
                action="object.create accepts list placement only on its root; use object.set for recursive owned lists",
            )
        base = BusinessDeclaration(
            declaration_id=row.declaration_id,
            result_handle=row.result_handle,
            target=row.target,
            fields=fields,
        )
        node = {
            "type": _resolve_native_object_type(session, row.target.kind),
            "name": row.target.name,
            **_compile_create_fields(session, base),
        }
        node_result_handles[id(node)] = row.result_handle
        if object_list is not None:
            try:
                node["list"] = (resolve_list_choice(session, object_list,
                    owner_id=session.handles.resolve_object(row.target.parent_handle).object_id).token
                    if object_list.startswith("bfh1-") else normalize_object_list_name(
                        object_list, request_path="$.business.object_list"))
            except BusinessDeclarationError:
                raise
            except (ValueError, TypeError) as exc:
                raise _repair(
                    session,
                    "OBJECT_CREATE_LIST_NAME_INVALID",
                    field="object_list",
                    action="provide one exact Wwise object-list name without an @ prefix",
                ) from exc
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
    result_bindings = graph_result_bindings([(root_node, "$")], node_result_handles)
    if result_bindings:
        arguments["graph_result_bindings"] = result_bindings
    if "list" in root_node:
        matches = [field for field in session.handles.as_dict()["fields"]
            if field["field_kind"] == "list" and field["scope_kind"] == "object"
            and field["scope_value"] == parent.object_id and field["token"] == root_node["list"]]
        if matches:
            field = resolve_list_choice(session, root_node["list"], owner_id=parent.object_id)
            arguments["documented_list_bindings"] = [dict(field.restrictions["documented_list"])]
    if "list" not in root_node:
        _validate_specialized_relationship(
            session,
            parent_type=parent.object_type,
            child_type=root_node["type"],
        )
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
    optional = {"field_values", "language", "notes", "platform", "plugin_placement"}
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
    if role not in PLUGIN_KINDS:
        raise _repair(
            session,
            "FIELD_VALUE_UNAVAILABLE",
            field="plugin_role",
            choices=["source", "effect", "sink", "metadata"],
            action="choose the requested Wwise plug-in role",
        )
    type_handle = session.handles.resolve_type(fields["plugin_type_handle"])
    accepted_categories = {PLUGIN_TYPE_CATEGORIES[role].casefold()}
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
    if "plugin_placement" in fields:
        plugin["placement"] = fields["plugin_placement"]
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
    references: list[dict[str, Any]] = []
    for handle, business_value in dynamic.items():
        field = session.handles.bound_field(handle)
        if (
            field.scope_kind != "class"
            or field.scope_value not in {type_handle.class_id, type_handle.name}
            or field.field_kind not in {"property", "reference"}
        ):
            raise _repair(
                session,
                "FIELD_HANDLE_SCOPE_MISMATCH",
                field="field_values",
                rejected_handle=field.handle,
                action="discover the property for the selected plug-in type",
            )
        value = session.handles.validate_field_value(field, business_value)
        if field.field_kind == "reference":
            chosen = session.handles.resolve_object(value)
            references.append({"name": field.token, "target": {"kind": "id", "value": chosen.object_id}})
        else:
            properties.append({"name": field.token, "value": value})
    if len(properties) + len(references) > MAX_PLUGIN_PROPERTIES:
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
    if references:
        plugin["references"] = references
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
        "name_conflict",
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
            "name_conflict",
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
    compiled = _compile_create_fields(session, stable_declaration,
        allow_reference_arrays=session.context.wwise_version in OBJECT_SET_REFERENCE_ARRAY_VERSIONS,
        allow_inline_curve=True)
    if "name_conflict" in fields:
        conflict = fields["name_conflict"]
        if conflict not in {"fail", "rename", "merge", "replace"}:
            raise _repair(
                session,
                "FIELD_VALUE_UNAVAILABLE",
                field="name_conflict",
                choices=["fail", "rename", "merge", "replace"],
                action="choose one disclosed collision outcome for this target's new children and list members",
            )
        compiled["on_name_conflict"] = conflict
    if "new_name" in fields:
        require_bound_name_mutability(source)
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
                name = (resolve_list_choice(session, value, owner_id=source.object_id).token
                    if value.startswith("bfh1-") else normalize_object_list_name(value, request_path="$.business.clear_object_lists"))
            except BusinessDeclarationError:
                raise
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
        if isinstance(business_value, Mapping) and "new_control_input_business" in business_value and source.object_type != "RTPC":
            raise _repair(session, "INVALID_CONTROL_INPUT_PLACEMENT", field="field_values", action="bind the exact existing RTPC for an owned Control Input replacement")
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
        if field.field_kind == "property":
            normalized = session.handles.validate_field_value(field, business_value)
            properties.append({"name": field.token, "value": normalized})
        else:
            references.append(_compile_graph_field_reference(session, field, business_value,
                allow_arrays=session.context.wwise_version in OBJECT_SET_REFERENCE_ARRAY_VERSIONS,
                allow_inline_curve=True))
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

    node_result_handles = {}

    def compile_rtpc(row):
        rtpc_args = _materialize_set_rtpc(replace(session, declarations=(row,)), planned_owners=new_by_result)["arguments"]
        node = {"rtpc": {key: rtpc_args[key] for key in ("property", "control_input", "points", "notes") if key in rtpc_args},
            "rtpc_mode": rtpc_args["mode"]}
        node_result_handles[id(node)] = row.result_handle
        new_input = node["rtpc"]["control_input"].get("new_control_input")
        if new_input is not None:
            from .canonical import canonical_sha256
            node_result_handles[id(new_input)] = "bnh1-" + canonical_sha256({"owned_control_input_of": row.result_handle})[:32]
        return node

    def compile_node(row: BusinessDeclaration) -> tuple[dict[str, Any], str | None, str | None]:
        assert isinstance(row.target, NewDescendantTarget)
        node, object_list, list_behavior = _compile_set_new_node(session, row)
        node_result_handles[id(node)] = row.result_handle
        descendants = planned_children.get(row.result_handle, [])
        if descendants:
            for child in descendants:
                assert isinstance(child.target, NewDescendantTarget)
                child_node, child_list, child_behavior = compile_node(child)
                if child_behavior is not None:
                    if list_behavior is not None and list_behavior != child_behavior:
                        raise _repair(session, "OBJECT_SET_LIST_BEHAVIOR_CONFLICT", field="list_behavior",
                                      action="use one inherited per-target list behavior for this graph")
                    list_behavior = child_behavior
                if child_list is None:
                    if "plugin" not in child_node:
                        _validate_specialized_relationship(session, parent_type=node["type"], child_type=child_node["type"])
                    elif child_node["plugin"]["kind"] == "source":
                        if node["type"] != "Sound":
                            raise _repair(session, "INVALID_SOURCE_TARGET", field="parent_handle", action="attach the Source plugin to a planned Sound or Voice")
                        if child_node["plugin"].get("language") is not None and not any(
                                prop["name"].casefold() == "isvoice" and prop["value"] is True for prop in node.get("properties", [])):
                            raise _repair(session, "PLUGIN_LANGUAGE_UNAVAILABLE", field="language", action="select a Voice owner for a localized Source")
                    node.setdefault("children", []).append(child_node)
                else:
                    lists = node.setdefault("lists", [])
                    descriptor = next((item for item in lists if item["name"] == child_list), None)
                    if descriptor is None:
                        descriptor = {"name": child_list, "objects": []}
                        lists.append(descriptor)
                    descriptor["objects"].append(child_node)
        rtpcs = [item for item in session.declarations if isinstance(item.target, OwnedRtpcTarget)
            and item.target.owner_handle == row.result_handle]
        if rtpcs:
            node.setdefault("lists", []).append({"name": "RTPC", "objects": [compile_rtpc(item) for item in rtpcs]})
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
        for reference in row.get("references", []):
            owned_input = reference["target"].get("new_control_input") if isinstance(reference["target"], Mapping) else None
            if owned_input is not None:
                from .canonical import canonical_sha256
                node_result_handles[id(owned_input)] = "bnh1-" + canonical_sha256({"owned_control_input_of": declaration.result_handle})[:32]
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
        node, object_list, list_behavior = compile_node(declaration)
        _apply_row_list_behavior(session, row, list_behavior)
        if object_list is None:
            if "plugin" not in node:
                _validate_specialized_relationship(session, parent_type=parent.object_type, child_type=node["type"])
            row.setdefault("children", []).append(node)
        else:
            lists = row.setdefault("lists", [])
            existing = next(
                (item for item in lists if item["name"] == object_list),
                None,
            )
            if existing is None:
                existing = {"name": object_list, "objects": []}
                lists.append(existing)
            existing["objects"].append(node)
    for declaration in session.declarations:
        if not isinstance(declaration.target, OwnedRtpcTarget):
            continue
        owner_handle = declaration.target.owner_handle
        if owner_handle in new_by_result:
            continue
        owner = session.handles.resolve_object(owner_handle)
        node = compile_rtpc(declaration)
        row = rows_by_handle.get(owner_handle)
        if row is None:
            row = {"object": {"kind": "id", "value": owner.object_id}}
            rows_by_handle[owner_handle] = row
            rows.append(row)
        lists = row.setdefault("lists", [])
        descriptor = next((item for item in lists if item["name"] == "RTPC"), None)
        if descriptor is None:
            descriptor = {"name": "RTPC", "objects": []}
            lists.append(descriptor)
        descriptor["objects"].append(node)
    for row in rows:
        if set(row) <= {"object", "list_mode"}:
            raise _repair(
                session,
                "BUSINESS_DECLARATION_INCOMPLETE",
                field="declarations",
                action="give every exact target at least one requested outcome",
            )
    settings = dict(session.settings)
    allowed_settings = {"add_to_source_control", "list_behavior", "name_conflict", "platform", "voice_source_completion"}
    if "voice_source_completion" in settings and settings["voice_source_completion"] not in {"separate-previews", "atomic-required"}:
        raise _repair(session, "FIELD_VALUE_UNAVAILABLE", field="voice_source_completion",
            action="select separate-previews for explicitly staged Voice/Source completion")
    unexpected_settings = sorted(set(settings) - allowed_settings)
    if unexpected_settings:
        raise _repair(
            session,
            "OBJECT_GRAPH_SETTING_UNAVAILABLE",
            field=unexpected_settings[0],
            action="use one disclosed object.set batch setting",
        )
    rows = order_result_rows(rows, node_result_handles, revision=session.revision)
    arguments: dict[str, Any] = {"objects": rows}
    documented_bindings = []
    for row in rows:
        for descriptor in row.get("lists", []):
            matches = [field for field in session.handles.as_dict()["fields"]
                if field["field_kind"] == "list" and field["scope_kind"] == "object"
                and field["scope_value"] == row["object"]["value"] and field["token"] == descriptor["name"]]
            if matches:
                field = resolve_list_choice(session, descriptor["name"], owner_id=row["object"]["value"])
                evidence = dict(field.restrictions["documented_list"])
                if evidence not in documented_bindings:
                    documented_bindings.append(evidence)
        for descriptor in row.get("references", []):
            candidates = [field for field in session.handles.as_dict()["fields"]
                if field["field_kind"] == "list" and field["scope_kind"] == "object"
                and field["scope_value"] == row["object"]["value"] and field["token"] == descriptor["name"]]
            if candidates:
                field = resolve_list_choice(session, descriptor["name"], owner_id=row["object"]["value"])
                evidence = {**dict(field.restrictions["documented_list"]),
                    "reference_targets": [target["value"] for target in descriptor["target"]]}
                if evidence not in documented_bindings:
                    documented_bindings.append(evidence)
    def bind_planned_occurrences(node, request_path):
        owner_handle = node_result_handles.get(id(node))
        if owner_handle is not None:
            for descriptor in node.get("lists", []):
                evidence = resolve_planned_list_evidence(session, descriptor["name"], owner_handle=owner_handle)
                documented_bindings.append({**evidence, "planned_owner": {
                    "result_handle": owner_handle, "request_path": request_path}})
            # Only this declaration's validated class-scoped List selections
            # certify arrays. Another class may expose a scalar with this token
            # (Sound.Metadata List versus MetadataSlot.Metadata Reference).
            declared_fields = [session.handles.bound_field(handle)
                for handle in (new_by_result[owner_handle].fields.get("field_values", {}) if owner_handle in new_by_result else {})]
            for reference in node.get("references", []):
                fields = [field for field in declared_fields if field.field_kind == "list"
                    and field.scope_kind == "class" and field.token == reference["name"]]
                if fields and isinstance(reference["target"], list):
                    evidence = resolve_planned_list_evidence(session, reference["name"], owner_handle=owner_handle)
                    documented_bindings.append({**evidence, "reference_targets": [target["value"] for target in reference["target"]],
                        "planned_owner": {"result_handle": owner_handle, "request_path": request_path}})
        for index, child in enumerate(node.get("children", [])):
            bind_planned_occurrences(child, f"{request_path}.children[{index}]")
        for index, descriptor in enumerate(node.get("lists", [])):
            for member_index, member in enumerate(descriptor["objects"]):
                bind_planned_occurrences(member, f"{request_path}.lists[{index}].objects[{member_index}]")
    for index, row in enumerate(rows):
        bind_planned_occurrences(row, f"$.objects[{index}]")
    result_bindings = graph_result_bindings([(row, f"$.objects[{index}]") for index, row in enumerate(rows)], node_result_handles)
    if result_bindings:
        arguments["graph_result_bindings"] = result_bindings
    if documented_bindings:
        arguments["documented_list_bindings"] = documented_bindings
    if "platform" in settings:
        platform = settings["platform"]
        if not isinstance(platform, str) or not platform.strip():
            raise _repair(
                session, "FIELD_VALUE_TYPE_MISMATCH", field="platform",
                action="provide one exact user-requested Wwise platform",
            )
        arguments["platform"] = platform
    conflict = settings.get("name_conflict", "fail")
    if conflict not in {"fail", "rename", "merge", "replace"}:
        raise _repair(
            session,
            "FIELD_VALUE_UNAVAILABLE",
            field="name_conflict",
            choices=["fail", "rename", "merge", "replace"],
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
    *, planned_owners=None,
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
    if not isinstance(declaration.target, (ExistingObjectTarget, OwnedRtpcTarget)):
        raise _repair(session, "TARGET_FORM_INVALID", field="object_handle", action="bind the exact RTPC owner")
    fields = dict(declaration.fields)
    required = {"curve_points", "field_handle"}
    optional = {"mode", "notes", "control_input_handle", "new_control_input"}
    if ("control_input_handle" in fields) == ("new_control_input" in fields):
        raise _repair(session, "CONTROL_INPUT_CHOICE_REQUIRED", field="control_input_handle", action="choose one existing or one new owned Control Input")
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
    owner_handle = (declaration.target.owner_handle if isinstance(declaration.target, OwnedRtpcTarget)
        else declaration.target.object_handle)
    planned = (planned_owners or {}).get(owner_handle)
    target = None if planned else session.handles.resolve_object(owner_handle)
    from .owned_control_inputs import compile_owned_control_input
    owned_input = compile_owned_control_input(session, fields["new_control_input"]) if "new_control_input" in fields else None
    control = None if owned_input is not None else session.handles.resolve_object(fields["control_input_handle"])
    control_token = "".join(
        character
        for character in (control.object_type.casefold() if control is not None else "")
        if character.isalnum()
    )
    if control is not None and control_token not in {
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
    if planned:
        evidence = resolve_planned_list_evidence(session if len(session.declarations) > 1 else replace(session,
            declarations=(*tuple((planned_owners or {}).values()), *session.declarations)), "RTPC", owner_handle=owner_handle)
        valid_scope = field.scope_kind == "class" and field.scope_value == evidence["scope"]["class_id"]
    else:
        valid_scope = field.scope_kind == "object" and str(field.scope_value).upper() == target.object_id.upper()
    if not valid_scope or field.field_kind != "property":
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
        "object": {"kind": "id", "value": owner_handle if planned else target.object_id},
        "property": field.token,
        "control_input": owned_input if owned_input is not None else {"kind": "id", "value": control.object_id},
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
    if isinstance(declaration.target, OwnedRtpcTarget):
        return {"arguments": arguments}
    if owned_input is not None:
        from .canonical import canonical_sha256
        path = "$.objects[0].lists[0].objects[0]"
        rtpc_handle = "bnh1-" + canonical_sha256({"owned_rtpc_of": declaration.result_handle})[:32]
        arguments["graph_result_bindings"] = [
            {"result_handle": rtpc_handle, "request_path": path},
            {"result_handle": "bnh1-" + canonical_sha256({"owned_control_input_of": rtpc_handle})[:32],
             "request_path": path + ".control_input"}]
    return parse_operation_request(
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": session.context.wwise_version,
            "operation": "object.setRTPC",
            "arguments": arguments,
        },
        expected_version=session.context.wwise_version,
    ).as_dict()


def validate_object_graph_draft(operation, session):
    """Validate editable facts without requiring a not-yet-declared List.

    This produces no request. Check/Preview always use the strict materializer
    with the original settings, so pending replaceAll never becomes append.
    """
    validation = session
    if (operation == "object.set" and session.settings.get("list_behavior") == "replace-all"
            and not any(isinstance(row.target, OwnedRtpcTarget) or "object_list" in row.fields or "clear_object_lists" in row.fields for row in session.declarations)):
        validation = replace(session, settings={**session.settings, "list_behavior": "append"})
    materialize_object_graph_business_request(operation, validation)


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
        from .voice_source_staging import lower
        return lower(_materialize_set(session), session)
    raise ValueError("object graph business operation is not migrated yet")


__all__ = ["materialize_object_graph_business_request", "validate_object_graph_draft"]
