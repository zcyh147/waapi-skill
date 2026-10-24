"""Owned meter/file/cursor controls through real public transactions and teardown."""
from copy import deepcopy
import json

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support import runtime_observation_evidence as runtime
from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
from tests.unit.test_runtime_business_gateway import _env,gateway,_RuntimeControlDraftClient
from tests.unit.test_runtime_cursor_branch_evidence import BUILDS
from tests.unit.test_runtime_log_branch_evidence import log_inventory

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
    client.call=call;context=runtime.program_source_context(flow=PREFIX+'registerMeter')
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
        runtime.program_source_context(flow=uri),deepcopy(trace),deepcopy(calls))for receipt,uri in ((register,PREFIX+'registerMeter'),(unregister,PREFIX+'unregisterMeter'))]


@pytest.mark.parametrize('version',['2025.1','2024.1'])
def test_meter_controls_public_pair_teardown_and_consumer(request,tmp_path,version):
    from tests.support.runtime_owned_control_evidence import original_meter,write_owned_control_bundle
    hosts=('wwise-authoring',)if version=='2025.1'else('wwise-authoring',)
    routes=[f'{version}|{host}|{BUILDS[version]}|function|{uri}'for host in hosts for uri in sorted(METER_URIS)]
    inventory=log_inventory(routes);captures=[]
    for host in hosts:
        actual=original_meter(f'{version}|{host}|{BUILDS[version]}|function|{PREFIX}registerMeter')
        for selector in ('id','path','exact-type-name'):
            captures.extend(meter_pair(tmp_path/(host+'-'+selector),version,host,selector,actual['object']))
    def finalize(phases):
        paths=[]
        for i,(receipt,native,context,trace,calls)in enumerate(captures):
            path=tmp_path/f'capture-{i}.json'
            runtime.write_program_receipt(path,receipt,native,nodeid=request.node.nodeid,phase_reports=phases,source_context=context,native_reads=trace,public_calls=calls);paths.append(path)
        index=write_owned_control_bundle(tmp_path/'bundle',paths,inventory=inventory,name_prefix='owned-controls-'+version+'-meter-')
        policies=json.loads((index.parent/'requirements.json').read_bytes());bindings,base,_=audit.portable_binding_inputs(index,policies)
        def evaluate(document):return completion.evaluate_coverage(audit.ROOT,inventory,document,digest=audit.digest,evidence_base=base,requirements_document=policies)
        result=evaluate(bindings);runtime.write_json(tmp_path/'consumer-result.json',result)
        assert {r['state']for r in result['obligations']}=={'verified'},[(r['pointer'],r['evidence_results'])for r in result['obligations']if r['state']!='verified']
        for route in routes:
            missing=deepcopy(bindings);missing['bindings'][route+'|/resultSchema']['evidence'].pop('native')
            checked=evaluate(missing)
            assert all(r['state']!='verified'for r in checked['obligations']if r['route']==route)
            assert all(r['state']=='verified'for r in checked['obligations']if r['route']!=route)
    register_exact_evidence_finalizer(request.node,finalize)
