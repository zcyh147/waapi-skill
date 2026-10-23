"""Closed scalar metadata conditions through the public Gateway/native seam."""
import copy
import json
import re
from pathlib import Path

from tests.unit.test_query_list_functions import SequenceTask, SOUND, OTHER, SOUND_CLASS


class FieldTask(SequenceTask):
    def __init__(self, tmp_path, version='2025.1'):
        super().__init__(tmp_path, version)
        source = json.loads((Path(__file__).parents[1]/'fixtures/metadata-conditions/query-pitch-five-versions.json').read_text())
        self.metadata[SOUND_CLASS]['Pitch'] = copy.deepcopy(source['samples'][version]['metadata'])

    def call(self, uri, args=None, options=None):
        waql = (args or {}).get('waql','')
        if uri.endswith('object.get') and waql != 'from type Project take 1':
            self.calls.append((uri,args,options))
            ids = re.findall(r'"(\{[0-9A-Fa-f-]{36}\})"',waql.split(' where ')[0])
            if ' select ' in waql:
                owner, = ids
                relation = re.search(r' select (\w+)',waql).group(1)
                refs = self.objects[owner].get(relation) or []
                rows = [{**self.objects[r['id']],**r} for r in refs]
            else:
                rows = [self.objects[identity] for identity in ids] if ids else list(self.rows)
            # A small transport simulator for the exact emitted WHERE/skip/take
            # domain. It does not invoke the production condition compiler.
            pieces = re.split(r' (where|skip|take) ',waql)
            for index in range(1,len(pieces),2):
                operation,expression = pieces[index:index+2]
                if operation == 'skip': rows = rows[int(expression):]
                elif operation == 'take': rows = rows[:int(expression)]
                else: rows = [row for row in rows if self.native_matches(row,expression)]
            return {'return':[self.projection(row,options['return']) for row in rows]}
        return super().call(uri,args,options)

    @classmethod
    def native_matches(cls,row,expression):
        # Strip only fully enclosing parentheses, then split at depth zero.
        while expression.startswith('('):
            depth = 0
            for index,c in enumerate(expression):
                if c == '(': depth += 1
                elif c == ')': depth -= 1
                if depth == 0: break
            if index != len(expression)-1: break
            expression = expression[1:-1]
        for operator in (' or ',' and '):
            depth = 0
            for index,c in enumerate(expression):
                if c == '(': depth += 1
                elif c == ')': depth -= 1
                if depth == 0 and expression.startswith(operator,index):
                    left,right = expression[:index],expression[index+len(operator):]
                    return (cls.native_matches(row,left) or cls.native_matches(row,right)) if operator == ' or ' else (cls.native_matches(row,left) and cls.native_matches(row,right))
        match = re.fullmatch(r'([\w@]+) (=|!=|<=|>=|<|>|:) (.+)',expression)
        assert match,expression
        field,operator,literal = match.groups(); value = json.loads(literal)
        if field not in row: return False
        actual = row[field]
        if operator == ':': return any(word.casefold().startswith(value.casefold()) for word in actual.split())
        if operator == '=': return type(actual) is type(value) and actual == value
        if operator == '!=': return actual != value
        if operator == '<=': return actual <= value
        if operator == '>=': return actual >= value
        if operator == '<': return actual < value
        return actual > value


def test_two_owners_keep_roots_and_return_pitch_matching_members_and_count(tmp_path):
    task = FieldTask(tmp_path)
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2',
        '--include-related', 'children', 'volume-db',
        '--include-related', 'children', 'matching-field', 'ordinary', 'Voice Pitch', 'at-most', '-500', 'volume-db',
        '--include-related-field', 'children', 'matching-field', 'ordinary', 'Voice Pitch', 'at-most', '-500', 'Pitch',
        '--include-related', 'children', 'matching-field', 'ordinary', 'Voice Pitch', 'at-most', '-500', 'count')
    assert code == 0, result
    assert len(result['agent_result']) == 2
    for root in result['agent_result']:
        assert len(root['related']['children']['items']) == 2
        selected, count = root['related']['projections']
        assert [item['object']['id'] for item in selected['items']] == [SOUND]
        assert selected['items'][0]['volume_db'] == -12
        assert selected['items'][0]['properties'] == {'Pitch': -560}
        assert count['value'] == 1
    assert any('where @Pitch <= -500' in args.get('waql', '') for uri, args, _ in task.calls if uri.endswith('object.get'))
    assert list(result)[-1] == 'agent_result'


