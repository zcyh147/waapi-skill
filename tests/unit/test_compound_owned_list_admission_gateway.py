"""Supported source Lists compose into native groups without new history observers."""
from copy import deepcopy
import json

import pytest

from tests.unit.test_owned_named_list_stages_gateway import (
    named_list_task, BUS, SOUND, SLOT, METADATA, SET, FIRST, OLD_SLOT, ROOT,
)


def group_list_task(tmp_path, *, companion=None, creation_first=True, task_factory=named_list_task, **kwargs):
    task = task_factory(tmp_path, compound=True, **kwargs)
    if companion and companion[0] == 'object.setReference':
        task.objects[companion[1]]['@OutputBus'] = {'id': companion[2]}
    assert task.step('draft-check')[0] == 0
    children = [task.draft, task.authority]
    if companion:
        operation, object_id, value = companion
        parent, authority, revision = task.compound_parent
        code, started = task.run('draft-start-undo-child', parent, '--task-authority', authority,
            '--expected-revision', str(revision), '--operation', operation)
        assert code == 0, started
        task.draft, task.authority, task.revision = started['draft']['draft_id'], started['task_authority'], started['draft']['revision']
        owner = task.bind(object_id)
        if operation == 'object.setReference':
            target = task.bind(value)
            code, field = task.step('draft-discover-fields', '--object-handle', owner, '--meaning', 'OutputBus')
            assert code == 0, field
            handle = field['meaning_results'][0]['candidates'][0]['handle']
            code, declared = task.step('draft-declare-field-change', '--object-handle', owner,
                '--field-handle', handle, '--target-handle', target)
            assert code == 0, declared
        else:
            assert task.step('draft-declare-object-change', '--new-name' if operation == 'object.setName' else '--notes', value)[0] == 0
        code, checked = task.step('draft-check')
        assert code == 0, checked
        children.extend([task.draft, task.authority])
        if not creation_first:
            children = children[2:] + children[:2]
    task.draft, task.authority, task.revision = task.compound_parent
    code, declared = task.step('draft-declare-undo-plan', '--display-name', 'Metadata routing',
        *[token for index in range(0, len(children), 2) for token in ('--child-draft', *children[index:index + 2])])
    assert code == 0, declared
    original = task.call
    task.group_open = False
    task.group_connections = []
    def call(uri, args=None, options=None):
        if uri.startswith('ak.wwise.core.undo.'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            if uri.endswith('beginGroup'):
                assert not task.group_open
                task.group_open = True
            elif uri.endswith(('endGroup', 'cancelGroup')):
                assert task.group_open
                task.group_open = False
            return {}
        if uri == 'ak.wwise.core.object.setName':
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            owner = task.objects[args['object']]
            old = owner['path']
            owner.update(name=args['value'], path=old.rsplit('\\', 1)[0] + '\\' + args['value'])
            for row in task.objects.values():
                if row['id'] != owner['id'] and row['path'].startswith(old + '\\'):
                    row['path'] = owner['path'] + row['path'][len(old):]
            return {}
        if task.group_open:
            task.group_connections.append(id(task))
        return original(uri, args, options)
    task.call = call
    def disconnect():
        assert not task.group_open, 'Native group crossed connection lifetime'
    task.disconnect = disconnect
    return task


@pytest.mark.parametrize('owner_kind', [('Sound', 65552), ('PropertyContainer', 524304)])
def test_parent_group_admits_and_verifies_existing_owned_list_source(tmp_path, owner_kind):
    task = group_list_task(tmp_path, new_owner_kind=owner_kind)
    before = deepcopy(task.objects)
    tx, shown = task.preview()
    assert any('Undo/redo restoration' in warning for warning in shown['artifact']['prepared_operation']['warnings'])
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert verified['verification']['business_state_verified'] is True
    assert verified['verification']['verification_strength'] == 'compound_child_readback'
    assert all(task.objects[oid] == row for oid, row in before.items())
    assert task.objects[SOUND]['@Metadata'] == [{'id': SLOT}]
    assert task.objects[SLOT]['owner'] == {'id': SOUND}
    assert task.objects[SLOT]['@Metadata'] == {'id': METADATA}
    assert task.objects[SOUND]['@OutputBus'] == {'id': BUS}
    writes = [(uri, args) for uri, args, _ in task.calls if uri == SET or uri.startswith('ak.wwise.core.undo.')]
    assert [uri for uri, _ in writes] == ['ak.wwise.core.undo.beginGroup', SET, SET, SET, 'ak.wwise.core.undo.endGroup']
    assert writes[0][1] == {} and writes[-1][1] == {'displayName': 'Metadata routing'}
    assert task.group_connections and set(task.group_connections) == {id(task)}
    assert not task.group_open
    assert task.run('execute', tx)[0] == 2
    assert len(task.writes) == 3
    if owner_kind[0] == 'Sound':
        from tests.unit.test_compound_undo_business_gateway import _reject_created_graph_receipt
        rejected = _reject_created_graph_receipt(task, tx)
        assert 'ordinary hierarchy observation' in rejected['message']


@pytest.mark.parametrize('fault', ['wrong-owner', 'wrong-metadata-target'])
def test_group_list_failed_owned_proof_cancels_without_dependent_write_or_retry(tmp_path, fault):
    task = group_list_task(tmp_path, fault=fault)
    tx, shown = task.preview()
    assert task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    code, failed = task.run('execute', tx)
    assert code == 2 and failed['verified'] is False and failed['automatic_retry'] is False, failed
    assert failed.get('rollback_verified', False) is False
    assert len(task.writes) == 2 and '@OutputBus' not in task.objects[SOUND]
    native = [uri for uri, _, _ in task.calls if uri.startswith('ak.wwise.core.undo.')]
    assert native == ['ak.wwise.core.undo.beginGroup', 'ak.wwise.core.undo.cancelGroup']
    assert task.run('execute', tx)[0] == 2 and len(task.writes) == 2
    assert not task.group_open


def test_group_list_prewrite_retained_parent_drift_stops_before_group_begin(tmp_path):
    from tests.unit.test_object_graph_owned_choices_gateway import SECOND
    task = group_list_task(tmp_path)
    tx, shown = task.preview()
    assert task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    task.objects[SECOND]['name'] = 'Later parent'
    code, rejected = task.run('execute', tx)
    assert code == 2 and rejected.get('executed') is not True, rejected
    assert task.writes == []
    assert not any(uri.startswith('ak.wwise.core.undo.') for uri, _, _ in task.calls)


def test_group_list_retained_parent_overlap_stops_before_group_begin(tmp_path):
    from tests.unit.test_object_graph_owned_choices_gateway import SECOND
    task = group_list_task(tmp_path, companion=('object.setNotes', SECOND, 'Conflicting notes'))
    code, rejected = task.step('draft-check')
    assert code == 2 and rejected['error_code'] == 'UNDO_GROUP_OVERLAPPING_OUTCOME', rejected
    assert task.writes == [] and not task.group_open


def test_group_list_ancestor_rename_keeps_actual_source_owner_and_member_identity(tmp_path):
    from tests.unit.test_object_graph_owned_choices_gateway import SECOND
    task = group_list_task(tmp_path, companion=('object.setName', SECOND, 'Renamed parent'))
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert task.objects[SOUND]['path'].endswith('\\Renamed parent\\Sender')
    assert task.objects[SLOT]['owner'] == {'id': SOUND}
    assert task.objects[SLOT]['path'] == '\\opaque-slot-path'


@pytest.mark.parametrize('damage', ['missing-stage', 'foreign-stage'])
def test_group_list_verification_rejects_incomplete_or_foreign_actual_stage(tmp_path, damage):
    from wwise_waapi.canonical import canonical_json_bytes, canonical_sha256
    task = group_list_task(tmp_path)
    tx, shown = task.preview()
    assert task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    assert task.run('execute', tx)[0] == 0
    code, full = task.run('transaction-show', tx)
    assert code == 0, full
    events = full['events']
    execution = next(event['details']['dispatch_result'] for event in events if event['event_type'] == 'execution_completed')
    child = execution['result']['phases'][1]['dispatch_result']
    stages = child['owned_result_execution']['stages']
    if damage == 'missing-stage':
        stages.pop()
    else:
        stages[1]['args']['objects'][0]['object'] = METADATA
    previous = ''
    for event in events:
        event['previous_event_hash'] = previous
        event.pop('event_hash')
        event['event_hash'] = previous = canonical_sha256(event)
    directory = task.path / 'state' / 'transactions' / tx
    (directory / 'events.jsonl').write_bytes(b''.join(canonical_json_bytes(event) + b'\n' for event in events))
    state_path = directory / 'state.json'
    state = json.loads(state_path.read_text())
    state['last_event_hash'] = previous
    state_path.write_bytes(canonical_json_bytes(state))
    code, failed = task.run('verify', tx)
    assert code == 2 and failed.get('verified') is not True, failed
    assert task.run('execute', tx)[0] == 2 and len(task.writes) == 3


@pytest.mark.parametrize('owner_kind', [('Sound', 65552), ('PropertyContainer', 524304)])
def test_group_list_retained_owner_append_verifies_source_and_retains_prefix(tmp_path, owner_kind):
    task = group_list_task(tmp_path, retained=True, retained_kind=owner_kind)
    before = deepcopy(task.objects)
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert verified['verification']['business_state_verified'] is True
    assert task.objects[FIRST]['@Metadata'] == [{'id': OLD_SLOT}, {'id': SLOT}]
    assert task.objects[FIRST]['@OutputBus'] == {'id': BUS}
    assert task.objects[SLOT]['owner'] == {'id': FIRST}
    assert task.objects[SLOT]['@Metadata'] == {'id': METADATA}
    assert all(task.objects[oid] == row for oid, row in before.items() if oid != FIRST)
    assert task.objects[FIRST]['notes'] == before[FIRST]['notes']
    assert len(task.writes) == 3 and not task.group_open
    assert task.run('execute', tx)[0] == 2 and len(task.writes) == 3


@pytest.mark.parametrize('companion', [('object.setReference', FIRST, ROOT),
    ('object.setNotes', OLD_SLOT, 'Changed prefix')])
def test_retained_list_source_rejects_conflicting_reference_or_prefix_before_begin(tmp_path, companion):
    task = group_list_task(tmp_path, retained=True, companion=companion)
    code, rejected = task.step('draft-check')
    assert code == 2 and rejected['error_code'] == 'UNDO_GROUP_OVERLAPPING_OUTCOME', rejected
    assert task.writes == [] and not task.group_open


def test_group_list_retained_owner_nonempty_replacement_verifies_each_fragment(tmp_path):
    from tests.unit.test_owned_named_list_stages_gateway import SECOND_SLOT
    task = group_list_task(tmp_path, retained=True, replace_existing_two=True)
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert task.objects[FIRST]['@Metadata'] == [{'id': SLOT}, {'id': SECOND_SLOT}]
    assert OLD_SLOT not in task.objects
    assert task.objects[FIRST]['@OutputBus'] == {'id': BUS}
    assert all(task.objects[oid]['owner'] == {'id': FIRST} for oid in (SLOT, SECOND_SLOT))
    assert len(task.writes) == 4
    first, second = task.writes[1:3]
    assert first['objects'][0].get('listMode', first['listMode']) == 'replaceAll'
    assert second['objects'][0]['listMode'] == 'append'
    assert task.run('execute', tx)[0] == 2 and len(task.writes) == 4


@pytest.mark.parametrize('replace_list', [False, True])
def test_group_list_merge_owner_preserves_original_guid_and_complete_source(tmp_path, replace_list):
    from tests.unit.test_owned_named_list_stages_gateway import SECOND_SLOT
    task = group_list_task(tmp_path, multiple_new=True, owner_collision=True, name_conflict='merge',
        old_source_child=True, replace_existing_two=replace_list)
    before = deepcopy(task.objects)
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert SOUND not in task.objects
    assert task.objects[FIRST]['@Metadata'] == ([] if replace_list else [{'id': OLD_SLOT}]) + [{'id': SLOT}, {'id': SECOND_SLOT}]
    assert task.objects[FIRST]['@OutputBus'] == {'id': BUS}
    assert all(task.objects[oid] == row for oid, row in before.items() if oid != FIRST and not (replace_list and oid == OLD_SLOT))
    assert (OLD_SLOT not in task.objects) is replace_list
    assert len(task.writes) == 5
    assert all(write['objects'][0]['object'] == FIRST for write in task.writes[2:])
    assert task.run('execute', tx)[0] == 2 and len(task.writes) == 5


def test_group_list_replaced_owner_binds_new_guid_and_removes_original_scope(tmp_path):
    from tests.unit.test_owned_named_list_stages_gateway import SECOND_SLOT
    task = group_list_task(tmp_path, multiple_new=True, owner_collision=True, name_conflict='replace')
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert FIRST not in task.objects and OLD_SLOT not in task.objects
    assert task.objects[SOUND]['@Metadata'] == [{'id': SLOT}, {'id': SECOND_SLOT}]
    assert task.objects[SOUND]['@OutputBus'] == {'id': BUS}
    assert len(task.writes) == 5
    assert all(write['objects'][0]['object'] == SOUND for write in task.writes[2:])
    assert task.run('execute', tx)[0] == 2 and len(task.writes) == 5


@pytest.mark.parametrize('creation_first', [False, True])
def test_replaced_owner_rejects_sibling_field_write_before_begin_in_either_order(tmp_path, creation_first):
    task = group_list_task(tmp_path, multiple_new=True, owner_collision=True, name_conflict='replace',
        companion=('object.setReference', FIRST, ROOT), creation_first=creation_first)
    code, rejected = task.step('draft-check')
    assert code == 2 and rejected['error_code'] == 'UNDO_GROUP_OVERLAPPING_OUTCOME', rejected
    assert task.writes == [] and not task.group_open


@pytest.mark.parametrize('policy', ['merge', 'replace', 'merge-replace-list'])
def test_group_list_owner_conflict_and_ancestor_rename_verify_exact_source(tmp_path, policy):
    from tests.unit.test_object_graph_owned_choices_gateway import SECOND
    task = group_list_task(tmp_path, multiple_new=True, owner_collision=True,
        name_conflict='merge' if policy == 'merge-replace-list' else policy, replace_existing_two=policy == 'merge-replace-list',
        companion=('object.setName', SECOND, 'Renamed parent'))
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    owner = SOUND if policy == 'replace' else FIRST
    assert task.objects[owner]['path'].endswith('\\Renamed parent\\Sender')
    assert task.objects[owner]['@OutputBus'] == {'id': BUS}
    assert task.objects[SLOT]['owner'] == {'id': owner}
    assert task.objects[SLOT]['path'] == '\\opaque-slot-path'


def test_merged_owner_original_hierarchy_overlap_stops_before_begin(tmp_path):
    child = '{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}'
    task = group_list_task(tmp_path, multiple_new=True, owner_collision=True, name_conflict='merge', old_source_child=True,
        companion=('object.setNotes', child, 'Conflicting original take'))
    code, rejected = task.step('draft-check')
    assert code == 2 and rejected['error_code'] == 'UNDO_GROUP_OVERLAPPING_OUTCOME', rejected
    assert task.writes == [] and not task.group_open


@pytest.mark.parametrize('policy', ['merge', 'replace'])
def test_owner_conflict_prewrite_drift_cancels_without_constructing_owner_or_retry(tmp_path, policy):
    task = group_list_task(tmp_path, multiple_new=True, owner_collision=True, name_conflict=policy, fault='changed-merge-root')
    tx, shown = task.preview()
    assert task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    code, failed = task.run('execute', tx)
    assert code == 2 and failed.get('verified') is not True and failed['automatic_retry'] is False, failed
    assert len(task.writes) == 1 and SLOT not in task.objects
    assert failed.get('rollback_verified', False) is False
    assert task.run('execute', tx)[0] == 2 and len(task.writes) == 1
    assert not task.group_open


@pytest.mark.parametrize('version,mode', [('2023.1', 'replace-all'), ('2024.1', 'append')])
def test_group_admits_planned_legacy_playlist_references_with_exact_order_and_repeats(tmp_path, version, mode):
    from tests.unit.test_legacy_playlist_planned_targets_gateway import planned_playlist_task, CHILD
    task = group_list_task(tmp_path, task_factory=planned_playlist_task, version=version, mode=mode)
    tx, shown = task.preview()
    assert any('Undo/redo restoration' in warning for warning in shown['artifact']['prepared_operation']['warnings'])
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    expected = [CHILD, ROOT, CHILD] if mode == 'replace-all' else [ROOT, CHILD, ROOT, CHILD]
    assert task.objects[FIRST]['@Playlist'] == [{'id': oid} for oid in expected]
    assert task.objects[ROOT]['notes'] == 'Keep One' and task.objects[CHILD]['notes'] == 'Keep Two'
    assert len(task.writes) == 2 and task.run('execute', tx)[0] == 2
    assert not task.group_open


def test_group_playlist_incomplete_actual_children_cancel_before_reference_array_without_retry(tmp_path):
    from tests.unit.test_legacy_playlist_planned_targets_gateway import planned_playlist_task
    task = group_list_task(tmp_path, task_factory=planned_playlist_task)
    original = task.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri == SET and len(task.writes) == 1:
            result['objects'][0]['children'][0]['children'].pop()
        return result
    task.call = call
    tx, shown = task.preview()
    assert task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    code, failed = task.run('execute', tx)
    assert code == 2 and failed.get('verified') is not True and failed['automatic_retry'] is False, failed
    assert failed.get('rollback_verified', False) is False
    assert len(task.writes) == 1
    assert [uri for uri, _, _ in task.calls if uri.startswith('ak.wwise.core.undo.')] == [
        'ak.wwise.core.undo.beginGroup', 'ak.wwise.core.undo.cancelGroup']
    assert task.run('execute', tx)[0] == 2 and len(task.writes) == 1
    assert not task.group_open


def test_group_playlist_source_within_bounds_ignores_optional_history_budget(tmp_path, monkeypatch):
    from tests.unit.test_legacy_playlist_planned_targets_gateway import planned_playlist_task
    from wwise_waapi import edit_history_business
    monkeypatch.setattr(edit_history_business, 'MAX_OBSERVATIONS', 1)
    task = group_list_task(tmp_path, task_factory=planned_playlist_task)
    task.preview()
    assert task.writes == [] and not task.group_open


def test_retained_list_prefix_drift_after_preview_stops_before_begin(tmp_path):
    task = group_list_task(tmp_path, retained=True)
    tx, shown = task.preview()
    assert task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    task.objects[OLD_SLOT]['notes'] = 'Later drift'
    code, rejected = task.run('execute', tx)
    assert code == 2 and rejected.get('executed') is not True, rejected
    assert task.writes == []
    assert not any(uri.startswith('ak.wwise.core.undo.') for uri, _, _ in task.calls)


@pytest.mark.parametrize('replace,fault', [(False, 'changed-prefix'), (True, 'left-replaced-member')])
def test_retained_list_invalid_source_roster_cancels_before_later_write_without_retry(tmp_path, replace, fault):
    task = group_list_task(tmp_path, retained=True, replace_existing_two=replace, fault=fault)
    tx, shown = task.preview()
    assert task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    code, failed = task.run('execute', tx)
    assert code == 2 and failed['automatic_retry'] is False and failed.get('verified') is not True, failed
    assert failed.get('rollback_verified', False) is False
    assert len(task.writes) == 2 and '@OutputBus' not in task.objects[FIRST]
    assert [uri for uri, _, _ in task.calls if uri.startswith('ak.wwise.core.undo.')] == [
        'ak.wwise.core.undo.beginGroup', 'ak.wwise.core.undo.cancelGroup']
    assert task.run('execute', tx)[0] == 2 and len(task.writes) == 2
    assert not task.group_open


def test_retained_list_ancestor_rename_keeps_owned_members_out_of_ordinary_sibling_roots(tmp_path):
    from tests.unit.test_object_graph_owned_choices_gateway import SECOND
    task = group_list_task(tmp_path, retained=True, companion=('object.setName', SECOND, 'Renamed parent'))
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert task.objects[FIRST]['path'].endswith('\\Renamed parent\\Sender')
    assert task.objects[FIRST]['@Metadata'] == [{'id': OLD_SLOT}, {'id': SLOT}]
    assert task.objects[SLOT]['owner'] == {'id': FIRST}
    assert task.objects[OLD_SLOT]['path'] == '\\opaque-old-slot'
    assert task.objects[SLOT]['path'] == '\\opaque-slot-path'


def test_source_only_group_over_history_budget_still_obeys_source_plan_bound(tmp_path):
    # 64 new nodes + 62 reference fields + 3 retained parent/collision rows consumed
    # 129 history observations. Their actual source plan exceeds 256 KiB.
    task = group_list_task(tmp_path, slot_count=31, second_owner_slots=30)
    code, checked = task.step('draft-check')
    assert code == 2 and checked['error_code'] == 'UNDO_GROUP_PLAN_TOO_LARGE', checked
    assert checked['details']['limit_bytes'] == 262144
    assert checked['details']['size_bytes'] > 262144
    assert task.writes == [] and not task.group_open


@pytest.mark.parametrize('retained', [False, True])
def test_source_only_group_within_source_bounds_ignores_optional_history_budget(tmp_path, monkeypatch, retained):
    from wwise_waapi import edit_history_business
    from wwise_waapi.canonical import canonical_json_bytes
    monkeypatch.setattr(edit_history_business, 'MAX_OBSERVATIONS', 1)
    task = group_list_task(tmp_path, retained=retained)
    _, shown = task.preview()
    plan = shown['artifact']['prepared_operation']['pre_state']['execution_plan']
    assert len(canonical_json_bytes(plan)) <= 262144
    assert task.writes == [] and not task.group_open
