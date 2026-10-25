"""Named documented List members retain typed ownership through native-name stages."""
from copy import deepcopy
import json

import pytest

from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, FIRST, SECOND, ROOT, PROJECT_GROUP

BUS = '{55555555-5555-5555-5555-555555555555}'
SOUND = '{66666666-6666-6666-6666-666666666666}'
SLOT = '{77777777-7777-7777-7777-777777777777}'
SET = 'ak.wwise.core.object.set'
METADATA = '{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}'


OLD_SLOT = '{88888888-8888-8888-8888-888888888888}'
SECOND_SLOT = '{99999999-9999-9999-9999-999999999999}'


def named_list_task(tmp_path, *, retained=False, fault=None, reference=True, empty_replace_two=False, multiple_new=False, constructor_reference=True, constructor_target='valid', replace_existing_two=False, owner_collision=False, old_source_child=False, name_conflict='rename', retained_kind=('Sound', 65552)):
    task = OwnedGraphTask(tmp_path, '2025.1', 'object.set')
    task.types = [{'classId': cid, 'name': name, 'type': 'Inner' if name == 'MetadataSlot' else 'WObject'} for name, cid in (
        ('WorkUnit', 1638416), ('Bus', 1376272), ('Sound', 65552), ('MetadataSlot', 5570560))]
    task.objects = {
        PROJECT_GROUP: {'id': PROJECT_GROUP, 'name': 'Default Work Unit', 'type': 'WorkUnit', 'classId': 1638416,
            'path': r'\Master-Mixer Hierarchy\Default Work Unit', 'parent': None, 'notes': 'Keep buses'},
        ROOT: {'id': ROOT, 'name': 'Routing', 'type': 'Bus', 'classId': 1376272,
            'path': r'\Master-Mixer Hierarchy\Default Work Unit\Routing', 'parent': {'id': PROJECT_GROUP}, 'notes': 'Keep collision'},
        SECOND: {'id': SECOND, 'name': 'Default Work Unit', 'type': 'WorkUnit', 'classId': 1638416,
            'path': r'\Actor-Mixer Hierarchy\Default Work Unit', 'parent': None, 'notes': 'Keep sounds'},
    }
    task.types.append({'classId': 58982409, 'name': 'Wwise System Output Settings', 'type': 'Metadata'})
    task.objects[METADATA] = {'id': METADATA, 'name': 'System settings', 'type': 'Metadata', 'classId': 58982409,
        'path': r'\Metadata\Default Work Unit\System settings', 'parent': None, 'notes': 'Keep Metadata'}
    if owner_collision:
        task.objects[ROOT]['name'] = 'Existing bus'
        task.objects[ROOT]['path'] = task.objects[PROJECT_GROUP]['path'] + r'\Existing bus'
    if retained_kind[0] not in {row['name'] for row in task.types}:
        task.types.append({'classId': retained_kind[1], 'name': retained_kind[0], 'type': 'WObject'})
    if retained or owner_collision:
        task.objects[FIRST] = {'id': FIRST, 'name': 'Sender', 'type': retained_kind[0], 'classId': retained_kind[1],
            'path': task.objects[SECOND]['path'] + r'\Sender', 'parent': {'id': SECOND},
            'notes': 'Keep sound', '@Metadata': [{'id': OLD_SLOT}]}
        if retained_kind[0] in {'Bus', 'AuxBus'}:
            task.objects[FIRST].update(path=task.objects[PROJECT_GROUP]['path'] + r'\Sender', parent={'id': PROJECT_GROUP})
        task.objects[OLD_SLOT] = {'id': OLD_SLOT, 'name': 'Old slot', 'type': 'PluginInnerObject', 'classId': 5570560,
            'path': r'\opaque-old-slot', 'owner': {'id': FIRST}, 'parent': None, 'notes': 'Keep old slot', '@Metadata': {'id': METADATA}}
        if empty_replace_two:
            task.objects[FIRST]['@Metadata'] = []
            del task.objects[OLD_SLOT]
    task.metadata = {'OutputBus': {'name': 'OutputBus', 'type': 'Reference',
        'restriction': {'type': 'reference', 'restrictions': [{'type': ['Bus']}, 'notNull']}}}
    task.metadata['Metadata'] = {'name': 'Metadata', 'type': 'Reference',
        'restriction': {'type': 'reference', 'restrictions': [{'type': ['Metadata']}, 'notNull']}}
    if old_source_child:
        task.types.append({'classId': 16, 'name': 'AudioFileSource', 'type': 'WObject'})
        child = '{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}'
        task.objects[child] = {'id': child, 'name': 'Existing take', 'type': 'AudioFileSource', 'classId': 16,
            'path': task.objects[FIRST]['path'] + r'\Existing take', 'parent': {'id': FIRST}, 'notes': 'Keep existing source'}
    old_slot_before = deepcopy(task.objects.get(OLD_SLOT))
    original = task.call
    task.writes = []
    task.partial_list_drift_injected = False
    def call(uri, args=None, options=None):
        if uri == 'ak.wwise.core.object.get' and args and 'waql' in args:
            for owner in (FIRST, SOUND):
                if args['waql'] == f'from object "{owner}" select @Metadata take 1':
                    task.calls.append((uri, deepcopy(args), deepcopy(options)))
                    return {'return': deepcopy(task.objects[owner].get('@Metadata', [])[:1])}
        if uri == SET:
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            task.writes.append(deepcopy(args))
            results = []
            def create(node, parent, owned=False):
                oid, actual, cid = {'Routing': (BUS, 'Routing19', 1376272),
                    'Sender': (SOUND, 'Sender', 65552), 'Room slot': (SLOT, 'Room slot', 5570560),
                    'Second slot': (SECOND_SLOT, 'Second slot', 5570560)}[node['name']]
                previous = None
                if node['name'] == 'Routing' and owner_collision:
                    actual = 'Routing'
                if node['name'] == 'Sender' and owner_collision:
                    if name_conflict == 'merge':
                        oid, previous = FIRST, deepcopy(task.objects[FIRST])
                    elif name_conflict == 'replace':
                        del task.objects[FIRST], task.objects[OLD_SLOT]
                if owned:
                    actual = ''
                task.objects[oid] = {'id': oid, 'name': actual, 'type': 'PluginInnerObject' if owned else node['type'],
                    'classId': cid, 'notes': previous['notes'] if previous else '', 'path': (r'\opaque-slot-path' if owned else task.objects[parent]['path'] + '\\' + actual),
                    **({'owner': {'id': parent}, 'parent': None} if owned else {'parent': {'id': parent}})}
                result = {'id': oid, 'name': actual, **({'type': 'PluginInnerObject'} if owned else {})}
                if node['type'] == 'Sound':
                    task.objects[oid]['@Metadata'] = previous.get('@Metadata', []) if previous else []
                for key, nodes in node.items():
                    if key == 'children' or key == '@Metadata' and isinstance(nodes, list):
                        members = [create(child, oid, key == '@Metadata') for child in nodes]
                        result[key] = members
                        if key == '@Metadata':
                            task.objects[oid][key] = [{'id': member['id']} for member in members]
                if owned:
                    assert node.get('@Metadata') == METADATA, 'MetadataSlot constructor needs its Metadata target'
                    task.objects[oid]['@Metadata'] = {'id': node['@Metadata']}
                return result
            for node in args['objects']:
                parent = node['object']
                row = {'id': parent, 'name': task.objects[parent]['name']}
                for key, value in node.items():
                    if key in ('children', '@Metadata'):
                        members = [create(child, parent, key == '@Metadata') for child in value]
                        row[key] = members
                        if key == '@Metadata':
                            if node.get('listMode', args.get('listMode', 'append')) == 'replaceAll':
                                for previous in task.objects[parent].get(key, []):
                                    del task.objects[previous['id']]
                                task.objects[parent][key] = []
                            task.objects[parent].setdefault(key, []).extend({'id': member['id']} for member in members)
                    elif key == '@OutputBus':
                        target = next(item for item in task.objects.values() if item['path'] == value)
                        task.objects[parent][key] = {'id': target['id']}
                results.append(row)
            if fault in {'changed-merge-root', 'changed-merge-prefix'} and len(task.writes) == 1:
                task.objects[FIRST if fault == 'changed-merge-root' else OLD_SLOT]['notes'] = 'External drift before owner stage'
            if fault == 'changed-prefix-before-slot' and len(task.writes) == 1:
                task.objects[OLD_SLOT]['notes'] = 'Changed before later creation'
            if SLOT in task.objects and len(task.writes) < 3:
                if fault == 'wrong-class':
                    task.objects[SLOT]['classId'] = 65552
                elif fault == 'left-replaced-member':
                    task.objects[OLD_SLOT] = deepcopy(old_slot_before)
                elif fault == 'wrong-runtime-type':
                    task.objects[SLOT]['type'] = 'Sound'
                elif fault == 'wrong-owner':
                    task.objects[SLOT]['owner'] = {'id': SECOND}
                elif fault == 'wrong-metadata-target':
                    task.objects[SLOT]['@Metadata'] = {'id': ROOT}
                elif fault == 'extra-member':
                    task.objects[FIRST if retained else SOUND]['@Metadata'].append({'id': ROOT})
                elif fault == 'reversed-prefix':
                    task.objects[FIRST]['@Metadata'].reverse()
                elif fault == 'changed-prefix':
                    task.objects[OLD_SLOT]['notes'] = 'Unrequested change'
            return {'objects': results}
        result = original(uri, args, options)
        if (fault in {'omitted-empty-metadata', 'omitted-nonempty-metadata'} and uri == 'ak.wwise.core.object.get'
                and options == {'return': ['id', '@Metadata']}):
            for row in result.get('return', []):
                value = row.get('@Metadata')
                if isinstance(value, list) and (not value if fault == 'omitted-empty-metadata' else bool(value)):
                    del row['@Metadata']
        if (fault in {'removed-first-member', 'changed-first-member'} and not task.partial_list_drift_injected
                and len(task.writes) == 2 and SLOT in task.objects
                and uri == 'ak.wwise.core.object.get'
                and args == {'from': {'id': [ROOT]}, 'transform': [{'select': ['children']}]}
                and options == {'return': ['id']}):
            # External drift after the first member's full binding/preservation
            # reads, before the next creation's prewrite roster observation.
            task.partial_list_drift_injected = True
            if fault == 'removed-first-member':
                task.objects[FIRST]['@Metadata'] = []
            else:
                task.objects[SLOT]['notes'] = 'Unrequested first-member change'
        return result
    task.call = call
    parents = [task.bind(oid) for oid in (PROJECT_GROUP, SECOND)]
    code, configured = task.step('draft-business-configure', '--name-conflict', name_conflict)
    assert code == 0, configured
    if empty_replace_two or replace_existing_two:
        code, configured = task.step('draft-business-configure', '--name-conflict', name_conflict, '--list-behavior', 'replace-all')
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
    metadata_fields = []
    if constructor_reference:
        metadata_handle = 'null' if constructor_target == 'null' else task.bind(ROOT if constructor_target == 'wrong-type' else METADATA)
        code, metadata = task.step('draft-discover-fields', '--type-handle', kinds['MetadataSlot'], '--meaning', 'Metadata')
        assert code == 0, metadata
        metadata_fields = ['--field-value', metadata['meaning_results'][0]['candidates'][0]['handle'], metadata_handle]
    code, slot = task.step('draft-declare-new', '--declaration-id', 'slot', '--parent-handle', retained_handle if retained else sound['draft']['declared_object']['result_handle'], '--name', 'Room slot', '--kind', kinds['MetadataSlot'], '--field', 'object_list', list_field, *metadata_fields)
    if constructor_target == 'wrong-type':
        assert code == 2 and slot['error_code'] == 'REFERENCE_TARGET_TYPE_MISMATCH', slot
        task.constructor_rejected = slot
        return task
    assert code == 0, slot
    if empty_replace_two or multiple_new or replace_existing_two:
        code, slot2 = task.step('draft-declare-new', '--declaration-id', 'slot2', '--parent-handle', retained_handle if retained else sound['draft']['declared_object']['result_handle'],
            '--name', 'Second slot', '--kind', kinds['MetadataSlot'], '--field', 'object_list', list_field, *metadata_fields)
        assert code == 0, slot2
    return task


