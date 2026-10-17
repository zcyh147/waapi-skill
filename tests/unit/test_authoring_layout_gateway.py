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
    client = FakeClient({'ak.wwise.core.getInfo': live_info(year=2025, command_line=False)},
                        errors={URI + 'getLayoutNames': RuntimeError('native observation failed')})
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


ELEMENT_ID = '{11111111-1111-1111-1111-111111111111}'
VIEW_ID = '{22222222-2222-2222-2222-222222222222}'
PROJECT_ID = '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}'


def _identity_client(*, rectangle=None, instances=None, layout=None, version='2025.1'):
    info = live_info(year=int(version[:4]), command_line=False)
    info.update(processId=1234, sessionId='authoring-session-1')
    info['version']['schema'] = 152
    return FakeClient({
        'ak.wwise.core.getInfo': info,
        'ak.wwise.core.getProjectInfo': {'id': PROJECT_ID, 'name': 'Sandbox', 'path': r'C:\Sandbox\Sandbox.wproj'},
        URI + 'getLayout': layout or {'Layout': {'Name': 'Designer', 'StackPanel': {
            'Name': 'StackPanel', 'ID': ELEMENT_ID, 'Orientation': 'Horizontal', '@Children': [
                {'@type': 'Splitter', 'ID': '{33333333-3333-3333-3333-333333333333}'},
                {'@type': 'View', 'ID': VIEW_ID, 'Name': 'ProjectExplorer', 'SelectionChannel': '1'}]}}},
        URI + 'getViewInstances': {'viewInstances': instances if instances is not None else [
            {'viewID': VIEW_ID, 'viewName': 'ProjectExplorer', 'viewDisplayName': 'Project Explorer', 'viewIsDocked': True},
            {'viewID': VIEW_ID, 'viewName': 'ProjectExplorer', 'viewDisplayName': 'Project Explorer', 'viewIsDocked': True}]},
        URI + 'getElementRectangle': rectangle if rectangle is not None else {'left': 10, 'top': 20, 'right': 400, 'bottom': 300},
        URI + 'getViewHandle': ['{44444444-4444-4444-4444-444444444444}'],
    })


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
def test_layout_inspection_issues_scoped_elements_and_coalesces_duplicate_view_ids(tmp_path, version):
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version=version, project_modification_policy='read_only')
    code, schema = gateway.execute_gateway(['request-schema', URI + 'getElementRectangle'], env=env)
    assert code == 0, schema
    inspect_argv = [*schema['identity_discovery']['gateway_argv'], '--layout-name', 'Designer']
    state = ['--state-dir', str(tmp_path / 'state')]
    code, inspection = gateway.execute_gateway([*state, *inspect_argv], env=env, client_factory=lambda _: _identity_client(version=version))
    assert code == 0, inspection
    assert len(inspection['views']) == 1
    assert inspection['layout_handle'].startswith('lh1-')
    element = next(row for row in inspection['elements'] if row['kind'] == 'StackPanel')
    assert element['handle'].startswith('lh1-')
    assert element['location'] == '/Layout/StackPanel'
    assert element['name'] == 'StackPanel'
    assert inspection['views'][0]['display_name'] == 'Project Explorer'
    client = _identity_client(version=version)
    code, rectangle = gateway.execute_gateway([*state, *schema['continuation']['gateway_argv'],
        '--element-handle', element['handle']], env=env, client_factory=lambda _: client)
    assert code == 0, rectangle
    assert rectangle['result'] == {'left': 10, 'top': 20, 'right': 400, 'bottom': 300}
    assert client.calls[-1] == (URI + 'getElementRectangle', {'id': ELEMENT_ID}, {})


def _inspect_scoped_layout(tmp_path):
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version='2025.1', project_modification_policy='read_only')
    state = ['--state-dir', str(tmp_path / 'state')]
    code, inspection = gateway.execute_gateway([*state, 'layout-inspect', '--layout-name', 'Designer'],
        env=env, client_factory=lambda _: _identity_client())
    assert code == 0, inspection
    return env, state, inspection


