"""Closed enum-backed Blend Track discovery through the public query Gateway."""
from __future__ import annotations

import pytest

from tests.unit.test_object_query_result_pages import QueryTask, PROJECT_GUID

SUPPORTED = ('2024.1', '2025.1')
OLDER = ('2021.1', '2022.1', '2023.1')
TRACKS = [
    {'id': '{8D76C40F-1C73-42C7-9A26-8C0E56E6898F}', 'name': 'On-Load'},
    {'id': '{8650F5F9-E62B-4394-8729-1FF0C63A0681}', 'name': 'Off-Load'},
]


@pytest.mark.parametrize('version', SUPPORTED)
def test_blend_track_list_preserves_exact_native_order_and_reference_extensions(tmp_path, version):
    task = QueryTask(tmp_path, version)
    task.row.pop('notes')
    tracks = [dict(TRACKS[1], future={'enabled': False, 'value': 0}), dict(TRACKS[0])]
    task.row.update(type='BlendContainer', blendTracks=tracks)
    code, result = task.run('query-object', '--exact-id', PROJECT_GUID, '--include', 'blend-tracks')
    assert code == 0, result
    assert result['agent_result'][0]['blend_tracks'] == tracks
    assert list(result)[-1] == 'agent_result'
    assert task.calls[-1] == ('ak.wwise.core.object.get',
        {'waql': 'from object "' + PROJECT_GUID + '"'},
        {'return': ['id', 'name', 'type', 'path', 'blendTracks']})
    assert {uri for uri, _, _ in task.calls} == {'ak.wwise.core.getInfo', 'ak.wwise.core.object.get'}


@pytest.mark.parametrize('version', (*OLDER, *SUPPORTED))
def test_blend_tracks_disclosure_uses_native_enum_and_result_pattern_without_specific_shape(tmp_path, version):
    import json
    import re
    from pathlib import Path
    from tests.unit.test_object_query_result_pages import gateway

    task = QueryTask(tmp_path, version)
    code, schema = task.run('query-schema', '--output', 'blend-tracks')
    assert code == 0, schema
    output = schema['business_output']
    assert output['supported_versions'] == list(SUPPORTED)
    assert output['available'] is (version in SUPPORTED)
    assert output['native_absence_proven'] is False
    if version in OLDER:
        assert output['native_definition'] is None
        assert output['result_schema'] is None
        assert 'matching returnExpression' in output['availability_reason']
        assert 'not advertised' in output['availability_reason']
        code, rejected = task.run('query-object', '--exact-id', PROJECT_GUID, '--include', 'blend-tracks')
        assert code == 2, rejected
        assert 'matching returnExpression' in rejected['message']
    else:
        graph = json.loads((Path(gateway.__file__).parents[1] / 'resources/manifest' / version / 'definitions.json').read_text())
        source = output['native_definition']
        assert source['version'] == version and source['wwise_build'] == graph['wwise_build']
        assert source['document'] == 'waapi_definitions.json'
        assert source['pointer'].startswith('/definitions/returnExpression/items/anyOf/0/enum/')
        native = graph['documents'][source['document']]
        for part in source['pointer'].split('/')[1:]:
            native = native[int(part)] if isinstance(native, list) else native[part]
        assert native == 'blendTracks'
        matching = [(pattern, value) for pattern, value in graph['documents'][source['document']]['definitions']['objectReturn']['patternProperties'].items()
            if re.fullmatch(pattern, 'blendTracks')]
        assert len(matching) == 1
        assert output['result_schema'] == matching[0][1]
        assert output['specific_result_shape_proven'] is False
        assert output['result_schema_source']['pointer'].startswith('/definitions/objectReturn/patternProperties/')
        assert output['result_shape']['anyOf']
        assert 'type' not in output['result_shape'] and 'required' not in output['result_shape']
        assert output['meaning_source']['uri'] == 'ak.wwise.core.blendContainer.addTrack'
        assert 'list of Blend Tracks' in output['meaning_source']['description']
    assert task.calls == []


@pytest.mark.parametrize('version', (*OLDER, *SUPPORTED))
def test_override_source_no_match_guidance_preserves_mode_during_refinement(tmp_path, version):
    task = QueryTask(tmp_path, version)
    task.row.pop('notes')
    task.row['@@Volume'] = 0
    code, clarification = task.run('query-object', '--exact-id', PROJECT_GUID,
        '--include-override-source-value', 'unfindable meaning')
    assert code == 0 and clarification['status'] == 'needs_clarification', clarification
    advice = clarification['agent_result']
    assert '--include-override-source-value' in advice['repair']
    assert '--include-field' not in advice['repair']
    assert advice['unresolved'][0]['requested_options'] == ['--include-override-source-value']
    assert not any(uri.endswith('object.get') for uri, _, _ in task.calls)
    code, refined = task.run('query-object', '--exact-id', PROJECT_GUID,
        '--include-override-source-value', 'Volume')
    assert code == 0, refined
    assert refined['agent_result'][0]['override_source_values'] == {'Volume': 0}
    assert 'properties' not in refined['agent_result'][0]
    assert task.calls[-1][2]['return'] == ['id', 'name', 'type', 'path', '@@Volume']


