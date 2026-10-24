"""Source-owned fixed Profiler rows using the existing runtime evidence transport."""
from copy import deepcopy
import json
from pathlib import Path, PurePosixPath
import shutil

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support import runtime_observation_evidence as runtime

URIS = frozenset('ak.wwise.core.profiler.' + name for name in ('getVoices', 'getBusses', 'getAudioObjects', 'getGameObjects'))
ORIGINAL_CANDIDATE = '4e5eb44bff9b2d173b97559c9d70ff5f7d78d2f3'
NODEID = 'tests/destructive/test_authoring_ui_business_live.py::test_runtime_owned_2025_profiler_readers'
ARCHIVE_SHA = '91324beb53f122fb2348a07e39e7f803f81130824b47ad9955cb842b3ffdf495'
CATEGORY_SHA = '87a77cd2960e890145ad21ccffaa2aa10f65ac374a37515bdc0e50b0431859d4'
CAPTURE_SHA = '6df34044156629b39a414a41e392c41e7c40b425e8e6f6f548c1605e3028ce5f'
CATEGORIES = frozenset(('profiler-voices-observation', 'profiler-busses-observation', 'profiler-audio-objects-observation',
    'profiler-game-objects-observation', 'profiler-voice-instance-filter', 'profiler-bus-instance-filter', 'profiler-audio-objects-bus-filter'))


def schema_node(branch, root=audit.ROOT):
    return runtime._contribution_node({**branch, 'pointer': branch['pointer'].split('/@boolean/')[0]}, root)


def categories(branch, node):
    if not branch['pointer'].startswith('/resultSchema'):
        return ['program']
    if (branch['kind'] in {'constraint', 'empty_object', 'empty_string'}
            or branch['kind'] == 'optional_presence' and branch['value'] == 'absent'
            or branch['kind'] == 'collection_cardinality' and branch['value'] in {'empty', 'single'}
            or branch['kind'] == 'schema' and (node is False or isinstance(node, dict) and node.get('type') in {'object', 'array'})):
        return ['program']
    return ['program', 'native']


def predicate(branch, node, value, root=audit.ROOT):
    if branch['kind'] == 'boolean_value':
        return type(value) is bool and value is branch['value']
    if branch['kind'] == 'schema' and isinstance(node, dict) and node.get('type') == 'boolean':
        return type(value) is bool
    return runtime._contribution_predicate(branch, node, value, root=root)


def row_data(rows):
    return [{key: value for key, value in row.items() if key not in {'voice_instance_handle', 'bus_instance_handle'}} for row in rows]


def public_pointer(branch, pointer):
    if branch['pointer'] in runtime.CONTRIBUTION_CURSOR_POINTERS and not branch['route'].endswith('|ak.wwise.core.profiler.getGameObjects'):
        return '/gateway/payload/agent_result/profiler_position'
    if pointer.startswith('/native_call/result/return'):
        if branch['route'].endswith('|ak.wwise.core.profiler.getGameObjects'):
            pointer = pointer.replace('/native_call/result/return', '/gateway/payload/agent_result/game_objects', 1)
            for old, new in (('registrationTime', 'register_time'), ('unregistrationTime', 'unregister_time'),
                             ('registerTime', 'register_time'), ('unregisterTime', 'unregister_time')):
                if pointer.endswith('/' + old): pointer = pointer[:-len(old)] + new
            return pointer
        public = pointer.replace('/native_call/result', '/gateway/payload/agent_result', 1)
        return public.rsplit('/', 1)[0] if branch['kind'] == 'optional_presence' and branch['value'] == 'absent' else public
    return '/gateway/payload/agent_result'


