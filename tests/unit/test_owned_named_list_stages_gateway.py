"""Named documented List members retain typed ownership through native-name stages."""
from copy import deepcopy

import pytest

from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, FIRST, SECOND, ROOT, PROJECT_GROUP

BUS = '{55555555-5555-5555-5555-555555555555}'
SOUND = '{66666666-6666-6666-6666-666666666666}'
SLOT = '{77777777-7777-7777-7777-777777777777}'
SET = 'ak.wwise.core.object.set'


OLD_SLOT = '{88888888-8888-8888-8888-888888888888}'


def named_list_task(tmp_path, *, retained=False, fault=None, reference=True):
    task = OwnedGraphTask(tmp_path, '2025.1', 'object.set')
    task.types = [{'classId': cid, 'name': name, 'type': 'WObject'} for name, cid in (
        ('WorkUnit', 1638416), ('Bus', 1376272), ('Sound', 65552), ('MetadataSlot', 5570560))]
    task.objects = {
        PROJECT_GROUP: {'id': PROJECT_GROUP, 'name': 'Default Work Unit', 'type': 'WorkUnit', 'classId': 1638416,
            'path': r'\Master-Mixer Hierarchy\Default Work Unit', 'parent': None, 'notes': 'Keep buses'},
        ROOT: {'id': ROOT, 'name': 'Routing', 'type': 'Bus', 'classId': 1376272,
            'path': r'\Master-Mixer Hierarchy\Default Work Unit\Routing', 'parent': {'id': PROJECT_GROUP}, 'notes': 'Keep collision'},
        SECOND: {'id': SECOND, 'name': 'Default Work Unit', 'type': 'WorkUnit', 'classId': 1638416,
            'path': r'\Actor-Mixer Hierarchy\Default Work Unit', 'parent': None, 'notes': 'Keep sounds'},
    }
    if retained:
        task.objects[FIRST] = {'id': FIRST, 'name': 'Sender', 'type': 'Sound', 'classId': 65552,
            'path': task.objects[SECOND]['path'] + r'\Sender', 'parent': {'id': SECOND},
            'notes': 'Keep sound', '@Metadata': [{'id': OLD_SLOT}]}
        task.objects[OLD_SLOT] = {'id': OLD_SLOT, 'name': 'Old slot', 'type': 'PluginInnerObject', 'classId': 5570560,
            'path': r'\opaque-old-slot', 'owner': {'id': FIRST}, 'parent': None, 'notes': 'Keep old slot'}
    task.metadata = {'OutputBus': {'name': 'OutputBus', 'type': 'Reference',
        'restriction': {'type': 'reference', 'restrictions': [{'type': ['Bus']}]}}}
    original = task.call
    task.writes = []
    def call(uri, args=None, options=None):
        if uri == SET:
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            task.writes.append(deepcopy(args))
            results = []
            def create(node, parent, owned=False):
                oid, actual, cid = {'Routing': (BUS, 'Routing19', 1376272),
                    'Sender': (SOUND, 'Sender', 65552), 'Room slot': (SLOT, 'Room slot', 5570560)}[node['name']]
                task.objects[oid] = {'id': oid, 'name': actual, 'type': 'PluginInnerObject' if owned else node['type'],
                    'classId': cid, 'notes': '', 'path': (r'\opaque-slot-path' if owned else task.objects[parent]['path'] + '\\' + actual),
                    **({'owner': {'id': parent}, 'parent': None} if owned else {'parent': {'id': parent}})}
                result = {'id': oid, 'name': actual}
                for key, nodes in node.items():
                    if key == 'children' or key == '@Metadata':
                        members = [create(child, oid, key == '@Metadata') for child in nodes]
                        result[key] = members
                        if key == '@Metadata':
                            task.objects[oid][key] = [{'id': member['id']} for member in members]
                return result
            for node in args['objects']:
                parent = node['object']
                row = {'id': parent, 'name': task.objects[parent]['name']}
                for key, value in node.items():
                    if key in ('children', '@Metadata'):
                        members = [create(child, parent, key == '@Metadata') for child in value]
                        row[key] = members
                        if key == '@Metadata':
                            task.objects[parent].setdefault(key, []).extend({'id': member['id']} for member in members)
                    elif key == '@OutputBus':
                        target = next(item for item in task.objects.values() if item['path'] == value)
                        task.objects[parent][key] = {'id': target['id']}
                results.append(row)
            if fault == 'changed-prefix-before-slot' and len(task.writes) == 1:
                task.objects[OLD_SLOT]['notes'] = 'Changed before later creation'
            if SLOT in task.objects and len(task.writes) < 3:
                if fault == 'wrong-class':
                    task.objects[SLOT]['classId'] = 65552
                elif fault == 'wrong-owner':
                    task.objects[SLOT]['owner'] = {'id': SECOND}
                elif fault == 'extra-member':
                    task.objects[FIRST if retained else SOUND]['@Metadata'].append({'id': ROOT})
                elif fault == 'reversed-prefix':
                    task.objects[FIRST]['@Metadata'].reverse()
                elif fault == 'changed-prefix':
                    task.objects[OLD_SLOT]['notes'] = 'Unrequested change'
            return {'objects': results}
        return original(uri, args, options)
    task.call = call
    parents = [task.bind(oid) for oid in (PROJECT_GROUP, SECOND)]
    code, configured = task.step('draft-business-configure', '--name-conflict', 'rename')
    assert code == 0, configured
    kinds = {}
    for name in ('Bus', 'Sound', 'MetadataSlot'):
        code, selected = task.step('draft-discover-types', '--role', 'object', '--meaning', name)
        assert code == 0, selected
        kinds[name] = selected['type_candidates'][0]['handle']
    retained_handle = task.bind(FIRST) if retained else None
    owner_scope = ['--object-handle', retained_handle] if retained else ['--type-handle', kinds['Sound']]
    code, fields = task.step('draft-discover-fields', *owner_scope, '--field-source', 'documented-lists', '--list')
    assert code == 0, fields
    selected = next(row for row in fields['agent_result']['items'] if row['name'] == 'Metadata')
    code, field = task.step('draft-discover-fields', *owner_scope, '--field-source', 'documented-lists', '--selection', selected['selection'])
    assert code == 0, field
    list_field = field['meaning_results'][0]['candidates'][0]['handle']
    code, output = task.step('draft-discover-fields', *owner_scope, '--meaning', 'OutputBus')
    assert code == 0, output
    output_field = output['meaning_results'][0]['candidates'][0]['handle']
    code, routing = task.step('draft-declare-new', '--declaration-id', 'routing', '--parent-handle', parents[0], '--name', 'Routing', '--kind', kinds['Bus'])
    assert code == 0, routing
    routing_handle = routing['draft']['declared_object']['result_handle']
    reference_fields = ['--field-value', output_field, routing_handle] if reference else []
    if retained:
        code, sound = task.step('draft-declare-existing', '--declaration-id', 'sender', '--object-handle', retained_handle, *reference_fields)
    else:
        code, sound = task.step('draft-declare-new', '--declaration-id', 'sender', '--parent-handle', parents[1], '--name', 'Sender', '--kind', kinds['Sound'], *reference_fields)
    assert code == 0, sound
    code, slot = task.step('draft-declare-new', '--declaration-id', 'slot', '--parent-handle', retained_handle if retained else sound['draft']['declared_object']['result_handle'], '--name', 'Room slot', '--kind', kinds['MetadataSlot'], '--field', 'object_list', list_field)
    assert code == 0, slot
    return task


