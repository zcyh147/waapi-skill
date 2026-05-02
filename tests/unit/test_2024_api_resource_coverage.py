from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from wwise_waapi.deferred_registry import ApiClassifier  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION = "2024.1"
FUNCTIONS_MANIFEST = REPO_ROOT / "resources" / "manifest" / VERSION / "functions.json"
TOPICS_MANIFEST = REPO_ROOT / "resources" / "manifest" / VERSION / "topics.json"
COVERAGE_RESOURCE = REPO_ROOT / "resources" / "coverage" / VERSION / "api-coverage.json"
SOURCE_NOTES_RESOURCE = REPO_ROOT / "resources" / "semantic" / VERSION / "source_notes.json"
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
ALLOWED_STATUSES = {"deferred", "excluded", "live-tested", "sandbox-mutating-tested"}
ALLOWED_PARITY_BUCKETS = {"manifest-only", "deferred", "excluded", "live-tested", "sandbox-mutating-tested"}
RISKY_CATEGORY_PREFIXES = (
    "soundengine",
    "core.profiler",
    "core.transport",
    "ui",
    "cli",
    "core.remote",
    "debug",
)


def test_2024_resource_covers_every_reflected_function_and_topic_once_with_2024_paths() -> None:
    reflected = sorted(_uris(FUNCTIONS_MANIFEST, "functions") + _uris(TOPICS_MANIFEST, "topics"))
    payload = _coverage_payload()
    coverage = payload["coverage"]
    encoded = json.dumps(payload)

    assert len(_uris(FUNCTIONS_MANIFEST, "functions")) == 148
    assert len(_uris(TOPICS_MANIFEST, "topics")) == 30
    assert len(reflected) == 178
    assert len(coverage) == 178
    assert [entry["uri"] for entry in coverage] == reflected
    assert len({entry["uri"] for entry in coverage}) == len(coverage)
    assert payload["metadata"]["version"] == VERSION
    assert payload["metadata"]["manifest_source"] == "resources/manifest/2024.1"
    assert "resources/manifest/2024/" not in encoded
    assert "resources/coverage/2024/" not in encoded
    assert "resources/manifest/2022.1" not in encoded
    assert "resources/manifest/2023.1" not in encoded
    assert "resources/manifest/2025" not in encoded


def test_2024_coverage_entries_have_required_versioned_metadata() -> None:
    classifier = ApiClassifier()

    for entry in _coverage_payload()["coverage"]:
        expected = classifier.classify(entry["uri"], entry["item_type"])
        evidence = entry["behavioral_evidence"]

        assert entry["version"] == VERSION
        assert entry["item_type"] in {"function", "topic"}
        assert entry["coverage_status"] in ALLOWED_STATUSES, entry["uri"]
        assert entry["test_status"] == entry["coverage_status"], entry["uri"]
        assert entry["schema_status"] == "ok", entry["uri"]
        assert entry["schema_mapping"]["manifest_uri"] == f"resources/manifest/2024.1/schemas.json#{entry['uri']}"
        assert entry["category"] == expected.category
        assert entry["risk_level"] == expected.risk_level
        assert entry["parity_bucket"] == entry["coverage_status"]
        assert entry["parity_bucket"] in ALLOWED_PARITY_BUCKETS, entry["uri"]
        assert entry["deferred"]["coverage_status"] == entry["coverage_status"]
        assert evidence["coverage"] == entry["coverage_status"]
        assert evidence["parity_bucket"] == entry["parity_bucket"]

        if entry["uri"] in PROMOTED_READ_ONLY_URIS:
            assert entry["coverage_status"] == "live-tested"
            assert entry["deferred"]["status"] is False
            assert evidence["manifest_reflection_only"] is False
            assert evidence["counts_as_behavioral"] is True
            assert evidence["counts_as_live_behavioral"] is True
            assert evidence["evidence_path"] == "resources/waql/2024.1/object-get-live-matrix.json"
            assert ".sisyphus/evidence/wwise-2024-waapi-integration-coverage/" in json.dumps(evidence)
        elif entry["uri"] in SANDBOX_MUTATING_TESTED_URIS:
            assert entry["coverage_status"] == "sandbox-mutating-tested"
            assert entry["deferred"]["status"] is False
            assert evidence["manifest_reflection_only"] is False
            assert evidence["counts_as_behavioral"] is True
            assert evidence["counts_as_live_behavioral"] is True
            assert evidence["evidence_path"] == ".sisyphus/evidence/task-2024-10-destructive-sandbox.txt"
            assert evidence["destructive_case_evidence"].startswith(
                ".sisyphus/evidence/wwise-2024-waapi-integration-coverage/destructive/"
            )
        else:
            assert entry["coverage_status"] in {"deferred", "excluded"}, entry["uri"]
            assert entry["deferred"]["status"] is True
            assert evidence["manifest_reflection_only"] is True
            assert evidence["counts_as_behavioral"] is False
            assert evidence["counts_as_live_behavioral"] is False
            assert "behavioral proof" in evidence["evidence_standard"]


