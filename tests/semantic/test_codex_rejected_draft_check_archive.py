"""Rejected-check archive proof through the full existing verification seam."""
import copy
import json
from pathlib import Path
import pytest

from tests.semantic.support.codex_expansion_archive import ExpansionArchiveError, verify_expansion_task_archive
from tests.semantic.support.codex_expansion_music_case import M01_ASSERTIONS
from tests.semantic.support.codex_expansion_policy import ExpansionReadScope, canonical_digest
from tests.semantic.test_codex_expansion_archive import (
    INPUTS, _GATEWAY, _refresh_bound_rejection_receipts, _sealed_invalid_draft_bind, _write,
)
from wwise_waapi.business_declarations import BusinessContext, BusinessHandleRegistry, NewDescendantTarget
from wwise_waapi.business_declaration_state import BusinessDeclarationSession
from wwise_waapi.operation_drafts import OperationDraftStore, _record_digest
from wwise_waapi.operation_composer import operation_composer_digest


_WITNESS = json.loads((Path(__file__).parents[1] / "fixtures/semantic/expansion-rejected-draft-check-0e04c8c.json").read_text())


def _verify(root):
    plan = json.loads((root / "expansion-plan.json").read_text())
    return verify_expansion_task_archive(root, expected_unit_id=plan["unit_id"],
        expected_version=plan["version"], expected_inputs_sha256=INPUTS)


