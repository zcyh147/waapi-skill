"""Prospective C09 v1 notice review; historical fixture grades stay unchanged."""
import json
import os
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
    from tests.semantic.support.codex_harness import BoundedProcessResult as ProcessResult
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
    assert review.verify_c09_review_receipt(receipt, decision=decision, expected_binding=json.loads((tmp_path / 'review/invocation-binding.json').read_text())) is True
    assert len(calls) == 4  # two CLI probes, one prompt audit, one model turn
    receipt['input']['visible_messages'][-1]['text'] += 'tampered'
    import pytest
    with pytest.raises(ValueError, match='receipt'):
        review.verify_c09_review_receipt(receipt, decision=decision, expected_binding=json.loads((tmp_path / 'review/invocation-binding.json').read_text()))


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


def sealed_c09_archive(root, monkeypatch, damage=None, transaction_id=None, actual_audit=False):
    """Adapt the existing complete fake archive fixture, with a separate C09 oracle."""
    import shlex
    import shutil
    import sys
    from copy import deepcopy
    from dataclasses import asdict
    from tests.semantic.test_codex_expansion_archive import _sealed_c08, _write, INPUTS
    from tests.semantic.support.codex_expansion_policy import canonical_digest
    from tests.semantic.support.codex_expansion_effects_case import verify_c09, C09_ASSERTIONS
    from tests.semantic.support.codex_harness import completed_command_records, BoundedProcessResult as ProcessResult
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
    tx = transaction_id or 'tx1-00000000000000000001'
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
    oracle.update(transaction_id=tx, before=before, after=after, preview_before=before, preview_after=before,
        assertions=assertions, artifact_hash=artifact_hash, gateway_verification_state='verified')
    oracle['permit']['artifact_sha256'] = artifact_hash
    oracle['permit']['transaction_id'] = tx
    _write(root / 'expansion-oracle.json', oracle)
    broker = json.loads((root / 'expansion-broker.json').read_text())
    directory = root / 'turns/turn-01'
    events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
    for record in broker['records']:
        argv = record['gateway_arguments']
        argv[:] = [tx if value == 'tx1-00000000000000000001' else value for value in argv]
        if argv[0] == 'draft-start': argv[1] = 'object.createPlugin'
        model = ['python', plan['skill_source'] + '/scripts/run.py', 'gateway.py', *argv]
        semantic = ['runner-owned-version', '2025.1', *argv]
        if '--expected-revision' in argv: semantic[-1] = 1
        payload = record['payload']
        if 'transaction_id' in payload: payload['transaction_id'] = tx
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
            if actual_audit:
                fixture_audit = json.loads((FIXTURE.parent / 'reviewer-prompt-audit-cli-0.159.2-v2.json').read_text())
                payload = json.loads(fixture_audit['audit_stdout'])
                owned_home = str(Path(kwargs['env']['CODEX_HOME']).resolve())
                for message in payload:
                    for content in message['content']:
                        if content.get('type') == 'input_text':
                            content['text'] = content['text'].replace(
                                '/private/var/folders/0g/wcnvwhx96wqd99gqw8t8hy040000gn/T/codex-waapi-state-ceie7a06', owned_home)
                payload[0]['content'][0]['text'] = review.RUBRIC
                payload[-1]['content'][0]['text'] = command[-1]
                if damage == 'audit_wrong_root':
                    for message in payload:
                        for content in message['content']:
                            if content.get('type') == 'input_text':
                                content['text'] = content['text'].replace(owned_home, '/unowned/.codex')
                elif damage in {'audit_user_skill', 'audit_waapi_skill'}:
                    name = 'waapi-skill' if damage == 'audit_waapi_skill' else 'personal'
                    payload.append({'role': 'developer', 'content':
                        f'- {name}: unowned (file: /unowned/.agents/skills/{name}/SKILL.md)'})
                elif damage == 'audit_memory':
                    payload.append({'role': 'developer', 'content': '<memory_summary>executor memory</memory_summary>'})
                elif damage == 'audit_developer':
                    payload[0]['content'][0]['text'] += ' altered rubric'
                return ProcessResult(0, json.dumps(payload), '', .01)
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
        stdout = '\n'.join(json.dumps(event) for event in events)
        if damage == 'invalid_utf8':
            from tests.semantic.support.codex_harness import run_process
            raw = stdout.encode('utf-8').replace(b'accepted', b'ac\xffcepted')
            return run_process([sys.executable, '-c',
                'import sys; sys.stdout.buffer.write(bytes.fromhex(sys.argv[1]))', raw.hex()], **kwargs)
        return ProcessResult(0, stdout, '', .01)
    monkeypatch.setattr(review, 'run_process', process)
    graded = review.grade_c09_notice(SimpleNamespace(stdout=(directory / 'events.jsonl').read_text()), commands,
        version='2025.1', execute_expected=True, preview_artifact=artifact, before_snapshot=before,
        transaction_id=tx, user_prompt=plan['prompts'][0], other_gates={'authorization': True}, root=directory, options=options)
    assert graded['passed'] is (damage is None)
    budget = json.loads((root / 'expansion-agent-budget.json').read_text())
    for row in (budget['turns'][0], result['turns'][0]):
        row['notice_invocation_binding_sha256'] = graded['invocation_binding_sha256']
    _write(root / 'expansion-agent-budget.json', budget)
    _write(root / 'expansion-task-result.json', result)
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


