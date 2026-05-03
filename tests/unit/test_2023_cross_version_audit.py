from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.common import BuilderFamily, require_source_note  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.source_notes import SemanticSourceNoteChecker  # pyright: ignore[reportMissingImports]
from wwise_waapi.dispatcher import DEFAULT_WWISE_VERSION, WwiseDispatcher  # pyright: ignore[reportMissingImports]
from wwise_waapi.manifest import ManifestStore  # pyright: ignore[reportMissingImports]


ROOT = Path(__file__).resolve().parents[2]
VERSION_2022 = "2022.1"
VERSION_2023 = "2023.1"
SANDBOX_MUTATING_TESTED_2023_URIS = {
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
NOTEBOOK_2023 = "wwise-2023.1-docs"
MANIFEST_ROOT = ROOT / "skills" / "waapi-skill" / "resources" / "manifest"
SEMANTIC_2023 = ROOT / "skills" / "waapi-skill" / "resources" / "semantic" / VERSION_2023 / "source_notes.json"
COVERAGE_2022 = ROOT / "tests" / "destructive" / "support" / "resources" / "capabilities" / VERSION_2022 / "api-coverage.json"
COVERAGE_2023 = ROOT / "tests" / "destructive" / "support" / "resources" / "capabilities" / VERSION_2023 / "api-coverage.json"
LIVE_MATRIX_2023 = ROOT / "tests" / "destructive" / "support" / "resources" / "capabilities" / VERSION_2023 / "live-coverage-matrix.json"
PHASE2_SUMMARY_2023 = ROOT / "tests" / "destructive" / "support" / "resources" / "capabilities" / VERSION_2023 / "phase2-coverage-summary.json"
POLICY_2023 = ROOT / "tests" / "destructive" / "support" / "resources" / "capabilities" / VERSION_2023 / "phase21-uri-policy.json"
DEFERRED_2023 = ROOT / "skills" / "waapi-skill" / "resources" / "deferred" / "2023.1.json"
WAQL_2023 = ROOT / "skills" / "waapi-skill" / "resources" / "waql" / VERSION_2023 / "object-get-live-matrix.json"
FIXTURE_2023 = ROOT / "tests" / "_org" / VERSION_2023
REFERENCES_2023 = ROOT / "references" / "semantic" / VERSION_2023
LIVE_TESTED_2023_URI = "ak.wwise.core.object.get"
READBACK_HELPER_URIS = {
    "ak.wwise.core.soundbank.getInclusions",
    "ak.wwise.core.switchContainer.getAssignments",
}
APPROVED_2023_PROMOTION_EVIDENCE = (
    ".sisyphus/evidence/wwise-2023-test-parity/",
    "resources/waql/2023.1/",
)
EXPECTED_FAMILIES = {
    "query",
    "object-mutation",
    "property-reference",
    "import",
    "soundbank",
    "switchcontainer",
}


def test_2023_and_2022_resources_are_independently_addressable() -> None:
    store = ManifestStore(root=MANIFEST_ROOT)
    manifest_2022 = store.load(VERSION_2022)
    manifest_2023 = store.load(VERSION_2023)
    coverage_2022 = _read_json(COVERAGE_2022)
    coverage_2023 = _read_json(COVERAGE_2023)
    notes_2023 = _read_json(SEMANTIC_2023)

    assert DEFAULT_WWISE_VERSION == VERSION_2022
    assert len(manifest_2022["functions"]) == 112
    assert len(manifest_2022["topics"]) == 32
    assert len(coverage_2022["coverage"]) == 144
    assert len(manifest_2023["functions"]) == 149
    assert len(manifest_2023["topics"]) == 32
    assert len(manifest_2023["schemas"]) == 181
    assert len(coverage_2023["coverage"]) == 181
    assert manifest_2023["metadata"]["wwise_version_target"] == VERSION_2023
    assert coverage_2023["metadata"]["manifest_source"] == "resources/manifest/2023.1"
    assert notes_2023["version"] == VERSION_2023
    assert notes_2023["notebook_id"] == NOTEBOOK_2023
    assert set(notes_2023["notes"]) == EXPECTED_FAMILIES
    assert (FIXTURE_2023 / "SampleProject.wproj").is_file()
    assert (REFERENCES_2023 / "semantic-builder-notebooklm-gate.md").is_file()

    default_result = WwiseDispatcher(manifest_store=store).dispatch("ak.wwise.core.getInfo", dry_run=True)
    explicit_2023_result = WwiseDispatcher(manifest_store=store).dispatch(
        "ak.wwise.core.getInfo",
        version=VERSION_2023,
        dry_run=True,
    )

    assert default_result["ok"] is True
    assert default_result["version"] == VERSION_2022
    assert explicit_2023_result["ok"] is True
    assert explicit_2023_result["version"] == VERSION_2023


def test_explicit_2023_resource_lookups_never_read_2022_or_global_semantic_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    original_read_text: Callable[..., str] = Path.read_text
    touched: list[str] = []

    def guarded_read_text(path: Path, *args: Any, **kwargs: Any) -> str:
        path_text = path.as_posix()
        touched.append(path_text)
        if "2022.1" in path_text or "references/semantic-builder-" in path_text:
            raise AssertionError(f"Explicit 2023.1 audit touched forbidden fallback resource: {path_text}")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    store = ManifestStore(root=MANIFEST_ROOT)
    manifest = store.load(VERSION_2023)
    status = require_source_note(SemanticSourceNoteChecker(notebook_id=NOTEBOOK_2023), BuilderFamily.QUERY, version=VERSION_2023)
    coverage = _read_json(COVERAGE_2023)
    live_matrix = _read_json(LIVE_MATRIX_2023)
    deferred = _read_json(DEFERRED_2023)
    waql = _read_json(WAQL_2023)

    assert len(manifest["functions"] + manifest["topics"]) == 181
    assert status.allowed is True
    assert status.version == VERSION_2023
    assert coverage["metadata"]["version"] == VERSION_2023
    assert live_matrix["metadata"]["version"] == VERSION_2023
    assert {entry["version"] for entry in deferred["deferred"]} == {VERSION_2023}
    assert waql["metadata"]["wwise_version_target"] == VERSION_2023
    assert any("resources/manifest/2023.1" in path for path in touched)
    assert any("resources/semantic/2023.1/source_notes.json" in path for path in touched)
    assert any("tests/destructive/support/resources/capabilities/2023.1" in path for path in touched)
    assert any("resources/deferred/2023.1.json" in path for path in touched)
    assert any("resources/waql/2023.1" in path for path in touched)
    assert not any("2022.1" in path or "references/semantic-builder-" in path for path in touched)


def test_2023_semantic_source_notes_use_2023_notebook_and_versioned_references() -> None:
    payload = _read_json(SEMANTIC_2023)

    assert payload["protocol"] == "references/semantic/2023.1/semantic-builder-protocol.md"
    for family, note in payload["notes"].items():
        assert family in EXPECTED_FAMILIES
        assert note["status"] == "grounded"
        assert note["notebook_id"] == NOTEBOOK_2023
        assert note["version_target"] == VERSION_2023
        assert note["gate_evidence_path"] == "references/semantic/2023.1/semantic-builder-notebooklm-gate.md"
        assert set(note["required_fields"]) <= set(note["cited_required_fields"])
        for evidence_path in [note["gate_evidence_path"], *note["source_urls"]]:
            assert evidence_path.startswith("references/semantic/2023.1/"), evidence_path
            assert "references/semantic-builder-" not in evidence_path
            assert "2022.1" not in evidence_path
        encoded_note = json.dumps(note, sort_keys=True)
        assert NOTEBOOK_2023 in encoded_note
        assert "wwise-2022.1-docs" not in encoded_note

    for reference in REFERENCES_2023.glob("*.md"):
        text = reference.read_text(encoding="utf-8")
        assert "references/semantic-builder-" not in text
        assert "wwise-2022.1-docs" not in text


def test_2023_coverage_deferred_and_waql_counts_are_version_separated() -> None:
    manifest = ManifestStore(root=MANIFEST_ROOT).load(VERSION_2023)
    coverage = _read_json(COVERAGE_2023)
    live_matrix = _read_json(LIVE_MATRIX_2023)
    phase2_summary = _read_json(PHASE2_SUMMARY_2023)
    policy = _read_json(POLICY_2023)
    deferred = _read_json(DEFERRED_2023)
    waql = _read_json(WAQL_2023)
    coverage_entries = coverage["coverage"]
    matrix_entries = live_matrix["matrix"]
    summary_entries = phase2_summary["entries"]
    coverage_by_uri = {entry["uri"]: entry for entry in coverage_entries}
    matrix_by_uri = {entry["uri"]: entry for entry in matrix_entries}
    summary_by_uri = {entry["uri"]: entry for entry in summary_entries}
    reflected_uris = sorted(entry["uri"] for entry in manifest["functions"] + manifest["topics"])
    expected_status_counts = _counts_with_summary_zeroes(_count_by_key(coverage_entries, "coverage_status"), coverage["summary"]["status_counts"])
    expected_parity_counts = _counts_with_summary_zeroes(
        _count_by_key(coverage_entries, "parity_bucket"),
        coverage["summary"]["parity_bucket_counts"],
    )
    behavioral_uris = {entry["uri"] for entry in matrix_entries if entry["counts_as_behavioral"] is True}
    live_behavioral_uris = {entry["uri"] for entry in matrix_entries if entry["counts_as_live_behavioral"] is True}
    promoted_uris = {LIVE_TESTED_2023_URI, *SANDBOX_MUTATING_TESTED_2023_URIS}

    assert coverage["summary"]["implemented"] == 181
    assert coverage["summary"]["total_functions"] == 149
    assert coverage["summary"]["total_topics"] == 32
    assert [entry["uri"] for entry in coverage_entries] == reflected_uris
    assert [entry["uri"] for entry in matrix_entries] == reflected_uris
    assert [entry["uri"] for entry in summary_entries] == reflected_uris
    assert len(coverage_by_uri) == len(matrix_by_uri) == len(summary_by_uri) == 181
    assert coverage["summary"]["status_counts"] == expected_status_counts
    assert coverage["summary"]["parity_bucket_counts"] == expected_parity_counts
    assert coverage["summary"]["parity_bucket_total"] == 181
    assert coverage["summary"]["live_tested"] == 1
    assert coverage["summary"]["behavioral_supported"] == len(promoted_uris)
    assert {entry["version"] for entry in coverage_entries} == {VERSION_2023}
    assert all(entry["schema_mapping"]["manifest_uri"].startswith("resources/manifest/2023.1/") for entry in coverage_entries)

    assert live_matrix["summary"]["reflected_count"] == 181
    assert len(matrix_entries) == 181
    assert live_matrix["summary"]["status_counts"] == expected_status_counts
    assert live_matrix["summary"]["parity_bucket_counts"] == expected_parity_counts
    assert live_matrix["summary"]["parity_bucket_total"] == 181
    assert live_matrix["summary"]["live_tested"] == 1
    assert {entry["version"] for entry in matrix_entries} == {VERSION_2023}
    assert all(entry["source_coverage_uri"] == "tests/destructive/support/resources/capabilities/2023.1/api-coverage.json" for entry in matrix_entries)
    assert phase2_summary["metadata"]["baseline_resource"] == "tests/destructive/support/resources/capabilities/2023.1/api-coverage.json"
    assert phase2_summary["metadata"]["live_matrix_resource"] == "tests/destructive/support/resources/capabilities/2023.1/live-coverage-matrix.json"
    assert phase2_summary["summary"]["reflected_count"] == 181
    assert phase2_summary["summary"]["status_counts"] == expected_status_counts
    assert phase2_summary["summary"]["parity_bucket_counts"] == expected_parity_counts
    assert phase2_summary["summary"]["parity_bucket_total"] == 181
    assert phase2_summary["summary"]["behavioral_covered_count"] == len(behavioral_uris) == len(promoted_uris)
    assert phase2_summary["summary"]["live_behavioral_covered_count"] == len(live_behavioral_uris) == len(promoted_uris)
    assigned_policy_uris = [uri for uris in policy["policy"]["parity_buckets"].values() for uri in uris]
    assert sorted(assigned_policy_uris) == reflected_uris
    assert len(assigned_policy_uris) == len(set(assigned_policy_uris)) == 181
    assert policy["summary"]["status_counts"] == expected_status_counts
    assert policy["summary"]["parity_bucket_counts"] == expected_parity_counts
    assert policy["summary"]["parity_bucket_total"] == 181
    active_deferred_entries = [
        entry
        for entry in deferred["deferred"]
        if coverage_by_uri[entry["uri"]]["coverage_status"] in {"deferred", "excluded"}
    ]
    deferred_status_counts = _count_by_key(active_deferred_entries, "coverage_status")
    assert deferred_status_counts == {
        "deferred": expected_status_counts["deferred"],
        "excluded": expected_status_counts["excluded"],
    }
    assert {entry["uri"] for entry in deferred["deferred"]} == {
        entry["uri"] for entry in coverage_entries if entry["coverage_status"] in {"deferred", "excluded"}
    }
    assert {entry["uri"] for entry in coverage_entries if entry["coverage_status"] == "live-tested"} == {LIVE_TESTED_2023_URI}
    assert {entry["uri"] for entry in coverage_entries if entry["coverage_status"] == "sandbox-mutating-tested"} == SANDBOX_MUTATING_TESTED_2023_URIS
    assert expected_status_counts["untested"] > 0
    assert {entry["version"] for entry in deferred["deferred"]} == {VERSION_2023}
    assert all("resources/manifest/2023.1" in entry["evidence_source"] for entry in deferred["deferred"])
    assert all(coverage_by_uri[uri]["coverage_status"] == "supported" for uri in READBACK_HELPER_URIS)
    assert all(coverage_by_uri[uri]["parity_bucket"] == "conformance-only" for uri in READBACK_HELPER_URIS)
    assert all(matrix_by_uri[uri]["counts_as_behavioral"] is False for uri in READBACK_HELPER_URIS)
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
        if uri in promoted_uris:
            assert evidence["manifest_reflection_only"] is False, uri
            assert evidence["counts_as_behavioral"] is True, uri
            assert evidence["counts_as_live_behavioral"] is True, uri
            assert _has_approved_2023_promotion_evidence(evidence), uri
        elif evidence.get("manifest_reflection_only") is True:
            assert entry["coverage_status"] not in {"live-tested", "sandbox-mutating-tested"}, uri
            assert entry["parity_bucket"] not in {"live-tested", "sandbox-mutating-tested"}, uri
            assert evidence["counts_as_behavioral"] is False, uri
            assert evidence["counts_as_live_behavioral"] is False, uri

    assert waql["summary"]["version"] == VERSION_2023
    assert waql["summary"]["coverage_status"] == "live-tested"
    assert waql["summary"]["live_tested_cases"] == 8
    assert waql["metadata"]["schema_source"] == "resources/manifest/2023.1/schemas.json#ak.wwise.core.object.get"
    assert waql["metadata"]["comparison_only_sources"] == [
        "resources/waql/2022.1/object-get-live-matrix.json format only",
        "No 2022.1 evidence paths are reused as 2023.1 proof.",
    ]
    assert all(
        case["coverage_status"] == "live-tested"
        and case["evidence_path"].startswith(".sisyphus/evidence/wwise-2023-test-parity/live-read-only/")
        for case in waql["live_cases"]
    )


def test_2023_fixture_tree_is_versioned_and_contains_no_committed_runtime_artifacts() -> None:
    metadata = _read_json(FIXTURE_2023 / "fixture-metadata.json")
    manifest = _read_json(FIXTURE_2023 / "fixture-manifest.json")

    assert metadata["fixture_root"] == "tests/_org/2023.1"
    assert metadata["wwise"]["version"] == VERSION_2023
    assert metadata["wwise"]["build"] == "2023.1.19.8928"
    assert metadata["provenance"]["source_path"].endswith("SampleProject2023.1.19.8928/SampleProject/SampleProject.wproj")
    assert manifest["file_count"] == metadata["hash_strategy"]["file_count"] == 65
    assert manifest["digest"] == metadata["hash_strategy"]["manifest_digest"]
    assert {Path(entry["path"]).suffix for entry in manifest["files"]} <= {".wproj", ".wwu", ".md"}

    runtime_suffixes = {".akd", ".bnk", ".wem", ".prof", ".profraw", ".validationcache", ".wsettings", ".log"}
    for entry in manifest["files"]:
        path = Path(entry["path"])
        assert path.suffix != ".md" or path.name == "README.md"
        assert path.suffix not in runtime_suffixes
        assert "GeneratedSoundBanks" not in path.parts
        assert "Logs" not in path.parts


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _count_by_key(entries: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        value = str(entry[key])
        counts[value] = counts.get(value, 0) + 1
    return counts


def _has_approved_2023_promotion_evidence(evidence: dict[str, Any]) -> bool:
    encoded_evidence = json.dumps(evidence, sort_keys=True)
    return any(source in encoded_evidence for source in APPROVED_2023_PROMOTION_EVIDENCE)


def _counts_with_summary_zeroes(counts: dict[str, int], summary_counts: dict[str, int]) -> dict[str, int]:
    return {key: counts.get(key, 0) for key in summary_counts}
