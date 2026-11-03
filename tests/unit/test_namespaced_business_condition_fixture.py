"""The prepared native witness rejects missing/typed values using fake native I/O."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.destructive.support import namespaced_query_fixture as fixture
from tests.unit.test_namespaced_query_fixture import sandbox_copy
from tests.unit.test_query_namespaced_conditions import NamespacedTask
from tests.unit.test_workflow_source_guard import workflow


@pytest.mark.parametrize('fault', ['none', 'missing-before', 'bool-before', 'missing-after', 'native-error'])
def test_public_condition_witness_requires_actual_value_reads_and_freezes_first_failure(tmp_path, workflow, monkeypatch, fault):
    from tests.destructive import test_query_namespaced_business_conditions as witness
    sandbox, owned, io = sandbox_copy(tmp_path)
    report = fixture.prepare_namespaced_query_fixture(sandbox, owned_root=owned, io_root=io)
    sandbox.metadata = SimpleNamespace(get_info_version=dict(year=2025, major=1, minor=7, build=9143))
    task_root = tmp_path / 'fake-native'; task_root.mkdir()
    task = NamespacedTask(task_root, '2025.1')
    task.info['version'].update(year=2025, major=1, minor=7, build=9143)
    task.info['isCommandLine'] = True
    task.project['filePath'] = str(sandbox.sandbox_project)
    sound = task.members[fixture.SOUND]
    sound.update(name='Footstep_Crouching_Concrete_01', path='\\Containers\\Footsteps\\Footstep_Crouching_Concrete_01')
    sound['@@' + fixture.TOKEN] = 0
    task.metadata[fixture.SOUND] = copy.deepcopy(task.metadata[sound['classId']])
    task.rows = [sound]
    packets = owned / 'packets'; packets.mkdir()
    task.env['WWISE_EVIDENCE_DIR'] = str(packets)
    runtime = SimpleNamespace(version='2025.1', sandbox=sandbox, namespaced_query_prelaunch=report,
        state_dir=owned / 'state', env=task.env, candidate='program-only', category_results=[])
    task.env['WAAPI_SKILL_STATE_DIR'] = str(runtime.state_dir)
    public_conditions, selected_calls = [], []
    original = task.call
    def native(uri, args=None, options=None):
        expression = (args or {}).get('waql', '')
        if uri.endswith('object.get') and 'where @MyCompany:Status' in expression:
            selected_calls.append(expression)
            if fault == 'native-error': raise RuntimeError('Simulated native syntax rejection; never retry')
        result = original(uri, args, options)
        field = '@' + fixture.TOKEN
        if uri.endswith('object.get') and field in (options or {}).get('return', ()) and ' where ' not in expression:
            if fault in {'missing-before', 'bool-before'} or fault == 'missing-after' and selected_calls:
                for row in result['return']:
                    if fault == 'bool-before': row[field] = False
                    else: row.pop(field, None)
        return result
    task.call = native
    def raw(argv):
        if '--where-field' in argv: public_conditions.append(list(argv))
        return workflow.waapi_gateway.execute_gateway(['--timeout', '30', '--state-dir', str(runtime.state_dir), *argv],
            env=runtime.env, client_factory=lambda _: task)
    runtime.raw_gateway = raw
    if fault == 'none': witness.test_namespaced_closed_conditions_require_native_value_readback(runtime, monkeypatch)
    else:
        with pytest.raises(AssertionError):
            witness.test_namespaced_closed_conditions_require_native_value_readback(runtime, monkeypatch)
    category, = runtime.category_results
    body = Path(category['observation_path']).read_bytes()
    assert fixture.sha(body) == category['observation_sha256']
    receipt = json.loads(body)
    if fault == 'none':
        assert category['status'] == 'PASS' and receipt['typed_custom_return_proof'] is True
        assert len(public_conditions) == 4 and len(receipt['reads']) == 7
        assert len(selected_calls) == 2  # Two ordinary comparisons; override calls are independently traced too.
        assert all(argv[argv.index('--where-field') + 2] == fixture.TOKEN for argv in public_conditions)
    else:
        assert category['status'] == 'FAIL' and category['business_effect_verified'] is False
        assert receipt['typed_custom_return_proof'] is False and len(public_conditions) == 1
        assert len(selected_calls) == (1 if fault in {'native-error', 'missing-after'} else 0)
    assert receipt['override_difference_proof'] is False
    assert not any('--advanced-waql' in argv for argv in public_conditions)
