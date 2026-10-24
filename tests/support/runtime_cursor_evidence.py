"""Exact cursor scalars through the existing portable and qualified read seams."""
from functools import lru_cache
import json
from pathlib import Path
import shutil

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support import runtime_observation_evidence as runtime
from tests.support import fixed_runtime_read_evidence as fixed
from tests.support import runtime_remaining_evidence as remaining

URI='ak.wwise.core.profiler.getCursorTime'
SUPPORT='tests/fixtures/runtime-cursor/support-review.json'
SUPPORT_SHA='fd4a459e767aadaceefcff3ef0dc996eb3b1277408dd4f821e45c7ed0e8e67fb'
CONTRACT='waapi-skill.retained-cursor-assessment/v1'


def review(root=audit.ROOT):
    data=remaining._read_pin(root/SUPPORT,SUPPORT_SHA)
    scope=remaining.review(root)
    expected={k:v for k,v in scope['entries'].items()if v['route'].endswith('|'+URI)}
    if len(expected)!=142 or data['entries']!=expected or len(data['profiles'])!=10:
        raise ValueError('Exact142 cursor scope differs')
    if data['policy_sha256']!=remaining.POLICY_SHA:
        raise ValueError('Exact cursor parent policy differs')
    return data


def exact_entry(branch,root):
    entry=remaining.exact_entry(branch,root)
    if branch['id']not in review(root)['entries']:
        raise ValueError('Only exact142 cursor rows qualify')
    return entry


def original_cursor(route,base=None,*,root=audit.ROOT):
    """Retain actual mode, whole original closure and original workflow outcome."""
    data=review(root);p=data['profiles'][route]
    archive_path=root/p['archive_source']if base is None else Path(base)/('cursor-'+p['version']+'-'+p['host']+'-original.json.gz')
    stat=archive_path.stat()
    return _original(route,archive_path,root,(stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns))


