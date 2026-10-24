"""Closed R127 runtime policies and log adapters behind the ordinary evidence reader.

Only exact source-owned rows qualify. Log evidence is checked here; the closed
Console LoadedMedia family delegates to its existing evidence helper. Other
families retain business gates without an adapter; generic evidence cannot unlock them.
"""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import shutil

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support import runtime_observation_evidence as runtime
from tests.support import fixed_runtime_read_evidence as fixed

POLICY = 'tests/fixtures/runtime/runtime-remaining-policy-r127.json'
POLICY_SHA = '994dc0ead6c3740a0d83512ed75af06ace2943c6477cafe6c6ce898a3c340408'
FIXTURE = 'tests/fixtures/runtime-log'
SUPPORT_SHA = 'eff70a4100be8eb88b4e4e58b2792bbb1607a5e307c536c3d407c9af5767a13a'
LOG_GET = 'ak.wwise.core.log.get'
LOG_URIS = frozenset('ak.wwise.core.log.' + n for n in ('get','addItem','clear'))
R122_CANDIDATE = '1f32f9f223cebe11076ca07f168f29fad99adfab'
R122_ROUTE = '2025.1|wwise-console|2025.1.7.9143|function|'

PRIOR = 'tests/fixtures/runtime/runtime-remaining-prior-r127.json.gz'
PRIOR_SHA = '7c80a224fb8350c979ed7e4a72598cd5d8f750cbe8817b396467becce108132a'
_RELEASE_BUILDS = {'2021.1':'2021.1.14.8108','2022.1':'2022.1.19.8584','2023.1':'2023.1.19.8928',
    '2024.1':'2024.1.13.9056','2025.1':'2025.1.7.9143'}
# The cheap ownership boundary precedes all fixture access. LoadedMedia here is
# Console-only; previously accepted Authoring rows belong to their existing scope.
_ROUTE_START = {
    **{'ak.wwise.core.'+name:2021 for name in ('log.get','profiler.enableProfilerData','profiler.getCursorTime',
        'profiler.startCapture','profiler.stopCapture','transport.create','transport.destroy','transport.executeAction',
        'transport.getList','transport.getState')},
    'ak.wwise.core.transport.prepare':2022,
    **{'ak.wwise.core.'+name:2023 for name in ('log.addItem','log.clear','profiler.getCpuUsage','profiler.getLoadedMedia',
        'profiler.getPerformanceMonitor','profiler.getStreamedMedia','profiler.saveCapture','transport.useOriginals')},
    **{'ak.wwise.core.profiler.'+name:2024 for name in ('getMeters','registerMeter','unregisterMeter')},
    **{'ak.wwise.core.profiler.'+name:2025 for name in ('moveCursor','setCursorTime')},
}


def owned_route(route):
    if not isinstance(route,str):return False
    parts=route.split('|')
    if len(parts)!=5:return False
    version,host,build,kind,uri=parts
    return (kind=='function'and host in {'wwise-console','wwise-authoring'}and _RELEASE_BUILDS.get(version)==build
        and uri in _ROUTE_START and int(version[:4])>=_ROUTE_START[uri]
        and (not uri.endswith('.getLoadedMedia')or host=='wwise-console'))


@lru_cache(maxsize=8)
def _sealed_prior(path,signature):
    import base64,gzip,io
    raw=path.read_bytes()
    if len(raw)>1_000_000 or runtime.sha(raw)!=PRIOR_SHA:
        raise ValueError('Exact runtime prior originals changed')
    with gzip.GzipFile(fileobj=io.BytesIO(raw))as stream:body=stream.read(8_000_001)
    if len(body)>8_000_000:raise ValueError('Exact runtime prior originals size changed')
    packet=json.loads(body)
    if set(packet)!={'contract','candidate','files'}or packet['contract']!='waapi-skill.runtime-policy-originals/v1':
        raise ValueError('Exact runtime prior originals contract changed')
    return packet['candidate'],{name:base64.b64decode(value,validate=True)for name,value in packet['files'].items()}


def _prior_contents(root):
    path=root/PRIOR;stat=path.stat()
    return _sealed_prior(path,(stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns))


def _prior_raw(root,candidate,path,seal):
    observed,files=_prior_contents(root)
    if observed!=candidate or path not in files or runtime.sha(files[path])!=seal:
        raise ValueError('Exact runtime prior scope digest/history changed')
    return files[path]


@lru_cache(maxsize=32)
def _sealed_json(path, seal, signature):
    raw = path.read_bytes()
    if runtime.sha(raw) != seal:
        raise ValueError('Exact source-owned runtime descriptor changed: ' + str(path))
    return json.loads(raw)


def _read_pin(path, seal):
    stat = path.stat()
    return _sealed_json(path,seal,(stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns))


def review(root=audit.ROOT):
    result = _read_pin(root/POLICY,POLICY_SHA)
    if result['counts'] != {'entries':10977,'routes':169,'native_business_anchors':169,'conditional_rows':10808,'input_rows':3003}:
        raise ValueError('Exact R127 remaining roster counts differ')
    _,originals=_prior_contents(root)
    expected={result['prior_policy']['path'],*[p for p in result['prior_scopes']if '/runtime-loaded-media/'in p]}
    if set(originals)!=expected:raise ValueError('Exact runtime prior scope closure changed')
    for path,seal in result['prior_scopes'].items():
        if '/runtime-loaded-media/'in path:
            _historical_scope(root,result['basis'],path,seal)
        else:_read_pin(root/path,seal)
    _check_baseline(root,POLICY_SHA)
    return result


@lru_cache(maxsize=16)
def _historical_scope(root,candidate,path,seal):
    _prior_raw(root,candidate,path,seal)


