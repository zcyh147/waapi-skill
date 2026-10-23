"""Condition-only namespaced property binding at the public Gateway seam."""
import copy
import json
import re

import pytest

from tests.unit.test_query_field_conditions import FieldTask, SOUND, OTHER, SOUND_CLASS
from tests.unit.test_object_query_result_pages import VERSIONS


TOKEN = 'MyCompany:Status'
METADATA = {'name': TOKEN, 'type': 'int16', 'default': 0, 'display': {'name': 'Status'},
    'restriction': {'type': 'enum', 'values': [{'value': value} for value in (0, 1, 2)]}}


class NamespacedTask(FieldTask):
    def __init__(self, tmp_path, version):
        super().__init__(tmp_path, version)
        self.metadata[SOUND_CLASS][TOKEN] = copy.deepcopy(METADATA)
        for index, row in enumerate(self.members.values()):
            row['@' + TOKEN] = index
            row['@@' + TOKEN] = 1 - index

    @classmethod
    def native_matches(cls, row, expression):
        # External fake-native decision only; no production renderer/evaluator.
        match = re.fullmatch(r'(@@?[A-Za-z0-9_]+:[A-Za-z0-9_]+) (=|!=|<=|>=|<|>) (.+)', expression)
        if match:
            field, operator, literal = match.groups()
            if field not in row: return False
            actual, value = row[field], json.loads(literal)
            if operator == '=': return type(actual) is type(value) and actual == value
            if operator == '!=': return actual != value
            if operator == '<=': return actual <= value
            if operator == '>=': return actual >= value
            if operator == '<': return actual < value
            return actual > value
        return super().native_matches(row, expression)


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('mode,expected,clause', [
    ('ordinary', SOUND, 'where @MyCompany:Status = 0'),
    ('override-source-value', OTHER, 'where @@MyCompany:Status = 0'),
])
def test_namespaced_property_conditions_bind_actual_metadata_before_root_limit(tmp_path, version, mode, expected, clause):
    task = NamespacedTask(tmp_path, version)
    task.rows = [task.members[OTHER], task.members[SOUND]]
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--where-field', mode, 'Status', 'is', '0', '--detail')
    assert code == 0, result
    assert [row['id'] for row in result['agent_result']] == [expected]
    assert clause + ' take 1' in result['semantic_preview']['envelope']['args']['waql']
    assert result['related_scope_binding']['root_field_conditions']['source_complete'] is True
    assert any(uri.endswith('getPropertyInfo') and args['property'] == TOKEN for uri, args, _ in task.calls)
    assert list(result)[-1] == 'agent_result'


@pytest.mark.parametrize('version', VERSIONS)
def test_related_namespaced_condition_modes_keep_independent_views_and_native_reducers(tmp_path, version):
    task = NamespacedTask(tmp_path, version)
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2',
        '--include-related', 'children', 'volume-db',
        '--include-related', 'children', 'matching-field', 'ordinary', 'Status', 'is', '0', 'volume-db',
        '--include-related', 'children', 'matching-field', 'override-source-value', 'Status', 'is', '0', 'count',
        '--include-related', 'children', 'any-match-field', 'ordinary', 'Status', 'is', '0')
    assert code == 0, result
    for row in result['agent_result']:
        assert len(row['related']['children']['items']) == 2
        ordinary, override, any_match = row['related']['projections']
        assert [item['object']['id'] for item in ordinary['items']] == [SOUND]
        assert override['value'] == 1 and any_match['value'] is True


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('exact_token', [False, True])
def test_namespaced_meaning_ambiguity_requires_exact_live_discovery(tmp_path, version, exact_token):
    task = NamespacedTask(tmp_path, version)
    alternate = 'OtherCompany:Status'
    task.metadata[SOUND_CLASS][alternate] = {**copy.deepcopy(METADATA), 'name': alternate}
    task.rows = [task.members[SOUND], task.members[OTHER]]
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--where-field', 'ordinary', TOKEN if exact_token else 'Status', 'is', '0')
    if exact_token:
        assert code == 0 and [row['id'] for row in result['agent_result']] == [SOUND], result
    else:
        assert code == 2 and result['error_code'] == 'QUERY_FIELD_CONDITION_UNAVAILABLE', result
        assert not any(' where ' in (args or {}).get('waql', '') for _, args, _ in task.calls)


