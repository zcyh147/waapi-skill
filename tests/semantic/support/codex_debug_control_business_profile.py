"""Targeted Fresh Agent profile for one safe Debug host-control Preview."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_business_profile_contract import (
    load_closed_business_profile_source,
    select_closed_business_profile_units,
)


PROFILE_CONTRACT = "waapi-skill.debug-control-business-profile/v1"
PROFILE_ID = "debug_control_business_1"
MODEL = "gpt-5.6-terra"
REASONING_EFFORT = "medium"
SERVICE_TIER = "default"
UNIT_IDS = ("DBG21-AUTOMATION-PREVIEW",)
OPERATION = "debug.setAutomationMode"
VERSION = "2021.1"
_FORBIDDEN_PROMPT_MECHANICS = (
    "draft-start",
    "draft-declare",
    "operation-schema",
    "typed-call",
    "ak.wwise.",
)


class DebugControlBusinessProfileError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DebugControlBusinessScenario:
    id: str
    api: str
    prompt_sha256: str


@dataclass(frozen=True, slots=True)
class DebugControlBusinessUnit:
    unit_id: str
    operation: str
    version: str
    prompt_template: str
    final_markers: tuple[str, ...]
    scenario: DebugControlBusinessScenario

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
class DebugControlBusinessProfile:
    path: Path
    definition_sha256: str
    units: tuple[DebugControlBusinessUnit, ...]


def load_debug_control_business_profile(
    path: str | Path,
    *,
    unit_ids: Sequence[str] = (),
    versions: Sequence[str] = (),
) -> DebugControlBusinessProfile:
    source = load_closed_business_profile_source(
        path,
        contract=PROFILE_CONTRACT,
        profile_id=PROFILE_ID,
        model=MODEL,
        reasoning_effort=REASONING_EFFORT,
        service_tier=SERVICE_TIER,
        expected_unit_count=1,
        error_type=DebugControlBusinessProfileError,
        subject="Debug-control business",
    )
    parsed = (_parse_unit(source.units[0]),)
    units = select_closed_business_profile_units(
        parsed,
        unit_ids=unit_ids,
        versions=versions,
        known_unit_ids=UNIT_IDS,
        supported_versions=(VERSION,),
        error_type=DebugControlBusinessProfileError,
        subject="Debug-control business",
    )
    return DebugControlBusinessProfile(
        path=source.path,
        definition_sha256=source.definition_sha256,
        units=units,
    )


def _parse_unit(value: Any) -> DebugControlBusinessUnit:
    keys = {"unit_id", "operation", "version", "prompt", "final_markers"}
    if not isinstance(value, Mapping) or set(value) != keys:
        raise DebugControlBusinessProfileError(
            "Debug-control business unit is not closed"
        )
    if (
        value.get("unit_id") != UNIT_IDS[0]
        or value.get("operation") != OPERATION
        or value.get("version") != VERSION
    ):
        raise DebugControlBusinessProfileError(
            "Debug-control business unit identity drifted"
        )
    prompt = value.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise DebugControlBusinessProfileError(
            "Debug-control business prompt is invalid"
        )
    if any(token in prompt.casefold() for token in _FORBIDDEN_PROMPT_MECHANICS):
        raise DebugControlBusinessProfileError(
            "Debug-control business prompt exposes Gateway mechanics"
        )
    markers = value.get("final_markers")
    if not isinstance(markers, list) or not markers or any(
        not isinstance(marker, str) or not marker for marker in markers
    ):
        raise DebugControlBusinessProfileError(
            "Debug-control business final markers are invalid"
        )
    return DebugControlBusinessUnit(
        unit_id=UNIT_IDS[0],
        operation=OPERATION,
        version=VERSION,
        prompt_template=prompt,
        final_markers=tuple(markers),
        scenario=DebugControlBusinessScenario(
            id=UNIT_IDS[0],
            api=OPERATION,
            prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        ),
    )


__all__ = [
    "DebugControlBusinessProfile",
    "DebugControlBusinessProfileError",
    "DebugControlBusinessScenario",
    "DebugControlBusinessUnit",
    "MODEL",
    "OPERATION",
    "PROFILE_ID",
    "REASONING_EFFORT",
    "SERVICE_TIER",
    "UNIT_IDS",
    "VERSION",
    "load_debug_control_business_profile",
]
