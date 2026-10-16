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
