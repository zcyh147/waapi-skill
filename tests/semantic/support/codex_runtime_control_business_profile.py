"""Targeted Fresh Agent profile for one runtime-control Preview."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_business_profile_contract import (
    load_closed_business_profile_source,
    select_closed_business_profile_units,
)


PROFILE_CONTRACT = "waapi-skill.runtime-control-business-profile/v1"
PROFILE_ID = "runtime_control_business_1"
MODEL = "gpt-5.6-terra"
REASONING_EFFORT = "medium"
SERVICE_TIER = "default"
UNIT_IDS = ("RUNTIME25-PROFILER-VOICES-PREVIEW",)
OPERATION = "ak.wwise.core.profiler.enableProfilerData"
VERSION = "2025.1"
_FORBIDDEN_PROMPT_MECHANICS = (
    "draft-start",
    "draft-declare",
    "request-schema",
    "typed-call",
    "ak.wwise.",
)


class RuntimeControlBusinessProfileError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RuntimeControlBusinessScenario:
    id: str
    api: str
    prompt_sha256: str


@dataclass(frozen=True, slots=True)
class RuntimeControlBusinessUnit:
    unit_id: str
    operation: str
    version: str
    prompt_template: str
    final_markers: tuple[str, ...]
    scenario: RuntimeControlBusinessScenario

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
class RuntimeControlBusinessProfile:
    path: Path
    definition_sha256: str
    units: tuple[RuntimeControlBusinessUnit, ...]


def load_runtime_control_business_profile(
    path: str | Path,
    *,
    unit_ids: Sequence[str] = (),
    versions: Sequence[str] = (),
) -> RuntimeControlBusinessProfile:
    source = load_closed_business_profile_source(
        path,
        contract=PROFILE_CONTRACT,
        profile_id=PROFILE_ID,
        model=MODEL,
        reasoning_effort=REASONING_EFFORT,
        service_tier=SERVICE_TIER,
        expected_unit_count=1,
        error_type=RuntimeControlBusinessProfileError,
        subject="Runtime-control business",
    )
    parsed = (_parse_unit(source.units[0]),)
    units = select_closed_business_profile_units(
        parsed,
        unit_ids=unit_ids,
        versions=versions,
        known_unit_ids=UNIT_IDS,
        supported_versions=(VERSION,),
        error_type=RuntimeControlBusinessProfileError,
        subject="Runtime-control business",
    )
    return RuntimeControlBusinessProfile(
        path=source.path,
        definition_sha256=source.definition_sha256,
        units=units,
    )


def _parse_unit(value: Any) -> RuntimeControlBusinessUnit:
    keys = {"unit_id", "operation", "version", "prompt", "final_markers"}
    if not isinstance(value, Mapping) or set(value) != keys:
        raise RuntimeControlBusinessProfileError(
            "Runtime-control business unit is not closed"
        )
    if (
        value.get("unit_id") != UNIT_IDS[0]
        or value.get("operation") != OPERATION
        or value.get("version") != VERSION
    ):
        raise RuntimeControlBusinessProfileError(
            "Runtime-control business unit identity drifted"
        )
    prompt = value.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise RuntimeControlBusinessProfileError(
            "Runtime-control business prompt is invalid"
        )
    if any(token in prompt.casefold() for token in _FORBIDDEN_PROMPT_MECHANICS):
        raise RuntimeControlBusinessProfileError(
            "Runtime-control business prompt exposes Gateway mechanics"
        )
    markers = value.get("final_markers")
    if not isinstance(markers, list) or not markers or any(
        not isinstance(marker, str) or not marker for marker in markers
    ):
        raise RuntimeControlBusinessProfileError(
            "Runtime-control business final markers are invalid"
        )
    return RuntimeControlBusinessUnit(
        unit_id=UNIT_IDS[0],
        operation=OPERATION,
        version=VERSION,
        prompt_template=prompt,
        final_markers=tuple(markers),
        scenario=RuntimeControlBusinessScenario(
            id=UNIT_IDS[0],
            api=OPERATION,
            prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        ),
    )


__all__ = [
    "MODEL",
    "OPERATION",
    "PROFILE_ID",
    "REASONING_EFFORT",
    "SERVICE_TIER",
    "UNIT_IDS",
    "VERSION",
    "RuntimeControlBusinessProfile",
    "RuntimeControlBusinessProfileError",
    "RuntimeControlBusinessScenario",
    "RuntimeControlBusinessUnit",
    "load_runtime_control_business_profile",
]
