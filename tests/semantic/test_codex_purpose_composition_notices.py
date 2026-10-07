"""Frozen #147 purpose/ordinal contrasts at the prospective-notice seam."""

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.semantic.support.codex_task_runner_v3 import expansion_preview_notice


_ROOT = Path(__file__).parents[1] / "fixtures/semantic"
_MATRIX = _ROOT / "expansion-purpose-independent-20261007.json"
_FIXTURE = _ROOT / "expansion-purpose-fixture-0b6af50-20261007.json"
_CASES = json.loads(_MATRIX.read_text())["cases"]


def _notice(text, event_edit=None):
    case = json.loads(_FIXTURE.read_text())
    events = copy.deepcopy(case["events"])
    events[1]["item"]["text"] = text
    if event_edit == "swap notice with Execute start":
        events[1], events[2] = events[2], events[1]
    elif event_edit == "insert second Preview completion after notice and before Execute start":
        events.insert(2, copy.deepcopy(events[0]))
    else:
        assert event_edit is None
    records = [SimpleNamespace(command=phase, argv=("python", "/tmp/skill/scripts/run.py", "gateway.py", phase, "x"))
               for phase in ("preview-from-draft", "execute")]
    return expansion_preview_notice(
        SimpleNamespace(stdout="\n".join(json.dumps(event) for event in events)),
        records, version=case["artifact"]["request"]["version"], execute_expected=True,
        preview_artifact=case["artifact"], before_snapshot=case["before"])


def test_exact_449_byte_notice_precedes_execute_start():
    assert hashlib.sha256(_FIXTURE.read_bytes()).hexdigest() == "1ddfe39754f4ee50fae43817c39641b064dde7f1d4e0a6f27e7fea7df0e33ee1"
    case = json.loads(_FIXTURE.read_text())
    assert [event["type"] for event in case["events"]] == ["item.completed", "item.completed", "item.started"]
    assert case["events"][0]["item"]["command"] == "preview-from-draft"
    assert case["events"][2]["item"]["command"] == "execute"
    text = case["events"][1]["item"]["text"]
    assert len(text.encode()) == 449
    assert hashlib.sha256(text.encode()).hexdigest() == "fd50b3a320b430737779dea45eb5bac6a8d38d482abddb8a7562a5c8d8de58ec"
    assert _notice(text)


@pytest.mark.parametrize("vector", _CASES, ids=[vector["id"] for vector in _CASES])
def test_frozen_independent_purpose_and_ordinal_compositions(vector):
    assert hashlib.sha256(_MATRIX.read_bytes()).hexdigest() == "19a734704545f162b0450d50be691a8914e233a00cf3f89987ac4347fafe5b44"
    assert _notice(vector["text"], vector.get("event_edit")) is vector["expected"], vector["criterion"]


@pytest.mark.parametrize("coordinator", ["", "并", "并且", "且", "同时", "另外"])
@pytest.mark.parametrize("qualifier,expected", [("第二次", False), ("再", True), ("另外", True)])
def test_coordinators_preserve_explicit_second_write_and_bare_restatement(coordinator, qualifier, expected):
    text = _CASES[19]["text"].replace("再追加 Wwise Gain", coordinator + qualifier + "追加 Wwise Gain")
    assert _notice(text) is expected


@pytest.mark.parametrize("producer", ["并记录修改前状态", "修改前状态已保存", "预检已建立修改前状态"])
@pytest.mark.parametrize("purpose", ["用于保持性比较", "供执行后保持性核验", "以便后续保持性验证",
                                     "用于随后保持性验收", "供保持性检查"])
def test_complete_baseline_producers_compose_bounded_preservation_read_purpose(producer, purpose):
    text = _CASES[0]["text"].replace("并记录修改前状态用于保持性核验", producer + purpose)
    assert _notice(text)


@pytest.mark.parametrize("replacement", [
    "并修改音量用于保持性核验",
    "并记录修改前状态并修改音量用于保持性核验",
    "并记录修改前状态用于保持性核验并修改音量",
    "并记录修改前状态用于保持性核验并清空另一对象",
    "并记录修改前状态用于保持性修改音量",
    "并记录修改前状态用于保持性核验并第二次追加效果器",
])
def test_complete_read_purpose_never_hides_a_residual_write(replacement):
    text = _CASES[0]["text"].replace("并记录修改前状态用于保持性核验", replacement)
    assert not _notice(text)


@pytest.mark.parametrize("edit", [
    ("Expansion_EXP25-C09_NewGain", "WrongEffect"),
    ("Expansion C09 appended gain", "Wrong notes"),
    ("已核对目标声音身份", "已核对其他声音身份"),
    ("将追加 Wwise Gain", "可能追加 Wwise Gain"),
    ("将追加 Wwise Gain", "不会追加 Wwise Gain"),
    ("allow_changes", "read_only"),
])
def test_preservation_purpose_keeps_owner_descriptor_polarity_and_policy_checks(edit):
    assert not _notice(_CASES[0]["text"].replace(*edit))


@pytest.mark.parametrize("qualifier,suffix", [("第2次", ""), ("再一次", ""), ("再", "一次 ")])
def test_coordinator_keeps_other_explicit_repeat_forms(qualifier, suffix):
    text = _CASES[19]["text"].replace("再追加 Wwise Gain", "同时" + qualifier + "追加 " + suffix + "Wwise Gain")
    assert not _notice(text)
