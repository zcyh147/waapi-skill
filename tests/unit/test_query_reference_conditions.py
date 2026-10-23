"""Closed reference/value-source conditions at the public Gateway seam."""
import copy
import json
import re

import pytest

from tests.unit.test_query_field_conditions import FieldTask, SOUND, OTHER, SOUND_CLASS
from tests.unit.test_query_related_paths import REFERENCE_CLASS, REFERENCE_PACKET, TARGET, LOCAL
from tests.unit.test_object_query_result_pages import VERSIONS


MISSING = '{00000000-0000-0000-0000-000000000099}'


class ReferenceTask(FieldTask):
    def __init__(self, tmp_path, version='2025.1'):
        super().__init__(tmp_path, version)
        self.metadata[REFERENCE_CLASS] = {'PlaylistObject': copy.deepcopy(REFERENCE_PACKET['metadata'])}
        self.metadata[REFERENCE_CLASS]['Pitch'] = copy.deepcopy(self.metadata[SOUND_CLASS]['Pitch'])
        for index, row in enumerate(self.members.values()):
            row.update(classId=REFERENCE_CLASS, type=REFERENCE_PACKET['identity_model']['type'])
            resolved, local = (TARGET, LOCAL) if index == 0 else (LOCAL, TARGET)
            row['@@PlaylistObject'] = {**resolved, 'extension': {'zero': 0, 'false': False}}
            row['@PlaylistObject'] = {**local, 'extension': {'zero': 0, 'false': False}}
            row['PlaylistObject'] = copy.deepcopy(row['@@PlaylistObject'])
            row['@@Pitch'] = 0 if index == 0 else -560
        self.targets = {TARGET['id']: {**TARGET, 'type': 'Bus', 'path': r'\Buses\Resolved'}}

    def call(self, uri, args=None, options=None):
        args = args or {}
        if uri.endswith('object.get') and ('from' in args or args.get('waql', '').startswith('from type Bus ')):
            self.calls.append((uri, args, options))
            if 'from' in args:
                key, values = next(iter(args['from'].items()))
                rows = [row for row in {**self.objects, **self.targets}.values() if row.get(key) in values]
            else:
                expression = re.search(r' where (.+) take 2$', args['waql']).group(1)
                rows = [row for row in self.targets.values() if self.native_matches(row, expression)]
            return {'return': [self.projection(row, options['return']) for row in rows]}
        return super().call(uri, args, options)

    @classmethod
    def native_matches(cls, row, expression):
        if expression.startswith('!(') and expression.endswith(')'):
            return not cls.native_matches(row, expression[2:-1])
        match = re.fullmatch(r'(@@?\w+)(\.id)? (=|!=) (null|"[^"\n]+")', expression)
        if match:
            field, identity, operator, literal = match.groups()
            value = row.get(field)
            if identity:
                if not isinstance(value, dict): return False
                value = value['id']
            expected = json.loads(literal)
            return value == expected if operator == '=' else value != expected
        return super().native_matches(row, expression)


