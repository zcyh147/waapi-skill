"""Planned legacy Playlist targets bind through the public owned-graph stages."""
from copy import deepcopy
import json

import pytest

from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, FIRST, SECOND, ROOT, CHILD

SET = 'ak.wwise.core.object.set'


def planned_playlist_task(tmp_path, version='2023.1', mode='replace-all', wrong_parent=False, compound=False):
    task = OwnedGraphTask(tmp_path, version, 'object.set')
    if compound:
        from tests.unit.test_compound_undo_business_gateway import _start_parent_owned_graph_child
        _start_parent_owned_graph_child(task, 'object.set')
    task.objects = {SECOND: {'id': SECOND, 'name': 'Default Work Unit', 'type': 'WorkUnit', 'classId': 1638416,
        'path': r'\Actor-Mixer Hierarchy\Default Work Unit', 'parent': None, 'notes': 'Keep parent'}}
    task.types = [{'classId': cid, 'name': name, 'type': 'WObject'} for cid, name in
        ((1638416, 'WorkUnit'), (589840, 'RandomSequenceContainer'), (65552, 'Sound'))]
    parent = task.bind(SECOND)
    kinds = {}
    for name in ('RandomSequenceContainer', 'Sound'):
        code, result = task.step('draft-discover-types', '--role', 'object', '--meaning', name)
        assert code == 0, result
        kinds[name] = result['type_candidates'][0]['handle']
    code, listed = task.step('draft-discover-fields', '--type-handle', kinds['RandomSequenceContainer'],
        '--field-source', 'documented-lists', '--list')
    choice = next(row for row in listed['agent_result']['items'] if row['name'] == 'Playlist')
    code, selected = task.step('draft-discover-fields', '--type-handle', kinds['RandomSequenceContainer'],
        '--field-source', 'documented-lists', '--selection', choice['selection'])
    assert code == 0, selected
    candidate = selected['meaning_results'][0]['candidates'][0]
    assert 'json_array_of_same_draft_result_handles' in candidate['value_input']['accepted_forms']
    field = candidate['handle']
    code, owner = task.step('draft-declare-new', '--declaration-id', 'owner', '--parent-handle', parent,
        '--name', 'Numbers', '--kind', kinds['RandomSequenceContainer'])
    assert code == 0, owner
    owner_handle = owner['draft']['declared_object']['result_handle']
    children = []
    for name in ('One', 'Two'):
        code, declared = task.step('draft-declare-new', '--declaration-id', name,
            '--parent-handle', parent if wrong_parent else owner_handle, '--name', name, '--kind', kinds['Sound'])
        assert code == 0, declared
        children.append(declared['draft']['declared_object']['result_handle'])
    assert task.step('draft-business-configure', '--list-behavior', mode)[0] == 0
    code, revised = task.step('draft-revise-declaration', '--declaration-id', 'owner', '--field-value', field,
        json.dumps([children[1], children[0], children[1]]))
    assert code == 0, revised
    task.handles = [owner_handle, *children]
    task.writes = []
    original = task.call
    def call(uri, args=None, options=None):
        if uri != SET:
            return original(uri, args, options)
        task.calls.append((uri, deepcopy(args), deepcopy(options)))
        task.writes.append(deepcopy(args))
        node, = args['objects']
        if 'children' in node:
            assert node['object'] == SECOND
            owner, = node['children']
            assert owner['name'] == 'Numbers' and '@Playlist' not in owner
            assert owner['children'] == [{'type': 'Sound', 'name': 'One'}, {'type': 'Sound', 'name': 'Two'}]
            path = task.objects[SECOND]['path'] + r'\Numbers'
            task.objects[FIRST] = {'id': FIRST, 'name': 'Numbers', 'type': 'RandomSequenceContainer', 'classId': 589840,
                'path': path, 'parent': {'id': SECOND}, 'notes': '', '@Playlist': [{'id': ROOT}]}
            for oid, name in ((ROOT, 'One'), (CHILD, 'Two')):
                task.objects[oid] = {'id': oid, 'name': name, 'type': 'Sound', 'classId': 65552,
                    'path': path + '\\' + name, 'parent': {'id': FIRST}, 'notes': 'Keep ' + name}
            return {'objects': [{'id': SECOND, 'name': 'Default Work Unit', 'children': [
                {'id': FIRST, 'name': 'Numbers', '@Playlist': [{}],
                    'children': [{'id': ROOT, 'name': 'One'}, {'id': CHILD, 'name': 'Two'}]}]}]}
        assert node['object'] == FIRST and node['@Playlist'] == [CHILD, ROOT, CHILD]
        assert node['listMode'] == ('replaceAll' if mode == 'replace-all' else 'append')
        prefix = task.objects[FIRST]['@Playlist'] if mode == 'append' else []
        task.objects[FIRST]['@Playlist'] = [*prefix, *({'id': oid} for oid in node['@Playlist'])]
        return {'objects': [{'id': FIRST, 'name': 'Numbers'}]}
    task.call = call
    return task


