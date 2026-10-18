"""Literal native missing-controller pattern at the public same-graph seam."""
import json
from pathlib import Path

import pytest

from tests.unit.test_workflow_source_guard import workflow, _new_result_reference_runtime


def test_absent_override_on_auxbus_keeps_one_same_graph_write(tmp_path, workflow):
    runtime, commands, writes, task = _new_result_reference_runtime(
        tmp_path, workflow, '2025.1', noisy_fields=True, native_conditions=True)
    original = task.call
    def call(uri, args=None, options=None):
        if uri.endswith('getPropertyInfo') and args.get('property') == 'OverrideUserAuxSends':
            raise RuntimeError("Property doesn't exist on the object (literal 553 controller absence)")
        return original(uri, args, options)
    task.call = call
    category = workflow._collect_new_result_scalar_reference_acceptance(runtime, root_name='WAAPI_RESULT_REFERENCE_TEST')
    assert category['status'] == 'PASS', category
    assert len(writes) == 1
    assert not any(call[0].endswith('getPropertyInfo') and call[1].get('property') == 'OverrideUserAuxSends' for call in task.calls)
    source = writes[0][1]['objects'][0]['children'][0]['children'][1]
    assert '@OverrideUserAuxSends' not in source



@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1'])
def test_source_absent_override_is_sealed_for_both_native_graph_lanes(tmp_path, workflow, version):
    runtime, commands, writes, task = _new_result_reference_runtime(tmp_path, workflow, version, native_conditions=True)
    category = workflow._collect_new_result_scalar_reference_acceptance(runtime, root_name='WAAPI_RESULT_REFERENCE_TEST')
    assert category['status'] == 'PASS'
    preview_command = next(row for row in json.loads(Path(category['observation_path']).read_text())['calls'] if row['argv'][0] == 'transaction-show')
    nodes = preview_command['payload']['artifact']['prepared_operation']['verification_plan']['nodes']
    sender = next(row for row in nodes if row.get('requested_name') == 'Sender')
    evidence = sender['new_object_default_evidence'][0]
    assert evidence['requirements'] == [] and evidence['derived_properties'] == {}
    assert evidence['override_applicability'][0]['version'] == version
    assert evidence['override_applicability'][0]['structural_proof']['parent']['request_path']
    assert len(writes) == 1


@pytest.mark.parametrize('fault', ['controller-present', 'field-missing', 'source-missing', 'incomplete-closure', 'bad-source-seal'])
def test_absent_override_needs_complete_source_and_exact_live_names(tmp_path, workflow, monkeypatch, fault):
    from wwise_waapi import override_applicability as module
    from wwise_waapi.canonical import canonical_sha256
    runtime, commands, writes, task = _new_result_reference_runtime(tmp_path, workflow, '2025.1', native_conditions=True)
    original = task.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('getPropertyAndReferenceNames') and args.get('classId') == 3997712:
            if fault == 'controller-present': result['return'].append('OverrideUserAuxSends')
            if fault == 'field-missing': result['return'] = []
        return result
    task.call = call
    if fault.startswith('source') or fault in {'incomplete-closure', 'bad-source-seal'}:
        root = tmp_path / 'override-source'
        target = root / '2025.1' / 'override-applicability.json'
        target.parent.mkdir(parents=True)
        value = json.loads((module.CATALOG_ROOT / '2025.1' / target.name).read_text())
        if fault == 'incomplete-closure': value['nodes'] = [row for row in value['nodes'] if row['key'] != 'ObjectBase:UserAuxSends']
        if fault == 'bad-source-seal': value['source']['build'] = 'unreviewed'
        else: value['catalog_sha256'] = canonical_sha256({key: item for key, item in value.items() if key != 'catalog_sha256'})
        if fault != 'source-missing': target.write_text(json.dumps(value))
        monkeypatch.setattr(module, 'CATALOG_ROOT', root)
    with pytest.raises(AssertionError):
        workflow._collect_new_result_scalar_reference_acceptance(runtime, root_name='WAAPI_RESULT_REFERENCE_TEST')
    assert not writes


