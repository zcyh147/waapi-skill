from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.deferred_registry import ApiClassifier  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION = "2021.1"
FUNCTIONS_MANIFEST = REPO_ROOT / "skills" / "waapi-skill" / "resources" / "manifest" / VERSION / "functions.json"
TOPICS_MANIFEST = REPO_ROOT / "skills" / "waapi-skill" / "resources" / "manifest" / VERSION / "topics.json"
COVERAGE_RESOURCE = REPO_ROOT / "tests" / "destructive" / "support" / "resources" / "capabilities" / VERSION / "api-coverage.json"
MATRIX_RESOURCE = REPO_ROOT / "tests" / "destructive" / "support" / "resources" / "capabilities" / VERSION / "live-coverage-matrix.json"
SUMMARY_RESOURCE = REPO_ROOT / "tests" / "destructive" / "support" / "resources" / "capabilities" / VERSION / "phase2-coverage-summary.json"
POLICY_RESOURCE = REPO_ROOT / "tests" / "destructive" / "support" / "resources" / "capabilities" / VERSION / "phase21-uri-policy.json"

CLASSIFICATION_STATUSES = {"supported", "behavioral", "deferred", "excluded", "live-tested", "sandbox-mutating-tested"}
BLOCKED_STATUSES = {"deferred", "excluded"}
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
FORBIDDEN_NEWER_EVIDENCE = (
    "resources/manifest/2022.1",
    "resources/manifest/2023.1",
    "resources/manifest/2024.1",
    "resources/manifest/2025.1",
    "tests/destructive/support/resources/capabilities/2022.1",
    "tests/destructive/support/resources/capabilities/2023.1",
    "tests/destructive/support/resources/capabilities/2024.1",
    "tests/destructive/support/resources/capabilities/2025.1",
    "resources/deferred/2022.1",
    "resources/deferred/2023.1",
    "resources/deferred/2024.1",
    "resources/deferred/2025.1",
)


def test_2021_resource_covers_every_reflected_function_and_topic_once_with_2021_paths() -> None:
    reflected = sorted(_uris(FUNCTIONS_MANIFEST, "functions") + _uris(TOPICS_MANIFEST, "topics"))
    payload = _coverage_payload()
    coverage = payload["coverage"]
    encoded = json.dumps(payload)

    assert len(_uris(FUNCTIONS_MANIFEST, "functions")) == 99
    assert len(_uris(TOPICS_MANIFEST, "topics")) == 27
    assert len(reflected) == 126
    assert len(coverage) == 126
    assert [entry["uri"] for entry in coverage] == reflected
    assert len({entry["uri"] for entry in coverage}) == len(coverage)
    assert payload["metadata"]["version"] == VERSION
    assert payload["metadata"]["manifest_source"] == "resources/manifest/2021.1"
    assert payload["metadata"]["reflected_counts"]["manifest_function_count"] == 99
    assert payload["metadata"]["reflected_counts"]["manifest_topic_count"] == 27
    assert payload["metadata"]["reflected_counts"]["schema_count"] == 126
    assert payload["metadata"]["reflected_counts"]["schema_failure_count"] == 0
    assert not any(path in encoded for path in FORBIDDEN_NEWER_EVIDENCE)


