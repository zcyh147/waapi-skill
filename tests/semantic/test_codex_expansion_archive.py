"""Read-only expansion replay rejects missing or inconsistent sealed evidence."""

import json
import os
import importlib.util
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
from tests.semantic.support.codex_gateway_contracts import TASK_LOCAL_RUNNER_POSIX, TASK_LOCAL_RUNNER_WINDOWS
from tests.semantic.support.codex_filesystem_security import write_utf8_text_bytes
from tests.semantic.test_codex_transaction_seal import _artifact
from wwise_waapi.transactions import TransactionStore
from wwise_waapi.operation_drafts import OperationDraftStore, _record_digest
from wwise_waapi.operation_composer import operation_composer_digest
from wwise_waapi.canonical import canonical_json_bytes


_GATEWAY_SPEC = importlib.util.spec_from_file_location("waapi_expansion_archive_test_gateway",
    Path(__file__).resolve().parents[2] / "skills/waapi-skill/scripts/gateway.py")
assert _GATEWAY_SPEC is not None and _GATEWAY_SPEC.loader is not None
_GATEWAY = importlib.util.module_from_spec(_GATEWAY_SPEC)
sys.modules[_GATEWAY_SPEC.name] = _GATEWAY
_GATEWAY_SPEC.loader.exec_module(_GATEWAY)

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


