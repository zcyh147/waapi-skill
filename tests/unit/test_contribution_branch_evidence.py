"""Direct public Gateway behavior with injected native responses."""

from copy import deepcopy

import json

import pytest

from tests.unit.test_runtime_result_reference_gateway import task, GUID, PREFIX

URI = PREFIX + 'getVoiceContributions'

VERSIONS = ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1')

def test_older_partial_contribution_reports_only_actual_fields(tmp_path):
    run, _, _ = task(tmp_path, '2022.1', URI, {'return': {'volume': -3.0}})
    code, payload = run('profiler-voice-contributions', '--capture-ms', '123', '--voice-object-id', GUID)
    assert code == 0, json.dumps(payload)
    assert payload['agent_result'] == {
        'contribution_reported': True, 'volume': -3.0, 'lpf': None, 'hpf': None,
        'dsf': {'feature_available': False, 'reported': False, 'value': None}, 'objects': None,
        'unreported_fields': ['lpf', 'hpf', 'objects'],
    }

def test_explicit_wwise_default_bus_path_omits_native_selection(tmp_path):
    result = {'return': {'volume': -3.0, 'LPF': 0.0, 'HPF': 0.0, 'objects': []}}
    run, _, calls = task(tmp_path, '2022.1', URI, result)
    code, payload = run('profiler-voice-contributions', '--capture-ms', '123',
        '--voice-object-id', GUID, '--bus-path', 'wwise-default')
    assert code == 0, json.dumps(payload)
    assert calls[-1] == (URI, {'voicePipelineID': 42, 'time': 123}, {})

@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('field', ('volume', 'LPF', 'HPF', 'objects'))
@pytest.mark.parametrize('damage', ('absent', 'null'))
def test_contribution_partial_return_keeps_versioned_presence_and_type_rules(tmp_path, version, field, damage):
    contribution = {'volume': -3.0, 'LPF': 0.0, 'HPF': 0.0, 'objects': []}
    if version == '2025.1':
        contribution['DSF'] = 0.0
    if damage == 'absent':
        del contribution[field]
    else:
        contribution[field] = None
    run, _, _ = task(tmp_path, version, URI, {'return': contribution})
    code, payload = run('profiler-voice-contributions', '--capture-ms', '123', '--voice-object-id', GUID)
    if damage == 'absent' and version in ('2021.1', '2022.1'):
        assert code == 0, json.dumps(payload)
        assert payload['agent_result']['contribution_reported'] is True
        assert payload['agent_result']['unreported_fields'] == [{'LPF': 'lpf', 'HPF': 'hpf'}.get(field, field)]
        assert payload['agent_result'][{'LPF': 'lpf', 'HPF': 'hpf'}.get(field, field)] is None
    else:
        assert code == 2, json.dumps(payload)
        assert 'agent_result' not in payload

@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('mode', (None, 'dry-path', 'wwise-default'))
def test_public_bus_path_choices_preserve_omission_and_dry_construction(tmp_path, version, mode):
    result = {'return': {'volume': -3.0, 'LPF': 0.0, 'HPF': 0.0, 'objects': [],
        **({'DSF': 0.0} if version == '2025.1' else {})}}
    run, _, calls = task(tmp_path, version, URI, result)
    code, payload = run('profiler-voice-contributions', '--capture-ms', '123',
        '--voice-object-id', GUID, *(['--bus-path', mode] if mode is not None else []))
    assert code == 0, json.dumps(payload)
    expected = {'voicePipelineID': 42, 'time': 123}
    if mode != 'wwise-default':
        expected['bussesPipelineID'] = []
    assert calls[-1] == (URI, expected, {})

@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('mode', ('dry-path', 'wwise-default'))
@pytest.mark.parametrize('selector', ('--bus-object-id', '--bus-instance-handle'))
def test_explicit_bus_path_rejects_conflicting_bus_selectors_before_dispatch(tmp_path, version, mode, selector):
    run, _, calls = task(tmp_path, version, URI, {})
    code, payload = run('profiler-voice-contributions', '--capture-ms', '123', '--voice-object-id', GUID,
        '--bus-path', mode, selector, GUID if selector == '--bus-object-id' else 'untrusted-handle')
    assert code == 2, json.dumps(payload)
    assert 'conflicts' in payload['message']
    assert not calls

