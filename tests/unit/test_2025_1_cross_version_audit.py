from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.common import BuilderFamily  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.source_notes import SemanticSourceNoteChecker  # pyright: ignore[reportMissingImports]
from wwise_waapi.dispatcher import DEFAULT_WWISE_VERSION, WwiseDispatcher  # pyright: ignore[reportMissingImports]
from wwise_waapi.manifest import ManifestStore, audit_manifest  # pyright: ignore[reportMissingImports]


ROOT = Path(__file__).resolve().parents[2]
VERSION_2022 = "2022.1"
VERSION_2025 = "2025.1"
BUILD_2025 = "2025.1.7.9143"
NOTEBOOK_2025 = "wwise-2025.1-docs"
MANIFEST_ROOT = ROOT / "resources" / "manifest"
MANIFEST_2025 = MANIFEST_ROOT / VERSION_2025
ADDED_SINCE_2024 = MANIFEST_2025 / "added-since-2024.1.json"
COVERAGE_2025 = ROOT / "resources" / "coverage" / VERSION_2025 / "api-coverage.json"
LIVE_MATRIX_2025 = ROOT / "resources" / "coverage" / VERSION_2025 / "live-coverage-matrix.json"
PHASE2_SUMMARY_2025 = ROOT / "resources" / "coverage" / VERSION_2025 / "phase2-coverage-summary.json"
POLICY_2025 = ROOT / "resources" / "coverage" / VERSION_2025 / "phase21-uri-policy.json"
DEFERRED_2025 = ROOT / "resources" / "deferred" / f"{VERSION_2025}.json"
SEMANTIC_2025 = ROOT / "resources" / "semantic" / VERSION_2025 / "source_notes.json"
REFERENCES_2025 = ROOT / "references" / "semantic" / VERSION_2025
WAQL_2025 = ROOT / "resources" / "waql" / VERSION_2025
GET_INFO_URI = "ak.wwise.core.getInfo"
EXPECTED_2025_AUDIT_COUNTS = (154, 31, 185, 0)
PROMOTED_2025_STATUSES = {"live-tested", "sandbox-mutating-tested"}
APPROVED_2025_PROMOTION_EVIDENCE = (
    ".sisyphus/evidence/wwise-2025-waapi-integration-coverage/",
    "resources/waql/2025.1/",
)
FORBIDDEN_2025_FALLBACK_FRAGMENTS = (
    ".sisyphus/evidence/wwise-2022",
    ".sisyphus/evidence/wwise-2023",
    ".sisyphus/evidence/wwise-2024",
    ".sisyphus/evidence/wwise-2025/",
    "resources/waql/2022.1",
    "resources/waql/2023.1",
    "resources/waql/2024.1",
    "resources/waql/2025/",
    "resources/manifest/2022.1",
    "resources/manifest/2023.1",
    "resources/manifest/2024.1",
    "resources/manifest/2025/",
    "resources/coverage/2022.1",
    "resources/coverage/2023.1",
    "resources/coverage/2024.1",
    "resources/coverage/2025/",
    "resources/deferred/2022.1",
    "resources/deferred/2023.1",
    "resources/deferred/2024.1",
    "resources/deferred/2025/",
    "resources/semantic/2022.1",
    "resources/semantic/2023.1",
    "resources/semantic/2024.1",
    "resources/semantic/2025/",
    "references/semantic/2022.1",
    "references/semantic/2023.1",
    "references/semantic/2024.1",
    "references/semantic/2025/",
    "references/semantic-builder-",
)
REQUIRED_2025_BEHAVIOR_MARKERS = ("2025.1", "behavior")
FRESH_2025_EXECUTION_MARKERS = ("live", "sandbox", "destructive", "waql")
NON_BEHAVIORAL_PROMOTION_MARKERS = (
    "manifest-only",
    "manifest reflection only",
    "skipped-test",
    "skipped test",
    "skipped live",
    "skipped destructive",
    "helper-only",
    "helper only",
    "notebooklm-only",
    "notebooklm only",
    "notebooklm is source evidence",
    "no behavior evidence",
)


def _reject_forbidden_2025_fallback(path: Path) -> None:
    path_text = path.as_posix()
    for fragment in FORBIDDEN_2025_FALLBACK_FRAGMENTS:
        if fragment in path_text:
            raise AssertionError(f"Explicit 2025.1 audit touched forbidden fallback resource: {path_text}")


