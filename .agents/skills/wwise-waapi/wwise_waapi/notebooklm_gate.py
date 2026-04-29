"""Fail-closed gate for NotebookLM-backed Wwise documentation evidence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


EXPECTED_NOTEBOOK_ID = "wwise-2022.1-docs"
OPEN_STATUS = "open"
FAIL_CLOSED_STATUS = "fail-closed"


@dataclass(slots=True, frozen=True)
class NotebookLMGateStatus:
    """Result of checking whether docs-dependent work may proceed."""

    allowed: bool
    status: str
    reason: str
    notebook_id: str | None = None
    evidence_path: Path | None = None


class NotebookLMGate:
    """Validate persisted NotebookLM evidence before docs-dependent generation."""

    def __init__(self, evidence_path: Path, notebook_id: str = EXPECTED_NOTEBOOK_ID) -> None:
        self.evidence_path = evidence_path
        self.notebook_id = notebook_id

    def check(self) -> NotebookLMGateStatus:
        if not self.evidence_path.exists():
            return NotebookLMGateStatus(
                allowed=False,
                status=FAIL_CLOSED_STATUS,
                reason="NotebookLM gate evidence is missing.",
                evidence_path=self.evidence_path,
            )

        try:
            evidence_text = self.evidence_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return NotebookLMGateStatus(
                allowed=False,
                status=FAIL_CLOSED_STATUS,
                reason=f"NotebookLM gate evidence could not be read: {exc}",
                evidence_path=self.evidence_path,
            )

        fields = _parse_evidence_fields(evidence_text)
        status = fields.get("gate status", "").strip().lower()
        evidence_notebook_id = fields.get("notebook id", "").strip()
        auth_result = fields.get("auth result", "").strip().lower()
        list_result = fields.get("list result", "").strip().lower()
        query_result = fields.get("query result", "").strip().lower()

        if status != OPEN_STATUS:
            return NotebookLMGateStatus(
                allowed=False,
                status=status or FAIL_CLOSED_STATUS,
                reason=fields.get("failure", "NotebookLM evidence is not open."),
                notebook_id=evidence_notebook_id or None,
                evidence_path=self.evidence_path,
            )

        if evidence_notebook_id != self.notebook_id:
            return NotebookLMGateStatus(
                allowed=False,
                status=FAIL_CLOSED_STATUS,
                reason=f"NotebookLM evidence is for {evidence_notebook_id or 'no notebook'}, expected {self.notebook_id}.",
                notebook_id=evidence_notebook_id or None,
                evidence_path=self.evidence_path,
            )

        if (auth_result, list_result, query_result) != ("success", "success", "success"):
            return NotebookLMGateStatus(
                allowed=False,
                status=FAIL_CLOSED_STATUS,
                reason="NotebookLM auth, list, and query evidence must all be success.",
                notebook_id=evidence_notebook_id,
                evidence_path=self.evidence_path,
            )

        return NotebookLMGateStatus(
            allowed=True,
            status=OPEN_STATUS,
            reason=f"NotebookLM evidence is present for {self.notebook_id}.",
            notebook_id=evidence_notebook_id,
            evidence_path=self.evidence_path,
        )


def docs_generation_allowed(evidence_path: Path, notebook_id: str = EXPECTED_NOTEBOOK_ID) -> bool:
    """Return True only when NotebookLM evidence opens the docs gate."""

    return NotebookLMGate(evidence_path, notebook_id).check().allowed


def require_docs_generation(evidence_path: Path, notebook_id: str = EXPECTED_NOTEBOOK_ID) -> None:
    """Raise RuntimeError when docs-dependent generation must be blocked."""

    status = NotebookLMGate(evidence_path, notebook_id).check()
    if not status.allowed:
        raise RuntimeError(status.reason)


def _parse_evidence_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        cleaned = line.strip()
        if cleaned.startswith("-"):
            cleaned = cleaned[1:].strip()
        if ":" not in cleaned:
            continue
        key, value = cleaned.split(":", 1)
        normalized_key = key.strip().lower().strip("*`")
        if normalized_key:
            fields[normalized_key] = value.strip().strip("*`")
    return fields
