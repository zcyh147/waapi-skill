"""Controlled original-batch producer checks; no product/native credit."""
from copy import deepcopy
import hashlib
from pathlib import Path
import json

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance.branch_audit_completion import evidence_result, installed_obligations
from tests.support import condition_branch_evidence, condition_scalar_batch
from tests.support import condition_scalar_program as producer
from tests.unit.test_scalar_condition_product_gateway import run_scalar_public_workflow


@pytest.fixture(scope="module")
def source_inputs():
    root = Path(__file__).parents[2]
    plan = condition_scalar_batch.scalar_plan(condition_scalar_batch.scalar_manifest(root))
    group = next(g for g in plan["groups"] if g["version"] == "2025.1" and g["field"] == "GainBand1")
    owned = installed_obligations(root, digest=audit.digest, load=audit.load)
    ids = {m["id"] for m in group["members"]} | {condition_branch_evidence.SHOW_BRANCH_ID}
    branches = {b["id"]: b for b in owned if b["id"] in ids}
    inventory = {"native_coverage": {"candidate_sha256": "c" * 64, "obligations": list(branches.values())},
                 "routes": [{"id": "2025.1|function|ak.wwise.core.object.setProperty"}]}
    return {**plan, "groups": [group]}, inventory, branches


def test_original_batch_has_explicit_per_id_observations_without_product_credit(tmp_path, request, source_inputs):
    plan, inventory, branches = deepcopy(source_inputs)
    capture = producer.prepare_program_batch(tmp_path / "capture", [request.node.nodeid], plan, inventory,
                                             scope_kind="controlled")
    group = plan["groups"][0]
    observation = run_scalar_public_workflow(tmp_path / "workflow", group)
    producer.finish_program_node(capture, request.node.nodeid,
        {"setup": "passed", "call": "passed", "teardown": "passed"}, {group["id"]: observation})
    published = capture["root"] / "published"
    bindings = json.loads((published / "bindings.json").read_text())["bindings"]
    assert set(bindings) == {m["id"] for m in group["members"]}
    assert not (published / "requirements.json").exists()
    for identity, binding in bindings.items():
        status, reason = evidence_result(binding["evidence"]["program"], branches[identity], "c" * 64,
            "program", "controlled", published, binding)
        assert (status, reason) == ("passed", None)
        status, reason = evidence_result(binding["evidence"]["program"], branches[identity], "c" * 64,
            "program", "product", published, binding)
        assert status == "missing" and "controlled evidence" in reason


@pytest.mark.parametrize("damage", ["wrong-node", "missing-field", "extra-field", "metadata-value", "controller",
                                   "changed-field", "typed-field", "wrong-write", "unverified", "changed-plan", "changed-source"])
def test_original_batch_refuses_incomplete_or_changed_member_proof(tmp_path, request, source_inputs, damage):
    plan, inventory, _ = deepcopy(source_inputs)
    capture = producer.prepare_program_batch(tmp_path / "capture", [request.node.nodeid], plan, inventory, scope_kind="controlled")
    group = plan["groups"][0]
    observed = run_scalar_public_workflow(tmp_path / "workflow", group)
    observations = {group["id"]: observed}
    node = request.node.nodeid
    if damage == "wrong-node": node = "unexecuted-node"
    if damage == "missing-field": observations.clear()
    if damage == "extra-field": observations["not-predeclared"] = deepcopy(observed)
    if damage == "metadata-value": observed["observations"]["metadata"]["dependencies"][0]["conditions"][0]["restriction"]["values"][0]["value"] = 1
    if damage == "controller": observed["observations"]["before"]["OnOffBand1"] = False
    if damage == "changed-field": observed["observations"]["after"]["GainBand1"] = 999
    if damage == "typed-field": observed["observations"]["after"]["GainBand1"] = int(group["model"]["requested"])
    if damage == "wrong-write": observed["native_call"]["args"]["property"] = "OtherField"
    if damage == "unverified": observed["gateway"]["payload"]["verified"] = False
    if damage == "changed-plan": capture["plan"]["credit"] = "invented-credit"
    if damage == "changed-source": capture["relevant_sources"][next(iter(capture["relevant_sources"]))] = "0" * 64
    with pytest.raises((ValueError, AssertionError)):
        producer.finish_program_node(capture, node, {"setup": "passed", "call": "passed", "teardown": "passed"}, observations)
    assert not (capture["root"] / "published").exists()


