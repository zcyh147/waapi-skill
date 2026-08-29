"""Targeted Fresh Agent profile for one CLI/Console build Preview."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_business_profile_contract import (
    load_closed_business_profile_source,
    select_closed_business_profile_units,
)


PROFILE_CONTRACT = "waapi-skill.cli-console-business-profile/v1"
PROFILE_ID = "cli_console_business_1"
MODEL = "gpt-5.6-terra"
REASONING_EFFORT = "medium"
SERVICE_TIER = "default"
UNIT_IDS = ("CLI25-SOUNDBANK-BUILD-PREVIEW",)
OPERATION = "ak.wwise.cli.generateSoundbank"
VERSION = "2025.1"
PROJECT_PLACEHOLDER = "{project_file}"
OUTPUT_DIRECTORY = "GeneratedSoundBanks/FreshAgent"
_FORBIDDEN_PROMPT_MECHANICS = (
    "draft-start",
    "draft-declare",
    "request-schema",
    "typed-call",
    "ak.wwise.",
)


class CliConsoleBusinessProfileError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CliConsoleBusinessScenario:
    id: str
    api: str
    prompt_sha256: str


@dataclass(frozen=True, slots=True)
class CliConsoleBusinessUnit:
    unit_id: str
    operation: str
    version: str
    prompt_template: str
    final_markers: tuple[str, ...]
    scenario: CliConsoleBusinessScenario

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
class CliConsoleBusinessProfile:
    path: Path
    definition_sha256: str
    units: tuple[CliConsoleBusinessUnit, ...]


def load_cli_console_business_profile(
    path: str | Path,
    *,
    unit_ids: Sequence[str] = (),
    versions: Sequence[str] = (),
) -> CliConsoleBusinessProfile:
    source = load_closed_business_profile_source(
        path,
        contract=PROFILE_CONTRACT,
        profile_id=PROFILE_ID,
        model=MODEL,
        reasoning_effort=REASONING_EFFORT,
        service_tier=SERVICE_TIER,
        expected_unit_count=1,
        error_type=CliConsoleBusinessProfileError,
        subject="CLI/Console business",
    )
    parsed = (_parse_unit(source.units[0]),)
    units = select_closed_business_profile_units(
        parsed,
        unit_ids=unit_ids,
        versions=versions,
        known_unit_ids=UNIT_IDS,
        supported_versions=(VERSION,),
        error_type=CliConsoleBusinessProfileError,
        subject="CLI/Console business",
    )
    return CliConsoleBusinessProfile(
        path=source.path,
        definition_sha256=source.definition_sha256,
        units=units,
    )


def _parse_unit(value: Any) -> CliConsoleBusinessUnit:
    keys = {"unit_id", "operation", "version", "prompt", "final_markers"}
    if not isinstance(value, Mapping) or set(value) != keys:
        raise CliConsoleBusinessProfileError("CLI/Console business unit is not closed")
    if (
        value.get("unit_id") != UNIT_IDS[0]
        or value.get("operation") != OPERATION
        or value.get("version") != VERSION
    ):
        raise CliConsoleBusinessProfileError("CLI/Console business unit identity drifted")
    prompt = value.get("prompt")
    if (
        not isinstance(prompt, str)
        or not prompt.strip()
        or prompt.count(PROJECT_PLACEHOLDER) != 1
        or OUTPUT_DIRECTORY not in prompt
    ):
        raise CliConsoleBusinessProfileError("CLI/Console business prompt is invalid")
    if any(token in prompt.casefold() for token in _FORBIDDEN_PROMPT_MECHANICS):
        raise CliConsoleBusinessProfileError(
            "CLI/Console business prompt exposes Gateway mechanics"
        )
    markers = value.get("final_markers")
    if not isinstance(markers, list) or not markers or any(
        not isinstance(marker, str) or not marker for marker in markers
    ):
        raise CliConsoleBusinessProfileError(
            "CLI/Console business final markers are invalid"
        )
    return CliConsoleBusinessUnit(
        unit_id=UNIT_IDS[0],
        operation=OPERATION,
        version=VERSION,
        prompt_template=prompt,
        final_markers=tuple(markers),
        scenario=CliConsoleBusinessScenario(
            id=UNIT_IDS[0],
            api=OPERATION,
            prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        ),
    )


__all__ = [
    "MODEL",
    "OPERATION",
    "OUTPUT_DIRECTORY",
    "PROFILE_ID",
    "REASONING_EFFORT",
    "SERVICE_TIER",
    "UNIT_IDS",
    "VERSION",
    "CliConsoleBusinessProfile",
    "CliConsoleBusinessProfileError",
    "CliConsoleBusinessScenario",
    "CliConsoleBusinessUnit",
    "load_cli_console_business_profile",
]
