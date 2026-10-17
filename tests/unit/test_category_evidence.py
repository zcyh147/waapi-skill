from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.destructive.support import category_evidence
from tests.destructive.support import exact_real_evidence


@pytest.mark.parametrize("damage", [None, "hash", "mtime", "retained", "residual", "cleanup", "unreported", "unreported-teardown", "teardown-error"])
def test_finalized_scenario_produces_original_category_v3_with_exact_node_and_observation(tmp_path, monkeypatch, damage):
    from types import SimpleNamespace
    from tests.maintenance.branch_audit_completion import read_category_run
    import hashlib

    target = tmp_path / "category.jsonl"
    monkeypatch.setenv("WWISE_CATEGORY_EVIDENCE_PATH", str(target))
    monkeypatch.setattr(category_evidence, "current_evidence_platform", lambda: "macos")
    observation = tmp_path / "condition-visibility.json"
    observation.write_text(json.dumps({"observations": [{"after": {"SlewRateUp": 37}}]}))
    lifecycle = {"contract": "waapi-skill.codex-semantic-scenario-lifecycle/v3", "final_status": "PASS",
                 "sandbox_retained": False, "errors": [], "quarantine_path": None,
                 "source_hash_before": {"digest": "same", "strategy": "full"},
                 "source_hash_after": {"digest": "same", "strategy": "full"},
                 "source_mtime_before_ns": 10, "source_mtime_after_ns": 10}
    metadata = SimpleNamespace(process_cleanup_result="cleaned", process_cleanup_details={"residual_processes": []})
    reports = {"setup": "passed", "call": "passed", "teardown": "passed"}
    if damage == "hash":
        lifecycle["source_hash_after"]["digest"] = "changed"
    if damage == "mtime":
        lifecycle["source_mtime_after_ns"] = 11
    if damage == "retained":
        lifecycle["sandbox_retained"] = True
    if damage == "residual":
        metadata.process_cleanup_details["residual_processes"] = [123]
    if damage == "cleanup":
        metadata.process_cleanup_result = "unknown"
    if damage == "unreported":
        reports.pop("call")
    if damage == "unreported-teardown":
        reports.pop("teardown")
    if damage == "teardown-error":
        reports["teardown"] = "failed"
    kwargs = {"repo_root": tmp_path, "candidate": "a" * 40, "version": "2025.1",
              "nodeid": "tests/destructive/test_condition_visibility_gateway.py::test_show_visibility_does_not_change_native_prerequisite[Self]",
              "phase_reports": reports, "started_at_unix_ns": 1, "lifecycle": lifecycle,
              "sandbox": SimpleNamespace(sandbox_path=tmp_path / "deleted-sandbox", metadata=metadata),
              "host": {"displayName": "Wwise", "isCommandLine": True,
                       "version": {"year": 2025, "major": 1, "minor": 7, "build": 9143}},
              "observation_path": observation, "transactions": []}
    if damage not in {None, "teardown-error"}:
        with pytest.raises(AssertionError):
            exact_real_evidence.append_finalized_scenario_evidence(**kwargs)
        assert not target.exists()
        return
    exact_real_evidence.append_finalized_scenario_evidence(**kwargs)
    record = json.loads(target.read_text())
    descriptor = {"artifact": str(target), "record_index": 0, "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                  "nodeid": kwargs["nodeid"]}
    if damage == "teardown-error":
        assert record["invocation"]["outcome"] == "FAIL"
        with pytest.raises(ValueError, match="PASS"):
            read_category_run(descriptor, tmp_path)
        return
    context = read_category_run(descriptor, tmp_path)
    assert context["build"] == "2025.1.7.9143"
    assert record["invocation"]["node_outcomes"] == [{"nodeid": kwargs["nodeid"], "outcome": "PASS"}]
    assert record["categories"][0]["observation"] == {
        "artifact": str(observation), "sha256": hashlib.sha256(observation.read_bytes()).hexdigest(),
    }


@pytest.mark.parametrize("reports", [
    {"setup": "passed", "call": "passed"},
    {"setup": "passed", "call": "passed", "teardown": "failed"},
    {"setup": "passed", "call": "failed", "teardown": "passed"},
])
def test_program_condition_finalization_cannot_pass_missing_or_failed_teardown(tmp_path, reports):
    from tests.support.condition_branch_evidence import finish_condition_capture
    import subprocess
    root = Path(__file__).parents[2]
    capture = {"root": tmp_path, "branch": {"id": "unit-control-only", "pointer": "/condition", "shape_sha256": "b" * 64},
               "public": {"id": "unit-control-only"}, "candidate_sha256": "c" * 64,
               "git_candidate": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
               "relevant_sources": {}, "nodeid": "unit-control-only"}
    finish_condition_capture(capture, reports, {})
    assert json.loads((tmp_path / "program.json").read_text())["invocation"]["outcome"] == "FAIL"


def test_exact_evidence_callback_waits_for_teardown_and_sees_its_failure():
    from types import SimpleNamespace
    from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer, finalize_reported_node_evidence
    item = SimpleNamespace(_waapi_phase_reports={"setup": "passed", "call": "passed"})
    observed = []
    register_exact_evidence_finalizer(item, observed.append)
    finalize_reported_node_evidence(item, SimpleNamespace(when="call", outcome="passed"))
    assert observed == []
    item._waapi_phase_reports["teardown"] = "failed"
    finalize_reported_node_evidence(item, SimpleNamespace(when="teardown", outcome="failed"))
    assert observed == [{"setup": "passed", "call": "passed", "teardown": "failed"}]
    finalize_reported_node_evidence(item, SimpleNamespace(when="teardown", outcome="failed"))
    assert len(observed) == 1


def test_exact_evidence_callback_failure_fails_the_report_and_multiple_producers_are_rejected():
    from types import SimpleNamespace
    from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer, finalize_reported_node_evidence
    item = SimpleNamespace(_waapi_phase_reports={"setup": "passed", "call": "passed", "teardown": "passed"})
    def failed(_reports):
        raise OSError("seal could not be published")
    register_exact_evidence_finalizer(item, failed)
    with pytest.raises(AssertionError, match="one exact"):
        register_exact_evidence_finalizer(item, failed)
    report = SimpleNamespace(when="teardown", outcome="passed")
    finalize_reported_node_evidence(item, report)
    assert report.outcome == item._waapi_phase_reports["teardown"] == "failed"
    assert "seal could not be published" in report.longrepr


def _append(tmp_path: Path, *, candidate: str = "a" * 40) -> None:
    category_evidence.append_category_evidence(
        repo_root=tmp_path,
        candidate=candidate,
        version="2025.1",
        host={"display_name": "WwiseConsole", "version": "2025.1.7.9143"},
        categories=[
            {
                "category": "object-topology",
                "status": "PASS",
                "verifier_strength": "operation_specific_readback",
            }
        ],
        source={"hash_before": "same", "hash_after": "same"},
        residual_state={"sandbox": "deleted", "residual_processes": []},
    )


@pytest.mark.parametrize(
    ("platform_name", "filename"),
    (("macos", "macos-category-evidence.jsonl"), ("windows", "windows-category-evidence.jsonl")),
)
def test_category_evidence_uses_exact_host_platform_contract_and_default_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform_name: str,
    filename: str,
) -> None:
    monkeypatch.delenv("WWISE_CATEGORY_EVIDENCE_PATH", raising=False)
    monkeypatch.delenv("WWISE_MACOS_CATEGORY_EVIDENCE_PATH", raising=False)
    monkeypatch.setattr(category_evidence, "current_evidence_platform", lambda: platform_name)

    _append(tmp_path)

    target = tmp_path / ".waapi-skill-state" / "evidence" / "full-typed-input" / filename
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["contract"] == "waapi-skill.host-category-evidence/v1"
    assert payload["platform"] == platform_name
    assert payload["candidate"] == "a" * 40