def test_v2_actual_CLI_owned_system_catalog_reaches_review_and_replays_after_cleanup(tmp_path, monkeypatch):
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive
    from tests.semantic.support import codex_c09_notice_adjudication as review
    root = sealed_c09_archive(tmp_path, monkeypatch, actual_audit=True)
    binding = json.loads((root / 'turns/turn-01/notice-review/invocation-binding.json').read_text())
    assert binding['contract'] == 'waapi-skill.c09-review-invocation/v2'
    assert not Path(binding['context']['audit_codex_home']).exists()
    before = {str(path): path.read_bytes() for path in root.rglob('*') if path.is_file()}
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('rejudgment')))
    # Replay cannot recover ownership by looking up a deleted temporary root.
    original_resolve = Path.resolve
    def resolve(path, *args, **kwargs):
        if 'codex-waapi-state-' in str(path):
            raise AssertionError('deleted audit-root resolution')
        return original_resolve(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'resolve', resolve)
    original_stat = Path.stat
    def stat(path, *args, **kwargs):
        if 'codex-waapi-state-' in str(path):
            raise AssertionError('deleted audit-root lookup')
        return original_stat(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'stat', stat)
    assert verify_expansion_task_archive(root, expected_unit_id='EXP25-C09', expected_version='2025.1',
        expected_inputs_sha256='a' * 64)['business_pass'] is True
    assert before == {str(path): path.read_bytes() for path in root.rglob('*') if path.is_file()}


import pytest


@pytest.mark.parametrize('damage', ['audit_wrong_root', 'audit_user_skill', 'audit_waapi_skill',
    'audit_memory', 'audit_developer'])
def test_v2_actual_CLI_catalog_does_not_admit_executor_skills_memory_or_rubric_changes(tmp_path, monkeypatch, damage):
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive, ExpansionArchiveError
    root = sealed_c09_archive(tmp_path, monkeypatch, damage=damage, actual_audit=True)
    receipt = json.loads((root / 'turns/turn-01/notice-review/receipt.json').read_text())
    assert receipt['invocation'] is None
    assert receipt['outcome'] == 'review_required'
    with pytest.raises(ExpansionArchiveError):
        verify_expansion_task_archive(root, expected_unit_id='EXP25-C09', expected_version='2025.1',
            expected_inputs_sha256='a' * 64)


@pytest.mark.skipif(os.name == 'nt', reason='exact frozen prompt inventory owns macOS host locators')
def test_exact_frozen_audit_copy_only_classifies_independently_owned_system_root():
    import hashlib
    from tests.semantic.support.codex_harness import audit_prompt_input_payload
    fixture = json.loads((FIXTURE.parent / 'reviewer-prompt-audit-cli-0.159.2-v2.json').read_text())
    raw = fixture['audit_stdout']
    assert hashlib.sha256(raw.encode()).hexdigest() == fixture['source_audit_sha256']
    payload = json.loads(raw)
    # Literal expected host identity from the observed isolated launch, not a
    # locator selected by the prompt inventory under test.
    owned = Path('/private/var/folders/0g/wcnvwhx96wqd99gqw8t8hy040000gn/T/codex-waapi-state-ceie7a06/skills/.system')
    old = audit_prompt_input_payload(payload, expected_developer_instructions=fixture['expected_developer_instructions'])
    prospective = audit_prompt_input_payload(payload, system_skill_root=owned, system_skill_root_is_archived=True,
        expected_developer_instructions=fixture['expected_developer_instructions'])
    assert len(old.unexpected_skills) == 4
    assert len(prospective.system_skills) == 4
    assert prospective.unexpected_skills == ()
    assert prospective.developer_instructions_exact is True
    assert prospective.has_memory is False and prospective.has_target_skill is False


