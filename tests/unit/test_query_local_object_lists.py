"""Owner-preserving, source-certified local RTPC/EffectSlot/Marker projections."""
import copy
import json
import re
from pathlib import Path

import pytest

from tests.unit.test_query_field_conditions import FieldTask
from tests.unit.test_query_related_paths import SOUND_CLASS, SOUND, OTHER

RTPC1 = '{4AD8A39B-B005-4572-9A98-0A60BDB55A80}'
RTPC2 = '{482C90B6-387C-4E86-8228-B5E4DA392451}'
CURVE1 = '{86435C2C-DB2B-4A66-A49A-A1F14390321C}'
CURVE2 = '{0B357DC6-5FE7-4E50-9C31-23CDE7F34307}'
POINTS = [{'x': 0.0, 'y': -5.67053, 'shape': 'Linear'}, {'x': 1.0, 'y': 0.0, 'shape': 'Linear'}]


class LocalListTask(FieldTask):
    def __init__(self, tmp_path, version='2025.1'):
        super().__init__(tmp_path, version)
        owner = {'id': SOUND, 'name': 'Owner', 'type': 'Sound', 'path': '\\Sounds\\Owner', 'classId': SOUND_CLASS}
        members = {}
        for identity, curve, points in [(RTPC1, CURVE1, POINTS), (RTPC2, CURVE2, [{'x': 0, 'y': 0, 'shape': 'Exp3'}])]:
            members[identity] = {'id': identity, 'name': '', 'type': 'RTPC', 'path': '\\Sounds\\Owner\\' + identity,
                'classId': 1441808, 'owner': {'id': SOUND, 'name': 'Owner'}, '@PropertyName': 'Volume',
                'ControlInput': {'id': OTHER, 'name': 'Input'}, 'Curve': {'id': curve},
                'Curve.classId': 917520, 'Curve.points': copy.deepcopy(points)}
        members[RTPC2]['ControlInput'] = {'id': CURVE2, 'name': 'Other Input'}
        owner['@RTPC'] = [{key: row[key] for key in ('id','name')} for row in members.values()]
        self.rows = [owner]; self.row = owner; self.objects = {SOUND: owner, **members}; self.members = members
        self.metadata[1441808] = {'PropertyName': {'name': 'PropertyName', 'type': 'string'},
            'ControlInput': {'name':'ControlInput','type':'','restriction': {'type':'reference','restrictions':[{'type':['GameParameter']}]}},
            'Curve': {'name': 'Curve', 'type': '', 'restriction': {'type': 'reference', 'restrictions': [{'type': ['Curve']}]}}}

    def call(self, uri, args=None, options=None):
        waql = (args or {}).get('waql','')
        if uri.endswith('object.get') and re.search(r' select @(RTPC|Effects|Markers)',waql):
            self.calls.append((uri,args,options))
            owner, = re.findall(r'\{[0-9A-Fa-f-]{36}\}',waql.split(' select ')[0])
            relation = re.search(r' select (@\w+)',waql).group(1)
            rows = [self.objects[ref['id']] for ref in self.objects[owner][relation]]
            for operation, expression in zip(re.split(r' (where|skip|take) ',waql)[1::2],re.split(r' (where|skip|take) ',waql)[2::2]):
                if operation == 'take': rows = rows[:int(expression)]
                elif operation == 'skip': rows = rows[int(expression):]
                else: rows = [row for row in rows if self.native_matches(row,expression)]
            return {'return': [self.projection(row,options['return']) for row in rows]}
        return super().call(uri,args,options)


@pytest.mark.parametrize('version', ['2022.1','2023.1','2024.1','2025.1'])
def test_local_rtpcs_preserve_owner_empty_names_and_associated_curve_points(tmp_path, version):
    task = LocalListTask(tmp_path, version)
    code, result = task.run('query-object','--exact-id',SOUND,
        '--include-related-field','local-rtpcs','PropertyName',
        '--include-related','local-rtpcs','reference','Curve','curve-points','--detail')
    assert code == 0, result
    root, = result['agent_result']
    assert root['id'] == SOUND
    items = root['related']['local-rtpcs']['items']
    assert [row['object']['id'] for row in items] == [RTPC1, RTPC2]
    assert [row['object']['name'] for row in items] == ['', '']
    assert [row['properties'] for row in items] == [{'PropertyName':'Volume'}]*2
    assert items[0]['related']['references']['Curve']['curve_points'] == POINTS
    assert items[1]['related']['references']['Curve']['curve_points'] == [{'x':0,'y':0,'shape':'Exp3'}]
    assert any('select @RTPC' in (args or {}).get('waql','') or any('@RTPC.{' in field for field in (options or {}).get('return',[])) for uri,args,options in task.calls)


def effect_task(tmp_path, version):
    task = LocalListTask(tmp_path, version)
    task.row['@Effects'] = task.row.pop('@RTPC')
    for row in task.members.values():
        row.update(type='EffectSlot', classId=5505040, **{'@Bypass': False, '@Render': True,
            'Effect': {'id': OTHER,'name':'Gain'}, 'Effect.classId': 9109507, 'Effect.pluginName': 'Wwise Gain'})
    task.metadata[5505040] = {'Bypass': {'name':'Bypass','type':'bool'}, 'Render': {'name':'Render','type':'bool'},
        'Effect': {'name':'Effect','type':'','restriction': {'type':'reference','restrictions':[{'type':['Effect']}]}}}
    return task


