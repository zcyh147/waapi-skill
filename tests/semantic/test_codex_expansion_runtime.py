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
    assert not {"--host", "--port", "--version"}.intersection(command)
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
    assert outcome.checks["trusted_oracle_closed"] is True
    archived = json.loads((root / "outcome.json").read_text())
    assert archived["inputs_sha256"] == "a" * 64
    assert archived["checks"]["trusted_oracle_closed"] is True
    if boundary:
        assert outcome.task_root is None and outcome.thread_id is None
        assert outcome.checks["capability_boundary"]["business_pass"] is False


def _run_close_case(monkeypatch, tmp_path, *, close_result=True, initially_closed=True,
                    close_exception=False, finish_result=True, finish_exception=False,
                    boundary=False):
    root = tmp_path / "case"
    calls = []
    prepared = make_policy().prepared
    runtime_state = SimpleNamespace(host="127.0.0.1", port=41234, owned_root=root / "owned",
        runner_environment={}, sandbox=SimpleNamespace(sandbox_project=root / "sample.wproj"),
        asset_root=root / "assets", evidence_root=root / "evidence")

    class Lifecycle:
        def __init__(self, **kwargs):
            pass
        def start(self):
            root.parent.mkdir(parents=True, exist_ok=True)
            root.mkdir()
            return runtime_state
        def finish(self, status, *, reason="", post_shutdown_hook=None):
            calls.append("wwise_shutdown")
            errors = []
            final_status = status
            if post_shutdown_hook is not None:
                try:
                    post_shutdown_hook(runtime_state)
                except BaseException as exc:
                    errors.append(f"post-shutdown-proof: {type(exc).__name__}: {exc}")
                    final_status = "BLOCKED"
            return SimpleNamespace(final_status=final_status, source_hash_before="same",
                source_hash_after="same", source_mtime_before_ns=10, source_mtime_after_ns=10,
                errors=tuple(errors), as_dict=lambda: {"final_status": final_status, "errors": errors})

    class Direct:
        def __init__(self, **kwargs):
            self.calls = []
            self.is_closed = initially_closed
        @property
        def fully_closed(self):
            return self.is_closed
        def __call__(self, uri, args, options):
            return {"return": [{"id": OWNER, "path": "\\Containers\\Default Work Unit\\Music"}]}
        def close(self):
            calls.append("close")
            if close_exception:
                raise RuntimeError("immediate close failed")
            if close_result is True:
                self.is_closed = initially_closed
            return close_result
        def finish_close(self):
            calls.append("finish_close")
            if finish_exception:
                raise RuntimeError("post-shutdown close failed")
            if finish_result is True:
                self.is_closed = True
            return finish_result

    def prepare(ctx):
        if boundary:
            raise ExpectedCapabilityBoundary("M05", "2022.1", {
                "agent_executed": False, "business_effect_verified": False,
                "public_observation": "unavailable"})
        return prepared

    monkeypatch.setattr(runtime, "ScenarioLifecycle", Lifecycle)
    monkeypatch.setattr(runtime, "OwnedDirectWaapiCall", Direct)
    monkeypatch.setattr(runtime, "fixture_gateway", lambda **kwargs: lambda argv: {"ok": True})
    monkeypatch.setattr(runtime, "expansion_oracle_reader", lambda **kwargs:
        lambda view, ids: [{"id": identifier, "path": "\\Containers\\Default Work Unit\\Music"}
                          for identifier in ids])
    monkeypatch.setattr(runtime, "run_expansion_codex_task", lambda **kwargs:
        {"passed": True, "status": "PASS", "thread_id": "one-thread"})
    monkeypatch.setattr(runtime.importlib, "import_module", lambda name: SimpleNamespace(
        prepare_m01=prepare, prepare_m05=prepare))
    options = SimpleNamespace(model="gpt-6-luna", reasoning_effort="high", service_tier="default",
        live_environment={}, skill_source=tmp_path, campaign_inputs_sha256="a" * 64)
    unit = SimpleNamespace(case_id="M05" if boundary else "M01", version="2022.1" if boundary else "2025.1",
        unit_id="EXP22-M05" if boundary else "EXP25-M01", policy="allow_changes")
    outcome = runtime.run_expansion_unit(unit, scenario_root=root, options=options)
    return outcome, calls