def _fixture(root, version="2025.1"):
    _sealed_invalid_draft_bind(root)
    plan = json.loads((root / "expansion-plan.json").read_text())
    plan.update(unit_id="EXP" + version[2:4] + "-M01", version=version,
        required_assertions=sorted(M01_ASSERTIONS), before=copy.deepcopy(_WITNESS["before"]))
    parent = plan["before"]["parent"]
    plan["read_scope"]["object_ids"] = [parent["id"]]
    plan["read_scope"]["relationship_sources"] = [parent["id"]]
    plan["read_scope"]["owned_project_reads"] = True
    scope = ExpansionReadScope(**{key: frozenset(value) if isinstance(value, list) else value for key, value in plan["read_scope"].items()})
    plan["read_scope_sha256"] = scope.digest
    plan.pop("sha256")
    plan["sha256"] = canonical_digest(plan)
    _write(root / "expansion-plan.json", plan)
    broker = json.loads((root / "expansion-broker.json").read_text())
    start = broker["records"][0]
    if version != "2025.1":
        # Only disposable test setup is replaced; production verification is
        # read-only and never touches either this or the frozen native store.
        old = start["payload"]["draft"]["draft_id"]
        (root / "broker/state/operation-drafts-v1/records" / (old + ".json")).unlink()
        fresh = OperationDraftStore(root / "broker/state").start(operation="audio.import", version=version,
            schema_digest=_GATEWAY.operation_draft_schema_digest("audio.import", version), composer_digest=operation_composer_digest("audio.import", version))
        record = fresh.record
        start["payload"].update(task_authority=fresh.task_authority, draft={
            "contract": "waapi-skill.operation-draft/v1", "draft_id": fresh.draft_id, "revision": 1,
            "business_revision": 0, "lifecycle_state": "editable", "binding": {"operation": "audio.import", "version": version, "schema_digest": record.schema_digest},
            "created_at": record.created_at, "updated_at": record.updated_at, "expires_at": record.expires_at,
            "declarations": [], "check": None, "seal": None, "preview": None})
    draft_id, authority = start["payload"]["draft"]["draft_id"], start["payload"]["task_authority"]
    context = BusinessContext.create(task_authority=authority, project_id=parent["id"],
        project_path="/fixture/SampleProject.wproj", wwise_version=version, wwise_build="v" + version + ".7")
    store = OperationDraftStore(root / "broker/state")
    objects = []
    def bind(session):
        handles = BusinessHandleRegistry.from_dict(session.handles.as_dict())
        objects.append(handles.bind_object(object_id=parent["id"], name=parent["name"], object_type=parent["type"], path=parent["path"], semantic_kind=None))
        return session.with_handle_registry(handles)
    bound = store.apply_business_update(draft_id, task_authority=authority, expected_revision=1,
        schema_digest=start["payload"]["draft"]["binding"]["schema_digest"], composer_digest=operation_composer_digest("audio.import", version),
        context=context, update=bind, event_type="handles.bound")
    handle = objects[0]
    def receipt(argv, revision, **extra):
        row = copy.deepcopy(start)
        row.update(gateway_arguments=argv, payload={"ok": True, "command": argv[0], "draft": {
            "contract": "waapi-skill.operation-draft/v1", "draft_id": draft_id, "revision": revision,
            "lifecycle_state": "editable", "binding": start["payload"]["draft"]["binding"], **extra}})
        return row
    binding = receipt(["draft-bind-object", draft_id, "--task-authority", authority, "--expected-revision", "1", "--object-id", parent["id"]], 2, business_revision=0)
    binding["payload"]["bound_object"] = {"handle": handle.handle, "name": handle.name, "type": handle.object_type, "semantic_kind": handle.semantic_kind}
    project_file = root / "broker/evidence/fixture-project.json"
    project_summary = {"api": "ak.wwise.core.getProjectInfo", "ok": True, "dry_run": False,
        "version": version, "evidence_path": str(project_file)}
    _write(project_file, {**project_summary, "result": {"id": context.project_id, "path": context.project_path}})
    binding["payload"]["project_call"] = project_summary
    media = root / "media"
    media.mkdir()
    for name in ("Quiet.wav", "Full.wav"):
        (media / name).write_bytes(b"fixture-media")
    plan["preview_parameters"] = {"media": {"Quiet": str(media / "Quiet.wav"), "Full": str(media / "Full.wav")},
        "parent_path": parent["path"], "segment_name": "Imported", "version": version}
    plan.pop("sha256")
    plan["sha256"] = canonical_digest(plan)
    _write(root / "expansion-plan.json", plan)
    argv = copy.deepcopy(_WITNESS["declaration_argv"])
    argv[1] = draft_id
    argv[argv.index("--task-authority") + 1] = authority
    argv[argv.index("--new-row") + 2] = handle.handle
    argv[argv.index("--media-directory") + 1] = str(media)
    def declare(session):
        captured = _WITNESS["native_stored_facts"]["declarations"]
        references = {captured[0]["target"]["parent_handle"]: handle.handle}
        for row in captured:
            target, fields = row["target"], copy.deepcopy(row["fields"])
            assert target["form"] == "new-descendant"
            if "media_file" in fields:
                fields["media_file"] = str(media / Path(fields["media_file"]).name)
            session = session.with_new_declaration(declaration_id=row["declaration_id"],
                target=NewDescendantTarget(references[target["parent_handle"]], target["name"], target["kind"]), fields=fields)
            references[row["result_handle"]] = session.declarations[-1].result_handle
        return session
    store.apply_business_update(draft_id, task_authority=authority, expected_revision=2,
        schema_digest=bound.schema_digest, composer_digest=bound.composer_digest, context=context,
        update=declare, event_type="declaration.batch-added")
    declaration = receipt(argv, 3, batch_receipt={"contract": "waapi-skill.business-declaration-batch-receipt/v1", "chunk_declaration_count": 3, "cumulative_declaration_count": 3, "switch_assignment_count": 0},
        next_command={"command": "draft-check", "gateway_argv": ["draft-check", draft_id, "--task-authority", authority, "--expected-revision", "3"]})
    reject = copy.deepcopy(_WITNESS["rejected_record"])
    reject["gateway_arguments"][1] = draft_id
    broker["records"] = [start, binding, declaration, reject]
    for index, row in enumerate(broker["records"], 1):
        row.update(sequence=index, started_at_unix=index, finished_at_unix=index + .1, duration_seconds=.1)
        if row["accepted"]:
            row["step_name"] = f"expansion.step.{index:04d}"
    names = [row["step_name"] for row in broker["records"] if row["accepted"]]
    broker.update(expected_step_names=names, consumed_step_names=names)
    _refresh_bound_rejection_receipts(root, broker)
    broker = json.loads((root / "expansion-broker.json").read_text())
    for row in broker["records"]:
        if row["accepted"]:
            argv = row["gateway_arguments"]
            semantic = ["runner-owned-version", version, *argv]
            if "--expected-revision" in argv:
                semantic[2 + argv.index("--expected-revision") + 1] = int(argv[argv.index("--expected-revision") + 1])
            row["semantic_argv_sha256"] = canonical_digest(semantic)
    _write(root / "expansion-broker.json", broker)
    result = json.loads((root / "expansion-task-result.json").read_text())
    result.update(unit_id=plan["unit_id"], version=version, plan_sha256=plan["sha256"])
    result["turns"][0]["broker_prefix_count"] = 4
    _write(root / "expansion-task-result.json", result)
    oracle = json.loads((root / "expansion-oracle.json").read_text())
    oracle["before"] = oracle["reconciliation"]["snapshot"] = plan["before"]
    oracle["reconciliation"]["snapshot_sha256"] = canonical_digest(plan["before"])
    _write(root / "expansion-oracle.json", oracle)
    grade = json.loads((root / "turns/turn-01/turn-grade.json").read_text())
    grade["broker_prefix_count"] = 4
    _write(root / "turns/turn-01/turn-grade.json", grade)
    budget = json.loads((root / "expansion-agent-budget.json").read_text())
    budget["turns"] = result["turns"]
    _write(root / "expansion-agent-budget.json", budget)


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_terminal_wrong_authority_check_is_an_unchanged_isolated_fail(tmp_path, version):
    _fixture(tmp_path, version)
    before = {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob("*") if path.is_file()}
    replay = _verify(tmp_path)
    assert replay["archive_valid"] is True and replay["original_status"] == "FAIL"
    assert replay["business_pass"] is False and replay["executions"] == replay["execution_reservations"] == 0
    assert before == {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob("*") if path.is_file()}


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
@pytest.mark.parametrize("assertions", [{"exact_segment_track_source_topology": True}, None])
def test_rejected_check_cannot_carry_unexecuted_oracle_assertions(tmp_path, version, assertions):
    _fixture(tmp_path, version)
    path = tmp_path / "expansion-oracle.json"
    oracle = json.loads(path.read_text())
    if assertions is None:
        oracle.pop("assertions")
    else:
        oracle["assertions"] = assertions
    _write(path, oracle)
    with pytest.raises(ExpansionArchiveError, match="rejected check carries preparation or verification evidence"):
        _verify(tmp_path)


