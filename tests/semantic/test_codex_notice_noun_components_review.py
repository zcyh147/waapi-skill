"""Independent, pre-repair contrasts at the existing public notice seam.

The vector judgments are frozen before noun-span production changes. Source
contexts are native evidence; substituted prose and damaged contexts are only
program controls and never native acceptance or historical regrading.
"""
import copy
import hashlib
import json
import shlex
from pathlib import Path

import pytest

from tests.semantic.test_codex_expansion_task_runner import _grammatical_notice


_SOURCE = Path(__file__).parents[1] / "fixtures/semantic/expansion-noun-span-notices-a7381ac.json"
_SOURCE_SHA256 = "d6936e44f7b44824805ffef84fd684594eb445c1892de841ec992770113f183c"
_CASES = json.loads(_SOURCE.read_text())["cases"]

# Independent positive/contradiction pairs; these are not a grammar inventory.
_VECTORS = (
    ("owner-identity-attribute", 0, "owner", "已核对目标声音身份。", True),
    ("owner-config-attribute", 0, "owner", "已核对目标声音的配置。", True),
    ("owner-foreign-attribute", 0, "owner", "已核对 OtherSound 身份。", False),
    ("owner-compound-attribute", 0, "owner", "已核对目标声音和 OtherSound 身份。", False),
    ("baseline-config-noun", 0, "owner", "已核对目标声音，并建立修改前的配置基线。", True),
    ("baseline-verification-basis", 0, "append", "执行后将对照基线核验原有效果器的身份与顺序。", True),
    ("baseline-extra-field-predicate", 0, "append", "并建立修改前的配置基线，并将目标声音的 Pitch 改为12。", False),
    ("baseline-extra-edit-same-clause", 0, "append", "并建立修改前的配置基线并修改 Pitch 为12。", False),
    ("grant-policy-modifier", 0, "append", "此次具体变更已取得 allow_changes 策略下的独立持久授权。", True),
    ("change-noun-preview-and-execution", 0, "execution", "这份具体变更的预览已生成。现在执行这份具体变更。", True),
    ("grant-wrong-policy", 0, "append", "此次具体变更已取得 read_only 策略下的独立持久授权。", False),
    ("grant-negative-polarity", 0, "append", "此次具体变更未取得 allow_changes 策略下的独立持久授权。", False),
    ("grant-other-beneficiary", 0, "append", "在 OtherSound 上，此次具体变更已取得 allow_changes 策略下的独立持久授权。", False),
    ("change-noun-refusal", 0, "execution", "不会执行这份具体变更。", False),
    ("append-owned-chain", 1, "placement", "将在目标声音的效果链末尾追加", True),
    ("append-after-two-existing", 0, "placement", "将于现有两个效果器之后追加", True),
    ("append-foreign-chain", 1, "placement", "将在 OtherSound 的效果链末尾追加", False),
    ("append-before-existing", 0, "placement", "将于现有两个效果器之前追加", False),
    ("append-wrong-existing-count", 0, "placement", "将于现有三个效果器之后追加", False),
    ("reference-parent-qualified-source", 2, "reference-source", "Stealth 中目标 Stinger", True),
    ("reference-foreign-parent", 2, "reference-source", "OtherPlaylist 中目标 Stinger", False),
    ("reference-compound-parent", 2, "reference-source", "Stealth 和 OtherPlaylist 中目标 Stinger", False),
    ("reference-wrong-old-value", 2, "reference-old", "OtherBonus", False),
    ("reference-wrong-new-value", 2, "reference-new", "Bonus", False),
    ("reference-duplicate-membership", 2, "membership", "duplicate", False),
    ("reference-missing-membership", 2, "membership", "missing", False),
    ("reference-foreign-membership", 2, "membership", "foreign", False),
    ("reference-refused-execution", 2, "execution", "不会执行这一项引用变更。", False),
)


def _case(index):
    assert hashlib.sha256(_SOURCE.read_bytes()).hexdigest() == _SOURCE_SHA256
    case = copy.deepcopy(_CASES[index])
    for proof in case["source"]["phases"]:
        outer = shlex.split(proof["raw_command"])
        assert outer[:2] == ["/bin/bash", "-lc"]
        argv = shlex.split(outer[-1])
        assert argv[argv.index("gateway.py") + 1] == proof["phase"]
        assert sum(event["item"].get("command") == proof["phase"] for event in case["events"]) == 1
    if index < 2:
        descriptor = case["artifact"]["request"]["arguments"]["plugin"]
        text = ("已核对目标声音。即将追加 Wwise Gain 效果器 " + descriptor["name"]
                + "，备注为“" + descriptor["notes"] + "”。现在执行。")
        assert len(case["before"]["entries"]) == 2
    else:
        assert case["before"]["owner"]["name"] == "Stealth"
        assert case["before"]["stinger"]["@Trigger"]["name"] == "Bonus"
        assert case["before"]["target"]["name"] == "Backup_Team_Arrives"
        text = ("预览已完成：唯一写入项是将目标 Stinger 的触发器从 Bonus 改为 "
                "Backup_Team_Arrives。现在执行。")
    preview = next(i for i, event in enumerate(case["events"])
                   if event["item"].get("command") == "preview-from-draft")
    post = next(event["item"] for event in case["events"][preview + 1:]
                if event["item"]["type"] == "agent_message")
    post["text"] = text
    return case, post


@pytest.mark.parametrize("index", [0, 1, 2])
def test_independent_component_context_has_a_complete_supported_primary_effect(index):
    case, _ = _case(index)
    assert _grammatical_notice(case)


@pytest.mark.parametrize("vector", _VECTORS, ids=lambda row: row[0])
def test_frozen_independent_noun_component_contrasts(vector):
    _, index, component, value, expected = vector
    case, post = _case(index)
    if component == "owner":
        post["text"] = post["text"].replace("已核对目标声音。", value)
    elif component == "append":
        post["text"] += value
    elif component == "execution":
        post["text"] = post["text"].replace("现在执行。", value)
    elif component == "placement":
        post["text"] = post["text"].replace("即将追加", value)
    elif component == "reference-source":
        post["text"] = post["text"].replace("目标 Stinger", value)
    elif component == "reference-old":
        post["text"] = post["text"].replace("从 Bonus 改为", "从 " + value + " 改为")
    elif component == "reference-new":
        post["text"] = post["text"].replace("Backup_Team_Arrives", value)
    else:
        members = case["before"]["owner"]["@Stingers"]
        if value == "duplicate":
            members.append(copy.deepcopy(members[0]))
        elif value == "missing":
            members.clear()
        else:
            members[0]["id"] = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
    assert _grammatical_notice(case) is expected
