from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
EVALS_JSON = ROOT / "evals" / "evals.json"
REFERENCE_ROOT = ROOT / "references"
SEMANTIC_2025_REFERENCES = REFERENCE_ROOT / "semantic" / "2025.1"
TASK12_REVIEW_PACKET = ROOT / ".sisyphus" / "evidence" / "wwise-2025-waapi-integration-coverage" / "parity-review-packet.md"
COVERAGE_2025 = ROOT / "tests" / "destructive" / "support" / "resources" / "capabilities" / "2025.1" / "api-coverage.json"
LIVE_MATRIX_2025 = ROOT / "tests" / "destructive" / "support" / "resources" / "capabilities" / "2025.1" / "live-coverage-matrix.json"
DEFERRED_2025 = ROOT / "skills" / "waapi-skill" / "resources" / "deferred" / "2025.1.json"
CLASSIFICATION_2025 = ROOT / "tests" / "destructive" / "support" / "resources" / "capabilities" / "2025.1" / "added-api-classification.json"
DOC_PATHS = (
    ROOT / "skills" / "waapi-skill" / "SKILL.md",
    *sorted(REFERENCE_ROOT.glob("*.md")),
    *sorted(SEMANTIC_2025_REFERENCES.glob("*.md")),
    TASK12_REVIEW_PACKET,
)
DOC_CONTRACT_PATHS = (
    ROOT / "skills" / "waapi-skill" / "SKILL.md",
    ROOT / "references" / "long-run-runbook.md",
    ROOT / "references" / "eval-review-workflow.md",
    ROOT / "references" / "phase2-user-review-packet.md",
    TASK12_REVIEW_PACKET,
)
WWISE_2025_CONSOLE = "/Applications/Audiokinetic/Wwise2025.1.7.9143/Wwise.app/Contents/Tools/WwiseConsole.sh"
WWISE_2025_SAMPLE_PROJECT = "/Applications/Audiokinetic/SampleProject2025.1.7.9143/SampleProject/SampleProject.wproj"
LIVE_2025_READ_ONLY_COMMAND = (
    'WWISE_VERSION=2025.1 WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2025.1.7.9143/Wwise.app/Contents/Tools/WwiseConsole.sh" '
    'WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2025.1.7.9143/SampleProject/SampleProject.wproj" '
    "WWISE_READINESS_TIMEOUT=180 WWISE_LIVE=1 python -m pytest tests/live/test_2025_1_live_prerequisites.py "
    "tests/live/test_2025_1_reflection_inventory.py tests/live/test_2025_1_waql_live_matrix.py -q"
)
DESTRUCTIVE_2025_COMMAND = (
    'WWISE_VERSION=2025.1 WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2025.1.7.9143/Wwise.app/Contents/Tools/WwiseConsole.sh" '
    'WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2025.1.7.9143/SampleProject/SampleProject.wproj" '
    "WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes/2025.1 WWISE_READINESS_TIMEOUT=180 WWISE_LIVE=1 WWISE_DESTRUCTIVE=1 "
    "python -m pytest tests/destructive/test_2025_1_project_mutation_sandbox.py "
    "tests/destructive/test_2025_1_soundbank_audio_sandbox.py "
    "tests/destructive/test_2025_1_switchcontainer_assignment_sandbox.py -q"
)
PROMOTED_2025_MUTATING_APIS = {
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
FORBIDDEN_2025_POSITIVE_CLAIMS = (
    "all 2025.1 APIs are live-tested",
    "all 2025.1 APIs are behavior-tested",
    "all 2025.1 APIs are fully behavior-tested",
    "complete 2025.1 support",
    "full 2025.1 support",
    "full support for 2025.1",
    "full 2025.1 WAAPI behavioral coverage",
    "2025.1 full WAAPI coverage",
    "2025.1 full WAAPI behavioral coverage",
    "manifest reflection proves 2025.1 behavior",
    "manifest reflection is 2025.1 live evidence",
    "all 2025.1 APIs are live tested",
    "all 2025.1 APIs are behavior tested",
    "skipped live tests prove 2025.1 behavior",
    "skipped destructive tests prove 2025.1 behavior",
    "skipped tests prove 2025.1 behavior",
    "2024 evidence proves 2025.1 behavior",
    "NotebookLM-only text proves 2025.1 behavior",
    "macOS evidence validates Windows",
    "macOS evidence is Windows validation",
    "macOS run validates Windows",
)
FORBIDDEN_2025_STALE_PROOF_PATTERNS = (
    re.compile(
        r"(resources/(?:manifest|coverage|semantic)/(?:2022\.1|2023\.1|2024\.1)|"
        r"resources/deferred/(?:2022\.1|2023\.1|2024\.1)\.json|"
        r"references/semantic/(?:2022\.1|2023\.1|2024\.1)|"
        r"references/semantic-builder-|"
        r"wwise-202[234]\.1-docs)"
        r".{0,120}(?:proves?|proof|evidence|support|coverage).{0,120}2025\.1",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"2025\.1.{0,120}(?:proves?|proof|evidence|support|coverage).{0,120}"
        r"(resources/(?:manifest|coverage|semantic)/(?:2022\.1|2023\.1|2024\.1)|"
        r"resources/deferred/(?:2022\.1|2023\.1|2024\.1)\.json|"
        r"references/semantic/(?:2022\.1|2023\.1|2024\.1)|"
        r"references/semantic-builder-|"
        r"wwise-202[234]\.1-docs)",
        re.IGNORECASE | re.DOTALL,
    ),
)


def test_2025_docs_and_evals_reject_no_overclaim_phrases() -> None:
    combined = _combined_docs_and_evals_text().lower()

    for claim in FORBIDDEN_2025_POSITIVE_CLAIMS:
        assert claim.lower() not in combined

    for phrase in (
        "fully behavior-tested 2025.1",
        "2025.1 APIs are fully behavior-tested",
        "2025.1 support is complete",
        "2025.1 manifest reflection proves live behavior",
        "all APIs live-tested for 2025.1",
        "Windows validation passed from macOS",
    ):
        assert phrase.lower() not in combined


def test_2025_claims_do_not_use_prior_versions_or_global_paths_as_proof() -> None:
    surfaces = _claim_surfaces()
    assert any(path == TASK12_REVIEW_PACKET for path, _ in surfaces)

    for path, text in surfaces:
        for pattern in FORBIDDEN_2025_STALE_PROOF_PATTERNS:
            assert pattern.search(text) is None, path


def test_2025_docs_include_exact_counts_paths_commands_and_limited_claims() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in DOC_CONTRACT_PATHS)
    counts = _resource_counts()

    assert counts == {
        "coverage_total": 185,
        "live_total": 154,
        "deferred_total": 143,
        "coverage_status": {"excluded": 48, "deferred": 126, "sandbox-mutating-tested": 10, "live-tested": 1},
        "coverage_item_type": {"function": 154, "topic": 31},
        "classification_total": 70,
        "classification_item_type": {"function": 59, "topic": 11},
        "classification_inventory_change": {"added": 7, "changed": 63},
        "classification_status": {"deferred": 33, "excluded": 16, "candidate-sandbox-mutating": 14, "candidate-live-read-only": 7},
    }

    assert WWISE_2025_CONSOLE in combined
    assert WWISE_2025_SAMPLE_PROJECT in combined
    assert "python -m pytest -q" in combined
    assert _squash_command(LIVE_2025_READ_ONLY_COMMAND) in _squash_command(combined)
    assert _squash_command(DESTRUCTIVE_2025_COMMAND) in _squash_command(combined)

    assert "complete reflected inventory and parity classification for 154 functions" in combined
    assert "topic inventory is now present" in combined
    assert "topic inventory rows are inventory/substitute accounting only until fresh active live topic evidence exists" in combined
    assert "one live read-only URI" in combined
    assert "ten copied-sandbox mutating URIs" in combined
    assert "143" in combined
    assert "95 deferred" in combined
    assert "48 excluded" in combined
    assert "2024 evidence is comparison metadata only" in combined
    assert "Wwise 2023.1, 2024.1, and 2025.1 are supported only where versioned manifests" in combined
    assert "resources/manifest/2025.1/" in combined
    assert "resources/semantic/2025.1/source_notes.json" in combined
    assert "tests/destructive/support/resources/capabilities/2025.1/" in combined
    assert "skipped live or destructive tests" in combined
    assert "NotebookLM-only text" in combined
    assert "not runtime proof" in combined
    assert "Windows validation remains a caveat" in combined or "Windows remains a caveat" in combined
    assert "ak.wwise.core.object.get" in combined
    assert "ak.wwise.core.soundbank.getInclusions" in combined
    assert "ak.wwise.core.switchContainer.getAssignments" in combined
    assert "remain unpromoted" in combined

    for api in PROMOTED_2025_MUTATING_APIS:
        assert api in combined