@pytest.mark.parametrize('version', VERSIONS)
def test_namespaced_instance_scopes_do_not_borrow_another_objects_token(tmp_path, version):
    task = NamespacedTask(tmp_path, version)
    task.metadata[SOUND_CLASS].pop(TOKEN)
    alternate = 'OtherCompany:Status'
    task.metadata[SOUND] = {TOKEN: copy.deepcopy(METADATA)}
    task.metadata[OTHER] = {alternate: {**copy.deepcopy(METADATA), 'name': alternate}}
    task.members[OTHER]['@' + alternate] = 1
    task.rows = [task.members[OTHER], task.members[SOUND]]
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--where-field', 'ordinary', 'Status', 'is', '0', '--detail')
    assert code == 0 and [row['id'] for row in result['agent_result']] == [SOUND], result
    selections = result['related_scope_binding']['root_field_conditions']['scopes']
    assert {(row['scope']['object'], row['selected']['name']) for row in selections} == {(SOUND, TOKEN), (OTHER, alternate)}


@pytest.mark.parametrize('version', VERSIONS)
def test_unknown_class_namespaced_kind_uses_actual_object_property_metadata(tmp_path, version):
    task = NamespacedTask(tmp_path, version)
    task.metadata[SOUND_CLASS][TOKEN].update(type='', restriction={})
    task.metadata[SOUND] = {TOKEN: copy.deepcopy(METADATA)}
    task.rows = [task.members[SOUND]]
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--where-field', 'ordinary', 'Status', 'is', '0', '--detail')
    assert code == 0 and [row['id'] for row in result['agent_result']] == [SOUND], result
    selection, = result['related_scope_binding']['root_field_conditions']['scopes']
    assert selection['scope'] == {'object': SOUND}


@pytest.mark.parametrize('version', VERSIONS)
def test_namespaced_conditions_refresh_metadata_on_each_invocation(tmp_path, version):
    task = NamespacedTask(tmp_path, version)
    task.rows = [task.members[SOUND]]
    flags = ('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--where-field', 'ordinary', 'Status', 'is', '0')
    code, result = task.run(*flags)
    assert code == 0 and [row['id'] for row in result['agent_result']] == [SOUND], result
    first_calls = len(task.calls)
    task.metadata[SOUND_CLASS][TOKEN]['type'] = 'opaque'
    code, result = task.run(*flags)
    assert code == 2 and result['error_code'] == 'QUERY_FIELD_CONDITION_UNAVAILABLE', result
    assert any(uri.endswith('getPropertyInfo') and args['property'] == TOKEN for uri, args, _ in task.calls[first_calls:])


@pytest.mark.parametrize('version', VERSIONS)
def test_namespaced_condition_scope_does_not_grant_custom_output_authority(tmp_path, version):
    task = NamespacedTask(tmp_path, version)
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2',
        '--include-related-field', 'children', 'matching-field', 'ordinary', 'Status', 'is', '0', 'Status')
    assert code == 2 and result['error_code'] == 'RELATED_QUERY_FIELD_TOKEN', result


