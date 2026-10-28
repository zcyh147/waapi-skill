"""Exact capture ACKs and documented default normalization, no hidden-state claims."""
from functools import lru_cache
import json
from pathlib import Path
import shutil

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support import runtime_observation_evidence as runtime
from tests.support import fixed_runtime_read_evidence as fixed
from tests.support import runtime_remaining_evidence as remaining
from tests.support import runtime_cursor_evidence as cursor

URIS=frozenset('ak.wwise.core.profiler.'+n for n in ('enableProfilerData','startCapture','stopCapture'))
SUPPORT='tests/fixtures/runtime-capture-controls/support-review.json'
SUPPORT_SHA='d9d4fc32e8896f63d9ec0cc446b769bdc411e0e8c5fab3a2ddf04645497ade56'
CONTRACT='waapi-skill.retained-capture-control-assessment/v1'


def review(root=audit.ROOT):
    data=remaining._read_pin(root/SUPPORT,SUPPORT_SHA)
    expected={k:v for k,v in remaining.review(root)['entries'].items()if v['route'].split('|')[-1]in URIS}
    if (len(expected)!=672 or data['entries']!=expected or len(data['profiles'])!=30
            or data['policy_sha256']!=remaining.POLICY_SHA or data['cursor_support_sha256']!=cursor.SUPPORT_SHA
            or set(data['normalized_inputs'])!={k for k in expected if k.endswith('/enable/@presence/absent')}):
        raise ValueError('Exact672 capture control scope/defaults differs')
    return data


def exact_entry(branch,root=audit.ROOT):
    entry=remaining.exact_entry(branch,root)
    if branch['id']not in review(root)['entries']:raise ValueError('Only exact672 capture controls qualify')
    return entry


def original_control(route,base=None,*,root=audit.ROOT):
    """Reuse whole original archive/source/physical cleanup, never parent PASS."""
    p=review(root)['profiles'][route];original=cursor.original_cursor(p['cursor_route'],base,root=root)
    read=original['read'];raw=json.loads(read(p['raw_path']));cp=original['profile']
    report=json.loads(read(cp['report_path']))
    calls=report['calls']if cp['host']=='wwise-console'else json.loads(read(cp['node_path']))['receipts']
    chain=p['receipts'];preview,shown,confirmed,executed,verified=chain
    uri=route.split('|')[-1];tx=p['transaction_id'];request=p['request'];payload=verified['payload'];result=payload['agent_result']
    if (any(c not in calls for c in chain)or audit.digest(chain)!=p['receipt_sha256']
            or runtime.sha(read(p['raw_path']))!=p['raw_sha256']or raw['api']!=uri or raw['result']!=p['result']
            or raw['ok']is not True or raw['dry_run']is not False or raw['version']!=cp['version']
            or any(c['exit_code']!=0 or c['payload'].get('ok')is not True for c in chain)
            or preview['argv'][0]not in {'preview-from-draft','typed-zero-call'}
            or shown['argv']not in [preview['payload']['next_command']['gateway_argv'],['transaction-show',tx]]
            or confirmed['argv']!=shown['payload']['next_command']['gateway_argv']
            or executed['argv']!=['execute',tx]or verified['argv']!=executed['payload']['next_command']['gateway_argv']
            or executed['payload']['dispatch_result']['api']!=uri
            or Path(executed['payload']['dispatch_result']['evidence_path']).name!=Path(p['raw_path']).name
            or any(c['payload']['transaction_id']!=tx or c['payload']['artifact_hash']!=preview['payload']['artifact_hash']for c in chain)
            or result['request']['arguments']!=request or result['result']!=raw['result']or request['api']!=uri
            or payload['state']!='result_schema_checked'or payload['verified']is not False
            or payload['verification']['business_state_verified']is not False
            or payload['automatic_retry']is not False or result['executed']is not True):
        raise ValueError('Exact retained control public authorization/once dispatch/weak ACK differs')
    # Every capture-start fact belongs to this same full workflow's paired stop.
    if uri.endswith('.startCapture'):
        stop=review(root)['profiles'][route.rsplit('.',1)[0]+'.stopCapture']
        if stop['cursor_route']!=p['cursor_route']or stop['receipts'][-1]not in calls:
            raise ValueError('Original paired stop missing')
    return {'args':request['args'],'result':raw['result'],'archive':original['archive'],'profile':p,'read':read,
        'facts':{**original['facts'],'actual_control':uri,'verification':'result_schema_checked',
            'business_state_verified':False,'native_optional_enable_omission_observed':False,
            'enabled_settings_verified':False,'capture_running_or_stopped_verified':False,'prior_settings_restoration_verified':False}}


