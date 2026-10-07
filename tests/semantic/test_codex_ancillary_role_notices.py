"""Ancillary records retain the exact prospective notice at the public seam."""

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.semantic.support.codex_task_runner_v3 import expansion_preview_notice


_EXACT = Path(__file__).parents[1] / "fixtures/semantic/expansion-ancillary-roles-1cbc2d0.json"
_MATRIX = _EXACT.with_name("expansion-ancillary-role-independent-20261007.json")
_FIXTURE = _EXACT.with_name("expansion-ancillary-role-independent-fixture-20261007.json")
_VECTORS = json.loads(_MATRIX.read_text())["vectors"]


def _notice(events, case):
    records = [SimpleNamespace(command=phase, argv=("python", "/tmp/skill/scripts/run.py", "gateway.py", phase, "x"))
               for phase in ("preview-from-draft", "execute")]
    return expansion_preview_notice(
        SimpleNamespace(stdout="\n".join(json.dumps(event) for event in events)),
        records, version=case["artifact"]["request"]["version"], execute_expected=True,
        preview_artifact=case["artifact"], before_snapshot=case["before"])


def test_exact_ancillary_role_notice_precedes_execute_start():
    assert hashlib.sha256(_EXACT.read_bytes()).hexdigest() == "4f1c0475e555a27de359b7cef2fa3fb8823c1aa3341bdc0d115f23d615b5e188"
    case = json.loads(_EXACT.read_text())
    assert case["source"]["source_event_indices"] == [22, 23, 24]
    assert case["source"]["execute_completion_index"] == 25
    assert case["events"][2]["type"] == "item.started"
    text = case["events"][1]["item"]["text"]
    assert hashlib.sha256(text.encode()).hexdigest() == "cb742e83003bbbf6bfada9bc21c39ec7e31d801170c0650e425ed298d28a2a14"
    assert _notice(case["events"], case)


@pytest.mark.parametrize("vector", _VECTORS, ids=[vector["id"] for vector in _VECTORS])
def test_frozen_independent_ancillary_roles_preserve_owned_effect_and_remaining_claims(vector):
    assert hashlib.sha256(_MATRIX.read_bytes()).hexdigest() == "6fe9d9f3e5bbc5377b68f29cbfe8e500061dc8e3d329ae36add4926ec506234f"
    assert hashlib.sha256(_FIXTURE.read_bytes()).hexdigest() == "776e7b08a737efec00f08024281bdc67f090e31a88aeb69a81ed34313c45bbbe"
    case = json.loads(_FIXTURE.read_text())[vector["fixture_ref"]]
    for patch in vector["counterfactual_fixture_patch"]:
        if patch["op"] == "counterfactual_gate":
            # The frozen policy counterfactual is documentary at this notice
            # seam. It does not exercise or replace actual policy validation.
            continue
        target = case
        parts = patch["path"].lstrip("/").split("/")
        for part in parts[:-1]:
            target = target[int(part)] if isinstance(target, list) else target[part]
        if patch["op"] == "replace":
            target[parts[-1]] = patch["value"]
        else:
            assert patch["op"] == "remove"
            del target[parts[-1]]
    phases = {}
    for event in case["events"]:
        item = event.get("item", {})
        command = item.get("command", "")
        if item.get("type") != "command_execution":
            continue
        if "gateway.py preview-from-draft " in command and event["type"] == "item.completed":
            phases["preview_receipt"] = copy.deepcopy(event)
            phases["preview_receipt"]["item"]["command"] = "preview-from-draft"
        elif "gateway.py execute " in command and event["type"] == "item.started":
            phases["execute_start"] = copy.deepcopy(event)
            phases["execute_start"]["item"]["command"] = "execute"
    assert set(phases) == {"preview_receipt", "execute_start"}
    assert phases["execute_start"]["type"] == "item.started"
    events = []
    for stage in vector["stage_schedule"]:
        if stage.startswith("message:"):
            events.append({"type": "item.completed", "item": {"type": "agent_message",
                "text": vector["messages"][int(stage.split(":")[1])]}})
        else:
            events.append(copy.deepcopy(phases["preview_receipt" if stage == "second_preview_receipt" else stage]))
    assert _notice(events, case) is vector["expected_notice_evidence"], vector["expectation_basis"]


