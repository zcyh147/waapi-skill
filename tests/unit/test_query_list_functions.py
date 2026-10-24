"""Closed per-owner list selections through the public query Gateway."""
import copy
import re
import json

from tests.unit.test_query_related_lists import ListTask, SOUND, OTHER, SOUND_CLASS


class SequenceTask(ListTask):
    def call(self, uri, args=None, options=None):
        waql = (args or {}).get('waql', '')
        if uri.endswith('object.get') and (' select ' in waql or ' where ' in waql):
            self.calls.append((uri, args, options))
            assert not re.search(r'\bskip 0\b', waql)
            assert all('.take(' not in field and '.first(' not in field for field in options['return'])
            ids = re.findall(r'\{[0-9A-Fa-f-]{36}\}', waql)
            if ' select ' in waql:
                owner, = ids
                relation = re.search(r' select (\w+)', waql).group(1)
                refs = self.objects[owner].get(relation) or []
                rows = [{**self.objects[r['id']], **r} for r in refs]
            else:
                rows = [self.objects[identity] for identity in ids]
            transforms = r' (skip|take) (\d+)| (?:where|and) ([\w@]+) (=|<=|>=|:) ("(?:\\.|[^"\\])*"|true|false|-?\d+(?:\.\d+)?)'
            for match in re.finditer(transforms,waql):
                transform, number, field, operator, literal = match.groups()
                if transform:
                    count = int(number)
                    rows = rows[count:] if transform == 'skip' else rows[:count]
                else:
                    value = json.loads(literal)
                    def matches(row):
                        if field not in row: return False
                        actual = row[field]
                        if operator == '=': return type(actual) is type(value) and actual == value
                        if operator == '<=': return actual <= value
                        if operator == '>=': return actual >= value
                        return value.casefold() in actual.casefold()
                    rows = [row for row in rows if matches(row)]
            return {'return': [self.projection(row,options['return']) for row in rows]}
        return super().call(uri,args,options)


def test_two_owners_keep_full_children_and_distinct_first_take_views_with_live_pitch(tmp_path):
    task = SequenceTask(tmp_path)
    code, result = task.run('query-object','--kind','all-sounds','--max-results','2',
        '--include-related','children','volume-db',
        '--include-related','children','first','volume-db',
        '--include-related-field','children','first','Pitch',
        '--include-related','children','take','1','volume-db')
    assert code == 0, result
    left, right = result['agent_result']
    assert [m['object']['id'] for m in left['related']['children']['items']] == [SOUND, OTHER]
    assert [m['object']['id'] for m in right['related']['children']['items']] == [OTHER, SOUND]
    first, take = left['related']['projections']
    assert first['spec'] == {'source':'children','stages':[{'selection':'first'}]}
    assert first['items'][0]['object']['id'] == SOUND
    assert first['items'][0]['volume_db'] == -12
    assert first['items'][0]['properties'] == {'Pitch':-560}
    assert take['spec'] == {'source':'children','stages':[{'selection':'take','count':1}]}
    assert len(take['items']) == 1
    assert right['related']['projections'][0]['items'][0]['properties'] == {'Pitch':0}
    assert list(result)[-1] == 'agent_result'

import pytest
from tests.unit.test_object_query_result_pages import VERSIONS


@pytest.mark.parametrize('version', VERSIONS)
def test_ordered_selection_stages_and_derived_reducers_keep_empty_semantics(tmp_path, version):
    task = SequenceTask(tmp_path, version)
    code, result = task.run('query-object','--kind','all-sounds','--max-results','2',
        '--include-related','children','last','volume-db',
        '--include-related','children','at','0','volume-db',
        '--include-related','children','skip','1','take','1','volume-db',
        '--include-related','children','take','1','skip','1','volume-db',
        '--include-related','children','count',
        '--include-related','children','any',
        '--include-related','children','take','0','any')
    assert code == 0, result
    records = result['agent_result'][0]['related']['projections']
    assert [r['items'][0]['object']['id'] if r['items'] else None for r in records[:4]] == [OTHER,SOUND,OTHER,None]
    assert [r['value'] for r in records[4:]] == [2,True,False]
    assert all(r['derivation'] == 'gateway-business-sequence' for r in records)
    assert list(result)[-1] == 'agent_result'

