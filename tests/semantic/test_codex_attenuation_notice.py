"""Attenuation notices are evaluated at the existing public grading seam."""

import json
import re
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.semantic.support.codex_task_runner_v3 import expansion_preview_notice


def _case(version):
    return json.loads((Path(__file__).parents[1] / "fixtures/semantic" /
        f"expansion-attenuation-notice-c39b728-{version[:4]}.json").read_text())


def _notice(case):
    records = [SimpleNamespace(command=name, argv=("python", "/tmp/skill/scripts/run.py", "gateway.py", name, "x"))
               for name in ("preview-from-draft", "execute")]
    return expansion_preview_notice(SimpleNamespace(stdout="\n".join(json.dumps(event) for event in case["events"])),
        records, version=case["version"], execute_expected=True,
        preview_artifact=case["artifact"], before_snapshot=case["before"])


def _decibel_case():
    fixture = json.loads((Path(__file__).parents[1] / "fixtures/semantic/expansion-contextual-notices-4d2c121.json").read_text())
    case = next(case for case in fixture["cases"] if case["case"] == "008-EXP25-C08")
    case["version"] = "2025.1"
    return case


@pytest.mark.parametrize("damage", ["wrong_y_unit", "wrong_x_unit", "extra_wrong_unit_point", "wrong_value", "wrong_source", "wrong_shape", "foreign_owner", "second_field", "other_quantity"])
def test_decibel_notation_is_bound_to_the_sealed_curve_quantity_and_complete_points(damage):
    case = _decibel_case()
    post = case["events"][1]["item"]
    if damage == "wrong_y_unit": post["text"] = post["text"].replace("-12 dB", "-12 Hz")
    elif damage == "wrong_x_unit": post["text"] = post["text"].replace("50.0,", "50.0 dB,")
    elif damage == "extra_wrong_unit_point": post["text"] += "另有点 (75,-24 Hz)。"
    elif damage == "wrong_value": post["text"] = post["text"].replace("-12 dB", "-60 dB")
    elif damage == "wrong_source": post["text"] = post["text"].replace("自定义", "project")
    elif damage == "wrong_shape": post["text"] = post["text"].replace("线性", "非线性")
    elif damage == "foreign_owner": post["text"] += "另外将 OtherOwner 的干声音量来源设为自定义。"
    elif damage == "second_field": post["text"] += "另外将该衰减的 Pitch 设为 12。"
    else:
        args = case["artifact"]["request"]["arguments"]["args"]
        args["curveType"] = "SpreadUsage"
        case["artifact"]["prepared_operation"]["request"] = deepcopy(case["artifact"]["request"])
        case["artifact"]["prepared_operation"]["dispatch"]["args"] = deepcopy(args)
        post["text"] = post["text"].replace("干声音量", "spread")
    assert not _notice(case)


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_actual_attenuation_notice_states_exact_effect_before_execute(version):
    assert _notice(_case(version))


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
@pytest.mark.parametrize("defect", ["missing", "extra", "wrong_value", "wrong_order", "wrong_shape",
    "wrong_kind", "wrong_source", "contradictory_kind", "contradictory_source", "negated", "foreign_id", "extra_field", "generic", "late", "later_conflict"])
def test_attenuation_notice_rejects_wrong_or_incomplete_effect_and_timing(version, defect):
    case = _case(version)
    item = case["events"][1]["item"]
    text = item["text"]
    pairs = list(re.finditer(r"\([^()]+\)", text))
    if defect == "missing": text = text[:pairs[-1].start()] + text[pairs[-1].end():]
    elif defect == "extra": text += "另设点 (75,-24)。"
    elif defect == "wrong_value": text = text.replace("-12", "-60")
    elif defect == "wrong_order":
        a, b = pairs[:2]
        text = text[:a.start()] + b.group() + text[a.end():b.start()] + a.group() + text[b.end():]
    elif defect == "wrong_shape": text = text.replace("线性", "非线性")
    elif defect == "wrong_kind": text = text.replace("干声音量", "湿声音量")
    elif defect == "wrong_source": text = text.replace("自定义", "project")
    elif defect == "contradictory_kind": text += "目标曲线不是干声音量。"
    elif defect == "contradictory_source": text += "来源不是自定义。"
    elif defect == "negated": text = text.replace("设为", "不设为")
    elif defect == "foreign_id": text += "对象为 {AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}。"
    elif defect == "extra_field": text += "同时修改备注。"
    elif defect == "generic": text = "预览完成，现在执行。"
    elif defect == "late": case["events"][1], case["events"][2] = case["events"][2], case["events"][1]
    else:
        case["events"].insert(2, {"type": "item.completed", "item": {"type": "agent_message", "text": "另外将干声音量曲线改为 (0,0)、(50,-60)、(100,-48)，各点线性。"}})
    item["text"] = text
    assert not _notice(case)