@pytest.mark.parametrize('explicit', [None, True, False])
def test_declared_sound_user_send_override_keeps_ordinary_controller_planner(tmp_path, explicit):
    from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, FIRST, SECOND, ROOT
    task = OwnedGraphTask(tmp_path, '2025.1', 'object.set')
    task.types = [{'name': name, 'classId': value, 'type': 'WObject'} for name, value in (
        ('Sound', 65552), ('WorkUnit', 1638416), ('AuxBus', 3997712))]
    task.objects = {
        FIRST: {'id': FIRST, 'name': 'Rain', 'type': 'Sound', 'classId': 65552,
            'path': r'\Actor-Mixer Hierarchy\Default Work Unit\Rain', 'parent': {'id': SECOND},
            'notes': 'Keep source', '@UserAuxSend0': None, '@OverrideUserAuxSends': False},
        SECOND: {'id': SECOND, 'name': 'Default Work Unit', 'type': 'WorkUnit', 'classId': 1638416,
            'path': r'\Actor-Mixer Hierarchy\Default Work Unit'},
        ROOT: {'id': ROOT, 'name': 'Hall', 'type': 'AuxBus', 'classId': 3997712,
            'path': r'\Busses\Default Work Unit\Hall'},
    }
    task.metadata = {
        'UserAuxSend0': {'name': 'UserAuxSend0', 'type': '', 'restriction': {'type': 'reference',
            'restrictions': [{'type': ['Auxiliary Bus'], 'sharedOnlyTypes': []}]},
            'dependencies': [
                {'type': 'isMasterBus', 'value': False, 'action': 'Show', 'context': 'Self'},
                {'type': 'override', 'action': 'Enable', 'context': 'Self', 'property': 'OverrideUserAuxSends'}]},
        'OverrideUserAuxSends': {'name': 'OverrideUserAuxSends', 'type': 'bool', 'default': False},
    }
    source, target = task.bind(FIRST), task.bind(ROOT)
    reference = task.discover(source, 'UserAuxSend0')
    fields = ['--field-value', reference, target]
    if explicit is not None:
        controller = task.discover(source, 'OverrideUserAuxSends')
        fields += ['--field-value', controller, json.dumps(explicit)]
    code, declared = task.step('draft-declare-existing', '--declaration-id', 'source', '--object-handle', source, *fields)
    assert code == 0, declared
    if explicit is False:
        code, rejected = task.step('draft-check')
        assert code == 2, rejected
    else:
        _tx, shown = task.preview()
        native = shown['artifact']['prepared_operation']['dispatch']['args']['objects'][0]
        assert native['@UserAuxSend0'] == ROOT
        assert native['@OverrideUserAuxSends'] is True
    assert any(uri.endswith('getPropertyInfo') and args.get('property') == 'OverrideUserAuxSends' for uri, args, _ in task.calls)
    assert not any(uri.endswith(('object.set', 'setProperty', 'setReference')) for uri, _args, _options in task.calls)


@pytest.mark.parametrize('fault', ['catalog-drift', 'field-dependency-drift', 'controller-appears'])
def test_absent_override_proof_drift_blocks_the_only_write(tmp_path, monkeypatch, fault):
    from tests.unit.test_new_object_bus_conditions_gateway import _bus_children_task
    from wwise_waapi import override_applicability as module
    from wwise_waapi.canonical import canonical_sha256
    task, writes = _bus_children_task(tmp_path)
    if fault == 'catalog-drift':
        target = tmp_path / 'source' / '2025.1' / 'override-applicability.json'
        target.parent.mkdir(parents=True)
        target.write_bytes((module.CATALOG_ROOT / '2025.1' / target.name).read_bytes())
        monkeypatch.setattr(module, 'CATALOG_ROOT', target.parents[1])
    tx, shown = task.preview()
    if fault == 'catalog-drift':
        value = json.loads(target.read_text())
        value['nodes'][0]['source_node_sha256'] = '0' * 64
        value['catalog_sha256'] = canonical_sha256({key: item for key, item in value.items() if key != 'catalog_sha256'})
        target.write_text(json.dumps(value))
    elif fault == 'field-dependency-drift':
        task.metadata['UserAuxSend0']['dependencies'][1]['context'] = 'Parent'
    else:
        task.metadata['OverrideUserAuxSends'] = {'name': 'OverrideUserAuxSends', 'type': 'bool', 'default': False}
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, rejected = task.run('execute', tx)
    assert code == 2 and rejected.get('executed') is not True, rejected
    assert not writes


@pytest.mark.parametrize('wrong_node', ['Sender', 'WAAPI_RESULT_REFERENCE_TEST'])
def test_old_create_applicability_requires_actual_source_and_parent_class(tmp_path, workflow, wrong_node):
    runtime, commands, writes, task = _new_result_reference_runtime(tmp_path, workflow, '2021.1', native_conditions=True)
    original = task.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('object.create'):
            next(row for row in task.objects.values() if row['name'] == wrong_node)['classId'] = 65552
        return result
    task.call = call
    with pytest.raises(AssertionError):
        workflow._collect_new_result_scalar_reference_acceptance(runtime, root_name='WAAPI_RESULT_REFERENCE_TEST')
    receipt = json.loads(Path(runtime.category_results[0]['observation_path']).read_text())
    assert receipt['gateway_verification']['payload'].get('verified') is not True
    assert len(writes) == 1 and [command[0] for command in commands].count('execute') == 1
