"""Targeted Fresh Agent profile for bound object metadata field edits."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_business_profile_contract import (
    load_closed_business_profile_source,
    select_closed_business_profile_units,
)


PROFILE_CONTRACT = "waapi-skill.object-metadata-business-profile/v1"
PROFILE_ID = "object_metadata_business_1"
MODEL = "gpt-5.6-terra"
REASONING_EFFORT = "medium"
SERVICE_TIER = "default"
UNIT_IDS = ("OMB22-ALARM-OUTPUT-BUS",)
_FORBIDDEN_PROMPT_MECHANICS = (
    "draft-start",
    "draft-bind",
    "draft-discover",
    "draft-declare",
    "operation-request",
    "request-json",
    "ak.wwise.",
    "object_handle",
    "field_handle",
)


class ObjectMetadataBusinessProfileError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ObjectMetadataBusinessScenario:
    id: str
    api: str
    prompt_sha256: str


@dataclass(frozen=True, slots=True)
class ObjectMetadataBusinessUnit:
    unit_id: str
    operation: str
    version: str
    prompt_template: str
    source: Mapping[str, Any]
    target: Mapping[str, Any]
    field_meaning: str
    native_reference: str
    final_markers: tuple[str, ...]
    scenario: ObjectMetadataBusinessScenario

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
class ObjectMetadataBusinessProfile:
    path: Path
    definition_sha256: str
    units: tuple[ObjectMetadataBusinessUnit, ...]


def load_object_metadata_business_profile(
    path: str | Path,
    *,
    unit_ids: Sequence[str] = (),
    versions: Sequence[str] = (),
) -> ObjectMetadataBusinessProfile:
    source = load_closed_business_profile_source(
        path,
        contract=PROFILE_CONTRACT,
        profile_id=PROFILE_ID,
        model=MODEL,
        reasoning_effort=REASONING_EFFORT,
        service_tier=SERVICE_TIER,
        expected_unit_count=1,
        error_type=ObjectMetadataBusinessProfileError,
        subject="object metadata",
    )
    parsed = (_parse_unit(source.units[0]),)
    units = select_closed_business_profile_units(
        parsed,
        unit_ids=unit_ids,
        versions=versions,
        known_unit_ids=UNIT_IDS,
        supported_versions=("2022.1",),
        error_type=ObjectMetadataBusinessProfileError,
        subject="object metadata",
    )
    return ObjectMetadataBusinessProfile(
        path=source.path,
        definition_sha256=source.definition_sha256,
        units=units,
    )


def _parse_unit(value: Any) -> ObjectMetadataBusinessUnit:
    keys = {
        "unit_id", "operation", "api", "version", "prompt", "source", "target",
        "field_meaning", "native_reference", "final_markers",
    }
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ObjectMetadataBusinessProfileError("object metadata unit is not closed")
    if (
        value.get("unit_id") != UNIT_IDS[0]
        or value.get("operation") != "object.setReference"
        or value.get("api") != "ak.wwise.core.object.setReference"
        or value.get("version") != "2022.1"
    ):
        raise ObjectMetadataBusinessProfileError("object metadata unit identity drifted")
    prompt = value.get("prompt")
    meaning = value.get("field_meaning")
    native_reference = value.get("native_reference")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ObjectMetadataBusinessProfileError("object metadata prompt is invalid")
    if any(token in prompt.casefold() for token in _FORBIDDEN_PROMPT_MECHANICS):
        raise ObjectMetadataBusinessProfileError("object metadata prompt exposes mechanics")
    if not isinstance(meaning, str) or not meaning.strip() or "{field_meaning}" not in prompt:
        raise ObjectMetadataBusinessProfileError("object metadata field meaning is invalid")
    if (
        not isinstance(native_reference, str)
        or not native_reference
        or native_reference.casefold() in prompt.casefold()
    ):
        raise ObjectMetadataBusinessProfileError("object metadata prompt exposes native token")
    objects: list[dict[str, Any]] = []
    for role in ("source", "target"):
        obj = value.get(role)
        if not isinstance(obj, Mapping) or set(obj) != {"id", "name", "type", "path"}:
            raise ObjectMetadataBusinessProfileError(f"object metadata {role} is not closed")
        if not all(isinstance(obj.get(key), str) and obj.get(key) for key in obj):
            raise ObjectMetadataBusinessProfileError(f"object metadata {role} is invalid")
        if not str(obj["path"]).startswith("\\") or f"{{{role}_path}}" not in prompt:
            raise ObjectMetadataBusinessProfileError(f"object metadata {role} path is invalid")
        objects.append(dict(obj))
    markers = value.get("final_markers")
    if not isinstance(markers, list) or not markers or any(
        not isinstance(marker, str) or not marker for marker in markers
    ):
        raise ObjectMetadataBusinessProfileError("object metadata markers are invalid")
    return ObjectMetadataBusinessUnit(
        unit_id=UNIT_IDS[0],
        operation="object.setReference",
        version="2022.1",
        prompt_template=prompt,
        source=objects[0],
        target=objects[1],
        field_meaning=meaning,
        native_reference=native_reference,
        final_markers=tuple(markers),
        scenario=ObjectMetadataBusinessScenario(
            id=UNIT_IDS[0],
            api="ak.wwise.core.object.setReference",
            prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        ),
    )


__all__ = [
    "MODEL", "ObjectMetadataBusinessProfile", "ObjectMetadataBusinessProfileError",
    "ObjectMetadataBusinessScenario", "ObjectMetadataBusinessUnit", "PROFILE_ID",
    "REASONING_EFFORT", "SERVICE_TIER", "UNIT_IDS",
    "load_object_metadata_business_profile",
]