@lru_cache(maxsize=64)
def _original(route,archive_path,root,signature):
    import gzip
    data=review(root);p=data['profiles'][route]
    archive={'artifact':archive_path.name,'sha256':p['archive_sha256']}
    read=runtime.archive_reader(archive,archive_path.parent)
    encoded=json.loads(gzip.decompress(archive_path.read_bytes()))['files']
    if len(encoded)!=p['archive_files']or audit.digest(encoded)!=p['archive_map_sha256']:
        raise ValueError('Exact cursor whole archive differs')
    def load(path):return json.loads(read(path))
    report=load(p['report_path']);receipt=p['receipt'];raw=load(p['raw_path']);root_name=p['original_root']
    context=completion.native_host_context(report['host'],'isCommandLine')
    if (context!={k:p[k]for k in ('version','host','build')}or report['candidate']!=p['candidate']
            or runtime.sha(read(p['report_path']))!=p['report_sha256']or runtime.sha(read(p['raw_path']))!=p['raw_sha256']
            or raw['api']!=URI or raw['result']!=p['result']or raw['ok']is not True or raw['dry_run']is not False
            or raw['version']!=p['version']or receipt['exit_code']!=0
            or receipt['argv']!=['core-call',URI,'--profiler-cursor','capture-latest']
            or receipt['payload']['agent_result']!=report['capture_position']
            or report['capture_position']!={'profiler_cursor':'capture-latest','available':True,'position_ms':p['result']['return']}
            or report['cleanup']['complete']is not True or report['cleanup']['errors']!=[]
            or report['fixture_before']!=report['fixture_after']):
        raise ValueError('Exact native cursor request/result/host/source cleanup differs')
    source=data['source_maps'][p['candidate']]['sources']
    if p['host']=='wwise-console':
        if receipt not in report['calls']or report['complete']is not True or report['errors']!=[]:
            raise ValueError('Actual Console cursor receipt missing')
        final=json.loads(read(root_name+'/evidence/category.jsonl').splitlines()[-1])
        if (final['candidate']!=p['candidate']or final['invocation']['phase']!='final'or final['invocation']['outcome']!='PASS'
                or final['source']['hash_before']!=final['source']['hash_after']or final['source']['mtime_before_ns']!=final['source']['mtime_after_ns']
                or final['residual_state']['sandbox']!='deleted'or final['residual_state']['residual_processes']!=[]):
            raise ValueError('Original Console cursor finalization differs')
        original_source=json.loads((root/'tests/fixtures/runtime-console-reads/r125-source-map.json').read_bytes())
        if original_source['candidate']!=p['candidate']or original_source['sources']!=source:
            raise ValueError('Original Console full packaged sources differ')
    else:
        node=load(p['node_path'])
        if receipt not in node['receipts']or node['candidate']!=p['candidate']or any(node['source_context']['sources'].get(k)!=v for k,v in source.items()):
            raise ValueError('Original Authoring cursor receipt/sources differ')
        for group in node['artifacts'].values():
            for item in group['files']:
                body=read(group['path']+'/'+item['path'])
                if len(body)!=item['bytes']or runtime.sha(body)!=item['sha256']:
                    raise ValueError('Complete original cursor node manifest differs')
        rr=load(root_name+'/root-review.json')
        if rr['candidate']!=p['candidate']or rr['source_unchanged']is not True:
            raise ValueError('Original Authoring source preservation missing')
        if p['original_finalization']=='BLOCKED':
            life=load(root_name+'/evidence/lifecycle.json');quarantine=load(root_name+'/evidence/quarantine.json')
            if (life['final_status']!='BLOCKED'or life['errors']!=[]or quarantine['status']!='BLOCKED'or quarantine['never_reuse']is not True
                    or rr['formal_outcome']!='BLOCKED'or rr['lifecycle_errors']!=[]or rr['integrity_errors']!=[]
                    or any(rr[k]is not True for k in ('cleanup_complete','fixture_preserved','post_terminal_port_8080_bindable'))
                    or rr['post_terminal_owned_processes']!=[]):
                raise ValueError('R104 original BLOCKED and physical cleanup facts differ')
        else:
            life=load(root_name+'/evidence/lifecycle-final.json')
            witness=report['outcomes']['profiler-cursor-snap-readback']
            user=p['user_cursor_receipt'];user_raw=load(p['user_cursor_raw_path'])
            if (life['final_status']!='PASS'or life['sandbox_retained']is not False or rr['port_released']is not True
                    or user not in node['receipts']or user['exit_code']!=0 or user_raw['api']!=URI or user_raw['result']!=p['result']
                    or witness['outcome']!='PASS'or witness['evidence']['user_cursor']!=user['payload']['agent_result']
                    or witness['evidence']['snapped_time_ms']!=p['result']['return']or witness['evidence']['transaction']['verified']is not True):
                raise ValueError('R92 original user/snapped cursor witness differs')
        if life['source_hash_before']!=life['source_hash_after']or life['source_mtime_before_ns']!=life['source_mtime_after_ns']:
            raise ValueError('Original Authoring source drift')
    current=runtime.program_source_context(root,flow=URI)['packaged']
    changes={k:{'before':source.get(k),'after':current.get(k)}for k in source.keys()|current.keys()if source.get(k)!=current.get(k)}
    if len(current)!=413 or changes!=data['source_maps'][p['candidate']]['changes']:
        raise ValueError('Exact reviewed cursor source delta differs')
    from wwise_waapi.native_catalog import load_native_catalog
    catalog=load_native_catalog(p['version'],p['host'],root=root/'skills/waapi-skill/resources/native-catalog')
    if catalog['content_sha256']!=p['catalog_sha256']or audit.digest(catalog['schemas'][URI])!=p['schema_sha256']:
        raise ValueError('Exact native cursor meanings/catalog differ')
    return {'result':p['result'],'profile':p,'archive':archive,'read':read,'facts':{
        'original_candidate':p['candidate'],'original_context':context,'original_finalization':p['original_finalization'],
        'actual_cursor':'capture','physical_cleanup_complete':True,'global_pass_transferred':False,
        'continuing_position_verified':False,'capture_completeness_verified':False}}


