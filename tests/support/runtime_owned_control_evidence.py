"""Exact owned control evidence behind the existing remaining-policy consumer."""
from functools import lru_cache
import json
from pathlib import Path
import shutil

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support import runtime_observation_evidence as runtime
from tests.support import runtime_remaining_evidence as remaining
from tests.support import runtime_cursor_evidence as cursor
from tests.support import fixed_runtime_read_evidence as fixed

PREFIX='ak.wwise.core.profiler.'
METER_URIS=frozenset(PREFIX+n for n in ('registerMeter','unregisterMeter'))
URIS=METER_URIS|{PREFIX+n for n in ('saveCapture','moveCursor','setCursorTime')}
SUPPORT='tests/fixtures/runtime-owned-controls/support-review.json'
SUPPORT_SHA='3baf25bc05531e013c03c7523986461bd79220929e77d8ea97ec67c42c98f198'
CONTRACT='waapi-skill.retained-owned-control-assessment/v1'


def review(root=audit.ROOT):
    data=remaining._read_pin(root/SUPPORT,SUPPORT_SHA)
    expected={k:v for k,v in remaining.review(root)['entries'].items()if v['route'].split('|')[-1]in URIS}
    if (len(expected)!=298 or data['entries']!=expected or data['policy_sha256']!=remaining.POLICY_SHA
            or data['cursor_support_sha256']!=cursor.SUPPORT_SHA or len(data['meter_normalized_inputs'])!=64):
        raise ValueError('Exact298 owned controls/source policy differs')
    if 'meter_support_sha256'in data:
        from tests.support import meter_runtime_read_evidence as meter
        if data['meter_support_sha256']!=meter.SUPPORT_SHA:raise ValueError('Exact shared meter original provider differs')
    return data


def exact_entry(branch,root=audit.ROOT):
    entry=remaining.exact_entry(branch,root)
    if branch['id']not in review(root)['entries']:raise ValueError('Only exact298 owned controls qualify')
    return entry


def original_meter(route,base=None,*,root=audit.ROOT):
    p=review(root)['profiles'].get(route)
    if p is None or p['provider']not in {'r92','r93'}:raise ValueError('No exact retained native meter ACK for this route')
    if p['provider']=='r93':
        if route.rsplit('|',1)[0]!='2024.1|wwise-authoring|2024.1.13.9056|function':raise ValueError('Only exact Authoring2024 registration pair uses R93')
        from tests.support.meter_runtime_read_evidence import original_profile
        shared=original_profile('2024.1',base,root=root);d=shared['descriptor'];cp={'node_path':d['node_path'],'version':'2024.1'};read=shared['read']
        original={'profile':cp,'read':read,'archive':{'artifact':shared['label']+'-original.json.gz','sha256':d['archive_sha256']},
            'sources':shared['sources'],'archive_source':d['archive_source'],'archive_name':shared['label']+'-original.json.gz',
            'facts':{'original_candidate':d['candidate'],'original_context':{k:d[k]for k in ('version','host','build')},
                'original_finalization':'PASS','physical_cleanup_complete':True,'global_pass_transferred':False}}
        rows=[]
        for group in shared['node']['artifacts'].values():
            for item in group['files']:
                if item['path'].endswith('-ak_wwise_core_object_get.json'):
                    raw=json.loads(read(group['path']+'/'+item['path']))
                    rows.extend(row for row in raw['result'].get('return',[])if row.get('id')==p['object']['id']and all(k in row for k in p['object']))
        if not rows or any(any(row[k]!=v for k,v in p['object'].items())for row in rows):raise ValueError('R93 actual owned object identity/type/path differs')
    else:
        original=cursor.original_cursor(p['cursor_route'],base,root=root);cp=original['profile'];read=original['read']
    node=json.loads(read(cp['node_path']));calls=node['receipts'];chain=[calls[i]for i in p['receipt_indices']]
    preview,shown,confirmed,executed,verified=chain;payload=verified['payload'];native=json.loads(read(p['raw_path']));request=p['request'];uri=route.split('|')[-1]
    if (audit.digest(chain)!=p['receipt_sha256']or runtime.sha(read(p['raw_path']))!=p['raw_sha256']
            or any(c['exit_code']!=0 or c['payload'].get('ok')is not True for c in chain)
            or native['ok']is not True or native['dry_run']is not False or native['api']!=uri or native['version']!=cp['version']
            or native['result']!=p['result']or request!={'api':uri,'args':{'object':p['object']['id']},'options':{}}
            or shown['argv']not in [preview['payload']['next_command']['gateway_argv'],['transaction-show',preview['payload']['transaction_id']]]
            or confirmed['argv']!=shown['payload']['next_command']['gateway_argv']
            or executed['argv']!=['execute',preview['payload']['transaction_id']]or verified['argv']!=executed['payload']['next_command']['gateway_argv']
            or any(c['payload']['artifact_hash']!=preview['payload']['artifact_hash']for c in chain)
            or executed['payload']['dispatch_result']['api']!=uri
            or Path(executed['payload']['dispatch_result']['evidence_path']).name!=Path(p['raw_path']).name
            or payload['agent_result']['request']['arguments']!=request or payload['agent_result']['result']!=p['result']
            or payload['automatic_retry']is not False or payload['state']!='result_schema_checked'or payload['verified']is not False
            or payload['verification']['business_state_verified']is not False):
        raise ValueError('Exact original meter object/authorization/ACK differs')
    # Check both actual acknowledged members of the same owned registration pair.
    other=PREFIX+('unregisterMeter'if uri.endswith('.registerMeter')else'registerMeter')
    paired=review(root)['profiles'][route.rsplit('|',1)[0]+'|'+other]
    last=calls[paired['receipt_indices'][-1]]['payload']
    if paired.get('cursor_route')!=p.get('cursor_route')or paired['provider']!=p['provider']or paired['object']!=p['object']or last['state']!='result_schema_checked'or last['verified']is not False:
        raise ValueError('Same-object balanced native registration pair missing')
    return {**{k:original[k]for k in ('sources','archive_source','archive_name')if k in original},'object':p['object'],'profile':p,'archive':original['archive'],'read':read,
        'facts':{**original['facts'],'actual_control':uri,'bound_object':p['object'],'verification':'result_schema_checked',
            'business_state_verified':False,'registration_membership_verified':False,'reference_count_verified':False,'prior_settings_restoration_verified':False}}


def code_bindings(branch):
    return {key:{'source':'skills/waapi-skill/wwise_waapi/'+symbol,'selector':branch['pointer']}for key,symbol in (
        ('construction','runtime_inspection_business.py#materialize_runtime_control_business_request'),
        ('validation','builders/schema.py#validate_resolved_semantic_result'),('verifier','profiler_capture_artifact.py#verify_capture_artifact'if branch['route'].endswith('.saveCapture')else'operation_registry.py#verify_prepared_operation'))}


def _capture(encoded,root):
    cap=json.loads(encoded);uri=cap['native_call']['uri']
    if cap['source_context']!=remaining._current_context(root,uri,cap['source_context']):raise ValueError('Owned control capture sources changed')
    if uri in METER_URIS:return _meter_capture(encoded,root)
    if uri==PREFIX+'saveCapture':return _save_capture(encoded,root)
    if uri in {PREFIX+'moveCursor',PREFIX+'setCursorTime'}:return _cursor_capture(encoded,root)
    raise ValueError('Owned control family mapper not implemented')


