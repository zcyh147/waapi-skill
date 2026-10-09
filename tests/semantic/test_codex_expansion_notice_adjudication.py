"""Prospective per-workflow notices through the shared sealed reviewer seam."""
import json
import pytest
from pathlib import Path
from types import SimpleNamespace


def timeline(text, *, version='2025.1', ask=False):
    events = [
        {'type': 'item.completed', 'item': {'type': 'command_execution', 'command': 'preview'}},
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': text}},
    ]
    if not ask:
        events.append({'type': 'item.started', 'item': {'type': 'command_execution', 'command': 'execute'}})
    commands = [SimpleNamespace(command=label, argv=('python', 'skills/waapi-skill/scripts/run.py',
        'gateway.py', route, '--version', version)) for label, route in
        [('preview', 'preview-from-draft'), ('execute', 'execute')]]
    return SimpleNamespace(stdout='\n'.join(json.dumps(row, ensure_ascii=False) for row in events)), commands


def historical_case(case_id):
    cases = json.loads((Path(__file__).parents[1] /
        'fixtures/semantic/expansion-contextual-notices-c39b728.json').read_text())['cases']
    return next(row for row in cases if row['case'].endswith(case_id))


def import_case(case_id):
    return json.loads((Path(__file__).parents[1] /
        'fixtures/semantic/expansion-notice-adjudication-v1.json').read_text())['cases'][case_id]


@pytest.mark.parametrize('case_id', ['C01', 'C03', 'M01'])
def test_import_review_receives_exact_typed_roles(case_id):
    from tests.semantic.support.codex_expansion_notice_adjudication import decide_expansion_notice
    case = import_case(case_id)
    result, commands = timeline(case['unsupported_notice'], ask=case_id != 'M01')
    decision = decide_expansion_notice(result, commands, case_id=case_id, version='2025.1',
        execute_expected=case_id == 'M01', preview_artifact=case['artifact'], before_snapshot=case['before'],
        preview_parameters=case['parameters'])
    assert decision['outcome'] == 'review_required'
    roles = decision['input']['attested_roles']
    assert roles['quantity'] == {'C01': 1, 'C03': 2, 'M01': 3}[case_id]
    assert roles['mappings'][0]['source_file'] == {'C01': '/replacement/JP.wav', 'C03': '/replacement/left/Hit.wav',
        'M01': None}[case_id]
    if case_id == 'C01':
        assert roles['mappings'][0]['language'] == 'Japanese'
        assert roles['target']['volume_db'] == -3
    elif case_id == 'C03':
        assert roles['mappings'][1]['source_file'] == '/replacement/right/Hit.wav'
        assert roles['mappings'][0]['destination']['id'] != roles['mappings'][1]['destination']['id']
    else:
        assert roles['mappings'][1]['field_owner'] == 'MusicTrack'
        assert roles['mappings'][1]['properties'] == [{'name': 'Volume', 'value': -6}]


def test_rtpc_review_input_retains_existing_association_and_ordered_delta():
    from tests.semantic.support.codex_expansion_notice_adjudication import decide_expansion_notice
    case = historical_case('C06')
    result, commands = timeline('即将在已核对的声音上把 Rain_Intensity 到 Volume 的原有 RTPC 换成三节点直线映射；0时-48dB，50时-6dB，100时0dB，其余曲线保持。')
    plan = case['artifact']['prepared_operation']['verification_plan']
    decision = decide_expansion_notice(result, commands, case_id='C06', version='2025.1', execute_expected=True,
        preview_artifact=case['artifact'], before_snapshot=case['before'], preview_parameters={
            'version': '2025.1', 'owner_id': plan['object_id'], 'control_id': plan['control_input_id'],
            'target_id': plan['existing_rtpc_id'], 'expected_notes': ''})
    assert decision['outcome'] == 'review_required'
    roles = decision['input']['attested_roles']
    assert roles['association']['new'] == [(0, -48), (50, -6), (100, 0)]
    assert roles['units']['y'] == 'decibels'


def test_stinger_review_input_keeps_distinct_source_target_owner_segment_roles():
    from tests.semantic.support.codex_expansion_notice_adjudication import decide_expansion_notice
    case = historical_case('M05')
    result, commands = timeline('即将让已核对的 MusicStinger 接收 Backup_Team_Arrives 触发，仍播放同一音乐段；只改 Trigger 引用，容器和其他 Stinger 保持。')
    decision = decide_expansion_notice(result, commands, case_id='M05', version='2025.1', execute_expected=True,
        preview_artifact=case['artifact'], before_snapshot=case['before'], preview_parameters={'version': '2025.1'})
    assert decision['outcome'] == 'review_required'
    roles = decision['input']['attested_roles']
    assert roles['destination']['type'] == 'Trigger'
    assert roles['source']['type'] == 'MusicStinger'
    assert roles['source']['id'] != roles['destination']['id']
    assert roles['preserved_segment']['id'] == case['before']['segment']['id']


