from __future__ import annotations

from pathlib import Path

from tests.destructive.support.windows_gate import (  # pyright: ignore[reportMissingImports]
    FAILED_STATUS,
    PASSED_STATUS,
    PENDING_STATUS,
    WindowsValidationGate,
    windows_validation_status,
)


def test_missing_windows_evidence_defaults_to_pending(tmp_path: Path) -> None:
    evidence_path = tmp_path / "missing.md"

    status = WindowsValidationGate(evidence_path, system_name="Darwin").check()

    assert status.status == PENDING_STATUS
    assert status.evidence_path == evidence_path
    assert status.can_claim_cross_platform is False


def test_pending_windows_evidence_keeps_cross_platform_claim_closed(tmp_path: Path) -> None:
    evidence_path = tmp_path / "windows-gate.md"
    evidence_path.write_text(
        "- Windows validation status: pending\n"
        "- Host platform: macOS\n"
        "- Blocking condition: Waiting for live Windows WwiseConsole validation.\n",
        encoding="utf-8",
    )

    status = windows_validation_status(evidence_path, system_name="Darwin")

    assert status.status == PENDING_STATUS
    assert "Waiting for live Windows" in status.reason
    assert status.can_claim_cross_platform is False


def test_failed_windows_evidence_reports_failed_status(tmp_path: Path) -> None:
    evidence_path = tmp_path / "windows-gate.md"
    evidence_path.write_text(
        "- Windows validation status: failed\n"
        "- Failure: taskkill cleanup did not terminate child process tree.\n",
        encoding="utf-8",
    )

    status = windows_validation_status(evidence_path, system_name="Windows")

    assert status.status == FAILED_STATUS
    assert "taskkill cleanup" in status.reason
    assert status.can_claim_cross_platform is False


def test_passed_status_requires_windows_live_evidence(tmp_path: Path) -> None:
    evidence_path = tmp_path / "windows-gate.md"
    evidence_path.write_text(
        "- Windows validation status: passed\n"
        "- Host platform: macOS\n"
        "- Windows live validation: not-run\n",
        encoding="utf-8",
    )

    status = windows_validation_status(evidence_path, system_name="Darwin")

    assert status.status == FAILED_STATUS
    assert "requires evidence captured on Windows" in status.reason
    assert status.can_claim_cross_platform is False


def test_passed_windows_live_evidence_opens_cross_platform_claim(tmp_path: Path) -> None:
    evidence_path = tmp_path / "windows-gate.md"
    evidence_path.write_text(
        "- Windows validation status: passed\n"
        "- Host platform: Windows\n"
        "- Windows live validation: passed\n",
        encoding="utf-8",
    )

    status = windows_validation_status(evidence_path, system_name="Darwin")

    assert status.status == PASSED_STATUS
    assert status.can_claim_cross_platform is True
