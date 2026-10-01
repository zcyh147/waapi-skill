from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from tests.semantic.support import codex_expansion_runtime as runtime
from tests.semantic.support.codex_expansion_cases import ExpectedCapabilityBoundary
from tests.semantic.test_codex_expansion_broker_policy import make_policy, OWNER


def test_fixture_gateway_uses_separate_packaged_process_and_private_endpoint(monkeypatch, tmp_path):
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({"ok": True, "command": "status",
            "endpoint": {"host": "127.0.0.1", "port": 41234}}))
    monkeypatch.setattr(runtime, "run_owned_gateway", run)
    owned = SimpleNamespace(host="127.0.0.1", port=41234, owned_root=tmp_path,
                            runner_environment={"WWISE_WAAPI_PORT": "41234"})
    receipts = []
    gateway = runtime.fixture_gateway(skill_source=tmp_path / "skill", runtime=owned,
                                      version="2025.1", receipts=receipts)
    assert gateway(["status"])["ok"]
    command, kwargs = calls[0]
    assert command[1:3] == [str(tmp_path / "skill" / "scripts" / "run.py"), "gateway.py"]
    assert command[command.index("--port") + 1] == "41234"
    assert kwargs["environment"]["WAAPI_SKILL_CONFIG_PATH"] == str(tmp_path / "setup-config.json")
    assert kwargs["timeout_seconds"] == 45
    assert receipts[0]["argv"] == ["status"]


@pytest.mark.parametrize("case,version,boundary,expected", [
    ("M01", "2025.1", False, "PASS"),
    ("M01", "2025.1", False, "FAIL"),
    ("M01", "2025.1", False, "BLOCKED"),
    ("M01", "2025.1", False, "INDETERMINATE"),
    ("M05", "2022.1", True, "BOUNDARY_PROVEN"),
    ("M01", "2025.1", True, "BLOCKED"),
])
def test_existing_lifecycle_dispatch_and_boundary_never_start_an_agent(monkeypatch, tmp_path, case, version, boundary, expected):
    root = tmp_path / "case"
    calls = []
    prepared = make_policy().prepared
    class Lifecycle:
        def __init__(self, **kwargs):
            calls.append(("lifecycle", kwargs))
        def start(self):
            root.mkdir()
            return SimpleNamespace(host="127.0.0.1", port=41234, owned_root=root / "owned",
                runner_environment={}, sandbox=SimpleNamespace(sandbox_project=root / "sample.wproj"),
                asset_root=root / "assets", evidence_root=root / "evidence")
        def finish(self, status, **kwargs):
            calls.append(("finish", status))
            return SimpleNamespace(final_status=status, source_hash_before="same", source_hash_after="same",
                source_mtime_before_ns=10, source_mtime_after_ns=10, errors=(),
                as_dict=lambda: {"final_status": status})
    class Direct:
        def __init__(self, **kwargs):
            self.calls = []
            self.fully_closed = False
        def __call__(self, uri, args, options):
            return {"return": [{"id": OWNER, "path": "\\Containers\\Default Work Unit\\Music"}]}
        def close(self):
            self.fully_closed = True
            calls.append(("closed", True))
            return True
    def prepare(ctx):
        if boundary:
            raise ExpectedCapabilityBoundary(case, version, {"agent_executed": False,
                "business_effect_verified": False, "public_observation": "unavailable"})
        return prepared
    def run_task(**kwargs):
        calls.append(("agent", kwargs))
        return {"passed": expected == "PASS", "status": expected, "thread_id": "one-thread"}
    monkeypatch.setattr(runtime, "ScenarioLifecycle", Lifecycle)
    monkeypatch.setattr(runtime, "OwnedDirectWaapiCall", Direct)
    monkeypatch.setattr(runtime, "fixture_gateway", lambda **kwargs: lambda argv: {"ok": True})
    monkeypatch.setattr(runtime, "run_expansion_codex_task", run_task)
    monkeypatch.setattr(runtime.importlib, "import_module", lambda name: SimpleNamespace(**{
        "prepare_m01": prepare, "prepare_m05": prepare}))
    options = SimpleNamespace(model="gpt-6-luna", reasoning_effort="high", service_tier="default",
                              live_environment={}, skill_source=tmp_path, campaign_inputs_sha256="a" * 64)
    unit = SimpleNamespace(case_id=case, version=version, unit_id=f"EXP-{case}", policy="allow_changes")
    outcome = runtime.run_expansion_unit(unit, scenario_root=root, options=options)
    assert outcome.status == expected, outcome
    assert any(row[0] == "agent" for row in calls) is not boundary
    assert json.loads((root / "outcome.json").read_text())["inputs_sha256"] == "a" * 64
    if boundary:
        assert outcome.task_root is None and outcome.thread_id is None
        assert outcome.checks["capability_boundary"]["business_pass"] is False


def test_fixture_timeout_preserves_bounded_failure_receipt_without_retry(monkeypatch, tmp_path):
    launches = []
    def fail(command, **kwargs):
        launches.append(command)
        raise runtime.subprocess.TimeoutExpired(command, kwargs["timeout_seconds"])
    monkeypatch.setattr(runtime, "run_owned_gateway", fail)
    owned = SimpleNamespace(host="127.0.0.1", port=41234, owned_root=tmp_path, runner_environment={})
    receipts = []
    gateway = runtime.fixture_gateway(skill_source=tmp_path / "skill", runtime=owned,
                                      version="2025.1", receipts=receipts)
    with pytest.raises(runtime.subprocess.TimeoutExpired):
        gateway(["execute", "tx1-owned"])
    assert len(launches) == len(receipts) == 1
    assert receipts[0]["argv"] == ["execute", "tx1-owned"] and receipts[0]["processes_reaped"] is True
    assert len(receipts[0]["error"]["message"].encode()) <= 2048
