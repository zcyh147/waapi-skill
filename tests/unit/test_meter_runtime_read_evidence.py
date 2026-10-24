"""Meter reads reach complete public pages, real teardown and the ordinary consumer."""
from copy import deepcopy
import json

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support import runtime_observation_evidence as runtime
from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
from tests.unit.test_runtime_log_branch_evidence import log_inventory
from tests.unit.test_runtime_business_gateway import gateway, _env
from tests.unit.test_profiler_meter_objects_gateway import MeterClient, METERS

BUILDS={'2024.1':'2024.1.13.9056','2025.1':'2025.1.7.9143'}


def public_read(path,version,console,rows,argv):
    path.mkdir(parents=True);context=runtime.program_source_context(flow=METERS)
    client=MeterClient(path,version);client.rows=deepcopy(rows);fallback=client.call;trace=[]
    def call(uri,args=None,options=None):
        result={'return':99328}if uri.endswith('.getCursorTime')else fallback(uri,args,options)
        if uri=='ak.wwise.core.getInfo':
            y,major,minor,build=map(int,BUILDS[version].split('.'));result['version'].update(year=y,major=major,minor=minor,build=build,displayName='v'+BUILDS[version]);result['isCommandLine']=console
        trace.append({'ordinal':len(trace),'uri':uri,'args':deepcopy(args),'options':deepcopy(options),'result':deepcopy(result)})
        return result
    client.call=call;env=_env(path,version=version)
    code,payload=gateway.execute_gateway(['--state-dir',str(path/'state'),*argv],env=env,client_factory=lambda _:client)
    assert code==0,payload
    first={'argv':argv,'exit_code':code,'payload':payload};calls=[{'gateway':first,'native_start':0,'native_end':len(trace)}]
    while payload['agent_result']['complete']is False:
        nextargv=payload['agent_result']['next_command']['full_argv'][3:]
        code,payload=gateway.execute_gateway(nextargv,env=env,client_factory=lambda _:pytest.fail('Retained meter page connected'))
        assert code==0,json.dumps(payload)
        calls.append({'gateway':{'argv':nextargv,'exit_code':code,'payload':payload},'native_start':len(trace),'native_end':len(trace)})
        assert len(calls)<=128
    native=[r for r in trace if r['uri']==METERS][-1]
    return first,{k:native[k]for k in ('uri','args','options','result')},context,trace,calls


def test_meter_first_vertical_cardinality_absence_teardown_and_native_gate(request,tmp_path):
    from tests.support.meter_runtime_read_evidence import original_profile,write_bundle
    version='2025.1';route=f'{version}|wwise-authoring|{BUILDS[version]}|function|{METERS}'
    pointers={'/resultSchema','/resultSchema/properties/meters/@cardinality/empty',
        '/resultSchema/properties/meters/@cardinality/single','/resultSchema/properties/meters/@cardinality/multiple',
        '/resultSchema/properties/meters/items/properties/object/$ref',
        '/resultSchema/@definition/waapi_definitions.json/definitions/objectReturn/properties/notes/@presence/absent'}
    inventory=log_inventory(route,pointers=pointers);assert len(inventory['native_coverage']['obligations'])==6
    original=original_profile(version);row=deepcopy(original['call']['result']['meters'][0])
    captures=[public_read(tmp_path/'original',version,False,original['call']['result']['meters'],original['profile']['argv'])]
    for label,rows in [('empty',[]),('single',[row]),('multiple',[row,row])]:
        captures.append(public_read(tmp_path/label,version,False,rows,
            ['core-call',METERS,'--profiler-position','123','--max-results','1','--meter-object-include','notes']))
    def finalize(phases):
        paths=[]
        for i,(receipt,native,context,trace,calls)in enumerate(captures):
            path=tmp_path/f'capture-{i}.json';runtime.write_program_receipt(path,receipt,native,nodeid=request.node.nodeid,phase_reports=phases,
                source_context=context,native_reads=trace,public_calls=calls);paths.append(path)
        index=write_bundle(tmp_path/'bundle',paths,inventory=inventory,name_prefix='meter-2025.1-wwise-authoring-')
        policies=json.loads((index.parent/'requirements.json').read_bytes());document,base,_=audit.portable_binding_inputs(index,policies)
        result=completion.evaluate_coverage(audit.ROOT,inventory,document,digest=audit.digest,evidence_base=base,requirements_document=policies)
        runtime.write_json(tmp_path/'consumer-result.json',result)
        assert {r['state']for r in result['obligations']}=={'verified'},[(r['pointer'],r['reasons'],r['evidence_results'])for r in result['obligations']if r['state']!='verified']
        from tests.support.meter_runtime_read_evidence import _capture
        corrupted=json.loads(paths[0].read_bytes())
        assert corrupted['native_call']['result']['meters'][0]['configurationMask']==0
        corrupted['gateway']['payload']['agent_result']['meters'][0]['configurationMask']=False
        corrupted['public_calls'][0]['gateway']['payload']['agent_result']['meters'][0]['configurationMask']=False
        with pytest.raises(ValueError,match='Whole selected native meter array'):
            _capture(json.dumps(corrupted),audit.ROOT)
        missing=deepcopy(document);missing['bindings'][route+'|/resultSchema']['evidence'].pop('native')
        blocked=completion.evaluate_coverage(audit.ROOT,inventory,missing,digest=audit.digest,evidence_base=base,requirements_document=policies)
        assert all(r['state']!='verified'for r in blocked['obligations'])
    register_exact_evidence_finalizer(request.node,finalize)


