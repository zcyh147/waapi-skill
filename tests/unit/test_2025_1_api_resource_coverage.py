from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from wwise_waapi.deferred_registry import ApiClassifier  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION = "2025.1"
BASELINE_VERSION = "2024.1"
FUNCTIONS_MANIFEST = REPO_ROOT / "resources" / "manifest" / VERSION / "functions.json"
COVERAGE_RESOURCE = REPO_ROOT / "resources" / "coverage" / VERSION / "api-coverage.json"
CLASSIFICATION_RESOURCE = REPO_ROOT / "resources" / "coverage" / VERSION / "added-api-classification.json"
SOURCE_NOTES_RESOURCE = REPO_ROOT / "resources" / "semantic" / VERSION / "source_notes.json"
BASELINE_COVERAGE_RESOURCE = REPO_ROOT / "resources" / "coverage" / BASELINE_VERSION / "api-coverage.json"

ALLOWED_STATUSES = {"deferred", "excluded", "live-tested", "sandbox-mutating-tested"}
ALLOWED_BLOCKED_STATUSES = {"deferred", "excluded"}
FORBIDDEN_PROMOTED_STATUSES = {"live-tested", "sandbox-mutating-tested"}
CANDIDATE_STATUSES = {"candidate-live-read-only", "candidate-sandbox-mutating"}


def test_2025_resource_covers_every_reflected_function_once_with_2025_paths() -> None:
    reflected = sorted(_uris(FUNCTIONS_MANIFEST, "functions"))
    payload = _coverage_payload()
    coverage = payload["coverage"]
    encoded = json.dumps(payload)

    assert len(reflected) == 154
    assert len(coverage) == 154
    assert [entry["uri"] for entry in coverage] == reflected
    assert len({entry["uri"] for entry in coverage}) == len(coverage)
    assert payload["metadata"]["version"] == VERSION
    assert payload["metadata"]["manifest_source"] == "resources/manifest/2025.1"
    assert "resources/manifest/2025/" not in encoded
    assert "resources/coverage/2025/" not in encoded
    assert "resources/manifest/2022.1" not in encoded
    assert "resources/manifest/2023.1" not in encoded


def test_2025_coverage_entries_are_blocked_until_fresh_2025_evidence_exists() -> None:
    classifier = ApiClassifier()

    for entry in _coverage_payload()["coverage"]:
        expected = classifier.classify(entry["uri"], entry["item_type"])
        evidence = entry["behavioral_evidence"]

        assert entry["version"] == VERSION
        assert entry["item_type"] == "function"
        assert entry["category"] == expected.category
        assert entry["risk_level"] == expected.risk_level
        assert entry["schema_status"] == "ok", entry["uri"]
        assert entry["schema_mapping"]["manifest_uri"] == f"resources/manifest/2025.1/schemas.json#{entry['uri']}"
        assert entry["coverage_status"] in ALLOWED_BLOCKED_STATUSES, entry["uri"]
        assert entry["test_status"] == entry["coverage_status"], entry["uri"]
        assert entry["parity_bucket"] == entry["coverage_status"], entry["uri"]
        assert entry["deferred"]["status"] is True, entry["uri"]
        assert entry["deferred"]["coverage_status"] == entry["coverage_status"], entry["uri"]
        assert evidence["coverage"] == entry["coverage_status"]
        assert evidence["parity_bucket"] == entry["parity_bucket"]
        assert evidence["manifest_reflection_only"] is True
        assert evidence["counts_as_behavioral"] is False
        assert evidence["counts_as_live_behavioral"] is False
        assert "2024 evidence" in evidence["evidence_standard"]
        assert entry["coverage_status"] not in FORBIDDEN_PROMOTED_STATUSES, entry["uri"]


def test_2025_task6_classifications_remain_planning_only_in_coverage() -> None:
    coverage_by_uri = {entry["uri"]: entry for entry in _coverage_payload()["coverage"]}
    classifications = [entry for entry in _classification_payload()["classifications"] if entry["item_type"] == "function"]

    assert classifications
    for classification in classifications:
        entry = coverage_by_uri[classification["uri"]]
        assert entry["task6_classification_status"] == classification["status"], entry["uri"]
        assert entry["behavioral_evidence"]["counts_as_behavioral"] is False, entry["uri"]
        if classification["status"] in CANDIDATE_STATUSES:
            assert entry["coverage_status"] == "deferred", entry["uri"]
            assert entry["candidate_status"] == classification["status"], entry["uri"]
            assert entry["behavioral_evidence"]["candidate_origin"] == "task6-classification", entry["uri"]
        elif classification["status"] == "excluded":
            assert entry["coverage_status"] == "excluded", entry["uri"]
        else:
            assert entry["coverage_status"] == "deferred", entry["uri"]


