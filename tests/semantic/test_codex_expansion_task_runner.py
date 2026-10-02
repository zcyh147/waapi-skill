import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.semantic.support.codex_task_runner_v3 import expansion_preview_notice


ARTIFACT = {"request": {"operation": "audio.import", "arguments": {
    "imports": [{"object_path": r"\Music\Quiet", "properties": [{"name": "Volume", "value": -6.0}]}]}}}


@pytest.mark.parametrize("unit,expected", [("EXP25-C01", True), ("EXP25-C06", False), ("EXP25-M01", False)])
def test_actual_archived_preview_notice_wording_and_order(unit, expected):
    fixture = json.loads((Path(__file__).parents[1] / "fixtures/semantic/expansion-preview-notice-122eb09.json").read_text())
    case = next(case for case in fixture["cases"] if case["unit"] == unit)
    assert _notice(case["events"], artifact=case["preview_artifact"],
        before=case["before_snapshot"], execute_expected=case["execute_expected"]) is expected


def _current_notice_case(model="sol-medium", unit="EXP25-C06"):
    fixture = json.loads((Path(__file__).parents[1] / "fixtures/semantic/expansion-preview-notice-0997d20.json").read_text())
    return next(case for case in fixture["cases"] if case["model"] == model and case["unit"] == unit)


@pytest.mark.parametrize("model,unit", [("luna-high", "EXP25-C06"), ("sol-medium", "EXP25-C06"),
    ("luna-high", "EXP25-M01")])
def test_current_archived_notice_accepts_specific_effect_in_bound_context(model, unit):
    case = _current_notice_case(model, unit)
    assert _notice(case["events"], artifact=case["preview_artifact"], before=case["before_snapshot"])


@pytest.mark.parametrize("text", [
    "即将执行预览。",
    "将音量曲线的中间点改为 (50,-60)，两端和线性插值保持不变。",
    "将音量曲线的中间点改为 (50,6)，两端和线性插值保持不变。",
    "将音量曲线的中间点改为 (50,-6)，两端改为 (0,-20)、(100,2)，各段线性。",
    "将音量曲线改为 (0,-48)、(50,-6)、(100,0)，各段线性；备注改为新的备注。",
    "现有音量曲线为 (0,-48)、(50,-24)、(100,0)。将音量曲线的中间点改为 (50,-6)，两端和线性插值保持不变。",
    "将音量曲线改为 (0,-48)、(50,-6)、(100,0)，各段线性，目标是 {AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}。",
])
def test_contextual_rtpc_notice_rejects_wrong_effect_and_preservation(text):
    case = _current_notice_case()
    assert not _notice([PREVIEW, _message(text), EXECUTE],
        artifact=case["preview_artifact"], before=case["before_snapshot"])


@pytest.mark.parametrize("preservation,expected", [
    ("不修改备注，也不修改其他控制曲线。", True),
    ("do not change pitch; do not update notes.", True),
    ("do not change pitch or update notes.", True),
    ("修改备注。", False),
    ("change pitch.", False),
    ("不修改备注，但修改其他控制曲线。", False),
    ("do not change pitch, but update notes.", False),
    ("不修改备注，并更新身份。", False),
])
def test_rtpc_preservation_uses_clause_polarity(preservation, expected):
    case = _current_notice_case()
    text = "将音量曲线改为 (0,-48)、(50,-6)、(100,0)，各段线性；" + preservation
    assert _notice([PREVIEW, _message(text), EXECUTE],
        artifact=case["preview_artifact"], before=case["before_snapshot"]) is expected


@pytest.mark.parametrize("interpolation,expected", [
    ("线性", True), ("linear", True), ("非线性", False), ("不使用线性", False),
    ("保持线性", True), ("使用线性", True), ("不保持线性", False), ("不用线性", False),
    ("nonlinear", False), ("non-linear", False), ("not linear", False),
])
@pytest.mark.parametrize("form", ["full", "delta"])
def test_rtpc_notice_requires_affirmative_requested_interpolation(form, interpolation, expected):
    case = _current_notice_case()
    if form == "full":
        text = f"将音量曲线改为 (0,-48)、(50,-6)、(100,0)，各段{interpolation}。"
    else:
        text = f"将音量曲线的中间点改为 (50,-6)，两端和{interpolation}插值保持不变。"
    assert _notice([PREVIEW, _message(text), EXECUTE],
        artifact=case["preview_artifact"], before=case["before_snapshot"]) is expected


def test_rtpc_interpolation_check_does_not_blacklist_unrelated_preservation_clause():
    case = _current_notice_case()
    text = "将音量曲线改为 (0,-48)、(50,-6)、(100,0)，各段线性；其他曲线的非线性插值不变。"
    assert _notice([PREVIEW, _message(text), EXECUTE],
        artifact=case["preview_artifact"], before=case["before_snapshot"])


@pytest.mark.parametrize("defect", ["owner", "control", "association", "plan_points", "snapshot",
    "duplicate_volume", "duplicate_control", "version", "missing_versions", "nonfinite", "boolean_point", "shape", "notes", "malformed_prepared", "malformed_plan", "duplicate_plan_row"])
def test_rtpc_context_requires_unique_immutable_and_baseline_agreement(defect):
    case = _current_notice_case()
    artifact, before = case["preview_artifact"], case["before_snapshot"]
    args = artifact["request"]["arguments"]
    prepared = artifact["prepared_operation"]
    plan = prepared["verification_plan"]
    foreign = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
    if defect in {"owner", "control", "association"}:
        plan[{"owner": "object_id", "control": "control_input_id", "association": "existing_rtpc_id"}[defect]] = foreign
    elif defect == "plan_points":
        plan["points"][1]["y"] = -60
    elif defect == "snapshot":
        prepared["pre_state"]["rtpc_snapshot"]["rows"][0]["notes"] = "changed"
    elif defect == "duplicate_volume":
        from copy import deepcopy
        row = deepcopy(next(row for row in before["rtpcs"].values() if row["@PropertyName"] == "Volume"))
        row["id"] = foreign
        before["rtpcs"][foreign] = row
        prepared["pre_state"]["rtpc_snapshot"]["rows"].append(row)
        plan["before_rows"].append(row)
    elif defect == "duplicate_control":
        before["controls"].append(dict(before["controls"][0]))
    elif defect == "version":
        plan.pop("version")
    elif defect == "missing_versions":
        artifact["request"].pop("version")
        prepared.pop("version")
        plan.pop("version")
    elif defect == "malformed_prepared":
        artifact["prepared_operation"] = []
    elif defect == "malformed_plan":
        prepared["verification_plan"] = []
    elif defect == "duplicate_plan_row":
        plan["before_rows"].append(dict(plan["before_rows"][0]))
    elif defect in {"nonfinite", "boolean_point", "shape"}:
        args["points"][1]["shape" if defect == "shape" else "y"] = {
            "nonfinite": float("nan"), "boolean_point": True, "shape": "Logarithmic"}[defect]
    elif defect == "notes":
        args["notes"] = "overwrite"
    assert not _notice(case["events"], artifact=artifact, before=before)


def _scalar_notice_case():
    return json.loads((Path(__file__).parents[1] / "fixtures/semantic/expansion-midpoint-notice-919043f.json").read_text())


def test_actual_scalar_midpoint_notice_in_attested_relationship_context():
    case = _scalar_notice_case()
    assert _notice(case["events"], artifact=case["preview_artifact"], before=case["before_snapshot"])


@pytest.mark.parametrize("role,value,endpoints,shape,expected", [
    ("中点", "-6.0", "(0,-48) 和 (100,0)", "线性", True),
    ("中点", "−6", "(0,-48) 和 (100,0)", "线性", True),
    ("端点", "-6", "(0,-48) 和 (100,0)", "线性", False),
    ("中点", "+6", "(0,-48) 和 (100,0)", "线性", False),
    ("中点", "-60", "(0,-48) 和 (100,0)", "线性", False),
    ("中点", "-6.5", "(0,-48) 和 (100,0)", "线性", False),
    ("中点", "-6e2", "(0,-48) 和 (100,0)", "线性", False),
    ("中点", "-6", "(0,-48) 和 (100,2)", "线性", False),
    ("中点", "-6", "(100,0)", "线性", False),
    ("中点", "-6", "(0,-48) 和 (100,0)", "非线性", False),
    ("中点", "-6", "(0,-48) 和 (100,0)", "不保持线性", False),
])
def test_scalar_midpoint_requires_exact_role_value_endpoints_and_shape(role, value, endpoints, shape, expected):
    case = _scalar_notice_case()
    text = f"我将该关系的{role}改为 {value}，保持 {endpoints} 不变、三个点均为{shape}。"
    assert _notice([PREVIEW, _message(text), EXECUTE],
        artifact=case["preview_artifact"], before=case["before_snapshot"]) is expected


@pytest.mark.parametrize("defect", ["one_point", "four_points", "different_domain", "multiple_changes", "ambiguous_volume"])
def test_scalar_role_is_only_defined_in_unique_three_point_single_middle_y_change(defect):
    from copy import deepcopy
    case = _scalar_notice_case()
    artifact, before = case["preview_artifact"], case["before_snapshot"]
    args, prepared = artifact["request"]["arguments"], artifact["prepared_operation"]
    if defect == "one_point":
        args["points"] = [args["points"][1]]
    elif defect == "four_points":
        args["points"].insert(1, {"x": 25, "y": -24, "shape": "Linear"})
    elif defect == "different_domain":
        args["points"][1]["x"] = 60
    elif defect == "multiple_changes":
        args["points"][0]["y"] = -30
    else:
        row = deepcopy(next(row for row in before["rtpcs"].values() if row["@PropertyName"] == "Volume"))
        row["id"] = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
        before["rtpcs"][row["id"]] = row
        prepared["pre_state"]["rtpc_snapshot"]["rows"].append(deepcopy(row))
        prepared["verification_plan"]["before_rows"].append(row)
    prepared["verification_plan"]["points"] = deepcopy(args["points"])
    assert not _notice(case["events"], artifact=artifact, before=before)


@pytest.mark.parametrize("text", [
    "现在处理该关系，并保持其他项不变。",
    "我将该关系的中点改为 -6，三个点均为线性。",
    "我不将该关系的中点改为 -6，保持 (0,-48) 和 (100,0) 不变、三个点均为线性。",
    "我将该关系的中点改为 -6，保持 (0,-48) 和 (100,0) 不变、三个点均为线性；修改备注。",
])
def test_scalar_role_keeps_concrete_retention_and_preservation_obligations(text):
    case = _scalar_notice_case()
    assert not _notice([PREVIEW, _message(text), EXECUTE],
        artifact=case["preview_artifact"], before=case["before_snapshot"])


@pytest.mark.parametrize("text", [
    "我将该关系的中点改为 -6，但中点改为 -60，保持 (0,-48) 和 (100,0) 不变、三个点均为线性。",
    "现有音量曲线中点为 (50,-24)，我将该关系的中点改为 -6，保持 (0,-48) 和 (100,0) 不变、三个点均为线性。",
])
def test_scalar_notice_rejects_conflicting_claims_and_wrong_historical_points(text):
    case = _scalar_notice_case()
    assert not _notice([PREVIEW, _message(text), EXECUTE],
        artifact=case["preview_artifact"], before=case["before_snapshot"])


@pytest.mark.parametrize("target,expected", [
    ("该关系", True), ("Volume/Rain_Intensity 曲线", True),
    ("Pitch 曲线", False), ("Time 控制的该关系", False),
])
def test_scalar_role_cannot_override_explicit_property_or_control_target(target, expected):
    case = _scalar_notice_case()
    text = f"我将 {target} 的中点改为 -6，保持 (0,-48) 和 (100,0) 不变、三个点均为线性。"
    assert _notice([PREVIEW, _message(text), EXECUTE],
        artifact=case["preview_artifact"], before=case["before_snapshot"]) is expected


def _cross_clause_notice_case():
    return json.loads((Path(__file__).parents[1] / "fixtures/semantic/expansion-context-notice-cf94158.json").read_text())


def test_actual_notice_composes_same_target_delta_retention_and_prior_requested_shape():
    case = _cross_clause_notice_case()
    assert _notice(case["events"], artifact=case["preview_artifact"], before=case["before_snapshot"])


