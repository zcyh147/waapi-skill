"""Targeted Fresh Agent profile for SoundEngine parameter closure."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_business_profile_contract import (
    load_closed_business_profile_source,
    select_closed_business_profile_units,
)


PROFILE_CONTRACT = "waapi-skill.soundengine-business-profile/v1"
PROFILE_ID = "soundengine_business_4"
MODEL = "gpt-5.6-terra"
REASONING_EFFORT = "medium"
SERVICE_TIER = "default"
UNIT_IDS = (
    "SOUND22-MONITOR-PREVIEW",
    "SOUND22-GAME-OBJECT-PREVIEW",
    "SOUND22-EVENT-PREVIEW",
    "SOUND22-LISTENER-PREVIEW",
)
OPERATIONS = (
    "ak.soundengine.postMsgMonitor",
    "ak.soundengine.registerGameObj",
    "ak.soundengine.executeActionOnEvent",
    "ak.soundengine.setListenerSpatialization",
)
VERSION = "2022.1"
MONITOR_MESSAGE = "Fresh Agent SoundEngine business probe"
GAME_OBJECT_NAME = "Fresh Weather Listener"
EVENT_NAME = "Fresh Alarm Event"
EVENT_ID = "{11111111-2222-3333-4444-555555555555}"
LISTENER_HANDLE = "goh1-11111111111111111111111111111111"
LISTENER_ID = 424242
_FORBIDDEN_PROMPT_MECHANICS = (
    "draft-start",
    "draft-declare",
    "request-schema",
    "typed-call",
    "ak.soundengine",
)


class SoundEngineBusinessProfileError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SoundEngineBusinessScenario:
    id: str
    api: str
    prompt_sha256: str


@dataclass(frozen=True, slots=True)
class SoundEngineBusinessUnit:
    unit_id: str
    operation: str
    version: str
    prompt_template: str
    final_markers: tuple[str, ...]
    scenario: SoundEngineBusinessScenario

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
class SoundEngineBusinessProfile:
    path: Path
    definition_sha256: str
    units: tuple[SoundEngineBusinessUnit, ...]


def load_soundengine_business_profile(
    path: str | Path,
    *,
    unit_ids: Sequence[str] = (),
    versions: Sequence[str] = (),
) -> SoundEngineBusinessProfile:
    source = load_closed_business_profile_source(
        path,
        contract=PROFILE_CONTRACT,
        profile_id=PROFILE_ID,
        model=MODEL,
        reasoning_effort=REASONING_EFFORT,
        service_tier=SERVICE_TIER,
        expected_unit_count=4,
        error_type=SoundEngineBusinessProfileError,
        subject="SoundEngine business",
    )
    parsed = tuple(
        _parse_unit(value, index=index)
        for index, value in enumerate(source.units)
    )
    units = select_closed_business_profile_units(
        parsed,
        unit_ids=unit_ids,
        versions=versions,
        known_unit_ids=UNIT_IDS,
        supported_versions=(VERSION,),
        error_type=SoundEngineBusinessProfileError,
        subject="SoundEngine business",
    )
    return SoundEngineBusinessProfile(
        path=source.path,
        definition_sha256=source.definition_sha256,
        units=units,
    )


def _parse_unit(value: Any, *, index: int) -> SoundEngineBusinessUnit:
    keys = {"unit_id", "operation", "version", "prompt", "final_markers"}
    if not isinstance(value, Mapping) or set(value) != keys:
        raise SoundEngineBusinessProfileError(
            "SoundEngine business unit is not closed"
        )
    if (
        index >= len(UNIT_IDS)
        or value.get("unit_id") != UNIT_IDS[index]
        or value.get("operation") != OPERATIONS[index]
        or value.get("version") != VERSION
    ):
        raise SoundEngineBusinessProfileError(
            "SoundEngine business unit identity drifted"
        )
    prompt = value.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise SoundEngineBusinessProfileError(
            "SoundEngine business prompt is invalid"
        )
    required_prompt_value = (
        MONITOR_MESSAGE,
        GAME_OBJECT_NAME,
        EVENT_NAME,
        LISTENER_HANDLE,
    )[index]
    if required_prompt_value not in prompt:
        raise SoundEngineBusinessProfileError(
            "SoundEngine business prompt lost its exact business value"
        )
    if any(token in prompt.casefold() for token in _FORBIDDEN_PROMPT_MECHANICS):
        raise SoundEngineBusinessProfileError(
            "SoundEngine business prompt exposes Gateway mechanics"
        )
    markers = value.get("final_markers")
    if not isinstance(markers, list) or not markers or any(
        not isinstance(marker, str) or not marker for marker in markers
    ):
        raise SoundEngineBusinessProfileError(
            "SoundEngine business final markers are invalid"
        )
    return SoundEngineBusinessUnit(
        unit_id=UNIT_IDS[index],
        operation=OPERATIONS[index],
        version=VERSION,
        prompt_template=prompt,
        final_markers=tuple(markers),
        scenario=SoundEngineBusinessScenario(
            id=UNIT_IDS[index],
            api=OPERATIONS[index],
            prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        ),
    )


__all__ = [
    "MODEL",
    "EVENT_ID",
    "EVENT_NAME",
    "GAME_OBJECT_NAME",
    "LISTENER_HANDLE",
    "LISTENER_ID",
    "MONITOR_MESSAGE",
    "OPERATIONS",
    "PROFILE_ID",
    "REASONING_EFFORT",
    "SERVICE_TIER",
    "UNIT_IDS",
    "VERSION",
    "SoundEngineBusinessProfile",
    "SoundEngineBusinessProfileError",
    "SoundEngineBusinessScenario",
    "SoundEngineBusinessUnit",
    "load_soundengine_business_profile",
]
