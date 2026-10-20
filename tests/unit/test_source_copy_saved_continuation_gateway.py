"""Operation-owned persisted Source proof through normal public transactions."""
from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET
import json
import pytest

from tests.unit.test_legacy_source_copy_collector import saved_copy_runtime, SOURCE, COPIED, DEST, SAVED_OWNER, SAVED_ROLES
from tests.unit.test_field_interface_closure_gateway import PROJECT, SECOND
from tests.semantic.support.typed_gateway_input import create_object_lifecycle_business_preview


def saved_source_task(path, *, rename=False):
    runtime, commands, writes, task = saved_copy_runtime(path)
    root = task.project_file.parent
    task.project_file.write_text(f'<WwiseDocument><Project ID="{PROJECT}" Name="Fixture"/></WwiseDocument>')
    task.objects[PROJECT]['workunitIsDirty'] = False
    midi_id = task.objects[SOURCE]['workunit']['id']
    midi_path = root / 'Actor-Mixer Hierarchy/MIDI.wwu'
    default_path = root / 'Actor-Mixer Hierarchy/Default Work Unit.wwu'
    for identity, file in [(midi_id, midi_path), (SECOND, default_path)]:
        task.objects[identity].update(workunitIsDirty=False, workunitType='rootFile', filePath=str(file))
    task.objects[SAVED_OWNER].update(filePath=str(midi_path), workunit={'id': midi_id})
    task.objects[SOURCE]['filePath'] = str(midi_path)
    task.objects[DEST] = {'id': DEST, 'name': 'Destination', 'type': 'Sound', 'classId': 65552,
        'path': task.objects[SECOND]['path'] + '\\Destination', 'parent': {'id': SECOND},
        'workunit': {'id': SECOND}, 'filePath': str(default_path), 'notes': '', '@IsVoice': False}
    default_path.write_text(f'<WwiseDocument><WorkUnit ID="{SECOND}" Name="Default Work Unit"><ChildrenList>'
        f'<Sound ID="{DEST}" Name="Destination"/></ChildrenList></WorkUnit></WwiseDocument>')
    retained = json.loads((Path(__file__).parents[1] / 'fixtures/metadata/source-owned-2021-native-read-fields.json').read_text())
    owned_fields = {}
    for role, binding in SAVED_ROLES.items():
        if role == 'source': continue
        observed = retained['roles'][role]
        assert observed['class_id'] == binding[3]
        owned_fields[binding[0]] = owned_fields[binding[1]] = observed['metadata']
        task.objects[binding[0]].update({'@' + name: value for name, value in observed['fields'].items()})
    call = task.call
    def observed(uri, args=None, options=None):
        if (args or {}).get('object') in owned_fields:
            fields = owned_fields[args['object']]
            if uri.endswith('getPropertyAndReferenceNames'):
                task.calls.append((uri, deepcopy(args), deepcopy(options)))
                return {'return': list(fields)}
            if uri.endswith('getPropertyInfo'):
                task.calls.append((uri, deepcopy(args), deepcopy(options)))
                return fields[args['property']]
        if uri.endswith('object.get') and ' select @ControlInput ' in (args or {}).get('waql', ''):
            identity = args['waql'].split('"')[1]
            if identity == SAVED_ROLES['rtpc'][0]:
                task.calls.append((uri, deepcopy(args), deepcopy(options)))
                return {'return': task.project_rows([task.objects[SAVED_ROLES['control_input'][0]]], options)}
        result = call(uri, args, options)
        if uri.endswith('object.copy'):
            for role, binding in SAVED_ROLES.items():
                if role != 'source':
                    for name in owned_fields[binding[0]]:
                        if '@' + name in task.objects[binding[0]]:
                            task.objects[binding[1]]['@' + name] = task.objects[binding[0]]['@' + name]
            if rename:
                task.objects[COPIED].update(name=task.objects[SOURCE]['name'] + '1',
                    path=task.objects[SAVED_OWNER]['path'] + '\\' + task.objects[SOURCE]['name'] + '1')
            task.objects[COPIED]['filePath'] = str(midi_path if rename else default_path)
            task.objects[SECOND]['workunitIsDirty'] = True
        if uri.endswith('project.save'):
            if rename and COPIED in task.objects:
                document = ET.parse(midi_path)
                owner, = [row for row in document.iter('Sound') if row.get('ID') == SAVED_OWNER]
                original_source, = [row for row in owner.iter('SourcePlugin') if row.get('ID') == SOURCE]
                copied_source = deepcopy(original_source)
                for role, binding in SAVED_ROLES.items():
                    node, = [row for row in copied_source.iter(binding[2]) if row.get('ID') == binding[0]]
                    node.set('ID', binding[1])
                    if binding[5] is not None: node.set('ShortID', str(binding[5]))
                copied_source.set('Name', task.objects[COPIED]['name'])
                owner.find('ChildrenList').append(copied_source)
                document.write(midi_path)
                default = ET.parse(default_path)
                for children in default.iter('ChildrenList'):
                    for node in list(children):
                        if node.get('ID') == COPIED: children.remove(node)
                default.write(default_path)
            for identity in (PROJECT, SECOND, midi_id): task.objects[identity]['workunitIsDirty'] = False
        return result
    task.call = observed
    return runtime, writes, task


