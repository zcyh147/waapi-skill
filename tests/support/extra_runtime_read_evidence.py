"""Exact CPU/performance/streaming facts behind the ordinary evidence consumer.

The eighteen same-host/build roots attest native availability and nonempty data.
All optional diagnostics stay opaque; the current public replay owns construction,
complete pagination and faithful preservation. Original R104 BLOCKED stays BLOCKED.
"""
from copy import deepcopy
from functools import lru_cache
import gzip
import json
from pathlib import Path
import shutil
import subprocess

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support import runtime_observation_evidence as runtime
from tests.support import runtime_remaining_evidence as remaining
from tests.support import fixed_runtime_read_evidence as fixed

URIS=frozenset('ak.wwise.core.profiler.'+n for n in ('getCpuUsage','getPerformanceMonitor','getStreamedMedia'))
SUPPORT='tests/fixtures/runtime-extra-reads/support-review.json'
SUPPORT_SHA = '3ab3b25f660dc4bd6eb9b7967b9449ff71067ae3a56e6a2a276b9a1e68059009'
CONTRACT='waapi-skill.extra-runtime-read-assessment/v1'


def review(root=audit.ROOT):
    document=remaining._read_pin(root/SUPPORT,SUPPORT_SHA)
    entries=remaining.review(root)['entries']
    expected={k:v for k,v in entries.items()if v['family']=='extra_reads'and v['route'].split('|')[-1]in URIS}
    if document['entries']!=expected or len(expected)!=654 or len(document['profiles'])!=18:
        raise ValueError('Exact654 diagnostic scope differs')
    for identity,profile in document['profiles'].items():
        entry=expected[identity]
        if (entry['role']!='native_business_anchor'or profile['route']!=entry['route']
                or profile['native_shape_sha256']!=entry['native_shape_sha256']or not identity.endswith('|/resultSchema')):
            raise ValueError('Exact diagnostic native roots differ')
    return document


@lru_cache(maxsize=8)
def _historical(root,candidate,sources_json):
    sources=json.loads(sources_json)
    names=subprocess.check_output(['git','ls-tree','-r','--name-only',candidate,'--','skills/waapi-skill'],cwd=root,text=True).splitlines()
    if set(names)!=set(sources)or completion.historical_source_seals(root,candidate,sources)!=sources:
        raise ValueError('Complete original diagnostic packaged sources differ')