@pytest.mark.parametrize('version', ['2021.1','2022.1','2023.1','2024.1','2025.1'])
@pytest.mark.parametrize('source', ['local-rtpcs','local-effect-slots'])
def test_closed_local_lists_disclose_and_enforce_version_specific_source(tmp_path, version, source):
    task = LocalListTask(tmp_path,version) if source == 'local-rtpcs' else effect_task(tmp_path,version)
    code,schema = task.run('query-schema')
    assert code == 0
    contract = schema['related_outputs']['local_object_lists']
    available = version >= ('2022.1' if source == 'local-rtpcs' else '2023.1')
    assert contract['contexts'][source]['available'] is available
    assert 'directly stored' in contract['membership']
    if source == 'local-rtpcs' and version == '2021.1':
        boundary = contract['contexts'][source]
        assert boundary['limitation_kind'] == 'skill-interface'
        assert boundary['native_absence_proven'] is False
        assert 'stored property-to-RTPC association' in boundary['availability_reason']
        assert 'exact RTPC/Game Parameter' in boundary['availability_reason']
        assert 'typed ControlInput' in boundary['availability_reason']
        assert boundary['alternatives']['query'] == 'query-object --exact-id'
        assert boundary['alternatives']['metadata'] == 'metadata list/detail --exact-id'
    elif source == 'local-rtpcs':
        assert 'limitation_kind' not in contract['contexts'][source]
    code,result = task.run('query-object','--exact-id',SOUND,'--include-related',source,'count')
    if available:
        assert code == 0,result
        assert result['agent_result'][0]['related']['projections'][0]['value'] == 2
    else:
        assert code == 2 and not any(uri.endswith('object.get') for uri,_,_ in task.calls),result
        if source == 'local-rtpcs':
            assert result['message'] == contract['contexts'][source]['availability_reason']
            assert 'Skill limitation' in result['message'] and 'not a claim of native absence' in result['message']


@pytest.mark.parametrize('version', ['2023.1','2024.1','2025.1'])
def test_effect_slots_reuse_actual_metadata_and_resolved_effect_reference(tmp_path,version):
    task=effect_task(tmp_path,version)
    code,result=task.run('query-object','--exact-id',SOUND,
        '--include-related-field','local-effect-slots','Bypass',
        '--include-related-field','local-effect-slots','Render',
        '--include-related','local-effect-slots','reference','Effect','plugin-name')
    assert code == 0,result
    items=result['agent_result'][0]['related']['local-effect-slots']['items']
    assert [row['object']['id'] for row in items] == [RTPC1,RTPC2]
    assert all(row['properties']=={'Bypass':False,'Render':True} and
        row['related']['references']['Effect']['plugin_name']=='Wwise Gain' for row in items)


@pytest.mark.parametrize('version',['2022.1','2025.1'])
@pytest.mark.parametrize('path', [ ['local-rtpcs'], ['local-rtpcs','first'],
    ['combine','local-rtpcs','and','local-rtpcs','end','take','3']])
@pytest.mark.parametrize('fault',['class','owner','missing-owner'])
def test_local_members_require_declared_class_and_actual_owner_in_every_sequence(tmp_path,version,path,fault):
    task=LocalListTask(tmp_path,version)
    row=task.members[RTPC1]
    if fault=='class':row['classId']=SOUND_CLASS
    elif fault=='owner':row['owner']={'id':OTHER}
    else:row.pop('owner')
    code,result=task.run('query-object','--exact-id',SOUND,'--include-related-field',*path,'PropertyName')
    assert code==2 and result['error_code']=='RELATED_QUERY_LOCAL_LIST_MEMBER',result


@pytest.mark.parametrize('version',['2022.1','2025.1'])
def test_unknown_plugin_class_cannot_borrow_abstract_source_list_or_return_empty(tmp_path,version):
    task=LocalListTask(tmp_path,version)
    task.row.update(classId=9699331,type='SourcePlugin',name='Wwise Synth One')
    task.row['@RTPC']=[]
    code,result=task.run('query-object','--exact-id',SOUND,'--include-related','local-rtpcs','any')
    assert code==2 and result['error_code']=='RELATED_QUERY_LOCAL_LIST_SOURCE',result
    assert not any('@RTPC' in (args or {}).get('waql','') or any('@RTPC' in field for field in (options or {}).get('return',[])) for _,args,options in task.calls)


@pytest.mark.parametrize('version',['2022.1','2023.1','2024.1','2025.1'])
@pytest.mark.parametrize('selection',[[],['first'],['combine','local-rtpcs','and','local-rtpcs','end','take','3']])
def test_exact_source_plugin_class_projects_its_source_certified_rtpcs(tmp_path,version,selection):
    task=LocalListTask(tmp_path,version)
    task.row.update(classId=9699330,type='SourcePlugin',name='Wwise Synth One')
    path=selection if selection and selection[0]=='combine' else ['local-rtpcs',*selection]
    code,result=task.run('query-object','--exact-id',SOUND,
        '--include-related',*path,'reference','Curve','curve-points','--detail')
    assert code==0,result
    root,=result['agent_result']
    if not selection:
        items=root['related']['local-rtpcs']['items']
        assert [row['object']['id'] for row in items]==[RTPC1,RTPC2]
        assert items[0]['related']['references']['Curve']['curve_points']==POINTS
    elif selection==['first']:
        projection,=root['related']['projections']
        selected,=projection['items']
        assert selected['object']['id']==RTPC1 and selected['related']['references']['Curve']['curve_points']==POINTS
    else:
        projection,=root['related']['projections']
        assert [row['object']['id'] for row in projection['items']]==[RTPC1,RTPC2,RTPC1]


@pytest.mark.parametrize('version',['2022.1','2023.1','2024.1','2025.1'])
@pytest.mark.parametrize('actual_type',['Source','Sound'])
def test_source_plugin_bridge_requires_actual_object_type_not_gettypes_category(tmp_path,version,actual_type):
    task=LocalListTask(tmp_path,version)
    task.row.update(classId=9699330,type=actual_type,name='Wwise Synth One')
    code,result=task.run('query-object','--exact-id',SOUND,'--include-related','local-rtpcs','count')
    assert code==2 and result['error_code']=='RELATED_QUERY_LOCAL_LIST_SOURCE',result


@pytest.mark.parametrize('version',['2022.1','2025.1'])
def test_exact_source_plugin_bridge_also_loads_actual_type_at_singleton_owner(tmp_path,version):
    task=LocalListTask(tmp_path,version)
    source=copy.deepcopy(task.row)
    source.update(id=OTHER,classId=9699330,type='SourcePlugin',name='Wwise Synth One')
    task.objects[OTHER]=source
    task.row.update(parent={'id':OTHER,'name':'Wwise Synth One'},**{'parent.classId':9699330,
        'parent.type':'SourcePlugin','parent.@RTPC':source['@RTPC']})
    for member in task.members.values():member['owner']={'id':OTHER,'name':'Wwise Synth One'}
    code,result=task.run('query-object','--exact-id',SOUND,'--include-related-field','parent','local-rtpcs','first','PropertyName')
    assert code==0,result
    projection,=result['agent_result'][0]['related']['parent']['related']['projections']
    assert [row['object']['id'] for row in projection['items']]==[RTPC1]


