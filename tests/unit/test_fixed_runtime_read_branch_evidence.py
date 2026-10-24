"""Fixed Profiler readers publish exact public branches through the audit consumer."""
from copy import deepcopy
import json
import time
from pathlib import Path

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support.runtime_observation_evidence import archive_reader, sha, program_source_context, write_json, write_program_receipt
from tests.unit.test_runtime_business_gateway import gateway, _env, _RuntimeControlDraftClient

FIXTURE = audit.ROOT / 'tests/fixtures/runtime-fixed-reads'
NODEID = 'tests/destructive/test_authoring_ui_business_live.py::test_runtime_owned_2025_profiler_readers'
URI = 'ak.wwise.core.profiler.getVoices'


def original_read(uri=URI, *, filtered=False):
    descriptor = {'artifact': 'r103-originals.json.gz', 'sha256': sha((FIXTURE / 'r103-originals.json.gz').read_bytes())}
    read = archive_reader(descriptor, FIXTURE)
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
                      view='diagnostics', position='40042', fields=None, uri=URI, filtered=False, public_calls=None, handle_index=0, seed_rows=None):
    operation = uri
    original, raw = original_read(operation, filtered=filtered)
    context = program_source_context(flow=operation)
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


@pytest.fixture(scope='module')
def inventory(request):
    started = time.perf_counter()
    result = audit.build_inventory()
    request.config._fixed_inventory_seconds = time.perf_counter() - started
    return result


def test_one_complete_fixed_reader_reaches_portable_final_consumer(tmp_path, inventory):
    receipt, native, context, trace = public_fixed_read(tmp_path / 'public')
    assert receipt['payload']['agent_result']['return'][0]['objectGUID'] == '{FBF74BF9-8B83-44A8-AC8A-BA85372ECDC4}'
    assert len(native['options']['return']) == 20
    capture = tmp_path / 'capture.json'
    write_program_receipt(capture, receipt, native, nodeid='fixed-voices2025',
        phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context,
        native_reads=trace, public_calls=[{'gateway': receipt, 'native_start': 0, 'native_end': len(trace)}])
    from tests.support.fixed_runtime_read_evidence import write_fixed_bundle
    route = next(row for row in inventory['native_coverage']['routes']
        if row['uri'] == URI and row['version'] == '2025.1' and row['host'] == 'wwise-authoring')
    identity = route['id'] + '|/resultSchema/@definition/waapi_definitions.json/definitions/voiceReturn/properties/objectGUID'
    index = write_fixed_bundle(tmp_path / 'bundle', capture, FIXTURE, inventory=inventory, selected={identity})
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, policy)
    def observed():
        result = completion.evaluate_coverage(audit.ROOT, inventory, document,
            digest=audit.digest, evidence_base=base, requirements_document=policy)
        return next(r for r in result['obligations'] if r['id'] == identity)
    row = observed()
    assert row['state'] == 'verified', json.dumps(row)
    binding = document['bindings'][identity]
    program = completion.read_sealed_artifact(binding['evidence']['program'], base)
    program['gateway']['payload']['agent_result']['return'][0]['objectGUID'] = '{11111111-1111-1111-1111-111111111111}'
    program['runtime_read_program']['gateway'] = deepcopy(program['gateway'])
    program['runtime_read_program']['public_calls'][-1]['gateway'] = deepcopy(program['gateway'])
    for check in program['branch_assertions'][identity]['checks']:
        if check['pointer'] == binding['gateway_observation_pointer']:
            check['equals'] = completion.pointer_value(program, check['pointer'])
    proof = completion.read_sealed_artifact(binding['runtime_observation_attachment'], base)
    proof['program_capture'] = write_json(base / 'changed-capture.json', program['runtime_read_program'])
    binding['runtime_observation_attachment'] = write_json(base / 'changed-proof.json', proof)
    binding['evidence']['program'].update(write_json(base / 'changed-program.json', program))
    damaged = observed()
    assert damaged['evidence_results']['program']['outcome'] == 'missing', json.dumps(damaged)
    assert 'complete native/public fixed-row projection' in damaged['evidence_results']['program']['reason']


