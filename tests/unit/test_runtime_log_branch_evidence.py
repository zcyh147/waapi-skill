"""Direct public Gateway behavior with injected native responses."""

from copy import deepcopy

import gzip

import json

import pytest

from tests.maintenance import branch_coverage_audit as audit

from tests.unit.test_console_log_observer_gateway import ConsoleLogClient

from tests.unit.test_runtime_business_gateway import _env, gateway, _LogControlClient

from tests.unit.test_fixed_runtime_read_branch_evidence import pointer_value

GET = 'ak.wwise.core.log.get'

ROUTE = '2025.1|wwise-console|2025.1.7.9143|function|' + GET

ROW = {'severity':'Message','message':'WAAPI owned Console addition 2c3d53909345442d977fc2d79c1d3c3e',
       'time':1792821462,'messageId':''}

def public_log_read(path, rows, *, version='2025.1', console=True, channel='general'):
    path.mkdir(parents=True)
    context = None
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
            target=pointer_value(documents[key[0]],pointer)
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
    rows=native_log_rows(version)
    assert rows
    captures=[public_log_read(tmp_path/str(i),[row],version=version,console=console)for i,row in enumerate(rows)]
    channels=['soundbank-generation','audio-conversion','platform-settings-copy','waapi','project-load']
    if version in {'2023.1','2024.1','2025.1'}:channels+=['source-control','lua']
    captures.extend(public_log_read(tmp_path/('channel-'+channel),[ROW],version=version,console=console,channel=channel)for channel in channels)
    captures.append(public_log_read(tmp_path/'empty',[],version=version,console=console))
    captures.append(public_log_read(tmp_path/'multiple',[ROW,ROW],version=version,console=console))

def public_log_control(path,uri,*,version='2025.1',console=False,channel='general',severity='message',message='owned log control'):
    path.mkdir(parents=True)
    client=ConsoleLogClient(path,version=version)if console else _LogControlClient(path,version=version)
    client.console=console;client.rows=[deepcopy(ROW)]
    context=None;trace=[];calls=[];original=client.call
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
    receipt,native,context,trace,calls=public_log_control(tmp_path/'public',uri,console=console,message=ROW['message'],
        channel=None if operation=='addItem'else'general',severity=None)

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
    opaque={'/key~':'值','array':[None,False,True,3.5,{'deep':['opaque']}],'empty':{}}
    reference={'id':'{11111111-1111-1111-1111-111111111111}','name':'reference','/opaque~field':opaque}
    platform={'id':'{22222222-2222-2222-2222-222222222222}','name':'platform',
        '@Evidence':deepcopy(reference),'@@EvidenceList':[deepcopy(reference)],'/opaque~field':deepcopy(opaque)}
    row={**ROW,'platform':platform}
    captures=[public_log_read(tmp_path/'actual-replay',[ROW]),public_log_read(tmp_path/'opaque',[row])]