@pytest.mark.parametrize('version',['2022.1','2023.1','2024.1','2025.1'])
def test_offline_bridge_discloses_exact_scope_and_retains_distinct_primary_type_evidence(tmp_path,version):
    task=LocalListTask(tmp_path,version)
    code,schema=task.run('query-schema')
    assert code==0
    assert schema['related_outputs']['local_object_lists']['explicit_class_bridges']==[{
        'actual_class_id':9699330,'actual_object_type':'SourcePlugin','source_class_id':1048592,'native_list':'@RTPC'}]
    root=Path(__file__).resolve().parents[2]/'skills/waapi-skill'
    source=json.loads((root/'references/semantic'/version/'query-local-list-bridge.json').read_text())
    assert source['version']==version
    assert source['official_plugin_identity']['sha256']=='372181c5a3452fa6822da5e96e5d3fd2652337bb3fd65d8a81bbe4e24463d996'
    assert source['class_id_calculation']['calculation']=='2 + (0 << 4) + (148 << (4 + 12)) = 9699330'
    assert source['retained_type_registration']['row']=={'classId':9699330,'name':'Wwise Synth One','type':'Source'}
    owner=source['retained_object_observation']['object']; member=source['retained_member_observation']['object']
    assert owner['class_id']==9699330 and owner['type']=='SourcePlugin'
    assert member['class_id']==1441808 and member['type']=='RTPC' and member['owner']['id']==owner['id']
    assert source['abstract_declaration']['declaration']['name']=='RTPC'


@pytest.mark.parametrize('version',['2022.1','2025.1'])
@pytest.mark.parametrize('fault',['member-class','member-owner'])
def test_source_plugin_bridge_keeps_actual_member_class_and_owner_controls(tmp_path,version,fault):
    task=LocalListTask(tmp_path,version)
    task.row.update(classId=9699330,type='SourcePlugin')
    if fault=='member-class':task.members[RTPC1]['classId']=65552
    else:task.members[RTPC1]['owner']={'id':OTHER}
    code,result=task.run('query-object','--exact-id',SOUND,'--include-related-field','local-rtpcs','PropertyName')
    assert code==2 and result['error_code']=='RELATED_QUERY_LOCAL_LIST_MEMBER',result


@pytest.mark.parametrize('version',['2023.1','2025.1'])
def test_source_plugin_rtpc_bridge_does_not_admit_unproven_effect_list(tmp_path,version):
    task=effect_task(tmp_path,version)
    task.row.update(classId=9699330,type='SourcePlugin')
    code,result=task.run('query-object','--exact-id',SOUND,'--include-related','local-effect-slots','count')
    assert code==2 and result['error_code']=='RELATED_QUERY_LOCAL_LIST_SOURCE',result


@pytest.mark.parametrize('version',['2022.1','2023.1','2024.1','2025.1'])
@pytest.mark.parametrize('layout',['singleton','list'])
@pytest.mark.parametrize('value', [ [{'x':False,'y':0,'shape':'Linear'}], [{'x':0,'y':0,'shape':'Bogus'}],
    [{'x':0,'y':float('inf'),'shape':'Linear'}], [{'x':0,'shape':'Linear'}], 'points'])
def test_related_points_reject_incompatible_values_at_existing_singleton_and_member_seams(tmp_path,version,layout,value):
    task=LocalListTask(tmp_path,version)
    if layout=='singleton':
        task.row.update(parent={'id':CURVE1,'name':''},**{'parent.points':copy.deepcopy(value)})
        path=['parent']
    else:
        task.members[RTPC1]['Curve.points']=copy.deepcopy(value);path=['local-rtpcs','reference','Curve']
    code,result=task.run('query-object','--exact-id',SOUND,'--include-related',*path,'curve-points')
    if isinstance(value,list) and value and value[0].get('y') == float('inf'):
        assert code != 0 and result.get('ok') is False,result  # Native JSON/evidence bound may reject nonfinite before projection.
    else:
        assert code==2 and result['error_code']=='RELATED_QUERY_CURVE_POINTS',result


@pytest.mark.parametrize('version',['2022.1','2025.1'])
def test_related_curve_point_reads_keep_order_null_and_more_than_mutation_input_cap(tmp_path,version):
    task=LocalListTask(tmp_path,version)
    points=[{'x':i,'y':-i,'shape':'Linear'} for i in range(257,-1,-1)]
    task.row.update(parent={'id':CURVE1,'name':''}, **{'parent.points':points})
    code,result=task.run('query-object','--exact-id',SOUND,'--include-related','parent','curve-points')
    assert code==0,result
    assert result['agent_result'][0]['related']['parent']['curve_points']==points
    task.row['parent.points']=None
    code,result=task.run('query-object','--exact-id',SOUND,'--include-related','parent','curve-points')
    assert code==0 and result['agent_result'][0]['related']['parent']['curve_points'] is None,result


@pytest.mark.parametrize('version',['2022.1','2025.1'])
def test_combined_zero_window_does_not_certify_an_unsupported_list_source_as_empty(tmp_path,version):
    task=LocalListTask(tmp_path,version);task.row['classId']=9699330
    code,result=task.run('query-object','--exact-id',SOUND,'--include-related','combine','local-rtpcs','and','local-rtpcs','end','take','0','count')
    assert code==2 and result['error_code']=='RELATED_QUERY_LOCAL_LIST_SOURCE',result


