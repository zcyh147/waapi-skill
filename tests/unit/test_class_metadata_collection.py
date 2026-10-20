"""Closed class metadata collection through the existing public Gateway seam."""
from pathlib import Path
import pytest

from tests.maintenance import collect_class_metadata as collector


def test_versioned_schedule_uses_only_owned_class_fields_and_keeps_unobserved_choices_missing():
    plans = {v:collector.collection_plan(v) for v in collector.BUILDS}
    assert plans['2022.1']['targets'] == {'Wwise Delay':['DelayTime','FeedbackEnabled'], 'Sound':['BypassEffect0','Effect0']}
    assert plans['2021.1']['targets'] == {'ModulatorTime':['EnvelopeStopPlayback']}
    assert plans['2023.1']['targets'] == {'Action':['Scope'],'EffectSlot':['Bypass','Effect']}
    assert plans['2024.1']['targets'] == {'Sound':['AttenuationDistanceScaling'],'EffectSlot':['Bypass','Effect']}
    assert plans['2025.1']['targets'] == {'Sound':['Weight'],'EffectSlot':['Bypass','Effect'],
        'ModulatorTime':['EnvelopeStopPlayback'],'MediaPoolFilter':['FieldName']}
    assert [len(p['eligible_branch_ids']) for p in plans.values()] == [1,10,9,9,12]
    for version,plan in plans.items():
        assert all('/@presence/absent' not in identity for identity in plan['eligible_branch_ids'])
        assert plan['limits']['gateway_invocations'] <= 48
        assert plan['limits']['native_bytes'] == 32*1024*1024
        assert plan['limits']['sealed_files'] == 512 and plan['limits']['sealed_bytes'] == 128*1024*1024
        assert plan['limits']['bytes_per_sealed_file'] == 1_048_576
        assert plan['project_mutation_commands'] == 0 and plan['agent_started'] is False


def public_gateway(tmp_path,version='2022.1',scope='Wwise Delay'):
    """Actual public Gateway with injected packets; controlled program only."""
    from copy import deepcopy
    import json
    from tests.unit import test_metadata_discovery_gateway as public
    root = tmp_path;root.mkdir(exist_ok=True)
    scopes = collector.SCHEDULE[version] if scope is None else {scope:collector.SCHEDULE[version][scope]}
    fields = next(iter(scopes.values()))
    responses = public._metadata_responses(root,version=version,names=tuple(fields))
    responses[public.GET_INFO_URI]['version']['minor']=int(collector.BUILDS[version].split('.')[2])
    responses[public.GET_TYPES_URI] = {'return':[{'classId':collector.CLASS_IDS[name],'name':name,'type':'Effect' if name=='Wwise Delay' else 'WObject'} for name in scopes]}
    responses[public.GET_NAMES_URI] = lambda args,options:{'return':list(next(values for name,values in scopes.items() if collector.CLASS_IDS[name]==args['classId']))}
    def info(args,options):
        assert options == {}
        declared = next(values for name,values in scopes.items() if collector.CLASS_IDS[name]==args['classId'])
        value = declared[args['property']]
        return {'name':args['property'],'type':'bool' if type(value) is bool else '' if value is None else 'string' if type(value) is str else 'Real32',
            'default':deepcopy(value),'dependencies':[]}
    responses[public.GET_PROPERTY_INFO_URI] = info
    responses['ak.wwise.core.getProjectInfo'] = public._project_row(root)
    client = public.FakeClient(responses)
    env = public._gateway_env(root,version=version)
    env['WWISE_EVIDENCE_DIR'] = str(root/'dispatcher-evidence')
    code,result=public.waapi_gateway.execute_gateway(['config-set','--project-modification-policy','read_only'],env=env)
    assert code == 0,result
    index = 0
    def gateway(argv):
        nonlocal index
        code,payload = public.waapi_gateway.execute_gateway(argv,env=env,client_factory=lambda _:client)
        assert code == 0,payload
        index += 1;stem=f'{index:03}'
        (root/(stem+'.stdout')).write_text(json.dumps(payload,allow_nan=False))
        (root/(stem+'.command.json')).write_text(json.dumps({'gateway_arguments':argv}))
        (root/(stem+'.exit.json')).write_text(json.dumps({'exit_code':code,'launched':True,'child_reaped':True}))
        if 'agent_result' in payload:(root/(stem+'.agent-result.json')).write_text(json.dumps(payload['agent_result'],allow_nan=False))
        return payload,stem
    return gateway,client


