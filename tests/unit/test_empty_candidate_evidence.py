"""Impossible generated alternatives require a real public rejection receipt."""
from copy import deepcopy
import gzip
import json

import pytest
from pathlib import Path

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance.branch_audit_completion import evidence_result
from tests.unit.test_runtime_business_gateway import _env, gateway

ROOT = Path(__file__).resolve().parents[2]
ROUTE = '2025.1|wwise-console|2025.1.7.9143|function|ak.wwise.core.log.get'


def _native_rows(route=ROUTE):
    packed = json.loads(gzip.decompress((ROOT / 'docs/branch-coverage-inventory.native-obligations.json.gz').read_bytes()))
    result = []
    for row in packed['rows']:
        if row.get('route') is None or packed['routes'][row['route']] != route:
            continue
        row = deepcopy(row)
        row.update(packed['contexts'][row.pop('context')])
        row['route'] = route
        row['id'] = route + '|' + row['pointer']
        row['shape_sha256'] = packed['shapes'][row.pop('shape')]
        result.append(row)
    return result


def _log_receipt(tmp_path, severity):
    class Client:
        def __init__(self): self.calls = []
        def disconnect(self): pass
        def call(self, uri, args=None, options=None):
            if uri == 'ak.wwise.core.getInfo':
                result = {'displayName': 'Wwise', 'isCommandLine': True,
                          'version': {'year': 2025, 'major': 1, 'minor': 7, 'build': 9143,
                                      'displayName': 'v2025.1.7.9143'}}
            elif uri == 'ak.wwise.core.getProjectInfo':
                result = {'id': '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}', 'name': 'SampleProject', 'path': str(tmp_path / 'Sample.wproj')}
            else:
                assert uri == 'ak.wwise.core.log.get'
                result = {'items': [{'message': 'owned marker', 'severity': severity, 'time': 1, 'messageId': 'Custom'}]}
            self.calls.append({'uri': uri, 'args': deepcopy(args or {}), 'options': deepcopy(options or {}), 'result': deepcopy(result)})
            return result
    client = Client()
    argv = ['--state-dir', str(tmp_path / 'state'), 'core-call', 'ak.wwise.core.log.get', '--log-channel', 'general']
    code, payload = gateway.execute_gateway(argv, env=_env(tmp_path), client_factory=lambda _: client)
    return {'gateway': {'argv': argv, 'exit_code': code, 'payload': payload}, 'native_calls': client.calls}


def _seal(path, record):
    path.write_text(json.dumps(record, sort_keys=True, ensure_ascii=False) + '\n')
    import hashlib
    return {'artifact': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'nodeid': 'test_empty_log_severity_requires_exact_public_result_rejection'}


