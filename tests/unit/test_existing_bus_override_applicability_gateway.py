"""Actual source placement, never prospective defaults, for user-send conditions."""
from copy import deepcopy
import json

import pytest

from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, FIRST, SECOND, ROOT, CHILD


def existing_task(tmp_path, *, version='2025.1', operation='object.set', field='UserAuxSend0', source_kind='AuxBus'):
    task = OwnedGraphTask(tmp_path, version, operation)
    classes = {'Bus': 1376272, 'AuxBus': 3997712, 'Sound': 65552, 'WorkUnit': 1638416}
    task.types = [{'name': name, 'classId': value, 'type': 'WObject'} for name, value in classes.items()]
    task.objects = {
        FIRST: {'id': FIRST, 'name': 'Sender', 'type': source_kind, 'classId': classes[source_kind],
            'path': r'\Busses\Default Work Unit\Routing\Sender', 'parent': {'id': SECOND}, 'notes': 'Keep sender',
            '@UserAuxSend0': None, '@UserAuxSendVolume0': -3.0},
        SECOND: {'id': SECOND, 'name': 'Routing', 'type': 'Bus', 'classId': classes['Bus'],
            'path': r'\Busses\Default Work Unit\Routing', 'parent': {'id': CHILD}, 'notes': 'Keep routing'},
        ROOT: {'id': ROOT, 'name': 'Destination', 'type': 'AuxBus', 'classId': classes['AuxBus'],
            'path': r'\Busses\Default Work Unit\Routing\Destination', 'parent': {'id': SECOND}, 'notes': 'Keep target'},
        CHILD: {'id': CHILD, 'name': 'Default Work Unit', 'type': 'WorkUnit', 'classId': classes['WorkUnit'],
            'path': r'\Busses\Default Work Unit', 'notes': 'Keep work unit'},
    }
    dependencies = ([{'type': 'isMasterBus', 'value': False, 'action': 'Show', 'context': 'Self'}]
        if version in {'2024.1', '2025.1'} else []) + [
        {'type': 'override', 'action': 'Enable', 'context': 'Self', 'property': 'OverrideUserAuxSends'}]
    task.metadata = {
        'UserAuxSend0': {'name': 'UserAuxSend0', 'type': '', 'supports': {'unlink': False},
            'restriction': {'type': 'reference', 'restrictions': [{'type': ['Auxiliary Bus'], 'sharedOnlyTypes': []}]},
            'dependencies': deepcopy(dependencies)},
        'UserAuxSendVolume0': {'name': 'UserAuxSendVolume0', 'type': 'Real64', 'default': 0,
            'restriction': {'type': 'range', 'min': -200, 'max': 12}, 'dependencies': deepcopy(dependencies)},
    }
    if version in {'2021.1', '2022.1', '2023.1'}:
        task.metadata['UserAuxSendVolume0']['dependencies'].append({'type': 'reference', 'action': 'Enable',
            'context': 'Self', 'property': 'UserAuxSend0', 'conditions': [{'referenceIsSet': True}]})
    original = task.call
    writes = []
    def call(uri, args=None, options=None):
        if uri.endswith('getPropertyInfo') and args.get('property') == 'OverrideUserAuxSends' and 'OverrideUserAuxSends' not in task.metadata:
            raise RuntimeError('Literal native 553: property does not exist on AuxBus')
        if uri.endswith('isPropertyEnabled'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': True}  # Scalar-only program fixture, not native observed Boolean.
        if uri.endswith(('object.set', 'setProperty', 'setReference')):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            writes.append((uri, deepcopy(args)))
            if uri.endswith('object.set'):
                for item in args['objects']:
                    row = task.objects[item['object']]
                    if 'name' in item:
                        old_path = row['path']
                        row['name'] = item['name']
                        row['path'] = old_path.rsplit('\\', 1)[0] + '\\' + row['name']
                        for descendant in task.objects.values():
                            if descendant['path'].startswith(old_path + '\\'):
                                descendant['path'] = row['path'] + descendant['path'][len(old_path):]
                    if 'notes' in item: row['notes'] = item['notes']
                    for name, value in item.items():
                        if name.startswith('@'):
                            row[name] = {'id': value} if name == '@UserAuxSend0' and value else value
                return {'objects': [{'id': item['object'], 'name': task.objects[item['object']]['name']} for item in args['objects']]}
            name = args.get('reference', args.get('property'))
            task.objects[args['object']]['@' + name] = {'id': args['value']} if name == 'UserAuxSend0' and args['value'] else args['value']
            return {}
        result = original(uri, args, options)
        if uri.endswith('object.get'):
            return {'return': [{name: deepcopy(row.get(name, row.get('@' + name)))
                for name in options['return'] if name in row or '@' + name in row} for row in result['return']]}
        return result
    task.call = call
    task.operation = operation
    task.selected_field = field
    return task, writes


def select_field(task, *, owner=None, kind=None, token):
    scope = ['--object-handle', owner] if owner else ['--type-handle', kind]
    code, listed = task.step('draft-discover-fields', *scope, '--list')
    assert code == 0, listed
    selection = next(row['selection'] for row in listed['agent_result']['fields'] if row['name'] == token)
    code, chosen = task.step('draft-discover-fields', *scope, '--selection', selection)
    assert code == 0, chosen
    candidate = chosen['meaning_results'][0]['candidates'][0]
    if kind:
        assert candidate['scope_evidence'] == {'kind': 'class_metadata', 'placement': 'unresolved',
            'required_before_mutation': True, 'mutation_authority': False}
    return candidate['handle']


def declare_existing(task, *, extra=()):
    source = task.bind(FIRST)
    field = select_field(task, owner=source, token=task.selected_field)
    value = task.bind(ROOT) if task.selected_field == 'UserAuxSend0' else '-9'
    if task.operation == 'object.set':
        code, declared = task.step('draft-declare-existing', '--declaration-id', 'source', '--object-handle', source,
            '--field-value', field, value, *extra)
    else:
        code, declared = task.step('draft-declare-field-change', '--object-handle', source, '--field-handle', field,
            '--target-handle' if task.selected_field == 'UserAuxSend0' else '--business-value', value)
    assert code == 0, declared


@pytest.mark.parametrize('version,operation,field', [(version, operation, field)
    for version in ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1')
    for operation, field in [('object.setReference', 'UserAuxSend0'), ('object.set', 'UserAuxSend0'),
        ('object.setProperty', 'UserAuxSendVolume0'), ('object.set', 'UserAuxSendVolume0')]
    if version != '2021.1' or operation != 'object.set'])
@pytest.mark.parametrize('source_kind', ['AuxBus', 'Bus'])
def test_existing_bus_user_send_uses_actual_source_and_parent_without_override(tmp_path, version, operation, field, source_kind):
    task, writes = existing_task(tmp_path, version=version, operation=operation, field=field, source_kind=source_kind)
    if version in {'2021.1', '2022.1', '2023.1'} and field == 'UserAuxSendVolume0':
        task.objects[FIRST]['@UserAuxSend0'] = {'id': ROOT}
    before = deepcopy(task.objects)
    declare_existing(task)
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    if code:
        (tmp_path / 'unexpected-verification.json').write_text(json.dumps(verified))
    assert code == 0 and verified['verified'] is True, verified
    assert len(writes) == 1
    assert 'OverrideUserAuxSends' not in json.dumps(writes)
    assert task.objects[FIRST]['@' + field] == ({'id': ROOT} if field == 'UserAuxSend0' else -9)
    assert task.objects[SECOND] == before[SECOND] and task.objects[ROOT] == before[ROOT]
    assert task.objects[FIRST]['notes'] == before[FIRST]['notes']


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1'])
@pytest.mark.parametrize('valid_parent', [True, False])
def test_class_scalar_discovery_rebinds_versioned_placement_before_mutation(tmp_path, version, valid_parent):
    operation = 'object.create' if version == '2021.1' else 'object.set'
    task, writes = existing_task(tmp_path, version=version, operation=operation, field='UserAuxSendVolume0')
    parent = task.bind(SECOND if valid_parent else CHILD)
    code, types = task.step('draft-discover-types', '--role', 'object', '--meaning', 'AuxBus')
    assert code == 0, types
    kind = types['type_candidates'][0]['handle']
    field = select_field(task, kind=kind, token='UserAuxSendVolume0')
    reference = select_field(task, kind=kind, token='UserAuxSend0')
    target = task.bind(ROOT)
    code, declared = task.step('draft-declare-new', '--declaration-id', 'new', '--parent-handle', parent,
        '--name', 'NewSender', '--kind', kind, '--field-value', field, '-9', '--field-value', reference, target)
    assert code == 0, declared
    if not valid_parent and version in {'2024.1', '2025.1'}:
        code, rejected = task.step('draft-check')
        assert code == 2, rejected
    else:
        _tx, shown = task.preview()
        nodes = shown['artifact']['prepared_operation']['verification_plan']['nodes']
        node = next(row for row in nodes if row.get('requested_name') == 'NewSender')
        proof = node['new_object_default_evidence'][0]['override_applicability'][0]
        assert proof.get('purpose', 'mutation') == 'mutation'
        if valid_parent:
            assert proof['structural_proof']['parent']['object_id'] == SECOND
        else:
            assert proof['structural_proof'] is None
            # A class-only applicability fact must still be reacquired before
            # execution; missing placement is not permission to reuse stale metadata.
            task.metadata['UserAuxSendVolume0']['restriction']['max'] = 11
            code, confirmed = task.run('confirm', _tx, '--confirmation-token', shown['confirmation']['token'])
            assert code == 0, confirmed
            code, rejected = task.run('execute', _tx)
            assert code == 2 and rejected.get('executed') is not True, rejected
        assert node['new_object_default_evidence'][0]['derived_properties'] == {}
    assert not writes


@pytest.mark.parametrize('edit', ['source-name', 'source-notes', 'parent-name', 'both-names', 'rename-policy'])
def test_existing_bus_applicability_preserves_explicit_graph_name_and_notes_edits(tmp_path, edit):
    task, writes = existing_task(tmp_path)
    extra = []
    if edit in {'parent-name', 'both-names'}:
        parent = task.bind(SECOND)
        code, declared = task.step('draft-declare-existing', '--declaration-id', 'parent', '--object-handle', parent,
            '--field', 'new_name', 'RoutingEdited')
        assert code == 0, declared
    if edit != 'parent-name':
        extra = ['--field', 'notes' if edit == 'source-notes' else 'new_name', 'Edited']
    if edit == 'rename-policy':
        extra += ['--field', 'name_conflict', 'rename']
        original = task.call
        def call(uri, args=None, options=None):
            value = original(uri, args, options)
            if uri.endswith('object.set'):
                assert args['objects'][0]['name'] == 'Edited'
                row = task.objects[FIRST]
                row['name'] = 'Edited_1'  # A native outcome, never predicted by the Gateway.
                row['path'] = row['path'].rsplit('\\', 1)[0] + '\\' + row['name']
                value['objects'][0]['name'] = row['name']
            return value
        task.call = call
    declare_existing(task, extra=extra)
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    if code:
        (tmp_path / 'unexpected-verification.json').write_text(json.dumps(verified))
    assert code == 0 and verified['verified'] is True, verified
    assert len(writes) == 1


@pytest.mark.parametrize('fault', ['master-parent', 'wrong-parent-class', 'missing-parent', 'wrong-source-class',
    'wrong-source-path', 'object-class-metadata', 'unrelated-override', 'extra-dependency'])
def test_existing_bus_applicability_rejects_unproved_scope_without_write(tmp_path, fault):
    task, writes = existing_task(tmp_path, operation='object.setReference')
    if fault == 'master-parent': task.objects[FIRST]['parent'] = {'id': CHILD}
    if fault == 'wrong-parent-class': task.objects[SECOND]['classId'] = 65552
    if fault == 'missing-parent': task.objects[FIRST].pop('parent')
    if fault == 'wrong-source-class': task.objects[FIRST]['classId'] = True
    if fault == 'wrong-source-path': task.objects[FIRST]['path'] += r'\Guessed'
    if fault == 'unrelated-override': task.metadata['UserAuxSend0']['dependencies'][1]['property'] = 'UnprovedOverride'
    if fault == 'extra-dependency': task.metadata['UserAuxSend0']['dependencies'].append({'type': 'unknown'})
    if fault == 'object-class-metadata':
        original = task.call
        def call(uri, args=None, options=None):
            value = deepcopy(original(uri, args, options))
            if uri.endswith('getPropertyInfo') and args.get('classId'):
                value['supports']['unlink'] = True
            return value
        task.call = call
    declare_existing(task)
    code, rejected = task.step('draft-check')
    assert code == 2, rejected
    assert not writes


@pytest.mark.parametrize('fault', ['source-class', 'parent-class', 'parent-edge', 'source-path', 'source-notes',
    'parent-notes', 'metadata', 'controller-present', 'object-inventory'])
def test_existing_bus_applicability_revalidates_actual_state_before_only_write(tmp_path, fault):
    task, writes = existing_task(tmp_path, operation='object.setReference')
    declare_existing(task)
    tx, shown = task.preview()
    if fault == 'source-class': task.objects[FIRST]['classId'] = 65552
    if fault == 'parent-class': task.objects[SECOND]['classId'] = 65552
    if fault == 'parent-edge': task.objects[FIRST]['parent'] = {'id': CHILD}
    if fault == 'source-path': task.objects[FIRST]['path'] += r'\Moved'
    if fault == 'source-notes': task.objects[FIRST]['notes'] = 'Unexpected'
    if fault == 'parent-notes': task.objects[SECOND]['notes'] = 'Unexpected'
    if fault == 'metadata': task.metadata['UserAuxSend0']['dependencies'][1]['context'] = 'Parent'
    if fault == 'controller-present': task.metadata['OverrideUserAuxSends'] = {'name': 'OverrideUserAuxSends', 'type': 'bool'}
    if fault == 'object-inventory':
        original = task.call
        def call(uri, args=None, options=None):
            value = deepcopy(original(uri, args, options))
            if uri.endswith('getPropertyAndReferenceNames') and args.get('object') == FIRST:
                value['return'].append('UnrequestedProperty')
            return value
        task.call = call
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, rejected = task.run('execute', tx)
    assert code == 2 and rejected.get('executed') is not True, rejected
    assert not writes


@pytest.mark.parametrize('operation,field', [('object.setReference', 'UserAuxSend0'), ('object.setProperty', 'UserAuxSendVolume0')])
@pytest.mark.parametrize('fault', ['wrong-value', 'source-class', 'parent-edge', 'source-notes', 'parent-notes', 'source-path'])
def test_existing_bus_applicability_never_verifies_wrong_effect_or_unrequested_state(tmp_path, operation, field, fault):
    task, writes = existing_task(tmp_path, operation=operation, field=field)
    declare_existing(task)
    tx, shown = task.preview()
    original = task.call
    def call(uri, args=None, options=None):
        value = original(uri, args, options)
        if uri.endswith(('setProperty', 'setReference')):
            if fault == 'wrong-value': task.objects[FIRST]['@' + field] = {'id': SECOND} if field == 'UserAuxSend0' else -1
            if fault == 'source-class': task.objects[FIRST]['classId'] = True
            if fault == 'parent-edge': task.objects[FIRST]['parent'] = {'id': CHILD}
            if fault == 'source-notes': task.objects[FIRST]['notes'] = 'Unexpected'
            if fault == 'parent-notes': task.objects[SECOND]['notes'] = 'Unexpected'
            if fault == 'source-path': task.objects[FIRST]['path'] += r'\Unexpected'
        return value
    task.call = call
    code, verified = task.finish(tx, shown)
    assert code == 2 and verified.get('verified') is not True, verified
    assert len(writes) == 1


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1'])
def test_old_scalar_own_reference_condition_is_enforced_not_discarded(tmp_path, version):
    task, writes = existing_task(tmp_path, version=version, operation='object.setProperty', field='UserAuxSendVolume0')
    declare_existing(task)
    code, rejected = task.step('draft-check')
    assert code == 2, rejected
    assert not writes


@pytest.mark.parametrize('version', ['2022.1', '2023.1'])
def test_old_scalar_and_its_reference_condition_share_one_explicit_set(tmp_path, version):
    task, writes = existing_task(tmp_path, version=version, field='UserAuxSendVolume0')
    source = task.bind(FIRST)
    volume = select_field(task, owner=source, token='UserAuxSendVolume0')
    reference = select_field(task, owner=source, token='UserAuxSend0')
    destination = task.bind(ROOT)
    code, declared = task.step('draft-declare-existing', '--declaration-id', 'source', '--object-handle', source,
        '--field-value', volume, '-9', '--field-value', reference, destination)
    assert code == 0, declared
    tx, shown = task.preview()
    native = shown['artifact']['prepared_operation']['dispatch']['args']['objects'][0]
    assert native == {'object': FIRST, '@UserAuxSendVolume0': -9, '@UserAuxSend0': ROOT}
    code, verified = task.finish(tx, shown)
    if code:
        (tmp_path / 'unexpected-verification.json').write_text(json.dumps(verified))
    assert code == 0 and verified['verified'] is True, verified
    assert len(writes) == 1


@pytest.mark.parametrize('fault', ['path', 'notes'])
def test_combined_requested_renames_do_not_waive_unrequested_source_drift(tmp_path, fault):
    task, writes = existing_task(tmp_path)
    parent = task.bind(SECOND)
    code, declared = task.step('draft-declare-existing', '--declaration-id', 'parent', '--object-handle', parent,
        '--field', 'new_name', 'RoutingEdited')
    assert code == 0, declared
    declare_existing(task, extra=['--field', 'new_name', 'Edited'])
    tx, shown = task.preview()
    original = task.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('object.set'):
            task.objects[FIRST]['path' if fault == 'path' else 'notes'] += 'Unexpected'
        return result
    task.call = call
    code, verified = task.finish(tx, shown)
    assert code == 2 and verified.get('verified') is not True, verified
    assert len(writes) == 1


@pytest.mark.parametrize('fault', [None, 'path', 'move'])
def test_generic_sound_and_actor_mixer_renames_keep_exact_guid_paths(tmp_path, fault):
    task, writes = existing_task(tmp_path, version='2023.1', field='Volume', source_kind='Sound')
    task.types.append({'name': 'ActorMixer', 'classId': 73744, 'type': 'WObject'})
    task.objects[SECOND].update(type='ActorMixer', classId=73744,
        path=r'\Actor-Mixer Hierarchy\Default Work Unit\Routing')
    task.objects[FIRST].update(path=task.objects[SECOND]['path'] + r'\Sender')
    task.objects[CHILD]['path'] = r'\Actor-Mixer Hierarchy\Default Work Unit'
    task.objects[FIRST]['@Volume'] = -3.0
    task.metadata = {'Volume': {'name': 'Volume', 'type': 'Real64',
        'restriction': {'type': 'range', 'min': -200, 'max': 12}}}
    parent = task.bind(SECOND)
    code, declared = task.step('draft-declare-existing', '--declaration-id', 'parent', '--object-handle', parent,
        '--field', 'new_name', 'RoutingEdited')
    assert code == 0, declared
    declare_existing(task, extra=['--field', 'new_name', 'Edited'])
    tx, shown = task.preview()
    original = task.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('object.set'):
            if fault == 'path': task.objects[FIRST]['path'] += 'Unexpected'
            if fault == 'move':
                task.objects[FIRST]['parent'] = {'id': CHILD}
                task.objects[FIRST]['path'] = task.objects[CHILD]['path'] + r'\Edited'
        return result
    task.call = call
    code, verified = task.finish(tx, shown)
    assert code == (0 if fault is None else 2), verified
    assert (verified.get('verified') is True) == (fault is None)
    assert len(writes) == 1


@pytest.mark.parametrize('fault', [None, 'drift', 'missing-chain'])
def test_generic_ancestor_rename_seals_missing_intermediate_guid_snapshot(tmp_path, fault):
    task, writes = existing_task(tmp_path, version='2023.1', field='Volume', source_kind='Sound')
    task.types.append({'name': 'ActorMixer', 'classId': 73744, 'type': 'WObject'})
    base = r'\Actor-Mixer Hierarchy\Default Work Unit'
    task.objects[CHILD]['path'] = base
    task.objects[SECOND].update(type='ActorMixer', classId=73744, path=base + r'\Routing')
    task.objects[ROOT].update(type='ActorMixer', classId=73744, name='Middle',
        path=base + r'\Routing\Middle', parent={'id': CHILD if fault == 'missing-chain' else SECOND})
    task.objects[FIRST].update(path=base + r'\Routing\Middle\Sender', parent={'id': ROOT})
    task.objects[FIRST]['@Volume'] = -3.0
    task.metadata = {'Volume': {'name': 'Volume', 'type': 'Real64',
        'restriction': {'type': 'range', 'min': -200, 'max': 12}}}
    parent = task.bind(SECOND)
    code, declared = task.step('draft-declare-existing', '--declaration-id', 'ancestor', '--object-handle', parent,
        '--field', 'new_name', 'RoutingEdited')
    assert code == 0, declared
    declare_existing(task, extra=['--field', 'new_name', 'Edited'])
    if fault == 'missing-chain':
        code, rejected = task.step('draft-check')
        assert code == 2, rejected
        assert not writes
        return
    tx, shown = task.preview()
    if fault == 'drift':
        task.objects[ROOT]['notes'] = 'Unrequested intermediate drift'
        code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
        assert code == 0, confirmed
        code, rejected = task.run('execute', tx)
        assert code == 2 and rejected.get('executed') is not True, rejected
        assert not writes
    else:
        code, verified = task.finish(tx, shown)
        assert code == 0 and verified['verified'] is True, verified
        assert task.objects[FIRST]['path'] == base + r'\RoutingEdited\Middle\Edited'
        assert len(writes) == 1


@pytest.mark.parametrize('source_kind', ['AuxBus', 'Sound'])
@pytest.mark.parametrize('fault', [None, 'parent-name', 'parent-guid', 'path'])
def test_renamed_parent_reference_label_is_derived_from_admitted_exact_parent(tmp_path, source_kind, fault):
    task, writes = existing_task(tmp_path, field='UserAuxSend0' if source_kind == 'AuxBus' else 'Volume', source_kind=source_kind)
    if source_kind == 'Sound':
        task.types.append({'name': 'ActorMixer', 'classId': 73744, 'type': 'WObject'})
        task.objects[SECOND].update(type='ActorMixer', classId=73744)
        task.metadata = {'Volume': {'name': 'Volume', 'type': 'Real64',
            'restriction': {'type': 'range', 'min': -200, 'max': 12}}}
        task.objects[FIRST]['@Volume'] = -3.0
    for row in task.objects.values():
        parent = row.get('parent')
        if isinstance(parent, dict):
            parent['name'] = task.objects[parent['id']]['name']
    parent = task.bind(SECOND)
    code, declared = task.step('draft-declare-existing', '--declaration-id', 'parent', '--object-handle', parent,
        '--field', 'new_name', 'RoutingEdited')
    assert code == 0, declared
    declare_existing(task, extra=['--field', 'new_name', 'Edited'])
    tx, shown = task.preview()
    original = task.call
    def call(uri, args=None, options=None):
        value = original(uri, args, options)
        if uri.endswith('object.set'):
            for row in task.objects.values():
                parent = row.get('parent')
                if isinstance(parent, dict):
                    parent['name'] = task.objects[parent['id']]['name']
            if fault == 'parent-name': task.objects[FIRST]['parent']['name'] = 'Unrequested label'
            if fault == 'parent-guid': task.objects[FIRST]['parent']['id'] = CHILD
            if fault == 'path': task.objects[FIRST]['path'] += 'Unrequested'
        return value
    task.call = call
    code, verified = task.finish(tx, shown)
    assert code == (0 if fault is None else 2), verified
    assert (verified.get('verified') is True) == (fault is None), verified
    assert len(writes) == 1


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1'])
@pytest.mark.parametrize('field', ['UserAuxSend0', 'UserAuxSendVolume0'])
def test_old_root_bus_without_master_visibility_condition_uses_exact_live_identity(tmp_path, version, field):
    operation = 'object.setReference' if field == 'UserAuxSend0' else 'object.setProperty'
    task, writes = existing_task(tmp_path, version=version, operation=operation,
        field=field, source_kind='Bus')
    task.objects[FIRST]['parent'] = {'id': CHILD}
    task.objects[FIRST]['path'] = task.objects[CHILD]['path'] + '\\' + task.objects[FIRST]['name']
    if field == 'UserAuxSendVolume0':
        task.objects[FIRST]['@UserAuxSend0'] = {'id': ROOT}
    before = deepcopy(task.objects)
    declare_existing(task)
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert len(writes) == 1 and 'OverrideUserAuxSends' not in json.dumps(writes)
    assert task.objects[FIRST]['@' + field] == ({'id': ROOT} if field == 'UserAuxSend0' else -9)
    assert task.objects[FIRST]['parent'] == before[FIRST]['parent']
    assert task.objects[FIRST]['notes'] == before[FIRST]['notes']
    assert all(task.objects[key] == before[key] for key in (SECOND, ROOT, CHILD))


@pytest.mark.parametrize('phase', ['before-execute', 'after-write'])
@pytest.mark.parametrize('fault', ['parent-class', 'parent-notes', 'metadata', 'source-path'])
def test_old_root_bus_does_not_waive_live_drift_or_unrequested_changes(tmp_path, phase, fault):
    task, writes = existing_task(tmp_path, version='2023.1', operation='object.setReference', source_kind='Bus')
    task.objects[FIRST]['parent'] = {'id': CHILD}
    task.objects[FIRST]['path'] = task.objects[CHILD]['path'] + '\\' + task.objects[FIRST]['name']
    declare_existing(task)
    tx, shown = task.preview()
    def corrupt():
        if fault == 'parent-class': task.objects[CHILD]['classId'] = 65552
        if fault == 'parent-notes': task.objects[CHILD]['notes'] = 'Unexpected'
        if fault == 'metadata': task.metadata['UserAuxSend0']['dependencies'][0]['context'] = 'Parent'
        if fault == 'source-path': task.objects[FIRST]['path'] += r'\Unexpected'
    if phase == 'before-execute':
        corrupt()
        code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
        assert code == 0, confirmed
        code, rejected = task.run('execute', tx)
        assert code == 2 and rejected.get('executed') is not True, rejected
        assert not writes
    else:
        original = task.call
        def call(uri, args=None, options=None):
            value = original(uri, args, options)
            if uri.endswith('setReference'): corrupt()
            return value
        task.call = call
        code, verified = task.finish(tx, shown)
        assert code == 2 and verified.get('verified') is not True, verified
        assert len(writes) == 1
