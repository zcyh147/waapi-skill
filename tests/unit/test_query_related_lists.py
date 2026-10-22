"""Root-preserving related member records through the public Gateway."""
from __future__ import annotations

import copy
import re

from tests.unit.test_query_related_paths import PathTask, SOUND_CLASS, SOUND, OTHER, PARENT, OTHER_PARENT


class ListTask(PathTask):
    def __init__(self, tmp_path, version='2025.1'):
        super().__init__(tmp_path, version)
        self.members = {
            SOUND: {'id': SOUND, 'name': 'First', 'type': 'Sound', 'path': r'\Sounds\First',
                    'classId': SOUND_CLASS, '@Volume': -12, '@Pitch': -560},
            OTHER: {'id': OTHER, 'name': 'Second', 'type': 'Sound', 'path': r'\Sounds\Second',
                    'classId': SOUND_CLASS, '@Volume': 0, '@Pitch': 0},
        }
        self.rows = [
            {**PARENT, 'type': 'RandomSequenceContainer', 'path': r'\Sounds\ContainerA',
                'children': [self.reference(SOUND), self.reference(OTHER)]},
            {**OTHER_PARENT, 'type': 'RandomSequenceContainer', 'path': r'\Sounds\ContainerB',
                'children': [self.reference(OTHER), self.reference(SOUND)]},
        ]
        self.objects = {**self.members, **{row['id']: row for row in self.rows}}

    def reference(self, identity):
        return {key: copy.deepcopy(self.members[identity][key]) for key in ('id', 'name')}

    @staticmethod
    def comma_fields(value):
        fields, depth, start = [], 0, 0
        for index, character in enumerate(value):
            if character == '{': depth += 1
            if character == '}': depth -= 1
            if character == ',' and depth == 0:
                fields.append(value[start:index].strip()); start = index + 1
        fields.append(value[start:].strip())
        return fields

    def projection(self, row, expressions):
        result = {}
        for expression in expressions:
            source, separator, alias = expression.partition(' as ')
            key = alias if separator else source
            if '.{' in source:
                relation, nested = source.split('.{', 1)
                assert nested.endswith('}'), expression
                if relation not in row: continue
                value = row[relation]
                if value is None:
                    result[key] = None
                else:
                    assert isinstance(value, list), value
                    result[key] = [self.projection(self.objects[reference['id']], self.comma_fields(nested[:-1])) for reference in value]
            elif source in row:
                result[key] = copy.deepcopy(row[source])
        return result

    def call(self, uri, args=None, options=None):
        if uri.endswith('object.get') and args != {'waql': 'from type Project take 1'}:
            self.calls.append((uri, args, options))
            ids = args.get('from', {}).get('id')
            if ids is None:
                ids = re.findall(r'\{[0-9A-Fa-f-]{36}\}', args.get('waql', ''))
            rows = [self.objects[identity] for identity in ids] if ids else self.rows
            return {'return': [self.projection(row, options['return']) for row in rows]}
        return super().call(uri, args, options)


def test_broad_list_projection_keeps_each_root_and_its_ordered_members_with_fixed_and_custom_values(tmp_path):
    task = ListTask(tmp_path)
    code, result = task.run('query-object', '--kind', 'all-sounds', '--max-results', '2',
        '--include-related', 'children', 'volume-db', '--include-related-field', 'children', 'Pitch')
    assert code == 0, result
    rows = result['agent_result']
    assert [row['id'] for row in rows] == [PARENT['id'], OTHER_PARENT['id']]
    assert [[item['object']['id'] for item in row['related']['children']['items']] for row in rows] == [[SOUND, OTHER], [OTHER, SOUND]]
    first, second = rows[0]['related']['children']['items']
    assert first == {'object': {'id': SOUND, 'name': 'First', 'type': 'Sound', 'path': r'\Sounds\First'}, 'volume_db': -12, 'properties': {'Pitch': -560}}
    assert second['volume_db'] == 0 and second['properties']['Pitch'] == 0
    assert [args for uri, args, _ in task.calls if uri.endswith('getPropertyAndReferenceNames')] == [{'classId': SOUND_CLASS}]
    data_reads = [options['return'] for uri, _, options in task.calls if uri.endswith('object.get')]
    assert 'children.{id,name,type,path,classId,@Volume,@Pitch} as related0' in data_reads[-1]
    assert not any(uri.endswith(('setProperty', 'setReference')) for uri, _, _ in task.calls)
    assert list(result)[-1] == 'agent_result'