def test_2025_eval_examples_are_version_scoped_when_added() -> None:
    payload = json.loads(EVALS_JSON.read_text(encoding="utf-8"))
    entries = [entry for entry in payload["evals"] if entry["id"].startswith("2025-")]

    assert {entry["id"] for entry in entries} == {
        "2025-parity-review-version-scoped-summary",
        "2025-live-and-destructive-command-review",
    }

    for entry in entries:
        serialized = json.dumps(entry, sort_keys=True)
        lowered = serialized.lower()
        assert "2025.1" in serialized, entry["id"]
        assert any("2025.1" in file_path for file_path in entry["files"]), entry["id"]
        assert "references/semantic-builder-" not in serialized, entry["id"]
        assert "resources/manifest/2022.1" not in serialized, entry["id"]
        assert "resources/manifest/2023.1" not in serialized, entry["id"]
        assert "resources/manifest/2024.1" not in serialized, entry["id"]
        assert "wwise-2024.1-docs proves 2025.1" not in serialized, entry["id"]
        assert "macOS run validates Windows" not in serialized, entry["id"]
        for claim in FORBIDDEN_2025_POSITIVE_CLAIMS:
            assert claim.lower() not in lowered, entry["id"]


def test_task12_review_packet_has_required_sections_counts_and_limited_claims() -> None:
    packet = TASK12_REVIEW_PACKET.read_text(encoding="utf-8")

    assert [
        line.removeprefix("## ")
        for line in packet.splitlines()
        if line.startswith("## ")
    ] == [
        "Promoted Evidence",
        "Deferred/Excluded",
        "2025-Only Classification",
        "NotebookLM and Docs Caveats",
        "Commands Run",
        "Task 14 Final Reconciliation",
        "Source Immutability",
        "Windows Caveat",
        "Known Non-Goals",
    ]

    assert "reconcile to 154 functions" in packet
    assert "one live read-only URI and ten copied-sandbox mutating URIs" in packet
    assert "ak.wwise.core.object.get" in packet
    assert packet.count("promoted to `live-tested`") == 1
    assert "143 entries deferred or excluded" in packet
    assert "95 deferred entries and 48 excluded entries" in packet
    assert "70 added or changed 2025.1 inventory entries" in packet
    assert "59 functions and 11 topics" in packet
    assert "7 added entries and 63 changed entries" in packet
    assert "33 deferred, 16 excluded, 14 candidate-sandbox-mutating, and 7 candidate-live-read-only" in packet
    assert "2024 comparison metadata" in packet
    assert "NotebookLM-only notes" in packet
    assert "URL candidates are not fetched proof" in packet
    assert "Windows validation is a caveat and follow-up" in packet
    assert "not Windows-host validation" in packet
    assert "Task 14 reran the final 2025.1 reconciliation commands" in packet
    assert "48 passed in 0.23s" in packet
    assert "12 passed in 170.38s" in packet
    assert "5 passed in 400.56s" in packet
    assert "26 passed in 0.11s" in packet
    assert WWISE_2025_CONSOLE in packet
    assert WWISE_2025_SAMPLE_PROJECT in packet
    assert _squash_command(LIVE_2025_READ_ONLY_COMMAND) in _squash_command(packet)
    assert _squash_command(DESTRUCTIVE_2025_COMMAND) in _squash_command(packet)

    for api in PROMOTED_2025_MUTATING_APIS:
        assert api in packet

    lowered = packet.lower()
    for claim in FORBIDDEN_2025_POSITIVE_CLAIMS:
        assert claim.lower() not in lowered