def test_closed_collector_uses_live_public_selections_and_seals_actual_dispatcher_bytes(tmp_path):
    gateway,client = public_gateway(tmp_path)
    rows = collector.collect_scope(gateway,'2022.1','Wwise Delay',['DelayTime','FeedbackEnabled'],tmp_path,lambda:None)
    assert [row['field'] for row in rows] == ['DelayTime','FeedbackEnabled']
    assert [row['observed_default'] for row in rows] == [0.5,True]
    assert all(row['status']=='captured' and row['native_receipt'].startswith('dispatcher-evidence/') for row in rows)
    assert all((tmp_path/row['native_receipt']).is_file() for row in rows)
    assert client.disconnected


def controlled_capture(tmp_path):
    """Synthetic lifecycle wrapper for reader controls only; zero native credit."""
    import json,hashlib,subprocess
    gateway,_ = public_gateway(tmp_path,scope=None)
    status,stem = gateway(['status'])
    rows=[]
    for scope,fields in collector.collection_plan('2022.1')['targets'].items():
        rows.extend(collector.collect_scope(gateway,'2022.1',scope,fields,tmp_path,lambda:None))
    def write(name,value):(tmp_path/name).write_text(json.dumps(value,allow_nan=False))
    write('targets.json',rows)
    write('initial-status.json',{'receipt':stem})
    source={'digest':'controlled-source','strategy':'full'}
    lifecycle={'contract':'waapi-skill.codex-semantic-scenario-lifecycle/v3','version':'2022.1','final_status':'PASS',
        'sandbox_retained':False,'errors':[],'source_hash_before':source,'source_hash_after':source,
        'source_mtime_before_ns':1,'source_mtime_after_ns':1}
    write('summary.json',{'status':'PASS','lifecycle':lifecycle,'project_mutation_commands':0,'agent_started':False,'invocation':{'phase':'final','outcome':'PASS',
        'node_outcomes':[{'nodeid':collector.collection_plan('2022.1')['collector_nodeid'],'outcome':'PASS'}]}})
    write('ready.json',{'get_info':status['wwise'],'source_hash_before':source,'source_mtime_before_ns':1,
        'host':status['endpoint']['host'],'port':status['endpoint']['port']})
    plan=collector.collection_plan('2022.1')
    plan['observation_origin']='controlled_public_gateway'
    # Keep only the exercised scope; it is still one exact scheduled source.
    plan['actual_deadlines']={'readiness_seconds':180,'total_seconds':600}
    plan['source_seals']=collector.source_links('2022.1',plan['targets'])[1]
    plan['repositories']=[{'checkout':str(collector.REPO),'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=collector.REPO,text=True).strip()}]
    write('plan.json',plan)
    write('cleanup.json',{'process_exited':True,'residual_processes':[]})
    files=[{'path':p.relative_to(tmp_path).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size}
        for p in tmp_path.rglob('*') if p.is_file() and not p.is_relative_to(tmp_path/'config')]
    write('evidence-seal.json',{'contract':'waapi-skill.class-metadata-seal/v1','files':files})
    return collector.metadata_descriptors(tmp_path)


def test_existing_scenario_reader_accepts_exact_sealed_class_native_and_public_packets(tmp_path):
    from tests.maintenance import branch_audit_completion as reader
    descriptor=controlled_capture(tmp_path)['2022.1|Wwise Delay|DelayTime']
    context=reader.read_metadata_run(descriptor,tmp_path)
    assert context['native_result']['default'] == 0.5
    assert context['class_name'] == 'Wwise Delay' and context['class_id'] == 6946819
    assert context['field'] == 'DelayTime'
    assert context['gateway']['argv'][:4] == ['metadata','detail','--custom-kind','Wwise Delay']


@pytest.mark.parametrize('damage',['native-bytes','wrong-class','wrong-sibling','wrong-selection','missing-default',
    'true-vs-one','missing-parent','cleanup','source-omission','lifecycle-source-omission','session','target-occurrence','extra-descriptor'])
def test_class_reader_corruption_starts_from_valid_sealed_public_baseline(tmp_path,damage):
    import json,hashlib
    from tests.maintenance import branch_audit_completion as reader
    descriptor=controlled_capture(tmp_path)['2022.1|Wwise Delay|FeedbackEnabled']
    assert reader.read_metadata_run(descriptor,tmp_path)['native_result']['default'] is True
    targets=json.loads((tmp_path/'targets.json').read_bytes());target=targets[descriptor['target_index']]
    native_path=tmp_path/target['native_receipt']
    if damage=='native-bytes':
        native_path.write_text('{}')
    elif damage=='extra-descriptor':descriptor['extra']=True
    elif damage=='target-occurrence':descriptor['target_index']=0
    else:
        payload=json.loads((tmp_path/(descriptor['receipt']+'.stdout')).read_bytes())
        native=json.loads(native_path.read_bytes())
        if damage=='wrong-class':payload['agent_result']['scope']['resolved']['classId']=65552
        elif damage=='wrong-sibling':payload['agent_result']['metadata']['name']=native['result']['name']='OtherField'
        elif damage=='wrong-selection':payload['agent_result']['selection']='mf1.unissued'
        elif damage=='missing-default':
            del payload['agent_result']['metadata']['default'];del native['result']['default']
        elif damage=='true-vs-one':payload['agent_result']['metadata']['default']=native['result']['default']=1
        elif damage=='missing-parent':del payload['agent_result']['metadata']
        elif damage=='cleanup':(tmp_path/'cleanup.json').write_text(json.dumps({'process_exited':True,'residual_processes':[1]}))
        elif damage in {'source-omission','lifecycle-source-omission'}:
            plan=json.loads((tmp_path/'plan.json').read_bytes())
            if damage=='lifecycle-source-omission':
                dependency=str(collector.REPO/'tests/destructive/support/live_environment.py')
                assert any(row['path']==dependency for row in plan['source_seals'])
                plan['source_seals']=[row for row in plan['source_seals'] if row['path']!=dependency]
            else:plan['source_seals']=plan['source_seals'][1:]
            (tmp_path/'plan.json').write_text(json.dumps(plan))
        elif damage=='session':
            ready=json.loads((tmp_path/'ready.json').read_bytes());ready['get_info']['processId']+=1
            (tmp_path/'ready.json').write_text(json.dumps(ready))
        (tmp_path/(descriptor['receipt']+'.stdout')).write_text(json.dumps(payload))
        (tmp_path/(descriptor['receipt']+'.agent-result.json')).write_text(json.dumps(payload['agent_result']))
        native_path.write_text(json.dumps(native))
        target['native_sha256']=hashlib.sha256(native_path.read_bytes()).hexdigest();target['native_bytes']=native_path.stat().st_size
        (tmp_path/'targets.json').write_text(json.dumps(targets))
        seal=json.loads((tmp_path/'evidence-seal.json').read_bytes())
        for entry in seal['files']:
            path=tmp_path/entry['path'];entry.update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),bytes=path.stat().st_size)
        (tmp_path/'evidence-seal.json').write_text(json.dumps(seal));descriptor['seal']['sha256']=hashlib.sha256((tmp_path/'evidence-seal.json').read_bytes()).hexdigest()
    with pytest.raises((ValueError,KeyError,TypeError)):
        reader.read_metadata_run(descriptor,tmp_path)