import hashlib
import json
from pathlib import Path
import pytest
from tests.unit.test_object_query_result_pages import VERSIONS, gateway
from tests.unit.test_query_related_paths import REFERENCE_CLASS, REFERENCE_PACKET, TARGET, LOCAL


def options():
    return ['--kind','all-sounds','--max-results','2','--include-related','children','volume-db','--include-related-field','children','Pitch']


@pytest.mark.parametrize('version', VERSIONS)
def test_all_versions_share_ordered_grouping_and_disclose_actual_strategy_and_packet_associations(tmp_path, version):
    task = ListTask(tmp_path, version)
    code, result = task.run('query-object', *options(), '--detail', '--platform', 'Platform', '--language', 'Language')
    assert code == 0, result
    assert result['agent_result'][0]['related']['children']['items'][0]['properties']['Pitch'] == -560
    strategy = 'gateway-guid-grouped-reads' if version in {'2021.1','2022.1'} else 'native-composed-members'
    proof = result['related_scope_binding']
    assert proof['strategy'] == strategy and proof['atomic_snapshot'] is False
    assert proof['scopes'][0]['scope'] == {'classId': SOUND_CLASS}
    assert len([args for uri,args,_ in task.calls if uri.endswith('getPropertyAndReferenceNames')]) == 1
    assert result['related_read_evidence']
    for read in result['related_read_evidence']:
        assert {'api','args','options','result_sha256','call'} <= read.keys()
        assert read['call']['evidence_path']
    for uri,args,native_options in task.calls:
        if uri.endswith('object.get'):
            assert native_options.get('platform') == 'Platform' and native_options.get('language') == 'Language'
    assert list(result)[-1] == 'agent_result'


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('presence', ['absent','null','empty','duplicate','extensions','field-absent'])
def test_list_and_member_presence_extensions_and_duplicate_occurrences_are_lossless(tmp_path, version, presence):
    task = ListTask(tmp_path, version)
    if presence == 'absent': task.rows[0].pop('children')
    elif presence == 'null': task.rows[0]['children'] = None
    elif presence == 'empty': task.rows[0]['children'] = []
    elif presence == 'duplicate': task.rows[0]['children'] = [task.reference(SOUND)] * 2
    elif presence == 'extensions':
        task.members[SOUND]['@Pitch'] = {'related':{},'future':[False,0,None]}
    else:
        task.members[SOUND].pop('@Pitch')
    code, result = task.run('query-object', *options())
    assert code == 0, result
    context = result['agent_result'][0]['related']['children']
    if presence == 'absent': assert context == {'unavailable_fields':['items']}
    elif presence == 'null': assert context == {'items':None}
    elif presence == 'empty': assert context == {'items':[]}
    elif presence == 'duplicate': assert [item['object']['id'] for item in context['items']] == [SOUND,SOUND]
    elif presence == 'extensions': assert context['items'][0]['properties']['Pitch'] == {'related':{},'future':[False,0,None]}
    else: assert context['items'][0]['unavailable_fields'] == ['properties.Pitch']


