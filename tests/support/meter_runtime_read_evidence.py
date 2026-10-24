"""Closed getMeters public replay and the two retained Authoring meter facts.

Conditional fake values prove preservation, not native population or applicability.
The Console roots and the 60 spelling/12 empty-input questions remain blocking.
"""
from copy import deepcopy
from functools import lru_cache
import gzip
import json
from pathlib import Path
import shutil

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support import runtime_observation_evidence as runtime
from tests.support import runtime_remaining_evidence as remaining
from tests.support import extra_runtime_read_evidence as extra

URI='ak.wwise.core.profiler.getMeters'
URIS=frozenset({URI})
SUPPORT='tests/fixtures/runtime-meter/support-review.json'
SUPPORT_SHA='18594040da2afa4a090a8e1a2c8756b8a5f23391a93e8a5bdb69c4f91fe1efc0'
CONTRACT='waapi-skill.meter-runtime-read-assessment/v1'


def review(root=audit.ROOT):
    d=remaining._read_pin(root/SUPPORT,SUPPORT_SHA)
    expected={k:v for k,v in remaining.review(root)['entries'].items()if v['route'].endswith('|'+URI)}
    groups=[set(d[k])for k in ('program_candidate_ids','native_root_ids','pending_spelling_ids','pending_empty_input_ids')]
    if (d['entries']!=expected or len(expected)!=2744 or list(map(len,groups))!=[2668,4,60,12]
            or set.union(*groups)!=set(expected)or sum(map(len,groups))!=len(expected)
            or d['pending_native_business_anchor_ids']!=[k for k in d['native_root_ids']if '|wwise-console|'in k]
            or set(d['profiles'])!={k for k in d['native_root_ids']if '|wwise-authoring|'in k}):
        raise ValueError('Exact meter scope/pending/native root ownership differs')
    singles={k for k,v in expected.items()if v['pointer']=='/optionsSchema/@definition/waapi_definitions.json/definitions/returnExpression/@cardinality/single'}
    marker={'kind':'gateway-owned-identity-augmentation','public_flag':'--meter-object-include','requested_outputs':['notes'],
        'native_return':['id','name','type','path','notes'],'native_cardinality':5,'literal_native_single':False}
    if len(singles)!=4 or d['normalized_input_choices']!={k:{'native_shape_sha256':expected[k]['native_shape_sha256'],**marker}for k in singles}:
        raise ValueError('Exact source-owned meter single-output normalization differs')
    return d


