"""Prepared local-list witness at the real Gateway / injected native boundary."""
import copy
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from tests.unit.test_query_local_object_lists import LocalListTask
from tests.unit.test_workflow_source_guard import workflow


@pytest.mark.parametrize('version',['2025.1','2022.1'])
@pytest.mark.parametrize('fault',['none','object-metadata','wrong-class','wrong-owner','missing-member'])
def test_local_list_witness_uses_real_gateway_and_stops_invalid_members(tmp_path,workflow,monkeypatch,version,fault):
    from tests.destructive import test_query_local_list_outputs as witness
    source=tmp_path/'source';owned=tmp_path/'owned';sandbox=owned/'project'
    for relative in witness.source_paths(version):
        target=source/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(witness.REPO/'tests/_org'/version/relative,target)
    (source/'SampleProject.wproj').write_text('<WwiseDocument/>')
    shutil.copytree(source,sandbox)
    task_root=tmp_path/'transport';task_root.mkdir()
    task=LocalListTask(task_root,version)
    task.info['version'].update(dict(zip(('year','major','minor','build'),witness.BUILDS[version])))
    task.info['isCommandLine']=True;task.project['filePath']=str(sandbox/'SampleProject.wproj')
    runtime=SimpleNamespace(version=version,candidate='program-only',category_results=[],state_dir=owned/'state',
        sandbox=SimpleNamespace(source_root=source,sandbox_path=sandbox,
            metadata=SimpleNamespace(get_info_version=task.info['version'])),env=task.env)
    facts=witness.source_frame(runtime)
    fixture=json.loads((witness.REPO/'tests/fixtures/query-local-lists/native-metadata.json').read_text())
    task.objects={}
    prefix='\\Containers' if version=='2025.1' else '\\Actor-Mixer Hierarchy'
    for identity,expected in facts['owners'].items():
        task.objects[identity]={'id':identity,'name':expected['name'],'type':expected['type'],'classId':expected['class_id'],
            'path':prefix+'\\'+expected['name'],expected['native']:[{'id':member,'name':''} for member in expected['members']]}
    for identity,expected in facts['members'].items():
        row={'id':identity,'name':'','type':expected['type'],'classId':expected['class_id'],
            'path':prefix+'\\'+identity,'owner':{'id':expected['owner']}}
        if expected['type']=='RTPC':
            curve=expected['curve']
            points=[{'x':x,'y':y,'shape':'Linear'} for x,y in facts['curves'][curve]['xy']]
            row.update({'@PropertyName':expected['property'],'ControlInput':{'id':expected['control_input']},
                'Curve':{'id':curve,'points':copy.deepcopy(points),'@Flags':3},'Curve.classId':917520,'Curve.points':points})
            task.objects[curve]={'id':curve,'name':'','type':'Curve','classId':917520,'path':prefix+'\\'+curve,
                'owner':{'id':identity},'points':points}
        else:
            row.update({'@Bypass':fixture['slot_boolean_sample']['Bypass'],'@Render':fixture['slot_boolean_sample']['Render'],'Effect':{'id':expected['effect']},
                'Effect.classId':7733251,'Effect.pluginName':'Wwise RoomVerb'})
            task.objects[expected['effect']]={'id':expected['effect'],'name':'Bright_Small_Hall_Env','type':'Effect',
                'classId':7733251,'path':'\\Effects\\Bright_Small_Hall_Env','pluginName':'Wwise RoomVerb'}
        task.objects[identity]=row
    task.row=task.objects[witness.SOUND];task.rows=[task.row]
    task.metadata={int(key):copy.deepcopy(value) for key,value in fixture['versions'][version]['metadata'].items()}
    for identity,row in task.objects.items():
        if row['classId'] in task.metadata:task.metadata[identity]=copy.deepcopy(task.metadata[row['classId']])
    if fault=='object-metadata':task.metadata[1441808]={}
    original=task.call;phase=''
    def native(uri,args=None,options=None):
        if uri.endswith('object.get') and (args or {}).get('waql','').startswith('from type Project take '):
            task.calls.append((uri,args,options));return {'return':[task.projection(task.project,options['return'])]}
        result=original(uri,args,options)
        if phase=='sound-full' and uri.endswith('object.get') and fault not in {'none','object-metadata'}:
            def change(value):
                if isinstance(value,dict):
                    if value.get('id')==witness.SOUND_RTPCS[0]:
                        if fault=='wrong-class':value['classId']=65552
                        elif fault=='wrong-owner':value['owner']={'id':witness.SOURCE}
                    for key,item in list(value.items()):
                        if isinstance(item,list) and fault=='missing-member':value[key]=[row for row in item if not isinstance(row,dict) or row.get('id')!=witness.SOUND_RTPCS[0]]
                        change(value[key])
                elif isinstance(value,list):
                    for item in value:change(item)
            change(result)
        return result
    task.call=native
    packets=owned/'packets';packets.mkdir()
    task.env.update(WWISE_EVIDENCE_DIR=str(packets),WAAPI_SKILL_STATE_DIR=str(runtime.state_dir))
    attempts=[]
    def forbidden(url):
        attempts.append(url);raise AssertionError('Fake witness must stop before a real client or socket')
    monkeypatch.setattr(workflow.waapi_gateway,'default_client_factory',forbidden)
    execute=workflow.waapi_gateway.execute_gateway
    def injected(argv,**kwargs):return execute(argv,client_factory=lambda _:task,**kwargs)
    monkeypatch.setattr(workflow.waapi_gateway,'execute_gateway',injected)
    def raw(argv):
        nonlocal phase
        phase='sound-full' if '--include-related-field' in argv and 'first' not in argv and witness.SOUND in argv else 'other'
        return workflow.waapi_gateway.execute_gateway(['--timeout','30','--state-dir',str(runtime.state_dir),*argv],env=runtime.env)
    runtime.raw_gateway=raw
    if fault in {'none','object-metadata'}:witness.test_local_rtpc_and_effect_slot_outputs_keep_actual_owners(runtime,monkeypatch)
    else:
        with pytest.raises(AssertionError):witness.test_local_rtpc_and_effect_slot_outputs_keep_actual_owners(runtime,monkeypatch)
    assert not attempts
    category,=runtime.category_results
    body=Path(category['observation_path']).read_bytes();assert witness.sha(body)==category['observation_sha256']
    receipt=json.loads(body)
    assert category['status']==('PASS' if fault in {'none','object-metadata'} else 'FAIL')
    assert receipt['business_effect_verified'] is (fault in {'none','object-metadata'})
    if fault in {'none','object-metadata'}:
        assert len(receipt['groups'])==(6 if version=='2025.1' else 5)
        assert receipt['dispatch_count']>0 and receipt['transaction_count']==0
    else:assert receipt['groups'][-1]['label']=='sound-full'