@pytest.mark.parametrize('family', ('numeric', 'omitted', 'empty', 'cursor-capture', 'cursor-user'))
def test_representative_fixed_reader_program_families(tmp_path, inventory, family):
    from tests.support.fixed_runtime_read_evidence import write_fixed_bundle
    version = '2022.1' if family == 'empty' else '2025.1'
    view = 'capture-defaults' if family == 'omitted' else 'empty-selection' if family == 'empty' else 'diagnostics'
    position = 'capture-latest' if family == 'cursor-capture' else 'user-cursor' if family == 'cursor-user' else '0'
    receipt, native, context, trace = public_fixed_read(tmp_path / 'public', version=version, view=view, position=position,
        rows=[] if family == 'omitted' else [{}] if family == 'empty' else None)
    capture = tmp_path / 'capture.json'
    write_program_receipt(capture, receipt, native, nodeid='fixed-family-' + family,
        phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context,
        native_reads=trace, public_calls=[{'gateway': receipt, 'native_start': 0, 'native_end': len(trace)}])
    route = next(r for r in inventory['native_coverage']['routes'] if r['version'] == version and r['host'] == 'wwise-authoring' and r['uri'] == URI)
    definitions = '/@definition/waapi_definitions.json/definitions/'
    pointers = ({'/argsSchema', '/argsSchema/additionalProperties', '/argsSchema/properties/time', '/argsSchema/properties/time/$ref',
        '/argsSchema' + definitions + 'cursorTime', '/argsSchema' + definitions + 'cursorTime/oneOf/0',
        '/argsSchema' + definitions + 'cursorTime/oneOf/0/minimum', '/optionsSchema', '/optionsSchema/additionalProperties',
        '/optionsSchema/properties/return', '/optionsSchema/properties/return/$ref', '/optionsSchema' + definitions + 'voiceReturnOptions',
        '/optionsSchema' + definitions + 'voiceReturnOptions/items/enum/0', '/optionsSchema' + definitions + 'voiceReturnOptions/@cardinality/multiple',
        '/resultSchema', '/resultSchema/additionalProperties', '/resultSchema/properties/return', '/resultSchema/properties/return/items/$ref',
        '/resultSchema' + definitions + 'voiceReturn', '/resultSchema' + definitions + 'voiceReturn/properties/objectGUID/$ref',
        '/resultSchema/@definition/common_definitions.json/definitions/guid/pattern'} if family == 'numeric' else
        {'/optionsSchema', '/optionsSchema/@empty/object', '/optionsSchema/properties/return/@presence/absent',
         '/resultSchema', '/resultSchema/properties/return/@cardinality/empty'} if family == 'omitted' else
        {'/optionsSchema/properties/return/@presence/present', '/optionsSchema' + definitions + 'voiceReturnOptions/@cardinality/empty',
         '/resultSchema/properties/return/@cardinality/single', '/resultSchema' + definitions + 'voiceReturn/@empty/object'} if family == 'empty' else
        {'/argsSchema' + definitions + 'cursorTime/oneOf/1', '/argsSchema' + definitions + 'cursorTime/oneOf/1/$ref',
         '/argsSchema' + definitions + 'profilerCursor', '/argsSchema' + definitions + 'profilerCursor/enum/' + ('1' if family == 'cursor-capture' else '0')})
    selected = {route['id'] + '|' + pointer for pointer in pointers}
    index = write_fixed_bundle(tmp_path / 'bundle', capture, None, inventory=inventory, selected=selected)
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, policy)
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    observed = [r for r in result['obligations'] if r['id'] in selected]
    assert len(observed) == len(selected)
    assert all(r['evidence_results']['program']['outcome'] == 'passed' for r in observed), json.dumps(observed)
    assert all(r['state'] == ('implemented_unverified' if 'native' in r['requirements'] else 'verified') for r in observed), json.dumps(observed)


@pytest.mark.parametrize('selection', ('single', 'ordered-repeated'))
def test_explicit_fixed_fields_reach_consumer_with_exact_order_and_repetition(tmp_path, inventory, selection):
    from tests.support.fixed_runtime_read_evidence import write_fixed_bundle
    fields = ['objectName'] if selection == 'single' else ['baseVolume', 'objectName', 'baseVolume']
    receipt, native, context, trace = public_fixed_read(tmp_path / 'public', position='0', fields=fields)
    assert native['options'] == {'return': fields}
    assert {k for k in receipt['payload']['agent_result']['return'][0] if k != 'voice_instance_handle'} == set(fields)
    capture = tmp_path / 'capture.json'
    write_program_receipt(capture, receipt, native, nodeid='fixed-fields-' + selection,
        phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context,
        native_reads=trace, public_calls=[{'gateway': receipt, 'native_start': 0, 'native_end': len(trace)}])
    route = next(r for r in inventory['native_coverage']['routes'] if r['version'] == '2025.1' and r['host'] == 'wwise-authoring' and r['uri'] == URI)
    prefix = '/optionsSchema/@definition/waapi_definitions.json/definitions/voiceReturnOptions'
    pointers = {'/optionsSchema', '/optionsSchema/properties/return', '/optionsSchema/properties/return/$ref', prefix,
        prefix + '/@cardinality/' + ('single' if selection == 'single' else 'multiple')}
    selected = {route['id'] + '|' + pointer for pointer in pointers}
    selected.update(r['id'] for r in inventory['native_coverage']['obligations'] if r['route'] == route['id']
        and r['kind'] == 'enum_value' and r['pointer'].startswith('/optionsSchema') and r['value'] in fields)
    index = write_fixed_bundle(tmp_path / 'bundle', capture, None, inventory=inventory, selected=selected)
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, policy)
    def observed():
        result = completion.evaluate_coverage(audit.ROOT, inventory, document,
            digest=audit.digest, evidence_base=base, requirements_document=policy)
        return [r for r in result['obligations'] if r['id'] in document['bindings']]
    result = observed()
    assert {r['state'] for r in result} == {'verified'}, json.dumps(result)
    if selection == 'ordered-repeated':
        identity = route['id'] + '|/optionsSchema'
        document['bindings'] = {identity: document['bindings'][identity]}
        binding = document['bindings'][identity]
        program = completion.read_sealed_artifact(binding['evidence']['program'], base)
        changed = fields[1:] + fields[:1]
        program['native_call']['options']['return'] = changed
        captured = program['runtime_read_program']
        captured['native_call'] = deepcopy(program['native_call'])
        captured['native_reads'][-1]['options'] = deepcopy(program['native_call']['options'])
        program['branch_assertions'][identity]['checks'][0]['equals'] = {'return': changed}
        binding['evidence']['program'].update(write_json(base / 'wrong-order.json', program))
        damaged, = observed()
        assert damaged['evidence_results']['program']['outcome'] == 'missing', json.dumps(damaged)
        assert 'exact controlled request/options' in damaged['evidence_results']['program']['reason']


