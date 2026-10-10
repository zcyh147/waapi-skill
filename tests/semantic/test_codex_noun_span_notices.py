"""Raw noun-component witnesses at the existing public notice seam."""
import copy
import json
import shlex
from pathlib import Path

import pytest

from tests.semantic.test_codex_expansion_task_runner import _grammatical_notice

_CASES = json.loads((Path(__file__).parents[1] / "fixtures/semantic/expansion-noun-span-notices-a7381ac.json").read_text())["cases"]


@pytest.mark.parametrize("case", _CASES, ids=lambda row: row["case"])
def test_exact_noun_span_notice(case):
    case = copy.deepcopy(case)
    for proof in case["source"]["phases"]:
        outer = shlex.split(proof["raw_command"])
        assert outer[:2] == ["/bin/bash", "-lc"]
        argv = shlex.split(outer[-1])
        assert argv[argv.index("gateway.py") + 1] == proof["phase"]
        assert sum(e["item"].get("command") == proof["phase"] for e in case["events"]) == 1
    assert _grammatical_notice(case)


def _post(case):
    preview = next(i for i, event in enumerate(case["events"]) if event["item"].get("command") == "preview-from-draft")
    return next(event["item"] for event in case["events"][preview + 1:] if event["item"]["type"] == "agent_message")


@pytest.mark.parametrize("index,claim", [
    (0, "并建立修改前的配置基线，并修改 Pitch 为12。"),
    (0, "现在执行这一个引用变更。"),
    (0, "不会执行这一个引用变更。"),
    (1, "具体变更预览已取得 read_only 策略下的授权。"),
    (2, "网关未依据 allow_changes 策略授权。"),
    (2, "网关已依据 read_only 策略授权。"),
    (2, "同时把 NumSegmentAdvance 改为2。"),
    (2, "关联音乐段保持为 OtherSegment。"),
])
def test_composed_nouns_leave_wrong_context_and_extra_claims_visible(index, claim):
    case = copy.deepcopy(_CASES[index])
    _post(case)["text"] += claim
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("damage", ["empty_subject", "missing_parent_id", "wrong_parent_type", "missing_old_id"])
def test_parent_reference_assignment_requires_nonempty_typed_independent_roles(damage):
    case = copy.deepcopy(_CASES[2])
    if damage == "empty_subject":
        _post(case)["text"] = _post(case)["text"].replace("Stealth 中目标 Stinger", " ")
    elif damage == "missing_parent_id":
        case["before"]["owner"].pop("id")
    elif damage == "wrong_parent_type":
        case["before"]["owner"]["type"] = "Sound"
    else:
        case["before"]["stinger"]["@Trigger"].pop("id")
        case["artifact"]["prepared_operation"]["pre_state"]["field_before"]["value"].pop("id")
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("role", ["parent", "old", "segment"])
def test_attested_reference_role_accepts_exact_guid_only_in_its_owned_span(role):
    case = copy.deepcopy(_CASES[2])
    if role == "parent":
        old, new = "Stealth 中目标 Stinger", case["before"]["owner"]["id"] + " 中目标 Stinger"
    elif role == "old":
        old, new = "从 Bonus 改为", "从 " + case["before"]["stinger"]["@Trigger"]["id"] + " 改为"
    else:
        old, new = "关联音乐段保持为 Stinger Bonus", "关联音乐段保持为 " + case["before"]["segment"]["id"]
    _post(case)["text"] = _post(case)["text"].replace(old, new)
    assert _grammatical_notice(case)


@pytest.mark.parametrize("role", ["parent", "old", "segment"])
@pytest.mark.parametrize("placement", ["unscoped", "foreign"])
def test_reference_role_guid_does_not_authorize_unscoped_or_foreign_identity(role, placement):
    case = copy.deepcopy(_CASES[2])
    identity = {"parent": case["before"]["owner"], "old": case["before"]["stinger"]["@Trigger"],
                "segment": case["before"]["segment"]}[role]["id"]
    if placement == "unscoped":
        _post(case)["text"] += "已记录 " + identity + "。"
    else:
        foreign = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
        replacements = {"parent": ("Stealth 中目标 Stinger", foreign + " 中目标 Stinger"),
                        "old": ("从 Bonus 改为", "从 " + foreign + " 改为"),
                        "segment": ("关联音乐段保持为 Stinger Bonus", "关联音乐段保持为 " + foreign)}
        old, new = replacements[role]
        _post(case)["text"] = _post(case)["text"].replace(old, new)
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("identity", [None, "not-a-guid"])
def test_segment_preservation_requires_canonical_independent_identity(identity):
    case = copy.deepcopy(_CASES[2])
    for row in (case["before"]["segment"], case["before"]["stinger"]["@Segment"]):
        if identity is None:
            row.pop("id")
        else:
            row["id"] = identity
    assert not _grammatical_notice(case)
