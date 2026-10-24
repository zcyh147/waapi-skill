"""Transport authority and independent route evidence through the public Gateway."""
from copy import deepcopy
import json

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support import runtime_observation_evidence as runtime
from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
from tests.unit.test_runtime_business_gateway import _env, gateway, _RuntimeControlDraftClient
from tests.unit.test_runtime_log_branch_evidence import log_inventory

PREFIX='ak.wwise.core.transport.'
BUILDS={'2021.1':'2021.1.14.8108','2022.1':'2022.1.19.8584','2023.1':'2023.1.19.8928','2024.1':'2024.1.13.9056','2025.1':'2025.1.7.9143'}


class TransportClient(_RuntimeControlDraftClient):
    """External Wwise boundary only; handles/transactions are the real product."""
    def __init__(self,path,version,host,target):
        super().__init__(path,version=version)
        self.console=host=='wwise-console';self.target_id=target;self.rows=[];self.states={};self.trace=[]
    def call(self,uri,args=None,options=None):
        if uri==PREFIX+'create':
            self.rows=[{'transport':0,'object':args['object'],'gameObject':args.get('gameObject',18446744073709551614)}]
            self.states[0]='stopped';result={'transport':0}
        elif uri==PREFIX+'getList':result={'list':deepcopy(self.rows)}
        elif uri==PREFIX+'getState':result={'state':self.states[args['transport']]}
        elif uri==PREFIX+'executeAction':
            for row in self.rows:
                if 'transport'in args and row['transport']!=args['transport']:continue
                old=self.states[row['transport']]
                self.states[row['transport']]={'play':'playing','stop':'stopped','playDirectly':'playing',
                    'pause':{'playing':'paused','paused':'playing','stopped':'stopped'}[old],
                    'playStop':{'playing':'stopped','paused':'playing','stopped':'playing'}[old]}[args['action']]
            result={}
        elif uri==PREFIX+'destroy':self.rows=[r for r in self.rows if r['transport']!=args['transport']];result={}
        elif uri in {PREFIX+'prepare',PREFIX+'useOriginals'}:result={}
        elif uri=='ak.wwise.core.object.get'and isinstance(args,dict)and ('path'in args.get('from',{})or 'ofType'in args.get('from',{})or args.get('waql','').startswith('from type Event')):
            result={'return':[{'id':self.target_id,'name':'Play_Weather','type':'Event','path':r'\Events\Default Work Unit\Play_Weather'}]}
        else:
            result=super().call(uri,args,options)
            if uri=='ak.wwise.core.getInfo':
                year,major,minor,build=map(int,BUILDS[self.version].split('.'))
                result.update(isCommandLine=self.console)
                result['version'].update(year=year,major=major,minor=minor,build=build)
        self.trace.append({'ordinal':len(self.trace),'uri':uri,'args':deepcopy(args),'options':deepcopy(options),'result':deepcopy(result)})
        return result


