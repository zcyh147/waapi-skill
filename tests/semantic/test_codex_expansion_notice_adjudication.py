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


def test_reimport_notice_requires_business_mappings_without_unchanged_native_defaults():
    from tests.semantic.support.codex_expansion_notice_adjudication import decide_expansion_notice
    case = import_case('C03')
    result, commands = timeline('将按上述完整路径分别重新导入现有 Left、Right；声音与来源身份和 Originals 位置、音量及路由保持，等你确认。', ask=True)
    decision = decide_expansion_notice(result, commands, case_id='C03', version='2025.1', execute_expected=False,
        preview_artifact=case['artifact'], before_snapshot=case['before'], preview_parameters=case['parameters'], adjudication_contract='waapi-skill.expansion-notice-adjudication/v2')
    assert decision['input']['contract'] == 'waapi-skill.expansion-notice-adjudication/v2'
    obligations = decision['input']['notice_obligations']
    assert obligations['action'] == 'reimport-existing-media'
    assert [row['source_file'] for row in obligations['mappings']] == ['/replacement/left/Hit.wav', '/replacement/right/Hit.wav']
    assert [row['destination']['name'] for row in obligations['mappings']] == ['Left', 'Right']
    assert not any('language' in row or 'field_owner' in row for row in obligations['mappings'])
    # Complete truth remains available to reject affirmative false claims.
    assert decision['input']['attested_roles']['mappings'][0]['language'] == 'SFX'
    assert decision['input']['attested_roles']['mappings'][0]['field_owner'] == 'Sound SFX'


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
    from tests.semantic.support.codex_expansion_archive import replay_c09_notice, _scope
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
        user_prompt=plan['prompts'][0], read_admission=_scope(plan),
        broker_records=json.loads((tmp_path / 'expansion-broker.json').read_text())['records'])
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


@pytest.mark.parametrize('case_id', ['C01', 'C06', 'C08', 'C09', 'M01', 'M05'])
def test_notice_obligations_keep_changed_business_meaning_and_contextual_facts_distinct(case_id):
    from tests.semantic.support.codex_expansion_notice_adjudication import decide_expansion_notice
    artifact, before, _, parameters, _, notice = case_facts(case_id)
    result, commands = timeline(notice, ask=case_id == 'C01')
    decision = decide_expansion_notice(result, commands, case_id=case_id, version='2025.1',
        execute_expected=case_id != 'C01', preview_artifact=artifact, before_snapshot=before,
        preview_parameters=parameters, user_prompt='Explicit original business request.',
        adjudication_contract='waapi-skill.expansion-notice-adjudication/v2')
    obligations = decision['input']['notice_obligations']
    assert obligations['preserve'] == decision['input']['attested_roles']['preserve']
    assert 'before_snapshot' not in obligations and 'topology' not in obligations
    if case_id == 'C01':
        assert obligations['selected_language'] == 'Japanese'
        assert obligations['import_kind'] == 'Sound Voice'
        assert obligations['mappings'][0]['destination']['type'] == 'Sound'
        assert obligations['preserve_existing_sound_and_source_identity'] is True
        assert 'English(US) media and association' in obligations['preserve']
    elif case_id == 'C06':
        assert obligations['action'] == 'update-existing-RTPC'
        assert obligations['property'] == 'Volume'
        assert obligations['points'] == [{'x': 0, 'y': -48, 'shape': 'Linear'},
            {'x': 50, 'y': -6, 'shape': 'Linear'}, {'x': 100, 'y': 0, 'shape': 'Linear'}]
        assert obligations['control_input']['name'] == 'Rain_Intensity'
        assert obligations['axis_meaning'] == {'x': 'GameParameter value', 'y': 'decibels'}
        assert 'old' not in obligations and 'delta' not in obligations
    elif case_id == 'C08':
        assert obligations['curve_kind'] == 'volume-dry'
        assert obligations['curve_source'] == 'custom'
        assert obligations['points'][1] == {'x': 50, 'y': -12, 'shape': 'Linear'}
        assert obligations['gateway_verification'] == 'result_schema'
        assert obligations['axis_meaning']['x'] == 'distance in the sealed project domain'
        assert 'before_curve' not in obligations
    elif case_id == 'C09':
        assert obligations['effect_count'] == 1
        assert obligations['effect'] == artifact['prepared_operation']['verification_plan']['descriptor']
        assert 'protected_effect_count' not in obligations
    elif case_id == 'M01':
        assert obligations['segment_count'] == 1 and obligations['track_count'] == 2 and obligations['media_count'] == 2
        assert obligations['segment']['type'] == 'MusicSegment'
        assert [row['destination']['type'] for row in obligations['mappings']] == ['MusicTrack', 'MusicTrack']
        assert [row['source_file'] for row in obligations['mappings']] == ['/replacement/Quiet.wav', '/replacement/Full.wav']
        assert obligations['mappings'][0]['properties'] == [{'name': 'Volume', 'value': -6}]
        assert obligations['volume_owner'] == 'MusicTrack' and obligations['volume_unit'] == 'decibels'
        assert 'quantity' not in obligations and 'AudioFileSource' not in json.dumps(obligations)
    else:
        assert obligations['action'] == 'update-existing-reference'
        assert obligations['field'] == 'Trigger'
        assert obligations['destination']['type'] == 'Trigger'
        assert obligations['preserved_segment']['type'] == 'MusicSegment'
        assert 'before_reference' not in obligations and 'siblings' not in obligations


def test_prospective_rubric_uses_business_obligations_and_preserves_legacy_text():
    import hashlib
    from tests.semantic.support.codex_c09_notice_adjudication import reviewer_rubric, reviewer_configuration
    from tests.semantic.support.codex_expansion_notice_adjudication import BUSINESS_CONTRACT as CONTRACT, LEGACY_CONTRACT
    old = reviewer_rubric(LEGACY_CONTRACT)
    new = reviewer_rubric(CONTRACT)
    assert 'use the attested_roles as obligations' in old
    # Independently captured from the source-only 8550bdd/v1 rubric.
    assert hashlib.sha256(old.encode()).hexdigest() == 'd304d0d46e3fd3c4cc85e002745227dba6c77eb1c1b9fb03a672f91fe5600172'
    assert 'use notice_obligations for required business meaning' in new
    assert 'use the attested_roles as obligations' not in new
    assert 'Sealed facts cannot supply missing visible intent' in new
    assert 'Japanese' in new and 'unchanged SFX' in new
    assert 'AudioFileSource/sequence/clip' in new and 'result-schema-only' in new
    assert reviewer_configuration(CONTRACT)['rubric_sha256'] != reviewer_configuration(LEGACY_CONTRACT)['rubric_sha256']


