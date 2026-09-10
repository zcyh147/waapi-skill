"""Compile reviewed generic Core declarations into canonical WAAPI calls."""

from __future__ import annotations

import math
from typing import Any, Mapping

from .business_declaration_state import BusinessDeclarationSession
from .business_declarations import business_repair
from .core_business_contracts import core_business_contract_data
from .operation_registry import parse_operation_request


_PASTE_MODES = {
    "replace": "replaceEntire",
    "merge-replace": "addReplace",
    "merge-keep": "addKeep",
}
_CURVE_KINDS = {
    "volume-dry": "VolumeDryUsage",
    "volume-wet-game": "VolumeWetGameUsage",
    "volume-wet-user": "VolumeWetUserUsage",
    "low-pass-filter": "LowPassFilterUsage",
    "high-pass-filter": "HighPassFilterUsage",
    "high-shelf": "HighShelfUsage",
    "spread": "SpreadUsage",
    "focus": "FocusUsage",
    "obstruction-volume": "ObstructionVolumeUsage",
    "obstruction-high-pass": "ObstructionHPFUsage",
    "obstruction-low-pass": "ObstructionLPFUsage",
    "obstruction-high-shelf": "ObstructionHSFUsage",
    "occlusion-volume": "OcclusionVolumeUsage",
    "occlusion-high-pass": "OcclusionHPFUsage",
    "occlusion-low-pass": "OcclusionLPFUsage",
    "occlusion-high-shelf": "OcclusionHSFUsage",
    "diffraction-volume": "DiffractionVolumeUsage",
    "diffraction-high-pass": "DiffractionHPFUsage",
    "diffraction-low-pass": "DiffractionLPFUsage",
    "diffraction-high-shelf": "DiffractionHSFUsage",
    "transmission-volume": "TransmissionVolumeUsage",
    "transmission-high-pass": "TransmissionHPFUsage",
    "transmission-low-pass": "TransmissionLPFUsage",
    "transmission-high-shelf": "TransmissionHSFUsage",
}
_CURVE_SOURCES = {
    "none": "None",
    "custom": "Custom",
    "volume-dry": "UseVolumeDry",
    "project": "UseProject",
}
_CURVE_SHAPES = {
    "constant": "Constant",
    "linear": "Linear",
    "log-3": "Log3",
    "log-2": "Log2",
    "log-1": "Log1",
    "inverted-s-curve": "InvertedSCurve",
    "s-curve": "SCurve",
    "exp-1": "Exp1",
    "exp-2": "Exp2",
    "exp-3": "Exp3",
}
_FADE_MODES = {
    "none": "None",
    "manual": "Manual",
    "automatic": "Automatic",
}


def _object_id(
    session: BusinessDeclarationSession,
    handle: Any,
    *,
    field: str,
    role: str,
) -> str:
    if not isinstance(handle, str):
        raise business_repair(
            "REQUIRED_FIELD_MISSING",
            field=field,
            action=f"bind the exact {role} object and copy its returned handle",
        )
    bound = session.handles.resolve_object(handle)
    if bound.role != role:
        raise business_repair(
            "BOUND_OBJECT_ROLE_MISMATCH",
            field=field,
            expected_role=role,
            actual_role=bound.role,
            action=f"copy the handle returned for the {role} role",
        )
    return bound.object_id


def _core_plan(session: BusinessDeclarationSession) -> Mapping[str, Any]:
    if set(session.settings) != {"core_plan"}:
        raise business_repair(
            "CORE_PLAN_INCOMPLETE",
            field="core_plan",
            action="submit the one complete Gateway-disclosed Core business plan",
        )
    plan = session.settings["core_plan"]
    if not isinstance(plan, Mapping):
        raise business_repair(
            "CORE_PLAN_INVALID",
            field="core_plan",
            action="submit the closed fields disclosed for this Core operation",
        )
    return plan