def test_default_dispatcher_remains_2022_1_and_explicit_2025_1_dispatch_succeeds() -> None:
    store = ManifestStore(root=MANIFEST_ROOT)
    manifest_2025 = store.load(VERSION_2025)
    audit = audit_manifest(manifest_2025)

    assert DEFAULT_WWISE_VERSION == VERSION_2022
    assert manifest_2025["metadata"]["version_key"] == VERSION_2025
    assert manifest_2025["metadata"]["wwise_version_target"] == VERSION_2025
    assert manifest_2025["metadata"]["wwise_build"] == BUILD_2025
    assert (
        audit.manifest_function_count,
        audit.manifest_topic_count,
        audit.schema_count,
        audit.schema_failure_count,
    ) == EXPECTED_2025_AUDIT_COUNTS

    dispatcher = WwiseDispatcher(manifest_store=store)
    default_result = dispatcher.dispatch(GET_INFO_URI, dry_run=True)
    explicit_2025_result = dispatcher.dispatch(GET_INFO_URI, version=VERSION_2025, dry_run=True)

    assert default_result["ok"] is True
    assert default_result["version"] == VERSION_2022
    assert explicit_2025_result["ok"] is True
    assert explicit_2025_result["version"] == VERSION_2025
    assert explicit_2025_result["result"]["dry_run"] is True


def test_explicit_2025_1_resource_lookups_never_read_prior_bare_or_global_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_exists: Callable[..., bool] = Path.exists
    original_read_text: Callable[..., str] = Path.read_text
    touched: list[str] = []

    def guarded_exists(path: Path, *args: Any, **kwargs: Any) -> bool:
        path_text = path.as_posix()
        touched.append(path_text)
        _reject_forbidden_2025_fallback(path)
        return original_exists(path, *args, **kwargs)

    def guarded_read_text(path: Path, *args: Any, **kwargs: Any) -> str:
        path_text = path.as_posix()
        touched.append(path_text)
        _reject_forbidden_2025_fallback(path)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", guarded_exists)
    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    store = ManifestStore(root=MANIFEST_ROOT)
    manifest = store.load(VERSION_2025)
    dispatch_result = WwiseDispatcher(manifest_store=store).dispatch(GET_INFO_URI, version=VERSION_2025, dry_run=True)
    added_inventory = _read_json(ADDED_SINCE_2024)
    coverage = _read_json(COVERAGE_2025)
    matrix = _read_json(LIVE_MATRIX_2025)
    summary = _read_json(PHASE2_SUMMARY_2025)
    policy = _read_json(POLICY_2025)
    deferred = _read_json(DEFERRED_2025)
    source_note_status = SemanticSourceNoteChecker(notebook_id=NOTEBOOK_2025).check(
        BuilderFamily.QUERY.value,
        version=VERSION_2025,
    )

    assert manifest["metadata"]["version_key"] == VERSION_2025
    assert dispatch_result["ok"] is True
    assert dispatch_result["version"] == VERSION_2025
    assert added_inventory["metadata"]["target_version"] == VERSION_2025
    assert coverage["metadata"]["version"] == VERSION_2025
    assert matrix["metadata"]["version"] == VERSION_2025
    assert summary["metadata"]["version"] == VERSION_2025
    assert policy["metadata"]["version"] == VERSION_2025
    assert deferred["metadata"]["version"] == VERSION_2025
    assert source_note_status.allowed is True
    assert source_note_status.version == VERSION_2025
    assert source_note_status.error_code is None
    assert source_note_status.reason == "Semantic source note is grounded."
    assert any("resources/manifest/2025.1/manifest.json" in path for path in touched)
    assert any("resources/manifest/2025.1/functions.json" in path for path in touched)
    assert any("resources/manifest/2025.1/topics.json" in path for path in touched)
    assert any("resources/manifest/2025.1/schemas.json" in path for path in touched)
    assert any("resources/manifest/2025.1/added-since-2024.1.json" in path for path in touched)
    assert any("resources/coverage/2025.1/api-coverage.json" in path for path in touched)
    assert any("resources/coverage/2025.1/live-coverage-matrix.json" in path for path in touched)
    assert any("resources/coverage/2025.1/phase2-coverage-summary.json" in path for path in touched)
    assert any("resources/coverage/2025.1/phase21-uri-policy.json" in path for path in touched)
    assert any("resources/deferred/2025.1.json" in path for path in touched)
    assert any("resources/semantic/2025.1/source_notes.json" in path for path in touched)
    assert not any(
        any(fragment in path for fragment in FORBIDDEN_2025_FALLBACK_FRAGMENTS)
        for path in touched
    )


