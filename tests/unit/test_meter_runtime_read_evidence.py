"""Direct public Gateway behavior with injected native responses."""

from copy import deepcopy

import json

import pytest

from tests.maintenance import branch_coverage_audit as audit

from tests.unit.test_runtime_business_gateway import gateway, _env

from tests.unit.test_profiler_meter_objects_gateway import MeterClient, METERS

from tests.unit.test_fixed_runtime_read_branch_evidence import pointer_value

BUILDS={'2024.1':'2024.1.13.9056','2025.1':'2025.1.7.9143'}

def public_read(path,version,console,rows,argv):
    path.mkdir(parents=True);context=None
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


def meter_fixture_rows(version,mode):
    """Finite reflected value domains; these values claim no native population."""
    from wwise_waapi.native_catalog import load_native_catalog
    catalog=load_native_catalog(version,'wwise-authoring');docs=catalog['definitions']['documents']
    guid='{FBF74BF9-8B83-44A8-AC8A-BA85372ECDC4}'
    def value(node,document='waapi_definitions.json',depth=0):
        assert depth<16
        if '$ref'in node:
            doc,pointer=node['$ref'].split('#',1);doc=doc or document
            return value(pointer_value(docs[doc],pointer),doc,depth+1)
        for union in ('oneOf','anyOf'):
            if union in node:return value(node[union][mode%len(node[union])],document,depth+1)
        if 'enum'in node:return deepcopy(node['enum'][mode%len(node['enum'])])
        kind=node.get('type')
        if isinstance(kind,list):kind=kind[mode%len(kind)]
        if kind=='object':
            fields=node.get('properties',{})
            return {k:value(v,document,depth+1)for k,v in fields.items()if mode not in {2,3,10}or (depth==0 and mode!=10)or k in node.get('required',[])}
        if kind=='array':
            n=0 if mode==3 else 1 if mode in {1,2}else 2
            return [value(node['items'],document,depth+1)for _ in range(max(n,node.get('minItems',0)))]
        if kind=='string':return guid if 'pattern'in node else ''if mode==1 else 'Conditional fixture'
        if kind=='boolean':return bool(mode%2)
        if kind in {'integer','number'}:
            return node.get('minimum',0)if mode%2==0 else node.get('maximum',1)
        if kind=='null':return None
        raise AssertionError(('Unplanned reflected fixture shape',node))
    schema=docs['waapi_definitions.json']['definitions']['objectReturn'];obj=value(schema)
    # Canonical GUID validity is independent of the empty-string fixture mode.
    if 'id'in obj:obj['id']=guid
    item=catalog['schemas'][METERS]['resultSchema']['properties']['meters']['items']
    row=value(item)
    row['object']=obj
    return [row]if mode in {1,2,3}else[row,deepcopy(row)]

@pytest.mark.parametrize('version,console', [('2024.1', False), ('2025.1', True)])
def test_known_meter_fields_public_whole_arrays_teardown_and_exact_gates(request,tmp_path,version,console):
    from wwise_waapi.profiler_meter_objects import meter_named_outputs
    captures=[]
    names=list(meter_named_outputs(version));chunks=[names[i:i+32]for i in range(0,len(names),32)]
    # Whole arrays and absent optional fields exercise the shared projection.
    # Enum domains and selectors are already checked at the public contract seam.
    for mode in (0, 3):
        for chunkno,names in enumerate(chunks):
            argv=['core-call',METERS,'--profiler-position',str(mode),'--max-results','1']
            for name in names:argv+=['--meter-object-include',name]
            rows=meter_fixture_rows(version,mode)
            captures.append(public_read(tmp_path/f'{mode}-{chunkno}',version,console,rows,argv))
    for label,position,rows,flags in [('empty',1,[],[]),
            ('empty-selection',1,meter_fixture_rows(version,0),['--meter-object-empty-selection']),
            ('capture','capture-latest',meter_fixture_rows(version,0),['--meter-object-include','notes']),
            ('user','user-cursor',meter_fixture_rows(version,0),['--meter-object-include','notes'])]:
        captures.append(public_read(tmp_path/label,version,console,rows,['core-call',METERS,'--profiler-position',str(position),'--max-results','64',*flags]))
