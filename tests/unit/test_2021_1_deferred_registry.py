from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from wwise_waapi.deferred_registry import ApiClassifier, DeferredRegistry  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION = "2021.1"
DEFERRED_RESOURCE = REPO_ROOT / "skills" / "wwise-waapi" / "resources" / "deferred" / f"{VERSION}.json"
COVERAGE_RESOURCE = REPO_ROOT / "skills" / "wwise-waapi" / "resources" / "capabilities" / VERSION / "api-coverage.json"
FUNCTIONS_MANIFEST = REPO_ROOT / "skills" / "wwise-waapi" / "resources" / "manifest" / VERSION / "functions.json"
TOPICS_MANIFEST = REPO_ROOT / "skills" / "wwise-waapi" / "resources" / "manifest" / VERSION / "topics.json"

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
LIVE_TESTED_OBJECT_GET = "ak.wwise.core.object.get"
SANDBOX_MUTATING_TESTED_URIS = {
    "ak.wwise.core.audio.import",
    "ak.wwise.core.object.create",
    "ak.wwise.core.object.delete",
    "ak.wwise.core.object.setNotes",
    "ak.wwise.core.soundbank.setInclusions",
    "ak.wwise.core.switchContainer.addAssignment",
    "ak.wwise.core.switchContainer.removeAssignment",
    "ak.wwise.core.undo.beginGroup",
    "ak.wwise.core.undo.endGroup",
}


def test_2021_deferred_registry_loads_and_matches_blocked_coverage() -> None:
    registry = DeferredRegistry.load_default(VERSION)
    payload = _deferred_payload()
    coverage = _coverage_payload()["coverage"]
    reflected = {entry["uri"] for entry in _json(FUNCTIONS_MANIFEST)["functions"]}
    reflected_topics = {entry["uri"] for entry in _json(TOPICS_MANIFEST)["topics"]}
    blocked_function_coverage = {
        entry["uri"]
        for entry in coverage
        if entry["item_type"] == "function" and entry["coverage_status"] in {"deferred", "excluded"}
    }
    blocked_topic_coverage = {
        entry["uri"]
        for entry in coverage
        if entry["item_type"] == "topic" and entry["coverage_status"] in {"deferred", "excluded"}
    }

    assert len(registry.entries) == 89
    assert set(registry.entries) == blocked_function_coverage == reflected - {LIVE_TESTED_OBJECT_GET} - SANDBOX_MUTATING_TESTED_URIS
    assert blocked_topic_coverage == reflected_topics
    assert payload["summary"]["deferred_registry_entries"] == 89
    assert payload["summary"]["classification_counts"] == {
        "supported": 0,
        "behavioral": 0,
        "deferred": 43,
        "excluded": 46,
        "live-tested": 1,
        "sandbox-mutating-tested": 9,
    }
    assert LIVE_TESTED_OBJECT_GET not in registry.entries
    assert not (SANDBOX_MUTATING_TESTED_URIS & set(registry.entries))
    assert not (reflected_topics & set(registry.entries))


def test_2021_topic_inventory_rows_are_deferred_and_non_behavioral() -> None:
    coverage = _coverage_payload()["coverage"]
    reflected_topics = {entry["uri"] for entry in _json(TOPICS_MANIFEST)["topics"]}
    topic_entries = [entry for entry in coverage if entry["item_type"] == "topic"]

    assert {entry["uri"] for entry in topic_entries} == reflected_topics
    assert len(topic_entries) == 27
    for entry in topic_entries:
        evidence = entry["behavioral_evidence"]
        assert entry["coverage_status"] == "deferred", entry["uri"]
        assert entry["parity_bucket"] == "deferred", entry["uri"]
        assert evidence["counts_as_behavioral"] is False, entry["uri"]
        assert evidence["counts_as_live_behavioral"] is False, entry["uri"]
        assert "not behavioral coverage" in entry["deferred"]["substitute_test"], entry["uri"]


def test_2021_deferred_entries_include_task5_evidence_contract() -> None:
    classifier = ApiClassifier()
    encoded = json.dumps(_deferred_payload())
    assert not any(f"resources/manifest/{version}" in encoded for version in FORBIDDEN_NEWER_EVIDENCE)
    assert not any(f"resources/capabilities/{version}" in encoded for version in FORBIDDEN_NEWER_EVIDENCE)
    assert not any(f"resources/deferred/{version}" in encoded for version in FORBIDDEN_NEWER_EVIDENCE)

    for entry in _deferred_payload()["deferred"]:
        assert REQUIRED_TASK5_FIELDS <= set(entry), entry["uri"]
        assert entry["version"] == VERSION
        assert entry["date"] == "2026-05-02"
        assert entry["behavioral_coverage"] == "deferred"
        assert entry["inventory_coverage"] == "reflected-2021.1-schema-ok"
        if entry["source_evidence_path"].startswith("not-applicable:"):
            assert entry["evidence_source"] == entry["reflection_evidence_path"], entry["uri"]
        else:
            assert entry["source_evidence_path"].startswith("resources/semantic/2021.1/source_notes.json#"), entry["uri"]
            assert entry["source_evidence_path"] in entry["evidence_source"], entry["uri"]
        assert entry["reflection_evidence_path"] == f"resources/manifest/2021.1/functions.json#{entry['uri']}"
        assert len(entry["evidence_source"].split(" + ")) == len(set(entry["evidence_source"].split(" + "))), entry["uri"]
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
