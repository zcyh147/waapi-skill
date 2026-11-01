"""Direct public Gateway behavior with injected native responses."""

from copy import deepcopy

import json

import pytest

from tests.maintenance import branch_coverage_audit as audit

from tests.unit.test_runtime_business_gateway import _env,gateway,_RuntimeControlDraftClient

from tests.unit.test_runtime_cursor_branch_evidence import BUILDS

PREFIX='ak.wwise.core.profiler.'

METER_URIS={PREFIX+'registerMeter',PREFIX+'unregisterMeter'}

def meter_pair(path,version,host,selector,row):
    path.mkdir(parents=True);client=_RuntimeControlDraftClient(path,version=version);original=client.call;trace=[];calls=[]
    def call(uri,args=None,options=None):
        if uri in METER_URIS:value={}
        elif uri=='ak.wwise.core.object.get':value={'return':[deepcopy(row)]}
        else:value=original(uri,args,options)
        if uri=='ak.wwise.core.getInfo':
            year,major,minor,build=map(int,BUILDS[version].split('.'));value['version'].update(year=year,major=major,minor=minor,build=build);value['isCommandLine']=host=='wwise-console'
        trace.append({'ordinal':len(trace),'uri':uri,'args':deepcopy(args),'options':deepcopy(options),'result':deepcopy(value)})
        return value
    client.call=call;context=None
    def invoke(argv):
        start=len(trace);code,payload=gateway.execute_gateway(['--state-dir',str(path/'state'),*argv],env=_env(path,version=version),client_factory=lambda _:client)
        assert code==0,payload
        calls.append({'gateway':{'argv':list(argv),'exit_code':code,'payload':payload},'native_start':start,'native_end':len(trace)})
        return payload
    def operation(uri):
        started=invoke(['draft-start',uri]);draft=started['draft']['draft_id'];authority=started['task_authority']
        identity=(['--object-id',row['id']]if selector=='id'else
            ['--exact-type-name',row['type'],row['name']]if selector=='exact-type-name'else
            [x for segment in row['path'].strip('\\').split('\\')for x in ('--object-path-segment',segment)])
        bound=invoke(['draft-bind-object',draft,'--task-authority',authority,'--expected-revision',str(started['draft']['revision']),'--role','meter_object',*identity])
        declared=invoke(['draft-declare-runtime-control-plan',draft,'--task-authority',authority,'--expected-revision',str(bound['draft']['revision']),'--meter-object-handle',bound['bound_object']['handle']])
        checked=invoke(['draft-check',draft,'--task-authority',authority,'--expected-revision',str(declared['draft']['revision'])])
        preview=invoke(['preview-from-draft',draft,'--task-authority',authority,'--expected-revision',str(checked['draft']['revision'])])
        shown=invoke(preview['next_command']['gateway_argv']);invoke(shown['next_command']['gateway_argv'])
        executed=invoke(['execute',preview['transaction_id']]);verified=invoke(executed['next_command']['gateway_argv'])
        assert verified['verified']is False and verified['state']=='result_schema_checked'
        assert verified['verification']['business_state_verified']is False
        return calls[-1]['gateway']
    try:register=operation(PREFIX+'registerMeter')
    finally:unregister=operation(PREFIX+'unregisterMeter')
    assert [x['uri']for x in trace if x['uri']in METER_URIS]==[PREFIX+'registerMeter',PREFIX+'unregisterMeter']
    return [(receipt,{k:next(x for x in trace if x['uri']==uri)[k]for k in ('uri','args','options','result')},
        None,deepcopy(trace),deepcopy(calls))for receipt,uri in ((register,PREFIX+'registerMeter'),(unregister,PREFIX+'unregisterMeter'))]

