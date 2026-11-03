"""Bounded empirical WHERE-token proof; no production grammar or value RETURN."""
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
from wwise_waapi.canonical import canonical_sha256


pytestmark = [pytest.mark.live, pytest.mark.destructive,
    pytest.mark.skipif(os.environ.get('WWISE_VERSION') != '2025.1',
        reason='Initial namespaced-token witness is selected for2025.1.7.9143 only')]
SOURCE, _ = official_sources()  # Immutable SDK provenance checked before startup.


@pytest.mark.parametrize('workflow_sandbox_runtime', [PROFILE], indirect=True)
def test_namespaced_custom_property_where_uses_native_membership(workflow_sandbox_runtime, monkeypatch):
    runtime = workflow_sandbox_runtime
    assert runtime.version == '2025.1'
    live = runtime.sandbox.metadata.get_info_version
    assert tuple(live[key] for key in ('year', 'major', 'minor', 'build')) == BUILDS[runtime.version]
    output = runtime.state_dir / 'query-namespaced-property.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    assert not output.exists()
    evidence_root = Path(runtime.env['WWISE_EVIDENCE_DIR'])
    observation = {'candidate': runtime.candidate, 'version': runtime.version, 'read_only': True,
        'sources': SOURCE, 'fixture': runtime.namespaced_query_prelaunch,
        'candidate_status': 'source-grounded @/@@PROPERTY_NAME substitution; native acceptance unproven until this attempt',
        'custom_return_proof': False, 'override_difference_proof': False,
        'reads': [], 'business_effect_verified': False}
    category = {'category': 'query-namespaced-property-where', 'status': 'FAIL',
        'verifier_strength': 'fresh_actual_metadata_official_default_nonassignment_and_native_positive_negative_membership',
        'observation_path': str(output)}
    runtime.category_results.append(category)
    status, continuation_count = 'FAIL', 0
    original_dispatch = waapi_gateway.WwiseDispatcher.dispatch

    def read(label, argv):
        nonlocal continuation_count
        assert len(observation['reads']) < 9
        record = {'label': label, 'invocations': []}
        observation['reads'].append(record)
        entries, encoding, offset, initial_calls, packets = [], None, 0, None, {}
        while True:
            before = set(evidence_root.glob('*.json'))
            calls = []
            invocation = {'argv': list(argv), 'dispatch_calls': calls, 'native_packets': []}
            record['invocations'].append(invocation)
            def capture(dispatcher, api, **kwargs):
                assert len(calls) < 128
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
                assert call['ok'] is packet['ok']
                assert canonical_sha256(packet['result']) == call['result_sha256']
            # First native rejection stops this attempt; never guess another spelling.
            assert code == 0 and payload.get('ok') is True, payload
            assert list(payload)[-1] == 'agent_result'
            if initial_calls is None: initial_calls = calls
            value = payload['agent_result']
            if not isinstance(value, dict) or 'entries_encoding' not in value:
                assert not entries and payload.get('projection_complete') is not False
                return value, initial_calls, packets
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
        return _page_value(entries, encoding)['objects'], initial_calls, packets

    def native_query(calls, packets, expression):
        matches = [call for call in calls if call['api'] == 'ak.wwise.core.object.get'
            and (call['args'] or {}).get('waql') == expression + ' take 1']
        assert len(matches) == 1, (expression, calls)
        call, = matches
        assert call['options']['return'] == ['id', 'name', 'type', 'path']
        return packets[call['evidence_path']]['result']['return']

    try:
        fixture = runtime.namespaced_query_prelaunch
        assert fixture['profile'] == PROFILE and fixture['native_acceptance'] is False
        assert sha(read_file(runtime.sandbox.sandbox_path / TARGET, 2048)) == DEFINITION_SHA
        observation['source_before'] = source_sound_frame(runtime.sandbox)
        assert observation['source_before'] == fixture['source_wwu']
        code, schema = runtime.raw_gateway(['query-schema', '--advanced'])
        observation['advanced_schema'] = schema
        assert code == 0 and schema['query_layer'] == 'advanced-native-waql'
        assert schema['boundary']['fixed_api'] == 'ak.wwise.core.object.get'
        assert schema['boundary']['gateway_appends_final_take'] is True
        baseline, calls, packets = read('exact-sound-before',
            ['query-object', '--exact-id', SOUND, '--max-results', '1', '--include', 'class-id'])
        sound, = baseline
        assert sound['id'] == SOUND and sound['type'] == 'Sound'
        assert sound['name'] == fixture['source_wwu']['sound_name']
        discovered, calls, packets = read('fresh-actual-custom-property-metadata',
            ['metadata', 'discover', '--exact-id', SOUND, '--meaning', TOKEN])
        candidates = [row for row in discovered['candidates'] if row['name'] == TOKEN]
        assert len(candidates) == 1
        names, infos = [], []
        for call in calls:
            args = call['args'] or {}
            if call['api'].endswith(('getPropertyInfo', 'getPropertyAndReferenceNames')):
                scope = {key: args[key] for key in ('classId', 'object') if key in args}
                assert scope in ({'classId': sound['class_id']}, {'object': SOUND}), scope
                result = packets[call['evidence_path']]['result']
                if call['api'].endswith('getPropertyAndReferenceNames'):
                    names.append(result['return'])
                elif args.get('property') == TOKEN:
                    assert result['name'] == TOKEN and result['type'] in {'int16', 'int32'}
                    assert type(result.get('default')) is int and result['default'] == 0
                    restriction = result['restriction']
                    assert restriction['type'] == 'enum'
                    values = [row['value'] for row in restriction['values']]
                    assert len(values) == 3 and all(type(value) is int for value in values) and set(values) == {0, 1, 2}
                    infos.append({'scope': scope, 'packet': call['evidence_path'], 'metadata': result})
        assert any(TOKEN in row for row in names) and infos
        observation['baseline'] = {'sound': sound, 'fresh_metadata': infos,
            'expected_value': 0, 'expected_value_authority': fixture['expected_value_authority']}
        observation['native_membership'] = []
        for mode, prefix in (('ordinary', '@'), ('override-source-value', '@@')):
            for value in (0, 1):
                expression = f'from object "{SOUND}" where {prefix}{TOKEN} = {value}'
                rows, calls, packets = read(f'{mode}-equals-{value}',
                    ['query-object', '--advanced-waql', expression, '--max-results', '1'])
                native = native_query(calls, packets, expression)
                expected = [SOUND] if value == 0 else []
                assert [row['id'] for row in rows] == [row['id'] for row in native] == expected
                for row in native:
                    assert {key: row[key] for key in ('id', 'name', 'type', 'path')} == {
                        key: sound[key] for key in ('id', 'name', 'type', 'path')}
                observation['native_membership'].append({'mode': mode, 'constant': value,
                    'expression': expression, 'selected_ids': expected})
        after, _, _ = read('exact-sound-after',
            ['query-object', '--exact-id', SOUND, '--max-results', '1', '--include', 'class-id'])
        assert after == baseline
        observation['source_after'] = source_sound_frame(runtime.sandbox)
        assert observation['source_after'] == observation['source_before']
        assert sha(read_file(runtime.sandbox.sandbox_path / TARGET, 2048)) == DEFINITION_SHA
        assert len(observation['native_membership']) == 4
        observation['candidate_status'] = 'matching2025 native positive/negative membership accepted both token modes'
        observation['business_effect_verified'] = True
        status = 'PASS'
    except BaseException as exc:
        observation['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        body = json.dumps(observation, ensure_ascii=False, indent=2).encode()
        bounded = len(body) <= 24 * 1024 * 1024
        if not bounded:
            status = 'FAIL'; observation['business_effect_verified'] = False
            observation['finalization_error'] = 'Observation exceeded24MiB; retained without truncation'
            body = json.dumps(observation, ensure_ascii=False, indent=2).encode()
        output.write_bytes(body)
        category.update(status=status, observation_sha256=hashlib.sha256(body).hexdigest(),
            business_effect_verified=observation['business_effect_verified'])
        assert bounded, 'Finalized observation exceeded24MiB; evidence retained without native PASS'