def original_profile(version,base=None,*,root=audit.ROOT):
    """Full original source/manifest/finalized cleanup closure, shared by controls.

    The returned read accessor resolves original sealed archive paths verbatim.
    Register/unregister consumers must additionally validate their own exact calls.
    """
    support=review(root);d=support['providers'][version];label='meter-'+d['label']
    archive_path=root/d['archive_source']if base is None else Path(base)/(label+'-original.json.gz')
    read=runtime.archive_reader({'artifact':archive_path.name,'sha256':d['archive_sha256']},archive_path.parent)
    fs=json.loads(gzip.decompress(archive_path.read_bytes()))['files']
    if len(fs)!=d['archive_files']or audit.digest(fs)!=d['archive_map_sha256']:raise ValueError('Whole original meter closure differs')
    for path,seal in d['seals'].items():
        if runtime.sha(read(path))!=seal:raise ValueError('Exact original meter seal differs')
    capture=json.loads(read(d['capture_path']));node=json.loads(read(d['node_path']));rn=d['original_root']
    final=json.loads(read(rn+'/evidence/authoring-batch-finalization.json'));life=json.loads(read(rn+'/evidence/lifecycle-final.json'));check=json.loads(read(rn+'/root-review.json'))
    sources=d['sources'];extra._historical(root,d['candidate'],json.dumps(sources,sort_keys=True))
    current=runtime.program_source_context(root,flow=URI)['packaged']
    changes={p:{'before':sources.get(p),'after':current.get(p)}for p in sources.keys()|current.keys()if sources.get(p)!=current.get(p)}
    if len(sources)!=412 or len(current)!=413 or changes!=d['source_changes']:raise ValueError('Exact complete meter source bridge differs')
    for group in node['artifacts'].values():
        for item in group['files']:
            body=read(group['path']+'/'+item['path'])
            if runtime.sha(body)!=item['sha256']or len(body)!=item['bytes']:raise ValueError('Original complete meter node manifest differs')
    if (node['candidate']!=d['candidate']or any(node['source_context']['sources'].get(p)!=v for p,v in sources.items())
            or capture['candidate']!=d['candidate']or completion.native_host_context(capture['host'],'isCommandLine')!={k:d[k]for k in ('version','host','build')}
            or capture['fixture_before']!=capture['fixture_after']or capture['cleanup']['complete']is not True or capture['cleanup']['errors']!=[]
            or final['candidate']!=d['candidate']or final['outcome']!='PASS'or final['lifecycle']!=life
            or final['node_outcomes']!=[{'nodeid':node['nodeid'],'outcome':'PASS'}]
            or final['observations'][node['nodeid']]!={'bytes':len(read(d['node_path'])),'path':d['node_path'],'sha256':d['seals'][d['node_path']]}
            or life['final_status']!='PASS'or life['errors']!=[]or life['sandbox_retained']is not False
            or life['source_hash_before']!=life['source_hash_after']or life['source_mtime_before_ns']!=life['source_mtime_after_ns']
            or check['candidate']!=d['candidate']or check['outcome']!='PASS'or check['pytest']['exit_code']!=0
            or any(check[k]is not True for k in ('source_unchanged','cleanup_complete','port_released'))or check['residual_processes']!=[]):
        raise ValueError('Original meter host/source/final PASS/cleanup facts differ')
    identity=next(k for k,p in support['profiles'].items()if p['version']==version);profile=support['profiles'][identity]
    raw=json.loads(read(profile['raw_path']));issuer=json.loads(read(profile['issuer_path']));request=profile['request'];live=issuer['context']['live']
    receipts=[r for r in node['receipts']if r['argv']==profile['argv']];receipt,=receipts
    outcome=capture['outcomes']['profiler-meter-object-observation'];e=outcome['evidence']
    if (raw['api']!=URI or raw['version']!=version or raw['ok']is not True or raw['dry_run']is not False
            or issuer['sha256']!=audit.digest({k:v for k,v in issuer.items()if k!='sha256'})or issuer['plan']['request']!=request
            or request['args']!={'time':capture['capture_position']['position_ms']}or len(raw['result']['meters'])!=profile['native_rows']
            or not raw['result']['meters']or outcome['outcome']!='PASS'or receipt['payload']['agent_result']['complete']is not True
            or e['position_ms']!=request['args']['time']or not e['meters']or any(row not in issuer['plan']['result']['meters']for row in e['meters'])
            or receipt['exit_code']!=0 or receipt['payload']['ok']is not True or receipt['payload']['agent_result']['meters']!=issuer['plan']['result']['meters']
            or receipt['payload']['agent_result']['meter_object_projection']!=issuer['plan']['result']['meter_object_projection']
            or any(live[k]!=capture['host'][k]for k in ('processId','sessionId','version'))):
        raise ValueError('Exact original meter native/public issuer/whole array differs')
    from wwise_waapi.builders.schema import validate_resolved_semantic_result
    validate_resolved_semantic_result(URI,raw['result'],version=version,meter_projection_fields=request['options']['return'])
    facts={'original_finalization':'PASS','original_reader_outcome':'PASS','native_nonempty_rows':len(raw['result']['meters']),
        'physical_cleanup_complete':True,'source_preserved':True,'global_pass_transferred':False}
    return dict(descriptor=d,profile=profile,label=label,read=read,node=node,capture=capture,finalization=final,sources=sources,
        source_changes=changes,native=raw,call={'uri':URI,'args':request['args'],'options':request['options'],'result':raw['result']},facts=facts)