def meter_fixture_rows(version,mode):
    """Finite reflected value domains; these values claim no native population."""
    from wwise_waapi.native_catalog import load_native_catalog
    catalog=load_native_catalog(version,'wwise-authoring');docs=catalog['definitions']['documents']
    guid='{FBF74BF9-8B83-44A8-AC8A-BA85372ECDC4}'
    def value(node,document='waapi_definitions.json',depth=0):
        assert depth<16
        if '$ref'in node:
            doc,pointer=node['$ref'].split('#',1);doc=doc or document
            return value(completion.pointer_value(docs[doc],pointer),doc,depth+1)
        for union in ('oneOf','anyOf'):
            if union in node:return value(node[union][mode%len(node[union])],document,depth+1)
        if 'enum'in node:return deepcopy(node['enum'][mode%len(node['enum'])])
        kind=node.get('type')
        if isinstance(kind,list):kind=kind[mode%len(kind)]
        if kind=='object':
            fields=node.get('properties',{})
            return {k:value(v,document,depth+1)for k,v in fields.items()if mode not in {2,3,10}or (depth==0 and mode!=10)or k in node.get('required',[])}
        if kind=='array':
            n=0 if mode==3 else 1 if mode in {1,2}else 2
            return [value(node['items'],document,depth+1)for _ in range(max(n,node.get('minItems',0)))]
        if kind=='string':return guid if 'pattern'in node else ''if mode==1 else 'Conditional fixture'
        if kind=='boolean':return bool(mode%2)
        if kind in {'integer','number'}:
            return node.get('minimum',0)if mode%2==0 else node.get('maximum',1)
        if kind=='null':return None
        raise AssertionError(('Unplanned reflected fixture shape',node))
    schema=docs['waapi_definitions.json']['definitions']['objectReturn'];obj=value(schema)
    # Canonical GUID validity is independent of the empty-string fixture mode.
    if 'id'in obj:obj['id']=guid
    item=catalog['schemas'][METERS]['resultSchema']['properties']['meters']['items']
    row=value(item)
    row['object']=obj
    return [row]if mode in {1,2,3}else[row,deepcopy(row)]


