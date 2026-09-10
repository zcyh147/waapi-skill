"""Closed loader for the four-family, eight-task #52 MVP profile."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


PROFILE_CONTRACT = "waapi-skill.deep-interface-mvp-profile/v1"
PROFILE_ID = "deep_interface_mvp_8"
MODEL = "gpt-5.6-terra"
REASONING_EFFORT = "medium"
SERVICE_TIER = "default"
CASE_IDS = (
    "MVP22-WEATHER",
    "MVP22-RIFLE",
    "MVP25-FOOTSTEPS",
    "MVP25-WEAPONS",
)
CASE_FAMILIES = ("weather", "rifle", "footsteps", "weapons")
UNIT_IDS = tuple(
    f"{case_id}-{variant}"
    for case_id in CASE_IDS
    for variant in ("A", "B")
)
FAMILIES = tuple(
    family
    for family in CASE_FAMILIES
    for _variant in ("A", "B")
)


class ImportMvpProfileError(ValueError):
    """The fixed MVP profile is malformed or has drifted."""


@dataclass(frozen=True, slots=True)
class ImportMvpScenario:
    id: str
    api: str = "test.waapi.audio.import.business-mvp"


@dataclass(frozen=True, slots=True)
class ImportMvpUnit:
    unit_id: str
    family: str
    version: str
    prompt: str
    paraphrases: tuple[str, str]
    variant: str
    commands: tuple[tuple[str, ...], ...]
    final_markers: tuple[str, ...]
    scenario: ImportMvpScenario


@dataclass(frozen=True, slots=True)
class ImportMvpProfile:
    path: Path
    definition_sha256: str
    units: tuple[ImportMvpUnit, ...]


def load_import_mvp_profile(
    path: str | Path,
    *,
    unit_ids: Sequence[str] = (),
    versions: Sequence[str] = (),
) -> ImportMvpProfile:
    profile_path = Path(path).expanduser().resolve(strict=True)
    raw = json.loads(profile_path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping) or set(raw) != {
        "contract",
        "profile_id",
        "model",
        "units",
    }:
        raise ImportMvpProfileError("MVP profile root schema is not closed")
    if raw.get("contract") != PROFILE_CONTRACT or raw.get("profile_id") != PROFILE_ID:
        raise ImportMvpProfileError("MVP profile identity drifted")
    if raw.get("model") != {
        "name": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "service_tier": SERVICE_TIER,
        "memory": "disabled",
    }:
        raise ImportMvpProfileError("MVP profile model settings drifted")
    raw_units = raw.get("units")
    if not isinstance(raw_units, list) or len(raw_units) != len(CASE_IDS):
        raise ImportMvpProfileError("MVP profile requires exactly four business cases")
    units = tuple(
        unit
        for value, case_id, family in zip(
            raw_units,
            CASE_IDS,
            CASE_FAMILIES,
            strict=True,
        )
        for unit in _parse_case(
            value,
            expected_id=case_id,
            expected_family=family,
        )
    )
    selected_ids = tuple(dict.fromkeys(str(value) for value in unit_ids))
    selected_versions = tuple(dict.fromkeys(str(value) for value in versions))
    if len(selected_ids) != len(tuple(unit_ids)) or len(selected_versions) != len(tuple(versions)):
        raise ImportMvpProfileError("MVP filters must be unique")
    unknown = sorted(set(selected_ids) - set(UNIT_IDS))
    if unknown:
        raise ImportMvpProfileError("unknown MVP units: " + ", ".join(unknown))
    if any(value not in {"2022.1", "2025.1"} for value in selected_versions):
        raise ImportMvpProfileError("MVP profile supports only 2022.1 and 2025.1")
    filtered = tuple(
        unit
        for unit in units
        if (not selected_ids or unit.unit_id in selected_ids)
        and (not selected_versions or unit.version in selected_versions)
    )
    if not filtered:
        raise ImportMvpProfileError("no MVP units matched the filters")
    return ImportMvpProfile(
        path=profile_path,
        definition_sha256=hashlib.sha256(profile_path.read_bytes()).hexdigest(),
        units=filtered,
    )


def _parse_case(
    value: Any,
    *,
    expected_id: str,
    expected_family: str,
) -> tuple[ImportMvpUnit, ImportMvpUnit]:
    if not isinstance(value, Mapping) or set(value) != {
        "unit_id",
        "family",
        "version",
        "paraphrases",
        "commands",
        "final_markers",
    }:
        raise ImportMvpProfileError("MVP unit schema is not closed")
    if value.get("unit_id") != expected_id or value.get("family") != expected_family:
        raise ImportMvpProfileError("MVP unit identity or order drifted")
    version = value.get("version")
    paraphrases_value = value.get("paraphrases")
    if (
        version not in {"2022.1", "2025.1"}
        or not isinstance(paraphrases_value, list)
        or len(paraphrases_value) != 2
        or len(set(paraphrases_value)) != 2
        or any(not isinstance(item, str) or not item for item in paraphrases_value)
    ):
        raise ImportMvpProfileError("MVP unit version or paraphrases are invalid")
    paraphrases = (str(paraphrases_value[0]), str(paraphrases_value[1]))
    commands_value = value.get("commands")
    if (
        not isinstance(commands_value, list)
        or len(commands_value) < 3
        or any(
            not isinstance(command, list)
            or not command
            or any(not isinstance(token, str) or not token for token in command)
            for command in commands_value
        )
    ):
        raise ImportMvpProfileError("MVP command protocol is invalid")
    commands = tuple(tuple(command) for command in commands_value)
    if commands[0] != ("mvp-context", "--family", expected_family) or commands[-1] != (
        "mvp-preview",
    ):
        raise ImportMvpProfileError("MVP protocol must begin with context and end with preview")
    markers_value = value.get("final_markers")
    if (
        not isinstance(markers_value, list)
        or not markers_value
        or any(not isinstance(marker, str) or not marker for marker in markers_value)
    ):
        raise ImportMvpProfileError("MVP final markers are invalid")
    return tuple(
        ImportMvpUnit(
            unit_id=f"{expected_id}-{variant}",
            family=expected_family,
            version=str(version),
            prompt=prompt,
            paraphrases=paraphrases,
            variant=variant,
            commands=commands,
            final_markers=tuple(markers_value),
            scenario=ImportMvpScenario(id=f"{expected_id}-{variant}"),
        )
        for variant, prompt in zip(("A", "B"), paraphrases, strict=True)
    )


__all__ = [
    "CASE_FAMILIES",
    "CASE_IDS",
    "FAMILIES",
    "ImportMvpProfile",
    "ImportMvpProfileError",
    "ImportMvpScenario",
    "ImportMvpUnit",
    "MODEL",
    "PROFILE_ID",
    "REASONING_EFFORT",
    "SERVICE_TIER",
    "UNIT_IDS",
    "load_import_mvp_profile",
]
