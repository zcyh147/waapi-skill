"""Closed singleton paths and actual-scope metadata through the public Gateway."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tests.unit.test_query_related_outputs import RelatedTask, SOUND, OTHER, PARENT, OTHER_PARENT
from tests.unit.test_object_query_result_pages import VERSIONS

REFERENCE_PACKET = json.loads((Path(__file__).parents[1] / 'fixtures/metadata-conditions/playlist-object-2025.json').read_text())
REFERENCE_CLASS = REFERENCE_PACKET['identity_model']['classId']
SOUND_CLASS = 65552  # Existing reflected Sound class fixture, not a guessed WAQL type code.
TARGET = {'id': '{8D76C40F-1C73-42C7-9A26-8C0E56E6898F}', 'name': 'Resolved'}
LOCAL = {'id': '{8650F5F9-E62B-4394-8729-1FF0C63A0681}', 'name': 'Local'}


class PathTask(RelatedTask):
    def __init__(self, tmp_path, version='2025.1'):
        super().__init__(tmp_path, version)
        assert REFERENCE_PACKET['provenance']['native_packet_sha256'] == '519aa5006f6b9322443adc9eb33810d542c66e250932833d87293f40a5a660a2'
        self.metadata = {
            REFERENCE_CLASS: {'PlaylistObject': copy.deepcopy(REFERENCE_PACKET['metadata'])},
            SOUND_CLASS: {'Pitch': {'name': 'Pitch', 'type': 'int32', 'display': {'name': 'Pitch'}}},
        }
        for row in self.rows:
            row.update(classId=SOUND_CLASS)
        self.rows[0].update({'parent': PARENT, 'parent.classId': REFERENCE_CLASS,
            'parent.parent': OTHER_PARENT, 'parent.parent.classId': SOUND_CLASS, 'parent.parent.@Volume': -12,
            'parent.PlaylistObject': TARGET, 'parent.@PlaylistObject': LOCAL,
            'parent.PlaylistObject.classId': SOUND_CLASS,
            'parent.PlaylistObject.@Volume': -2, 'parent.PlaylistObject.@Pitch': -560})
        self.rows[1].update({'parent': OTHER_PARENT, 'parent.classId': REFERENCE_CLASS,
            'parent.parent': PARENT, 'parent.parent.classId': SOUND_CLASS, 'parent.parent.@Volume': 0,
            'parent.PlaylistObject': LOCAL, 'parent.@PlaylistObject': TARGET,
            'parent.PlaylistObject.classId': SOUND_CLASS,
            'parent.PlaylistObject.@Volume': 0, 'parent.PlaylistObject.@Pitch': 0})

    def call(self, uri, args=None, options=None):
        if uri.endswith('object.get') and args != {'waql': 'from type Project take 1'}:
            self.calls.append((uri, args, options))
            return {'return': [{field: copy.deepcopy(row[field]) for field in options['return'] if field in row} for row in self.rows]}
        if uri.endswith(('getPropertyAndReferenceNames', 'getPropertyInfo')):
            self.calls.append((uri, args, options))
            scope = args.get('classId', args.get('object'))
            fields = self.metadata[scope]
            return ({'return': list(fields)} if uri.endswith('getPropertyAndReferenceNames')
                else copy.deepcopy(fields[args['property']]))
        return super().call(uri, args, options)


def flow_options():
    return ['--include-related', 'parent', 'parent', 'volume-db',
        '--include-related-field', 'parent', 'Playlist Object',
        '--include-related-local-reference', 'parent', 'Playlist Object',
        '--include-related', 'parent', 'reference', 'Playlist Object', 'volume-db',
        '--include-related-field', 'parent', 'reference', 'Playlist Object', 'Pitch']


def test_closed_broad_flow_keeps_roots_and_binds_each_hop_to_actual_related_class(tmp_path):
    task = PathTask(tmp_path)
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2', *flow_options())
    assert code == 0, result
    rows = result['agent_result']
    assert [row['id'] for row in rows] == [SOUND, OTHER]
    first = rows[0]['related']['parent']
    assert first['object'] == PARENT
    assert first['related']['parent']['volume_db'] == -12
    assert first['references'] == {'PlaylistObject': TARGET}
    assert first['local_references'] == {'PlaylistObject': LOCAL}
    target = first['related']['references']['PlaylistObject']
    assert target == {'object': TARGET, 'volume_db': -2, 'properties': {'Pitch': -560}}
    assert rows[1]['related']['parent']['related']['references']['PlaylistObject']['properties']['Pitch'] == 0
    names = [args for uri, args, _ in task.calls if uri.endswith('getPropertyAndReferenceNames')]
    assert names == [{'classId': REFERENCE_CLASS}, {'classId': SOUND_CLASS}]
    infos = [args for uri, args, _ in task.calls if uri.endswith('getPropertyInfo')]
    assert infos == [{'classId': REFERENCE_CLASS, 'property': 'PlaylistObject'}, {'classId': SOUND_CLASS, 'property': 'Pitch'}]
    assert {uri for uri, _, _ in task.calls} <= {'ak.wwise.core.getInfo', 'ak.wwise.core.object.get',
        'ak.wwise.core.object.getPropertyAndReferenceNames', 'ak.wwise.core.object.getPropertyInfo'}
    assert list(result)[-1] == 'agent_result'


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('source', ['broad', 'advanced', 'exact'])
def test_related_modes_and_multihop_share_fresh_scope_and_preserve_return_context(tmp_path, version, source):
    task = PathTask(tmp_path, version)
    source_args = {'broad': ['--kind', 'all-sounds', '--max-results', '2'],
        'advanced': ['--advanced-waql', 'from type Sound orderby name', '--max-results', '2'],
        'exact': ['--exact-id', SOUND]}[source]
    if source == 'exact':
        task.rows = task.rows[:1]
    code, result = task.run('query-object', *source_args, *flow_options(), '--platform', 'Mac', '--language', 'SFX', '--detail')
    assert code == 0, result
    assert result['agent_result'][0]['related']['parent']['related']['parent']['volume_db'] == -12
    assert result['related_scope_binding']['mutation_authority'] is False
    assert {entry['scope']['classId'] for entry in result['related_scope_binding']['scopes']} == {REFERENCE_CLASS, SOUND_CLASS}
    assert all(options['platform'] == 'Mac' and options['language'] == 'SFX'
        for uri, args, options in task.calls if uri.endswith('object.get'))
    reads = [args for uri, args, _ in task.calls if uri.endswith('object.get')]
    assert all(args == reads[0] for args in reads)
    assert list(result)[-1] == 'agent_result'


@pytest.mark.parametrize('version', VERSIONS)
def test_multihop_fixed_path_does_not_overwrite_reference_terminal_or_discover_metadata(tmp_path, version):
    task = PathTask(tmp_path, version)
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2',
        '--include-related', 'parent', 'parent', '--include-related', 'parent', 'parent', 'volume-db')
    assert code == 0, result
    parent = result['agent_result'][0]['related']['parent']
    assert parent == {'object': PARENT, 'parent': OTHER_PARENT,
        'related': {'parent': {'object': OTHER_PARENT, 'volume_db': -12}}}
    assert len([uri for uri, _, _ in task.calls if uri.endswith('object.get')]) == 1
    assert not any('Property' in uri for uri, _, _ in task.calls)


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('case', ['empty-roots', 'absent-parent', 'null-parent', 'absent-field', 'null-field', 'false-field'])
def test_empty_or_unavailable_related_data_preserves_roots_without_invented_metadata_authority(tmp_path, version, case):
    task = PathTask(tmp_path, version)
    task.rows = task.rows[:1]
    task.row['parent.@Pitch'] = -560
    task.metadata[REFERENCE_CLASS] = {'Pitch': {'name': 'Pitch', 'type': 'int32'}}
    if case == 'empty-roots':
        task.rows = []
    elif case == 'absent-parent':
        task.row.pop('parent')
    elif case == 'null-parent':
        task.row['parent'] = None
    elif case == 'absent-field':
        task.row.pop('parent.@Pitch')
    else:
        task.row['parent.@Pitch'] = None if case == 'null-field' else False
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2',
        '--include-related-field', 'parent', 'Pitch')
    assert code == 0 and result['status'] == 'ok', result
    if case == 'empty-roots':
        assert result['agent_result'] == []
    else:
        parent = result['agent_result'][0]['related']['parent']
        if case == 'absent-field':
            assert parent['unavailable_fields'] == ['properties.Pitch']
        elif case.endswith('field'):
            assert parent['properties']['Pitch'] is (None if case == 'null-field' else False)
        elif case == 'null-parent':
            assert parent['object'] is None
        else:
            assert 'object' not in parent
    if case in {'empty-roots', 'absent-parent', 'null-parent'}:
        assert not any('Property' in uri for uri, _, _ in task.calls)
    assert list(result)[-1] == 'agent_result'


@pytest.mark.parametrize('version', VERSIONS)
def test_different_actual_classes_bind_only_their_own_tokens_or_explicit_unavailable_request(tmp_path, version):
    task = PathTask(tmp_path, version)
    task.rows[1]['parent.classId'] = SOUND_CLASS
    task.metadata[REFERENCE_CLASS] = {'Pitch': {'name': 'Pitch', 'type': 'int32'}}
    task.metadata[SOUND_CLASS] = {}
    task.metadata[OTHER_PARENT['id']] = {}
    task.rows[0]['parent.@Pitch'] = -560
    # A token supplied by native data on the other class is not metadata authority.
    task.rows[1]['parent.@Pitch'] = 999
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2',
        '--include-related-field', 'parent', 'Pitch')
    assert code == 0 and result['status'] == 'ok', result
    assert result['agent_result'][0]['related']['parent']['properties'] == {'Pitch': -560}
    second = result['agent_result'][1]['related']['parent']
    assert second['object'] == OTHER_PARENT and 'properties' not in second
    assert second['unavailable_field_requests'][0]['meaning'] == 'Pitch'
    assert second['unavailable_field_requests'][0]['requested_option'] == '--include-related-field'


@pytest.mark.parametrize('version', VERSIONS)
def test_custom_related_modes_keep_local_override_and_reference_extensions_distinct(tmp_path, version):
    task = PathTask(tmp_path, version)
    task.rows = task.rows[:1]
    task.metadata[REFERENCE_CLASS]['Pitch'] = {'name': 'Pitch', 'type': 'int32'}
    task.row.update({'parent.@Pitch': 0, 'parent.@@Pitch': -560,
        'parent.PlaylistObject': {**TARGET, 'extension': {'enabled': False, 'value': 0}}})
    code, result = task.run('query-object', '--exact-id', SOUND,
        '--include-related-field', 'parent', 'Pitch',
        '--include-related-override-source-value', 'parent', 'Pitch',
        '--include-related-field', 'parent', 'Playlist Object',
        '--include-related-local-reference', 'parent', 'Playlist Object')
    assert code == 0, result
    parent = result['agent_result'][0]['related']['parent']
    assert parent['properties'] == {'Pitch': 0}
    assert parent['override_source_values'] == {'Pitch': -560}
    assert parent['references']['PlaylistObject'] == {**TARGET, 'extension': {'enabled': False, 'value': 0}}
    assert parent['local_references'] == {'PlaylistObject': LOCAL}
    assert 'related_scope_binding' not in result


@pytest.mark.parametrize('version', VERSIONS)
def test_instance_specific_field_uses_exact_actual_guid_when_class_metadata_cannot_bind(tmp_path, version):
    task = PathTask(tmp_path, version)
    task.rows = task.rows[:1]
    task.metadata[REFERENCE_CLASS] = {}
    task.metadata[PARENT['id']] = {'Pitch': {'name': 'Pitch', 'type': 'int32'}}
    task.row['parent.@Pitch'] = -560
    code, result = task.run('query-object', '--exact-id', SOUND,
        '--include-related-field', 'parent', 'Pitch', '--detail')
    assert code == 0 and result['status'] == 'ok', result
    assert result['agent_result'][0]['related']['parent']['properties'] == {'Pitch': -560}
    assert result['related_scope_binding']['scopes'][0]['scope'] == {'object': PARENT['id']}
    names = [args for uri, args, _ in task.calls if uri.endswith('getPropertyAndReferenceNames')]
    assert names == [{'classId': REFERENCE_CLASS}, {'object': PARENT['id']}]


@pytest.mark.parametrize('version', VERSIONS)
def test_missing_reference_hop_on_one_complete_scope_keeps_that_root_without_borrowed_token(tmp_path, version):
    task = PathTask(tmp_path, version)
    task.rows[1]['parent.classId'] = SOUND_CLASS
    task.metadata[SOUND_CLASS] = {}
    task.metadata[OTHER_PARENT['id']] = {}
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2',
        '--include-related', 'parent', 'reference', 'Playlist Object', 'volume-db')
    assert code == 0 and result['status'] == 'ok', result
    assert len(result['agent_result']) == 2
    first, second = [row['related']['parent'] for row in result['agent_result']]
    assert first['related']['references']['PlaylistObject']['volume_db'] == -2
    assert 'related' not in second
    assert second['unavailable_field_requests'][0]['requested_option'] == 'reference'


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('failure', ['ambiguous', 'no-match', 'partial-no-match', 'wrong-property-kind', 'wrong-reference-kind', 'duplicate-alias'])
def test_scoped_binding_never_guesses_or_dispatches_final_values_when_declaration_is_unresolved(tmp_path, version, failure):
    task = PathTask(tmp_path, version)
    task.rows = task.rows[:1]
    option, meaning = '--include-related-field', 'Pitch'
    task.metadata[PARENT['id']] = {}
    if failure == 'ambiguous':
        task.metadata[REFERENCE_CLASS] = {name: {'name': name, 'type': 'int32', 'display': {'name': 'Pitch'}} for name in ['PitchA', 'PitchB']}
    elif failure == 'partial-no-match':
        task.metadata[REFERENCE_CLASS] = {f'Field{index}': {'name': f'Field{index}', 'type': 'int32'} for index in range(300)}
    elif failure == 'no-match':
        task.metadata[REFERENCE_CLASS] = {}
    elif failure == 'wrong-property-kind':
        option, meaning = '--include-related-local-reference', 'Pitch'
        task.metadata[REFERENCE_CLASS] = {'Pitch': {'name': 'Pitch', 'type': 'int32'}}
    else:
        meaning = 'Playlist Object'
        if failure == 'wrong-reference-kind':
            option = '--include-related-override-source-value'
    options = [option, 'parent', meaning]
    if failure == 'duplicate-alias':
        options.extend([option, 'parent', 'PlaylistObject'])
    code, result = task.run('query-object', '--exact-id', SOUND, *options)
    if failure in {'ambiguous', 'no-match', 'partial-no-match'}:
        assert code == 0 and result['status'] == 'needs_clarification', result
        unresolved = result['agent_result']['unresolved'][0]
        assert unresolved['option'] == option and unresolved['meaning'] == meaning
        assert unresolved['scope'] in [{'classId': REFERENCE_CLASS}, {'object': PARENT['id']}]
        assert unresolved['complete'] is (failure != 'partial-no-match')
    else:
        assert code == 2, result
        assert result['error_code'] == ('RELATED_QUERY_DUPLICATE_FIELD' if failure == 'duplicate-alias' else 'RELATED_QUERY_FIELD_KIND')
    if failure in {'ambiguous', 'partial-no-match', 'wrong-property-kind', 'wrong-reference-kind'}:
        assert [args for uri, args, _ in task.calls if uri.endswith('getPropertyAndReferenceNames')] == [{'classId': REFERENCE_CLASS}]
    data_reads = [options for uri, _, options in task.calls if uri.endswith('object.get')]
    assert all('parent.@Pitch' not in options['return'] and 'parent.PlaylistObject' not in options['return'] for options in data_reads)
    assert not any(uri.endswith(('setProperty', 'setReference')) for uri, _, _ in task.calls)


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('options', [
    ['--include-related-field', 'parent', '@Pitch'],
    ['--include-related-field', 'parent', 'Pitch.function()'],
    ['--include-related-field', 'parent.parent', 'Pitch'],
    ['--include-related', 'parent', 'reference', 'volume-db'],
    ['--include-related-local-reference', 'parent', 'OutputBus', '--include-related-local-reference', 'parent', 'OutputBus'],
])
def test_path_and_field_grammar_rejects_raw_accessors_and_duplicate_declarations_offline(tmp_path, version, options):
    task = PathTask(tmp_path, version)
    code, result = task.run('query-object', '--exact-id', SOUND, *options)
    assert code == 2, result
    assert task.calls == []


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('change', ['none', 'metadata', 'inventory', 'class', 'prefix', 'root-order', 'kind'])
def test_related_pages_repeat_same_bounded_query_and_seal_scope_metadata_and_membership(tmp_path, version, change):
    task = PathTask(tmp_path, version)
    task.metadata[REFERENCE_CLASS]['Pitch'] = {'name': 'Pitch', 'type': 'int32'}
    text = '音声' * 12000
    for row in task.rows:
        row['parent.@Pitch'] = -560
        row['parent.notes'] = text
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2',
        '--include-related-field', 'parent', 'Pitch', '--include-related', 'parent', 'notes')
    assert code == 0 and result['status'] == 'partial', result
    argv = result['agent_result']['next_command']['gateway_argv']
    if change == 'metadata':
        task.metadata[REFERENCE_CLASS]['Pitch']['type'] = 'Real64'
    elif change == 'inventory':
        task.metadata[REFERENCE_CLASS]['Other'] = {'name': 'Other', 'type': 'int32'}
    elif change == 'class':
        task.rows[0]['parent.classId'] = SOUND_CLASS
    elif change == 'prefix':
        task.rows[0]['parent'] = OTHER_PARENT
    elif change == 'root-order':
        task.rows.reverse()
    elif change == 'kind':
        task.metadata[REFERENCE_CLASS]['Pitch'] = {**REFERENCE_PACKET['metadata'], 'name': 'Pitch'}
    if change != 'none':
        code, rejected = task.run(*argv)
        assert code == 2 and rejected['error_code'] == 'QUERY_RESULT_CONTINUATION_CHANGED', rejected
        assert rejected.get('agent_result') is None
        return
    entries = []
    while True:
        page = result['agent_result']
        entries.extend(page['entries'])
        assert list(result)[-1] == 'agent_result'
        if page['projection_complete']:
            break
        code, result = task.run(*page['next_command']['gateway_argv'])
        assert code == 0, result
    assert ''.join(entry['value'] for entry in entries if entry['pointer'] == '/objects/0/related/parent/notes') == text
    assert [entry['value'] for entry in entries if entry['pointer'] == '/objects/0/related/parent/properties/Pitch'] == [-560]
    names = [args for uri, args, _ in task.calls if uri.endswith('getPropertyAndReferenceNames')]
    assert len(names) > 1  # Invocation-local cache, never stale persisted metadata.


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('change', ['root-order', 'prefix', 'class', 'list'])
def test_preparation_cannot_attach_values_to_changed_or_list_related_scope(tmp_path, version, change):
    class ChangingTask(PathTask):
        count = 0
        def call(self, uri, args=None, options=None):
            if uri.endswith('object.get') and args != {'waql': 'from type Project take 1'}:
                self.count += 1
                if self.count == 2:
                    if change == 'root-order':
                        self.rows.reverse()
                    elif change == 'prefix':
                        self.rows[0]['parent'] = OTHER_PARENT
                    elif change == 'class':
                        self.rows[0]['parent.classId'] = SOUND_CLASS
                    else:
                        self.rows[0]['parent.PlaylistObject'] = [TARGET, LOCAL]
            return super().call(uri, args, options)
    task = ChangingTask(tmp_path, version)
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2', *flow_options())
    assert code == 2, result
    assert result['error_code'] == ('RELATED_QUERY_RESULT_SHAPE' if change == 'list' else 'RELATED_QUERY_SCOPE_CHANGED')
    assert result.get('agent_result') is None


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('bound', ['return-count', 'expression-bytes', 'custom-total', 'fixed-total'])
def test_related_projection_uses_existing_caps_including_all_identity_scope_helpers(tmp_path, version, bound):
    from tests.unit.test_object_query_result_pages import gateway
    from wwise_waapi.builders.query import MAX_ADVANCED_RETURN_EXPRESSIONS, MAX_ADVANCED_RETURN_EXPRESSION_BYTES
    task = PathTask(tmp_path, version)
    if bound == 'custom-total':
        options = ['--include-related-field', 'parent', 'Pitch'] * gateway.MAX_QUERY_CUSTOM_OUTPUTS + ['--include-field', 'Volume']
    elif bound == 'fixed-total':
        options = ['--include-related', 'parent', 'volume-db'] * gateway.MAX_QUERY_BUSINESS_OUTPUTS + ['--include', 'notes']
    else:
        # A single declaration can exceed the native projection, independently
        # of the number of user-requested terminal outputs.
        count = MAX_ADVANCED_RETURN_EXPRESSIONS if bound == 'return-count' else MAX_ADVANCED_RETURN_EXPRESSION_BYTES // len('parent.') + 1
        options = ['--include-related', *(['parent'] * count), 'volume-db']
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2', *options)
    assert code == 2, result
    assert task.calls == []


@pytest.mark.parametrize('version', VERSIONS)
def test_related_schema_exposes_same_source_proven_closed_modes_paths_and_limits_offline(tmp_path, version):
    import hashlib
    from tests.unit.test_object_query_result_pages import gateway
    task = PathTask(tmp_path, version)
    code, result = task.run('query-schema')
    assert code == 0, result
    contract = result['related_outputs']
    assert contract['custom_terminal_options'] == ['--include-related-field', '--include-related-override-source-value', '--include-related-local-reference']
    assert contract['native_limits'] == {'return_expressions_including_helpers': 64, 'each_expression_utf8_bytes': 4096}
    root = Path(gateway.__file__).parents[1]
    source = json.loads((root / 'references/semantic' / version / 'query-reference-value-sources.json').read_text())
    section_path = root / 'references/semantic' / version / source['retained_section']
    section = ''.join(json.loads(section_path.read_text()))
    assert hashlib.sha256(section.encode()).hexdigest() == source['retained_section_sha256']
    assert 'parent.parent.type' in section and 'OutputBus.Volume' in section and 'UserAuxSend0.Attenuation' in section
    assert 'reference' in source['semantics']['resolved_reference'] and '@@' in source['semantics']['resolved_reference']
    assert contract['field_value_source_evidence']['page_sha256'] == source['page_sha256']
    assert 'list compositions' in contract['followup']
    assert task.calls == []


@pytest.mark.parametrize('version', VERSIONS)
def test_local_reference_hop_is_distinct_from_resolved_hop_and_preserves_null(tmp_path, version):
    task = PathTask(tmp_path, version)
    task.rows = task.rows[:1]
    task.row.update({'parent.@PlaylistObject.classId': SOUND_CLASS,
        'parent.@PlaylistObject.@Pitch': None})
    code, result = task.run('query-object', '--exact-id', SOUND,
        '--include-related-field', 'parent', 'local-reference', 'Playlist Object', 'Pitch',
        '--include-related-field', 'parent', 'reference', 'Playlist Object', 'Pitch')
    assert code == 0, result
    contexts = result['agent_result'][0]['related']['parent']['related']
    assert contexts['local_references']['PlaylistObject'] == {'object': LOCAL, 'properties': {'Pitch': None}}
    assert contexts['references']['PlaylistObject'] == {'object': TARGET, 'properties': {'Pitch': -560}}


def test_detail_scope_proof_uses_existing_lossless_pages_when_native_reference_extensions_are_large(tmp_path):
    task = PathTask(tmp_path)
    task.rows = task.rows[:1]
    extension = '声' * 24000
    task.row['parent'] = {**PARENT, 'extension': extension}
    task.row['parent.@Pitch'] = -560
    task.metadata[REFERENCE_CLASS] = {'Pitch': {'name': 'Pitch', 'type': 'int32'}}
    code, result = task.run('query-object', '--exact-id', SOUND, '--include-related-field', 'parent', 'Pitch', '--detail')
    assert code == 0 and result['status'] == 'partial', result
    while True:
        assert len(json.dumps(result, ensure_ascii=False, indent=2).encode()) <= 32 * 1024
        assert list(result)[-1] == 'agent_result'
        page = result['agent_result']
        if page['projection_complete']:
            break
        code, result = task.run(*page['next_command']['gateway_argv'])
        assert code == 0, result


@pytest.mark.parametrize('version', VERSIONS)
def test_heterogeneous_scopes_bind_different_tokens_without_projection_leakage(tmp_path, version):
    task = PathTask(tmp_path, version)
    task.rows[1]['parent.classId'] = SOUND_CLASS
    task.metadata[REFERENCE_CLASS] = {'Pitch': {'name': 'Pitch', 'type': 'int32', 'display': {'name': 'Level'}}}
    task.metadata[SOUND_CLASS] = {'Volume': {'name': 'Volume', 'type': 'Real32', 'display': {'name': 'Level'}}}
    task.rows[0].update({'parent.@Pitch': -560, 'parent.@Volume': 999})
    task.rows[1].update({'parent.@Pitch': 999, 'parent.@Volume': 0})
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2',
        '--include-related-field', 'parent', 'Level')
    assert code == 0, result
    assert [row['related']['parent']['properties'] for row in result['agent_result']] == [{'Pitch': -560}, {'Volume': 0}]
    fields = task.calls[-1][2]['return']
    assert 'parent.@Pitch' in fields and 'parent.@Volume' in fields


@pytest.mark.parametrize('version', VERSIONS)
def test_reference_hop_can_begin_at_each_root_and_preserves_duplicate_occurrences(tmp_path, version):
    task = PathTask(tmp_path, version)
    task.metadata[SOUND_CLASS]['PlaylistObject'] = copy.deepcopy(REFERENCE_PACKET['metadata'])
    for row in task.rows:
        row.update({'id': SOUND, 'PlaylistObject': TARGET, 'PlaylistObject.classId': SOUND_CLASS,
            'PlaylistObject.@Pitch': -560})
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2',
        '--include-related-field', 'reference', 'Playlist Object', 'Pitch')
    assert code == 0, result
    assert [row['id'] for row in result['agent_result']] == [SOUND, SOUND]
    assert [row['related']['references']['PlaylistObject'] for row in result['agent_result']] == [
        {'object': TARGET, 'properties': {'Pitch': -560}}] * 2
    assert len([uri for uri, _, _ in task.calls if uri.endswith('getPropertyAndReferenceNames')]) == 1


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('case', ['missing-class', 'unexpressible-token', 'missing-root-id'])
def test_related_scope_fallback_and_unresolvable_identity_or_token_are_explicit(tmp_path, version, case):
    task = PathTask(tmp_path, version)
    task.rows = task.rows[:1]
    task.metadata[PARENT['id']] = {'Pitch': {'name': 'Pitch', 'type': 'int32'}}
    task.row['parent.@Pitch'] = -560
    if case == 'missing-class':
        task.row.pop('parent.classId')
    elif case == 'missing-root-id':
        task.row.pop('id')
    else:
        task.metadata[REFERENCE_CLASS] = {'Pitch.foo': {'name': 'Pitch.foo', 'type': 'int32', 'display': {'name': 'Pitch'}}}
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2',
        '--include-related-field', 'parent', 'Pitch', '--detail')
    if case == 'missing-class':
        assert code == 0, result
        assert result['related_scope_binding']['scopes'][0]['scope'] == {'object': PARENT['id']}
        assert result['agent_result'][0]['related']['parent']['properties'] == {'Pitch': -560}
    else:
        assert code == 2, result
        assert result['error_code'] == ('RELATED_QUERY_IDENTITY_INCOMPLETE' if case == 'missing-root-id' else 'RELATED_QUERY_FIELD_TOKEN')
        assert result.get('agent_result') is None


@pytest.mark.parametrize('version', VERSIONS)
def test_fixed_projection_presence_does_not_change_when_other_path_requires_metadata(tmp_path, version):
    task = PathTask(tmp_path, version)
    task.rows = task.rows[:1]
    task.row.pop('parent')
    task.row.update({'parent.@Volume': 0, 'owner': OTHER_PARENT, 'owner.classId': SOUND_CLASS, 'owner.@Pitch': -560})
    code, result = task.run('query-object', '--exact-id', SOUND,
        '--include-related', 'parent', 'volume-db', '--include-related-field', 'owner', 'Pitch')
    assert code == 0, result
    parent = result['agent_result'][0]['related']['parent']
    assert parent['volume_db'] == 0
    assert 'object' not in parent and parent['unavailable_fields'] == ['object']
    assert parent['identity_completeness']['mutation_authority'] is False
    assert result['agent_result'][0]['related']['owner']['properties'] == {'Pitch': -560}


@pytest.mark.parametrize('version', VERSIONS)
def test_continuation_field_kind_change_is_a_continuation_boundary_not_a_new_request_error(tmp_path, version):
    task = PathTask(tmp_path, version)
    task.rows = task.rows[:1]
    task.row['parent.notes'] = '音声' * 12000
    code, result = task.run('query-object', '--exact-id', SOUND,
        '--include-related', 'parent', 'notes', '--include-related-local-reference', 'parent', 'Playlist Object')
    assert code == 0 and result['status'] == 'partial', result
    task.metadata[REFERENCE_CLASS]['PlaylistObject'] = {'name': 'PlaylistObject', 'type': 'int32', 'display': {'name': 'Playlist Object'}}
    code, rejected = task.run(*result['agent_result']['next_command']['gateway_argv'])
    assert code == 2 and rejected['error_code'] == 'QUERY_RESULT_CONTINUATION_CHANGED', rejected
    assert rejected.get('agent_result') is None


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('drift', ['class-bool', 'class-float', 'extension-bool'])
def test_related_scope_revalidation_rejects_typed_drift_even_when_python_values_compare_equal(tmp_path, version, drift):
    class TypedDriftTask(PathTask):
        reads = 0
        def call(self, uri, args=None, options=None):
            if uri.endswith('object.get') and args != {'waql': 'from type Project take 1'}:
                self.reads += 1
                if self.reads == 2:
                    if drift == 'class-bool':
                        self.row['parent.classId'] = True
                    elif drift == 'class-float':
                        self.row['parent.classId'] = float(REFERENCE_CLASS)
                    else:
                        self.row['parent']['extension']['enabled'] = 0
            return super().call(uri, args, options)
    task = TypedDriftTask(tmp_path, version)
    task.rows = task.rows[:1]
    if drift == 'class-bool':
        task.row['parent.classId'] = 1
        task.metadata[1] = {'Pitch': {'name': 'Pitch', 'type': 'int32'}}
    else:
        task.metadata[REFERENCE_CLASS] = {'Pitch': {'name': 'Pitch', 'type': 'int32'}}
    task.row['parent'] = {**PARENT, 'extension': {'enabled': False}}
    task.row['parent.@Pitch'] = -560
    code, rejected = task.run('query-object', '--exact-id', SOUND, '--include-related-field', 'parent', 'Pitch')
    assert code == 2 and rejected['error_code'] == 'RELATED_QUERY_SCOPE_CHANGED', rejected
    assert rejected.get('agent_result') is None


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('slot', ['identity', 'fixed-reference', 'custom-reference'])
def test_projection_preserves_native_related_extensions_and_does_not_mutate_transport_result(tmp_path, version, slot):
    class RetainedResultTask(PathTask):
        native_result = None
        def call(self, uri, args=None, options=None):
            result = super().call(uri, args, options)
            if uri.endswith('object.get') and args != {'waql': 'from type Project take 1'}:
                self.native_result = result
            return result
    task = RetainedResultTask(tmp_path, version)
    task.rows = task.rows[:1]
    extension = {'related': {}, 'nested': {'related': {}, 'amount': 0}, 'list': [{'related': {}, 'enabled': False}]}
    native = {**TARGET, **copy.deepcopy(extension)}
    if slot == 'identity':
        native = {**PARENT, **copy.deepcopy(extension)}
        task.row['parent'] = native
        options = ['--include-related', 'parent', 'volume-db']
        field, output = 'parent', 'object'
    elif slot == 'fixed-reference':
        task.row['parent.OutputBus'] = native
        options = ['--include-related', 'parent', 'output-bus']
        field, output = 'parent.OutputBus', 'output_bus'
    else:
        task.row['parent.PlaylistObject'] = native
        options = ['--include-related-field', 'parent', 'Playlist Object']
        field, output = 'parent.PlaylistObject', None
    code, result = task.run('query-object', '--exact-id', SOUND, *options)
    assert code == 0, result
    parent = result['agent_result'][0]['related']['parent']
    actual = parent[output] if output else parent['references']['PlaylistObject']
    assert actual == native
    assert task.native_result['return'][0][field] == native
    assert 'related' not in parent  # No empty Gateway-owned child namespace.
    assert list(result)[-1] == 'agent_result'


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('route', ['ordinary', 'local-reference', 'reference-hop'])
def test_unknown_class_kind_uses_exact_endpoint_metadata_without_inventing_action_instance_typing(tmp_path, version, route):
    # Real class-unknown packets exist for 2021–2023. The two later lanes are
    # fake public controls of that same valid metadata shape, not native credit.
    samples = json.loads((Path(__file__).parents[1] / 'fixtures/metadata-conditions/action-target-class-unknown.json').read_text())['samples']
    assert {key: value['source_sha256'] for key, value in samples.items()} == {
        '2021.1': '6be8fcda9b186e704b74aa479abab0273e4f66edc2f2dce10d71dbc774ca0df4',
        '2022.1': '85779fd6872354b2759ec6fd6148e6b5445a7abfdad1a9b34bc0b7c31cb7f7d2',
        '2023.1': 'f3f47350ac5cfc84f153e4b151682102628c1001eb62dad8273a563b7d03f362'}
    sample = samples.get(version, samples['2023.1'])
    assert sample['metadata']['name'] == 'Target' and sample['metadata']['type'] == '' and sample['metadata']['restriction'] == {}
    task = PathTask(tmp_path, version)
    task.rows = task.rows[:1]
    class_id = sample['scope']['resolved']['classId']
    task.row['parent.classId'] = class_id
    task.metadata[class_id] = {'Target': copy.deepcopy(sample['metadata'])}
    # Exact-object positive kind uses the unmodified R62 PlaylistObject packet.
    # This does NOT assert that an actual Action.Target instance is reference-typed.
    task.metadata[PARENT['id']] = {'PlaylistObject': copy.deepcopy(REFERENCE_PACKET['metadata'])}
    options = {
        'ordinary': ['--include-related-field', 'parent', 'Target object'],
        'local-reference': ['--include-related-local-reference', 'parent', 'Target object'],
        'reference-hop': ['--include-related', 'parent', 'reference', 'Target object', 'volume-db'],
    }[route]
    code, result = task.run('query-object', '--exact-id', SOUND, *options, '--detail')
    assert code == 0 and result['status'] == 'ok', result
    parent = result['agent_result'][0]['related']['parent']
    if route == 'ordinary':
        assert parent['references'] == {'PlaylistObject': TARGET}
    elif route == 'local-reference':
        assert parent['local_references'] == {'PlaylistObject': LOCAL}
    else:
        assert parent['related']['references']['PlaylistObject'] == {'object': TARGET, 'volume_db': -2}
    selected = result['related_scope_binding']['scopes'][0]
    assert selected['scope'] == {'object': PARENT['id']}
    assert selected['selected'] == {'name': 'PlaylistObject', 'kind': 'reference'}
    assert [args for uri, args, _ in task.calls if uri.endswith('getPropertyAndReferenceNames')] == [
        {'classId': class_id}, {'object': PARENT['id']}]