def public_copy(task, *, parent=DEST, conflict='fail'):
    def gateway(argv):
        code, payload = task.run(*argv)
        assert code == 0, payload
        return payload
    preview = create_object_lifecycle_business_preview(gateway, version='2021.1',
        operation='object.copy', object_id=SOURCE, parent_id=parent, name_conflict=conflict)
    tx = preview['transaction_id']
    code, shown = task.run('transaction-show', tx, '--summary-only'); assert code == 0, shown
    code, result = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token']); assert code == 0, result
    code, result = task.run('execute', tx); assert code == 0, result
    return tx


def test_clean_saved_source_copy_defers_terminal_for_separate_final_save(tmp_path):
    runtime, writes, task = saved_source_task(tmp_path)
    task.objects['{01010101-0101-0101-0101-010101010101}'] = {'id': '{01010101-0101-0101-0101-010101010101}',
        'name': 'Unrelated', 'type': 'WorkUnit', 'classId': 1638416,
        'path': r'\Actor-Mixer Hierarchy\Unrelated', 'parent': None, 'notes': '',
        'workunitIsDirty': True}  # Unrelated WWU cannot force a baseline Save.
    tx = public_copy(task)
    code, result = task.run('verify', tx)
    assert code == 0 and result['state'] == 'executed_unverified', result
    assert result['status'] == 'source_copy_saved_proof_pending', result
    assert result['next_command']['command'] == 'continue-source-copy-proof'
    assert [uri.rsplit('.', 1)[-1] for uri, args in writes] == ['copy']
    assert result['source_copy_saved_proof']['baseline_origin'] == 'already_clean'


def test_clean_source_copy_finishes_only_after_owned_separately_authorized_save(tmp_path):
    runtime, writes, task = saved_source_task(tmp_path)
    tx = public_copy(task)
    code, pending = task.run('verify', tx); assert code == 0, pending
    code, child = task.run(*pending['next_command']['gateway_argv']); assert code == 0, json.dumps(child)
    identity, authority = child['draft']['draft_id'], child['task_authority']
    code, checked = task.run('draft-check', identity, '--task-authority', authority,
        '--expected-revision', str(child['draft']['revision'])); assert code == 0, checked
    code, preview = task.run('preview-from-draft', identity, '--task-authority', authority,
        '--expected-revision', str(checked['draft']['revision'])); assert code == 0, preview
    saved = preview['transaction_id']
    code, denied = task.run('execute', saved); assert code == 2, denied
    code, shown = task.run('transaction-show', saved, '--summary-only'); assert code == 0, shown
    code, result = task.run('confirm', saved, '--confirmation-token', shown['confirmation']['token']); assert code == 0, result
    code, result = task.run('execute', saved); assert code == 0, result
    code, result = task.run('verify', saved); assert code == 0, result
    assert result['next_command']['gateway_argv'] == ['verify', tx]
    code, result = task.run(*result['next_command']['gateway_argv'])
    assert code == 0 and result['verified'] is True, json.dumps({'status': result.get('status'), 'message': result.get('message'), 'verification_message': result.get('verification', {}).get('message'), 'failures': [x for x in result.get('verification', {}).get('assertions', []) if not x.get('passed')]})
    scope = result['verification']['verification_scope']
    assert scope['complete_copy_preservation'] is True and scope['owned_role_count'] == 3
    assert [uri.rsplit('.', 1)[-1] for uri, args in writes] == ['copy', 'save']
    assert task.run('execute', tx)[0] == 2


