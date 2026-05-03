from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION = "2024.1"
MATRIX_RESOURCE = REPO_ROOT / "skills" / "wwise-waapi" / "resources" / "capabilities" / VERSION / "live-coverage-matrix.json"
SUMMARY_RESOURCE = REPO_ROOT / "skills" / "wwise-waapi" / "resources" / "capabilities" / VERSION / "phase2-coverage-summary.json"
API_COVERAGE_RESOURCE = REPO_ROOT / "skills" / "wwise-waapi" / "resources" / "capabilities" / VERSION / "api-coverage.json"
POLICY_RESOURCE = REPO_ROOT / "skills" / "wwise-waapi" / "resources" / "capabilities" / VERSION / "phase21-uri-policy.json"
FUNCTIONS_MANIFEST = REPO_ROOT / "skills" / "wwise-waapi" / "resources" / "manifest" / VERSION / "functions.json"
PROMOTED_READ_ONLY_URI = "ak.wwise.core.object.get"
PROMOTED_READ_ONLY_URIS = {PROMOTED_READ_ONLY_URI}
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
ALLOWED_PARITY_BUCKETS = {"manifest-only", "deferred", "excluded", "live-tested", "sandbox-mutating-tested"}
RISKY_FAMILIES = {"profiler", "transport", "soundengine", "UI", "CLI", "remote", "debug"}


def test_2024_live_matrix_covers_every_reflected_function_once() -> None:
    matrix = _matrix_payload()["matrix"]
    reflected = sorted(_uris(FUNCTIONS_MANIFEST, "functions"))

    assert len(matrix) == len(reflected)
    assert [entry["uri"] for entry in matrix] == reflected
    assert len({entry["uri"] for entry in matrix}) == len(matrix)
    assert {entry["version"] for entry in matrix} == {VERSION}


def test_2024_live_matrix_promotes_only_fresh_2024_evidence() -> None:
    matrix_payload = _matrix_payload()
    coverage_by_uri = {entry["uri"]: entry for entry in _coverage_payload()["coverage"]}
    live_entries = [entry for entry in matrix_payload["matrix"] if entry["coverage_status"] == "live-tested"]
    sandbox_entries = [entry for entry in matrix_payload["matrix"] if entry["coverage_status"] == "sandbox-mutating-tested"]

    assert matrix_payload["summary"]["live_tested"] == 1
    assert matrix_payload["summary"]["behavioral_supported"] == 1 + len(SANDBOX_MUTATING_TESTED_URIS)
    assert matrix_payload["summary"]["live_behavioral_covered_count"] == 1 + len(SANDBOX_MUTATING_TESTED_URIS)
    assert "Task 8 promotes ak.wwise.core.object.get" in matrix_payload["metadata"]["status_policy"]
    assert "Task 10 promotes only safe mutating APIs" in matrix_payload["metadata"]["status_policy"]
    assert {entry["uri"] for entry in live_entries} == PROMOTED_READ_ONLY_URIS
    assert {entry["uri"] for entry in sandbox_entries} == SANDBOX_MUTATING_TESTED_URIS

    for entry in matrix_payload["matrix"]:
        source = coverage_by_uri[entry["uri"]]
        evidence = source["behavioral_evidence"]
        assert entry["coverage_status"] == source["coverage_status"], entry["uri"]
        assert entry["parity_bucket"] == source["parity_bucket"], entry["uri"]
        assert entry["evidence_standard"] == source["evidence_standard"], entry["uri"]
        assert entry["counts_as_behavioral"] == evidence["counts_as_behavioral"], entry["uri"]
        assert entry["counts_as_live_behavioral"] == evidence["counts_as_live_behavioral"], entry["uri"]
        assert entry["manifest_source_uri"].startswith("resources/manifest/2024.1/"), entry["uri"]
        assert entry["source_coverage_uri"] == "resources/capabilities/2024.1/api-coverage.json"

        if entry["uri"] == PROMOTED_READ_ONLY_URI:
            assert entry["parity_bucket"] == "live-tested"
            assert entry["achieved_status"] == "live-tested"
            assert entry["counts_as_behavioral"] is True
            assert entry["counts_as_live_behavioral"] is True
            assert entry["evidence_path"] == "resources/waql/2024.1/object-get-live-matrix.json"
            assert ".sisyphus/evidence/task-2024-8-live-read-only.txt" in entry["fixture_prerequisites"]
        elif entry["uri"] in SANDBOX_MUTATING_TESTED_URIS:
            assert entry["parity_bucket"] == "sandbox-mutating-tested"
            assert entry["achieved_status"] == "sandbox-mutating-tested"
            assert entry["counts_as_behavioral"] is True
            assert entry["counts_as_live_behavioral"] is True
            assert entry["evidence_path"] == ".sisyphus/evidence/task-2024-10-destructive-sandbox.txt"
            assert any(path.startswith(".sisyphus/evidence/wwise-2024-waapi-integration-coverage/destructive/") for path in entry["fixture_prerequisites"])
        else:
            assert entry["parity_bucket"] in {"deferred", "excluded"}, entry["uri"]
            assert entry["counts_as_behavioral"] is False, entry["uri"]
            assert entry["counts_as_live_behavioral"] is False, entry["uri"]
            assert entry["achieved_status"] not in {"live-tested", "sandbox-mutating-tested"}, entry["uri"]

    assert {uri for uri, entry in coverage_by_uri.items() if entry["coverage_status"] == "live-tested"} == PROMOTED_READ_ONLY_URIS
    assert {uri for uri, entry in coverage_by_uri.items() if entry["coverage_status"] == "sandbox-mutating-tested"} == SANDBOX_MUTATING_TESTED_URIS
    assert all(coverage_by_uri[uri]["coverage_status"] == "deferred" for uri in READBACK_HELPER_URIS)


