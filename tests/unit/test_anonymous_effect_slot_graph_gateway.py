"""Anonymous EffectSlot construction uses source placement and ordered membership."""
from copy import deepcopy
import json

import pytest

from tests.unit.test_list_merge_existing_conditions_gateway import list_task, select_field, EFFECT, EFFECT_PARENT
from tests.unit.test_object_graph_owned_choices_gateway import FIRST, SECOND, ROOT, CHILD

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


def declare_slots(task, *, owner=None, owner_kind=None, targets=None, renders=("false", "false"), bypasses=("true", "false")):
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
    for name, target, bypass, render in [('first', targets[0], bypasses[0], renders[0]), ('second', targets[1], bypasses[1], renders[1])]:
        handle = target if target.startswith('bnh1-') else task.bind(target)
        code, declared = task.step('draft-declare-new', '--declaration-id', name, '--parent-handle', owner,
            '--kind', kind, '--field', 'object_list', effects,
            '--field-value', fields['Effect'], handle, *(['--field-value', fields['Bypass'], bypass] if bypass is not None else []),
            *(['--field-value', fields['Render'], render] if render is not None else []))
        assert code == 0, declared
    return owner


@pytest.mark.parametrize('version,mode,fault', [
    ('2023.1', 'append', None), ('2024.1', 'replace-all', None),
    ('2025.1', 'append', None), ('2025.1', 'replace-all', None),
    ('2025.1', 'replace-all', 'nonlexicographic-guids'),
    *[('2025.1', 'append', fault) for fault in ['old-bypass', 'order', 'class', 'owner',
        'duplicate-return', 'old-return', 'spare-notes', 'target-notes', 'value']],
    *[('2025.1', 'replace-all', fault) for fault in ['order', 'old-return', 'retained-old-member']],
])
def test_two_anonymous_slots_bind_independent_membership_not_returned_order(tmp_path, version, mode, fault):
    new_a, new_b = (SLOT_B, SLOT_A) if fault == 'nonlexicographic-guids' else (SLOT_A, SLOT_B)
    expect_failure = fault is not None and fault != 'nonlexicographic-guids'
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
                {'type': 'EffectSlot', 'name': '', '@Bypass': False, '@Render': False, '@Effect': EFFECT_B}]}], args
            for identity, effect, bypass, render, path in [
                (new_a, EFFECT, True, False, r'\Opaque new slot A'),
                (new_b, EFFECT_B, False, False, r'\Opaque new slot B')]:
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
            task.objects[FIRST]['@Effects'] += [{'id': new_a}, {'id': new_b}]
            if fault == 'order':
                task.objects[FIRST]['@Effects'][-2:] = [{'id': new_b}, {'id': new_a}]
            if fault == 'class': task.objects[new_a]['classId'] = 5570560
            if fault == 'owner': task.objects[new_a]['owner'] = {'id': EFFECT_PARENT}
            if fault == 'value': task.objects[new_a]['@Bypass'] = False
            if fault == 'spare-notes': task.objects[CHILD]['notes'] = 'Reset'
            if fault == 'target-notes': task.objects[EFFECT_B]['notes'] = 'Reset'
            if fault == 'old-bypass':
                task.objects[ROOT]['@Bypass'] = True
            # Returned associations are explicitly reversed. Their order cannot
            # identify declarations; independent owner Effects order can.
            return {'objects': [{'id': FIRST, 'name': 'Sender', '@Effects': [
                {'id': new_a if fault == 'duplicate-return' else ROOT if fault == 'old-return' else new_b, 'name': ''},
                {'id': new_a, 'name': ''}]}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == (2 if expect_failure else 0), json.dumps(verified)
    assert (verified.get('verified') is True) == (not expect_failure), verified
    assert len(writes) == 1
    if expect_failure:
        return
    expected = [new_a, new_b] if mode == 'replace-all' else [ROOT, CHILD, new_a, new_b]
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


@pytest.mark.parametrize("parent_kind,fault", [
    ("WorkUnit", None), ("WorkUnit", "wrong-reference"),
    *[("Folder", fault) for fault in [None, "wrong-reference", "folder-class-drift",
        "folder-catalog-drift", "folder-ancestor-notes", "folder-ancestor-owner", "folder-parent"]],
])
def test_anonymous_slot_references_same_graph_new_independent_shareset(tmp_path, fault, parent_kind):
    task = anonymous_task(tmp_path)
    parent_id = EFFECT_PARENT
    if parent_kind == "Folder":
        parent_id = '{ABABABAB-ABAB-ABAB-ABAB-ABABABABABAB}'
        task.types.append({'name': 'Folder', 'classId': 131088, 'type': 'WObject'})
        ancestor = '{CFCFCFCF-CFCF-CFCF-CFCF-CFCFCFCFCFCF}'
        task.objects[ancestor] = {'id': ancestor, 'name': 'Library', 'type': 'Folder',
            'classId': 131088, 'path': task.objects[EFFECT_PARENT]['path'] + r'\Library',
            'parent': {'id': EFFECT_PARENT}, 'notes': 'Keep independent ancestor'}
        task.objects[parent_id] = {'id': parent_id, 'name': 'ShareSets', 'type': 'Folder',
            'classId': 131088, 'path': task.objects[ancestor]['path'] + r'\ShareSets',
            'parent': {'id': ancestor}, 'notes': 'Keep Folder'}
    new_path = task.objects[parent_id]['path'] + r'\New ShareSet'
    parent = task.bind(parent_id)
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
    assert native['objects'][0] == {'object': parent_id, 'children': [
        {'type': 'Effect', 'name': 'New ShareSet', 'classId': 8454147}]}
    assert native['objects'][1]['object'] == FIRST
    assert native['objects'][1]['@Effects'][0]['@Effect'] == new_path

    new_effect = '{CDCDCDCD-CDCD-CDCD-CDCD-CDCDCDCDCDCD}'
    original, writes = task.call, []
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            writes.append(deepcopy(args))
            assert args == native
            task.objects[new_effect] = {'id': new_effect, 'name': 'New ShareSet', 'type': 'Effect',
                'classId': 8454147, 'path': new_path,
                'parent': {'id': parent_id}, 'notes': ''}
            for identity, effect, bypass, render in [(SLOT_A, new_effect, True, False), (SLOT_B, EFFECT_B, False, False)]:
                task.objects[identity] = {'id': identity, 'name': '', 'type': 'PluginInnerObject',
                    'classId': 5505040, 'path': r'\Opaque ' + identity, 'owner': {'id': FIRST}, 'notes': '',
                    '@Effect': {'id': EFFECT if fault == 'wrong-reference' else effect}, '@Bypass': bypass, '@Render': render}
            task.objects[FIRST]['@Effects'] += [{'id': SLOT_A}, {'id': SLOT_B}]
            if fault == 'folder-ancestor-notes': task.objects[ancestor]['notes'] = 'Unexpected reset'
            if fault == 'folder-ancestor-owner': task.objects[ancestor]['owner'] = {'id': FIRST}
            if fault == 'folder-parent': task.objects[parent_id]['parent'] = {'id': EFFECT_PARENT}
            return {'objects': [
                {'id': FIRST, 'name': 'Sender', '@Effects': [{'id': SLOT_B, 'name': ''}, {'id': SLOT_A, 'name': ''}]},
                {'id': parent_id, 'name': task.objects[parent_id]['name'], 'children': [{'id': new_effect, 'name': 'New ShareSet'}]}]}
        return original(uri, args, options)
    task.call = call
    if fault in {'folder-class-drift', 'folder-catalog-drift'}:
        if fault == 'folder-class-drift': task.objects[ancestor]['classId'] = 1638416
        else: task.types[-1]['type'] = 'DifferentBaseClass'
        code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
        assert code == 0, confirmed
        code, rejected = task.run('execute', tx)
        assert code == 2 and rejected.get('executed') is not True, rejected
        assert not writes
        return
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
    assert contract['on_name_conflict']['supported'] == ['fail']
    assert contract['on_name_conflict']['pending_source_native_proof'] == ['rename', 'merge', 'replace']
    task.bind(FIRST)
    code, found = task.step('draft-discover-types', '--role', 'object', '--meaning', 'EffectSlot')
    assert code == 0, found
    continuation = found['draft']['next_action_binding']['declare_new']['anonymous_list_member']
    assert '--name' not in continuation['append']
    assert '--kind' in continuation['append'] and 'object_list' in continuation['append']
    assert continuation['native_name'] == 'Gateway_owned_empty_string'
    assert continuation['semantics']['on_name_conflict'] == contract['on_name_conflict']
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


@pytest.mark.parametrize('conflict', ['rename', 'merge', 'replace'])
def test_anonymous_nondefault_conflict_policy_is_explicitly_pending_before_dispatch(tmp_path, conflict):
    task = anonymous_task(tmp_path)
    declare_slots(task)
    code, configured = task.step('draft-business-configure', '--name-conflict', conflict)
    assert code == 0, configured
    code, checked = task.step('draft-check')
    assert code == 2 and 'ANONYMOUS_LIST_CONFLICT_UNRESOLVED' in json.dumps(checked), checked
    assert not any(uri.endswith('object.set') for uri, _, _ in task.calls)


def test_explicit_render_false_before_later_true_is_rejected_before_any_write(tmp_path):
    task = anonymous_task(tmp_path)
    # Literal nativee2 request: first(Bypasstrue,Renderfalse), then
    # second(Bypassfalse,Rendertrue). Native silently forces first Rendertrue.
    declare_slots(task, renders=("false", "true"))
    code, checked = task.step('draft-check')
    assert code == 2 and checked['error_code'] == 'EFFECT_RENDER_CHAIN_CONFLICT', checked
    assert not any(uri.endswith(('object.set', 'setProperty', 'object.create')) for uri, _, _ in task.calls)


def test_omitted_new_predecessor_render_is_derived_in_preview(tmp_path):
    task = anonymous_task(tmp_path)
    declare_slots(task, renders=(None, 'true'))
    code, configured = task.step('draft-business-configure', '--list-behavior', 'replace-all')
    assert code == 0, configured
    _, shown = task.preview()
    prepared = shown['artifact']['prepared_operation']
    slots = prepared['dispatch']['args']['objects'][0]['@Effects']
    assert slots[0]['@Render'] is True
    assert slots[0]['@Bypass'] is True  # Bypass precedence never rewrites stored intent.
    chain = prepared['pre_state']['effect_render_chains'][0]
    assert chain['derived'][0]['after'] is True
    assert 'Bypass takes precedence' in chain['bypass_policy']


@pytest.mark.parametrize('version,fault', [('2025.1', fault) for fault in [None, 'ignored-derived', 'metadata-drift', 'member-drift']] + [('2023.1', None), ('2024.1', None)])
def test_render_prefix_append_verifies_derived_old_and_new_predecessors(tmp_path, version, fault):
    task = anonymous_task(tmp_path, version)
    declare_slots(task, renders=(None, 'true'))
    original, writes = task.call, []
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            writes.append(deepcopy(args))
            slots = args['objects'][0]['@Effects']
            assert slots[0]['@Render'] is True and slots[1]['@Render'] is True
            for identity, source in zip([SLOT_A, SLOT_B], slots):
                task.objects[identity] = {'id': identity, 'name': '', 'type': 'PluginInnerObject',
                    'classId': 5505040, 'owner': {'id': FIRST}, 'path': r'\Opaque ' + identity,
                    'notes': '', '@Effect': {'id': source['@Effect']}, '@Bypass': source['@Bypass'], '@Render': source['@Render']}
            for identity in [ROOT, CHILD]:
                task.objects[identity]['@Render'] = fault != 'ignored-derived'
            task.objects[FIRST]['@Effects'] += [{'id': SLOT_A}, {'id': SLOT_B}]
            return {'objects': [{'id': FIRST, 'name': 'Sender', '@Effects': [{'id': SLOT_A, 'name': ''}, {'id': SLOT_B, 'name': ''}]}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    chain = shown['artifact']['prepared_operation']['pre_state']['effect_render_chains'][0]
    assert [row['key'] for row in chain['derived']] == [ROOT, CHILD, '$.objects[0].lists[0].objects[0]']
    if fault in {'metadata-drift', 'member-drift'}:
        if fault == 'metadata-drift': task.metadata['Render']['default'] = True
        else: task.objects[FIRST]['@Effects'].reverse()
        code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
        assert code == 0, confirmed
        code, failed = task.run('execute', tx)
        assert code == 2 and writes == [], failed
    else:
        code, verified = task.finish(tx, shown)
        assert (code == 0 and verified.get('verified') is True) == (fault is None), verified
        assert len(writes) == 1
        assert task.objects[SLOT_A]['@Bypass'] is True and task.objects[SLOT_B]['@Bypass'] is False


@pytest.mark.parametrize('operation', ['object.setProperty', 'object.set'])
def test_exact_existing_slot_render_uses_same_chain_preview_and_readback(tmp_path, operation):
    task, _ = list_task(tmp_path, operation=operation)
    prior = task.call
    def enabled(uri, args=None, options=None):
        if uri.endswith('isPropertyEnabled'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': True}
        return prior(uri, args, options)
    task.call = enabled
    target = task.bind(CHILD)
    render = select_field(task, owner=target, token='Render')
    if operation == 'object.setProperty':
        code, declared = task.step('draft-declare-field-change', '--object-handle', target,
            '--field-handle', render, '--business-value', 'true')
    else:
        code, declared = task.step('draft-declare-existing', '--declaration-id', 'slot', '--object-handle', target,
            '--field-value', render, 'true')
    assert code == 0, declared
    original, writes = task.call, []
    def call(uri, args=None, options=None):
        if uri.endswith(('object.set', 'object.setProperty')):
            writes.append(deepcopy(args))
            task.objects[ROOT]['@Render'] = task.objects[CHILD]['@Render'] = True
            return {'objects': [{'id': CHILD, 'name': 'Spare'}]} if operation == 'object.set' else {}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    chain = shown['artifact']['prepared_operation']['pre_state']['effect_render_chains'][0]
    assert chain['derived'] == [{'key': ROOT, 'before': False, 'after': True}]
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert len(writes) == 1
    if operation == 'object.setProperty':
        code, started = task.run('draft-start', 'ak.wwise.core.undo.undo')
        assert code == 0, started
        history = started['draft']
        code, rejected = task.run('draft-declare-core-plan', history['draft_id'],
            '--task-authority', started['task_authority'], '--expected-revision', str(history['revision']),
            '--value', 'history_scope', 'latest_project_history', '--value', 'expectation_receipt', tx)
        assert code == 2 and 'Render chain' in json.dumps(rejected), rejected
        assert not any(uri.endswith('undo.undo') for uri, _, _ in task.calls)


@pytest.mark.parametrize('version,operation', [('2021.1', 'object.setProperty'), ('2022.1', 'object.setProperty'), ('2022.1', 'object.set')])
def test_legacy_render_chain_uses_same_prefix_plan_without_changing_bypass(tmp_path, version, operation):
    task, _ = list_task(tmp_path, version=version, operation=operation)
    del task.objects[ROOT], task.objects[CHILD], task.objects[FIRST]['@Effects']
    task.types = [row for row in task.types if row['name'] != 'EffectSlot']
    task.metadata = {}
    reference_dependency = lambda i: {'type': 'reference', 'action': 'Enable', 'context': 'Self',
        'property': 'Effect' + str(i), 'conditions': [{'referenceIsSet': True}]}
    for i in range(4):
        task.objects[FIRST].update({f'@Effect{i}': {'id': EFFECT}, f'@RenderEffect{i}': False, f'@BypassEffect{i}': i == 0})
        task.metadata[f'Effect{i}'] = {'name': f'Effect{i}', 'type': '', 'default': None,
            'restriction': {'type': 'reference', 'restrictions': [{'type': ['Effect']}]}}
        for prefix in ('Bypass', 'Render'):
            task.metadata[f'{prefix}Effect{i}'] = {'name': f'{prefix}Effect{i}', 'type': 'bool', 'default': False,
                'dependencies': [reference_dependency(i)]}
    original, writes = task.call, []
    def call(uri, args=None, options=None):
        if uri.endswith('isPropertyEnabled'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': True}
        if uri.endswith(('object.set', 'object.setProperty')):
            writes.append(deepcopy(args))
            if operation == 'object.set':
                assert args['objects'] == [{'object': FIRST, '@RenderEffect1': True, '@RenderEffect0': True}]
            else:
                assert args == {'object': FIRST, 'property': 'RenderEffect1', 'value': True}
            task.objects[FIRST]['@RenderEffect0'] = task.objects[FIRST]['@RenderEffect1'] = True
            return {'objects': [{'id': FIRST, 'name': 'Sender'}]} if operation == 'object.set' else {}
        return original(uri, args, options)
    task.call = call
    target = task.bind(FIRST)
    render = select_field(task, owner=target, token='RenderEffect1')
    if operation == 'object.set':
        code, declared = task.step('draft-declare-existing', '--declaration-id', 'sound', '--object-handle', target,
            '--field-value', render, 'true')
    else:
        code, declared = task.step('draft-declare-field-change', '--object-handle', target,
            '--field-handle', render, '--business-value', 'true')
    assert code == 0, declared
    before = deepcopy(task.objects)
    tx, shown = task.preview()
    chain = shown['artifact']['prepared_operation']['pre_state']['effect_render_chains'][0]
    assert chain['derived'] == [{'key': 'RenderEffect0', 'before': False, 'after': True}]
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert task.objects[FIRST] == {**before[FIRST], '@RenderEffect0': True, '@RenderEffect1': True}
    assert len(writes) == 1


def test_render_replace_all_keeps_new_metadata_after_deleting_old_slots(tmp_path):
    task = anonymous_task(tmp_path)
    declare_slots(task, renders=('true', 'false'))
    code, configured = task.step('draft-business-configure', '--list-behavior', 'replace-all')
    assert code == 0, configured
    original, writes = task.call, []
    def call(uri, args=None, options=None):
        if uri.endswith('getPropertyInfo') and args.get('object') in (ROOT, CHILD):
            assert args['object'] in task.objects, 'deleted old slot metadata must not be queried after replaceAll'
        if uri.endswith('object.set'):
            writes.append(deepcopy(args))
            slots = args['objects'][0]['@Effects']
            assert args['listMode'] == 'replaceAll'
            for identity in (ROOT, CHILD): del task.objects[identity]
            task.objects[FIRST]['@Effects'] = [{'id': SLOT_A}, {'id': SLOT_B}]
            for identity, node in zip((SLOT_A, SLOT_B), slots):
                task.objects[identity] = {'id': identity, 'name': '', 'type': 'PluginInnerObject', 'classId': 5505040,
                    'owner': {'id': FIRST}, 'path': r'\Opaque ' + identity, 'notes': '', '@Effect': {'id': node['@Effect']},
                    '@Bypass': node['@Bypass'], '@Render': node['@Render']}
            return {'objects': [{'id': FIRST, 'name': 'Sender', '@Effects': [{'id': SLOT_B, 'name': ''}, {'id': SLOT_A, 'name': ''}]}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    assert any(field['scope'].get('object_id') == ROOT for field in shown['artifact']['prepared_operation']['pre_state']['effect_render_chains'][0]['metadata'])
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert len(writes) == 1 and ROOT not in task.objects and CHILD not in task.objects


def test_separate_existing_rows_cannot_hide_explicit_render_contradiction(tmp_path):
    task, _ = list_task(tmp_path, operation='object.set')
    prior = task.call
    def enabled(uri, args=None, options=None):
        if uri.endswith('isPropertyEnabled'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': True}
        return prior(uri, args, options)
    task.call = enabled
    for declaration, identity, value in [('earlier', ROOT, 'false'), ('later', CHILD, 'true')]:
        target = task.bind(identity)
        render = select_field(task, owner=target, token='Render')
        code, declared = task.step('draft-declare-existing', '--declaration-id', declaration,
            '--object-handle', target, '--field-value', render, value)
        assert code == 0, declared
    code, failed = task.step('draft-check')
    assert code == 2 and failed['error_code'] == 'EFFECT_RENDER_CHAIN_CONFLICT', failed
    assert not any(uri.endswith(('object.set', 'object.setProperty')) for uri, _, _ in task.calls)


def test_render_clear_before_retained_true_successor_is_explicit_pending_boundary(tmp_path):
    task, _ = list_task(tmp_path, version='2023.1', operation='object.setProperty')
    task.objects[ROOT]['@Render'] = task.objects[CHILD]['@Render'] = True
    original = task.call
    def call(uri, args=None, options=None):
        if uri.endswith('isPropertyEnabled'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': True}
        return original(uri, args, options)
    task.call = call
    target = task.bind(ROOT)
    render = select_field(task, owner=target, token='Render')
    code, declared = task.step('draft-declare-field-change', '--object-handle', target,
        '--field-handle', render, '--business-value', 'false')
    assert code == 0, declared
    code, rejected = task.step('draft-check')
    assert code == 2 and rejected['error_code'] == 'EFFECT_RENDER_SUFFIX_OBSERVATION_REQUIRED', rejected
    assert rejected['details']['mutation_dispatched'] is False
    assert not any(uri.endswith('object.setProperty') for uri, _, _ in task.calls)


@pytest.mark.parametrize('wrong_default', [False, True])
def test_omitted_bypass_default_is_independently_verified_without_native_rewrite(tmp_path, wrong_default):
    task = anonymous_task(tmp_path)
    declare_slots(task, renders=('true', 'false'), bypasses=(None, None))
    code, configured = task.step('draft-business-configure', '--list-behavior', 'replace-all')
    assert code == 0, configured
    original = task.call
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            slots = args['objects'][0]['@Effects']
            assert all('@Bypass' not in node for node in slots), args
            for identity in (ROOT, CHILD): del task.objects[identity]
            task.objects[FIRST]['@Effects'] = [{'id': SLOT_A}, {'id': SLOT_B}]
            for identity, node in zip((SLOT_A, SLOT_B), slots):
                task.objects[identity] = {'id': identity, 'name': '', 'type': 'PluginInnerObject', 'classId': 5505040,
                    'owner': {'id': FIRST}, 'path': r'\Opaque ' + identity, 'notes': '', '@Effect': {'id': node['@Effect']},
                    '@Bypass': wrong_default, '@Render': node['@Render']}
            return {'objects': [{'id': FIRST, 'name': 'Sender', '@Effects': [{'id': SLOT_A, 'name': ''}, {'id': SLOT_B, 'name': ''}]}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    specs = shown['artifact']['prepared_operation']['verification_plan']['nodes']
    default = next(prop for node in specs for prop in node['properties'] if prop['name'] == 'Bypass')
    assert default['observed_class_default'] is True and default['value'] is False
    code, verified = task.finish(tx, shown)
    assert (code == 0 and verified.get('verified') is True) == (not wrong_default), verified


def test_legacy_import_owner_render_fields_are_explicit_unfinished_chain_boundary(tmp_path):
    import wave
    task, _ = list_task(tmp_path, version='2022.1', operation='audio.import')
    task.metadata['IsVoice'] = {'name': 'IsVoice', 'type': 'bool', 'default': False}
    task.metadata['RenderEffect0'] = {'name': 'RenderEffect0', 'type': 'bool', 'default': False,
        'dependencies': [{'type': 'reference', 'action': 'Enable', 'context': 'Self', 'property': 'Effect0',
            'conditions': [{'referenceIsSet': True}]}]}
    task.metadata['Effect0'] = {'name': 'Effect0', 'type': '', 'default': None,
        'restriction': {'type': 'reference', 'restrictions': [{'type': ['Effect']}]}}
    task.objects[FIRST].update({'@IsVoice': False, '@RenderEffect0': False, '@Effect0': {'id': EFFECT}})
    prior = task.call
    def enabled(uri, args=None, options=None):
        if uri.endswith('isPropertyEnabled'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': True}
        return prior(uri, args, options)
    task.call = enabled
    target = task.bind(FIRST)
    code, found = task.step('draft-discover-fields', '--object-handle', target, '--meaning', 'RenderEffect0')
    assert code == 0, found
    field = found['meaning_results'][0]['candidates'][0]['handle']
    media = tmp_path / 'render-input.wav'
    with wave.open(str(media), 'wb') as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(48000); output.writeframes(b'\0\0' * 8)
    code, declared = task.step('draft-declare-existing', '--declaration-id', 'sound', '--object-handle', target, '--field', 'media_file', str(media), '--field-value', field, 'true')
    assert code == 0, declared
    code, rejected = task.step('draft-check')
    assert code == 2 and rejected['error_code'] == 'EFFECT_RENDER_IMPORT_CHAIN_PENDING', rejected
    assert rejected['details']['mutation_dispatched'] is False
    assert 'audio.importTabDelimited' in rejected['details']['remaining_obligation']
    assert not any(uri.endswith('audio.import') for uri, _, _ in task.calls)


@pytest.mark.parametrize('operation', ['object.setProperty', 'object.set'])
def test_render_clear_previews_and_verifies_observed_suffix_without_changing_bypass(tmp_path, operation):
    task, _ = list_task(tmp_path, operation=operation)
    task.objects[ROOT]['@Render'] = task.objects[CHILD]['@Render'] = True
    original, writes = task.call, []
    def call(uri, args=None, options=None):
        if uri.endswith('isPropertyEnabled'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': True}
        if uri.endswith(('object.set', 'object.setProperty')):
            writes.append(deepcopy(args))
            if operation == 'object.setProperty':
                assert args == {'object': ROOT, 'property': 'Render', 'value': False}
            else:
                assert args['objects'] == [{'object': ROOT, '@Render': False}]
            task.objects[ROOT]['@Render'] = task.objects[CHILD]['@Render'] = False
            return {'objects': [{'id': ROOT, 'name': task.objects[ROOT]['name']}]} if operation == 'object.set' else {}
        return original(uri, args, options)
    task.call = call
    before = deepcopy(task.objects)
    target = task.bind(ROOT)
    render = select_field(task, owner=target, token='Render')
    if operation == 'object.setProperty':
        code, declared = task.step('draft-declare-field-change', '--object-handle', target,
            '--field-handle', render, '--business-value', 'false')
    else:
        code, declared = task.step('draft-declare-existing', '--declaration-id', 'slot', '--object-handle', target,
            '--field-value', render, 'false')
    assert code == 0, declared
    tx, shown = task.preview()
    chain = shown['artifact']['prepared_operation']['pre_state']['effect_render_chains'][0]
    assert chain['derived'] == [{'key': CHILD, 'before': True, 'after': False}]
    assert chain['suffix_rule']['rule'] == 'clearing a Render flag clears all subsequent stored Render flags'
    assert chain['suffix_rule']['version'] == '2025.1'
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert task.objects == {**before, ROOT: {**before[ROOT], '@Render': False}, CHILD: {**before[CHILD], '@Render': False}}
    assert len(writes) == 1