@pytest.mark.parametrize('actual_audit', [False, True])
def test_v1_archive_keeps_original_catalog_audit_semantics(tmp_path, monkeypatch, actual_audit):
    from tests.semantic.support import codex_c09_notice_adjudication as review
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive, ExpansionArchiveError
    from tests.semantic.support.codex_expansion_policy import canonical_digest
    root = sealed_c09_archive(tmp_path, monkeypatch, actual_audit=actual_audit)
    directory = root / 'turns/turn-01/notice-review'
    path = directory / 'invocation-binding.json'
    binding = json.loads(path.read_text())
    binding['contract'] = 'waapi-skill.c09-review-invocation/v1'
    binding['context'].pop('audit_codex_home')
    binding['sha256'] = canonical_digest({k: v for k, v in binding.items() if k != 'sha256'})
    path.write_text(json.dumps(binding))
    path = directory / 'receipt.json'
    receipt = json.loads(path.read_text())
    receipt['invocation_binding_sha256'] = binding['sha256']
    receipt['sha256'] = canonical_digest({k: v for k, v in receipt.items() if k != 'sha256'})
    path.write_text(json.dumps(receipt))
    for name in ('expansion-agent-budget.json', 'expansion-task-result.json'):
        path = root / name
        record = json.loads(path.read_text())
        record['turns'][0]['notice_invocation_binding_sha256'] = binding['sha256']
        path.write_text(json.dumps(record))
    before = {str(path): path.read_bytes() for path in root.rglob('*') if path.is_file()}
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('rejudgment')))
    kwargs = dict(expected_unit_id='EXP25-C09', expected_version='2025.1', expected_inputs_sha256='a' * 64)
    if actual_audit:
        with pytest.raises(ExpansionArchiveError, match='isolated execution'):
            verify_expansion_task_archive(root, **kwargs)
    else:
        assert verify_expansion_task_archive(root, **kwargs)['business_pass'] is True
    assert before == {str(path): path.read_bytes() for path in root.rglob('*') if path.is_file()}


def test_archived_owned_system_paths_are_lexical_and_reject_escape_or_sibling_roots(tmp_path, monkeypatch):
    from tests.semantic.support.codex_harness import is_codex_system_skill
    root = tmp_path / 'reviewer space 日本 $`' / 'skills' / '.system'
    monkeypatch.setattr(Path, 'resolve', lambda *a, **k: (_ for _ in ()).throw(AssertionError('archive lookup')))
    def classified(locator):
        return is_codex_system_skill(str(locator), system_skill_root=root, system_skill_root_is_archived=True)
    assert classified(root / 'builtin' / 'SKILL.md') is True
    assert classified(root / 'builtin' / '..' / 'outside' / 'SKILL.md') is False
    assert classified(root.parent / '.system-other' / 'builtin' / 'SKILL.md') is False
    assert classified(root / 'SKILL.md') is False
    assert classified('builtin/SKILL.md') is False
    assert classified(str(root / 'builtin' / 'SKILL.md').upper()) is (os.name == 'nt')
    mixed = str(root / 'builtin' / 'SKILL.md')
    mixed = mixed.replace('\\', '/') if os.name == 'nt' else mixed.replace('/', '\\')
    assert classified(mixed) is (os.name == 'nt')


@pytest.mark.skipif(os.name != 'nt', reason='native Windows UNC ownership semantics')
def test_archived_owned_system_paths_preserve_native_UNC_case_semantics():
    from tests.semantic.support.codex_harness import is_codex_system_skill
    root = Path(r'\\server\share\reviewer space\skills\.system')
    assert is_codex_system_skill(r'\\SERVER\SHARE\reviewer space\skills\.system\builtin\SKILL.md',
        system_skill_root=root, system_skill_root_is_archived=True) is True
    assert is_codex_system_skill(r'\\server\other\reviewer space\skills\.system\builtin\SKILL.md',
        system_skill_root=root, system_skill_root_is_archived=True) is False


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