def test_bare_2025_manifest_placeholder_has_no_payload_files() -> None:
    bare_2025 = MANIFEST_ROOT / "2025"
    payloads = []
    if bare_2025.exists():
        payloads = [path for path in bare_2025.iterdir() if path.name != ".gitkeep"]

    assert payloads == []


def test_2025_coverage_policy_deferred_source_notes_docs_and_optional_waql_reconcile() -> None:
    manifest = ManifestStore(root=MANIFEST_ROOT).load(VERSION_2025)
    coverage = _read_json(COVERAGE_2025)
    live_matrix = _read_json(LIVE_MATRIX_2025)
    phase2_summary = _read_json(PHASE2_SUMMARY_2025)
    policy = _read_json(POLICY_2025)
    deferred = _read_json(DEFERRED_2025)
    source_notes = _read_json(SEMANTIC_2025)

    _assert_2025_resources_reconcile(manifest, coverage, live_matrix, phase2_summary, policy, deferred, source_notes)


@pytest.mark.parametrize(
    ("case_name", "evidence_update"),
    [
        ("stale-2022-path", {"evidence_path": ".sisyphus/evidence/wwise-2022-live/object-get.txt"}),
        ("stale-2023-path", {"evidence_path": "resources/waql/2023.1/object-get-live-matrix.json"}),
        ("stale-2024-text", {"evidence_path": "resources/waql/2025.1/object-get-live.json", "fixture_prerequisites": ["2024.1 copied sandbox proof"]}),
        ("bare-2025-coverage-path", {"evidence_path": "resources/coverage/2025/object-get-live.json"}),
        ("bare-2025-waql-path", {"evidence_path": "resources/waql/2025/object-get-live.json"}),
        ("bare-2025-semantic-path", {"evidence_path": "references/semantic/2025/object-get-live.md"}),
        ("bare-2025-evidence-path", {"evidence_path": ".sisyphus/evidence/wwise-2025/object-get-live.txt"}),
        ("approved-root-only", {"evidence_path": "resources/waql/2025.1/"}),
        ("manifest-only-proof", {"evidence_path": "resources/waql/2025.1/object-get-live.json", "evidence_standard": "manifest-only proof"}),
        ("skipped-test-proof", {"evidence_path": "resources/waql/2025.1/object-get-live.json", "fixture_prerequisites": ["skipped-test proof"]}),
        ("helper-only-proof", {"evidence_path": "resources/waql/2025.1/object-get-live.json", "evidence_standard": "helper-only proof"}),
        ("notebooklm-only-proof", {"evidence_path": "resources/waql/2025.1/object-get-live.json", "evidence_standard": "NotebookLM-only proof"}),
    ],
)
def test_2025_promoted_behavior_evidence_rejects_stale_or_non_behavioral_proof(
    case_name: str,
    evidence_update: dict[str, Any],
) -> None:
    manifest = ManifestStore(root=MANIFEST_ROOT).load(VERSION_2025)
    coverage = _read_json(COVERAGE_2025)
    live_matrix = _read_json(LIVE_MATRIX_2025)
    phase2_summary = _read_json(PHASE2_SUMMARY_2025)
    policy = _read_json(POLICY_2025)
    deferred = _read_json(DEFERRED_2025)
    source_notes = _read_json(SEMANTIC_2025)
    uri = "ak.wwise.core.object.get"

    _promote_local_fixture(coverage, live_matrix, phase2_summary, policy, deferred, uri, evidence_update)

    with pytest.raises(AssertionError, match=case_name.replace("-", ".*")):
        _assert_2025_resources_reconcile(
            manifest,
            coverage,
            live_matrix,
            phase2_summary,
            policy,
            deferred,
            source_notes,
            failure_context=case_name,
        )