def _validate_capture(record, binding, branch, root):
    """The exact mapped route, never optional markers, owns capture eligibility."""
    from wwise_waapi.builders.schema import validate_resolved_semantic_result
    from wwise_waapi.runtime_inspection_business import normalize_runtime_inspection_result, materialize_runtime_inspection_business_request
    version, host, build, kind, uri = branch['route'].split('|')
    captured = record.get('runtime_read_program', {})
    gateway, native = record['gateway'], record['native_call']
    payload = gateway['payload']
    if (uri not in URIS or kind != 'function' or captured.get('contract') != 'waapi-skill.runtime-read-program/v1'
            or captured.get('phase_reports') != dict.fromkeys(('setup', 'call', 'teardown'), 'passed')
            or captured.get('source_unchanged') is not True
            or captured.get('source_context') != runtime.program_source_context(root, flow=uri)
            or record.get('relevant_sources') != captured['source_context']['packaged']
            or audit.digest(captured.get('gateway')) != audit.digest(gateway)
            or audit.digest(captured.get('native_call')) != audit.digest(native)
            or gateway['argv'] != binding['input']['gateway_argv'] or gateway['exit_code'] != 0
            or payload.get('ok') is not True or payload.get('is_command_line') != (host == 'wwise-console')
            or any(payload['schema_validation'][section]['version'] != version for section in ('request', 'result'))
            or native['uri'] != uri):
        raise ValueError('Fixed-row proof needs exact current public capture/phases/host/version')
    trace = captured['native_reads']
    if (not 1 <= len(trace) <= 128 or any(type(row['ordinal']) is not int or row['ordinal'] != index
        or set(row) != {'ordinal', 'uri', 'args', 'options', 'result'} for index, row in enumerate(trace))):
        raise ValueError('Fixed-row ordered native trace differs')
    calls = captured.get('public_calls')
    if not isinstance(calls, list) or not 1 <= len(calls) <= 2:
        raise ValueError('Fixed-row exact public call spans required')
    end = 0
    for call in calls:
        if (set(call) != {'gateway', 'native_start', 'native_end'} or type(call['native_start']) is not int
                or type(call['native_end']) is not int or call['native_start'] != end
                or not end < call['native_end'] <= len(trace) or call['gateway']['exit_code'] != 0
                or call['gateway']['payload'].get('ok') is not True):
            raise ValueError('Fixed-row ordered public/native call spans differ')
        end = call['native_end']
    if end != len(trace) or audit.digest(calls[-1]['gateway']) != audit.digest(gateway):
        raise ValueError('Fixed-row final public/native call span differs')
    final_trace = trace[calls[-1]['native_start']:]
    info, = [row['result'] for row in final_trace if row['uri'] == 'ak.wwise.core.getInfo']
    if completion.native_host_context(info, 'isCommandLine') != {'version': version, 'host': host, 'build': build}:
        raise ValueError('Fixed-row actual public host/build differs')
    final = trace[-1]
    if audit.digest({key: final[key] for key in ('uri', 'args', 'options', 'result')}) != audit.digest(native):
        raise ValueError('Fixed-row final trace/request/result differs')
    if uri.endswith('.getGameObjects'):
        from wwise_waapi.builders.stable_reads import normalize_profiler_game_objects_result, build_profiler_game_objects_request
        argv = gateway['argv']
        if argv[0] != 'profiler-game-objects' or len(calls) != 1 or [r['uri'] for r in final_trace if r['uri'] in URIS] != [uri]:
            raise ValueError('Fixed GameObjects requires its exact dedicated command')
        if '--capture-ms' in argv:
            time = argv[argv.index('--capture-ms') + 1]
        else:
            choice = argv[argv.index('--capture') + 1]
            time = {'latest': 'capture', 'user-cursor': 'user'}[choice]
        request = build_profiler_game_objects_request(version=version, time=time)
        if (audit.digest({'api': uri, 'args': native['args'], 'options': native['options']}) !=
                audit.digest({'api': request.uri, 'args': request.args, 'options': request.options})
                or audit.digest(payload['semantic_preview']) != audit.digest(request.as_dict())):
            raise ValueError('Fixed GameObjects exact controlled request/options differs')
        expected = normalize_profiler_game_objects_result(version=version, result=native['result'])
        if audit.digest(expected) != audit.digest(payload['agent_result']):
            raise ValueError('Program must preserve complete native/public fixed-row projection')
    else:
        argv = gateway['argv']
        if argv[:2] != ['core-call', uri] or '--profiler-position' not in argv:
            raise ValueError('Fixed-row exact public route/position missing')
        position = argv[argv.index('--profiler-position') + 1]
        fields = [argv[index + 1] for index, token in enumerate(argv[:-1]) if token == '--result-field']
        view = argv[argv.index('--result-view') + 1] if '--result-view' in argv else None if fields else 'summary'
        pipeline_bindings = filtered_binding(captured, branch, root)
        request, _, business = materialize_runtime_inspection_business_request(uri, version,
            profiler_position=position, result_view=view, result_fields=fields or None, max_results=64, log_channel=None,
            voice_instance_handle=next((value for value, item in pipeline_bindings.items() if item['kind'] == 'voice'), None),
            bus_instance_handle=next((value for value, item in pipeline_bindings.items() if item['kind'] == 'bus'), None),
            pipeline_bindings=pipeline_bindings)
        if view in {'summary', 'identity', 'diagnostics'}:
            identity_fields = ['busGUID', 'gameObjectID'] if uri.endswith('.getAudioObjects') else ['objectGUID', 'gameObjectID']
            request['options'] = {'return': list(dict.fromkeys([*request['options']['return'], *identity_fields]))}
        if position in {'capture-latest', 'user-cursor'}:
            cursor = cursor_source(captured, uri, position)
            request['args']['time'] = cursor['result']['return']
        if type(native['args'].get('time')) is not int or native['args']['time'] < 0:
            raise ValueError('Fixed-row time requires its exact public construction')
        if payload['business_request'] != {'operation': uri, **business, 'max_results': 64}:
            raise ValueError('Fixed-row reported public construction differs')
        if audit.digest({'api': uri, 'args': native['args'], 'options': native['options']}) != audit.digest(request):
            raise ValueError('Fixed-row exact controlled request/options differs')
        validate_resolved_semantic_result(uri, native['result'], version=version)
        expected = normalize_runtime_inspection_result(uri, native['result'], business_request=business,
            max_results=max(1, len(native['result']['return'])))
        actual = payload['agent_result']
        if (audit.digest(row_data(actual['return'])) != audit.digest(expected['return'])
                or actual.get('complete') is not True or actual['total_count'] != len(native['result']['return'])
                or actual['profiler_position'] != position):
            raise ValueError('Program must preserve complete native/public fixed-row projection')



