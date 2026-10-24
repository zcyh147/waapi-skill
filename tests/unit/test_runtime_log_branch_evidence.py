"""Runtime log evidence uses real public Gateway calls and actual pytest teardown."""
from copy import deepcopy
import gzip
import json

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support import runtime_observation_evidence as runtime
from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
from tests.unit.test_console_log_observer_gateway import ConsoleLogClient
from tests.unit.test_runtime_business_gateway import _env, gateway, _LogControlClient

GET = 'ak.wwise.core.log.get'
ROUTE = '2025.1|wwise-console|2025.1.7.9143|function|' + GET
ROW = {'severity':'Message','message':'WAAPI owned Console addition 2c3d53909345442d977fc2d79c1d3c3e',
       'time':1792821462,'messageId':''}


def log_inventory(route=ROUTE, pointers=None):
    stored = json.loads((audit.ROOT/'docs/branch-coverage-inventory.json').read_bytes())
    packed = json.loads(gzip.decompress((audit.ROOT/'docs/branch-coverage-inventory.native-obligations.json.gz').read_bytes()))
    route_ids={route}if isinstance(route,str)else set(route)
    native_routes=[r for r in stored['native_coverage']['routes']if r['id']in route_ids]
    assert {r['id']for r in native_routes}==route_ids
    obligations=[]
    for encoded in packed['rows']:
        if encoded.get('route')is None or packed['routes'][encoded['route']]not in route_ids:continue
        native_route=packed['routes'][encoded['route']]
        row=dict(encoded);row.update(packed['contexts'][row.pop('context')])
        row.update(route=native_route,id=native_route+'|'+row['pointer'],shape_sha256=packed['shapes'][row.pop('shape')])
        if pointers is None or row['pointer']in pointers:obligations.append(row)
    return {'routes':[r for r in stored['routes']if r['id']in {n['public_route']for n in native_routes}],
        'native_coverage':{'candidate_sha256':'f'*64,'catalogs':stored['native_coverage']['catalogs'],
            'routes':native_routes,'obligations':obligations}}



def public_log_read(path, rows, *, version='2025.1', console=True, channel='general'):
    path.mkdir(parents=True)
    context = runtime.program_source_context(flow=GET)
    client = _LogControlClient(path,version=version) if version in {'2021.1','2022.1'} else ConsoleLogClient(path,version=version)
    client.console=console; client.rows=deepcopy(rows)
    original, trace = client.call, []
    def call(uri,args=None,options=None):
        result = original(uri,args,options)
        if uri=='ak.wwise.core.getInfo':
            minor,build={'2021.1':(14,8108),'2022.1':(19,8584),'2023.1':(19,8928),'2024.1':(13,9056),'2025.1':(7,9143)}[version]
            result['version'].update(minor=minor,build=build)
        trace.append({'ordinal':len(trace),'uri':uri,'args':deepcopy(args),'options':deepcopy(options),'result':deepcopy(result)})
        return result
    client.call=call
    argv=['core-call',GET,'--log-channel',channel,'--max-results','1000']
    code,payload=gateway.execute_gateway(['--state-dir',str(path/'state'),*argv],
        env=_env(path,version=version),client_factory=lambda _:client)
    assert code==0,payload
    first={'argv':argv,'exit_code':code,'payload':payload}
    pages=[first]; reconstructed=[]; fragments=[]
    while True:
        result=payload['agent_result']
        reconstructed.extend(result['items'])
        if 'row_fragment'in result:
            fragment=result['row_fragment'];fragments.append(fragment['value'])
            if fragment['offset_characters']+len(fragment['value'])==fragment['total_characters']:
                reconstructed.append(json.loads(''.join(fragments)));fragments=[]
        if result.get('complete',True):break
        page_argv=result['next_command']['full_argv'][3:]
        code,payload=gateway.execute_gateway(page_argv,env=_env(path,version=version),
            client_factory=lambda _:pytest.fail('Retained log page connected'))
        assert code==0,payload
        pages.append({'argv':page_argv,'exit_code':code,'payload':payload})
        assert len(pages)<=128
    assert reconstructed==rows and not fragments
    first['public_pages']=pages[1:]
    native,=[row for row in trace if row['uri']==GET]
    return first, {k:native[k] for k in ('uri','args','options','result')},context,trace


def test_console_log_public_teardown_portable_native_gate(request,tmp_path):
    inventory=log_inventory(pointers={'/argsSchema','/optionsSchema','/resultSchema',
        '/resultSchema/properties/items','/resultSchema/properties/items/@cardinality/single'})
    assert len(inventory['native_coverage']['obligations'])==5
    receipt,native,context,trace=public_log_read(tmp_path/'public',[ROW])
    def finalize(phases):
        from tests.support.runtime_remaining_evidence import write_log_bundle
        capture=tmp_path/'capture.json'
        pages=receipt.pop('public_pages')
        runtime.write_program_receipt(capture,receipt,native,nodeid=request.node.nodeid,
            phase_reports=phases,source_context=context,native_reads=trace,
            public_calls=[{'gateway':receipt,'native_start':0,'native_end':len(trace)},
                *[{'gateway':page,'native_start':len(trace),'native_end':len(trace)}for page in pages]])
        index=write_log_bundle(tmp_path/'bundle',[capture],inventory=inventory)
        policies=json.loads((index.parent/'requirements.json').read_bytes())
        document,base,_=audit.portable_binding_inputs(index,policies)
        def evaluate(bindings):
            return completion.evaluate_coverage(audit.ROOT,inventory,bindings,digest=audit.digest,
                evidence_base=base,requirements_document=policies)
        result=evaluate(document)
        runtime.write_json(tmp_path/'consumer-result.json',result)
        assert {r['state'] for r in result['obligations']}=={'verified'}, [(r['pointer'],r['evidence_results'],r['reasons'])for r in result['obligations']]
        damaged=deepcopy(document)
        anchor=ROUTE+'|/resultSchema'
        damaged['bindings'][anchor]['evidence'].pop('native')
        missing=evaluate(damaged)
        assert all(r['state']!='verified' for r in missing['obligations'])
    register_exact_evidence_finalizer(request.node,finalize)