def test_empty_log_severity_requires_exact_public_result_rejection(tmp_path, request):
    from tests.support.empty_candidate_evidence import counterexample_source_context
    initial_context = counterexample_source_context(ROOT)
    rows = _native_rows()
    branch = next(row for row in rows if row['pointer'].endswith('/logCentralSeverity/@empty/string'))
    edges = {row['id']: row for row in rows if row['kind'] == 'reference'}
    valid = _log_receipt(tmp_path, 'Message')
    invalid = _log_receipt(tmp_path, '')
    assert valid['gateway']['exit_code'] == 0, valid
    assert invalid['gateway']['exit_code'] == 2 and 'agent_result' not in invalid['gateway']['payload'], invalid
    from tests.support.empty_candidate_evidence import classify_empty_candidate, counterexample_source_context
    classification = classify_empty_candidate(ROOT, branch)
    assert classification['status'] == 'rejected', classification
    call_index = next(i for i, c in enumerate(invalid['native_calls']) if c['uri'] == 'ak.wwise.core.log.get')
    observation = f'/native_calls/{call_index}/result/items/0/severity'
    binding = {'disposition': 'schema_counterexample', 'empty_candidate': classification,
               'input': {'gateway_argv': invalid['gateway']['argv']},
               'dispatch_pointer': f'/native_calls/{call_index}', 'observation_pointer': observation,
               'reference_chain': [ROUTE + '|/resultSchema/properties/items/items/$ref',
                    ROUTE + '|/resultSchema/@definition/waapi_definitions.json/definitions/logCentralItem/properties/severity/$ref']}
    record = dict(invalid, candidate_sha256='controlled-current', scope_kind='controlled',
                  source_context=initial_context, phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'),
                  invocation={'phase': 'final', 'outcome': 'PASS', 'node_outcomes': [
                    {'nodeid': 'test_empty_log_severity_requires_exact_public_result_rejection', 'outcome': 'PASS'}]},
                  counterexample={'classification': classification, 'valid': valid},
                  branch_assertions={branch['id']: {'native_shape_sha256': branch['shape_sha256'], 'native_route': ROUTE,
                    'checks': [{'pointer': observation, 'equals': ''}]}})
    descriptor = _seal(tmp_path / 'counterexample.json', record)
    outcome = evidence_result(descriptor, branch, 'controlled-current', 'program', 'controlled', tmp_path,
                              binding, ROOT, edges)
    assert outcome == ('passed', None), (outcome, invalid['gateway']['payload'])
    # Damage the same produced packet; no repeated public producer is needed.
    for damage in ('schema', 'candidate', 'success', 'error-field', 'no-dispatch', 'valid-counterpart', 'wrong-field', 'nonfinal', 'source-drift', 'late-failure'):
        damaged, damaged_binding = deepcopy(record), deepcopy(binding)
        if damage == 'schema':
            damaged['counterexample']['classification']['parent_schema_sha256'] = '0' * 64
            damaged_binding['empty_candidate'] = deepcopy(damaged['counterexample']['classification'])
        elif damage == 'candidate':
            damaged['native_calls'][call_index]['result']['items'][0]['severity'] = 'Warning'
        elif damage == 'success':
            damaged['gateway']['exit_code'] = 0
            damaged['gateway']['payload']['ok'] = True
        elif damage == 'error-field':
            damaged['gateway']['payload'] = {'ok': False, 'error_code': 'SemanticValidationError',
                                            'details': {'section': 'result.items[0].message'}}
        elif damage == 'no-dispatch':
            damaged['native_calls'][call_index]['uri'] = 'ak.wwise.core.getInfo'
        elif damage == 'valid-counterpart':
            damaged['counterexample']['valid']['native_calls'][call_index]['result']['items'][0]['severity'] = ''
        elif damage == 'wrong-field':
            damaged_binding['observation_pointer'] = observation.rsplit('/', 1)[0] + '/message'
        elif damage == 'source-drift':
            damaged['source_context'] = {}
        elif damage == 'late-failure':
            damaged['phase_reports']['teardown'] = 'failed'
        else:
            damaged['invocation']['phase'] = 'call'
        damaged_descriptor = _seal(tmp_path / ('damage-' + damage + '.json'), damaged)
        rejected = evidence_result(damaged_descriptor, branch, 'controlled-current', 'program', 'controlled', tmp_path,
                                   damaged_binding, ROOT, edges)
        assert rejected[0] == 'missing', (damage, rejected)
    native = evidence_result(descriptor, branch, 'controlled-current', 'native', 'controlled', tmp_path, binding, ROOT, edges)
    assert native[0] == 'missing'

    from tests.support.empty_candidate_evidence import write_counterexample_bundle, counterexample_source_context
    from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
    source_context = initial_context
    public_id = '2025.1|function|ak.wwise.core.log.get'
    public = next(row for row in json.loads((ROOT / 'docs/branch-coverage-inventory.json').read_text())['routes'] if row['id'] == public_id)
    binding.update(branch_id=branch['id'], native_shape_sha256=branch['shape_sha256'], public_route=public_id,
                   public_route_sha256=audit.digest(public),
                   **{key: {'source': 'skills/waapi-skill/wwise_waapi/runtime_inspection_business.py#normalize_runtime_inspection_result',
                            'selector': branch['pointer']} for key in ('construction', 'validation', 'verifier')})
    inventory = {'native_coverage': {'candidate_sha256': 'controlled-current', 'obligations': rows}}
    index = write_counterexample_bundle(tmp_path / 'portable', record, branch=branch, binding=binding, inventory=inventory,
        root=ROOT, nodeid=request.node.nodeid, phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'),
        source_context=source_context)
    for phases, sources in ((dict.fromkeys(('setup', 'call', 'teardown'), 'failed'), source_context),
                             (dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), {})):
        with pytest.raises(ValueError, match='successful phases and unchanged'):
            write_counterexample_bundle(tmp_path / 'bad-publication', record, branch=branch, binding=binding,
                inventory=inventory, root=ROOT, nodeid=request.node.nodeid, phase_reports=phases, source_context=sources)
        assert not (tmp_path / 'bad-publication').exists()
    with pytest.raises(ValueError, match='collision'):
        write_counterexample_bundle(index.parent, record, branch=branch, binding=binding, inventory=inventory,
            root=ROOT, nodeid=request.node.nodeid, phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=source_context)
    policy = json.loads(index.with_name(index.name.replace('index', 'requirements')).read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, policy)
    published_binding = document['bindings'][branch['id']]
    passed = evidence_result(published_binding['evidence']['program'], branch, 'controlled-current', 'program', 'controlled', base,
                             published_binding, ROOT, edges)
    assert passed == ('passed', None), passed
    # Product emission runs only from the existing actual teardown callback.
    import os
    destination = Path(os.environ.get('WAAPI_EMPTY_COUNTEREXAMPLE_CAPTURE', tmp_path / 'after-teardown'))
    register_exact_evidence_finalizer(request.node, lambda phases: write_counterexample_bundle(destination, record,
        branch=branch, binding=binding, inventory=inventory, root=ROOT, nodeid=request.node.nodeid,
        phase_reports=phases, source_context=source_context))



