"""Synthetic authenticated receipts exercise the existing offline archive seam."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shlex
import shutil

import pytest
from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive, ExpansionArchiveError
from tests.semantic.support.codex_expansion_policy import ExpansionReadScope, canonical_digest
from tests.semantic.support.codex_repair_cases import F2_ASSERTIONS
from tests.semantic.test_codex_expansion_archive import _sealed_c08, _write, INPUTS
from tests.semantic.support.codex_harness import completed_command_records

TARGET = "{22222222-2222-2222-2222-222222222222}"


def sealed_read_archive(root):
    _sealed_c08(root)
    shutil.rmtree(root / "broker/state/transactions")
    plan = json.loads((root / "expansion-plan.json").read_text())
    plan.pop("sha256")
    expected = {"name": "Repair_WindVelocity", "type": "GameParameter", "path": r"\Game Parameters\Default Work Unit\Repair_WindVelocity",
                "parent": "{11111111-1111-1111-1111-111111111111}", "properties": {"Min": -12, "Max": 36, "InitialValue": 7}}
    before = {"objects": {TARGET: {"id": TARGET, **expected}}, "complete": True,
        "source_integrity": {"sha256": "a" * 64, "mtime_ns": 42}, "media": {}}
    scope = ExpansionReadScope(frozenset({TARGET}), frozenset({"ak.wwise.core.object.get"}), owned_project_reads=True)
    plan.update(contract="waapi-skill.repair-task-plan/v1", unit_id="REPAIR25-F2", policy="read_only",
        operation="ak.wwise.core.object.get", request_schema_uri=None, prompts=["Inspect the parameter, refining a missed spelling."],
        before=before, required_assertions=sorted(F2_ASSERTIONS),
        read_scope={key: sorted(value) if isinstance(value, frozenset) else value for key, value in asdict(scope).items()},
        read_scope_sha256=scope.digest, oracle_parameters={"expected": expected, "target_id": TARGET}, preview_parameters={})
    digest = canonical_digest(plan)
    _write(root / "expansion-plan.json", {**plan, "sha256": digest})
    assertions = {name: True for name in F2_ASSERTIONS}
    _write(root / "expansion-oracle.json", {"before": before, "after": before, "assertions": assertions,
        "transaction_id": None, "artifact_hash": None, "gateway_verification_state": None})
    old_events = [json.loads(line) for line in (root / "turns/turn-01/events.jsonl").read_text().splitlines()]
    events = old_events[:4]
    records = []
    for index, word in enumerate(("Missing", "Repair_Wind"), 1):
        argv = ["query-object", "--search-text", word, "--max-results", "10"]
        rows = [] if index == 1 else [{"id": TARGET, **expected}]
        payload = {"ok": True, "command": "query-object", "count": len(rows), "objects": rows,
                   "query_bound": {"mode": "take", "value": 10}, "limit_reached": False}
        runner = str(Path(plan["skill_source"]) / "scripts/run.py")
        model_argv = ["python", runner, "gateway.py", *argv]
        stdout = json.dumps(payload)
        records.append({"sequence": index, "step_name": f"expansion.step.{index:04d}",
            "model_argv": model_argv, "normalized_model_argv": model_argv, "gateway_arguments": argv,
            "raw_argv_sha256": canonical_digest(model_argv), "argv_sha256": canonical_digest(model_argv),
            "semantic_argv_sha256": canonical_digest(["runner-owned-version", "2025.1", *argv]),
            "payload_sha256": canonical_digest(payload),
            "runner_command_sha256": canonical_digest([plan["trusted_python"], runner, "gateway.py", *argv]),
            "authenticated": True, "accepted": True, "succeeded": True, "payload": payload, "stdout": stdout,
            "exit_code": 0, "runner_exit_code": 0, "allowed_exit_codes": [0], "payload_error": "",
            "started_at_unix": index, "finished_at_unix": index + .1, "duration_seconds": .1})
        item = {"id": f"cmd-{index}", "type": "command_execution", "command": shlex.join(model_argv),
                "status": "completed", "exit_code": 0, "aggregated_output": stdout}
        events.extend([{"type": "item.started", "item": {**item, "status": "in_progress"}}, {"type": "item.completed", "item": item}])
    final = "Repair_WindVelocity has range -12 to 36 and default 7."
    events.extend([{"type": "item.completed", "item": {"id": "final", "type": "agent_message", "text": final}}, {"type": "turn.completed"}])
    names = [row["step_name"] for row in records]
    _write(root / "expansion-broker.json", {"records": records, "passed": True, "complete": True,
        "expected_step_names": names, "consumed_step_names": names})
    result = json.loads((root / "expansion-task-result.json").read_text())
    result.update(unit_id="REPAIR25-F2", plan_sha256=digest, assertions=assertions, gateway_verification_state=None)
    _write(root / "expansion-task-result.json", result)
    directory = root / "turns/turn-01"
    grade = json.loads((directory / "turn-grade.json").read_text())
    grade.update(prompt_sha256=hashlib.sha256(plan["prompts"][0].encode()).hexdigest(), broker_prefix_count=2)
    _write(directory / "turn-grade.json", grade)
    facts = json.loads((directory / "codex-facts.json").read_text())
    facts.update(final_response=final, command_facts={"command_records": [asdict(row) for row in completed_command_records(events, platform_name="posix")]})
    _write(directory / "codex-facts.json", facts)
    (directory / "events.jsonl").write_text("".join(json.dumps(row) + "\n" for row in events))
    (directory / "final.txt").write_text(final + "\n")
    (directory / "prompt.txt").write_text(plan["prompts"][0] + "\n")


def test_read_only_repair_archive_replays_without_inventing_transaction(tmp_path):
    sealed_read_archive(tmp_path)
    result = verify_expansion_task_archive(tmp_path, expected_unit_id="REPAIR25-F2", expected_version="2025.1", expected_inputs_sha256=INPUTS)
    assert result["business_pass"] and result["executions"] == 0


@pytest.mark.parametrize("damage", ["source", "target", "no_miss", "extra_transaction"])
def test_repair_archive_rejects_changed_state_missing_refinement_or_extra_write(tmp_path, damage):
    sealed_read_archive(tmp_path)
    if damage == "extra_transaction":
        (tmp_path / "broker/state/transactions/tx1-extra").mkdir(parents=True)
    elif damage in {"source", "target"}:
        path = tmp_path / "expansion-oracle.json"
        value = json.loads(path.read_text())
        if damage == "source":
            value["after"]["source_integrity"]["mtime_ns"] += 1
        else:
            value["after"]["objects"][TARGET]["properties"]["InitialValue"] = 8
        _write(path, value)
    else:
        path = tmp_path / "expansion-broker.json"
        value = json.loads(path.read_text())
        value["records"][0]["payload"]["objects"] = value["records"][1]["payload"]["objects"]
        _write(path, value)
    with pytest.raises(ExpansionArchiveError):
        verify_expansion_task_archive(tmp_path, expected_unit_id="REPAIR25-F2", expected_version="2025.1", expected_inputs_sha256=INPUTS)
