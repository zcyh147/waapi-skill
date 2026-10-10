"""Frozen full-campaign witnesses at the existing public notice seam."""
import copy
import json
import shlex
from pathlib import Path

import pytest

from tests.semantic.test_codex_expansion_task_runner import _grammatical_notice


_CASES = json.loads((Path(__file__).parents[1] / "fixtures/semantic/expansion-composed-notices-87f9dc8.json").read_text())["cases"]


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case["case"])
def test_actual_full87_notice_describes_the_exact_prepared_effect(case):
    for proof in case["source"]["phases"]:
        outer = shlex.split(proof["raw_command"])
        argv = shlex.split(outer[-1]) if outer[:2] == ["/bin/bash", "-lc"] else outer
        assert argv[argv.index("gateway.py") + 1] == proof["phase"]
    assert _grammatical_notice(copy.deepcopy(case))


@pytest.mark.parametrize("owner", ["目标声音已绑定", "目标声音已核对", "已核对目标声音"])
@pytest.mark.parametrize("display", ["Wwise Gain 类型已从实时目录确认", "已从实时插件目录确认 Wwise Gain", "并匹配到 Wwise Gain"])
@pytest.mark.parametrize("baseline", ["修改前状态已记录", "并记录修改前状态"])
def test_owner_display_and_baseline_roles_compose_independently(owner, display, baseline):
    case = copy.deepcopy(_CASES[0])
    case["events"][-2]["item"]["text"] = case["events"][-2]["item"]["text"].replace(
        "目标声音已绑定，Wwise Gain 类型已从实时目录确认，修改前状态已记录", f"{owner}，{display}，{baseline}")
    assert _grammatical_notice(case)


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case["case"])
@pytest.mark.parametrize("claim,expected", [
    ("不会修改其他对象。", True), ("当前策略为 read_only。", False),
    ("我不会执行该预览。", False), ("同时修改 Pitch 为12。", False),
    ("目标是 OtherOwner。", False),
])
def test_composed_roles_preserve_exclusions_and_reject_remaining_contradictions(case, claim, expected):
    case = copy.deepcopy(case)
    case["events"][-2]["item"]["text"] += claim
    assert _grammatical_notice(case) is expected


@pytest.mark.parametrize("scope", ["本次写入范围只包含此条曲线", "此次写入仅涉及这一条曲线"])
def test_one_curve_write_scope_is_ancillary_only(scope):
    case = copy.deepcopy(_CASES[1])
    case["events"][-2]["item"]["text"] = case["events"][-2]["item"]["text"].replace("此次写入仅涉及这一条曲线", scope)
    assert _grammatical_notice(case)
    case["events"][-2]["item"]["text"] = scope + "。现在执行。"
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("damage", ["before", "foreign_placement", "wrong_kind", "extra_target", "wrong_owner", "ambiguous_owner"])
def test_operation_modifiers_cannot_change_prepared_owner_kind_placement_or_scope(damage):
    case = copy.deepcopy(_CASES[2] if damage in {"before", "foreign_placement", "wrong_kind"} else _CASES[1] if damage == "extra_target" else _CASES[0])
    text = case["events"][-2]["item"]["text"]
    old, new = {
        "before": ("现有效果器之后", "现有效果器之前"),
        "foreign_placement": ("现有效果器之后", "OtherSound 的效果器之后"),
        "wrong_kind": ("类型为 Wwise Gain", "类型为 Sound"),
        "extra_target": ("这一条曲线", "这一条曲线和另一条曲线"),
        "wrong_owner": ("目标声音已绑定", "OtherSound 已绑定"),
        "ambiguous_owner": ("目标声音已绑定", "目标声音和 OtherSound 已绑定"),
    }[damage]
    case["events"][-2]["item"]["text"] = text.replace(old, new)
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("extra", ["并清空 Pitch", "且修改 Segment", "同时删除 OtherObject"])
def test_negative_scope_cannot_hide_a_coordinated_affirmative_mutation(extra):
    case = copy.deepcopy(_CASES[-1])
    case["events"][-2]["item"]["text"] = case["events"][-2]["item"]["text"].replace("其他设置的修改", "其他设置的修改" + extra)
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("join", ["并", "且", "同时", "，", "。"])
@pytest.mark.parametrize("predicate", ["将关联音乐段的 NumSegmentAdvance 改为 2", "将该 Stinger 的 NumSegmentAdvance 改为 2", "清空 Pitch"])
def test_scope_negation_does_not_cross_a_coordinated_subject_and_field(join, predicate):
    case = copy.deepcopy(_CASES[-1])
    case["events"][-2]["item"]["text"] = case["events"][-2]["item"]["text"].replace("其他设置的修改", "其他设置的修改" + join + predicate)
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("field", ["音量为12", "Pitch 为12", "volume = 12", "Probability 是12"])
def test_closed_effect_descriptor_cannot_gain_an_adjacent_unapproved_property(field):
    case = copy.deepcopy(_CASES[2])
    case["events"][-2]["item"]["text"] = case["events"][-2]["item"]["text"].replace("gain”；", "gain”，" + field + "；")
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("join", ["并", "，", "。"])
@pytest.mark.parametrize("predicate", ["不将关联音乐段的 NumSegmentAdvance 改为 2", "不会清空 Pitch"])
def test_each_negative_predicate_preserves_unrelated_protected_fields(join, predicate):
    case = copy.deepcopy(_CASES[-1])
    case["events"][-2]["item"]["text"] = case["events"][-2]["item"]["text"].replace("其他设置的修改", "其他设置的修改" + join + predicate)
    assert _grammatical_notice(case)


@pytest.mark.parametrize("claim", ["不会修改音量为12。", "核验会检查音量与备注的保持情况。", "目前尚未修改工程。"])
def test_descriptor_value_validation_does_not_invent_an_edit_from_preservation_or_read_status(claim):
    case = copy.deepcopy(_CASES[2])
    case["events"][-2]["item"]["text"] += claim
    assert _grammatical_notice(case)


@pytest.mark.parametrize("prefix", ["不会同时", "不会另外", "不同时", "不另外", "不会并"])
def test_a_coordinating_adverb_does_not_drop_its_governing_negation(prefix):
    case = copy.deepcopy(_CASES[2])
    case["events"][-2]["item"]["text"] += prefix + "修改 Pitch。"
    assert _grammatical_notice(case)


@pytest.mark.parametrize("join", ["并", "同时", "另外"])
def test_a_second_predicate_does_not_borrow_the_first_predicates_negation(join):
    case = copy.deepcopy(_CASES[2])
    case["events"][-2]["item"]["text"] += "不会修改 Pitch" + join + "修改 Lowpass 为12。"
    assert not _grammatical_notice(case)
