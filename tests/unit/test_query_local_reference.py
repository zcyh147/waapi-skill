"""Metadata-bound local references coexist with existing resolved reference reads."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tests.unit.test_object_query_result_pages import QueryTask, VERSIONS, PROJECT_GUID

PACKET = Path(__file__).parents[1] / 'fixtures/metadata-conditions/playlist-object-2025.json'
LOCAL = {'id': '{8D76C40F-1C73-42C7-9A26-8C0E56E6898F}', 'name': 'Local'}
RESOLVED = {'id': '{8650F5F9-E62B-4394-8729-1FF0C63A0681}', 'name': 'Resolved'}


class ReferenceTask(QueryTask):
    def __init__(self, tmp_path, version):
        super().__init__(tmp_path, version)
        fixture = json.loads(PACKET.read_text())
        assert fixture['provenance']['native_packet_sha256'] == '519aa5006f6b9322443adc9eb33810d542c66e250932833d87293f40a5a660a2'
        # Exact native 2025 metadata, simulated over all parsers; no native
        # cross-version or override-effect credit comes from these fake rows.
        self.reference_metadata = fixture['metadata']
        self.field = 'PlaylistObject'
        self.available_fields = [self.field]
        self.row.pop('notes')
        self.row.update(type='PluginInnerObject', name='', path='[PlaylistSlot: (First)]')

    def call(self, uri, args=None, options=None):
        if uri.endswith('getPropertyInfo'):
            self.calls.append((uri, args, options))
            return copy.deepcopy(self.reference_metadata)
        if uri.endswith('getPropertyAndReferenceNames'):
            self.calls.append((uri, args, options))
            return {'return': list(self.available_fields)}
        return super().call(uri, args, options)


@pytest.mark.parametrize('version', VERSIONS)
def test_same_reference_returns_distinct_local_and_resolved_values_without_alias_input(tmp_path, version):
    task = ReferenceTask(tmp_path, version)
    local = {**LOCAL, 'future': {'enabled': False, 'value': 0}}
    task.row.update({'PlaylistObject': RESOLVED, '@PlaylistObject': local})
    code, result = task.run('query-object', '--exact-id', PROJECT_GUID,
        '--include-field', 'Playlist Object', '--include-local-reference', 'Playlist Object')
    assert code == 0, result
    row = result['agent_result'][0]
    assert row['references'] == {'PlaylistObject': RESOLVED}
    assert row['local_references'] == {'PlaylistObject': local}
    assert 'properties' not in row and 'override_source_values' not in row
    assert list(result)[-1] == 'agent_result'
    assert task.calls[-1] == ('ak.wwise.core.object.get',
        {'waql': 'from object "' + PROJECT_GUID + '"'},
        {'return': ['id', 'name', 'type', 'path', 'PlaylistObject', '@PlaylistObject']})
    assert {uri for uri, _, _ in task.calls} <= {
        'ak.wwise.core.getInfo', 'ak.wwise.core.object.get',
        'ak.wwise.core.object.getPropertyAndReferenceNames', 'ak.wwise.core.object.getPropertyInfo'}


@pytest.mark.parametrize('version', VERSIONS)
def test_offline_schema_pins_real_sdk_reference_semantics_and_version(tmp_path, version):
    import hashlib
    from tests.unit.test_object_query_result_pages import gateway
    task = ReferenceTask(tmp_path, version)
    code, result = task.run('query-schema')
    assert code == 0, result
    contract = result['custom_outputs']['local_references']
    assert contract['field_kind'] == 'reference'
    assert contract['output_group'] == 'local_references'
    assert contract['ordinary_reference']['meaning'] == 'override-resolved reference'
    assert contract['ordinary_reference']['native_equivalence'] == 'no prefix is equivalent to @@'
    source = contract['source']
    expected = {
        '2021.1': ('2021.1.14.8108', '48b12b73e1d25a4cdf878b69e51e3e89a5ded1bf7297b5e8b72a5846a6bdf62d'),
        '2022.1': ('2022.1.19.8584', '00e9476b76a5909eb9636b65fdc68213db8f7d35e44fbfb0b271f8997fb9bbc7'),
        '2023.1': ('2023.1.19.8928', 'd5c71af4c4cfd0d229668e7892ba3eaa990abc2962f7a3b657607f7830041fce'),
        '2024.1': ('2024.1.13.9056', '5165140438af177a0953465bd88f85b9d43e97cdccd5fbd8d610e7047a48bafb'),
        '2025.1': ('2025.1.7.9143', 'c50dd24ce42b502a0368fa4be8a6e081cc4435fa8ce9b5a8f1d447e01c45a3f6'),
    }
    assert (source['wwise_build'], source['page_sha256']) == expected[version]
    assert source['version'] == version and source['page'] == 'waapi_query.html'
    assert source['section'] == 'waapi_query_return'
    section_file = Path(gateway.__file__).parents[1] / 'references/semantic' / version / source['retained_section']
    section = ''.join(json.loads(section_file.read_text())).encode('utf-8')
    expected_section_hash = ('3583812afef304f9943995c69043c84c6f816ddf65d1a78b6943c027aaec11ab'
        if version in {'2021.1', '2022.1'} else 'db6c9de2d19a23e03d9d00d467bbddd31f792a631c20b57356f8ed782d5a60bf')
    assert hashlib.sha256(section).hexdigest() == source['retained_section_sha256'] == expected_section_hash
    assert b'@OutputBus' in section and b'@@OutputBus' in section
    assert b'Work Unit' in section and b'Override Parent' in section
    assert b'When no prefix is used' in section
    assert b'This is the equivalent of using the @@ prefix' in section
    assert task.calls == []


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('value', [None, 'absent', {}, [], [RESOLVED, LOCAL]])
def test_local_reference_preserves_null_absence_empty_and_ordered_native_values(tmp_path, version, value):
    task = ReferenceTask(tmp_path, version)
    if value != 'absent':
        task.row['@PlaylistObject'] = value
    code, result = task.run('query-object', '--exact-id', PROJECT_GUID,
        '--include-local-reference', 'Playlist Object')
    assert code == 0, result
    row = result['agent_result'][0]
    if value == 'absent':
        assert 'local_references' not in row
        assert row['unavailable_fields'] == ['local_references.PlaylistObject']
    else:
        assert row['local_references'] == {'PlaylistObject': value}
        assert 'unavailable_fields' not in row
    assert list(result)[-1] == 'agent_result'


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('options', [
    ['--include-local-reference', '@OutputBus'],
    ['--include-local-reference', '@@OutputBus'],
    ['--include-local-reference', 'parent.@OutputBus'],
    ['--include-local-reference', ''],
    ['--include-local-reference', ' Output Bus'],
    ['--include-local-reference', 'Output Bus;name'],
    ['--include-local-reference', 'Output Bus', '--include-local-reference', 'output bus'],
    ['--include-local-reference', 'Output Bus', '--view', 'sound-routing-diagnostics'],
    ['--include-local-reference', 'Output Bus', '--relationship', 'children'],
    ['--include-local-reference', 'Output Bus', '--advanced-waql', 'from type Sound', '--max-results', '2'],
    [*sum((['--include-field', f'Field {i}'] for i in range(15)), []),
        '--include-override-source-value', 'Field 16', '--include-local-reference', 'Field 17'],
])
def test_invalid_local_reference_declarations_fail_before_transport(tmp_path, version, options):
    task = ReferenceTask(tmp_path, version)
    source = [] if '--advanced-waql' in options else ['--exact-id', PROJECT_GUID]
    code, rejected = task.run('query-object', *source, *options)
    assert code == 2, rejected
    assert task.calls == []


@pytest.mark.parametrize('version', VERSIONS)
def test_local_reference_rejects_property_metadata_before_data_read(tmp_path, version):
    task = QueryTask(tmp_path, version)
    code, rejected = task.run('query-object', '--exact-id', PROJECT_GUID,
        '--include-local-reference', 'Volume')
    assert code == 2, rejected
    assert 'reference' in rejected['message']
    assert not any(uri.endswith('object.get') for uri, _, _ in task.calls)


@pytest.mark.parametrize('version', VERSIONS)
def test_unresolved_local_mode_is_retained_on_refinement_and_aliases_are_rejected(tmp_path, version):
    task = ReferenceTask(tmp_path, version)
    code, result = task.run('query-object', '--exact-id', PROJECT_GUID,
        '--include-field', 'unfindable', '--include-local-reference', 'unfindable')
    assert code == 0 and result['status'] == 'needs_clarification', result
    assert result['agent_result']['unresolved'][0]['requested_options'] == ['--include-field', '--include-local-reference']
    assert '--include-local-reference' in result['agent_result']['repair']
    assert not any(uri.endswith('object.get') for uri, _, _ in task.calls)
    task.row.update({'PlaylistObject': RESOLVED, '@PlaylistObject': LOCAL})
    code, result = task.run('query-object', '--exact-id', PROJECT_GUID,
        '--include-field', 'playlist object', '--include-local-reference', 'Playlist Object')
    assert code == 0, result
    assert result['agent_result'][0]['local_references'] == {'PlaylistObject': LOCAL}
    task.calls.clear()
    code, rejected = task.run('query-object', '--exact-id', PROJECT_GUID,
        '--include-local-reference', 'PlaylistObject', '--include-local-reference', 'Playlist Object')
    assert code == 2, rejected
    assert 'duplicate result fields' in rejected['message']
    assert not any(uri.endswith('object.get') for uri, _, _ in task.calls)


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('change', ['none', 'result', 'metadata', 'inventory'])
def test_local_reference_pages_preserve_values_and_revalidate_exact_metadata(tmp_path, version, change):
    task = ReferenceTask(tmp_path, version)
    text = '音声' * 12000
    task.row.update({'PlaylistObject': RESOLVED, '@PlaylistObject': {**LOCAL, 'future': text}})
    code, result = task.run('query-object', '--exact-id', PROJECT_GUID,
        '--include-field', 'Playlist Object', '--include-local-reference', 'Playlist Object',
        '--platform', 'Mac', '--language', 'SFX')
    assert code == 0 and result['status'] == 'partial', result
    argv = result['agent_result']['next_command']['gateway_argv']
    if change != 'none':
        if change == 'result':
            task.row['@PlaylistObject']['future'] += '!'
        elif change == 'metadata':
            task.reference_metadata['display']['name'] = 'Changed Reference Label'
        else:
            task.available_fields = []
        code, rejected = task.run(*argv)
        assert code == 2 and rejected['error_code'] == 'QUERY_RESULT_CONTINUATION_CHANGED', rejected
        assert rejected.get('agent_result') is None
        return
    entries = []
    while True:
        assert list(result)[-1] == 'agent_result'
        page = result['agent_result']
        entries.extend(page['entries'])
        if page['projection_complete']:
            break
        code, result = task.run(*page['next_command']['gateway_argv'])
        assert code == 0, result
    assert ''.join(entry['value'] for entry in entries
        if entry['pointer'] == '/objects/0/local_references/PlaylistObject/future') == text
    assert [entry['value'] for entry in entries
        if entry['pointer'] == '/objects/0/references/PlaylistObject/id'] == [RESOLVED['id']]
    data_options = [options for uri, args, options in task.calls
        if uri.endswith('object.get') and args != {'waql': 'from type Project take 1'}]
    assert data_options and all(options == {'return': ['id', 'name', 'type', 'path', 'PlaylistObject', '@PlaylistObject'],
        'platform': 'Mac', 'language': 'SFX'} for options in data_options)