def test_attenuation_unsupported_equivalent_binds_typed_curve_and_weaker_verifier():
    from tests.semantic.support.codex_expansion_notice_adjudication import decide_expansion_notice
    fixture = json.loads((Path(__file__).parents[1] /
        'fixtures/semantic/expansion-attenuation-notice-c39b728-2025.json').read_text())
    text = '即将让这份衰减的干声随距离按三个直线节点衰落：距离 0 为 0 dB，5距离 0 为 -12 dB，10距离 0 为 -48 dB。其他曲线和源对象保持。'
    result, commands = timeline(text)
    decision = decide_expansion_notice(result, commands, case_id='C08', version='2025.1',
        execute_expected=True, preview_artifact=fixture['artifact'], before_snapshot=fixture['before'],
        preview_parameters={'version': '2025.1', 'object_id': fixture['before']['attenuation']['id'],
            'expected_points': [{'x': 0, 'y': 0, 'shape': 'Linear'}, {'x': 50, 'y': -12, 'shape': 'Linear'},
                                {'x': 100, 'y': -48, 'shape': 'Linear'}]})
    assert decision['outcome'] == 'review_required'
    roles = decision['input']['attested_roles']
    assert roles['gateway_verification'] == 'result_schema'
    assert roles['curve']['kind'] == 'volume-dry'
    assert roles['curve']['points'][1] == {'x': 50, 'y': -12, 'shape': 'Linear'}