def _sealed_c08(root: Path, *, passed=True, rejected_preview=False, notice_fault=None, repair_metadata=None):
    identifier = "{11111111-1111-1111-1111-111111111111}"
    tx = "tx1-00000000000000000001"
    points = [{"x": 0, "y": 0, "shape": "Linear"}, {"x": 100, "y": -48, "shape": "Linear"}]
    preview_points = ([{"x": 0, "y": 0, "shape": "Linear"}, {"x": 80, "y": -48, "shape": "Linear"}]
                      if rejected_preview else points)
    before = {"attenuation": {"id": identifier, "name": "FixtureAttenuation", "type": "Attenuation",
        "path": r"\Attenuations\Default Work Unit\FixtureAttenuation"}, "users": {"sound": {
        "id": "{33333333-3333-3333-3333-333333333333}", "type": "Sound", "references": {"Attenuation": {"id": identifier}}}},
              "source": {"object": {"id": "{22222222-2222-2222-2222-222222222222}",
                  "name": "SourceAttenuation", "type": "Attenuation", "path": r"\Attenuations\Default Work Unit\SourceAttenuation"},
                  "notes": "original"}, "curves": {
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
    artifact["prepared_operation"].update(operation="waapi.call", version="2025.1",
        request=deepcopy(artifact["request"]), dispatch={"uri": api,
            "args": deepcopy(artifact["request"]["arguments"]["args"]), "options": {}},
        verification_plan={"kind": "result-schema", "strategy": "result_schema", "uri": api, "version": "2025.1"})
    if notice_fault == "prepared_request":
        artifact["prepared_operation"]["request"]["arguments"]["args"]["use"] = "None"
    elif notice_fault == "dispatch":
        artifact["prepared_operation"]["dispatch"]["args"]["points"][1]["y"] = -12
    elif notice_fault == "baseline_type":
        before["attenuation"]["type"] = "Sound"
        after["attenuation"]["type"] = "Sound"
    elif notice_fault == "source_alias":
        before["source"]["object"]["id"] = identifier
        after["source"]["object"]["id"] = identifier
    if repair_metadata is not None:
        from tests.semantic.support.codex_repair_cases import verify_f1, F1_ASSERTIONS
        expected = {"name": "Repair_Room", "type": "Effect", "path": r"\Effects\Default Work Unit\Repair_Room",
                    "parent": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}", "properties": {"PreDelay": 24}}
        before = {"objects": {identifier: {"id": identifier, **expected, "properties": {"PreDelay": 25}}},
                  "source_integrity": {"sha256": "a" * 64, "mtime_ns": 1}, "media": {}, "complete": True}
        after = deepcopy(before)
        after["objects"][identifier]["properties"]["PreDelay"] = 24
        artifact["request"].update(operation="object.setProperty", arguments={
            "object": {"kind": "id", "value": identifier}, "property": "PreDelay", "value": 24})
        artifact["prepared_operation"].update(operation="object.setProperty", request=deepcopy(artifact["request"]),
            dispatch={"uri": "ak.wwise.core.object.setProperty", "args": {"object": identifier, "property": "PreDelay", "value": 24}, "options": {}})
        artifact["connection_configuration"] = {"config_path": str(root / "fixture-config.json"),
            "waapi_host": artifact["project_guard"]["endpoint"]["host"],
            "waapi_port": artifact["project_guard"]["endpoint"]["port"], "wwise_version": "2025.1"}
    verification_state = "verified" if repair_metadata is not None else "result_schema_checked"
    store = TransactionStore(root / "broker" / "state")
    store.create_preview(tx, artifact)
    authority = "caller_asserted_current_user_change_request"
    if not rejected_preview:
        store.transition(tx, "policy_authorized", expected_state="draft", event_type="policy_authorized",
                         details={"policy": "allow_changes", "authority": authority, "explicit_confirmation": False})
        store.begin_execution(tx, expected_authorization="policy_authorized")
        store.mark_executed_unverified(tx)
        store.record_verification(tx, outcome=verification_state)
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
    if repair_metadata is not None:
        plan.update(contract="waapi-skill.repair-task-plan/v1", model="gpt-5.6-terra", reasoning_effort="medium", service_tier="default", unit_id="REPAIR25-F1", operation="object.setProperty", request_schema_uri=None,
            required_assertions=sorted(F1_ASSERTIONS), before=before,
            oracle_parameters={"expected": expected, "target_id": identifier},
            preview_parameters={"expected": expected, "target_id": identifier, "parent_id": expected["parent"]})
    digest = canonical_digest(plan)
    _write(root / "expansion-plan.json", {**plan, "sha256": digest})
    artifact_hash = canonical_digest(artifact)
    assertions = {} if rejected_preview else verify_c08(before, after, expected_points=points)
    if repair_metadata is not None:
        assertions = {**verify_f1(before, after, expected=expected, target_id=identifier), "metadata_list_page_detail": True}
    oracle = {"before": before, "after": None if rejected_preview else after,
        "preview_before": before, "preview_after": before, "assertions": assertions,
        "transaction_id": tx, "artifact_hash": artifact_hash,
        "gateway_verification_state": None if rejected_preview else verification_state,
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
    if repair_metadata is not None:
        start = repair_metadata[0][1]
        argv_rows[1] = ["preview-from-draft", start["draft"]["draft_id"], "--task-authority", start["task_authority"],
                        "--expected-revision", str(repair_metadata[-1][1]["draft"]["revision"])]
        argv_rows = [argv for argv, _ in repair_metadata] + argv_rows[1:]
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
            payload["state"] = verification_state
        if repair_metadata is not None and index <= len(repair_metadata):
            payload = deepcopy(repair_metadata[index - 1][1])
        model_argv = ["python", str(Path(plan["skill_source"]) / "scripts" / "run.py"), "gateway.py", *argv]
        semantic = ["runner-owned-version", "2025.1", *argv]
        if "--expected-revision" in argv:
            semantic[semantic.index("--expected-revision") + 1] = int(argv[argv.index("--expected-revision") + 1])
        stdout = json.dumps(payload)
        records.append({"sequence": index, "step_name": f"expansion.step.{index:04d}",
            "model_argv": model_argv, "normalized_model_argv": model_argv, "gateway_arguments": argv,
            "raw_argv_sha256": canonical_digest(model_argv), "argv_sha256": canonical_digest(model_argv),
            "semantic_argv_sha256": canonical_digest(semantic), "payload_sha256": canonical_digest(payload),
            "runner_command_sha256": canonical_digest([plan["trusted_python"], str(Path(plan["skill_source"]) / "scripts" / "run.py"), "gateway.py", *argv]),
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
                    "The preview passed; applying it now." if notice_fault == "missing_effect" else
                    "I will set Repair_Room PreDelay to 24." if repair_metadata is not None else
                    "I will set FixtureAttenuation's dry volume curve to Custom; points (0, 0), (100, -48), all Linear.")}})
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
    _write(root / "expansion-task-result.json", {"unit_id": plan["unit_id"], "version": "2025.1",
        "passed": passed and not rejected_preview,
        **({"status": "FAIL"} if rejected_preview else {}),
        "thread_id": "thread", "plan_sha256": digest, "assertions": assertions,
        "agent_seconds": 12, "slow": False, "turns": turns,
        "gateway_verification_state": None if rejected_preview else verification_state})
    directory = root / "turns" / "turn-01"
    _write(directory / "turn-grade.json", {"index": 1, "prompt_sha256": hashlib.sha256(plan["prompts"][0].encode()).hexdigest(),
        "common_gates": gates, "broker_prefix_count": len(records),
        "passed": not rejected_preview, "errors": ["policy checkpoint failed"] if rejected_preview else []})
    _write(directory / "codex-facts.json", {"thread_id": "thread", "final_response": final_response,
        "exit_status": 0, "timed_out": False, "prompt_audit": {"passed": True, "has_memory": False},
        "isolation_audit": {"passed": True}, "skill_tree_unchanged": True,
        "skill_tree_sha256_before": INPUTS, "skill_tree_sha256_after": INPUTS,
        "command_facts": {"command_records": [asdict(row) for row in completed_command_records(events, platform_name="posix")]}})
    write_utf8_text_bytes(directory / "events.jsonl", "".join(json.dumps(event) + "\n" for event in events))
    write_utf8_text_bytes(directory / "prompt.txt", plan["prompts"][0] + "\n")
    write_utf8_text_bytes(directory / "final.txt", final_response + "\n")
    write_utf8_text_bytes(directory / "stderr.txt", "")


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


@pytest.mark.parametrize("notice_fault", ("prepared_request", "dispatch", "baseline_type", "source_alias", "missing_effect"))
def test_synthetic_pass_archive_requires_attested_curve_request_dispatch_baseline_and_notice(tmp_path, notice_fault):
    # Keep all artifact hashes, journals and Broker receipts internally sealed:
    # these disagreements must fail semantic proof, not merely stale hashing.
    _sealed_c08(tmp_path, notice_fault=notice_fault)
    oracle = json.loads((tmp_path / "expansion-oracle.json").read_text())
    assert all(oracle["assertions"].values())
    with pytest.raises(ExpansionArchiveError, match="visible post-Preview notice"):
        _verify(tmp_path)


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
        record["model_argv"] = ["python", str(Path(plan["skill_source"]) / "scripts" / "run.py"), "gateway.py", *argv]
        record["normalized_model_argv"] = record["model_argv"]
        record["raw_argv_sha256"] = record["argv_sha256"] = canonical_digest(record["model_argv"])
        semantic = ["runner-owned-version", "2025.1", *argv]
        if command == "draft-check":
            semantic[-1] = 1
        record["semantic_argv_sha256"] = canonical_digest(semantic)
        record["runner_command_sha256"] = canonical_digest([plan["trusted_python"], str(Path(plan["skill_source"]) / "scripts" / "run.py"), "gateway.py", *argv])
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
    write_utf8_text_bytes(directory / "events.jsonl", "".join(json.dumps(event) + "\n" for event in events))
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
    write_utf8_text_bytes(directory / "events.jsonl", "".join(json.dumps(event) + "\n" for event in events))
    write_utf8_text_bytes(directory / "stderr.txt", "")
    replay = _verify(root)
    assert replay["original_status"] == "BLOCKED" and replay["business_pass"] is False
    events.append({"type": "item.completed", "item": {"type": "agent_message", "text": "Working"}})
    write_utf8_text_bytes(directory / "events.jsonl", "".join(json.dumps(event) + "\n" for event in events))
    with pytest.raises(ExpansionArchiveError, match="pre-action"):
        _verify(root)


def _realistic_command_paths(root):
    """CLI shell argv differs from the authenticated shim's received argv."""
    broker = json.loads((root / 'expansion-broker.json').read_text())
    directory = root / 'turns/turn-01'
    events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
    for record in broker['records']:
        old = shlex.join(record['model_argv'])
        raw = ['python', TASK_LOCAL_RUNNER_WINDOWS if os.name == 'nt' else TASK_LOCAL_RUNNER_POSIX,
               'gateway.py', *record['gateway_arguments']]
        record['model_argv'] = [str(root / 'broker/bin/python'), *raw[1:]]
        record['normalized_model_argv'] = ['python', str(root / 'agent-workspace/.agents/skills/waapi-skill/scripts/run.py'), 'gateway.py', *record['gateway_arguments']]
        record['raw_argv_sha256'] = canonical_digest(record['model_argv'])
        record['argv_sha256'] = canonical_digest(record['normalized_model_argv'])
        for event in events:
            item = event.get('item', {})
            if item.get('command') == old:
                item['command'] = shlex.join(raw)
    _write(root / 'expansion-broker.json', broker)
    write_utf8_text_bytes(directory / 'events.jsonl', ''.join(json.dumps(event) + '\n' for event in events))
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
        model = ['python', str(Path(plan['skill_source']) / 'scripts' / 'run.py'), 'gateway.py', *argv]
        payload = {'ok': True, 'command': 'query-object', 'objects': [{'id': identifier}], 'count': 1, 'query_bound': {'mode': 'exact-object'}}
        record.update(sequence=index, model_argv=model, normalized_model_argv=model, gateway_arguments=argv,
            raw_argv_sha256=canonical_digest(model), argv_sha256=canonical_digest(model),
            semantic_argv_sha256=canonical_digest(['runner-owned-version', '2025.1', *argv]),
            runner_command_sha256=canonical_digest([plan['trusted_python'], str(Path(plan['skill_source']) / 'scripts' / 'run.py'), 'gateway.py', *argv]),
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
    write_utf8_text_bytes(directory / 'events.jsonl', ''.join(json.dumps(event) + '\n' for event in events))
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


def _sealed_parser_rejected_query(root):
    """The b4fd348 C09 unsupported effects projection, with no dispatch."""
    _sealed_read_rejection(root)
    plan = json.loads((root / 'expansion-plan.json').read_text())
    broker = json.loads((root / 'expansion-broker.json').read_text())
    record = broker['records'][-1]
    record['gateway_arguments'] = ['query-object', '--exact-id', plan['read_scope']['object_ids'][0],
        '--include', 'effects', '--max-results', '100']
    record['rejection'] = 'expansion policy rejected command: command does not satisfy the public Gateway parser'
    record['stderr'] = 'Gateway broker rejected command: ' + record['rejection'] + '\n'
    _refresh_bound_rejection_receipts(root, broker)


def test_authenticated_invalid_effects_query_is_an_isolated_fail_without_archive_writes(tmp_path):
    _sealed_parser_rejected_query(tmp_path)
    before = {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
              for path in tmp_path.rglob('*') if path.is_file()}
    result = _verify(tmp_path)
    assert result['archive_valid'] is True and result['original_status'] == 'FAIL'
    assert result['business_pass'] is False
    assert result['executions'] == result['execution_reservations'] == 0
    assert {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in tmp_path.rglob('*') if path.is_file()} == before


@pytest.mark.parametrize('damage', ('authentication', 'runner_exit', 'payload', 'payload_digest',
    'raw_hash', 'normalized_hash', 'token', 'extra_token', 'reason', 'stderr', 'valid_syntax', 'help', 'mutation',
    'admitted_invalid', 'missing_receipt', 'later_dispatch', 'duplicate_rejection', 'reconciliation', 'pass'))
def test_parser_rejected_query_requires_exact_terminal_authenticated_negative_proof(tmp_path, damage):
    _sealed_parser_rejected_query(tmp_path)
    broker = json.loads((tmp_path / 'expansion-broker.json').read_text())
    row = broker['records'][-1]
    if damage == 'authentication': row['authenticated'] = False
    elif damage == 'runner_exit': row['runner_exit_code'] = 2
    elif damage == 'payload': row['payload'] = {'ok': False}
    elif damage == 'payload_digest': row['payload_sha256'] = 'b' * 64
    elif damage == 'raw_hash': row['raw_argv_sha256'] = 'b' * 64
    elif damage == 'normalized_hash': row['argv_sha256'] = 'b' * 64
    elif damage == 'token': row['gateway_arguments'][-3] = 'another-output'
    elif damage == 'extra_token': row['gateway_arguments'].append('--unrecorded')
    elif damage == 'reason': row['rejection'] = 'unsupported query'
    elif damage == 'stderr': row['stderr'] = row['stderr'].rstrip()
    elif damage in ('valid_syntax', 'help', 'mutation', 'admitted_invalid'):
        if damage == 'valid_syntax': row['gateway_arguments'][-3] = 'parent'
        elif damage == 'help': row['gateway_arguments'] = ['query-object', '--help']
        elif damage == 'mutation': row['gateway_arguments'] = ['execute', '--invalid']
        else: row['accepted'] = True
        _refresh_bound_rejection_receipts(tmp_path, broker)
    elif damage == 'missing_receipt': broker['records'].pop()
    elif damage == 'later_dispatch':
        extra = deepcopy(broker['records'][0])
        extra.update(sequence=3, step_name='expansion.step.0002')
        broker['records'].append(extra)
        _refresh_bound_rejection_receipts(tmp_path, broker)
    elif damage == 'duplicate_rejection':
        extra = deepcopy(row)
        extra['sequence'] = 3
        broker['records'].append(extra)
        _refresh_bound_rejection_receipts(tmp_path, broker)
    elif damage == 'reconciliation':
        oracle = json.loads((tmp_path / 'expansion-oracle.json').read_text())
        oracle['reconciliation']['child_reaped'] = False
        _write(tmp_path / 'expansion-oracle.json', oracle)
    else:
        result = json.loads((tmp_path / 'expansion-task-result.json').read_text())
        result.update(passed=True, status='PASS')
        _write(tmp_path / 'expansion-task-result.json', result)
    _write(tmp_path / 'expansion-broker.json', broker)
    with pytest.raises(ExpansionArchiveError):
        _verify(tmp_path)


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
        write_utf8_text_bytes(directory / 'events.jsonl', ''.join(json.dumps(event) + '\n' for event in events))
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
        write_utf8_text_bytes(directory / 'events.jsonl', ''.join(json.dumps(event) + '\n' for event in events))
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
    write_utf8_text_bytes(directory / 'events.jsonl', ''.join(json.dumps(event) + '\n' for event in events))
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
    write_utf8_text_bytes(directory / 'events.jsonl', ''.join(json.dumps(event) + '\n' for event in events))
    facts = json.loads((directory / 'codex-facts.json').read_text())
    facts['command_facts']['command_records'] = [asdict(row) for row in completed_command_records(events, platform_name='posix')]
    _write(directory / 'codex-facts.json', facts)
    grade = json.loads((directory / 'turn-grade.json').read_text())
    grade['broker_prefix_count'] = 1
    _write(directory / 'turn-grade.json', grade)
    with pytest.raises(ExpansionArchiveError, match='omitted.*receipt'):
        _verify(tmp_path)


def _sealed_invalid_draft_bind(root, operation="audio.import"):
    _sealed_read_rejection(root)
    plan = json.loads((root / 'expansion-plan.json').read_text())
    plan['operation'] = 'audio.import' if operation == 'audio.import' else 'waapi.call'
    plan.pop('request_schema_uri', None)
    if operation != 'audio.import':
        plan['request_schema_uri'] = operation
    plan['read_scope']['operations'] = [operation]
    scope = ExpansionReadScope(**{key: frozenset(value) if isinstance(value, list) else value
        for key, value in plan['read_scope'].items()})
    plan['read_scope_sha256'] = scope.digest
    plan.pop('sha256')
    plan['sha256'] = canonical_digest(plan)
    _write(root / 'expansion-plan.json', plan)
    start = OperationDraftStore(root / 'broker/state').start(operation=operation, version='2025.1',
        schema_digest=_GATEWAY.operation_draft_schema_digest(operation, '2025.1'), composer_digest=operation_composer_digest(operation, '2025.1'))
    record = start.record
    draft = {'contract': 'waapi-skill.operation-draft/v1', 'draft_id': start.draft_id,
        'revision': 1, 'business_revision': 0, 'lifecycle_state': 'editable',
        'binding': {'operation': record.operation, 'version': record.version, 'schema_digest': record.schema_digest},
        'created_at': record.created_at, 'updated_at': record.updated_at, 'expires_at': record.expires_at,
        'declarations': [], 'check': None, 'seal': None, 'preview': None}
    broker = json.loads((root / 'expansion-broker.json').read_text())
    first, last = broker['records']
    first['gateway_arguments'] = ['draft-start', operation]
    first['payload'] = {'ok': True, 'command': 'draft-start', 'draft': draft, 'task_authority': start.task_authority}
    first['payload_sha256'] = canonical_digest(first['payload'])
    first['stdout'] = json.dumps(first['payload'])
    last['gateway_arguments'] = ['draft-bind-object', start.draft_id, '--task-authority', start.task_authority,
        '--expected-revision', '1', '--object-id', plan['read_scope']['object_ids'][0][1:-1]]
    last['rejection'] = 'expansion policy rejected command: bound object is outside the approved fixture'
    last['stderr'] = 'Gateway broker rejected command: ' + last['rejection'] + '\n'
    for row in broker['records']:
        argv = row['gateway_arguments']
        row['model_argv'] = ['python', str(Path(plan['skill_source']) / 'scripts' / 'run.py'), 'gateway.py', *argv]
        row['normalized_model_argv'] = row['model_argv']
        row['raw_argv_sha256'] = row['argv_sha256'] = canonical_digest(row['model_argv'])
        if row['accepted']:
            row['semantic_argv_sha256'] = canonical_digest(['runner-owned-version', '2025.1', *argv])
            row['runner_command_sha256'] = canonical_digest([plan['trusted_python'], str(Path(plan['skill_source']) / 'scripts' / 'run.py'), 'gateway.py', *argv])
    _write(root / 'expansion-broker.json', broker)
    directory = root / 'turns/turn-01'
    events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
    for event in events:
        item = event.get('item', {})
        if item.get('id') in {'cmd-1', 'cmd-2'}:
            row = broker['records'][int(item['id'][-1]) - 1]
            item['command'] = shlex.join(row['model_argv'])
            item['aggregated_output'] = row['stdout']
    write_utf8_text_bytes(directory / 'events.jsonl', ''.join(json.dumps(event) + '\n' for event in events))
    result = json.loads((root / 'expansion-task-result.json').read_text())
    oracle = json.loads((root / 'expansion-oracle.json').read_text())
    oracle.update(artifact_hash=None, authorization=None, permit=None,
        preview_before=None, preview_after=None, gateway_verification_state=None)
    _write(root / 'expansion-oracle.json', oracle)
    result['plan_sha256'] = plan['sha256']
    _write(root / 'expansion-task-result.json', result)
    _realistic_command_paths(root)


def test_terminal_invalid_guid_draft_bind_preserves_failed_zero_mutation_archive(tmp_path):
    _sealed_invalid_draft_bind(tmp_path)
    before = {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob('*') if path.is_file()}
    replay = _verify(tmp_path)
    assert replay['archive_valid'] is True and replay['original_status'] == 'FAIL'
    assert replay['business_pass'] is False and replay['executions'] == replay['execution_reservations'] == 0
    assert {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob('*') if path.is_file()} == before


def _sealed_bound_draft_read_rejection(root, *, declaration=False):
    """Production Draft update plus the terminal owned-read pattern from #132."""
    from wwise_waapi.business_declarations import BusinessContext, BusinessHandleRegistry
    operation = 'ak.wwise.core.object.setAttenuationCurve' if declaration else 'audio.import'
    _sealed_invalid_draft_bind(root, operation)
    plan = json.loads((root / 'expansion-plan.json').read_text())
    # This derivative models a Sound read, not the C08 attenuation identity.
    # Complete baseline rows must never give one GUID two different types.
    identifier = plan['before']['attenuation']['id'] if declaration else plan['before']['users']['sound']['id']
    plan['read_scope']['object_ids'] = [identifier]
    plan['read_scope']['relationship_sources'] = [identifier]
    scope = ExpansionReadScope(**{key: frozenset(value) if isinstance(value, list) else value
        for key, value in plan['read_scope'].items()})
    plan['read_scope_sha256'] = scope.digest
    identity = plan['before']['attenuation'] if declaration else {'id': identifier, 'name': 'FixtureSound', 'type': 'Sound', 'path': r'\Containers\FixtureSound'}
    if not declaration:
        plan['before']['sound'] = identity
    plan.pop('sha256')
    plan['sha256'] = canonical_digest(plan)
    _write(root / 'expansion-plan.json', plan)
    broker = json.loads((root / 'expansion-broker.json').read_text())
    first = broker['records'][0]
    start = first['payload']
    context = BusinessContext.create(task_authority=start['task_authority'], project_id=identifier,
        project_path='/fixture/SampleProject.wproj', wwise_version='2025.1', wwise_build='v2025.1.7')
    captured = []
    def bind(session):
        handles = BusinessHandleRegistry.from_dict(session.handles.as_dict())
        captured.append(handles.bind_object(object_id=identifier, name=identity['name'],
            object_type=identity['type'], path=identity['path'], semantic_kind=None if declaration else 'sound-voice',
            role='attenuation' if declaration else None))
        return session.with_handle_registry(handles)
    updated = OperationDraftStore(root / 'broker/state').apply_business_update(start['draft']['draft_id'],
        task_authority=start['task_authority'], expected_revision=1,
        schema_digest=start['draft']['binding']['schema_digest'],
        composer_digest=operation_composer_digest(operation, '2025.1'),
        context=context, update=bind, event_type='handles.bound')
    bound = captured[0]
    payload = {'ok': True, 'command': 'draft-bind-object', 'draft': {
        'contract': 'waapi-skill.operation-draft/v1', 'draft_id': updated.draft_id,
        'revision': 2, 'business_revision': 0, 'lifecycle_state': 'editable', 'binding': start['draft']['binding']},
        'bound_object': {'handle': bound.handle, 'name': bound.name, 'type': bound.object_type,
                         'semantic_kind': bound.semantic_kind}}
    accepted = deepcopy(first)
    accepted.update(sequence=2, step_name='expansion.step.0002', payload=payload,
        payload_sha256=canonical_digest(payload), stdout=json.dumps(payload), gateway_arguments=[
        'draft-bind-object', updated.draft_id, '--task-authority', start['task_authority'],
        '--expected-revision', '1', *(['--role', 'attenuation'] if declaration else []), '--object-id', identifier])
    if declaration:
        payload['bound_object']['role'] = 'attenuation'
        accepted['payload_sha256'] = canonical_digest(payload)
        accepted['stdout'] = json.dumps(payload)
    rejected = deepcopy(broker['records'][-1])
    rejected.update(sequence=3, gateway_arguments=['query-object', '--exact-id', identifier,
        '--relationship', 'children', '--include', 'parent', '--include', 'file-path', '--max-results', '100'],
        rejection='expansion policy rejected command: project query requires a bounded public source')
    rejected['stderr'] = 'Gateway broker rejected command: ' + rejected['rejection'] + '\n'
    if declaration:
        witness = json.loads((Path(__file__).parents[1] / 'fixtures/semantic/expansion-rejected-declaration-719e3e0.json').read_text())['record']
        rejected.update({key: witness[key] for key in ('rejection', 'stderr', 'gateway_arguments')})
        argv = rejected['gateway_arguments']
        argv[1] = updated.draft_id
        argv[argv.index('--task-authority') + 1] = start['task_authority']
        argv[argv.index('--role') + 2:argv.index('--role') + 4] = ['bo', bound.handle[2:]]
    broker.update(records=[first, accepted, rejected],
        expected_step_names=['expansion.step.0001', 'expansion.step.0002'],
        consumed_step_names=['expansion.step.0001', 'expansion.step.0002'])
    directory = root / 'turns/turn-01'
    events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
    events = [event for event in events if not event.get('item', {}).get('id', '').startswith('cmd-')]
    final = events[-2:]
    events = events[:-2]
    for row in broker['records']:
        argv = row['gateway_arguments']
        model = ['python', str(Path(plan['skill_source']) / 'scripts' / 'run.py'), 'gateway.py', *argv]
        row.update(model_argv=model, normalized_model_argv=model,
            raw_argv_sha256=canonical_digest(model), argv_sha256=canonical_digest(model))
        if row['accepted']:
            semantic = ['runner-owned-version', '2025.1', *argv]
            if '--expected-revision' in argv:
                semantic[2 + argv.index('--expected-revision') + 1] = 1
            row['semantic_argv_sha256'] = canonical_digest(semantic)
            row['runner_command_sha256'] = canonical_digest([plan['trusted_python'], str(Path(plan['skill_source']) / 'scripts' / 'run.py'), 'gateway.py', *argv])
        item = {'id': 'cmd-' + str(row['sequence']), 'type': 'command_execution', 'command': shlex.join(model),
            'status': 'completed', 'exit_code': row['exit_code'], 'aggregated_output': row['stdout']}
        events.extend([{'type': 'item.started', 'item': {**item, 'status': 'in_progress'}},
                       {'type': 'item.completed', 'item': item}])
    _write(root / 'expansion-broker.json', broker)
    write_utf8_text_bytes(directory / 'events.jsonl', ''.join(json.dumps(event) + '\n' for event in [*events, *final]))
    oracle = json.loads((root / 'expansion-oracle.json').read_text())
    oracle['before'] = oracle['reconciliation']['snapshot'] = plan['before']
    oracle['reconciliation']['snapshot_sha256'] = canonical_digest(plan['before'])
    _write(root / 'expansion-oracle.json', oracle)
    result = json.loads((root / 'expansion-task-result.json').read_text())
    result['plan_sha256'] = plan['sha256']
    _write(root / 'expansion-task-result.json', result)
    grade = json.loads((directory / 'turn-grade.json').read_text())
    grade['broker_prefix_count'] = 3
    _write(directory / 'turn-grade.json', grade)
    _realistic_command_paths(root)


def test_terminal_owned_read_cap_rejection_after_bound_draft_remains_isolated_fail(tmp_path):
    _sealed_bound_draft_read_rejection(tmp_path)
    before = {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob('*') if path.is_file()}
    replay = _verify(tmp_path)
    assert replay['archive_valid'] is True and replay['original_status'] == 'FAIL'
    assert replay['business_pass'] is False and replay['executions'] == replay['execution_reservations'] == 0
    assert {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob('*') if path.is_file()} == before


def _refresh_bound_rejection_receipts(root, broker):
    directory = root / 'turns/turn-01'
    events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
    final = events[-2:]
    events = [event for event in events[:-2] if not event.get('item', {}).get('id', '').startswith('cmd-')]
    for row in broker['records']:
        argv = row['gateway_arguments']
        model = ['python', '.agents/skills/waapi-skill/scripts/run.py', 'gateway.py', *argv]
        row['model_argv'] = model
        if row['accepted']:
            row['payload_sha256'] = canonical_digest(row['payload'])
            row['stdout'] = json.dumps(row['payload'])
            semantic = ['runner-owned-version', '2025.1', *argv]
            if '--expected-revision' in argv:
                semantic[2 + argv.index('--expected-revision') + 1] = int(argv[argv.index('--expected-revision') + 1])
            row['semantic_argv_sha256'] = canonical_digest(semantic)
            plan = json.loads((root / 'expansion-plan.json').read_text())
            row['runner_command_sha256'] = canonical_digest([plan['trusted_python'], str(Path(plan['skill_source']) / 'scripts' / 'run.py'), 'gateway.py', *argv])
        item = {'id': 'cmd-' + str(row['sequence']), 'type': 'command_execution', 'command': shlex.join(model),
            'status': 'completed', 'exit_code': row['exit_code'], 'aggregated_output': row['stdout']}
        events.extend([{'type': 'item.started', 'item': {**item, 'status': 'in_progress'}},
                       {'type': 'item.completed', 'item': item}])
    _write(root / 'expansion-broker.json', broker)
    write_utf8_text_bytes(directory / 'events.jsonl', ''.join(json.dumps(event) + '\n' for event in [*events, *final]))
    _realistic_command_paths(root)


@pytest.mark.parametrize('damage', ('bound_identity', 'revision', 'settings', 'audit', 'projection',
    'within_cap', 'authority', 'transaction', 'later_dispatch', 'raw_order', 'reconciliation', 'preview'))
def test_bound_draft_rejected_read_requires_exact_unchanged_failure_proof(tmp_path, damage):
    _sealed_bound_draft_read_rejection(tmp_path)
    broker = json.loads((tmp_path / 'expansion-broker.json').read_text())
    path = next((tmp_path / 'broker/state/operation-drafts-v1/records').glob('*.json'))
    if damage in {'bound_identity', 'revision', 'settings', 'audit'}:
        stored = json.loads(path.read_text())
        if damage == 'bound_identity':
            from wwise_waapi.business_declarations import BusinessContext, BusinessHandleRegistry
            raw = stored['composition']['business_session']
            obj = raw['handles']['objects'][0]
            registry = BusinessHandleRegistry(BusinessContext.from_binding_dict(raw['context']),
                token_bytes=lambda _size: bytes.fromhex(obj['handle'].split('-', 1)[1]))
            registry.bind_object(object_id=obj['object_id'], name='ForgedName', object_type=obj['object_type'],
                path=obj['path'], semantic_kind=obj['semantic_kind'])
            raw['handles'] = registry.as_dict()
            broker['records'][1]['payload']['bound_object']['name'] = 'ForgedName'
            _refresh_bound_rejection_receipts(tmp_path, broker)
        elif damage == 'revision':
            stored['revision'] = 3
        elif damage == 'settings':
            stored['composition']['business_session']['settings'] = {'source_gain_db': 1}
        else:
            stored['audit'][-1]['event_type'] = 'settings.changed'
            event = stored['audit'][-1]
            event.pop('event_hash')
            event['event_hash'] = canonical_digest(event)
        stored.pop('record_digest')
        stored['record_digest'] = _record_digest(stored)
        path.write_bytes(canonical_json_bytes(stored))
    elif damage in {'projection', 'within_cap', 'authority', 'later_dispatch'}:
        if damage == 'projection':
            broker['records'][1]['payload']['draft']['business_revision'] = 1
        elif damage == 'within_cap':
            broker['records'][-1]['gateway_arguments'][-1] = '64'
        elif damage == 'authority':
            broker['records'][1]['gateway_arguments'][3] = 'da1-' + '0' * 40
        else:
            extra = deepcopy(broker['records'][0])
            extra['sequence'] = 4
            broker['records'].append(extra)
        _refresh_bound_rejection_receipts(tmp_path, broker)
    elif damage == 'raw_order':
        _swap_raw_command_blocks(tmp_path, 'cmd-2', 'cmd-3')
    elif damage == 'transaction':
        (tmp_path / 'broker/state/transactions').mkdir()
    else:
        oracle = json.loads((tmp_path / 'expansion-oracle.json').read_text())
        if damage == 'preview':
            oracle['preview_after'] = {'pending': True}
        else:
            oracle['reconciliation']['snapshot']['sound']['name'] = 'changed'
            oracle['reconciliation']['snapshot_sha256'] = canonical_digest(oracle['reconciliation']['snapshot'])
        _write(tmp_path / 'expansion-oracle.json', oracle)
    with pytest.raises(ExpansionArchiveError):
        _verify(tmp_path)


@pytest.mark.parametrize('damage', ('authority', 'revision', 'wrong_guid', 'braced_guid', 'other_rejection',
    'runner_evidence', 'extra_draft', 'composition', 'audit', 'schema', 'start_projection', 'terminal_omission',
    'later_dispatch', 'transaction', 'authorization', 'preview', 'pending_preview', 'missing_null', 'reconciliation', 'changed_state', 'reap', 'pass_gate'))
def test_invalid_draft_bind_requires_exact_pristine_negative_proof(tmp_path, damage):
    _sealed_invalid_draft_bind(tmp_path)
    broker_path = tmp_path / 'expansion-broker.json'
    broker = json.loads(broker_path.read_text())
    last = broker['records'][-1]
    if damage in {'authority', 'revision', 'wrong_guid', 'braced_guid', 'other_rejection', 'runner_evidence', 'later_dispatch', 'start_projection'}:
        if damage == 'authority':
            last['gateway_arguments'][3] = 'da1-' + '0' * 40
        elif damage == 'revision':
            last['gateway_arguments'][5] = '2'
        elif damage == 'wrong_guid':
            last['gateway_arguments'][-1] = '99999999-9999-9999-9999-999999999999'
        elif damage == 'braced_guid':
            last['gateway_arguments'][-1] = '{' + last['gateway_arguments'][-1] + '}'
        elif damage == 'other_rejection':
            last['rejection'] = 'expansion policy rejected command: Draft identity, authority or revision is stale'
            last['stderr'] = 'Gateway broker rejected command: ' + last['rejection'] + '\n'
        elif damage == 'runner_evidence':
            last['runner_command_sha256'] = 'a' * 64
        elif damage == 'start_projection':
            first = broker['records'][0]
            first['payload']['draft']['business_revision'] = 1
            first['payload_sha256'] = canonical_digest(first['payload'])
            first['stdout'] = json.dumps(first['payload'])
        else:
            broker['records'].append(deepcopy(broker['records'][0]))
            broker['records'][-1]['sequence'] = 3
        _write(broker_path, broker)
        # Rebind all modified receipt argv and raw facts, so the rejection
        # depends on semantic proof rather than stale digests.
        directory = tmp_path / 'turns/turn-01'
        events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
        for row in broker['records']:
            row['model_argv'] = ['python', '.agents/skills/waapi-skill/scripts/run.py', 'gateway.py', *row['gateway_arguments']]
            for event in events:
                if event.get('item', {}).get('id') == 'cmd-' + str(row['sequence']):
                    event['item']['command'] = shlex.join(row['model_argv'])
        _write(broker_path, broker)
        write_utf8_text_bytes(directory / 'events.jsonl', ''.join(json.dumps(event) + '\n' for event in events))
        _realistic_command_paths(tmp_path)
    elif damage in {'extra_draft', 'composition', 'audit', 'schema'}:
        path = next((tmp_path / 'broker/state/operation-drafts-v1/records').glob('*.json'))
        stored = json.loads(path.read_text())
        if damage == 'extra_draft':
            _write(path.with_name('od1-' + '0' * 32 + '.json'), stored)
        else:
            if damage == 'composition':
                stored['composition']['bound_objects'] = {'forged': {'id': '{11111111-1111-1111-1111-111111111111}'}}
            elif damage == 'schema':
                stored['schema_digest'] = 'd' * 64
            else:
                stored['audit'][0]['event_type'] = 'modified'
                event = stored['audit'][0]
                event.pop('event_hash')
                event['event_hash'] = canonical_digest(event)
            stored.pop('record_digest')
            stored['record_digest'] = _record_digest(stored)
            path.write_bytes(canonical_json_bytes(stored))
    elif damage == 'terminal_omission':
        directory = tmp_path / 'turns/turn-01'
        events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
        events = [event for event in events if event.get('item', {}).get('id') != 'cmd-2']
        write_utf8_text_bytes(directory / 'events.jsonl', ''.join(json.dumps(event) + '\n' for event in events))
        facts = json.loads((directory / 'codex-facts.json').read_text())
        facts['command_facts']['command_records'] = [asdict(row) for row in completed_command_records(events, platform_name='posix')]
        _write(directory / 'codex-facts.json', facts)
        grade = json.loads((directory / 'turn-grade.json').read_text())
        grade['broker_prefix_count'] = 1
        _write(directory / 'turn-grade.json', grade)
    elif damage == 'transaction':
        (tmp_path / 'broker/state/transactions').mkdir()
    elif damage == 'pass_gate':
        path = tmp_path / 'turns/turn-01/turn-grade.json'
        grade = json.loads(path.read_text())
        grade['common_gates']['policy_checkpoint'] = True
        _write(path, grade)
    else:
        path = tmp_path / 'expansion-oracle.json'
        oracle = json.loads(path.read_text())
        if damage == 'authorization':
            oracle['authorization'] = {'authorized': True}
        elif damage == 'preview':
            oracle['transaction_id'] = 'tx1-00000000000000000001'
        elif damage == 'pending_preview':
            oracle['preview_after'] = {'pending': True}
        elif damage == 'missing_null':
            oracle.pop('permit')
        elif damage == 'reconciliation':
            oracle.pop('reconciliation')
        elif damage == 'changed_state':
            oracle['reconciliation']['snapshot']['source']['notes'] = 'changed'
            oracle['reconciliation']['snapshot_sha256'] = canonical_digest(oracle['reconciliation']['snapshot'])
        else:
            oracle['reconciliation']['child_reaped'] = False
        _write(path, oracle)
    with pytest.raises(ExpansionArchiveError):
        _verify(tmp_path)


def test_rejected_bind_rejects_self_consistent_wrong_gateway_schema_digest(tmp_path):
    _sealed_invalid_draft_bind(tmp_path)
    path = next((tmp_path / 'broker/state/operation-drafts-v1/records').glob('*.json'))
    stored = json.loads(path.read_text())
    stored['schema_digest'] = 'd' * 64
    stored.pop('record_digest')
    stored['record_digest'] = _record_digest(stored)
    path.write_bytes(canonical_json_bytes(stored))
    broker_path = tmp_path / 'expansion-broker.json'
    broker = json.loads(broker_path.read_text())
    first = broker['records'][0]
    first['payload']['draft']['binding']['schema_digest'] = stored['schema_digest']
    first['payload_sha256'] = canonical_digest(first['payload'])
    first['stdout'] = json.dumps(first['payload'])
    _write(broker_path, broker)
    directory = tmp_path / 'turns/turn-01'
    events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
    for event in events:
        if event.get('item', {}).get('id') == 'cmd-1':
            event['item']['aggregated_output'] = first['stdout']
    write_utf8_text_bytes(directory / 'events.jsonl', ''.join(json.dumps(event) + '\n' for event in events))
    facts = json.loads((directory / 'codex-facts.json').read_text())
    facts['command_facts']['command_records'] = [asdict(row) for row in completed_command_records(events, platform_name='posix')]
    _write(directory / 'codex-facts.json', facts)
    with pytest.raises(ExpansionArchiveError, match='pristine'):
        _verify(tmp_path)


def test_sealed_malformed_core_declaration_is_a_zero_dispatch_isolated_fail(tmp_path):
    _sealed_bound_draft_read_rejection(tmp_path, declaration=True)
    before = {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob('*') if path.is_file()}
    replay = _verify(tmp_path)
    assert replay['archive_valid'] is True and replay['original_status'] == 'FAIL'
    assert replay['business_pass'] is False and replay['executions'] == replay['execution_reservations'] == 0
    assert {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob('*') if path.is_file()} == before


@pytest.mark.parametrize('damage', ('authority', 'missing_authority', 'duplicate_authority', 'draft_id',
    'revision', 'raw_hash', 'normalized_hash', 'argv', 'missing_receipt', 'duplicate_receipt',
    'runner_exit', 'payload', 'dispatch_digest', 'authentication', 'valid_syntax', 'later_dispatch',
    'stored_revision', 'stored_authority', 'stored_settings', 'stored_role', 'stored_audit',
    'projection', 'transaction', 'reconciliation', 'cleanup', 'passed'))
def test_rejected_declaration_requires_exact_bound_draft_and_terminal_no_dispatch_proof(tmp_path, damage):
    _sealed_bound_draft_read_rejection(tmp_path, declaration=True)
    broker = json.loads((tmp_path / 'expansion-broker.json').read_text())
    row = broker['records'][-1]
    argv = row['gateway_arguments']
    if damage in ('authority', 'missing_authority', 'duplicate_authority', 'draft_id', 'revision', 'valid_syntax'):
        if damage == 'authority': argv[3] = 'da1-' + 'a' * 40
        elif damage == 'missing_authority': del argv[2:4]
        elif damage == 'duplicate_authority': argv.extend(['--task-authority', argv[3]])
        elif damage == 'draft_id': argv[1] = 'od1-' + 'a' * 32
        elif damage == 'revision': argv[5] = '1'
        else:
            handle = broker['records'][1]['payload']['bound_object']['handle']
            argv[argv.index('--role') + 1:argv.index('--value')] = ['attenuation_handle', handle]
        _refresh_bound_rejection_receipts(tmp_path, broker)
    elif damage == 'raw_hash': row['raw_argv_sha256'] = 'b' * 64
    elif damage == 'normalized_hash': row['argv_sha256'] = 'b' * 64
    elif damage == 'argv': argv.append('--unrecorded')
    elif damage == 'missing_receipt': broker['records'].pop()
    elif damage == 'duplicate_receipt':
        extra = deepcopy(row)
        extra['sequence'] = 4
        broker['records'].append(extra)
        _refresh_bound_rejection_receipts(tmp_path, broker)
    elif damage == 'runner_exit': row['runner_exit_code'] = 2
    elif damage == 'payload': row['payload'] = {'ok': False}
    elif damage == 'dispatch_digest': row['runner_command_sha256'] = 'b' * 64
    elif damage == 'authentication': row['authenticated'] = False
    elif damage == 'later_dispatch':
        extra = deepcopy(broker['records'][0])
        extra.update(sequence=4, step_name='expansion.step.0003')
        broker['records'].append(extra)
        _refresh_bound_rejection_receipts(tmp_path, broker)
    elif damage.startswith('stored_'):
        path = next((tmp_path / 'broker/state/operation-drafts-v1/records').glob('*.json'))
        stored = json.loads(path.read_text())
        if damage == 'stored_revision': stored['revision'] = 3
        elif damage == 'stored_authority': stored['authority_digest'] = 'b' * 64
        elif damage == 'stored_settings': stored['composition']['business_session']['settings'] = {'foreign': True}
        elif damage == 'stored_role': stored['composition']['business_session']['handles']['objects'][0]['role'] = 'foreign'
        else: stored['audit'][-1]['event_type'] = 'declaration.appended'
        stored['record_digest'] = _record_digest(stored)
        _write(path, stored)
    elif damage == 'projection':
        broker['records'][1]['payload']['bound_object']['name'] = 'OtherAttenuation'
        _refresh_bound_rejection_receipts(tmp_path, broker)
    elif damage == 'transaction': _write(tmp_path / 'broker/state/transactions/forged/state.json', {})
    elif damage in ('reconciliation', 'cleanup'):
        oracle = json.loads((tmp_path / 'expansion-oracle.json').read_text())
        if damage == 'cleanup': oracle['reconciliation']['subprocesses_reaped'] = False
        else: oracle['reconciliation']['snapshot'] = {}
        _write(tmp_path / 'expansion-oracle.json', oracle)
    else:
        result = json.loads((tmp_path / 'expansion-task-result.json').read_text())
        result.update(passed=True, status='PASS')
        _write(tmp_path / 'expansion-task-result.json', result)
    _write(tmp_path / 'expansion-broker.json', broker)
    with pytest.raises(ExpansionArchiveError):
        _verify(tmp_path)


def _sealed_post_verification_query_timeout(root, *, continuation=False, fabricated_pass=False):
    """Exact authenticated read failure after a separately verified transaction."""
    from tests.semantic.test_codex_expansion_broker_reads import query_timeout_receipt, failure_broker, invoke, OWNER
    from tests.semantic.support.codex_gateway_broker import _BROKER_COMPLETE
    with failure_broker(root / "fake-timeout-emitter", query_timeout_receipt()) as live_fake:
        assert invoke(live_fake, "query-object", "--exact-id", OWNER)["exit_code"] == 2
        emitted = live_fake.evidence().as_dict(include_output=True)
    _sealed_c08(root)
    plan = json.loads((root / 'expansion-plan.json').read_text())
    broker = json.loads((root / 'expansion-broker.json').read_text())
    directory = root / 'turns/turn-01'
    events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
    final = events[-2:]
    events = events[:-2]
    extra = [(['query-object', '--exact-id', plan['read_scope']['object_ids'][0]],
        emitted['records'][0]['payload'], emitted['records'][0]['runner_exit_code'])]
    if continuation:
        extra.append((['operations'], {'ok': True, 'status': 'ok', 'command': 'operations'}, 0))
    for argv, payload, exit_code in extra:
        sequence = len(broker['records']) + 1
        model = ['python', str(Path(plan['skill_source']) / 'scripts' / 'run.py'), 'gateway.py', *argv]
        record = deepcopy(broker['records'][-1])
        record.update(sequence=sequence, step_name=f'expansion.step.{sequence:04d}', model_argv=model,
            normalized_model_argv=model, gateway_arguments=argv, raw_argv_sha256=canonical_digest(model),
            argv_sha256=canonical_digest(model), semantic_argv_sha256=canonical_digest(['runner-owned-version', '2025.1', *argv]),
            runner_command_sha256=canonical_digest([plan['trusted_python'], str(Path(plan['skill_source']) / 'scripts' / 'run.py'), 'gateway.py', *argv]),
            payload=payload, payload_sha256=canonical_digest(payload), stdout=json.dumps(payload),
            exit_code=exit_code, runner_exit_code=exit_code, allowed_exit_codes=[0, 2] if exit_code == 2 else [0])
        broker['records'].append(record)
        item = {'id': f'cmd-{sequence}', 'type': 'command_execution', 'command': shlex.join(model),
            'status': 'completed', 'exit_code': exit_code, 'aggregated_output': record['stdout']}
        events.extend([{'type': 'item.started', 'item': {**item, 'status': 'in_progress'}},
            {'type': 'item.completed', 'item': item}])
    names = [record['step_name'] for record in broker['records']]
    broker.update(passed=True if fabricated_pass else emitted['passed'],
        complete=True if fabricated_pass else emitted['complete'],
        terminal_state=_BROKER_COMPLETE if fabricated_pass else emitted['terminal_state'],
        expected_step_names=names, consumed_step_names=names)
    _write(root / 'expansion-broker.json', broker)
    events.extend(final)
    write_utf8_text_bytes(directory / 'events.jsonl', ''.join(json.dumps(event) + '\n' for event in events))
    facts = json.loads((directory / 'codex-facts.json').read_text())
    facts['command_facts']['command_records'] = [asdict(row) for row in completed_command_records(events, platform_name='posix')]
    _write(directory / 'codex-facts.json', facts)
    grade = json.loads((directory / 'turn-grade.json').read_text())
    grade['broker_prefix_count'] = len(broker['records'])
    grade['common_gates']['broker_provenance'] = fabricated_pass
    grade.update(passed=fabricated_pass, errors=[] if fabricated_pass else ['broker_provenance'])
    _write(directory / 'turn-grade.json', grade)
    budget = json.loads((root / 'expansion-agent-budget.json').read_text())
    budget['turns'][0]['gates'] = grade['common_gates']
    _write(root / 'expansion-agent-budget.json', budget)
    result = json.loads((root / 'expansion-task-result.json').read_text())
    result.update(passed=fabricated_pass, turns=budget['turns'])
    _write(root / 'expansion-task-result.json', result)


def test_authenticated_post_verification_read_timeout_replays_fail_without_changing_verified_state(tmp_path):
    _sealed_post_verification_query_timeout(tmp_path)
    files = {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob('*') if path.is_file()}
    assert json.loads((tmp_path / 'expansion-broker.json').read_text())['terminal_state'] == 'INDETERMINATE'
    replay = _verify(tmp_path)
    assert replay['archive_valid'] is True and replay['original_status'] == 'FAIL'
    assert replay['business_pass'] is False and replay['gateway_verification_state'] == 'result_schema_checked'
    assert files == {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob('*') if path.is_file()}


@pytest.mark.parametrize('contradiction', ['continuation', 'fabricated_pass'])
def test_exact_read_timeout_cannot_replay_later_dispatch_or_pass(tmp_path, contradiction):
    _sealed_post_verification_query_timeout(tmp_path, **{contradiction: True})
    with pytest.raises(ExpansionArchiveError, match='terminal|timeout'):
        _verify(tmp_path)


def test_query_timeout_archive_requires_exact_production_terminal_state_casing(tmp_path):
    _sealed_post_verification_query_timeout(tmp_path)
    path = tmp_path / 'expansion-broker.json'
    broker = json.loads(path.read_text())
    broker['terminal_state'] = broker['terminal_state'].lower()
    _write(path, broker)
    with pytest.raises(ExpansionArchiveError, match='query timeout is terminal'):
        _verify(tmp_path)
