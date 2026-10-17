"""Current public Gateway transactions must cross the formal archive boundary."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from tests.unit.test_gameparameter_class_fields_gateway import NativeParameterTask, FIRST, CREATED
from tests.semantic.support.codex_transaction_seal import create_preview_seal, verify_preview_seal, TransactionSealError
from wwise_waapi.transactions import TransactionStore


def produce_transaction(path, monkeypatch, *, policy="allow_changes", version="2025.1"):
    from tests.unit.test_field_interface_closure_gateway import FieldTask
    rows = []
    original = FieldTask.run
    def capture(self, *argv):
        code, payload = original(self, *argv)
        assert code == 0, payload
        if argv[0] != "config-set":
            rows.append((list(argv), deepcopy(payload)))
        return code, payload
    monkeypatch.setattr(FieldTask, "run", capture)
    task = NativeParameterTask(path, version)
    task.run("config-set", "--project-modification-policy", policy)
    before = deepcopy(task.objects)
    task.declare_complete_parameter()
    task.step("draft-check")
    _, preview = task.step("preview-from-draft", *(["--apply"] if policy == "allow_changes" else []))
    tx = preview["transaction_id"]
    seal = None
    if policy == "ask_before_changes":
        seal = create_preview_seal(path / "state", tx)
        _, shown = task.run("transaction-show", tx)
        task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    task.run("execute", tx)
    _, verified = task.run("verify", tx)
    assert verified["verified"] is True
    assert [task.objects[CREATED][field] for field in ("Min", "Max", "InitialValue")] == [-12, 36, 7]
    return task, rows, tx, before, seal


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_public_gateway_transaction_crosses_preview_seal_and_verification(tmp_path, monkeypatch, version):
    task, rows, tx, _, seal = produce_transaction(tmp_path, monkeypatch, policy="ask_before_changes", version=version)
    result = verify_preview_seal(tmp_path / "state", tx, seal, allowed_states=("verified",))
    assert result.transaction_id == tx
    artifact = TransactionStore(tmp_path / "state").load_preview(tx).artifact
    assert artifact["connection_configuration"] == {"config_path": str(tmp_path / "config.json"),
        "waapi_host": "127.0.0.1", "waapi_port": 31337, "wwise_version": version}


def seal_public_archive(root, task, rows, tx):
    """Use existing archive fixture scaffolding around untouched public store files."""
    import hashlib
    import shutil
    import shlex
    from dataclasses import asdict
    from tests.semantic.test_codex_expansion_archive import _sealed_c08, _write
    from tests.semantic.support.codex_expansion_policy import canonical_digest, ExpansionReadScope
    from tests.semantic.support.codex_repair_cases import verify_f3, F3_ASSERTIONS
    from tests.semantic.support.codex_harness import completed_command_records
    _sealed_c08(root)
    shutil.rmtree(root / "broker/state/transactions")
    shutil.copytree(task.path / "state/transactions", root / "broker/state/transactions")
    preview = TransactionStore(task.path / "state").load_preview(tx)
    artifact_hash = preview.artifact_hash
    parent = {key: task.objects[FIRST][key] for key in ("id", "name", "type", "path")}
    created = task.objects[CREATED]
    expected = {key: created[key] for key in ("name", "type", "path")}
    expected.update(parent=FIRST, properties={"Min": -12, "Max": 36, "InitialValue": 7})
    before = {"objects": {FIRST: parent}, "source_integrity": {"sha256": "a" * 64, "mtime_ns": 1}, "media": {}, "complete": True}
    after = deepcopy(before)
    after["objects"][CREATED] = {"id": CREATED, **expected}
    assertions = verify_f3(before, after, expected=expected, target_id=CREATED)
    assert all(assertions.values())
    plan = json.loads((root / "expansion-plan.json").read_text()); plan.pop("sha256")
    scope = ExpansionReadScope(frozenset({FIRST}), frozenset({"object.create"}))
    plan.update(contract="waapi-skill.repair-task-plan/v1", unit_id="REPAIR25-F3", operation="object.create", request_schema_uri=None,
        model="gpt-5.6-terra", reasoning_effort="medium", service_tier="default", before=before,
        prompts=["Create WeatherIntensity with range -12 to 36 and default 7."], required_assertions=sorted(F3_ASSERTIONS),
        read_scope={key: sorted(value) if isinstance(value, frozenset) else value for key, value in asdict(scope).items()},
        read_scope_sha256=scope.digest, oracle_parameters={"expected": expected, "target_id": CREATED},
        preview_parameters={"expected": expected, "parent_id": FIRST})
    digest = canonical_digest(plan); _write(root / "expansion-plan.json", {**plan, "sha256": digest})
    oracle = json.loads((root / "expansion-oracle.json").read_text())
    oracle.update(before=before, after=after, preview_before=before, preview_after=before, assertions=assertions,
        transaction_id=tx, artifact_hash=artifact_hash, gateway_verification_state="verified")
    oracle["permit"].update(transaction_id=tx, artifact_sha256=artifact_hash)
    _write(root / "expansion-oracle.json", oracle)
    broker = json.loads((root / "expansion-broker.json").read_text())
    template = broker["records"][0]
    directory = root / "turns/turn-01"
    events = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
    events = [event for event in events if event.get("type") in {"thread.started", "turn.started"}
              or event.get("item", {}).get("id") == "read-skill"]
    records = []
    for index, (argv, payload) in enumerate(rows, 1):
        model = ["python", str(Path(plan["skill_source"]) / "scripts/run.py"), "gateway.py", *argv]
        semantic = ["runner-owned-version", "2025.1", *argv]
        if "--expected-revision" in semantic:
            offset = semantic.index("--expected-revision") + 1
            semantic[offset] = int(semantic[offset])
        stdout = json.dumps(payload)
        record = {**deepcopy(template), "sequence": index, "step_name": f"expansion.step.{index:04d}",
            "model_argv": model, "normalized_model_argv": model, "gateway_arguments": argv,
            "raw_argv_sha256": canonical_digest(model), "argv_sha256": canonical_digest(model),
            "semantic_argv_sha256": canonical_digest(semantic), "payload": payload, "payload_sha256": canonical_digest(payload),
            "stdout": stdout, "runner_command_sha256": canonical_digest([plan["trusted_python"], *model[1:]]),
            "started_at_unix": index, "finished_at_unix": index + .1}
        records.append(record)
        item = {"id": f"cmd-{index}", "type": "command_execution", "command": shlex.join(model),
                "status": "completed", "exit_code": 0, "aggregated_output": stdout}
        events.extend([{"type": "item.started", "item": {**item, "status": "in_progress"}}, {"type": "item.completed", "item": item}])
        if argv[0] == "preview-from-draft":
            events.append({"type": "item.completed", "item": {"id": "notice", "type": "agent_message",
                "text": "I will create WeatherIntensity with range -12 to 36 and default 7."}})
    events.extend([{"type": "item.completed", "item": {"id": "final", "type": "agent_message", "text": "Done."}}, {"type": "turn.completed"}])
    names = [record["step_name"] for record in records]
    broker.update(records=records, expected_step_names=names, consumed_step_names=names)
    _write(root / "expansion-broker.json", broker)
    result = json.loads((root / "expansion-task-result.json").read_text())
    result.update(unit_id="REPAIR25-F3", plan_sha256=digest, assertions=assertions, gateway_verification_state="verified")
    _write(root / "expansion-task-result.json", result)
    grade = json.loads((directory / "turn-grade.json").read_text())
    grade.update(prompt_sha256=hashlib.sha256(plan["prompts"][0].encode()).hexdigest(), broker_prefix_count=len(records))
    _write(directory / "turn-grade.json", grade)
    facts = json.loads((directory / "codex-facts.json").read_text())
    facts["command_facts"] = {"command_records": [asdict(row) for row in completed_command_records(events, platform_name="posix")]}
    _write(directory / "codex-facts.json", facts)
    (directory / "events.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))
    (directory / "prompt.txt").write_text(plan["prompts"][0] + "\n")


@pytest.mark.parametrize("fault", [None, "missing", "endpoint_drift"])
def test_public_policy_authorized_transaction_reaches_archive_and_scheduler(tmp_path, monkeypatch, fault):
    from tests.semantic.test_codex_expansion_archive import INPUTS
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive, ExpansionArchiveError
    from tests.semantic.run_codex_skill_matrix import expansion_case_isolated
    producer = tmp_path / "producer"; producer.mkdir()
    task, rows, tx, _, _ = produce_transaction(producer, monkeypatch)
    root = tmp_path / "archive"
    seal_public_archive(root, task, rows, tx)
    if fault:
        from wwise_waapi.canonical import canonical_sha256
        path = root / "broker/state/transactions" / tx / "preview.json"
        envelope = json.loads(path.read_text())
        if fault == "missing":
            del envelope["artifact"]["connection_configuration"]
        else:
            envelope["artifact"]["connection_configuration"]["waapi_port"] = 31338
        envelope["artifact_hash"] = canonical_sha256(envelope["artifact"])
        path.write_text(json.dumps(envelope))
        with pytest.raises(ExpansionArchiveError, match="connection_configuration"):
            verify_expansion_task_archive(root, expected_unit_id="REPAIR25-F3", expected_version="2025.1", expected_inputs_sha256=INPUTS)
    else:
        replay = verify_expansion_task_archive(root, expected_unit_id="REPAIR25-F3", expected_version="2025.1", expected_inputs_sha256=INPUTS)
        assert replay["business_pass"] is True
    record = {"scenario_id": "REPAIR25-F3", "version": "2025.1", "status": "PASS", "scenario_root": str(tmp_path),
        "runner_outcome": {"task_root": str(root), "inputs_sha256": INPUTS, "checks": {"trusted_oracle_closed": True},
            "lifecycle": {"scenario_id": "REPAIR25-F3", "version": "2025.1", "source_hash_before": {"sha256": "source"},
                "source_hash_after": {"sha256": "source"}, "source_mtime_before_ns": 1, "source_mtime_after_ns": 1, "errors": []}}}
    assert expansion_case_isolated(record) is (fault is None)


@pytest.mark.parametrize("fault", ["missing", "extra", "null", "host", "port", "boolean_port", "version", "relative_path", "traversal"])
def test_current_archive_rejects_malformed_or_mismatched_configuration(tmp_path, monkeypatch, fault):
    from tests.semantic.support.codex_transaction_seal import _validate_artifact
    task, _, tx, _, _ = produce_transaction(tmp_path, monkeypatch)
    artifact = deepcopy(TransactionStore(tmp_path / "state").load_preview(tx).artifact)
    configuration = artifact["connection_configuration"]
    if fault == "missing":
        del artifact["connection_configuration"]
    elif fault == "extra":
        configuration["unreviewed"] = True
    elif fault == "null":
        artifact["connection_configuration"] = None
    else:
        key, value = {"host": ("waapi_host", "other.example"), "port": ("waapi_port", 31338),
            "boolean_port": ("waapi_port", True), "version": ("wwise_version", "2022.1"),
            "relative_path": ("config_path", "config.json"), "traversal": ("config_path", "/tmp/../config.json")}[fault]
        configuration[key] = value
    with pytest.raises(TransactionSealError):
        _validate_artifact(artifact, require_connection_configuration=True)


@pytest.mark.parametrize("path", [r"C:\Users\Audio & 测试\config.json", r"\\server\share\Audio & 测试\config.json"])
def test_archive_configuration_path_keeps_foreign_host_identity_without_opening_it(tmp_path, monkeypatch, path):
    from tests.semantic.support.codex_transaction_seal import _validate_artifact
    _, _, tx, _, _ = produce_transaction(tmp_path, monkeypatch)
    artifact = deepcopy(TransactionStore(tmp_path / "state").load_preview(tx).artifact)
    artifact["connection_configuration"]["config_path"] = path
    assert _validate_artifact(artifact, require_connection_configuration=True)
    assert artifact["connection_configuration"]["config_path"] == path


def test_changed_configuration_bytes_cannot_reuse_public_preview_seal(tmp_path, monkeypatch):
    _, _, tx, _, seal = produce_transaction(tmp_path, monkeypatch, policy="ask_before_changes")
    path = tmp_path / "state/transactions" / tx / "preview.json"
    payload = json.loads(path.read_text())
    payload["artifact"]["connection_configuration"]["config_path"] = str(tmp_path / "other-config.json")
    path.write_text(json.dumps(payload))
    with pytest.raises(TransactionSealError):
        verify_preview_seal(tmp_path / "state", tx, seal, allowed_states=("verified",))
