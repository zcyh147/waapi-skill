"""Read-only reference/local/override WHERE proof; no unset inference from omission."""
import copy
import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tests.destructive.test_gateway_workflow_transaction_matrix import workflow_sandbox_runtime, waapi_gateway
from tests.destructive.test_query_list_sequences import (
    BUILDS, DEFINITION_EVIDENCE, PINS, READ_APIS, REPO, _page_value, _wwu,
)
from tests.destructive.test_query_local_reference import SOUND, LOCAL_BUS, RESOLVED_BUS
from tests.destructive.test_query_override_source_values import SOUND as OVERRIDE_SOUND, PARENT
from wwise_waapi.canonical import canonical_json_bytes, canonical_sha256


pytestmark = [pytest.mark.live, pytest.mark.destructive,
    pytest.mark.skipif(os.environ.get('WWISE_VERSION') not in {'2021.1', '2025.1'},
        reason='Reference-condition witnesses are selected for2021.1/2025.1; no intermediate-version matrix')]
ZERO = '{00000000-0000-0000-0000-000000000000}'
AMBISONICS = {
    '2021.1': '9ce075f255131130504058fe6012f7546ccb51216dd58e85c5982eb2682e2fd2',
    '2022.1': '78d79b7a1aa7bcf71fa8b7d90c42902579138aff0ad2bae2f7673beedc618313',
    '2023.1': '47830f6435b6e11a4f2b736d4788afc6d2c15bd3233592dd75a238e2ee3f2da6',
    '2024.1': '8a5180d5e6125a02f7033cf149463078c498b8e21bce7f9958566664142047a3',
    '2025.1': '338d4c724ae8137d925e6563a3ba75ca703f0c2119576f57092e091cb2c74533',
}
# Provenance only: do not require ignored historical artifacts on the test host.
CLEARED_REFERENCE_EVIDENCE = {
    'build': '2025.1.7.9143',
    'path': 'r70-stored-clear-23f5b5d7-2025-r1/pytest/gateway-workflows-2025-10/state/inherited-reference-clear.json',
    'sha256': '8a6cd4cd2569ea7bec575275e7a27e2fba88becfe94f2fe50c1acaa325cc0f50',
    'fact': 'A verified real local-reference clear returned an object with zero GUID; not an omission/null equivalence',
}


def _sources():
    """Pin all five WHERE domains and committed graph before any fixture starts."""
    evidence = {}
    for version, (definition_sha, _) in PINS.items():
        path = REPO / 'skills/waapi-skill/references/semantic' / version / 'query-reference-condition-sources.json'
        source = json.loads(path.read_text())
        assert source['version'] == version and source['wwise_build'] == DEFINITION_EVIDENCE[version]['build']
        assert source['definitions_sha256'] == definition_sha
        assert source['domain'] == 'query-predicates-and-selection'
        assert source['return_domain_source'] == 'query-reference-value-sources.json'
        for section in source['sections'].values():
            assert hashlib.sha256(section['html'].encode()).hexdigest() == section['html_sha256']
        for name, phrase in (('reference_object_expression', 'When using @'),
                ('where_examples', '@UserAuxSend0 != null'), ('reference_identity_chain', 'OutputBus.id'),
                ('boolean_negation', 'Negates an expression'), ('property_value', '@@ is the same as no @')):
            assert phrase in source['sections'][name]['html']
        footsteps = ET.parse(REPO / 'tests/_org' / version / _wwu(version)).getroot()
        sound = next(node for node in footsteps.iter('Sound') if node.get('ID') == SOUND)
        assert not sound.findall("./ReferenceList/Reference[@Name='UserAuxSend0']")
        assert sound.find("./ReferenceList/Reference[@Name='OutputBus']/ObjectRef").get('ID') == LOCAL_BUS
        ambisonics = REPO / 'tests/_org' / version / _wwu(version).with_name('Ambisonics.wwu')
        assert hashlib.sha256(ambisonics.read_bytes()).hexdigest() == AMBISONICS[version]
        tree = ET.parse(ambisonics).getroot()
        child = next(node for node in tree.iter('Sound') if node.get('ID') == OVERRIDE_SOUND)
        parent = next(node for node in tree.iter() if node.get('ID') == PARENT)
        assert child in parent.findall('./ChildrenList/Sound')
        assert child.find("./PropertyList/Property[@Name='3DSpatialization']") is None
        assert parent.find("./PropertyList/Property[@Name='3DSpatialization']").get('Value') == '2'
        evidence[version] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'page_sha256': source['page_sha256'], 'archive_sha256': source['archive_sha256'],
            'sections_sha256': canonical_sha256(source['sections']), 'ambisonics_sha256': AMBISONICS[version]}
    return evidence


