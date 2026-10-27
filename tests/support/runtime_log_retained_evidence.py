"""Closed retained log facts behind the existing qualified-evidence attachment.

Original FAIL/BLOCKED outcomes stay original. Only nineteen pinned log roots
qualify here; three R122 roots use their original finalized-PASS path instead.
Two older Console clear roots retain ACK/schema-only native facts, without effect credit.
"""
from functools import lru_cache
import json
from pathlib import Path
import shutil
import subprocess

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support import runtime_observation_evidence as runtime

SUPPORT='tests/fixtures/runtime-log/retained-log-support.json'
SUPPORT_SHA = '1ab373b97e0b20dd849cf1b4915603785d59e030427163e3fd5c6b66f8abc97c'
CONTRACT='waapi-skill.retained-log-assessment/v1'


@lru_cache(maxsize=32)
def _catalog_seal(path,seal,signature):
    if runtime.sha(path.read_bytes())!=seal:raise ValueError('Exact retained log catalog differs')


def review(root=audit.ROOT):
    from tests.support.runtime_remaining_evidence import _read_pin,review as remaining
    result=_read_pin(root/SUPPORT,SUPPORT_SHA)
    if len(result['profiles'])!=19 or result['pending_native_business_anchor_ids']!=[]:
        raise ValueError('Exact retained log roster differs')
    entries=remaining(root)['entries']
    for identity,profile in result['profiles'].items():
        entry=entries[identity]
        if (entry['role']!='native_business_anchor'or profile['target_route']!=entry['route']
                or profile['native_shape_sha256']!=entry['native_shape_sha256']
                ):
            raise ValueError('Exact retained log target scope/schema differs')
        path=root/profile['target_catalog'];stat=path.stat()
        _catalog_seal(path,profile['target_catalog_sha256'],(stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns))
    return result


@lru_cache(maxsize=8)
def _historical(root,candidate,sources_json):
    sources=json.loads(sources_json)
    names=subprocess.check_output(['git','ls-tree','-r','--name-only',candidate,'--','skills/waapi-skill'],cwd=root,text=True).splitlines()
    if set(names)!=set(sources)or completion.historical_source_seals(root,candidate,sources)!=sources:
        raise ValueError('Complete historical log packaged source map differs')