def test_new_attenuation_runner_receipt_replays_without_model(tmp_path, monkeypatch):
    from tests.semantic.support.codex_expansion_notice_adjudication import grade_expansion_notice, CONTRACT
    from tests.semantic.support.codex_expansion_archive import replay_c09_notice
    from tests.semantic.support import codex_c09_notice_adjudication as review
    from tests.semantic.test_codex_expansion_archive import _sealed_c08
    from tests.semantic.test_codex_c09_notice_adjudication import grounded_judgment
    from tests.semantic.support.codex_harness import completed_command_records, BoundedProcessResult
    from wwise_waapi.transactions import TransactionStore
    _sealed_c08(tmp_path)
    plan = json.loads((tmp_path / 'expansion-plan.json').read_text())
    artifact = TransactionStore(tmp_path / 'broker/state').load_preview('tx1-00000000000000000001').artifact
    directory = tmp_path / 'turns/turn-01'
    events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
    for row in events:
        if row.get('item', {}).get('id') == 'preview-notice':
            row['item']['text'] = '我将让 FixtureAttenuation 的干声音量随距离作直线衰落，距离0为0dB，距离100为-48dB；只换这一条自定义曲线。'
    result = SimpleNamespace(stdout='\n'.join(json.dumps(row) for row in events))
    commands = completed_command_records(events, platform_name='posix')
    binary, auth = tmp_path / 'fake-codex', tmp_path / 'fake-auth'
    binary.write_bytes(b'fake CLI')
    auth.write_text('{}')
    options = SimpleNamespace(codex_binary=binary, auth_json=auth, windows_powershell_core_host=None)
    def process(command, **kwargs):
        if command[1:] == ['features', 'list']:
            return BoundedProcessResult(0, '\n'.join(review.DISABLED_FEATURES), '', .01)
        if command[1:] == ['exec', '--help']:
            return BoundedProcessResult(0, '--output-schema --ephemeral --ignore-user-config --ignore-rules --sandbox', '', .01)
        if 'prompt-input' in command:
            return BoundedProcessResult(0, json.dumps([{'role': 'developer', 'content': review.reviewer_rubric(CONTRACT)}]), '', .01)
        payload = json.loads(command[-1])
        assert payload['attested_roles']['gateway_verification'] == 'result_schema'
        output = [{'type': 'thread.started', 'thread_id': 'independent'}, {'type': 'turn.started'},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(grounded_judgment(payload))}},
            {'type': 'turn.completed', 'usage': {'input_tokens': 10, 'output_tokens': 10}}]
        return BoundedProcessResult(0, '\n'.join(json.dumps(row) for row in output), '', .01)
    monkeypatch.setattr(review, 'run_process', process)
    kwargs = dict(case_id='C08', version='2025.1', execute_expected=True, preview_artifact=artifact,
        before_snapshot=plan['before'], preview_parameters=plan['preview_parameters'], transaction_id='tx1-00000000000000000001',
        user_prompt=plan['prompts'][0])
    graded = grade_expansion_notice(result, commands, other_gates={'authorization': True}, root=directory, options=options, **kwargs)
    assert graded['passed'] is True
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('model replay')))
    assert replay_c09_notice(directory, result, commands, other_gates={'authorization': True},
        expected_runtime=review.reviewer_runtime_identity(options), expected_binding_sha256=graded['invocation_binding_sha256'],
        adjudication_contract=CONTRACT, **kwargs) is True
    from dataclasses import asdict
    from tests.semantic.support.codex_expansion_policy import canonical_digest
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive
    (directory / 'events.jsonl').write_text(result.stdout)
    facts_path = directory / 'codex-facts.json'
    facts = json.loads(facts_path.read_text())
    facts['command_facts']['command_records'] = [asdict(row) for row in commands]
    facts_path.write_text(json.dumps(facts))
    plan.pop('sha256')
    plan['notice_adjudication'] = {'configuration': review.reviewer_configuration(CONTRACT),
        'runtime': review.reviewer_runtime_identity(options)}
    digest = canonical_digest(plan)
    (tmp_path / 'expansion-plan.json').write_text(json.dumps({**plan, 'sha256': digest}))
    for name in ('expansion-agent-budget.json', 'expansion-task-result.json'):
        path = tmp_path / name
        body = json.loads(path.read_text())
        body['turns'][0]['notice_invocation_binding_sha256'] = graded['invocation_binding_sha256']
        if name == 'expansion-task-result.json': body['plan_sha256'] = digest
        path.write_text(json.dumps(body))
    before = {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    archived = verify_expansion_task_archive(tmp_path, expected_unit_id='EXP25-C08',
        expected_version='2025.1', expected_inputs_sha256='a' * 64)
    assert archived['business_pass'] is True
    assert archived['gateway_verification_state'] == 'result_schema_checked'
    assert before == {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}


def case_facts(case_id, version='2025.1'):
    """Independent existing case oracles supply expected after-state facts."""
    from copy import deepcopy
    if case_id in {'C01', 'C03', 'M01'}:
        case = import_case(case_id)
        artifact, before, parameters = case['artifact'], case['before'], case['parameters']
        notice = case['unsupported_notice']
    elif case_id == 'C08':
        case = json.loads((Path(__file__).parents[1] /
            'fixtures/semantic/expansion-attenuation-notice-c39b728-2025.json').read_text())
        artifact, before = case['artifact'], case['before']
        parameters = {'version': version, 'object_id': before['attenuation']['id'],
            'expected_points': [{'x': 0, 'y': 0, 'shape': 'Linear'}, {'x': 50, 'y': -12, 'shape': 'Linear'},
                                {'x': 100, 'y': -48, 'shape': 'Linear'}]}
        notice = '即将让目标衰减的干声随距离按三个直线节点衰落：距离 0 为 0 dB，5距离 0 为 -12 dB，10距离 0 为 -48 dB。其他曲线和源对象保持。'
    else:
        case = historical_case(case_id)
        artifact, before = case['artifact'], case['before']
        if case_id == 'C06':
            plan = artifact['prepared_operation']['verification_plan']
            parameters = {'version': version, 'owner_id': plan['object_id'], 'control_id': plan['control_input_id'],
                'target_id': plan['existing_rtpc_id'], 'expected_notes': ''}
            notice = '将让原 Sound 的 Rain_Intensity→Volume 曲线用三个直线节点，0值-48dB，50值-6dB，100值0dB。其他RTPC及媒体保留。'
        elif case_id == 'M05':
            parameters = {'version': version}
            notice = '即将让已核对的 MusicStinger 接收 Backup_Team_Arrives 触发，仍播放同一音乐段；只改 Trigger 引用，容器和其他 Stinger 保持。'
        else:
            descriptor = artifact['request']['arguments']['plugin']
            parameters = {'version': version, 'owner_id': before['owner']['id'],
                'class_id': descriptor['class_id'], 'name': descriptor['name'], 'notes': descriptor['notes']}
            notice = '目标声音的效果链即将多一项 ' + descriptor['name'] + '，Wwise Gain；备注为“' + descriptor['notes'] + '”。只追加该项，既有效果器原样。'
    if case_id == 'C09' and version == '2025.1':
        case = json.loads((Path(__file__).parents[1] / 'fixtures/semantic/c09-notice-adjudication-v1.json').read_text())
        artifact, before, notice = case['preview_artifact'], case['before_snapshot'], case['notice']
        descriptor = artifact['request']['arguments']['plugin']
        parameters = {'version': version, 'owner_id': before['owner']['id'],
            'class_id': descriptor['class_id'], 'name': descriptor['name'], 'notes': descriptor['notes']}
    artifact = deepcopy(artifact)
    # Versioned C09 placement comes from separate 22/25 witnesses. Other case
    # requests are identical business fixtures; only their pinned version moves.
    def pin(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == 'version': value[key] = version
                else: pin(child)
        elif isinstance(value, list):
            for child in value: pin(child)
    pin(artifact)
    parameters['version'] = version
    after = deepcopy(before)
    if case_id == 'C01':
        after['sources']['Japanese']['media']['sha256'] = 'replacement-Japanese'
        oracle = {'replacement_sha256': 'replacement-Japanese'}
    elif case_id == 'C03':
        oracle = {'expected': {key: 'replacement-' + row['object']['name'] for key, row in before['sounds'].items()}}
        for key, digest in oracle['expected'].items(): after['sounds'][key]['media']['sha256'] = digest
    elif case_id == 'M01':
        from tests.semantic.test_codex_expansion_music_case import snapshots
        _, created = snapshots()
        after.update(segment=created['segment'], tracks=created['tracks'])
        after['segment']['parent']['id'] = before['parent']['id']
        after['children'] = before['children'] + [after['segment']]
        oracle = {'expected_hashes': {'Quiet': 'Quiet', 'Full': 'Full'}}
    elif case_id == 'C06':
        after['rtpcs'][parameters['target_id']]['@Curve']['points'] = [
            {'x': 0, 'y': -48, 'shape': 'Linear'}, {'x': 50, 'y': -6, 'shape': 'Linear'},
            {'x': 100, 'y': 0, 'shape': 'Linear'}]
        oracle = {'target_id': parameters['target_id']}
    elif case_id == 'C08':
        after['curves']['volume-dry'] = {'use': 'Custom', 'points': parameters['expected_points']}
        oracle = {'expected_points': parameters['expected_points']}
    elif case_id == 'M05':
        new = {'id': before['target']['id'], 'name': before['target']['name']}
        after['stinger']['@Trigger'] = new
        next(row for row in after['siblings'] if row['id'] == before['stinger']['id'])['@Trigger'] = new
        oracle = {'version': version, 'target_id': before['target']['id']}
    else:
        effect = '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}'
        slot = (str(next(n for n in range(4) if str(n) not in before['slot_order'])) if version == '2022.1'
            else '{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}')
        descriptor = artifact['request']['arguments']['plugin']
        after['slot_order'].append(slot)
        after['entries'].append({'slot': slot, 'slot_state': None if version == '2022.1' else {
            'id': slot, 'type': 'EffectSlot', 'owner': {'id': before['owner']['id']}, '@Effect': {'id': effect}},
            'effect': {'id': effect, 'type': 'Effect', 'classId': descriptor['class_id'], 'name': descriptor['name'],
                'notes': descriptor['notes'], 'owner': {'id': before['owner']['id'] if version == '2022.1' else slot}}})
        oracle = {'version': version, 'expected_class_id': descriptor['class_id'],
            'expected_name': descriptor['name'], 'expected_notes': descriptor['notes']}
    return artifact, before, after, parameters, oracle, notice


def sealed_workflow(root, monkeypatch, case_id, version='2025.1', *, damage=None, text=None):
    """Complete real-TransactionStore fixture through runner grade and archive."""
    import hashlib
    import importlib
    import shlex
    import shutil
    from copy import deepcopy
    from dataclasses import asdict
    from tests.semantic.test_codex_expansion_archive import _sealed_c08, _write
    from tests.semantic.support.codex_expansion_policy import canonical_digest
    from tests.semantic.support.codex_harness import completed_command_records, BoundedProcessResult
    from tests.semantic.support import codex_c09_notice_adjudication as review
    from tests.semantic.support.codex_expansion_notice_adjudication import grade_expansion_notice, CONTRACT
    from tests.semantic.test_codex_c09_notice_adjudication import grounded_judgment
    from wwise_waapi.transactions import TransactionStore, confirmation_token_for
    _sealed_c08(root)
    artifact, before, after, parameters, oracle_parameters, notice = case_facts(case_id, version)
    if text is not None: notice = text
    modules = {'C01': 'voice', 'C03': 'media', 'C06': 'rtpc', 'C08': 'attenuation', 'C09': 'effects', 'M01': 'music', 'M05': 'stinger'}
    module = importlib.import_module('tests.semantic.support.codex_expansion_' + modules[case_id] + '_case')
    assertions = getattr(module, 'verify_' + case_id.lower())(before, after, **oracle_parameters)
    assert all(assertions.values()), assertions
    plan = json.loads((root / 'expansion-plan.json').read_text())
    plan.pop('sha256')
    old = TransactionStore(root / 'broker/state').load_preview('tx1-00000000000000000001').artifact
    old = deepcopy(old)
    old['request'] = artifact['request']
    old['prepared_operation'].update(artifact['prepared_operation'])
    artifact = old
    for guard in ('project_guard', 'runtime_guard'):
        artifact[guard]['version'] = version
        artifact[guard]['fingerprint'] = canonical_digest({k: v for k, v in artifact[guard].items() if k not in {'contract', 'fingerprint'}})
    ask = case_id in {'C01', 'C03'}
    state = 'result_schema_checked' if case_id == 'C08' else 'verified'
    binary, auth = root / 'fake-codex', root / 'fake-auth'
    binary.write_bytes(b'fake independent CLI')
    auth.write_text('{}')
    options = SimpleNamespace(codex_binary=binary, auth_json=auth, windows_powershell_core_host=None)
    prompts = ['Perform this requested workflow.'] + (['Confirm this exact Preview.'] if ask else [])
    unit = 'EXP' + version[2:4] + '-' + case_id
    plan.update(unit_id=unit, version=version, operation=artifact['request']['operation'],
        request_schema_uri='ak.wwise.core.object.setAttenuationCurve' if case_id == 'C08' else None,
        before=before, policy='ask_before_changes' if ask else 'allow_changes', prompts=prompts,
        required_assertions=sorted(getattr(module, case_id + '_ASSERTIONS')),
        oracle_parameters=oracle_parameters, preview_parameters=parameters,
        notice_adjudication={'configuration': review.reviewer_configuration(CONTRACT), 'runtime': review.reviewer_runtime_identity(options)})
    digest = canonical_digest(plan)
    _write(root / 'expansion-plan.json', {**plan, 'sha256': digest})
    shutil.rmtree(root / 'broker/state')  # only the disposable fixture above
    store = TransactionStore(root / 'broker/state')
    tx = 'tx1-00000000000000000001'
    preview = store.create_preview(tx, artifact)
    token = None
    if ask:
        awaiting = store.submit_for_confirmation(tx)
        token = confirmation_token_for(transaction_id=tx, artifact_hash=preview.artifact_hash,
            state='awaiting_confirmation', event_sequence=awaiting.event_sequence, last_event_hash=awaiting.last_event_hash)
        store.confirm(tx, confirmation_token=token)
    else:
        store.authorize_by_policy(tx, policy='allow_changes', authority='caller_asserted_current_user_change_request')
    store.begin_execution(tx, expected_authorization='confirmed' if ask else 'policy_authorized')
    store.mark_executed_unverified(tx)
    store.record_verification(tx, outcome=state)
    artifact_hash = canonical_digest(artifact)
    oracle = json.loads((root / 'expansion-oracle.json').read_text())
    oracle.update(before=before, after=after, preview_before=before, preview_after=before, assertions=assertions,
        artifact_hash=artifact_hash, gateway_verification_state=state, authorization={'mode': 'explicit_confirmation' if ask else 'policy_authorization',
            'explicit_confirmation': ask, 'authority': 'caller_asserted_current_user_change_request'})
    oracle['permit'].update(artifact_sha256=artifact_hash, authorized_turn=2 if ask else 1)
    _write(root / 'expansion-oracle.json', oracle)
    original = json.loads((root / 'expansion-broker.json').read_text())['records']
    args = [['draft-start', plan['request_schema_uri'] or plan['operation']],
        ['preview-from-draft', 'draft', '--task-authority', 'auth', '--expected-revision', '1']]
    if ask: args.append(['confirm', tx, '--confirmation-token', token])
    args += [['execute', tx], ['verify', tx]]
    records, turn_events = [], []
    skill = root / 'turns/turn-01/events.jsonl'
    initial = [json.loads(line) for line in skill.read_text().splitlines()][:4]
    for turn_index in range(2 if ask else 1):
        turn_events.append(deepcopy(initial) if turn_index == 0 else [
            {'type': 'thread.started', 'thread_id': 'thread'}, {'type': 'turn.started'}])
    for index, argv in enumerate(args, 1):
        template = deepcopy(original[0 if argv[0] == 'draft-start' else 1 if argv[0] == 'preview-from-draft' else 2 if argv[0] in {'execute', 'confirm'} else 3])
        model = ['python', plan['skill_source'] + '/scripts/run.py', 'gateway.py', *argv]
        semantic = ['runner-owned-version', version, *argv]
        if '--expected-revision' in argv: semantic[-1] = 1
        payload = template['payload']
        payload['command'] = argv[0]
        if argv[0] != 'draft-start': payload.update(transaction_id=tx, artifact_hash=artifact_hash)
        if argv[0] == 'verify': payload['state'] = state
        elif argv[0] == 'confirm': payload['state'] = 'confirmed'
        template.update(sequence=index, step_name=f'expansion.step.{index:04d}', model_argv=model, normalized_model_argv=model,
            gateway_arguments=argv, raw_argv_sha256=canonical_digest(model), argv_sha256=canonical_digest(model),
            semantic_argv_sha256=canonical_digest(semantic), payload_sha256=canonical_digest(payload), stdout=json.dumps(payload),
            runner_command_sha256=canonical_digest([plan['trusted_python'], plan['skill_source'] + '/scripts/run.py', 'gateway.py', *argv]))
        records.append(template)
        command = {'id': 'cmd-' + str(index), 'type': 'command_execution', 'command': shlex.join(model),
            'status': 'completed', 'exit_code': 0, 'aggregated_output': template['stdout']}
        events = turn_events[1 if ask and index > 2 else 0]
        events.extend([{'type': 'item.started', 'item': {**command, 'status': 'in_progress'}}, {'type': 'item.completed', 'item': command}])
        if argv[0] == 'preview-from-draft':
            events.append({'type': 'item.completed', 'item': {'id': 'preview-notice', 'type': 'agent_message', 'text': notice}})
    for events in turn_events:
        events += [{'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Done.'}}, {'type': 'turn.completed'}]
    for index, events in enumerate(turn_events, 1):
        directory = root / f'turns/turn-{index:02d}'
        directory.mkdir(parents=True, exist_ok=True)
        commands = completed_command_records(events, platform_name='posix')
        facts = json.loads((root / 'turns/turn-01/codex-facts.json').read_text())
        facts['command_facts']['command_records'] = [asdict(row) for row in commands]
        _write(directory / 'codex-facts.json', facts)
        (directory / 'events.jsonl').write_text('\n'.join(json.dumps(row) for row in events))
        (directory / 'prompt.txt').write_text(prompts[index - 1] + '\n')
        (directory / 'final.txt').write_text('Done.\n')
        (directory / 'stderr.txt').write_text('')
        grade = json.loads((root / 'turns/turn-01/turn-grade.json').read_text())
        grade.update(index=index, prompt_sha256=hashlib.sha256(prompts[index - 1].encode()).hexdigest(), broker_prefix_count=2 if ask and index == 1 else len(records))
        _write(directory / 'turn-grade.json', grade)
    names = [row['step_name'] for row in records]
    _write(root / 'expansion-broker.json', {'records': records, 'passed': True, 'complete': True,
        'expected_step_names': names, 'consumed_step_names': names})
    def process(command, **kwargs):
        if command[1:] == ['features', 'list']: return BoundedProcessResult(0, '\n'.join(review.DISABLED_FEATURES), '', .01)
        if command[1:] == ['exec', '--help']: return BoundedProcessResult(0, '--output-schema --ephemeral --ignore-user-config --ignore-rules --sandbox', '', .01)
        if 'prompt-input' in command: return BoundedProcessResult(0, json.dumps([{'role': 'developer', 'content': review.reviewer_rubric(CONTRACT)}]), '', .01)
        payload = json.loads(command[-1])
        judgment = grounded_judgment(payload)
        if damage == 'uncertain':
            judgment['outcome'] = 'review_required'
            judgment['obligations'][0]['status'] = 'unresolved'
        elif damage == 'wrong':
            judgment['outcome'] = 'material_reject'
            judgment['obligations'][0]['status'] = 'contradicted'
        if damage == 'timeout': return BoundedProcessResult(124, '', 'isolated reviewer deadline', .01, timed_out=True)
        if damage == 'malformed': judgment = {'outcome': 'accepted'}
        output = [{'type': 'thread.started', 'thread_id': 'independent'}, {'type': 'turn.started'},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(judgment)}},
            {'type': 'turn.completed', 'usage': {'input_tokens': 10, 'output_tokens': 10}}]
        return BoundedProcessResult(0, '\n'.join(json.dumps(row) for row in output), '', .01)
    monkeypatch.setattr(review, 'run_process', process)
    directory = root / 'turns/turn-01'
    events = turn_events[0]
    graded = grade_expansion_notice(SimpleNamespace(stdout=(directory / 'events.jsonl').read_text()),
        completed_command_records(events, platform_name='posix'), case_id=case_id, version=version,
        execute_expected=not ask, preview_artifact=artifact, before_snapshot=before, preview_parameters=parameters,
        transaction_id=tx, user_prompt=prompts[0], other_gates={'policy_checkpoint': True}, root=directory, options=options)
    if text is None:
        assert graded['decision']['outcome'] == 'review_required', graded['decision']
    assert graded['passed'] is (damage is None), graded
    turns = []
    for index in range(1, len(turn_events) + 1):
        grade = json.loads((root / f'turns/turn-{index:02d}/turn-grade.json').read_text())
        if index == 1:
            grade['common_gates']['visible_preview_notice'] = graded['passed']
            grade['passed'] = graded['passed']
            grade['errors'] = [] if graded['passed'] else ['visible_preview_notice']
            _write(root / f'turns/turn-{index:02d}/turn-grade.json', grade)
        turns.append({'index': index, 'gates': grade['common_gates'], 'agent_seconds': 12,
            **({'notice_invocation_binding_sha256': graded['invocation_binding_sha256']} if index == 1 else {})})
    _write(root / 'expansion-agent-budget.json', {'hard_seconds': 600, 'slow_seconds': 420, 'elapsed_seconds': 12 * len(turns),
        'slow': False, 'turns': turns, 'turn_measurements': [{'started_monotonic': 100 + 12*i,
            'finished_monotonic': 112 + 12*i, 'elapsed_seconds': 12} for i in range(len(turns))]})
    _write(root / 'expansion-task-result.json', {'unit_id': unit, 'version': version, 'passed': graded['passed'],
        'thread_id': 'thread', 'plan_sha256': digest, 'assertions': assertions, 'agent_seconds': 12 * len(turns),
        'slow': False, 'turns': turns, 'gateway_verification_state': state})
    return unit


