import json
from types import SimpleNamespace

import pytest

from tests.semantic.support.codex_task_runner_v3 import expansion_preview_notice


ARTIFACT = {"request": {"operation": "audio.import", "arguments": {
    "imports": [{"object_path": r"\Music\Quiet", "properties": [{"name": "Volume", "value": -6.0}]}]}}}


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


def _notice(events, *, artifact=ARTIFACT, before=None, execute_expected=True):
    records = [SimpleNamespace(command=command, argv=("python", "/tmp/skill/scripts/run.py", "gateway.py", command, "x"))
               for command in ("preview-from-draft", "execute")]
    return expansion_preview_notice(SimpleNamespace(stdout="\n".join(json.dumps(event) for event in events)),
        records, version="2025.1", execute_expected=execute_expected,
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