def public_lifecycle(path,version,host,originals,*,selector='id',only_bound=False):
    path.mkdir(parents=True);target=originals[PREFIX+'create']['call']['args']['object']
    client=TransportClient(path,version,host,target);env=_env(path,version=version);calls=[];stages=[]
    sources={u:runtime.program_source_context(flow=u)for u in originals}
    def invoke(argv):
        start=len(client.trace)
        code,payload=gateway.execute_gateway(['--state-dir',str(path/'state'),*argv],env=env,client_factory=lambda _:client)
        receipt={'argv':list(argv),'exit_code':code,'payload':payload}
        calls.append({'gateway':receipt,'native_start':start,'native_end':len(client.trace)})
        assert code==0,payload
        return payload
    def transaction(uri,fields=(),bind=False):
        first=len(calls);started=invoke(['draft-start',uri]);draft=started['draft']['draft_id'];authority=started['task_authority'];current=started
        if bind:
            current=invoke(['draft-bind-object',draft,'--task-authority',authority,'--expected-revision',str(current['draft']['revision']),
                '--role','target',*(['--object-id',target]if selector=='id'else ['--exact-type-name','Event','Play_Weather']if selector=='qualified-name'else [item for segment in ('Events','Default Work Unit','Play_Weather')for item in ('--object-path-segment',segment)])])
            fields=('--target-handle',current['bound_object']['handle'],*fields)
        current=invoke(['draft-declare-runtime-control-plan',draft,'--task-authority',authority,'--expected-revision',str(current['draft']['revision']),*fields])
        current=invoke(['draft-check',draft,'--task-authority',authority,'--expected-revision',str(current['draft']['revision'])])
        preview=invoke(['preview-from-draft',draft,'--task-authority',authority,'--expected-revision',str(current['draft']['revision'])])
        shown=invoke(preview['next_command']['gateway_argv']);invoke(shown['next_command']['gateway_argv'])
        executed=invoke(['execute',preview['transaction_id']]);verified=invoke(executed['next_command']['gateway_argv'])
        stages.append({'uri':uri,'start':first,'end':len(calls),'receipt_index':len(calls)-1})
        return verified
    if not only_bound and PREFIX+'useOriginals'in originals:transaction(PREFIX+'useOriginals',('--audition-media','originals'))
    if PREFIX+'prepare'in originals:transaction(PREFIX+'prepare',bind=True)
    created=transaction(PREFIX+'create',bind=True)
    handle=created['agent_result']['business_result']['transport_handle'];assert handle.startswith('trh1-')
    if not only_bound:
        first=len(calls);schema=invoke(['request-schema',PREFIX+'getList'])
        listed=invoke(['typed-zero-call',PREFIX+'getList','--schema-digest',schema['schema_digest']])
        stages.append({'uri':PREFIX+'getList','start':first,'end':len(calls),'receipt_index':len(calls)-1})
        assert listed['agent_result']['list']==client.rows
        first=len(calls);state=invoke(['core-call',PREFIX+'getState','--transport-handle',handle])
        stages.append({'uri':PREFIX+'getState','start':first,'end':len(calls),'receipt_index':len(calls)-1})
        assert state['agent_result']=={'transport_handle':handle,'state':'stopped'}
        transaction(PREFIX+'executeAction',('--audition-action','play','--transport-scope','one-transport','--transport-handle',handle))
        transaction(PREFIX+'executeAction',('--audition-action','stop','--transport-scope','one-transport','--transport-handle',handle))
    destroyed=transaction(PREFIX+'destroy',('--transport-handle',handle));assert destroyed['verified']is True
    assert client.rows==[]
    # Retired authority must not dispatch another state/action, even if ID0 was valid.
    before=len(client.trace)
    code,bad=gateway.execute_gateway(['--state-dir',str(path/'state'),'core-call',PREFIX+'getState','--transport-handle',handle],env=env,client_factory=lambda _:client)
    assert code==2 and not any(r['uri']==PREFIX+'getState'for r in client.trace[before:])
    # Rejected request is independent of the successful lifecycle receipt.
    trace=client.trace[:before]
    return calls,trace,stages,sources


