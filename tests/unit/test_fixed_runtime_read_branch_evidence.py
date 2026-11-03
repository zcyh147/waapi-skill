"""Direct public Gateway behavior with injected native responses."""

from copy import deepcopy

import json

import time

from pathlib import Path

import pytest

from tests.maintenance import branch_coverage_audit as audit

from tests.unit.test_runtime_business_gateway import gateway, _env, _RuntimeControlDraftClient

def archive_reader(path):
    """Read immutable archived fixture bytes without evaluating historical credit."""
    import base64
    import gzip
    raw = path.read_bytes()
    files = json.loads(gzip.decompress(raw))['files']
    return lambda name: base64.b64decode(files[name], validate=True)

def pointer_value(document, pointer):
    for token in pointer.strip('/').split('/') if pointer else ():
        token = token.replace('~1', '/').replace('~0', '~')
        document = document[int(token)] if isinstance(document, list) else document[token]
    return document

FIXTURE = audit.ROOT / 'tests/fixtures/runtime-fixed-reads'

NODEID = 'tests/destructive/test_authoring_ui_business_live.py::test_runtime_owned_2025_profiler_readers'

URI = 'ak.wwise.core.profiler.getVoices'

def original_read(uri=URI, *, filtered=False):
    read = archive_reader(FIXTURE / 'r103-originals.json.gz')
    run = json.loads((FIXTURE / 'r103-category.json').read_bytes())
    seal = json.loads(read(run['categories'][0]['batch_finalization']['artifact']))
    node = json.loads(read(seal['observations'][NODEID]['path']))
    receipt, = [r for r in node['receipts'] if (r['argv'][0] == 'profiler-game-objects' if uri.endswith('.getGameObjects') else r['argv'][:2] == ['core-call', uri])
        and any(flag in r['argv'] for flag in ('--voice-instance-handle', '--bus-instance-handle')) == filtered]
    import gzip
    files = json.loads(gzip.decompress((FIXTURE / 'r103-originals.json.gz').read_bytes()))['files']
    rawpath, = [name for name in files if name.endswith('/' + receipt['payload']['call']['evidence_path'].rsplit('/', 1)[1])]
    return receipt, json.loads(read(rawpath))

