"""Root-preserving fixed related values through the public Gateway."""
from __future__ import annotations

import copy

import pytest

from tests.unit.test_object_query_result_pages import QueryTask, VERSIONS

SOUND = '{0030BF58-90C3-428B-B940-44CC1C5A51B5}'
OTHER = '{63715E20-32E0-4D02-B0D7-B510915A8A01}'
PARENT = {'id': '{D5594A4B-DDB0-47F3-AC2F-08F104C72438}', 'name': 'FS_Concrete'}
OTHER_PARENT = {'id': '{69B63CDA-3CCD-4246-982E-C1104DE15720}', 'name': 'Other'}


class RelatedTask(QueryTask):
    def __init__(self, tmp_path, version):
        super().__init__(tmp_path, version)
        self.row.pop('notes')
        self.row.update(id=SOUND)
        self.rows = [self.row, {**self.row, 'id': OTHER}]

    def call(self, uri, args=None, options=None):
        if uri.endswith('object.get') and args != {'waql': 'from type Project take 1'}:
            self.calls.append((uri, args, options))
            return {'return': copy.deepcopy(self.rows)}
        return super().call(uri, args, options)


@pytest.mark.parametrize('version', VERSIONS)
def test_each_sound_keeps_its_identity_and_own_related_values_without_metadata_reads(tmp_path, version):
    task = RelatedTask(tmp_path, version)
    task.rows[0].update({'@Volume': 0, 'parent': PARENT, 'parent.@Volume': -12, 'parent.@Pitch': -560})
    task.rows[1].update({'@Volume': -1, 'parent': OTHER_PARENT, 'parent.@Volume': -2, 'parent.@Pitch': 0})
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2',
        '--include', 'volume-db', '--include-related', 'parent', 'volume-db',
        '--include-related', 'parent', 'pitch-cents')
    assert code == 0, result
    rows = result['agent_result']
    assert [row['id'] for row in rows] == [SOUND, OTHER]
    assert [row['volume_db'] for row in rows] == [0, -1]
    assert [row['related'] for row in rows] == [
        {'parent': {'object': PARENT, 'volume_db': -12, 'pitch_cents': -560}},
        {'parent': {'object': OTHER_PARENT, 'volume_db': -2, 'pitch_cents': 0}},
    ]
    assert task.calls[-1] == ('ak.wwise.core.object.get', {'waql': 'from type Sound take 2'},
        {'return': ['id', 'name', 'type', 'path', '@Volume', 'parent', 'parent.@Volume', 'parent.@Pitch']})
    assert {uri for uri, _, _ in task.calls} == {'ak.wwise.core.getInfo', 'ak.wwise.core.object.get'}
    assert list(result)[-1] == 'agent_result'


