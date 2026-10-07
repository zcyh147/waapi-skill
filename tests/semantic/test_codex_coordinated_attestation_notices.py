"""Coordinated read attestation at the agreed public notice-grading seam."""
import copy
import hashlib
import json
import shlex
from pathlib import Path

import pytest

from tests.semantic.test_codex_expansion_task_runner import _grammatical_notice

_CASES = json.loads((Path(__file__).parents[1] / "fixtures/semantic/expansion-coordinated-attestation-0c2e75e.json").read_text())["cases"]


def test_exact_coordinated_owner_and_type_attestation_notice():
    case = copy.deepcopy(_CASES[0])
    source = case["source"]
    assert source["notice_event_index"] == 23
    assert case["events"][2] == source["notice_event"]
    assert [proof["event_index"] for proof in source["phases"]] == [22, 24]
    for proof in source["phases"]:
        outer = shlex.split(proof["raw_command"])
        assert outer[:2] == ["/bin/bash", "-lc"]
        argv = shlex.split(outer[-1])
        assert argv[argv.index("gateway.py") + 1] == proof["phase"]
        assert sum(event["item"].get("command") == proof["phase"] for event in case["events"]) == 1
    assert _grammatical_notice(case)


_INDEPENDENT = Path(__file__).parents[1] / "fixtures/semantic/expansion-coordinated-attestation-independent-20261007.json"
_DESIGN = json.loads(_INDEPENDENT.read_text())


@pytest.mark.parametrize("vector", _DESIGN["vectors"], ids=lambda row: row["id"])
def test_independent_coordinated_attestation_contrasts(vector):
    assert hashlib.sha256(_INDEPENDENT.read_bytes()).hexdigest() == "67ec04ea10f5aacad588dc28b1ace2fdbc6363d6339e8c3a27c408abf4339bb8"
    case = copy.deepcopy(_DESIGN["fixture"])
    case["events"][case["replacement_event_index"]]["item"]["text"] = vector["notice"]
    assert _grammatical_notice(case) is vector["expected"], vector["reason"]


@pytest.mark.parametrize("recipient", ["", "向目标声音"])
@pytest.mark.parametrize("qualifier,expected", [
    ("将", True), ("即将", True), ("会", True),
    ("可能", False), ("可能会", False), ("也许会", False),
    ("或许将", False), ("不确定是否会", False),
])
def test_local_append_certainty_cannot_be_supplied_by_later_generic_execution(recipient, qualifier, expected):
    case = copy.deepcopy(_CASES[0])
    post = case["events"][2]["item"]
    post["text"] = post["text"].replace("。将追加", "。" + qualifier + recipient + "追加")
    assert _grammatical_notice(case) is expected


@pytest.mark.parametrize("operands", [
    "目标声音身份、实时 Sound 类型",
    "目标声音身份、实时 ActorMixer 类型",
    "目标声音身份、OtherSound 身份、实时 Wwise Gain 类型",
    "目标声音身份、实时 Wwise Gain 类型、实时 Wwise Limiter 类型",
    "目标声音身份、实时 Wwise Gain 类型、未知核对项目",
    "目标声音身份、实时 Wwise Gain 类型、修改 Pitch 为12",
    "目标声音身份、实时 Wwise Gain 类型、",
    "、目标声音身份、实时 Wwise Gain 类型",
])
def test_every_coordinated_member_remains_closed_even_with_explicit_append_recipient(operands):
    case = copy.deepcopy(_CASES[0])
    post = case["events"][2]["item"]
    post["text"] = post["text"].replace("目标声音身份、实时 Wwise Gain 类型", operands)
    post["text"] = post["text"].replace("。将追加", "。将向目标声音追加")
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("damage", ["before-mismatch", "prepared-version", "native-kind", "placement", "tool", "late"])
def test_coordinated_read_never_replaces_native_context_or_notice_timing(damage):
    case = copy.deepcopy(_CASES[0])
    if damage == "before-mismatch":
        case["before"]["owner"]["id"] = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
    elif damage == "prepared-version":
        case["artifact"]["prepared_operation"]["version"] = "2024.1"
    elif damage == "native-kind":
        case["artifact"]["prepared_operation"]["verification_plan"]["descriptor"]["kind"] = "source"
    elif damage == "placement":
        case["artifact"]["prepared_operation"]["verification_plan"]["placement"]["replace_existing_allowed"] = True
    elif damage == "tool":
        case["events"][2]["item"]["type"] = "command_execution"
    else:
        case["events"][-2:] = case["events"][-2:][::-1]
    assert not _grammatical_notice(case)
