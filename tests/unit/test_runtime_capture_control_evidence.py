"""Direct public Gateway behavior with injected native responses."""

from copy import deepcopy

import json

import pytest

from tests.maintenance import branch_coverage_audit as audit

from tests.unit.test_runtime_business_gateway import _env, gateway, _RuntimeControlDraftClient

from tests.unit.test_runtime_cursor_branch_evidence import BUILDS

PREFIX='ak.wwise.core.profiler.'

URIS={PREFIX+n for n in ('enableProfilerData','startCapture','stopCapture')}

def capture_control_flow(path,version,host,uri,args,result):
    path.mkdir(parents=True)
    client=_RuntimeControlDraftClient(path,version=version);trace=[];calls=[];original=client.call
    def call(api,native_args=None,options=None):
        if api in URIS:value=deepcopy(result)if api==uri else{}
        else:value=original(api,native_args,options)
        if api=='ak.wwise.core.getInfo':
            year,major,minor,build=map(int,BUILDS[version].split('.'))
            value['version'].update(year=year,major=major,minor=minor,build=build)
            value['isCommandLine']=host=='wwise-console'
        trace.append({'ordinal':len(trace),'uri':api,'args':deepcopy(native_args),'options':deepcopy(options),'result':deepcopy(value)})
        return value
    client.call=call;context=None
    def invoke(argv):
        start=len(trace);code,payload=gateway.execute_gateway(['--state-dir',str(path/'state'),*argv],env=_env(path,version=version),client_factory=lambda _:client)
        assert code==0,payload
        receipt={'argv':list(argv),'exit_code':code,'payload':payload}
        calls.append({'gateway':receipt,'native_start':start,'native_end':len(trace)})
        return payload
    if uri.endswith('.enableProfilerData'):
        reverse={'voices': 'voices'}
        declaration=['--capture-data-empty']if not args['dataTypes']else[x for row in args['dataTypes']for x in ('--capture-data',reverse[row['dataType']],'enable'if row['enable']else'disable')]
        started=invoke(['draft-start',uri]);draft=started['draft']['draft_id'];authority=started['task_authority']
        if version=='2025.1':
            before=len(trace)
            code,rejected=gateway.execute_gateway(['--state-dir',str(path/'state'),'draft-declare-runtime-control-plan',draft,
                '--task-authority',authority,'--expected-revision',str(started['draft']['revision'])],
                env=_env(path,version=version),client_factory=lambda _:client)
            assert code==2 and rejected['ok']is False and not any(x['uri']in URIS for x in trace[before:])
            # Rejection is a separate receipt, not part of this successful span.
            del trace[before:]
        current=invoke(['draft-declare-runtime-control-plan',draft,'--task-authority',authority,'--expected-revision',str(started['draft']['revision']),*declaration])
        current=invoke(['draft-check',draft,'--task-authority',authority,'--expected-revision',str(current['draft']['revision'])])
        preview=invoke(['preview-from-draft',draft,'--task-authority',authority,'--expected-revision',str(current['draft']['revision'])])
    else:
        schema=invoke(['request-schema',uri]);preview=invoke(schema['continuation']['gateway_argv'])
    shown=invoke(preview['next_command']['gateway_argv']);invoke(shown['next_command']['gateway_argv'])
    def paired_stop():
        schema=invoke(['request-schema',PREFIX+'stopCapture']);stop=invoke(schema['continuation']['gateway_argv'])
        shown=invoke(stop['next_command']['gateway_argv']);invoke(shown['next_command']['gateway_argv'])
        done=invoke(['execute',stop['transaction_id']]);invoke(done['next_command']['gateway_argv'])
    try:
        executed=invoke(['execute',preview['transaction_id']]);verified=invoke(executed['next_command']['gateway_argv'])
        target_receipt=calls[-1]['gateway']
    finally:
        if uri.endswith('.startCapture'):paired_stop()
    native,=[x for x in trace if x['uri']==uri]
    assert native['args']==args and native['options']=={}
    assert verified['agent_result']['result']==result
    assert verified['verified']is False and verified['state']=='result_schema_checked'
    assert verified['verification']['business_state_verified']is False
    code,rejected=gateway.execute_gateway(['--state-dir',str(path/'state'),'execute',preview['transaction_id']],env=_env(path,version=version),client_factory=lambda _:client)
    assert code==2,rejected
    assert sum(x['uri']==uri for x in trace)==1
    return target_receipt,{k:native[k]for k in ('uri','args','options','result')},context,trace[:calls[-1]['native_end']],calls

@pytest.mark.parametrize('version',['2025.1','2021.1','2022.1','2023.1','2024.1'])
def test_capture_control_paired_hosts_public_teardown_consumer(request,tmp_path,version):
    for host in ('wwise-console', 'wwise-authoring'):
        for suffix, args in [('enableProfilerData', {'dataTypes': [{'dataType': 'voices', 'enable': True}]}),
                             ('startCapture', {}), ('stopCapture', {})]:
            capture_control_flow(tmp_path / (host + suffix), version, host, PREFIX + suffix, args, {})