@pytest.mark.parametrize('version',['2022.1','2023.1','2024.1','2025.1'])
def test_local_full_selected_and_combined_views_keep_same_property_inputs_and_occurrences(tmp_path,version):
    task=LocalListTask(tmp_path,version)
    code,result=task.run('query-object','--exact-id',SOUND,
        '--include-related-field','local-rtpcs','PropertyName',
        '--include-related-field','local-rtpcs','ControlInput',
        '--include-related-field','local-rtpcs','first','PropertyName',
        '--include-related-field','combine','local-rtpcs','and','local-rtpcs','end','take','3','PropertyName',
        '--include-related','local-rtpcs','matching-field','ordinary','PropertyName','is','Volume','count')
    assert code==0,result
    related=result['agent_result'][0]['related']
    assert [row['references']['ControlInput']['id'] for row in related['local-rtpcs']['items']]==[OTHER,CURVE2]
    first=next(view for view in related['projections'] if view['spec'].get('stages')==[{'selection':'first'}])
    combined=next(view for view in related['projections'] if view['spec']['source']=='combine')
    count=next(view for view in related['projections'] if view['spec'].get('reducer'))
    assert [row['object']['id'] for row in first['items']]==[RTPC1]
    assert [row['object']['id'] for row in combined['items']]==[RTPC1,RTPC2,RTPC1]
    assert [row['origin']['arm'] for row in combined['items']]==[0,0,1]
    assert count['value']==2


@pytest.mark.parametrize('version',['2022.1','2025.1'])
@pytest.mark.parametrize('change',['none','class','owner','points','typed-points','metadata'])
def test_local_list_pages_rebind_and_revalidate_sources_owners_metadata_and_curve_values(tmp_path,version,change):
    task=LocalListTask(tmp_path,version);task.row['notes']='音声'*16000
    code,result=task.run('query-object','--exact-id',SOUND,'--include','notes',
        '--include-related','local-rtpcs','reference','Curve','curve-points')
    assert code==0 and result['status']=='partial',result
    if change=='class':task.row['classId']=9699330
    elif change=='owner':task.members[RTPC1]['owner']={'id':OTHER}
    elif change=='points':task.members[RTPC1]['Curve.points'][0]['y']-=1
    elif change=='typed-points':task.members[RTPC1]['Curve.points'][0]['x']=False
    elif change=='metadata':task.metadata[1441808]['Curve']['type']='bool';task.metadata[1441808]['Curve']['restriction']={}
    code,continued=task.run(*result['agent_result']['next_command']['gateway_argv'])
    if change=='none':assert code==0 and continued['status']=='partial',continued
    else:assert code==2 and continued['error_code']=='QUERY_RESULT_CONTINUATION_CHANGED',continued


@pytest.mark.parametrize('version',['2022.1','2025.1'])
@pytest.mark.parametrize('presence',['empty','absent','null'])
def test_local_source_admission_precedes_empty_null_absent_membership(tmp_path,version,presence):
    task=LocalListTask(tmp_path,version)
    if presence=='empty':task.row['@RTPC']=[]
    elif presence=='null':task.row['@RTPC']=None
    else:task.row.pop('@RTPC')
    if version=='2022.1':
        # External SELECT returns zero rows for a declared local list with no entries.
        original=task.call
        def call(uri,args=None,options=None):
            if 'select @RTPC' in (args or {}).get('waql',''):
                task.calls.append((uri,args,options));return {'return':[]}
            return original(uri,args,options)
        task.call=call
    code,result=task.run('query-object','--exact-id',SOUND,'--include-related-field','local-rtpcs','PropertyName')
    assert code==0,result
    view=result['agent_result'][0]['related']['local-rtpcs']
    if version=='2022.1' or presence=='empty':assert view=={'items':[]}
    elif presence=='null':assert view=={'items':None}
    else:assert view=={'unavailable_fields':['items']}


MARKER_PACKET = json.loads((Path(__file__).parents[1]/'fixtures/query-local-lists/marker-2025.json').read_text())
MARKER = MARKER_PACKET['membership']['result']['return'][0]['id']
MARKER_OWNER = MARKER_PACKET['exact_read']['result']['return'][0]['owner']['id']


def marker_task(tmp_path, version='2025.1'):
    task = LocalListTask(tmp_path, version)
    # Retained native identity and metadata; the opaque path is not a hierarchy.
    member = copy.deepcopy(MARKER_PACKET['exact_read']['result']['return'][0])
    owner = {'id': MARKER_OWNER, 'name': 'audit_outside', 'type': 'AudioFileSource',
        'path': r'\Sounds\Owner\audit_outside', 'classId': 16, '@Markers': [{'id': MARKER}]}
    task.row = owner; task.rows = [owner]; task.members = {MARKER: member}
    task.objects = {MARKER_OWNER: owner, MARKER: member}
    fields = {name: copy.deepcopy(packet['result']) for name, packet in MARKER_PACKET['metadata'].items()}
    task.metadata[5373968] = fields
    task.metadata[MARKER] = copy.deepcopy(fields)
    return task


@pytest.mark.parametrize('version', ['2023.1','2024.1','2025.1'])
def test_local_markers_preserve_source_owner_native_guid_opaque_path_and_discovered_values(tmp_path, version):
    task = marker_task(tmp_path, version)
    code,result = task.run('query-object','--exact-id',MARKER_OWNER,
        '--include-related','local-markers','class-id',
        '--include-related','local-markers','owner',
        '--include-related-field','local-markers','Time',
        '--include-related-field','local-markers','Label','--detail')
    assert code == 0,result
    root, = result['agent_result']
    assert root['id'] == MARKER_OWNER
    member, = root['related']['local-markers']['items']
    assert member == {'object': {'id': MARKER, 'name': '', 'type': 'Marker', 'path': '[Marker]'},
        'class_id': 5373968, 'owner': {'id': MARKER_OWNER, 'name': 'audit_outside'},
        'properties': {'Time': 0.0, 'Label': 'R90_MARKER'}}
    assert result['related_scope_binding']['local_list_sources'][0]['declaration']['element_classes'] == [{'name':'Marker','class_id':5373968}]
    assert list(result)[-1] == 'agent_result'
    assert {uri for uri,_,_ in task.calls} <= {'ak.wwise.core.getInfo','ak.wwise.core.object.get',
        'ak.wwise.core.object.getPropertyAndReferenceNames','ak.wwise.core.object.getPropertyInfo'}


