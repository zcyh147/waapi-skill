"""Metadata-bound namespaced scalar outputs through the public Gateway."""
import copy

import pytest

from tests.unit.test_object_query_result_pages import QueryTask, VERSIONS, PROJECT_GUID
from tests.unit.test_query_namespaced_conditions import NamespacedTask, TOKEN, METADATA
from tests.unit.test_query_related_paths import PathTask, REFERENCE_CLASS, REFERENCE_PACKET, SOUND, OTHER, PARENT, SOUND_CLASS


@pytest.mark.parametrize('version', VERSIONS)
def test_singleton_namespaced_property_outputs_keep_ordinary_and_override_values(tmp_path, version):
    task = PathTask(tmp_path, version)
    task.rows = task.rows[:1]
    task.metadata[REFERENCE_CLASS][TOKEN] = copy.deepcopy(METADATA)
    task.row.update({'parent.@' + TOKEN: 0, 'parent.@@' + TOKEN: 2})
    code, result = task.run('query-object', '--exact-id', SOUND,
        '--include-related-field', 'parent', TOKEN,
        '--include-related-override-source-value', 'parent', TOKEN, '--detail')
    assert code == 0, result
    parent = result['agent_result'][0]['related']['parent']
    assert parent['object'] == PARENT
    assert parent['properties'] == {TOKEN: 0}
    assert parent['override_source_values'] == {TOKEN: 2}
    assert any({'parent.@' + TOKEN, 'parent.@@' + TOKEN} <= set(options['return'])
        for uri, args, options in task.calls if uri.endswith('object.get'))
    assert any(uri.endswith('getPropertyInfo') and args == {'classId': REFERENCE_CLASS, 'property': TOKEN}
        for uri, args, _ in task.calls)
    assert list(result)[-1] == 'agent_result'


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('path,expected', [
    (['children'], [SOUND, OTHER]),
    (['children', 'first'], [SOUND]),
    (['combine', 'children', 'and', 'children', 'end', 'take', '2'], [SOUND, OTHER]),
])
def test_namespaced_collection_terminals_preserve_selected_members_and_value_modes(tmp_path, version, path, expected):
    task = NamespacedTask(tmp_path, version)
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2',
        '--include-related-field', *path, TOKEN,
        '--include-related-override-source-value', *path, TOKEN)
    assert code == 0, result
    related = result['agent_result'][0]['related']
    view = related['children'] if path == ['children'] else related['projections'][0]
    assert [item['object']['id'] for item in view['items']] == expected
    assert [item['properties'][TOKEN] for item in view['items']] == [0, 1][:len(expected)]
    assert [item['override_source_values'][TOKEN] for item in view['items']] == [1, 0][:len(expected)]
    assert list(result)[-1] == 'agent_result'


@pytest.mark.parametrize('version', VERSIONS)
def test_root_namespaced_output_modes_keep_existing_metadata_bound_behavior(tmp_path, version):
    task = QueryTask(tmp_path, version)
    task.field, task.field_type = TOKEN, 'int16'
    task.row.pop('notes')
    task.row.update({'@' + TOKEN: 0, '@@' + TOKEN: 2})
    code, result = task.run('query-object', '--exact-id', PROJECT_GUID,
        '--include-field', TOKEN, '--include-override-source-value', TOKEN)
    assert code == 0, result
    assert result['agent_result'][0]['properties'] == {TOKEN: 0}
    assert result['agent_result'][0]['override_source_values'] == {TOKEN: 2}


def terminal_task(tmp_path, version, layout):
    if layout == 'singleton':
        task = PathTask(tmp_path, version)
        task.rows = task.rows[:1]
        task.metadata[REFERENCE_CLASS][TOKEN] = copy.deepcopy(METADATA)
        task.row['parent.@' + TOKEN] = 0
        return task, REFERENCE_CLASS, PARENT['id'], ['parent']
    task = NamespacedTask(tmp_path, version)
    task.rows = task.rows[:1]
    task.rows[0]['children'] = [task.reference(SOUND)]
    return task, SOUND_CLASS, SOUND, ['children']


