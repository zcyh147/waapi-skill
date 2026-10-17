"""Real authenticated rejection and task grading; only the external CLI is fake."""
from dataclasses import asdict
import json
from pathlib import Path
import shlex
from types import SimpleNamespace
import pytest
from tests.semantic.support import codex_task_runner_v3 as runner
from tests.semantic.support.codex_gateway_broker import CodexGatewayBroker
from tests.semantic.support.codex_harness import completed_command_records, classify_task_commands, audit_session_events
from tests.semantic.support.codex_expansion_cases import PreparedExpansionCase
from tests.semantic.support.codex_expansion_policy import canonical_digest
from tests.semantic.support.codex_repair_cases import F2_ASSERTIONS, F3_ASSERTIONS, verify_f2
from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive, ExpansionArchiveError

SKILL = Path(__file__).parents[2] / "skills/waapi-skill"
INPUTS = "a" * 64


def produce_rejected_task(tmp_path, monkeypatch, *, policy="read_only", rejected_argv=None, gateway_calls=None):
    held = {}
    def broker_factory(**kwargs):
        held["broker"] = CodexGatewayBroker(**kwargs)
        return held["broker"]
    monkeypatch.setattr(runner, "CodexGatewayBroker", broker_factory)
    class FakeCli:
        thread_id = "read-rejection-thread"
        windows_powershell_core_host = None
        def __init__(self, config, **kwargs):
            self.config, self.budget = config, kwargs["agent_case_budget"]
            held["instructions"] = config.developer_instructions
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def run_initial(self, prompt, *, output_dir):
            self.budget.start_turn(100)
            broker = held["broker"]
            events = [{"type": "thread.started", "thread_id": self.thread_id}, {"type": "turn.started"}]
            for number, relative in enumerate(("SKILL.md", "references/waapi-query.md" if policy == "read_only" else "references/waapi-operate.md")):
                path = broker.invocation_skill_source / relative
                item = {"id": f"read-{number}", "type": "command_execution", "command": shlex.join(["cat", str(path)]),
                    "status": "completed", "exit_code": 0, "aggregated_output": path.read_text()}
                events.extend([{"type": "item.started", "item": {**item, "status": "in_progress"}}, {"type": "item.completed", "item": item}])
            calls = gateway_calls or [(rejected_argv or ["query-object", "--kind", "game-parameter",
                    "--include", "range", "--include", "default", "--max-results", "100"], 126)]
            for number, (arguments, expected_exit) in enumerate(calls):
                argv = [str(broker.invocation_runner_path), "gateway.py", *arguments]
                reply = broker._handle_request({"token": broker._token, "interpreter": "python", "argv": argv})
                assert reply["exit_code"] == expected_exit, reply
                item = {"id": f"query-{number}", "type": "command_execution", "command": shlex.join(["python", *argv]),
                    "status": "completed", "exit_code": expected_exit, "aggregated_output": reply["stdout"]}
                events.extend([{"type": "item.started", "item": {**item, "status": "in_progress"}}, {"type": "item.completed", "item": item}])
            final = "Target has range -12 to 36 and default 7. No change was made." if gateway_calls and calls[-1][1] == 0 else "I could not complete the read. No change was made."
            events.extend([{"type": "item.completed", "item": {"id": "final", "type": "agent_message", "text": final}}, {"type": "turn.completed"}])
            self.budget.finish_turn(101)
            commands = completed_command_records(events, platform_name="posix")
            facts = classify_task_commands(commands, workspace=self.config.workspace, skill_source=SKILL,
                expected_gateway_subcommands=("query-object", "query-schema", "draft-start"), expected_wwise_version="2025.1")
            result = SimpleNamespace(stdout="".join(json.dumps(event) + "\n" for event in events), stderr="", exit_status=0,
                timed_out=False, thread_id=self.thread_id, final_response=final,
                command_facts=facts, isolation_audit=SimpleNamespace(passed=True), prompt_audit=SimpleNamespace(passed=True, has_memory=False),
                session_audit=audit_session_events(events), collab_call_count=0, file_change_count=0, skill_tree_unchanged=True,
                created_source_files=(), modified_source_files=(), deleted_source_files=())
            result.facts_dict = lambda: {"thread_id": self.thread_id, "final_response": result.final_response, "exit_status": 0,
                "timed_out": False, "prompt_audit": {"passed": True, "has_memory": False}, "isolation_audit": {"passed": True},
                "skill_tree_unchanged": True, "skill_tree_sha256_before": INPUTS, "skill_tree_sha256_after": INPUTS,
                "command_facts": asdict(facts)}
            return result
    monkeypatch.setattr(runner, "CodexCliTask", FakeCli)
    target = "{11111111-1111-1111-1111-111111111111}"
    expected = {"name": "Target", "type": "GameParameter", "path": r"\Game Parameters\Target", "parent": "parent",
                "properties": {"Min": -12, "Max": 36, "InitialValue": 7}}
    before = {"objects": {target: {"id": target, **expected}}, "complete": True,
              "source_integrity": {"sha256": INPUTS, "mtime_ns": 1}, "media": {}}
    prepared = PreparedExpansionCase(prompt="Find the named parameter and report range and default.", policy=policy,
        operation="ak.wwise.core.object.get" if policy == "read_only" else "object.create", before=before, read_object_ids=frozenset({"{11111111-1111-1111-1111-111111111111}"}), relationship_sources=frozenset(),
        read_includes=frozenset(), required_assertions=F2_ASSERTIONS if policy == "read_only" else F3_ASSERTIONS, approve_preview=lambda _: False,
        snapshot=lambda: before, verify=lambda old, new: verify_f2(old, new, expected=expected, target_id=target),
        archive_oracle_parameters={"target_id": target, "expected": expected})
    options = SimpleNamespace(skill_source=SKILL, model="gpt-5.6-terra", reasoning_effort="medium", service_tier="default",
        campaign_inputs_sha256=INPUTS, codex_binary=tmp_path / "fake-codex", auth_json=tmp_path / "auth", windows_powershell_core_host=None)
    options.codex_binary.write_text("fake external CLI")
    root = tmp_path / "task"
    outcome = runner.run_expansion_codex_task(unit=SimpleNamespace(unit_id="REPAIR25-F2" if policy == "read_only" else "REPAIR25-F3", version="2025.1"), prepared=prepared,
        task_root=root, options=options, runner_environment={}, scoped_paths={}, reconcile_after_failure=lambda: {
            "status": "completed", "child_reaped": True, "subprocesses_reaped": True, "snapshot": before, "snapshot_sha256": canonical_digest(before), "elapsed_seconds": .1,
            "seconds": 30, "read_seconds": 10})
    return root, outcome, held


