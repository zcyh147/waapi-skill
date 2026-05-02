from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from wwise_waapi.deferred_registry import ApiClassifier, DeferredRegistry  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION = "2021.1"
DEFERRED_RESOURCE = REPO_ROOT / "resources" / "deferred" / f"{VERSION}.json"
COVERAGE_RESOURCE = REPO_ROOT / "resources" / "coverage" / VERSION / "api-coverage.json"
FUNCTIONS_MANIFEST = REPO_ROOT / "resources" / "manifest" / VERSION / "functions.json"

REQUIRED_TASK5_FIELDS = {
    "uri",
    "family",
    "version",
    "reason",
    "blocker",
    "source_evidence_path",
    "reflection_evidence_path",
    "live_applicability",
    "destructive_applicability",
    "substitute_test",
    "date",
    "tool_version",
}
FORBIDDEN_NEWER_EVIDENCE = ("2022.1", "2023.1", "2024.1", "2025.1")


def test_2021_deferred_registry_loads_and_matches_blocked_coverage() -> None:
    registry = DeferredRegistry.load_default(VERSION)
    payload = _deferred_payload()
    coverage = _coverage_payload()["coverage"]
    reflected = {entry["uri"] for entry in _json(FUNCTIONS_MANIFEST)["functions"]}
    blocked_coverage = {entry["uri"] for entry in coverage if entry["coverage_status"] in {"deferred", "excluded"}}

    assert len(registry.entries) == 99
    assert set(registry.entries) == reflected == blocked_coverage
    assert payload["summary"]["deferred_registry_entries"] == 99
    assert payload["summary"]["classification_counts"] == {"supported": 0, "behavioral": 0, "deferred": 53, "excluded": 46}


def test_2021_deferred_entries_include_task5_evidence_contract() -> None:
    classifier = ApiClassifier()
    encoded = json.dumps(_deferred_payload())
    assert not any(f"resources/manifest/{version}" in encoded for version in FORBIDDEN_NEWER_EVIDENCE)
    assert not any(f"resources/coverage/{version}" in encoded for version in FORBIDDEN_NEWER_EVIDENCE)
    assert not any(f"resources/deferred/{version}" in encoded for version in FORBIDDEN_NEWER_EVIDENCE)

    for entry in _deferred_payload()["deferred"]:
        assert REQUIRED_TASK5_FIELDS <= set(entry), entry["uri"]
        assert entry["version"] == VERSION
        assert entry["date"] == "2026-05-02"
        assert entry["behavioral_coverage"] == "deferred"
        assert entry["inventory_coverage"] == "reflected-2021.1-schema-ok"
        assert entry["source_evidence_path"].startswith("resources/")
        assert entry["reflection_evidence_path"] == f"resources/manifest/2021.1/functions.json#{entry['uri']}"
        assert "not behavioral coverage" in entry["substitute_test"]
        assert "2021.1" in entry["tool_version"]
        assert entry["live_applicability"] == "blocked-pending-fresh-2021.1-live-evidence"
        assert entry["destructive_applicability"] in {"destructive-opt-in-required", "not-destructive-by-uri-risk"}

        expected = classifier.classify(entry["uri"], entry["item_type"])
        assert entry["category"] == expected.category
        assert entry["risk_level"] == expected.risk_level


def test_2021_deferred_entries_do_not_claim_behavior_from_skipped_live_or_destructive_tests() -> None:
    coverage_by_uri = {entry["uri"]: entry for entry in _coverage_payload()["coverage"]}

    for entry in _deferred_payload()["deferred"]:
        coverage = coverage_by_uri[entry["uri"]]
        evidence = coverage["behavioral_evidence"]
        assert evidence["counts_as_behavioral"] is False
        assert evidence["counts_as_live_behavioral"] is False
        assert coverage["deferred"]["source_evidence_path"] == entry["source_evidence_path"]
        assert coverage["deferred"]["reflection_evidence_path"] == entry["reflection_evidence_path"]
        assert coverage["deferred"]["live_applicability"] == entry["live_applicability"]
        assert coverage["deferred"]["destructive_applicability"] == entry["destructive_applicability"]
        assert "Skipped live/destructive tests are never counted" in evidence["evidence_standard"]


def _deferred_payload() -> dict[str, Any]:
    return _json(DEFERRED_RESOURCE)


def _coverage_payload() -> dict[str, Any]:
    return _json(COVERAGE_RESOURCE)


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
