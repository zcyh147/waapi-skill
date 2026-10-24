"""Cursor meaning and exact retained availability through the ordinary consumer."""
from copy import deepcopy
import json

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support import runtime_observation_evidence as runtime
from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
from tests.unit.test_runtime_business_gateway import _env, gateway, FakeClient
from tests.unit.test_runtime_log_branch_evidence import log_inventory

URI = 'ak.wwise.core.profiler.getCursorTime'
BUILDS = {'2021.1':'2021.1.14.8108','2022.1':'2022.1.19.8584','2023.1':'2023.1.19.8928',
          '2024.1':'2024.1.13.9056','2025.1':'2025.1.7.9143'}


def test_cursor_capture_context_seals_public_inventory_and_policy_dependencies():
    names=runtime.program_source_context(flow=URI)['capture']
    assert {
        'tests/support/runtime_cursor_evidence.py',
        'tests/unit/test_runtime_cursor_branch_evidence.py',
        'tests/unit/test_runtime_log_branch_evidence.py',
        'tests/support/runtime_remaining_evidence.py',
        'tests/fixtures/runtime/runtime-remaining-policy-r127.json',
        'tests/support/fixed_runtime_read_evidence.py',
        'tests/fixtures/runtime-cursor/support-review.json',
    }<=names.keys()


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
    context=runtime.program_source_context(flow=URI)
    argv=['core-call',URI,'--profiler-cursor',choice]
    code,payload=gateway.execute_gateway(['--state-dir',str(path/'state'),*argv],env=_env(path,version=version),client_factory=lambda _:client)
    native,=[x for x in trace if x['uri']==URI]
    return {'argv':argv,'exit_code':code,'payload':payload}, {k:native[k]for k in ('uri','args','options','result')}, context, trace