def retained(label,base=None,*,root=audit.ROOT):
    descriptor=review(root)['providers'][label]
    archive_path=root/descriptor['archive_source']if base is None else Path(base)/(label+'-original.json.gz')
    base=archive_path.parent
    archive={'artifact':archive_path.name,'sha256':descriptor['archive_sha256']}
    read=runtime.archive_reader(archive,base)
    import gzip
    files=json.loads(gzip.decompress(archive_path.read_bytes()))['files']
    if len(files)!=descriptor['archive_files']or audit.digest(files)!=descriptor['archive_map_sha256']:
        raise ValueError('Whole original log closure differs')
    raw=read(descriptor['capture_path']);capture=json.loads(raw)
    context=completion.native_host_context(capture['host'],'isCommandLine')
    if (runtime.sha(raw)!=descriptor['capture_sha256']or capture['candidate']!=descriptor['candidate']
            or context!={k:descriptor[k]for k in ('version','host','build')}):
        raise ValueError('Exact retained log producer/host/build differs')
    sources=descriptor['sources'];_historical(root,descriptor['candidate'],json.dumps(sources,sort_keys=True))
    current=runtime.program_source_context(root,flow='ak.wwise.core.log.get')['packaged']
    changes={p:{'before':sources.get(p),'after':current.get(p)}for p in sources.keys()|current.keys()if sources.get(p)!=current.get(p)}
    if len(current)!=413 or changes!=descriptor['source_changes']:
        runtime.retained_runtime_sources(sources, root)
    if descriptor.get('kind')=='console-clear-schema-ack':
        return _console_clear_ack(descriptor,archive,read,capture,raw)
    root_name=descriptor['original_root']
    root_review=json.loads(read(root_name+'/root-review.json'))
    if root_review['candidate']!=descriptor['candidate']or root_review['source_unchanged']is not True:
        raise ValueError('Original source-preservation review differs')
    requests={};results={};get='ak.wwise.core.log.get';add='ak.wwise.core.log.addItem';clear='ak.wwise.core.log.clear'
    if descriptor['host']=='wwise-authoring':
        node=json.loads(read(descriptor['node_path']));manifest={}
        for group in node['artifacts'].values():
            for item in group['files']:
                p=group['path']+'/'+item['path'];body=read(p)
                if runtime.sha(body)!=item['sha256']or len(body)!=item['bytes']or p in manifest:
                    raise ValueError('Original complete node artifact manifest differs')
                manifest[p]=body
        if (node['candidate']!=descriptor['candidate']or any(node['source_context']['sources'].get(p)!=seal for p,seal in sources.items())
                or capture['cleanup']['complete']is not True or capture['cleanup']['errors']!=[]
                or capture['fixture_before']!=capture['fixture_after']):
            raise ValueError('Exact retained log node source/physical cleanup/preservation differs')
        if label.startswith('r104'):
            life=json.loads(read(root_name+'/evidence/lifecycle.json'));quarantine=json.loads(read(root_name+'/evidence/quarantine.json'))
            if (life['final_status']!='BLOCKED'or life['errors']!=[]or life['sandbox_retained']is not True
                    or life['source_hash_before']!=life['source_hash_after']or life['source_mtime_before_ns']!=life['source_mtime_after_ns']
                    or quarantine['status']!='BLOCKED'or quarantine['never_reuse']is not True
                    or root_review['formal_outcome']!='BLOCKED'or root_review['integrity_errors']!=[]or root_review['lifecycle_errors']!=[]
                    or root_review['post_terminal_owned_processes']!=[]
                    or any(root_review[k]is not True for k in ('cleanup_complete','fixture_preserved','post_terminal_port_8080_bindable'))):
                raise ValueError('Original R104 BLOCKED status/physical cleanup must remain')
        else:
            seal=json.loads(read(root_name+'/evidence/authoring-batch-finalization.json'))
            life=json.loads(read(root_name+'/evidence/lifecycle-final.json'))
            if (seal['candidate']!=descriptor['candidate']or seal['outcome']!='PASS'or root_review['pytest']['exit_code']!=0
                    or root_review['port_released']is not True or life['final_status']!='PASS'or life['sandbox_retained']is not False
                    or life['source_hash_before']!=life['source_hash_after']or life['source_mtime_before_ns']!=life['source_mtime_after_ns']):
                raise ValueError('Original R92 finalized PASS/teardown must remain')
        addition=capture['outcomes']['runtime-owned-log-add'];removal=capture['outcomes']['runtime-owned-log-clear']
        a,b=addition['evidence'],removal['evidence'];before=capture['logs']['general_before'];after=a['rows_after'];message=capture['logs']['message']
        matches=lambda row:row['message']==message and row['severity']=='Message'
        if (addition['outcome']!='PASS'or removal['outcome']!='PASS'or not sum(map(matches,after))>sum(map(matches,before))
                or a['message']!=message or b['rows_after']!=[]or b['other_after']!=capture['logs']['other_before']
                or a['exclusive_causation_verified']is not False or b['continuing_channel_state_verified']is not False):
            raise ValueError('Actual owned log addition/clear and other-channel facts required')
        for uri,e in ((add,a),(clear,b)):
            tx=e['transaction']
            if tx['verified']is not True or tx['state']!='verified':raise ValueError('Original log effect verification missing')
            requests[uri]=tx['agent_result']['request']['arguments'];results[uri]=tx['agent_result']['result']
        requests[get]={'api':get,'args':{'channel':'general'},'options':{}};results[get]={'items':after}
        facts={'original_workflow_outcome':descriptor['original_workflow_outcome'],'original_finalization':descriptor['original_workflow_outcome'],
            'qualified_log_fact':'owned-addition-and-prior-contents-cleared','physical_cleanup_complete':True,'global_pass_transferred':False}
    else:
        tx=capture['transaction'];observer=root_review['observer']
        if (descriptor['original_workflow_outcome']!='FAIL'or '1 failed'not in root_review['pytest']
                or type(root_review['port_released'])is not int or observer['outcome']!='timeout'or observer['events_observed']!=0
                or observer['cleanup']!={'status':'unsubscribed'}or tx['verify']['verified']is not False
                or tx['verify']['state']!='result_schema_checked'):
            raise ValueError('Original R98 FAIL/unobservable/no-effect/unsubscribe facts must remain')
        requests[add]=tx['verify']['agent_result']['request']['arguments'];results[add]=tx['verify']['agent_result']['result']
        requests[get]={'api':get,'args':{'channel':'general'},'options':{}};results[get]={'items':[]}
        facts={'original_workflow_outcome':'FAIL','original_finalization':'FAIL','qualified_log_fact':'native-schema-ack-and-empty-unobservable-getter-only',
            'effect_observed':False,'observer_events':0,'observer_cleanup':'unsubscribed','port_released':root_review['port_released'],'global_pass_transferred':False}
    calls={}
    for uri,result in results.items():
        call=next((x for x in descriptor['calls']if x['api']==uri and x['result']==result),None)
        if call is None:raise ValueError('Whole actual native log result missing')
        body=read(call['path']);native=json.loads(body)
        if (runtime.sha(body)!=call['sha256']or native['api']!=uri or native['result']!=result or native['version']!=descriptor['version']
                or native['ok']is not True or native['dry_run']is not False):
            raise ValueError('Exact retained native log call differs')
        calls[uri]=call
    return dict(descriptor=descriptor,archive={'artifact':label+'-original.json.gz','sha256':descriptor['archive_sha256']},read=read,capture=capture,capture_raw=raw,requests=requests,results=results,calls=calls,facts=facts)


