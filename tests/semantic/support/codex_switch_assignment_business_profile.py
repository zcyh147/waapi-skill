"""Targeted Fresh Agent profile for one bound Switch assignment Preview."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_business_profile_contract import (
    load_closed_business_profile_source,
    select_closed_business_profile_units,
)


PROFILE_CONTRACT = "waapi-skill.switch-assignment-business-profile/v1"
PROFILE_ID = "switch_assignment_business_1"
MODEL = "gpt-5.6-terra"
REASONING_EFFORT = "medium"
SERVICE_TIER = "default"
UNIT_IDS = ("SAB22-ADD-SNOW",)
ROLES = ("switch_container", "child", "group", "state_or_switch")
_FORBIDDEN_PROMPT_MECHANICS = (
    "draft-start",
    "draft-bind",
    "draft-declare",
    "operation-request",
    "request-json",
    "ak.wwise.",
    "object_handle",
)


class SwitchAssignmentBusinessProfileError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SwitchAssignmentBusinessScenario:
    id: str
    api: str
    prompt_sha256: str


@dataclass(frozen=True, slots=True)
class SwitchAssignmentBusinessUnit:
    unit_id: str
    operation: str
    version: str
    prompt_template: str
    objects: Mapping[str, Mapping[str, str]]
    final_markers: tuple[str, ...]
    scenario: SwitchAssignmentBusinessScenario

    @property
    def user_turn_count(self) -> int:
        return 1

    @property
    def transaction_count(self) -> int:
        return 1

    @property
    def runner_lane(self) -> str:
        return "agent"


@dataclass(frozen=True, slots=True)
class SwitchAssignmentBusinessProfile:
    path: Path
    definition_sha256: str
    units: tuple[SwitchAssignmentBusinessUnit, ...]


def load_switch_assignment_business_profile(
    path: str | Path,
    *,
    unit_ids: Sequence[str] = (),
    versions: Sequence[str] = (),
) -> SwitchAssignmentBusinessProfile:
    source = load_closed_business_profile_source(
        path,
        contract=PROFILE_CONTRACT,
        profile_id=PROFILE_ID,
        model=MODEL,
        reasoning_effort=REASONING_EFFORT,
        service_tier=SERVICE_TIER,
        expected_unit_count=1,
        error_type=SwitchAssignmentBusinessProfileError,
        subject="Switch assignment",
    )
    parsed = (_parse_unit(source.units[0]),)
    units = select_closed_business_profile_units(
        parsed,
        unit_ids=unit_ids,
        versions=versions,
        known_unit_ids=UNIT_IDS,
        supported_versions=("2022.1",),
        error_type=SwitchAssignmentBusinessProfileError,
        subject="Switch assignment",
    )
    return SwitchAssignmentBusinessProfile(
        path=source.path,
        definition_sha256=source.definition_sha256,
        units=units,
    )


def _parse_unit(value: Any) -> SwitchAssignmentBusinessUnit:
    keys = {
        "unit_id",
        "operation",
        "api",
        "version",
        "prompt",
        "objects",
        "final_markers",
    }
    if not isinstance(value, Mapping) or set(value) != keys:
        raise SwitchAssignmentBusinessProfileError(
            "Switch assignment unit is not closed"
        )
    if (
        value.get("unit_id") != UNIT_IDS[0]
        or value.get("operation") != "switchContainer.addAssignment"
        or value.get("api")
        != "ak.wwise.core.switchContainer.addAssignment"
        or value.get("version") != "2022.1"
    ):
        raise SwitchAssignmentBusinessProfileError(
            "Switch assignment unit identity drifted"
        )
    prompt = value.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise SwitchAssignmentBusinessProfileError(
            "Switch assignment prompt is invalid"
        )
    if any(token in prompt.casefold() for token in _FORBIDDEN_PROMPT_MECHANICS):
        raise SwitchAssignmentBusinessProfileError(
            "Switch assignment prompt exposes Gateway mechanics"
        )
    objects = value.get("objects")
    if not isinstance(objects, Mapping) or tuple(objects) != ROLES:
        raise SwitchAssignmentBusinessProfileError(
            "Switch assignment object roles are not closed"
        )
    parsed_objects: dict[str, Mapping[str, str]] = {}
    for role in ROLES:
        row = objects.get(role)
        if not isinstance(row, Mapping) or set(row) != {
            "id",
            "name",
            "type",
            "path",
            "parent",
        }:
            raise SwitchAssignmentBusinessProfileError(
                f"Switch assignment {role} object is not closed"
            )
        if not all(isinstance(row.get(field), str) and row.get(field) for field in row):
            raise SwitchAssignmentBusinessProfileError(
                f"Switch assignment {role} object is invalid"
            )
        if not str(row["path"]).startswith("\\"):
            raise SwitchAssignmentBusinessProfileError(
                f"Switch assignment {role} path is invalid"
            )
        parsed_objects[role] = dict(row)
    for role in ("switch_container", "child", "state_or_switch"):
        if f"{{{role}_path}}" not in prompt:
            raise SwitchAssignmentBusinessProfileError(
                f"Switch assignment prompt lacks {role} path"
            )
    if parsed_objects["child"]["parent"] != parsed_objects["switch_container"]["id"]:
        raise SwitchAssignmentBusinessProfileError(
            "Switch assignment child parent drifted"
        )
    if parsed_objects["state_or_switch"]["parent"] != parsed_objects["group"]["id"]:
        raise SwitchAssignmentBusinessProfileError(
            "Switch assignment value parent drifted"
        )
    markers = value.get("final_markers")
    if not isinstance(markers, list) or not markers or any(
        not isinstance(marker, str) or not marker for marker in markers
    ):
        raise SwitchAssignmentBusinessProfileError(
            "Switch assignment final markers are invalid"
        )
    return SwitchAssignmentBusinessUnit(
        unit_id=UNIT_IDS[0],
        operation="switchContainer.addAssignment",
        version="2022.1",
        prompt_template=prompt,
        objects=parsed_objects,
        final_markers=tuple(markers),
        scenario=SwitchAssignmentBusinessScenario(
            id=UNIT_IDS[0],
            api="ak.wwise.core.switchContainer.addAssignment",
            prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        ),
    )


__all__ = [
    "MODEL",
    "PROFILE_ID",
    "REASONING_EFFORT",
    "ROLES",
    "SERVICE_TIER",
    "UNIT_IDS",
    "SwitchAssignmentBusinessProfile",
    "SwitchAssignmentBusinessProfileError",
    "SwitchAssignmentBusinessScenario",
    "SwitchAssignmentBusinessUnit",
    "load_switch_assignment_business_profile",
]
