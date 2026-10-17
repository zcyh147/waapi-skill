"""Public query producer → authenticated Broker/task → archive/scheduler."""
import json
from pathlib import Path
import pytest
from tests.semantic.test_codex_repair_read_rejection import produce_rejected_task, INPUTS
from tests.semantic.support.codex_gateway_broker import CodexGatewayBroker
from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive
from tests.semantic.run_codex_skill_matrix import expansion_case_isolated
from tests.unit.test_field_interface_closure_gateway import gateway, FieldTask, FIRST


def public_reads(tmp_path, monkeypatch, selector):
    """Only native client and transport are fake; Gateway owns every payload."""
    task = FieldTask.__new__(FieldTask)
    task.version = "2025.1"
    task.calls = []
    task.project_file = tmp_path / "Fixture.wproj"
    task.project_file.write_text("fixture")
    task.metadata = {key: {"name": key, "type": "Real32"} for key in ("Min", "Max", "InitialValue")}
    target = {"id": FIRST, "name": "Target", "type": "GameParameter", "path": r"\Game Parameters\Target",
              "@Min": -12, "@Max": 36, "@InitialValue": 7}
    original = task.call
    def call(uri, args=None, options=None):
        if uri.endswith("object.get") and args.get("waql") != "from type Project take 1":
            return {"return": [] if "Missing" in json.dumps(args) else [target]}
        return original(uri, args, options)
    task.call = call
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"wwise_version": "2025.1", "waapi_port": 31337, "waapi_host": "127.0.0.1"}))
    queries = [[*selector, "query-schema"], ["query-object", "--search-text", "Missing", "--max-results", "10"],
        ["query-object", "--search-text", "Target", "--max-results", "10"],
        ["query-object", "--exact-id", FIRST, "--include-field", "Min", "--include-field", "Max", "--include-field", "InitialValue"]]
    rows = []
    for argv in queries:
        code, payload = gateway.execute_gateway(argv, env={"WAAPI_SKILL_CONFIG_PATH": str(config)}, client_factory=lambda _: task)
        assert code == 0, json.dumps(payload)
        # Broker strips the offline selector before trusted execution.
        rows.append((["query-schema"] if argv == queries[0] else argv, payload))
    script = tmp_path / "transport.py"
    script.write_text("import json,sys\nrows=" + repr(rows) + "\nprint(json.dumps(next(payload for argv,payload in rows if argv==sys.argv[1:])))\n")
    launch = CodexGatewayBroker._launch_runner
    def replay(self, command, *, runner_env):
        return launch(self, [command[0], str(script), *command[3:]], runner_env=runner_env)
    monkeypatch.setattr(CodexGatewayBroker, "_launch_runner", replay)
    return [(argv, 0) for argv in queries]


@pytest.mark.parametrize("selector", [["--version", "2025.1"], ["--wwise-version=2025.1"]])
def test_public_versioned_schema_and_refinement_archive_as_read_only(tmp_path, monkeypatch, selector):
    calls = public_reads(tmp_path, monkeypatch, selector)
    root, outcome, _ = produce_rejected_task(tmp_path, monkeypatch, gateway_calls=calls)
    assert outcome["passed"] is True, outcome
    replay = verify_expansion_task_archive(root, expected_unit_id="REPAIR25-F2", expected_version="2025.1", expected_inputs_sha256=INPUTS)
    assert replay["archive_valid"] and replay["business_pass"]
    assert replay["executions"] == replay["execution_reservations"] == 0


def test_versioned_schema_receipt_reaches_notice_evidence_without_losing_authentication(tmp_path, monkeypatch):
    from tests.semantic.test_codex_expansion_notice_adjudication import public_read_notice_context
    from tests.semantic.support.codex_expansion_notice_adjudication import decide_expansion_notice
    from tests.semantic.support.codex_harness import completed_command_records
    from tests.semantic.support.codex_expansion_archive import _scope
    calls = public_reads(tmp_path, monkeypatch, ["--version", "2025.1"])
    root, _, _ = produce_rejected_task(tmp_path, monkeypatch, gateway_calls=calls)
    records = json.loads((root / "expansion-broker.json").read_text())["records"]
    events = [json.loads(line) for line in (root / "turns/turn-01/events.jsonl").read_text().splitlines()]
    event = next(row for row in events if row.get("type") == "item.completed" and row.get("item", {}).get("id") == "query-0")
    result, commands, kwargs = public_read_notice_context()
    # Replace the old synthetic read with the actual public schema receipt.
    result.stdout = json.dumps(event) + "\n" + "\n".join(result.stdout.splitlines()[1:])
    commands = [*completed_command_records([event]), *commands[1:]]
    kwargs.update(broker_records=records[:1], read_admission=_scope(json.loads((root / "expansion-plan.json").read_text())))
    decision = decide_expansion_notice(result, commands, adjudication_contract="waapi-skill.expansion-notice-adjudication/v4", **kwargs)
    assert decision["outcome"] == "review_required", decision
    reads = decision["input"]["pre_execution_public_reads"]["reads"]
    assert len(reads) == 1
    assert reads[0]["gateway_arguments"] == calls[0][0]
    records[0]["authenticated"] = False
    assert decide_expansion_notice(result, commands, adjudication_contract="waapi-skill.expansion-notice-adjudication/v4", **kwargs)["outcome"] == "material_reject"