def test_fixed_cursor_consumer_rejects_resealed_integral_float_source(tmp_path, inventory):
    from tests.support.fixed_runtime_read_evidence import write_fixed_bundle
    receipt, native, context, trace = public_fixed_read(tmp_path / 'public', position='capture-latest')
    capture = tmp_path / 'capture.json'
    write_program_receipt(capture, receipt, native, nodeid='fixed-typed-cursor',
        phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context,
        native_reads=trace, public_calls=[{'gateway': receipt, 'native_start': 0, 'native_end': len(trace)}])
    route = next(r for r in inventory['native_coverage']['routes'] if r['version'] == '2025.1' and r['host'] == 'wwise-authoring' and r['uri'] == URI)
    identity = route['id'] + '|/argsSchema/@definition/waapi_definitions.json/definitions/cursorTime/oneOf/1'
    index = write_fixed_bundle(tmp_path / 'bundle', capture, None, inventory=inventory, selected={identity})
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, policy)
    binding = document['bindings'][identity]
    program = completion.read_sealed_artifact(binding['evidence']['program'], base)
    cursor, = [r for r in program['runtime_read_program']['native_reads'] if r['uri'].endswith('.getCursorTime')]
    cursor['result']['return'] = 123.0
    binding['evidence']['program'].update(write_json(base / 'float-source.json', program))
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    damaged = next(r for r in result['obligations'] if r['id'] == identity)
    assert damaged['evidence_results']['program']['outcome'] == 'missing', json.dumps(damaged)
    assert 'ordered typed cursor snapshot' in damaged['evidence_results']['program']['reason']


def typed_fixed_rows(version, uri, mode='rich'):
    """Small fixed-reader fixtures from the matching definition's scalar domains."""
    from wwise_waapi.native_catalog import load_native_catalog
    catalog = load_native_catalog(version, 'wwise-authoring')
    documents = catalog['definitions']['documents']
    def resolve(reference):
        name, pointer = reference.split('#', 1)
        return completion.pointer_value(documents[name or 'waapi_definitions.json'], pointer)
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
def test_typed_fixed_reader_result_families_reach_consumer(tmp_path, inventory, version, name, mode):
    from tests.support.fixed_runtime_read_evidence import write_fixed_bundle, mappings
    uri = 'ak.wwise.core.profiler.' + name
    receipt, native, context, trace = public_fixed_read(tmp_path / 'public', version=version, uri=uri,
        rows=typed_fixed_rows(version, uri, mode), position='0')
    capture = tmp_path / 'capture.json'
    write_program_receipt(capture, receipt, native, nodeid='fixed-typed-' + name,
        phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context,
        native_reads=trace, public_calls=[{'gateway': receipt, 'native_start': 0, 'native_end': len(trace)}])
    captured = json.loads(capture.read_bytes())
    route = next(r for r in inventory['native_coverage']['routes'] if r['version'] == version and r['host'] == 'wwise-authoring' and r['uri'] == uri)
    selected = {m['branch']['id'] for m in mappings(inventory, captured, route) if m['branch']['pointer'].startswith('/resultSchema')}
    assert selected
    index = write_fixed_bundle(tmp_path / 'bundle', capture, None, inventory=inventory, selected=selected)
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, policy)
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    observed = [r for r in result['obligations'] if r['id'] in selected]
    failures = [{k:r[k] for k in ('id','state','evidence_results')} for r in observed if r['evidence_results']['program']['outcome'] != 'passed']
    assert not failures, json.dumps(failures)
    assert {r['id'] for r in observed} == selected