def filtered_binding(captured, branch, root):
    """A public seed and same-T identity read own the one selected pipeline."""
    from wwise_waapi.runtime_inspection_observations import pipeline_key, validate_pipeline_handle
    uri = captured['native_call']['uri']
    argv = captured['gateway']['argv']
    flags = [flag for flag in ('--voice-instance-handle', '--bus-instance-handle') if flag in argv]
    calls, trace = captured['public_calls'], captured['native_reads']
    final_trace = trace[calls[-1]['native_start']:]
    relevant = [row for row in final_trace if row['uri'] in URIS]
    if not flags:
        if len(calls) != 1 or len(relevant) != 1 or relevant[0]['ordinal'] != len(trace) - 1:
            raise ValueError('Fixed-row unfiltered read has extra dependent calls')
        return {}
    if len(flags) != 1 or len(calls) != 2 or len(relevant) != 2:
        raise ValueError('Fixed-row filtered seed/revalidation trace differs')
    flag, = flags
    kind = 'voice' if flag == '--voice-instance-handle' else 'bus'
    handle = argv[argv.index(flag) + 1]
    validate_pipeline_handle(handle)
    seed_uri = 'ak.wwise.core.profiler.' + ('getVoices' if kind == 'voice' else 'getBusses')
    seed = calls[0]['gateway']
    seed_trace = trace[:calls[0]['native_end']]
    checked, final = relevant
    time = captured['native_call']['args']['time']
    if (seed['argv'][:2] != ['core-call', seed_uri] or checked['uri'] != seed_uri or final['uri'] != uri
            or checked['args'] != {'time': time}
            or checked['options'] != {'return': ['pipelineID', 'gameObjectID', 'objectGUID', 'objectName', 'gameObjectName']}
            or any(token in seed['argv'] for token in ('--voice-instance-handle', '--bus-instance-handle'))
            or type(seed_trace[-1]['args'].get('time')) is not int or seed_trace[-1]['args']['time'] != time):
        raise ValueError('Fixed-row same-time identity revalidation differs')
    seed_native = {key: seed_trace[-1][key] for key in ('uri', 'args', 'options', 'result')}
    seed_capture = {**captured, 'gateway': seed, 'native_call': seed_native, 'native_reads': seed_trace,
        'public_calls': [calls[0]]}
    seed_branch = {**branch, 'route': branch['route'].rsplit('|', 1)[0] + '|' + seed_uri}
    _validate_capture({'gateway': seed, 'native_call': seed_native, 'runtime_read_program': seed_capture,
        'relevant_sources': captured['source_context']['packaged']}, {'input': {'gateway_argv': seed['argv']}}, seed_branch, root)
    for api in ('ak.wwise.core.getInfo', 'ak.wwise.core.object.get'):
        first = [{k:r[k] for k in ('uri','args','options','result')} for r in seed_trace if r['uri'] == api]
        second = [{k:r[k] for k in ('uri','args','options','result')} for r in final_trace if r['uri'] == api]
        if audit.digest(first) != audit.digest(second):
            raise ValueError('Fixed-row seed project/host context differs')
    public, = [row for row in seed['payload']['agent_result']['return'] if row.get(kind + '_instance_handle') == handle]
    native_id = captured['native_call']['args'][kind + 'PipelineID']
    original, = [row for row in seed_native['result']['return'] if row.get('pipelineID') == native_id]
    revalidated, = [row for row in checked['result']['return'] if row.get('pipelineID') == native_id]
    identity = {key: original[key] for key in ('objectGUID', 'gameObjectID')}
    if (type(native_id) is not int or not 0 <= native_id <= 0xffffffff
            or handle.rsplit('-', 1)[1] != pipeline_key(kind, native_id)
            or audit.digest(identity) != audit.digest({key: revalidated.get(key) for key in identity})
            or any(audit.digest(public.get(key)) != audit.digest(value) for key, value in identity.items())):
        raise ValueError('Fixed-row issued handle identity differs from exact revalidation')
    return {handle: {'handle': handle, 'kind': kind, 'native_id': native_id}}

def cursor_source(captured, uri, choice):
    """One source-owned moving cursor snapshot before every dependent read."""
    trace = captured['native_reads'][captured['public_calls'][-1]['native_start']:]
    cursors = [row for row in trace if row['uri'] == 'ak.wwise.core.profiler.getCursorTime']
    source_time = cursors[0]['result'].get('return') if len(cursors) == 1 and type(cursors[0]['result']) is dict else None
    enum = {'capture-latest': 'capture', 'user-cursor': 'user'}[choice]
    dependents = [row for row in trace if row['uri'] in URIS]
    if (len(cursors) != 1 or type(source_time) is not int or source_time < 0
            or cursors[0]['args'] != {'cursor': enum} or cursors[0]['options'] != {}
            or cursors[0]['result'] != {'return': source_time} or not 1 <= len(dependents) <= 2
            or dependents[-1]['uri'] != uri or any(row['ordinal'] <= cursors[0]['ordinal']
                or type(row['args'].get('time')) is not int or row['args']['time'] != source_time for row in dependents)):
        raise ValueError('Fixed-row exact ordered typed cursor snapshot differs')
    return cursors[0]


def validate_program(record, binding, branch, root, reference_edges=None):
    _validate_capture(record, binding, branch, root)
    pointer = binding.get('program_observation_pointer') if binding.get('runtime_observation_attachment') else binding['observation_pointer']
    if binding['gateway_observation_pointer'] != public_pointer(branch, pointer):
        raise ValueError('Fixed-row corresponding exact public occurrence differs')
    node = schema_node(branch, root)
    if branch['pointer'] in runtime.CONTRIBUTION_CURSOR_POINTERS and not branch['route'].endswith('.getGameObjects'):
        edges = reference_edges or {}
        first = branch['route'] + '|/argsSchema/properties/time/$ref'
        second = branch['route'] + '|/argsSchema/@definition/waapi_definitions.json/definitions/cursorTime/oneOf/1/$ref'
        chain = [first] if 'definitions/cursorTime/' in branch['pointer'] else [first, second]
        completion.exact_observation_pointer(branch, {**binding, 'observation_pointer': '/native_call/args/time'},
            '/native_call', 'args', edges)
        if (binding.get('reference_chain') != chain
                or edges[first]['reference']['target'] != branch['route'] + '|/argsSchema/@definition/waapi_definitions.json/definitions/cursorTime'
                or edges[second]['reference']['target'] != branch['route'] + '|/argsSchema/@definition/waapi_definitions.json/definitions/profilerCursor'
                or branch['shape_sha256'] != audit.digest(node)):
            raise ValueError('Fixed-row exact cursor branch/ref/shape differs')
        argv = record['gateway']['argv']
        source = cursor_source(record['runtime_read_program'], record['native_call']['uri'], argv[argv.index('--profiler-position') + 1])
        expected = f"/runtime_read_program/native_reads/{source['ordinal']}/args/cursor"
        if pointer != expected or not predicate(branch, node, source['args']['cursor'], root):
            raise ValueError('Fixed-row exact cursor branch/occurrence differs')
        return {'branch_id': branch['id'], 'observation_pointer': expected}
    if branch['kind'] == 'optional_presence' and branch['value'] == 'absent':
        parent = completion.pointer_value(record, pointer.rsplit('/', 1)[0])
        if type(parent) is not dict or pointer.rsplit('/', 1)[1] in parent:
            raise ValueError('Fixed-row omission requires existing exact parent and missing field')
        value = runtime._CONTRIBUTION_ABSENT
    else:
        value = completion.pointer_value(record, pointer)
    if not predicate(branch, node, value, root):
        raise ValueError('Fixed-row exact pinned branch predicate failed')


