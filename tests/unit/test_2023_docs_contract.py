from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOC_PATHS = (
    ROOT / "SKILL.md",
    ROOT / "references" / "long-run-runbook.md",
    ROOT / "references" / "eval-review-workflow.md",
    ROOT / "references" / "phase2-user-review-packet.md",
)
EVALS_JSON = ROOT / "evals" / "evals.json"

WWISE_2023_CONSOLE = "/Applications/Audiokinetic/Wwise2023.1.19.8928/Wwise.app/Contents/Tools/WwiseConsole.sh"
WWISE_2023_SAMPLE_PROJECT = "/Applications/Audiokinetic/SampleProject2023.1.19.8928/SampleProject/SampleProject.wproj"


def test_2023_docs_include_exact_paths_and_no_full_coverage_claims() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in DOC_PATHS)

    assert WWISE_2023_CONSOLE in combined
    assert WWISE_2023_SAMPLE_PROJECT in combined
    assert "references/semantic/2023.1/" in combined
    assert "resources/semantic/2023.1/source_notes.json" in combined
    assert "Runtime builders and dispatcher flows do not query NotebookLM" in combined
    assert "Runtime reads local persisted evidence" in combined
    assert "2024 and 2025 are future sequential follow-ups" in combined
    assert "not implemented here" in combined

    forbidden_positive_claims = (
        "complete 2023.1 support",
        "full support for 2023.1",
        "all 2023.1 APIs are behavior-tested",
        "all 2023.1 APIs are live-tested",
        "2023.1 full WAAPI coverage",
    )
    lowered = combined.lower()
    for claim in forbidden_positive_claims:
        assert claim.lower() not in lowered

    assert "skipped live or destructive tests are not live evidence" in combined or "skipped live/destructive suite as proof" in combined


def test_2023_eval_examples_are_version_scoped() -> None:
    payload = json.loads(EVALS_JSON.read_text(encoding="utf-8"))
    entries = [entry for entry in payload["evals"] if entry["id"].startswith("2023-")]

    assert {entry["id"] for entry in entries} == {
        "2023-semantic-builder-version-scoped-preview",
        "2023-deferred-coverage-version-scoped-review",
    }

    serialized_entries = json.dumps(entries, sort_keys=True)
    assert "2023.1" in serialized_entries
    assert "resources/semantic/2023.1/source_notes.json" in serialized_entries
    assert "references/semantic/2023.1/" in serialized_entries
    assert "resources/coverage/2023.1/" in serialized_entries
    assert "resources/deferred/2023.1.json" in serialized_entries
    assert "full 2023.1 WAAPI behavioral coverage" in serialized_entries

    for entry in entries:
        assert any("2023.1" in file_path for file_path in entry["files"]), entry["id"]
        assert "references/semantic-builder-query.md" not in entry["files"]
        assert "references/semantic-builder-notebooklm-gate.md" not in entry["files"]
        assert "/Applications/" not in json.dumps(entry, sort_keys=True)

    assert "wwise-2022.1-docs proves 2023.1" in serialized_entries
    assert "not live-tested" in serialized_entries
