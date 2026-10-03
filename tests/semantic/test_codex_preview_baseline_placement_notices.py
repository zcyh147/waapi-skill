"""Exact Preview-baseline and owned-placement notice through public grading."""
import copy
import json
import shlex
from pathlib import Path

from tests.semantic.test_codex_expansion_task_runner import _grammatical_notice

_CASES = json.loads((Path(__file__).parents[1] / "fixtures/semantic/expansion-preview-baseline-placement-e49354a.json").read_text())["cases"]


def test_exact_preview_baseline_owned_placement_notice():
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


def test_preview_baseline_role_does_not_consume_adjacent_write():
    case = copy.deepcopy(_CASES[0])
    post = next(e["item"] for e in case["events"] if "预览已建立" in e["item"].get("text", ""))
    post["text"] = post["text"].replace("预览已建立修改前基线，", "预览已建立修改前基线，并修改 Pitch 为12，")
    assert not _grammatical_notice(case)


def test_owned_chain_placement_does_not_consume_adjacent_write():
    case = copy.deepcopy(_CASES[0])
    post = next(e["item"] for e in case["events"] if "预览已建立" in e["item"].get("text", ""))
    post["text"] = post["text"].replace("此次不设置", "同时清空另一对象。此次不设置")
    assert not _grammatical_notice(case)
