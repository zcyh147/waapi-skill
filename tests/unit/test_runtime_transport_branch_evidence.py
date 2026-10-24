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
        else:
            result=super().call(uri,args,options)
            if uri=='ak.wwise.core.getInfo':
                year,major,minor,build=map(int,BUILDS[self.version].split('.'))
                result.update(isCommandLine=self.console)
                result['version'].update(year=year,major=major,minor=minor,build=build)
        self.trace.append({'ordinal':len(self.trace),'uri':uri,'args':deepcopy(args),'options':deepcopy(options),'result':deepcopy(result)})
        return result


def public_lifecycle(path,version,host,originals):
    path.mkdir(parents=True);target=originals[PREFIX+'create']['call']['args']['object']
    client=TransportClient(path,version,host,target);env=_env(path,version=version);calls=[];stages=[]
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
                '--role','target','--object-id',target])
            fields=('--target-handle',current['bound_object']['handle'],*fields)
        current=invoke(['draft-declare-runtime-control-plan',draft,'--task-authority',authority,'--expected-revision',str(current['draft']['revision']),*fields])
        current=invoke(['draft-check',draft,'--task-authority',authority,'--expected-revision',str(current['draft']['revision'])])
        preview=invoke(['preview-from-draft',draft,'--task-authority',authority,'--expected-revision',str(current['draft']['revision'])])
        shown=invoke(preview['next_command']['gateway_argv']);invoke(shown['next_command']['gateway_argv'])
        executed=invoke(['execute',preview['transaction_id']]);verified=invoke(executed['next_command']['gateway_argv'])
        stages.append({'uri':uri,'start':first,'end':len(calls),'receipt_index':len(calls)-1})
        return verified
    if PREFIX+'useOriginals'in originals:transaction(PREFIX+'useOriginals',('--audition-media','originals'))
    if PREFIX+'prepare'in originals:transaction(PREFIX+'prepare',bind=True)
    created=transaction(PREFIX+'create',bind=True)
    handle=created['agent_result']['business_result']['transport_handle'];assert handle.startswith('trh1-')
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
    return calls,trace,stages


def test_transport_2024_paired_host_lifecycle_teardown_portable_consumer(request,tmp_path):
    from tests.support.runtime_transport_evidence import original_transport,write_transport_bundle,URIS
    routes=[f'2024.1|{h}|{BUILDS["2024.1"]}|function|{u}'for h in ('wwise-console','wwise-authoring')for u in sorted(URIS)]
    inventory=log_inventory(routes,pointers={'/argsSchema','/optionsSchema','/resultSchema'});sessions=[]
    for host in ('wwise-console','wwise-authoring'):
        originals={u:original_transport(f'2024.1|{host}|{BUILDS["2024.1"]}|function|{u}')for u in URIS}
        sessions.append(public_lifecycle(tmp_path/host,'2024.1',host,originals))
    def finalize(phases):
        paths=[]
        for number,(calls,trace,stages)in enumerate(sessions):
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
                    source_context=runtime.program_source_context(flow=stage['uri']),native_reads=trace,public_calls=calls)
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