@lru_cache(maxsize=8)
def _check_baseline(root, seal):
    r = _read_pin(root/POLICY,seal); baseline=r['prior_policy']
    raw=_prior_raw(root,baseline['candidate'],baseline['path'],baseline['sha256'])
    if runtime.sha(raw)!=baseline['sha256'] or set(json.loads(raw)['branches']) & set(r['entries']):
        raise ValueError('Remaining runtime prior-policy absence/history differs')


def selected(identity,root=audit.ROOT):
    if not isinstance(identity,str)or not owned_route(identity.rsplit('|',1)[0]):return False
    return identity in review(root)['entries']


def exact_entry(branch,root=audit.ROOT):
    entry=review(root)['entries'].get(branch['id'])
    if not entry or any(branch.get(k)!=entry[k] for k in ('route','pointer','kind','owner_issue','parent_issue','blocks_issue')) or branch['shape_sha256']!=entry['native_shape_sha256']:
        raise ValueError('Only exact remaining runtime branch/shape/owner qualifies')
    return entry


def policy(entry):
    return {'native_shape_sha256':entry['native_shape_sha256'],'categories':entry['categories'],
        'reason':'R127 exact remaining runtime '+entry['family']+': '+entry['role']+'; same-route business/native gate required; no native optional-value occurrence claim'}


def counterexample_policy(branch,root=audit.ROOT):
    """Closed four-ID compiler counterexamples retain their native business gate."""
    if branch['id']not in review(root)['schema_counterexample_ids']:
        raise ValueError('Only exact four source-owned log counterexamples qualify')
    from tests.support.empty_candidate_evidence import classify_empty_candidate
    classification=classify_empty_candidate(root,branch)
    if classification is None or classification['status']!='rejected':
        raise ValueError('Exact source-invalid log severity candidate no longer rejects')
    return {'native_shape_sha256':branch['shape_sha256'],'categories':['program'],'empty_candidate':classification,
        'reason':'Resolved reflected schema rejects this concrete synthetic candidate; exact public counterexample program proof required. No native absence/effect or parent credit.'}


def preservation_gates(root,policies,obligations):
    if not any(branch['id']in policies and owned_route(branch['id'].rsplit('|',1)[0])for branch in obligations):return {}
    roster=review(root)['entries'];gates={}
    for branch in obligations:
        identity=branch['id']
        if identity not in roster or identity not in policies:continue
        entry=exact_entry(branch,root)
        expected=counterexample_policy(branch,root) if identity in review(root)['schema_counterexample_ids'] else policy(entry)
        gates[identity]=entry['required_native_anchor_ids'] if policies[identity]==expected else None
    return gates


def support(root=audit.ROOT):
    return _read_pin(root/FIXTURE/'r122-support.json',SUPPORT_SHA)


def original_log(artifact_base=None,*,root=audit.ROOT):
    """Recheck the whole retained R122 workflow; no manufactured native rows."""
    r=support(root);base=Path(artifact_base) if artifact_base is not None else root/FIXTURE
    descriptor={'artifact':'r122-original.json.gz','sha256':r['archive_sha256']}
    read=runtime.archive_reader(descriptor,base)
    import gzip
    encoded=json.loads(gzip.decompress((base/descriptor['artifact']).read_bytes()))['files']
    if len(encoded)!=r['archive_files'] or audit.digest(encoded)!=r['archive_map_sha256']:
        raise ValueError('Complete original R122 archive differs')
    category={'artifact':'r122-category.json','sha256':r['category_sha256'],'nodeid':r['nodeid']}
    context=completion.read_category_run(category,base);final=context['record']
    history=read(r['original_root']+'/evidence/category.jsonl').splitlines()
    receipt_raw=read(r['receipt_path']);receipt=json.loads(receipt_raw)
    if (json.loads(history[-1])!=final or context['candidate']!=R122_CANDIDATE
            or {k:context[k]for k in ('version','host','build')}!={'version':'2025.1','host':'wwise-console','build':'2025.1.7.9143'}
            or runtime.sha(receipt_raw)!=r['receipt_sha256'] or receipt['candidate']!=R122_CANDIDATE
            or completion.native_host_context(receipt['host'],'isCommandLine')!={k:context[k]for k in ('version','host','build')}
            or receipt['durable_observation']['outcome']!='matched'
            or receipt['durable_observation']['cleanup']!={'status':'unsubscribed'}):
        raise ValueError('R122 exact finalized host/receipt/event/cleanup differs')
    workflow=receipt['getter_workflow'];expected=receipt['expected']
    rows=workflow['post_add']['items']
    if (len(rows)!=1 or any(rows[0][k]!=expected[k]for k in ('message','severity'))
            or workflow['post_add']['truncated'] is not False or workflow['clear_prestate']['items']!=rows
            or workflow['clear_prestate']['outcome']!='complete' or workflow['post_clear']!={'outcome':'complete','items':[],'item_count':0}
            or any(receipt[k]['verify']['state']!='verified' or receipt[k]['verify']['verified'] is not True
                   for k in ('transaction','clear_transaction'))):
        raise ValueError('R122 actual nonempty getter/add/clear business facts differ')
    for call in r['calls']:
        raw=read(call['path']);decoded=json.loads(raw)
        if runtime.sha(raw)!=call['sha256'] or decoded['api']!=call['api'] or decoded['result']!=call['result'] or decoded['ok'] is not True or decoded['dry_run'] is not False or decoded['version']!='2025.1':
            raise ValueError('R122 original native call differs')
    sources=r['sources']
    if completion.historical_source_seals(root,R122_CANDIDATE,sources)!=sources:
        raise ValueError('R122 original complete packaged sources differ')
    current=runtime.program_source_context(root,flow=LOG_GET)['packaged']
    differences={k:{'before':sources.get(k),'after':current.get(k)}for k in sources.keys()|current.keys()if sources.get(k)!=current.get(k)}
    if len(sources)!=413 or len(current)!=413 or differences!=r['packaged_source_changes']:
        raise ValueError('R122 exact reviewed packaged source bridge differs')
    return dict(review=r,read=read,archive=descriptor,category=category,context=context,receipt=receipt,receipt_raw=receipt_raw,sources=sources)