def original_observation(originals, category):
    """Use strict original PASS; all archive paths are inert logical identities."""
    originals = Path(originals)
    archive = {'artifact': 'r103-originals.json.gz', 'sha256': runtime.sha((originals / 'r103-originals.json.gz').read_bytes())}
    category_descriptor = {'artifact': 'r103-category.json', 'sha256': runtime.sha((originals / 'r103-category.json').read_bytes()), 'nodeid': NODEID}
    if archive['sha256'] != ARCHIVE_SHA or category_descriptor['sha256'] != CATEGORY_SHA or category not in CATEGORIES:
        raise ValueError('Exact original R103 archive/category scope required')
    read = runtime.archive_reader(archive, originals)
    context = completion.read_category_run(category_descriptor, originals)
    completion.validate_authoring_batch_finalization(context['record'], originals, read_bytes=read)
    run = context['record']
    if (context['candidate'] != ORIGINAL_CANDIDATE or context['host'] != 'wwise-authoring'
            or context['version'] != '2025.1' or context['build'] != '2025.1.7.9143'
            or {row['category'] for row in run['categories']} != CATEGORIES):
        raise ValueError('Original R103 exact seven-category roster/context differs')
    seal = json.loads(read(run['categories'][0]['batch_finalization']['artifact']))
    node = json.loads(read(seal['observations'][NODEID]['path']))
    archived = {PurePosixPath(group['path']).joinpath(item['path']).as_posix(): item for group in node['artifacts'].values() for item in group['files']}
    capture_path, = [name for name in archived if name.endswith('/profiler-capture.json')]
    capture_raw = read(capture_path)
    if runtime.sha(capture_raw) != CAPTURE_SHA: raise ValueError('Original fixed-row capture differs')
    capture = json.loads(capture_raw)
    if capture['outcomes'][category]['outcome'] != 'PASS': raise ValueError('Original fixed-row category did not pass')
    uri = ('ak.wwise.core.profiler.getGameObjects' if category == 'profiler-game-objects-observation' else
        'ak.wwise.core.profiler.getAudioObjects' if 'audio-objects' in category else
        'ak.wwise.core.profiler.getBusses' if 'bus' in category else 'ak.wwise.core.profiler.getVoices')
    filtered = 'filter' in category
    receipt, = [r for r in node['receipts'] if (r['argv'][0] == 'profiler-game-objects' if uri.endswith('.getGameObjects') else r['argv'][:2] == ['core-call', uri])
        and any(flag in r['argv'] for flag in ('--voice-instance-handle', '--bus-instance-handle')) == filtered]
    raw_path, = [name for name in archived if name.endswith('/' + receipt['payload']['call']['evidence_path'].rsplit('/', 1)[1])]
    raw = json.loads(read(raw_path))
    plans = [(name, json.loads(read(name))) for name in archived if '/runtime-inspection-observations-v1/rto1-' in name]
    if uri.endswith('.getGameObjects'):
        request = receipt['payload']['semantic_preview']
        request = {'api': uri, 'args': request['args'], 'options': request['options']}
    else:
        _, plan = next((name, plan) for name, plan in plans if plan['plan']['request']['api'] == uri
            and ('voicePipelineID' in plan['plan']['request']['args']) == ('--voice-instance-handle' in receipt['argv'])
            and ('busPipelineID' in plan['plan']['request']['args']) == ('--bus-instance-handle' in receipt['argv']))
        request = plan['plan']['request']
    if raw['api'] != uri or raw['ok'] is not True or raw['dry_run'] is not False or raw['error_code'] is not None:
        raise ValueError('Original successful fixed-row raw read required')
    return dict(context=context, read=read, node=node, capture=capture, capture_raw=capture_raw,
        capture_path=capture_path, raw=raw, raw_path=raw_path, request=request, receipt=receipt,
        category_descriptor=category_descriptor, archive=archive)


def mappings(inventory, captured, route, selected=None):
    branches = [b for b in inventory['native_coverage']['obligations'] if b['route'] == route['id']]
    edges = {b['id']: b for b in branches if b['kind'] == 'reference'}
    found = []
    for branch in branches:
        if selected is not None and branch['id'] not in selected: continue
        node = schema_node(branch)
        if branch['pointer'] in runtime.CONTRIBUTION_CURSOR_POINTERS and not route['uri'].endswith('.getGameObjects'):
            argv = captured['gateway']['argv']; position = argv[argv.index('--profiler-position') + 1]
            if position in {'capture-latest', 'user-cursor'}:
                source = cursor_source(captured, route['uri'], position)
                if predicate(branch, node, source['args']['cursor']):
                    found.append({'branch': branch, 'program_pointer': f"/runtime_read_program/native_reads/{source['ordinal']}/args/cursor",
                        'reference_chain': runtime._contribution_chains(branch, edges)[0], 'categories': ['program']})
            continue
        for chain in runtime._contribution_chains(branch, edges):
            hit = next(((pointer, value) for pointer, value in runtime._contribution_occurrences(captured,
                runtime._contribution_pattern(branch, chain, edges)) if predicate(branch, node, value)), None)
            if hit:
                found.append({'branch': branch, 'program_pointer': hit[0], 'reference_chain': chain, 'categories': categories(branch, node)})
                break
    if selected is not None and {r['branch']['id'] for r in found} != selected:
        raise ValueError('Every selected fixed-row branch needs an exact independently observed predicate')
    return found