@pytest.mark.parametrize('case_id,version', [(case, version) for version in ('2022.1', '2025.1')
    for case in ('C01', 'C03', 'C06', 'C08', 'C09', 'M01', 'M05') if (case, version) != ('M05', '2022.1')])
def test_each_workflow_full_archive_replays_sealed_review_without_model(tmp_path, monkeypatch, case_id, version):
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive
    from tests.semantic.support import codex_c09_notice_adjudication as review
    unit = sealed_workflow(tmp_path, monkeypatch, case_id, version)
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('model replay')))
    before = {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    archived = verify_expansion_task_archive(tmp_path, expected_unit_id=unit, expected_version=version, expected_inputs_sha256='a' * 64)
    assert archived['business_pass'] is True
    assert archived['turn_count'] == (2 if case_id in {'C01', 'C03'} else 1)
    assert before == {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}


_CONTRASTS = json.loads((Path(__file__).parents[1] /
    'fixtures/semantic/expansion-notice-independent-contrasts-v1.json').read_text())['contrasts'][:12]


def instantiate_contrast(contrast):
    """Resolve independent observer placeholders through the sealed case roles."""
    import re
    case = contrast['case']
    artifact, before, _, parameters, _, _ = case_facts(case)
    if case == 'C01':
        tokens = {'V': before['sound']['id'], 'J': before['sources']['Japanese']['object']['id'],
            'E': before['sources']['English(US)']['object']['id'], 'EV': before['event']['id'],
            'D': before['distractor']['id'], 'VF': parameters['replacement']}
    elif case == 'C03':
        rows = list(before['sounds'].values())
        tokens = {'L': rows[0]['object']['id'], 'R': rows[1]['object']['id'],
            'LF': '/replacement/left/Hit.wav', 'RF': '/replacement/right/Hit.wav',
            'LD': rows[0]['media']['path'], 'RD': rows[1]['media']['path'], 'D': before['distractor']['id']}
    elif case == 'C06':
        tokens = {'O': before['owner']['id'], 'RC': parameters['control_id'], 'T': parameters['target_id'],
            'PT': next(key for key in before['rtpcs'] if key != parameters['target_id'])}
    elif case == 'C08':
        points = parameters['expected_points']
        tokens = {'A': before['attenuation']['id'], 'AS': before['source']['object']['id'],
            'U': next(iter(before['users'])), 's': str(points[0]['x']), 'm': str(points[1]['x']), 'e': str(points[2]['x'])}
    elif case == 'M01':
        tokens = {'P': before['parent']['id'], 'K': before['protected']['id'],
            'QF': parameters['media']['Quiet'], 'FF': parameters['media']['Full']}
    else:
        tokens = {'S': before['stinger']['id'], 'O': before['owner']['id'], 'B': before['stinger']['@Trigger']['id'],
            'N': before['target']['name'] + '（' + before['target']['id'] + '）', 'MS': before['segment']['id'],
            'PS': before['protected']['stinger']['id'], 'PO': before['protected']['owner']['id']}
    return re.sub(r'(?<![A-Za-z])(' + '|'.join(sorted(tokens, key=len, reverse=True)) + r')(?![A-Za-z])',
        lambda match: tokens[match.group()], contrast['notice'])


@pytest.mark.parametrize('contrast', _CONTRASTS, ids=lambda row: row['id'])
def test_independent_heldout_business_meanings_survive_runner_and_archive(tmp_path, monkeypatch, contrast):
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive
    from tests.semantic.support import codex_c09_notice_adjudication as review
    wrong = contrast['id'].endswith('-wrong')
    unit = sealed_workflow(tmp_path, monkeypatch, contrast['case'], damage='wrong' if wrong else None,
        text=instantiate_contrast(contrast))
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('model replay')))
    replayed = verify_expansion_task_archive(tmp_path, expected_unit_id=unit,
        expected_version='2025.1', expected_inputs_sha256='a' * 64)
    assert replayed['business_pass'] is (not wrong)
    assert replayed['original_status'] == ('FAIL' if wrong else 'PASS')