@pytest.mark.parametrize('version', VERSIONS)
def test_two_owners_keep_distinct_resolved_and_stored_reference_matches(tmp_path, version):
    task = ReferenceTask(tmp_path, version)
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2',
        '--include-related', 'children', 'volume-db',
        '--include-related', 'children', 'matching-field', 'reference', 'Playlist Object', 'is', TARGET['id'], 'volume-db',
        '--include-related', 'children', 'matching-field', 'local-reference', 'Playlist Object', 'is', TARGET['id'], 'count')
    assert code == 0, result
    assert len(result['agent_result']) == 2
    for root in result['agent_result']:
        assert len(root['related']['children']['items']) == 2
        resolved, stored = root['related']['projections']
        assert [row['object']['id'] for row in resolved['items']] == [SOUND]
        assert stored['value'] == 1
    assert any('where @@PlaylistObject.id = ' in (args or {}).get('waql', '') for uri, args, _ in task.calls)
    assert any('where @PlaylistObject.id = ' in (args or {}).get('waql', '') for uri, args, _ in task.calls)


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('constant', [MISSING, json.dumps({'kind': 'id', 'value': MISSING})])
def test_nonexistent_guid_is_a_literal_comparison_not_a_live_target(tmp_path, version, constant):
    task = ReferenceTask(tmp_path, version)
    task.rows = list(task.members.values())
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--where-field', 'reference', 'Playlist Object', 'is', constant)
    assert code == 0 and result['agent_result'] == [], result
    assert not any(MISSING in str(args) and 'where' not in (args or {}).get('waql', '') for _, args, _ in task.calls)


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('source', ['broad', 'advanced', 'relationship'])
@pytest.mark.parametrize('mode,expected', [('reference', SOUND), ('local-reference', OTHER), ('override-source-value', OTHER)])
def test_modes_share_complete_root_scope_before_limit(tmp_path, version, source, mode, expected):
    task = ReferenceTask(tmp_path, version)
    if source == 'relationship': flags = ['--exact-id', task.rows[0]['id'], '--relationship', 'children']
    else:
        task.rows = list(task.members.values())
        flags = ['--kind', 'all-sounds'] if source == 'broad' else ['--advanced-waql', 'from type PluginInnerObject']
    condition = ['Voice Pitch', 'at-most', '-500'] if mode == 'override-source-value' else ['Playlist Object', 'is', TARGET['id']]
    code, result = task.run('query-object', *flags, '--max-results', '1', '--where-field', mode, *condition)
    assert code == 0, result
    assert [row['id'] for row in result['agent_result']] == [expected]


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('mode', ['reference', 'local-reference'])
@pytest.mark.parametrize('presence', ['null', 'absent'])
def test_reference_setness_preserves_native_absence_and_null_without_python_guess(tmp_path, version, mode, presence):
    task = ReferenceTask(tmp_path, version)
    field = ('@@' if mode == 'reference' else '@') + 'PlaylistObject'
    if presence == 'null': task.members[OTHER][field] = None
    else: task.members[OTHER].pop(field)
    # This fake transport supplies native setness decisions. In particular its
    # selected unset record retains omission rather than synthesizing a null.
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2',
        '--include-related', 'children', 'any-match-field', mode, 'Playlist Object', 'is-not', 'null',
        '--include-related', 'children', 'matching-field', mode, 'Playlist Object', 'is', 'null', 'volume-db')
    assert code == 0, result
    for root in result['agent_result']:
        present, unset = root['related']['projections']
        assert present['value'] is True
        assert [item['object']['id'] for item in unset['items']] == [OTHER]


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('selector', [
    {'kind': 'path', 'value': '\\' + '声' * 2000},
    {'kind': 'exact-type-name', 'type': 'Bus', 'name': 'Resolved'},
])
def test_named_reference_selector_uses_owning_identity_budget_and_actual_resolution(tmp_path, version, selector):
    task = ReferenceTask(tmp_path, version)
    task.rows = list(task.members.values())
    if selector['kind'] == 'path': task.targets[TARGET['id']]['path'] = selector['value']
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--where-field', 'reference', 'Playlist Object', 'is', json.dumps(selector, ensure_ascii=False))
    assert code == 0, result
    assert [row['id'] for row in result['agent_result']] == [SOUND]
    assert any('from' in (args or {}) or (args or {}).get('waql', '').startswith('from type Bus ') for _, args, _ in task.calls)


@pytest.mark.parametrize('version', VERSIONS)
def test_offline_schema_discloses_separate_query_and_return_mode_authority(tmp_path, version):
    import hashlib
    from pathlib import Path
    from tests.unit.test_object_query_result_pages import gateway
    task = ReferenceTask(tmp_path, version)
    code, result = task.run('query-schema')
    assert code == 0, result
    contract = result['field_conditions']
    assert set(contract['modes']) == {'ordinary', 'reference', 'local-reference', 'override-source-value'}
    assert contract['reference_constants']['canonical_guid_requires_existence'] is False
    source = contract['reference_source']
    assert source['version'] == version and source['domain'] == 'query-predicates-and-selection'
    for section in source['sections'].values():
        assert hashlib.sha256(section['html'].encode()).hexdigest() == section['html_sha256']
    assert 'When using @' in source['sections']['reference_object_expression']['html']
    assert '!= null' in source['sections']['where_examples']['html']
    assert source['definitions_sha256'] == hashlib.sha256((Path(gateway.__file__).parents[1]/'resources/manifest'/version/'definitions.json').read_bytes()).hexdigest()
    assert not task.calls