@pytest.mark.parametrize('version,console',[('2025.1',False),('2024.1',False),('2025.1',True),('2024.1',True)])
def test_known_meter_fields_public_whole_arrays_teardown_and_exact_gates(request,tmp_path,version,console):
    from tests.support import meter_runtime_read_evidence as meter
    from wwise_waapi.profiler_meter_objects import meter_named_outputs
    host='wwise-console'if console else'wwise-authoring';route=f'{version}|{host}|{BUILDS[version]}|function|{METERS}'
    wanted=set(meter.review()['program_candidate_ids'])|set(meter.review()['native_root_ids'])
    inventory=log_inventory(route);inventory['native_coverage']['obligations']=[b for b in inventory['native_coverage']['obligations']if b['id']in wanted]
    assert len(inventory['native_coverage']['obligations'])==(750 if version=='2025.1'else 586)
    pending=[b['id']for b in inventory['native_coverage']['obligations']if '/patternProperties/'in b['pointer']and (b['pointer'].endswith('/anyOf/3/items')or b['pointer'].endswith('/anyOf/5/items')or '/anyOf/5/items/@boolean/'in b['pointer'])]
    assert len(pending)==4
    inventory['native_coverage']['obligations']=[b for b in inventory['native_coverage']['obligations']if b['id']not in pending]
    captures=[]
    if not console:
        original=meter.original_profile(version)
        captures.append(public_read(tmp_path/'original',version,console,original['call']['result']['meters'],original['profile']['argv']))
    names=list(meter_named_outputs(version));chunks=[names[i:i+32]for i in range(0,len(names),32)]
    # Fixed modes cover enum alternatives, present/absent, booleans, scalar
    # bounds, empty/single/multiple collections and whole-row fragmentation.
    for mode in range(14):
        for chunkno,names in enumerate(chunks):
            argv=['core-call',METERS,'--profiler-position',str(mode),'--max-results','1']
            for name in names:argv+=['--meter-object-include',name]
            if mode in {4,5}:
                scope='{FBF74BF9-8B83-44A8-AC8A-BA85372ECDC4}'if mode==5 else'Mac'
                argv+=['--meter-platform',scope,'--meter-language',scope]
            rows=meter_fixture_rows(version,mode)
            if mode==8:
                for row in rows:row['object']['notes']='Retained Unicode 语音 '+('x'*6000)
            captures.append(public_read(tmp_path/f'{mode}-{chunkno}',version,console,rows,argv))
    for label,position,rows,flags in [('default',0,meter_fixture_rows(version,0),[]),('empty',1,[],[]),
            ('empty-selection',1,meter_fixture_rows(version,0),['--meter-object-empty-selection']),
            ('capture','capture-latest',meter_fixture_rows(version,0),['--meter-object-include','notes']),
            ('user','user-cursor',meter_fixture_rows(version,0),['--meter-object-include','notes'])]:
        captures.append(public_read(tmp_path/label,version,console,rows,['core-call',METERS,'--profiler-position',str(position),'--max-results','64',*flags]))
    def finalize(phases):
        paths=[]
        for i,(receipt,native,context,trace,calls)in enumerate(captures):
            path=tmp_path/f'capture-{i}.json';runtime.write_program_receipt(path,receipt,native,nodeid=request.node.nodeid,phase_reports=phases,
                source_context=context,native_reads=trace,public_calls=calls);paths.append(path)
        index=meter.write_bundle(tmp_path/'bundle',paths,inventory=inventory,name_prefix=f'meter-{version}-{host}-')
        policies=json.loads((index.parent/'requirements.json').read_bytes());document,base,_=audit.portable_binding_inputs(index,policies)
        result=completion.evaluate_coverage(audit.ROOT,inventory,document,digest=audit.digest,evidence_base=base,requirements_document=policies)
        runtime.write_json(tmp_path/'consumer-result.json',{'result':result,'pending_primitive_array_ids':pending,'canonical_meter_denominator':2744})
        if console:
            assert all(r['state']!='verified'and r['evidence_results']['program']['outcome']=='passed'for r in result['obligations']),result
        else:
            assert {r['state']for r in result['obligations']}=={'verified'},[(r['pointer'],r['reasons'],r['evidence_results'])for r in result['obligations']if r['state']!='verified']
        if not console and version=='2025.1':
            single=next(k for k in document['bindings']if k.endswith('/returnExpression/@cardinality/single'))
            descriptor=document['bindings'][single]['evidence']['program'];record=completion.read_sealed_artifact(descriptor,base)
            sealed=record['runtime_read_program']
            assert sealed['gateway']['argv'][-2:]==['--meter-object-include','notes']
            assert sealed['native_call']['options']=={'return':['id','name','type','path','notes']}
            assert record['branch_assertions'][single]['checks'][0]=={'pointer':'/native_call/options/return','equals':['id','name','type','path','notes']}
            for damage in ('requested-count','native-field','augmentation','flag','teardown','host','page','source'):
                bad=deepcopy(sealed)
                if damage=='requested-count':bad['gateway']['argv']+=['--meter-object-include','volume-db']
                elif damage in {'native-field','augmentation'}:
                    fields=['id','name','type','path','shortId']if damage=='native-field'else['notes']
                    bad['native_call']['options']['return']=fields
                    [r for r in bad['native_reads']if r['uri']==METERS][-1]['options']['return']=fields
                elif damage=='flag':bad['gateway']['argv'][-2]='--meter-object-include-field'
                elif damage=='teardown':bad['phase_reports']['teardown']='failed'
                elif damage=='host':next(r for r in bad['native_reads']if r['uri']=='ak.wwise.core.getInfo')['result']['isCommandLine']=True
                elif damage=='page':bad['public_calls'][-1]['gateway']['payload']['agent_result']['snapshot_sha256']='0'*64
                else:bad['source_context']['packaged']['skills/waapi-skill/scripts/run.py']='0'*64
                with pytest.raises((ValueError,KeyError),match='.'):
                    meter._capture(json.dumps(bad),audit.ROOT)
            changed=deepcopy(document);changed['bindings'][single]['normalized_input_choice']['literal_native_single']=True
            rejected=completion.evaluate_coverage(audit.ROOT,inventory,changed,digest=audit.digest,evidence_base=base,requirements_document=policies)
            assert next(r for r in rejected['obligations']if r['id']==single)['state']!='verified'
            assert all(r['state']=='verified'for r in rejected['obligations']if r['id']!=single)
        if not console:
            missing=deepcopy(document);missing['bindings'][route+'|/resultSchema']['evidence'].pop('native')
            blocked=completion.evaluate_coverage(audit.ROOT,inventory,missing,digest=audit.digest,evidence_base=base,requirements_document=policies)
            assert all(r['state']!='verified'for r in blocked['obligations'])
    register_exact_evidence_finalizer(request.node,finalize)