def _refresh(root, broker):
    _refresh_bound_rejection_receipts(root, broker)
    current = json.loads((root / "expansion-broker.json").read_text())
    version = json.loads((root / "expansion-plan.json").read_text())["version"]
    for row in current["records"]:
        if row["accepted"]:
            argv = row["gateway_arguments"]
            semantic = ["runner-owned-version", version, *argv]
            if "--expected-revision" in argv:
                semantic[2 + argv.index("--expected-revision") + 1] = int(argv[argv.index("--expected-revision") + 1])
            row["semantic_argv_sha256"] = canonical_digest(semantic)
    _write(root / "expansion-broker.json", current)


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
@pytest.mark.parametrize("damage", ["foreign_draft", "revision", "unchanged_authority", "other_rejection", "malformed_cli",
    "runner", "payload", "unauthenticated", "raw_hash", "later_dispatch", "missing_receipt", "duplicate_prefix",
    "prefix_authority", "prefix_handle", "projection", "check_projection"])
def test_rejected_check_requires_exact_authenticated_terminal_prefix(tmp_path, version, damage):
    _fixture(tmp_path, version)
    broker = json.loads((tmp_path / "expansion-broker.json").read_text())
    last = broker["records"][-1]
    argv = last["gateway_arguments"]
    if damage == "foreign_draft": argv[1] = "od1-" + "a" * 32
    elif damage == "revision": argv[-1] = "2"
    elif damage == "unchanged_authority": argv[3] = broker["records"][0]["payload"]["task_authority"]
    elif damage == "other_rejection":
        last["rejection"] = "expansion policy rejected command: bound object is outside the approved fixture"
        last["stderr"] = "Gateway broker rejected command: " + last["rejection"] + "\n"
    elif damage == "malformed_cli": argv += ["--unknown", "value"]
    elif damage == "runner": last["runner_exit_code"] = 0
    elif damage == "payload": last["payload"] = {"ok": False}
    elif damage == "unauthenticated": last["authenticated"] = False
    elif damage == "later_dispatch":
        broker["records"].append(copy.deepcopy(broker["records"][0]))
        broker["records"][-1]["sequence"] = 5
    elif damage == "missing_receipt": broker["records"].pop()
    elif damage == "duplicate_prefix":
        broker["records"].insert(2, copy.deepcopy(broker["records"][1]))
        for index, row in enumerate(broker["records"], 1): row["sequence"] = index
    elif damage == "prefix_authority":
        broker["records"][0]["payload"]["task_authority"] = "da1-" + "a" * 40
        for row in broker["records"][1:-1]: row["gateway_arguments"][3] = "da1-" + "a" * 40
    elif damage == "prefix_handle": broker["records"][1]["payload"]["bound_object"]["handle"] = "boh1-" + "a" * 32
    elif damage == "projection": broker["records"][2]["payload"]["draft"]["batch_receipt"]["chunk_declaration_count"] = 2
    elif damage == "check_projection": broker["records"][2]["payload"]["draft"]["check"] = {"state": "checked"}
    _refresh(tmp_path, broker)  # Rebind stdout, payload, argv, raw facts and hashes.
    if damage == "raw_hash":
        broker = json.loads((tmp_path / "expansion-broker.json").read_text())
        broker["records"][-1]["raw_argv_sha256"] = "0" * 64
        _write(tmp_path / "expansion-broker.json", broker)
    with pytest.raises(ExpansionArchiveError): _verify(tmp_path)


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
@pytest.mark.parametrize("damage", ["field", "order", "extra_row", "settings", "handle", "parent_name", "parent_type",
    "schema", "composer", "authority", "audit", "project_context", "project_evidence", "missing_project_evidence",
    "missing_state", "extra_state", "transaction", "media_path"])
