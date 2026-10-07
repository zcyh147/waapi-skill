"""Operation nouns and bounded owner carry at the existing notice seam."""
import copy
import hashlib
import json
from itertools import permutations
from pathlib import Path

import pytest

from tests.semantic.test_codex_expansion_task_runner import _grammatical_notice


_FIXTURE = Path(__file__).parents[1] / "fixtures/semantic/expansion-operation-noun-700914d.json"
_CASE = json.loads(_FIXTURE.read_text())["cases"][0]


def test_exact_operation_noun_notice_from_frozen_700914d():
    case = copy.deepcopy(_CASE)
    assert case["events"][2] == case["source"]["notice_event"]
    assert case["source"]["notice_event_index"] == 23
    assert [row["event_index"] for row in case["source"]["phases"]] == [22, 24]
    assert _grammatical_notice(case)


_INDEPENDENT = Path(__file__).parents[1] / "fixtures/semantic/expansion-operation-noun-independent-20261007.json"
_DESIGN = json.loads(_INDEPENDENT.read_text())


@pytest.mark.parametrize("vector", _DESIGN["vectors"], ids=lambda row: row["id"])
def test_independent_operation_noun_and_owner_contrasts(vector):
    assert hashlib.sha256(_INDEPENDENT.read_bytes()).hexdigest() == "c8c668d22c038813fa0996d8ca30fcab2e30553ef0f165d77238c6dfc274da8a"
    case = copy.deepcopy(_DESIGN["fixture"])
    case["events"][case["replacement_event_index"]]["item"]["text"] = vector["notice"]
    for patch in vector.get("fixture_patches", []):
        assert patch["op"] == "replace"
        parts = patch["path"].lstrip("/").split("/")
        target = case
        for part in parts[:-1]:
            target = target[int(part)] if isinstance(target, list) else target[part]
        key = int(parts[-1]) if isinstance(target, list) else parts[-1]
        assert key in target if isinstance(target, dict) else 0 <= key < len(target)
        target[key] = patch["value"]
    if "event_order" in vector:
        case["events"] = [case["events"][index] for index in vector["event_order"]]
    for insertion in reversed(vector.get("event_inserts", [])):
        case["events"].insert(insertion["after_event_index"] + 1, copy.deepcopy(insertion["event"]))
    assert _grammatical_notice(case) is vector["expected"], vector["reason"]


@pytest.mark.parametrize("noun", ["追加", "添加", "新增", "创建", "插入"])
def test_current_operation_noun_is_shared_by_authorization_pending_and_execution(noun):
    case = copy.deepcopy(_DESIGN["fixture"])
    text = next(row["notice"] for row in _DESIGN["vectors"] if row["id"] == "P05")
    case["events"][1]["item"]["text"] = text.replace("此次追加", "此次" + noun)
    assert _grammatical_notice(case)


_NEUTRAL_COMPONENTS = (
    "此次追加已取得 allow_changes 策略的独立授权",
    "目前尚未修改",
    "修改前状态已记录",
)


@pytest.mark.parametrize("components", list(permutations(_NEUTRAL_COMPONENTS)))
@pytest.mark.parametrize("separator", ["。", "；", "，"])
def test_singleton_owner_crosses_only_complete_neutral_components(components, separator):
    case = copy.deepcopy(_DESIGN["fixture"])
    text = next(row["notice"] for row in _DESIGN["vectors"] if row["id"] == "P02")
    concrete = text[text.index("即将追加"):]
    case["events"][1]["item"]["text"] = separator.join(("已核对目标声音", *components, concrete))
    assert _grammatical_notice(case)


@pytest.mark.parametrize("whitespace", [" ", "\t", " \t "])
def test_validated_neutral_clause_edge_whitespace_preserves_owner(whitespace):
    case = copy.deepcopy(_DESIGN["fixture"])
    case["events"][1]["item"]["text"] = case["events"][1]["item"]["text"].replace("的独立授权，", "的独立授权" + whitespace + "，")
    assert _grammatical_notice(case)


