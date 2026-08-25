"""Current production Business Declaration profile for object lifecycle routing."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


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
    profile_path = Path(path).expanduser().resolve(strict=True)
    raw = json.loads(profile_path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping) or set(raw) != {
        "contract", "profile_id", "model", "units"
    }:
        raise ObjectLifecycleBusinessProfileError("object lifecycle profile is not closed")
    if raw.get("contract") != PROFILE_CONTRACT or raw.get("profile_id") != PROFILE_ID:
        raise ObjectLifecycleBusinessProfileError("object lifecycle profile identity drifted")
    if raw.get("model") != {
        "name": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "service_tier": SERVICE_TIER,
        "memory": "disabled",
    }:
        raise ObjectLifecycleBusinessProfileError("object lifecycle model settings drifted")
    rows = raw.get("units")
    if not isinstance(rows, list) or len(rows) != 3:
        raise ObjectLifecycleBusinessProfileError("object lifecycle profile requires three units")
    parsed = tuple(
        _parse_unit(row, expected_id=unit_id, expected_operation=operation)
        for row, unit_id, operation in zip(rows, UNIT_IDS, OPERATIONS, strict=True)
    )
    selected_ids = tuple(dict.fromkeys(str(value) for value in unit_ids))
    selected_versions = tuple(dict.fromkeys(str(value) for value in versions))
    if len(selected_ids) != len(tuple(unit_ids)) or len(selected_versions) != len(tuple(versions)):
        raise ObjectLifecycleBusinessProfileError("object lifecycle filters must be unique")
    unknown = sorted(set(selected_ids) - set(UNIT_IDS))
    if unknown:
        raise ObjectLifecycleBusinessProfileError(
            "unknown object lifecycle units: " + ", ".join(unknown)
        )
    if any(version != "2022.1" for version in selected_versions):
        raise ObjectLifecycleBusinessProfileError(
            "object lifecycle profile supports only 2022.1"
        )
    units = tuple(
        unit
        for unit in parsed
        if (not selected_ids or unit.unit_id in selected_ids)
        and (not selected_versions or unit.version in selected_versions)
    )
    if not units:
        raise ObjectLifecycleBusinessProfileError("no object lifecycle units matched")
    return ObjectLifecycleBusinessProfile(
        path=profile_path,
        definition_sha256=hashlib.sha256(profile_path.read_bytes()).hexdigest(),
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
