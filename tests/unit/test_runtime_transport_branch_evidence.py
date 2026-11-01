"""Direct public Gateway behavior with injected native responses."""

from copy import deepcopy

import json

import pytest

from tests.maintenance import branch_coverage_audit as audit

from tests.unit.test_runtime_business_gateway import _env, gateway, _RuntimeControlDraftClient

PREFIX='ak.wwise.core.transport.'

def transport_inputs(*suffixes):
    return {PREFIX + suffix: {'call': {'args': {'object': '{11111111-1111-1111-1111-111111111111}'}}}
            for suffix in suffixes}

BUILDS={'2021.1':'2021.1.14.8108','2022.1':'2022.1.19.8584','2023.1':'2023.1.19.8928','2024.1':'2024.1.13.9056','2025.1':'2025.1.7.9143'}

class TransportClient(_RuntimeControlDraftClient):
    """External Wwise boundary only; handles/transactions are the real product."""
    def __init__(self,path,version,host,target):
        super().__init__(path,version=version)
        self.console=host=='wwise-console';self.target_id=target;self.rows=[];self.states={};self.trace=[];self.create_ids=[0]
        self.objects={target:{'id':target,'name':'Play_Weather','type':'Event','path':r'\Events\Default Work Unit\Play_Weather'}}
        self.binding_target=target
    def call(self,uri,args=None,options=None):
        if uri==PREFIX+'create':
            native_id=self.create_ids.pop(0)if self.create_ids else 0
            self.rows.append({'transport':native_id,'object':args['object'],'gameObject':args.get('gameObject',18446744073709551614)})
            self.states[native_id]='stopped';result={'transport':native_id}
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
        elif uri=='ak.wwise.core.object.get'and isinstance(args,dict)and args.get('from',{}).get('id')and set(args['from']['id'])<=self.objects.keys():
            result={'return':[deepcopy(self.objects[i])for i in args['from']['id']]}
        elif uri=='ak.wwise.core.object.get'and isinstance(args,dict)and ('path'in args.get('from',{})or 'ofType'in args.get('from',{})or args.get('waql','').startswith('from type Event')):
            result={'return':[deepcopy(self.objects[self.binding_target])]}
        else:
            result=super().call(uri,args,options)
            if uri=='ak.wwise.core.getInfo':
                year,major,minor,build=map(int,BUILDS[self.version].split('.'))
                result.update(isCommandLine=self.console)
                result['version'].update(year=year,major=major,minor=minor,build=build)
        self.trace.append({'ordinal':len(self.trace),'uri':uri,'args':deepcopy(args),'options':deepcopy(options),'result':deepcopy(result)})
        return result