def _require_plan_fields(
    plan: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str] = frozenset(),
) -> None:
    missing = sorted(required - set(plan))
    unexpected = sorted(set(plan) - required - optional)
    if missing or unexpected:
        raise business_repair(
            "CORE_PLAN_FIELDS_INVALID",
            field="core_plan",
            missing=missing,
            unexpected=unexpected,
            action="submit exactly the fields disclosed for this Core operation",
        )


def _object_ids(
    session: BusinessDeclarationSession,
    handles: Any,
    *,
    field: str,
    role: str,
) -> list[str]:
    if (
        not isinstance(handles, list)
        or not handles
        or len(handles) > 64
        or len(handles) != len(set(handles))
    ):
        raise business_repair(
            "BUSINESS_COLLECTION_INVALID",
            field=field,
            action="provide one bounded nonempty list of unique bound object handles",
        )
    return [
        _object_id(session, handle, field=field, role=role)
        for handle in handles
    ]


def _field_token(
    session: BusinessDeclarationSession,
    handle: Any,
    *,
    field: str,
    object_id: str,
) -> str:
    if not isinstance(handle, str):
        raise business_repair(
            "REQUIRED_FIELD_MISSING",
            field=field,
            action="copy one live-discovered Field Handle",
        )
    bound = session.handles.bound_field(handle)
    if (
        bound.scope_kind != "object"
        or str(bound.scope_value).upper() != object_id.upper()
    ):
        raise business_repair(
            "FIELD_HANDLE_SCOPE_MISMATCH",
            field=field,
            rejected_handle=handle,
            action="discover the field for the exact business object",
        )
    return bound.token


def _field_tokens(
    session: BusinessDeclarationSession,
    handles: Any,
    *,
    field: str,
    object_id: str,
) -> list[str]:
    if (
        not isinstance(handles, list)
        or not handles
        or len(handles) > 64
        or len(handles) != len(set(handles))
    ):
        raise business_repair(
            "BUSINESS_COLLECTION_INVALID",
            field=field,
            action="provide one bounded nonempty list of unique Field Handles",
        )
    return [
        _field_token(
            session,
            handle,
            field=field,
            object_id=object_id,
        )
        for handle in handles
    ]