@pytest.mark.parametrize("defect", ["missing_plan", "wrong_plan_count", "wrong_plan_control", "wrong_plan_shape", "wrong_plan_identity",
    "wrong_value", "wrong_history", "foreign_id", "wrong_property", "wrong_control", "missing_remainder",
    "wrong_shape_clause", "wrong_shape_later_message", "extra_change", "late", "generic"])
def test_composed_notice_keeps_context_effect_and_temporal_obligations(defect):
    case = _cross_clause_notice_case()
    events = case["events"]
    earlier, post = events[0]["item"], events[2]["item"]
    if defect == "missing_plan":
        events.pop(0)
    elif defect == "wrong_plan_count":
        earlier["text"] = earlier["text"].replace("三点线性", "两点线性")
    elif defect == "wrong_plan_control":
        earlier["text"] = earlier["text"].replace("Rain_Intensity", "Time")
    elif defect == "wrong_plan_shape":
        earlier["text"] = earlier["text"].replace("三点线性", "三点非线性")
    elif defect == "wrong_plan_identity":
        earlier["text"] += "目标 {AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}。"
    elif defect in {"wrong_value", "wrong_history", "wrong_property", "wrong_control"}:
        old, new = {"wrong_value": ("(50,-6)", "(50,-60)"), "wrong_history": ("(50,-12)", "(50,-24)"),
            "wrong_property": ("Voice Volume", "Voice Pitch"), "wrong_control": ("Rain_Intensity", "Time")}[defect]
        post["text"] = post["text"].replace(old, new)
    elif defect == "foreign_id":
        post["text"] = post["text"].replace("{5435E98C-AC79-495D-9274-9B8332ACE98E}", "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}")
    elif defect == "missing_remainder":
        post["text"] = post["text"].replace("曲线其余两点已符合目标", "预览已准备好")
    elif defect == "wrong_shape_clause":
        post["text"] += "各段非线性。"
    elif defect == "wrong_shape_later_message":
        events.insert(3, _message("各段不保持线性。"))
    elif defect == "extra_change":
        post["text"] += "另外将音量曲线的 (100,0) 改为 (100,2)。"
    elif defect == "late":
        events[2], events[3] = events[3], events[2]
    else:
        post["text"] = "预览已完成，现在执行。"
    assert not _notice(events, artifact=case["preview_artifact"], before=case["before_snapshot"])


@pytest.mark.parametrize("midpoint,expected", [("-6", True), ("-60", False)])
def test_inherited_shape_plan_explicit_points_must_match_sealed_request(midpoint, expected):
    case = _cross_clause_notice_case()
    earlier = case["events"][0]["item"]
    earlier["text"] = earlier["text"].replace("提交三点线性曲线", f"提交 (0,-48)、(50,{midpoint})、(100,0) 三点线性曲线")
    assert _notice(case["events"], artifact=case["preview_artifact"], before=case["before_snapshot"]) is expected


@pytest.mark.parametrize("later,expected", [
    ("我将为 Volume/Rain_Intensity 提交三点非线性曲线。", False),
    ("我将为 Volume/Rain_Intensity 提交三点对数曲线。", False),
    ("I will submit 3 points with a Logarithmic curve for Volume/Rain_Intensity.", False),
    ("已完成元数据读取，Volume/Rain_Intensity 尚未执行。", True),
    ("我将为 Volume/Rain_Intensity 提交 (0,-48)、(50,-60)、(100,0) 三点线性曲线。", False),
    ("我将为 Volume/Time 提交三点线性曲线。", False),
    ("我将为 Volume/Rain_Intensity 提交三点线性曲线。", True),
])
def test_later_pre_preview_plan_replaces_inherited_shape_authority(later, expected):
    case = _cross_clause_notice_case()
    case["events"].insert(1, _message(later))
    assert _notice(case["events"], artifact=case["preview_artifact"], before=case["before_snapshot"]) is expected


def test_other_relationship_retention_cannot_certify_target_remainder():
    case = _cross_clause_notice_case()
    post = case["events"][2]["item"]
    post["text"] = post["text"].replace("曲线其余两点已符合目标", "另一条关系的两端保持不变")
    assert not _notice(case["events"], artifact=case["preview_artifact"], before=case["before_snapshot"])


def test_same_target_notice_can_complete_retention_in_a_separate_visible_message():
    case = _cross_clause_notice_case()
    post = case["events"][2]["item"]["text"]
    first, rest = post.split("；", 1)
    case["events"][2] = _message(first + "。")
    case["events"].insert(3, _message(rest))
    assert _notice(case["events"], artifact=case["preview_artifact"], before=case["before_snapshot"])


def _point_notice_case(model):
    fixture = json.loads((Path(__file__).parents[1] / "fixtures/semantic/expansion-point-notice-86e23cd.json").read_text())
    return next(case for case in fixture["cases"] if case["model"] == model)


@pytest.mark.parametrize("model", ["luna-high", "sol-medium"])
def test_actual_delta_explanation_and_complete_curve_facts_form_coherent_notice(model):
    case = _point_notice_case(model)
    assert _notice(case["events"], artifact=case["preview_artifact"], before=case["before_snapshot"])


@pytest.mark.parametrize("model,defect", [
    ("luna-high", "conflicting_delta"), ("luna-high", "wrong_history"), ("luna-high", "no_middle_role"),
    ("luna-high", "missing_result_point"), ("luna-high", "extra_result_point"), ("luna-high", "duplicate_authored_point"),
    ("luna-high", "wrong_result_domain"), ("luna-high", "wrong_shape"), ("luna-high", "foreign_id"),
    ("sol-medium", "missing_current_point"), ("sol-medium", "duplicate_current_point"),
    ("sol-medium", "wrong_history"), ("sol-medium", "wrong_delta_domain"), ("sol-medium", "wrong_role"),
    ("sol-medium", "foreign_history"), ("sol-medium", "extra_change"), ("sol-medium", "wrong_control"),
    ("sol-medium", "generic"), ("sol-medium", "late"),
])
def test_coherent_point_evidence_does_not_hide_incomplete_extra_or_conflicting_claims(model, defect):
    case = _point_notice_case(model)
    post = case["events"][1]["item"]
    text = post["text"]
    if defect == "conflicting_delta":
        text = text.replace("(50, -6)", "(50, -60)", 1)
    elif defect == "wrong_history":
        text = text.replace("(50, -12)", "(50, -24)") if model == "luna-high" else text.replace("(50,-12)", "(50,-24)")
    elif defect == "no_middle_role":
        text = text.replace("中间点", "曲线")
    elif defect == "missing_result_point":
        text = text.replace("、(100, 0)", "")
    elif defect == "extra_result_point":
        text = text.replace("、(100, 0)", "、(75, -3)、(100, 0)")
    elif defect == "duplicate_authored_point":
        text = text.replace("曲线点为 (0, -48)、(50, -6)、(100, 0)", "曲线点为 (0, -48)、(50, -6)、(50, -6)、(100, 0)")
    elif defect == "wrong_result_domain":
        text = text.replace("曲线点为 (0, -48)、(50, -6)", "曲线点为 (0, -48)、(60, -6)")
    elif defect == "wrong_shape":
        text = text.replace("各段线性", "各段非线性")
    elif defect == "foreign_id":
        text += "目标是 {AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}。"
    elif defect == "missing_current_point":
        text = text.replace("、(100,0)", "")
    elif defect == "duplicate_current_point":
        text = text.replace("、(100,0)", "、(100,0)、(100,0)")
    elif defect == "wrong_delta_domain":
        text = text.replace("(50,-6)", "(60,-6)")
    elif defect == "wrong_role":
        text = text.replace("中间点", "端点")
    elif defect == "foreign_history":
        text = text.replace("当前曲线为", "另一条关系的当前曲线为")
    elif defect == "extra_change":
        text += "同时将音量曲线的 (100,0) 改为 (100,2)。"
    elif defect == "wrong_control":
        text = text.replace("把中间点", "把 Time 控制的中间点")
    elif defect == "generic":
        text = "音量关系已核对，现在执行。"
    else:
        case["events"][1], case["events"][2] = case["events"][2], case["events"][1]
    post["text"] = text
    assert not _notice(case["events"], artifact=case["preview_artifact"], before=case["before_snapshot"])


def test_incidental_middle_role_cannot_normalize_four_authored_curve_points():
    case = _point_notice_case("luna-high")
    text = "将音量曲线（包括中间点）改为 (50,-6)、(0,-48)、(50,-6)、(100,0)，各段线性。"
    assert not _notice([PREVIEW, _message(text), EXECUTE],
        artifact=case["preview_artifact"], before=case["before_snapshot"])


def test_incidental_middle_role_cannot_turn_one_point_replacement_into_preserving_edit():
    case = _point_notice_case("sol-medium")
    text = "当前音量曲线为 (0,-48)、(50,-12)、(100,0)，各段线性。即将把音量曲线（包括中间点）改为 (50,-6)，保留原控制关系及备注。"
    assert not _notice([PREVIEW, _message(text), EXECUTE],
        artifact=case["preview_artifact"], before=case["before_snapshot"])


def _initial_context_notice(case_id):
    fixture = json.loads((Path(__file__).parents[1] / "fixtures/semantic/expansion-contextual-notices-977e71e.json").read_text())
    return next(case for case in fixture["cases"] if case["case"] == case_id)


def _next_context_notice(case_id):
    fixture = json.loads((Path(__file__).parents[1] / "fixtures/semantic/expansion-contextual-notices-c39b728.json").read_text())
    return next(case for case in fixture["cases"] if case["case"] == case_id)


def _coherent_context_notice(case_id):
    fixture = json.loads((Path(__file__).parents[1] / "fixtures/semantic/expansion-contextual-notices-4d2c121.json").read_text())
    return next(case for case in fixture["cases"] if case["case"] == case_id)


@pytest.mark.parametrize("case_id", ["003-EXP22-C06", "005-EXP22-C09", "007-EXP25-C06", "008-EXP25-C08", "009-EXP25-C09", "010-EXP25-M05"])
def test_archived_coherent_notice_states_match_the_attested_single_edit(case_id):
    case = _coherent_context_notice(case_id)
    assert _notice(case["events"], artifact=case["artifact"], before=case["before"])


@pytest.mark.parametrize("case_id", ["003-EXP22-C06", "005-EXP22-C09", "007-EXP25-C06", "008-EXP25-C08", "009-EXP25-C09", "010-EXP25-M05"])
@pytest.mark.parametrize("damage", ["foreign_identity", "baseline", "version", "generic", "late", "extra_change"])
def test_coherent_notice_context_cannot_certify_unattested_or_extra_effects(case_id, damage):
    case = _coherent_context_notice(case_id)
    post = case["events"][-2]["item"]
    if damage == "foreign_identity": post["text"] += "目标是 {AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}。"
    elif damage == "baseline":
        key = "attenuation" if case_id.endswith("C08") else "stinger" if case_id.endswith("M05") else "owner"
        case["before"][key]["id"] = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
    elif damage == "version": case["artifact"]["request"]["version"] = "2024.1"
    elif damage == "generic": post["text"] = "预览已授权，现在执行。"
    elif damage == "late": case["events"][-2:] = case["events"][-2:][::-1]
    else:
        post["text"] += "同时修改备注。" if case_id.endswith("C06") else "该衰减的 Pitch 设为 12。" if case_id.endswith("C08") else "另外向 OtherOwner 新增名为 Expansion_" + case_id.split("-", 1)[1] + "_NewGain 的 Effect。" if case_id.endswith("C09") else "同时设为 OtherTrigger。"
    assert not _notice(case["events"], artifact=case["artifact"], before=case["before"])


