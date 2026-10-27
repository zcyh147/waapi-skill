"""Supported source Lists compose into native groups without new history observers."""
from copy import deepcopy
import json

import pytest

from tests.unit.test_owned_named_list_stages_gateway import (
    named_list_task, BUS, SOUND, SLOT, METADATA, SET,
)


def group_list_task(tmp_path, *, companion=None, **kwargs):
    task = named_list_task(tmp_path, compound=True, **kwargs)
    assert task.step('draft-check')[0] == 0
    children = [task.draft, task.authority]
    if companion:
        operation, object_id, value = companion
        parent, authority, revision = task.compound_parent
        code, started = task.run('draft-start-undo-child', parent, '--task-authority', authority,
            '--expected-revision', str(revision), '--operation', operation)
        assert code == 0, started
        task.draft, task.authority, task.revision = started['draft']['draft_id'], started['task_authority'], started['draft']['revision']
        task.bind(object_id)
        assert task.step('draft-declare-object-change', '--new-name' if operation == 'object.setName' else '--notes', value)[0] == 0
        assert task.step('draft-check')[0] == 0
        children.extend([task.draft, task.authority])
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


def test_group_list_retained_owner_remains_an_explicit_source_admission_gap(tmp_path):
    task = group_list_task(tmp_path, retained=True)
    code, rejected = task.step('draft-check')
    assert code == 2 and rejected['error_code'] == 'UNDO_GROUP_CHILD_OBSERVATION_REQUIRED', rejected
    assert 'retained/replacement source admission remains unfinished' in rejected['message']
    assert task.writes == []