def _combined_docs_and_evals_text() -> str:
    parts = [path.read_text(encoding="utf-8") for path in DOC_PATHS if path.is_file()]
    parts.append(EVALS_JSON.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _claim_surfaces() -> list[tuple[Path, str]]:
    surfaces: list[tuple[Path, str]] = []
    for path in DOC_PATHS:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        is_2025_surface = SEMANTIC_2025_REFERENCES in path.parents or "2025" in path.name or path.name == "SKILL.md" or path == TASK12_REVIEW_PACKET
        if not is_2025_surface or "2025.1" not in text:
            continue
        if path.name == "SKILL.md":
            surfaces.extend((path, line) for line in text.splitlines() if "2025.1" in line)
        else:
            surfaces.append((path, text))

    payload: dict[str, Any] = json.loads(EVALS_JSON.read_text(encoding="utf-8"))
    for entry in payload["evals"]:
        serialized = json.dumps(entry, sort_keys=True)
        if "2025.1" in serialized or entry["id"].startswith("2025-"):
            surfaces.append((EVALS_JSON, serialized))
    return surfaces


def _resource_counts() -> dict[str, Any]:
    coverage = json.loads(COVERAGE_2025.read_text(encoding="utf-8"))["coverage"]
    live = json.loads(LIVE_MATRIX_2025.read_text(encoding="utf-8"))["matrix"]
    deferred = json.loads(DEFERRED_2025.read_text(encoding="utf-8"))["deferred"]
    classifications = json.loads(CLASSIFICATION_2025.read_text(encoding="utf-8"))["classifications"]
    return {
        "coverage_total": len(coverage),
        "live_total": len(live),
        "deferred_total": len(deferred),
        "coverage_status": dict(Counter(entry["coverage_status"] for entry in coverage)),
        "coverage_item_type": dict(Counter(entry["item_type"] for entry in coverage)),
        "classification_total": len(classifications),
        "classification_item_type": dict(Counter(entry["item_type"] for entry in classifications)),
        "classification_inventory_change": dict(Counter(entry["inventory_change"] for entry in classifications)),
        "classification_status": dict(Counter(entry["status"] for entry in classifications)),
    }


def _squash_command(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\\\n", " ")).strip()