def original(identity,base=None,*,root=audit.ROOT):
    support=review(root);profile=support['profiles'][identity];label=profile['provider'];d=support['providers'][label]
    archive_path=root/d['archive_source']if base is None else Path(base)/(label+'-original.json.gz')
    archive={'artifact':archive_path.name,'sha256':d['archive_sha256']};read=runtime.archive_reader(archive,archive_path.parent)
    files=json.loads(gzip.decompress(archive_path.read_bytes()))['files']
    if len(files)!=d['archive_files']or audit.digest(files)!=d['archive_map_sha256']:
        raise ValueError('Whole original diagnostic closure differs')
    raw=read(d['capture_path']);capture=json.loads(raw);host=completion.native_host_context(capture['host'],'isCommandLine')
    if (runtime.sha(raw)!=d['capture_sha256']or capture['candidate']!=d['candidate']
            or host!={k:d[k]for k in ('version','host','build')}
            or capture['fixture_before']!=capture['fixture_after']or capture['cleanup']['complete']is not True
            or capture['cleanup']['errors']!=[]):raise ValueError('Original diagnostic host/source/cleanup differs')
    _historical(root,d['candidate'],json.dumps(d['sources'],sort_keys=True))
    current=runtime.original_runtime_source_context(root,flow=profile['request']['api'])['packaged'];sources=d['sources']
    changes={p:{'before':sources.get(p),'after':current.get(p)}for p in sources.keys()|current.keys()if sources.get(p)!=current.get(p)}
    if len(current)!=413 or changes!=d['source_changes']:raise ValueError('Exact diagnostic source bridge differs')
    if d['host']=='wwise-console':
        category=json.loads(read(d['original_root']+'/evidence/category.jsonl').splitlines()[-1]);inv=category['invocation']
        if (category['candidate']!=d['candidate']or inv['phase']!='final'or inv['outcome']!='PASS'
                or category['source']['hash_before']!=category['source']['hash_after']
                or category['source']['mtime_before_ns']!=category['source']['mtime_after_ns']
                or category['residual_state']['process_cleanup']!='cleaned'or category['residual_state']['sandbox']!='deleted'
                or category['residual_state']['residual_processes']!=[]):raise ValueError('Original Console finalized source/cleanup missing')
        outcome=capture['outcomes'][profile['reader']]
    else:
        root_review=json.loads(read(d['original_root']+'/root-review.json'))
        life=json.loads(read(d['original_root']+'/evidence/lifecycle.json'));quarantine=json.loads(read(d['original_root']+'/evidence/quarantine.json'))
        node_path=d['capture_path'].split('-native-evidence/')[0]+'.json';node=json.loads(read(node_path))
        for group in node['artifacts'].values():
            for item in group['files']:
                body=read(group['path']+'/'+item['path'])
                if runtime.sha(body)!=item['sha256']or len(body)!=item['bytes']:raise ValueError('Original complete node manifest differs')
        if (node['candidate']!=d['candidate']or any(node['source_context']['sources'].get(p)!=v for p,v in sources.items())
                or root_review['candidate']!=d['candidate']or root_review['source_unchanged']is not True
                or root_review['formal_outcome']!='BLOCKED'or root_review['integrity_errors']!=[]or root_review['lifecycle_errors']!=[]
                or root_review['post_terminal_owned_processes']!=[]
                or any(root_review[k]is not True for k in ('cleanup_complete','fixture_preserved','post_terminal_port_8080_bindable'))
                or life['final_status']!='BLOCKED'or life['errors']!=[]or life['sandbox_retained']is not True
                or life['source_hash_before']!=life['source_hash_after']or life['source_mtime_before_ns']!=life['source_mtime_after_ns']
                or quarantine['status']!='BLOCKED'or quarantine['never_reuse']is not True):raise ValueError('Original R104 BLOCKED/cleanup/source facts must remain')
        name={'cpu':'cpu','performance':'performance','streamed_media':'streamed-media'}[profile['reader']]
        outcome=capture['outcomes']['profiler-'+name+'-observation']
    body=read(profile['raw_path']);native=json.loads(body);issuer_raw=read(profile['issuer_path']);issuer=json.loads(issuer_raw)
    rows=native['result']['return'];request=profile['request'];live=issuer['context']['live'];actual=capture['host']
    if (runtime.sha(body)!=profile['raw_sha256']or runtime.sha(issuer_raw)!=profile['issuer_sha256']
            or native['api']!=request['api']or native['version']!=d['version']or native['ok']is not True or native['dry_run']is not False
            or len(rows)!=profile['native_rows']or not rows or outcome['outcome']!=profile['original_reader_outcome']
            or issuer['sha256']!=audit.digest({k:v for k,v in issuer.items()if k!='sha256'})
            or issuer['plan']['request']!=request or issuer['plan']['result']['return']!=rows
            or issuer['plan']['result']['returned_count']!=len(rows)or issuer['plan']['result']['truncated']is not False
            or any(live[k]!=actual[k]for k in ('processId','sessionId','version'))
            or request['args']!={'time':capture['capture_position']['position_ms']}or request['options']!={}):
        raise ValueError('Exact original complete diagnostic native array/issuer/request differs')
    from wwise_waapi.builders.schema import validate_resolved_semantic_result
    validate_resolved_semantic_result(request['api'],native['result'],version=d['version'])
    e=outcome['evidence']
    if e['complete']is not profile['original_public_complete']or e['position_ms']!=request['args']['time']or e['nonempty']is not True:
        raise ValueError('Original public completeness/partiality facts differ')
    if d['host']=='wwise-console'and (e['retained_rows']!=rows or e['agent_result_pages'][-1]['complete']is not True):
        raise ValueError('Original Console complete public diagnostic array differs')
    facts={'original_finalization':'PASS'if d['host']=='wwise-console'else'BLOCKED',
        'original_reader_outcome':profile['original_reader_outcome'],'original_public_complete':profile['original_public_complete'],
        'native_nonempty_rows':len(rows),'physical_cleanup_complete':True,'global_pass_transferred':False}
    return dict(descriptor=d,profile=profile,label=label,read=read,native=native,call={'uri':request['api'],'args':request['args'],'options':request['options'],'result':native['result']},facts=facts)


