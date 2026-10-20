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


@pytest.mark.parametrize('damage',[None,'operation_tone.py','host_ui_debug_business_contracts.py','host_ui_debug_business.py','gateway.py','object_lifecycle_graph.py','operation_registry.py','source_copy_observations.py','core_business.py','core_business_contracts.py','partial-bridge'])
def test_metadata_bridge_accepts_only_exact_reviewed_tone_blobs(original_root,inventory,tmp_path,monkeypatch,damage):
    import subprocess
    capture,replay,record,bindings,descriptor = controlled_attachment(tmp_path,original_root,inventory,'ControlInput')
    branch = next(row for row in capture['branches'] if row['id'] in bindings)
    binding = {**bindings[branch['id']],'category_inputs':{'live_metadata':record['category_inputs']}}
    def result():
        return completion.evidence_result(descriptor,branch,'c'*64,'live_metadata','controlled',tmp_path,binding,
            source_root=audit.ROOT,reference_edges=capture['edges'])
    assert result() == ('passed',None)
    accepted = 'ae7e6e2981df0f2c9c8bc43fe3026f6d4962ff90'
    packets = {}
    for name in ('operation_tone.py','host_ui_debug_business_contracts.py','host_ui_debug_business.py','gateway.py',
                 'object_lifecycle_graph.py','operation_registry.py','source_copy_observations.py','core_business.py','core_business_contracts.py'):
        relative = ('skills/waapi-skill/scripts/' if name == 'gateway.py' else 'skills/waapi-skill/wwise_waapi/')+name
        raw = subprocess.check_output(['git','show',accepted+':'+relative],cwd=audit.ROOT)
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
    assert result() == ('passed',None)  # Exact accepted Tone + Source-copy + Save baseline before every corruption.
    assert record['source_bridge']['changed_files']['skills/waapi-skill/wwise_waapi/source_copy_observations.py']['before'] is None
    if damage is None:return
    target = next(path for path in packets if path.name == ('gateway.py' if damage == 'partial-bridge' else damage))
    if damage == 'partial-bridge':
        relative = str(target.relative_to(audit.ROOT))
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
