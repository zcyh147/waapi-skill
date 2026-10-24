"""Three diagnostic readers reach actual teardown and the ordinary consumer."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support import runtime_observation_evidence as runtime
from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
from tests.unit.test_runtime_log_branch_evidence import log_inventory
from tests.unit.test_runtime_business_gateway import gateway,_env,_RuntimeControlDraftClient

URIS=tuple('ak.wwise.core.profiler.'+n for n in ('getCpuUsage','getPerformanceMonitor','getStreamedMedia'))
BUILDS={'2023.1':'2023.1.19.8928','2024.1':'2024.1.13.9056','2025.1':'2025.1.7.9143'}


def public_read(path,uri,version,console,rows,position):
    path.mkdir(parents=True);context=runtime.program_source_context(flow=uri)
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


@pytest.mark.parametrize('version,console',[pytest.param('2025.1',True,id='console-2025.1'),
    pytest.param('2023.1',True,id='console-2023.1'),pytest.param('2024.1',True,id='console-2024.1'),
    pytest.param('2023.1',False,id='authoring-2023.1'),pytest.param('2024.1',False,id='authoring-2024.1'),pytest.param('2025.1',False,id='authoring-2025.1')])
def test_extra_diagnostic_reads_public_teardown_portable_consumer(request,tmp_path,version,console):
    from tests.support.extra_runtime_read_evidence import original_call,write_bundle
    host='wwise-console'if console else'wwise-authoring';routes=[f'{version}|{host}|{BUILDS[version]}|function|{u}'for u in URIS]
    inventory=log_inventory(routes);assert len(inventory['native_coverage']['obligations'])==109
    captures=[]
    for i,(uri,route)in enumerate(zip(URIS,routes,strict=True)):
        actual=original_call(route+'|/resultSchema');row=deepcopy(actual['result']['return'][0]);empty=deepcopy(row)
        for k,v in empty.items():
            if isinstance(v,str):empty[k]=''
            elif isinstance(v,bool):empty[k]=False
        families=[(actual['result']['return'],actual['args']['time']),([empty],0),([row,row],1),([],2),([row],'capture-latest'),([row],'user-cursor')]
        for j,(rows,position)in enumerate(families):captures.append(public_read(tmp_path/f'{i}-{j}',uri,version,console,rows,position))
    def finalize(phases):
        paths=[]
        for i,(receipt,native,context,trace,calls)in enumerate(captures):
            path=tmp_path/f'capture-{i}.json';runtime.write_program_receipt(path,receipt,native,nodeid=request.node.nodeid,phase_reports=phases,
                source_context=context,native_reads=trace,public_calls=calls);paths.append(path)
        index=write_bundle(tmp_path/'bundle',paths,inventory=inventory)
        policies=json.loads((index.parent/'requirements.json').read_bytes());document,base,_=audit.portable_binding_inputs(index,policies)
        result=completion.evaluate_coverage(audit.ROOT,inventory,document,digest=audit.digest,evidence_base=base,requirements_document=policies)
        runtime.write_json(tmp_path/'consumer-result.json',result)
        assert {r['state']for r in result['obligations']}=={'verified'},[(r['pointer'],r['reasons'],r['evidence_results'])for r in result['obligations']if r['state']!='verified']
        if version=='2025.1'and console:
            from tests.support.extra_runtime_read_evidence import _capture
            sealed=json.loads(paths[0].read_bytes())
            for field in ('phase','host','retry','page','source'):
                bad=deepcopy(sealed)
                if field=='phase':bad['phase_reports']['teardown']='failed'
                elif field=='host':bad['native_reads'][0]['result']['isCommandLine']=False
                elif field=='retry':
                    bad['native_reads'].append({**deepcopy(bad['native_reads'][-1]),'ordinal':len(bad['native_reads'])})
                elif field=='page':bad['public_calls'][-1]['gateway']['payload']['agent_result']['page']['offset_from_end']=0
                else:bad['source_context']['packaged']['skills/waapi-skill/scripts/run.py']='0'*64
                with pytest.raises((ValueError,KeyError),match='.'):_capture(json.dumps(bad),audit.ROOT)
            for malformed in (None,0,'false'):
                bad=deepcopy(sealed)
                bad['gateway']['payload']['agent_result']['truncated']=malformed
                for call in bad['public_calls']:call['gateway']['payload']['agent_result']['truncated']=malformed
                with pytest.raises(ValueError,match='pages/spans/order'):_capture(json.dumps(bad),audit.ROOT)
            # Reseal an internally consistent public-payload corruption. The
            # ordinary consumer must still compare its whole array to transport.
            bad_document=deepcopy(document);root_id=routes[0]+'|/resultSchema'
            descriptor=bad_document['bindings'][root_id]['evidence']['program']
            record=completion.read_sealed_artifact(descriptor,base)
            record['gateway']['payload']['agent_result']['return'][0]['elementName']='changed-public-value'
            record['runtime_read_program']['gateway']=deepcopy(record['gateway'])
            record['runtime_read_program']['public_calls'][0]['gateway']=deepcopy(record['gateway'])
            replaced=runtime.write_json(base/'tampered-program.json',record)
            for binding in bad_document['bindings'].values():
                if binding['evidence']['program']==descriptor:binding['evidence']['program']={**replaced,'nodeid':descriptor['nodeid']}
            rejected=completion.evaluate_coverage(audit.ROOT,inventory,bad_document,digest=audit.digest,evidence_base=base,requirements_document=policies)
            assert all(r['state']!='verified'if r['route']==routes[0]else r['state']=='verified'for r in rejected['obligations'])
        for route in routes:
            missing=deepcopy(document);missing['bindings'][route+'|/resultSchema']['evidence'].pop('native')
            blocked=completion.evaluate_coverage(audit.ROOT,inventory,missing,digest=audit.digest,evidence_base=base,requirements_document=policies)
            assert all(r['state']!= 'verified'if r['route']==route else r['state']=='verified'for r in blocked['obligations'])
    register_exact_evidence_finalizer(request.node,finalize)