@pytest.mark.parametrize('version',['2025.1','remaining'])
def test_meter_controls_public_pair_teardown_and_consumer(request,tmp_path,version):
    contexts=[('2025.1','wwise-authoring')]if version=='2025.1'else[('2025.1','wwise-console'),('2024.1','wwise-authoring'),('2024.1','wwise-console')]
    routes=[f'{v}|{host}|{BUILDS[v]}|function|{uri}'for v,host in contexts for uri in sorted(METER_URIS)]
    captures=[]
    for v,host in contexts:
        row={'id':'{11111111-1111-1111-1111-111111111111}', 'type':'Bus', 'name':'Meter', 'path':r'\Master-Mixer Hierarchy\Default Work Unit\Meter'}
        for selector in ('id','path','exact-type-name'):
            captures.extend(meter_pair(tmp_path/(v+'-'+host+'-'+selector),v,host,selector,row))

def save_capture_flow(path,version,host):
    path.mkdir(parents=True);output=path/'captures';output.mkdir();destination=output/'Owned.prof';sentinel=output/'unrelated.txt';sentinel.write_bytes(b'preserve')
    client=_RuntimeControlDraftClient(path,version=version);original=client.call;trace=[];calls=[];rejections=[];uri=PREFIX+'saveCapture'
    def call(api,args=None,options=None):
        if api==uri:destination.write_bytes(b'opaque owned capture bytes');value={}
        else:value=original(api,args,options)
        if api=='ak.wwise.core.getInfo':
            year,major,minor,build=map(int,BUILDS[version].split('.'));value['version'].update(year=year,major=major,minor=minor,build=build);value['isCommandLine']=host=='wwise-console'
        trace.append({'ordinal':len(trace),'uri':api,'args':deepcopy(args),'options':deepcopy(options),'result':deepcopy(value)})
        return value
    client.call=call;context=None
    def invoke(argv,*,reject=False):
        start=len(trace);code,payload=gateway.execute_gateway(['--state-dir',str(path/'state'),*argv],env=_env(path,version=version),client_factory=lambda _:client)
        receipt={'argv':list(argv),'exit_code':code,'payload':payload}
        if reject:
            assert code==2 and payload['ok']is False and not any(x['uri']==uri for x in trace[start:]),payload
            rejections.append({'gateway':receipt,'native_calls':deepcopy(trace[start:])});del trace[start:]
        else:
            assert code==0,payload;calls.append({'gateway':receipt,'native_start':start,'native_end':len(trace)})
        return payload
    started=invoke(['draft-start',uri]);draft=started['draft']['draft_id'];authority=started['task_authority']
    base=['draft-declare-runtime-control-plan',draft,'--task-authority',authority,'--expected-revision',str(started['draft']['revision'])]
    for directory,name in (('', 'Owned'),(str(output),'')):
        invoke([*base,'--capture-output-directory',directory,'--capture-name',name],reject=True)
    declared=invoke([*base,'--capture-output-directory',str(output),'--capture-name','Owned'])
    checked=invoke(['draft-check',draft,'--task-authority',authority,'--expected-revision',str(declared['draft']['revision'])])
    preview=invoke(['preview-from-draft',draft,'--task-authority',authority,'--expected-revision',str(checked['draft']['revision'])])
    shown=invoke(preview['next_command']['gateway_argv']);invoke(shown['next_command']['gateway_argv'])
    executed=invoke(['execute',preview['transaction_id']]);verified=invoke(executed['next_command']['gateway_argv']);receipt=calls[-1]['gateway']
    assert verified['verified']is True and verified['verification']['business_state_verified']is True
    full=invoke(['transaction-show',preview['transaction_id']])
    evidence=next(e['details']['verification']for e in reversed(full['events'])if e['event_type']=='verification_recorded')
    assert evidence['readbacks'][0]['path']==str(destination)and evidence['readbacks'][0]['unrelated_files_preserved']is True
    assert sentinel.read_bytes()==b'preserve'and destination.read_bytes()==b'opaque owned capture bytes'
    native,=[x for x in trace if x['uri']==uri]
    return receipt,{k:native[k]for k in ('uri','args','options','result')},context,trace,calls,rejections

