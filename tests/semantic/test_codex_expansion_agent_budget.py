from types import SimpleNamespace

import pytest

from tests.semantic.support import codex_harness as harness
from tests.semantic.support.codex_expansion_policy import CumulativeAgentBudget, ExpansionPolicyError


def task(budget):
    value = object.__new__(harness.CodexCliTask)
    value.agent_case_budget = budget
    value._turn_results = []
    value._failed = False
    return value


def test_task_passes_only_remaining_case_budget_to_later_turns(monkeypatch, tmp_path):
    value = task(CumulativeAgentBudget())
    times = iter((100.0, 500.0, 900.0, 1100.0, 1200.0))
    monkeypatch.setattr(harness.time, "monotonic", lambda: next(times))
    observed = []
    def run(_prompt, *, output_dir, command, timeout_seconds):
        observed.append(timeout_seconds)
        return SimpleNamespace()
    value._run_turn = run
    value._record_turn("first", output_dir=tmp_path, command=[])
    value._record_turn("confirm", output_dir=tmp_path, command=[])
    with pytest.raises(ExpansionPolicyError, match="exhausted"):
        value._record_turn("retry", output_dir=tmp_path, command=[])
    assert observed == [600.0, 200.0]
    assert value.agent_case_budget.slow


def test_legacy_task_keeps_existing_per_turn_call_shape(tmp_path):
    value = task(None)
    def run(_prompt, *, output_dir, command):
        return SimpleNamespace()
    value._run_turn = run
    value._record_turn("first", output_dir=tmp_path, command=[])
    assert len(value._turn_results) == 1


def test_failed_turn_consumes_budget_and_is_terminal(monkeypatch, tmp_path):
    value = task(CumulativeAgentBudget())
    times = iter((0.0, 450.0))
    monkeypatch.setattr(harness.time, "monotonic", lambda: next(times))
    def run(*args, **kwargs):
        raise RuntimeError("failed model call")
    value._run_turn = run
    with pytest.raises(RuntimeError):
        value._record_turn("first", output_dir=tmp_path, command=[])
    assert value._failed and value.agent_case_budget.elapsed_seconds == 450


def test_prompt_audit_retry_cannot_restart_the_remaining_case_budget(monkeypatch, tmp_path):
    value = object.__new__(harness.CodexCliHarness)
    value.config = SimpleNamespace(workspace=tmp_path)
    monkeypatch.setattr(harness, "build_prompt_audit_command", lambda *args, **kwargs: ["fake-codex"])
    times = iter((100.0, 102.0, 103.1))
    monkeypatch.setattr(harness.time, "monotonic", lambda: next(times))
    timeouts = []
    def run(*args, **kwargs):
        timeouts.append(kwargs["timeout"])
        return SimpleNamespace(exit_status=124, timed_out=True, stderr="timeout")
    monkeypatch.setattr(harness, "run_process", run)
    with pytest.raises(harness.CodexHarnessError, match="budget exhausted"):
        value.audit_prompt("hello", env={}, timeout_seconds=3)
    assert timeouts == [1.0]
