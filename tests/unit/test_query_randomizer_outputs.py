"""Property-bound randomizer values through the closed public query Gateway."""
import copy

import pytest

from tests.unit.test_object_query_result_pages import VERSIONS
from tests.unit.test_query_related_paths import PathTask, SOUND, OTHER, SOUND_CLASS, REFERENCE_CLASS, REFERENCE_PACKET
from tests.unit.test_query_namespaced_conditions import NamespacedTask


@pytest.mark.parametrize('version', VERSIONS)
def test_root_randomizer_keeps_owner_and_distinguishes_disabled_zero_offsets(tmp_path, version):
    task = PathTask(tmp_path, version)
    task.rows = task.rows[:1]
    task.row.update({'randomizer("Pitch").@Enabled': False,
        'randomizer("Pitch").@Min': 0, 'randomizer("Pitch").@Max': 200.0})
    code, result = task.run('query-object', '--exact-id', SOUND,
        '--include-related', 'randomizer', 'Pitch', 'enabled',
        '--include-related', 'randomizer', 'Pitch', 'min-offset',
        '--include-related', 'randomizer', 'Pitch', 'max-offset')
    assert code == 0, result
    row, = result['agent_result']
    assert row['id'] == SOUND
    assert row['related']['randomizers']['Pitch'] == {'enabled': False, 'min_offset': 0, 'max_offset': 200.0}
    assert list(result)[-1] == 'agent_result'


@pytest.mark.parametrize('version', VERSIONS)
def test_related_randomizer_binds_parent_property_without_modifier_identity(tmp_path, version):
    task = PathTask(tmp_path, version)
    task.rows = task.rows[:1]
    task.metadata[REFERENCE_CLASS]['Pitch'] = copy.deepcopy(task.metadata[SOUND_CLASS]['Pitch'])
    task.row.update({'parent.randomizer("Pitch").@Min': -200.0, 'parent.randomizer("Pitch").@Max': 200.0})
    code, result = task.run('query-object', '--exact-id', SOUND,
        '--include-related', 'parent', 'randomizer', 'Pitch', 'min-offset',
        '--include-related', 'parent', 'randomizer', 'Pitch', 'max-offset')
    assert code == 0, result
    parent = result['agent_result'][0]['related']['parent']
    assert parent['related']['randomizers']['Pitch'] == {'min_offset': -200.0, 'max_offset': 200.0}
    assert parent['object']['id'] != SOUND


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('path,expected', [
    (['children'], [SOUND, OTHER]),
    (['children', 'first'], [SOUND]),
    (['combine', 'children', 'and', 'children', 'end', 'take', '3'], [SOUND, OTHER, SOUND]),
])
def test_member_randomizers_keep_owner_order_and_selected_occurrences(tmp_path, version, path, expected):
    task = NamespacedTask(tmp_path, version)
    task.members[SOUND].update({'randomizer("Pitch").@Enabled': False, 'randomizer("Pitch").@Min': -200})
    task.members[OTHER].update({'randomizer("Pitch").@Enabled': True, 'randomizer("Pitch").@Min': 0})
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2',
        '--include-related', *path, 'randomizer', 'Pitch', 'enabled',
        '--include-related', *path, 'randomizer', 'Pitch', 'min-offset')
    assert code == 0, result
    related = result['agent_result'][0]['related']
    view = related['children'] if path == ['children'] else related['projections'][0]
    assert [item['object']['id'] for item in view['items']] == expected
    assert [item['related']['randomizers']['Pitch'] for item in view['items']] == [
        {'enabled': identity == OTHER, 'min_offset': 0 if identity == OTHER else -200} for identity in expected]


