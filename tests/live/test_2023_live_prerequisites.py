from __future__ import annotations

import os
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from tests.support.active_gate_failures import skip_or_fail_strict_real  # pyright: ignore[reportMissingImports]
from wwise_waapi.live_environment import (  # pyright: ignore[reportMissingImports]
    ENV_WWISE_CONSOLE,
    ENV_WWISE_LIVE,
    ENV_WWISE_SAMPLE_PROJECT_PATH,
    ENV_WWISE_VERSION,
    LiveEnvironmentContract,
    LiveEnvironmentError,
    require_live_environment,
)


EXPECTED_WWISE_VERSION = "2023.1"
EXPECTED_WWISE_CONSOLE = Path(
    "/Applications/Audiokinetic/Wwise2023.1.19.8928/Wwise.app/Contents/Tools/WwiseConsole.sh"
)
EXPECTED_SAMPLE_PROJECT = Path(
    "/Applications/Audiokinetic/SampleProject2023.1.19.8928/SampleProject/SampleProject.wproj"
)


@pytest.mark.live
def test_2023_live_environment_prerequisites_fail_fast() -> None:
    contract = require_2023_live_environment()

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


def require_2023_live_environment() -> LiveEnvironmentContract:
    if os.getenv(ENV_WWISE_LIVE) != "1":
        skip_or_fail_strict_real(f"{ENV_WWISE_LIVE}=1 is required for 2023.1 live smoke gates")
    if os.getenv(ENV_WWISE_VERSION) != EXPECTED_WWISE_VERSION:
        skip_or_fail_strict_real(f"{ENV_WWISE_VERSION}=2023.1 is required for 2023.1 live smoke gates")

    try:
        contract = require_live_environment()
    except LiveEnvironmentError as exc:
        skip_or_fail_strict_real(str(exc))
        raise AssertionError("unreachable after prerequisite skip")
    if contract.console_path != EXPECTED_WWISE_CONSOLE:
        skip_or_fail_strict_real(
            f"{ENV_WWISE_CONSOLE} must be the exact 2023.1 WwiseConsole path "
            f"{EXPECTED_WWISE_CONSOLE}; got {contract.console_path}"
        )
    if contract.sample_project_source != EXPECTED_SAMPLE_PROJECT:
        skip_or_fail_strict_real(
            f"{ENV_WWISE_SAMPLE_PROJECT_PATH} must be the exact 2023.1 SampleProject path "
            f"{EXPECTED_SAMPLE_PROJECT}; got {contract.sample_project_source}"
        )
    return contract
