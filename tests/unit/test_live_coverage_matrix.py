from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from wwise_waapi.phase21_uri_policy import CONFORMANCE_ONLY_URIS  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "waapi-skill"
MATRIX_RESOURCE = SKILL_ROOT / "resources" / "capabilities" / "2022.1" / "live-coverage-matrix.json"
API_COVERAGE_RESOURCE = SKILL_ROOT / "resources" / "capabilities" / "2022.1" / "api-coverage.json"
FUNCTIONS_MANIFEST = SKILL_ROOT / "resources" / "manifest" / "2022.1" / "functions.json"
TOPICS_MANIFEST = SKILL_ROOT / "resources" / "manifest" / "2022.1" / "topics.json"
WAQL_API_URI = "ak.wwise.core.object.get"

REQUIRED_ENTRY_FIELDS = {
    "uri",
    "version",
    "item_type",
    "category",
    "current_status",
    "target_status",
    "achieved_status",
    "destructive_risk",
    "allowed_test_tier",
    "fixture_prerequisites",
    "evidence_standard",
    "skip_wrapper_rationale",
    "fallback_reason",
    "phase1_inventory_status",
    "phase1_behavioral_evidence",
    "source_coverage_uri",
}
ALLOWED_TARGET_STATUSES = {
    "deferred-with-substitute-test",
    "fake-route-tested",
    "live-candidate",
    "conformance-only-skip",
    "skipped-approved",
    "wrapper-only",
}
ALLOWED_ACHIEVED_STATUSES = {"fake-route-tested", "deferred-with-substitute-test"}
NON_LIVE_TARGET_STATUSES = {"wrapper-only", "skipped-approved", "conformance-only-skip", "deferred-with-substitute-test"}
WRAPPER_ONLY_CATEGORIES = {"ui", "ui.commands", "ui.project"}
SKIPPED_APPROVED_CATEGORIES = {"cli", "core.remote", "debug"}
LIVE_CANDIDATE_CATEGORIES = {
    "core.audio",
    "core.object",
    "core.profiler",
    "core.profiler.captureLog",
    "core.soundbank",
    "core.switchContainer",
    "core.transport",
    "core.undo",
    "soundengine",
}


def test_matrix_covers_every_reflected_2022_api_once_sorted_by_uri() -> None:
    matrix = _matrix_entries()
    reflected_functions = _uris(FUNCTIONS_MANIFEST, "functions")
    reflected_topics = _uris(TOPICS_MANIFEST, "topics")
    reflected = sorted(reflected_functions + reflected_topics)

    assert len(reflected_functions) == 112
    assert len(reflected_topics) == 32
    assert len(matrix) == 144
    assert [entry["uri"] for entry in matrix] == reflected
    assert len({entry["uri"] for entry in matrix}) == len(matrix)


def test_matrix_entries_have_required_status_schema_and_preserve_phase1_achievements() -> None:
    source_by_uri = _api_coverage_by_uri()

    for entry in _matrix_entries():
        uri = entry["uri"]
        source = source_by_uri[uri]
        assert REQUIRED_ENTRY_FIELDS <= set(entry), uri
        assert entry["version"] == "2022.1"
        assert entry["target_status"] in ALLOWED_TARGET_STATUSES, uri
        assert entry["achieved_status"] in ALLOWED_ACHIEVED_STATUSES, uri
        assert entry["current_status"] == source["test_status"], uri
        assert entry["achieved_status"] == source["test_status"], uri
        assert entry["category"] == source["category"], uri
        assert entry["item_type"] == source["item_type"], uri
        assert entry["destructive_risk"]["risk_level"] == source["risk_level"], uri
        assert entry["destructive_risk"]["destructive_opt_in"] == source["destructive_opt_in"], uri
        assert entry["phase1_inventory_status"] == "reflected-schema-ok", uri
        assert entry["evidence_standard"], uri
        assert entry["fallback_reason"], uri


def test_live_candidates_have_fixture_prerequisites_and_non_live_targets_do_not_count_as_live() -> None:
    for entry in _matrix_entries():
        target_status = entry["target_status"]
        if target_status == "live-candidate":
            assert entry["fixture_prerequisites"], entry["uri"]
            assert entry["allowed_test_tier"] in {"live-sandbox", "live-sandbox-destructive-opt-in"}, entry["uri"]
            assert entry["achieved_status"] != "live-tested", entry["uri"]
        if target_status in NON_LIVE_TARGET_STATUSES:
            assert not entry["allowed_test_tier"].startswith("live"), entry["uri"]
            assert entry["achieved_status"] != "live-tested", entry["uri"]