def terminal_items(result, layout):
    related = result['agent_result'][0]['related']
    return [related['parent']] if layout == 'singleton' else related['children']['items']


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('layout', ['singleton', 'list'])
def test_unknown_class_kind_uses_fresh_actual_object_property_for_namespaced_output(tmp_path, version, layout):
    task, scope, identity, path = terminal_task(tmp_path, version, layout)
    task.metadata[scope][TOKEN].update(type='', restriction={})
    task.metadata[identity] = {TOKEN: copy.deepcopy(METADATA)}
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--include-related-field', *path, TOKEN, '--detail')
    assert code == 0, result
    assert terminal_items(result, layout)[0]['properties'] == {TOKEN: 0}
    assert any(selection['scope'] == {'object': identity} and selection['selected']['name'] == TOKEN
        for selection in result['related_scope_binding']['scopes'])


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('layout', ['singleton', 'list'])
def test_namespaced_output_ambiguity_requires_exact_token_and_refreshes_each_invocation(tmp_path, version, layout):
    task, scope, identity, path = terminal_task(tmp_path, version, layout)
    other = 'OtherCompany:Status'
    task.metadata[scope][other] = {**copy.deepcopy(METADATA), 'name': other}
    flags = ['query-object', '--kind', 'all-sounds', '--max-results', '1', '--include-related-field', *path]
    code, result = task.run(*flags, 'Status')
    assert code == 0 and result['status'] == 'needs_clarification', result
    code, result = task.run(*flags, TOKEN)
    assert code == 0 and terminal_items(result, layout)[0]['properties'] == {TOKEN: 0}, result
    task.metadata[scope] = {}
    task.metadata[identity] = {}
    before = len(task.calls)
    code, result = task.run(*flags, TOKEN)
    assert code == 0 and result['status'] == 'needs_clarification', result
    assert any(uri.endswith('getPropertyAndReferenceNames') for uri, _, _ in task.calls[before:])


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('layout', ['singleton', 'list'])
@pytest.mark.parametrize('use', ['reference-terminal', 'reference-hop', 'local-reference-terminal'])
def test_namespaced_property_terminal_permission_does_not_expand_reference_grammar(tmp_path, version, layout, use):
    task, scope, identity, path = terminal_task(tmp_path, version, layout)
    if use != 'local-reference-terminal':
        task.metadata[scope][TOKEN] = {**copy.deepcopy(REFERENCE_PACKET['metadata']), 'name': TOKEN}
    flags = (['--include-related', *path, 'reference', TOKEN, 'volume-db'] if use == 'reference-hop'
        else ['--include-related-local-reference' if use == 'local-reference-terminal' else '--include-related-field', *path, TOKEN])
    if use == 'local-reference-terminal':
        flags = ['--include-related-field', *path, TOKEN, *flags]
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1', *flags)
    assert code == 2 and result['error_code'] == 'RELATED_QUERY_FIELD_TOKEN', result
    assert result.get('agent_result') is None


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('layout', ['singleton', 'list'])
@pytest.mark.parametrize('token', ['MyCompany::Status', 'MyCompany:Status.foo', 'MyCompany:Status) where true', 'MyCompany:Stаtus'])
def test_unsafe_discovered_output_tokens_do_not_receive_namespaced_permission(tmp_path, version, layout, token):
    task, scope, identity, path = terminal_task(tmp_path, version, layout)
    task.metadata[scope].pop(TOKEN)
    task.metadata[scope][token] = {**copy.deepcopy(METADATA), 'name': token}
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--include-related-field', *path, 'Status')
    assert code == 2 and result['error_code'] == 'RELATED_QUERY_FIELD_TOKEN', result
    assert result.get('agent_result') is None


@pytest.mark.parametrize('layout', ['singleton', 'list'])
@pytest.mark.parametrize('presence', ['absent', 'null', 'false'])
def test_namespaced_terminal_values_keep_existing_presence_semantics(tmp_path, layout, presence):
    task, scope, identity, path = terminal_task(tmp_path, '2025.1', layout)
    row, field = (task.row, 'parent.@' + TOKEN) if layout == 'singleton' else (task.members[SOUND], '@' + TOKEN)
    if presence == 'absent': row.pop(field)
    else: row[field] = None if presence == 'null' else False
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--include-related-field', *path, TOKEN)
    assert code == 0, result
    item = terminal_items(result, layout)[0]
    if presence == 'absent':
        assert item['unavailable_fields'] == ['properties.' + TOKEN]
        assert 'properties' not in item
    else:
        assert item['properties'][TOKEN] is (None if presence == 'null' else False)


@pytest.mark.parametrize('layout', ['singleton', 'list'])
@pytest.mark.parametrize('change', ['none', 'metadata', 'value'])
def test_namespaced_terminal_pages_keep_actual_scope_and_value_seals(tmp_path, layout, change):
    task, scope, identity, path = terminal_task(tmp_path, '2025.1', layout)
    row = task.row if layout == 'singleton' else task.rows[0]
    row['notes'] = '音声' * 16000
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--include', 'notes', '--include-related-field', *path, TOKEN)
    assert code == 0 and result['status'] == 'partial', result
    if change == 'metadata': task.metadata[scope][TOKEN]['type'] = 'int32'
    elif change == 'value':
        target, field = (task.row, 'parent.@' + TOKEN) if layout == 'singleton' else (task.members[SOUND], '@' + TOKEN)
        target[field] = 2
    code, continued = task.run(*result['agent_result']['next_command']['gateway_argv'])
    if change == 'none': assert code == 0 and continued['status'] == 'partial', continued
    else: assert code == 2 and continued['error_code'] == 'QUERY_RESULT_CONTINUATION_CHANGED', continued


@pytest.mark.parametrize('version', VERSIONS)
def test_namespaced_matching_condition_and_terminal_share_actual_property_scope(tmp_path, version):
    task = NamespacedTask(tmp_path, version)
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2',
        '--include-related-field', 'children', 'matching-field', 'ordinary', TOKEN, 'is', '0', TOKEN,
        '--include-related-override-source-value', 'children', 'matching-field', 'ordinary', TOKEN, 'is', '0', TOKEN)
    assert code == 0, result
    for root in result['agent_result']:
        projection, = root['related']['projections']
        assert [item['object']['id'] for item in projection['items']] == [SOUND]
        assert projection['items'][0]['properties'] == {TOKEN: 0}
        assert projection['items'][0]['override_source_values'] == {TOKEN: 1}