@pytest.mark.parametrize('version', VERSIONS)
def test_contribution_request_schema_discloses_business_bus_path_choices(version):
    from tests.unit.test_runtime_business_gateway import gateway
    code, payload = gateway.execute_gateway(['--version', version, 'request-schema', URI],
        client_factory=lambda _: pytest.fail('offline contribution discovery connected'))
    assert code == 0, json.dumps(payload)
    assert payload['native_request_fields_disclosed'] is False
    game_object = payload['commands'][0]['input_forms']['game_object']
    assert game_object['domain'] == ('int64-or-uint64' if version in ('2024.1', '2025.1') else 'uint64')
    assert game_object['minimum'] == (-(1 << 63) if version in ('2024.1', '2025.1') else 0)
    assert game_object['maximum'] == (1 << 64) - 1
    assert game_object['version'] == version
    form = payload['commands'][0]['input_forms']['bus_selection']
    assert form['choices'] == {'dry-path': 'Explicit empty dry path',
        'wwise-default': 'Leave path selection to Wwise; no dry-path equivalence claim'}

@pytest.mark.parametrize('version,game_object_id', [('2024.1', -1), ('2025.1', -(1 << 63))])
def test_object_identity_contribution_selects_versioned_negative_game_object(tmp_path, version, game_object_id):
    from tests.unit.test_runtime_business_gateway import gateway, _env, _RuntimeControlDraftClient
    client = _RuntimeControlDraftClient(tmp_path, version=version)
    original = client.call
    calls = []
    def call(uri, args=None, options=None):
        calls.append((uri, deepcopy(args), deepcopy(options)))
        if uri == PREFIX + 'getVoices':
            return {'return': [{'pipelineID': 42, 'gameObjectID': game_object_id, 'objectGUID': GUID,
                'objectName': 'Voice', 'gameObjectName': 'Object'}]}
        if uri == URI:
            return {'return': {'volume': -3.0, 'LPF': 0.0, 'HPF': 0.0, 'objects': [],
                **({'DSF': 0.0} if version == '2025.1' else {})}}
        return original(uri, args, options)
    client.call = call
    code, payload = gateway.execute_gateway(['--state-dir', str(tmp_path / 'state'), 'profiler-voice-contributions',
        '--capture-ms', '123', '--voice-object-id', GUID, '--game-object-id', str(game_object_id)],
        env=_env(tmp_path, version=version), client_factory=lambda _: client)
    assert code == 0, json.dumps(payload)
    assert calls[-1] == (URI, {'voicePipelineID': 42, 'bussesPipelineID': [], 'time': 123}, {})

@pytest.mark.parametrize('version,invalid', [
    *((version, -1) for version in VERSIONS[:3]), ('2024.1', -(1 << 63) - 1), ('2025.1', 1 << 64),
])
def test_object_identity_contribution_rejects_outside_versioned_game_object_range(tmp_path, version, invalid):
    run, _, calls = task(tmp_path, version, URI, {})
    code, payload = run('profiler-voice-contributions', '--capture-ms', '123', '--voice-object-id', GUID,
        '--game-object-id', str(invalid))
    assert code == 2, json.dumps(payload)
    assert '--game-object-id' in payload['message']
    assert not calls

def retained_contribution(version):
    from tests.unit.test_fixed_runtime_read_branch_evidence import archive_reader
    from pathlib import Path
    import base64
    import gzip
    from tests.maintenance import branch_coverage_audit as audit
    originals = audit.ROOT / ('tests/fixtures/branch-evidence/product/runtime-rtpc-fields-r109/originals/2022.1'
        if version == '2022.1' else 'tests/fixtures/branch-evidence/product/runtime-read-r108')
    category = json.loads((originals / 'original-category.json').read_bytes())
    read = archive_reader(originals / 'original-closure.json.gz')
    seal = json.loads(read(category['categories'][0]['batch_finalization']['artifact']))
    node = json.loads(read(next(iter(seal['observations'].values()))['path']))
    receipt, = [row for row in node['receipts'] if row['argv'][0] == 'profiler-voice-contributions'
        and '--bus-instance-handle' in row['argv']]
    files = json.loads(gzip.decompress((originals / 'original-closure.json.gz').read_bytes()))['files']
    raw_name, = [name for name in files if name.endswith('/' + receipt['payload']['call']['evidence_path'].rsplit('/', 1)[1])]
    raw = json.loads(read(raw_name))
    args = receipt['payload']['semantic_preview']['args']
    rows = {}
    for suffix, identities in [('getVoices', [args['voicePipelineID']]), ('getBusses', args['bussesPipelineID'])]:
        matches = []
        for name in files:
            if name.endswith(f'-ak_wwise_core_profiler_{suffix}.json'):
                result = json.loads(read(name))['result']['return']
                if all(sum(row.get('pipelineID') == identity for row in result) == 1 for identity in identities):
                    matches.append(result)
        assert matches
        rows[suffix] = [deepcopy(next(row for row in matches[-1] if row['pipelineID'] == identity)) for identity in identities]
    return originals, receipt, raw, rows

