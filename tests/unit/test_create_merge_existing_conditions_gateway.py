"""Existing create/merge collisions use actual source state, never new defaults."""
from copy import deepcopy

import pytest

from tests.unit.test_existing_bus_override_applicability_gateway import existing_task, select_field
from tests.unit.test_object_graph_owned_choices_gateway import FIRST, SECOND, ROOT

CHILD = '{55555555-5555-5555-5555-555555555555}'


def merge_task(tmp_path, *, version='2021.1', source_kind='AuxBus'):
    task, _unused = existing_task(tmp_path, version=version, operation='object.create', source_kind=source_kind)
    if source_kind == 'Sound':
        task.types.append({'name': 'ActorMixer', 'classId': 73744, 'type': 'WObject'})
        task.objects[SECOND].update(type='ActorMixer', classId=73744,
            path=r'\Actor-Mixer Hierarchy\Default Work Unit\Routing')
        task.objects[FIRST]['path'] = task.objects[SECOND]['path'] + r'\Sender'
        task.metadata['OverrideUserAuxSends'] = {'name': 'OverrideUserAuxSends', 'type': 'bool', 'default': False}
        task.objects[FIRST]['@OverrideUserAuxSends'] = True
        task.objects[FIRST]['@Volume'] = -6.0
        task.metadata['UserAuxSend0']['dependencies'] = [
            {'type': 'override', 'action': 'Enable', 'context': 'Self', 'property': 'OverrideUserAuxSends'}]
    original = task.call
    writes = []
    def call(uri, args=None, options=None):
        if uri.endswith('object.create'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            writes.append(deepcopy(args))
            assert args['parent'] == SECOND and args['type'] == source_kind and args['name'] == 'Sender'
            assert args['onNameConflict'] == 'merge' and args['autoAddToSourceControl'] is False
            assert args['@UserAuxSend0'] == ROOT
            for name, value in args.items():
                if name.startswith('@'):
                    task.objects[FIRST][name] = {'id': value} if name == '@UserAuxSend0' else value
            return {'id': FIRST, 'name': 'Sender'}
        return original(uri, args, options)
    task.call = call
    return task, writes


def declare_merge(task, *, scalar=True, notes=None):
    parent, target = task.bind(SECOND), task.bind(ROOT)
    code, found = task.step('draft-discover-types', '--role', 'object', '--meaning', task.objects[FIRST]['type'])
    assert code == 0, found
    kind = found['type_candidates'][0]['handle']
    reference = select_field(task, kind=kind, token='UserAuxSend0')
    values = ['--field-value', reference, target]
    if scalar:
        values += ['--field-value', select_field(task, kind=kind, token='UserAuxSendVolume0'), '-12']
    code, configured = task.step('draft-business-configure', '--name-conflict', 'merge')
    assert code == 0, configured
    code, declared = task.step('draft-declare-new', '--declaration-id', 'source', '--parent-handle', parent,
        '--name', 'Sender', '--kind', kind, *values, *([] if notes is None else ['--field', 'notes', notes]))
    assert code == 0, declared


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1'])
def test_existing_auxbus_create_merge_binds_actual_conditions_and_retains_guid(tmp_path, version):
    task, writes = merge_task(tmp_path, version=version)
    before = deepcopy(task.objects)
    declare_merge(task)
    tx, shown = task.preview()
    node = shown['artifact']['prepared_operation']['verification_plan']['nodes'][0]
    assert node['preexisting_id'] == FIRST
    assert 'new_object_default_evidence' not in node
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified.get('verified') is True, verified
    assert len(writes) == 1 and '@OverrideUserAuxSends' not in writes[0]
    assert task.objects[FIRST]['@UserAuxSend0'] == {'id': ROOT}
    assert task.objects[FIRST]['@UserAuxSendVolume0'] == -12
    assert all(task.objects[FIRST][field] == before[FIRST][field] for field in ('id', 'name', 'type', 'path', 'parent', 'notes'))
    assert task.objects[SECOND] == before[SECOND] and task.objects[ROOT] == before[ROOT]


def test_ordinary_sound_merge_uses_actual_override_and_preserves_unrequested_fields(tmp_path):
    task, writes = merge_task(tmp_path, source_kind='Sound')
    before = deepcopy(task.objects)
    declare_merge(task, scalar=False)
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified.get('verified') is True, verified
    assert len(writes) == 1 and writes[0]['@OverrideUserAuxSends'] is True
    assert task.objects[FIRST]['@OverrideUserAuxSends'] is True
    assert task.objects[FIRST]['@Volume'] == before[FIRST]['@Volume']
    assert task.objects[FIRST]['notes'] == before[FIRST]['notes']


@pytest.mark.parametrize('overwrite_existing_notes', [False, True])
def test_existing_merge_constructor_notes_preserve_actual_existing_notes(tmp_path, overwrite_existing_notes):
    task, writes = merge_task(tmp_path)
    before_notes = task.objects[FIRST]['notes']
    original = task.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('object.create') and overwrite_existing_notes:
            task.objects[FIRST]['notes'] = args['notes']
        return result
    task.call = call
    declare_merge(task, notes='Requested notes')
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == (2 if overwrite_existing_notes else 0), verified
    assert (verified.get('verified') is True) is (not overwrite_existing_notes)
    assert len(writes) == 1 and task.objects[FIRST]['notes'] == ('Requested notes' if overwrite_existing_notes else before_notes)


def add_child(task):
    task.objects[CHILD] = {'id': CHILD, 'name': 'Keep child', 'type': 'Bus', 'classId': 1376272,
        'path': task.objects[FIRST]['path'] + r'\Keep child', 'parent': {'id': FIRST}, 'notes': 'Keep child notes'}


@pytest.mark.parametrize('fault', ['class', 'metadata', 'parent', 'notes', 'reference', 'child'])
def test_existing_merge_revalidates_actual_source_before_only_dispatch(tmp_path, fault):
    task, writes = merge_task(tmp_path)
    add_child(task)
    declare_merge(task)
    tx, shown = task.preview()
    if fault == 'class': task.objects[FIRST]['classId'] = 65552
    if fault == 'metadata': task.metadata['UserAuxSend0']['dependencies'][0]['context'] = 'Parent'
    if fault == 'parent': task.objects[FIRST]['parent'] = {'id': ROOT}
    if fault == 'notes': task.objects[FIRST]['notes'] = 'Drift'
    if fault == 'reference': task.objects[FIRST]['@UserAuxSend0'] = {'id': SECOND}
    if fault == 'child': task.objects[CHILD]['notes'] = 'Drift'
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, rejected = task.run('execute', tx)
    assert code == 2 and rejected.get('executed') is not True, rejected
    assert not writes


@pytest.mark.parametrize('fault', ['guid', 'class', 'parent', 'notes', 'reference', 'scalar', 'child', 'child-path', 'extra-child'])
def test_existing_merge_rejects_wrong_native_effect_and_unrequested_resets(tmp_path, fault):
    task, writes = merge_task(tmp_path)
    add_child(task)
    declare_merge(task)
    tx, shown = task.preview()
    original = task.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('object.create'):
            if fault == 'guid': result['id'] = ROOT
            if fault == 'class': task.objects[FIRST]['classId'] = 65552
            if fault == 'parent': task.objects[FIRST]['parent'] = {'id': ROOT}
            if fault == 'notes': task.objects[FIRST]['notes'] = ''
            if fault == 'reference': task.objects[FIRST]['@UserAuxSend0'] = {'id': SECOND}
            if fault == 'scalar': task.objects[FIRST]['@UserAuxSendVolume0'] = -1
            if fault == 'child': task.objects[CHILD]['notes'] = ''
            if fault == 'child-path': task.objects[CHILD]['path'] += 'Unexpected'
            if fault == 'extra-child':
                task.objects[ROOT]['parent'] = {'id': FIRST}
                task.objects[ROOT]['path'] = task.objects[FIRST]['path'] + r'\Destination'
        return result
    task.call = call
    code, verified = task.finish(tx, shown)
    assert code == 2 and verified.get('verified') is not True, verified
    assert len(writes) == 1


@pytest.mark.parametrize('fault', ['wrong-class', 'missing-class', 'duplicate', 'wrong-parent'])
def test_create_merge_rejects_unproved_collision_before_preview(tmp_path, fault):
    task, writes = merge_task(tmp_path)
    declare_merge(task)
    if fault == 'wrong-class': task.objects[FIRST]['classId'] = 65552
    if fault == 'missing-class': del task.objects[FIRST]['classId']
    if fault == 'wrong-parent': task.objects[FIRST]['parent'] = {'id': ROOT}
    if fault == 'duplicate':
        task.objects[CHILD] = {**deepcopy(task.objects[FIRST]), 'id': CHILD}
    code, checked = task.step('draft-check')
    assert code == 2, checked
    assert checked['error_code'] == ('AMBIGUOUS_IDENTITY' if fault == 'duplicate' else 'INVALID_TARGET_TYPE'), checked
    assert not writes


def test_nested_create_merge_uses_each_actual_source_without_recreating_parent(tmp_path):
    task, writes = merge_task(tmp_path)
    add_child(task)
    task.objects[CHILD].update(name='Nested', type='AuxBus', classId=3997712,
        path=task.objects[FIRST]['path'] + r'\Nested', **{'@UserAuxSend0': None, '@UserAuxSendVolume0': 0})
    parent, target = task.bind(SECOND), task.bind(ROOT)
    code, found = task.step('draft-discover-types', '--role', 'object', '--meaning', 'AuxBus')
    assert code == 0, found
    kind = found['type_candidates'][0]['handle']
    reference = select_field(task, kind=kind, token='UserAuxSend0')
    scalar = select_field(task, kind=kind, token='UserAuxSendVolume0')
    code, configured = task.step('draft-business-configure', '--name-conflict', 'merge')
    assert code == 0, configured
    code, root = task.step('draft-declare-new', '--declaration-id', 'root', '--parent-handle', parent,
        '--name', 'Sender', '--kind', kind)
    assert code == 0, root
    root_handle = root['draft']['declared_object']['result_handle']
    code, declared = task.step('draft-declare-new', '--declaration-id', 'child', '--parent-handle', root_handle,
        '--name', 'Nested', '--kind', kind, '--field-value', reference, target, '--field-value', scalar, '-12')
    assert code == 0, declared
    original = task.call
    def call(uri, args=None, options=None):
        if uri.endswith('object.create'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            writes.append(deepcopy(args))
            assert args == {'parent': SECOND, 'type': 'AuxBus', 'name': 'Sender', 'children': [
                {'type': 'AuxBus', 'name': 'Nested', '@UserAuxSend0': ROOT, '@UserAuxSendVolume0': -12}],
                'onNameConflict': 'merge', 'autoAddToSourceControl': False}
            task.objects[CHILD].update({'@UserAuxSend0': {'id': ROOT}, '@UserAuxSendVolume0': -12})
            return {'id': FIRST, 'name': 'Sender', 'children': [{'id': CHILD, 'name': 'Nested'}]}
        return original(uri, args, options)
    task.call = call
    before = deepcopy(task.objects)
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified.get('verified') is True, verified
    assert len(writes) == 1 and task.objects[FIRST] == before[FIRST]
    assert len(task.objects) == len(before)