@pytest.mark.parametrize('change', ['model', 'effort', 'tier', 'sandbox', 'network', 'schema', 'enabled_shell', 'duplicate_model', 'audit_model', 'audit_override'])
def test_complete_C09_archive_rejects_changed_effective_reviewer_settings(tmp_path, monkeypatch, change):
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive, ExpansionArchiveError
    from tests.semantic.support.codex_expansion_policy import canonical_digest
    root = sealed_c09_archive(tmp_path, monkeypatch)
    path = root / 'turns/turn-01/notice-review/receipt.json'
    receipt = json.loads(path.read_text())
    command = receipt['invocation']
    if change == 'model': command[command.index('--model') + 1] = 'different-model'
    elif change == 'effort': command[command.index('model_reasoning_effort="medium"')] = 'model_reasoning_effort="high"'
    elif change == 'tier': command[command.index('service_tier="default"')] = 'service_tier="priority"'
    elif change == 'sandbox': command[command.index('--sandbox') + 1] = 'danger-full-access'; command.insert(-1, 'read-only')
    elif change == 'network': command[command.index('sandbox_workspace_write.network_access=false')] = 'sandbox_workspace_write.network_access=true'
    elif change == 'schema': command[command.index('--output-schema') + 1] = '/tmp/unrelated-schema.json'
    elif change == 'enabled_shell': command[-1:-1] = ['--enable', 'shell_tool']
    elif change == 'duplicate_model': command[-1:-1] = ['--model', 'gpt-6.1-sol']
    elif change == 'audit_model':
        audit = receipt['audit_command']
        audit[audit.index('model="gpt-6.1-sol"')] = 'model="different-model"'
    elif change == 'audit_override': receipt['audit_command'][-1:-1] = ['-c', 'features.shell_tool=true']
    receipt['sha256'] = canonical_digest({key: value for key, value in receipt.items() if key != 'sha256'})
    path.write_text(json.dumps(receipt))
    with pytest.raises(ExpansionArchiveError, match='invocation'):
        verify_expansion_task_archive(root, expected_unit_id='EXP25-C09', expected_version='2025.1', expected_inputs_sha256='a' * 64)


@pytest.mark.parametrize('change', ['schema_content', 'configuration', 'decision', 'runtime', 'workspace', 'audit_codex_home', 'missing'])
def test_complete_C09_archive_rejects_rewritten_binding_and_receipt(tmp_path, monkeypatch, change):
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive, ExpansionArchiveError
    from tests.semantic.support.codex_expansion_policy import canonical_digest
    root = sealed_c09_archive(tmp_path, monkeypatch, actual_audit=change == 'audit_codex_home')
    directory = root / 'turns/turn-01/notice-review'
    path = directory / 'invocation-binding.json'
    binding = json.loads(path.read_text())
    receipt_path = directory / 'receipt.json'
    receipt = json.loads(receipt_path.read_text())
    if change == 'missing': path.unlink()
    else:
        if change == 'schema_content': binding['schema_utf8'] = '{}'
        elif change == 'configuration': binding['configuration']['model'] = 'different-model'
        elif change == 'decision': binding['decision_sha256'] = 'e' * 64
        elif change == 'runtime': binding['runtime']['codex_sha256'] = 'e' * 64
        elif change == 'audit_codex_home': binding['context']['audit_codex_home'] = '/unowned/.codex'
        elif change == 'workspace':
            binding['context']['workspace'] += '-other'
            binding['context']['schema'] = str(Path(binding['context']['workspace']) / 'judgment-schema.json')
        binding['sha256'] = canonical_digest({k: v for k, v in binding.items() if k != 'sha256'})
        receipt['invocation_binding_sha256'] = binding['sha256']
        receipt['sha256'] = canonical_digest({k: v for k, v in receipt.items() if k != 'sha256'})
        path.write_text(json.dumps(binding))
        receipt_path.write_text(json.dumps(receipt))
    with pytest.raises(ExpansionArchiveError):
        verify_expansion_task_archive(root, expected_unit_id='EXP25-C09', expected_version='2025.1', expected_inputs_sha256='a' * 64)


@pytest.mark.parametrize('stream', ['stdout', 'stderr'])
def test_bounded_subprocess_invalid_UTF8_is_explicit_failure_with_exact_raw_evidence(tmp_path, stream):
    import base64
    import os
    import sys
    from tests.semantic.support.codex_harness import run_process
    result = run_process([sys.executable, '-c', 'import sys; getattr(sys, sys.argv[1]).buffer.write(b"ac\\xffcepted")', stream],
        cwd=tmp_path, env=os.environ, timeout=2, max_output_bytes=4096)
    assert result.exit_status != 0
    assert stream in result.output_decoding_error
    assert base64.b64decode(getattr(result, stream + '_base64')) == b'ac\xffcepted'
    assert getattr(result, stream) != 'accepted'


