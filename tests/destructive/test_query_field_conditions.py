"""Read-only scalar WHERE acceptance against an independent child baseline."""
import copy
import hashlib
import json
import re
from pathlib import Path

import pytest

from tests.destructive.test_gateway_workflow_transaction_matrix import workflow_sandbox_runtime, waapi_gateway
from tests.destructive.test_query_list_sequences import (
    CHILDREN, CONTAINER, BUILDS, DEFINITION_EVIDENCE, PINS, READ_APIS, REPO,
    _page_value, _projection, _spec, _wwu,
)
from wwise_waapi.canonical import canonical_json_bytes, canonical_sha256


pytestmark = [pytest.mark.live, pytest.mark.destructive]


def _condition_sources():
    """Check matching five-version WHERE evidence before fixture startup."""
    evidence = {}
    for version, (definition_sha, _) in PINS.items():
        path = REPO / 'skills/waapi-skill/references/semantic' / version / 'query-field-condition-sources.json'
        source = json.loads(path.read_text())
        assert source['version'] == version
        assert source['wwise_build'] == DEFINITION_EVIDENCE[version]['build']
        assert source['definitions_sha256'] == definition_sha
        assert source['domain'] == 'query-predicates-and-selection'
        for section in source['sections'].values():
            assert hashlib.sha256(section['html'].encode()).hexdigest() == section['html_sha256']
        assert 'When using @' in source['sections']['property_value']['html']
        assert 'Compares two numerical values' in source['sections']['comparison_operators']['html']
        evidence[version] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'definitions_sha256': definition_sha, 'page_sha256': source['page_sha256'],
            'sections_sha256': canonical_sha256(source['sections'])}
    return evidence


CONDITION_SOURCES = _condition_sources()