@pytest.mark.parametrize('name,filtered', [
    ('getVoices', False), ('getBusses', False), ('getAudioObjects', False), ('getGameObjects', False),
    ('getVoices', True), ('getBusses', True), ('getAudioObjects', True),
])
def test_seven_original_fixed_arrays_replay_through_public_portable_consumer(tmp_path, inventory, name, filtered):
    from tests.support.fixed_runtime_read_evidence import write_fixed_bundle, mappings
    uri = 'ak.wwise.core.profiler.' + name
    calls = []
    receipt, native, context, trace = public_fixed_read(tmp_path / 'public', uri=uri, filtered=filtered, public_calls=calls)
    capture = tmp_path / 'capture.json'
    write_program_receipt(capture, receipt, native, nodeid='fixed-original-' + name + str(filtered),
        phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context,
        native_reads=trace, public_calls=calls)
    captured = json.loads(capture.read_bytes())
    route = next(r for r in inventory['native_coverage']['routes'] if r['version'] == '2025.1' and r['host'] == 'wwise-authoring' and r['uri'] == uri)
    selected = {m['branch']['id'] for m in mappings(inventory, captured, route) if m['categories'] == ['program', 'native']}
    assert selected
    index = write_fixed_bundle(tmp_path / 'bundle', capture, FIXTURE, inventory=inventory, selected=selected)
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, policy)
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    observed = [r for r in result['obligations'] if r['id'] in selected]
    failures = [{k:r[k] for k in ('id','state','evidence_results')} for r in observed if r['state'] != 'verified']
    assert not failures, json.dumps(failures)
    assert {r['id'] for r in observed} == selected


def test_fixed_handle_consumer_rejects_resealed_changed_identity(tmp_path, inventory):
    from tests.support.fixed_runtime_read_evidence import write_fixed_bundle
    calls = []
    receipt, native, context, trace = public_fixed_read(tmp_path / 'public', filtered=True, public_calls=calls)
    capture = tmp_path / 'capture.json'
    write_program_receipt(capture, receipt, native, nodeid='fixed-handle-causal',
        phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context,
        native_reads=trace, public_calls=calls)
    route = next(r for r in inventory['native_coverage']['routes'] if r['version'] == '2025.1' and r['host'] == 'wwise-authoring' and r['uri'] == URI)
    identity = route['id'] + '|/argsSchema'
    index = write_fixed_bundle(tmp_path / 'bundle', capture, None, inventory=inventory, selected={identity})
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, policy)
    def outcome():
        result = completion.evaluate_coverage(audit.ROOT, inventory, document,
            digest=audit.digest, evidence_base=base, requirements_document=policy)
        return next(r for r in result['obligations'] if r['id'] == identity)
    assert outcome()['state'] == 'verified'
    binding = document['bindings'][identity]
    program = completion.read_sealed_artifact(binding['evidence']['program'], base)
    captured = program['runtime_read_program']
    checked, = [r for r in captured['native_reads'][calls[-1]['native_start']:-1] if r['uri'] == URI]
    checked['result']['return'][0]['objectGUID'] = '{11111111-1111-1111-1111-111111111111}'
    binding['evidence']['program'].update(write_json(base / 'changed-identity.json', program))
    damaged = outcome()
    assert damaged['evidence_results']['program']['outcome'] == 'missing'
    assert 'issued handle identity' in damaged['evidence_results']['program']['reason']


FIXED_LANES = [(version, host, name) for version in ('2021.1','2022.1','2023.1','2024.1','2025.1')
    for host in ('wwise-console','wwise-authoring') for name in ('getVoices','getBusses','getAudioObjects','getGameObjects')
    if version != '2021.1' or name != 'getGameObjects']


def fixed_case_modes(version, name):
    modes = ['rich', 'empty', 'single', 'cursor-capture', 'cursor-user']
    if name == 'getAudioObjects': modes.append('empty-arrays')
    if name != 'getGameObjects': modes += ['absent', 'omit', 'empty-selection', 'single-field', 'filter-zero', 'filter-max']
    elif version == '2022.1': modes.append('absent')
    return modes


def fixed_program_case(tmp_path, version, host, name, mode):
    from wwise_waapi.native_catalog import load_native_catalog
    uri = 'ak.wwise.core.profiler.' + name
    catalog = load_native_catalog(version, host)
    position = 'capture-latest' if mode == 'cursor-capture' else 'user-cursor' if mode == 'cursor-user' else '0'
    shape = mode if mode in {'empty','single','empty-arrays','absent'} else 'rich'
    rows = typed_fixed_rows(version, uri, shape)
    view = 'capture-defaults' if mode == 'omit' else 'empty-selection' if mode == 'empty-selection' else 'diagnostics'
    fields = None
    if mode == 'rich' and name != 'getGameObjects':
        option = catalog['schemas'][uri]['optionsSchema']['properties']['return']['$ref'].rsplit('/',1)[1]
        fields = catalog['definitions']['documents']['waapi_definitions.json']['definitions'][option]['items']['enum']
    if mode == 'single-field': fields = ['audioObjectName' if name == 'getAudioObjects' else 'objectName']
    calls = []
    receipt, native, context, trace = public_fixed_read(tmp_path, version=version, host=host, uri=uri,
        rows=rows, view=view, position=position, fields=fields, filtered=mode.startswith('filter-'), public_calls=calls,
        handle_index=1 if mode == 'filter-max' else 0,
        seed_rows=typed_fixed_rows(version, 'ak.wwise.core.profiler.getBusses') if name == 'getAudioObjects' else None)
    return receipt, native, context, trace, calls


