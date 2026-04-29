from __future__ import annotations

from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi import NotebookLMGate, docs_generation_allowed, require_docs_generation  # pyright: ignore[reportMissingImports]


SUCCESS_EVIDENCE = """# NotebookLM gate evidence

- Gate status: open
- Notebook id: wwise-2022.1-docs
- Auth result: success
- List result: success
- Query result: success
"""


def write_evidence(tmp_path: Path, text: str) -> Path:
    evidence = tmp_path / "task-10-notebooklm-gate.md"
    evidence.write_text(text, encoding="utf-8")
    return evidence


def test_successful_evidence_opens_gate(tmp_path: Path) -> None:
    evidence = write_evidence(tmp_path, SUCCESS_EVIDENCE)

    status = NotebookLMGate(evidence).check()

    assert status.allowed is True
    assert status.status == "open"
    assert status.notebook_id == "wwise-2022.1-docs"
    assert docs_generation_allowed(evidence) is True
    require_docs_generation(evidence)


def test_missing_evidence_blocks_docs_generation(tmp_path: Path) -> None:
    evidence = tmp_path / "missing.md"

    status = NotebookLMGate(evidence).check()

    assert status.allowed is False
    assert status.status == "fail-closed"
    assert "missing" in status.reason
    with pytest.raises(RuntimeError, match="missing"):
        require_docs_generation(evidence)


def test_fail_closed_evidence_blocks_docs_generation(tmp_path: Path) -> None:
    evidence = write_evidence(
        tmp_path,
        """# NotebookLM gate evidence

- Gate status: fail-closed
- Notebook id: wwise-2022.1-docs
- Auth result: success
- List result: success
- Query result: failed
- Failure: Query timed out before NotebookLM returned an answer.
""",
    )

    status = NotebookLMGate(evidence).check()

    assert status.allowed is False
    assert status.status == "fail-closed"
    assert "timed out" in status.reason
    assert docs_generation_allowed(evidence) is False


def test_wrong_notebook_id_blocks_docs_generation(tmp_path: Path) -> None:
    evidence = write_evidence(
        tmp_path,
        SUCCESS_EVIDENCE.replace("wwise-2022.1-docs", "other-notebook"),
    )

    status = NotebookLMGate(evidence).check()

    assert status.allowed is False
    assert status.status == "fail-closed"
    assert "expected wwise-2022.1-docs" in status.reason


def test_incomplete_success_fields_block_docs_generation(tmp_path: Path) -> None:
    evidence = write_evidence(
        tmp_path,
        SUCCESS_EVIDENCE.replace("- Query result: success", "- Query result: failed"),
    )

    status = NotebookLMGate(evidence).check()

    assert status.allowed is False
    assert "auth, list, and query" in status.reason


def test_unreadable_evidence_blocks_docs_generation(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence-directory.md"
    evidence.mkdir()

    status = NotebookLMGate(evidence).check()

    assert status.allowed is False
    assert status.status == "fail-closed"
    assert "could not be read" in status.reason
    assert docs_generation_allowed(evidence) is False


def test_workflow_docs_contain_required_command_templates() -> None:
    workflow = Path(".agents/skills/wwise-waapi/references/notebooklm-workflow.md").read_text(encoding="utf-8")

    assert "python scripts/run.py auth_manager.py status" in workflow
    assert "python scripts/run.py notebook_manager.py list" in workflow
    assert "python scripts/run.py ask_question.py" in workflow
    assert "--notebook-id wwise-2022.1-docs" in workflow
    assert "fail-closed" in workflow
    assert "Follow up for Wwise 2022.1 WAAPI" in workflow