@pytest.mark.parametrize("case_id", ["003-EXP22-C06", "007-EXP25-C06"])
@pytest.mark.parametrize("damage", ["wrong_history", "wrong_value", "positive_value", "wrong_endpoint", "wrong_order", "extra_point", "wrong_from", "missing_point_role", "replace_curve", "wrong_shape", "foreign_property", "foreign_control", "second_delta", "wrong_y_unit", "extra_wrong_unit_point"])
def test_before_state_and_only_middle_y_claim_require_the_exact_sealed_edit(case_id, damage):
    case = _coherent_context_notice(case_id)
    post = case["events"][-2]["item"]
    text = post["text"]
    if damage == "wrong_history": text = text.replace("(50, -12)", "(50, -24)").replace("(50,-12)", "(50,-24)")
    elif damage == "wrong_value": text = text.replace("改为 -6", "改为 -60")
    elif damage == "positive_value": text = text.replace("改为 -6", "改为 6")
    elif damage == "wrong_endpoint": text = text.replace("(0, -48)", "(0, -20)").replace("(0,-48)", "(0,-20)")
    elif damage == "wrong_order": text = text.replace("(0, -48)、(50, -12)", "(50, -12)、(0, -48)").replace("(0,-48)、(50,-12)", "(50,-12)、(0,-48)")
    elif damage == "extra_point": text = text.replace("(100, 0)", "(100, 0)、(75,-3)").replace("(100,0)", "(100,0)、(75,-3)")
    elif damage == "wrong_from": text = text.replace("从 -12", "从 -24") if "从 -12" in text else text.replace("中间点改为", "中间点从 -24 改为")
    elif damage == "missing_point_role": text = text.replace("中间点", "该点")
    elif damage == "replace_curve": text = text.replace("中间点改为 -6 dB", "曲线改为 (50,-6)").replace("曲线的中间点从 -12 改为 -6", "曲线改为 (50,-6)")
    elif damage == "wrong_shape": text = text.replace("线性", "非线性")
    elif damage == "foreign_property": text = text.replace("中间点", "Pitch 曲线的中间点")
    elif damage == "foreign_control": text = text.replace("中间点", "Time 关联的中间点")
    elif damage == "wrong_y_unit": text = text.replace("-6 dB", "-6 Hz") if "-6 dB" in text else text.replace("改为 -6", "改为 -6 Hz")
    elif damage == "extra_wrong_unit_point": text += "另有点 (75,-3 Hz)。"
    else: text += "但仅把中间点改为 -60，线性段保持原样。"
    assert text != post["text"]
    post["text"] = text
    assert not _notice(case["events"], artifact=case["artifact"], before=case["before"])


@pytest.mark.parametrize("claim", [
    "另外向 OtherOwner 新增名为 Expansion_EXP25-C09_NewGain 的 Effect。",
    "另外在此对象和 OtherOwner 上新增名为 Expansion_EXP25-C09_NewGain 的 Effect。",
    "另外新增名为 AnotherGain 的 Effect。",
    "另外删除原效果。",
])
def test_this_object_in_attested_notice_never_inherits_a_second_owner_or_effect(claim):
    case = _coherent_context_notice("009-EXP25-C09")
    case["events"][-2]["item"]["text"] += claim
    assert not _notice(case["events"], artifact=case["artifact"], before=case["before"])


def test_before_state_with_precise_midpoint_delta_and_preserved_remainder_needs_no_only_keyword():
    case = _coherent_context_notice("007-EXP25-C06")
    case["events"][-2]["item"]["text"] = case["events"][-2]["item"]["text"].replace("仅把", "把")
    assert _notice(case["events"], artifact=case["artifact"], before=case["before"])


@pytest.mark.parametrize("case_id", ["003-EXP22-C06", "007-EXP25-C06"])
@pytest.mark.parametrize("claim,expected", [
    ("但仅把中间点改为 -60 Hz，线性段保持原样。", False),
    ("但仅把中间点改为 -60，线性段保持原样。", False),
    ("但仅把中间点改为，线性段保持原样。", False),
    ("但仅把中间点改为未知值，线性段保持原样。", False),
    ("不会把中间点改为 -60 Hz。", True),
    ("不会把中间点改为 -60 dB。", True),
    ("当前中间点为 -12 dB。", True),
    ("当前中间点为 -24 dB。", False),
    ("当前中间点为 -12 Hz。", False),
])
def test_later_scalar_edit_intent_cannot_hide_behind_a_valid_effect(case_id, claim, expected):
    case = _coherent_context_notice(case_id)
    case["events"][-2]["item"]["text"] += claim
    assert _notice(case["events"], artifact=case["artifact"], before=case["before"]) is expected


@pytest.mark.parametrize("case_id", ["003-EXP22-C06", "007-EXP25-C06"])
@pytest.mark.parametrize("value,expected", [
    ("(-60 Hz)", False), ("（-60 Hz）", False), ("(-60)", False), ("（-6）", False),
    ("(50,-60)", False), ("（50,-60）", False), ("(50,)", False),
    ("(50,-6", False), ("（50,-6", False), ("(50,-6))", False),
    ("(50,-6)", True), ("（50,-6）", True),
])
def test_midpoint_tuple_intent_requires_a_complete_correct_coordinate_claim(case_id, value, expected):
    case = _coherent_context_notice(case_id)
    case["events"][-2]["item"]["text"] += f"但仅把中间点改为 {value}，线性段保持原样。"
    assert _notice(case["events"], artifact=case["artifact"], before=case["before"]) is expected


@pytest.mark.parametrize("claim,expected", [
    ("不会把中间点改为 (-60 Hz)。", True),
    ("不会把中间点改为 (50,-60)。", True),
    ("不会把中间点改为 (50,-6)。", False),
    ("但仅把中间点从 (50,-24) 改为 (50,-6)，线性段保持原样。", False),
    ("但仅把中间点从 -24 改为 (50,-6)，线性段保持原样。", False),
])
def test_tuple_edit_exception_preserves_polarity_and_asserted_before_state(claim, expected):
    case = _coherent_context_notice("003-EXP22-C06")
    case["events"][-2]["item"]["text"] += claim
    assert _notice(case["events"], artifact=case["artifact"], before=case["before"]) is expected


@pytest.mark.parametrize("case_id", ["003-EXP22-C06", "007-EXP25-C06"])
@pytest.mark.parametrize("value,expected", [
    ("(-24 dB)", False), ("(-12 Hz)", False), ("（-24 dB）", False),
    ("(50,-12)", True), ("（50,-12 dB）", True), ("(-12 dB)", True),
    ("(50,-24)", False), ("(75,-12)", False), ("(50,-12 Hz)", False),
    ("(50,-12", False), ("(-12 dB", False), ("(50,-12))", False),
])
def test_historical_midpoint_claim_requires_complete_exact_old_value(case_id, value, expected):
    case = _coherent_context_notice(case_id)
    case["events"][-2]["item"]["text"] += f"当前中间点为 {value}。"
    assert _notice(case["events"], artifact=case["artifact"], before=case["before"]) is expected


def test_later_historical_conflict_cannot_borrow_a_valid_historical_tuple():
    case = _coherent_context_notice("003-EXP22-C06")
    case["events"][-2]["item"]["text"] += "当前中间点为 (50,-12)。当前中间点为 (-24 dB)。"
    assert not _notice(case["events"], artifact=case["artifact"], before=case["before"])


@pytest.mark.parametrize("case_id", ["003-EXP22-C06", "007-EXP25-C06"])
@pytest.mark.parametrize("origin", ["(50,-24", "（50,-12"])
def test_unclosed_origin_cannot_make_an_affirmative_midpoint_claim_disappear(case_id, origin):
    case = _coherent_context_notice(case_id)
    case["events"][-2]["item"]["text"] += f"但仅把中间点从 {origin} 改为 (0,-48)、(50,-6)、(100,0)，各段线性。"
    assert not _notice(case["events"], artifact=case["artifact"], before=case["before"])


@pytest.mark.parametrize("case_id", ["005-EXP22-C09", "007-EXP25-C06", "009-EXP25-C09", "010-EXP25-M05"])
def test_next_archived_notice_accounts_for_bound_owner_and_exact_effect(case_id):
    case = _next_context_notice(case_id)
    assert _notice(case["events"], artifact=case["artifact"], before=case["before"])


@pytest.mark.parametrize("case_id", ["005-EXP22-C09", "007-EXP25-C06", "009-EXP25-C09", "010-EXP25-M05"])
@pytest.mark.parametrize("defect", ["foreign_identity", "wrong_baseline", "generic", "late", "extra_action"])
def test_next_context_cannot_supply_foreign_generic_late_or_extra_changes(case_id, defect):
    case = _next_context_notice(case_id)
    post = case["events"][-2]
    if defect == "foreign_identity": post["item"]["text"] += "目标是 {AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}。"
    elif defect == "wrong_baseline":
        key = "stinger" if case_id.endswith("M05") else "owner"
        case["before"][key]["id"] = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
    elif defect == "generic": post["item"]["text"] = "预览通过，现在执行。"
    elif defect == "late": case["events"][-2:] = case["events"][-2:][::-1]
    else:
        post["item"]["text"] += "同时修改备注。" if case_id.endswith("C06") else "同时删除原效果。" if case_id.endswith("C09") else "同时设为 OtherTrigger。"
    assert not _notice(case["events"], artifact=case["artifact"], before=case["before"])


@pytest.mark.parametrize("defect", ["wrong_prefix", "foreign_owner", "wrong_name", "wrong_notes", "occupied_slot", "unproven_slot", "wrong_refs", "wrong_version"])
def test_checked_sound_discourse_cannot_authorize_a_different_legacy_effect(defect):
    case = _next_context_notice("005-EXP22-C09")
    post = case["events"][-2]["item"]
    plan = case["artifact"]["prepared_operation"]["verification_plan"]
    if defect == "wrong_prefix": post["text"] = post["text"].replace("44BD...", "AAAA...")
    elif defect == "foreign_owner": post["text"] = post["text"].replace("已核对的 Sound", "另一条 Sound")
    elif defect == "wrong_name": post["text"] = post["text"].replace("Expansion_EXP22-C09_NewGain", "AnotherGain")
    elif defect == "wrong_notes": post["text"] = post["text"].replace("Expansion C09 appended gain", "AnotherNote")
    elif defect == "occupied_slot": plan["pre_effect_references"]["@Effect2"] = plan["pre_effect_references"]["@Effect0"]
    elif defect == "unproven_slot": plan["placement"]["requires_proven_empty_slot"] = False
    elif defect == "wrong_refs": plan["pre_effect_references"]["@Effect0"] = None
    else:
        case["artifact"]["request"]["version"] = "2025.1"
        case["artifact"]["prepared_operation"]["version"] = "2025.1"
    assert not _notice(case["events"], artifact=case["artifact"], before=case["before"])


@pytest.mark.parametrize("defect", ["wrong_delta", "wrong_history", "wrong_endpoints", "missing_endpoint", "extra_endpoint", "wrong_order", "wrong_shape", "stale_shape", "wrong_count"])
def test_exact_retained_endpoint_claim_requires_the_sealed_numerical_curve(defect):
    case = _next_context_notice("007-EXP25-C06")
    post, earlier = case["events"][-2]["item"], case["events"][0]["item"]
    changes = {"wrong_delta": ("(50,−6)", "(50,−60)"), "wrong_history": ("(50,−12)", "(50,−24)"),
        "wrong_endpoints": ("(0,−48)", "(0,−20)"), "missing_endpoint": (" 与 (100,0)", ""),
        "extra_endpoint": ("与 (100,0)", "与 (100,0)、(75,-3)"),
        "wrong_order": ("(0,−48) 与 (100,0)", "(100,0) 与 (0,−48)")}
    if defect in changes: post["text"] = post["text"].replace(*changes[defect])
    elif defect == "wrong_shape": post["text"] += "各段非线性。"
    elif defect == "stale_shape": earlier["text"] = earlier["text"].replace("线性段", "非线性段")
    else: earlier["text"] = earlier["text"].replace("三个控制点", "四个控制点")
    assert not _notice(case["events"], artifact=case["artifact"], before=case["before"])


@pytest.mark.parametrize("case_id,original,replacement", [
    ("009-EXP25-C09", "指定的 Sound", "指定的 Sound OtherOwner"),
    ("009-EXP25-C09", "Expansion_EXP25-C09_NewGain", "AnotherGain"),
    ("010-EXP25-M05", "该 Stinger", "另一条 Stinger"),
    ("010-EXP25-M05", "Backup_Team_Arrives", "Bonus"),
])
def test_contextual_owner_status_cannot_mask_an_explicit_wrong_owner_or_effect(case_id, original, replacement):
    case = _next_context_notice(case_id)
    post = case["events"][-2]["item"]
    assert original in post["text"]
    post["text"] = post["text"].replace(original, replacement)
    assert not _notice(case["events"], artifact=case["artifact"], before=case["before"])


@pytest.mark.parametrize("owner", ["OtherOwner", "AnotherSound", "该 Sound 和 OtherOwner", "该 Sound 或另一条 Sound",
    "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"])
