from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Callable

import pytest  # pyright: ignore[reportMissingImports]
import json

from wwise_waapi.dispatcher import DEFAULT_WWISE_VERSION, WwiseDispatcher  # pyright: ignore[reportMissingImports]
from wwise_waapi.manifest import ManifestStore, audit_manifest  # pyright: ignore[reportMissingImports]


ROOT = Path(__file__).resolve().parents[2]
VERSION_2022 = "2022.1"
VERSION_2024 = "2024.1"
NOTEBOOK_2024 = "wwise-2024.1-docs"
MANIFEST_ROOT = Path("resources") / "manifest"
SEMANTIC_2024 = ROOT / "resources" / "semantic" / VERSION_2024 / "source_notes.json"
COVERAGE_2024 = ROOT / "resources" / "coverage" / VERSION_2024 / "api-coverage.json"
LIVE_MATRIX_2024 = ROOT / "resources" / "coverage" / VERSION_2024 / "live-coverage-matrix.json"
PHASE2_SUMMARY_2024 = ROOT / "resources" / "coverage" / VERSION_2024 / "phase2-coverage-summary.json"
POLICY_2024 = ROOT / "resources" / "coverage" / VERSION_2024 / "phase21-uri-policy.json"
DEFERRED_2024 = ROOT / "resources" / "deferred" / f"{VERSION_2024}.json"
REFERENCES_2024 = ROOT / "references" / "semantic" / VERSION_2024
FIXTURE_2024 = ROOT / "tests" / "_org" / VERSION_2024
GET_INFO_URI = "ak.wwise.core.getInfo"
EXPECTED_2024_AUDIT_COUNTS = (148, 30, 178, 0)
PROMOTED_2024_STATUSES = {"live-tested", "sandbox-mutating-tested"}
APPROVED_2024_PROMOTION_EVIDENCE = (
    ".sisyphus/evidence/wwise-2024-waapi-integration-coverage/",
    "resources/waql/2024.1/",
)
FORBIDDEN_2024_FALLBACK_FRAGMENTS = (
    "resources/manifest/2022.1",
    "resources/manifest/2023.1",
    "resources/manifest/2024/",
    "resources/manifest/2025",
    "resources/coverage/2022.1",
    "resources/coverage/2023.1",
    "resources/coverage/2024/",
    "resources/coverage/2025",
    "resources/deferred/2022.1",
    "resources/deferred/2023.1",
    "resources/deferred/2024/",
    "resources/deferred/2025",
    "resources/semantic/2022.1",
    "resources/semantic/2023.1",
    "resources/semantic/2024/",
    "resources/semantic/2025",
    "references/semantic/2022.1",
    "references/semantic/2023.1",
    "references/semantic/2024/",
    "references/semantic/2025",
    "references/semantic-builder-",
)
NO_2025_RESOURCE_ROOTS = (
    ROOT / "resources" / "manifest",
    ROOT / "resources" / "coverage",
    ROOT / "resources" / "semantic",
    ROOT / "references" / "semantic",
)


def _reject_forbidden_2024_fallback(path: Path) -> None:
    path_text = path.as_posix()
    for fragment in FORBIDDEN_2024_FALLBACK_FRAGMENTS:
        if fragment in path_text:
            raise AssertionError(f"Explicit 2024.1 audit touched forbidden fallback resource: {path_text}")


def test_default_dispatcher_remains_2022_1_and_explicit_2024_1_dispatch_succeeds() -> None:
    store = ManifestStore(root=MANIFEST_ROOT)
    manifest_2024 = store.load(VERSION_2024)
    audit = audit_manifest(manifest_2024)

    assert DEFAULT_WWISE_VERSION == VERSION_2022
    assert manifest_2024["metadata"]["version_key"] == VERSION_2024
    assert manifest_2024["metadata"]["wwise_version_target"] == VERSION_2024
    assert manifest_2024["metadata"]["wwise_build"] == "2024.1.13.9056"
    assert (
        audit.manifest_function_count,
        audit.manifest_topic_count,
        audit.schema_count,
        audit.schema_failure_count,
    ) == EXPECTED_2024_AUDIT_COUNTS
    assert (FIXTURE_2024 / "SampleProject.wproj").is_file()

    dispatcher = WwiseDispatcher(manifest_store=store)
    default_result = dispatcher.dispatch(GET_INFO_URI, dry_run=True)
    explicit_2024_result = dispatcher.dispatch(GET_INFO_URI, version=VERSION_2024, dry_run=True)

    assert default_result["ok"] is True
    assert default_result["version"] == VERSION_2022
    assert explicit_2024_result["ok"] is True
    assert explicit_2024_result["version"] == VERSION_2024


