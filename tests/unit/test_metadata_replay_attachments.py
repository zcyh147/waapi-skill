"""Original-read/current-program attachment controls; no synthetic native PASS."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support import metadata_replay_branch_evidence as producer


@pytest.fixture(scope='module')
def original_root():
    retained = producer.portable_original_reads()
    if set(retained) == set(producer.CASES):
        return retained
    value = os.environ.get('WAAPI_R51_METADATA_ORIGINAL_ROOT')
    if not value:
        pytest.skip('Awaiting committed R51 portable originals; optional preparatory archive unavailable')
    return Path(value)


def original_read(root,field):
    return deepcopy(root[field]) if isinstance(root,dict) else producer.original_read(root,field)


def test_original_r51_metadata_adapter_preserves_blocked_business_and_exact_read(original_root):
    descriptor = original_read(original_root, 'ControlInput')
    context = completion.read_metadata_run(descriptor, audit.ROOT)
    assert context['host'] == 'wwise-console' and context['build'] == '2021.1.14.8108'
    assert context['business_category_status'] == 'blocked'
    assert context['gateway']['payload']['agent_result']['metadata']['default'] is None
    assert context['native_result']['default'] is None
    assert context['gateway']['argv'][0:2] == ['metadata', 'detail']


def write(path, value, **extra):
    path.write_text(json.dumps(value), encoding='utf-8')
    return {'artifact':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),**extra}



def test_r55_original_class_reader_preserves_exact_860_source_and_six_raw_contexts():
    originals=producer.r55_original_reads()
    assert len(originals)==6
    source=producer.r55_replay_case('2023.1|ModulatorTime|EnvelopeStopPlayback')
    context=source['context']
    assert context['candidate']=='860965d3368a92032061e5b3045c9a916d185b4b'
    assert context['cohort']=='r55' and len(context['relevant_sources'])==561
    assert context['native_result']['default'] is True
    assert source['packets']['ak.wwise.core.object.getPropertyAndReferenceNames']['result']['return']
    with pytest.raises(ValueError,match='source closure changed'):
        completion.read_metadata_run(originals['2023.1|ModulatorTime|EnvelopeStopPlayback'],audit.ROOT)


def test_r54_original_class_reader_retains_full_8a_native_source_and_origin():
    originals=producer.r54_original_reads()
    assert len(originals)==16
    descriptor=originals['2022.1|Wwise Delay|DelayTime']
    context=completion.read_metadata_run(descriptor,audit.ROOT,historical_class=True)
    assert context['candidate']=='8a8d5f8e006fd56dd5c78ebe6429ee24450abf26'
    assert len(context['relevant_sources'])==560
    assert context['native_result']['default']==0.5
    assert context['observation_origin']=='native_scenario_lifecycle'
    with pytest.raises(ValueError,match='source closure changed'):
        completion.read_metadata_run(descriptor,audit.ROOT)



def test_r54_original_index_anchor_rejects_self_consistently_rewritten_archive(tmp_path):
    import shutil
    originals=producer.r54_original_reads()
    case='2022.1|Wwise Delay|DelayTime'
    accepted=originals[case];original=Path(accepted['root']);altered=tmp_path/'altered-original'
    shutil.copytree(original,altered)
    index=audit.load(audit.ROOT/'docs/branch-coverage-evidence-index.json')
    base=(audit.ROOT/'docs'/index['base']).resolve();attachments=[]
    # Locator-only projection: every accepted seal hash stays unchanged.
    for number,desc in enumerate(index['metadata_attachments']):
        item=completion.read_sealed_artifact(desc,base)
        record=completion.read_sealed_artifact(item['evidence'],base)
        archive=record.get('metadata_run',{})
        if item['contract']=='waapi-skill.class-metadata-attachment/v1' and (base/archive['root']).resolve()==original:
            archive['root']=str(altered);archive['seal']['artifact']=str(altered/'evidence-seal.json')
            item['evidence']=write(tmp_path/f'record-{number}.json',record,**{k:v for k,v in item['evidence'].items() if k not in {'artifact','sha256'}})
            attachments.append(write(tmp_path/f'attachment-{number}.json',item))
        else:
            attachments.append(dict(desc,artifact=str(base/desc['artifact'])))
    index.update(base=str(base),metadata_attachments=attachments)
    path=tmp_path/'index.json';path.write_text(json.dumps(index))
    baseline=producer.r54_original_reads(path)
    assert len(baseline)==16
    assert completion.read_metadata_run(baseline[case],audit.ROOT,historical_class=True)['native_result']['default']==0.5
    targets=json.loads((altered/'targets.json').read_bytes());target=targets[0]
    native_path=altered/target['native_receipt'];native=json.loads(native_path.read_bytes())
    native['result']['default']=0.75;write(native_path,native)
    for suffix in ('.stdout','.agent-result.json'):
        receipt=altered/(target['detail_receipt']+suffix);value=json.loads(receipt.read_bytes())
        result=value['agent_result'] if suffix=='.stdout' else value
        result['metadata']['default']=0.75
        write(receipt,value)
    target.update(observed_default=0.75,native_sha256=hashlib.sha256(native_path.read_bytes()).hexdigest(),native_bytes=native_path.stat().st_size,
        detail_agent_result_sha256=hashlib.sha256((altered/(target['detail_receipt']+'.agent-result.json')).read_bytes()).hexdigest())
    write(altered/'targets.json',targets)
    seal=json.loads((altered/'evidence-seal.json').read_bytes())
    for entry in seal['files']:
        source=altered/entry['path'];entry.update(sha256=hashlib.sha256(source.read_bytes()).hexdigest(),bytes=source.stat().st_size)
    write(altered/'evidence-seal.json',seal)
    # The rewrite is internally valid; only the ORIGINAL index/record seal anchor rejects it.
    freshly_resealed=deepcopy(baseline[case]);freshly_resealed['seal']['sha256']=hashlib.sha256((altered/'evidence-seal.json').read_bytes()).hexdigest()
    assert completion.read_metadata_run(freshly_resealed,audit.ROOT,historical_class=True)['native_result']['default']==0.75
    with pytest.raises(ValueError,match='hash|digest|seal'):
        producer.r54_original_reads(path)


def r54_control(tmp_path,inventory,case='2022.1|Wwise Delay|DelayTime',*,cohort='r54'):
    from tests.unit.test_metadata_discovery_gateway import _run_original_r54_metadata_replay
    from tests.maintenance.collect_class_metadata import collection_plan
    observed={};_run_original_r54_metadata_replay(tmp_path,case,observed,cohort=cohort)
    original=producer.class_original_reads(cohort)[case]
    context=completion.read_metadata_run(original,audit.ROOT,historical_class=True)
    eligible=set(collection_plan(context['version'],cohort=cohort)['eligible_branch_ids'])
    from tests.support.metadata_read_branch_evidence import _witness
    edges={r['id']:r for r in inventory['native_coverage']['obligations'] if r['kind']=='reference'}
    branches=[r for r in inventory['native_coverage']['obligations'] if r['id'] in eligible
        and _witness(r,context['native_result'],edges) is not None]
    capture={'cohort':cohort,'scope_kind':'controlled','candidate_sha256':'c'*64,'git_candidate':'controlled_current_program',
        'relevant_sources':producer.r54_current_sources(),'historical_sources':context['relevant_sources'],
        'originals':{case:original},'branches':branches,'edges':edges,
        'case_branch_ids':{case:[r['id'] for r in branches]}}
    program,bindings=producer.make_r54_replay_receipt(capture,case,observed,dict.fromkeys(('setup','call','teardown'),'passed'))
    descriptor=write(tmp_path/'r54-program.json',program,nodeid=producer.class_original_profile(cohort)['node']+'['+case+']')
    record=producer.make_r54_attachment_record(capture,case,descriptor,program,bindings,base=audit.ROOT)
    attachment=write(tmp_path/'r54-attachment.json',record,nodeid=descriptor['nodeid'])
    branch=next(r for r in branches if r['pointer'].endswith('/anyOf/'+('1' if cohort=='r55' else '2')))
    binding={**bindings[branch['id']],'category_inputs':{'live_metadata':record['category_inputs']}}
    return capture,program,record,attachment,branch,binding


def test_original_r54_and_current_replay_keep_distinct_full_source_and_public_inputs(inventory,tmp_path):
    capture,program,record,descriptor,branch,binding=r54_control(tmp_path,inventory)
    assert record['source_bridge']['attribution']=='historical_native_current_program_not_current_native'
    assert len(record['source_bridge']['historical_sources'])==560
    assert completion.evidence_result(descriptor,branch,'c'*64,'live_metadata','controlled',tmp_path,binding,
        source_root=audit.ROOT,reference_edges=capture['edges'])==('passed',None)



def test_r55_original_and_current_replay_keep_distinct_sources_inputs_and_ten_leaf_scope(inventory,tmp_path):
    capture,program,record,descriptor,branch,binding=r54_control(tmp_path,inventory,
        '2021.1|MusicStinger|CustomCueMatchName',cohort='r55')
    assert record['source_bridge']['historical_candidate']==producer.R55_ORIGINAL
    assert record['source_bridge']['attribution']=='historical_native_current_program_not_current_native'
    assert len(record['source_bridge']['historical_sources'])==561
    assert completion.evidence_result(descriptor,branch,'c'*64,'live_metadata','controlled',tmp_path,binding,
        source_root=audit.ROOT,reference_edges=capture['edges'])==('passed',None)



@pytest.mark.parametrize('cohort',('r54','r55'))
@pytest.mark.parametrize('damage',('future-tone','future-contract','future-aux','future-helper',
    'unknown-aux','omitted-aux','false-helper-before','future-gateway','future-composer',
    'future-drafts','future-proof','future-fixture','omitted-fixture','false-fixture-before','partial-source-runtime'))
def test_class_bridge_requires_exact_accepted_runtime_and_auxiliary_blobs(inventory,tmp_path,monkeypatch,cohort,damage):
    case='2022.1|Wwise Delay|DelayTime' if cohort=='r54' else '2021.1|MusicStinger|CustomCueMatchName'
    capture,program,record,descriptor,branch,binding=r54_control(tmp_path,inventory,case,cohort=cohort)
    def result():
        return completion.evidence_result(descriptor,branch,'c'*64,'live_metadata','controlled',tmp_path,binding,
            source_root=audit.ROOT,reference_edges=capture['edges'])
    assert result()==('passed',None)
    bridge=record['source_bridge'];helper='tests/semantic/support/codex_source_copy_protocol.py'
    fixture='tests/destructive/support/source_copy_fixture.py'
    assert bridge['attribution']=='historical_native_current_program_not_current_native'
    assert len(bridge['historical_sources'])==(560 if cohort=='r54' else 561)
    assert len(bridge['current_sources'])==570
    assert helper not in bridge['historical_sources']
    assert bridge['changed_files'][helper]=={'before':None,
        'after':'b469b24ae64be096d314eb66da81b28833e0e45283d0cc66184199af2a089fdf'}
    assert fixture not in bridge['historical_sources']
    assert bridge['changed_files'][fixture]=={'before':None,
        'after':'f9c8ba22f8b69e01bd9e5cf2424699efad4bafce71b1d10a712caf2b3d80177d'}
    assert all(name not in bridge['current_sources'] for name in ('ci/program-test-nodes.txt',
        'tests/unit/test_ci_test_bat.py','tests/unit/test_class_metadata_product_attachments.py'))
    if damage=='omitted-aux':bridge['changed_files'].pop(helper)
    elif damage=='false-helper-before':bridge['changed_files'][helper]['before']='0'*64
    elif damage=='omitted-fixture':bridge['changed_files'].pop(fixture)
    elif damage=='false-fixture-before':bridge['changed_files'][fixture]['before']='0'*64
    else:
        relative={'future-tone':'skills/waapi-skill/wwise_waapi/operation_tone.py',
            'future-contract':'skills/waapi-skill/wwise_waapi/host_ui_debug_business_contracts.py',
            'future-aux':'tests/semantic/support/codex_gateway_broker.py',
            'future-helper':helper,'unknown-aux':'tests/semantic/support/codex_archive_paths.py',
            'future-gateway':'skills/waapi-skill/scripts/gateway.py',
            'future-composer':'skills/waapi-skill/wwise_waapi/operation_composer.py',
            'future-drafts':'skills/waapi-skill/wwise_waapi/operation_drafts.py',
            'future-proof':'skills/waapi-skill/wwise_waapi/source_copy_proof.py',
            'future-fixture':fixture,'partial-source-runtime':'skills/waapi-skill/scripts/gateway.py'}[damage]
        path=audit.ROOT/relative;read_bytes=Path.read_bytes
        if damage=='partial-source-runtime':
            import subprocess
            changed=subprocess.check_output(['git','show',producer.class_original_profile(cohort)['candidate']+':'+relative],cwd=audit.ROOT)
        else:changed=read_bytes(path)+b'\n# unreviewed future source\n'
        monkeypatch.setattr(Path,'read_bytes',lambda p:changed if p==path else read_bytes(p))
        current=producer.r54_current_sources();bridge['current_sources']=current
        bridge['changed_files']=producer.source_changes(bridge['historical_sources'],current)
        program['relevant_sources']=current
    record['replay']=write(tmp_path/'changed-class-program.json',program,nodeid=descriptor['nodeid'])
    descriptor=write(tmp_path/'changed-class-attachment.json',record,nodeid=descriptor['nodeid'])
    outcome,reason=result()
    assert outcome=='missing' and 'unreviewed runtime drift' in reason


def test_r54_assigns_only_observed_versioned_leaves_to_sixteen_original_scenarios(inventory):
    from tests.maintenance.collect_class_metadata import collection_plan
    originals=producer.r54_original_reads()
    contexts={case:completion.read_metadata_run(desc,audit.ROOT,historical_class=True) for case,desc in originals.items()}
    selected=set().union(*(set(collection_plan(v)['eligible_branch_ids']) for v in ('2021.1','2022.1','2023.1','2024.1','2025.1')))
    rows=[r for r in inventory['native_coverage']['obligations'] if r['id'] in selected]
    edges={r['id']:r for r in inventory['native_coverage']['obligations'] if r['kind']=='reference'}
    owners=producer.r54_case_assignments(rows,edges,contexts)
    assert len(owners)==16 and sum(map(len,owners.values()))==41
    assert {i for ids in owners.values() for i in ids}==selected
    unobserved=next(r for r in inventory['native_coverage']['obligations'] if r['id'] in collection_plan('2022.1',cohort='r55')['eligible_branch_ids'])
    with pytest.raises(ValueError,match='do not witness'):
        producer.r54_case_assignments(rows+[unobserved],edges,contexts)


@pytest.mark.parametrize('damage',['native-git','native-source','native-origin','native-field','raw-result','raw-input',
    'current-source','changed-file-proof','runtime-drift','runtime-new-file-drift','partial-runtime-bridge','current-field','leaf','whole','reference','category-input',
    'attribution','product-git','teardown'])
def test_r54_historical_replay_controls_start_from_valid_original_and_current_flow(inventory,tmp_path,monkeypatch,damage):
    capture,program,record,descriptor,branch,binding=r54_control(tmp_path,inventory)
    def result(scope='controlled'):
        return completion.evidence_result(descriptor,branch,'c'*64,'live_metadata',scope,tmp_path,binding,
            source_root=audit.ROOT,reference_edges=capture['edges'])
    assert result()==('passed',None)
    if damage in {'native-git','native-source','native-origin','native-field'}:
        import shutil
        original=Path(record['metadata_run']['root']);dest=tmp_path/'altered-original';shutil.copytree(original,dest)
        record['metadata_run']['root']=str(dest)
        record['metadata_run']['seal']['artifact']=str(dest/'evidence-seal.json')
        plan=json.loads((dest/'plan.json').read_bytes())
        if damage=='native-git':plan['repositories'][0]['commit']='ae7e6e2981df0f2c9c8bc43fe3026f6d4962ff90'
        elif damage=='native-source':plan['source_seals']=plan['source_seals'][1:]
        elif damage=='native-origin':plan['observation_origin']='controlled_public_gateway'
        else:record['metadata_run']['target_index']=1
        (dest/'plan.json').write_text(json.dumps(plan))
        seal=json.loads((dest/'evidence-seal.json').read_bytes());entry=next(e for e in seal['files'] if e['path']=='plan.json')
        entry.update(sha256=hashlib.sha256((dest/'plan.json').read_bytes()).hexdigest(),bytes=(dest/'plan.json').stat().st_size)
        (dest/'evidence-seal.json').write_text(json.dumps(seal))
        record['metadata_run']['seal']['sha256']=hashlib.sha256((dest/'evidence-seal.json').read_bytes()).hexdigest()
    elif damage=='raw-result':program['native_call']['result']['default']=0.75
    elif damage=='raw-input':program['replayed_original_packets_sha256']['ak.wwise.core.object.getTypes']='0'*64
    elif damage=='current-source':record['source_bridge']['current_sources'].pop('tests/unit/test_metadata_default_branch_evidence.py')
    elif damage=='changed-file-proof':
        assert 'tests/unit/test_metadata_default_branch_evidence.py' in record['source_bridge']['changed_files']
        record['source_bridge']['changed_files'].pop('tests/unit/test_metadata_default_branch_evidence.py')
    elif damage in {'runtime-drift','runtime-new-file-drift','partial-runtime-bridge'}:
        import subprocess
        before=Path.read_bytes
        relative=('skills/waapi-skill/wwise_waapi/source_copy_proof.py' if damage=='runtime-new-file-drift'
            else 'skills/waapi-skill/scripts/gateway.py')
        path=audit.ROOT/relative
        if damage=='runtime-new-file-drift':assert relative not in record['source_bridge']['historical_sources']
        changed=(subprocess.check_output(['git','show',producer.R54_ORIGINAL+':'+relative],cwd=audit.ROOT)
            if damage=='partial-runtime-bridge' else before(path)+b'\n# unreviewed change\n')
        monkeypatch.setattr(Path,'read_bytes',lambda p:changed if p==path else before(p))
        current=producer.r54_current_sources();record['source_bridge']['current_sources']=current
        record['source_bridge']['changed_files']=producer.source_changes(record['source_bridge']['historical_sources'],current)
        program['relevant_sources']=current
    elif damage=='current-field':program['native_call']['args']['property']='FeedbackEnabled'
    elif damage=='leaf':
        checks=program['branch_assertions'][branch['id']]['checks'];checks[:]=[c for c in checks if c['pointer']!='/native_call/result/default']
    elif damage=='whole':
        checks=record['branch_assertions'][branch['id']]['checks'];checks[:]=[c for c in checks if c['pointer']!='/gateway/payload/agent_result']
    elif damage=='reference':binding['reference_chain']=[branch['route']+'|/resultSchema/properties/audioEngineId/$ref']
    elif damage=='category-input':
        record['category_inputs']['replay']=record['category_inputs']['historical']
        binding['category_inputs']['live_metadata']=record['category_inputs']
    elif damage=='attribution':record['source_bridge']['attribution']='current_native'
    elif damage=='product-git':
        # This committed source contains the newly added module too: rejection
        # must prove different source bytes, not merely a missing historical file.
        wrong='411e8173949020bad26e4302f1e9428a21bcac7d'
        assert producer.git_source_seals(wrong,program['relevant_sources'])!=program['relevant_sources']
        record['scope_kind']=program['scope_kind']='product';program['git_candidate']=wrong
    elif damage=='teardown':
        program['invocation']['outcome']='FAIL';program['invocation']['node_outcomes'][0]['outcome']='FAIL'
        record['invocation']=deepcopy(program['invocation'])
    record['replay']=write(tmp_path/'altered-r54-program.json',program,nodeid=descriptor['nodeid'])
    descriptor=write(tmp_path/'altered-r54-attachment.json',record,nodeid=descriptor['nodeid'])
    outcome,reason=result('product' if damage=='product-git' else 'controlled')
    assert outcome=='missing',reason
    if damage in {'runtime-drift','runtime-new-file-drift','partial-runtime-bridge'}:assert 'unreviewed runtime drift' in reason
    if damage=='product-git':assert 'Git/source ownership' in reason


@pytest.mark.parametrize('damage', ('reply-bytes','status-host','identity-class','business-promotion',
    'unfinished-node','source-drift','residual-process','wrong-occurrence','native-public-mismatch',
    'category-transaction','identity-endpoint','reply-session-endpoint'))
def test_original_archive_controls_start_from_valid_historical_receipt(original_root,tmp_path,damage):
    descriptor = original_read(original_root,'ControlInput')
    assert completion.read_metadata_run(descriptor,audit.ROOT)['native_result']['default'] is None
    rows = [json.loads(line) for line in Path(descriptor['category']['artifact']).read_bytes().splitlines()]
    category = rows[descriptor['category']['record_index']]
    body = completion.read_sealed_artifact(descriptor['observation'],audit.ROOT)
    if damage == 'reply-bytes':
        path = tmp_path/'corrupted-reply.json';path.write_text('{}')
        descriptor['reply']['artifact'] = str(path)
        with pytest.raises(ValueError,match='artifact digest mismatch'):
            completion.read_metadata_run(descriptor,tmp_path)
        return
    if damage in ('status-host','identity-class','native-public-mismatch','identity-endpoint','reply-session-endpoint'):
        role = {'status-host':'status','identity-class':'identity','native-public-mismatch':'native',
            'identity-endpoint':'identity','reply-session-endpoint':'reply'}[damage]
        value = completion.read_sealed_artifact(descriptor[role],audit.ROOT)
        if damage == 'status-host':value['wwise']['isCommandLine'] = False
        elif damage == 'identity-class':value['agent_result'][0]['class_id'] = 1441792
        elif damage == 'native-public-mismatch':value['result']['default'] = 0
        elif damage == 'identity-endpoint':value['endpoint']['port'] += 1
        else:value['session_context']['endpoint']['port'] += 1
        descriptor[role] = write(tmp_path/(role+'.json'),value)
        if role == 'native':
            link = next(row for row in body['native_evidence'] if row['sha256'] == original_read(original_root,'ControlInput')['native']['sha256'])
        else:link = body['calls'][{'status':0,'identity':3,'reply':descriptor['call_index']}[role]]['reply']
        link['sha256'] = descriptor[role]['sha256']
    elif damage == 'business-promotion':category['categories'][0]['status'] = 'PASS'
    elif damage == 'unfinished-node':category['invocation']['phase'] = 'call'
    elif damage == 'source-drift':category['source']['hash_after'] = '0'*64
    elif damage == 'residual-process':category['residual_state']['residual_processes'] = [12345]
    elif damage == 'category-transaction':category['transactions'] = ['unexpected-transaction']
    else:descriptor['call_index'] += 1
    descriptor['observation'] = write(tmp_path/'observation.json',body)
    original = next(row for row in category['categories'] if row['category'] == 'legacy-original-source-owned-read')
    original['observation_sha256'] = descriptor['observation']['sha256']
    path = tmp_path/'category.jsonl';path.write_text(''.join(json.dumps(row)+'\n' for row in rows))
    descriptor['category'] = {'artifact':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'record_index':descriptor['category']['record_index'],'nodeid':descriptor['category']['nodeid']}
    with pytest.raises(ValueError):completion.read_metadata_run(descriptor,tmp_path)


@pytest.fixture(scope='module')
def inventory():
    return audit.load(audit.ROOT/'docs/branch-coverage-inventory.json')


def controlled_attachment(tmp_path, original_root, inventory, field):
    from tests.unit.test_metadata_discovery_gateway import _run_original_r51_metadata_replay
    observed = {}
    expected = {'Color':0,'ControlInput':None,'OverrideColor':False}[field]
    _run_original_r51_metadata_replay(tmp_path,field,expected,observed)
    rows = producer.selected_branches(inventory)
    capture = {'scope_kind':'controlled','candidate_sha256':'c'*64,'git_candidate':'controlled_current_program',
        'relevant_sources':producer.source_seals(),'historical_sources':producer.historical_sources(),
        'branches':rows,'edges':{r['id']:r for r in inventory['native_coverage']['obligations']if r['kind']=='reference'},
        'originals':{field:original_read(original_root,field)}}
    replay, bindings = producer.make_replay_receipt(capture,field,observed,dict.fromkeys(('setup','call','teardown'),'passed'))
    descriptor = write(tmp_path/'current-program.json',replay,nodeid=producer.NODE+'['+producer.CASES[field]+']')
    record = producer.make_attachment_record(capture,field,descriptor,replay,bindings,base=tmp_path)
    attachment = write(tmp_path/'attachment.json',record,nodeid=descriptor['nodeid'])
    return capture, replay, record, bindings, attachment


@pytest.mark.parametrize('field',producer.CASES)
def test_original_metadata_and_current_replay_have_separate_exact_inputs(original_root, inventory, tmp_path, field):
    assert not any(name.startswith('tests/semantic/') for name in producer.source_seals())
    assert not any(name.startswith('tests/semantic/') for name in producer.historical_sources())
    capture,replay,record,replay_bindings,descriptor = controlled_attachment(tmp_path,original_root,inventory,field)
    assert record['category_inputs']['historical'] != record['category_inputs']['replay']
    for branch in capture['branches']:
        if branch['id'] not in replay_bindings:
            continue
        binding = {**replay_bindings[branch['id']], 'category_inputs':{'live_metadata':record['category_inputs']}}
        assert completion.evidence_result(descriptor,branch,'c'*64,'live_metadata','controlled',tmp_path,binding,
            source_root=audit.ROOT,reference_edges=capture['edges']) == ('passed',None)


def portable_control(tmp_path, original_root, inventory):
    """Copy one small real program bundle; no full fixture-tree clones or product credit."""
    import shutil
    capture,replay,record,bindings,descriptor = controlled_attachment(tmp_path,original_root,inventory,'ControlInput')
    branch = next(row for row in capture['branches'] if row['id'] in bindings)
    index = audit.load(audit.ROOT/'docs/branch-coverage-evidence-index.json')
    source_base = (audit.ROOT/'docs'/index['base']).resolve()
    entry = next(e for e in index['entries'] if branch['id'] in json.loads((source_base/e['bindings']['artifact']).read_bytes())['bindings'])
    base = tmp_path/'bundle';base.mkdir()
    for desc in [entry['bindings'],*entry['origin'].values()]:
        path = base/desc['artifact'];path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source_base/desc['artifact'],path)
    for role in ('category','observation','status','identity','reply','native'):
        desc = record['metadata_run'][role]
        target = base/(role+'.original.json');shutil.copyfile(desc['artifact'],target)
        desc['artifact'] = target.name
    shutil.copyfile(record['replay']['artifact'],base/'replay.controlled.json')
    record['replay']['artifact'] = 'replay.controlled.json'
    proof = write(base/'metadata.controlled.json',record,nodeid=descriptor['nodeid'])
    proof['artifact'] = Path(proof['artifact']).name
    attached = {'contract':'waapi-skill.r51-metadata-attachment/v1','branch_id':branch['id'],
        'native_shape_sha256':branch['shape_sha256'],'category_inputs':record['category_inputs'],'evidence':proof}
    attachment = write(base/'attachment.controlled.json',attached);attachment['artifact']=Path(attachment['artifact']).name
    document = {'contract':index['contract'],'base':'bundle','entries':[entry],'metadata_attachments':[attachment]}
    path = tmp_path/'index.json';path.write_text(json.dumps(document))
    return path,document,base,attached,branch


def portable_r54_control(tmp_path,inventory,*,cohort='r54'):
    import shutil
    case='2021.1|MusicStinger|CustomCueMatchName' if cohort=='r55' else '2022.1|Wwise Delay|DelayTime'
    capture,program,record,descriptor,branch,binding=r54_control(tmp_path,inventory,case,cohort=cohort)
    index=audit.load(audit.ROOT/'docs/branch-coverage-evidence-index.json');source=(audit.ROOT/'docs'/index['base']).resolve()
    entry=next(e for e in index['entries'] if branch['id'] in json.loads((source/e['bindings']['artifact']).read_bytes())['bindings'])
    base=tmp_path/'bundle';base.mkdir()
    for desc in [entry['bindings'],*entry['origin'].values()]:
        target=base/desc['artifact'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/desc['artifact'],target)
    archive=record['metadata_run'];original=Path(archive['root']);shutil.copytree(original,base/original.name)
    archive['root']=original.name;archive['seal']['artifact']=original.name+'/evidence-seal.json'
    shutil.copyfile(record['replay']['artifact'],base/'replay.json');record['replay']['artifact']='replay.json'
    proof=write(base/'metadata.json',record,nodeid=descriptor['nodeid']);proof['artifact']='metadata.json'
    item={'contract':'waapi-skill.class-metadata-attachment/v1','branch_id':branch['id'],
        'native_shape_sha256':branch['shape_sha256'],'category_inputs':record['category_inputs'],'evidence':proof}
    attached=write(base/'attachment.json',item);attached['artifact']='attachment.json'
    document={'contract':index['contract'],'base':'bundle','entries':[entry],'metadata_attachments':[attached]}
    path=tmp_path/'index.json';path.write_text(json.dumps(document));return path,document,base,item,branch



@pytest.mark.parametrize('damage',['native-pin','cohort','class','field','leaf','raw-result','raw-bytes',
    'seal','original-source','current-source','future-harness','reference','whole-result'])
def test_r55_historical_reuse_rejects_damaged_identity_or_public_leaf_from_valid_baseline(inventory,tmp_path,monkeypatch,damage):
    capture,program,record,descriptor,branch,binding=r54_control(tmp_path,inventory,
        '2021.1|MusicStinger|CustomCueMatchName',cohort='r55')
    def result():
        return completion.evidence_result(descriptor,branch,'c'*64,'live_metadata','controlled',tmp_path,binding,
            source_root=audit.ROOT,reference_edges=capture['edges'])
    assert result()==('passed',None)
    if damage=='native-pin':record['source_bridge']['historical_candidate']=producer.R54_ORIGINAL
    elif damage=='cohort':record['source_bridge']['contract']='waapi-skill.r54-class-metadata-leaf-replay/v1'
    elif damage=='class':program['native_call']['args']['classId']=5111824
    elif damage=='field':program['native_call']['args']['property']='EnvelopeStopPlayback'
    elif damage=='leaf':
        checks=program['branch_assertions'][branch['id']]['checks'];checks[:]=[c for c in checks if c['pointer']!='/native_call/result/default']
    elif damage=='raw-result':program['native_call']['result']['default']='changed'
    elif damage in {'raw-bytes','seal'}:
        import shutil
        archive=record['metadata_run'];source=Path(archive['root']);changed=tmp_path/'changed-original';shutil.copytree(source,changed)
        archive['root']=str(changed);archive['seal']['artifact']=str(changed/'evidence-seal.json')
        targets=json.loads((changed/'targets.json').read_bytes());packet=changed/targets[0]['native_receipt']
        if damage=='raw-bytes':
            native=json.loads(packet.read_bytes());native['result']['default']='changed';write(packet,native)
        else:
            # All inner files/proofs remain valid. A different serialization of
            # the outer seal cannot replace the independently accepted receipt.
            seal=json.loads((changed/'evidence-seal.json').read_bytes());write(changed/'evidence-seal.json',seal)
            archive['seal']['sha256']=hashlib.sha256((changed/'evidence-seal.json').read_bytes()).hexdigest()
            assert archive['seal']['sha256']!=producer.R55_ORIGINAL_SEALS['2021.1']
    elif damage=='original-source':record['source_bridge']['historical_sources'].pop('tests/semantic/support/codex_gateway_broker.py')
    elif damage=='current-source':record['source_bridge']['current_sources'].pop('tests/unit/test_metadata_default_branch_evidence.py')
    elif damage=='future-harness':
        path=audit.ROOT/'tests/semantic/support/codex_gateway_broker.py';before=Path.read_bytes
        monkeypatch.setattr(Path,'read_bytes',lambda p:before(p)+b'\n# unknown future harness\n' if p==path else before(p))
        current=producer.r54_current_sources();record['source_bridge']['current_sources']=current
        record['source_bridge']['changed_files']=producer.source_changes(record['source_bridge']['historical_sources'],current);program['relevant_sources']=current
    elif damage=='reference':binding['reference_chain']=[branch['route']+'|/resultSchema/properties/audioEngineId/$ref']
    else:
        checks=record['branch_assertions'][branch['id']]['checks'];checks[:]=[c for c in checks if c['pointer']!='/gateway/payload/agent_result']
    record['replay']=write(tmp_path/'changed-r55-program.json',program,nodeid=descriptor['nodeid'])
    descriptor=write(tmp_path/'changed-r55-attachment.json',record,nodeid=descriptor['nodeid'])
    outcome,reason=result();assert outcome=='missing',reason
    if damage=='future-harness':assert 'unreviewed runtime drift' in reason
    if damage=='seal':assert 'Original accepted R55 seal anchor changed' in reason



def test_r55_assigns_exact_ten_observed_leaves_to_six_original_scenarios(inventory):
    from tests.maintenance.collect_class_metadata import collection_plan
    contexts={case:completion.read_metadata_run(desc,audit.ROOT,historical_class=True)
        for case,desc in producer.r55_original_reads().items()}
    selected=set().union(*(set(collection_plan(v,cohort='r55')['eligible_branch_ids']) for v in ('2021.1','2022.1','2023.1','2024.1')))
    rows=[r for r in inventory['native_coverage']['obligations'] if r['id'] in selected]
    edges={r['id']:r for r in inventory['native_coverage']['obligations'] if r['kind']=='reference'}
    owners=producer.r54_case_assignments(rows,edges,contexts)
    assert len(owners)==6 and sum(map(len,owners.values()))==10
    assert set().union(*map(set,owners.values()))==selected
    false=next(r for r in inventory['native_coverage']['obligations'] if r['route'].split('|')[0]=='2023.1'
        and r['route'].endswith('|ak.wwise.core.object.getPropertyInfo') and r['pointer'].endswith('/propertyValue/anyOf/3/@boolean/false'))
    with pytest.raises(ValueError,match='do not witness'):producer.r54_case_assignments(rows+[false],edges,contexts)


def test_r55_portable_historical_attachment_keeps_program_and_ignores_unavailable_original_paths(inventory,tmp_path,monkeypatch):
    path,index,base,item,branch=portable_r54_control(tmp_path,inventory,cohort='r55')
    policy=audit.load(audit.ROOT/'docs/branch-coverage-requirements.json')
    old=json.loads((base/index['entries'][0]['bindings']['artifact']).read_bytes())['bindings'][branch['id']]
    original_roots={Path(d['root']) for d in producer.r55_original_reads().values()};read_bytes=Path.read_bytes
    def local_only(p):
        if any(p.is_relative_to(root) for root in original_roots):raise AssertionError('Portable read followed original absolute archive')
        return read_bytes(p)
    monkeypatch.delenv('WAAPI_R55_CLASS_METADATA_ORIGINALS',raising=False);monkeypatch.setattr(Path,'read_bytes',local_only)
    inputs,_,_=audit.portable_binding_inputs(path,policy);binding=inputs['bindings'][branch['id']]
    assert binding['input']==old['input'] and binding['evidence']['program']==old['evidence']['program']
    edges={r['id']:r for r in inventory['native_coverage']['obligations'] if r['kind']=='reference'}
    assert completion.evidence_result(item['evidence'],branch,'c'*64,'live_metadata','controlled',base,binding,
        source_root=audit.ROOT,reference_edges=edges)==('passed',None)
    (base/'replay.json').write_text('{}')
    with pytest.raises(ValueError):audit.portable_binding_inputs(path,policy)


@pytest.mark.parametrize('damage',[None,'duplicate','extra','archive-bytes','replay-bytes','dependency-escape'])
def test_r54_historical_portable_transport_preserves_program_and_checks_original_dependencies(inventory,tmp_path,damage):
    path,index,base,item,branch=portable_r54_control(tmp_path,inventory)
    policy=audit.load(audit.ROOT/'docs/branch-coverage-requirements.json')
    original=json.loads((base/index['entries'][0]['bindings']['artifact']).read_bytes())['bindings'][branch['id']]
    actual,_,_=audit.portable_binding_inputs(path,policy)
    assert actual['bindings'][branch['id']]['input']==original['input']
    assert actual['bindings'][branch['id']]['evidence']['program']==original['evidence']['program']
    assert actual['bindings'][branch['id']]['evidence']['live_metadata']==item['evidence']
    if damage is None:
        edges={r['id']:r for r in inventory['native_coverage']['obligations'] if r['kind']=='reference'}
        assert completion.evidence_result(item['evidence'],branch,'c'*64,'live_metadata','controlled',base,
            actual['bindings'][branch['id']],source_root=audit.ROOT,reference_edges=edges)==('passed',None)
        return
    record=json.loads((base/'metadata.json').read_bytes())
    if damage=='duplicate':index['metadata_attachments'].append(deepcopy(index['metadata_attachments'][0]))
    elif damage=='archive-bytes':(base/record['metadata_run']['root']/'targets.json').write_text('[]')
    elif damage=='replay-bytes':(base/'replay.json').write_text('{}')
    else:
        if damage=='extra':record['source_bridge']['arbitrary_equivalence']=True
        else:record['metadata_run']['root']='../escape'
        proof=write(base/'metadata.json',record,nodeid=item['evidence']['nodeid']);proof['artifact']='metadata.json';item['evidence']=proof
        attached=write(base/'attachment.json',item);attached['artifact']='attachment.json';index['metadata_attachments']=[attached]
    path.write_text(json.dumps(index))
    with pytest.raises(ValueError):audit.portable_binding_inputs(path,policy)


def test_portable_metadata_attachment_is_additive_and_keeps_original_program(original_root,inventory,tmp_path):
    path,document,base,attached,branch = portable_control(tmp_path,original_root,inventory)
    policy = audit.load(audit.ROOT/'docs/branch-coverage-requirements.json')
    original = json.loads((base/document['entries'][0]['bindings']['artifact']).read_bytes())['bindings'][branch['id']]
    actual,_,_ = audit.portable_binding_inputs(path,policy)
    binding = actual['bindings'][branch['id']]
    assert binding['evidence']['program'] == original['evidence']['program']
    assert binding['input'] == original['input']
    assert binding['evidence']['live_metadata'] == attached['evidence']
    assert binding['category_inputs']['live_metadata'] == attached['category_inputs']


def test_portable_originals_resolve_without_environment_or_original_absolute_paths(original_root,inventory,tmp_path,monkeypatch):
    path,index,base,attachment,branch = portable_control(tmp_path,original_root,inventory)
    assert producer.portable_original_reads(path)['ControlInput']
    archived = json.loads((base/'observation.original.json').read_bytes())
    forbidden = {Path(row['reply']['path']) for row in archived['calls']}
    forbidden.update(Path(row['path']) for row in archived['native_evidence'])
    forbidden.update(Path(row['native_path']) for row in archived['native_evidence'])
    category = completion.read_sealed_artifact({**json.loads((base/attachment['evidence']['artifact']).read_bytes())['metadata_run']['category'],
        'artifact':str(base/'category.original.json')},base)
    forbidden.update(Path(row['observation_path']) for row in category['categories'] if 'observation_path' in row)
    monkeypatch.delenv('WAAPI_R51_METADATA_ORIGINAL_ROOT',raising=False)
    read_bytes = Path.read_bytes
    def portable_only(target):
        if target in forbidden:raise FileNotFoundError('Original host absolute paths unavailable')
        return read_bytes(target)
    monkeypatch.setattr(Path,'read_bytes',portable_only)
    retained = producer.portable_original_reads(path)
    result = completion.read_metadata_run(retained['ControlInput'],tmp_path)
    assert result['native_result']['default'] is None
    assert result['business_category_status'] == 'blocked'
    replay_root = tmp_path/'portable-replay';replay_root.mkdir()
    capture,replay,record,bindings,descriptor = controlled_attachment(replay_root,retained,inventory,'ControlInput')
    branch = next(row for row in capture['branches'] if row['id'] in bindings)
    binding = {**bindings[branch['id']],'category_inputs':{'live_metadata':record['category_inputs']}}
    assert completion.evidence_result(descriptor,branch,'c'*64,'live_metadata','controlled',replay_root,binding,
        source_root=audit.ROOT,reference_edges=capture['edges']) == ('passed',None)


@pytest.mark.parametrize('damage', ('wrong-input','wrong-replay-input','wrong-source','missing-source','missing-change-proof',
    'current-native-claim','wrong-field','wrong-scope','wrong-public-host','changed-native-result','missing-leaf-proof','missing-whole-proof',
    'failed-teardown','wrong-ref','unobserved-true','missing-parent','null-parent','native-credit','controlled-product-credit'))
def test_metadata_attachment_corruption_starts_from_original_and_replay_baseline(original_root,inventory,tmp_path,damage):
    capture,replay,record,bindings,descriptor = controlled_attachment(tmp_path,original_root,inventory,'ControlInput')
    branch = next(row for row in capture['branches'] if row['id'] in bindings)
    binding = {**bindings[branch['id']], 'category_inputs':{'live_metadata':deepcopy(record['category_inputs'])}}
    def result(category='live_metadata',scope='controlled'):
        return completion.evidence_result(descriptor,branch,'c'*64,category,scope,tmp_path,binding,
            source_root=audit.ROOT,reference_edges=capture['edges'])
    assert result() == ('passed',None)
    if damage == 'wrong-input':
        binding['category_inputs']['live_metadata']['historical'] = replay['gateway']['argv']
    elif damage == 'wrong-replay-input':
        binding['category_inputs']['live_metadata']['replay'] = record['category_inputs']['historical']
    elif damage == 'wrong-source':
        record['source_bridge']['historical_sources']['skills/waapi-skill/scripts/gateway.py'] = '0'*64
    elif damage == 'missing-source':
        del record['source_bridge']['current_sources']['skills/waapi-skill/scripts/gateway.py']
    elif damage == 'missing-change-proof':
        record['source_bridge']['changed_files'] = {}
    elif damage == 'current-native-claim':
        record['source_bridge']['attribution'] = 'current_native'
    elif damage == 'wrong-field':
        replay['native_call']['args']['property'] = 'Color'
    elif damage == 'wrong-scope':
        replay['gateway']['payload']['agent_result']['scope']['object'] = '{11111111-1111-1111-1111-111111111111}'
    elif damage == 'wrong-public-host':
        replay['gateway']['payload']['is_command_line'] = False
    elif damage == 'changed-native-result':
        replay['native_call']['result']['default'] = 0
    elif damage in ('missing-leaf-proof','missing-whole-proof'):
        checks = replay['branch_assertions'][branch['id']]['checks']
        pointer = '/gateway/payload/agent_result' if damage == 'missing-whole-proof' else '/gateway/payload/agent_result/metadata/default'
        checks[:] = [check for check in checks if check['pointer'] != pointer]
    elif damage == 'failed-teardown':
        replay['invocation']['outcome'] = record['invocation']['outcome'] = 'FAIL'
    elif damage == 'wrong-ref':
        binding['reference_chain'] = [branch['route']+'|/resultSchema/properties/audioEngineId/$ref']
    elif damage == 'unobserved-true':
        old_id = branch['id']
        branch = next(row for row in inventory['native_coverage']['obligations'] if row['route'] == branch['route']
            and row['pointer'].endswith('/propertyValue/anyOf/3/@boolean/true'))
        for receipt in (record,replay):
            assertion = receipt['branch_assertions'].pop(old_id)
            assertion['native_shape_sha256'] = branch['shape_sha256']
            receipt['branch_assertions'][branch['id']] = assertion
    elif damage == 'missing-parent':
        del replay['gateway']['payload']['agent_result']['metadata']
    elif damage == 'null-parent':
        replay['gateway']['payload']['agent_result']['metadata'] = None
    elif damage == 'native-credit':
        assert result(category='native')[0] == 'missing'
        return
    else:
        assert result(scope='product')[0] == 'missing'
        return
    # Re-sign exact current values, ensuring scope/field/bridge controls cannot
    # pass by failing only an unrelated obsolete equals assertion or file seal.
    for assertion in replay['branch_assertions'].values():
        for check in assertion['checks']:
            if 'equals' in check:
                try:check['equals'] = deepcopy(completion.pointer_value(replay,check['pointer']))
                except (KeyError,TypeError):pass
    record['replay'] = write(tmp_path/'changed-program.json',replay,nodeid=descriptor['nodeid'])
    descriptor = write(tmp_path/'changed-attachment.json',record,nodeid=descriptor['nodeid'])
    assert result()[0] == 'missing',damage


def test_metadata_replay_rejects_numeric_zero_borrowing_original_false(original_root,inventory,tmp_path):
    capture,replay,record,bindings,descriptor = controlled_attachment(tmp_path,original_root,inventory,'OverrideColor')
    branch = next(row for row in capture['branches'] if row['id'] in bindings)
    binding = {**bindings[branch['id']],'category_inputs':{'live_metadata':record['category_inputs']}}
    def result():
        return completion.evidence_result(descriptor,branch,'c'*64,'live_metadata','controlled',tmp_path,binding,
            source_root=audit.ROOT,reference_edges=capture['edges'])
    assert result() == ('passed',None)
    replay['native_call']['result']['default'] = replay['gateway']['payload']['agent_result']['metadata']['default'] = 0
    for assertion in replay['branch_assertions'].values():
        for check in assertion['checks']:check['equals'] = deepcopy(completion.pointer_value(replay,check['pointer']))
    record['replay'] = write(tmp_path/'numeric-program.json',replay,nodeid=descriptor['nodeid'])
    descriptor = write(tmp_path/'numeric-attachment.json',record,nodeid=descriptor['nodeid'])
    outcome,reason = result()
    assert outcome == 'missing' and 'exact original class/field/native response' in reason


def test_metadata_bridge_rejects_new_runtime_drift_even_with_full_changed_file_proof(original_root,inventory,tmp_path,monkeypatch):
    capture,replay,record,bindings,descriptor = controlled_attachment(tmp_path,original_root,inventory,'ControlInput')
    branch = next(row for row in capture['branches'] if row['id'] in bindings)
    binding = {**bindings[branch['id']],'category_inputs':{'live_metadata':record['category_inputs']}}
    def result():
        return completion.evidence_result(descriptor,branch,'c'*64,'live_metadata','controlled',tmp_path,binding,
            source_root=audit.ROOT,reference_edges=capture['edges'])
    assert result() == ('passed',None)
    original_read_bytes = Path.read_bytes
    gateway_path = audit.ROOT/'skills/waapi-skill/scripts/gateway.py'
    def changed_source(path):
        raw = original_read_bytes(path)
        return raw+b'\n# unreviewed runtime change\n' if path == gateway_path else raw
    monkeypatch.setattr(Path,'read_bytes',changed_source)
    current = producer.source_seals()
    record['source_bridge']['current_sources'] = current
    record['source_bridge']['changed_files'] = producer.source_changes(record['source_bridge']['historical_sources'],current)
    replay['relevant_sources'] = current
    record['replay'] = write(tmp_path/'drifted-program.json',replay,nodeid=descriptor['nodeid'])
    descriptor = write(tmp_path/'drifted-attachment.json',record,nodeid=descriptor['nodeid'])
    outcome,reason = result()
    assert outcome == 'missing' and 'runtime drift is not equivalent' in reason


@pytest.mark.parametrize('damage',[None,'operation_tone.py','host_ui_debug_business_contracts.py','host_ui_debug_business.py','gateway.py','object_lifecycle_graph.py','operation_registry.py','source_copy_observations.py','core_business.py','core_business_contracts.py','operation_composer.py','operation_drafts.py','transaction_runtime.py','source_copy_proof.py','partial-bridge'])
def test_metadata_bridge_accepts_only_exact_reviewed_tone_blobs(original_root,inventory,tmp_path,monkeypatch,damage):
    import subprocess
    capture,replay,record,bindings,descriptor = controlled_attachment(tmp_path,original_root,inventory,'ControlInput')
    branch = next(row for row in capture['branches'] if row['id'] in bindings)
    binding = {**bindings[branch['id']],'category_inputs':{'live_metadata':record['category_inputs']}}
    def result():
        return completion.evidence_result(descriptor,branch,'c'*64,'live_metadata','controlled',tmp_path,binding,
            source_root=audit.ROOT,reference_edges=capture['edges'])
    assert result() == ('passed',None)
    source_pin = '796f16ca0794d45e4deed6f9ec92039f32f69b20'
    packets = {}
    for name in ('operation_tone.py','host_ui_debug_business_contracts.py','host_ui_debug_business.py','gateway.py',
                 'object_lifecycle_graph.py','operation_registry.py','source_copy_observations.py','core_business.py','core_business_contracts.py',
                 'operation_composer.py','operation_drafts.py','transaction_runtime.py','source_copy_proof.py'):
        relative = ('skills/waapi-skill/scripts/' if name == 'gateway.py' else 'skills/waapi-skill/wwise_waapi/')+name
        raw = subprocess.check_output(['git','show',source_pin+':'+relative],cwd=audit.ROOT)
        packets[audit.ROOT/relative] = raw
    read_bytes = Path.read_bytes
    monkeypatch.setattr(Path,'read_bytes',lambda path:packets[path] if path in packets else read_bytes(path))
    def resign():
        current = producer.source_seals()
        record['source_bridge']['current_sources'] = current
        record['source_bridge']['changed_files'] = producer.source_changes(record['source_bridge']['historical_sources'],current)
        replay['relevant_sources'] = current
        record['replay'] = write(tmp_path/'tone-program.json',replay,nodeid=descriptor['nodeid'])
        return write(tmp_path/'tone-attachment.json',record,nodeid=descriptor['nodeid'])
    descriptor = resign()
    assert result() == ('passed',None)  # Exact accepted combined runtime baseline before every corruption.
    assert record['source_bridge']['changed_files']['skills/waapi-skill/wwise_waapi/source_copy_observations.py']['before'] is None
    assert record['source_bridge']['changed_files']['skills/waapi-skill/wwise_waapi/source_copy_proof.py']['before'] is None
    if damage is None:return
    target = next(path for path in packets if path.name == ('gateway.py' if damage == 'partial-bridge' else damage))
    if damage == 'partial-bridge':
        relative = target.relative_to(audit.ROOT).as_posix()
        packets[target] = subprocess.check_output(['git','show',producer.ORIGINAL+':'+relative],cwd=audit.ROOT)
    else:packets[target] += b'\n# unapproved drift\n'
    descriptor = resign()
    outcome,reason = result()
    assert outcome == 'missing' and 'runtime drift is not equivalent' in reason


@pytest.mark.parametrize('damage',('duplicate','conflict','unknown-field','unknown-index-field','input-extra','evidence-extra',
    'dependency-extra','dependency-escape','wrong-node','wrong-shape','program-projection'))
def test_portable_attachment_rejects_closed_field_and_conflict_violations(original_root,inventory,tmp_path,damage):
    path,index,base,attachment,branch = portable_control(tmp_path,original_root,inventory)
    policy = audit.load(audit.ROOT/'docs/branch-coverage-requirements.json')
    baseline,_,_ = audit.portable_binding_inputs(path,policy)
    assert baseline['bindings'][branch['id']]['evidence']['live_metadata'] == attachment['evidence']
    evidence = json.loads((base/attachment['evidence']['artifact']).read_bytes())
    if damage in ('duplicate','conflict'):
        index['metadata_attachments'].append(deepcopy(index['metadata_attachments'][0]))
        if damage == 'conflict':
            extra = deepcopy(attachment);extra['category_inputs']['historical'] = ['metadata','detail','changed']
            desc = write(base/'conflicting.json',extra);desc['artifact']='conflicting.json';index['metadata_attachments'][-1]=desc
    elif damage == 'unknown-field':attachment['extra'] = True
    elif damage == 'unknown-index-field':index['another_attachment_engine'] = []
    elif damage == 'input-extra':attachment['category_inputs']['program_override'] = ['status']
    elif damage == 'evidence-extra':attachment['evidence']['pointer'] = '/arbitrary'
    elif damage == 'dependency-extra':evidence['metadata_run']['native']['ignored'] = True
    elif damage == 'dependency-escape':evidence['metadata_run']['native']['artifact'] = '../outside.json'
    elif damage == 'wrong-node':evidence['replay']['nodeid'] = 'unrelated-node'
    elif damage == 'wrong-shape':attachment['native_shape_sha256'] = '0'*64
    else:
        desc = index['entries'][0]['bindings'];projection = json.loads((base/desc['artifact']).read_bytes())
        projection['bindings'][branch['id']]['evidence']['live_metadata'] = attachment['evidence']
        changed = write(base/desc['artifact'],projection);desc['sha256']=changed['sha256']
    if damage.startswith('dependency') or damage == 'wrong-node':
        updated = write(base/'metadata.changed.json',evidence,nodeid=attachment['evidence']['nodeid']);updated['artifact']='metadata.changed.json';attachment['evidence']=updated
    if damage not in ('duplicate','conflict'):
        desc = write(base/'attachment.changed.json',attachment);desc['artifact']='attachment.changed.json';index['metadata_attachments'][0]=desc
    path.write_text(json.dumps(index))
    with pytest.raises(ValueError):audit.portable_binding_inputs(path,policy)


def test_r51_historical_source_map_does_not_grow_with_current_owned_dependencies():
    # Retained-original discovery must work independently of stale current
    # copied policy; strict whole-index import is deliberately a later phase.
    originals = producer.portable_original_reads()
    assert set(originals) == {'Color', 'ControlInput', 'OverrideColor'}
    original = producer.historical_sources()
    assert len(original) == 343
    assert audit.digest(original) == '9f59dd64d2d7e856fae5f55cd71e5b1f471e1d32883d78a6ad53b860cde3ee9a'
    current = producer.source_seals()
    assert len(current) == 354
    additions = {'skills/waapi-skill/wwise_waapi/owned_control_inputs.py', *(
        'skills/waapi-skill/resources/metadata/' + version + '/owned-control-input-construction.json'
        for version in ('2022.1', '2023.1', '2024.1', '2025.1'))}
    changes = producer.source_changes(original, current)
    assert additions <= set(changes)
    assert all(name not in original and changes[name]['before'] is None
               and changes[name]['after'] == current[name] for name in additions)


@pytest.mark.parametrize('cohort', ('r51', 'r54', 'r55'))
def test_new_owned_dependencies_reject_unreviewed_drift(original_root, inventory, tmp_path, monkeypatch, cohort):
    if cohort == 'r51':
        capture, program, record, bindings, descriptor = controlled_attachment(tmp_path, original_root, inventory, 'ControlInput')
        branch = next(row for row in capture['branches'] if row['id'] in bindings)
        binding = {**bindings[branch['id']], 'category_inputs': {'live_metadata': record['category_inputs']}}
        current_sources = producer.source_seals
    else:
        case = '2022.1|Wwise Delay|DelayTime' if cohort == 'r54' else '2021.1|MusicStinger|CustomCueMatchName'
        capture, program, record, descriptor, branch, binding = r54_control(tmp_path, inventory, case, cohort=cohort)
        current_sources = producer.r54_current_sources
    def result():
        return completion.evidence_result(descriptor, branch, 'c' * 64, 'live_metadata', 'controlled',
            tmp_path, binding, source_root=audit.ROOT, reference_edges=capture['edges'])
    assert result() == ('passed', None)
    assert len(record['source_bridge']['current_sources']) == (354 if cohort == 'r51' else 570)
    additions = ['skills/waapi-skill/wwise_waapi/owned_control_inputs.py', *(
        'skills/waapi-skill/resources/metadata/' + version + '/owned-control-input-construction.json'
        for version in ('2022.1', '2023.1', '2024.1', '2025.1'))]
    original_program, original_record = deepcopy(program), deepcopy(record)
    read_bytes = Path.read_bytes
    for relative in additions:
        assert relative not in record['source_bridge']['historical_sources']
        with monkeypatch.context() as scoped:
            target = audit.ROOT / relative
            scoped.setattr(Path, 'read_bytes', lambda path: read_bytes(path) + b'\n' if path == target else read_bytes(path))
            program, record = deepcopy(original_program), deepcopy(original_record)
            current = current_sources()
            record['source_bridge']['current_sources'] = current
            record['source_bridge']['changed_files'] = producer.source_changes(record['source_bridge']['historical_sources'], current)
            program['relevant_sources'] = current
            record['replay'] = write(tmp_path / 'changed-owned-program.json', program, nodeid=descriptor['nodeid'])
            descriptor = write(tmp_path / 'changed-owned-attachment.json', record, nodeid=descriptor['nodeid'])
            outcome, reason = result()
            assert outcome == 'missing' and ('runtime drift' in reason or 'changed-file proof' in reason)