@pytest.mark.parametrize('version,host,name', FIXED_LANES)
def test_all_fixed_reader_branches_have_exact_public_program_evidence(tmp_path, inventory, request, version, host, name):
    from tests.support.fixed_runtime_read_evidence import write_fixed_stage
    from wwise_waapi.native_catalog import load_native_catalog
    uri = 'ak.wwise.core.profiler.' + name
    route = next(r for r in inventory['native_coverage']['routes'] if r['version'] == version and r['host'] == host and r['uri'] == uri)
    captures = []
    started = time.perf_counter()
    for mode in fixed_case_modes(version, name):
        receipt, native, context, trace, calls = fixed_program_case(tmp_path / mode, version, host, name, mode)
        path = tmp_path / (mode + '.json')
        write_program_receipt(path, receipt, native, nodeid='fixed-lane-' + name + '-' + mode,
            phase_reports=dict.fromkeys(('setup','call','teardown'), 'passed'), source_context=context,
            native_reads=trace, public_calls=calls)
        captures.append(path)
    captured_at = time.perf_counter()
    index = write_fixed_stage(tmp_path / 'bundle', captures, inventory=inventory, route_ids={route['id']})
    mapped_at = time.perf_counter()
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, policy)
    imported_at = time.perf_counter()
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    evaluated_at = time.perf_counter()
    write_json(tmp_path / 'phase-timings.json', {'inventory_seconds': request.config._fixed_inventory_seconds,
        'public_capture_seconds': captured_at - started, 'map_publish_seconds': mapped_at - captured_at,
        'portable_import_seconds': imported_at - mapped_at, 'evaluate_seconds': evaluated_at - imported_at})
    observed = [r for r in result['obligations'] if r['id'] in document['bindings']]
    failures = [{k:r[k] for k in ('id','state','evidence_results')} for r in observed if r['evidence_results']['program']['outcome'] != 'passed']
    assert not failures, json.dumps(failures)
    assert {r['id'] for r in observed} == set(policy['branches'])
    assert all(r['state'] == ('verified' if r['requirements'] == ['program'] else 'implemented_unverified') for r in observed)


def test_shared_fixed_stage_consumes_seven_originals_without_duplicate_credit(tmp_path, inventory):
    from tests.support.fixed_runtime_read_evidence import write_fixed_stage, mappings, CATEGORIES
    captures, originals, selected = [], {}, set()
    for name, filtered, category in (
        ('getVoices', False, 'profiler-voices-observation'),
        ('getVoices', True, 'profiler-voice-instance-filter'),
        ('getBusses', False, 'profiler-busses-observation'),
        ('getBusses', True, 'profiler-bus-instance-filter'),
        ('getAudioObjects', False, 'profiler-audio-objects-observation'),
        ('getAudioObjects', True, 'profiler-audio-objects-bus-filter'),
        ('getGameObjects', False, 'profiler-game-objects-observation'),
    ):
        uri = 'ak.wwise.core.profiler.' + name
        calls = []
        receipt, native, context, trace = public_fixed_read(tmp_path / category, uri=uri, filtered=filtered, public_calls=calls)
        path = tmp_path / (category + '.json')
        write_program_receipt(path, receipt, native, nodeid='fixed-stage-' + category,
            phase_reports=dict.fromkeys(('setup','call','teardown'), 'passed'), source_context=context,
            native_reads=trace, public_calls=calls)
        originals[category] = path
        route = next(r for r in inventory['native_coverage']['routes'] if r['version'] == '2025.1' and r['host'] == 'wwise-authoring' and r['uri'] == uri)
        candidate_ids = sorted(m['branch']['id'] for m in mappings(inventory, json.loads(path.read_bytes()), route)
            if m['categories'] == ['program','native'])
        selected.update(candidate_ids[:1 if name == 'getGameObjects' else 2])
    receipt, native, context, trace = public_fixed_read(tmp_path / 'one-field', fields=['objectName'])
    path = tmp_path / 'one-field.json'
    write_program_receipt(path, receipt, native, nodeid='fixed-stage-one-field',
        phase_reports=dict.fromkeys(('setup','call','teardown'), 'passed'), source_context=context,
        native_reads=trace, public_calls=[{'gateway':receipt,'native_start':0,'native_end':len(trace)}])
    captures.append(path)
    voice_route = next(r for r in inventory['native_coverage']['routes'] if r['version'] == '2025.1' and r['host'] == 'wwise-authoring' and r['uri'] == URI)
    selected.add(voice_route['id'] + '|/argsSchema')
    assert len(selected) == 8
    index = write_fixed_stage(tmp_path / 'bundle', captures, inventory=inventory,
        original_captures=originals, originals=FIXTURE, selected_ids=selected)
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, policy)
    attached = [binding for binding in document['bindings'].values() if binding.get('runtime_observation_attachment')]
    assert len(attached) == 7
    proofs = [completion.read_sealed_artifact(binding['runtime_observation_attachment'], base) for binding in attached]
    assert {proof['mapping']['category'] for proof in proofs} == CATEGORIES
    assert len({proof['archive']['artifact'] for proof in proofs}) == 1
    assert len({proof['capture']['artifact'] for proof in proofs}) == 1
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    observed = [r for r in result['obligations'] if r['id'] in selected]
    assert {r['id'] for r in observed} == selected
    assert all(r['state'] == 'verified' for r in observed), json.dumps(observed)


