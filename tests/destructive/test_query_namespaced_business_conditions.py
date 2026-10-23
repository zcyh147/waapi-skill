"""Closed public conditions with genuine typed value reads, separate from R82."""
import copy
import hashlib
import json
import os
import re
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
        reason='Public namespaced condition acceptance is selected for2025.1.7.9143 only')]
SOURCE, _ = official_sources()
IDENTITY = ('id', 'name', 'type', 'path')


@pytest.mark.parametrize('workflow_sandbox_runtime', [PROFILE], indirect=True)
def test_namespaced_closed_conditions_require_native_value_readback(workflow_sandbox_runtime, monkeypatch):
    runtime = workflow_sandbox_runtime
    assert runtime.version == '2025.1'
    live = runtime.sandbox.metadata.get_info_version
    assert tuple(live[key] for key in ('year', 'major', 'minor', 'build')) == BUILDS[runtime.version]
    output = runtime.state_dir / 'query-namespaced-business-conditions.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    assert not output.exists()
    evidence_root = Path(runtime.env['WWISE_EVIDENCE_DIR'])
    observation = {'candidate': runtime.candidate, 'version': runtime.version, 'read_only': True,
        'sources': SOURCE, 'fixture': runtime.namespaced_query_prelaunch,
        'scope': 'closed public ordinary/override conditions with native typed predicate-value readback; not an advanced-query replay',
        'typed_custom_return_proof': False, 'override_difference_proof': False,
        'reads': [], 'business_effect_verified': False}
    category = {'category': 'query-namespaced-business-conditions', 'status': 'FAIL',
        'verifier_strength': 'actual_metadata_complete_source_native_typed_value_before_after_and_public_selected_ids',
        'observation_path': str(output)}
    runtime.category_results.append(category)
    status, continuation_count = 'FAIL', 0
    original_dispatch = waapi_gateway.WwiseDispatcher.dispatch

    def read(label, argv):
        nonlocal continuation_count
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

    def trace(rows, calls, packets, payload, sound, field, constant):
        expected_query = f'from object "{SOUND}" where {field} = {constant} take 1'
        finals = [index for index, call in enumerate(calls) if call['api'] == 'ak.wwise.core.object.get'
            and (call['args'] or {}).get('waql') == expected_query]
        assert len(finals) == 1, (expected_query, calls)
        final, = finals
        chosen = calls[final]
        assert set(chosen['options']['return']) == {*IDENTITY, 'classId', field}
        selected = packets[chosen['evidence_path']]['result']['return']
        expected_ids = [SOUND] if constant == 0 else []
        assert [row['id'] for row in rows] == [row['id'] for row in selected] == expected_ids
        sources, values = [], []
        for index, call in enumerate(calls):
            if call['api'] != 'ak.wwise.core.object.get': continue
            expression = (call['args'] or {}).get('waql', '')
            if expression == 'from type Project take 1': continue
            assert expression.startswith(f'from object "{SOUND}"'), expression
            raw = packets[call['evidence_path']]['result']['return']
            for row in raw:
                assert {key: row[key] for key in IDENTITY} == {key: sound[key] for key in IDENTITY}
                assert row['classId'] == sound['class_id']
            if ' where ' in expression or ' select ' in expression: continue
            # Existing value reads are bounded by one explicit GUID and may
            # omit take. Separate complete-source scans retain their own take.
            match = re.fullmatch(r'from object "' + re.escape(SOUND) + r'"(?: take ([1-9][0-9]*))?', expression)
            assert match and len(raw) == 1
            if match.group(1) is not None and len(raw) < int(match.group(1)): sources.append(index)
            if field in call['options']['return']:
                assert field in raw[0] and type(raw[0][field]) is int and raw[0][field] == 0
                values.append({'index': index, 'packet': call['evidence_path'], 'value': raw[0][field]})
        assert any(index < final for index in sources) and any(index > final for index in sources)
        assert any(row['index'] < final for row in values) and any(row['index'] > final for row in values)
        for row in selected:
            assert field in row and type(row[field]) is int and row[field] == 0
        for row in rows: assert row['class_id'] == sound['class_id']
        proof = payload['related_scope_binding']['root_field_conditions']
        assert proof['source_complete'] is True and proof['source_rows'] == 1
        assert proof['native_predicates'] == [f'where {field} = {constant}']
        scopes = []
        for selection in proof['scopes']:
            assert selection['selected'] == {'name': TOKEN, 'kind': 'property'} and selection['complete'] is True
            scopes.append(selection['scope'])
        fresh = metadata(calls, packets, sound, scopes)
        observation['reads'][-1]['proof'] = {'final_packet': chosen['evidence_path'],
            'native_query': expected_query, 'selected_ids': expected_ids, 'typed_value_observations': values,
            'fresh_metadata': fresh, 'complete_source_before_after': True, 'business_scope': proof}

    try:
        fixture = runtime.namespaced_query_prelaunch
        assert fixture['profile'] == PROFILE and fixture['native_acceptance'] is False
        assert sha(read_file(runtime.sandbox.sandbox_path / TARGET, 2048)) == DEFINITION_SHA
        observation['source_before'] = source_sound_frame(runtime.sandbox)
        assert observation['source_before'] == fixture['source_wwu']
        code, schema = runtime.raw_gateway(['query-schema'])
        observation['business_schema'] = schema
        assert code == 0 and schema['field_conditions']['namespaced_properties']['source']['version'] == '2025.1'
        baseline, _, _, _ = read('exact-sound-before',
            ['query-object', '--exact-id', SOUND, '--max-results', '1', '--include', 'class-id'])
        sound, = baseline
        assert sound['id'] == SOUND and sound['type'] == 'Sound' and sound['name'] == fixture['source_wwu']['sound_name']
        discovered, calls, packets, _ = read('fresh-actual-custom-property-metadata',
            ['metadata', 'discover', '--exact-id', SOUND, '--meaning', TOKEN])
        candidates = [row for row in discovered['candidates'] if row['name'] == TOKEN]
        candidate, = candidates
        meaning = candidate['name']  # Exact freshly disclosed token; no display-name ambiguity in this witness.
        observation['baseline'] = {'sound': sound, 'fresh_metadata': metadata(calls, packets, sound),
            'expected_value_authority': fixture['expected_value_authority']}
        for mode, prefix in (('ordinary', '@'), ('override-source-value', '@@')):
            for constant in (0, 1):
                rows, calls, packets, payload = read(f'{mode}-equals-{constant}',
                    ['query-object', '--exact-id', SOUND, '--max-results', '1', '--where-field',
                        mode, meaning, 'is', str(constant), '--include', 'class-id', '--detail'])
                trace(rows, calls, packets, payload, sound, prefix + meaning, constant)
        after, _, _, _ = read('exact-sound-after',
            ['query-object', '--exact-id', SOUND, '--max-results', '1', '--include', 'class-id'])
        assert canonical_json_bytes(after) == canonical_json_bytes(baseline)
        observation['source_after'] = source_sound_frame(runtime.sandbox)
        assert observation['source_after'] == observation['source_before']
        assert sha(read_file(runtime.sandbox.sandbox_path / TARGET, 2048)) == DEFINITION_SHA
        assert len(observation['reads']) == 7
        observation['typed_custom_return_proof'] = True
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
            observation['typed_custom_return_proof'] = False
            observation['finalization_error'] = 'Observation exceeded24MiB; retained without truncation'
            body = json.dumps(observation, ensure_ascii=False, indent=2).encode()
        output.write_bytes(body)
        category.update(status=status, observation_sha256=hashlib.sha256(body).hexdigest(),
            business_effect_verified=observation['business_effect_verified'])
        assert bounded, 'Finalized observation exceeded24MiB; retained without native PASS'