@pytest.mark.parametrize('version',['2025.1','remaining'])
def test_save_capture_boundary_teardown_portable_consumer(request,tmp_path,version):
    contexts=[('2025.1','wwise-authoring')]if version=='2025.1'else[('2023.1','wwise-authoring'),('2023.1','wwise-console'),('2024.1','wwise-authoring'),('2024.1','wwise-console'),('2025.1','wwise-console')]
    routes=[f'{v}|{host}|{BUILDS[v]}|function|{PREFIX}saveCapture'for v,host in contexts]
    captures=[save_capture_flow(tmp_path/(v+'-'+host),v,host)for v,host in contexts]

def cursor_control_flow(path,host,uri,choice,time_ms):
    import contextlib
    import io
    path.mkdir(parents=True);version='2025.1';client=_RuntimeControlDraftClient(path,version=version);original=client.call;trace=[];calls=[];rejection=None
    def call(api,args=None,options=None):
        value={'return':time_ms}if api in {uri,PREFIX+'getCursorTime'}else original(api,args,options)
        if api=='ak.wwise.core.getInfo':
            year,major,minor,build=map(int,BUILDS[version].split('.'));value['version'].update(year=year,major=major,minor=minor,build=build);value['isCommandLine']=host=='wwise-console'
        trace.append({'ordinal':len(trace),'uri':api,'args':deepcopy(args),'options':deepcopy(options),'result':deepcopy(value)});return value
    client.call=call;context=None
    def invoke(argv,*,reject=False):
        start=len(trace);out,err=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            try:code,payload=gateway.execute_gateway(['--state-dir',str(path/'state'),*argv],env=_env(path,version=version),client_factory=lambda _:client)
            except SystemExit as exc:code,payload=exc.code,None
        receipt={'argv':list(argv),'exit_code':code,'payload':payload,'stdout':out.getvalue(),'stderr':err.getvalue()}
        if reject:
            assert code==2 and payload is None and trace[start:]==[]
            return {'gateway':receipt,'native_calls':[]}
        assert code==0,payload;calls.append({'gateway':receipt,'native_start':start,'native_end':len(trace)});return payload
    started=invoke(['draft-start',uri]);draft=started['draft']['draft_id'];authority=started['task_authority'];flag='--cursor-move'if uri.endswith('.moveCursor')else'--cursor-target-ms'
    argv=['draft-declare-runtime-control-plan',draft,'--task-authority',authority,'--expected-revision',str(started['draft']['revision']),flag,str(choice)]
    if uri.endswith('.moveCursor'):rejection=invoke([*argv[:-1],''],reject=True)
    declared=invoke(argv);checked=invoke(['draft-check',draft,'--task-authority',authority,'--expected-revision',str(declared['draft']['revision'])])
    preview=invoke(['preview-from-draft',draft,'--task-authority',authority,'--expected-revision',str(checked['draft']['revision'])])
    shown=invoke(preview['next_command']['gateway_argv']);invoke(shown['next_command']['gateway_argv'])
    executed=invoke(['execute',preview['transaction_id']]);verified=invoke(executed['next_command']['gateway_argv']);receipt=calls[-1]['gateway']
    assert verified['verified']is True and verified['verification']['business_state_verified']is True
    invoke(['transaction-show',preview['transaction_id']]);native,=[x for x in trace if x['uri']==uri]
    return receipt,{k:native[k]for k in ('uri','args','options','result')},context,trace,calls,rejection

@pytest.mark.parametrize('host',['wwise-authoring','wwise-console'])
def test_cursor_controls_teardown_portable_consumer(request,tmp_path,host):
    uris=(PREFIX+'setCursorTime',PREFIX+'moveCursor')
    choices=[(uris[0],38549,38549),(uris[1],'first-frame',10133),(uris[1],'next-frame',10144),(uris[1],'last-frame',13600),(uris[1],'previous-frame',13589)]
    captures=[cursor_control_flow(tmp_path/str(i),host,u,choice,time)for i,(u,choice,time)in enumerate(choices)]
