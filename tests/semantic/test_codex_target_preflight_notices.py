"""Exact target/preflight notice at the public grading seam."""
import copy
import json
import shlex
from pathlib import Path

from tests.semantic.test_codex_expansion_task_runner import _grammatical_notice

_CASES = json.loads((Path(__file__).parents[1] / "fixtures/semantic/expansion-target-preflight-595cc85.json").read_text())["cases"]


def test_exact_target_preflight_notice():
    case = copy.deepcopy(_CASES[0])
    assert [proof["phase"] for proof in case["source"]["phases"]] == ["preview-from-draft", "execute"]
    assert [proof["event_index"] for proof in case["source"]["phases"]] == [22, 24]
    for proof in case["source"]["phases"]:
        outer = shlex.split(proof["raw_command"])
        assert outer[:2] == ["/bin/bash", "-lc"]
        argv = shlex.split(outer[-1])
        assert argv[argv.index("gateway.py") + 1] == proof["phase"]
        assert sum(e["item"].get("command") == proof["phase"] for e in case["events"]) == 1
    assert _grammatical_notice(case)


def test_preflight_baseline_cannot_carry_foreign_subject_to_creation():
    case = copy.deepcopy(_CASES[0])
    post = next(e["item"] for e in case["events"] if "预检已保存" in e["item"].get("text", ""))
    post["text"] = post["text"].replace("预检已保存修改前状态", "预检已保存 OtherSound 的修改前状态")
    assert not _grammatical_notice(case)


def test_preflight_baseline_cannot_hide_adjacent_mutation():
    case = copy.deepcopy(_CASES[0])
    post = next(e["item"] for e in case["events"] if "预检已保存" in e["item"].get("text", ""))
    post["text"] = post["text"].replace("预检已保存修改前状态", "预检已保存修改前状态，并修改 Pitch 为12")
    assert not _grammatical_notice(case)


def test_preflight_baseline_does_not_establish_primary_owner():
    case = copy.deepcopy(_CASES[0])
    post = next(e["item"] for e in case["events"] if "预检已保存" in e["item"].get("text", ""))
    post["text"] = post["text"].replace("已确认目标为指定声音，并匹配到 Wwise Gain。", "已匹配到 Wwise Gain。")
    assert not _grammatical_notice(case)