def test_authenticated_read_rejection_preserves_real_task_fail_and_read_only_notice(tmp_path, monkeypatch):
    root, outcome, held = produce_rejected_task(tmp_path, monkeypatch)
    assert outcome["status"] == "FAIL", outcome
    assert outcome["passed"] is False
    grade = json.loads((root / "turns/turn-01/turn-grade.json").read_text())
    assert grade["common_gates"]["visible_preview_notice"] is True
    assert set(grade["errors"]) == {"broker_provenance", "policy_checkpoint"}
    replay = verify_expansion_task_archive(root, expected_unit_id="REPAIR25-F2", expected_version="2025.1", expected_inputs_sha256=INPUTS)
    assert replay["archive_valid"] is True and replay["original_status"] == "FAIL" and replay["business_pass"] is False
    assert replay["executions"] == replay["execution_reservations"] == 0


def test_read_only_task_instructions_and_plan_use_query_reference(tmp_path, monkeypatch):
    root, _, held = produce_rejected_task(tmp_path, monkeypatch)
    plan = json.loads((root / "expansion-plan.json").read_text())
    assert plan.get("skill_read_schedule") == [["SKILL.md", "references/waapi-query.md"]]
    assert "waapi-query.md" in held["instructions"]
    assert "waapi-operate.md" not in held["instructions"]


@pytest.mark.parametrize("fault", [None, "authentication", "false_notice", "source", "cleanup", "schedule"])
def test_real_rejected_task_isolates_only_with_truthful_archive_source_and_cleanup(tmp_path, monkeypatch, fault):
    from tests.semantic.run_codex_skill_matrix import expansion_case_isolated
    root, outcome, _ = produce_rejected_task(tmp_path, monkeypatch)
    lifecycle = {"scenario_id": "REPAIR25-F2", "version": "2025.1", "source_hash_before": {"sha256": "source"},
        "source_hash_after": {"sha256": "source"}, "source_mtime_before_ns": 1, "source_mtime_after_ns": 1, "errors": []}
    if fault == "source": lifecycle["source_hash_after"] = {"sha256": "changed"}
    elif fault == "cleanup": lifecycle["errors"] = ["cleanup: unproved"]
    elif fault in {"authentication", "false_notice", "schedule"}:
        name = {"authentication": "expansion-broker.json", "false_notice": "turns/turn-01/turn-grade.json", "schedule": "expansion-plan.json"}[fault]
        path = root / name; value = json.loads(path.read_text())
        if fault == "authentication": value["records"][-1]["authenticated"] = False
        elif fault == "false_notice": value["common_gates"]["visible_preview_notice"] = False
        else:
            value["skill_read_schedule"] = [["SKILL.md", "references/waapi-operate.md"]]
            value.pop("sha256"); value["sha256"] = canonical_digest(value)
            result_path = root / "expansion-task-result.json"
            result = json.loads(result_path.read_text()); result["plan_sha256"] = value["sha256"]
            result_path.write_text(json.dumps(result))
        path.write_text(json.dumps(value))
    record = {"scenario_id": "REPAIR25-F2", "version": "2025.1", "status": "FAIL", "scenario_root": str(tmp_path),
        "runner_outcome": {"task_root": str(root), "inputs_sha256": INPUTS, "checks": {"trusted_oracle_closed": True}, "lifecycle": lifecycle}}
    assert expansion_case_isolated(record) is (fault is None)


