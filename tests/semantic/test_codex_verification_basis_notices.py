"""Current-change authorization and before-state verification at notice seam."""
import copy
import json
import shlex
from pathlib import Path

import pytest

from tests.semantic.test_codex_expansion_task_runner import _grammatical_notice

_CASE = json.loads((Path(__file__).parents[1] / "fixtures/semantic/expansion-verification-basis-notice-0e04c8c.json").read_text())["case"]


def test_exact_current_change_and_before_state_notice():
    case = copy.deepcopy(_CASE)
    for proof in case["source"]["phases"]:
        outer = shlex.split(proof["raw_command"])
        assert outer[:2] == ["/bin/bash", "-lc"]
        argv = shlex.split(outer[-1])
        assert argv[argv.index("gateway.py") + 1] == proof["phase"]
        assert sum(e["item"].get("command") == proof["phase"] for e in case["events"]) == 1
    assert _grammatical_notice(case)


def _notice(case):
    preview = next(i for i, event in enumerate(case["events"]) if event["item"].get("command") == "preview-from-draft")
    return next(event["item"] for event in case["events"][preview + 1:] if event["item"]["type"] == "agent_message")


@pytest.mark.parametrize("referent", ["本次", "此次"])
@pytest.mark.parametrize("basis", ["修改前状态", "执行前基线"])
@pytest.mark.parametrize("verb", ["对照", "依据"])
def test_current_change_and_verification_basis_components_compose(referent, basis, verb):
    case = copy.deepcopy(_CASE)
    item = _notice(case)
    item["text"] = item["text"].replace("本次具体修改", referent + "具体修改").replace("对照修改前状态", verb + basis)
    assert _grammatical_notice(case)


@pytest.mark.parametrize("old,new", [
    ("本次具体修改已取得 allow_changes", "本次具体修改已取得 read_only"),
    ("本次具体修改已取得", "本次具体修改未取得"),
    ("本次具体修改已取得", "本次具体修改可能取得"),
    ("本次具体修改已取得", "在 OtherSound 上，本次具体修改已取得"),
    ("已核对目标声音", "已核对目标声音和 OtherSound"),
    ("即将追加 Wwise Gain 效果器", "即将追加 Sound"),
    ("执行后会对照修改前状态核验", "同时修改 Pitch 为12。执行后会对照修改前状态核验"),
    ("对照修改前状态核验", "对照修改前状态并修改 Pitch 为12再核验"),
    ("核验原有效果器的身份", "核验原有效果器的身份并修改 Pitch 为12"),
    ("执行后会对照修改前状态核验", "在 OtherSound 上执行后会对照修改前状态核验"),
    ("执行后会对照修改前状态核验", "执行后会对照 OtherSound 的修改前状态核验"),
    ("本次具体修改已取得 allow_changes 策略的独立持久授权", "本次具体修改已取得 allow_changes 策略的独立持久授权，当前策略为 read_only"),
])
def test_ancillary_spans_do_not_hide_foreign_policy_or_real_edits(old, new):
    case = copy.deepcopy(_CASE)
    item = _notice(case)
    assert old in item["text"]
    item["text"] = item["text"].replace(old, new)
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("claim", ["我不会执行该变更。", "目标是 OtherSound。", "同时删除原效果。"])
def test_later_contradictions_remain_visible(claim):
    case = copy.deepcopy(_CASE)
    _notice(case)["text"] += claim
    assert not _grammatical_notice(case)


def test_authorization_and_verification_intent_do_not_supply_primary_effect():
    case = copy.deepcopy(_CASE)
    _notice(case)["text"] = ("本次具体修改已取得 allow_changes 策略的独立持久授权。"
        "执行后会对照修改前状态核验原有效果器的身份。现在执行。")
    assert not _grammatical_notice(case)