@pytest.mark.parametrize('version', VERSIONS)
def test_named_target_meaning_is_revalidated_after_final_selection(tmp_path, version):
    task = ReferenceTask(tmp_path, version)
    task.rows = list(task.members.values())
    original = task.call
    def changed(uri, args=None, options=None):
        result = original(uri, args, options)
        if (args or {}).get('waql', '').startswith('from type Sound where @@PlaylistObject'):
            task.targets[TARGET['id']]['name'] = 'Renamed'
        return result
    task.call = changed
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--where-field', 'reference', 'Playlist Object', 'is',
        json.dumps({'kind': 'exact-type-name', 'type': 'Bus', 'name': 'Resolved'}))
    assert code == 2 and result['error_code'] == 'QUERY_FIELD_CONDITION_TARGET', result


@pytest.mark.parametrize('version', VERSIONS)
def test_scoped_selector_parent_retains_owning_character_budget(tmp_path, version):
    from wwise_waapi.operation_object import DEFAULT_MAX_IDENTITY_PARENT_LITERAL_LENGTH
    task = ReferenceTask(tmp_path, version)
    task.rows = list(task.members.values())
    parent = '{00000000-0000-0000-0000-000000000088}'
    path = '\\' + '声' * (DEFAULT_MAX_IDENTITY_PARENT_LITERAL_LENGTH - 1)
    task.objects[parent] = {'id': parent, 'name': 'Parent', 'type': 'WorkUnit', 'path': path,
        'children': [TARGET]}
    task.targets[TARGET['id']]['parent'] = {'id': parent, 'name': 'Parent'}
    task.objects.update(task.targets)
    selector = {'kind': 'scoped-name', 'type': 'Bus', 'name': 'Resolved', 'parent': {'kind': 'path', 'value': path}}
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--where-field', 'reference', 'Playlist Object', 'is', json.dumps(selector, ensure_ascii=False))
    assert code == 0 and [row['id'] for row in result['agent_result']] == [SOUND], result


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('fault', ['absent', 'null', 'wrong-id', 'typed-extension'])
def test_selected_reference_observation_requires_exact_presence_and_value(tmp_path, version, fault):
    task = ReferenceTask(tmp_path, version)
    original = task.call
    def changed(uri, args=None, options=None):
        result = original(uri, args, options)
        if 'where @@PlaylistObject.id' in (args or {}).get('waql', ''):
            for row in result['return']:
                if fault == 'absent': row.pop('@@PlaylistObject')
                elif fault == 'null': row['@@PlaylistObject'] = None
                elif fault == 'wrong-id': row['@@PlaylistObject']['id'] = MISSING
                else: row['@@PlaylistObject']['extension']['false'] = 0
        return result
    task.call = changed
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2',
        '--include-related', 'children', 'matching-field', 'reference', 'Playlist Object', 'is', TARGET['id'], 'count')
    assert code == 2 and result['error_code'] == 'RELATED_QUERY_SCOPE_CHANGED', result


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('change', ['none', 'literal-target-name', 'named-target', 'reference-value', 'metadata'])
def test_reference_pages_bind_only_the_actual_operand_authority(tmp_path, version, change):
    task = ReferenceTask(tmp_path, version)
    task.rows = list(task.members.values())
    for row in task.members.values(): row['notes'] = '音声' * 16000
    value = json.dumps({'kind': 'exact-type-name', 'type': 'Bus', 'name': 'Resolved'}) if change == 'named-target' else TARGET['id']
    code, first = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2',
        '--where-field', 'reference', 'Playlist Object', 'is', value, '--include', 'notes')
    assert code == 0 and first['status'] == 'partial', first
    if change in {'literal-target-name', 'named-target'}: task.targets[TARGET['id']]['name'] = 'Renamed'
    elif change == 'reference-value': task.members[SOUND]['@@PlaylistObject']['extension']['false'] = 0
    elif change == 'metadata': task.metadata[REFERENCE_CLASS]['PlaylistObject']['display']['name'] = 'Renamed Meaning'
    code, second = task.run(*first['agent_result']['next_command']['gateway_argv'])
    if change in {'none', 'literal-target-name'}:
        assert code == 0 and second['status'] == 'partial', second
        assert second['agent_result']['page']['offset'] == first['agent_result']['page']['next_offset']
    else:
        assert code == 2 and second['error_code'] == 'QUERY_RESULT_CONTINUATION_CHANGED', second


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('values', [
    ['reference', 'Playlist Object', 'below', MISSING],
    ['reference', '@PlaylistObject', 'is', MISSING],
    ['reference', 'PlaylistObject.id', 'is', MISSING],
    ['reference', 'Playlist Object', 'is', '{"kind":"waql","value":"from type Sound"}'],
    ['reference', 'Playlist Object', 'is', '{"kind":"id","kind":"path","value":"x"}'],
    ['reference', 'Playlist Object', 'is', '{"kind":"id","value":false}'],
])
def test_reference_conditions_reject_raw_or_invalid_operands_before_transport(tmp_path, version, values):
    task = ReferenceTask(tmp_path, version)
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1', '--where-field', *values)
    assert code == 2, result
    assert not task.calls