def test_remaining_policy_is_exact_and_history_is_immutable():
    from tests.support.runtime_remaining_evidence import review, policy
    reviewed=review(); packed=json.loads(gzip.decompress((audit.ROOT/'docs/branch-coverage-inventory.native-obligations.json.gz').read_bytes()))
    original={}
    for encoded in packed['rows']:
        if encoded.get('route') is None:continue
        route=packed['routes'][encoded['route']];identity=route+'|'+encoded['pointer']
        if identity in reviewed['entries']:
            original[identity]={**encoded,**packed['contexts'][encoded['context']],
                'route':route,'native_shape_sha256':packed['shapes'][encoded['shape']]}
    assert len(original)==10977 and len({r['route']for r in original.values()})==169
    from tests.support.runtime_remaining_evidence import owned_route
    expected_routes={r['route']for r in original.values()}
    builds={'2021.1':'2021.1.14.8108','2022.1':'2022.1.19.8584','2023.1':'2023.1.19.8928','2024.1':'2024.1.13.9056','2025.1':'2025.1.7.9143'}
    candidates={f'{v}|{host}|{build}|function|{uri}'for v,build in builds.items()for host in ('wwise-console','wwise-authoring')for uri in {r.split('|')[-1]for r in expected_routes}}
    assert {route for route in candidates if owned_route(route)}==expected_routes
    assert sum(e['categories']==['program','native']for e in reviewed['entries'].values())==169
    assert len(reviewed['normalized_input_choices'])==24
    assert {r['public_form']for r in reviewed['normalized_input_choices'].values()}=={'omitted','explicit-default'}
    assert sum(not e['pointer'].startswith('/resultSchema')for e in reviewed['entries'].values())==3003
    assert {p for p in original}==set(reviewed['entries'])
    published=json.loads((audit.ROOT/'docs/branch-coverage-requirements.json').read_bytes())['branches']
    assert not set(original)&set(published)
    for identity,entry in reviewed['entries'].items():
        assert all(entry[k]==original[identity][k]for k in ('route','pointer','kind','native_shape_sha256','owner_issue','parent_issue','blocks_issue'))
        anchors=entry['required_native_anchor_ids']
        assert anchors==([]if entry['pointer']=='/resultSchema'else[entry['route']+'|/resultSchema'])
        assert policy(entry)['categories']==entry['categories']
    from tests.support.runtime_remaining_evidence import counterexample_policy,preservation_gates
    selected=[{**row,'id':identity,'shape_sha256':row['native_shape_sha256']}for identity,row in original.items()]
    counters=set(reviewed['schema_counterexample_ids'])
    assert len(counters)==4 and counters=={identity for identity in original if identity.endswith('/logCentralSeverity/@empty/string')}
    policies={identity:policy(entry)for identity,entry in reviewed['entries'].items()}
    for branch in selected:
        if branch['id']in counters:policies[branch['id']]=counterexample_policy(branch)
    gates=preservation_gates(audit.ROOT,policies,selected)
    assert set(gates)==set(original)
    assert all(gates[identity]==entry['required_native_anchor_ids']for identity,entry in reviewed['entries'].items())
    counter=next(b for b in selected if b['id']in counters)
    wrong=deepcopy(policies);wrong[counter['id']]['reason']='caller downgrade'
    assert preservation_gates(audit.ROOT,wrong,[counter])[counter['id']] is None
    stale={**counter,'shape_sha256':'0'*64}
    with pytest.raises(ValueError,match='exact remaining'):
        preservation_gates(audit.ROOT,policies,[stale])
    unrelated={'id':'unrelated', 'route':'unrelated'}
    assert preservation_gates(audit.ROOT,{'unrelated':{'categories':['program']}},[unrelated])=={}


