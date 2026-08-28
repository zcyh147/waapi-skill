"""Targeted Fresh Agent profile for one generic Core business Preview."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_business_profile_contract import (
    load_closed_business_profile_source,
    select_closed_business_profile_units,
)


PROFILE_CONTRACT = "waapi-skill.core-business-profile/v1"
PROFILE_ID = "core_business_1"
MODEL = "gpt-5.6-terra"
REASONING_EFFORT = "medium"
SERVICE_TIER = "default"
UNIT_IDS = ("CORE25-PROJECT-SAVE-PREVIEW",)
_OPERATION = "ak.wwise.core.project.save"
_VERSION = "2025.1"
_FORBIDDEN_PROMPT_MECHANICS = (
    "draft-start",
    "draft-declare",
    "request-schema",
    "typed-call",
    "ak.wwise.",
)


class CoreBusinessProfileError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CoreBusinessScenario:
    id: str
    api: str
    prompt_sha256: str


@dataclass(frozen=True, slots=True)
class CoreBusinessUnit:
    unit_id: str
    operation: str
    version: str
    prompt_template: str
    final_markers: tuple[str, ...]
    scenario: CoreBusinessScenario

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
class CoreBusinessProfile:
    path: Path
    definition_sha256: str
    units: tuple[CoreBusinessUnit, ...]


def load_core_business_profile(
    path: str | Path,
    *,
    unit_ids: Sequence[str] = (),
    versions: Sequence[str] = (),
) -> CoreBusinessProfile:
    source = load_closed_business_profile_source(
        path,
        contract=PROFILE_CONTRACT,
        profile_id=PROFILE_ID,
        model=MODEL,
        reasoning_effort=REASONING_EFFORT,
        service_tier=SERVICE_TIER,
        expected_unit_count=1,
        error_type=CoreBusinessProfileError,
        subject="Core business",
    )
    parsed = (_parse_unit(source.units[0]),)
    units = select_closed_business_profile_units(
        parsed,
        unit_ids=unit_ids,
        versions=versions,
        known_unit_ids=UNIT_IDS,
        supported_versions=(_VERSION,),
        error_type=CoreBusinessProfileError,
        subject="Core business",
    )
    return CoreBusinessProfile(
        path=source.path,
        definition_sha256=source.definition_sha256,
        units=units,
    )


def _parse_unit(value: Any) -> CoreBusinessUnit:
    keys = {"unit_id", "operation", "version", "prompt", "final_markers"}
    if not isinstance(value, Mapping) or set(value) != keys:
        raise CoreBusinessProfileError("Core business unit is not closed")
    if (
        value.get("unit_id") != UNIT_IDS[0]
        or value.get("operation") != _OPERATION
        or value.get("version") != _VERSION
    ):
        raise CoreBusinessProfileError("Core business unit identity drifted")
    prompt = value.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise CoreBusinessProfileError("Core business prompt is invalid")
    if any(token in prompt.casefold() for token in _FORBIDDEN_PROMPT_MECHANICS):
        raise CoreBusinessProfileError("Core business prompt exposes Gateway mechanics")
    markers = value.get("final_markers")
    if not isinstance(markers, list) or not markers or any(
        not isinstance(marker, str) or not marker for marker in markers
    ):
        raise CoreBusinessProfileError("Core business final markers are invalid")
    return CoreBusinessUnit(
        unit_id=UNIT_IDS[0],
        operation=_OPERATION,
        version=_VERSION,
        prompt_template=prompt,
        final_markers=tuple(markers),
        scenario=CoreBusinessScenario(
            id=UNIT_IDS[0],
            api=_OPERATION,
            prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        ),
    )


__all__ = [
    "MODEL",
    "PROFILE_ID",
    "REASONING_EFFORT",
    "SERVICE_TIER",
    "UNIT_IDS",
    "CoreBusinessProfile",
    "CoreBusinessProfileError",
    "CoreBusinessScenario",
    "CoreBusinessUnit",
    "load_core_business_profile",
]
