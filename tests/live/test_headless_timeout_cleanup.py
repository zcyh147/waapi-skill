from __future__ import annotations

import os
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.headless import HeadlessLifecycle, LifecycleTimeouts, ReadinessTimeout, StartupTimeout, WwiseConsolePathResolver  # pyright: ignore[reportMissingImports]


@pytest.mark.live
def test_headless_startup_timeout_is_controlled_and_cleans_up(tmp_path: Path) -> None:
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
            startup=float(os.getenv("WWISE_STARTUP_TIMEOUT", "0.01")),
            readiness=float(os.getenv("WWISE_READINESS_TIMEOUT", "0.01")),
            probe=float(os.getenv("WWISE_PROBE_TIMEOUT", "0.01")),
            shutdown=float(os.getenv("WWISE_SHUTDOWN_TIMEOUT", "5")),
        ),
        launch_env={**os.environ, "WINEPREFIX": str(tmp_path / ".wine-prefix")},
    )
    try:
        with pytest.raises((StartupTimeout, ReadinessTimeout)) as exc_info:
            lifecycle.run_until_ready()
        diagnostics = exc_info.value.diagnostics
        assert diagnostics["port"] == lifecycle.port
        assert diagnostics["argv"] == lifecycle.command
        assert diagnostics["cwd"]
        assert diagnostics["timeout"] in {lifecycle.timeouts.startup, lifecycle.timeouts.readiness}
        assert diagnostics["duration"] >= 0.0
        assert "process_state" in diagnostics
        assert "exit_code" in diagnostics
        assert "stdout_tail" in diagnostics
        assert "stderr_tail" in diagnostics
        assert "last_exception" in diagnostics
    finally:
        lifecycle.shutdown(suppress_errors=True)
        assert lifecycle.process is None or lifecycle.process.poll() is not None
        assert lifecycle.cleanup_report is None or lifecycle.cleanup_report.is_clean is True