def native_log_rows(version):
    """Finite external data from the independent pinned native schemas, not Gateway logic.

    Zip alternatives rather than multiply combinations. The public assertion is
    whole-value preservation; malformed/limit controls exercise actual failures.
    """
    import re
    from itertools import cycle
    catalog=json.loads((audit.ROOT/f'skills/waapi-skill/resources/native-catalog/{version}/wwise-authoring.json').read_bytes())
    documents=catalog['definitions']['documents']
    guid='{11111111-1111-1111-1111-111111111111}'
    def variants(node,seen=()):
        if node is True:return ['Evidence']
        if node is False:return []
        if '$ref'in node:
            name,pointer=node['$ref'].split('#');key=(name or 'waapi_definitions.json',pointer)
            if key in seen:return [{}]
            target=completion.pointer_value(documents[key[0]],pointer)
            return variants({**target,**{k:v for k,v in node.items()if k!='$ref'}},(*seen,key))
        if 'enum'in node:return deepcopy(node['enum'])
        union=next((key for key in ('oneOf','anyOf','OneOf')if key in node),None)
        if union:return [v for arm in node[union]for v in variants(arm,seen)]
        kind=node.get('type')
        if kind=='object':
            properties=node.get('properties',{});required=node.get('required',[])
            values={k:variants(v,seen)for k,v in properties.items()if v is not False}
            for pattern,child in node.get('patternProperties',{}).items():
                key=next(k for k in ['@Evidence','@@Evidence','Evidence','OutputBus','Evidence/Λ']if re.search(pattern,k))
                values[key]=variants(child,seen)
            count=max((len(v)for v in values.values()),default=1)
            rich=[{k:deepcopy(v[i%len(v)])for k,v in values.items()if v}for i in range(count)]
            minimal={k:deepcopy(values[k][0])for k in required}
            return [minimal,*rich]
        if kind=='array':
            members=variants(node.get('items',{}),seen)
            return ([[]]if node.get('minItems',0)==0 else[])+[[deepcopy(v)]for v in members]+([deepcopy(members[:2])]if members else[])
        if kind=='boolean':return [False,True]
        if kind=='null':return [None]
        if kind in {'integer','number'}:
            return list(dict.fromkeys([node.get('minimum',0),node.get('maximum',1)]))
        if kind=='string':
            candidates=['Evidence','',guid,r'\Master-Mixer Hierarchy\Default Work Unit\Evidence']
            return [v for v in candidates if len(v)>=node.get('minLength',0)and('pattern'not in node or re.search(node['pattern'],v))]
        return [{}]
    schema=catalog['schemas'][GET]['resultSchema']['properties']['items']['items']
    values=variants(schema)
    distinct={json.dumps(value,sort_keys=True):value for value in values}
    return list(distinct.values())


@pytest.mark.parametrize('version',['2021.1','2022.1','2023.1','2024.1','2025.1'])
@pytest.mark.parametrize('console',[True,False],ids=['console','authoring'])
def test_log_get_versioned_public_result_branches(request,tmp_path,version,console):
    builds={'2021.1':'2021.1.14.8108','2022.1':'2022.1.19.8584','2023.1':'2023.1.19.8928','2024.1':'2024.1.13.9056','2025.1':'2025.1.7.9143'}
    route=f"{version}|{'wwise-console'if console else'wwise-authoring'}|{builds[version]}|function|{GET}"
    inventory=log_inventory(route)
    # Four whole-roster source contradictions retain their IDs/policies. A legal
    # positive result cannot satisfy the 2025 severity empty synthetic branch.
    contradictions=[b for b in inventory['native_coverage']['obligations']
        if b['pointer']=='/resultSchema/@definition/waapi_definitions.json/definitions/logCentralSeverity/@empty/string']
    assert len(contradictions)==(1 if version=='2025.1'else 0)
    inventory['native_coverage']['obligations']=[b for b in inventory['native_coverage']['obligations']if b not in contradictions]
    rows=native_log_rows(version)
    assert rows
    from tests.support.runtime_log_retained_evidence import program_native_call
    actual_rows=[ROW]if console and version=='2025.1'else program_native_call(route+'|/resultSchema')['result']['items']
    captures=[public_log_read(tmp_path/'actual-replay',actual_rows,version=version,console=console),
        *[public_log_read(tmp_path/str(i),[row],version=version,console=console)for i,row in enumerate(rows)]]
    channels=['soundbank-generation','audio-conversion','platform-settings-copy','waapi','project-load']
    if version in {'2023.1','2024.1','2025.1'}:channels+=['source-control','lua']
    captures.extend(public_log_read(tmp_path/('channel-'+channel),[ROW],version=version,console=console,channel=channel)for channel in channels)
    captures.append(public_log_read(tmp_path/'empty',[],version=version,console=console))
    captures.append(public_log_read(tmp_path/'multiple',[ROW,ROW],version=version,console=console))
    def finalize(phases):
        from tests.support.runtime_remaining_evidence import write_log_bundle
        paths=[]
        for i,(receipt,native,context,trace)in enumerate(captures):
            path=tmp_path/f'capture-{i}.json'
            pages=receipt.pop('public_pages')
            runtime.write_program_receipt(path,receipt,native,nodeid=request.node.nodeid,phase_reports=phases,
                source_context=context,native_reads=trace,public_calls=[{'gateway':receipt,'native_start':0,'native_end':len(trace)},
                    *[{'gateway':page,'native_start':len(trace),'native_end':len(trace)}for page in pages]])
            paths.append(path)
        index=write_log_bundle(tmp_path/'bundle',paths,inventory=inventory)
        policies=json.loads((index.parent/'requirements.json').read_bytes())
        bindings,base,_=audit.portable_binding_inputs(index,policies)
        result=completion.evaluate_coverage(audit.ROOT,inventory,bindings,digest=audit.digest,evidence_base=base,requirements_document=policies)
        runtime.write_json(tmp_path/'consumer-result.json',result)
        assert {r['state']for r in result['obligations']}=={'verified'},[(r['pointer'],r['evidence_results'])for r in result['obligations']if r['state']!='verified']
        damaged=deepcopy(bindings)
        damaged['bindings'][route+'|/resultSchema']['evidence'].pop('native',None)
        missing=completion.evaluate_coverage(audit.ROOT,inventory,damaged,digest=audit.digest,evidence_base=base,requirements_document=policies)
        assert all(r['state']!='verified'for r in missing['obligations'])
    register_exact_evidence_finalizer(request.node,finalize)


