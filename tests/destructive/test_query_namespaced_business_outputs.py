"""Closed namespaced root/related outputs with genuine typed native values."""
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from tests.destructive.support.namespaced_query_fixture import (
    PROFILE, TOKEN, SOUND, TARGET, DEFINITION_SHA, official_sources, source_sound_frame,
)
from tests.destructive.support.source_copy_fixture import read_file, sha
from tests.destructive.test_gateway_workflow_transaction_matrix import workflow_sandbox_runtime, waapi_gateway
from tests.destructive.test_query_list_sequences import BUILDS, READ_APIS, _page_value
from wwise_waapi.canonical import canonical_json_bytes, canonical_sha256


pytestmark = [pytest.mark.live, pytest.mark.destructive,
    pytest.mark.skipif(os.environ.get('WWISE_VERSION') != '2025.1',
        reason='Public namespaced output acceptance is selected for2025.1.7.9143 only')]
SOURCE, _ = official_sources()
IDENTITY = ('id', 'name', 'type', 'path')
AUDIO_SOURCE = '{806D447C-2AC4-4A6C-89DB-9D6DAFA7B5CF}'
CONTAINER = '{D5594A4B-DDB0-47F3-AC2F-08F104C72438}'


@pytest.mark.parametrize('workflow_sandbox_runtime', [PROFILE], indirect=True)
def test_namespaced_property_outputs_preserve_actual_related_values(workflow_sandbox_runtime, monkeypatch):
    runtime = workflow_sandbox_runtime
    assert runtime.version == '2025.1'
    live = runtime.sandbox.metadata.get_info_version
    assert tuple(live[key] for key in ('year', 'major', 'minor', 'build')) == BUILDS[runtime.version]
    output = runtime.state_dir / 'query-namespaced-business-outputs.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    assert not output.exists()
    evidence_root = Path(runtime.env['WWISE_EVIDENCE_DIR'])
    observation = {'candidate': runtime.candidate, 'version': runtime.version, 'read_only': True,
        'sources': SOURCE, 'fixture': runtime.namespaced_query_prelaunch,
        'scope': 'closed root/singleton/selected-list property outputs; actual native values, not condition replay',
        'typed_custom_return_proof': False, 'override_difference_proof': False,
        'reads': [], 'business_effect_verified': False}
    category = {'category': 'query-namespaced-business-outputs', 'status': 'FAIL',
        'verifier_strength': 'actual_endpoint_metadata_native_typed_root_chain_and_member_values_with_public_output_groups',
        'observation_path': str(output)}
    runtime.category_results.append(category)
    status, continuation_count, dispatch_count = 'FAIL', 0, 0
    original_dispatch = waapi_gateway.WwiseDispatcher.dispatch

    def read(label, argv):
        nonlocal continuation_count, dispatch_count
        assert len(observation['reads']) < 7
        record = {'label': label, 'invocations': []}
        observation['reads'].append(record)
        entries, encoding, offset, initial_calls, initial_payload, packets = [], None, 0, None, None, {}
        while True:
            before = set(evidence_root.glob('*.json'))
            calls = []
            invocation = {'argv': list(argv), 'dispatch_calls': calls, 'native_packets': []}
            record['invocations'].append(invocation)
            def capture(dispatcher, api, **kwargs):
                nonlocal dispatch_count
                assert dispatch_count < 128
                dispatch_count += 1
                call = {'api': api, **copy.deepcopy({key: kwargs.get(key) for key in ('version', 'args', 'options')})}
                calls.append(call)
                result = original_dispatch(dispatcher, api, **kwargs)
                call.update(ok=result['ok'], evidence_path=result.get('evidence_path'),
                    result_sha256=canonical_sha256(result.get('result')))
                return result
            with monkeypatch.context() as patch:
                patch.setattr(waapi_gateway.WwiseDispatcher, 'dispatch', capture)
                code, payload = (runtime.raw_gateway(argv) if initial_calls is None
                    else waapi_gateway.execute_gateway(argv, env=runtime.env))
            invocation.update(exit_code=code, payload=payload)
            paths = sorted(set(evidence_root.glob('*.json')) - before)
            assert len(paths) <= 128
            total = 0
            for path in paths:
                body = read_file(path, 8 * 1024 * 1024); total += len(body)
                assert total <= 8 * 1024 * 1024
                invocation['native_packets'].append({'path': str(path), 'bytes': len(body), 'sha256': sha(body)})
                packet = json.loads(body)
                assert packet['api'] in READ_APIS, packet
                packets[str(path)] = packet
            assert {call['evidence_path'] for call in calls} == {str(path) for path in paths}
            for call in calls:
                packet = packets[call['evidence_path']]
                assert call['api'] == packet['api'] and call['version'] == runtime.version
                assert call['ok'] is packet['ok'] and call['ok'] is True
                assert canonical_sha256(packet['result']) == call['result_sha256']
            assert code == 0 and payload.get('ok') is True, payload
            assert list(payload)[-1] == 'agent_result'
            if initial_calls is None: initial_calls, initial_payload = calls, payload
            value = payload['agent_result']
            if not isinstance(value, dict) or 'entries_encoding' not in value:
                assert not entries and payload.get('projection_complete') is not False
                return value, initial_calls, packets, initial_payload
            if encoding is None: encoding = value['entries_encoding']
            assert encoding in {'json-document-fragments', 'json-pointer-entries'}
            assert encoding == value['entries_encoding'] and value['page']['offset'] == offset
            entries.extend(value['entries']); offset += len(value['entries'])
            assert value['page']['next_offset'] == offset
            if value['projection_complete']: break
            assert continuation_count < 4, 'Delivery exceeded approved continuation bound; no retry'
            continuation_count += 1
            argv = value['next_command']['gateway_argv']
            assert 'query-object' in argv and '--result-query' in argv and '--result-page' in argv
        return _page_value(entries, encoding)['objects'], initial_calls, packets, initial_payload

    def metadata(calls, packets, sound, selected_scopes=None):
        names, infos, insufficient = [], [], []
        for call in calls:
            if not call['api'].endswith(('getPropertyInfo', 'getPropertyAndReferenceNames')): continue
            args = call['args'] or {}
            scope = {key: args[key] for key in ('classId', 'object') if key in args}
            assert scope in ({'classId': sound['class_id']}, {'object': SOUND}), scope
            result = packets[call['evidence_path']]['result']
            if call['api'].endswith('getPropertyAndReferenceNames'):
                names.append({'scope': scope, 'names': result['return']})
            elif args.get('property') == TOKEN:
                assert result['name'] == TOKEN
                row = {'scope': scope, 'packet': call['evidence_path'], 'metadata': result}
                if result.get('type') not in {'int16', 'int32'}:
                    insufficient.append(row); continue  # Unknown class kind may require actual-object fallback.
                assert type(result.get('default')) is int and result['default'] == 0
                restriction = result['restriction']; assert restriction['type'] == 'enum'
                values = [item['value'] for item in restriction['values']]
                assert len(values) == 3 and all(type(value) is int for value in values) and set(values) == {0, 1, 2}
                infos.append(row)
        assert infos
        for scope in selected_scopes or [row['scope'] for row in infos]:
            assert any(row['scope'] == scope and TOKEN in row['names'] for row in names)
            assert any(row['scope'] == scope for row in infos)
        return {'fresh_typed_fields': infos, 'insufficient_class_observations': insufficient}

    def public_values(row):
        for group in ('properties', 'override_source_values'):
            assert isinstance(row.get(group), dict) and TOKEN in row[group], row
            assert set(row[group]) == {TOKEN}
            assert type(row[group][TOKEN]) is int and row[group][TOKEN] == 0

    def native_identity(row, expected):
        assert {key: row[key] for key in IDENTITY} == {key: expected[key] for key in IDENTITY}
        assert row['classId'] == expected['class_id']

    def scalar_packets(calls, packets, expected, fields):
        values = []
        for index, call in enumerate(calls):
            if call['api'] != 'ak.wwise.core.object.get' or not set(fields) <= set(call['options']['return']): continue
            raw, = packets[call['evidence_path']]['result']['return']
            native_identity(raw, expected)
            for field in fields:
                assert field in raw and type(raw[field]) is int and raw[field] == 0
            values.append({'index': index, 'packet': call['evidence_path'],
                'native_query': call['args']['waql'], 'values': {field: raw[field] for field in fields}})
        assert values, (fields, calls)
        return values

    def selected_metadata(calls, packets, payload, sound):
        proof = payload['related_scope_binding']
        scopes = []
        for selection in proof['scopes']:
            assert selection['selected'] == {'name': TOKEN, 'kind': 'property'} and selection['complete'] is True
            scopes.append(selection['scope'])
        assert scopes
        return proof, metadata(calls, packets, sound, scopes)

    root_argv = ['query-object', '--exact-id', SOUND, '--max-results', '1', '--include', 'class-id',
        '--include', 'parent', '--include-field', TOKEN, '--include-override-source-value', TOKEN, '--detail']
    try:
        fixture = runtime.namespaced_query_prelaunch
        assert fixture['profile'] == PROFILE and fixture['native_acceptance'] is False
        assert sha(read_file(runtime.sandbox.sandbox_path / TARGET, 2048)) == DEFINITION_SHA
        observation['source_before'] = source_sound_frame(runtime.sandbox)
        assert observation['source_before'] == fixture['source_wwu']
        code, schema = runtime.raw_gateway(['query-schema'])
        observation['business_schema'] = schema
        assert code == 0
        assert schema['field_conditions']['namespaced_properties']['related_property_output_modes'] == ['ordinary', 'override-source-value']
        modes = schema['related_outputs']['custom_terminal_modes']
        assert modes['--include-related-field']['property'] == {'native_prefix': '@', 'output_group': 'properties'}
        assert modes['--include-related-override-source-value']['property'] == {'native_prefix': '@@', 'output_group': 'override_source_values'}
        sound_rows, _, _, _ = read('exact-sound-before', ['query-object', '--exact-id', SOUND,
            '--max-results', '1', '--include', 'class-id', '--include', 'parent'])
        sound, = sound_rows
        assert sound['id'] == SOUND and sound['type'] == 'Sound' and sound['name'] == fixture['source_wwu']['sound_name']
        assert sound['parent']['id'] == CONTAINER and sound['parent']['name'] == 'FS_Concrete'
        source_rows, _, _, _ = read('exact-source-before', ['query-object', '--exact-id', AUDIO_SOURCE,
            '--max-results', '1', '--include', 'class-id', '--include', 'parent'])
        source, = source_rows
        assert source['id'] == AUDIO_SOURCE and source['type'] == 'AudioFileSource' and source['name'] == sound['name']
        assert source['parent']['id'] == SOUND and source['parent']['name'] == sound['name']
        for row in (sound, source):
            assert all(isinstance(row[key], str) and row[key] for key in IDENTITY)
            assert type(row['class_id']) is int
        discovered, calls, packets, _ = read('fresh-actual-custom-property-metadata',
            ['metadata', 'discover', '--exact-id', SOUND, '--meaning', TOKEN])
        candidate, = [row for row in discovered['candidates'] if row['name'] == TOKEN]
        assert candidate['kind'] == 'property'
        observation['baseline'] = {'sound': sound, 'source': source, 'fresh_metadata': metadata(calls, packets, sound),
            'expected_value_authority': fixture['expected_value_authority']}
        roots, calls, packets, _ = read('root-property-outputs-before', root_argv)
        root, = roots
        public_values(root)
        assert {key: root[key] for key in sound} == sound
        observation['reads'][-1]['proof'] = {'typed_native_values': scalar_packets(calls, packets, sound, ['@' + TOKEN, '@@' + TOKEN]),
            'fresh_metadata': metadata(calls, packets, sound)}
        singleton, calls, packets, payload = read('singleton-parent-property-outputs',
            ['query-object', '--exact-id', AUDIO_SOURCE, '--max-results', '1', '--include', 'class-id',
                '--include-related-field', 'parent', TOKEN, '--include-related-override-source-value', 'parent', TOKEN, '--detail'])
        row, = singleton
        assert {key: row[key] for key in (*IDENTITY, 'class_id')} == {key: source[key] for key in (*IDENTITY, 'class_id')}
        parent = row['related']['parent']
        assert parent['object'] == source['parent']
        public_values(parent)
        typed = scalar_packets(calls, packets, source, ['parent.@' + TOKEN, 'parent.@@' + TOKEN])
        assert len(typed) == 1  # Existing singleton planner observes scope, then final typed values once.
        scope_before = []
        for index, call in enumerate(calls):
            if call['api'] == 'ak.wwise.core.object.get' and index < typed[0]['index']:
                raw, = packets[call['evidence_path']]['result']['return']
                assert {key: raw[key] for key in IDENTITY} == {key: source[key] for key in IDENTITY}
                assert raw['parent'] == source['parent'] and raw['parent.classId'] == sound['class_id']
                scope_before.append(call['evidence_path'])
        assert scope_before
        for value in typed:
            raw, = packets[value['packet']]['result']['return']
            assert raw['parent'] == source['parent'] and raw['parent.classId'] == sound['class_id']
        proof, fresh = selected_metadata(calls, packets, payload, sound)
        observation['reads'][-1]['proof'] = {'typed_native_values': typed, 'parent_scope_before_packets': scope_before,
            'fresh_metadata': fresh, 'business_scope': proof}
        selected, calls, packets, payload = read('selected-child-property-outputs',
            ['query-object', '--exact-id', CONTAINER, '--max-results', '1', '--include', 'class-id',
                '--include-related-field', 'children', 'matching', 'name-is', sound['name'], TOKEN,
                '--include-related-override-source-value', 'children', 'matching', 'name-is', sound['name'], TOKEN, '--detail'])
        owner, = selected
        assert owner['id'] == CONTAINER and owner['type'] == 'RandomSequenceContainer' and owner['name'] == sound['parent']['name']
        view, = owner['related']['projections']  # Both modes share this one selected sequence.
        assert view['spec'] == {'source': 'children', 'stages': [{'selection': 'matching', 'condition': 'name-is', 'value': sound['name']}]}
        item, = view['items']
        assert item['object'] == {key: sound[key] for key in IDENTITY}
        public_values(item)
        # Sequence selection uses current planner's GUID member reads, never an invented chained RETURN.
        typed = scalar_packets(calls, packets, sound, ['@' + TOKEN, '@@' + TOKEN])
        roots_at = [index for index, call in enumerate(calls) if call['api'] == 'ak.wwise.core.object.get'
            and (call['args'] or {}).get('waql') == f'from object "{CONTAINER}" take 1']
        assert roots_at
        final_root = max(roots_at)
        assert any(value['index'] < final_root for value in typed) and any(value['index'] > final_root for value in typed)
        memberships = []
        prefix = f'from object "{CONTAINER}" select children where name = "{sound["name"]}" take '
        for index, call in enumerate(calls):
            expression = (call['args'] or {}).get('waql', '')
            if call['api'] != 'ak.wwise.core.object.get' or not expression.startswith(prefix): continue
            count = expression[len(prefix):]
            assert count.isascii() and count.isdecimal() and int(count) > 1
            raw = packets[call['evidence_path']]['result']['return']
            assert len(raw) == 1 < int(count)
            assert {key: raw[0][key] for key in IDENTITY} == {key: sound[key] for key in IDENTITY}
            memberships.append({'index': index, 'packet': call['evidence_path'], 'selected_ids': [raw[0]['id']]})
        assert any(value['index'] < final_root for value in memberships) and any(value['index'] > final_root for value in memberships)
        for value in typed:
            assert value['native_query'] in {f'from object "{SOUND}"', f'from object "{SOUND}" take 1'}
        proof, fresh = selected_metadata(calls, packets, payload, sound)
        assert proof['sequence_semantics'].startswith('Gateway business derivation')
        for association in proof['read_associations']:
            assert any(all(canonical_json_bytes(call[key]) == canonical_json_bytes(association[key])
                for key in ('api', 'args', 'options', 'result_sha256')) for call in calls), association
        observation['reads'][-1]['proof'] = {'typed_native_member_values': typed, 'final_root_index': final_root,
            'selected_ids': [item['object']['id']], 'complete_native_memberships': memberships,
            'fresh_metadata': fresh, 'business_scope': proof}
        repeated, calls, packets, _ = read('root-property-outputs-after', root_argv)
        assert canonical_json_bytes(repeated) == canonical_json_bytes(roots)
        observation['reads'][-1]['proof'] = {'typed_native_values': scalar_packets(calls, packets, sound, ['@' + TOKEN, '@@' + TOKEN]),
            'fresh_metadata': metadata(calls, packets, sound)}
        observation['source_after'] = source_sound_frame(runtime.sandbox)
        assert observation['source_after'] == observation['source_before']
        assert sha(read_file(runtime.sandbox.sandbox_path / TARGET, 2048)) == DEFINITION_SHA
        assert len(observation['reads']) == 7
        observation['typed_custom_return_proof'] = True
        observation['business_effect_verified'] = True
        observation['dispatch_count'] = dispatch_count
        status = 'PASS'
    except BaseException as exc:
        observation['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        body = json.dumps(observation, ensure_ascii=False, indent=2).encode()
        bounded = len(body) <= 24 * 1024 * 1024
        if not bounded:
            status = 'FAIL'; observation['business_effect_verified'] = False
            observation['typed_custom_return_proof'] = False
            observation['finalization_error'] = 'Observation exceeded24MiB; retained without truncation'
            body = json.dumps(observation, ensure_ascii=False, indent=2).encode()
        output.write_bytes(body)
        category.update(status=status, observation_sha256=hashlib.sha256(body).hexdigest(),
            business_effect_verified=observation['business_effect_verified'])
        assert bounded, 'Finalized observation exceeded24MiB; retained without native PASS'