@pytest.mark.parametrize('version,mode', [('2023.1', 'replace-all'), ('2024.1', 'append')])
def test_planned_legacy_playlist_uses_verified_guids_and_observed_prefix(tmp_path, version, mode):
    task = planned_playlist_task(tmp_path, version, mode)
    assert task.step('draft-check')[0] == 0
    code, preview = task.step('preview-from-draft')
    assert code == 0, preview
    assert preview['preview_summary']['staged_reference_lists'][0]['constructor_roster'] == 'observed_after_creation_before_assignment'
    tx = preview['transaction_id']
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    expected = [CHILD, ROOT, CHILD] if mode == 'replace-all' else [ROOT, CHILD, ROOT, CHILD]
    assert task.objects[FIRST]['@Playlist'] == [{'id': oid} for oid in expected]
    assert task.objects[ROOT]['notes'] == 'Keep One' and task.objects[CHILD]['notes'] == 'Keep Two'
    assert len(task.writes) == 2 and not any(uri.endswith(('object.delete', 'setReference')) for uri, _, _ in task.calls)
    roster = verified['agent_result']['business_result']['created_objects']
    assert {row['result_handle'] for row in roster} == set(task.handles)
    code, full = task.run('transaction-show', tx)
    assert code == 0, full
    proof = next(event['details']['dispatch_result']['owned_result_execution'] for event in full['events']
        if event['event_type'] == 'execution_completed')
    observed, = proof['reference_lists']
    assert [row['id'] for row in observed['guard']['members']] == [ROOT]
    assert observed['expected_roster'] == expected
    assert task.run('execute', tx)[0] == 2 and len(task.writes) == 2


def test_planned_legacy_playlist_rejects_a_child_of_another_planned_parent(tmp_path):
    task = planned_playlist_task(tmp_path, wrong_parent=True)
    code, rejected = task.step('draft-check')
    assert code == 2 and rejected['error_code'] == 'INVALID_REFERENCE_TARGET', rejected
    assert 'direct child' in rejected['message'] and task.writes == []


@pytest.mark.parametrize('damage', ['partial-child-identity', 'target-parent-drift', 'owner-class-metadata-drift', 'changed-target-after-array'])
def test_planned_legacy_playlist_stops_after_unproved_or_drifting_creation(tmp_path, damage):
    task = planned_playlist_task(tmp_path)
    tx, shown = task.preview()
    original = task.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri == SET:
            if len(task.writes) == 1:
                if damage == 'partial-child-identity':
                    result['objects'][0]['children'][0]['children'].pop()
                elif damage == 'target-parent-drift':
                    task.objects[CHILD]['parent'] = {'id': SECOND}
                elif damage == 'owner-class-metadata-drift':
                    next(row for row in task.types if row['name'] == 'RandomSequenceContainer')['name'] = 'Changed class metadata'
            elif damage == 'changed-target-after-array':
                task.objects[ROOT]['notes'] = 'Unexpected target change'
        return result
    task.call = call
    assert task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    code, executed = task.run('execute', tx)
    if damage == 'changed-target-after-array':
        assert code == 0, executed
        code, rejected = task.run('verify', tx)
        assert code == 2 and rejected.get('verified') is not True, rejected
    else:
        assert code == 2 and executed.get('executed') is not True, executed
    assert len(task.writes) == (2 if damage == 'changed-target-after-array' else 1)
    assert ROOT in task.objects and CHILD in task.objects
    assert task.run('execute', tx)[0] == 2
    assert len(task.writes) == (2 if damage == 'changed-target-after-array' else 1)
