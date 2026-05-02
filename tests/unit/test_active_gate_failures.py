from __future__ import annotations

import pytest  # pyright: ignore[reportMissingImports]

from tests.support.active_gate_failures import (  # pyright: ignore[reportMissingImports]
    skip_or_fail_strict_real,
    skip_or_fail_unavailable,
    strict_real_mode_enabled,
)
from wwise_waapi.live_environment import LiveEnvironmentError  # pyright: ignore[reportMissingImports]


def test_strict_real_mode_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WWISE_STRICT_REAL", raising=False)

    assert strict_real_mode_enabled() is False
    with pytest.raises(pytest.skip.Exception):
        skip_or_fail_strict_real("missing WwiseConsole")


def test_strict_real_mode_turns_prerequisite_skip_into_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WWISE_STRICT_REAL", "1")

    assert strict_real_mode_enabled() is True
    with pytest.raises(pytest.fail.Exception) as failed:
        skip_or_fail_strict_real("missing WwiseConsole")

    assert "strict real Wwise prerequisite unavailable" in str(failed.value)
    assert "missing WwiseConsole" in str(failed.value)


def test_strict_real_mode_turns_unavailable_wrapper_into_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WWISE_STRICT_REAL", "1")
    exc = LiveEnvironmentError("WwiseConsole not found")

    with pytest.raises(pytest.fail.Exception) as failed:
        skip_or_fail_unavailable(exc, "destructive sandbox startup")

    assert "destructive sandbox startup" in str(failed.value)
    assert "WwiseConsole not found" in str(failed.value)