def public_log_control(path,uri,*,version='2025.1',console=False,channel='general',severity='message',message='owned log control'):
    path.mkdir(parents=True)
    client=ConsoleLogClient(path,version=version)if console else _LogControlClient(path,version=version)
    client.console=console;client.rows=[deepcopy(ROW)]
    context=runtime.program_source_context(flow=uri);trace=[];calls=[];original=client.call
    def call(api,args=None,options=None):
        result=original(api,args,options)
        if api=='ak.wwise.core.getInfo':
            minor,build={'2023.1':(19,8928),'2024.1':(13,9056),'2025.1':(7,9143)}[version]
            result['version'].update(minor=minor,build=build)
        trace.append({'ordinal':len(trace),'uri':api,'args':deepcopy(args),'options':deepcopy(options),'result':deepcopy(result)})
        return result
    client.call=call
    def invoke(argv):
        start=len(trace)
        code,payload=gateway.execute_gateway(['--state-dir',str(path/'state'),*argv],env=_env(path,version=version),client_factory=lambda _:client)
        assert code==0,payload
        receipt={'argv':list(argv),'exit_code':code,'payload':payload}
        calls.append({'gateway':receipt,'native_start':start,'native_end':len(trace)})
        return payload
    started=invoke(['draft-start',uri]);draft=started['draft']['draft_id'];authority=started['task_authority']
    declaration=['--log-channel',channel]if channel is not None else[]
    if uri.endswith('.addItem'):
        declaration+=['--message',message]
        if severity is not None:declaration+=['--severity',severity]
    current=invoke(['draft-declare-runtime-control-plan',draft,'--task-authority',authority,'--expected-revision',str(started['draft']['revision']),*declaration])
    current=invoke(['draft-check',draft,'--task-authority',authority,'--expected-revision',str(current['draft']['revision'])])
    preview=invoke(['preview-from-draft',draft,'--task-authority',authority,'--expected-revision',str(current['draft']['revision'])])
    shown=invoke(preview['next_command']['gateway_argv']);invoke(shown['next_command']['gateway_argv'])
    executed=invoke(['execute',preview['transaction_id']]);verified=invoke(executed['next_command']['gateway_argv'])
    native,=[x for x in trace if x['uri']==uri]
    assert verified['agent_result']['request']['arguments']=={'api':uri,'args':native['args'],'options':native['options']}
    assert verified['agent_result']['result']==native['result']
    assert verified['verified']is (not console or version=='2025.1'),verified
    return calls[-1]['gateway'],{k:native[k]for k in ('uri','args','options','result')},context,trace,calls


@pytest.mark.parametrize('operation',['addItem','clear'])
@pytest.mark.parametrize('console',[False,True],ids=['authoring','console'])
def test_log_control_public_transaction_evidence(request,tmp_path,operation,console):
    uri='ak.wwise.core.log.'+operation
    route='2025.1|'+('wwise-console'if console else'wwise-authoring')+'|2025.1.7.9143|function|'+uri
    pointers={'/argsSchema','/optionsSchema','/resultSchema'}
    if operation=='addItem':pointers|={'/argsSchema/properties/channel/@presence/absent','/argsSchema/properties/severity/@presence/absent'}
    inventory=log_inventory(route,pointers=pointers)
    receipt,native,context,trace,calls=public_log_control(tmp_path/'public',uri,console=console,message=ROW['message'],
        channel=None if operation=='addItem'else'general',severity=None)
    def finalize(phases):
        from tests.support.runtime_remaining_evidence import write_log_bundle
        path=tmp_path/'capture.json'
        runtime.write_program_receipt(path,receipt,native,nodeid=request.node.nodeid,phase_reports=phases,
            source_context=context,native_reads=trace,public_calls=calls)
        index=write_log_bundle(tmp_path/'bundle',[path],inventory=inventory)
        if console:
            policies=json.loads((index.parent/'requirements.json').read_bytes())
            bindings,base,_=audit.portable_binding_inputs(index,policies)
            result=completion.evaluate_coverage(audit.ROOT,inventory,bindings,digest=audit.digest,evidence_base=base,requirements_document=policies)
            assert {r['state']for r in result['obligations']}=={'verified'},[(r['pointer'],r['reasons'])for r in result['obligations']]
            damaged=deepcopy(bindings);damaged['bindings'][route+'|/resultSchema']['evidence'].pop('native')
            rejected=completion.evaluate_coverage(audit.ROOT,inventory,damaged,digest=audit.digest,evidence_base=base,requirements_document=policies)
            assert all(r['state']!='verified'for r in rejected['obligations'])
    register_exact_evidence_finalizer(request.node,finalize)


def test_retained_authoring_log_gate_through_ordinary_consumer(request,tmp_path):
    from tests.support.runtime_log_retained_evidence import program_native_call
    route='2023.1|wwise-authoring|2023.1.19.8928|function|'+GET
    inventory=log_inventory(route,pointers={'/argsSchema','/optionsSchema','/resultSchema'})
    original=program_native_call(route+'|/resultSchema')
    receipt,native,context,trace=public_log_read(tmp_path/'public',original['result']['items'],version='2023.1',console=False)
    assert native==original
    def finalize(phases):
        from tests.support.runtime_remaining_evidence import write_log_bundle
        path=tmp_path/'capture.json';pages=receipt.pop('public_pages')
        runtime.write_program_receipt(path,receipt,native,nodeid=request.node.nodeid,phase_reports=phases,source_context=context,native_reads=trace,
            public_calls=[{'gateway':receipt,'native_start':0,'native_end':len(trace)},*[{'gateway':p,'native_start':len(trace),'native_end':len(trace)}for p in pages]])
        index=write_log_bundle(tmp_path/'bundle',[path],inventory=inventory);policies=json.loads((index.parent/'requirements.json').read_bytes())
        bindings,base,_=audit.portable_binding_inputs(index,policies)
        result=completion.evaluate_coverage(audit.ROOT,inventory,bindings,digest=audit.digest,evidence_base=base,requirements_document=policies)
        runtime.write_json(tmp_path/'consumer-result.json',result)
        assert {r['state']for r in result['obligations']}=={'verified'},[(r['pointer'],r['evidence_results'])for r in result['obligations']]
    register_exact_evidence_finalizer(request.node,finalize)