def test_explicit_2024_1_resource_lookups_never_read_prior_generic_global_or_2025_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_read_text: Callable[..., str] = Path.read_text
    touched: list[str] = []

    def guarded_read_text(path: Path, *args: Any, **kwargs: Any) -> str:
        path_text = path.as_posix()
        touched.append(path_text)
        _reject_forbidden_2024_fallback(path)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    store = ManifestStore(root=MANIFEST_ROOT)
    manifest = store.load(VERSION_2024)
    dispatch_result = WwiseDispatcher(manifest_store=store).dispatch(GET_INFO_URI, version=VERSION_2024, dry_run=True)
    coverage = _read_json(COVERAGE_2024)
    matrix = _read_json(LIVE_MATRIX_2024)
    summary = _read_json(PHASE2_SUMMARY_2024)
    policy = _read_json(POLICY_2024)
    deferred = _read_json(DEFERRED_2024)

    assert manifest["metadata"]["version_key"] == VERSION_2024
    assert dispatch_result["ok"] is True
    assert dispatch_result["version"] == VERSION_2024
    assert coverage["metadata"]["version"] == VERSION_2024
    assert matrix["metadata"]["version"] == VERSION_2024
    assert summary["metadata"]["version"] == VERSION_2024
    assert policy["metadata"]["version"] == VERSION_2024
    assert deferred["metadata"]["version"] == VERSION_2024
    assert any("resources/manifest/2024.1/manifest.json" in path for path in touched)
    assert any("resources/manifest/2024.1/functions.json" in path for path in touched)
    assert any("resources/manifest/2024.1/topics.json" in path for path in touched)
    assert any("resources/manifest/2024.1/schemas.json" in path for path in touched)
    assert any("resources/coverage/2024.1/api-coverage.json" in path for path in touched)
    assert any("resources/coverage/2024.1/live-coverage-matrix.json" in path for path in touched)
    assert any("resources/coverage/2024.1/phase2-coverage-summary.json" in path for path in touched)
    assert any("resources/coverage/2024.1/phase21-uri-policy.json" in path for path in touched)
    assert any("resources/deferred/2024.1.json" in path for path in touched)
    assert not any(
        any(fragment in path for fragment in FORBIDDEN_2024_FALLBACK_FRAGMENTS)
        for path in touched
    )


def test_no_2025_resource_payloads_were_introduced() -> None:
    discovered_2025_paths: list[Path] = []

    for root in NO_2025_RESOURCE_ROOTS:
        if not root.exists():
            continue
        for child in root.iterdir():
            if not child.name.startswith("2025"):
                continue
            candidates = [child] if child.is_file() else list(child.iterdir())
            discovered_2025_paths.extend(candidate for candidate in candidates if candidate.name != ".gitkeep")

    assert discovered_2025_paths == []

def test_2024_semantic_source_notes_use_2024_notebook_and_versioned_references() -> None:
    payload = json.loads(SEMANTIC_2024.read_text(encoding="utf-8"))

    assert payload["version"] == VERSION_2024
    assert payload["notebook_id"] == NOTEBOOK_2024
    assert payload["protocol"] == "references/semantic/2024.1/semantic-builder-protocol.md"

    for family, note in payload["notes"].items():
        assert note["status"] == "grounded"
        assert note["notebook_id"] == NOTEBOOK_2024
        assert note["version_target"] == VERSION_2024
        assert note["gate_evidence_path"] == "references/semantic/2024.1/semantic-builder-notebooklm-gate.md"
        assert set(note["required_fields"]) <= set(note["cited_required_fields"])
        for evidence_path in [note["gate_evidence_path"], *note["source_urls"]]:
            assert evidence_path.startswith("references/semantic/2024.1/"), evidence_path
            assert "references/semantic-builder-" not in evidence_path
            assert "2022.1" not in evidence_path
            assert "2023.1" not in evidence_path
        encoded_note = json.dumps(note, sort_keys=True)
        assert NOTEBOOK_2024 in encoded_note
        assert "wwise-2022.1-docs" not in encoded_note
        assert "wwise-2023.1-docs" not in encoded_note
        assert "resources/semantic/2024/" not in encoded_note

    for reference in REFERENCES_2024.glob("*.md"):
        text = reference.read_text(encoding="utf-8")
        assert "references/semantic-builder-" not in text
        assert "wwise-2022.1-docs" not in text
        assert "wwise-2023.1-docs" not in text
        assert "references/semantic/2022.1" not in text
        assert "references/semantic/2023.1" not in text


