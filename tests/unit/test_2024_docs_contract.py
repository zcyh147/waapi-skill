from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
EVALS_JSON = ROOT / "evals" / "evals.json"
REFERENCE_ROOT = ROOT / "references"
SEMANTIC_2024_REFERENCES = REFERENCE_ROOT / "semantic" / "2024.1"
TASK11_REVIEW_PACKET = ROOT / ".sisyphus" / "evidence" / "wwise-2024-waapi-integration-coverage" / "parity-review-packet.md"
DOC_PATHS = (
    ROOT / "SKILL.md",
    *sorted(REFERENCE_ROOT.glob("*.md")),
    *sorted(SEMANTIC_2024_REFERENCES.glob("*.md")),
)
DOC_CONTRACT_PATHS = (
    ROOT / "SKILL.md",
    ROOT / "references" / "long-run-runbook.md",
    ROOT / "references" / "eval-review-workflow.md",
    ROOT / "references" / "phase2-user-review-packet.md",
)
WWISE_2024_CONSOLE = "/Applications/Audiokinetic/Wwise2024.1.13.9056/Wwise.app/Contents/Tools/WwiseConsole.sh"
WWISE_2024_SAMPLE_PROJECT = "/Applications/Audiokinetic/SampleProject2024.1.13.9056/SampleProject/SampleProject.wproj"
LIVE_2024_READ_ONLY_COMMAND = (
    'WWISE_VERSION=2024.1 WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2024.1.13.9056/Wwise.app/Contents/Tools/WwiseConsole.sh" '
    'WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2024.1.13.9056/SampleProject/SampleProject.wproj" '
    "WWISE_LIVE=1 python -m pytest tests/live/test_2024_live_prerequisites.py "
    "tests/live/test_2024_reflection_inventory.py tests/live/test_2024_waql_live_matrix.py -q"
)
DESTRUCTIVE_2024_COMMAND = (
    'WWISE_VERSION=2024.1 WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2024.1.13.9056/Wwise.app/Contents/Tools/WwiseConsole.sh" '
    'WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2024.1.13.9056/SampleProject/SampleProject.wproj" '
    "WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes/2024.1 WWISE_LIVE=1 WWISE_DESTRUCTIVE=1 "
    "python -m pytest tests/destructive/test_2024_project_mutation_sandbox.py "
    "tests/destructive/test_2024_soundbank_audio_sandbox.py "
    "tests/destructive/test_2024_switchcontainer_assignment_sandbox.py -q"
)
PROMOTED_2024_MUTATING_APIS = {
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

FORBIDDEN_2024_POSITIVE_CLAIMS = (
    "all 2024.1 APIs are live-tested",
    "all 2024.1 APIs are behavior-tested",
    "all 2024.1 APIs are fully behavior-tested",
    "complete 2024.1 support",
    "full 2024.1 support",
    "full support for 2024.1",
    "full 2024.1 WAAPI behavioral coverage",
    "2024.1 full WAAPI coverage",
    "2024.1 full WAAPI behavioral coverage",
    "manifest reflection proves behavioral support",
    "manifest reflection is live evidence",
    "manifest-only live-tested",
)
FORBIDDEN_2024_STALE_PROOF_PATTERNS = (
    re.compile(
        r"(resources/(?:manifest|coverage|semantic)/(?:2022\.1|2023\.1)|"
        r"resources/deferred/(?:2022\.1|2023\.1)\.json|"
        r"references/semantic/(?:2022\.1|2023\.1)|"
        r"references/semantic-builder-|"
        r"wwise-202[23]\.1-docs)"
        r".{0,120}(?:proves?|proof|evidence|support|coverage).{0,120}2024\.1",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"2024\.1.{0,120}(?:proves?|proof|evidence|support|coverage).{0,120}"
        r"(resources/(?:manifest|coverage|semantic)/(?:2022\.1|2023\.1)|"
        r"resources/deferred/(?:2022\.1|2023\.1)\.json|"
        r"references/semantic/(?:2022\.1|2023\.1)|"
        r"references/semantic-builder-|"
        r"wwise-202[23]\.1-docs)",
        re.IGNORECASE | re.DOTALL,
    ),
)


def test_2024_docs_and_evals_reject_no_overclaim_phrases() -> None:
    combined = _combined_docs_and_evals_text().lower()

    for claim in FORBIDDEN_2024_POSITIVE_CLAIMS:
        assert claim.lower() not in combined

    for phrase in (
        "fully behavior-tested 2024.1",
        "2024.1 APIs are fully behavior-tested",
        "2024.1 support is complete",
        "2024.1 manifest reflection proves live behavior",
    ):
        assert phrase.lower() not in combined


def test_2024_claims_do_not_use_2022_2023_or_global_paths_as_proof() -> None:
    surfaces = _claim_surfaces()
    assert any(path.as_posix().endswith("references/semantic/2024.1/semantic-builder-protocol.md") for path, _ in surfaces)

    for path, text in surfaces:
        for pattern in FORBIDDEN_2024_STALE_PROOF_PATTERNS:
            assert pattern.search(text) is None, path


def test_2024_semantic_docs_are_version_scoped_and_not_behavioral_evidence() -> None:
    semantic_docs = sorted(SEMANTIC_2024_REFERENCES.glob("*.md"))
    assert semantic_docs

    for path in semantic_docs:
        text = path.read_text(encoding="utf-8")
        assert "2024.1" in text, path
        assert "wwise-2024.1-docs" in text, path
        assert "references/semantic/2024.1/" in text or path.name == "semantic-builder-protocol.md", path
        assert "references/semantic-builder-" not in text, path
        assert "wwise-2022.1-docs" not in text, path
        assert "wwise-2023.1-docs" not in text, path
        lowered = text.lower()
        for claim in FORBIDDEN_2024_POSITIVE_CLAIMS:
            assert claim.lower() not in lowered, path
        assert "source notes are live evidence" not in lowered, path
        assert "source notes prove behavioral support" not in lowered, path


def test_2024_eval_examples_are_version_scoped_when_added() -> None:
    payload = json.loads(EVALS_JSON.read_text(encoding="utf-8"))
    entries = [entry for entry in payload["evals"] if entry["id"].startswith("2024-")]

    assert {entry["id"] for entry in entries} == {
        "2024-parity-review-version-scoped-summary",
        "2024-live-and-destructive-command-review",
    }

    for entry in entries:
        serialized = json.dumps(entry, sort_keys=True)
        lowered = serialized.lower()
        assert "2024.1" in serialized, entry["id"]
        assert any("2024.1" in file_path for file_path in entry["files"]), entry["id"]
        assert "references/semantic-builder-" not in serialized, entry["id"]
        assert "resources/manifest/2022.1" not in serialized, entry["id"]
        assert "resources/manifest/2023.1" not in serialized, entry["id"]
        assert "resources/coverage/2022.1" not in serialized, entry["id"]
        assert "resources/coverage/2023.1" not in serialized, entry["id"]
        assert "wwise-2022.1-docs proves 2024.1" not in serialized, entry["id"]
        assert "wwise-2023.1-docs proves 2024.1" not in serialized, entry["id"]
        for claim in FORBIDDEN_2024_POSITIVE_CLAIMS:
            assert claim.lower() not in lowered, entry["id"]


def test_2024_docs_include_exact_paths_commands_and_limited_claims() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in DOC_CONTRACT_PATHS)

    assert WWISE_2024_CONSOLE in combined
    assert WWISE_2024_SAMPLE_PROJECT in combined
    assert "python -m pytest -q" in combined
    assert _squash_command(LIVE_2024_READ_ONLY_COMMAND) in _squash_command(combined)
    assert _squash_command(DESTRUCTIVE_2024_COMMAND) in _squash_command(combined)

    assert "complete reflected inventory and parity classification" in combined
    assert "148 functions" in combined
    assert "topic inventory is now present" in combined
    assert "topic inventory rows are inventory/substitute accounting only until fresh active live topic evidence exists" in combined
    assert "one live read-only URI" in combined
    assert "ten copied-sandbox mutating URIs" in combined
    assert "remaining 137 entries" in combined
    assert "ak.wwise.core.object.get" in combined
    assert "ak.wwise.core.soundbank.getInclusions" in combined
    assert "ak.wwise.core.switchContainer.getAssignments" in combined
    assert "remain unpromoted" in combined
    assert "Windows validation is recorded as a non-blocking evidence caveat, not a hard gate" in combined

    for api in PROMOTED_2024_MUTATING_APIS:
        assert api in combined