@pytest.mark.parametrize('version',['2025.1','2021.1','2022.1','2023.1','2024.1'])
def test_cursor_paired_hosts_public_teardown_portable_consumer(request,tmp_path,version):
    from tests.support.runtime_cursor_evidence import original_cursor, write_cursor_bundle
    routes=[f'{version}|{host}|{BUILDS[version]}|function|{URI}'for host in ('wwise-console','wwise-authoring')]
    inventory=log_inventory(routes); captures=[]
    for host,route in zip(('wwise-console','wwise-authoring'),routes,strict=True):
        actual=original_cursor(route)
        values=[('capture-latest',actual['result']['return']),('user-cursor',0),('capture-latest',-1)]
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
    def finalize(phases):
        paths=[]
        for i,(receipt,native,context,trace)in enumerate(captures):
            path=tmp_path/f'capture-{i}.json'
            runtime.write_program_receipt(path,receipt,native,nodeid=request.node.nodeid,phase_reports=phases,source_context=context,
                native_reads=trace,public_calls=[{'gateway':receipt,'native_start':0,'native_end':len(trace)}])
            paths.append(path)
        index=write_cursor_bundle(tmp_path/'bundle',paths,inventory=inventory,name_prefix='cursor-'+version+'-')
        policies=json.loads((index.parent/'requirements.json').read_bytes())
        bindings,base,_=audit.portable_binding_inputs(index,policies)
        def evaluate(document):
            return completion.evaluate_coverage(audit.ROOT,inventory,document,digest=audit.digest,evidence_base=base,requirements_document=policies)
        result=evaluate(bindings); runtime.write_json(tmp_path/'consumer-result.json',result)
        assert {r['state']for r in result['obligations']}=={'verified'},[(r['pointer'],r['evidence_results'],r['reasons'])for r in result['obligations']if r['state']!='verified']
        for route in routes:
            missing=deepcopy(bindings);missing['bindings'][route+'|/resultSchema']['evidence'].pop('native')
            damaged=evaluate(missing)
            assert all(r['state']!='verified'for r in damaged['obligations']if r['route']==route)
            assert all(r['state']=='verified'for r in damaged['obligations']if r['route']!=route)
        if version=='2021.1':
            # Reuse this group's real packets for causal admission controls.
            identity=routes[0]+'|/argsSchema'
            for damage in ('mode','public-result','host','duplicate-read','source','teardown','candidate'):
                damaged=deepcopy(bindings);bound=damaged['bindings'][identity]
                record=deepcopy(completion.read_sealed_artifact(bound['evidence']['program'],base))
                cap=record['runtime_read_program']
                if damage=='mode':
                    record['native_call']['args']['cursor']='user'
                    cap['native_call']['args']['cursor']='user'
                    next(x for x in cap['native_reads']if x['uri']==URI)['args']['cursor']='user'
                elif damage=='public-result':
                    record['gateway']['payload']['agent_result']['position_ms']+=1
                    cap['gateway']['payload']['agent_result']['position_ms']+=1
                    cap['public_calls'][0]['gateway']=cap['gateway']
                elif damage=='host':
                    next(x for x in cap['native_reads']if x['uri']=='ak.wwise.core.getInfo')['result']['isCommandLine']=False
                elif damage=='duplicate-read':
                    extra=deepcopy(cap['native_reads'][-1]);extra['ordinal']=len(cap['native_reads'])
                    cap['native_reads'].append(extra);cap['public_calls'][0]['native_end']+=1
                elif damage=='source':cap['source_context']['capture']['tests/support/runtime_cursor_evidence.py']='0'*64
                elif damage=='teardown':cap['phase_reports']['teardown']='failed'
                else:record['candidate_sha256']='0'*64
                bound['evidence']['program']={**runtime.write_json(base/('damage-'+damage+'.json'),record),'nodeid':request.node.nodeid}
                rejected=evaluate(damaged)
                assert next(r for r in rejected['obligations']if r['id']==identity)['state']!='verified',damage
            anchor=routes[0]+'|/resultSchema'
            bound=bindings['bindings'][anchor]
            assessment=completion.read_sealed_artifact(bound['qualified_runtime_read_attachment'],base)
            archive=base/assessment['archive']['artifact'];raw=archive.read_bytes()
            try:
                archive.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
                rejected=evaluate(deepcopy(bindings))
                assert all(r['state']!='verified'for r in rejected['obligations']if r['route']==routes[0])
            finally:archive.write_bytes(raw)
            receipt,native,context,trace=captures[0]
            for phases,sources in (({'setup':'passed','call':'passed','teardown':'failed'},context),
                                   (dict.fromkeys(('setup','call','teardown'),'passed'),{})):
                with pytest.raises(ValueError):
                    runtime.write_program_receipt(tmp_path/'must-not-publish.json',receipt,native,nodeid=request.node.nodeid,
                        phase_reports=phases,source_context=sources,native_reads=trace)
                assert not (tmp_path/'must-not-publish.json').exists()
    register_exact_evidence_finalizer(request.node,finalize)


def test_cursor_public_capture_cannot_hide_an_unrelated_native_call(request,tmp_path):
    from tests.support.runtime_cursor_evidence import original_cursor,write_cursor_bundle
    route=f'2025.1|wwise-console|{BUILDS["2025.1"]}|function|{URI}'
    inventory=log_inventory(route,pointers={'/argsSchema','/resultSchema'})
    actual=original_cursor(route)
    receipt,native,context,trace=cursor_read(tmp_path/'public','2025.1','wwise-console','capture-latest',actual['result'])
    def finalize(phases):
        path=tmp_path/'capture.json'
        runtime.write_program_receipt(path,receipt,native,nodeid=request.node.nodeid,phase_reports=phases,source_context=context,
            native_reads=trace,public_calls=[{'gateway':receipt,'native_start':0,'native_end':len(trace)}])
        index=write_cursor_bundle(tmp_path/'bundle',[path],inventory=inventory)
        policies=json.loads((index.parent/'requirements.json').read_bytes());bindings,base,_=audit.portable_binding_inputs(index,policies)
        def evaluate(document):return completion.evaluate_coverage(audit.ROOT,inventory,document,digest=audit.digest,
            evidence_base=base,requirements_document=policies)
        assert {r['state']for r in evaluate(bindings)['obligations']}=={'verified'}
        identity=route+'|/argsSchema';bound=bindings['bindings'][identity]
        record=deepcopy(completion.read_sealed_artifact(bound['evidence']['program'],base));cap=record['runtime_read_program']
        cap['native_reads'].append({'ordinal':len(cap['native_reads']),'uri':'ak.wwise.core.log.clear','args':{'channel':'general'},'options':{},'result':{}})
        cap['public_calls'][0]['native_end']+=1
        bound['evidence']['program']={**runtime.write_json(base/'unrelated-call.json',record),'nodeid':request.node.nodeid}
        assert next(r for r in evaluate(bindings)['obligations']if r['id']==identity)['state']!='verified'
    register_exact_evidence_finalizer(request.node,finalize)


