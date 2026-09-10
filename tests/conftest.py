from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "waapi-skill"
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))


def pytest_configure(config):
    config.addinivalue_line("markers", "live: tests that require Wwise and WAAPI access")
    config.addinivalue_line("markers", "destructive: tests that may mutate a fixture Wwise project")
    config.addinivalue_line("markers", "active_gate_policy: fake tests for active gate skip/fail semantics")


def pytest_collection_modifyitems(items):
    live_enabled = os.getenv("WWISE_LIVE") == "1"
    destructive_enabled = os.getenv("WWISE_DESTRUCTIVE") == "1"

    for item in items:
        if "active_gate_policy" in item.keywords:
            continue
        if "live" in item.keywords and not live_enabled:
            item.add_marker(pytest.mark.skip(reason="WWISE_LIVE=1 is required for live tests"))
        if "destructive" in item.keywords and not (live_enabled and destructive_enabled):
            item.add_marker(
                pytest.mark.skip(
                    reason="WWISE_LIVE=1 and WWISE_DESTRUCTIVE=1 are required for destructive tests"
                )
            )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Retain exact phase outcomes for real-evidence fixture finalizers."""

    outcome = yield
    report = outcome.get_result()
    reports = getattr(item, "_waapi_phase_reports", None)
    if reports is None:
        reports = {}
        setattr(item, "_waapi_phase_reports", reports)
    reports[report.when] = report.outcome