def test_each_additional_effect_owner_must_agree_with_the_sealed_source(owner):
    case = _next_context_notice("009-EXP25-C09")
    case["events"][-2]["item"]["text"] += f"另外向 {owner} 新增名为 Expansion_EXP25-C09_NewGain 的 effect。"
    assert not _notice(case["events"], artifact=case["artifact"], before=case["before"])


@pytest.mark.parametrize("claim,expected", [
    ("另外不向 OtherOwner 新增名为 Expansion_EXP25-C09_NewGain 的 effect。", True),
    ("另外向该 Sound 新增名为 Expansion_EXP25-C09_NewGain 的 effect。", True),
    ("该新增 effect 名为 Expansion_EXP25-C09_NewGain。", True),
    ("另外在 OtherOwner 上新增名为 Expansion_EXP25-C09_NewGain 的 effect。", False),
    ("另外新增名为 Expansion_EXP25-C09_NewGain 的 effect on OtherOwner。", False),
    ("另外新增名为 Expansion_EXP25-C09_NewGain 的 effect 到 OtherOwner。", False),
])
def test_explicit_owner_claims_are_distinct_from_omitted_owner_or_negated_preservation(claim, expected):
    case = _next_context_notice("009-EXP25-C09")
    case["events"][-2]["item"]["text"] += claim
    assert _notice(case["events"], artifact=case["artifact"], before=case["before"]) is expected


@pytest.mark.parametrize("owner", ["OtherOwner", "该 Stinger 和 OtherOwner", "{FB63DE7B-12AF-4A12-A836-FFAE0B4DD858}"])
def test_reference_source_cannot_inherit_a_foreign_named_or_target_guid_owner(owner):
    case = _next_context_notice("010-EXP25-M05")
    case["events"][-2]["item"]["text"] += f"另外将 {owner} 的 Trigger 引用设为 Backup_Team_Arrives。"
    assert not _notice(case["events"], artifact=case["artifact"], before=case["before"])


def test_reference_action_cannot_apply_the_right_target_to_a_foreign_possessive_owner():
    case = _next_context_notice("010-EXP25-M05")
    case["events"][-2]["item"]["text"] += "另外修改 OtherOwner 的 Trigger 引用为 Backup_Team_Arrives。"
    assert not _notice(case["events"], artifact=case["artifact"], before=case["before"])


@pytest.mark.parametrize("case_id", ["004-EXP22-C06", "012-EXP25-C09", "014-EXP25-M05"])
def test_initial_frozen_notices_resolve_uniquely_attested_context(case_id):
    case = _initial_context_notice(case_id)
    assert _notice(case["events"], artifact=case["artifact"], before=case["before"])


@pytest.mark.parametrize("case_id,defect", [
    ("004-EXP22-C06", "wrong_arrow"), ("004-EXP22-C06", "wrong_antecedent"),
    ("004-EXP22-C06", "ambiguous_point"), ("004-EXP22-C06", "wrong_scalar"),
    ("004-EXP22-C06", "wrong_shape"), ("004-EXP22-C06", "extra_point"),
    ("012-EXP25-C09", "wrong_name"), ("012-EXP25-C09", "wrong_notes"),
    ("012-EXP25-C09", "extra_change"), ("012-EXP25-C09", "negated"),
    ("014-EXP25-M05", "wrong_target"), ("014-EXP25-M05", "segment_change"),
    ("014-EXP25-M05", "negated"),
])
def test_contextual_notice_does_not_inherit_wrong_or_extra_effect_claims(case_id, defect):
    case = _initial_context_notice(case_id)
    post = next(event["item"] for event in case["events"] if event.get("original_index") == 27)
    if defect == "wrong_arrow":
        case["events"][0]["item"]["text"] = case["events"][0]["item"]["text"].replace("50→−6", "50→−60")
    elif defect == "wrong_antecedent": post["text"] = post["text"].replace("(50,−12)", "(100,0)")
    elif defect == "ambiguous_point": post["text"] = post["text"].replace("(50,−12)", "(50,−12) 和 (0,-48)")
    elif defect == "wrong_scalar": post["text"] = post["text"].replace("改为 −6", "改为 −60")
    elif defect == "wrong_shape": post["text"] = post["text"].replace("各段线性", "各段非线性")
    elif defect == "extra_point": post["text"] = post["text"].replace("改为 −6", "改为 −6，同时 (75,-3)")
    elif defect == "wrong_name": post["text"] = post["text"].replace("Expansion_EXP25-C09_NewGain", "AnotherGain")
    elif defect == "wrong_notes": post["text"] = post["text"].replace("Expansion C09 appended gain", "wrong note")
    elif defect == "extra_change": post["text"] += "同时修改该 Sound 音量为 -12。"
    elif defect == "wrong_target": post["text"] = post["text"].replace("Backup_Team_Arrives", "Bonus")
    elif defect == "segment_change": post["text"] += "音乐段改为 OtherSegment。"
    else: post["text"] = post["text"].replace("即将向该 Sound 新增", "不会向该 Sound 新增") if case_id.endswith("C09") else post["text"].replace("只会改动", "不会改动")
    assert not _notice(case["events"], artifact=case["artifact"], before=case["before"])


@pytest.mark.parametrize("case_id", ["012-EXP25-C09", "014-EXP25-M05"])
@pytest.mark.parametrize("defect", ["wrong_source", "wrong_verifier", "malformed_source", "foreign_id", "generic", "late"])
def test_type_pronoun_requires_unique_attested_roles_and_advance_effect(case_id, defect):
    case = _initial_context_notice(case_id)
    prepared, before = case["artifact"]["prepared_operation"], case["before"]
    key = "owner" if case_id.endswith("C09") else "stinger"
    plan_key = "target_id" if case_id.endswith("C09") else "object_id"
    post = next(event for event in case["events"] if event.get("original_index") == 27)
    if defect == "wrong_source": before[key]["id"] = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
    elif defect == "wrong_verifier": prepared["verification_plan"][plan_key] = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
    elif defect == "malformed_source": before[key] = [before[key]]
    elif defect == "foreign_id": post["item"]["text"] += "目标为 {AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}。"
    elif defect == "generic": post["item"]["text"] = "预览通过，现在处理。"
    else:
        post_index = case["events"].index(post)
        case["events"][post_index], case["events"][post_index + 1] = case["events"][post_index + 1], post
    assert not _notice(case["events"], artifact=case["artifact"], before=before)


@pytest.mark.parametrize("case_id", ["012-EXP25-C09", "014-EXP25-M05"])
@pytest.mark.parametrize("defect", ["request_disagrees", "prepared_disagrees", "later_contradiction", "ambiguous_binding"])
def test_contextual_notice_rejects_disagreement_and_later_contradictions(case_id, defect):
    case = _initial_context_notice(case_id)
    artifact, before = case["artifact"], case["before"]
    plugin = case_id.endswith("C09")
    if defect == "request_disagrees":
        artifact["request"]["arguments"]["target"]["value"] = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
    elif defect == "prepared_disagrees":
        state = artifact["prepared_operation"]["pre_state"]
        if plugin: state["plugin_creation_guard"]["descriptor"]["notes"] = "wrong note"
        else: state["target"]["name"] = "AnotherTrigger"
    elif defect == "ambiguous_binding":
        if plugin: artifact["prepared_operation"]["verification_plan"]["placement"]["replace_existing_allowed"] = True
        else: before["owner"]["@Stingers"].append(dict(before["owner"]["@Stingers"][0]))
    else:
        contradiction = "不会向该 Sound 新增插件。" if plugin else "不会改动该 MusicStinger 的 Trigger 引用。"
        case["events"].insert(-1, {"type": "item.completed", "item": {"type": "agent_message", "text": contradiction}})
    assert not _notice(case["events"], artifact=artifact, before=before)


@pytest.mark.parametrize("case_id,claim", [
    ("012-EXP25-C09", "同时修改该 Sound 的 Pitch 为 12。"),
    ("014-EXP25-M05", "同时修改该 MusicStinger 的 Probability 为 12。"),
    ("004-EXP22-C06", "同时修改该 Sound 的 Pitch 为 12。"),
    ("012-EXP25-C09", "同时删除原效果。"),
    ("012-EXP25-C09", "同时替换原效果。"),
    ("012-EXP25-C09", "同时移除原效果。"),
    ("014-EXP25-M05", "同时修改该 MusicStinger 的 NumSegmentAdvance 为 12。"),
    ("014-EXP25-M05", "同时修改 NumSegmentAdvance 为 2。"),
    ("014-EXP25-M05", "同时修改 Trigger 为 Bonus。"),
    ("014-EXP25-M05", "同时改动该 MusicStinger 的 Trigger 引用，目标为 Bonus。"),
    ("012-EXP25-C09", "同时新增一个名为 AnotherGain 的 effect。"),
])
@pytest.mark.parametrize("preserve", [False, True])
def test_contextual_notice_distinguishes_unapproved_field_changes_from_preservation(case_id, claim, preserve):
    case = _initial_context_notice(case_id)
    post = next(event["item"] for event in case["events"] if event.get("original_index") == 27)
    post["text"] += claim.replace("同时", "同时不", 1) if preserve else claim
    assert _notice(case["events"], artifact=case["artifact"], before=case["before"]) is preserve


def test_rtpc_context_accepts_independent_snapshot_row_permutations():
    case = _current_notice_case()
    case["preview_artifact"]["prepared_operation"]["verification_plan"]["before_rows"].reverse()
    assert _notice(case["events"], artifact=case["preview_artifact"], before=case["before_snapshot"])


def test_rtpc_reference_requires_previously_stated_correct_points():
    case = _current_notice_case("luna-high")
    post = next(event for event in case["events"] if event.get("original_index") == 27)
    assert not _notice([PREVIEW, post, EXECUTE], artifact=case["preview_artifact"], before=case["before_snapshot"])


@pytest.mark.parametrize("text", [
    "按上述预期执行，关系是 {AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}。",
    "将音量曲线改为上述指定线性点，关系是 {AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}。",
])
def test_rtpc_reference_cannot_override_foreign_identity(text):
    case = _current_notice_case()
    earlier = _message("将音量曲线设为 (0,-48)、(50,-6)、(100,0)，各段线性。")
    assert not _notice([earlier, PREVIEW, _message(text), EXECUTE],
        artifact=case["preview_artifact"], before=case["before_snapshot"])


@pytest.mark.parametrize("events", ["before", "after", "tool"])
def test_contextual_rtpc_keeps_advance_visible_message_boundary(events):
    case = _current_notice_case()
    message = next(event for event in case["events"] if event.get("original_index") == 25)
    sequence = {"before": [message, PREVIEW, EXECUTE], "after": [PREVIEW, EXECUTE, message],
        "tool": [PREVIEW, {"type": "item.completed", "item": {"type": "command_execution",
            "aggregated_output": message["item"]["text"]}}, EXECUTE]}[events]
    assert not _notice(sequence, artifact=case["preview_artifact"], before=case["before_snapshot"])


@pytest.mark.parametrize("text", ["将更新 Quiet 的轨道音量为 -6 dB。", "I will update Quiet with volume at -6 dB."])
def test_import_notice_accepts_equivalent_update_wording(text):
    assert _notice([PREVIEW, _message(text), EXECUTE])


@pytest.mark.parametrize("value,expected", [("−6", True), ("−6.0", True), ("+6", False),
    ("6", False), ("−60", False), ("−6.5", False)])
def test_numeric_notice_preserves_sign_and_exact_value(value, expected):
    assert _notice([PREVIEW, _message(f"将导入 Quiet，音量为 {value} dB。"), EXECUTE]) is expected


@pytest.mark.parametrize("text", ["正在更新进度。", "将更新 Full 的音量为 -6 dB。", "将更新 Quiet 的音量为 -60 dB。"])
def test_update_wording_does_not_relax_concrete_effect_obligations(text):
    assert not _notice([PREVIEW, _message(text), EXECUTE])


@pytest.mark.parametrize("text", ["将更新 Line_01 的 English(US) 素材。", "将更新 Line_01。", "Japanese 已核对，正在处理。"])
def test_update_notice_keeps_target_and_requested_language_obligations(text):
    artifact = {"request": {"operation": "audio.import", "arguments": {
        "imports": [{"object_path": r"\Voices\Line_01", "import_language": "Japanese"}]}}}
    assert not _notice([PREVIEW, _message(text), EXECUTE], artifact=artifact)


