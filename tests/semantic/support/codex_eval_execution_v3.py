"""Closed execution selection and turn planning for the reviewed v3 heavy suite.

This module is deliberately side-effect free.  It turns the approved v3
definitions into atomic campaign units and an exact multi-turn shape, but it
does not materialize fixtures, start Codex, connect to Wwise, or interpret
executable callbacks from JSON.  Live request and oracle adapters are supplied
by the separately closed runner registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .codex_eval_bundle_v3 import EvalBundleV3, EvalBundleV3Error, OnlineScenario


HEAVY_PROFILE_ID = "heavy_cross_version_80"
HEAVY_API_URIS = frozenset(
    {
        "ak.wwise.core.object.get",
        "ak.wwise.core.object.create",
        "ak.wwise.core.object.set",
        "ak.wwise.core.audio.import",
        "ak.wwise.core.audio.importTabDelimited",
        "ak.wwise.core.audio.convert",
        "ak.wwise.core.mediaPool.get",
        "ak.wwise.core.soundbank.generate",
        "ak.wwise.core.soundbank.generated",
        "ak.wwise.core.soundbank.processDefinitionFiles",
        "ak.wwise.core.soundbank.convertExternalSources",
        "ak.wwise.core.soundbank.setInclusions",
        "ak.wwise.cli.generateSoundbank",
        "ak.wwise.cli.tabDelimitedImport",
        "ak.wwise.cli.convertExternalSource",
        "ak.wwise.cli.migrate",
    }
)
HEAVY_PROFILE_VERSION_COUNTS = {"2022.1": 70, "2024.1": 5, "2025.1": 5}
HEAVY_PROFILE_SCENARIO_COUNT = 80
HEAVY_PROFILE_USER_TURN_COUNT = 145
HEAVY_PROFILE_CONFIRMATION_TURN_COUNT = 65
ZERO_PRIMARY_DISPATCH_SCENARIO_IDS = frozenset(
    {"O22-AUDIO-TAB-01", "O22-SB-PROCESS-DEF-05"}
)
MULTI_TRANSACTION_SCENARIO_COUNTS = {"O22-AUDIO-TAB-02": 3}


class V3ExecutionPlanError(EvalBundleV3Error):
    """The approved v3 definitions cannot form the frozen heavy profile."""


@dataclass(frozen=True, slots=True)
class ScenarioTurn:
    """One natural user turn in a single memory-isolated Codex task."""

    index: int
    kind: str
    prompt: str
    transaction_index: int | None
    expects_next_preview: bool


@dataclass(frozen=True, slots=True)
class HeavyScenarioUnit:
    """One atomic campaign unit and its exact user-turn topology."""

    scenario: OnlineScenario
    version: str
    turns: tuple[ScenarioTurn, ...]

    @property
    def unit_id(self) -> str:
        return self.scenario.id

    @property
    def transaction_count(self) -> int:
        return self.scenario.confirmation_turn_count

    @property
    def user_turn_count(self) -> int:
        return len(self.turns)


def select_heavy_scenarios(
    bundle: EvalBundleV3,
    *,
    scenario_ids: Sequence[str] = (),
    versions: Sequence[str] = (),
) -> tuple[OnlineScenario, ...]:
    """Select the approved 80-case profile without silently widening it."""

    heavy = tuple(case for case in bundle.scenarios if case.api in HEAVY_API_URIS)
    _validate_complete_profile(heavy)

    requested_ids = _unique_filter(scenario_ids, label="scenario ids")
    requested_versions = _unique_filter(versions, label="versions")
    unknown_ids = sorted(set(requested_ids) - {case.id for case in heavy})
    if unknown_ids:
        raise V3ExecutionPlanError(
            "unknown or non-heavy v3 scenario ids: " + ", ".join(unknown_ids)
        )
    unknown_versions = sorted(
        set(requested_versions) - set(HEAVY_PROFILE_VERSION_COUNTS)
    )
    if unknown_versions:
        raise V3ExecutionPlanError(
            "the heavy profile has no scenarios for versions: "
            + ", ".join(unknown_versions)
        )

    selected = tuple(
        case
        for case in heavy
        if (not requested_ids or case.id in requested_ids)
        and (not requested_versions or _representative_version(case) in requested_versions)
    )
    if not selected:
        raise V3ExecutionPlanError("no v3 heavy scenarios matched the requested filters")
    return selected


def build_heavy_units(
    scenarios: Iterable[OnlineScenario],
) -> tuple[HeavyScenarioUnit, ...]:
    units = tuple(
        HeavyScenarioUnit(
            scenario=scenario,
            version=_representative_version(scenario),
            turns=_build_turns(scenario),
        )
        for scenario in scenarios
    )
    ids = [unit.unit_id for unit in units]
    if len(ids) != len(set(ids)):
        raise V3ExecutionPlanError("heavy campaign units contain duplicate scenario ids")
    return units


def required_unit_map(
    units: Sequence[HeavyScenarioUnit],
) -> dict[str, tuple[str, ...]]:
    """Return the campaign consolidation shape for atomic scenario units."""

    return {unit.unit_id: ("scenario",) for unit in units}


def _build_turns(scenario: OnlineScenario) -> tuple[ScenarioTurn, ...]:
    turns = [
        ScenarioTurn(
            index=1,
            kind="request",
            prompt=scenario.prompt,
            transaction_index=None,
            expects_next_preview=False,
        )
    ]
    confirmation_count = scenario.confirmation_turn_count
    if scenario.id in ZERO_PRIMARY_DISPATCH_SCENARIO_IDS:
        if confirmation_count != 0:
            raise V3ExecutionPlanError(
                f"{scenario.id} is a zero-dispatch refusal but requests confirmation"
            )
        return tuple(turns)

    expected_multi = MULTI_TRANSACTION_SCENARIO_COUNTS.get(scenario.id)
    if expected_multi is not None and confirmation_count != expected_multi:
        raise V3ExecutionPlanError(
            f"{scenario.id} must preserve {expected_multi} separate transactions"
        )
    if scenario.protocol == "single":
        if confirmation_count != 0:
            raise V3ExecutionPlanError(
                f"single-turn scenario {scenario.id} unexpectedly requests confirmation"
            )
        return tuple(turns)
    if confirmation_count < 1 or not scenario.confirmation_prompt:
        raise V3ExecutionPlanError(
            f"preview/confirm scenario {scenario.id} lacks a dispatch-bound confirmation"
        )

    for transaction_index in range(1, confirmation_count + 1):
        turns.append(
            ScenarioTurn(
                index=len(turns) + 1,
                kind="confirmation",
                prompt=scenario.confirmation_prompt,
                transaction_index=transaction_index,
                expects_next_preview=transaction_index < confirmation_count,
            )
        )
    return tuple(turns)


def _validate_complete_profile(scenarios: Sequence[OnlineScenario]) -> None:
    if len(scenarios) != HEAVY_PROFILE_SCENARIO_COUNT:
        raise V3ExecutionPlanError(
            "heavy profile must contain exactly "
            f"{HEAVY_PROFILE_SCENARIO_COUNT} scenarios, found {len(scenarios)}"
        )
    by_api = {api: 0 for api in HEAVY_API_URIS}
    version_counts = {version: 0 for version in HEAVY_PROFILE_VERSION_COUNTS}
    confirmation_count = 0
    user_turn_count = 0
    zero_dispatch_ids: set[str] = set()
    for scenario in scenarios:
        by_api[scenario.api] += 1
        version = _representative_version(scenario)
        if version not in version_counts:
            raise V3ExecutionPlanError(
                f"{scenario.id} uses unsupported heavy-profile version {version}"
            )
        version_counts[version] += 1
        confirmation_count += scenario.confirmation_turn_count
        user_turn_count += 1 + scenario.confirmation_turn_count
        if scenario.primary_dispatch.count == 0:
            zero_dispatch_ids.add(scenario.id)
    wrong_api_counts = {api: count for api, count in by_api.items() if count != 5}
    if wrong_api_counts:
        raise V3ExecutionPlanError(
            f"heavy profile must contain five scenarios per API: {wrong_api_counts}"
        )
    if version_counts != HEAVY_PROFILE_VERSION_COUNTS:
        raise V3ExecutionPlanError(
            f"heavy profile version distribution drifted: {version_counts}"
        )
    if confirmation_count != HEAVY_PROFILE_CONFIRMATION_TURN_COUNT:
        raise V3ExecutionPlanError(
            "heavy confirmation-turn count drifted: "
            f"expected {HEAVY_PROFILE_CONFIRMATION_TURN_COUNT}, found {confirmation_count}"
        )
    if user_turn_count != HEAVY_PROFILE_USER_TURN_COUNT:
        raise V3ExecutionPlanError(
            "heavy user-turn count drifted: "
            f"expected {HEAVY_PROFILE_USER_TURN_COUNT}, found {user_turn_count}"
        )
    if zero_dispatch_ids != ZERO_PRIMARY_DISPATCH_SCENARIO_IDS:
        raise V3ExecutionPlanError(
            f"heavy zero-dispatch refusal set drifted: {sorted(zero_dispatch_ids)}"
        )


def _representative_version(scenario: OnlineScenario) -> str:
    if len(scenario.versions) != 1:
        raise V3ExecutionPlanError(
            f"heavy scenario {scenario.id} must pin exactly one execution version"
        )
    return scenario.versions[0]


def _unique_filter(values: Sequence[str], *, label: str) -> tuple[str, ...]:
    normalized = tuple(str(value) for value in values)
    if len(normalized) != len(set(normalized)):
        raise V3ExecutionPlanError(f"duplicate {label} are not allowed")
    return normalized


__all__ = [
    "HEAVY_API_URIS",
    "HEAVY_PROFILE_CONFIRMATION_TURN_COUNT",
    "HEAVY_PROFILE_ID",
    "HEAVY_PROFILE_SCENARIO_COUNT",
    "HEAVY_PROFILE_USER_TURN_COUNT",
    "HEAVY_PROFILE_VERSION_COUNTS",
    "HeavyScenarioUnit",
    "MULTI_TRANSACTION_SCENARIO_COUNTS",
    "ScenarioTurn",
    "V3ExecutionPlanError",
    "ZERO_PRIMARY_DISPATCH_SCENARIO_IDS",
    "build_heavy_units",
    "required_unit_map",
    "select_heavy_scenarios",
]