REVIEWED_CHANGES = {'skills/waapi-skill/scripts/gateway.py': {'before': '9ea8d1c0c79c9323c8ee0e48b8cb9444c54c8d73f9f7330ed827563f31f42f03', 'after': '0736194eecf13361bd35b1db8c31d614f6f93c4cf2d14b82e34061490cc05fce'}, 'skills/waapi-skill/wwise_waapi/builders/schema.py': {'before': '4a1ac5146edc65eb8e58defd689051f79a198bafb2d5d2134d912bd9a862fd6d', 'after': 'cd11309c557b68ea7bcb7d82c2bcbc1a448d08f8e283fab50a0424555fc4f8f2'}, 'skills/waapi-skill/wwise_waapi/builders/stable_reads.py': {'before': '74e37957692c6748f6c7f8f6c4dd795dc31c10b78ba0d30500a90d59b818412d', 'after': 'ea1c39a5480afc5720f99a0acb85015c7c7d028d8ee53eb1937ff079fce9d7d8'}, 'skills/waapi-skill/wwise_waapi/operation_registry.py': {'before': '691d93149f80e619539c40db64d1b9d34b86771b0660740eb948356c92a034e1', 'after': 'f96a2233a98e03dd62de261a24b3f81876284af28f0973758cf1f8a805b5dd5a'}, 'skills/waapi-skill/wwise_waapi/runtime_inspection_business.py': {'before': '62e4ed3eca63a62637e7b8e1ab4c5c55c18ceffb49d91d4e318cecec44ce116c', 'after': '06442176e0aa4f5862feb0c66ef9878221494145755d700c02029353641e9f4d'}, 'skills/waapi-skill/wwise_waapi/runtime_inspection_business_contracts.py': {'before': 'd3ebc12976ef6d8976cf8d136ded7dbcd08cc0728ed365b4a0d70e9420fe2c12', 'after': '2a8bb6ef98e2ec59ff802a80309aa4554cf78c37014e28f9c30123df2ed810ca'}, 'skills/waapi-skill/wwise_waapi/transport_action.py': {'before': '3f9828a964b75ce04cc683b8cf0479d4d82b4eddd05c7d26bb4cde6e0b096ec4', 'after': 'f1dfed2fc9e2697d37e022262d440a7d3ace7005d4f5e57b939d7550d7efa2a5'}}
REVIEWED_SYMBOLS = {
    'scripts/gateway.py': ['dispatch_runtime_inspection_business_read', 'dispatch_command:profiler-game-objects', 'fixed_command_route_payload', 'stable-read constant imports', 'build_parser', 'preflight_core_business_input'],
    'wwise_waapi/builders/schema.py': ['validate_resolved_semantic_result', '_validate_resolved_sections', '_runtime_result_reference_schema'],
    'wwise_waapi/builders/stable_reads.py': ['normalize_profiler_game_objects_result'],
    'wwise_waapi/runtime_inspection_business.py': ['RTPC-only guard/disclosure', 'Sequence/field-contract imports', 'materialize_runtime_inspection_business_request', 'normalize_runtime_inspection_result'],
    'wwise_waapi/runtime_inspection_business_contracts.py': ['transport-only earlier delta', 'field ceiling', 'profiler_result_field_choices', 'three row declarations', 'runtime_inspection_business_contract_data'],
    'wwise_waapi/transport_action.py': ['expected_state; unrelated to fixed reads'],
    'wwise_waapi/operation_registry.py': ['verify_prepared_operation transport message; unrelated to fixed reads'],
}


def validate_source_review(descriptor, historical, branch, root, base):
    review = completion.read_sealed_artifact(descriptor, base)
    version, host, build, _, uri = branch['route'].split('|')
    current = runtime.program_source_context(root, flow=uri)['packaged']
    changes = {key: {'before': historical.get(key), 'after': current.get(key)}
        for key in historical.keys() | current.keys() if historical.get(key) != current.get(key)}
    if (version != '2025.1' or host != 'wwise-authoring' or build != '2025.1.7.9143' or uri not in URIS
            or not branch['pointer'].startswith('/resultSchema') or categories(branch, schema_node(branch, root)) != ['program', 'native']
            or set(review) != {'contract', 'historical_candidate', 'historical_sources', 'current_sources', 'changed_files', 'changed_symbols', 'category', 'archive', 'program_replay'}
            or review['contract'] != 'waapi-skill.fixed-row-source-review/v1'
            or review['historical_candidate'] != ORIGINAL_CANDIDATE or len(historical) != 413
            or review['historical_sources'] != historical or review['current_sources'] != current
            or review['changed_files'] != REVIEWED_CHANGES or changes != REVIEWED_CHANGES
            or review['changed_symbols'] != REVIEWED_SYMBOLS):
        raise ValueError('Fixed-row exact reviewed R103 seven-file source/branch closure differs')
    runtime._portable_descriptor(review['program_replay'], base)
    replay = completion.read_sealed_artifact(review['program_replay'], base)
    original = original_observation(base, review['category'])
    if (review['archive'] != original['archive'] or historical != {k:v for k,v in original['node']['source_context']['sources'].items() if k.startswith('skills/waapi-skill/')}
            or audit.digest(replay['native_call']) != audit.digest({'uri': uri, 'args': original['request']['args'],
                'options': original['request']['options'], 'result': original['raw']['result']})):
        raise ValueError('Fixed-row complete original native request/array replay differs')
    provisional = {'gateway': replay['gateway'], 'native_call': replay['native_call'], 'runtime_read_program': replay,
                   'relevant_sources': replay['source_context']['packaged']}
    _validate_capture(provisional, {'input': {'gateway_argv': replay['gateway']['argv']}}, branch, root)


