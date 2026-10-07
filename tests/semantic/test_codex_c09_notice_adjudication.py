"""Prospective C09 v1 notice review; historical fixture grades stay unchanged."""
import json
from pathlib import Path
from types import SimpleNamespace

from tests.semantic.support.codex_task_runner_v3 import expansion_preview_notice

FIXTURE = Path(__file__).parents[1] / 'fixtures/semantic/c09-notice-adjudication-v1.json'


def witness(text=None):
    fixture = json.loads(FIXTURE.read_text(encoding='utf-8'))
    notice = fixture['notice'] if text is None else text
    events = [
        {'type': 'item.completed', 'item': {'type': 'command_execution', 'command': 'preview'}},
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': notice}},
        {'type': 'item.started', 'item': {'type': 'command_execution', 'command': 'execute'}},
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'AFTER STATE MUST NOT LEAK'}},
    ]
    commands = [SimpleNamespace(command=route, argv=('python', 'skills/waapi-skill/scripts/run.py', 'gateway.py',
        subcommand, '--version', '2025.1')) for route, subcommand in [('preview', 'preview-from-draft'), ('execute', 'execute')]]
    return SimpleNamespace(stdout='\n'.join(json.dumps(event, ensure_ascii=False) for event in events)), commands, fixture


def test_c914_unsupported_notice_requires_review_and_retains_legacy_fail():
    from tests.semantic.support.codex_c09_notice_adjudication import decide_c09_notice
    result, commands, fixture = witness()
    kwargs = dict(version='2025.1', execute_expected=True, preview_artifact=fixture['preview_artifact'],
        before_snapshot=fixture['before_snapshot'])
    assert expansion_preview_notice(result, commands, **kwargs) is False
    decision = decide_c09_notice(result, commands, **kwargs)
    assert decision['outcome'] == 'review_required'
    assert decision['input']['visible_messages'][0]['text'] == fixture['notice']
    assert 'AFTER STATE' not in json.dumps(decision['input'])


def test_material_wrong_note_cannot_be_sent_for_review():
    from tests.semantic.support.codex_c09_notice_adjudication import decide_c09_notice
    result, commands, fixture = witness('将追加 Expansion_EXP25-C09_NewGain，备注为“Wrong note”，现在执行。')
    decision = decide_c09_notice(result, commands, version='2025.1', execute_expected=True,
        preview_artifact=fixture['preview_artifact'], before_snapshot=fixture['before_snapshot'])
    assert decision['outcome'] == 'material_reject'
    assert decision['reason'] == 'explicit-descriptor-contradiction'


def test_reviewer_subprocess_output_is_bounded_and_reaped(tmp_path):
    import os
    import sys
    from tests.semantic.support.codex_harness import run_process
    result = run_process([sys.executable, '-c', 'print("x" * 1000000)'], cwd=tmp_path, env=os.environ,
        timeout=2, max_output_bytes=4096)
    assert result.exit_status != 0
    assert len((result.stdout + result.stderr).encode('utf-8')) <= 4096


def grounded_judgment(review_input, verdict='accepted'):
    notice = review_input['visible_messages'][-1]
    return {'outcome': verdict, 'obligations': [{'obligation': key, 'status': 'satisfied',
        'event_position': notice['event_position'], 'quote': notice['text'], 'reason': 'Visible prospective C09 plan agrees with sealed facts.'}
        for key in ('target', 'effect', 'values', 'scope_and_preservation', 'prospective_meaning', 'optional_baseline_claims')]}