def public_contribution_flow(root, version='2025.1', host='wwise-authoring', *, cursor=None, identity_forms='handles', retained=None):
    from tests.unit.test_runtime_business_gateway import gateway, _env, _RuntimeControlDraftClient
    context = None
    originals, original_receipt, raw, rows = retained if retained is not None else retained_contribution(version)
    source_args = original_receipt['payload']['semantic_preview']['args']
    root.mkdir(parents=True, exist_ok=True)
    client = _RuntimeControlDraftClient(root, version=version)
    original = client.call
    trace, public_calls = [], []
    def call(uri, args=None, options=None):
        if uri in (PREFIX + 'getVoices', PREFIX + 'getBusses'):
            result = {'return': deepcopy(rows[uri.rsplit('.', 1)[1]])}
        elif uri == URI:
            result = deepcopy(raw['result'])
        elif uri == PREFIX + 'getCursorTime':
            result = {'return': source_args['time']}
        else:
            result = original(uri, args, options)
            if uri == 'ak.wwise.core.getInfo':
                from tests.unit.test_rtpc_field_branch_evidence import BUILDS
                minor, build = BUILDS[version]
                result['isCommandLine'] = host == 'wwise-console'
                result['version'].update(minor=minor, build=build, displayName=f'v{version}.{minor}.{build}')
        trace.append({'ordinal': len(trace), 'uri': uri, 'args': deepcopy(args),
            'options': deepcopy(options), 'result': deepcopy(result)})
        return result
    client.call = call
    env = _env(root, version=version)
    def run(argv):
        start = len(trace)
        code, payload = gateway.execute_gateway(['--state-dir', str(root / 'state'), *argv], env=env,
            client_factory=lambda _: client)
        assert code == 0, json.dumps(payload)
        receipt = {'argv': argv, 'exit_code': code, 'payload': payload}
        public_calls.append({'gateway': deepcopy(receipt), 'native_start': start, 'native_end': len(trace)})
        return receipt
    position = str(source_args['time'])
    voice = run(['core-call', PREFIX + 'getVoices', '--profiler-position', position, '--max-results', '64'])
    busses = (run(['core-call', PREFIX + 'getBusses', '--profiler-position', position, '--max-results', '64'])
        if source_args.get('bussesPipelineID') else None)
    capture = ['--capture-ms', position] if cursor is None else ['--capture', cursor]
    selected_voice = (['--voice-object-id', rows['getVoices'][0]['objectGUID']]
        if identity_forms == 'object-voice' else ['--voice-instance-handle',
            voice['payload']['agent_result']['return'][0]['voice_instance_handle']])
    selected_busses = [] if not source_args.get('bussesPipelineID') else ([value for row in rows['getBusses'] for value in ('--bus-object-id', row['objectGUID'])]
        if identity_forms == 'object-bus' else [value for row in busses['payload']['agent_result']['return']
            for value in ('--bus-instance-handle', row['bus_instance_handle'])])
    argv = ['profiler-voice-contributions', *capture, *selected_voice, *selected_busses]
    receipt = run(argv)
    assert receipt['payload']['semantic_preview']['args'] == source_args
    assert receipt['payload']['agent_result'] == original_receipt['payload']['agent_result']
    final = {key: trace[-1][key] for key in ('uri', 'args', 'options', 'result')}
    assert final['uri'] == URI and final['result'] == raw['result']
    return receipt, final, context, trace, public_calls, originals