def test_empty_public_severity_is_rejected_before_dispatch_with_valid_preview_counterpart(tmp_path, request):
    import contextlib
    import io
    from tests.unit.test_console_log_observer_gateway import ConsoleLogClient
    from tests.support.empty_candidate_evidence import classify_empty_candidate, counterexample_source_context
    route = ROUTE.replace('log.get', 'log.addItem')
    initial_context = counterexample_source_context(ROOT)
    rows = _native_rows(route)
    branch = next(row for row in rows if row['pointer'].endswith('/logCentralSeverity/@empty/string'))
    classification = classify_empty_candidate(ROOT, branch)
    edges = {row['id']: row for row in rows if row['kind'] == 'reference'}
    client = ConsoleLogClient(tmp_path)
    recorded = []
    original_call = client.call
    def call(uri, args=None, options=None):
        result = original_call(uri, args, options)
        recorded.append({'uri': uri, 'args': deepcopy(args or {}), 'options': deepcopy(options or {}), 'result': deepcopy(result)})
        return result
    client.call = call
    def invoke(argv):
        recorded.clear()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code, payload = gateway.execute_gateway(argv, env=_env(tmp_path), client_factory=lambda _: client)
            except SystemExit as exc:
                code, payload = exc.code, None
        return {'gateway': {'argv': argv, 'exit_code': code, 'payload': payload,
                            'stdout': out.getvalue(), 'stderr': err.getvalue()}, 'native_calls': deepcopy(recorded)}
    prefix = ['--state-dir', str(tmp_path / 'state')]
    started = invoke([*prefix, 'draft-start', 'ak.wwise.core.log.addItem'])['gateway']['payload']
    declaration = [*prefix, 'draft-declare-runtime-control-plan', started['draft']['draft_id'],
                   '--task-authority', started['task_authority'], '--expected-revision', str(started['draft']['revision']),
                   '--message', 'owned marker', '--severity', '']
    invalid = invoke(declaration)
    assert invalid['gateway']['exit_code'] == 2 and invalid['gateway']['payload'] is None
    assert invalid['native_calls'] == []
    valid = invoke([*declaration[:-1], 'message'])
    assert valid['gateway']['exit_code'] == 0, valid
    current = valid['gateway']['payload']
    checked = invoke([*prefix, 'draft-check', current['draft']['draft_id'], '--task-authority', started['task_authority'],
                      '--expected-revision', str(current['draft']['revision'])])['gateway']['payload']
    compiled = invoke([*prefix, 'preview-from-draft', checked['draft']['draft_id'], '--task-authority', started['task_authority'],
                       '--expected-revision', str(checked['draft']['revision'])])
    assert compiled['gateway']['exit_code'] == 0, compiled
    assert compiled['gateway']['payload']['agent_result']['request']['arguments']['args']['severity'] == 'Message'
    dispatch = '/counterexample/compiled/gateway/payload/agent_result/request/arguments'
    observation = dispatch + '/args/severity'
    binding = {'disposition': 'schema_counterexample', 'empty_candidate': classification,
               'input': {'gateway_argv': declaration}, 'dispatch_pointer': dispatch, 'observation_pointer': observation,
               'reference_chain': [route + '|/argsSchema/properties/severity/$ref']}
    record = dict(invalid, candidate_sha256='controlled-current', scope_kind='controlled',
                  source_context=initial_context, phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'),
        invocation={'phase': 'final', 'outcome': 'PASS', 'node_outcomes': [
            {'nodeid': 'test_empty_log_severity_requires_exact_public_result_rejection', 'outcome': 'PASS'}]},
        counterexample={'classification': classification, 'valid': valid, 'compiled': compiled,
                        'public_input_pointer': '/gateway/argv/' + str(len(declaration) - 1)},
        branch_assertions={branch['id']: {'native_shape_sha256': branch['shape_sha256'], 'native_route': route,
            'checks': [{'pointer': '/gateway/argv/' + str(len(declaration) - 1), 'equals': ''}]}})
    descriptor = _seal(tmp_path / 'argument-counterexample.json', record)
    result = evidence_result(descriptor, branch, 'controlled-current', 'program', 'controlled', tmp_path, binding, ROOT, edges)
    assert result == ('passed', None), result
    for damage in ('wrong-flag', 'wrong-operation', 'wrong-declaration', 'target-dispatch', 'invalid-preview', 'wrong-host', 'successful-parser'):
        changed = deepcopy(record)
        if damage == 'wrong-flag':
            changed['gateway']['stderr'] = changed['gateway']['stderr'].replace('argument --severity:', 'argument --log-channel:')
        elif damage == 'wrong-operation':
            changed['counterexample']['compiled']['gateway']['payload']['agent_result']['request']['arguments']['api'] = 'ak.wwise.core.log.clear'
        elif damage == 'wrong-declaration':
            changed['counterexample']['valid']['gateway']['payload']['draft']['binding']['operation'] = 'ak.wwise.core.log.clear'
        elif damage == 'target-dispatch':
            changed['native_calls'] = [{'uri': 'ak.wwise.core.log.addItem', 'args': {'severity': ''}, 'options': {}, 'result': {}}]
        elif damage == 'invalid-preview':
            changed['counterexample']['compiled']['gateway']['payload']['agent_result']['request']['arguments']['args']['severity'] = ''
        elif damage == 'wrong-host':
            next(call for call in changed['counterexample']['valid']['native_calls'] if call['uri'] == 'ak.wwise.core.getInfo')['result']['isCommandLine'] = False
        else:
            changed['gateway']['exit_code'] = 0
        changed_descriptor = _seal(tmp_path / ('args-' + damage + '.json'), changed)
        assert evidence_result(changed_descriptor, branch, 'controlled-current', 'program', 'controlled', tmp_path,
                               binding, ROOT, edges)[0] == 'missing', damage
    from tests.support.empty_candidate_evidence import write_counterexample_bundle
    from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
    import os
    destination = Path(os.environ.get('WAAPI_EMPTY_COUNTEREXAMPLE_ARGUMENT_CAPTURE', tmp_path / 'after-teardown'))
    public_id = '2025.1|function|ak.wwise.core.log.addItem'
    public = next(row for row in json.loads((ROOT / 'docs/branch-coverage-inventory.json').read_text())['routes'] if row['id'] == public_id)
    binding.update(branch_id=branch['id'], native_shape_sha256=branch['shape_sha256'], public_route=public_id,
                   public_route_sha256=audit.digest(public),
                   **{key: {'source': 'skills/waapi-skill/wwise_waapi/runtime_inspection_business.py#materialize_runtime_control_business_request',
                            'selector': branch['pointer']} for key in ('construction', 'validation', 'verifier')})
    inventory = {'native_coverage': {'candidate_sha256': 'controlled-current', 'obligations': rows}}
    register_exact_evidence_finalizer(request.node, lambda phases: write_counterexample_bundle(destination, record,
        branch=branch, binding=binding, inventory=inventory, root=ROOT, nodeid=request.node.nodeid,
        phase_reports=phases, source_context=initial_context))


