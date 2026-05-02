from __future__ import annotations

from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from tests.support.active_gate_failures import skip_or_fail_unavailable  # pyright: ignore[reportMissingImports]
from wwise_waapi.headless import EarlyProcessExit, ReadinessTimeout  # pyright: ignore[reportMissingImports]
from wwise_waapi.live_environment import LiveEnvironmentError, require_destructive_environment  # pyright: ignore[reportMissingImports]


@pytest.mark.destructive
def test_destructive_fixture_project_must_be_under_sandbox_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    console = tmp_path / "WwiseConsole.sh"
    console.write_text("#!/bin/sh\n", encoding="utf-8")
    console.chmod(0o755)
    sample_source = tmp_path / "sample" / "SampleProject.wproj"
    sample_source.parent.mkdir(parents=True)
    sample_source.write_text("<WwiseDocument />", encoding="utf-8")
    outside_project = tmp_path / "not-under-sandbox" / "project.wproj"
    outside_project.parent.mkdir(parents=True)
    outside_project.write_text("<WwiseDocument />", encoding="utf-8")
    sandbox_root = tmp_path / "sandbox"
    sandbox_root.mkdir()
    monkeypatch.setenv("WWISE_CONSOLE", str(console))
    monkeypatch.setenv("WWISE_SAMPLE_PROJECT_PATH", str(sample_source))
    monkeypatch.setenv("WWISE_FIXTURE_PROJECT", str(outside_project))
    monkeypatch.setenv("WWISE_SANDBOX_ROOT", str(sandbox_root))

    with pytest.raises(LiveEnvironmentError, match="must be under active WWISE_SANDBOX_ROOT"):
        require_destructive_environment()


@pytest.mark.active_gate_policy
def test_wrapped_destructive_readiness_timeout_fails_not_skips() -> None:
    timeout = ReadinessTimeout("fake destructive readiness timeout", {"port": 31338, "timeout": 0.01})

    try:
        raise RuntimeError("sandbox unavailable after launch") from timeout
    except RuntimeError as exc:
        wrapped = exc

    with pytest.raises(pytest.fail.Exception) as failed:
        skip_or_fail_unavailable(wrapped, "destructive sandbox startup")

    assert "ReadinessTimeout" in str(failed.value)
    assert "active Wwise runtime failure" in str(failed.value)


@pytest.mark.active_gate_policy
def test_wrapped_destructive_early_process_exit_fails_not_skips() -> None:
    early_exit = EarlyProcessExit("fake destructive early process exit", {"returncode": 1, "stderr_tail": "boom"})

    try:
        raise RuntimeError("sandbox unavailable after launch") from early_exit
    except RuntimeError as exc:
        wrapped = exc

    with pytest.raises(pytest.fail.Exception) as failed:
        skip_or_fail_unavailable(wrapped, "destructive sandbox startup")

    assert "EarlyProcessExit" in str(failed.value)
    assert "active Wwise runtime failure" in str(failed.value)