def test_view_frontend_read_uses_live_scoped_identity_and_preserves_array_result(tmp_path):
    env, state, inspection = _inspect_scoped_layout(tmp_path)
    code, schema = gateway.execute_gateway(['request-schema', URI + 'getViewHandle'], env=env)
    assert code == 0, schema
    client = _identity_client()
    code, result = gateway.execute_gateway([*state, *schema['continuation']['gateway_argv'],
        '--view-handle', inspection['views'][0]['handle']], env=env, client_factory=lambda _: client)
    assert code == 0, result
    assert result['result'] == result['agent_result'] == ['{44444444-4444-4444-4444-444444444444}']
    assert client.calls[-1] == (URI + 'getViewHandle', {'viewID': VIEW_ID}, {})


@pytest.mark.parametrize('drift', ['session', 'process', 'project', 'config', 'view', 'role'])
def test_scoped_layout_read_rejects_stale_or_wrong_authority_before_target_dispatch(tmp_path, drift):
    env, state, inspection = _inspect_scoped_layout(tmp_path)
    client = _identity_client()
    handle = inspection['views'][0]['handle']
    if drift == 'session': client.responses['ak.wwise.core.getInfo']['sessionId'] = 'later-session'
    elif drift == 'process': client.responses['ak.wwise.core.getInfo']['processId'] = 5555
    elif drift == 'project': client.responses['ak.wwise.core.getProjectInfo']['id'] = '{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}'
    elif drift == 'config': set_gateway_config(env, waapi_port=31338)
    elif drift == 'view': client.responses[URI + 'getViewInstances'] = {'viewInstances': []}
    elif drift == 'role': handle = inspection['elements'][0]['handle']
    code, result = gateway.execute_gateway([*state, 'layout-read', 'frontend', '--view-handle', handle],
        env=env, client_factory=lambda _: client)
    assert code == 2 and result['ok'] is False
    assert URI + 'getViewHandle' not in [call[0] for call in client.calls]
    assert client.disconnected


def test_conflicting_duplicate_view_identity_cannot_issue_handles(tmp_path):
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version='2025.1')
    client = _identity_client(instances=[{'viewID': VIEW_ID, 'viewName': 'ProjectExplorer'},
                                       {'viewID': VIEW_ID, 'viewName': 'Transport'}])
    code, result = gateway.execute_gateway(['--state-dir', str(tmp_path / 'state'), 'layout-inspect',
        '--layout-name', 'Designer'], env=env, client_factory=lambda _: client)
    assert code == 2 and 'Conflicting duplicate view identity' in result['message']
    assert not list((tmp_path / 'state').glob('authoring-layout-handles-v1/*.json'))


def test_layout_directory_discloses_compact_authoring_namespace_defaults(tmp_path):
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version='2025.1')
    code, directory = gateway.execute_gateway(['operations'], env=env)
    assert code == 0, directory
    assert directory['request_schema_route_defaults_by_namespace']['ak.wwise.ui.layout.'] == {
        'host_surface': 'wwise-authoring', 'supported_versions': ['2024.1', '2025.1']}
    assert gateway.gateway_json_document_size(directory) < 26 * 1024


def test_layout_identity_discovery_never_treats_view_data_as_layout_elements(tmp_path):
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version='2025.1')
    client = _identity_client()
    layout = client.responses[URI + 'getLayout']['Layout']['StackPanel']
    layout['@Children'][1]['ViewData'] = {'arbitraryData': {'@type': 'View', 'ID': 'not-an-element'}}
    code, result = gateway.execute_gateway(['--state-dir', str(tmp_path / 'state'),
        'layout-inspect', '--layout-name', 'Designer'], env=env, client_factory=lambda _: client)
    assert code == 0, result
    assert len(result['elements']) == 3