@pytest.mark.parametrize("defect", ["missing_prepared", "request_mismatch", "dispatch_mismatch", "missing_plan",
    "wrong_plan", "wrong_version", "missing_baseline", "wrong_owner", "wrong_type", "ambiguous_owner",
    "wrong_native_kind", "wrong_native_shape", "nonfinite", "extra_argument"])
def test_attenuation_context_requires_exact_sealed_target_plan_and_baseline(defect):
    case = _case("2025.1")
    artifact = case["artifact"]
    prepared = artifact["prepared_operation"]
    if defect == "missing_prepared": del artifact["prepared_operation"]
    elif defect == "request_mismatch": prepared["request"]["arguments"]["args"]["use"] = "None"
    elif defect == "dispatch_mismatch": prepared["dispatch"]["args"]["object"] = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
    elif defect == "missing_plan": del prepared["verification_plan"]
    elif defect == "wrong_plan": prepared["verification_plan"]["uri"] = "ak.wwise.core.object.set"
    elif defect == "wrong_version": case["version"] = "2000.1"
    elif defect == "missing_baseline": del case["before"]["attenuation"]
    elif defect == "wrong_owner": case["before"]["attenuation"]["id"] = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
    elif defect == "wrong_type": case["before"]["attenuation"]["type"] = "Sound"
    elif defect == "ambiguous_owner": case["before"]["source"]["object"] = deepcopy(case["before"]["attenuation"])
    else:
        args = artifact["request"]["arguments"]["args"]
        if defect == "wrong_native_kind": args["curveType"] = "UnknownUsage"
        elif defect == "wrong_native_shape": args["points"][1]["shape"] = "UnknownShape"
        elif defect == "nonfinite": args["points"][1]["x"] = float("inf")
        else: args["unexpected"] = "value"
        prepared["request"] = deepcopy(artifact["request"])
        prepared["dispatch"]["args"] = deepcopy(args)
    assert not _notice(case)


@pytest.mark.parametrize("extra", [
    "同时修改该对象的 Pitch 为 12。", "同时删除备注。", "同时删除其他对象。",
    "删除操作将立即执行。", "接下来将执行删除操作。",
    "同时移除该对象。", "同时清空该对象的备注。", "同时重置该对象的任意属性。",
    "同时替换该对象的 CustomField 为 12。", "同时新增一个其他对象。",
    "同时将另一个对象的干声音量曲线设为自定义。",
    "同时将 Horns 的干声音量曲线设为自定义。",
    "同时将 Horns 和该对象的干声音量曲线设为自定义。",
    "同时将 OtherOwner 和该衰减对象的干声音量曲线设为自定义。",
    "同时将另一个对象及该对象的干声音量曲线设为自定义。",
    "同时将该对象的任意属性设为 12。",
    "同时将该对象的曲线来源设为 project。",
    "同时将该对象的曲线形状设为 log-1。",
    "I will delete another object.", "I will remove its notes.",
    "I will replace this attenuation's Pitch with 12.",
])
def test_every_affirmative_mutation_must_be_the_sealed_attenuation_curve_effect(extra):
    case = _case("2025.1")
    case["events"][1]["item"]["text"] += extra
    assert not _notice(case)


@pytest.mark.parametrize("extra", [
    "修改范围已核实。", "修改请求的状态正常。", "删除操作没有执行。",
    "不修改该对象的 Pitch。", "不会删除备注。", "不会移除其他对象。",
    "不替换任何其他属性。", "Do not delete another object.",
    "I will not remove notes.", "The replacement status is unchanged.",
])
def test_nouns_status_and_negated_preservation_do_not_add_mutation(extra):
    case = _case("2025.1")
    case["events"][1]["item"]["text"] += extra
    assert _notice(case)