def original_call(identity,*,root=audit.ROOT):return original(identity,root=root)['call']


@lru_cache(maxsize=256)
def _capture(captured_json,root):
    from wwise_waapi.builders.schema import validate_resolved_semantic_result
    from wwise_waapi.runtime_inspection_business import materialize_runtime_inspection_business_request,normalize_runtime_inspection_result
    c=json.loads(captured_json);g=c['gateway'];native=c['native_call'];uri=native['uri'];trace=c['native_reads'];calls=c['public_calls'];p=g['payload']
    if (uri not in URIS or c['contract']!='waapi-skill.runtime-read-program/v1'or c['phase_reports']!=dict.fromkeys(('setup','call','teardown'),'passed')
            or c['source_unchanged']is not True or c['source_context']!=runtime.program_source_context(root,flow=uri)
            or g['exit_code']!=0 or p.get('ok')is not True or not 1<=len(trace)<=128 or not 1<=len(calls)<=128
            or any(set(r)!={'ordinal','uri','args','options','result'}or type(r['ordinal'])is not int or r['ordinal']!=i for i,r in enumerate(trace))
            or any(r['uri']not in {uri,'ak.wwise.core.getInfo','ak.wwise.core.getProjectInfo','ak.wwise.core.profiler.getCursorTime'}for r in trace)):
        raise ValueError('Exact diagnostic current public phases/source/finite trace required')
    info,=[r['result']for r in trace if r['uri']=='ak.wwise.core.getInfo'];context=completion.native_host_context(info,'isCommandLine');version=context['version']
    target,=[r for r in trace if r['uri']==uri]
    if ({k:target[k]for k in ('uri','args','options','result')}!=native or p.get('is_command_line')is not (context['host']=='wwise-console')
            or any(p['schema_validation'][s]['version']!=version for s in ('request','result'))):raise ValueError('Exact diagnostic live host/native call differs')
    argv=g['argv']
    if len(argv)!=6 or argv[:2]!=['core-call',uri]or argv[2]!='--profiler-position'or argv[4:]!=['--max-results','64']:
        raise ValueError('Exact controlled public diagnostic input required')
    position=argv[3];request,_,business=materialize_runtime_inspection_business_request(uri,version,profiler_position=position,max_results=64,log_channel=None)
    cursors=[r for r in trace if r['uri'].endswith('.getCursorTime')]
    if position in {'capture-latest','user-cursor'}:
        cursor,=cursors
        if (cursor['args']!={'cursor':{'capture-latest':'capture','user-cursor':'user'}[position]}or cursor['options']!={}
                or cursor['ordinal']>=target['ordinal']or set(cursor['result'])!={'return'}or type(cursor['result']['return'])is not int or cursor['result']['return']<0):raise ValueError('Exact frozen native cursor resolution required')
        request['args']['time']=cursor['result']['return']
    elif cursors:raise ValueError('Numeric position must not query a cursor')
    if ({'api':uri,'args':native['args'],'options':native['options']}!=request or type(native['args'].get('time'))is not int or native['args']['time']<0
            or p['business_request']!={'operation':uri,**business,'max_results':64}):raise ValueError('Exact diagnostic public compiler result differs')
    validate_resolved_semantic_result(uri,native['result'],version=version)
    expected=normalize_runtime_inspection_result(uri,native['result'],business_request=business,max_results=max(1,len(native['result']['return'])))
    snapshot=audit.digest(expected);rows=[];previous=None;offset=0
    for i,call in enumerate(calls):
        page=call['gateway'];payload=page['payload'];result=payload['agent_result']
        if (set(call)!={'gateway','native_start','native_end'}or call['native_start']!=(0 if i==0 else len(trace))or call['native_end']!=len(trace)
                or (page!=g if i==0 else page['argv']!=previous['next_command']['full_argv'][3:])or page['exit_code']!=0 or payload['ok']is not True
                or list(payload)[-1]!='agent_result'or result['profiler_position']!=position or result['total_count']!=len(native['result']['return'])
                or result['returned_count']!=len(result['return'])or result['complete']is not (i==len(calls)-1)
                or result['snapshot_sha256']!=snapshot or result['instantaneous_native_resource_authority']is not False
                or result['observation']!='retained_profiler_capture_snapshot'
                or result['page']!={'offset_from_end':offset,'next_offset_from_end':offset+len(result['return']),'order':'newest_range_first_native_order_within_range'}
                or result['truncated']is not (i<len(calls)-1)or result['expires_at']!=p['agent_result']['expires_at']):
            raise ValueError('Exact public issued diagnostic pages/spans/order required')
        rows=result['return']+rows;offset+=len(result['return']);previous=result
    if rows!=native['result']['return']:raise ValueError('Whole native diagnostic array must survive public pagination')
    return context


