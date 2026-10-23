"""One 2025 native-name SET source with a typed owned Metadata List member."""
import hashlib
import json
import os
from pathlib import Path
import uuid

import pytest

from tests.destructive.test_gateway_workflow_transaction_matrix import (
    _bind_business_object, _complete_business_draft, _discover_business_type,
    _start_business_draft, _update_business_draft, declared_business_object_handle,
    discovered_business_field_handle, workflow_sandbox_runtime,
)

pytestmark = [pytest.mark.live, pytest.mark.destructive,
    pytest.mark.skipif(os.environ.get('WWISE_VERSION') != '2025.1', reason='One matching 2025 named List source witness')]
OWNER = '{ED2BCAC8-D7B6-4448-8900-439B557894F4}'
ANCESTOR = '{8CF94195-E210-4967-89DB-CA103B48A267}'
GUNS = '{06362E8D-5A32-497A-B063-3DA95963CE47}'
CARS = '{33329D23-BCDD-4D1A-9734-2403A3428FAE}'
CONTAINERS = '{B7237E6E-5972-4B02-A4C9-267862F2241B}'
RETAINED_CONTAINER = '{69D14C5F-00CF-445E-B163-A53DBC2AFB80}'
WINDOWS = '{6E0CB257-C6C8-4C5C-8366-2740DFC441EC}'
OWNER_PATH = r'\Busses\Default Work Unit\Main Audio Bus\Environmental\SFX'
CONTAINERS_PATH = r'\Containers\Default Work Unit'
GET = 'ak.wwise.core.object.get'
SET = 'ak.wwise.core.object.set'
ROLES = ('bus', 'sound', 'slot')
REQUESTED = {'bus': 'Guns', 'sound': 'R84 Metadata Sound', 'slot': 'Room slot'}
CLASSES = {'bus': 1376272, 'sound': 65552, 'slot': 5570560}