@pytest.mark.parametrize('version', ('2022.1', '2025.1'))
def test_complete_retained_contribution_replays_with_current_issued_handles(tmp_path, version):
    receipt, native, _, _, _, _ = public_contribution_flow(tmp_path, version)
    assert len(receipt['payload']['agent_result']['objects']) == 7
    assert native['result']['return']['volume'] == -9.0

def contribution_result(version, mode):
    if mode in ('absent', 'cursor-capture', 'cursor-user'):
        return {}
    if mode == 'partial':
        return {'return': {}}
    objects = []
    if mode == 'rich':
        parameters = [
            {'driver': GUID, 'driverValue': GUID, 'propertyType': 'Volume', 'reason': 'State', 'value': -3.0},
            {'driver': 'SoundBankValue', 'driverValue': 1.5, 'propertyType': 'Volume', 'reason': 'SoundBankValue', 'value': -3.0},
            {'driver': '', 'driverValue': 0.0, 'propertyType': '', 'reason': '', 'value': 0.0}, {}]
        for index in (0, (1 << 32) - 1):
            objects.append({'name': 'Voice', 'volume': -3.0, 'LPF': 0.0, 'HPF': 0.0,
                'children': [{}, {'name': 'Child', 'children': [], 'parameters': []}], 'parameters': deepcopy(parameters),
                **({'index': index} if version in ('2024.1', '2025.1') else {}),
                **({'DSF': 0.0} if version == '2025.1' else {})})
        objects[1]['children'] = []
        objects[1]['parameters'] = []
        objects.append({})
    elif mode == 'single':
        objects = [{'name': '', 'children': [{}], 'parameters': [{}]}]
    return {'return': {'volume': -3.0, 'LPF': 0.0, 'HPF': 0.0, 'objects': objects,
        **({'DSF': 0.0} if version == '2025.1' else {})}}

def public_contribution_case(root, version, host, mode):
    from tests.unit.test_runtime_business_gateway import gateway, _env, _RuntimeControlDraftClient
    from tests.unit.test_rtpc_field_branch_evidence import BUILDS
    context = None
    root.mkdir(parents=True, exist_ok=True)
    client = _RuntimeControlDraftClient(root, version=version)
    original = client.call
    bus_guids = ['{22222222-2222-2222-2222-222222222222}', '{33333333-3333-3333-3333-333333333333}']
    game_object = -(1 << 63) if version in ('2024.1', '2025.1') else 0
    def identity(pipeline, guid):
        return {'pipelineID': pipeline, 'objectGUID': guid, 'objectName': 'Voice',
            'gameObjectID': game_object, 'gameObjectName': 'Object'}
    trace = []
    def call(uri, args=None, options=None):
        if uri == PREFIX + 'getVoices':
            result = {'return': [identity(0, GUID)]}
        elif uri == PREFIX + 'getBusses':
            result = {'return': [identity(index, guid) for index, guid in zip((1, (1 << 32) - 1), bus_guids)]}
        elif uri == URI:
            result = contribution_result(version, mode)
        elif uri == PREFIX + 'getCursorTime':
            result = {'return': 123}
        else:
            result = original(uri, args, options)
            if uri == 'ak.wwise.core.getInfo':
                minor, build = BUILDS[version]
                result['isCommandLine'] = host == 'wwise-console'
                result['version'].update(minor=minor, build=build, displayName=f'v{version}.{minor}.{build}')
        trace.append({'ordinal': len(trace), 'uri': uri, 'args': deepcopy(args), 'options': deepcopy(options), 'result': deepcopy(result)})
        return result
    client.call = call
    argv = ['profiler-voice-contributions', '--voice-object-id', GUID, '--game-object-id', str(game_object)]
    argv += ['--capture', 'latest' if mode == 'cursor-capture' else 'user-cursor'] if mode.startswith('cursor-') else ['--capture-ms', '0' if mode == 'empty' else '123']
    if mode in ('rich', 'single'):
        argv += [value for guid in bus_guids[:2 if mode == 'rich' else 1] for value in ('--bus-object-id', guid)]
    elif mode == 'omit':
        argv += ['--bus-path', 'wwise-default']
    code, payload = gateway.execute_gateway(['--state-dir', str(root / 'state'), *argv], env=_env(root, version=version),
        client_factory=lambda _: client)
    assert code == 0, json.dumps(payload)
    receipt = {'argv': argv, 'exit_code': code, 'payload': payload}
    native = {key: trace[-1][key] for key in ('uri', 'args', 'options', 'result')}
    assert native['uri'] == URI
    return receipt, native, context, trace, [{'gateway': deepcopy(receipt), 'native_start': 0, 'native_end': len(trace)}]

