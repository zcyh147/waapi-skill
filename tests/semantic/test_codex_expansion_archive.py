"""Read-only expansion replay rejects missing or inconsistent sealed evidence."""

import json
import hashlib
import shlex
import sys
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import pytest

from tests.semantic.support.codex_expansion_archive import (
    ExpansionArchiveError, verify_expansion_boundary_archive,
    verify_expansion_task_archive, _authorization, _receipts,
)
from tests.semantic.support.codex_expansion_policy import canonical_digest
from tests.semantic.support.codex_expansion_policy import ExpansionReadScope
from tests.semantic.support.codex_expansion_attenuation_case import C08_ASSERTIONS, verify_c08
from tests.semantic.support.codex_harness import completed_command_records
from tests.semantic.test_codex_transaction_seal import _artifact
from wwise_waapi.transactions import TransactionStore


INPUTS = "a" * 64


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _verify(root):
    return verify_expansion_task_archive(root, expected_unit_id="EXP25-C08",
        expected_version="2025.1", expected_inputs_sha256=INPUTS)


def test_missing_task_archive_is_rejected_without_creating_any_files(tmp_path):
    root = tmp_path / "absent"
    with pytest.raises(ExpansionArchiveError):
        _verify(root)
    assert not root.exists()


def test_plan_digest_and_candidate_binding_are_mandatory(tmp_path):
    plan = {"contract": "waapi-skill.integration-expansion-task-plan/v1",
            "unit_id": "EXP25-C08", "version": "2025.1", "inputs_sha256": "b" * 64}
    _write(tmp_path / "expansion-plan.json", {**plan, "sha256": canonical_digest(plan)})
    with pytest.raises(ExpansionArchiveError, match="inputs"):
        _verify(tmp_path)
    plan["inputs_sha256"] = INPUTS
    _write(tmp_path / "expansion-plan.json", {**plan, "sha256": "0" * 64})
    with pytest.raises(ExpansionArchiveError, match="digest"):
        _verify(tmp_path)


def test_archive_rejects_duplicate_json_keys_and_symlinks(tmp_path):
    path = tmp_path / "expansion-plan.json"
    path.write_text('{"contract":"one","contract":"two"}', encoding="utf-8")
    with pytest.raises(ExpansionArchiveError, match="duplicate"):
        _verify(tmp_path)
    path.unlink()
    outside = tmp_path / "other.json"
    outside.write_text("{}", encoding="utf-8")
    path.symlink_to(outside)
    with pytest.raises(ExpansionArchiveError):
        _verify(tmp_path)


def test_boundary_never_counts_as_an_agent_or_business_pass(tmp_path):
    evidence = {
        "public_observation": {"ok": True, "status": "needs_clarification", "agent_result": {
            "unresolved": [{"meaning": "Trigger", "candidate_names": []},
                           {"meaning": "Segment", "candidate_names": ["Other"]}]}},
        "identity_before": {"id": "{11111111-1111-1111-1111-111111111111}"},
        "identity_after": {"id": "{11111111-1111-1111-1111-111111111111}"},
        "agent_executed": False, "business_effect_verified": False,
    }
    outcome = {"scenario_id": "EXP22-M05", "version": "2022.1", "status": "BOUNDARY_PROVEN",
        "inputs_sha256": INPUTS, "task_root": None, "thread_id": None,
        "checks": {"capability_boundary": {"case_id": "M05", "version": "2022.1",
            "boundary_code": "CAPABILITY_UNAVAILABLE", "evidence": evidence,
            "agent_started": False, "business_pass": False}}}
    _write(tmp_path / "outcome.json", outcome)
    result = verify_expansion_boundary_archive(tmp_path, expected_unit_id="EXP22-M05",
        expected_version="2022.1", expected_inputs_sha256=INPUTS)
    assert result["boundary_proven"] is True
    assert result["business_pass"] is False and result["agent_started"] is False
    outcome["checks"]["capability_boundary"]["business_pass"] = True
    _write(tmp_path / "outcome.json", outcome)
    with pytest.raises(ExpansionArchiveError):
        verify_expansion_boundary_archive(tmp_path, expected_unit_id="EXP22-M05",
            expected_version="2022.1", expected_inputs_sha256=INPUTS)