def _original_request(original,uri):
    receipt=original['receipt']
    if uri==LOG_GET:
        return {'api':uri,'args':{'channel':receipt['getter_workflow']['post_add']['channel']},'options':{}}
    name='transaction'if uri.endswith('.addItem')else'clear_transaction'
    return receipt[name]['verify']['agent_result']['request']['arguments']


def _original_call(original,uri):
    calls=original['review']['calls']
    if uri==LOG_GET:
        return next(x for x in calls if x['api']==uri and x['result'].get('items')==original['receipt']['getter_workflow']['post_add']['items'])
    return next(x for x in calls if x['api']==uri)


@lru_cache(maxsize=32)
def _current_context_cached(root,flow,signature):
    return runtime.program_source_context(root,flow=flow)


def _current_context(root,flow,captured):
    names=sorted({name for group in captured.values() for name in group})
    signature=tuple((name,(root/name).stat().st_size,(root/name).stat().st_mtime_ns,(root/name).stat().st_ctime_ns)for name in names)
    return _current_context_cached(root,flow,signature)


def _log_public_rows(captured):
    """Validate actual public retained pages/fragments without rewriting agent_result."""
    calls=captured['public_calls'];trace=captured['native_reads'];native=captured['native_call'];original=native['result']['items']
    if not 1<=len(calls)<=128 or calls[0]!={'gateway':captured['gateway'],'native_start':0,'native_end':len(trace)}:
        raise ValueError('Bounded exact public log read/retained-page spans required')
    values={};fragments={};snapshot=None;previous=None
    for index,call in enumerate(calls):
        page=call['gateway'];payload=page['payload'];result=payload['agent_result']
        if page['exit_code']!=0 or payload.get('ok')is not True or list(payload)[-1]!='agent_result':
            raise ValueError('Exact successful final public page required')
        if index:
            if call['native_start']!=len(trace) or call['native_end']!=len(trace) or page['argv']!=previous['next_command']['full_argv'][3:]:
                raise ValueError('Retained log pages must use exact offline continuation without reread')
        if 'snapshot_sha256'not in result:
            if len(calls)!=1 or result['truncated']is not False or result['returned_count']!=len(original):
                raise ValueError('Ordinary complete log result differs')
            return result['items']
        if snapshot is None:snapshot=result['snapshot_sha256']
        if result['snapshot_sha256']!=snapshot or result['total_count']!=len(original):
            raise ValueError('Retained pages changed snapshot identity or total count')
        offset=result['page']['offset_from_end'];end=result['page']['next_offset_from_end']
        if type(offset)is not int or type(end)is not int or not 0<=offset<=end<=len(original):
            raise ValueError('Log page offsets differ')
        if 'row_fragment'in result:
            fragment=result['row_fragment'];row_index=fragment['row_index']
            parts=fragments.setdefault(row_index,[])
            if (result['items']!=[] or row_index!=len(original)-offset-1
                    or fragment['offset_characters']!=sum(map(len,parts)) or row_index in values):
                raise ValueError('Log fragment occurrence or contiguous offset differs')
            parts.append(fragment['value'])
            if sum(map(len,parts))==fragment['total_characters']:
                if end!=offset+1:raise ValueError('Final fragment did not advance one retained row')
                values[row_index]=json.loads(''.join(parts));del fragments[row_index]
            elif end!=offset:raise ValueError('Partial fragment advanced past its row')
        else:
            if len(result['items'])!=end-offset:raise ValueError('Retained page row count differs')
            for row_index,row in zip(range(len(original)-end,len(original)-offset),result['items'],strict=True):
                if row_index in values:raise ValueError('Duplicate public log row occurrence')
                values[row_index]=row
        if result['complete']is not (index==len(calls)-1) or result['truncated']is not (index!=len(calls)-1):
            raise ValueError('Incomplete or extra public page delivery')
        previous=result
    if fragments or set(values)!=set(range(len(original))):raise ValueError('Complete public log rows/fragments missing')
    return [values[i]for i in range(len(original))]


@lru_cache(maxsize=256)
def _validate_log_capture(captured_json,root):
    captured=json.loads(captured_json);gateway=captured['gateway'];native=captured['native_call'];payload=gateway['payload'];trace=captured.get('native_reads',[])
    if (captured.get('contract')!='waapi-skill.runtime-read-program/v1'
            or captured.get('phase_reports')!=dict.fromkeys(('setup','call','teardown'),'passed')
            or captured.get('source_unchanged')is not True or native['uri']!=LOG_GET
            or gateway['exit_code']!=0 or payload.get('ok')is not True):
        raise ValueError('Complete exact public log capture/teardown required')
    if (not 1<=len(trace)<=16 or any(set(x)!={'ordinal','uri','args','options','result'} or type(x['ordinal'])is not int or x['ordinal']!=i for i,x in enumerate(trace))
            or [{k:x[k]for k in ('uri','args','options','result')}for x in trace if x['uri']==LOG_GET]!=[native]
            or len([x for x in trace if x['uri']==LOG_GET])!=1):
        raise ValueError('Log read requires one exact bounded public/native span')
    info,=[x['result']for x in trace if x['uri']=='ak.wwise.core.getInfo']
    context=completion.native_host_context(info,'isCommandLine')
    argv=gateway['argv'];channel=argv[argv.index('--log-channel')+1]
    if argv!=['core-call',LOG_GET,'--log-channel',channel,'--max-results','1000']:
        raise ValueError('Exact bounded public log declaration differs')
    from wwise_waapi.runtime_inspection_business import materialize_runtime_inspection_business_request
    from wwise_waapi.builders.schema import validate_resolved_semantic_result
    request,_,_=materialize_runtime_inspection_business_request(LOG_GET,context['version'],log_channel=channel,max_results=1000)
    if request!={'api':LOG_GET,'args':native['args'],'options':native['options']}:
        raise ValueError('Gateway-owned versioned channel construction differs')
    validate_resolved_semantic_result(LOG_GET,native['result'],version=context['version'])
    if _log_public_rows(captured)!=native['result']['items']:
        raise ValueError('Complete native/public nested log values differ')
    return context