def test_damaged_UTF8_never_passes_live_C09_gate_or_complete_archive(tmp_path, monkeypatch):
    import base64
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive, ExpansionArchiveError
    root = sealed_c09_archive(tmp_path, monkeypatch, damage='invalid_utf8')
    receipt = json.loads((root / 'turns/turn-01/notice-review/receipt.json').read_text())
    assert receipt['outcome'] == 'review_required' and receipt['judgment'] is None
    assert receipt['execution']['exit_status'] == 126
    assert receipt['execution']['process_exit_status'] == 0
    assert receipt['execution']['output_decoding_error'] is not None
    assert b'ac\xffcepted' in base64.b64decode(receipt['execution']['stdout_base64'])
    with pytest.raises(ExpansionArchiveError):
        verify_expansion_task_archive(root, expected_unit_id='EXP25-C09', expected_version='2025.1', expected_inputs_sha256='a' * 64)


def test_receipt_cannot_repair_damaged_original_bytes_into_accepted_judgment(tmp_path, monkeypatch):
    import base64
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive, ExpansionArchiveError
    from tests.semantic.support.codex_expansion_policy import canonical_digest
    root = sealed_c09_archive(tmp_path, monkeypatch, damage='invalid_utf8')
    path = root / 'turns/turn-01/notice-review/receipt.json'
    receipt = json.loads(path.read_text())
    # Reproduce the old lossy repair as an attempted receipt rewrite, keeping
    # the independently recorded original raw byte stream.
    repaired = base64.b64decode(receipt['execution']['stdout_base64']).decode('utf-8', 'ignore')
    events = [json.loads(line) for line in repaired.splitlines()]
    receipt.update(outcome='accepted', error=None, stdout=repaired,
        judgment=json.loads(events[-2]['item']['text']), usage=events[-1]['usage'])
    receipt['execution'].update(exit_status=0, output_decoding_error=None, stdout=repaired)
    receipt['sha256'] = canonical_digest({k: v for k, v in receipt.items() if k != 'sha256'})
    path.write_text(json.dumps(receipt))
    with pytest.raises(ExpansionArchiveError):
        verify_expansion_task_archive(root, expected_unit_id='EXP25-C09', expected_version='2025.1', expected_inputs_sha256='a' * 64)


def test_bounded_invalid_UTF8_timeout_still_reaps_the_actual_process(tmp_path):
    import base64
    import os
    import sys
    from tests.semantic.support.codex_harness import run_process
    pid_file = tmp_path / 'owned-pid.txt'
    result = run_process([sys.executable, '-c',
        'import os,pathlib,sys,time; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); '
        'sys.stdout.buffer.write(b"ac\\xffcepted"); sys.stdout.buffer.flush(); time.sleep(60)', str(pid_file)],
        cwd=tmp_path, env=os.environ, timeout=.5, max_output_bytes=4096)
    assert result.exit_status == 124 and result.timed_out
    assert result.output_decoding_error is not None
    assert base64.b64decode(result.stdout_base64) == b'ac\xffcepted'
    if os.name != 'nt':
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid_file.read_text()), 0)


def test_bounded_subprocess_preserves_valid_UTF8_and_CRLF_bytes(tmp_path):
    import base64
    import os
    import sys
    from tests.semantic.support.codex_harness import run_process
    raw = '有效的中文\r\n'.encode('utf-8')
    result = run_process([sys.executable, '-c',
        'import sys; sys.stdout.buffer.write(bytes.fromhex(sys.argv[1]))', raw.hex()],
        cwd=tmp_path, env=os.environ, timeout=2, max_output_bytes=4096)
    assert result.exit_status == result.process_exit_status == 0
    assert result.output_decoding_error is None
    assert result.stdout.encode('utf-8') == base64.b64decode(result.stdout_base64) == raw


