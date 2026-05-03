from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION = "2025.1"
MATRIX_RESOURCE = REPO_ROOT / "skills" / "wwise-waapi" / "resources" / "coverage" / VERSION / "live-coverage-matrix.json"
SUMMARY_RESOURCE = REPO_ROOT / "skills" / "wwise-waapi" / "resources" / "coverage" / VERSION / "phase2-coverage-summary.json"
API_COVERAGE_RESOURCE = REPO_ROOT / "skills" / "wwise-waapi" / "resources" / "coverage" / VERSION / "api-coverage.json"
POLICY_RESOURCE = REPO_ROOT / "skills" / "wwise-waapi" / "resources" / "coverage" / VERSION / "phase21-uri-policy.json"
FUNCTIONS_MANIFEST = REPO_ROOT / "skills" / "wwise-waapi" / "resources" / "manifest" / VERSION / "functions.json"

ALLOWED_PARITY_BUCKETS = {"deferred", "excluded", "live-tested", "manifest-only", "sandbox-mutating-tested"}
FORBIDDEN_PROMOTED_STATUSES = {"live-tested", "sandbox-mutating-tested"}
CANDIDATE_STATUSES = {"candidate-live-read-only", "candidate-sandbox-mutating"}
LIVE_TESTED_URI = "ak.wwise.core.object.get"
SANDBOX_MUTATING_TESTED_URIS = {
    "ak.wwise.core.audio.import",
    "ak.wwise.core.object.create",
    "ak.wwise.core.object.delete",
    "ak.wwise.core.object.set",
    "ak.wwise.core.soundbank.setInclusions",
    "ak.wwise.core.switchContainer.addAssignment",
    "ak.wwise.core.switchContainer.removeAssignment",
    "ak.wwise.core.undo.beginGroup",
    "ak.wwise.core.undo.endGroup",
    "ak.wwise.core.undo.undo",
}
READBACK_HELPER_URIS = {
    "ak.wwise.core.soundbank.getInclusions",
    "ak.wwise.core.switchContainer.getAssignments",
}


def test_2025_live_matrix_covers_every_reflected_function_once() -> None:
    matrix = _matrix_payload()["matrix"]
    reflected = sorted(_uris(FUNCTIONS_MANIFEST, "functions"))

    assert len(matrix) == len(reflected) == 154
    assert [entry["uri"] for entry in matrix] == reflected
    assert len({entry["uri"] for entry in matrix}) == len(matrix)
    assert {entry["version"] for entry in matrix} == {VERSION}


def test_2025_live_matrix_promotes_only_fresh_object_get_and_destructive_evidence() -> None:
    matrix_payload = _matrix_payload()
    coverage_by_uri = {entry["uri"]: entry for entry in _coverage_payload()["coverage"]}

    assert matrix_payload["summary"]["live_tested"] == 1
    assert matrix_payload["summary"]["behavioral_supported"] == 1 + len(SANDBOX_MUTATING_TESTED_URIS)
    assert matrix_payload["summary"]["behavioral_covered_count"] == 1 + len(SANDBOX_MUTATING_TESTED_URIS)
    assert matrix_payload["summary"]["live_behavioral_covered_count"] == 1 + len(SANDBOX_MUTATING_TESTED_URIS)
    assert "fresh 2025.1 live/destructive evidence" in matrix_payload["metadata"]["status_policy"]

    for entry in matrix_payload["matrix"]:
        source = coverage_by_uri[entry["uri"]]
        evidence = source["behavioral_evidence"]
        assert entry["coverage_status"] == source["coverage_status"], entry["uri"]
        assert entry["parity_bucket"] == source["parity_bucket"], entry["uri"]
        assert entry["evidence_standard"] == source["evidence_standard"], entry["uri"]
        if entry["uri"] == LIVE_TESTED_URI:
            assert entry["counts_as_behavioral"] == evidence["counts_as_behavioral"] is True, entry["uri"]
            assert entry["counts_as_live_behavioral"] == evidence["counts_as_live_behavioral"] is True, entry["uri"]
            assert entry["achieved_status"] == "live-tested", entry["uri"]
            assert entry["evidence_path"] == "resources/waql/2025.1/object-get-live-matrix.json", entry["uri"]
            continue
        if entry["uri"] in SANDBOX_MUTATING_TESTED_URIS:
            assert entry["counts_as_behavioral"] == evidence["counts_as_behavioral"] is True, entry["uri"]
            assert entry["counts_as_live_behavioral"] == evidence["counts_as_live_behavioral"] is True, entry["uri"]
            assert entry["achieved_status"] == "sandbox-mutating-tested", entry["uri"]
            assert entry["evidence_path"].startswith(".sisyphus/evidence/wwise-2025-waapi-integration-coverage/destructive/"), entry["uri"]
            assert ".sisyphus/evidence/task-2025-11-destructive-sandbox.txt" in entry["fixture_prerequisites"], entry["uri"]
            continue

        assert entry["counts_as_behavioral"] == evidence["counts_as_behavioral"] is False, entry["uri"]
        assert entry["counts_as_live_behavioral"] == evidence["counts_as_live_behavioral"] is False, entry["uri"]
        assert entry["manifest_source_uri"].startswith("resources/manifest/2025.1/"), entry["uri"]
        assert entry["source_coverage_uri"] == "resources/coverage/2025.1/api-coverage.json"
        assert entry["achieved_status"] not in FORBIDDEN_PROMOTED_STATUSES, entry["uri"]
        assert entry["current_status"] not in FORBIDDEN_PROMOTED_STATUSES, entry["uri"]
        assert entry["target_status"] not in FORBIDDEN_PROMOTED_STATUSES, entry["uri"]