def test_transport_2024_paired_host_lifecycle_teardown_portable_consumer(request,tmp_path):
    from tests.support.runtime_transport_evidence import original_transport,write_transport_bundle,URIS
    routes=[f'2024.1|{h}|{BUILDS["2024.1"]}|function|{u}'for h in ('wwise-console','wwise-authoring')for u in sorted(URIS)]
    inventory=log_inventory(routes,pointers={'/argsSchema','/optionsSchema','/resultSchema'});sessions=[]
    for host in ('wwise-console','wwise-authoring'):
        originals={u:original_transport(f'2024.1|{host}|{BUILDS["2024.1"]}|function|{u}')for u in URIS}
        sessions.append(public_lifecycle(tmp_path/host,'2024.1',host,originals))
    def finalize(phases):
        paths=[]
        for number,(calls,trace,stages,sources)in enumerate(sessions):
            for j,stage in enumerate(stages):
                if stage['uri']==PREFIX+'executeAction'and '--audition-action'in calls[stage['start']+1]['gateway']['argv'] and calls[stage['start']+1]['gateway']['argv'][calls[stage['start']+1]['gateway']['argv'].index('--audition-action')+1]=='stop':continue
                part=calls[stage['start']:stage['end']];writes=[r for r in trace[part[0]['native_start']:part[-1]['native_end']]if r['uri']==stage['uri']]
                # Readbacks may repeat the same read URI; the exact public request
                # comes from the one selected direct read or mutation execution.
                if stage['uri']==PREFIX+'getState':writes=[r for r in trace[part[-1]['native_start']:part[-1]['native_end']]if r['uri']==stage['uri']]
                if stage['uri']==PREFIX+'getList':writes=[r for r in trace[part[-1]['native_start']:part[-1]['native_end']]if r['uri']==stage['uri']]
                assert len(writes)==1
                row=writes[0];native={k:row[k]for k in ('uri','args','options','result')};path=tmp_path/f'capture-{number}-{j}.json'
                runtime.write_program_receipt(path,calls[stage['receipt_index']]['gateway'],native,nodeid=request.node.nodeid,phase_reports=phases,
                    source_context=sources[stage['uri']],native_reads=trace,public_calls=calls)
                cap=json.loads(path.read_bytes());cap['transport_stage']=stage;cap['transport_stages']=stages;runtime.write_json(path,cap);paths.append(path)
        index=write_transport_bundle(tmp_path/'bundle',paths,inventory=inventory,name_prefix='transport-2024.1-')
        policies=json.loads((index.parent/'requirements.json').read_bytes());bindings,base,_=audit.portable_binding_inputs(index,policies)
        def evaluate(b):return completion.evaluate_coverage(audit.ROOT,inventory,b,digest=audit.digest,evidence_base=base,requirements_document=policies)
        result=evaluate(bindings);runtime.write_json(tmp_path/'consumer-result.json',result)
        assert {r['state']for r in result['obligations']}=={'verified'},[(r['id'],r['reasons'])for r in result['obligations']if r['state']!='verified']
        for route in routes:
            damaged=deepcopy(bindings);damaged['bindings'][route+'|/resultSchema']['evidence'].pop('native')
            negative=evaluate(damaged)
            assert all(r['state']!='verified'for r in negative['obligations']if r['route']==route)
            assert all(r['state']=='verified'for r in negative['obligations']if r['route']!=route)
        with pytest.raises(ValueError,match='duplicates an exact branch'):
            runtime.write_runtime_composition(tmp_path/'duplicates',[(index,policies),(index,policies)])
    register_exact_evidence_finalizer(request.node,finalize)


def test_retained_2025_authoring_prepare_keeps_its_own_blocked_root_and_target():
    from tests.support.runtime_transport_evidence import original_transport
    route=f'2025.1|wwise-authoring|{BUILDS["2025.1"]}|function|'
    prepare=original_transport(route+PREFIX+'prepare')
    create=original_transport(route+PREFIX+'create')
    assert prepare['provider']['archive_files']==307
    assert prepare['call']=={'uri':PREFIX+'prepare','args':{'object':'{9EEFCC8E-7FC2-4CDC-8BE9-C682F2CA77CC}'},'options':{},'result':{}}
    assert prepare['facts']['original_finalization']=='BLOCKED'
    assert prepare['facts']['physical_cleanup_complete']is True
    assert prepare['facts']['global_pass_transferred']is False
    assert prepare['facts']['business_boundary']=='acknowledgment_schema_only'
    assert create['facts']['original_finalization']=='PASS'
    assert create['call']['args']['object']=='{FBF74BF9-8B83-44A8-AC8A-BA85372ECDC4}'
    assert prepare['provider']['archive_source']!=create['provider']['archive_source']