@pytest.mark.parametrize('version', ['2021.1','2022.1','2023.1','2024.1','2025.1'])
def test_local_marker_contract_keeps_modern_stored_list_and_legacy_inner_boundaries(tmp_path, version):
    task = marker_task(tmp_path, version)
    code,schema = task.run('query-schema')
    assert code == 0,schema
    contract = schema['related_outputs']['local_object_lists']
    context = contract['contexts']['local-markers']
    assert context['native'] == '@Markers' and context['field'] == 'Markers'
    assert context['available'] is (version >= '2023.1')
    assert 'no imported/effective marker computation claim' in context['scope']
    assert 'remaining' not in contract
    paths = contract['available_paths']
    assert '2021 Skill limitation' in paths['rtpc_association']
    assert 'Effect0-3' in paths['fixed_effects'] and '--include-field' in paths['fixed_effects']
    assert '--include marker-records' in paths['marker_records'] and 'actual ordered' in paths['marker_records']
    assert 'equivalence is not established' in paths['marker_records']
    for backlog in ('inspection semantics', 'imported/effective marker projection', 'remaining', '#181'):
        assert backlog not in json.dumps(paths)
    if version < '2023.1':
        boundary = context['native_boundary']
        assert boundary['version'] == version and boundary['introduced_in'] == '2023.1'
        assert boundary['scope'] == 'direct source Marker object/List read and edit through WAAPI/WAQL; not all file/effective marker information'
        assert boundary['source']['feature'] == 'Markers in Audio File Source'
        assert boundary['source']['feature_statement'] == 'The following elements have been refactored and are now accessible in WAAPI and WAQL:'
        assert boundary['source']['member_sha256'] == 'ab295251f12c58809e78a24691f4a0603034b8f7519f63f8aa52904295771c39'
        assert boundary['registered_type_discovery_available'] is True
        assert boundary['all_marker_information_absence_proven'] is False
    else:
        assert 'native_boundary' not in context
    code,result = task.run('query-object','--exact-id',MARKER_OWNER,'--include-related','local-markers','count')
    if version >= '2023.1':
        assert code == 0,result
        assert result['agent_result'][0]['related']['projections'][0]['value'] == 1
    else:
        assert code == 2 and not task.calls,result
        assert 'introduced in Wwise 2023.1' in result['message'] and 'not all file/effective marker information' in result['message']
        assert 'native absence is not established' not in result['message']
        original = task.call
        def native(uri, args=None, options=None):
            if uri.endswith('object.getTypes'):
                task.calls.append((uri,args,options))
                return {'return':[{'name':'Marker','classId':65077248,'type':'Inner'}]}
            return original(uri,args,options)
        task.call = native
        task.metadata[65077248] = {'Time':{'name':'Time','type':'Real64'},'Label':{'name':'Label','type':'string'}}
        code,types = task.run('metadata','types')
        assert code == 0,types
        inner, = types['agent_result']['types']
        assert {key:inner[key] for key in ('name','classId','type')} == {'name':'Marker','classId':65077248,'type':'Inner'}
        code,fields = task.run('metadata','list','--custom-kind','Marker')
        assert code == 0 and [field['name'] for field in fields['agent_result']['fields']] == ['Label','Time'],fields
        assert not any('@Markers' in (args or {}).get('waql','') for uri,args,_ in task.calls if uri.endswith('object.get'))


@pytest.mark.parametrize('version', ['2023.1','2025.1'])
def test_local_marker_selected_combined_and_field_reducers_keep_occurrences_and_zero_values(tmp_path, version):
    task = marker_task(tmp_path, version)
    # The second row is a program-only alternate, not an extra retained native observation.
    second = copy.deepcopy(task.members[MARKER]); second.update(id=RTPC2, **{'@Time': 1.0,'@Label': ''})
    task.members[RTPC2] = second; task.objects[RTPC2] = second; task.metadata[RTPC2] = task.metadata[MARKER]
    task.row['@Markers'].append({'id':RTPC2})
    code,result = task.run('query-object','--exact-id',MARKER_OWNER,
        '--include-related-field','local-markers','Time',
        '--include-related-field','local-markers','Label',
        '--include-related-field','local-markers','first','Time',
        '--include-related-field','local-markers','last','Label',
        '--include-related-field','local-markers','at','1','Label',
        '--include-related-field','local-markers','skip','1','take','1','Time',
        '--include-related-field','combine','local-markers','and','local-markers','end','take','3','Label',
        '--include-related','local-markers','matching-field','ordinary','Time','at-most','0','count',
        '--include-related','local-markers','any-match-field','ordinary','Label','is','R90_MARKER',
        '--include-related','local-markers','all-match-field','ordinary','Time','at-most','0')
    assert code == 0,result
    related = result['agent_result'][0]['related']
    assert [row['properties'] for row in related['local-markers']['items']] == [
        {'Time':0.0,'Label':'R90_MARKER'}, {'Time':1.0,'Label':''}]
    views = related['projections']
    first = next(view for view in views if view['spec'].get('stages') == [{'selection':'first'}])
    last = next(view for view in views if view['spec'].get('stages') == [{'selection':'last'}])
    at = next(view for view in views if view['spec'].get('stages') == [{'selection':'at','count':1}])
    window = next(view for view in views if view['spec'].get('stages') == [{'selection':'skip','count':1},{'selection':'take','count':1}])
    combined = next(view for view in views if view['spec']['source'] == 'combine')
    reduced = {view['spec']['reducer']['operation']:view['value'] for view in views if view['spec'].get('reducer')}
    assert first['items'][0]['object']['id'] == MARKER and first['items'][0]['properties'] == {'Time':0.0}
    assert last['items'][0]['object']['id'] == RTPC2 and last['items'][0]['properties'] == {'Label':''}
    assert at['items'][0]['object']['id'] == RTPC2
    assert window['items'][0]['properties'] == {'Time':1.0}
    assert [row['object']['id'] for row in combined['items']] == [MARKER,RTPC2,MARKER]
    assert [row['origin'] for row in combined['items']] == [
        {'arm':0,'occurrence':0},{'arm':0,'occurrence':1},{'arm':1,'occurrence':0}]
    assert reduced == {'count':1,'any-match':True,'all-match':False}
    assert list(result)[-1] == 'agent_result'


@pytest.mark.parametrize('path', [ ['local-markers'], ['local-markers','first'],
    ['combine','local-markers','and','local-markers','end','take','2']])