@pytest.mark.parametrize('case_id', ['C03', 'C06', 'M01'])
def test_exact_pre_execution_witness_produces_business_obligations_without_regrading_history(case_id):
    """Actual sealed producer facts, no outcomes; synthetic route timeline only."""
    import hashlib
    from tests.semantic.support.codex_expansion_notice_adjudication import decide_expansion_notice, LEGACY_CONTRACT
    from tests.semantic.support.codex_expansion_policy import canonical_digest
    directory = Path(__file__).parents[1] / 'fixtures/semantic/notice-obligations-8550bdd'
    provenance = json.loads((directory / 'provenance.json').read_text())
    entry = next(row for row in provenance['rows'] if row['case'] == case_id)
    raw = (directory / entry['copied_input']).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == entry['copied_input_sha256']
    witness = json.loads(raw)
    assert not {'after_snapshot', 'outcome', 'judgment', 'business_pass'} & witness.keys()
    roles, version = witness['attested_roles'], witness['version']
    parameters = {'version': version}
    if case_id == 'C03':
        parameters.update(mappings={row['destination']['path']: row['source_file'] for row in roles['mappings']},
            target_ids={row['destination']['path']: row['destination']['id'] for row in roles['mappings']})
    elif case_id == 'C06':
        plan = witness['prepared_operation']['verification_plan']
        parameters.update(owner_id=plan['object_id'], control_id=plan['control_input_id'],
            target_id=plan['existing_rtpc_id'], expected_notes=roles['association']['notes'])
    else:
        parameters.update(parent_path=roles['target']['path'], segment_name='Imported',
            media={row['destination']['path'].rsplit('\\', 1)[-1]: row['source_file']
                for row in roles['mappings'] if row['source_file'] is not None})
    # Preserve the exact visible message text/positions, without copying the
    # source's command outcomes or any post-execution campaign state.
    positions = [row['event_position'] for row in witness['visible_messages']]
    end = witness['execute_event_position'] or max(positions) + 1
    events = [{'type': 'fixture.placeholder'} for _ in range(end + (case_id != 'C03'))]
    for row in witness['visible_messages']:
        events[row['event_position']] = {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': row['text']}}
    events[witness['preview_event_position']] = {'type': 'item.completed',
        'item': {'type': 'command_execution', 'command': 'preview'}}
    if case_id != 'C03':
        events[end] = {'type': 'item.started', 'item': {'type': 'command_execution', 'command': 'execute'}}
    _, commands = timeline('', version=version, ask=case_id == 'C03')
    result = SimpleNamespace(stdout='\n'.join(json.dumps(row, ensure_ascii=False) for row in events))
    kwargs = dict(case_id=case_id, version=version, execute_expected=case_id != 'C03',
        preview_artifact={'transaction_id': witness['transaction_id'], 'request': witness['immutable_request'],
            'prepared_operation': witness['prepared_operation']}, before_snapshot=witness['before_snapshot'],
        preview_parameters=parameters, user_prompt=witness['user_prompt'], transaction_id=witness['transaction_id'])
    legacy = decide_expansion_notice(result, commands, adjudication_contract=LEGACY_CONTRACT, **kwargs)
    current = decide_expansion_notice(result, commands, **kwargs)
    assert legacy['outcome'] == current['outcome'] == 'review_required'
    assert canonical_digest(current['input']['attested_roles']) == canonical_digest(roles)
    assert current['input']['visible_messages'] == witness['visible_messages']
    assert current['input']['user_prompt'] == witness['user_prompt']
    assert current['input']['notice_obligations']['action'] == {
        'C03': 'reimport-existing-media', 'C06': 'update-existing-RTPC', 'M01': 'import-new-music-media'}[case_id]
    assert 'notice_obligations' not in legacy['input']
    assert (directory / entry['copied_input']).read_bytes() == raw


def sealed_workflow(root, monkeypatch, case_id, version='2025.1', *, damage=None, text=None, transaction_id=None,
        adjudication_contract=None, user_prompt=None, public_reads=()):
    """Complete real-TransactionStore fixture through runner grade and archive."""
    import hashlib
    import importlib
    import shlex
    import shutil
    from copy import deepcopy
    from dataclasses import asdict
    from tests.semantic.test_codex_expansion_archive import _sealed_c08, _write
    from tests.semantic.support.codex_expansion_archive import _scope
    from tests.semantic.support.codex_expansion_policy import canonical_digest
    from tests.semantic.support.codex_harness import completed_command_records, BoundedProcessResult
    from tests.semantic.support import codex_c09_notice_adjudication as review
    from tests.semantic.support.codex_expansion_notice_adjudication import grade_expansion_notice, CONTRACT
    CONTRACT = adjudication_contract or CONTRACT
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
    prompts = [user_prompt or 'Perform this requested workflow.'] + (['Confirm this exact Preview.'] if ask else [])
    unit = 'EXP' + version[2:4] + '-' + case_id
    plan.update(unit_id=unit, version=version, operation=artifact['request']['operation'],
        request_schema_uri='ak.wwise.core.object.setAttenuationCurve' if case_id == 'C08' else None,
        before=before, policy='ask_before_changes' if ask else 'allow_changes', prompts=prompts,
        required_assertions=sorted(getattr(module, case_id + '_ASSERTIONS')),
        oracle_parameters=oracle_parameters, preview_parameters=parameters,
        notice_adjudication={'configuration': review.reviewer_configuration(CONTRACT), 'runtime': review.reviewer_runtime_identity(options)})
    if public_reads:
        from tests.semantic.support.codex_expansion_policy import ExpansionReadScope
        read_ids = {argv[argv.index('--exact-id') + 1] for argv, _ in public_reads if '--exact-id' in argv}
        scope = ExpansionReadScope(frozenset(set(plan['read_scope']['object_ids']) | read_ids),
            frozenset({plan['operation']}), owned_project_reads=True, max_rows=100)
        plan['read_scope'] = {key: sorted(value) if isinstance(value, frozenset) else value
            for key, value in asdict(scope).items()}
        plan['read_scope_sha256'] = scope.digest
    digest = canonical_digest(plan)
    _write(root / 'expansion-plan.json', {**plan, 'sha256': digest})
    shutil.rmtree(root / 'broker/state')  # only the disposable fixture above
    store = TransactionStore(root / 'broker/state')
    tx = transaction_id or 'tx1-00000000000000000001'
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
    oracle.update(transaction_id=tx, before=before, after=after, preview_before=before, preview_after=before, assertions=assertions,
        artifact_hash=artifact_hash, gateway_verification_state=state, authorization={'mode': 'explicit_confirmation' if ask else 'policy_authorization',
            'explicit_confirmation': ask, 'authority': 'caller_asserted_current_user_change_request'})
    oracle['permit'].update(transaction_id=tx, artifact_sha256=artifact_hash, authorized_turn=2 if ask else 1)
    _write(root / 'expansion-oracle.json', oracle)
    original = json.loads((root / 'expansion-broker.json').read_text())['records']
    args = [list(argv) for argv, _ in public_reads] + [['draft-start', plan['request_schema_uri'] or plan['operation']],
        ['preview-from-draft', 'draft', '--task-authority', 'auth', '--expected-revision', '1']]
    preview_index = len(args)
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
        payload = deepcopy(public_reads[index - 1][1]) if index <= len(public_reads) else template['payload']
        template['payload'] = payload
        payload['command'] = argv[0]
        if argv[0] not in {'draft-start', 'query-object', 'metadata', 'query-schema'}: payload.update(transaction_id=tx, artifact_hash=artifact_hash)
        if argv[0] == 'verify': payload['state'] = state
        elif argv[0] == 'confirm': payload['state'] = 'confirmed'
        template.update(sequence=index, step_name=f'expansion.step.{index:04d}', model_argv=model, normalized_model_argv=model,
            gateway_arguments=argv, raw_argv_sha256=canonical_digest(model), argv_sha256=canonical_digest(model),
            semantic_argv_sha256=canonical_digest(semantic), payload_sha256=canonical_digest(payload), stdout=json.dumps(payload),
            runner_command_sha256=canonical_digest([plan['trusted_python'], plan['skill_source'] + '/scripts/run.py', 'gateway.py', *argv]))
        records.append(template)
        command = {'id': 'cmd-' + str(index), 'type': 'command_execution', 'command': shlex.join(model),
            'status': 'completed', 'exit_code': 0, 'aggregated_output': template['stdout']}
        events = turn_events[1 if ask and index > preview_index else 0]
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
        grade.update(index=index, prompt_sha256=hashlib.sha256(prompts[index - 1].encode()).hexdigest(), broker_prefix_count=preview_index if ask and index == 1 else len(records))
        _write(directory / 'turn-grade.json', grade)
    names = [row['step_name'] for row in records]
    _write(root / 'expansion-broker.json', {'records': records, 'passed': True, 'complete': True,
        'expected_step_names': names, 'consumed_step_names': names})
    def process(command, **kwargs):
        if command[1:] == ['features', 'list']: return BoundedProcessResult(0, '\n'.join(review.DISABLED_FEATURES), '', .01)
        if command[1:] == ['exec', '--help']: return BoundedProcessResult(0, '--output-schema --ephemeral --ignore-user-config --ignore-rules --sandbox', '', .01)
        if 'prompt-input' in command: return BoundedProcessResult(0, json.dumps([{'role': 'developer', 'content': review.reviewer_rubric(CONTRACT)}]), '', .01)
        payload = json.loads(command[-1])
        assert payload['contract'] == CONTRACT
        assert ('notice_obligations' in payload) is (not CONTRACT.endswith('/v1'))
        assert payload['user_prompt'] == prompts[0]
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
        transaction_id=tx, user_prompt=prompts[0], adjudication_contract=CONTRACT,
        broker_records=records, read_admission=_scope(plan),
        other_gates={'policy_checkpoint': True}, root=directory, options=options)
    if text is None:
        assert graded['decision']['outcome'] == ('material_reject' if damage == 'unattested_role' else 'review_required'), graded['decision']
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