def test_transport_name_path_normalization_requires_public_identity_and_readback(request,tmp_path):
    from tests.support.runtime_transport_evidence import original_transport,write_transport_bundle
    routes=[f'2024.1|wwise-console|{BUILDS["2024.1"]}|function|'+PREFIX+s for s in ('create','prepare')]
    inventory=log_inventory(routes)
    from tests.support.runtime_transport_evidence import review
    selected=set(review()['normalized_identities'])|{r+'|/resultSchema'for r in routes}
    inventory['native_coverage']['obligations']=[b for b in inventory['native_coverage']['obligations']if b['id']in selected]
    assert len(inventory['native_coverage']['obligations'])==18
    originals={u:original_transport(f'2024.1|wwise-console|{BUILDS["2024.1"]}|function|{u}')for u in (PREFIX+'create',PREFIX+'prepare')}
    sessions=[public_lifecycle(tmp_path/selector,'2024.1','wwise-console',originals,selector=selector,only_bound=True)
              for selector in ('id','qualified-name','path')]
    def finalize(phases):
        paths=[]
        for number,(calls,trace,stages,sources)in enumerate(sessions):
            for j,stage in enumerate(stages):
                if stage['uri']not in originals:continue
                part=calls[stage['start']:stage['end']];native,=[r for r in trace[part[0]['native_start']:part[-1]['native_end']]if r['uri']==stage['uri']]
                path=tmp_path/f'capture-{number}-{j}.json'
                runtime.write_program_receipt(path,calls[stage['receipt_index']]['gateway'],{k:native[k]for k in ('uri','args','options','result')},
                    nodeid=request.node.nodeid,phase_reports=phases,source_context=sources[stage['uri']],native_reads=trace,public_calls=calls)
                cap=json.loads(path.read_bytes());cap.update(transport_stage=stage,transport_stages=stages);runtime.write_json(path,cap);paths.append(path)
        index=write_transport_bundle(tmp_path/'bundle',paths,inventory=inventory,name_prefix='transport-2024.1-')
        policies=json.loads((index.parent/'requirements.json').read_bytes());bindings,base,_=audit.portable_binding_inputs(index,policies)
        result=completion.evaluate_coverage(audit.ROOT,inventory,bindings,digest=audit.digest,evidence_base=base,requirements_document=policies)
        runtime.write_json(tmp_path/'consumer-result.json',result)
        assert {r['state']for r in result['obligations']}=={'verified'},[(r['id'],r['reasons'])for r in result['obligations']if r['state']!='verified']
    register_exact_evidence_finalizer(request.node,finalize)


def public_create_omission(path,version,host):
    path.mkdir(parents=True)
    class MissingIdClient(TransportClient):
        def call(self,uri,args=None,options=None):
            result=super().call(uri,args,options)
            if uri==PREFIX+'create':
                result={};self.trace[-1]['result']={}
            return result
    client=MissingIdClient(path,version,host,'{11111111-1111-1111-1111-111111111111}')
    context=runtime.program_source_context(flow=PREFIX+'create');env=_env(path,version=version);calls=[]
    def invoke(argv,expected=0):
        start=len(client.trace);code,payload=gateway.execute_gateway(['--state-dir',str(path/'state'),*argv],env=env,client_factory=lambda _:client)
        calls.append({'gateway':{'argv':list(argv),'exit_code':code,'payload':payload},'native_start':start,'native_end':len(client.trace)})
        assert code==expected,payload
        return payload
    current=invoke(['draft-start',PREFIX+'create']);draft=current['draft']['draft_id'];authority=current['task_authority']
    current=invoke(['draft-bind-object',draft,'--task-authority',authority,'--expected-revision',str(current['draft']['revision']),
        '--role','target','--object-id',client.target_id])
    target=current['bound_object']['handle']
    current=invoke(['draft-declare-runtime-control-plan',draft,'--task-authority',authority,'--expected-revision',str(current['draft']['revision']),'--target-handle',target])
    current=invoke(['draft-check',draft,'--task-authority',authority,'--expected-revision',str(current['draft']['revision'])])
    preview=invoke(['preview-from-draft',draft,'--task-authority',authority,'--expected-revision',str(current['draft']['revision'])])
    shown=invoke(preview['next_command']['gateway_argv']);invoke(shown['next_command']['gateway_argv'])
    executed=invoke(['execute',preview['transaction_id']],expected=2)
    assert executed['state']=='indeterminate'and executed['executed']is True and executed['verified']is False
    assert executed['error_code']=='TRANSPORT_HANDLE_RESULT_INVALID'
    assert executed['cleanup']['status']=='unknown'and executed['cleanup']['spec']['binding']['materialized']is False
    assert not executed.get('agent_result')
    assert not list((path/'state'/'runtime-transport-handles-v1'/'records').glob('*.json'))
    native,=[r for r in client.trace if r['uri']==PREFIX+'create'];assert native['result']=={}
    journal=[json.loads(line)for line in (path/'state'/'transactions'/preview['transaction_id']/'events.jsonl').read_text().splitlines()]
    assert journal[-1]['event_type']=='execution_indeterminate'
    assert journal[-1]['details']['dispatch_result']['result']=={}
    return calls,client.trace,context,journal


