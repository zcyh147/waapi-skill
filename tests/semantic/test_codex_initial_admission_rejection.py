"""No-dispatch policy rejection is distinct from accepted mutation failure."""
import json
import pytest
from tests.semantic.test_codex_repair_read_rejection import produce_rejected_task, INPUTS
from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive, ExpansionArchiveError


def test_wrong_initial_draft_is_a_marked_zero_dispatch_failure(tmp_path, monkeypatch):
    root, outcome, _ = produce_rejected_task(tmp_path, monkeypatch, policy="allow_changes",
        rejected_argv=["draft-start", "ak.wwise.core.gameParameter.setRange"])
    assert outcome["status"] == "FAIL" and outcome["passed"] is False
    record = json.loads((root / "expansion-broker.json").read_text())["records"][-1]
    assert record.get("admission_rejection", {}).get("stage") == "initial_policy_admission"
    assert record["runner_exit_code"] is None
    assert not (root / "broker/state/transactions").exists()
    assert not (root / "broker/state/operation-drafts-v1").exists()
    replay = verify_expansion_task_archive(root, expected_unit_id="REPAIR25-F3", expected_version="2025.1", expected_inputs_sha256=INPUTS)
    assert replay["archive_valid"] is True and replay["original_status"] == "FAIL" and replay["business_pass"] is False
    assert replay["executions"] == replay["execution_reservations"] == 0


@pytest.mark.parametrize("fault", ["missing_marker", "marker_contract", "marker_argv", "marker_state", "dispatch",
    "reservation", "capability", "extra", "authentication", "runner", "draft_store", "transaction_store"])
def test_initial_rejection_requires_complete_unmodified_zero_dispatch_proof(tmp_path, monkeypatch, fault):
    root, _, _ = produce_rejected_task(tmp_path, monkeypatch, policy="allow_changes",
        rejected_argv=["draft-start", "ak.wwise.core.gameParameter.setRange"])
    path = root / "expansion-broker.json"; evidence = json.loads(path.read_text()); record = evidence["records"][-1]
    if fault == "missing_marker": del record["admission_rejection"]
    elif fault == "authentication": record["authenticated"] = False
    elif fault == "runner": record["runner_exit_code"] = 0
    elif fault in {"draft_store", "transaction_store"}:
        (root / "broker/state" / ("operation-drafts-v1" if fault == "draft_store" else "transactions")).mkdir()
    else:
        key, value = {"marker_contract": ("contract", "unreviewed"), "marker_argv": ("gateway_argv_sha256", "0" * 64),
            "marker_state": ("policy_state", "executing"), "dispatch": ("runner_dispatched", True),
            "reservation": ("execution_reserved", True), "capability": ("draft_id", "od1-other"), "extra": ("unreviewed", True)}[fault]
        record["admission_rejection"][key] = value
    path.write_text(json.dumps(evidence))
    with pytest.raises(ExpansionArchiveError):
        verify_expansion_task_archive(root, expected_unit_id="REPAIR25-F3", expected_version="2025.1", expected_inputs_sha256=INPUTS)
    from tests.semantic.run_codex_skill_matrix import expansion_case_isolated
    record = {"scenario_id": "REPAIR25-F3", "version": "2025.1", "status": "FAIL", "scenario_root": str(tmp_path),
        "runner_outcome": {"task_root": str(root), "inputs_sha256": INPUTS, "checks": {"trusted_oracle_closed": True},
            "lifecycle": {"scenario_id": "REPAIR25-F3", "version": "2025.1", "source_hash_before": {"sha256": "source"},
                "source_hash_after": {"sha256": "source"}, "source_mtime_before_ns": 1, "source_mtime_after_ns": 1, "errors": []}}}
    assert not expansion_case_isolated(record)


def test_unexpected_policy_implementation_fault_gets_no_ordinary_rejection_marker(tmp_path, monkeypatch):
    from tests.semantic.support.codex_repair_broker_policy import RepairBrokerPolicy
    def unexpected(*args, **kwargs):
        raise RuntimeError("simulated implementation fault")
    monkeypatch.setattr(RepairBrokerPolicy, "prepare", unexpected)
    root, outcome, _ = produce_rejected_task(tmp_path, monkeypatch, policy="allow_changes",
        rejected_argv=["draft-start", "ak.wwise.core.gameParameter.setRange"])
    record = json.loads((root / "expansion-broker.json").read_text())["records"][-1]
    assert "admission_rejection" not in record
    with pytest.raises(ExpansionArchiveError):
        verify_expansion_task_archive(root, expected_unit_id="REPAIR25-F3", expected_version="2025.1", expected_inputs_sha256=INPUTS)


@pytest.mark.parametrize("field", ["preview_before", "preview_after", "gateway_verification_state"])
def test_initial_rejection_cannot_claim_later_phase_evidence(tmp_path, monkeypatch, field):
    root, _, _ = produce_rejected_task(tmp_path, monkeypatch, policy="allow_changes",
        rejected_argv=["draft-start", "ak.wwise.core.gameParameter.setRange"])
    path = root / "expansion-oracle.json"; value = json.loads(path.read_text()); value[field] = "unearned"
    path.write_text(json.dumps(value))
    with pytest.raises(ExpansionArchiveError):
        verify_expansion_task_archive(root, expected_unit_id="REPAIR25-F3", expected_version="2025.1", expected_inputs_sha256=INPUTS)