SOURCES = _sources()


def _observed(row, field):
    return {'present': field in row, **({'value': row[field]} if field in row else {})}


def _same(left, right):
    assert canonical_json_bytes(left) == canonical_json_bytes(right), (left, right)


def test_reference_local_and_override_conditions_use_native_scopes_and_unset_facts(workflow_sandbox_runtime, monkeypatch):
    runtime = workflow_sandbox_runtime
    live = runtime.sandbox.metadata.get_info_version
    assert runtime.version in {'2021.1', '2025.1'}
    oldest = runtime.version == '2021.1'
    maximum_groups = 7 if oldest else 8
    assert tuple(live[key] for key in ('year', 'major', 'minor', 'build')) == BUILDS[runtime.version]
    for relative, digest in ((_wwu(runtime.version), PINS[runtime.version][1]),
            (_wwu(runtime.version).with_name('Ambisonics.wwu'), AMBISONICS[runtime.version])):
        assert hashlib.sha256((runtime.sandbox.source_root / relative).read_bytes()).hexdigest() == digest
    output = runtime.state_dir / 'query-reference-conditions.json'
    output.parent.mkdir(parents=True, exist_ok=True)  # Before the first retained read, not only in finalization.
    assert not output.exists()
    evidence_root = Path(runtime.env['WWISE_EVIDENCE_DIR'])
    observation = {'candidate': runtime.candidate, 'version': runtime.version, 'read_only': True,
        'definitions': DEFINITION_EVIDENCE, 'sources': SOURCES,
        'acceptance_scope': '2021 four core groups plus three observational unset-expression groups' if oldest else '2025 eight-group reference/local/override proof',
        'unset_association_authority': 'new matching2021 native WHERE observation; no transferred zero-GUID/null premise' if oldest else CLEARED_REFERENCE_EVIDENCE,
        'reads': [], 'core_verified': False, 'unset_verified': False, 'business_effect_verified': False}
    category = {'category': 'query-reference-local-override-conditions', 'status': 'FAIL',
        'verifier_strength': 'actual_native_where_unfiltered_values_complete_source_and_fresh_actual_metadata',
        'observation_path': str(output)}
    runtime.category_results.append(category)
    status, continuation_count = 'FAIL', 0
    original_dispatch = waapi_gateway.WwiseDispatcher.dispatch

    def read(label, identity, flags):
        nonlocal continuation_count
        assert len(observation['reads']) < maximum_groups
        argv = ['query-object', '--exact-id', identity, '--max-results', '1', *flags]
        record = {'label': label, 'invocations': []}
        observation['reads'].append(record)
        entries, offset, encoding, initial_calls, packets = [], 0, None, None, {}
        while True:
            before = set(evidence_root.glob('*.json'))
            calls = []
            invocation = {'argv': argv, 'dispatch_calls': calls, 'native_packets': []}
            record['invocations'].append(invocation)
            def capture(dispatcher, api, **kwargs):
                # R77's reviewed passive spy: unchanged arguments, one original
                # call, and the very same returned object; never a direct client.
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
            # Established sequence witness decoder and complete continuation
            # protocol; no flags prepended to a returned complete gateway_argv.
            assert isinstance(value, dict) and value['entries_encoding'] in {'json-document-fragments', 'json-pointer-entries'}, payload
            if encoding is None: encoding = value['entries_encoding']
            assert encoding == value['entries_encoding'] and value['page']['offset'] == offset
            entries.extend(value['entries']); offset += len(value['entries'])
            assert value['page']['next_offset'] == offset
            if value['projection_complete']: break
            assert continuation_count < 4, 'Delivery exceeds the approved continuation budget; retain evidence without retry'
            continuation_count += 1
            argv = value['next_command']['gateway_argv']
            assert 'query-object' in argv and '--result-query' in argv and '--result-page' in argv
        return _page_value(entries, encoding)['objects'], initial_calls, packets

    def native_rows(call, packets):
        return packets[call['evidence_path']]['result']['return']

    def final_call(calls, identity, clauses):
        expected = ' '.join([f'from object "{identity}"', *clauses, 'take 1'])
        indices = [index for index, call in enumerate(calls) if (call['args'] or {}).get('waql') == expected]
        assert len(indices) == 1, (expected, calls)
        return indices[0]

    def metadata(calls, packets, field, identity, class_id, *, reference, required=True):
        matches = []
        for call in calls:
            if not call['api'].endswith('getPropertyInfo') or call['args']['property'] != field: continue
            result = packets[call['evidence_path']]['result']
            assert result['name'] == field
            scope = {key: call['args'][key] for key in ('classId', 'object') if key in call['args']}
            assert scope in ({'classId': class_id}, {'object': identity}), scope
            kind = (str(result.get('type', '')).casefold() in {'reference', 'objectreference'}
                or str(result.get('restriction', {}).get('type', '')).casefold() == 'reference')
            if required: assert kind is reference
            if not reference: assert result['type'] in {'int16', 'int32'}
            matches.append({'scope': scope, 'packet': call['evidence_path'], 'metadata': result, 'kind_compatible': kind is reference})
        if required: assert matches, (field, calls)
        return matches

    def trace(rows, calls, packets, identity, clauses, expected_values):
        """The sealed native outcome, not a Python predicate, determines membership."""
        final = final_call(calls, identity, clauses)
        selected = native_rows(calls[final], packets)
        assert [row['id'] for row in rows] == [row['id'] for row in selected]
        assert all(row['id'] == identity for row in selected)
        sources, values = [], {field: [] for field in expected_values}
        for index, call in enumerate(calls):
            assert call['ok'] is True and call['api'] in READ_APIS
            if call['api'] != 'ak.wwise.core.object.get': continue
            waql = (call['args'] or {}).get('waql', '')
            # Literal comparison targets must not gain target-existence reads.
            assert waql.startswith(f'from object "{identity}"'), waql
            if ' where ' in waql or ' select ' in waql: continue
            raw = native_rows(call, packets)
            assert len(raw) == 1 and raw[0]['id'] == identity
            match = re.fullmatch(r'from object "' + re.escape(identity) + r'" take ([1-9][0-9]*)', waql)
            if match and {'id', 'name', 'type', 'path', 'classId'} <= set(call['options']['return']):
                assert len(raw) < int(match.group(1))
                sources.append((index, raw[0]))
            for field, expected in expected_values.items():
                if field in call['options']['return'] and 'classId' in call['options']['return']:
                    _same(_observed(raw[0], field), expected)
                    values[field].append((index, raw[0]))
        assert any(index < final for index, _ in sources) and any(index > final for index, _ in sources)
        known = sources[0][1]
        assert known['type'] == 'Sound'
        for _, raw in sources:
            for key in ('id', 'name', 'type', 'path', 'classId'): _same(raw[key], known[key])
        for raw in selected:
            for key in ('id', 'name', 'type', 'path', 'classId'): _same(raw[key], known[key])
        scopes = {}
        for field, observed in values.items():
            assert any(index < final for index, _ in observed) and any(index > final for index, _ in observed), field
            for _, raw in observed:
                for key in ('id', 'name', 'type', 'path', 'classId'): _same(raw[key], known[key])
            for raw in selected: _same(_observed(raw, field), expected_values[field])
            token = field.lstrip('@')
            scopes[field] = metadata(calls, packets, token, identity, known['classId'],
                reference=token != '3DSpatialization', required=not (oldest and token == 'UserAuxSend0'))
            if oldest and token == 'UserAuxSend0': assert any(item['kind_compatible'] for item in scopes[field])
        observation['reads'][-1]['proof'] = {'final_packet': calls[final]['evidence_path'],
            'selected_ids': [row['id'] for row in selected], 'complete_source': known, 'metadata': scopes,
            'unfiltered_values': expected_values, 'source_before_and_after': True}
        return selected

    try:
        baseline, calls, packets = read('independent-stored-resolved-and-unset-candidate', SOUND,
            ['--include', 'class-id', '--include-field', 'OutputBus', '--include-local-reference', 'OutputBus',
                '--include-local-reference', 'UserAuxSend0'])
        sound, = baseline
        assert sound['id'] == SOUND and sound['name'] == 'Footstep_Crouching_Concrete_01' and sound['type'] == 'Sound'
        raw, = native_rows(calls[final_call(calls, SOUND, [])], packets)
        for key in ('id', 'name', 'type', 'path'): _same(sound[key], raw[key])
        _same(sound['class_id'], raw['classId'])
        _same(sound['references']['OutputBus'], raw['OutputBus'])
        _same(sound['local_references']['OutputBus'], raw['@OutputBus'])
        assert raw['OutputBus']['id'] == RESOLVED_BUS and raw['@OutputBus']['id'] == LOCAL_BUS
        _same(_observed(sound.get('local_references', {}), 'UserAuxSend0'), _observed(raw, '@UserAuxSend0'))
        metadata(calls, packets, 'OutputBus', SOUND, raw['classId'], reference=True)
        unset_metadata = metadata(calls, packets, 'UserAuxSend0', SOUND, raw['classId'], reference=True, required=not oldest)
        unset = _observed(raw, '@UserAuxSend0')
        if oldest:
            # A present canonical reference shape is interpretable, but zero
            # does not acquire2025's null meaning. The documented native WHERE
            # observations below establish the old association themselves.
            eligible = (any(item['kind_compatible'] for item in unset_metadata) and unset['present']
                and (unset['value'] is None or isinstance(unset['value'], dict)
                    and isinstance(unset['value'].get('id'), str)
                    and re.fullmatch(r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}', unset['value']['id']) is not None))
            basis = 'source nonassignment plus fresh actual-scope reference metadata and present interpretable raw value; no preexisting2021 null/zero equivalence'
        else:
            eligible = unset['present'] and (unset['value'] is None
                or isinstance(unset['value'], dict) and unset['value'].get('id') == ZERO)
            basis = 'present native null or matching-host documented cleared zero-GUID shape plus fresh reference metadata and source nonassignment'
        observation['unset_candidate'] = {'raw': unset, 'eligible': eligible, 'basis': basis, 'metadata': unset_metadata}
        observation['independent_sound'] = sound
        reference_values = {'@@OutputBus': {'present': True, 'value': raw['OutputBus']},
            '@OutputBus': _observed(raw, '@OutputBus')}
        positive_flags = ['--where-field', 'reference', 'OutputBus', 'is', RESOLVED_BUS,
            '--where-field', 'local-reference', 'OutputBus', 'is', LOCAL_BUS,
            '--where-field', 'reference', 'OutputBus', 'is-not', LOCAL_BUS,
            '--where-field', 'reference', 'OutputBus', 'is-not', 'null',
            '--include-field', 'OutputBus', '--include-local-reference', 'OutputBus']
        rows, calls, packets = read('stored-resolved-known-set-positive', SOUND, positive_flags)
        assert [row['id'] for row in rows] == [SOUND]
        _same(rows[0]['references']['OutputBus'], sound['references']['OutputBus'])
        _same(rows[0]['local_references']['OutputBus'], sound['local_references']['OutputBus'])
        selected, = trace(rows, calls, packets, SOUND, [f'where @@OutputBus.id = "{RESOLVED_BUS}"',
            f'where @OutputBus.id = "{LOCAL_BUS}"', f'where @@OutputBus.id != "{LOCAL_BUS}"',
            'where @@OutputBus != null'], reference_values)
        _same(rows[0]['references']['OutputBus'], selected['OutputBus'])
        _same(rows[0]['local_references']['OutputBus'], selected['@OutputBus'])
        rows, calls, packets = read('known-set-null-negative', SOUND,
            ['--where-field', 'reference', 'OutputBus', 'is', 'null'])
        assert rows == []
        trace(rows, calls, packets, SOUND, ['where !(@@OutputBus != null)'], {'@@OutputBus': reference_values['@@OutputBus']})

        if eligible:
            unset_outcomes = {}
            for label, comparison, constant, clause, expected_ids in (
                ('known-unset-null', 'is', 'null', 'where !(@UserAuxSend0 != null)', [SOUND]),
                ('known-unset-setness', 'is-not', 'null', 'where @UserAuxSend0 != null', []),
                ('known-unset-identity-inequality', 'is-not', RESOLVED_BUS, f'where @UserAuxSend0.id != "{RESOLVED_BUS}"', None)):
                flags = ['--where-field', 'local-reference', 'UserAuxSend0', comparison, constant]
                if label == 'known-unset-null': flags += ['--include-local-reference', 'UserAuxSend0']
                observed_label = label.replace('known-unset', 'observe-unassigned-reference') if oldest else label
                rows, calls, packets = read(observed_label, SOUND, flags)
                if expected_ids is not None and not oldest: assert [row['id'] for row in rows] == expected_ids
                trace(rows, calls, packets, SOUND, [clause], {'@UserAuxSend0': unset})
                if label == 'known-unset-null':
                    for row in rows: _same(_observed(row.get('local_references', {}), 'UserAuxSend0'), unset)
                unset_outcomes[observed_label] = [row['id'] for row in rows]
                if expected_ids is None:
                    observation['unset_identity_inequality_native_outcome'] = [row['id'] for row in rows]
            observation['unset_verified'] = True
            observation['unset_native_expression_observations'] = {'raw_value': unset, 'selected_ids': unset_outcomes,
                'classification': 'new2021 shape/null/setness/identity-inequality association observed from documented native WHERE' if oldest else '2025 independently eligible unset fixture verified',
                'preexisting_matching_null_proof': not oldest, 'python_complement_used': False}
        else:
            observation['unset_incomplete_reason'] = (
                '2021 candidate lacks fresh actual-scope reference metadata or a present interpretable native reference value; no null/zero equivalence is inferred. Three observational groups were not executed.' if oldest else
                'Fresh reference RETURN did not establish a present null or documented cleared zero-GUID shape; omission is not null. Groups3-5 were not executed.')

        scalar_values = {'@3DSpatialization': {'present': True, 'value': 0}, '@@3DSpatialization': {'present': True, 'value': 2}}
        rows, calls, packets = read('local-and-override-scalar-positive', OVERRIDE_SOUND,
            ['--where-field', 'ordinary', '3DSpatialization', 'is', '0',
                '--where-field', 'override-source-value', '3DSpatialization', 'is', '2',
                '--include-field', '3DSpatialization', '--include-override-source-value', '3DSpatialization',
                '--include', 'parent', '--include', 'class-id'])
        scalar, = rows
        assert scalar['id'] == OVERRIDE_SOUND and scalar['name'] == 'SLS_CAR_PassBy_DirtGravelRoad_01'
        assert scalar['parent']['id'] == PARENT
        _same(scalar['properties']['3DSpatialization'], 0)
        _same(scalar['override_source_values']['3DSpatialization'], 2)
        selected, = trace(rows, calls, packets, OVERRIDE_SOUND,
            ['where @3DSpatialization = 0', 'where @@3DSpatialization = 2'], scalar_values)
        _same(scalar['class_id'], selected['classId'])
        _same(scalar['parent'], selected['parent'])
        _same(scalar['properties']['3DSpatialization'], selected['@3DSpatialization'])
        _same(scalar['override_source_values']['3DSpatialization'], selected['@@3DSpatialization'])
        if not oldest:
            rows, calls, packets = read('wrong-override-scalar-negative', OVERRIDE_SOUND,
                ['--where-field', 'override-source-value', '3DSpatialization', 'is', '0'])
            assert rows == []
            trace(rows, calls, packets, OVERRIDE_SOUND, ['where @@3DSpatialization = 0'],
                {'@@3DSpatialization': scalar_values['@@3DSpatialization']})
        observation['core_verified'] = True
        assert len(observation['reads']) == ((7 if eligible else 4) if oldest else (8 if eligible else 5))
        if not observation['unset_verified']:
            observation['outcome'] = 'incomplete_unset_fixture'
            pytest.fail(observation['unset_incomplete_reason'])
        observation['business_effect_verified'] = True
        status = 'PASS'
    except BaseException as exc:
        observation['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        body = json.dumps(observation, ensure_ascii=False, indent=2).encode('utf-8')
        # Retain a failed oversized receipt too; never convert a finalizer
        # failure into a PASS category or silently truncate packet associations.
        bounded = len(body) <= 24 * 1024 * 1024
        if not bounded:
            status = 'FAIL'
            observation['business_effect_verified'] = False
            observation['finalization_error'] = 'Observation exceeded24MiB; oversized evidence retained without truncation'
            body = json.dumps(observation, ensure_ascii=False, indent=2).encode('utf-8')
        output.write_bytes(body)
        category.update(status=status, observation_sha256=hashlib.sha256(body).hexdigest(),
            business_effect_verified=observation['business_effect_verified'])
        assert bounded, 'Finalized observation exceeded24MiB; evidence retained, no native PASS'
