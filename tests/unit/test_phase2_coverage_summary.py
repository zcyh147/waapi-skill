from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from wwise_waapi.api_coverage_audit import ApiCoverageAuditor  # pyright: ignore[reportMissingImports]
from wwise_waapi.deferred_registry import DeferredRegistry  # pyright: ignore[reportMissingImports]
from wwise_waapi.manifest import DeterministicJsonWriter, ManifestStore  # pyright: ignore[reportMissingImports]
from wwise_waapi.phase2_coverage_summary import (  # pyright: ignore[reportMissingImports]
    Phase2CoverageSummaryBuilder,
    phase2_status_records_from_summary,
)
from wwise_waapi.phase21_uri_policy import (  # pyright: ignore[reportMissingImports]
    ACCEPTED_FAKE_ROUTE_PROFILER_READ_URIS,
    CONFORMANCE_ONLY_URIS,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT
MANIFEST_ROOT = SKILL_ROOT / "resources" / "manifest"
SUMMARY_RESOURCE = SKILL_ROOT / "resources" / "coverage" / "2022.1" / "phase2-coverage-summary.json"
SKIPPED_APPROVED_CATEGORIES = {"cli", "core.remote", "debug"}
WRAPPER_ONLY_CATEGORIES = {"ui", "ui.commands", "ui.project"}
POLICY_CATEGORIES = SKIPPED_APPROVED_CATEGORIES | WRAPPER_ONLY_CATEGORIES


def test_phase2_summary_resource_is_regenerated_byte_stable() -> None:
    generated = Phase2CoverageSummaryBuilder().build("2022.1")
    on_disk = _summary_payload()

    assert generated == on_disk
    assert DeterministicJsonWriter().dumps(generated) == SUMMARY_RESOURCE.read_text(encoding="utf-8")


def test_phase2_summary_covers_144_reflected_apis_and_audits_statuses() -> None:
    payload = _summary_payload()
    manifest = ManifestStore(root=MANIFEST_ROOT).load("2022.1")
    records = phase2_status_records_from_summary(payload)

    result = ApiCoverageAuditor().audit(manifest, DeferredRegistry(), version="2022.1", phase2_status_records=records)

    assert result.passed is True
    assert result.reflected_count == 144
    assert result.inventory_covered_count == 144
    assert result.phase2_status_covered_count == 144
    assert result.behavioral_covered_count == 38
    assert result.live_behavioral_covered_count == 13
    assert result.status_counts == payload["summary"]["phase2_status_counts"]
    assert [entry["uri"] for entry in payload["entries"]] == sorted(
        entry["uri"] for entry in manifest["functions"] + manifest["topics"]
    )


def test_before_after_counts_preserve_phase1_baseline_and_phase2_policy() -> None:
    summary = _summary_payload()["summary"]

    assert summary["total_functions"] == 112
    assert summary["total_topics"] == 32
    assert summary["reflected_count"] == 144
    assert summary["phase1_status_counts"] == {"deferred-with-substitute-test": 117, "fake-route-tested": 27}
    assert summary["original_deferred_before_phase2"] == 117
    assert summary["original_deferred_after_phase2"] == 63
    assert summary["original_deferred_promoted_behavioral"] == 13
    assert summary["original_deferred_policy_approved"] == 41
    assert summary["original_fake_route_promoted_live"] == 0
    assert summary["phase2_status_counts"] == {
        "conformance-only-skip": 11,
        "fake-route-tested": 25,
        "sandbox-mutating-tested": 13,
        "skipped-approved": 21,
        "still-deferred-with-evidence": 63,
        "wrapper-only": 11,
    }
    assert summary["phase2_status_counts"].get("live-sandbox-tested", 0) == 0
    assert summary["profiler_backed_tested_count"] == 0
    assert summary["soundengine_backed_tested_count"] == 0
    assert summary["windows_validation"] == "pending"


def test_policy_categories_take_precedence_over_fake_route_status() -> None:
    entries = _summary_payload()["entries"]
    skipped = [entry for entry in entries if entry["achieved_status"] == "skipped-approved"]
    wrapper = [entry for entry in entries if entry["achieved_status"] == "wrapper-only"]
    phase1_fake_policy = [
        entry for entry in entries if entry["phase1_status"] == "fake-route-tested" and entry["category"] in POLICY_CATEGORIES
    ]

    assert len(skipped) == 21
    assert len(wrapper) == 11
    assert {entry["category"] for entry in skipped} <= SKIPPED_APPROVED_CATEGORIES
    assert {entry["category"] for entry in wrapper} <= WRAPPER_ONLY_CATEGORIES
    assert len(phase1_fake_policy) == 2
    for entry in phase1_fake_policy:
        expected = "skipped-approved" if entry["category"] in SKIPPED_APPROVED_CATEGORIES else "wrapper-only"
        assert entry["achieved_status"] == expected, entry["uri"]
        assert entry["status_transition"] == "phase1-fake-route-policy-approved", entry["uri"]
        assert entry["counts_as_behavioral"] is False, entry["uri"]


def test_non_policy_phase1_fake_route_tested_apis_remain_accepted_and_unchanged() -> None:
    fake_route_entries = [entry for entry in _summary_payload()["entries"] if entry["phase1_status"] == "fake-route-tested"]
    non_policy_fake_route_entries = [entry for entry in fake_route_entries if entry["category"] not in POLICY_CATEGORIES]

    assert len(fake_route_entries) == 27
    assert len(non_policy_fake_route_entries) == 25
    assert {entry["achieved_status"] for entry in non_policy_fake_route_entries} == {"fake-route-tested"}
    assert {entry["status_transition"] for entry in non_policy_fake_route_entries} == {"phase1-fake-route-unchanged"}
    assert all(
        entry["evidence_command"] == "python -m pytest tests/unit/test_dispatch_routes_all_2022.py -q"
        for entry in non_policy_fake_route_entries
    )


def test_every_phase2_transition_has_evidence_and_deferred_entries_keep_blockers() -> None:
    for entry in _summary_payload()["entries"]:
        assert entry["evidence_path"], entry["uri"]
        assert entry["evidence_command"], entry["uri"]
        assert entry["evidence_paths"], entry["uri"]
        assert entry["inventory_coverage"] == "reflected-schema-ok", entry["uri"]
        assert entry["windows_validation"] == "pending", entry["uri"]
        if entry["achieved_status"] == "still-deferred-with-evidence":
            assert entry["substitute_test"], entry["uri"]
            assert "not behavioral coverage" in entry["substitute_test"], entry["uri"]
            assert entry["blocking_condition"], entry["uri"]
            assert entry["future_review_trigger"], entry["uri"]
            assert entry["counts_as_behavioral"] is False, entry["uri"]
            assert entry["counts_as_live_behavioral"] is False, entry["uri"]
        if entry["achieved_status"] in {"wrapper-only", "skipped-approved", "conformance-only-skip"}:
            assert entry["user_approved_rationale"], entry["uri"]
            assert entry["counts_as_behavioral"] is False, entry["uri"]
            assert entry["counts_as_live_behavioral"] is False, entry["uri"]


def test_truthful_promotions_and_required_blockers_are_not_overclaimed() -> None:
    entries = _entries_by_uri()

    assert entries["ak.wwise.core.object.get"]["achieved_status"] == "fake-route-tested"
    assert entries["ak.wwise.core.object.get"]["phase1_status"] == "fake-route-tested"
    assert ".sisyphus/evidence/wwise-waapi-live-sandbox-coverage/task-5-waql-live.md" in entries[
        "ak.wwise.core.object.get"
    ]["supplemental_live_evidence"]["evidence_paths"]
    assert entries["ak.wwise.core.object.create"]["achieved_status"] == "sandbox-mutating-tested"
    assert entries["ak.wwise.core.audio.imported"]["achieved_status"] == "sandbox-mutating-tested"
    assert entries["ak.wwise.core.soundbank.generated"]["achieved_status"] == "sandbox-mutating-tested"

    assert_conformance_only(entries, "ak.wwise.core.project.saved")
    assert_conformance_only(entries, "ak.wwise.core.undo.cancelGroup")
    assert "undo.redo" in entries["ak.wwise.core.undo.cancelGroup"]["related_blocker"]
    assert_blocked(entries, "ak.wwise.core.switchContainer.addAssignment", "Switch Group reference")
    assert_fake_route_with_attempted_blocker(entries, "ak.wwise.core.switchContainer.getAssignments", "readback")
    assert_blocked(entries, "ak.wwise.core.soundbank.processDefinitionFiles", "SoundBank object readback")
    assert_conformance_only(entries, "ak.wwise.core.transport.stateChanged")
    assert_blocked(entries, "ak.soundengine.postMsgMonitor", "capture-log topic payload")
    assert_blocked(entries, "ak.wwise.core.profiler.captureLog.itemAdded", "capture-log topic payload")
    assert_blocked(entries, "ak.soundengine.registerGameObj", "profiler game-object topic payloads")
    assert_blocked(entries, "ak.wwise.core.profiler.gameObjectRegistered", "profiler game-object topic payloads")


def test_windows_remains_pending_not_validated() -> None:
    payload = _summary_payload()

    assert payload["summary"]["windows_validation"] == "pending"
    assert "not Windows validation" in payload["metadata"]["windows_policy"]
    assert {entry["windows_validation"] for entry in payload["entries"]} == {"pending"}


def assert_blocked(entries: Mapping[str, Mapping[str, Any]], uri: str, blocker_text: str) -> None:
    entry = entries[uri]
    assert entry["achieved_status"] == "still-deferred-with-evidence"
    assert blocker_text in entry["blocking_condition"]
    assert entry["substitute_test"]
    assert entry["future_review_trigger"]


def assert_conformance_only(entries: Mapping[str, Mapping[str, Any]], uri: str) -> None:
    entry = entries[uri]
    assert entry["achieved_status"] == "conformance-only-skip"
    assert entry["evidence_class"] == "conformance_only_skip"
    assert entry["counts_as_behavioral"] is False
    assert entry["counts_as_live_behavioral"] is False
    assert "behaviorally simple" in entry["user_approved_rationale"]
    assert "lifecycle/state-transition live proof" in entry["future_review_trigger"]


def test_conformance_only_policy_entries_are_explicit_and_non_live() -> None:
    entries = _entries_by_uri()

    assert {uri for uri, entry in entries.items() if entry["achieved_status"] == "conformance-only-skip"} == CONFORMANCE_ONLY_URIS
    for uri in CONFORMANCE_ONLY_URIS:
        assert_conformance_only(entries, uri)
        assert entries[uri]["status_transition"] == "phase1-deferred-conformance-only-policy-approved"

    for uri in ACCEPTED_FAKE_ROUTE_PROFILER_READ_URIS:
        assert entries[uri]["achieved_status"] == "fake-route-tested"
        assert entries[uri]["counts_as_behavioral"] is True
        assert entries[uri]["counts_as_live_behavioral"] is False


def assert_fake_route_with_attempted_blocker(
    entries: Mapping[str, Mapping[str, Any]], uri: str, blocker_text: str
) -> None:
    entry = entries[uri]
    assert entry["phase1_status"] == "fake-route-tested"
    assert entry["achieved_status"] == "fake-route-tested"
    assert blocker_text in entry["attempted_live_blocker"]
    assert entry["attempted_live_evidence_path"]
    assert entry["attempted_live_evidence_command"]
    assert entry["attempted_live_review_trigger"]


def _summary_payload() -> dict[str, Any]:
    return json.loads(SUMMARY_RESOURCE.read_text(encoding="utf-8"))


def _entries_by_uri() -> dict[str, Mapping[str, Any]]:
    return {entry["uri"]: entry for entry in _summary_payload()["entries"]}