def test_transport_native_valid_create_omission_keeps_uncertainty_and_no_handle(request,tmp_path):
    from tests.support.runtime_transport_evidence import original_transport,write_transport_bundle
    route=f'2024.1|wwise-console|{BUILDS["2024.1"]}|function|'+PREFIX+'create'
    inventory=log_inventory(route,pointers={'/argsSchema','/resultSchema','/resultSchema/@empty/object','/resultSchema/properties/transport/@presence/absent'})
    baseline=public_lifecycle(tmp_path/'baseline','2024.1','wwise-console',{PREFIX+'create':original_transport(route)},only_bound=True)
    uncertain=public_create_omission(tmp_path/'uncertain','2024.1','wwise-console')
    def finalize(phases):
        from tests.support.runtime_transport_evidence import write_transport_preservation_receipt
        calls,trace,stages,sources=baseline;stage=next(s for s in stages if s['uri']==PREFIX+'create')
        native,=[r for r in trace if r['uri']==PREFIX+'create'];path=tmp_path/'positive.json'
        runtime.write_program_receipt(path,calls[stage['receipt_index']]['gateway'],{k:native[k]for k in ('uri','args','options','result')},
            nodeid=request.node.nodeid,phase_reports=phases,source_context=sources[stage['uri']],native_reads=trace,public_calls=calls)
        cap=json.loads(path.read_bytes());cap.update(transport_stage=stage,transport_stages=stages);runtime.write_json(path,cap)
        uc,ut,context,journal=uncertain;native,=[r for r in ut if r['uri']==PREFIX+'create'];up=tmp_path/'uncertain.json'
        write_transport_preservation_receipt(up,uc[-1]['gateway'],{k:native[k]for k in ('uri','args','options','result')},
            nodeid=request.node.nodeid,phase_reports=phases,source_context=context,native_reads=ut,public_calls=uc,journal=journal)
        index=write_transport_bundle(tmp_path/'bundle',[path,up],inventory=inventory,name_prefix='transport-2024.1-')
        policies=json.loads((index.parent/'requirements.json').read_bytes());bindings,base,_=audit.portable_binding_inputs(index,policies)
        result=completion.evaluate_coverage(audit.ROOT,inventory,bindings,digest=audit.digest,evidence_base=base,requirements_document=policies)
        runtime.write_json(tmp_path/'consumer-result.json',result)
        assert {r['state']for r in result['obligations']}=={'verified'},[(r['id'],r['reasons'])for r in result['obligations']if r['state']!='verified']
        identity=route+'|/resultSchema/@empty/object'
        original_bound=bindings['bindings'][identity]
        original_record=completion.read_sealed_artifact(original_bound['evidence']['program'],base)
        from wwise_waapi.canonical import canonical_sha256
        def evaluate(document):return completion.evaluate_coverage(audit.ROOT,inventory,document,digest=audit.digest,evidence_base=base,requirements_document=policies)
        for damage in ('wrong-exit','wrong-error','missing-journal','changed-journal','fake-success','fake-handle','fake-cleanup','wrong-operation','source','teardown','candidate','ordinal-bool'):
            damaged=deepcopy(bindings);bound=damaged['bindings'][identity];record=deepcopy(original_record);cap=record['runtime_read_program'];g=cap['gateway']
            if damage=='wrong-exit':g['exit_code']=0
            elif damage=='wrong-error':g['payload']['error_code']='OTHER_FAILURE'
            elif damage=='missing-journal':cap['transport_preservation'].pop('journal')
            elif damage=='changed-journal':
                event=cap['transport_preservation']['journal'][-1];event['details']['dispatch_result']['result']={'transport':0}
                event['event_hash']=canonical_sha256({k:v for k,v in event.items()if k!='event_hash'})
            elif damage=='fake-success':g['payload'].update(ok=True,state='verified',status='verified',verified=True)
            elif damage=='fake-handle':g['payload']['agent_result']={'business_result':{'transport_handle':'trh1-'+'a'*32}}
            elif damage=='fake-cleanup':g['payload']['cleanup']['status']='complete';g['payload']['cleanup']['spec']['binding']['materialized']=True
            elif damage=='wrong-operation':cap['native_call']['uri']='ak.wwise.core.log.clear';record['native_call']=cap['native_call']
            elif damage=='source':cap['source_context']['capture']['tests/support/runtime_transport_evidence.py']='0'*64
            elif damage=='teardown':cap['phase_reports']['teardown']='failed'
            elif damage=='candidate':record['candidate_sha256']='0'*64
            else:cap['native_reads'][0]['ordinal']=False
            cap['public_calls'][-1]['gateway']=g;record['gateway']=g
            bound['evidence']['program']={**runtime.write_json(base/('damage-'+damage+'.json'),record),'nodeid':request.node.nodeid}
            rejected=evaluate(damaged)
            assert next(r for r in rejected['obligations']if r['id']==identity)['state']!='verified',damage
        # A coherent attempt to lend uncertainty to an input leaf remains barred.
        other=route+'|/argsSchema';damaged=deepcopy(bindings);bound=damaged['bindings'][other];record=deepcopy(original_record)
        cap=record['runtime_read_program'];pointer='/native_call/args'
        record['branch_assertions'][other]={'native_shape_sha256':bound['native_shape_sha256'],'native_route':route,
            'checks':[{'pointer':pointer,'equals':record['native_call']['args']},{'pointer':'/gateway/payload/dispatch_result/result','equals':{}}]}
        bound.update(input={'gateway_argv':cap['gateway']['argv'],'selector':pointer},observation_pointer=pointer,
            gateway_observation_pointer='/gateway/payload/dispatch_result/result')
        bound['evidence']['program']={**runtime.write_json(base/'wrong-branch.json',record),'nodeid':request.node.nodeid}
        rejected=evaluate(damaged)
        assert next(r for r in rejected['obligations']if r['id']==other)['state']!='verified'
        # The changed emitter itself must refuse failed teardown or source drift
        # before producing an artifact; these reuse the actual uncertain packet.
        for label,bad_phases,bad_context in (('teardown',{**phases,'teardown':'failed'},context),('source',phases,{})):
            destination=tmp_path/('must-not-publish-'+label+'.json')
            with pytest.raises(ValueError):
                write_transport_preservation_receipt(destination,uc[-1]['gateway'],{k:native[k]for k in ('uri','args','options','result')},
                    nodeid=request.node.nodeid,phase_reports=bad_phases,source_context=bad_context,native_reads=ut,public_calls=uc,journal=journal)
            assert not destination.exists()
        # Correct conditional handling still cannot supply its own native root.
        damaged=deepcopy(bindings);damaged['bindings'][route+'|/resultSchema']['evidence'].pop('native')
        rejected=completion.evaluate_coverage(audit.ROOT,inventory,damaged,digest=audit.digest,evidence_base=base,requirements_document=policies)
        assert all(r['state']!='verified'for r in rejected['obligations'])
    register_exact_evidence_finalizer(request.node,finalize)