@lru_cache(maxsize=4096)
def _node(root,route,pointer):
    for marker in ('/@boolean/','/@nullable','/@presence/','/@cardinality/','/@empty/'):pointer=pointer.split(marker)[0]
    catalog=remaining._log_catalog(root,*route.split('|')[:2]);uri=route.split('|')[-1]
    if '/@definition/'in pointer:
        section,rest=pointer.split('/@definition/',1);name,_,suffix=rest.partition('/')
        context=catalog['schemas'][uri][section.strip('/')]if name=='<schema>'else catalog['definitions']['documents'][name]
        return completion.pointer_value(context,'/'+suffix if suffix else'')
    return completion.pointer_value(catalog['schemas'][uri],pointer)


def predicate(branch,value,root):
    node=_node(root,branch['route'],branch['pointer']);kind=branch['kind']
    if kind not in {'schema','reference'}:return fixed.predicate(branch,node,value,root)
    if value is runtime._CONTRIBUTION_ABSENT:return False
    pointer=branch['pointer'].rsplit('/',1)[0]if kind=='reference'else branch['pointer']
    if type(node)is bool:pointer=pointer.rsplit('/',1)[0]
    parent={**branch,'pointer':pointer,'shape_sha256':audit.digest(_node(root,branch['route'],pointer))}
    try:completion.validate_native_alternative(root,parent,value)
    except (ValueError,TypeError):return False
    return True


def _effective(branch,root):
    # Local declaration rows and resolved reference aliases retain distinct IDs.
    # They describe the identical pinned node, reached through the real item ref.
    for name in ('definitions','localDefinitions'):
        prefix='/resultSchema/'+name+'/'
        if branch['pointer'].startswith(prefix):
            pointer=branch['pointer'].replace('/resultSchema/','/resultSchema/@definition/<schema>/',1)
            if _node(root,branch['route'],pointer)!=_node(root,branch['route'],branch['pointer']):
                raise ValueError('Local diagnostic declaration/reference alias differs')
            return {**branch,'pointer':pointer}
    return branch