def code_bindings(branch):
    construction=('runtime_inspection_business.py#materialize_runtime_control_business_request'if branch['route'].endswith('.enableProfilerData')
        else'../scripts/gateway.py#preflight_typed_zero_input')
    return {key:{'source':('skills/waapi-skill/scripts/gateway.py#preflight_typed_zero_input'if symbol.startswith('../')else'skills/waapi-skill/wwise_waapi/'+symbol),'selector':branch['pointer']}for key,symbol in (
        ('construction',construction),('validation','builders/schema.py#validate_resolved_semantic_result'),
        ('verifier','operation_registry.py#verify_prepared_operation'))}


def _capture(encoded,root):
    cap=json.loads(encoded);uri=cap['native_call']['uri']
    if cap['source_context']!=remaining._current_context(root,uri,cap['source_context']):raise ValueError('Exact capture control sources changed')
    return _capture_body(encoded,root)


@lru_cache(maxsize=128)
def _capture_body(encoded,root):
    from wwise_waapi.builders.schema import validate_resolved_semantic_result
    cap=json.loads(encoded);native=cap['native_call'];uri=native['uri'];calls=cap['public_calls'];trace=cap['native_reads']
    enable=uri.endswith('.enableProfilerData');count=8 if enable else 6
    if (uri not in URIS or cap['contract']!='waapi-skill.runtime-read-program/v1'
            or cap['phase_reports']!=dict.fromkeys(('setup','call','teardown'),'passed')or cap['source_unchanged']is not True
            or len(calls)!=(count+6 if uri.endswith('.startCapture')else count)or not 1<=len(trace)<=128):
        raise ValueError('Complete bounded capture-control transaction/paired cleanup/teardown required')
    commands=(['draft-start','draft-declare-runtime-control-plan','draft-check','preview-from-draft']if enable else['request-schema','typed-zero-call'])+['transaction-show','confirm','execute','verify']
    if uri.endswith('.startCapture'):commands+=['request-schema','typed-zero-call','transaction-show','confirm','execute','verify']
    cursor_index=0
    for command,item in zip(commands,calls,strict=True):
        receipt=item['gateway'];payload=receipt['payload'];end=item['native_end']
        if (receipt['argv'][0]!=command or receipt['exit_code']!=0 or payload.get('ok')is not True
                or type(item['native_start'])is not int or item['native_start']!=cursor_index
                or type(end)is not int or not cursor_index<=end<=len(trace)
                or 'agent_result'in payload and list(payload)[-1]!='agent_result'):
            raise ValueError('Actual capture public phase/order/native span differs')
        cursor_index=end
    allowed={uri,'ak.wwise.core.getInfo','ak.wwise.core.getProjectInfo','ak.wwise.core.remote.getConnectionStatus'}
    if uri.endswith('.startCapture'):allowed.add('ak.wwise.core.profiler.stopCapture')
    if (cursor_index!=len(trace)or any(set(x)!={'ordinal','uri','args','options','result'}or type(x['ordinal'])is not int or x['ordinal']!=i for i,x in enumerate(trace))):
        raise ValueError('Exact finite native trace differs')
    contexts=[completion.native_host_context(x['result'],'isCommandLine')for x in trace if x['uri']=='ak.wwise.core.getInfo']
    if not contexts or any(x!=contexts[0]for x in contexts):raise ValueError('Capture control host/version drift')
    context=contexts[0]
    if context['version']=='2021.1':allowed.add('ak.wwise.core.object.get')
    if any(x['uri']not in allowed for x in trace):raise ValueError('Unrelated native call in capture control')
    targets=[{k:x[k]for k in ('uri','args','options','result')}for x in trace if x['uri']==uri]
    if targets!=[native]:raise ValueError('Capture control executes exactly once')
    if cap['gateway']!=calls[count-1]['gateway']:raise ValueError('Exact final target Gateway receipt differs')
    def transaction(group,target):
        preview,shown,confirmed,executed,verified=[i['gateway']for i in group[-5:]];p=preview['payload'];tx=p['transaction_id'];seal=p['artifact_hash'];payload=verified['payload'];result=payload['agent_result']
        if (shown['argv']!=p['next_command']['gateway_argv']or confirmed['argv']!=shown['payload']['next_command']['gateway_argv']
                or executed['argv']!=['execute',tx]or verified['argv']!=executed['payload']['next_command']['gateway_argv']
                or any(c['payload'].get('transaction_id')!=tx or c['payload'].get('artifact_hash')!=seal for c in (shown,confirmed,executed,verified))
                or payload.get('automatic_retry')is not False or result.get('executed')is not True
                or result['request']['arguments']!={'api':target['uri'],'args':target['args'],'options':target['options']}
                or result['result']!=target['result']or payload['state']!='result_schema_checked'or payload['verified']is not False
                or payload['verification']['business_state_verified']is not False
                or payload['is_command_line']is not (context['host']=='wwise-console')):
            raise ValueError('Sealed capture Preview/confirmation/once execution/weak result differs')
        validate_resolved_semantic_result(target['uri'],target['result'],version=context['version'])
        if target['options']!={}:raise ValueError('Control options must be empty')
        if target['uri'].endswith('.enableProfilerData'):
            declaration=group[1]['gateway']['argv'];tokens=declaration[declaration.index('--expected-revision')+2:];rows=[]
            names=review(root)['public_data_sets'][context['version']]
            if tokens!=['--capture-data-empty']:
                if not tokens or len(tokens)%3:raise ValueError('Actual explicit capture-data choice missing')
                for offset in range(0,len(tokens),3):
                    flag,name,value=tokens[offset:offset+3]
                    if flag!='--capture-data'or name not in names or value not in {'enable','disable'}:raise ValueError('Exact capture data choice differs')
                    rows.append({'dataType':names[name],'enable':value=='enable'})
            if audit.digest(target['args'])!=audit.digest({'dataTypes':rows}):raise ValueError('Ordered public capture directives/native compiler differs')
            scope=payload['verification']['verification_scope']
            if any(scope.get(k)is not False for k in ('enabled_settings_verified','empty_effect_verified','repeated_data_set_resolution_verified','prior_settings_restoration_verified')):
                raise ValueError('Capture ACK cannot claim enablement/restoration')
        elif group[1]['gateway']['argv']!=group[0]['gateway']['payload']['continuation']['gateway_argv']or target['args']!={}:
            raise ValueError('Zero-value control must follow issued public continuation')
    transaction(calls[:count],native)
    if uri.endswith('.startCapture'):
        stop,=[{k:x[k]for k in ('uri','args','options','result')}for x in trace if x['uri']=='ak.wwise.core.profiler.stopCapture']
        transaction(calls[count:],stop)
    return context


