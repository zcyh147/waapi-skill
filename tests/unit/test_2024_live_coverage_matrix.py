from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION = "2024.1"
MATRIX_RESOURCE = REPO_ROOT / "resources" / "coverage" / VERSION / "live-coverage-matrix.json"
SUMMARY_RESOURCE = REPO_ROOT / "resources" / "coverage" / VERSION / "phase2-coverage-summary.json"
API_COVERAGE_RESOURCE = REPO_ROOT / "resources" / "coverage" / VERSION / "api-coverage.json"
POLICY_RESOURCE = REPO_ROOT / "resources" / "coverage" / VERSION / "phase21-uri-policy.json"
FUNCTIONS_MANIFEST = REPO_ROOT / "resources" / "manifest" / VERSION / "functions.json"
ALLOWED_PARITY_BUCKETS = {"manifest-only", "deferred", "excluded", "live-tested", "sandbox-mutating-tested"}
RISKY_FAMILIES = {"profiler", "transport", "soundengine", "UI", "CLI", "remote", "debug"}


def test_2024_live_matrix_covers_every_reflected_function_once() -> None:
    matrix = _matrix_payload()["matrix"]
    reflected = sorted(_uris(FUNCTIONS_MANIFEST, "functions"))

    assert len(matrix) == len(reflected)
    assert [entry["uri"] for entry in matrix] == reflected
    assert len({entry["uri"] for entry in matrix}) == len(matrix)
    assert {entry["version"] for entry in matrix} == {VERSION}


def test_2024_live_matrix_has_no_manifest_or_source_note_live_claims() -> None:
    matrix_payload = _matrix_payload()
    coverage_by_uri = {entry["uri"]: entry for entry in _coverage_payload()["coverage"]}

    assert matrix_payload["summary"]["live_tested"] == 0
    assert matrix_payload["summary"]["behavioral_supported"] == 0
    assert "source notes are semantic contracts only" in matrix_payload["metadata"]["status_policy"]
    for entry in matrix_payload["matrix"]:
        source = coverage_by_uri[entry["uri"]]
        evidence = source["behavioral_evidence"]
        assert entry["coverage_status"] == source["coverage_status"], entry["uri"]
        assert entry["parity_bucket"] == source["parity_bucket"], entry["uri"]
        assert entry["parity_bucket"] in {"deferred", "excluded"}, entry["uri"]
        assert entry["evidence_standard"] == source["evidence_standard"], entry["uri"]
        assert entry["counts_as_behavioral"] == evidence["counts_as_behavioral"] is False, entry["uri"]
        assert entry["counts_as_live_behavioral"] == evidence["counts_as_live_behavioral"] is False, entry["uri"]
        assert entry["achieved_status"] not in {"live-tested", "sandbox-mutating-tested"}, entry["uri"]
        assert entry["manifest_source_uri"].startswith("resources/manifest/2024.1/"), entry["uri"]
        assert entry["source_coverage_uri"] == "resources/coverage/2024.1/api-coverage.json"

    assert {uri for uri, entry in coverage_by_uri.items() if entry["coverage_status"] == "live-tested"} == set()
    assert {uri for uri, entry in coverage_by_uri.items() if entry["coverage_status"] == "sandbox-mutating-tested"} == set()


def test_2024_phase2_summary_matches_matrix_without_behavioral_overclaim() -> None:
    summary = _summary_payload()
    matrix = _matrix_payload()
    coverage = _coverage_payload()
    matrix_entries = matrix["matrix"]
    coverage_entries = coverage["coverage"]

    assert summary["metadata"]["baseline_resource"] == "resources/coverage/2024.1/api-coverage.json"
    assert summary["metadata"]["live_matrix_resource"] == "resources/coverage/2024.1/live-coverage-matrix.json"
    assert summary["summary"]["status_counts"] == matrix["summary"]["status_counts"] == coverage["summary"]["status_counts"]
    assert summary["summary"]["parity_bucket_counts"] == matrix["summary"]["parity_bucket_counts"] == coverage["summary"]["parity_bucket_counts"]
    assert set(summary["summary"]["parity_bucket_counts"]) == ALLOWED_PARITY_BUCKETS
    expected_total = len(_uris(FUNCTIONS_MANIFEST, "functions"))

    assert summary["summary"]["parity_bucket_total"] == matrix["summary"]["parity_bucket_total"] == expected_total
    assert coverage["summary"]["parity_bucket_total"] == expected_total
    assert summary["summary"]["behavioral_covered_count"] == 0
    assert summary["summary"]["live_behavioral_covered_count"] == 0
    assert [entry["uri"] for entry in summary["entries"]] == [entry["uri"] for entry in matrix_entries] == [entry["uri"] for entry in coverage_entries]
    assert all(entry["version"] == VERSION for entry in summary["entries"])
    assert all(entry["manifest_reflection_only"] is True for entry in summary["entries"])


def test_2024_phase21_policy_reconciles_parity_buckets_and_blocked_lists() -> None:
    policy = json.loads(POLICY_RESOURCE.read_text(encoding="utf-8"))
    coverage_by_uri = {entry["uri"]: entry for entry in _coverage_payload()["coverage"]}
    parity_buckets = policy["policy"]["parity_buckets"]

    assert set(parity_buckets) == ALLOWED_PARITY_BUCKETS
    expected_total = len(_uris(FUNCTIONS_MANIFEST, "functions"))

    assert policy["summary"]["parity_bucket_total"] == expected_total
    assert sum(policy["summary"]["parity_bucket_counts"].values()) == expected_total

    assigned = [uri for uris in parity_buckets.values() for uri in uris]
    assert sorted(assigned) == sorted(coverage_by_uri)
    assert len(assigned) == len(set(assigned)) == expected_total
    for bucket, uris in parity_buckets.items():
        assert policy["summary"]["parity_bucket_counts"][bucket] == len(uris)
        assert all(coverage_by_uri[uri]["parity_bucket"] == bucket for uri in uris)

    assert policy["policy"]["live_tested_uris"] == []
    assert policy["policy"]["sandbox_mutating_tested_uris"] == []
    assert sorted(policy["policy"]["manifest_only_uris"]) == sorted(coverage_by_uri)
    assert sorted(policy["policy"]["deferred_uris"] + policy["policy"]["excluded_uris"]) == sorted(coverage_by_uri)


def test_2024_risky_policy_keeps_all_risky_families_excluded() -> None:
    policy = json.loads(POLICY_RESOURCE.read_text(encoding="utf-8"))
    coverage_by_uri = {entry["uri"]: entry for entry in _coverage_payload()["coverage"]}

    assert set(policy["policy"]["risky_family_uris"]) == RISKY_FAMILIES
    for family, uris in policy["policy"]["risky_family_uris"].items():
        for uri in uris:
            entry = coverage_by_uri[uri]
            assert entry["coverage_status"] == "excluded", uri
            assert entry["parity_bucket"] == "excluded", uri
            assert entry["behavioral_evidence"]["counts_as_behavioral"] is False, uri
            assert entry["behavioral_evidence"]["counts_as_live_behavioral"] is False, uri


def _matrix_payload() -> dict:
    return json.loads(MATRIX_RESOURCE.read_text(encoding="utf-8"))


def _summary_payload() -> dict:
    return json.loads(SUMMARY_RESOURCE.read_text(encoding="utf-8"))


def _coverage_payload() -> dict:
    return json.loads(API_COVERAGE_RESOURCE.read_text(encoding="utf-8"))


def _uris(path: Path, section: str) -> list[str]:
    return [entry["uri"] for entry in json.loads(path.read_text(encoding="utf-8"))[section]]