def test_cursor_version_prefixes_compose_without_rewriting_original_packets(request,tmp_path):
    from tests.support.runtime_cursor_evidence import original_cursor,write_cursor_bundle
    versions=('2021.1','2025.1');routes=[f'{v}|wwise-console|{BUILDS[v]}|function|{URI}'for v in versions]
    inventory=log_inventory(routes,pointers={'/argsSchema','/resultSchema'});captures=[]
    for version,route in zip(versions,routes,strict=True):
        original=original_cursor(route)
        captures.append(cursor_read(tmp_path/version,version,'wwise-console','capture-latest',original['result']))
    def finalize(phases):
        components=[];defaults=[]
        for number,(version,route,values)in enumerate(zip(versions,routes,captures,strict=True)):
            receipt,native,context,trace=values;capture=tmp_path/('capture-'+version+'.json')
            runtime.write_program_receipt(capture,receipt,native,nodeid=request.node.nodeid,phase_reports=phases,source_context=context,
                native_reads=trace,public_calls=[{'gateway':receipt,'native_start':0,'native_end':len(trace)}])
            selected=log_inventory(route,pointers={'/argsSchema','/resultSchema'})
            old=write_cursor_bundle(tmp_path/('default-'+version),[capture],inventory=selected)
            defaults.append((old,json.loads((old.parent/'requirements.json').read_bytes())))
            index=write_cursor_bundle(tmp_path/('named-'+version),[capture],inventory=selected,name_prefix='cursor-'+version+'-')
            components.append((index,json.loads((index.parent/'requirements.json').read_bytes())))
        # Historical defaults stay unchanged; their duplicate identities cannot
        # silently overwrite a different version's program or native packet.
        with pytest.raises(ValueError,match='duplicates an entry identity|common-base path collision'):
            runtime.write_runtime_composition(tmp_path/'default-collision',defaults)
        combined,policies=runtime.write_runtime_composition(tmp_path/'combined',components)
        bindings,base,_=audit.portable_binding_inputs(combined,policies)
        assert len(bindings['bindings'])==4
        result=completion.evaluate_coverage(audit.ROOT,inventory,bindings,digest=audit.digest,evidence_base=base,requirements_document=policies)
        runtime.write_json(tmp_path/'consumer-result.json',result)
        assert {r['state']for r in result['obligations']}=={'verified'}
        for version,route in zip(versions,routes,strict=True):
            original=original_cursor(route);name='cursor-'+version+'-wwise-console-original.json.gz'
            assert (base/name).read_bytes()==(audit.ROOT/original['profile']['archive_source']).read_bytes()
        with pytest.raises(ValueError,match='duplicates an exact branch'):
            runtime.write_runtime_composition(tmp_path/'duplicate',[*components,components[0]])
        for prefix in ('../escape-','foreign-','cursor-2024.1-'):
            target=tmp_path/('reject-'+str(len(prefix)))
            with pytest.raises(ValueError,match='prefix'):
                write_cursor_bundle(target,[tmp_path/'capture-2021.1.json'],
                    inventory=log_inventory(routes[0],pointers={'/argsSchema','/resultSchema'}),name_prefix=prefix)
            assert not target.exists()
    register_exact_evidence_finalizer(request.node,finalize)
