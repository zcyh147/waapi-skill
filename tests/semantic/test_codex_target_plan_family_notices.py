"""Finite target/operation-noun families at the attested notice seam."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from tests.semantic.test_codex_expansion_task_runner import _grammatical_notice


_EXACT = Path(__file__).parents[1] / "fixtures/semantic/expansion-target-plan-e93a575.json"
_MATRIX = _EXACT.with_name("expansion-target-plan-independent-20261007.json")
_FIXTURE = _EXACT.with_name("expansion-target-plan-independent-fixture-20261007.json")
_DESIGN = json.loads(_MATRIX.read_text())
_CONTEXT = json.loads(_FIXTURE.read_text())


def test_exact_target_plan_notice_from_frozen_e93a575():
    case = json.loads(_EXACT.read_text())
    assert case["source_event_indices"] == [22, 23, 24]
    assert case["events"][1]["item"]["text"] == (
        "目标已核对，追加方案已按 allow_changes 策略取得独立持久授权，目前尚未修改工程。"
        "即将追加 Wwise Gain 效果器 Expansion_EXP25-C09_NewGain，备注为“Expansion C09 appended gain”，"
        "不另设插件参数或平台值；执行后将核验原有效果器的身份、slot 绑定和顺序，以及声音属性的保持情况。\n"
    )
    assert _grammatical_notice(case)


@pytest.mark.parametrize("pair,polarity", [(pair, polarity) for pair in _DESIGN["pairs"]
    for polarity in ("positive", "negative")], ids=[pair["pair_id"] + "-" + polarity
    for pair in _DESIGN["pairs"] for polarity in ("positive", "negative")])
def test_frozen_independent_target_plan_families(pair, polarity):
    # Pair11 清单 is an unsupported-language boundary, not business invalidity.
    assert hashlib.sha256(_MATRIX.read_bytes()).hexdigest() == "a4a087d4cbf58f7302a434baf350ef15fad44883db9d08e2a74105abacd0e67b"
    assert hashlib.sha256(_FIXTURE.read_bytes()).hexdigest() == "79c14d62eb9084737deb18dd8ed47f64cc8fc223590340b092ed48669deec6ca"
    vector = pair[polarity]
    if pair.get("fixture_ref"):
        key = pair["fixture_ref"].split(".", 1)[1]
        case = copy.deepcopy(_CONTEXT["cross_kind_fixtures"][key])
        preview, execute = (event for event in case["events"] if event["item"]["type"] == "command_execution")
    else:
        case = json.loads(_EXACT.read_text())
        preview, _, execute = case["events"]
    phases = {"preview_receipt": preview, "execute_start": execute}
    events = []
    for stage in vector["stage_schedule"]:
        if stage.startswith("message:"):
            events.append({"type": "item.completed", "item": {"type": "agent_message",
                "text": vector["messages"][int(stage.split(":")[1])]}})
        elif stage == "synthetic_second_preview":
            events.append(copy.deepcopy(preview))
        else:
            events.append(copy.deepcopy(phases[stage]))
    case["events"] = events
    assert _grammatical_notice(case) is vector["expected_notice_evidence"], vector["rationale"]


@pytest.mark.parametrize("selector,source,tail,expected", [
    ("volume-dry 干声音量曲线", "Custom", "", True),
    ("干声音量 volume-dry 曲线", "Custom", "", True),
    ("volume-dry spread 曲线", "Custom", "", False),
    ("volume-dry 湿声音量曲线", "Custom", "", False),
    ("volume-dry 干声音量和 spread 曲线", "Custom", "", False),
    ("volume-dry 干声音量曲线", "UseVolumeDry", "", False),
    ("volume-dry 干声音量曲线", "Custom", "同时修改备注为 changed。", False),
    ("干声音量 volume-dry 曲线", "Custom", "同时把该衰减对象的 spread 曲线设置为 Custom。", False),
    ("volume-dry 干声音量 dry volume 曲线", "Custom", "", False),
])
def test_adjacent_equivalent_curve_aliases_remain_one_closed_selector(selector, source, tail, expected):
    case = copy.deepcopy(_CONTEXT["cross_kind_fixtures"]["011-EXP25-C08"])
    case["events"] = case["events"][1:]
    case["events"][1]["item"]["text"] = (
        "已核对目标衰减对象身份。已核实该衰减对象配置。即将把该衰减对象的 "
        + selector + "设置为 " + source + "，按顺序写入 Linear 点 (0, 0 dB)、(50, -12 dB)、(100, -48 dB)，"
        "其他曲线、引用和对象身份保持。" + tail)
    assert _grammatical_notice(case) is expected


@pytest.mark.parametrize("attestation", [
    "未核对目标", "目标尚未核实", "可能已确认该对象", "该对象身份可能已确认",
    "目标声音和 OtherSound 身份已核对", "该对象和 OtherSound 配置已核实",
])
def test_conflicting_target_claim_cannot_be_erased_by_an_explicit_correct_append_owner(attestation):
    case = json.loads(_EXACT.read_text())
    case["events"][1]["item"]["text"] = (attestation + "。即将向目标声音追加 Wwise Gain 效果器 "
        "Expansion_EXP25-C09_NewGain，备注为“Expansion C09 appended gain”。")
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("damage", ["negated", "uncertain", "unmatched", "omitted", "wrong-point", "wrong-order", "foreign-owner", "extra-edit"])
def test_ordered_point_summary_cannot_supply_or_broaden_the_curve_assignment(damage):
    case = copy.deepcopy(_CONTEXT["cross_kind_fixtures"]["011-EXP25-C08"])
    case["events"] = case["events"][1:]
    text = _DESIGN["pairs"][20]["positive"]["messages"][0]
    if damage == "negated":
        text = text.replace("即将把", "不会把")
    elif damage == "uncertain":
        text = text.replace("即将把", "可能把")
    elif damage == "unmatched":
        text = text.replace("设置为 Custom", "设置为 None")
    elif damage == "omitted":
        text = text[:text.index("即将把")] + text[text.index("按顺序写入"):]
    elif damage == "wrong-point":
        text = text.replace("(50, -12 dB)", "(50, -24 dB)")
    elif damage == "wrong-order":
        text = text.replace("(0, 0 dB)、(50, -12 dB)", "(50, -12 dB)、(0, 0 dB)")
    elif damage == "foreign-owner":
        text = text.replace("即将把该衰减对象", "即将把 OtherAttenuation")
    else:
        text += "同时修改备注为 changed。"
    case["events"][1]["item"]["text"] = text
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("attestation,notice", [
    ("目标和 OtherSound 尚未核实", "bare-owner"),
    ("目标和 OtherSound 尚未核实", "typed-owner"),
    ("目标对象和 OtherSound身份尚未核对", "exact"),
    ("可能已核对目标声音和 OtherSound 身份", "exact"),
    ("目标对象和 OtherSound身份已核对", "exact"),
])
def test_review_compound_target_attestation_cannot_disappear_beside_correct_append(attestation, notice):
    case = json.loads(_EXACT.read_text())
    if notice == "exact":
        case["events"][1]["item"]["text"] += attestation + "。"
    else:
        owner = "目标" if notice == "bare-owner" else "目标声音"
        case["events"][1]["item"]["text"] = (attestation + "。即将向" + owner
            + "追加 Wwise Gain 效果器 Expansion_EXP25-C09_NewGain，备注为“Expansion C09 appended gain”。")
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("attestation", [
    "未核对目标和 OtherSound", "目标和 OtherSound 未核对",
    "还未核实该对象和 OtherSound 的配置", "该对象和 OtherSound 的配置还未核实",
    "没有确认 OtherSound", "OtherSound 没有确认",
    "不能核实 OtherSound身份", "OtherSound身份不能核实",
    "可能已核对目标声音和 OtherSound 身份", "目标声音和 OtherSound 身份可能已核对",
    "也许已确认该对象和 OtherSound 配置", "该对象和 OtherSound 配置也许已确认",
    "或许已核实 OtherSound", "OtherSound 或许已核实",
    "不确定是否已核对 OtherSound身份", "OtherSound身份不确定是否已核对",
])
def test_finite_nonaffirmative_supplied_owner_frames_fail_closed(attestation):
    case = json.loads(_EXACT.read_text())
    case["events"][1]["item"]["text"] += attestation + "。"
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("attestation", [
    "已核对目标", "目标已核实", "已确认目标声音身份", "目标声音身份已确认",
    "已核实该对象的配置", "该对象的配置已核实",
])
def test_affirmative_same_family_target_attributes_preserve_correct_append(attestation):
    case = json.loads(_EXACT.read_text())
    case["events"][1]["item"]["text"] += attestation + "。"
    assert _grammatical_notice(case)


@pytest.mark.parametrize("attestation", [
    "已核对该 Stinger 身份", "该 Stinger 配置已核实",
])
def test_affirmative_typed_source_attributes_preserve_separate_reference_destination(attestation):
    case = copy.deepcopy(_CONTEXT["cross_kind_fixtures"]["014-EXP25-M05"])
    preview = next(i for i, event in enumerate(case["events"])
        if event["item"].get("command") == "preview-from-draft")
    post = next(event["item"] for event in case["events"][preview + 1:]
        if event["item"]["type"] == "agent_message")
    post["text"] += attestation + "。"
    assert _grammatical_notice(case)


@pytest.mark.parametrize("ancillary", ["未确认下一步时间", "未核对文档"])
def test_unrelated_nonaffirmative_reads_preserve_correct_explicit_owner(ancillary):
    case = json.loads(_EXACT.read_text())
    case["events"][1]["item"]["text"] = (ancillary + "。即将向目标声音追加 Wwise Gain 效果器 "
        "Expansion_EXP25-C09_NewGain，备注为“Expansion C09 appended gain”。")
    assert _grammatical_notice(case)