def test_2025_status_totals_record_zero_accidental_promotion_and_2024_comparison() -> None:
    payload = _coverage_payload()
    coverage = payload["coverage"]
    status_counts = payload["summary"]["status_counts"]
    parity_counts = payload["summary"]["parity_bucket_counts"]
    baseline = payload["metadata"]["baseline_comparison"]

    assert set(payload["metadata"]["status_model"]) == ALLOWED_STATUSES
    assert set(status_counts) == ALLOWED_STATUSES
    assert status_counts == _counts_with_zeroes(Counter(entry["coverage_status"] for entry in coverage), status_counts)
    assert parity_counts == _counts_with_zeroes(Counter(entry["parity_bucket"] for entry in coverage), parity_counts)
    assert sum(status_counts.values()) == len(coverage) == 154
    assert payload["summary"]["total_functions"] == 154
    assert payload["summary"]["implemented"] == 154
    assert payload["summary"]["manifest_only"] == 154
    assert payload["summary"]["behavioral_supported"] == 0
    assert payload["summary"]["live_tested"] == 0
    assert status_counts["live-tested"] == 0
    assert status_counts["sandbox-mutating-tested"] == 0
    assert parity_counts["live-tested"] == 0
    assert parity_counts["sandbox-mutating-tested"] == 0
    assert baseline["baseline_version"] == BASELINE_VERSION
    assert baseline["baseline_reflected_count"] == len(_baseline_payload()["coverage"]) == 148
    assert baseline["common_function_count"] == len({entry["uri"] for entry in coverage} & {entry["uri"] for entry in _baseline_payload()["coverage"]})
    assert baseline["policy"] == "2024.1 evidence is comparison metadata only and never counts as 2025.1 proof."


def test_2025_source_notes_are_context_not_behavior_proof() -> None:
    source_notes = _source_notes_payload()["notes"]
    source_uris = {uri for note in source_notes.values() for uri in note["endpoints"]}
    coverage_by_uri = {entry["uri"]: entry for entry in _coverage_payload()["coverage"]}
    covered_source_uris = source_uris & set(coverage_by_uri)

    assert covered_source_uris
    for uri in covered_source_uris:
        entry = coverage_by_uri[uri]
        assert entry["source_note_family"] in source_notes, uri
        assert entry["behavioral_evidence"]["source_note_family"] == entry["source_note_family"], uri
        assert entry["coverage_status"] in ALLOWED_BLOCKED_STATUSES, uri
        assert entry["behavioral_evidence"]["counts_as_behavioral"] is False, uri


def test_2025_does_not_reuse_2024_live_or_sandbox_proof() -> None:
    baseline_by_uri = {entry["uri"]: entry for entry in _baseline_payload()["coverage"]}
    coverage_by_uri = {entry["uri"]: entry for entry in _coverage_payload()["coverage"]}
    previously_promoted = {
        uri: entry["coverage_status"]
        for uri, entry in baseline_by_uri.items()
        if entry["coverage_status"] in FORBIDDEN_PROMOTED_STATUSES and uri in coverage_by_uri
    }

    assert previously_promoted
    for uri, previous_status in previously_promoted.items():
        entry = coverage_by_uri[uri]
        assert entry["previous_2024_status"] == previous_status, uri
        assert entry["coverage_status"] in ALLOWED_BLOCKED_STATUSES, uri
        assert entry["candidate_status"] in CANDIDATE_STATUSES, uri
        assert entry["behavioral_evidence"]["candidate_origin"] in {
            "2024-baseline-comparison-only",
            "task6-classification",
        }, uri
        assert entry["behavioral_evidence"]["counts_as_behavioral"] is False, uri


def _coverage_payload() -> dict[str, Any]:
    return json.loads(COVERAGE_RESOURCE.read_text(encoding="utf-8"))


def _classification_payload() -> dict[str, Any]:
    return json.loads(CLASSIFICATION_RESOURCE.read_text(encoding="utf-8"))


def _source_notes_payload() -> dict[str, Any]:
    return json.loads(SOURCE_NOTES_RESOURCE.read_text(encoding="utf-8"))


def _baseline_payload() -> dict[str, Any]:
    return json.loads(BASELINE_COVERAGE_RESOURCE.read_text(encoding="utf-8"))


def _uris(path: Path, section: str) -> list[str]:
    return [entry["uri"] for entry in json.loads(path.read_text(encoding="utf-8"))[section]]


def _counts_with_zeroes(counts: Counter[str], summary_counts: dict[str, int]) -> dict[str, int]:
    return {key: counts.get(key, 0) for key in summary_counts}