@pytest.mark.parametrize('contract', ['c09', 'expansion'])
def test_gateway_generated_nonhex_identity_reaches_review_and_readonly_archive(tmp_path, monkeypatch, contract):
    from wwise_waapi import transactions
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive
    from tests.semantic.support import codex_c09_notice_adjudication as review
    from tests.semantic.test_codex_expansion_notice_adjudication import sealed_workflow

    monkeypatch.setattr(transactions.secrets, 'randbits', lambda bits: (1 << bits) - 1)
    tx = transactions.new_transaction_id()
    assert tx == 'tx1-zzzzzzzzzzzzzzzzzzzz'
    if contract == 'c09':
        sealed_c09_archive(tmp_path, monkeypatch, transaction_id=tx)
    else:
        sealed_workflow(tmp_path, monkeypatch, 'C09', '2025.1', transaction_id=tx)
    preview = transactions.TransactionStore(tmp_path / 'broker/state').load_preview(tx)
    receipt = json.loads((tmp_path / 'turns/turn-01/notice-review/receipt.json').read_text())
    assert receipt['input']['transaction_id'] == preview.transaction_id == tx
    assert receipt['input']['preview_sha256'] == preview.artifact_hash
    before = {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('rejudgment')))
    replay = verify_expansion_task_archive(tmp_path, expected_unit_id='EXP25-C09',
        expected_version='2025.1', expected_inputs_sha256='a' * 64)
    assert replay['business_pass'] is True
    assert before == {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}


@pytest.mark.parametrize('contract', ['c09', 'expansion'])
def test_notice_review_rejects_malformed_transaction_id_before_reviewer(tmp_path, monkeypatch, contract):
    from wwise_waapi.transactions import TransactionStore, UnsafeTransactionId
    from tests.semantic.support import codex_c09_notice_adjudication as review
    from tests.semantic.support.codex_expansion_notice_adjudication import grade_expansion_notice
    from tests.semantic.support.codex_harness import completed_command_records
    from tests.semantic.test_codex_expansion_notice_adjudication import sealed_workflow

    if contract == 'c09':
        sealed_c09_archive(tmp_path, monkeypatch)
    else:
        sealed_workflow(tmp_path, monkeypatch, 'C09', '2025.1')
    plan = json.loads((tmp_path / 'expansion-plan.json').read_text())
    artifact = TransactionStore(tmp_path / 'broker/state').load_preview('tx1-00000000000000000001').artifact
    stdout = (tmp_path / 'turns/turn-01/events.jsonl').read_text()
    commands = completed_command_records([json.loads(line) for line in stdout.splitlines()], platform_name='posix')
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('reviewer called')))
    grader = review.grade_c09_notice if contract == 'c09' else grade_expansion_notice
    kwargs = {} if contract == 'c09' else {'case_id': 'C09', 'preview_parameters': plan['preview_parameters']}
    invalid_ids = [
        'tx1-' + 'z' * 19, 'tx1-' + 'z' * 21, 'tx1-' + 'Z' * 20,
        *['tx1-' + letter + '0' * 19 for letter in 'ilou'],
        'tx1-' + '0' * 19 + '/', '../transaction', 'legacy/transaction',
        'legacy\\transaction', 'legacy transaction', 'tx1-' + '0' * 20 + '\n',
        '', None, 42,
    ]
    for index, transaction_id in enumerate(invalid_ids):
        with pytest.raises(UnsafeTransactionId):
            grader(SimpleNamespace(stdout=stdout), commands, version='2025.1', execute_expected=True,
                preview_artifact=artifact, before_snapshot=plan['before'], user_prompt=plan['prompts'][0],
                transaction_id=transaction_id, other_gates={'authorization': True},
                root=tmp_path / f'rejected-{index}', options=None, **kwargs)
        assert not (tmp_path / f'rejected-{index}/notice-review').exists()


@pytest.mark.parametrize('contract', ['c09', 'expansion'])
def test_gateway_legacy_identity_preserves_review_and_archive_binding(tmp_path, monkeypatch, contract):
    from tests.semantic.support.codex_expansion_archive import verify_expansion_task_archive
    from tests.semantic.support import codex_c09_notice_adjudication as review
    from tests.semantic.test_codex_expansion_notice_adjudication import sealed_workflow

    tx = 'legacy-transaction_01.record'
    if contract == 'c09':
        sealed_c09_archive(tmp_path, monkeypatch, transaction_id=tx)
    else:
        sealed_workflow(tmp_path, monkeypatch, 'C09', '2025.1', transaction_id=tx)
    monkeypatch.setattr(review, 'run_process', lambda *a, **k: (_ for _ in ()).throw(AssertionError('rejudgment')))
    before = {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    replay = verify_expansion_task_archive(tmp_path, expected_unit_id='EXP25-C09',
        expected_version='2025.1', expected_inputs_sha256='a' * 64)
    assert replay['business_pass'] is True
    assert before == {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
