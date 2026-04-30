from __future__ import annotations

from pathlib import Path


RUNBOOK = Path(__file__).resolve().parents[2] / "references" / "long-run-runbook.md"


def runbook_text() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


def ralph_prompt_text() -> str:
    text = runbook_text()
    start = text.index("```text") + len("```text")
    end = text.index("```", start)
    return text[start:end]


def test_runbook_documents_primary_start_work_and_optional_ralph_loop() -> None:
    text = runbook_text()

    assert "primary execution path is `/start-work`" in text
    assert "Primary path: `/start-work`" in text
    assert "Optional path: guarded Ralph-loop" in text
    assert "Do not start a Ralph loop from this runbook automatically" in text


def test_ralph_prompt_restates_non_negotiable_constraints() -> None:
    prompt = ralph_prompt_text()

    required_constraints = (
        "No silent skips",
        "Headless first",
        "NotebookLM gate",
        "wwise-2022.1-docs",
        "TDD",
        "overall line and branch coverage >=85%",
        ">=95% coverage for core headless, manifest, generator, and timeout modules",
        "No unbounded waits",
        "No user-project mutation",
        "Deferred registry enforcement",
        "Windows gate truthfulness",
        "Final verification with user approval",
    )
    for required in required_constraints:
        assert required in prompt


def test_ralph_prompt_includes_stop_conditions_and_evidence_paths() -> None:
    prompt = ralph_prompt_text()

    required_stops = (
        "Stop immediately on any safety risk",
        "Stop docs-dependent generation if the NotebookLM gate",
        "Stop live or destructive validation if no isolated fixture project",
        "Stop cross-platform claims when Windows evidence is absent",
        "Stop final completion after presenting verification results",
    )
    for required in required_stops:
        assert required in prompt

    for evidence_path in (
        ".sisyphus/evidence/task-10-notebooklm-gate.md",
        ".sisyphus/evidence/task-11-windows-gate.md",
        ".sisyphus/evidence/task-12-runbook.md",
        ".sisyphus/evidence/task-12-approval-stop.md",
    ):
        assert evidence_path in prompt


def test_final_approval_required() -> None:
    text = runbook_text()
    prompt = ralph_prompt_text()

    approval_phrases = (
        "present consolidated verification results",
        "wait for explicit user okay before marking completion",
        "Final verification is not self-completing",
        "wait for explicit user okay before marking the final verification wave complete",
    )
    for required in approval_phrases:
        assert required in text or required in prompt

    assert "Do not make Ralph loop auto-complete" not in text
    assert ".sisyphus/evidence/task-12-approval-stop.md" in text
