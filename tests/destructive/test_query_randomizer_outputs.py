"""Read-only property-bound randomizer acceptance through the public Gateway."""
import copy
import hashlib
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from tests.destructive.support.source_copy_fixture import read_file, sha
from tests.destructive.test_gateway_workflow_transaction_matrix import workflow_sandbox_runtime, waapi_gateway
from tests.destructive.test_query_list_sequences import BUILDS, PINS, READ_APIS, _page_value, _wwu
from wwise_waapi.canonical import canonical_json_bytes, canonical_sha256


pytestmark = [pytest.mark.live, pytest.mark.destructive,
    pytest.mark.skipif(os.environ.get('WWISE_VERSION') not in {'2021.1', '2025.1'},
        reason='Selected randomizer RETURN acceptance backends are2025.1 and2021.1')]
REPO = Path(__file__).resolve().parents[2]
OWNER = '{B5DB3AFA-044F-441E-BC4A-1397D20E2692}'
CHILD = '{621056DB-C9E5-45AE-8412-6517D7026FBF}'
CHILDREN = {CHILD: 'FS_Crouching',
    '{1DDFE6B7-6229-4178-8B17-B252091C251A}': 'FS_Running',
    '{4FB8A67B-A879-435C-81EA-C2173CA9D929}': 'FS_Walking'}
IDENTITY = ('id', 'name', 'type', 'path')
FIELDS = {'enabled': 'Enabled', 'min_offset': 'Min', 'max_offset': 'Max'}


def source_frame(runtime):
    """Independent complete WWU source and owned-copy preservation, no launch/write."""
    relative = _wwu(runtime.version)
    source = runtime.sandbox.source_root / relative
    owned = runtime.sandbox.sandbox_path / relative
    assert source.resolve() != owned.resolve()
    assert not source.is_symlink() and not owned.is_symlink()
    body = read_file(source, 4 * 1024 * 1024)
    assert sha(body) == PINS[runtime.version][1]
    assert sha(read_file(owned, 4 * 1024 * 1024)) == sha(body)
    tree = ET.fromstring(body)
    owner, = [row for row in tree.iter('SwitchContainer') if row.get('ID') == OWNER]
    assert owner.get('Name') == 'Footstep_Types'
    children = owner.find('ChildrenList')
    assert children is not None
    assert {row.get('ID'): row.get('Name') for row in children} == CHILDREN
    assert all(row.tag == 'SwitchContainer' for row in children)
    modifiers = {}
    for name, expected in [('Pitch', {'Min': -200, 'Max': 200}), ('Volume', {'Min': -5})]:
        prop, = [row for row in owner.findall('./PropertyList/Property') if row.get('Name') == name]
        modifier, = prop.findall('./ModifierList/ModifierInfo/Modifier')
        stored = {row.get('Name'): float(row.get('Value')) for row in modifier.findall('./PropertyList/Property')}
        assert all(stored[key] == value for key, value in expected.items())
        modifiers[name] = {'stored_fields': stored, 'expected_offsets': expected}
    return {'relative_path': str(relative), 'sha256': sha(body), 'source_mtime_ns': source.stat().st_mtime_ns,
        'owned_mtime_ns': owned.stat().st_mtime_ns, 'owner': OWNER, 'children': CHILDREN, 'modifiers': modifiers}