def test_root_field_condition_applies_before_final_root_limit(tmp_path):
    task = FieldTask(tmp_path)
    task.rows = [task.members[OTHER],task.members[SOUND]]
    code,result = task.run('query-object','--kind','all-sounds','--max-results','1',
        '--where-field','ordinary','Voice Pitch','at-most','-500','--include','pitch-cents','--detail')
    assert code == 0,json.dumps(result,ensure_ascii=False)
    assert [row['id'] for row in result['agent_result']] == [SOUND]
    assert result['agent_result'][0]['pitch_cents'] == -560
    query = result['semantic_preview']['envelope']['args']['waql']
    assert 'where @Pitch <= -500 take 1' in query
    assert result['related_scope_binding']['root_field_conditions']['source_complete'] is True
    assert result['related_scope_binding']['root_field_conditions']['final_root_limit_applied_after_predicates'] is True

import pytest
from tests.unit.test_object_query_result_pages import VERSIONS, gateway
from tests.unit.test_query_related_paths import REFERENCE_CLASS


@pytest.mark.parametrize('version', VERSIONS)
def test_all_field_reducers_share_scalar_binding_and_false_empty_semantics(tmp_path,version):
    task = FieldTask(tmp_path,version)
    code,result = task.run('query-object','--kind','all-sounds','--max-results','2',
        '--include-related','children','any-match-field','ordinary','Voice Pitch','at-most','-500',
        '--include-related','children','all-match-field','ordinary','Voice Pitch','at-most','-500',
        '--include-related','children','take','0','all-match-field','ordinary','Voice Pitch','at-most','-500')
    assert code == 0,json.dumps(result,ensure_ascii=False)
    assert [[r['value'] for r in root['related']['projections']] for root in result['agent_result']] == [[True,False,False],[True,False,False]]


@pytest.mark.parametrize('version', VERSIONS)
def test_related_unknown_predicate_preserves_root_and_other_views_without_fabricating_matches(tmp_path,version):
    task = FieldTask(tmp_path,version)
    task.members[OTHER]['classId'] = REFERENCE_CLASS
    task.metadata[OTHER] = {}
    code,result = task.run('query-object','--kind','all-sounds','--max-results','2',
        '--include-related','children','volume-db',
        '--include-related','children','matching-field','ordinary','Voice Pitch','at-most','-500','count')
    assert code == 0,json.dumps(result,ensure_ascii=False)
    for root in result['agent_result']:
        assert len(root['related']['children']['items']) == 2
        projection, = root['related']['projections']
        assert 'value' not in projection and 'items' not in projection
        assert projection['unavailable_predicates'][0]['condition']['meaning'] == 'Voice Pitch'
        assert projection['unavailable_predicates'][0]['unresolved_scope']['scope'] == {'object':OTHER}


@pytest.mark.parametrize('version', VERSIONS)
def test_root_unknown_field_stops_without_claiming_unfiltered_roots_match(tmp_path,version):
    task = FieldTask(tmp_path,version)
    task.rows = [task.members[SOUND],task.members[OTHER]]
    task.members[OTHER]['classId'] = REFERENCE_CLASS
    task.metadata[OTHER] = {}
    code,result = task.run('query-object','--kind','all-sounds','--max-results','1',
        '--where-field','ordinary','Voice Pitch','at-most','-500')
    assert code == 2,result
    assert result['error_code'] == 'QUERY_FIELD_CONDITION_UNAVAILABLE'
    assert result.get('agent_result') is None


@pytest.mark.parametrize('version',VERSIONS)
def test_offline_field_condition_schema_pins_where_sources_and_shows_limits_and_remaining_modes(tmp_path,version):
    task = FieldTask(tmp_path,version)
    code,result = task.run('query-schema')
    assert code == 0,json.dumps(result,ensure_ascii=False)
    contract = result['field_conditions']
    assert contract['modes'] == ['ordinary']
    assert contract['root_limit_order'] == 'native field predicates before final root take'
    assert contract['source']['version'] == version
    assert contract['source']['domain'] == 'query-predicates-and-selection'
    assert 'metadata' in contract['authority'] and 'runtime SDK' in contract['source_boundary']
    assert not task.calls


