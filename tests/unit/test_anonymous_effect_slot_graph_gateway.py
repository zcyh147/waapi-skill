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


@pytest.mark.parametrize('version,mode,fault', [
    ('2023.1', 'append', None), ('2024.1', 'replace-all', None),
    ('2025.1', 'append', None), ('2025.1', 'replace-all', None),
    *[('2025.1', 'append', fault) for fault in ['old-bypass', 'order', 'class', 'owner',
        'duplicate-return', 'old-return', 'spare-notes', 'target-notes', 'value']],
    *[('2025.1', 'replace-all', fault) for fault in ['order', 'old-return', 'retained-old-member']],
])
def test_two_anonymous_slots_bind_independent_membership_not_returned_order(tmp_path, version, mode, fault):
    task = anonymous_task(tmp_path, version)
    before = deepcopy(task.objects)
    declare_slots(task)
    if mode == 'replace-all':
        code, configured = task.step('draft-business-configure', '--list-behavior', mode)
        assert code == 0, json.dumps(configured)
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
            if mode == 'replace-all':
                assert args['listMode'] == 'replaceAll'
                task.objects[FIRST]['@Effects'] = []
                if fault == 'retained-old-member':
                    task.objects[FIRST]['@Effects'].append({'id': ROOT})
                else:
                    del task.objects[ROOT]
                del task.objects[CHILD]
            task.objects[FIRST]['@Effects'] += [{'id': SLOT_A}, {'id': SLOT_B}]
            if fault == 'order':
                task.objects[FIRST]['@Effects'][-2:] = [{'id': SLOT_B}, {'id': SLOT_A}]
            if fault == 'class': task.objects[SLOT_A]['classId'] = 5570560
            if fault == 'owner': task.objects[SLOT_A]['owner'] = {'id': EFFECT_PARENT}
            if fault == 'value': task.objects[SLOT_A]['@Bypass'] = False
            if fault == 'spare-notes': task.objects[CHILD]['notes'] = 'Reset'
            if fault == 'target-notes': task.objects[EFFECT_B]['notes'] = 'Reset'
            if fault == 'old-bypass':
                task.objects[ROOT]['@Bypass'] = True
            # Returned associations are explicitly reversed. Their order cannot
            # identify declarations; independent owner Effects order can.
            return {'objects': [{'id': FIRST, 'name': 'Sender', '@Effects': [
                {'id': SLOT_A if fault == 'duplicate-return' else ROOT if fault == 'old-return' else SLOT_B, 'name': ''},
                {'id': SLOT_A, 'name': ''}]}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == (2 if fault else 0), json.dumps(verified)
    assert (verified.get('verified') is True) == (fault is None), verified
    assert len(writes) == 1
    if fault:
        return
    expected = [SLOT_A, SLOT_B] if mode == 'replace-all' else [ROOT, CHILD, SLOT_A, SLOT_B]
    assert [row['id'] for row in task.objects[FIRST]['@Effects']] == expected
    preserved = [EFFECT, EFFECT_B, EFFECT_PARENT] + ([ROOT, CHILD] if mode == 'append' else [])
    assert all(task.objects[identity] == before[identity] for identity in preserved)


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
@pytest.mark.parametrize("planned_owner", [False, True])
def test_new_local_effect_is_inline_owned_by_the_new_anonymous_slot(tmp_path, fault, planned_owner):
    task = anonymous_task(tmp_path)
    from tests.unit.test_object_graph_owned_choices_gateway import SECOND
    actual_owner = '{ABABABAB-ABAB-ABAB-ABAB-ABABABABABAB}' if planned_owner else FIRST
    if planned_owner:
        parent = task.bind(SECOND)
        code, types = task.step('draft-discover-types', '--role', 'object', '--meaning', 'Sound')
        assert code == 0, types
        sound_kind = types['type_candidates'][0]['handle']
        code, created = task.step('draft-declare-new', '--declaration-id', 'owner', '--parent-handle', parent,
            '--name', 'New owner', '--kind', sound_kind)
        assert code == 0, created
        owner = created['draft']['declared_object']['result_handle']
        scope = ['--type-handle', sound_kind]
    else:
        owner = task.bind(FIRST)
        scope = ['--object-handle', owner]
    code, found = task.step('draft-discover-types', '--role', 'object', '--meaning', 'EffectSlot')
    assert code == 0, found
    slot_kind = found['type_candidates'][0]['handle']
    bypass = select_field(task, kind=slot_kind, token='Bypass')
    code, listed = task.step('draft-discover-fields', *scope, '--field-source', 'documented-lists', '--list')
    assert code == 0, listed
    selection = next(row['selection'] for row in listed['agent_result']['items'] if row['name'] == 'Effects')
    code, selected = task.step('draft-discover-fields', *scope, '--field-source', 'documented-lists', '--selection', selection)
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
    expected_slot = {'type': 'EffectSlot', 'name': '', '@Bypass': True,
        '@Effect': {'type': 'Effect', 'name': 'Local Effect', 'classId': 8454147}}
    expected = ([{'object': SECOND, 'children': [{'type': 'Sound', 'name': 'New owner', '@Effects': [expected_slot]}]}]
        if planned_owner else [{'object': FIRST, '@Effects': [expected_slot]}])
    assert shown['artifact']['prepared_operation']['dispatch']['args']['objects'] == expected

    local = '{EFEFEFEF-EFEF-EFEF-EFEF-EFEFEFEFEFEF}'
    original, writes = task.call, []
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            writes.append(deepcopy(args))
            if planned_owner:
                task.objects[actual_owner] = {'id': actual_owner, 'name': 'New owner', 'type': 'Sound', 'classId': 65552,
                    'parent': {'id': SECOND}, 'path': task.objects[SECOND]['path'] + r'\New owner', 'notes': '', '@Effects': []}
            slot = (args['objects'][0]['children'][0] if planned_owner else args['objects'][0])['@Effects'][0]
            assert slot['@Effect'] == {'type': 'Effect', 'name': 'Local Effect', 'classId': 8454147}
            task.objects[SLOT_A] = {'id': SLOT_A, 'name': '', 'type': 'PluginInnerObject', 'classId': 5505040,
                'owner': {'id': actual_owner}, 'path': r'\Opaque new slot', 'notes': '', '@Effect': {'id': local}, '@Bypass': True, '@Render': False}
            # Actual retained native topology: local Effect owner is the slot,
            # with parent unavailable. This is distinct from a ShareSet.
            task.objects[local] = {'id': local, 'name': 'Local Effect', 'type': 'Effect', 'classId': 8454147,
                'owner': {'id': FIRST if fault else SLOT_A}, 'path': r'\Opaque local effect', 'notes': ''}
            task.objects[actual_owner]['@Effects'].append({'id': SLOT_A})
            result = {'id': actual_owner, 'name': 'New owner' if planned_owner else 'Sender', '@Effects': [
                {'id': SLOT_A, 'name': '', '@Effect': {'id': local, 'name': 'Local Effect'}}]}
            return {'objects': [{'id': SECOND, 'name': 'Default Work Unit', 'children': [result]}] if planned_owner else [result]}
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


@pytest.mark.parametrize('fault', ['owner-class', 'list-order', 'metadata', 'target-owner', 'target-notes'])
def test_anonymous_constructor_revalidates_source_and_target_before_one_write(tmp_path, fault):
    task = anonymous_task(tmp_path)
    declare_slots(task)
    tx, shown = task.preview()
    if fault == 'owner-class': task.objects[FIRST]['classId'] = 2293776
    if fault == 'list-order': task.objects[FIRST]['@Effects'].reverse()
    if fault == 'metadata': task.metadata['Bypass']['dependencies'][0]['context'] = 'Parent'
    if fault == 'target-owner': task.objects[EFFECT]['owner'] = {'id': ROOT}
    if fault == 'target-notes': task.objects[EFFECT]['notes'] = 'Drift'
    original, writes = task.call, []
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            writes.append(deepcopy(args))
            raise RuntimeError('Unexpected write after sealed anonymous source drift')
        return original(uri, args, options)
    task.call = call
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, rejected = task.run('execute', tx)
    assert code == 2, rejected
    assert not writes


@pytest.mark.parametrize('value', ['retarget', 'null', 'zero', 'missing'])
def test_append_can_compose_an_explicit_old_slot_reference_edit(tmp_path, value):
    task = anonymous_task(tmp_path)
    # Retained f4 native receipt returns EffectSlot for this exact binding.
    # The independent class-verified construction controls also cover generic
    # PluginInnerObject projections without rewriting their returned type.
    task.objects[ROOT]['type'] = 'EffectSlot'
    task.objects[ROOT]['@Effect'] = {key: task.objects[EFFECT][key] for key in ['id', 'name', 'type', 'path']}
    declare_slots(task)
    slot = task.bind(ROOT)
    field = select_field(task, owner=slot, token='Effect')
    target = task.bind(EFFECT_B) if value == 'retarget' else 'null'
    code, declared = task.step('draft-declare-existing', '--declaration-id', 'retarget', '--object-handle', slot,
        '--field-value', field, target)
    assert code == 0, declared
    original, writes = task.call, []
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            writes.append(deepcopy(args))
            rows = {row['object']: row for row in args['objects']}
            assert rows[ROOT] == {'object': ROOT, '@Effect': EFFECT_B if value == 'retarget' else None}
            if value == 'retarget':
                task.objects[ROOT]['@Effect'] = {key: task.objects[EFFECT_B][key] for key in ['id', 'name', 'type', 'path']}
            elif value == 'zero':
                task.objects[ROOT]['@Effect'] = {'id': '{00000000-0000-0000-0000-000000000000}', 'name': ''}
            elif value == 'missing':
                del task.objects[ROOT]['@Effect']
            else:
                task.objects[ROOT]['@Effect'] = None
            for identity, source in zip([SLOT_A, SLOT_B], rows[FIRST]['@Effects'], strict=True):
                task.objects[identity] = {'id': identity, 'name': '', 'type': 'PluginInnerObject', 'classId': 5505040,
                    'owner': {'id': FIRST}, 'path': r'\Opaque new slot ' + identity, 'notes': '',
                    '@Effect': {'id': source['@Effect']}, '@Bypass': source['@Bypass'], '@Render': source['@Render']}
            task.objects[FIRST]['@Effects'] += [{'id': SLOT_A}, {'id': SLOT_B}]
            return {'objects': [{'id': FIRST, 'name': 'Sender', '@Effects': [{'id': SLOT_B, 'name': ''}, {'id': SLOT_A, 'name': ''}]}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == (2 if value == 'missing' else 0), json.dumps(verified)
    assert (verified.get('verified') is True) == (value != 'missing'), verified
    assert len(writes) == 1


def test_existing_nested_shareset_reference_uses_actual_parent_chain_not_constructor_destination(tmp_path):
    task = anonymous_task(tmp_path)
    folder = '{BEBEBEBE-BEBE-BEBE-BEBE-BEBEBEBEBEBE}'
    task.types.append({'name': 'Folder', 'classId': 131088, 'type': 'WObject'})
    task.objects[folder] = {'id': folder, 'name': 'Nested ShareSets', 'type': 'Folder', 'classId': 131088,
        'path': task.objects[EFFECT_PARENT]['path'] + r'\Nested ShareSets', 'parent': {'id': EFFECT_PARENT}, 'notes': 'Keep folder'}
    task.objects[EFFECT]['parent'] = {'id': folder}
    task.objects[EFFECT]['path'] = task.objects[folder]['path'] + r'\Existing Effect'
    declare_slots(task)
    code, checked = task.step('draft-check')
    assert code == 0, json.dumps(checked)


def test_public_schema_and_continuation_disclose_source_owned_blank_name(tmp_path):
    task = anonymous_task(tmp_path)
    code, schema = task.run('operation-schema', 'object.set')
    assert code == 0, schema
    def find(value):
        if isinstance(value, dict):
            if 'anonymous_list_member' in value: return value['anonymous_list_member']
            for nested in value.values():
                result = find(nested)
                if result is not None: return result
        if isinstance(value, list):
            for nested in value:
                result = find(nested)
                if result is not None: return result
    contract = find(schema)
    assert contract['omit'] == ['name']
    assert contract['versions'] == ['2023.1', '2024.1', '2025.1']
    task.bind(FIRST)
    code, found = task.step('draft-discover-types', '--role', 'object', '--meaning', 'EffectSlot')
    assert code == 0, found
    continuation = found['draft']['next_action_binding']['declare_new']['anonymous_list_member']
    assert '--name' not in continuation['append']
    assert '--kind' in continuation['append'] and 'object_list' in continuation['append']
    assert continuation['native_name'] == 'Gateway_owned_empty_string'
    assert continuation['local_plugin']['plugin_placement'] == 'owner'


def test_append_preserves_reference_identity_when_same_graph_renames_its_shareset(tmp_path):
    task = anonymous_task(tmp_path)
    for identity in [ROOT, CHILD]:
        task.objects[identity]['@Effect'] = {key: task.objects[EFFECT][key] for key in ['id', 'name', 'type', 'path']}
    declare_slots(task)
    target = task.bind(EFFECT)
    code, declared = task.step('draft-declare-existing', '--declaration-id', 'rename-effect', '--object-handle', target,
        '--field', 'new_name', 'Renamed ShareSet')
    assert code == 0, declared
    original, writes = task.call, []
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            writes.append(deepcopy(args))
            rows = {row['object']: row for row in args['objects']}
            assert rows[EFFECT] == {'object': EFFECT, 'name': 'Renamed ShareSet'}
            task.objects[EFFECT]['name'] = 'Renamed ShareSet'
            task.objects[EFFECT]['path'] = r'\Effects\Default Work Unit\Renamed ShareSet'
            for identity in [ROOT, CHILD]:
                task.objects[identity]['@Effect'] = {key: task.objects[EFFECT][key] for key in ['id', 'name', 'type', 'path']}
            for identity, source in zip([SLOT_A, SLOT_B], rows[FIRST]['@Effects'], strict=True):
                task.objects[identity] = {'id': identity, 'name': '', 'type': 'PluginInnerObject', 'classId': 5505040,
                    'owner': {'id': FIRST}, 'path': r'\Opaque new slot ' + identity, 'notes': '',
                    '@Effect': {'id': source['@Effect']}, '@Bypass': source['@Bypass'], '@Render': source['@Render']}
            task.objects[FIRST]['@Effects'] += [{'id': SLOT_A}, {'id': SLOT_B}]
            return {'objects': [{'id': FIRST, 'name': 'Sender', '@Effects': [{'id': SLOT_B, 'name': ''}, {'id': SLOT_A, 'name': ''}]}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified.get('verified') is True, json.dumps(verified)
    assert len(writes) == 1


@pytest.mark.parametrize('fault', [None, 'wrong-owner-label', 'wrong-owner-guid'])
def test_append_owner_label_follows_only_the_sealed_owner_rename(tmp_path, fault):
    task = anonymous_task(tmp_path)
    for identity in [ROOT, CHILD]:
        task.objects[identity]['owner'] = {'id': FIRST, 'name': 'Sender'}
    owner = declare_slots(task)
    code, declared = task.step('draft-declare-existing', '--declaration-id', 'rename-owner', '--object-handle', owner,
        '--field', 'new_name', 'Renamed owner')
    assert code == 0, declared
    original, writes = task.call, []
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            writes.append(deepcopy(args))
            row = args['objects'][0]
            assert row['name'] == 'Renamed owner'
            task.objects[FIRST]['name'] = row['name']
            task.objects[FIRST]['path'] = task.objects[FIRST]['path'].rsplit('\\', 1)[0] + '\\' + row['name']
            for identity in [ROOT, CHILD]:
                task.objects[identity]['owner'] = {'id': EFFECT_PARENT if fault == 'wrong-owner-guid' else FIRST,
                    'name': 'Wrong owner label' if fault == 'wrong-owner-label' else row['name']}
            for identity, source in zip([SLOT_A, SLOT_B], row['@Effects'], strict=True):
                task.objects[identity] = {'id': identity, 'name': '', 'type': 'PluginInnerObject', 'classId': 5505040,
                    'owner': {'id': FIRST, 'name': row['name']}, 'path': r'\Opaque new slot ' + identity, 'notes': '',
                    '@Effect': {'id': source['@Effect']}, '@Bypass': source['@Bypass'], '@Render': source['@Render']}
            task.objects[FIRST]['@Effects'] += [{'id': SLOT_A}, {'id': SLOT_B}]
            return {'objects': [{'id': FIRST, 'name': row['name'], '@Effects': [{'id': SLOT_B, 'name': ''}, {'id': SLOT_A, 'name': ''}]}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == (2 if fault else 0), json.dumps(verified)
    assert (verified.get('verified') is True) == (fault is None), verified
    assert len(writes) == 1


def test_anonymous_append_rejects_aggregate_population_beyond_complete_read_bound(tmp_path):
    task = anonymous_task(tmp_path)
    old = deepcopy(task.objects[ROOT])
    task.objects[FIRST]['@Effects'] = []
    for index in range(127):
        identity = '{%08X-0000-0000-0000-000000000000}' % (1000 + index)
        task.objects[identity] = {**deepcopy(old), 'id': identity, 'path': r'\Opaque old slot ' + identity}
        task.objects[FIRST]['@Effects'].append({'id': identity})
    declare_slots(task)
    code, checked = task.step('draft-check')
    assert code == 2 and 'LIST_SNAPSHOT_LIMIT_EXCEEDED' in json.dumps(checked), checked
    assert not any(uri.endswith('object.set') for uri, _, _ in task.calls)
