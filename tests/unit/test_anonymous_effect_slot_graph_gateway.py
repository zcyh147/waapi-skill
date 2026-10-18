"""Anonymous EffectSlot construction uses source placement and ordered membership."""
from copy import deepcopy
import json

import pytest

from tests.unit.test_list_merge_existing_conditions_gateway import list_task, select_field, EFFECT, EFFECT_PARENT
from tests.unit.test_object_graph_owned_choices_gateway import FIRST, ROOT, CHILD

EFFECT_B = '{77777777-7777-7777-7777-777777777777}'
SLOT_A = '{88888888-8888-8888-8888-888888888888}'
SLOT_B = '{99999999-9999-9999-9999-999999999999}'


def anonymous_task(tmp_path, version='2025.1'):
    task, _ = list_task(tmp_path, version=version, operation='object.set')
    task.types.append({"name": "Wwise Meter", "classId": 8454147, "type": "Effect"})
    # Existing anonymous slot representation follows the retained native fact:
    # slot.owner=Sound, opaque path, no parent projection. Effects here are
    # independent ShareSet fixtures with actual folder parent, not local effects.
    for identity, path in [(ROOT, r'\Opaque old slot A'), (CHILD, r'\Opaque old slot B')]:
        task.objects[identity]['name'] = ''
        task.objects[identity]['path'] = path
    task.objects[EFFECT_B] = {**deepcopy(task.objects[EFFECT]), 'id': EFFECT_B,
        'name': 'Other ShareSet', 'path': r'\Effects\Default Work Unit\Other ShareSet'}
    return task


def declare_slots(task, *, owner=None, owner_kind=None, targets=None):
    owner = task.bind(FIRST) if owner is None else owner
    scope = ["--object-handle", owner] if owner_kind is None else ["--type-handle", owner_kind]
    code, listed = task.step('draft-discover-fields', *scope,
        '--field-source', 'documented-lists', '--list')
    assert code == 0, listed
    choice = next(row for row in listed['agent_result']['items'] if row['name'] == 'Effects')
    code, selected = task.step('draft-discover-fields', *scope,
        '--field-source', 'documented-lists', '--selection', choice['selection'])
    assert code == 0, selected
    effects = selected['meaning_results'][0]['candidates'][0]['handle']
    code, found = task.step('draft-discover-types', '--role', 'object', '--meaning', 'EffectSlot')
    assert code == 0, found
    kind = found['type_candidates'][0]['handle']
    fields = {name: select_field(task, kind=kind, token=name) for name in ['Effect', 'Bypass', 'Render']}
    targets = [EFFECT, EFFECT_B] if targets is None else targets
    for name, target, bypass, render in [('first', targets[0], 'true', 'false'), ('second', targets[1], 'false', 'true')]:
        handle = target if target.startswith('bnh1-') else task.bind(target)
        code, declared = task.step('draft-declare-new', '--declaration-id', name, '--parent-handle', owner,
            '--kind', kind, '--field', 'object_list', effects,
            '--field-value', fields['Effect'], handle, '--field-value', fields['Bypass'], bypass,
            '--field-value', fields['Render'], render)
        assert code == 0, declared
    return owner


