from __future__ import annotations

import os
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.headless import HeadlessLifecycle, LifecycleTimeouts, WwiseConsolePathResolver  # pyright: ignore[reportMissingImports]


@pytest.mark.live
def test_headless_wwise_launches_waapi_and_cleans_up() -> None:
    console_path = WwiseConsolePathResolver().resolve(os.getenv("WWISE_CONSOLE"))
    if not Path(console_path).exists():
        pytest.skip(f"WwiseConsole is unavailable at {console_path}")
    project_path = os.getenv("WWISE_FIXTURE_PROJECT")
    if not project_path or not Path(project_path).exists():
        pytest.skip("WWISE_FIXTURE_PROJECT is required for WwiseConsole waapi-server")
    assert project_path is not None

    lifecycle = HeadlessLifecycle(
        console_path=console_path,
        project_path=Path(project_path),
        timeouts=LifecycleTimeouts(
            startup=float(os.getenv("WWISE_STARTUP_TIMEOUT", "10")),
            readiness=float(os.getenv("WWISE_READINESS_TIMEOUT", "60")),
            probe=float(os.getenv("WWISE_PROBE_TIMEOUT", "5")),
            shutdown=float(os.getenv("WWISE_SHUTDOWN_TIMEOUT", "10")),
        ),
    )
    try:
        result = lifecycle.run_until_ready()
        assert lifecycle.port is not None and lifecycle.port > 0
        assert result is not None
    finally:
        lifecycle.shutdown(suppress_errors=True)
        assert lifecycle.process is None or lifecycle.process.poll() is not None