def final_save_preview(task, pending):
    code, child = task.run(*pending['next_command']['gateway_argv']); assert code == 0, json.dumps(child)
    identity, authority = child['draft']['draft_id'], child['task_authority']
    code, checked = task.run('draft-check', identity, '--task-authority', authority,
        '--expected-revision', str(child['draft']['revision'])); assert code == 0, json.dumps(checked)
    code, preview = task.run('preview-from-draft', identity, '--task-authority', authority,
        '--expected-revision', str(checked['draft']['revision'])); assert code == 0, json.dumps(preview)
    return preview


def test_declined_unexecuted_allowed_save_finalizes_live_scope_and_blocks_stale_execution(tmp_path):
    runtime, writes, task = saved_source_task(tmp_path)
    tx = public_copy(task)
    code, pending = task.run('verify', tx); assert code == 0, pending
    assert task.run('config-set', '--project-modification-policy', 'allow_changes')[0] == 0
    preview = final_save_preview(task, pending)
    assert preview['state'] == 'policy_authorized'
    code, declined = task.run('continue-source-copy-proof', tx, '--decline-save')
    assert code == 0 and declined['state'] == 'verified', declined
    scope = declined['verification']['verification_scope']
    assert scope['complete_copy_preservation'] is False
    assert scope['saved_proof_incomplete_reason'] == 'final_Save_declined'
    code, result = task.run('execute', preview['transaction_id'])
    assert code == 2 and [uri.rsplit('.', 1)[-1] for uri, args in writes] == ['copy'], result
    before = task.run('transaction-show', tx, '--summary-only')[1]
    assert task.run('verify', tx)[0] == 2
    after = task.run('transaction-show', tx, '--summary-only')[1]
    assert after['state'] == 'verified' and after['events'] == before['events']


