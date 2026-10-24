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


@pytest.mark.parametrize('version',['2025.1','remaining'])
def test_meter_controls_public_pair_teardown_and_consumer(request,tmp_path,version):
    from tests.support.runtime_owned_control_evidence import original_meter,review,write_owned_control_bundle
    contexts=[('2025.1','wwise-authoring')]if version=='2025.1'else[('2025.1','wwise-console'),('2024.1','wwise-authoring'),('2024.1','wwise-console')]
    routes=[f'{v}|{host}|{BUILDS[v]}|function|{uri}'for v,host in contexts for uri in sorted(METER_URIS)]
    inventory=log_inventory(routes);captures=[]
    for v,host in contexts:
        row=review()['program_objects'][v]
        for selector in ('id','path','exact-type-name'):
            captures.extend(meter_pair(tmp_path/(v+'-'+host+'-'+selector),v,host,selector,row))
    def finalize(phases):
        paths=[]
        for i,(receipt,native,context,trace,calls)in enumerate(captures):
            path=tmp_path/f'capture-{i}.json'
            runtime.write_program_receipt(path,receipt,native,nodeid=request.node.nodeid,phase_reports=phases,source_context=context,native_reads=trace,public_calls=calls);paths.append(path)
        components=[]
        for v in sorted({c[0]for c in contexts}):
            selected_routes=[r for r in routes if r.startswith(v+'|')]
            selected_paths=[path for path in paths if json.loads(path.read_bytes())['gateway']['payload']['detected_version']==v]
            component=write_owned_control_bundle(tmp_path/('bundle-'+v),selected_paths,inventory=log_inventory(selected_routes),name_prefix='owned-controls-'+v+'-meter-')
            components.append((component,json.loads((component.parent/'requirements.json').read_bytes())))
        if len(components)==1:index,policies=components[0]
        else:index,policies=runtime.write_runtime_composition(tmp_path/'combined',components)
        bindings,base,_=audit.portable_binding_inputs(index,policies)
        def evaluate(document):return completion.evaluate_coverage(audit.ROOT,inventory,document,digest=audit.digest,evidence_base=base,requirements_document=policies)
        result=evaluate(bindings);runtime.write_json(tmp_path/'consumer-result.json',result)
        for row in result['obligations']:
            assert row['evidence_results']['program']['outcome']=='passed',(row['pointer'],row['evidence_results'])
            assert row['state']==('verified'if row['route']in review()['profiles']else'implemented_unverified'),row
        baseline={row['id']:row['state']for row in result['obligations']}
        for route in routes:
            if 'native'not in bindings['bindings'][route+'|/resultSchema']['evidence']:continue
            missing=deepcopy(bindings);missing['bindings'][route+'|/resultSchema']['evidence'].pop('native')
            checked=evaluate(missing)
            assert all(r['state']!='verified'for r in checked['obligations']if r['route']==route)
            assert all(r['state']==baseline[r['id']]for r in checked['obligations']if r['route']!=route)
        if version=='2025.1':
            identity=routes[0]+'|/argsSchema'
            for damage in ('native-guid','row-drift','handle','pair-cleanup','effect-upgrade','extra-native','source','teardown','candidate'):
                changed=deepcopy(bindings);bound=changed['bindings'][identity]
                record=deepcopy(completion.read_sealed_artifact(bound['evidence']['program'],base));cap=record['runtime_read_program']
                if damage=='native-guid':cap['native_call']['args']['object']='{FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF}'
                elif damage=='row-drift':next(x for x in cap['native_reads']if x['uri']=='ak.wwise.core.object.get')['result']['return'][0]['path']+=' changed'
                elif damage=='handle':cap['public_calls'][2]['gateway']['argv'][-1]='not-the-bound-handle'
                elif damage=='pair-cleanup':
                    cap['public_calls']=cap['public_calls'][:9];cap['native_reads']=cap['native_reads'][:cap['public_calls'][-1]['native_end']]
                elif damage=='effect-upgrade':cap['public_calls'][8]['gateway']['payload']['verification']['business_state_verified']=True
                elif damage=='extra-native':
                    cap['native_reads'].append({'ordinal':len(cap['native_reads']),'uri':PREFIX+'stopCapture','args':{},'options':{},'result':{}});cap['public_calls'][-1]['native_end']+=1
                elif damage=='source':cap['source_context']['capture']['tests/support/runtime_owned_control_evidence.py']='0'*64
                elif damage=='teardown':cap['phase_reports']['teardown']='failed'
                else:record['candidate_sha256']='0'*64
                bound['evidence']['program']={**runtime.write_json(base/('damaged-'+damage+'.json'),record),'nodeid':request.node.nodeid}
                assert next(r for r in evaluate(changed)['obligations']if r['id']==identity)['state']!='verified',damage
            normal=next(k for k,b in bindings['bindings'].items()if 'normalized_input_choice'in b)
            changed=deepcopy(bindings);changed['bindings'][normal]['normalized_input_choice']['native_alias_dispatch_claimed']=True
            assert next(r for r in evaluate(changed)['obligations']if r['id']==normal)['state']!='verified'
            for bad in ('../escape-','foreign-','owned-controls-2024.1-meter-'):
                out=tmp_path/('bad-'+str(len(bad)))
                with pytest.raises(ValueError,match='prefix'):write_owned_control_bundle(out,paths,inventory=inventory,name_prefix=bad)
                assert not out.exists()
            with pytest.raises(ValueError,match='duplicates an exact branch'):
                runtime.write_runtime_composition(tmp_path/'duplicate',[(index,policies),(index,policies)])
    register_exact_evidence_finalizer(request.node,finalize)


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
    client.call=call;context=runtime.program_source_context(flow=uri)
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
    from tests.support.runtime_owned_control_evidence import review,write_owned_control_bundle,write_file_boundary_capture
    contexts=[('2025.1','wwise-authoring')]if version=='2025.1'else[('2023.1','wwise-authoring'),('2023.1','wwise-console'),('2024.1','wwise-authoring'),('2024.1','wwise-console'),('2025.1','wwise-console')]
    routes=[f'{v}|{host}|{BUILDS[v]}|function|{PREFIX}saveCapture'for v,host in contexts];inventory=log_inventory(routes)
    captures=[save_capture_flow(tmp_path/(v+'-'+host),v,host)for v,host in contexts]
    def finalize(phases):
        paths=[];boundaries=[]
        for i,(receipt,native,context,trace,calls,rejections)in enumerate(captures):
            capture=tmp_path/f'capture-{i}.json';runtime.write_program_receipt(capture,receipt,native,nodeid=request.node.nodeid,phase_reports=phases,source_context=context,native_reads=trace,public_calls=calls);paths.append(capture)
            rejected=tmp_path/f'boundary-{i}.json';write_file_boundary_capture(rejected,rejections,capture,nodeid=request.node.nodeid,phase_reports=phases,source_context=context);boundaries.append(rejected)
        components=[]
        for v in sorted({c[0]for c in contexts}):
            indexes=[i for i,c in enumerate(contexts)if c[0]==v]
            component=write_owned_control_bundle(tmp_path/('bundle-'+v),[paths[i]for i in indexes],inventory=log_inventory([r for r in routes if r.startswith(v+'|')]),name_prefix='owned-controls-'+v+'-save-',file_boundaries=[boundaries[i]for i in indexes])
            components.append((component,json.loads((component.parent/'requirements.json').read_bytes())))
        if len(components)==1:index,policies=components[0]
        else:index,policies=runtime.write_runtime_composition(tmp_path/'combined',components)
        bindings,base,_=audit.portable_binding_inputs(index,policies)
        def evaluate(document):return completion.evaluate_coverage(audit.ROOT,inventory,document,digest=audit.digest,evidence_base=base,requirements_document=policies)
        result=evaluate(bindings);runtime.write_json(tmp_path/'consumer-result.json',result)
        for row in result['obligations']:
            assert row['evidence_results']['program']['outcome']=='passed',(row['pointer'],row['evidence_results'])
            assert row['state']==('verified'if row['route']in review()['profiles']else'implemented_unverified'),row
        baseline={row['id']:row['state']for row in result['obligations']}
        for route in routes:
            if 'native'not in bindings['bindings'][route+'|/resultSchema']['evidence']:continue
            missing=deepcopy(bindings);missing['bindings'][route+'|/resultSchema']['evidence'].pop('native')
            checked=evaluate(missing)
            assert all(r['state']!='verified'for r in checked['obligations']if r['route']==route)
            assert all(r['state']==baseline[r['id']]for r in checked['obligations']if r['route']!=route)
        if version=='2025.1':
            identity=routes[0]+'|/argsSchema/properties/file/@empty/string'
            for damage in ('field-borrow','flag-borrow','authority','dispatched','artifact','teardown','source','rejection-extra-0','rejection-extra-1'):
                changed=deepcopy(bindings);bound=changed['bindings'][identity]
                record=deepcopy(completion.read_sealed_artifact(bound['evidence']['program'],base));proof=record['file_destination_boundary']
                if damage=='field-borrow':proof['rejections'][0]['gateway']['payload']['details']['repair']['field']='capture_name'
                elif damage=='flag-borrow':proof['rejections'][0]['gateway']['argv'][-4]='--meter-object-handle'
                elif damage=='authority':proof['rejections'][0]['gateway']['argv'][3]='borrowed-authority'
                elif damage=='dispatched':proof['rejections'][1]['native_calls'].append(deepcopy(proof['valid']['native_call']))
                elif damage=='artifact':proof['valid']['public_calls'][-1]['gateway']['payload']['events'][-1]['details']['verification']['readbacks'][0]['nonempty']=False
                elif damage=='teardown':proof['phase_reports']['teardown']='failed'
                elif damage.startswith('rejection-extra-'):
                    i=int(damage[-1]);trace=proof['rejections'][i]['native_calls'];trace.append({'ordinal':trace[-1]['ordinal']+1,'uri':'ak.wwise.core.log.clear','args':{'channel':'General'},'options':{},'result':{}})
                    if i==0:record['native_calls']=deepcopy(trace)
                else:proof['valid']['source_context']['capture']['tests/support/runtime_owned_control_evidence.py']='0'*64
                bound['evidence']['program']={**runtime.write_json(base/('bad-boundary-'+damage+'.json'),record),'nodeid':request.node.nodeid}
                row=next(r for r in evaluate(changed)['obligations']if r['id']==identity)
                assert row['state']!='verified',damage
    register_exact_evidence_finalizer(request.node,finalize)


