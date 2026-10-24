"""Closed transport lifetime evidence; ACKs and state observations stay distinct."""
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
from tests.support import fixed_runtime_read_evidence as fixed

PREFIX='ak.wwise.core.transport.'
URIS=frozenset(PREFIX+n for n in ('create','destroy','executeAction','prepare','useOriginals','getList','getState'))
SUPPORT='tests/fixtures/runtime-transport/support-review.json'
SUPPORT_SHA='0d73058e2ff6737b9fcff18b134b130e41be48845c82b48edf393fc1e3f4e85d'
CONTRACT='waapi-skill.retained-transport-assessment/v1'


def review(root=audit.ROOT):
    data=remaining._read_pin(root/SUPPORT,SUPPORT_SHA)
    expected={k:v for k,v in remaining.review(root)['entries'].items()if v['route'].split('|')[-1]in URIS}
    if (len(expected)!=1486 or data['entries']!=expected or len(data['profiles'])!=64
            or data['policy_sha256']!=remaining.POLICY_SHA or len(data['normalized_identities'])!=144):
        raise ValueError('Exact1486 transport roster/history differs')
    return data


def exact_entry(branch,root):
    entry=remaining.exact_entry(branch,root)
    if branch['id']not in review(root)['entries']:raise ValueError('Only exact1486 transport rows qualify')
    return entry


@lru_cache(maxsize=32)
def _provider(label,root,signature):
    data=review(root);p=data['providers'][label];probe=p['probe']
    # Reuse the existing complete original-archive/context/source/cleanup validator.
    # The cursor/diagnostic fact itself earns no transport credit.
    if probe['kind']=='cursor':
        from tests.support import runtime_cursor_evidence as cursor
        original=cursor.original_cursor(probe['route'],root=root)
        sources=cursor.review(root)['source_maps'][p['original_candidate']]['sources']
    else:
        from tests.support import extra_runtime_read_evidence as extra
        original=extra.original(probe['identity'],root=root)
        sources=original['descriptor']['sources']
    path=root/p['archive_source'];encoded=json.loads(gzip.decompress(path.read_bytes()))['files']
    if (runtime.sha(path.read_bytes())!=p['archive_sha256']or len(encoded)!=p['archive_files']
            or audit.digest(encoded)!=p['archive_map_sha256']):raise ValueError('Exact whole transport original differs')
    return original['read'],sources,original['facts']


def original_transport(route,base=None,*,root=audit.ROOT):
    data=review(root);profile=data['profiles'][route];p=data['providers'][profile['provider']]
    source=root/p['archive_source'];stat=source.stat()
    read,sources,facts=_provider(profile['provider'],root,(stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns))
    name='transport-origin-'+profile['provider']+'.json.gz'
    archive={'artifact':name,'sha256':p['archive_sha256']}
    if base is not None:
        read=runtime.archive_reader(archive,Path(base))
        encoded=json.loads(gzip.decompress((Path(base)/name).read_bytes()))['files']
        if len(encoded)!=p['archive_files']or audit.digest(encoded)!=p['archive_map_sha256']:raise ValueError('Exact portable transport whole archive differs')
    raw=read(profile['raw_path']);packet=json.loads(raw);locator=profile['request_source'];body=read(locator['path'])
    doc=json.loads(body)if locator['line']is None else json.loads(body.splitlines()[locator['line']])
    issued=completion.pointer_value(doc,locator['pointer'])
    call=({'uri':issued['request']['arguments']['api'],'args':issued['request']['arguments']['args'],
        'options':issued['request']['arguments']['options'],'result':issued['result']}if locator['kind']=='agent-result'else issued)
    report=json.loads(read(p['report_path']));context=completion.native_host_context(report['host'],'isCommandLine')
    if (runtime.sha(raw)!=profile['raw_sha256']or runtime.sha(body)!=locator['sha256']or call!=profile['call']
            or packet['api']!=call['uri']or packet['ok']is not True or packet['dry_run']is not False
            or packet['result']!=call['result']or context!={k:v for k,v in zip(('version','host','build'),route.split('|')[:3])}
            or packet['version']!=context['version']or report['candidate']!=p['original_candidate']):
        raise ValueError('Exact original transport request/result/session/route differs')
    from wwise_waapi.builders.schema import validate_resolved_semantic_result
    validate_resolved_semantic_result(call['uri'],call['result'],version=context['version'])
    # prepare/useOriginals are actual accepted requests, never prepared-state/global-mode proof.
    retained={'original_candidate':p['original_candidate'],'original_context':context,
        'original_finalization':facts['original_finalization'],'physical_cleanup_complete':True,
        'global_pass_transferred':False,'acoustic_output_verified':False,'global_mode_restoration_verified':False,
        'business_boundary':'acknowledgment_schema_only'if call['uri']in {PREFIX+'prepare',PREFIX+'useOriginals'}else'owned_transport_identity_bounded_state_lifetime'}
    return {'profile':profile,'provider':p,'archive':archive,'call':call,'read':read,'sources':sources,'facts':retained}