def test_current_class_native_attachment_uses_own_input_and_keeps_program_independent(tmp_path):
    import json
    from tests.maintenance import branch_coverage_audit as audit,branch_audit_completion as reader
    root=tmp_path/'native';root.mkdir();controlled_capture(root)
    inventory=audit.load(audit.ROOT/'docs/branch-coverage-inventory.json')
    descriptors=collector.write_branch_attachments(root,inventory,scope_kind='controlled')
    assert len(descriptors)==10
    attachment=reader.read_sealed_artifact(descriptors[0],tmp_path)
    branch=next(row for row in inventory['native_coverage']['obligations'] if row['id']==attachment['branch_id'])
    bindings,base,_=audit.portable_binding_inputs(audit.ROOT/'docs/branch-coverage-evidence-index.json',audit.load(audit.ROOT/'docs/branch-coverage-requirements.json'))
    binding=bindings['bindings'][branch['id']]
    assert binding['input']['gateway_argv'] != attachment['category_inputs']['native']
    binding={**binding,'category_inputs':{'live_metadata':attachment['category_inputs']}}
    edges={row['id']:row for row in inventory['native_coverage']['obligations'] if row['kind']=='reference'}
    assert reader.evidence_result(attachment['evidence'],branch,inventory['native_coverage']['candidate_sha256'],
        'live_metadata','controlled',tmp_path,binding,source_root=audit.ROOT,reference_edges=edges)==('passed',None)
    assert reader.evidence_result(attachment['evidence'],branch,inventory['native_coverage']['candidate_sha256'],
        'live_metadata','product',tmp_path,binding,source_root=audit.ROOT,reference_edges=edges)[0]=='missing'