@pytest.mark.parametrize('case_id', ['C01', 'C03', 'C06', 'C08', 'M01', 'M05'])
def test_uncertain_notice_judgment_stays_a_valid_failed_archive(tmp_path, monkeypatch, case_id):
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive
    from tests.semantic.support import codex_c09_notice_adjudication as review
    unit = sealed_workflow(tmp_path, monkeypatch, case_id, damage='uncertain')
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('model replay')))
    replayed = verify_expansion_task_archive(tmp_path, expected_unit_id=unit,
        expected_version='2025.1', expected_inputs_sha256='a' * 64)
    assert replayed['archive_valid'] is True
    assert replayed['business_pass'] is False


def test_2022_stinger_remains_a_boundary_even_with_visible_notice():
    from tests.semantic.support.codex_expansion_notice_adjudication import decide_expansion_notice
    case = historical_case('M05')
    result, commands = timeline('只改现有 Stinger 的 Trigger。', version='2022.1')
    decision = decide_expansion_notice(result, commands, case_id='M05', version='2022.1', execute_expected=True,
        preview_artifact=case['artifact'], before_snapshot=case['before'], preview_parameters={'version': '2022.1'})
    assert decision == {'outcome': 'material_reject', 'reason': 'workflow-version-policy-boundary'}