def code_bindings(branch):
    source='skills/waapi-skill/wwise_waapi/'
    read=branch['route'].endswith(('.getState','.getList'))
    return {key:{'source':source+symbol,'selector':branch['pointer']}for key,symbol in (
        ('construction','runtime_inspection_business.py#materialize_runtime_inspection_business_request'if read else'runtime_inspection_business.py#materialize_runtime_control_business_request'),
        ('validation','builders/schema.py#validate_resolved_semantic_result'),
        ('verifier','runtime_transport_handles.py#RuntimeTransportHandleStore'))}


def _call(row):return {k:row[k]for k in ('uri','args','options','result')}
def _choice(argv,flag,default=None):return argv[argv.index(flag)+1]if flag in argv else default


@lru_cache(maxsize=64)
def _session(encoded):
    session=json.loads(encoded);trace=session['trace'];calls=session['calls'];stages=session['stages']
    if not 1<=len(trace)<=2048 or not 1<=len(calls)<=128 or not 1<=len(stages)<=32:raise ValueError('Bounded transport lifecycle required')
    allowed=URIS|{'ak.wwise.core.getInfo','ak.wwise.core.getProjectInfo','ak.wwise.core.object.get'}
    if any(set(r)!={'ordinal','uri','args','options','result'}or type(r['ordinal'])is not int or r['ordinal']!=i or r['uri']not in allowed for i,r in enumerate(trace)):
        raise ValueError('Exact finite transport trace differs')
    contexts=[completion.native_host_context(r['result'],'isCommandLine')for r in trace if r['uri']=='ak.wwise.core.getInfo']
    infos=[r['result']for r in trace if r['uri']=='ak.wwise.core.getInfo']
    if not contexts or any(c!=contexts[0]for c in contexts)or any(x!=infos[0]for x in infos):raise ValueError('Transport live host/build/session drift')
    context=contexts[0];cursor=0
    for call in calls:
        g=call['gateway'];end=call['native_end']
        if (g['exit_code']!=0 or g['payload'].get('ok')is not True or type(call['native_start'])is not int or call['native_start']!=cursor
                or type(end)is not int or not cursor<=end<=len(trace)
                or 'agent_result'in g['payload']and list(g['payload'])[-1]!='agent_result'):raise ValueError('Actual public transport phase/span differs')
        cursor=end
    if cursor!=len(trace):raise ValueError('Unattributed transport native trace')
    lifetimes={};cursor=0;selected=[]
    for stage in stages:
        start,end=stage['start'],stage['end'];uri=stage['uri'];part=calls[start:end]
        if any(type(stage[k])is not int for k in ('start','end','receipt_index'))or start!=cursor or end<=start or stage['receipt_index']!=end-1 or uri not in URIS:raise ValueError('Transport stage partition differs')
        cursor=end;argvs=[c['gateway']['argv']for c in part];commands=[a[0]for a in argvs];payload=part[-1]['gateway']['payload']
        own=trace[part[0]['native_start']:part[-1]['native_end']]
        if uri in {PREFIX+'getList',PREFIX+'getState'}:
            if uri.endswith('.getList'):
                if commands!=['request-schema','typed-zero-call']or argvs[0]!=['request-schema',uri]or argvs[1]!=['typed-zero-call',uri,'--schema-digest',part[0]['gateway']['payload']['schema_digest']]:raise ValueError('Exact getList managed read required')
            elif commands!=['core-call']or len(argvs[0])!=4 or argvs[0][:3]!=['core-call',uri,'--transport-handle']:raise ValueError('Exact issued-handle getState required')
            targets=[r for r in own if r['uri']==uri]
            if len(targets)!=1:raise ValueError('One direct transport read required')
            native=_call(targets[0])
            if uri.endswith('.getList'):
                if native['args']!={}or native['options']!={}or payload['agent_result']!=native['result']:raise ValueError('Whole getList result changed')
            else:
                handle=argvs[0][-1]
                if handle not in lifetimes or native['args']!={'transport':lifetimes[handle]}or native['options']!={}or payload['agent_result']!={'transport_handle':handle,**native['result']}:raise ValueError('Exact live handle/state mapping differs')
        else:
            bind=uri.endswith(('.create','.prepare'));expected=['draft-start']+(['draft-bind-object']if bind else[])+['draft-declare-runtime-control-plan','draft-check','preview-from-draft','transaction-show','confirm','execute','verify']
            if commands!=expected or argvs[0]!=['draft-start',uri]:raise ValueError('Complete public transport Draft/Preview/once execution required')
            offset=int(bind);decl=argvs[1+offset];preview=part[3+offset]['gateway']['payload'];shown=part[4+offset]['gateway']['payload'];executed=part[6+offset]['gateway']['payload'];tx=preview['transaction_id'];seal=preview['artifact_hash']
            if (argvs[4+offset]!=preview['next_command']['gateway_argv']or argvs[5+offset]!=shown['next_command']['gateway_argv']
                    or argvs[6+offset]!=['execute',tx]or argvs[7+offset]!=executed['next_command']['gateway_argv']
                    or any(x.get('transaction_id')!=tx or x.get('artifact_hash')!=seal for x in (shown,executed,payload))
                    or payload.get('automatic_retry')is not False):raise ValueError('Sealed transport confirmation/continuation differs')
            mutation=[r for r in own if r['uri']in URIS-{PREFIX+'getList',PREFIX+'getState'}]
            if len(mutation)!=1 or mutation[0]['uri']!=uri:raise ValueError('Transport mutation must execute exactly once')
            native=_call(mutation[0]);result=payload['agent_result']
            if result['request']['arguments']!={'api':uri,'args':native['args'],'options':native['options']}or result['result']!=native['result']or result['executed']is not True:raise ValueError('Exact transport public request/result differs')
            args={}
            if bind:
                bound=part[1]['gateway']['payload']['bound_object']['handle']
                if _choice(decl,'--target-handle')!=bound:raise ValueError('Bound target handle substituted')
                bind_rows=[r for r in trace[part[1]['native_start']:part[1]['native_end']]if r['uri']=='ak.wwise.core.object.get']
                ids=[x['id']for r in bind_rows for x in r['result'].get('return',[])if x.get('id')==native['args'].get('object')]
                if not ids:raise ValueError('Exact live target identity readback absent')
                args['object']=ids[-1]
                if uri.endswith('.create')and '--game-object-id'in decl:args['gameObject']=int(_choice(decl,'--game-object-id'))
            elif uri.endswith('.useOriginals'):args={'enable':{'originals':True,'converted':False}[_choice(decl,'--audition-media')]}
            else:
                handle=_choice(decl,'--transport-handle')
                if uri.endswith('.destroy')or _choice(decl,'--transport-scope')=='one-transport':
                    if handle not in lifetimes:raise ValueError('Unknown or retired transport authority')
                    args['transport']=lifetimes[handle]
                elif _choice(decl,'--transport-scope')!='all-active'or handle is not None:raise ValueError('Unknown transport scope')
                if uri.endswith('.executeAction'):args['action']={'play':'play','stop':'stop','pause':'pause','toggle-play-stop':'playStop','play-directly':'playDirectly'}[_choice(decl,'--audition-action')]
            if native['args']!=args or native['options']!={}:raise ValueError('Disclosed transport choices/native compiler differ')
            if uri.endswith(('.prepare','.useOriginals')):
                if payload['status']!='result_schema_checked'or payload['verified']is not False:raise ValueError('ACK-only transport effect overclaim')
            elif payload['verified']is not True:raise ValueError('Transport identity/state/lifetime not verified')
            if uri.endswith('.create'):
                handle=result['business_result']['transport_handle'];native_id=native['result']['transport']
                if type(native_id)is not int or not 0<=native_id<=0xffffffff or not handle.startswith('trh1-')or handle in lifetimes:raise ValueError('Usable transport ID/handle required')
                rows=[x for r in own if r['uri']==PREFIX+'getList'for x in r['result'].get('list',[])if x.get('transport')==native_id and x.get('object')==args['object']]
                if not rows or 'gameObject'in args and any(r['gameObject']!=args['gameObject']for r in rows):raise ValueError('Created transport association missing')
                lifetimes[handle]=native_id
            elif uri.endswith('.destroy'):lifetimes.pop(handle)
        selected.append(native)
    if cursor!=len(calls)or lifetimes:raise ValueError('Complete independent transport cleanup missing')
    return context,selected


