"""Direct public Gateway behavior with injected native responses."""

from copy import deepcopy

import json

import pytest

from tests.maintenance import branch_coverage_audit as audit

from tests.unit.test_runtime_business_gateway import _env, gateway, FakeClient

URI = 'ak.wwise.core.profiler.getCursorTime'

BUILDS = {'2021.1':'2021.1.14.8108','2022.1':'2022.1.19.8584','2023.1':'2023.1.19.8928',
          '2024.1':'2024.1.13.9056','2025.1':'2025.1.7.9143'}

def cursor_read(path, version, host, choice, value):
    path.mkdir(parents=True)
    year, major, minor, build = map(int, BUILDS[version].split('.'))
    info = {'displayName':'Wwise','isCommandLine':host=='wwise-console','apiVersion':1,
            'platform':'macosx','configuration':'release',
            'version':{'year':year,'major':major,'minor':minor,'build':build,
                       'displayName':'v'+BUILDS[version]}}
    client = FakeClient({'ak.wwise.core.getInfo':[info], URI:[deepcopy(value)]})
    trace=[]; original=client.call
    def call(uri,args=None,options=None):
        result=original(uri,args,options)
        trace.append({'ordinal':len(trace),'uri':uri,'args':deepcopy(args),'options':deepcopy(options),'result':deepcopy(result)})
        return result
    client.call=call
    context=None
    argv=['core-call',URI,'--profiler-cursor',choice]
    code,payload=gateway.execute_gateway(['--state-dir',str(path/'state'),*argv],env=_env(path,version=version),client_factory=lambda _:client)
    native,=[x for x in trace if x['uri']==URI]
    return {'argv':argv,'exit_code':code,'payload':payload}, {k:native[k]for k in ('uri','args','options','result')}, context, trace

@pytest.mark.parametrize('version',['2025.1','2021.1','2022.1','2023.1','2024.1'])
def test_cursor_paired_hosts_public_teardown_portable_consumer(request,tmp_path,version):
    captures=[]
    for host in ('wwise-console','wwise-authoring'):
        values=[('capture-latest',123),('user-cursor',0),('capture-latest',-1)]
        if version in {'2021.1','2022.1'}:values.append(('user-cursor',None))
        for choice,position in values:
            receipt,native,context,trace=cursor_read(tmp_path/(host+'-'+choice+'-'+str(position)),version,host,choice,{}if position is None else{'return':position})
            assert receipt['exit_code']==0,receipt
            assert native['args']=={'cursor':{'capture-latest':'capture','user-cursor':'user'}[choice]}
            assert receipt['payload']['agent_result']==({'profiler_cursor':choice,'available':False,'position_ms':None,
                'unavailable_reason':'native-position-not-returned'}if position is None else
                {'profiler_cursor':choice,'available':position!=-1,'position_ms':None if position==-1 else position})
            captures.append((receipt,native,context,trace))
        bad_values=[{'return':True},{'return':-2},{'return':'1'}]
        if version not in {'2021.1','2022.1'}:bad_values.append({})
        for number,bad in enumerate(bad_values):
            receipt,*_=cursor_read(tmp_path/(host+'-malformed-'+str(number)),version,host,'capture-latest',bad)
            assert receipt['exit_code']==2 and receipt['payload']['ok']is False
            assert 'agent_result'not in receipt['payload']
