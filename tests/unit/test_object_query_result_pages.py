"""Public lossless delivery of native-valid large object query values."""
from __future__ import annotations
import json
from pathlib import Path
import pytest
from tests.unit.test_waapi_gateway import FakeClient, gateway_env, live_info, PROJECT_GUID, waapi_gateway as gateway

VERSIONS = ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1')

@pytest.mark.parametrize('version', VERSIONS)
def test_large_native_notes_remain_readable_through_public_continuation(tmp_path: Path, version: str):
    env = gateway_env(tmp_path)
    env['WAAPI_SKILL_STATE_DIR'] = str(tmp_path / 'state')
    config = Path(env['WAAPI_SKILL_CONFIG_PATH'])
    config.write_text(json.dumps({'wwise_version': version, 'waapi_host': '127.0.0.1', 'waapi_port': 31337,
                                 'project_modification_policy': 'ask_before_changes'}))
    info = live_info(year=int(version[:4]))
    info.update(sessionId='{22222222-2222-2222-2222-222222222222}', processId=123)
    text = '声\\"\n' * 80000
    native = {'return': [{'id': PROJECT_GUID, 'name': 'Sound', 'type': 'Sound', 'path': r'\Actor-Mixer Hierarchy\Sound', 'notes': text}]}
    assert len(json.dumps(native, ensure_ascii=False).encode()) < 1024 * 1024
    class Client(FakeClient):
        def call(self, uri, args=None, options=None):
            if uri == 'ak.wwise.core.object.get' and args == {'waql': 'from type Project take 1'}:
                return {'return': [{'id': PROJECT_GUID, 'name': 'Project', 'type': 'Project', 'path': str(tmp_path / 'project' / 'Fixture.wproj')}]}
            return super().call(uri, args, options)
    client = Client({'ak.wwise.core.getInfo': info, 'ak.wwise.core.object.get': native, 'ak.wwise.core.getProjectInfo': {'id': PROJECT_GUID, 'name': 'Project', 'path': str(tmp_path / 'project' / 'Fixture.wproj')}})
    code, result = gateway.execute_gateway(['query-object', '--exact-id', PROJECT_GUID, '--include', 'notes'],
                                           env=env, client_factory=lambda _: client)
    assert code == 0, json.dumps(result, ensure_ascii=False)
    assert result['status'] == 'partial'
    pages = [result['agent_result']]
    while not pages[-1]['projection_complete']:
        code, result = gateway.execute_gateway(pages[-1]['next_command']['gateway_argv'], env=env, client_factory=lambda _: client)
        assert code == 0, json.dumps(result, ensure_ascii=False)
        assert list(result)[-1] == 'agent_result'
        assert len(json.dumps(result, ensure_ascii=False, indent=2).encode()) <= 32 * 1024
        pages.append(result['agent_result'])
    fragments = [entry for page in pages for entry in page['entries'] if entry['pointer'] == '/objects/0/notes']
    assert ''.join(entry['value'] for entry in fragments) == text
    assert pages[0]['objects'] == [{**{key: value for key, value in native['return'][0].items() if key != 'notes'}, 'projection_omitted_fields': ['notes']}]
    reads = [call for call in client.calls if call[0] == 'ak.wwise.core.object.get']
    assert all(call == reads[0] for call in reads)


