"""Direct public Gateway behavior with injected native responses."""

from copy import deepcopy

import json

from pathlib import Path

import pytest

from tests.maintenance import branch_coverage_audit as audit

from tests.unit.test_runtime_business_gateway import gateway,_env,_RuntimeControlDraftClient

URIS=tuple('ak.wwise.core.profiler.'+n for n in ('getCpuUsage','getPerformanceMonitor','getStreamedMedia'))

BUILDS={'2023.1':'2023.1.19.8928','2024.1':'2024.1.13.9056','2025.1':'2025.1.7.9143'}

def public_read(path,uri,version,console,rows,position):
    path.mkdir(parents=True);context=None
    client=_RuntimeControlDraftClient(path,version=version);fallback=client.call;trace=[]
    def call(api,args=None,options=None):
        result=({'return':deepcopy(rows)}if api==uri else {'return':99328}if api.endswith('.getCursorTime')else fallback(api,args,options))
        if api=='ak.wwise.core.getInfo':
            y,major,minor,build=map(int,BUILDS[version].split('.'));result['version'].update(year=y,major=major,minor=minor,build=build,displayName='v'+BUILDS[version]);result['isCommandLine']=console
        trace.append({'ordinal':len(trace),'uri':api,'args':deepcopy(args),'options':deepcopy(options),'result':deepcopy(result)})
        return result
    client.call=call;argv=['core-call',uri,'--profiler-position',str(position),'--max-results','64']
    code,payload=gateway.execute_gateway(['--state-dir',str(path/'state'),*argv],env=_env(path,version=version),client_factory=lambda _:client)
    assert code==0,payload
    first={'argv':argv,'exit_code':code,'payload':payload};calls=[{'gateway':first,'native_start':0,'native_end':len(trace)}];allrows=[]
    while True:
        page=payload['agent_result'];allrows=page['return']+allrows
        if page.get('complete',True):break
        nextargv=page['next_command']['full_argv'][3:]
        code,payload=gateway.execute_gateway(nextargv,env=_env(path,version=version),client_factory=lambda _:pytest.fail('Retained diagnostic page connected'))
        assert code==0,payload;calls.append({'gateway':{'argv':nextargv,'exit_code':code,'payload':payload},'native_start':len(trace),'native_end':len(trace)})
        assert len(calls)<=128
    assert allrows==rows and list(first['payload'])[-1]=='agent_result'
    native,=[r for r in trace if r['uri']==uri]
    return first,{k:native[k]for k in ('uri','args','options','result')},context,trace,calls

@pytest.mark.parametrize('version', ['2023.1', '2024.1', '2025.1'])
@pytest.mark.parametrize('console', [True, False])
def test_extra_diagnostic_reads_public_teardown_portable_consumer(tmp_path, version, console):
    rows = [
        [{'id': 0, 'type': '', 'elementName': 'Audio', 'instances': 2, 'millisecondsExclusive': 0.014,
          'millisecondsInclusive': 0.2167, 'percentExclusive': 0.13, 'percentInclusive': 2.03}],
        [{'id': 'ActiveTransitions', 'name': 'Transitions', 'value': 0}],
        [{'deviceName': 'Disk', 'streamName': 'Stream', 'fileSize': 1, 'filePosition': 0.5, 'priority': 1,
          'bandwidthTotal': 1, 'bandwidthLowLevel': 1, 'referencedMemory': 1, 'estimatedThroughput': 1,
          'active': True, 'targetBufferSize': 1, 'bufferStatusBuffered': 1.0}],
    ]
    for i, (uri, result) in enumerate(zip(URIS, rows)):
        for j, (values, position) in enumerate([(result, 0), (result * 2, 1), ([], 2),
                                               (result, 'capture-latest'), (result, 'user-cursor')]):
            public_read(tmp_path / f'{i}-{j}', uri, version, console, values, position)