def test_2025_promoted_behavior_evidence_requires_approved_2025_root_and_fresh_behavior_text() -> None:
    manifest = ManifestStore(root=MANIFEST_ROOT).load(VERSION_2025)
    coverage = _read_json(COVERAGE_2025)
    live_matrix = _read_json(LIVE_MATRIX_2025)
    phase2_summary = _read_json(PHASE2_SUMMARY_2025)
    policy = _read_json(POLICY_2025)
    deferred = _read_json(DEFERRED_2025)
    source_notes = _read_json(SEMANTIC_2025)
    uri = "ak.wwise.core.object.get"

    _promote_local_fixture(
        coverage,
        live_matrix,
        phase2_summary,
        policy,
        deferred,
        uri,
        {
            "evidence_path": "resources/waql/2025.1/object-get-live-matrix.json",
            "evidence_standard": "Fresh 2025.1 live behavior evidence from read-only WAQL execution.",
            "fixture_prerequisites": [
                ".sisyphus/evidence/wwise-2025-waapi-integration-coverage/live/object-get.txt"
            ],
        },
    )

    _assert_2025_resources_reconcile(manifest, coverage, live_matrix, phase2_summary, policy, deferred, source_notes)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_2025_resources_reconcile(
    manifest: dict[str, Any],
    coverage: dict[str, Any],
    live_matrix: dict[str, Any],
    phase2_summary: dict[str, Any],
    policy: dict[str, Any],
    deferred: dict[str, Any],
    source_notes: dict[str, Any],
    *,
    failure_context: str = "2025-parity",
) -> None:
    reflected_function_uris = sorted(entry["uri"] for entry in manifest["functions"])
    reflected_topic_uris = sorted(entry["uri"] for entry in manifest["topics"])
    coverage_entries = coverage["coverage"]
    matrix_entries = live_matrix["matrix"]
    summary_entries = phase2_summary["entries"]
    deferred_entries = deferred["deferred"]
    coverage_by_uri = {entry["uri"]: entry for entry in coverage_entries}
    matrix_by_uri = {entry["uri"]: entry for entry in matrix_entries}
    summary_by_uri = {entry["uri"]: entry for entry in summary_entries}
    deferred_by_uri = {entry["uri"]: entry for entry in deferred_entries}
    expected_status_counts = _counts_with_summary_zeroes(
        dict(Counter(entry["coverage_status"] for entry in coverage_entries)),
        coverage["summary"]["status_counts"],
    )
    expected_parity_counts = _counts_with_summary_zeroes(
        dict(Counter(entry["parity_bucket"] for entry in coverage_entries)),
        coverage["summary"]["parity_bucket_counts"],
    )
    expected_candidate_counts = dict(
        sorted(Counter(entry["candidate_status"] for entry in coverage_entries if entry["candidate_status"]).items())
    )
    expected_source_note_counts = dict(
        sorted(Counter(entry["source_note_family"] for entry in coverage_entries if entry["source_note_family"]).items())
    )
    promoted_uris = {
        entry["uri"]
        for entry in coverage_entries
        if entry["coverage_status"] in PROMOTED_2025_STATUSES or entry["parity_bucket"] in PROMOTED_2025_STATUSES
    }
    behavioral_uris = {entry["uri"] for entry in matrix_entries if entry["counts_as_behavioral"] is True}
    live_behavioral_uris = {entry["uri"] for entry in matrix_entries if entry["counts_as_live_behavioral"] is True}

    assert len(reflected_function_uris) == EXPECTED_2025_AUDIT_COUNTS[0], failure_context
    assert len(reflected_topic_uris) == EXPECTED_2025_AUDIT_COUNTS[1], failure_context
    assert [entry["uri"] for entry in coverage_entries] == reflected_function_uris, failure_context
    assert [entry["uri"] for entry in matrix_entries] == reflected_function_uris, failure_context
    assert [entry["uri"] for entry in summary_entries] == reflected_function_uris, failure_context
    assert len(coverage_by_uri) == len(matrix_by_uri) == len(summary_by_uri) == len(reflected_function_uris), failure_context
    assert _version_set(coverage_entries) == {VERSION_2025}, failure_context
    assert _version_set(matrix_entries) == {VERSION_2025}, failure_context
    assert _version_set(summary_entries) == {VERSION_2025}, failure_context

    _assert_common_2025_metadata(coverage, live_matrix, phase2_summary, policy)
    _assert_common_2025_summary(coverage, expected_status_counts, expected_parity_counts, expected_candidate_counts, expected_source_note_counts, len(reflected_function_uris), failure_context)
    _assert_common_2025_summary(live_matrix, expected_status_counts, expected_parity_counts, expected_candidate_counts, expected_source_note_counts, len(reflected_function_uris), failure_context)
    _assert_common_2025_summary(phase2_summary, expected_status_counts, expected_parity_counts, expected_candidate_counts, expected_source_note_counts, len(reflected_function_uris), failure_context)
    _assert_common_2025_summary(policy, expected_status_counts, expected_parity_counts, expected_candidate_counts, expected_source_note_counts, len(reflected_function_uris), failure_context)
    assert live_matrix["summary"]["behavioral_covered_count"] == len(behavioral_uris), failure_context
    assert live_matrix["summary"]["live_behavioral_covered_count"] == len(live_behavioral_uris), failure_context
    assert phase2_summary["summary"]["behavioral_covered_count"] == len(behavioral_uris), failure_context
    assert phase2_summary["summary"]["live_behavioral_covered_count"] == len(live_behavioral_uris), failure_context

    assigned_policy_uris = [uri for uris in policy["policy"]["parity_buckets"].values() for uri in uris]
    assert sorted(assigned_policy_uris) == reflected_function_uris, failure_context
    assert len(assigned_policy_uris) == len(set(assigned_policy_uris)) == len(reflected_function_uris), failure_context
    for bucket, uris in policy["policy"]["parity_buckets"].items():
        assert policy["summary"]["parity_bucket_counts"][bucket] == len(uris), failure_context
        assert all(coverage_by_uri[uri]["parity_bucket"] == bucket for uri in uris), failure_context
    assert sorted(policy["policy"]["live_tested_uris"]) == sorted(
        uri for uri, entry in coverage_by_uri.items() if entry["coverage_status"] == "live-tested"
    ), failure_context
    assert sorted(policy["policy"]["sandbox_mutating_tested_uris"]) == sorted(
        uri for uri, entry in coverage_by_uri.items() if entry["coverage_status"] == "sandbox-mutating-tested"
    ), failure_context
    assert sorted(policy["policy"]["deferred_uris"] + policy["policy"]["excluded_uris"]) == sorted(
        uri for uri, entry in coverage_by_uri.items() if entry["coverage_status"] in {"deferred", "excluded"}
    ), failure_context
    assert sorted(
        policy["policy"]["manifest_only_uris"]
        + policy["policy"]["live_tested_uris"]
        + policy["policy"]["sandbox_mutating_tested_uris"]
    ) == reflected_function_uris, failure_context

    blocked_uris = {
        entry["uri"]
        for entry in coverage_entries
        if entry["coverage_status"] in {"deferred", "excluded"}
    }
    assert set(deferred_by_uri) == blocked_uris, failure_context
    assert deferred["summary"]["total"] == len(blocked_uris), failure_context
    assert deferred["summary"]["status_counts"] == _count_by_key(deferred_entries, "coverage_status"), failure_context
    assert _version_set(deferred_entries) == {VERSION_2025}, failure_context
    assert all("resources/manifest/2025.1" in entry["evidence_source"] for entry in deferred_entries), failure_context

    source_note_uris = {uri for note in source_notes["notes"].values() for uri in note["endpoints"]}
    reflected_uris = set(reflected_function_uris) | set(reflected_topic_uris)
    assert source_notes["version"] == VERSION_2025, failure_context
    assert source_notes["notebook_id"] == NOTEBOOK_2025, failure_context
    assert source_note_uris <= reflected_uris, failure_context
    for family, note in source_notes["notes"].items():
        assert note["status"] == "grounded", failure_context
        assert note["notebook_id"] == NOTEBOOK_2025, failure_context
        assert note["version_target"] == VERSION_2025, failure_context
        assert note["gate_evidence_path"] == "references/semantic/2025.1/semantic-builder-notebooklm-gate.md", failure_context
        assert set(note["required_fields"]) <= set(note["cited_required_fields"]), failure_context
        for evidence_path in [source_notes["protocol"], note["gate_evidence_path"], *note["source_urls"]]:
            assert evidence_path.startswith("references/semantic/2025.1/"), failure_context
            assert (ROOT / evidence_path).is_file(), failure_context
            assert not _has_forbidden_2025_text(evidence_path), failure_context
        for uri in note["endpoints"]:
            if uri in coverage_by_uri:
                assert coverage_by_uri[uri]["source_note_family"] == family, failure_context

    _assert_2025_reference_docs_are_versioned(failure_context)
    _assert_optional_2025_waql_resources_are_versioned(failure_context)

    for uri, entry in coverage_by_uri.items():
        matrix_entry = matrix_by_uri[uri]
        summary_entry = summary_by_uri[uri]
        evidence = entry["behavioral_evidence"]
        assert matrix_entry["coverage_status"] == entry["coverage_status"], failure_context
        assert summary_entry["coverage_status"] == entry["coverage_status"], failure_context
        assert matrix_entry["parity_bucket"] == entry["parity_bucket"], failure_context
        assert summary_entry["parity_bucket"] == entry["parity_bucket"], failure_context
        assert matrix_entry["counts_as_behavioral"] == evidence["counts_as_behavioral"], failure_context
        assert matrix_entry["counts_as_live_behavioral"] == evidence["counts_as_live_behavioral"], failure_context
        assert summary_entry["counts_as_behavioral"] == evidence["counts_as_behavioral"], failure_context
        assert summary_entry["counts_as_live_behavioral"] == evidence["counts_as_live_behavioral"], failure_context
        assert entry["schema_mapping"]["manifest_uri"].startswith("resources/manifest/2025.1/"), failure_context
        assert matrix_entry["manifest_source_uri"].startswith("resources/manifest/2025.1/"), failure_context
        assert matrix_entry["source_coverage_uri"] == "resources/coverage/2025.1/api-coverage.json", failure_context
        assert summary_entry["source_coverage_uri"] == "resources/coverage/2025.1/api-coverage.json", failure_context

        is_promoted = (
            uri in promoted_uris
            or matrix_entry["achieved_status"] in PROMOTED_2025_STATUSES
            or summary_entry["achieved_status"] in PROMOTED_2025_STATUSES
            or evidence["counts_as_behavioral"] is True
            or evidence["counts_as_live_behavioral"] is True
        )
        if is_promoted:
            assert evidence["manifest_reflection_only"] is False, f"{failure_context}: manifest-only promotion {uri}"
            _assert_fresh_2025_behavioral_promotion(entry, matrix_entry, summary_entry, failure_context=failure_context)
        else:
            assert entry["coverage_status"] not in PROMOTED_2025_STATUSES, failure_context
            assert entry["parity_bucket"] not in PROMOTED_2025_STATUSES, failure_context
            assert matrix_entry["achieved_status"] not in PROMOTED_2025_STATUSES, failure_context
            assert summary_entry["achieved_status"] not in PROMOTED_2025_STATUSES, failure_context
            assert evidence["counts_as_behavioral"] is False, failure_context
            assert evidence["counts_as_live_behavioral"] is False, failure_context


