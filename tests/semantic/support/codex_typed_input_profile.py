"""Closed loader for the fixed 25-task, five-version typed-input profile.

The profile derives immutable task definitions from the reviewed V3 bundle and
returns the same small unit interface consumed by the existing semantic matrix.
It does not start Codex or Wwise, materialize a fixture, or implement a second
runner or business oracle.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_eval_bundle_v3 import (
    EvalBundleV3Error,
    OnlineScenario,
    load_eval_bundle_v3,
)
from tests.semantic.support.codex_eval_execution_v3 import ScenarioTurn


PROFILE_CONTRACT = "waapi-skill.codex-typed-input-profile/v1"
PROFILE_ID = "typed_input_cross_version_25"
BASE_SUITE_REPO_RELATIVE = "skills/waapi-skill/evals/suite-v3.json"
SUPPORTED_VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
REQUIRED_CATEGORIES = (
    "zero",
    "inline",
    "draft",
    "generic",
    "dedicated",
    "query",
    "topic",
    "metadata",
    "file_code",
    "weak_verifier",
)
PROFILE_TASK_COUNT = 25
TASKS_PER_VERSION = 5
MODEL_SETTINGS = {
    "model": "gpt-5.6-terra",
    "reasoning_effort": "medium",
    "service_tier": "default",
    "memory": "disabled",
}
_PROFILE_KEYS = {
    "contract",
    "profile_id",
    "base_suite",
    "versions",
    "required_categories",
    "model_settings",
    "totals",
    "tasks",
}
_TASK_REQUIRED_KEYS = {
    "unit_id",
    "base_scenario_id",
    "api",
    "version",
    "categories",
}
_TASK_KEYS = _TASK_REQUIRED_KEYS | {"prompt", "confirmation_prompt"}
_UNIT_ID_RE = re.compile(r"^TYP(?:21|22|23|24|25)-[A-Z0-9][A-Z0-9-]*$")


class TypedInputProfileError(EvalBundleV3Error):
    """The fixed typed-input profile is malformed or drifted."""


@dataclass(frozen=True, slots=True)
class TypedInputUnit:
    unit_id: str
    base_scenario_id: str
    scenario: OnlineScenario
    version: str
    categories: tuple[str, ...]
    turns: tuple[ScenarioTurn, ...]

    @property
    def transaction_count(self) -> int:
        return self.scenario.confirmation_turn_count

    @property
    def user_turn_count(self) -> int:
        return len(self.turns)


@dataclass(frozen=True, slots=True)
class TypedInputProfile:
    path: Path
    base_suite_path: Path
    definition_sha256: str
    units: tuple[TypedInputUnit, ...]


def load_typed_input_profile(
    path: str | Path,
    *,
    unit_ids: Sequence[str] = (),
    versions: Sequence[str] = (),
) -> TypedInputProfile:
    profile_path = Path(path).expanduser().resolve(strict=True)
    root = _load_json(profile_path)
    if set(root) != _PROFILE_KEYS:
        raise TypedInputProfileError("typed-input profile schema is not closed")
    if (
        root.get("contract") != PROFILE_CONTRACT
        or root.get("profile_id") != PROFILE_ID
        or root.get("base_suite") != BASE_SUITE_REPO_RELATIVE
    ):
        raise TypedInputProfileError("typed-input profile identity drifted")
    if _strings(root.get("versions"), "versions") != SUPPORTED_VERSIONS:
        raise TypedInputProfileError("typed-input profile versions drifted")
    if _strings(root.get("required_categories"), "required_categories") != REQUIRED_CATEGORIES:
        raise TypedInputProfileError("typed-input required categories drifted")
    if root.get("model_settings") != MODEL_SETTINGS:
        raise TypedInputProfileError("typed-input model settings drifted")
    if root.get("totals") != {
        "task_count": PROFILE_TASK_COUNT,
        "tasks_per_version": TASKS_PER_VERSION,
    }:
        raise TypedInputProfileError("typed-input totals drifted")

    repo_root = Path(__file__).resolve().parents[3]
    base_suite_path = (repo_root / BASE_SUITE_REPO_RELATIVE).resolve(strict=True)
    bundle = load_eval_bundle_v3(base_suite_path)
    raw_tasks = root.get("tasks")
    if not isinstance(raw_tasks, list):
        raise TypedInputProfileError("typed-input tasks must be an array")
    complete_units = tuple(
        _parse_unit(value, index=index, bundle=bundle)
        for index, value in enumerate(raw_tasks)
    )
    _validate_complete_units(complete_units)

    requested_ids = _unique_strings(unit_ids, "unit ids")
    requested_versions = _unique_strings(versions, "versions")
    known_ids = {unit.unit_id for unit in complete_units}
    unknown_ids = sorted(set(requested_ids) - known_ids)
    if unknown_ids:
        raise TypedInputProfileError(
            "unknown typed-input unit ids: " + ", ".join(unknown_ids)
        )
    unknown_versions = sorted(set(requested_versions) - set(SUPPORTED_VERSIONS))
    if unknown_versions:
        raise TypedInputProfileError(
            "typed-input profile has no units for versions: "
            + ", ".join(unknown_versions)
        )
    selected = tuple(
        unit
        for unit in complete_units
        if (not requested_ids or unit.unit_id in requested_ids)
        and (not requested_versions or unit.version in requested_versions)
    )
    if not selected:
        raise TypedInputProfileError("no typed-input units matched the filters")
    return TypedInputProfile(
        path=profile_path,
        base_suite_path=base_suite_path,
        definition_sha256=hashlib.sha256(profile_path.read_bytes()).hexdigest(),
        units=selected,
    )


def _parse_unit(value: Any, *, index: int, bundle: Any) -> TypedInputUnit:
    path = f"tasks[{index}]"
    if (
        not isinstance(value, dict)
        or not _TASK_REQUIRED_KEYS.issubset(value)
        or not set(value).issubset(_TASK_KEYS)
    ):
        raise TypedInputProfileError(f"{path} schema is not closed")
    unit_id = _text(value.get("unit_id"), f"{path}.unit_id")
    if _UNIT_ID_RE.fullmatch(unit_id) is None:
        raise TypedInputProfileError(f"{path}.unit_id is invalid")
    base_scenario_id = _text(
        value.get("base_scenario_id"), f"{path}.base_scenario_id"
    )
    api = _text(value.get("api"), f"{path}.api")
    version = _text(value.get("version"), f"{path}.version")
    if version not in SUPPORTED_VERSIONS:
        raise TypedInputProfileError(f"{path}.version is unsupported")
    categories = _strings(value.get("categories"), f"{path}.categories")
    if not categories or len(categories) != len(set(categories)):
        raise TypedInputProfileError(f"{path}.categories are invalid")
    if set(categories) - set(REQUIRED_CATEGORIES):
        raise TypedInputProfileError(f"{path}.categories contain unknown values")

    scenario = bundle.scenario(base_scenario_id)
    blockers = bundle.scenario_mapping_blockers(base_scenario_id)
    if blockers:
        raise TypedInputProfileError(
            f"{base_scenario_id} retains unresolved request mappings: "
            + ", ".join(item.id for item in blockers)
        )
    if scenario.api != api:
        raise TypedInputProfileError(f"{path}.api differs from its V3 scenario")
    prompt = value.get("prompt", scenario.prompt)
    if not isinstance(prompt, str) or not prompt.strip():
        raise TypedInputProfileError(f"{path}.prompt must be non-empty text")
    confirmation_prompt = value.get(
        "confirmation_prompt",
        scenario.confirmation_prompt,
    )
    if scenario.protocol != "single" and (
        not isinstance(confirmation_prompt, str)
        or not confirmation_prompt.strip()
    ):
        raise TypedInputProfileError(
            f"{path}.confirmation_prompt must be non-empty text"
        )
    scenario = replace(
        scenario,
        versions=(version,),
        prompt=prompt,
        confirmation_prompt=confirmation_prompt,
    )
    turns = _turns(scenario)
    return TypedInputUnit(
        unit_id=unit_id,
        base_scenario_id=base_scenario_id,
        scenario=scenario,
        version=version,
        categories=categories,
        turns=turns,
    )


def _turns(scenario: OnlineScenario) -> tuple[ScenarioTurn, ...]:
    turns = [
        ScenarioTurn(1, "request", scenario.prompt, None, False)
    ]
    if scenario.protocol == "single":
        if scenario.confirmation_turn_count != 0:
            raise TypedInputProfileError(
                f"{scenario.id} single protocol requests confirmation"
            )
        return tuple(turns)
    if scenario.confirmation_turn_count != 1 or not scenario.confirmation_prompt:
        raise TypedInputProfileError(
            f"{scenario.id} must have exactly one confirmation turn"
        )
    turns.append(
        ScenarioTurn(2, "confirmation", scenario.confirmation_prompt, 1, False)
    )
    return tuple(turns)


def _validate_complete_units(units: Sequence[TypedInputUnit]) -> None:
    if len(units) != PROFILE_TASK_COUNT:
        raise TypedInputProfileError(
            f"typed-input profile requires {PROFILE_TASK_COUNT} tasks"
        )
    ids = tuple(unit.unit_id for unit in units)
    if len(ids) != len(set(ids)):
        raise TypedInputProfileError("typed-input unit ids must be unique")
    counts = Counter(unit.version for unit in units)
    expected = {version: TASKS_PER_VERSION for version in SUPPORTED_VERSIONS}
    if counts != expected:
        raise TypedInputProfileError(
            f"typed-input version distribution drifted: {dict(counts)}"
        )
    covered = {category for unit in units for category in unit.categories}
    if covered != set(REQUIRED_CATEGORIES):
        raise TypedInputProfileError(
            "typed-input category coverage drifted: " + repr(sorted(covered))
        )


def _load_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TypedInputProfileError(f"typed-input profile is invalid: {exc}") from exc
    if not isinstance(value, dict):
        raise TypedInputProfileError("typed-input profile root must be an object")
    return value


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypedInputProfileError(f"{path} must be non-empty text")
    return value


def _strings(value: Any, path: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise TypedInputProfileError(f"{path} must be an array of text")
    return tuple(value)


def _unique_strings(values: Sequence[str], label: str) -> tuple[str, ...]:
    normalized = tuple(str(value) for value in values)
    if len(normalized) != len(set(normalized)):
        raise TypedInputProfileError(f"duplicate {label} are not allowed")
    return normalized


__all__ = [
    "MODEL_SETTINGS",
    "PROFILE_CONTRACT",
    "PROFILE_ID",
    "PROFILE_TASK_COUNT",
    "REQUIRED_CATEGORIES",
    "SUPPORTED_VERSIONS",
    "TypedInputProfile",
    "TypedInputProfileError",
    "TypedInputUnit",
    "load_typed_input_profile",
]