def test_independent_reviewer_receipt_replays_without_model_and_rejects_tampering(tmp_path, monkeypatch):
    from tests.semantic.support import codex_c09_notice_adjudication as review
    from tests.semantic.support.codex_harness import ProcessResult
    result, commands, fixture = witness()
    decision = review.decide_c09_notice(result, commands, version='2025.1', execute_expected=True,
        preview_artifact=fixture['preview_artifact'], before_snapshot=fixture['before_snapshot'])
    binary = tmp_path / 'codex'
    binary.write_bytes(b'fake CLI identity')
    calls = []
    def process(command, **kwargs):
        calls.append(command)
        assert kwargs['max_output_bytes'] <= 512 * 1024
        assert not any('BROKER' in key or 'WAAPI' in key for key in kwargs['env'])
        if command[1:] == ['features', 'list']:
            return ProcessResult(0, '\n'.join(review.DISABLED_FEATURES), '', .01)
        if command[1:] == ['exec', '--help']:
            return ProcessResult(0, '--output-schema --ephemeral --ignore-user-config --ignore-rules --sandbox', '', .01)
        if 'prompt-input' in command:
            return ProcessResult(0, json.dumps([{'role': 'developer', 'content': review.RUBRIC}]), '', 0.1)
        assert '--ephemeral' in command and 'read-only' in command and '--output-schema' in command
        assert 'shell_tool' in command and 'plugins' in command
        events = [
            {'type': 'thread.started', 'thread_id': 'separate-reviewer'}, {'type': 'turn.started'},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(grounded_judgment(decision['input']))}},
            {'type': 'turn.completed', 'usage': {'input_tokens': 100, 'output_tokens': 50}},
        ]
        return ProcessResult(0, '\n'.join(json.dumps(e) for e in events), '', 0.5)
    monkeypatch.setattr(review, 'run_process', process)
    options = SimpleNamespace(codex_binary=binary, auth_json=tmp_path / 'auth', windows_powershell_core_host=None)
    options.auth_json.write_text('{}')
    receipt = review.review_c09_notice(decision, root=tmp_path / 'review', options=options)
    assert receipt['outcome'] == 'accepted'
    assert receipt['usage'] == {'input_tokens': 100, 'output_tokens': 50}
    assert review.verify_c09_review_receipt(receipt, decision=decision) is True
    assert len(calls) == 4  # two CLI probes, one prompt audit, one model turn
    receipt['input']['visible_messages'][-1]['text'] += 'tampered'
    import pytest
    with pytest.raises(ValueError, match='receipt'):
        review.verify_c09_review_receipt(receipt, decision=decision)


def test_task_gate_never_invokes_reviewer_to_rescue_a_hard_failure(tmp_path, monkeypatch):
    from tests.semantic.support import codex_c09_notice_adjudication as review
    result, commands, fixture = witness()
    monkeypatch.setattr(review, 'review_c09_notice', lambda *a, **k: (_ for _ in ()).throw(AssertionError('reviewer called')))
    assert review.grade_c09_notice(result, commands, version='2025.1', execute_expected=True,
        preview_artifact=fixture['preview_artifact'], before_snapshot=fixture['before_snapshot'],
        transaction_id='tx1-' + 'a' * 20, user_prompt='Append the requested Gain.',
        other_gates={'authorization': False}, root=tmp_path, options=None)['passed'] is False


def test_archive_notice_gate_requires_receipt_only_for_review_required_and_checks_bound_input(tmp_path):
    import pytest
    from tests.semantic.support import codex_c09_notice_adjudication as review
    from tests.semantic.support.codex_expansion_archive import replay_c09_notice, ExpansionArchiveError
    result, commands, fixture = witness()
    kwargs = dict(version='2025.1', execute_expected=True, preview_artifact=fixture['preview_artifact'],
        before_snapshot=fixture['before_snapshot'], transaction_id='tx1-' + 'a' * 20, user_prompt='Append Gain.')
    decision = review.decide_c09_notice(result, commands, **kwargs)
    (tmp_path / 'notice-decision.json').write_text(json.dumps(decision))
    with pytest.raises(ExpansionArchiveError, match='missing|receipt|file'):
        replay_c09_notice(tmp_path, result, commands, other_gates={'authorization': True}, expected_runtime={}, **kwargs)
    assert replay_c09_notice(tmp_path, result, commands, other_gates={'authorization': False}, expected_runtime={}, **kwargs) is False


