"""Capture controls retain truthful ACKs through public execution and teardown."""
from copy import deepcopy
import json

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support import runtime_observation_evidence as runtime
from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
from tests.unit.test_runtime_business_gateway import _env, gateway, _RuntimeControlDraftClient
from tests.unit.test_runtime_cursor_branch_evidence import BUILDS
from tests.unit.test_runtime_log_branch_evidence import log_inventory

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
    client.call=call;context=runtime.program_source_context(flow=uri)
    def invoke(argv):
        start=len(trace);code,payload=gateway.execute_gateway(['--state-dir',str(path/'state'),*argv],env=_env(path,version=version),client_factory=lambda _:client)
        assert code==0,payload
        receipt={'argv':list(argv),'exit_code':code,'payload':payload}
        calls.append({'gateway':receipt,'native_start':start,'native_end':len(trace)})
        return payload
    if uri.endswith('.enableProfilerData'):
        from tests.support.runtime_capture_control_evidence import review
        names=review()['public_data_sets'][version];reverse={v:k for k,v in names.items()}
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
    from tests.support.runtime_capture_control_evidence import original_control,review,write_capture_control_bundle
    routes=[f'{version}|{host}|{BUILDS[version]}|function|{uri}'for host in ('wwise-console','wwise-authoring')for uri in sorted(URIS)]
    inventory=log_inventory(routes);captures=[]
    for host in ('wwise-console','wwise-authoring'):
        # Register the owned paired stop before starting; finally also runs on a
        # failed start assertion. This is fixture cleanup, not a stopped-state oracle.
        for uri in sorted(URIS):
            route=f'{version}|{host}|{BUILDS[version]}|function|{uri}';actual=original_control(route)
            captures.append(capture_control_flow(tmp_path/(host+'-'+uri.rsplit('.',1)[-1]+'-actual'),version,host,uri,actual['args'],actual['result']))
        enable=PREFIX+'enableProfilerData';names=review()['public_data_sets'][version]
        variants=[{'dataTypes':[]},{'dataTypes':[{'dataType':'voices','enable':True}]},
            {'dataTypes':[{'dataType':'voices','enable':True},{'dataType':'voices','enable':False}]},
            {'dataTypes':[{'dataType':value,'enable':True}for value in names.values()]}]
        captures.extend(capture_control_flow(tmp_path/(host+'-enable-'+str(i)),version,host,enable,args,{})for i,args in enumerate(variants))
        for suffix in ('startCapture','stopCapture'):
            captures.append(capture_control_flow(tmp_path/(host+'-'+suffix+'-absent'),version,host,PREFIX+suffix,{},{}))
    def finalize(phases):
        paths=[]
        for i,(receipt,native,context,trace,calls)in enumerate(captures):
            path=tmp_path/f'capture-{i}.json'
            runtime.write_program_receipt(path,receipt,native,nodeid=request.node.nodeid,phase_reports=phases,source_context=context,native_reads=trace,public_calls=calls)
            paths.append(path)
        index=write_capture_control_bundle(tmp_path/'bundle',paths,inventory=inventory,name_prefix='capture-control-'+version+'-')
        policies=json.loads((index.parent/'requirements.json').read_bytes());bindings,base,_=audit.portable_binding_inputs(index,policies)
        def evaluate(document):return completion.evaluate_coverage(audit.ROOT,inventory,document,digest=audit.digest,evidence_base=base,requirements_document=policies)
        result=evaluate(bindings);runtime.write_json(tmp_path/'consumer-result.json',result)
        assert {r['state']for r in result['obligations']}=={'verified'},[(r['pointer'],r['evidence_results'],r['reasons'])for r in result['obligations']if r['state']!='verified']
        for route in routes:
            missing=deepcopy(bindings);missing['bindings'][route+'|/resultSchema']['evidence'].pop('native')
            checked=evaluate(missing)
            assert all(r['state']!='verified'for r in checked['obligations']if r['route']==route)
            assert all(r['state']=='verified'for r in checked['obligations']if r['route']!=route)
        if version=='2025.1':
            identity=routes[0]+'|/argsSchema'
            for damage in ('directive','effect-claim','host','extra-native','duplicate-target','source','teardown','candidate'):
                changed=deepcopy(bindings);bound=changed['bindings'][identity]
                record=deepcopy(completion.read_sealed_artifact(bound['evidence']['program'],base));cap=record['runtime_read_program']
                if damage=='directive':
                    for native in (record['native_call'],cap['native_call'],next(x for x in cap['native_reads']if x['uri']==PREFIX+'enableProfilerData')):
                        native['args']['dataTypes'][0]['enable']=False
                    for receipt in (record['gateway'],cap['gateway'],cap['public_calls'][-1]['gateway']):
                        receipt['payload']['agent_result']['request']['arguments']['args']['dataTypes'][0]['enable']=False
                elif damage=='effect-claim':
                    for receipt in (record['gateway'],cap['gateway'],cap['public_calls'][-1]['gateway']):
                        receipt['payload']['verified']=True;receipt['payload']['verification']['business_state_verified']=True
                elif damage=='host':
                    for row in cap['native_reads']:
                        if row['uri']=='ak.wwise.core.getInfo':row['result']['isCommandLine']=False
                elif damage in {'extra-native','duplicate-target'}:
                    row=(deepcopy(next(x for x in cap['native_reads']if x['uri']==PREFIX+'enableProfilerData'))if damage=='duplicate-target'else
                         {'uri':'ak.wwise.core.log.clear','args':{'channel':'general'},'options':{},'result':{}})
                    row['ordinal']=len(cap['native_reads']);cap['native_reads'].append(row);cap['public_calls'][-1]['native_end']+=1
                elif damage=='source':cap['source_context']['capture']['tests/support/runtime_capture_control_evidence.py']='0'*64
                elif damage=='teardown':cap['phase_reports']['teardown']='failed'
                else:record['candidate_sha256']='0'*64
                bound['evidence']['program']={**runtime.write_json(base/('damage-'+damage+'.json'),record),'nodeid':request.node.nodeid}
                assert next(r for r in evaluate(changed)['obligations']if r['id']==identity)['state']!='verified',damage
            start=next(r for r in routes if r.startswith(version+'|wwise-console|')and r.endswith('.startCapture'))
            for damage in ('missing-paired-stop','malformed-time'):
                changed=deepcopy(bindings);bound=changed['bindings'][start+'|/argsSchema']
                record=deepcopy(completion.read_sealed_artifact(bound['evidence']['program'],base));cap=record['runtime_read_program']
                if damage=='missing-paired-stop':
                    cap['public_calls']=cap['public_calls'][:6];cap['native_reads']=cap['native_reads'][:cap['public_calls'][-1]['native_end']]
                else:
                    for native in (record['native_call'],cap['native_call'],next(x for x in cap['native_reads']if x['uri']==PREFIX+'startCapture')):native['result']={'return':True}
                    for receipt in (record['gateway'],cap['gateway'],cap['public_calls'][5]['gateway']):receipt['payload']['agent_result']['result']={'return':True}
                bound['evidence']['program']={**runtime.write_json(base/('damage-'+damage+'.json'),record),'nodeid':request.node.nodeid}
                assert next(r for r in evaluate(changed)['obligations']if r['id']==start+'|/argsSchema')['state']!='verified',damage
            normalized=routes[0]+'|/argsSchema/properties/dataTypes/items/properties/enable/@presence/absent'
            for invalid_default in (False,1):
                changed=deepcopy(bindings);changed['bindings'][normalized]['normalized_input_choice']['native_default']=invalid_default
                assert next(r for r in evaluate(changed)['obligations']if r['id']==normalized)['state']!='verified'
            source_index=json.loads(index.read_bytes());components=[]
            for host in ('wwise-console','wwise-authoring'):
                selected_entries=[];selected_attachments=[];selected_ids=set()
                for item in source_index['entries']:
                    owned=json.loads((base/item['bindings']['artifact']).read_bytes())['bindings']
                    if all(identity.split('|')[1]==host for identity in owned):
                        selected_entries.append(item);selected_ids.update(owned)
                for item in source_index['qualified_runtime_read_attachments']:
                    if completion.read_sealed_artifact(item,base)['branch_id']in selected_ids:selected_attachments.append(item)
                component=base/('component-'+host+'.json')
                runtime.write_json(component,{**source_index,'entries':selected_entries,'qualified_runtime_read_attachments':selected_attachments})
                components.append((component,{**policies,'branches':{k:v for k,v in policies['branches'].items()if k in selected_ids}}))
            combined,combined_policies=runtime.write_runtime_composition(tmp_path/'composed-hosts',components)
            combined_bindings,combined_base,_=audit.portable_binding_inputs(combined,combined_policies)
            combined_result=completion.evaluate_coverage(audit.ROOT,inventory,combined_bindings,digest=audit.digest,evidence_base=combined_base,requirements_document=combined_policies)
            assert {r['state']for r in combined_result['obligations']}=={'verified'}
            # Prefixes are closed before allocation; ordinary composition rejects
            # duplicate exact IDs instead of silently replacing an earlier packet.
            for bad in ('../escape-','capture-control-2024.1-','foreign-'):
                target=tmp_path/('bad-prefix-'+str(len(bad)))
                with pytest.raises(ValueError,match='prefix'):write_capture_control_bundle(target,paths,inventory=inventory,name_prefix=bad)
                assert not target.exists()
            with pytest.raises(ValueError,match='duplicates an exact branch'):
                runtime.write_runtime_composition(tmp_path/'duplicate-components',[(index,policies),(index,policies)])
            receipt,native,context,trace,calls=captures[0]
            with pytest.raises(ValueError,match='teardown'):
                runtime.write_program_receipt(tmp_path/'must-not-publish.json',receipt,native,nodeid=request.node.nodeid,
                    phase_reports={**phases,'teardown':'failed'},source_context=context,native_reads=trace,public_calls=calls)
            assert not(tmp_path/'must-not-publish.json').exists()
    register_exact_evidence_finalizer(request.node,finalize)
