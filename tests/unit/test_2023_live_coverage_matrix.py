from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION = "2023.1"
MATRIX_RESOURCE = REPO_ROOT / "tests" / "destructive" / "support" / "resources" / "capabilities" / VERSION / "live-coverage-matrix.json"
SUMMARY_RESOURCE = REPO_ROOT / "tests" / "destructive" / "support" / "resources" / "capabilities" / VERSION / "phase2-coverage-summary.json"
API_COVERAGE_RESOURCE = REPO_ROOT / "tests" / "destructive" / "support" / "resources" / "capabilities" / VERSION / "api-coverage.json"
POLICY_RESOURCE = REPO_ROOT / "tests" / "destructive" / "support" / "resources" / "capabilities" / VERSION / "phase21-uri-policy.json"
WAQL_RESOURCE = REPO_ROOT / "tests" / "fixtures" / "resource-evidence" / "waql" / VERSION / "object-get-live-matrix.json"
FUNCTIONS_MANIFEST = REPO_ROOT / "skills" / "waapi-skill" / "resources" / "manifest" / VERSION / "functions.json"
TOPICS_MANIFEST = REPO_ROOT / "skills" / "waapi-skill" / "resources" / "manifest" / VERSION / "topics.json"
ALLOWED_PARITY_BUCKETS = {
    "live-tested",
    "sandbox-mutating-tested",
    "fake-route-tested",
    "evidence-only",
    "conformance-only",
    "wrapper-only",
    "deferred",
    "excluded",
}
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
APPROVED_PROMOTION_EVIDENCE = (
    ".sisyphus/evidence/wwise-2023-test-parity/",
    "resources/waql/2023.1/",
)


def test_2023_live_matrix_covers_every_reflected_api_once() -> None:
    matrix = _matrix_payload()["matrix"]
    reflected = sorted(_uris(FUNCTIONS_MANIFEST, "functions") + _uris(TOPICS_MANIFEST, "topics"))

    assert len(matrix) == 181
    assert [entry["uri"] for entry in matrix] == reflected
    assert len({entry["uri"] for entry in matrix}) == len(matrix)
    assert {entry["version"] for entry in matrix} == {VERSION}


def test_2023_live_matrix_has_no_manifest_only_live_claims() -> None:
    matrix_payload = _matrix_payload()
    coverage_by_uri = {entry["uri"]: entry for entry in _coverage_payload()["coverage"]}
    promoted_uris = {LIVE_TESTED_URI, *SANDBOX_MUTATING_TESTED_URIS}

    assert matrix_payload["summary"]["live_tested"] == 1
    assert "manifest reflection alone is never behavioral support" in matrix_payload["metadata"]["status_policy"]
    for entry in matrix_payload["matrix"]:
        source = coverage_by_uri[entry["uri"]]
        evidence = source["behavioral_evidence"]
        assert entry["coverage_status"] == source["coverage_status"], entry["uri"]
        assert entry["parity_bucket"] == source["parity_bucket"], entry["uri"]
        assert entry["parity_bucket"] in ALLOWED_PARITY_BUCKETS, entry["uri"]
        assert entry["evidence_standard"] == source["evidence_standard"], entry["uri"]
        assert entry["counts_as_behavioral"] == evidence["counts_as_behavioral"], entry["uri"]
        assert entry["counts_as_live_behavioral"] == evidence["counts_as_live_behavioral"], entry["uri"]
        if entry["uri"] == LIVE_TESTED_URI:
            assert entry["counts_as_behavioral"] is True, entry["uri"]
            assert entry["counts_as_live_behavioral"] is True, entry["uri"]
            assert entry["achieved_status"] == "live-tested", entry["uri"]
            assert entry["evidence_path"] == ".sisyphus/evidence/task-3-live-read-only.txt"
            assert _has_approved_promotion_evidence(source), entry["uri"]
        elif entry["uri"] in SANDBOX_MUTATING_TESTED_URIS:
            assert entry["counts_as_behavioral"] is True, entry["uri"]
            assert entry["counts_as_live_behavioral"] is True, entry["uri"]
            assert entry["achieved_status"] == "sandbox-mutating-tested", entry["uri"]
            assert entry["evidence_path"] == ".sisyphus/evidence/task-4-destructive-sandbox.txt"
            assert _has_approved_promotion_evidence(source), entry["uri"]
        else:
            assert entry["counts_as_behavioral"] is False, entry["uri"]
            assert entry["counts_as_live_behavioral"] is False, entry["uri"]
            assert entry["achieved_status"] != "live-tested", entry["uri"]
            assert entry["uri"] not in promoted_uris, entry["uri"]
            if evidence.get("manifest_reflection_only") is True:
                assert entry["achieved_status"] not in {"live-tested", "sandbox-mutating-tested"}, entry["uri"]
                assert entry["parity_bucket"] not in {"live-tested", "sandbox-mutating-tested"}, entry["uri"]
        assert entry["manifest_source_uri"].startswith("resources/manifest/2023.1/"), entry["uri"]

    assert {uri for uri, entry in coverage_by_uri.items() if entry["coverage_status"] == "live-tested"} == {LIVE_TESTED_URI}
    assert {uri for uri, entry in coverage_by_uri.items() if entry["coverage_status"] == "sandbox-mutating-tested"} == SANDBOX_MUTATING_TESTED_URIS
    assert all(coverage_by_uri[uri]["coverage_status"] == "supported" for uri in READBACK_HELPER_URIS)
    assert all(coverage_by_uri[uri]["parity_bucket"] == "conformance-only" for uri in READBACK_HELPER_URIS)