FIXED_PROGRAM_CASES = [(version, host, name, mode) for version, host, name in FIXED_LANES
    for mode in fixed_case_modes(version, name)]
FIXED_ORIGINAL_CASES = [
    ('getVoices', 'profiler-voices-observation'), ('getVoices', 'profiler-voice-instance-filter'),
    ('getBusses', 'profiler-busses-observation'), ('getBusses', 'profiler-bus-instance-filter'),
    ('getAudioObjects', 'profiler-audio-objects-observation'), ('getAudioObjects', 'profiler-audio-objects-bus-filter'),
    ('getGameObjects', 'profiler-game-objects-observation'),
]
FIXED_PROGRAM_CASES += [('2025.1', 'wwise-authoring', name, 'original-' + category) for name, category in FIXED_ORIGINAL_CASES]
FIXED_PROGRAM_CASES.append(('2025.1','wwise-console','getVoices','r118-original'))
FIXED_PROGRAM_CASES += [(version,'wwise-console','getVoices','r119-original')
    for version in ('2021.1','2022.1','2023.1','2024.1')]


@pytest.mark.parametrize('version,host,name,mode', FIXED_PROGRAM_CASES,
    ids=['-'.join(case) for case in FIXED_PROGRAM_CASES])
def test_fixed_reader_program_emits_after_actual_teardown(tmp_path, request, version, host, name, mode):
    import os
    from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
    public_root = tmp_path / 'public'
    if mode == 'r119-original':
        _, raw = r119_original_read(version)
        from tests.support.fixed_runtime_read_evidence import R119_PROFILES
        calls = []
        receipt, native, context, trace = public_fixed_read(public_root, version=version, host='wwise-console',
            rows=raw['result']['return'], position=str(R119_PROFILES[version]['time']), public_calls=calls)
    elif mode == 'r118-original':
        _, raw = r118_original_read()
        calls = []
        receipt, native, context, trace = public_fixed_read(public_root, host='wwise-console',
            rows=raw['result']['return'], view='identity', position='6016', public_calls=calls)
    elif mode.startswith('original-'):
        calls = []
        receipt, native, context, trace = public_fixed_read(public_root, version=version, host=host,
            uri='ak.wwise.core.profiler.' + name, filtered='filter' in mode, public_calls=calls)
    else:
        receipt, native, context, trace, calls = fixed_program_case(public_root, version, host, name, mode)
    destination = Path(os.environ.get('WAAPI_FIXED_READER_CAPTURE_DIR', tmp_path)) / f'{version}-{host}-{name}-{mode}.json'
    register_exact_evidence_finalizer(request.node, lambda phases: write_program_receipt(
        destination, receipt, native, nodeid=request.node.nodeid, phase_reports=phases,
        source_context=context, native_reads=trace, public_calls=calls))


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


def r118_original_read():
    descriptor = {'artifact':'r118-originals.json.gz',
        'sha256':'6fb48b4582a02968ca8cce07714c756bbaf5c2d581a26eecf0ff6f296754eaa5'}
    read = archive_reader(descriptor, FIXTURE)
    import gzip
    files = json.loads(gzip.decompress((FIXTURE / descriptor['artifact']).read_bytes()))['files']
    report_path, = [name for name in files if name.endswith('/state/console-profiler-probe.json')]
    report = json.loads(read(report_path))
    receipt, = [r for r in report['calls'] if r['argv'][:2] == ['core-call', URI]]
    raw = json.loads(read(receipt['payload']['call']['evidence_path']))
    return receipt, raw


def test_r118_console_identity_native_fields_reach_same_portable_consumer(tmp_path, inventory):
    from tests.support.fixed_runtime_read_evidence import write_fixed_bundle, mappings
    original, raw = r118_original_read()
    receipt, native, context, trace = public_fixed_read(tmp_path / 'public', host='wwise-console',
        rows=raw['result']['return'], view='identity', position='6016')
    assert native['result'] == raw['result']
    assert receipt['payload']['agent_result']['return'][0]['objectName'] == 'Outside_Idle_1000'
    assert 'pipelineID' not in receipt['payload']['agent_result']['return'][0]
    path = tmp_path / 'capture.json'
    write_program_receipt(path, receipt, native, nodeid='fixed-r118-identity',
        phase_reports=dict.fromkeys(('setup','call','teardown'), 'passed'), source_context=context,
        native_reads=trace, public_calls=[{'gateway':receipt,'native_start':0,'native_end':len(trace)}])
    route = next(r for r in inventory['native_coverage']['routes'] if r['version'] == '2025.1' and r['host'] == 'wwise-console' and r['uri'] == URI)
    selected = {m['branch']['id'] for m in mappings(inventory, json.loads(path.read_bytes()), route)
        if m['categories'] == ['program','native']}
    index = write_fixed_bundle(tmp_path / 'bundle', path, FIXTURE, inventory=inventory, selected=selected)
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, policy)
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    observed = [r for r in result['obligations'] if r['id'] in selected]
    assert {r['id'] for r in observed} == selected
    assert all(r['state'] == 'verified' for r in observed), json.dumps(observed)
    write_json(tmp_path / 'r118-native-selected.json', {'ids':sorted(selected),'count':len(selected)})