def test_category_evidence_generic_override_is_platform_neutral(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "custom" / "windows-evidence.jsonl"
    monkeypatch.setenv("WWISE_CATEGORY_EVIDENCE_PATH", str(target))
    monkeypatch.setenv("WWISE_MACOS_CATEGORY_EVIDENCE_PATH", str(tmp_path / "must-not-win.jsonl"))
    monkeypatch.setattr(category_evidence, "current_evidence_platform", lambda: "windows")

    _append(tmp_path)

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["platform"] == "windows"
    assert not (tmp_path / "must-not-win.jsonl").exists()


def test_legacy_macos_override_does_not_capture_windows_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_target = tmp_path / "legacy-macos.jsonl"
    monkeypatch.delenv("WWISE_CATEGORY_EVIDENCE_PATH", raising=False)
    monkeypatch.setenv("WWISE_MACOS_CATEGORY_EVIDENCE_PATH", str(legacy_target))
    monkeypatch.setattr(category_evidence, "current_evidence_platform", lambda: "windows")

    _append(tmp_path)

    windows_target = (
        tmp_path
        / ".waapi-skill-state"
        / "evidence"
        / "full-typed-input"
        / "windows-category-evidence.jsonl"
    )
    assert windows_target.exists()
    assert not legacy_target.exists()


def test_exact_evidence_v2_preserves_invocation_and_transaction_outcomes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "exact.jsonl"
    monkeypatch.setenv("WWISE_CATEGORY_EVIDENCE_PATH", str(target))
    monkeypatch.setattr(category_evidence, "current_evidence_platform", lambda: "macos")

    category_evidence.append_category_evidence(
        repo_root=tmp_path,
        candidate="b" * 40,
        version="2022.1",
        host={"display_name": "WwiseConsole", "version": "2022.1.19.8584"},
        categories=[
            {
                "category": "object-topology",
                "status": "PASS",
                "verifier_strength": "operation_specific_readback",
            }
        ],
        source={"mtime_before_ns": 10, "mtime_after_ns": 10},
        residual_state={"sandbox": "deleted", "quarantine_path": None},
        invocation={
            "selected_test_nodeids": ["tests/destructive/test_example.py::test_one"],
            "started_at_unix_ns": 100,
            "finished_at_unix_ns": 200,
            "outcome": "PASS",
        },
        transactions=[
            {
                "transaction_id": "tx1-0123456789abcdefghjk",
                "state": "verified",
                "artifact_hash": "c" * 64,
                "event_sequence": 5,
            }
        ],
    )

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["contract"] == "waapi-skill.host-category-evidence/v2"
    assert payload["invocation"]["outcome"] == "PASS"
    assert payload["transactions"] == [
        {
            "artifact_hash": "c" * 64,
            "event_sequence": 5,
            "state": "verified",
            "transaction_id": "tx1-0123456789abcdefghjk",
        }
    ]


def test_exact_evidence_rejects_partial_v2_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(category_evidence, "current_evidence_platform", lambda: "macos")
    with pytest.raises(AssertionError, match="invocation and transactions together"):
        category_evidence.append_category_evidence(
            repo_root=tmp_path,
            candidate="a" * 40,
            version="2025.1",
            host={"display_name": "WwiseConsole"},
            categories=[
                {
                    "category": "object-topology",
                    "status": "PASS",
                    "verifier_strength": "operation_specific_readback",
                }
            ],
            source={},
            residual_state={},
            invocation={"outcome": "PASS"},
        )


def test_exact_transaction_outcomes_reads_all_materialized_states(
    tmp_path: Path,
) -> None:
    from wwise_waapi.transactions import TransactionStore

    store = TransactionStore(tmp_path)
    first = store.create_preview("first", {"operation": "one"})
    second = store.create_preview("second", {"operation": "two"})

    outcomes = category_evidence.exact_transaction_outcomes(tmp_path)

    assert outcomes == [
        {
            "transaction_id": "first",
            "state": "draft",
            "artifact_hash": first.artifact_hash,
            "event_sequence": 1,
        },
        {
            "transaction_id": "second",
            "state": "draft",
            "artifact_hash": second.artifact_hash,
            "event_sequence": 1,
        },
    ]


def test_exact_evidence_v3_preserves_prepared_phase_without_pass_credit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "prepared.jsonl"
    monkeypatch.setenv("WWISE_CATEGORY_EVIDENCE_PATH", str(target))
    monkeypatch.setattr(category_evidence, "current_evidence_platform", lambda: "macos")
    nodeid = "tests/destructive/test_example.py::test_one"

    category_evidence.append_category_evidence(
        repo_root=tmp_path,
        candidate="d" * 40,
        version="2025.1",
        host={"display_name": "WwiseConsole"},
        categories=[
            {
                "category": "object-topology",
                "status": "PASS",
                "verifier_strength": "readback",
            }
        ],
        source={},
        residual_state={
            "sandbox": "quarantined_pending_release",
            "quarantine_path": "/tmp/quarantine",
        },
        invocation={
            "selected_test_nodeids": [nodeid],
            "node_outcomes": [{"nodeid": nodeid, "outcome": "PASS"}],
            "started_at_unix_ns": 1,
            "finished_at_unix_ns": 2,
            "phase": "prepared",
            "outcome": "PENDING",
        },
        transactions=[],
    )

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["contract"] == "waapi-skill.host-category-evidence/v3"
    assert payload["invocation"]["phase"] == "prepared"
    assert payload["invocation"]["outcome"] == "PENDING"


def test_exact_evidence_v3_rejects_quarantine_without_exact_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(category_evidence, "current_evidence_platform", lambda: "macos")
    nodeid = "tests/destructive/test_example.py::test_one"

    with pytest.raises(AssertionError, match="cannot claim quarantine"):
        category_evidence.append_category_evidence(
            repo_root=tmp_path,
            candidate="d" * 40,
            version="2025.1",
            host={"display_name": "WwiseConsole"},
            categories=[
                {
                    "category": "object-topology",
                    "status": "FAIL",
                    "verifier_strength": "readback",
                }
            ],
            source={},
            residual_state={"sandbox": "quarantined", "quarantine_path": None},
            invocation={
                "selected_test_nodeids": [nodeid],
                "node_outcomes": [{"nodeid": nodeid, "outcome": "FAIL"}],
                "started_at_unix_ns": 1,
                "finished_at_unix_ns": 2,
                "phase": "final",
                "outcome": "FAIL",
            },
            transactions=[],
        )