def portable_class_index(tmp_path):
    import json,shutil,hashlib
    from tests.maintenance import branch_coverage_audit as audit,branch_audit_completion as reader
    native=tmp_path/'native';native.mkdir();controlled_capture(native)
    inventory=audit.load(audit.ROOT/'docs/branch-coverage-inventory.json')
    attachment=collector.write_branch_attachments(native,inventory,scope_kind='controlled')[0]
    identity=reader.read_sealed_artifact(attachment,tmp_path)['branch_id']
    index=audit.load(audit.ROOT/'docs/branch-coverage-evidence-index.json');source=(audit.ROOT/'docs'/index['base']).resolve()
    entry=next(e for e in index['entries'] if identity in json.loads((source/e['bindings']['artifact']).read_bytes())['bindings'])
    base=tmp_path/'bundle';base.mkdir()
    for desc in [entry['bindings'],*entry['origin'].values()]:
        dest=base/desc['artifact'];dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/desc['artifact'],dest)
    shutil.copytree(native,base/native.name)
    document={'contract':index['contract'],'base':'bundle','entries':[entry],'metadata_attachments':[attachment]}
    path=tmp_path/'index.json';path.write_text(json.dumps(document))
    return path,identity,document,base


def test_portable_current_class_native_attachment_preserves_original_program_projection(tmp_path):
    from tests.maintenance import branch_coverage_audit as audit
    path,identity,index,base=portable_class_index(tmp_path)
    policy=audit.load(audit.ROOT/'docs/branch-coverage-requirements.json')
    before,_,_=audit.portable_binding_inputs(audit.ROOT/'docs/branch-coverage-evidence-index.json',policy)
    actual,_,_=audit.portable_binding_inputs(path,policy)
    assert actual['bindings'][identity]['input']==before['bindings'][identity]['input']
    assert actual['bindings'][identity]['evidence']['program']==before['bindings'][identity]['evidence']['program']
    assert set(actual['bindings'][identity]['category_inputs']['live_metadata'])=={'native'}


@pytest.mark.parametrize('version,scope',[(v,s) for v,scopes in collector.SCHEDULE.items() for s in scopes
    if (v,s)!=('2022.1','Wwise Delay')])
def test_matching_version_class_schedule_runs_through_actual_public_gateway(tmp_path,version,scope):
    gateway,client=public_gateway(tmp_path,version,scope)
    rows=collector.collect_scope(gateway,version,scope,list(collector.SCHEDULE[version][scope]),tmp_path,lambda:None)
    assert [row['field'] for row in rows]==list(collector.SCHEDULE[version][scope])
    for row in rows:
        expected=collector.SCHEDULE[version][scope][row['field']]
        assert row['default_present'] is True
        assert type(row['observed_default']) is type(expected) and row['observed_default']==expected
    assert client.disconnected