def test_2025_phase2_summary_matches_matrix_and_coverage_accounting() -> None:
    summary = _summary_payload()
    matrix = _matrix_payload()
    coverage = _coverage_payload()
    matrix_entries = matrix["matrix"]
    coverage_entries = coverage["coverage"]
    coverage_function_entries = [entry for entry in coverage_entries if entry["item_type"] == "function"]
    coverage_topic_entries = [entry for entry in coverage_entries if entry["item_type"] == "topic"]

    assert summary["metadata"]["baseline_resource"] == "resources/coverage/2025.1/api-coverage.json"
    assert summary["metadata"]["live_matrix_resource"] == "resources/coverage/2025.1/live-coverage-matrix.json"
    function_status_counts = _counts(coverage_function_entries, "coverage_status")
    function_parity_counts = _counts(coverage_function_entries, "parity_bucket")
    assert summary["summary"]["status_counts"] == matrix["summary"]["status_counts"] == function_status_counts
    assert summary["summary"]["parity_bucket_counts"] == matrix["summary"]["parity_bucket_counts"] == function_parity_counts
    assert coverage["summary"]["status_counts"]["deferred"] == function_status_counts["deferred"] + len(coverage_topic_entries)
    assert coverage["summary"]["parity_bucket_counts"]["deferred"] == function_parity_counts["deferred"] + len(coverage_topic_entries)
    assert set(summary["summary"]["parity_bucket_counts"]) == ALLOWED_PARITY_BUCKETS
    expected_total = len(_uris(FUNCTIONS_MANIFEST, "functions"))

    assert summary["summary"]["parity_bucket_total"] == matrix["summary"]["parity_bucket_total"] == expected_total
    assert coverage["summary"]["parity_bucket_total"] == expected_total + len(coverage_topic_entries)
    assert summary["summary"]["behavioral_covered_count"] == 1 + len(SANDBOX_MUTATING_TESTED_URIS)
    assert summary["summary"]["live_behavioral_covered_count"] == 1 + len(SANDBOX_MUTATING_TESTED_URIS)
    assert [entry["uri"] for entry in summary["entries"]] == [entry["uri"] for entry in matrix_entries] == [entry["uri"] for entry in coverage_function_entries]
    assert all(entry["version"] == VERSION for entry in summary["entries"])
    assert len(coverage_topic_entries) == 31
    assert all(entry["coverage_status"] == "deferred" for entry in coverage_topic_entries)
    assert all(entry["behavioral_evidence"]["counts_as_behavioral"] is False for entry in coverage_topic_entries)
    assert all(entry["behavioral_evidence"]["counts_as_live_behavioral"] is False for entry in coverage_topic_entries)
    assert all(
        entry["manifest_reflection_only"] is (entry["uri"] not in ({LIVE_TESTED_URI} | SANDBOX_MUTATING_TESTED_URIS))
        for entry in summary["entries"]
    )