@pytest.mark.parametrize("after_preview,before_execute,expected", [
    (True, True, True), (False, True, False), (True, False, False),
])
def test_allow_notice_has_temporal_binding_without_fixed_prose(after_preview, before_execute, expected):
    records = [SimpleNamespace(command=command, argv=("python", "/tmp/skill/scripts/run.py", "gateway.py", command, "x"))
               for command in ("preview-from-draft", "execute")]
    preview = {"type": "item.completed", "item": {"type": "command_execution", "command": "preview-from-draft"}}
    execute = {"type": "item.started", "item": {"type": "command_execution", "command": "execute"}}
    message = {"type": "item.completed", "item": {"type": "agent_message", "text": "导入 Quiet，其轨道音量将改成 -6 dB，其余项保持现状。"}}
    events = [preview, message, execute] if after_preview else [message, preview, execute]
    if not before_execute:
        events = [preview, execute, message]
    result = SimpleNamespace(stdout="\n".join(json.dumps(event) for event in events))
    assert expansion_preview_notice(result, records, version="2025.1", execute_expected=True, preview_artifact=ARTIFACT, before_snapshot={}) is expected


def test_allow_notice_rejects_progress_only_message():
    records = [SimpleNamespace(command=command, argv=("python", "/tmp/skill/scripts/run.py", "gateway.py", command, "x"))
               for command in ("preview-from-draft", "execute")]
    events = [
        {"type": "item.completed", "item": {"type": "command_execution", "command": "preview-from-draft"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Working on it"}},
        {"type": "item.started", "item": {"type": "command_execution", "command": "execute"}},
    ]
    assert not expansion_preview_notice(SimpleNamespace(stdout="\n".join(json.dumps(event) for event in events)),
                                        records, version="2025.1", execute_expected=True, preview_artifact=ARTIFACT, before_snapshot={})


def _notice(events, *, artifact=ARTIFACT, before=None, execute_expected=True, version="2025.1"):
    records = [SimpleNamespace(command=command, argv=("python", "/tmp/skill/scripts/run.py", "gateway.py", command, "x"))
               for command in ("preview-from-draft", "execute")]
    return expansion_preview_notice(SimpleNamespace(stdout="\n".join(json.dumps(event) for event in events)),
        records, version=version, execute_expected=execute_expected,
        preview_artifact=artifact, before_snapshot=before or {})


def _message(text):
    return {"type": "item.completed", "item": {"type": "agent_message", "text": text}}


PREVIEW = {"type": "item.completed", "item": {"type": "command_execution", "command": "preview-from-draft"}}
EXECUTE = {"type": "item.started", "item": {"type": "command_execution", "command": "execute"}}


@pytest.mark.parametrize("text", [
    "I’ll create Quiet with its volume at -6 dB.",
    "Quiet will be imported at a volume of -6.0 dB; I’m proceeding with that preview.",
    "现在导入 Quiet，并把音量设置为 -6 dB。",
    "预览结果是新增 Quiet，音量为 -6 分贝，接下来执行。",
])
def test_notice_accepts_varied_expected_effect_summaries(text):
    assert _notice([PREVIEW, _message(text), EXECUTE])


@pytest.mark.parametrize("text", [
    "Working on it", "正在处理", "Preview approved; proceeding now.",
    "Quiet is ready; I’ll continue.", "I’ll import Quiet with volume at -60 dB.",
    "I’ll create Full with volume at -6 dB.",
])
def test_notice_rejects_generic_or_different_effect(text):
    assert not _notice([PREVIEW, _message(text), EXECUTE])


@pytest.mark.parametrize("earlier", [True, False])
def test_post_preview_reference_requires_previously_presented_expected_result(earlier):
    events = [_message("I’ll create Quiet with volume at -6 dB.")] if earlier else []
    assert _notice([*events, PREVIEW, _message("I’ll apply the expected changes above."), EXECUTE]) is earlier


def test_expected_effect_can_be_presented_across_separate_visible_messages():
    assert _notice([_message("I’ll create Quiet with volume at -6 dB."), PREVIEW,
                    _message("现在按上述预期结果执行。"), EXECUTE])


def test_ask_policy_summary_must_follow_preview_and_stop_before_execute():
    summary = _message("I’ll create Quiet with volume at -6 dB.")
    assert _notice([PREVIEW, summary], execute_expected=False)
    assert not _notice([summary, PREVIEW], execute_expected=False)
    assert not _notice([PREVIEW, summary, EXECUTE], execute_expected=False)


def test_tool_output_does_not_present_expected_result_to_user():
    assert not _notice([PREVIEW, {"type": "item.completed", "item": {
        "type": "command_execution", "command": "draft-inspect", "aggregated_output":
        "I’ll create Quiet with volume at -6 dB."}}, EXECUTE])


def test_notice_is_bound_to_sealed_selector_identity_and_effect_name():
    owner, control = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}", "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}"
    artifact = {"request": {"operation": "object.setRTPC", "arguments": {
        "object": {"kind": "id", "value": owner}, "control_input": {"kind": "id", "value": control},
        "property": "Volume", "points": [{"x": 0, "y": -24, "shape": "Linear"}]}}}
    before = {"owner": {"id": owner, "name": "Motor"}, "input": {"id": control, "name": "Speed"}}
    assert _notice([PREVIEW, _message("I’ll update Motor’s volume RTPC curve driven by Speed."), EXECUTE],
                   artifact=artifact, before=before)
    assert not _notice([PREVIEW, _message("I’ll update Motor’s volume RTPC curve driven by Distance."), EXECUTE],
                       artifact=artifact, before=before)


def test_absent_sealed_effect_fails_closed():
    assert not _notice([PREVIEW, _message("I’ll create Quiet with volume at -6 dB."), EXECUTE], artifact={})


@pytest.mark.parametrize("failure_kind,expected", [("infrastructure", "BLOCKED"), ("budget", "FAIL"), ("uncertain_execute", "INDETERMINATE")])
def test_expansion_returns_classified_failure_and_reconciles_only_after_broker_close(monkeypatch, tmp_path, failure_kind, expected):
    from tests.semantic.support import codex_task_runner_v3 as runner
    from tests.semantic.support import codex_expansion_broker_policy as policy_module
    from tests.semantic.support.codex_harness import CodexInfrastructureError, CodexInfrastructureFailure
    from tests.semantic.test_codex_expansion_broker_policy import make_policy, SKILL
    calls = []
    recorded_commands = []
    prepared = make_policy().prepared
    policy = policy_module.ExpansionBrokerPolicy(prepared=prepared, version="2025.1", skill_source=SKILL, scoped_paths={})
    class Broker:
        state_directory = tmp_path / "broker-state"
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            calls.append("broker-open")
            return self
        def __exit__(self, *_):
            calls.append("broker-closed-reaped")
        def model_environment_overrides(self):
            return {}
        def evidence(self):
            return SimpleNamespace(records=(), passed=False, as_dict=lambda **_: {"records": recorded_commands})
        def reconcile(self, *args, **kwargs):
            return SimpleNamespace(passed=True)
    class Task:
        thread_id = "failed-thread"
        def __init__(self, *args, **kwargs):
            self.budget = kwargs["agent_case_budget"]
            instructions = args[0].developer_instructions
            assert "allow_changes: announce edits; Execute only with distinct durable policy authorization" in instructions
            assert "only execution waits for confirmation" not in instructions
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def run_initial(self, *_args, **_kwargs):
            self.budget.start_turn(100)
            self.budget.finish_turn(701 if failure_kind != "infrastructure" else 101)
            if failure_kind == "uncertain_execute":
                from wwise_waapi.transactions import TransactionStore
                store = TransactionStore(Broker.state_directory)
                tx = "tx1-" + "7" * 20
                artifact = {"request": {"operation": "audio.import"}}
                preview = store.create_preview(tx, artifact)
                store.authorize_by_policy(tx, policy="allow_changes", authority=policy.gateway_module.POLICY_AUTHORIZATION_AUTHORITY)
                store.begin_execution(tx, expected_authorization="policy_authorized")
                policy.transaction_id = tx
                recorded_commands.append({"accepted": True, "gateway_arguments": ("execute", tx), "succeeded": False})
            if failure_kind != "infrastructure":
                raise TimeoutError("Agent budget expired after action")
            raise CodexInfrastructureError(CodexInfrastructureFailure("authentication", "No auth", True, False, 0),
                                           SimpleNamespace())
    monkeypatch.setattr(runner, "prepare_workspace_skill_install", lambda *args: SKILL)
    monkeypatch.setattr(runner, "CodexGatewayBroker", Broker)
    monkeypatch.setattr(runner, "CodexCliTask", Task)
    monkeypatch.setattr(policy_module, "ExpansionBrokerPolicy", lambda **kwargs: policy)
    monkeypatch.setattr(runner, "_archive_turn", lambda *args, **kwargs: None)
    def reconcile():
        assert calls[-1] == "broker-closed-reaped"
        calls.append("independent-read")
        return {"status": "completed", "child_reaped": True, "subprocesses_reaped": True, "snapshot": prepared.before, "elapsed_seconds": 0.1}
    options = SimpleNamespace(skill_source=SKILL, model="gpt-6.1-sol", reasoning_effort="medium",
        service_tier="default", campaign_inputs_sha256="a" * 64, codex_binary=tmp_path / "codex", auth_json=tmp_path / "auth",
        windows_powershell_core_host=None)
    outcome = runner.run_expansion_codex_task(unit=SimpleNamespace(unit_id="EXP25-M01", version="2025.1"),
        prepared=prepared, task_root=tmp_path / "task", options=options, runner_environment={}, scoped_paths={},
        reconcile_after_failure=reconcile)
    assert outcome["status"] == expected and outcome["passed"] is False
    if failure_kind == "infrastructure":
        assert outcome["infrastructure"]["category"] == "authentication"
    else:
        assert outcome["agent_seconds"] == 601 and outcome["infrastructure"] is None
    assert len(recorded_commands) == (1 if failure_kind == "uncertain_execute" else 0)
    assert calls == ["broker-open", "broker-closed-reaped", "independent-read"]
    oracle = json.loads((tmp_path / "task" / "expansion-oracle.json").read_text())
    assert oracle["reconciliation"]["child_reaped"] is True


def _preview_bound_midpoint_case():
    return json.loads((Path(__file__).parents[1] / "fixtures/semantic/expansion-preview-midpoint-719e3e0.json").read_text())


def test_actual_post_preview_scalar_delta_inherits_only_the_attested_full_plan():
    case = _preview_bound_midpoint_case()
    assert _notice(case["events"], artifact=case["artifact"], before=case["before"])


@pytest.mark.parametrize("replacement", ["按不可变预览把", "现在按预览将该关系的", "按预览把"])
def test_preview_bound_midpoint_notice_does_not_require_repeated_endpoints_or_shape(replacement):
    case = _preview_bound_midpoint_case()
    case["events"][-2]["item"]["text"] = case["events"][-2]["item"]["text"].replace("现在按预览把", replacement)
    assert _notice(case["events"], artifact=case["artifact"], before=case["before"])