def test_property_bound_randomizer_values_keep_owner_and_member_scope(workflow_sandbox_runtime, monkeypatch):
    runtime = workflow_sandbox_runtime
    assert runtime.version in {'2021.1', '2025.1'}
    live = runtime.sandbox.metadata.get_info_version
    assert tuple(live[key] for key in ('year', 'major', 'minor', 'build')) == BUILDS[runtime.version]
    output = runtime.state_dir / 'query-randomizer-outputs.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    assert not output.exists()
    evidence_root = Path(runtime.env['WWISE_EVIDENCE_DIR'])
    observation = {'candidate': runtime.candidate, 'version': runtime.version, 'read_only': True,
        'typed_randomizer_return_proof': False, 'reads': [], 'business_effect_verified': False,
        'boundary': 'property-bound root/singleton/full-and-selected-member typed RETURN; no Modifier identity or XML default inference'}
    category = {'category': 'query-randomizer-outputs', 'status': 'FAIL',
        'verifier_strength': 'fresh_property_scope_actual_typed_root_chain_and_member_randomizer_values',
        'observation_path': str(output)}
    runtime.category_results.append(category)
    status, continuation_count, dispatch_count = 'FAIL', 0, 0
    original_dispatch = waapi_gateway.WwiseDispatcher.dispatch

    def read(label, argv):
        nonlocal continuation_count, dispatch_count
        assert len(observation['reads']) < 6
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
        restored = _page_value(entries, encoding)
        diagnostics = {**initial_payload, **{key: restored[key] for key in ('related_scope_binding', 'related_read_evidence') if key in restored}}
        return restored['objects'], initial_calls, packets, diagnostics

    def object_calls(calls, packets):
        return [(index, call, packets[call['evidence_path']]['result']['return'])
            for index, call in enumerate(calls) if call['api'] == 'ak.wwise.core.object.get']

    def identity(raw, expected):
        assert {key: raw[key] for key in IDENTITY} == {key: expected[key] for key in IDENTITY}
        assert raw['classId'] == expected['class_id']

    def values(raw, prefix=''):
        result = {}
        for output, field in FIELDS.items():
            native = prefix + 'randomizer("Pitch").@' + field
            assert native in raw, (native, raw)
            value = raw[native]
            if output == 'enabled': assert type(value) is bool, (native, value)
            else: assert type(value) in (int, float) and value == (-200 if output == 'min_offset' else 200), (native, value)
            result[output] = value
        assert result == actual_pitch
        return result

    def public_pitch(context):
        assert context['related']['randomizers']['Pitch'] == actual_pitch
        assert set(context['related']['randomizers']['Pitch']) == set(FIELDS)

    def metadata(calls, packets, owner, meanings, payload=None):
        names, infos = [], []
        for call in calls:
            if not call['api'].endswith(('getPropertyAndReferenceNames', 'getPropertyInfo')): continue
            args = call['args'] or {}
            scope = {key: args[key] for key in ('classId', 'object') if key in args}
            assert scope in ({'classId': owner['class_id']}, {'object': OWNER}), scope
            result = packets[call['evidence_path']]['result']
            if call['api'].endswith('getPropertyAndReferenceNames'):
                names.append({'scope': scope, 'names': result['return']})
            elif args.get('property') in meanings and result.get('type'):
                assert result['name'] == args['property']
                assert result.get('restriction', {}).get('type') != 'reference'
                infos.append({'scope': scope, 'name': args['property'], 'metadata': result, 'packet': call['evidence_path']})
        for name in meanings:
            selected = [row for row in infos if row['name'] == name]
            assert selected, (name, calls)
            assert any(row['scope'] == info['scope'] and name in row['names'] for info in selected for row in names)
        if payload is not None:
            proof = payload['related_scope_binding']
            assert proof['scopes']
            for selection in proof['scopes']:
                assert selection['selected']['kind'] == 'property' and selection['selected']['name'] in meanings
                assert selection['complete'] is True
                assert any(info['scope'] == selection['scope'] and info['name'] == selection['selected']['name'] for info in infos)
            for association in proof.get('read_associations', []):
                assert any(all(canonical_json_bytes(call[key]) == canonical_json_bytes(association[key])
                    for key in ('api', 'args', 'options', 'result_sha256')) for call in calls), association
        return infos

    def root_values(calls, packets, owner):
        proofs = []
        fields = {f'randomizer("Pitch").@{field}' for field in FIELDS.values()} | {'randomizer("Volume").@Min'}
        for index, call, rows in object_calls(calls, packets):
            if not fields <= set((call['options'] or {})['return']): continue
            raw, = rows
            identity(raw, owner); values(raw)
            volume = raw['randomizer("Volume").@Min']
            assert type(volume) in (int, float) and volume == -5
            proofs.append({'index': index, 'packet': call['evidence_path'], 'values': {field: raw[field] for field in sorted(fields)}})
        assert proofs
        return proofs

    root_argv = ['query-object', '--exact-id', OWNER, '--max-results', '1', '--include', 'class-id',
        '--include-related', 'randomizer', 'Pitch', 'enabled',
        '--include-related', 'randomizer', 'Pitch', 'min-offset',
        '--include-related', 'randomizer', 'Pitch', 'max-offset',
        '--include-related', 'randomizer', 'Volume', 'min-offset', '--detail']
    try:
        observation['source_before'] = source_frame(runtime)
        code, schema = runtime.raw_gateway(['query-schema'])
        observation['business_schema'] = schema
        assert code == 0
        source = schema['related_outputs']['randomizers']['source']
        assert source['version'] == runtime.version
        assert source['wwise_build'] == '.'.join(map(str, BUILDS[runtime.version]))
        assert source['definitions_sha256'] == PINS[runtime.version][0]
        observation['randomizer_source'] = source
        rows, calls, packets, _ = read('exact-owner-before', ['query-object', '--exact-id', OWNER,
            '--max-results', '1', '--include', 'class-id', '--detail'])
        owner, = rows
        assert owner['id'] == OWNER and owner['name'] == 'Footstep_Types' and owner['type'] == 'SwitchContainer'
        assert all(isinstance(owner[key], str) and owner[key] for key in IDENTITY) and type(owner['class_id']) is int
        raw, = packets[calls[-1]['evidence_path']]['result']['return']
        identity(raw, owner)
        discovered, calls, packets, _ = read('fresh-owner-property-metadata',
            ['metadata', 'discover', '--exact-id', OWNER, '--meaning', 'Pitch', '--meaning', 'Volume'])
        for name in ('Pitch', 'Volume'):
            candidate, = [row for row in discovered['candidates'] if row['name'] == name]
            assert candidate['kind'] == 'property'
        observation['baseline'] = {'owner': owner, 'fresh_metadata': metadata(calls, packets, owner, {'Pitch', 'Volume'})}
        roots, calls, packets, payload = read('root-randomizer-values-before', root_argv)
        root, = roots
        assert {key: root[key] for key in owner} == owner
        actual_pitch = root['related']['randomizers']['Pitch']
        # Enabled authority is the actual native value below, never XML omission/default.
        assert type(actual_pitch['enabled']) is bool
        public_pitch(root)
        assert root['related']['randomizers']['Volume'] == {'min_offset': -5}
        observation['reads'][-1]['proof'] = {'typed_native_values': root_values(calls, packets, owner),
            'fresh_metadata': metadata(calls, packets, owner, {'Pitch', 'Volume'}, payload)}
        singleton, calls, packets, payload = read('singleton-parent-randomizer-values',
            ['query-object', '--exact-id', CHILD, '--max-results', '1', '--include', 'class-id',
                '--include-related', 'parent', 'randomizer', 'Pitch', 'enabled',
                '--include-related', 'parent', 'randomizer', 'Pitch', 'min-offset',
                '--include-related', 'parent', 'randomizer', 'Pitch', 'max-offset', '--detail'])
        child, = singleton
        assert child['id'] == CHILD and child['name'] == CHILDREN[CHILD] and child['type'] == 'SwitchContainer'
        assert all(isinstance(child[key], str) and child[key] for key in IDENTITY) and type(child['class_id']) is int
        parent = child['related']['parent']
        assert parent['object'] == {key: owner[key] for key in ('id', 'name')}
        public_pitch(parent)
        before, final = [], []
        for index, call, native in object_calls(calls, packets):
            raw, = native
            assert {key: raw[key] for key in IDENTITY} == {key: child[key] for key in IDENTITY}
            if 'classId' in raw: assert raw['classId'] == child['class_id']
            assert raw['parent'] == parent['object'] and raw['parent.classId'] == owner['class_id']
            if 'parent.randomizer("Pitch").@Enabled' in (call['options'] or {})['return']:
                identity(raw, child); values(raw, 'parent.'); final.append({'index': index, 'packet': call['evidence_path']})
            else: before.append({'index': index, 'packet': call['evidence_path']})
        assert len(final) == 1 and any(row['index'] < final[0]['index'] for row in before)
        observation['reads'][-1]['proof'] = {'parent_scope_before': before, 'typed_native_chained_values': final,
            'fresh_metadata': metadata(calls, packets, owner, {'Pitch'}, payload)}
        member_argv = ['query-object', '--exact-id', OWNER, '--max-results', '1', '--include', 'class-id']
        for path in (['children'], ['children', 'matching', 'name-is', CHILDREN[CHILD]]):
            for terminal in ('enabled', 'min-offset', 'max-offset'):
                member_argv.extend(['--include-related', *path, 'parent', 'randomizer', 'Pitch', terminal])
        members, calls, packets, payload = read('full-and-selected-member-parent-randomizers', member_argv)
        member_owner, = members
        assert {key: member_owner[key] for key in owner} == owner
        full = member_owner['related']['children']['items']
        assert len(full) == 3 and {item['object']['id'] for item in full} == set(CHILDREN)
        view, = member_owner['related']['projections']
        assert view['spec'] == {'source': 'children', 'stages': [{'selection': 'matching', 'condition': 'name-is', 'value': CHILDREN[CHILD]}]}
        selected, = view['items']
        assert selected['object'] == {key: child[key] for key in IDENTITY}
        for item in [*full, selected]:
            assert item['object']['name'] == CHILDREN[item['object']['id']]
            assert item['object']['type'] == 'SwitchContainer'
            assert item['related']['parent']['object'] == parent['object']
            public_pitch(item['related']['parent'])
        expected_strategy = 'native-composed-members' if runtime.version == '2025.1' else 'gateway-guid-grouped-reads'
        # Compact reply preserves exact business values; genuine captured calls below
        # prove the two planners without requesting thousands of diagnostic entries.
        fresh = metadata(calls, packets, owner, {'Pitch'})
        native_memberships, typed_members, composed = [], [], []
        roots_at = []
        for index, call, native in object_calls(calls, packets):
            waql = call['args']['waql']; fields = call['options']['return']
            if waql == f'from object "{OWNER}" take 1': roots_at.append(index)
            if ' select children' in waql:
                ids = [raw['id'] for raw in native]
                assert set(ids) == ({CHILD} if ' where ' in waql else set(CHILDREN))
                native_memberships.append({'index': index, 'packet': call['evidence_path'], 'ids': ids,
                    'selected': ' where ' in waql})
            if {f'parent.randomizer("Pitch").@{field}' for field in FIELDS.values()} <= set(fields):
                for raw in native:
                    assert raw['id'] in CHILDREN and raw['classId'] == child['class_id']
                    assert {key: raw[key] for key in IDENTITY} == next(item['object'] for item in full if item['object']['id'] == raw['id'])
                    assert raw['parent'] == parent['object'] and raw['parent.classId'] == owner['class_id']
                    values(raw, 'parent.')
                typed_members.append({'index': index, 'packet': call['evidence_path'], 'ids': [raw['id'] for raw in native]})
            for field in fields:
                if not field.startswith('children.{') or not all(f'parent.randomizer("Pitch").@{terminal}' in field for terminal in FIELDS.values()): continue
                expression, separator, alias = field.partition(' as ')
                assert separator and runtime.version == '2025.1'
                raw_root, = native; identity(raw_root, owner)
                rows = raw_root[alias]
                assert [row['id'] for row in rows] == [item['object']['id'] for item in full]
                for raw in rows:
                    assert raw['classId'] == child['class_id']
                    assert raw['parent'] == parent['object'] and raw['parent.classId'] == owner['class_id']
                    values(raw, 'parent.')
                composed.append({'index': index, 'packet': call['evidence_path'], 'accessor': expression,
                    'ids': [row['id'] for row in rows]})
        assert roots_at and typed_members
        final_root = max(roots_at)
        assert any(row['index'] < final_root and CHILD in row['ids'] for row in typed_members)
        assert any(row['index'] > final_root and CHILD in row['ids'] for row in typed_members)
        for side in (lambda index: index < final_root, lambda index: index > final_root):
            assert any(row['selected'] and side(row['index']) for row in native_memberships)
        if runtime.version == '2025.1': assert composed and not any(not row['selected'] for row in native_memberships)
        else:
            assert not composed
            full_memberships = [row for row in native_memberships if not row['selected']]
            assert full_memberships and all(row['ids'] == [item['object']['id'] for item in full] for row in full_memberships)
            assert any(set(row['ids']) == set(CHILDREN) for row in typed_members)
        observation['reads'][-1]['proof'] = {'strategy': expected_strategy, 'fresh_metadata': fresh,
            'native_memberships': native_memberships, 'typed_member_values': typed_members,
            'native_composed_member_values': composed, 'final_root_index': final_root,
            'public_full_member_ids': [item['object']['id'] for item in full], 'public_selected_ids': [selected['object']['id']]}
        repeated, calls, packets, payload = read('root-randomizer-values-after', root_argv)
        assert canonical_json_bytes(repeated) == canonical_json_bytes(roots)
        observation['reads'][-1]['proof'] = {'typed_native_values': root_values(calls, packets, owner),
            'fresh_metadata': metadata(calls, packets, owner, {'Pitch', 'Volume'}, payload)}
        observation['source_after'] = source_frame(runtime)
        assert observation['source_after'] == observation['source_before']
        assert len(observation['reads']) == 6
        observation.update(typed_randomizer_return_proof=True, business_effect_verified=True, dispatch_count=dispatch_count)
        status = 'PASS'
    except BaseException as exc:
        observation['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        body = json.dumps(observation, ensure_ascii=False, indent=2).encode()
        bounded = len(body) <= 24 * 1024 * 1024
        if not bounded:
            status = 'FAIL'; observation['business_effect_verified'] = False
            observation['typed_randomizer_return_proof'] = False
            observation['finalization_error'] = 'Observation exceeded24MiB; retained without truncation'
            body = json.dumps(observation, ensure_ascii=False, indent=2).encode()
        output.write_bytes(body)
        category.update(status=status, observation_sha256=hashlib.sha256(body).hexdigest(),
            business_effect_verified=observation['business_effect_verified'])
        assert bounded, 'Finalized observation exceeded24MiB; retained without native PASS'