def scheduler_record(root, status="PASS"):
    return {"scenario_id": "REPAIR25-F2", "version": "2025.1", "status": status, "scenario_root": str(root.parent),
        "runner_outcome": {"task_root": str(root), "inputs_sha256": INPUTS, "checks": {"trusted_oracle_closed": True},
            "lifecycle": {"scenario_id": "REPAIR25-F2", "version": "2025.1", "source_hash_before": {"sha256": "source"},
                "source_hash_after": {"sha256": "source"}, "source_mtime_before_ns": 1, "source_mtime_after_ns": 1, "errors": []}}}


@pytest.mark.parametrize("fault", [None, "authentication", "raw_argv", "runner_hash", "semantic_hash", "interpreter", "source", "cleanup"])
def test_versioned_read_archive_keeps_exact_proof_and_scheduler_boundaries(tmp_path, monkeypatch, fault):
    from tests.semantic.support.codex_expansion_policy import canonical_digest
    calls = public_reads(tmp_path, monkeypatch, ["--version=2025.1"])
    root, _, _ = produce_rejected_task(tmp_path, monkeypatch, gateway_calls=calls)
    record = scheduler_record(root)
    if fault in {"source", "cleanup"}:
        lifecycle = record["runner_outcome"]["lifecycle"]
        if fault == "source": lifecycle["source_hash_after"] = {"sha256": "changed"}
        else: lifecycle["errors"] = ["cleanup incomplete"]
    elif fault == "interpreter":
        path = root / "expansion-plan.json"; plan = json.loads(path.read_text()); plan.pop("sha256")
        # A different lexical spelling cannot be substituted even if it resolves
        # to the same executable. The Broker hash remains exact.
        actual = Path(plan["trusted_python"])
        alternate = str(actual.resolve())
        if alternate == str(actual): alternate = str(actual.parent / ".." / actual.parent.name / actual.name)
        assert alternate != str(actual)
        plan["trusted_python"] = alternate
        plan["sha256"] = canonical_digest(plan); path.write_text(json.dumps(plan))
        path = root / "expansion-task-result.json"; result = json.loads(path.read_text())
        result["plan_sha256"] = plan["sha256"]; path.write_text(json.dumps(result))
    elif fault:
        path = root / "expansion-broker.json"; evidence = json.loads(path.read_text()); row = evidence["records"][0]
        if fault == "authentication": row["authenticated"] = False
        elif fault == "raw_argv": row["gateway_arguments"][0] = "--version=2024.1"
        elif fault == "runner_hash": row["runner_command_sha256"] = "0" * 64
        else: row["semantic_argv_sha256"] = "0" * 64
        path.write_text(json.dumps(evidence))
    assert expansion_case_isolated(record) is (fault is None)


@pytest.mark.parametrize("argv", [["--version", "2025.1", "query-object", "--exact-id", FIRST],
    ["--version", "2025.1", "draft-start", "object.create"], ["draft-start", "object.create"],
    ["--version", "2024.1", "query-schema"], ["--host", "127.0.0.1", "query-schema"],
    ["--state-dir", "/tmp/escape", "query-schema"], ["--invalid", "query-schema"],
    ["--version", "2025.1", "--version", "2025.1", "query-schema"]])
def test_unsupported_globals_and_real_mutations_never_dispatch(tmp_path, monkeypatch, argv):
    def forbidden(*args, **kwargs):
        raise AssertionError("rejected input dispatched")
    monkeypatch.setattr(CodexGatewayBroker, "_launch_runner", forbidden)
    root, outcome, held = produce_rejected_task(tmp_path, monkeypatch, rejected_argv=argv)
    assert outcome["status"] == "FAIL" and outcome["passed"] is False
    record = held["broker"].evidence().records[0]
    assert not record.accepted and record.authenticated
    assert not (root / "broker/state/transactions").exists()


def reject_as_prior_policy(monkeypatch):
    from tests.semantic.support.codex_repair_broker_policy import RepairBrokerPolicy
    from tests.semantic.support.codex_expansion_policy import ExpansionPolicyError
    original = RepairBrokerPolicy.prepare
    def prior(self, argv, *, state_directory):
        if argv[0].startswith("-"):
            raise ExpansionPolicyError("repair read-only workflow cannot prepare or execute a transaction")
        return original(self, argv, state_directory=state_directory)
    monkeypatch.setattr(RepairBrokerPolicy, "prepare", prior)


