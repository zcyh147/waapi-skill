from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from wwise_waapi.api_coverage import ApiCoverageBuilder  # pyright: ignore[reportMissingImports]
from wwise_waapi.deferred_registry import ApiClassifier  # pyright: ignore[reportMissingImports]
from wwise_waapi.manifest import ManifestStore  # pyright: ignore[reportMissingImports]
from wwise_waapi.waql import WAQL_API_URI  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT
MANIFEST_ROOT = SKILL_ROOT / "resources" / "manifest"
COVERAGE_RESOURCE = SKILL_ROOT / "resources" / "coverage" / "2022.1" / "api-coverage.json"
EVIDENCE_SUMMARY = REPO_ROOT / ".sisyphus" / "evidence" / "task-7-api-coverage-summary.json"
REQUIRED_ENTRY_FIELDS = {
    "uri",
    "version",
    "item_type",
    "category",
    "risk_level",
    "schema_status",
    "schema_mapping",
    "route",
    "safety",
    "test_status",
    "deferred",
    "behavioral_evidence",
    "usage_guidance",
}


def test_generated_coverage_resource_represents_every_reflected_2022_api_once() -> None:
    manifest = ManifestStore(root=MANIFEST_ROOT).load("2022.1")
    payload = _coverage_payload()
    coverage = payload["coverage"]
    reflected_functions = [entry["uri"] for entry in manifest["functions"]]
    reflected_topics = [entry["uri"] for entry in manifest["topics"]]
    reflected = sorted(reflected_functions + reflected_topics)

    assert len(reflected_functions) == 112
    assert len(reflected_topics) == 32
    assert [entry["uri"] for entry in coverage] == reflected
    assert len(coverage) == 144
    assert len({entry["uri"] for entry in coverage}) == 144


def test_coverage_entries_have_required_metadata_schema_route_safety_and_guidance() -> None:
    payload = _coverage_payload()
    classifier = ApiClassifier()

    for entry in payload["coverage"]:
        assert REQUIRED_ENTRY_FIELDS <= set(entry), entry["uri"]
        assert entry["version"] == "2022.1"
        assert entry["schema_status"] == "ok"
        assert entry["schema_mapping"]["manifest_uri"].endswith(f"#{entry['uri']}")
        assert {"args", "options", "result"} <= set(entry["schema_mapping"]["sections"])
        assert entry["route"]["dispatcher"] == "WwiseDispatcher.dispatch"
        assert entry["route"]["target"] in {"WwiseDispatcher.dispatch", "SubscriptionManager.wait_for_event"}
        assert isinstance(entry["safety"]["deterministic_default"], bool)
        assert entry["behavioral_evidence"]["test"].startswith("tests/unit/")
        assert entry["usage_guidance"]["default_path"]
        expected = classifier.classify(entry["uri"], entry["item_type"])
        assert entry["category"] == expected.category
        assert entry["risk_level"] == expected.risk_level


def test_safe_and_deferred_entries_use_distinct_evidence_models() -> None:
    payload = _coverage_payload()
    safe = [entry for entry in payload["coverage"] if entry["deferred"]["status"] is False]
    deferred = [entry for entry in payload["coverage"] if entry["deferred"]["status"] is True]

    assert safe, "At least one deterministic fake-route API should be safe-tested"
    assert deferred, "Unsafe/UI/sound-engine/topic APIs should remain deferred"
    assert all(entry["test_status"] == "fake-route-tested" for entry in safe)
    assert all(entry["behavioral_evidence"]["coverage"].startswith("fake-route-tested") for entry in safe)
    assert all(entry["test_status"] == "deferred-with-substitute-test" for entry in deferred)
    assert all(entry["deferred"]["behavioral_coverage"] == "deferred" for entry in deferred)
    assert any(entry["uri"].startswith("ak.soundengine.") for entry in deferred)
    assert any(entry["item_type"] == "topic" for entry in deferred)


def test_waql_coverage_references_source_grounded_reference_and_gate() -> None:
    entry = _coverage_by_uri()[WAQL_API_URI]

    assert entry["deferred"]["status"] is False
    assert entry["usage_guidance"]["waql_reference"] == "references/waql-2022.1.md"
    assert entry["usage_guidance"]["waql_gate"] == "wwise_waapi.waql.require_waql_helper_generation"
    assert entry["behavioral_evidence"]["evidence"] == "references/waql-2022.1.md"


def test_evidence_summary_counts_match_generated_resource() -> None:
    payload = _coverage_payload()
    summary = json.loads(EVIDENCE_SUMMARY.read_text(encoding="utf-8"))
    coverage = payload["coverage"]

    assert summary == payload["summary"]
    assert summary["total_functions"] == 112
    assert summary["total_topics"] == 32
    assert summary["implemented"] == len(coverage) == 144
    assert summary["safe_tested"] == sum(1 for entry in coverage if entry["test_status"] == "fake-route-tested")
    assert summary["deferred"] == sum(1 for entry in coverage if entry["deferred"]["status"] is True)
    assert summary["live_tested"] == 0
    assert summary["destructive_opt_in"] == sum(1 for entry in coverage if entry["destructive_opt_in"] is True)


def test_builder_fails_on_artificial_missing_api_instead_of_silent_skip() -> None:
    manifest = ManifestStore(root=MANIFEST_ROOT).load("2022.1")
    reflected = dict(manifest)
    reflected["functions"] = [*manifest["functions"], {"uri": "ak.wwise.core.artificialMissing"}]
    store = ManifestStore()
    store.record("2022.1", reflected)
    builder = ApiCoverageBuilder(manifest_store=store)

    try:
        builder.build("2022.1")
    except KeyError as exc:
        assert "ak.wwise.core.artificialMissing" in str(exc)
    else:  # pragma: no cover - explicit failure path for silent skips
        raise AssertionError("Artificial API was silently accepted without implementation or deferred evidence")


def _coverage_payload() -> dict[str, Any]:
    return json.loads(COVERAGE_RESOURCE.read_text(encoding="utf-8"))


def _coverage_by_uri() -> dict[str, Mapping[str, Any]]:
    return {entry["uri"]: entry for entry in _coverage_payload()["coverage"]}