def _uncertain_create(cap):
    """The sole native-valid missing-ID outcome, not a generic failed-flow waiver."""
    from wwise_waapi.canonical import canonical_sha256
    from wwise_waapi.builders.schema import validate_resolved_semantic_result
    trace=cap['native_reads'];calls=cap['public_calls'];native=cap['native_call'];gateway=cap['gateway']
    if (set(cap['transport_preservation'])!={'kind','journal'}or cap['transport_preservation'].get('kind')!='native-valid-create-id-omitted'
            or native['uri']!=PREFIX+'create'or native['result']!={}or len(calls)!=8 or not 1<=len(trace)<=128
            or [c['gateway']['argv'][0]for c in calls]!=['draft-start','draft-bind-object','draft-declare-runtime-control-plan',
                'draft-check','preview-from-draft','transaction-show','confirm','execute']):raise ValueError('Only exact missing-create-ID preservation qualifies')
    infos=[r['result']for r in trace if r['uri']=='ak.wwise.core.getInfo']
    if not infos or any(x!=infos[0]for x in infos):raise ValueError('Uncertain create live session drift')
    context=completion.native_host_context(infos[0],'isCommandLine');cursor=0
    for i,c in enumerate(calls):
        g=c['gateway'];end=c['native_end']
        if (type(c['native_start'])is not int or c['native_start']!=cursor or type(end)is not int or not cursor<=end<=len(trace)
                or g['exit_code']!=(2 if i==7 else 0)or g['payload'].get('ok')is not (i!=7)):
            raise ValueError('Exact uncertain create public span differs')
        cursor=end
    if cursor!=len(trace)or calls[-1]['gateway']!=gateway:raise ValueError('Uncertain create terminal packet differs')
    allowed={PREFIX+'create','ak.wwise.core.getInfo','ak.wwise.core.getProjectInfo','ak.wwise.core.object.get'}
    if any(set(r)!={'ordinal','uri','args','options','result'}or type(r['ordinal'])is not int or r['ordinal']!=i or r['uri']not in allowed for i,r in enumerate(trace)):
        raise ValueError('Uncertain create may not retry/clean up an unknown ID')
    create,=[r for r in trace if r['uri']==PREFIX+'create']
    if _call(create)!=native or not calls[-1]['native_start']<=create['ordinal']<calls[-1]['native_end']:raise ValueError('One actual create execution required')
    validate_resolved_semantic_result(PREFIX+'create',native['result'],version=context['version'])
    preview=calls[4]['gateway']['payload'];shown=calls[5]['gateway']['payload'];payload=gateway['payload'];tx=preview['transaction_id'];seal=preview['artifact_hash']
    if (calls[0]['gateway']['argv']!=['draft-start',PREFIX+'create']or calls[5]['gateway']['argv']!=preview['next_command']['gateway_argv']
            or calls[6]['gateway']['argv']!=shown['next_command']['gateway_argv']or gateway['argv']!=['execute',tx]
            or payload.get('transaction_id')!=tx or shown.get('artifact_hash')!=seal
            or payload.get('state')!='indeterminate'or payload.get('status')!='transport_handle_persistence_failed'
            or payload.get('error_code')!='TRANSPORT_HANDLE_RESULT_INVALID'or payload.get('executed')is not True
            or payload.get('verified')is not False or payload.get('automatic_retry')is not False or payload.get('agent_result')
            or payload['cleanup']['status']!='unknown'or payload['cleanup']['spec']['binding']['materialized']is not False):
        raise ValueError('Missing native ID must retain uncertainty/no handle/unknown cleanup')
    target=_choice(calls[1]['gateway']['argv'],'--object-id')
    if (native['args']!={'object':target}or native['options']!={}
            or _choice(calls[2]['gateway']['argv'],'--target-handle')!=calls[1]['gateway']['payload']['bound_object']['handle']
            or not any(r.get('id')==target for c in trace if c['uri']=='ak.wwise.core.object.get'for r in c['result'].get('return',[]))):
        raise ValueError('Uncertain create must retain its exact public target binding')
    journal=cap['transport_preservation']['journal'];previous=''
    if [e['event_type']for e in journal]!=['preview_created','confirmation_requested','confirmed','execution_started','execution_indeterminate']:
        raise ValueError('Actual uncertain creation journal required')
    transitions=[(None,'draft'),('draft','awaiting_confirmation'),('awaiting_confirmation','confirmed'),('confirmed','executing'),('executing','indeterminate')]
    for i,event in enumerate(journal):
        if ((event['from_state'],event['to_state'])!=transitions[i]or type(event['sequence'])is not int or event['transaction_id']!=tx or event['artifact_hash']!=seal or event['sequence']!=i+1
                or event['previous_event_hash']!=previous or event['event_hash']!=canonical_sha256({k:v for k,v in event.items()if k!='event_hash'})):
            raise ValueError('Uncertain creation durable journal chain differs')
        previous=event['event_hash']
    last=journal[-1];dispatch=last['details']['dispatch_result']
    if (last['to_state']!='indeterminate'or last['details']['automatic_retry']is not False
            or last['details']['phase']!='transport_lifetime_after_native_dispatch'or dispatch['api']!=native['uri']
            or dispatch['version']!=context['version']or dispatch['ok']is not True or dispatch['dry_run']is not False
            or dispatch['error_code']is not None or dispatch['result']!={}or payload['dispatch_result']!=dispatch):raise ValueError('Actual native-valid absent result not preserved')
    return context