@pytest.mark.parametrize('version',VERSIONS)
@pytest.mark.parametrize('source',['broad','advanced','relationship'])
def test_root_and_related_predicates_share_actual_heterogeneous_scope_without_borrowing_tokens(tmp_path,version,source):
    task = FieldTask(tmp_path,version)
    task.members[OTHER].update(classId=REFERENCE_CLASS,**{'@AlternatePitch':0})
    task.metadata[REFERENCE_CLASS] = {'AlternatePitch':{'name':'AlternatePitch','type':'int32','display':{'name':'Voice Pitch'}}}
    if source == 'relationship':
        args = ['--exact-id',task.rows[0]['id'],'--relationship','children']
    else:
        task.rows = [task.members[OTHER],task.members[SOUND]]
        args = ['--kind','all-sounds'] if source == 'broad' else ['--advanced-waql','from type Sound']
    code,result = task.run('query-object',*args,'--max-results','1',
        '--where-field','ordinary','Voice Pitch','at-most','-500','--include','volume-db','--detail')
    assert code == 0,json.dumps(result,ensure_ascii=False)
    assert [row['id'] for row in result['agent_result']] == [SOUND]
    scopes = result['related_scope_binding']['root_field_conditions']['scopes']
    assert {entry['scope']['classId'] for entry in scopes} == {SOUND_CLASS,REFERENCE_CLASS}
    assert {entry['selected']['name'] for entry in scopes} == {'Pitch','AlternatePitch'}


@pytest.mark.parametrize('version',VERSIONS)
def test_related_field_stage_keeps_finite_prefix_before_later_condition_and_concat_origin(tmp_path,version):
    task = FieldTask(tmp_path,version)
    task.rows[0]['children'] = [task.reference(OTHER),task.reference(SOUND)]+[task.reference(SOUND)]*4095
    task.rows[1]['children'] = [task.reference(OTHER)]
    code,result = task.run('query-object','--kind','all-sounds','--max-results','2',
        '--include-related','combine','children','and','self','end','take','1','matching-field','ordinary','Voice Pitch','at-most','-500','count',
        '--include-related','children','take','1','matching-field','ordinary','Voice Pitch','at-most','-500','count')
    assert code == 0,json.dumps(result,ensure_ascii=False)
    assert [r['value'] for r in result['agent_result'][0]['related']['projections']] == [0,0]
    assert [r['value'] for r in result['agent_result'][1]['related']['projections']] == [0,0]


@pytest.mark.parametrize('version',VERSIONS)
@pytest.mark.parametrize('case',['boolean','zero','outside-range','fractional-int','reference-kind','unknown-type'])
def test_live_scalar_types_choose_comparisons_without_mutation_assignment_validation(tmp_path,version,case):
    task = FieldTask(tmp_path,version)
    task.rows = [task.members[SOUND]]
    meaning,comparison,value = 'Voice Pitch','at-most','-500'
    expected = 0
    if case == 'boolean':
        task.metadata[SOUND_CLASS]['Pitch']['type'] = 'bool'; task.members[SOUND]['@Pitch'] = False
        comparison,value = 'is','false'; expected = 1
    elif case == 'zero': comparison,value,expected = 'is','-560',1
    elif case == 'outside-range': value,expected = '50000',1
    elif case == 'fractional-int': value,expected = '1.5',None
    elif case == 'reference-kind':
        task.metadata[SOUND_CLASS]['Pitch'] = copy.deepcopy(__import__('tests.unit.test_query_related_paths',fromlist=['REFERENCE_PACKET']).REFERENCE_PACKET['metadata'])
        task.metadata[SOUND_CLASS]['Pitch']['name']='Pitch'; expected=None
    elif case == 'unknown-type': task.metadata[SOUND_CLASS]['Pitch']['type']='opaque'; expected=None
    code,result = task.run('query-object','--kind','all-sounds','--max-results','1','--where-field','ordinary',meaning,comparison,value)
    if expected is None:
        assert code == 2,result
        assert result.get('agent_result') is None
    else:
        assert code == 0,json.dumps(result,ensure_ascii=False)
        assert len(result['agent_result']) == expected