@pytest.mark.parametrize('version', VERSIONS)
def test_schema_separates_namespaced_where_sources_from_existing_return_grammar(tmp_path, version):
    import hashlib
    from pathlib import Path
    task = NamespacedTask(tmp_path, version)
    code, result = task.run('query-schema')
    assert code == 0, result
    contract = result['field_conditions']['namespaced_properties']
    assert contract['modes'] == ['ordinary', 'override-source-value']
    assert contract['token_pattern'] == '[A-Za-z0-9_]+:[A-Za-z0-9_]+'
    assert contract['source']['version'] == version and contract['source']['domain'] == 'query-property-predicates'
    assert contract['source']['native_component']['version'] == '2025.1'
    assert contract['source']['native_component']['custom_return_proof'] is False
    assert contract['custom_output_token_grammar_changed'] is False
    assert contract['predicate_value_readback_required'] is True
    source = contract['source']
    definitions = Path(__file__).parents[2] / 'skills/waapi-skill/resources/manifest' / version / 'definitions.json'
    assert source['definitions_sha256'] == hashlib.sha256(definitions.read_bytes()).hexdigest()
    for section in source['sections'].values():
        assert hashlib.sha256(section['html'].encode()).hexdigest() == section['html_sha256']
    assert 'MyCompany:Status' in source['sections']['custom_property_definition']['html']
    assert '@@PROPERTY_NAME' in source['sections']['waql_property_accessors']['html']


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('token', ['MyCompany:Status.id', 'MyCompany::Status', 'MyCompany:Status) where true', 'MyCompany:Stаtus'])
def test_unsafe_discovered_tokens_never_gain_condition_expression_authority(tmp_path, version, token):
    task = NamespacedTask(tmp_path, version)
    task.metadata[SOUND_CLASS].pop(TOKEN)
    task.metadata[SOUND_CLASS][token] = {**copy.deepcopy(METADATA), 'name': token}
    task.rows = [task.members[SOUND]]
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--where-field', 'ordinary', 'Status', 'is', '0')
    assert code == 2 and result.get('agent_result') is None, result
    assert not any(' where ' in (args or {}).get('waql', '') for _, args, _ in task.calls)


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('mode', ['ordinary', 'reference'])
def test_namespaced_reference_metadata_never_borrows_scalar_token_permission(tmp_path, version, mode):
    from tests.unit.test_query_related_paths import REFERENCE_PACKET
    task = NamespacedTask(tmp_path, version)
    task.metadata[SOUND_CLASS][TOKEN] = {**copy.deepcopy(REFERENCE_PACKET['metadata']), 'name': TOKEN, 'display': {'name': 'Status'}}
    task.rows = [task.members[SOUND]]
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--where-field', mode, 'Status', 'is', SOUND if mode == 'reference' else '0')
    assert code == 2 and result.get('agent_result') is None, result
    assert not any(' where ' in (args or {}).get('waql', '') for _, args, _ in task.calls)


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('fault', ['absent', 'wrong-type'])
def test_namespaced_where_requires_existing_typed_selected_value_readback(tmp_path, version, fault):
    task = NamespacedTask(tmp_path, version)
    task.rows = [task.members[SOUND]]
    original = task.call
    def changed(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('object.get') and 'where @MyCompany:Status' in (args or {}).get('waql', ''):
            for row in result['return']:
                if fault == 'absent': row.pop('@' + TOKEN)
                else: row['@' + TOKEN] = False
        return result
    task.call = changed
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--where-field', 'ordinary', 'Status', 'is', '0')
    assert code == 2 and result.get('agent_result') is None, result


@pytest.mark.parametrize('change', ['none', 'metadata', 'value'])
def test_namespaced_conditions_keep_page_snapshot_authority(tmp_path, change):
    task = NamespacedTask(tmp_path, '2025.1')
    task.rows = [task.members[SOUND]]
    task.members[SOUND]['notes'] = '音声' * 16000
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--where-field', 'ordinary', 'Status', 'is', '0', '--include', 'notes')
    assert code == 0 and result['status'] == 'partial', result
    if change == 'metadata': task.metadata[SOUND_CLASS][TOKEN]['type'] = 'int32'
    elif change == 'value': task.members[SOUND]['@' + TOKEN] = False
    code, continued = task.run(*result['agent_result']['next_command']['gateway_argv'])
    if change == 'none': assert code == 0 and continued['status'] == 'partial', continued
    else: assert code == 2 and continued['error_code'] == 'QUERY_RESULT_CONTINUATION_CHANGED', continued


@pytest.mark.parametrize('kind,value,text,clause', [
    ('bool', False, 'false', 'where @MyCompany:Status = false'),
    ('string', 'null', 'null', 'where @MyCompany:Status = "null"'),
    ('Real64', 0.5, '0.5', 'where @MyCompany:Status = 0.5'),
])
def test_namespaced_renderer_preserves_existing_scalar_literal_types(tmp_path, kind, value, text, clause):
    task = NamespacedTask(tmp_path, '2025.1')
    task.metadata[SOUND_CLASS][TOKEN].update(type=kind, restriction={})
    task.members[SOUND]['@' + TOKEN] = value
    task.rows = [task.members[SOUND]]
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '1',
        '--where-field', 'ordinary', 'Status', 'is', text, '--detail')
    assert code == 0 and [row['id'] for row in result['agent_result']] == [SOUND], result
    assert clause + ' take 1' in result['semantic_preview']['envelope']['args']['waql']