def public_fixed_read(tmp_path, *, version='2025.1', host='wwise-authoring', rows=None,
                      view='diagnostics', position='40042', fields=None, uri=URI, filtered=False, public_calls=None, handle_index=0, seed_rows=None, original_argv=None):
    operation = uri
    original, raw = original_read(operation, filtered=filtered)
    context = None
    tmp_path.mkdir(parents=True)
    client = _RuntimeControlDraftClient(tmp_path, version=version)
    fallback = client.call
    trace = []
    def call(uri, args=None, options=None):
        if uri in {URI, 'ak.wwise.core.profiler.getBusses', 'ak.wwise.core.profiler.getAudioObjects'} or uri == operation:
            result = {'return': deepcopy((raw if uri == operation else original_read(uri)[1])['result']['return'] if rows is None or uri != operation else rows)}
        elif uri == 'ak.wwise.core.profiler.getCursorTime':
            result = {'return': 123}
        else:
            result = fallback(uri, args, options)
        if seed_rows is not None and uri == 'ak.wwise.core.profiler.getBusses' and operation.endswith('.getAudioObjects'):
            result = {'return': deepcopy(seed_rows)}
        if uri == 'ak.wwise.core.getInfo':
            from tests.unit.test_rtpc_field_branch_evidence import BUILDS
            minor, build = BUILDS[version]
            result['isCommandLine'] = host == 'wwise-console'
            result['version'].update(minor=minor, build=build, displayName=f'v{version}.{minor}.{build}')
        trace.append({'ordinal': len(trace), 'uri': uri, 'args': deepcopy(args), 'options': deepcopy(options), 'result': deepcopy(result)})
        return result
    client.call = call
    argv = ['core-call', operation, '--profiler-position', position, *(['--result-view', view] if fields is None else
        [token for name in fields for token in ('--result-field', name)]), '--max-results', '64']
    if operation.endswith('.getGameObjects'):
        argv = ['profiler-game-objects', *(['--capture-ms', position] if position.isdecimal() else
            ['--capture', 'latest' if position == 'capture-latest' else 'user-cursor'])]
    if original_argv is not None:
        argv = deepcopy(original_argv)
    def public_receipt(argv, code, payload):
        # Evidence-only copy of the Gateway-written immutable issuer record;
        # the public payload and argv are preserved exactly.
        receipt = {'argv': argv, 'exit_code': code, 'payload': payload}
        handles = {row['voice_instance_handle'] for row in payload.get('agent_result', {}).get('return', [])
            if 'voice_instance_handle' in row}
        if handles:
            from wwise_waapi.runtime_inspection_observations import validate_pipeline_handle
            for handle in handles: validate_pipeline_handle(handle)
            observation_handles = {'rto1-' + handle[5:].rsplit('-', 1)[0] for handle in handles}
            assert len(observation_handles) == 1
            observation_handle, = observation_handles
            receipt['retained_observation'] = json.loads((tmp_path / 'state/runtime-inspection-observations-v1' /
                (observation_handle + '.json')).read_bytes())
        return receipt
    calls = public_calls if public_calls is not None else []
    if filtered:
        seed_uri = URI if operation == URI else 'ak.wwise.core.profiler.getBusses'
        kind = 'voice' if seed_uri == URI else 'bus'
        seed_argv = ['core-call', seed_uri, '--profiler-position', position, '--result-view', 'diagnostics', '--max-results', '64']
        code, seed = gateway.execute_gateway(['--state-dir', str(tmp_path / 'state'), *seed_argv],
            env=_env(tmp_path, version=version), client_factory=lambda _: client)
        assert code == 0, json.dumps(seed)
        handle = seed['agent_result']['return'][handle_index][kind + '_instance_handle']
        calls.append({'gateway': public_receipt(seed_argv, code, seed), 'native_start': 0, 'native_end': len(trace)})
        argv.extend(['--' + kind + '-instance-handle', handle])
    start = len(trace)
    code, payload = gateway.execute_gateway(['--state-dir', str(tmp_path / 'state'), *argv],
        env=_env(tmp_path, version=version), client_factory=lambda _: client)
    assert code == 0, json.dumps(payload)
    if not operation.endswith('.getGameObjects'):
        assert payload['agent_result']['complete'] is True
    native = {key: trace[-1][key] for key in ('uri', 'args', 'options', 'result')}
    assert native['args']['time'] == (int(position) if position.isdecimal() else
        ('capture' if position == 'capture-latest' else 'user') if operation.endswith('.getGameObjects') else 123)
    receipt = public_receipt(argv, code, payload)
    calls.append({'gateway': receipt, 'native_start': start, 'native_end': len(trace)})
    return receipt, native, context, trace

@pytest.mark.parametrize('selection', ('single', 'ordered-repeated'))
def test_explicit_fixed_fields_reach_consumer_with_exact_order_and_repetition(tmp_path, selection):
    fields = ['objectName'] if selection == 'single' else ['baseVolume', 'objectName', 'baseVolume']
    receipt, native, context, trace = public_fixed_read(tmp_path / 'public', position='0', fields=fields)
    assert native['options'] == {'return': fields}
    assert {k for k in receipt['payload']['agent_result']['return'][0] if k != 'voice_instance_handle'} == set(fields)

def typed_fixed_rows(version, uri, mode='rich'):
    """Small fixed-reader fixtures from the matching definition's scalar domains."""
    from wwise_waapi.native_catalog import load_native_catalog
    catalog = load_native_catalog(version, 'wwise-authoring')
    documents = catalog['definitions']['documents']
    def resolve(reference):
        name, pointer = reference.split('#', 1)
        return pointer_value(documents[name or 'waapi_definitions.json'], pointer)
    item = catalog['schemas'][uri]['resultSchema']['properties']['return']['items']
    if '$ref' in item:
        item = resolve(item['$ref'])
    if mode == 'empty': return []
    if mode == 'absent': return [{}]
    def scalar(schema, index, field):
        if '$ref' in schema:
            name = schema['$ref'].rsplit('/', 1)[1]
            target = resolve(schema['$ref'])
            if name == 'guid': return '{FBF74BF9-8B83-44A8-AC8A-BA85372ECDC4}'
            if name == 'id64bits':
                unsigned = resolve(target['anyOf'][0]['$ref'].replace('#/', 'common_definitions.json#/'))
                signed = resolve(target['anyOf'][1]['$ref'].replace('#/', 'common_definitions.json#/'))
                return [unsigned['minimum'], unsigned['maximum'], signed['minimum'], signed['maximum']][index]
            assert name in {'uint32', 'uint64', 'int8', 'int32', 'int64'}
            if field in {'pipelineID', 'busPipelineID'} and index >= 2: return index - 1
            return target['minimum'] if index % 2 == 0 else target['maximum']
        kind = schema['type']
        if kind == 'string': return '' if index % 2 == 0 else 'Row'
        if kind == 'boolean': return bool(index % 2)
        if kind == 'number': return 0.0 if index % 2 == 0 else 1.5
        if kind == 'integer': return index
        raise AssertionError((field, schema))
    rows = []
    count = 1 if mode in {'single', 'empty-arrays'} else 4 if version in {'2024.1', '2025.1'} else 2
    for index in range(count):
        row = {}
        for field, schema in item['properties'].items():
            if schema.get('type') == 'array':
                if field == 'metadata':
                    full = {name: scalar(spec, index, name) for name, spec in schema['items']['properties'].items()}
                    required = {name: scalar(schema['items']['properties'][name], index + 1, name) for name in schema['items']['required']}
                    row[field] = [] if mode == 'empty-arrays' else [required] if mode == 'single' else [full, required]
                else:
                    assert field in {'rmsMeter', 'peakMeter'} and schema['items']['type'] == 'number'
                    row[field] = [] if mode == 'empty-arrays' else [0.0] if mode == 'single' else [0.0, 1.5]
            else:
                row[field] = scalar(schema, index, field)
        rows.append(row)
    return rows