@pytest.mark.parametrize('contract', ['waapi-skill.expansion-notice-adjudication/v1',
    'waapi-skill.expansion-notice-adjudication/v2', 'waapi-skill.expansion-notice-adjudication/v3'])
def test_full_archive_replays_exact_sealed_contract_without_upgrading_legacy_input(tmp_path, monkeypatch, contract):
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive
    from tests.semantic.support import codex_c09_notice_adjudication as review
    unit = sealed_workflow(tmp_path, monkeypatch, 'C03', adjudication_contract=contract)
    decision = json.loads((tmp_path / 'turns/turn-01/notice-decision.json').read_text())
    assert decision['input']['contract'] == contract
    assert ('notice_obligations' in decision['input']) is (not contract.endswith('/v1'))
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('model replay')))
    files = {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    replayed = verify_expansion_task_archive(tmp_path, expected_unit_id=unit,
        expected_version='2025.1', expected_inputs_sha256='a' * 64)
    assert replayed['archive_valid'] is True and replayed['business_pass'] is True
    assert files == {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}


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


_OBLIGATION_CONTRASTS = json.loads((Path(__file__).parents[1] /
    'fixtures/semantic/expansion-notice-obligation-contrasts-v2.json').read_text())['contrasts']


@pytest.mark.parametrize('contrast', _OBLIGATION_CONTRASTS, ids=lambda row: row['id'])
def test_prospective_contrast_input_and_pinned_receipt_status_survive_complete_archive(tmp_path, monkeypatch, contrast):
    """Transport/binding proof only: the fake reviewer does not grade language."""
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive
    from tests.semantic.support import codex_c09_notice_adjudication as review
    notice = instantiate_contrast(contrast)
    prompt = instantiate_contrast({**contrast, 'notice': contrast['user_prompt']})
    damage = {'sufficient': None, 'contradicted': 'wrong', 'unresolved': 'uncertain'}[contrast['expected_meaning']]
    unit = sealed_workflow(tmp_path, monkeypatch, contrast['case'], damage=damage, text=notice, user_prompt=prompt,
        adjudication_contract='waapi-skill.expansion-notice-adjudication/v2')
    decision = json.loads((tmp_path / 'turns/turn-01/notice-decision.json').read_text())
    receipt = json.loads((tmp_path / 'turns/turn-01/notice-review/receipt.json').read_text())
    assert decision['outcome'] == 'review_required'  # even complete attested facts cannot rescue empty intent
    assert receipt['input'] == decision['input']
    assert receipt['input']['user_prompt'] == prompt
    assert any(row['text'] == notice for row in receipt['input']['visible_messages'])
    obligations = receipt['input']['notice_obligations']
    assert obligations['action'] == {'C01': 'reimport-existing-media', 'C03': 'reimport-existing-media',
        'C06': 'update-existing-RTPC', 'C08': 'update-selected-attenuation-curve', 'M01': 'import-new-music-media'}[contrast['case']]
    if contrast['case'] == 'C01': assert obligations['selected_language'] == 'Japanese'
    if contrast['case'] == 'C08': assert obligations['gateway_verification'] == 'result_schema'
    if contrast['case'] == 'M01': assert obligations['media_count'] == 2 and obligations['track_count'] == 2
    assert not {'after_snapshot', 'after', 'business_pass', 'judgment'} & receipt['input'].keys()
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('model replay')))
    files = {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    archived = verify_expansion_task_archive(tmp_path, expected_unit_id=unit,
        expected_version='2025.1', expected_inputs_sha256='a' * 64)
    assert archived['archive_valid'] is True
    assert archived['business_pass'] is (damage is None)
    assert files == {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}


@pytest.mark.parametrize('tamper', ['selected-language', 'native-default-obligation', 'contract-downgrade',
    'contract-v2-downgrade', 'public-reader-substitution'])
def test_resealed_receipt_cannot_change_required_meaning_or_downgrade_new_contract(tmp_path, monkeypatch, tamper):
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive, ExpansionArchiveError
    from tests.semantic.support.codex_expansion_policy import canonical_digest
    from tests.semantic.support import codex_c09_notice_adjudication as review
    unit = sealed_workflow(tmp_path, monkeypatch, 'C01')
    path = tmp_path / 'turns/turn-01/notice-review/receipt.json'
    receipt = json.loads(path.read_text())
    if tamper == 'selected-language': receipt['input']['notice_obligations']['selected_language'] = 'English(US)'
    elif tamper == 'native-default-obligation': receipt['input']['notice_obligations']['required_native_topology'] = 'two sources'
    elif tamper == 'contract-v2-downgrade':
        receipt['input']['contract'] = 'waapi-skill.expansion-notice-adjudication/v2'
    elif tamper == 'public-reader-substitution':
        receipt['input']['verification_context']['live_availability_or_completed_read'] = 'persisted-state-proven'
    else:
        receipt['input']['contract'] = 'waapi-skill.expansion-notice-adjudication/v1'
        receipt['input'].pop('notice_obligations')
    receipt['sha256'] = canonical_digest({key: value for key, value in receipt.items() if key != 'sha256'})
    path.write_text(json.dumps(receipt))
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('model replay')))
    with pytest.raises(ExpansionArchiveError, match='binding'):
        verify_expansion_task_archive(tmp_path, expected_unit_id=unit,
            expected_version='2025.1', expected_inputs_sha256='a' * 64)


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