def write_transport_preservation_receipt(path,gateway,native_call,*,nodeid,phase_reports,source_context,native_reads,public_calls,journal):
    """Operation-local positive handling proof for exactly two conditional leaves."""
    cap={'contract':'waapi-skill.runtime-read-program/v1','nodeid':nodeid,'phase_reports':phase_reports,
        'source_context':source_context,'source_unchanged':True,'gateway':gateway,'native_call':native_call,
        'native_reads':native_reads,'public_calls':public_calls,
        'transport_preservation':{'kind':'native-valid-create-id-omitted','journal':journal}}
    _capture(cap,audit.ROOT)
    return runtime.write_json(path,cap)


def _capture(cap,root):
    uri=cap['native_call']['uri']
    if (uri not in URIS or cap['contract']!='waapi-skill.runtime-read-program/v1'
            or cap['phase_reports']!=dict.fromkeys(('setup','call','teardown'),'passed')or cap['source_unchanged']is not True
            or cap['source_context']!=runtime.program_source_context(root,flow=uri)):raise ValueError('Exact transport teardown/source required')
    if cap.get('transport_preservation')is not None:return _uncertain_create(cap)
    context,natives=_session(json.dumps({'calls':cap['public_calls'],'trace':cap['native_reads'],'stages':cap['transport_stages']}))
    stage=cap['transport_stage']
    if stage not in cap['transport_stages']or cap['gateway']!=cap['public_calls'][stage['receipt_index']]['gateway']or natives[cap['transport_stages'].index(stage)]!=cap['native_call']:
        raise ValueError('Independent transport stage/native request differs')
    return context