def code_bindings(branch):
    source='skills/waapi-skill/wwise_waapi/'
    return {key:{'source':source+symbol,'selector':branch['pointer']}for key,symbol in (
        ('construction','runtime_inspection_business.py#materialize_runtime_inspection_business_request'),
        ('validation','builders/schema.py#validate_resolved_semantic_result'),
        ('verifier','runtime_inspection_business.py#normalize_runtime_inspection_result'))}


def _validate_capture(encoded,root):
    cap=json.loads(encoded)
    if cap['source_context']!=remaining._current_context(root,URI,cap['source_context']):
        raise ValueError('Exact cursor source drift')
    return _validate_capture_body(encoded,root)


@lru_cache(maxsize=128)
def _validate_capture_body(encoded,root):
    cap=json.loads(encoded);g=cap['gateway'];n=cap['native_call'];trace=cap['native_reads'];argv=g['argv'];payload=g['payload']
    if (cap['contract']!='waapi-skill.runtime-read-program/v1'or cap['phase_reports']!=dict.fromkeys(('setup','call','teardown'),'passed')
            or cap['source_unchanged']is not True
            or g['exit_code']!=0 or payload.get('ok')is not True or list(payload)[-1]!='agent_result'
            or argv not in [['core-call',URI,'--profiler-cursor',c]for c in ('capture-latest','user-cursor')]
            or cap['public_calls']!=[{'gateway':g,'native_start':0,'native_end':len(trace)}]
            or not 1<=len(trace)<=8 or any(type(x['ordinal'])is not int or x['ordinal']!=i
                or set(x)!={'ordinal','uri','args','options','result'}
                or x['uri']not in {'ak.wwise.core.getInfo',URI}for i,x in enumerate(trace))):
        raise ValueError('Exact public cursor capture/finalization/source differs')
    info,=[x['result']for x in trace if x['uri']=='ak.wwise.core.getInfo'];context=completion.native_host_context(info,'isCommandLine')
    if [{k:x[k]for k in ('uri','args','options','result')}for x in trace if x['uri']==URI]!=[n]:
        raise ValueError('One actual cursor read required')
    from wwise_waapi.runtime_inspection_business import materialize_runtime_inspection_business_request,normalize_runtime_inspection_result
    from wwise_waapi.builders.schema import validate_resolved_semantic_result
    request,limit,business=materialize_runtime_inspection_business_request(URI,context['version'],profiler_cursor=argv[-1],log_channel=None,max_results=None)
    if n!={'uri':URI,'args':request['args'],'options':request['options'],'result':n['result']}:
        raise ValueError('Exact public cursor mode/native request differs')
    validate_resolved_semantic_result(URI,n['result'],version=context['version'])
    projected=normalize_runtime_inspection_result(URI,n['result'],business_request=business,max_results=limit,version=context['version'])
    if payload['agent_result']!=projected or payload['is_command_line']is not (context['host']=='wwise-console'):
        raise ValueError('Exact cursor unavailable/nonnegative-ms projection differs')
    return context


def validate_evidence(record,binding,branch,category,base,root,edges=None):
    exact_entry(branch,root)
    if category!='program':raise ValueError('Cursor native fact requires its closed qualified attachment')
    cap=record['runtime_read_program'];context=_validate_capture(json.dumps(cap),root)
    version,host,build,_,_=branch['route'].split('|')
    if (context!={'version':version,'host':host,'build':build}or record['gateway']!=cap['gateway']or record['native_call']!=cap['native_call']
            or record['relevant_sources']!=cap['source_context']['packaged']or binding['input']['gateway_argv']!=cap['gateway']['argv']
            or any(binding.get(k)!=v for k,v in code_bindings(branch).items())):
        raise ValueError('Exact cursor branch/public/native source context differs')
    pointer=binding['observation_pointer']
    completion.exact_observation_pointer(branch,binding,'/native_call',branch['pointer'].split('/')[1].removesuffix('Schema'),edges or {})
    value=(runtime._CONTRIBUTION_ABSENT if branch['kind']=='optional_presence'and branch['value']=='absent'
           and pointer.rsplit('/',1)[-1]not in completion.pointer_value(record,pointer.rsplit('/',1)[0])
           else completion.pointer_value(record,pointer))
    if not fixed.predicate(branch,fixed.schema_node(branch,root),value,root):
        raise ValueError('Exact cursor branch predicate not observed')