def test_supported_attenuation_notice_with_false_verifier_claim_requires_review_and_replays_fail(tmp_path, monkeypatch):
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive
    from tests.semantic.support import codex_c09_notice_adjudication as review
    fixture = json.loads((Path(__file__).parents[1] /
        'fixtures/semantic/expansion-attenuation-notice-c39b728-2025.json').read_text())
    supported = '\n'.join(row['item']['text'] for row in fixture['events'] if row['item']['type'] == 'agent_message')
    # Independent contrast #160: result_schema_checked does not attest actual
    # curve effect or audibility, even alongside a supported prospective plan.
    overclaim = 'Gateway 已核验，所以本次衰减曲线的实际业务效果已有 Gateway 完整证明，且听感正确。'
    unit = sealed_workflow(tmp_path, monkeypatch, 'C08', damage='wrong', text=supported + '\n' + overclaim)
    decision = json.loads((tmp_path / 'turns/turn-01/notice-decision.json').read_text())
    assert decision['outcome'] == 'review_required'
    assert (tmp_path / 'turns/turn-01/notice-review/receipt.json').is_file()
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('model replay')))
    archived = verify_expansion_task_archive(tmp_path, expected_unit_id=unit,
        expected_version='2025.1', expected_inputs_sha256='a' * 64)
    assert archived['archive_valid'] is True and archived['business_pass'] is False
    assert archived['gateway_verification_state'] == 'result_schema_checked'


@pytest.mark.parametrize('defect', ['empty', 'wrong_type', 'malformed_guid', 'aliased_guid'])
def test_attenuation_preserved_source_must_be_attested_before_review_and_failed_archive_replays(tmp_path, monkeypatch, defect):
    from copy import deepcopy
    import sys
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive
    from tests.semantic.support import codex_c09_notice_adjudication as review
    original = case_facts
    def malformed(case_id, version='2025.1'):
        artifact, before, after, parameters, oracle, notice = original(case_id, version)
        source = deepcopy(before['source']['object'])
        if defect == 'empty': source = {}
        elif defect == 'wrong_type': source['type'] = 'Sound'
        elif defect == 'malformed_guid': source['id'] = '{not-a-canonical-guid}'
        else: source['id'] = before['attenuation']['id'].lower()
        before['source']['object'] = source
        after['source']['object'] = deepcopy(source)
        return artifact, before, after, parameters, oracle, notice
    monkeypatch.setattr(sys.modules[__name__], 'case_facts', malformed)
    unit = sealed_workflow(tmp_path, monkeypatch, 'C08', damage='unattested_role')
    decision = json.loads((tmp_path / 'turns/turn-01/notice-decision.json').read_text())
    assert decision['outcome'] == 'material_reject'
    assert decision['reason'] == 'unattested-workflow-operation-or-roles'
    assert not (tmp_path / 'turns/turn-01/notice-review').exists()
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('model replay')))
    archived = verify_expansion_task_archive(tmp_path, expected_unit_id=unit,
        expected_version='2025.1', expected_inputs_sha256='a' * 64)
    assert archived['archive_valid'] is True and archived['business_pass'] is False


def supported_context_notice(case_id):
    if case_id == 'C06':
        case = historical_case(case_id)
    else:
        cases = json.loads((Path(__file__).parents[1] /
            'fixtures/semantic/expansion-current-role-notices-db2299c.json').read_text())['cases']
        case = next(row for row in cases if row['case'].endswith('EXP25-' + case_id))
    messages = [row['item']['text'] for row in case['events'] if row['item']['type'] == 'agent_message']
    return '\n'.join(messages) if case_id == 'C06' else messages[-1]


@pytest.mark.parametrize('case_id', ['C06', 'C09', 'M05'])
@pytest.mark.parametrize('false_baseline', [False, True], ids=['supported', 'false-baseline'])
def test_new_contract_reviews_complete_legacy_positive_context_and_replays_its_judgment(tmp_path, monkeypatch, case_id, false_baseline):
    from tests.semantic.support.codex_task_runner_v3 import expansion_preview_notice
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive
    from tests.semantic.support import codex_c09_notice_adjudication as review
    artifact, before, _, _, _, _ = case_facts(case_id)
    notice = supported_context_notice(case_id)
    result, commands = timeline(notice)
    # These supported contextual frames retain their original parser result;
    # the new contract cannot extend that result to all other visible claims.
    assert expansion_preview_notice(result, commands, version='2025.1', execute_expected=True,
        preview_artifact=artifact, before_snapshot=before) is True
    if false_baseline:
        notice += ('当前 Stinger 数量为 99。' if case_id == 'M05' else '当前声音音量为 -99 dB。')
    unit = sealed_workflow(tmp_path, monkeypatch, case_id,
        damage='wrong' if false_baseline else None, text=notice)
    decision = json.loads((tmp_path / 'turns/turn-01/notice-decision.json').read_text())
    assert decision['outcome'] == 'review_required'
    assert decision['reason'] == 'legacy-partial-parser-insufficient-for-complete-notice-meaning'
    assert (tmp_path / 'turns/turn-01/notice-review/receipt.json').is_file()
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('model replay')))
    archived = verify_expansion_task_archive(tmp_path, expected_unit_id=unit,
        expected_version='2025.1', expected_inputs_sha256='a' * 64)
    assert archived['business_pass'] is (not false_baseline)


def test_new_c09_retains_deterministic_material_rejection_before_complete_review(tmp_path, monkeypatch):
    from tests.semantic.support.codex_expansion_notice_adjudication import grade_expansion_notice
    from tests.semantic.support import codex_c09_notice_adjudication as review
    artifact, before, _, parameters, _, _ = case_facts('C09')
    name = artifact['request']['arguments']['plugin']['name']
    result, commands = timeline('将追加 ' + name + '，备注为“Wrong note”，现在执行。')
    monkeypatch.setattr(review, 'review_c09_notice', lambda *a, **k: (_ for _ in ()).throw(AssertionError('material rescue')))
    graded = grade_expansion_notice(result, commands, case_id='C09', version='2025.1', execute_expected=True,
        preview_artifact=artifact, before_snapshot=before, preview_parameters=parameters,
        other_gates={'policy_checkpoint': True}, root=tmp_path, options=None)
    assert graded['decision'] == {'outcome': 'material_reject', 'reason': 'explicit-descriptor-contradiction'}
    assert graded['passed'] is False and graded['receipt'] is None