def normalized_input(branch,cap,root):
    source=review(root)['normalized_inputs'].get(branch['id'])
    if source is None:return None
    from wwise_waapi.native_catalog import load_native_catalog
    version,host,_,_,uri=branch['route'].split('|');catalog=load_native_catalog(version,host,root=root/'skills/waapi-skill/resources/native-catalog')
    schema=completion.pointer_value(catalog,source['pointer'])
    if audit.digest(schema)!=source['schema_sha256']or 'Defaults to true when not specified.'not in schema['description']:
        raise ValueError('Exact native default-true source changed')
    declaration=cap['public_calls'][1]['gateway']['argv']
    # The actual compiler trace already binds every explicit public row. Select
    # one true occurrence; absence is semantic normalization, never a wire claim.
    if '--capture-data'not in declaration:return None
    for i,row in enumerate(cap['native_call']['args']['dataTypes']):
        if row['enable']is True:
            return {'public_flag':'--capture-data','public_choice':'enable','native_default':True,
                'source':source,'native_pointer':'/native_call/args/dataTypes/'+str(i)+'/enable'}
    return None


def validate_evidence(record,binding,branch,category,base,root,edges=None):
    exact_entry(branch,root)
    if category!='program':raise ValueError('Capture native ACK requires closed qualified attachment')
    cap=record['runtime_read_program'];context=_capture(json.dumps(cap),root)
    version,host,build,_,_=branch['route'].split('|')
    if (context!={'version':version,'host':host,'build':build}or record['gateway']!=cap['gateway']or record['native_call']!=cap['native_call']
            or record['relevant_sources']!=cap['source_context']['packaged']or binding['input']['gateway_argv']!=cap['gateway']['argv']
            or any(binding.get(k)!=v for k,v in code_bindings(branch).items())):
        raise ValueError('Exact capture branch/public/native source context differs')
    pointer=binding['observation_pointer'];normal=binding.get('normalized_input_choice')
    if normal is not None:
        if audit.digest(normal)!=audit.digest(normalized_input(branch,cap,root))or pointer!=normal['native_pointer']or binding.get('reference_chain')!=[]:
            raise ValueError('Only ten exact explicit enable/default-true normalizations qualify')
        return {'observation_pointer':pointer}
    completion.exact_observation_pointer(branch,binding,'/native_call',branch['pointer'].split('/')[1].removesuffix('Schema'),edges or {})
    value=remaining._occurrence_value(record,pointer,branch)
    if not fixed.predicate(branch,fixed.schema_node(branch,root),value,root):raise ValueError('Exact capture branch occurrence missing')