def test_task11_review_packet_has_required_sections_and_limited_claims() -> None:
    packet = TASK11_REVIEW_PACKET.read_text(encoding="utf-8")

    assert [
        line.removeprefix("## ")
        for line in packet.splitlines()
        if line.startswith("## ")
    ] == [
        "Promoted Evidence",
        "Deferred/Excluded",
        "Commands Run",
        "Source Immutability",
        "Windows Caveat",
        "Known Non-Goals",
    ]

    assert "reconcile to 148 functions" in packet
    assert "one live read-only URI and ten copied-sandbox mutating URIs" in packet
    assert "ak.wwise.core.object.get" in packet
    assert packet.count("promoted to `live-tested`") == 1
    assert "137 entries deferred or excluded" in packet
    assert "remain unpromoted" in packet
    assert "fail closed" in packet
    assert "Windows validation is non-blocking evidence and caveat" in packet
    assert "not a hard gate" in packet
    assert WWISE_2024_CONSOLE in packet
    assert WWISE_2024_SAMPLE_PROJECT in packet
    assert _squash_command(LIVE_2024_READ_ONLY_COMMAND) in _squash_command(packet)
    assert _squash_command(DESTRUCTIVE_2024_COMMAND) in _squash_command(packet)

    for api in PROMOTED_2024_MUTATING_APIS:
        assert api in packet

    lowered = packet.lower()
    for claim in FORBIDDEN_2024_POSITIVE_CLAIMS:
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
        is_2024_surface = SEMANTIC_2024_REFERENCES in path.parents or "2024" in path.name or path.name == "SKILL.md"
        if is_2024_surface and "2024.1" in text:
            surfaces.append((path, text))

    payload: dict[str, Any] = json.loads(EVALS_JSON.read_text(encoding="utf-8"))
    for entry in payload["evals"]:
        serialized = json.dumps(entry, sort_keys=True)
        if "2024.1" in serialized or entry["id"].startswith("2024-"):
            surfaces.append((EVALS_JSON, serialized))
    return surfaces


def _squash_command(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\\\n", " ")).strip()