@pytest.mark.parametrize('case_id', ['C06', 'C08'])
def test_v3_copied_preexecution_projection_separates_edit_intent_from_protected_facts(case_id):
    from tests.semantic.support.codex_expansion_notice_adjudication import decide_expansion_notice
    from tests.semantic.support.codex_expansion_policy import canonical_digest
    witness, kwargs, result, commands = copied_intent_witness(case_id)
    old = decide_expansion_notice(result, commands,
        adjudication_contract='waapi-skill.expansion-notice-adjudication/v2', **kwargs)
    new = decide_expansion_notice(result, commands, adjudication_contract='waapi-skill.expansion-notice-adjudication/v3', **kwargs)
    assert new['input']['contract'] == 'waapi-skill.expansion-notice-adjudication/v3'
    assert canonical_digest(old['input']['notice_obligations']) == canonical_digest(witness['notice_obligations'])
    assert canonical_digest(new['input']['attested_roles']) == canonical_digest(witness['attested_roles'])
    assert new['input']['visible_messages'] == witness['visible_messages']
    assert new['input']['user_prompt'] == witness['user_prompt']
    expected = {key: value for key, value in witness['notice_obligations'].items()
        if key not in {'preserve', 'gateway_verification'}}
    assert new['input']['notice_obligations'] == {**expected, 'preservation_intent': {
        'only_declared_changes': True, 'adopt_user_preservation_scope': True}}
    assert new['input']['attested_roles']['preserve'] == witness['attested_roles']['preserve']
    assert not {'after', 'after_snapshot', 'judgment', 'business_pass'} & new['input'].keys()
    if case_id == 'C08':
        assert new['input']['prepared_operation']['verification_plan']['kind'] == 'result-schema'
        assert new['input']['attested_roles']['gateway_verification'] == 'result_schema'
        context = new['input']['verification_context']
        assert context['public_readback_routes'] == [{'uri': 'ak.wwise.core.object.getAttenuationCurve',
            'fixed_commands': ['metadata attenuation']}]
        assert context['support_evidence'] == 'packaged-public-interface-only'
        assert context['live_availability_or_completed_read'] == 'not_attested'
        assert 'verification_context' not in old['input']


def copied_intent_witness(case_id):
    """Only copied preexecution facts; placeholders carry no command outcome."""
    import hashlib
    directory = Path(__file__).parents[1] / 'fixtures/semantic/notice-intent-71f1a09'
    stem = 'waapi-' + case_id.lower() + '-v2-preexecution-input-71f1a09'
    raw = (directory / (stem + '.json')).read_bytes()
    provenance = json.loads((directory / (stem + '.provenance.json')).read_text())
    assert hashlib.sha256(raw).hexdigest() == provenance['copied_input_sha256']
    witness = json.loads(raw)
    assert not {'after', 'after_snapshot', 'judgment', 'business_pass', 'outcome'} & witness.keys()
    plan = witness['prepared_operation']['verification_plan']
    parameters = {'version': witness['version']}
    if case_id == 'C06':
        parameters.update(owner_id=plan['object_id'], control_id=plan['control_input_id'],
            target_id=plan['existing_rtpc_id'], expected_notes=witness['attested_roles']['association']['notes'])
    else:
        parameters.update(object_id=witness['before_snapshot']['attenuation']['id'],
            expected_points=[{'x': 0.0, 'y': 0, 'shape': 'Linear'},
                {'x': 50.0, 'y': -12, 'shape': 'Linear'}, {'x': 100.0, 'y': -48, 'shape': 'Linear'}])
    events = [{'type': 'fixture.placeholder'} for _ in range(witness['execute_event_position'] + 1)]
    for row in witness['visible_messages']:
        events[row['event_position']] = {'type': 'item.completed',
            'item': {'type': 'agent_message', 'text': row['text']}}
    events[witness['preview_event_position']] = {'type': 'item.completed',
        'item': {'type': 'command_execution', 'command': 'preview'}}
    events[witness['execute_event_position']] = {'type': 'item.started',
        'item': {'type': 'command_execution', 'command': 'execute'}}
    _, commands = timeline('', version=witness['version'])
    kwargs = dict(case_id=case_id, version=witness['version'], execute_expected=True,
        preview_artifact={'transaction_id': witness['transaction_id'], 'request': witness['immutable_request'],
            'prepared_operation': witness['prepared_operation']}, before_snapshot=witness['before_snapshot'],
        preview_parameters=parameters, user_prompt=witness['user_prompt'], transaction_id=witness['transaction_id'])
    return witness, kwargs, SimpleNamespace(stdout='\n'.join(json.dumps(row, ensure_ascii=False) for row in events)), commands


def test_v3_rubric_fits_effective_instructions_and_keeps_v1_v2_fingerprints():
    import hashlib
    from tests.semantic.support.codex_c09_notice_adjudication import reviewer_rubric
    legacy_hashes = {1: 'd304d0d46e3fd3c4cc85e002745227dba6c77eb1c1b9fb03a672f91fe5600172',
        2: 'a2410a3573343e4ac2f7a26a792f610c7c83d429749677368fd7ffc7c61a95d1'}
    for version, digest in legacy_hashes.items():
        assert hashlib.sha256(reviewer_rubric('waapi-skill.expansion-notice-adjudication/v' + str(version)).encode()).hexdigest() == digest
    rubric = reviewer_rubric('waapi-skill.expansion-notice-adjudication/v3')
    assert len(rubric.encode('utf-8')) <= 2048
    assert 'Future proof uncertainty does not revoke' in rubric
    assert 'Uncertain EDIT scope' in rubric
    assert 'no unconditional pre-Execute schema-only warning' in rubric
    assert 'ALL sealed facts' in rubric
    assert 'operation/Skill/user contracts; honor explicit disclosure requests' in rubric
    assert 'Packaged support is not live availability' in rubric