@pytest.mark.parametrize('case_id', ['C01', 'C03', 'M01'])
def test_import_prepared_source_or_parent_role_mismatch_never_enters_review(case_id):
    from tests.semantic.support.codex_expansion_notice_adjudication import decide_expansion_notice
    case = import_case(case_id)
    prepared = case['artifact']['prepared_operation']
    target = prepared['verification_plan']['targets'][0]
    foreign = '{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}'
    if case_id == 'C01': target['localized_source_snapshot']['rows'][0]['id'] = foreign
    elif case_id == 'C03': target['existing_sfx_source_snapshot']['rows'][0]['parent']['id'] = foreign
    else: prepared['resolved_roles']['targets[0].anchor']['object'] = foreign
    result, commands = timeline(case['unsupported_notice'], ask=case_id != 'M01')
    decision = decide_expansion_notice(result, commands, case_id=case_id, version='2025.1', execute_expected=case_id == 'M01',
        preview_artifact=case['artifact'], before_snapshot=case['before'], preview_parameters=case['parameters'])
    assert decision['outcome'] == 'material_reject'


@pytest.mark.parametrize('case_id', ['C01', 'C03', 'C06', 'C08', 'M01', 'M05'])
def test_missing_notice_and_failed_hard_gate_cannot_use_reviewer(case_id, tmp_path, monkeypatch):
    from tests.semantic.support.codex_expansion_notice_adjudication import grade_expansion_notice
    from tests.semantic.support import codex_c09_notice_adjudication as review
    artifact, before, _, parameters, _, notice = case_facts(case_id)
    ask = case_id in {'C01', 'C03'}
    result, commands = timeline('', ask=ask)
    kwargs = dict(case_id=case_id, version='2025.1', execute_expected=not ask,
        preview_artifact=artifact, before_snapshot=before, preview_parameters=parameters)
    monkeypatch.setattr(review, 'review_c09_notice', lambda *a, **k: (_ for _ in ()).throw(AssertionError('review cannot rescue')))
    empty = grade_expansion_notice(result, commands, other_gates={'policy_checkpoint': True},
        root=tmp_path / 'missing', options=None, **kwargs)
    assert empty['passed'] is False and empty['decision']['outcome'] == 'material_reject'
    result, commands = timeline(notice, ask=ask)
    failed = grade_expansion_notice(result, commands, other_gates={'policy_checkpoint': False},
        root=tmp_path / 'hard-failure', options=None, **kwargs)
    assert failed['passed'] is False and failed['receipt'] is None