def test_2021_derived_active_source_uses_filtered_source_before_final_limit(tmp_path):
    from tests.unit import test_typed_query_construction as legacy
    client,ids = legacy._legacy_multi_sound_client(tmp_path)
    original = client.call
    observed_owners = {}
    def native(uri,args=None,options=None):
        query = (args or {}).get('waql','')
        requested = re.findall(r'"(\{[0-9A-Fa-f-]{36}\})"',query)
        if uri.endswith('object.get') and query.startswith('from object ') and ' select ' not in query and requested and set(requested)<=set(observed_owners):
            client.calls.append((uri,args,options))
            return {'return':[{field:row[field] for field in options['return'] if field in row} for row in (observed_owners[identity] for identity in requested)]}
        result = original(uri,args,options)
        if uri.endswith('object.get') and query.startswith('from type Sound'):
            values = {ids['sound']:0,ids['second_sound']:-7.25}
            rows = result['return']
            observed_owners.update({row['id']:{**row,'@Volume':values[row['id']]} for row in rows})
            if '@Volume' in options['return']:
                for row in rows: row['@Volume'] = values[row['id']]
            if 'where @Volume <= -1.0' in query:
                rows = [row for row in rows if values[row['id']] <= -1]
            take = re.search(r' take (\d+)$',query)
            if take: rows = rows[:int(take.group(1))]
            result = {'return':rows}
        return result
    client.call = native
    code,result = legacy.gateway.execute_gateway(['query-object','--kind','all-sounds','--max-results','1',
        '--where-field','ordinary','Volume','at-most','-1','--platform','Mac','--language','SFX',
        '--include','active-source','--detail'],env=legacy._env(tmp_path,'2021.1'),client_factory=lambda _:client)
    assert code == 0,json.dumps(result,ensure_ascii=False)
    assert result['agent_result'][0]['id'] == ids['second_sound']
    assert result['agent_result'][0]['active_source'] == {'id':ids['second_active'],'name':'Gamma'}
    assert result['active_source_resolution']['sound_count'] == 1
    assert result['related_scope_binding']['root_field_conditions']['final_root_limit_applied_after_predicates'] is True
    owner_queries = [args['waql'] for uri,args,_ in client.calls if uri.endswith('object.get') and 'where @Volume' in args.get('waql','')]
    assert owner_queries == ['from type Sound where @Volume <= -1.0 take 1']*2


@pytest.mark.parametrize('version',VERSIONS)
@pytest.mark.parametrize('lane',['root','related'])
@pytest.mark.parametrize('change',['none','metadata','typed-value'])
def test_field_condition_pages_preserve_all_values_and_reject_metadata_or_typed_predicate_drift(tmp_path,version,lane,change):
    task = FieldTask(tmp_path,version)
    text = '音声'*16000
    for member in task.members.values(): member['notes']=text
    if lane == 'root':
        task.rows = [task.members[SOUND],task.members[OTHER]]
        args = ['--where-field','ordinary','Voice Pitch','at-most','0','--include','notes']
    else:
        args = ['--include-related','children','matching-field','ordinary','Voice Pitch','at-most','0','first','notes']
    code,result = task.run('query-object','--kind','all-sounds','--max-results','2',*args,'--detail')
    assert code == 0 and result['status']=='partial',json.dumps(result,ensure_ascii=False)
    first = result
    if change == 'metadata': task.metadata[SOUND_CLASS]['Pitch']['type']='Real64'
    elif change == 'typed-value': task.members[OTHER]['@Pitch']=False
    if change != 'none':
        code,rejected = task.run(*result['agent_result']['next_command']['gateway_argv'])
        assert code == 2 and rejected['error_code']=='QUERY_RESULT_CONTINUATION_CHANGED',rejected
        return
    entries=[]
    for _ in range(160):
        page=result['agent_result'];entries.extend(page['entries'])
        assert page['entries_encoding']=='json-pointer-entries'
        assert list(result)[-1]=='agent_result'
        assert len(json.dumps(result,ensure_ascii=False,indent=2).encode())<=32768
        if page['projection_complete']:break
        code,result=task.run(*page['next_command']['gateway_argv'])
        assert code == 0,result
    else: pytest.fail('field query did not finish its bounded projection')
    pointer='/objects/0/notes' if lane=='root' else '/objects/0/related/projections/0/items/0/notes'
    assert ''.join(entry['value'] for entry in entries if entry['pointer']==pointer)==text
    assert first['agent_result']['page']['offset']==0