class QueryTask:
    def __init__(self, tmp_path, version='2025.1'):
        self.env = gateway_env(tmp_path)
        self.env['WAAPI_SKILL_STATE_DIR'] = str(tmp_path / 'state')
        config = Path(self.env['WAAPI_SKILL_CONFIG_PATH'])
        data = json.loads(config.read_text()); data['wwise_version'] = version
        config.write_text(json.dumps(data))
        self.info = live_info(year=int(version[:4]))
        self.info.update(sessionId='{22222222-2222-2222-2222-222222222222}', processId=123)
        self.project = {'id': PROJECT_GUID, 'name': 'Project', 'type': 'Project', 'path': chr(92), 'filePath': str(tmp_path / 'project' / 'Fixture.wproj')}
        self.row = {'id': PROJECT_GUID, 'name': 'Sound', 'type': 'Sound', 'path': r'\Actor-Mixer Hierarchy\Sound', 'notes': '声' * 24000}
        self.calls = []
        self.field = 'Volume'

    def call(self, uri, args=None, options=None):
        self.calls.append((uri, args, options))
        if uri.endswith('getInfo'):
            return self.info
        if uri.endswith('getProjectInfo'):
            return self.project
        if uri.endswith('object.get'):
            if args == {'waql': 'from type Project take 1'}:
                return {'return': [self.project]}
            return {'return': [self.row]}
        if uri.endswith('getPropertyAndReferenceNames'):
            return {'return': [self.field]}
        if uri.endswith('getPropertyInfo'):
            return {'name': self.field, 'type': getattr(self, 'field_type', 'Real32')}
        raise AssertionError(uri)

    def disconnect(self):
        pass

    def run(self, *argv):
        return gateway.execute_gateway(list(argv), env=self.env, client_factory=lambda _: self)

    def first(self, *extra):
        code, payload = self.run('query-object', '--exact-id', PROJECT_GUID, '--include', 'notes', *extra)
        assert code == 0, json.dumps(payload)
        return payload


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('change', ['result', 'session', 'project', 'configuration', 'extra-query', 'cross-query', 'field-inventory', 'field-metadata'])
def test_query_result_pages_reject_changed_result_context_and_selection(tmp_path, version, change):
    task = QueryTask(tmp_path, version)
    extra = ('--include-field', 'Volume') if change in {'field-inventory', 'field-metadata'} else ()
    if extra:
        task.row['@Volume'] = 0.25
    first = task.first(*extra)
    argv = first['agent_result']['next_command']['gateway_argv']
    before = len(task.calls)
    if change == 'result':
        task.row['notes'] += '!'
    elif change == 'session':
        task.info['sessionId'] = '{33333333-3333-3333-3333-333333333333}'
    elif change == 'project':
        task.project['path'] = '/changed-project'
    elif change == 'configuration':
        config = Path(task.env['WAAPI_SKILL_CONFIG_PATH'])
        data = json.loads(config.read_text()); data['waapi_port'] = 31338
        config.write_text(json.dumps(data))
    elif change == 'field-metadata':
        task.field_type = 'Real64'
    elif change == 'extra-query':
        argv = [*argv, '--include', 'parent']
    elif change == 'cross-query':
        second = task.first('--platform', 'Other Platform')
        argv = list(second['agent_result']['next_command']['gateway_argv'])
        argv[-1] = first['agent_result']['next_command']['gateway_argv'][-1]
    else:
        task.field = 'Unrelated'
    code, rejected = task.run(*argv)
    assert code == 2, rejected
    assert 'agent_result' not in rejected or rejected['agent_result'] is None
    if change in {'session', 'project', 'configuration', 'extra-query'}:
        assert not any(uri.endswith('object.get') and args != {'waql': 'from type Project take 1'}
                       for uri, args, _ in task.calls[before:])
    assert not any(uri.endswith(('setProperty', 'setReference')) for uri, _, _ in task.calls)


@pytest.mark.parametrize('version', VERSIONS)
def test_compact_query_avoids_large_duplicate_and_selected_read_consumes_exact_agent_result(tmp_path, version):
    task = QueryTask(tmp_path, version)
    task.row['notes'] = '声' * 7000
    result = task.first()
    assert result['agent_result'] == [task.row]
    assert 'objects' not in result and result['objects_source'] == 'agent_result'
    assert list(result)[-1] == 'agent_result'
    assert sum(uri.endswith('object.get') for uri, _, _ in task.calls) == 1
    # The ordinary next exact-ID read consumes the canonical result, with no
    # dependency on the intentionally omitted duplicate projection.
    selected = result['agent_result'][0]
    code, readback = task.run('query-object', '--exact-id', selected['id'])
    assert code == 0, readback
    assert {key: readback['agent_result'][0][key] for key in ('id', 'name', 'type', 'path')} == {
        key: selected[key] for key in ('id', 'name', 'type', 'path')}
    assert 'projection_complete' not in readback
    code, schema = task.run('query-schema')
    assert code == 0
    assert 'objects_source=agent_result' in json.dumps(schema)


@pytest.mark.parametrize('version', VERSIONS)
def test_large_identity_is_explicitly_omitted_from_headers_and_never_mutation_candidate(tmp_path, version):
    task = QueryTask(tmp_path, version)
    task.row['name'] = '名前' * 10000
    first = task.first()
    header = first['agent_result']['objects'][0]
    assert 'name' not in header and 'name' in header['projection_omitted_fields']
    assert 'mutation_selection' not in first
    assert first['agent_result']['page']['mutation_authority'] is False
    assert first['agent_result']['projection_complete'] is False