def _finite_number(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise business_repair(
            "BUSINESS_VALUE_INVALID",
            field=field,
            action="provide one finite number",
        )
    normalized = float(value)
    if not math.isfinite(normalized):
        raise business_repair(
            "BUSINESS_VALUE_INVALID",
            field=field,
            action="provide one finite number",
        )
    return normalized


def _string_list(value: Any, *, field: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or len(value) > 64
        or not all(
            isinstance(item, str)
            and item.strip()
            and len(item.encode("utf-8")) <= 256
            and not any(ord(character) < 32 or ord(character) == 127 for character in item)
            for item in value
        )
        or len(value) != len(set(value))
    ):
        raise business_repair(
            "BUSINESS_COLLECTION_INVALID",
            field=field,
            action="provide one bounded nonempty list of unique names",
        )
    return list(value)


def _business_name(value: Any, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value.encode("utf-8")) > 256
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise business_repair(
            "BUSINESS_VALUE_INVALID",
            field=field,
            action="provide one nonempty bounded business name without control characters",
        )
    return value


def _curve_points(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 64:
        raise business_repair(
            "BUSINESS_COLLECTION_INVALID",
            field="points",
            action="provide a bounded list of at most 64 curve points",
        )
    points: list[dict[str, Any]] = []
    for index, row in enumerate(value):
        if not isinstance(row, Mapping) or set(row) != {"x", "y", "shape"}:
            raise business_repair(
                "BUSINESS_VALUE_INVALID",
                field=f"points[{index}]",
                action="provide x, y, and one disclosed curve shape",
            )
        shape = _CURVE_SHAPES.get(row["shape"])
        if shape is None:
            raise business_repair(
                "BUSINESS_ENUM_INVALID",
                field=f"points[{index}].shape",
                choices=sorted(_CURVE_SHAPES),
                action="choose one disclosed curve shape",
            )
        points.append(
            {
                "x": _finite_number(row["x"], field=f"points[{index}].x"),
                "y": _finite_number(row["y"], field=f"points[{index}].y"),
                "shape": shape,
            }
        )
    return points


def _blend_edges(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != 2:
        raise business_repair(
            "BUSINESS_COLLECTION_INVALID",
            field="edges",
            action="provide exactly the left and right Blend Track edges",
        )
    edges: list[dict[str, Any]] = []
    for index, row in enumerate(value):
        required = {"edge_position", "fade_mode", "shape"}
        allowed = required | {"fade_position"}
        if (
            not isinstance(row, Mapping)
            or not required <= set(row)
            or set(row) - allowed
        ):
            raise business_repair(
                "BUSINESS_VALUE_INVALID",
                field=f"edges[{index}]",
                action="provide edge position, fade mode, shape, and optional fade position",
            )
        fade_mode = _FADE_MODES.get(row["fade_mode"])
        shape = _CURVE_SHAPES.get(row["shape"])
        if fade_mode is None or shape is None:
            raise business_repair(
                "BUSINESS_ENUM_INVALID",
                field=f"edges[{index}]",
                action="choose disclosed fade mode and curve shape values",
            )
        edge = {
            "edgePosition": _finite_number(
                row["edge_position"], field=f"edges[{index}].edge_position"
            ),
            "fadeMode": fade_mode,
            "fadeShape": shape,
        }
        if "fade_position" in row:
            edge["fadePosition"] = _finite_number(
                row["fade_position"], field=f"edges[{index}].fade_position"
            )
        if fade_mode == "Manual" and "fadePosition" not in edge:
            raise business_repair(
                "REQUIRED_FIELD_MISSING",
                field=f"edges[{index}].fade_position",
                action="provide a fade position for a manual edge",
            )
        edges.append(edge)
    if edges[0]["edgePosition"] > edges[1]["edgePosition"]:
        raise business_repair(
            "BUSINESS_RANGE_INVALID",
            field="edges",
            action="place the left edge at or before the right edge",
        )
    return edges


def materialize_core_business_request(
    operation: str,
    session: BusinessDeclarationSession,
) -> dict[str, Any]:
    """Compile one generic Core business declaration at the shared seam."""

    if not isinstance(session, BusinessDeclarationSession):
        raise TypeError("session must be BusinessDeclarationSession")
    version = session.context.wwise_version
    contract = core_business_contract_data(operation, version)
    plan = _core_plan(session)
    if operation == "ak.wwise.core.object.diff":
        expected = {"source_handle", "target_handle"}
        if set(plan) != expected:
            raise business_repair(
                "CORE_PLAN_FIELDS_INVALID",
                field="core_plan",
                required=sorted(expected),
                supplied=sorted(str(key) for key in plan),
                action="submit exactly the two disclosed object roles",
            )
        args = {
            "source": _object_id(
                session,
                plan["source_handle"],
                field="source_handle",
                role="source",
            ),
            "target": _object_id(
                session,
                plan["target_handle"],
                field="target_handle",
                role="target",
            ),
        }
    elif operation == "ak.wwise.core.switchContainer.getAssignments":
        _require_plan_fields(plan, required={"switch_container_handle"})
        args = {
            "id": _object_id(
                session,
                plan["switch_container_handle"],
                field="switch_container_handle",
                role="switch_container",
            )
        }
    elif operation in {"ak.wwise.core.audio.mute", "ak.wwise.core.audio.solo"}:
        outcome_field = "muted" if operation.endswith("mute") else "soloed"
        _require_plan_fields(
            plan,
            required={"object_handles", outcome_field},
        )
        outcome = plan[outcome_field]
        if type(outcome) is not bool:
            raise business_repair(
                "BUSINESS_VALUE_INVALID",
                field=outcome_field,
                action="provide true or false",
            )
        args = {
            "objects": _object_ids(
                session,
                plan["object_handles"],
                field="object_handles",
                role="object",
            ),
            "value": outcome,
        }
    elif operation == "ak.wwise.core.object.setStateGroups":
        _require_plan_fields(
            plan,
            required={"object_handle", "state_group_handles"},
        )
        args = {
            "object": _object_id(
                session,
                plan["object_handle"],
                field="object_handle",
                role="object",
            ),
            "stateGroups": _object_ids(
                session,
                plan["state_group_handles"],
                field="state_group_handles",
                role="state_group",
            ),
        }
    elif operation == "ak.wwise.core.blendContainer.getAssignments":
        _require_plan_fields(plan, required={"blend_track_handle"})
        args = {
            "object": _object_id(
                session,
                plan["blend_track_handle"],
                field="blend_track_handle",
                role="blend_track",
            )
        }
    elif operation in {
        "ak.wwise.core.workUnit.load",
        "ak.wwise.core.workUnit.unload",
    }:
        _require_plan_fields(plan, required={"work_unit_handle"})
        args = {
            "object": _object_id(
                session,
                plan["work_unit_handle"],
                field="work_unit_handle",
                role="work_unit",
            )
        }
    elif operation == "ak.wwise.core.object.setRandomizer":
        _require_plan_fields(
            plan,
            required={"object_handle", "field_handle"},
            optional={
                "enabled",
                "minimum_offset",
                "maximum_offset",
                "platform_name",
            },
        )
        if not set(plan) & {"enabled", "minimum_offset", "maximum_offset"}:
            raise business_repair(
                "REQUIRED_FIELD_MISSING",
                field="randomizer_outcome",
                action="provide enabled, minimum offset, or maximum offset",
            )
        object_id = _object_id(
            session,
            plan["object_handle"],
            field="object_handle",
            role="object",
        )
        args = {
            "object": object_id,
            "property": _field_token(
                session,
                plan["field_handle"],
                field="field_handle",
                object_id=object_id,
            ),
        }
        if "enabled" in plan:
            if type(plan["enabled"]) is not bool:
                raise business_repair(
                    "BUSINESS_VALUE_INVALID",
                    field="enabled",
                    action="provide true or false",
                )
            args["enabled"] = plan["enabled"]
        if "minimum_offset" in plan:
            minimum = _finite_number(plan["minimum_offset"], field="minimum_offset")
            if minimum > 0:
                raise business_repair(
                    "BUSINESS_RANGE_INVALID",
                    field="minimum_offset",
                    maximum=0,
                    action="provide a value at or below zero",
                )
            args["min"] = minimum
        if "maximum_offset" in plan:
            maximum = _finite_number(plan["maximum_offset"], field="maximum_offset")
            if maximum < 0:
                raise business_repair(
                    "BUSINESS_RANGE_INVALID",
                    field="maximum_offset",
                    minimum=0,
                    action="provide a value at or above zero",
                )
            args["max"] = maximum
        if "platform_name" in plan:
            args["platform"] = _business_name(
                plan["platform_name"], field="platform_name"
            )
    elif operation == "ak.wwise.core.object.isLinked":
        _require_plan_fields(
            plan,
            required={"object_handle", "field_handle", "platform_name"},
        )
        object_id = _object_id(
            session,
            plan["object_handle"],
            field="object_handle",
            role="object",
        )
        args = {
            "object": object_id,
            "property": _field_token(
                session,
                plan["field_handle"],
                field="field_handle",
                object_id=object_id,
            ),
            "platform": _business_name(
                plan["platform_name"], field="platform_name"
            ),
        }
    elif operation == "ak.wwise.core.object.setStateProperties":
        _require_plan_fields(
            plan,
            required={"object_handle", "field_handles"},
        )
        object_id = _object_id(
            session,
            plan["object_handle"],
            field="object_handle",
            role="object",
        )
        args = {
            "object": object_id,
            "stateProperties": _field_tokens(
                session,
                plan["field_handles"],
                field="field_handles",
                object_id=object_id,
            ),
        }
    elif operation == "ak.wwise.core.object.pasteProperties":
        _require_plan_fields(
            plan,
            required={"source_handle", "target_handles"},
            optional={
                "include_field_handles",
                "exclude_field_handles",
                "list_mode",
            },
        )
        if "include_field_handles" in plan and "exclude_field_handles" in plan:
            raise business_repair(
                "BUSINESS_FIELDS_CONFLICT",
                field="include_field_handles",
                action="choose inclusion or exclusion, not both",
            )
        source_id = _object_id(
            session,
            plan["source_handle"],
            field="source_handle",
            role="source",
        )
        args = {
            "source": source_id,
            "targets": _object_ids(
                session,
                plan["target_handles"],
                field="target_handles",
                role="target",
            ),
        }
        if "include_field_handles" in plan:
            args["inclusion"] = _field_tokens(
                session,
                plan["include_field_handles"],
                field="include_field_handles",
                object_id=source_id,
            )
        if "exclude_field_handles" in plan:
            args["exclusion"] = _field_tokens(
                session,
                plan["exclude_field_handles"],
                field="exclude_field_handles",
                object_id=source_id,
            )
        if "list_mode" in plan:
            mode = _PASTE_MODES.get(plan["list_mode"])
            if mode is None:
                raise business_repair(
                    "BUSINESS_ENUM_INVALID",
                    field="list_mode",
                    choices=sorted(_PASTE_MODES),
                    action="choose one disclosed list merge outcome",
                )
            args["pasteMode"] = mode
    elif operation == "ak.wwise.core.audio.convert":
        _require_plan_fields(
            plan,
            required={
                "audio_object_handles",
                "platform_names",
                "languages",
                "io_root",
            },
        )
        args = {
            "objects": _object_ids(
                session,
                plan["audio_object_handles"],
                field="audio_object_handles",
                role="audio_object",
            ),
            "platforms": _string_list(plan["platform_names"], field="platform_names"),
            "languages": _string_list(plan["languages"], field="languages"),
        }
    elif operation == "ak.wwise.core.audio.setConversionPlugin":
        _require_plan_fields(
            plan,
            required={"conversion_handle", "platform_name", "plugin_name"},
        )
        args = {
            "conversion": _object_id(
                session,
                plan["conversion_handle"],
                field="conversion_handle",
                role="conversion",
            ),
            "platform": _business_name(
                plan["platform_name"], field="platform_name"
            ),
            "plugin": _business_name(plan["plugin_name"], field="plugin_name"),
        }
    elif operation == "ak.wwise.core.object.setAttenuationCurve":
        _require_plan_fields(
            plan,
            required={"attenuation_handle", "curve_kind", "curve_source", "points"},
            optional={"platform_name"},
        )
        curve_kind = _CURVE_KINDS.get(plan["curve_kind"])
        curve_source = _CURVE_SOURCES.get(plan["curve_source"])
        if curve_kind is None or curve_source is None:
            raise business_repair(
                "BUSINESS_ENUM_INVALID",
                field="curve_kind_or_source",
                action="choose disclosed attenuation curve meanings",
            )
        points = _curve_points(plan["points"])
        if curve_source == "Custom" and not points:
            raise business_repair(
                "BUSINESS_FIELDS_CONFLICT",
                field="points",
                action="provide at least one point for curve_source custom",
            )
        if curve_source != "Custom" and points:
            raise business_repair(
                "BUSINESS_FIELDS_CONFLICT",
                field="points",
                action="use curve_source custom when supplying curve points",
            )
        args: dict[str, Any] = {
            "object": _object_id(
                session,
                plan["attenuation_handle"],
                field="attenuation_handle",
                role="attenuation",
            ),
            "curveType": curve_kind,
            "use": curve_source,
            "points": points,
        }
        if "platform_name" in plan:
            args["platform"] = _business_name(
                plan["platform_name"], field="platform_name"
            )
    elif operation == "ak.wwise.core.blendContainer.addAssignment":
        _require_plan_fields(
            plan,
            required={"blend_track_handle", "child_handle"},
            optional={"insertion_index", "edges"},
        )
        args = {
            "object": _object_id(
                session,
                plan["blend_track_handle"],
                field="blend_track_handle",
                role="blend_track",
            ),
            "child": _object_id(
                session,
                plan["child_handle"],
                field="child_handle",
                role="child",
            ),
        }
        if "insertion_index" in plan:
            index = plan["insertion_index"]
            if type(index) is not int or index < 0:
                raise business_repair(
                    "BUSINESS_RANGE_INVALID",
                    field="insertion_index",
                    minimum=0,
                    action="provide a nonnegative integer",
                )
            args["index"] = index
        if "edges" in plan:
            args["edges"] = _blend_edges(plan["edges"])
    elif operation == "ak.wwise.core.blendContainer.addTrack":
        _require_plan_fields(
            plan,
            required={"blend_container_handle", "track_name"},
        )
        name = _business_name(plan["track_name"], field="track_name")
        if any(character in name for character in "\\<>"):
            raise business_repair(
                "BUSINESS_VALUE_INVALID",
                field="track_name",
                action="provide one Wwise object name without path syntax",
            )
        args = {
            "object": _object_id(
                session,
                plan["blend_container_handle"],
                field="blend_container_handle",
                role="blend_container",
            ),
            "name": name,
        }
    elif operation == "ak.wwise.core.blendContainer.removeAssignment":
        _require_plan_fields(
            plan,
            required={"blend_track_handle", "child_handle"},
        )
        args = {
            "object": _object_id(
                session,
                plan["blend_track_handle"],
                field="blend_track_handle",
                role="blend_track",
            ),
            "child": _object_id(
                session,
                plan["child_handle"],
                field="child_handle",
                role="child",
            ),
        }
    elif operation == "ak.wwise.core.project.save":
        if set(plan) - {"auto_check_out"}:
            raise business_repair(
                "CORE_PLAN_FIELDS_INVALID",
                field="core_plan",
                required=[],
                optional=["auto_check_out"],
                supplied=sorted(str(key) for key in plan),
                action="submit only the disclosed project save choice",
            )
        value = plan.get("auto_check_out")
        if value is not None and type(value) is not bool:
            raise business_repair(
                "BUSINESS_VALUE_INVALID",
                field="auto_check_out",
                action="provide true or false",
            )
        args = (
            {}
            if value is None
            else {"autoCheckOutToSourceControl": value}
        )
    else:  # pragma: no cover - contract registry invariant
        raise ValueError("unsupported generic Core business operation")
    if contract["execution_shape"] == "bounded_read":
        return {
            "contract": "waapi-skill.core-business-call/v1",
            "version": version,
            "api": operation,
            "args": args,
            "options": {},
        }
    operation_arguments: dict[str, Any] = {
        "api": operation,
        "args": args,
        "options": {},
    }
    if operation == "ak.wwise.core.audio.convert":
        io_root = plan["io_root"]
        if not isinstance(io_root, str) or not io_root:
            raise business_repair(
                "BUSINESS_VALUE_INVALID",
                field="io_root",
                action="provide the exact caller-owned conversion I/O root",
            )
        operation_arguments["io_root"] = io_root
    return parse_operation_request(
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": version,
            "operation": "waapi.call",
            "arguments": operation_arguments,
        },
        expected_version=version,
    ).as_dict()


__all__ = ["materialize_core_business_request"]