@pytest.mark.parametrize('version',VERSIONS)
@pytest.mark.parametrize('lane',['root','related'])
def test_empty_scope_establishes_no_field_authority_and_needs_no_discovery(tmp_path,version,lane):
    task=FieldTask(tmp_path,version)
    if lane=='root':
        task.rows=[]
        args=['--where-field','ordinary','Unknown Meaning','is','0']
    else:
        for row in task.rows: row['children']=[]
        args=['--include-related','children','matching-field','ordinary','Unknown Meaning','is','0','count']
    code,result=task.run('query-object','--kind','all-sounds','--max-results','2',*args)
    assert code == 0,result
    assert not any('getProperty' in uri for uri,_,_ in task.calls)
    if lane=='root': assert result['agent_result']==[]
    else: assert [root['related']['projections'][0]['value'] for root in result['agent_result']]==[0,0]


@pytest.mark.parametrize('version',VERSIONS)
@pytest.mark.parametrize('fault',['duplicate','extra','missing-scope'])
def test_native_condition_batches_reject_unassociated_selected_or_scope_identities(tmp_path,version,fault):
    task=FieldTask(tmp_path,version)
    original=task.call
    def bad(uri,args=None,options=None):
        result=original(uri,args,options)
        query=(args or {}).get('waql','')
        if uri.endswith('object.get') and query.startswith('from object '):
            if fault=='missing-scope' and 'where' not in query and options['return']==['id','name','type','path','classId']:
                return {'return':[]}
            if 'where @Pitch' in query:
                if fault=='duplicate': result['return']*=2
                elif fault=='extra': result['return'].append(copy.deepcopy(task.rows[0]))
        return result
    task.call=bad
    code,result=task.run('query-object','--kind','all-sounds','--max-results','2',
        '--include-related','children','matching-field','ordinary','Voice Pitch','at-most','-500','count')
    assert code == 2,result
    assert result['error_code']=='QUERY_FIELD_CONDITION_BATCH'
    assert result.get('agent_result') is None


@pytest.mark.parametrize('version',VERSIONS)
def test_complete_root_scope_limit_is_not_the_requested_final_root_limit_or_hidden_prefix(tmp_path,version):
    from wwise_waapi.identity_limits import MULTI_IDENTITY_READ_MAX_IDS
    task=FieldTask(tmp_path,version)
    task.rows=[task.members[SOUND]]*(MULTI_IDENTITY_READ_MAX_IDS+1)
    code,result=task.run('query-object','--kind','all-sounds','--max-results','1',
        '--where-field','ordinary','Voice Pitch','at-most','-500')
    assert code == 2 and result['error_code']=='QUERY_FIELD_CONDITION_LIMIT',result
    assert not any('getProperty' in uri for uri,_,_ in task.calls)


@pytest.mark.parametrize('version',VERSIONS)
@pytest.mark.parametrize('values',[
    ['ordinary','@Pitch','is','0'],['ordinary','Pitch','<=','0'],
    ['override-source','Pitch','is','0'],['ordinary','Pitch()','is','0']])
def test_field_condition_rejects_raw_grammar_and_unproven_modes_before_transport(tmp_path,version,values):
    task=FieldTask(tmp_path,version)
    code,result=task.run('query-object','--kind','all-sounds','--max-results','1','--where-field',*values)
    assert code==2,result
    assert not task.calls


@pytest.mark.parametrize('version',VERSIONS)
def test_field_source_sections_and_native_metadata_are_exact_versioned_primary_shapes(tmp_path,version):
    import hashlib
    task=FieldTask(tmp_path,version)
    code,result=task.run('query-schema')
    assert code==0,result
    source=result['field_conditions']['source']
    base=Path(gateway.__file__).parents[1]
    definitions=base/'resources/manifest'/version/'definitions.json'
    assert source['definitions_sha256']==hashlib.sha256(definitions.read_bytes()).hexdigest()
    for section in source['sections'].values():
        assert section['html_sha256']==hashlib.sha256(section['html'].encode()).hexdigest()
    assert 'Compares two numerical values' in source['sections']['comparison_operators']['html']
    assert 'When using @' in source['sections']['property_value']['html']
    assert task.metadata[SOUND_CLASS]['Pitch']['type']=='int32'
    assert task.metadata[SOUND_CLASS]['Pitch']['restriction']=={'type':'range','min':-2400,'max':2400}
    assert not task.calls