def test_2023_phase2_summary_matches_matrix_without_behavioral_overclaim() -> None:
    summary = _summary_payload()
    matrix = _matrix_payload()
    coverage = _coverage_payload()
    matrix_entries = matrix["matrix"]
    coverage_entries = coverage["coverage"]
    behavioral_uris = {entry["uri"] for entry in matrix_entries if entry["counts_as_behavioral"] is True}
    live_behavioral_uris = {entry["uri"] for entry in matrix_entries if entry["counts_as_live_behavioral"] is True}
    promoted_uris = {LIVE_TESTED_URI, *SANDBOX_MUTATING_TESTED_URIS}

    assert summary["metadata"]["baseline_resource"] == "tests/destructive/support/resources/capabilities/2023.1/api-coverage.json"
    assert summary["metadata"]["live_matrix_resource"] == "tests/destructive/support/resources/capabilities/2023.1/live-coverage-matrix.json"
    assert summary["summary"]["status_counts"] == matrix["summary"]["status_counts"] == coverage["summary"]["status_counts"]
    assert summary["summary"]["parity_bucket_counts"] == matrix["summary"]["parity_bucket_counts"] == coverage["summary"]["parity_bucket_counts"]
    assert set(summary["summary"]["parity_bucket_counts"]) == ALLOWED_PARITY_BUCKETS
    assert summary["summary"]["parity_bucket_total"] == matrix["summary"]["parity_bucket_total"] == 181
    assert coverage["summary"]["parity_bucket_total"] == 181
    assert summary["summary"]["behavioral_covered_count"] == len(behavioral_uris) == len(promoted_uris)
    assert summary["summary"]["live_behavioral_covered_count"] == len(live_behavioral_uris) == len(promoted_uris)
    assert coverage["summary"]["behavioral_supported"] == len(promoted_uris)
    assert [entry["uri"] for entry in summary["entries"]] == [entry["uri"] for entry in matrix_entries] == [entry["uri"] for entry in coverage_entries]
    assert all(entry["version"] == VERSION for entry in summary["entries"])
    assert all(entry["parity_bucket"] in ALLOWED_PARITY_BUCKETS for entry in summary["entries"])
    assert all(entry["evidence_standard"] for entry in summary["entries"])


def test_2023_phase21_policy_reconciles_parity_buckets_to_reflected_apis() -> None:
    policy = json.loads(POLICY_RESOURCE.read_text(encoding="utf-8"))
    coverage_by_uri = {entry["uri"]: entry for entry in _coverage_payload()["coverage"]}
    parity_buckets = policy["policy"]["parity_buckets"]

    assert set(parity_buckets) == ALLOWED_PARITY_BUCKETS
    assert policy["summary"]["parity_bucket_total"] == 181
    assert sum(policy["summary"]["parity_bucket_counts"].values()) == 181

    assigned = [uri for uris in parity_buckets.values() for uri in uris]
    assert sorted(assigned) == sorted(coverage_by_uri)
    assert len(assigned) == len(set(assigned)) == 181
    for bucket, uris in parity_buckets.items():
        assert policy["summary"]["parity_bucket_counts"][bucket] == len(uris)
        assert all(coverage_by_uri[uri]["parity_bucket"] == bucket for uri in uris)


def test_2023_waql_matrix_is_live_tested_and_does_not_reuse_2022_evidence() -> None:
    payload = json.loads(WAQL_RESOURCE.read_text(encoding="utf-8"))
    encoded = json.dumps(payload)

    assert payload["metadata"]["wwise_version_target"] == VERSION
    assert payload["metadata"]["schema_source"] == "resources/manifest/2023.1/schemas.json#ak.wwise.core.object.get"
    assert payload["summary"]["coverage_status"] == "live-tested"
    assert payload["summary"]["live_tested_cases"] == len(payload["live_cases"]) == 8
    assert all(case["coverage_status"] == "live-tested" for case in payload["live_cases"])
    assert all(
        case["evidence_path"].startswith(".sisyphus/evidence/wwise-2023-test-parity/live-read-only/")
        for case in payload["live_cases"]
    )
    assert "resources/waql/2022.1/object-get-live-matrix.json format only" in payload["metadata"]["comparison_only_sources"]
    assert ".sisyphus/evidence/wwise-waapi-live-sandbox-coverage/waql" not in encoded


def _has_approved_promotion_evidence(entry: dict) -> bool:
    encoded = json.dumps(entry["behavioral_evidence"], sort_keys=True)
    return any(source in encoded for source in APPROVED_PROMOTION_EVIDENCE)


def _matrix_payload() -> dict:
    return json.loads(MATRIX_RESOURCE.read_text(encoding="utf-8"))


def _summary_payload() -> dict:
    return json.loads(SUMMARY_RESOURCE.read_text(encoding="utf-8"))


def _coverage_payload() -> dict:
    return json.loads(API_COVERAGE_RESOURCE.read_text(encoding="utf-8"))


def _uris(path: Path, section: str) -> list[str]:
    return [entry["uri"] for entry in json.loads(path.read_text(encoding="utf-8"))[section]]