def test_2021_entries_are_deferred_or_excluded_without_behavioral_promotion() -> None:
    classifier = ApiClassifier()

    for entry in _coverage_payload()["coverage"]:
        expected = classifier.classify(entry["uri"], entry["item_type"])
        evidence = entry["behavioral_evidence"]

        assert entry["version"] == VERSION
        assert entry["item_type"] in {"function", "topic"}
        assert entry["category"] == expected.category
        assert entry["risk_level"] == expected.risk_level
        assert entry["schema_status"] == "ok", entry["uri"]
        assert entry["schema_mapping"]["manifest_uri"] == f"resources/manifest/2021.1/schemas.json#{entry['uri']}"
        if entry["uri"] == LIVE_TESTED_OBJECT_GET:
            assert entry["coverage_status"] == "live-tested"
            assert entry["test_status"] == "live-tested"
            assert entry["parity_bucket"] == "live-tested"
            assert entry["deferred"]["status"] is False
            assert evidence["counts_as_behavioral"] is True
            assert evidence["counts_as_live_behavioral"] is True
            assert evidence["evidence_path"] == "resources/waql/2021.1/object-get-live-matrix.json"
            assert evidence["live_command_evidence"] == (
                ".sisyphus/evidence/wwise-2021-waapi-integration-coverage/task-7-waql-matrix.json"
            )
            assert "Task 7" not in evidence["evidence_standard"] or "ak.wwise.core.object.get" in evidence["evidence_standard"]
            continue
        if entry["uri"] in SANDBOX_MUTATING_TESTED_URIS:
            assert entry["coverage_status"] == "sandbox-mutating-tested", entry["uri"]
            assert entry["test_status"] == "sandbox-mutating-tested", entry["uri"]
            assert entry["parity_bucket"] == "sandbox-mutating-tested", entry["uri"]
            assert entry["deferred"]["status"] is False, entry["uri"]
            assert evidence["manifest_reflection_only"] is False, entry["uri"]
            assert evidence["counts_as_behavioral"] is True, entry["uri"]
            assert evidence["counts_as_live_behavioral"] is True, entry["uri"]
            assert "Fresh 2021.1 copied-sandbox destructive behavior evidence" in evidence["evidence_standard"]
            assert evidence["live_command_evidence"] in {
                ".sisyphus/evidence/wwise-2021-waapi-integration-coverage/task-10-object-crud.json",
                ".sisyphus/evidence/wwise-2021-waapi-integration-coverage/task-11-soundbank-audio.json",
                ".sisyphus/evidence/wwise-2021-waapi-integration-coverage/task-12-switchcontainer-assignment.json",
            }
            continue

        assert entry["coverage_status"] in BLOCKED_STATUSES, entry["uri"]
        assert entry["test_status"] == entry["coverage_status"], entry["uri"]
        assert entry["parity_bucket"] == entry["coverage_status"], entry["uri"]
        assert entry["deferred"]["status"] is True, entry["uri"]
        assert entry["deferred"]["coverage_status"] == entry["coverage_status"], entry["uri"]
        assert evidence["coverage"] == entry["coverage_status"]
        assert evidence["parity_bucket"] == entry["parity_bucket"]
        assert evidence["manifest_reflection_only"] is True
        assert evidence["counts_as_behavioral"] is False
        assert evidence["counts_as_live_behavioral"] is False
        assert len(evidence["source_paths"]) == len(set(evidence["source_paths"])), entry["uri"]
        if entry["item_type"] == "topic":
            assert "topic coverage is manifest inventory/substitute accounting only" in evidence["evidence_standard"]
            assert "no-Wwise-launch instruction" in evidence["evidence_standard"]
        else:
            assert "Task 4 reflection prove inventory presence, not behavior" in evidence["evidence_standard"]
            assert "no 2022.1/2023.1/2024.1/2025.1 evidence" in evidence["evidence_standard"]
        if entry["source_note_family"]:
            assert evidence["source_note_evidence"].startswith("resources/semantic/2021.1/source_notes.json#"), entry["uri"]
        elif entry["item_type"] == "topic":
            assert "topics are sourced" in evidence["source_note_evidence"], entry["uri"]
            assert evidence["source_paths"] == [entry["deferred"]["reflection_evidence_path"]], entry["uri"]
        else:
            assert evidence["source_note_evidence"] == "not-applicable: no 2021.1 source-note family mapped for this URI", entry["uri"]
            assert evidence["source_paths"] == [entry["deferred"]["reflection_evidence_path"]], entry["uri"]


def test_2021_classification_accounting_has_zero_unknowns() -> None:
    payload = _coverage_payload()
    _assert_exact_classification_accounting(payload, _uris(FUNCTIONS_MANIFEST, "functions") + _uris(TOPICS_MANIFEST, "topics"))

    status_counts = payload["summary"]["status_counts"]
    assert set(status_counts) == CLASSIFICATION_STATUSES
    assert status_counts == {
        "supported": 0,
        "behavioral": 0,
        "deferred": 70,
        "excluded": 46,
        "live-tested": 1,
        "sandbox-mutating-tested": 9,
    }
    assert payload["summary"]["unknown"] == 0
    assert payload["summary"]["behavioral_supported"] == 1 + len(SANDBOX_MUTATING_TESTED_URIS)
    assert payload["summary"]["live_tested"] == 1


def test_2021_unclassified_reflected_uri_is_rejected_by_accounting_fixture() -> None:
    payload = json.loads(json.dumps(_coverage_payload()))
    reflected = [*_uris(FUNCTIONS_MANIFEST, "functions"), *_uris(TOPICS_MANIFEST, "topics"), "ak.wwise.core.unclassifiedInjected"]

    with pytest.raises(AssertionError, match="unclassified reflected URIs"):
        _assert_exact_classification_accounting(payload, reflected)


