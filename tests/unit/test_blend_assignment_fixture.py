"""Actual Blend native collector exercised through the public Gateway/fake boundary."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.support.gateway_config import set_gateway_config
from tests.unit.test_core_business_gateway import _BlendAssignmentTask
from tests.unit.test_workflow_source_guard import workflow


def blend_runtime(tmp_path, workflow, monkeypatch, version="2024.1", fault=None):
    task = _BlendAssignmentTask(tmp_path / "backend", version)
    set_gateway_config(task.env, waapi_host="127.0.0.1", waapi_port=31337)
    build = dict(zip(("year", "major", "minor", "build"), (2024, 1, 13, 9056) if version == "2024.1" else (2025, 1, 7, 9143)))
    task.info["version"].update(build)
    track = "{8D76C40F-1C73-42C7-9A26-8C0E56E6898F}"
    owner = "{97A58685-6231-4227-9BAB-451E089615A8}"
    child = "{CFAF8A1B-1DF5-4711-80DA-D61A42F859D7}"
    path = (r"\Containers" if version == "2025.1" else r"\Actor-Mixer Hierarchy") + r"\Car Engine\Porsche 911 - Blend Container"
    task.objects = {
        track: dict(id=track, name="On-Load", type="BlendTrack", path="On-Load"),
        owner: dict(id=owner, name="Porsche 911 - Blend Container", type="BlendContainer", path=path, blendTracks=[dict(id=track, name="On-Load")]),
        child: dict(id=child, name="Outside_Off-Load_2000", type="Sound", path=path + r"\Outside_Off-Load_2000", parent=dict(id=owner)),
    }
    task.assignments = [dict(child="{" + f"{index + 100:08x}" + "-1234-5678-9ABC-ABCDEF123456}", index=index, edges=task.edges(index * 10)) for index in range(6)]
    original_call = task.call
    def native(uri, args=None, options=None):
        result = original_call(uri, args, options)
        if uri == task.uri and fault in {"verify", "verify+write"}:
            task.assignments[1]["edges"][0]["edgePosition"] = 999
        return result
    task.call = native
    packets = tmp_path / "packets"; packets.mkdir()
    state = tmp_path / "collector-state"; state.mkdir()
    runtime = SimpleNamespace(version=version, candidate="program-only", category_results=[], state_dir=state,
        sandbox=SimpleNamespace(source_root=workflow.REPO_ROOT / "tests/_org" / version, metadata=SimpleNamespace(get_info_version=build)),
        env={**task.env, "WWISE_EVIDENCE_DIR": str(packets)}, port=31337,
        lifecycle=SimpleNamespace(host="127.0.0.1", waapi_url="ws://127.0.0.1:31337/waapi"))
    commands = []
    def raw(argv):
        commands.append(list(argv))
        code, reply = workflow.waapi_gateway.execute_gateway(["--state-dir", str(state), *argv], env=runtime.env, client_factory=lambda _: task)
        if argv[0] == "verify" and fault == "bound":
            for index in range(65): (packets / f"extra-{index}.json").write_text("{}")
        return code, reply
    runtime.raw_gateway = raw
    runtime.gateway = lambda argv, live: workflow._WorkflowSandboxRuntime.gateway(runtime, argv, live=live)
    def forbidden(*args, **kwargs): raise AssertionError("Collector fake cannot create a real client/socket")
    monkeypatch.setattr(workflow.waapi_gateway, "default_client_factory", forbidden)
    return runtime, task, commands


def test_blend_collector_retains_actual_failed_verification_after_one_execution(tmp_path, workflow, monkeypatch):
    runtime, task, commands = blend_runtime(tmp_path, workflow, monkeypatch, fault="verify")
    with pytest.raises(AssertionError):
        workflow.test_blend_assignment_negative_index_order_preservation(runtime)
    category, = runtime.category_results
    receipt = json.loads(Path(category["observation_path"]).read_text())
    phases = receipt["transactions"]
    assert phases["preview"]["transaction_id"] == phases["transaction_id"]
    assert phases["execute"]["executed"] is True
    assert phases["verify"]["verified"] is False
    assert phases["verify"]["verification"]["business_state_verified"] is False
    assert category["status"] == "FAIL" and receipt["native_assignment_effect_verified"] is False
    assert "failure" in receipt and phases["verify_exit_code"] == 2
    assert [cmd[0] for cmd in commands].count("execute") == [cmd[0] for cmd in commands].count("verify") == 1
    assert sum(uri == task.uri for uri, _, _ in task.calls) == 1


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
def test_blend_collector_runs_actual_public_flow_for_both_fixture_definitions(tmp_path, workflow, monkeypatch, version):
    runtime, task, commands = blend_runtime(tmp_path, workflow, monkeypatch, version)
    workflow.test_blend_assignment_negative_index_order_preservation(runtime)
    category, = runtime.category_results
    receipt = json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "PASS" and receipt["native_assignment_effect_verified"] is True
    assert receipt["transactions"]["verify"]["verification"]["business_state_verified"] is True
    assert receipt["after"]["agent_result"]["return"][0]["child"] == "{CFAF8A1B-1DF5-4711-80DA-D61A42F859D7}"
    assert [cmd[0] for cmd in commands].count("execute") == [cmd[0] for cmd in commands].count("verify") == 1
    assert sum(uri == task.uri for uri, _, _ in task.calls) == 1


def test_blend_collector_receipt_write_failure_never_leaves_pass(tmp_path, workflow, monkeypatch):
    runtime, task, commands = blend_runtime(tmp_path, workflow, monkeypatch)
    write = Path.write_bytes
    def fail_final(path, data):
        if path.name.startswith("blend-negative-insertion.json"):
            raise OSError("injected receipt write failed")
        return write(path, data)
    monkeypatch.setattr(Path, "write_bytes", fail_final)
    with pytest.raises(OSError, match="injected receipt write failed"):
        workflow.test_blend_assignment_negative_index_order_preservation(runtime)
    category, = runtime.category_results
    assert category["status"] == "FAIL"
    partial = json.loads(Path(category["observation_path"]).read_text())
    assert partial["native_assignment_effect_verified"] is False
    assert partial["transactions"]["execute"]["executed"] is True
    assert partial["transactions"]["verify"]["verified"] is True
    assert partial["finalization_error"]["type"] == "OSError"
    assert [cmd[0] for cmd in commands].count("execute") == 1


def test_blend_collector_evidence_bound_cannot_credit_pass(tmp_path, workflow, monkeypatch):
    runtime, task, commands = blend_runtime(tmp_path, workflow, monkeypatch, fault="bound")
    with pytest.raises(AssertionError, match="Blend dispatcher evidence file bound"):
        workflow.test_blend_assignment_negative_index_order_preservation(runtime)
    category, = runtime.category_results
    receipt = json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "FAIL" and category["native_assignment_effect_verified"] is False
    assert receipt["native_assignment_effect_verified"] is False
    assert receipt["transactions"]["verify"]["verified"] is True
    assert receipt["finalization_error"]["message"].startswith("Blend dispatcher evidence file bound")
    assert [cmd[0] for cmd in commands].count("execute") == 1


@pytest.mark.parametrize("all_writes_fail", [False, True])
def test_blend_collector_preserves_original_verification_failure_when_finalization_also_fails(tmp_path, workflow, monkeypatch, all_writes_fail):
    runtime, task, commands = blend_runtime(tmp_path, workflow, monkeypatch, fault="verify+write")
    write = Path.write_bytes
    def fail_final(path, data):
        if path.name.startswith("blend-negative-insertion") and (all_writes_fail or path.name.startswith("blend-negative-insertion.json")):
            raise OSError("later finalization failure")
        return write(path, data)
    monkeypatch.setattr(Path, "write_bytes", fail_final)
    with pytest.raises(AssertionError) as original:
        workflow.test_blend_assignment_negative_index_order_preservation(runtime)
    category, = runtime.category_results
    receipt = category["partial_receipt"] if all_writes_fail else json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "FAIL" and category["native_assignment_effect_verified"] is False
    assert receipt["native_assignment_effect_verified"] is False
    assert receipt["failure"]["type"] == "AssertionError"
    assert receipt["failure"]["message"] == str(original.value)[:2048]
    assert receipt["finalization_error"]["type"] == "OSError"
    assert receipt["transactions"]["preview"]["transaction_id"] == receipt["transactions"]["transaction_id"]
    assert receipt["transactions"]["execute"]["executed"] is True
    assert receipt["transactions"]["verify"]["verified"] is False
    assert receipt["transactions"]["verify_exit_code"] == 2
    assert [cmd[0] for cmd in commands].count("execute") == [cmd[0] for cmd in commands].count("verify") == 1
    assert sum(uri == task.uri for uri, _, _ in task.calls) == 1
