from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION = "2023.1"
MATRIX_RESOURCE = REPO_ROOT / "resources" / "coverage" / VERSION / "live-coverage-matrix.json"
SUMMARY_RESOURCE = REPO_ROOT / "resources" / "coverage" / VERSION / "phase2-coverage-summary.json"
API_COVERAGE_RESOURCE = REPO_ROOT / "resources" / "coverage" / VERSION / "api-coverage.json"
WAQL_RESOURCE = REPO_ROOT / "resources" / "waql" / VERSION / "object-get-live-matrix.json"
FUNCTIONS_MANIFEST = REPO_ROOT / "resources" / "manifest" / VERSION / "functions.json"
TOPICS_MANIFEST = REPO_ROOT / "resources" / "manifest" / VERSION / "topics.json"


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

    assert matrix_payload["summary"]["live_tested"] == 0
    assert "manifest reflection alone is never behavioral support" in matrix_payload["metadata"]["status_policy"]
    for entry in matrix_payload["matrix"]:
        source = coverage_by_uri[entry["uri"]]
        assert entry["coverage_status"] == source["coverage_status"], entry["uri"]
        assert entry["counts_as_behavioral"] is False, entry["uri"]
        assert entry["counts_as_live_behavioral"] is False, entry["uri"]
        assert entry["achieved_status"] != "live-tested", entry["uri"]
        assert entry["manifest_source_uri"].startswith("resources/manifest/2023.1/"), entry["uri"]


def test_2023_phase2_summary_matches_matrix_without_behavioral_overclaim() -> None:
    summary = _summary_payload()
    matrix = _matrix_payload()

    assert summary["metadata"]["baseline_resource"] == "resources/coverage/2023.1/api-coverage.json"
    assert summary["metadata"]["live_matrix_resource"] == "resources/coverage/2023.1/live-coverage-matrix.json"
    assert summary["summary"]["status_counts"] == matrix["summary"]["status_counts"]
    assert summary["summary"]["behavioral_covered_count"] == 0
    assert summary["summary"]["live_behavioral_covered_count"] == 0
    assert all(entry["version"] == VERSION for entry in summary["entries"])


def test_2023_waql_matrix_is_evidence_only_and_does_not_reuse_2022_evidence() -> None:
    payload = json.loads(WAQL_RESOURCE.read_text(encoding="utf-8"))
    encoded = json.dumps(payload)

    assert payload["metadata"]["wwise_version_target"] == VERSION
    assert payload["metadata"]["schema_source"] == "resources/manifest/2023.1/schemas.json#ak.wwise.core.object.get"
    assert payload["summary"]["coverage_status"] == "evidence-only"
    assert payload["summary"]["live_tested_cases"] == 0
    assert all(case["coverage_status"] == "evidence-only" for case in payload["live_cases"])
    assert all(case["evidence_path"] == "" for case in payload["live_cases"])
    assert "resources/waql/2022.1/object-get-live-matrix.json format only" in payload["metadata"]["comparison_only_sources"]
    assert ".sisyphus/evidence/wwise-waapi-live-sandbox-coverage/waql" not in encoded


def _matrix_payload() -> dict:
    return json.loads(MATRIX_RESOURCE.read_text(encoding="utf-8"))


def _summary_payload() -> dict:
    return json.loads(SUMMARY_RESOURCE.read_text(encoding="utf-8"))


def _coverage_payload() -> dict:
    return json.loads(API_COVERAGE_RESOURCE.read_text(encoding="utf-8"))


def _uris(path: Path, section: str) -> list[str]:
    return [entry["uri"] for entry in json.loads(path.read_text(encoding="utf-8"))[section]]