def validate_evidence(record, binding, branch, category, base, root, edges):
    proof = runtime._proof(binding, base); mapping = proof['mapping']; chain = mapping['reference_chain']
    if (category not in {'program', 'native'} or proof['branch_id'] != branch['id'] or proof['native_shape_sha256'] != branch['shape_sha256']
            or mapping['branch_id'] != branch['id'] or mapping['native_shape_sha256'] != branch['shape_sha256']
            or binding['observation_pointer'] != mapping['native_pointer'] or binding['program_observation_pointer'] != mapping['program_pointer']
            or binding['reference_chain'] != chain or not branch['pointer'].startswith('/resultSchema')):
        raise ValueError('Fixed-row exact original branch/reference mapping differs')
    completion.exact_observation_pointer(branch, {'observation_pointer': mapping['program_pointer'], 'reference_chain': chain}, '/native_call', 'result', edges)
    completion.exact_observation_pointer(branch, {'observation_pointer': mapping['native_pointer'], 'reference_chain': chain}, '/observations/raw', 'result', edges)
    captured = completion.read_sealed_artifact(proof['program_capture'], base)
    if category == 'program':
        if audit.digest(record.get('runtime_read_program')) != audit.digest(captured):
            raise ValueError('Fixed-row attached public capture differs')
        validate_program({**record, 'runtime_read_program': captured}, binding, branch, root, edges)
        return
    original = original_observation(base, mapping['category'])
    historical = {k:v for k,v in original['node']['source_context']['sources'].items() if k.startswith('skills/waapi-skill/')}
    if (proof['native_run']['sha256'] != CATEGORY_SHA or proof['native_run']['nodeid'] != NODEID
            or proof['archive'] != original['archive'] or proof['relevant_sources'] != historical
            or proof['capture']['sha256'] != CAPTURE_SHA or proof['capture_original_path'] != original['capture_path']
            or mapping['raw_original_path'] != original['raw_path']
            or original['read'](mapping['raw_original_path']) != (base / mapping['raw_observation']['artifact']).read_bytes()
            or original['capture_raw'] != (base / proof['capture']['artifact']).read_bytes()
            or record['native_runs'] != [proof['native_run']]
            or record['observation_artifacts'] != {'capture': proof['capture'], 'raw': mapping['raw_observation']}
            or audit.digest(captured['native_call']) != audit.digest({'uri': original['raw']['api'], 'args': original['request']['args'],
                'options': original['request']['options'], 'result': original['raw']['result']})):
        raise ValueError('Fixed-row original strict-PASS observation/request/replay differs')
    validate_source_review(proof['source_review'], historical, branch, root, base)
    if record['branch_assertions'][branch['id']]['checks'] != mapping['native_checks']:
        raise ValueError('Fixed-row exact native branch assertion differs')