def qualified_result(descriptor,assessment,branch,candidate,scope_kind,base,binding,root,edges):
    entry=exact_entry(branch,root)
    if branch['pointer']!='/resultSchema'or entry['role']!='native_business_anchor'or scope_kind!='product':
        raise ValueError('Only exact cursor same-route result root qualifies')
    original=original_cursor(branch['route'],base,root=root);p=original['profile']
    record=completion.read_sealed_artifact(descriptor,base);cap=completion.read_sealed_artifact(assessment['program_capture'],base)
    expected={'contract':CONTRACT,'branch_id':branch['id'],'profile':p,'support_review':assessment['support_review'],
        'archive':original['archive'],'program_capture':assessment['program_capture'],'facts':original['facts']}
    if (assessment!=expected or assessment['support_review']['sha256']!=SUPPORT_SHA
            or completion.read_sealed_artifact(assessment['support_review'],base)!=review(root)
            or record!={'candidate_sha256':candidate,'scope_kind':'product','evidence_kind':'qualified_retained_cursor_fact',
                'branch_id':branch['id'],'native_shape_sha256':branch['shape_sha256'],'assessment_sha256':binding['qualified_runtime_read_attachment']['sha256'],
                'relevant_sources':review(root)['source_maps'][p['candidate']]['sources'],'retained_facts':original['facts']}
            or cap['native_call']!={'uri':URI,'args':p['native_args'],'options':{},'result':p['result']}):
        raise ValueError('Exact original cursor fact/current same-mode scalar replay differs')
    validate_evidence({'gateway':cap['gateway'],'native_call':cap['native_call'],'runtime_read_program':cap,
        'relevant_sources':cap['source_context']['packaged']},binding,branch,'program',base,root,edges)
    return 'passed',None