def test_wrapper_and_skipped_entries_have_rationales() -> None:
    for entry in _matrix_entries():
        if entry["target_status"] in {"wrapper-only", "skipped-approved"}:
            assert entry["skip_wrapper_rationale"], entry["uri"]
            assert entry["fixture_prerequisites"] == [], entry["uri"]


def test_conformance_only_entries_have_policy_rationales_and_are_not_live_candidates() -> None:
    entries = _by_uri(_matrix_entries())

    assert {uri for uri, entry in entries.items() if entry["target_status"] == "conformance-only-skip"} == CONFORMANCE_ONLY_URIS
    for uri in CONFORMANCE_ONLY_URIS:
        entry = entries[uri]
        assert entry["allowed_test_tier"] == "conformance-only-policy"
        assert entry["fixture_prerequisites"] == []
        assert entry["counts_as_live_behavior"] is False
        assert entry["evidence_class"] == "conformance_only_skip"
        assert "behaviorally simple" in entry["user_approved_rationale"]
        assert "lifecycle/state-transition live proof" in entry["future_review_trigger"]


def test_matrix_points_to_final_phase21_consolidation_without_claiming_windows() -> None:
    consolidation = _matrix_payload()["metadata"]["phase2_consolidation"]
    non_live_statuses = _matrix_payload()["metadata"]["does_not_count_as_live_behavioral_coverage"]

    assert consolidation["final_summary_resource"] == "resources/capabilities/2022.1/phase2-coverage-summary.json"
    assert consolidation["audit_resource"] == "wwise_waapi/api_coverage_audit.py"
    assert consolidation["evidence_classes"] == [
        "live_behavioral_waapi",
        "live_behavioral_profiler",
        "conformance_only_skip",
        "still_deferred_with_evidence",
    ]
    assert consolidation["windows_validation"] == "pending"
    assert "final one-status-per-URI" in consolidation["policy"]
    assert "fake-route-tested" in non_live_statuses


def test_user_category_policy() -> None:
    entries = _matrix_entries()

    for entry in entries:
        category = entry["category"]
        uri = entry["uri"]
        if category in {"cli", "core.remote", "debug"}:
            assert entry["target_status"] in {"skipped-approved", "wrapper-only"}, uri
        if category in {"ui", "ui.commands", "ui.project"}:
            assert entry["target_status"] == "wrapper-only", uri
        if _is_expected_live_candidate(entry):
            assert entry["target_status"] == "live-candidate", uri

    assert any(entry["target_status"] == "live-candidate" and entry["category"] == "soundengine" for entry in entries)
    assert any(entry["target_status"] == "live-candidate" and entry["item_type"] == "topic" for entry in entries)
    assert _by_uri(entries)[WAQL_API_URI]["target_status"] == "live-candidate"
    assert all(
        entry["achieved_status"] == "fake-route-tested"
        for entry in entries
        if _api_coverage_by_uri()[entry["uri"]]["test_status"] == "fake-route-tested"
    )


def _is_expected_live_candidate(entry: Mapping[str, Any]) -> bool:
    if entry["uri"] in CONFORMANCE_ONLY_URIS:
        return False
    category = entry["category"]
    if category in WRAPPER_ONLY_CATEGORIES or category in SKIPPED_APPROVED_CATEGORIES:
        return False
    return entry["item_type"] == "topic" or category in LIVE_CANDIDATE_CATEGORIES or entry["uri"] == WAQL_API_URI


def _matrix_payload() -> dict[str, Any]:
    return json.loads(MATRIX_RESOURCE.read_text(encoding="utf-8"))


def _matrix_entries() -> list[Mapping[str, Any]]:
    entries = _matrix_payload()["matrix"]
    assert isinstance(entries, list)
    return entries


def _api_coverage_by_uri() -> dict[str, Mapping[str, Any]]:
    payload = json.loads(API_COVERAGE_RESOURCE.read_text(encoding="utf-8"))
    return {entry["uri"]: entry for entry in payload["coverage"]}


def _uris(path: Path, section: str) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [entry["uri"] for entry in payload[section]]


def _by_uri(entries: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {entry["uri"]: entry for entry in entries}