@pytest.mark.parametrize('version,console',[
    pytest.param(v,c,id=('console-'if c else'authoring-')+v)
    for c in (True,False)for v in ('2021.1','2022.1','2023.1','2024.1','2025.1')if not(c and v=='2025.1')])
def test_retained_log_gate_relationships_by_version(request,tmp_path,version,console):
    from tests.support import runtime_log_retained_evidence as retained
    host='wwise-console'if console else'wwise-authoring'
    profiles={identity:p for identity,p in retained.review()['profiles'].items()
        if p['target_route'].split('|')[:2]==[version,host]}
    assert profiles  # Original R122 has separate actual public causal tests.
    inventory=log_inventory([p['target_route']for p in profiles.values()],pointers={'/argsSchema','/optionsSchema','/resultSchema'})
    captures=[]
    for i,identity in enumerate(profiles):
        actual=retained.program_native_call(identity);uri=actual['uri']
        if uri==GET:
            receipt,native,context,trace=public_log_read(tmp_path/str(i),actual['result']['items'],version=version,console=console)
            pages=receipt.pop('public_pages');calls=[{'gateway':receipt,'native_start':0,'native_end':len(trace)},
                *[{'gateway':p,'native_start':len(trace),'native_end':len(trace)}for p in pages]]
        else:
            receipt,native,context,trace,calls=public_log_control(tmp_path/str(i),uri,version=version,console=console,
                message=actual['args'].get('message','unused'))
        assert native==actual
        captures.append((receipt,native,context,trace,calls))
    def finalize(phases):
        from tests.support.runtime_remaining_evidence import write_log_bundle
        paths=[]
        for i,(receipt,native,context,trace,calls)in enumerate(captures):
            path=tmp_path/f'capture-{i}.json';runtime.write_program_receipt(path,receipt,native,nodeid=request.node.nodeid,phase_reports=phases,
                source_context=context,native_reads=trace,public_calls=calls);paths.append(path)
        index=write_log_bundle(tmp_path/'bundle',paths,inventory=inventory);policies=json.loads((index.parent/'requirements.json').read_bytes())
        bindings,base,_=audit.portable_binding_inputs(index,policies)
        result=completion.evaluate_coverage(audit.ROOT,inventory,bindings,digest=audit.digest,evidence_base=base,requirements_document=policies)
        runtime.write_json(tmp_path/'consumer-result.json',result)
        assert {r['state']for r in result['obligations']}=={'verified'},[(r['pointer'],r['evidence_results'])for r in result['obligations']]
        for identity in profiles:
            damaged=deepcopy(bindings);damaged['bindings'][identity]['evidence'].pop('native')
            missing=completion.evaluate_coverage(audit.ROOT,inventory,damaged,digest=audit.digest,evidence_base=base,requirements_document=policies)
            assert all(r['state']!='verified'for r in missing['obligations']if r['route']==identity.rsplit('|',1)[0])
    register_exact_evidence_finalizer(request.node,finalize)


@pytest.mark.parametrize('version',['2023.1','2024.1','2025.1'])
@pytest.mark.parametrize('console',[True,False],ids=['console','authoring'])
@pytest.mark.parametrize('operation',['addItem','clear'])
def test_log_control_all_public_input_branches(request,tmp_path,version,console,operation):
    from tests.support import runtime_log_retained_evidence as retained
    uri='ak.wwise.core.log.'+operation
    build={'2023.1':'2023.1.19.8928','2024.1':'2024.1.13.9056','2025.1':'2025.1.7.9143'}[version]
    route=f"{version}|{'wwise-console'if console else'wwise-authoring'}|{build}|function|{uri}"
    inventory=log_inventory(route)
    invalid=[b for b in inventory['native_coverage']['obligations']if b['pointer'].endswith('/logCentralSeverity/@empty/string')]
    assert len(invalid)==(1 if version=='2025.1'and operation=='addItem'else 0)
    inventory['native_coverage']['obligations']=[b for b in inventory['native_coverage']['obligations']if b not in invalid]
    identity=route+'|/resultSchema'
    if console and version=='2025.1':message=ROW['message']
    elif identity in retained.review()['profiles']:
        message=retained.program_native_call(identity)['args'].get('message','unused')
    else:
        assert console and operation=='clear'and version in {'2023.1','2024.1'}
        message='unused'  # Unimplemented native providers remain blocking.
    captures=[public_log_control(tmp_path/'actual-replay',uri,version=version,console=console,message=message,
        channel=None if operation=='addItem'else'general',severity=None)]
    channels=['general','soundbank-generation','audio-conversion','platform-settings-copy','waapi','project-load','source-control','lua']
    severities=['message','warning','error','fatal']
    captures.extend(public_log_control(tmp_path/str(i),uri,version=version,console=console,channel=channel,
        severity=severities[i%4],message='输入 '+channel+'\n$HOME')for i,channel in enumerate(channels))
    if operation=='addItem':
        captures.append(public_log_control(tmp_path/'empty-message',uri,version=version,console=console,message=''))
        captures.append(public_log_control(tmp_path/'exact-whitespace',uri,version=version,console=console,message=' \tLog\n '))
    assert len(captures)<12
    def finalize(phases):
        from tests.support.runtime_remaining_evidence import write_log_bundle
        paths=[]
        for i,(receipt,native,context,trace,calls)in enumerate(captures):
            path=tmp_path/f'capture-{i}.json';runtime.write_program_receipt(path,receipt,native,nodeid=request.node.nodeid,phase_reports=phases,
                source_context=context,native_reads=trace,public_calls=calls);paths.append(path)
        index=write_log_bundle(tmp_path/'bundle',paths,inventory=inventory);policies=json.loads((index.parent/'requirements.json').read_bytes())
        bindings,base,_=audit.portable_binding_inputs(index,policies)
        result=completion.evaluate_coverage(audit.ROOT,inventory,bindings,digest=audit.digest,evidence_base=base,requirements_document=policies)
        runtime.write_json(tmp_path/'consumer-result.json',result)
        assert {r['state']for r in result['obligations']}=={'verified'},[(r['pointer'],r['evidence_results'])for r in result['obligations']]
        if console and version!='2025.1'and operation=='clear':
            missing_bindings=deepcopy(bindings)
            for bound in missing_bindings['bindings'].values():bound['evidence'].pop('native',None)
            missing=completion.evaluate_coverage(audit.ROOT,inventory,missing_bindings,digest=audit.digest,evidence_base=base,requirements_document=policies)
            assert all(r['state']!='verified'for r in missing['obligations'])
    register_exact_evidence_finalizer(request.node,finalize)


