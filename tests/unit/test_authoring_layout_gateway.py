"""Public Gateway seam for ordinary Authoring layout discovery (#188)."""
from __future__ import annotations

import pytest

from tests.support.gateway_config import set_gateway_config
from tests.unit.test_waapi_gateway import FakeClient, gateway_env, live_info, waapi_gateway as gateway

URI = 'ak.wwise.ui.layout.'
READS = [
    ('getLayoutNames', 'names', None, {'layouts': ['Designer', 'Profiler']}),
    ('getCurrentLayoutName', 'current', None, {'name': ''}),
    ('getLayout', 'contents', 'Designer', {'Layout': {'Name': 'Designer'}}),
    ('getViewInstances', 'instances', 'Designer', {'viewInstances': []}),
    ('getViewTypes', 'types', None, {'viewTypes': []}),
]


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
@pytest.mark.parametrize('suffix,subject,name,result', READS)
def test_layout_discovery_schema_reaches_bounded_authoring_read(tmp_path, version, suffix, subject, name, result):
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version=version, project_modification_policy='read_only')
    code, schema = gateway.execute_gateway(['request-schema', URI + suffix], env=env,
        client_factory=lambda _: pytest.fail('schema must remain offline'))
    assert code == 0, schema
    argv = schema['continuation']['gateway_argv']
    assert argv == ['layout-read', subject]
    if name is not None:
        argv = [*argv, '--layout-name', name]
    client = FakeClient({'ak.wwise.core.getInfo': live_info(year=int(version[:4]), command_line=False),
                         URI + suffix: result})
    code, payload = gateway.execute_gateway(argv, env=env, client_factory=lambda _: client)
    assert code == 0, payload
    assert payload['result'] == result
    assert payload['complete'] is True and payload['truncated'] is False
    assert client.calls[-1] == (URI + suffix, {'name': name} if name is not None else {}, {})
    assert client.disconnected


def test_layout_names_contract_discloses_factory_scope_and_contents_limit(tmp_path):
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version='2025.1')
    _, names = gateway.execute_gateway(['request-schema', URI + 'getLayoutNames'], env=env)
    _, contents = gateway.execute_gateway(['request-schema', URI + 'getLayout'], env=env)
    assert names['result_scope'] == 'factory_layout_names'
    assert contents['result_scope'] == 'bounded_native_document_with_unresolved_definition_semantics'
    assert contents['safety']['mutation_identity_authority'] is False


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
@pytest.mark.parametrize('subject', ['names', 'current', 'contents', 'instances', 'types'])
def test_layout_read_rejects_console_without_target_dispatch(tmp_path, version, subject):
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version=version)
    client = FakeClient({'ak.wwise.core.getInfo': live_info(year=int(version[:4]), command_line=True)})
    argv = ['layout-read', subject]
    if subject in {'contents', 'instances'}:
        argv += ['--layout-name', 'Designer']
    code, result = gateway.execute_gateway(argv, env=env, client_factory=lambda _: client)
    assert code == 2 and result['error_code'] == 'AUTHORING_HOST_REQUIRED'
    assert [call[0] for call in client.calls] == ['ak.wwise.core.getInfo']
    assert client.disconnected


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1'])
def test_layout_reads_have_exact_older_version_boundary_before_connect(tmp_path, version):
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version=version)
    for argv in (['request-schema', URI + 'getLayoutNames'], ['layout-read', 'names']):
        code, result = gateway.execute_gateway(argv, env=env,
            client_factory=lambda _: pytest.fail('known absence must not connect'))
        assert code == 2
        assert 'absent' in result['message'].lower()


@pytest.mark.parametrize('argv', [
    ['layout-read', 'contents'], ['layout-read', 'instances'],
    ['layout-read', 'types', '--layout-name', 'Designer'],
    ['layout-read', 'contents', '--layout-name', 'x' * 4097],
])
def test_invalid_layout_business_input_never_connects(tmp_path, argv):
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version='2025.1')
    code, result = gateway.execute_gateway(argv, env=env,
        client_factory=lambda _: pytest.fail('invalid business input must not connect'))
    assert code == 2 and result['ok'] is False