@lru_cache(maxsize=256)
def _capture(captured_json,root):
    from scripts import gateway
    from wwise_waapi.builders.schema import validate_semantic_payload,validate_semantic_result,validate_resolved_semantic_result
    from wwise_waapi.profiler_meter_objects import compile_meter_object_options
    from wwise_waapi.runtime_inspection_business import materialize_runtime_inspection_business_request,normalize_runtime_inspection_result
    if len(captured_json.encode('utf-8'))>80*1024*1024:raise ValueError('Meter capture exceeds its finite byte budget')
    c=json.loads(captured_json);g=c['gateway'];native=c['native_call'];trace=c['native_reads'];calls=c['public_calls'];p=g['payload'];argv=g['argv']
    allowed={URI,'ak.wwise.core.getInfo','ak.wwise.core.getProjectInfo','ak.wwise.core.profiler.getCursorTime',
        'ak.wwise.core.object.getPropertyAndReferenceNames','ak.wwise.core.object.getPropertyInfo','ak.wwise.core.object.get'}
    if (native['uri']!=URI or c['contract']!='waapi-skill.runtime-read-program/v1'or c['phase_reports']!=dict.fromkeys(('setup','call','teardown'),'passed')
            or c['source_unchanged']is not True or c['source_context']!=runtime.program_source_context(root,flow=URI)
            or g['exit_code']!=0 or p.get('ok')is not True or not 1<=len(trace)<=128 or not 1<=len(calls)<=128
            or any(set(r)!={'ordinal','uri','args','options','result'}or type(r['ordinal'])is not int or r['ordinal']!=i or r['uri']not in allowed for i,r in enumerate(trace))
            or argv[:2]!=['core-call',URI]):raise ValueError('Exact current meter public phases/source/finite trace required')
    # Parse only the existing public meter declaration. Unrelated Gateway flags
    # cannot be smuggled through a packet and authenticated by its own argv.
    flags={'--profiler-position','--max-results','--meter-object-include','--meter-object-include-field',
        '--meter-object-include-override-source-value','--meter-object-include-local-reference',
        '--meter-object-include-related','--meter-object-include-related-field','--meter-object-include-related-override-source-value',
        '--meter-object-include-related-local-reference','--meter-object-empty-selection','--meter-platform','--meter-language'}
    if any(v.startswith('--')and v not in flags for v in argv[2:]):raise ValueError('Only closed meter public flags qualify')
    args=gateway.build_parser().parse_args(argv)
    info,=[r['result']for r in trace if r['uri']=='ak.wwise.core.getInfo'];context=completion.native_host_context(info,'isCommandLine');version=context['version']
    if version not in {'2024.1','2025.1'}or p.get('is_command_line')is not (context['host']=='wwise-console'):raise ValueError('Exact meter host/version differs')
    request,_,business=materialize_runtime_inspection_business_request(URI,version,profiler_position=args.profiler_position,max_results=args.max_results,log_channel=None)
    reads=[r for r in trace if r['uri']not in {'ak.wwise.core.getInfo','ak.wwise.core.getProjectInfo'}];position=business['profiler_position']
    if position in {'capture-latest','user-cursor'}:
        cursor=reads.pop(0)
        if cursor['uri']!='ak.wwise.core.profiler.getCursorTime'or cursor['args']!={'cursor':{'capture-latest':'capture','user-cursor':'user'}[position]}or cursor['options']!={}:raise ValueError('Exact meter frozen cursor differs')
        validate_resolved_semantic_result(cursor['uri'],cursor['result'],version=version)
        request['args']['time']=cursor['result']['return']
    selected=compile_meter_object_options(args,version,compile_condition=lambda condition:gateway._query_sequence_condition(version,condition))
    def read(uri,arguments,options):
        if not reads:raise ValueError('Missing selected meter/metadata read')
        actual=reads.pop(0)
        if {k:actual[k]for k in ('uri','args','options')}!={'uri':uri,'args':arguments,'options':options}:raise ValueError('Exact selected meter/metadata request sequence differs')
        validate_semantic_payload(uri,arguments,options,version=version)
        validate_semantic_result(uri,actual['result'],version=version)
        return deepcopy(actual['result'])
    if selected.prepare(read_meter=lambda options:read(URI,request['args'],options),read_metadata=read,time=request['args']['time'])is not None:
        raise ValueError('Clarification cannot qualify a complete meter result')
    request['options']=selected.options();result=read(URI,request['args'],request['options'])
    if reads or native!={'uri':URI,'args':request['args'],'options':request['options'],'result':result}:
        raise ValueError('Exact final meter native call/unused reads differ')
    validate_resolved_semantic_result(URI,result,version=version,meter_projection_fields=request['options'].get('return'))
    projected=selected.project(result)
    expected=normalize_runtime_inspection_result(URI,projected,business_request=business,max_results=max(1,len(result['meters'])),version=version)
    if p['business_request']!={'operation':URI,**business,'max_results':args.max_results}or any(p['schema_validation'][s]['version']!=version for s in ('request','result')):
        raise ValueError('Exact meter compiled business/validation differs')
    rows=[];previous=None;offset=0;fragment='';fragment_row=None
    for i,call in enumerate(calls):
        page=call['gateway'];payload=page['payload'];out=payload['agent_result'];page_rows=out['meters'];end=offset+len(page_rows)
        if 'row_fragment'in out:
            f=out['row_fragment']
            if page_rows or f['offset_characters']!=len(fragment)or f['row_index']!=len(result['meters'])-offset-1 or type(f['value'])is not str:
                raise ValueError('Exact meter row-fragment offset/identity differs')
            if fragment_row is not None and fragment_row!=f['row_index']:raise ValueError('Meter fragment row changed')
            fragment_row=f['row_index'];fragment+=f['value']
            if len(fragment)>f['total_characters']:raise ValueError('Meter fragment overflow')
            if len(fragment)==f['total_characters']:
                rows.insert(0,json.loads(fragment));fragment='';fragment_row=None;end=offset+1
        else:rows=page_rows+rows
        if (set(call)!={'gateway','native_start','native_end'}or call['native_start']!=(0 if i==0 else len(trace))or call['native_end']!=len(trace)
                or (page!=g if i==0 else page['argv']!=previous['next_command']['full_argv'][3:])or page['exit_code']!=0 or payload['ok']is not True
                or list(payload)[-1]!='agent_result'or out['profiler_position']!=position or out['total_count']!=len(result['meters'])
                or out['returned_count']!=len(page_rows)or out['complete']is not (i==len(calls)-1)or out['snapshot_sha256']!=audit.digest(expected)
                or out['instantaneous_native_resource_authority']is not False or out['observation']!='retained_profiler_capture_snapshot'
                or out['page']!={'offset_from_end':offset,'next_offset_from_end':end,'order':'newest_range_first_native_order_within_range'}
                or out['truncated']is not (i<len(calls)-1)or out['expires_at']!=p['agent_result']['expires_at']
                or audit.digest(out.get('meter_object_projection'))!=audit.digest(projected.get('meter_object_projection'))):
            raise ValueError('Exact complete meter public pages/proof/spans/order differ')
        offset=end;previous=out
    if fragment or audit.digest(rows)!=audit.digest(projected['meters']):raise ValueError('Whole selected native meter array must survive public projection/pages/fragments')
    return context