def test_empty_replace_list_two_staged_members_survive_and_verify(tmp_path):
    task = named_list_task(tmp_path, retained=True, empty_replace_two=True)
    before = deepcopy(task.objects)
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert task.objects[FIRST]['@Metadata'] == [{'id': SLOT}, {'id': SECOND_SLOT}]
    assert all(task.objects[oid]['owner'] == {'id': FIRST} for oid in (SLOT, SECOND_SLOT))
    assert task.objects[SLOT]['name'] == task.objects[SECOND_SLOT]['name'] == ''
    assert all(task.objects[oid] == row for oid, row in before.items() if oid != FIRST)
    assert task.objects[FIRST]['notes'] == before[FIRST]['notes']
    assert task.objects[FIRST]['@OutputBus'] == {'id': BUS}
    assert len(task.writes) == 4
    assert task.writes[0]['listMode'] == task.writes[1]['listMode'] == 'replaceAll'
    assert task.writes[2]['objects'][0]['listMode'] == 'append'
    assert task.writes[1]['objects'][0]['@Metadata'] == [{'type': 'MetadataSlot', 'name': 'Room slot', '@Metadata': METADATA}]
    assert task.writes[2]['objects'][0]['@Metadata'] == [{'type': 'MetadataSlot', 'name': 'Second slot', '@Metadata': METADATA}]
    assert task.writes[-1] == {'objects': [{'object': FIRST, '@OutputBus': task.objects[BUS]['path']}]}
    roster = verified['agent_result']['business_result']['created_objects']
    assert {row['object']['id'] for row in roster} == {BUS, SLOT, SECOND_SLOT}


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
    code, full = task.run('transaction-show', tx)
    assert code == 0, full
    internal = [node['constructor_inputs'] for node in full['artifact']['prepared_operation']['pre_state']['object_set_nodes']
        if 'constructor_inputs' in node]
    assert internal and all('constructor_packet_sha256' in proof and 'constructor_evidence' in proof for proof in internal)
    public = [assertion['evidence']['constructor_inputs'] for event in full['events']
        for phase in ('role_validation', 'verification')
        for assertion in event['details'].get(phase, {}).get('assertions', [])
        if 'constructor_inputs' in assertion.get('evidence', {})]
    assert len(public) >= 2, full['events']
    expected = {'version': '2025.1', 'class_name': 'MetadataSlot', 'class_id': 5570560,
        'collection': 'Metadata', 'required_references': ['Metadata']}
    assert all(proof == expected for proof in public), public


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