def test_scoped_view_handle_record_cannot_be_replaced_by_a_symlink(tmp_path):
    env, state, inspection = _inspect_scoped_layout(tmp_path)
    handle = inspection['views'][0]['handle']
    record = tmp_path / 'state' / 'authoring-layout-handles-v1' / (handle + '.json')
    outside = tmp_path / 'outside.json'
    outside.write_bytes(record.read_bytes())
    record.unlink()
    record.symlink_to(outside)
    client = _identity_client()
    code, result = gateway.execute_gateway([*state, 'layout-read', 'frontend', '--view-handle', handle],
        env=env, client_factory=lambda _: client)
    assert code == 2 and 'links/reparse' in result['message']
    assert URI + 'getViewHandle' not in [call[0] for call in client.calls]


def test_scoped_layout_handle_expires_without_target_dispatch(tmp_path, monkeypatch):
    import time
    env, state, inspection = _inspect_scoped_layout(tmp_path)
    now = time.time()
    monkeypatch.setattr(time, 'time', lambda: now + 901)
    client = _identity_client()
    code, result = gateway.execute_gateway([*state, 'layout-read', 'frontend', '--view-handle',
        inspection['views'][0]['handle']], env=env, client_factory=lambda _: client)
    assert code == 2 and 'expired' in result['message']
    assert URI + 'getViewHandle' not in [call[0] for call in client.calls]


def test_inspection_reclaims_only_valid_expired_handles_at_capacity(tmp_path, monkeypatch):
    import json
    from copy import deepcopy
    from wwise_waapi import authoring_layout_handles as handles
    from wwise_waapi.canonical import canonical_sha256
    env, state, _ = _inspect_scoped_layout(tmp_path)
    root = tmp_path / 'state' / 'authoring-layout-handles-v1'
    live = {path: path.read_bytes() for path in root.iterdir()}
    template = json.loads(next(iter(live.values())))
    expired = []
    for index in range(len(live)):
        record = deepcopy(template)
        record['handle'] = 'lh1-' + format(index, '032x')
        record['expires_at'] = 1
        record.pop('sha256')
        record['sha256'] = canonical_sha256(record)
        path = root / (record['handle'] + '.json')
        path.write_text(json.dumps(record), encoding='utf-8')
        expired.append(path)
    preserved = {root / 'unowned.txt': b'keep user data', root / ('lh1-' + 'f' * 32 + '.json'): b'{broken'}
    for path, data in preserved.items():
        path.write_bytes(data)
    monkeypatch.setattr(handles, '_MAX_RECORDS', len(live) * 2 + len(preserved))
    code, result = gateway.execute_gateway([*state, 'layout-inspect', '--layout-name', 'Designer'],
        env=env, client_factory=lambda _: _identity_client())
    assert code == 0, result
    assert all(not path.exists() for path in expired)
    assert all(path.read_bytes() == data for path, data in {**live, **preserved}.items())
    assert len(list(root.iterdir())) == handles._MAX_RECORDS


@pytest.mark.parametrize('suffix,subject,name,_', READS)
def test_native_optional_outer_result_omission_is_preserved_without_invented_values(tmp_path, suffix, subject, name, _):
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version='2025.1')
    client = FakeClient({'ak.wwise.core.getInfo': live_info(year=2025, command_line=False), URI + suffix: {}})
    argv = ['layout-read', subject] + (['--layout-name', name] if name is not None else [])
    code, result = gateway.execute_gateway(argv, env=env, client_factory=lambda _: client)
    assert code == 0, result
    assert result['result'] == result['agent_result'] == {}
    assert result['observation']['native_schema_status'] == 'optional_result_field_omitted'
    assert result['observation']['business_arrangement_verified'] is False


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
def test_omitted_layout_contents_return_structured_unavailability_without_issuing_handles(tmp_path, version):
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version=version)
    state_dir = tmp_path / 'state'
    client = _identity_client(version=version)
    client.responses[URI + 'getLayout'] = {}
    client.responses[URI + 'getViewInstances'] = {'viewInstances': []}
    code, result = gateway.execute_gateway(['--state-dir', str(state_dir), 'layout-inspect', '--layout-name', 'Designer'],
        env=env, client_factory=lambda _: client)
    assert code == 2 and result['ok'] is False, result
    assert 'unavailable' in result['message'].lower(), result
    assert 'no identity handles issued' in result['message'].lower(), result
    assert not list(state_dir.glob('authoring-layout-handles-v1/*.json'))