def test_clear_requires_explicit_public_channel_even_native_default_known(tmp_path):
    env=_env(tmp_path)
    client=_LogControlClient(tmp_path)
    def offline(_):return client
    code,started=gateway.execute_gateway(['--state-dir',str(tmp_path/'state'),'draft-start','ak.wwise.core.log.clear'],env=env,client_factory=offline)
    assert code==0,started
    code,rejected=gateway.execute_gateway(['--state-dir',str(tmp_path/'state'),'draft-declare-runtime-control-plan',started['draft']['draft_id'],
        '--task-authority',started['task_authority'],'--expected-revision',str(started['draft']['revision'])],env=env,client_factory=offline)
    assert code==2,rejected
    assert rejected['ok']is False
    assert 'log_channel'in json.dumps(rejected)
    assert not any(uri=='ak.wwise.core.log.clear'for uri,_,_ in client.calls)


def test_log_nested_open_objects_preserve_every_opaque_value(request,tmp_path):
    inventory=log_inventory()
    branches=[b for b in inventory['native_coverage']['obligations']if b['pointer']=='/resultSchema'or
        b['pointer'].endswith(('/objectReturn/additionalProperties','/anyOf/6/additionalProperties','/anyOf/7/items/additionalProperties'))or
        b['pointer']in {'/resultSchema/properties/items/items/$ref','/resultSchema/@definition/waapi_definitions.json/definitions/logCentralItem/properties/platform/$ref'}]
    assert len(branches)==6
    inventory['native_coverage']['obligations']=branches
    opaque={'/key~':'值','array':[None,False,True,3.5,{'deep':['opaque']}],'empty':{}}
    reference={'id':'{11111111-1111-1111-1111-111111111111}','name':'reference','/opaque~field':opaque}
    platform={'id':'{22222222-2222-2222-2222-222222222222}','name':'platform',
        '@Evidence':deepcopy(reference),'@@EvidenceList':[deepcopy(reference)],'/opaque~field':deepcopy(opaque)}
    row={**ROW,'platform':platform}
    captures=[public_log_read(tmp_path/'actual-replay',[ROW]),public_log_read(tmp_path/'opaque',[row])]
    def finalize(phases):
        from tests.support.runtime_remaining_evidence import write_log_bundle
        paths=[]
        for i,(receipt,native,context,trace)in enumerate(captures):
            path=tmp_path/f'capture-{i}.json';pages=receipt.pop('public_pages')
            runtime.write_program_receipt(path,receipt,native,nodeid=request.node.nodeid,phase_reports=phases,source_context=context,native_reads=trace,
                public_calls=[{'gateway':receipt,'native_start':0,'native_end':len(trace)},*[{'gateway':p,'native_start':len(trace),'native_end':len(trace)}for p in pages]])
            paths.append(path)
        index=write_log_bundle(tmp_path/'bundle',paths,inventory=inventory);policies=json.loads((index.parent/'requirements.json').read_bytes())
        bindings,base,_=audit.portable_binding_inputs(index,policies)
        result=completion.evaluate_coverage(audit.ROOT,inventory,bindings,digest=audit.digest,evidence_base=base,requirements_document=policies)
        assert {r['state']for r in result['obligations']}=={'verified'},[(r['pointer'],r['evidence_results'])for r in result['obligations']]
    register_exact_evidence_finalizer(request.node,finalize)


