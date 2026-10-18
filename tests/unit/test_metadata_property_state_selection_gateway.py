"""Read-only exact selected field state through the actual public Gateway."""
from copy import deepcopy

import pytest

from tests.unit.test_metadata_discovery_gateway import (
    waapi_gateway, FakeClient, _gateway_env, _metadata_responses,
    OBJECT_GUID, GET_PROPERTY_INFO_URI, IS_PROPERTY_ENABLED_URI,
    GET_INFO_URI, GET_NAMES_URI, OBJECT_GET_URI, SESSION_B, _property_info,
)


def selected_reference_task(tmp_path, version='2025.1'):
    # Actual 553 AuxBus reference metadata, never a fabricated Boolean controller.
    reference = {'name': 'UserAuxSend0', 'type': '', 'default': None,
        'restriction': {'type': 'reference', 'restrictions': [{'type': ['Auxiliary Bus'], 'sharedOnlyTypes': []}]},
        'supports': {'randomizer': False, 'rtpc': 'None', 'unlink': False},
        'dependencies': [{'action': 'Show', 'context': 'Self', 'type': 'isMasterBus', 'value': False},
            {'action': 'Enable', 'context': 'Self', 'type': 'override', 'property': 'OverrideUserAuxSends'}]}
    names = ('Volume', *(f'UserAuxSendHPF{i}' for i in range(4)), *(f'UserAuxSendLPF{i}' for i in range(4)), 'UserAuxSend0')
    responses = _metadata_responses(tmp_path, version=version, names=names)
    def info(args, _options):
        assert args == {'object': OBJECT_GUID, 'property': 'UserAuxSend0'}, args
        return deepcopy(reference)
    responses[GET_PROPERTY_INFO_URI] = info
    responses[IS_PROPERTY_ENABLED_URI] = {'return': True}
    client, env = FakeClient(responses), _gateway_env(tmp_path, version=version)
    def run(*argv):
        return waapi_gateway.execute_gateway(list(argv), env=env, client_factory=lambda _url: client)
    code, listed = run('metadata', 'list', '--exact-id', OBJECT_GUID, '--page-size', '64')
    assert code == 0, listed
    selection, = [row['selection'] for row in listed['agent_result']['fields'] if row['name'] == 'UserAuxSend0']
    return run, client, selection, reference


def test_selected_reference_state_preserves_native_boolean_without_controller_lookup(tmp_path):
    run, client, selection, _reference = selected_reference_task(tmp_path)
    code, payload = run('metadata', 'property-state', '--exact-id', OBJECT_GUID,
                        '--selection', selection, '--platform', 'Windows')
    assert code == 0, payload
    assert payload['agent_result']['enabled'] is True
    assert payload['agent_result']['field'] == 'UserAuxSend0'
    assert payload['agent_result']['kind'] == 'reference'
    assert payload['agent_result']['mutation_authority'] is False
    assert [(uri, args, options) for uri, args, options in client.calls if uri == IS_PROPERTY_ENABLED_URI] == [
        (IS_PROPERTY_ENABLED_URI, {'object': OBJECT_GUID, 'property': 'UserAuxSend0', 'platform': 'Windows'}, {})]


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1'])
@pytest.mark.parametrize('enabled', [True, False])
def test_selected_reference_state_is_versioned_current_object_observation_only(tmp_path, version, enabled):
    run, client, selection, reference = selected_reference_task(tmp_path, version)
    client.responses[IS_PROPERTY_ENABLED_URI] = {'return': enabled}
    code, schema = run('request-schema', IS_PROPERTY_ENABLED_URI)
    assert code == 0 and schema['commands'][0]['input_forms']['field_choice']['selected_kinds'] == ['property', 'reference'], schema
    code, detail = run('metadata', 'detail', '--exact-id', OBJECT_GUID, '--selection', selection)
    assert code == 0 and detail['agent_result']['metadata']['type'] == '', detail
    assert detail['agent_result']['metadata']['dependencies'] == reference['dependencies']
    code, result = run('metadata', 'property-state', '--exact-id', OBJECT_GUID,
                       '--selection', selection, '--platform', 'Windows')
    assert code == 0 and result['agent_result']['enabled'] is enabled, result
    assert result['agent_result']['selection'] == selection
    assert result['agent_result']['scope'] == {'kind': 'object', 'object': OBJECT_GUID}
    assert result['agent_result']['mutation_authority'] is False
    assert len([c for c in client.calls if c[0] == IS_PROPERTY_ENABLED_URI]) == 1
    assert [c[1]['property'] for c in client.calls if c[0] == GET_PROPERTY_INFO_URI] == ['UserAuxSend0', 'UserAuxSend0']