@pytest.mark.parametrize('version', VERSIONS)
def test_matching_and_reducers_use_exact_disclosed_business_conditions_not_native_strings(tmp_path, version):
    task = SequenceTask(tmp_path, version)
    code, result = task.run('query-object','--kind','all-sounds','--max-results','2',
        '--include-related','children','matching','name-is','First','count',
        '--include-related','children','any-match','volume-db-at-most','-1',
        '--include-related','children','all-match','kind-is','sound',
        '--include-related','children','take','0','all-match','kind-is','sound')
    assert code == 0, result
    for root in result['agent_result']:
        assert [r['value'] for r in root['related']['projections']] == [1,True,True,False]
    reads = [a['waql'] for u,a,_ in task.calls if u.endswith('object.get') and ' select ' in a.get('waql','')]
    assert any('where name = "First"' in query for query in reads)
    assert any('where @Volume <= -1' in query for query in reads)

@pytest.mark.parametrize('version', VERSIONS)
def test_combination_preserves_arm_order_duplicate_occurrences_and_nested_selection(tmp_path, version):
    task = SequenceTask(tmp_path,version)
    task.members[SOUND]['children'] = [task.reference(OTHER)]
    task.members[OTHER]['children'] = []
    code,result = task.run('query-object','--kind','all-sounds','--max-results','2',
        '--include-related','combine','children','and','children','end','take','3','volume-db',
        '--include-related-field','children','first','children','first','Pitch')
    assert code == 0,result
    left = result['agent_result'][0]
    combined = left['related']['projections'][0]
    assert [item['object']['id'] for item in combined['items']] == [SOUND,OTHER,SOUND]
    assert [item['origin']['arm'] for item in combined['items']] == [0,0,1]
    assert [item['origin']['occurrence'] for item in combined['items']] == [0,1,0]
    nested = left['related']['projections'][1]['items'][0]['related']['projections'][0]
    assert nested['items'][0]['properties'] == {'Pitch':0}

from pathlib import Path
from tests.unit.test_object_query_result_pages import gateway

@pytest.mark.parametrize('version', VERSIONS)
def test_offline_sequence_contract_pins_domain_sources_and_discloses_business_derivation(tmp_path, version):
    task = SequenceTask(tmp_path,version)
    code,result = task.run('query-schema')
    assert code == 0,result
    contract = result['related_outputs']['list_members']['sequences']
    assert contract['versions'] == list(VERSIONS)
    assert contract['result_location'] == 'related.projections'
    assert contract['selection_tokens'] == ['matching','matching-field','first','last','at','skip','take']
    assert contract['reducer_tokens'] == ['count','any','any-match','all-match','any-match-field','all-match-field']
    assert 'Gateway' in contract['derivation'] and 'native function-return equality' in contract['derivation']
    source = json.loads((Path(gateway.__file__).parents[1]/'references/semantic'/version/'query-list-output-sources.json').read_text())
    sections = source['sequence_sources']
    assert sections['query_transforms']['domain'] == 'query-selection'
    assert 'select' in sections['query_transforms']['html']
    assert contract['source']['wwise_build'] == source['wwise_build']
    if version in {'2023.1','2024.1','2025.1'}:
        assert sections['list_functions']['domain'] == 'query-predicates-and-selection'
        assert 'Returns false if empty' in sections['list_functions']['html']
        assert sections['concat_return']['domain'] == 'return-expression'
    else:
        assert sections['list_functions'] is None
        assert sections['concat_return'] is None
    assert not task.calls

@pytest.mark.parametrize('version', VERSIONS)
def test_fixed_windows_and_existence_push_before_full_membership_ceiling(tmp_path, version):
    task = SequenceTask(tmp_path,version)
    task.rows[0]['children'] = [task.reference(SOUND)] * 4097
    task.rows[1]['children'] = []
    code,result = task.run('query-object','--kind','all-sounds','--max-results','2',
        '--include-related-field','children','first','Pitch',
        '--include-related','children','at','4096','volume-db',
        '--include-related','children','any-match','name-is','First')
    assert code == 0,result
    records = result['agent_result'][0]['related']['projections']
    by_kind = {record['spec'].get('reducer',{}).get('operation') or record['spec']['stages'][0]['selection']:record for record in records}
    assert by_kind['first']['items'][0]['properties']['Pitch'] == -560
    assert by_kind['at']['items'][0]['volume_db'] == -12
    assert by_kind['any-match']['value'] is True
    reads = [a['waql'] for u,a,_ in task.calls if u.endswith('object.get') and ' select ' in a.get('waql','')]
    assert reads and all(query.endswith('take 1') for query in reads)

