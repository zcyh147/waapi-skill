from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from wwise_waapi.deferred_registry import DeferredRegistry, REQUIRED_COVERAGE_FIELDS, REQUIRED_DEFERRED_FIELDS  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION = "2025.1"
DEFERRED_RESOURCE = REPO_ROOT / "resources" / "deferred" / f"{VERSION}.json"
COVERAGE_RESOURCE = REPO_ROOT / "resources" / "coverage" / VERSION / "api-coverage.json"

FORBIDDEN_PROMOTED_STATUSES = {"live-tested", "sandbox-mutating-tested"}
REQUIRED_EXCLUDED_FAMILIES = {"CLI", "UI", "debug", "remote", "soundengine"}


def test_2025_deferred_registry_loads_and_matches_all_blocked_coverage() -> None:
    registry = DeferredRegistry.load_default(VERSION)
    coverage = _coverage_payload()["coverage"]
    blocked = {entry["uri"] for entry in coverage if entry["coverage_status"] in {"deferred", "excluded"}}

    assert set(registry.entries) == blocked
    assert len(registry.entries) == len(blocked) == 154
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


def test_2025_deferred_resource_declares_shape_and_forbidden_promotions() -> None:
    payload = _deferred_payload()
    coverage = _coverage_payload()["coverage"]

    assert payload["metadata"]["version"] == VERSION
    assert payload["metadata"]["required_fields"] == list(REQUIRED_DEFERRED_FIELDS + REQUIRED_COVERAGE_FIELDS) + ["coverage_status"]
    assert payload["metadata"]["manifest_source"] == "resources/manifest/2025.1"
    assert payload["metadata"]["source_notes"] == "resources/semantic/2025.1/source_notes.json"
    assert payload["metadata"]["task6_classification"] == "resources/coverage/2025.1/added-api-classification.json"
    assert set(payload["metadata"]["coverage_model"]["coverage_status"]) == {"deferred", "excluded"}
    assert set(payload["metadata"]["coverage_model"]["forbidden_promoted_statuses"]) == FORBIDDEN_PROMOTED_STATUSES
    assert {entry["coverage_status"] for entry in payload["deferred"]} == {"deferred", "excluded"}
    assert {entry["uri"] for entry in payload["deferred"]} == {entry["uri"] for entry in coverage}
    assert not any(entry["coverage_status"] in FORBIDDEN_PROMOTED_STATUSES for entry in payload["deferred"])


def test_2025_deferred_registry_exactly_matches_coverage_entries() -> None:
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
        assert "resources/manifest/2025.1" in entry["evidence_source"]
        assert "2024.1" not in entry["evidence_source"]


def test_2025_deferred_summary_reconciles_deferred_and_excluded_counts() -> None:
    payload = _deferred_payload()
    deferred_entries = [entry for entry in payload["deferred"] if entry["coverage_status"] == "deferred"]
    excluded_entries = [entry for entry in payload["deferred"] if entry["coverage_status"] == "excluded"]
    status_counts = dict(sorted(Counter(entry["coverage_status"] for entry in payload["deferred"]).items()))

    assert payload["summary"]["total"] == 154
    assert payload["summary"]["deferred_count"] == len(deferred_entries)
    assert payload["summary"]["excluded_count"] == len(excluded_entries)
    assert payload["summary"]["status_counts"] == status_counts
    assert status_counts["deferred"] + status_counts["excluded"] == 154
    assert payload["metadata"]["baseline_comparison"]["policy"] == "2024.1 evidence is comparison metadata only and never counts as 2025.1 proof."


def test_2025_excluded_families_follow_policy_names() -> None:
    payload = _deferred_payload()
    excluded_entries = [entry for entry in payload["deferred"] if entry["coverage_status"] == "excluded"]
    excluded_family_values = {entry["excluded_family"] for entry in excluded_entries}

    assert REQUIRED_EXCLUDED_FAMILIES <= set(payload["metadata"]["excluded_families"])
    assert excluded_family_values <= REQUIRED_EXCLUDED_FAMILIES
    assert "cli" not in excluded_family_values
    assert "CLI" in excluded_family_values


def _deferred_payload() -> dict:
    return json.loads(DEFERRED_RESOURCE.read_text(encoding="utf-8"))


def _coverage_payload() -> dict:
    return json.loads(COVERAGE_RESOURCE.read_text(encoding="utf-8"))