def _normalized_identity(branch,cap,root):
    """Exact business identity equivalence; never literal native text dispatch."""
    approved=review(root)['normalized_identities'].get(branch['id'])
    if approved is None:return None
    stage=cap['transport_stage'];part=cap['public_calls'][stage['start']:stage['end']]
    if len(part)!=9 or part[1]['gateway']['argv'][0]!='draft-bind-object':return None
    argv=part[1]['gateway']['argv'];selector=approved['selector']
    if selector=='qualified-name':
        if '--exact-type-name'not in argv:return None
        index=argv.index('--exact-type-name');kind,name=argv[index+1:index+3];spelling=kind+':'+name
    else:
        segments=[argv[i+1]for i,x in enumerate(argv)if x=='--object-path-segment']
        if not segments:return None
        spelling='\\'+'\\'.join(segments)
    guid=cap['native_call']['args'].get('object')
    before=part[1]['native_start'];after=part[1]['native_end'];trace=cap['native_reads']
    matches=[row for call in trace[before:after]if call['uri']=='ak.wwise.core.object.get'
        for row in call['result'].get('return',[])if row.get('id')==guid
        and (row.get('type')==kind and row.get('name')==name if selector=='qualified-name'else row.get('path')==spelling)]
    exact=[row for call in trace[after:]if call['uri']=='ak.wwise.core.object.get'and guid in call['args'].get('from',{}).get('id',[])
        for row in call['result'].get('return',[])if row.get('id')==guid]
    if not matches or not any(all(row.get(k)==matches[0].get(k)for k in ('id','name','type','path'))for row in exact):
        raise ValueError('Normalized identity lacks exact public selector and later GUID readback')
    version,host,_,_,uri=branch['route'].split('|')
    catalog=remaining._log_catalog(root,version,host)
    schema=catalog['schemas'][uri]['argsSchema']['properties']['object']
    definition=catalog['definitions']['documents']['waapi_definitions.json']['definitions']
    if schema.get('$ref')!='waapi_definitions.json#/definitions/objectArg':raise ValueError('Native object identity reference differs')
    pointer=branch['pointer'];target='uniqueQualifiedName'if selector=='qualified-name'else'objectPathArg'
    if '/objectArg/anyOf/'in pointer:
        index=int(pointer.split('/objectArg/anyOf/')[1].split('/')[0])
        if definition['objectArg']['anyOf'][index].get('$ref')!='#/definitions/'+target:raise ValueError('Exact primary objectArg arm differs')
    elif '/definitions/'+target not in pointer:raise ValueError('Exact primary object identity definition differs')
    if not fixed.predicate(branch,fixed.schema_node(branch,root),spelling,root):raise ValueError('Public identity does not satisfy matching native identity meaning')
    return {'selector':selector,'public_identity':spelling,'resolved_guid':guid,'native_pointer':'/native_call/args/object',
        'meaning':'Exact live business identity to GUID; no literal name/path dispatch claim'}