@pytest.mark.parametrize('version', SUPPORTED)
@pytest.mark.parametrize('presence', ['empty', 'null', 'absent'])
def test_blend_tracks_preserves_empty_null_and_unavailable_results(tmp_path, version, presence):
    task = QueryTask(tmp_path, version)
    task.row.pop('notes')
    if presence != 'absent':
        task.row['blendTracks'] = [] if presence == 'empty' else None
    code, result = task.run('query-object', '--exact-id', PROJECT_GUID, '--include', 'blend-tracks')
    assert code == 0, result
    row = result['agent_result'][0]
    if presence == 'absent':
        assert 'blend_tracks' not in row
        assert row['unavailable_fields'] == ['blend_tracks']
    else:
        assert row['blend_tracks'] == ([] if presence == 'empty' else None)
        assert 'unavailable_fields' not in row
    assert list(result)[-1] == 'agent_result'


@pytest.mark.parametrize('version', SUPPORTED)
def test_blend_tracks_composes_with_advanced_query_fixed_projection(tmp_path, version):
    task = QueryTask(tmp_path, version)
    task.row.pop('notes')
    task.row['blendTracks'] = TRACKS
    code, result = task.run('query-object', '--advanced-waql', 'from object "' + PROJECT_GUID + '"',
        '--max-results', '1', '--include', 'blend-tracks')
    assert code == 0, result
    assert result['agent_result'][0]['blend_tracks'] == TRACKS
    assert task.calls[-1] == ('ak.wwise.core.object.get',
        {'waql': 'from object "' + PROJECT_GUID + '" take 1'},
        {'return': ['id', 'name', 'type', 'path', 'blendTracks']})


@pytest.mark.parametrize('version', SUPPORTED)
def test_duplicate_blend_track_declarations_reject_before_transport(tmp_path, version):
    task = QueryTask(tmp_path, version)
    code, rejected = task.run('query-object', '--exact-id', PROJECT_GUID,
        '--include', 'blend-tracks', '--include', 'blend-tracks')
    assert code == 2, rejected
    assert task.calls == []


@pytest.mark.parametrize('version', SUPPORTED)
@pytest.mark.parametrize('change', [False, True])
def test_large_blend_track_reference_value_pages_bind_exact_order_and_native_extensions(tmp_path, version, change):
    import json

    task = QueryTask(tmp_path, version)
    task.row.pop('notes')
    text = '音声' * 12000
    task.row['blendTracks'] = [dict(TRACKS[1], future=text), dict(TRACKS[0])]
    code, result = task.run('query-object', '--exact-id', PROJECT_GUID, '--include', 'blend-tracks')
    assert code == 0 and result['status'] == 'partial', result
    argv = result['agent_result']['next_command']['gateway_argv']
    if change:
        task.row['blendTracks'].reverse()
        code, rejected = task.run(*argv)
        assert code == 2 and rejected['error_code'] == 'QUERY_RESULT_CONTINUATION_CHANGED', rejected
        assert rejected.get('agent_result') is None
    else:
        entries = []
        while True:
            assert list(result)[-1] == 'agent_result'
            assert len(json.dumps(result, ensure_ascii=False, indent=2).encode()) <= 32 * 1024
            page = result['agent_result']
            entries.extend(page['entries'])
            if page['projection_complete']:
                break
            code, result = task.run(*page['next_command']['gateway_argv'])
            assert code == 0, result
        assert ''.join(entry['value'] for entry in entries
            if entry['pointer'] == '/objects/0/blend_tracks/0/future') == text
        assert [entry['value'] for entry in entries if entry['pointer'] == '/objects/0/blend_tracks/0/name'] == ['Off-Load']
        assert [entry['value'] for entry in entries if entry['pointer'] == '/objects/0/blend_tracks/1/name'] == ['On-Load']
    data_options = [options for uri, args, options in task.calls
        if uri.endswith('object.get') and args != {'waql': 'from type Project take 1'}]
    assert data_options and all(options == {'return': ['id', 'name', 'type', 'path', 'blendTracks']} for options in data_options)
    assert not any(uri.endswith(('setProperty', 'setReference')) for uri, _, _ in task.calls)


@pytest.mark.parametrize('version', (*OLDER, *SUPPORTED))
@pytest.mark.parametrize('mode', ['ordinary', 'both'])
def test_unresolved_field_guidance_preserves_each_requested_value_mode(tmp_path, version, mode):
    task = QueryTask(tmp_path, version)
    options = ['--include-field', 'unfindable meaning']
    expected = ['--include-field']
    if mode == 'both':
        options.extend(['--include-override-source-value', 'unfindable meaning'])
        expected.append('--include-override-source-value')
    code, result = task.run('query-object', '--exact-id', PROJECT_GUID, *options)
    assert code == 0 and result['status'] == 'needs_clarification', result
    advice = result['agent_result']
    assert advice['unresolved'][0]['requested_options'] == expected
    assert all(option in advice['repair'] for option in expected)
    if mode == 'ordinary':
        assert '--include-override-source-value' not in advice['repair']
    assert not any(uri.endswith('object.get') for uri, _, _ in task.calls)


def test_native_enum_names_do_not_become_arbitrary_public_outputs():
    from tests.unit.test_object_query_result_pages import gateway

    for native in ('blendTracks', 'suppportsRandomizer', 'sound:arbitraryFilePath'):
        with pytest.raises(SystemExit):
            gateway.build_parser().parse_args(['query-object', '--exact-id', PROJECT_GUID, '--include', native])
