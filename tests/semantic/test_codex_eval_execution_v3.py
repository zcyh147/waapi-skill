from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from tests.semantic.support.codex_eval_bundle_v3 import load_eval_bundle_v3
from tests.semantic.support.codex_eval_execution_v3 import (
    HEAVY_PROFILE_CONFIRMATION_TURN_COUNT,
    HEAVY_PROFILE_SCENARIO_COUNT,
    HEAVY_PROFILE_USER_TURN_COUNT,
    HEAVY_PROFILE_VERSION_COUNTS,
    V3ExecutionPlanError,
    build_heavy_units,
    required_unit_map,
    select_heavy_scenarios,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SUITE_V3 = REPO_ROOT / "skills" / "waapi-skill" / "evals" / "suite-v3.json"


def test_heavy_profile_is_exactly_80_atomic_scenarios_and_145_user_turns() -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)
    scenarios = select_heavy_scenarios(bundle)
    units = build_heavy_units(scenarios)

    assert len(units) == HEAVY_PROFILE_SCENARIO_COUNT == 80
    assert sum(unit.user_turn_count for unit in units) == HEAVY_PROFILE_USER_TURN_COUNT == 145
    assert sum(unit.transaction_count for unit in units) == HEAVY_PROFILE_CONFIRMATION_TURN_COUNT == 65
    assert Counter(unit.version for unit in units) == HEAVY_PROFILE_VERSION_COUNTS
    assert required_unit_map(units) == {
        unit.unit_id: ("scenario",) for unit in units
    }


def test_heavy_profile_preserves_zero_dispatch_refusals_and_three_transactions() -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)
    units = {unit.unit_id: unit for unit in build_heavy_units(select_heavy_scenarios(bundle))}

    for scenario_id in ("O22-AUDIO-TAB-01", "O22-SB-PROCESS-DEF-05"):
        unit = units[scenario_id]
        assert unit.scenario.primary_dispatch.count == 0
        assert unit.transaction_count == 0
        assert [turn.kind for turn in unit.turns] == ["request"]

    sequential = units["O22-AUDIO-TAB-02"]
    assert sequential.transaction_count == 3
    assert [turn.kind for turn in sequential.turns] == [
        "request",
        "confirmation",
        "confirmation",
        "confirmation",
    ]
    assert [turn.expects_next_preview for turn in sequential.turns] == [
        False,
        True,
        True,
        False,
    ]


def test_heavy_selection_filters_only_after_validating_the_frozen_profile() -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)
    selected = select_heavy_scenarios(
        bundle,
        scenario_ids=("VS24-F-AUDIO-CONVERT-01",),
        versions=("2024.1",),
    )
    assert [scenario.id for scenario in selected] == ["VS24-F-AUDIO-CONVERT-01"]

    with pytest.raises(V3ExecutionPlanError, match="unknown or non-heavy"):
        select_heavy_scenarios(bundle, scenario_ids=("C1",))
    with pytest.raises(V3ExecutionPlanError, match="no scenarios for versions"):
        select_heavy_scenarios(bundle, versions=("2021.1",))