def test_2024_phase2_summary_matches_matrix_with_object_get_promotion() -> None:
    summary = _summary_payload()
    matrix = _matrix_payload()
    coverage = _coverage_payload()
    matrix_entries = matrix["matrix"]
    coverage_entries = coverage["coverage"]
    coverage_function_entries = [entry for entry in coverage_entries if entry["item_type"] == "function"]
    coverage_topic_entries = [entry for entry in coverage_entries if entry["item_type"] == "topic"]

    assert summary["metadata"]["baseline_resource"] == "resources/capabilities/2024.1/api-coverage.json"
    assert summary["metadata"]["live_matrix_resource"] == "resources/capabilities/2024.1/live-coverage-matrix.json"
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
    assert len(coverage_topic_entries) == 30
    assert all(entry["coverage_status"] == "deferred" for entry in coverage_topic_entries)
    assert all(entry["behavioral_evidence"]["counts_as_behavioral"] is False for entry in coverage_topic_entries)
    assert all(entry["behavioral_evidence"]["counts_as_live_behavioral"] is False for entry in coverage_topic_entries)
    assert {entry["uri"] for entry in summary["entries"] if entry["manifest_reflection_only"] is False} == (
        PROMOTED_READ_ONLY_URIS | SANDBOX_MUTATING_TESTED_URIS
    )


def test_2024_phase21_policy_reconciles_parity_buckets_and_blocked_lists() -> None:
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

    assert policy["policy"]["live_tested_uris"] == [PROMOTED_READ_ONLY_URI]
    assert set(policy["policy"]["sandbox_mutating_tested_uris"]) == SANDBOX_MUTATING_TESTED_URIS
    assert PROMOTED_READ_ONLY_URI not in policy["policy"]["manifest_only_uris"]
    assert not (SANDBOX_MUTATING_TESTED_URIS & set(policy["policy"]["manifest_only_uris"]))
    assert READBACK_HELPER_URIS <= set(policy["policy"]["manifest_only_uris"])
    assert sorted(policy["policy"]["manifest_only_uris"] + policy["policy"]["live_tested_uris"] + policy["policy"]["sandbox_mutating_tested_uris"]) == sorted(function_coverage_by_uri)
    assert sorted(policy["policy"]["deferred_uris"] + policy["policy"]["excluded_uris"] + policy["policy"]["live_tested_uris"] + policy["policy"]["sandbox_mutating_tested_uris"]) == sorted(function_coverage_by_uri)
    assert not (topic_uris & set(assigned))


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


def _counts(entries: list[dict], key: str) -> dict:
    values = ALLOWED_PARITY_BUCKETS if key == "parity_bucket" else set(entry[key] for entry in entries)
    return {value: sum(1 for entry in entries if entry[key] == value) for value in sorted(values)}
