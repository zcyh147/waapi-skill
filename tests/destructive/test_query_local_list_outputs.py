"""Read-only local RTPC / EffectSlot business projections on owned project copies."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from tests.destructive.support.source_copy_fixture import read_file, sha
from tests.destructive.test_gateway_workflow_transaction_matrix import workflow_sandbox_runtime, waapi_gateway
from tests.destructive.test_query_list_sequences import BUILDS, READ_APIS, _page_value
from wwise_waapi.canonical import canonical_json_bytes, canonical_sha256

pytestmark=[pytest.mark.live,pytest.mark.destructive,
    pytest.mark.skipif(os.environ.get('WWISE_VERSION') not in {'2022.1','2025.1'},
        reason='Selected local-list RETURN backends are2025.1 composed and2022.1 GUID-grouped')]
REPO=Path(__file__).resolve().parents[2]
SOUND='{63E5A1E6-4265-463E-A5C5-322F742423E1}'
SOURCE='{95DDA32B-B666-4269-A54C-5ABF4E201C99}'
AUXBUS='{9B518943-213A-4E65-8B0F-99440709822A}'
SOUND_RTPCS=('{4AD8A39B-B005-4572-9A98-0A60BDB55A80}','{482C90B6-387C-4E86-8228-B5E4DA392451}')
SOURCE_RTPC='{CE99046D-D354-422D-A7BB-F1305FF00B2F}'
SLOT='{36FF6043-98B5-407B-99C0-CEA8AF191E6E}'
EFFECT='{4D11F2B7-6057-4887-A725-F00E1629699E}'
PINS={'2022.1':('41784c1030c678d9a7f19a105dfb48e46fb8b76b044e9a3bdb8f2da885f61c3a',),
    '2025.1':('b8fc20794cc3d6b7ac17f5bd67fd57d297098830c52e985d44318f459da9c0df',
        '0d06c10e0e632bdb723d00922d38e1796561c781b11c8d71f5b7eeedb10130b6')}
# Existing workflow normalize_project_copy's exact 2025 Auro profile removes an
# unrelated bus reference and serializes that WWU. The selected MIDI is intact.
PREPARED_PINS={**PINS,'2025.1':(PINS['2025.1'][0],
    'dbd6e902dd8f062900f3c7e6ed38c55998d1af194e7d77d5d56c3e11f455992a')}
IDENTITY=('id','name','type','path')
MAX_DISPATCHES=384
MAX_PACKET_BYTES=32*1024*1024


def source_paths(version):
    paths=[Path('Containers' if version=='2025.1' else 'Actor-Mixer Hierarchy')/'MIDI.wwu']
    if version=='2025.1':paths.append(Path('Busses/Default Work Unit.wwu'))
    return paths


def source_frame(runtime):
    """Independent full WWU source/owned-copy evidence; no edits or inferred defaults."""
    frames=[];trees=[];prepared_trees=[]
    for relative,pin,prepared_pin in zip(source_paths(runtime.version),PINS[runtime.version],PREPARED_PINS[runtime.version]):
        source=runtime.sandbox.source_root/relative;owned=runtime.sandbox.sandbox_path/relative
        assert source.resolve()!=owned.resolve() and not source.is_symlink() and not owned.is_symlink()
        body=read_file(source,4*1024*1024);assert sha(body)==pin
        prepared=read_file(owned,4*1024*1024);assert sha(prepared)==prepared_pin,'Prepared WWU bytes drifted'
        frames.append({'relative_path':relative.as_posix(),'sha256':pin,'prepared_sha256':prepared_pin,
            'source_bytes':len(body),'prepared_bytes':len(prepared),'source_mtime_ns':source.stat().st_mtime_ns,
            'owned_mtime_ns':owned.stat().st_mtime_ns})
        trees.append(ET.fromstring(body))
        prepared_trees.append(ET.fromstring(prepared))
    owners={};members={};curves={}
    selected=[(SOUND,'Sound','Synth',65552,SOUND_RTPCS),(SOURCE,'SourcePlugin','Wwise Synth One',9699330,(SOURCE_RTPC,))]
    for identity,kind,name,class_id,expected in selected:
        node,=[row for row in trees[0].iter() if row.tag==kind and row.get('ID')==identity]
        assert node.tag==kind and node.get('Name')==name
        lists=[row for row in node.findall('./ObjectLists/ObjectList') if row.get('Name')=='RTPC']
        rtpcs=[row for group in lists for row in group.iter('RTPC')]
        assert tuple(row.get('ID') for row in rtpcs)==expected
        owners[identity]={'name':name,'type':kind,'class_id':class_id,'native':'@RTPC','members':list(expected)}
        for rtpc in rtpcs:
            prop,=[row for row in rtpc.findall('./PropertyList/Property') if row.get('Name')=='PropertyName']
            refs={row.get('Name'):row for row in rtpc.findall('./ReferenceList/Reference')}
            control=list(refs['ControlInput'].findall('./ObjectRef'))+list(refs['ControlInput'].findall('./Custom/*'))
            input_node,=control;curve,=refs['Curve'].findall('./Custom/Curve')
            members[rtpc.get('ID')]={'type':'RTPC','class_id':1441808,'owner':identity,'property':prop.get('Value'),
                'control_input':input_node.get('ID'),'curve':curve.get('ID')}
            points=curve.findall('./PointList/Point')
            assert points
            curves[curve.get('ID')]={'owner':rtpc.get('ID'),
                'xy':[[float(row.findtext('XPos')),float(row.findtext('YPos'))] for row in points]}
    assert [members[identity]['property'] for identity in SOUND_RTPCS]==['Volume','Volume']
    assert len({members[identity]['control_input'] for identity in SOUND_RTPCS})==2
    if runtime.version=='2025.1':
        bus,=[row for row in trees[1].iter('AuxBus') if row.get('ID')==AUXBUS]
        slots=[row for group in bus.findall('./ObjectLists/ObjectList') if group.get('Name')=='Effects' for row in group]
        slot,=slots;assert slot.tag=='EffectSlot' and slot.get('ID')==SLOT
        ref,=slot.findall('./ReferenceList/Reference/ObjectRef');assert ref.get('ID')==EFFECT
        owners[AUXBUS]={'name':bus.get('Name'),'type':'AuxBus','class_id':3997712,'native':'@Effects','members':[SLOT]}
        members[SLOT]={'type':'EffectSlot','class_id':5505040,'owner':AUXBUS,'effect':EFFECT}
    def business_xml(node):
        # Wwise's scalar/reference data and child order are preserved; only XML
        # formatting whitespace disappears. Non-whitespace text/tails stay exact.
        return {'tag':node.tag,'attributes':dict(node.attrib),
            'text':node.text if node.text and node.text.strip() else None,
            'tail':node.tail if node.tail and node.tail.strip() else None,
            'children':[business_xml(child) for child in node]}
    selected={**{identity:row['type'] for identity,row in owners.items()},
        **{identity:row['type'] for identity,row in members.items()},**{identity:'Curve' for identity in curves}}
    subtrees={}
    for identity,kind in selected.items():
        original,=[node for tree in trees for node in tree.iter(kind) if node.get('ID')==identity]
        prepared,=[node for tree in prepared_trees for node in tree.iter(kind) if node.get('ID')==identity]
        expected=business_xml(original);actual=business_xml(prepared)
        assert canonical_json_bytes(actual)==canonical_json_bytes(expected),('Selected business subtree changed',identity)
        subtrees[identity]={'kind':kind,'source_sha256':canonical_sha256(expected),'prepared_sha256':canonical_sha256(actual)}
    return {'wwus':frames,'owners':owners,'members':members,'curves':curves,'business_subtrees':subtrees}


def test_local_rtpc_and_effect_slot_outputs_keep_actual_owners(workflow_sandbox_runtime,monkeypatch):
    runtime=workflow_sandbox_runtime
    assert runtime.version in {'2022.1','2025.1'}
    assert tuple(runtime.sandbox.metadata.get_info_version[key] for key in ('year','major','minor','build'))==BUILDS[runtime.version]
    output=runtime.state_dir/'query-local-list-outputs.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    assert output.parent.resolve()==output.parent and not output.is_symlink() and not output.exists()
    evidence_root=Path(runtime.env['WWISE_EVIDENCE_DIR'])
    observation={'candidate':runtime.candidate,'version':runtime.version,'read_only':True,'transaction_count':0,
        'groups':[],'business_effect_verified':False,'typed_local_list_projection_proof':False}
    category={'category':'query-local-list-outputs','status':'FAIL','observation_path':str(output),
        'verifier_strength':'fresh_exact_owner_member_metadata_and_independent_curve_value_association'}
    runtime.category_results.append(category)
    status='FAIL';dispatch_count=0;packet_bytes=0;continuations=0
    original_dispatch=waapi_gateway.WwiseDispatcher.dispatch

    def group(label):
        assert len(observation['groups'])<6
        current={'label':label,'invocations':[]};observation['groups'].append(current);return current

    def read(current,argv):
        nonlocal dispatch_count,packet_bytes,continuations
        entries=[];encoding=None;offset=0;first=True;initial=None;all_calls=[];packets={}
        while True:
            assert sum(len(item['invocations']) for item in observation['groups'])<40
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
        rows,calls,packets=read(current,['query-object','--exact-id',identity,'--max-results','1','--include','class-id',*fields])
        row,=rows;assert row['id']==identity
        assert all(isinstance(row[key],str) for key in IDENTITY) and row['path']
        assert type(row['class_id']) is int and row['class_id']>0
        assert any(any(raw.get('id')==identity and raw.get('classId')==row['class_id']
            for raw in packet.get('result',{}).get('return',[])) for packet in packets.values() if packet['api'].endswith('object.get'))
        return row,calls,packets

    def metadata(calls,packets,identity,class_id,fields):
        identities={identity} if isinstance(identity,str) else set(identity)
        names={};infos={}
        for call in calls:
            if not call['api'].endswith(('getPropertyAndReferenceNames','getPropertyInfo')):continue
            args=call['args'] or {}
            scope=('classId',args['classId']) if 'classId' in args else ('object',args.get('object'))
            assert scope==('classId',class_id) or scope[0]=='object' and scope[1] in identities,scope
            result=packets[call['evidence_path']]['result']
            if call['api'].endswith('getPropertyAndReferenceNames'):names[scope]=result['return']
            elif args.get('property') in fields:infos[(scope,args['property'])]=result
        for name,kind in fields.items():
            for identity in identities:
                scopes=[scope for scope in [('classId',class_id),('object',identity)]
                    if name in names.get(scope,[]) and (scope,name) in infos]
                assert scopes,(identity,name,calls)
                for scope in scopes:
                    info=infos[(scope,name)];assert info['name']==name
                    if kind=='reference':assert info.get('restriction',{}).get('type')=='reference'
                    else:assert info['type']==kind and info.get('restriction',{}).get('type')!='reference'
        return [{'scope':dict([scope]),'metadata':value} for (scope,name),value in infos.items()]

    def points(value):
        assert isinstance(value,list) and value
        for point in value:
            assert set(point)=={'x','y','shape'} and point['shape'] in shapes
            assert all(type(point[key]) in (int,float) and math.isfinite(point[key]) for key in ('x','y'))
        return value

    def baseline(current):
        result={'owners':{},'membership':{},'members':{},'curves':{}}
        for identity,expected in facts['owners'].items():
            row,_,_=exact(current,identity)
            assert (row['name'],row['type'],row['class_id'])==(expected['name'],expected['type'],expected['class_id'])
            result['owners'][identity]=row
            rows,_,_=read(current,['query-object','--advanced-waql',f'from object "{identity}" select {expected["native"]}',
                '--max-results','3','--include','class-id','--include','owner'])
            assert {row['id'] for row in rows}==set(expected['members']) and len(rows)==len(expected['members'])
            for member in rows:
                target=facts['members'][member['id']]
                assert member['class_id']==target['class_id'] and member['type']==target['type'] and member['owner']['id']==identity
            result['membership'][identity]=[row['id'] for row in rows]
        for identity,expected in facts['members'].items():
            fields={'PropertyName':'string','ControlInput':'reference','Curve':'reference'} if expected['type']=='RTPC' else {'Bypass':'bool','Render':'bool','Effect':'reference'}
            options=['--include','owner']
            for name in fields:options.extend(['--include-field',name])
            row,calls,packets=exact(current,identity,*options)
            assert row['class_id']==expected['class_id'] and row['type']==expected['type'] and row['owner']['id']==expected['owner']
            metadata(calls,packets,identity,expected['class_id'],fields)
            if expected['type']=='RTPC':
                assert row['properties']['PropertyName']==expected['property']
                assert row['references']['ControlInput']['id']==expected['control_input'] and row['references']['Curve']['id']==expected['curve']
            else:
                assert all(type(row['properties'][key]) is bool for key in ('Bypass','Render'))
                assert row['references']['Effect']['id']==expected['effect']
            result['members'][identity]=row
        for identity,expected in facts['curves'].items():
            row,_,_=exact(current,identity,'--include','owner','--include','curve-points')
            assert row['type']=='Curve' and row['class_id']==917520 and row['owner']['id']==expected['owner']
            points(row['curve_points']);assert [[item['x'],item['y']] for item in row['curve_points']]==expected['xy']
            result['curves'][identity]=row
        if runtime.version=='2025.1':
            row,_,_=exact(current,EFFECT,'--include','plugin-name')
            assert row['type']=='Effect' and isinstance(row['plugin_name'],str) and row['plugin_name']
            result['effect']=row
        return result

    def check_member(member,owner,mode):
        identity=member['object']['id'];expected=facts['members'][identity];before=initial['members'][identity]
        assert identity in initial['membership'][owner]
        assert member['object']['type']==expected['type']
        # classId/owner are planner validation scope, preserved in original native
        # packets below; compact public member identity deliberately omits them.
        if expected['type']=='RTPC':
            if mode=='full':
                assert member['properties']['PropertyName']==before['properties']['PropertyName']
                assert member['references']['ControlInput']['id']==before['references']['ControlInput']['id']
            context=member['related']['references']['Curve']
            assert context['object']['id']==expected['curve']
            assert points(context['curve_points'])==initial['curves'][expected['curve']]['curve_points']
        else:
            if mode=='full':
                assert member['properties']==before['properties']
                assert member['references']['Effect']['id']==EFFECT
            assert member['related']['references']['Effect']['plugin_name']==initial['effect']['plugin_name']

    def native_values(calls,packets,owner,required,include_full):
        proofs=[];fresh={identity:set() for identity in required};scopes=set();native=facts['owners'][owner]['native']
        def rows(value):
            if isinstance(value,dict):
                if value.get('id') in required:yield value
                for item in value.values():yield from rows(item)
            elif isinstance(value,list):
                for item in value:yield from rows(item)
        for call in calls:
            if not call['api'].endswith('object.get'):continue
            packet=packets[call['evidence_path']]
            for row in rows(packet['result']['return']):
                identity=row['id'];expected=facts['members'][identity]
                terminal='Curve.points' if expected['type']=='RTPC' else 'Effect.pluginName'
                fields=({terminal,'@PropertyName','ControlInput'} if expected['type']=='RTPC' else
                    {terminal,'@Bypass','@Render','Effect'}) if include_full else {terminal}
                if row.get('classId')==expected['class_id'] and row.get('owner',{}).get('id')==owner:scopes.add(identity)
                for field in fields.intersection(row):
                    assert row['classId']==expected['class_id']
                    if 'owner' in row:assert row['owner']['id']==owner
                    if field=='Curve.points':assert points(row[field])==initial['curves'][expected['curve']]['curve_points']
                    elif field=='Effect.pluginName':assert row[field]==initial['effect']['plugin_name']
                    elif field=='@PropertyName':assert type(row[field]) is str and row[field]==initial['members'][identity]['properties']['PropertyName']
                    elif field in {'ControlInput','Effect'}:assert row[field]['id']==initial['members'][identity]['references'][field]['id']
                    else:assert type(row[field]) is bool and row[field]==initial['members'][identity]['properties'][field[1:]]
                    fresh[identity].add(field);proofs.append({'packet':call['evidence_path'],'member':identity,'field':field})
        for identity,seen in fresh.items():
            rtpc=facts['members'][identity]['type']=='RTPC'
            expected=({'Curve.points','@PropertyName','ControlInput'} if rtpc else {'Effect.pluginName','@Bypass','@Render','Effect'}) if include_full else {'Curve.points' if rtpc else 'Effect.pluginName'}
            assert seen==expected,(identity,seen,expected)
        assert scopes==set(required),(scopes,required)
        return {'typed_member_packets':proofs,'native_source':native}

    def projection(current,owner,selected,include_full):
        native=facts['owners'][owner]['native'];rtpc=native=='@RTPC';name='local-rtpcs' if rtpc else 'local-effect-slots'
        argv=['query-object','--exact-id',owner,'--max-results','1']
        if include_full:
            for field in (('PropertyName','ControlInput') if rtpc else ('Bypass','Render','Effect')):
                argv.extend(['--include-related-field',name,field])
            argv.extend(['--include-related',name,'reference','Curve' if rtpc else 'Effect','curve-points' if rtpc else 'plugin-name'])
        if selected:
            for path in ([name,'first'],['combine',name,'and',name,'end','take','3' if owner==SOUND else '2']):
                argv.extend(['--include-related',*path,'reference','Curve' if rtpc else 'Effect','curve-points' if rtpc else 'plugin-name'])
        rows,calls,packets=read(current,argv);root,=rows
        assert {key:root[key] for key in IDENTITY}=={key:initial['owners'][owner][key] for key in IDENTITY}
        if include_full:
            full=root['related'][name]['items'];assert [row['object']['id'] for row in full]==initial['membership'][owner]
            for member in full:check_member(member,owner,'full')
        if selected:
            first,combined=([row for row in root['related']['projections'] if row['spec'].get('stages')==[{'selection':'first'}]][0],
                [row for row in root['related']['projections'] if row['spec']['source']=='combine'][0])
            expected=initial['membership'][owner]
            assert [row['object']['id'] for row in first['items']]==expected[:1]
            assert [row['object']['id'] for row in combined['items']]==(expected+expected)[:3 if owner==SOUND else 2]
            assert [row['origin']['arm'] for row in combined['items']]==([0,0,1] if owner==SOUND else [0,1])
            for member in first['items']+combined['items']:check_member(member,owner,'selected')
        required=set(initial['membership'][owner]) if include_full or owner==SOUND else {initial['membership'][owner][0]}
        current['proof']=native_values(calls,packets,owner,required,include_full)
        fields={'PropertyName':'string','ControlInput':'reference','Curve':'reference'} if rtpc else {'Bypass':'bool','Render':'bool','Effect':'reference'}
        current['proof']['fresh_metadata']=metadata(calls,packets,required,1441808 if rtpc else 5505040,
            fields if include_full else {'Curve':'reference'})
        if include_full and runtime.version=='2025.1':
            assert any(any(field.startswith(native+'.{') for field in (call['options'] or {}).get('return',[]))
                for call in calls if call['api'].endswith('object.get'))

    try:
        facts=source_frame(runtime);observation['source_before']=facts
        code,schema=runtime.raw_gateway(['query-schema']);assert code==0
        observation['schema']=schema['related_outputs']['local_object_lists']
        definitions=json.loads((REPO/'skills/waapi-skill/resources/manifest'/runtime.version/'definitions.json').read_text())
        assert definitions['wwise_build']=='.'.join(map(str,BUILDS[runtime.version]))
        defs=definitions['documents']['waapi_definitions.json']['definitions'];shape=defs['pointsDefinition']['items']['properties']['shape']
        shapes=shape.get('enum') or defs[shape['$ref'].rsplit('/',1)[-1]]['enum']
        initial=baseline(group('baseline-before'));observation['baseline']=initial
        projection(group('sound-full'),SOUND,False,True)
        projection(group('sound-selected-combined'),SOUND,True,False)
        projection(group('source-plugin-full-selected-combined'),SOURCE,True,True)
        if runtime.version=='2025.1':projection(group('effect-slots-full-selected-combined'),AUXBUS,True,True)
        final=baseline(group('baseline-after'));assert canonical_json_bytes(final)==canonical_json_bytes(initial)
        observation['source_after']=source_frame(runtime);assert observation['source_after']==facts
        assert len(observation['groups'])==(6 if runtime.version=='2025.1' else 5)
        observation.update(business_effect_verified=True,typed_local_list_projection_proof=True)
        status='PASS'
    except BaseException as exc:
        observation['error']=f'{type(exc).__name__}: {exc}';raise
    finally:
        observation.update(dispatch_count=dispatch_count,packet_bytes=packet_bytes,continuation_count=continuations,
            invocation_count=sum(len(row['invocations']) for row in observation['groups']))
        body=json.dumps(observation,ensure_ascii=False,indent=2).encode();bounded=len(body)<=24*1024*1024
        if not bounded:
            status='FAIL';observation.update(business_effect_verified=False,typed_local_list_projection_proof=False,
                finalization_error='Observation exceeded24MiB; retained without truncation')
            body=json.dumps(observation,ensure_ascii=False,indent=2).encode()
        with output.open('xb') as stream:stream.write(body)
        category.update(status=status,observation_sha256=hashlib.sha256(body).hexdigest(),
            business_effect_verified=observation['business_effect_verified'])
        assert bounded,'Finalized observation exceeded24MiB; no native PASS'