@pytest.mark.parametrize("fault", [None, "old-bypass"])
def test_two_anonymous_slots_bind_independent_membership_not_returned_order(tmp_path, fault):
    task = anonymous_task(tmp_path)
    before = deepcopy(task.objects)
    declare_slots(task)
    original, writes = task.call, []
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            writes.append(deepcopy(args))
            assert args['objects'] == [{'object': FIRST, '@Effects': [
                {'type': 'EffectSlot', 'name': '', '@Bypass': True, '@Render': False, '@Effect': EFFECT},
                {'type': 'EffectSlot', 'name': '', '@Bypass': False, '@Render': True, '@Effect': EFFECT_B}]}], args
            for identity, effect, bypass, render, path in [
                (SLOT_A, EFFECT, True, False, r'\Opaque new slot A'),
                (SLOT_B, EFFECT_B, False, True, r'\Opaque new slot B')]:
                task.objects[identity] = {'id': identity, 'name': '', 'type': 'PluginInnerObject',
                    'classId': 5505040, 'owner': {'id': FIRST}, 'path': path, 'notes': '',
                    '@Effect': {'id': effect}, '@Bypass': bypass, '@Render': render}
            task.objects[FIRST]['@Effects'] += [{'id': SLOT_A}, {'id': SLOT_B}]
            if fault == 'old-bypass':
                task.objects[ROOT]['@Bypass'] = True
            # Returned associations are explicitly reversed. Their order cannot
            # identify declarations; independent owner Effects order can.
            return {'objects': [{'id': FIRST, 'name': 'Sender', '@Effects': [
                {'id': SLOT_B, 'name': ''}, {'id': SLOT_A, 'name': ''}]}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == (2 if fault else 0), json.dumps(verified)
    assert (verified.get('verified') is True) == (fault is None), verified
    assert len(writes) == 1
    if fault:
        return
    assert [row['id'] for row in task.objects[FIRST]['@Effects']] == [ROOT, CHILD, SLOT_A, SLOT_B]
    assert all(task.objects[identity] == before[identity] for identity in [ROOT, CHILD, EFFECT, EFFECT_B, EFFECT_PARENT])


def test_planned_sound_owns_two_new_anonymous_slots(tmp_path):
    from tests.unit.test_object_graph_owned_choices_gateway import SECOND
    task = anonymous_task(tmp_path)
    parent = task.bind(SECOND)
    code, types = task.step('draft-discover-types', '--role', 'object', '--meaning', 'Sound')
    assert code == 0, types
    kind = types['type_candidates'][0]['handle']
    code, declared = task.step('draft-declare-new', '--declaration-id', 'sound', '--parent-handle', parent,
        '--name', 'New sound', '--kind', kind)
    assert code == 0, declared
    owner = declared['draft']['declared_object']['result_handle']
    declare_slots(task, owner=owner, owner_kind=kind)
    new_owner = '{ABABABAB-ABAB-ABAB-ABAB-ABABABABABAB}'
    original, writes = task.call, []
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            writes.append(deepcopy(args))
            sound = args['objects'][0]['children'][0]
            assert sound['type'] == 'Sound' and sound['name'] == 'New sound', args
            assert [row['name'] for row in sound['@Effects']] == ['', '']
            task.objects[new_owner] = {'id': new_owner, 'name': 'New sound', 'type': 'Sound',
                'classId': 65552, 'path': task.objects[SECOND]['path'] + r'\New sound',
                'parent': {'id': SECOND}, 'notes': '', '@Effects': [{'id': SLOT_A}, {'id': SLOT_B}]}
            for identity, source in [(SLOT_A, sound['@Effects'][0]), (SLOT_B, sound['@Effects'][1])]:
                task.objects[identity] = {'id': identity, 'name': '', 'type': 'PluginInnerObject',
                    'classId': 5505040, 'owner': {'id': new_owner}, 'path': r'\Opaque ' + identity, 'notes': '',
                    '@Effect': {'id': source['@Effect']}, '@Bypass': source['@Bypass'], '@Render': source['@Render']}
            return {'objects': [{'id': SECOND, 'name': task.objects[SECOND]['name'], 'children': [
                {'id': new_owner, 'name': 'New sound', '@Effects': [
                    {'id': SLOT_B, 'name': ''}, {'id': SLOT_A, 'name': ''}]}]}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified.get('verified') is True, json.dumps(verified)
    assert len(writes) == 1


@pytest.mark.parametrize("fault", [None, "wrong-reference"])
def test_anonymous_slot_references_same_graph_new_independent_shareset(tmp_path, fault):
    task = anonymous_task(tmp_path)
    parent = task.bind(EFFECT_PARENT)
    code, found = task.step('draft-discover-types', '--role', 'effect', '--meaning', 'Wwise Meter')
    assert code == 0, found
    kind = found['type_candidates'][0]['handle']
    code, declared = task.step('draft-declare-new', '--declaration-id', 'new-effect', '--parent-handle', parent,
        '--name', 'New ShareSet', '--kind', kind, '--field', 'plugin_placement', 'shareset')
    assert code == 0, declared
    effect_handle = declared['draft']['declared_object']['result_handle']
    declare_slots(task, targets=[effect_handle, EFFECT_B])
    tx, shown = task.preview()
    native = shown['artifact']['prepared_operation']['dispatch']['args']
    assert native['objects'][0] == {'object': EFFECT_PARENT, 'children': [
        {'type': 'Effect', 'name': 'New ShareSet', 'classId': 8454147}]}
    assert native['objects'][1]['object'] == FIRST
    assert native['objects'][1]['@Effects'][0]['@Effect'] == r'\Effects\Default Work Unit\New ShareSet'

    new_effect = '{CDCDCDCD-CDCD-CDCD-CDCD-CDCDCDCDCDCD}'
    original, writes = task.call, []
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            writes.append(deepcopy(args))
            assert args == native
            task.objects[new_effect] = {'id': new_effect, 'name': 'New ShareSet', 'type': 'Effect',
                'classId': 8454147, 'path': r'\Effects\Default Work Unit\New ShareSet',
                'parent': {'id': EFFECT_PARENT}, 'notes': ''}
            for identity, effect, bypass, render in [(SLOT_A, new_effect, True, False), (SLOT_B, EFFECT_B, False, True)]:
                task.objects[identity] = {'id': identity, 'name': '', 'type': 'PluginInnerObject',
                    'classId': 5505040, 'path': r'\Opaque ' + identity, 'owner': {'id': FIRST}, 'notes': '',
                    '@Effect': {'id': EFFECT if fault == 'wrong-reference' else effect}, '@Bypass': bypass, '@Render': render}
            task.objects[FIRST]['@Effects'] += [{'id': SLOT_A}, {'id': SLOT_B}]
            return {'objects': [
                {'id': FIRST, 'name': 'Sender', '@Effects': [{'id': SLOT_B, 'name': ''}, {'id': SLOT_A, 'name': ''}]},
                {'id': EFFECT_PARENT, 'name': 'Default Work Unit', 'children': [{'id': new_effect, 'name': 'New ShareSet'}]}]}
        return original(uri, args, options)
    task.call = call
    code, verified = task.finish(tx, shown)
    assert code == (2 if fault else 0), json.dumps(verified)
    assert (verified.get('verified') is True) == (fault is None), verified
    assert len(writes) == 1


@pytest.mark.parametrize("fault", [None, "wrong-owner"])
def test_new_local_effect_is_inline_owned_by_the_new_anonymous_slot(tmp_path, fault):
    task = anonymous_task(tmp_path)
    owner = task.bind(FIRST)
    code, found = task.step('draft-discover-types', '--role', 'object', '--meaning', 'EffectSlot')
    assert code == 0, found
    slot_kind = found['type_candidates'][0]['handle']
    bypass = select_field(task, kind=slot_kind, token='Bypass')
    code, listed = task.step('draft-discover-fields', '--object-handle', owner, '--field-source', 'documented-lists', '--list')
    assert code == 0, listed
    selection = next(row['selection'] for row in listed['agent_result']['items'] if row['name'] == 'Effects')
    code, selected = task.step('draft-discover-fields', '--object-handle', owner, '--field-source', 'documented-lists', '--selection', selection)
    assert code == 0, selected
    effects = selected['meaning_results'][0]['candidates'][0]['handle']
    code, declared = task.step('draft-declare-new', '--declaration-id', 'slot', '--parent-handle', owner,
        '--kind', slot_kind, '--field', 'object_list', effects, '--field-value', bypass, 'true')
    assert code == 0, declared
    slot_handle = declared['draft']['declared_object']['result_handle']
    code, found = task.step('draft-discover-types', '--role', 'effect', '--meaning', 'Wwise Meter')
    assert code == 0, found
    code, declared = task.step('draft-declare-new', '--declaration-id', 'local', '--parent-handle', slot_handle,
        '--name', 'Local Effect', '--kind', found['type_candidates'][0]['handle'], '--field', 'plugin_placement', 'owner')
    assert code == 0, declared
    tx, shown = task.preview()
    assert shown['artifact']['prepared_operation']['dispatch']['args']['objects'] == [
        {'object': FIRST, '@Effects': [{'type': 'EffectSlot', 'name': '', '@Bypass': True,
            '@Effect': {'type': 'Effect', 'name': 'Local Effect', 'classId': 8454147}}]}]

    local = '{EFEFEFEF-EFEF-EFEF-EFEF-EFEFEFEFEFEF}'
    original, writes = task.call, []
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            writes.append(deepcopy(args))
            slot = args['objects'][0]['@Effects'][0]
            assert slot['@Effect'] == {'type': 'Effect', 'name': 'Local Effect', 'classId': 8454147}
            task.objects[SLOT_A] = {'id': SLOT_A, 'name': '', 'type': 'PluginInnerObject', 'classId': 5505040,
                'owner': {'id': FIRST}, 'path': r'\Opaque new slot', 'notes': '', '@Effect': {'id': local}, '@Bypass': True, '@Render': False}
            # Actual retained native topology: local Effect owner is the slot,
            # with parent unavailable. This is distinct from a ShareSet.
            task.objects[local] = {'id': local, 'name': 'Local Effect', 'type': 'Effect', 'classId': 8454147,
                'owner': {'id': FIRST if fault else SLOT_A}, 'path': r'\Opaque local effect', 'notes': ''}
            task.objects[FIRST]['@Effects'].append({'id': SLOT_A})
            return {'objects': [{'id': FIRST, 'name': 'Sender', '@Effects': [
                {'id': SLOT_A, 'name': '', '@Effect': {'id': local, 'name': 'Local Effect'}}]}]}
        return original(uri, args, options)
    task.call = call
    code, verified = task.finish(tx, shown)
    assert code == (2 if fault else 0), json.dumps(verified)
    assert (verified.get('verified') is True) == (fault is None), verified
    assert len(writes) == 1
    assert 'parent' not in task.objects[SLOT_A] and 'parent' not in task.objects[local]


def test_existing_local_effect_cannot_be_assumed_to_be_a_reusable_shareset(tmp_path):
    task = anonymous_task(tmp_path)
    task.objects[EFFECT]['owner'] = {'id': ROOT}
    task.objects[EFFECT].pop('parent')
    task.objects[EFFECT]['path'] = r'\Opaque local Effect'
    declare_slots(task)
    code, checked = task.step('draft-check')
    assert code == 2 and 'LOCAL_EFFECT_REUSE_UNRESOLVED' in json.dumps(checked), checked
    assert not any(uri.endswith('object.set') for uri, _, _ in task.calls)