def _assert_common_2025_metadata(*payloads: dict[str, Any]) -> None:
    for payload in payloads:
        metadata = payload["metadata"]
        assert metadata["version"] == VERSION_2025
        assert metadata["manifest_source"] == "resources/manifest/2025.1"
        assert metadata["source_notes"] == "resources/semantic/2025.1/source_notes.json"
        assert metadata["task6_classification"] == "resources/coverage/2025.1/added-api-classification.json"
        assert metadata["no_promotion_from_manifest_only"] is True
        assert metadata["no_reuse_of_2024_behavior_evidence"] is True
        assert metadata["baseline_comparison"]["policy"] == "2024.1 evidence is comparison metadata only and never counts as 2025.1 proof."


def _assert_common_2025_summary(
    payload: dict[str, Any],
    expected_status_counts: dict[str, int],
    expected_parity_counts: dict[str, int],
    expected_candidate_counts: dict[str, int],
    expected_source_note_counts: dict[str, int],
    reflected_count: int,
    failure_context: str,
) -> None:
    summary = payload["summary"]
    assert summary["reflected_count"] == reflected_count, failure_context
    assert summary["total_functions"] == reflected_count, failure_context
    assert summary["implemented"] == reflected_count, failure_context
    assert summary["manifest_only"] == reflected_count - summary["behavioral_supported"], failure_context
    assert summary["status_counts"] == expected_status_counts, failure_context
    assert summary["parity_bucket_counts"] == expected_parity_counts, failure_context
    assert summary["parity_bucket_total"] == reflected_count, failure_context
    assert summary["candidate_status_counts"] == expected_candidate_counts, failure_context
    assert summary["source_note_family_counts"] == expected_source_note_counts, failure_context
    assert summary["forbidden_promoted_counts"] == {
        status: expected_status_counts.get(status, 0) for status in PROMOTED_2025_STATUSES
    }, failure_context


