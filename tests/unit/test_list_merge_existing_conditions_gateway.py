"""Source-proven List collisions bind actual metadata before condition planning."""
from copy import deepcopy
import json

import pytest

from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, FIRST, SECOND, ROOT, CHILD


def select_field(task, *, owner=None, kind=None, token):
    scope = ['--object-handle', owner] if owner else ['--type-handle', kind]
    code, listed = task.step('draft-discover-fields', *scope, '--list')
    assert code == 0, json.dumps(listed)
    selection = next(row['selection'] for row in listed['agent_result']['fields'] if row['name'] == token)
    code, chosen = task.step('draft-discover-fields', *scope, '--selection', selection)
    assert code == 0, json.dumps(chosen)
    return chosen['meaning_results'][0]['candidates'][0]['handle']


EFFECT = '{55555555-5555-5555-5555-555555555555}'
EFFECT_PARENT = '{66666666-6666-6666-6666-666666666666}'


def list_task(tmp_path, *, version='2025.1', operation='object.create', explicit_reference=False):
    task = OwnedGraphTask(tmp_path, version, operation)
    task.types = [{'name': name, 'classId': value, 'type': 'WObject'} for name, value in
        [('Sound', 65552), ('EffectSlot', 5505040), ('WorkUnit', 1638416)]]
    # Hierarchical-looking owned paths below are fixture shapes only. Native
    # PluginInnerObject paths may be opaque; exact preservation is authoritative.
    base = r'\Actor-Mixer Hierarchy\Default Work Unit'
    task.objects = {
        FIRST: {'id': FIRST, 'name': 'Sender', 'type': 'Sound', 'classId': 65552, 'path': base + r'\Sender',
            'parent': {'id': SECOND}, 'notes': 'Keep sound', '@Effects': [{'id': ROOT}, {'id': CHILD}], '@OverrideEffect': True},
        SECOND: {'id': SECOND, 'name': 'Default Work Unit', 'type': 'WorkUnit', 'classId': 1638416,
            'path': base, 'parent': None, 'notes': 'Keep work unit'},
        ROOT: {'id': ROOT, 'name': 'Slot', 'type': 'PluginInnerObject', 'classId': 5505040,
            'path': base + r'\Sender\Slot', 'owner': {'id': FIRST}, 'notes': 'Keep slot',
            '@Effect': {'id': EFFECT}, '@Bypass': False, '@Render': False},
        CHILD: {'id': CHILD, 'name': 'Spare', 'type': 'PluginInnerObject', 'classId': 5505040,
            'path': base + r'\Sender\Spare', 'owner': {'id': FIRST}, 'notes': 'Keep spare',
            '@Effect': {'id': EFFECT}, '@Bypass': False, '@Render': False},
        #8454147 is Wwise Meter in all five pinned object-types inventories.
        EFFECT: {'id': EFFECT, 'name': 'Existing Effect', 'type': 'Effect', 'classId': 8454147,
            'path': r'\Effects\Default Work Unit\Existing Effect', 'parent': {'id': EFFECT_PARENT}, 'notes': 'Keep effect'},
        EFFECT_PARENT: {'id': EFFECT_PARENT, 'name': 'Default Work Unit', 'type': 'WorkUnit', 'classId': 1638416,
            'path': r'\Effects\Default Work Unit', 'parent': None, 'notes': 'Keep effect work unit'},
    }
    # XML EffectSlot property grammar2023–25; normalized metadata is fixture-only,
    # not claimed to be an observed native getPropertyInfo response.
    task.metadata = {'Effect': {'name': 'Effect', 'type': '', 'default': None,
        'restriction': {'type': 'reference', 'restrictions': [{'type': ['Effect']}]}}}
    for name in ('Bypass', 'Render'):
        task.metadata[name] = {'name': name, 'type': 'bool', 'default': False,
            'dependencies': [{'type': 'reference', 'action': 'Enable', 'context': 'Self', 'property': 'Effect',
                'conditions': [{'referenceIsSet': True}]}]}
    original = task.call
    writes = []
    def call(uri, args=None, options=None):
        if uri.endswith(('object.create', 'object.set')):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            writes.append((uri, deepcopy(args)))
            node = args if uri.endswith('object.create') else args['objects'][0]['@Effects'][0]
            assert node['type'] == 'EffectSlot' and node['name'] == 'Slot', args
            assert node['@Bypass'] is True and ('@Effect' in node) is explicit_reference, args
            if explicit_reference:
                assert node['@Effect'] == EFFECT, args
                task.objects[ROOT]['@Effect'] = {'id': EFFECT}
            task.objects[ROOT]['@Bypass'] = True
            if uri.endswith('object.create'):
                assert args['parent'] == FIRST and args['list'] == 'Effects' and args['onNameConflict'] == 'merge', args
                return {'id': ROOT, 'name': 'Slot'}
            assert args['objects'][0]['object'] == FIRST and args['onNameConflict'] == 'merge', args
            return {'objects': [{'id': FIRST, 'name': 'Sender', '@Effects': [{'id': ROOT, 'name': 'Slot'}]}]}
        result = original(uri, args, options)
        if uri.endswith('object.get'):
            return {'return': [{key: deepcopy(row.get(key, row.get('@' + key))) for key in options['return']
                if key in row or '@' + key in row} for row in result['return']]}
        return result
    task.call = call
    return task, writes