def mappings(inventory,captured,route):
    branches=[b for b in inventory['native_coverage']['obligations']if b['route']==route['id']];edges={b['id']:b for b in branches if b['kind']=='reference'};found=[]
    for branch in branches:
        if branch['pointer']in runtime.CONTRIBUTION_CURSOR_POINTERS:
            cursors=[r for r in captured['native_reads']if r['uri'].endswith('.getCursorTime')]
            if cursors and predicate(branch,cursors[0]['args']['cursor'],audit.ROOT):
                found.append({'branch':branch,'program_pointer':f"/runtime_read_program/native_reads/{cursors[0]['ordinal']}/args/cursor",'reference_chain':runtime._contribution_chains(branch,edges)[0]})
            continue
        effective=_effective(branch,audit.ROOT)
        for chain in runtime._contribution_chains(effective,edges):
            hit=next(((p,v)for p,v in runtime._contribution_occurrences(captured,runtime._contribution_pattern(effective,chain,edges))if predicate(branch,v,audit.ROOT)),None)
            if hit:
                found.append({'branch':branch,'program_pointer':hit[0],'reference_chain':chain});break
    return found


def validate_evidence(record,binding,branch,category,base,root,edges=None):
    remaining.exact_entry(branch,root)
    if category!='program':raise ValueError('Diagnostic native roots require their qualified attachment')
    c=record['runtime_read_program'];g=record['gateway'];native=record['native_call'];version,host,build,_,uri=branch['route'].split('|')
    if (g!=c['gateway']or native!=c['native_call']or g['argv']!=binding['input']['gateway_argv']or record['relevant_sources']!=c['source_context']['packaged']
            or _capture(json.dumps(c),root)!={'version':version,'host':host,'build':build}
            or any(binding.get(k)!=v for k,v in _code_bindings(branch).items())):raise ValueError('Exact diagnostic public source/binding/host differs')
    pointer=binding['observation_pointer']
    if branch['pointer']in runtime.CONTRIBUTION_CURSOR_POINTERS:
        completion.exact_observation_pointer(branch,{**binding,'observation_pointer':'/native_call/args/time'},'/native_call','args',edges or {})
        cursor,=[r for r in c['native_reads']if r['uri'].endswith('.getCursorTime')]
        expected=f"/runtime_read_program/native_reads/{cursor['ordinal']}/args/cursor"
        if pointer!=expected or not predicate(branch,cursor['args']['cursor'],root):raise ValueError('Exact public named cursor branch differs')
        return {'observation_pointer':expected}
    effective=_effective(branch,root)
    completion.exact_observation_pointer(effective,binding,'/native_call',branch['pointer'].split('/')[1].removesuffix('Schema'),edges or {})
    if not predicate(branch,remaining._occurrence_value(record,pointer,branch),root):raise ValueError('Exact diagnostic branch predicate failed')
    if effective!=branch:return {'observation_pointer':pointer}


def _code_bindings(branch):
    validation='validate_resolved_semantic_result'if branch['pointer'].startswith('/resultSchema')else'validate_semantic_payload'
    return {k:{'source':source,'selector':branch['pointer']}for k,source in (
        ('construction','skills/waapi-skill/wwise_waapi/runtime_inspection_business.py#materialize_runtime_inspection_business_request'),
        ('validation','skills/waapi-skill/wwise_waapi/builders/schema.py#'+validation),
        ('verifier','skills/waapi-skill/wwise_waapi/runtime_inspection_business.py#normalize_runtime_inspection_result'))}


