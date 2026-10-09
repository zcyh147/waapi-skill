"""Credential-free Preview facts through the producer and sealed archive seam."""
import json
import pytest
from pathlib import Path

from tests.semantic.test_codex_expansion_notice_adjudication import sealed_workflow

V7 = 'waapi-skill.expansion-notice-adjudication/v7'


def test_authenticated_preview_authorization_survives_runner_and_readonly_archive(tmp_path, monkeypatch):
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive
    from tests.semantic.support import codex_c09_notice_adjudication as review
    unit = sealed_workflow(tmp_path, monkeypatch, 'C09', adjudication_contract=V7)
    receipt = json.loads((tmp_path / 'turns/turn-01/notice-review/receipt.json').read_text())
    facts = receipt['input']['pre_execution_authorization']
    assert facts['state'] == 'policy_authorized'
    assert facts['executed'] is False and facts['change_requested'] is True
    assert facts['authorization'] == {
        'mode': 'policy_authorization', 'policy': 'allow_changes',
        'authority': 'caller_asserted_current_user_change_request',
        'explicit_confirmation': False, 'notice_required': True,
    }
    assert facts['transaction_id'] == receipt['input']['transaction_id']
    assert facts['preview_sha256'] == receipt['input']['preview_sha256']
    assert facts['event_position'] == receipt['input']['preview_event_position']
    assert facts['pre_execution_timeline_sha256'] == receipt['input']['pre_execution_timeline_sha256']
    assert facts['broker_sequence'] == 2
    assert [row['event_type'] for row in facts['events']] == ['preview_created', 'policy_authorized']
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('model replay')))
    files = {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    replay = verify_expansion_task_archive(tmp_path, expected_unit_id=unit,
        expected_version='2025.1', expected_inputs_sha256='a' * 64)
    assert replay['archive_valid'] is True and replay['business_pass'] is True
    assert files == {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


def test_ask_preview_reports_pending_facts_without_granting_confirmation(tmp_path, monkeypatch):
    sealed_workflow(tmp_path, monkeypatch, 'C01', adjudication_contract=V7)
    receipt = json.loads((tmp_path / 'turns/turn-01/notice-review/receipt.json').read_text())
    facts = receipt['input']['pre_execution_authorization']
    assert facts['scope'] == 'preview-time-facts-only-not-execution-permission-or-human-confirmation'
    assert facts['state'] == 'awaiting_confirmation'
    assert facts['authorization'] == {'mode': 'explicit_confirmation', 'policy': 'ask_before_changes',
        'explicit_confirmation': False, 'notice_required': True, 'requires_later_user_message': True}
    assert facts['events'][-1]['event_type'] == 'confirmation_requested'
    assert receipt['input']['execute_event_position'] is None


def test_original_preexecute_preview_receipt_runs_real_producer_without_source_regrading():
    import hashlib
    from types import SimpleNamespace
    from tests.semantic.support.codex_expansion_notice_adjudication import decide_expansion_notice
    from tests.semantic.support.codex_harness import completed_command_records
    from tests.semantic.support.codex_expansion_policy import canonical_digest
    directory = Path(__file__).parents[1] / 'fixtures/semantic/notice-authorization-cd4cee1'
    provenance = json.loads((directory / 'provenance.json').read_text())
    raw = (directory / 'witness.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == provenance['files']['witness.json']
    witness = json.loads(raw)
    artifact = witness['preview_artifact']
    assert canonical_digest(artifact) == '48b624d4f4f127c13e07956cb81f116f4cc262694b9236f06e46624682d9f857'
    events = [{'type': 'fixture.placeholder'} for _ in range(24)]
    for row in witness['visible_messages']:
        events[row['event_position']] = {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': row['text']}}
    events[22] = witness['preview_event']
    execute = 'python skills/waapi-skill/scripts/run.py gateway.py execute ' + witness['transaction_id']
    events.append({'type': 'item.started', 'item': {'type': 'command_execution', 'command': execute}})
    commands = list(completed_command_records(events))
    # The first Execute is excluded from input; it carries no dispatch result.
    commands.append(SimpleNamespace(command=execute, argv=tuple(execute.split())))
    plan = artifact['prepared_operation']['verification_plan']
    result = SimpleNamespace(stdout='\n'.join(json.dumps(row) for row in events))
    kwargs = dict(case_id='C09', version='2022.1', execute_expected=True,
        preview_artifact=artifact, before_snapshot=witness['before_snapshot'],
        transaction_id=witness['transaction_id'], user_prompt=witness['user_prompt'],
        preview_parameters={'version': '2022.1', 'owner_id': plan['target_id'],
            'class_id': artifact['request']['arguments']['plugin']['class_id'],
            'name': artifact['request']['arguments']['plugin']['name'],
            'notes': artifact['request']['arguments']['plugin']['notes']},
        broker_records=[witness['broker_record']])
    decision = decide_expansion_notice(result, commands, adjudication_contract=V7, **kwargs)
    assert decision['outcome'] == 'review_required', decision
    facts = decision['input']['pre_execution_authorization']
    assert facts['event_position'] == 22 and facts['broker_sequence'] == 8
    assert facts['payload_sha256'] == 'f9b4a0588553d0ac804505b41e32b0335491428ca2395c8f17578196faf0a5d7'
    assert facts['broker_record_sha256'] == canonical_digest(witness['broker_record'])
    assert facts['broker_record_sha256'] != provenance['source_preview_broker_record_canonical_sha256']
    assert facts['pre_execution_timeline_sha256'] == canonical_digest(events[:24])
    assert facts['pre_execution_timeline_sha256'] != witness['original_pre_execution_timeline_sha256']
    assert facts['events'][1]['event_hash'] == 'bebd6698f7f3d4a7f1cdef7d43b6a4c053f3042e0a8a370d6c8000c5019a7a6e'
    legacy = decide_expansion_notice(result, commands,
        adjudication_contract='waapi-skill.expansion-notice-adjudication/v6', **kwargs)
    assert decision['input'] == {**legacy['input'], 'contract': V7, 'pre_execution_authorization': facts}
    projected = json.dumps(facts)
    for credential in ('fixture-redacted-authority', 'task_authority', 'confirmation_token', 'authorization_nonce',
            'model_argv', 'gateway_arguments', 'shell_command', 'session_context', 'endpoint', 'auth.json'):
        assert credential not in projected
    assert raw == (directory / 'witness.json').read_bytes()


@pytest.fixture
def acquired_context(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from wwise_waapi.transactions import TransactionStore
    from tests.semantic.support.codex_expansion_archive import _scope
    from tests.semantic.support.codex_harness import completed_command_records
    sealed_workflow(tmp_path, monkeypatch, 'C09', adjudication_contract=V7)
    plan = json.loads((tmp_path / 'expansion-plan.json').read_text())
    records = json.loads((tmp_path / 'expansion-broker.json').read_text())['records']
    payload = records[1]['payload']
    events = [json.loads(line) for line in (tmp_path / 'turns/turn-01/events.jsonl').read_text().splitlines()]
    artifact = TransactionStore(tmp_path / 'broker/state').load_preview(payload['transaction_id']).artifact
    kwargs = dict(case_id='C09', version='2025.1', execute_expected=True,
        preview_artifact=artifact, before_snapshot=plan['before'], preview_parameters=plan['preview_parameters'],
        transaction_id=payload['transaction_id'], user_prompt=plan['prompts'][0], broker_records=records,
        read_admission=_scope(plan))
    return events, completed_command_records(events), kwargs


def decide_context(context):
    from types import SimpleNamespace
    from tests.semantic.support.codex_expansion_notice_adjudication import decide_expansion_notice
    events, commands, kwargs = context
    return decide_expansion_notice(SimpleNamespace(stdout='\n'.join(json.dumps(row) for row in events)),
        commands, adjudication_contract=V7, **kwargs)


def reseal_preview(context):
    from tests.semantic.support.codex_expansion_policy import canonical_digest
    events, _, kwargs = context
    record = kwargs['broker_records'][1]
    record['payload_sha256'] = canonical_digest(record['payload'])
    record['stdout'] = json.dumps(record['payload'])
    preview = next(row for row in events if row.get('type') == 'item.completed'
        and row.get('item', {}).get('type') == 'command_execution'
        and 'preview-from-draft' in row['item']['command'])
    preview['item']['aggregated_output'] = record['stdout']


@pytest.mark.parametrize('damage', ['wrong-transaction', 'wrong-hash', 'wrong-target', 'wrong-operation',
    'wrong-policy', 'wrong-authority', 'explicit-confirmation', 'executed', 'unauthenticated', 'unaccepted',
    'unsucceeded', 'payload-digest', 'event-output', 'post-execute', 'duplicate-receipt', 'missing-receipt',
    'missing-event', 'event-state', 'agent-state', 'agent-authorization', 'wrong-version'])
def test_false_preview_bindings_cannot_supply_authorization_facts(acquired_context, damage):
    _, _, kwargs = acquired_context
    records = kwargs['broker_records']
    record, payload = records[1], records[1]['payload']
    if damage == 'wrong-transaction': payload['transaction_id'] = 'tx1-00000000000000000002'
    elif damage == 'wrong-hash': payload['artifact_hash'] = '0' * 64
    elif damage == 'wrong-target': payload['agent_result']['request']['arguments']['target']['value'] = '{00000000-0000-0000-0000-000000000099}'
    elif damage == 'wrong-operation': payload['agent_result']['operation'] = 'object.set'
    elif damage == 'wrong-policy': payload['authorization']['policy'] = 'read_only'
    elif damage == 'wrong-authority': payload['authorization']['authority'] = 'agent-prose'
    elif damage == 'explicit-confirmation': payload['authorization']['explicit_confirmation'] = True
    elif damage == 'executed': payload['executed'] = payload['agent_result']['executed'] = True
    elif damage in {'unauthenticated', 'unaccepted', 'unsucceeded'}:
        record[{'unauthenticated': 'authenticated', 'unaccepted': 'accepted', 'unsucceeded': 'succeeded'}[damage]] = False
    elif damage == 'post-execute': record['sequence'] = records[2]['sequence'] + 1
    elif damage == 'duplicate-receipt': records.append(dict(record))
    elif damage == 'missing-receipt': records.pop(1)
    elif damage == 'missing-event': payload['events'].pop()
    elif damage == 'event-state': payload['events'][-1]['to_state'] = 'confirmed'
    elif damage == 'agent-state': payload['agent_result']['state'] = 'confirmed'
    elif damage == 'agent-authorization': payload['agent_result']['authorization'] = {}
    elif damage == 'wrong-version': payload['detected_version'] = '2022.1'
    if damage != 'missing-receipt': reseal_preview(acquired_context)
    if damage == 'payload-digest': record['payload_sha256'] = '0' * 64
    if damage == 'event-output': record['payload']['change_requested'] = False
    decision = decide_context(acquired_context)
    assert decision == {'outcome': 'material_reject', 'reason': 'unbound-pre-execution-authorization-evidence'}


def test_prose_only_grant_claim_has_no_acquired_authorization_fact(acquired_context):
    events, _, kwargs = acquired_context
    kwargs['broker_records'] = ()
    next(row for row in events if row.get('item', {}).get('type') == 'agent_message')['item']['text'] += ' Authorization already acquired.'
    decision = decide_context(acquired_context)
    assert decision['outcome'] == 'review_required'
    assert decision['input']['pre_execution_authorization'] is None


@pytest.mark.parametrize('damage', ['boolean-as-number', 'session-policy'])
def test_malformed_or_conflicting_receipt_semantics_fail_closed(acquired_context, damage):
    payload = acquired_context[2]['broker_records'][1]['payload']
    if damage == 'boolean-as-number':
        payload['authorization']['explicit_confirmation'] = 0
    else:
        payload['session_context'] = {'project_modification_policy': 'read_only'}
    reseal_preview(acquired_context)
    decision = decide_context(acquired_context)
    assert decision == {'outcome': 'material_reject', 'reason': 'unbound-pre-execution-authorization-evidence'}


def test_v7_adds_only_bound_facts_and_aliases_exact_v6_rubric_and_high_settings(acquired_context):
    from types import SimpleNamespace
    from tests.semantic.support.codex_expansion_notice_adjudication import decide_expansion_notice, CONTRACT
    from tests.semantic.support.codex_c09_notice_adjudication import reviewer_configuration, reviewer_rubric
    from tests.semantic.support.codex_expansion_policy import canonical_digest
    assert CONTRACT == V7
    events, commands, kwargs = acquired_context
    v6 = 'waapi-skill.expansion-notice-adjudication/v6'
    legacy = decide_expansion_notice(SimpleNamespace(stdout='\n'.join(json.dumps(row) for row in events)),
        commands, adjudication_contract=v6, **kwargs)
    current = decide_context(acquired_context)
    assert current['input'] == {**legacy['input'], 'contract': V7,
        'pre_execution_authorization': current['input']['pre_execution_authorization']}
    config = reviewer_configuration(v6)
    assert canonical_digest(config) == 'd2bb4bbf82ec2526d3e31d82ab51b6b72f6528cbef8781d44c81257061776246'
    assert reviewer_configuration(V7) == {**config, 'contract': V7}
    assert reviewer_rubric(V7).encode() == reviewer_rubric(v6).encode()
    assert reviewer_configuration('waapi-skill.expansion-notice-adjudication/v5')['reasoning_effort'] == 'high'
    assert config['reasoning_effort'] == 'high' and config['timeout_seconds'] == 120
    assert canonical_digest(reviewer_configuration('waapi-skill.expansion-notice-adjudication/v5')) == 'b47e15cd869b744606f93764c074484f4214cb7567c52861ce0bb3315297c6b0'


def test_receipt_credentials_are_excluded_from_review_projection(acquired_context):
    payload = acquired_context[2]['broker_records'][1]['payload']
    for key in ('task_authority', 'confirmation_token', 'authorization_nonce', 'auth_json', 'next_command', 'endpoint'):
        payload[key] = {'sensitive': 'never-expose-' + key}
    reseal_preview(acquired_context)
    decision = decide_context(acquired_context)
    assert decision['outcome'] == 'review_required'
    assert 'never-expose' not in json.dumps(decision['input'])


@pytest.mark.parametrize('tamper', ['transaction', 'preview', 'timeline', 'position', 'sequence',
    'payload-digest', 'record-digest', 'grant', 'event'])
def test_resealed_fact_substitution_is_rejected_by_readonly_archive(tmp_path, monkeypatch, tamper):
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive, ExpansionArchiveError
    from tests.semantic.support.codex_expansion_policy import canonical_digest
    from tests.semantic.support import codex_c09_notice_adjudication as review
    unit = sealed_workflow(tmp_path, monkeypatch, 'C09', adjudication_contract=V7)
    directory = tmp_path / 'turns/turn-01'
    receipt = json.loads((directory / 'notice-review/receipt.json').read_text())
    facts = receipt['input']['pre_execution_authorization']
    field, value = {
        'transaction': ('transaction_id', 'tx1-00000000000000000002'), 'preview': ('preview_sha256', '0' * 64),
        'timeline': ('pre_execution_timeline_sha256', '0' * 64), 'position': ('event_position', 99),
        'sequence': ('broker_sequence', 99), 'payload-digest': ('payload_sha256', '0' * 64),
        'record-digest': ('broker_record_sha256', '0' * 64), 'grant': ('state', 'confirmed'),
        'event': ('events', []),
    }[tamper]
    facts[field] = value
    decision = json.loads((directory / 'notice-decision.json').read_text())
    receipt['decision_sha256'] = canonical_digest({**decision, 'input': receipt['input']})
    receipt['sha256'] = canonical_digest({key: val for key, val in receipt.items() if key != 'sha256'})
    (directory / 'notice-review/receipt.json').write_text(json.dumps(receipt))
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('model replay')))
    files = {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    with pytest.raises(ExpansionArchiveError):
        verify_expansion_task_archive(tmp_path, expected_unit_id=unit,
            expected_version='2025.1', expected_inputs_sha256='a' * 64)
    assert files == {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


def test_decoded_event_must_match_receipt_types_exactly(acquired_context):
    events, _, _ = acquired_context
    event = next(row for row in events if row.get('type') == 'item.completed'
        and row.get('item', {}).get('type') == 'command_execution'
        and 'preview-from-draft' in row['item']['command'])
    output = json.loads(event['item']['aggregated_output'])
    output['authorization']['explicit_confirmation'] = 0
    output['agent_result']['authorization']['explicit_confirmation'] = 0
    event['item']['aggregated_output'] = json.dumps(output)
    assert decide_context(acquired_context) == {
        'outcome': 'material_reject', 'reason': 'unbound-pre-execution-authorization-evidence'}


@pytest.mark.parametrize('damage', ['empty-argv', 'event-sequence-boolean', 'missing-agent'])
def test_malformed_preview_record_returns_bounded_rejection(acquired_context, damage):
    record = acquired_context[2]['broker_records'][1]
    if damage == 'empty-argv': record['normalized_model_argv'] = []
    elif damage == 'event-sequence-boolean': record['payload']['events'][0]['sequence'] = True
    else: record['payload'].pop('agent_result')
    reseal_preview(acquired_context)
    assert decide_context(acquired_context)['outcome'] == 'material_reject'


def test_ask_grant_overclaim_cannot_override_external_gates(tmp_path, monkeypatch):
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive
    unit = sealed_workflow(tmp_path, monkeypatch, 'C01', adjudication_contract=V7,
        text='I will perform the requested Japanese replacement; authorization and human confirmation already acquired.',
        damage='wrong')
    receipt = json.loads((tmp_path / 'turns/turn-01/notice-review/receipt.json').read_text())
    assert receipt['input']['pre_execution_authorization']['authorization']['explicit_confirmation'] is False
    assert receipt['outcome'] == 'material_reject'
    replay = verify_expansion_task_archive(tmp_path, expected_unit_id=unit,
        expected_version='2025.1', expected_inputs_sha256='a' * 64)
    assert replay['archive_valid'] is True and replay['business_pass'] is False
