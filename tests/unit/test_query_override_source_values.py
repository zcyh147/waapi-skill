"""Closed public property values on the source of override, never runtime values."""
from __future__ import annotations

import pytest

from tests.unit.test_object_query_result_pages import QueryTask, VERSIONS, PROJECT_GUID


@pytest.mark.parametrize('version', VERSIONS)
def test_one_query_preserves_ordinary_and_override_source_value_for_same_property(tmp_path, version):
    task = QueryTask(tmp_path, version)
    task.row.pop('notes')
    task.row.update({'@Volume': -12, '@@Volume': 0})
    code, result = task.run('query-object', '--exact-id', PROJECT_GUID,
        '--include-field', 'Volume', '--include-override-source-value', 'Volume')
    assert code == 0, result
    row = result['agent_result'][0]
    assert row['properties'] == {'Volume': -12}
    assert row['override_source_values'] == {'Volume': 0}
    assert list(result)[-1] == 'agent_result'
    data_reads = [(args, options) for uri, args, options in task.calls if uri.endswith('object.get')]
    assert data_reads == [({'waql': 'from object "' + PROJECT_GUID + '"'},
        {'return': ['id', 'name', 'type', 'path', '@Volume', '@@Volume']})]
    assert {uri for uri, _, _ in task.calls} <= {
        'ak.wwise.core.getInfo', 'ak.wwise.core.object.get',
        'ak.wwise.core.object.getPropertyAndReferenceNames', 'ak.wwise.core.object.getPropertyInfo'}


@pytest.mark.parametrize('version', VERSIONS)
def test_query_schema_discloses_exact_override_source_value_branch(tmp_path, version):
    import json
    import re
    from pathlib import Path
    from tests.unit.test_object_query_result_pages import gateway

    task = QueryTask(tmp_path, version)
    code, schema = task.run('query-schema')
    assert code == 0, schema
    value_source = schema['custom_outputs']['override_source_values']
    assert value_source['option'] == '--include-override-source-value <user-facing property meaning>'
    assert value_source['output_group'] == 'override_source_values'
    assert value_source['same_property_with_ordinary_value'] is True
    assert value_source['meaning'] == 'value of the property for the source of override'
    assert value_source['not_observed'] == ['ancestor identity', 'runtime RTPC or mixed audio result']
    assert value_source['field_kind'] == 'property'
    assert value_source['reference_semantics'] == 'not established by cited property-value documentation'
    assert 'reference_alternative' not in value_source
    source = value_source['native_definition']
    assert source['version'] == version
    assert source['document'] == 'waapi_definitions.json'
    assert source['pointer'] == '/definitions/returnExpression/items/anyOf/1'
    graph = json.loads((Path(gateway.__file__).parents[1] / 'resources/manifest' / version / 'definitions.json').read_text())
    native = graph['documents'][source['document']]['definitions']['returnExpression']['items']['anyOf'][1]
    return_shapes = graph['documents'][source['document']]['definitions']['objectReturn']['patternProperties']
    assert any(re.fullmatch(pattern, '@@Volume') for pattern in return_shapes)
    assert 'double @@ returns the value of the property for the source of override' in native['description']
    assert task.calls == []


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('meaning', ['@Volume', '@@Volume', 'parent.@Volume'])
def test_override_source_value_rejects_accessor_text_before_transport(tmp_path, version, meaning):
    task = QueryTask(tmp_path, version)
    code, rejected = task.run('query-object', '--exact-id', PROJECT_GUID,
        '--include-override-source-value', meaning)
    assert code == 2, rejected
    assert 'user-facing' in rejected['message']
    assert task.calls == []


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('value', [False, 0, None, 'absent'])
def test_override_source_value_preserves_false_zero_null_and_absence(tmp_path, version, value):
    task = QueryTask(tmp_path, version)
    task.row.pop('notes')
    if value is False:
        task.field, task.field_type = 'ContinuePlay', 'bool'
    if value != 'absent':
        task.row['@@' + task.field] = value
    code, result = task.run('query-object', '--exact-id', PROJECT_GUID,
        '--include-override-source-value', task.field)
    assert code == 0, result
    row = result['agent_result'][0]
    if value == 'absent':
        assert 'override_source_values' not in row
        assert row['unavailable_fields'] == ['override_source_values.Volume']
    else:
        assert row['override_source_values'] == {task.field: value}
        assert type(row['override_source_values'][task.field]) is type(value)
        assert 'unavailable_fields' not in row
    assert 'properties' not in row
    assert list(result)[-1] == 'agent_result'


@pytest.mark.parametrize('version', VERSIONS)
def test_ordinary_and_override_source_meanings_share_one_exact_field_without_case_conflict(tmp_path, version):
    task = QueryTask(tmp_path, version)
    task.row.pop('notes')
    task.row.update({'@Volume': -12, '@@Volume': 0})
    code, result = task.run('query-object', '--exact-id', PROJECT_GUID,
        '--include-field', 'volume', '--include-override-source-value', 'Volume')
    assert code == 0, result
    assert result['agent_result'][0]['properties'] == {'Volume': -12}
    assert result['agent_result'][0]['override_source_values'] == {'Volume': 0}