def _code_bindings(branch):
    construction=('profiler_meter_objects.py#compile_meter_object_options'if branch['pointer'].startswith('/optionsSchema')else'runtime_inspection_business.py#materialize_runtime_inspection_business_request')
    validation='validate_resolved_semantic_result'if branch['pointer'].startswith('/resultSchema')else'validate_semantic_payload'
    return {k:{'source':'skills/waapi-skill/wwise_waapi/'+source,'selector':branch['pointer']}for k,source in (
        ('construction',construction),('validation','builders/schema.py#'+validation),('verifier','profiler_meter_objects.py#MeterObjectOptions'))}


def _selected_occurrence(captured,pointer):
    prefix='/native_call/result/meters/'
    if pointer.startswith(prefix)and '/object/'in pointer:
        token=pointer.split('/object/',1)[1].split('/')[0]
        # Optional object fields count only when explicitly selected at this root.
        if token not in captured['native_call']['options'].get('return',['id','name']):return False
    return True


def _normalized_single(branch,captured,root=audit.ROOT):
    marker=review(root)['normalized_input_choices'].get(branch['id'])
    if marker is None:return None
    argv=captured['gateway']['argv'];native=captured['native_call']
    if (len(argv)==8 and argv[:2]==['core-call',URI]and argv[2]=='--profiler-position'
            and argv[4]=='--max-results'and argv[6:]==['--meter-object-include','notes']
            and native['options']=={'return':['id','name','type','path','notes']}):
        return marker
    return None