def validate_evidence(record,binding,branch,category,base,root,edges=None):
    exact_entry(branch,root)
    if category!='program':raise ValueError('Transport root requires closed retained native attachment')
    cap=record['runtime_read_program'];context=_capture(cap,root)
    if (context!={k:v for k,v in zip(('version','host','build'),branch['route'].split('|')[:3])}
            or cap['native_call']['uri']!=branch['route'].split('|')[-1]or record['gateway']!=cap['gateway']or record['native_call']!=cap['native_call']
            or record['relevant_sources']!=cap['source_context']['packaged']or binding['input']['gateway_argv']!=cap['gateway']['argv']
            or any(binding.get(k)!=v for k,v in code_bindings(branch).items())):raise ValueError('Exact transport branch/current public context differs')
    if cap.get('transport_preservation')is not None and branch['pointer']not in {'/resultSchema/@empty/object','/resultSchema/properties/transport/@presence/absent'}:
        raise ValueError('Uncertain create handling cannot grant another leaf or native root')
    pointer=binding['observation_pointer']
    if binding.get('normalized_identity')is not None:
        normalized=_normalized_identity(branch,cap,root)
        if normalized is None or binding['normalized_identity']!=normalized or pointer!=normalized['native_pointer']:
            raise ValueError('Exact public identity normalization differs')
        return {'observation_pointer':pointer}
    completion.exact_observation_pointer(branch,binding,'/native_call',branch['pointer'].split('/')[1].removesuffix('Schema'),edges or{})
    value=remaining._occurrence_value(record,pointer,branch)
    if not fixed.predicate(branch,fixed.schema_node(branch,root),value,root):raise ValueError('Exact transport branch predicate absent')
    if cap.get('transport_preservation')is not None:
        return {'transport_create_omission_preserved':True}


