"""Exact baseline-purpose notice at the public grading seam."""
import copy
import json
import shlex
from pathlib import Path

from tests.semantic.test_codex_expansion_task_runner import _grammatical_notice

_CASES = json.loads((Path(__file__).parents[1] / "fixtures/semantic/expansion-baseline-purpose-a77c96a.json").read_text())["cases"]


def test_exact_baseline_purpose_notice():
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


def _without_purpose():
    case = copy.deepcopy(_CASES[0])
    post = next(e["item"] for e in case["events"] if "用于执行后比较" in e["item"].get("text", ""))
    post["text"] = post["text"].replace("用于执行后比较", "")
    return case, post


def test_verification_question_is_not_a_descriptor_copula():
    case, _ = _without_purpose()
    assert _grammatical_notice(case)


def test_actual_field_copula_is_not_exempted_as_a_question():
    case, post = _without_purpose()
    post["text"] = post["text"].replace("以及声音属性是否保持", "以及声音属性是12")
    assert not _grammatical_notice(case)


def test_verification_question_does_not_hide_adjacent_write():
    case, post = _without_purpose()
    post["text"] += "同时修改 Pitch 为12。"
    assert not _grammatical_notice(case)