@pytest.mark.parametrize("interlude", [
    "稍后再评估", "已核对 OtherSound", "已核对目标声音和 OtherSound",
    "对此次导入已取得 allow_changes 策略的独立授权",
    "此次追加已取得 allow_changes 策略的独立授权并修改 Pitch 为12",
    "修改前状态已记录并修改 Pitch 为12",
])
def test_unknown_or_conflicting_interlude_does_not_carry_owner(interlude):
    case = copy.deepcopy(_DESIGN["fixture"])
    case["events"][1]["item"]["text"] = case["events"][1]["item"]["text"].replace("即将追加", interlude + "。即将追加")
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("tail", [
    "第二次向目标声音追加 Wwise Gain 效果器 Expansion_EXP25-C09_NewGain，备注为“Expansion C09 appended gain”。",
    "再向目标声音追加一次 Wwise Gain 效果器 Expansion_EXP25-C09_NewGain，备注为“Expansion C09 appended gain”。",
])
def test_an_additional_actual_append_is_rejected_even_with_the_approved_descriptor(tail):
    case = copy.deepcopy(_DESIGN["fixture"])
    case["events"][1]["item"]["text"] += tail
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("tail", [
    "即将向目标声音追加 Wwise Gain 效果器 Expansion_EXP25-C09_NewGain，备注为“Expansion C09 appended gain”。",
    "另外向目标声音追加 Wwise Gain 效果器 Expansion_EXP25-C09_NewGain，备注为“Expansion C09 appended gain”。",
    "之后再向目标声音追加 Wwise Gain 效果器 Expansion_EXP25-C09_NewGain，备注为“Expansion C09 appended gain”。",
    "现在执行此次追加并核验。",
    "此次追加已取得 allow_changes 策略的独立授权。",
])
def test_restatement_and_current_operation_nouns_are_not_additional_appends(tail):
    case = copy.deepcopy(_DESIGN["fixture"])
    case["events"][1]["item"]["text"] += tail
    assert _grammatical_notice(case)


def test_after_a_neutral_read_then_append_is_one_plan():
    case = copy.deepcopy(_DESIGN["fixture"])
    case["events"][1]["item"]["text"] = case["events"][1]["item"]["text"].replace("即将追加", "之后再向目标声音追加")
    assert _grammatical_notice(case)


@pytest.mark.parametrize("separator", ["，", ",", "。", "；", ";", "\n"])
def test_unknown_local_clause_consumes_owner_before_a_later_omitted_owner_append(separator):
    case = copy.deepcopy(_DESIGN["fixture"])
    case["events"][1]["item"]["text"] = case["events"][1]["item"]["text"].replace("即将追加", "稍后再评估" + separator + "然后追加")
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("separator", ["，", ",", "。", "；", ";", "\n"])
def test_unknown_local_clause_does_not_replace_an_explicit_valid_append_owner(separator):
    case = copy.deepcopy(_DESIGN["fixture"])
    case["events"][1]["item"]["text"] = case["events"][1]["item"]["text"].replace("即将追加", "稍后再评估" + separator + "即将向目标声音追加")
    assert _grammatical_notice(case)


@pytest.mark.parametrize("prefix,suffix", [
    ("再一次向目标声音", ""),
    ("再向目标声音", "一遍"),
])
def test_explicit_repeat_count_order_cannot_add_another_approved_append(prefix, suffix):
    case = copy.deepcopy(_DESIGN["fixture"])
    case["events"][1]["item"]["text"] += prefix + "追加" + suffix + " Wwise Gain 效果器 Expansion_EXP25-C09_NewGain，备注为“Expansion C09 appended gain”。"
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("qualifier", ["不会", "可能会", "也许会", "不确定是否会"])
@pytest.mark.parametrize("separator", ["，", ",", "。", "；", "\n"])
def test_matching_refusal_or_uncertainty_cannot_hide_behind_a_consumed_owner_window(qualifier, separator):
    case = copy.deepcopy(_DESIGN["fixture"])
    case["events"][1]["item"]["text"] += ("已核对目标声音。稍后再评估" + separator + qualifier
        + "追加 Wwise Gain 效果器 Expansion_EXP25-C09_NewGain，备注为“Expansion C09 appended gain”。")
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("separator", ["，", "。"])
@pytest.mark.parametrize("owner,expected", [
    ("OtherSound", True), ("目标声音", False),
    ("目标声音和 OtherSound", False),
    ("{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}", False),
])
def test_only_a_complete_named_foreign_recipient_exempts_matching_negated_preservation(separator, owner, expected):
    case = copy.deepcopy(_DESIGN["fixture"])
    case["events"][1]["item"]["text"] += ("已核对目标声音。稍后再评估" + separator + "不会向 " + owner
        + " 追加 Wwise Gain 效果器 Expansion_EXP25-C09_NewGain，备注为“Expansion C09 appended gain”。")
    assert _grammatical_notice(case) is expected