def write_fixed_bundle(output, program_path, originals, *, inventory, selected=None, name_prefix=''):
    """Publish independent assertions through the existing runtime attachment."""
    captured = json.loads(Path(program_path).read_bytes()); uri = captured['native_call']['uri']
    payload = captured['gateway']['payload']; version = payload['schema_validation']['result']['version']
    host = 'wwise-console' if payload['is_command_line'] else 'wwise-authoring'
    route = next(r for r in inventory['native_coverage']['routes'] if r['uri'] == uri and r['version'] == version and r['host'] == host)
    public = next(r for r in inventory['routes'] if r['id'] == route['public_route'])
    mapped = mappings(inventory, captured, route, selected)
    if name_prefix and (not name_prefix.endswith('-') or '/' in name_prefix or '..' in name_prefix):
        raise ValueError('Fixed flow prefix must be a simple filename prefix')
    output = Path(output);output.mkdir(parents=True, exist_ok=bool(name_prefix))
    def filename(name):
        if name == 'original-capture.json': return 'r103-capture.json'
        return name if name.startswith('r103-') else name_prefix + name
    def write(name, value): return runtime.write_json(output / filename(name), value)
    shutil.copyfile(program_path, output / filename('program-capture.json'))
    def descriptor(name):return {'artifact': filename(name), 'sha256': runtime.sha((output / filename(name)).read_bytes())}
    sources = captured['source_context']['packaged']; candidate = inventory['native_coverage']['candidate_sha256']
    program = {'candidate_sha256': candidate, 'scope_kind': 'product', 'relevant_sources': sources,
        'gateway': captured['gateway'], 'native_call': captured['native_call'], 'runtime_read_program': captured,
        'invocation': {'phase': 'final', 'outcome': 'PASS', 'node_outcomes': [{'nodeid': captured['nodeid'], 'outcome': 'PASS'}]}, 'branch_assertions': {}}
    document = {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': {}}
    policy = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {}}
    native = original = source_review = None
    if originals is not None:
        if any(m['categories'] != ['program', 'native'] for m in mapped):
            raise ValueError('Original native attachment only accepts independently observed data branches')
        if version != '2025.1' or host != 'wwise-authoring':raise ValueError('Fixed-row native originals are only2025Authoring')
        category = ('profiler-voices-observation' if uri.endswith('.getVoices') else 'profiler-busses-observation' if uri.endswith('.getBusses')
            else 'profiler-audio-objects-observation' if uri.endswith('.getAudioObjects') else 'profiler-game-objects-observation')
        if '--voice-instance-handle' in captured['gateway']['argv']: category = 'profiler-voice-instance-filter'
        elif '--bus-instance-handle' in captured['gateway']['argv']:
            category = 'profiler-audio-objects-bus-filter' if uri.endswith('.getAudioObjects') else 'profiler-bus-instance-filter'
        for name in ('r103-category.json', 'r103-originals.json.gz'):
            source = (Path(originals) / name).read_bytes()
            if (output / name).exists():
                if (output / name).read_bytes() != source: raise ValueError('Fixed stage original closure changed')
            else: (output / name).write_bytes(source)
        original = original_observation(output, category)
        (output / filename('original-capture.json')).write_bytes(original['capture_raw'])
        (output / filename('original-raw.json')).write_bytes(original['read'](original['raw_path']))
        historical = {k:v for k,v in original['node']['source_context']['sources'].items() if k.startswith('skills/waapi-skill/')}
        native_run = {**descriptor('r103-category.json'), 'nodeid': NODEID,
            'observation_sha256': [descriptor('original-capture.json')['sha256'], descriptor('original-raw.json')['sha256']]}
        source_review = write('source-review.json', {'contract': 'waapi-skill.fixed-row-source-review/v1',
            'historical_candidate': ORIGINAL_CANDIDATE, 'historical_sources': historical, 'current_sources': sources,
            'changed_files': REVIEWED_CHANGES, 'changed_symbols': REVIEWED_SYMBOLS, 'category': category,
            'archive': descriptor('r103-originals.json.gz'), 'program_replay': descriptor('program-capture.json')})
        native = {'candidate_sha256': candidate, 'scope_kind': 'product', 'evidence_kind': 'native_execution',
            'relevant_sources': historical, 'invocation': original['context']['record']['invocation'], 'native_runs': [native_run],
            'observation_artifacts': {'capture': descriptor('original-capture.json'), 'raw': descriptor('original-raw.json')}, 'branch_assertions': {}}
    for mapping in mapped:
        branch, pointer = mapping['branch'], mapping['program_pointer']; identity=branch['id']; public_path=public_pointer(branch,pointer)
        check = ({'pointer': pointer, 'absent': True} if branch['kind'] == 'optional_presence' and branch['value'] == 'absent' else
            {'pointer': pointer, 'cardinality': branch['value']} if branch['kind'] == 'collection_cardinality' else
            {'pointer': pointer, 'equals': completion.pointer_value(program, pointer)})
        assertion={'native_shape_sha256':branch['shape_sha256'],'native_route':branch['route']}
        program['branch_assertions'][identity]={**assertion,'checks':[check,{'pointer':public_path,'equals':completion.pointer_value(captured,public_path)}]}
        binding={'branch_id':identity,'native_shape_sha256':branch['shape_sha256'],'public_route':public['id'],'public_route_sha256':audit.digest(public),
            'input':{'gateway_argv':captured['gateway']['argv'],'selector':pointer},'dispatch_pointer':'/native_call','observation_pointer':pointer,
            'gateway_observation_pointer':public_path,'reference_chain':mapping['reference_chain'],'relevant_sources':sorted(sources),'evidence':{},
            **{key:{'source':source,'selector':branch['pointer']} for key,source in (
                ('construction','skills/waapi-skill/wwise_waapi/runtime_inspection_business.py#materialize_runtime_inspection_business_request'),
                ('validation','skills/waapi-skill/wwise_waapi/builders/schema.py#validate_resolved_semantic_result'),
                ('verifier','skills/waapi-skill/wwise_waapi/runtime_inspection_business.py#normalize_runtime_inspection_result'))}}
        document['bindings'][identity]=binding
        policy['branches'][identity]={'native_shape_sha256':branch['shape_sha256'],'categories':mapping['categories'],
            'reason':'Exact reported fixed-reader data/reference/present/boolean/multiple occurrence; independent native fact required' if mapping['categories']==['program','native'] else
            'SPEC section5 exact deterministic fixed-reader construction/predicate/shape preservation; no actual native occurrence/data/effect claim'}
        if native is not None:
            native_pointer=pointer.replace('/native_call','/observations/raw',1)
            native_value=completion.pointer_value({'observations':{'raw':original['raw']}},native_pointer)
            native_check={'pointer':native_pointer,'cardinality':branch['value']} if branch['kind']=='collection_cardinality' else {'pointer':native_pointer,'equals':native_value}
            native['branch_assertions'][identity]={**assertion,'checks':[native_check]}
            mapping.update(branch_id=identity,native_shape_sha256=branch['shape_sha256'],native_pointer=native_pointer,
                native_result_parent='/observations/raw',native_checks=[native_check],category=category,
                raw_observation=descriptor('original-raw.json'),raw_original_path=original['raw_path'])
    pd={**write('program.json',program),'nodeid':captured['nodeid']}
    for binding in document['bindings'].values():binding['evidence']['program']=deepcopy(pd)
    bd=write('bindings.json',document);rd=write('requirements.json',policy);attachments=[]
    if native is not None:
        nd={**write('native.json',native),'nodeid':NODEID}
        for number,mapping in enumerate(mapped):
            branch=mapping['branch'];identity=branch['id'];binding=deepcopy(document['bindings'][identity])
            proof={'contract':'waapi-skill.runtime-observation-proof/v1','branch_id':identity,'native_shape_sha256':branch['shape_sha256'],
                'mapping':{k:v for k,v in mapping.items() if k!='branch'},'native_run':native_run,'archive':descriptor('r103-originals.json.gz'),
                'capture':descriptor('original-capture.json'),'capture_original_path':original['capture_path'],'program_capture':descriptor('program-capture.json'),
                'relevant_sources':historical,'source_review':source_review}
            proof_descriptor=write(f'proof-{number}.json',proof)
            binding.update(runtime_observation_attachment=proof_descriptor,program_observation_pointer=mapping['program_pointer'],
                observation_pointer=mapping['native_pointer'],native_observations_sha256={'capture':descriptor('original-capture.json')['sha256'],'raw':descriptor('original-raw.json')['sha256']})
            equivalence={'contract':'waapi-skill.branch-evidence-equivalence/v1','from_candidate':ORIGINAL_CANDIDATE,'to_candidate':candidate,
                'branch_id':identity,'native_shape_sha256':branch['shape_sha256'],'native_route':branch['route'],'evidence_sha256':native_run['sha256'],
                'binding_semantics_sha256':audit.digest(completion.binding_semantics(binding)),
                'reviewed_reason':'Exact reviewed R103 seven-file read scope; complete original typed array/request/public projection current replay; no mutation or lifecycle effect credit',
                'sources':historical,'runtime_read_review':source_review}
            ed=write(f'equivalence-{number}.json',equivalence)
            attachments.append(write(f'attachment-{number}.json',{'contract':'waapi-skill.runtime-observation-attachment/v1','branch_id':identity,
                'proof':proof_descriptor,'evidence':nd,'native_equivalence':ed}))
    write('index.json',{'contract':'waapi-skill.branch-evidence-index/v1','base':'.',
        'entries':[{'id':name_prefix+'fixed-'+version+'-'+host,'bindings':bd,'origin':{'bindings':bd,'program':descriptor('program.json'),'requirements':rd,'capture':descriptor('program-capture.json')}}],
        **({'runtime_observation_attachments':attachments} if attachments else {})})
    return output/filename('index.json')


