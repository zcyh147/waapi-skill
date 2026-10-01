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