def _assert_fresh_2025_behavioral_promotion(*objects: dict[str, Any], failure_context: str) -> None:
    encoded = json.dumps(objects, sort_keys=True).lower()
    evidence_text = _promotion_evidence_text(*objects)
    assert any(root.lower() in encoded for root in APPROVED_2025_PROMOTION_EVIDENCE), (
        f"{failure_context}: missing approved 2025.1 behavior evidence root"
    )
    assert not _has_forbidden_2025_text(encoded), f"{failure_context}: stale or bare-version evidence path"
    assert not any(stale in evidence_text for stale in ("2022.1", "2023.1", "2024.1")), (
        f"{failure_context}: stale evidence text"
    )
    assert not any(f'"{root.lower()}"' in evidence_text for root in APPROVED_2025_PROMOTION_EVIDENCE), (
        f"{failure_context}: approved root alone is not behavioral proof"
    )
    for marker in REQUIRED_2025_BEHAVIOR_MARKERS:
        assert marker in evidence_text, f"{failure_context}: missing fresh behavior marker {marker}"
    assert any(marker in evidence_text for marker in FRESH_2025_EXECUTION_MARKERS), (
        f"{failure_context}: missing fresh 2025.1 execution marker"
    )
    for marker in NON_BEHAVIORAL_PROMOTION_MARKERS:
        assert marker not in evidence_text, f"{failure_context}: non-behavioral proof marker {marker}"


