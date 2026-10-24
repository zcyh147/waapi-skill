"""Exact live type selections are bounded read sources, never aliases or authority."""
from __future__ import annotations
import json
import pytest
from tests.unit.test_metadata_discovery_gateway import (
    FakeClient, _metadata_responses, _gateway_env, _metadata_command_platform,
    _assert_metadata_command, waapi_gateway as gateway, GET_TYPES_URI,
    OBJECT_GET_URI, GET_INFO_URI, OBJECT_GUID,
)
from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS as VERSIONS


def setup_type(tmp_path, version):
    name = 'NativePlugin_' + 'X' * 6000
    responses = _metadata_responses(tmp_path, version=version)
    # Both category and class ID are optional; neither spells a WAQL type.
    responses[GET_TYPES_URI] = {'return': [{'name': name}]}
    gateway.validate_semantic_result(GET_TYPES_URI, responses[GET_TYPES_URI], version=version)
    responses[OBJECT_GET_URI] = {'return': []}
    client = FakeClient(responses)
    env = _gateway_env(tmp_path, version=version)
    client.test_env = env
    def run(argv):
        return gateway.execute_gateway(argv, env=env, client_factory=lambda _: client)
    code, listed = run(['metadata', 'types'])
    assert code == 0, listed
    return name, client, run, listed['agent_result']['types'][0]


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('platform', ['posix', 'windows'])
def test_disclosed_long_native_type_is_exact_query_source(tmp_path, version, platform, monkeypatch):
    _metadata_command_platform(monkeypatch, platform)
    name, client, run, row = setup_type(tmp_path, version)
    command = row['query_command']
    _assert_metadata_command(command, platform)
    assert name not in command['gateway_argv']
    assert len(command['shell_command'].encode('utf-8')) < 8192
    code, result = run([*command['gateway_argv'], '--predicate', 'name-is', 'Selected',
                        '--include', 'notes', '--platform', 'Mac', '--language', 'SFX'])
    assert code == 0, result
    assert result['agent_result'] == []
    assert list(result)[-1] == 'agent_result'
    assert len(json.dumps(result, ensure_ascii=False, indent=2).encode()) < 64 * 1024
    assert client.calls[-1] == (OBJECT_GET_URI,
        {'waql': f'from type {name} where name = "Selected" take 20'},
        {'return': ['id', 'name', 'type', 'path', 'notes'], 'platform': 'Mac', 'language': 'SFX'})


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('change', ['inventory', 'session'])
def test_type_selection_drift_stops_before_object_query(tmp_path, version, change):
    _, client, run, row = setup_type(tmp_path, version)
    if change == 'inventory':
        client.responses[GET_TYPES_URI] = {'return': [{'name': 'Unrelated'}]}
    else:
        client.responses[GET_INFO_URI] = {**client.responses[GET_INFO_URI], 'sessionId': OBJECT_GUID}
    before = len(client.calls)
    code, result = run(['query-object', '--type-selection', row['selection'], '--max-results', '2'])
    assert code == 2 and result['error_code'] == 'METADATA_SELECTION_SCOPE_CHANGED', result
    assert not any(uri == OBJECT_GET_URI for uri, _, _ in client.calls[before:])


@pytest.mark.parametrize('version', VERSIONS)
def test_exact_type_selection_resolves_ambiguous_loose_names(tmp_path, version):
    _, client, run, _ = setup_type(tmp_path, version)
    client.responses[GET_TYPES_URI] = {'return': [{'name': 'Foo.Bar'}, {'name': 'Foo_Bar'}]}
    code, ambiguous = run(['query-object', '--custom-kind', 'Foo Bar', '--max-results', '2'])
    assert code == 0 and ambiguous['status'] == 'needs_clarification', ambiguous
    assert ambiguous['agent_result']['candidate_count'] == 2
    assert not any(uri == OBJECT_GET_URI for uri, _, _ in client.calls)
    code, listed = run(['metadata', 'types'])
    assert code == 0, listed
    selected = next(row for row in listed['agent_result']['types'] if row['name'] == 'Foo_Bar')
    code, result = run(['query-object', '--type-selection', selected['selection'], '--max-results', '20'])
    assert code == 0, result
    assert client.calls[-1] == (OBJECT_GET_URI, {'waql': 'from type Foo_Bar take 20'},
                              {'return': ['id', 'name', 'type', 'path']})


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('name', ['Bad Type', 'Bad"Type', 'Sound take 1000; from type Event', None])
def test_discovered_type_name_never_becomes_native_expression(tmp_path, version, name):
    _, client, run, _ = setup_type(tmp_path, version)
    client.responses[GET_TYPES_URI] = {'return': [{} if name is None else {'name': name}]}
    code, listed = run(['metadata', 'types'])
    assert code == 0, listed
    selected = listed['agent_result']['types'][0]
    code, result = run(['query-object', '--type-selection', selected['selection'], '--max-results', '20'])
    expected = 'METADATA_TYPE_NAME_UNAVAILABLE' if name is None else 'METADATA_TYPE_QUERY_SYNTAX_UNAVAILABLE'
    assert code == 2 and result['error_code'] == expected, result
    assert not any(uri == OBJECT_GET_URI for uri, _, _ in client.calls)


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('change', ['expired', 'host'])
def test_type_selection_expiry_and_endpoint_binding(tmp_path, version, change, monkeypatch):
    _, client, run, row = setup_type(tmp_path, version)
    if change == 'expired':
        import time
        now = time.time()
        monkeypatch.setattr(time, 'time', lambda: now + 901)
    else:
        # This is isolated test configuration, never the user's config.
        from pathlib import Path
        config = Path(client.test_env['WAAPI_SKILL_CONFIG_PATH'])
        data = json.loads(config.read_text())
        data['waapi_port'] += 1
        config.write_text(json.dumps(data))
    code, result = run(row['query_command']['gateway_argv'])
    expected = 'METADATA_SELECTION_EXPIRED' if change == 'expired' else 'METADATA_SELECTION_SCOPE_CHANGED'
    assert code == 2 and result['error_code'] == expected, result
    assert not any(uri == OBJECT_GET_URI for uri, _, _ in client.calls)