def _require_execute_mutations(calls,trace,expected):
    uris={mutation['uri']for mutation in expected.values()}
    for index,call in enumerate(calls):
        actual=[{k:item[k]for k in ('uri','args','options','result')}
            for item in trace[call['native_start']:call['native_end']]if item['uri']in uris]
        wanted=[expected[index]]if index in expected else[]
        if (audit.digest(actual)!=audit.digest(wanted)
                or index in expected and call['gateway']['argv'][0]!='execute'):
            raise ValueError('Mutation must occur only in its matching Execute native slice')


@lru_cache(maxsize=128)
def _meter_capture(encoded,root):
    from wwise_waapi.builders.schema import validate_resolved_semantic_result
    cap=json.loads(encoded);trace=cap['native_reads'];calls=cap['public_calls'];native=cap['native_call'];uri=native['uri']
    if (cap['contract']!='waapi-skill.runtime-read-program/v1'or cap['phase_reports']!=dict.fromkeys(('setup','call','teardown'),'passed')
            or cap['source_unchanged']is not True or len(calls)!=18 or not 1<=len(trace)<=128):raise ValueError('Complete owned meter pair/actual teardown required')
    commands=['draft-start','draft-bind-object','draft-declare-runtime-control-plan','draft-check','preview-from-draft','transaction-show','confirm','execute','verify']*2
    end=0
    for command,item in zip(commands,calls,strict=True):
        g=item['gateway'];payload=g['payload'];start=item['native_start'];stop=item['native_end']
        if (g['argv'][0]!=command or g['exit_code']!=0 or payload.get('ok')is not True or type(start)is not int or start!=end
                or type(stop)is not int or not start<=stop<=len(trace)or'agent_result'in payload and list(payload)[-1]!='agent_result'):
            raise ValueError('Owned meter actual public phase/native span differs')
        end=stop
    if end!=len(trace)or any(set(x)!={'ordinal','uri','args','options','result'}or type(x['ordinal'])is not int or x['ordinal']!=i for i,x in enumerate(trace)):
        raise ValueError('Owned meter finite trace differs')
    contexts=[completion.native_host_context(x['result'],'isCommandLine')for x in trace if x['uri']=='ak.wwise.core.getInfo']
    if not contexts or any(x!=contexts[0]for x in contexts):raise ValueError('Owned meter host/version drift')
    context=contexts[0];allowed=METER_URIS|{'ak.wwise.core.getInfo','ak.wwise.core.getProjectInfo','ak.wwise.core.object.get','ak.wwise.core.remote.getConnectionStatus'}
    if any(x['uri']not in allowed for x in trace):raise ValueError('Unrelated native call in meter pair')
    mutations=[{k:x[k]for k in ('uri','args','options','result')}for x in trace if x['uri']in METER_URIS]
    if len(mutations)!=2 or [x['uri']for x in mutations]!=[PREFIX+'registerMeter',PREFIX+'unregisterMeter']or mutations[0]['args']!=mutations[1]['args']:
        raise ValueError('Exactly one balanced same-object native meter pair required')
    _require_execute_mutations(calls,trace,{7:mutations[0],16:mutations[1]})
    target=0 if uri.endswith('.registerMeter')else 1
    if native!=mutations[target]or cap['gateway']!=calls[target*9+8]['gateway']:raise ValueError('Exact meter target receipt differs')
    rows=[row for x in trace if x['uri']=='ak.wwise.core.object.get'for row in x['result']['return']]
    if not rows:raise ValueError('Actual owned meter identity resolution missing')
    identity={k:rows[0][k]for k in ('id','name','type','path')}
    if identity['type']not in {'Bus','AuxBus','AudioDevice'}or any(any(row.get(k)!=v for k,v in identity.items())for row in rows):
        raise ValueError('Meter role identity/type/path drift')
    if any(x['args']!={'object':identity['id']}or x['options']!={}for x in mutations):raise ValueError('Meter native identity differs from live revalidation')
    for number,mutation in enumerate(mutations):
        group=[x['gateway']for x in calls[number*9:(number+1)*9]];started,bound,declared,checked,preview,shown,confirmed,executed,verified=group
        tx=preview['payload']['transaction_id'];seal=preview['payload']['artifact_hash'];payload=verified['payload'];a=payload['agent_result'];draft=started['payload']['draft']['draft_id'];authority=started['payload']['task_authority']
        if (started['argv']!=['draft-start',mutation['uri']]or any(draft not in c['argv']or authority not in c['argv']for c in (bound,declared,checked,preview))
                or bound['payload']['bound_object']['role']!='meter_object'or bound['payload']['bound_object']['type']!=identity['type']or bound['payload']['bound_object']['name']!=identity['name']
                or declared['argv'][-2:]!=['--meter-object-handle',bound['payload']['bound_object']['handle']]
                or shown['argv']!=preview['payload']['next_command']['gateway_argv']or confirmed['argv']!=shown['payload']['next_command']['gateway_argv']
                or executed['argv']!=['execute',tx]or verified['argv']!=executed['payload']['next_command']['gateway_argv']
                or any(c['payload'].get('transaction_id')!=tx or c['payload'].get('artifact_hash')!=seal for c in (shown,confirmed,executed,verified))
                or a['request']['arguments']!={'api':mutation['uri'],'args':mutation['args'],'options':{}}or a['result']!=mutation['result']
                or payload['verified']is not False or payload['state']!='result_schema_checked'or payload['verification']['business_state_verified']is not False
                or payload['automatic_retry']is not False or a['executed']is not True or payload['is_command_line']is not (context['host']=='wwise-console')):
            raise ValueError('Sealed public meter identity/confirmation/ACK differs')
        argv=bound['argv']
        if '--object-id'in argv:
            if argv[-2:]!=['--object-id',identity['id']]:raise ValueError('Meter ID selector differs')
        elif '--exact-type-name'in argv:
            if argv[-3:]!=['--exact-type-name',identity['type'],identity['name']]:raise ValueError('Meter exact type/name differs')
        elif '--object-path-segment'in argv:
            tokens=argv[argv.index('--object-path-segment'):]
            if len(tokens)%2 or tokens[::2]!=['--object-path-segment']*(len(tokens)//2)or'\\'+'\\'.join(tokens[1::2])!=identity['path']:
                raise ValueError('Meter exact path selector differs')
        else:raise ValueError('Unreviewed public meter selector')
        validate_resolved_semantic_result(mutation['uri'],mutation['result'],version=context['version'])
    return context,identity


def normalized_input(branch,cap,root):
    source=review(root)['meter_normalized_inputs'].get(branch['id'])
    if source is None:return None
    number=0 if cap['native_call']['uri'].endswith('.registerMeter')else 1
    argv=cap['public_calls'][number*9+1]['gateway']['argv'];mode=source['public_selector']
    if ('--exact-type-name'if mode=='exact-type-name'else'--object-path-segment')not in argv:return None
    _,identity=_meter_capture(json.dumps(cap),root)
    alias=identity['type']+':'+identity['name']if mode=='exact-type-name'else identity['path']
    from wwise_waapi.native_catalog import load_native_catalog
    version,host,_,_,_=branch['route'].split('|');cat=load_native_catalog(version,host,root=root/'skills/waapi-skill/resources/native-catalog')
    if cat['content_sha256']!=source['catalog_sha256']or audit.digest(cat['definitions'])!=source['native_definition_graph_sha256']:
        raise ValueError('Exact meter native identity alternatives changed')
    parent=branch['pointer'].rsplit('/',1)[0]if branch['kind']in {'reference','constraint'}else branch['pointer']
    parent_schema=fixed.schema_node({**branch,'pointer':parent},root)
    completion.validate_native_alternative(root,{**branch,'pointer':parent,'shape_sha256':audit.digest(parent_schema)},alias,catalog=cat)
    return {'source':source,'public_selector':mode,'resolved_identity':identity,'native_alias_meaning':alias,'native_pointer':'/native_call/args/object','native_alias_dispatch_claimed':False}


def validate_evidence(record,binding,branch,category,base,root,edges=None):
    exact_entry(branch,root)
    if category!='program':raise ValueError('Owned control native requires its exact retained attachment')
    if branch.get('approved_boundary',{}).get('kind')=='file_destination':
        validate_file_boundary_receipt(record,branch,binding,record['branch_assertions'][branch['id']]['checks'],root)
        return None
    cap=record['runtime_read_program'];context,_=_capture(json.dumps(cap),root);version,host,build,_,uri=branch['route'].split('|')
    if (context!={'version':version,'host':host,'build':build}or cap['native_call']['uri']!=uri or record['gateway']!=cap['gateway']or record['native_call']!=cap['native_call']
            or record['relevant_sources']!=cap['source_context']['packaged']or binding['input']['gateway_argv']!=cap['gateway']['argv']
            or any(binding.get(k)!=v for k,v in code_bindings(branch).items())):raise ValueError('Owned control branch/source/public context differs')
    pointer=binding['observation_pointer'];normal=binding.get('normalized_input_choice')
    if normal is not None:
        if audit.digest(normal)!=audit.digest(normalized_input(branch,cap,root))or pointer!=normal['native_pointer']or binding.get('reference_chain')!=[]:
            raise ValueError('Only exact actual public meter identity normalization qualifies')
        return {'observation_pointer':pointer}
    completion.exact_observation_pointer(branch,binding,'/native_call',branch['pointer'].split('/')[1].removesuffix('Schema'),edges or {})
    if not fixed.predicate(branch,fixed.schema_node(branch,root),remaining._occurrence_value(record,pointer,branch),root):raise ValueError('Owned control exact branch predicate missing')


def qualified_result(descriptor,assessment,branch,candidate,scope_kind,base,binding,root,edges):
    entry=exact_entry(branch,root)
    if branch['pointer']!='/resultSchema'or entry['role']!='native_business_anchor'or scope_kind!='product':raise ValueError('Only exact owned-control roots qualify')
    original=original_control(branch['route'],base,root=root);p=original['profile']
    cap=completion.read_sealed_artifact(assessment['program_capture'],base);record=completion.read_sealed_artifact(descriptor,base)
    expected={'contract':CONTRACT,'branch_id':branch['id'],'profile':p,'support_review':assessment['support_review'],'archive':original['archive'],'program_capture':assessment['program_capture'],'facts':original['facts']}
    if branch['route'].endswith('.saveCapture'):
        expected['destination_binding']={'mode':'exact-authorized-directory-plus-name','original':p['request']['args']['file'],'program':cap['native_call']['args']['file']}
    expected_args=cap['native_call']['args']if branch['route'].endswith('.saveCapture')else p['request']['args']
    if (assessment!=expected or assessment['support_review']['sha256']!=SUPPORT_SHA or completion.read_sealed_artifact(assessment['support_review'],base)!=review(root)
            or record!={'candidate_sha256':candidate,'scope_kind':'product','evidence_kind':'qualified_retained_owned_control_fact','branch_id':branch['id'],
                'native_shape_sha256':branch['shape_sha256'],'assessment_sha256':binding['qualified_runtime_read_attachment']['sha256'],
                'relevant_sources':_original_sources(original,root),'retained_facts':original['facts']}
            or cap['native_call']!={'uri':p['request']['api'],'args':expected_args,'options':{},'result':p['result']}):raise ValueError('Exact original owned control/current full replay differs')
    validate_evidence({'gateway':cap['gateway'],'native_call':cap['native_call'],'runtime_read_program':cap,'relevant_sources':cap['source_context']['packaged']},binding,branch,'program',base,root,edges)
    return 'passed',None


def write_owned_control_bundle(output,captures,*,inventory,name_prefix='',file_boundaries=()):
    versions={r['version']for r in inventory['native_coverage']['routes']if r['uri']in URIS}
    families={('meter'if r['uri']in METER_URIS else'save'if r['uri']==PREFIX+'saveCapture'else'cursor')for r in inventory['native_coverage']['routes']if r['uri']in URIS}
    if (not isinstance(name_prefix,str)or name_prefix and (len(versions)!=1 or len(families)!=1
            or name_prefix!='owned-controls-'+next(iter(versions))+'-'+next(iter(families))+'-')):
        raise ValueError('Only the closed matching-version owned control prefix qualifies')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(audit.ROOT/SUPPORT,output/'owned-control-support-review.json')
    candidate=inventory['native_coverage']['candidate_sha256'];seen=set()
    index={'contract':'waapi-skill.branch-evidence-index/v1','base':'.','entries':[],'qualified_runtime_read_attachments':[]}
    requirements={'contract':'waapi-skill.branch-evidence-requirements/v1','branches':{}}
    edges={b['id']:b for b in inventory['native_coverage']['obligations']if b['kind']=='reference'}
    def write(name,value):return runtime.write_json(output/name,value)
    def desc(name):return {'artifact':name,'sha256':runtime.sha((output/name).read_bytes())}
    for number,path in enumerate(captures):
        cap=json.loads(Path(path).read_bytes());context,_=_capture(json.dumps(cap),audit.ROOT);uri=cap['native_call']['uri']
        route,=[r for r in inventory['native_coverage']['routes']if r['uri']==uri and all(r[k]==v for k,v in context.items())]
        public,=[r for r in inventory['routes']if r['id']==route['public_route']]
        mappings=[]
        for branch in inventory['native_coverage']['obligations']:
            if branch['id']in seen or branch['route']!=route['id']:continue
            exact_entry(branch,audit.ROOT)
            normal=normalized_input(branch,cap,audit.ROOT)
            if normal:
                mappings.append((branch,[],normal['native_pointer'],normal));continue
            for chain in runtime._contribution_chains(branch,edges):
                hit=next(((p,v)for p,v in runtime._contribution_occurrences(cap,runtime._contribution_pattern(branch,chain,edges))
                    if fixed.predicate(branch,fixed.schema_node(branch),v)),None)
                if hit:mappings.append((branch,chain,hit[0],None));break
        if not mappings:continue
        prefix=(name_prefix or'owned-controls-')+context['host']+'-'+str(number)+'-';cp=write(prefix+'capture.json',cap)
        program={'candidate_sha256':candidate,'scope_kind':'product','relevant_sources':cap['source_context']['packaged'],
            'gateway':cap['gateway'],'native_call':cap['native_call'],'runtime_read_program':cap,
            'invocation':{'phase':'final','outcome':'PASS','node_outcomes':[{'nodeid':cap['nodeid'],'outcome':'PASS'}]},'branch_assertions':{}}
        bindings={'contract':'waapi-skill.branch-bindings/v1','bindings':{}};policies={'contract':requirements['contract'],'branches':{}}
        for branch,chain,pointer,normal in mappings:
            identity=branch['id'];entry=exact_entry(branch,audit.ROOT);pp='/gateway/payload/agent_result'
            program['branch_assertions'][identity]={'native_shape_sha256':branch['shape_sha256'],'native_route':branch['route'],
                'checks':[({'pointer':pointer,'absent':True}if branch['kind']=='optional_presence'and branch['value']=='absent'and normal is None
                    else {'pointer':pointer,'cardinality':branch['value']}if branch['kind']=='collection_cardinality'
                    else {'pointer':pointer,'equals':completion.pointer_value(program,pointer)}),{'pointer':pp,'equals':completion.pointer_value(program,pp)}]}
            binding={'branch_id':identity,'native_shape_sha256':branch['shape_sha256'],'public_route':public['id'],'public_route_sha256':audit.digest(public),
                **({'normalized_input_choice':normal}if normal else{}),
                'input':{'gateway_argv':cap['gateway']['argv'],'selector':pointer},'dispatch_pointer':'/native_call','observation_pointer':pointer,
                'gateway_observation_pointer':pp,'reference_chain':chain,'relevant_sources':sorted(cap['source_context']['packaged']),'evidence':{},**code_bindings(branch)}
            validate_evidence(program,binding,branch,'program',output,audit.ROOT,edges)
            bindings['bindings'][identity]=binding;policies['branches'][identity]=remaining.policy(entry);seen.add(identity)
            if entry['role']=='native_business_anchor'and route['id']in review()['profiles']:
                original=original_control(route['id']);p=original['profile']
                expected_args=cap['native_call']['args']if uri==PREFIX+'saveCapture'else p['request']['args']
                if cap['native_call']!={'uri':uri,'args':expected_args,'options':{},'result':p['result']}:
                    raise ValueError('Capture native root requires actual original complete request/result replay first')
                name,source=_original_transport(original,audit.ROOT);shutil.copyfile(audit.ROOT/source,output/name)
                assessment=write(prefix+'assessment.json',{'contract':CONTRACT,'branch_id':identity,'profile':p,'support_review':desc('owned-control-support-review.json'),
                    'archive':desc(name),'program_capture':cp,'facts':original['facts'],
                    **({'destination_binding':{'mode':'exact-authorized-directory-plus-name','original':p['request']['args']['file'],'program':cap['native_call']['args']['file']}}if uri==PREFIX+'saveCapture'else{})})
                evidence=write(prefix+'qualified.json',{'candidate_sha256':candidate,'scope_kind':'product','evidence_kind':'qualified_retained_owned_control_fact',
                    'branch_id':identity,'native_shape_sha256':branch['shape_sha256'],'assessment_sha256':assessment['sha256'],
                    'relevant_sources':_original_sources(original,audit.ROOT),'retained_facts':original['facts']})
                index['qualified_runtime_read_attachments'].append(write(prefix+'attachment.json',{'contract':'waapi-skill.qualified-retained-read-attachment/v1',
                    'branch_id':identity,'assessment':assessment,'evidence':evidence}))
        pd={**write(prefix+'program.json',program),'nodeid':cap['nodeid']}
        for b in bindings['bindings'].values():b['evidence']['program']=pd
        bd=write(prefix+'bindings.json',bindings);rd=write(prefix+'requirements.json',policies)
        index['entries'].append({'id':prefix,'bindings':bd,'origin':{'bindings':bd,'program':desc(prefix+'program.json'),'requirements':rd,'capture':cp}})
        requirements['branches'].update(policies['branches'])
    _write_file_boundaries(output,index,requirements,inventory,file_boundaries,seen,name_prefix)
    if seen!={b['id']for b in inventory['native_coverage']['obligations']}:
        raise ValueError('Missing exact owned control branch occurrences: '+str(set(b['id']for b in inventory['native_coverage']['obligations'])-seen))
    write('requirements.json',requirements);write('index.json',index)
    return output/'index.json'


def original_save(route,base=None,*,root=audit.ROOT):
    p=review(root)['profiles'].get(route)
    if p is None or p['provider']!='saved-artifact':raise ValueError('No exact retained saved-capture fact for route')
    original=cursor.original_cursor(p['cursor_route'],base,root=root);cp=original['profile'];read=original['read'];node=json.loads(read(cp['node_path']));calls=node['receipts'];chain=[calls[i]for i in p['receipt_indices']]
    preview,shown,confirmed,executed,verified=chain;raw=json.loads(read(p['raw_path']));witness=json.loads(read(cp['report_path']))['outcomes']['profiler-saved-capture-artifact'];e=witness['evidence'];payload=verified['payload'];uri=route.split('|')[-1]
    if (audit.digest(chain)!=p['receipt_sha256']or runtime.sha(read(p['raw_path']))!=p['raw_sha256']or audit.digest(witness)!=p['witness_sha256']
            or witness['outcome']!='PASS'or e['outcome']!='exact_destination_created_or_content_changed_and_nonempty'
            or e['capture_content_completeness_verified']is not False or e['capture_format_validity_verified']is not False
            or e['writes_outside_output_directory_observed']is not False or type(e['file']['size'])is not int or e['file']['size']<=0
            or e['file']['path']!=p['request']['args']['file']or e['transaction']!=payload
            or raw['ok']is not True or raw['dry_run']is not False or raw['api']!=uri or raw['result']!=p['result']
            or payload['agent_result']['request']['arguments']!=p['request']or payload['agent_result']['result']!=p['result']
            or any(c['exit_code']!=0 or c['payload'].get('ok')is not True for c in chain)
            or shown['argv']not in [preview['payload']['next_command']['gateway_argv'],['transaction-show',preview['payload']['transaction_id']]]
            or confirmed['argv']!=shown['payload']['next_command']['gateway_argv']or executed['argv']!=['execute',preview['payload']['transaction_id']]
            or verified['argv']!=executed['payload']['next_command']['gateway_argv']
            or any(c['payload']['artifact_hash']!=preview['payload']['artifact_hash']for c in chain)
            or Path(executed['payload']['dispatch_result']['evidence_path']).name!=Path(p['raw_path']).name
            or payload['verified']is not True or payload['verification']['business_state_verified']is not True
            or payload['verification']['verification_strength']!='profiler_capture_artifact'or payload['automatic_retry']is not False):
        raise ValueError('Exact original saved destination/artifact/provenance differs')
    return {'profile':p,'archive':original['archive'],'read':read,'facts':{**original['facts'],'actual_control':uri,
        'original_destination':p['request']['args']['file'],'original_file':e['file'],'exact_destination_created_or_changed_nonempty':True,
        'unrelated_file_contents_preserved':True,'capture_format_validity_verified':False,'capture_content_completeness_verified':False}}


@lru_cache(maxsize=128)
def _save_capture(encoded,root):
    from wwise_waapi.host_paths import parse_absolute_host_path
    from wwise_waapi.builders.schema import validate_resolved_semantic_result
    cap=json.loads(encoded);native=cap['native_call'];calls=cap['public_calls'];trace=cap['native_reads'];uri=PREFIX+'saveCapture'
    if (native['uri']!=uri or cap['contract']!='waapi-skill.runtime-read-program/v1'or cap['phase_reports']!=dict.fromkeys(('setup','call','teardown'),'passed')
            or cap['source_unchanged']is not True or len(calls)!=9 or not 1<=len(trace)<=96):raise ValueError('Complete actual saved-artifact public transaction/teardown required')
    commands=['draft-start','draft-declare-runtime-control-plan','draft-check','preview-from-draft','transaction-show','confirm','execute','verify','transaction-show'];end=0
    for command,item in zip(commands,calls,strict=True):
        g=item['gateway'];start=item['native_start'];stop=item['native_end']
        if (g['argv'][0]!=command or g['exit_code']!=0 or g['payload'].get('ok')is not True or type(start)is not int or start!=end
                or type(stop)is not int or not start<=stop<=len(trace)or'agent_result'in g['payload']and list(g['payload'])[-1]!='agent_result'):
            raise ValueError('Saved-artifact public phase/native span differs')
        end=stop
    allowed={uri,'ak.wwise.core.getInfo','ak.wwise.core.getProjectInfo','ak.wwise.core.remote.getConnectionStatus'}
    if end!=len(trace)or any(set(x)!={'ordinal','uri','args','options','result'}or type(x['ordinal'])is not int or x['ordinal']!=i or x['uri']not in allowed for i,x in enumerate(trace)):
        raise ValueError('Saved-artifact bounded once-only trace differs')
    contexts=[completion.native_host_context(x['result'],'isCommandLine')for x in trace if x['uri']=='ak.wwise.core.getInfo']
    if not contexts or any(x!=contexts[0]for x in contexts):raise ValueError('Saved-artifact host/version drift')
    context=contexts[0]
    if [{k:x[k]for k in ('uri','args','options','result')}for x in trace if x['uri']==uri]!=[native]:raise ValueError('Exactly one saved-capture dispatch required')
    _require_execute_mutations(calls,trace,{6:native})
    started,declared,checked,preview,shown,confirmed,executed,verified,full=[x['gateway']for x in calls];payload=verified['payload'];tx=preview['payload']['transaction_id'];seal=preview['payload']['artifact_hash'];draft=started['payload']['draft']['draft_id'];authority=started['payload']['task_authority']
    decl_argv=declared['argv'];decl_directory=decl_argv[decl_argv.index('--capture-output-directory')+1]
    io_root=str(parse_absolute_host_path(decl_directory,allow_trailing_separator=True).pure_path)
    if (started['argv']!=['draft-start',uri]or any(draft not in x['argv']or authority not in x['argv']for x in (declared,checked,preview))
            or shown['argv']!=preview['payload']['next_command']['gateway_argv']or confirmed['argv']!=shown['payload']['next_command']['gateway_argv']
            or executed['argv']!=['execute',tx]or verified['argv']!=executed['payload']['next_command']['gateway_argv']or full['argv']!=['transaction-show',tx]
            or any(x['payload'].get('transaction_id')!=tx or x['payload'].get('artifact_hash')!=seal for x in (shown,confirmed,executed,verified,full))
            or payload['agent_result']['request']['arguments']!={'api':uri,'args':native['args'],'options':{},'io_root':io_root}
            or payload['agent_result']['result']!=native['result']or cap['gateway']!=verified
            or payload['verified']is not True or payload['state']!='verified'or payload['automatic_retry']is not False
            or payload['verification']['business_state_verified']is not True or payload['verification']['verification_strength']!='profiler_capture_artifact'
            or payload['is_command_line']is not (context['host']=='wwise-console')):raise ValueError('Sealed saved-capture authorization/once execution/actual verification differs')
    argv=declared['argv'];directory=argv[argv.index('--capture-output-directory')+1];name=argv[argv.index('--capture-name')+1]
    path=str(parse_absolute_host_path(directory,allow_trailing_separator=True).pure_path/(name if name.casefold().endswith('.prof')else name+'.prof'))
    if not name or native['args']!={'file':path}or native['options']!={}:raise ValueError('Exact public authorized file destination differs')
    evidence=next(e['details']['verification']for e in reversed(full['payload']['events'])if e['event_type']=='verification_recorded');readback,=evidence['readbacks'];scope=evidence['verification_scope']
    public_verification=payload['verification']
    evidence_matches=(audit.digest(evidence)==public_verification['canonical_sha256']if 'summary_contract'in public_verification else audit.digest(evidence)==audit.digest(public_verification))
    if (not evidence_matches or readback['path']!=path
            or readback['kind']!='profiler-capture-artifact-observation'or readback['changed']is not True or readback['nonempty']is not True
            or readback['unrelated_files_preserved']is not True or type(readback['after_file']['size'])is not int or readback['after_file']['size']<=0
            or readback['after_file']['path']!=path or scope['capture_content_completeness_verified']is not False
            or scope['capture_format_validity_verified']is not False or scope['writes_outside_output_directory_observed']is not False
            or readback['verification_scope']!=scope):raise ValueError('Complete exact nonempty changed artifact/preservation proof differs')
    validate_resolved_semantic_result(uri,native['result'],version=context['version'])
    return context,None


def approved_file_boundary(root,branch,binding):
    exact_entry(branch,root);data=review(root)
    if (branch['id']not in data['save_boundary_ids']or binding.get('boundary')!={'kind':'file_destination','support_sha256':SUPPORT_SHA,'native_field':'file'}):return None
    from tests.support.empty_candidate_evidence import classify_empty_candidate
    if classify_empty_candidate(root,branch)['status']!='accepted':raise ValueError('File boundary must retain schema-admitted empty string')
    from wwise_waapi.runtime_inspection_business_contracts import runtime_inspection_business_contract_data
    version=branch['route'].split('|')[0];contract=runtime_inspection_business_contract_data(PREFIX+'saveCapture',version=version)['declaration']
    if contract['field_types']!=data['file_boundary_authority']['field_types']:raise ValueError('Approved file destination authorization contract differs')
    return {'kind':'file_destination','native_field':'file','source_review_sha256':SUPPORT_SHA,'native_schema_classification':'accepted'}


def write_file_boundary_capture(path,rejections,valid_capture,*,nodeid,phase_reports,source_context):
    valid=json.loads(Path(valid_capture).read_bytes())
    if phase_reports!=dict.fromkeys(('setup','call','teardown'),'passed')or source_context!=runtime.program_source_context(flow=PREFIX+'saveCapture'):
        raise ValueError('File boundary needs actual successful finalization/current sources')
    return runtime.write_json(path,{'contract':'waapi-skill.file-destination-boundary/v1','nodeid':nodeid,'phase_reports':phase_reports,
        'source_context':source_context,'rejections':rejections,'valid':valid})


def validate_file_boundary_receipt(record,branch,binding,checks,root=None):
    root=root or audit.ROOT;exact_entry(branch,root)
    if branch['id']not in review(root)['save_boundary_ids']:raise ValueError('Only exact six destination boundaries qualify')
    proof=record['file_destination_boundary'];valid=proof['valid'];context,_=_capture(json.dumps(valid),root)
    if (proof['contract']!='waapi-skill.file-destination-boundary/v1'or proof['phase_reports']!=dict.fromkeys(('setup','call','teardown'),'passed')
            or proof['source_context']!=valid['source_context']or record['relevant_sources']!=valid['source_context']['packaged']
            or context!={k:v for k,v in zip(('version','host','build'),branch['route'].split('|')[:3],strict=True)}or len(proof['rejections'])!=2):
        raise ValueError('Exact boundary scope/current valid counterpart differs')
    accepted=valid['public_calls'][1];declaration=accepted['gateway']['argv'];found=set()
    accepted_calls=valid['native_reads'][accepted['native_start']:accepted['native_end']]
    if [x['uri']for x in accepted_calls]!=['ak.wwise.core.getInfo','ak.wwise.core.getProjectInfo']:
        raise ValueError('Exact read-only declaration context required')
    for rejected in proof['rejections']:
        gateway=rejected['gateway'];argv=gateway['argv'];payload=gateway['payload'];calls=rejected['native_calls']
        # A rejection cannot conceal any other dispatch. Both failed declarations
        # have the same read-only connection/project context as their accepted
        # same-Draft counterpart, including exact trace types and session facts.
        if (audit.digest(calls)!=audit.digest(accepted_calls)
                or any(payload.get(k)!=accepted['gateway']['payload'].get(k)for k in ('endpoint','detected_version','is_command_line'))):
            raise ValueError('Rejected destination read-only context/session trace differs')
        changed=[i for i,(a,b)in enumerate(zip(argv,declaration,strict=True))if a!=b]
        if len(changed)!=1 or argv[changed[0]]!=''or changed[0]==0:raise ValueError('File boundary must change only one public destination value')
        flag=argv[changed[0]-1];field=review(root)['file_boundary_authority']['flags'].get(flag)
        if field is None or gateway['exit_code']!=2 or payload.get('ok')is not False or any(x['uri']==PREFIX+'saveCapture'for x in calls):raise ValueError('Exact empty destination/no-dispatch rejection required')
        # The actual materializer discloses the precise failed public field.
        if (payload.get('error_code')!='INVALID_HOST_PATH'or payload.get('details',{}).get('repair',{}).get('field')!=field
                or payload['details']['repair'].get('draft_changed')is not False or payload['details']['repair'].get('error_code')!='INVALID_HOST_PATH'):
            raise ValueError('File destination rejection lacks exact field attribution')
        found.add(flag)
    if found!=set(review(root)['file_boundary_authority']['flags'])or record['gateway']!=proof['rejections'][0]['gateway']or record['native_calls']!=proof['rejections'][0]['native_calls']:
        raise ValueError('Both exact public destination boundaries required')


def _write_file_boundaries(output,index,requirements,inventory,paths,seen,name_prefix):
    candidate=inventory['native_coverage']['candidate_sha256']
    for number,path in enumerate(paths):
        proof=json.loads(Path(path).read_bytes());cap=proof['valid'];context,_=_capture(json.dumps(cap),audit.ROOT)
        route,=[r for r in inventory['native_coverage']['routes']if r['uri']==PREFIX+'saveCapture'and all(r[k]==v for k,v in context.items())]
        identity=route['id']+'|/argsSchema/properties/file/@empty/string';branch,=[b for b in inventory['native_coverage']['obligations']if b['id']==identity];entry=exact_entry(branch)
        if identity in seen:raise ValueError('Duplicate file destination boundary')
        public,=[r for r in inventory['routes']if r['id']==route['public_route']];prefix=(name_prefix or'owned-controls-')+context['host']+'-boundary-'+str(number)+'-'
        cp=runtime.write_json(output/(prefix+'capture.json'),proof);rejected=proof['rejections'][0];g=rejected['gateway'];check={'pointer':'/gateway/payload/error_code','equals':g['payload']['error_code']}
        record={'candidate_sha256':candidate,'scope_kind':'product','relevant_sources':cap['source_context']['packaged'],**rejected,'file_destination_boundary':proof,
            'invocation':{'phase':'final','outcome':'PASS','node_outcomes':[{'nodeid':proof['nodeid'],'outcome':'PASS'}]},'branch_assertions':{
                identity:{'native_shape_sha256':branch['shape_sha256'],'native_route':branch['route'],'checks':[check]}}}
        position=g['argv'].index('--capture-output-directory')+1;pointer='/gateway/argv/'+str(position)
        binding={'branch_id':identity,'native_shape_sha256':branch['shape_sha256'],'public_route':public['id'],'public_route_sha256':audit.digest(public),
            'input':{'gateway_argv':g['argv'],'selector':pointer},'dispatch_pointer':'/file_destination_boundary/valid/native_call','observation_pointer':pointer,
            'gateway_observation_pointer':'/gateway/payload/error_code','reference_chain':[],'relevant_sources':sorted(cap['source_context']['packaged']),
            'disposition':'approved_boundary','boundary':{'kind':'file_destination','support_sha256':SUPPORT_SHA,'native_field':'file'},**code_bindings(branch)}
        if approved_file_boundary(audit.ROOT,branch,binding)is None:raise ValueError('Unapproved file destination boundary')
        validate_file_boundary_receipt(record,branch,binding,[check],audit.ROOT)
        pd={**runtime.write_json(output/(prefix+'program.json'),record),'nodeid':proof['nodeid']};binding['evidence']={'program':pd}
        bd=runtime.write_json(output/(prefix+'bindings.json'),{'contract':'waapi-skill.branch-bindings/v1','bindings':{identity:binding}})
        policy={'contract':requirements['contract'],'branches':{identity:remaining.policy(entry)}};rd=runtime.write_json(output/(prefix+'requirements.json'),policy)
        index['entries'].append({'id':prefix,'bindings':bd,'origin':{'bindings':bd,'program':{'artifact':pd['artifact'],'sha256':pd['sha256']},'requirements':rd,'capture':cp}})
        requirements['branches'].update(policy['branches']);seen.add(identity)


def original_control(route,base=None,*,root=audit.ROOT):
    uri=route.split('|')[-1]
    if uri in METER_URIS:return original_meter(route,base,root=root)
    if uri==PREFIX+'saveCapture':return original_save(route,base,root=root)
    if uri==PREFIX+'moveCursor':return original_moves(route,base,root=root)
    p=review(root)['profiles'].get(route)
    if p is None or p['provider']!='cursor-effect':raise ValueError('No exact retained cursor control effect for route')
    original=cursor.original_cursor(p['cursor_route'],base,root=root);cp=original['profile'];read=original['read'];calls=json.loads(read(cp['node_path']))['receipts'];chain=[calls[i]for i in p['receipt_indices']]
    preview,shown,confirmed,executed,verified=chain;raw=json.loads(read(p['raw_path']));payload=verified['payload'];witness=json.loads(read(cp['report_path']))['outcomes']['profiler-cursor-snap-readback'];e=witness['evidence'];time=p['result']['return']
    if (audit.digest(chain)!=p['receipt_sha256']or runtime.sha(read(p['raw_path']))!=p['raw_sha256']or audit.digest(witness)!=p['witness_sha256']
            or witness['outcome']!='PASS'or type(time)is not int or time<0 or e['snapped_time_ms']!=time or e['requested_time_ms']!=p['request']['args']['time']
            or e['user_cursor']!={'profiler_cursor':'user-cursor','available':True,'position_ms':time}or e['transaction']!=payload
            or raw['ok']is not True or raw['dry_run']is not False or raw['api']!=uri or raw['result']!=p['result']
            or payload['agent_result']['request']['arguments']!=p['request']or payload['agent_result']['result']!=p['result']
            or any(c['exit_code']!=0 or c['payload'].get('ok')is not True for c in chain)
            or shown['argv']not in [preview['payload']['next_command']['gateway_argv'],['transaction-show',preview['payload']['transaction_id']]]
            or confirmed['argv']!=shown['payload']['next_command']['gateway_argv']or executed['argv']!=['execute',preview['payload']['transaction_id']]
            or verified['argv']!=executed['payload']['next_command']['gateway_argv']or any(c['payload']['artifact_hash']!=preview['payload']['artifact_hash']for c in chain)
            or Path(executed['payload']['dispatch_result']['evidence_path']).name!=Path(p['raw_path']).name
            or payload['verified']is not True or payload['verification']['business_state_verified']is not True
            or payload['verification']['verification_strength']!='independent_profiler_user_cursor_observation'or payload['automatic_retry']is not False):
        raise ValueError('Exact original cursor returned time/independent observation/authorization differs')
    return {'profile':p,'archive':original['archive'],'read':read,'facts':{**original['facts'],'actual_control':uri,
        'requested_time_ms':e['requested_time_ms'],'returned_time_ms':time,'independent_user_cursor':e['user_cursor'],
        'continuing_cursor_position_verified':False,'capture_data_verified':False}}


@lru_cache(maxsize=128)
def _cursor_capture(encoded,root):
    from wwise_waapi.runtime_inspection_business_contracts import PROFILER_CURSOR_MOVE_MEANINGS
    from wwise_waapi.builders.schema import validate_resolved_semantic_result
    cap=json.loads(encoded);native=cap['native_call'];uri=native['uri'];calls=cap['public_calls'];trace=cap['native_reads'];getter=PREFIX+'getCursorTime'
    if (uri not in {PREFIX+'moveCursor',PREFIX+'setCursorTime'}or cap['contract']!='waapi-skill.runtime-read-program/v1'
            or cap['phase_reports']!=dict.fromkeys(('setup','call','teardown'),'passed')or cap['source_unchanged']is not True or len(calls)!=9 or not 1<=len(trace)<=96):
        raise ValueError('Complete actual cursor control/public observation/teardown required')
    commands=['draft-start','draft-declare-runtime-control-plan','draft-check','preview-from-draft','transaction-show','confirm','execute','verify','transaction-show'];end=0
    for command,item in zip(commands,calls,strict=True):
        g=item['gateway'];start=item['native_start'];stop=item['native_end']
        if (g['argv'][0]!=command or g['exit_code']!=0 or g['payload'].get('ok')is not True or type(start)is not int or start!=end
                or type(stop)is not int or not start<=stop<=len(trace)or'agent_result'in g['payload']and list(g['payload'])[-1]!='agent_result'):
            raise ValueError('Cursor exact public phase/native span differs')
        end=stop
    allowed={uri,getter,'ak.wwise.core.getInfo','ak.wwise.core.getProjectInfo','ak.wwise.core.remote.getConnectionStatus'}
    if end!=len(trace)or any(set(x)!={'ordinal','uri','args','options','result'}or type(x['ordinal'])is not int or x['ordinal']!=i or x['uri']not in allowed for i,x in enumerate(trace)):
        raise ValueError('Cursor finite once-only trace differs')
    contexts=[completion.native_host_context(x['result'],'isCommandLine')for x in trace if x['uri']=='ak.wwise.core.getInfo']
    if not contexts or any(x!=contexts[0]for x in contexts)or contexts[0]['version']!='2025.1':raise ValueError('Cursor actual host/version drift')
    context=contexts[0];mutations=[{k:x[k]for k in ('uri','args','options','result')}for x in trace if x['uri']==uri];reads=[x for x in trace if x['uri']==getter]
    if mutations!=[native]or len(reads)!=1 or reads[0]['args']!={'cursor':'user'}or reads[0]['options']!={}:raise ValueError('Cursor needs one dispatch and one independent user observation')
    _require_execute_mutations(calls,trace,{6:native})
    started,declared,checked,preview,shown,confirmed,executed,verified,full=[x['gateway']for x in calls];payload=verified['payload'];tx=preview['payload']['transaction_id'];seal=preview['payload']['artifact_hash'];draft=started['payload']['draft']['draft_id'];authority=started['payload']['task_authority']
    if (started['argv']!=['draft-start',uri]or any(draft not in x['argv']or authority not in x['argv']for x in (declared,checked,preview))
            or shown['argv']!=preview['payload']['next_command']['gateway_argv']or confirmed['argv']!=shown['payload']['next_command']['gateway_argv']
            or executed['argv']!=['execute',tx]or verified['argv']!=executed['payload']['next_command']['gateway_argv']or full['argv']!=['transaction-show',tx]
            or any(x['payload'].get('transaction_id')!=tx or x['payload'].get('artifact_hash')!=seal for x in (shown,confirmed,executed,verified,full))
            or payload['agent_result']['request']['arguments']!={'api':uri,'args':native['args'],'options':{}}or payload['agent_result']['result']!=native['result']or cap['gateway']!=verified
            or payload['verified']is not True or payload['state']!='verified'or payload['automatic_retry']is not False
            or payload['verification']['business_state_verified']is not True or payload['verification']['verification_strength']!='independent_profiler_user_cursor_observation'
            or payload['is_command_line']is not (context['host']=='wwise-console')):raise ValueError('Sealed cursor authorization/once execution/verification differs')
    argv=declared['argv'];flag='--cursor-move'if uri.endswith('.moveCursor')else'--cursor-target-ms';value=argv[argv.index(flag)+1]
    args={'position':PROFILER_CURSOR_MOVE_MEANINGS.get(value)}if uri.endswith('.moveCursor')else{'time':int(value)}
    if native['args']!=args or native['options']!={}:raise ValueError('Exact public cursor meaning differs from compiled native request')
    validate_resolved_semantic_result(uri,native['result'],version=context['version']);time=native['result']['return']
    if type(time)is not int or time<0 or reads[0]['result']!={'return':time}:raise ValueError('Returned cursor time is unavailable or differs from independent observation')
    if not calls[7]['native_start']<=reads[0]['ordinal']<calls[7]['native_end']:raise ValueError('Independent getter must occur in verification phase')
    evidence=next(e['details']['verification']for e in reversed(full['payload']['events'])if e['event_type']=='verification_recorded');public=payload['verification']
    matching=(audit.digest(evidence)==public['canonical_sha256']if 'summary_contract'in public else audit.digest(evidence)==audit.digest(public))
    observed={'kind':'profiler-user-cursor-observation','returned_time_ms':time,'observed_time_ms':time,'capture_data_verified':False,'outcome':'matched'}
    if (not matching or evidence['verification_scope']['cursor_observation']!=observed
            or evidence['verification_scope']['continuing_cursor_position_verified']is not False
            or {k:reads[0][k]for k in ('uri','args','options','result')}not in evidence['readbacks']):raise ValueError('Complete independent cursor verification evidence differs')
    return context,None


def cursor_counterexample_policy(branch,root=audit.ROOT):
    exact_entry(branch,root)
    if branch['id']not in review(root)['cursor_counterexample_ids']:raise ValueError('Only exact two cursor-position counterexamples qualify')
    from tests.support.empty_candidate_evidence import classify_empty_candidate
    classification=classify_empty_candidate(root,branch)
    if classification is None or classification['status']!='rejected':raise ValueError('Exact invalid cursor-position candidate no longer rejects')
    return {'native_shape_sha256':branch['shape_sha256'],'categories':['program'],'empty_candidate':classification,
        'reason':'Resolved reflected schema rejects this concrete synthetic candidate; exact public counterexample program proof required. No native absence/effect or parent credit.'}


def original_moves(route,base=None,*,root=audit.ROOT):
    """Exact R108 four-mode business observations, whole original closure retained."""
    import gzip
    data=review(root);p=data['profiles'].get(route);r=data['r108']
    if p is None or p['provider']!='move-effect'or route!='2025.1|wwise-authoring|2025.1.7.9143|function|'+PREFIX+'moveCursor':
        raise ValueError('Only exact retained Authoring2025 four-mode cursor facts qualify')
    archive_path=root/r['archive_source']if base is None else Path(base)/Path(r['archive_source']).name
    archive={'artifact':archive_path.name,'sha256':r['archive_sha256']};read=runtime.archive_reader(archive,archive_path.parent)
    encoded=json.loads(gzip.decompress(archive_path.read_bytes()))['files']
    if len(encoded)!=r['archive_files']or audit.digest(encoded)!=r['archive_map_sha256']:raise ValueError('Complete106-file R108 archive differs')
    load=lambda path:json.loads(read(path))
    node=load(r['node_path']);report=load(r['report_path']);rr=load(r['original_root']+'/root-review.json');final=load(r['original_root']+'/evidence/authoring-batch-finalization.json');life=final['lifecycle']
    context=completion.native_host_context(report['host'],'isCommandLine')
    if (context!={'version':'2025.1','host':'wwise-authoring','build':'2025.1.7.9143'}or completion.native_host_context({'version':final['host']['version'],'isCommandLine':final['host']['is_command_line']},'isCommandLine')!=context
            or any(x['candidate']!=r['original_candidate']for x in (node,report,rr,final))
            or runtime.sha(read(r['node_path']))!=r['node_sha256']or runtime.sha(read(r['report_path']))!=r['report_sha256']
            or rr['report_sha256']!=r['report_sha256']or rr['formal_outcome']!='PASS'or rr['source_unchanged']is not True
            or rr['cleanup_complete']is not True or rr['cleanup_errors']!=[]or rr['integrity_errors']!=[]or rr['post_terminal_bare_port_8080_bindable']is not True
            or report['complete']is not True or report['errors']!=[]or report['cleanup']['complete']is not True or report['cleanup']['errors']!=[]
            or final['outcome']!='PASS'or life['final_status']!='PASS'or life['errors']!=[]or life['sandbox_retained']is not False
            or life['source_hash_before']!=life['source_hash_after']or life['source_mtime_before_ns']!=life['source_mtime_after_ns']
            or final['resources']['port']['released']is not True or final['resources']['residual_processes']!=[]
            or final['resources']['cleanup_report']['process_exited']is not True or final['resources']['cleanup_report']['residual_processes']!=[]):
        raise ValueError('Original R108 actual host/source/terminal cleanup facts differ')
    if (audit.digest(node['source_context'])!=r['source_context_sha256']or final['source_context']!=node['source_context']
            or {k:v for k,v in node['source_context']['sources'].items()if k.startswith('skills/waapi-skill/')}!=r['original_sources']):
        raise ValueError('All617 original source entries/native413 subset differ')
    source=r['original_sources'];current=runtime.program_source_context(root,flow=PREFIX+'moveCursor')['packaged']
    changes={k:{'before':source.get(k),'after':current.get(k)}for k in source.keys()|current.keys()if source.get(k)!=current.get(k)}
    if len(source)!=413 or len(current)!=413 or changes!=r['source_changes']:raise ValueError('Exact reviewed R108 full413 source delta differs')
    checked=0
    for group in node['artifacts'].values():
        for item in group['files']:
            body=read(group['path']+'/'+item['path']);checked+=1
            if len(body)!=item['bytes']or runtime.sha(body)!=item['sha256']:raise ValueError('Complete original R10899-file node manifest differs')
    if checked!=99:raise ValueError('Original R108 manifest membership differs')
    modes=[]
    if [m['request']['args']['position']for m in p['modes']]!=['first','next','last','previous']:raise ValueError('All four actual interpreted move modes required')
    for m in p['modes']:
        raw=load(m['raw_path']);chain=[node['receipts'][i]for i in m['receipt_indices']];preview,shown,confirmed,executed,verified=chain;payload=verified['payload'];witness=report['outcomes'][m['witness']];e=witness['evidence'];time=m['result']['return']
        if (audit.digest(chain)!=m['receipt_sha256']or runtime.sha(read(m['raw_path']))!=m['raw_sha256']or audit.digest(witness)!=m['witness_sha256']
                or raw['ok']is not True or raw['dry_run']is not False or raw['api']!=PREFIX+'moveCursor'or raw['version']!='2025.1'or raw['result']!=m['result']
                or m['request']!={'api':PREFIX+'moveCursor','args':{'position':m['request']['args']['position']},'options':{}}
                or any(x['exit_code']!=0 or x['payload'].get('ok')is not True for x in chain)
                or shown['argv']not in [preview['payload']['next_command']['gateway_argv'],['transaction-show',preview['payload']['transaction_id']]]
                or confirmed['argv']!=shown['payload']['next_command']['gateway_argv']or executed['argv']!=['execute',preview['payload']['transaction_id']]
                or verified['argv']!=executed['payload']['next_command']['gateway_argv']or any(x['payload']['artifact_hash']!=preview['payload']['artifact_hash']for x in chain)
                or Path(executed['payload']['dispatch_result']['evidence_path']).name!=Path(m['raw_path']).name
                or payload['agent_result']['request']['arguments']!=m['request']or payload['agent_result']['result']!=m['result']
                or payload['verified']is not True or payload['automatic_retry']is not False or payload['verification']['business_state_verified']is not True
                or payload['verification']['verification_strength']!='independent_profiler_user_cursor_observation'
                or witness['outcome']!='PASS'or e['transaction']!=payload or e['capture_data_completeness_verified']is not False
                or type(time)is not int or time<0 or e['returned_time_ms']!=time or e['observed_time_ms']!=time
                or payload['verification']['verification_scope']['cursor_observation']!={'kind':'profiler-user-cursor-observation','returned_time_ms':time,'observed_time_ms':time,'capture_data_verified':False,'outcome':'matched'}):
            raise ValueError('Exact original move-mode return/independent user observation/authorization differs')
        events=[json.loads(line)for line in read(m['journal_path']).splitlines()]
        verification=next(x['details']['verification']for x in reversed(events)if x['event_type']=='verification_recorded');getter=load(m['getter_raw_path'])
        native_read={'uri':PREFIX+'getCursorTime','args':{'cursor':'user'},'options':{},'result':{'return':time}}
        if (audit.digest(verification)!=m['verification_sha256']or audit.digest(verification)!=payload['verification']['canonical_sha256']
                or verification['readbacks']!=[native_read,payload['verification']['verification_scope']['cursor_observation']]
                or runtime.sha(read(m['getter_raw_path']))!=m['getter_raw_sha256']or getter['api']!=PREFIX+'getCursorTime'
                or getter['ok']is not True or getter['dry_run']is not False or getter['version']!='2025.1'or getter['result']!={'return':time}):
            raise ValueError('Original move independent user getter/full journal differs')
        modes.append({'position':m['request']['args']['position'],'returned_time_ms':time,'observed_time_ms':time})
    return {'profile':p,'archive':archive,'archive_source':r['archive_source'],'read':read,'sources':source,'facts':{
        'original_candidate':r['original_candidate'],'original_context':context,'original_finalization':'PASS','physical_cleanup_complete':True,
        'global_pass_transferred':False,'actual_control':PREFIX+'moveCursor','modes':modes,'continuing_position_verified':False,'capture_completeness_verified':False}}


def _original_sources(original,root):
    if 'sources'in original:return original['sources']
    profile=cursor.review(root)['profiles'][original['profile']['cursor_route']]
    return cursor.review(root)['source_maps'][profile['candidate']]['sources']


def _original_transport(original,root):
    if 'archive_source'in original:return original.get('archive_name',Path(original['archive_source']).name),original['archive_source']
    p=cursor.review(root)['profiles'][original['profile']['cursor_route']]
    return 'cursor-'+p['version']+'-'+p['host']+'-original.json.gz',p['archive_source']