def mappings(inventory,captured,route,*,seen=frozenset()):
    branches=[b for b in inventory['native_coverage']['obligations']if b['route']==route['id']]
    edges={b['id']:b for b in branches if b['kind']=='reference'};found=[]
    for branch in branches:
        if branch['id']in seen:continue
        normalized=_normalized_single(branch,captured)
        if normalized is not None:
            found.append({'branch':branch,'program_pointer':'/native_call/options/return',
                'reference_chain':runtime._contribution_chains(branch,edges)[0],'normalized_input_choice':normalized});continue
        if branch['pointer']in runtime.CONTRIBUTION_CURSOR_POINTERS:
            cursors=[r for r in captured['native_reads']if r['uri'].endswith('.getCursorTime')]
            if cursors and extra.predicate(branch,cursors[0]['args']['cursor'],audit.ROOT):
                found.append({'branch':branch,'program_pointer':f"/runtime_read_program/native_reads/{cursors[0]['ordinal']}/args/cursor",'reference_chain':runtime._contribution_chains(branch,edges)[0]})
            continue
        effective=extra._effective(branch,audit.ROOT)
        for chain in runtime._contribution_chains(effective,edges):
            hit=next(((p,v)for p,v in remaining._log_occurrences(captured,runtime._contribution_pattern(effective,chain,edges))
                if _selected_occurrence(captured,p)and extra.predicate(branch,v,audit.ROOT)),None)
            if hit:
                found.append({'branch':branch,'program_pointer':hit[0],'reference_chain':chain});break
    return found


def validate_evidence(record,binding,branch,category,base,root,edges=None):
    entry=remaining.exact_entry(branch,root);d=review(root)
    if category!='program'or branch['id']not in set(d['program_candidate_ids'])|set(d['native_root_ids']):raise ValueError('Only exact known meter program branches qualify')
    c=record['runtime_read_program'];g=record['gateway'];version,host,build,_,uri=branch['route'].split('|')
    if (record['native_call']!=c['native_call']or g!=c['gateway']or g['argv']!=binding['input']['gateway_argv']
            or record['relevant_sources']!=c['source_context']['packaged']or _capture(json.dumps(c),root)!={'version':version,'host':host,'build':build}
            or any(binding.get(k)!=v for k,v in _code_bindings(branch).items())or not _selected_occurrence(c,binding['observation_pointer'])):
        raise ValueError('Exact meter public source/selected-root/binding/host differs')
    pointer=binding['observation_pointer'];effective=extra._effective(branch,root)
    normalized=_normalized_single(branch,c,root)
    if branch['id']in d['normalized_input_choices']:
        completion.exact_observation_pointer(branch,binding,'/native_call','options',edges or {})
        if normalized is None or audit.digest(binding.get('normalized_input_choice'))!=audit.digest(normalized) or pointer!='/native_call/options/return':
            raise ValueError('Exact disclosed one-output identity normalization required; no literal native-single claim')
        return {'observation_pointer':pointer}
    if binding.get('normalized_input_choice')is not None:raise ValueError('Unlisted meter branch cannot borrow normalization')
    if branch['pointer']in runtime.CONTRIBUTION_CURSOR_POINTERS:
        completion.exact_observation_pointer(branch,{**binding,'observation_pointer':'/native_call/args/time'},'/native_call','args',edges or {})
        cursor,=[r for r in c['native_reads']if r['uri'].endswith('.getCursorTime')]
        expected=f"/runtime_read_program/native_reads/{cursor['ordinal']}/args/cursor"
        if pointer!=expected or not extra.predicate(branch,cursor['args']['cursor'],root):raise ValueError('Exact public meter cursor branch differs')
        return {'observation_pointer':expected}
    completion.exact_observation_pointer(effective,binding,'/native_call',branch['pointer'].split('/')[1].removesuffix('Schema'),edges or {})
    if not extra.predicate(branch,remaining._occurrence_value(record,pointer,branch),root):raise ValueError('Exact meter branch predicate failed')
    if effective!=branch:return {'observation_pointer':pointer}