@pytest.mark.parametrize('version', VERSIONS)
def test_randomizer_schema_discloses_closed_property_context_and_matching_primary_sources(tmp_path, version):
    import hashlib
    from pathlib import Path
    task = PathTask(tmp_path, version)
    code, result = task.run('query-schema')
    assert code == 0, result
    contract = result['related_outputs']['randomizers']
    assert contract['hop'] == 'randomizer MEANING'
    assert contract['terminals'] == ['enabled', 'min-offset', 'max-offset']
    assert contract['modifier_identity_required'] is False
    assert 'actual native values required' in contract['value_authority']
    source = contract['source']
    assert source['version'] == version
    p = Path(__file__).parents[2] / 'skills/waapi-skill/resources/manifest' / version / 'definitions.json'
    assert source['definitions_sha256'] == hashlib.sha256(p.read_bytes()).hexdigest()
    assert 'randomizer(&quot;PropertyName&quot;)' in source['return_example']['html'] or 'randomizer("PropertyName")' in source['return_example']['html']
    for section in [source['return_example'], *source['modifier_fields'].values()]:
        assert hashlib.sha256(section['html'].encode()).hexdigest() == section['sha256']


def randomizer_task(tmp_path, version, layout):
    if layout == 'root':
        task = PathTask(tmp_path, version)
        task.rows = task.rows[:1]
        return task, task.row, SOUND, []
    task = NamespacedTask(tmp_path, version)
    task.rows = task.rows[:1]
    task.rows[0]['children'] = [task.reference(SOUND)]
    return task, task.members[SOUND], SOUND, ['children']


def randomizer_result(result, layout, token='Pitch'):
    row, = result['agent_result']
    if layout == 'list': row, = row['related']['children']['items']
    return row['related']['randomizers'][token]


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('layout', ['root', 'list'])
def test_absent_randomizer_fields_preserve_owner_without_invented_defaults(tmp_path, version, layout):
    task, row, identity, path = randomizer_task(tmp_path, version, layout)
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--include-related', *path, 'randomizer', 'Pitch', 'enabled',
        '--include-related', *path, 'randomizer', 'Pitch', 'min-offset')
    assert code == 0, result
    assert randomizer_result(result, layout) == {'unavailable_fields': ['enabled', 'min_offset']}


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('layout', ['root', 'list'])
@pytest.mark.parametrize('terminal,native,value', [('enabled', 'Enabled', 0), ('min-offset', 'Min', False), ('max-offset', 'Max', None)])
def test_present_randomizer_values_require_their_specific_scalar_type(tmp_path, version, layout, terminal, native, value):
    task, row, identity, path = randomizer_task(tmp_path, version, layout)
    row[f'randomizer("Pitch").@{native}'] = value
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--include-related', *path, 'randomizer', 'Pitch', terminal)
    assert code == 2 and result.get('agent_result') is None, result
    assert result['error_code'] == 'RELATED_QUERY_RANDOMIZER_VALUE'


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('layout', ['root', 'list'])
def test_namespaced_randomizer_argument_uses_actual_object_kind_fallback_and_owned_quotes(tmp_path, version, layout):
    task, row, identity, path = randomizer_task(tmp_path, version, layout)
    token = 'MyCompany:Pitch'
    info = {'name': token, 'type': 'Real64', 'display': {'name': 'Custom Pitch'}}
    task.metadata[SOUND_CLASS] = {token: {**info, 'type': ''}}
    task.metadata[identity] = {token: info}
    row['randomizer("MyCompany:Pitch").@Min'] = -3.5
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--include-related', *path, 'randomizer', 'Custom Pitch', 'min-offset', '--detail')
    assert code == 0, result
    assert randomizer_result(result, layout, token) == {'min_offset': -3.5}
    assert any(selection['scope'] == {'object': identity} and selection['selected'] == {'name': token, 'kind': 'property'}
        for selection in result['related_scope_binding']['scopes'])


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('layout', ['root', 'list'])
def test_randomizer_arguments_require_actual_property_kind_not_reference_metadata(tmp_path, version, layout):
    task, row, identity, path = randomizer_task(tmp_path, version, layout)
    task.metadata[SOUND_CLASS]['Pitch'] = {**copy.deepcopy(REFERENCE_PACKET['metadata']), 'name': 'Pitch', 'display': {'name': 'Pitch'}}
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--include-related', *path, 'randomizer', 'Pitch', 'enabled')
    assert code == 2 and result['error_code'] == 'RELATED_QUERY_FIELD_KIND', result
    assert result.get('agent_result') is None


