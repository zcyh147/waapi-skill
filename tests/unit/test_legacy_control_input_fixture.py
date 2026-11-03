"""The2021 witness uses the real public Gateway and injected read transport."""
import copy
import json
from pathlib import Path
import re
import shutil
from types import SimpleNamespace

import pytest

from tests.unit.test_query_legacy_control_input import LegacyTask
from tests.unit.test_workflow_source_guard import workflow


@pytest.mark.parametrize('fault',['none','wrong-class','wrong-owner','missing-reference','prepared-drift'])
def test_legacy_control_input_witness_runs_whole_public_flow_and_stops_bad_facts(tmp_path,workflow,monkeypatch,fault):
    from tests.destructive import test_query_legacy_control_input as witness
    source=tmp_path/'source';owned=tmp_path/'owned';sandbox=owned/'project'
    original=witness.REPO/'tests/_org/2021.1'
    for relative in [Path('SampleProject.wproj'),*(path.relative_to(original) for path in original.rglob('*.wwu'))]:
        target=source/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original/relative,target)
    shutil.copytree(source,sandbox)
    # Exercise the actual helper with the matching no-modifier request. The live
    # workflow skips this helper on2021; both paths must retain the same bytes.
    prelaunch_io=owned/'prelaunch-io';prelaunch_io.mkdir()
    prepared=workflow.normalize_project_copy(sandbox/'SampleProject.wproj',io_root=prelaunch_io,owned_root=owned,
        request=workflow.ProjectPrelaunchRequest(scenario_id='gateway-workflow-transaction-matrix'))
    (owned/'prelaunch-helper-report.json').write_text(json.dumps(prepared.as_dict(),indent=2))
    task_root=tmp_path/'transport';task_root.mkdir();task=LegacyTask(task_root)
    task.info['version'].update(dict(zip(('year','major','minor','build'),witness.BUILDS['2021.1'])))
    task.info['isCommandLine']=True;task.project['filePath']=str(sandbox/'SampleProject.wproj')
    runtime=SimpleNamespace(version='2021.1',candidate='program-only',category_results=[],state_dir=owned/'state',
        sandbox=SimpleNamespace(source_root=source,sandbox_path=sandbox,metadata=SimpleNamespace(get_info_version=task.info['version'])),env=task.env)
    facts=witness.source_frame(runtime);assert facts['source_sha256']==facts['prepared_sha256']
    samples=json.loads((witness.REPO/'tests/fixtures/query-legacy-control-input/native-metadata.json').read_text())['scopes']
    task.metadata={}
    for identity,class_id in [(witness.RTPC,1441808),(witness.LFO,4194320)]:
        task.metadata[identity]={name:copy.deepcopy(row['metadata']) for name,row in samples[identity].items()}
        task.metadata[class_id]=copy.deepcopy(task.metadata[identity])
    task.objects[witness.SOURCE]={'id':witness.SOURCE,'name':'Wwise Synth One','type':'SourcePlugin','classId':9699330,
        'path':r'\Actor-Mixer Hierarchy\MIDI\Synth\Wwise Synth One','parent':{'id':witness.SOUND}}
    task.objects[witness.RTPC].update({'@Color':0,'@OverrideColor':False,'ControlInput.classId':4194320,
        '@ControlInput.classId':4194320,'ControlInput.@LfoFrequency':4,'ControlInput.@LfoDepth':90,
        '@ControlInput.@LfoFrequency':4,'@ControlInput.@LfoDepth':90})
    task.objects[witness.LFO]={'id':witness.LFO,'name':'Modulator LFO (Custom)','type':'ModulatorLfo','classId':4194320,
        'path':r'\Actor-Mixer Hierarchy\MIDI\Synth\Wwise Synth One\[RTPC: Output Level, Modulator LFO (Custom)]',
        'owner':{'id':witness.RTPC},'@LfoFrequency':4,'@LfoDepth':90}
    original_call=task.call;phase=''
    def native(uri,args=None,options=None):
        if uri.endswith('object.get') and (args or {}).get('waql')=='from type Project take 1':
            task.calls.append((uri,args,options));return {'return':[task.projection(task.project,options['return'])]}
        if uri.endswith('object.get') and re.search(r' select @?ControlInput(?: |$)',(args or {}).get('waql','')):
            task.calls.append((uri,args,options));result={'return':[task.projection(task.objects[witness.LFO],options['return'])]}
        else:result=original_call(uri,args,options)
        if phase=='root' and uri.endswith('object.get'):
            for row in result['return']:
                if row.get('id')!=witness.RTPC:continue
                if fault=='wrong-class' and 'classId' in row:row['classId']=65552
                elif fault=='wrong-owner' and 'owner' in row:row['owner']={'id':witness.LFO}
                elif fault=='missing-reference':row.pop('@ControlInput',None)
        return result
    task.call=native
    packets=owned/'packets';packets.mkdir();task.env.update(WWISE_EVIDENCE_DIR=str(packets),WAAPI_SKILL_STATE_DIR=str(runtime.state_dir))
    attempts=[]
    def forbidden(url):
        attempts.append(url);raise AssertionError('Fake witness must stop before a real client or socket')
    monkeypatch.setattr(workflow.waapi_gateway,'default_client_factory',forbidden)
    execute=workflow.waapi_gateway.execute_gateway
    def injected(argv,**kwargs):return execute(argv,client_factory=lambda _:task,**kwargs)
    monkeypatch.setattr(workflow.waapi_gateway,'execute_gateway',injected)
    def raw(argv):
        nonlocal phase
        phase='root' if '--include-field' in argv and 'ControlInput' in argv else 'other'
        return workflow.waapi_gateway.execute_gateway(['--timeout','30','--state-dir',str(runtime.state_dir),*argv],env=runtime.env)
    runtime.raw_gateway=raw
    if fault=='prepared-drift':(sandbox/witness.RELATIVE).write_bytes((sandbox/witness.RELATIVE).read_bytes()+b'\n')
    if fault=='none':witness.test_legacy_control_input_typed_reads_keep_exact_rtpc_and_lfo_scope(runtime,monkeypatch)
    else:
        with pytest.raises(AssertionError):witness.test_legacy_control_input_typed_reads_keep_exact_rtpc_and_lfo_scope(runtime,monkeypatch)
    assert not attempts
    category,=runtime.category_results
    body=Path(category['observation_path']).read_bytes();assert witness.sha(body)==category['observation_sha256']
    receipt=json.loads(body);assert category['status']==('PASS' if fault=='none' else 'FAIL')
    assert receipt['business_effect_verified'] is (fault=='none')
    if fault=='none':
        assert len(receipt['groups'])==5 and receipt['dispatch_count']>0 and receipt['transaction_count']==0
        assert receipt['continuation_count']==0
    elif fault=='prepared-drift':assert receipt['groups']==[] and receipt['dispatch_count']==0