def public_lifecycle(path,version,host,originals,*,selector='id',only_bound=False,rich=False,media_rejections=None,media_only=False):
    path.mkdir(parents=True);target=originals[PREFIX+'create']['call']['args']['object']
    client=TransportClient(path,version,host,target);env=_env(path,version=version);calls=[];stages=[]
    if rich:client.create_ids=[0xffffffff,0]
    if PREFIX+'prepare'in originals:
        prepare_target=originals[PREFIX+'prepare']['call']['args']['object']
        if prepare_target not in client.objects:client.objects[prepare_target]={'id':prepare_target,'name':'Play_Prepare','type':'Event','path':r'\Events\Default Work Unit\Play_Prepare'}
    sources=dict.fromkeys(originals)
    def invoke(argv):
        start=len(client.trace)
        code,payload=gateway.execute_gateway(['--state-dir',str(path/'state'),*argv],env=env,client_factory=lambda _:client)
        receipt={'argv':list(argv),'exit_code':code,'payload':payload}
        calls.append({'gateway':receipt,'native_start':start,'native_end':len(client.trace)})
        assert code==0,payload
        return payload
    def transaction(uri,fields=(),bind=False,bound_target=None):
        first=len(calls);started=invoke(['draft-start',uri]);draft=started['draft']['draft_id'];authority=started['task_authority'];current=started
        if bind:
            selected=target if bound_target is None else bound_target;client.binding_target=selected;obj=client.objects[selected]
            binding=(['--object-id',selected]if selector=='id'else ['--exact-type-name',obj['type'],obj['name']]if selector=='qualified-name'
                else [item for segment in obj['path'].split('\\')[1:]for item in ('--object-path-segment',segment)])
            current=invoke(['draft-bind-object',draft,'--task-authority',authority,'--expected-revision',str(current['draft']['revision']),'--role','target',*binding])
            fields=('--target-handle',current['bound_object']['handle'],*fields)
        declaration=['draft-declare-runtime-control-plan',draft,'--task-authority',authority,'--expected-revision',str(current['draft']['revision'])]
        if uri==PREFIX+'useOriginals'and media_rejections is not None:
            start=len(client.trace);code,rejected=gateway.execute_gateway(['--state-dir',str(path/'state'),*declaration],env=env,client_factory=lambda _:client)
            assert code==2 and rejected['ok']is False and not any(r['uri']==uri for r in client.trace[start:]),rejected
            media_rejections.append({'stage_index':len(stages),'gateway':{'argv':declaration,'exit_code':code,'payload':rejected},'native_calls':deepcopy(client.trace[start:])})
            del client.trace[start:]
        current=invoke([*declaration,*fields])
        current=invoke(['draft-check',draft,'--task-authority',authority,'--expected-revision',str(current['draft']['revision'])])
        preview=invoke(['preview-from-draft',draft,'--task-authority',authority,'--expected-revision',str(current['draft']['revision'])])
        shown=invoke(preview['next_command']['gateway_argv']);invoke(shown['next_command']['gateway_argv'])
        executed=invoke(['execute',preview['transaction_id']]);verified=invoke(executed['next_command']['gateway_argv'])
        stages.append({'uri':uri,'start':first,'end':len(calls),'receipt_index':len(calls)-1})
        return verified
    def list_read():
        first=len(calls);schema=invoke(['request-schema',PREFIX+'getList'])
        listed=invoke(['typed-zero-call',PREFIX+'getList','--schema-digest',schema['schema_digest']])
        stages.append({'uri':PREFIX+'getList','start':first,'end':len(calls),'receipt_index':len(calls)-1})
        assert listed['agent_result']=={'list':client.rows}
    def state_read(handle,expected):
        first=len(calls);state=invoke(['core-call',PREFIX+'getState','--transport-handle',handle])
        stages.append({'uri':PREFIX+'getState','start':first,'end':len(calls),'receipt_index':len(calls)-1})
        assert state['agent_result']=={'transport_handle':handle,'state':expected}
    if not only_bound and PREFIX+'useOriginals'in originals:transaction(PREFIX+'useOriginals',('--audition-media','converted'if rich else'originals'))
    if media_only:return calls,client.trace,stages,sources
    if PREFIX+'prepare'in originals:transaction(PREFIX+'prepare',bind=True,bound_target=prepare_target)
    created=transaction(PREFIX+'create',('--game-object-id','0')if rich else(),bind=True)
    handle=created['agent_result']['business_result']['transport_handle'];assert handle.startswith('trh1-');handles=[handle]
    if rich:
        second=transaction(PREFIX+'create',('--game-object-id','18446744073709551615'),bind=True)
        handles.append(second['agent_result']['business_result']['transport_handle']);assert handles[0]!=handles[1]
    if not only_bound:
        list_read();state_read(handle,'stopped')
        for i,action in enumerate(('play','pause','pause','toggle-play-stop','play-directly')if rich else('play','stop')):
            transaction(PREFIX+'executeAction',('--audition-action',action,'--transport-scope','one-transport','--transport-handle',handle))
            if rich and i in (0,1):state_read(handle,'playing'if i==0 else'paused')
        if rich:transaction(PREFIX+'executeAction',('--audition-action','stop','--transport-scope','all-active'))
    for old in handles:
        destroyed=transaction(PREFIX+'destroy',('--transport-handle',old));assert destroyed['verified']is True
    assert client.rows==[]
    if rich:list_read()
    # Retired authority must not dispatch another state/action after cleanup.
    before=len(client.trace)
    for old in handles:
        code,bad=gateway.execute_gateway(['--state-dir',str(path/'state'),'core-call',PREFIX+'getState','--transport-handle',old],env=env,client_factory=lambda _:client)
        assert code==2 and not any(r['uri']==PREFIX+'getState'for r in client.trace[before:])
    return calls,client.trace[:before],stages,sources