def _severity_counterexample(path,branch,*,console):
    """Actual public rejection and causal successful counterpart; external transport only."""
    import contextlib
    import io
    from tests.support.empty_candidate_evidence import classify_empty_candidate
    path.mkdir(parents=True)
    uri=branch['route'].split('|')[-1];client=ConsoleLogClient(path);client.console=console
    trace=[];original=client.call
    def call(api,args=None,options=None):
        result=original(api,args,options)
        trace.append({'uri':api,'args':deepcopy(args or {}),'options':deepcopy(options or {}),'result':deepcopy(result)})
        return result
    client.call=call
    def invoke(argv):
        trace.clear();out,err=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            try:code,payload=gateway.execute_gateway(argv,env=_env(path),client_factory=lambda _:client)
            except SystemExit as exc:code,payload=exc.code,None
        return {'gateway':{'argv':argv,'exit_code':code,'payload':payload,'stdout':out.getvalue(),'stderr':err.getvalue()},'native_calls':deepcopy(trace)}
    prefix=['--state-dir',str(path/'state')];classification=classify_empty_candidate(audit.ROOT,branch)
    route=branch['route']
    if uri==GET:
        argv=[*prefix,'core-call',GET,'--log-channel','general']
        client.rows=[deepcopy(ROW)];valid=invoke(argv)
        client.rows[0]['severity']='';invalid=invoke(argv)
        i=next(i for i,c in enumerate(invalid['native_calls'])if c['uri']==GET)
        dispatch=f'/native_calls/{i}';observation=dispatch+'/result/items/0/severity'
        proof={'classification':classification,'valid':valid}
        chain=[route+'|/resultSchema/properties/items/items/$ref',route+'|/resultSchema/@definition/waapi_definitions.json/definitions/logCentralItem/properties/severity/$ref']
        check={'pointer':observation,'equals':''}
    else:
        started=invoke([*prefix,'draft-start',uri])['gateway']['payload']
        argv=[*prefix,'draft-declare-runtime-control-plan',started['draft']['draft_id'],'--task-authority',started['task_authority'],
            '--expected-revision',str(started['draft']['revision']),'--message','owned counterexample','--severity','']
        invalid=invoke(argv);valid=invoke([*argv[:-1],'message']);current=valid['gateway']['payload']
        checked=invoke([*prefix,'draft-check',current['draft']['draft_id'],'--task-authority',started['task_authority'],
            '--expected-revision',str(current['draft']['revision'])])['gateway']['payload']
        compiled=invoke([*prefix,'preview-from-draft',checked['draft']['draft_id'],'--task-authority',started['task_authority'],
            '--expected-revision',str(checked['draft']['revision'])])
        dispatch='/counterexample/compiled/gateway/payload/agent_result/request/arguments';observation=dispatch+'/args/severity'
        proof={'classification':classification,'valid':valid,'compiled':compiled,'public_input_pointer':'/gateway/argv/'+str(len(argv)-1)}
        chain=[route+'|/argsSchema/properties/severity/$ref'];check={'pointer':proof['public_input_pointer'],'equals':''}
    assert valid['gateway']['exit_code']==0 and invalid['gateway']['exit_code']==2
    record={**invalid,'scope_kind':'product','counterexample':proof,'branch_assertions':{branch['id']:{'native_route':route,'native_shape_sha256':branch['shape_sha256'],'checks':[check]}}}
    from tests.support.runtime_remaining_evidence import _code_bindings
    public_id='2025.1|function|'+uri
    binding={'branch_id':branch['id'],'native_shape_sha256':branch['shape_sha256'],'public_route':public_id,
        'disposition':'schema_counterexample','empty_candidate':classification,'input':{'gateway_argv':argv,'selector':observation},'dispatch_pointer':dispatch,
        'observation_pointer':observation,'reference_chain':chain,**_code_bindings(branch)}
    return record,binding


@pytest.mark.parametrize('console',[True,False],ids=['console','authoring'])
def test_log_invalid_severity_counterexamples_keep_native_gates(request,tmp_path,console):
    from tests.support import runtime_remaining_evidence as remaining
    from tests.support import runtime_log_retained_evidence as retained
    from tests.support.empty_candidate_evidence import counterexample_source_context,write_counterexample_bundle
    host='wwise-console'if console else'wwise-authoring';prefix=f'2025.1|{host}|2025.1.7.9143|function|'
    routes=[prefix+uri for uri in (GET,'ak.wwise.core.log.addItem')]
    pointers={'/resultSchema','/argsSchema/properties/severity/$ref','/resultSchema/properties/items/items/$ref',
        '/resultSchema/@definition/waapi_definitions.json/definitions/logCentralItem/properties/severity/$ref',
        '/resultSchema/@definition/waapi_definitions.json/definitions/logCentralSeverity/@empty/string',
        '/argsSchema/@definition/waapi_definitions.json/definitions/logCentralSeverity/@empty/string'}
    inventory=log_inventory(routes,pointers);source_context=counterexample_source_context(audit.ROOT)
    invalid=[b for b in inventory['native_coverage']['obligations']if b['pointer'].endswith('/logCentralSeverity/@empty/string')]
    assert len(invalid)==2
    counter=[(b,*_severity_counterexample(tmp_path/('counter-'+str(i)),b,console=console))for i,b in enumerate(invalid)]
    positive=deepcopy(inventory);positive['native_coverage']['obligations']=[b for b in positive['native_coverage']['obligations']if b not in invalid]
    if console:rows=[ROW];message=ROW['message']
    else:
        rows=retained.program_native_call(routes[0]+'|/resultSchema')['result']['items']
        message=retained.program_native_call(routes[1]+'|/resultSchema')['args']['message']
    read=public_log_read(tmp_path/'root-read',rows,console=console)
    control=public_log_control(tmp_path/'root-add',routes[1].split('|')[-1],console=console,message=message,channel='general',severity='message')
    def finalize(phases):
        paths=[]
        for i,values in enumerate((read,control)):
            if i==0:
                receipt,native,context,trace=values;calls=[{'gateway':receipt,'native_start':0,'native_end':len(trace)},
                    *({'gateway':page,'native_start':len(trace),'native_end':len(trace)}for page in receipt.pop('public_pages'))]
            else:receipt,native,context,trace,calls=values
            path=tmp_path/f'root-capture-{i}.json';runtime.write_program_receipt(path,receipt,native,nodeid=request.node.nodeid,phase_reports=phases,
                source_context=context,native_reads=trace,public_calls=calls);paths.append(path)
        index=remaining.write_log_bundle(tmp_path/'bundle',paths,inventory=positive);doc=json.loads(index.read_bytes());policies=json.loads((index.parent/'requirements.json').read_bytes())
        for branch,record,binding in counter:
            public=next(r for r in inventory['routes']if r['id']==binding['public_route']);binding['public_route_sha256']=audit.digest(public)
            part=write_counterexample_bundle(index.parent,record,branch=branch,binding=binding,inventory=inventory,root=audit.ROOT,
                nodeid=request.node.nodeid,phase_reports=phases,source_context=source_context)
            fragment=json.loads(part.read_bytes());doc['entries'].extend(fragment['entries'])
            req=fragment['entries'][0]['origin']['requirements'];policies['branches'].update(completion.read_sealed_artifact(req,index.parent)['branches'])
        runtime.write_json(index,doc);runtime.write_json(index.parent/'requirements.json',policies)
        bindings,base,_=audit.portable_binding_inputs(index,policies)
        result=completion.evaluate_coverage(audit.ROOT,inventory,bindings,digest=audit.digest,evidence_base=base,requirements_document=policies)
        runtime.write_json(tmp_path/'consumer-result.json',result)
        assert {r['state']for r in result['obligations']}=={'verified'},[(r['pointer'],r['evidence_results'])for r in result['obligations']]
        missing=deepcopy(bindings)
        for bound in missing['bindings'].values():bound['evidence'].pop('native',None)
        blocked=completion.evaluate_coverage(audit.ROOT,inventory,missing,digest=audit.digest,evidence_base=base,requirements_document=policies)
        assert all(r['state']!='verified'for r in blocked['obligations'])
        for branch,_,_ in counter:
            damaged=deepcopy(policies);damaged['branches'][branch['id']]['reason']='caller downgrade'
            rejected=completion.evaluate_coverage(audit.ROOT,inventory,bindings,digest=audit.digest,evidence_base=base,requirements_document=damaged)
            assert next(r for r in rejected['obligations']if r['id']==branch['id'])['state']!='verified'
    register_exact_evidence_finalizer(request.node,finalize)