@pytest.mark.parametrize("damage", [
    "no_plan", "wrong_plan", "wrong_plan_shape", "no_preview", "late", "no_reference", "wrong_history",
    "no_history", "wrong_midpoint", "wrong_unit", "missing_value", "wrong_owner", "foreign_guid",
    "no_identity", "no_notes", "wrong_notes", "no_sibling", "changed_sibling", "wrong_property",
    "wrong_control", "extra_endpoint", "wrong_shape", "extra_edit", "conflicting_scalar", "changed_preview",
])
def test_preview_reference_cannot_inherit_unknown_or_conflicting_rtpc_effects(damage):
    case = _preview_bound_midpoint_case()
    post = case["events"][-2]["item"]
    text = post["text"]
    if damage == "no_plan": case["events"].pop(0)
    elif damage == "wrong_plan": case["events"][0]["item"]["text"] = case["events"][0]["item"]["text"].replace("(50, -6)", "(50, -60)")
    elif damage == "wrong_plan_shape": case["events"][0]["item"]["text"] = case["events"][0]["item"]["text"].replace("线性", "非线性")
    elif damage == "no_preview": case["events"].pop(1)
    elif damage == "late": case["events"][-2:] = case["events"][-2:][::-1]
    elif damage == "changed_preview": case["artifact"]["prepared_operation"]["verification_plan"]["points"][1]["y"] = -60
    else:
        replacements = {
            "no_reference": ("现在按预览把", "现在把"),
            "wrong_history": ("`-12 dB`", "`-24 dB`"),
            "no_history": ("当前中点是 `-12 dB`。", ""),
            "wrong_midpoint": ("`-6 dB`", "`-60 dB`"),
            "wrong_unit": ("`-6 dB`", "`-6 Hz`"),
            "missing_value": ("`-6 dB`", "未知值"),
            "wrong_owner": ("现在按预览把", "现在按预览把 OtherSound 的"),
            "no_identity": ("身份与备注", "备注"),
            "no_notes": ("身份与备注", "身份"),
            "wrong_notes": ("Preserve volume association", "Different notes"),
            "no_sibling": ("另有一条 Voice Pitch／Time 曲线，预览显示它不在本次改动范围内。", ""),
            "changed_sibling": ("不在本次改动范围内", "也在本次改动范围内"),
            "wrong_property": ("把中点", "把 Pitch 曲线的中点"),
            "wrong_control": ("Volume／Rain_Intensity", "Volume／Time"),
        }
        if damage in replacements:
            old, new = replacements[damage]
            assert old in text
            text = text.replace(old, new)
        else:
            text += {
                "foreign_guid": "目标是 {AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}。",
                "extra_endpoint": "两端改为 (0,-20)、(100,0)。",
                "wrong_shape": "各段非线性。",
                "extra_edit": "同时修改备注。",
                "conflicting_scalar": "但仅把中间点改为 (-60 Hz)，线性段保持原样。",
            }[damage]
        post["text"] = text
    assert not _notice(case["events"], artifact=case["artifact"], before=case["before"])


@pytest.mark.parametrize("claim,expected", [
    ("同时修改 Lowpass 为 12。", False),
    ("同时删除另一条关系。", False),
    ("同时替换原曲线。", False),
    ("同时把端点改为 -20 dB。", False),
    ("不修改 Lowpass，也不删除另一条关系。", True),
    ("不替换原曲线。", True),
])
def test_preview_scalar_inheritance_accounts_for_every_additional_edit(claim, expected):
    case = _preview_bound_midpoint_case()
    case["events"][-2]["item"]["text"] += claim
    assert _notice(case["events"], artifact=case["artifact"], before=case["before"]) is expected


@pytest.mark.parametrize("claim,expected", [
    ("同时新增另一条关系。", False),
    ("同时移除另一条关系。", False),
    ("同时添加另一条关系。", False),
    ("同时创建另一条关系。", False),
    ("同时清空原曲线。", False),
    ("Also add another relationship.", False),
    ("Also create another relationship.", False),
    ("Also clear the curve.", False),
    ("不新增另一条关系。", True),
    ("不移除另一条关系。", True),
    ("不添加另一条关系。", True),
    ("不创建另一条关系。", True),
    ("不清空原曲线。", True),
    ("Do not add another relationship.", True),
    ("Do not create another relationship.", True),
    ("Do not clear the curve.", True),
    ("新增关系计数为零；移除关系计数为零。", True),
    ("No relationships were created or removed.", True),
])
def test_preview_scalar_inheritance_rejects_add_remove_clear_actions_not_preservation_or_status(claim, expected):
    case = _preview_bound_midpoint_case()
    case["events"][-2]["item"]["text"] += claim
    assert _notice(case["events"], artifact=case["artifact"], before=case["before"]) is expected


def _consolidated_notice_case(case_id):
    fixture = json.loads((Path(__file__).parents[1] / 'fixtures/semantic/expansion-contextual-notices-86b475e.json').read_text())
    return next(case for case in fixture['cases'] if case['case'] == case_id)


@pytest.mark.parametrize('case_id', ['004-EXP22-C09', '005-EXP25-C06', '006-EXP25-C08', '007-EXP25-C09', '008-EXP25-M05'])
def test_consolidated_actual_notice_has_one_attested_effect_before_execute(case_id):
    case = _consolidated_notice_case(case_id)
    assert _notice(case['events'], artifact=case['artifact'], before=case['before'])


@pytest.mark.parametrize('case_id', ['004-EXP22-C09', '005-EXP25-C06', '006-EXP25-C08', '007-EXP25-C09', '008-EXP25-M05'])
@pytest.mark.parametrize('damage', ['foreign_id', 'baseline', 'version', 'late', 'generic', 'extra_action'])
def test_consolidated_context_does_not_inherit_foreign_late_or_additional_changes(case_id, damage):
    case = _consolidated_notice_case(case_id)
    post = case['events'][-2]['item']
    if damage == 'foreign_id': post['text'] += '目标是 {AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}。'
    elif damage == 'baseline':
        key = 'attenuation' if case_id.endswith('C08') else 'stinger' if case_id.endswith('M05') else 'owner'
        case['before'][key]['id'] = '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}'
    elif damage == 'version': case['artifact']['request']['version'] = '2024.1'
    elif damage == 'late': case['events'][-2:] = case['events'][-2:][::-1]
    elif damage == 'generic': post['text'] = '预览已授权，现在执行。'
    else: post['text'] += '同时清空另一条曲线。'
    assert not _notice(case['events'], artifact=case['artifact'], before=case['before'])


@pytest.mark.parametrize('case_id', ['004-EXP22-C09', '007-EXP25-C09'])
@pytest.mark.parametrize('damage', ['foreign_owner', 'extra_owner', 'wrong_name', 'wrong_notes', 'noun_edit', 'pronoun_without_antecedent'])
def test_effect_chain_location_and_request_nouns_are_not_new_owner_or_edit_authority(case_id, damage):
    case = _consolidated_notice_case(case_id)
    post = case['events'][-2]['item']
    if damage == 'foreign_owner': post['text'] = post['text'].replace('其效果链末尾', 'OtherSound 的效果链末尾').replace('该 Sound 下', 'OtherSound 下')
    elif damage == 'extra_owner': post['text'] += '另外在 OtherSound 下新增 Wwise Gain 效果器。'
    elif damage == 'wrong_name': post['text'] = post['text'].replace('NewGain', 'OtherGain')
    elif damage == 'wrong_notes': post['text'] = post['text'].replace('Expansion C09 appended gain', 'Different notes')
    elif damage == 'noun_edit': post['text'] += '本次修改请求，随后修改 Lowpass 为 12。'
    else:
        post['text'] = post['text'].replace('目标已核实为指定 GUID 对应的 Sound。', '').replace('该 Sound 下', '其效果链末尾')
    assert not _notice(case['events'], artifact=case['artifact'], before=case['before'])


@pytest.mark.parametrize('damage', ['old_value', 'old_x', 'new_value', 'new_x', 'final_value', 'final_order', 'final_missing',
    'final_extra', 'wrong_unit', 'shape', 'foreign_property', 'extra_edit', 'unclosed', 'conflicting_final'])
def test_coherent_midpoint_delta_and_full_final_curve_validate_every_numeric_and_edit_claim(damage):
    case = _consolidated_notice_case('005-EXP25-C06')
    post = case['events'][-2]['item']
    replacements = {
        'old_value': ('(50,-12)', '(50,-24)'), 'old_x': ('(50,-12)', '(75,-12)'),
        'new_value': ('将改为 (50,-6)', '将改为 (50,-60)'), 'new_x': ('将改为 (50,-6)', '将改为 (75,-6)'),
        'final_value': ('曲线为 (0,-48)、(50,-6)、(100,0)', '曲线为 (0,-48)、(50,-60)、(100,0)'),
        'final_order': ('曲线为 (0,-48)、(50,-6)、(100,0)', '曲线为 (50,-6)、(0,-48)、(100,0)'),
        'final_missing': ('曲线为 (0,-48)、(50,-6)、(100,0)', '曲线为 (0,-48)、(50,-6)'),
        'final_extra': ('曲线为 (0,-48)、(50,-6)、(100,0)', '曲线为 (0,-48)、(50,-6)、(75,-3)、(100,0)'),
        'wrong_unit': ('将改为 (50,-6)', '将改为 (50,-6 Hz)'),
        'shape': ('各段线性', '各段非线性'), 'foreign_property': ('提交后曲线为', 'Pitch 提交后曲线为'),
        'unclosed': ('(50,-12)', '(50,-12'),
    }
    if damage in replacements:
        old, new = replacements[damage]
        assert old in post['text']
        post['text'] = post['text'].replace(old, new)
    else: post['text'] += '同时修改 Lowpass 为 12。' if damage == 'extra_edit' else '最终曲线为 (0,-20)、(50,-6)、(100,0)，各段线性。'
    assert not _notice(case['events'], artifact=case['artifact'], before=case['before'])


@pytest.mark.parametrize('damage', ['source', 'shape', 'kind', 'point', 'order', 'unit', 'foreign_owner', 'extra_edit'])
def test_owned_custom_linear_points_phrase_is_exactly_the_sealed_attenuation_effect(damage):
    case = _consolidated_notice_case('006-EXP25-C08')
    post = case['events'][-2]['item']
    old, new = {
        'source': ('自定义', 'project'), 'shape': ('线性点', '非线性点'), 'kind': ('干声音量', 'spread'),
        'point': ('(50.0, -12)', '(50.0, -24)'), 'order': ('(0.0, 0)、(50.0, -12)', '(50.0, -12)、(0.0, 0)'),
        'unit': ('(50.0, -12)', '(50.0, -12 Hz)'), 'foreign_owner': ('指定衰减对象', 'OtherAttenuation'),
        'extra_edit': ('我现在执行', '同时修改 Pitch 为 12。我现在执行'),
    }[damage]
    assert old in post['text']
    post['text'] = post['text'].replace(old, new)
    assert not _notice(case['events'], artifact=case['artifact'], before=case['before'])


@pytest.mark.parametrize('case_id', ['004-EXP22-C09', '007-EXP25-C09'])
def test_explicit_foreign_source_claim_cannot_be_overridden_by_a_later_pronoun(case_id):
    case = _consolidated_notice_case(case_id)
    case['events'][-2]['item']['text'] += '目标已核实为 OtherSound。'
    assert not _notice(case['events'], artifact=case['artifact'], before=case['before'])


@pytest.mark.parametrize('replacement', ['(50,-12 dB)，将改为 (50,-6 dB)', '(50,-12)，将改为 -6 dB'])
def test_coherent_final_plan_accepts_quantity_compatible_midpoint_notation(replacement):
    case = _consolidated_notice_case('005-EXP25-C06')
    post = case['events'][-2]['item']
    post['text'] = post['text'].replace('(50,-12)，将改为 (50,-6)', replacement)
    assert _notice(case['events'], artifact=case['artifact'], before=case['before'])


@pytest.mark.parametrize('replacement,expected', [
    ('不会更新该 RTPC 关系。', False), ('不修改 Voice Volume 曲线。', False),
    ('不会更新 Rain_Intensity 关系。', False), ('', False),
    ('当前中间点是 (50,-12)，将改为 (50,-6)。不修改 Voice Pitch/Time 曲线。', True),
    ('当前中间点是 (50,-12)，将改为 (50,-6)。不修改关系身份与备注。', True),
])
def test_exact_final_curve_requires_affirmative_target_edit_not_negated_or_missing_edit(replacement, expected):
    case = _consolidated_notice_case('005-EXP25-C06')
    post = case['events'][-2]['item']
    post['text'] = post['text'].replace('当前中间点是 (50,-12)，将改为 (50,-6)。', replacement)
    assert _notice(case['events'], artifact=case['artifact'], before=case['before']) is expected


def _coherent_curve_case(old, new):
    case = _consolidated_notice_case('005-EXP25-C06')
    def points(values): return [{'x': x, 'y': y, 'shape': 'Linear'} for x, y in values]
    case['artifact']['request']['arguments']['points'] = points(new)
    prepared = case['artifact']['prepared_operation']
    prepared['verification_plan']['points'] = points(new)
    for rows in (case['before']['rtpcs'].values(), prepared['pre_state']['rtpc_snapshot']['rows'],
                 prepared['verification_plan']['before_rows']):
        for row in rows:
            if row['@PropertyName'] == 'Volume': row['@Curve']['points'] = points(old)
    return case