@pytest.mark.parametrize('failure', ['native-refusal', 'timeout', 'malformed', 'wrong-metadata-name', 'unknown-kind'])
def test_selected_reference_state_preserves_failure_without_fallback_or_write(tmp_path, failure):
    run, client, selection, reference = selected_reference_task(tmp_path)
    if failure == 'native-refusal':
        class WaapiRequestFailed(Exception):
            uri = 'ak.wwise.invalid_arguments'
            kwargs = {'details': {'property': 'UserAuxSend0', 'procedureUri': IS_PROPERTY_ENABLED_URI},
                      'message': 'Property does not exist on this object.'}
        client.errors[IS_PROPERTY_ENABLED_URI] = WaapiRequestFailed('native reference observation refusal')
    elif failure == 'timeout':
        client.errors[IS_PROPERTY_ENABLED_URI] = TimeoutError('reference enabled response unobserved')
    elif failure == 'malformed':
        client.responses[IS_PROPERTY_ENABLED_URI] = {'return': 'true'}
    elif failure == 'wrong-metadata-name':
        client.responses[GET_PROPERTY_INFO_URI] = {**reference, 'name': 'UserAuxSend1'}
    else:
        client.responses[GET_PROPERTY_INFO_URI] = {'name': 'UserAuxSend0', 'type': '', 'supports': {}}
    code, result = run('metadata', 'property-state', '--exact-id', OBJECT_GUID,
                       '--selection', selection, '--platform', 'Windows')
    assert code == 2 and result.get('agent_result') is None, result
    calls = [c for c in client.calls if c[0] == IS_PROPERTY_ENABLED_URI]
    assert len(calls) == (0 if failure in {'wrong-metadata-name', 'unknown-kind'} else 1)
    if failure == 'native-refusal':
        assert result['call']['waapi_error_uri'] == 'ak.wwise.invalid_arguments', result
        assert result['call']['waapi_error_details']['details']['property'] == 'UserAuxSend0'
    if failure == 'malformed':
        assert result['details']['call']['api'] == IS_PROPERTY_ENABLED_URI, result
        assert result['details']['native_result'] == {'return': 'true'}, result
    assert all(c[0] in {GET_INFO_URI, GET_NAMES_URI, OBJECT_GET_URI, GET_PROPERTY_INFO_URI, IS_PROPERTY_ENABLED_URI} for c in client.calls)


@pytest.mark.parametrize('drift', ['object', 'names', 'session', 'project', 'version', 'forged', 'expired'])
def test_selected_reference_state_reuses_scope_inventory_session_and_expiry_guards(tmp_path, monkeypatch, drift):
    import time
    run, client, selection, _reference = selected_reference_task(tmp_path)
    scope = OBJECT_GUID
    if drift == 'object':
        scope = '{33333333-3333-3333-3333-333333333333}'
    elif drift == 'names':
        client.responses[GET_NAMES_URI]['return'].append('NewField')
    elif drift == 'session':
        client.responses[GET_INFO_URI]['sessionId'] = SESSION_B
    elif drift == 'project':
        client.responses[OBJECT_GET_URI]['return'][0]['id'] = '{44444444-4444-4444-4444-444444444444}'
    elif drift == 'version':
        client.responses[GET_INFO_URI]['version']['year'] = 2024
    elif drift == 'forged':
        selection = selection[:-1] + ('0' if selection[-1] != '0' else '1')
    else:
        later = time.time() + 901
        monkeypatch.setattr(time, 'time', lambda: later)
    code, result = run('metadata', 'property-state', '--exact-id', scope,
                       '--selection', selection, '--platform', 'Windows')
    assert code == 2, result
    assert not any(c[0] == IS_PROPERTY_ENABLED_URI for c in client.calls)


@pytest.mark.parametrize('extra', [[], ['--meaning', 'Volume'], ['--page', 'forged'], ['--detail-view', 'dependencies'],
    ['--platform', ' Windows '], ['--platform', 'Windows\x00'], ['--platform', 'x' * 1025]])
def test_selected_state_keeps_platform_and_input_bounds(tmp_path, extra):
    run, client, selection, _reference = selected_reference_task(tmp_path)
    platform = [] if not extra or extra[0] == '--platform' else ['--platform', 'Windows']
    code, result = run('metadata', 'property-state', '--exact-id', OBJECT_GUID,
                       '--selection', selection, *platform, *extra)
    assert code == 2, result
    assert not any(c[0] == IS_PROPERTY_ENABLED_URI for c in client.calls)


def test_selected_scalar_state_reuses_same_locator_without_fuzzy_metadata_reads(tmp_path):
    run, client, selection, _reference = selected_reference_task(tmp_path)
    code, page = run('metadata', 'list', '--exact-id', OBJECT_GUID, '--page-size', '64')
    volume = next(row['selection'] for row in page['agent_result']['fields'] if row['name'] == 'Volume')
    client.responses[GET_PROPERTY_INFO_URI] = _property_info('Volume')
    code, result = run('metadata', 'property-state', '--exact-id', OBJECT_GUID,
                       '--selection', volume, '--platform', 'Windows')
    assert code == 0 and result['agent_result']['kind'] == 'property', result
    assert [c[1]['property'] for c in client.calls if c[0] == IS_PROPERTY_ENABLED_URI] == ['Volume']


@pytest.mark.parametrize('selection', ['', 'UserAuxSend0', 'forged', 'mp1.0.0.invalid'])
def test_property_state_never_treats_missing_or_forged_locator_as_first_field(tmp_path, selection):
    run, client, _selection, _reference = selected_reference_task(tmp_path)
    client.responses[GET_PROPERTY_INFO_URI] = lambda args, options: _property_info(args['property'])
    code, result = run('metadata', 'property-state', '--exact-id', OBJECT_GUID,
                       '--selection', selection, '--platform', 'Windows')
    assert code == 2, result
    assert not any(call[0] == IS_PROPERTY_ENABLED_URI for call in client.calls)


@pytest.mark.parametrize('scope', [['--kind', 'sound'], ['--type-selection', 'forged-type']])
def test_selected_property_state_does_not_accept_class_scope(tmp_path, scope):
    run, client, selection, _reference = selected_reference_task(tmp_path)
    code, result = run('metadata', 'property-state', *scope, '--selection', selection, '--platform', 'Windows')
    assert code == 2, result
    assert not any(call[0] == IS_PROPERTY_ENABLED_URI for call in client.calls)
