from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from tests.support.active_gate_failures import skip_or_fail_strict_real  # pyright: ignore[reportMissingImports]
from tests.destructive.support.live_environment import (  # pyright: ignore[reportMissingImports]
    ENV_WWISE_CONSOLE,
    ENV_WWISE_LIVE,
    ENV_WWISE_SAMPLE_PROJECT_PATH,
    ENV_WWISE_VERSION,
    LiveEnvironmentContract,
    LiveEnvironmentError,
    WWISE_2024_1_CONSOLE_PATH,
    WWISE_2024_1_SAMPLE_PROJECT_PATH,
    require_live_environment,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_WWISE_VERSION = "2024.1"
EXPECTED_WWISE_CONSOLE = WWISE_2024_1_CONSOLE_PATH
EXPECTED_SAMPLE_PROJECT = WWISE_2024_1_SAMPLE_PROJECT_PATH
PREREQUISITE_EVIDENCE = (
    REPO_ROOT
    / ".sisyphus"
    / "evidence"
    / "wwise-2024-waapi-integration-coverage"
    / "live-read-only"
    / "prerequisites-unavailable.json"
)


@pytest.mark.live
def test_2024_live_environment_prerequisites_fail_fast() -> None:
    contract = require_2024_live_environment()

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


def require_2024_live_environment() -> LiveEnvironmentContract:
    if os.getenv(ENV_WWISE_LIVE) != "1":
        _skip_with_prerequisite_evidence(f"{ENV_WWISE_LIVE}=1 is required for 2024.1 live smoke gates")
    if os.getenv(ENV_WWISE_VERSION) != EXPECTED_WWISE_VERSION:
        _skip_with_prerequisite_evidence(f"{ENV_WWISE_VERSION}=2024.1 is required for 2024.1 live smoke gates")

    try:
        contract = require_live_environment()
    except LiveEnvironmentError as exc:
        _skip_with_prerequisite_evidence(str(exc))
        raise AssertionError("unreachable after prerequisite skip")

    if contract.console_path != EXPECTED_WWISE_CONSOLE:
        _skip_with_prerequisite_evidence(
            f"{ENV_WWISE_CONSOLE} must be the exact 2024.1 WwiseConsole path "
            f"{EXPECTED_WWISE_CONSOLE}; got {contract.console_path}"
        )
    if contract.sample_project_source != EXPECTED_SAMPLE_PROJECT:
        _skip_with_prerequisite_evidence(
            f"{ENV_WWISE_SAMPLE_PROJECT_PATH} must be the exact 2024.1 SampleProject path "
            f"{EXPECTED_SAMPLE_PROJECT}; got {contract.sample_project_source}"
        )
    return contract


def _skip_with_prerequisite_evidence(reason: str) -> None:
    PREREQUISITE_EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
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
    PREREQUISITE_EVIDENCE.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    skip_or_fail_strict_real(reason)