def sealed_c09_archive(root, monkeypatch, damage=None):
    """Adapt the existing complete fake archive fixture, with a separate C09 oracle."""
    import shlex
    import shutil
    import sys
    from copy import deepcopy
    from dataclasses import asdict
    from tests.semantic.test_codex_expansion_archive import _sealed_c08, _write, INPUTS
    from tests.semantic.support.codex_expansion_policy import canonical_digest
    from tests.semantic.support.codex_expansion_effects_case import verify_c09, C09_ASSERTIONS
    from tests.semantic.support.codex_harness import completed_command_records, ProcessResult
    from tests.semantic.support import codex_c09_notice_adjudication as review
    from wwise_waapi.transactions import TransactionStore
    _sealed_c08(root)
    fixture = json.loads(FIXTURE.read_text())
    artifact, before = fixture['preview_artifact'], fixture['before_snapshot']
    descriptor = artifact['request']['arguments']['plugin']
    after = deepcopy(before)
    slot, effect = '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}', '{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}'
    after['slot_order'].append(slot)
    after['entries'].append({'slot': slot, 'slot_state': {'id': slot, 'type': 'EffectSlot',
        'owner': {'id': before['owner']['id']}, '@Effect': {'id': effect}},
        'effect': {'id': effect, 'type': 'Effect', 'classId': descriptor['class_id'],
            'name': descriptor['name'], 'notes': descriptor['notes'], 'owner': {'id': slot}}})
    oracle_parameters = {'version': '2025.1', 'expected_class_id': descriptor['class_id'],
        'expected_name': descriptor['name'], 'expected_notes': descriptor['notes']}
    assertions = verify_c09(before, after, **oracle_parameters)
    assert all(assertions.values())
    plan = json.loads((root / 'expansion-plan.json').read_text())
    plan.pop('sha256')
    binary, auth = root / 'fake-codex', root / 'fake-auth'
    binary.write_bytes(b'fake independent CLI')
    auth.write_text('{}')
    options = SimpleNamespace(codex_binary=binary, auth_json=auth, windows_powershell_core_host=None)
    runtime = review.reviewer_runtime_identity(options)
    plan.update(unit_id='EXP25-C09', operation='object.createPlugin', request_schema_uri=None,
        before=before, required_assertions=sorted(C09_ASSERTIONS), oracle_parameters=oracle_parameters,
        preview_parameters={'version': '2025.1', 'owner_id': before['owner']['id'],
            'class_id': descriptor['class_id'], 'name': descriptor['name'], 'notes': descriptor['notes']},
        notice_adjudication={'configuration': review.reviewer_configuration(), 'runtime': runtime})
    digest = canonical_digest(plan)
    _write(root / 'expansion-plan.json', {**plan, 'sha256': digest})
    tx = 'tx1-00000000000000000001'
    shutil.rmtree(root / 'broker/state')  # disposable fake fixture only
    store = TransactionStore(root / 'broker/state')
    store.create_preview(tx, artifact)
    store.transition(tx, 'policy_authorized', expected_state='draft', event_type='policy_authorized',
        details={'policy': 'allow_changes', 'authority': 'caller_asserted_current_user_change_request', 'explicit_confirmation': False})
    store.begin_execution(tx, expected_authorization='policy_authorized')
    store.mark_executed_unverified(tx)
    store.record_verification(tx, outcome='verified')
    oracle = json.loads((root / 'expansion-oracle.json').read_text())
    artifact_hash = canonical_digest(artifact)
    oracle.update(before=before, after=after, preview_before=before, preview_after=before,
        assertions=assertions, artifact_hash=artifact_hash, gateway_verification_state='verified')
    oracle['permit']['artifact_sha256'] = artifact_hash
    _write(root / 'expansion-oracle.json', oracle)
    broker = json.loads((root / 'expansion-broker.json').read_text())
    directory = root / 'turns/turn-01'
    events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
    for record in broker['records']:
        argv = record['gateway_arguments']
        if argv[0] == 'draft-start': argv[1] = 'object.createPlugin'
        model = ['python', plan['skill_source'] + '/scripts/run.py', 'gateway.py', *argv]
        semantic = ['runner-owned-version', '2025.1', *argv]
        if '--expected-revision' in argv: semantic[-1] = 1
        payload = record['payload']
        if 'artifact_hash' in payload: payload['artifact_hash'] = artifact_hash
        if argv[0] == 'verify': payload['state'] = 'verified'
        record.update(model_argv=model, normalized_model_argv=model, raw_argv_sha256=canonical_digest(model),
            argv_sha256=canonical_digest(model), semantic_argv_sha256=canonical_digest(semantic),
            payload_sha256=canonical_digest(payload), stdout=json.dumps(payload),
            runner_command_sha256=canonical_digest([plan['trusted_python'], plan['skill_source'] + '/scripts/run.py', 'gateway.py', *argv]))
        for event in events:
            item = event.get('item', {})
            if item.get('id') == 'cmd-' + str(record['sequence']):
                item.update(command=shlex.join(model), aggregated_output=record['stdout'])
    for event in events:
        if event.get('item', {}).get('id') == 'preview-notice': event['item']['text'] = fixture['notice']
    _write(root / 'expansion-broker.json', broker)
    (directory / 'events.jsonl').write_text(''.join(json.dumps(event) + '\n' for event in events))
    facts = json.loads((directory / 'codex-facts.json').read_text())
    commands = completed_command_records(events, platform_name='posix')
    facts['command_facts']['command_records'] = [asdict(row) for row in commands]
    _write(directory / 'codex-facts.json', facts)
    result = json.loads((root / 'expansion-task-result.json').read_text())
    result.update(unit_id='EXP25-C09', plan_sha256=digest, assertions=assertions, gateway_verification_state='verified')
    _write(root / 'expansion-task-result.json', result)
    decision = review.decide_c09_notice(SimpleNamespace(stdout=(directory / 'events.jsonl').read_text()), commands,
        version='2025.1', execute_expected=True, preview_artifact=artifact, before_snapshot=before,
        transaction_id=tx, user_prompt=plan['prompts'][0])
    assert decision['outcome'] == 'review_required'
    def process(command, **kwargs):
        if command[1:] == ['features', 'list']:
            return ProcessResult(0, '\n'.join(review.DISABLED_FEATURES), '', .01)
        if command[1:] == ['exec', '--help']:
            return ProcessResult(0, '--output-schema --ephemeral --ignore-user-config --ignore-rules --sandbox', '', .01)
        if 'prompt-input' in command:
            return ProcessResult(0, json.dumps([{'role': 'developer', 'content': review.RUBRIC}]), '', .01)
        judgment = grounded_judgment(decision['input'])
        if damage == 'uncertain':
            judgment['obligations'][0]['status'] = 'unresolved'
            judgment['outcome'] = 'review_required'
        elif damage == 'conflicting': judgment['outcome'] = 'material_reject'
        elif damage == 'ungrounded': judgment['obligations'][0]['quote'] = 'invented meaning'
        elif damage == 'missing_obligation': judgment['obligations'].pop()
        elif damage == 'duplicate_obligation': judgment['obligations'][-1] = judgment['obligations'][0]
        if damage == 'timeout': return ProcessResult(124, '', 'review timeout', .01, timed_out=True)
        if damage == 'unavailable': return ProcessResult(1, '', 'review unavailable', .01)
        raw = '{' if damage == 'malformed' else json.dumps(judgment)
        events = [{'type': 'thread.started', 'thread_id': 'independent-review'}, {'type': 'turn.started'},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': raw}},
            {'type': 'turn.completed', 'usage': {'input_tokens': 50, 'output_tokens': 30}}]
        if damage == 'tool_use': events.insert(2, {'type': 'item.completed', 'item': {'type': 'mcp_tool_call'}})
        if damage == 'truncated': events.pop()
        return ProcessResult(0, '\n'.join(json.dumps(event) for event in events), '', .01)
    monkeypatch.setattr(review, 'run_process', process)
    graded = review.grade_c09_notice(SimpleNamespace(stdout=(directory / 'events.jsonl').read_text()), commands,
        version='2025.1', execute_expected=True, preview_artifact=artifact, before_snapshot=before,
        transaction_id=tx, user_prompt=plan['prompts'][0], other_gates={'authorization': True}, root=directory, options=options)
    assert graded['passed'] is (damage is None)
    return root