def declare_list_merge(task, *, explicit_reference=False):
    owner = task.bind(FIRST)
    code, listed = task.step('draft-discover-fields', '--object-handle', owner,
        '--field-source', 'documented-lists', '--list')
    assert code == 0, listed
    choice = next(row for row in listed['agent_result']['items'] if row['name'] == 'Effects')
    code, chosen = task.step('draft-discover-fields', '--object-handle', owner,
        '--field-source', 'documented-lists', '--selection', choice['selection'])
    assert code == 0, chosen
    field = chosen['meaning_results'][0]['candidates'][0]['handle']
    code, types = task.step('draft-discover-types', '--role', 'object', '--meaning', 'EffectSlot')
    assert code == 0, types
    kind = types['type_candidates'][0]['handle']
    bypass = select_field(task, kind=kind, token='Bypass')
    reference = (['--field-value', select_field(task, kind=kind, token='Effect'), task.bind(EFFECT)]
        if explicit_reference else [])
    code, configured = task.step('draft-business-configure', '--name-conflict', 'merge')
    assert code == 0, configured
    code, declared = task.step('draft-declare-new', '--declaration-id', 'slot', '--parent-handle', owner,
        '--name', 'Slot', '--kind', kind, '--field', 'object_list', field, '--field-value', bypass, 'true', *reference)
    assert code == 0, declared
    return owner


@pytest.mark.parametrize('version', ['2023.1', '2024.1', '2025.1'])
@pytest.mark.parametrize('operation', ['object.create', 'object.set'])
def test_list_merge_existing_effect_satisfies_bypass_without_reference_write(tmp_path, version, operation):
    task, writes = list_task(tmp_path, version=version, operation=operation)
    before = deepcopy(task.objects)
    declare_list_merge(task)
    tx, shown = task.preview()
    nodes = shown['artifact']['prepared_operation']['verification_plan']['nodes']
    member = next(node for node in nodes if node.get('requested_name') == 'Slot')
    assert member['preexisting_id'] == ROOT and 'new_object_default_evidence' not in member
    code, verified = task.finish(tx, shown)
    if code:
        (tmp_path / "list-verification.json").write_text(json.dumps(verified, indent=2))
    assert code == 0 and verified.get('verified') is True, verified
    assert len(writes) == 1
    assert task.objects[ROOT] == {**before[ROOT], '@Bypass': True}
    assert task.objects[FIRST] == before[FIRST] and task.objects[CHILD] == before[CHILD]
    assert task.objects[EFFECT] == before[EFFECT]