@pytest.mark.parametrize('version', VERSIONS)
def test_nested_lists_and_singleton_paths_keep_independent_member_identity(tmp_path, version):
    task = ListTask(tmp_path, version)
    for member in task.members.values():
        member['children'] = [task.reference(OTHER)]
        member['parent'] = PARENT
        member['parent.classId'] = SOUND_CLASS
        member['parent.@Volume'] = -5
    code, result = task.run('query-object', '--kind','all-sounds','--max-results','2',
        '--include-related','children','children','pitch-cents',
        '--include-related','children','parent','volume-db',
        '--include-related','parent','volume-db')
    assert code == 0, result
    member = result['agent_result'][0]['related']['children']['items'][0]
    assert member['object']['id'] == SOUND
    assert member['related']['children']['items'][0]['object']['id'] == OTHER
    assert member['related']['children']['items'][0]['pitch_cents'] == 0
    assert member['related']['parent']['object'] == PARENT
    assert member['related']['parent']['volume_db'] == -5


@pytest.mark.parametrize('version', VERSIONS)
def test_heterogeneous_member_metadata_never_borrows_another_class_token_and_keeps_root(tmp_path, version):
    task = ListTask(tmp_path, version)
    task.members[OTHER]['classId'] = REFERENCE_CLASS
    task.metadata[OTHER] = {}
    code, result = task.run('query-object', *options(), '--detail')
    assert code == 0, result
    members = result['agent_result'][0]['related']['children']['items']
    assert members[0]['properties'] == {'Pitch':-560}
    assert 'properties' not in members[1]
    assert members[1]['unavailable_field_requests'][0]['meaning'] == 'Pitch'
    scopes = [item['scope'] for item in result['related_scope_binding']['scopes']]
    assert {'classId':REFERENCE_CLASS} not in scopes  # Class no-match falls back to actual GUID.
    assert {'object':OTHER} in scopes


@pytest.mark.parametrize('version', VERSIONS)
def test_member_reference_modes_and_hops_use_actual_class_and_preserve_extensions(tmp_path, version):
    task = ListTask(tmp_path, version)
    for member in task.members.values():
        member['classId'] = REFERENCE_CLASS
        member.update({'PlaylistObject':TARGET,'@PlaylistObject':LOCAL,
            'PlaylistObject.classId':SOUND_CLASS,'PlaylistObject.@Volume':-2})
    code, result = task.run('query-object','--kind','all-sounds','--max-results','2',
        '--include-related-field','children','Playlist Object',
        '--include-related-local-reference','children','Playlist Object',
        '--include-related','children','reference','Playlist Object','volume-db')
    assert code == 0, result
    member = result['agent_result'][0]['related']['children']['items'][0]
    assert member['references']['PlaylistObject'] == TARGET
    assert member['local_references']['PlaylistObject'] == LOCAL
    assert member['related']['references']['PlaylistObject']['object'] == TARGET
    assert member['related']['references']['PlaylistObject']['volume_db'] == -2


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('change', ['typed-class','membership','root-order'])
def test_preparation_rejects_type_exact_scope_or_membership_drift(tmp_path, version, change):
    class Changing(ListTask):
        count = 0
        def call(self, uri,args=None,options=None):
            if uri.endswith('object.get') and args != {'waql':'from type Project take 1'}:
                self.count += 1
                if self.count == (4 if version in {'2021.1','2022.1'} else 3):
                    if change == 'typed-class': self.members[SOUND]['classId'] = True
                    elif change == 'membership': self.rows[0]['children'].reverse()
                    else: self.rows.reverse()
            return super().call(uri,args,options)
    task = Changing(tmp_path,version)
    # 1 and True compare equal in Python; observation must still reject the drift.
    task.members[SOUND]['classId'] = 1
    task.metadata[1] = task.metadata[SOUND_CLASS]
    code,result = task.run('query-object',*options())
    assert code == 2 and result['error_code'] == 'RELATED_QUERY_SCOPE_CHANGED', result
    assert result.get('agent_result') is None