@lru_cache(maxsize=256)
def _validate_control_capture(captured_json,root):
    from collections import Counter
    from wwise_waapi.builders.schema import validate_resolved_semantic_result
    captured=json.loads(captured_json);gateway=captured['gateway'];native=captured['native_call'];trace=captured['native_reads'];calls=captured['public_calls']
    if (captured.get('contract')!='waapi-skill.runtime-read-program/v1'
            or captured.get('phase_reports')!=dict.fromkeys(('setup','call','teardown'),'passed')
            or captured.get('source_unchanged')is not True or native['uri']not in LOG_URIS-{LOG_GET}
            or len(calls)!=8 or not 1<=len(trace)<=128 or calls[-1]['gateway']!=gateway):
        raise ValueError('Exact complete public log transaction and teardown required')
    commands=['draft-start','draft-declare-runtime-control-plan','draft-check','preview-from-draft','transaction-show','confirm','execute','verify']
    cursor=0
    for command,call in zip(commands,calls,strict=True):
        receipt=call['gateway'];payload=receipt['payload'];end=call['native_end']
        if (receipt['argv'][0]!=command or receipt['exit_code']!=0 or payload.get('ok')is not True
                or call['native_start']!=cursor or type(end)is not int or not cursor<=end<=len(trace)
                or 'agent_result'in payload and list(payload)[-1]!='agent_result'):
            raise ValueError('Actual public log transaction phase/order/span differs')
        cursor=end
    if cursor!=len(trace)or any(x['ordinal']!=i or set(x)!={'ordinal','uri','args','options','result'}for i,x in enumerate(trace)):
        raise ValueError('Exact finite native transaction spans required')
    contexts=[completion.native_host_context(x['result'],'isCommandLine')for x in trace if x['uri']=='ak.wwise.core.getInfo']
    if not contexts or any(x!=contexts[0]for x in contexts):raise ValueError('Log transaction host drift')
    context=contexts[0];version=context['version'];payload=gateway['payload'];result=payload['agent_result']
    actual=[{k:x[k]for k in ('uri','args','options','result')}for x in trace if x['uri']==native['uri']]
    if actual!=[native]or any(x['uri']in LOG_URIS-{LOG_GET,native['uri']}for x in trace):
        raise ValueError('Log transaction must execute its one mutation exactly once')
    preview=calls[3]['gateway']['payload'];shown=calls[4]['gateway']['payload'];executed=calls[6]['gateway']['payload'];tx=preview['transaction_id'];seal=preview['artifact_hash']
    if (calls[4]['gateway']['argv']!=preview['next_command']['gateway_argv']
            or calls[5]['gateway']['argv']!=shown['next_command']['gateway_argv']
            or calls[6]['gateway']['argv']!=['execute',tx] or gateway['argv']!=executed['next_command']['gateway_argv']
            or any(x.get('transaction_id')!=tx or x.get('artifact_hash')!=seal for x in (shown,executed,payload))
            or payload.get('automatic_retry')is not False or result.get('executed')is not True
            or result['request']['arguments']!={'api':native['uri'],'args':native['args'],'options':native['options']}
            or result['result']!=native['result']):
        raise ValueError('Sealed Preview/confirmation/once execution/final exact result differs')
    declaration=calls[1]['gateway']['argv'];channels={'general':'general','soundbank-generation':'soundbankGenerate','audio-conversion':'conversion',
        'platform-settings-copy':'copyPlatformSettings','waapi':'waapi','project-load':'projectLoad','source-control':'sourceControl','lua':'lua'}
    def choice(flag,default):return declaration[declaration.index(flag)+1]if flag in declaration else default
    expected={'channel':channels[choice('--log-channel','general')]}
    if native['uri'].endswith('.addItem'):
        expected.update(message=choice('--message',None),severity={'message':'Message','warning':'Warning','error':'Error','fatal':'Fatal Error'}[choice('--severity','message')])
    if native['args']!=expected or native['options']!={}:raise ValueError('Literal public log choice/native construction differs')
    validate_resolved_semantic_result(native['uri'],native['result'],version=version)
    observed=payload['verification']['verification_scope']['log_observation'];reads=[x['result']for x in trace if x['uri']==LOG_GET]
    for read in reads:validate_resolved_semantic_result(LOG_GET,read,version=version)
    if any(x['args']!={'channel':expected['channel']}or x['options']!={}for x in trace if x['uri']==LOG_GET):
        raise ValueError('Log effect read changed selected channel')
    if observed['channel']!=expected['channel']or observed['exclusive_causation_verified']is not False or observed['continuing_channel_state_verified']is not False:
        raise ValueError('Log effect must retain channel and concurrency limits')
    mode=('console_log_unobservable'if context['host']=='wwise-console'and version!='2025.1'else
        'matching_item_event'if context['host']=='wwise-console'and native['uri'].endswith('.addItem')else
        'new_matching_item'if native['uri'].endswith('.addItem')else'prior_contents_absent')
    if observed['outcome']!=mode:raise ValueError('Exact host/version log business verification mode differs')
    if observed['outcome']=='new_matching_item':
        before,after=reads[-2]['items'],reads[-1]['items'];matches=lambda row:row['message']==expected['message']and row['severity']==expected['severity']
        old,new=sum(map(matches,before)),sum(map(matches,after))
        if not new>old or observed['matching_items_before']!=old or observed['matching_items_after']!=new or payload['verified']is not True:
            raise ValueError('Actual new exact log-item multiset increase required')
    elif observed['outcome']=='prior_contents_absent':
        before,after=reads[-2]['items'],reads[-1]['items'];canonical=lambda rows:Counter(json.dumps(row,sort_keys=True)for row in rows)
        if not before or canonical(before)&canonical(after)or payload['verified']is not True or observed['post_channel_empty']is not (not after):
            raise ValueError('Actual prior log rows absent; no perpetual empty-state claim')
    elif observed['outcome']=='console_log_unobservable':
        if context['host']!='wwise-console'or version=='2025.1'or payload['verified']is not False or payload['state']!='result_schema_checked':
            raise ValueError('Only exact older Console weaker log-observation boundary qualifies')
    elif observed['outcome']=='matching_item_event':
        if context['host']!='wwise-console'or version!='2025.1'or not native['uri'].endswith('.addItem')or payload['verified']is not True:
            raise ValueError('Only exact supported Console owned event qualifies')
        # Complete sealed execution retains the matched event and unsubscribe result.
        event=observed['execution_observation']
        if (event!=executed['dispatch_result']['log_item_observation']or event['contract']!='waapi-skill.console-log-add-observation/v1'
                or event['outcome']!='matched'or event['subscribed']is not True or event['topic']!='ak.wwise.core.log.itemAdded'
                or event['cleanup']!={'status':'unsubscribed'}or not 1<=event['events_observed']<=64
                or event['event']['channel']!=expected['channel']
                or any(event['event']['item'][k]!=expected[k]for k in ('message','severity'))):
            raise ValueError('Complete exact owned matched event and unsubscribe required')
        validate_resolved_semantic_result(LOG_GET,{'items':[event['event']['item']]},version=version)
    else:raise ValueError('No interpreted log effect or approved exact native boundary')
    return context