def test_2021_matrix_summary_and_policy_match_coverage_accounting() -> None:
    coverage = _coverage_payload()
    matrix = _json(MATRIX_RESOURCE)
    phase2 = _json(SUMMARY_RESOURCE)
    policy = _json(POLICY_RESOURCE)

    function_coverage = [entry for entry in coverage["coverage"] if entry["item_type"] == "function"]
    assert [entry["uri"] for entry in matrix["matrix"]] == [entry["uri"] for entry in function_coverage]
    assert [entry["uri"] for entry in phase2["entries"]] == [entry["uri"] for entry in function_coverage]
    function_status_counts = {key: Counter(entry["coverage_status"] for entry in function_coverage).get(key, 0) for key in matrix["summary"]["status_counts"]}
    assert matrix["summary"]["status_counts"] == function_status_counts
    assert phase2["summary"]["status_counts"] == function_status_counts
    assert policy["summary"]["classification_counts"] == function_status_counts
    assert matrix["summary"]["behavioral_covered_count"] == 1 + len(SANDBOX_MUTATING_TESTED_URIS)
    assert matrix["summary"]["live_behavioral_covered_count"] == 1 + len(SANDBOX_MUTATING_TESTED_URIS)
    assert phase2["summary"]["behavioral_covered_count"] == 1 + len(SANDBOX_MUTATING_TESTED_URIS)
    assert phase2["summary"]["live_behavioral_covered_count"] == 1 + len(SANDBOX_MUTATING_TESTED_URIS)

    assigned = [uri for uris in policy["policy"]["classification_buckets"].values() for uri in uris]
    assert sorted(assigned) == [entry["uri"] for entry in function_coverage]
    assert len(assigned) == len(set(assigned)) == 99

    for entry in matrix["matrix"]:
        if entry["uri"] == LIVE_TESTED_OBJECT_GET:
            assert entry["counts_as_behavioral"] is True
            assert entry["counts_as_live_behavioral"] is True
            assert entry["evidence_path"] == "resources/waql/2021.1/object-get-live-matrix.json"
            assert entry["coverage_status"] == "live-tested"
        elif entry["uri"] in SANDBOX_MUTATING_TESTED_URIS:
            assert entry["counts_as_behavioral"] is True
            assert entry["counts_as_live_behavioral"] is True
            assert entry["evidence_path"].startswith(
                ".sisyphus/evidence/wwise-2021-waapi-integration-coverage/destructive/"
            )
            assert entry["coverage_status"] == "sandbox-mutating-tested"
        else:
            assert entry["counts_as_behavioral"] is False
            assert entry["counts_as_live_behavioral"] is False
            assert entry["evidence_path"] == "resources/deferred/2021.1.json"
        assert entry["manifest_source_uri"].startswith("resources/manifest/2021.1/")
        assert entry["source_coverage_uri"] == "tests/destructive/support/resources/capabilities/2021.1/api-coverage.json"


def _assert_exact_classification_accounting(payload: dict[str, Any], reflected_uris: list[str]) -> None:
    reflected = sorted(reflected_uris)
    coverage = payload["coverage"]
    coverage_uris = [entry["uri"] for entry in coverage]
    assert coverage_uris == sorted(coverage_uris)
    assert len(coverage_uris) == len(set(coverage_uris))

    missing = sorted(set(reflected) - set(coverage_uris))
    extra = sorted(set(coverage_uris) - set(reflected))
    assert not missing, f"unclassified reflected URIs: {missing}"
    assert not extra, f"coverage includes non-reflected URIs: {extra}"

    statuses = [entry["coverage_status"] for entry in coverage]
    invalid_statuses = sorted(set(statuses) - CLASSIFICATION_STATUSES)
    assert not invalid_statuses, f"invalid classification statuses: {invalid_statuses}"
    counts = {status: Counter(statuses).get(status, 0) for status in payload["summary"]["status_counts"]}
    assert counts == payload["summary"]["status_counts"]
    assert sum(counts.values()) == len(reflected)
    assert payload["summary"]["unknown"] == 0
    assert payload["summary"]["reflected_total"] == len(reflected)


def _coverage_payload() -> dict[str, Any]:
    return _json(COVERAGE_RESOURCE)


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _uris(path: Path, section: str) -> list[str]:
    return [entry["uri"] for entry in json.loads(path.read_text(encoding="utf-8"))[section]]