@pytest.mark.parametrize('fault', ['class','owner','missing-owner'])
def test_local_marker_members_fail_closed_on_wrong_class_or_source_owner(tmp_path, path, fault):
    task = marker_task(tmp_path)
    row = task.members[MARKER]
    if fault == 'class': row['classId'] = 65077248  # The older Inner class cannot masquerade as a modern WObject.
    elif fault == 'owner': row['owner'] = {'id': OTHER}
    else: row.pop('owner')
    code,result = task.run('query-object','--exact-id',MARKER_OWNER,'--include-related-field',*path,'Time')
    assert code == 2 and result['error_code'] == 'RELATED_QUERY_LOCAL_LIST_MEMBER',result
    assert result.get('agent_result') is None


@pytest.mark.parametrize('path', [ ['local-markers'], ['local-markers','take','0'],
    ['combine','local-markers','and','local-markers','end','take','0']])
def test_empty_or_zero_marker_window_does_not_certify_the_wrong_owner_class(tmp_path, path):
    task = marker_task(tmp_path)
    task.row.update(classId=SOUND_CLASS, type='Sound', **{'@Markers': []})
    code,result = task.run('query-object','--exact-id',MARKER_OWNER,'--include-related',*path,'count')
    assert code == 2 and result['error_code'] == 'RELATED_QUERY_LOCAL_LIST_SOURCE',result
    assert result['details']['native_absence_proven'] is False


@pytest.mark.parametrize('presence', ['empty-list','absent-list','null-list','empty-label','absent-value','null-value'])
def test_marker_lists_and_values_preserve_empty_missing_null_and_numeric_zero(tmp_path, presence):
    task = marker_task(tmp_path)
    if presence == 'empty-list': task.row['@Markers'] = []
    elif presence == 'absent-list': task.row.pop('@Markers')
    elif presence == 'null-list': task.row['@Markers'] = None
    elif presence == 'empty-label': task.members[MARKER]['@Label'] = ''
    elif presence == 'absent-value': task.members[MARKER].pop('@Label')
    else: task.members[MARKER]['@Label'] = None
    code,result = task.run('query-object','--exact-id',MARKER_OWNER,
        '--include-related-field','local-markers','Time','--include-related-field','local-markers','Label')
    assert code == 0,result
    view = result['agent_result'][0]['related']['local-markers']
    if presence == 'empty-list': assert view == {'items':[]}
    elif presence == 'absent-list': assert view == {'unavailable_fields':['items']}
    elif presence == 'null-list': assert view == {'items':None}
    else:
        member, = view['items']
        assert member['properties']['Time'] == 0.0
        if presence == 'absent-value':
            assert member['properties'] == {'Time':0.0} and member['unavailable_fields'] == ['properties.Label']
        else:
            assert member['properties']['Label'] == ('' if presence == 'empty-label' else None)


@pytest.mark.parametrize('failure', ['no-match','partial','wrong-kind'])
def test_marker_values_require_fresh_complete_matching_metadata_without_token_guessing(tmp_path, failure):
    task = marker_task(tmp_path)
    if failure == 'no-match': task.metadata[5373968] = {}; task.metadata[MARKER] = {}
    elif failure == 'partial':
        task.metadata[5373968] = {f'Field{i}': {'name':f'Field{i}','type':'int32'} for i in range(300)}
    option = '--include-related-local-reference' if failure == 'wrong-kind' else '--include-related-field'
    code,result = task.run('query-object','--exact-id',MARKER_OWNER,option,'local-markers','Time')
    if failure == 'wrong-kind':
        assert code == 2 and result['error_code'] == 'RELATED_QUERY_FIELD_KIND',result
    else:
        assert code == 0 and result['status'] == 'needs_clarification',result
        unresolved, = result['agent_result']['unresolved']
        assert unresolved['meaning'] == 'Time' and unresolved['complete'] is (failure == 'no-match')
        assert unresolved['scope'] == ({'classId':5373968} if failure == 'partial' else {'object':MARKER})
    assert all('@Time' not in json.dumps(options) for uri,_,options in task.calls if uri.endswith('object.get'))


@pytest.mark.parametrize('tokens', [ ['local-markers','take','-1','count'], ['local-markers','at','01','count'],
    ['local-markers.take(1)','count'], ['local-markers','matching','@Time','0','count'],
    ['combine','local-markers','end','count']])
def test_marker_context_uses_existing_closed_selector_grammar_before_transport(tmp_path, tokens):
    task = marker_task(tmp_path)
    code,result = task.run('query-object','--exact-id',MARKER_OWNER,'--include-related',*tokens)
    assert code == 2 and not task.calls,result


@pytest.mark.parametrize('empty', [False,True])
def test_local_marker_zero_window_and_empty_reducers_do_not_invent_values_or_membership(tmp_path, empty):
    task = marker_task(tmp_path)
    if empty: task.row['@Markers'] = []
    code,result = task.run('query-object','--exact-id',MARKER_OWNER,
        '--include-related','local-markers','count',
        '--include-related','local-markers','any',
        '--include-related','local-markers','take','0','count',
        '--include-related','local-markers','take','0','any',
        '--include-related','local-markers','take','0','all-match-field','ordinary','Time','at-most','0')
    assert code == 0,result
    views = result['agent_result'][0]['related']['projections']
    whole = {view['spec']['reducer']['operation']:view['value'] for view in views if not view['spec'].get('stages')}
    zero = {view['spec']['reducer']['operation']:view['value'] for view in views if view['spec'].get('stages')}
    assert whole == {'count':0 if empty else 1,'any':not empty}
    assert zero == {'count':0,'any':False,'all-match':False}


def test_local_marker_finite_selection_uses_existing_native_cap_before_full_membership_limit(tmp_path):
    task = marker_task(tmp_path)
    task.row['@Markers'] = [{'id':MARKER}] * 4097
    code,result = task.run('query-object','--exact-id',MARKER_OWNER,
        '--include-related-field','local-markers','first','Time','--include-related','local-markers','any')
    assert code == 0,result
    views = result['agent_result'][0]['related']['projections']
    selected, = [view for view in views if view['spec'].get('stages')]
    assert selected['items'][0]['properties'] == {'Time':0.0}
    queries = [args['waql'] for uri,args,_ in task.calls if uri.endswith('object.get') and ' select ' in args.get('waql','')]
    assert queries and all('select @Markers' in query and query.endswith('take 1')
        and set(re.findall(r' take (\d+)',query)) == {'1'} for query in queries)


