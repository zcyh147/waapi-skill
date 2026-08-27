"""Targeted Fresh Agent profile for one compound Undo Preview."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_business_profile_contract import (
    load_closed_business_profile_source,
    select_closed_business_profile_units,
)


PROFILE_CONTRACT = "waapi-skill.compound-undo-business-profile/v1"
PROFILE_ID = "compound_undo_business_1"
MODEL = "gpt-5.6-terra"
REASONING_EFFORT = "medium"
SERVICE_TIER = "default"
UNIT_IDS = ("CUB22-WEATHER-TWO-CHANGES",)
_FORBIDDEN_PROMPT_MECHANICS = (
    "draft-start",
    "draft-bind",
    "draft-declare",
    "operation-request",
    "request-json",
    "ak.wwise.",
    "object_handle",
)


class CompoundUndoBusinessProfileError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CompoundUndoBusinessScenario:
    id: str
    api: str
    prompt_sha256: str


@dataclass(frozen=True, slots=True)
class CompoundUndoBusinessUnit:
    unit_id: str
    operation: str
    version: str
    prompt_template: str
    object: Mapping[str, str]
    notes_value: str
    name_value: str
    display_name: str
    final_markers: tuple[str, ...]
    scenario: CompoundUndoBusinessScenario

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
class CompoundUndoBusinessProfile:
    path: Path
    definition_sha256: str
    units: tuple[CompoundUndoBusinessUnit, ...]


def load_compound_undo_business_profile(
    path: str | Path,
    *,
    unit_ids: Sequence[str] = (),
    versions: Sequence[str] = (),
) -> CompoundUndoBusinessProfile:
    source = load_closed_business_profile_source(
        path,
        contract=PROFILE_CONTRACT,
        profile_id=PROFILE_ID,
        model=MODEL,
        reasoning_effort=REASONING_EFFORT,
        service_tier=SERVICE_TIER,
        expected_unit_count=1,
        error_type=CompoundUndoBusinessProfileError,
        subject="compound Undo",
    )
    parsed = (_parse_unit(source.units[0]),)
    units = select_closed_business_profile_units(
        parsed,
        unit_ids=unit_ids,
        versions=versions,
        known_unit_ids=UNIT_IDS,
        supported_versions=("2022.1",),
        error_type=CompoundUndoBusinessProfileError,
        subject="compound Undo",
    )
    return CompoundUndoBusinessProfile(
        path=source.path,
        definition_sha256=source.definition_sha256,
        units=units,
    )


def _parse_unit(value: Any) -> CompoundUndoBusinessUnit:
    keys = {
        "unit_id",
        "operation",
        "api",
        "version",
        "prompt",
        "object",
        "notes_value",
        "name_value",
        "display_name",
        "final_markers",
    }
    if not isinstance(value, Mapping) or set(value) != keys:
        raise CompoundUndoBusinessProfileError("compound Undo unit is not closed")
    if (
        value.get("unit_id") != UNIT_IDS[0]
        or value.get("operation") != "waapi.undoGroup"
        or value.get("api") != "ak.wwise.core.undo.beginGroup"
        or value.get("version") != "2022.1"
    ):
        raise CompoundUndoBusinessProfileError("compound Undo unit identity drifted")
    prompt = value.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise CompoundUndoBusinessProfileError("compound Undo prompt is invalid")
    if any(token in prompt.casefold() for token in _FORBIDDEN_PROMPT_MECHANICS):
        raise CompoundUndoBusinessProfileError("compound Undo prompt exposes mechanics")
    obj = value.get("object")
    if not isinstance(obj, Mapping) or set(obj) != {
        "id",
        "name",
        "type",
        "path",
        "parent",
        "notes",
    }:
        raise CompoundUndoBusinessProfileError("compound Undo object is not closed")
    if not all(isinstance(obj.get(field), str) and obj.get(field) for field in obj):
        raise CompoundUndoBusinessProfileError("compound Undo object is invalid")
    if not str(obj["path"]).startswith("\\"):
        raise CompoundUndoBusinessProfileError("compound Undo object path is invalid")
    values = {
        field: value.get(field)
        for field in ("notes_value", "name_value", "display_name")
    }
    if any(not isinstance(item, str) or not item for item in values.values()):
        raise CompoundUndoBusinessProfileError("compound Undo values are invalid")
    for placeholder in (
        "{object_path}",
        "{notes_value}",
        "{name_value}",
        "{display_name}",
    ):
        if placeholder not in prompt:
            raise CompoundUndoBusinessProfileError(
                f"compound Undo prompt lacks {placeholder}"
            )
    markers = value.get("final_markers")
    if not isinstance(markers, list) or not markers or any(
        not isinstance(marker, str) or not marker for marker in markers
    ):
        raise CompoundUndoBusinessProfileError("compound Undo markers are invalid")
    return CompoundUndoBusinessUnit(
        unit_id=UNIT_IDS[0],
        operation="waapi.undoGroup",
        version="2022.1",
        prompt_template=prompt,
        object=dict(obj),
        notes_value=str(values["notes_value"]),
        name_value=str(values["name_value"]),
        display_name=str(values["display_name"]),
        final_markers=tuple(markers),
        scenario=CompoundUndoBusinessScenario(
            id=UNIT_IDS[0],
            api="ak.wwise.core.undo.beginGroup",
            prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        ),
    )


__all__ = [
    "MODEL",
    "PROFILE_ID",
    "REASONING_EFFORT",
    "SERVICE_TIER",
    "UNIT_IDS",
    "CompoundUndoBusinessProfile",
    "CompoundUndoBusinessProfileError",
    "CompoundUndoBusinessScenario",
    "CompoundUndoBusinessUnit",
    "load_compound_undo_business_profile",
]