def _promotion_evidence_text(*objects: dict[str, Any]) -> str:
    evidence_fields: list[Any] = []
    for obj in objects:
        evidence_fields.extend(
            obj.get(key)
            for key in ("evidence_path", "evidence_standard", "fixture_prerequisites")
            if key in obj
        )
        behavioral_evidence = obj.get("behavioral_evidence")
        if isinstance(behavioral_evidence, dict):
            evidence_fields.extend(
                behavioral_evidence.get(key)
                for key in ("evidence", "evidence_standard", "test")
                if key in behavioral_evidence
            )
    return json.dumps(evidence_fields, sort_keys=True).lower()


def _assert_2025_reference_docs_are_versioned(failure_context: str) -> None:
    references = sorted(REFERENCES_2025.glob("*.md"))
    assert references, failure_context
    for reference in references:
        text = reference.read_text(encoding="utf-8")
        assert "wwise-2025.1-docs" in text or reference.name == "discrepancy-register.md", failure_context
        assert "references/semantic/2025/" not in text, failure_context
        assert "resources/semantic/2025/" not in text, failure_context
        assert "resources/coverage/2025/" not in text, failure_context
        assert "resources/waql/2025/" not in text, failure_context
        assert "references/semantic-builder-" not in text, failure_context
        assert "wwise-2022.1-docs" not in text, failure_context
        assert "wwise-2023.1-docs" not in text, failure_context
        assert "wwise-2024.1-docs" not in text, failure_context


def _assert_optional_2025_waql_resources_are_versioned(failure_context: str) -> None:
    if not WAQL_2025.exists():
        return
    for resource in sorted(path for path in WAQL_2025.rglob("*") if path.is_file()):
        text = resource.read_text(encoding="utf-8")
        assert "2025.1" in text, failure_context
        assert not _has_forbidden_2025_text(resource.as_posix()), failure_context
        assert not _has_forbidden_2025_text(text), failure_context


