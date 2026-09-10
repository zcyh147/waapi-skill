"""Compile project-setting declarations into canonical WAAPI operations."""

from __future__ import annotations

import math
from typing import Any, Mapping

from .business_declaration_state import BusinessDeclarationSession
from .business_declarations import BoundObjectHandle, business_repair
from .operation_registry import parse_operation_request
from .project_setting_business_contracts import (
    GAME_PARAMETER_SET_RANGE_URI,
    SOUND_SET_ACTIVE_SOURCE_URI,
    project_setting_business_contract_data,
)


_CURVE_UPDATE_OUTCOMES = {
    "stretch": "stretch",
    "preserve-x": "preserveX",
}


def _plan(session: BusinessDeclarationSession) -> Mapping[str, Any]:
    if set(session.settings) != {"project_setting_plan"}:
        raise business_repair(
            "PROJECT_SETTING_PLAN_INCOMPLETE",
            field="project_setting_plan",
            action="submit the one complete Gateway-disclosed project-setting plan",
        )
    plan = session.settings["project_setting_plan"]
    if not isinstance(plan, Mapping):
        raise business_repair(
            "PROJECT_SETTING_PLAN_INVALID",
            field="project_setting_plan",
            action="submit one closed project-setting plan",
        )
    return plan


def _bound(
    session: BusinessDeclarationSession,
    value: Any,
    *,
    field: str,
    role: str,
    object_type: str,
) -> BoundObjectHandle:
    if not isinstance(value, str):
        raise business_repair(
            "REQUIRED_FIELD_MISSING",
            field=field,
            action=f"bind the exact {role} and copy its returned handle",
        )
    bound = session.handles.resolve_object(value)
    if bound.role != role or bound.object_type != object_type:
        raise business_repair(
            "BOUND_OBJECT_ROLE_MISMATCH",
            field=field,
            expected_role=role,
            expected_type=object_type,
            actual_role=bound.role,
            actual_type=bound.object_type,
            action=f"copy the handle returned for the {role} role",
        )
    return bound


def _finite(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise business_repair(
            "BUSINESS_VALUE_INVALID",
            field=field,
            action="provide one finite number",
        )
    result = float(value)
    if not math.isfinite(result):
        raise business_repair(
            "BUSINESS_VALUE_INVALID",
            field=field,
            action="provide one finite number",
        )
    return result


def materialize_project_setting_business_request(
    operation: str,
    session: BusinessDeclarationSession,
) -> dict[str, Any]:
    if not isinstance(session, BusinessDeclarationSession):
        raise TypeError("session must be BusinessDeclarationSession")
    project_setting_business_contract_data(
        operation,
        session.context.wwise_version,
    )
    plan = _plan(session)
    if operation == SOUND_SET_ACTIVE_SOURCE_URI:
        allowed = {"sound_handle", "source_handle", "platform_name"}
        if set(plan) - allowed or not {"sound_handle", "source_handle"} <= set(plan):
            raise business_repair(
                "PROJECT_SETTING_PLAN_FIELDS_INVALID",
                field="project_setting_plan",
                action="submit only the disclosed Sound and source outcome",
            )
        sound = _bound(
            session,
            plan["sound_handle"],
            field="sound_handle",
            role="sound",
            object_type="Sound",
        )
        source = _bound(
            session,
            plan["source_handle"],
            field="source_handle",
            role="source",
            object_type="AudioFileSource",
        )
        if source.path.rsplit("\\", 1)[0].casefold() != sound.path.casefold():
            raise business_repair(
                "PROJECT_SETTING_RELATIONSHIP_INVALID",
                field="source_handle",
                action="bind an AudioFileSource that is a direct child of the Sound",
            )
        args: dict[str, Any] = {
            "sound": sound.object_id,
            "source": source.object_id,
        }
        if "platform_name" in plan:
            platform = plan["platform_name"]
            if not isinstance(platform, str) or not platform or platform != platform.strip():
                raise business_repair(
                    "BUSINESS_VALUE_INVALID",
                    field="platform_name",
                    action="provide one exact installed platform name",
                )
            args["platform"] = platform
    elif operation == GAME_PARAMETER_SET_RANGE_URI:
        required = {
            "game_parameter_handle",
            "minimum",
            "maximum",
            "curve_update_outcome",
        }
        if set(plan) != required:
            raise business_repair(
                "PROJECT_SETTING_PLAN_FIELDS_INVALID",
                field="project_setting_plan",
                action="submit exactly the disclosed Game Parameter range outcome",
            )
        game_parameter = _bound(
            session,
            plan["game_parameter_handle"],
            field="game_parameter_handle",
            role="game_parameter",
            object_type="GameParameter",
        )
        minimum = _finite(plan["minimum"], field="minimum")
        maximum = _finite(plan["maximum"], field="maximum")
        if minimum >= maximum:
            raise business_repair(
                "BUSINESS_RANGE_INVALID",
                field="minimum",
                minimum=minimum,
                maximum=maximum,
                action="provide a minimum strictly below the maximum",
            )
        curve_update = _CURVE_UPDATE_OUTCOMES.get(plan["curve_update_outcome"])
        if curve_update is None:
            raise business_repair(
                "BUSINESS_ENUM_INVALID",
                field="curve_update_outcome",
                choices=sorted(_CURVE_UPDATE_OUTCOMES),
                action="choose how existing curves should respond to the new range",
            )
        args = {
            "object": game_parameter.object_id,
            "min": minimum,
            "max": maximum,
            "onCurveUpdate": curve_update,
        }
    else:  # pragma: no cover - contract registry invariant
        raise ValueError("unsupported project-setting business operation")
    return parse_operation_request(
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": session.context.wwise_version,
            "operation": "waapi.call",
            "arguments": {
                "api": operation,
                "args": args,
                "options": {},
            },
        },
        expected_version=session.context.wwise_version,
    ).as_dict()


__all__ = ["materialize_project_setting_business_request"]