def _occurrence_value(record,pointer,branch):
    try:return completion.pointer_value(record,pointer)
    except KeyError:
        if branch['kind']=='optional_presence' and branch['value']=='absent':
            completion.pointer_value(record,pointer.rsplit('/',1)[0])
            return runtime._CONTRIBUTION_ABSENT
        raise


def _code_bindings(branch):
    uri=branch['route'].split('|')[-1];reading=uri==LOG_GET
    construction='materialize_runtime_inspection_business_request'if reading else'materialize_runtime_control_business_request'
    verifier=('skills/waapi-skill/wwise_waapi/runtime_inspection_business.py#normalize_runtime_inspection_result'if reading else
        'skills/waapi-skill/wwise_waapi/runtime_log_observer.py#event_observation'if branch['route'].split('|')[:2]==['2025.1','wwise-console']and uri.endswith('.addItem')else
        'skills/waapi-skill/wwise_waapi/runtime_log_effects.py#compare_channel')
    validation='validate_resolved_semantic_result'if branch['pointer'].startswith('/resultSchema')else'validate_semantic_payload'
    return {key:{'source':source,'selector':branch['pointer']}for key,source in (
        ('construction','skills/waapi-skill/wwise_waapi/runtime_inspection_business.py#'+construction),
        ('validation','skills/waapi-skill/wwise_waapi/builders/schema.py#'+validation),('verifier',verifier))}


def validate_program(record,binding,branch,root,edges=None):
    exact_entry(branch,root);uri=branch['route'].split('|')[-1]
    if any(binding.get(k)!=v for k,v in _code_bindings(branch).items()):raise ValueError('Exact log compiler/validator/business verifier binding differs')
    if uri not in LOG_URIS:raise ValueError('Remaining runtime family public mapper is not implemented yet')
    captured=record.get('runtime_read_program',{});gateway=record['gateway'];native=record['native_call']
    if (captured.get('source_context')!=_current_context(root,uri,captured.get('source_context',{}))
            or record.get('relevant_sources')!=captured['source_context']['packaged']
            or captured.get('gateway')!=gateway or captured.get('native_call')!=native or gateway['argv']!=binding['input']['gateway_argv']):
        raise ValueError('Exact complete public log source/receipt differs')
    context=(_validate_log_capture if uri==LOG_GET else _validate_control_capture)(json.dumps(captured),root)
    version,host,build,_,_=branch['route'].split('|')
    if context!={'version':version,'host':host,'build':build} or gateway['payload'].get('is_command_line')is not (host=='wwise-console'):
        raise ValueError('Log exact public/native host/version/build differs')
    pointer=binding.get('program_observation_pointer',binding['observation_pointer'])
    completion.exact_observation_pointer(branch,{**binding,'observation_pointer':pointer},'/native_call',branch['pointer'].split('/')[1].removesuffix('Schema'),edges or {})
    normalized=binding.get('normalized_input_choice')
    if normalized is not None:
        if normalized!=_normalized_log_input(branch,captured)or pointer!=normalized['native_pointer']:
            raise ValueError('Only exact actual public omission/native default normalization qualifies')
        return {'observation_pointer':pointer}
    value=_occurrence_value(record,pointer,branch)
    if not _log_predicate(branch,_log_node(branch,root),value,root):
        raise ValueError('Exact log branch occurrence failed its pinned predicate')