def qualified_result(descriptor,assessment,branch,candidate,scope_kind,base,binding,root,edges):
    entry=exact_entry(branch,root)
    if branch['pointer']!='/resultSchema'or entry['role']!='native_business_anchor'or scope_kind!='product':raise ValueError('Only exact transport root qualifies')
    original=original_transport(branch['route'],base,root=root);cap=completion.read_sealed_artifact(assessment['program_capture'],base)
    expected={'contract':CONTRACT,'branch_id':branch['id'],'profile':original['profile'],'support_review':assessment['support_review'],
        'archive':original['archive'],'program_capture':assessment['program_capture'],'facts':original['facts']}
    record=completion.read_sealed_artifact(descriptor,base)
    if (assessment!=expected or assessment['support_review']['sha256']!=SUPPORT_SHA or completion.read_sealed_artifact(assessment['support_review'],base)!=review(root)
            or record!={'candidate_sha256':candidate,'scope_kind':'product','evidence_kind':'qualified_retained_transport_fact','branch_id':branch['id'],
                'native_shape_sha256':branch['shape_sha256'],'assessment_sha256':binding['qualified_runtime_read_attachment']['sha256'],
                'relevant_sources':original['sources'],'retained_facts':original['facts']}
            or cap['native_call']!=original['call']):raise ValueError('Exact original transport fact/current complete request replay differs')
    validate_evidence({'gateway':cap['gateway'],'native_call':cap['native_call'],'runtime_read_program':cap,'relevant_sources':cap['source_context']['packaged']},binding,branch,'program',base,root,edges)
    return 'passed',None