def attach_gate(output,index,candidate,branch,cp,prefix):
    if branch['id']not in review()['profiles']:return
    original_fact=original(branch['id']);captured=completion.read_sealed_artifact(cp,output)
    if captured['native_call']!=original_fact['call']:return
    d=original_fact['descriptor'];label=original_fact['label']
    shutil.copyfile(audit.ROOT/d['archive_source'],output/(label+'-original.json.gz'));shutil.copyfile(audit.ROOT/SUPPORT,output/'extra-support.json')
    def write(name,value):return runtime.write_json(output/name,value)
    def desc(name):return {'artifact':name,'sha256':runtime.sha((output/name).read_bytes())}
    raw_name=prefix+'raw.json';(output/raw_name).write_bytes(original_fact['read'](original_fact['profile']['raw_path']))
    assessment=write(prefix+'assessment.json',{'contract':CONTRACT,'branch_id':branch['id'],'profile':original_fact['profile'],
        'source_review':desc('extra-support.json'),'archive':desc(label+'-original.json.gz'),'raw':desc(raw_name),'program_capture':cp,'retained_facts':original_fact['facts']})
    evidence=write(prefix+'qualified.json',{'candidate_sha256':candidate,'scope_kind':'product','evidence_kind':'qualified_retained_diagnostic_fact',
        'branch_id':branch['id'],'native_shape_sha256':branch['shape_sha256'],'assessment_sha256':assessment['sha256'],
        'retained_facts':original_fact['facts'],'relevant_sources':d['sources']})
    index.setdefault('qualified_runtime_read_attachments',[]).append(write(prefix+'attachment.json',
        {'contract':'waapi-skill.qualified-retained-read-attachment/v1','branch_id':branch['id'],'assessment':assessment,'evidence':evidence}))


def qualified_result(descriptor,assessment,branch,candidate,scope_kind,base,binding,root,edges):
    remaining.exact_entry(branch,root);profile=review(root)['profiles'].get(branch['id'])
    if (profile is None or assessment['contract']!=CONTRACT or assessment['branch_id']!=branch['id']or assessment['profile']!=profile
            or scope_kind!='product'or False
            or not runtime.qualified_source_review_matches(assessment['source_review'],SUPPORT_SHA,review(root),base)):raise ValueError('Only exact eighteen diagnostic roots qualify')
    fact=original(branch['id'],base,root=root);d=fact['descriptor'];captured=completion.read_sealed_artifact(assessment['program_capture'],base)
    record=completion.read_sealed_artifact(descriptor,base)
    expected={'candidate_sha256':candidate,'scope_kind':'product','evidence_kind':'qualified_retained_diagnostic_fact','branch_id':branch['id'],
        'native_shape_sha256':branch['shape_sha256'],'assessment_sha256':binding['qualified_runtime_read_attachment']['sha256'],
        'retained_facts':fact['facts'],'relevant_sources':d['sources']}
    if (assessment['archive']!={'artifact':fact['label']+'-original.json.gz','sha256':d['archive_sha256']}
            or assessment['retained_facts']!=fact['facts']or record!=expected or captured['native_call']!=fact['call']
            or (base/assessment['raw']['artifact']).read_bytes()!=fact['read'](profile['raw_path'])
            or assessment['raw']['sha256']!=profile['raw_sha256']):raise ValueError('Exact whole original diagnostic/current replay differs')
    if runtime.retained_qualified_capture(captured):
        return 'passed',None
    validate_evidence({'gateway':captured['gateway'],'native_call':captured['native_call'],'runtime_read_program':captured,
        'relevant_sources':captured['source_context']['packaged']},binding,branch,'program',base,root,edges)
    return 'passed',None