def public_list_result(path,version,host,value):
    path.mkdir(parents=True)
    class ListClient(TransportClient):
        def call(self,uri,args=None,options=None):
            if uri==PREFIX+'getList':
                self.trace.append({'ordinal':len(self.trace),'uri':uri,'args':deepcopy(args),'options':deepcopy(options),'result':deepcopy(value)})
                return deepcopy(value)
            return super().call(uri,args,options)
    client=ListClient(path,version,host,'{11111111-1111-1111-1111-111111111111}')
    source=runtime.program_source_context(flow=PREFIX+'getList');env=_env(path,version=version);calls=[]
    def invoke(argv):
        start=len(client.trace);code,payload=gateway.execute_gateway(['--state-dir',str(path/'state'),*argv],env=env,client_factory=lambda _:client)
        assert code==0,payload
        calls.append({'gateway':{'argv':argv,'exit_code':code,'payload':payload},'native_start':start,'native_end':len(client.trace)})
        return payload
    schema=invoke(['request-schema',PREFIX+'getList']);read=invoke(['typed-zero-call',PREFIX+'getList','--schema-digest',schema['schema_digest']])
    assert read['agent_result']==value
    return calls,client.trace,[{'uri':PREFIX+'getList','start':0,'end':2,'receipt_index':1}],{PREFIX+'getList':source}