@pytest.mark.parametrize('version', VERSIONS)
def test_override_source_property_contract_does_not_admit_reference_metadata(tmp_path, version):
    import json
    from pathlib import Path
    # Exact Console 2025.1.7.9143 packet shape, simulated over all parsers;
    # this is not five-version native reference evidence.
    fixture = json.loads((Path(__file__).parents[1] / 'fixtures/metadata-conditions/playlist-object-2025.json').read_text())
    assert fixture['provenance']['native_packet_sha256'] == '519aa5006f6b9322443adc9eb33810d542c66e250932833d87293f40a5a660a2'
    class RetainedReference(QueryTask):
        def call(self, uri, args=None, options=None):
            if uri.endswith('getPropertyInfo'):
                self.calls.append((uri, args, options))
                return fixture['metadata']
            return super().call(uri, args, options)
    task = RetainedReference(tmp_path, version)
    task.field = 'PlaylistObject'
    code, rejected = task.run('query-object', '--exact-id', PROJECT_GUID,
        '--include-override-source-value', 'Playlist Object')
    assert code == 2, rejected
    assert 'property-value documentation' in rejected['message']
    assert not any(uri.endswith('object.get') for uri, _, _ in task.calls)
    assert not any('set' in uri for uri, _, _ in task.calls)


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('options', [
    ['--include-override-source-value', 'Volume', '--include-override-source-value', ' volume '],
    ['--include-override-source-value', 'Volume', '--include-override-source-value', 'volume'],
    ['--include-override-source-value', 'Volume;notes'],
    ['--include-override-source-value', ''],
    ['--include-override-source-value', 'Volume', '--relationship', 'children'],
    ['--include-override-source-value', 'Volume', '--view', 'sound-routing-diagnostics'],
])
def test_invalid_override_source_declarations_fail_before_transport(tmp_path, version, options):
    task = QueryTask(tmp_path, version)
    code, rejected = task.run('query-object', '--exact-id', PROJECT_GUID, *options)
    assert code == 2, rejected
    assert task.calls == []


@pytest.mark.parametrize('version', VERSIONS)
def test_advanced_override_source_value_stays_outside_unproven_custom_scope(tmp_path, version):
    task = QueryTask(tmp_path, version)
    code, rejected = task.run('query-object', '--advanced-waql', 'from type Sound', '--max-results', '1',
        '--include-override-source-value', 'Volume')
    assert code == 2, rejected
    assert 'live metadata scope' in rejected['message']
    assert task.calls == []


@pytest.mark.parametrize('version', VERSIONS)
def test_duplicate_exact_override_source_field_aliases_do_not_dispatch_data(tmp_path, version):
    class Aliases(QueryTask):
        def call(self, uri, args=None, options=None):
            if uri.endswith('getPropertyInfo'):
                self.calls.append((uri, args, options))
                return {'name': 'Volume', 'type': 'Real32', 'display': {'name': 'Level'}}
            return super().call(uri, args, options)
    task = Aliases(tmp_path, version)
    code, rejected = task.run('query-object', '--exact-id', PROJECT_GUID,
        '--include-override-source-value', 'Volume', '--include-override-source-value', 'Level')
    assert code == 2, rejected
    assert 'duplicate result fields' in rejected['message']
    assert not any(uri.endswith('object.get') for uri, _, _ in task.calls)


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('change', ['inventory', 'metadata'])
def test_override_source_continuations_revalidate_exact_field_selection(tmp_path, version, change):
    task = QueryTask(tmp_path, version)
    task.row.update({'@Volume': -12, '@@Volume': 0})
    result = task.first('--include-field', 'Volume', '--include-override-source-value', 'Volume')
    assert result['status'] == 'partial', result
    argv = result['agent_result']['next_command']['gateway_argv']
    if change == 'metadata':
        task.field_type = 'Real64'
    else:
        task.field = 'Unrelated'
    code, rejected = task.run(*argv)
    assert code == 2 and rejected['error_code'] == 'QUERY_RESULT_CONTINUATION_CHANGED', rejected
    assert rejected.get('agent_result') is None
    assert not any(uri.endswith(('setProperty', 'setReference')) for uri, _, _ in task.calls)


@pytest.mark.parametrize('version', VERSIONS)
def test_large_override_source_value_pages_preserve_both_modes_and_original_scope(tmp_path, version):
    task = QueryTask(tmp_path, version)
    task.field = 'Text'
    task.field_type = 'string'
    task.row.pop('notes')
    text = '音声' * 12000
    task.row.update({'@Text': '', '@@Text': text})
    code, result = task.run('query-object', '--exact-id', PROJECT_GUID,
        '--include-field', 'Text', '--include-override-source-value', 'Text',
        '--platform', 'Mac', '--language', 'SFX')
    assert code == 0 and result['status'] == 'partial', result
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
        if entry['pointer'] == '/objects/0/override_source_values/Text') == text
    assert [entry['value'] for entry in entries if entry['pointer'] == '/objects/0/properties/Text'] == ['']
    data_options = [options for uri, args, options in task.calls
        if uri.endswith('object.get') and args != {'waql': 'from type Project take 1'}]
    assert data_options and all(options == {
        'return': ['id', 'name', 'type', 'path', '@Text', '@@Text'], 'platform': 'Mac', 'language': 'SFX'}
        for options in data_options)