@pytest.mark.parametrize('version', VERSIONS)
def test_offline_related_catalog_is_pinned_to_matching_descriptor_and_chain_sources(tmp_path, version):
    import json
    from pathlib import Path
    from tests.unit.test_object_query_result_pages import gateway
    task = RelatedTask(tmp_path, version)
    code, result = task.run('query-schema')
    assert code == 0, result
    contract = result['related_outputs']
    assert contract['relations'] == {'parent': 'parent', 'owner': 'owner', 'work-unit': 'workunit'}
    assert contract['metadata_reads'] is False
    assert contract['budget']['shared_fixed_outputs'] == gateway.MAX_QUERY_BUSINESS_OUTPUTS
    assert 'local values' in contract['terminal_semantics']
    assert 'not cumulative levels or runtime audio' in contract['terminal_semantics']
    assert contract['outputs']['volume-db']['available']
    assert contract['outputs']['notes']['available']
    assert contract['outputs']['original-file-path']['available']
    assert contract['outputs']['active-source']['available'] is (version != '2021.1')
    if version == '2021.1':
        assert 'multi-read derivation' in contract['outputs']['active-source']['reason']
    assert contract['outputs']['converted-codec']['available'] is (version in {'2024.1', '2025.1'})
    assert contract['outputs']['converted-trimmed-duration']['available'] is (version == '2025.1')
    root = Path(gateway.__file__).parents[1]
    graph = json.loads((root / 'resources/manifest' / version / 'definitions.json').read_text())
    source = json.loads((root / 'references/semantic' / version / 'query-related-output-sources.json').read_text())
    assert source['wwise_build'] == contract['source']['wwise_build'] == graph['wwise_build']
    assert source['version'] == contract['source']['version'] == version
    assert contract['source']['page_sha256'] == {
        '2021.1': '87b10aecdd13083c0a2d75fb0659119fbe08ba54ea5bfa85f041576033074ac4',
        '2022.1': 'cd882bee048d8168fe61f8eb88f8dbe9e228e30b67521ddcedaf7538c2fa8cd6',
        '2023.1': '0a1e191ebd047c4e18cbf1a019cdb8d9d2a5014eeb7cbd3a6090f90bbac0ca74',
        '2024.1': 'a030dec88e3b956cea1a9595980ddd54e4d40e646453e87198605b60a065ac20',
        '2025.1': '99bac5a48b124535cf2d11b9d010ba21ffda60e8321f558c35f0eeeba51fe201',
    }[version]
    assert 'Separate each expression with a dot' in source['chain_rules'][0]['html']
    assert 'followed by a value expression' in source['chain_rules'][1]['html']
    assert contract['chain_html_lines'] == [rule['html_line'] for rule in source['chain_rules']]
    for name, detail in contract['outputs'].items():
        if not detail['available']:
            continue
        # Public output detail supplies the exact existing native descriptor;
        # these source guards do not synthesize a return allowlist from enums.
        if name in {'volume-db', 'pitch-cents', 'output-bus'}:
            assert name in source['property_terminal_proof']
            continue
        if version == '2021.1' and name == 'original-file-path':
            native = 'originalWavFilePath'
        else:
            from wwise_waapi.object_query_outputs import QUERY_BUSINESS_OUTPUTS
            native = QUERY_BUSINESS_OUTPUTS[name][0]
        assert native in source['documented_descriptors'], (version, name, native)
        assert native in source['documented_descriptors'][native]['html']
    definitions = graph['documents']['waapi_definitions.json']['definitions']
    assert contract['result_schema'] == definitions['objectReturn']['patternProperties']
    assert task.calls == []


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('relation,native', [('parent', 'parent'), ('owner', 'owner'), ('work-unit', 'workunit')])
def test_singleton_relations_share_core_and_reference_terminals_without_metadata(tmp_path, version, relation, native):
    task = RelatedTask(tmp_path, version)
    task.rows = [task.row]
    identity = {**PARENT, 'future': {'enabled': False, 'amount': 0}}
    task.row.update({native: identity, native + '.notes': 'related notes', native + '.OutputBus': OTHER_PARENT})
    code, result = task.run('query-object', '--exact-id', SOUND,
        '--include-related', relation, 'notes', '--include-related', relation, 'output-bus')
    assert code == 0, result
    assert result['agent_result'][0]['related'] == {relation: {
        'object': identity, 'notes': 'related notes', 'output_bus': OTHER_PARENT}}
    assert {uri for uri, _, _ in task.calls} == {'ak.wwise.core.getInfo', 'ak.wwise.core.object.get'}


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('case', ['relation-absent', 'field-absent', 'null', 'zero', 'malformed-identity'])
def test_related_presence_and_identity_do_not_invent_values_or_authority(tmp_path, version, case):
    task = RelatedTask(tmp_path, version)
    task.rows = [task.row]
    if case != 'relation-absent':
        task.row['parent'] = PARENT if case != 'malformed-identity' else {'id': 'not-a-guid', 'name': 'Parent'}
    if case != 'field-absent':
        task.row['parent.@Volume'] = None if case == 'null' else 0
    code, result = task.run('query-object', '--exact-id', SOUND, '--include-related', 'parent', 'volume-db')
    assert code == 0, result
    row = result['agent_result'][0]
    assert row['id'] == SOUND and 'identity_completeness' not in row
    parent = row['related']['parent']
    if case == 'field-absent':
        assert 'volume_db' not in parent
        assert parent['unavailable_fields'] == ['volume_db']
    else:
        assert parent['volume_db'] is (None if case == 'null' else 0)
    if case in {'relation-absent', 'malformed-identity'}:
        assert parent['identity_completeness']['complete'] is False
        assert parent['identity_completeness']['mutation_authority'] is False
        assert result['native_observation']['return'][0] == task.row
    if case == 'relation-absent':
        assert 'object' not in parent and parent['unavailable_fields'] == ['object']
    assert list(result)[-1] == 'agent_result'


