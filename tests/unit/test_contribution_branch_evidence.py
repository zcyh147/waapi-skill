"""Public contribution flows retain exact versioned branch evidence."""
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
    from pathlib import Path
    import base64
    import gzip
    from tests.maintenance import branch_coverage_audit as audit
    from tests.support.runtime_observation_evidence import archive_reader, sha
    originals = audit.ROOT / ('tests/fixtures/branch-evidence/product/runtime-rtpc-fields-r109/originals/2022.1'
        if version == '2022.1' else 'tests/fixtures/branch-evidence/product/runtime-read-r108')
    category = json.loads((originals / 'original-category.json').read_bytes())
    archive = {'artifact': 'original-closure.json.gz', 'sha256': sha((originals / 'original-closure.json.gz').read_bytes())}
    read = archive_reader(archive, originals)
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
    from tests.support.runtime_observation_evidence import program_source_context
    from tests.unit.test_runtime_business_gateway import gateway, _env, _RuntimeControlDraftClient
    context = program_source_context(flow=URI)
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
    busses = run(['core-call', PREFIX + 'getBusses', '--profiler-position', position, '--max-results', '64'])
    capture = ['--capture-ms', position] if cursor is None else ['--capture', cursor]
    selected_voice = (['--voice-object-id', rows['getVoices'][0]['objectGUID']]
        if identity_forms == 'object-voice' else ['--voice-instance-handle',
            voice['payload']['agent_result']['return'][0]['voice_instance_handle']])
    selected_busses = ([value for row in rows['getBusses'] for value in ('--bus-object-id', row['objectGUID'])]
        if identity_forms == 'object-bus' else [value for row in busses['payload']['agent_result']['return']
            for value in ('--bus-instance-handle', row['bus_instance_handle'])])
    argv = ['profiler-voice-contributions', *capture, *selected_voice, *selected_busses]
    receipt = run(argv)
    assert receipt['payload']['semantic_preview']['args'] == source_args
    assert receipt['payload']['agent_result'] == original_receipt['payload']['agent_result']
    final = {key: trace[-1][key] for key in ('uri', 'args', 'options', 'result')}
    assert final['uri'] == URI and final['result'] == raw['result']
    return receipt, final, context, trace, public_calls, originals


@pytest.fixture(scope='module')
def inventory():
    from tests.maintenance import branch_coverage_audit as audit
    return audit.build_inventory()


def test_one_contribution_flow_reaches_final_consumer_and_binds_public_projection(tmp_path, inventory):
    from tests.support.runtime_observation_evidence import write_program_receipt, write_read_bundle, write_json
    from tests.maintenance import branch_coverage_audit as audit
    from tests.maintenance import branch_audit_completion as completion
    receipt, native, context, trace, public_calls, originals = public_contribution_flow(tmp_path)
    capture = tmp_path / 'capture.json'
    write_program_receipt(capture, receipt, native, nodeid='contribution-top2025',
        phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context,
        native_reads=trace, public_calls=public_calls)
    index = write_read_bundle(tmp_path / 'bundle', capture, originals, inventory=inventory,
        version='2025.1', host='wwise-authoring', mode='top-data')
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, policy)
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    selected = [row for row in result['obligations'] if row['id'] in document['bindings']]
    assert len(selected) == 4
    assert {row['state'] for row in selected} == {'verified'}, json.dumps(selected)
    identity = next(key for key in document['bindings'] if key.endswith('/properties/volume'))
    binding = document['bindings'][identity]
    document['bindings'] = {identity: binding}
    program = completion.read_sealed_artifact(binding['evidence']['program'], base)
    program['gateway']['payload']['agent_result']['volume'] = -8.0
    program['runtime_read_program']['gateway'] = deepcopy(program['gateway'])
    program['runtime_read_program']['public_calls'][-1]['gateway'] = deepcopy(program['gateway'])
    for check in program['branch_assertions'][identity]['checks']:
        if check['pointer'] == '/gateway/payload/agent_result/volume':
            check['equals'] = -8.0
    proof = completion.read_sealed_artifact(binding['runtime_observation_attachment'], base)
    proof['program_capture'] = write_json(base / 'damaged-capture.json', program['runtime_read_program'])
    binding['runtime_observation_attachment'] = write_json(base / 'damaged-proof.json', proof)
    binding['evidence']['program'].update(write_json(base / 'damaged-program.json', program))
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    damaged = next(row for row in result['obligations'] if row['id'] == identity)
    assert damaged['evidence_results']['program']['outcome'] == 'missing', json.dumps(damaged)
    assert 'complete contribution projection' in damaged['evidence_results']['program']['reason']


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
    from tests.support.runtime_observation_evidence import program_source_context
    from tests.unit.test_runtime_business_gateway import gateway, _env, _RuntimeControlDraftClient
    from tests.unit.test_rtpc_field_branch_evidence import BUILDS
    context = program_source_context(flow=URI)
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