@pytest.mark.parametrize('version', VERSIONS)
def test_selected_catalog_type_retains_native_query_rejection_without_alias_retry(tmp_path, version):
    from tests.unit.test_waapi_gateway import WaapiRequestFailed
    _, client, run, _ = setup_type(tmp_path, version)
    client.responses[GET_TYPES_URI] = {'return': [{'name': 'ObjectSettingAssoc', 'type': 'WObject', 'classId': 1572880}]}
    code, listed = run(['metadata', 'types'])
    assert code == 0, listed
    client.errors[OBJECT_GET_URI] = WaapiRequestFailed('ak.wwise.query.invalid_query',
        {'message': 'Unknown object type (11)'})
    code, result = run(['query-object', '--type-selection', listed['agent_result']['types'][0]['selection'], '--max-results', '20'])
    assert code == 2 and result['status'] == 'error', result
    assert result['call']['waapi_error_uri'] == 'ak.wwise.query.invalid_query'
    assert [args for uri, args, _ in client.calls if uri == OBJECT_GET_URI] == [
        {'waql': 'from type ObjectSettingAssoc take 20'}]
    assert result['agent_result'] is None


@pytest.mark.parametrize('version', VERSIONS)
def test_selected_type_result_pages_revalidate_exact_inventory(tmp_path, version):
    from tests.unit.test_object_query_result_pages import QueryTask
    class SelectedTypeTask(QueryTask):
        native_types = [{'name': 'NativePlugin_' + 'X' * 6000}]
        def call(self, uri, args=None, options=None):
            if uri == GET_TYPES_URI:
                self.calls.append((uri, args, options))
                return {'return': self.native_types}
            return super().call(uri, args, options)
    task = SelectedTypeTask(tmp_path, version)
    code, listed = task.run('metadata', 'types')
    assert code == 0, listed
    command = listed['agent_result']['types'][0]['query_command']['gateway_argv']
    code, first = task.run(*command, '--include', 'notes')
    assert code == 0 and first['status'] == 'partial', first
    page = first['agent_result']
    original_next = page['next_command']['gateway_argv']
    fragments = []
    while True:
        fragments.extend(entry['value'] for entry in page['entries']
            if entry['pointer'] == '/objects/0/notes')
        if page['projection_complete']:
            break
        code, result = task.run(*page['next_command']['gateway_argv'])
        assert code == 0 and list(result)[-1] == 'agent_result', result
        assert result['agent_result']['page']['mutation_authority'] is False
        page = result['agent_result']
    assert ''.join(fragments) == task.row['notes']
    task.native_types = [{'name': 'Unrelated'}]
    before = len(task.calls)
    code, rejected = task.run(*original_next)
    assert code == 2 and rejected['error_code'] == 'METADATA_SELECTION_SCOPE_CHANGED', rejected
    # 2021 has no getProjectInfo route: its existing exact context check uses
    # object.get, but must never reissue the selected type's data query.
    assert [args for uri, args, _ in task.calls[before:] if uri == OBJECT_GET_URI] == (
        [{'waql': 'from type Project take 1'}] if version == '2021.1' else [])


@pytest.mark.parametrize('version', VERSIONS)
def test_native_type_extensions_cannot_overwrite_gateway_selection(tmp_path, version):
    _, client, run, _ = setup_type(tmp_path, version)
    native = {'name': 'Sound', 'selection': 'native extension', 'query_command': {'future': None}}
    client.responses[GET_TYPES_URI] = {'return': [native]}
    code, listed = run(['metadata', 'types'])
    assert code == 0, listed
    row = listed['agent_result']['types'][0]
    assert row['details_complete'] is False
    code, detail = run(row['detail_command']['gateway_argv'])
    assert code == 0 and detail['agent_result']['complete'] is True, detail
    values = {entry['pointer']: entry.get('value') for entry in detail['agent_result']['entries']}
    assert values['/selection'] == 'native extension'
    assert values['/query_command/future'] is None
    code, result = run(row['query_command']['gateway_argv'])
    assert code == 0, result
    assert client.calls[-1][1] == {'waql': 'from type Sound take 20'}