@pytest.mark.parametrize('fault', ['wrong-class', 'wrong-runtime-type', 'wrong-owner', 'wrong-metadata-target', 'extra-member', 'reversed-prefix', 'changed-prefix'])
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
    assert 'result_reference_execution' not in shown['artifact']['prepared_operation']['semantic_preview']['envelope']['metadata']
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


@pytest.mark.parametrize('missing', ['membership', 'constructor-reference'])
def test_named_list_verification_requires_retained_ordered_membership_read(tmp_path, missing):
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
    membership = next(row for row in reads if row['args'] == {'from': {'id': [SOUND if missing == 'membership' else SLOT]}}
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


@pytest.mark.parametrize('fault', ['removed-first-member', 'changed-first-member'])
def test_empty_replace_continuation_rechecks_first_member_before_later_write(tmp_path, fault):
    task = named_list_task(tmp_path, retained=True, empty_replace_two=True, fault=fault)
    tx, shown = task.preview()
    assert task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    code, failed = task.run('execute', tx)
    assert code == 2 and failed.get('executed') is not True, failed
    assert task.partial_list_drift_injected is True
    proof = failed['dispatch_result']['owned_result_execution']
    assert len(proof['stages']) == 2 and len(proof['creation_bindings']) == 3
    assert proof['creation_bindings'][2]['before_readbacks']
    assert any(row['options'] == {'return': ['id', '@Metadata']}
        and row['result']['return'] == [{'id': FIRST, '@Metadata': [{'id': SLOT}]}]
        for row in proof['creation_bindings'][1]['readbacks'])
    assert len(task.writes) == 2 and SECOND_SLOT not in task.objects
    assert '@OutputBus' not in task.objects[FIRST]
    assert task.run('execute', tx)[0] == 2 and len(task.writes) == 2


def test_nonempty_inner_replace_list_keeps_single_member_source_and_preservation(tmp_path):
    task = named_list_task(tmp_path, retained=True)
    before = deepcopy(task.objects)
    code, configured = task.step('draft-business-configure', '--name-conflict', 'rename', '--list-behavior', 'replace-all')
    assert code == 0, configured
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert len(task.writes) == 3 and OLD_SLOT not in task.objects
    assert task.objects[FIRST]['@Metadata'] == [{'id': SLOT}]
    assert task.objects[SLOT]['@Metadata'] == {'id': METADATA}
    assert all(task.objects[oid] == row for oid, row in before.items() if oid not in {FIRST, OLD_SLOT})
    assert task.objects[FIRST]['notes'] == before[FIRST]['notes']


def test_new_metadata_slot_requires_constructor_reference_before_preview(tmp_path):
    task = named_list_task(tmp_path, constructor_reference=False)
    code, checked = task.step('draft-check')
    assert code == 2 and checked.get('error_code') == 'REQUIRED_CONSTRUCTOR_REFERENCE_MISSING', checked
    assert checked['details']['reference'] == 'Metadata'
    assert checked['details']['field_discovery']['meaning'] == 'Metadata'
    encoded = json.dumps(checked)
    assert 'r84-named-list-2a3037eb-2025-r2' not in encoded, checked['details']['required_inputs']
    assert 'constructor_packet_sha256' not in encoded
    assert checked['details']['required_inputs'] == {'version': '2025.1', 'class_name': 'MetadataSlot',
        'class_id': 5570560, 'collection': 'Metadata', 'required_references': ['Metadata']}
    assert task.writes == []


@pytest.mark.parametrize('target,error', [('null', 'INVALID_REFERENCE_TARGET'), ('wrong-type', 'REFERENCE_TARGET_TYPE_MISMATCH')])
def test_metadata_constructor_rejects_null_or_wrong_type_before_preview(tmp_path, target, error):
    task = named_list_task(tmp_path, constructor_target=target)
    code, checked = (2, task.constructor_rejected) if target == 'wrong-type' else task.step('draft-check')
    assert code == 2 and checked.get('error_code') == error, checked
    assert task.writes == []


def test_metadata_constructor_metadata_drift_stops_every_write(tmp_path):
    task = named_list_task(tmp_path)
    tx, shown = task.preview()
    assert task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    task.metadata['Metadata']['restriction']['restrictions'] = [{'type': ['Metadata']}]
    code, rejected = task.run('execute', tx)
    assert code == 2 and rejected.get('executed') is not True, rejected
    assert task.writes == []


def test_new_owner_indistinguishable_inner_members_get_unique_bounded_stages(tmp_path):
    task = named_list_task(tmp_path, multiple_new=True)
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert task.objects[SOUND]['@Metadata'] == [{'id': SLOT}, {'id': SECOND_SLOT}]
    assert task.objects[SLOT]['name'] == task.objects[SECOND_SLOT]['name'] == ''
    roster = verified['agent_result']['business_result']['created_objects']
    slots = {row['declaration_label']: row for row in roster if row.get('name_role') == 'declaration_label'}
    assert slots['Room slot']['object']['id'] == SLOT and slots['Second slot']['object']['id'] == SECOND_SLOT
    assert all(row['owner_id'] == SOUND and row['native_name'] == '' for row in slots.values())
    assert len(task.writes) == 5  # Bus, Sound, each indistinguishable member, then reference.
    assert [row['objects'][0].get('@Metadata') for row in task.writes[2:4]] == [
        [{'type': 'MetadataSlot', 'name': 'Room slot', '@Metadata': METADATA}],
        [{'type': 'MetadataSlot', 'name': 'Second slot', '@Metadata': METADATA}]]
    assert task.writes[-1] == {'objects': [{'object': SOUND, '@OutputBus': task.objects[BUS]['path']}]}


@pytest.mark.parametrize('owner_kind', [('AuxBus', 3997712), ('PropertyContainer', 524304)])
def test_metadata_inner_representation_uses_shared_exact_owner_sources(tmp_path, owner_kind):
    task = named_list_task(tmp_path, retained=True, retained_kind=owner_kind)
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert task.objects[FIRST]['@Metadata'] == [{'id': OLD_SLOT}, {'id': SLOT}]
    assert task.objects[SLOT]['name'] == '' and task.objects[SLOT]['classId'] == 5570560
    assert task.objects[SLOT]['owner'] == {'id': FIRST}
    assert task.objects[SLOT]['@Metadata'] == {'id': METADATA}
    assert task.objects[OLD_SLOT]['notes'] == 'Keep old slot'
    assert len(task.writes) == 3 and task.objects[FIRST]['@OutputBus'] == {'id': BUS}


def test_nonempty_inner_replace_all_keeps_both_created_fragments_and_reference(tmp_path):
    task = named_list_task(tmp_path, retained=True, replace_existing_two=True)
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert task.objects[FIRST]['@Metadata'] == [{'id': SLOT}, {'id': SECOND_SLOT}]
    assert OLD_SLOT not in task.objects
    assert task.objects[FIRST]['@OutputBus'] == {'id': BUS}
    assert len(task.writes) == 4
    first, second = task.writes[1:3]
    assert first['objects'][0]['object'] == FIRST and second['objects'][0]['object'] == FIRST
    assert first['objects'][0].get('listMode', first['listMode']) == 'replaceAll'
    assert second['objects'][0]['listMode'] == 'append'


@pytest.mark.parametrize('policy', ['merge', 'replace', 'merge-replace-list'])
def test_two_inner_members_construct_owner_once_then_use_its_actual_guid(tmp_path, policy):
    task = named_list_task(tmp_path, multiple_new=True, owner_collision=True,
        name_conflict='merge' if policy == 'merge-replace-list' else policy, replace_existing_two=policy == 'merge-replace-list')
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    owner = FIRST if policy.startswith('merge') else SOUND
    expected = ([{'id': OLD_SLOT}] if policy == 'merge' else []) + [{'id': SLOT}, {'id': SECOND_SLOT}]
    assert task.objects[owner]['@Metadata'] == expected
    assert task.objects[owner]['@OutputBus'] == {'id': BUS}
    assert len(task.writes) == 5
    assert task.writes[1]['objects'] == [{'object': SECOND, 'children': [{'name': 'Sender', 'type': 'Sound'}]}]
    for write in task.writes[2:4]:
        assert write['objects'][0]['object'] == owner
        assert 'children' not in write['objects'][0] and 'name' not in write['objects'][0]
    if policy == 'merge':
        assert task.objects[OLD_SLOT]['notes'] == 'Keep old slot'
    elif policy == 'replace':
        assert FIRST not in task.objects and OLD_SLOT not in task.objects
    else:
        assert OLD_SLOT not in task.objects
        assert task.writes[2]['objects'][0].get('listMode', task.writes[2]['listMode']) == 'replaceAll'
        assert task.writes[3]['objects'][0]['listMode'] == 'append'


@pytest.mark.parametrize('fault,policy', [('changed-merge-root', 'merge'), ('changed-merge-root', 'replace'), ('changed-merge-prefix', 'merge')])
def test_inner_owner_first_fragment_rechecks_original_retained_scope(tmp_path, fault, policy):
    task = named_list_task(tmp_path, multiple_new=True, owner_collision=True, name_conflict=policy, fault=fault)
    tx, shown = task.preview()
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, rejected = task.run('execute', tx)
    assert code == 2 and rejected.get('executed') is not True, rejected
    assert len(task.writes) == 1 and SLOT not in task.objects
    code, replay = task.run('execute', tx)
    assert code == 2 and len(task.writes) == 1, replay


@pytest.mark.parametrize('fault', ['removed-first-member', 'changed-first-member'])
def test_nonempty_inner_replace_all_rechecks_partial_roster_before_next_append(tmp_path, fault):
    task = named_list_task(tmp_path, retained=True, replace_existing_two=True, fault=fault)
    tx, shown = task.preview()
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, rejected = task.run('execute', tx)
    assert code == 2 and rejected.get('executed') is not True, rejected
    assert task.partial_list_drift_injected and len(task.writes) == 2
    assert SECOND_SLOT not in task.objects and '@OutputBus' not in task.objects[FIRST]
    code, replay = task.run('execute', tx)
    assert code == 2 and len(task.writes) == 2, replay


def test_nonempty_inner_replace_all_proves_old_member_absent_before_later_append(tmp_path):
    task = named_list_task(tmp_path, retained=True, replace_existing_two=True, fault='left-replaced-member')
    tx, shown = task.preview()
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, rejected = task.run('execute', tx)
    assert code == 2 and rejected.get('executed') is not True, rejected
    assert len(task.writes) == 2 and SECOND_SLOT not in task.objects
    code, replay = task.run('execute', tx)
    assert code == 2 and len(task.writes) == 2, replay


@pytest.mark.parametrize('corrupt_child', [False, True])
def test_inner_merge_owner_preserves_preexisting_hierarchy_before_member_writes(tmp_path, corrupt_child):
    task = named_list_task(tmp_path, multiple_new=True, owner_collision=True, old_source_child=True, name_conflict='merge')
    child = '{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}'
    before = {'id': child, 'name': 'Existing take', 'type': 'AudioFileSource', 'classId': 16,
        'path': task.objects[FIRST]['path'] + r'\Existing take', 'parent': {'id': FIRST}, 'notes': 'Keep existing source'}
    task.objects[child] = deepcopy(before)
    original = task.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if corrupt_child and uri == SET and len(task.writes) == 2:
            task.objects[child]['notes'] = 'Unrequested source change'
        return result
    task.call = call
    tx, shown = task.preview()
    if corrupt_child:
        code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
        assert code == 0, confirmed
        code, rejected = task.run('execute', tx)
        assert code == 2 and rejected.get('executed') is not True, rejected
        assert len(task.writes) == 2 and SLOT not in task.objects
        code, replay = task.run('execute', tx)
        assert code == 2 and len(task.writes) == 2, replay
    else:
        code, verified = task.finish(tx, shown)
        assert code == 0 and verified['verified'] is True, verified
        assert task.objects[child] == before and len(task.writes) == 5


def test_new_inner_owner_missing_empty_projection_requires_independent_bounded_list_read(tmp_path):
    task = named_list_task(tmp_path, multiple_new=True, fault='omitted-empty-metadata')
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    query = {'waql': f'from object "{SOUND}" select @Metadata take 1'}
    assert any(uri == 'ak.wwise.core.object.get' and args == query and options == {'return': ['id']}
        for uri, args, options in task.calls)
    assert len(task.writes) == 5 and task.objects[SOUND]['@Metadata'] == [{'id': SLOT}, {'id': SECOND_SLOT}]


def test_nonempty_inner_list_cannot_be_normalized_from_omitted_projection(tmp_path):
    task = named_list_task(tmp_path, multiple_new=True, fault='omitted-nonempty-metadata')
    tx, shown = task.preview()
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, rejected = task.run('execute', tx)
    assert code == 2 and rejected.get('executed') is not True, rejected
    query = {'waql': f'from object "{SOUND}" select @Metadata take 1'}
    assert any(uri == 'ak.wwise.core.object.get' and args == query for uri, args, _ in task.calls)
    assert len(task.writes) == 3 and SECOND_SLOT not in task.objects and '@OutputBus' not in task.objects[SOUND]
    code, replay = task.run('execute', tx)
    assert code == 2 and len(task.writes) == 3, replay


def metadata_local_reference():
    from pathlib import Path
    source = json.loads((Path(__file__).parents[1] / 'fixtures' / 'metadata' / 'metadata-slot-local-reference-2025.json').read_text())
    value = deepcopy(source['reference_read']['result']['return'][0]['@Metadata'])
    value[0].update(id=METADATA, name='System settings')
    return value


@pytest.mark.parametrize('fault', ['wrong-target', 'multiple', 'empty', 'malformed'])
def test_metadata_local_singleton_rejects_invalid_reference_before_dependent_write(tmp_path, fault):
    task = named_list_task(tmp_path)
    original = task.call
    value = metadata_local_reference()
    if fault == 'wrong-target':
        value[0]['id'] = ROOT
    elif fault == 'multiple':
        value.append({'id': ROOT, 'name': 'Routing'})
    elif fault == 'empty':
        value = []
    else:
        value[0]['name'] = None
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('object.get') and args == {'from': {'id': [SLOT]}} and options == {'return': ['id', '@Metadata']}:
            return {'return': [{'id': SLOT, '@Metadata': deepcopy(value)}]}
        return result
    task.call = call
    tx, shown = task.preview()
    assert task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    code, stopped = task.run('execute', tx)
    assert code == 2 and stopped.get('executed') is not True, stopped
    assert stopped['dispatch_result']['message'] == 'Required constructor reference changed before dependent write'
    assert len(task.writes) == 2 and '@OutputBus' not in task.objects[SOUND]
    assert task.run('execute', tx)[0] == 2 and len(task.writes) == 2


@pytest.mark.parametrize('fault', ['metadata-cardinality', 'unrelated-reference-array'])
def test_metadata_local_relation_is_strict_in_final_graph_verification(tmp_path, fault):
    task = named_list_task(tmp_path)
    original = task.call
    corrupt = False
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('object.get'):
            for row in result.get('return', []):
                if row.get('id') == SLOT and '@Metadata' in row:
                    row['@Metadata'] = metadata_local_reference()
                    if corrupt and fault == 'metadata-cardinality':
                        row['@Metadata'].append({'id': ROOT, 'name': 'Routing'})
                if corrupt and fault == 'unrelated-reference-array' and row.get('id') == SOUND and 'OutputBus' in row:
                    row['OutputBus'] = [row['OutputBus']]
        return result
    task.call = call
    tx, shown = task.preview()
    assert task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    code, executed = task.run('execute', tx)
    assert code == 0 and executed['executed'] is True, executed
    corrupt = True
    code, rejected = task.run('verify', tx)
    assert code == 2 and rejected['verified'] is False and rejected['state'] == 'verification_failed', rejected
    assert len(task.writes) == 3
    assert task.run('execute', tx)[0] == 2 and len(task.writes) == 3


def playlist_creation_task(tmp_path, *, reference=True, operation='object.set', fixture_ids=None):
    from tests.unit.test_playlist_reference_gateway import FACTS
    owner_id, target_id, old_slot_id, peer_id, new_slot_id = fixture_ids or (ROOT, FIRST, OLD_SLOT, SECOND_SLOT, SLOT)
    task = OwnedGraphTask(tmp_path, '2025.1', operation)
    base = r'\Containers\Default Work Unit\Numbers'
    task.types = [{'classId': cid, 'name': name, 'type': category} for cid, name, category in (
        (589840, 'RandomSequenceContainer', 'WObject'), (65552, 'Sound', 'WObject'), (5636096, 'PlaylistSlot', 'Inner'))]
    task.metadata = {'PlaylistObject': deepcopy(FACTS['metadata'])}
    task.objects = {
        owner_id: {'id': owner_id, 'name': 'Numbers', 'type': 'RandomSequenceContainer', 'classId': 589840,
            'path': base, 'notes': 'Keep owner', '@RandomOrSequence': 1, '@Playlist': [{'id': old_slot_id}, {'id': peer_id}]},
        target_id: {'id': target_id, 'name': 'First', 'type': 'Sound', 'classId': 65552,
            'path': base + r'\First', 'parent': {'id': owner_id}, 'notes': 'Keep target'},
    }
    for oid in (old_slot_id, peer_id):
        task.objects[oid] = {'id': oid, 'name': '', 'type': 'PluginInnerObject', 'classId': 5636096,
            'path': base + r'\[PlaylistSlot: (First)]', 'owner': {'id': owner_id}, 'notes': 'Keep peer',
            'PlaylistObject': {'id': target_id}}
    original = task.call
    task.writes = []
    def call(uri, args=None, options=None):
        if uri == 'ak.wwise.core.object.get' and args and 'waql' in args:
            import re
            match = re.fullmatch(r'from object "([^"\n]+)"(?: select @(Playlist|PlaylistObject))? take [0-9]+', args['waql'])
            if match:
                task.calls.append((uri, deepcopy(args), deepcopy(options)))
                if match[2] is None:
                    return {'return': task.project_rows([task.objects[match[1]]] if match[1] in task.objects else [], options)}
                value = task.objects[match[1]].get('@Playlist' if match[2] == 'Playlist' else 'PlaylistObject')
                ids = [row['id'] for row in value] if isinstance(value, list) else [value['id']]
                return {'return': task.project_rows([task.objects[oid] for oid in ids], options)}
        if uri == SET:
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            task.writes.append(deepcopy(args))
            item, = args['objects']
            slot, = item['@Playlist']
            assert item['object'] == owner_id and slot == {'type': 'PlaylistSlot', 'name': '', '@PlaylistObject': target_id}
            task.objects[new_slot_id] = {'id': new_slot_id, 'name': '', 'type': 'PluginInnerObject', 'classId': 5636096,
                'path': base + r'\[PlaylistSlot: (First)]', 'owner': {'id': owner_id}, 'notes': '', 'PlaylistObject': {'id': target_id}}
            task.objects[owner_id]['@Playlist'].append({'id': new_slot_id})
            return {'objects': [{'id': owner_id, 'name': 'Numbers', '@Playlist': [{'id': new_slot_id, 'name': ''}]}]}
        return original(uri, args, options)
    task.call = call
    owner, target = task.bind(owner_id), task.bind(target_id)
    code, kinds = task.step('draft-discover-types', '--role', 'object', '--meaning', 'PlaylistSlot')
    assert code == 0, kinds
    kind = kinds['type_candidates'][0]['handle']
    code, fields = task.step('draft-discover-fields', '--object-handle', owner, '--field-source', 'documented-lists', '--list')
    assert code == 0, fields
    selected = next(row for row in fields['agent_result']['items'] if row['name'] == 'Playlist')
    code, field = task.step('draft-discover-fields', '--object-handle', owner, '--field-source', 'documented-lists', '--selection', selected['selection'])
    assert code == 0, field
    list_field = field['meaning_results'][0]['candidates'][0]['handle']
    code, field = task.step('draft-discover-fields', '--type-handle', kind, '--meaning', 'Playlist Object')
    assert code == 0, field
    reference_field = field['meaning_results'][0]['candidates'][0]['handle']
    reference_args = ['--field-value', reference_field, target] if reference else []
    code, declared = task.step('draft-declare-new', '--declaration-id', 'playlist-slot', '--parent-handle', owner,
        '--name', 'Requested occurrence', '--kind', kind, '--field', 'object_list', list_field, *reference_args)
    assert code == 0, declared
    return task


def test_new_playlist_member_keeps_ordered_peers_and_targets_exact_direct_child(tmp_path):
    task = playlist_creation_task(tmp_path)
    before = deepcopy(task.objects)
    code, checked = task.step('draft-check')
    assert code == 0, checked
    code, preview = task.step('preview-from-draft')
    assert code == 0, preview
    tx = preview['transaction_id']
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    naming = preview['preview_summary']['owned_inner_naming']
    assert naming['class_name'] == 'PlaylistSlot' and naming['collection'] == 'Playlist'
    assert naming['declaration_name_role'] == 'label' and naming['native_name'] == ''
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert task.objects[ROOT]['@Playlist'] == [{'id': OLD_SLOT}, {'id': SECOND_SLOT}, {'id': SLOT}]
    assert all(task.objects[oid] == row for oid, row in before.items() if oid != ROOT)
    assert task.objects[SLOT]['PlaylistObject'] == {'id': FIRST}
    created, = verified['agent_result']['business_result']['created_objects']
    assert created['declaration_label'] == 'Requested occurrence' and created['name_role'] == 'declaration_label'
    assert created['native_name'] == created['object']['name'] == ''
    assert created['owner_id'] == ROOT and created['list_name'] == 'Playlist'
    assert len(task.writes) == 1
    code, replay = task.run('execute', tx)
    assert code == 2 and len(task.writes) == 1, replay


def test_new_playlist_member_rejects_wrong_parent_before_preview(tmp_path):
    task = playlist_creation_task(tmp_path)
    task.objects[FIRST]['parent'] = {'id': SECOND_SLOT}
    before = deepcopy(task.objects)
    code, result = task.step('draft-check')
    assert code == 2 and 'CONSTRAINED_REFERENCE_BOUNDARY' in json.dumps(result), result
    assert task.objects == before and task.writes == []


@pytest.mark.parametrize('change', ['target-parent', 'owner-class', 'membership', 'metadata', 'peer-reference'])
@pytest.mark.parametrize('stage', ['before-execute', 'after-execute'])
def test_new_playlist_member_rejects_drift_without_replaying_creation(tmp_path, change, stage):
    task = playlist_creation_task(tmp_path)
    tx, shown = task.preview()
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    if stage == 'after-execute':
        code, executed = task.run('execute', tx)
        assert code == 0, executed
    if change == 'target-parent':
        task.objects[FIRST]['parent'] = {'id': SECOND_SLOT}
    elif change == 'owner-class':
        task.objects[ROOT]['classId'] = 65552
    elif change == 'membership':
        task.objects[ROOT]['@Playlist'].reverse()
    elif change == 'metadata':
        task.metadata['PlaylistObject']['restriction']['restrictions'].remove('mustChildOf')
    else:
        task.objects[OLD_SLOT]['PlaylistObject'] = {'id': ROOT}
    before = deepcopy(task.objects)
    code, result = task.run('execute' if stage == 'before-execute' else 'verify', tx)
    assert code == 2, result
    assert task.objects == before and len(task.writes) == (stage == 'after-execute')
    code, replay = task.run('execute', tx)
    assert code == 2 and len(task.writes) == (stage == 'after-execute'), replay


def test_new_playlist_member_does_not_recreate_after_missing_result_identity(tmp_path):
    task = playlist_creation_task(tmp_path)
    tx, shown = task.preview()
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    original = task.call
    def interrupted(uri, args=None, options=None):
        result = original(uri, args, options)
        return {} if uri == SET else result
    task.call = interrupted
    code, executed = task.run('execute', tx)
    # Acknowledged native change without the returned GUID is never repaired by
    # creating again or by selecting an object from its display path.
    code, verified = task.run('verify', tx)
    assert code == 2 and verified.get('verified') is not True, verified
    code, replay = task.run('execute', tx)
    assert code == 2 and len(task.writes) == 1, replay
    assert task.objects[ROOT]['@Playlist'] == [{'id': OLD_SLOT}, {'id': SECOND_SLOT}, {'id': SLOT}]


@pytest.mark.parametrize('policy', ['read_only', 'ask_before_changes', 'allow_changes'])
def test_new_playlist_member_retains_each_modification_policy(tmp_path, policy):
    task = playlist_creation_task(tmp_path)
    code, configured = task.run('config-set', '--project-modification-policy', policy)
    assert code == 0, configured
    code, checked = task.step('draft-check')
    assert code == 0, checked
    code, preview = task.step('preview-from-draft', *(['--apply'] if policy == 'allow_changes' else []))
    if policy == 'read_only':
        if code == 0:
            code, result = task.run('execute', preview['transaction_id'])
            assert code == 2, result
        assert task.writes == []
        return
    assert code == 0, preview
    tx = preview['transaction_id']
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    if policy == 'ask_before_changes':
        code, result = task.run('execute', tx)
        assert code == 2 and task.writes == [], result
        code, result = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
        assert code == 0, result
    else:
        assert shown['authorization']['mode'] == 'policy_authorization'
    code, executed = task.run('execute', tx)
    assert code == 0, executed
    code, verified = task.run('verify', tx)
    assert code == 0 and verified['verified'] is True and len(task.writes) == 1, verified


@pytest.mark.parametrize('version,element_names', [
    ('2021.1', None), ('2022.1', None),
    ('2023.1', ['Sound', 'RandomSequenceContainer', 'SwitchContainer', 'BlendContainer']),
    ('2024.1', ['Sound', 'RandomSequenceContainer', 'SwitchContainer', 'BlendContainer']),
    ('2025.1', ['PlaylistSlot']),
])
def test_playlist_creation_discovery_preserves_five_version_list_representations(tmp_path, version, element_names):
    task = OwnedGraphTask(tmp_path, version, 'object.create' if version == '2021.1' else 'object.set')
    task.types = [{'name': 'RandomSequenceContainer', 'classId': 589840, 'type': 'WObject'}]
    task.objects[FIRST] = {'id': FIRST, 'name': 'Numbers', 'type': 'RandomSequenceContainer', 'classId': 589840,
        'path': r'\Containers\Numbers', '@RandomOrSequence': 1}
    owner = task.bind(FIRST)
    code, fields = task.step('draft-discover-fields', '--object-handle', owner,
        '--field-source', 'documented-lists', '--list')
    assert code == 0, fields
    playlists = [row for row in fields['agent_result']['items'] if row['name'] == 'Playlist']
    if element_names is None:
        assert playlists == [] and fields['agent_result']['native_unavailability_proven'] is False
    else:
        playlist, = playlists
        assert [row['name'] for row in playlist['element_classes']] == element_names


def test_new_playlist_member_requires_selected_child_in_its_constructor(tmp_path):
    task = playlist_creation_task(tmp_path, reference=False)
    code, result = task.step('draft-check')
    assert code == 2 and 'PLAYLIST_CONSTRUCTOR_TARGET_REQUIRED' in json.dumps(result), result
    assert task.writes == []


@pytest.mark.parametrize('mode', ['replace-all', 'object.create'])
def test_new_playlist_member_does_not_extrapolate_its_constructor_contract(tmp_path, mode):
    task = playlist_creation_task(tmp_path, operation='object.create' if mode == 'object.create' else 'object.set')
    if mode == 'replace-all':
        code, configured = task.step('draft-business-configure', '--list-behavior', 'replace-all')
        assert code == 0, configured
    code, result = task.step('draft-check')
    assert code == 2 and 'CONSTRAINED_REFERENCE_BOUNDARY' in json.dumps(result), result
    assert task.writes == []
