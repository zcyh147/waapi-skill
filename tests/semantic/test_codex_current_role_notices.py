"""Closed current-change, before-state and reference roles at notice seam."""
import copy
import json
import shlex
from pathlib import Path

import pytest

from tests.semantic.test_codex_expansion_task_runner import _grammatical_notice

_CASES = json.loads((Path(__file__).parents[1] / "fixtures/semantic/expansion-current-role-notices-db2299c.json").read_text())["cases"]


def _post(case):
    preview = next(i for i, event in enumerate(case["events"]) if event["item"].get("command") == "preview-from-draft")
    return next(event["item"] for event in case["events"][preview + 1:] if event["item"]["type"] == "agent_message")


@pytest.mark.parametrize("case", _CASES, ids=lambda row: row["case"])
def test_exact_current_role_notice(case):
    case = copy.deepcopy(case)
    for proof in case["source"]["phases"]:
        outer = shlex.split(proof["raw_command"])
        assert outer[:2] == ["/bin/bash", "-lc"]
        argv = shlex.split(outer[-1])
        assert argv[argv.index("gateway.py") + 1] == proof["phase"]
        assert sum(e["item"].get("command") == proof["phase"] for e in case["events"]) == 1
    assert _grammatical_notice(case)


@pytest.mark.parametrize("referent", ["这份", "这一份", "此项"])
@pytest.mark.parametrize("grant", ["提供", "授予"])
def test_current_change_beneficiary_components_compose(referent, grant):
    case = copy.deepcopy(_CASES[0])
    item = _post(case)
    item["text"] = item["text"].replace("这份具体变更提供", referent + "具体变更" + grant)
    assert _grammatical_notice(case)


@pytest.mark.parametrize("basis", ["变更前", "改动前", "执行前"])
def test_before_state_terms_retain_the_owned_effect(basis):
    case = copy.deepcopy(_CASES[2])
    _post(case)["text"] = _post(case)["text"].replace("变更前", basis)
    assert _grammatical_notice(case)


@pytest.mark.parametrize("preposition", ["按", "依据"])
@pytest.mark.parametrize("change", ["修改", "变更"])
def test_provider_and_submitted_scope_are_ancillary_components(preposition, change):
    case = copy.deepcopy(_CASES[1])
    item = _post(case)
    item["text"] = item["text"].replace("依据保存的", preposition + "保存的").replace("提交的修改范围", "提交的" + change + "范围")
    assert _grammatical_notice(case)