def write_bundle(output,captures,*,inventory,name_prefix='',retained_native=()):
    if retained_native:
        if captures:
            raise ValueError('Native-only conversion does not accept current program captures')
        from tests.support.qualified_runtime_read_evidence import write_selected_native_bundle
        return write_selected_native_bundle(output, inventory, retained_native, family=__name__)
    contexts={(r['version'],r['host'])for r in inventory['native_coverage']['routes']if r['uri']in URIS}
    if (not isinstance(name_prefix,str)or name_prefix and (len(contexts)!=1
            or name_prefix!='extra-'+'-'.join(next(iter(contexts)))+'-')):
        raise ValueError('Only the closed matching-version-host extra prefix qualifies')
    output=Path(output);output.mkdir(parents=True,exist_ok=False);candidate=inventory['native_coverage']['candidate_sha256']
    index={'contract':'waapi-skill.branch-evidence-index/v1','base':'.','entries':[]};requirements={'contract':'waapi-skill.branch-evidence-requirements/v1','branches':{}};seen=set()
    def write(name,value):return runtime.write_json(output/name,value)
    for number,path in enumerate(captures):
        captured=json.loads(Path(path).read_bytes());native=captured['native_call'];gateway=captured['gateway'];context=_capture(json.dumps(captured),audit.ROOT)
        route,=[r for r in inventory['native_coverage']['routes']if r['uri']==native['uri']and all(r[k]==v for k,v in context.items())]
        public,=[r for r in inventory['routes']if r['id']==route['public_route']];mapped=[m for m in mappings(inventory,captured,route)if m['branch']['id']not in seen]
        if not mapped:continue
        prefix=(name_prefix or'extra-')+str(number)+'-';cp=write(prefix+'capture.json',captured)
        program={'candidate_sha256':candidate,'scope_kind':'product','relevant_sources':captured['source_context']['packaged'],'gateway':gateway,'native_call':native,
            'runtime_read_program':captured,'invocation':{'phase':'final','outcome':'PASS','node_outcomes':[{'nodeid':captured['nodeid'],'outcome':'PASS'}]},'branch_assertions':{}}
        bindings={'contract':'waapi-skill.branch-bindings/v1','bindings':{}};policies={'contract':requirements['contract'],'branches':{}}
        for m in mapped:
            b=m['branch'];identity=b['id'];pointer=m['program_pointer'];pp='/gateway/payload/agent_result'
            check=({'pointer':pointer,'absent':True}if b['kind']=='optional_presence'and b['value']=='absent'else
                {'pointer':pointer,'cardinality':b['value']}if b['kind']=='collection_cardinality'else{'pointer':pointer,'equals':completion.pointer_value(program,pointer)})
            program['branch_assertions'][identity]={'native_shape_sha256':b['shape_sha256'],'native_route':route['id'],'checks':[check,{'pointer':pp,'equals':completion.pointer_value(program,pp)}]}
            binding={'branch_id':identity,'native_shape_sha256':b['shape_sha256'],'public_route':public['id'],'public_route_sha256':audit.digest(public),
                'input':{'gateway_argv':gateway['argv'],'selector':pointer},'dispatch_pointer':'/native_call','observation_pointer':pointer,
                'gateway_observation_pointer':pp,'reference_chain':m['reference_chain'],'relevant_sources':sorted(captured['source_context']['packaged']),'evidence':{},**_code_bindings(b)}
            validate_evidence(program,binding,b,'program',output,audit.ROOT,{x['id']:x for x in inventory['native_coverage']['obligations']if x['kind']=='reference'})
            bindings['bindings'][identity]=binding;policies['branches'][identity]=remaining.policy(remaining.exact_entry(b));seen.add(identity)
            attach_gate(output,index,candidate,b,cp,prefix)
        pd={**write(prefix+'program.json',program),'nodeid':captured['nodeid']}
        for binding in bindings['bindings'].values():binding['evidence']['program']=pd
        bd=write(prefix+'bindings.json',bindings);rd=write(prefix+'requirements.json',policies)
        index['entries'].append({'id':prefix,'bindings':bd,'origin':{'bindings':bd,'program':{'artifact':prefix+'program.json','sha256':pd['sha256']},'requirements':rd,'capture':cp}})
        requirements['branches'].update(policies['branches'])
    if seen!={b['id']for b in inventory['native_coverage']['obligations']}:raise ValueError('Missing exact diagnostic branches: '+str([b['pointer']for b in inventory['native_coverage']['obligations']if b['id']not in seen]))
    write('requirements.json',requirements);write('index.json',index);return output/'index.json'