@pytest.mark.parametrize('version', ['2021.1','2022.1'])
@pytest.mark.parametrize('invalid', ['missing','duplicate','extra','malformed'])
def test_grouped_member_batch_requires_exact_canonical_identity_set(tmp_path,version,invalid):
    class Invalid(ListTask):
        def call(self,uri,args=None,options=None):
            result = super().call(uri,args,options)
            if uri.endswith('object.get') and 'from object ' in args.get('waql',''):
                if invalid == 'missing': result['return'].pop()
                elif invalid == 'duplicate': result['return'][1] = copy.deepcopy(result['return'][0])
                elif invalid == 'extra': result['return'][1]['id'] = TARGET['id']
                else: result['return'][0]['id'] = 'bad'
            return result
    task = Invalid(tmp_path,version)
    code,result = task.run('query-object',*options())
    assert code == 2 and result['error_code'] in {'RELATED_QUERY_MEMBER_BATCH','RELATED_QUERY_RESULT_SHAPE'}, result
    assert result.get('agent_result') is None


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('source', ['advanced','empty'])
def test_list_queries_keep_existing_advanced_bounds_and_empty_result_semantics(tmp_path,version,source):
    task = ListTask(tmp_path,version)
    if source == 'empty': task.rows = []
    args = ['--advanced-waql','from type Sound','--max-results','2'] if source == 'advanced' else ['--kind','all-sounds','--max-results','2']
    code,result = task.run('query-object',*args,'--include-related-field','children','Pitch')
    assert code == 0, result
    if source == 'empty':
        assert result['agent_result'] == []
        assert not any(uri.endswith('getPropertyAndReferenceNames') for uri,_,_ in task.calls)
    else: assert result['agent_result'][0]['related']['children']['items'][0]['properties']['Pitch'] == -560


@pytest.mark.parametrize('version', VERSIONS)
def test_offline_list_contract_packages_exact_matching_source_and_owned_limits(tmp_path,version):
    task = ListTask(tmp_path,version)
    code,result = task.run('query-schema')
    assert code == 0, result
    lists = result['related_outputs']['list_members']
    source = json.loads((Path(gateway.__file__).parents[1]/'references/semantic'/version/'query-list-output-sources.json').read_text())
    assert source['wwise_build'] == result['related_outputs']['source']['wwise_build']
    assert source['page_sha256'] == result['related_outputs']['source']['page_sha256']
    assert lists['strategy'] == source['strategy']
    assert lists['relations'] == {'children':'children','descendants':'descendants','ancestors':'ancestors','references-to':'referencesTo'}
    assert lists['limits']['source_ids_per_read'] == 64 and lists['limits']['unique_member_ids'] == 4096
    assert lists['source']['sections_sha256'] == hashlib.sha256(json.dumps(source['sections'],ensure_ascii=False,separators=(',',':'),sort_keys=True).encode()).hexdigest()
    assert 'direct children' in ''.join(section['html'] for section in source['sections'])
    if version not in {'2021.1','2022.1'}:
        html = ''.join(section['html'] for section in source['sections'])
        assert 'children.target.{path, type}' in html and ' as ' in html
    assert task.calls == []


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('change', ['none','member-value','membership','metadata'])
def test_list_pages_reconstruct_member_values_and_seal_all_owned_reads(tmp_path,version,change):
    task = ListTask(tmp_path,version)
    text = '音声' * 7000
    for member in task.members.values(): member['notes'] = text
    code,result = task.run('query-object',*options(),'--include-related','children','notes',*(['--detail'] if change == 'none' else []))
    assert code == 0 and result['status'] == 'partial', result
    next_argv = result['agent_result']['next_command']['gateway_argv']
    if change == 'member-value': task.members[SOUND]['@Pitch'] = -561
    elif change == 'membership': task.rows[0]['children'].reverse()
    elif change == 'metadata': task.metadata[SOUND_CLASS]['Pitch']['type'] = 'Real64'
    if change != 'none':
        code,rejected = task.run(*next_argv)
        assert code == 2 and rejected['error_code'] == 'QUERY_RESULT_CONTINUATION_CHANGED', rejected
        return
    entries = []
    while True:
        page = result['agent_result']
        entries.extend(page['entries'])
        assert len(json.dumps(result,ensure_ascii=False,indent=2).encode()) <= 32768
        assert list(result)[-1] == 'agent_result'
        if page['projection_complete']: break
        code,result = task.run(*page['next_command']['gateway_argv'])
        assert code == 0, result
    assert ''.join(entry['value'] for entry in entries if entry['pointer'] == '/objects/0/related/children/items/0/notes') == text
    assert [entry['value'] for entry in entries if entry['pointer'] == '/objects/0/related/children/items/0/properties/Pitch'] == [-560]


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('bound', ['occurrences','unique','bytes'])
def test_owned_member_limits_fail_before_truncating_or_returning_partial_members(tmp_path,version,bound,monkeypatch):
    import wwise_waapi.object_query_related_lists as lists
    task = ListTask(tmp_path,version)
    if bound == 'occurrences': monkeypatch.setattr(lists,'MAX_RELATED_MEMBER_OCCURRENCES',1)
    elif bound == 'unique': monkeypatch.setattr(lists,'MULTI_IDENTITY_READ_MAX_IDS',1)
    else:
        monkeypatch.setattr(gateway,'MAX_GATEWAY_RESULT_JSON_BYTES',5000)
        task.members[SOUND]['notes'] = 'x' * 3000
        task.rows[0]['children'] = [task.reference(SOUND)] * 2
        task.rows[1]['children'] = []
    args = options() + (['--include-related','children','notes'] if bound == 'bytes' else [])
    code,result = task.run('query-object',*args)
    assert code == 2, result
    assert result.get('agent_result') is None
    assert result['error_code'] in {'RELATED_QUERY_MEMBER_LIMIT','RELATED_QUERY_OBSERVATION_LIMIT','RELATED_QUERY_READ_FAILED'}, result


