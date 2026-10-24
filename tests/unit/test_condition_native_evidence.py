"""Controlled producer checks; these injected records grant no native credit."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from tests.destructive.support import category_evidence, exact_real_evidence
from tests.maintenance.branch_audit_completion import read_category_run
from tests.support import condition_branch_evidence as producer


NODE = "tests/destructive/test_condition_visibility_gateway.py::test_show_visibility_does_not_change_native_prerequisite[Self]"


def inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(category_evidence, "current_evidence_platform", lambda: "macos")
    monkeypatch.setenv("WWISE_CATEGORY_EVIDENCE_PATH", str(tmp_path / "category.jsonl"))
    source = "tests/support/condition_branch_evidence.py"
    candidate = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=producer.audit.ROOT, text=True).strip()
    capture = {"root": tmp_path / "published", "nodeid": NODE, "scope_kind": "controlled",
               "branch": {"id": "unit-control-only", "shape_sha256": "b" * 64, "route": None,
                          "version": "2025.1", "build": "2025.1.7.9143"},
               "case": deepcopy(producer._PROGRAM_CASES["slew-rate-show"]),
               "relation": "Self", "candidate_sha256": "c" * 64, "git_candidate": candidate,
               "relevant_sources": {source: hashlib.sha256((producer.audit.ROOT / source).read_bytes()).hexdigest()}}
    metadata = {"name": "SlewRateUp", "type": "Real64", "dependencies": [{"type": "property", "context": "Self",
        "action": "Show", "property": "RTPCRamping", "conditions": [{"enum": [{"value": 1}]}]}]}
    host = {"isCommandLine": True, "version": {"year": 2025, "major": 1, "minor": 7, "build": 9143}}
    observations = []
    for mode in (0, 1):
        controller = {"id": "owned", "RTPCRamping": mode}
        observations.append({"mode": mode, "requested_value": 37 + mode,
            "before": {"id": "owned", "SlewRateUp": 0.0}, "after": {"id": "owned", "SlewRateUp": 37.0 + mode},
            "controller_before": controller, "controller_after": deepcopy(controller),
            "is_property_enabled": {"return": True}, "metadata_before": deepcopy(metadata), "metadata_after": deepcopy(metadata)})
    observed = {"candidate": candidate, "host": host, "version": "2025.1", "relation": "Self", "field": "SlewRateUp",
                "prerequisite": "RTPCRamping", "metadata": metadata, "observations": observations}
    observation = tmp_path / "original-observation.json"
    observation.write_text(json.dumps(observed))
    lifecycle = {"contract": "waapi-skill.codex-semantic-scenario-lifecycle/v3", "final_status": "PASS",
                 "sandbox_retained": False, "errors": [], "source_hash_before": {"digest": "same", "strategy": "full"},
                 "source_hash_after": {"digest": "same", "strategy": "full"},
                 "source_mtime_before_ns": 10, "source_mtime_after_ns": 10}
    kwargs = dict(repo_root=producer.audit.ROOT, candidate=candidate, version="2025.1", nodeid=NODE,
                  phase_reports={"setup": "passed", "call": "passed", "teardown": "passed"}, started_at_unix_ns=1,
                  lifecycle=lifecycle, sandbox=SimpleNamespace(sandbox_path=tmp_path / "deleted", metadata=SimpleNamespace(
                      process_cleanup_result="cleaned", process_cleanup_details={"residual_processes": []})),
                  host=host, observation_path=observation, transactions=[])
    kwargs["original_publisher"] = lambda record: producer.publish_condition_native_capture(capture, record, observation)
    return capture, kwargs, observed


def test_original_native_wrapper_links_final_category_and_preserves_real64_readback(tmp_path, monkeypatch):
    capture, kwargs, _ = inputs(tmp_path, monkeypatch)
    exact_real_evidence.append_finalized_scenario_evidence(**kwargs)
    root = capture["root"]
    record = json.loads((root / "native.json").read_text())
    assert record["scope_kind"] == "controlled"
    assert record["evidence_kind"] == "native_execution"
    assert record["git_candidate"] == capture["git_candidate"]
    context = read_category_run(record["native_runs"][0], tmp_path)
    assert context["build"] == "2025.1.7.9143"
    assert record["native_runs"][0]["observation_sha256"] == [record["observation_artifacts"]["wwise-console"]["sha256"]]
    checks = record["branch_assertions"]["unit-control-only"]["checks"]
    check = next(row for row in checks if row["pointer"] == "/observations/wwise-console/observations/0/after/SlewRateUp")
    assert type(check["equals"]) is float and check["equals"] == 37.0
    link = json.loads((root / "native-link.json").read_text())
    assert link["native_equivalence"] == {}
    assert link["native_observations_sha256"] == {"wwise-console": record["observation_artifacts"]["wwise-console"]["sha256"]}
    assert json.loads((root / "sources.json").read_text())["relevant_sources"] == capture["relevant_sources"]


@pytest.mark.parametrize("damage", ["missing-report", "teardown-error", "wrong-node", "wrong-field", "missing-field", "wrong-build", "wrong-candidate", "changed-source", "wrong-value", "controller-write"])
def test_native_wrapper_is_not_published_for_incomplete_or_mismatched_original_provenance(tmp_path, monkeypatch, damage):
    capture, kwargs, observed = inputs(tmp_path, monkeypatch)
    if damage == "missing-report": kwargs["phase_reports"].pop("teardown")
    if damage == "teardown-error": kwargs["phase_reports"]["teardown"] = "failed"
    if damage == "wrong-node": capture["nodeid"] = "other-node"
    if damage == "wrong-field": observed["field"] = "Weight"
    if damage == "missing-field": observed["observations"][0]["after"].pop("SlewRateUp")
    if damage == "wrong-build": capture["branch"]["build"] = "2025.1.0.1"
    if damage == "wrong-candidate": observed["candidate"] = "d" * 40
    if damage == "changed-source": capture["relevant_sources"] = {next(iter(capture["relevant_sources"])): "e" * 64}
    if damage == "wrong-value": observed["observations"][0]["after"]["SlewRateUp"] = 99.0
    if damage == "controller-write": observed["observations"][0]["controller_after"]["RTPCRamping"] = 1
    kwargs["observation_path"].write_text(json.dumps(observed))
    if damage == "teardown-error":
        exact_real_evidence.append_finalized_scenario_evidence(**kwargs)
        assert json.loads((tmp_path / "category.jsonl").read_text())["invocation"]["outcome"] == "FAIL"
    else:
        with pytest.raises((AssertionError, ValueError, KeyError)):
            exact_real_evidence.append_finalized_scenario_evidence(**kwargs)
    assert not capture["root"].exists()


def test_native_publication_failure_fails_teardown_without_publishing_pass(tmp_path, monkeypatch):
    from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer, finalize_reported_node_evidence
    capture, kwargs, _ = inputs(tmp_path, monkeypatch)
    def reject_publication(_pending, _target):
        raise OSError("atomic original evidence publication failed")
    monkeypatch.setattr(Path, "rename", reject_publication)
    item = SimpleNamespace(_waapi_phase_reports=kwargs["phase_reports"])
    register_exact_evidence_finalizer(item, lambda reports: exact_real_evidence.append_finalized_scenario_evidence(
        **{**kwargs, "phase_reports": reports}))
    report = SimpleNamespace(when="teardown", outcome="passed")
    finalize_reported_node_evidence(item, report)
    assert report.outcome == "failed" and "atomic original evidence" in report.longrepr
    assert not capture["root"].exists()
    assert not (tmp_path / "category.jsonl").exists()
    assert list(tmp_path.glob(".published-pending-*/category.json"))  # retained, unpublished stage


def test_native_link_does_not_claim_missing_reviewed_source_equivalence(tmp_path, monkeypatch):
    from tests.maintenance.branch_audit_completion import evidence_result
    capture, kwargs, _ = inputs(tmp_path, monkeypatch)
    exact_real_evidence.append_finalized_scenario_evidence(**kwargs)
    link = json.loads((capture["root"] / "native-link.json").read_text())
    # Controlled scope checks the same strict reader; no proof or product credit.
    status, reason = evidence_result(link["evidence"]["native"],
        {**capture["branch"], "pointer": "/condition", "kind": "condition", "approved_boundary": None},
        capture["candidate_sha256"], "native", "controlled", tmp_path, link)
    assert status == "missing" and reason == "'artifact'"  # missing reviewed equivalence descriptor


def test_native_producer_keeps_the_actual_enabled_fact_and_never_overwrites_original_output(tmp_path, monkeypatch):
    capture, kwargs, observed = inputs(tmp_path, monkeypatch)
    observed["observations"][0]["is_property_enabled"]["return"] = False
    kwargs["observation_path"].write_text(json.dumps(observed))
    exact_real_evidence.append_finalized_scenario_evidence(**kwargs)
    original = (capture["root"] / "native.json").read_bytes()
    checks = json.loads(original)["branch_assertions"]["unit-control-only"]["checks"]
    assert next(row["equals"] for row in checks if row["pointer"].endswith("/0/is_property_enabled")) == {"return": False}
    with pytest.raises(ValueError, match="immutable"):
        exact_real_evidence.append_finalized_scenario_evidence(**kwargs)
    assert (capture["root"] / "native.json").read_bytes() == original