def attach_gate(output,index,candidate,branch,cp,prefix):
    if branch['id']not in review()['profiles']:return
    original_fact=original_profile(branch['route'].split('|')[0]);captured=completion.read_sealed_artifact(cp,output)
    if captured['native_call']!=original_fact['call']:return
    d=original_fact['descriptor'];label=original_fact['label']
    shutil.copyfile(audit.ROOT/d['archive_source'],output/(label+'-original.json.gz'));shutil.copyfile(audit.ROOT/SUPPORT,output/'meter-support.json')
    def write(name,value):return runtime.write_json(output/name,value)
    def desc(name):return {'artifact':name,'sha256':runtime.sha((output/name).read_bytes())}
    raw_name=prefix+'raw.json';(output/raw_name).write_bytes(original_fact['read'](original_fact['profile']['raw_path']))
    assessment=write(prefix+'assessment.json',{'contract':CONTRACT,'branch_id':branch['id'],'profile':original_fact['profile'],
        'source_review':desc('meter-support.json'),'archive':desc(label+'-original.json.gz'),'raw':desc(raw_name),'program_capture':cp,'retained_facts':original_fact['facts']})
    evidence=write(prefix+'qualified.json',{'candidate_sha256':candidate,'scope_kind':'product','evidence_kind':'qualified_retained_meter_fact',
        'branch_id':branch['id'],'native_shape_sha256':branch['shape_sha256'],'assessment_sha256':assessment['sha256'],
        'retained_facts':original_fact['facts'],'relevant_sources':d['sources']})
    index.setdefault('qualified_runtime_read_attachments',[]).append(write(prefix+'attachment.json',
        {'contract':'waapi-skill.qualified-retained-read-attachment/v1','branch_id':branch['id'],'assessment':assessment,'evidence':evidence}))


def qualified_result(descriptor,assessment,branch,candidate,scope_kind,base,binding,root,edges):
    remaining.exact_entry(branch,root);profile=review(root)['profiles'].get(branch['id'])
    if (profile is None or assessment['contract']!=CONTRACT or assessment['branch_id']!=branch['id']or assessment['profile']!=profile
            or scope_kind!='product'or assessment['source_review']['sha256']!=SUPPORT_SHA
            or completion.read_sealed_artifact(assessment['source_review'],base)!=review(root)):raise ValueError('Only exact two Authoring meter roots qualify')
    fact=original_profile(branch['route'].split('|')[0],base,root=root);d=fact['descriptor'];captured=completion.read_sealed_artifact(assessment['program_capture'],base)
    record=completion.read_sealed_artifact(descriptor,base)
    expected={'candidate_sha256':candidate,'scope_kind':'product','evidence_kind':'qualified_retained_meter_fact','branch_id':branch['id'],
        'native_shape_sha256':branch['shape_sha256'],'assessment_sha256':binding['qualified_runtime_read_attachment']['sha256'],
        'retained_facts':fact['facts'],'relevant_sources':d['sources']}
    if (assessment['archive']!={'artifact':fact['label']+'-original.json.gz','sha256':d['archive_sha256']}
            or assessment['retained_facts']!=fact['facts']or record!=expected or captured['native_call']!=fact['call']
            or (base/assessment['raw']['artifact']).read_bytes()!=fact['read'](profile['raw_path'])
            or assessment['raw']['sha256']!=profile['raw_sha256']):raise ValueError('Exact whole original meter/current replay differs')
    validate_evidence({'gateway':captured['gateway'],'native_call':captured['native_call'],'runtime_read_program':captured,
        'relevant_sources':captured['source_context']['packaged']},binding,branch,'program',base,root,edges)
    return 'passed',None