@pytest.mark.parametrize('case_id', ['C01', 'C03', 'C06', 'C08', 'M01', 'M05'])
def test_each_workflow_archive_rejects_resealed_notice_or_receipt_substitution(tmp_path, monkeypatch, case_id):
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive, ExpansionArchiveError
    from tests.semantic.support.codex_expansion_policy import canonical_digest
    from tests.semantic.support import codex_c09_notice_adjudication as review
    unit = sealed_workflow(tmp_path, monkeypatch, case_id)
    path = tmp_path / 'turns/turn-01/notice-review/receipt.json'
    receipt = json.loads(path.read_text())
    receipt['input']['attested_roles']['quantity'] = 99
    receipt['sha256'] = canonical_digest({key: value for key, value in receipt.items() if key != 'sha256'})
    path.write_text(json.dumps(receipt))
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('model replay')))
    with pytest.raises(ExpansionArchiveError, match='binding'):
        verify_expansion_task_archive(tmp_path, expected_unit_id=unit, expected_version='2025.1', expected_inputs_sha256='a' * 64)


@pytest.mark.parametrize('case_id', ['C01', 'C03', 'C06', 'M01'])
def test_accepted_notice_cannot_supply_later_confirmation_or_durable_grant(tmp_path, monkeypatch, case_id):
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive, ExpansionArchiveError
    unit = sealed_workflow(tmp_path, monkeypatch, case_id)
    path = tmp_path / 'expansion-oracle.json'
    oracle = json.loads(path.read_text())
    if case_id in {'C01', 'C03'}: oracle['permit']['authorized_turn'] = 1
    else: oracle['authorization'] = None
    path.write_text(json.dumps(oracle))
    with pytest.raises(ExpansionArchiveError, match='authorization'):
        verify_expansion_task_archive(tmp_path, expected_unit_id=unit, expected_version='2025.1', expected_inputs_sha256='a' * 64)


@pytest.mark.parametrize('damage', ['timeout', 'malformed'])
def test_new_music_reviewer_infrastructure_failures_preserve_valid_failed_archive(tmp_path, monkeypatch, damage):
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive
    from tests.semantic.support import codex_c09_notice_adjudication as review
    unit = sealed_workflow(tmp_path, monkeypatch, 'M01', damage=damage)
    receipt = json.loads((tmp_path / 'turns/turn-01/notice-review/receipt.json').read_text())
    assert receipt['error'] is not None and receipt['judgment'] is None
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('model replay')))
    assert verify_expansion_task_archive(tmp_path, expected_unit_id=unit,
        expected_version='2025.1', expected_inputs_sha256='a' * 64)['business_pass'] is False