@pytest.mark.parametrize('version',['2021.1','2022.1'])
def test_grouped_source_chunks_are_checked_and_never_exceed_actual_builder_source_limit(tmp_path,version):
    import uuid
    from wwise_waapi.builders.query import MAX_STRUCTURED_SOURCE_ITEMS
    task = ListTask(tmp_path,version)
    task.members.clear()
    for number in range(MAX_STRUCTURED_SOURCE_ITEMS + 1):
        identity = '{' + str(uuid.UUID(int=number+1)).upper() + '}'
        task.members[identity] = {'id':identity,'name':f'Member{number}','type':'Sound','path':f'\\Sounds\\Member{number}','classId':SOUND_CLASS,'@Volume':number}
    task.objects.update(task.members)
    task.rows[0]['children'] = [task.reference(identity) for identity in task.members]
    task.rows[1]['children'] = []
    code,result = task.run('query-object','--kind','all-sounds','--max-results','2','--include-related','children','volume-db')
    assert code == 0, result
    assert len(result['agent_result'][0]['related']['children']['items']) == 65
    member_reads = [args for uri,args,_ in task.calls if uri.endswith('object.get') and 'from object ' in args.get('waql','')]
    assert {len(re.findall(r'\{[0-9A-Fa-f-]{36}\}',args['waql'])) for args in member_reads} == {64,1}


@pytest.mark.parametrize('version', VERSIONS)
def test_raw_member_identity_extensions_are_type_exact_scope_facts_and_never_pruned(tmp_path,version):
    class Extension(ListTask):
        count = 0
        def projection(self,row,expressions):
            projected = super().projection(row,expressions)
            if row['id'] == SOUND:
                projected['future'] = {'related':{},'value': True if self.count >= 4 else 1}
            return projected
        def call(self,uri,args=None,options=None):
            if uri.endswith('object.get') and args != {'waql':'from type Project take 1'}: self.count += 1
            return super().call(uri,args,options)
    task = Extension(tmp_path,version)
    code,result = task.run('query-object',*options())
    assert code == 2 and result['error_code'] == 'RELATED_QUERY_SCOPE_CHANGED', result


