"""Closed four-family production audio.import semantic profile."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


PROFILE_CONTRACT = "waapi-skill.audio-import-business-profile/v2"
PROFILE_ID = "audio_import_business_8"
MODEL = "gpt-5.6-terra"
REASONING_EFFORT = "medium"
SERVICE_TIER = "default"
CASE_IDS = (
    "AIB22-WEATHER",
    "AIB22-RIFLE",
    "AIB25-FOOTSTEPS",
    "AIB25-WEAPONS",
)
CASE_FAMILIES = ("weather", "rifle", "footsteps", "weapons")
UNIT_IDS = tuple(
    f"{case_id}-{variant}"
    for case_id in CASE_IDS
    for variant in ("A", "B")
)
_FORBIDDEN_PROMPT_MECHANICS = (
    "object_path",
    "objecttype",
    "metadata scope",
    "import_operation",
    "draft-declare",
    "draft-bind",
    "ak.wwise.",
)


class ImportBusinessProfileError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ImportBusinessScenario:
    id: str
    prompt_sha256: str
    api: str = "ak.wwise.core.audio.import"


@dataclass(frozen=True, slots=True)
class ImportBusinessUnit:
    unit_id: str
    family: str
    version: str
    prompt_template: str
    variant: str
    objects: tuple[Mapping[str, Any], ...]
    fields: tuple[Mapping[str, Any], ...]
    transactions: tuple[Mapping[str, Any], ...]
    final_markers: tuple[str, ...]
    scenario: ImportBusinessScenario

    @property
    def user_turn_count(self) -> int:
        return 1

    @property
    def transaction_count(self) -> int:
        return len(self.transactions)

    @property
    def runner_lane(self) -> str:
        return "agent"


@dataclass(frozen=True, slots=True)
class ImportBusinessProfile:
    path: Path
    definition_sha256: str
    units: tuple[ImportBusinessUnit, ...]


def load_import_business_profile(
    path: str | Path,
    *,
    unit_ids: Sequence[str] = (),
    versions: Sequence[str] = (),
) -> ImportBusinessProfile:
    profile_path = Path(path).expanduser().resolve(strict=True)
    raw = json.loads(profile_path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping) or set(raw) != {
        "contract", "profile_id", "model", "units"
    }:
        raise ImportBusinessProfileError("audio import business profile is not closed")
    if raw.get("contract") != PROFILE_CONTRACT or raw.get("profile_id") != PROFILE_ID:
        raise ImportBusinessProfileError("audio import business profile identity drifted")
    if raw.get("model") != {
        "name": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "service_tier": SERVICE_TIER,
        "memory": "disabled",
    }:
        raise ImportBusinessProfileError("audio import business model settings drifted")
    raw_units = raw.get("units")
    if not isinstance(raw_units, list) or len(raw_units) != 4:
        raise ImportBusinessProfileError("audio import business profile requires four cases")
    parsed = tuple(
        unit
        for value, case_id, family in zip(raw_units, CASE_IDS, CASE_FAMILIES, strict=True)
        for unit in _parse_case(value, expected_id=case_id, expected_family=family)
    )
    selected_ids = tuple(dict.fromkeys(str(value) for value in unit_ids))
    selected_versions = tuple(dict.fromkeys(str(value) for value in versions))
    if len(selected_ids) != len(tuple(unit_ids)) or len(selected_versions) != len(tuple(versions)):
        raise ImportBusinessProfileError("audio import business filters must be unique")
    unknown = sorted(set(selected_ids) - set(UNIT_IDS))
    if unknown:
        raise ImportBusinessProfileError("unknown audio import business units: " + ", ".join(unknown))
    if any(value not in {"2022.1", "2025.1"} for value in selected_versions):
        raise ImportBusinessProfileError("audio import business profile supports only 2022.1 and 2025.1")
    units = tuple(
        unit
        for unit in parsed
        if (not selected_ids or unit.unit_id in selected_ids)
        and (not selected_versions or unit.version in selected_versions)
    )
    if not units:
        raise ImportBusinessProfileError("no audio import business units matched")
    return ImportBusinessProfile(
        path=profile_path,
        definition_sha256=hashlib.sha256(profile_path.read_bytes()).hexdigest(),
        units=units,
    )


def _parse_case(
    value: Any,
    *,
    expected_id: str,
    expected_family: str,
) -> tuple[ImportBusinessUnit, ImportBusinessUnit]:
    expected_keys = {
        "unit_id", "family", "version", "variants", "objects", "fields",
        "transactions",
    }
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        raise ImportBusinessProfileError("audio import business case is not closed")
    if value.get("unit_id") != expected_id or value.get("family") != expected_family:
        raise ImportBusinessProfileError("audio import business case identity drifted")
    version = value.get("version")
    variants = value.get("variants")
    objects = value.get("objects")
    fields = value.get("fields")
    transactions = value.get("transactions")
    if version not in {"2022.1", "2025.1"}:
        raise ImportBusinessProfileError("audio import business version is invalid")
    if (
        not isinstance(variants, list)
        or len(variants) != 2
    ):
        raise ImportBusinessProfileError("audio import business variants are invalid")
    expected_variant_keys = {
        "id", "prompt", "transaction_indexes", "final_markers",
    }
    if any(
        not isinstance(item, Mapping) or set(item) != expected_variant_keys
        for item in variants
    ):
        raise ImportBusinessProfileError("audio import business variant is not closed")
    if [item.get("id") for item in variants] != ["A", "B"]:
        raise ImportBusinessProfileError("audio import business variant identity drifted")
    prompts = [item.get("prompt") for item in variants]
    if (
        len(set(prompts)) != 2
        or any(not isinstance(item, str) or not item.strip() for item in prompts)
    ):
        raise ImportBusinessProfileError("audio import business prompts are invalid")
    prompt_text = "\n".join(str(item) for item in prompts).casefold()
    if any(token in prompt_text for token in _FORBIDDEN_PROMPT_MECHANICS):
        raise ImportBusinessProfileError("Agent prompt exposes raw Wwise request mechanics")
    if not isinstance(objects, list) or not objects:
        raise ImportBusinessProfileError("audio import business fixture objects are invalid")
    if not isinstance(fields, list):
        raise ImportBusinessProfileError("audio import business fixture fields are invalid")
    if not isinstance(transactions, list) or not transactions:
        raise ImportBusinessProfileError("audio import business transactions are invalid")
    frozen_objects = tuple(dict(item) for item in objects if isinstance(item, Mapping))
    frozen_fields = tuple(dict(item) for item in fields if isinstance(item, Mapping))
    frozen_transactions = tuple(dict(item) for item in transactions if isinstance(item, Mapping))
    if len(frozen_objects) != len(objects) or len(frozen_fields) != len(fields) or len(frozen_transactions) != len(transactions):
        raise ImportBusinessProfileError("audio import business fixture rows must be objects")
    parsed_units: list[ImportBusinessUnit] = []
    for item in variants:
        indexes = item.get("transaction_indexes")
        markers = item.get("final_markers")
        if (
            not isinstance(indexes, list)
            or not indexes
            or any(type(index) is not int for index in indexes)
            or len(set(indexes)) != len(indexes)
            or any(not 0 <= index < len(frozen_transactions) for index in indexes)
        ):
            raise ImportBusinessProfileError(
                "audio import business variant transaction indexes are invalid"
            )
        if (
            not isinstance(markers, list)
            or not markers
            or any(not isinstance(marker, str) or not marker for marker in markers)
        ):
            raise ImportBusinessProfileError(
                "audio import business variant final markers are invalid"
            )
        variant = str(item["id"])
        prompt = str(item["prompt"])
        parsed_units.append(
            ImportBusinessUnit(
                unit_id=f"{expected_id}-{variant}",
                family=expected_family,
                version=str(version),
                prompt_template=prompt,
                variant=variant,
                objects=frozen_objects,
                fields=frozen_fields,
                transactions=tuple(
                    frozen_transactions[index] for index in indexes
                ),
                final_markers=tuple(str(marker) for marker in markers),
                scenario=ImportBusinessScenario(
                    id=f"{expected_id}-{variant}",
                    prompt_sha256=hashlib.sha256(
                        prompt.encode("utf-8")
                    ).hexdigest(),
                ),
            )
        )
    return parsed_units[0], parsed_units[1]


__all__ = [
    "CASE_FAMILIES", "CASE_IDS", "ImportBusinessProfile",
    "ImportBusinessProfileError", "ImportBusinessScenario", "ImportBusinessUnit",
    "MODEL", "PROFILE_ID", "REASONING_EFFORT", "SERVICE_TIER", "UNIT_IDS",
    "load_import_business_profile",
]