@pytest.mark.parametrize('version,name,mode', [
    ('2021.1', 'getBusses', 'rich'), ('2025.1', 'getAudioObjects', 'rich'),
    ('2022.1', 'getGameObjects', 'absent'), ('2025.1', 'getGameObjects', 'rich'),
])
def test_typed_fixed_reader_result_families_reach_consumer(tmp_path, version, name, mode):
    uri = 'ak.wwise.core.profiler.' + name
    rows = typed_fixed_rows(version, uri, mode)
    receipt, native, context, trace = public_fixed_read(tmp_path / 'public', version=version, uri=uri, rows=rows, position='0')
    assert native['result']['return'] == rows
    result = receipt['payload']['agent_result']
    if name == 'getGameObjects':
        if version == '2022.1':
            assert result == {'count': 1, 'game_objects': [{'id': None, 'name': None, 'register_time': None,
                'unregister_time': None, 'unreported_fields': ['id', 'name', 'register_time', 'unregister_time']}]}
        else:
            assert [(row['id'], row['name'], row['register_time'], row['unregister_time']) for row in result['game_objects']] == [
                (row['id'], row['name'], row['registerTime'], row['unregisterTime']) for row in rows]
    else:
        assert [{k: value for k, value in row.items() if not k.endswith('_instance_handle')} for row in result['return']] == rows

@pytest.mark.parametrize('name,filtered', [
    ('getVoices', False), ('getBusses', False), ('getAudioObjects', False), ('getGameObjects', False),
    ('getVoices', True), ('getBusses', True), ('getAudioObjects', True),
])
def test_seven_original_fixed_arrays_replay_through_public_portable_consumer(tmp_path, name, filtered):
    uri = 'ak.wwise.core.profiler.' + name
    calls = []
    receipt, native, context, trace = public_fixed_read(tmp_path / 'public', uri=uri, filtered=filtered, public_calls=calls)
    expected = native['result']['return']
    public = receipt['payload']['agent_result']
    if name == 'getGameObjects':
        assert [(row['id'], row['name'], row['register_time'], row['unregister_time']) for row in public['game_objects']] == [
            (row['id'], row['name'], row['registerTime'], row['unregisterTime']) for row in expected]
        return
    result = public['return']
    assert [{k: value for k, value in row.items() if not k.endswith('_instance_handle')} for row in result] == expected
    if name in {'getVoices', 'getBusses'}:
        key = 'voice_instance_handle' if name == 'getVoices' else 'bus_instance_handle'
        assert all(row[key] for row in result)

@pytest.mark.parametrize('catalog_host', ('wwise-console', 'wwise-authoring'))
def test_fixed_gameobjects_2021_boundary_has_no_native_route_or_connection(tmp_path, catalog_host):
    from wwise_waapi.native_catalog import load_native_catalog
    uri = 'ak.wwise.core.profiler.getGameObjects'
    assert uri not in load_native_catalog('2021.1', catalog_host)['schemas']
    code, payload = gateway.execute_gateway(['profiler-game-objects', '--capture-ms', '0'],
        env=_env(tmp_path, version='2021.1'),
        client_factory=lambda _: pytest.fail('2021GameObjects must stop before connection'))
    assert code == 2
    assert payload['error_code'] == 'UNSUPPORTED_STABLE_READ_VERSION'
    assert 'agent_result' not in payload