def test_2024_statuses_promote_only_fresh_2024_live_and_destructive_evidence() -> None:
    payload = _coverage_payload()
    coverage = payload["coverage"]
    status_counts = payload["summary"]["status_counts"]
    parity_counts = payload["summary"]["parity_bucket_counts"]
    live_promoted = {entry["uri"] for entry in coverage if entry["coverage_status"] == "live-tested"}
    sandbox_promoted = {entry["uri"] for entry in coverage if entry["coverage_status"] == "sandbox-mutating-tested"}

    assert set(payload["metadata"]["status_model"]) == ALLOWED_STATUSES
    assert set(status_counts) == ALLOWED_STATUSES
    assert set(payload["metadata"]["parity_bucket_model"]) == ALLOWED_PARITY_BUCKETS
    assert set(parity_counts) == ALLOWED_PARITY_BUCKETS
    assert sum(status_counts.values()) == len(coverage) == 178
    assert sum(parity_counts.values()) == len(coverage) == 178
    assert payload["summary"]["total_functions"] == 148
    assert payload["summary"]["implemented"] == 178
    assert payload["summary"]["total_topics"] == 30
    assert payload["summary"]["manifest_only"] == 167
    assert payload["summary"]["live_tested"] == 1
    assert payload["summary"]["behavioral_supported"] == 1 + len(SANDBOX_MUTATING_TESTED_URIS)
    assert status_counts == _counts_with_zeroes(Counter(entry["coverage_status"] for entry in coverage), status_counts)
    assert parity_counts == _counts_with_zeroes(Counter(entry["parity_bucket"] for entry in coverage), parity_counts)
    assert parity_counts["live-tested"] == 1
    assert parity_counts["sandbox-mutating-tested"] == len(SANDBOX_MUTATING_TESTED_URIS)
    assert live_promoted == PROMOTED_READ_ONLY_URIS
    assert sandbox_promoted == SANDBOX_MUTATING_TESTED_URIS


def test_2024_source_note_families_are_context_except_promoted_object_get() -> None:
    source_notes = json.loads(SOURCE_NOTES_RESOURCE.read_text(encoding="utf-8"))["notes"]
    expected_families = {"query", "object-mutation", "property-reference", "import", "soundbank", "switchcontainer"}
    source_uris = {
        uri
        for family, note in source_notes.items()
        if family in expected_families
        for uri in note["endpoints"]
    }
    coverage_by_uri = {entry["uri"]: entry for entry in _coverage_payload()["coverage"] if entry["item_type"] == "function"}
    covered_source_uris = source_uris & set(coverage_by_uri)

    assert set(source_notes) == expected_families
    assert covered_source_uris
    for uri in covered_source_uris:
        entry = coverage_by_uri[uri]
        assert entry["source_note_family"] in expected_families
        if uri == PROMOTED_READ_ONLY_URI:
            assert entry["coverage_status"] == "live-tested"
            assert entry["behavioral_evidence"]["manifest_reflection_only"] is False
            assert entry["behavioral_evidence"]["counts_as_behavioral"] is True
        elif uri in SANDBOX_MUTATING_TESTED_URIS:
            assert entry["coverage_status"] == "sandbox-mutating-tested"
            assert entry["behavioral_evidence"]["manifest_reflection_only"] is False
            assert entry["behavioral_evidence"]["counts_as_behavioral"] is True
        else:
            assert entry["coverage_status"] == "deferred"
            assert entry["behavioral_evidence"]["manifest_reflection_only"] is True
            assert entry["behavioral_evidence"]["counts_as_behavioral"] is False


def test_2024_risky_families_are_not_promoted() -> None:
    for entry in _coverage_payload()["coverage"]:
        if entry["item_type"] == "topic":
            assert entry["coverage_status"] == "deferred", entry["uri"]
            assert entry["behavioral_evidence"]["counts_as_behavioral"] is False, entry["uri"]
            continue
        if _is_risky_category(entry["category"]):
            assert entry["coverage_status"] == "excluded", entry["uri"]
            assert entry["parity_bucket"] == "excluded", entry["uri"]
            assert entry["behavioral_evidence"]["counts_as_behavioral"] is False, entry["uri"]
            assert entry["behavioral_evidence"]["counts_as_live_behavioral"] is False, entry["uri"]
            assert "excluded" in entry["deferred"]["blocking_condition"], entry["uri"]


def _coverage_payload() -> dict[str, Any]:
    return json.loads(COVERAGE_RESOURCE.read_text(encoding="utf-8"))


def _uris(path: Path, section: str) -> list[str]:
    return [entry["uri"] for entry in json.loads(path.read_text(encoding="utf-8"))[section]]


def _is_risky_category(category: str) -> bool:
    return any(category == prefix or category.startswith(prefix + ".") for prefix in RISKY_CATEGORY_PREFIXES)


def _counts_with_zeroes(counts: Counter[str], summary_counts: dict[str, int]) -> dict[str, int]:
    return {key: counts.get(key, 0) for key in summary_counts}
