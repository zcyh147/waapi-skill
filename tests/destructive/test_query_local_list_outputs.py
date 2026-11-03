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
from wwise_waapi.object_query_related_runtime import canonical_guid

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


# Source-only anchors for the bounded 2025 function-context transport probe.
# These files are read in full; the live sandbox and committed source stay unchanged.
CONTEXT_PINS = {
    'Containers/Music/Music.wwu': '5b92968638cf618eeedcdc6213df683e58e32ec332e34fdda9f584912566136b',
    'States/Music.wwu': '65698912e221154656d706020e359a2dbf8c2148dc022e1d139510bdd5e3857f',
    'Containers/NYC Ambience.wwu': 'b0592d83c6e6e4438c152c0f806f8d95a87bc4f6f97bd7785851fe263eebfb16',
    'Containers/Footsteps.wwu': '0b5c0a9c8b195d4c2c95d5ace81836711b3978533f7c2ec17cb17a7782700270',
}


def query_function_context_source_frame(runtime):
    """Pin query inputs/source associations without inferring computed selections."""
    assert runtime.version == '2025.1'
    trees = {}; frames = []
    for relative, pin in CONTEXT_PINS.items():
        source = runtime.sandbox.source_root / relative
        owned = runtime.sandbox.sandbox_path / relative
        assert source.resolve() != owned.resolve() and not source.is_symlink() and not owned.is_symlink()
        body = read_file(source, 2 * 1024 * 1024)
        assert sha(body) == pin and read_file(owned, 2 * 1024 * 1024) == body
        trees[relative] = ET.fromstring(body)
        frames.append({'relative_path': relative, 'sha256': pin,
            'source_mtime_ns': source.stat().st_mtime_ns, 'owned_mtime_ns': owned.stat().st_mtime_ns})

    def find(relative, tag, identity):
        node, = [row for row in trees[relative].iter(tag) if row.get('ID') == identity]
        return node

    def identity(node):
        return {'id': node.get('ID'), 'name': node.get('Name'), 'type': node.tag}

    music = 'Containers/Music/Music.wwu'
    state_owner = find(music, 'MusicTrack', '{9861812D-295E-47DC-BB84-803555479814}')
    state_id = '{20A3B196-D22F-42F7-8592-A37A3E5B467A}'
    state = find('States/Music.wwu', 'State', state_id)
    state_entry, = [row for row in state_owner.findall('./StateInfo/CustomStateList/CustomState')
        if row.find('StateRef').get('ID') == state_id]
    custom, = state_entry.findall('CustomState')
    assert state.get('Name') == state_entry.find('StateRef').get('Name') == 'c_Fight'
    assert custom.get('ID') == '{4C10E9EB-9AC1-4134-93D8-5EF9364E4E06}'
    panner_owner = find('Containers/NYC Ambience.wwu', 'Sound', '{3FCC7FC1-63CD-46F4-BB87-7741E08706E5}')
    panner, = panner_owner.findall('./PositioningInfo/Panner')
    assert panner.get('ID') == '{15866C0E-BAE4-47B2-BDE5-1BD5A3DD9D77}'
    sound = find('Containers/Footsteps.wwu', 'Sound', '{0030BF58-90C3-428B-B940-44CC1C5A51B5}')
    attenuation_owner = find('Containers/Footsteps.wwu', 'RandomSequenceContainer', '{D5594A4B-DDB0-47F3-AC2F-08F104C72438}')
    attenuation, = attenuation_owner.findall('./ReferenceList/Reference[@Name="Attenuation"]/Custom/Attenuation')
    assert attenuation.get('ID') == '{CB2B7556-B4AB-46B1-A0C9-20D4880B6DED}'
    contexts = []
    for label, owner, selected, expression in (
        ('state', state_owner, custom, f'state("{state_id}")'),
        ('panner', panner_owner, panner, 'panner'),
        ('max-duration-source-object', sound, None, 'maxDurationSourceObject'),
        ('max-radius-attenuation-object', attenuation_owner, None, 'maxRadiusAttenuationObject'),
    ):
        context = {'label': label, 'owner': identity(owner), 'expression': expression,
            'selection_kind': 'computed' if selected is None else 'source-association'}
        if selected is not None: context['selected'] = identity(selected)
        contexts.append(context)
    # These are independent scalar query inputs, never computed-selector oracles.
    return {'files': frames, 'contexts': contexts,
        'scalar_owners': {'field-status': identity(sound), 'curve-selection': identity(attenuation)}}