@pytest.mark.parametrize('change',['none','owner','class','metadata','value'])
def test_marker_result_pages_revalidate_exact_owner_class_metadata_and_zero_value(tmp_path, change):
    task = marker_task(tmp_path); task.row['notes'] = '音声' * 16000
    code,result = task.run('query-object','--exact-id',MARKER_OWNER,'--include','notes',
        '--include-related-field','local-markers','Time','--include-related-field','local-markers','Label')
    assert code == 0 and result['status'] == 'partial',result
    if change == 'owner': task.members[MARKER]['owner'] = {'id': OTHER}
    elif change == 'class': task.members[MARKER]['classId'] = 65077248
    elif change == 'metadata': task.metadata[5373968]['Time']['type'] = 'bool'
    elif change == 'value': task.members[MARKER]['@Time'] = 1.0
    code,continued = task.run(*result['agent_result']['next_command']['gateway_argv'])
    if change == 'none': assert code == 0 and continued['status'] == 'partial',continued
    else: assert code == 2 and continued['error_code'] == 'QUERY_RESULT_CONTINUATION_CHANGED',continued


def marker_record_task(tmp_path, version='2025.1'):
    from tests.unit.test_object_query_result_pages import QueryTask
    task = QueryTask(tmp_path, version)
    # Program transport built from R90's actual manual-member scalar values;
    # this is not a recorded plain-Markers composition or file-cue result.
    member = MARKER_PACKET['exact_read']['result']['return'][0]
    task.row = {'id':MARKER_OWNER,'name':'audit_outside','type':'AudioFileSource','path':r'\Sounds\audit_outside',
        'owner':{'id':SOUND,'name':'Sound'},
        'waapiMarkerRecords':[{'time':member['@Time'],'label':member['@Label'],'extension':{'retained':True}},
            {'time':1.25,'label':''}]}
    return task


def test_marker_records_fixed_composition_keeps_source_context_and_actual_records(tmp_path):
    task = marker_record_task(tmp_path)
    code,result = task.run('query-object','--exact-id',MARKER_OWNER,'--max-results','1',
        '--include','owner','--include','marker-records','--detail')
    assert code == 0,result
    row, = result['agent_result']
    assert {key:row[key] for key in ('id','name','type','path','owner')} == {key:task.row[key] for key in ('id','name','type','path','owner')}
    assert row['marker_records'] == task.row['waapiMarkerRecords']
    assert list(result)[-1] == 'agent_result'
    reads = [(args,options) for uri,args,options in task.calls if uri.endswith('object.get')]
    assert reads == [({'waql':f'from object "{MARKER_OWNER}" take 1'},
        {'return':['id','name','type','path','owner','Markers.{time,label} as waapiMarkerRecords']})]
    code,schema = task.run('query-schema','--output','marker-records')
    assert code == 0,schema
    output = schema['business_output']
    assert output['available'] is True and output['supported_versions'] == ['2023.1','2024.1','2025.1']
    assert output['computed_file_cue_semantics_proven'] is False
    assert output['native_definition'] is None and output['source']['wwise_build'] == '2025.1.7.9143'
    assert output['source']['composition'] == 'Markers.{time,label}'
    assert output['source']['alias_rule'] == 'EXPRESSION as NAME'
    assert output['result_scope'] == 'root AudioFileSource records; no canonical per-record identity or mutation authority'


@pytest.mark.parametrize('version', ['2021.1','2022.1','2023.1','2024.1','2025.1'])
def test_marker_records_schema_version_and_related_scope_are_explicit(tmp_path, version):
    task = marker_record_task(tmp_path, version)
    code,schema = task.run('query-schema','--output','marker-records')
    assert code == 0 and schema['business_output']['available'] is (version >= '2023.1'),schema
    assert schema['business_output']['supported_versions'] == ['2023.1','2024.1','2025.1']
    code,contract = task.run('query-schema')
    assert code == 0 and contract['related_outputs']['outputs']['marker-records']['available'] is False,contract
    code,result = task.run('query-object','--exact-id',MARKER_OWNER,'--include-related','parent','marker-records')
    assert code == 2 and result['error_code'] == 'GatewayInputError' and not task.calls,result
    if version < '2023.1':
        code,result = task.run('query-object','--exact-id',MARKER_OWNER,'--include','marker-records')
        assert code == 2 and result['error_code'] == 'GatewayInputError' and not task.calls,result
        assert '2023.1' in result['message']
    else:
        code,result = task.run('query-object','--exact-id',MARKER_OWNER,'--include','marker-records')
        assert code == 0 and result['agent_result'][0]['marker_records'] == task.row['waapiMarkerRecords'],result


@pytest.mark.parametrize('presence', ['missing','null','empty','missing-null-fields'])
def test_marker_records_preserve_actual_presence_and_native_values(tmp_path, presence):
    task = marker_record_task(tmp_path)
    if presence == 'missing': task.row.pop('waapiMarkerRecords')
    elif presence == 'null': task.row['waapiMarkerRecords'] = None
    elif presence == 'empty': task.row['waapiMarkerRecords'] = []
    else: task.row['waapiMarkerRecords'] = [{'time':-5.670529842376709},{'label':''},
        {'time':None,'label':None},{'extension':{'null':None,'enabled':False}}]
    code,result = task.run('query-object','--exact-id',MARKER_OWNER,'--include','marker-records')
    assert code == 0,result
    row, = result['agent_result']
    if presence == 'missing': assert 'marker_records' not in row and row['unavailable_fields'] == ['marker_records']
    else: assert row['marker_records'] == task.row['waapiMarkerRecords']