def test_nested_list_merge_binds_actual_member_below_merged_planned_owner(tmp_path):
    task, writes = list_task(tmp_path, operation='object.set')
    parent = task.bind(SECOND)
    code, found = task.step('draft-discover-types', '--role', 'object', '--meaning', 'Sound')
    assert code == 0, found
    sound = found['type_candidates'][0]['handle']
    code, configured = task.step('draft-business-configure', '--name-conflict', 'merge')
    assert code == 0, configured
    code, created = task.step('draft-declare-new', '--declaration-id', 'sound', '--parent-handle', parent,
        '--name', 'Sender', '--kind', sound)
    assert code == 0, created
    owner = created['draft']['declared_object']['result_handle']
    code, listed = task.step('draft-discover-fields', '--type-handle', sound,
        '--field-source', 'documented-lists', '--list')
    assert code == 0, listed
    choice = next(row for row in listed['agent_result']['items'] if row['name'] == 'Effects')
    code, selected = task.step('draft-discover-fields', '--type-handle', sound,
        '--field-source', 'documented-lists', '--selection', choice['selection'])
    assert code == 0, selected
    field = selected['meaning_results'][0]['candidates'][0]['handle']
    code, found = task.step('draft-discover-types', '--role', 'object', '--meaning', 'EffectSlot')
    assert code == 0, found
    slot = found['type_candidates'][0]['handle']
    bypass = select_field(task, kind=slot, token='Bypass')
    code, declared = task.step('draft-declare-new', '--declaration-id', 'slot', '--parent-handle', owner,
        '--name', 'Slot', '--kind', slot, '--field', 'object_list', field, '--field-value', bypass, 'true')
    assert code == 0, declared
    original = task.call
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            writes.append((uri, deepcopy(args)))
            assert args['objects'] == [{'object': SECOND, 'children': [
                {'type': 'Sound', 'name': 'Sender', '@Effects': [{'type': 'EffectSlot', 'name': 'Slot', '@Bypass': True}]}]}]
            task.objects[ROOT]['@Bypass'] = True
            return {'objects': [{'id': SECOND, 'name': 'Default Work Unit', 'children': [
                {'id': FIRST, 'name': 'Sender', '@Effects': [{'id': ROOT, 'name': 'Slot'}]}]}]}
        return original(uri, args, options)
    task.call = call
    before = deepcopy(task.objects)
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    if code:
        (tmp_path / 'list-verification.json').write_text(json.dumps(verified, indent=2))
    assert code == 0 and verified.get('verified') is True, verified
    assert len(writes) == 1
    assert task.objects == {**before, ROOT: {**before[ROOT], '@Bypass': True}}


@pytest.mark.parametrize('operation', ['object.create', 'object.set'])
@pytest.mark.parametrize('fault', ['class', 'owner', 'notes', 'reference', 'metadata', 'membership', 'target-notes'])
def test_existing_list_collision_revalidates_before_single_dispatch(tmp_path, operation, fault):
    task, writes = list_task(tmp_path, operation=operation)
    declare_list_merge(task)
    tx, shown = task.preview()
    if fault == 'class': task.objects[ROOT]['classId'] = 5308432
    if fault == 'owner': task.objects[ROOT]['owner'] = {'id': SECOND}
    if fault == 'notes': task.objects[ROOT]['notes'] = 'Drift'
    if fault == 'reference': task.objects[ROOT]['@Effect'] = None
    if fault == 'metadata': task.metadata['Bypass']['dependencies'][0]['context'] = 'Parent'
    if fault == 'membership': task.objects[FIRST]['@Effects'].reverse()
    if fault == 'target-notes': task.objects[EFFECT]['notes'] = 'Drift'
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, rejected = task.run('execute', tx)
    assert code == 2 and rejected.get('executed') is not True, rejected
    assert not writes


@pytest.mark.parametrize('operation', ['object.create', 'object.set'])
@pytest.mark.parametrize('fault', ['guid', 'class', 'owner', 'notes', 'path', 'value', 'reference',
    'spare-notes', 'spare-path', 'target-notes', 'membership'])
def test_existing_list_merge_rejects_wrong_effect_or_unrequested_changes(tmp_path, operation, fault):
    task, writes = list_task(tmp_path, operation=operation)
    declare_list_merge(task)
    tx, shown = task.preview()
    original = task.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith(('object.create', 'object.set')):
            if fault == 'guid':
                node = result if operation == 'object.create' else result['objects'][0]['@Effects'][0]
                node['id'] = CHILD
            if fault == 'class': task.objects[ROOT]['classId'] = 5308432
            if fault == 'owner': task.objects[ROOT]['owner'] = {'id': SECOND}
            if fault == 'notes': task.objects[ROOT]['notes'] = 'Reset'
            if fault == 'path': task.objects[ROOT]['path'] += 'Unexpected'
            if fault == 'value': task.objects[ROOT]['@Bypass'] = False
            if fault == 'reference': task.objects[ROOT]['@Effect'] = None
            if fault == 'spare-notes': task.objects[CHILD]['notes'] = 'Reset'
            if fault == 'spare-path': task.objects[CHILD]['path'] += 'Unexpected'
            if fault == 'target-notes': task.objects[EFFECT]['notes'] = 'Reset'
            if fault == 'membership': task.objects[FIRST]['@Effects'].reverse()
        return result
    task.call = call
    code, verified = task.finish(tx, shown)
    assert code == 2 and verified.get('verified') is not True, verified
    assert len(writes) == 1