@pytest.mark.parametrize("rejected_argv", [["--version", "2025.1", "query-schema"],
    ["--version", "2024.1", "query-schema"], ["--version", "2025.1", "query-object", "--exact-id", FIRST]])
def test_authenticated_prior_schema_refusal_remains_fail_and_scheduler_reaches_next_unit(tmp_path, monkeypatch, rejected_argv):
    from tests.semantic import run_codex_skill_matrix as matrix
    from tests.semantic.support.codex_expansion_runtime import ExpansionOutcome
    from tests.semantic.test_codex_repair_cli_wiring import options
    if rejected_argv == ["--version", "2025.1", "query-schema"]:
        reject_as_prior_policy(monkeypatch)
    ids = ["REPAIR25-F2", "REPAIR25-F3"]
    selected = options(tmp_path, monkeypatch, "matrix", *[part for value in ids for part in ("--case-id", value)])
    monkeypatch.setattr(matrix, "prepare_iteration_root", lambda path, **_: path.mkdir())
    called = []
    def execute(unit, *, scenario_root, options):
        called.append(unit.unit_id)
        if unit.case_id == "F3":
            raise RuntimeError("fake executor stops after proving F3 was reached")
        scenario_root.mkdir(parents=True)
        root, outcome, _ = produce_rejected_task(scenario_root, monkeypatch, rejected_argv=rejected_argv)
        replay = verify_expansion_task_archive(root, expected_unit_id=unit.unit_id, expected_version=unit.version, expected_inputs_sha256=INPUTS)
        assert replay["archive_valid"] and not replay["business_pass"] and replay["original_status"] == "FAIL"
        assert outcome["status"] == "FAIL" and not outcome["passed"]
        return ExpansionOutcome(unit.unit_id, unit.version, "FAIL", "authenticated pre-dispatch refusal", str(scenario_root),
            str(root), outcome["thread_id"], {"trusted_oracle_closed": True}, scheduler_record(root)["runner_outcome"]["lifecycle"], INPUTS)
    assert matrix.run_heavy_v3_matrix(selected, unit_runner=execute, dependency_preflight=lambda: {"ok": True}) == 1
    assert called == ids
    summary = json.loads((selected.iteration_root / "summary.json").read_text())
    assert summary["failed_unit_ids"] == ["REPAIR25-F2"] and not summary["all_selected_passed"]


@pytest.mark.parametrize("fault", ["authentication", "dispatch", "argv_digest", "failed_assertion"])
def test_prior_versioned_refusal_requires_untampered_no_dispatch_proof(tmp_path, monkeypatch, fault):
    reject_as_prior_policy(monkeypatch)
    root, _, _ = produce_rejected_task(tmp_path, monkeypatch, rejected_argv=["--version", "2025.1", "query-schema"])
    if fault == "failed_assertion":
        path = root / "expansion-task-result.json"; value = json.loads(path.read_text())
        value["assertions"]["read_refinement"] = True
    else:
        path = root / "expansion-broker.json"; value = json.loads(path.read_text()); record = value["records"][0]
        if fault == "authentication": record["authenticated"] = False
        elif fault == "dispatch": record["admission_rejection"]["runner_dispatched"] = True
        else: record["admission_rejection"]["gateway_argv_sha256"] = "0" * 64
    path.write_text(json.dumps(value))
    assert not expansion_case_isolated(scheduler_record(root, "FAIL"))


@pytest.mark.parametrize("argv", [["--version", "2024.1", "query-schema"],
    ["--version=2025.1", "query-object", "--exact-id", FIRST]])
@pytest.mark.parametrize("marked", [True, False, "tampered"])
def test_rejected_version_prefix_preserves_fail_only_with_initial_admission_proof(tmp_path, monkeypatch, argv, marked):
    root, outcome, _ = produce_rejected_task(tmp_path, monkeypatch, rejected_argv=argv)
    assert outcome["status"] == "FAIL" and outcome["passed"] is False
    if marked is not True:
        path = root / "expansion-broker.json"; evidence = json.loads(path.read_text())
        if marked is False: evidence["records"][0].pop("admission_rejection")
        else: evidence["records"][0]["admission_rejection"]["runner_dispatched"] = True
        path.write_text(json.dumps(evidence))
    assert expansion_case_isolated(scheduler_record(root, "FAIL")) is (marked is True)
    if marked is True:
        replay = verify_expansion_task_archive(root, expected_unit_id="REPAIR25-F2", expected_version="2025.1", expected_inputs_sha256=INPUTS)
        assert replay["original_status"] == "FAIL" and not replay["business_pass"]
        assert replay["executions"] == replay["execution_reservations"] == 0