@pytest.mark.parametrize('case_id', ['C06', 'C08'])
def test_v3_copied_preexecution_intent_runs_real_producer_and_readonly_archive(tmp_path, monkeypatch, case_id):
    """Copied source facts; constructed fake effect/judgment has no semantic credit."""
    import sys
    from copy import deepcopy
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive
    from tests.semantic.support import codex_c09_notice_adjudication as review
    witness, kwargs, _, _ = copied_intent_witness(case_id)
    def copied_facts(case, version):
        assert (case, version) == (case_id, witness['version'])
        before = deepcopy(witness['before_snapshot'])
        after = deepcopy(before)
        parameters = deepcopy(kwargs['preview_parameters'])
        if case_id == 'C06':
            after['rtpcs'][parameters['target_id']]['@Curve']['points'] = [
                {'x': 0, 'y': -48, 'shape': 'Linear'}, {'x': 50, 'y': -6, 'shape': 'Linear'},
                {'x': 100, 'y': 0, 'shape': 'Linear'}]
            oracle = {'target_id': parameters['target_id']}
        else:
            after['curves']['volume-dry'] = {'use': 'Custom', 'points': parameters['expected_points']}
            oracle = {'expected_points': parameters['expected_points']}
        return deepcopy(kwargs['preview_artifact']), before, after, parameters, oracle, witness['visible_messages'][-1]['text']
    monkeypatch.setattr(sys.modules[__name__], 'case_facts', copied_facts)
    unit = sealed_workflow(tmp_path, monkeypatch, case_id, witness['version'],
        transaction_id=witness['transaction_id'], user_prompt=witness['user_prompt'],
        adjudication_contract='waapi-skill.expansion-notice-adjudication/v3')
    decision = json.loads((tmp_path / 'turns/turn-01/notice-decision.json').read_text())
    receipt = json.loads((tmp_path / 'turns/turn-01/notice-review/receipt.json').read_text())
    assert receipt['input'] == decision['input']
    assert receipt['input']['contract'].endswith('/v3')
    assert receipt['input']['before_snapshot'] == witness['before_snapshot']
    assert receipt['input']['immutable_request'] == witness['immutable_request']
    assert receipt['input']['visible_messages'][-1]['text'] == witness['visible_messages'][-1]['text']
    assert receipt['input']['user_prompt'] == witness['user_prompt']
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('model replay')))
    files = {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    archived = verify_expansion_task_archive(tmp_path, expected_unit_id=unit,
        expected_version=witness['version'], expected_inputs_sha256='a' * 64)
    assert archived['archive_valid'] is True and archived['business_pass'] is True
    if case_id == 'C08': assert archived['gateway_verification_state'] == 'result_schema_checked'
    assert files == {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}


_INTENT_CONTRASTS = json.loads((Path(__file__).parents[1] /
    'fixtures/semantic/expansion-notice-intent-contrasts-v3.json').read_text())['contrasts']


@pytest.mark.parametrize('adjudication_contract', ['waapi-skill.expansion-notice-adjudication/v3',
    'waapi-skill.expansion-notice-adjudication/v4'])
@pytest.mark.parametrize('contrast', _INTENT_CONTRASTS, ids=lambda row: row['id'])
def test_v3_v4_independent_intent_proof_contrasts_transport_sealed_judgments_without_regrading(
        tmp_path, monkeypatch, contrast, adjudication_contract):
    """Fake schema judgments prove binding/non-PASS propagation, not accuracy."""
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive
    from tests.semantic.support import codex_c09_notice_adjudication as review
    notice = instantiate_contrast(contrast)
    prompt = instantiate_contrast({**contrast, 'notice': contrast['user_prompt']})
    damage = {'sufficient': None, 'contradicted': 'wrong', 'unresolved': 'uncertain'}[contrast['expected_meaning']]
    unit = sealed_workflow(tmp_path, monkeypatch, contrast['case'], damage=damage, text=notice, user_prompt=prompt,
        adjudication_contract=adjudication_contract)
    decision = json.loads((tmp_path / 'turns/turn-01/notice-decision.json').read_text())
    receipt = json.loads((tmp_path / 'turns/turn-01/notice-review/receipt.json').read_text())
    assert decision['outcome'] == 'review_required'
    assert receipt['input'] == decision['input']
    assert receipt['input']['contract'] == adjudication_contract
    assert any(row['text'] == notice for row in receipt['input']['visible_messages'])
    assert receipt['input']['user_prompt'] == prompt
    assert 'preserve' not in receipt['input']['notice_obligations']
    assert receipt['input']['attested_roles']['preserve']
    if contrast['case'] == 'C08':
        assert receipt['input']['prepared_operation']['verification_plan']['kind'] == 'result-schema'
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('model replay')))
    files = {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    archived = verify_expansion_task_archive(tmp_path, expected_unit_id=unit,
        expected_version='2025.1', expected_inputs_sha256='a' * 64)
    assert archived['archive_valid'] is True
    assert archived['business_pass'] is (damage is None)
    assert files == {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}


@pytest.mark.parametrize('case_id', ['C01', 'C03', 'C06', 'C08', 'C09', 'M01', 'M05'])
def test_v3_preserves_all_seven_workflow_target_effect_value_requirements(case_id):
    from tests.semantic.support.codex_expansion_notice_adjudication import decide_expansion_notice
    artifact, before, _, parameters, _, notice = case_facts(case_id)
    result, commands = timeline(notice, ask=case_id in {'C01', 'C03'})
    kwargs = dict(case_id=case_id, version='2025.1', execute_expected=case_id not in {'C01', 'C03'},
        preview_artifact=artifact, before_snapshot=before, preview_parameters=parameters)
    old = decide_expansion_notice(result, commands,
        adjudication_contract='waapi-skill.expansion-notice-adjudication/v2', **kwargs)['input']
    new = decide_expansion_notice(result, commands, **kwargs)['input']
    expected = {key: value for key, value in old['notice_obligations'].items()
        if key not in {'preserve', 'gateway_verification'}}
    assert new['notice_obligations'] == {**expected, 'preservation_intent': {
        'only_declared_changes': True, 'adopt_user_preservation_scope': True}}
    assert new['attested_roles'] == old['attested_roles']
    assert new['prepared_operation'] == old['prepared_operation']
    assert new['before_snapshot'] == old['before_snapshot']
    assert 'verification_context' not in old


def public_read_notice_context():
    from tests.semantic.support.codex_expansion_policy import BoundedExpansionReads, ExpansionReadScope, canonical_digest
    from tests.semantic.support.codex_expansion_notice_adjudication import decide_expansion_notice
    case = import_case('C01')
    identifier = case['before']['sound']['id']
    result, commands = timeline(case['unsupported_notice'], ask=True)
    argv = ('query-object', '--exact-id', identifier, '--relationship', 'children', '--max-results', '10')
    payload = {'ok': True, 'status': 'ok', 'command': 'query-object', 'query_bound': {'mode': 'take', 'value': 10},
        'count': 0, 'objects': [], 'agent_result': [], 'session_context': {'private': 'not reviewer facts'}}
    model = ('python', 'skills/waapi-skill/scripts/run.py', 'gateway.py', *argv)
    read = SimpleNamespace(command='read', argv=model)
    event = {'type': 'item.completed', 'item': {'type': 'command_execution', 'command': 'read',
        'status': 'completed', 'exit_code': 0, 'aggregated_output': json.dumps(payload)}}
    result.stdout = json.dumps(event) + '\n' + result.stdout
    records = [{'sequence': 1, 'authenticated': True, 'accepted': True, 'succeeded': True,
        'model_argv': model, 'normalized_model_argv': model, 'gateway_arguments': argv, 'payload': payload,
        'payload_sha256': canonical_digest(payload), 'exit_code': 0, 'runner_exit_code': 0, 'payload_error': ''}]
    admission = BoundedExpansionReads(ExpansionReadScope(frozenset({identifier}), frozenset({'audio.import'}),
        relationship_sources=frozenset({identifier})))
    kwargs = dict(case_id='C01', version='2025.1', execute_expected=False,
        preview_artifact=case['artifact'], before_snapshot=case['before'],
        preview_parameters=case['parameters'], broker_records=records, read_admission=admission)
    return result, [read, *commands], kwargs


def test_v4_notice_receives_authenticated_complete_empty_child_read():
    from tests.semantic.support.codex_expansion_notice_adjudication import decide_expansion_notice
    from tests.semantic.support.codex_expansion_policy import canonical_digest
    result, commands, kwargs = public_read_notice_context()
    admission, record = kwargs['read_admission'], kwargs['broker_records'][0]
    argv, payload = record['gateway_arguments'], record['payload']
    decision = decide_expansion_notice(result, commands, **kwargs)
    assert decision['outcome'] == 'review_required'
    evidence = decision['input']['pre_execution_public_reads']
    assert evidence['read_scope_sha256'] == admission.scope.digest
    assert evidence['reads'][0]['event_position'] == 0
    assert evidence['reads'][0]['broker_sequence'] == 1
    assert evidence['reads'][0]['gateway_arguments'] == list(argv)
    assert evidence['reads'][0]['result'] == {'query_bound': {'mode': 'take', 'value': 10}, 'count': 0, 'objects': []}
    assert evidence['reads'][0]['payload_sha256'] == canonical_digest(payload)
    assert 'private' not in json.dumps(evidence)


@pytest.mark.parametrize('damage', ['no_ledger', 'unauthenticated', 'unaccepted', 'payload', 'digest',
    'argv_binding', 'wrong_object', 'wrong_scope', 'missing_objects', 'ceiling', 'post_execute_ledger'])
def test_v4_unbound_or_out_of_scope_reads_cannot_supply_notice_facts(damage):
    from tests.semantic.support.codex_expansion_notice_adjudication import decide_expansion_notice
    from tests.semantic.support.codex_expansion_policy import canonical_digest
    result, commands, kwargs = public_read_notice_context()
    record = kwargs['broker_records'][0]
    payload = record['payload']
    if damage == 'no_ledger': kwargs['broker_records'] = []
    elif damage == 'post_execute_ledger':
        kwargs['broker_records'] = [{'sequence': 1, 'gateway_arguments': ('execute',)}, {**record, 'sequence': 2}]
    elif damage == 'unauthenticated': record['authenticated'] = False
    elif damage == 'unaccepted': record['accepted'] = False
    elif damage == 'payload': payload['count'] = 1
    elif damage == 'digest': record['payload_sha256'] = '0' * 64
    elif damage == 'argv_binding': record['gateway_arguments'] = ('query-object', '--exact-id', record['gateway_arguments'][2])
    else:
        if damage == 'wrong_object':
            payload.update(count=1, objects=[{'id': '{99999999-9999-9999-9999-999999999999}'}],
                query_bound={'mode': 'exact-object'})
            argv = ('query-object', '--exact-id', record['gateway_arguments'][2])
        elif damage == 'wrong_scope':
            argv = ('query-object', '--exact-id', '{99999999-9999-9999-9999-999999999999}',
                '--relationship', 'children', '--max-results', '10')
        elif damage == 'missing_objects':
            payload.pop('objects')
            argv = record['gateway_arguments']
        else:
            payload['query_bound'] = {'mode': 'take', 'value': 1}
            payload.update(count=1, objects=[{'id': record['gateway_arguments'][2]}])
            argv = ('query-object', '--exact-id', record['gateway_arguments'][2], '--relationship', 'children', '--max-results', '1')
        record['payload_sha256'] = canonical_digest(payload)
        record['gateway_arguments'] = argv
        commands[0].argv = (*commands[0].argv[:3], *argv)
        record['model_argv'] = commands[0].argv
        events = [json.loads(line) for line in result.stdout.splitlines()]
        events[0]['item']['aggregated_output'] = json.dumps(payload)
        result.stdout = '\n'.join(json.dumps(row) for row in events)
    assert decide_expansion_notice(result, commands, **kwargs) == {
        'outcome': 'material_reject', 'reason': 'unbound-pre-execution-public-read-evidence'}


@pytest.mark.parametrize('marker', [{'complete': False}, {'truncated': True},
    {'response_integrity': {'complete': False, 'truncated': True}}])
def test_v4_explicit_incomplete_read_never_proves_absence(marker):
    from tests.semantic.support.codex_expansion_notice_adjudication import decide_expansion_notice
    from tests.semantic.support.codex_expansion_policy import canonical_digest
    result, commands, kwargs = public_read_notice_context()
    record = kwargs['broker_records'][0]
    record['payload'].update(marker)
    record['payload_sha256'] = canonical_digest(record['payload'])
    events = [json.loads(line) for line in result.stdout.splitlines()]
    events[0]['item']['aggregated_output'] = json.dumps(record['payload'])
    result.stdout = '\n'.join(json.dumps(row) for row in events)
    decision = decide_expansion_notice(result, commands, **kwargs)
    read = decision['input']['pre_execution_public_reads']['reads'][0]
    assert read['scope_complete'] is False
    assert all(read['result'][key] == value for key, value in marker.items())


def test_v4_reads_completed_after_execute_are_excluded():
    from tests.semantic.support.codex_expansion_notice_adjudication import decide_expansion_notice
    result, commands, kwargs = public_read_notice_context()
    events = [json.loads(line) for line in result.stdout.splitlines()]
    after_read = events.pop(0)
    result.stdout = '\n'.join(json.dumps(row) for row in [*events,
        {'type': 'item.started', 'item': {'type': 'command_execution', 'command': 'execute'}}, after_read])
    case = import_case('M01')
    kwargs.update(case_id='M01', execute_expected=True, preview_artifact=case['artifact'],
        before_snapshot=case['before'], preview_parameters=case['parameters'])
    decision = decide_expansion_notice(result, commands, **kwargs)
    assert decision['outcome'] == 'review_required'
    assert decision['input']['pre_execution_public_reads']['reads'] == []
    assert decision['input']['execute_event_position'] == 2


@pytest.mark.parametrize('present', [False, True])
def test_v4_selected_object_fields_preserve_absent_versus_null(present):
    from tests.semantic.support.codex_expansion_notice_adjudication import decide_expansion_notice
    from tests.semantic.support.codex_expansion_policy import canonical_digest
    result, commands, kwargs = public_read_notice_context()
    record = kwargs['broker_records'][0]
    identifier = record['gateway_arguments'][2]
    row = {'id': identifier}
    if present: row['active_source'] = None
    record['payload'].update(count=1, objects=[row], query_bound={'mode': 'exact-object'})
    record['gateway_arguments'] = ('query-object', '--exact-id', identifier)
    commands[0].argv = (*commands[0].argv[:3], *record['gateway_arguments'])
    record['model_argv'] = commands[0].argv
    record['payload_sha256'] = canonical_digest(record['payload'])
    events = [json.loads(line) for line in result.stdout.splitlines()]
    events[0]['item']['aggregated_output'] = json.dumps(record['payload'])
    result.stdout = '\n'.join(json.dumps(row) for row in events)
    actual = decide_expansion_notice(result, commands, **kwargs)['input']['pre_execution_public_reads']['reads'][0]['result']['objects'][0]
    assert ('active_source' in actual) is present
    assert actual == row


def test_v4_rubric_fits_bound_and_retains_all_historical_hashes():
    import hashlib
    from tests.semantic.support.codex_c09_notice_adjudication import reviewer_rubric
    expected = {1: 'd304d0d46e3fd3c4cc85e002745227dba6c77eb1c1b9fb03a672f91fe5600172',
        2: 'a2410a3573343e4ac2f7a26a792f610c7c83d429749677368fd7ffc7c61a95d1',
        3: 'fa1324b097245efca5afc39f59edaf38ce242204fbf14e3cd9c4cc8de5cfac7f'}
    for version, digest in expected.items():
        assert hashlib.sha256(reviewer_rubric('waapi-skill.expansion-notice-adjudication/v' + str(version)).encode()).hexdigest() == digest
    rubric = reviewer_rubric('waapi-skill.expansion-notice-adjudication/v4')
    assert len(rubric.encode()) <= 2048
    for requirement in ('Future proof uncertainty', 'Uncertain EDIT scope', 'scope_complete',
        'absent differs from null or empty', 'potential support only', 'neither acquired evidence',
        'raw/code bypass', 'execute/reverify/retry', 'exact contiguous visible quote/event position'):
        assert requirement in rubric


def test_v4_public_read_facts_survive_real_runner_and_readonly_full_archive(tmp_path, monkeypatch):
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive
    from tests.semantic.support import codex_c09_notice_adjudication as review
    identifier = import_case('C01')['before']['distractor']['id']
    reads = [(('query-object', '--exact-id', identifier, '--relationship', 'children', '--max-results', '100'),
        {'ok': True, 'status': 'ok', 'command': 'query-object', 'count': 0, 'objects': [], 'agent_result': [],
         'query_bound': {'mode': 'take', 'value': 100}})]
    unit = sealed_workflow(tmp_path, monkeypatch, 'C01', public_reads=reads)
    decision = json.loads((tmp_path / 'turns/turn-01/notice-decision.json').read_text())
    evidence = decision['input']['pre_execution_public_reads']['reads']
    assert len(evidence) == 1
    assert evidence[0]['broker_sequence'] == 1
    assert evidence[0]['result']['count'] == 0 and evidence[0]['result']['objects'] == []
    assert evidence[0]['event_position'] < decision['input']['preview_event_position']
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('model replay')))
    files = {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    replay = verify_expansion_task_archive(tmp_path, expected_unit_id=unit,
        expected_version='2025.1', expected_inputs_sha256='a' * 64)
    assert replay['archive_valid'] is True and replay['business_pass'] is True
    assert files == {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}


def test_v4_original_backup_witness_restores_only_acquired_public_facts():
    import hashlib
    from tests.semantic.support.codex_expansion_notice_adjudication import decide_expansion_notice
    from tests.semantic.support.codex_expansion_archive import _scope
    from tests.semantic.support.codex_expansion_policy import canonical_digest, ExpansionReadScope
    from tests.semantic.support.codex_harness import completed_command_records
    from dataclasses import asdict
    directory = Path(__file__).parents[1] / 'fixtures/semantic/notice-read-evidence-e1f3e9b'
    provenance = json.loads((directory / 'provenance.json').read_text())
    for name, digest in provenance['files'].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == digest
    witness = json.loads((directory / 'c01-input.json').read_text())
    reads = json.loads((directory / 'backup-reads.json').read_text())
    events = [{'type': 'fixture.placeholder'} for _ in range(37)]
    for row in witness['visible_messages']:
        events[row['event_position']] = {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': row['text']}}
    for row in reads['events']:
        events[row['event_position']] = row['event']
    events[35] = {'type': 'item.completed', 'item': {'type': 'command_execution', 'command': 'preview'}}
    commands = completed_command_records(events, platform_name='posix')
    _, preview = timeline('', version='2022.1', ask=True)
    commands = [*commands, *preview]
    backup = witness['before_snapshot']['distractor']['id']
    scope = ExpansionReadScope(frozenset({backup}), frozenset({'audio.import'}), owned_project_reads=True, max_rows=100)
    admission = _scope({'read_scope': {key: sorted(value) if isinstance(value, frozenset) else value
        for key, value in asdict(scope).items()}, 'read_scope_sha256': scope.digest,
        'skill_source': str(Path(__file__).parents[2] / 'skills/waapi-skill'), 'version': '2022.1'})
    sound = witness['before_snapshot']['sound']
    decision = decide_expansion_notice(SimpleNamespace(stdout='\n'.join(json.dumps(e) for e in events)), commands,
        case_id='C01', version='2022.1', execute_expected=False, user_prompt=witness['user_prompt'],
        transaction_id=witness['transaction_id'], before_snapshot=witness['before_snapshot'],
        preview_artifact={'transaction_id': witness['transaction_id'], 'request': witness['immutable_request'],
            'prepared_operation': witness['prepared_operation']}, preview_parameters={'version':'2022.1',
            'sound_id':sound['id'], 'sound_path':sound['path'], 'replacement':witness['attested_roles']['mappings'][0]['source_file']},
        broker_records=reads['records'], read_admission=admission)
    assert decision['outcome'] == 'review_required'
    input = decision['input']
    projected = input['pre_execution_public_reads']['reads']
    assert [row['event_position'] for row in projected] == [26, 29]
    assert [row['broker_sequence'] for row in projected] == [10, 11]
    assert projected[0]['result']['objects'][0]['volume_db'] == -9.0
    assert projected[0]['result']['objects'][0]['active_source'] is None
    assert projected[1]['gateway_arguments'][2] == backup
    assert projected[1]['result']['count'] == 0 and projected[1]['result']['objects'] == []
    assert projected[1]['scope_complete'] is True
    for row, record in zip(projected, reads['records']):
        assert row['payload_sha256'] == record['payload_sha256']
        assert row['broker_record_sha256'] == canonical_digest(record)
    assert input['before_snapshot'] == witness['before_snapshot']
    assert input['visible_messages'] == witness['visible_messages']
    assert 'children' not in input['before_snapshot']['distractor']
    assert 'session_context' not in json.dumps(projected)


@pytest.mark.parametrize('tamper', ['scope', 'position', 'payload-digest', 'empty-as-absent'])
def test_v4_resealed_read_projection_cannot_replace_original_archive_authority(tmp_path, monkeypatch, tamper):
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive, ExpansionArchiveError
    from tests.semantic.support.codex_expansion_policy import canonical_digest
    from tests.semantic.support import codex_c09_notice_adjudication as review
    identifier = import_case('C01')['before']['distractor']['id']
    reads = [(('query-object', '--exact-id', identifier, '--relationship', 'children', '--max-results', '100'),
        {'ok': True, 'status': 'ok', 'command': 'query-object', 'count': 0, 'objects': [], 'agent_result': [],
         'query_bound': {'mode': 'take', 'value': 100}})]
    unit = sealed_workflow(tmp_path, monkeypatch, 'C01', public_reads=reads)
    path = tmp_path / 'turns/turn-01/notice-review/receipt.json'
    receipt = json.loads(path.read_text())
    projection = receipt['input']['pre_execution_public_reads']
    if tamper == 'scope': projection['read_scope_sha256'] = '0' * 64
    elif tamper == 'position': projection['reads'][0]['event_position'] += 1
    elif tamper == 'payload-digest': projection['reads'][0]['payload_sha256'] = '0' * 64
    else: projection['reads'][0]['result'].pop('objects')
    decision = json.loads((tmp_path / 'turns/turn-01/notice-decision.json').read_text())
    receipt['decision_sha256'] = canonical_digest({**decision, 'input': receipt['input']})
    receipt['sha256'] = canonical_digest({key:value for key,value in receipt.items() if key != 'sha256'})
    path.write_text(json.dumps(receipt))
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('model replay')))
    with pytest.raises(ExpansionArchiveError):
        verify_expansion_task_archive(tmp_path, expected_unit_id=unit, expected_version='2025.1',
            expected_inputs_sha256='a' * 64)
