from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from wwise_waapi.deferred_registry import ApiClassifier  # pyright: ignore[reportMissingImports]
from wwise_waapi.manifest import ManifestStore  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION = "2023.1"
MANIFEST_ROOT = REPO_ROOT / "resources" / "manifest"
COVERAGE_RESOURCE = REPO_ROOT / "resources" / "coverage" / VERSION / "api-coverage.json"
ALLOWED_STATUSES = {"supported", "deferred", "excluded", "untested", "evidence-only", "live-tested"}
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
EXCLUDED_CATEGORY_PREFIXES = (
    "soundengine",
    "core.profiler",
    "core.transport",
    "ui",
    "cli",
    "core.remote",
    "debug",
)


def test_2023_resource_covers_every_reflected_api_once_with_2023_paths() -> None:
    manifest = ManifestStore(root=MANIFEST_ROOT).load(VERSION)
    payload = _coverage_payload()
    reflected = sorted(entry["uri"] for entry in manifest["functions"] + manifest["topics"])
    coverage = payload["coverage"]

    assert len(manifest["functions"]) == 149
    assert len(manifest["topics"]) == 32
    assert len(coverage) == 181
    assert [entry["uri"] for entry in coverage] == reflected
    assert len({entry["uri"] for entry in coverage}) == len(coverage)
    assert payload["metadata"]["version"] == VERSION
    assert payload["metadata"]["manifest_source"] == "resources/manifest/2023.1"
    assert "resources/coverage/2022.1" not in json.dumps(payload)
    assert "resources/deferred/2022.1" not in json.dumps(payload)


def test_2023_coverage_entries_have_required_versioned_metadata() -> None:
    classifier = ApiClassifier()

    for entry in _coverage_payload()["coverage"]:
        assert entry["version"] == VERSION
        assert entry["coverage_status"] in ALLOWED_STATUSES, entry["uri"]
        assert entry["test_status"] == entry["coverage_status"], entry["uri"]
        assert entry["schema_status"] == "ok", entry["uri"]
        assert entry["schema_mapping"]["manifest_uri"] == f"resources/manifest/2023.1/schemas.json#{entry['uri']}"
        expected = classifier.classify(entry["uri"], entry["item_type"])
        assert entry["category"] == expected.category
        assert entry["risk_level"] == expected.risk_level
        assert entry["behavioral_evidence"]["coverage"] == entry["coverage_status"]
        assert entry["parity_bucket"] in ALLOWED_PARITY_BUCKETS, entry["uri"]
        assert entry["evidence_standard"], entry["uri"]
        assert entry["behavioral_evidence"]["parity_bucket"] == entry["parity_bucket"], entry["uri"]
        assert entry["behavioral_evidence"]["evidence_standard"] == entry["evidence_standard"], entry["uri"]
        assert entry["behavioral_evidence"]["counts_as_behavioral"] is False
        assert entry["behavioral_evidence"]["counts_as_live_behavioral"] is False


def test_2023_coverage_statuses_are_not_manifest_only_claims() -> None:
    payload = _coverage_payload()
    status_model = payload["metadata"]["status_model"]
    status_counts = payload["summary"]["status_counts"]

    parity_counts = payload["summary"]["parity_bucket_counts"]

    assert set(status_model) == ALLOWED_STATUSES
    assert set(status_counts) <= ALLOWED_STATUSES
    assert set(payload["metadata"]["parity_bucket_model"]) == ALLOWED_PARITY_BUCKETS
    assert set(parity_counts) == ALLOWED_PARITY_BUCKETS
    assert sum(parity_counts.values()) == len(payload["coverage"]) == 181
    assert status_counts["supported"] > 0
    assert status_counts["deferred"] > 0
    assert status_counts["excluded"] > 0
    assert status_counts["untested"] > 0
    assert status_counts["evidence-only"] > 0
    assert payload["summary"]["live_tested"] == 0
    assert payload["summary"]["behavioral_supported"] == 0

    for entry in payload["coverage"]:
        evidence = entry["behavioral_evidence"]
        if evidence.get("manifest_reflection_only") is True:
            assert entry["coverage_status"] != "supported", entry["uri"]
            assert entry["coverage_status"] != "live-tested", entry["uri"]
            assert evidence["counts_as_behavioral"] is False, entry["uri"]
        if entry["coverage_status"] == "supported":
            assert "no 2023.1 behavioral execution is claimed" in evidence["evidence"], entry["uri"]
            assert evidence["counts_as_behavioral"] is False, entry["uri"]


def test_2023_excluded_families_are_not_semantic_builder_support() -> None:
    for entry in _coverage_payload()["coverage"]:
        if _is_excluded_category(entry["category"]):
            assert entry["coverage_status"] == "excluded", entry["uri"]
            assert entry["deferred"]["status"] is True, entry["uri"]
            assert "excluded" in entry["deferred"]["blocking_condition"], entry["uri"]


def _coverage_payload() -> dict[str, Any]:
    return json.loads(COVERAGE_RESOURCE.read_text(encoding="utf-8"))


def _is_excluded_category(category: str) -> bool:
    return any(category == prefix or category.startswith(prefix + ".") for prefix in EXCLUDED_CATEGORY_PREFIXES)


def _by_uri(entries: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {entry["uri"]: entry for entry in entries}