@pytest.mark.parametrize("reports", [{"setup": "passed", "call": "passed"},
    {"setup": "passed", "call": "passed", "teardown": "failed"}])
def test_late_or_missing_reports_withhold_the_whole_original_batch(tmp_path, request, source_inputs, reports):
    plan, inventory, _ = deepcopy(source_inputs)
    capture = producer.prepare_program_batch(tmp_path / "capture", [request.node.nodeid], plan, inventory, scope_kind="controlled")
    group = plan["groups"][0]
    observed = run_scalar_public_workflow(tmp_path / "workflow", group)
    producer.finish_program_node(capture, request.node.nodeid, reports, {group["id"]: observed})
    assert not (capture["root"] / "published").exists()
    assert json.loads((capture["root"] / "outcome.json").read_text())["outcome"] == "FAIL"
    assert list(capture["root"].glob("observations-*.json"))


@pytest.mark.parametrize("phase", ["directory", "final-seal"])
def test_unpublished_staged_program_cannot_bypass_final_publication_failure(tmp_path, request, source_inputs, monkeypatch, phase):
    plan, inventory, branches = deepcopy(source_inputs)
    capture = producer.prepare_program_batch(tmp_path / "capture", [request.node.nodeid], plan, inventory, scope_kind="controlled")
    group = plan["groups"][0]
    observed = run_scalar_public_workflow(tmp_path / "workflow", group)
    original_rename = Path.rename
    def fail_publication(source, target):
        if (phase == "directory" and source.name.startswith(".program-pending-")) or (phase == "final-seal" and source.name == ".batch-final.pending"):
            raise OSError("original publication failed")
        return original_rename(source, target)
    monkeypatch.setattr(Path, "rename", fail_publication)
    with pytest.raises(OSError, match="original publication failed"):
        producer.finish_program_node(capture, request.node.nodeid,
            {"setup": "passed", "call": "passed", "teardown": "passed"}, {group["id"]: observed})
    assert (capture["root"] / "published").exists() is (phase == "final-seal")
    assert not (capture["root"] / "batch-final.json").exists()
    staged = capture["root"] / "published" if phase == "final-seal" else next(capture["root"].glob(".program-pending-*"))
    bindings = json.loads((staged / "bindings.json").read_text())["bindings"]
    identity, binding = next(iter(bindings.items()))
    original = staged / Path(binding["evidence"]["program"]["artifact"]).name
    descriptor = {**binding["evidence"]["program"], "artifact": str(original),
                  "sha256": hashlib.sha256(original.read_bytes()).hexdigest()}
    status, reason = evidence_result(descriptor, branches[identity], "c" * 64, "program", "controlled", staged, binding)
    assert status == "missing" and "batch-final.json" in reason


def test_source_model_batch_cannot_emit_product_evidence_before_native_linkage_review(tmp_path, source_inputs):
    plan, inventory, _ = deepcopy(source_inputs)
    node = "tests/unit/test_scalar_condition_product_gateway.py::test_product_self_scalar_source_conditions[2025.1]"
    with pytest.raises(ValueError, match="reviewed native-effect linkage"):
        producer.prepare_program_batch(tmp_path / "capture", [node], plan, inventory, scope_kind="product")
    assert not (tmp_path / "capture").exists()


def test_no_batch_receipt_is_published_before_all_selected_nodes_report(tmp_path, request, source_inputs):
    plan, inventory, _ = deepcopy(source_inputs)
    last_node = request.node.nodeid + "-last-node-control"
    capture = producer.prepare_program_batch(tmp_path / "capture", [request.node.nodeid, last_node], plan, inventory, scope_kind="controlled")
    group = plan["groups"][0]
    observed = run_scalar_public_workflow(tmp_path / "workflow", group)
    reports = {"setup": "passed", "call": "passed", "teardown": "passed"}
    producer.finish_program_node(capture, request.node.nodeid, reports, {group["id"]: observed})
    assert not (capture["root"] / "published").exists()
    producer.finish_program_node(capture, last_node, {**reports, "teardown": "failed"}, {})
    assert not (capture["root"] / "batch-final.json").exists()
    assert not (capture["root"] / "published").exists()