@pytest.mark.parametrize('old,new', [
    ([(0,-12)], [(0,-6)]),
    ([(0,-48),(50,-12)], [(0,-48),(50,-6)]),
    ([(0,-48),(50,-12),(100,0)], [(0,-20),(50,-6),(100,0)]),
])
def test_coherent_middle_promotion_requires_unique_three_point_single_middle_y_edit(old, new):
    case = _coherent_curve_case(old, new)
    middle = min(1, len(old)-1)
    final = '、'.join(f'({x},{y})' for x,y in new)
    case['events'][-2]['item']['text'] = (f'Voice Volume/Rain_Intensity 关系及备注保持原样。当前中间点是 ({old[middle][0]},{old[middle][1]})，'
        f'将改为 ({new[middle][0]},{new[middle][1]})。提交后曲线为 {final}，各段线性。')
    assert not _notice(case['events'], artifact=case['artifact'], before=case['before'])


def test_ordinary_exact_full_curve_notice_remains_valid_for_one_point_edit():
    case = _coherent_curve_case([(0,-12)], [(0,-6)])
    case['events'][-2]['item']['text'] = '将 Voice Volume/Rain_Intensity 曲线设为 (0,-6)，各段线性。'
    assert _notice(case['events'], artifact=case['artifact'], before=case['before'])


def _grammatical_role_case(case_id):
    fixture = json.loads((Path(__file__).parents[1] / 'fixtures/semantic/expansion-contextual-notices-fa51197.json').read_text())
    return next(case for case in fixture['cases'] if case['case'] == case_id)


@pytest.mark.parametrize('case_id', ['002-EXP22-C08', '003-EXP22-C09', '005-EXP25-C08', '006-EXP25-C09', '007-EXP25-M05'])
def test_actual_notice_grammatical_roles_match_one_sealed_primary_effect(case_id):
    case = _grammatical_role_case(case_id)
    assert _notice(case['events'], artifact=case['artifact'], before=case['before'], version=case['artifact']['request']['version'])


def _grammatical_notice(case):
    return _notice(case['events'], artifact=case['artifact'], before=case['before'], version=case['artifact']['request']['version'])


@pytest.mark.parametrize('case_id', ['002-EXP22-C08', '003-EXP22-C09', '005-EXP25-C08', '006-EXP25-C09', '007-EXP25-M05'])
@pytest.mark.parametrize('damage', ['foreign_id', 'baseline', 'version', 'late', 'generic', 'extra_change', 'noun_only', 'noun_then_edit'])
def test_grammatical_role_composition_never_invents_identity_authority_or_additional_edits(case_id, damage):
    case = _grammatical_role_case(case_id)
    post = case['events'][-2]['item']
    if damage == 'foreign_id': post['text'] += '目标是 {AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}。'
    elif damage == 'baseline':
        key = 'attenuation' if case_id.endswith('C08') else 'stinger' if case_id.endswith('M05') else 'owner'
        case['before'][key]['id'] = '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}'
    elif damage == 'version': case['artifact']['prepared_operation']['version'] = '2024.1'
    elif damage == 'late': case['events'][-2:] = case['events'][-2:][::-1]
    elif damage == 'generic': post['text'] = '预览已授权，现在执行。'
    elif damage == 'noun_only': post['text'] = '预览已按策略获得此项变更的独立授权。现在执行这一项修改。'
    elif damage == 'extra_change': post['text'] += '同时清空另一对象。'
    else: post['text'] += '现在执行这一项修改，随后修改 Lowpass 为 12。'
    assert not _grammatical_notice(case)


@pytest.mark.parametrize('case_id', ['002-EXP22-C08', '005-EXP25-C08'])
@pytest.mark.parametrize('damage', ['wrong_owner', 'two_owners', 'wrong_field', 'wrong_source', 'wrong_point', 'wrong_unit', 'wrong_shape', 'extra_point'])
def test_attenuation_owner_field_and_value_clauses_remain_one_exact_effect(case_id, damage):
    case = _grammatical_role_case(case_id)
    post = case['events'][-2]['item']
    if damage == 'wrong_owner': post['text'] = post['text'].replace('该衰减对象', 'OtherOwner').replace('指定衰减对象', 'OtherOwner')
    elif damage == 'two_owners': post['text'] = post['text'].replace('该衰减对象', '该衰减对象和 OtherOwner').replace('指定衰减对象', '指定衰减对象和 OtherOwner')
    elif damage == 'wrong_field': post['text'] = post['text'].replace('volume-dry', 'spread').replace('干声音量', 'spread')
    elif damage == 'wrong_source': post['text'] = post['text'].replace('custom', 'project').replace('自定义', 'project')
    elif damage == 'wrong_point': post['text'] = post['text'].replace('-12.0', '-60.0')
    elif damage == 'wrong_unit': post['text'] = post['text'].replace('-12.0 dB', '-12.0 Hz').replace('(50.0, -12.0)', '(50.0, -12.0 Hz)')
    elif damage == 'wrong_shape': post['text'] = post['text'].replace('线性', '非线性')
    else: post['text'] += '另有点 (75,-24)。'
    assert not _grammatical_notice(case)


@pytest.mark.parametrize('replacement', [
    '；设置为自定义', '，OtherOwner 的干声音量设置为自定义',
    '，它和 OtherOwner 设置为自定义', '，其他对象也设置为自定义',
])
def test_attenuation_subject_can_cross_only_one_adjacent_comma_without_a_new_owner(replacement):
    case = _grammatical_role_case('005-EXP25-C08')
    post = case['events'][-2]['item']
    post['text'] = post['text'].replace('，设置为自定义', replacement)
    assert not _grammatical_notice(case)


@pytest.mark.parametrize('case_id', ['003-EXP22-C09', '006-EXP25-C09'])
@pytest.mark.parametrize('damage', ['owner', 'name', 'notes', 'kind', 'description_then_edit', 'description_only', 'conflicting_notes'])
def test_effect_creation_description_nouns_cannot_hide_foreign_or_conflicting_effects(case_id, damage):
    case = _grammatical_role_case(case_id)
    post = case['events'][-2]['item']
    if damage == 'owner': post['text'] = post['text'].replace('该 Sound', 'OtherSound').replace('该 `Sound`', 'OtherSound')
    elif damage == 'name': post['text'] = post['text'].replace('NewGain', 'OtherGain')
    elif damage == 'notes': post['text'] = post['text'].replace('Expansion C09 appended gain', 'Different notes')
    elif damage == 'kind': post['text'] = post['text'].replace('效果器', 'Source')
    elif damage == 'description_then_edit': post['text'] += '预览采用的是追加效果器的修改，随后删除另一个对象。'
    elif damage == 'description_only': post['text'] = '预览采用的是追加效果器的修改，并获得此项变更的独立授权。'
    else: post['text'] += '新效果器备注为“Different notes”。'
    assert not _grammatical_notice(case)


@pytest.mark.parametrize('verb', ['创建', '新增', '添加', '插入', '追加'])
def test_creation_semantic_verbs_share_the_attested_create_only_plugin_lane(verb):
    case = _grammatical_role_case('006-EXP25-C09')
    post = case['events'][-2]['item']
    post['text'] = post['text'].replace('创建一个', verb + '一个')
    assert _grammatical_notice(case)


@pytest.mark.parametrize('damage', ['owner', 'field', 'value', 'extra_subject', 'noun_then_edit'])
def test_reference_execute_summary_noun_does_not_supply_or_broaden_primary_effect(damage):
    case = _grammatical_role_case('007-EXP25-M05')
    post = case['events'][-2]['item']
    if damage == 'owner': post['text'] = post['text'].replace('该 Stinger', 'OtherStinger')
    elif damage == 'field': post['text'] = post['text'].replace('`Trigger`', '`Segment`')
    elif damage == 'value': post['text'] = post['text'].replace('Backup_Team_Arrives', 'OtherTrigger')
    elif damage == 'extra_subject': post['text'] += '同时把 OtherStinger 的 Trigger 设为 Backup_Team_Arrives。'
    else: post['text'] += '执行这一项改动，随后设为 OtherTrigger。'
    assert not _grammatical_notice(case)


@pytest.mark.parametrize('owner,expected', [
    ('OtherSound', False), ('{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}', False),
    ('该 Sound', True), ('此对象', True),
])
def test_operation_description_noun_validates_its_explicit_owner_before_exemption(owner, expected):
    case = _grammatical_role_case('006-EXP25-C09')
    case['events'][-2]['item']['text'] += f'在 {owner} 上采用的是追加效果器的修改。'
    assert _grammatical_notice(case) is expected


@pytest.mark.parametrize('owner,field,expected', [
    ('OtherOwner', '干声音量曲线', False), ('该对象和 OtherOwner', '干声音量曲线', False),
    ('{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}', '干声音量曲线', False),
    ('该衰减对象', 'spread 曲线', False), ('该衰减对象', 'Pitch 曲线', False),
    ('该衰减对象', '干声音量曲线', True), ('指定衰减对象', 'volume-dry 曲线', True),
])
def test_recognized_target_subject_rejects_contradictions_even_without_a_new_action(owner, field, expected):
    case = _grammatical_role_case('005-EXP25-C08')
    case['events'][-2]['item']['text'] += f'目标是 {owner} 的{field}。'
    assert _grammatical_notice(case) is expected


@pytest.mark.parametrize('case_id,claim', [
    ('006-EXP25-C09', '预览获得此项变更的独立授权。'),
    ('006-EXP25-C09', '不在 OtherSound 上新增效果器。'),
    ('005-EXP25-C08', '不修改 OtherOwner 的干声音量曲线。'),
    ('005-EXP25-C08', '其他对象不在本次变更范围。'),
])
def test_unrelated_negated_preservation_and_ownerless_status_do_not_assert_a_new_target(case_id, claim):
    case = _grammatical_role_case(case_id)
    case['events'][-2]['item']['text'] += claim
    assert _grammatical_notice(case)


@pytest.mark.parametrize('case_id', ['006-EXP25-C09', '007-EXP25-M05'])
@pytest.mark.parametrize('frame', ['execution', 'authorization', 'request'])
@pytest.mark.parametrize('owner_kind,expected', [
    ('foreign_name', False), ('foreign_guid', False), ('ambiguous', False),
    ('attested_name', True), ('attested_guid', True), ('omitted', True),
])
def test_all_planned_change_noun_frames_validate_explicit_owner_before_exemption(case_id, frame, owner_kind, expected):
    case = _grammatical_role_case(case_id)
    primary = '该 Sound' if case_id.endswith('C09') else '该 Stinger'
    identifier = case['before']['owner']['id'] if case_id.endswith('C09') else case['before']['stinger']['id']
    owner = {'foreign_name': 'OtherOwner', 'foreign_guid': '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}',
             'ambiguous': primary + ' 和 OtherOwner', 'attested_name': primary,
             'attested_guid': identifier, 'omitted': None}[owner_kind]
    prefix = '' if owner is None else f'在 {owner} 上'
    noun = {'execution': '执行此项修改。', 'authorization': '获得此项变更的独立授权。', 'request': '本次修改请求。'}[frame]
    case['events'][-2]['item']['text'] += prefix + noun
    assert _grammatical_notice(case) is expected


@pytest.mark.parametrize('claim', ['不在 OtherOwner 上执行此项修改。', '不会向 OtherOwner 新增效果器。'])
def test_negated_foreign_noun_or_action_is_preservation_not_an_explicit_owner_assertion(claim):
    case = _grammatical_role_case('006-EXP25-C09')
    case['events'][-2]['item']['text'] += claim
    assert _grammatical_notice(case)


def _expected_state_case(case_id):
    fixture = json.loads((Path(__file__).parents[1] / 'fixtures/semantic/expansion-expected-state-notices-db82de6.json').read_text())
    return next(case for case in fixture['cases'] if case['case'] == case_id)


@pytest.mark.parametrize('case_id', ['002-EXP22-C08', '003-EXP22-C09'])
def test_actual_prospective_expected_state_and_authorization_roles_match_the_owned_preview(case_id):
    assert _grammatical_notice(_expected_state_case(case_id))


@pytest.mark.parametrize('damage', ['current', 'history', 'generic', 'no_intent', 'refusal', 'foreign_owner', 'ambiguous_owner',
    'wrong_kind', 'wrong_source', 'wrong_point', 'wrong_order', 'wrong_shape', 'wrong_count', 'wrong_unit',
    'unclosed_point', 'extra_point', 'extra_action', 'extra_create', 'extra_write', 'late'])