def test_rejected_check_rejects_fully_resealed_state_or_scope_drift(tmp_path, version, damage):
    _fixture(tmp_path, version)
    path = next((tmp_path / "broker/state/operation-drafts-v1/records").glob("*.json"))
    stored = json.loads(path.read_text())
    raw = stored["composition"]["business_session"]
    if damage == "field": raw["declarations"][1]["fields"]["volume_db"] = -3
    elif damage == "order": raw["declarations"][1:] = raw["declarations"][1:][::-1]
    elif damage == "extra_row":
        session = BusinessDeclarationSession.from_dict(raw)
        parent = session.declarations[0].result_handle
        stored["composition"]["business_session"] = session.with_new_declaration(declaration_id="extra",
            target=NewDescendantTarget(parent, "Extra", "music-track"), fields={}).as_dict()
    elif damage == "settings": raw["settings"] = {"defaults": {"volume_db": -3}}
    elif damage == "handle": raw["handles"]["objects"][0]["handle"] = "boh1-" + "a" * 32
    elif damage in {"parent_name", "parent_type"}:
        obj = raw["handles"]["objects"][0]
        context = BusinessContext.from_binding_dict(raw["context"])
        registry = BusinessHandleRegistry(context)
        registry.bind_object(object_id=obj["object_id"], name="Other" if damage == "parent_name" else obj["name"],
            object_type="Sound" if damage == "parent_type" else obj["object_type"], path=obj["path"], semantic_kind=None)
        fresh = registry.as_dict()["objects"][0]
        fresh["handle"] = obj["handle"]  # Valid binding digest, unchanged opaque token.
        raw["handles"]["objects"][0] = fresh
    elif damage == "schema": stored["schema_digest"] = "b" * 64
    elif damage == "composer": stored["composer_digest"] = "b" * 64
    elif damage == "authority": stored["authority_digest"] = "b" * 64
    elif damage == "audit":
        stored["audit"][-1]["event_type"] = "declaration.revised"
        prior = ""
        for event in stored["audit"]:
            event["previous_event_hash"] = prior
            event.pop("event_hash")
            event["event_hash"] = canonical_digest(event)
            prior = event["event_hash"]
    elif damage == "project_context":
        raw["context"]["project_path"] = raw["handles"]["context"]["project_path"] = "/foreign/SampleProject.wproj"
        # Recompute a valid registry binding against the changed context.
        obj = raw["handles"]["objects"][0]
        registry = BusinessHandleRegistry(BusinessContext.from_binding_dict(raw["context"]))
        registry.bind_object(object_id=obj["object_id"], name=obj["name"], object_type=obj["object_type"], path=obj["path"], semantic_kind=None)
        obj["binding_digest"] = registry.as_dict()["objects"][0]["binding_digest"]
    elif damage == "project_evidence":
        evidence = tmp_path / "broker/evidence/fixture-project.json"
        payload = json.loads(evidence.read_text()); payload["result"]["id"] = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
        _write(evidence, payload)
    elif damage == "missing_project_evidence": (tmp_path / "broker/evidence/fixture-project.json").unlink()
    elif damage == "missing_state": path.unlink()
    elif damage == "extra_state":
        OperationDraftStore(tmp_path / "broker/state").start(operation="audio.import", version=version,
            schema_digest=stored["schema_digest"], composer_digest=stored["composer_digest"])
    elif damage == "transaction": (tmp_path / "broker/state/transactions").mkdir()
    elif damage == "media_path": raw["declarations"][1]["fields"]["media_file"] = str(tmp_path / "foreign.wav")
    if damage != "missing_state":
        stored["record_digest"] = _record_digest(stored)
        _write(path, stored)
    with pytest.raises(ExpansionArchiveError): _verify(tmp_path)


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
@pytest.mark.parametrize("damage", ["row_order", "extra_field", "media_scope", "parent_handle"])
def test_resealed_declaration_argv_cannot_change_stored_facts_or_owned_scope(tmp_path, version, damage):
    _fixture(tmp_path, version)
    broker = json.loads((tmp_path / "expansion-broker.json").read_text())
    argv = broker["records"][2]["gateway_arguments"]
    if damage == "row_order":
        position = argv.index("--row-order")
        argv[position + 2:position + 4] = argv[position + 2:position + 4][::-1]
    elif damage == "extra_field": argv += ["--field", "full", "volume_db", "-12"]
    elif damage == "media_scope": argv[argv.index("--media-directory") + 1] = str(tmp_path / "foreign")
    else: argv[argv.index("--new-row") + 2] = "boh1-" + "a" * 32
    _refresh(tmp_path, broker)
    with pytest.raises(ExpansionArchiveError): _verify(tmp_path)