@pytest.mark.parametrize('version', VERSIONS)
def test_reference_binding_uses_each_actual_class_token_and_preserves_occurrences(tmp_path, version):
    task = ReferenceTask(tmp_path, version)
    task.members[OTHER].update(classId=SOUND_CLASS, type='Sound')
    task.metadata[SOUND_CLASS]['AlternateReference'] = {**copy.deepcopy(REFERENCE_PACKET['metadata']), 'name': 'AlternateReference'}
    task.members[OTHER]['@@AlternateReference'] = copy.deepcopy(task.members[OTHER]['@@PlaylistObject'])
    task.members[OTHER].pop('@@PlaylistObject')
    task.rows[0]['children'] += [task.reference(SOUND)]
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2',
        '--include-related', 'children', 'matching-field', 'reference', 'Playlist Object', 'is', TARGET['id'], 'volume-db',
        '--include-related', 'children', 'all-match-field', 'reference', 'Playlist Object', 'is-not', MISSING)
    assert code == 0, result
    assert [item['object']['id'] for item in result['agent_result'][0]['related']['projections'][0]['items']] == [SOUND, SOUND]
    assert all(row['related']['projections'][1]['value'] is True for row in result['agent_result'])
    assert any('@@AlternateReference.id' in (args or {}).get('waql', '') for _, args, _ in task.calls)
    task.rows = [task.members[OTHER], task.members[SOUND]]
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--where-field', 'reference', 'Playlist Object', 'is', TARGET['id'])
    assert code == 0 and [row['id'] for row in result['agent_result']] == [SOUND], result
    assert {uri for uri, _, _ in task.calls} <= {'ak.wwise.core.getInfo', 'ak.wwise.core.object.get',
        'ak.wwise.core.object.getPropertyAndReferenceNames', 'ak.wwise.core.object.getPropertyInfo'}


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('mode,meaning', [('ordinary', 'Playlist Object'), ('override-source-value', 'Playlist Object'), ('reference', 'Voice Pitch'), ('local-reference', 'Voice Pitch')])
def test_known_wrong_field_kind_cannot_change_mode(tmp_path, version, mode, meaning):
    task = ReferenceTask(tmp_path, version)
    task.rows = list(task.members.values())
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--where-field', mode, meaning, 'is', TARGET['id'] if mode in {'reference', 'local-reference'} else '0')
    assert code == 2 and result['error_code'] == 'QUERY_FIELD_CONDITION_KIND', result


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('kind,value,literal', [('bool', False, 'false'), ('int32', 0, '0'), ('string', 'null', 'null')])
def test_override_property_values_keep_exact_scalar_types_and_null_text(tmp_path, version, kind, value, literal):
    task = ReferenceTask(tmp_path, version)
    task.rows = [task.members[SOUND]]
    task.metadata[REFERENCE_CLASS]['Pitch']['type'] = kind
    task.members[SOUND]['@@Pitch'] = value
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--where-field', 'override-source-value', 'Voice Pitch', 'is', literal)
    assert code == 0 and [row['id'] for row in result['agent_result']] == [SOUND], result