def test_file_boundary_is_exact_and_does_not_load_unrelated_scope(tmp_path):
    from tests.support.runtime_owned_control_evidence import review,SUPPORT_SHA
    boundary={'boundary':{'kind':'file_destination','support_sha256':SUPPORT_SHA,'native_field':'file'}}
    assert completion.approved_boundary(tmp_path,{'id':'unrelated'},boundary,{},None,audit.digest)is None
    identity=review()['save_boundary_ids'][0]
    branch={'id':identity,**review()['entries'][identity]}
    with pytest.raises((ValueError,OSError)):
        completion.approved_boundary(tmp_path,branch,boundary,{},None,audit.digest)


def cursor_control_flow(path,host,uri,choice,time_ms):
    import contextlib
    import io
    path.mkdir(parents=True);version='2025.1';client=_RuntimeControlDraftClient(path,version=version);original=client.call;trace=[];calls=[];rejection=None
    def call(api,args=None,options=None):
        value={'return':time_ms}if api in {uri,PREFIX+'getCursorTime'}else original(api,args,options)
        if api=='ak.wwise.core.getInfo':
            year,major,minor,build=map(int,BUILDS[version].split('.'));value['version'].update(year=year,major=major,minor=minor,build=build);value['isCommandLine']=host=='wwise-console'
        trace.append({'ordinal':len(trace),'uri':api,'args':deepcopy(args),'options':deepcopy(options),'result':deepcopy(value)});return value
    client.call=call;context=runtime.program_source_context(flow=uri)
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
    from tests.support.runtime_owned_control_evidence import review,write_owned_control_bundle
    from tests.support.empty_candidate_evidence import classify_empty_candidate,counterexample_source_context,write_counterexample_bundle
    uris=(PREFIX+'setCursorTime',PREFIX+'moveCursor');routes=[f'2025.1|{host}|{BUILDS["2025.1"]}|function|{u}'for u in uris];inventory=log_inventory(routes)
    counters=[b for b in inventory['native_coverage']['obligations']if b['id']in review()['cursor_counterexample_ids']]
    positive=deepcopy(inventory);positive['native_coverage']['obligations']=[b for b in positive['native_coverage']['obligations']if b not in counters]
    choices=[(uris[0],38549,38549),(uris[1],'first-frame',10133),(uris[1],'next-frame',10144),(uris[1],'last-frame',13600),(uris[1],'previous-frame',13589)]
    captures=[cursor_control_flow(tmp_path/str(i),host,u,choice,time)for i,(u,choice,time)in enumerate(choices)];counter_context=counterexample_source_context(audit.ROOT)
    def finalize(phases):
        paths=[]
        for i,(receipt,native,context,trace,calls,_)in enumerate(captures):
            path=tmp_path/f'capture-{i}.json';runtime.write_program_receipt(path,receipt,native,nodeid=request.node.nodeid,phase_reports=phases,source_context=context,native_reads=trace,public_calls=calls);paths.append(path)
        index=write_owned_control_bundle(tmp_path/'bundle',paths,inventory=positive,name_prefix='owned-controls-2025.1-cursor-');doc=json.loads(index.read_bytes());policies=json.loads((index.parent/'requirements.json').read_bytes())
        receipt,native,context,trace,calls,rejection=captures[1]
        for branch in counters:
            classification=classify_empty_candidate(audit.ROOT,branch)
            def phase(i):
                c=calls[i];return {'gateway':c['gateway'],'native_calls':trace[c['native_start']:c['native_end']]}
            dispatch='/counterexample/compiled/gateway/payload/agent_result/request/arguments';observation=dispatch+'/args/position';public_pointer='/gateway/argv/'+str(len(rejection['gateway']['argv'])-1)
            record={**rejection,'scope_kind':'product','counterexample':{'classification':classification,'valid':phase(1),'compiled':phase(3),'public_input_pointer':public_pointer},
                'branch_assertions':{branch['id']:{'native_route':branch['route'],'native_shape_sha256':branch['shape_sha256'],'checks':[{'pointer':public_pointer,'equals':''}]}}}
            public=next(x for x in inventory['routes']if x['id']=='2025.1|function|'+uris[1])
            from tests.support.runtime_owned_control_evidence import code_bindings
            binding={'branch_id':branch['id'],'native_shape_sha256':branch['shape_sha256'],'public_route':public['id'],'public_route_sha256':audit.digest(public),
                'disposition':'schema_counterexample','empty_candidate':classification,'input':{'gateway_argv':rejection['gateway']['argv'],'selector':observation},
                'dispatch_pointer':dispatch,'observation_pointer':observation,'reference_chain':[],**code_bindings(branch)}
            fragment=write_counterexample_bundle(index.parent,record,branch=branch,binding=binding,inventory=inventory,root=audit.ROOT,nodeid=request.node.nodeid,phase_reports=phases,source_context=counter_context)
            part=json.loads(fragment.read_bytes());doc['entries'].extend(part['entries']);policies['branches'].update(completion.read_sealed_artifact(part['entries'][0]['origin']['requirements'],index.parent)['branches'])
        runtime.write_json(index,doc);runtime.write_json(index.parent/'requirements.json',policies)
        bindings,base,_=audit.portable_binding_inputs(index,policies)
        def evaluate(document,requirements=policies):return completion.evaluate_coverage(audit.ROOT,inventory,document,digest=audit.digest,evidence_base=base,requirements_document=requirements)
        result=evaluate(bindings);runtime.write_json(tmp_path/'consumer-result.json',result)
        for row in result['obligations']:
            assert row['evidence_results']['program']['outcome']=='passed',(row['pointer'],row['evidence_results'])
            assert row['state']==('verified'if row['route']in review()['profiles']else'implemented_unverified'),row
        for route in routes:
            if 'native'not in bindings['bindings'][route+'|/resultSchema']['evidence']:continue
            missing=deepcopy(bindings);missing['bindings'][route+'|/resultSchema']['evidence'].pop('native')
            assert all(r['state']!='verified'for r in evaluate(missing)['obligations']if r['route']==route)
        if host=='wwise-authoring':
            identity=routes[0]+'|/resultSchema'
            for damage in ('getter-time','extra-native','public-choice','scope-upgrade','source','teardown'):
                changed=deepcopy(bindings);bound=changed['bindings'][identity];record=deepcopy(completion.read_sealed_artifact(bound['evidence']['program'],base));cap=record['runtime_read_program']
                if damage=='getter-time':next(x for x in cap['native_reads']if x['uri']==PREFIX+'getCursorTime')['result']['return']+=1
                elif damage=='extra-native':
                    cap['native_reads'].append({'ordinal':len(cap['native_reads']),'uri':PREFIX+'setCursorTime','args':{'time':38549},'options':{},'result':{'return':38549}});cap['public_calls'][-1]['native_end']+=1
                elif damage=='public-choice':cap['public_calls'][1]['gateway']['argv'][-1]='-5'
                elif damage=='scope-upgrade':cap['gateway']['payload']['verification']['verification_scope']['continuing_cursor_position_verified']=True
                elif damage=='source':cap['source_context']['capture']['tests/support/runtime_owned_control_evidence.py']='0'*64
                else:cap['phase_reports']['teardown']='failed'
                bound['evidence']['program']={**runtime.write_json(base/('bad-cursor-'+damage+'.json'),record),'nodeid':request.node.nodeid}
                assert next(r for r in evaluate(changed)['obligations']if r['id']==identity)['evidence_results']['program']['outcome']!='passed',damage
            identity=counters[0]['id']
            for damage in ('borrowed-flag','compiled-field','draft-authority','classification'):
                changed=deepcopy(bindings);bound=changed['bindings'][identity];record=deepcopy(completion.read_sealed_artifact(bound['evidence']['program'],base));proof=record['counterexample']
                if damage=='borrowed-flag':
                    for target in (record,proof['valid']):target['gateway']['argv'][-2]='--severity'
                    proof['valid']['gateway']['argv'][-1]='message'
                    record['gateway']['stderr']="gateway: error: argument --severity: invalid choice: '' (choose from 'message')\n"
                    bound['input']['gateway_argv']=deepcopy(record['gateway']['argv'])
                elif damage=='compiled-field':proof['compiled']['gateway']['payload']['agent_result']['request']['arguments']['args']['position']='last'
                elif damage=='draft-authority':proof['compiled']['gateway']['argv'][3]='borrowed-authority'
                else:proof['classification']['status']='accepted'
                bound['evidence']['program']={**runtime.write_json(base/('bad-cursor-counter-'+damage+'.json'),record),'nodeid':request.node.nodeid}
                assert next(r for r in evaluate(changed)['obligations']if r['id']==identity)['evidence_results']['program']['outcome']!='passed',damage
            policies_changed=deepcopy(policies);policies_changed['branches'][identity]['reason']='caller downgrade'
            assert next(r for r in evaluate(bindings,policies_changed)['obligations']if r['id']==identity)['state']!='verified'
    register_exact_evidence_finalizer(request.node,finalize)
