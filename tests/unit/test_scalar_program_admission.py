"""Ordinary CI cannot arm an inherited original scalar evidence producer."""
from pathlib import Path
import subprocess
import sys

import pytest

from ci import test_driver


ROOT = Path(__file__).parents[2]
TARGET = 'tests/unit/test_scalar_condition_product_gateway.py'


@pytest.mark.parametrize('mode,args,retained', [
    ('program', (), False), ('notice-fast', (), False), ('nonlive', (), False),
    ('nonlive', ('tests/unit', '-q'), False),
    ('nonlive', (TARGET, 'tests/unit/test_metadata_discovery.py', '-q'), False),
    ('nonlive', (TARGET, '-q', '--basetemp=/tmp/explicit-original-temp'), True),
    ('nonlive', (TARGET + '::test_product_self_scalar_source_conditions[2025.1]', '-q'), True),
])
def test_driver_keeps_scalar_environment_only_for_explicit_standalone_target(monkeypatch, mode, args, retained):
    calls = []
    monkeypatch.setattr(test_driver, 'validate_nonlive_readiness', lambda *_: None)
    def run(command, **options):
        calls.append(options['env'])
        return subprocess.CompletedProcess(command, 0)
    driver = test_driver.TestDriver(environment={'WAAPI_SCALAR_PROGRAM_BATCH_ROOT': '/tmp/inherited-original-root',
        'WAAPI_SCALAR_PROGRAM_SELECTION': '/tmp/inherited-selection.json'},
        python_executable=sys.executable, command_runner=run)
    assert driver.run(test_driver.TestRequest(version='none', mode=mode, pytest_args=args)) == 0
    assert len(calls) == 1
    assert ('WAAPI_SCALAR_PROGRAM_BATCH_ROOT' in calls[0]) is retained
    assert ('WAAPI_SCALAR_PROGRAM_SELECTION' in calls[0]) is retained


def test_actual_pytest_rejects_unrelated_collected_node_before_inventory_or_root(tmp_path, monkeypatch):
    from tests.maintenance import branch_coverage_audit as audit
    inventory_calls = []
    def forbidden():
        inventory_calls.append(True)
        raise AssertionError('inventory must not build for an unrelated session')
    monkeypatch.setattr(audit, 'build_inventory', forbidden)
    monkeypatch.setenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
    monkeypatch.setenv('WAAPI_SCALAR_PROGRAM_BATCH_ROOT', str(tmp_path / 'capture'))
    monkeypatch.delenv('WAAPI_SCALAR_PROGRAM_SELECTION', raising=False)
    unrelated = tmp_path / 'test_unrelated.py'
    unrelated.write_text('def test_unrelated():\n    pass\n')
    code = pytest.main([str(ROOT / TARGET), str(unrelated), '-q', '-p', 'no:cacheprovider'])
    assert int(code) == 1
    assert inventory_calls == []
    assert not (tmp_path / 'capture').exists()


def test_actual_pytest_filtered_missing_versions_cannot_create_a_partial_default_batch(tmp_path, monkeypatch):
    from tests.maintenance import branch_coverage_audit as audit
    def forbidden():
        raise AssertionError('inventory must not build before exact group coverage')
    monkeypatch.setattr(audit, 'build_inventory', forbidden)
    monkeypatch.setenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
    monkeypatch.setenv('WAAPI_SCALAR_PROGRAM_BATCH_ROOT', str(tmp_path / 'capture'))
    monkeypatch.delenv('WAAPI_SCALAR_PROGRAM_SELECTION', raising=False)
    code = pytest.main([str(ROOT / TARGET), '-k', '2025.1', '-q', '-p', 'no:cacheprovider'])
    assert int(code) == 1
    assert not (tmp_path / 'capture').exists()
