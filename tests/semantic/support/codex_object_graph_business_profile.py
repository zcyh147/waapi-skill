"""Targeted Fresh Agent profile for one named Weather object graph."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_business_profile_contract import (
    load_closed_business_profile_source,
    select_closed_business_profile_units,
)


PROFILE_CONTRACT = "waapi-skill.object-graph-business-profile/v1"
PROFILE_ID = "object_graph_business_1"
MODEL = "gpt-5.6-terra"
REASONING_EFFORT = "medium"
SERVICE_TIER = "default"
UNIT_IDS = ("OGB22-WEATHER-GRAPH",)
_FORBIDDEN_PROMPT_MECHANICS = (
    "draft-start",
    "draft-bind",
    "draft-declare",
    "operation-request",
    "request-json",
    "ak.wwise.",
    "object_handle",
)


class ObjectGraphBusinessProfileError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ObjectGraphBusinessScenario:
    id: str
    api: str
    prompt_sha256: str


@dataclass(frozen=True, slots=True)
class ObjectGraphBusinessUnit:
    unit_id: str
    operation: str
    version: str
    prompt_template: str
    parent: Mapping[str, Any]
    root_name: str
    sounds: tuple[Mapping[str, Any], ...]
    final_markers: tuple[str, ...]
    scenario: ObjectGraphBusinessScenario

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
class ObjectGraphBusinessProfile:
    path: Path
    definition_sha256: str
    units: tuple[ObjectGraphBusinessUnit, ...]


def load_object_graph_business_profile(
    path: str | Path,
    *,
    unit_ids: Sequence[str] = (),
    versions: Sequence[str] = (),
) -> ObjectGraphBusinessProfile:
    source = load_closed_business_profile_source(
        path,
        contract=PROFILE_CONTRACT,
        profile_id=PROFILE_ID,
        model=MODEL,
        reasoning_effort=REASONING_EFFORT,
        service_tier=SERVICE_TIER,
        expected_unit_count=1,
        error_type=ObjectGraphBusinessProfileError,
        subject="object graph",
    )
    units = select_closed_business_profile_units(
        (_parse_unit(source.units[0]),),
        unit_ids=unit_ids,
        versions=versions,
        known_unit_ids=UNIT_IDS,
        supported_versions=("2022.1",),
        error_type=ObjectGraphBusinessProfileError,
        subject="object graph",
    )
    return ObjectGraphBusinessProfile(
        path=source.path,
        definition_sha256=source.definition_sha256,
        units=units,
    )


def _parse_unit(value: Any) -> ObjectGraphBusinessUnit:
    keys = {
        "unit_id", "operation", "api", "version", "prompt", "parent",
        "root_name", "sounds", "final_markers",
    }
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ObjectGraphBusinessProfileError("object graph unit is not closed")
    if (
        value.get("unit_id") != UNIT_IDS[0]
        or value.get("operation") != "object.create"
        or value.get("api") != "ak.wwise.core.object.create"
        or value.get("version") != "2022.1"
    ):
        raise ObjectGraphBusinessProfileError("object graph unit identity drifted")
    prompt = value.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ObjectGraphBusinessProfileError("object graph prompt is invalid")
    if any(token in prompt.casefold() for token in _FORBIDDEN_PROMPT_MECHANICS):
        raise ObjectGraphBusinessProfileError("object graph prompt exposes mechanics")
    parent = value.get("parent")
    if (
        not isinstance(parent, Mapping)
        or set(parent) != {"id", "name", "type", "path"}
        or not all(isinstance(parent.get(key), str) and parent.get(key) for key in parent)
        or not str(parent["path"]).startswith("\\")
        or "{parent_path}" not in prompt
    ):
        raise ObjectGraphBusinessProfileError("object graph parent is invalid")
    root_name = value.get("root_name")
    sounds = value.get("sounds")
    if not isinstance(root_name, str) or not root_name:
        raise ObjectGraphBusinessProfileError("object graph root name is invalid")
    if (
        not isinstance(sounds, list)
        or len(sounds) != 2
        or any(
            not isinstance(row, Mapping)
            or set(row) != {"name", "loop", "volume_db"}
            or not isinstance(row.get("name"), str)
            or row.get("loop") != "infinite"
            or isinstance(row.get("volume_db"), bool)
            or not isinstance(row.get("volume_db"), (int, float))
            for row in sounds
        )
    ):
        raise ObjectGraphBusinessProfileError("object graph sounds are invalid")
    markers = value.get("final_markers")
    if not isinstance(markers, list) or not markers or any(
        not isinstance(marker, str) or not marker for marker in markers
    ):
        raise ObjectGraphBusinessProfileError("object graph markers are invalid")
    return ObjectGraphBusinessUnit(
        unit_id=UNIT_IDS[0],
        operation="object.create",
        version="2022.1",
        prompt_template=prompt,
        parent=dict(parent),
        root_name=root_name,
        sounds=tuple(dict(row) for row in sounds),
        final_markers=tuple(markers),
        scenario=ObjectGraphBusinessScenario(
            id=UNIT_IDS[0],
            api="ak.wwise.core.object.create",
            prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        ),
    )


__all__ = [
    "MODEL", "ObjectGraphBusinessProfile", "ObjectGraphBusinessProfileError",
    "ObjectGraphBusinessScenario", "ObjectGraphBusinessUnit", "PROFILE_ID",
    "REASONING_EFFORT", "SERVICE_TIER", "UNIT_IDS",
    "load_object_graph_business_profile",
]