@pytest.mark.parametrize("fault", [None, "source", "mtime", "close", "reconciliation", "status"])
def test_ordinary_failed_check_continues_only_with_existing_isolation_guards(tmp_path, fault):
    from tests.semantic import run_codex_skill_matrix as matrix
    _fixture(tmp_path)
    record = {"scenario_id": "EXP25-M01", "version": "2025.1", "scenario_root": str(tmp_path), "status": "FAIL",
        "runner_outcome": {"task_root": str(tmp_path), "inputs_sha256": INPUTS, "checks": {"trusted_oracle_closed": True},
            "lifecycle": {"scenario_id": "EXP25-M01", "version": "2025.1", "source_hash_before": {"digest": INPUTS},
                "source_hash_after": {"digest": INPUTS}, "source_mtime_before_ns": 1, "source_mtime_after_ns": 1,
                "errors": ["scenario: expected Agent failure"]}}}
    if fault == "source": record["runner_outcome"]["lifecycle"]["source_hash_after"]["digest"] = "b" * 64
    elif fault == "mtime": record["runner_outcome"]["lifecycle"]["source_mtime_after_ns"] = 2
    elif fault == "close": record["runner_outcome"]["checks"]["trusted_oracle_closed"] = False
    elif fault == "status": record["status"] = "PASS"
    elif fault == "reconciliation":
        path = tmp_path / "expansion-oracle.json"
        oracle = json.loads(path.read_text()); oracle["reconciliation"]["child_reaped"] = False
        _write(path, oracle)
    assert matrix.expansion_case_isolated(record) is (fault is None)
