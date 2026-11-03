"""Direct public Gateway behavior with injected native responses."""

from copy import deepcopy

import json

from pathlib import Path

from time import perf_counter

import pytest

from tests.maintenance import branch_coverage_audit as audit

from tests.unit.test_runtime_business_gateway import _RuntimeControlDraftClient, _env, gateway

URI = 'ak.wwise.core.profiler.getRTPCs'

RPM = '{63D15B0F-16E7-4B8A-B9CA-7BF10AD315B4}'

BUILDS = {'2021.1': (14, 8108), '2022.1': (19, 8584), '2023.1': (19, 8928),
          '2024.1': (13, 9056), '2025.1': (7, 9143)}

FIXTURES = audit.ROOT / 'tests/fixtures/branch-evidence/product'

def public_rtpc_read(root, version='2022.1', host='wwise-authoring', position='23637', rows=None, native_reads=None):
    source_context = None
    root.mkdir(parents=True, exist_ok=True)
    native_rows = deepcopy(rows if rows is not None else [
        {'id': RPM, 'name': 'RPM', 'gameObjectId': 18446744073709551615, 'value': 1000.0},
        {'id': RPM, 'name': 'RPM', 'gameObjectId': 18446744073709551614, 'value': 1000.0}])
    class Client(_RuntimeControlDraftClient):
        def __init__(self):
            super().__init__(root, version=version)
            self.calls = []
        def call(self, uri, args=None, options=None):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            if uri == URI:
                result = {'return': deepcopy(native_rows)}
            elif uri == 'ak.wwise.core.profiler.getCursorTime':
                result = {'return': 12345 if args['cursor'] == 'capture' else 23456}
            else:
                result = super().call(uri, args, options)
            if uri == 'ak.wwise.core.getInfo':
                minor, build = BUILDS[version]
                result['isCommandLine'] = host == 'wwise-console'
                result['version'].update(minor=minor, build=build, displayName=f'v{version}.{minor}.{build}')
            if native_reads is not None:
                native_reads.append({'ordinal': len(self.calls) - 1, 'uri': uri,
                    'args': deepcopy(args), 'options': deepcopy(options), 'result': deepcopy(result)})
            return result
    client = Client()
    argv = ['core-call', URI, '--profiler-position', position, '--max-results', '64']
    code, payload = gateway.execute_gateway(['--state-dir', str(root / 'state'), *argv],
        env=_env(root, version=version), client_factory=lambda _: client)
    assert code == 0, json.dumps(payload)
    assert payload['agent_result']['return'] == native_rows
    assert payload['agent_result']['complete'] is True
    expected_time = int(position) if position.isdecimal() else 12345 if position == 'capture-latest' else 23456
    assert client.calls[-1] == (URI, {'time': expected_time}, {})
    return {'argv': argv, 'exit_code': code, 'payload': payload}, {
        'uri': URI, 'args': {'time': expected_time}, 'options': {}, 'result': {'return': native_rows}}, source_context

@pytest.mark.parametrize('version', BUILDS)
@pytest.mark.parametrize('host', ('wwise-console', 'wwise-authoring'))
def test_public_rtpc_contract_and_exact_mapping_across_versions(tmp_path, version, host):
    # Both zero and positive time cross the actual public construction boundary.
    for position in ('0', '23637'):
        receipt, dispatch, _ = public_rtpc_read(tmp_path / position, version, host, position)
        assert dispatch['args'] == {'time': int(position)}
        assert receipt['payload']['agent_result']['profiler_position'] == position

@pytest.mark.parametrize('version,count', [('2022.1', 17), ('2025.1', 5)])
def test_original_complete_native_arrays_preserved_through_public_gateway(tmp_path, request, version, count):
    originals = (FIXTURES / 'runtime-rtpc-fields-r109/originals/2022.1' if version == '2022.1'
        else FIXTURES / 'runtime-read-r108')
    capture = json.loads((originals / 'original-capture.json').read_bytes())
    evidence = capture['outcomes']['profiler-rtpcs-observation']['evidence']
    rows = evidence['agent_result']['return']
    receipt, dispatch, context = public_rtpc_read(tmp_path, version, position=str(evidence['position_ms']), rows=rows)
    assert len(receipt['payload']['agent_result']['return']) == count
    if version == '2022.1':
        # Reflection's uniqueName pattern does not describe these original strings.
        # Preserve actual native names; this makes no whole-array schema claim.
        assert rows[12]['name'] == 'CC #1: Modulation'
        assert rows[14]['name'] == 'MIDI note velocity'