@pytest.mark.parametrize('version', VERSIONS)
def test_reference_window_before_matching_does_not_discover_hidden_suffix(tmp_path, version):
    task = ReferenceTask(tmp_path, version)
    task.rows[0]['children'] = [task.reference(OTHER)] + [task.reference(SOUND)] * 4096
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2',
        '--include-related', 'combine', 'children', 'and', 'self', 'end', 'take', '1',
        'matching-field', 'reference', 'Playlist Object', 'is', TARGET['id'], 'count')
    assert code == 0, result
    assert [row['related']['projections'][0]['value'] for row in result['agent_result']] == [0, 0]


@pytest.mark.parametrize('version', VERSIONS)
def test_reference_unknown_scope_keeps_roots_and_unavailability_mode(tmp_path, version):
    task = ReferenceTask(tmp_path, version)
    task.metadata[REFERENCE_CLASS].pop('PlaylistObject')
    task.metadata[SOUND] = task.metadata[OTHER] = {}
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2',
        '--include-related', 'children', 'volume-db',
        '--include-related', 'children', 'matching-field', 'local-reference', 'Playlist Object', 'is-not', 'null', 'count')
    assert code == 0, result
    for root in result['agent_result']:
        assert len(root['related']['children']['items']) == 2
        record, = root['related']['projections']
        assert 'value' not in record and 'items' not in record
        assert record['unavailable_predicates'][0]['condition']['mode'] == 'local-reference'


def test_reference_selector_request_budget_is_not_removed_by_json_whitespace(tmp_path):
    from wwise_waapi.operation_object import DEFAULT_MAX_REQUEST_BYTES
    task = ReferenceTask(tmp_path)
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--where-field', 'reference', 'Playlist Object', 'is', ' ' * DEFAULT_MAX_REQUEST_BYTES + 'null')
    assert code == 2 and not task.calls, result


@pytest.mark.parametrize('version', VERSIONS)
def test_unset_native_identity_inequality_is_not_python_complement(tmp_path, version):
    task = ReferenceTask(tmp_path, version)
    task.members[OTHER].pop('@@PlaylistObject')
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2',
        '--include-related', 'children', 'matching-field', 'reference', 'Playlist Object', 'is-not', TARGET['id'], 'count',
        '--include-related', 'children', 'matching-field', 'reference', 'Playlist Object', 'is', 'null', 'volume-db')
    assert code == 0, result
    for root in result['agent_result']:
        unequal, unset = root['related']['projections']
        assert unequal['value'] == 0  # Native fake: an absent .id is not an unequal string.
        assert [row['object']['id'] for row in unset['items']] == [OTHER]


@pytest.mark.parametrize('version', VERSIONS)
def test_named_selector_ambiguity_is_not_a_literal_guid_failure(tmp_path, version):
    task = ReferenceTask(tmp_path, version)
    task.rows = list(task.members.values())
    task.targets[LOCAL['id']] = {**task.targets[TARGET['id']], 'id': LOCAL['id'], 'path': r'\Other\Resolved'}
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--where-field', 'reference', 'Playlist Object', 'is', json.dumps({'kind': 'exact-type-name', 'type': 'Bus', 'name': 'Resolved'}))
    assert code == 2 and result['error_code'] == 'QUERY_FIELD_CONDITION_TARGET', result


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('value', [False, 0, [], {'id': 'not-a-guid'}])
def test_malformed_reference_observation_is_unknown_not_an_unset_value(tmp_path, version, value):
    task = ReferenceTask(tmp_path, version)
    task.members[OTHER]['@PlaylistObject'] = value
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2',
        '--include-related', 'children', 'any-match-field', 'local-reference', 'Playlist Object', 'is', 'null')
    assert code == 0, result
    for root in result['agent_result']:
        projection, = root['related']['projections']
        assert 'value' not in projection
        assert projection['unavailable_predicates'][0]['presence'] == 'incompatible_type'
