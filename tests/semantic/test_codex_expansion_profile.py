from pathlib import Path

import pytest

from tests.semantic.support.codex_expansion_profile import load_expansion_profile, validate_model_configuration


PROFILE = Path(__file__).parent / "data" / "integration-expansion-v1" / "profile.json"


def test_profile_counts_business_and_boundary_units_separately():
    profile = load_expansion_profile(PROFILE)
    assert len(profile.units) == 13
    assert [unit.unit_id for unit in profile.capability_boundaries] == ["EXP22-M05"]
    assert all(unit.policy == ("ask_before_changes" if unit.case_id in {"C01", "C03"} else "allow_changes")
               for unit in profile.units)


def test_initial_pilot_is_three_2025_units_without_implicit_version_multiplication():
    profile = load_expansion_profile(PROFILE, unit_ids=("C01", "M01", "C06"), versions=("2025.1",))
    assert [unit.unit_id for unit in profile.units] == ["EXP25-C01", "EXP25-C06", "EXP25-M01"]
    assert not profile.capability_boundaries


def test_boundary_only_selection_does_not_become_a_successful_agent_case():
    profile = load_expansion_profile(PROFILE, unit_ids=("M05",), versions=("2022.1",))
    assert profile.units == () and len(profile.capability_boundaries) == 1


@pytest.mark.parametrize("values", [("gpt-6-luna", "high", "default"),
                                    ("gpt-6.1-sol", "medium", "default"),
                                    ("gpt-6.1-sol", "high", "default"),
                                    ("gpt-6-luna", "medium", "default")])
def test_reviewed_model_configuration(values):
    validate_model_configuration(*values)


@pytest.mark.parametrize("values", [("gpt-5.6-terra", "medium", "default"),
                                    ("gpt-6.1-sol", "xhigh", "default"),
                                    ("gpt-6.1-sol", "high", "priority"),
                                    ("gpt-6-luna", "high", "priority")])
def test_no_silent_model_or_tier_fallback(values):
    with pytest.raises(ValueError):
        validate_model_configuration(*values)
