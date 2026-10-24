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
SUPPORT_SHA='1d580e740482d4a09ba786941d94609a708a25d73e113f77457157d089be214a'
CONTRACT='waapi-skill.retained-owned-control-assessment/v1'


def review(root=audit.ROOT):
    data=remaining._read_pin(root/SUPPORT,SUPPORT_SHA)
    expected={k:v for k,v in remaining.review(root)['entries'].items()if v['route'].split('|')[-1]in URIS}
    if (len(expected)!=298 or data['entries']!=expected or data['policy_sha256']!=remaining.POLICY_SHA
            or data['cursor_support_sha256']!=cursor.SUPPORT_SHA or len(data['meter_normalized_inputs'])!=64):
        raise ValueError('Exact298 owned controls/source policy differs')
    return data


def exact_entry(branch,root=audit.ROOT):
    entry=remaining.exact_entry(branch,root)
    if branch['id']not in review(root)['entries']:raise ValueError('Only exact298 owned controls qualify')
    return entry


def original_meter(route,base=None,*,root=audit.ROOT):
    p=review(root)['profiles'].get(route)
    if p is None or p['provider']!='r92':raise ValueError('No exact retained native meter ACK for this route')
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
    if paired['cursor_route']!=p['cursor_route']or paired['object']!=p['object']or last['state']!='result_schema_checked'or last['verified']is not False:
        raise ValueError('Same-object balanced native registration pair missing')
    return {'object':p['object'],'profile':p,'archive':original['archive'],'read':read,
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
    raise ValueError('Owned control family mapper not implemented')


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
    original=(original_save if branch['route'].endswith('.saveCapture')else original_meter)(branch['route'],base,root=root);p=original['profile'];cp=cursor.review(root)['profiles'][p['cursor_route']]
    cap=completion.read_sealed_artifact(assessment['program_capture'],base);record=completion.read_sealed_artifact(descriptor,base)
    expected={'contract':CONTRACT,'branch_id':branch['id'],'profile':p,'support_review':assessment['support_review'],'archive':original['archive'],'program_capture':assessment['program_capture'],'facts':original['facts']}
    if branch['route'].endswith('.saveCapture'):
        expected['destination_binding']={'mode':'exact-authorized-directory-plus-name','original':p['request']['args']['file'],'program':cap['native_call']['args']['file']}
    expected_args=cap['native_call']['args']if branch['route'].endswith('.saveCapture')else p['request']['args']
    if (assessment!=expected or assessment['support_review']['sha256']!=SUPPORT_SHA or completion.read_sealed_artifact(assessment['support_review'],base)!=review(root)
            or record!={'candidate_sha256':candidate,'scope_kind':'product','evidence_kind':'qualified_retained_owned_control_fact','branch_id':branch['id'],
                'native_shape_sha256':branch['shape_sha256'],'assessment_sha256':binding['qualified_runtime_read_attachment']['sha256'],
                'relevant_sources':cursor.review(root)['source_maps'][cp['candidate']]['sources'],'retained_facts':original['facts']}
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
        prefix=(name_prefix or'owned-controls-')+str(number)+'-';cp=write(prefix+'capture.json',cap)
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
                original=(original_save if uri==PREFIX+'saveCapture'else original_meter)(route['id']);p=original['profile'];cp_profile=cursor.review()['profiles'][p['cursor_route']]
                expected_args=cap['native_call']['args']if uri==PREFIX+'saveCapture'else p['request']['args']
                if cap['native_call']!={'uri':uri,'args':expected_args,'options':{},'result':p['result']}:
                    raise ValueError('Capture native root requires actual original complete request/result replay first')
                name='cursor-'+cp_profile['version']+'-'+cp_profile['host']+'-original.json.gz';shutil.copyfile(audit.ROOT/cp_profile['archive_source'],output/name)
                assessment=write(prefix+'assessment.json',{'contract':CONTRACT,'branch_id':identity,'profile':p,'support_review':desc('owned-control-support-review.json'),
                    'archive':desc(name),'program_capture':cp,'facts':original['facts'],
                    **({'destination_binding':{'mode':'exact-authorized-directory-plus-name','original':p['request']['args']['file'],'program':cap['native_call']['args']['file']}}if uri==PREFIX+'saveCapture'else{})})
                evidence=write(prefix+'qualified.json',{'candidate_sha256':candidate,'scope_kind':'product','evidence_kind':'qualified_retained_owned_control_fact',
                    'branch_id':identity,'native_shape_sha256':branch['shape_sha256'],'assessment_sha256':assessment['sha256'],
                    'relevant_sources':cursor.review()['source_maps'][cp_profile['candidate']]['sources'],'retained_facts':original['facts']})
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
        public,=[r for r in inventory['routes']if r['id']==route['public_route']];prefix=(name_prefix or'owned-controls-')+'boundary-'+str(number)+'-'
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
