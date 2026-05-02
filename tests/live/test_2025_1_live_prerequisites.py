from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from tests.support.active_gate_failures import fail_if_active_runtime_failure  # pyright: ignore[reportMissingImports]
from wwise_waapi.headless import ReadinessTimeout  # pyright: ignore[reportMissingImports]
from wwise_waapi.live_environment import (  # pyright: ignore[reportMissingImports]
    ENV_WWISE_CONSOLE,
    ENV_WWISE_LIVE,
    ENV_WWISE_SAMPLE_PROJECT_PATH,
    ENV_WWISE_VERSION,
    LiveEnvironmentContract,
    LiveEnvironmentError,
    require_live_environment,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_WWISE_VERSION = "2025.1"
EXPECTED_WWISE_CONSOLE = Path(
    "/Applications/Audiokinetic/Wwise2025.1.7.9143/Wwise.app/Contents/Tools/WwiseConsole.sh"
)
EXPECTED_SAMPLE_PROJECT = Path(
    "/Applications/Audiokinetic/SampleProject2025.1.7.9143/SampleProject/SampleProject.wproj"
)
PREREQUISITE_EVIDENCE = (
    REPO_ROOT
    / ".sisyphus"
    / "evidence"
    / "wwise-2025-waapi-integration-coverage"
    / "live-read-only"
    / "prerequisites-unavailable.json"
)
TASK_PREREQUISITE_BLOCKER = REPO_ROOT / ".sisyphus" / "evidence" / "task-2025-9-live-prereq-blocker.txt"


@pytest.mark.live
def test_2025_live_environment_prerequisites_fail_fast() -> None:
    contract = require_2025_live_environment()

    assert contract.version == EXPECTED_WWISE_VERSION
    console_path = contract.console_path
    sample_project = contract.sample_project_source
    assert console_path is not None
    assert sample_project is not None
    assert console_path == EXPECTED_WWISE_CONSOLE
    assert sample_project == EXPECTED_SAMPLE_PROJECT
    assert console_path.exists()
    assert sample_project.exists()
    assert sample_project.suffix == ".wproj"


def test_2025_wrong_path_prerequisites_skip_before_sandbox_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    wrong_console = REPO_ROOT / ".sisyphus" / "runtime" / "wrong-2025" / "WwiseConsole.sh"
    wrong_project = REPO_ROOT / ".sisyphus" / "runtime" / "wrong-2025" / "SampleProject.wproj"
    monkeypatch.setenv(ENV_WWISE_LIVE, "1")
    monkeypatch.setenv(ENV_WWISE_VERSION, EXPECTED_WWISE_VERSION)
    monkeypatch.setenv(ENV_WWISE_CONSOLE, str(wrong_console))
    monkeypatch.setenv(ENV_WWISE_SAMPLE_PROJECT_PATH, str(wrong_project))

    with pytest.raises(pytest.skip.Exception) as skipped:
        require_2025_live_environment()

    assert str(wrong_console) in str(skipped.value)
    assert TASK_PREREQUISITE_BLOCKER.exists()
    blocker = TASK_PREREQUISITE_BLOCKER.read_text(encoding="utf-8")
    assert "controlled wrong-path prerequisite coverage" in blocker
    assert "sandbox_copy_attempted: false" in blocker
    assert "mutation_attempted: false" in blocker


@pytest.mark.active_gate_policy
def test_2025_active_gated_readiness_timeout_fails_not_skips() -> None:
    timeout = ReadinessTimeout("fake readiness timeout", {"port": 31337, "timeout": 0.01})

    with pytest.raises(pytest.fail.Exception) as failed:
        fail_if_active_runtime_failure(timeout, "2025.1 live prerequisite launch")

    assert "ReadinessTimeout" in str(failed.value)
    assert "active Wwise runtime failure" in str(failed.value)


def require_2025_live_environment() -> LiveEnvironmentContract:
    if os.getenv(ENV_WWISE_LIVE) != "1":
        _skip_with_prerequisite_evidence(f"{ENV_WWISE_LIVE}=1 is required for 2025.1 live read-only gates")
    if os.getenv(ENV_WWISE_VERSION) != EXPECTED_WWISE_VERSION:
        _skip_with_prerequisite_evidence(f"{ENV_WWISE_VERSION}=2025.1 is required for 2025.1 live read-only gates")

    try:
        contract = require_live_environment()
    except LiveEnvironmentError as exc:
        _skip_with_prerequisite_evidence(str(exc))
        raise AssertionError("unreachable after prerequisite skip")

    if contract.console_path != EXPECTED_WWISE_CONSOLE:
        _skip_with_prerequisite_evidence(
            f"{ENV_WWISE_CONSOLE} must be the exact 2025.1 WwiseConsole path "
            f"{EXPECTED_WWISE_CONSOLE}; got {contract.console_path}"
        )
    if contract.sample_project_source != EXPECTED_SAMPLE_PROJECT:
        _skip_with_prerequisite_evidence(
            f"{ENV_WWISE_SAMPLE_PROJECT_PATH} must be the exact 2025.1 SampleProject path "
            f"{EXPECTED_SAMPLE_PROJECT}; got {contract.sample_project_source}"
        )
    return contract


def _skip_with_prerequisite_evidence(reason: str) -> None:
    payload = {
        "status": "skipped-before-sandbox-copy",
        "reason": reason,
        "expected": {
            ENV_WWISE_VERSION: EXPECTED_WWISE_VERSION,
            ENV_WWISE_CONSOLE: str(EXPECTED_WWISE_CONSOLE),
            ENV_WWISE_SAMPLE_PROJECT_PATH: str(EXPECTED_SAMPLE_PROJECT),
            ENV_WWISE_LIVE: "1",
        },
        "actual": {
            ENV_WWISE_VERSION: os.getenv(ENV_WWISE_VERSION),
            ENV_WWISE_CONSOLE: os.getenv(ENV_WWISE_CONSOLE),
            ENV_WWISE_SAMPLE_PROJECT_PATH: os.getenv(ENV_WWISE_SAMPLE_PROJECT_PATH),
            ENV_WWISE_LIVE: os.getenv(ENV_WWISE_LIVE),
        },
        "mutation_attempted": False,
        "sandbox_copy_attempted": False,
        "recorded_at_unix": int(time.time()),
    }
    PREREQUISITE_EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    PREREQUISITE_EVIDENCE.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_task_prerequisite_blocker(reason, payload)
    pytest.skip(reason)


def _write_task_prerequisite_blocker(reason: str, payload: dict[str, object]) -> None:
    TASK_PREREQUISITE_BLOCKER.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "Task 2025-9 live prerequisite blocker",
        "status: controlled wrong-path prerequisite coverage" if "wrong-2025" in reason else "status: prerequisite blocked",
        f"reason: {reason}",
        f"expected_version: {EXPECTED_WWISE_VERSION}",
        f"expected_console: {EXPECTED_WWISE_CONSOLE}",
        f"expected_sample_project: {EXPECTED_SAMPLE_PROJECT}",
        f"actual: {json.dumps(payload['actual'], sort_keys=True)}",
        "sandbox_copy_attempted: false",
        "mutation_attempted: false",
        "destructive_enabled: false",
        "evidence: prerequisite gate returned before sandbox copy, Wwise launch, or project mutation",
    ]
    TASK_PREREQUISITE_BLOCKER.write_text("\n".join(lines) + "\n", encoding="utf-8")