def qualified_result(descriptor,assessment,branch,candidate,scope_kind,base,binding,root,edges):
    entry=exact_entry(branch,root)
    if branch['pointer']!='/resultSchema'or entry['role']!='native_business_anchor'or scope_kind!='product':raise ValueError('Only exact capture ACK roots qualify')
    original=original_control(branch['route'],base,root=root);p=original['profile']
    record=completion.read_sealed_artifact(descriptor,base);cap=completion.read_sealed_artifact(assessment['program_capture'],base)
    sources=cursor.review(root)['source_maps'][cursor.review(root)['profiles'][p['cursor_route']]['candidate']]['sources']
    expected={'contract':CONTRACT,'branch_id':branch['id'],'profile':p,'support_review':assessment['support_review'],
        'archive':original['archive'],'program_capture':assessment['program_capture'],'facts':original['facts']}
    if (assessment!=expected or not runtime.qualified_source_review_matches(assessment['support_review'],SUPPORT_SHA,review(root),base)
            or record!={'candidate_sha256':candidate,'scope_kind':'product','evidence_kind':'qualified_retained_capture_control_ack',
                'branch_id':branch['id'],'native_shape_sha256':branch['shape_sha256'],'assessment_sha256':binding['qualified_runtime_read_attachment']['sha256'],
                'relevant_sources':sources,'retained_facts':original['facts']}
            or cap['native_call']!={'uri':branch['route'].split('|')[-1],'args':original['args'],'options':{},'result':original['result']}):
        raise ValueError('Exact original control ACK/current complete replay differs')
    if runtime.retained_qualified_capture(cap):
        return 'passed',None
    validate_evidence({'gateway':cap['gateway'],'native_call':cap['native_call'],'runtime_read_program':cap,
        'relevant_sources':cap['source_context']['packaged']},binding,branch,'program',base,root,edges)
    return 'passed',None