@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('tokens', [
    ['children','take','-1','volume-db'], ['children','at','01','volume-db'],
    ['children.take(2)','volume-db'], ['children','matching','@Volume','0','count'],
    ['children','matching','kind-is','Sound','count'],
    ['combine','children','end','volume-db'], ['combine','self','and','end','volume-db'],
    ['children','all','volume-db'],
])
def test_closed_sequence_rejects_bad_grammar_and_parallel_condition_aliases_before_transport(tmp_path,version,tokens):
    task = SequenceTask(tmp_path,version)
    code,result = task.run('query-object','--exact-id',SOUND,'--include-related',*tokens)
    assert code == 2,result
    assert not task.calls

@pytest.mark.parametrize('version', VERSIONS)
def test_projection_terminal_binding_preserves_heterogeneous_unavailability_and_refinement(tmp_path, version):
    from tests.unit.test_query_related_paths import REFERENCE_CLASS
    task = SequenceTask(tmp_path,version)
    task.members[OTHER]['classId'] = REFERENCE_CLASS
    task.metadata[OTHER] = {}
    code,result = task.run('query-object','--kind','all-sounds','--max-results','2',
        '--include-related-field','children','first','Pitch')
    assert code == 0,result
    left,right = result['agent_result']
    assert left['related']['projections'][0]['items'][0]['properties'] == {'Pitch':-560}
    unknown = right['related']['projections'][0]['items'][0]
    assert 'properties' not in unknown
    assert unknown['unavailable_field_requests'][0]['requested_option'] == '--include-related-field'
    assert unknown['unavailable_field_requests'][0]['meaning'] == 'Pitch'

@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('change',['none','value','membership','metadata'])
def test_selected_projection_pages_are_lossless_and_seal_scope_values_and_spec(tmp_path,version,change):
    task = SequenceTask(tmp_path,version)
    text = '音声'*6000
    for member in task.members.values(): member['notes'] = text
    code,result = task.run('query-object','--advanced-waql','from type Sound','--max-results','2',
        '--include-related','children','first','notes',
        '--include-related-field','children','first','Pitch')
    assert code == 0 and result['status'] == 'partial', result
    if change == 'value': task.members[SOUND]['@Pitch'] = -561
    elif change == 'membership': task.rows[0]['children'].reverse()
    elif change == 'metadata': task.metadata[SOUND_CLASS]['Pitch']['type'] = 'Real64'
    if change != 'none':
        code,rejected = task.run(*result['agent_result']['next_command']['gateway_argv'])
        assert code == 2 and rejected['error_code'] == 'QUERY_RESULT_CONTINUATION_CHANGED',rejected
        return
    entries = []
    while True:
        page = result['agent_result']
        entries.extend(page['entries'])
        assert len(json.dumps(result,ensure_ascii=False,indent=2).encode()) <= 32768
        assert list(result)[-1] == 'agent_result'
        if page['projection_complete']: break
        code,result = task.run(*page['next_command']['gateway_argv'])
        assert code == 0,result
    fragments = [entry for entry in entries if entry['pointer'] == '/objects/0/related/projections/0/items/0/notes']
    assert ''.join(entry['value'] for entry in fragments) == text

@pytest.mark.parametrize('version', VERSIONS)
def test_concat_existence_stops_at_proven_match_without_materializing_later_large_arms(tmp_path,version):
    task = SequenceTask(tmp_path,version)
    task.rows[0]['children'] = [task.reference(SOUND)]*4097
    task.rows[1]['children'] = []
    code,result = task.run('query-object','--kind','all-sounds','--max-results','2',
        '--include-related','combine','self','and','children','end','any',
        '--include-related','combine','self','and','children','end','any-match','name-is','First')
    assert code == 0,result
    assert [r['value'] for r in result['agent_result'][0]['related']['projections']] == [True,True]
    assert [r['value'] for r in result['agent_result'][1]['related']['projections']] == [True,False]