def write_transport_bundle(output,captures,*,inventory,name_prefix=''):
    versions={r['version']for r in inventory['native_coverage']['routes']if r['uri']in URIS}
    if (not isinstance(name_prefix,str)or name_prefix and (len(versions)!=1
            or name_prefix!='transport-'+next(iter(versions))+'-')):
        raise ValueError('Only the closed matching-version transport prefix qualifies')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(audit.ROOT/SUPPORT,output/'transport-support-review.json')
    candidate=inventory['native_coverage']['candidate_sha256'];seen=set()
    index={'contract':'waapi-skill.branch-evidence-index/v1','base':'.','entries':[],'qualified_runtime_read_attachments':[]}
    requirements={'contract':'waapi-skill.branch-evidence-requirements/v1','branches':{}}
    edges={b['id']:b for b in inventory['native_coverage']['obligations']if b['kind']=='reference'}
    def write(name,value):return runtime.write_json(output/name,value)
    def desc(name):return {'artifact':name,'sha256':runtime.sha((output/name).read_bytes())}
    for number,path in enumerate(captures):
        cap=json.loads(Path(path).read_bytes());context=_capture(cap,audit.ROOT)
        route,=[r for r in inventory['native_coverage']['routes']if r['uri']==cap['native_call']['uri'] and all(r[k]==v for k,v in context.items())]
        public,=[r for r in inventory['routes']if r['id']==route['public_route']]
        mappings=[]
        for branch in inventory['native_coverage']['obligations']:
            if branch['id']in seen or branch['route']!=route['id']:continue
            exact_entry(branch,audit.ROOT)
            if cap.get('transport_preservation')and branch['pointer']not in {'/resultSchema/@empty/object','/resultSchema/properties/transport/@presence/absent'}:continue
            normalized=_normalized_identity(branch,cap,audit.ROOT)
            if normalized:
                mappings.append((branch,[],normalized['native_pointer'],normalized));continue
            for chain in runtime._contribution_chains(branch,edges):
                hit=next(((p,v)for p,v in runtime._contribution_occurrences(cap,runtime._contribution_pattern(branch,chain,edges))
                    if fixed.predicate(branch,fixed.schema_node(branch),v)),None)
                if hit:mappings.append((branch,chain,hit[0],None));break
        if not mappings:continue
        prefix=(name_prefix or'transport-')+str(number)+'-';cp=write(prefix+'capture.json',cap)
        program={'candidate_sha256':candidate,'scope_kind':'product','relevant_sources':cap['source_context']['packaged'],
            'gateway':cap['gateway'],'native_call':cap['native_call'],'runtime_read_program':cap,
            'invocation':{'phase':'final','outcome':'PASS','node_outcomes':[{'nodeid':cap['nodeid'],'outcome':'PASS'}]},'branch_assertions':{}}
        bindings={'contract':'waapi-skill.branch-bindings/v1','bindings':{}};policies={'contract':requirements['contract'],'branches':{}}
        for branch,chain,pointer,normalized in mappings:
            identity=branch['id'];entry=exact_entry(branch,audit.ROOT);pp='/gateway/payload/dispatch_result/result'if cap.get('transport_preservation')else'/gateway/payload/agent_result'
            program['branch_assertions'][identity]={'native_shape_sha256':branch['shape_sha256'],'native_route':branch['route'],
                'checks':[({'pointer':pointer,'absent':True}if branch['kind']=='optional_presence'and branch['value']=='absent'
                    else {'pointer':pointer,'equals':completion.pointer_value(program,pointer)}),{'pointer':pp,'equals':completion.pointer_value(program,pp)}]}
            binding={'branch_id':identity,'native_shape_sha256':branch['shape_sha256'],'public_route':public['id'],'public_route_sha256':audit.digest(public),
                'input':{'gateway_argv':cap['gateway']['argv'],'selector':pointer},'dispatch_pointer':'/native_call','observation_pointer':pointer,
                'gateway_observation_pointer':pp,'reference_chain':chain,**({'normalized_identity':normalized}if normalized else{}),'relevant_sources':sorted(cap['source_context']['packaged']),'evidence':{},**code_bindings(branch)}
            validate_evidence(program,binding,branch,'program',output,audit.ROOT,edges)
            bindings['bindings'][identity]=binding;policies['branches'][identity]=remaining.policy(entry);seen.add(identity)
            if entry['role']=='native_business_anchor':
                original=original_transport(route['id']);p=original['profile'];provider=original['provider']
                if cap['native_call']!=original['call']:
                    raise ValueError('Transport native root requires actual original request/result replay first')
                name=original['archive']['artifact'];shutil.copyfile(audit.ROOT/provider['archive_source'],output/name)
                assessment=write(prefix+'assessment.json',{'contract':CONTRACT,'branch_id':identity,'profile':p,'support_review':desc('transport-support-review.json'),
                    'archive':desc(name),'program_capture':cp,'facts':original['facts']})
                evidence=write(prefix+'qualified.json',{'candidate_sha256':candidate,'scope_kind':'product','evidence_kind':'qualified_retained_transport_fact',
                    'branch_id':identity,'native_shape_sha256':branch['shape_sha256'],'assessment_sha256':assessment['sha256'],
                    'relevant_sources':original['sources'],'retained_facts':original['facts']})
                index['qualified_runtime_read_attachments'].append(write(prefix+'attachment.json',{'contract':'waapi-skill.qualified-retained-read-attachment/v1',
                    'branch_id':identity,'assessment':assessment,'evidence':evidence}))
        pd={**write(prefix+'program.json',program),'nodeid':cap['nodeid']}
        for b in bindings['bindings'].values():b['evidence']['program']=pd
        bd=write(prefix+'bindings.json',bindings);rd=write(prefix+'requirements.json',policies)
        index['entries'].append({'id':prefix,'bindings':bd,'origin':{'bindings':bd,'program':desc(prefix+'program.json'),'requirements':rd,'capture':cp}})
        requirements['branches'].update(policies['branches'])
    if seen!={b['id']for b in inventory['native_coverage']['obligations']}:
        raise ValueError('Missing exact transport branch occurrences: '+str(set(b['id']for b in inventory['native_coverage']['obligations'])-seen))
    write('requirements.json',requirements);write('index.json',index)
    return output/'index.json'