def test_refusal_cannot_finalize_parent_while_owned_save_is_executing(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    runtime, writes, task = saved_source_task(tmp_path)
    tx = public_copy(task)
    code, pending = task.run('verify', tx); assert code == 0, pending
    assert task.run('config-set', '--project-modification-policy', 'allow_changes')[0] == 0
    preview = final_save_preview(task, pending)
    started, release = Event(), Event()
    original = task.call
    def blocked(uri, args=None, options=None):
        if uri.endswith('project.save'):
            started.set()
            assert release.wait(10), 'Test must release its one owned Save'
        return original(uri, args, options)
    task.call = blocked
    with ThreadPoolExecutor(max_workers=1) as executor:
        execution = executor.submit(task.run, 'execute', preview['transaction_id'])
        try:
            assert started.wait(5)
            code, refusal = task.run('continue-source-copy-proof', tx, '--decline-save')
            assert code == 2 and refusal['error_code'] == 'TRANSACTION_EXECUTION_IN_PROGRESS', refusal
            code, parent = task.run('transaction-show', tx, '--summary-only')
            assert code == 0 and parent['state'] == 'executed_unverified'
        finally:
            release.set()
        code, result = execution.result(timeout=5)
        assert code == 0, result
    assert [uri.rsplit('.', 1)[-1] for uri, args in writes] == ['copy', 'save']
    assert task.run('continue-source-copy-proof', tx, '--decline-save')[0] == 2


def checked_dirty_parent(task):
    task.objects[PROJECT]['workunitIsDirty'] = True
    class Checked(Exception): pass
    result = {}
    def gateway(argv):
        code, payload = task.run(*argv); assert code == 0, payload
        if argv[0] == 'draft-check':
            result.update(payload)
            raise Checked()
        return payload
    try:
        create_object_lifecycle_business_preview(gateway, version='2021.1', operation='object.copy',
            object_id=SOURCE, parent_id=DEST, name_conflict='fail')
    except Checked:
        return result
    raise AssertionError('Expected public check boundary')


def authorize_execute_verify(task, tx):
    code, shown = task.run('transaction-show', tx, '--summary-only'); assert code == 0, shown
    if shown['state'] != 'policy_authorized':
        code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token']); assert code == 0, confirmed
    code, executed = task.run('execute', tx); assert code == 0, executed
    code, verified = task.run('verify', tx); assert code == 0, verified
    return verified


def test_dirty_baseline_save_returns_exact_parent_after_gateway_restart_then_completes_copy(tmp_path):
    runtime, writes, task = saved_source_task(tmp_path)
    public_calls, native_trace = [], []
    phase = ['fixture']
    native_call = task.call
    def traced(uri, args=None, options=None):
        native_trace.append({'phase': phase[0], 'uri': uri, 'args': deepcopy(args or {}), 'options': deepcopy(options or {})})
        return native_call(uri, args, options)
    task.call = traced
    invoke = task.run
    def measured(*argv):
        phase[0] = f'{len(public_calls):02d}:' + argv[0]
        code, payload = invoke(*argv)
        public_calls.append((list(argv), len(json.dumps(payload, ensure_ascii=False).encode('utf-8'))))
        return code, payload
    task.run = measured
    checked = checked_dirty_parent(task)
    assert checked['next_command']['command'] == 'continue-source-copy-proof', checked
    save = final_save_preview(task, checked)
    receipt = authorize_execute_verify(task, save['transaction_id'])
    # Every task.run is a separate public Gateway invocation; only durable child
    # state can return the parent capability after baseline Save.
    code, parent = task.run(*receipt['next_command']['gateway_argv']); assert code == 0, parent
    code, resumed = task.run(*receipt['next_command']['gateway_argv']); assert code == 0, resumed
    assert resumed['next_command'] == parent['next_command'] and resumed['draft']['revision'] == parent['draft']['revision']
    assert parent['draft']['draft_id'] == checked['draft']['draft_id']
    assert parent['draft']['revision'] > checked['draft']['revision']
    code, checked_parent = task.run(*parent['next_command']['gateway_argv']); assert code == 0, checked_parent
    code, copy = task.run(*checked_parent['next_command']['gateway_argv']); assert code == 0, copy
    pending = authorize_execute_verify(task, copy['transaction_id'])
    assert pending['source_copy_saved_proof']['baseline_origin'] == 'authorized_baseline_Save'
    final = final_save_preview(task, pending)
    saved = authorize_execute_verify(task, final['transaction_id'])
    code, result = task.run(*saved['next_command']['gateway_argv']); assert code == 0, result
    assert result['verification']['verification_scope']['complete_copy_preservation'] is True
    assert [uri.rsplit('.', 1)[-1] for uri, args in writes] == ['save', 'copy', 'save']
    native = list(Path(task.env['WWISE_EVIDENCE_DIR']).rglob('*.json'))
    budget = {'public_calls': len(public_calls), 'reply_bytes': sum(size for argv, size in public_calls),
        'max_reply_bytes': max(size for argv, size in public_calls), 'native_files': len(native),
        'native_bytes': sum(path.stat().st_size for path in native)}
    assert budget['public_calls'] <= 128 and budget['max_reply_bytes'] <= 4 * 1024 * 1024
    (tmp_path / 'production-budget.json').write_text(json.dumps(budget))
    (tmp_path / 'production-native-trace.json').write_text(json.dumps(native_trace))
    print('R54 production dirty protocol budget:', json.dumps(budget))


def test_saved_proof_rejects_live_owned_scalar_corruption_even_with_equal_saved_xml(tmp_path):
    runtime, writes, task = saved_source_task(tmp_path)
    tx = public_copy(task)
    code, pending = task.run('verify', tx); assert code == 0, pending
    preview = final_save_preview(task, pending)
    saved = authorize_execute_verify(task, preview['transaction_id'])
    task.objects[SAVED_ROLES['curve'][1]]['@Flags'] = 4
    code, failed = task.run(*saved['next_command']['gateway_argv'])
    assert code == 2 and failed['status'] == 'verification_failed', failed
    assert [uri.rsplit('.', 1)[-1] for uri, args in writes] == ['copy', 'save']


@pytest.mark.parametrize('field', ['draft_id', 'task_authority', 'source_revision'])
def test_private_baseline_return_cannot_redirect_or_revive_parent(tmp_path, field):
    from wwise_waapi.canonical import canonical_sha256, canonical_json_bytes
    runtime, writes, task = saved_source_task(tmp_path)
    checked = checked_dirty_parent(task)
    code, child = task.run(*checked['next_command']['gateway_argv']); assert code == 0, child
    save = final_save_preview(task, {'next_command': {'gateway_argv': checked['next_command']['gateway_argv']}})
    receipt = authorize_execute_verify(task, save['transaction_id'])
    parent_file = tmp_path / 'state/operation-drafts-v1/records' / (checked['draft']['draft_id'] + '.json')
    parent_before = parent_file.read_bytes()
    child_file = tmp_path / 'state/operation-drafts-v1/records' / (child['draft']['draft_id'] + '.json')
    record = json.loads(child_file.read_text())
    envelope = record['composition']['source_copy_parent_return']
    if field == 'draft_id': envelope[field] = 'od1-' + '1' * 32
    elif field == 'task_authority': envelope[field] = 'da1-' + '2' * 40
    else: envelope[field] += 1
    # Recompute the nonsecret file integrity digest so this reaches the actual
    # parent/origin/capability binding rather than only damaged-file detection.
    record.pop('record_digest')
    record['record_digest'] = canonical_sha256({'contract': 'waapi-skill.operation-draft-record-digest/v1', 'record': record})
    child_file.write_bytes(canonical_json_bytes(record))
    code, failed = task.run(*receipt['next_command']['gateway_argv'])
    assert code == 2 and 'next_command' not in failed, failed
    assert parent_file.read_bytes() == parent_before
    assert [uri.rsplit('.', 1)[-1] for uri, args in writes] == ['save']


def test_baseline_refusal_invalidates_previously_allowed_save_and_keeps_ordinary_copy_usable(tmp_path):
    runtime, writes, task = saved_source_task(tmp_path)
    checked = checked_dirty_parent(task)
    assert task.run('config-set', '--project-modification-policy', 'allow_changes')[0] == 0
    save = final_save_preview(task, checked)
    code, refusal = task.run(*checked['next_command']['gateway_argv'], '--decline-save')
    assert code == 0, refusal
    assert task.run('execute', save['transaction_id'])[0] == 2
    code, parent = task.run(*refusal['next_command']['gateway_argv']); assert code == 0, parent
    code, preview = task.run(*parent['next_command']['gateway_argv']); assert code == 0, preview
    result = authorize_execute_verify(task, preview['transaction_id'])
    assert result['verified'] and not result['verification']['verification_scope']['complete_copy_preservation']
    assert [uri.rsplit('.', 1)[-1] for uri, args in writes] == ['copy']


@pytest.mark.parametrize('fault', ['point-value', 'point-order', 'alias', 'missing-member', 'short-id'])
def test_saved_graph_corruption_cannot_finish_or_downgrade_copy(tmp_path, fault):
    runtime, writes, task = saved_source_task(tmp_path)
    tx = public_copy(task)
    code, pending = task.run('verify', tx); assert code == 0, pending
    save = final_save_preview(task, pending)
    authorize_execute_verify(task, save['transaction_id'])
    model = task.project_file.parent / 'Actor-Mixer Hierarchy/Default Work Unit.wwu'
    tree = ET.parse(model)
    source, = list(tree.iter('SourcePlugin'))
    curve = source.find('.//Curve')
    if fault == 'point-value': curve.find('PointList/Point/YPos').text = '99'
    elif fault == 'point-order': curve.find('PointList')[:] = list(reversed(curve.find('PointList')))
    elif fault == 'alias': curve.set('ID', source.find('.//RTPC').get('ID'))
    elif fault == 'missing-member': source.find('.//Reference/Custom').clear()
    else: task.objects[SAVED_ROLES['control_input'][1]]['shortId'] += 1
    tree.write(model)
    code, failed = task.run('continue-source-copy-proof', tx, '--decline-save')
    assert code == 2, failed  # Save already ran: refusal cannot claim prevention.
    code, failed = task.run('verify', tx)
    assert code == 2 and failed['status'] == 'verification_failed', failed
    assert [uri.rsplit('.', 1)[-1] for uri, args in writes] == ['copy', 'save']


def test_baseline_refusal_is_atomic_with_owned_save_execution(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    runtime, writes, task = saved_source_task(tmp_path)
    checked = checked_dirty_parent(task)
    assert task.run('config-set', '--project-modification-policy', 'allow_changes')[0] == 0
    preview = final_save_preview(task, checked)
    started, release = Event(), Event()
    original = task.call
    def blocked(uri, args=None, options=None):
        if uri.endswith('project.save'):
            started.set(); assert release.wait(10)
        return original(uri, args, options)
    task.call = blocked
    with ThreadPoolExecutor(max_workers=1) as executor:
        execution = executor.submit(task.run, 'execute', preview['transaction_id'])
        try:
            assert started.wait(5)
            code, refusal = task.run(*checked['next_command']['gateway_argv'], '--decline-save')
            assert code == 2 and refusal['error_code'] == 'TRANSACTION_EXECUTION_IN_PROGRESS', refusal
        finally:
            release.set()
        code, result = execution.result(timeout=5); assert code == 0, result
    assert [uri.rsplit('.', 1)[-1] for uri, args in writes] == ['save']
    assert task.run(*checked['next_command']['gateway_argv'], '--decline-save')[0] == 2


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1'])
def test_saved_observer_version_boundary_preserves_ordinary_copy_and_read_only_policy(tmp_path, version):
    runtime, writes, task = saved_source_task(tmp_path)
    task.version = version
    if version == '2021.1':
        observed_call = task.call
        def authoring(uri, args=None, options=None):
            result = observed_call(uri, args, options)
            if uri.endswith('getInfo'): result['isCommandLine'] = False
            return result
        task.call = authoring
    task.run('config-set', '--wwise-version', version)
    def gateway(argv):
        code, payload = task.run(*argv); assert code == 0, payload
        return payload
    preview = create_object_lifecycle_business_preview(gateway, version=version,
        operation='object.copy', object_id=SOURCE, parent_id=DEST, name_conflict='fail')
    result = authorize_execute_verify(task, preview['transaction_id'])
    assert result['verified'] and not result['verification']['verification_scope']['complete_copy_preservation']
    assert [uri.rsplit('.', 1)[-1] for uri, args in writes] == ['copy']
    # A read-only policy still blocks any ordinary copy Preview, independent of
    # saved observer availability. No Save or policy override is synthesized.
    task.objects.pop(COPIED)
    task.run('config-set', '--project-modification-policy', 'read_only')
    responses = []
    def blocked(argv):
        code, payload = task.run(*argv); responses.append((code, payload))
        if code: raise ValueError(payload)
        return payload
    with pytest.raises(ValueError):
        create_object_lifecycle_business_preview(blocked, version=version,
            operation='object.copy', object_id=SOURCE, parent_id=DEST, name_conflict='fail')
    assert responses[-1][0] == 2 and [uri.rsplit('.', 1)[-1] for uri, args in writes] == ['copy']


def test_read_only_final_save_offer_cannot_dispatch_and_decline_keeps_exact_live_scope(tmp_path):
    runtime, writes, task = saved_source_task(tmp_path)
    tx = public_copy(task)
    code, pending = task.run('verify', tx); assert code == 0, pending
    assert task.run('config-set', '--project-modification-policy', 'read_only')[0] == 0
    code, child = task.run(*pending['next_command']['gateway_argv']); assert code == 0, child
    code, checked = task.run(*child['next_command']['gateway_argv']); assert code == 0, checked
    code, denied = task.run(*checked['next_command']['gateway_argv']); assert code == 2, denied
    code, scoped = task.run('continue-source-copy-proof', tx, '--decline-save')
    assert code == 0 and scoped['verified'] and not scoped['verification']['verification_scope']['complete_copy_preservation'], scoped
    assert [uri.rsplit('.', 1)[-1] for uri, args in writes] == ['copy']


def test_clean_baseline_dirty_drift_blocks_copy_before_any_write(tmp_path):
    runtime, writes, task = saved_source_task(tmp_path)
    def gateway(argv):
        code, payload = task.run(*argv); assert code == 0, payload
        return payload
    preview = create_object_lifecycle_business_preview(gateway, version='2021.1', operation='object.copy',
        object_id=SOURCE, parent_id=DEST, name_conflict='fail')
    tx = preview['transaction_id']
    shown = task.run('transaction-show', tx, '--summary-only')[1]
    assert task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    task.objects[SECOND]['workunitIsDirty'] = True
    code, failed = task.run('execute', tx)
    assert code == 2 and not writes, failed


def test_final_save_continuation_resumes_same_sealed_child_after_lost_reply(tmp_path):
    runtime, writes, task = saved_source_task(tmp_path)
    tx = public_copy(task)
    code, pending = task.run('verify', tx); assert code == 0, pending
    preview = final_save_preview(task, pending)
    code, resumed = task.run(*pending['next_command']['gateway_argv']); assert code == 0, resumed
    assert resumed['next_command']['gateway_argv'] == ['transaction-show', preview['transaction_id'], '--summary-only']
    authorize_execute_verify(task, preview['transaction_id'])
    code, resumed = task.run(*pending['next_command']['gateway_argv']); assert code == 0, resumed
    assert resumed['next_command']['gateway_argv'] == ['verify', tx]
    code, result = task.run(*resumed['next_command']['gateway_argv']); assert code == 0 and result['verified'], result
    assert [uri.rsplit('.', 1)[-1] for uri, args in writes] == ['copy', 'save']


def test_rechecking_parent_invalidates_baseline_child_before_native_save(tmp_path):
    runtime, writes, task = saved_source_task(tmp_path)
    checked = checked_dirty_parent(task)
    assert task.run('config-set', '--project-modification-policy', 'allow_changes')[0] == 0
    save = final_save_preview(task, checked)
    argv = checked['next_command']['gateway_argv']
    code, rechecked = task.run('draft-check', *argv[1:]); assert code == 0, rechecked
    assert rechecked['draft']['revision'] > checked['draft']['revision']
    code, failed = task.run('execute', save['transaction_id'])
    assert code == 2 and writes == [], failed


def test_generated_save_start_association_survives_origin_stripping(tmp_path):
    from wwise_waapi.canonical import canonical_sha256, canonical_json_bytes
    runtime, writes, task = saved_source_task(tmp_path)
    tx = public_copy(task)
    code, pending = task.run('verify', tx); assert code == 0, pending
    code, child = task.run(*pending['next_command']['gateway_argv']); assert code == 0, child
    identity = child['draft']['draft_id']
    file = tmp_path / 'state/operation-drafts-v1/records' / (identity + '.json')
    record = json.loads(file.read_text())
    record['composition'].pop('source_copy_save_origin')
    record.pop('record_digest')
    record['record_digest'] = canonical_sha256({'contract': 'waapi-skill.operation-draft-record-digest/v1', 'record': record})
    file.write_bytes(canonical_json_bytes(record))
    code, blocked = task.run('draft-inspect', identity, '--task-authority', child['task_authority'])
    assert code == 2 and [uri.rsplit('.', 1)[-1] for uri, args in writes] == ['copy'], blocked


def test_old_ordinary_save_id_matching_new_namespace_stays_ordinary(tmp_path):
    from wwise_waapi.canonical import canonical_sha256, canonical_json_bytes
    runtime, writes, task = saved_source_task(tmp_path)
    code, ordinary = task.run('draft-start', 'ak.wwise.core.project.save'); assert code == 0, ordinary
    old = ordinary['draft']['draft_id']
    directory = tmp_path / 'state/operation-drafts-v1/records'
    record = json.loads((directory / (old + '.json')).read_text())
    legacy = 'od1-f54c50' + old[-26:]
    record['draft_id'] = legacy
    previous = ''
    for event in record['audit']:
        event.update(draft_id=legacy, previous_event_hash=previous)
        event.pop('event_hash')
        event['event_hash'] = previous = canonical_sha256(event)
    record.pop('record_digest')
    record['record_digest'] = canonical_sha256({'contract': 'waapi-skill.operation-draft-record-digest/v1', 'record': record})
    (directory / (legacy + '.json')).write_bytes(canonical_json_bytes(record))
    (directory / (legacy + '.json')).chmod(0o600)
    code, inspected = task.run('draft-inspect', legacy, '--task-authority', ordinary['task_authority'])
    assert code == 0 and inspected['draft']['draft_id'] == legacy, inspected
    assert not writes


@pytest.mark.parametrize('fault', ['missing-original-file', 'corrupt-original-point'])
def test_decline_distinguishes_unavailable_optional_file_from_observed_graph_corruption(tmp_path, fault):
    runtime, writes, task = saved_source_task(tmp_path)
    tx = public_copy(task)
    code, pending = task.run('verify', tx); assert code == 0, pending
    file = task.project_file.parent / 'Actor-Mixer Hierarchy/MIDI.wwu'
    if fault == 'missing-original-file': file.rename(file.with_suffix('.held'))
    else:
        tree = ET.parse(file)
        source, = [row for row in tree.iter('SourcePlugin') if row.get('ID') == SOURCE]
        source.find('.//Curve/PointList/Point/YPos').text = '99'
        tree.write(file)
    code, result = task.run('continue-source-copy-proof', tx, '--decline-save')
    if fault == 'missing-original-file':
        assert code == 0 and result['verified'], result
        scope = result['verification']['verification_scope']
        assert not scope['complete_copy_preservation'] and scope['declined_saved_observation']['status'] == 'read_authority_unavailable'
    else:
        assert code == 2 and result['status'] == 'verification_failed', result
    assert [uri.rsplit('.', 1)[-1] for uri, args in writes] == ['copy']


def test_baseline_save_rejects_selected_file_membership_drift_before_write(tmp_path):
    runtime, writes, task = saved_source_task(tmp_path)
    checked = checked_dirty_parent(task)
    assert task.run('config-set', '--project-modification-policy', 'allow_changes')[0] == 0
    save = final_save_preview(task, checked)
    task.objects[SOURCE]['filePath'] = str(task.project_file.parent / 'Actor-Mixer Hierarchy/Default Work Unit.wwu')
    code, failed = task.run('execute', save['transaction_id'])
    assert code == 2 and not writes, failed


def test_dirty_baseline_save_does_not_reject_other_valid_source_shapes(tmp_path):
    runtime, writes, task = saved_source_task(tmp_path)
    file = task.project_file.parent / 'Actor-Mixer Hierarchy/MIDI.wwu'
    tree = ET.parse(file)
    source, = [row for row in tree.iter('SourcePlugin') if row.get('ID') == SOURCE]
    prop = source.find("PropertyList/Property[@Name='OutputLevel']")
    prop.remove(prop.find('RTPCList'))  # An ordinary Synth without this owned graph is outside the first full shape.
    tree.write(file)
    for role, binding in SAVED_ROLES.items():
        if role != 'source': task.objects.pop(binding[0])
    checked = checked_dirty_parent(task)
    save = final_save_preview(task, checked)
    receipt = authorize_execute_verify(task, save['transaction_id'])
    code, parent = task.run(*receipt['next_command']['gateway_argv']); assert code == 0, parent
    code, checked = task.run(*parent['next_command']['gateway_argv']); assert code == 0, checked
    assert checked['next_command']['command'] == 'preview-from-draft'
    code, preview = task.run(*checked['next_command']['gateway_argv']); assert code == 0, preview
    assert preview['state'] == 'awaiting_confirmation'
    assert [uri.rsplit('.', 1)[-1] for uri, args in writes] == ['save']


def test_large_sound_childset_keeps_ordinary_copy_without_claiming_complete_saved_proof(tmp_path):
    runtime, writes, task = saved_source_task(tmp_path)
    for index in range(128):
        identity = '{' + f'{index + 1:08X}' + '-0101-0101-0101-010101010101}'
        task.objects[identity] = {'id': identity, 'name': f'Retained {index}', 'type': 'SourcePlugin',
            'classId': 9699330, 'parent': {'id': SAVED_OWNER}, 'notes': '',
            'path': task.objects[SAVED_OWNER]['path'] + f'\\Retained {index}'}
    tx = public_copy(task)
    code, result = task.run('verify', tx)
    assert code == 0 and result['verified'], result
    scope = result['verification']['verification_scope']
    assert not scope['complete_copy_preservation'] and 'owner_childsets_over_observation_budget' in scope['unobserved']
    assert [uri.rsplit('.', 1)[-1] for uri, args in writes] == ['copy']


def test_saved_same_sound_rename_preserves_source_and_owned_graph_with_new_root_name(tmp_path):
    runtime, writes, task = saved_source_task(tmp_path, rename=True)
    tx = public_copy(task, parent=SAVED_OWNER, conflict='rename')
    code, pending = task.run('verify', tx); assert code == 0, pending
    save = final_save_preview(task, pending)
    result = authorize_execute_verify(task, save['transaction_id'])
    code, verified = task.run(*result['next_command']['gateway_argv'])
    assert code == 0 and verified['verification']['verification_scope']['complete_copy_preservation'], verified
    assert task.objects[COPIED]['name'] == 'Wwise Synth One1'
    assert task.objects[SOURCE]['name'] == 'Wwise Synth One'
    assert [uri.rsplit('.', 1)[-1] for uri, args in writes] == ['copy', 'save']
