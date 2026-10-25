from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "waapi-skill"
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))


def pytest_addoption(parser):
    parser.getgroup('owned Authoring').addoption('--owned-authoring-batch-root', default=None,
        help='Fresh absolute root for one explicitly selected owned Authoring batch')


def pytest_configure(config):
    config.addinivalue_line("markers", "live: tests that require Wwise and WAAPI access")
    config.addinivalue_line("markers", "destructive: tests that may mutate a fixture Wwise project")
    config.addinivalue_line("markers", "active_gate_policy: fake tests for active gate skip/fail semantics")
    result = os.getenv('WAAPI_TEST_BATCH_RESULT')
    if result:
        from tests.support.test_run_result import BatchResult
        config.pluginmanager.register(BatchResult(result), 'waapi-batch-result')


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_collection_finish(session):
    outcome = yield
    outcome.get_result()
    if session.config.getoption('owned_authoring_batch_root', default=None) is None:
        return
    if session.testsfailed or session.shouldstop or session.shouldfail:
        raise pytest.UsageError('Owned Authoring requires a complete successful collection before launch')
    from tests.destructive.support.authoring_batch import configure_authoring_batch_owner
    configure_authoring_batch_owner(session.config, session.items, repo_root=REPO_ROOT)


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


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    """Retain exact phase outcomes for real-evidence fixture finalizers."""

    outcome = yield
    report = outcome.get_result()
    reports = getattr(item, "_waapi_phase_reports", None)
    if reports is None:
        reports = {}
        setattr(item, "_waapi_phase_reports", reports)
    reports[report.when] = report.outcome
    from tests.support.exact_evidence_finalization import finalize_reported_node_evidence
    finalize_reported_node_evidence(item, report)