@pytest.mark.parametrize('returned', (777, -1, True, 1.5), ids=('fixed-time', 'negative', 'boolean', 'noninteger'))
def test_contribution_cursor_snapshots_once_before_selecting_voice_and_bus(tmp_path, returned):
    from tests.unit.test_runtime_business_gateway import gateway, _env, _RuntimeControlDraftClient
    client = _RuntimeControlDraftClient(tmp_path, version='2025.1')
    original, calls = client.call, []
    bus = '{22222222-2222-2222-2222-222222222222}'
    def call(uri, args=None, options=None):
        calls.append((uri, deepcopy(args), deepcopy(options)))
        if uri == PREFIX + 'getCursorTime':
            # A moving cursor would advance on every resolution; only the first
            # fixed T is allowed to own the selected identities and final data.
            count = sum(row[0] == uri for row in calls)
            return {'return': returned if count == 1 else 778}
        if uri in (PREFIX + 'getVoices', PREFIX + 'getBusses'):
            return {'return': [{'pipelineID': 42 if uri.endswith('getVoices') else 43,
                'gameObjectID': 1, 'objectGUID': GUID if uri.endswith('getVoices') else bus,
                'objectName': 'selected at T', 'gameObjectName': 'Game'}]}
        if uri == URI:
            return {'return': {'volume': -9.0 if args['time'] == 777 else -99.0,
                'LPF': 0.0, 'HPF': 0.0, 'DSF': 0.0, 'objects': []}}
        return original(uri, args, options)
    client.call = call
    code, payload = gateway.execute_gateway(['--state-dir', str(tmp_path / 'state'),
        'profiler-voice-contributions', '--capture', 'latest', '--voice-object-id', GUID,
        '--bus-object-id', bus], env=_env(tmp_path, version='2025.1'), client_factory=lambda _: client)
    assert sum(row[0] == PREFIX + 'getCursorTime' for row in calls) == 1, payload
    dependent = [row for row in calls if row[0] in {PREFIX + 'getVoices', PREFIX + 'getBusses', URI}]
    if type(returned) is int and returned >= 0:
        assert code == 0, payload
        assert payload['agent_result']['volume'] == -9.0
        assert [row[1]['time'] for row in dependent] == [777, 777, 777]
    else:
        assert code != 0, payload
        assert not dependent

def test_contribution_malformed_cursor_root_has_bounded_public_error_context(tmp_path):
    from tests.unit.test_runtime_business_gateway import gateway, _env, _RuntimeControlDraftClient
    client = _RuntimeControlDraftClient(tmp_path, version='2025.1')
    original, calls = client.call, []
    def call(uri, args=None, options=None):
        calls.append(uri)
        return None if uri == PREFIX + 'getCursorTime' else original(uri, args, options)
    client.call = call
    code, payload = gateway.execute_gateway(['--state-dir', str(tmp_path / 'state'),
        'profiler-voice-contributions', '--capture', 'latest', '--voice-object-id', GUID],
        env=_env(tmp_path, version='2025.1'), client_factory=lambda _: client)
    assert code == 2, payload
    assert payload['error_code'] == 'INVALID_STABLE_READ_RESULT'
    assert payload['details']['api'] == PREFIX + 'getCursorTime'
    assert payload['details']['cursor'] == 'capture'
    assert payload['details']['result'] == 'None'
    assert PREFIX + 'getVoices' not in calls and URI not in calls