def validate_evidence(record,binding,branch,category,base,root,edges=None):
    entry=exact_entry(branch,root)
    if entry['family']=='console_loaded_media':
        from tests.support.loaded_media_runtime_evidence import validate_console_evidence
        return validate_console_evidence(record,binding,branch,category,base,root,edges)
    if category=='program':
        return validate_program(record,binding,branch,root,edges)
    if category!='native' or entry['role']!='native_business_anchor' or not binding.get('runtime_observation_attachment') or branch['route']not in {R122_ROUTE+uri for uri in LOG_URIS}:
        raise ValueError('Exact remaining business gate has no implemented native adapter')
    original=original_log(base,root=root);proof=runtime._proof(binding,base);mapping=proof['mapping']
    captured=completion.read_sealed_artifact(proof['program_capture'],base)
    raw=completion.read_sealed_artifact(mapping['raw_observation'],base)
    expected=_original_call(original,branch['route'].split('|')[-1]);request=_original_request(original,expected['api'])
    if (proof['branch_id']!=branch['id'] or proof['native_shape_sha256']!=branch['shape_sha256']
            or proof['archive']!=original['archive'] or proof['source_review']['sha256']!=SUPPORT_SHA
            or completion.read_sealed_artifact(proof['source_review'],base)!=original['review']
            or proof['capture_original_path']!=original['review']['receipt_path']
            or (base/proof['capture']['artifact']).read_bytes()!=original['receipt_raw']
            or (base/mapping['raw_observation']['artifact']).read_bytes()!=original['read'](expected['path'])
            or proof['relevant_sources']!=original['sources'] or record['native_runs']!=[proof['native_run']]
            or record['observation_artifacts']!={'capture':proof['capture'],'raw':mapping['raw_observation']}
            or mapping['native_pointer']!='/observations/raw/result' or mapping['program_pointer']!='/native_call/result'
            or captured['native_call']!={'uri':request['api'],'args':request['args'],'options':request['options'],'result':raw['result']}):
        raise ValueError('R122 exact full original result/source/current replay differs')
    validate_program({'gateway':captured['gateway'],'native_call':captured['native_call'],'runtime_read_program':captured,'relevant_sources':captured['source_context']['packaged']},binding,branch,root,edges)


def validate_source_equivalence(proof,sources,branch,binding,root,base):
    exact_entry(branch,root)
    if branch['id']not in {R122_ROUTE+uri+'|/resultSchema'for uri in LOG_URIS} or proof['from_candidate']!=R122_CANDIDATE or not binding.get('runtime_observation_attachment'):
        raise ValueError('Only exact R122 log gate can use its source bridge')
    attached=runtime._proof(binding,base)
    original=original_log(base,root=root)
    if (proof['runtime_remaining_source_review']!=attached['source_review'] or sources!=original['sources']
            or attached['source_review']['sha256']!=SUPPORT_SHA):
        raise ValueError('Exact R122 complete source review differs')



@lru_cache(maxsize=16)
def _log_catalog(root,version,host):
    from wwise_waapi.native_catalog import load_native_catalog
    return load_native_catalog(version,host,root=root/'skills/waapi-skill/resources/native-catalog')


@lru_cache(maxsize=8192)
def _log_node_at(root,route,pointer):
    version,host,build,_,uri=route.split('|')
    catalog=_log_catalog(root,version,host)
    if catalog['provenance']['build']!=build:raise ValueError('Pinned log build differs')
    if '/@definition/'in pointer:
        _,rest=pointer.split('/@definition/',1);name,suffix=rest.split('/',1)
        return completion.pointer_value(catalog['definitions']['documents'][name],'/'+suffix)
    return completion.pointer_value(catalog['schemas'][uri],pointer)


def _log_node(branch,root):
    pointer=branch['pointer']
    for marker in ('/@boolean/','/@nullable','/@presence/','/@cardinality/','/@empty/'):
        pointer=pointer.split(marker)[0]
    return _log_node_at(root,branch['route'],pointer)


@lru_cache(maxsize=32768)
def _log_alternative(root,route,pointer,value_json):
    """Closed log schemas use the same resolved, bounded product validator.

    descriptionOverride is a reflected annotation, never an extra constraint.
    Pattern-property keys remain subject to their actual referenced schema.
    """
    from wwise_waapi.schema_inventory import DefinitionGraph,resolve_schema_reference
    from wwise_waapi.builders.schema import _SchemaWalker
    from wwise_waapi.builders.common import SemanticValidationError
    version,host,_,_,uri=route.split('|');catalog=_log_catalog(root,version,host)
    definitions=catalog['definitions']
    graph=DefinitionGraph(**{k:definitions[k]for k in ('contract','version','wwise_build','source_file_names','documents','inventory_sha256')})
    context=(graph.documents[pointer.split('/@definition/',1)[1].split('/',1)[0]]
        if '/@definition/'in pointer else catalog['schemas'][uri][pointer.split('/')[1]])
    class Walker(_SchemaWalker):
        def validate(self,schema,value,*,path,depth=0):
            if depth>32:raise ValueError('Log reference budget exceeded')
            if not isinstance(schema,dict):raise ValueError('Unknown log schema semantics')
            reference=schema.get('$ref',schema.get('#ref'))
            if reference is not None:
                resolved=resolve_schema_reference(reference,root_schema=self.context,graph=graph)
                old=self.context
                self.context=old if resolved.document_name=='<schema>'else graph.documents[resolved.document_name]
                try:self.validate(resolved.target,value,path=path,depth=depth+1)
                finally:self.context=old
                schema={k:v for k,v in schema.items()if k not in ('$ref','#ref')}
            known={'type','properties','patternProperties','additionalProperties','required','items','minItems','maxItems','uniqueItems',
                'enum','const','oneOf','anyOf','allOf','minLength','maxLength','pattern','minimum','maximum','exclusiveMinimum','exclusiveMaximum',
                'multipleOf','minProperties','maxProperties','description','descriptionOverride','descriptions','title','default','examples','definitions','localDefinitions','synopsis'}
            if set(schema)-known:raise ValueError('Unknown log schema keyword')
            super().validate(schema,value,path=path,depth=depth)
    walker=Walker(uri=uri,version=version);walker.context=context
    try:walker.validate(_log_node_at(root,route,pointer),json.loads(value_json),path='exact-log-alternative')
    except (ValueError,SemanticValidationError,TypeError):return False
    return not walker.unresolved_refs