def test_transport_list_native_valid_partial_data_never_issues_authority(request,tmp_path):
    from tests.support.runtime_transport_evidence import original_transport,write_transport_bundle
    route=f'2024.1|wwise-console|{BUILDS["2024.1"]}|function|'+PREFIX+'getList'
    pointers={'/resultSchema','/resultSchema/@empty/object','/resultSchema/properties/list/@presence/absent',
        '/resultSchema/properties/list/items/@empty/object',*[f'/resultSchema/properties/list/items/properties/{k}/@presence/absent'for k in ('transport','object','gameObject')]}
    inventory=log_inventory(route,pointers=pointers);assert len(inventory['native_coverage']['obligations'])==7
    actual=original_transport(route)['call']['result']
    sessions=[public_list_result(tmp_path/str(i),'2024.1','wwise-console',value)for i,value in enumerate((actual,{}, {'list':[{}]}))]
    def finalize(phases):
        paths=[]
        for i,(calls,trace,stages,sources)in enumerate(sessions):
            stage=stages[0];native,=[r for r in trace if r['uri']==PREFIX+'getList'];path=tmp_path/f'capture-{i}.json'
            runtime.write_program_receipt(path,calls[-1]['gateway'],{k:native[k]for k in ('uri','args','options','result')},nodeid=request.node.nodeid,
                phase_reports=phases,source_context=sources[stage['uri']],native_reads=trace,public_calls=calls)
            cap=json.loads(path.read_bytes());cap.update(transport_stage=stage,transport_stages=stages);runtime.write_json(path,cap);paths.append(path)
        index=write_transport_bundle(tmp_path/'bundle',paths,inventory=inventory,name_prefix='transport-2024.1-')
        policies=json.loads((index.parent/'requirements.json').read_bytes());bindings,base,_=audit.portable_binding_inputs(index,policies)
        result=completion.evaluate_coverage(audit.ROOT,inventory,bindings,digest=audit.digest,evidence_base=base,requirements_document=policies)
        runtime.write_json(tmp_path/'consumer-result.json',result)
        assert {r['state']for r in result['obligations']}=={'verified'},[(r['id'],r['reasons'])for r in result['obligations']if r['state']!='verified']
    register_exact_evidence_finalizer(request.node,finalize)