def program_native_call(identity,*,root=audit.ROOT):
    profile=review(root)['profiles'][identity];original=retained(profile['provider'],root=root);uri=profile['target_route'].split('|')[-1]
    request=original['requests'][uri]
    return {'uri':uri,'args':request['args'],'options':request['options'],'result':original['results'][uri]}


def attach_gate(output,index,candidate,branch,binding,program_capture,prefix):
    """Use the existing ordinary qualified attachment; never relabel a run PASS."""
    identity=branch['id'];profile=review()['profiles'].get(identity)
    if profile is None:return
    original=retained(profile['provider']);label=profile['provider'];uri=branch['route'].split('|')[-1];output=Path(output)
    captured=completion.read_sealed_artifact(program_capture,output)
    if captured['native_call']!=program_native_call(identity):return  # Program-only packet cannot qualify this native gate.
    def write(name,value):return runtime.write_json(output/name,value)
    def desc(name):return {'artifact':name,'sha256':runtime.sha((output/name).read_bytes())}
    shutil.copyfile(audit.ROOT/original['descriptor']['archive_source'],output/(label+'-original.json.gz'))
    shutil.copyfile(audit.ROOT/SUPPORT,output/'retained-log-support.json')
    (output/(prefix+'raw.json')).write_bytes(original['read'](original['calls'][uri]['path']))
    assessment=write(prefix+'assessment.json',{'contract':CONTRACT,'branch_id':identity,'profile':profile,'provider':label,'source_review':desc('retained-log-support.json'),
        'archive':original['archive'],'raw':desc(prefix+'raw.json'),'program_capture':program_capture,'retained_facts':original['facts']})
    evidence=write(prefix+'qualified.json',{'candidate_sha256':candidate,'scope_kind':'product','evidence_kind':'qualified_retained_log_fact',
        'branch_id':identity,'native_shape_sha256':branch['shape_sha256'],'assessment_sha256':assessment['sha256'],'retained_facts':original['facts'],
        'relevant_sources':original['descriptor']['sources']})
    index.setdefault('qualified_runtime_read_attachments',[]).append(write(prefix+'qualified-attachment.json',
        {'contract':'waapi-skill.qualified-retained-read-attachment/v1','branch_id':identity,'assessment':assessment,'evidence':evidence}))


def qualified_result(descriptor,assessment,branch,candidate,scope_kind,base,binding,root,edges):
    from tests.support import runtime_remaining_evidence as remaining
    remaining.exact_entry(branch,root);profile=review(root)['profiles'].get(branch['id'])
    if (profile is None or assessment['contract']!=CONTRACT or assessment['branch_id']!=branch['id']or assessment['profile']!=profile
            or assessment['provider']!=profile['provider']or scope_kind!='product'
            or assessment['source_review']['sha256']!=SUPPORT_SHA or completion.read_sealed_artifact(assessment['source_review'],base)!=review(root)):
        raise ValueError('Only exact source-owned retained log root/relationship qualifies')
    original=retained(profile['provider'],base,root=root);uri=branch['route'].split('|')[-1]
    captured=completion.read_sealed_artifact(assessment['program_capture'],base);record=completion.read_sealed_artifact(descriptor,base)
    expected={'uri':uri,'args':original['requests'][uri]['args'],'options':original['requests'][uri]['options'],'result':original['results'][uri]}
    if (assessment['archive']!=original['archive']or assessment['retained_facts']!=original['facts']or record!={'candidate_sha256':candidate,'scope_kind':'product',
            'evidence_kind':'qualified_retained_log_fact','branch_id':branch['id'],'native_shape_sha256':branch['shape_sha256'],
            'assessment_sha256':binding['qualified_runtime_read_attachment']['sha256'],'retained_facts':original['facts'],'relevant_sources':original['descriptor']['sources']}
            or (base/assessment['raw']['artifact']).read_bytes()!=original['read'](original['calls'][uri]['path'])
            or assessment['raw']['sha256']!=runtime.sha(original['read'](original['calls'][uri]['path']))or captured['native_call']!=expected):
        raise ValueError('Exact original native fact/current whole replay/original outcome differs')
    if not runtime.retained_runtime_native(binding, branch, root, base):
        remaining.validate_program({'gateway':captured['gateway'],'native_call':captured['native_call'],'runtime_read_program':captured,
            'relevant_sources':captured['source_context']['packaged']},binding,branch,root,edges)
    return 'passed',None


