"""One no-setup2021 public ControlInput witness on the existing owned lifecycle."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from tests.destructive.support.source_copy_fixture import read_file, sha, xml, _reject_symlink_chain
from tests.destructive.test_gateway_workflow_transaction_matrix import workflow_sandbox_runtime, waapi_gateway
from tests.destructive.test_query_list_sequences import BUILDS, READ_APIS as COMMON_READ_APIS, _page_value
from wwise_waapi.canonical import canonical_json_bytes, canonical_sha256

pytestmark=[pytest.mark.live,pytest.mark.destructive,
    pytest.mark.skipif(os.environ.get('WWISE_VERSION')!='2021.1',reason='Selected legacy ControlInput representation is2021.1')]
REPO=Path(__file__).resolve().parents[2]
SOURCE='{95DDA32B-B666-4269-A54C-5ABF4E201C99}'
RTPC='{CE99046D-D354-422D-A7BB-F1305FF00B2F}'
LFO='{E323F786-253F-48C6-86B9-AB0335804E9F}'
CURVE='{0B357DC6-5FE7-4E50-9C31-23CDE7F34307}'
SOUND='{63E5A1E6-4265-463E-A5C5-322F742423E1}'
RELATIVE=Path('Actor-Mixer Hierarchy/MIDI.wwu')
PIN='4f4839e0457831e6d85c012847159b6f410c8716ec9a6c4ab6e9f888ff3c39e3'
READ_APIS=COMMON_READ_APIS
MAX_DISPATCHES=128
MAX_PACKET_BYTES=8*1024*1024
IDENTITY=('id','name','type','path')


def source_frame(runtime):
    source=runtime.sandbox.source_root/RELATIVE
    owned=runtime.sandbox.sandbox_path/RELATIVE
    assert runtime.sandbox.source_root.resolve()!=runtime.sandbox.sandbox_path.resolve()
    _reject_symlink_chain(source,owned_input=runtime.sandbox.source_root,label='original MIDI');_reject_symlink_chain(owned,owned_input=runtime.sandbox.sandbox_path,label='prepared MIDI')
    assert source.resolve().is_relative_to(runtime.sandbox.source_root.resolve())
    assert owned.resolve().is_relative_to(runtime.sandbox.sandbox_path.resolve())
    raw=read_file(source,4*1024*1024);prepared=read_file(owned,4*1024*1024)
    # The current workflow normalizes only2022/2025. Its2021 branch is copy-only.
    assert sha(raw)==PIN and sha(prepared)==PIN,'Source or prepared2021 MIDI bytes changed'
    tree=xml(raw);copy_tree=xml(prepared)
    node,=[row for row in tree.iter('SourcePlugin') if row.get('ID')==SOURCE]
    assert node.attrib['PluginName']=='Wwise Synth One' and node.attrib['PluginID']=='148' and node.attrib['CompanyID']=='0'
    prop,=node.findall('./PropertyList/Property[@Name="OutputLevel"]')
    rtpc,=prop.findall('./RTPCList/RTPC');assert rtpc.get('ID')==RTPC
    assert len(list(node.iter('RTPC')))==1
    lfo,=rtpc.findall('./ReferenceList/Reference[@Name="ControlInput"]/Custom/ModulatorLfo');assert lfo.get('ID')==LFO
    curve,=rtpc.findall('./Curve');assert curve.get('ID')==CURVE
    stored={p.get('Name'):p.get('Value') for p in lfo.findall('./PropertyList/Property')}
    assert {name:float(stored[name]) for name in ('LfoFrequency','LfoDepth')}=={'LfoFrequency':4.0,'LfoDepth':90.0}
    def business(n):
        return {'tag':n.tag,'attributes':dict(n.attrib),'text':n.text if n.text and n.text.strip() else None,
            'tail':n.tail if n.tail and n.tail.strip() else None,'children':[business(child) for child in n]}
    subtrees={}
    for identity,kind in [(SOURCE,'SourcePlugin'),(RTPC,'RTPC'),(LFO,'ModulatorLfo'),(CURVE,'Curve')]:
        original,=[row for row in tree.iter(kind) if row.get('ID')==identity]
        copied,=[row for row in copy_tree.iter(kind) if row.get('ID')==identity]
        assert canonical_json_bytes(business(original))==canonical_json_bytes(business(copied))
        subtrees[identity]=canonical_sha256(business(original))
    return {'relative_path':RELATIVE.as_posix(),'source_sha256':sha(raw),'prepared_sha256':sha(prepared),
        'source_bytes':len(raw),'prepared_bytes':len(prepared),'source_mtime_ns':source.stat().st_mtime_ns,
        'prepared_mtime_ns':owned.stat().st_mtime_ns,'business_subtrees':subtrees}


def test_legacy_control_input_typed_reads_keep_exact_rtpc_and_lfo_scope(workflow_sandbox_runtime,monkeypatch):
    runtime=workflow_sandbox_runtime
    assert runtime.version=='2021.1'
    assert tuple(runtime.sandbox.metadata.get_info_version[key] for key in ('year','major','minor','build'))==BUILDS[runtime.version]
    output=runtime.state_dir/'query-legacy-control-input.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    _reject_symlink_chain(output.parent,owned_input=runtime.state_dir,label='observation parent')
    assert output.parent.resolve()==output.parent and not output.exists() and not output.is_symlink()
    evidence_root=Path(runtime.env['WWISE_EVIDENCE_DIR'])
    observation={'candidate':runtime.candidate,'version':runtime.version,'read_only':True,'transaction_count':0,
        'groups':[],'business_effect_verified':False,'typed_control_input_projection_proof':False,
        'boundary':'exact legacy reference kind and related LFO values; no old PropertyName or Curve points claim'}
    category={'category':'query-legacy-control-input','status':'FAIL','observation_path':str(output),
        'verifier_strength':'fresh_exact_scope_inventory_kind_source_typed_reference_lfo_values_and_preservation'}
    runtime.category_results.append(category)
    status='FAIL';dispatch_count=0;packet_bytes=0;continuations=0
    original_dispatch=waapi_gateway.WwiseDispatcher.dispatch

    def group(label):
        assert len(observation['groups'])<5
        current={'label':label,'invocations':[]};observation['groups'].append(current);return current

    def read(current,argv):
        nonlocal dispatch_count,packet_bytes,continuations
        entries=[];encoding=None;offset=0;first=True;initial=None;all_calls=[];packets={}
        while True:
            assert sum(len(item['invocations']) for item in observation['groups'])<16
            before=set(evidence_root.glob('*.json'));calls=[]
            invocation={'argv':list(argv),'dispatch_calls':calls,'native_packets':[]};current['invocations'].append(invocation)
            def capture(dispatcher,api,**kwargs):
                nonlocal dispatch_count
                assert dispatch_count<MAX_DISPATCHES
                dispatch_count+=1
                call={'api':api,**copy.deepcopy({key:kwargs.get(key) for key in ('version','args','options')})};calls.append(call)
                result=original_dispatch(dispatcher,api,**kwargs)
                call.update(ok=result['ok'],evidence_path=result.get('evidence_path'),result_sha256=canonical_sha256(result.get('result')))
                return result
            with monkeypatch.context() as patch:
                patch.setattr(waapi_gateway.WwiseDispatcher,'dispatch',capture)
                code,payload=(runtime.raw_gateway(argv) if first else waapi_gateway.execute_gateway(argv,env=runtime.env))
            invocation.update(exit_code=code,payload=payload);all_calls.extend(calls)
            paths=sorted(set(evidence_root.glob('*.json'))-before)
            assert len(paths)<=MAX_DISPATCHES
            for path in paths:
                body=read_file(path,8*1024*1024);packet_bytes+=len(body);assert packet_bytes<=MAX_PACKET_BYTES
                invocation['native_packets'].append({'path':str(path),'bytes':len(body),'sha256':sha(body)})
                packet=json.loads(body);assert packet['api'] in READ_APIS
                packets[str(path)]=packet
            assert {call['evidence_path'] for call in calls}=={str(path) for path in paths}
            for call in calls:
                packet=packets[call['evidence_path']]
                assert packet['api']==call['api'] and call['version']==runtime.version
                assert call['ok'] is packet['ok'] is True
                assert canonical_sha256(packet['result'])==call['result_sha256']
            assert code==0 and payload.get('ok') is True,payload
            assert list(payload)[-1]=='agent_result'
            if first:initial=payload
            value=payload['agent_result']
            if not isinstance(value,dict) or 'entries_encoding' not in value:
                assert not entries and payload.get('projection_complete') is not False
                return value,all_calls,packets
            if encoding is None:encoding=value['entries_encoding']
            assert encoding==value['entries_encoding'] and value['page']['offset']==offset
            entries.extend(value['entries']);offset+=len(value['entries']);assert value['page']['next_offset']==offset
            if value['projection_complete']:return _page_value(entries,encoding)['objects'],all_calls,packets
            assert continuations<4,'Unexpected delivery growth; no retry or raised limit'
            continuations+=1;argv=value['next_command']['gateway_argv'];first=False
            assert 'query-object' in argv and '--result-query' in argv and '--result-page' in argv

    def exact(current,identity,*fields):
        value,calls,packets=read(current,['query-object','--exact-id',identity,'--max-results','1',
            '--include','class-id','--include','owner',*fields])
        assert isinstance(value,list) and len(value)==1,value
        row,=value;assert row['id']==identity
        assert all(isinstance(row[key],str) for key in IDENTITY) and row['path']
        return row,calls,packets

    def identity(row,identity,kind,class_id,owner=None):
        assert row['id']==identity and row['type']==kind and row['class_id']==class_id
        assert type(row['class_id']) is int
        if owner is not None:assert row['owner']['id']==owner

    def values(row):
        assert isinstance(row.get('properties'),dict) and {'LfoFrequency','LfoDepth'}<=set(row['properties']),row
        fields=row['properties']
        for name,expected in [('LfoFrequency',4),('LfoDepth',90)]:
            assert type(fields[name]) in (int,float) and math.isfinite(fields[name]) and fields[name]==expected
        return {name:fields[name] for name in ('LfoFrequency','LfoDepth')}

    def baseline(current):
        source,_,_=exact(current,SOURCE)
        identity(source,SOURCE,'SourcePlugin',9699330)
        rtpc,_,_=exact(current,RTPC,'--include-field','Color','--include-field','OverrideColor')
        identity(rtpc,RTPC,'RTPC',1441808,SOURCE)
        assert type(rtpc['properties']['Color']) is int and type(rtpc['properties']['OverrideColor']) is bool
        lfo,_,_=exact(current,LFO,'--include-field','LfoFrequency','--include-field','LfoDepth')
        identity(lfo,LFO,'ModulatorLfo',4194320,RTPC);values(lfo)
        return {'source':source,'rtpc':rtpc,'lfo':lfo}

    def native_rows(calls,packets):
        return [(call,packets[call['evidence_path']]['result']['return']) for call in calls
            if call['api']=='ak.wwise.core.object.get']

    def typed_reference(value):
        assert isinstance(value,dict) and value.get('id')==LFO

    def related(context):
        assert context['object']['id']==LFO
        values(context)

    try:
        before=source_frame(runtime);observation['source_before']=before
        initial=baseline(group('baseline-before'));observation['baseline_before']=initial
        current=group('root-ordinary-local-reference')
        row,calls,packets=exact(current,RTPC,'--include-field','ControlInput','--include-local-reference','ControlInput')
        identity(row,RTPC,'RTPC',1441808,SOURCE)
        assert 'ControlInput' in row.get('references',{}) and 'ControlInput' in row.get('local_references',{}),row
        typed_reference(row['references']['ControlInput']);typed_reference(row['local_references']['ControlInput'])
        selected=[raw for call,rows in native_rows(calls,packets) if set(('ControlInput','@ControlInput'))<=set((call['options'] or {}).get('return',[])) for raw in rows]
        raw,=selected;typed_reference(raw['ControlInput']);typed_reference(raw['@ControlInput'])
        infos=[packets[c['evidence_path']]['result'] for c in calls if c['api'].endswith('getPropertyInfo')
            and (c['args'] or {}).get('property')=='ControlInput']
        assert infos and all(info.get('type') in (None,'') and not info.get('restriction') for info in infos)
        current=group('ordinary-local-singleton-lfo-values')
        flags=['query-object','--exact-id',RTPC,'--max-results','1']
        for mode in ('reference','local-reference'):
            for field in ('LfoFrequency','LfoDepth'):
                flags+=['--include-related-field',mode,'ControlInput',field]
        rows,calls,packets=read(current,flags)
        row,=rows;assert row['id']==RTPC
        related(row['related']['references']['ControlInput']);related(row['related']['local_references']['ControlInput'])
        for prefix in ('ControlInput','@ControlInput'):
            selected=[raw for call,rows in native_rows(calls,packets)
                if {prefix+'.@LfoFrequency',prefix+'.@LfoDepth'}<=set((call['options'] or {}).get('return',[])) for raw in rows]
            assert selected
            for raw in selected:
                assert raw[prefix]['id']==LFO and raw[prefix+'.classId']==4194320
                assert raw[prefix+'.@LfoFrequency']==4 and raw[prefix+'.@LfoDepth']==90
        current=group('combined-reference-occurrences')
        flags=['query-object','--exact-id',RTPC,'--max-results','1']
        for field in ('LfoFrequency','LfoDepth'):
            flags+=['--include-related-field','combine','reference','ControlInput','and','local-reference','ControlInput','end',field]
        rows,calls,packets=read(current,flags)
        row,=rows;assert row['id']==RTPC
        projection,=row['related']['projections'];items=projection['items'];assert len(items)==2
        assert [item['origin']['arm'] for item in items]==[0,1]
        for item in items:related(item)
        actual_members=[raw for call,rows in native_rows(calls,packets) for raw in rows
            if raw.get('id')==LFO and {'@LfoFrequency','@LfoDepth'}<=set(raw)]
        assert actual_members
        for raw in actual_members:
            assert raw['type']=='ModulatorLfo' and raw['classId']==4194320
            values({'properties':{'LfoFrequency':raw['@LfoFrequency'],'LfoDepth':raw['@LfoDepth']}})
        final=baseline(group('baseline-after'));assert canonical_json_bytes(final)==canonical_json_bytes(initial)
        observation['baseline_after']=final
        assert source_frame(runtime)==before
        observation.update(business_effect_verified=True,typed_control_input_projection_proof=True)
        status='PASS'
    except BaseException as exc:
        observation['error']=f'{type(exc).__name__}: {exc}';raise
    finally:
        observation.update(dispatch_count=dispatch_count,packet_bytes=packet_bytes,continuation_count=continuations,
            invocation_count=sum(len(row['invocations']) for row in observation['groups']))
        body=json.dumps(observation,ensure_ascii=False,indent=2).encode();bounded=len(body)<=16*1024*1024
        if not bounded:
            status='FAIL';observation.update(business_effect_verified=False,typed_control_input_projection_proof=False,
                finalization_error='Observation exceeded16MiB; retained without truncation')
            body=json.dumps(observation,ensure_ascii=False,indent=2).encode()
        with output.open('xb') as stream:stream.write(body)
        category.update(status=status,observation_sha256=sha(body),business_effect_verified=observation['business_effect_verified'])
        assert bounded,'Finalized observation exceeded16MiB; no native PASS'
