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


def test_empty_log_severity_requires_exact_public_result_rejection(tmp_path):
    rows = _native_rows()
    branch = next(row for row in rows if row['pointer'].endswith('/logCentralSeverity/@empty/string'))
    edges = {row['id']: row for row in rows if row['kind'] == 'reference'}
    valid = _log_receipt(tmp_path, 'Message')
    invalid = _log_receipt(tmp_path, '')
    assert valid['gateway']['exit_code'] == 0, valid
    assert invalid['gateway']['exit_code'] == 2 and 'agent_result' not in invalid['gateway']['payload'], invalid
    from tests.support.empty_candidate_evidence import classify_empty_candidate
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
    for damage in ('schema', 'candidate', 'success', 'error-field', 'no-dispatch', 'valid-counterpart', 'wrong-field', 'nonfinal'):
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
        else:
            damaged['invocation']['phase'] = 'call'
        damaged_descriptor = _seal(tmp_path / ('damage-' + damage + '.json'), damaged)
        rejected = evidence_result(damaged_descriptor, branch, 'controlled-current', 'program', 'controlled', tmp_path,
                                   damaged_binding, ROOT, edges)
        assert rejected[0] == 'missing', (damage, rejected)
    native = evidence_result(descriptor, branch, 'controlled-current', 'native', 'controlled', tmp_path, binding, ROOT, edges)
    assert native[0] == 'missing'