def test_r118_current_handle_rejects_resealed_wrong_row_kind_and_observation(tmp_path, inventory):
    from tests.support.fixed_runtime_read_evidence import write_fixed_bundle
    from wwise_waapi.runtime_inspection_observations import pipeline_key
    _, original = r118_original_read()
    rows = deepcopy(original['result']['return'])
    second = deepcopy(rows[0])
    second.update(pipelineID=2, playingID=2, objectName='OtherVoice')
    rows.append(second)  # Schema-valid program shape; not another native fact.
    receipt, native, context, trace = public_fixed_read(tmp_path / 'public', host='wwise-console',
        rows=rows, view='identity', position='6016')
    path = tmp_path / 'capture.json'
    write_program_receipt(path, receipt, native, nodeid='fixed-current-handle-controls',
        phase_reports=dict.fromkeys(('setup','call','teardown'), 'passed'), source_context=context,
        native_reads=trace, public_calls=[{'gateway':receipt,'native_start':0,'native_end':len(trace)}])
    route = next(r for r in inventory['native_coverage']['routes'] if r['version'] == '2025.1' and r['host'] == 'wwise-console' and r['uri'] == URI)
    identity = route['id'] + '|/resultSchema/@definition/waapi_definitions.json/definitions/voiceReturn/properties/pipelineID'
    index = write_fixed_bundle(tmp_path / 'bundle', path, None, inventory=inventory, selected={identity})
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, policy)
    binding = document['bindings'][identity]
    def observed():
        result = completion.evaluate_coverage(audit.ROOT, inventory, document,
            digest=audit.digest, evidence_base=base, requirements_document=policy)
        return next(r for r in result['obligations'] if r['id'] == identity)
    assert observed()['evidence_results']['program']['outcome'] == 'passed'
    baseline = completion.read_sealed_artifact(binding['evidence']['program'], base)
    own_handle = receipt['payload']['agent_result']['return'][0]['voice_instance_handle']
    replacements = {
        'wrong-row': receipt['payload']['agent_result']['return'][1]['voice_instance_handle'],
        'wrong-kind': own_handle.rsplit('-',1)[0] + '-' + pipeline_key('bus',1),
        'unrelated-observation': 'rph1-' + ('f' * 32 if own_handle[5:37] != 'f' * 32 else 'e' * 32) + '-' + pipeline_key('voice',1),
    }
    for mode, handle in replacements.items():
        program = deepcopy(baseline)
        program['gateway']['payload']['agent_result']['return'][0]['voice_instance_handle'] = handle
        program['runtime_read_program']['gateway'] = deepcopy(program['gateway'])
        program['runtime_read_program']['public_calls'][-1]['gateway'] = deepcopy(program['gateway'])
        for check in program['branch_assertions'][identity]['checks']:
            if check['pointer'] == binding['gateway_observation_pointer']: check['equals'] = handle
        binding['evidence']['program'].update(write_json(base / (mode + '.json'),program))
        damaged = observed()
        assert damaged['evidence_results']['program']['outcome'] == 'missing', json.dumps(damaged)
        assert 'same-row current issued voice handle' in damaged['evidence_results']['program']['reason']


def test_r118_native_and_program_selectors_join_without_r103_rebinding(tmp_path, inventory):
    from tests.support.fixed_runtime_read_evidence import write_fixed_stage
    _, original = r118_original_read()
    receipt, native, context, trace = public_fixed_read(tmp_path / 'public', host='wwise-console',
        rows=original['result']['return'], view='identity', position='6016')
    path = tmp_path / 'capture.json'
    write_program_receipt(path, receipt, native, nodeid='r118-stage',
        phase_reports=dict.fromkeys(('setup','call','teardown'), 'passed'), source_context=context,
        native_reads=trace, public_calls=[{'gateway':receipt,'native_start':0,'native_end':len(trace)}])
    route = next(r for r in inventory['native_coverage']['routes'] if r['version'] == '2025.1' and r['host'] == 'wwise-console' and r['uri'] == URI)
    selected = {route['id'] + '|/argsSchema', route['id'] + '|/resultSchema/@definition/waapi_definitions.json/definitions/voiceReturn/properties/pipelineID'}
    index = write_fixed_stage(tmp_path / 'bundle', [path], inventory=inventory, selected_ids=selected,
        r118_capture=path, r118_originals=FIXTURE)
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, policy)
    attached = [binding for binding in document['bindings'].values() if binding.get('runtime_observation_attachment')]
    assert len(attached) == 1
    proof = completion.read_sealed_artifact(attached[0]['runtime_observation_attachment'], base)
    assert proof['archive']['artifact'] == 'r118-originals.json.gz'
    assert not (base / 'r103-originals.json.gz').exists()
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    observed = [r for r in result['obligations'] if r['id'] in selected]
    assert {r['id'] for r in observed} == selected
    assert {r['state'] for r in observed} == {'verified'}, json.dumps(observed)


