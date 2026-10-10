"""Pre-repair judgments for Preview baseline and owned append components.

Prose substitutions are program controls, not native acceptance or regrading.
"""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from tests.semantic.test_codex_expansion_task_runner import _grammatical_notice

_SOURCE = Path(__file__).parents[1] / "fixtures/semantic/expansion-preview-baseline-placement-e49354a.json"
_SOURCE_SHA256 = "0e9d97cd7881cffd04b8612197d1a79abf840985c21021880e6189f4f27bf8ad"
_VECTORS = (
    ("preview-baseline-authorization", "prefix", "预览已建立修改前基线，并取得 allow_changes 策略的独立授权；目前尚未修改。", True),
    ("owned-after-shorthand", "placement", "即将在目标声音的现有效果器后追加", True),
    ("preview-wrong-policy", "prefix", "预览已建立修改前基线，并取得 read_only 策略的独立授权。", False),
    ("preview-refused-authorization", "prefix", "预览已建立修改前基线，并未取得 allow_changes 策略的独立授权。", False),
    ("foreign-after-owner", "placement", "即将在 OtherSound 的现有效果器后追加", False),
    ("compound-after-owner", "placement", "即将在目标声音和 OtherSound 的现有效果器后追加", False),
    ("before-existing", "placement", "即将在目标声音的现有效果器前追加", False),
    ("replace-existing", "placement", "即将在目标声音上替换现有效果器为", False),
    ("contradictory-name", "append", "即将追加 Wwise Gain 效果器 OtherGain，备注为“Expansion C09 appended gain”。", False),
    ("contradictory-notes", "append", "即将追加 Wwise Gain 效果器 Expansion_EXP25-C09_NewGain，备注为“Other notes”。", False),
    ("contradictory-native-kind", "append", "新增项是 Sound：Expansion_EXP25-C09_NewGain，备注为“Expansion C09 appended gain”。", False),
    ("baseline-extra-edit", "prefix", "预览已建立修改前基线，并取得 allow_changes 策略的独立授权，并修改 Pitch 为12。", False),
)


def _control():
    assert hashlib.sha256(_SOURCE.read_bytes()).hexdigest() == _SOURCE_SHA256
    case = copy.deepcopy(json.loads(_SOURCE.read_text())["cases"][0])
    descriptor = case["artifact"]["request"]["arguments"]["plugin"]
    assert descriptor["name"] == "Expansion_EXP25-C09_NewGain"
    assert descriptor["notes"] == "Expansion C09 appended gain"
    assert len(case["before"]["entries"]) == 2
    preview = next(i for i, event in enumerate(case["events"])
                   if event["item"].get("command") == "preview-from-draft")
    post = next(event["item"] for event in case["events"][preview + 1:]
                if event["item"]["type"] == "agent_message")
    post["text"] = ("已核对目标声音。即将追加 Wwise Gain 效果器 " + descriptor["name"]
                    + "，备注为“" + descriptor["notes"] + "”。现在执行。")
    return case, post


def test_preview_component_control_has_a_complete_primary_effect():
    case, _ = _control()
    assert _grammatical_notice(case)


@pytest.mark.parametrize("vector", _VECTORS, ids=lambda row: row[0])
def test_frozen_preview_component_contrasts(vector):
    _, component, value, expected = vector
    case, post = _control()
    if component == "prefix":
        post["text"] = value + post["text"]
    elif component == "placement":
        post["text"] = post["text"].replace("即将追加", value)
    else:
        post["text"] += value
    assert _grammatical_notice(case) is expected