def collect_query_function_contexts(runtime, monkeypatch):
    """One read-only lifecycle; stop only a rejected context, retaining native packets."""
    assert runtime.version == '2025.1'
    assert tuple(runtime.sandbox.metadata.get_info_version[key] for key in ('year', 'major', 'minor', 'build')) == BUILDS['2025.1']
    output = runtime.state_dir / 'query-function-contexts.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    assert not output.exists() and not output.is_symlink()
    evidence_root = Path(runtime.env['WWISE_EVIDENCE_DIR'])
    observation = {'candidate': runtime.candidate, 'version': runtime.version, 'read_only': True,
        'transaction_count': 0, 'groups': [], 'context_transport_verified': False, 'scalar_transport_verified': False, 'business_effect_verified': False,
        'boundary': 'documented advanced SELECT contexts and closed scalar terminals; no raw RETURN, invented GUID/ownership/status values, or setup writes'}
    category = {'category': 'query-function-contexts', 'status': 'FAIL', 'observation_path': str(output),
        'verifier_strength': 'source_pinned_context_transport_and_actual_native_scalar_to_public_value_association'}
    runtime.category_results.append(category)
    dispatch_count = 0; packet_bytes = 0; invocation_count = 0
    original = waapi_gateway.WwiseDispatcher.dispatch

    def read(group, argv, *, allow_empty=False):
        nonlocal dispatch_count, packet_bytes, invocation_count
        assert invocation_count < 14
        invocation_count += 1
        record = {'argv': list(argv), 'dispatch_calls': [], 'native_packets': []}
        group['invocations'].append(record)
        before = set(evidence_root.glob('*.json'))
        def capture(dispatcher, api, **kwargs):
            nonlocal dispatch_count
            assert dispatch_count < 96
            dispatch_count += 1
            assert api in READ_APIS
            call = {'api': api, **copy.deepcopy({key: kwargs.get(key) for key in ('version', 'args', 'options')})}
            record['dispatch_calls'].append(call)
            result = original(dispatcher, api, **kwargs)
            call.update(ok=result['ok'], evidence_path=result.get('evidence_path'), result_sha256=canonical_sha256(result.get('result')))
            return result
        with monkeypatch.context() as patch:
            patch.setattr(waapi_gateway.WwiseDispatcher, 'dispatch', capture)
            code, payload = runtime.raw_gateway(argv)
        record.update(exit_code=code, payload=payload)
        packets = {}
        for path in sorted(set(evidence_root.glob('*.json')) - before):
            body = read_file(path, 2 * 1024 * 1024); packet_bytes += len(body)
            assert packet_bytes <= 16 * 1024 * 1024
            packet = json.loads(body); packets[str(path)] = packet
            record['native_packets'].append({'path': str(path), 'bytes': len(body), 'sha256': sha(body)})
        assert {call['evidence_path'] for call in record['dispatch_calls']} == set(packets)
        for call in record['dispatch_calls']:
            packet = packets[call['evidence_path']]
            assert packet['api'] == call['api'] and call['version'] == runtime.version
            assert packet['ok'] is call['ok'] and canonical_sha256(packet.get('result')) == call['result_sha256']
        assert code == 0 and payload.get('ok') is True, payload
        assert list(payload)[-1] == 'agent_result'
        rows = payload['agent_result']
        assert isinstance(rows, list) and (len(rows) <= 1 if allow_empty else len(rows) == 1), payload
        native = [packet for packet in packets.values() if packet['api'] == 'ak.wwise.core.object.get']
        if not rows:
            assert native and any(packet.get('result', {}).get('return') == [] for packet in native)
            return None
        row, = rows
        assert all(isinstance(row.get(key), str) for key in IDENTITY) and canonical_guid(row['id']) and row['type'] and row['path'], row
        assert native and any(any(all(raw.get(key) == row[key] for key in IDENTITY)
            for raw in packet.get('result', {}).get('return', []) if isinstance(raw, dict)) for packet in native)
        return row

    def exact(group, expected):
        row = read(group, ['query-object', '--exact-id', expected['id'], '--max-results', '1', '--detail'])
        assert all(row[key] == expected[key] for key in ('id', 'name', 'type')), (row, expected)
        return row

    def scalar_group(label, expected, choices):
        group = {'label': label, 'status': 'FAIL', 'invocations': [], 'source_owner': expected}
        observation['groups'].append(group)
        try:
            argv = ['query-object', '--exact-id', expected['id'], '--max-results', '1', '--detail']
            for tokens, _native, _path in choices:
                argv.extend(['--include-related', *tokens])
            row = read(group, argv)
            assert all(row[key] == expected[key] for key in ('id', 'name', 'type'))
            proofs = []
            for descriptor in group['invocations'][0]['native_packets']:
                packet = json.loads(read_file(Path(descriptor['path']), 2 * 1024 * 1024))
                if packet['api'] != 'ak.wwise.core.object.get': continue
                for native_row in packet.get('result', {}).get('return', []):
                    if native_row.get('id') != expected['id']: continue
                    for _tokens, native, path in choices:
                        if native not in native_row: continue
                        value = native_row[native]
                        public = row
                        for key in path: public = public[key]
                        assert value is None or type(value) is (str if path[-1] == 'source' else bool)
                        assert type(value) is type(public) and public == value
                        proofs.append({'packet': descriptor['path'], 'native_field': native,
                            'public_path': list(path), 'value': value})
            group['actual_scalar_proofs'] = proofs
            assert {proof['native_field'] for proof in proofs} == {choice[1] for choice in choices}, 'Required native scalar evidence missing; public omissions retained'
            group['status'] = 'PASS'
        except (AssertionError, KeyError) as exc:
            group['failure'] = str(exc)

    try:
        facts = query_function_context_source_frame(runtime)
        observation['source_before'] = facts
        for fact in facts['contexts']:
            group = {'label': fact['label'], 'status': 'FAIL', 'invocations': [], 'source': fact}
            observation['groups'].append(group)
            try:
                owner = exact(group, fact['owner'])
                expression = f'from object "{owner["id"]}" select {fact["expression"]}'
                computed = fact['selection_kind'] == 'computed'
                selected = read(group, ['query-object', '--advanced-waql', expression, '--max-results', '1', '--detail'],
                    allow_empty=computed)
                # Wwise owns computed extrema. XML pins the input only; a direct
                # source child/reference is not an oracle for a computed result.
                group.update(selected=selected, selection_state='no-match' if selected is None else 'selected',
                    result_count=0 if selected is None else 1, exact_readback_required=selected is not None)
                if selected is not None:
                    if not computed:
                        assert all(selected[key] == fact['selected'][key] for key in ('id', 'name', 'type')), selected
                    assert exact(group, selected) == selected
                    group['exact_readback_verified'] = True
                else:
                    group['exact_readback_verified'] = False  # Completed no-match; no GUID exists to read back.
                group['status'] = 'PASS'
            except AssertionError as exc:
                group['failure'] = str(exc)
                # No GUID coercion, raw projection, retry, or dependent read after
                # an adapter/native rejection. Other fixed contexts remain independent.
        # Source anchors independently authorize these read-only exact-ID roots;
        # neither scalar group depends on successful transport of another context.
        scalar_group('field-status', facts['scalar_owners']['field-status'], [
            (['field-status', 'Pitch', 'linked'], 'isLinked("Pitch")', ('related', 'field_status', 'Pitch', 'linked')),
            (['field-status', 'RTPC', 'overridable'], 'isOverridable("RTPC")', ('related', 'field_status', 'RTPC', 'overridable')),
            (['field-status', 'OutputBus', 'override-source'], 'isSourceOfOverride("OutputBus")', ('related', 'field_status', 'OutputBus', 'override-source')),
            (['field-status', 'RTPC', 'present'], 'hasProperty("RTPC")', ('related', 'field_status', 'RTPC', 'present')),
        ])
        scalar_group('curve-selection', facts['scalar_owners']['curve-selection'], [
            (['curve-selection', 'volume-dry'], 'curveToUse("VolumeDryUsage")', ('related', 'curve_selections', 'volume-dry', 'source')),
            (['curve-selection', 'volume-wet-game'], 'curveToUse("VolumeWetGameUsage")', ('related', 'curve_selections', 'volume-wet-game', 'source')),
        ])
        observation['source_after'] = query_function_context_source_frame(runtime)
        assert observation['source_before'] == observation['source_after']
        observation['context_transport_verified'] = all(group['status'] == 'PASS' for group in observation['groups'][:4])
        observation['scalar_transport_verified'] = all(group['status'] == 'PASS' for group in observation['groups'][4:])
        assert all(group['status'] == 'PASS' for group in observation['groups']), 'Query function collection incomplete; see retained per-group packets'
        observation['business_effect_verified'] = True
        category['status'] = 'PASS'
    except BaseException as exc:
        observation['failure'] = {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        observation.update(dispatch_count=dispatch_count, packet_bytes=packet_bytes, invocation_count=invocation_count)
        body = json.dumps(observation, ensure_ascii=False, indent=2).encode()
        bounded = len(body) <= 20 * 1024 * 1024
        if not bounded:
            category['status'] = 'FAIL'
            observation.update(context_transport_verified=False, scalar_transport_verified=False, business_effect_verified=False,
                finalization_error='Observation exceeds20MiB; retained without truncation')
            body = json.dumps(observation, ensure_ascii=False, indent=2).encode()
        with output.open('xb') as stream: stream.write(body)
        category.update(observation_sha256=sha(body), business_effect_verified=observation['business_effect_verified'])
        assert bounded
    return category


@pytest.mark.skipif(os.environ.get('WWISE_VERSION') != '2025.1', reason='Documented function-context probe is2025.1 only')
def test_documented_query_function_context_transport(workflow_sandbox_runtime, monkeypatch):
    collect_query_function_contexts(workflow_sandbox_runtime, monkeypatch)