@pytest.mark.parametrize('version', VERSIONS)
def test_windows_query_page_command_is_short_exact_and_context_bound(tmp_path, version, monkeypatch):
    import types
    original = gateway.transaction_next_command
    def windows_command(*args, **kwargs):
        actual = gateway.os
        gateway.os = types.SimpleNamespace(**{**vars(actual), 'name': 'nt'})
        try:
            return original(*args, **kwargs)
        finally:
            gateway.os = actual
    monkeypatch.setattr(gateway, 'transaction_next_command', windows_command)
    task = QueryTask(tmp_path, version)
    first = task.first('--platform', '平台声' * 50, '--language', '語言' * 50)
    command = first['agent_result']['next_command']
    assert len(command['shell_command'].encode('utf-8')) < 8192
    assert '-EncodedCommand' in command['shell_command']
    assert len(json.dumps(first, ensure_ascii=False, indent=2).encode()) <= 32 * 1024
    code, result = task.run(*command['gateway_argv'])
    assert code == 0, result
    reads = [(args, options) for uri, args, options in task.calls if uri.endswith('object.get') and args != {'waql': 'from type Project take 1'}]
    assert reads[0] == reads[1]


@pytest.mark.parametrize('version', VERSIONS)
def test_detail_query_preserves_diagnostics_and_missing_native_identity_without_fabrication(tmp_path, version):
    task = QueryTask(tmp_path, version)
    task.row.pop('type')
    first = task.first('--detail')
    assert 'semantic_preview' in first and 'call' in first
    assert 'native_observation' not in first
    assert 'type' not in first['agent_result']['objects'][0]
    assert 'mutation_selection' not in first
    seen = []
    while True:
        seen.extend(first['agent_result']['entries'])
        if first['agent_result']['projection_complete']:
            break
        code, first = task.run(*first['agent_result']['next_command']['gateway_argv'])
        assert code == 0, first
    assert any(entry['pointer'] == '/objects/0/identity_completeness/complete' and entry.get('value') is False for entry in seen)
    assert not any(entry['pointer'] == '/native_observation/return/0/type' for entry in seen)
    assert ''.join(entry['value'] for entry in seen if entry['pointer'] == '/native_observation/return/0/notes') == task.row['notes']


@pytest.mark.parametrize('version', VERSIONS)
def test_missing_host_session_discloses_partial_read_without_unbound_continuation(tmp_path, version):
    task = QueryTask(tmp_path, version)
    task.info.pop('sessionId')
    first = task.first()
    assert first['status'] == 'partial'
    page = first['agent_result']
    assert 'next_command' not in page
    assert page['page']['continuation_unavailable_reason'] == 'host_session_identity_unavailable'
    assert page['projection_complete'] is False


def test_large_detail_semantic_preview_survives_as_lossless_entries_in_short_windows_pages(tmp_path, monkeypatch):
    import types
    original = gateway.transaction_next_command
    def windows_command(*args, **kwargs):
        actual = gateway.os
        gateway.os = types.SimpleNamespace(**{**vars(actual), 'name': 'nt'})
        try:
            return original(*args, **kwargs)
        finally:
            gateway.os = actual
    monkeypatch.setattr(gateway, 'transaction_next_command', windows_command)
    task = QueryTask(tmp_path)
    term = '声' * 1500
    # Legal bounded closed declaration, not a raw native payload or expression.
    first = task.first('--predicate', 'notes-contain', term, '--detail')
    assert 'semantic_preview' not in first
    assert first['projection_boundary']['semantic_preview_source'] == 'agent_result.entries/semantic_preview'
    entries = []
    while True:
        assert len(json.dumps(first, ensure_ascii=False, indent=2).encode()) <= 32 * 1024
        entries.extend(first['agent_result']['entries'])
        if first['agent_result']['projection_complete']:
            break
        command = first['agent_result']['next_command']
        assert len(command['shell_command'].encode()) < 8192
        code, first = task.run(*command['gateway_argv'])
        assert code == 0, first
    assert any(entry['pointer'].startswith('/semantic_preview') for entry in entries)
    reads = [args for uri, args, _ in task.calls if uri.endswith('object.get')]
    assert all(args == reads[0] for args in reads)
    assert term.replace('"', '\\"') in reads[0]['waql']


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('detail', [False, True])
def test_near_native_transport_limit_keeps_first_query_page_bounded_without_extra_result_reread(tmp_path, version, detail):
    task = QueryTask(tmp_path, version)
    task.row['notes'] = '声' * 330000
    first = task.first(*(['--detail'] if detail else []))
    assert first['status'] == 'partial'
    assert len(json.dumps(first, ensure_ascii=False, indent=2).encode()) <= 32 * 1024
    assert sum(uri.endswith('object.get') and args != {'waql': 'from type Project take 1'} for uri, args, _ in task.calls) == 1
    assert first['agent_result']['projection_complete'] is False