def test_native_named_set_proves_named_list_owner_and_all_public_occurrences(tmp_path):
    task = named_list_task(tmp_path)
    before = deepcopy(task.objects)
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert all(task.objects[oid] == row for oid, row in before.items())
    assert len(task.writes) == 3
    assert task.writes[-1] == {'objects': [{'object': SOUND, '@OutputBus': task.objects[BUS]['path']}]}
    assert task.objects[SOUND]['@Metadata'] == [{'id': SLOT}]
    assert task.objects[SLOT]['owner'] == {'id': SOUND} and task.objects[SLOT]['parent'] is None
    roster = verified['agent_result']['business_result']['created_objects']
    assert {row['object']['id'] for row in roster} == {BUS, SOUND, SLOT}
    slot = next(row for row in roster if row['object']['id'] == SLOT)
    assert slot['owner_id'] == SOUND and slot['list_name'] == 'Metadata' and 'parent_id' not in slot


def test_staged_named_list_append_retains_ordered_prefix_and_member_state(tmp_path):
    task = named_list_task(tmp_path, retained=True)
    old = deepcopy(task.objects[OLD_SLOT])
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert task.objects[FIRST]['@Metadata'] == [{'id': OLD_SLOT}, {'id': SLOT}]
    assert task.objects[OLD_SLOT] == old and task.objects[FIRST]['notes'] == 'Keep sound'
    assert task.writes[-1] == {'objects': [{'object': FIRST, '@OutputBus': task.objects[BUS]['path']}]}
    assert {row['object']['id'] for row in verified['agent_result']['business_result']['created_objects']} == {BUS, SLOT}