@pytest.mark.parametrize('version', VERSIONS)
def test_randomizer_duplicate_semantic_aliases_do_not_merge_or_dispatch_final_values(tmp_path, version):
    task = PathTask(tmp_path, version)
    task.rows = task.rows[:1]
    task.metadata[SOUND_CLASS]['Pitch']['display']['name'] = 'Voice Pitch'
    task.row['randomizer("Pitch").@Min'] = -200
    code, result = task.run('query-object', '--exact-id', SOUND,
        '--include-related', 'randomizer', 'Pitch', 'min-offset',
        '--include-related', 'randomizer', 'Voice Pitch', 'min-offset')
    assert code == 2 and result['error_code'] == 'RELATED_QUERY_DUPLICATE_FIELD', result
    assert not any('randomizer("Pitch").@Min' in (options or {}).get('return', ()) for _, _, options in task.calls)


@pytest.mark.parametrize('version', VERSIONS)
def test_root_randomizer_still_binds_when_an_independent_list_view_selects_list_planner(tmp_path, version):
    task = NamespacedTask(tmp_path, version)
    owner = task.rows[0]
    task.rows = [owner]
    task.metadata[owner['id']] = copy.deepcopy(task.metadata[SOUND_CLASS])
    owner['randomizer("Pitch").@Min'] = -5
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--include-related', 'randomizer', 'Pitch', 'min-offset', '--include-related', 'children', 'volume-db')
    assert code == 0, result
    related = result['agent_result'][0]['related']
    assert related['randomizers']['Pitch'] == {'min_offset': -5}
    assert len(related['children']['items']) == 2


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('layout', ['root', 'list'])
def test_randomizer_meaning_ambiguity_and_new_invocation_metadata_are_not_cached_authority(tmp_path, version, layout):
    task, row, identity, path = randomizer_task(tmp_path, version, layout)
    info = task.metadata[SOUND_CLASS]['Pitch']
    info['display'] = {'name': 'Offset Property'}
    task.metadata[SOUND_CLASS]['OtherPitch'] = {**copy.deepcopy(info), 'name': 'OtherPitch'}
    row['randomizer("Pitch").@Min'] = 0
    flags = ['query-object', '--kind', 'all-sounds', '--max-results', '1', '--include-related', *path, 'randomizer']
    code, result = task.run(*flags, 'Offset Property', 'min-offset')
    assert code == 0 and result['status'] == 'needs_clarification', result
    assert result['agent_result']['unresolved'][0]['option'] == 'randomizer'
    code, result = task.run(*flags, 'Pitch', 'min-offset')
    assert code == 0 and randomizer_result(result, layout) == {'min_offset': 0}, result
    task.metadata[SOUND_CLASS] = {}; task.metadata[identity] = {}
    before = len(task.calls)
    code, result = task.run(*flags, 'Pitch', 'min-offset')
    assert code == 0 and result['status'] == 'needs_clarification', result
    assert any(uri.endswith('getPropertyAndReferenceNames') for uri, _, _ in task.calls[before:])


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('layout', ['root', 'list'])
def test_actual_owner_scopes_select_their_own_randomizer_argument(tmp_path, version, layout):
    task = PathTask(tmp_path, version) if layout == 'root' else NamespacedTask(tmp_path, version)
    owners = task.rows if layout == 'root' else [task.members[SOUND], task.members[OTHER]]
    owners[1]['classId'] = REFERENCE_CLASS
    task.metadata[SOUND_CLASS] = {'Pitch': {'name': 'Pitch', 'type': 'Real64', 'display': {'name': 'Offset Property'}}}
    task.metadata[REFERENCE_CLASS] = {'OtherPitch': {'name': 'OtherPitch', 'type': 'Real64', 'display': {'name': 'Offset Property'}}}
    owners[0]['randomizer("Pitch").@Min'] = -200
    owners[1]['randomizer("OtherPitch").@Min'] = 0
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2',
        '--include-related', *(['children'] if layout == 'list' else []), 'randomizer', 'Offset Property', 'min-offset')
    assert code == 0, result
    rows = result['agent_result'] if layout == 'root' else result['agent_result'][0]['related']['children']['items']
    assert [row['related']['randomizers'] for row in rows] == [{'Pitch': {'min_offset': -200}}, {'OtherPitch': {'min_offset': 0}}]