def test_2025_phase21_policy_reconciles_parity_buckets_candidates_and_blocked_lists() -> None:
    policy = json.loads(POLICY_RESOURCE.read_text(encoding="utf-8"))
    coverage_by_uri = {entry["uri"]: entry for entry in _coverage_payload()["coverage"]}
    function_coverage_by_uri = {uri: entry for uri, entry in coverage_by_uri.items() if entry["item_type"] == "function"}
    topic_uris = {uri for uri, entry in coverage_by_uri.items() if entry["item_type"] == "topic"}
    parity_buckets = policy["policy"]["parity_buckets"]

    assert set(parity_buckets) == ALLOWED_PARITY_BUCKETS
    expected_total = len(_uris(FUNCTIONS_MANIFEST, "functions"))

    assert policy["summary"]["parity_bucket_total"] == expected_total
    assert sum(policy["summary"]["parity_bucket_counts"].values()) == expected_total

    assigned = [uri for uris in parity_buckets.values() for uri in uris]
    assert sorted(assigned) == sorted(function_coverage_by_uri)
    assert len(assigned) == len(set(assigned)) == expected_total
    for bucket, uris in parity_buckets.items():
        assert policy["summary"]["parity_bucket_counts"][bucket] == len(uris)
        assert all(function_coverage_by_uri[uri]["parity_bucket"] == bucket for uri in uris)

    assert policy["policy"]["live_tested_uris"] == [LIVE_TESTED_URI]
    assert set(policy["policy"]["sandbox_mutating_tested_uris"]) == SANDBOX_MUTATING_TESTED_URIS
    assert not (READBACK_HELPER_URIS & set(policy["policy"]["sandbox_mutating_tested_uris"]))
    promoted_uris = {LIVE_TESTED_URI} | SANDBOX_MUTATING_TESTED_URIS
    assert policy["policy"]["manifest_only_uris"] == sorted(set(function_coverage_by_uri) - promoted_uris)
    assert sorted(policy["policy"]["deferred_uris"] + policy["policy"]["excluded_uris"]) == sorted(set(function_coverage_by_uri) - promoted_uris)
    assert sorted(policy["policy"]["manifest_only_uris"] + policy["policy"]["live_tested_uris"] + policy["policy"]["sandbox_mutating_tested_uris"]) == sorted(function_coverage_by_uri)
    assert not (topic_uris & set(assigned))

    candidate_uris = policy["policy"]["candidate_live_read_only_uris"] + policy["policy"]["candidate_sandbox_mutating_uris"]
    assert candidate_uris
    assert all(coverage_by_uri[uri]["candidate_status"] in CANDIDATE_STATUSES for uri in candidate_uris)
    assert all(
        coverage_by_uri[uri]["coverage_status"] in {"deferred", "excluded", "live-tested", "sandbox-mutating-tested"}
        for uri in candidate_uris
    )
    assert [uri for uri in candidate_uris if coverage_by_uri[uri]["coverage_status"] == "live-tested"] == [LIVE_TESTED_URI]
    assert {uri for uri in candidate_uris if coverage_by_uri[uri]["coverage_status"] == "sandbox-mutating-tested"} == SANDBOX_MUTATING_TESTED_URIS


def test_2025_no_accidental_promotion_policy_is_tracked_json_only() -> None:
    policy = json.loads(POLICY_RESOURCE.read_text(encoding="utf-8"))

    assert policy["summary"]["status_counts"]["live-tested"] == 1
    assert policy["summary"]["status_counts"]["sandbox-mutating-tested"] == len(SANDBOX_MUTATING_TESTED_URIS)
    assert policy["summary"]["forbidden_promoted_counts"] == {"live-tested": 1, "sandbox-mutating-tested": len(SANDBOX_MUTATING_TESTED_URIS)}
    assert policy["policy"]["live_tested_uris"] == [LIVE_TESTED_URI]
    assert set(policy["policy"]["sandbox_mutating_tested_uris"]) == SANDBOX_MUTATING_TESTED_URIS


def _matrix_payload() -> dict:
    return json.loads(MATRIX_RESOURCE.read_text(encoding="utf-8"))


def _summary_payload() -> dict:
    return json.loads(SUMMARY_RESOURCE.read_text(encoding="utf-8"))


def _coverage_payload() -> dict:
    return json.loads(API_COVERAGE_RESOURCE.read_text(encoding="utf-8"))


def _uris(path: Path, section: str) -> list[str]:
    return [entry["uri"] for entry in json.loads(path.read_text(encoding="utf-8"))[section]]


def _counts(entries: list[dict], key: str) -> dict:
    values = ALLOWED_PARITY_BUCKETS if key == "parity_bucket" else set(entry[key] for entry in entries)
    return {value: sum(1 for entry in entries if entry[key] == value) for value in sorted(values)}