def test_retained_list_prefix_drift_stops_before_later_creation(tmp_path):
    task = named_list_task(tmp_path, retained=True, fault='changed-prefix-before-slot')
    tx, shown = task.preview()
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, failed = task.run('execute', tx)
    assert code == 2 and failed.get('executed') is not True, failed
    assert len(task.writes) == 1 and SLOT not in task.objects
    code, replay = task.run('execute', tx)
    assert code == 2 and len(task.writes) == 1, replay


@pytest.mark.parametrize('fault', ['wrong-class', 'wrong-owner', 'extra-member', 'reversed-prefix', 'changed-prefix'])
def test_bad_named_list_proof_stops_dependent_reference_and_cannot_retry(tmp_path, fault):
    task = named_list_task(tmp_path, retained=True, fault=fault)
    tx, shown = task.preview()
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, failed = task.run('execute', tx)
    assert code == 2 and failed.get('executed') is not True, failed
    assert len(task.writes) == 2 and '@OutputBus' not in task.objects[FIRST]
    code, replay = task.run('execute', tx)
    assert code == 2 and len(task.writes) == 2, replay


def test_named_list_without_reference_keeps_existing_single_native_source(tmp_path):
    task = named_list_task(tmp_path, reference=False)
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert len(task.writes) == 1 and '@OutputBus' not in task.objects[SOUND]
    assert task.objects[SOUND]['@Metadata'] == [{'id': SLOT}]
    assert task.objects[SLOT]['owner'] == {'id': SOUND} and task.objects[SLOT]['classId'] == 5570560


def test_retained_list_drift_after_preview_blocks_every_write(tmp_path):
    task = named_list_task(tmp_path, retained=True)
    tx, shown = task.preview()
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    task.objects[OLD_SLOT]['notes'] = 'Changed outside Preview'
    code, rejected = task.run('execute', tx)
    assert code == 2 and rejected.get('executed') is not True, rejected
    assert task.writes == []


def test_named_list_verification_requires_retained_ordered_membership_read(tmp_path):
    import json
    from wwise_waapi.canonical import canonical_json_bytes, canonical_sha256
    task = named_list_task(tmp_path)
    tx, shown = task.preview()
    assert task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    code, executed = task.run('execute', tx)
    assert code == 0, executed
    code, full = task.run('transaction-show', tx)
    assert code == 0, full
    events = full['events']
    execution = next(event['details']['dispatch_result'] for event in events if event['event_type'] == 'execution_completed')
    proof = execution['owned_result_execution']
    assert execution['result'] == proof['stages'][0]['dispatch_result']['result']
    assert len(proof['stages']) == 3 and len(proof['creation_bindings']) == 2
    reads = proof['creation_bindings'][1]['readbacks']
    membership = next(row for row in reads if row['args'] == {'from': {'id': [SOUND]}}
        and row['options'] == {'return': ['id', '@Metadata']})
    reads.remove(membership)
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
    assert 'Owned creation stage lost its exact read association' in json.dumps(failed), failed
    assert task.run('execute', tx)[0] == 2 and len(task.writes) == 3