def test_remaining_policy_does_not_enter_unrelated_or_empty_scope(tmp_path):
    from tests.support import runtime_remaining_evidence as remaining
    unrelated='2025.1|wwise-console|2025.1.7.9143|function|ak.wwise.core.object.get|/resultSchema'
    assert remaining.selected(unrelated,tmp_path) is False
    assert remaining.preservation_gates(tmp_path,{},[])=={}
    assert remaining.preservation_gates(tmp_path,{'unrelated':{'categories':['program']}},[{'id':'unrelated','route':'unrelated'}])=={}
    owned=ROUTE+'|/resultSchema'
    with pytest.raises(FileNotFoundError):remaining.selected(owned,tmp_path)
    path=tmp_path/remaining.POLICY;path.parent.mkdir(parents=True);path.write_text('{}')
    with pytest.raises(ValueError,match='descriptor changed'):remaining.selected(owned,tmp_path)


def test_remaining_policy_portable_scope_keeps_history_without_git(tmp_path,monkeypatch):
    import shutil
    from tests.support import runtime_remaining_evidence as remaining
    from pathlib import Path
    # Export just the complete policy closure; no .git or historical checkout.
    paths=[remaining.POLICY,'tests/fixtures/runtime/runtime-remaining-prior-r127.json.gz',
        'tests/fixtures/runtime/runtime-risk-policy-r124.json','tests/fixtures/runtime/runtime-opaque-policy-r126.json']
    for name in paths:
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(audit.ROOT/name,path)
    import subprocess
    monkeypatch.setattr(subprocess,'check_output',lambda *a,**k:pytest.fail('Portable policy history must not invoke git'))
    roster=remaining.review(tmp_path);identity=ROUTE+'|/resultSchema';entry=roster['entries'][identity]
    branch={**entry,'id':identity,'shape_sha256':entry['native_shape_sha256']}
    requirements={'contract':'waapi-skill.branch-evidence-requirements/v1','branches':{identity:remaining.policy(entry)}}
    output=tmp_path/'portable';output.mkdir()
    program=runtime.write_json(output/'program.json',{'contract':'controlled-policy-path-not-verification'})
    bindings=runtime.write_json(output/'bindings.json',{'contract':'waapi-skill.branch-bindings/v1','bindings':{identity:{'branch_id':identity,'evidence':{'program':program}}}})
    req=runtime.write_json(output/'requirements.json',requirements)
    index=runtime.write_json(output/'index.json',{'contract':'waapi-skill.branch-evidence-index/v1','base':'.','entries':[
        {'id':'portable-policy','bindings':bindings,'origin':{'bindings':bindings,'program':program,'capture':program,'requirements':req}}]})
    document,base,_=audit.portable_binding_inputs(output/index['artifact'],requirements)
    assert set(document['bindings'])=={identity}and base==output
    assert remaining.preservation_gates(tmp_path,requirements['branches'],[branch])=={identity:[]}
    historical=tmp_path/'tests/fixtures/runtime/runtime-remaining-prior-r127.json.gz';historical.write_bytes(historical.read_bytes()+b'corrupt')
    with pytest.raises(ValueError,match='prior.*changed'):remaining.review(tmp_path)