def _promote_local_fixture(
    coverage: dict[str, Any],
    live_matrix: dict[str, Any],
    phase2_summary: dict[str, Any],
    policy: dict[str, Any],
    deferred: dict[str, Any],
    uri: str,
    evidence_update: dict[str, Any],
) -> None:
    coverage_entry = _entry_by_uri(coverage["coverage"], uri)
    matrix_entry = _entry_by_uri(live_matrix["matrix"], uri)
    summary_entry = _entry_by_uri(phase2_summary["entries"], uri)
    status = "live-tested"
    for entry in (coverage_entry, matrix_entry, summary_entry):
        entry["coverage_status"] = status
        entry["parity_bucket"] = status
        entry["achieved_status"] = status
        entry["counts_as_behavioral"] = True
        entry["counts_as_live_behavioral"] = True
        entry.update(deepcopy(evidence_update))
    coverage_entry["test_status"] = status
    coverage_entry["behavioral_evidence"]["coverage"] = status
    coverage_entry["behavioral_evidence"]["parity_bucket"] = status
    coverage_entry["behavioral_evidence"]["manifest_reflection_only"] = False
    coverage_entry["behavioral_evidence"]["counts_as_behavioral"] = True
    coverage_entry["behavioral_evidence"]["counts_as_live_behavioral"] = True
    if "evidence_standard" in evidence_update:
        coverage_entry["behavioral_evidence"]["evidence"] = evidence_update["evidence_standard"]
    coverage_entry["behavioral_evidence"].update(deepcopy(evidence_update))
    summary_entry["manifest_reflection_only"] = False
    if uri in policy["policy"]["deferred_uris"]:
        policy["policy"]["deferred_uris"].remove(uri)
    if uri in policy["policy"]["manifest_only_uris"]:
        policy["policy"]["manifest_only_uris"].remove(uri)
    if uri in policy["policy"]["parity_buckets"]["deferred"]:
        policy["policy"]["parity_buckets"]["deferred"].remove(uri)
    policy["policy"]["live_tested_uris"].append(uri)
    policy["policy"]["parity_buckets"][status].append(uri)
    deferred["deferred"] = [entry for entry in deferred["deferred"] if entry["uri"] != uri]
    _refresh_summaries(coverage, live_matrix, phase2_summary, policy, deferred)


def _refresh_summaries(
    coverage: dict[str, Any],
    live_matrix: dict[str, Any],
    phase2_summary: dict[str, Any],
    policy: dict[str, Any],
    deferred: dict[str, Any],
) -> None:
    coverage_entries = coverage["coverage"]
    status_counts = _counts_with_summary_zeroes(
        dict(Counter(entry["coverage_status"] for entry in coverage_entries)),
        coverage["summary"]["status_counts"],
    )
    parity_counts = _counts_with_summary_zeroes(
        dict(Counter(entry["parity_bucket"] for entry in coverage_entries)),
        coverage["summary"]["parity_bucket_counts"],
    )
    behavioral_supported = len(
        [entry for entry in coverage_entries if entry["behavioral_evidence"]["counts_as_behavioral"] is True]
    )
    manifest_only = len(coverage_entries) - behavioral_supported
    for payload in (coverage, live_matrix, phase2_summary, policy):
        payload["summary"]["status_counts"] = status_counts
        payload["summary"]["parity_bucket_counts"] = parity_counts
        payload["summary"]["behavioral_supported"] = behavioral_supported
        payload["summary"]["manifest_only"] = manifest_only
        payload["summary"]["live_tested"] = status_counts["live-tested"]
        payload["summary"]["forbidden_promoted_counts"] = {
            status: status_counts[status] for status in PROMOTED_2025_STATUSES
        }
        if "behavioral_covered_count" in payload["summary"]:
            payload["summary"]["behavioral_covered_count"] = behavioral_supported
            payload["summary"]["live_behavioral_covered_count"] = behavioral_supported
    deferred["summary"]["total"] = len(deferred["deferred"])
    deferred["summary"]["status_counts"] = dict(sorted(Counter(entry["coverage_status"] for entry in deferred["deferred"]).items()))


def _entry_by_uri(entries: list[dict[str, Any]], uri: str) -> dict[str, Any]:
    return next(entry for entry in entries if entry["uri"] == uri)


def _version_set(entries: list[dict[str, Any]]) -> set[str]:
    return {entry["version"] for entry in entries}


def _count_by_key(entries: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        value = str(entry[key])
        counts[value] = counts.get(value, 0) + 1
    return counts


def _counts_with_summary_zeroes(counts: dict[str, int], summary_counts: dict[str, int]) -> dict[str, int]:
    return {key: counts.get(key, 0) for key in summary_counts}


def _has_forbidden_2025_text(text: str) -> bool:
    lowered = text.lower()
    return any(fragment.lower() in lowered for fragment in FORBIDDEN_2025_FALLBACK_FRAGMENTS)