@pytest.mark.parametrize("failed_case", ["F2", "F3"])
def test_formal_matrix_continues_after_archived_ordinary_admission_failure(tmp_path, monkeypatch, failed_case):
    from tests.semantic import run_codex_skill_matrix as matrix
    from tests.semantic.support.codex_expansion_runtime import ExpansionOutcome
    from tests.semantic.test_codex_repair_cli_wiring import options
    ids = ["REPAIR25-F2", "REPAIR25-F3", "REPAIR25-F4"] if failed_case == "F2" else ["REPAIR25-F3", "REPAIR25-F4"]
    selected = options(tmp_path, monkeypatch, "matrix", *[part for value in ids for part in ("--case-id", value)])
    monkeypatch.setattr(matrix, "prepare_iteration_root", lambda path, **_: path.mkdir())
    called = []
    def execute(unit, *, scenario_root, options):
        called.append(unit.unit_id)
        if unit.case_id != failed_case:
            raise RuntimeError("fake executor ends after proving next workflow was reached")
        scenario_root.mkdir(parents=True)
        kwargs = {} if failed_case == "F2" else {"policy": "allow_changes", "rejected_argv": ["draft-start", "ak.wwise.core.gameParameter.setRange"]}
        task_root, outcome, _ = produce_rejected_task(scenario_root, monkeypatch, **kwargs)
        lifecycle = {"scenario_id": unit.unit_id, "version": unit.version, "source_hash_before": {"sha256": "source"},
            "source_hash_after": {"sha256": "source"}, "source_mtime_before_ns": 1, "source_mtime_after_ns": 1, "errors": []}
        return ExpansionOutcome(unit.unit_id, unit.version, "FAIL", "ordinary invalid query", str(scenario_root),
            str(task_root), outcome["thread_id"], {"trusted_oracle_closed": True}, lifecycle, INPUTS)
    assert matrix.run_heavy_v3_matrix(selected, unit_runner=execute, dependency_preflight=lambda: {"ok": True}) == 1
    assert called[:2] == ids[:2]
    summary = json.loads((selected.iteration_root / "summary.json").read_text())
    assert summary["failed_unit_ids"] == [ids[0]]
    assert summary["all_selected_passed"] is False


def test_current_mutation_task_keeps_operate_reference(tmp_path, monkeypatch):
    root, _, held = produce_rejected_task(tmp_path, monkeypatch, policy="allow_changes")
    plan = json.loads((root / "expansion-plan.json").read_text())
    assert plan["skill_read_schedule"] == [["SKILL.md", "references/waapi-operate.md"]]
    assert "waapi-operate.md" in held["instructions"]
    assert "waapi-query.md" not in held["instructions"]


@pytest.mark.parametrize("copies", [("expansion-task-result.json",), ("expansion-oracle.json",),
    ("expansion-task-result.json", "expansion-oracle.json")])
@pytest.mark.parametrize("fault", ["changed", "missing", "extra", "non_boolean"])
def test_failed_read_assertions_must_replay_exactly_in_both_copies(tmp_path, monkeypatch, copies, fault):
    root, _, _ = produce_rejected_task(tmp_path, monkeypatch)
    for name in copies:
        path = root / name; value = json.loads(path.read_text())
        if fault == "changed": value["assertions"]["source_unchanged"] = False
        elif fault == "missing": del value["assertions"]["source_unchanged"]
        elif fault == "extra": value["assertions"]["unreviewed"] = True
        else: value["assertions"]["source_unchanged"] = 1
        path.write_text(json.dumps(value))
    with pytest.raises(ExpansionArchiveError, match="read-only repair oracle replay mismatch"):
        verify_expansion_task_archive(root, expected_unit_id="REPAIR25-F2", expected_version="2025.1", expected_inputs_sha256=INPUTS)
    from tests.semantic.run_codex_skill_matrix import expansion_case_isolated
    lifecycle = {"scenario_id": "REPAIR25-F2", "version": "2025.1", "source_hash_before": {"sha256": "source"},
        "source_hash_after": {"sha256": "source"}, "source_mtime_before_ns": 1, "source_mtime_after_ns": 1, "errors": []}
    record = {"scenario_id": "REPAIR25-F2", "version": "2025.1", "status": "FAIL", "scenario_root": str(tmp_path),
        "runner_outcome": {"task_root": str(root), "inputs_sha256": INPUTS, "checks": {"trusted_oracle_closed": True}, "lifecycle": lifecycle}}
    assert not expansion_case_isolated(record)