def test_2025_native_named_set_with_owned_metadata_slot(workflow_sandbox_runtime):
    runtime = workflow_sandbox_runtime
    assert runtime.version == '2025.1'
    build = runtime.sandbox.metadata.get_info_version
    assert tuple(build.get(key) for key in ('year', 'major', 'minor', 'build')) == (2025, 1, 7, 9143)
    output = runtime.state_dir / 'named-list-native-source.json'
    assert not output.exists(), 'Never overwrite an earlier observation'
    output.parent.mkdir(parents=True, exist_ok=True)
    evidence_root = Path(runtime.env['WWISE_EVIDENCE_DIR'])
    previous = set(evidence_root.glob('*.json'))
    endpoint = {'host': runtime.lifecycle.host, 'port': runtime.port, 'url': runtime.lifecycle.waapi_url}
    observation = {'candidate': runtime.candidate, 'version': runtime.version, 'endpoint': endpoint,
        'calls': [], 'reads': [], 'transactions': [], 'native_evidence': [], 'setup_transaction_count': 0,
        'history_executed': False, 'complete': False, 'business_effect_verified': False,
        'lifecycle_acceptance': 'Requires final host-category-evidence/v3 source/cleanup/process PASS'}
    category = {'category': 'native-named-set-owned-metadata-list', 'status': 'FAIL',
        'observation_path': str(output), 'verifier_strength': 'independent_actual_GUID_class_owner_ordered_List_reference_and_retained_scope'}
    runtime.category_results.append(category)

    def retain():
        body = json.dumps(observation, ensure_ascii=False, indent=2).encode('utf-8')
        assert len(body) <= 16 * 1024 * 1024, 'Named List observation byte bound exceeded'
        temporary = output.with_suffix('.tmp')
        temporary.write_bytes(body)
        temporary.replace(output)

    class ReceiptGateway:
        def raw_gateway(self, argv):
            assert len(observation['calls']) < 128, 'Named List public command bound exceeded'
            record = {'argv': list(argv)}
            observation['calls'].append(record)
            try:
                code, payload = runtime.raw_gateway(argv)
                record.update(exit_code=code, payload=payload)
                return code, payload
            except BaseException as exc:
                record['exception'] = {'type': type(exc).__name__, 'message': str(exc)}
                raise
            finally:
                retain()

        def gateway(self, argv, *, live):
            code, payload = self.raw_gateway(argv)
            assert code == 0 and payload.get('ok') is True, payload
            if live:
                assert payload.get('endpoint') == endpoint and payload.get('detected_version') == runtime.version, payload
            return payload

    gateway = ReceiptGateway()

    def query(label, argv, ceiling):
        assert len(observation['reads']) < 15
        observation['reads'].append({'label': label, 'call_index': len(observation['calls'])})
        payload = gateway.gateway(['query-object', *argv, '--max-results', str(ceiling), '--detail'], live=True)
        assert payload.get('projection_complete') is not False and payload.get('status') != 'partial', payload
        assert payload.get('limit_reached') is not True and list(payload)[-1] == 'agent_result', payload
        rows = payload['agent_result']
        assert isinstance(rows, list) and payload['count'] == len(rows) and len(rows) < ceiling, payload
        assert len({str(uuid.UUID(row['id'])) for row in rows}) == len(rows), rows
        assert all(uuid.UUID(row['id']).int != 0 for row in rows), rows
        return rows

    projection = ['--include', 'class-id', '--include', 'parent', '--include', 'notes']

    def exact(label, identity, *, platform=False, reference=False):
        args = ['--exact-id', identity, *([] if platform else projection)]
        if reference:
            args += ['--include-field', 'OutputBus', '--platform', WINDOWS]
        row, = query(label, args, 2)
        assert row['id'].upper() == identity.upper(), row
        return row

    def scope(label):
        return {'owner': exact(label + '-owner', OWNER), 'ancestor': exact(label + '-ancestor', ANCESTOR),
            'buses': query(label + '-buses', ['--exact-id', OWNER, '--relationship', 'descendants', *projection], 8),
            'containers': exact(label + '-containers', CONTAINERS),
            'children': query(label + '-container-children', ['--exact-id', CONTAINERS, '--relationship', 'children', *projection], 4)}

    try:
        observation['reads'].append({'label': 'host', 'call_index': len(observation['calls'])})
        host = gateway.gateway(['status'], live=True)
        assert host['wwise']['isCommandLine'] is True, host
        # Status intentionally has no agent_result; exact result ordering applies to queries.
        platform = exact('platform', WINDOWS, platform=True)
        assert platform['name'] == 'Windows' and platform['type'] == 'Platform', platform
        before = observation['before'] = scope('before')
        assert before['owner']['path'] == OWNER_PATH and before['owner']['parent']['id'] == ANCESTOR, before
        assert before['owner']['class_id'] == before['ancestor']['class_id'] == 1376272, before
        assert before['containers']['path'] == CONTAINERS_PATH and before['containers']['class_id'] == 1638416, before
        assert {row['id'] for row in before['buses']} == {GUNS, CARS}, before
        assert {row['id'] for row in before['children']} == {RETAINED_CONTAINER}, before
        assert {row['name'] for row in before['buses']} == {'Guns', 'Cars'}, before
        assert all(row['class_id'] == 1376272 and row['parent']['id'] == OWNER for row in before['buses']), before
        draft = _start_business_draft(gateway, 'object.set')
        parents = {role: _bind_business_object(gateway, draft, object_id=identity) for role, identity in (('bus', OWNER), ('sound', CONTAINERS))}
        _update_business_draft(gateway, draft, 'draft-business-configure', ['--name-conflict', 'rename', '--platform', WINDOWS], live=False)
        types = {name: _discover_business_type(gateway, draft, meaning=name, role='object', expected_label=name)
            for name in ('Bus', 'Sound', 'MetadataSlot')}
        listing = _update_business_draft(gateway, draft, 'draft-discover-fields',
            ['--type-handle', types['Sound'], '--field-source', 'documented-lists', '--list'], live=True)
        choice, = [row for row in listing['agent_result']['items'] if row['name'] == 'Metadata']
        assert choice['element_classes'] == [{'name': 'MetadataSlot', 'class_id': 5570560}], choice
        selected = _update_business_draft(gateway, draft, 'draft-discover-fields',
            ['--type-handle', types['Sound'], '--field-source', 'documented-lists', '--selection', choice['selection']], live=True)
        list_candidate, = [row for result in selected['meaning_results'] for row in result['candidates']]
        assert list_candidate['field_kind'] == 'list' and list_candidate['evidence']['declaration']['name'] == 'Metadata', selected
        list_field = list_candidate['handle']
        observation['list_selection'] = selected
        page, seen, output_choice = None, set(), None
        for _ in range(4):
            fields = _update_business_draft(gateway, draft, 'draft-discover-fields',
                ['--type-handle', types['Sound'], '--list', '--page-size', '64', *(['--page', page] if page else [])], live=True)['agent_result']
            matches = [row for row in fields['fields'] if row['name'] == 'OutputBus']
            assert len(matches) <= 1, fields
            if matches:
                output_choice = matches[0]
                break
            assert fields.get('complete') is not True, fields
            page = fields['next_page']
            assert isinstance(page, str) and page not in seen, fields
            seen.add(page)
        assert output_choice is not None, 'OutputBus not disclosed within four bounded pages'
        selected = _update_business_draft(gateway, draft, 'draft-discover-fields',
            ['--type-handle', types['Sound'], '--selection', output_choice['selection']], live=True)
        field = discovered_business_field_handle(selected, 'OutputBus')
        candidate, = [row for result in selected['meaning_results'] for row in result['candidates'] if row['handle'] == field]
        assert candidate['field_kind'] == 'reference' and 'Bus' in candidate['restrictions']['allowed_target_types'], candidate
        observation['output_bus_field'] = candidate
        handles = {}
        for role, name, kind, parent in (('bus', REQUESTED['bus'], 'Bus', parents['bus']),
                ('sound', REQUESTED['sound'], 'Sound', parents['sound']), ('slot', REQUESTED['slot'], 'MetadataSlot', 'sound')):
            declared = _update_business_draft(gateway, draft, 'draft-declare-new', ['--declaration-id', role,
                '--parent-handle', handles[parent] if parent in handles else parent, '--name', name, '--kind', types[kind],
                *(['--field-value', field, handles['bus']] if role == 'sound' else []),
                *(['--field', 'object_list', list_field] if role == 'slot' else [])], live=False)
            handles[role] = declared_business_object_handle(declared, role)
        observation['declared_handles'] = handles
        phase = {'role': 'source'}
        observation['transactions'].append(phase)

        def inspect(preview):
            shown = phase['before_authorization'] = gateway.gateway(['transaction-show', preview['transaction_id']], live=False)
            prepared = observation['prepared'] = shown['artifact']['prepared_operation']
            facts = prepared['pre_state']['planned_reference_context']['facts']
            specs = observation['specs'] = {role: next(node for node in prepared['verification_plan']['nodes']
                if facts.get(node['request_path'], {}).get('result_handle') == handle) for role, handle in handles.items()}
            assert all(specs[role]['class_id'] == CLASSES[role] and specs[role]['requested_name'] == REQUESTED[role] for role in ROLES), specs
            assert specs['slot']['collection'] == 'Metadata' and specs['slot']['parent_request_path'] == specs['sound']['request_path'], specs
            plan = prepared['pre_state']['owned_result_stages']
            assert len(plan['creation_stages']) == 2 and len(plan['deferred']) == 1 and len(plan['lists']) == 1, plan
            assert plan['lists'][0]['before'] == [] and plan['lists'][0]['members'] == [specs['slot']['request_path']], plan
            assert prepared['semantic_preview']['envelope']['metadata']['result_reference_execution']['stage_count'] == 3

        phase.update(_complete_business_draft(gateway, draft, inspect_preview=inspect))
        assert phase['execute']['automatic_retry'] is False and phase['verify']['verified'] is True, phase
        phase['after_verification'] = gateway.gateway(['transaction-show', phase['preview']['transaction_id']], live=False)
        assert phase['before_authorization']['artifact'] == phase['after_verification']['artifact'], phase
        execution = next(event['details']['dispatch_result'] for event in phase['after_verification']['events'] if event['event_type'] == 'execution_completed')
        proof = observation['stage_proof'] = execution['owned_result_execution']
        specs = observation['specs']
        created = observation['created'] = {role: proof['identities'][specs[role]['request_path']] for role in ROLES}
        ids = {role: row['id'] for role, row in created.items()}
        assert len(set(ids.values())) == 3 and not set(ids.values()) & {OWNER, ANCESTOR, GUNS, CARS, CONTAINERS, RETAINED_CONTAINER, WINDOWS}, created
        assert execution['result'] == proof['stages'][0]['dispatch_result']['result'] and len(proof['stages']) == 3, proof
        assert all(stage['uri'] == SET and stage['dispatch_result']['ok'] is True for stage in proof['stages']), proof
        packet_paths = observation['stage_packet_paths'] = []
        for stage in proof['stages']:
            packet = Path(stage['dispatch_result']['evidence_path'])
            assert packet.parent.resolve() == evidence_root.resolve() and packet not in previous, stage
            native = json.loads(packet.read_bytes())
            assert native['api'] == SET and native['version'] == runtime.version and native['ok'] is True, native
            assert native['result'] == stage['dispatch_result']['result'], native
            packet_paths.append(str(packet))
        assert len(set(packet_paths)) == 3, packet_paths
        first, second, reference = proof['stages']
        assert first['args']['objects'][0]['object'] == OWNER and first['args']['objects'][0]['children'][0]['name'] == 'Guns', first
        assert second['args']['objects'][0]['object'] == CONTAINERS, second
        sound = second['args']['objects'][0]['children'][0]
        assert sound['name'] == REQUESTED['sound'] and sound['@Metadata'] == [{'type': 'MetadataSlot', 'name': REQUESTED['slot']}], second
        assert '@OutputBus' not in sound, second
        assert reference['args'] == {'objects': [{'object': ids['sound'], 'platform': WINDOWS, '@OutputBus': created['bus']['path']}]}, reference
        assert proof['creation_bindings'][1]['before_readbacks'] and all(row['passed'] for row in proof['creation_bindings'][1]['before_preservation']), proof
        membership_reads = [row for row in proof['creation_bindings'][1]['readbacks'] if row['options'] == {'return': ['id', '@Metadata']}]
        assert membership_reads, proof
        for row in membership_reads:
            owner, = row['result']['return']
            assert owner['id'].upper() == ids['sound'].upper(), row
            members = owner['@Metadata']
            assert isinstance(members, list) and len(members) == 1, row
            member_ids = [member['id'] for member in members]
            assert all(isinstance(identity, str) and uuid.UUID(identity).int != 0 for identity in member_ids), row
            assert [identity.upper() for identity in member_ids] == [ids['slot'].upper()], row
        after = observation['after'] = scope('after')
        assert all(after[key] == before[key] for key in ('owner', 'ancestor', 'containers')), after
        for role, identity in (('buses', GUNS), ('buses', CARS), ('children', RETAINED_CONTAINER)):
            assert next(row for row in after[role] if row['id'] == identity) == next(row for row in before[role] if row['id'] == identity), after
        assert {row['id'] for row in after['buses']} == {GUNS, CARS, ids['bus']}, after
        assert {row['id'] for row in after['children']} == {RETAINED_CONTAINER, ids['sound']}, after
        independent = {'bus': next(row for row in after['buses'] if row['id'] == ids['bus']),
            'sound': exact('source-sound-reference', ids['sound'], reference=True)}
        assert independent['sound']['references']['OutputBus']['id'] == ids['bus'], independent
        assert query('source-sound-children', ['--exact-id', ids['sound'], '--relationship', 'children', *projection], 2) == []
        gateway.gateway(['query-schema', '--advanced'], live=False)
        slots = query('source-metadata-members', ['--advanced-waql', f'from object "{ids["sound"]}" select @Metadata',
            *projection, '--include', 'owner'], 2)
        slot, = slots
        assert slot['id'] == ids['slot'] and slot['class_id'] == 5570560 and slot['owner']['id'] == ids['sound'], slot
        independent['slot'] = slot
        observation['independent_created'] = independent
        business = phase['verify']['agent_result']['business_result']
        roster = {row['result_handle']: row for row in business['created_objects']}
        assert business['configuration_complete'] is True and business['identity_source'] == 'independently_verified_creation_occurrences', business
        assert len(business['created_objects']) == len(roster) == 3 and set(roster) == set(handles.values()), roster
        for role, handle in handles.items():
            actual, row = independent[role], roster[handle]
            assert row['object'] == {key: actual[key] for key in ('id', 'name', 'type', 'path')}, row
            assert row['class_id'] == CLASSES[role] and row['requested_name'] == REQUESTED[role], row
            assert row['request_path'] == specs[role]['request_path'], row
            if role == 'slot':
                assert row['owner_id'] == ids['sound'] and row['list_name'] == 'Metadata' and 'parent_id' not in row, row
            else:
                parent = OWNER if role == 'bus' else CONTAINERS
                assert row['parent_id'] == parent == actual['parent']['id'], row
                assert actual['path'] == (OWNER_PATH if role == 'bus' else CONTAINERS_PATH) + '\\' + actual['name'], row
        assert len(observation['reads']) == 15 and len(observation['transactions']) == 1
        observation.update(complete=True, business_effect_verified=True)
        category['status'] = 'PASS'
    except BaseException as exc:
        observation['failure'] = {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        try:
            packets = sorted(set(evidence_root.glob('*.json')) - previous)
            assert len(packets) <= 512
            total = 0
            actual_sets = []
            for packet in packets:
                body = packet.read_bytes()
                total += len(body)
                assert total <= 32 * 1024 * 1024
                native = json.loads(body)
                assert not native.get('api', '').startswith('ak.wwise.core.undo.'), native
                if native.get('api') == SET:
                    actual_sets.append(str(packet))
                observation['native_evidence'].append({'path': str(packet), 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()})
            if observation['complete']:
                assert set(actual_sets) == set(observation['stage_packet_paths']) and len(actual_sets) == 3, actual_sets
        except BaseException as exc:
            observation.update(complete=False, business_effect_verified=False, collection_failure={'type': type(exc).__name__, 'message': str(exc)})
            category['status'] = 'FAIL'
            raise
        finally:
            try:
                retain()
                category.update(observation_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                    business_effect_verified=observation['complete'] and observation['business_effect_verified'])
            except BaseException:
                category.update(status='FAIL', business_effect_verified=False)
                category.pop('observation_sha256', None)
                raise