def write_bundle(output,captures,*,inventory,name_prefix=''):
    contexts={(r['version'],r['host'])for r in inventory['native_coverage']['routes']if r['uri']in URIS}
    if (not isinstance(name_prefix,str)or name_prefix and (len(contexts)!=1
            or name_prefix!='meter-'+'-'.join(next(iter(contexts)))+'-')):
        raise ValueError('Only the closed matching-version-host extra prefix qualifies')
    output=Path(output);output.mkdir(parents=True,exist_ok=False);candidate=inventory['native_coverage']['candidate_sha256']
    index={'contract':'waapi-skill.branch-evidence-index/v1','base':'.','entries':[]};requirements={'contract':'waapi-skill.branch-evidence-requirements/v1','branches':{}};seen=set()
    def write(name,value):return runtime.write_json(output/name,value)
    for number,path in enumerate(captures):
        captured=json.loads(Path(path).read_bytes());native=captured['native_call'];gateway=captured['gateway'];context=_capture(json.dumps(captured),audit.ROOT)
        route,=[r for r in inventory['native_coverage']['routes']if r['uri']==native['uri']and all(r[k]==v for k,v in context.items())]
        public,=[r for r in inventory['routes']if r['id']==route['public_route']];mapped=mappings(inventory,captured,route,seen=seen)
        if not mapped:continue
        prefix=(name_prefix or'meter-')+str(number)+'-';cp=write(prefix+'capture.json',captured)
        program={'candidate_sha256':candidate,'scope_kind':'product','relevant_sources':captured['source_context']['packaged'],'gateway':gateway,'native_call':native,
            'runtime_read_program':captured,'invocation':{'phase':'final','outcome':'PASS','node_outcomes':[{'nodeid':captured['nodeid'],'outcome':'PASS'}]},'branch_assertions':{}}
        bindings={'contract':'waapi-skill.branch-bindings/v1','bindings':{}};policies={'contract':requirements['contract'],'branches':{}}
        for m in mapped:
            b=m['branch'];identity=b['id'];pointer=m['program_pointer'];pp='/gateway/payload/agent_result'
            check=({'pointer':pointer,'absent':True}if b['kind']=='optional_presence'and b['value']=='absent'else
                {'pointer':pointer,'cardinality':b['value']}if b['kind']=='collection_cardinality'and not m.get('normalized_input_choice')else{'pointer':pointer,'equals':completion.pointer_value(program,pointer)})
            program['branch_assertions'][identity]={'native_shape_sha256':b['shape_sha256'],'native_route':route['id'],'checks':[check,{'pointer':pp,'equals':completion.pointer_value(program,pp)}]}
            binding={'branch_id':identity,'native_shape_sha256':b['shape_sha256'],'public_route':public['id'],'public_route_sha256':audit.digest(public),
                'input':{'gateway_argv':gateway['argv'],'selector':pointer},'dispatch_pointer':'/native_call','observation_pointer':pointer,
                'gateway_observation_pointer':pp,'reference_chain':m['reference_chain'],
                **({'normalized_input_choice':m['normalized_input_choice']}if m.get('normalized_input_choice')else{}),'relevant_sources':sorted(captured['source_context']['packaged']),'evidence':{},**_code_bindings(b)}
            validate_evidence(program,binding,b,'program',output,audit.ROOT,{x['id']:x for x in inventory['native_coverage']['obligations']if x['kind']=='reference'})
            bindings['bindings'][identity]=binding;policies['branches'][identity]=remaining.policy(remaining.exact_entry(b));seen.add(identity)
            attach_gate(output,index,candidate,b,cp,prefix)
        pd={**write(prefix+'program.json',program),'nodeid':captured['nodeid']}
        for binding in bindings['bindings'].values():binding['evidence']['program']=pd
        bd=write(prefix+'bindings.json',bindings);rd=write(prefix+'requirements.json',policies)
        index['entries'].append({'id':prefix,'bindings':bd,'origin':{'bindings':bd,'program':{'artifact':prefix+'program.json','sha256':pd['sha256']},'requirements':rd,'capture':cp}})
        requirements['branches'].update(policies['branches'])
    if seen!={b['id']for b in inventory['native_coverage']['obligations']}:raise ValueError('Missing exact meter branches: '+str([b['pointer']for b in inventory['native_coverage']['obligations']if b['id']not in seen]))
    write('requirements.json',requirements);write('index.json',index);return output/'index.json'