def test_transport_name_path_normalization_requires_public_identity_and_readback(tmp_path):
    originals = transport_inputs('create', 'prepare')
    for selector in ('id', 'qualified-name', 'path'):
        public_lifecycle(tmp_path / selector, '2024.1', 'wwise-console', originals, selector=selector, only_bound=True)

def public_create_omission(path,version,host):
    path.mkdir(parents=True)
    class MissingIdClient(TransportClient):
        def call(self,uri,args=None,options=None):
            result=super().call(uri,args,options)
            if uri==PREFIX+'create':
                result={};self.trace[-1]['result']={}
            return result
    client=MissingIdClient(path,version,host,'{11111111-1111-1111-1111-111111111111}')
    context=None;env=_env(path,version=version);calls=[]
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

def test_transport_native_valid_create_omission_keeps_uncertainty_and_no_handle(tmp_path):
    public_lifecycle(tmp_path / 'baseline', '2024.1', 'wwise-console', transport_inputs('create'), only_bound=True)
    public_create_omission(tmp_path / 'uncertain', '2024.1', 'wwise-console')

def public_list_result(path,version,host,value):
    path.mkdir(parents=True)
    class ListClient(TransportClient):
        def call(self,uri,args=None,options=None):
            if uri==PREFIX+'getList':
                self.trace.append({'ordinal':len(self.trace),'uri':uri,'args':deepcopy(args),'options':deepcopy(options),'result':deepcopy(value)})
                return deepcopy(value)
            return super().call(uri,args,options)
    client=ListClient(path,version,host,'{11111111-1111-1111-1111-111111111111}')
    source=None;env=_env(path,version=version);calls=[]
    def invoke(argv):
        start=len(client.trace);code,payload=gateway.execute_gateway(['--state-dir',str(path/'state'),*argv],env=env,client_factory=lambda _:client)
        assert code==0,payload
        calls.append({'gateway':{'argv':argv,'exit_code':code,'payload':payload},'native_start':start,'native_end':len(client.trace)})
        return payload
    schema=invoke(['request-schema',PREFIX+'getList']);read=invoke(['typed-zero-call',PREFIX+'getList','--schema-digest',schema['schema_digest']])
    assert read['agent_result']==value
    return calls,client.trace,[{'uri':PREFIX+'getList','start':0,'end':2,'receipt_index':1}],{PREFIX+'getList':source}

def test_transport_list_native_valid_partial_data_never_issues_authority(tmp_path):
    for i, value in enumerate(({'list': []}, {}, {'list': [{}]})):
        public_list_result(tmp_path / str(i), '2024.1', 'wwise-console', value)
    assert not list(tmp_path.glob('*/state/runtime-transport-handles-v1/records/*.json'))

def test_transport_independent_readbacks_bind_action_scope_and_retirement(tmp_path):
    for label, rich in (('single', False), ('cohort', True)):
        public_lifecycle(tmp_path / label, '2024.1', 'wwise-console', transport_inputs('create', 'executeAction', 'destroy', 'getList', 'getState'), rich=rich)

def test_transport_2023_explicit_media_boundary_public_teardown_consumer(tmp_path):
    for host in ('wwise-console', 'wwise-authoring'):
        for rich in (False, True):
            rejected = []
            public_lifecycle(tmp_path / (host + str(rich)), '2023.1', host,
                transport_inputs('create', 'useOriginals'), rich=rich, media_rejections=rejected, media_only=True)
            assert len(rejected) == 1
