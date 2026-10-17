"""Ordinary CI cannot arm an inherited original scalar evidence producer."""
from pathlib import Path
import json
import subprocess
import sys

import pytest

from ci import test_driver


ROOT = Path(__file__).parents[2]
TARGET = 'tests/unit/test_scalar_condition_product_gateway.py'


@pytest.fixture(scope='module')
def full_selection():
    from tests.maintenance import branch_coverage_audit as audit
    from tests.support.condition_scalar_batch import scalar_manifest, scalar_plan
    plan = scalar_plan(scalar_manifest(ROOT))
    return {'contract': 'waapi-skill.condition-scalar-program-selection/v1',
        'source_plan_sha256': audit.digest(plan), 'group_ids': [group['id'] for group in plan['groups']]}


def _select(tmp_path, monkeypatch, selection):
    path = tmp_path / 'selection.json'
    path.write_text(json.dumps(selection))
    monkeypatch.setenv('WAAPI_SCALAR_PROGRAM_SELECTION', str(path))


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


def test_actual_pytest_rejects_unrelated_collected_node_before_inventory_or_root(tmp_path, monkeypatch, full_selection):
    from tests.maintenance import branch_coverage_audit as audit
    inventory_calls = []
    def forbidden():
        inventory_calls.append(True)
        raise AssertionError('inventory must not build for an unrelated session')
    monkeypatch.setattr(audit, 'build_inventory', forbidden)
    monkeypatch.setenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
    monkeypatch.setenv('WAAPI_SCALAR_PROGRAM_BATCH_ROOT', str(tmp_path / 'capture'))
    _select(tmp_path, monkeypatch, full_selection)
    unrelated = tmp_path / 'test_unrelated.py'
    unrelated.write_text('def test_unrelated():\n    pass\n')
    code = pytest.main([str(ROOT / TARGET), str(unrelated), '-q', '-p', 'no:cacheprovider'])
    assert int(code) == 1
    assert inventory_calls == []
    assert not (tmp_path / 'capture').exists()


def test_actual_pytest_filtered_missing_versions_cannot_create_a_partial_default_batch(tmp_path, monkeypatch, full_selection):
    from tests.maintenance import branch_coverage_audit as audit
    def forbidden():
        raise AssertionError('inventory must not build before exact group coverage')
    monkeypatch.setattr(audit, 'build_inventory', forbidden)
    monkeypatch.setenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
    monkeypatch.setenv('WAAPI_SCALAR_PROGRAM_BATCH_ROOT', str(tmp_path / 'capture'))
    _select(tmp_path, monkeypatch, full_selection)
    code = pytest.main([str(ROOT / TARGET), '-k', '2025.1', '-q', '-p', 'no:cacheprovider'])
    assert int(code) == 1
    assert not (tmp_path / 'capture').exists()


def test_actual_allfive_pytest_root_without_selection_fails_before_inventory_or_root(tmp_path, monkeypatch):
    from tests.maintenance import branch_coverage_audit as audit
    inventory_calls = []
    def forbidden():
        inventory_calls.append(True)
        raise AssertionError('missing explicit selection must fail before inventory')
    monkeypatch.setattr(audit, 'build_inventory', forbidden)
    monkeypatch.setenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
    monkeypatch.setenv('WAAPI_SCALAR_PROGRAM_BATCH_ROOT', str(tmp_path / 'capture'))
    monkeypatch.delenv('WAAPI_SCALAR_PROGRAM_SELECTION', raising=False)
    code = pytest.main([str(ROOT / TARGET), '-q', '-p', 'no:cacheprovider'])
    assert int(code) == 1
    assert inventory_calls == []
    assert not (tmp_path / 'capture').exists()


@pytest.mark.parametrize('damage', ['stale-plan', 'duplicate-group', 'unknown-group'])
def test_actual_pytest_rejects_changed_selection_before_inventory(tmp_path, monkeypatch, full_selection, damage):
    from copy import deepcopy
    from tests.maintenance import branch_coverage_audit as audit
    selection = deepcopy(full_selection)
    if damage == 'stale-plan':
        selection['source_plan_sha256'] = '0' * 64
    elif damage == 'duplicate-group':
        selection['group_ids'].append(selection['group_ids'][0])
    else:
        selection['group_ids'].append('unknown')
    inventory_calls = []
    def forbidden():
        inventory_calls.append(True)
        raise AssertionError('changed selection must fail before inventory')
    monkeypatch.setattr(audit, 'build_inventory', forbidden)
    monkeypatch.setenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
    monkeypatch.setenv('WAAPI_SCALAR_PROGRAM_BATCH_ROOT', str(tmp_path / 'capture'))
    _select(tmp_path, monkeypatch, selection)
    code = pytest.main([str(ROOT / TARGET), '-q', '-p', 'no:cacheprovider'])
    assert int(code) == 1 and inventory_calls == []
    assert not (tmp_path / 'capture').exists()


def test_actual_allfive_pytest_explicit_frozen_selection_reaches_original_producer(tmp_path, monkeypatch, full_selection):
    from tests.maintenance import branch_coverage_audit as audit
    from tests.support import condition_scalar_program as producer
    inventory_calls, preparations, finishes = [], [], []
    def inventory():
        inventory_calls.append(True)
        return {}
    def prepare(output, nodeids, plan, observed_inventory, **options):
        preparations.append(options['node_groups'])
        assert observed_inventory == {}
        assert {identity for values in options['node_groups'].values() for identity in values} == set(full_selection['group_ids'])
        # Admission control only: no product workflow or evidence is produced here.
        return {'node_groups': {node: [] for node in nodeids}}
    monkeypatch.setattr(audit, 'build_inventory', inventory)
    monkeypatch.setattr(producer, 'prepare_program_batch', prepare)
    monkeypatch.setattr(producer, 'finish_program_node', lambda *args: finishes.append(args[2]))
    monkeypatch.setenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
    monkeypatch.setenv('WAAPI_SCALAR_PROGRAM_BATCH_ROOT', str(tmp_path / 'capture'))
    _select(tmp_path, monkeypatch, full_selection)
    code = pytest.main([str(ROOT / TARGET), '-q', '-p', 'no:cacheprovider'])
    assert int(code) == 0
    assert inventory_calls == [True] and len(preparations) == 1 and len(finishes) == 5
    assert all(set(reports) == {'setup', 'call', 'teardown'} for reports in finishes)
    assert not (tmp_path / 'capture').exists()
