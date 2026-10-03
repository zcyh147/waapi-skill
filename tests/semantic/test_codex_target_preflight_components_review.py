"""Independent pre-repair target-copula and before-state producer contrasts."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from tests.semantic.test_codex_expansion_task_runner import _grammatical_notice

_SOURCE = Path(__file__).parents[1] / "fixtures/semantic/expansion-target-preflight-595cc85.json"
_SOURCE_SHA256 = "a24d1fb38ace6741331e3ee92612c0ed504c449110d9b824731eef0744f44a81"
_VECTORS = (
    ("target-copula-for-role", "target", "已确认目标为指定声音。", True),
    ("target-copula-is-role", "target", "已确认目标是指定声音。", True),
    ("target-copula-exact-guid", "guid", "已确认目标为 {id}。", True),
    ("target-foreign", "target", "已确认目标为 OtherSound。", False),
    ("target-compound", "target", "已确认目标为指定声音和 OtherSound。", False),
    ("target-refused", "target", "未确认目标为指定声音。", False),
    ("target-wrong-native-role", "target", "已确认目标为指定衰减对象。", False),
    ("preflight-before-state", "prefix", "预检已保存修改前状态。", True),
    ("preview-before-baseline", "prefix", "预览已建立修改前基线。", True),
    ("producer-wrong-policy", "prefix", "预检已保存修改前状态，并取得 read_only 策略的独立授权。", False),
    ("producer-refused-authorization", "prefix", "预检已保存修改前状态，并未取得 allow_changes 策略的独立授权。", False),
    ("producer-adjacent-extra-edit", "prefix", "预检已保存修改前状态，并修改 Pitch 为12。", False),
)


def _control():
    assert hashlib.sha256(_SOURCE.read_bytes()).hexdigest() == _SOURCE_SHA256
    case = copy.deepcopy(json.loads(_SOURCE.read_text())["cases"][0])
    descriptor = case["artifact"]["request"]["arguments"]["plugin"]
    preview = next(i for i, event in enumerate(case["events"])
                   if event["item"].get("command") == "preview-from-draft")
    post = next(event["item"] for event in case["events"][preview + 1:]
                if event["item"]["type"] == "agent_message")
    post["text"] = ("已核对目标声音。即将追加 Wwise Gain 效果器 " + descriptor["name"]
                    + "，备注为“" + descriptor["notes"] + "”。现在执行。")
    return case, post


def test_target_preflight_control_has_a_complete_primary_effect():
    case, _ = _control()
    assert _grammatical_notice(case)


@pytest.mark.parametrize("vector", _VECTORS, ids=lambda row: row[0])
def test_frozen_target_preflight_component_contrasts(vector):
    _, component, value, expected = vector
    case, post = _control()
    if component == "guid":
        value = value.replace("{id}", case["before"]["owner"]["id"])
    if component in {"target", "guid"}:
        post["text"] = post["text"].replace("已核对目标声音。", value)
    else:
        post["text"] = value + post["text"]
    assert _grammatical_notice(case) is expected