def test_empty_classification_preserves_native_valid_message_and_exact_local_definition_aliases():
    from tests.support.empty_candidate_evidence import classify_empty_candidate
    cache = {}
    rows = _native_rows(ROUTE.replace('log.get', 'log.addItem'))
    message = next(row for row in rows if row['pointer'] == '/argsSchema/properties/message/@empty/string')
    assert classify_empty_candidate(ROOT, message, cache=cache)['status'] == 'accepted'
    severity = next(row for row in rows if row['pointer'].endswith('/logCentralSeverity/@empty/string'))
    assert classify_empty_candidate(ROOT, severity, cache=cache)['status'] == 'rejected'
    changed = dict(severity, shape_sha256='0' * 64)
    assert classify_empty_candidate(ROOT, changed, cache=cache)['status'] == 'unknown'
    unknown_route = '2021.1|wwise-console|2021.1.14.8108|function|ak.wwise.core.log.get'
    unknown = next(row for row in _native_rows(unknown_route) if row['pointer'] == '/resultSchema/properties/items/@cardinality/empty')
    assert classify_empty_candidate(ROOT, unknown, cache=cache)['status'] == 'unknown'
    aliases = []
    for version, build in (('2023.1', '2023.1.19.8928'), ('2024.1', '2024.1.13.9056'), ('2025.1', '2025.1.7.9143')):
        for host in ('wwise-console', 'wwise-authoring'):
            route = f'{version}|{host}|{build}|function|ak.wwise.core.profiler.getPerformanceMonitor'
            selected = [row for row in _native_rows(route) if row['kind'] == 'empty_string'
                        and '/@definition/<schema>/' in row['pointer']]
            assert len(selected) == 2
            for branch in selected:
                classified = classify_empty_candidate(ROOT, branch, cache=cache)
                assert classified['status'] == 'accepted', classified
                direct = next(row for row in _native_rows(route) if row['pointer'] == branch['pointer'].replace('/@definition/<schema>', ''))
                direct_class = classify_empty_candidate(ROOT, direct, cache=cache)
                assert classified['context_sha256'] == direct_class['context_sha256']
                assert classified['parent_schema_sha256'] == direct_class['parent_schema_sha256']
                aliases.append(branch['id'])
    assert len(aliases) == 12