def _log_predicate(branch,node,value,root):
    kind=branch['kind']
    if kind=='nullable':return value is None
    if kind not in {'schema','reference'}:return fixed.predicate(branch,node,value,root)
    if value is runtime._CONTRIBUTION_ABSENT:return False
    pointer=branch['pointer'].rsplit('/',1)[0]if kind=='reference'else branch['pointer']
    if type(node)is bool:pointer=pointer.rsplit('/',1)[0]
    return _log_alternative(root,branch['route'],pointer,json.dumps(value,ensure_ascii=False,sort_keys=True))


def _log_occurrences(record,tokens,prefix=''):
    if not tokens:
        yield prefix,record
        return
    token,*rest=tokens
    if token=='*':
        if type(record)is list:
            for i,value in enumerate(record):yield from _log_occurrences(value,rest,prefix+'/'+str(i))
    elif isinstance(token,tuple):
        import re
        if type(record)is dict:
            for key,value in record.items():
                if re.search(token[1],key):
                    yield from _log_occurrences(value,rest,prefix+'/'+key.replace('~','~0').replace('/','~1'))
    elif type(record)is dict:
        if token in record:yield from _log_occurrences(record[token],rest,prefix+'/'+token)
        elif not rest:yield prefix+'/'+token,runtime._CONTRIBUTION_ABSENT


def _normalized_log_input(branch,captured):
    """Exact public choices normalize documented defaults, without wire-absence claims."""
    uri=branch['route'].split('|')[-1]
    if uri not in LOG_URIS-{LOG_GET}:return None
    source=review()['normalized_input_choices'].get(branch['id'])
    if source is None:return None
    flag,default=source['public_flag'],source['native_default']
    field='severity'if flag=='--severity'else'channel'
    version,host,_,_,_=branch['route'].split('|');schema=_log_catalog(audit.ROOT,version,host)['schemas'][uri]['argsSchema']['properties'][field]
    if audit.digest(schema)!=source['schema_sha256']or "Default is '"+default+"'"not in schema['description']:
        raise ValueError('Exact matching native default semantics differ')
    declaration=captured['public_calls'][1]['gateway']['argv']
    form=source['public_form']
    valid=(flag not in declaration if form=='omitted'else flag in declaration and declaration[declaration.index(flag)+1]=='general')
    if valid and captured['native_call']['args'].get(field)==default:
        return {'public_flag':flag,'public_form':form,'native_default':default,
            'native_pointer':'/native_call/args'if branch['pointer']=='/argsSchema/@empty/object'else'/native_call/args/'+field}
    return None


def _log_mappings(inventory,captured,route):
    branches=[b for b in inventory['native_coverage']['obligations']if b['route']==route['id']]
    edges={b['id']:b for b in branches if b['kind']=='reference'};found=[]
    for branch in branches:
        normalized=_normalized_log_input(branch,captured)
        if normalized:
            found.append({'branch':branch,'program_pointer':normalized['native_pointer'],'reference_chain':[],
                'normalized_input_choice':normalized})
            continue
        node=_log_node(branch,audit.ROOT)
        for chain in runtime._contribution_chains(branch,edges):
            hit=next(((p,v)for p,v in _log_occurrences(captured,runtime._contribution_pattern(branch,chain,edges))
                if _log_predicate(branch,node,v,audit.ROOT)),None)
            if hit:
                found.append({'branch':branch,'program_pointer':hit[0],'reference_chain':chain})
                break
    return found