def test_scalar_conditions_keep_native_order_values_scope_and_root_limit(workflow_sandbox_runtime, monkeypatch):
    runtime = workflow_sandbox_runtime
    live = runtime.sandbox.metadata.get_info_version
    assert tuple(live[key] for key in ('year', 'major', 'minor', 'build')) == BUILDS[runtime.version]
    assert hashlib.sha256((runtime.sandbox.source_root / _wwu(runtime.version)).read_bytes()).hexdigest() == PINS[runtime.version][1]
    output = runtime.state_dir / 'query-field-conditions.json'
    assert not output.exists()
    evidence_root = Path(runtime.env['WWISE_EVIDENCE_DIR'])
    observation = {'candidate': runtime.candidate, 'version': runtime.version, 'read_only': True,
        'definitions': DEFINITION_EVIDENCE, 'condition_sources': CONDITION_SOURCES,
        'reads': [], 'business_effect_verified': False}
    category = {'category': 'query-field-conditions', 'status': 'FAIL',
        'verifier_strength': 'native_where_with_independent_order_guid_values_actual_metadata_and_complete_source',
        'observation_path': str(output)}
    runtime.category_results.append(category)
    status, continuation_count = 'FAIL', 0
    original_dispatch = waapi_gateway.WwiseDispatcher.dispatch

    def read(label, flags, *, maximum=16):
        nonlocal continuation_count
        assert len(observation['reads']) < 5
        argv = ['query-object', '--exact-id', CONTAINER, '--max-results', str(maximum), *flags]
        record = {'label': label, 'invocations': []}
        observation['reads'].append(record)
        entries, offset, encoding, initial_calls, packets = [], 0, None, None, {}
        while True:
            before = set(evidence_root.glob('*.json'))
            calls = []
            def capture(dispatcher, api, **kwargs):
                # Passive observation of genuine public Gateway dispatch. Copy
                # inputs before calling the original once; never modify its
                # inputs, result or transport, and return the exact same object.
                assert len(calls) < 128
                call = {'api': api, **copy.deepcopy({key: kwargs.get(key) for key in ('version', 'args', 'options')})}
                result = original_dispatch(dispatcher, api, **kwargs)
                call.update(ok=result['ok'], evidence_path=result.get('evidence_path'),
                    result_sha256=canonical_sha256(result.get('result')))
                calls.append(call)
                return result
            with monkeypatch.context() as patch:
                patch.setattr(waapi_gateway.WwiseDispatcher, 'dispatch', capture)
                # Returned complete argv already owns state/configuration. The
                # workflow convenience wrapper adds --timeout, so only initial
                # business commands use it; continuations execute verbatim.
                code, payload = (runtime.raw_gateway(argv) if initial_calls is None
                    else waapi_gateway.execute_gateway(argv, env=runtime.env))
            invocation = {'argv': argv, 'exit_code': code, 'payload': payload,
                'dispatch_calls': calls, 'native_packets': []}
            record['invocations'].append(invocation)
            paths = sorted(set(evidence_root.glob('*.json')) - before)
            assert len(paths) <= 128
            total = 0
            for path in paths:
                body = path.read_bytes(); total += len(body)
                assert total <= 8 * 1024 * 1024
                invocation['native_packets'].append({'path': str(path), 'bytes': len(body),
                    'sha256': hashlib.sha256(body).hexdigest()})
                packet = json.loads(body)
                assert packet['api'] in READ_APIS, packet
                packets[str(path)] = packet
            assert {call['evidence_path'] for call in calls} == {str(path) for path in paths}
            for call in calls:
                packet = packets[call['evidence_path']]
                assert call['api'] == packet['api'] and call['version'] == runtime.version
                assert call['ok'] is packet['ok']
                assert canonical_sha256(packet['result']) == call['result_sha256']
            assert code == 0 and payload.get('ok') is True, payload
            assert list(payload)[-1] == 'agent_result'
            if initial_calls is None: initial_calls = calls
            value = payload['agent_result']
            if isinstance(value, list):
                assert not entries and payload.get('projection_complete') is not False
                return value, initial_calls, packets
            # Exact established public query protocol, shared reconstruction
            # helper from the accepted sequence witness; no alternate decoder.
            assert isinstance(value, dict) and value['entries_encoding'] in {'json-document-fragments', 'json-pointer-entries'}, payload
            if encoding is None: encoding = value['entries_encoding']
            assert encoding == value['entries_encoding'] and value['page']['offset'] == offset
            entries.extend(value['entries']); offset += len(value['entries'])
            assert value['page']['next_offset'] == offset
            if value['projection_complete']: break
            assert continuation_count < 4, 'Unexpected delivery cost; retain evidence for Main to adjust grouping'
            continuation_count += 1
            argv = value['next_command']['gateway_argv']
            assert 'query-object' in argv and '--result-query' in argv and '--result-page' in argv
        restored = _page_value(entries, encoding)
        return restored['objects'], initial_calls, packets

    def trace(calls, packets, by_id, thresholds, *, root=False):
        """Associate actual dispatcher requests with immutable native packets."""
        assert calls
        first_paths = {row['path'] for row in observation['reads'][-1]['invocations'][0]['native_packets']}
        assert {row['evidence_path'] for row in calls} == first_paths
        seen_thresholds, metadata_scopes, full_sources, final = set(), [], [], []
        for index, call in enumerate(calls):
            assert call['api'] in READ_APIS and call['ok'] is True
            assert call['version'] == runtime.version
            packet = packets[call['evidence_path']]
            assert packet['ok'] is True and packet['api'] == call['api']
            assert canonical_sha256(packet['result']) == call['result_sha256']
            if call['api'].endswith('getPropertyInfo') and call['args']['property'] == 'Pitch':
                assert packet['result']['name'] == 'Pitch' and packet['result']['type'] == 'int32'
                scope = {key: call['args'][key] for key in ('classId', 'object') if key in call['args']}
                assert scope in ([{'classId': known['class_id']} for known in by_id.values()]
                    + [{'object': identity} for identity in by_id])
                metadata_scopes.append(scope)
            waql = (call['args'] or {}).get('waql', '')
            source = re.fullmatch(r'from object "' + re.escape(CONTAINER) + r'" select children take ([1-9][0-9]*)', waql)
            if root and source:
                rows = packet['result']['return']
                # A complete source witness must terminate below its real
                # requested native cap, not merely contain a plausible prefix.
                assert len(rows) == 5 < int(source.group(1))
                assert [row['id'] for row in rows] == list(by_id)
                assert set(row['id'] for row in rows) == CHILDREN
                for row in rows:
                    assert all(canonical_json_bytes(row[key]) == canonical_json_bytes(by_id[row['id']][business])
                        for key, business in (('id', 'id'), ('name', 'name'), ('type', 'type'), ('path', 'path'), ('classId', 'class_id')))
                full_sources.append(index)
            match = re.search(r'where @Pitch <= (-?\d+)(?: |$)', waql)
            if not match: continue
            threshold = int(match.group(1)); seen_thresholds.add(threshold)
            expected = [identity for identity, known in by_id.items() if known['pitch_cents'] <= threshold]
            requested = set(re.findall(r'"(\{[0-9A-Fa-f-]{36}\})"', waql.split(' where ')[0]))
            if ' select children' not in waql: expected = [identity for identity in expected if identity in requested]
            rows = packet['result']['return']
            if root:
                assert waql == f'from object "{CONTAINER}" select children where @Pitch <= {threshold} take 1'
                assert [row['id'] for row in rows] == expected[:1]
                final.append(index)
            else:
                assert {row['id'] for row in rows} == set(expected)
            for row in rows:
                assert row['id'] in expected
                assert canonical_json_bytes(row['@Pitch']) == canonical_json_bytes(by_id[row['id']]['pitch_cents'])
        assert metadata_scopes and seen_thresholds == set(thresholds)
        if root:
            assert len(final) == 1 and any(index < final[0] for index in full_sources)
            assert any(index > final[0] for index in full_sources), 'Complete post-query source revalidation must remain observable'
            # Every independent member must have an unfiltered exact value
            # observation before the final WHERE, with actual typed class/value.
            values_before = {}
            for call in calls[:final[0]]:
                waql = (call['args'] or {}).get('waql', '')
                if not waql.startswith('from object ') or ' where ' in waql or ' select ' in waql:
                    continue
                if not {'classId', '@Pitch'} <= set((call['options'] or {}).get('return', [])):
                    continue
                for row in packets[call['evidence_path']]['result']['return']:
                    assert row['id'] in by_id
                    assert canonical_json_bytes(row['classId']) == canonical_json_bytes(by_id[row['id']]['class_id'])
                    assert canonical_json_bytes(row['@Pitch']) == canonical_json_bytes(by_id[row['id']]['pitch_cents'])
                    values_before[row['id']] = row
            assert set(values_before) == CHILDREN

    def condition(threshold):
        return {'field_condition': {'mode': 'ordinary', 'meaning': 'Voice Pitch',
            'comparison': 'at-most', 'value': str(threshold)}}

    def spec(threshold, *, count=False):
        return _spec(stages=[{'selection': 'matching', **condition(threshold)}],
            reducer={'operation': 'count'} if count else None)

    try:
        baseline, calls, packets = read('independent-children', ['--relationship', 'children',
            '--include', 'volume-db', '--include', 'pitch-cents', '--include', 'class-id'])
        assert len(calls) == 1 and calls[0]['args']['waql'] == f'from object "{CONTAINER}" select children take 16'
        native = packets[calls[0]['evidence_path']]['result']['return']
        order = [row['id'] for row in native]
        assert len(order) == 5 and set(order) == CHILDREN
        assert [row['id'] for row in baseline] == order
        by_id = {row['id']: row for row in baseline}
        for row, raw in zip(baseline, native):
            assert row['type'] == raw['type'] == 'Sound'
            assert all(row[key] == raw[key] for key in ('id', 'name', 'type', 'path'))
            for business, field in (('volume_db', '@Volume'), ('pitch_cents', '@Pitch'), ('class_id', 'classId')):
                assert canonical_json_bytes(row[business]) == canonical_json_bytes(raw[field])
        assert {row['name'] for row in baseline} == {f'Footstep_Crouching_Concrete_{number:02d}' for number in range(1, 6)}
        expected = {threshold: [identity for identity in order if by_id[identity]['pitch_cents'] <= threshold] for threshold in (0, -1)}
        assert expected[0] and not expected[-1], 'Existing baseline must actually witness a nonempty and an empty condition'
        observation['independent_order'] = order
        observation['independent_values'] = by_id

        rows, calls, packets = read('related-matching-values-and-counts', [
            '--include-related', 'children', 'matching-field', 'ordinary', 'Voice Pitch', 'at-most', '0', 'volume-db',
            '--include-related-field', 'children', 'matching-field', 'ordinary', 'Voice Pitch', 'at-most', '0', 'Pitch',
            '--include-related', 'children', 'matching-field', 'ordinary', 'Voice Pitch', 'at-most', '0', 'count',
            '--include-related', 'children', 'matching-field', 'ordinary', 'Voice Pitch', 'at-most', '-1', 'count'])
        root, = rows
        assert root['id'] == CONTAINER and root['name'] == 'FS_Concrete'
        items = _projection(root, spec(0))['items']
        assert [item['object']['id'] for item in items] == expected[0]
        for item in items:
            known = by_id[item['object']['id']]
            assert all(item['object'][key] == known[key] for key in ('id', 'name', 'type', 'path'))
            assert canonical_json_bytes(item['volume_db']) == canonical_json_bytes(known['volume_db'])
            assert canonical_json_bytes(item['properties']['Pitch']) == canonical_json_bytes(known['pitch_cents'])
        for threshold in (0, -1):
            count = _projection(root, spec(threshold, count=True))['value']
            assert type(count) is int and count == len(expected[threshold])
        trace(calls, packets, by_id, (0, -1))

        rows, calls, packets = read('related-empty-keeps-root', ['--include-related', 'children',
            'matching-field', 'ordinary', 'Voice Pitch', 'at-most', '-1', 'volume-db'])
        root, = rows
        assert root['id'] == CONTAINER and root['name'] == 'FS_Concrete'
        assert _projection(root, spec(-1))['items'] == []
        trace(calls, packets, by_id, (-1,))

        for threshold in (0, -1):
            rows, calls, packets = read(f'root-filter-before-limit-{threshold}', ['--relationship', 'children',
                '--where-field', 'ordinary', 'Pitch', 'at-most', str(threshold), '--include', 'pitch-cents'], maximum=1)
            assert [row['id'] for row in rows] == expected[threshold][:1]
            for row in rows:
                assert canonical_json_bytes(row['pitch_cents']) == canonical_json_bytes(by_id[row['id']]['pitch_cents'])
            trace(calls, packets, by_id, (threshold,), root=True)
        assert len(observation['reads']) == 5
        observation['business_effect_verified'] = True
        status = 'PASS'
    except BaseException as exc:
        observation['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        body = json.dumps(observation, ensure_ascii=False, indent=2).encode('utf-8')
        assert len(body) <= 24 * 1024 * 1024
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(body)
        category.update(status=status, observation_sha256=hashlib.sha256(body).hexdigest())
