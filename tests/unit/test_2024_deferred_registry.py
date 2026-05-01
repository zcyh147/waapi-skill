from __future__ import annotations

import json
from pathlib import Path

from wwise_waapi.deferred_registry import DeferredRegistry, REQUIRED_COVERAGE_FIELDS, REQUIRED_DEFERRED_FIELDS  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION = "2024.1"
DEFERRED_RESOURCE = REPO_ROOT / "resources" / "deferred" / f"{VERSION}.json"
COVERAGE_RESOURCE = REPO_ROOT / "resources" / "coverage" / VERSION / "api-coverage.json"
REQUIRED_EXCLUDED_FAMILIES = {"profiler", "transport", "soundengine", "UI", "CLI", "remote", "debug"}


def test_2024_deferred_registry_loads_and_matches_blocked_coverage() -> None:
    registry = DeferredRegistry.load_default(VERSION)
    coverage = _coverage_payload()["coverage"]
    blocked = {entry["uri"] for entry in coverage if entry["coverage_status"] in {"deferred", "excluded"}}

    assert set(registry.entries) == blocked
    assert len(registry.entries) == len(blocked) == len(coverage) == 148
    for uri, deferred in registry.entries.items():
        source = next(entry for entry in coverage if entry["uri"] == uri)
        assert deferred.version == VERSION
        assert deferred.item_type == "function"
        assert deferred.item_type == source["item_type"]
        assert deferred.category == source["category"]
        assert deferred.inventory_coverage == "reflected-manifest-only"
        assert deferred.behavioral_coverage == "deferred"
        assert source["deferred"]["evidence_source"] == deferred.evidence_source
        assert "not behavioral coverage" in deferred.substitute_test


def test_2024_deferred_resource_declares_conservative_status_model() -> None:
    payload = _deferred_payload()
    coverage = _coverage_payload()["coverage"]

    assert payload["metadata"]["version"] == VERSION
    assert payload["metadata"]["required_fields"] == list(REQUIRED_DEFERRED_FIELDS + REQUIRED_COVERAGE_FIELDS) + ["coverage_status"]
    assert payload["metadata"]["manifest_source"] == "resources/manifest/2024.1"
    assert payload["metadata"]["source_notes"] == "resources/semantic/2024.1/source_notes.json"
    assert "coverage_status" in payload["metadata"]["coverage_model"]
    assert "not behavioral coverage" in payload["metadata"]["coverage_model"]["behavioral_coverage"]
    assert {entry["coverage_status"] for entry in payload["deferred"]} == {"deferred", "excluded"}
    assert {entry["uri"] for entry in payload["deferred"]} == {entry["uri"] for entry in coverage}


def test_2024_deferred_registry_exactly_matches_deferred_and_excluded_entries() -> None:
    deferred = _deferred_payload()["deferred"]
    coverage = _coverage_payload()["coverage"]
    coverage_by_uri = {entry["uri"]: entry for entry in coverage}

    assert [entry["uri"] for entry in deferred] == [entry["uri"] for entry in coverage]
    for entry in deferred:
        source = coverage_by_uri[entry["uri"]]
        assert entry["coverage_status"] == source["coverage_status"]
        assert entry["category"] == source["category"]
        assert entry["risk_level"] == source["risk_level"]
        assert entry["version"] == VERSION
        assert "resources/manifest/2024.1" in entry["evidence_source"]
        assert "2023.1" not in entry["evidence_source"]


def test_2024_excluded_families_are_explicit_and_not_promoted() -> None:
    payload = _deferred_payload()
    families = set(payload["metadata"]["excluded_families"])
    excluded_entries = [entry for entry in payload["deferred"] if entry["coverage_status"] == "excluded"]
    excluded_family_values = {entry["excluded_family"] for entry in excluded_entries}
    excluded_categories = payload["summary"]["excluded_category_counts"]

    assert REQUIRED_EXCLUDED_FAMILIES <= families
    assert (REQUIRED_EXCLUDED_FAMILIES - {"remote"}) <= excluded_family_values
    assert any(category.startswith("core.profiler") for category in excluded_categories)
    assert any(category.startswith("core.transport") for category in excluded_categories)
    assert "soundengine" in excluded_categories
    assert "cli" in excluded_categories
    assert "debug" in excluded_categories
    assert any(category.startswith("ui") for category in excluded_categories)
    assert payload["summary"]["excluded_count"] == len(excluded_entries)
    assert payload["summary"]["status_counts"] == {"deferred": 75, "excluded": 73}


def _deferred_payload() -> dict:
    return json.loads(DEFERRED_RESOURCE.read_text(encoding="utf-8"))


def _coverage_payload() -> dict:
    return json.loads(COVERAGE_RESOURCE.read_text(encoding="utf-8"))