@pytest.mark.parametrize('value', ['records',[1],[{'time':False}],[{'time':'0'}],[{'label':42}]])
def test_marker_record_shape_errors_retain_the_original_bounded_packet(tmp_path, value):
    task = marker_record_task(tmp_path)
    task.row['waapiMarkerRecords'] = value
    packets = tmp_path/'packets'; task.env['WWISE_EVIDENCE_DIR'] = str(packets)
    code,result = task.run('query-object','--exact-id',MARKER_OWNER,'--include','marker-records')
    assert code == 2 and result['error_code'] == 'QUERY_MARKER_RECORDS_SHAPE',result
    assert result['details']['id'] == MARKER_OWNER and result['details']['native_key'] == 'waapiMarkerRecords'
    assert not result.get('agent_result')
    native = [json.loads(path.read_text()) for path in packets.glob('*.json')]
    packet, = [row for row in native if row['api'].endswith('object.get')]
    assert packet['result']['return'][0]['waapiMarkerRecords'] == value


def test_marker_record_roots_remain_independent_after_advanced_source_selection(tmp_path):
    task = marker_record_task(tmp_path)
    second = copy.deepcopy(task.row)
    second.update(id=RTPC2,name='Other source',owner={'id':OTHER,'name':'Other sound'},
        waapiMarkerRecords=[{'time':2,'label':'Other marker'}])
    original = task.call
    def native(uri,args=None,options=None):
        result = original(uri,args,options)
        if uri.endswith('object.get') and args != {'waql':'from type Project take 1'}:
            result = {'return':[copy.deepcopy(second),copy.deepcopy(task.row)]}
        return result
    task.call = native
    code,result = task.run('query-object','--advanced-waql','from type AudioFileSource','--max-results','2',
        '--include','owner','--include','marker-records')
    assert code == 0,result
    rows = result['agent_result']
    assert [(row['id'],row['owner'],row['marker_records']) for row in rows] == [
        (row['id'],row['owner'],row['waapiMarkerRecords']) for row in (second,task.row)]
    assert [(args,options) for uri,args,options in task.calls if uri.endswith('object.get')] == [
        ({'waql':'from type AudioFileSource take 2'},
         {'return':['id','name','type','path','owner','Markers.{time,label} as waapiMarkerRecords']})]


@pytest.mark.parametrize('change', ['none','native-result'])
def test_marker_record_pages_deliver_actual_values_and_reject_changed_native_records(tmp_path, change):
    task = marker_record_task(tmp_path)
    label = '声"\\\n' * 8000
    task.row['waapiMarkerRecords'] = [{'time':2.5,'label':label,'extension':{'kept':True}},
        {'time':0,'label':'second'}]
    code,page = task.run('query-object','--exact-id',MARKER_OWNER,'--max-results','1','--include','marker-records')
    assert code == 0 and page['status'] == 'partial',page
    if change != 'none':
        task.row['waapiMarkerRecords'][0]['label'] += '!'
        code,result = task.run(*page['agent_result']['next_command']['gateway_argv'])
        assert code == 2 and result['error_code'] == 'QUERY_RESULT_CONTINUATION_CHANGED' and not result.get('agent_result'),result
        return
    entries=[]; count=0
    while True:
        count += 1; assert count <= 32
        assert len(json.dumps(page,ensure_ascii=False,indent=2).encode()) <= 32*1024
        assert list(page)[-1] == 'agent_result'
        value=page['agent_result']; assert value['entries_encoding'] == 'json-pointer-entries'
        assert value['objects'][0]['id'] == MARKER_OWNER and value['page']['mutation_authority'] is False
        entries.extend(value['entries'])
        if value['projection_complete']: break
        code,page = task.run(*value['next_command']['gateway_argv'])
        assert code == 0,page
    assert ''.join(entry['value'] for entry in entries if entry['pointer']=='/objects/0/marker_records/0/label') == label
    assert [entry['value'] for entry in entries if entry['pointer']=='/objects/0/marker_records/0/time'] == [2.5]
    assert [entry['value'] for entry in entries if entry['pointer']=='/objects/0/marker_records/1/time'] == [0]
    assert [entry['value'] for entry in entries if entry['pointer']=='/objects/0/marker_records/1/label'] == ['second']
    assert [entry['value'] for entry in entries if entry['pointer']=='/objects/0/marker_records/0/extension/kept'] == [True]
    reads=[(args,options) for uri,args,options in task.calls if uri.endswith('object.get') and args!={'waql':'from type Project take 1'}]
    assert reads and all(read == ({'waql':f'from object "{MARKER_OWNER}" take 1'},
        {'return':['id','name','type','path','Markers.{time,label} as waapiMarkerRecords']}) for read in reads)


def test_marker_records_keep_existing_native_byte_ceiling_and_root_row_limit(tmp_path):
    task = marker_record_task(tmp_path)
    code,rejected = task.run('query-object','--exact-id',MARKER_OWNER,'--max-results','1001','--include','marker-records')
    assert code == 2 and rejected['error_code'] == 'SemanticValidationError' and not task.calls,rejected
    assert rejected['details'] == {'minimum':0,'maximum':1000,'take':1001}
    task.row['waapiMarkerRecords']=[{'time':0,'label':'x'*(1024*1024)}]
    code,result=task.run('query-object','--exact-id',MARKER_OWNER,'--max-results','1','--include','marker-records')
    assert code == 2 and result['call']['error_code'] == 'RESULT_TOO_LARGE' and not result.get('agent_result'),result
    assert len(json.dumps(result,ensure_ascii=False,indent=2).encode()) <= 32*1024
    assert sum(uri.endswith('object.get') for uri,_,_ in task.calls) == 1


def test_marker_records_preserve_native_rejection_without_retry_or_mode_claim(tmp_path):
    task=marker_record_task(tmp_path); original=task.call
    def native(uri,args=None,options=None):
        if uri.endswith('object.get') and args!={'waql':'from type Project take 1'}:
            task.calls.append((uri,args,options)); raise RuntimeError('selected Marker record projection rejected')
        return original(uri,args,options)
    task.call=native
    code,result=task.run('query-object','--exact-id',MARKER_OWNER,'--include','marker-records')
    assert code == 2 and result['call']['ok'] is False and not result.get('agent_result'),result
    assert result['call']['error_code'] == 'RuntimeError' and 'selected Marker record projection rejected' in result['call']['message']
    assert sum(uri.endswith('object.get') for uri,_,_ in task.calls) == 1