def test_2024_semantic_runtime_checks_read_local_files_only(monkeypatch: pytest.MonkeyPatch) -> None:
    original_read_text: Callable[..., str] = Path.read_text
    touched: list[str] = []

    def guarded_read_text(path: Path, *args: Any, **kwargs: Any) -> str:
        path_text = path.as_posix()
        touched.append(path_text)
        _reject_forbidden_2024_fallback(path)
        assert "scripts/run.py" not in path_text
        assert ".agents/skills/notebooklm" not in path_text
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    payload = json.loads(SEMANTIC_2024.read_text(encoding="utf-8"))
    gate_text = (REFERENCES_2024 / "semantic-builder-notebooklm-gate.md").read_text(encoding="utf-8")

    assert payload["notebook_id"] == NOTEBOOK_2024
    assert "Runtime builders must read versioned local source-note resources" in gate_text
    assert any("resources/semantic/2024.1/source_notes.json" in path for path in touched)
    assert any("references/semantic/2024.1/semantic-builder-notebooklm-gate.md" in path for path in touched)
    assert not any(any(fragment in path for fragment in FORBIDDEN_2024_FALLBACK_FRAGMENTS) for path in touched)


def test_2024_coverage_policy_deferred_and_source_notes_reconcile_without_manifest_only_promotions() -> None:
    manifest = ManifestStore(root=MANIFEST_ROOT).load(VERSION_2024)
    coverage = _read_json(COVERAGE_2024)
    live_matrix = _read_json(LIVE_MATRIX_2024)
    phase2_summary = _read_json(PHASE2_SUMMARY_2024)
    policy = _read_json(POLICY_2024)
    deferred = _read_json(DEFERRED_2024)
    source_notes = _read_json(SEMANTIC_2024)

    reflected_function_uris = sorted(entry["uri"] for entry in manifest["functions"])
    reflected_topic_uris = sorted(entry["uri"] for entry in manifest["topics"])
    coverage_entries = coverage["coverage"]
    matrix_entries = live_matrix["matrix"]
    summary_entries = phase2_summary["entries"]
    coverage_by_uri = {entry["uri"]: entry for entry in coverage_entries}
    matrix_by_uri = {entry["uri"]: entry for entry in matrix_entries}
    summary_by_uri = {entry["uri"]: entry for entry in summary_entries}
    expected_status_counts = _counts_with_summary_zeroes(
        dict(Counter(entry["coverage_status"] for entry in coverage_entries)),
        coverage["summary"]["status_counts"],
    )
    expected_parity_counts = _counts_with_summary_zeroes(
        dict(Counter(entry["parity_bucket"] for entry in coverage_entries)),
        coverage["summary"]["parity_bucket_counts"],
    )
    expected_source_note_counts = dict(
        sorted(Counter(entry["source_note_family"] for entry in coverage_entries if entry["source_note_family"]).items())
    )
    promoted_uris = {
        entry["uri"]
        for entry in coverage_entries
        if entry["coverage_status"] in PROMOTED_2024_STATUSES or entry["parity_bucket"] in PROMOTED_2024_STATUSES
    }
    behavioral_uris = {entry["uri"] for entry in matrix_entries if entry["counts_as_behavioral"] is True}
    live_behavioral_uris = {entry["uri"] for entry in matrix_entries if entry["counts_as_live_behavioral"] is True}

    assert len(reflected_topic_uris) == len(manifest["topics"])
    assert [entry["uri"] for entry in coverage_entries] == reflected_function_uris
    assert [entry["uri"] for entry in matrix_entries] == reflected_function_uris
    assert [entry["uri"] for entry in summary_entries] == reflected_function_uris
    assert len(coverage_by_uri) == len(matrix_by_uri) == len(summary_by_uri) == len(reflected_function_uris)
    assert coverage["summary"]["total_functions"] == len(reflected_function_uris)
    assert coverage["summary"]["implemented"] == len(reflected_function_uris)
    assert coverage["summary"]["reflected_count"] == len(reflected_function_uris)
    assert coverage["summary"]["status_counts"] == expected_status_counts
    assert coverage["summary"]["parity_bucket_counts"] == expected_parity_counts
    assert coverage["summary"]["parity_bucket_total"] == len(reflected_function_uris)
    assert coverage["summary"]["manifest_only"] == len(
        [entry for entry in coverage_entries if entry["behavioral_evidence"]["manifest_reflection_only"] is True]
    )
    assert coverage["summary"]["source_note_family_counts"] == expected_source_note_counts
    assert {entry["version"] for entry in coverage_entries} == {VERSION_2024}
    assert all(entry["schema_mapping"]["manifest_uri"].startswith("resources/manifest/2024.1/") for entry in coverage_entries)

    assert live_matrix["metadata"]["baseline_resource"] == "resources/coverage/2024.1/api-coverage.json"
    assert live_matrix["summary"]["reflected_count"] == len(reflected_function_uris)
    assert live_matrix["summary"]["total_functions"] == len(reflected_function_uris)
    assert live_matrix["summary"]["status_counts"] == expected_status_counts
    assert live_matrix["summary"]["parity_bucket_counts"] == expected_parity_counts
    assert live_matrix["summary"]["parity_bucket_total"] == len(reflected_function_uris)
    assert live_matrix["summary"]["behavioral_covered_count"] == len(behavioral_uris)
    assert live_matrix["summary"]["live_behavioral_covered_count"] == len(live_behavioral_uris)
    assert live_matrix["summary"]["source_note_family_counts"] == expected_source_note_counts
    assert {entry["version"] for entry in matrix_entries} == {VERSION_2024}
    assert all(entry["source_coverage_uri"] == "resources/coverage/2024.1/api-coverage.json" for entry in matrix_entries)

    assert phase2_summary["metadata"]["baseline_resource"] == "resources/coverage/2024.1/api-coverage.json"
    assert phase2_summary["metadata"]["live_matrix_resource"] == "resources/coverage/2024.1/live-coverage-matrix.json"
    assert phase2_summary["summary"]["reflected_count"] == len(reflected_function_uris)
    assert phase2_summary["summary"]["total_functions"] == len(reflected_function_uris)
    assert phase2_summary["summary"]["status_counts"] == expected_status_counts
    assert phase2_summary["summary"]["parity_bucket_counts"] == expected_parity_counts
    assert phase2_summary["summary"]["parity_bucket_total"] == len(reflected_function_uris)
    assert phase2_summary["summary"]["behavioral_covered_count"] == len(behavioral_uris)
    assert phase2_summary["summary"]["live_behavioral_covered_count"] == len(live_behavioral_uris)
    assert phase2_summary["summary"]["source_note_family_counts"] == expected_source_note_counts

    assigned_policy_uris = [uri for uris in policy["policy"]["parity_buckets"].values() for uri in uris]
    assert sorted(assigned_policy_uris) == reflected_function_uris
    assert len(assigned_policy_uris) == len(set(assigned_policy_uris)) == len(reflected_function_uris)
    assert policy["summary"]["status_counts"] == expected_status_counts
    assert policy["summary"]["parity_bucket_counts"] == expected_parity_counts
    assert policy["summary"]["parity_bucket_total"] == len(reflected_function_uris)
    assert policy["summary"]["source_note_family_counts"] == expected_source_note_counts
    assert sorted(policy["policy"]["live_tested_uris"]) == sorted(
        uri for uri, entry in coverage_by_uri.items() if entry["coverage_status"] == "live-tested"
    )
    assert sorted(policy["policy"]["sandbox_mutating_tested_uris"]) == sorted(
        uri for uri, entry in coverage_by_uri.items() if entry["coverage_status"] == "sandbox-mutating-tested"
    )
    assert sorted(policy["policy"]["deferred_uris"] + policy["policy"]["excluded_uris"]) == sorted(
        uri for uri, entry in coverage_by_uri.items() if entry["coverage_status"] in {"deferred", "excluded"}
    )

    deferred_entries = deferred["deferred"]
    deferred_by_uri = {entry["uri"]: entry for entry in deferred_entries}
    blocked_uris = {
        entry["uri"]
        for entry in coverage_entries
        if entry["coverage_status"] in {"deferred", "excluded"}
    }
    assert set(deferred_by_uri) == blocked_uris
    assert deferred["summary"]["total"] == len(blocked_uris)
    assert deferred["summary"]["status_counts"] == _count_by_key(deferred_entries, "coverage_status")
    assert {entry["version"] for entry in deferred_entries} == {VERSION_2024}
    assert all("resources/manifest/2024.1" in entry["evidence_source"] for entry in deferred_entries)

    source_note_uris = {
        uri
        for note in source_notes["notes"].values()
        for uri in note["endpoints"]
    }
    for entry in coverage_entries:
        if entry["source_note_family"]:
            assert entry["uri"] in source_note_uris
    assert source_notes["version"] == VERSION_2024
    assert source_notes["notebook_id"] == NOTEBOOK_2024

    for uri, entry in coverage_by_uri.items():
        matrix_entry = matrix_by_uri[uri]
        summary_entry = summary_by_uri[uri]
        evidence = entry["behavioral_evidence"]
        assert matrix_entry["coverage_status"] == entry["coverage_status"], uri
        assert summary_entry["coverage_status"] == entry["coverage_status"], uri
        assert matrix_entry["parity_bucket"] == entry["parity_bucket"], uri
        assert summary_entry["parity_bucket"] == entry["parity_bucket"], uri
        assert matrix_entry["counts_as_behavioral"] == evidence["counts_as_behavioral"], uri
        assert matrix_entry["counts_as_live_behavioral"] == evidence["counts_as_live_behavioral"], uri
        assert summary_entry["counts_as_behavioral"] == evidence["counts_as_behavioral"], uri
        assert summary_entry["counts_as_live_behavioral"] == evidence["counts_as_live_behavioral"], uri

        is_promoted = (
            uri in promoted_uris
            or matrix_entry["achieved_status"] in PROMOTED_2024_STATUSES
            or summary_entry["achieved_status"] in PROMOTED_2024_STATUSES
            or evidence["counts_as_behavioral"] is True
            or evidence["counts_as_live_behavioral"] is True
        )
        if is_promoted:
            assert evidence["manifest_reflection_only"] is False, uri
            assert _has_approved_2024_promotion_evidence(entry, matrix_entry, summary_entry), uri
        elif evidence.get("manifest_reflection_only") is True:
            assert entry["coverage_status"] not in PROMOTED_2024_STATUSES, uri
            assert entry["parity_bucket"] not in PROMOTED_2024_STATUSES, uri
            assert matrix_entry["achieved_status"] not in PROMOTED_2024_STATUSES, uri
            assert summary_entry["achieved_status"] not in PROMOTED_2024_STATUSES, uri
            assert evidence["counts_as_behavioral"] is False, uri
            assert evidence["counts_as_live_behavioral"] is False, uri

    for uri in policy["policy"]["manifest_only_uris"]:
        evidence = coverage_by_uri[uri]["behavioral_evidence"]
        assert evidence["manifest_reflection_only"] is True, uri
        assert coverage_by_uri[uri]["coverage_status"] not in PROMOTED_2024_STATUSES, uri
        assert coverage_by_uri[uri]["parity_bucket"] not in PROMOTED_2024_STATUSES, uri


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _count_by_key(entries: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        value = str(entry[key])
        counts[value] = counts.get(value, 0) + 1
    return counts


def _counts_with_summary_zeroes(counts: dict[str, int], summary_counts: dict[str, int]) -> dict[str, int]:
    return {key: counts.get(key, 0) for key in summary_counts}


def _has_approved_2024_promotion_evidence(*objects: dict[str, Any]) -> bool:
    encoded = json.dumps(objects, sort_keys=True)
    return any(root in encoded for root in APPROVED_2024_PROMOTION_EVIDENCE)

