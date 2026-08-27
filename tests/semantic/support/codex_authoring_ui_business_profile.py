"""Targeted Fresh Agent profile for Authoring UI capture and command previews."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_business_profile_contract import (
    load_closed_business_profile_source,
    select_closed_business_profile_units,
)


PROFILE_CONTRACT = "waapi-skill.authoring-ui-business-profile/v1"
PROFILE_ID = "authoring_ui_business_2"
MODEL = "gpt-5.6-terra"
REASONING_EFFORT = "medium"
SERVICE_TIER = "default"
UNIT_IDS = ("AUI22-CAPTURE-PREVIEW", "AUI25-SAVE-PREVIEW")
VERSIONS = ("2022.1", "2025.1")
_OPERATIONS = {
    UNIT_IDS[0]: ("ui.captureScreen", "ak.wwise.ui.captureScreen", "2022.1"),
    UNIT_IDS[1]: (
        "ui.commands.execute",
        "ak.wwise.ui.commands.execute",
        "2025.1",
    ),
}
_FORBIDDEN_PROMPT_MECHANICS = (
    "draft-start",
    "draft-declare",
    "operation-request",
    "request-json",
    "ak.wwise.",
    "schema-digest",
)


class AuthoringUiBusinessProfileError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AuthoringUiBusinessScenario:
    id: str
    api: str
    prompt_sha256: str


@dataclass(frozen=True, slots=True)
class AuthoringUiBusinessUnit:
    unit_id: str
    operation: str
    version: str
    prompt: str
    request_arguments: Mapping[str, Any]
    final_markers: tuple[str, ...]
    scenario: AuthoringUiBusinessScenario

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
class AuthoringUiBusinessProfile:
    path: Path
    definition_sha256: str
    units: tuple[AuthoringUiBusinessUnit, ...]


def load_authoring_ui_business_profile(
    path: str | Path,
    *,
    unit_ids: Sequence[str] = (),
    versions: Sequence[str] = (),
) -> AuthoringUiBusinessProfile:
    source = load_closed_business_profile_source(
        path,
        contract=PROFILE_CONTRACT,
        profile_id=PROFILE_ID,
        model=MODEL,
        reasoning_effort=REASONING_EFFORT,
        service_tier=SERVICE_TIER,
        expected_unit_count=2,
        error_type=AuthoringUiBusinessProfileError,
        subject="Authoring UI",
    )
    parsed = tuple(_parse_unit(value) for value in source.units)
    units = select_closed_business_profile_units(
        parsed,
        unit_ids=unit_ids,
        versions=versions,
        known_unit_ids=UNIT_IDS,
        supported_versions=VERSIONS,
        error_type=AuthoringUiBusinessProfileError,
        subject="Authoring UI",
    )
    return AuthoringUiBusinessProfile(
        path=source.path,
        definition_sha256=source.definition_sha256,
        units=units,
    )


def _parse_unit(value: Any) -> AuthoringUiBusinessUnit:
    keys = {
        "unit_id",
        "operation",
        "api",
        "version",
        "prompt",
        "request_arguments",
        "final_markers",
    }
    if not isinstance(value, Mapping) or set(value) != keys:
        raise AuthoringUiBusinessProfileError("Authoring UI unit is not closed")
    unit_id = value.get("unit_id")
    expected = _OPERATIONS.get(str(unit_id))
    if expected is None or tuple(
        value.get(field) for field in ("operation", "api", "version")
    ) != expected:
        raise AuthoringUiBusinessProfileError("Authoring UI unit identity drifted")
    prompt = value.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or any(
        token in prompt.casefold() for token in _FORBIDDEN_PROMPT_MECHANICS
    ):
        raise AuthoringUiBusinessProfileError("Authoring UI prompt is invalid")
    arguments = value.get("request_arguments")
    if not isinstance(arguments, Mapping):
        raise AuthoringUiBusinessProfileError("Authoring UI arguments are invalid")
    expected_arguments = (
        {"view_name": "Project Explorer"}
        if unit_id == UNIT_IDS[0]
        else {"command": "SaveProject"}
    )
    if dict(arguments) != expected_arguments:
        raise AuthoringUiBusinessProfileError("Authoring UI arguments drifted")
    markers = value.get("final_markers")
    if not isinstance(markers, list) or not markers or any(
        not isinstance(marker, str) or not marker for marker in markers
    ):
        raise AuthoringUiBusinessProfileError("Authoring UI markers are invalid")
    api = str(value["api"])
    return AuthoringUiBusinessUnit(
        unit_id=str(unit_id),
        operation=str(value["operation"]),
        version=str(value["version"]),
        prompt=prompt,
        request_arguments=dict(arguments),
        final_markers=tuple(markers),
        scenario=AuthoringUiBusinessScenario(
            id=str(unit_id),
            api=api,
            prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        ),
    )


__all__ = [
    "MODEL",
    "PROFILE_ID",
    "REASONING_EFFORT",
    "SERVICE_TIER",
    "UNIT_IDS",
    "VERSIONS",
    "AuthoringUiBusinessProfile",
    "AuthoringUiBusinessProfileError",
    "AuthoringUiBusinessScenario",
    "AuthoringUiBusinessUnit",
    "load_authoring_ui_business_profile",
]