def test_trusted_oracle_actor_close_is_proven_immediately_or_after_wwise_shutdown(monkeypatch, tmp_path):
    immediate, immediate_calls = _run_close_case(monkeypatch, tmp_path / "immediate")
    assert immediate.status == "PASS" and immediate.checks["trusted_oracle_closed"] is True
    assert immediate_calls == ["close", "wwise_shutdown"]

    deferred, deferred_calls = _run_close_case(monkeypatch, tmp_path / "deferred",
        close_result=False, initially_closed=False, finish_result=True)
    assert deferred.status == "PASS" and deferred.checks["trusted_oracle_closed"] is True
    assert deferred_calls == ["close", "wwise_shutdown", "finish_close"]


@pytest.mark.parametrize("failure", ("unreaped", "post_shutdown_exception", "immediate_exception"))
def test_unproved_trusted_oracle_actor_close_is_systemic_and_blocks(monkeypatch, tmp_path, failure):
    kwargs = {"close_result": False, "initially_closed": False, "finish_result": False}
    if failure == "post_shutdown_exception":
        kwargs["finish_exception"] = True
    elif failure == "immediate_exception":
        kwargs.update(close_exception=True, finish_result=True)
    outcome, calls = _run_close_case(monkeypatch, tmp_path, **kwargs)
    assert outcome.status == "BLOCKED"
    assert outcome.checks["trusted_oracle_closed"] is False
    assert "post-shutdown-proof:" in outcome.lifecycle["errors"][0]
    assert calls[0] == "close" and calls[1] == "wwise_shutdown"
    archived = json.loads((Path(outcome.scenario_root) / "outcome.json").read_text())
    assert archived["checks"]["trusted_oracle_closed"] is False


def test_unproved_actor_close_cannot_promote_capability_boundary(monkeypatch, tmp_path):
    outcome, calls = _run_close_case(monkeypatch, tmp_path, close_result=False,
        initially_closed=False, finish_result=False, boundary=True)
    assert outcome.status == "BLOCKED"
    assert outcome.checks["trusted_oracle_closed"] is False
    assert outcome.checks["capability_boundary"]["business_pass"] is False
    assert outcome.task_root is None and outcome.thread_id is None
    assert calls == ["close", "wwise_shutdown", "finish_close"]


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


def test_macos_expansion_versions_use_distinct_empty_homes_and_owned_cleanup(monkeypatch, tmp_path):
    """The real expansion/lifecycle path owns the wrapper's effective bottle."""
    from tests.semantic.support import codex_scenario_lifecycle_v3 as lifecycle
    from tests.semantic.test_codex_scenario_lifecycle_v3 import _install_fakes

    source, _ = _install_fakes(monkeypatch, tmp_path)
    monkeypatch.setattr(runtime.sys, "platform", "darwin")
    monkeypatch.setattr(lifecycle, "require_live_environment", lambda env:
        SimpleNamespace(version=env["WWISE_VERSION"], sample_project_source=source))
    launches, cleanups = [], []

    def launch(sandbox, env, *, wine_prefix_path, case_owned_root):
        home = Path(env["HOME"])
        assert home.is_dir() and not any(home.iterdir())
        assert not wine_prefix_path.exists()
        assert wine_prefix_path == home / "Library/Application Support/Wwise2019/Bottles/Wwise2019x64"
        assert case_owned_root == home.parent
        wine_prefix_path.mkdir(parents=True)
        sandbox.metadata.wine_prefix_path = str(wine_prefix_path)
        launches.append((home, wine_prefix_path))
        return SimpleNamespace(host="127.0.0.1", port=49152,
            command=("WwiseConsole", str(sandbox.sandbox_project)),
            launch_cwd=sandbox.sandbox_root.resolve(), prefix=wine_prefix_path)

    def shutdown(process, sandbox, *, suppress_errors):
        assert suppress_errors is False
        assert str(process.prefix) == sandbox.metadata.wine_prefix_path
        cleanups.append(process.prefix)

    class Direct:
        calls = []
        fully_closed = True
        def __init__(self, **kwargs):
            pass
        def close(self):
            return True

    prepared = make_policy().prepared
    monkeypatch.setattr(lifecycle, "launch_sandboxed_wwise", launch)
    monkeypatch.setattr(lifecycle, "shutdown_sandboxed_wwise", shutdown)
    monkeypatch.setattr(runtime, "make_project_prelaunch_hook", lambda request: lambda *args: None)
    monkeypatch.setattr(runtime, "OwnedDirectWaapiCall", Direct)
    monkeypatch.setattr(runtime, "fixture_gateway", lambda **kwargs: lambda argv: {"ok": True})
    monkeypatch.setattr(runtime, "expansion_oracle_reader", lambda **kwargs:
        lambda view, ids: [{"id": identifier, "path": "\\Containers\\Default Work Unit\\Music"} for identifier in ids])
    monkeypatch.setattr(runtime.importlib, "import_module", lambda name: SimpleNamespace(prepare_m01=lambda ctx: prepared))
    monkeypatch.setattr(runtime, "run_expansion_codex_task", lambda **kwargs:
        {"passed": True, "status": "PASS", "thread_id": "fake-task"})
    options = SimpleNamespace(model="gpt-6-luna", reasoning_effort="high", service_tier="default",
        live_environment={}, skill_source=tmp_path, campaign_inputs_sha256="a" * 64)

    for version in ("2022.1", "2025.1"):
        root = tmp_path / version
        unit = SimpleNamespace(case_id="M01", version=version, unit_id=f"EXP-{version}", policy="allow_changes")
        outcome = runtime.run_expansion_unit(unit, scenario_root=root, options=options)
        assert outcome.status == "PASS", outcome
        start = json.loads((root / "evidence/start.json").read_text())
        assert start["isolated_launch_environment"] == {"HOME": str(launches[-1][0])}
        assert start["owned_wine_prefix"] == str(cleanups[-1])
        assert not (root / "owned").exists()
    assert launches[0][0] != launches[1][0]
    assert cleanups == [prefix for _, prefix in launches]
    assert all(tmp_path in prefix.parents for prefix in cleanups)