def test_full_C09_archive_replays_sealed_review_without_subprocess_or_grade_writes(tmp_path, monkeypatch):
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive
    from tests.semantic.support import codex_c09_notice_adjudication as review
    root = sealed_c09_archive(tmp_path, monkeypatch)
    before = {str(path): path.read_bytes() for path in root.rglob('*') if path.is_file()}
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('rejudgment')))
    result = verify_expansion_task_archive(root, expected_unit_id='EXP25-C09', expected_version='2025.1', expected_inputs_sha256='a' * 64)
    assert result['business_pass'] is True
    assert before == {str(path): path.read_bytes() for path in root.rglob('*') if path.is_file()}


import pytest


@pytest.mark.parametrize('damage', ['uncertain', 'conflicting', 'ungrounded', 'missing_obligation',
    'duplicate_obligation', 'timeout', 'unavailable', 'malformed', 'tool_use', 'truncated'])
def test_new_C09_review_failures_never_promote_business_success(tmp_path, monkeypatch, damage):
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive, ExpansionArchiveError
    root = sealed_c09_archive(tmp_path, monkeypatch, damage=damage)
    receipt = json.loads((root / 'turns/turn-01/notice-review/receipt.json').read_text())
    assert receipt['outcome'] != 'accepted'
    with pytest.raises(ExpansionArchiveError):
        verify_expansion_task_archive(root, expected_unit_id='EXP25-C09', expected_version='2025.1', expected_inputs_sha256='a' * 64)


