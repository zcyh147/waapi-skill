"""Current production Business Declaration profile for object lifecycle routing."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_business_profile_contract import (
    load_closed_business_profile_source,
    select_closed_business_profile_units,
)


PROFILE_CONTRACT = "waapi-skill.object-lifecycle-business-profile/v1"
PROFILE_ID = "object_lifecycle_business_3"
MODEL = "gpt-5.6-terra"
REASONING_EFFORT = "medium"
SERVICE_TIER = "default"
UNIT_IDS = ("OLB22-NOTES", "OLB22-DELETE", "OLB22-RENAME")
OPERATIONS = ("object.setNotes", "object.delete", "object.setName")
_FORBIDDEN_PROMPT_MECHANICS = (
    "draft-start",
    "draft-bind",
    "draft-declare",
    "operation-request",
    "request-json",
    "ak.wwise.",
    "object_handle",
)


class ObjectLifecycleBusinessProfileError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ObjectLifecycleBusinessScenario:
    id: str
    api: str
    prompt_sha256: str


@dataclass(frozen=True, slots=True)
class ObjectLifecycleBusinessUnit:
    unit_id: str
    operation: str
    version: str
    prompt_template: str
    object: Mapping[str, Any]
    value: str | None
    final_markers: tuple[str, ...]
    scenario: ObjectLifecycleBusinessScenario

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
class ObjectLifecycleBusinessProfile:
    path: Path
    definition_sha256: str
    units: tuple[ObjectLifecycleBusinessUnit, ...]


def load_object_lifecycle_business_profile(
    path: str | Path,
    *,
    unit_ids: Sequence[str] = (),
    versions: Sequence[str] = (),
) -> ObjectLifecycleBusinessProfile:
    source = load_closed_business_profile_source(
        path,
        contract=PROFILE_CONTRACT,
        profile_id=PROFILE_ID,
        model=MODEL,
        reasoning_effort=REASONING_EFFORT,
        service_tier=SERVICE_TIER,
        expected_unit_count=3,
        error_type=ObjectLifecycleBusinessProfileError,
        subject="object lifecycle",
    )
    parsed = tuple(
        _parse_unit(row, expected_id=unit_id, expected_operation=operation)
        for row, unit_id, operation in zip(
            source.units,
            UNIT_IDS,
            OPERATIONS,
            strict=True,
        )
    )
    units = select_closed_business_profile_units(
        parsed,
        unit_ids=unit_ids,
        versions=versions,
        known_unit_ids=UNIT_IDS,
        supported_versions=("2022.1",),
        error_type=ObjectLifecycleBusinessProfileError,
        subject="object lifecycle",
    )
    return ObjectLifecycleBusinessProfile(
        path=source.path,
        definition_sha256=source.definition_sha256,
        units=units,
    )


def _parse_unit(
    value: Any,
    *,
    expected_id: str,
    expected_operation: str,
) -> ObjectLifecycleBusinessUnit:
    keys = {
        "unit_id", "operation", "api", "version", "prompt", "object",
        "value", "final_markers",
    }
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ObjectLifecycleBusinessProfileError("object lifecycle unit is not closed")
    if value.get("unit_id") != expected_id or value.get("operation") != expected_operation:
        raise ObjectLifecycleBusinessProfileError("object lifecycle unit identity drifted")
    api = value.get("api")
    if api != f"ak.wwise.core.{expected_operation}":
        raise ObjectLifecycleBusinessProfileError("object lifecycle API drifted")
    if value.get("version") != "2022.1":
        raise ObjectLifecycleBusinessProfileError("object lifecycle version drifted")
    prompt = value.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ObjectLifecycleBusinessProfileError("object lifecycle prompt is invalid")
    if any(token in prompt.casefold() for token in _FORBIDDEN_PROMPT_MECHANICS):
        raise ObjectLifecycleBusinessProfileError("object lifecycle prompt exposes mechanics")
    obj = value.get("object")
    if not isinstance(obj, Mapping) or set(obj) != {
        "id", "name", "type", "path", "parent", "notes"
    }:
        raise ObjectLifecycleBusinessProfileError("object lifecycle object is not closed")
    if not all(isinstance(obj.get(key), str) for key in obj):
        raise ObjectLifecycleBusinessProfileError("object lifecycle object fields are invalid")
    if not str(obj["path"]).startswith("\\"):
        raise ObjectLifecycleBusinessProfileError("object lifecycle object path is invalid")
    raw_value = value.get("value")
    if expected_operation == "object.delete":
        if raw_value is not None or "{value}" in prompt:
            raise ObjectLifecycleBusinessProfileError("delete must not invent a value")
    elif not isinstance(raw_value, str) or not raw_value or "{value}" not in prompt:
        raise ObjectLifecycleBusinessProfileError("object lifecycle value is invalid")
    markers = value.get("final_markers")
    if not isinstance(markers, list) or not markers or any(
        not isinstance(marker, str) or not marker for marker in markers
    ):
        raise ObjectLifecycleBusinessProfileError("object lifecycle markers are invalid")
    if "{object_path}" not in prompt:
        raise ObjectLifecycleBusinessProfileError("object lifecycle prompt lacks object path")
    return ObjectLifecycleBusinessUnit(
        unit_id=expected_id,
        operation=expected_operation,
        version="2022.1",
        prompt_template=prompt,
        object=dict(obj),
        value=raw_value,
        final_markers=tuple(markers),
        scenario=ObjectLifecycleBusinessScenario(
            id=expected_id,
            api=str(api),
            prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        ),
    )


__all__ = [
    "MODEL", "ObjectLifecycleBusinessProfile", "ObjectLifecycleBusinessProfileError",
    "ObjectLifecycleBusinessScenario", "ObjectLifecycleBusinessUnit", "OPERATIONS",
    "PROFILE_ID", "REASONING_EFFORT", "SERVICE_TIER", "UNIT_IDS",
    "load_object_lifecycle_business_profile",
]