@pytest.mark.parametrize('subject,result,valid', [
    ('instances', {'viewInstances': [{'viewID': '{00000000-0000-0000-0000-000000000001}',
                                    'viewName': 'ProjectExplorer', 'viewDisplayName': 'Project Explorer',
                                    'viewIsDocked': True}]}, True),
    ('instances', {'viewInstances': [{'viewName': 'ProjectExplorer'}]}, True),
    ('types', {'viewTypes': [{'viewName': 'ProjectExplorer', 'viewDisplayName': 'Project Explorer'}]}, True),
    ('types', {'viewTypes': [{}]}, True),
    ('contents', {'Layout': {'Name': 'Designer', 'StackPanel': {'native_observed': True}}}, True),
    ('names', {'layouts': [1]}, False), ('current', {'name': None}, False),
    ('types', {'viewTypes': [{'viewName': 1}]}, False),
    ('types', {'viewTypes': [{'extra': 'forbidden'}]}, False),
    ('instances', {'viewInstances': [{'viewID': 'not-a-guid'}]}, False),
    ('instances', {'viewInstances': [{'viewIsDocked': 1}]}, False),
    ('contents', {'Layout': {}}, False), ('current', {'name': '', 'extra': 1}, False),
    ('names', {'layouts': ['Designer'] * 1025}, False),
    ('current', {'name': 'x' * (256 * 1024)}, False),
])
def test_layout_read_result_is_bounded_and_preserves_optional_native_fields(tmp_path, subject, result, valid):
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version='2025.1', project_modification_policy='read_only')
    suffix = next(row[0] for row in READS if row[1] == subject)
    client = FakeClient({'ak.wwise.core.getInfo': live_info(year=2025, command_line=False), URI + suffix: result})
    argv = ['layout-read', subject]
    if subject in {'contents', 'instances'}:
        argv += ['--layout-name', 'Designer']
    code, payload = gateway.execute_gateway(argv, env=env, client_factory=lambda _: client)
    assert (code == 0) is valid, payload
    assert client.disconnected
    if valid:
        assert payload['result'] == payload['agent_result'] == result
        if subject == 'contents':
            assert payload['observation']['native_schema_status'] == 'definition_semantics_unresolved'
            assert payload['observation']['business_arrangement_verified'] is False
    else:
        assert payload['ok'] is False
        assert payload.get('complete') is not True


def test_layout_read_native_failure_is_reported_without_retry(tmp_path):
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version='2025.1')
    client = FakeClient({'ak.wwise.core.getInfo': live_info(year=2025, command_line=False),
                         URI + 'getLayoutNames': RuntimeError('native observation failed')})
    code, result = gateway.execute_gateway(['layout-read', 'names'], env=env, client_factory=lambda _: client)
    assert code == 2 and result['call']['ok'] is False
    assert [call[0] for call in client.calls] == ['ak.wwise.core.getInfo', URI + 'getLayoutNames']
    assert client.disconnected


def test_layout_read_retains_bounded_native_schema_mismatch_evidence(tmp_path):
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version='2025.1')
    native = {'Layout': {'unexpectedNativeShape': 'preserve this observation'}}
    client = FakeClient({'ak.wwise.core.getInfo': live_info(year=2025, command_line=False),
                         URI + 'getLayout': native})
    code, payload = gateway.execute_gateway(['layout-read', 'contents', '--layout-name', 'Designer'],
        env=env, client_factory=lambda _: client)
    assert code == 2 and payload['error_code'] == 'INVALID_LAYOUT_READ_RESULT'
    assert payload['details']['native_observation'] == native
    assert payload['details']['business_arrangement_verified'] is False


@pytest.mark.parametrize('argv', [
    ['draft-start', URI + 'getLayoutNames'],
    ['typed-zero-call', URI + 'getLayoutNames', '--schema-digest', 'forged'],
])
def test_closed_layout_reads_do_not_open_generic_typed_construction(tmp_path, argv):
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version='2025.1')
    code, payload = gateway.execute_gateway(argv, env=env,
        client_factory=lambda _: pytest.fail('closed-route rejection must not connect'))
    assert code == 2
    assert 'layout-read' in payload['message']