def r119_original_read(version):
    import gzip
    year = version.split('.')[0]
    name = f'r119-{year}-originals.json.gz'
    read = archive_reader({'artifact': name, 'sha256': sha((FIXTURE / name).read_bytes())}, FIXTURE)
    files = json.loads(gzip.decompress((FIXTURE / name).read_bytes()))['files']
    report_path, = [name for name in files if name.endswith('/state/console-profiler-probe.json')]
    report = json.loads(read(report_path))
    receipt, = [r for r in report['calls'] if r['argv'][:2] == ['core-call', URI]]
    raw = json.loads(read(receipt['payload']['call']['evidence_path']))
    return receipt, raw


@pytest.mark.parametrize('version,position', (('2021.1',5077), ('2022.1',5280), ('2023.1',6005), ('2024.1',5781)))
def test_r119_console_diagnostics_originals_reach_portable_final_consumer(tmp_path, inventory, version, position):
    from tests.support.fixed_runtime_read_evidence import write_fixed_stage, mappings
    original, raw = r119_original_read(version)
    assert len(raw['result']['return']) == 1 and len(raw['result']['return'][0]) == 20
    receipt, native, context, trace = public_fixed_read(tmp_path / 'public', version=version,
        host='wwise-console', rows=raw['result']['return'], position=str(position))
    assert audit.digest(native['result']) == audit.digest(raw['result'])
    assert receipt['payload']['agent_result']['return'][0]['pipelineID'] == 1
    path = tmp_path / 'capture.json'
    write_program_receipt(path, receipt, native, nodeid='fixed-r119-' + version,
        phase_reports=dict.fromkeys(('setup','call','teardown'), 'passed'), source_context=context,
        native_reads=trace, public_calls=[{'gateway':receipt,'native_start':0,'native_end':len(trace)}])
    route = next(r for r in inventory['native_coverage']['routes']
        if r['version'] == version and r['host'] == 'wwise-console' and r['uri'] == URI)
    selected = {m['branch']['id'] for m in mappings(inventory, json.loads(path.read_bytes()), route)
        if m['categories'] == ['program','native']}
    selected.add(route['id'] + '|/argsSchema')
    index = write_fixed_stage(tmp_path / 'bundle', [path], inventory=inventory, selected_ids=selected,
        r119_captures={version:path}, r119_originals=FIXTURE)
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, policy)
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    observed = [r for r in result['obligations'] if r['id'] in selected]
    write_json(tmp_path / 'r119-native-selected.json', {'ids':sorted(selected),'count':len(selected),
        'observed':observed})
    assert {r['id'] for r in observed} == selected
    assert {r['state'] for r in observed} == {'verified'}, json.dumps(observed)
    if version == '2021.1':
        # A valid foreign original shares candidate301a and all packaged hashes;
        # refreshing descriptor seals must not allow its version to replace2021.
        identity = next(i for i in selected if i.endswith('/properties/objectGUID'))
        binding = document['bindings'][identity]
        proof = completion.read_sealed_artifact(binding['runtime_observation_attachment'], base)
        foreign_path = base / 'foreign-category.json'
        foreign_path.write_bytes((FIXTURE / 'r119-2022-category.json').read_bytes())
        foreign = {**proof['native_run'], 'artifact':foreign_path.name, 'sha256':sha(foreign_path.read_bytes())}
        assert completion.read_category_run(foreign,base)['version'] == '2022.1'
        native_record = completion.read_sealed_artifact(binding['evidence']['native'],base)
        native_record['native_runs'] = [foreign]
        proof['native_run'] = foreign
        binding['evidence']['native'].update(write_json(base / 'foreign-native.json',native_record))
        binding['runtime_observation_attachment'] = write_json(base / 'foreign-proof.json',proof)
        damaged = completion.evaluate_coverage(audit.ROOT, inventory, document,
            digest=audit.digest, evidence_base=base, requirements_document=policy)
        row = next(r for r in damaged['obligations'] if r['id'] == identity)
        write_json(tmp_path / 'r119-foreign-profile-result.json',row)
        assert row['evidence_results']['native']['outcome'] == 'missing', json.dumps(row)
        assert 'original strict-PASS observation/request/replay differs' in row['evidence_results']['native']['reason']
