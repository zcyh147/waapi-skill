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
    native_route, = [r for r in stored['native_coverage']['routes'] if r['id'] == route]
    obligations = []
    for encoded in packed['rows']:
        if encoded.get('route') is None or packed['routes'][encoded['route']] != route:
            continue
        row = dict(encoded); row.update(packed['contexts'][row.pop('context')])
        row.update(route=route,id=route+'|'+row['pointer'],shape_sha256=packed['shapes'][row.pop('shape')])
        if pointers is None or row['pointer'] in pointers: obligations.append(row)
    return {'routes':[r for r in stored['routes'] if r['id']==native_route['public_route']],
        'native_coverage':{'candidate_sha256':'f'*64,'catalogs':stored['native_coverage']['catalogs'],
                          'routes':[native_route],'obligations':obligations}}


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
    assert sum(e['categories']==['program','native']for e in reviewed['entries'].values())==169
    assert sum(not e['pointer'].startswith('/resultSchema')for e in reviewed['entries'].values())==3003
    assert {p for p in original}==set(reviewed['entries'])
    published=json.loads((audit.ROOT/'docs/branch-coverage-requirements.json').read_bytes())['branches']
    assert not set(original)&set(published)
    for identity,entry in reviewed['entries'].items():
        assert all(entry[k]==original[identity][k]for k in ('route','pointer','kind','native_shape_sha256','owner_issue','parent_issue','blocks_issue'))
        anchors=entry['required_native_anchor_ids']
        assert anchors==([]if entry['pointer']=='/resultSchema'else[entry['route']+'|/resultSchema'])
        assert policy(entry)['categories']==entry['categories']


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
    captures=[public_log_read(tmp_path/'actual-replay',[ROW],version=version,console=console),
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
        write_log_bundle(tmp_path/'bundle',paths,inventory=inventory)
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
    declaration=['--log-channel',channel]
    if uri.endswith('.addItem'):declaration+=['--message',message,'--severity',severity]
    current=invoke(['draft-declare-runtime-control-plan',draft,'--task-authority',authority,'--expected-revision',str(started['draft']['revision']),*declaration])
    current=invoke(['draft-check',draft,'--task-authority',authority,'--expected-revision',str(current['draft']['revision'])])
    preview=invoke(['preview-from-draft',draft,'--task-authority',authority,'--expected-revision',str(current['draft']['revision'])])
    shown=invoke(preview['next_command']['gateway_argv']);invoke(shown['next_command']['gateway_argv'])
    executed=invoke(['execute',preview['transaction_id']]);verified=invoke(executed['next_command']['gateway_argv'])
    native,=[x for x in trace if x['uri']==uri]
    assert verified['agent_result']['request']['arguments']=={'api':uri,'args':native['args'],'options':native['options']}
    assert verified['agent_result']['result']==native['result']
    assert verified['verified']is True,verified
    return calls[-1]['gateway'],{k:native[k]for k in ('uri','args','options','result')},context,trace,calls


@pytest.mark.parametrize('operation',['addItem','clear'])
@pytest.mark.parametrize('console',[False,True],ids=['authoring','console'])
def test_log_control_public_transaction_evidence(request,tmp_path,operation,console):
    uri='ak.wwise.core.log.'+operation
    route='2025.1|'+('wwise-console'if console else'wwise-authoring')+'|2025.1.7.9143|function|'+uri
    inventory=log_inventory(route,pointers={'/argsSchema','/optionsSchema','/resultSchema'})
    receipt,native,context,trace,calls=public_log_control(tmp_path/'public',uri,console=console,message=ROW['message'])
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
