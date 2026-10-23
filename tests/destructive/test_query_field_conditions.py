"""Read-only scalar WHERE acceptance against an independent child baseline."""
import hashlib
import json
import re
from pathlib import Path

import pytest

from tests.destructive.test_gateway_workflow_transaction_matrix import workflow_sandbox_runtime
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


def test_scalar_conditions_keep_native_order_values_scope_and_root_limit(workflow_sandbox_runtime):
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

    def read(label, flags, *, maximum=16):
        nonlocal continuation_count
        assert len(observation['reads']) < 5
        argv = ['query-object', '--exact-id', CONTAINER, '--max-results', str(maximum), '--detail', *flags]
        record = {'label': label, 'invocations': []}
        observation['reads'].append(record)
        entries, offset, encoding, initial, packets = [], 0, None, None, {}
        while True:
            before = set(evidence_root.glob('*.json'))
            code, payload = runtime.raw_gateway(argv)
            invocation = {'argv': argv, 'exit_code': code, 'payload': payload, 'native_packets': []}
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
            assert code == 0 and payload.get('ok') is True, payload
            assert list(payload)[-1] == 'agent_result'
            if initial is None: initial = payload
            value = payload['agent_result']
            if isinstance(value, list):
                assert not entries and payload.get('projection_complete') is not False
                return value, initial, packets
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
        return restored['objects'], {**initial, **{key: value for key, value in restored.items() if key != 'objects'}}, packets

    def trace(detail, packets, by_id, thresholds, *, root=False):
        proof = detail['related_scope_binding']
        authority = proof['root_field_conditions'] if root else proof
        assert authority['mutation_authority'] is False
        selected = [row for row in authority['scopes'] if (row.get('selected') or {}).get('name') == 'Pitch']
        assert selected
        for selection in selected:
            assert selection['complete'] is True and selection['selected']['kind'] == 'property'
            assert selection['scope'] in ([{'classId': known['class_id']} for known in by_id.values()]
                + [{'object': identity} for identity in by_id])
        records = detail['related_read_evidence']
        assert records
        first_paths = {row['path'] for row in observation['reads'][-1]['invocations'][0]['native_packets']}
        descriptors = {canonical_sha256(row) for row in authority['read_associations']}
        seen_thresholds, metadata_witness = set(), False
        for row in records:
            assert canonical_sha256({key: row[key] for key in ('api', 'args', 'options', 'result_sha256')}) in descriptors
            path = row['call']['evidence_path']
            assert path in first_paths, 'Origin evidence must refer to the original invocation'
            packet = packets[path]
            assert packet['ok'] is True and packet['api'] == row['api']
            assert canonical_sha256(packet['result']) == row['result_sha256']
            if row['api'].endswith('getPropertyInfo') and row['args']['property'] == 'Pitch':
                assert packet['result']['name'] == 'Pitch' and packet['result']['type'] == 'int32'
                metadata_witness = True
            waql = row['args'].get('waql', '')
            match = re.search(r'where @Pitch <= (-?\d+)(?: |$)', waql)
            if not match: continue
            threshold = int(match.group(1)); seen_thresholds.add(threshold)
            expected = {identity for identity, known in by_id.items() if known['pitch_cents'] <= threshold}
            requested = set(re.findall(r'"(\{[0-9A-Fa-f-]{36}\})"', waql.split(' where ')[0]))
            if ' select children' not in waql: expected &= requested
            rows = packet['result']['return']
            # Related selected-ID reads have no final root cap. Root final
            # projection is checked separately against the independent order.
            if ' take 1' not in waql:
                assert {value['id'] for value in rows} == expected
            for value in rows:
                assert value['id'] in expected
                assert canonical_json_bytes(value['@Pitch']) == canonical_json_bytes(by_id[value['id']]['pitch_cents'])
        # Root final WHERE is the independently dispatched detail.call, outside
        # preparation's read_associations; verify it below rather than inventing
        # a helper-read association for that final packet.
        assert metadata_witness and seen_thresholds == (set() if root else set(thresholds))
        return authority

    def condition(threshold):
        return {'field_condition': {'mode': 'ordinary', 'meaning': 'Voice Pitch',
            'comparison': 'at-most', 'value': str(threshold)}}

    def spec(threshold, *, count=False):
        return _spec(stages=[{'selection': 'matching', **condition(threshold)}],
            reducer={'operation': 'count'} if count else None)

    try:
        baseline, detail, packets = read('independent-children', ['--relationship', 'children',
            '--include', 'volume-db', '--include', 'pitch-cents', '--include', 'class-id'])
        native = packets[detail['call']['evidence_path']]['result']['return']
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

        rows, detail, packets = read('related-matching-values-and-counts', [
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
        trace(detail, packets, by_id, (0, -1))

        rows, detail, packets = read('related-empty-keeps-root', ['--include-related', 'children',
            'matching-field', 'ordinary', 'Voice Pitch', 'at-most', '-1', 'volume-db'])
        root, = rows
        assert root['id'] == CONTAINER and root['name'] == 'FS_Concrete'
        assert _projection(root, spec(-1))['items'] == []
        trace(detail, packets, by_id, (-1,))

        for threshold in (0, -1):
            rows, detail, packets = read(f'root-filter-before-limit-{threshold}', ['--relationship', 'children',
                '--where-field', 'ordinary', 'Pitch', 'at-most', str(threshold), '--include', 'pitch-cents'], maximum=1)
            assert [row['id'] for row in rows] == expected[threshold][:1]
            for row in rows:
                assert canonical_json_bytes(row['pitch_cents']) == canonical_json_bytes(by_id[row['id']]['pitch_cents'])
            proof = trace(detail, packets, by_id, (threshold,), root=True)
            assert proof['source_complete'] is True and proof['source_rows'] == 5
            assert proof['final_root_limit_applied_after_predicates'] is True
            waql = detail['semantic_preview']['envelope']['args']['waql']
            assert waql == f'from object "{CONTAINER}" select children where @Pitch <= {threshold} take 1'
            final_rows = packets[detail['call']['evidence_path']]['result']['return']
            assert [row['id'] for row in final_rows] == expected[threshold][:1]
            for row in final_rows:
                assert canonical_json_bytes(row['@Pitch']) == canonical_json_bytes(by_id[row['id']]['pitch_cents'])
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