@pytest.mark.parametrize('damage', ['missing', 'output', 'transaction', 'timeline', 'runtime', 'invocation', 'notice_source', 'oracle_after'])
def test_full_C09_archive_rejects_missing_or_tampered_review_and_hard_facts(tmp_path, monkeypatch, damage):
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive, ExpansionArchiveError
    from tests.semantic.support import codex_c09_notice_adjudication as review
    root = sealed_c09_archive(tmp_path, monkeypatch)
    path = root / 'turns/turn-01/notice-review/receipt.json'
    receipt = json.loads(path.read_text())
    if damage == 'missing': path.unlink()
    elif damage == 'notice_source':
        events = root / 'turns/turn-01/events.jsonl'
        rows = [json.loads(line) for line in events.read_text().splitlines()]
        for row in rows:
            if row.get('item', {}).get('id') == 'preview-notice':
                row['item']['text'] += '目标是 OtherSound。'
        events.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    elif damage == 'oracle_after':
        path = root / 'expansion-oracle.json'
        oracle = json.loads(path.read_text())
        oracle['after']['owner']['@Volume'] = -99
        path.write_text(json.dumps(oracle))
    else:
        if damage == 'output': receipt['stdout'] += '{}'
        elif damage == 'transaction': receipt['input']['transaction_id'] = 'tx1-' + 'e' * 20
        elif damage == 'timeline': receipt['input']['pre_execution_timeline_sha256'] = 'e' * 64
        elif damage == 'runtime': receipt['runtime']['codex_sha256'] = 'e' * 64
        elif damage == 'invocation': receipt['invocation'] = []
        # Even a rewritten local receipt checksum cannot defeat its independent source/plan binding.
        from tests.semantic.support.codex_expansion_policy import canonical_digest
        receipt['sha256'] = canonical_digest({k: v for k, v in receipt.items() if k != 'sha256'})
        path.write_text(json.dumps(receipt))
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('rejudgment')))
    with pytest.raises(ExpansionArchiveError):
        verify_expansion_task_archive(root, expected_unit_id='EXP25-C09', expected_version='2025.1', expected_inputs_sha256='a' * 64)


def test_negated_bookkeeping_wrong_note_is_not_a_material_edit_claim():
    from tests.semantic.support.codex_c09_notice_adjudication import decide_c09_notice
    result, commands, fixture = witness('不会设置备注为“Wrong note”。将追加 Expansion_EXP25-C09_NewGain。')
    decision = decide_c09_notice(result, commands, version='2025.1', execute_expected=True,
        preview_artifact=fixture['preview_artifact'], before_snapshot=fixture['before_snapshot'])
    assert decision['outcome'] == 'review_required'


def test_bounded_reviewer_process_timeout_reaps_the_child(tmp_path):
    import os
    import sys
    from tests.semantic.support.codex_harness import run_process
    result = run_process([sys.executable, '-c', 'import time; time.sleep(60)'], cwd=tmp_path, env=os.environ,
        timeout=.05, max_output_bytes=4096)
    assert result.timed_out and result.exit_status == 124


@pytest.mark.parametrize('defect', ['target', 'descriptor', 'missing_notice', 'notice_after_execute'])
def test_new_C09_hard_notice_failures_do_not_enter_semantic_review(defect):
    from tests.semantic.support.codex_c09_notice_adjudication import decide_c09_notice
    result, commands, fixture = witness()
    if defect == 'target': fixture['before_snapshot']['owner']['id'] = '{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}'
    elif defect == 'descriptor': fixture['preview_artifact']['request']['arguments']['plugin']['class_id'] = 1
    else:
        events = [json.loads(line) for line in result.stdout.splitlines()]
        if defect == 'missing_notice': events.pop(1)
        else: events[1], events[2] = events[2], events[1]
        result.stdout = '\n'.join(json.dumps(row) for row in events)
    decision = decide_c09_notice(result, commands, version='2025.1', execute_expected=True,
        preview_artifact=fixture['preview_artifact'], before_snapshot=fixture['before_snapshot'])
    assert decision['outcome'] == 'material_reject'


@pytest.mark.parametrize('claim', [
    '同时删除原效果。', '同时修改该 Sound 的 Pitch 为 12。',
    '新增项是 Sound：Expansion_EXP25-C09_NewGain。', '并记录原有三效果器的状态。',
])
def test_explicit_material_C09_contradictions_cannot_become_review_required(claim):
    from tests.semantic.support.codex_c09_notice_adjudication import decide_c09_notice
    result, commands, fixture = witness(json.loads(FIXTURE.read_text())['notice'] + '\n' + claim)
    decision = decide_c09_notice(result, commands, version='2025.1', execute_expected=True,
        preview_artifact=fixture['preview_artifact'], before_snapshot=fixture['before_snapshot'])
    assert decision['outcome'] == 'material_reject'
