"""Persist pytest's final phase reports for an explicitly owned batch root."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


class BatchResult:
    def __init__(self, path):
        self.path = Path(path)
        self.nodes = []
        self.phases = {}
        self.failures = []
        self.duplicates_removed = int(os.getenv('WAAPI_TEST_BATCH_DUPLICATES', '0'))

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, items):
        unique = {}
        for item in items:
            unique.setdefault(item.nodeid, item)
        self.duplicates_removed += len(items) - len(unique)
        items[:] = unique.values()
        self.nodes = list(unique)
        self.persist(terminal=False)

    def pytest_runtest_logreport(self, report):
        self.phases.setdefault(report.nodeid, {})[report.when] = report.outcome
        if report.failed:
            self.failures.append({'nodeid': report.nodeid, 'phase': report.when,
                                  'detail': str(report.longrepr)[-2000:]})
        self.persist(terminal=False)

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_sessionfinish(self, session, exitstatus):
        yield
        self.persist(terminal=True, exit_code=int(session.exitstatus))

    def persist(self, *, terminal, exit_code=None):
        outcomes = []
        for node in self.nodes:
            phases = self.phases.get(node, {})
            state = ('FAIL' if 'failed' in phases.values() else 'SKIP' if 'skipped' in phases.values()
                     else 'PASS' if phases == dict.fromkeys(('setup', 'call', 'teardown'), 'passed') else 'BLOCKED')
            outcomes.append({'nodeid': node, 'outcome': state})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.pending')
        temporary.write_text(json.dumps({'terminal': terminal, 'exit_code': exit_code,
            'node_outcomes': outcomes, 'phase_reports': self.phases,
            'duplicates_removed': self.duplicates_removed, 'failures': self.failures}) + '\n', encoding='utf-8')
        temporary.replace(self.path)
