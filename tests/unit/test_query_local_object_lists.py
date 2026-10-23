"""Owner-preserving, source-certified local RTPC/EffectSlot projections."""
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
        if uri.endswith('object.get') and re.search(r' select @(RTPC|Effects)',waql):
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
    code,result = task.run('query-object','--exact-id',SOUND,'--include-related',source,'count')
    if available:
        assert code == 0,result
        assert result['agent_result'][0]['related']['projections'][0]['value'] == 2
    else:
        assert code == 2 and not any(uri.endswith('object.get') for uri,_,_ in task.calls),result


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
