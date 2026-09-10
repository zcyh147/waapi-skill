from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.destructive.support import category_evidence


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
