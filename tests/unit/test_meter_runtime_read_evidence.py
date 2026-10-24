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
        missing=deepcopy(document);missing['bindings'][route+'|/resultSchema']['evidence'].pop('native')
        blocked=completion.evaluate_coverage(audit.ROOT,inventory,missing,digest=audit.digest,evidence_base=base,requirements_document=policies)
        assert all(r['state']!='verified'for r in blocked['obligations'])
    register_exact_evidence_finalizer(request.node,finalize)