@pytest.mark.parametrize('version', VERSIONS)
def test_list_terminal_kind_and_raw_accessor_rejection_preserve_metadata_authority(tmp_path,version):
    task = ListTask(tmp_path,version)
    code,result = task.run('query-object','--kind','all-sounds','--max-results','2','--include-related-local-reference','children','Pitch')
    assert code == 2 and result['error_code'] == 'RELATED_QUERY_FIELD_KIND', result
    before = len(task.calls)
    code,result = task.run('query-object','--kind','all-sounds','--max-results','2','--include-related-field','children','@Pitch')
    assert code == 2, result
    assert len(task.calls) == before


@pytest.mark.parametrize('version',VERSIONS)
def test_fixed_and_custom_slots_can_share_native_value_without_colliding(tmp_path,version):
    task = ListTask(tmp_path,version)
    code,result = task.run('query-object','--kind','all-sounds','--max-results','2',
        '--include-related','children','pitch-cents','--include-related-field','children','Pitch')
    assert code == 0, result
    member = result['agent_result'][0]['related']['children']['items'][0]
    assert member['pitch_cents'] == -560 and member['properties']['Pitch'] == -560


@pytest.mark.parametrize('version',VERSIONS)
@pytest.mark.parametrize('relation,native',[('descendants','descendants'),('ancestors','ancestors'),('references-to','referencesTo')])
def test_documented_object_list_descriptors_share_the_same_member_contract(tmp_path,version,relation,native):
    task = ListTask(tmp_path,version)
    for row in task.rows: row[native] = row.pop('children')
    code,result = task.run('query-object','--kind','all-sounds','--max-results','2','--include-related',relation,'volume-db')
    assert code == 0, result
    assert [member['object']['id'] for member in result['agent_result'][0]['related'][relation]['items']] == [SOUND,OTHER]


@pytest.mark.parametrize('version',VERSIONS)
@pytest.mark.parametrize('presence',['null','absent'])
def test_missing_singleton_terminal_behavior_stays_the_same_when_lists_are_requested(tmp_path,version,presence):
    task = ListTask(tmp_path,version)
    for member in task.members.values():
        if presence == 'null': member['parent'] = None
    code,result = task.run('query-object','--kind','all-sounds','--max-results','2',
        '--include-related','children','parent','volume-db','--include-related-field','children','Pitch')
    assert code == 0, result
    context = result['agent_result'][0]['related']['children']['items'][0]['related']['parent']
    assert context['unavailable_fields'] == (['volume_db'] if presence == 'null' else ['object','volume_db'])
    if presence == 'null': assert context['object'] is None


@pytest.mark.parametrize('version',VERSIONS)
def test_nested_list_paths_are_bounded_before_live_preparation(tmp_path,version):
    from wwise_waapi.builders.query import MAX_ADVANCED_RETURN_EXPRESSIONS
    task = ListTask(tmp_path,version)
    code,result = task.run('query-object','--kind','all-sounds','--max-results','2',
        '--include-related',*(['children']*(MAX_ADVANCED_RETURN_EXPRESSIONS+1)),'volume-db')
    assert code == 2, result
    assert task.calls == []


@pytest.mark.parametrize('version',['2021.1','2022.1'])
@pytest.mark.parametrize('change',['name','typed-extension'])
def test_grouped_membership_reference_facts_cannot_be_hidden_by_member_readback(tmp_path,version,change):
    class Changing(ListTask):
        count = 0
        def call(self,uri,args=None,options=None):
            if uri.endswith('object.get') and args != {'waql':'from type Project take 1'}:
                self.count += 1
                if self.count == 4:
                    reference = self.rows[0]['children'][0]
                    if change == 'name': reference['name'] = 'Renamed'
                    else: reference['classId'] = True
            return super().call(uri,args,options)
    task = Changing(tmp_path,version)
    if change == 'typed-extension': task.rows[0]['children'][0]['classId'] = SOUND_CLASS
    code,result = task.run('query-object',*options())
    assert code == 2 and result['error_code'] == 'RELATED_QUERY_SCOPE_CHANGED', result