@pytest.mark.parametrize("index,old,new", [
    (0, "allow_changes", "read_only"),
    (0, "策略已为这份", "策略未为这份"),
    (0, "策略已为这份", "策略可能为这份"),
    (0, "这份具体变更", "OtherSound 的具体变更"),
    (0, "目标声音", "目标声音和 OtherSound"),
    (1, "allow_changes", "ask_before_changes"),
    (1, "提交的修改范围仅包含这一条曲线", "提交的修改范围还包含 Pitch 字段"),
    (1, "提交的修改范围仅包含这一条曲线", "在 OtherAttenuation 上提交的修改范围仅包含这一条曲线"),
    (1, "(50.0, -12)", "(50.0, -60)"),
    (2, "并记录变更前状态", "并记录 OtherSound 的变更前状态"),
    (2, "（Wwise Gain）", "（Sound）"),
    (2, "（Wwise Gain）", "（MusicSegment）"),
    (2, "（Wwise Gain）", "（Wwise Gain"),
    (3, "确认为 MusicStinger", "确认为 Sound"),
    (3, "确认为 MusicStinger", "确认为 MusicStinger 和 OtherStinger"),
    (3, "当前显示为 Bonus", "当前显示为 OtherBonus"),
    (3, "新的引用目标已核对为 Backup_Team_Arrives", "新的引用目标已核对为 Bonus"),
    (3, "这一项触发器引用修改", "这两项触发器引用修改"),
    (3, "这一项触发器引用修改", "这一项 Segment 引用修改"),
])
def test_recognized_roles_cannot_change_owner_policy_kind_value_or_scope(index, old, new):
    case = copy.deepcopy(_CASES[index])
    item = _post(case)
    assert old in item["text"]
    item["text"] = item["text"].replace(old, new)
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("case", _CASES, ids=lambda row: row["case"])
@pytest.mark.parametrize("claim", ["同时修改 Pitch 为12。", "我不会执行该变更。", "目标是 OtherOwner。"])
def test_extra_actions_refusal_and_foreign_targets_remain_visible(case, claim):
    case = copy.deepcopy(case)
    _post(case)["text"] += claim
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("claim", ["同时目标对象确认为 Sound。", "并当前显示为 OtherBonus。", "另外新的引用目标已核对为 Bonus。"])
def test_coordinated_reference_facts_cannot_contradict_an_earlier_valid_fact(claim):
    case = copy.deepcopy(_CASES[3])
    _post(case)["text"] += claim
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("damage", ["missing_old", "wrong_prepared_old", "ambiguous_source", "missing_scope", "only_type", "no_preview", "late"])
def test_reference_composition_needs_independent_old_value_unique_source_and_timing(damage):
    case = copy.deepcopy(_CASES[3])
    item = _post(case)
    if damage == "missing_old":
        case["before"]["stinger"].pop("@Trigger")
    elif damage == "wrong_prepared_old":
        case["artifact"]["prepared_operation"]["pre_state"]["field_before"]["value"]["name"] = "OtherBonus"
    elif damage == "ambiguous_source":
        case["before"]["owner"]["@Stingers"].append(copy.deepcopy(case["before"]["owner"]["@Stingers"][0]))
    elif damage == "missing_scope":
        item["text"] = item["text"].replace("预览只包含这一项触发器引用修改", "预览已生成")
    elif damage == "only_type":
        item["text"] = "目标对象确认为 MusicStinger。现在执行。"
    elif damage == "no_preview":
        case["events"] = [e for e in case["events"] if e["item"].get("command") != "preview-from-draft"]
    else:
        post = next(e for e in case["events"] if e["item"] is item)
        case["events"].remove(post)
        case["events"].append(post)
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("claim", ["并当前显示为 Bonus。", "同时目标对象确认为 MusicStinger。", "另外新的引用目标已核对为 Backup_Team_Arrives。"])
def test_coordinated_reference_facts_retain_the_same_attested_values(claim):
    case = copy.deepcopy(_CASES[3])
    _post(case)["text"] += claim
    assert _grammatical_notice(case)


@pytest.mark.parametrize("claim", ["目标对象未确认为 MusicStinger。", "当前未显示为 Bonus。", "新的引用目标未核对为 Backup_Team_Arrives。", "预览不包含这一项触发器引用修改。"])
def test_explicit_negative_reference_role_cannot_be_ignored_after_valid_roles(claim):
    case = copy.deepcopy(_CASES[3])
    _post(case)["text"] += claim
    assert not _grammatical_notice(case)


def test_submitted_scope_and_authorization_do_not_prove_the_curve_effect():
    case = copy.deepcopy(_CASES[1])
    _post(case)["text"] = "本次修改已依据保存的 allow_changes 策略取得独立授权。提交的修改范围仅包含这一条曲线。现在执行。"
    assert not _grammatical_notice(case)


def test_protected_music_scope_exclusion_is_not_a_denied_primary_reference_edit():
    case = copy.deepcopy(_CASES[3])
    _post(case)["text"] += "预览未包含音乐段或容器变更。"
    assert _grammatical_notice(case)


@pytest.mark.parametrize("tail", ["类型为 Sound", " type = Source", "并类型为 MusicSegment", " Pitch 为12", "，并类型为 Source", "，且 Pitch 为12"])
def test_parenthesized_kind_cannot_hide_an_adjacent_descriptor_contradiction(tail):
    case = copy.deepcopy(_CASES[2])
    item = _post(case)
    item["text"] = item["text"].replace("（Wwise Gain）", "（Wwise Gain）" + tail)
    assert not _grammatical_notice(case)


@pytest.mark.parametrize("tail", ["类型为 Effect", " type = effect", "，类型为 Effect", "并类型为 Effect", "，并类型为 Effect", "且类型为 Effect"])
def test_parenthesized_kind_and_equivalent_type_continuations_agree(tail):
    case = copy.deepcopy(_CASES[2])
    item = _post(case)
    item["text"] = item["text"].replace("（Wwise Gain）", "（Wwise Gain）" + tail)
    assert _grammatical_notice(case)