def test_contribution_cursor_preserves_issued_handle_context_and_fixed_numeric_projection(tmp_path):
    receipt, native, _, trace, calls, _ = public_contribution_flow(tmp_path, cursor='latest')
    final = trace[calls[-1]['native_start']:]
    cursor, = [row for row in final if row['uri'] == PREFIX + 'getCursorTime']
    dependent = [row for row in final if row['uri'] in {PREFIX + 'getVoices', PREFIX + 'getBusses', URI}]
    assert cursor['args'] == {'cursor': 'capture'}
    assert cursor['result'] == {'return': 30837}
    assert [row['args']['time'] for row in dependent] == [30837, 30837, 30837]
    assert all(row['ordinal'] > cursor['ordinal'] for row in dependent)
    assert native['args'] == {'bussesPipelineID': [2], 'time': 30837, 'voicePipelineID': 1}
    assert receipt['payload']['agent_result']['volume'] == -9.0

@pytest.mark.parametrize('identity_forms', ('object-voice', 'object-bus'))
def test_contribution_mixed_identity_forms_preserve_selected_bus_path(tmp_path, identity_forms):
    receipt, native, _, trace, calls, _ = public_contribution_flow(tmp_path, identity_forms=identity_forms)
    final = trace[calls[-1]['native_start']:]
    assert [row['uri'] for row in final if row['uri'] in {PREFIX + 'getVoices', PREFIX + 'getBusses', URI}] == [
        PREFIX + 'getVoices', PREFIX + 'getBusses', URI]
    assert native['args'] == {'bussesPipelineID': [2], 'time': 30837, 'voicePipelineID': 1}
    assert receipt['payload']['agent_result']['volume'] == -9.0

@pytest.mark.parametrize(('identity_forms', 'damage'), (
    ('object-voice', 'cross-game'), ('object-bus', 'cross-game'), ('object-voice', 'stale-handle')))
def test_contribution_shared_bus_tail_rejects_cross_game_or_stale_bus(tmp_path, identity_forms, damage):
    from tests.unit.test_runtime_business_gateway import gateway, _env, _RuntimeControlDraftClient
    from tests.unit.test_runtime_result_reference_gateway import profiler_row
    voice = profiler_row('getVoices', '2025.1')
    voice.update(gameObjectID=1)
    bus = profiler_row('getBusses', '2025.1')
    bus.update(pipelineID=43, objectGUID='{22222222-2222-2222-2222-222222222222}',
        gameObjectID=2 if damage == 'cross-game' else 1)
    client = _RuntimeControlDraftClient(tmp_path, version='2025.1')
    original, calls, final = client.call, [], False
    def call(uri, args=None, options=None):
        calls.append(uri)
        if uri == PREFIX + 'getVoices':
            return {'return': [deepcopy(voice)]}
        if uri == PREFIX + 'getBusses':
            row = deepcopy(bus)
            if final and damage == 'stale-handle':
                row['objectGUID'] = '{33333333-3333-3333-3333-333333333333}'
            return {'return': [row]}
        return original(uri, args, options)
    client.call = call
    env = _env(tmp_path, version='2025.1')
    def run(argv):
        return gateway.execute_gateway(['--state-dir', str(tmp_path / 'state'), *argv], env=env, client_factory=lambda _: client)
    seed_uri = PREFIX + ('getBusses' if identity_forms == 'object-voice' else 'getVoices')
    code, seed = run(['core-call', seed_uri, '--profiler-position', '123'])
    assert code == 0, seed
    if identity_forms == 'object-voice':
        selectors = ['--voice-object-id', GUID, '--bus-instance-handle', seed['agent_result']['return'][0]['bus_instance_handle']]
    else:
        selectors = ['--voice-instance-handle', seed['agent_result']['return'][0]['voice_instance_handle'], '--bus-object-id', bus['objectGUID']]
    final = True
    start = len(calls)
    code, payload = run(['profiler-voice-contributions', '--capture-ms', '123', *selectors])
    assert URI not in calls[start:], payload
    if damage == 'cross-game':
        assert code == 0 and payload['status'] == 'needs_clarification', payload
        assert payload['agent_result']['matching_bus_count'] == 0
    else:
        assert code == 2 and 'identity changed' in payload['message'], payload

def test_contribution_shared_bus_tail_preserves_homogeneous_object_order(tmp_path):
    _, native, _, _, _ = public_contribution_case(tmp_path, '2025.1', 'wwise-authoring', 'rich')
    assert native['args'] == {'voicePipelineID': 0, 'bussesPipelineID': [1, (1 << 32) - 1], 'time': 123}
