"""Independent, pre-repair read-only baseline-purpose contrasts."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from tests.semantic.test_codex_expansion_task_runner import _grammatical_notice

_SOURCE = Path(__file__).parents[1] / "fixtures/semantic/expansion-baseline-purpose-a77c96a.json"
_SOURCE_SHA256 = "c50ccd4910953dbe82f0838a79f457a15b3629aa28f98b3cabab088eb455bfdb"
_VECTORS = (
    ("purpose-post-execution-compare", "已核对目标声音，并保存修改前状态用于执行后比较。", True),
    ("purpose-later-verification", "已核对目标声音，并建立修改前的配置基线供后续核验。", True),
    ("purpose-comparison-without-time", "已核对目标声音，并记录修改前状态以便比较。", True),
    ("purpose-use-without-time", "已核对目标声音，并保存修改前状态用于比较。", True),
    ("purpose-is-mutation", "已核对目标声音，并保存修改前状态用于修改 Pitch 为12。", False),
    ("purpose-foreign-subject", "已核对目标声音，并保存 OtherSound 的修改前状态用于比较。", False),
    ("purpose-extra-action-within", "已核对目标声音，并保存修改前状态用于比较并清空另一对象。", False),
    ("purpose-extra-action-after", "已核对目标声音，并保存修改前状态用于比较，同时修改 Pitch 为12。", False),
    ("purpose-unapproved-field-tail", "已核对目标声音，并保存修改前状态用于比较，Pitch 将改为12。", False),
    ("purpose-wrong-notes-tail", "已核对目标声音，并保存修改前状态用于比较。新增效果器的备注为“Other notes”。", False),
    ("purpose-wrong-policy", "已核对目标声音，并保存修改前状态用于比较。该变更已取得 read_only 策略的独立授权。", False),
    ("purpose-execution-refusal", "已核对目标声音，并保存修改前状态用于比较。不会执行追加。", False),
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


def test_baseline_purpose_control_has_a_complete_primary_effect():
    case, _ = _control()
    assert _grammatical_notice(case)


@pytest.mark.parametrize("vector", _VECTORS, ids=lambda row: row[0])
def test_frozen_baseline_purpose_component_contrasts(vector):
    _, prefix, expected = vector
    case, post = _control()
    post["text"] = prefix + post["text"]
    assert _grammatical_notice(case) is expected
