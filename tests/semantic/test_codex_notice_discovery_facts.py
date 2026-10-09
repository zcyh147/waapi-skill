"""Closed Draft acquisition facts; fixtures never regrade a historical outcome."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from tests.semantic.support.codex_expansion_notice_adjudication import decide_expansion_notice
from tests.semantic.support.codex_expansion_policy import canonical_digest
from tests.semantic.support.codex_harness import completed_command_records

V8 = 'waapi-skill.expansion-notice-adjudication/v8'


def generated_discoveries():
    type_handle = 'bth1-' + '1' * 32
    candidate = {'handle': 'bfh1-' + '2' * 32, 'label': 'Gain', 'field_kind': 'property',
        'value_type': 'number', 'platform': None, 'restrictions': {'minimum': -96.0, 'maximum': 24.0},
        'value_input': {'type': 'number'}, 'matched_meanings': ['Gain']}
    return [(['draft-discover-types', '--meaning', 'Wwise Gain', '--role', 'effect'],
        {'type_candidates': [{'handle': type_handle, 'label': 'Wwise Gain', 'role': 'effect',
            'matched_meanings': ['Wwise Gain']}], 'candidate_count': 1,
            'selection_required': True, 'selection_rule': 'copy_one_returned_type_candidate.handle'}),
        (['draft-discover-fields', '--type-handle', type_handle, '--meaning', 'Gain'],
        {'field_candidates': [candidate], 'candidate_count': 1, 'meaning_count': 1,
            'meaning_results': [{'meaning': 'Gain', 'candidate_count': 1, 'candidates': [candidate]}],
            'rejected_candidate_count': 0, 'selection_required': False,
            'selection_rule': 'copy_exactly_one_candidate.handle_per_requested_meaning'})]


def test_real_field_producer_normalization_survives_fake_runner_archive(tmp_path, monkeypatch):
    from tests.unit.test_object_metadata_business_gateway import (
        waapi_gateway, _offline, _env, _info, _project, OBJECT_ID, FakeClient)
    from tests.semantic.test_codex_expansion_notice_adjudication import sealed_workflow
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive
    from tests.semantic.support import codex_c09_notice_adjudication as review
    producer = tmp_path / 'producer'
    producer.mkdir()
    code, started = _offline(producer, 'draft-start', 'object.setProperty')
    assert code == 0
    draft, authority = started['draft']['draft_id'], started['task_authority']
    client = FakeClient({'ak.wwise.core.getInfo': [_info()],
        'ak.wwise.core.getProjectInfo': [_project(producer)], 'ak.wwise.core.object.get': [{'return': [{
            'id': OBJECT_ID, 'name': 'Alarm', 'type': 'Sound', 'path': r'\Actor-Mixer Hierarchy\Default Work Unit\Alarm'}]}]})
    common = ['--state-dir', str(producer / 'state')]
    code, bound = waapi_gateway.execute_gateway([*common, 'draft-bind-object', draft,
        '--task-authority', authority, '--expected-revision', '1', '--object-id', OBJECT_ID],
        env=_env(producer), client_factory=lambda _: client)
    assert code == 0, bound
    metadata = {'name': 'VolumeGain', 'type': 'Real32', 'display': {'name': 'Volume gain'},
        'restriction': {'type': 'range', 'min': -96.0, 'max': 24.0}}
    client = FakeClient({'ak.wwise.core.getInfo': [_info()], 'ak.wwise.core.getProjectInfo': [_project(producer)],
        'ak.wwise.core.object.getPropertyAndReferenceNames': [{'return': ['VolumeGain']}] * 2,
        'ak.wwise.core.object.getPropertyInfo': [metadata] * 2})
    code, discovered = waapi_gateway.execute_gateway([*common, 'draft-discover-fields', draft,
        '--task-authority', authority, '--expected-revision', '2', '--object-handle', bound['bound_object']['handle'],
        '--meaning', 'Volume  gain'], env=_env(producer), client_factory=lambda _: client)
    assert code == 0, discovered
    assert discovered['meaning_results'][0]['meaning'] == 'Volume  gain'
    assert discovered['field_candidates'][0]['matched_meanings'] == ['Volume gain']
    discoveries = generated_discoveries()
    discoveries[1][0][-1] = 'Volume  gain'
    # Reuse exact real producer semantic rows in the existing generated archive;
    # its synthetic class scope is plumbing evidence, not a real plug-in read.
    discoveries[1] = (discoveries[1][0], {key: discovered[key] for key in ('field_candidates', 'candidate_count', 'meaning_count',
        'meaning_results', 'rejected_candidate_count', 'selection_required', 'selection_rule')})
    root = tmp_path / 'archive'
    root.mkdir()
    unit = sealed_workflow(root, monkeypatch, 'C09', adjudication_contract=V8, draft_discoveries=discoveries)
    receipt = json.loads((root / 'turns/turn-01/notice-review/receipt.json').read_text())
    fact = receipt['input']['pre_execution_draft_discoveries']['discoveries'][-1]
    assert fact['meanings'] == ['Volume  gain']
    assert fact['candidates'][0]['matched_meanings'] == ['Volume gain']
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('model replay')))
    assert verify_expansion_task_archive(root, expected_unit_id=unit,
        expected_version='2025.1', expected_inputs_sha256='a' * 64)['archive_valid'] is True


def refined_discoveries(command):
    rows = generated_discoveries()
    index = 0 if command == 'draft-discover-types' else 1
    argv = rows[index][0][:]
    argv[argv.index('--meaning') + 1] = 'Unmatched initial phrase'
    rows.insert(index, (argv, {'ok': False, 'error_code': 'CAPABILITY_UNAVAILABLE'}))
    return rows


@pytest.mark.parametrize('command', ['draft-discover-types', 'draft-discover-fields'])
def test_admitted_failed_discovery_then_refinement_acquires_only_successful_rows(tmp_path, monkeypatch, command):
    from tests.semantic.test_codex_expansion_notice_adjudication import sealed_workflow
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive
    from tests.semantic.support import codex_c09_notice_adjudication as review
    unit = sealed_workflow(tmp_path, monkeypatch, 'C09', adjudication_contract=V8,
        draft_discoveries=refined_discoveries(command))
    receipt = json.loads((tmp_path / 'turns/turn-01/notice-review/receipt.json').read_text())
    evidence = receipt['input']['pre_execution_draft_discoveries']
    assert len(evidence['discoveries']) == 2
    assert 'Unmatched initial phrase' not in json.dumps(evidence)
    failed, = [row for row in evidence['revision_lineage'] if row.get('status') == 'failed-no-acquisition']
    assert failed['expected_revision'] == failed['result_revision'] == (1 if command.endswith('types') else 2)
    assert evidence['preview_expected_revision'] == 3
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('model replay')))
    files = {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    replay = verify_expansion_task_archive(tmp_path, expected_unit_id=unit,
        expected_version='2025.1', expected_inputs_sha256='a' * 64)
    assert replay['archive_valid'] is True and replay['business_pass'] is True
    assert files == {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


@pytest.mark.parametrize('command', ['draft-discover-types', 'draft-discover-fields'])
@pytest.mark.parametrize('damage', ['bad-revision', 'retry-revision', 'unauthenticated', 'unaccepted',
    'wrong-authority', 'event-output', 'wrong-exit', 'missing-admission', 'candidate-rows'])
def test_failed_discovery_refinement_retains_binding_and_no_acquisition_boundary(tmp_path, monkeypatch, command, damage):
    from tests.semantic.test_codex_expansion_notice_adjudication import sealed_workflow
    from tests.semantic.support.codex_expansion_archive import _scope
    from wwise_waapi.transactions import TransactionStore
    sealed_workflow(tmp_path, monkeypatch, 'C09', adjudication_contract=V8, draft_discoveries=refined_discoveries(command))
    plan = json.loads((tmp_path / 'expansion-plan.json').read_text())
    records = json.loads((tmp_path / 'expansion-broker.json').read_text())['records']
    events = [json.loads(line) for line in (tmp_path / 'turns/turn-01/events.jsonl').read_text().splitlines()]
    tx = 'tx1-00000000000000000001'
    kwargs = dict(case_id='C09', version='2025.1', execute_expected=True,
        preview_artifact=TransactionStore(tmp_path / 'broker/state').load_preview(tx).artifact,
        before_snapshot=plan['before'], preview_parameters=plan['preview_parameters'], transaction_id=tx,
        user_prompt=plan['prompts'][0], broker_records=records, read_admission=_scope(plan))
    positions = [i for i, event in enumerate(events) if event.get('type') == 'item.completed'
        and event.get('item', {}).get('type') == 'command_execution' and 'gateway.py' in event['item'].get('command', '')]
    context = events, list(completed_command_records(events)), kwargs, {'receipts': [{'event_position': i} for i in positions]}
    index = 1 if command.endswith('types') else 2
    record = records[index]
    if damage == 'bad-revision':
        record['payload']['draft'] = {**records[0]['payload']['draft'], 'revision': index + 1}
    elif damage == 'retry-revision':
        records[index + 1]['gateway_arguments'][5] = str(index + 1)
        reseal(context, index + 1)
    elif damage == 'unauthenticated': record['authenticated'] = False
    elif damage == 'unaccepted': record['accepted'] = False
    elif damage == 'wrong-authority': record['gateway_arguments'][3] = 'other-authority'
    elif damage == 'event-output': events[positions[index]]['item']['aggregated_output'] = '{}'
    elif damage == 'wrong-exit':
        record.update(exit_code=0, runner_exit_code=0)
        events[positions[index]]['item']['exit_code'] = 0
    elif damage == 'missing-admission': record['allowed_exit_codes'] = [0]
    else: record['payload']['type_candidates'] = []
    if damage != 'event-output': reseal(context, index)
    decision = decide(context)
    assert decision['outcome'] == 'material_reject'
    assert 'input' not in decision


@pytest.mark.parametrize('version', ['2022.1', '2025.1'])
def test_type_and_field_facts_survive_fake_runner_and_readonly_archive(tmp_path, monkeypatch, version):
    from tests.semantic.test_codex_expansion_notice_adjudication import sealed_workflow
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive
    from tests.semantic.support import codex_c09_notice_adjudication as review
    unit = sealed_workflow(tmp_path, monkeypatch, 'C09', version=version, adjudication_contract=V8,
        draft_discoveries=generated_discoveries())
    receipt = json.loads((tmp_path / 'turns/turn-01/notice-review/receipt.json').read_text())
    evidence = receipt['input']['pre_execution_draft_discoveries']
    type_fact, field_fact = evidence['discoveries']
    assert field_fact['meanings'] == ['Gain']
    assert field_fact['scope'] == {'kind': 'class-candidate',
        'candidate_sha256': type_fact['candidates'][0]['candidate_sha256'],
        'label': 'Wwise Gain', 'role': 'effect', 'platform': None}
    assert field_fact['candidates'] == [{'candidate_sha256': canonical_digest('bfh1-' + '2' * 32),
        'label': 'Gain', 'field_kind': 'property', 'value_type': 'number', 'platform': None,
        'restrictions': {'minimum': -96.0, 'maximum': 24.0}, 'matched_meanings': ['Gain']}]
    assert field_fact['meaning_results'] == [{'meaning': 'Gain', 'candidate_count': 1,
        'candidate_sha256s': [field_fact['candidates'][0]['candidate_sha256']]}]
    assert field_fact['selection_required'] is False
    assert field_fact['current_property_values'] == 'not-discovered'
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('model replay')))
    files = {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    replay = verify_expansion_task_archive(tmp_path, expected_unit_id=unit,
        expected_version=version, expected_inputs_sha256='a' * 64)
    assert replay['archive_valid'] is True and replay['business_pass'] is True
    assert files == {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


@pytest.fixture
def field_context(tmp_path, monkeypatch):
    from tests.semantic.test_codex_expansion_notice_adjudication import sealed_workflow
    from tests.semantic.support.codex_expansion_archive import _scope
    from wwise_waapi.transactions import TransactionStore
    sealed_workflow(tmp_path, monkeypatch, 'C09', adjudication_contract=V8, draft_discoveries=generated_discoveries())
    plan = json.loads((tmp_path / 'expansion-plan.json').read_text())
    records = json.loads((tmp_path / 'expansion-broker.json').read_text())['records']
    events = [json.loads(line) for line in (tmp_path / 'turns/turn-01/events.jsonl').read_text().splitlines()]
    tx = 'tx1-00000000000000000001'
    kwargs = dict(case_id='C09', version='2025.1', execute_expected=True,
        preview_artifact=TransactionStore(tmp_path / 'broker/state').load_preview(tx).artifact,
        before_snapshot=plan['before'], preview_parameters=plan['preview_parameters'], transaction_id=tx,
        user_prompt=plan['prompts'][0], broker_records=records, read_admission=_scope(plan))
    return events, list(completed_command_records(events)), kwargs, {'receipts': [
        {'event_position': next(i for i, event in enumerate(events) if event.get('type') == 'item.completed'
            and event.get('item', {}).get('type') == 'command_execution'
            and event['item'].get('command') == command.command)}
        for command in completed_command_records(events) if 'gateway.py' in command.command]}


@pytest.mark.parametrize('damage', ['wrong-scope', 'wrong-semantic-scope', 'wrong-platform', 'wrong-meaning', 'field-kind',
    'value-type', 'reference-type', 'value-input-type', 'boolean-range', 'nonfinite-range', 'bad-enum',
    'credential-restriction', 'duplicate-row', 'wrong-meaning-count', 'projection-disagreement', 'typed-event-output'])
def test_field_discovery_requires_exact_scope_and_typed_semantics(field_context, damage):
    context = field_context
    events, _, kwargs, witness = context
    record = kwargs['broker_records'][2]
    payload = record['payload']
    row = payload['meaning_results'][0]['candidates'][0]
    if damage == 'wrong-scope': record['gateway_arguments'][7] = 'bth1-' + '9' * 32
    elif damage == 'wrong-semantic-scope': record['gateway_arguments'][6:8] = ['--semantic-kind', 'nonexistent-kind']
    elif damage == 'wrong-platform': record['gateway_arguments'] += ['--platform', 'Windows']
    elif damage == 'wrong-meaning': payload['meaning_results'][0]['meaning'] = 'Other'
    elif damage == 'field-kind': row['field_kind'] = 'unknown'
    elif damage == 'value-type': row['value_type'] = 'native'
    elif damage == 'reference-type': row['value_type'] = 'reference'
    elif damage == 'value-input-type': row['value_input']['type'] = 'boolean'
    elif damage == 'boolean-range': row['restrictions']['minimum'] = False
    elif damage == 'nonfinite-range': row['restrictions']['maximum'] = float('inf')
    elif damage == 'bad-enum': row['restrictions']['enum_choices'] = ['not-a-number']
    elif damage == 'credential-restriction': row['restrictions']['task_authority'] = 'never-expose'
    elif damage == 'duplicate-row': payload['meaning_results'][0]['candidates'].append(row.copy())
    elif damage == 'wrong-meaning-count': payload['meaning_count'] = True
    elif damage == 'projection-disagreement': payload['field_candidates'][0]['label'] = 'Other'
    elif damage == 'typed-event-output':
        event = events[witness['receipts'][2]['event_position']]
        output = json.loads(event['item']['aggregated_output'])
        output['candidate_count'] = True
        event['item']['aggregated_output'] = json.dumps(output)
    if damage not in {'typed-event-output', 'nonfinite-range'}: reseal(context, 2)
    decision = decide(context)
    assert decision['outcome'] == 'material_reject'
    assert 'input' not in decision


@pytest.mark.parametrize('scope_kind', ['semantic-class', 'bound-object'])
def test_field_scope_projects_only_publicly_acquired_identity(field_context, scope_kind):
    context = field_context
    _, _, kwargs, _ = context
    field = kwargs['broker_records'][2]
    if scope_kind == 'semantic-class':
        field['gateway_arguments'][6:8] = ['--semantic-kind', 'sound-sfx']
        expected = {'kind': 'semantic-class', 'semantic_kind': 'sound-sfx', 'platform': None}
    else:
        handle = 'boh1-' + '8' * 32
        binding = kwargs['broker_records'][1]
        binding['gateway_arguments'] = binding['gateway_arguments'][:6] + ['--object-id', kwargs['before_snapshot']['owner']['id']]
        binding['gateway_arguments'][0] = 'draft-bind-object'
        binding['payload']['command'] = 'draft-bind-object'
        binding['payload']['bound_object'] = {'handle': handle, 'name': 'Owner', 'type': 'Sound'}
        for key in ('type_candidates', 'candidate_count', 'selection_required', 'selection_rule'):
            binding['payload'].pop(key)
        reseal(context, 1)
        field['gateway_arguments'][6:8] = ['--object-handle', handle]
        expected = {'kind': 'bound-object', 'object_sha256': canonical_digest(handle), 'name': 'Owner',
            'type': 'Sound', 'platform': None}
    reseal(context, 2)
    decision = decide(context)
    assert decision['outcome'] == 'review_required', decision
    fact = decision['input']['pre_execution_draft_discoveries']['discoveries'][-1]
    assert fact['scope'] == expected
    assert 'id' not in fact['scope'] and 'class_id' not in fact['scope']


def test_field_partial_projection_retains_returned_semantics_without_wider_claim(field_context):
    context = field_context
    record = context[2]['broker_records'][2]
    payload = record['payload']
    payload.pop('field_candidates')
    payload['candidate_projection'] = 'meaning_results[].candidates_without_duplicate_top_level_rows'
    payload['meaning_results'][0]['candidates'][0].pop('matched_meanings')
    payload['draft']['response_integrity'] = {'complete': False, 'truncated': True}
    reseal(context, 2)
    decision = decide(context)
    assert decision['outcome'] == 'review_required', decision
    fact = decision['input']['pre_execution_draft_discoveries']['discoveries'][-1]
    assert fact['response_integrity'] == {'complete': False, 'truncated': True}
    assert fact['candidates'][0]['label'] == 'Gain'
    assert fact['entire_catalog_complete'] == 'unattested'
    assert fact['current_property_values'] == 'not-discovered'


def test_v8_adds_only_discovery_input_and_preserves_exact_v7_config_and_rubric():
    from tests.semantic.support.codex_c09_notice_adjudication import reviewer_configuration, reviewer_rubric
    from tests.semantic.support.codex_expansion_notice_adjudication import CONTRACT
    v7 = 'waapi-skill.expansion-notice-adjudication/v7'
    assert CONTRACT == V8
    config = reviewer_configuration(v7)
    assert config == {**reviewer_configuration('waapi-skill.expansion-notice-adjudication/v6'), 'contract': v7}
    assert reviewer_configuration(V8) == {**config, 'contract': V8}
    assert reviewer_rubric(V8).encode() == reviewer_rubric(v7).encode()
    assert config['reasoning_effort'] == 'high' and config['timeout_seconds'] == 120


def test_v8_invocation_binding_retains_high_and_rejects_resealed_medium(tmp_path, monkeypatch):
    from tests.semantic.test_codex_expansion_notice_adjudication import sealed_workflow
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive, ExpansionArchiveError
    from tests.semantic.support import codex_c09_notice_adjudication as review
    commands = []
    unit = sealed_workflow(tmp_path, monkeypatch, 'C09', adjudication_contract=V8,
        draft_discoveries=generated_discoveries(), subprocess_commands=commands)
    directory = tmp_path / 'turns/turn-01/notice-review'
    receipt = json.loads((directory / 'receipt.json').read_text())
    binding = json.loads((directory / 'invocation-binding.json').read_text())
    assert binding['configuration'] == receipt['configuration']
    assert binding['sha256'] == receipt['invocation_binding_sha256']
    for command in commands[-2:]:
        assert [value for value in command if value.startswith('model_reasoning_effort=')] == ['model_reasoning_effort="high"']
    receipt['configuration']['reasoning_effort'] = 'medium'
    receipt['sha256'] = canonical_digest({key: val for key, val in receipt.items() if key != 'sha256'})
    (directory / 'receipt.json').write_text(json.dumps(receipt))
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('model replay')))
    with pytest.raises(ExpansionArchiveError):
        verify_expansion_task_archive(tmp_path, expected_unit_id=unit, expected_version='2025.1', expected_inputs_sha256='a' * 64)


@pytest.mark.parametrize('tamper', ['transaction', 'preview', 'timeline', 'position', 'sequence',
    'payload-digest', 'record-digest', 'revision', 'candidate', 'scope', 'freshness'])
def test_resealed_discovery_fact_substitution_fails_archive_without_model(tmp_path, monkeypatch, tamper):
    from tests.semantic.test_codex_expansion_notice_adjudication import sealed_workflow
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive, ExpansionArchiveError
    from tests.semantic.support import codex_c09_notice_adjudication as review
    unit = sealed_workflow(tmp_path, monkeypatch, 'C09', adjudication_contract=V8, draft_discoveries=generated_discoveries())
    directory = tmp_path / 'turns/turn-01'
    receipt = json.loads((directory / 'notice-review/receipt.json').read_text())
    evidence = receipt['input']['pre_execution_draft_discoveries']
    if tamper in {'transaction', 'preview', 'timeline'}:
        field = {'transaction': 'transaction_id', 'preview': 'preview_sha256', 'timeline': 'pre_execution_timeline_sha256'}[tamper]
        evidence[field] = '0' * 64
    else:
        field, value = {'position': ('event_position', 999), 'sequence': ('broker_sequence', 999),
            'payload-digest': ('payload_sha256', '0' * 64), 'record-digest': ('broker_record_sha256', '0' * 64),
            'revision': ('result_revision', 99), 'candidate': ('candidates', []),
            'scope': ('scope', {'role': 'source'}), 'freshness': ('fresh_network_fetch', True)}[tamper]
        evidence['discoveries'][0][field] = value
    decision = json.loads((directory / 'notice-decision.json').read_text())
    receipt['decision_sha256'] = canonical_digest({**decision, 'input': receipt['input']})
    receipt['sha256'] = canonical_digest({key: val for key, val in receipt.items() if key != 'sha256'})
    (directory / 'notice-review/receipt.json').write_text(json.dumps(receipt))
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('model replay')))
    files = {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    with pytest.raises(ExpansionArchiveError):
        verify_expansion_task_archive(tmp_path, expected_unit_id=unit, expected_version='2025.1', expected_inputs_sha256='a' * 64)
    assert files == {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


def witness_context():
    import shlex
    directory = Path(__file__).parents[1] / 'fixtures/semantic/notice-discovery-8079061'
    raw = (directory / 'witness.json').read_bytes()
    provenance = json.loads((directory / 'provenance.json').read_text())
    assert hashlib.sha256(raw).hexdigest() == provenance['fixture_sha256']
    witness = json.loads(raw)
    events = [{'type': 'fixture.placeholder'} for _ in range(24)]
    for row in witness['visible_messages']:
        events[row['event_position']] = {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': row['text']}}
    for row in witness['receipts']:
        record = row['record']
        events[row['event_position']] = {'type': 'item.completed', 'item': {'type': 'command_execution',
            'command': shlex.join(record['model_argv']), 'exit_code': record['exit_code'],
            'aggregated_output': json.dumps(record['payload'], ensure_ascii=False)}}
    execute = 'python skills/waapi-skill/scripts/run.py gateway.py execute ' + witness['transaction_id']
    events.append({'type': 'item.started', 'item': {'type': 'command_execution', 'command': execute}})
    commands = list(completed_command_records(events))
    commands.append(SimpleNamespace(command=execute, argv=tuple(execute.split())))
    artifact = witness['preview_artifact']
    plan = artifact['prepared_operation']['verification_plan']
    kwargs = dict(case_id='C09', version='2025.1', execute_expected=True,
        preview_artifact=artifact, before_snapshot=witness['before_snapshot'],
        transaction_id=witness['transaction_id'], user_prompt=witness['user_prompt'],
        preview_parameters={'version': '2025.1', 'owner_id': plan['target_id'],
            'class_id': artifact['request']['arguments']['plugin']['class_id'],
            'name': artifact['request']['arguments']['plugin']['name'],
            'notes': artifact['request']['arguments']['plugin']['notes']},
        broker_records=[row['record'] for row in witness['receipts']])
    return events, commands, kwargs, witness


def decide(context, contract=V8):
    events, commands, kwargs, _ = context
    return decide_expansion_notice(SimpleNamespace(stdout='\n'.join(json.dumps(row) for row in events)),
        commands, adjudication_contract=contract, **kwargs)


def reseal(context, index):
    import shlex
    events, _, kwargs, witness = context
    record = kwargs['broker_records'][index]
    record['payload_sha256'] = canonical_digest(record['payload'])
    record['model_argv'] = ['python', 'skills/waapi-skill/scripts/run.py', 'gateway.py', *record['gateway_arguments']]
    record['normalized_model_argv'] = record['model_argv'][:]
    event = events[witness['receipts'][index]['event_position']]
    event['item'].update(command=shlex.join(record['model_argv']), aggregated_output=json.dumps(record['payload']))
    commands = list(completed_command_records(events))
    started = [event['item']['command'] for event in events if event.get('type') == 'item.started'
        and event.get('item', {}).get('type') == 'command_execution'
        and ' gateway.py execute ' in event['item']['command']]
    if started and not any(command.command == started[0] for command in commands):
        commands.append(SimpleNamespace(command=started[0], argv=tuple(started[0].split())))
    context[1][:] = commands


@pytest.mark.parametrize('damage', ['wrong-draft', 'wrong-revision', 'broken-lineage', 'wrong-role',
    'wrong-meaning', 'wrong-version', 'wrong-operation', 'wrong-schema', 'wrong-authority',
    'unauthenticated', 'unaccepted', 'unsucceeded', 'offline', 'payload-digest', 'event-output',
    'post-execute-sequence', 'post-preview-event', 'duplicate-receipt', 'duplicate-event',
    'duplicate-candidate', 'typed-count', 'wrong-selection', 'unknown-option', 'credential-label'])
def test_discovery_facts_reject_unbound_or_malformed_type_evidence(damage):
    context = witness_context()
    events, _, kwargs, _ = context
    records = kwargs['broker_records']
    record, payload = records[2], records[2]['payload']
    if damage == 'wrong-draft': payload['draft']['draft_id'] = 'another-draft'
    elif damage == 'wrong-revision': payload['draft']['revision'] = 4
    elif damage == 'broken-lineage': records[3]['gateway_arguments'][5] = '2'; reseal(context, 3)
    elif damage == 'wrong-role': payload['type_candidates'][0]['role'] = 'source'
    elif damage == 'wrong-meaning': payload['type_candidates'][0]['matched_meanings'] = ['Unrelated']
    elif damage == 'wrong-version': payload['detected_version'] = '2022.1'
    elif damage == 'wrong-operation': payload['draft']['binding']['operation'] = 'audio.import'
    elif damage == 'wrong-schema': payload['draft']['binding']['schema_digest'] = '0' * 64
    elif damage == 'wrong-authority': record['gateway_arguments'][3] = 'another-authority'
    elif damage == 'unauthenticated': record['authenticated'] = False
    elif damage == 'unaccepted': record['accepted'] = False
    elif damage == 'unsucceeded': record['succeeded'] = False
    elif damage == 'offline': payload['offline'] = True
    elif damage == 'payload-digest': record['payload_sha256'] = '0' * 64
    elif damage == 'event-output': events[16]['item']['aggregated_output'] = '{}'
    elif damage == 'post-execute-sequence':
        records.append({'sequence': 4, 'gateway_arguments': ['execute', kwargs['transaction_id']],
            'model_argv': ['python', 'skills/waapi-skill/scripts/run.py', 'gateway.py', 'execute', kwargs['transaction_id']],
            'normalized_model_argv': ['python']})
    elif damage == 'post-preview-event': events[16], events[23] = events[23], events[16]
    elif damage == 'duplicate-receipt': records.append(record.copy())
    elif damage == 'duplicate-event': events.insert(17, events[16].copy())
    elif damage == 'duplicate-candidate': payload['type_candidates'] *= 2; payload['candidate_count'] = 2
    elif damage == 'typed-count': payload['candidate_count'] = True
    elif damage == 'wrong-selection': payload['selection_required'] = False
    elif damage == 'unknown-option': record['gateway_arguments'] += ['--invented', 'true']
    elif damage == 'credential-label': payload['type_candidates'][0]['label'] = record['gateway_arguments'][3]
    if damage not in {'payload-digest', 'event-output', 'post-preview-event', 'duplicate-event'}:
        reseal(context, 2)
    decision = decide(context)
    assert decision['outcome'] == 'material_reject'
    assert 'input' not in decision


def test_real_redacted_witness_projects_acquired_type_without_freshness_or_selection_claim():
    context = witness_context()
    decision = decide(context)
    assert decision['outcome'] == 'review_required', decision
    evidence = decision['input']['pre_execution_draft_discoveries']
    fact, = evidence['discoveries']
    assert fact['command'] == 'draft-discover-types'
    assert fact['event_position'] == 16 and fact['broker_sequence'] == 5
    assert fact['expected_revision'] == 2 and fact['result_revision'] == 3
    assert fact['meanings'] == ['Wwise Gain'] and fact['scope'] == {'role': 'effect'}
    assert fact['candidates'][0]['label'] == 'Wwise Gain'
    assert fact['selection_required'] is True
    assert fact['acquisition'] == 'session-bound-live-metadata'
    assert fact['fresh_network_fetch'] == 'unattested'
    assert fact['entire_catalog_complete'] == 'unattested'
    assert fact['selection'] == 'not-established-by-discovery'
    assert evidence['transaction_id'] == decision['input']['transaction_id']
    assert evidence['preview_sha256'] == decision['input']['preview_sha256']
    assert evidence['pre_execution_timeline_sha256'] == decision['input']['pre_execution_timeline_sha256']
    assert evidence['preview_expected_revision'] == 5
    assert [(row['command'], row['result_revision']) for row in evidence['revision_lineage']] == [
        ('draft-start', 1), ('draft-bind-object', 2), ('draft-discover-types', 3),
        ('draft-declare-existing', 4), ('draft-check', 5)]
    source = context[3]['receipts'][2]
    assert source['original_payload_sha256'] == 'dcacd8074e996a44f3ed37b165b8a9eb4d7ced711387b3fa87bb0b8857e9dcf4'
    assert fact['payload_sha256'] == source['record']['payload_sha256'] != source['original_payload_sha256']
    assert fact['broker_record_sha256'] == canonical_digest(source['record']) != source['original_record_sha256']
    assert evidence['pre_execution_timeline_sha256'] != context[3]['original_pre_execution_timeline_sha256']
    old = decide(context, 'waapi-skill.expansion-notice-adjudication/v7')
    assert decision['input'] == {**old['input'], 'contract': V8, 'pre_execution_draft_discoveries': evidence}
    projected = json.dumps(evidence)
    for credential in ('fixture-redacted-authority', 'task_authority', 'handle', 'next_command',
            'gateway_arguments', 'model_argv', 'shell_command', 'endpoint', 'auth.json'):
        assert credential not in projected