def write_cursor_bundle(output,captures,*,inventory):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(audit.ROOT/SUPPORT,output/'cursor-support-review.json')
    candidate=inventory['native_coverage']['candidate_sha256'];seen=set()
    index={'contract':'waapi-skill.branch-evidence-index/v1','base':'.','entries':[],'qualified_runtime_read_attachments':[]}
    requirements={'contract':'waapi-skill.branch-evidence-requirements/v1','branches':{}}
    edges={b['id']:b for b in inventory['native_coverage']['obligations']if b['kind']=='reference'}
    def write(name,value):return runtime.write_json(output/name,value)
    def desc(name):return {'artifact':name,'sha256':runtime.sha((output/name).read_bytes())}
    for number,path in enumerate(captures):
        cap=json.loads(Path(path).read_bytes());context=_validate_capture(json.dumps(cap),audit.ROOT)
        route,=[r for r in inventory['native_coverage']['routes']if r['uri']==URI and all(r[k]==v for k,v in context.items())]
        public,=[r for r in inventory['routes']if r['id']==route['public_route']]
        mappings=[]
        for branch in inventory['native_coverage']['obligations']:
            if branch['id']in seen or branch['route']!=route['id']:continue
            exact_entry(branch,audit.ROOT)
            for chain in runtime._contribution_chains(branch,edges):
                hit=next(((p,v)for p,v in runtime._contribution_occurrences(cap,runtime._contribution_pattern(branch,chain,edges))
                    if fixed.predicate(branch,fixed.schema_node(branch),v)),None)
                if hit:mappings.append((branch,chain,hit[0]));break
        if not mappings:continue
        prefix='cursor-'+str(number)+'-';cp=write(prefix+'capture.json',cap)
        program={'candidate_sha256':candidate,'scope_kind':'product','relevant_sources':cap['source_context']['packaged'],
            'gateway':cap['gateway'],'native_call':cap['native_call'],'runtime_read_program':cap,
            'invocation':{'phase':'final','outcome':'PASS','node_outcomes':[{'nodeid':cap['nodeid'],'outcome':'PASS'}]},'branch_assertions':{}}
        bindings={'contract':'waapi-skill.branch-bindings/v1','bindings':{}};policies={'contract':requirements['contract'],'branches':{}}
        for branch,chain,pointer in mappings:
            identity=branch['id'];entry=exact_entry(branch,audit.ROOT);pp='/gateway/payload/agent_result'
            program['branch_assertions'][identity]={'native_shape_sha256':branch['shape_sha256'],'native_route':branch['route'],
                'checks':[({'pointer':pointer,'absent':True}if branch['kind']=='optional_presence'and branch['value']=='absent'
                    else {'pointer':pointer,'equals':completion.pointer_value(program,pointer)}),{'pointer':pp,'equals':completion.pointer_value(program,pp)}]}
            binding={'branch_id':identity,'native_shape_sha256':branch['shape_sha256'],'public_route':public['id'],'public_route_sha256':audit.digest(public),
                'input':{'gateway_argv':cap['gateway']['argv'],'selector':pointer},'dispatch_pointer':'/native_call','observation_pointer':pointer,
                'gateway_observation_pointer':pp,'reference_chain':chain,'relevant_sources':sorted(cap['source_context']['packaged']),'evidence':{},**code_bindings(branch)}
            validate_evidence(program,binding,branch,'program',output,audit.ROOT,edges)
            bindings['bindings'][identity]=binding;policies['branches'][identity]=remaining.policy(entry);seen.add(identity)
            if entry['role']=='native_business_anchor':
                original=original_cursor(route['id']);p=original['profile']
                if cap['native_call']!={'uri':URI,'args':p['native_args'],'options':{},'result':p['result']}:
                    raise ValueError('Cursor native root requires actual original mode/scalar replay first')
                name='cursor-'+p['version']+'-'+p['host']+'-original.json.gz';shutil.copyfile(audit.ROOT/p['archive_source'],output/name)
                assessment=write(prefix+'assessment.json',{'contract':CONTRACT,'branch_id':identity,'profile':p,'support_review':desc('cursor-support-review.json'),
                    'archive':desc(name),'program_capture':cp,'facts':original['facts']})
                evidence=write(prefix+'qualified.json',{'candidate_sha256':candidate,'scope_kind':'product','evidence_kind':'qualified_retained_cursor_fact',
                    'branch_id':identity,'native_shape_sha256':branch['shape_sha256'],'assessment_sha256':assessment['sha256'],
                    'relevant_sources':review()['source_maps'][p['candidate']]['sources'],'retained_facts':original['facts']})
                index['qualified_runtime_read_attachments'].append(write(prefix+'attachment.json',{'contract':'waapi-skill.qualified-retained-read-attachment/v1',
                    'branch_id':identity,'assessment':assessment,'evidence':evidence}))
        pd={**write(prefix+'program.json',program),'nodeid':cap['nodeid']}
        for b in bindings['bindings'].values():b['evidence']['program']=pd
        bd=write(prefix+'bindings.json',bindings);rd=write(prefix+'requirements.json',policies)
        index['entries'].append({'id':prefix,'bindings':bd,'origin':{'bindings':bd,'program':desc(prefix+'program.json'),'requirements':rd,'capture':cp}})
        requirements['branches'].update(policies['branches'])
    if seen!={b['id']for b in inventory['native_coverage']['obligations']}:
        raise ValueError('Missing exact cursor branch occurrences: '+str(set(b['id']for b in inventory['native_coverage']['obligations'])-seen))
    write('requirements.json',requirements);write('index.json',index)
    return output/'index.json'