@pytest.fixture(scope='module')
def contribution_batch(tmp_path_factory, inventory):
    from tests.support.runtime_observation_evidence import write_program_receipt, write_read_stage
    root = tmp_path_factory.mktemp('contribution-batch')
    captures, originals = {}, {}
    for version in VERSIONS:
        for host in ('wwise-console', 'wwise-authoring'):
            modes = ['rich', 'single', 'empty', 'absent', 'omit', 'cursor-capture', 'cursor-user']
            if version in ('2021.1', '2022.1'):
                modes += ['partial']
            for mode in modes:
                receipt, native, context, trace, calls = public_contribution_case(root / f'{version}-{host}-{mode}', version, host, mode)
                path = root / f'{version}-{host}-{mode}.json'
                write_program_receipt(path, receipt, native, nodeid=f'{version}-{host}-{mode}', source_context=context,
                    native_reads=trace, public_calls=calls, phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'))
                captures[version, host, mode] = path
        if version in ('2022.1', '2025.1'):
            receipt, native, context, trace, calls, original = public_contribution_flow(root / f'{version}-original', version)
            path = root / f'{version}-original.json'
            write_program_receipt(path, receipt, native, nodeid=f'{version}-original', source_context=context,
                native_reads=trace, public_calls=calls, phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'))
            captures[version, 'wwise-authoring', 'original'] = path
            originals[version] = original
    return write_read_stage(root / 'bundle', captures, originals, inventory=inventory)


def test_shared_contribution_batch_maps_every_exact_reflected_branch(contribution_batch, inventory):
    from tests.maintenance import branch_coverage_audit as audit
    from tests.maintenance import branch_audit_completion as completion
    policy = json.loads((contribution_batch.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(contribution_batch, policy)
    assert len(document['bindings']) == 1080
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    selected = [row for row in result['obligations'] if row['id'] in document['bindings']]
    failed = [row for row in selected if row['evidence_results']['program']['outcome'] != 'passed']
    assert not failed, json.dumps([(row['id'], row['evidence_results']) for row in failed])
    native_failed = [(row['id'], row['evidence_results']) for row in selected
        if document['bindings'][row['id']].get('runtime_observation_attachment')
        and row['evidence_results']['native']['outcome'] != 'passed']
    assert not native_failed, json.dumps(native_failed)
    assert len(selected) == 1080
    assert sum(row['requirements'] == ['program'] for row in selected) >= 270
    assert {row['state'] for row in selected} <= {'verified', 'implemented_unverified'}
    assert all(row['evidence_results'].get('native', {}).get('outcome') == 'missing'
        for row in selected if row['requirements'] == ['native', 'program']
        and row['route'].split('|')[:2] not in (['2022.1', 'wwise-authoring'], ['2025.1', 'wwise-authoring']))


CONTRIBUTION_PROGRAM_CASES = [
    (version, host, mode)
    for version in VERSIONS for host in ('wwise-console', 'wwise-authoring')
    for mode in ('rich', 'single', 'empty', 'absent', 'omit', 'cursor-capture', 'cursor-user',
        *(('partial',) if version in ('2021.1', '2022.1') else ()))
] + [(version, 'wwise-authoring', 'original') for version in ('2022.1', '2025.1')]


@pytest.mark.parametrize(('version', 'host', 'mode'), CONTRIBUTION_PROGRAM_CASES,
    ids=['-'.join(case) for case in CONTRIBUTION_PROGRAM_CASES])
def test_contribution_program_emits_after_actual_teardown(tmp_path, request, version, host, mode):
    import os
    from pathlib import Path
    from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
    from tests.support.runtime_observation_evidence import write_program_receipt
    if mode == 'original':
        receipt, native, context, trace, calls, _ = public_contribution_flow(tmp_path, version, host)
    else:
        receipt, native, context, trace, calls = public_contribution_case(tmp_path, version, host, mode)
    destination = Path(os.environ.get('WAAPI_CONTRIBUTION_CAPTURE_DIR', tmp_path)) / f'{version}-{host}-{mode}.json'
    register_exact_evidence_finalizer(request.node, lambda phases: write_program_receipt(
        destination, receipt, native, nodeid=request.node.nodeid, phase_reports=phases,
        source_context=context, native_reads=trace, public_calls=calls))


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


def test_one_contribution_cursor_proves_fixed_time_construction_and_rejects_resealed_trace(tmp_path, inventory):
    from tests.support.runtime_observation_evidence import write_program_receipt, write_read_bundle, write_json
    from tests.maintenance import branch_coverage_audit as audit
    from tests.maintenance import branch_audit_completion as completion
    receipt, native, context, trace, calls = public_contribution_case(tmp_path / 'public', '2025.1', 'wwise-authoring', 'cursor-capture')
    capture = tmp_path / 'capture.json'
    write_program_receipt(capture, receipt, native, nodeid='contribution-cursor', source_context=context,
        native_reads=trace, public_calls=calls, phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'))
    index = write_read_bundle(tmp_path / 'bundle', capture, None, inventory=inventory,
        version='2025.1', host='wwise-authoring', mode='cursor-capture')
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, policy)
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    selected = [row for row in result['obligations'] if row['id'] in document['bindings']]
    assert len(selected) == 4
    assert {row['state'] for row in selected} == {'verified'}, json.dumps(selected)
    identity = next(key for key in document['bindings'] if key.endswith('/profilerCursor/enum/1'))
    binding = document['bindings'][identity]
    document['bindings'] = {identity: binding}
    program = completion.read_sealed_artifact(binding['evidence']['program'], base)
    cursor = next(row for row in program['runtime_read_program']['native_reads'] if row['uri'].endswith('getCursorTime'))
    cursor['result']['return'] += 1
    binding['evidence']['program'].update(write_json(base / 'damaged-program.json', program))
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    changed = next(row for row in result['obligations'] if row['id'] == identity)
    assert changed['evidence_results']['program']['outcome'] == 'missing', json.dumps(changed)
    assert 'fixed cursor construction trace' in changed['evidence_results']['program']['reason']


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


def test_shared_contribution_cursor_batch_proves_exact_fifty_normalized_branches(tmp_path, inventory):
    from tests.support.runtime_observation_evidence import write_program_receipt, write_read_stage, write_json
    from tests.maintenance import branch_coverage_audit as audit
    from tests.maintenance import branch_audit_completion as completion
    captures = {}
    for version in VERSIONS:
        for host in ('wwise-console', 'wwise-authoring'):
            for mode in ('cursor-capture', 'cursor-user'):
                receipt, native, context, trace, calls = public_contribution_case(tmp_path / f'{version}-{host}-{mode}', version, host, mode)
                path = tmp_path / f'{version}-{host}-{mode}.json'
                write_program_receipt(path, receipt, native, nodeid=f'{version}-{host}-{mode}', source_context=context,
                    native_reads=trace, public_calls=calls, phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'))
                captures[version, host, mode] = path
    index = write_read_stage(tmp_path / 'bundle', captures, {}, inventory=inventory)
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, policy)
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    selected = [row for row in result['obligations'] if row['id'] in document['bindings']]
    write_json(tmp_path / 'cursor-final-consumer.json', selected)
    assert len(selected) == 50
    assert all(row['requirements'] == ['program'] and row['state'] == 'verified' for row in selected), json.dumps(selected)



@pytest.mark.parametrize('identity_forms', ('object-voice', 'object-bus'))
def test_contribution_mixed_identity_forms_preserve_selected_bus_path(tmp_path, identity_forms):
    receipt, native, _, trace, calls, _ = public_contribution_flow(tmp_path, identity_forms=identity_forms)
    final = trace[calls[-1]['native_start']:]
    assert [row['uri'] for row in final if row['uri'] in {PREFIX + 'getVoices', PREFIX + 'getBusses', URI}] == [
        PREFIX + 'getVoices', PREFIX + 'getBusses', URI]
    assert native['args'] == {'bussesPipelineID': [2], 'time': 30837, 'voicePipelineID': 1}
    assert receipt['payload']['agent_result']['volume'] == -9.0


@pytest.mark.parametrize('identity_forms', ('object-voice', 'object-bus'))
def test_mixed_contribution_program_binds_each_selected_bus_form(tmp_path, inventory, identity_forms):
    from tests.support.runtime_observation_evidence import write_program_receipt, write_read_bundle, write_json
    from tests.maintenance import branch_coverage_audit as audit
    from tests.maintenance import branch_audit_completion as completion
    receipt, native, context, trace, calls, _ = public_contribution_flow(tmp_path / 'public', identity_forms=identity_forms)
    capture = tmp_path / 'capture.json'
    write_program_receipt(capture, receipt, native, nodeid='mixed-contribution', source_context=context,
        native_reads=trace, public_calls=calls, phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'))
    index = write_read_bundle(tmp_path / 'bundle', capture, None, inventory=inventory,
        version='2025.1', host='wwise-authoring', mode='top-data')
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, policy)
    identity = next(key for key in document['bindings'] if key.endswith('/properties/volume'))
    binding = document['bindings'][identity]
    document['bindings'] = {identity: binding}
    def outcome():
        result = completion.evaluate_coverage(audit.ROOT, inventory, document,
            digest=audit.digest, evidence_base=base, requirements_document=policy)
        return next(row['evidence_results']['program'] for row in result['obligations'] if row['id'] == identity)
    assert outcome()['outcome'] == 'passed'
    program = completion.read_sealed_artifact(binding['evidence']['program'], base)
    for target in (program, program['runtime_read_program']):
        target['native_call']['args']['bussesPipelineID'] = []
        target['gateway']['payload']['semantic_preview']['args']['bussesPipelineID'] = []
    program['runtime_read_program']['public_calls'][-1]['gateway'] = deepcopy(program['gateway'])
    program['runtime_read_program']['native_reads'][-1]['args']['bussesPipelineID'] = []
    binding['evidence']['program'].update(write_json(base / 'damaged-program.json', program))
    assert outcome()['outcome'] == 'missing'


def test_contribution_cursor_proof_rejects_resealed_integral_float_snapshot(tmp_path, inventory):
    from tests.support.runtime_observation_evidence import write_program_receipt, write_read_bundle, write_json
    from tests.maintenance import branch_coverage_audit as audit
    from tests.maintenance import branch_audit_completion as completion
    receipt, native, context, trace, calls = public_contribution_case(tmp_path / 'public', '2025.1', 'wwise-authoring', 'cursor-capture')
    capture = tmp_path / 'capture.json'
    write_program_receipt(capture, receipt, native, nodeid='typed-contribution-cursor', source_context=context,
        native_reads=trace, public_calls=calls, phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'))
    index = write_read_bundle(tmp_path / 'bundle', capture, None, inventory=inventory,
        version='2025.1', host='wwise-authoring', mode='cursor-capture')
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, policy)
    identity = next(key for key in document['bindings'] if key.endswith('/profilerCursor/enum/1'))
    binding = document['bindings'][identity]
    document['bindings'] = {identity: binding}
    def outcome():
        result = completion.evaluate_coverage(audit.ROOT, inventory, document,
            digest=audit.digest, evidence_base=base, requirements_document=policy)
        return next(row['evidence_results']['program'] for row in result['obligations'] if row['id'] == identity)
    assert outcome()['outcome'] == 'passed'
    program = completion.read_sealed_artifact(binding['evidence']['program'], base)
    cursor = next(row for row in program['runtime_read_program']['native_reads'] if row['uri'] == PREFIX + 'getCursorTime')
    cursor['result']['return'] = float(cursor['result']['return'])
    binding['evidence']['program'].update(write_json(base / 'damaged-program.json', program))
    rejected = outcome()
    assert rejected['outcome'] == 'missing', json.dumps(rejected)
    assert 'fixed cursor construction trace' in rejected['reason']


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