@pytest.mark.parametrize('version', VERSIONS)
def test_related_fixed_outputs_coexist_with_root_metadata_and_deduplicate_identity_helper(tmp_path, version):
    task = RelatedTask(tmp_path, version)
    task.rows = [task.row]
    task.row.update({'@Volume': 0, 'parent': PARENT, 'parent.@Volume': -12})
    code, result = task.run('query-object', '--exact-id', SOUND, '--include', 'parent',
        '--include-field', 'Volume', '--include-related', 'parent', 'volume-db')
    assert code == 0, result
    row = result['agent_result'][0]
    assert row['parent'] == PARENT and row['properties'] == {'Volume': 0}
    assert row['related']['parent'] == {'object': PARENT, 'volume_db': -12}
    assert task.calls[-1][2]['return'] == ['id', 'name', 'type', 'path', 'parent', 'parent.@Volume', '@Volume']


@pytest.mark.parametrize('version', VERSIONS)
def test_related_fixed_projection_keeps_advanced_bound_and_literal_return_scope(tmp_path, version):
    task = RelatedTask(tmp_path, version)
    task.rows[0].update({'parent': PARENT, 'parent.@Volume': -12})
    task.rows[1].update({'parent': OTHER_PARENT, 'parent.@Volume': 0})
    code, result = task.run('query-object', '--advanced-waql', 'from type Sound orderby name',
        '--max-results', '2', '--include-related', 'parent', 'volume-db', '--platform', 'Mac', '--language', 'SFX')
    assert code == 0, result
    assert [row['id'] for row in result['agent_result']] == [SOUND, OTHER]
    assert task.calls[-1][1] == {'waql': 'from type Sound orderby name take 2'}
    assert task.calls[-1][2] == {'return': ['id', 'name', 'type', 'path', 'parent', 'parent.@Volume'], 'platform': 'Mac', 'language': 'SFX'}
    assert list(result)[-1] == 'agent_result'


@pytest.mark.parametrize('version,name,native,value', [
    ('2021.1', 'original-file-path', 'originalWavFilePath', '/original.wav'),
    ('2022.1', 'active-source', 'activeSource', OTHER_PARENT),
    ('2023.1', 'original-relative-file-path', 'originalRelativeFilePath', 'file.wav'),
    ('2024.1', 'converted-codec', 'convertedCodec', 'Vorbis'),
    ('2025.1', 'converted-trimmed-duration', 'convertedTrimmedDuration', 0),
])
def test_version_specific_documented_descriptors_use_the_same_related_record(tmp_path, version, name, native, value):
    task = RelatedTask(tmp_path, version)
    task.rows = [task.row]
    task.row.update({'parent': PARENT, 'parent.' + native: value})
    code, result = task.run('query-object', '--exact-id', SOUND, '--include-related', 'parent', name)
    assert code == 0, result
    assert result['agent_result'][0]['related']['parent'] == {'object': PARENT, name.replace('-', '_'): value}
    assert task.calls[-1][2]['return'] == ['id', 'name', 'type', 'path', 'parent', 'parent.' + native]


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('options', [
    ['--include-related', 'children', 'volume-db'],
    ['--include-related', 'parent.parent', 'volume-db'],
    ['--include-related', '@OutputBus', 'volume-db'],
    ['--include-related', 'parent', '@Volume'],
    ['--include-related', 'parent', 'parent.name'],
    ['--include-related', 'parent', 'notes;name'],
    ['--include-related', 'parent', 'volume-db', '--include-related', 'parent', 'volume-db'],
    ['--include-related', 'parent', 'source-duration'],
    ['--include-related', 'parent', 'volume-db', '--view', 'sound-routing-diagnostics'],
])
def test_related_declarations_reject_raw_or_unproven_composition_before_transport(tmp_path, version, options):
    task = RelatedTask(tmp_path, version)
    code, rejected = task.run('query-object', '--exact-id', SOUND, *options)
    assert code == 2, rejected
    assert task.calls == []


