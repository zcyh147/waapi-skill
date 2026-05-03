from __future__ import annotations

import copy
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION = "2025.1"
CLASSIFICATION_RESOURCE = REPO_ROOT / "skills" / "wwise-waapi" / "resources" / "coverage" / VERSION / "added-api-classification.json"
INVENTORY_RESOURCE = REPO_ROOT / "skills" / "wwise-waapi" / "resources" / "manifest" / VERSION / "added-since-2024.1.json"
SOURCE_NOTES_RESOURCE = REPO_ROOT / "skills" / "wwise-waapi" / "resources" / "semantic" / VERSION / "source_notes.json"
DISCREPANCY_REGISTER = REPO_ROOT / "references" / "semantic" / VERSION / "discrepancy-register.md"

ALLOWED_STATUSES = {
    "candidate-live-read-only",
    "candidate-sandbox-mutating",
    "deferred",
    "excluded",
}
FORBIDDEN_PROMOTED_STATUSES = {"live-tested", "sandbox-mutating-tested"}
DEFER_BY_DEFAULT_REASONS = {
    "docs_reflection_mismatch",
    "fixture_state_gap",
    "generated_soundbank_required",
    "missing_source_evidence",
    "profiler_session_required",
    "unsafe_state",
    "unsupported_semantics",
}


def test_2025_added_api_classification_covers_inventory_exactly_once() -> None:
    payload = _classification_payload()
    entries = payload["classifications"]
    expected = _inventory_entries()

    assert payload["metadata"]["version"] == VERSION
    assert payload["metadata"]["inventory_source"] == "resources/manifest/2025.1/added-since-2024.1.json"
    assert payload["summary"]["inventory_total"] == len(expected) == 70
    assert [(entry["item_type"], entry["inventory_change"], entry["uri"]) for entry in entries] == expected
    assert len({entry["uri"] for entry in entries}) == len(entries)
    assert {entry["version"] for entry in entries} == {VERSION}


def test_2025_added_api_classification_uses_valid_status_and_reason_model() -> None:
    payload = _classification_payload()
    entries = payload["classifications"]
    policy = payload["metadata"]["policy"]

    assert set(payload["metadata"]["status_model"]) == ALLOWED_STATUSES
    assert set(policy["behavior_tested_statuses_forbidden"]) == FORBIDDEN_PROMOTED_STATUSES
    assert set(policy["defer_by_default_reason_codes"]) == DEFER_BY_DEFAULT_REASONS

    for entry in entries:
        assert entry["status"] in ALLOWED_STATUSES, entry["uri"]
        assert entry["status"] not in FORBIDDEN_PROMOTED_STATUSES, entry["uri"]
        assert entry["behavior_tested"] is False, entry["uri"]
        assert entry["reason_codes"], entry["uri"]
        assert entry["source_evidence"][0] == "resources/manifest/2025.1/added-since-2024.1.json", entry["uri"]
        assert "resources/semantic/2025.1/source_notes.json" in entry["source_evidence"] or "missing_source_evidence" in entry["reason_codes"], entry["uri"]
        assert "references/semantic/2025.1/discrepancy-register.md" in entry["source_evidence"], entry["uri"]

        if entry["reason_codes"] and DEFER_BY_DEFAULT_REASONS.intersection(entry["reason_codes"]):
            assert entry["status"] in {"deferred", "excluded", "candidate-sandbox-mutating"}, entry["uri"]
        if "missing_source_evidence" in entry["reason_codes"]:
            assert entry["status"] in {"deferred", "excluded"}, entry["uri"]
        if "docs_reflection_mismatch" in entry["reason_codes"]:
            assert entry["status"] == "deferred", entry["uri"]


def test_2025_candidate_entries_are_source_note_grounded_without_behavior_promotion() -> None:
    source_notes = _source_notes_payload()["notes"]
    source_families = set(source_notes)
    candidate_entries = [
        entry
        for entry in _classification_payload()["classifications"]
        if entry["status"] in {"candidate-live-read-only", "candidate-sandbox-mutating"}
    ]

    assert candidate_entries
    for entry in candidate_entries:
        assert entry["family"] in source_families, entry["uri"]
        assert "source_note_grounded" in entry["reason_codes"], entry["uri"]
        assert entry["behavior_tested"] is False, entry["uri"]
        assert not any(status in entry.values() for status in FORBIDDEN_PROMOTED_STATUSES), entry["uri"]


def test_2025_docs_reflection_mismatch_local_mutation_defers() -> None:
    payload = _classification_payload()
    source = next(entry for entry in payload["classifications"] if entry["status"] == "candidate-live-read-only")
    mutated = copy.deepcopy(source)
    mutated["reason_codes"] = ["source_note_grounded", "docs_reflection_mismatch"]
    mutated["status"] = _status_after_defer_policy(mutated, payload)

    assert mutated["status"] == "deferred"
    assert "docs_reflection_mismatch" in mutated["reason_codes"]
    assert payload["metadata"]["policy"]["docs_reflection_mismatch_default_status"] == "deferred"


def test_2025_semantic_caveats_remain_deferred_or_unpromoted() -> None:
    entries = {entry["uri"]: entry for entry in _classification_payload()["classifications"]}
    discrepancy_text = DISCREPANCY_REGISTER.read_text(encoding="utf-8")

    assert "object.structureChanged" in discrepancy_text
    assert "object.set" in discrepancy_text
    assert entries["ak.wwise.core.object.structureChanged"]["status"] == "candidate-live-read-only"
    assert entries["ak.wwise.core.object.set"]["status"] == "candidate-sandbox-mutating"
    assert "slot_wrapper_required" in entries["ak.wwise.core.object.set"]["reason_codes"]

    for uri in {
        "ak.wwise.core.object.childAdded",
        "ak.wwise.core.object.childRemoved",
        "ak.wwise.core.object.created",
        "ak.wwise.core.object.postDeleted",
        "ak.wwise.core.object.preDeleted",
    }:
        assert entries[uri]["status"] == "deferred", uri
        assert "docs_reflection_mismatch" in entries[uri]["reason_codes"], uri


def _classification_payload() -> dict:
    return json.loads(CLASSIFICATION_RESOURCE.read_text(encoding="utf-8"))


def _source_notes_payload() -> dict:
    return json.loads(SOURCE_NOTES_RESOURCE.read_text(encoding="utf-8"))


def _inventory_entries() -> list[tuple[str, str, str]]:
    manifest = json.loads(INVENTORY_RESOURCE.read_text(encoding="utf-8"))
    expected = []
    for section in ("functions", "topics"):
        for change_type in ("added", "changed"):
            for item in manifest[section][change_type]:
                expected.append((item["type"], change_type, item["uri"]))
    return expected


def _status_after_defer_policy(entry: dict, payload: dict) -> str:
    if "docs_reflection_mismatch" in entry["reason_codes"]:
        return payload["metadata"]["policy"]["docs_reflection_mismatch_default_status"]
    return entry["status"]