def _single_message_notice(fixture_ref, text):
    case = json.loads(_FIXTURE.read_text())[fixture_ref]
    events = [
        {"type": "item.completed", "item": {"type": "command_execution", "command": "preview-from-draft"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": text}},
        {"type": "item.started", "item": {"type": "command_execution", "command": "execute"}},
    ]
    return _notice(events, case)


@pytest.mark.parametrize("owner_type,owner_id,expected", [
    ("Stinger", "{B8D45849-AF76-4770-BE7B-5A6553B1337B}", True),
    ("Stinger", "{FB63DE7B-12AF-4A12-A836-FFAE0B4DD858}", False),
    ("Trigger", "{FB63DE7B-12AF-4A12-A836-FFAE0B4DD858}", False),
    ("Trigger", "{B8D45849-AF76-4770-BE7B-5A6553B1337B}", False),
])
def test_typed_guid_attestation_keeps_native_source_separate_from_destination(owner_type, owner_id, expected):
    text = _VECTORS[49]["messages"][0]
    text = text.replace("Stinger {B8D45849-AF76-4770-BE7B-5A6553B1337B}", owner_type + " " + owner_id, 1)
    assert _single_message_notice("Stinger", text) is expected


@pytest.mark.parametrize("damage", ["none", "old-unit", "new-unit", "old-value", "new-value", "endpoint-value",
                                      "endpoint-order", "endpoint-count", "wrong-shape", "denied-shape", "missing-shape", "extra-edit",
                                      "later-time-edit", "later-shape-contradiction"])
def test_rtpc_middle_delta_and_retained_endpoints_keep_exact_quantity_order_and_remaining_edits(damage):
    text = _VECTORS[51]["messages"][0]
    if damage == "old-unit":
        text = text.replace("(50, -12 dB)", "(50, -12 Hz)")
    elif damage == "new-unit":
        text = text.replace("(50, -6 dB)", "(50, -6 Hz)")
    elif damage == "old-value":
        text = text.replace("(50, -12 dB)", "(50, -18 dB)")
    elif damage == "new-value":
        text = text.replace("(50, -6 dB)", "(50, -3 dB)")
    elif damage == "endpoint-value":
        text = text.replace("(0, -48 dB)", "(0, -24 dB)")
    elif damage == "endpoint-order":
        text = text.replace("(0, -48 dB)、(100, 0 dB)", "(100, 0 dB)、(0, -48 dB)")
    elif damage == "endpoint-count":
        text = text.replace("、(100, 0 dB)", "")
    elif damage == "wrong-shape":
        text = text.replace("Linear", "Log3")
    elif damage == "denied-shape":
        text = text.replace("Linear", "不保持 Linear")
    elif damage == "missing-shape":
        text = text.replace("三点 Linear 形状、", "")
    elif damage == "extra-edit":
        text += "同时修改 Pitch 为12。"
    elif damage == "later-time-edit":
        text += "同时修改 Time 为12。"
    elif damage == "later-shape-contradiction":
        text += "本次 Volume RTPC 曲线不保持 Linear 形状。"
    assert _single_message_notice("RTPC", text) is (damage == "none")


@pytest.mark.parametrize("endpoints,expected", [
    ("端点 (0, -48 dB)、(100, 0 dB)、", True),
    ("端点 (0, -48 dB)、(100, 0 dB) 保持原样，", True),
    ("端点 (0, -48 dB)、(100, 0 dB) 不会保持原样，", False),
    ("端点 (0, -48 dB)、(100, 0 dB) 可能保持原样，", False),
    ("端点 (0, -48 dB)、(100, 0 dB)，", False),
])
def test_rtpc_endpoint_preservation_owns_its_predicate_and_polarity(endpoints, expected):
    text = _VECTORS[51]["messages"][0].replace("端点 (0, -48 dB)、(100, 0 dB)、", endpoints)
    assert _single_message_notice("RTPC", text) is expected


@pytest.mark.parametrize("replacement,extra,expected", [
    ("三点 Linear", "", True),
    ("四点 Linear", "", False),
    ("3 点 Linear", "", True),
    ("4 点 Linear", "", False),
    ("三点 Linear", "本次 Volume RTPC 曲线共四点。", False),
    ("三点 Linear", "本次 Volume RTPC 曲线共三点。", True),
    ("三点 Linear", "今天四点执行检查。", True),
    ("三点 Linear", "今天四点开始，五点结束。", True),
])
def test_rtpc_curve_cardinality_is_local_and_cannot_be_contradicted(replacement, extra, expected):
    text = _VECTORS[51]["messages"][0].replace("三点 Linear", replacement) + extra
    assert _single_message_notice("RTPC", text) is expected


@pytest.mark.parametrize("extra,expected", [
    ("同时移除 Pitch RTPC 关系。", False),
    ("同时清空 Pitch RTPC 关系。", False),
    ("同时新增 Pitch RTPC 关系。", False),
    ("同时移除该声音。", False),
    ("同时移除该声音上的 Volume RTPC 关系。", False),
    ("不会移除 Pitch RTPC 关系。", True),
    ("不会清空 Pitch RTPC 关系。", True),
    ("新增关系计数为零。移除关系计数为零。", True),
    ("移除关系计数为零。同时移除 Pitch RTPC 关系。", False),
    ("记录修改前状态。", True),
])
def test_rtpc_validated_curve_carrier_preserves_residual_action_accounting(extra, expected):
    assert _single_message_notice("RTPC", _VECTORS[51]["messages"][0] + extra) is expected


@pytest.mark.parametrize("frame", ["已确认 {operand} 身份", "{operand} 身份已确认", "已确认 {operand}", "{operand} 已确认"])
@pytest.mark.parametrize("owner_type,owner_id,expected", [
    ("Stinger", "{B8D45849-AF76-4770-BE7B-5A6553B1337B}", True),
    ("Stinger", "{FB63DE7B-12AF-4A12-A836-FFAE0B4DD858}", False),
    ("Trigger", "{FB63DE7B-12AF-4A12-A836-FFAE0B4DD858}", False),
    ("Trigger", "{B8D45849-AF76-4770-BE7B-5A6553B1337B}", False),
])
def test_typed_identity_forward_and_reverse_share_sealed_source_validation(frame, owner_type, owner_id, expected):
    text = _VECTORS[49]["messages"][0]
    _, separator, effect = text.partition("。")
    assert separator
    text = frame.format(operand=owner_type + " " + owner_id) + "。" + effect
    assert _single_message_notice("Stinger", text) is expected


@pytest.mark.parametrize("field", ["name", "type", "path"])
@pytest.mark.parametrize("damage", ["missing", None, "", 42])
def test_rtpc_matching_incomplete_owner_fields_do_not_attest_a_complete_source(field, damage):
    case = json.loads(_FIXTURE.read_text())["RTPC"]
    for row in (case["before"]["owner"], case["artifact"]["prepared_operation"]["pre_state"]["object"]):
        if damage == "missing":
            del row[field]
        else:
            row[field] = damage
    events = [
        {"type": "item.completed", "item": {"type": "command_execution", "command": "preview-from-draft"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": _VECTORS[51]["messages"][0]}},
        {"type": "item.started", "item": {"type": "command_execution", "command": "execute"}},
    ]
    assert not _notice(events, case)