def write_capture_control_bundle(output,captures,*,inventory,name_prefix='',retained_native=()):
    if retained_native:
        if captures:
            raise ValueError('Native-only conversion does not accept current program captures')
        from tests.support.qualified_runtime_read_evidence import write_selected_native_bundle
        return write_selected_native_bundle(output, inventory, retained_native, family=__name__)
    versions={r['version']for r in inventory['native_coverage']['routes']if r['uri']in URIS}
    if (not isinstance(name_prefix,str)or name_prefix and (len(versions)!=1
            or name_prefix!='capture-control-'+next(iter(versions))+'-')):
        raise ValueError('Only the closed matching-version capture control prefix qualifies')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(audit.ROOT/SUPPORT,output/'capture-control-support-review.json')
    candidate=inventory['native_coverage']['candidate_sha256'];seen=set()
    index={'contract':'waapi-skill.branch-evidence-index/v1','base':'.','entries':[],'qualified_runtime_read_attachments':[]}
    requirements={'contract':'waapi-skill.branch-evidence-requirements/v1','branches':{}}
    edges={b['id']:b for b in inventory['native_coverage']['obligations']if b['kind']=='reference'}
    def write(name,value):return runtime.write_json(output/name,value)
    def desc(name):return {'artifact':name,'sha256':runtime.sha((output/name).read_bytes())}
    for number,path in enumerate(captures):
        cap=json.loads(Path(path).read_bytes());context=_capture(json.dumps(cap),audit.ROOT);uri=cap['native_call']['uri']
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
        prefix=(name_prefix or'capture-control-')+str(number)+'-';cp=write(prefix+'capture.json',cap)
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
            if entry['role']=='native_business_anchor':
                original=original_control(route['id']);p=original['profile'];cp_profile=cursor.review()['profiles'][p['cursor_route']]
                if cap['native_call']!={'uri':uri,'args':original['args'],'options':{},'result':original['result']}:
                    raise ValueError('Capture native root requires actual original complete request/result replay first')
                name='cursor-'+cp_profile['version']+'-'+cp_profile['host']+'-original.json.gz';shutil.copyfile(audit.ROOT/cp_profile['archive_source'],output/name)
                assessment=write(prefix+'assessment.json',{'contract':CONTRACT,'branch_id':identity,'profile':p,'support_review':desc('capture-control-support-review.json'),
                    'archive':desc(name),'program_capture':cp,'facts':original['facts']})
                evidence=write(prefix+'qualified.json',{'candidate_sha256':candidate,'scope_kind':'product','evidence_kind':'qualified_retained_capture_control_ack',
                    'branch_id':identity,'native_shape_sha256':branch['shape_sha256'],'assessment_sha256':assessment['sha256'],
                    'relevant_sources':cursor.review()['source_maps'][cp_profile['candidate']]['sources'],'retained_facts':original['facts']})
                index['qualified_runtime_read_attachments'].append(write(prefix+'attachment.json',{'contract':'waapi-skill.qualified-retained-read-attachment/v1',
                    'branch_id':identity,'assessment':assessment,'evidence':evidence}))
        pd={**write(prefix+'program.json',program),'nodeid':cap['nodeid']}
        for b in bindings['bindings'].values():b['evidence']['program']=pd
        bd=write(prefix+'bindings.json',bindings);rd=write(prefix+'requirements.json',policies)
        index['entries'].append({'id':prefix,'bindings':bd,'origin':{'bindings':bd,'program':desc(prefix+'program.json'),'requirements':rd,'capture':cp}})
        requirements['branches'].update(policies['branches'])
    if seen!={b['id']for b in inventory['native_coverage']['obligations']}:
        raise ValueError('Missing exact capture control branch occurrences: '+str(set(b['id']for b in inventory['native_coverage']['obligations'])-seen))
    write('requirements.json',requirements);write('index.json',index)
    return output/'index.json'
