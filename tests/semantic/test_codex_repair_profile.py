from pathlib import Path

from tests.semantic.support.codex_repair_profile import load_repair_profile

PROFILE = Path(__file__).parent / "data/waapi-v11-repairs/profile.json"


def test_first_batch_is_four_tasks_four_turns_three_transactions_without_review_calls():
    profile = load_repair_profile(PROFILE)
    assert [(unit.case_id, unit.version, unit.policy, unit.transaction_count)
            for unit in profile.units] == [
        ("F1", "2025.1", "allow_changes", 1),
        ("F2", "2025.1", "read_only", 0),
        ("F3", "2025.1", "allow_changes", 1),
        ("F4", "2025.1", "allow_changes", 1),
    ]
    assert sum(unit.user_turn_count for unit in profile.units) == 4
    assert profile.budget == {"fresh_tasks": 4, "user_turns": 4, "model_calls": 4,
                              "transactions": 3, "hard_seconds_per_task": 600,
                              "hard_seconds_total": 2400, "gateway_calls_per_task": 96,
                              "reviewer_model_calls": 0, "automatic_reruns": 0}


import json
import pytest


@pytest.mark.parametrize("selection", [{"unit_ids": ("F1",)}, {"versions": ("2022.1",)},
                                      {"versions": ("2025.1", "2025.1")}])
def test_approved_batch_cannot_silently_expand_repeat_or_shrink(selection):
    with pytest.raises(ValueError):
        load_repair_profile(PROFILE, **selection)


@pytest.mark.parametrize("change", ["model", "policy", "command", "extra_case"])
def test_unreviewed_profile_changes_fail_closed(tmp_path, change):
    data = json.loads(PROFILE.read_text())
    if change == "model":
        data["model"]["name"] = "gpt-6-luna"
    elif change == "policy":
        data["units"][1]["policy"] = "allow_changes"
    elif change == "command":
        data["units"][0]["prompt"] += " Use gateway.py draft-start."
    else:
        data["units"].append(data["units"][0])
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_repair_profile(path)


def test_fixture_parents_are_stored_as_closed_business_segments():
    profile = load_repair_profile(PROFILE)
    assert [unit.parent_segments for unit in profile.units] == [
        ("Effects", "Default Work Unit"), ("Game Parameters", "Default Work Unit"),
        ("Game Parameters", "Default Work Unit"), ("Effects", "Default Work Unit")]


def test_documented_remaining_suffix_has_three_tasks_two_transactions_and_no_f1():
    profile = load_repair_profile(PROFILE, unit_ids=("REPAIR25-F2", "REPAIR25-F3", "REPAIR25-F4"))
    assert [unit.case_id for unit in profile.units] == ["F2", "F3", "F4"]
    assert profile.budget == {"fresh_tasks": 3, "user_turns": 3, "model_calls": 3,
        "transactions": 2, "hard_seconds_per_task": 600, "hard_seconds_total": 1800,
        "gateway_calls_per_task": 96, "reviewer_model_calls": 0, "automatic_reruns": 0}


@pytest.mark.parametrize("ids", [("REPAIR25-F3",), ("REPAIR25-F1", "REPAIR25-F4"),
    ("REPAIR25-F3", "REPAIR25-F2"), ("REPAIR25-F2", "REPAIR25-F2"),
    ("REPAIR25-F2", "REPAIR25-F3", "REPAIR25-F3"),
    ("REPAIR25-F4", "REPAIR25-F3"), ("REPAIR25-F3", "REPAIR25-F3"),
    ("REPAIR25-F2", "REPAIR25-F4", "REPAIR25-F3"), ("REPAIR25-F2", "REPAIR25-F2", "REPAIR25-F4")])
def test_remaining_suffix_does_not_enable_arbitrary_subsets(ids):
    with pytest.raises(ValueError):
        load_repair_profile(PROFILE, unit_ids=ids)


def test_unattempted_final_pair_has_two_tasks_two_transactions_and_1200_seconds():
    profile = load_repair_profile(PROFILE, unit_ids=("REPAIR25-F3", "REPAIR25-F4"))
    assert [unit.case_id for unit in profile.units] == ["F3", "F4"]
    assert profile.budget == {"fresh_tasks": 2, "user_turns": 2, "model_calls": 2,
        "transactions": 2, "hard_seconds_per_task": 600, "hard_seconds_total": 1200,
        "gateway_calls_per_task": 96, "reviewer_model_calls": 0, "automatic_reruns": 0}


def test_final_unattempted_f4_is_one_task_transaction_and_600_seconds():
    profile = load_repair_profile(PROFILE, unit_ids=("REPAIR25-F4",))
    assert [unit.case_id for unit in profile.units] == ["F4"]
    assert profile.budget == {"fresh_tasks": 1, "user_turns": 1, "model_calls": 1,
        "transactions": 1, "hard_seconds_per_task": 600, "hard_seconds_total": 600,
        "gateway_calls_per_task": 96, "reviewer_model_calls": 0, "automatic_reruns": 0}


@pytest.mark.parametrize("ids,transactions", [(("REPAIR25-F2",), 0), (("REPAIR25-F2", "REPAIR25-F3"), 1)])
def test_explicit_retry_selectors_have_only_their_requested_budget(ids, transactions):
    profile = load_repair_profile(PROFILE, unit_ids=ids)
    assert tuple(unit.unit_id for unit in profile.units) == ids
    assert profile.budget == {"fresh_tasks": len(ids), "user_turns": len(ids), "model_calls": len(ids),
        "transactions": transactions, "hard_seconds_per_task": 600, "hard_seconds_total": 600 * len(ids),
        "gateway_calls_per_task": 96, "reviewer_model_calls": 0, "automatic_reruns": 0}