@pytest.mark.parametrize('operation,mode', [('object.create', 'merge'), ('object.create', 'fail'),
    ('object.set', 'merge'), ('object.set', 'replace-all'), ('object.set', 'replace')])
def test_list_collision_only_append_merge_can_use_observed_reference_condition(tmp_path, operation, mode):
    task, writes = list_task(tmp_path, operation=operation)
    declare_list_merge(task)
    if mode == 'merge':
        # A real collision whose actual prerequisite is absent must still fail.
        task.objects[ROOT]['@Effect'] = None
    elif mode in {'fail', 'replace'}:
        code, changed = task.step('draft-business-configure', '--name-conflict', mode)
        assert code == 0, changed
    else:
        # Replacing a List is creation; the deleted slot cannot lend its Effect.
        code, changed = task.step('draft-business-configure', '--list-behavior', 'replace-all')
        assert code == 0, changed
    code, rejected = task.step('draft-check')
    assert code == 2 and 'REFERENCE_ACTIVATION_REQUIRED' in json.dumps(rejected), rejected
    assert not writes


@pytest.mark.parametrize('fault', ['wrong-class', 'missing-class', 'wrong-owner', 'duplicate-name'])
def test_list_merge_rejects_unproved_actual_collision(tmp_path, fault):
    task, writes = list_task(tmp_path)
    declare_list_merge(task)
    if fault == 'wrong-class': task.objects[ROOT]['classId'] = 5308432
    if fault == 'missing-class': del task.objects[ROOT]['classId']
    if fault == 'wrong-owner': task.objects[ROOT]['owner'] = {'id': SECOND}
    if fault == 'duplicate-name': task.objects[CHILD]['name'] = 'Slot'
    code, rejected = task.step('draft-check')
    assert code == 2, rejected
    assert not writes