@pytest.mark.parametrize('arguments', [
    ['--profiler-position', '-1'], ['--profiler-position', '1.5'],
    ['--profiler-position', 'NaN'], ['--profiler-position', '0', '--args', '{}'],
    ['--profiler-position', '0', '--options', '{}'],
])
def test_rtpc_construction_rejects_negative_nondecimal_and_native_inputs(tmp_path, arguments):
    client = _RuntimeControlDraftClient(tmp_path, version='2022.1')
    calls = []
    original = client.call
    def call(uri, args=None, options=None):
        calls.append(uri)
        return original(uri, args, options)
    client.call = call
    if '--args' in arguments or '--options' in arguments:
        with pytest.raises(SystemExit) as rejected:
            gateway.execute_gateway(['core-call', URI, *arguments],
                env=_env(tmp_path, version='2022.1'), client_factory=lambda _: client)
        assert rejected.value.code == 2
    else:
        code, payload = gateway.execute_gateway(['core-call', URI, *arguments],
            env=_env(tmp_path, version='2022.1'), client_factory=lambda _: client)
        assert code != 0, payload
    assert URI not in calls

@pytest.mark.parametrize('version', BUILDS)
@pytest.mark.parametrize('position', ('capture-latest', 'user-cursor'))
def test_cursor_choices_stay_owned_two_step_reads_without_enum_credit(tmp_path, version, position):
    receipt, dispatch, _ = public_rtpc_read(tmp_path, version, position=position)
    assert dispatch['args'] == {'time': 12345 if position == 'capture-latest' else 23456}
    assert receipt['payload']['agent_result']['profiler_position'] == position

def rtpc_scalar_rows():
    return [
        {'id': '{aBcD1234-16e7-4B8A-b9ca-7BF10ad315B4}', 'name': 'Engine_Load', 'gameObjectId': 0, 'value': 0.0},
        {'id': RPM, 'name': 'RPM', 'gameObjectId': 18446744073709551615, 'value': 1000.0},
        {'id': RPM, 'name': 'CC #1: Modulation', 'gameObjectId': 1, 'value': 1.0},
    ]


@pytest.mark.parametrize('version', BUILDS)
def test_public_rtpc_discloses_legacy_label_compatibility_after_row_validation(tmp_path, version):
    from wwise_waapi.builders.schema import validate_semantic_result
    receipt, dispatch, _ = public_rtpc_read(tmp_path, version, rows=rtpc_scalar_rows())
    metadata = receipt['payload']['schema_validation']['result']
    rules = metadata.get('compatibility_rules', [])
    assert receipt['payload']['agent_result']['return'][2]['name'] == 'CC #1: Modulation'
    assert metadata['unresolved_refs']  # Conservative traversal remains accurately disclosed.
    assert not validate_semantic_result(URI, dispatch['result'], version=version).compatibility_rules
    if version == '2025.1':
        assert not rules
    else:
        assert len(rules) == 1
        assert rules[0] == {
            'rule': 'rtpc-legacy-name-label-preservation',
            'section': '$.return[*].name', 'definition': 'waapi_definitions.json#/definitions/uniqueName',
            'reflected_pattern': '^[a-zA-Z_]+[a-zA-Z_0-9()]*$',
            'enforced_type': 'string', 'pattern_enforced': False,
            'behavior': 'Preserve native labels unchanged, including labels outside the reflected pattern',
        }

@pytest.mark.parametrize('returned', (-1, True, 1.5))
def test_rtpc_invalid_cursor_response_stops_before_rtpc_dispatch(tmp_path, returned):
    calls = []
    class Client(_RuntimeControlDraftClient):
        def call(self, uri, args=None, options=None):
            calls.append(uri)
            if uri == 'ak.wwise.core.profiler.getCursorTime':
                return {'return': returned}
            return super().call(uri, args, options)
    client = Client(tmp_path, version='2022.1')
    code, payload = gateway.execute_gateway(['--state-dir', str(tmp_path / 'state'), 'core-call', URI, '--profiler-position', 'capture-latest'],
        env=_env(tmp_path, version='2022.1'), client_factory=lambda _: client)
    assert code != 0, payload
    assert calls.count('ak.wwise.core.profiler.getCursorTime') == 1, payload
    assert URI not in calls