@pytest.mark.parametrize("platform", ("win32", "linux"))
def test_non_macos_expansion_preserves_lifecycle_launch_inputs(monkeypatch, tmp_path, platform):
    observed = {}
    class StopAfterConstruction(Exception):
        pass
    def construct(**kwargs):
        observed.update(kwargs)
        raise StopAfterConstruction
    monkeypatch.setattr(runtime.sys, "platform", platform)
    monkeypatch.setattr(runtime, "ScenarioLifecycle", construct)
    unit = SimpleNamespace(case_id="M01", version="2025.1", unit_id="EXP25-M01")
    live_environment = {"HOME": str(tmp_path / "existing-home")}
    options = SimpleNamespace(model="gpt-6-luna", reasoning_effort="high", service_tier="default",
        live_environment=live_environment)
    with pytest.raises(StopAfterConstruction):
        runtime.run_expansion_unit(unit, scenario_root=tmp_path / "case", options=options)
    assert observed["live_environment"] == live_environment
    assert observed["launch_environment_overrides"] is None
    assert observed["owned_wine_prefix"] is None


@pytest.mark.parametrize("contamination", ("settings", "bottle"))
def test_macos_expansion_rejects_nonempty_home_before_launch(monkeypatch, tmp_path, contamination):
    from tests.semantic.support import codex_scenario_lifecycle_v3 as lifecycle
    from tests.semantic.test_codex_scenario_lifecycle_v3 import _install_fakes

    _install_fakes(monkeypatch, tmp_path)
    monkeypatch.setattr(runtime.sys, "platform", "darwin")
    original_prepare = lifecycle.prepare_sample_project_sandbox
    def prepare(env, **kwargs):
        sandbox = original_prepare(env, **kwargs)
        home = Path(env["HOME"])
        if contamination == "settings":
            (home / "settings.ini").write_text("unexpected", encoding="utf-8")
        else:
            (home / "Library/Application Support/Wwise2019/Bottles/Wwise2019x64").mkdir(parents=True)
        return sandbox
    monkeypatch.setattr(lifecycle, "prepare_sample_project_sandbox", prepare)
    monkeypatch.setattr(lifecycle, "launch_sandboxed_wwise", lambda *args, **kwargs: pytest.fail("must not launch"))
    root = tmp_path / "case"
    options = SimpleNamespace(model="gpt-6-luna", reasoning_effort="high", service_tier="default",
        live_environment={}, campaign_inputs_sha256="a" * 64)
    unit = SimpleNamespace(case_id="M01", version="2022.1", unit_id="EXP22-M01")
    outcome = runtime.run_expansion_unit(unit, scenario_root=root, options=options)
    assert outcome.status == "BLOCKED"
    failure = json.loads((root / "evidence/start-failure.json").read_text())
    assert failure["stage"] == "prelaunch" and failure["wwise_stop_status"] == "not-started"
    assert failure["never_reuse"] is True
    assert "empty real case-owned Wwise HOME" in failure["primary_error"]
    assert failure["source_hash_before"] == failure["source_hash_after"]