@pytest.mark.parametrize('fault', [None, 'wrong-member-path', 'wrong-owner-guid'])
def test_existing_list_member_path_follows_only_requested_exact_owner_rename(tmp_path, fault):
    task, writes = list_task(tmp_path, version='2024.1', operation='object.set')
    work_unit = '{77777777-7777-7777-7777-777777777777}'
    task.objects[work_unit] = deepcopy(task.objects[SECOND])
    task.objects[work_unit]['id'] = work_unit
    task.objects[SECOND].update(name='Parent', type='ActorMixer', classId=73744,
        path=task.objects[work_unit]['path'] + r'\Parent', parent={'id': work_unit})
    for object_id in (FIRST, ROOT, CHILD):
        task.objects[object_id]['path'] = task.objects[object_id]['path'].replace(
            r'\Default Work Unit\Sender', r'\Default Work Unit\Parent\Sender')
    task.types.append({'name': 'ActorMixer', 'classId': 73744, 'type': 'WObject'})
    declare_list_merge(task)
    owner = task.bind(SECOND)
    code, declared = task.step('draft-declare-existing', '--declaration-id', 'owner', '--object-handle', owner,
        '--field', 'new_name', 'Storm', '--field', 'name_conflict', 'fail')
    assert code == 0, declared
    original = task.call
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            writes.append((uri, deepcopy(args)))
            assert args['objects'] == [{'object': SECOND, 'name': 'Storm', 'onNameConflict': 'fail'},
                {'object': FIRST, '@Effects': [{'type': 'EffectSlot', 'name': 'Slot', '@Bypass': True}]}]
            task.objects[SECOND].update(name='Storm', path=task.objects[work_unit]['path'] + r'\Storm')
            task.objects[FIRST]['path'] = task.objects[SECOND]['path'] + r'\Sender'
            for member in (ROOT, CHILD):
                task.objects[member]['path'] = task.objects[FIRST]['path'] + '\\' + task.objects[member]['name']
            task.objects[ROOT]['@Bypass'] = True
            if fault == 'wrong-member-path': task.objects[ROOT]['path'] += 'Unexpected'
            if fault == 'wrong-owner-guid': task.objects[ROOT]['owner'] = {'id': SECOND}
            return {'objects': [{'id': SECOND, 'name': 'Storm'},
                {'id': FIRST, 'name': 'Sender', '@Effects': [{'id': ROOT, 'name': 'Slot'}]}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    if code:
        (tmp_path / 'list-verification.json').write_text(json.dumps(verified, indent=2))
    assert code == (0 if fault is None else 2), verified
    assert (verified.get('verified') is True) == (fault is None), verified
    assert len(writes) == 1


@pytest.mark.parametrize('version,operation', [('2021.1', 'object.setProperty'),
    ('2022.1', 'object.setProperty'), ('2022.1', 'object.set')])
@pytest.mark.parametrize('bound', [True, False])
def test_legacy_sound_effect_scalar_uses_real_effect_n_reference_and_override(tmp_path, version, operation, bound):
    task, _unused = list_task(tmp_path, version=version, operation=operation)
    task.types = [item for item in task.types if item['name'] != 'EffectSlot']
    del task.objects[ROOT], task.objects[CHILD], task.objects[FIRST]['@Effects']
    task.objects[FIRST].update({'@Effect0': {'id': EFFECT} if bound else None, '@BypassEffect0': False})
    override = {'type': 'override', 'action': 'Enable', 'context': 'Self', 'property': 'OverrideEffect'}
    # Effective Sound groups2021/22: EffectsReferences, EffectsBypass and
    # EffectsBase's declared controller. This normalized fixture is not native evidence.
    task.metadata = {
        'OverrideEffect': {'name': 'OverrideEffect', 'type': 'bool', 'default': False, 'dependencies': [override]},
        'Effect0': {'name': 'Effect0', 'type': '', 'default': None, 'dependencies': [override],
            'restriction': {'type': 'reference', 'restrictions': [{'type': ['Effect']}]}},
        'BypassEffect0': {'name': 'BypassEffect0', 'type': 'bool', 'default': False,
            'dependencies': [override, {'type': 'reference', 'action': 'Enable', 'context': 'Self',
                'property': 'Effect0', 'conditions': [{'referenceIsSet': True}]}]},
    }
    prior = task.call
    def with_enabled(uri, args=None, options=None):
        if uri.endswith('isPropertyEnabled'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': bound}  # Scalar fixture-only observer, no native Boolean claim.
        return prior(uri, args, options)
    task.call = with_enabled
    target = task.bind(FIRST)
    field = select_field(task, owner=target, token='BypassEffect0')
    if operation == 'object.set':
        code, declared = task.step('draft-declare-existing', '--declaration-id', 'sound', '--object-handle', target,
            '--field-value', field, 'true')
    else:
        code, declared = task.step('draft-declare-field-change', '--object-handle', target, '--field-handle', field,
            '--business-value', 'true')
    assert code == 0, declared
    writes = []
    original = task.call
    def call(uri, args=None, options=None):
        if uri.endswith(('object.set', 'setProperty')):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            writes.append((uri, deepcopy(args)))
            if operation == 'object.set':
                assert args['objects'] == [{'object': FIRST, '@BypassEffect0': True}]
                result = {'objects': [{'id': FIRST, 'name': 'Sender'}]}
            else:
                assert args == {'object': FIRST, 'property': 'BypassEffect0', 'value': True}
                result = {}
            task.objects[FIRST]['@BypassEffect0'] = True
            return result
        return original(uri, args, options)
    task.call = call
    before = deepcopy(task.objects)
    if not bound:
        code, rejected = task.step('draft-check')
        assert code == 2, rejected
        assert not writes
        return
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified.get('verified') is True, verified
    assert len(writes) == 1 and task.objects == {**before, FIRST: {**before[FIRST], '@BypassEffect0': True}}


@pytest.mark.parametrize('operation', ['object.create', 'object.set'])
def test_list_merge_explicit_reference_satisfies_initially_unbound_actual_slot(tmp_path, operation):
    task, writes = list_task(tmp_path, operation=operation, explicit_reference=True)
    task.objects[ROOT]['@Effect'] = None
    declare_list_merge(task, explicit_reference=True)
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified.get('verified') is True, verified
    assert len(writes) == 1
    assert task.objects[ROOT]['@Effect'] == {'id': EFFECT} and task.objects[ROOT]['@Bypass'] is True


@pytest.mark.parametrize('fault', [None, 'changed-path'])
def test_merge_preserves_opaque_observed_slot_path_without_child_path_guess(tmp_path, fault):
    task, writes = list_task(tmp_path)
    task.objects[ROOT]['path'] = r'\opaque-slot-identity'
    declare_list_merge(task)
    original = task.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('object.create') and fault:
            task.objects[ROOT]['path'] = r'\another-opaque-identity'
        return result
    task.call = call
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == (0 if fault is None else 2), verified
    assert (verified.get('verified') is True) == (fault is None), verified
    assert len(writes) == 1


def test_replace_all_effect_slot_uses_new_supplied_reference_and_removes_old_members(tmp_path):
    task, writes = list_task(tmp_path, operation='object.set')
    declare_list_merge(task, explicit_reference=True)
    code, changed = task.step('draft-business-configure', '--list-behavior', 'replace-all')
    assert code == 0, changed
    fresh = '{77777777-7777-7777-7777-777777777777}'
    original = task.call
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            writes.append((uri, deepcopy(args)))
            assert args['listMode'] == 'replaceAll'
            assert args['objects'] == [{'object': FIRST,
                '@Effects': [{'type': 'EffectSlot', 'name': 'Slot', '@Bypass': True, '@Effect': EFFECT}]}]
            del task.objects[ROOT], task.objects[CHILD]
            task.objects[fresh] = {'id': fresh, 'name': 'Slot', 'type': 'PluginInnerObject', 'classId': 5505040,
                'path': r'\opaque-new-slot', 'owner': {'id': FIRST}, 'notes': '', '@Effect': {'id': EFFECT}, '@Bypass': True}
            task.objects[FIRST]['@Effects'] = [{'id': fresh}]
            return {'objects': [{'id': FIRST, 'name': 'Sender', '@Effects': [{'id': fresh, 'name': 'Slot'}]}]}
        return original(uri, args, options)
    task.call = call
    effect_before = deepcopy(task.objects[EFFECT])
    tx, shown = task.preview()
    member = next(node for node in shown['artifact']['prepared_operation']['verification_plan']['nodes']
        if node.get('requested_name') == 'Slot')
    assert 'preexisting_id' not in member and member.get('new_object_default_evidence')
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified.get('verified') is True, verified
    assert len(writes) == 1 and ROOT not in task.objects and CHILD not in task.objects
    assert task.objects[FIRST]['@Effects'] == [{'id': fresh}]
    assert task.objects[EFFECT] == effect_before


def test_list_merge_shared_effect_observation_agrees_for_explicit_and_retained_references(tmp_path):
    task, writes = list_task(tmp_path, operation='object.set')
    owner = declare_list_merge(task)
    task.objects[CHILD]['@Effect'] = None
    code, found = task.step('draft-discover-types', '--role', 'object', '--meaning', 'EffectSlot')
    assert code == 0, found
    kind = found['type_candidates'][0]['handle']
    bypass, effect = select_field(task, kind=kind, token='Bypass'), select_field(task, kind=kind, token='Effect')
    target = task.bind(EFFECT)
    code, declared = task.step('draft-declare-new', '--declaration-id', 'spare', '--parent-handle', owner,
        '--name', 'Spare', '--kind', kind, '--field', 'object_list', 'Effects',
        '--field-value', bypass, 'true', '--field-value', effect, target)
    assert code == 0, declared
    original = task.call
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            writes.append((uri, deepcopy(args)))
            assert args['objects'] == [{'object': FIRST, '@Effects': [
                {'type': 'EffectSlot', 'name': 'Slot', '@Bypass': True},
                {'type': 'EffectSlot', 'name': 'Spare', '@Bypass': True, '@Effect': EFFECT}]}]
            task.objects[ROOT]['@Bypass'] = True
            task.objects[CHILD].update({'@Bypass': True, '@Effect': {'id': EFFECT}})
            return {'objects': [{'id': FIRST, 'name': 'Sender', '@Effects': [
                {'id': ROOT, 'name': 'Slot'}, {'id': CHILD, 'name': 'Spare'}]}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified.get('verified') is True, verified
    assert len(writes) == 1