def _console_clear_ack(descriptor,archive,read,capture,capture_raw):
    """Exactly two reviewed same-host/build ACKs; no effect observation inferred."""
    base=descriptor['original_root'];tx=capture['transaction'];uri='ak.wwise.core.log.clear'
    category=json.loads(read(base+'/evidence/category.jsonl').splitlines()[-1]);result=json.loads(read(base+'/result.json'))
    verification=tx['verify'];scope=capture['observation_boundary'];request=verification['agent_result']['request']['arguments']
    journal_path=descriptor['capture_path'].rsplit('/state/',1)[0]+'/state/transactions/'+tx['transaction_id']+'/events.jsonl'
    events=[json.loads(line)for line in read(journal_path).splitlines()]
    invocation=category['invocation'];nodes={x['nodeid']:x['outcome']for x in invocation['node_outcomes']}
    status=next(x for x in category['categories']if x['category']=='console-log-clear-schema-acknowledgement')
    if (descriptor['version']not in {'2023.1','2024.1'}or descriptor['host']!='wwise-console'
            or invocation['phase']!='final'or invocation['outcome']!='PASS'or nodes.get(descriptor['nodeid'])!='PASS'
            or category['candidate']!=descriptor['candidate']or status['status']!='PASS'or status['effect_observed']is not False
            or completion.native_host_context(category['host'],'is_command_line')!={k:descriptor[k]for k in ('version','host','build')}
            or result['exit_code']!=0 or result['timed_out']is not False or result['remaining_owned_group']!=[]
            or category['source']['hash_before']!=category['source']['hash_after']or category['source']['mtime_before_ns']!=category['source']['mtime_after_ns']
            or category['residual_state']['process_cleanup']!='cleaned'or category['residual_state']['sandbox']!='deleted'or category['residual_state']['residual_processes']!=[]
            or verification['state']!='result_schema_checked'or verification['verified']is not False
            or verification['verification']['business_state_verified']is not False
            or verification['verification']['verification_scope']['log_observation']!=scope
            or scope['outcome']!='console_log_unobservable'or scope['effect_observed']is not False
            or request!={'api':uri,'args':{'channel':'general'},'options':{}}
            or len(events)!=6 or sum(x['event_type']=='execution_started'for x in events)!=1
            or sum(x['event_type']=='execution_completed'for x in events)!=1
            or events[-1]['details']['verification']!=verification['verification']):
        raise ValueError('Exact older Console finalized once-only weak ACK/source/cleanup differs')
    call,=descriptor['calls'];body=read(call['path']);native=json.loads(body)
    if (runtime.sha(body)!=call['sha256']or native['api']!=uri or native['version']!=descriptor['version']
            or native['ok']is not True or native['dry_run']is not False or native['result']!={}
            or verification['agent_result']['result']!={}):
        raise ValueError('Exact older Console successful clear ACK differs')
    facts={'original_workflow_outcome':'PASS','original_finalization':'PASS','qualified_log_fact':'same-host-build-native-clear-schema-ack-only',
        'effect_observed':False,'business_state_verified':False,'physical_cleanup_complete':True,'global_pass_transferred':False}
    return dict(descriptor=descriptor,archive={'artifact':Path(archive['artifact']).name,'sha256':descriptor['archive_sha256']},read=read,
        capture=capture,capture_raw=capture_raw,requests={uri:request},results={uri:{}},calls={uri:call},facts=facts)