@pytest.mark.parametrize('damage',['count','bytes'])
def test_native_archive_bounds_fail_closed_before_publication(tmp_path,damage):
    root=tmp_path/'dispatcher-evidence';root.mkdir()
    assert collector.native_archive_entries(tmp_path)==[]
    if damage=='count':
        for i in range(129):(root/(str(i)+'.json')).write_text('{}')
    else:(root/'oversized.json').write_bytes(b' '*(1_048_576+1))
    with pytest.raises(collector.HostFailure,match='bound exceeded'):collector.native_archive_entries(tmp_path)


@pytest.mark.parametrize('damage',['count','plan-bytes','console-bytes','total-bytes'])
def test_final_seal_bounds_cover_all_archived_originals_before_publication(tmp_path,damage):
    import json
    scenario=tmp_path/'scenario';scenario.mkdir()
    (scenario/'private-project').write_text('not portable evidence')
    (tmp_path/'gateway-config.json').write_text('private config')
    (tmp_path/'plan.json').write_text('{}')
    (tmp_path/'console-output.json').write_text('{}')
    collector.write_final_seal(tmp_path,scenario)
    seal=tmp_path/'evidence-seal.json'
    assert {row['path'] for row in json.loads(seal.read_bytes())['files']}=={'plan.json','console-output.json'}
    seal.unlink()  # Each corruption begins after a valid finalized archive.
    if damage=='count':
        for i in range(511):(tmp_path/str(i)).write_text('{}')
    elif damage in {'plan-bytes','console-bytes'}:
        name='plan.json' if damage=='plan-bytes' else 'console-output.json'
        with (tmp_path/name).open('wb') as stream:stream.truncate(1_048_577)
    else:
        for i in range(129):
            with (tmp_path/str(i)).open('wb') as stream:stream.truncate(1_048_576)
    with pytest.raises(collector.HostFailure,match='sealed archive bound exceeded'):
        collector.write_final_seal(tmp_path,scenario)
    assert not seal.exists()


@pytest.mark.parametrize('damage',['duplicate','extra','dependency-escape','dependency-byte','source-extra','input-borrow','extra-archive'])
def test_portable_class_transport_controls_start_from_valid_sealed_baseline(tmp_path,damage):
    import json,hashlib
    from tests.maintenance import branch_coverage_audit as audit
    path,identity,index,base=portable_class_index(tmp_path)
    policy=audit.load(audit.ROOT/'docs/branch-coverage-requirements.json')
    before,_,_=audit.portable_binding_inputs(path,policy)
    assert 'live_metadata' in before['bindings'][identity]['evidence']
    item_desc=index['metadata_attachments'][0];item=json.loads((base/item_desc['artifact']).read_bytes())
    record_desc=item['evidence'];record=json.loads((base/record_desc['artifact']).read_bytes())
    if damage=='duplicate':index['metadata_attachments'].append(dict(item_desc))
    elif damage=='extra':item['extra']=True
    elif damage=='dependency-byte':(base/'native'/'targets.json').write_text('[]')
    elif damage=='source-extra':record['source_context']['arbitrary_equivalence']=True
    elif damage=='input-borrow':item['category_inputs']['program_override']=['metadata','detail']
    elif damage=='extra-archive':record['metadata_run']['extra']=True
    else:record['metadata_run']['root']='../escape'
    if damage in {'source-extra','extra-archive','dependency-escape'}:
        target=base/record_desc['artifact'];target.write_text(json.dumps(record));record_desc['sha256']=hashlib.sha256(target.read_bytes()).hexdigest()
    if damage not in {'duplicate','dependency-byte'}:
        target=base/item_desc['artifact'];target.write_text(json.dumps(item));item_desc['sha256']=hashlib.sha256(target.read_bytes()).hexdigest()
    path.write_text(json.dumps(index))
    with pytest.raises(ValueError):audit.portable_binding_inputs(path,policy)