def test_prospective_attenuation_description_requires_complete_bound_effect_and_temporal_intent(damage):
    case = _expected_state_case('002-EXP22-C08')
    post = case['events'][-2]['item']
    replacements = {
        'current': ('预览已显示仅向', '当前状态显示向'), 'history': ('预览已显示仅向', '此前已经向'),
        'no_intent': ('我现在执行', '我现在等待'), 'refusal': ('仅向该衰减对象提交', '不向该衰减对象提交'),
        'foreign_owner': ('该衰减对象', 'OtherOwner'), 'ambiguous_owner': ('该衰减对象', '该衰减对象和 OtherOwner'),
        'wrong_kind': ('干声音量', 'spread'), 'wrong_source': ('自定义来源', 'project 来源'),
        'wrong_point': ('(50.0, -12)', '(50.0, -60)'), 'wrong_order': ('(0.0, 0)`、`(50.0, -12)', '(50.0, -12)`、`(0.0, 0)'),
        'wrong_shape': ('线性', '非线性'), 'wrong_count': ('三个', '四个'), 'wrong_unit': (' dB；', ' Hz；'),
        'unclosed_point': ('(50.0, -12)', '(50.0, -12'),
    }
    if damage in replacements:
        old, new = replacements[damage]
        assert old in post['text']
        post['text'] = post['text'].replace(old, new)
    elif damage == 'generic': post['text'] = '预览已授权，现在执行。'
    elif damage == 'late': case['events'][-2:] = case['events'][-2:][::-1]
    else: post['text'] += {'extra_point': '另外有点 (75,-24)。', 'extra_action': '同时修改 Pitch 为 12。',
                          'extra_create': '同时创建另一个对象。', 'extra_write': '同时写入 Pitch 为 12。'}[damage]
    assert not _grammatical_notice(case)


@pytest.mark.parametrize('frame,count,expected', [
    ('预览已确认：仅向', '3个', True), ('预览已表明只对', '三', True),
    ('预览已限定仅向', '3', True), ('预览已显示仅向', '30个', False),
    ('预览已显示仅向', '三十个', False), ('预览已显示仅向', '若干', False),
])
def test_prospective_description_count_and_frame_roles_are_general_but_closed(frame, count, expected):
    case = _expected_state_case('002-EXP22-C08')
    post = case['events'][-2]['item']
    post['text'] = post['text'].replace('预览已显示仅向', frame).replace('三个', count)
    assert _grammatical_notice(case) is expected


@pytest.mark.parametrize('owner,expected', [('OtherSound', False), ('该 Sound 和 OtherSound', False),
    ('{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}', False), ('该 Sound', True), ('', True)])
def test_provider_authorization_noun_still_validates_its_explicit_owner(owner, expected):
    case = _expected_state_case('003-EXP22-C09')
    prefix = '' if not owner else f'在 {owner} 上'
    case['events'][-2]['item']['text'] += prefix + '为此项变更提供独立授权。'
    assert _grammatical_notice(case) is expected


@pytest.mark.parametrize('damage', ['name', 'notes', 'foreign_owner', 'extra_write', 'noun_only', 'late'])
def test_creation_descriptor_and_provider_noun_require_one_independent_primary_effect(damage):
    case = _expected_state_case('003-EXP22-C09')
    post = case['events'][-2]['item']
    if damage == 'name': post['text'] = post['text'].replace('NewGain', 'OtherGain')
    elif damage == 'notes': post['text'] = post['text'].replace('Expansion C09 appended gain', 'Different notes')
    elif damage == 'foreign_owner': post['text'] = post['text'].replace('该 Sound', 'OtherSound')
    elif damage == 'extra_write': post['text'] += '同时写入 Pitch 为 12。'
    elif damage == 'noun_only': post['text'] = '当前策略为这项变更提供独立授权，我现在执行并核验。'
    else: case['events'][-2:] = case['events'][-2:][::-1]
    assert not _grammatical_notice(case)


@pytest.mark.parametrize('claim', ['我不会执行这项修改。', '不应用此项变更。', '不会执行该预览。'])
def test_prospective_expected_state_cannot_survive_a_later_requested_execution_refusal(claim):
    case = _expected_state_case('002-EXP22-C08')
    case['events'][-2]['item']['text'] += claim
    assert not _grammatical_notice(case)


def test_sealed_note_write_cannot_target_another_named_plugin():
    case = _expected_state_case('003-EXP22-C09')
    post = case['events'][-2]['item']
    post['text'] = post['text'].replace('并写入备注', '并 OtherGain 的写入备注')
    assert not _grammatical_notice(case)


@pytest.mark.parametrize('separator', ['，', '，并', '；', '并'])
@pytest.mark.parametrize('owner_kind,expected', [('foreign', False), ('foreign_guid', False), ('ambiguous', False),
    ('source', False), ('old_effect', False), ('new_effect', True)])
def test_coordinated_note_write_keeps_full_owner_frame_evidence(separator, owner_kind, expected):
    case = _expected_state_case('003-EXP22-C09')
    owner = {
        'foreign': 'OtherSound', 'foreign_guid': '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}',
        'ambiguous': '该 Sound 和 OtherSound', 'source': '该 Sound',
        'old_effect': case['before']['entries'][0]['effect']['name'],
        'new_effect': case['artifact']['request']['arguments']['plugin']['name'],
    }[owner_kind]
    case['events'][-2]['item']['text'] += f'在 {owner} 上{separator}写入备注“Expansion C09 appended gain”。'
    assert _grammatical_notice(case) is expected


@pytest.mark.parametrize('claim,expected', [
    ('写入备注“Expansion C09 appended gain”。', True),
    ('该效果器的写入备注“Expansion C09 appended gain”。', True),
    ('在 OtherSound 上向该 Sound，写入备注“Expansion C09 appended gain”。', False),
    ('不在 OtherSound 上写入备注“Expansion C09 appended gain”。', True),
    ('在该 Sound 上新增名为 Expansion_EXP22-C09_NewGain 的效果器，并写入备注“Expansion C09 appended gain”。', True),
])
def test_note_write_full_owner_evidence_and_local_qualifier_are_both_required(claim, expected):
    case = _expected_state_case('003-EXP22-C09')
    case['events'][-2]['item']['text'] += claim
    assert _grammatical_notice(case) is expected


def _attested_frame_case(case_id):
    fixture = json.loads((Path(__file__).parents[1] / 'fixtures/semantic/expansion-attested-frame-notices-492c30a.json').read_text())
    return next(case for case in fixture['cases'] if case['case'] == case_id)


@pytest.mark.parametrize('case_id', ['003-EXP22-C09', '004-EXP25-C08'])
def test_actual_identity_attestation_and_owned_preview_effect_frame(case_id):
    assert _grammatical_notice(_attested_frame_case(case_id))


@pytest.mark.parametrize('case_id', ['003-EXP22-C09', '004-EXP25-C08'])
@pytest.mark.parametrize('damage', ['foreign_id', 'wrong_type', 'interposed_owner', 'foreign_identity',
    'ambiguous_identity', 'refusal', 'extra_action', 'extra_owner_action', 'late', 'generic'])
def test_attested_preview_frames_preserve_identity_polarity_and_remaining_claims(case_id, damage):
    case = _attested_frame_case(case_id)
    post = case['events'][1]['item']
    text = post['text']
    if damage == 'foreign_id': text += '目标为 {AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}。'
    elif damage == 'wrong_type': text = text.replace('Sound', 'ActorMixer').replace('Attenuation', 'Sound')
    elif damage == 'interposed_owner': text = text.replace('。预览', '。目标是 OtherOwner。预览')
    elif damage == 'foreign_identity':
        text = text.replace('指定路径下的 `Sound`', 'OtherSound 路径下的 `Sound`').replace(
            '`Expansion_EXP25-C08_Attenuation`', '`OtherOwner`')
    elif damage == 'ambiguous_identity':
        text = text.replace('指定路径下的 `Sound`', '指定路径下的 `Sound` 和 OtherSound').replace(
            '`Expansion_EXP25-C08_Attenuation`', '`Expansion_EXP25-C08_Attenuation` 和 OtherOwner')
    elif damage == 'refusal': text = text.replace('预览将新增', '预览不会新增').replace('只调用其', '不会调用其')
    elif damage == 'extra_action': text += '同时修改 Pitch 为 12。'
    elif damage == 'extra_owner_action': text += '在 OtherOwner 上新增另一个效果。'
    elif damage == 'late': case['events'][1:] = case['events'][1:][::-1]
    elif damage == 'generic': text = '已核对目标，预览已授权，我现在执行。'
    post['text'] = text
    assert not _grammatical_notice(case)


@pytest.mark.parametrize('old,new', [
    ('我现在执行', '我现在等待'), ('自定义源', 'project 源'), ('线性点', '非线性点'),
    ('(50.0, -12.0)', '(50.0, -60.0)'), ('(50.0, -12.0)', '(50.0, -12.0 Hz)'),
    ('(50.0, -12.0)', '(50.0, -12.0'), ('`(50.0, -12.0)`、', ''),
    ('只调用其', '只调用 OtherOwner 的'), ('干声音量', 'spread'),
    ('预览确认本次', '当前状态确认本次'), ('预览确认本次', '此前已确认本次'),
])
def test_expected_curve_frame_requires_complete_prospective_owned_effect(old, new):
    case = _attested_frame_case('004-EXP25-C08')
    post = case['events'][1]['item']
    assert old in post['text']
    post['text'] = post['text'].replace(old, new)
    assert not _grammatical_notice(case)


@pytest.mark.parametrize('insert', ['预览已授权。', '预览仍待确认。目标是 OtherOwner。'])
def test_identity_inheritance_cannot_skip_an_intervening_sentence(insert):
    case = _attested_frame_case('003-EXP22-C09')
    post = case['events'][1]['item']
    post['text'] = post['text'].replace('。预览将新增', '。' + insert + '预览将新增')
    assert not _grammatical_notice(case)


@pytest.mark.parametrize('case_id', ['003-EXP22-C09', '004-EXP25-C08'])
@pytest.mark.parametrize('claim', ['我不会执行该预览。', '我不执行该预览。', '现在不执行该预览。',
    '我暂不执行本次修改。', '我并非现在执行该预览。'])
def test_normalized_expected_frames_reject_primary_execution_refusal(case_id, claim):
    case = _attested_frame_case(case_id)
    case['events'][1]['item']['text'] += claim
    assert not _grammatical_notice(case)


@pytest.mark.parametrize('case_id', ['003-EXP22-C09', '004-EXP25-C08'])
@pytest.mark.parametrize('replacement', ['我现在等待', '我此前已执行', '我不会执行'])
def test_normalized_expected_frames_require_current_prospective_intent(case_id, replacement):
    case = _attested_frame_case(case_id)
    post = case['events'][1]['item']
    assert '我现在执行' in post['text']
    post['text'] = post['text'].replace('我现在执行', replacement)
    assert not _grammatical_notice(case)


@pytest.mark.parametrize('case_id,old,new', [
    ('003-EXP22-C09', '核对确认', '已核对'),
    ('003-EXP22-C09', '核对确认', '已核对确认'),
    ('003-EXP22-C09', '，且 GUID', '、且 GUID'),
    ('004-EXP25-C08', '当前绑定已按', '该对象已按'),
    ('004-EXP25-C08', '确认为名为', '核实为名为'),
    ('004-EXP25-C08', '、类型为', '，类型为'),
    ('004-EXP25-C08', '预览确认本次只调用其', '预览已显示仅提交该对象的'),
    ('004-EXP25-C08', '自定义源', '自定义来源'),
])
def test_complete_attested_frame_components_allow_equivalent_grammar(case_id, old, new):
    case = _attested_frame_case(case_id)
    post = case['events'][1]['item']
    assert old in post['text']
    post['text'] = post['text'].replace(old, new)
    assert _grammatical_notice(case)


@pytest.mark.parametrize('case_id', ['003-EXP22-C09', '004-EXP25-C08'])
@pytest.mark.parametrize('claim', ['不会修改 OtherOwner 的备注。', '不会执行其他对象的修改。'])
def test_prospective_execution_polarity_does_not_confuse_unrelated_preservation(case_id, claim):
    case = _attested_frame_case(case_id)
    case['events'][1]['item']['text'] += claim
    assert _grammatical_notice(case)