@pytest.mark.parametrize('layout', ['root', 'list'])
@pytest.mark.parametrize('change', ['none', 'metadata', 'value', 'typed-value'])
def test_randomizer_pages_revalidate_property_scope_and_returned_values(tmp_path, layout, change):
    task, row, identity, path = randomizer_task(tmp_path, '2025.1', layout)
    root = task.row if layout == 'root' else task.rows[0]
    root['notes'] = '音声' * 16000
    row['randomizer("Pitch").@Min'] = 0
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1', '--include', 'notes',
        '--include-related', *path, 'randomizer', 'Pitch', 'min-offset')
    assert code == 0 and result['status'] == 'partial', result
    if change == 'value': row['randomizer("Pitch").@Min'] = 1
    elif change == 'typed-value': row['randomizer("Pitch").@Min'] = False
    elif change == 'metadata': task.metadata[SOUND_CLASS]['Pitch']['type'] = 'Real64'
    code, continued = task.run(*result['agent_result']['next_command']['gateway_argv'])
    if change == 'none': assert code == 0 and continued['status'] == 'partial', continued
    else: assert code == 2 and continued['error_code'] == 'QUERY_RESULT_CONTINUATION_CHANGED', continued


@pytest.mark.parametrize('tokens', [
    ['randomizer', '@Pitch', 'min-offset'],
    ['randomizer', 'Pitch', 'parent', 'min-offset'],
    ['randomizer', 'Pitch', 'volume-db'],
    ['randomizer', 'Pitch', 'count'],
    ['randomizer', 'Pitch', 'randomizer', 'Volume', 'enabled'],
])
def test_randomizer_context_cannot_become_raw_or_traversable_function_grammar(tmp_path, tokens):
    task = PathTask(tmp_path)
    code, result = task.run('query-object', '--exact-id', SOUND, '--include-related', *tokens)
    assert code == 2, result
    assert task.calls == []


@pytest.mark.parametrize('layout', ['root', 'list'])
@pytest.mark.parametrize('token', ['Company::Pitch', 'Pitch) where true', 'Company:Pitch.extra', 'Company:Рitch'])
def test_discovered_randomizer_arguments_cannot_inject_quoted_expression(tmp_path, layout, token):
    task, row, identity, path = randomizer_task(tmp_path, '2025.1', layout)
    task.metadata[SOUND_CLASS] = {token: {'name': token, 'type': 'Real64', 'display': {'name': 'Offset Property'}}}
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--include-related', *path, 'randomizer', 'Offset Property', 'min-offset')
    assert code == 2 and result['error_code'] == 'RELATED_QUERY_FIELD_TOKEN', result
    assert not any(any('randomizer(' in field for field in (options or {}).get('return', ())) for _, _, options in task.calls)


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('layout', ['root', 'list'])
def test_unmatched_actual_scope_keeps_owner_and_scoped_unavailable_argument(tmp_path, version, layout):
    task = PathTask(tmp_path, version) if layout == 'root' else NamespacedTask(tmp_path, version)
    owners = task.rows if layout == 'root' else [task.members[SOUND], task.members[OTHER]]
    owners[1]['classId'] = REFERENCE_CLASS
    task.metadata[REFERENCE_CLASS] = {}; task.metadata[OTHER] = {}
    owners[0]['randomizer("Pitch").@Min'] = -5
    owners[1]['randomizer("Pitch").@Min'] = 999  # Raw data on an unbound scope supplies no property authority.
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2',
        '--include-related', *(['children'] if layout == 'list' else []), 'randomizer', 'Pitch', 'min-offset')
    assert code == 0 and result['status'] == 'ok', result
    rows = result['agent_result'] if layout == 'root' else result['agent_result'][0]['related']['children']['items']
    assert rows[0]['related']['randomizers']['Pitch'] == {'min_offset': -5}
    assert 'randomizers' not in rows[1].get('related', {})
    assert rows[1]['unavailable_field_requests'][0]['meaning'] == 'Pitch'
    assert rows[1]['unavailable_field_requests'][0]['requested_option'] == 'randomizer'