def test_query_plan_capacity_reclaims_expired_records_and_rejects_expired_pages_before_dispatch(tmp_path, monkeypatch):
    import time
    from wwise_waapi.object_query_result_pages import ObjectQueryPlanStore
    task = QueryTask(tmp_path)
    monkeypatch.setattr(ObjectQueryPlanStore, 'MAX_RECORDS', 1)
    first = task.first()
    code, blocked = task.run('query-object', '--exact-id', PROJECT_GUID, '--include', 'notes')
    assert code == 2 and 'capacity' in blocked['message'], blocked
    now = time.time()
    monkeypatch.setattr(time, 'time', lambda: now + 901)
    task.calls.clear()
    code, expired = task.run(*first['agent_result']['next_command']['gateway_argv'])
    assert code == 2 and 'expired' in expired['message'], expired
    assert task.calls == []
    successor = task.first()
    assert successor['status'] == 'partial'
    assert successor['agent_result']['next_command']['gateway_argv'] != first['agent_result']['next_command']['gateway_argv']


def test_wrong_handle_namespace_cannot_read_another_plan(tmp_path):
    task = QueryTask(tmp_path)
    first = task.first()
    argv = first['agent_result']['next_command']['gateway_argv']
    task.calls.clear()
    code, rejected = task.run('query-object', '--result-query', 'mpq1-' + 'a' * 32, '--result-page', argv[-1])
    assert code == 2, rejected
    assert task.calls == []


@pytest.mark.parametrize('version', VERSIONS)
def test_advanced_query_pages_revalidate_original_long_read_and_retain_business_projection(tmp_path, version):
    task = QueryTask(tmp_path, version)
    code, _ = task.run('query-schema', '--advanced')
    assert code == 0
    waql = 'from type Sound where notes : "' + '声' * 9000 + '"'
    code, page = task.run('query-object', '--advanced-waql', waql, '--max-results', '1', '--include', 'notes', '--detail')
    assert code == 0, page
    assert page['status'] == 'partial'
    entries = []
    while True:
        assert len(json.dumps(page, ensure_ascii=False, indent=2).encode()) <= 32 * 1024
        entries.extend(page['agent_result']['entries'])
        if page['agent_result']['projection_complete']:
            break
        argv = page['agent_result']['next_command']['gateway_argv']
        assert len(json.dumps(argv).encode()) < 512
        code, page = task.run(*argv)
        assert code == 0, page
    assert ''.join(entry['value'] for entry in entries if entry['pointer'] == '/objects/0/notes') == task.row['notes']
    assert any(entry['pointer'].startswith('/semantic_preview') for entry in entries)
    reads = [args for uri, args, _ in task.calls if uri.endswith('object.get') and args != {'waql': 'from type Project take 1'}]
    assert all(args == {'waql': waql + ' take 1'} for args in reads)


def test_large_advanced_compilation_keeps_small_ordinary_reply_direct_without_paging_duplicate_diagnostics(tmp_path):
    task = QueryTask(tmp_path)
    task.row['notes'] = 'small'
    code, _ = task.run('query-schema', '--advanced')
    assert code == 0
    waql = 'from type Sound where notes : "' + '声' * 10000 + '"'
    code, result = task.run('query-object', '--advanced-waql', waql, '--max-results', '1', '--include', 'notes')
    assert code == 0, result
    assert result['agent_result'] == [task.row]
    assert 'projection_complete' not in result
    assert not any(uri.endswith('getProjectInfo') for uri, _, _ in task.calls)
    assert sum(uri.endswith('object.get') for uri, _, _ in task.calls) == 1
