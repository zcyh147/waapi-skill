"""Windows live-validation gate for Wwise WAAPI cross-platform claims."""

from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path


PENDING_STATUS = "pending"
PASSED_STATUS = "passed"
FAILED_STATUS = "failed"
WINDOWS_VALIDATION_STATUSES = frozenset({PENDING_STATUS, PASSED_STATUS, FAILED_STATUS})


@dataclass(slots=True, frozen=True)
class WindowsValidationStatus:
    """Result of checking whether Windows validation evidence is sufficient."""

    status: str
    reason: str
    evidence_path: Path
    can_claim_cross_platform: bool = False


class WindowsValidationGate:
    """Validate Windows evidence before cross-platform completion is claimed."""

    def __init__(self, evidence_path: Path, system_name: str | None = None) -> None:
        self.evidence_path = evidence_path
        self.system_name = system_name or platform.system()

    def check(self) -> WindowsValidationStatus:
        if not self.evidence_path.exists():
            return WindowsValidationStatus(
                status=PENDING_STATUS,
                reason="Windows validation evidence is missing; live validation remains pending.",
                evidence_path=self.evidence_path,
            )

        try:
            evidence_text = self.evidence_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return WindowsValidationStatus(
                status=FAILED_STATUS,
                reason=f"Windows validation evidence could not be read: {exc}",
                evidence_path=self.evidence_path,
            )

        fields = _parse_evidence_fields(evidence_text)
        status = _evidence_status(fields)
        if status not in WINDOWS_VALIDATION_STATUSES:
            return WindowsValidationStatus(
                status=FAILED_STATUS,
                reason="Windows validation evidence must declare status pending, passed, or failed.",
                evidence_path=self.evidence_path,
            )

        if status == PENDING_STATUS:
            return WindowsValidationStatus(
                status=PENDING_STATUS,
                reason=fields.get(
                    "blocking condition",
                    "Windows live validation remains pending until evidence from a Windows host exists.",
                ),
                evidence_path=self.evidence_path,
            )

        if status == FAILED_STATUS:
            return WindowsValidationStatus(
                status=FAILED_STATUS,
                reason=fields.get("failure", "Windows live validation failed."),
                evidence_path=self.evidence_path,
            )

        host_platform = fields.get("host platform", "").strip().lower()
        live_result = fields.get("windows live validation", "").strip().lower()
        if host_platform != "windows" or live_result != PASSED_STATUS:
            return WindowsValidationStatus(
                status=FAILED_STATUS,
                reason="Passed status requires evidence captured on Windows with Windows live validation: passed.",
                evidence_path=self.evidence_path,
            )

        return WindowsValidationStatus(
            status=PASSED_STATUS,
            reason="Windows live validation evidence is present.",
            evidence_path=self.evidence_path,
            can_claim_cross_platform=True,
        )


def windows_validation_status(evidence_path: Path, system_name: str | None = None) -> WindowsValidationStatus:
    """Check Windows validation evidence and return pending, passed, or failed."""

    return WindowsValidationGate(evidence_path, system_name=system_name).check()


def _evidence_status(fields: dict[str, str]) -> str:
    return (
        fields.get("windows validation status")
        or fields.get("validation status")
        or fields.get("status")
        or PENDING_STATUS
    ).strip().lower()


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