@pytest.mark.parametrize('damage',['input','source','whole-proof','leaf-proof','reference','product-origin','product-git'])
def test_current_native_category_controls_do_not_borrow_program_or_other_sources(tmp_path,damage):
    import json,hashlib
    from copy import deepcopy
    from tests.maintenance import branch_coverage_audit as audit,branch_audit_completion as reader
    root=tmp_path/'native';root.mkdir();controlled_capture(root)
    inventory=audit.load(audit.ROOT/'docs/branch-coverage-inventory.json')
    descriptors=collector.write_branch_attachments(root,inventory,scope_kind='controlled')
    item=next(reader.read_sealed_artifact(d,tmp_path) for d in descriptors
        if '/@definition/' in reader.read_sealed_artifact(d,tmp_path)['branch_id'])
    branch=next(row for row in inventory['native_coverage']['obligations'] if row['id']==item['branch_id'])
    bindings,_,_=audit.portable_binding_inputs(audit.ROOT/'docs/branch-coverage-evidence-index.json',audit.load(audit.ROOT/'docs/branch-coverage-requirements.json'))
    binding=deepcopy(bindings['bindings'][branch['id']]);binding['category_inputs']={'live_metadata':deepcopy(item['category_inputs'])}
    edges={row['id']:row for row in inventory['native_coverage']['obligations'] if row['kind']=='reference'}
    desc=item['evidence'];record=reader.read_sealed_artifact(desc,tmp_path)
    def result(scope='controlled'):
        return reader.evidence_result(desc,branch,inventory['native_coverage']['candidate_sha256'],'live_metadata',scope,
            tmp_path,binding,source_root=audit.ROOT,reference_edges=edges)
    assert result()==('passed',None)
    if damage=='input':binding['category_inputs']['live_metadata']['native']=binding['input']['gateway_argv']
    elif damage=='source':record['source_context']['native_candidate']='0'*40
    elif damage=='reference':binding['reference_chain']=[branch['route']+'|/resultSchema/properties/audioEngineId/$ref']
    elif damage=='product-origin':record['scope_kind']='product'
    elif damage=='product-git':
        # Reseal an internally consistent ancestor pin; do not depend on a dirty
        # checkout or treat the controlled public Gateway fixture as native.
        ancestor='ae7e6e2981df0f2c9c8bc43fe3026f6d4962ff90'
        plan=json.loads((root/'plan.json').read_bytes())
        plan['repositories'][0]['commit']=ancestor
        plan['observation_origin']='native_scenario_lifecycle'  # Simulated admission input, zero native credit.
        (root/'plan.json').write_text(json.dumps(plan))
        seal=json.loads((root/'evidence-seal.json').read_bytes())
        entry=next(row for row in seal['files'] if row['path']=='plan.json')
        entry.update(sha256=hashlib.sha256((root/'plan.json').read_bytes()).hexdigest(),bytes=(root/'plan.json').stat().st_size)
        (root/'evidence-seal.json').write_text(json.dumps(seal))
        record['metadata_run']['seal']['sha256']=hashlib.sha256((root/'evidence-seal.json').read_bytes()).hexdigest()
        record['source_context']['native_candidate']=ancestor
        context=reader.read_metadata_run(record['metadata_run'],tmp_path)
        assert context['candidate']==ancestor and context['relevant_sources']==record['source_context']['relevant_sources']
        path=tmp_path/'ancestor-native-record.json';path.write_text(json.dumps(record))
        desc={**desc,'artifact':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        assert result()==('passed',None)  # Only product Git ownership remains unproved.
        record['scope_kind']='product'
    else:
        checks=record['branch_assertions'][branch['id']]['checks']
        pointer='/gateway/payload/agent_result' if damage=='whole-proof' else '/gateway/payload/agent_result/metadata/default'
        checks[:]=[check for check in checks if check['pointer']!=pointer]
    path=tmp_path/'changed-native-record.json';path.write_text(json.dumps(record))
    desc={**desc,'artifact':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    outcome,reason=result('product' if damage in {'product-git','product-origin'} else 'controlled')
    assert outcome=='missing'
    if damage=='product-git':assert 'committed metadata source closure unavailable' in reason
    if damage=='product-origin':assert 'Controlled metadata origin' in reason