@pytest.mark.parametrize('version',VERSIONS)
def test_root_and_related_conditions_share_scoped_authority_and_actual_read_packets(tmp_path,version):
    from wwise_waapi.canonical import canonical_sha256
    task=FieldTask(tmp_path,version)
    task.members[SOUND]['children']=[task.reference(OTHER)]
    task.members[OTHER]['children']=[task.reference(SOUND)]
    task.rows=[task.members[SOUND],task.members[OTHER]]
    directory=tmp_path/'predicate-packets'; directory.mkdir()
    task.env['WWISE_EVIDENCE_DIR']=str(directory)
    code,result=task.run('query-object','--kind','all-sounds','--max-results','2',
        '--where-field','ordinary','Voice Pitch','at-most','0',
        '--include-related','children','matching-field','ordinary','Voice Pitch','at-most','0','volume-db','--detail')
    assert code==0,json.dumps(result,ensure_ascii=False)
    assert [row['related']['projections'][0]['items'][0]['volume_db'] for row in result['agent_result']]==[0,-12]
    assert len([uri for uri,_,_ in task.calls if uri.endswith('getPropertyAndReferenceNames')])==1
    proof=result['related_scope_binding']
    assert proof['root_field_conditions']['source_complete'] is True
    assert result['related_read_evidence']
    for read in result['related_read_evidence']:
        packet=json.loads(Path(read['call']['evidence_path']).read_text())
        assert canonical_sha256(packet['result'])==read['result_sha256']
        assert read['api']==packet['api']
    assert {uri for uri,_,_ in task.calls} <= {'ak.wwise.core.getInfo','ak.wwise.core.object.get',
        'ak.wwise.core.object.getPropertyAndReferenceNames','ak.wwise.core.object.getPropertyInfo'}
    assert list(result)[-1]=='agent_result'


@pytest.mark.parametrize('version',VERSIONS)
@pytest.mark.parametrize('kind',['unknown-class-kind','ambiguous-class'])
def test_scalar_conditions_use_exact_object_fallback_only_for_insufficient_class_kind(tmp_path,version,kind):
    task=FieldTask(tmp_path,version)
    observed=copy.deepcopy(task.metadata[SOUND_CLASS]['Pitch'])
    task.rows=[task.members[SOUND]]
    task.metadata[SOUND]={'Pitch':observed}
    if kind=='unknown-class-kind':
        task.metadata[SOUND_CLASS]['Pitch'].update(type='',restriction={})
    else:
        task.metadata[SOUND_CLASS]['AnotherPitch']={**copy.deepcopy(observed),'name':'AnotherPitch'}
    code,result=task.run('query-object','--kind','all-sounds','--max-results','1',
        '--where-field','ordinary','Voice Pitch','at-most','-500','--detail')
    object_lookups=[args for uri,args,_ in task.calls if uri.endswith('getPropertyAndReferenceNames') and 'object' in args]
    if kind=='unknown-class-kind':
        assert code==0,result
        assert [row['id'] for row in result['agent_result']]==[SOUND]
        assert object_lookups==[{'object':SOUND}]
        assert result['related_scope_binding']['root_field_conditions']['scopes'][0]['scope']=={'object':SOUND}
    else:
        assert code==2 and result['error_code']=='QUERY_FIELD_CONDITION_UNAVAILABLE',result
        assert object_lookups==[]


@pytest.mark.parametrize('version',VERSIONS)
def test_string_field_matching_uses_native_word_prefix_semantics_not_python_substring(tmp_path,version):
    task=FieldTask(tmp_path,version)
    task.rows=[task.members[OTHER],task.members[SOUND]]
    task.metadata[SOUND_CLASS]['Label']={'name':'Label','type':'string','display':{'name':'User Label'}}
    task.members[SOUND]['@Label']='Heel Step'
    task.members[OTHER]['@Label']='Wheel'
    code,result=task.run('query-object','--kind','all-sounds','--max-results','1',
        '--where-field','ordinary','User Label','matches-text','Heel')
    assert code==0,result
    assert [row['id'] for row in result['agent_result']]==[SOUND]