def write_fixed_stage(output, captures, *, inventory, route_ids=None, selected_ids=None, original_captures=None, originals=None):
    """Select each exact branch once from independent shared public flows."""
    routes = [r for r in inventory['native_coverage']['routes'] if r['uri'] in URIS
        and (route_ids is None or r['id'] in route_ids)]
    if route_ids is not None and {r['id'] for r in routes} != set(route_ids):
        raise ValueError('Fixed stage only accepts existing exact fixed-reader routes')
    wanted = {b['id'] for b in inventory['native_coverage']['obligations'] if b['route'] in {r['id'] for r in routes}}
    if selected_ids is not None:
        if not set(selected_ids) <= wanted: raise ValueError('Fixed stage selected identities escape exact mapped routes')
        wanted = set(selected_ids)
    selected = set()
    index = {'contract': 'waapi-skill.branch-evidence-index/v1', 'base': '.', 'entries': []}
    policy = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {}}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    def append_flow(flow, fresh):
        document = json.loads(flow.read_bytes())
        index['entries'].extend(document['entries'])
        if document.get('runtime_observation_attachments'):
            index.setdefault('runtime_observation_attachments', []).extend(document['runtime_observation_attachments'])
        flow_policy = completion.read_sealed_artifact(document['entries'][0]['origin']['requirements'], output)
        if policy['branches'].keys() & flow_policy['branches'].keys():
            raise ValueError('Fixed stage duplicates an exact branch')
        policy['branches'].update(flow_policy['branches'])
        selected.update(fresh)
    def captured_route(captured):
        payload = captured['gateway']['payload']
        version = payload['schema_validation']['result']['version']
        host = 'wwise-console' if payload['is_command_line'] else 'wwise-authoring'
        route, = [r for r in routes if r['uri'] == captured['native_call']['uri'] and r['version'] == version and r['host'] == host]
        return route
    if originals is not None or original_captures:
        if originals is None or set(original_captures or {}) != CATEGORIES:
            raise ValueError('Fixed native stage requires all exact seven original public replays')
        # Filtered receipts own one matching result branch each; unfiltered
        # receipts own the remaining independent data witnesses. No ID repeats.
        for category in sorted(CATEGORIES, key=lambda name: ('filter' not in name, name)):
            path = original_captures[category]
            captured = json.loads(Path(path).read_bytes())
            route = captured_route(captured)
            mapped = mappings(inventory, captured, route)
            fresh = {m['branch']['id'] for m in mapped if m['categories'] == ['program', 'native']} & wanted - selected
            if 'filter' in category:
                fresh = set(sorted(fresh)[:1])
            if not fresh:
                raise ValueError('Each original fixed receipt needs an independently matching unique data branch')
            flow = write_fixed_bundle(output, path, originals, inventory=inventory, selected=fresh,
                name_prefix='original-' + category + '-')
            proof = completion.read_sealed_artifact(json.loads(flow.read_bytes())['runtime_observation_attachments'][0], output)
            observed = completion.read_sealed_artifact(proof['proof'], output)
            if observed['mapping']['category'] != category:
                raise ValueError('Fixed original category does not match actual public filter')
            append_flow(flow, fresh)
    for number, path in enumerate(captures):
        captured = json.loads(Path(path).read_bytes())
        route = captured_route(captured)
        mapped = mappings(inventory, captured, route)
        fresh = ({m['branch']['id'] for m in mapped} & wanted) - selected
        if not fresh:
            continue
        flow = write_fixed_bundle(output, path, None, inventory=inventory, selected=fresh, name_prefix=f'flow-{number}-')
        append_flow(flow, fresh)
    if selected != wanted:
        raise ValueError('Fixed stage unproved exact branches: ' + repr(sorted(wanted - selected)))
    runtime.write_json(output / 'index.json', index)
    runtime.write_json(output / 'requirements.json', policy)
    return output / 'index.json'