def _sealed_c08(root: Path, *, passed=True, rejected_preview=False):
    identifier = "{11111111-1111-1111-1111-111111111111}"
    tx = "tx1-00000000000000000001"
    points = [{"x": 0, "y": 0, "shape": "Linear"}, {"x": 100, "y": -48, "shape": "Linear"}]
    preview_points = ([{"x": 0, "y": 0, "shape": "Linear"}, {"x": 80, "y": -48, "shape": "Linear"}]
                      if rejected_preview else points)
    before = {"attenuation": {"id": identifier, "name": "FixtureAttenuation"}, "users": {"sound": {"id": identifier}},
              "source": {"id": identifier, "notes": "original"}, "curves": {
        "volume-dry": {"use": "Custom", "points": [{"x": 0, "y": -6, "shape": "Linear"}]},
        "spread": {"use": "Custom", "points": [{"x": 0, "y": 50, "shape": "Linear"}]}}}
    after = deepcopy(before)
    after["curves"]["volume-dry"] = {"use": "Custom", "points": points}
    artifact = _artifact()
    for key in ("request", "project_guard", "runtime_guard"):
        artifact[key]["version"] = "2025.1"
    for key in ("project_guard", "runtime_guard"):
        body = {name: value for name, value in artifact[key].items() if name not in {"contract", "fingerprint"}}
        artifact[key]["fingerprint"] = canonical_digest(body)
    api = "ak.wwise.core.object.setAttenuationCurve"
    artifact["request"].update(operation="waapi.call", arguments={"api": api, "options": {}, "args": {
        "object": identifier, "curveType": "VolumeDryUsage", "use": "Custom", "points": preview_points}})
    artifact["prepared_operation"]["operation"] = "waapi.call"
    store = TransactionStore(root / "broker" / "state")
    store.create_preview(tx, artifact)
    authority = "caller_asserted_current_user_change_request"
    if not rejected_preview:
        store.transition(tx, "policy_authorized", expected_state="draft", event_type="policy_authorized",
                         details={"policy": "allow_changes", "authority": authority, "explicit_confirmation": False})
        store.begin_execution(tx, expected_authorization="policy_authorized")
        store.mark_executed_unverified(tx)
        store.record_verification(tx, outcome="result_schema_checked")
    scope = ExpansionReadScope(frozenset({identifier}), frozenset({api}))
    plan = {"contract": "waapi-skill.integration-expansion-task-plan/v1", "unit_id": "EXP25-C08",
        "version": "2025.1", "inputs_sha256": INPUTS, "policy": "allow_changes", "prompts": ["Perform this change."],
        "before": before, "required_assertions": sorted(C08_ASSERTIONS), "operation": "waapi.call",
        "request_schema_uri": api, "platform_name": "posix", "windows_powershell_core_host": None,
        "skill_source": str(Path(__file__).resolve().parents[2] / "skills" / "waapi-skill"),
        "trusted_python": str(Path(sys.executable).resolve()),
        "read_scope": {key: sorted(value) if isinstance(value, frozenset) else value for key, value in asdict(scope).items()},
        "read_scope_sha256": scope.digest, "oracle_parameters": {"expected_points": points},
        "preview_parameters": {"version": "2025.1", "object_id": identifier, "expected_points": points}}
    digest = canonical_digest(plan)
    _write(root / "expansion-plan.json", {**plan, "sha256": digest})
    artifact_hash = canonical_digest(artifact)
    assertions = {} if rejected_preview else verify_c08(before, after, expected_points=points)
    oracle = {"before": before, "after": None if rejected_preview else after,
        "preview_before": before, "preview_after": before, "assertions": assertions,
        "transaction_id": tx, "artifact_hash": artifact_hash,
        "gateway_verification_state": None if rejected_preview else "result_schema_checked",
        "authorization": None if rejected_preview else {
            "mode": "policy_authorization", "authority": authority, "explicit_confirmation": False},
        "permit": None if rejected_preview else {
            "transaction_id": tx, "artifact_sha256": artifact_hash, "authorization_nonce": "b" * 64,
            "preview_turn": 1, "authorized_turn": 1},
        "preview_approved": not rejected_preview}
    if rejected_preview:
        oracle["reconciliation"] = {"status": "completed", "seconds": 30, "read_seconds": 10,
            "elapsed_seconds": 1, "child_reaped": True, "subprocesses_reaped": True,
            "snapshot": before, "snapshot_sha256": canonical_digest(before)}
    _write(root / "expansion-oracle.json", oracle)
    argv_rows = [["draft-start", api], ["preview-from-draft", "draft", "--task-authority", "auth", "--expected-revision", "1"]]
    if not rejected_preview:
        argv_rows.extend([["execute", tx], ["verify", tx]])
    records, events = [], [{"type": "thread.started", "thread_id": "thread"}, {"type": "turn.started"}]
    skill_path = Path(plan["skill_source"]) / "SKILL.md"
    skill_read = {"id": "read-skill", "type": "command_execution", "command": shlex.join(["cat", str(skill_path)]),
                  "status": "completed", "exit_code": 0, "aggregated_output": skill_path.read_text()}
    events.extend([{"type": "item.started", "item": {**skill_read, "status": "in_progress"}},
                   {"type": "item.completed", "item": skill_read}])
    for index, argv in enumerate(argv_rows, 1):
        payload = {"ok": True, "command": argv[0]}
        if argv[0] == "draft-start":
            payload.update(draft={"draft_id": "draft", "revision": 1}, task_authority="auth")
        else:
            payload.update(transaction_id=tx, artifact_hash=artifact_hash)
        if argv[0] == "execute":
            payload["state"] = "executed_unverified"
        if argv[0] == "verify":
            payload["state"] = "result_schema_checked"
        model_argv = ["python", plan["skill_source"] + "/scripts/run.py", "gateway.py", *argv]
        semantic = ["runner-owned-version", "2025.1", *argv]
        if "--expected-revision" in argv:
            semantic[-1] = 1
        stdout = json.dumps(payload)
        records.append({"sequence": index, "step_name": f"expansion.step.{index:04d}",
            "model_argv": model_argv, "normalized_model_argv": model_argv, "gateway_arguments": argv,
            "raw_argv_sha256": canonical_digest(model_argv), "argv_sha256": canonical_digest(model_argv),
            "semantic_argv_sha256": canonical_digest(semantic), "payload_sha256": canonical_digest(payload),
            "runner_command_sha256": canonical_digest([plan["trusted_python"], plan["skill_source"] + "/scripts/run.py", "gateway.py", *argv]),
            "authenticated": True, "accepted": True, "succeeded": True, "payload": payload, "stdout": stdout,
            "exit_code": 0, "runner_exit_code": 0, "allowed_exit_codes": [0], "payload_error": "",
            "started_at_unix": index, "finished_at_unix": index + .1, "duration_seconds": .1})
        command = {"id": f"cmd-{index}", "type": "command_execution", "command": shlex.join(model_argv),
                   "status": "completed", "exit_code": 0, "aggregated_output": stdout}
        events.extend([{"type": "item.started", "item": {**command, "status": "in_progress"}},
                       {"type": "item.completed", "item": command}])
        if argv[0] == "preview-from-draft":
            events.append({"type": "item.completed", "item": {
                "id": "preview-notice", "type": "agent_message", "text": (
                    "The preview does not match the requested curve; I will not execute it."
                    if rejected_preview else
                    "The preview updates FixtureAttenuation's dry volume curve; applying it now.")}})
    final_response = ("I did not execute because the immutable Preview did not match the requested curve."
                      if rejected_preview else "Done.")
    events.extend([{"type": "item.completed", "item": {"id": "message", "type": "agent_message", "text": final_response}},
                   {"type": "turn.completed"}])
    names = [record["step_name"] for record in records]
    _write(root / "expansion-broker.json", {"records": records, "passed": not rejected_preview,
        "complete": not rejected_preview,
        "expected_step_names": names, "consumed_step_names": names})
    gates = {key: True for key in ("memory_isolated", "completed_turn", "one_target_skill", "no_collaboration",
        "only_packaged_references", "only_authenticated_gateway_and_skill_reads", "no_discovery_or_direct_waapi",
        "no_write_like_commands", "source_and_workspace_unchanged", "broker_provenance", "policy_checkpoint", "visible_preview_notice",
        "final_response_present", "cumulative_agent_budget")}
    if rejected_preview:
        gates["policy_checkpoint"] = False
    turns = [{"index": 1, "gates": gates, "agent_seconds": 12}]
    _write(root / "expansion-agent-budget.json", {"hard_seconds": 600, "slow_seconds": 420,
        "elapsed_seconds": 12, "slow": False, "turns": turns,
        "turn_measurements": [{"started_monotonic": 100, "finished_monotonic": 112, "elapsed_seconds": 12}]})
    _write(root / "expansion-task-result.json", {"unit_id": "EXP25-C08", "version": "2025.1",
        "passed": passed and not rejected_preview,
        **({"status": "FAIL"} if rejected_preview else {}),
        "thread_id": "thread", "plan_sha256": digest, "assertions": assertions,
        "agent_seconds": 12, "slow": False, "turns": turns,
        "gateway_verification_state": None if rejected_preview else "result_schema_checked"})
    directory = root / "turns" / "turn-01"
    _write(directory / "turn-grade.json", {"index": 1, "prompt_sha256": hashlib.sha256(plan["prompts"][0].encode()).hexdigest(),
        "common_gates": gates, "broker_prefix_count": len(records),
        "passed": not rejected_preview, "errors": ["policy checkpoint failed"] if rejected_preview else []})
    _write(directory / "codex-facts.json", {"thread_id": "thread", "final_response": final_response,
        "exit_status": 0, "timed_out": False, "prompt_audit": {"passed": True, "has_memory": False},
        "isolation_audit": {"passed": True}, "skill_tree_unchanged": True,
        "skill_tree_sha256_before": INPUTS, "skill_tree_sha256_after": INPUTS,
        "command_facts": {"command_records": [asdict(row) for row in completed_command_records(events, platform_name="posix")]}})
    (directory / "events.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))
    (directory / "prompt.txt").write_text(plan["prompts"][0] + "\n")
    (directory / "final.txt").write_text(final_response + "\n")
    (directory / "stderr.txt").write_text("")


def test_complete_archive_replays_real_store_without_writing_or_upgrading_failure(tmp_path):
    _sealed_c08(tmp_path, passed=False)
    before = {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob("*") if path.is_file()}
    result = _verify(tmp_path)
    assert result["archive_valid"] is True and result["original_status"] == "FAIL"
    assert result["business_pass"] is False and result["executions"] == 1
    after = {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before


def test_complete_archive_retains_weaker_gateway_verification(tmp_path):
    _sealed_c08(tmp_path)
    result = _verify(tmp_path)
    assert result["business_pass"] is True
    assert result["gateway_verification_state"] == "result_schema_checked"


def test_rejected_wrong_effect_preview_replays_as_fail_without_execution_or_writes(tmp_path):
    _sealed_c08(tmp_path, rejected_preview=True)
    before = {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
              for path in tmp_path.rglob("*") if path.is_file()}

    result = _verify(tmp_path)

    assert result["archive_valid"] is True and result["original_status"] == "FAIL"
    assert result["business_pass"] is False
    assert result["preview_approved"] is False and result["executions"] == 0
    oracle = json.loads((tmp_path / "expansion-oracle.json").read_text())
    broker = json.loads((tmp_path / "expansion-broker.json").read_text())
    assert oracle["transaction_id"] == "tx1-00000000000000000001"
    assert oracle["artifact_hash"] == broker["records"][1]["payload"]["artifact_hash"]
    assert oracle["authorization"] is None and oracle["permit"] is None
    assert [row["gateway_arguments"][0] for row in broker["records"]] == ["draft-start", "preview-from-draft"]
    transaction_root = tmp_path / "broker" / "state" / "transactions" / oracle["transaction_id"]
    state = json.loads((transaction_root / "state.json").read_text())
    events = [json.loads(line) for line in (transaction_root / "events.jsonl").read_text().splitlines()]
    assert state["state"] == "draft" and [event["to_state"] for event in events] == ["draft"]
    after = {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
             for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before


@pytest.mark.parametrize("tamper", ("true", "missing"))
def test_rejected_preview_requires_explicit_adapter_matched_false_approval(tmp_path, tamper):
    _sealed_c08(tmp_path, rejected_preview=True)
    path = tmp_path / "expansion-oracle.json"
    oracle = json.loads(path.read_text())
    if tamper == "true":
        oracle["preview_approved"] = True
    else:
        del oracle["preview_approved"]
    _write(path, oracle)

    with pytest.raises(ExpansionArchiveError, match="preview approval record"):
        _verify(tmp_path)


@pytest.mark.parametrize("missing_after", (False, True))
def test_passing_archive_requires_independent_post_state_for_oracle_replay(tmp_path, missing_after):
    _sealed_c08(tmp_path)
    path = tmp_path / "expansion-oracle.json"
    oracle = json.loads(path.read_text())
    if missing_after:
        del oracle["after"]
    else:
        oracle["after"] = None
    _write(path, oracle)
    with pytest.raises(ExpansionArchiveError, match="post-state"):
        _verify(tmp_path)


@pytest.mark.parametrize("damage", ("receipt", "oracle", "permit", "budget", "journal", "second_execute", "raw_commands"))
def test_archive_rejects_broken_independent_evidence(tmp_path, damage):
    _sealed_c08(tmp_path)
    filename = {"receipt": "expansion-broker.json", "oracle": "expansion-oracle.json",
        "permit": "expansion-oracle.json", "budget": "expansion-agent-budget.json",
        "second_execute": "expansion-broker.json", "raw_commands": "turns/turn-01/codex-facts.json"}.get(damage)
    if damage == "journal":
        path = next(tmp_path.glob("broker/state/transactions/*/events.jsonl"))
        path.write_text(path.read_text().replace('"policy":"allow_changes"', '"policy":"read_only"'))
    else:
        path = tmp_path / filename
        value = json.loads(path.read_text())
        if damage == "receipt":
            value["records"][2]["payload"]["artifact_hash"] = "c" * 64
        elif damage == "oracle":
            value["after"]["source"]["notes"] = "changed"
        elif damage == "permit":
            value["permit"]["artifact_sha256"] = "c" * 64
        elif damage == "budget":
            value["turn_measurements"][0]["finished_monotonic"] = 113
        elif damage == "raw_commands":
            value["command_facts"]["command_records"] = []
        else:
            value["records"].append(deepcopy(value["records"][2]))
            value["records"][-1]["sequence"] = 5
        _write(path, value)
    with pytest.raises(ExpansionArchiveError):
        _verify(tmp_path)


def test_ask_authorization_requires_later_turn_and_exact_real_confirmation_token(tmp_path):
    tx = "tx1-00000000000000000001"
    store = TransactionStore(tmp_path)
    artifact = _artifact()
    store.create_preview(tx, artifact)
    store.submit_for_confirmation(tx)
    snapshot = store.load_snapshot(tx)
    token = snapshot.confirmation_token
    store.confirm(tx, confirmation_token=token)
    store.begin_execution(tx, expected_authorization="confirmed")
    preview, events = store.load_preview(tx).as_dict(), list(store.read_events(tx))
    receipt = {"transaction_id": tx, "artifact_hash": preview["artifact_hash"]}
    records = [{"accepted": True, "sequence": index, "gateway_arguments": argv, "payload": receipt}
               for index, argv in enumerate([
                   ["preview-from-draft", "draft"], ["confirm", tx, "--confirmation-token", token], ["execute", tx]], 1)]
    oracle = {"authorization": {"mode": "explicit_confirmation", "explicit_confirmation": True},
        "permit": {"transaction_id": tx, "artifact_sha256": preview["artifact_hash"],
                   "authorization_nonce": "b" * 64, "preview_turn": 1, "authorized_turn": 2}}
    _authorization({"policy": "ask_before_changes"}, oracle, events, records, [{}, {}], preview, [1, 3])
    with pytest.raises(ExpansionArchiveError, match="later user turn"):
        _authorization({"policy": "ask_before_changes"}, oracle, events, records, [{}, {}], preview, [2, 3])
    records[1]["gateway_arguments"][-1] = "ct1-" + "0" * 24
    with pytest.raises(ExpansionArchiveError, match="token"):
        _authorization({"policy": "ask_before_changes"}, oracle, events, records, [{}, {}], preview, [1, 3])
    records[1]["gateway_arguments"] = ["confirm", tx, "--artifact-hash", preview["artifact_hash"]]
    with pytest.raises(ExpansionArchiveError, match="token"):
        _authorization({"policy": "ask_before_changes"}, oracle, events, records, [{}, {}], preview, [1, 3])


def test_failed_incomplete_turn_preserves_measured_time_without_a_new_grade(tmp_path):
    _sealed_c08(tmp_path, passed=False)
    budget_path = tmp_path / "expansion-agent-budget.json"
    budget = json.loads(budget_path.read_text())
    budget["turns"] = [{"index": 1, "agent_seconds": 12, "gates": {}, "incomplete": True}]
    _write(budget_path, budget)
    result_path = tmp_path / "expansion-task-result.json"
    result = json.loads(result_path.read_text())
    result["turns"] = budget["turns"]
    _write(result_path, result)
    grade = tmp_path / "turns/turn-01/turn-grade.json"
    grade.unlink()
    replay = _verify(tmp_path)
    assert replay["business_pass"] is False and replay["agent_seconds"] == 12
    assert not grade.exists()


@pytest.mark.parametrize("command", ("query-object", "draft-check", "execute"))
def test_failed_accepted_receipt_can_replay_without_json(tmp_path, command):
    _sealed_c08(tmp_path, passed=False)
    plan = json.loads((tmp_path / "expansion-plan.json").read_text())
    broker = json.loads((tmp_path / "expansion-broker.json").read_text())
    record = broker["records"][2]
    if command != "execute":
        argv = (["query-object", "--exact-id", next(iter(plan["read_scope"]["object_ids"]))]
                if command == "query-object" else ["draft-check", "draft", "--task-authority", "auth", "--expected-revision", "1"])
        record["gateway_arguments"] = argv
        record["model_argv"] = ["python", plan["skill_source"] + "/scripts/run.py", "gateway.py", *argv]
        record["normalized_model_argv"] = record["model_argv"]
        record["raw_argv_sha256"] = record["argv_sha256"] = canonical_digest(record["model_argv"])
        semantic = ["runner-owned-version", "2025.1", *argv]
        if command == "draft-check":
            semantic[-1] = 1
        record["semantic_argv_sha256"] = canonical_digest(semantic)
        record["runner_command_sha256"] = canonical_digest([plan["trusted_python"], plan["skill_source"] + "/scripts/run.py", "gateway.py", *argv])
    record.update(succeeded=False, payload=None, payload_sha256="", stdout="", exit_code=125,
                  runner_exit_code=None, payload_error="runner timeout; no complete JSON receipt")
    broker["records"] = [broker["records"][0], record]
    record["sequence"] = 2
    replayed = _receipts(tmp_path, plan, broker)
    assert replayed[-1]["succeeded"] is False


@pytest.mark.parametrize("dispatch_started", (False, True))
def test_failed_execute_reservation_is_not_proof_of_gateway_dispatch(tmp_path, dispatch_started):
    _sealed_c08(tmp_path, passed=False)
    broker_path = tmp_path / "expansion-broker.json"
    broker = json.loads(broker_path.read_text())
    broker["records"] = broker["records"][:3]
    broker["records"][-1].update(succeeded=False, payload=None, payload_sha256="", stdout="",
        exit_code=125, runner_exit_code=None, payload_error="runner timeout; no complete JSON receipt")
    broker.update(passed=False, complete=False)
    _write(broker_path, broker)
    directory = next(tmp_path.glob("broker/state/transactions/*"))
    events = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
    events = events[:3 if dispatch_started else 2]
    (directory / "events.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))
    state = json.loads((directory / "state.json").read_text())
    state.update(state=events[-1]["to_state"], event_sequence=len(events),
                 last_event_hash=events[-1]["event_hash"], updated_at=events[-1]["timestamp"])
    _write(directory / "state.json", state)
    oracle_path = tmp_path / "expansion-oracle.json"
    oracle = json.loads(oracle_path.read_text())
    oracle.update(after=None, assertions={}, gateway_verification_state=None, reconciliation={
        "status": "error", "seconds": 30, "read_seconds": 10, "elapsed_seconds": 1,
        "child_reaped": True, "subprocesses_reaped": True, "error": {"type": "TimeoutError", "message": "read timed out"}})
    _write(oracle_path, oracle)
    budget_path = tmp_path / "expansion-agent-budget.json"
    budget = json.loads(budget_path.read_text())
    budget["turns"] = [{"index": 1, "agent_seconds": 12, "gates": {}, "incomplete": True}]
    _write(budget_path, budget)
    result_path = tmp_path / "expansion-task-result.json"
    result = json.loads(result_path.read_text())
    result.update(turns=budget["turns"], assertions={}, gateway_verification_state=None, status="INDETERMINATE")
    _write(result_path, result)
    before = {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob("*") if path.is_file()}
    replay = _verify(tmp_path)
    assert replay["business_pass"] is False and replay["original_status"] == "INDETERMINATE"
    assert replay["execution_reservations"] == 1
    assert replay["executions"] == int(dispatch_started)
    assert {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("status", ("PASS", "BLOCKED", "INDETERMINATE"))
def test_archive_rejects_claimed_status_without_matching_original_proof(tmp_path, status):
    _sealed_c08(tmp_path, passed=False)
    path = tmp_path / "expansion-task-result.json"
    result = json.loads(path.read_text())
    result["status"] = status
    _write(path, result)
    with pytest.raises(ExpansionArchiveError, match="classification"):
        _verify(tmp_path)


@pytest.mark.parametrize("complete", (True, False))
def test_negative_archive_preserves_bounded_read_only_reconciliation_without_promoting_pass(tmp_path, complete):
    _sealed_c08(tmp_path, passed=False)
    path = tmp_path / "expansion-oracle.json"
    oracle = json.loads(path.read_text())
    receipt = {"status": "completed" if complete else "error", "seconds": 30, "read_seconds": 10,
               "elapsed_seconds": 1, "child_reaped": True, "subprocesses_reaped": True}
    if complete:
        receipt.update(snapshot=oracle["after"], snapshot_sha256=canonical_digest(oracle["after"]))
    else:
        receipt["error"] = {"type": "TimeoutError", "message": "oracle read timed out"}
    oracle["reconciliation"] = receipt
    _write(path, oracle)
    replay = _verify(tmp_path)
    assert replay["original_status"] == "FAIL" and replay["business_pass"] is False
    assert replay["reconciliation"]["status"] == receipt["status"]
    if complete:
        oracle["reconciliation"]["snapshot_sha256"] = "0" * 64
        _write(path, oracle)
        with pytest.raises(ExpansionArchiveError, match="reconciliation"):
            _verify(tmp_path)


def test_archive_preserves_blocked_infrastructure_only_from_raw_pre_action_events(tmp_path):
    donor = tmp_path / "complete-fixture"
    _sealed_c08(donor, passed=False)
    root = tmp_path / "blocked-fixture"
    plan = json.loads((donor / "expansion-plan.json").read_text())
    _write(root / "expansion-plan.json", plan)
    budget = json.loads((donor / "expansion-agent-budget.json").read_text())
    budget["turns"] = [{"index": 1, "agent_seconds": 12, "gates": {}, "incomplete": True}]
    _write(root / "expansion-agent-budget.json", budget)
    infrastructure = {"category": "authentication", "message": "authentication failed", "turn_failed": True,
                      "timed_out": False, "agent_item_event_count": 0}
    result = json.loads((donor / "expansion-task-result.json").read_text())
    result.update(status="BLOCKED", infrastructure=infrastructure, assertions={}, gateway_verification_state=None,
                  turns=budget["turns"])
    _write(root / "expansion-task-result.json", result)
    _write(root / "expansion-broker.json", {"records": [], "passed": False, "complete": False})
    _write(root / "expansion-oracle.json", {"before": plan["before"], "transaction_id": None,
        "reconciliation": {"status": "error", "seconds": 30, "read_seconds": 10, "elapsed_seconds": 1,
            "child_reaped": True, "subprocesses_reaped": True, "error": {"type": "TimeoutError", "message": "read timed out"}}})
    directory = root / "turns" / "turn-01"
    _write(directory / "codex-facts.json", {"timed_out": False})
    events = [{"type": "turn.failed", "error": {"message": "authentication failed"}}]
    (directory / "events.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))
    (directory / "stderr.txt").write_text("")
    replay = _verify(root)
    assert replay["original_status"] == "BLOCKED" and replay["business_pass"] is False
    events.append({"type": "item.completed", "item": {"type": "agent_message", "text": "Working"}})
    (directory / "events.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))
    with pytest.raises(ExpansionArchiveError, match="pre-action"):
        _verify(root)


def _realistic_command_paths(root):
    """CLI shell argv differs from the authenticated shim's received argv."""
    broker = json.loads((root / 'expansion-broker.json').read_text())
    directory = root / 'turns/turn-01'
    events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
    for record in broker['records']:
        old = shlex.join(record['model_argv'])
        raw = ['python', '.agents/skills/waapi-skill/scripts/run.py', 'gateway.py', *record['gateway_arguments']]
        record['model_argv'] = [str(root / 'broker/bin/python'), *raw[1:]]
        record['normalized_model_argv'] = ['python', str(root / 'agent-workspace/.agents/skills/waapi-skill/scripts/run.py'), 'gateway.py', *record['gateway_arguments']]
        record['raw_argv_sha256'] = canonical_digest(record['model_argv'])
        record['argv_sha256'] = canonical_digest(record['normalized_model_argv'])
        for event in events:
            item = event.get('item', {})
            if item.get('command') == old:
                item['command'] = shlex.join(raw)
    _write(root / 'expansion-broker.json', broker)
    (directory / 'events.jsonl').write_text(''.join(json.dumps(event) + '\n' for event in events))
    facts = json.loads((directory / 'codex-facts.json').read_text())
    facts['command_facts']['command_records'] = [asdict(row) for row in completed_command_records(events, platform_name='posix')]
    _write(directory / 'codex-facts.json', facts)


def _sealed_read_rejection(root):
    import shutil
    _sealed_c08(root, passed=False)
    shutil.rmtree(root / 'broker/state/transactions')
    plan = json.loads((root / 'expansion-plan.json').read_text())
    plan['read_scope']['owned_project_reads'] = True
    scope = ExpansionReadScope(frozenset(plan['read_scope']['object_ids']), frozenset(plan['read_scope']['operations']),
        includes=frozenset({'parent'}), relationship_sources=frozenset(plan['read_scope']['object_ids']), owned_project_reads=True)
    plan['read_scope'] = {key: sorted(value) if isinstance(value, frozenset) else value for key, value in asdict(scope).items()}
    plan['read_scope_sha256'] = scope.digest
    plan.pop('sha256')
    plan['sha256'] = canonical_digest(plan)
    _write(root / 'expansion-plan.json', plan)
    identifier = plan['read_scope']['object_ids'][0]
    argv_rows = [['query-object', '--exact-id', identifier],
                 ['query-object', '--exact-id', identifier, '--relationship', 'children', '--include', 'parent']]
    broker = json.loads((root / 'expansion-broker.json').read_text())
    originals = broker['records']
    records = []
    directory = root / 'turns/turn-01'
    events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
    events = [event for event in events if not event.get('item', {}).get('id', '').startswith(('cmd-', 'preview-notice'))]
    final_events = events[-2:]
    events = events[:-2]
    for index, argv in enumerate(argv_rows, 1):
        record = deepcopy(originals[index - 1])
        model = ['python', plan['skill_source'] + '/scripts/run.py', 'gateway.py', *argv]
        payload = {'ok': True, 'command': 'query-object', 'objects': [{'id': identifier}], 'count': 1, 'query_bound': {'mode': 'exact-object'}}
        record.update(sequence=index, model_argv=model, normalized_model_argv=model, gateway_arguments=argv,
            raw_argv_sha256=canonical_digest(model), argv_sha256=canonical_digest(model),
            semantic_argv_sha256=canonical_digest(['runner-owned-version', '2025.1', *argv]),
            runner_command_sha256=canonical_digest([plan['trusted_python'], plan['skill_source'] + '/scripts/run.py', 'gateway.py', *argv]),
            payload=payload, payload_sha256=canonical_digest(payload), stdout=json.dumps(payload))
        if index == 2:
            rejection = 'expansion policy rejected command: project query requires a bounded public source'
            record.update(authenticated=True, accepted=False, succeeded=False, exit_code=126, runner_exit_code=None,
                step_name=None, allowed_exit_codes=[], payload=None, payload_sha256='', payload_error='',
                runner_command_sha256='', semantic_argv_sha256='', rejection=rejection,
                stdout='', stderr='Gateway broker rejected command: ' + rejection + '\n')
        records.append(record)
        item = {'id': 'cmd-' + str(index), 'type': 'command_execution', 'command': shlex.join(model),
                'status': 'completed', 'exit_code': record['exit_code'], 'aggregated_output': record['stdout']}
        events += [{'type': 'item.started', 'item': {**item, 'status': 'in_progress'}}, {'type': 'item.completed', 'item': item}]
    events += final_events
    broker.update(records=records, passed=False, complete=False, expected_step_names=['expansion.step.0001'], consumed_step_names=['expansion.step.0001'])
    _write(root / 'expansion-broker.json', broker)
    (directory / 'events.jsonl').write_text(''.join(json.dumps(event) + '\n' for event in events))
    facts = json.loads((directory / 'codex-facts.json').read_text())
    facts['command_facts']['command_records'] = [asdict(row) for row in completed_command_records(events, platform_name='posix')]
    _write(directory / 'codex-facts.json', facts)
    oracle = {'before': plan['before'], 'after': None, 'transaction_id': None, 'assertions': {},
              'reconciliation': {'status': 'completed', 'seconds': 30, 'read_seconds': 10, 'elapsed_seconds': 1,
                  'child_reaped': True, 'subprocesses_reaped': True, 'snapshot': plan['before'], 'snapshot_sha256': canonical_digest(plan['before'])}}
    _write(root / 'expansion-oracle.json', oracle)
    budget = json.loads((root / 'expansion-agent-budget.json').read_text())
    gates = budget['turns'][0]['gates']
    for key in ('broker_provenance', 'policy_checkpoint', 'visible_preview_notice'):
        gates[key] = False
    _write(root / 'expansion-agent-budget.json', budget)
    result = json.loads((root / 'expansion-task-result.json').read_text())
    result.update(passed=False, status='FAIL', terminal_state='unprepared', assertions={}, gateway_verification_state=None,
                  plan_sha256=plan['sha256'], turns=budget['turns'])
    _write(root / 'expansion-task-result.json', result)
    grade = json.loads((directory / 'turn-grade.json').read_text())
    grade.update(common_gates=gates, broker_prefix_count=2, passed=False, errors=['broker_provenance', 'policy_checkpoint', 'visible_preview_notice'])
    _write(directory / 'turn-grade.json', grade)
    _realistic_command_paths(root)


def test_realistic_relative_shell_argv_binds_accepted_pass_receipts(tmp_path):
    _sealed_c08(tmp_path)
    _realistic_command_paths(tmp_path)
    assert _verify(tmp_path)['business_pass'] is True


def test_authenticated_predispatch_read_rejection_stays_fail_and_zero_mutation(tmp_path):
    _sealed_read_rejection(tmp_path)
    before = {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob('*') if path.is_file()}
    replay = _verify(tmp_path)
    assert replay['archive_valid'] is True and replay['original_status'] == 'FAIL'
    assert replay['business_pass'] is False and replay['executions'] == replay['execution_reservations'] == 0
    assert {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob('*') if path.is_file()} == before


@pytest.mark.parametrize('damage', ('unauthenticated', 'runner_evidence', 'payload', 'mutation', 'raw_bypass'))
def test_predispatch_read_rejection_requires_closed_negative_proof(tmp_path, damage):
    _sealed_read_rejection(tmp_path)
    path = tmp_path / 'expansion-broker.json'
    broker = json.loads(path.read_text())
    record = broker['records'][-1]
    if damage == 'unauthenticated':
        record['authenticated'] = False
    elif damage == 'runner_evidence':
        record['runner_command_sha256'] = 'b' * 64
    elif damage == 'payload':
        record['payload'] = {'ok': False}
    elif damage == 'mutation':
        argv = ['execute', 'tx1-00000000000000000001']
        record.update(gateway_arguments=argv,
            model_argv=[*record['model_argv'][:3], *argv],
            normalized_model_argv=[*record['normalized_model_argv'][:3], *argv])
        record['raw_argv_sha256'] = canonical_digest(record['model_argv'])
        record['argv_sha256'] = canonical_digest(record['normalized_model_argv'])
    else:
        directory = tmp_path / 'turns/turn-01'
        events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
        item = {'id': 'bypass', 'type': 'command_execution', 'command': "python -c 'print(1)'", 'status': 'completed', 'exit_code': 0, 'aggregated_output': '1'}
        events[-2:-2] = [{'type': 'item.started', 'item': {**item, 'status': 'in_progress'}}, {'type': 'item.completed', 'item': item}]
        (directory / 'events.jsonl').write_text(''.join(json.dumps(event) + '\n' for event in events))
        facts = json.loads((directory / 'codex-facts.json').read_text())
        facts['command_facts']['command_records'] = [asdict(row) for row in completed_command_records(events, platform_name='posix')]
        _write(directory / 'codex-facts.json', facts)
    _write(path, broker)
    with pytest.raises(ExpansionArchiveError):
        _verify(tmp_path)


@pytest.mark.parametrize('damage', ('extra', 'missing', 'duplicate_receipt', 'changed_argument', 'nonclosed_argument'))
def test_canonical_command_binding_keeps_exact_arguments_and_multiplicity(tmp_path, damage):
    if damage == 'duplicate_receipt':
        _sealed_read_rejection(tmp_path)
    else:
        _sealed_c08(tmp_path)
        _realistic_command_paths(tmp_path)
    directory = tmp_path / 'turns/turn-01'
    events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
    if damage == 'duplicate_receipt':
        broker = json.loads((tmp_path / 'expansion-broker.json').read_text())
        broker['records'].insert(1, deepcopy(broker['records'][0]))
        for index, row in enumerate(broker['records'], 1):
            row['sequence'] = index
        _write(tmp_path / 'expansion-broker.json', broker)
    else:
        selected = [event for event in events if event.get('item', {}).get('id') == 'cmd-1']
        if damage == 'extra':
            extra = deepcopy(selected)
            for event in extra:
                event['item']['id'] = 'extra-cmd'
            events[-2:-2] = extra
        elif damage == 'missing':
            events = [event for event in events if event not in selected]
        else:
            for event in selected:
                argv = shlex.split(event['item']['command'])
                if damage == 'changed_argument':
                    argv[-1] = 'ak.wwise.core.object.setNotes'
                else:
                    argv += ['--nonclosed-option', 'value']
                event['item']['command'] = shlex.join(argv)
        (directory / 'events.jsonl').write_text(''.join(json.dumps(event) + '\n' for event in events))
        facts = json.loads((directory / 'codex-facts.json').read_text())
        facts['command_facts']['command_records'] = [asdict(row) for row in completed_command_records(events, platform_name='posix')]
        _write(directory / 'codex-facts.json', facts)
    with pytest.raises(ExpansionArchiveError):
        _verify(tmp_path)


def _swap_raw_command_blocks(root, first_id, second_id):
    directory = root / 'turns/turn-01'
    events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
    first = [index for index, event in enumerate(events) if event.get('item', {}).get('id') == first_id]
    second = [index for index, event in enumerate(events) if event.get('item', {}).get('id') == second_id]
    assert len(first) == len(second) == 2
    assert [events[index]['type'] for index in first] == ['item.started', 'item.completed']
    assert [events[index]['type'] for index in second] == ['item.started', 'item.completed']
    for left, right in zip(first, second):
        events[left], events[right] = events[right], events[left]
    (directory / 'events.jsonl').write_text(''.join(json.dumps(event) + '\n' for event in events))
    facts = json.loads((directory / 'codex-facts.json').read_text())
    facts['command_facts']['command_records'] = [asdict(row) for row in completed_command_records(events, platform_name='posix')]
    _write(directory / 'codex-facts.json', facts)


def test_terminal_rejected_read_cannot_precede_accepted_query_in_raw_events(tmp_path):
    _sealed_read_rejection(tmp_path)
    _swap_raw_command_blocks(tmp_path, 'cmd-1', 'cmd-2')
    with pytest.raises(ExpansionArchiveError, match='order'):
        _verify(tmp_path)


def test_preview_execute_verify_receipts_require_same_raw_dependency_order(tmp_path):
    _sealed_c08(tmp_path)
    _realistic_command_paths(tmp_path)
    # The unchanged Preview and notice precede both commands. Only execution
    # and its verification are reversed, leaving every receipt and fact valid.
    _swap_raw_command_blocks(tmp_path, 'cmd-3', 'cmd-4')
    with pytest.raises(ExpansionArchiveError, match='order'):
        _verify(tmp_path)


def test_completed_rejected_read_turn_cannot_omit_terminal_receipt(tmp_path):
    _sealed_read_rejection(tmp_path)
    directory = tmp_path / 'turns/turn-01'
    events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
    events = [event for event in events if event.get('item', {}).get('id') != 'cmd-2']
    (directory / 'events.jsonl').write_text(''.join(json.dumps(event) + '\n' for event in events))
    facts = json.loads((directory / 'codex-facts.json').read_text())
    facts['command_facts']['command_records'] = [asdict(row) for row in completed_command_records(events, platform_name='posix')]
    _write(directory / 'codex-facts.json', facts)
    grade = json.loads((directory / 'turn-grade.json').read_text())
    grade['broker_prefix_count'] = 1
    _write(directory / 'turn-grade.json', grade)
    with pytest.raises(ExpansionArchiveError, match='omitted.*receipt'):
        _verify(tmp_path)