@pytest.mark.parametrize('version',VERSIONS)
def test_root_field_alias_duplicates_and_existing_declaration_budget_fail_closed(tmp_path,version):
    task=FieldTask(tmp_path,version)
    task.rows=[task.members[SOUND]]
    code,result=task.run('query-object','--kind','all-sounds','--max-results','1',
        '--where-field','ordinary','Pitch','at-most','0',
        '--where-field','ordinary','Voice Pitch','at-most','0')
    assert code==2 and 'duplicate' in result['message'],result
    fresh=FieldTask(tmp_path/'budget',version)
    argv=['query-object','--kind','all-sounds','--max-results','1']
    for number in range(gateway.MAX_QUERY_CUSTOM_OUTPUTS+1):
        argv+=['--where-field','ordinary','Voice Pitch','at-most',str(number)]
    code,result=fresh.run(*argv)
    assert code==2 and 'budget' in result['message'],result
    assert not fresh.calls


def test_original_file_match_owned_query_cannot_silently_ignore_field_predicate(tmp_path):
    task=FieldTask(tmp_path)
    code,result=task.run('query-object','--match-original-file-path','/owned/Audio.wav','--max-results','1000',
        '--where-field','ordinary','Voice Pitch','is','0')
    assert code==2 and '--where-field' in result['message'],result
    assert not task.calls


@pytest.mark.parametrize('version',VERSIONS)
@pytest.mark.parametrize('lane',['root','related'])
@pytest.mark.parametrize('presence',['absent','null'])
def test_absent_predicate_value_is_unknown_not_a_silent_nonmatch(tmp_path,version,lane,presence):
    task=FieldTask(tmp_path,version)
    if presence=='absent': task.members[OTHER].pop('@Pitch')
    else: task.members[OTHER]['@Pitch']=None
    if lane=='root':
        task.rows=[task.members[SOUND],task.members[OTHER]]
        args=['--where-field','ordinary','Voice Pitch','at-most','0']
    else:
        args=['--include-related','children','matching-field','ordinary','Voice Pitch','at-most','0','count']
    code,result=task.run('query-object','--kind','all-sounds','--max-results','2',*args)
    if lane=='root':
        assert code==2 and result['error_code']=='QUERY_FIELD_CONDITION_UNAVAILABLE',result
        assert result.get('agent_result') is None
    else:
        assert code==0,result
        for row in result['agent_result']:
            record,=row['related']['projections']
            assert 'value' not in record
            assert record['unavailable_predicates'][0]['condition']['meaning']=='Voice Pitch'


@pytest.mark.parametrize('version',VERSIONS)
def test_review_advanced_matching_roots_keep_explicit_final_cap(tmp_path,version):
    task=FieldTask(tmp_path,version)
    task.rows=[task.members[OTHER],task.members[SOUND]]
    code,result=task.run('query-object','--advanced-waql','from type Sound','--max-results','1',
        '--where-field','ordinary','Voice Pitch','at-most','0','--detail')
    assert code==0,result
    assert [row['id'] for row in result['agent_result']]==[OTHER]
    assert result['semantic_preview']['envelope']['args']['waql'].endswith(' take 1')


