from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.destructive.support.sandbox_fixture import hash_project
from tests.destructive.support import exact_real_evidence
from tests.support.platform_filesystem import create_symlink_or_skip


@pytest.fixture
def workflow(monkeypatch):
    monkeypatch.setenv("WWISE_LIVE", "1")
    monkeypatch.setenv("WWISE_DESTRUCTIVE", "1")
    return importlib.import_module("tests.destructive.test_gateway_workflow_transaction_matrix")


def _effect_slot_merge_runtime(tmp_path, workflow, version, *, fault=None):
    """Real public Gateway; native fake keeps actual anonymous slots and local Effects."""
    from copy import deepcopy
    import uuid
    from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, FIRST, SECOND

    task = OwnedGraphTask(tmp_path, version, 'object.create')
    task.types = [{'name': name, 'classId': value, 'type': kind} for name, value, kind in (
        ('Sound', 65552, 'WObject'), ('WorkUnit', 1638416, 'WObject'),
        ('EffectSlot', 5505040, 'WObject'), ('Wwise Gain', 9109507, 'Effect'))]
    path = ('\\Containers' if version == '2025.1' else '\\Actor-Mixer Hierarchy') + '\\Default Work Unit'
    task.objects = {SECOND: {'id': SECOND, 'name': 'Default Work Unit', 'type': 'WorkUnit',
        'classId': 1638416, 'path': path, 'parent': None, 'notes': 'Keep parent'}}
    task.metadata = {'Effect': {'name': 'Effect', 'type': '', 'default': None,
        'restriction': {'type': 'reference', 'restrictions': [{'type': ['Effect']}]}}}
    for name in ('Bypass', 'Render'):
        task.metadata[name] = {'name': name, 'type': 'bool', 'default': False,
            'dependencies': [{'type': 'reference', 'action': 'Enable', 'context': 'Self', 'property': 'Effect',
                'conditions': [{'referenceIsSet': True}]}]}
    original = task.call
    writes, commands = [], []
    def call(uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri.endswith('isPropertyEnabled'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args['property'] in ('Bypass', 'Render') and task.objects[args['object']]['@Effect']['id'] in task.objects, args
            return {'return': True}
        if uri.endswith('object.create'):
            task.calls.append((uri, deepcopy(args), deepcopy(options))); writes.append((uri, deepcopy(args)))
            assert args == {'parent': SECOND, 'type': 'Sound', 'name': 'WAAPI_SLOT_TEST',
                'notes': 'Keep sound', 'onNameConflict': 'fail', 'autoAddToSourceControl': False}, args
            task.objects[FIRST] = {'id': FIRST, 'name': args['name'], 'type': 'Sound', 'classId': 65552,
                'path': path + '\\' + args['name'], 'parent': {'id': SECOND}, 'notes': args['notes'], '@IsVoice': False, '@Effects': []}
            return {'id': FIRST, 'name': args['name']}
        if uri.endswith('object.set'):
            task.calls.append((uri, deepcopy(args), deepcopy(options))); writes.append((uri, deepcopy(args)))
            rows = args['objects']
            if '@Effects' in rows[0]:
                index = len(task.objects[FIRST]['@Effects'])
                node = rows[0]['@Effects'][0]
                assert node['type'] == 'EffectSlot' and node['name'] == '', args
                plugin = node['@Effect']
                assert plugin['type'] == 'Effect' and plugin['classId'] == 9109507, args
                slot, effect = ('{' + str(uuid.UUID(int=value)).upper() + '}' for value in (11 + index, 21 + index))
                task.objects[slot] = {'id': slot, 'name': '', 'type': 'EffectSlot', 'classId': 5505040,
                    'path': '\\opaque-slot-' + str(index), 'owner': {'id': FIRST}, 'notes': '',
                    '@Effect': {'id': effect}, '@Bypass': False, '@Render': False}
                task.objects[effect] = {'id': effect, 'name': plugin['name'], 'type': 'Effect', 'classId': 9109507,
                    'path': '\\opaque-local-effect-' + str(index), 'owner': {'id': slot},
                    'notes': plugin['notes'], '@FullBandGain': 0.0, '@LFEGain': 0.0}
                task.objects[FIRST]['@Effects'].append({'id': slot})
                return {'objects': [{'id': FIRST, 'name': task.objects[FIRST]['name'], '@Effects': [
                    {'id': slot, 'name': '', '@Effect': {'id': effect, 'name': plugin['name']}}]}]}
            if fault == 'native-error':
                raise RuntimeError('Actual selected slot write refused; no retry')
            result = []
            for row in rows:
                target = task.objects[row['object']]
                if 'name' in row:
                    assert row['object'] == FIRST, row
                    target.update(name=row['name'], path=path + '\\' + row['name'])
                if '@Bypass' in row:
                    assert set(row) == {'object', '@Bypass'} and target['type'] == 'EffectSlot', row
                    target['@Bypass'] = row['@Bypass']
                result.append({'id': target['id'], 'name': target['name']})
            slot_ids = [entry['id'] for entry in task.objects[FIRST]['@Effects']]
            selected, spare = (task.objects[value] for value in slot_ids)
            if fault == 'wrong-reference': selected['@Effect'] = deepcopy(spare['@Effect'])
            if fault == 'wrong-owner': selected['owner'] = {'id': SECOND}
            if fault == 'wrong-class': selected['classId'] = 1441808
            if fault == 'wrong-order': task.objects[FIRST]['@Effects'].reverse()
            if fault == 'wrong-value': selected['@Bypass'] = not selected['@Bypass']
            if fault == 'spare-value': spare['@Render'] = True
            if fault == 'effect-notes': task.objects[selected['@Effect']['id']]['notes'] = 'Not requested'
            if fault == 'effect-owner': task.objects[selected['@Effect']['id']]['owner'] = {'id': FIRST}
            if fault == 'effect-parent': task.objects[selected['@Effect']['id']]['parent'] = {'id': selected['id']}
            if fault == 'slot-parent-null': selected['parent'] = None
            if fault == 'rename-path' and len(writes) == 5: selected['path'] += 'Unexpected'
            return {'objects': result}
        if uri.endswith('object.get') and args.get('waql') != 'from type Project take 1':
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            expression = args.get('waql', '')
            if expression:
                assert expression.startswith('from object "'), expression
                identity = expression.split('"')[1]
                rows = [row for row in task.objects.values() if identity in (row['id'], row['path'])]
                if 'select @Effects' in expression:
                    assert len(rows) == 1, expression
                    rows = [task.objects[member['id']] for member in rows[0]['@Effects']]
            elif 'id' in args.get('from', {}):
                rows = [task.objects[value] for value in args['from']['id'] if value in task.objects]
            else:
                rows = [row for row in task.objects.values() if row['path'] in args['from']['path']]
            for transform in args.get('transform', []):
                assert len(rows) == 1, args
                source = rows[0]
                token = transform['select'][0]
                if token == 'children':
                    rows = [row for row in task.objects.values() if row.get('parent') == {'id': source['id']}]
                elif token == '@Effects':
                    rows = [task.objects[member['id']] for member in source['@Effects']]
                else:
                    raise AssertionError(args)
            return {'return': [{key: deepcopy(row.get(key, row.get('@' + key))) for key in options['return']
                if key in row or '@' + key in row} for row in rows]}
        if uri.endswith(('getPropertyAndReferenceNames', 'getPropertyInfo')) and (args.get('classId') == 9109507 or task.objects.get(args.get('object'), {}).get('type') == 'Effect'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': ['FullBandGain', 'LFEGain']} if uri.endswith('getPropertyAndReferenceNames') else {'name': args['property'], 'type': 'Real64', 'default': 0.0}
        return original(uri, args, options)
    task.call = call
    runtime = SimpleNamespace(version=version, state_dir=tmp_path / 'state', env=task.env,
        candidate='fixture-candidate', category_results=[])
    def raw(command):
        commands.append(list(command))
        code, payload = workflow.waapi_gateway.execute_gateway(['--state-dir', str(runtime.state_dir), *command],
            env=runtime.env, client_factory=lambda _url: task)
        if fault == 'prestate-owner' and command[0] == 'transaction-show' and len(writes) == 3:
            first = task.objects[FIRST]['@Effects'][0]['id']
            task.objects[first]['owner'] = {'id': SECOND}
        return code, payload
    runtime.raw_gateway = raw
    return runtime, commands, writes, task


@pytest.mark.parametrize('version', ['2023.1', '2024.1', '2025.1'])
def test_existing_effect_slot_collector_uses_anonymous_exact_guid_edits(tmp_path, workflow, version):
    runtime, commands, writes, _task = _effect_slot_merge_runtime(tmp_path, workflow, version)
    category = workflow._collect_existing_effect_slot_exact_member_acceptance(runtime, sound_name='WAAPI_SLOT_TEST')
    assert category['status'] == 'PASS'
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert receipt['business_effect_verified'] is True and receipt['inline_list_merge_verified'] is False
    assert receipt['setup_coverage_credit'] is False
    assert len(writes) == 5 and [cmd[0] for cmd in commands].count('verify') == 5
    assert [row['name'] for row in receipt['baseline']['slots']] == ['', '']
    assert len({row['id'] for row in receipt['baseline']['slots']}) == 2
    for slot, effect in zip(receipt['baseline']['slots'], receipt['baseline']['effects'], strict=True):
        assert effect['owner']['id'] == slot['id']
        assert 'parent' not in slot and 'parent' in slot['unavailable_fields']
        assert 'parent' not in effect and 'parent' in effect['unavailable_fields']
        assert effect['properties'] == {'FullBandGain': 0.0, 'LFEGain': 0.0}
    assert [phase['phase'] for phase in receipt['transactions'][-2:]] == ['exact_member_bypass', 'owner_rename_and_exact_member_bypass']
    assert receipt['transactions'][-1]['independent_effect']['owner']['name'] == 'WAAPI_SLOT_TEST_Renamed'
    assert len(receipt['calls']) <= 192 and Path(category['observation_path']).stat().st_size <= 8 * 1024 * 1024


@pytest.mark.parametrize('fault', ['wrong-reference', 'wrong-owner', 'wrong-class', 'wrong-order',
    'wrong-value', 'spare-value', 'effect-notes', 'rename-path', 'prestate-owner', 'native-error'])
def test_existing_effect_slot_collector_rejects_unrequested_or_failed_effect(tmp_path, workflow, fault):
    runtime, commands, writes, _task = _effect_slot_merge_runtime(tmp_path, workflow, '2025.1', fault=fault)
    with pytest.raises((AssertionError, KeyError)):
        workflow._collect_existing_effect_slot_exact_member_acceptance(runtime, sound_name='WAAPI_SLOT_TEST')
    category = runtime.category_results[-1]
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert category['status'] == 'FAIL' and receipt['business_effect_verified'] is False
    assert receipt['inline_list_merge_verified'] is False and receipt['failure']
    assert len(writes) == (3 if fault == 'prestate-owner' else 5 if fault == 'rename-path' else 4)
    # A rejected prestate never confirms/executes the requested effect. A refused
    # native write is never followed by verify or a retry of that write.
    expected_verifies = 3 if fault in ('prestate-owner', 'native-error') else 5 if fault == 'rename-path' else 4
    assert [cmd[0] for cmd in commands].count('verify') == expected_verifies
    assert not any(phase['effect_verified'] for phase in receipt['transactions'][3:] if fault != 'rename-path')
    assert len(receipt['calls']) <= 192 and Path(category['observation_path']).stat().st_size <= 8 * 1024 * 1024


@pytest.mark.parametrize('fault', ['effect-owner', 'effect-parent', 'slot-parent-null'])
def test_existing_effect_slot_collector_preserves_native_immediate_owner_and_unavailable_parent(tmp_path, workflow, fault):
    runtime, commands, writes, _task = _effect_slot_merge_runtime(tmp_path, workflow, '2025.1', fault=fault)
    with pytest.raises(AssertionError):
        workflow._collect_existing_effect_slot_exact_member_acceptance(runtime, sound_name='WAAPI_SLOT_TEST')
    receipt = json.loads(Path(runtime.category_results[-1]['observation_path']).read_text())
    assert runtime.category_results[-1]['status'] == 'FAIL'
    assert receipt['business_effect_verified'] is False and receipt['failure']['type'] == 'AssertionError'
    assert len(writes) == 4 and [command[0] for command in commands].count('verify') == 4
    assert receipt['transactions'][-1]['effect_verified'] is False
    for slot, effect in zip(receipt['baseline']['slots'], receipt['baseline']['effects'], strict=True):
        assert effect['owner']['id'] == slot['id']
        assert 'parent' not in slot and 'parent' not in effect
        assert 'parent' in slot['unavailable_fields'] and 'parent' in effect['unavailable_fields']


@pytest.mark.parametrize('version', ['2021.1', '2022.1'])
def test_existing_effect_slot_collector_keeps_legacy_scalar_boundary(tmp_path, workflow, version):
    runtime, commands, writes, _task = _effect_slot_merge_runtime(tmp_path, workflow, version)
    with pytest.raises(AssertionError, match='legacy scalar'):
        workflow._collect_existing_effect_slot_exact_member_acceptance(runtime, sound_name='WAAPI_SLOT_TEST')
    assert commands == [] and writes == []
    assert runtime.category_results[-1]['status'] == 'FAIL'


def _existing_bus_send_runtime(tmp_path, workflow, version, *, fault=None, root_sources=False):
    """Actual Gateway parsing/dispatch; fake native state honors each exact request."""
    from copy import deepcopy
    import uuid
    from tests.unit.test_existing_bus_override_applicability_gateway import existing_task
    from tests.unit.test_object_graph_owned_choices_gateway import CHILD

    task, _mutations = existing_task(tmp_path, version=version,
        operation='object.create' if version == '2021.1' else 'object.set')
    parent = deepcopy(task.objects[CHILD])
    parent['path'] = ('\\Busses' if version == '2025.1' else '\\Master-Mixer Hierarchy') + '\\Default Work Unit'
    parent['parent'] = None
    task.objects = {CHILD: parent}
    original = task.call
    writes, commands = [], []
    independent_read = False
    ids = {name: '{' + str(uuid.UUID(int=index)).upper() + '}' for index, name in enumerate(
        ('WAAPI_EXISTING_SEND_TEST', 'Destination', 'Sender', 'BatchSender'), 11)}

    setup_count = 3 if root_sources else 1
    source_names = {name: 'WAAPI_EXISTING_SEND_TEST_' + name if root_sources else name
        for name in ('Sender', 'BatchSender')}
    for name, actual_name in source_names.items():
        ids[actual_name] = ids[name]

    def call(uri, args=None, options=None):
        if uri.endswith(('object.create', 'object.set', 'setReference', 'setProperty')):
            writes.append((uri, deepcopy(args)))
            if len(writes) > setup_count and fault == 'native-error':
                raise RuntimeError('Existing-source write refused; never retry')
        if uri.endswith('object.create'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            if len(writes) == setup_count + 3:
                assert version == '2021.1', args
                assert args == {'parent': CHILD if root_sources else ids['WAAPI_EXISTING_SEND_TEST'],
                    'type': 'Bus' if root_sources else 'AuxBus', 'name': source_names['BatchSender'],
                    '@UserAuxSend0': ids['Destination'], '@UserAuxSendVolume0': -12,
                    'onNameConflict': 'merge', 'autoAddToSourceControl': False}, args
                task.objects[ids['BatchSender']].update({'@UserAuxSend0': {'id': args['@UserAuxSend0']},
                    '@UserAuxSendVolume0': args['@UserAuxSendVolume0']})
                return {'id': ids['Sender'] if fault == 'merge-wrong-guid' else ids['BatchSender'],
                    'name': source_names['BatchSender']}
            if root_sources and len(writes) in {2, 3}:
                name = source_names['Sender' if len(writes) == 2 else 'BatchSender']
                assert args == {'parent': CHILD, 'type': 'Bus', 'name': name, 'notes': 'Keep ' + name,
                    'onNameConflict': 'fail', 'autoAddToSourceControl': False}, args
            else:
                assert args == {'parent': CHILD, 'type': 'Bus', 'name': 'WAAPI_EXISTING_SEND_TEST',
                    'notes': 'Keep routing', 'children': [
                        {'type': 'AuxBus', 'name': name, 'notes': 'Keep ' + name}
                        for name in (('Destination',) if root_sources else ('Destination', 'Sender', 'BatchSender'))],
                    'onNameConflict': 'fail', 'autoAddToSourceControl': False}, args
            def create(node, owner):
                identity = ids[node['name']]
                task.objects[identity] = {'id': identity, 'name': node['name'], 'type': node['type'],
                    'classId': 1376272 if node['type'] == 'Bus' else 3997712,
                    'path': task.objects[owner]['path'] + '\\' + node['name'], 'parent': {'id': owner},
                    'notes': node['notes'], '@UserAuxSend0': None, '@UserAuxSendVolume0': 0}
                return {'id': identity, 'name': node['name'],
                    'children': [create(child, identity) for child in node.get('children', [])]}
            result = create(args, CHILD)
            if root_sources and len(writes) == 3 and fault == 'class':
                task.objects[ids['Sender']].update(type='AuxBus', classId=3997712)
            return result
        if uri.endswith('object.get') and args.get('waql', '').startswith('from object "'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            identity = args['waql'].split('"')[1]
            rows = [row for row in task.objects.values() if identity in {row['id'], row['path']}]
            projected = [{key: deepcopy(row.get(key, row.get('@' + key))) for key in options['return']
                if key in row or '@' + key in row} for row in rows]
            if independent_read and len(writes) > setup_count and fault == 'independent-guid':
                for row in projected:
                    if row.get('id') == ids['Sender'] and 'UserAuxSend0' in row:
                        row['UserAuxSend0'] = {'id': ids['WAAPI_EXISTING_SEND_TEST']}
            if independent_read and len(writes) == setup_count + 2 and fault == 'independent-value':
                for row in projected:
                    if row.get('id') == ids['Sender'] and '@UserAuxSendVolume0' in row:
                        row['@UserAuxSendVolume0'] = -4
            return {'return': projected}
        result = original(uri, args, options)
        if len(writes) > setup_count and uri.endswith(('object.set', 'setReference', 'setProperty')):
            source = task.objects[args['objects'][0]['object'] if 'objects' in args else args['object']]
            if fault == 'wrong-guid': source['@UserAuxSend0'] = {'id': ids['WAAPI_EXISTING_SEND_TEST']}
            if fault == 'wrong-value': source['@UserAuxSendVolume0'] = -1
            if fault == 'notes': source['notes'] = 'Not requested'
            if fault == 'parent': source['parent'] = {'id': ids['WAAPI_EXISTING_SEND_TEST'] if root_sources else CHILD}
            if fault == 'batch-wrong-guid' and len(writes) == setup_count + 3:
                source['@UserAuxSend0'] = {'id': ids['Sender']}
            if fault == 'scalar-effect' and len(writes) == setup_count + 2:
                source['@UserAuxSendVolume0'] = -4
        return result

    task.call = call
    runtime = SimpleNamespace(version=version, state_dir=tmp_path / 'state', env=task.env,
        candidate='fixture-candidate', category_results=[])
    def raw(command):
        nonlocal independent_read
        commands.append(list(command))
        independent_read = command[0] == 'query-object'
        if fault == 'merge-target-drift' and command[:2] == ['draft-start', 'object.create'] and len(writes) == setup_count + 2:
            original_source = task.objects[ids['BatchSender']]
            replacement = deepcopy(original_source)
            replacement['id'] = '{99999999-9999-9999-9999-999999999999}'
            original_source['name'] = 'MovedBatchSender'
            original_source['path'] += 'Moved'
            task.objects[replacement['id']] = replacement
        if fault == 'merge-state-drift' and command[:2] == ['draft-start', 'object.create'] and len(writes) == setup_count + 2:
            task.objects[ids['BatchSender']]['@UserAuxSend0'] = {'id': ids['Destination']}
        return workflow.waapi_gateway.execute_gateway(['--state-dir', str(runtime.state_dir), *command],
            env=runtime.env, client_factory=lambda _url: task)
    runtime.raw_gateway = raw
    return runtime, commands, writes, task


def test_existing_and_old_root_send_witnesses_retain_distinct_shared_state_receipts(tmp_path, workflow):
    shared = tmp_path / 'shared-state'
    (tmp_path / 'ordinary').mkdir()
    (tmp_path / 'old-root').mkdir()
    ordinary, _commands, _writes, _task = _existing_bus_send_runtime(tmp_path / 'ordinary', workflow, '2021.1')
    old_root, _commands, _writes, _task = _existing_bus_send_runtime(tmp_path / 'old-root', workflow, '2021.1', root_sources=True)
    ordinary.state_dir = old_root.state_dir = shared
    first = workflow._collect_existing_bus_send_acceptance(ordinary, root_name='WAAPI_EXISTING_SEND_TEST')
    first_path = Path(first['observation_path'])
    first_bytes = first_path.read_bytes()
    second = workflow._collect_existing_bus_send_acceptance(old_root,
        root_name='WAAPI_EXISTING_SEND_TEST', root_sources=True)
    second_path = Path(second['observation_path'])
    assert first['status'] == second['status'] == 'PASS'
    assert first['category'] == 'existing-bus-user-send'
    assert second['category'] == 'old-root-bus-user-send'
    assert first_path == shared / 'existing-bus-send-acceptance.json'
    assert second_path == shared / 'old-root-bus-send-acceptance.json'
    assert first_path != second_path
    assert first_path.read_bytes() == first_bytes
    for path, placement, count in [(first_path, 'aux_bus_children', 4), (second_path, 'old_root_bus_sources', 6)]:
        receipt = json.loads(path.read_text())
        assert receipt['placement'] == placement
        assert receipt['business_effect_verified'] is True
        assert len(receipt['transactions']) == count


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1'])
def test_old_root_bus_send_acceptance_uses_distinct_root_sources(tmp_path, workflow, version):
    runtime, commands, writes, task = _existing_bus_send_runtime(tmp_path, workflow, version, root_sources=True)
    category = workflow._collect_existing_bus_send_acceptance(runtime,
        root_name='WAAPI_EXISTING_SEND_TEST', root_sources=True)
    receipt = json.loads((runtime.state_dir / 'old-root-bus-send-acceptance.json').read_text())
    assert category['status'] == 'PASS'
    assert receipt['setup_coverage_credit'] is False
    assert receipt['business_effect_verified'] is True
    baseline, parent = receipt['baseline'], receipt['placement_parent']
    assert parent['type'] == 'WorkUnit' and parent['class_id'] == 1638416
    assert len({row['id'] for row in baseline.values()}) == 4
    for role in ('root', 'source', 'batch_source'):
        assert baseline[role]['type'] == 'Bus' and baseline[role]['class_id'] == 1376272
        assert baseline[role]['parent']['id'] == parent['id']
        assert baseline[role]['path'] == parent['path'] + '\\' + baseline[role]['name']
    assert baseline['target']['type'] == 'AuxBus' and baseline['target']['class_id'] == 3997712
    assert baseline['target']['parent']['id'] == baseline['root']['id']
    assert [uri.rsplit('.', 1)[1] for uri, _ in writes] == ['create'] * 3 + ['setReference', 'setProperty', 'create' if version == '2021.1' else 'set']
    assert [cmd[0] for cmd in commands].count('execute') == 6
    assert [cmd[0] for cmd in commands].count('verify') == 6
    assert 'OverrideUserAuxSends' not in json.dumps(writes)
    assert [phase['phase'] for phase in receipt['transactions'][:3]] == [
        'setup_no_coverage_credit', 'setup_source_no_coverage_credit', 'setup_batch_source_no_coverage_credit']
    for phase in receipt['transactions'][3:]:
        assert phase['effect_verified'] is True
        assert phase['independent_placement_parent'] == parent
        for role in ('source', 'batch_source'):
            assert phase['independent_effect'][role]['parent']['id'] == parent['id']
    if version == '2021.1':
        assert receipt['transactions'][-1]['expected_existing_merge'] == baseline['batch_source']
        assert writes[-1][1]['parent'] == parent['id']
        assert writes[-1][1]['type'] == 'Bus'
    else:
        assert writes[-1][1]['objects'][0]['object'] == baseline['batch_source']['id']
    assert len(receipt['calls']) <= 192
    assert (runtime.state_dir / 'old-root-bus-send-acceptance.json').stat().st_size <= 8 * 1024 * 1024


@pytest.mark.parametrize(('version', 'fault', 'write_count'), [
    ('2021.1', 'class', 3),
    ('2022.1', 'parent', 4),
    ('2023.1', 'independent-guid', 4),
    ('2021.1', 'merge-target-drift', 5),
    ('2021.1', 'merge-wrong-guid', 6),
    ('2023.1', 'native-error', 4),
])
def test_old_root_bus_send_acceptance_rejects_wrong_authority_or_effect(tmp_path, workflow, version, fault, write_count):
    runtime, commands, writes, _task = _existing_bus_send_runtime(tmp_path, workflow, version,
        root_sources=True, fault=fault)
    with pytest.raises(AssertionError):
        workflow._collect_existing_bus_send_acceptance(runtime,
            root_name='WAAPI_EXISTING_SEND_TEST', root_sources=True)
    receipt = json.loads((runtime.state_dir / 'old-root-bus-send-acceptance.json').read_text())
    assert runtime.category_results[-1]['status'] == 'FAIL'
    assert receipt['business_effect_verified'] is False
    assert len(writes) == write_count
    assert [cmd[0] for cmd in commands].count('execute') == write_count
    if fault == 'merge-target-drift':
        assert receipt['transactions'][-1]['native_outcome'] == 'not_executed'
        assert [cmd[0] for cmd in commands].count('confirm') == 5
    if fault == 'native-error':
        assert [cmd[0] for cmd in commands].count('verify') == 3
        assert receipt['transactions'][-1]['native_outcome'] == 'indeterminate'


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
def test_old_root_bus_witness_keeps_new_version_boundary_before_calls(tmp_path, workflow, version):
    runtime, commands, writes, _task = _existing_bus_send_runtime(tmp_path, workflow, version, root_sources=True)
    with pytest.raises(AssertionError, match='2024–2025 retain'):
        workflow._collect_existing_bus_send_acceptance(runtime,
            root_name='WAAPI_EXISTING_SEND_TEST', root_sources=True)
    receipt = json.loads((runtime.state_dir / 'old-root-bus-send-acceptance.json').read_text())
    assert receipt['calls'] == [] and commands == [] and writes == []
    assert receipt['business_effect_verified'] is False
    assert runtime.category_results[-1]['status'] == 'FAIL'


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1'])
def test_existing_bus_send_acceptance_uses_three_exact_public_mutations(tmp_path, workflow, version):
    runtime, commands, writes, task = _existing_bus_send_runtime(tmp_path, workflow, version)
    category = workflow._collect_existing_bus_send_acceptance(runtime, root_name='WAAPI_EXISTING_SEND_TEST')
    assert category['status'] == 'PASS', category
    assert [uri.rsplit('.', 1)[1] for uri, _ in writes] == ['create', 'setReference', 'setProperty', 'create' if version == '2021.1' else 'set']
    assert [cmd[0] for cmd in commands].count('execute') == 4
    assert [cmd[0] for cmd in commands].count('verify') == 4
    assert 'OverrideUserAuxSends' not in json.dumps(writes)
    assert writes[1][1]['value'] == next(row['id'] for row in task.objects.values() if row['name'] == 'Destination')
    assert writes[2][1]['value'] == -9
    assert (writes[3][1] if version == '2021.1' else writes[3][1]['objects'][0])['@UserAuxSendVolume0'] == -12


@pytest.mark.parametrize('fault', ['wrong-guid', 'wrong-value', 'notes', 'parent', 'independent-guid', 'batch-wrong-guid', 'native-error', 'scalar-effect', 'independent-value'])
def test_existing_bus_send_acceptance_rejects_wrong_effect_and_never_retries(tmp_path, workflow, fault):
    runtime, commands, writes, _task = _existing_bus_send_runtime(tmp_path, workflow, '2025.1', fault=fault)
    with pytest.raises(AssertionError):
        workflow._collect_existing_bus_send_acceptance(runtime, root_name='WAAPI_EXISTING_SEND_TEST')
    receipt = json.loads((runtime.state_dir / 'existing-bus-send-acceptance.json').read_text())
    assert runtime.category_results[-1]['status'] == 'FAIL'
    assert receipt['business_effect_verified'] is False
    assert len(writes) == (4 if fault == 'batch-wrong-guid' else 3 if fault in {'scalar-effect', 'independent-value'} else 2)
    assert [cmd[0] for cmd in commands].count('execute') == len(writes)
    if fault == 'native-error':
        assert [cmd[0] for cmd in commands].count('verify') == 1
        assert receipt['transactions'][-1]['native_outcome'] == 'indeterminate'


def test_existing_bus_send_2021_uses_one_guarded_merge_for_third_effect(tmp_path, workflow):
    runtime, commands, writes, _task = _existing_bus_send_runtime(tmp_path, workflow, '2021.1')
    category = workflow._collect_existing_bus_send_acceptance(runtime, root_name='WAAPI_EXISTING_SEND_TEST')
    receipt = json.loads((runtime.state_dir / 'existing-bus-send-acceptance.json').read_text())
    assert category['status'] == 'PASS'
    assert receipt['business_effect_verified'] is True
    assert [phase['effect_verified'] for phase in receipt['transactions']] == [True] * 4
    assert receipt['completed_mutation_phases'] == ['standalone_reference', 'standalone_scalar', 'samebatch_reference_scalar']
    assert receipt['transactions'][-1]['expected_existing_merge'] == receipt['baseline']['batch_source']
    assert [uri.rsplit('.', 1)[1] for uri, _ in writes] == ['create', 'setReference', 'setProperty', 'create']
    assert writes[-1][1]['onNameConflict'] == 'merge'
    assert [cmd[0] for cmd in commands].count('execute') == 4


@pytest.mark.parametrize('fault', ['merge-target-drift', 'merge-state-drift', 'merge-wrong-guid'])
def test_existing_bus_send_2021_never_mutates_replacement_or_accepts_wrong_returned_guid(tmp_path, workflow, fault):
    runtime, commands, writes, _task = _existing_bus_send_runtime(tmp_path, workflow, '2021.1', fault=fault)
    with pytest.raises(AssertionError):
        workflow._collect_existing_bus_send_acceptance(runtime, root_name='WAAPI_EXISTING_SEND_TEST')
    receipt = json.loads((runtime.state_dir / 'existing-bus-send-acceptance.json').read_text())
    assert runtime.category_results[-1]['status'] == 'FAIL'
    assert receipt['business_effect_verified'] is False
    assert len(writes) == (4 if fault == 'merge-wrong-guid' else 3)
    assert [cmd[0] for cmd in commands].count('execute') == len(writes)
    if fault != 'merge-wrong-guid':
        assert receipt['transactions'][-1]['native_outcome'] == 'not_executed'
        assert [cmd[0] for cmd in commands].count('confirm') == 3


def _new_result_reference_runtime(tmp_path, workflow, version, *, fault=None, noisy_fields=False, native_conditions=False):
    """The real public Gateway above an exact, independently mutated native tree."""
    from copy import deepcopy
    import uuid
    from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask

    operation = "object.create" if version == "2021.1" else "object.set"
    task = OwnedGraphTask(tmp_path, version, operation)
    parent = "{ABABABAB-ABAB-ABAB-ABAB-ABABABABABAB}"
    root, target, source = ("{" + str(uuid.UUID(int=value)) + "}" for value in (3, 5, 6))
    task.types = [{"name": name, "classId": value, "type": "WObject"} for name, value in (
        ("WorkUnit", 1638416), ("Bus", 1376272), ("AuxBus", 3997712))]
    parent_path = (r"\Busses\Default Work Unit" if version == "2025.1"
                   else r"\Master-Mixer Hierarchy\Default Work Unit")
    task.objects = {parent: {"id": parent, "name": "Default Work Unit", "type": "WorkUnit", "classId": 1638416,
        "path": parent_path, "parent": None, "notes": "Keep parent"}}
    commands, writes = [], []
    independent_read = False
    original = task.call
    base = parent_path + r"\WAAPI_RESULT_REFERENCE_TEST"
    # Exact names from the owned 2025 receipt; target metadata below stays a unit fixture.
    task.reference_field_names = [
        'Attenuation', '3DPosition', '3DSpatialization', 'AttenuationDistanceScaling',
        'BusChannelConfig', 'BusVolume', 'BypassEffect', 'CenterPercentage',
        'Color', 'EnableAttenuation', 'EnableDiffraction', 'GameAuxSendHPF',
        'GameAuxSendDSF', 'GameAuxSendLPF', 'GameAuxSendVolume', 'Highpass',
        'HoldEmitterPositionOrientation', 'HoldListenerOrientation', 'ListenerRelativeRouting', 'Lowpass',
        'OutputBusHighpass', 'OutputBusDualshelf', 'OutputBusLowpass', 'OutputBusVolume',
        'OverrideColor', 'Pitch', 'ReflectionsVolume', 'SpeakerPanning',
        'SpeakerPanning3DSpatializationMix', 'UseGameAuxSends', 'UserAuxSendHPF0', 'UserAuxSendHPF1',
        'UserAuxSendHPF2', 'UserAuxSendHPF3', 'UserAuxSendLPF0', 'UserAuxSendLPF1',
        'UserAuxSendLPF2', 'UserAuxSendLPF3', 'UserAuxSendVolume0', 'UserAuxSendVolume1',
        'UserAuxSendVolume2', 'UserAuxSendVolume3', 'Volume', 'ReflectionsAuxSend',
        'UserAuxSend0', 'UserAuxSend1', 'UserAuxSend2', 'UserAuxSend3',
    ] if noisy_fields else ["UserAuxSend0"]

    def call(uri, args=None, options=None):
        if uri.endswith(("getPropertyAndReferenceNames", "getPropertyInfo")):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args.get("classId") == 3997712 or args.get("object") == source, args
            if uri.endswith("getPropertyAndReferenceNames"):
                return {"return": task.reference_field_names}
            if args["property"].startswith(("UserAuxSendHPF", "UserAuxSendLPF")):
                name = args["property"]
                band, index = ("HPF" if "HPF" in name else "LPF"), name[-1]
                return {"name": name, "type": "int16", "default": 0,
                    "display": {"name": "User-Defined Auxiliary " + band + " " + index},
                    "restriction": {"type": "range", "min": 0, "max": 100},
                    "dependencies": [{"action": "Show", "context": "Self", "type": "isMasterBus", "value": False},
                        {"action": "Enable", "context": "Self", "property": "OverrideUserAuxSends", "type": "override"}]}
            if native_conditions and args["property"] == "OverrideUserAuxSends":
                raise RuntimeError("Literal native 553: controller property does not exist on AuxBus")
            assert args["property"] == "UserAuxSend0", args
            if native_conditions:
                # Literal relevant 2025 native shape; older program lanes use their XML group grammar, not claimed native observations.
                return {"name": "UserAuxSend0", "type": "", "default": None,
                    "supports": {"unlink": False, "randomizer": False, "rtpc": "None"},
                    "display": {"name": "User-Defined Auxiliary Send 0"},
                    "restriction": {"type": "reference", "restrictions": [{"type": ["Auxiliary Bus"], "sharedOnlyTypes": []}]},
                    "dependencies": ([{"type": "isMasterBus", "value": False, "action": "Show", "context": "Self"}]
                        if version in {"2024.1", "2025.1"} else []) + [
                        {"type": "override", "action": "Enable", "context": "Self", "property": "OverrideUserAuxSends"}]}
            return {"name": "UserAuxSend0", "type": "Reference", "display": {"name": "User-Defined Auxiliary Send 0"},
                "restriction": {"type": "reference", "restrictions": [{"type": ["AuxBus"]}]}}
        if uri in {"ak.wwise.core.object.create", "ak.wwise.core.object.set"}:
            writes.append((uri, deepcopy(args), deepcopy(options)))
            children = [{"type": "AuxBus", "name": "Destination"},
                {"type": "AuxBus", "name": "Sender", "@UserAuxSend0": base + r"\Destination"}]
            if operation == "object.create":
                assert args == {"parent": parent, "type": "Bus", "name": "WAAPI_RESULT_REFERENCE_TEST",
                    "children": children, "onNameConflict": "fail", "autoAddToSourceControl": False}
            else:
                assert args == {"objects": [{"object": parent, "children": [{"type": "Bus",
                    "name": "WAAPI_RESULT_REFERENCE_TEST", "children": children}]}], "onNameConflict": "fail",
                    "autoAddToSourceControl": False, "listMode": "append"}
            if fault == "native-error":
                raise RuntimeError("Frozen native graph rejection; never replay")
            task.objects[root] = {"id": root, "name": "WAAPI_RESULT_REFERENCE_TEST", "type": "Bus", "classId": 1376272,
                "path": base, "parent": {"id": parent}, "notes": ""}
            for identity, name in ((target, "Destination"), (source, "Sender")):
                task.objects[identity] = {"id": identity, "name": name, "type": "AuxBus", "classId": 3997712,
                    "path": base + "\\" + name, "parent": {"id": root}, "notes": ""}
            task.objects[source]["@UserAuxSend0"] = {"id": root if fault == "wrong-guid" else target}
            if native_conditions:
                if fault == "wrong-parent-effect":
                    task.objects[source]["parent"] = {"id": parent}
            result = {"id": root, "name": "WAAPI_RESULT_REFERENCE_TEST", "children": [
                {"id": target, "name": "Destination"}, {"id": source, "name": "Sender"}]}
            return result if operation == "object.create" else {"objects": [{"id": parent, "name": "Default Work Unit", "children": [result]}]}
        if uri.endswith("object.get") and args.get("waql", "").startswith('from object "') and not args["waql"].endswith(" take 1"):
            expression = args["waql"]
            identity = expression.split('"')[1]
            assert expression == f'from object "{identity}"', expression
            result = {"return": [deepcopy(row) for row in task.objects.values() if identity in {row["id"], row["path"]}]}
        else:
            result = original(uri, args, options)
        if uri.endswith("object.get") and args.get("waql") != "from type Project take 1":
            # Honor the literal native return projection, including reference spelling.
            rows = []
            for row in result["return"]:
                projected = {key: deepcopy(row.get(key, row.get("@" + key))) for key in options["return"]
                    if key in row or "@" + key in row}
                if independent_read and fault == "independent-path" and row["id"] == target:
                    projected["path"] = base + r"\NotRequested"
                if independent_read and fault == "independent-guid" and row["id"] == source and "UserAuxSend0" in projected:
                    projected["UserAuxSend0"] = {"id": root}
                if independent_read and fault == "independent-class" and row["id"] == target and "classId" in projected:
                    projected["classId"] = True
                if independent_read and fault == "independent-parent" and row["id"] == target and "parent" in projected:
                    projected["parent"] = {"id": parent}
                rows.append(projected)
            return {"return": rows}
        return result

    task.call = call
    runtime = SimpleNamespace(version=version, state_dir=tmp_path / "state", env=task.env,
        candidate="fixture-candidate", category_results=[])
    def raw(command):
        nonlocal independent_read
        commands.append(list(command))
        independent_read = command[0] == "query-object"
        return workflow.waapi_gateway.execute_gateway(["--state-dir", str(runtime.state_dir), *command],
            env=runtime.env, client_factory=lambda _url: task)
    runtime.raw_gateway = raw
    return runtime, commands, writes, task


def test_new_result_reference_exact_selection_and_native_condition_share_one_write(tmp_path, workflow):
    runtime, commands, writes, task = _new_result_reference_runtime(
        tmp_path, workflow, "2025.1", noisy_fields=True, native_conditions=True)
    category = workflow._collect_new_result_scalar_reference_acceptance(runtime, root_name="WAAPI_RESULT_REFERENCE_TEST")
    assert category["status"] == "PASS", category
    assert len(writes) == 1 and [command[0] for command in commands].count("execute") == 1
    assert {args["property"] for uri, args, _ in task.calls if uri.endswith("getPropertyInfo")} == {
        "UserAuxSend0"}
    sender = writes[0][1]["objects"][0]["children"][0]["children"][1]
    assert "@OverrideUserAuxSends" not in sender
    assert sender["@UserAuxSend0"].endswith(r"\Destination")


def test_new_result_reference_acceptance_selects_exact_listed_reference_amid_native_neighbours(tmp_path, workflow):
    runtime, commands, writes, task = _new_result_reference_runtime(tmp_path, workflow, "2025.1", noisy_fields=True)
    category = workflow._collect_new_result_scalar_reference_acceptance(runtime, root_name="WAAPI_RESULT_REFERENCE_TEST")
    assert category["status"] == "PASS", category
    assert len(writes) == 1
    discovery = [command for command in commands if command[0] == "draft-discover-fields"]
    assert "--list" in discovery[0] and "--selection" in discovery[1], discovery
    assert not any("--meaning" in command for command in discovery)
    assert {args["property"] for uri, args, _ in task.calls if uri.endswith("getPropertyInfo")} == {"UserAuxSend0"}
    exact_read = next(command for command in commands if command[0] == "query-object" and "--include-field" in command)
    assert exact_read[exact_read.index("--include-field") + 1] == "UserAuxSend0"


def test_new_result_reference_acceptance_copies_opaque_field_list_page(tmp_path, workflow):
    runtime, commands, writes, task = _new_result_reference_runtime(tmp_path, workflow, "2025.1", noisy_fields=True)
    # Synthetic preceding names force a second real Gateway page; their metadata is never requested.
    task.reference_field_names = [f"AA_Field{index:02}" for index in range(70)] + task.reference_field_names
    raw = runtime.raw_gateway
    pages = []

    def capture(command):
        code, payload = raw(command)
        if command[0] == "draft-discover-fields" and "--list" in command:
            pages.append(payload["agent_result"])
        return code, payload

    runtime.raw_gateway = capture
    category = workflow._collect_new_result_scalar_reference_acceptance(runtime, root_name="WAAPI_RESULT_REFERENCE_TEST")
    assert category["status"] == "PASS" and len(writes) == 1, category
    listed_commands = [command for command in commands if command[0] == "draft-discover-fields" and "--list" in command]
    assert len(listed_commands) == len(pages) == 2
    assert pages[0]["complete"] is False and pages[1]["complete"] is True
    assert listed_commands[1][listed_commands[1].index("--page") + 1] == pages[0]["next_page"]
    assert {args["property"] for uri, args, _ in task.calls if uri.endswith("getPropertyInfo")} == {"UserAuxSend0"}


@pytest.mark.parametrize("fault", ("missing-target", "selection-drift"))
def test_new_result_reference_acceptance_rejects_unavailable_exact_selection_without_write(tmp_path, workflow, fault):
    runtime, commands, writes, task = _new_result_reference_runtime(tmp_path, workflow, "2025.1", noisy_fields=True)
    raw = runtime.raw_gateway
    if fault == "missing-target":
        task.reference_field_names.remove("UserAuxSend0")

    def drift(command):
        if command[0] == "draft-discover-fields" and "--selection" in command:
            task.reference_field_names.remove("UserAuxSend0")
        return raw(command)

    runtime.raw_gateway = drift
    with pytest.raises(AssertionError):
        workflow._collect_new_result_scalar_reference_acceptance(runtime, root_name="WAAPI_RESULT_REFERENCE_TEST")
    category, = runtime.category_results
    receipt = json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "FAIL" and receipt["native_outcome"] == "not_executed", receipt
    assert receipt["business_effect_verified"] is False
    assert not writes and not any(command[0] == "execute" for command in commands)
    assert not any(uri.endswith("getPropertyInfo") for uri, _args, _options in task.calls)
    if fault == "selection-drift":
        assert receipt["calls"][-1]["exit_code"] != 0
        assert receipt["calls"][-1]["payload"]["error_code"] == "METADATA_SELECTION_SCOPE_CHANGED"


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_new_result_reference_acceptance_handles_native_non_master_bus_condition_in_same_write(tmp_path, workflow, version):
    runtime, commands, writes, _task = _new_result_reference_runtime(tmp_path, workflow, version, native_conditions=True)
    category = workflow._collect_new_result_scalar_reference_acceptance(runtime, root_name="WAAPI_RESULT_REFERENCE_TEST")
    assert category["status"] == "PASS", category
    assert len(writes) == 1 and [command[0] for command in commands].count("execute") == 1
    tree = writes[0][1] if version == "2021.1" else writes[0][1]["objects"][0]["children"][0]
    sender = tree["children"][1]
    assert "@OverrideUserAuxSends" not in sender
    assert sender["@UserAuxSend0"].endswith(r"\Destination")


@pytest.mark.parametrize("fault", ("controller-appears-after-write", "wrong-guid", "wrong-source-class", "wrong-parent-class", "wrong-parent-effect"))
def test_new_result_native_condition_needs_controller_class_parent_and_reference_effect(tmp_path, workflow, fault):
    runtime, commands, writes, task = _new_result_reference_runtime(tmp_path, workflow, "2025.1", native_conditions=True, fault=fault)
    original = task.call
    def effect(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith("getPropertyAndReferenceNames") and fault == "controller-appears-after-write" and writes:
            result["return"].append("OverrideUserAuxSends")
        if uri.endswith("object.set"):
            rows = {row["name"]: row for row in task.objects.values()}
            if fault == "wrong-source-class":
                rows["Sender"]["classId"] = True
            if fault == "wrong-parent-class":
                rows["WAAPI_RESULT_REFERENCE_TEST"]["classId"] = 65552
        return result
    task.call = effect
    with pytest.raises(AssertionError):
        workflow._collect_new_result_scalar_reference_acceptance(runtime, root_name="WAAPI_RESULT_REFERENCE_TEST")
    assert len(writes) == 1 and [command[0] for command in commands].count("execute") == 1
    receipt = json.loads(Path(runtime.category_results[0]["observation_path"]).read_text())
    assert receipt["gateway_verification"]["payload"].get("verified") is not True, receipt


@pytest.mark.parametrize("fault", ("value-true", "value-number", "action-enable", "context-parent", "extra-key", "controller-present"))
def test_new_result_native_condition_rejects_unproved_or_malformed_grammar_without_write(tmp_path, workflow, fault):
    runtime, commands, writes, task = _new_result_reference_runtime(tmp_path, workflow, "2025.1", native_conditions=True)
    original = task.call
    def metadata(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith("getPropertyInfo") and args["property"] == "UserAuxSend0":
            dependency = result["dependencies"][0]
            if fault == "value-true": dependency["value"] = True
            if fault == "value-number": dependency["value"] = 0
            if fault == "action-enable": dependency["action"] = "Enable"
            if fault == "context-parent": dependency["context"] = "Parent"
            if fault == "extra-key": dependency["property"] = "OverrideUserAuxSends"
        if uri.endswith("getPropertyAndReferenceNames") and fault == "controller-present":
            result["return"].append("OverrideUserAuxSends")
        return result
    task.call = metadata
    with pytest.raises(AssertionError):
        workflow._collect_new_result_scalar_reference_acceptance(runtime, root_name="WAAPI_RESULT_REFERENCE_TEST")
    assert not writes and not any(command[0] == "execute" for command in commands)


@pytest.mark.parametrize("fault", ("condition-drift", "controller-appears", "type-drift", "type-ambiguous"))
def test_new_result_native_condition_revalidates_metadata_and_types_before_only_write(tmp_path, workflow, fault):
    runtime, commands, writes, task = _new_result_reference_runtime(tmp_path, workflow, "2025.1", native_conditions=True)
    raw, original = runtime.raw_gateway, task.call
    executing = False
    def metadata(uri, args=None, options=None):
        result = original(uri, args, options)
        if executing and uri.endswith("getPropertyInfo"):
            if args["property"] == "UserAuxSend0" and fault == "condition-drift": result["dependencies"][0]["value"] = True
        if executing and uri.endswith("getPropertyAndReferenceNames") and fault == "controller-appears":
            result["return"].append("OverrideUserAuxSends")
        return result
    def drift(command):
        nonlocal executing
        if command[0] == "execute":
            executing = True
            if fault == "type-drift":
                task.types[1]["classId"] = 65552
            if fault == "type-ambiguous":
                task.types.append({"name": "bus", "classId": 65552, "type": "WObject"})
        return raw(command)
    task.call, runtime.raw_gateway = metadata, drift
    category = workflow._collect_new_result_scalar_reference_acceptance(runtime, root_name="WAAPI_RESULT_REFERENCE_TEST")
    assert category["status"] == "FAIL" and not writes, category
    assert [command[0] for command in commands].count("execute") == 1


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_new_result_reference_acceptance_uses_real_gateway_and_one_graph_write(tmp_path, workflow, version):
    runtime, commands, writes, _task = _new_result_reference_runtime(tmp_path, workflow, version)
    workflow._collect_new_result_scalar_reference_acceptance(runtime, root_name="WAAPI_RESULT_REFERENCE_TEST")
    category, = runtime.category_results
    assert category["status"] == "PASS", category
    receipt = json.loads(Path(category["observation_path"]).read_text())
    assert receipt["native_outcome"] == "accepted" and receipt["reference_effect"] == "proven", receipt
    assert receipt["independent_source"]["references"]["UserAuxSend0"]["id"] == receipt["independent_target"]["id"]
    assert len(writes) == 1 and [command[0] for command in commands].count("execute") == 1
    assert writes[0][0] == "ak.wwise.core.object." + ("create" if version == "2021.1" else "set")
    declaration = next(command for command in commands if command[0] == "draft-declare-new" and "source" in command)
    assert declaration[declaration.index("--field-value") + 1].startswith("bfh1-")
    assert declaration[declaration.index("--field-value") + 2].startswith("bnh1-")
    assert any(command[:1] == ["query-object"] and "--include-field" in command for command in commands)
    assert not any(flag in command for command in commands for flag in ("--advanced-waql", "--args", "--request-file"))


@pytest.mark.parametrize("version,fault", (("2021.1", "wrong-guid"), ("2025.1", "wrong-guid"),
    ("2021.1", "independent-path"), ("2025.1", "independent-guid"),
    ("2025.1", "independent-class"), ("2025.1", "independent-parent")))
def test_new_result_reference_acceptance_rejects_wrong_effect_or_independent_drift(tmp_path, workflow, version, fault):
    runtime, commands, writes, _task = _new_result_reference_runtime(tmp_path, workflow, version, fault=fault)
    with pytest.raises(AssertionError):
        workflow._collect_new_result_scalar_reference_acceptance(runtime, root_name="WAAPI_RESULT_REFERENCE_TEST")
    category, = runtime.category_results
    assert category["status"] == "FAIL", category
    receipt = json.loads(Path(category["observation_path"]).read_text())
    assert receipt["native_outcome"] == "accepted" and receipt["reference_effect"] != "proven", receipt
    assert receipt["business_effect_verified"] is False
    assert len(writes) == 1 and [command[0] for command in commands].count("execute") == 1
    assert receipt["gateway_verification"]["payload"].get("verified") is (fault != "wrong-guid"), receipt
    if fault in {"wrong-guid", "independent-guid"}:
        assert receipt["independent_source"]["references"]["UserAuxSend0"]["id"] != receipt["independent_target"]["id"]


def test_new_result_reference_acceptance_retains_native_failure_without_retry(tmp_path, workflow):
    runtime, commands, writes, _task = _new_result_reference_runtime(tmp_path, workflow, "2025.1", fault="native-error")
    category = workflow._collect_new_result_scalar_reference_acceptance(runtime, root_name="WAAPI_RESULT_REFERENCE_TEST")
    receipt = json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "FAIL" and receipt["native_outcome"] in {"rejected", "indeterminate"}, receipt
    assert receipt["reference_effect"] == "not_observed" and receipt["business_effect_verified"] is False
    assert "Frozen native graph rejection" in json.dumps(receipt["native_response"])
    assert len(writes) == 1 and [command[0] for command in commands].count("execute") == 1
    assert not any(command[0] in {"verify", "query-object"} for command in commands[commands.index(next(command for command in commands if command[0] == "execute")) + 1:])


@pytest.mark.parametrize("state", ("execution_failed", "indeterminate"))
def test_inline_wav_probe_keeps_terminal_receipt_without_retry(tmp_path, workflow, state):
    calls = []
    native_error = {"ok": False, "state": state, "dispatch_result": {
        "ok": False, "waapi_error_uri": "ak.wwise.invalid_arguments",
        "waapi_error_details": {"message": "exact original native error"},
    }, "error": {
        "code": "NATIVE_REJECTION" if state == "execution_failed" else "TIMEOUT",
        "message": "original native diagnostic", "details": {"unmodified": [1, 2]},
    }}
    runtime = _inline_probe_runtime(tmp_path, workflow, calls, terminal=native_error)
    receipt = {"calls": [], "lifecycle_final_reference": {"transaction_id": None, "phase": "final"}}
    workflow._run_inline_wav_probe(runtime, "{11111111-1111-1111-1111-111111111111}", "InlineProbe", receipt)
    retained = json.loads((tmp_path / "inline-wav-probe.json").read_text())
    assert retained["calls"][-1]["payload"] == native_error
    assert retained["native_outcome"] == ("rejected" if state == "execution_failed" else "indeterminate")
    assert retained["media_effect"] == "not_observed"
    assert retained["gateway_terminal_state"] == state
    assert retained["native_response"] == native_error["dispatch_result"]
    assert retained["lifecycle_final_reference"] == {"transaction_id": "transaction", "phase": "final"}
    assert [command[0] for command in calls].count("execute") == 1
    assert not any(command[0] in {"verify", "query-object"} for command in calls[calls.index(["execute", "transaction"]) + 1:])
    media = next(command for command in calls if command[0] == "draft-add-media")
    assert media[media.index("--inline-wav") + 1] == (
        "InlineProbe.wav|UklGRigAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQQAAAAAAAAA"
    )
    assert retained["compiled_native_request"]["args"]["objects"][0]["children"][0]["import"]["files"][0]["audioFileBase64"] == media[media.index("--inline-wav") + 1]


def _inline_probe_runtime(tmp_path, workflow, calls, *, terminal=None, corrupt=False):
    parent = "{11111111-1111-1111-1111-111111111111}"
    sound = "{22222222-2222-2222-2222-222222222222}"
    source = "{33333333-3333-3333-3333-333333333333}"
    project = tmp_path / "sandbox"
    original = project / "Originals" / "SFX" / "InlineProbe.wav"
    original.parent.mkdir(parents=True)
    native = {"uri": "ak.wwise.core.object.set", "args": {"objects": [{"children": [{"import": {"files": [{
        "audioFileBase64": "InlineProbe.wav|UklGRigAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQQAAAAAAAAA",
    }]}}]}]}, "options": {}}
    revision = 0
    executed = False

    def raw(command):
        nonlocal revision, executed
        calls.append(list(command))
        kind = command[0]
        revision += 1
        payload = {"ok": True, "draft": {"draft_id": "draft", "revision": revision},
                   "task_authority": "authority"}
        if kind == "draft-bind-object":
            payload["bound_object"] = {"handle": "parent-handle"}
        elif kind == "preview-from-draft":
            payload.update(transaction_id="transaction", artifact_hash="a" * 64)
        elif kind == "transaction-show":
            payload.update(artifact={"prepared_operation": {"dispatch": native}},
                           confirmation={"token": "confirmation"})
        elif kind == "execute":
            executed = True
            original.write_bytes(bytes.fromhex(
                "524946462800000057415645666d7420100000000100010044ac00008858010002001000646174610400000000000000"
            ) if not corrupt else b"wrong media")
            return (1, terminal) if terminal else (0, {"ok": True, "state": "executed_unverified", "dispatch_result": {"ok": True, "result": {"objects": [{"id": sound}]}}})
        elif kind == "verify":
            payload = {"ok": True, "state": "verified", "verification": {"business_state_verified": True}}
        elif kind == "query-object":
            if "--relationship" in command:
                rows = [] if not executed else ([{"id": sound, "name": "InlineProbe", "type": "Sound", "path": r"\Containers\Default Work Unit\Probe\InlineProbe"}]
                        if command[command.index("--exact-id") + 1] == parent else
                        [{"id": source, "type": "AudioFileSource"}])
            elif command[command.index("--exact-id") + 1] == sound:
                rows = [{"id": sound, "name": "InlineProbe", "type": "Sound", "path": r"\Containers\Default Work Unit\Probe\InlineProbe", "active_source": {"id": source}}]
            else:
                rows = [{"id": source, "name": "InlineProbe", "type": "AudioFileSource", "path": r"\Containers\Default Work Unit\Probe\InlineProbe\InlineProbe", "parent": {"id": sound}, "original_file_path": str(original), "source_language": {"id": "{44444444-4444-4444-4444-444444444444}", "name": "SFX"}}]
            payload = {"ok": True, "count": len(rows), "objects": rows}
        return 0, payload

    return SimpleNamespace(raw_gateway=raw, state_dir=tmp_path / "state", version="2025.1",
                           sandbox=SimpleNamespace(sandbox_path=project))


@pytest.mark.parametrize("corrupt", (False, True), ids=("exact-original", "corrupt-original"))
def test_inline_wav_probe_requires_linked_exact_original_media(tmp_path, workflow, corrupt):
    calls = []
    runtime = _inline_probe_runtime(tmp_path, workflow, calls, corrupt=corrupt)
    receipt = {"calls": []}
    if corrupt:
        with pytest.raises(AssertionError):
            workflow._run_inline_wav_probe(runtime, "{11111111-1111-1111-1111-111111111111}", "InlineProbe", receipt)
    else:
        workflow._run_inline_wav_probe(runtime, "{11111111-1111-1111-1111-111111111111}", "InlineProbe", receipt)
    retained = json.loads((tmp_path / "inline-wav-probe.json").read_text())
    assert retained["native_outcome"] == "accepted"
    assert retained["media_effect"] == ("incomplete" if corrupt else "proven")
    assert [command[0] for command in calls].count("execute") == 1
    if not corrupt:
        assert retained["original_wav"]["sha256"] == "0588c6a627c6603830a9e5d87ab258d4977c02876b9bac8f9598fccef098c1cf"
        assert retained["original_wav"]["pcm"] == {"channels": 1, "sample_width_bytes": 2, "sample_rate_hz": 44100, "frame_count": 2}


@pytest.mark.parametrize("fault", ("wrong-source-parent", "converted-media", "read-error",
                                   "wrong-language", "malformed-language-id", "string-language"))
def test_inline_wav_probe_does_not_credit_unlinked_or_unreadable_media(tmp_path, workflow, fault):
    calls = []
    runtime = _inline_probe_runtime(tmp_path, workflow, calls)
    raw_gateway = runtime.raw_gateway

    def broken_read(command):
        code, payload = raw_gateway(command)
        if command[0] == "query-object" and "original-file-path" in command:
            if fault == "read-error":
                return 1, {"ok": False, "error_code": "READ_FAILED", "message": "retained read failure"}
            if fault == "wrong-source-parent":
                payload["objects"][0]["parent"]["id"] = "{99999999-9999-9999-9999-999999999999}"
            elif fault == "wrong-language":
                payload["objects"][0]["source_language"]["name"] = "English(US)"
            elif fault == "malformed-language-id":
                payload["objects"][0]["source_language"]["id"] = "not-a-guid"
            elif fault == "string-language":
                payload["objects"][0]["source_language"] = "SFX"
            else:
                payload["objects"][0]["original_file_path"] = str(tmp_path / "sandbox" / ".cache" / "InlineProbe.wav")
        return code, payload

    runtime.raw_gateway = broken_read
    receipt = {"calls": []}
    with pytest.raises((AssertionError, ValueError)):
        workflow._run_inline_wav_probe(runtime, "{11111111-1111-1111-1111-111111111111}", "InlineProbe", receipt)
    retained = json.loads((tmp_path / "inline-wav-probe.json").read_text())
    assert retained["native_outcome"] == "accepted" and retained["media_effect"] == "incomplete"
    assert retained["diagnostic_error"]
    assert [command[0] for command in calls].count("execute") == 1
    if fault == "read-error":
        assert retained["calls"][-1]["payload"]["message"] == "retained read failure"


def test_inline_wav_probe_preserves_failed_gateway_verdict_beside_proven_effect(tmp_path, workflow):
    calls = []
    runtime = _inline_probe_runtime(tmp_path, workflow, calls)
    raw_gateway = runtime.raw_gateway
    failure = {"ok": False, "state": "verification_failed", "verification": {"business_state_verified": False}}

    def failed_verifier(command):
        code, payload = raw_gateway(command)
        return (2, failure) if command[0] == "verify" else (code, payload)

    runtime.raw_gateway = failed_verifier
    receipt = {"calls": []}
    workflow._run_inline_wav_probe(runtime, "{11111111-1111-1111-1111-111111111111}", "InlineProbe", receipt)
    retained = json.loads((tmp_path / "inline-wav-probe.json").read_text())
    assert retained["media_effect"] == "proven"
    assert retained["gateway_verification"] == {
        "exit_code": 2, "ok": False, "state": "verification_failed", "business_state_verified": False,
    }
    assert next(row["payload"] for row in retained["calls"] if row["argv"][0] == "verify") == failure
    assert [command[0] for command in calls].count("execute") == 1


def _source(root: Path) -> Path:
    root.mkdir()
    (root / "SampleProject.wproj").write_bytes(b"project")
    (root / "Music.wwu").write_bytes(b"workunit")
    media = root / "Originals" / "music.wav"
    media.parent.mkdir()
    media.write_bytes(b"original media")
    return media


def test_full_source_hash_detects_media_tamper_with_identical_size_and_mtime(tmp_path, workflow):
    root = tmp_path / "source"
    media = _source(root)
    before = workflow._hash_mutation_bearing_project_files(root)
    metadata_before = workflow._source_tree_inventory(root)
    info = media.stat()
    media.write_bytes(b"modified media")
    os.utime(media, ns=(info.st_atime_ns, info.st_mtime_ns))
    assert media.stat().st_size == info.st_size
    assert workflow._source_tree_inventory(root) == metadata_before
    after = workflow._hash_mutation_bearing_project_files(root)
    assert before[1:] == after[1:]
    assert before[0] != after[0]


def test_full_source_hash_counts_all_files_and_matches_existing_full_digest(tmp_path, workflow):
    root = tmp_path / "source"
    _source(root)
    (root / "notes.txt").write_bytes(b"non-project content")
    expected = hash_project(root, preferred_strategy="full")
    observed = workflow._hash_mutation_bearing_project_files(root)
    assert observed == (expected.digest, 4, expected.bytes_hashed)
    assert workflow._hash_mutation_bearing_project_files(root) == observed


@pytest.mark.parametrize("target_is_directory", (False, True))
def test_full_source_hash_rejects_links_before_reading_content(tmp_path, workflow, monkeypatch, target_is_directory):
    root = tmp_path / "source"
    _source(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside if target_is_directory else outside / "media.wav"
    if not target_is_directory:
        target.write_bytes(b"outside")
    create_symlink_or_skip(root / "link", target, target_is_directory=target_is_directory)
    monkeypatch.setattr(os, "open", lambda *_args, **_kwargs: pytest.fail("link must stop before content reads"))
    with pytest.raises(workflow.SandboxFixtureError, match="link|reparse"):
        workflow._hash_mutation_bearing_project_files(root)


@pytest.mark.parametrize("bound", ("SOURCE_HASH_MAX_FILES", "SOURCE_HASH_MAX_BYTES"))
def test_full_source_hash_preflights_bounds_before_content_reads(tmp_path, workflow, monkeypatch, bound):
    root = tmp_path / "source"
    _source(root)
    monkeypatch.setattr(workflow, bound, 1, raising=False)
    monkeypatch.setattr(os, "open", lambda *_args, **_kwargs: pytest.fail("bounds must stop before content reads"))
    with pytest.raises(workflow.SandboxFixtureError, match="bound"):
        workflow._hash_mutation_bearing_project_files(root)


def test_full_source_hash_rejects_linked_root(tmp_path, workflow):
    source = tmp_path / "source"
    _source(source)
    linked = tmp_path / "linked"
    create_symlink_or_skip(linked, source, target_is_directory=True)
    with pytest.raises(workflow.SandboxFixtureError, match="link|reparse"):
        workflow._hash_mutation_bearing_project_files(linked)


def test_full_source_hash_rejects_windows_reparse_metadata(tmp_path, workflow, monkeypatch):
    source = tmp_path / "source"
    _source(source)
    lstat = Path.lstat

    def marked_root(path, *args, **kwargs):
        info = lstat(path, *args, **kwargs)
        return (SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
                if path == source else info)

    monkeypatch.setattr(Path, "lstat", marked_root)
    with pytest.raises(workflow.SandboxFixtureError, match="reparse"):
        workflow._hash_mutation_bearing_project_files(source)


def _fixture_run(tmp_path, workflow, monkeypatch, *, tamper_on_shutdown=False):
    source = tmp_path / "source"
    media = _source(source)
    events, records = [], []
    lock_root = tmp_path / "sandboxes"
    lock_root.mkdir()
    task_root = tmp_path / "task"
    task_root.mkdir()

    class Lock:
        def __init__(self, root):
            self.root = root

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            events.append("release")

    def prepare(_env, *, sandbox_root, hash_strategy):
        assert hash_strategy == "bounded"  # Copy audit is separate from the full guard.
        copied = sandbox_root / "copy"
        copied.mkdir(parents=True)
        project = copied / "SampleProject.wproj"
        project.write_bytes(b"project")
        return SimpleNamespace(
            source_root=source, source_project=source / "SampleProject.wproj",
            sandbox_path=copied, sandbox_root=sandbox_root, sandbox_project=project,
            env={}, metadata=SimpleNamespace(
                selected_port=7312, launch_project_path=str(project),
                get_info_display_name="WwiseConsole", get_info_version="2023.1",
                process_cleanup_result="cleaned", process_cleanup_details={"residual_processes": []},
            ),
        )

    def launch(*_args, **_kwargs):
        events.append("launch")
        return SimpleNamespace(host="127.0.0.1", port=7312)

    def shutdown(*_args):
        events.append("shutdown")
        if tamper_on_shutdown:
            info = media.stat()
            media.write_bytes(b"modified media")
            os.utime(media, ns=(info.st_atime_ns, info.st_mtime_ns))

    def append(**record):
        events.append("record:" + record["invocation"]["phase"])
        records.append(record)

    def quarantine(sandbox, **_kwargs):
        destination = tmp_path / "quarantine"
        sandbox.sandbox_path.rename(destination)
        return destination

    monkeypatch.setenv("WWISE_VERSION", "2023.1")
    monkeypatch.setattr(workflow, "_safe_lock_root", lambda _env: lock_root)
    monkeypatch.setattr(workflow, "LiveSandboxLock", Lock)
    monkeypatch.setattr(workflow, "exact_git_candidate", lambda _root: "a" * 40)
    monkeypatch.setattr(workflow, "prepare_sample_project_sandbox", prepare)
    monkeypatch.setattr(workflow, "launch_sandboxed_wwise", launch)
    monkeypatch.setattr(workflow, "shutdown_sandboxed_wwise", shutdown)
    monkeypatch.setattr(exact_real_evidence, "exact_transaction_outcomes", lambda _path: [])
    monkeypatch.setattr(exact_real_evidence, "cleanup_sandbox", quarantine)
    monkeypatch.setattr(exact_real_evidence, "append_category_evidence", append)
    item = SimpleNamespace(
        path=workflow.__file__, nodeid="tests/native.py::test_source",
        _waapi_phase_reports={"setup": "passed", "call": "passed"},
    )
    request = SimpleNamespace(module=workflow, session=SimpleNamespace(items=[item]))
    factory = SimpleNamespace(mktemp=lambda _name: task_root)
    return workflow.workflow_sandbox_runtime.__wrapped__(request, factory), events, records


def test_workflow_failure_captures_owned_process_before_cleanup_with_bounded_tails(tmp_path, workflow, monkeypatch):
    fixture, events, records = _fixture_run(tmp_path, workflow, monkeypatch)
    runtime = next(fixture)
    class OwnedProcess:
        pid = 123456
        def poll(self):
            events.append('owned-poll')
            return 17
    class Output:
        def tail(self, stream, max_lines=20):
            assert max_lines == 20
            events.append('tail:' + stream)
            return stream + ':' + '声音' * 6000
    runtime.lifecycle.process = OwnedProcess()
    runtime.lifecycle.output = Output()
    shutdown = workflow.shutdown_sandboxed_wwise
    def cleanup(*args):
        path = runtime.state_dir / 'workflow-pre-teardown-process.json'
        assert path.is_file(), 'pre-teardown diagnostics must exist before cleanup'
        observed = json.loads(path.read_text())
        assert observed['owned_launch_pid'] == 123456 and observed['observed_exit_code'] == 17
        assert observed['process_state'] == 'exited' and observed['phase'] == 'before_owned_shutdown'
        assert type(observed['captured_at_unix_ns']) is int
        for stream in ('stdout', 'stderr'):
            assert 0 < len(observed[stream + '_tail'].encode('utf-8')) <= 4096
            assert observed[stream + '_truncated'] is True
        events.append('diagnostic-exists')
        shutdown(*args)
    monkeypatch.setattr(workflow, 'shutdown_sandboxed_wwise', cleanup)
    original = RuntimeError('Original workflow failure remains the verdict')
    with pytest.raises(RuntimeError) as caught:
        fixture.throw(original)
    assert caught.value is original
    assert events.index('owned-poll') < events.index('diagnostic-exists') < events.index('shutdown') < events.index('release')
    assert records[-1]['invocation']['outcome'] == 'FAIL'


def test_workflow_diagnostic_capture_error_preserves_original_failure_and_cleanup(tmp_path, workflow, monkeypatch, capsys):
    fixture, events, records = _fixture_run(tmp_path, workflow, monkeypatch)
    next(fixture)
    def failed_capture(*args, **kwargs):
        events.append('capture-error')
        raise OSError('Diagnostic disk error')
    monkeypatch.setattr(workflow, '_capture_workflow_pre_teardown_process', failed_capture)
    original = RuntimeError('Original failure must survive diagnostic capture error')
    with pytest.raises(RuntimeError) as caught:
        fixture.throw(original)
    assert caught.value is original
    assert events.index('capture-error') < events.index('shutdown') < events.index('release')
    assert records[-1]['invocation']['outcome'] == 'FAIL'
    assert 'Diagnostic disk error' in capsys.readouterr().err


@pytest.mark.parametrize("tamper", (False, True))
def test_source_full_guard_runs_after_shutdown_and_before_final_pass(tmp_path, workflow, monkeypatch, tamper):
    fixture, events, records = _fixture_run(
        tmp_path, workflow, monkeypatch, tamper_on_shutdown=tamper,
    )
    next(fixture)
    if tamper:
        with pytest.raises(AssertionError, match="source hash changed"):
            next(fixture)
    else:
        with pytest.raises(StopIteration):
            next(fixture)
    assert events.index("shutdown") < events.index("record:final")
    final = records[-1]
    assert final["invocation"]["outcome"] == ("FAIL" if tamper else "PASS")
    source = final["source"]
    assert source["hash_scope"] == "all-source-regular-file-content"
    assert source["hash_algorithm"] == "sha256"
    assert source["file_count_before"] == source["file_count_after"] == 3
    assert source["bytes_hashed_before"] == source["bytes_hashed_after"] == 29
    assert (source["hash_before"] == source["hash_after"]) is (not tamper)
    assert source["tree_metadata_before"] == source["tree_metadata_after"]


def test_source_hash_bound_stops_fixture_before_launch(tmp_path, workflow, monkeypatch):
    fixture, events, records = _fixture_run(tmp_path, workflow, monkeypatch)
    monkeypatch.setattr(workflow, "SOURCE_HASH_MAX_BYTES", 1)
    with pytest.raises(workflow.SandboxFixtureError, match="bound"):
        next(fixture)
    assert "launch" not in events
    assert "release" in events
    assert records == []


@pytest.mark.parametrize("after_read", (False, True))
def test_full_source_hash_rejects_changed_open_file_identity(
    tmp_path, workflow, monkeypatch, after_read,
):
    root = tmp_path / "source"
    _source(root)
    original_fstat = os.fstat
    calls = 0

    def switched_identity(descriptor):
        nonlocal calls
        calls += 1
        info = original_fstat(descriptor)
        fields = {name: getattr(info, name) for name in (
            "st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns",
        )}
        if calls == (2 if after_read else 1):
            fields["st_ino"] += 1
        return SimpleNamespace(**fields)

    monkeypatch.setattr(os, "fstat", switched_identity)
    with pytest.raises(workflow.SandboxFixtureError, match="changed.*hashing"):
        workflow._hash_mutation_bearing_project_files(root)


def _curve_probe_runtime(tmp_path, workflow, *, version="2025.1", curve_query_error=False,
                         repeat_names_page=False):
    import json
    import uuid

    state = tmp_path / "state"
    evidence = tmp_path / "dispatcher"
    evidence.mkdir()
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"wwise_version": version, "waapi_host": "127.0.0.1",
                                  "waapi_port": 31337, "project_modification_policy": "read_only"}))
    commands = []
    owner = "{11111111-1111-1111-1111-111111111111}"
    curve = "{22222222-2222-2222-2222-222222222222}"

    def gateway(command):
        command = list(command)
        commands.append(command)
        assert command[0] in {"config-show", "status", "metadata", "query-object", "query-schema"}
        payload = {"ok": True, "fixture_only": True, "detected_version": version,
                   "endpoint": {"host": "127.0.0.1", "port": 31337, "url": "ws://127.0.0.1:31337/waapi"}}
        if command[:2] == ["metadata", "types"]:
            payload["agent_result"] = {"complete": True, "types": [
                {"name": "RTPC", "type": "WObject", "classId": 655360, "selection": "rtpc-type"},
                {"name": "Curve", "type": "WObject", "classId": 917520, "selection": "curve-type"},
            ]}
        elif command[:2] == ["metadata", "list"]:
            payload["agent_result"] = {"complete": not repeat_names_page, "fields": [
                {"name": "Curve", "selection": "selected-Curve"},
            ]}
            if repeat_names_page:
                payload["agent_result"]["next_command"] = {"gateway_argv": command + ["--page", "fixture-page"]}
        elif command[:2] == ["metadata", "detail"]:
            assert command[-2:] == ["--selection", "selected-Curve"]
            payload["agent_result"] = {"complete": True, "metadata": {
                # Preserve genuine omission of optional name/type in the result.
                "restriction": {"type": "reference", "restrictions": [{"type": ["Curve"]}]},
                "nativeOptionalNull": None,
            }}
        elif command[0] == "query-object":
            if "--advanced-waql" in command or "--exact-id" in command:
                if "--advanced-waql" in command:
                    assert command[2] == f'from object "{owner}" select @Curve'
                    assert command[command.index("--max-results") + 1] == "1"
                else:
                    assert command[2] == curve
                if curve_query_error:
                    return 2, {"ok": False, "error_code": "fixture-native-unavailable",
                               "native_observation": {"fixture_only": True}}
                payload["objects"] = [{"id": curve, "name": "", "type": "Curve", "path": "\\Curve",
                                       "class_id": 917520, "curve_points": [{"x": 0, "y": -6, "shape": "Linear"}]}]
            else:
                assert command == ["query-object", "--type-selection", "rtpc-type", "--max-results", "2"]
                payload["objects"] = [{"id": owner, "name": "", "type": "RTPC", "path": "\\RTPC"}]
        (evidence / (uuid.uuid4().hex + ".json")).write_text(json.dumps({"fixture_only": True,
                                            "command": command, "result": payload}))
        return 0, payload

    return SimpleNamespace(state_dir=state, env={"WWISE_EVIDENCE_DIR": str(evidence),
                          "WAAPI_SKILL_CONFIG_PATH": str(config)}, version=version,
                          candidate="a" * 40, lifecycle=SimpleNamespace(host="127.0.0.1", waapi_url="ws://127.0.0.1:31337/waapi"),
                          port=31337, category_results=[], raw_gateway=gateway), commands


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_curve_probe_retains_exact_read_only_observations_without_native_launch(
    tmp_path, workflow, version,
):
    import hashlib
    import json
    from wwise_waapi.object_query_outputs import available_query_outputs

    runtime, commands = _curve_probe_runtime(tmp_path, workflow, version=version)
    category = workflow._collect_rtpc_curve_metadata_probe(runtime)
    observed = json.loads(Path(category["observation_path"]).read_text())
    # Collector fixture only; no real category publisher ran.
    assert category["status"] == ("blocked" if version == "2021.1" else "PASS")
    assert observed["candidate"] == "a" * 40 and observed["version"] == version
    assert ("curve-points" in available_query_outputs(version)) is (version != "2021.1")
    if version == "2021.1":
        assert "curve-points" not in commands[-1]
        assert any(row["reason"] == "curve_points_output_unavailable_in_public_version" for row in observed["boundaries"])
    assert observed["mutation_authority"] is False and observed["business_effect_verified"] is False
    details = [row for row in observed["calls"] if row["stage"].endswith("-detail")]
    assert len(details) == 2
    for row in details:
        metadata = row["payload"]["agent_result"]["metadata"]
        assert "name" not in metadata and "type" not in metadata
        assert metadata["nativeOptionalNull"] is None
    assert details[0]["gateway_argv"][2:4] == ["--type-selection", "rtpc-type"]
    assert details[1]["gateway_argv"][2:4] == ["--exact-id", "{11111111-1111-1111-1111-111111111111}"]
    assert len(observed["native_evidence"]) == len(commands)
    assert hashlib.sha256(Path(category["observation_path"]).read_bytes()).hexdigest() == category["observation_sha256"]
    assert all(Path(row["path"]).is_file() for row in observed["native_evidence"])


def test_curve_probe_records_failed_public_curve_read_as_boundary(tmp_path, workflow):
    import json
    runtime, _commands = _curve_probe_runtime(tmp_path, workflow, curve_query_error=True)
    category = workflow._collect_rtpc_curve_metadata_probe(runtime)
    observed = json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "blocked"
    assert any(row.get("error_code") == "fixture-native-unavailable" for row in observed["boundaries"])
    assert observed["calls"][-1]["payload"]["native_observation"] == {"fixture_only": True}


def test_curve_probe_stops_incomplete_name_paging_at_owned_bound(tmp_path, workflow):
    import json
    runtime, commands = _curve_probe_runtime(tmp_path, workflow, repeat_names_page=True)
    category = workflow._collect_rtpc_curve_metadata_probe(runtime)
    observed = json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "blocked"
    assert any(row["reason"] == "eight_page_bound_reached" for row in observed["boundaries"])
    assert len([command for command in commands if command[:2] == ["metadata", "list"]]) == 16
    assert not any(command[:2] == ["metadata", "detail"] for command in commands)


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_curve_probe_reference_read_uses_existing_public_gateway_contract(tmp_path, workflow, version):
    from tests.unit.test_object_graph_business_gateway import _info

    runtime, _commands = _curve_probe_runtime(tmp_path, workflow, version=version)
    calls = []
    owner = "{11111111-1111-1111-1111-111111111111}"
    curve = "{22222222-2222-2222-2222-222222222222}"

    class Client:
        def call(self, uri, args=None, options=None):
            calls.append((uri, args, options))
            if uri == "ak.wwise.core.getInfo":
                return _info(version)
            assert uri == "ak.wwise.core.object.get", (uri, args, options)
            assert args == {"waql": f'from object "{owner}" select @Curve take 1'}
            assert options["return"] == ["id", "name", "type", "path", "classId", *(["points"] if version != "2021.1" else [])]
            return {"return": [{"id": curve, "name": "", "type": "Curve", "path": "\\Curve",
                                "classId": 917520, "points": [{"x": 0, "y": -6, "shape": "Linear"}]}]}

        def disconnect(self):
            pass

    code, payload = workflow.waapi_gateway.execute_gateway([
        "--state-dir", str(runtime.state_dir), "query-object", "--advanced-waql",
        f'from object "{owner}" select @Curve', "--max-results", "1", "--include", "class-id",
        *(["--include", "curve-points"] if version != "2021.1" else []),
    ], env=runtime.env, client_factory=lambda _url: Client())
    assert code == 0, payload
    assert payload["objects"][0]["id"] == curve and payload["objects"][0]["type"] == "Curve"
    if version != "2021.1":
        assert payload["objects"][0]["curve_points"] == [{"x": 0, "y": -6, "shape": "Linear"}]
    assert all(uri in {"ak.wwise.core.getInfo", "ak.wwise.core.object.get"} for uri, _args, _options in calls)


def _owned_probe_runtime(tmp_path, workflow, *, version="2025.1", missing_list=False, overflow=False):
    import json
    import uuid

    runtime, commands = _curve_probe_runtime(tmp_path, workflow, version=version)
    ids = {name: "{" + str(uuid.UUID(int=index)) + "}" for index, name in enumerate(
        ("sound", "rtpc", "bus", "effect", "music", "group", "slot"), start=1)}
    def row(name, kind, owner=None):
        return {"id": ids[name], "name": name, "type": kind, "path": "\\" + name,
                "parent": None, "owner": {"id": ids[owner]} if owner else None, "class_id": 1234}
    sound, music = row("sound", "Sound"), row("music", "MusicSwitchContainer")
    rtpc, bus = row("rtpc", "RTPC", "sound"), row("bus", "Bus")
    effect = row("effect", "Effect" if version < "2023.1" else "EffectSlot", "sound")
    group, slot = row("group", "SwitchGroup"), row("slot", "MusicArgumentsSlot", "music")
    rows = {value["id"]: value for value in (sound, music, rtpc, bus, effect, group, slot)}
    effect_field = "Effect0" if version < "2023.1" else "Effects"
    hops = {(ids["sound"], "OutputBus"): [bus], (ids["sound"], "RTPC"): [rtpc],
            (ids["sound"], effect_field): [effect], (ids["music"], "Arguments"): [slot if version == "2025.1" else group],
            (ids["slot"], "Argument"): [group]}

    def gateway(command):
        command = list(command)
        commands.append(command)
        assert command[0] in {"config-show", "status", "metadata", "query-object", "query-schema"}
        payload = {"ok": True, "detected_version": version,
                   "endpoint": {"host": "127.0.0.1", "port": 31337, "url": "ws://127.0.0.1:31337/waapi"}}
        if command[:2] == ["metadata", "types"]:
            payload["agent_result"] = {"complete": True, "types": [
                {"name": kind, "selection": kind + "-type"} for kind in ("Sound", "MusicSwitchContainer", "RTPC")]}
        elif command[:2] == ["metadata", "list"]:
            fields = ["OutputBus", effect_field, *([] if missing_list else ["RTPC"])] if command[3] == ids["sound"] else (
                ["Arguments"] if command[3] == ids["music"] else ["Argument"])
            payload["agent_result"] = {"complete": True, "fields": [{"name": name, "selection": name + "-field"} for name in fields]}
        elif command[:2] == ["metadata", "detail"]:
            payload["agent_result"] = {"complete": True, "metadata": {"restriction": {"type": "reference"}, "fixtureOptional": None}}
        elif command[0] == "query-object":
            if "--exact-id" in command:
                found = [rows[command[command.index("--exact-id") + 1]]]
            elif "--type-selection" in command:
                found = [music if command[2] == "MusicSwitchContainer-type" else sound]
            else:
                expression = command[command.index("--advanced-waql") + 1]
                if expression.startswith("from type RTPC"):
                    found = [sound]
                elif expression.startswith("from project where owner.id"):
                    found = [rtpc, effect] if ids["sound"] in expression else ([slot] if version == "2025.1" else [])
                else:
                    owner = expression.split('"')[1]
                    field = expression.split("select @")[1]
                    found = hops[owner, field]
                    if overflow and field == "RTPC":
                        found = found * 5
            payload.update(objects=found, limit_reached=len(found) == int(command[command.index("--max-results") + 1])
                           if "--max-results" in command else False)
        path = Path(runtime.env["WWISE_EVIDENCE_DIR"]) / (uuid.uuid4().hex + ".json")
        path.write_text(json.dumps({"fixture_only": True, "command": command, "result": payload}))
        return 0, payload

    runtime.raw_gateway = gateway
    return runtime, commands, ids


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_owned_list_probe_retains_sample_only_graph_and_fresh_metadata(tmp_path, workflow, version):
    import json
    runtime, commands, ids = _owned_probe_runtime(tmp_path, workflow, version=version)
    category = workflow._collect_owned_list_metadata_probe(runtime)
    observed = json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "PASS", observed
    assert observed["complete_owned_list_discovery_proven"] is False
    assert observed["field_cardinality_permission_proven"] is False
    assert observed["mutation_authority"] is False
    assert observed["owner_comparisons"][0]["missing_known_owned_ids"] == []
    assert observed["native_evidence"] and observed["calls"]
    assert all("class-id" in command for command in commands if command[0] == "query-object")
    details = [call for call in observed["calls"] if call["gateway_argv"][:2] == ["metadata", "detail"]]
    assert "name" not in details[0]["payload"]["agent_result"]["metadata"]
    assert "type" not in details[0]["payload"]["agent_result"]["metadata"]
    assert all("Curve" not in " ".join(command) for command in commands)
    if version == "2025.1":
        assert any(f'from object "{ids["slot"]}" select @Argument' in command for command in commands)
    else:
        assert not any(part.endswith("select @Argument") for command in commands for part in command)


@pytest.mark.parametrize("fault", ("missing-list", "row-overflow", "metadata-error", "paging-overflow", "owner-filter"))
def test_owned_list_probe_keeps_incomplete_observation_blocked(tmp_path, workflow, fault):
    import json
    runtime, commands, ids = _owned_probe_runtime(tmp_path, workflow,
        missing_list=fault == "missing-list", overflow=fault == "row-overflow")
    original = runtime.raw_gateway

    def gateway(command):
        code, payload = original(command)
        if fault == "metadata-error" and list(command[:2]) == ["metadata", "detail"]:
            return 2, {"ok": False, "error_code": "fixture-metadata-rejected", "original_raw_error": {"fixture": None}}
        if fault == "paging-overflow" and list(command[:2]) == ["metadata", "list"]:
            payload["agent_result"].update(complete=False, next_command={"gateway_argv": list(command)})
        if fault == "owner-filter" and any(str(value).startswith("from project where owner.id") for value in command):
            payload["objects"][0]["owner"] = None
        return code, payload

    runtime.raw_gateway = gateway
    category = workflow._collect_owned_list_metadata_probe(runtime)
    observed = json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "blocked", observed
    expected = {"missing-list": "field_not_uniquely_listed_gateway_discovery_boundary",
                "row-overflow": "query_row_bound_reached", "metadata-error": "public_read_rejected",
                "paging-overflow": "metadata_page_bound_reached", "owner-filter": "owner_filter_readback_mismatch"}[fault]
    assert any(row["reason"] == expected for row in observed["boundaries"])
    assert len(commands) <= 96 and len(observed["calls"]) == len(commands)
    if fault == "missing-list":
        assert not any(command[-1] == "RTPC-field" for command in commands)
        assert any(f'from object "{ids["sound"]}" select @RTPC' in command for command in commands)
    if fault == "metadata-error":
        assert any(row["payload"].get("original_raw_error") == {"fixture": None} for row in observed["calls"])


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_owned_probe_reads_use_existing_public_gateway_with_owned_projection(tmp_path, workflow, version):
    from tests.unit.test_object_graph_business_gateway import _info

    runtime, _commands, ids = _owned_probe_runtime(tmp_path, workflow, version=version)
    effect = "Effect0" if version < "2023.1" else "Effects"
    expressions = ['from type RTPC select owner where type = "Sound"',
                   f'from object "{ids["sound"]}" select @RTPC',
                   f'from object "{ids["sound"]}" select @OutputBus',
                   f'from object "{ids["sound"]}" select @{effect}',
                   f'from project where owner.id = "{ids["sound"]}"']
    if version >= "2023.1":
        expressions.append(f'from object "{ids["music"]}" select @Arguments')
    if version == "2025.1":
        expressions.append(f'from object "{ids["slot"]}" select @Argument')
    observed = []

    class Client:
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.getInfo":
                return _info(version)
            assert uri == "ak.wwise.core.object.get", (uri, args, options)
            observed.append(args["waql"])
            assert options["return"] == ["id", "name", "type", "path", "parent", "owner", "classId"]
            slot = version == "2025.1" and "select @Arguments" in args["waql"]
            return {"return": [{"id": ids["slot"] if slot else ids["rtpc"], "name": "",
                                "type": "PluginInnerObject" if slot else "RTPC", "path": "\\RTPC",
                                "parent": None, "owner": {"id": ids["sound"]},
                                "classId": 5832704 if slot else 1441808}]}

        def disconnect(self):
            pass

    for expression in expressions:
        code, payload = workflow.waapi_gateway.execute_gateway([
            "--state-dir", str(runtime.state_dir), "query-object", "--advanced-waql", expression,
            "--max-results", "5", "--include", "parent", "--include", "owner", "--include", "class-id"],
            env=runtime.env, client_factory=lambda _url: Client())
        assert code == 0, payload
        rows = payload.get("objects", payload.get("agent_result"))
        assert rows[0]["owner"]["id"] == ids["sound"] and rows[0]["parent"] is None
        slot = version == "2025.1" and "select @Arguments" in expression
        assert rows[0]["class_id"] == (5832704 if slot else 1441808)
        assert rows[0]["type"] == ("PluginInnerObject" if slot else "RTPC")
    assert observed == [expression + " take 5" for expression in expressions]


def _short_id_probe_runtime(tmp_path, *, version="2021.1", fault=None):
    state = tmp_path / "short-id-state"
    state.mkdir()
    config = tmp_path / "short-id-config.json"
    config.write_text(json.dumps({"project_modification_policy": "ask_before_changes"}))
    evidence_root = tmp_path / "short-id-dispatcher"
    evidence_root.mkdir()
    commands = []
    endpoint = {"host": "127.0.0.1", "port": 8080, "url": "ws://127.0.0.1:8080/waapi"}
    event = {"id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}", "name": "Play_Example",
             "type": "Event", "path": "\\Events\\Play_Example", "short_id": 123}
    dialogue = {"id": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}", "name": "Dialogue_Example",
                "type": "DialogueEvent", "path": "\\Events\\Dialogue_Example", "short_id": 456}

    def gateway(command):
        command = list(command)
        commands.append(command)
        assert command[0] in {"status", "query-object"}, command
        payload = {"ok": True, "endpoint": endpoint, "detected_version": version}
        if command[0] == "query-object":
            selected = dialogue if "DialogueEvent" in command or "dialogue-event" in command else event
            if "--exact-id" in command:
                selected = dialogue if dialogue["id"] in command else event
            payload["agent_result"] = [dict(selected)]
            if "--short-id" in command:
                payload["source_resolution"] = {"complete": True, "candidate_count": 1}
        code = 0
        if fault == "missing-dialogue" and "DialogueEvent" in command:
            payload["agent_result"] = []
        if "--short-id" in command:
            if fault == "native-error":
                code, payload = 2, {"ok": False, "error_code": "native-fixture-rejection",
                                    "call": {"waapi_error_uri": "ak.fixture.invalidQuery", "raw_error": {"fixture": None}}}
            if fault == "incomplete":
                payload["source_resolution"]["complete"] = False
        if fault == "exact-drift" and "--exact-id" in command:
            payload["agent_result"][0]["name"] = "Changed"
        if fault == "endpoint" and command == ["status"]:
            payload["endpoint"] = {**endpoint, "port": 9999}
        if fault == "version" and command == ["status"]:
            payload["detected_version"] = "2025.1"
        path = evidence_root / f"{len(commands)}.json"
        path.write_text(json.dumps({"fixture_only": True, "argv": command, "payload": payload}))
        return code, payload

    runtime = SimpleNamespace(version=version, candidate="a" * 40, state_dir=state,
        category_results=[], env={"WAAPI_SKILL_CONFIG_PATH": str(config),
                                  "WWISE_EVIDENCE_DIR": str(evidence_root)},
        lifecycle=SimpleNamespace(host=endpoint["host"], waapi_url=endpoint["url"]),
        port=endpoint["port"], raw_gateway=gateway)
    return runtime, commands, config


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_short_id_probe_reuses_shared_runtime_without_policy_change(tmp_path, workflow, version):
    import hashlib
    runtime, commands, config = _short_id_probe_runtime(tmp_path, version=version)
    config_before = config.read_bytes()
    workflow.test_read_only_short_id_native_observation(runtime)
    category, = runtime.category_results
    assert category["status"] == "PASS", category
    body = Path(category["observation_path"]).read_bytes()
    observed = json.loads(body)
    assert category["observation_sha256"] == hashlib.sha256(body).hexdigest()
    assert observed["candidate"] == runtime.candidate and observed["version"] == version
    assert observed["project_mutation_count"] == 0 and observed["mutation_authority"] is False
    assert observed["observations"] == [
        {"kind": "event", "short_id": 123, "canonical_id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
         "outcome": "NATIVE_SUCCESS", "candidate_count": 1},
        {"kind": "dialogue-event", "short_id": 456, "canonical_id": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
         "outcome": "NATIVE_SUCCESS", "candidate_count": 1},
    ]
    assert len(commands) == len(observed["receipts"]) == len(observed["native_evidence"]) == 7
    assert config.read_bytes() == config_before
    assert all(command[0] in {"status", "query-object"} for command in commands)


@pytest.mark.parametrize("fault", ["missing-dialogue", "native-error", "incomplete", "exact-drift", "endpoint", "version"])
def test_short_id_shared_probe_retains_failure_without_retry(tmp_path, workflow, fault):
    runtime, commands, config = _short_id_probe_runtime(tmp_path, fault=fault)
    config_before = config.read_bytes()
    with pytest.raises(AssertionError):
        workflow.test_read_only_short_id_native_observation(runtime)
    category, = runtime.category_results
    assert category["status"] == "FAIL", category
    observed = json.loads(Path(category["observation_path"]).read_text())
    assert observed["error"].startswith("AssertionError:")
    assert observed["business_effect_verified"] is False
    assert config.read_bytes() == config_before
    assert len(commands) == len(observed["receipts"]) == len(observed["native_evidence"])
    assert len(commands) <= 7 and commands.count(commands[-1]) == 1
    if fault == "native-error":
        receipt = observed["receipts"][-1]
        assert receipt["exit_code"] == 2
        assert receipt["payload"]["call"] == {
            "waapi_error_uri": "ak.fixture.invalidQuery", "raw_error": {"fixture": None}}
    if fault == "missing-dialogue":
        assert "DialogueEvent populated fixture prerequisite missing" in observed["error"]
        assert not any("dialogue-event" in command for command in commands)


def test_standalone_short_id_observation_keeps_lifecycle_and_original_evidence(tmp_path, monkeypatch):
    import tests.live.test_full_coverage_query_native as standalone

    fake, commands, _config = _short_id_probe_runtime(tmp_path)
    root = tmp_path / "standalone-native-root"
    finished = []
    bindings = []

    class Lifecycle:
        def __init__(self, **kwargs):
            bindings.append(kwargs)

        def start(self):
            root.mkdir()
            return SimpleNamespace(evidence_root=root, host="127.0.0.1", port=8080)

        def finish(self, status, *, reason):
            finished.append((status, reason))
            return SimpleNamespace(final_status=status, as_dict=lambda: {"status": status})

    def fixture_gateway(*, skill_source, runtime, version, receipts):
        assert version == "2021.1" and runtime.evidence_root == root
        assert skill_source.name == "waapi-skill"

        def gateway(command):
            if command[0] == "config-set":
                assert command[-2:] == ["--project-modification-policy", "read_only"]
                code, payload = 0, {"ok": True}
            else:
                code, payload = fake.raw_gateway(command)
            receipts.append({"argv": list(command), "exit_code": code, "payload": payload})
            assert code == 0 and payload["ok"] is True
            return payload

        return gateway

    monkeypatch.setenv("WAAPI_SHORT_ID_NATIVE_ROOT", str(root))
    monkeypatch.setenv("WWISE_VERSION", "2021.1")
    monkeypatch.setattr(standalone, "ScenarioLifecycle", Lifecycle)
    monkeypatch.setattr(standalone, "fixture_gateway", fixture_gateway)
    standalone.test_short_id_typed_native_read_observations()
    evidence = json.loads((root / "short-id-native-observations.json").read_text())
    assert set(evidence) == {"agent_started", "project_mutation_count", "version", "scope", "receipts", "observations", "status"}
    assert len(evidence["receipts"]) == 8 and len(commands) == 7
    assert [row["kind"] for row in evidence["observations"]] == ["event", "dialogue-event"]
    assert evidence["project_mutation_count"] == 0
    assert finished == [("PASS", "")]
    assert bindings[0]["scenario_id"] == "full-coverage-short-id-typed-observations"
    assert bindings[0]["scenario_root"] == root


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_short_id_collector_executes_all_commands_through_public_gateway(tmp_path, workflow, version):
    from tests.unit.test_object_graph_business_gateway import _info, _project

    runtime, commands, config = _short_id_probe_runtime(tmp_path, version=version)
    config.write_text(json.dumps({"wwise_version": version, "waapi_host": "127.0.0.1",
        "waapi_port": 8080, "project_modification_policy": "ask_before_changes"}))
    rows = [
        {"id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}", "name": "Play_Example",
         "type": "Event", "path": "\\Events\\Play_Example", "shortId": 123},
        {"id": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}", "name": "Dialogue_Example",
         "type": "DialogueEvent", "path": "\\Events\\Dialogue_Example", "shortId": 456},
    ]
    dispatches = []
    dialogue_literal = "456.0" if version in {"2021.1", "2022.1", "2023.1"} else "456"

    class Client:
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.getInfo":
                return _info(version)
            if uri == "ak.wwise.core.getProjectInfo":
                return _project(tmp_path)
            if uri == "ak.wwise.core.object.getTypes":
                return {"return": [{"classId": 100, "name": "Event", "type": "WObject"},
                                   {"classId": 101, "name": "DialogueEvent", "type": "WObject"}]}
            assert uri == "ak.wwise.core.object.get", (uri, args, options)
            if args == {"waql": "from type Project take 1"}:
                assert version == "2021.1"
                assert options == {"return": ["id", "name", "type", "path"]}
                return {"return": [{**_project(tmp_path), "type": "Project"}]}
            dispatches.append((args, options))
            if "waql" in args:
                expression = args["waql"]
                selected = rows[1] if "DialogueEvent" in expression or rows[1]["id"] in expression else rows[0]
                assert expression in {
                    "from type Event take 1", "from type DialogueEvent take 1",
                    "from type Event where shortId = 123.0 take 65",
                    f"from type DialogueEvent where shortId = {dialogue_literal} take 65",
                    *(f'from object "{row["id"]}"' + suffix for row in rows for suffix in ("", " take 64")),
                }, expression
            else:
                assert version != "2021.1"
                assert args == {"from": {"id": [{"shortId": 123, "type": 10}]},
                                "transform": [{"range": [0, 65]}]}, args
                selected = rows[0]
            source_lookup = "shortId =" in args.get("waql", "") or "from" in args
            expected_fields = ["id", "name", "type", "path"] + ([] if source_lookup else ["shortId"])
            assert options == {"return": expected_fields}, options
            return {"return": [{key: selected[key] for key in options["return"]}]}

        def disconnect(self):
            pass

    def gateway(command):
        commands.append(list(command))
        workflow.waapi_gateway.build_parser().parse_args(list(command))
        return workflow.waapi_gateway.execute_gateway(
            ["--state-dir", str(runtime.state_dir), *command], env=runtime.env,
            client_factory=lambda _url: Client())

    runtime.raw_gateway = gateway
    workflow.test_read_only_short_id_native_observation(runtime)
    category, = runtime.category_results
    evidence = json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "PASS" and len(commands) == 7
    assert [row["short_id"] for row in evidence["observations"]] == [123, 456]
    assert [row["canonical_id"] for row in evidence["observations"]] == [row["id"] for row in rows]
    assert len(dispatches) == 8
    assert any(args == {"waql": f"from type DialogueEvent where shortId = {dialogue_literal} take 65"}
               for args, _options in dispatches)
    if version == "2021.1":
        assert any(args == {"waql": "from type Event where shortId = 123.0 take 65"}
                   for args, _options in dispatches)


@pytest.mark.parametrize(("projection", "fault"), [("full", None), ("compact", None),
    ("compact", "verification-digest"), ("compact", "assertion-count")])
def test_legacy_transaction_create_uses_public_draft_and_compact_verify_evidence(tmp_path, workflow, projection, fault):
    matrix = importlib.import_module("tests.destructive.test_gateway_transaction_matrix")
    from copy import deepcopy
    from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, ROOT
    from tests.unit.test_field_interface_closure_gateway import SECOND

    class Client(OwnedGraphTask):
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.getProjectInfo":
                # Existing large-project native response fixture forces the
                # real bounded stdout producer to compact verification evidence.
                response = super().call(uri, args, options)
                return ({**response, "directories": {"cache": "x" * 13_000}}
                        if projection == "compact" else response)
            if uri == "ak.wwise.core.object.create":
                self.calls.append((uri, deepcopy(args), deepcopy(options)))
                assert args["parent"] == SECOND
                assert args["type"] == "ActorMixer" and args["name"] == "LegacyProbe"
                assert args["notes"] == "Created once through public Draft"
                self.objects[ROOT] = {"id": ROOT, "name": "LegacyProbe", "type": "ActorMixer",
                    "path": self.objects[SECOND]["path"] + "\\LegacyProbe",
                    "parent": {"id": SECOND}, "notes": args["notes"]}
                return {"id": ROOT, "name": "LegacyProbe"}
            return super().call(uri, args, options)

    client = Client(tmp_path, "2023.1", "object.create")
    commands = []

    def gateway(command, *, live):
        commands.append(list(command))
        code, payload = matrix.waapi_gateway.execute_gateway(
            ["--state-dir", str(tmp_path / "state"), *command], env=client.env,
            client_factory=lambda _url: client)
        assert code == 0, payload
        if command[0] == "verify" and fault is not None:
            if fault == "verification-digest":
                payload["stdout_projection"]["verification_canonical_sha256"] = "0" * 64
            else:
                payload["verification"]["passed_assertion_count"] += 1
        return payload

    runtime = SimpleNamespace(version="2023.1", state_dir=tmp_path / "state", gateway=gateway)
    def complete():
        return matrix._complete_business_object_create(runtime,
            parent_segments=("Actor-Mixer Hierarchy", "Default Work Unit"),
            name="LegacyProbe", notes="Created once through public Draft")

    if fault is not None:
        with pytest.raises(AssertionError):
            complete()
    else:
        result = complete()
        assert result["verify"]["verified"] is True
        assert ("assertions" in result["verify"]["verification"]) is (projection == "full")
        assert result["verification_evidence"]["assertions"]
        assert all(item["passed"] is True for item in result["verification_evidence"]["assertions"])
    assert client.objects[ROOT]["parent"] == {"id": SECOND}
    assert len([uri for uri, _args, _options in client.calls if uri.endswith("object.create")]) == 1
    assert len([command for command in commands if command[0] == "execute"]) == 1


@pytest.mark.parametrize("version,number,signed", [
    (version, 3970659059, -324308237) for version in ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"]
] + [("2021.1", 0, 0), ("2021.1", 2147483648, -2147483648), ("2021.1", 4294967295, -1)])
@pytest.mark.parametrize("fault", [None, "native-error", "exact-drift"])
def test_short_id_diagnostic_uses_actual_gateway_and_retains_unsigned_miss(tmp_path, workflow, version, number, signed, fault):
    from tests.unit.test_object_graph_business_gateway import _info, _project

    runtime, commands, config = _short_id_probe_runtime(tmp_path, version=version)
    config.write_text(json.dumps({"wwise_version": version, "waapi_host": "127.0.0.1",
        "waapi_port": 8080, "project_modification_policy": "ask_before_changes"}))
    before = config.read_bytes()
    row = {"id": "{3C874205-5335-4290-830F-A8BFF3AE8A6B}", "name": "Objective_Status",
        "type": "DialogueEvent", "path": "\\Dynamic Dialogue\\Dialogue\\Objective_Status", "shortId": number}
    dispatches = []
    expected = {
        "from type DialogueEvent take 1",
        f'from object "{row["id"]}"',
        f"from type DialogueEvent where shortId = {number} take 65",
        f'from object "{row["id"]}" where shortId = {number} take 65',
        f"from type DialogueEvent where shortId = {signed} take 65",
        f"from type DialogueEvent where shortId = {number}.0 take 65",
        f'from object "{row["id"]}" take 65',
    }

    class Client:
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.getInfo":
                return _info(version)
            if uri == "ak.wwise.core.getProjectInfo":
                return _project(tmp_path)
            if uri == "ak.wwise.core.object.getTypes":
                return {"return": [{"classId": 101, "name": "DialogueEvent", "type": "WObject"}]}
            assert uri == "ak.wwise.core.object.get", (uri, args, options)
            if args == {"waql": "from type Project take 1"}:
                assert version == "2021.1"
                return {"return": [{**_project(tmp_path), "type": "Project"}]}
            expression = args["waql"]
            assert expression in expected, expression
            dispatches.append((expression, options))
            if options == {"return": ["id", "name", "type", "path"]}:
                literal = f"{number}.0" if version in {"2021.1", "2022.1", "2023.1"} else str(number)
                assert expression == f"from type DialogueEvent where shortId = {literal} take 65"
                return {"return": []}  # Keep a baseline-miss control after the repair, too.
            if fault == "native-error" and f"{number}.0" in expression:
                raise RuntimeError("diagnostic decimal literal rejected")
            if f"shortId = {number} " in expression:
                return {"return": []}  # Trace-shaped baseline miss, not a native semantics claim.
            selected = dict(row)
            if fault == "exact-drift" and expression == f'from object "{row["id"]}"':
                selected["name"] = "Changed"
            assert options == {"return": ["id", "name", "type", "path", "shortId"]}, options
            return {"return": [selected]}

        def disconnect(self):
            pass

    def gateway(command):
        commands.append(list(command))
        workflow.waapi_gateway.build_parser().parse_args(list(command))
        return workflow.waapi_gateway.execute_gateway(["--state-dir", str(runtime.state_dir), *command],
            env=runtime.env, client_factory=lambda _url: Client())

    runtime.raw_gateway = gateway
    if fault == "exact-drift":
        with pytest.raises(AssertionError):
            workflow.test_read_only_short_id_native_diagnostic(runtime)
    else:
        workflow.test_read_only_short_id_native_diagnostic(runtime)
    category, = runtime.category_results
    evidence = json.loads(Path(category["observation_path"]).read_text())
    assert config.read_bytes() == before
    assert evidence["business_effect_verified"] is False and evidence["mutation_authority"] is False
    if fault == "exact-drift":
        assert category["status"] == "FAIL" and len(commands) == 3
        return
    assert category["status"] == "PASS"  # Diagnostic collection only, never resolver acceptance.
    assert evidence["baseline_contains_chosen_identity"] is False
    assert len(commands) == 10 and commands.count(["query-schema", "--advanced"]) == 1
    assert all(command[0] in {"status", "query-schema", "query-object"} for command in commands)
    baseline = next(receipt for receipt in evidence["receipts"] if "--short-id" in receipt["argv"])
    assert baseline["payload"]["source_resolution"]["short_id"] == number
    assert baseline["payload"]["agent_result"] == []
    assert len(evidence["variants"]) == 5
    assert {variant["name"] for variant in evidence["variants"]} == {
        "typed-unsigned", "guid-unsigned", "typed-signed32", "typed-decimal", "guid-no-predicate"}
    assert all(variant["hypothesis"] for variant in evidence["variants"])
    assert all(expression.endswith((" take 1", " take 65")) or expression == f'from object "{row["id"]}"'
               for expression, _ in dispatches)
    if fault == "native-error":
        failed = next(variant for variant in evidence["variants"] if variant["name"] == "typed-decimal")
        assert failed["status"] == "query_failed"
        receipt = next(receipt for receipt in evidence["receipts"] if f"{number}.0" in str(receipt["argv"]))
        assert receipt["exit_code"] == 2
        assert receipt["payload"]["call"]["error_code"] == "RuntimeError"


def _prospective_native_runtime(tmp_path, workflow, version, family, *, fault=None):
    from copy import deepcopy
    from tests.unit.test_new_object_conditions_gateway import (
        ProspectiveReferenceTask, HIERARCHY_GROUP, HIERARCHY_TARGET, CREATED,
    )
    from tests.unit.test_field_interface_closure_gateway import FIRST

    class Client(ProspectiveReferenceTask):
        def call(self, uri, args=None, options=None):
            if uri.endswith("object.get"):
                expression = args.get("waql", "")
                if expression == f"from type {family} take 1":
                    self.calls.append((uri, deepcopy(args), deepcopy(options)))
                    rows = [] if fault == "missing-target" else [self.objects[HIERARCHY_TARGET]]
                elif expression.startswith('from object "'):
                    self.calls.append((uri, deepcopy(args), deepcopy(options)))
                    identity = expression.split('"')[1]
                    if identity.startswith("\\"):
                        assert identity == self.objects[FIRST]["path"], expression
                        rows = [deepcopy(self.objects[FIRST])]
                    else:
                        rows = [deepcopy(self.objects[identity])]
                    if fault == "independent-reference" and rows[0]["id"] == CREATED:
                        rows[0]["DefaultSwitchOrState"] = HIERARCHY_GROUP
                else:
                    result = super().call(uri, args, options)
                    rows = result["return"]
                return {"return": [{key: deepcopy(row[key[1:] if key.startswith("@") else key])
                    for key in options["return"] if (key[1:] if key.startswith("@") else key) in row}
                    for row in rows]}
            result = super().call(uri, args, options)
            if fault == "ignored-default" and uri.endswith("object.create"):
                self.objects[CREATED]["DefaultSwitchOrState"] = None
            return result

    client = Client(tmp_path, version, state=family == "State")
    client.types += [{"classId": 10, "name": family, "type": "WObject"},
                     {"classId": 11, "name": family + "Group", "type": "WObject"}]
    client.objects[FIRST]["path"] = (workflow.CONTAINERS_PARENT if version == "2025.1"
                                      else workflow.ACTOR_MIXER_PARENT)
    client.calls.clear()
    evidence_root = tmp_path / "dispatcher"
    evidence_root.mkdir()
    runtime = SimpleNamespace(version=version, candidate="a" * 40, state_dir=tmp_path / "state",
        category_results=[], env={**client.env, "WWISE_EVIDENCE_DIR": str(evidence_root)},
        lifecycle=SimpleNamespace(host="127.0.0.1", waapi_url="ws://127.0.0.1:31337/waapi"),
        port=31337, sandbox=SimpleNamespace(metadata=SimpleNamespace(get_info_version={"fixture": version})))
    commands = []

    def gateway(command):
        commands.append(list(command))
        workflow.waapi_gateway.build_parser().parse_args(list(command))
        return workflow.waapi_gateway.execute_gateway(["--state-dir", str(runtime.state_dir), *command],
            env=runtime.env, client_factory=lambda _url: client)

    runtime.raw_gateway = gateway
    return runtime, client, commands


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("family", ("Switch", "State"))
def test_prospective_reference_native_collector_uses_public_gateway(tmp_path, workflow, version, family):
    from tests.unit.test_new_object_conditions_gateway import HIERARCHY_GROUP, HIERARCHY_TARGET, CREATED

    runtime, client, commands = _prospective_native_runtime(tmp_path, workflow, version, family)
    workflow.test_prospective_group_default_native_acceptance(runtime, family)
    category, = runtime.category_results
    evidence = json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "PASS"
    assert evidence["independent_readback"]["id"] == CREATED
    assert evidence["selected_target"]["id"] == HIERARCHY_TARGET
    assert evidence["selected_group"]["id"] == HIERARCHY_GROUP
    assert evidence["source_rule"]["version"] == version
    assert len(evidence["source_rule"]["sha256"]) == 64
    writes = [(uri, args) for uri, args, _ in client.calls if uri.endswith(
        ("object.create", "object.set", "setReference", "setProperty"))]
    assert len(writes) == 1 and writes[0][0].endswith("object.create")
    assert writes[0][1]["@SwitchGroupOrStateGroup"] == HIERARCHY_GROUP
    assert writes[0][1]["@DefaultSwitchOrState"] == HIERARCHY_TARGET
    assert sum(command[0] == "execute" for command in commands) == 1
    assert any(command[:3] == ["query-object", "--custom-kind", family] for command in commands)
    independent = next(i for i, command in enumerate(commands) if command[:3] == ["query-object", "--exact-id", CREATED])
    assert independent > next(i for i, command in enumerate(commands) if command[0] == "verify")
    assert commands[independent].count("--include-field") == 2
    assert evidence["lifecycle_acceptance"].startswith("Requires the final")


@pytest.mark.parametrize("fault", ("missing-target", "ignored-default", "independent-reference"))
def test_prospective_reference_native_collector_retains_failure_without_retry(tmp_path, workflow, fault):
    runtime, client, commands = _prospective_native_runtime(tmp_path, workflow, "2025.1", "State", fault=fault)
    with pytest.raises(AssertionError):
        workflow.test_prospective_group_default_native_acceptance(runtime, "State")
    category, = runtime.category_results
    evidence = json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "FAIL" and evidence["error"]
    expected_creates = 0 if fault == "missing-target" else 1
    assert sum(command[0] == "execute" for command in commands) == expected_creates
    assert sum(uri.endswith("object.create") for uri, _, _ in client.calls) == expected_creates
    if fault == "ignored-default":
        last = evidence["receipts"][-1]
        assert last["argv"][0] == "verify" and last["exit_code"] == 2
        assert last["payload"].get("verified") is not True
    elif fault == "independent-reference":
        assert any(row["argv"][0] == "verify" and row["payload"].get("state") == "verified"
                   for row in evidence["receipts"])
        assert evidence["receipts"][-1]["argv"][0] == "query-object"
    if expected_creates:
        assert evidence["lifecycle_final_reference"]["transaction_id"] == category["transaction_id"]
        assert category["transaction_id"]


def test_owned_list_probe_keeps_generic_member_type_and_exact_class_id_observation(tmp_path, workflow):
    runtime, commands, ids = _owned_probe_runtime(tmp_path, workflow)
    original = runtime.raw_gateway

    def gateway(command):
        code, payload = original(command)
        if command[0] == "query-object":
            for row in payload["objects"]:
                if row["id"] == ids["slot"]:
                    row.update(type="PluginInnerObject", class_id=5832704)
        return code, payload

    runtime.raw_gateway = gateway
    category = workflow._collect_owned_list_metadata_probe(runtime)
    observed = json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "blocked"
    members = next(row["members"] for row in observed["relationships"] if row["field"] == "Arguments")
    assert members[0]["type"] == "PluginInnerObject" and members[0]["class_id"] == 5832704
    assert any(row["reason"] == "Arguments_member_type_differs_from_matching_source" for row in observed["boundaries"])
    assert observed["complete_owned_list_discovery_proven"] is False
    assert observed["field_cardinality_permission_proven"] is False and observed["mutation_authority"] is False
    assert all("class-id" in command for command in commands if command[0] == "query-object")


@pytest.mark.parametrize("missing", ("owner", "class_id"))
def test_owned_probe_projection_preserves_missing_outputs_and_explicit_null(tmp_path, workflow, missing):
    runtime, _commands, ids = _owned_probe_runtime(tmp_path, workflow)
    original = runtime.raw_gateway

    def gateway(command):
        code, payload = original(command)
        if command[0] == "query-object":
            for row in payload["objects"]:
                if row["id"] == ids["slot"]:
                    row.pop(missing, None)
        return code, payload

    runtime.raw_gateway = gateway
    category = workflow._collect_owned_list_metadata_probe(runtime)
    observed = json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "blocked"
    members = next(row["members"] for row in observed["relationships"] if row["field"] == "Arguments")
    assert missing not in members[0] and members[0]["parent"] is None
    expected = "relationship_output_missing" if missing == "owner" else "class_id_output_missing"
    assert any(row["reason"] == expected for row in observed["boundaries"])


@pytest.mark.parametrize("wrong_media,version,migrated,wrong_open", [
    *[pytest.param(wrong_media, version, migrated, wrong_open,
        id=f"{wrong_media}-{version}-{migrated}-{wrong_open}")
      for wrong_media in (False, True) for version, migrated, wrong_open in
      [("2025.1", False, False), ("2023.1", True, False), ("2024.1", True, False),
       ("2025.1", True, False), ("2023.1", True, True)]],
    *[pytest.param(fault, "2023.1", True, False, id=f"{fault}-2023.1-True-False")
      for fault in ("preservation", "lost", "new", "after-write", "wrong-media-after-write", "before-write", "preview-drift", "uppercase-before", "uppercase-after", "reopen-materialization", "reopen-save-failure")],
    *[pytest.param("reopen-materialization", version, True, False, id=f"reopen-materialization-{version}-True-False")
      for version in ("2024.1", "2025.1")],
    *[pytest.param(fault, "2025.1", False, False, id=f"{fault}-2025.1-False-False")
      for fault in ("overflow", "uppercase-overflow")],
])
def test_media_native_collector_saves_baseline_and_retains_failed_artifacts(tmp_path, workflow, monkeypatch, wrong_media, version, migrated, wrong_open):
    from xml.etree import ElementTree as ET
    from tests.unit.test_console_project_alternatives_gateway import CliProjectTask, saved_fixture_project, WaapiRequestFailed, OPEN

    class Client(CliProjectTask):
        def __init__(self, *args):
            self.loaded, self.reopened, self.absence_errors = True, False, []
            self.pending_reopened_state = False
            super().__init__(*args)

        def materialize_reopened_state(self):
            if self.pending_reopened_state:
                tree = ET.parse(self.other_unit)
                track = ET.SubElement(tree.find(".//WorkUnit/ChildrenList"), "MusicTrack", Name="Stealth",
                    ID="{9861812D-295E-47DC-BB84-803555479814}")
                states = ET.SubElement(ET.SubElement(track, "StateInfo"), "CustomStateList")
                states.append(ET.fromstring('''<CustomState><StateRef Name="None" ID="{4BA09D62-D59B-4880-A78C-8BECE7D7899F}"/>
<CustomState Name="" ID="{B5549C79-F061-49C0-8A64-21B5617FDCDF}" ShortID="824120204"/></CustomState>'''))
                tree.write(self.other_unit)
                self.pending_reopened_state = False

        def call(self, uri, args=None, options=None):
            if not self.loaded and (uri.endswith('getProjectInfo') or (
                    uri.endswith('object.get') and args.get('waql', '').startswith('from type Project '))):
                self.calls.append((uri, args, options))
                self.absence_errors.append(WaapiRequestFailed(uri))
                raise self.absence_errors[-1]
            if uri.endswith('object.get') and args.get('waql') == 'from type Project take 2':
                self.calls.append((uri, args, options))
                return {'return': [{'id': ('{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}' if wrong_open and self.reopened
                    else '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}'), 'name': 'Fixture',
                    'type': 'Project', 'path': '\\', 'filePath': str(self.project_file)}]}
            if uri.endswith('getProjectInfo') and wrong_open and self.reopened:
                return {**super().call(uri, args, options), 'id': '{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}'}
            if uri == OPEN:
                self.calls.append((uri, args, options))
                assert not self.loaded and args == {'path': str(self.project_file)}
                self.loaded = True
                self.reopened = True
                self.pending_reopened_state = wrong_media == "reopen-materialization"
                return {}
            if uri.endswith("project.save"):
                self.calls.append((uri, args, options))
                if self.reopened:
                    assert "model_images" not in runtime.category_results[-1]
                    assert not media_previews and not any(call[0] == self.operation for call in self.calls)
                    if wrong_media == "reopen-save-failure":
                        raise RuntimeError("Injected reopened project save failure")
                self.materialize_reopened_state()
                tree = ET.parse(self.unit)
                tree.find(".//MediaID").set("ID", "123456")
                tree.write(self.unit)
                return {}
            if uri == "ak.wwise.cli.migrate":
                self.calls.append((uri, args, options))
                tree = ET.parse(self.unit)
                tree.find('.//Property[@Name="Volume"]/ValueList/Value').text = '-3'
                tree.write(self.unit)
                self.loaded = False
                return {"result": 0}
            if uri == self.operation:
                self.materialize_reopened_state()
                self.project_file.with_suffix(".mediaid").write_text('''<WwiseDocument Type="MediaIDs">
<MediaIDInfo><MediaIDs><Language ID="393239870" Name="SFX"><File Name="Keep.wav">
<WObject ID="{33333333-3333-3333-3333-333333333333}"><MediaID ID="123456"/></WObject>
</File></Language></MediaIDs></MediaIDInfo></WwiseDocument>'''.replace("123456", "654321" if wrong_media is True or wrong_media == "wrong-media-after-write" else "123456"))
                tree = ET.parse(self.unit)
                source = tree.find(".//AudioFileSource")
                source.remove(source.find("MediaIDList"))
                tree.write(self.unit)
                tree = ET.parse(self.project_file)
                ET.SubElement(tree.find("./ProjectInfo/Project/PropertyList"), "Property",
                              Name="MediaIDsInSingleFile", Type="bool", Value="True")
                tree.write(self.project_file)
                if wrong_media == "preservation":
                    self.other_unit.write_bytes(self.other_unit.read_bytes().replace(b"-6", b"-9"))
                elif wrong_media == "lost":
                    self.other_unit.unlink()
                elif wrong_media in {"new", "uppercase-after"}:
                    name = "Created.WWU" if wrong_media == "uppercase-after" else "Created.wwu"
                    (self.other_unit.parent / name).write_bytes(self.other_unit.read_bytes())
            return super().call(uri, args, options)

    # Native migrate leaves the same Console instance alive with no active project.
    client = Client(tmp_path, version, "ak.wwise.cli.moveMediaIdsToSingleFile")
    client.unit = saved_fixture_project(client)
    tree = ET.parse(client.unit)
    source = ET.SubElement(ET.SubElement(tree.find(".//Sound"), "ChildrenList"),
        "AudioFileSource", Name="Keep", ID="{33333333-3333-3333-3333-333333333333}")
    ET.SubElement(source, "Language").text = "SFX"
    ET.SubElement(source, "AudioFile").text = "Keep.wav"
    ET.SubElement(ET.SubElement(source, "MediaIDList"), "MediaID", ID="111")
    tree.write(client.unit)
    client.other_unit = client.unit.with_name("Other Work Unit.WWU" if wrong_media == "uppercase-before" else "Other Work Unit.wwu")
    other = ET.parse(client.unit)
    for node in other.iter():
        if node.get("ID"):
            node.set("ID", node.get("ID").replace("1", "7").replace("2", "8").replace("3", "9"))
    other.find(".//Sound").remove(other.find(".//Sound/ChildrenList"))
    other.write(client.other_unit)
    if wrong_media in {"overflow", "uppercase-overflow"}:
        for number in range(511):
            extension = "WWU" if wrong_media == "uppercase-overflow" else "wwu"
            (client.unit.parent / f"Extra-{number}.{extension}").write_bytes(client.other_unit.read_bytes())
    if wrong_media in {"before-write", "after-write", "wrong-media-after-write"}:
        original_open = os.open
        phase = "before" if wrong_media == "before-write" else "after"
        def failing_open(path, flags, *args, **kwargs):
            if (flags & os.O_WRONLY and f"/{phase}/files/" in Path(path).as_posix()
                    and Path(path).name == client.other_unit.name):
                raise OSError("Injected owned evidence image write failure")
            return original_open(path, flags, *args, **kwargs)
        monkeypatch.setattr(os, "open", failing_open)
    commands, media_previews = [], []

    def gateway(command, *, live):
        commands.append(list(command))
        if (wrong_media == "preview-drift" and command[:2] == ["draft-start", client.operation]
                and runtime.category_results[-1].get("model_images")):
            client.other_unit.write_bytes(client.other_unit.read_bytes().replace(b"-6", b"-9"))
        code, payload = client.run(*command)
        assert code == 0, json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if command[0] == "preview-from-draft":
            shown_code, shown = client.run("transaction-show", payload["transaction_id"])
            assert shown_code == 0, shown
            prepared = shown["artifact"]["prepared_operation"]
            if prepared["dispatch"]["uri"] == client.operation:
                link = runtime.category_results[-1]["model_images"]["before"]
                index = json.loads(Path(link["index_path"]).read_text())
                assert link["complete"] and index["complete"]
                model = {Path(relative).as_posix(): row for relative, row in
                    prepared["pre_state"]["cli_project_effect"]["model_before"]["files"].items()}
                assert set(index["files"]) == set(model)
                matches = all(row["sha256"] == model[relative]["proof"]["sha256"]
                    and row["size"] == model[relative]["proof"]["size"] for relative, row in index["files"].items())
                assert matches is (wrong_media != "preview-drift")
                media_previews.append(payload["transaction_id"])
        return payload

    runtime = SimpleNamespace(gateway=gateway, version=version, category_results=[], state_dir=tmp_path / "state",
        sandbox=SimpleNamespace(sandbox_project=client.project_file),
        restart=lambda: pytest.fail('Collector must reopen the same Console instance without a host restart'))
    collect = (workflow.test_cli_console_media_id_migrated_project_acceptance if migrated
               else workflow.test_cli_console_media_id_file_observation)
    expects_failure = wrong_media not in {False, "uppercase-before", "reopen-materialization"} or wrong_open
    if expects_failure:
        with pytest.raises(OSError if wrong_media == "before-write" else AssertionError) as failure:
            collect(runtime)
    else:
        collect(runtime)
    category, = runtime.category_results
    if wrong_open:
        assert category['status'] == 'FAIL' and 'baseline_media_pairs' not in category
        assert category['setup_migration']['status'] == 'complete'
        assert category['setup_reopen']['status'] == 'FAIL'
        assert 'setup_reopen_save' not in category
        # The existing runtime gateway asserts with the complete serialized
        # failure; pytest may append its assertion rendering to that diagnostic.
        assert 'verification_failed' in str(category['setup_reopen']['failure'])
        assert 'business_state_verified' in str(category['setup_reopen']['failure'])
        assert category['setup_reopen']['coverage_credit'] == 'none; baseline preparation only'
        assert not any(uri == client.operation for uri, _, _ in client.calls)
        assert [uri for uri, _, _ in client.calls].count(OPEN) == 1
        return
    assert category["status"] == ("FAIL" if expects_failure else "PASS")
    if wrong_media == "reopen-save-failure":
        assert category['setup_migration']['status'] == category['setup_reopen']['status'] == 'complete'
        saved = category['setup_reopen_save']
        assert saved['status'] == 'FAIL' and saved['coverage_credit'] == 'none; baseline preparation only'
        assert 'Injected reopened project save failure' in str(saved['failure'])
        assert 'model_images' not in category and 'baseline_media_pairs' not in category
        assert not media_previews and not any(uri == client.operation for uri, _, _ in client.calls)
        writes = [uri for uri, _, _ in client.calls if uri.endswith('project.save') or uri in {'ak.wwise.cli.migrate', OPEN}]
        assert writes == ['ak.wwise.core.project.save', 'ak.wwise.cli.migrate', OPEN, 'ak.wwise.core.project.save']
        assert sum(command[0] == 'execute' for command in commands) == 4
        return
    if wrong_media == "preview-drift":
        assert "MEDIA_BASELINE_PREVIEW_MISMATCH" in str(failure.value)
        assert len(media_previews) == 1 and not any(uri == client.operation for uri, _, _ in client.calls)
        assert category["model_images"]["preview_binding"]["matches_before_images"] is False
        indexes = [json.loads(Path(category["model_images"][phase]["index_path"]).read_text()) for phase in ("before", "after")]
        key = "Actor-Mixer Hierarchy/Other Work Unit.wwu"
        assert all(index["complete"] for index in indexes)
        assert indexes[0]["files"][key]["sha256"] != indexes[1]["files"][key]["sha256"]
        return
    if wrong_media in {"before-write", "overflow", "uppercase-overflow"}:
        before = category["model_images"]["before"]
        index = json.loads(Path(before["index_path"]).read_text())
        assert before["complete"] is False and index["complete"] is False
        assert index["errors"] and client.project_file.name in index["files"]
        assert not media_previews and not any(uri == client.operation for uri, _, _ in client.calls)
        assert not category["model_images"]["after"]
        return
    assert len(media_previews) == 1
    binding = category["model_images"]["preview_binding"]
    assert binding["transaction_id"] == media_previews[0] and binding["matches_before_images"] is True
    assert len(binding["artifact_hash"]) == 64
    if wrong_media == "wrong-media-after-write":
        assert 'verification_failed' in str(failure.value)
        assert 'after_capture:' not in str(failure.value)
    assert category["mapping_file"]["content_base64"]
    assert category["source_work_unit_after"]["content_base64"]
    import hashlib
    image_indexes = {}
    for phase in ("before", "after"):
        link = category["model_images"][phase]
        index_raw = Path(link["index_path"]).read_bytes()
        assert hashlib.sha256(index_raw).hexdigest() == link["sha256"]
        index = json.loads(index_raw)
        incomplete = phase == "after" and wrong_media in {"lost", "after-write", "wrong-media-after-write"}
        assert index["complete"] is not incomplete
        other_name = "Other Work Unit.WWU" if wrong_media == "uppercase-before" else "Other Work Unit.wwu"
        expected_paths = {client.project_file.name, "Actor-Mixer Hierarchy/Default Work Unit.wwu", f"Actor-Mixer Hierarchy/{other_name}"}
        if phase == "after" and wrong_media in {"new", "uppercase-after"}:
            expected_paths.add("Actor-Mixer Hierarchy/Created.WWU" if wrong_media == "uppercase-after" else "Actor-Mixer Hierarchy/Created.wwu")
        assert set(index["files"]) == expected_paths
        for relative, row in index["files"].items():
            if row["status"] != "captured":
                assert incomplete and relative.endswith("Other Work Unit.wwu")
                assert row["status"] == ("missing" if wrong_media == "lost" else "capture_error")
                continue
            raw = (Path(category["model_images"]["root"]) / row["artifact_path"]).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == row["sha256"] == row["file_proof"]["sha256"]
            assert len(raw) == row["size"]
            if phase == "after":
                assert raw == (client.project_file.parent / relative).read_bytes()
            assert "content_base64" not in row
        image_indexes[phase] = index
    assert image_indexes["before"]["files"][client.project_file.name]["sha256"] != image_indexes["after"]["files"][client.project_file.name]["sha256"]
    if wrong_media == "reopen-materialization":
        for phase in ("before", "after"):
            row = image_indexes[phase]["files"]["Actor-Mixer Hierarchy/Other Work Unit.wwu"]
            document = ET.parse(Path(category["model_images"]["root"]) / row["artifact_path"])
            state = document.find('.//MusicTrack/StateInfo/CustomStateList/CustomState')
            assert state.find("StateRef").attrib == {"Name": "None", "ID": "{4BA09D62-D59B-4880-A78C-8BECE7D7899F}"}
            assert state.find("CustomState").attrib == {"Name": "", "ID": "{B5549C79-F061-49C0-8A64-21B5617FDCDF}", "ShortID": "824120204"}
        assert client.pending_reopened_state is False
    if wrong_media == "preservation":
        key = "Actor-Mixer Hierarchy/Other Work Unit.wwu"
        assert image_indexes["before"]["files"][key]["sha256"] != image_indexes["after"]["files"][key]["sha256"]
    assert category["baseline_media_pairs"] == [["{33333333-3333-3333-3333-333333333333}", "123456"]]
    writes = [uri for uri, _, _ in client.calls if uri.endswith("project.save") or uri in {client.operation, "ak.wwise.cli.migrate", OPEN}]
    assert writes == ["ak.wwise.core.project.save", *(["ak.wwise.cli.migrate", OPEN, "ak.wwise.core.project.save"] if migrated else []), client.operation]
    assert sum(command[0] == "execute" for command in commands) == (5 if migrated else 2)
    if migrated:
        assert category["baseline_setup"] == "public_gateway_save_then_migrate_then_reopen_then_save_before_capture"
        assert category["setup_migration"]["state"] == "result_schema_checked"
        assert category["setup_migration"]["business_state_verified"] is False
        assert client.absence_errors and all(error.uri == 'ak.wwise.no_project_loaded' for error in client.absence_errors)
        assert any(error.kwargs['details']['procedureUri'] == 'ak.wwise.core.getProjectInfo' for error in client.absence_errors)
        reopened = category['setup_reopen']
        assert reopened['state'] == 'verified' and reopened['business_state_verified'] is True
        assert reopened['coverage_credit'] == 'none; baseline preparation only'
        assert reopened['project_file'] == str(client.project_file)
        code, shown = client.run('transaction-show', reopened['transaction_id'])
        assert code == 0, shown
        dispatch = shown['artifact']['prepared_operation']['dispatch']
        assert dispatch == {'uri': OPEN, 'args': {'path': str(client.project_file)}, 'options': {}}
        assert reopened['verification']['business_state_verified'] is True
        saved = category['setup_reopen_save']
        assert saved['status'] == 'complete' and saved['coverage_credit'] == 'none; baseline preparation only'
        assert saved['state'] == 'result_schema_checked' and saved['business_state_verified'] is False
        assert set(saved['responses']) == {'preview', 'execute', 'verify'}
        assert saved['transaction_id'] not in {reopened['transaction_id'], media_previews[0]}
        assert '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}' in json.dumps(reopened['verification'])
        assert str(client.project_file) in json.dumps(reopened['verification'])
    else:
        assert not client.absence_errors and 'setup_reopen' not in category


@pytest.mark.parametrize('version', ['2021.1', '2022.1'])
def test_migrated_media_collector_retains_legacy_owned_fixture_boundary_without_synthesizing_open(tmp_path, workflow, version):
    from tests.unit.test_waapi_gateway import gateway_env, waapi_gateway as gateway
    from tests.support.gateway_config import set_gateway_config
    from wwise_waapi.native_catalog import load_native_catalog
    operation = 'ak.wwise.console.project.open'
    native = load_native_catalog(version, 'wwise-console')
    assert operation not in native['functions']
    assert 'ak.wwise.ui.project.open' in native['functions']
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version=version)
    code, schema = gateway.execute_gateway(['request-schema', operation], env=env,
        client_factory=lambda _: pytest.fail('Absent public Console open discovery must stay offline'))
    assert code != 0, schema
    runtime = SimpleNamespace(version=version, category_results=[],
        sandbox=SimpleNamespace(sandbox_project=tmp_path / 'Owned.wproj'),
        gateway=lambda *a, **kw: pytest.fail('Legacy preparation must not migrate or synthesize an unavailable open URI'))
    with pytest.raises(AssertionError, match='legacy_migrated_project_reopen_fixture'):
        workflow.test_cli_console_media_id_migrated_project_acceptance(runtime)
    category, = runtime.category_results
    assert category['status'] == 'blocked' and category['boundary'] == 'legacy_migrated_project_reopen_fixture'
    assert category['media_effect'] == 'not_executed'
    assert category['selected_reopen_uri'] == operation
    assert 'ak.wwise.ui.project.open' in category['unassessed_alternative']
    assert 'owned lifecycle fixture work' in category['reason']


@pytest.mark.parametrize('version,outcome,paged', [
    (version, outcome, False) for version in ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1']
    for outcome in ['true', 'false', 'native-refusal']] + [('2025.1', 'true', True)])
def test_reference_enabled_probe_uses_actual_gateway_and_never_writes(tmp_path, workflow, version, outcome, paged):
    import re
    from copy import deepcopy
    from tests.unit.test_metadata_property_state_selection_gateway import selected_reference_task
    from tests.unit.test_metadata_discovery_gateway import (
        OBJECT_GUID, GET_INFO_URI, OBJECT_GET_URI, GET_TYPES_URI, GET_NAMES_URI,
        GET_PROPERTY_INFO_URI, IS_PROPERTY_ENABLED_URI, waapi_gateway,
    )
    run, client, _selection, reference = selected_reference_task(tmp_path, version)
    parent, platform = '{33333333-3333-3333-3333-333333333333}', '{44444444-4444-4444-4444-444444444444}'
    rows = {OBJECT_GUID: {'id': OBJECT_GUID, 'name': 'Reverb', 'type': 'AuxBus', 'classId': 3997712,
        'path': r'\Busses\Default Work Unit\Master\Reverb', 'parent': {'id': parent}},
        parent: {'id': parent, 'name': 'Master', 'type': 'Bus', 'classId': 1376272,
            'path': r'\Busses\Default Work Unit\Master', 'parent': None},
        platform: {'id': platform, 'name': 'Windows', 'type': 'Platform', 'classId': 4522000,
            'path': r'\Platforms\Windows', 'parent': None}}
    project_result = client.responses[OBJECT_GET_URI]
    def objects(args, options):
        if args == {'waql': 'from type Project take 2'}:
            return project_result
        if 'waql' in args:
            expression = args['waql']
            typed = re.fullmatch(r'from type (AuxBus|Platform) take (\d+)', expression)
            exact = re.fullmatch(r'from object "(\{[A-Fa-f0-9-]+\})"(?: take (\d+))?', expression)
            assert typed or exact, args
            selected = [rows[OBJECT_GUID if typed[1] == 'AuxBus' else platform]] if typed else [rows[exact[1]]]
        else:
            assert set(args) == {'from'} and set(args['from']) == {'id'}, args
            selected = [rows[value] for value in args['from']['id']]
        return {'return': [{key: deepcopy(row[key]) for key in options['return'] if key in row} for row in selected]}
    client.responses[OBJECT_GET_URI] = objects
    client.responses[GET_TYPES_URI] = {'return': [{'name': name, 'classId': number, 'type': 'WObject'} for name, number in
        [('AuxBus', 3997712), ('Bus', 1376272), ('Platform', 4522000)]]}
    def info(args, _options):
        assert args in ({'object': OBJECT_GUID, 'property': 'UserAuxSend0'}, {'classId': 3997712, 'property': 'UserAuxSend0'}), args
        return deepcopy(reference)
    client.responses[GET_PROPERTY_INFO_URI] = info
    if paged:
        client.responses[GET_NAMES_URI]['return'] = [f'Unrelated{i}' for i in range(64)] + client.responses[GET_NAMES_URI]['return']
    client.responses[IS_PROPERTY_ENABLED_URI] = {'return': outcome == 'true'}
    if outcome == 'native-refusal':
        class WaapiRequestFailed(Exception):
            uri = 'ak.wwise.invalid_arguments'
            kwargs = {'details': {'property': 'UserAuxSend0', 'procedureUri': IS_PROPERTY_ENABLED_URI}, 'message': 'Native reference probe refused'}
        client.errors[IS_PROPERTY_ENABLED_URI] = WaapiRequestFailed('reference probe refused')
    config = tmp_path / 'config' / 'config.json'
    settings = json.loads(config.read_text())
    settings['project_modification_policy'] = 'read_only'
    config.write_text(json.dumps(settings))
    evidence = tmp_path / 'evidence'
    evidence.mkdir(exist_ok=True)
    env = {'WAAPI_SKILL_CONFIG_PATH': str(config), 'WWISE_EVIDENCE_DIR': str(evidence)}
    commands = []
    runtime = SimpleNamespace(version=version, candidate='unit-fixture-not-native', state_dir=tmp_path / 'probe-state',
        env=env, category_results=[], port=31337, lifecycle=SimpleNamespace(host='127.0.0.1', waapi_url='ws://127.0.0.1:31337/waapi'))
    def raw_gateway(command):
        commands.append(list(command))
        return waapi_gateway.execute_gateway(['--state-dir', str(runtime.state_dir), *command], env=env, client_factory=lambda _url: client)
    runtime.raw_gateway = raw_gateway
    result = workflow._collect_reference_enabled_metadata_probe(runtime)
    receipt = json.loads((runtime.state_dir / 'reference-enabled-metadata-observation.json').read_text())
    assert result['status'] == ('FAIL' if outcome == 'native-refusal' else 'PASS'), receipt
    assert receipt['mutation_authority'] is receipt['prospective_authority'] is receipt['business_effect_verified'] is False
    assert receipt['controller_name_absence']['class'] is receipt['controller_name_absence']['object'] is True
    assert receipt['class_field']['metadata']['type'] == receipt['object_field']['metadata']['type'] == ''
    assert len([call for call in client.calls if call[0] == IS_PROPERTY_ENABLED_URI]) == 1
    assert [call[1] for call in client.calls if call[0] == IS_PROPERTY_ENABLED_URI] == [
        {'object': OBJECT_GUID, 'property': 'UserAuxSend0', 'platform': platform}]
    assert all(command[0] in {'metadata', 'query-object'} for command in commands)
    if outcome == 'native-refusal':
        assert receipt['enabled_response']['payload']['call']['waapi_error_uri'] == 'ak.wwise.invalid_arguments'
    else:
        assert receipt['observed_enabled'] is (outcome == 'true')


def _rtpc_2021_representation_runtime(tmp_path, workflow, *, fault=None):
    """Actual public Gateway; internal-class facts below are synthetic protocol data."""
    from copy import deepcopy
    import re
    from tests.unit.test_metadata_discovery_gateway import (
        FakeClient, _gateway_env, _live_info, _project_row, GET_INFO_URI, OBJECT_GET_URI,
        GET_TYPES_URI, GET_NAMES_URI, GET_PROPERTY_INFO_URI,
    )
    sound = '{9EEFCC8E-7FC2-4CDC-8BE9-C682F2CA77CC}'
    rtpc = '{A809A571-6012-42BE-A00D-D8E7C89D1248}'
    curve = '{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}'
    objects = {
        sound: {'id': sound, 'name': 'Outside_Idle_1000', 'type': 'Sound',
            'path': r'\Actor-Mixer Hierarchy\Car Engine\Outside_Idle_1000', 'classId': 65552,
            'parent': None, 'owner': None},
        # No native2021 class ID or path claim: this is injected boundary data.
        rtpc: {'id': rtpc, 'name': '', 'type': 'RTPC', 'path': '', 'classId': 424242,
            'parent': None, 'owner': {'id': sound}},
        curve: {'id': curve, 'name': '', 'type': 'Curve', 'path': '', 'classId': 917520,
            'parent': None, 'owner': {'id': rtpc}},
    }
    if fault == 'omission':
        objects[rtpc].pop('classId')
        objects[rtpc].pop('owner')
    fields = {sound: ['Volume'], rtpc: ['Curve', 'ControlInput', 'PropertyName']}
    if fault == 'many-details':
        fields[rtpc] = ['Curve'] + [f'ControlInput{n}' for n in range(8)]
    if fault == 'pages':
        fields[rtpc] = [f'Unrelated{n:03}' for n in range(257)]
    if fault == 'no-curve-disclosure':
        fields[rtpc] = ['ControlInput']
    env = _gateway_env(tmp_path, version='2021.1')
    config = Path(env['WAAPI_SKILL_CONFIG_PATH'])
    settings = json.loads(config.read_text());settings['project_modification_policy'] = 'read_only'
    config.write_text(json.dumps(settings))
    evidence = Path(env['WWISE_EVIDENCE_DIR']);evidence.mkdir()
    dispatches, commands = [], []
    def get(args, options):
        dispatches.append((deepcopy(args), deepcopy(options)))
        expression = args.get('waql', '')
        if expression == 'from type Project take 1':
            return {'return': [_project_row(tmp_path)]}
        match = re.fullmatch(r'from object "(\{[A-Fa-f0-9-]+\})"(?: select @Curve)?(?: take \d+)?', expression)
        if match:
            identity = match[1]
            if identity == rtpc and fault == 'missing':
                return {'return': []}
            selected = [objects[curve if 'select @Curve' in expression else identity]]
        else:
            assert args.keys() == {'from'} and args['from'].keys() == {'id'}, args
            selected = [objects[identity] for identity in args['from']['id']]
        return {'return': [{key: deepcopy(row[key]) for key in options['return'] if key in row} for row in selected]}
    def names(args, _options):
        if fault == 'names-error' and args['object'] == rtpc:
            class WaapiRequestFailed(Exception):
                uri = 'ak.wwise.invalid_arguments'
                kwargs = {'message': 'Exact internal metadata refused; original detail',
                    'details': {'object': rtpc, 'original': None}}
            raise WaapiRequestFailed('Exact internal metadata refused; original detail')
        return {'return': fields[args['object']]}
    def info(args, _options):
        assert args['property'] in fields[args['object']]
        if args['property'] == 'Curve':
            # Preserve metadata name/type omission; reference restriction is explicit.
            return {'restriction': {'type': 'reference', 'restrictions': [{'type': ['Curve']}]},
                'nativeOptionalNull': None}
        return {'type': 'string', 'nativeOptionalNull': None}
    live_info = _live_info('2021.1')
    live_info['version']['minor'] = 14
    client = FakeClient({GET_INFO_URI: live_info, OBJECT_GET_URI: get,
        GET_TYPES_URI: {'return': [{'name': 'Sound', 'classId': 65552, 'type': 'WObject'}]},
        GET_NAMES_URI: names, GET_PROPERTY_INFO_URI: info})
    runtime = SimpleNamespace(version='2021.1', candidate='synthetic-program-control',
        state_dir=tmp_path / 'state', env=env, category_results=[], port=31337,
        lifecycle=SimpleNamespace(host='127.0.0.1', waapi_url='ws://127.0.0.1:31337/waapi'))
    def raw(command):
        commands.append(list(command))
        return workflow.waapi_gateway.execute_gateway(['--state-dir', str(runtime.state_dir), *command],
            env=env, client_factory=lambda _url: client)
    runtime.raw_gateway = raw
    return runtime, commands, client, dispatches, objects


@pytest.mark.parametrize('fault', [None, 'missing', 'names-error'])
def test_rtpc_2021_representation_probe_uses_public_scope_and_retains_boundaries(tmp_path, workflow, fault):
    runtime, commands, client, dispatches, objects = _rtpc_2021_representation_runtime(tmp_path, workflow, fault=fault)
    workflow.test_gateway_2021_rtpc_representation_diagnostic(runtime)
    result, = runtime.category_results
    receipt = json.loads(Path(result['observation_path']).read_text())
    assert result['status'] == 'blocked' and result['diagnostic_only'] is True
    assert receipt['collection_complete'] is True
    assert receipt['mutation_authority'] is receipt['business_effect_verified'] is False
    assert receipt['native_absence_proven'] is False
    assert receipt['version'] == '2021.1' and receipt['source']['sdk_build'] == '2021.1.14.8108'
    assert all(command[0] in {'config-show', 'status', 'query-schema', 'query-object', 'metadata'} for command in commands)
    assert {uri for uri, _args, _options in client.calls} <= {
        'ak.wwise.core.getInfo', 'ak.wwise.core.object.get', 'ak.wwise.core.object.getTypes',
        'ak.wwise.core.object.getPropertyAndReferenceNames', 'ak.wwise.core.object.getPropertyInfo'}
    rtpc = receipt['objects'][1]
    assert rtpc['requested_id'] == '{A809A571-6012-42BE-A00D-D8E7C89D1248}'
    if fault == 'missing':
        assert rtpc['identity_rows'] == [] and rtpc['names_complete'] is False
        assert any(row['reason'] == 'exact_internal_identity_not_observed' for row in receipt['boundaries'])
    elif fault == 'names-error':
        failed = [call for call in receipt['calls'] if call['exit_code'] != 0]
        assert len(failed) == 1 and failed[0]['payload']['error_code'] == 'LIVE_METADATA_READ_FAILED'
        assert failed[0]['payload']['details']['uri'] == 'ak.wwise.core.object.getPropertyAndReferenceNames'
        assert any(row['reason'] == 'public_read_rejected' for row in receipt['boundaries'])
        assert rtpc['names_complete'] is False
    else:
        assert rtpc['identity_rows'][0]['class_id'] == 424242
        assert rtpc['names_complete'] is True and rtpc['field_names'] == ['ControlInput', 'Curve', 'PropertyName']
        detail = next(row for row in receipt['field_details'] if row['disclosed_field'] == 'Curve')
        metadata = detail['pages'][0]['metadata']
        assert 'name' not in metadata and 'type' not in metadata and metadata['nativeOptionalNull'] is None
        assert len(receipt['relationship_reads']) == 2
        assert any('select @Curve' in args.get('waql', '') for args, _ in dispatches)
    assert not any('curve-points' in command or any('RTPCList' in item for item in command) for command in commands)


@pytest.mark.parametrize('fault', ['many-details', 'no-curve-disclosure', 'pages', 'omission'])
def test_rtpc_2021_representation_probe_keeps_discovery_and_observation_bounds(tmp_path, workflow, fault):
    runtime, commands, client, _dispatches, _objects = _rtpc_2021_representation_runtime(tmp_path, workflow, fault=fault)
    if fault == 'pages':
        with pytest.raises(AssertionError, match='four pages'):
            workflow._collect_2021_rtpc_representation_diagnostic(runtime)
    else:
        workflow._collect_2021_rtpc_representation_diagnostic(runtime)
    result, = runtime.category_results
    report = json.loads(Path(result['observation_path']).read_text())
    assert len(commands) <= 32
    assert len(report['field_details']) <= 6 and len(report['relationship_reads']) <= 2
    assert all(uri in {'ak.wwise.core.getInfo', 'ak.wwise.core.object.get', 'ak.wwise.core.object.getTypes',
        'ak.wwise.core.object.getPropertyAndReferenceNames', 'ak.wwise.core.object.getPropertyInfo'}
        for uri, _args, _options in client.calls)
    if fault == 'pages':
        assert result['status'] == 'FAIL' and report['collection_complete'] is False
        assert len(report['objects'][1]['field_names']) == 256 and report['objects'][1]['names_complete'] is False
        assert 'four pages' in report['failure']['message']
    else:
        assert result['status'] == 'blocked' and report['collection_complete'] is True
        if fault == 'many-details':
            assert len(report['objects'][1]['field_names']) == 9 and report['objects'][1]['names_complete'] is True
            assert len(report['field_details']) == 6 and report['detail_limit_reached'] is True
        elif fault == 'no-curve-disclosure':
            assert not any('--advanced-waql' in command for command in commands)
            assert [row['stage'] for row in report['relationship_reads']] == ['returned-RTPC-owner']
        elif fault == 'omission':
            assert 'class_id' not in report['objects'][1]['identity_rows'][0]
            assert any(row['reason'] == 'identity_output_omitted' and row['field'] == 'class_id' for row in report['boundaries'])


@pytest.mark.parametrize('version', ['2022.1', '2023.1', '2024.1', '2025.1'])
def test_rtpc_2021_representation_probe_does_not_apply_source_identity_to_other_versions(tmp_path, workflow, version):
    runtime, commands, _client, _dispatches, _objects = _rtpc_2021_representation_runtime(tmp_path, workflow)
    runtime.version = version
    with pytest.raises(AssertionError, match='pinned'):
        workflow._collect_2021_rtpc_representation_diagnostic(runtime)
    assert commands == [] and runtime.category_results == []


def test_rtpc_2021_representation_probe_stops_before_source_reads_on_wrong_build(tmp_path, workflow):
    runtime, commands, client, _dispatches, _objects = _rtpc_2021_representation_runtime(tmp_path, workflow)
    client.responses['ak.wwise.core.getInfo']['version']['build'] = 8109
    with pytest.raises(AssertionError, match='build'):
        workflow._collect_2021_rtpc_representation_diagnostic(runtime)
    report = json.loads(Path(runtime.category_results[0]['observation_path']).read_text())
    assert report['collection_complete'] is False and report['runtime_version_observed']['build'] == 8109
    assert not any(command[0] in {'query-object', 'metadata'} for command in commands)
    assert runtime.category_results[0]['status'] == 'FAIL'


def _rtpc_graph_runtime(tmp_path, workflow, version='2025.1', *, fault=None, exclusive=True):
    """Actual Gateway; source-shaped native graph state, not native receipts."""
    from copy import deepcopy
    import uuid
    from tests.unit.test_unnamed_rtpc_graph_gateway import rtpc_task
    task, _ = rtpc_task(tmp_path, version)
    actor, parameters = ('{' + str(uuid.UUID(int=n)).upper() + '}' for n in (101, 102))
    actor_path = ('\\Containers' if version == '2025.1' else '\\Actor-Mixer Hierarchy') + '\\Default Work Unit'
    task.objects = {identity: {'id': identity, 'name': 'Default Work Unit', 'type': 'WorkUnit',
        'classId': 1638416, 'path': path, 'parent': None, 'notes': 'Keep work unit'}
        for identity, path in [(actor, actor_path), (parameters, r'\Game Parameters\Default Work Unit')]}
    task.metadata.update({
        'Min': {'name': 'Min', 'type': 'Real64', 'default': -10},
        'Max': {'name': 'Max', 'type': 'Real64', 'default': 90},
        'CenterPercentage': {'name': 'CenterPercentage', 'type': 'int32', 'default': 0,
            'supports': {'rtpc': 'Exclusive' if exclusive else 'None'},
            'restriction': {'type': 'range', 'min': 0, 'max': 100}}})
    fields = {'Sound': ['Volume', 'Pitch', 'CenterPercentage'], 'GameParameter': ['Min', 'Max'],
        'RTPC': ['PropertyName', 'ControlInput', 'Curve'], 'Curve': [], 'WorkUnit': []}
    if fault in {'names-overflow', 'paged-sound-fields'}:
        fields['Sound'] = ['Volume', 'Pitch', 'CenterPercentage'] + [f'Other{i:03}' for i in range(254 if fault == 'names-overflow' else 108)]
    original, writes, commands = task.call, [], []
    next_id = 201
    def allocate():
        nonlocal next_id
        next_id += 1
        return '{' + str(uuid.UUID(int=next_id)).upper() + '}'
    def create(node, parent, *, owned=False):
        matches = [row for row in task.objects.values() if row.get('parent') == {'id': parent}
            and row['name'] == node['name'] and row['type'] == node['type']]
        if matches and task.conflict != 'merge': raise ValueError('Native name collision requires selected merge')
        row = matches[0] if matches else None
        if row is None:
            if fault == 'replacement-nonlexicographic-guids' and owned and node['type'] == 'RTPC' and task.list_mode == 'replaceAll':
                identity = '{' + str(uuid.UUID(int=902 if node['@PropertyName'] == 'Volume' else 901)).upper() + '}'
            else:
                identity = allocate()
            row = {'id': identity, 'name': node['name'], 'type': node['type'],
                'classId': next(entry['classId'] for entry in task.types if entry['name'] == node['type']),
                'path': ('\\opaque-' + identity if owned else task.objects[parent]['path'] + '\\' + node['name']),
                'notes': node.get('notes', ''), **({'owner': {'id': parent}} if owned else {'parent': {'id': parent}})}
            if node['type'] == 'Sound':
                row.update({'@RTPC': [], '@Volume': 0, '@Pitch': 0, '@CenterPercentage': 0})
            if node['type'] == 'GameParameter':
                row.update({'@Min': -10 if node['name'].endswith('_A') else 20, '@Max': 90 if node['name'].endswith('_A') else 220})
                if fault == 'invalid-range': row['@Min'] = row['@Max']
            task.objects[identity] = row
        return apply(node, row)
    def apply(node, row):
        result = {'id': row['id'], 'name': row['name']}
        if 'notes' in node: row['notes'] = node['notes']
        if 'children' in node:
            result['children'] = [create(child, row['id']) for child in node['children']]
        if '@RTPC' in node:
            if task.list_mode == 'replaceAll':
                for old in row['@RTPC']:
                    curve_id = task.objects[old['id']]['@Curve']['id']
                    del task.objects[curve_id]; del task.objects[old['id']]
                row['@RTPC'] = []
            result['@RTPC'] = []
            for child in node['@RTPC']:
                member = create(child, row['id'], owned=True)
                row['@RTPC'].append({'id': member['id']})
                result['@RTPC'].append(member)
        if '@PropertyName' in node: row['@PropertyName'] = node['@PropertyName']
        if '@ControlInput' in node: row['@ControlInput'] = {'id': node['@ControlInput']}
        if '@Curve' in node:
            curve = row.get('@Curve', {}).get('id') or allocate()
            points = deepcopy(node['@Curve']['points'])
            row['@Curve'] = {'id': curve, 'points': points}
            task.objects[curve] = {'id': curve, 'name': '', 'type': 'Curve', 'classId': 917520,
                'path': '\\opaque-curve-' + curve, 'owner': {'id': row['id']}, 'notes': '', 'points': deepcopy(points)}
            if fault == 'curve-owner-sound': task.objects[curve]['owner'] = deepcopy(row['owner'])
            elif fault == 'curve-owner-omitted': task.objects[curve].pop('owner')
        return result
    def call(uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri.endswith('getProjectInfo'):
            return {**original(uri, args, options), 'currentPlatformId': '{55555555-5555-5555-5555-555555555555}'}
        if uri.endswith('isPropertyEnabled'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            if fault in {'exclusive-disabled-after-create', 'exclusive-state-read-error'} and args['property'] == 'CenterPercentage':
                # Literal native28dc transition: the base scalar becomes disabled
                # once this Exclusive RTPC exists; its Curve remains a distinct edit.
                controlled = any(row.get('@PropertyName') == 'CenterPercentage' for row in task.objects.values())
                if controlled and fault == 'exclusive-state-read-error': return {'return': 'unavailable'}
                return {'return': not controlled}
            return {'return': True}
        if uri.endswith(('getPropertyAndReferenceNames', 'getPropertyInfo')):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            if uri.endswith('getPropertyInfo'): return deepcopy(task.metadata[args['property']])
            kind = task.objects[args['object']]['type'] if 'object' in args else next(t['name'] for t in task.types if t['classId'] == args['classId'])
            return {'return': fields[kind]}
        if uri.endswith('object.set'):
            task.calls.append((uri, deepcopy(args), deepcopy(options))); writes.append(deepcopy(args))
            task.list_mode = args.get('listMode', 'append')
            task.conflict = args.get('onNameConflict', 'fail')
            results = []
            for node in args['objects']:
                target = task.objects[node['object']]
                result = apply(node, target)
                # Native field-only rows may have no result association.
                if target['type'] != 'RTPC': results.append(result)
            return {'objects': results}
        if uri.endswith('object.get') and args.get('waql') != 'from type Project take 1':
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            expression = args.get('waql', '')
            source = args.get('from', {})
            if expression:
                assert expression.startswith('from object "'), expression
                identity = expression.split('"')[1]
                rows = [row for row in task.objects.values() if identity in (row['id'], row['path'])]
                if 'select @RTPC' in expression:
                    rows = [task.objects[item['id']] for item in rows[0]['@RTPC']]
                elif 'select @Curve' in expression:
                    rows = [task.objects[rows[0]['@Curve']['id']]]
            elif 'id' in source: rows = [task.objects[key] for key in source['id'] if key in task.objects]
            else: rows = [row for row in task.objects.values() if row['path'] in source['path']]
            for transform in args.get('transform', []):
                token = transform['select'][0]
                if token == 'children': rows = [row for row in task.objects.values() if row.get('parent') == {'id': rows[0]['id']}]
                elif token == 'descendants': rows = [row for row in task.objects.values() if row['path'].startswith(rows[0]['path'] + '\\')]
                else: raise AssertionError(transform)
            return {'return': [{key: deepcopy(row.get(key, row.get('@' + key))) for key in options['return']
                if key in row or '@' + key in row} for row in rows]}
        return original(uri, args, options)
    task.call = call
    runtime = SimpleNamespace(version=version, state_dir=tmp_path / 'state', env=task.env,
        candidate='fixture-candidate', category_results=[])
    def raw(command):
        commands.append(list(command))
        code, payload = workflow.waapi_gateway.execute_gateway(['--state-dir', str(runtime.state_dir), *command],
            env=runtime.env, client_factory=lambda _url: task)
        if fault == 'identity-drift' and command[0] == 'query-object' and '--path-segment' in command and 'WAAPI_RTPC_TEST' in command:
            created = next(row for row in task.objects.values() if row['name'] == 'WAAPI_RTPC_TEST')
            created.update(name='Changed between path and exact ID', path=created['path'] + '_Changed')
        if command[0] == 'verify' and code == 0 and len(writes) == 3 and fault:
            owner = next(row for row in task.objects.values() if row['name'] == 'WAAPI_RTPC_TEST')
            members = [task.objects[row['id']] for row in owner['@RTPC']]
            spare, selected = members[0], members[1]
            if fault == 'wrong-pair': selected['@ControlInput'] = deepcopy(members[2]['@ControlInput'])
            elif fault == 'spare-curve':
                spare['@Curve']['points'][0]['y'] += 1
                task.objects[spare['@Curve']['id']]['points'] = deepcopy(spare['@Curve']['points'])
            elif fault == 'owner-property': owner['@Volume'] = 7
            elif fault == 'spare-curve-owner': task.objects[spare['@Curve']['id']]['owner'] = {'id': parameters}
            elif fault == 'missing-member': owner['@RTPC'].pop(0)
            elif fault == 'wrong-owner': selected['owner'] = {'id': parameters}
        return code, payload
    runtime.raw_gateway = raw
    return runtime, commands, writes, task


@pytest.mark.parametrize('version', ['2022.1', '2023.1', '2024.1', '2025.1'])
def test_rtpc_graph_collector_groups_real_public_effects_and_preserves_spare(tmp_path, workflow, version):
    runtime, commands, writes, _task = _rtpc_graph_runtime(tmp_path, workflow, version)
    category = workflow._collect_rtpc_graph_acceptance(runtime, name='WAAPI_RTPC_TEST')
    assert category['status'] == 'PASS'
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert receipt['business_effect_verified'] is True and receipt['setup_coverage_credit'] is False
    assert len(writes) == 6 and [cmd[0] for cmd in commands].count('verify') == 6
    assert len(receipt['effects']) == 5 and all(row['effect_verified'] for row in receipt['effects'])
    assert receipt['exclusive']['status'] == 'observed_and_conflict_rejected'
    assert receipt['effects'][1]['independent_effect']['members'][0] == receipt['effects'][0]['independent_effect']['members'][0]
    assert {row['source_range']['minimum'] for row in receipt['controls']} == {-10, 20}


@pytest.mark.parametrize('fault', ['wrong-pair', 'spare-curve', 'missing-member', 'wrong-owner', 'spare-curve-owner', 'owner-property'])
def test_rtpc_graph_collector_independent_read_rejects_damage_after_gateway_verifies(tmp_path, workflow, fault):
    runtime, commands, writes, _task = _rtpc_graph_runtime(tmp_path, workflow, fault=fault)
    with pytest.raises(AssertionError):
        workflow._collect_rtpc_graph_acceptance(runtime, name='WAAPI_RTPC_TEST')
    receipt = json.loads((runtime.state_dir / 'rtpc-graph-acceptance.json').read_text())
    assert runtime.category_results[0]['status'] == 'FAIL' and receipt['business_effect_verified'] is False
    assert len(writes) == 3 and [cmd[0] for cmd in commands].count('verify') == 3
    assert receipt['effects'][1]['verify']['payload']['verification']['business_state_verified'] is True
    assert receipt['effects'][1]['effect_verified'] is False and receipt['failure']
    assert len(receipt['calls']) <= 384


def test_rtpc_graph_collector_records_pending_exclusive_without_manufacturing_witness(tmp_path, workflow):
    runtime, _commands, writes, _task = _rtpc_graph_runtime(tmp_path, workflow, exclusive=False)
    category = workflow._collect_rtpc_graph_acceptance(runtime, name='WAAPI_RTPC_TEST')
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert category['status'] == 'PASS' and len(writes) == 6
    assert receipt['exclusive']['status'] == 'pending' and 'rejection' not in receipt['exclusive']
    pending, = [row for row in runtime.category_results if row['category'] == 'rtpc-graph-exclusive-cardinality']
    assert pending['status'] == 'blocked'


def test_rtpc_graph_collector_never_constructs_2021_modern_graph(tmp_path, workflow):
    commands, writes = [], []
    runtime = SimpleNamespace(version='2021.1', state_dir=tmp_path / 'state', candidate='fixture-candidate', category_results=[])
    runtime.raw_gateway = lambda command: commands.append(command)
    with pytest.raises(AssertionError, match='No fabricated 2021'):
        workflow._collect_rtpc_graph_acceptance(runtime, name='WAAPI_RTPC_TEST')
    assert commands == [] and writes == [] and runtime.category_results[0]['status'] == 'FAIL'


@pytest.mark.parametrize('fault', ['names-overflow', 'invalid-range', 'identity-drift'])
def test_rtpc_graph_collector_discovery_and_range_bounds_prevent_effect_credit(tmp_path, workflow, fault):
    runtime, commands, writes, _task = _rtpc_graph_runtime(tmp_path, workflow, fault=fault)
    with pytest.raises(AssertionError):
        workflow._collect_rtpc_graph_acceptance(runtime, name='WAAPI_RTPC_TEST')
    receipt = json.loads((runtime.state_dir / 'rtpc-graph-acceptance.json').read_text())
    assert runtime.category_results[0]['status'] == 'FAIL' and receipt['complete'] is False
    assert receipt['business_effect_verified'] is False and receipt['effects'] == []
    assert len(writes) == 1 and [cmd[0] for cmd in commands].count('verify') == 1
    assert receipt['failure'] and len(receipt['calls']) <= 384


@pytest.mark.parametrize('fault', ['curve-owner-sound', 'curve-owner-omitted'])
def test_rtpc_graph_collector_preserves_observed_curve_owner_and_omission(tmp_path, workflow, fault):
    runtime, _commands, writes, _task = _rtpc_graph_runtime(tmp_path, workflow, fault=fault)
    category = workflow._collect_rtpc_graph_acceptance(runtime, name='WAAPI_RTPC_TEST')
    assert category['status'] == 'PASS' and len(writes) == 6
    receipt = json.loads(Path(category['observation_path']).read_text())
    observed = receipt['effects'][0]['independent_effect']
    curve = observed['members'][0]['curve']
    if fault == 'curve-owner-omitted': assert 'owner' not in curve
    else: assert curve['owner']['id'] == observed['owner']['id']
    assert receipt['effects'][1]['independent_effect']['members'][0]['curve'] == curve
    assert receipt['complete'] is True
    assert len(receipt['calls']) <= 384 and Path(category['observation_path']).stat().st_size <= 16 * 1024 * 1024


def test_rtpc_graph_collector_selects_observed_fields_beyond_first_draft_page(tmp_path, workflow):
    runtime, _commands, writes, _task = _rtpc_graph_runtime(tmp_path, workflow, fault='paged-sound-fields')
    category = workflow._collect_rtpc_graph_acceptance(runtime, name='WAAPI_RTPC_TEST')
    assert category['status'] == 'PASS' and len(writes) == 6
    receipt = json.loads(Path(category['observation_path']).read_text())
    owner = receipt['effects'][0]['independent_effect']['owner']['id']
    assert len(receipt['metadata'][owner]['names']) == 111
    assert receipt['documented_list']['field_kind'] == 'list'


@pytest.mark.parametrize('failed_effect', [False, True])
def test_rtpc_graph_collector_categories_survive_existing_exact_finalizer(tmp_path, workflow, monkeypatch, failed_effect):
    runtime, _commands, _writes, _task = _rtpc_graph_runtime(tmp_path / 'collector', workflow,
        version='2023.1', exclusive=False, fault='wrong-pair' if failed_effect else None)
    if failed_effect:
        with pytest.raises(AssertionError):
            workflow._collect_rtpc_graph_acceptance(runtime, name='WAAPI_RTPC_TEST')
        receipt = json.loads((runtime.state_dir / 'rtpc-graph-acceptance.json').read_text())
        phase = next(row for row in receipt['effects'] if row['phase'] == 'exact_update_and_append')
        assert phase['execute']['exit_code'] == phase['verify']['exit_code'] == 0
        assert phase['verify']['payload']['verification']['business_state_verified'] is True
        assert phase['effect_verified'] is False and len(_writes) == 3
    else:
        workflow._collect_rtpc_graph_acceptance(runtime, name='WAAPI_RTPC_TEST')
    (tmp_path / 'lifecycle').mkdir()
    fixture, events, records = _fixture_run(tmp_path / 'lifecycle', workflow, monkeypatch)
    from tests.destructive.support import category_evidence
    target = tmp_path / 'category.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(target))
    monkeypatch.setattr(exact_real_evidence, 'append_category_evidence', category_evidence.append_category_evidence)
    fixture_runtime = next(fixture)
    fixture_runtime.category_results.extend(runtime.category_results)
    with pytest.raises(StopIteration):
        next(fixture)
    retained_rows = [json.loads(line) for line in target.read_text().splitlines()]
    assert retained_rows[-1]['invocation']['phase'] == 'final'
    retained = retained_rows[-1]['categories']
    phases = [row for row in retained if row['category'].startswith('rtpc-graph-')]
    assert phases and all(row['verifier_strength'] for row in phases)
    assert any(row['status'] == ('FAIL' if failed_effect else 'blocked') for row in phases)
    assert events.index('shutdown') < events.index('release')


def test_rtpc_graph_collector_updates_existing_exclusive_curve_after_base_field_disables(tmp_path, workflow):
    runtime, _commands, writes, _task = _rtpc_graph_runtime(
        tmp_path, workflow, fault='exclusive-disabled-after-create')
    category = workflow._collect_rtpc_graph_acceptance(runtime, name='WAAPI_RTPC_TEST')
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert category['status'] == 'PASS' and receipt['complete'] is True
    assert len(writes) == 6  # One setup and five separately previewed effects.
    observed = [row['payload']['agent_result']['enabled'] for row in receipt['enabled_observations']
        if row['field'] == 'CenterPercentage']
    assert observed == [True, False]
    first, second = receipt['effects'][:2]
    existing = first['independent_effect']['members'][1]['object']['id']
    assert second['independent_effect']['members'][1]['object']['id'] == existing
    assert any(row.get('object') == existing and '@Curve' in row for row in writes[2]['objects'])
    assert receipt['exclusive']['status'] == 'observed_and_conflict_rejected'
    assert receipt['exclusive']['rejection']['payload']['error_code'] == 'RTPC_EXCLUSIVE_CONFLICT'
    assert receipt['exclusive']['reason'] != 'No legal active source-backed Exclusive field proved'


def test_rtpc_graph_collector_stops_before_update_when_base_state_read_fails(tmp_path, workflow):
    runtime, commands, writes, _task = _rtpc_graph_runtime(
        tmp_path, workflow, fault='exclusive-state-read-error')
    with pytest.raises(AssertionError):
        workflow._collect_rtpc_graph_acceptance(runtime, name='WAAPI_RTPC_TEST')
    receipt = json.loads((runtime.state_dir / 'rtpc-graph-acceptance.json').read_text())
    assert len(writes) == 2  # Setup and first verified effect; no second mutation.
    assert [command[0] for command in commands].count('verify') == 2
    assert len(receipt['effects']) == 1 and receipt['complete'] is False
    assert receipt['enabled_observations'][-1]['exit_code'] != 0
    assert runtime.category_results[0]['status'] == 'FAIL'


def test_rtpc_graph_collector_preserves_nonlexicographic_replacement_accessor_order(tmp_path, workflow):
    runtime, _commands, writes, _task = _rtpc_graph_runtime(
        tmp_path, workflow, fault='replacement-nonlexicographic-guids')
    category = workflow._collect_rtpc_graph_acceptance(runtime, name='WAAPI_RTPC_TEST')
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert category['status'] == 'PASS' and receipt['complete'] is True and len(writes) == 6
    replacement = receipt['effects'][-1]
    assert replacement['phase'] == 'replace_all' and replacement['effect_verified'] is True
    members = replacement['independent_effect']['members']
    assert [row['pair'][0] for row in members] == ['Volume', 'CenterPercentage']
    assert members[0]['object']['id'] > members[1]['object']['id']
    assert [node['@PropertyName'] for node in writes[-1]['objects'][0]['@RTPC']] == ['Volume', 'CenterPercentage']


def _anonymous_effect_construction_runtime(tmp_path, workflow, *, fault=None, version='2025.1'):
    """Actual public Gateway; source-shaped native boundary, never a collector success stub."""
    from copy import deepcopy
    import uuid
    from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, SECOND
    from tests.unit.test_list_merge_existing_conditions_gateway import EFFECT_PARENT
    task = OwnedGraphTask(tmp_path, version, 'object.set')
    task.types = [{'name': name, 'classId': value, 'type': kind} for name, value, kind in (
        ('Sound', 65552, 'WObject'), ('Folder', 131088, 'WObject'), ('WorkUnit', 1638416, 'WObject'),
        ('EffectSlot', 5505040, 'WObject'), ('Wwise Gain', 9109507, 'Effect'))]
    task.objects = {identity: {'id': identity, 'name': 'Default Work Unit', 'type': 'WorkUnit',
        'classId': 1638416, 'path': path, 'notes': 'Keep WorkUnit'} for identity, path in (
            (SECOND, ('\\Containers' if version == '2025.1' else '\\Actor-Mixer Hierarchy') + r'\Default Work Unit'),
            (EFFECT_PARENT, r'\Effects\Default Work Unit'))}
    task.metadata = {'Effect': {'name': 'Effect', 'type': '', 'default': None,
        'restriction': {'type': 'reference', 'restrictions': [{'type': ['Effect']}]}}}
    for name in ('Bypass', 'Render'):
        task.metadata[name] = {'name': name, 'type': 'bool', 'default': False,
            'dependencies': [{'type': 'reference', 'action': 'Enable', 'context': 'Self', 'property': 'Effect',
                'conditions': [{'referenceIsSet': True}]}]}
    original, writes, commands, next_id = task.call, [], [], 100
    def identity():
        nonlocal next_id
        next_id += 1
        return '{' + str(uuid.UUID(int=next_id)).upper() + '}'
    def named(node, parent):
        assert node['type'] in {'Sound', 'Folder', 'Effect'} and node['name'], node
        created = identity()
        class_id = {'Sound': 65552, 'Folder': 131088, 'Effect': 9109507}[node['type']]
        if node['type'] == 'Effect': assert node['classId'] == class_id, node
        row = {'id': created, 'name': node['name'], 'type': node['type'], 'classId': class_id,
            'path': task.objects[parent]['path'] + '\\' + node['name'], 'parent': {'id': parent}, 'notes': node.get('notes', '')}
        if node['type'] == 'Sound': row.update({'@IsVoice': False, '@Effects': []})
        if node['type'] == 'Effect': row.update({'@FullBandGain': 0.0, '@LFEGain': 0.0})
        task.objects[created] = row
        result = {'id': created, 'name': row['name']}
        if '@Effects' in node: result['@Effects'] = slots(node['@Effects'], created, 'append')
        return result
    def slots(nodes, owner, mode):
        if mode == 'replaceAll':
            for old in task.objects[owner]['@Effects']:
                task.objects.pop(old['id'])
            task.objects[owner]['@Effects'] = []
        results = []
        for index, node in enumerate(nodes):
            assert node['type'] == 'EffectSlot' and node['name'] == '', node
            slot = identity()
            reference = node['@Effect']
            if isinstance(reference, dict):
                assert reference['type'] == 'Effect' and reference['classId'] == 9109507, reference
                effect = identity()
                task.objects[effect] = {'id': effect, 'name': reference['name'], 'type': 'Effect', 'classId': 9109507,
                    'owner': {'id': slot}, 'path': '\\opaque-local-' + effect, 'notes': reference.get('notes', ''),
                    '@FullBandGain': 0.0, '@LFEGain': 0.0}
            else:
                matching = [row['id'] for row in task.objects.values() if reference in (row['id'], row['path'])]
                assert len(matching) == 1, reference
                effect = matching[0]
            task.objects[slot] = {'id': slot, 'name': '', 'type': 'EffectSlot', 'classId': 5505040,
                'owner': {'id': owner, 'name': task.objects[owner]['name']}, 'path': '\\opaque-slot-' + slot, 'notes': '',
                '@Effect': {'id': effect}, '@Bypass': node.get('@Bypass', False), '@Render': node.get('@Render', False)}
            task.objects[owner]['@Effects'].append({'id': slot})
            result = {'id': slot, 'name': ''}
            if isinstance(reference, dict): result['@Effect'] = {'id': effect, 'name': reference['name']}
            results.append(result)
        return list(reversed(results))  # Native associations never supply the order oracle.
    def call(uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri.endswith('object.set'):
            task.calls.append((uri, deepcopy(args), deepcopy(options))); writes.append(deepcopy(args))
            results = []
            for node in args['objects']:
                parent = node['object']; result = {'id': parent, 'name': task.objects[parent]['name']}
                if 'children' in node: result['children'] = [named(child, parent) for child in node['children']]
                if '@Effects' in node: result['@Effects'] = slots(node['@Effects'], parent, args.get('listMode', 'append'))
                results.append(result)
            return {'objects': list(reversed(results))}
        if uri.endswith('object.get') and args.get('waql') != 'from type Project take 1':
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            expression = args.get('waql', '')
            if expression:
                assert expression.startswith('from object "'), expression
                source = expression.split('"')[1]
                rows = [row for row in task.objects.values() if source in (row['id'], row['path'])]
                if 'select @Effects' in expression:
                    assert len(rows) == 1, expression
                    rows = [task.objects[item['id']] for item in rows[0]['@Effects']]
                elif 'select children' in expression:
                    assert len(rows) == 1, expression
                    rows = [row for row in task.objects.values() if row.get('parent', {}).get('id') == rows[0]['id']]
            elif 'id' in args.get('from', {}): rows = [task.objects[value] for value in args['from']['id'] if value in task.objects]
            else: rows = [row for row in task.objects.values() if row['path'] in args['from']['path']]
            for transform in args.get('transform', []):
                assert len(rows) == 1, args
                source, token = rows[0], transform['select'][0]
                if token == 'children': rows = [row for row in task.objects.values() if row.get('parent', {}).get('id') == source['id']]
                elif token == '@Effects': rows = [task.objects[item['id']] for item in source['@Effects']]
                elif token == 'descendants':
                    rows, frontier = [], [source['id']]
                    while frontier:
                        parent = frontier.pop()
                        children = [row for row in task.objects.values() if row.get('parent', {}).get('id') == parent]
                        rows.extend(children); frontier.extend(row['id'] for row in children)
                else: raise AssertionError(args)
            return {'return': [{key: deepcopy(row.get(key, row.get('@' + key))) for key in options['return']
                if key in row or '@' + key in row} for row in rows]}
        if uri.endswith(('getPropertyAndReferenceNames', 'getPropertyInfo')) and (args.get('classId') == 9109507 or task.objects.get(args.get('object'), {}).get('type') == 'Effect'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': ['FullBandGain', 'LFEGain']} if uri.endswith('getPropertyAndReferenceNames') else {'name': args['property'], 'type': 'Real64', 'default': 0.0}
        return original(uri, args, options)
    task.call = call
    runtime = SimpleNamespace(version=version, state_dir=tmp_path / 'state', env=task.env,
        candidate='a' * 40, category_results=[], port=31337,
        lifecycle=SimpleNamespace(host='127.0.0.1', waapi_url='ws://127.0.0.1:31337/waapi'))
    def raw(command):
        commands.append(list(command))
        code, payload = workflow.waapi_gateway.execute_gateway(['--state-dir', str(runtime.state_dir), *command],
            env=runtime.env, client_factory=lambda _: task)
        if fault and command[0] == 'verify' and len(writes) == 4 and payload.get('verified') is True:
            # Mutate only AFTER the real Gateway verified the intended first
            # append. The collector's independent oracle must reject this.
            sound = next(row for row in task.objects.values() if row['name'] == 'WAAPI_ANON_TEST_Sound')
            slot = task.objects[sound['@Effects'][0]['id']]
            if fault == 'independent-owner': slot['owner'] = {'id': SECOND}
            if fault == 'independent-order': sound['@Effects'].reverse()
        if fault == 'independent-previous-owner' and command[0] == 'verify' and len(writes) == 6 and payload.get('verified') is True:
            next(row for row in task.objects.values() if row['name'] == 'WAAPI_ANON_TEST_Sound')['notes'] = 'Unrequested reset'
        return code, payload
    runtime.raw_gateway = raw
    return runtime, commands, writes, task


def test_anonymous_effect_collector_full_public_flow_reaches_real_category_writer(tmp_path, workflow, monkeypatch):
    from tests.destructive.support.category_evidence import append_category_evidence, exact_transaction_outcomes
    runtime, commands, writes, _task = _anonymous_effect_construction_runtime(tmp_path, workflow)
    category = workflow._collect_anonymous_effect_slot_construction_acceptance(runtime, prefix='WAAPI_ANON_TEST')
    assert category['status'] == 'PASS' and category['verifier_strength']
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert receipt['business_effect_verified'] is True and receipt['setup_coverage_credit'] is False
    assert len(writes) == 6 and [command[0] for command in commands].count('execute') == 6
    assert [command[0] for command in commands].count('verify') == 6
    assert all(phase['effect_verified'] for phase in receipt['transactions'][3:])
    assert len(receipt['calls']) <= 256 and Path(category['observation_path']).stat().st_size <= 8 * 1024 * 1024
    target_ids = [row['id'] for row in receipt['baseline']['targets']]
    assert [row['notes'] for row in receipt['baseline']['targets']] == ['Keep target0', 'Keep target1']
    expected = lambda targets: [{'type': 'EffectSlot', 'name': '', '@Effect': target, '@Bypass': index != 0, '@Render': index == 0}
        for index, target in enumerate(targets)]
    assert writes[3]['objects'] == [{'object': receipt['baseline']['owner']['id'], '@Effects': expected(target_ids)}]
    assert writes[4]['listMode'] == 'replaceAll'
    assert writes[4]['objects'] == [{'object': receipt['baseline']['owner']['id'], '@Effects': expected(list(reversed(target_ids)))}]
    last = next(row['children'][0] for row in writes[5]['objects'] if row['children'][0]['type'] == 'Sound')
    assert last['@Effects'][1]['@Effect'] == {'type': 'Effect', 'classId': receipt['live_classes']['Wwise Gain'],
        'name': 'WAAPI_ANON_TEST_LocalGain', 'notes': 'Keep local Effect'}
    slot_declarations = [command for command in commands if command[0] == 'draft-declare-new'
        and command[command.index('--declaration-id') + 1] in {'slot0', 'slot1'}]
    assert len(slot_declarations) == 6 and all('--name' not in command for command in slot_declarations)
    output = tmp_path / 'actual-category-writer.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(output))
    node = 'fixture::anonymous_constructor'
    append_category_evidence(repo_root=tmp_path, candidate=runtime.candidate, version=runtime.version,
        host={'fixture_only': True}, categories=runtime.category_results,
        source={'fixture_only': True, 'hash_before': 'same', 'hash_after': 'same'}, residual_state={'sandbox': 'deleted'},
        invocation={'selected_test_nodeids': [node], 'node_outcomes': [{'nodeid': node, 'outcome': 'PASS'}],
            'started_at_unix_ns': 1, 'finished_at_unix_ns': 2, 'phase': 'final', 'outcome': 'PASS'},
        transactions=exact_transaction_outcomes(runtime.state_dir))
    record = json.loads(output.read_text())
    assert record['contract'] == 'waapi-skill.host-category-evidence/v3'
    assert record['categories'] == runtime.category_results
    assert len(record['transactions']) == 6 and all(row['state'] == 'verified' for row in record['transactions'])


@pytest.mark.parametrize('fault', ['independent-owner', 'independent-order'])
def test_anonymous_effect_collector_rejects_independent_corruption_after_gateway_verified(tmp_path, workflow, monkeypatch, fault):
    runtime, commands, writes, _task = _anonymous_effect_construction_runtime(tmp_path, workflow, fault=fault)
    with pytest.raises(AssertionError):
        workflow._collect_anonymous_effect_slot_construction_acceptance(runtime, prefix='WAAPI_ANON_TEST')
    category = runtime.category_results[-1]
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert category['status'] == 'FAIL' and category['verifier_strength']
    assert receipt['business_effect_verified'] is False and receipt['failure']
    phase = receipt['transactions'][-1]
    assert phase['phase'] == 'append_existing_sharesets' and phase['verify']['payload']['verified'] is True
    assert phase['execute']['payload']['state'] == 'executed_unverified' and phase['effect_verified'] is False
    assert len(writes) == 4 and [command[0] for command in commands].count('execute') == 4
    assert [command[0] for command in commands].count('verify') == 4
    from tests.destructive.support.category_evidence import append_category_evidence, exact_transaction_outcomes
    output = tmp_path / 'actual-failure-category-writer.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(output))
    node = 'fixture::anonymous_constructor_failure'
    append_category_evidence(repo_root=tmp_path, candidate=runtime.candidate, version=runtime.version,
        host={'fixture_only': True}, categories=runtime.category_results, source={'fixture_only': True},
        residual_state={'sandbox': 'retained'}, invocation={'selected_test_nodeids': [node],
            'node_outcomes': [{'nodeid': node, 'outcome': 'FAIL'}], 'started_at_unix_ns': 1,
            'finished_at_unix_ns': 2, 'phase': 'final', 'outcome': 'FAIL'},
        transactions=exact_transaction_outcomes(runtime.state_dir))
    record = json.loads(output.read_text())
    assert record['categories'][0]['status'] == 'FAIL' and record['invocation']['outcome'] == 'FAIL'
    assert len(record['transactions']) == 4 and all(row['state'] == 'verified' for row in record['transactions'])


def test_anonymous_collector_preserves_previous_owner_after_the_planned_graph_effect(tmp_path, workflow):
    runtime, commands, writes, _task = _anonymous_effect_construction_runtime(tmp_path, workflow, fault='independent-previous-owner')
    with pytest.raises(AssertionError):
        workflow._collect_anonymous_effect_slot_construction_acceptance(runtime, prefix='WAAPI_ANON_TEST')
    receipt = json.loads(Path(runtime.category_results[-1]['observation_path']).read_text())
    assert runtime.category_results[-1]['status'] == 'FAIL' and receipt['failure']
    assert len(writes) == 6 and [command[0] for command in commands].count('execute') == 6
    assert receipt['transactions'][-1]['verify']['payload']['verified'] is True
    assert receipt['transactions'][-1]['effect_verified'] is False


def _voice_creation_runtime(tmp_path, workflow, version='2025.1', *, fault=None):
    """Actual Gateway with a source-shaped native constructor, not collector replies."""
    from copy import deepcopy
    import uuid
    from tests.unit.test_sound_voice_creation_gateway import voice_task
    from tests.unit.test_object_graph_owned_choices_gateway import SECOND
    task = voice_task(tmp_path, version)
    task.objects = {SECOND: {'id': SECOND, 'name': 'Default Work Unit', 'type': 'WorkUnit',
        'classId': 3, 'path': ('\\Containers' if version == '2025.1' else '\\Actor-Mixer Hierarchy') + '\\Default Work Unit',
        'notes': 'Keep parent'}}
    container_type = 'PropertyContainer' if version == '2025.1' else 'ActorMixer'
    original, commands, writes = task.call, [], []
    def create(node, parent, *, owned=False):
        assert not owned and node['type'] in {'Sound', 'ActorMixer', container_type}, node
        identity = '{' + str(uuid.uuid4()).upper() + '}'
        actual_type = container_type if node['type'] == 'ActorMixer' else node['type']
        task.objects[identity] = {'id': identity, 'name': node['name'], 'type': actual_type,
            'classId': 65552 if actual_type == 'Sound' else 1,
            'parent': {'id': parent}, 'path': task.objects[parent]['path'] + '\\' + node['name'],
            'notes': node.get('notes', ''), **{key: deepcopy(value) for key, value in node.items() if key.startswith('@')}}
        children = [create(child, identity) for child in node.get('children', [])]
        return {'id': identity, 'name': node['name'], **({'children': children} if children else {})}
    task._create = create
    def call(uri, args=None, options=None):
        if uri.endswith(('object.create', 'object.set')):
            writes.append((uri, deepcopy(args)))
        if uri.endswith('object.get') and (args or {}).get('waql', '').startswith('from object "'):
            import re
            expression = args['waql']
            match = re.fullmatch(r'from object "([^"]+)"(?: take 1)?', expression)
            assert match, expression
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            rows = [row for row in task.objects.values() if match[1] in (row['id'], row['path'])]
            return {'return': [{key: deepcopy(row.get(key, row.get('@' + key))) for key in options['return']
                if key in row or '@' + key in row} for row in rows]}
        return original(uri, args, options)
    task.call = call
    runtime = SimpleNamespace(version=version, state_dir=tmp_path / 'state', env=task.env,
        candidate='a' * 40, category_results=[], port=31337,
        lifecycle=SimpleNamespace(host='127.0.0.1', waapi_url='ws://127.0.0.1:31337/waapi'))
    def raw(command):
        commands.append(list(command))
        code, payload = workflow.waapi_gateway.execute_gateway(['--state-dir', str(runtime.state_dir), *command],
            env=runtime.env, client_factory=lambda _: task)
        if command[0] == 'verify' and payload.get('verified') is True:
            if fault == 'numeric-flag' and len(writes) == 1:
                next(row for row in task.objects.values() if row['type'] == 'Sound')['@IsVoice'] = 1
            if fault == 'missing-nested-child' and len(writes) == 2:
                child = next(row for row in task.objects.values() if row['name'] == 'NestedVoice')
                del task.objects[child['id']]
        return code, payload
    runtime.raw_gateway = raw
    return runtime, commands, writes


@pytest.mark.parametrize('version', ['2021.1', '2025.1'])
def test_voice_creation_collector_uses_public_gateway_and_actual_category_writer(tmp_path, workflow, monkeypatch, version):
    import hashlib
    from tests.destructive.support.category_evidence import append_category_evidence, exact_transaction_outcomes
    runtime, commands, writes = _voice_creation_runtime(tmp_path, workflow, version)
    category = workflow._collect_voice_creation_acceptance(runtime, prefix='WAAPI_VOICE_TEST')
    receipt = json.loads(Path(category['observation_path']).read_text())
    expected = 2 if version == '2021.1' else 3
    assert category['status'] == 'PASS' and receipt['business_effect_verified'] is True
    assert len(writes) == expected and [row[0] for row in commands].count('execute') == expected
    assert [row[0] for row in commands].count('verify') == expected
    assert all(phase['effect_verified'] and phase['verify']['payload']['verified'] is True for phase in receipt['transactions'])
    for phase in receipt['transactions']:
        assert phase['independent_voice']['properties']['IsVoice'] is True
        assert phase['independent_voice']['properties']['Volume'] == phase['expected']['volume']
        dispatch = phase['compiled_native_request']
        args = dispatch['args']
        node = args['objects'][0]['children'][0] if dispatch['uri'].endswith('object.set') else args
        voice = node['children'][0] if phase['phase'] == 'ordinary_nested_voice' else node
        assert voice['@IsVoice'] is True and 'language' not in voice and 'import' not in voice
    output = tmp_path / 'voice-actual-category-writer.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(output))
    node = 'fixture::voice_creation'
    append_category_evidence(repo_root=tmp_path, candidate=runtime.candidate, version=runtime.version,
        host={'fixture_only': True}, categories=runtime.category_results,
        source={'fixture_only': True, 'hash_before': 'same', 'hash_after': 'same'}, residual_state={'sandbox': 'deleted'},
        invocation={'selected_test_nodeids': [node], 'node_outcomes': [{'nodeid': node, 'outcome': 'PASS'}],
            'started_at_unix_ns': 1, 'finished_at_unix_ns': 2, 'phase': 'final', 'outcome': 'PASS'},
        transactions=exact_transaction_outcomes(runtime.state_dir))
    record = json.loads(output.read_text())
    assert record['contract'] == 'waapi-skill.host-category-evidence/v3' and record['categories'] == runtime.category_results
    assert len(record['transactions']) == expected and all(row['state'] == 'verified' for row in record['transactions'])
    assert record['categories'][0]['observation_sha256'] == hashlib.sha256(Path(category['observation_path']).read_bytes()).hexdigest()


@pytest.mark.parametrize('fault', ['numeric-flag', 'missing-nested-child'])
def test_voice_creation_collector_rejects_corruption_after_gateway_verified(tmp_path, workflow, fault):
    runtime, commands, writes = _voice_creation_runtime(tmp_path, workflow, fault=fault)
    with pytest.raises(AssertionError):
        workflow._collect_voice_creation_acceptance(runtime, prefix='WAAPI_VOICE_TEST')
    category = runtime.category_results[-1]
    receipt = json.loads(Path(category['observation_path']).read_text())
    phase = receipt['transactions'][-1]
    expected = 1 if fault == 'numeric-flag' else 2
    assert category['status'] == 'FAIL' and receipt['business_effect_verified'] is False and receipt['failure']
    assert phase['execute']['payload']['state'] == 'executed_unverified' and phase['verify']['payload']['verified'] is True
    assert phase['effect_verified'] is False
    assert len(writes) == expected and [row[0] for row in commands].count('execute') == expected


def _created_fields_history_runtime(tmp_path, workflow, version='2025.1', *, fault=None, null_value=None, source_metadata=None):
    """Public Gateway with native-shaped create/history state, never manufactured receipts."""
    from copy import deepcopy
    import uuid
    from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, SECOND
    task = OwnedGraphTask(tmp_path, version, 'object.create')
    actor = ('\\Containers' if version == '2025.1' else '\\Actor-Mixer Hierarchy') + '\\Default Work Unit'
    attenuation_parent = '{66666666-6666-6666-6666-666666666666}'
    task.objects = {identity: {'id': identity, 'name': 'Default Work Unit', 'type': 'WorkUnit',
        'classId': 1638416, 'path': path, 'parent': None, 'notes': 'Keep parent'}
        for identity, path in [(SECOND, actor), (attenuation_parent, r'\Attenuations\Default Work Unit')]}
    task.types = [{'name': name, 'classId': value, 'type': 'WObject'} for name, value in (
        ('Sound', 65552), ('Attenuation', 655376), ('WorkUnit', 1638416))]
    task.metadata = {'IsLoopingEnabled': {'name': 'IsLoopingEnabled', 'type': 'bool', 'default': False},
        'IsLoopingInfinite': {'name': 'IsLoopingInfinite', 'type': 'bool', 'default': False},
        'Volume': {'name': 'Volume', 'type': 'Real32', 'restriction': {'type': 'range', 'min': -96, 'max': 6}},
        'Attenuation': {'name': 'Attenuation', 'type': '', 'restriction': {
            'type': 'reference', 'restrictions': [{'type': ['Attenuation']}]}}}
    if version == '2022.1':
        # Retained519 native2022 class metadata certifies a PRESENT null default.
        task.metadata['Attenuation']['default'] = None
    if source_metadata is not None:
        task.metadata.update(deepcopy(source_metadata))
        task.types.extend([{'name': 'Bus', 'classId': 1376272, 'type': 'WObject'},
            {'name': 'AuxBus', 'classId': 3997712, 'type': 'WObject'}])
    platform = '{77777777-7777-7777-7777-777777777777}'
    original, commands, writes = task.call, [], []
    history = {}
    def call(uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri.endswith('getProjectInfo'):
            return {**original(uri, args, options), 'currentPlatformId': platform,
                'platforms': [{'id': platform, 'name': 'Windows'}]}
        if uri.endswith('object.create'):
            task.calls.append((uri, deepcopy(args), deepcopy(options))); writes.append((uri, deepcopy(args)))
            identity = '{' + str(uuid.UUID(int=200 + len(writes))).upper() + '}'
            row = {'id': identity, 'name': args['name'], 'type': args['type'],
                'classId': next(item['classId'] for item in task.types if item['name'] == args['type']),
                'path': task.objects[args['parent']]['path'] + '\\' + args['name'],
                'parent': {'id': args['parent']}, 'notes': args.get('notes', '')}
            if args['type'] == 'Sound':
                row.update({'@' + key: deepcopy(info['default']) for key, info in task.metadata.items() if 'default' in info})
            row.update({key: deepcopy(value) for key, value in args.items() if key.startswith('@')})
            if '@Attenuation' in row and row['@Attenuation'] is None:
                row['@Attenuation'] = deepcopy(null_value)
            task.objects[identity] = row
            if row['type'] == 'Sound': history.update(id=identity, after=deepcopy(row))
            return {'id': identity, 'name': row['name']}
        if uri in {'ak.wwise.core.undo.undo', 'ak.wwise.core.undo.redo'}:
            task.calls.append((uri, deepcopy(args), deepcopy(options))); writes.append((uri, deepcopy(args)))
            if fault == 'undo-error' and uri.endswith('.undo'): raise RuntimeError('fixture undo native refused')
            if uri.endswith('.undo'): task.objects.pop(history['id'], None)
            else: task.objects[history['id']] = deepcopy(history['after'])
            return {}
        if uri.endswith('object.get') and args.get('waql') != 'from type Project take 1':
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            source = args.get('from', {})
            if 'id' in source: rows = [task.objects[key] for key in source['id'] if key in task.objects]
            elif 'path' in source: rows = [row for row in task.objects.values() if row['path'] in source['path']]
            else:
                expression = args['waql']; assert expression.startswith('from object "'), expression
                selector = expression.split('"')[1]
                rows = [row for row in task.objects.values() if selector in (row['id'], row['path'])]
            for transform in args.get('transform', []):
                assert transform == {'select': ['children']}, transform
                rows = [row for row in task.objects.values() if row.get('parent') == {'id': rows[0]['id']}]
            return {'return': [{key: deepcopy(row.get(key, row.get('@' + key))) for key in options['return']
                if key in row or '@' + key in row} for row in rows]}
        return original(uri, args, options)
    task.call = call
    runtime = SimpleNamespace(version=version, state_dir=tmp_path / 'state', env=task.env,
        candidate='fixture-candidate', category_results=[], port=31337,
        lifecycle=SimpleNamespace(host='127.0.0.1', waapi_url='ws://127.0.0.1:31337/waapi'))
    def raw(command):
        commands.append(list(command))
        code, payload = workflow.waapi_gateway.execute_gateway(['--state-dir', str(runtime.state_dir), *command],
            env=runtime.env, client_factory=lambda _url: task)
        if command[0] == 'status' and code == 0:
            if fault == 'endpoint-drift': payload['endpoint'] = {**payload['endpoint'], 'port': 31338}
            elif fault == 'version-drift': payload['detected_version'] = '2024.1'
        if fault == 'source-query-path' and command[0] == 'query-object' and '--exact-id' in command and history:
            for row in payload.get('objects', []):
                if row['id'] == history['id']: row['path'] = r'\Different\Returned\Path'
        if command[0] == 'verify' and code == 0 and history:
            last = writes[-1][0]
            if last.endswith('object.create') and fault == 'derived-after-verify':
                task.objects[history['id']]['@IsLoopingInfinite'] = False
            elif last.endswith('object.create') and fault == 'target-after-verify':
                next(row for row in task.objects.values() if row['type'] == 'Attenuation')['notes'] = 'Unexpected target change'
            elif last.endswith('object.create') and fault == 'null-cross-root-after-verify' and history['after']['name'].endswith('_null'):
                other = next(row for row in task.objects.values() if row['type'] == 'Sound' and row['name'].endswith('_existing'))
                task.objects[history['id']]['@Attenuation'] = deepcopy(other['@Attenuation'])
            elif last.endswith('.undo') and fault == 'undo-after-verify':
                task.objects[history['id']] = deepcopy(history['after'])
            elif last.endswith('.redo') and fault == 'redo-after-verify':
                task.objects[history['id']].pop('@Attenuation')
        return code, payload
    runtime.raw_gateway = raw
    return runtime, commands, writes, task


@pytest.mark.parametrize('version', ['2022.1', '2025.1'])
def test_created_fields_history_collector_executes_public_source_and_history_effects(tmp_path, workflow, version):
    runtime, commands, writes, _task = _created_fields_history_runtime(tmp_path, workflow, version)
    category = workflow._collect_created_leaf_fields_history_acceptance(runtime, name='WAAPI_HISTORY_TEST')
    assert category['status'] == 'PASS'
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert receipt['complete'] is True and receipt['business_effect_verified'] is True
    assert receipt['setup_coverage_credit'] is False
    assert [row['phase'] for row in receipt['effects']] == [item for case in ('existing', 'null')
        for item in ([case + '-source', case + '-undo'] if version == '2022.1'
            else [case + '-source', case + '-undo', case + '-redo'])]
    assert len(writes) == (5 if version == '2022.1' else 7)
    assert all(row['effect_verified'] is True for row in receipt['effects'])
    roots = [row['independent_effect']['id'] for row in receipt['effects'] if row['phase'].endswith('-source')]
    assert len(set(roots)) == 2
    for row in receipt['effects']:
        if row['phase'].endswith(('-undo', '-redo')):
            binding = row['immutable_preview']['prepared_operation']['pre_state']['history_binding']
            root = roots[int(row['phase'].startswith('null-'))]
            assert {item['object_id'] for item in binding['observations'] if item['kind'] == 'creation_field'} == {root}
    assert sum(command[0] == 'execute' for command in commands) == len(writes)
    parent = ('Containers' if version == '2025.1' else 'Actor-Mixer Hierarchy', 'Default Work Unit')
    path_queries = [tuple(command[index + 1] for index, token in enumerate(command) if token == '--path-segment')
        for command in commands if command[0] == 'query-object' and '--path-segment' in command]
    assert set(path_queries) == {parent, (*parent, 'WAAPI_HISTORY_TEST_existing'), (*parent, 'WAAPI_HISTORY_TEST_null')}
    if version == '2022.1': assert not any(uri.endswith('.redo') for uri, _args in writes)


@pytest.mark.parametrize('fault', ['derived-after-verify', 'target-after-verify', 'undo-after-verify', 'redo-after-verify', 'null-cross-root-after-verify', 'undo-error'])
def test_created_fields_history_collector_independent_oracle_retains_failed_effect(tmp_path, workflow, fault):
    runtime, commands, writes, _task = _created_fields_history_runtime(tmp_path, workflow, fault=fault)
    with pytest.raises(AssertionError):
        workflow._collect_created_leaf_fields_history_acceptance(runtime, name='WAAPI_HISTORY_TEST')
    category = runtime.category_results[0]
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert category['status'] == 'FAIL' and receipt['complete'] is False and receipt['business_effect_verified'] is False
    assert receipt['failure']['type'] == 'AssertionError'
    assert any(row['effect_verified'] is False for row in receipt['effects'])
    if fault == 'undo-error':
        assert 'fixture undo native refused' in json.dumps(receipt)
        assert len([uri for uri, _args in writes if uri.endswith('.undo')]) == 1
    else:
        # Gateway already reported verification; independent object/absence reads reject damage.
        phase = receipt['effects'][-1]
        assert phase['verify']['verified'] is True
        assert any(command[0] == 'query-object' for command in commands)


def test_created_fields_history_collector_never_dispatches_unpinned_2021_history(tmp_path, workflow):
    runtime, commands, writes, _task = _created_fields_history_runtime(tmp_path, workflow, '2021.1')
    with pytest.raises(AssertionError, match='No pinned native history'):
        workflow._collect_created_leaf_fields_history_acceptance(runtime, name='WAAPI_HISTORY_TEST')
    assert commands == writes == []


@pytest.mark.parametrize('null_value', ['{00000000-0000-0000-0000-000000000000}',
    {'id': '{00000000-0000-0000-0000-000000000000}', 'name': ''}])
def test_created_fields_history_collector_retains_native_explicit_null_representations(tmp_path, workflow, null_value):
    runtime, _commands, _writes, _task = _created_fields_history_runtime(tmp_path, workflow, null_value=null_value)
    category = workflow._collect_created_leaf_fields_history_acceptance(runtime, name='WAAPI_HISTORY_TEST')
    receipt = json.loads(Path(category['observation_path']).read_text())
    source = next(row for row in receipt['effects'] if row['phase'] == 'null-source')
    assert source['independent_effect']['references']['Attenuation'] == null_value
    assert category['status'] == 'PASS' and receipt['complete'] is True


@pytest.mark.parametrize('fault', ['endpoint-drift', 'version-drift', 'source-query-path'])
def test_created_fields_history_collector_rejects_unbound_live_context_or_path(tmp_path, workflow, fault):
    runtime, _commands, writes, _task = _created_fields_history_runtime(tmp_path, workflow, '2022.1', fault=fault)
    with pytest.raises(AssertionError):
        workflow._collect_created_leaf_fields_history_acceptance(runtime, name='WAAPI_HISTORY_TEST')
    receipt = json.loads((runtime.state_dir / 'created-fields-history-acceptance.json').read_text())
    assert receipt['complete'] is False and receipt['business_effect_verified'] is False
    assert runtime.category_results[0]['status'] == 'FAIL'
    if fault == 'source-query-path':
        assert not any(uri.endswith('.undo') for uri, _args in writes)
        assert receipt['effects'][-1]['verify']['verified'] is True
    else:
        assert writes == []


# Exact raw six-field metadata from retained807 native2025.1 draft discovery.
# Source/provenance: /tmp/full-coverage-180-new-object-non-master-condition-plan.md.
_CREATED_HISTORY_NATIVE_2025_METADATA = {'Volume': {'audioEngineId': 0,
            'default': 0.0,
            'dependencies': [],
            'display': {'group': 'Voice', 'index': 1520, 'name': 'Voice Volume'},
            'name': 'Volume',
            'restriction': {'max': 200.0, 'min': -200.0, 'type': 'range'},
            'supports': {'randomizer': True, 'rtpc': 'Additive', 'unlink': True},
            'type': 'Real64',
            'ui': {'autoUpdate': False,
                   'dataMeaning': 'Decibels',
                   'displayAs': {'bitfield': False, 'lrMix': False, 'musicNote': False, 'percentage': False},
                   'value': {'decimals': 1,
                             'fine': 0.1,
                             'infinity': 0,
                             'max': 12.0,
                             'min': -96.0,
                             'step': 1.0}}},
 'Attenuation': {'audioEngineId': 4294967295,
                 'default': None,
                 'dependencies': [{'action': 'Show',
                                   'context': 'Self',
                                   'type': 'isMasterBus',
                                   'value': False},
                                  {'action': 'Enable',
                                   'conditions': [{'restriction': {'type': 'enum',
                                                                   'values': [{'displayName': 'True',
                                                                               'value': True}]}}],
                                   'context': 'Self',
                                   'property': 'ListenerRelativeRouting',
                                   'type': 'property'},
                                  {'action': 'Enable',
                                   'conditions': [{'restriction': {'type': 'enum',
                                                                   'values': [{'displayName': 'True',
                                                                               'value': True}]}}],
                                   'context': 'Self',
                                   'property': 'ListenerRelativeRouting',
                                   'type': 'property'},
                                  {'action': 'Enable',
                                   'context': 'Self',
                                   'property': 'OverridePositioning',
                                   'type': 'override'}],
                 'display': {'group': 'Listener Relative Routing/Attenuation',
                             'index': 1641,
                             'name': 'Attenuation'},
                 'name': 'Attenuation',
                 'restriction': {'restrictions': [{'sharedOnlyTypes': [], 'type': ['Attenuation']}],
                                 'type': 'reference'},
                 'supports': {'randomizer': False, 'rtpc': 'None', 'unlink': True},
                 'type': '',
                 'ui': {'autoUpdate': False,
                        'dataMeaning': 'None',
                        'displayAs': {'bitfield': False,
                                      'lrMix': False,
                                      'musicNote': False,
                                      'percentage': False},
                        'value': {'decimals': 0,
                                  'fine': 0.0,
                                  'infinity': 0,
                                  'max': 0.0,
                                  'min': 0.0,
                                  'step': 0.0}}},
 'ListenerRelativeRouting': {'audioEngineId': 4294967295,
                             'default': True,
                             'dependencies': [{'action': 'Enable',
                                               'context': 'Self',
                                               'property': 'OverridePositioning',
                                               'type': 'override'}],
                             'display': {'group': 'Listener Relative Routing',
                                         'index': 1636,
                                         'name': 'Listener Relative Routing'},
                             'name': 'ListenerRelativeRouting',
                             'restriction': {},
                             'supports': {'randomizer': False, 'rtpc': 'None', 'unlink': False},
                             'type': 'bool',
                             'ui': {'autoUpdate': False,
                                    'dataMeaning': 'None',
                                    'displayAs': {'bitfield': False,
                                                  'lrMix': False,
                                                  'musicNote': False,
                                                  'percentage': False},
                                    'value': {'decimals': 0,
                                              'fine': 0.0,
                                              'infinity': 0,
                                              'max': 0.0,
                                              'min': 0.0,
                                              'step': 0.0}}},
 'OverridePositioning': {'audioEngineId': 4294967295,
                         'default': False,
                         'dependencies': [{'action': 'Enable',
                                           'context': 'Self',
                                           'property': 'OverridePositioning',
                                           'type': 'override'}],
                         'display': {'group': '', 'index': 1633, 'name': 'Override Positioning'},
                         'name': 'OverridePositioning',
                         'restriction': {},
                         'supports': {'randomizer': False, 'rtpc': 'None', 'unlink': False},
                         'type': 'bool',
                         'ui': {'autoUpdate': False,
                                'dataMeaning': 'None',
                                'displayAs': {'bitfield': False,
                                              'lrMix': False,
                                              'musicNote': False,
                                              'percentage': False},
                                'value': {'decimals': 0,
                                          'fine': 0.0,
                                          'infinity': 0,
                                          'max': 0.0,
                                          'min': 0.0,
                                          'step': 0.0}}},
 'IsLoopingEnabled': {'audioEngineId': 4294967295,
                      'default': False,
                      'dependencies': [],
                      'display': {'group': 'Loop', 'index': 1568, 'name': 'Loop'},
                      'name': 'IsLoopingEnabled',
                      'restriction': {},
                      'supports': {'randomizer': False, 'rtpc': 'None', 'unlink': False},
                      'type': 'bool',
                      'ui': {'autoUpdate': False,
                             'dataMeaning': 'None',
                             'displayAs': {'bitfield': False,
                                           'lrMix': False,
                                           'musicNote': False,
                                           'percentage': False},
                             'value': {'decimals': 0,
                                       'fine': 0.0,
                                       'infinity': 0,
                                       'max': 0.0,
                                       'min': 0.0,
                                       'step': 0.0}}},
 'IsLoopingInfinite': {'audioEngineId': 4294967295,
                       'default': True,
                       'dependencies': [{'action': 'Enable',
                                         'conditions': [{'restriction': {'type': 'enum',
                                                                         'values': [{'displayName': 'True',
                                                                                     'value': True}]}}],
                                         'context': 'Self',
                                         'property': 'IsLoopingEnabled',
                                         'type': 'property'}],
                       'display': {'group': 'Loop', 'index': 1569, 'name': 'Loop Infinite'},
                       'name': 'IsLoopingInfinite',
                       'restriction': {},
                       'supports': {'randomizer': False, 'rtpc': 'None', 'unlink': False},
                       'type': 'bool',
                       'ui': {'autoUpdate': False,
                              'dataMeaning': 'None',
                              'displayAs': {'bitfield': False,
                                            'lrMix': False,
                                            'musicNote': False,
                                            'percentage': False},
                              'value': {'decimals': 0,
                                        'fine': 0.0,
                                        'infinity': 0,
                                        'max': 0.0,
                                        'min': 0.0,
                                        'step': 0.0}}}}


def test_created_fields_history_collector_preserves_actual_same_call_reference_conditions(tmp_path, workflow):
    runtime, _commands, _writes, _task = _created_fields_history_runtime(tmp_path, workflow,
        source_metadata=_CREATED_HISTORY_NATIVE_2025_METADATA)
    category = workflow._collect_created_leaf_fields_history_acceptance(runtime, name="WAAPI_HISTORY_TEST")
    assert category["status"] == "PASS"
    receipt = json.loads(Path(category['observation_path']).read_text())
    for phase in receipt['effects']:
        if phase['phase'].endswith('-source'):
            assert phase['independent_effect']['properties']['OverridePositioning'] is True
            continue
        artifact = phase['immutable_preview']
        reference = artifact['request']['arguments']['history_binding']
        assert reference['contract'] == 'waapi-skill.history-draft-reference/v1' and 'observations' not in reference
        binding = artifact['prepared_operation']['pre_state']['history_binding']
        fields = [row for row in binding['observations'] if row['kind'] == 'creation_field']
        assert {row['field'] for row in fields} == {'IsLoopingEnabled', 'IsLoopingInfinite', 'Volume', 'OverridePositioning', 'Attenuation'}
        assert all(row['field_info']['raw'] == _CREATED_HISTORY_NATIVE_2025_METADATA[row['field']] for row in fields)
        assert phase['verify']['agent_result']['request'] == artifact['request']
        assert list(phase['verify'])[-1] == 'agent_result'
        assert len(json.dumps(phase['verify'], ensure_ascii=False, indent=2).encode('utf-8')) <= 24 * 1024


def test_null_source_only_diagnostic_uses_fresh_setup_and_same_five_fields_without_history(tmp_path, workflow):
    from tests.unit.test_compound_undo_business_gateway import _literal_2022_null_creation_metadata
    # Literal failed2022 condition/default grammar; a pure control, not native acceptance.
    runtime, commands, writes, _task = _created_fields_history_runtime(tmp_path, workflow, version='2022.1',
        source_metadata=_literal_2022_null_creation_metadata())
    category = workflow._collect_created_leaf_fields_history_acceptance(runtime,
        name='WAAPI_NULL_DIAGNOSTIC_TEST', null_source_only_diagnostic=True)
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert receipt['complete'] is True and receipt['business_effect_verified'] is False
    assert receipt['diagnostic_only'] is True and receipt['history_acceptance_credit'] is False
    assert category['status'] == 'blocked' and category['diagnostic_only'] is True
    assert category['history_acceptance_credit'] is False
    assert [row['phase'] for row in receipt['setup']] == ['setup-target']
    assert [row['phase'] for row in receipt['effects']] == ['null-source']
    assert len(writes) == 2 and all(uri == 'ak.wwise.core.object.create' for uri, _args in writes)
    assert [command[0] for command in commands].count('execute') == 2
    assert [command[0] for command in commands].count('verify') == 2
    assert not any('ak.wwise.core.undo.' in str(command) for command in commands)
    assert not any(uri.startswith('ak.wwise.core.undo.') for uri, _args, _options in _task.calls)
    _uri, native = writes[-1]
    expected_fields = {'IsLoopingEnabled': True, 'IsLoopingInfinite': True, 'Volume': -6.0,
        'OverridePositioning': True, 'Attenuation': None}
    assert {key: native['@' + key] for key in expected_fields if key != 'Attenuation'} == {
        key: value for key, value in expected_fields.items() if key != 'Attenuation'}
    assert '@Attenuation' not in native
    phase, = receipt['effects']
    actual = phase['independent_effect']
    assert {key: actual['properties'][key] for key in expected_fields if key != 'Attenuation'} == {
        key: value for key, value in expected_fields.items() if key != 'Attenuation'}
    assert 'Attenuation' in actual['references'] and actual['references']['Attenuation'] is None
    assert phase['native_outcome'] == 'accepted' and phase['effect_verified'] is True
    assert category['observation_sha256'] and category['verifier_strength']
    assert len(receipt['calls']) < 256 and Path(category['observation_path']).stat().st_size < 16 * 1024 * 1024


def _render_suffix_observation_runtime(tmp_path, workflow, *, outcome='cleared', version='2025.1'):
    from copy import deepcopy
    runtime, commands, writes, task = _anonymous_effect_construction_runtime(tmp_path, workflow, version=version)
    if outcome == 'color-change':
        task.metadata['Color'] = {'name': 'Color', 'type': 'int32', 'default': 0}
    original = task.call
    def call(uri, args=None, options=None):
        if uri.endswith('isPropertyEnabled'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': True}
        if uri.endswith('object.setProperty'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            writes.append(deepcopy(args))
            slots = [row for row in task.objects.values() if row['type'] == 'EffectSlot']
            assert len(slots) == 2 and args == {'object': slots[0]['id'], 'property': 'Render', 'value': False}, args
            assert [row['@Render'] for row in slots] == [True, True], slots
            if outcome == 'native-error': raise RuntimeError('Original native suffix rejection; never replay')
            if outcome == 'native-error-response':
                class NativeSuffixRejection(RuntimeError):
                    uri = 'ak.wwise.invalid_arguments'
                    kwargs = {'details': {'procedureUri': 'ak.wwise.core.object.setProperty'}}
                raise NativeSuffixRejection('Original native suffix rejection; never replay')
            slots[0]['@Render'] = False
            if outcome in {'cleared', 'missing-render', 'bypass-change', 'owner-change', 'reference-change', 'read-error'}:
                slots[1]['@Render'] = False
            if outcome == 'missing-render': del slots[1]['@Render']
            if outcome == 'bypass-change': slots[1]['@Bypass'] = True
            if outcome == 'owner-change': slots[1]['owner'] = {'id': slots[0]['id']}
            if outcome == 'reference-change': slots[1]['@Effect'] = deepcopy(slots[0]['@Effect'])
            if outcome == 'color-change': slots[1]['@Color'] = 123
            return {}
        if outcome == 'read-error' and len(writes) == 5 and uri.endswith('object.get'):
            raise RuntimeError('Original readback error after write; never classify a suffix')
        result = original(uri, args, options)
        if outcome == 'color-change' and uri.endswith('object.set'):
            for row in task.objects.values():
                if row['type'] == 'EffectSlot': row.setdefault('@Color', 0)
        return result
    task.call = call
    return runtime, commands, writes, task


@pytest.mark.parametrize('outcome', ['cleared', 'retained'])
def test_render_suffix_diagnostic_classifies_actual_chain_without_business_credit(tmp_path, workflow, monkeypatch, outcome):
    from tests.destructive.support.category_evidence import append_category_evidence, exact_transaction_outcomes
    runtime, commands, writes, _task = _render_suffix_observation_runtime(tmp_path, workflow, outcome=outcome)
    category = workflow._collect_effect_render_suffix_observation(runtime, prefix='WAAPI_SUFFIX_TEST')
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert receipt['diagnostic_complete'] is True and receipt['classification'] == outcome
    assert category['diagnostic_only'] is True and category['status'] == 'blocked'
    assert receipt['business_effect_verified'] is False
    assert [row['properties']['Render'] for row in receipt['suffix_before']['slots']] == [True, True]
    assert [row['properties']['Render'] for row in receipt['suffix_after']['slots']] == [False, outcome == 'retained']
    assert len(writes) == 5 and [command[0] for command in commands].count('execute') == 5
    assert [command[0] for command in commands].count('verify') == 5
    assert all(phase['setup_no_credit'] is True for phase in receipt['transactions'][:4])
    assert all(phase['effect_verified'] is False for phase in receipt['transactions'])
    assert len(receipt['calls']) < 256 and Path(category['observation_path']).stat().st_size < 8 * 1024 * 1024
    output = tmp_path / 'diagnostic-category.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(output))
    node = 'fixture::render_suffix_diagnostic'
    append_category_evidence(repo_root=tmp_path, candidate=runtime.candidate, version=runtime.version,
        host={'fixture_only': True}, categories=runtime.category_results,
        source={'fixture_only': True, 'hash_before': 'same', 'hash_after': 'same'}, residual_state={'sandbox': 'deleted'},
        invocation={'selected_test_nodeids': [node], 'node_outcomes': [{'nodeid': node, 'outcome': 'PASS'}],
            'started_at_unix_ns': 1, 'finished_at_unix_ns': 2, 'phase': 'final', 'outcome': 'PASS'},
        transactions=exact_transaction_outcomes(runtime.state_dir))
    record = json.loads(output.read_text())
    assert record['contract'] == 'waapi-skill.host-category-evidence/v3'
    assert record['invocation']['outcome'] == 'PASS' and record['categories'][0]['status'] == 'blocked'
    assert record['categories'][0]['business_effect_verified'] is False
    assert len(record['transactions']) == 5


@pytest.mark.parametrize('fault', ['missing-render', 'bypass-change', 'owner-change', 'reference-change', 'read-error'])
def test_render_suffix_diagnostic_cannot_classify_incomplete_or_unrequested_changes(tmp_path, workflow, fault):
    runtime, commands, writes, _task = _render_suffix_observation_runtime(tmp_path, workflow, outcome=fault)
    with pytest.raises(AssertionError):
        workflow._collect_effect_render_suffix_observation(runtime, prefix='WAAPI_SUFFIX_TEST')
    category, = runtime.category_results
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert category['status'] == 'FAIL' and receipt['diagnostic_complete'] is False
    assert receipt['classification'] == 'not_observed' and receipt['business_effect_verified'] is False
    assert len(writes) == 5 and [command[0] for command in commands].count('execute') == 5


@pytest.mark.parametrize('outcome,classification,complete,status', [
    pytest.param('native-error', 'indeterminate', False, 'FAIL', id='exception-indeterminate'),
    pytest.param('native-error-response', 'native_error_response', True, 'blocked', id='native-error-response')])
def test_render_suffix_diagnostic_retains_native_failure_and_stops_without_retry(tmp_path, workflow, outcome, classification, complete, status):
    runtime, commands, writes, _task = _render_suffix_observation_runtime(tmp_path, workflow, outcome=outcome)
    category = workflow._collect_effect_render_suffix_observation(runtime, prefix='WAAPI_SUFFIX_TEST')
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert category['classification'] == classification and receipt['diagnostic_complete'] is complete
    assert category['status'] == status and receipt['business_effect_verified'] is False
    assert receipt['transactions'][-1]['original_durable_state'] == 'indeterminate'
    assert receipt['effects_unknown'] is True and receipt['transactions'][-1]['effects_unknown'] is True
    if outcome == 'native-error-response':
        assert receipt['transactions'][-1]['native_error_code'] == 'ak.wwise.invalid_arguments'
    assert 'Original native suffix rejection' in json.dumps(receipt['transactions'][-1]['execute'])
    assert len(writes) == 5 and commands[-1][0] == 'execute'
    assert [command[0] for command in commands].count('verify') == 4


def test_render_suffix_diagnostic_preserves_other_disclosed_slot_scalars(tmp_path, workflow):
    runtime, commands, writes, _task = _render_suffix_observation_runtime(tmp_path, workflow, outcome='color-change')
    with pytest.raises(AssertionError):
        workflow._collect_effect_render_suffix_observation(runtime, prefix='WAAPI_SUFFIX_TEST')
    category, = runtime.category_results
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert category['status'] == 'FAIL' and receipt['diagnostic_complete'] is False
    assert len(writes) == 5 and [command[0] for command in commands].count('execute') == 5


@pytest.mark.parametrize('version', ['2023.1', '2024.1'])
def test_render_suffix_diagnostic_modern_version_public_routes(tmp_path, workflow, version):
    runtime, commands, writes, _task = _render_suffix_observation_runtime(tmp_path, workflow, version=version)
    category = workflow._collect_effect_render_suffix_observation(runtime, prefix='WAAPI_SUFFIX_TEST')
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert receipt['version'] == version and receipt['classification'] == 'cleared'
    assert receipt['diagnostic_complete'] is True and receipt['business_effect_verified'] is False
    assert category['status'] == 'blocked' and category['diagnostic_only'] is True
    assert [row['properties']['Render'] for row in receipt['suffix_before']['slots']] == [True, True]
    assert [row['properties']['Render'] for row in receipt['suffix_after']['slots']] == [False, False]
    assert receipt['baseline']['parents']['sound']['path'] == r'\Actor-Mixer Hierarchy\Default Work Unit'
    assert len(writes) == 5 and [command[0] for command in commands].count('execute') == 5
    assert [command[0] for command in commands].count('verify') == 5
    assert receipt['transactions'][-1]['compiled_native_request']['args'] == {
        'object': receipt['suffix_before']['ordered_ids'][0], 'property': 'Render', 'value': False}
    assert len(receipt['calls']) < 256 and Path(category['observation_path']).stat().st_size < 8 * 1024 * 1024


def _legacy_import_render_runtime(tmp_path, workflow, version='2022.1', *, fault=None):
    """Real Gateway, literal legacy metadata and native import/media state only."""
    from copy import deepcopy
    from tests.unit.test_anonymous_effect_slot_graph_gateway import legacy_render_import_task
    from tests.unit.test_list_merge_existing_conditions_gateway import EFFECT, EFFECT_PARENT
    from tests.unit.test_object_graph_owned_choices_gateway import FIRST, SECOND, ROOT
    task, writes = legacy_render_import_task(tmp_path, version, media=True)
    # Native/UI labels are distinct from exact selected metadata field tokens.
    for token, label in {'Effect0': 'Effect 0', 'RenderEffect1': 'Render Effect 1'}.items():
        task.metadata[token]['display'] = {'name': label}
    task.objects.pop(FIRST)
    if version == '2021.1':
        import xml.etree.ElementTree as ET
        from tests.unit.test_operation_registry_import_verifier import WWISE_2021_PROJECT
        tree = ET.parse(WWISE_2021_PROJECT)
        project = tree.find('./ProjectInfo/Project')
        project.set('Name', 'Fixture'); project.set('ID', '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}')
        tree.write(task.project_file, encoding='utf-8', xml_declaration=True)
        (task.project_file.parent / 'Originals').mkdir()
    folder = '{2990944C-71B4-45DD-B79B-286A4FC9A8BF}'
    other = '{83E0619D-B89C-4190-9D6E-A353DE39D1E4}'
    task.types += [{'name': 'Folder', 'classId': 131088, 'type': 'WObject'},
        {'name': 'Wwise Delay', 'classId': 6946819, 'type': 'Effect'},
        {'name': 'AudioSource' if version == '2021.1' else 'AudioFileSource', 'classId': 16, 'type': 'WObject'}]
    task.objects[EFFECT_PARENT].update(name='Factory Effects', path=r'\Effects\Factory Effects')
    task.objects[folder] = {'id': folder, 'name': 'Delay', 'type': 'Folder', 'classId': 131088,
        'path': r'\Effects\Factory Effects\Delay', 'parent': {'id': EFFECT_PARENT}, 'notes': 'Keep Delay'}
    for identity, name in ((EFFECT, 'Echo'), (other, 'The_Slap')):
        task.objects[identity] = {'id': identity, 'name': name, 'type': 'Effect', 'classId': 6946819,
            'path': task.objects[folder]['path'] + '\\' + name, 'parent': {'id': folder},
            'notes': 'Keep ' + name, '@DelayTime': 0.25, '@WetDryMix': 16.5}
    # Literal fixture-only Effect metadata, not claimed as native observation.
    effect_metadata = {name: {'name': name, 'type': 'Real32'} for name in ('DelayTime', 'WetDryMix')}
    original, commands = task.call, []
    project_dirty = {'value': False}
    def call(uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri == 'ak.wwise.core.project.save':
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            project_dirty['value'] = False
            return {}
        if uri.endswith(('getPropertyAndReferenceNames', 'getPropertyInfo')):
            obj = task.objects.get(args.get('object'), {})
            if obj.get('type') == 'Effect' or args.get('classId') == 6946819:
                task.calls.append((uri, deepcopy(args), deepcopy(options)))
                return {'return': list(effect_metadata)} if uri.endswith('getPropertyAndReferenceNames') else effect_metadata[args['property']]
        if uri.endswith('object.get') and args.get('waql') in {'from type Project take 1', 'from type Project take 2'}:
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': [{'id': '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}', 'name': 'Fixture', 'type': 'Project',
                'path': '\\', 'filePath': str(task.project_file), 'workunitIsDirty': project_dirty['value']}]}
        if uri.endswith('object.get') and args.get('waql', '').startswith('from object "'):
            import re
            expression = args['waql']
            if version == '2021.1':
                assert not {'activeSource', 'originalFilePath'} & set(options['return']), options
            if version == '2021.1':
                assert 'select activeSource' not in expression, 'Actual 2021 Console rejects activeSource traversal too'
            match = re.fullmatch(r'from object "([^"]+)"( select children)?(?: take (?:1|100))?', expression)
            assert match, expression
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            rows = [row for row in task.objects.values() if match[1] in (row['id'], row['path'])]
            if match[2]:
                assert version == '2021.1' and options['language'] == 'SFX'
                owner_ids = {row['id'] for row in rows}
                rows = [row for row in task.objects.values()
                    if (row['parent'].get('id') if isinstance(row.get('parent'), dict) else row.get('parent')) in owner_ids]
                if fault == 'empty-source' and len(writes) == 2:
                    rows = []
                if fault == 'selected-source-guid' and len(writes) == 2:
                    rows = [{**row, 'id': other} for row in rows]
                if fault == 'ambiguous-source' and len(writes) == 2:
                    rows = rows + [{**row, 'id': other} for row in rows]
            return {'return': [{key: deepcopy(row.get(key, row.get('@' + key))) for key in options['return']
                if key in row or '@' + key in row} for row in rows]}
        if uri.endswith('audio.importTabDelimited'):
            import csv
            import uuid
            task.calls.append((uri, deepcopy(args), deepcopy(options))); writes.append(deepcopy(args))
            results = []
            for record in csv.DictReader(Path(args['importFile']).read_text().splitlines(), delimiter='\t'):
                assert record['Object Type'] == 'Sound SFX' and record['Object Path'].startswith('<Sound SFX>'), record
                assert 'Property[IsVoice]' not in record
                name = record['Object Path'].removeprefix('<Sound SFX>')
                identity = '{' + str(uuid.uuid4()).upper() + '}'
                row = {'id': identity, 'name': name, 'type': 'Sound', 'classId': 65552,
                    'path': task.objects[SECOND]['path'] + '\\' + name, 'parent': {'id': SECOND},
                    'notes': record['Notes'], **{'@' + token: deepcopy(info['default']) for token, info in task.metadata.items()}}
                row['@IsVoice'] = False  # documented Sound SFX construction kind
                for key, value in record.items():
                    if key.startswith('Property['):
                        token = key[9:-1]; row['@' + token] = float(value) if token == 'Volume' else value == 'true'
                    elif key.startswith('Reference['): row['@' + key[10:-1]] = value
                for i in range(4):
                    if row.get('@RenderEffect' + str(i)) is True:
                        for j in range(i): row['@RenderEffect' + str(j)] = True
                task.objects[identity] = row; results.append(deepcopy(row))
            project_dirty['value'] = True
            return {'objects': results}
        result = original(uri, args, options)
        if uri.endswith('audio.import'):
            for node in args['imports']:
                if 'audioFile' in node:
                    source_path = node['objectPath'].replace('<AudioFileSource>', '')
                    for row in task.objects.values():
                        if row['path'] == source_path: row['notes'] = node.get('notes', '')
                    for row in result['objects']:
                        if row['path'] == source_path: row['notes'] = node.get('notes', '')
        if uri.endswith(('audio.import', 'audio.importTabDelimited')):
            project_dirty['value'] = True
            for row in task.objects.values():
                if row['type'] == 'AudioFileSource':
                    row['classId'] = 16
                if version == '2021.1' and 'originalFilePath' in row:
                    row['sound:originalWavFilePath'] = row['originalFilePath']
                    row['originalWavFilePath'] = row['originalFilePath']
        return result
    task.call = call
    runtime = SimpleNamespace(version=version, state_dir=tmp_path / 'state', env=task.env,
        candidate='a' * 40, category_results=[], port=31337,
        sandbox=SimpleNamespace(sandbox_path=task.project_file.parent, sandbox_project=task.project_file),
        lifecycle=SimpleNamespace(host='127.0.0.1', waapi_url='ws://127.0.0.1:31337/waapi'))
    def raw(command):
        commands.append(list(command))
        code, payload = workflow.waapi_gateway.execute_gateway(['--state-dir', str(runtime.state_dir), *command],
            env=runtime.env, client_factory=lambda _: task)
        if command[0] == 'verify' and payload.get('verified') is True and len(writes) == 2:
            source = next(row for row in task.objects.values() if row['type'] == 'AudioFileSource')
            if fault == 'independent-source-parent':
                source['parent'] = {'id': EFFECT_PARENT}
            if fault == 'source-media-mismatch':
                Path(source['originalFilePath']).write_bytes(b'changed after verified import')
        if (command[0] == 'query-object' and '--relationship' in command and code == 0
                and fault == 'partial-source' and len(writes) == 2):
            payload['projection_complete'] = False
            payload['status'] = 'partial'
        return code, payload
    runtime.raw_gateway = raw
    return runtime, commands, writes


@pytest.mark.parametrize('version', ['2022.1', '2021.1'])
def test_legacy_import_render_collector_full_public_flow_and_actual_writer(tmp_path, workflow, monkeypatch, version):
    import hashlib
    from tests.destructive.support.category_evidence import append_category_evidence, exact_transaction_outcomes
    runtime, commands, writes = _legacy_import_render_runtime(tmp_path, workflow, version)
    category = workflow._collect_legacy_import_render_acceptance(runtime, prefix='WAAPI_LEGACY_IMPORT_TEST')
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert category['status'] == 'PASS' and receipt['business_effect_verified'] is True
    selected = [candidate for call in receipt['calls'] if call['argv'][0] == 'draft-discover-fields'
        and '--selection' in call['argv'] for result in call.get('payload', {}).get('meaning_results', [])
        for candidate in result.get('candidates', [])]
    for token, label in {'Effect0': 'Effect 0', 'RenderEffect1': 'Render Effect 1'}.items():
        assert any(row['metadata']['name'] == token and row['label'] == label for row in selected)
    assert receipt['setup_coverage_credit'] is False and receipt['tsv_media_verified'] is False
    save_count = 3 if version == '2021.1' else 0
    assert len(writes) == 4 and [row[0] for row in commands].count('execute') == 4 + save_count
    assert [row[0] for row in commands].count('verify') == 4 + save_count
    prerequisites = receipt.get('prerequisites', [])
    assert len(prerequisites) == save_count
    assert all(row['coverage_credit'] is False and row['save']['verify']['state'] == 'result_schema_checked'
        for row in prerequisites)
    if save_count:
        assert [row['before_phase'] for row in prerequisites] == [
            'existing_media_render', 'new_media_refs_render', 'immutable_tsv_structure_render']
    effects = [row for row in receipt['transactions'] if not row['setup']]
    assert len(effects) == 3 and all(row['effect_verified'] for row in effects)
    assert all(row['verify']['payload']['verified'] is True for row in effects)
    assert [row['phase'] for row in effects] == ['existing_media_render', 'new_media_refs_render', 'immutable_tsv_structure_render']
    assert all(row['independent_owner']['properties']['RenderEffect0'] is True for row in effects)
    assert all(row['independent_owner']['properties']['RenderEffect1'] is True for row in effects)
    tsv = effects[-1]
    table_bytes = Path(tsv['table']['path']).read_bytes()
    assert hashlib.sha256(table_bytes).hexdigest() == tsv['table']['sha256']
    import csv, io
    records = list(csv.DictReader(io.StringIO(table_bytes.decode('utf-8')), delimiter='\t'))
    assert len(records) == 1
    record, = records
    assert record['Object Type'] == 'Sound SFX'
    assert record['Object Path'] == '<Sound SFX>WAAPI_LEGACY_IMPORT_TEST_TSV'
    assert 'Property[IsVoice]' not in record
    assert set(record) == {'Object Path', 'Object Type', 'Notes', 'Property[Volume]', 'Property[OverrideEffect]',
        'Reference[Effect0]', 'Reference[Effect1]', 'Property[RenderEffect1]'}
    assert record['Property[Volume]'] == '-9' and record['Property[OverrideEffect]'] == record['Property[RenderEffect1]'] == 'true'
    assert record['Notes'] == 'Keep legacy WAAPI_LEGACY_IMPORT_TEST_TSV'
    assert tsv['independent_owner']['properties']['IsVoice'] is False
    for row in effects[:2]:
        assert row['independent_source']['parent']['id'] == row['independent_owner']['id']
        assert row['media']['copied_sha256'] == row['media']['input_sha256']
        nodes = row['compiled_native_request']['args']['imports']
        assert len(nodes) == 2 and '@RenderEffect1' in nodes[0]
        assert not any(key.startswith('@') for key in nodes[1])
    if version == '2021.1':
        assert receipt['source_class_discovery'] == {'name': 'AudioSource', 'class_id': 16}
        assert all(row['independent_source']['type'] == 'AudioFileSource' and row['independent_source']['class_id'] == 16 for row in effects[:2])
        relation_calls = [call for call in receipt['calls'] if '--relationship' in call['argv']]
        assert relation_calls and all('--language' in call['argv'] and 'SFX' in call['argv']
            and call['argv'][call['argv'].index('--relationship') + 1] == 'children'
            and call['argv'][call['argv'].index('--max-results') + 1] == '100' for call in relation_calls)
        for row in effects[:2]:
            assert row['source_selection']['generic_active_source_mapping'] is False
            assert row['source_selection']['children'] == [row['source_selection']['selected']]
            assert row['source_selection']['selected']['id'] == row['independent_source']['id']
            assert row['source_selection']['sound_file']['original_file_path'] == row['independent_source']['original_file_path']
        assert category['read_view_scope'] == 'current_default_view_only_unobserved_platform_identity'
        assert all(row['read_view']['status'] == 'unobserved' for row in effects)
    else:
        assert all(row['read_view']['status'] == 'certified' for row in effects)
    output = tmp_path / 'legacy-import-category-writer.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(output))
    node = 'fixture::legacy_import_render'
    append_category_evidence(repo_root=tmp_path, candidate=runtime.candidate, version=runtime.version,
        host={'fixture_only': True}, categories=runtime.category_results,
        source={'fixture_only': True}, residual_state={'sandbox': 'deleted'},
        invocation={'selected_test_nodeids': [node], 'node_outcomes': [{'nodeid': node, 'outcome': 'PASS'}],
            'started_at_unix_ns': 1, 'finished_at_unix_ns': 2, 'phase': 'final', 'outcome': 'PASS'},
        transactions=exact_transaction_outcomes(runtime.state_dir))
    record = json.loads(output.read_text())
    assert record['contract'] == 'waapi-skill.host-category-evidence/v3' and record['categories'] == runtime.category_results
    assert len(record['transactions']) == 4 + save_count
    save_ids = {row['save']['preview']['transaction_id'] for row in prerequisites}
    assert all(row['state'] == ('result_schema_checked' if row['transaction_id'] in save_ids else 'verified')
        for row in record['transactions'])
    assert sum(row['transaction_id'] in save_ids for row in record['transactions']) == save_count
    assert record['categories'][0]['observation_sha256'] == hashlib.sha256(Path(category['observation_path']).read_bytes()).hexdigest()


def test_legacy_import_render_collector_rejects_live_source_move_after_gateway_verified(tmp_path, workflow, monkeypatch):
    import hashlib
    from tests.destructive.support.category_evidence import append_category_evidence, exact_transaction_outcomes
    runtime, commands, writes = _legacy_import_render_runtime(tmp_path, workflow, fault='independent-source-parent')
    with pytest.raises(AssertionError):
        workflow._collect_legacy_import_render_acceptance(runtime, prefix='WAAPI_LEGACY_IMPORT_TEST')
    category = runtime.category_results[-1]
    receipt = json.loads(Path(category['observation_path']).read_text())
    phase = receipt['transactions'][-1]
    assert phase['phase'] == 'existing_media_render' and phase['execute']['payload']['state'] == 'executed_unverified'
    assert phase['verify']['payload']['verified'] is True and phase['verify']['payload']['verification']['business_state_verified'] is True
    assert phase['effect_verified'] is False and receipt['business_effect_verified'] is False and receipt['failure']
    assert len(writes) == 2 and [row[0] for row in commands].count('execute') == 2
    assert [row[0] for row in commands].count('verify') == 2
    assert phase['independent_source']['parent']['id'] != phase['independent_owner']['id']
    output = tmp_path / 'legacy-import-failure-writer.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(output))
    node = 'fixture::legacy_import_source_failure'
    append_category_evidence(repo_root=tmp_path, candidate=runtime.candidate, version=runtime.version,
        host={'fixture_only': True}, categories=runtime.category_results, source={'fixture_only': True},
        residual_state={'sandbox': 'retained'}, invocation={'selected_test_nodeids': [node],
            'node_outcomes': [{'nodeid': node, 'outcome': 'FAIL'}], 'started_at_unix_ns': 1,
            'finished_at_unix_ns': 2, 'phase': 'final', 'outcome': 'FAIL'},
        transactions=exact_transaction_outcomes(runtime.state_dir))
    record = json.loads(output.read_text())
    assert record['categories'][0]['status'] == 'FAIL' and record['invocation']['outcome'] == 'FAIL'
    assert len(record['transactions']) == 2 and all(row['state'] == 'verified' for row in record['transactions'])
    assert record['categories'][0]['observation_sha256'] == hashlib.sha256(Path(category['observation_path']).read_bytes()).hexdigest()


@pytest.mark.parametrize('fault', ['selected-source-guid', 'independent-source-parent', 'partial-source',
    'ambiguous-source', 'empty-source', 'source-media-mismatch'])
def test_legacy_2021_source_oracle_stops_after_verified_import_on_mismatched_selection(tmp_path, workflow, fault):
    runtime, commands, writes = _legacy_import_render_runtime(tmp_path, workflow, '2021.1', fault=fault)
    with pytest.raises(AssertionError):
        workflow._collect_legacy_import_render_acceptance(runtime, prefix='WAAPI_LEGACY_SOURCE_NEGATIVE')
    receipt = json.loads(Path(runtime.category_results[-1]['observation_path']).read_text())
    assert receipt['failure'] and receipt['business_effect_verified'] is False
    phase = receipt['transactions'][-1]
    assert phase['phase'] == 'existing_media_render' and phase['verify']['payload']['verified'] is True
    assert phase['effect_verified'] is False
    assert len(writes) == 2
    assert [command[0] for command in commands].count('execute') == 3  # imports2 + save prerequisite1
    assert [command[0] for command in commands].count('verify') == 3
    if fault in {'empty-source', 'ambiguous-source', 'partial-source'}:
        children_calls = [call for call in receipt['calls'] if '--relationship' in call['argv']]
        assert len(children_calls) == 1
        assert children_calls[0]['exit_code'] == 0 and children_calls[0]['payload']['ok'] is True
        reason = 'source_child_page_incomplete' if fault == 'partial-source' else 'source_child_cardinality'
        assert reason in receipt['failure']['message']


def _soundcaster_dump_runtime(tmp_path, workflow, *, wrong_session=False):
    """Real Gateway and source XML; the JSON representation is deliberately fixture-only."""
    import shutil
    from tests.unit.test_console_project_alternatives_gateway import CliProjectTask
    task = CliProjectTask(tmp_path, '2024.1', 'ak.wwise.cli.dumpObjects')
    source = Path(__file__).resolve().parents[1] / '_org' / '2024.1'
    for directory in ('Soundcaster Sessions', 'Game Parameters', 'States', 'Switches'):
        shutil.copytree(source / directory, task.project_file.parent / directory)
    ids = ['{9C02096E-8E29-4029-9D49-778F85015C87}', '{1C5BA931-9550-4DC8-B1C7-13689B8AE813}',
           '{F4B8069C-3C15-4157-B570-8A41AB2463C2}']
    original = task.call
    writes, commands = [], []
    def call(uri, args=None, options=None):
        if uri == task.operation:
            writes.append(dict(args))
            assert args['content'] == 'propertyset' and 'no-session' not in args
            # No inference about actual Wwise dump shape follows from this fixture.
            rows = [{'id': identity, 'name': name, 'coincidental_value': 0.69}
                for identity, name in zip(ids, ['MIDI', 'Minigun', 'Music'])]
            if wrong_session:
                rows[1]['id'] = '{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}'
            Path(args['output']).write_text(json.dumps({'fixture_only': rows}), encoding='utf-8')
        return original(uri, args, options)
    task.call = call
    runtime = SimpleNamespace(version='2024.1', candidate='a' * 40, category_results=[],
        state_dir=tmp_path / 'state', env=task.env,
        sandbox=SimpleNamespace(sandbox_project=task.project_file, sandbox_root=tmp_path),
        lifecycle=SimpleNamespace(host='127.0.0.1', port=31337, waapi_url='ws://127.0.0.1:31337/waapi'), port=31337)
    def raw(argv):
        commands.append(list(argv))
        return workflow.waapi_gateway.execute_gateway(['--state-dir', str(runtime.state_dir), *argv],
            env=runtime.env, client_factory=lambda _: task)
    runtime.raw_gateway = raw
    return runtime, commands, writes, ids


def test_soundcaster_dump_observation_uses_gateway_and_actual_category_writer(tmp_path, workflow, monkeypatch):
    import hashlib
    from tests.destructive.support.category_evidence import append_category_evidence, exact_transaction_outcomes
    runtime, commands, writes, ids = _soundcaster_dump_runtime(tmp_path, workflow)
    category = workflow._collect_soundcaster_dump_observation(runtime)
    receipt_path = Path(category['observation_path'])
    receipt = json.loads(receipt_path.read_text())
    assert receipt['collection_complete'] is True and receipt['saved_model_preserved'] is True
    assert category['status'] == 'blocked' and receipt['business_preservation_verified'] is False
    assert receipt['session_values_observed'] is False and receipt['semantic_absence_proven'] is False
    assert [row['id'] for row in receipt['source_sessions']] == ids
    assert all(receipt['guid_occurrence_counts'][identity] > 0 for identity in ids)
    minigun = receipt['source_sessions'][1]
    assert next(row for row in minigun['rtpc'] if row['target_name'] == 'Engine_Load')['value_text'] == '0.69'
    assert receipt['source_binding_count'] == 100
    assert len(writes) == 1 and [row[0] for row in commands].count('execute') == 1
    assert [row[0] for row in commands].count('verify') == 1
    assert receipt['transaction']['verify_state'] == 'result_schema_checked'
    assert Path(receipt['dump_artifact']['archive_path']).read_bytes() == Path(writes[0]['output']).read_bytes()
    output = tmp_path / 'soundcaster-category.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(output))
    node = 'fixture::soundcaster_dump_diagnostic'
    append_category_evidence(repo_root=tmp_path, candidate=runtime.candidate, version=runtime.version,
        host={'fixture_only': True}, categories=runtime.category_results, source={'fixture_only': True},
        residual_state={'sandbox': 'deleted'}, invocation={'selected_test_nodeids': [node],
            'node_outcomes': [{'nodeid': node, 'outcome': 'PASS'}], 'started_at_unix_ns': 1,
            'finished_at_unix_ns': 2, 'phase': 'final', 'outcome': 'PASS'},
        transactions=exact_transaction_outcomes(runtime.state_dir))
    record = json.loads(output.read_text())
    assert record['contract'] == 'waapi-skill.host-category-evidence/v3'
    assert record['categories'][0]['status'] == 'blocked'
    assert record['categories'][0]['observation_sha256'] == hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    assert len(record['transactions']) == 1 and record['transactions'][0]['state'] == 'result_schema_checked'


def _stationary_tone_runtime(tmp_path, workflow, *, fault=None, version='2025.1'):
    import math
    import struct
    from tests.unit.test_host_ui_debug_business_adapter import _ToneFileClient, _env
    client = _ToneFileClient(tmp_path, version, is_command_line=fault != 'authoring')
    original = client.call
    writes, commands, native_files = [], [], {}
    def call(uri, args=None, options=None):
        if uri == 'ak.wwise.debug.generateToneWAV':
            writes.append(dict(args))
            assert set(args) == {'path', 'waveform', 'frequency', 'channelConfig', 'bitDepth',
                'sampleRate', 'attackTime', 'sustainTime', 'releaseTime', 'sustainLevel'}, args
            assert (args['waveform'], args['frequency'], args['channelConfig'], args['sampleRate'],
                args['attackTime'], args['sustainTime'], args['releaseTime']) == ('sine', 440, '1.0', 48000, 0, 0.25, 0)
            if fault == 'native-error':
                raise RuntimeError('fixture native generation outcome unknown')
            floating = args['bitDepth'] == 'float32'
            # Synthetic boundary bytes are not native evidence or a tolerance oracle.
            gain = {0: 1.0, -6: 0.5011872336272722}[args['sustainLevel']]
            samples = [gain * math.sin(2 * math.pi * 440 * i / 48000) for i in range(12000)]
            audio = b''.join(struct.pack('<f' if floating else '<h', value if floating else int(value * 32767)) for value in samples)
            fmt = struct.pack('<HHIIHH', 3 if floating else 1, 1, 48000, 192000 if floating else 96000,
                4 if floating else 2, 32 if floating else 16)
            raw = b'RIFF' + struct.pack('<I', 36 + len(audio)) + b'WAVEfmt ' + struct.pack('<I', 16) + fmt + b'data' + struct.pack('<I', len(audio)) + audio
            if fault == 'unrecognized-file': raw = b'fixture native writer bytes requiring investigation'
            client.artifact_bytes = raw
            if fault == 'missing-file': client.write_output = False
            native_files[args['path']] = raw
        result = original(uri, args, options)
        if uri == 'ak.wwise.core.getInfo':
            minor, build = {'2023.1': (19, 8928), '2024.1': (13, 9056), '2025.1': (7, 9143)}[version]
            result['version'].update(minor=minor, build=build, displayName=f'v{version}.{minor}.{build}')
            if fault == 'wrong-build': result['version']['build'] = 9999
        return result
    client.call = call
    env = {**_env(tmp_path, version), 'WWISE_EVIDENCE_DIR': str(tmp_path / 'dispatcher-evidence'),
        'WWISE_CATEGORY_EVIDENCE_PATH': str(tmp_path / 'category.jsonl')}
    source = tmp_path / 'immutable-source'; source.mkdir()
    source_project = source / 'SampleProject.wproj'; source_project.write_text('immutable source fixture')
    runtime = SimpleNamespace(version=version, candidate='a' * 40, category_results=[],
        state_dir=tmp_path / 'state', env=env, port=31337,
        sandbox=SimpleNamespace(sandbox_project=client.project_file, sandbox_root=tmp_path / 'sandbox-output',
            source_project=source_project, source_root=source),
        lifecycle=SimpleNamespace(host='127.0.0.1', port=31337, waapi_url='ws://127.0.0.1:31337/waapi'))
    runtime.sandbox.sandbox_root.mkdir()
    def raw(argv):
        commands.append(list(argv))
        return workflow.waapi_gateway.execute_gateway(['--state-dir', str(runtime.state_dir), *argv],
            env=env, client_factory=lambda _: client)
    runtime.raw_gateway = raw
    return runtime, commands, writes, native_files


def test_stationary_tone_diagnostic_archives_four_exact_artifacts_and_separate_public_transactions(tmp_path, workflow, monkeypatch):
    import hashlib
    runtime, commands, writes, native_files = _stationary_tone_runtime(tmp_path, workflow)
    category = workflow._collect_stationary_tone_characterization(runtime)
    receipt_path = Path(category['observation_path'])
    receipt = json.loads(receipt_path.read_text())
    assert receipt['collection_complete'] is True and receipt['business_effect_verified'] is False
    assert category['status'] == 'blocked' and category['diagnostic_only'] is True
    assert category['observation_sha256'] == hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    assert [(p['bit_depth'], p['sustain_db']) for p in receipt['phases']] == [
        ('int16', 0), ('int16', -6), ('float32', 0), ('float32', -6)]
    assert len(writes) == 4 and len({p['transaction_id'] for p in receipt['phases']}) == 4
    assert sum(argv[0] == 'execute' for argv in commands) == 4
    for phase in receipt['phases']:
        archived = Path(phase['wav']['archive_path']).read_bytes()
        assert archived == native_files[phase['output_path']]
        assert hashlib.sha256(archived).hexdigest() == phase['wav']['archive_proof']['sha256']
        shown = json.loads(Path(phase['transaction']['path']).read_text())
        assert shown['transaction_id'] == phase['transaction_id'] and shown['state'] == 'verified'
        assert shown['artifact']['request']['arguments']['args'] == next(row for row in writes if row['path'] == phase['output_path'])
        assert shown['events'] and phase['verification']['business_state_verified'] is True
    assert receipt['get_info']['isCommandLine'] is True
    assert receipt['get_info']['version']['build'] == 9143
    assert receipt['native_evidence'] and receipt['lifecycle_final_reference']['cleanup_status'] == 'unresolved_until_final_row'
    from tests.destructive.support.category_evidence import append_category_evidence, exact_transaction_outcomes
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', runtime.env['WWISE_CATEGORY_EVIDENCE_PATH'])
    node = 'fixture::stationary_tone_characterization'
    append_category_evidence(repo_root=tmp_path, candidate=runtime.candidate, version=runtime.version,
        host={'fixture_only': True}, categories=runtime.category_results,
        source={'fixture_only': True, 'hash_before': 'same', 'hash_after': 'same'},
        residual_state={'sandbox': 'deleted', 'process_cleanup': 'cleaned', 'residual_processes': []},
        invocation={'selected_test_nodeids': [node], 'node_outcomes': [{'nodeid': node, 'outcome': 'PASS'}],
            'started_at_unix_ns': 1, 'finished_at_unix_ns': 2, 'phase': 'final', 'outcome': 'PASS'},
        transactions=exact_transaction_outcomes(runtime.state_dir))
    record = json.loads(Path(runtime.env['WWISE_CATEGORY_EVIDENCE_PATH']).read_text())
    assert len(record['transactions']) == 4 and all(row['state'] == 'verified' for row in record['transactions'])
    assert record['categories'][0]['status'] == 'blocked' and record['categories'][0]['business_effect_verified'] is False
    assert record['categories'][0]['observation_sha256'] == hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    assert record['source']['hash_before'] == record['source']['hash_after']
    assert record['residual_state']['process_cleanup'] == 'cleaned'
    calls_before = len(commands)
    with pytest.raises(AssertionError, match='overwrite'):
        workflow._collect_stationary_tone_characterization(runtime)
    assert len(commands) == calls_before and len(writes) == 4


def test_stationary_tone_diagnostic_late_archive_failure_keeps_incomplete_nonpass_receipt(tmp_path, workflow, monkeypatch):
    runtime, commands, writes, _ = _stationary_tone_runtime(tmp_path, workflow)
    original = workflow.os.open
    def fail_archive(path, flags, *args, **kwargs):
        if Path(path).name == 'native-0.json':
            raise OSError('fixture native evidence destination unavailable')
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(workflow.os, 'open', fail_archive)
    with pytest.raises(OSError, match='destination unavailable'):
        workflow._collect_stationary_tone_characterization(runtime)
    receipt = json.loads((runtime.state_dir / 'tone-stationary-characterization.json').read_text())
    assert runtime.category_results[-1]['status'] == 'FAIL'
    assert receipt['collection_complete'] is False and receipt['business_effect_verified'] is False
    assert receipt['archive_failure']['type'] == 'OSError'
    assert len(writes) == 4 and sum(argv[0] == 'execute' for argv in commands) == 4
    assert all(Path(phase['wav']['archive_path']).is_file() for phase in receipt['phases'])


@pytest.mark.parametrize('fault,expected_writes', [('authoring', 0), ('wrong-build', 0), ('native-error', 1), ('missing-file', 1)])
def test_stationary_tone_diagnostic_stops_on_wrong_host_or_generation_failure_without_retry(tmp_path, workflow, fault, expected_writes):
    runtime, commands, writes, _ = _stationary_tone_runtime(tmp_path, workflow, fault=fault)
    with pytest.raises(Exception):
        workflow._collect_stationary_tone_characterization(runtime)
    receipt = json.loads((runtime.state_dir / 'tone-stationary-characterization.json').read_text())
    assert runtime.category_results[-1]['status'] == 'FAIL'
    assert receipt['collection_complete'] is False and receipt['business_effect_verified'] is False
    assert len(writes) == expected_writes and sum(argv[0] == 'execute' for argv in commands) == expected_writes
    assert not any(argv[0] == 'verify' for argv in commands)
    assert receipt['failure'] and receipt['native_evidence']
    if expected_writes:
        assert receipt['phases'][0]['execution_attempted'] is True
        final = json.loads(Path(receipt['phases'][0]['transaction']['path']).read_text())
        assert final['state'] == ('indeterminate' if fault == 'native-error' else 'executed_unverified')


def test_stationary_tone_diagnostic_retains_unrecognized_output_and_failed_verification_without_effect_credit(tmp_path, workflow):
    runtime, commands, writes, native_files = _stationary_tone_runtime(tmp_path, workflow, fault='unrecognized-file')
    category = workflow._collect_stationary_tone_characterization(runtime)
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert category['status'] == 'blocked' and receipt['collection_complete'] is True
    assert receipt['business_effect_verified'] is False and len(writes) == 4
    for phase in receipt['phases']:
        assert Path(phase['wav']['archive_path']).read_bytes() == native_files[phase['output_path']]
        assert phase['verification']['exit_code'] == 2 and phase['verification']['state'] == 'verification_failed'
        assert phase['signal_verified'] is False


def test_soundcaster_dump_wrong_guid_cannot_certify_same_named_session_values(tmp_path, workflow, monkeypatch):
    import hashlib
    from tests.destructive.support.category_evidence import append_category_evidence, exact_transaction_outcomes
    runtime, commands, writes, ids = _soundcaster_dump_runtime(tmp_path, workflow, wrong_session=True)
    category = workflow._collect_soundcaster_dump_observation(runtime)
    receipt_path = Path(category['observation_path'])
    receipt = json.loads(receipt_path.read_text())
    assert len(writes) == 1 and [row[0] for row in commands].count('execute') == 1
    assert receipt['transaction']['execute_state'] == 'executed_unverified'
    assert receipt['transaction']['verify_state'] == 'result_schema_checked'
    assert receipt['transaction']['business_state_verified'] is False
    assert receipt['collection_complete'] and receipt['saved_model_preserved']
    assert receipt['missing_session_guid_tokens'] == [ids[1]]
    assert receipt['guid_occurrence_counts'][ids[1]] == 0
    native = json.loads(Path(receipt['dump_artifact']['archive_path']).read_text())
    assert native['fixture_only'][1]['name'] == 'Minigun'
    assert native['fixture_only'][1]['coincidental_value'] == 0.69
    assert not any(row['id'] == ids[1] for row in receipt['session_guid_occurrences'])
    assert receipt['session_values_observed'] is receipt['business_preservation_verified'] is False
    assert receipt['semantic_absence_proven'] is False and category['status'] == 'blocked'
    output = tmp_path / 'soundcaster-wrong-guid-category.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(output))
    node = 'fixture::soundcaster_wrong_guid_diagnostic'
    append_category_evidence(repo_root=tmp_path, candidate=runtime.candidate, version=runtime.version,
        host={'fixture_only': True}, categories=runtime.category_results, source={'fixture_only': True},
        residual_state={'sandbox': 'deleted'}, invocation={'selected_test_nodeids': [node],
            'node_outcomes': [{'nodeid': node, 'outcome': 'PASS'}], 'started_at_unix_ns': 1,
            'finished_at_unix_ns': 2, 'phase': 'final', 'outcome': 'PASS'},
        transactions=exact_transaction_outcomes(runtime.state_dir))
    record = json.loads(output.read_text())
    assert record['categories'][0]['status'] == 'blocked'
    assert record['categories'][0]['observation_sha256'] == hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    assert len(record['transactions']) == 1 and record['transactions'][0]['state'] == 'result_schema_checked'


@pytest.mark.parametrize('version,build', [('2023.1', '2023.1.19.8928'), ('2024.1', '2024.1.13.9056')])
def test_stationary_tone_diagnostic_uses_matching_pinned_console_catalog_without_effect_credit(tmp_path, workflow, version, build):
    runtime, commands, writes, _ = _stationary_tone_runtime(tmp_path, workflow, version=version)
    category = workflow._collect_stationary_tone_characterization(runtime)
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert receipt['version'] == version and receipt['native_catalog']['build'] == build
    assert len(receipt['native_catalog']['content_sha256']) == 64
    assert len(writes) == 4 and sum(argv[0] == 'execute' for argv in commands) == 4
    assert len(set(receipt['lifecycle_final_reference']['transaction_ids'])) == 4
    assert receipt['collection_complete'] is True and receipt['business_effect_verified'] is False
    assert category['status'] == 'blocked' and category['diagnostic_only'] is True


def _multisource_public_runtime(tmp_path, workflow, *, fault=None, version='2021.1'):
    """Fake public replies exercise collector protocol/oracle only, not native admission."""
    from copy import deepcopy
    import shutil
    import uuid
    import xml.etree.ElementTree as ET
    sandbox = tmp_path / 'sandbox'; sandbox.mkdir()
    project = sandbox / 'Fixture.wproj'; project.write_text('<WwiseDocument/>')
    unit_path = sandbox / 'Actor-Mixer Hierarchy' / 'Default Work Unit.wwu'; unit_path.parent.mkdir()
    guid = lambda value: '{' + str(uuid.UUID(int=value)).upper() + '}'
    unit, platform, windows = guid(1), guid(2), guid(3)
    objects = {unit: {'id': unit, 'name': 'Default Work Unit', 'type': 'WorkUnit', 'class_id': 1638416,
        'path': workflow.ACTOR_MIXER_PARENT, 'parent': None, 'notes': '', 'file_path': str(unit_path)},
        platform: {'id': platform, 'name': 'Mac', 'type': 'Platform', 'class_id': 4, 'path': r'\Platforms\Mac', 'parent': None, 'notes': ''}}
    if version == '2022.1':
        objects[windows] = {'id': windows, 'name': 'Windows', 'type': 'Platform', 'class_id': 4,
            'path': r'\Platforms\Windows', 'parent': None, 'notes': ''}
    commands, drafts, transactions = [], {}, {}
    state = {'copies': 0, 'copy_attempts': 0, 'imports': 0, 'deletes': 0, 'active': {}, 'platform_active': {}, 'selections': 0, 'selection_attempts': 0}
    def saved_xml():
        root = ET.Element('WwiseDocument'); work = ET.SubElement(root, 'WorkUnit', ID=unit)
        children = ET.SubElement(work, 'ChildrenList')
        for row in list(objects.values()):
            if row['type'] != 'Sound': continue
            sound = ET.SubElement(children, 'Sound', ID=row['id'], Name=row['name'])
            sources = ET.SubElement(sound, 'ChildrenList')
            members = [item for item in objects.values() if item['type'] == 'AudioFileSource' and item['parent']['id'] == row['id']]
            for source in members:
                node = ET.SubElement(sources, 'AudioFileSource', ID=source['id'], Name=source['name'])
                ET.SubElement(node, 'Language').text = source['source_language']['name']
                ET.SubElement(node, 'AudioFile').text = Path(source['original_file_path']).name
            active = state['active'][row['id']]
            refs = ET.SubElement(sound, 'ActiveSourceList')
            choices = [(name, source) for (owner, name), source in state['platform_active'].items() if owner == row['id']]
            for name, source in choices or [('Linked', active)]:
                ET.SubElement(refs, 'ActiveSource', ID=guid(999) if fault == 'xml-guid' else source,
                    Name=objects[source]['name'], Platform=name)
        unit_path.write_bytes(ET.tostring(root))
    def raw(argv):
        argv = list(argv); commands.append(argv)
        payload = {'ok': True, 'detected_version': version,
            'endpoint': {'host': '127.0.0.1', 'port': 31337, 'url': 'ws://127.0.0.1:31337/waapi'}}
        command = argv[0]
        if command == 'metadata':
            payload['agent_result'] = {'complete': True, 'types': [
                {'name': name, 'classId': value, 'type': 'WObject', 'selection': name}
                for name, value in [('Sound', 65552), ('AudioSource' if version == '2021.1' else 'AudioFileSource', 16), ('WorkUnit', 1638416), ('Platform', 4)]]}
        elif command == 'query-object':
            if '--type-selection' in argv: found = [row for row in objects.values() if row['type'] == 'Platform']
            elif '--path-segment' in argv:
                path = '\\' + '\\'.join(argv[i + 1] for i, arg in enumerate(argv) if arg == '--path-segment')
                found = [row for row in objects.values() if row['path'] == path]
            else: found = [objects[argv[argv.index('--exact-id') + 1]]] if argv[argv.index('--exact-id') + 1] in objects else []
            if '--relationship' in argv:
                owner = argv[argv.index('--exact-id') + 1]
                found = [row for row in objects.values() if isinstance(row.get('parent'), dict) and row['parent']['id'] == owner]
                if fault != 'same-order': found = sorted(found, key=lambda row: row['name'])
            if version == '2022.1':
                name = 'Windows' if '--platform' in argv and argv[argv.index('--platform') + 1] in {windows, 'Windows'} else 'Mac'
                found = [deepcopy(row) for row in found]
                for row in found:
                    if row['type'] == 'Sound':
                        source = state['platform_active'].get((row['id'], name), state['active'][row['id']])
                        row.update(original_file_path=objects[source]['original_file_path'], active_source={'id': source, 'name': objects[source]['name']})
            includes = [argv[i + 1].replace('-', '_') for i, arg in enumerate(argv) if arg == '--include']
            keys = {'id', 'name', 'type', 'path', *includes}
            found = [{key: deepcopy(value) for key, value in row.items()
                if key in keys or key == 'properties' and '--include-field' in argv} for row in found]
            if fault == 'scalar-parent':
                for row in found:
                    for key in ('parent', 'work_unit'):
                        if isinstance(row.get(key), dict): row[key] = row[key]['id']
            payload.update(objects=found, count=len(found), projection_complete=True, limit_reached=False)
        elif command == 'request-schema':
            payload.update(input_shape='business_declaration', continuation={'subcommand': 'draft-start',
                'gateway_argv': ['draft-start', 'ak.wwise.core.project.save'], 'copy_exactly': True, 'append_arguments': 'forbidden'})
        elif command == 'draft-start':
            identity = 'draft-' + str(len(drafts)); drafts[identity] = {'operation': argv[1], 'revision': 1, 'roles': {}, 'rows': []}
            payload.update(draft={'draft_id': identity, 'revision': 1}, task_authority='authority')
        elif command in {'draft-bind-object', 'draft-declare-new', 'draft-declare-object-change', 'draft-declare-core-plan', 'draft-declare-project-setting-plan', 'draft-check', 'preview-from-draft'}:
            draft = drafts[argv[1]]
            if command == 'draft-check' and draft['operation'] == 'object.copy' and fault == 'preparation':
                return 2, {**payload, 'ok': False, 'error_code': 'INVALID_TARGET',
                    'recovery': {'project_write_outcome': 'no_project_write_in_this_invocation'}}
            if command == 'draft-check' and draft['operation'] == 'ak.wwise.core.sound.setActiveSource' and fault == 'select-preparation':
                return 2, {**payload, 'ok': False, 'error_code': 'INVALID_TARGET',
                    'recovery': {'project_write_outcome': 'no_project_write_in_this_invocation'}}
            if command == 'draft-bind-object':
                role = argv[argv.index('--role') + 1] if '--role' in argv else 'object'
                draft['roles'][role] = argv[argv.index('--object-id') + 1]
                payload['bound_object'] = {'handle': 'handle-' + role}
            elif command == 'draft-declare-new': draft['rows'].append(argv)
            elif command == 'draft-declare-project-setting-plan': draft['platform_name'] = argv[argv.index('--platform-name') + 1]
            elif command == 'preview-from-draft':
                identity = 'tx-' + str(len(transactions)); transactions[identity] = draft
                payload.update(transaction_id=identity, artifact_hash='hash-' + identity)
            draft['revision'] += 1
            payload['draft'] = {'draft_id': argv[1], 'revision': draft['revision']}
        elif command == 'transaction-show': payload['confirmation'] = {'token': 'token'}
        elif command == 'confirm': pass
        elif command in {'execute', 'verify'}:
            draft = transactions[argv[1]]; operation = draft['operation']
            if command == 'verify':
                payload.update(state='result_schema_checked' if operation == 'ak.wwise.core.project.save' else 'verified',
                    verified=operation != 'ak.wwise.core.project.save', verification={'status': 'result_schema_checked' if operation == 'ak.wwise.core.project.save' else 'verified',
                        'business_state_verified': operation != 'ak.wwise.core.project.save'})
            else:
                payload.update(state='executed_unverified', automatic_retry=False)
                if operation == 'ak.wwise.core.project.save': saved_xml()
                elif operation == 'audio.import':
                    state['imports'] += 1
                    assert len(draft['rows']) == (6 if version == '2021.1' else 2)
                    for index, row in enumerate(draft['rows']):
                        fields = {row[i + 1]: row[i + 2] for i, arg in enumerate(row) if arg == '--field'}
                        language, source_file = fields['language'], Path(fields['media_file'])
                        voice = row[row.index('--kind') + 1] == 'sound-voice'
                        assert voice == (language == 'English(US)')
                        assert row[row.index('--parent-handle') + 1] == 'handle-object'
                        destination = sandbox / 'Originals' / ('Voices/English(US)' if voice else 'SFX') / source_file.name
                        destination.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source_file, destination)
                        owner_id, source_id = guid(100 + index), guid(200 + index)
                        name = row[row.index('--name') + 1]
                        objects[owner_id] = {'id': owner_id, 'name': name, 'type': 'Sound', 'class_id': 65552,
                            'path': workflow.ACTOR_MIXER_PARENT + '\\' + name, 'parent': {'id': unit}, 'notes': '',
                            'properties': {'IsVoice': voice}, 'work_unit': {'id': unit}, 'original_file_path': str(destination)}
                        objects[source_id] = {'id': source_id, 'name': source_file.stem, 'type': 'AudioFileSource', 'class_id': 16,
                            'path': objects[owner_id]['path'] + '\\' + source_file.stem, 'parent': {'id': owner_id}, 'notes': '',
                            'source_language': {'name': language}, 'original_file_path': str(destination)}
                        state['active'][owner_id] = source_id
                elif operation == 'object.copy':
                    state['copy_attempts'] += 1
                    if fault in {'native', 'indeterminate'}:
                        dispatch = {'ok': False, 'failure_origin': 'exception' if fault == 'native' else 'missing_response'}
                        if fault == 'native': dispatch['waapi_error_uri'] = 'ak.wwise.invalid_arguments'
                        return 2, {**payload, 'ok': False, 'state': 'indeterminate', 'dispatch_result': dispatch}
                    source = objects[draft['roles']['object']]; parent = objects[draft['roles']['parent']]
                    assert source['type'] == 'AudioFileSource' and parent['type'] == 'Sound'
                    state['copies'] += 1
                    if fault == 'original-source-reset':
                        objects[state['active'][parent['id']]]['notes'] = 'Unexpected reset'
                    if fault != 'one-child':
                        identity = guid(300 + state['copies'])
                        objects[identity] = {**deepcopy(source), 'id': identity, 'parent': {'id': parent['id']},
                            'path': parent['path'] + '\\' + source['name']}
                elif operation == 'ak.wwise.core.sound.setActiveSource':
                    state['selection_attempts'] += 1
                    if fault in {'select-native', 'select-indeterminate'}:
                        dispatch = {'ok': False, 'failure_origin': 'exception' if fault == 'select-native' else 'missing_response'}
                        if fault == 'select-native': dispatch['waapi_error_uri'] = 'ak.wwise.invalid_arguments'
                        return 2, {**payload, 'ok': False, 'state': 'indeterminate', 'dispatch_result': dispatch}
                    state['selections'] += 1
                    owner, source = draft['roles']['sound'], draft['roles']['source']
                    if fault == 'linked-selection': state['active'][owner] = source
                    else: state['platform_active'][(owner, draft['platform_name'])] = source
                elif operation == 'object.delete':
                    state['deletes'] += 1
                    identity = draft['roles']['object']
                    for key in list(objects):
                        if key == identity or objects[key].get('parent') == {'id': identity}: del objects[key]
                else: raise AssertionError(operation)
        else: raise AssertionError(argv)
        return 0, payload
    runtime = SimpleNamespace(version=version, state_dir=tmp_path / 'state', candidate='program-fixture',
        category_results=[], raw_gateway=raw, lifecycle=SimpleNamespace(host='127.0.0.1', waapi_url='ws://127.0.0.1:31337/waapi'),
        port=31337, sandbox=SimpleNamespace(sandbox_path=sandbox, sandbox_project=project))
    return runtime, commands, state


def test_platform_active_source_characterizer_reuses_one_pair_and_saves_distinct_view_choices(tmp_path, workflow):
    runtime, commands, state = _multisource_public_runtime(tmp_path, workflow, version='2022.1')
    category = workflow._collect_multisource_active_selection_diagnostic(runtime, prefix='WAAPI_PLATFORM_TEST', platform_characterization=True)
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert category['status'] == 'PASS', receipt.get('failure')
    assert state['imports'] == 1 and state['copies'] == 1 and state['selections'] == 2 and state['deletes'] == 2
    assert len([row for row in commands if row[0] == 'draft-declare-new']) == 2
    assert receipt['oracle']['platform_choices_diverge'] is True
    assert receipt['path_join_matches_saved_oracle'] is True
    assert sum(receipt['call_counts'].values()) == len(commands) <= receipt['limits']['public_calls'] == 111
    assert receipt['generic_active_source_mapping'] is False and receipt['native_absence_proven'] is False


@pytest.mark.parametrize('fault,outcome,attempts', [
    ('select-preparation', 'skill_preparation_rejected', 0),
    ('select-native', 'native_rejection_reported', 1),
    ('select-indeterminate', 'execution_indeterminate', 1),
    ('linked-selection', 'saved_oracle_blocked', 2),
    ('xml-guid', 'saved_oracle_blocked', 2),
])
def test_platform_active_source_characterizer_preserves_rejections_and_never_replays_linked_surrogate(tmp_path, workflow, fault, outcome, attempts):
    runtime, commands, state = _multisource_public_runtime(tmp_path, workflow, version='2022.1', fault=fault)
    category = workflow._collect_multisource_active_selection_diagnostic(runtime, prefix='WAAPI_PLATFORM_TEST', platform_characterization=True)
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert category['status'] == 'blocked' and receipt['outcome'] == outcome, receipt.get('failure')
    assert state['selection_attempts'] == attempts and state['deletes'] == 0
    assert state['imports'] == 1 and state['copies'] == 1
    assert receipt['collection_complete'] is False and receipt['native_absence_proven'] is False
    assert len([row for row in commands if row[:2] == ['draft-start', 'ak.wwise.core.sound.setActiveSource']]) <= 2


@pytest.mark.parametrize('fault', [None, 'scalar-parent'])
def test_multisource_collector_public_setup_saved_oracle_and_cleanup(tmp_path, workflow, fault):
    runtime, commands, state = _multisource_public_runtime(tmp_path, workflow, fault=fault)
    category = workflow._collect_2021_multisource_active_selection_diagnostic(runtime, prefix='WAAPI_MULTI_TEST')
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert category['status'] == 'PASS', receipt.get('failure')
    assert state == {**state, 'imports': 1, 'copies': 3, 'copy_attempts': 3, 'deletes': 6}
    assert len([row for row in commands if row[0] == 'draft-declare-new']) == 6
    assert receipt['oracle']['ordering_counterexample'] == {'public': True, 'xml': False}
    assert receipt['path_join_matches_saved_oracle'] is True and receipt['object_cleanup'] == 'verified'
    assert receipt['generic_active_source_mapping'] is False and receipt['native_absence_proven'] is False
    assert sum(receipt['call_counts'].values()) == len(commands) <= receipt['limits']['public_calls']
    assert not any('active-source' in item or 'activeSource' in item for command in commands for item in command)


@pytest.mark.parametrize('fault,outcome,attempts', [('preparation', 'skill_preparation_rejected', 0),
    ('native', 'native_copy_rejection_reported', 1), ('indeterminate', 'execution_indeterminate', 1)])
def test_multisource_collector_stops_after_distinct_copy_setup_failures(tmp_path, workflow, fault, outcome, attempts):
    runtime, commands, state = _multisource_public_runtime(tmp_path, workflow, fault=fault)
    category = workflow._collect_2021_multisource_active_selection_diagnostic(runtime, prefix='WAAPI_MULTI_TEST')
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert category['status'] == 'blocked' and receipt['outcome'] == outcome, receipt.get('failure')
    assert state['copy_attempts'] == attempts and state['deletes'] == 0
    assert len([row for row in commands if row[:2] == ['draft-start', 'object.copy']]) == 1
    assert receipt['collection_complete'] is False and receipt['native_absence_proven'] is False


@pytest.mark.parametrize('fault,outcome', [('one-child', 'setup_cardinality_blocked'),
    ('xml-guid', 'saved_oracle_blocked'), ('same-order', 'ordering_counterexample_unproven'),
    ('original-source-reset', 'setup_cardinality_blocked')])
def test_multisource_collector_requires_two_sources_exact_xml_active_guid_and_order_counterexample(tmp_path, workflow, fault, outcome):
    runtime, _commands, state = _multisource_public_runtime(tmp_path, workflow, fault=fault)
    category = workflow._collect_2021_multisource_active_selection_diagnostic(runtime, prefix='WAAPI_MULTI_TEST')
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert category['status'] == 'blocked' and receipt['outcome'] == outcome, receipt.get('failure')
    assert state['deletes'] == 0 and receipt['collection_complete'] is False
    if fault == 'one-child':
        assert state['copy_attempts'] == 1 and 'oracle' not in receipt
    elif fault == 'same-order':
        assert receipt['path_join_matches_saved_oracle'] is True
        assert receipt['oracle']['ordering_discrimination'] is False


def _planned_source_characterization_runtime(tmp_path, workflow, *, fault=None):
    """Public Gateway plus independently stored native constructor results."""
    from copy import deepcopy
    import uuid
    from tests.unit.test_sound_voice_creation_gateway import planned_source_task, SOURCE_CLASS, JAPANESE, SECOND
    task = planned_source_task(tmp_path, '2025.1')
    captured = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/metadata/tone-source-2025.1-properties.json').read_text())
    assert captured['type'] == {'classId': SOURCE_CLASS, 'name': 'Wwise Tone Generator', 'type': 'Source'}
    task.metadata.pop('Frequency')
    task.metadata.update(deepcopy(captured['metadata']))
    if fault == 'missing-field':
        task.metadata.pop('StartFreq')
    task.languages = deepcopy(captured['project_languages'])
    language_objects = deepcopy(captured['language_objects'])
    if fault == 'language-membership':
        language_objects = [row for row in language_objects if row['name'] != 'English(US)']
    task.types.append({'name': 'Language', 'classId': 4915216, 'type': 'WObject'})
    french = '{CDCDCDCD-CDCD-CDCD-CDCD-CDCDCDCDCDCD}'
    if fault == 'two-locales':
        task.languages.append({'id': french, 'name': 'French', 'shortId': 4})
        language_objects.append({'id': french, 'name': 'French', 'type': 'Language', 'path': 'French'})
    task.objects[SECOND]['path'] = r'\Containers\Default Work Unit'
    native = tmp_path / 'native'; native.mkdir()
    task.env['WWISE_EVIDENCE_DIR'] = str(native)
    task.env['WWISE_CATEGORY_EVIDENCE_PATH'] = str(tmp_path / 'category.jsonl')
    created_sources, writes, commands = [], [], []
    def create(node, parent, *, owned=False):
        identity = '{' + str(uuid.uuid4()).upper() + '}'
        if node['type'] == 'Source' and fault == 'reuse' and created_sources:
            identity = created_sources[0]
        row = {'id': identity, 'name': node['name'], 'type': 'SourcePlugin' if node['type'] == 'Source' else 'Sound',
            'classId': SOURCE_CLASS if node['type'] == 'Source' else 65552,
            'path': task.objects[parent]['path'] + '\\' + node['name'], 'parent': {'id': parent},
            'notes': node.get('notes', ''), **{key: deepcopy(value) for key, value in node.items() if key.startswith('@')}}
        if node['type'] == 'Source':
            row.setdefault('@StartFreq', captured['metadata']['StartFreq']['default'])
            row.setdefault('@WaveType', captured['metadata']['WaveType']['default'])
            if fault == 'ignored-real-field': row['@StartFreq'] = 220
            row['audioSource:language'] = {'name': node.get('language', 'SFX')}
            if fault == 'ignored-language' and node.get('language'): row['audioSource:language']['name'] = 'SFX'
            created_sources.append(identity)
        else:
            row.setdefault('@IsVoice', False)
            row['activeSource'] = None
        task.objects[identity] = row
        children = [create(child, identity) for child in node.get('children', [])]
        return {'id': identity, 'name': row['name'], **({'children': children} if children else {})}
    task._create = create
    original = task.call
    def call(uri, args=None, options=None):
        if uri.endswith('object.get') and (args or {}).get('waql', '').startswith('from type Language '):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': deepcopy(language_objects)}
        expression = (args or {}).get('waql', '')
        if uri.endswith('object.get') and expression.startswith('from object "'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            selected = expression.split('"')[1]
            rows = [row for row in task.objects.values() if row['id'] == selected or row['path'] == selected]
            if ' select children ' in expression:
                assert len(rows) == 1, args
                rows = [row for row in task.objects.values() if row.get('parent') == {'id': rows[0]['id']}]
            return {'return': task.project_rows(rows, options or {})}
        if uri.endswith('object.set'): writes.append(deepcopy(args))
        result = original(uri, args, options)
        if uri.endswith('object.set') and fault == 'extra-child' and len(writes) == 2:
            original_owner = task.objects[created_sources[0]]['parent']['id']
            extra = '{FAFAFAFA-FAFA-FAFA-FAFA-FAFAFAFAFAFA}'
            task.objects[extra] = {'id': extra, 'name': 'Unexpected retained child', 'type': 'SourcePlugin',
                'classId': SOURCE_CLASS, 'path': task.objects[original_owner]['path'] + r'\Unexpected retained child',
                'parent': {'id': original_owner}, 'notes': 'Unexpected'}
        if uri.endswith('getInfo'):
            result['version'].update(minor=7, build=9143, displayName='v2025.1.7.9143')
        return result
    task.call = call
    runtime = SimpleNamespace(version='2025.1', candidate='a' * 40, category_results=[],
        state_dir=tmp_path / 'state', env=task.env, port=31337,
        sandbox=SimpleNamespace(source_project=task.project_file),
        lifecycle=SimpleNamespace(host='127.0.0.1', port=31337, waapi_url='ws://127.0.0.1:31337/waapi'))
    def raw(argv):
        commands.append(list(argv))
        code, result = task.run(*argv)
        if argv[0] == 'draft-discover-fields' and code == 0 and fault == 'ambiguous-field':
            meaning, = result['meaning_results']
            selected, = [row for row in meaning['candidates'] if row['metadata']['name'] == 'StartFreq']
            meaning['candidates'].append(deepcopy(selected))
            meaning['candidate_count'] += 1
            result['candidate_count'] += 1
        return code, result
    runtime.raw_gateway = raw
    return runtime, commands, writes, task


@pytest.mark.parametrize('locales', ['captured-single', 'two-locales'])
def test_planned_source_collector_preserves_three_transactions_and_original_source_identity(tmp_path, workflow, locales):
    import hashlib
    runtime, commands, writes, task = _planned_source_characterization_runtime(tmp_path, workflow, fault='two-locales' if locales == 'two-locales' else None)
    category = workflow._collect_planned_source_characterization(runtime, prefix='WAAPI_SOURCE_TEST')
    receipt_path = Path(category['observation_path'])
    receipt = json.loads(receipt_path.read_text())
    assert category['status'] == 'PASS' and receipt['collection_complete'] is True
    assert receipt['business_effect_verified'] is True
    assert category['observation_sha256'] == hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    assert [p['case'] for p in receipt['phases']] == ['sfx', 'voice-explicit-source', 'voice-default-source']
    assert len(writes) == 3 and len({p['transaction_id'] for p in receipt['phases']}) == 3
    for args in writes:
        source = args['objects'][0]['children'][0]['children'][0]
        assert source['@StartFreq'] == 440 and '@Frequency' not in source
    assert sum(argv[0] == 'execute' for argv in commands) == 3
    assert len(commands) == receipt['limits']['calls'] == 74
    ids = [p['independent_source']['id'] for p in receipt['phases']]
    assert len(set(ids)) == 3
    assert receipt['phases'][1]['retained_before'][0]['source'] == receipt['phases'][0]['independent_source']
    assert receipt['phases'][2]['retained_after'] == receipt['phases'][2]['retained_before']
    assert (receipt['phases'][1]['construction_language'] != receipt['phases'][1]['source_language']) is (locales == 'two-locales')
    assert receipt['distinct_language_disambiguation'] is (locales == 'two-locales')
    assert [row['name'] for row in receipt['language_choices']] == (['English(US)', 'French'] if locales == 'two-locales' else ['English(US)'])
    for phase in receipt['phases']:
        assert phase['frequency_field']['metadata']['name'] == 'StartFreq'
        assert phase['frequency_field']['metadata']['dependencies'][0]['property'] == 'WaveType'
        assert phase['independent_source']['properties']['StartFreq'] == 440
    assert receipt['phases'][2]['source_language'] is None
    assert receipt['phases'][2]['source_language_effect'] == 'observed_default_only_no_inheritance_claim'
    assert receipt['get_info']['version']['build'] == 9143
    assert receipt['native_evidence'] and receipt['lifecycle_final_reference']['cleanup_status'] == 'unresolved_until_final_row'
    assert receipt['lifecycle_final_reference']['transaction_ids'] == [p['transaction_id'] for p in receipt['phases']]
    for evidence in receipt['native_evidence']:
        raw = Path(evidence['archive_path']).read_bytes()
        assert raw == Path(evidence['native_path']).read_bytes()
        assert len(raw) == evidence['size'] and hashlib.sha256(raw).hexdigest() == evidence['sha256']


@pytest.mark.parametrize('fault', ['reuse', 'ignored-language', 'extra-child'])
def test_planned_source_collector_preserves_failed_native_effect_and_never_retries(tmp_path, workflow, fault):
    runtime, commands, writes, task = _planned_source_characterization_runtime(tmp_path, workflow, fault=fault)
    with pytest.raises(AssertionError):
        workflow._collect_planned_source_characterization(runtime, prefix='WAAPI_SOURCE_TEST')
    receipt = json.loads((runtime.state_dir / 'planned-source-characterization.json').read_text())
    assert runtime.category_results[-1]['status'] == 'FAIL'
    assert receipt['collection_complete'] is False and receipt['business_effect_verified'] is False
    assert len(writes) == 2
    ids = [argv[1] for argv in commands if argv[0] == 'execute']
    assert len(ids) == len(set(ids)) == 2
    expected_state = 'verified' if fault in {'reuse', 'extra-child'} else 'verification_failed'
    assert receipt['phases'][-1]['verify']['payload']['state'] == expected_state
    assert receipt['phases'][-1]['final_transaction']['state'] == expected_state
    if fault == 'reuse':
        # The local new-owner graph has no old children. Independent cross-phase
        # GUID proof must still reject reparenting a Source from another owner.
        assert 'retained GUID' in receipt['failure']['message']
    if fault == 'extra-child':
        assert 'changed the original owner/Source' in receipt['failure']['message']
    assert receipt['native_evidence'] and receipt['failure']


@pytest.mark.parametrize('fault', ['missing-field', 'ambiguous-field', 'language-membership'])
def test_planned_source_collector_requires_exact_field_and_project_language_membership(tmp_path, workflow, fault):
    runtime, commands, writes, task = _planned_source_characterization_runtime(tmp_path, workflow, fault=fault)
    with pytest.raises(AssertionError):
        workflow._collect_planned_source_characterization(runtime, prefix='WAAPI_SOURCE_TEST')
    receipt = json.loads((runtime.state_dir / 'planned-source-characterization.json').read_text())
    assert not writes and not any(argv[0] == 'execute' for argv in commands)
    assert runtime.category_results[-1]['status'] == 'FAIL' and receipt['collection_complete'] is False
    assert receipt['native_evidence'] and receipt['failure']


def test_planned_source_collector_rejects_ignored_actual_start_frequency(tmp_path, workflow):
    runtime, commands, writes, task = _planned_source_characterization_runtime(tmp_path, workflow, fault='ignored-real-field')
    with pytest.raises(AssertionError):
        workflow._collect_planned_source_characterization(runtime, prefix='WAAPI_SOURCE_TEST')
    receipt = json.loads((runtime.state_dir / 'planned-source-characterization.json').read_text())
    assert len(writes) == 1 and sum(argv[0] == 'execute' for argv in commands) == 1
    assert receipt['phases'][0]['verify']['payload']['state'] == 'verification_failed'
    assert runtime.category_results[-1]['status'] == 'FAIL' and receipt['business_effect_verified'] is False
    assert receipt['native_evidence'] and receipt['failure']


def _source_plugin_selection_runtime(tmp_path, workflow, *, fault=None):
    """Reuse the public workflow producer, with exact retained Tone metadata."""
    from copy import deepcopy
    runtime, commands, writes, task = _planned_source_characterization_runtime(tmp_path, workflow)
    fixture = json.loads((Path(__file__).parents[1] / 'fixtures/metadata/tone-source-2025-native-catalog.json').read_text())
    task.types = deepcopy(fixture['catalog']['return'])
    from tests.unit.test_sound_voice_creation_gateway import SECOND
    task.objects[SECOND]['classId'] = 1638416
    task.objects[SECOND]['parent'] = None
    create = task._create
    def create_source(node, parent, *, owned=False):
        result = create(node, parent, owned=owned)
        if node['type'] == 'Source':
            row = task.objects[result['id']]
            # Native default is modeled independently of the requested setter.
            if task.objects[parent].get('activeSource') is None:
                task.objects[parent]['activeSource'] = {'id': row['id'], 'name': row['name']}
        return result
    task._create = create_source
    original = task.call
    selections = []
    def call(uri, args=None, options=None):
        scope = (args or {}).get('object')
        source_scope = scope == 6684674 or task.objects.get(scope, {}).get('type') in {'Source', 'SourcePlugin'}
        if uri.endswith('getPropertyAndReferenceNames') and source_scope:
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return deepcopy(fixture['property_names'])
        if uri == 'ak.wwise.core.sound.setActiveSource':
            task.calls.append((uri, deepcopy(args), deepcopy(options))); selections.append(deepcopy(args))
            owner, source = task.objects[args['sound']], task.objects[args['source']]
            if fault != 'ignored': owner['activeSource'] = {'id': source['id'], 'name': source['name']}
            if fault == 'source-field':
                other = next(r for r in task.objects.values() if r['type'] == 'SourcePlugin' and r['id'] != source['id'])
                other['@StartFreq'] = 999
            if fault == 'extra-child':
                identity = '{FEFEFEFE-FEFE-FEFE-FEFE-FEFEFEFEFEFE}'
                task.objects[identity] = dict(source, id=identity, name='Unexpected', path=owner['path'] + r'\Unexpected')
            return {}
        previous = set(task.objects)
        result = original(uri, args, options)
        if uri.endswith('object.set'):
            # Model the valid omitted shape after the producer's fake defaults.
            for identity in set(task.objects) - previous:
                if task.objects[identity]['type'] == 'Sound':
                    task.objects[identity].pop('activeSource')
        return result
    task.call = call
    return runtime, commands, writes, selections, task


def test_source_plugin_selection_collector_requires_distinct_guid_change_and_preserves_original_bytes(tmp_path, workflow):
    import hashlib
    runtime, commands, writes, selections, task = _source_plugin_selection_runtime(tmp_path, workflow)
    category = workflow._collect_source_plugin_selection_acceptance(runtime, prefix='WAAPI_SELECT_TEST')
    path = Path(category['observation_path']); receipt = json.loads(path.read_text())
    assert category['status'] == 'PASS' and receipt['business_effect_verified'] is True
    assert len(writes) == 3 and len(selections) == 1 and len(receipt['transaction_ids']) == 4
    assert len(commands) == receipt['limits']['calls'] == 70
    assert len({argv[1] for argv in commands if argv[0] == 'execute'}) == 4
    assert receipt['selection']['before_active_id'] != receipt['selection']['requested_active_id']
    assert receipt['selection']['after_active_id'] == receipt['selection']['requested_active_id']
    assert receipt['selection']['preserved_before'] == receipt['selection']['preserved_after']
    assert category['observation_sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert receipt['native_evidence'] and receipt['lifecycle_final_reference']['cleanup_status'] == 'unresolved_until_final_row'
    assert receipt['metadata_selection']['frequency']['metadata']['name'] == 'StartFreq'
    assert receipt['metadata_selection']['waveform']['metadata']['name'] == 'WaveType'
    for row in receipt['native_evidence']:
        raw = Path(row['archive_path']).read_bytes()
        assert raw == Path(row['native_path']).read_bytes() and hashlib.sha256(raw).hexdigest() == row['sha256']


@pytest.mark.parametrize('fault', ['ignored', 'source-field', 'extra-child'])
def test_source_plugin_selection_collector_cannot_accept_ignored_effect_or_lost_preservation(tmp_path, workflow, fault):
    runtime, commands, writes, selections, task = _source_plugin_selection_runtime(tmp_path, workflow, fault=fault)
    with pytest.raises(AssertionError):
        workflow._collect_source_plugin_selection_acceptance(runtime, prefix='WAAPI_SELECT_TEST')
    receipt = json.loads((runtime.state_dir / 'source-plugin-selection.json').read_text())
    assert runtime.category_results[-1]['status'] == 'FAIL'
    assert receipt['business_effect_verified'] is False and receipt['collection_complete'] is False
    assert len(writes) == 3 and len(selections) == 1
    executes = [argv[1] for argv in commands if argv[0] == 'execute']
    assert len(executes) == len(set(executes)) == 4
    assert receipt['selection']['before_active_id'] != receipt['selection']['requested_active_id']
    phase = receipt['phases'][-1]
    expected = 'verification_failed' if fault == 'ignored' else 'verified'
    assert phase['verify']['payload']['state'] == phase['final_transaction']['state'] == expected
    if fault != 'ignored':
        assert receipt['selection']['after_active_id'] == receipt['selection']['requested_active_id']
        assert receipt['selection']['preserved_before'] != receipt['selection']['preserved_after']
        assert 'preserved' in receipt['failure']['message']
    assert receipt['native_evidence'] and receipt['failure']