@pytest.mark.parametrize('version', VERSIONS)
def test_combined_reference_arms_bind_actual_member_class_and_preserve_value_modes(tmp_path,version):
    from tests.unit.test_query_related_paths import REFERENCE_CLASS, TARGET, LOCAL
    task = SequenceTask(tmp_path,version)
    for member in task.members.values():
        member.update(classId=REFERENCE_CLASS,PlaylistObject=TARGET,**{'@PlaylistObject':LOCAL})
    task.objects[TARGET['id']] = {**TARGET,'type':'Sound','path':r'\Sounds\Resolved','classId':SOUND_CLASS,'@Pitch':0,'@Volume':-5}
    task.objects[LOCAL['id']] = {**LOCAL,'type':'Sound','path':r'\Sounds\Local','classId':SOUND_CLASS,'@Pitch':-4,'@Volume':0}
    code,result = task.run('query-object','--kind','all-sounds','--max-results','2',
        '--include-related','children','first','combine','reference','Playlist Object','and','local-reference','Playlist Object','end','volume-db')
    assert code == 0,result
    members = result['agent_result'][0]['related']['projections'][0]['items'][0]['related']['projections'][0]['items']
    assert [item['object']['id'] for item in members] == [TARGET['id'],LOCAL['id']]
    assert [item['volume_db'] for item in members] == [-5,0]
    assert len([args for uri,args,_ in task.calls if uri.endswith('getPropertyAndReferenceNames') and args == {'classId':REFERENCE_CLASS}]) == 1
    assert all(uri in {'ak.wwise.core.getInfo','ak.wwise.core.getProjectInfo','ak.wwise.core.object.get','ak.wwise.core.object.getPropertyInfo','ak.wwise.core.object.getPropertyAndReferenceNames'} for uri,_,_ in task.calls)

@pytest.mark.parametrize('version', VERSIONS)
def test_empty_advanced_sequence_result_establishes_no_discovered_field_authority(tmp_path,version):
    task = SequenceTask(tmp_path,version)
    task.rows = []
    code,result = task.run('query-object','--advanced-waql','from type Sound','--max-results','2',
        '--include-related-field','children','first','Pitch')
    assert code == 0 and result['agent_result'] == [],result
    assert not any(uri.endswith(('getPropertyInfo','getPropertyAndReferenceNames')) for uri,_,_ in task.calls)

@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('invalid',['missing','duplicate','extra','noncanonical'])
def test_selected_grouped_values_require_an_exact_canonical_member_batch_on_every_lane(tmp_path,version,invalid):
    class Broken(SequenceTask):
        def call(self,uri,args=None,options=None):
            result = super().call(uri,args,options)
            if uri.endswith('object.get') and 'from object ' in (args or {}).get('waql','') and ' select ' not in args['waql'] and '@Volume' in options['return']:
                rows = result['return']
                if invalid == 'missing': rows.clear()
                elif invalid == 'duplicate': rows.append(copy.deepcopy(rows[0]))
                elif invalid == 'extra': rows[0]['id'] = OTHER if rows[0]['id'] == SOUND else SOUND
                else: rows[0]['id'] = 'not-a-guid'
            return result
    task = Broken(tmp_path,version)
    code,result = task.run('query-object','--kind','all-sounds','--max-results','2',
        '--include-related','children','first','volume-db')
    assert code == 2,result
    assert result['error_code'] in {'RELATED_QUERY_MEMBER_BATCH','RELATED_QUERY_RESULT_SHAPE'}
    assert result.get('agent_result') is None

@pytest.mark.parametrize('version', VERSIONS)
def test_selected_member_extension_typed_drift_is_rejected_without_pruning_native_maps(tmp_path,version):
    class Changing(SequenceTask):
        memberships = 0
        def call(self,uri,args=None,options=None):
            if uri.endswith('object.get') and ' select ' in (args or {}).get('waql',''): self.memberships += 1
            return super().call(uri,args,options)
        def projection(self,row,expressions):
            value = super().projection(row,expressions)
            if row['id'] == SOUND: value['future'] = {'related':{},'value':True if self.memberships >= 2 else 1}
            return value
    task = Changing(tmp_path,version)
    code,result = task.run('query-object','--kind','all-sounds','--max-results','2',
        '--include-related','children','first','volume-db')
    assert code == 2 and result['error_code'] == 'RELATED_QUERY_SCOPE_CHANGED',result

@pytest.mark.parametrize('version', VERSIONS)
def test_concat_finite_prefix_survives_a_later_filter_above_full_membership_cap(tmp_path,version):
    task = SequenceTask(tmp_path,version)
    task.rows[0]['children'] = [task.reference(SOUND)]*4097
    task.rows[1]['children'] = []
    code,result = task.run('query-object','--kind','all-sounds','--max-results','2',
        '--include-related','combine','children','and','self','end','take','2','matching','kind-is','sound','volume-db')
    assert code == 0,result
    selected = result['agent_result'][0]['related']['projections'][0]['items']
    assert [member['object']['id'] for member in selected] == [SOUND,SOUND]
    assert [member['origin'] for member in selected] == [{'arm':0,'occurrence':0},{'arm':0,'occurrence':1}]
    assert [member['volume_db'] for member in selected] == [-12,-12]
    owner_queries = [args['waql'] for uri,args,_ in task.calls if uri.endswith('object.get') and ' select ' in args.get('waql','')]
    assert owner_queries and all(query.endswith('take 2') for query in owner_queries)
    assert all(' where ' not in query for query in owner_queries)

