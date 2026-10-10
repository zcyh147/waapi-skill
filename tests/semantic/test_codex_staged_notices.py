"""Exact stage-linked notices through the existing public grading seam."""
import copy
import json
from pathlib import Path

import pytest

from tests.semantic.test_codex_expansion_task_runner import _grammatical_notice


_CASES = json.loads((Path(__file__).parents[1] / "fixtures/semantic/expansion-staged-notices-eba698d.json").read_text())["cases"]


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case["case"])
def test_actual_eba_notice_composes_one_sealed_effect_and_preview_adoption(case):
    assert _grammatical_notice(copy.deepcopy(case))


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case["case"])
@pytest.mark.parametrize("claim", ["同时修改 Pitch 为12。", "目标是 OtherOwner。", "我不会执行该预览。"])
def test_staged_effect_does_not_hide_post_preview_contradictions(case, claim):
    case = copy.deepcopy(case)
    case["events"][-2]["item"]["text"] += claim
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("mode", ["read_only", "ask_before_changes", "unknown"])
def test_local_curve_authorization_cannot_mask_a_composite_invalid_policy(mode):
    case = copy.deepcopy(_CASES[0])
    case["events"][-2]["item"]["text"] += f"已取得 allow_changes 策略的独立授权，当前策略为 {mode}。"
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("damage", ["pre_only", "generic", "refusal", "wrong_label", "changed_plan", "competing_plan", "wrong_kind"])
def test_one_earlier_plan_requires_exact_post_preview_adoption_without_contradictions(damage):
    case = copy.deepcopy(_CASES[1])
    if damage == "pre_only":
        case["events"].pop(-2)
    elif damage == "generic":
        case["events"][-2]["item"]["text"] = "预览已生成，现在执行。"
    elif damage == "refusal":
        case["events"][-2]["item"]["text"] += "不会执行追加 Wwise Gain。"
    elif damage == "wrong_label":
        case["events"][-2]["item"]["text"] = case["events"][-2]["item"]["text"].replace("追加 Wwise Gain", "追加 Sound")
    elif damage == "changed_plan":
        case["artifact"]["request"]["arguments"]["plugin"]["name"] = "OtherGain"
    elif damage == "competing_plan":
        case["events"].insert(2, {"type": "item.completed", "item": {"type": "agent_message", "text": "将在 OtherOwner 上追加 OtherGain。"}})
    else:
        case["events"][1]["item"]["text"] = case["events"][1]["item"]["text"].replace("实时插件目录确认 Wwise Gain", "实时插件目录确认 Sound")
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("old", ["OtherTrigger", "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"])
def test_sole_assignment_scope_requires_the_independent_old_trigger(old):
    case = copy.deepcopy(_CASES[-1])
    case["events"][-2]["item"]["text"] = case["events"][-2]["item"]["text"].replace("从 Bonus", "从 " + old)
    assert not _grammatical_notice(case)


def test_assignment_origin_needs_prepared_and_independent_value_agreement():
    case = copy.deepcopy(_CASES[-1])
    case["artifact"]["prepared_operation"]["pre_state"]["field_before"]["value"]["id"] = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("claim", [
    "目标是 OtherSound。", "不会执行这项修改。", "备注改为“Different notes”。",
    "本次修改已取得独立授权，策略为 read_only。",
])
def test_separate_intervening_claim_invalidates_the_earlier_staged_plan(claim):
    case = copy.deepcopy(_CASES[1])
    case["events"].insert(2, {"type": "item.completed", "item": {"type": "agent_message", "text": claim}})
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("claim", ["正在核对插件元数据。", "目前尚未修改工程。", "不会修改其他对象。"])
def test_separate_neutral_progress_does_not_invalidate_a_complete_plan(claim):
    case = copy.deepcopy(_CASES[1])
    case["events"].insert(2, {"type": "item.completed", "item": {"type": "agent_message", "text": claim}})
    assert _grammatical_notice(case)


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case["case"])
@pytest.mark.parametrize("fresh_notice", [False, True])
def test_each_preview_requires_its_own_post_preview_notice(case, fresh_notice):
    case = copy.deepcopy(case)
    preview = next(event for event in case["events"] if event["item"].get("command") == "preview-from-draft")
    post = copy.deepcopy(case["events"][-2])
    case["events"].insert(-1, copy.deepcopy(preview))
    if fresh_notice:
        case["events"].insert(-1, post)
    assert _grammatical_notice(case) is fresh_notice
