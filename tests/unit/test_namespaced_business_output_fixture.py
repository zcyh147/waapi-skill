"""The prepared output witness uses the real Gateway with fake native transport."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.destructive.support import namespaced_query_fixture as fixture
from tests.unit.test_namespaced_query_fixture import sandbox_copy
from tests.unit.test_query_namespaced_conditions import NamespacedTask
from tests.unit.test_query_related_paths import REFERENCE_CLASS, SOUND_CLASS
from tests.unit.test_workflow_source_guard import workflow


@pytest.mark.parametrize('fault', ['none', 'missing-chain', 'bool-chain', 'missing-member', 'native-error'])
def test_public_output_witness_requires_actual_chained_and_member_values(tmp_path, workflow, monkeypatch, fault):
    from tests.destructive import test_query_namespaced_business_outputs as witness
    sandbox, owned, io = sandbox_copy(tmp_path)
    report = fixture.prepare_namespaced_query_fixture(sandbox, owned_root=owned, io_root=io)
    sandbox.metadata = SimpleNamespace(get_info_version=dict(year=2025, major=1, minor=7, build=9143))
    task_root = tmp_path / 'fake-native'; task_root.mkdir()
    task = NamespacedTask(task_root, '2025.1')
    task.info['version'].update(year=2025, major=1, minor=7, build=9143)
    task.info['isCommandLine'] = True
    task.project['filePath'] = str(sandbox.sandbox_project)
    sound = task.members[fixture.SOUND]
    sound.update(name='Footstep_Crouching_Concrete_01', path='\\Containers\\Footsteps\\FS_Concrete\\Footstep_Crouching_Concrete_01')
    sound['@@' + fixture.TOKEN] = 0
    container = task.objects[witness.CONTAINER]
    container['name'] = 'FS_Concrete'; container['classId'] = REFERENCE_CLASS
    container['children'] = [task.reference(fixture.SOUND)]
    sound['parent'] = {key: container[key] for key in ('id', 'name')}
    task.metadata[fixture.SOUND] = copy.deepcopy(task.metadata[SOUND_CLASS])
    source = {'id': witness.AUDIO_SOURCE, 'name': sound['name'], 'type': 'AudioFileSource',
        'path': sound['path'] + '\\Source', 'classId': REFERENCE_CLASS,
        'parent': {key: sound[key] for key in ('id', 'name')}, 'parent.classId': SOUND_CLASS,
        'parent.@' + fixture.TOKEN: 0, 'parent.@@' + fixture.TOKEN: 0}
    task.objects[witness.AUDIO_SOURCE] = source
    task.rows = [sound]
    packets = owned / 'packets'; packets.mkdir()
    task.env['WWISE_EVIDENCE_DIR'] = str(packets)
    runtime = SimpleNamespace(version='2025.1', sandbox=sandbox, namespaced_query_prelaunch=report,
        state_dir=owned / 'state', env=task.env, candidate='program-only', category_results=[])
    task.env['WAAPI_SKILL_STATE_DIR'] = str(runtime.state_dir)
    related_argv, phase, chain_calls = [], '', []
    original = task.call
    def native(uri, args=None, options=None):
        fields = (options or {}).get('return', ())
        if uri.endswith('object.get') and 'parent.@' + fixture.TOKEN in fields:
            chain_calls.append(copy.deepcopy(args))
            if fault == 'native-error': raise RuntimeError('Simulated chained native syntax rejection; no retry')
        result = original(uri, args, options)
        if uri.endswith('object.get'):
            for row in result['return']:
                if 'parent.@@' + fixture.TOKEN in fields:
                    if fault == 'missing-chain': row.pop('parent.@@' + fixture.TOKEN, None)
                    elif fault == 'bool-chain': row['parent.@@' + fixture.TOKEN] = False
                if fault == 'missing-member' and phase == 'selected' and row.get('id') == fixture.SOUND:
                    row.pop('@@' + fixture.TOKEN, None)
        return result
    task.call = native
    def raw(argv):
        nonlocal phase
        if '--include-related-field' in argv:
            related_argv.append(list(argv)); phase = 'selected' if 'children' in argv else 'singleton'
        else: phase = 'other'
        return workflow.waapi_gateway.execute_gateway(['--timeout', '30', '--state-dir', str(runtime.state_dir), *argv],
            env=runtime.env, client_factory=lambda _: task)
    runtime.raw_gateway = raw
    if fault == 'none': witness.test_namespaced_property_outputs_preserve_actual_related_values(runtime, monkeypatch)
    else:
        with pytest.raises(AssertionError):
            witness.test_namespaced_property_outputs_preserve_actual_related_values(runtime, monkeypatch)
    category, = runtime.category_results
    body = Path(category['observation_path']).read_bytes()
    assert fixture.sha(body) == category['observation_sha256']
    receipt = json.loads(body)
    assert receipt['override_difference_proof'] is False
    if fault == 'none':
        assert category['status'] == 'PASS' and receipt['typed_custom_return_proof'] is True
        assert len(receipt['reads']) == 7 and len(related_argv) == 2 and len(chain_calls) == 1
        assert receipt['dispatch_count'] <= 128
        selected = receipt['reads'][5]['invocations'][0]['payload']['agent_result'][0]['related']['projections']
        projection, = selected
        item, = projection['items']
        assert item['properties'] == item['override_source_values'] == {fixture.TOKEN: 0}
    else:
        assert category['status'] == 'FAIL' and category['business_effect_verified'] is False
        assert receipt['typed_custom_return_proof'] is False
        assert len(related_argv) == (2 if fault == 'missing-member' else 1)
        assert receipt['reads'][-1]['label'] == ('selected-child-property-outputs' if fault == 'missing-member' else 'singleton-parent-property-outputs')
        if fault == 'native-error': assert len(chain_calls) == 1
    assert not any('--advanced-waql' in argv or '--where-field' in argv for argv in related_argv)