def write_log_bundle(output,captures,*,inventory):
    """Publish log occurrences through the existing portable index/attachment contract."""
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    original=original_log();r=original['review'];candidate=inventory['native_coverage']['candidate_sha256']
    for name in ('r122-original.json.gz','r122-category.json','r122-support.json'):
        shutil.copyfile(audit.ROOT/FIXTURE/name,output/name)
    def write(name,value):return runtime.write_json(output/name,value)
    def desc(name):return {'artifact':name,'sha256':runtime.sha((output/name).read_bytes())}
    (output/'r122-receipt.json').write_bytes(original['receipt_raw'])
    index={'contract':'waapi-skill.branch-evidence-index/v1','base':'.','entries':[],'runtime_observation_attachments':[]}
    requirements={'contract':'waapi-skill.branch-evidence-requirements/v1','branches':{}}
    seen=set()
    for number,path in enumerate(captures):
        captured=json.loads(Path(path).read_bytes());native=captured['native_call'];gateway=captured['gateway']
        info=next(x['result']for x in captured['native_reads']if x['uri']=='ak.wwise.core.getInfo')
        context=completion.native_host_context(info,'isCommandLine')
        route,=[x for x in inventory['native_coverage']['routes']if x['uri']==native['uri']and all(x[k]==v for k,v in context.items())]
        public,=[x for x in inventory['routes']if x['id']==route['public_route']]
        mappings=_log_mappings(inventory,captured,route)
        mappings=[x for x in mappings if x['branch']['id']not in seen]
        if not mappings:continue
        prefix='log-'+str(number)+'-';cp=write(prefix+'capture.json',captured)
        program={'candidate_sha256':candidate,'scope_kind':'product','relevant_sources':captured['source_context']['packaged'],
            'gateway':gateway,'native_call':native,'runtime_read_program':captured,
            'invocation':{'phase':'final','outcome':'PASS','node_outcomes':[{'nodeid':captured['nodeid'],'outcome':'PASS'}]},'branch_assertions':{}}
        bindings={'contract':'waapi-skill.branch-bindings/v1','bindings':{}};policies={'contract':requirements['contract'],'branches':{}}
        for m in mappings:
            branch=m['branch'];identity=branch['id'];entry=exact_entry(branch);pointer=m['program_pointer']
            pp='/gateway/payload/agent_result'
            assertion={'native_shape_sha256':branch['shape_sha256'],'native_route':route['id']}
            check=({'pointer':pointer,'absent':True} if branch['kind']=='optional_presence'and branch['value']=='absent'and not m.get('normalized_input_choice') else
                {'pointer':pointer,'cardinality':branch['value']}if branch['kind']=='collection_cardinality'else{'pointer':pointer,'equals':completion.pointer_value(program,pointer)})
            program['branch_assertions'][identity]={**assertion,'checks':[check,{'pointer':pp,'equals':completion.pointer_value(program,pp)}]}
            binding={'branch_id':identity,'native_shape_sha256':branch['shape_sha256'],'public_route':public['id'],'public_route_sha256':audit.digest(public),
                **({'normalized_input_choice':m['normalized_input_choice']}if m.get('normalized_input_choice')else{}),
                'input':{'gateway_argv':gateway['argv'],'selector':pointer},'dispatch_pointer':'/native_call','observation_pointer':pointer,'gateway_observation_pointer':pp,
                'reference_chain':m['reference_chain'],'relevant_sources':sorted(captured['source_context']['packaged']),'evidence':{},
                **_code_bindings(branch)}
            validate_program(program,binding,branch,audit.ROOT,{b['id']:b for b in inventory['native_coverage']['obligations']if b['kind']=='reference'})
            bindings['bindings'][identity]=binding;policies['branches'][identity]=policy(entry);seen.add(identity)
            if entry['role']=='native_business_anchor'and route['id']in {R122_ROUTE+uri for uri in LOG_URIS}:
                expected=_original_call(original,native['uri']);request=_original_request(original,native['uri'])
                if native!={'uri':request['api'],'args':request['args'],'options':request['options'],'result':expected['result']}:raise ValueError('Exact complete R122 request/result replay required for log gate')
                raw_name=prefix+'r122-raw.json'
                (output/raw_name).write_bytes(original['read'](expected['path']))
                capture=desc('r122-receipt.json');raw=desc(raw_name)
                native_run={**original['category'],'observation_sha256':[capture['sha256'],raw['sha256']]}
                native_checks=[{'pointer':'/observations/raw/result','equals':native['result']}]
                native_record={'candidate_sha256':candidate,'scope_kind':'product','evidence_kind':'native_execution','relevant_sources':original['sources'],
                    'native_runs':[native_run],'invocation':original['context']['record']['invocation'],'observation_artifacts':{'capture':capture,'raw':raw},
                    'branch_assertions':{identity:{**assertion,'checks':native_checks}}}
                nd={**write(prefix+'native.json',native_record),'nodeid':r['nodeid']}
                proof=write(prefix+'proof.json',{'contract':'waapi-skill.runtime-observation-proof/v1','branch_id':identity,'native_shape_sha256':branch['shape_sha256'],
                    'mapping':{'branch_id':identity,'native_shape_sha256':branch['shape_sha256'],'program_pointer':pointer,'native_pointer':'/observations/raw/result','raw_observation':raw},
                    'program_capture':cp,'archive':original['archive'],'capture':capture,'capture_original_path':r['receipt_path'],'native_run':native_run,
                    'relevant_sources':original['sources'],'source_review':desc('r122-support.json')})
                attached=deepcopy(binding);attached.update(runtime_observation_attachment=proof,program_observation_pointer=pointer,observation_pointer='/observations/raw/result',
                    native_observations_sha256={'capture':capture['sha256'],'raw':raw['sha256']})
                eq=write(prefix+'equivalence.json',{'contract':'waapi-skill.branch-evidence-equivalence/v1','from_candidate':R122_CANDIDATE,'to_candidate':candidate,
                    'branch_id':identity,'native_shape_sha256':branch['shape_sha256'],'native_route':route['id'],'evidence_sha256':native_run['sha256'],
                    'binding_semantics_sha256':audit.digest(completion.binding_semantics(attached)),'reviewed_reason':'Exact retained R122 log business facts/current full public replay and pinned complete reviewed packaged-source delta; no generic host/version reuse',
                    'sources':original['sources'],'runtime_remaining_source_review':desc('r122-support.json')})
                index['runtime_observation_attachments'].append(write(prefix+'attachment.json',{'contract':'waapi-skill.runtime-observation-attachment/v1','branch_id':identity,'proof':proof,'evidence':nd,'native_equivalence':eq}))
            elif entry['role']=='native_business_anchor':
                from tests.support.runtime_log_retained_evidence import attach_gate
                attach_gate(output,index,candidate,branch,binding,cp,prefix)
        pd={**write(prefix+'program.json',program),'nodeid':captured['nodeid']}
        for binding in bindings['bindings'].values():binding['evidence']['program']=pd
        bd=write(prefix+'bindings.json',bindings);rd=write(prefix+'requirements.json',policies)
        index['entries'].append({'id':prefix,'bindings':bd,'origin':{'bindings':bd,'program':desc(prefix+'program.json'),'requirements':rd,'capture':cp}})
        requirements['branches'].update(policies['branches'])
    if seen!={b['id']for b in inventory['native_coverage']['obligations']}:
        raise ValueError('Missing exact public log branches: '+str([b['pointer']for b in inventory['native_coverage']['obligations']if b['id']not in seen]))
    write('requirements.json',requirements);write('index.json',index)
    return output/'index.json'