@pytest.mark.parametrize('version', VERSIONS)
def test_related_pairs_share_the_existing_total_fixed_output_budget(tmp_path, version):
    from tests.unit.test_object_query_result_pages import gateway
    task = RelatedTask(tmp_path, version)
    options = ['--include-related', 'parent', 'volume-db'] * gateway.MAX_QUERY_BUSINESS_OUTPUTS
    code, rejected = task.run('query-object', '--exact-id', SOUND, '--include', 'notes', *options)
    assert code == 2, rejected
    assert str(gateway.MAX_QUERY_BUSINESS_OUTPUTS) in rejected['message'] and 'total' in rejected['message']
    assert task.calls == []


def test_derived_2021_related_active_source_is_an_explicit_pretransport_boundary(tmp_path):
    task = RelatedTask(tmp_path, '2021.1')
    code, rejected = task.run('query-object', '--exact-id', SOUND, '--include-related', 'parent', 'active-source')
    assert code == 2 and 'multi-read derivation' in rejected['message'], rejected
    assert task.calls == []


@pytest.mark.parametrize('version', ('2023.1', '2024.1', '2025.1'))
@pytest.mark.parametrize('value', [[], [OTHER_PARENT, {**PARENT, 'future': {'active': False, 'value': 0}}]])
def test_singleton_related_list_valued_terminal_is_preserved_without_list_composition(tmp_path, version, value):
    task = RelatedTask(tmp_path, version)
    task.rows = [task.row]
    task.row.update({'parent': PARENT, 'parent.stateGroups': value})
    code, result = task.run('query-object', '--exact-id', SOUND, '--include-related', 'parent', 'state-groups')
    assert code == 0, result
    assert result['agent_result'][0]['related']['parent'] == {'object': PARENT, 'state_groups': value}
    assert {uri for uri, _, _ in task.calls} == {'ak.wwise.core.getInfo', 'ak.wwise.core.object.get'}


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('change', ['none', 'value', 'relation', 'session'])
def test_related_result_pages_retain_scope_and_reject_changed_observation(tmp_path, version, change):
    task = RelatedTask(tmp_path, version)
    task.rows = [task.row]
    text = '音声' * 12000
    task.row.update({'parent': PARENT, 'parent.notes': text})
    code, result = task.run('query-object', '--exact-id', SOUND, '--include-related', 'parent', 'notes',
        '--platform', 'Mac', '--language', 'SFX')
    assert code == 0 and result['status'] == 'partial', result
    argv = result['agent_result']['next_command']['gateway_argv']
    if change != 'none':
        if change == 'value':
            task.row['parent.notes'] += '!'
        elif change == 'relation':
            task.row['parent'] = OTHER_PARENT
        else:
            task.info['sessionId'] = '{33333333-3333-3333-3333-333333333333}'
        before = len(task.calls)
        code, rejected = task.run(*argv)
        assert code == 2 and rejected['error_code'] == 'QUERY_RESULT_CONTINUATION_CHANGED', rejected
        assert rejected.get('agent_result') is None
        if change == 'session':
            assert not any(uri.endswith('object.get') and args != {'waql': 'from type Project take 1'}
                for uri, args, _ in task.calls[before:])
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
        if entry['pointer'] == '/objects/0/related/parent/notes') == text
    assert [entry['value'] for entry in entries if entry['pointer'] == '/objects/0/related/parent/object/id'] == [PARENT['id']]
    options = [options for uri, args, options in task.calls
        if uri.endswith('object.get') and args != {'waql': 'from type Project take 1'}]
    assert options and all(value == {'return': ['id', 'name', 'type', 'path', 'parent', 'parent.notes'],
        'platform': 'Mac', 'language': 'SFX'} for value in options)