@pytest.mark.parametrize('version',VERSIONS)
@pytest.mark.parametrize('lane',['root','matching-field','any-match-field','all-match-field'])
def test_review_partial_display_discovery_cannot_certify_scalar_condition(tmp_path,version,lane):
    from wwise_waapi.metadata_discovery import MAX_METADATA_DISCOVERY_FALLBACK_DETAIL_SCAN
    task=FieldTask(tmp_path,version)
    last=MAX_METADATA_DISCOVERY_FALLBACK_DETAIL_SCAN
    task.metadata[SOUND_CLASS]={f'P{index:03}':{'name':f'P{index:03}','type':'int32',
        'display':{'name':'Tone Offset' if index in {0,last} else f'Unrelated {index}'}}
        for index in range(last+1)}
    for member in task.members.values():member['@P000']=0
    if lane=='root':
        task.rows=[task.members[SOUND],task.members[OTHER]]
        args=['--where-field','ordinary','Tone Offset','is','0']
    else:
        args=['--include-related','children','volume-db',
            '--include-related','children',lane,'ordinary','Tone Offset','is','0']
        if lane=='matching-field':args+=['count']
    code,result=task.run('query-object','--kind','all-sounds','--max-results','2',*args)
    if lane=='root':
        assert code==2 and result['error_code']=='QUERY_FIELD_CONDITION_UNAVAILABLE',result
    else:
        assert code==0,result
        for root in result['agent_result']:
            assert len(root['related']['children']['items'])==2
            projection,=root['related']['projections']
            assert 'value' not in projection and 'items' not in projection
            assert projection['unavailable_predicates'][0]['unresolved_scope']['complete'] is False
    assert not any('where @P000' in (args or {}).get('waql','') for uri,args,_ in task.calls)


@pytest.mark.parametrize('version',VERSIONS)
@pytest.mark.parametrize('continuation',[False,True])
def test_review_removed_source_member_still_existing_has_owned_drift_error(tmp_path,version,continuation):
    task=FieldTask(tmp_path,version)
    task.rows=[task.members[SOUND],task.members[OTHER]]
    argv=['query-object','--kind','all-sounds','--max-results','2',
        '--where-field','ordinary','Voice Pitch','at-most','0','--include','notes','--detail']
    if continuation:
        for row in task.members.values():row['notes']='音声'*16000
        code,first=task.run(*argv)
        assert code==0 and first['status']=='partial',first
        argv=first['agent_result']['next_command']['gateway_argv']
    original=task.call
    def leave_source(uri,args=None,options=None):
        result=original(uri,args,options)
        if uri.endswith('object.get') and (args or {}).get('waql','').startswith('from type Sound where @Pitch'):
            task.rows=[task.members[SOUND]]
        return result
    task.call=leave_source
    code,result=task.run(*argv)
    assert OTHER in task.objects  # The object survives; only source membership changed.
    expected='QUERY_RESULT_CONTINUATION_CHANGED' if continuation else 'RELATED_QUERY_SCOPE_CHANGED'
    assert code==2 and result['error_code']==expected,result


@pytest.mark.parametrize('version',VERSIONS)
@pytest.mark.parametrize('fault',['absent','null','changed','boolean','float'])
def test_review_selected_predicate_packet_must_agree_with_observed_value(tmp_path,version,fault):
    task=FieldTask(tmp_path,version)
    original=task.call
    def changed_selection(uri,args=None,options=None):
        result=original(uri,args,options)
        if uri.endswith('object.get') and 'where @Pitch' in (args or {}).get('waql',''):
            for row in result['return']:
                if fault=='absent':row.pop('@Pitch')
                else:row['@Pitch']={'null':None,'changed':0,'boolean':False,'float':-560.0}[fault]
        return result
    task.call=changed_selection
    code,result=task.run('query-object','--kind','all-sounds','--max-results','2',
        '--include-related','children','matching-field','ordinary','Voice Pitch','at-most','-500','count')
    assert code==2 and result['error_code']=='RELATED_QUERY_SCOPE_CHANGED',result


@pytest.mark.parametrize('version',VERSIONS)
def test_review_selected_value_disagreement_on_related_page_is_continuation_drift(tmp_path,version):
    task=FieldTask(tmp_path,version)
    for row in task.members.values():row['notes']='音声'*16000
    code,first=task.run('query-object','--kind','all-sounds','--max-results','2',
        '--include-related','children','matching-field','ordinary','Voice Pitch','at-most','0','first','notes','--detail')
    assert code==0 and first['status']=='partial',first
    original=task.call
    def changed_selection(uri,args=None,options=None):
        result=original(uri,args,options)
        if uri.endswith('object.get') and 'where @Pitch' in (args or {}).get('waql',''):
            result['return'][0]['@Pitch']=None
        return result
    task.call=changed_selection
    code,result=task.run(*first['agent_result']['next_command']['gateway_argv'])
    assert code==2 and result['error_code']=='QUERY_RESULT_CONTINUATION_CHANGED',result