@pytest.mark.parametrize('version', VERSIONS)
def test_custom_meaning_matching_internal_reducer_marker_still_discovers_and_returns_field(tmp_path,version):
    task = SequenceTask(tmp_path,version)
    meaning = '__sequence_value__'
    task.metadata[SOUND_CLASS][meaning] = {'name':meaning,'type':'int32'}
    task.members[SOUND]['@'+meaning] = 0
    task.members[OTHER]['@'+meaning] = -3
    code,result = task.run('query-object','--kind','all-sounds','--max-results','2',
        '--include-related-field','children',meaning)
    assert code == 0,result
    assert any(uri.endswith('getPropertyAndReferenceNames') for uri,_,_ in task.calls)
    fields = result['agent_result'][0]['related']['children']['items']
    assert [item['properties'][meaning] for item in fields] == [0,-3]

@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('stages,expected,reads',[
    (['take','2','matching','name-is','First'],[SOUND],True),
    (['take','2','last','matching','name-is','First'],[],True),
    (['take','0','matching','name-is','First'],[],False),
    (['take','2','skip','2','matching','name-is','First'],[],False),
    (['take','2','matching','name-is','First','take','0'],[],False),
])
def test_concat_prefix_later_stages_keep_order_and_empty_never_enumerates_arms(tmp_path,version,stages,expected,reads):
    task = SequenceTask(tmp_path,version)
    task.rows[0]['children'] = [task.reference(SOUND),task.reference(OTHER)]+[task.reference(SOUND)]*4095
    task.rows[1]['children'] = []
    code,result = task.run('query-object','--kind','all-sounds','--max-results','2',
        '--include-related','combine','children','and','self','end',*stages,'volume-db',
        '--include-related-field','combine','children','and','self','end',*stages,'Pitch')
    assert code == 0,result
    projection = result['agent_result'][0]['related']['projections'][0]
    assert [member['object']['id'] for member in projection['items']] == expected
    if expected:
        assert projection['items'][0]['properties'] == {'Pitch':-560}
        assert projection['items'][0]['origin'] == {'arm':0,'occurrence':0}
    owner_queries = [args['waql'] for uri,args,_ in task.calls if uri.endswith('object.get') and ' select ' in args.get('waql','')]
    assert bool(owner_queries) is reads
    assert all(' where ' not in query and query.endswith('take 2') for query in owner_queries)
    if not reads:
        assert not any(uri.endswith(('getPropertyInfo','getPropertyAndReferenceNames')) for uri,_,_ in task.calls)

@pytest.mark.parametrize('version', VERSIONS)
def test_bounded_concat_prefix_member_values_trace_actual_selection_and_guid_packets(tmp_path,version):
    from tests.unit.test_query_related_outputs import PARENT
    from wwise_waapi.canonical import canonical_sha256
    task = SequenceTask(tmp_path,version)
    task.rows[0]['children'] = [task.reference(SOUND)]*4097
    evidence = tmp_path/'prefix-packets'
    evidence.mkdir()
    task.env['WWISE_EVIDENCE_DIR'] = str(evidence)
    code,result = task.run('query-object','--exact-id',PARENT['id'],
        '--include-related','combine','children','and','self','end','take','2','matching','kind-is','sound','volume-db','--detail')
    assert code == 0,result
    items = result['agent_result'][0]['related']['projections'][0]['items']
    assert [member['volume_db'] for member in items] == [-12,-12]
    proof = result['related_scope_binding']
    assert proof['sequence_source']['version'] == version
    assert 'no native function-return equality' in proof['sequence_semantics']
    membership, values = [], []
    for read in result['related_read_evidence']:
        assert (read['api'],read['args'],read['options']) in task.calls
        packet = json.loads(Path(read['call']['evidence_path']).read_text())
        assert packet['api'] == read['api']
        assert canonical_sha256(packet['result']) == read['result_sha256']
        if ' select children ' in read['args'].get('waql',''):
            membership.append(packet['result']['return'])
        elif '@Volume' in read['options'].get('return',[]):
            values.extend(packet['result']['return'])
    assert membership and all([member['id'] for member in sequence] == [SOUND,SOUND] for sequence in membership)
    assert values and all(member['id'] == SOUND and member['@Volume'] == -12 for member in values)
    assert list(result)[-1] == 'agent_result'
