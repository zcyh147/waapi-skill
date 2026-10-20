"""Actual Gateway receipts through the formal Broker; fake WAAPI only."""
from copy import deepcopy
import json
import shlex
import pytest
from pathlib import Path
from types import SimpleNamespace

from tests.unit.test_source_copy_saved_continuation_gateway import saved_source_task, SOURCE, DEST
from tests.unit.test_field_interface_closure_gateway import gateway
from tests.semantic.support.codex_gateway_broker import CodexGatewayBroker
from tests.semantic.support.typed_gateway_input import _render_step_arguments
from tests.support.platform_process import run_model_argv


SKILL = Path(__file__).parents[2] / 'skills/waapi-skill'


def source_request():
    return {'contract': 'waapi-skill.operation-request/v1', 'version': '2021.1',
        'operation': 'object.copy', 'arguments': {
            'object': {'kind': 'id', 'value': SOURCE},
            'parent': {'kind': 'id', 'value': DEST}, 'on_name_conflict': 'fail'}}


def run_source_protocol(tmp_path, monkeypatch, *, dirty=False, decline_stage=None, swap_child_parent=False, resume_stage=None, policy="ask_before_changes", wrong_user_turn=False, captured_brokers=None, stop_after_turn=None):
    from tests.semantic.support.codex_source_copy_protocol import build_source_copy_saved_proof_protocol
    import tests.semantic.support.codex_expansion_reconciliation as reconciliation
    from tests.semantic.support.codex_harness import prepare_workspace_skill_install, _business_draft_continuation_candidates
    runtime, writes, task = saved_source_task(tmp_path)
    if dirty:
        from tests.unit.test_field_interface_closure_gateway import PROJECT
        task.objects[PROJECT]['workunitIsDirty'] = True
    protocol = build_source_copy_saved_proof_protocol(source_request(), dirty_baseline=dirty, decline_stage=decline_stage, resume_stage=resume_stage, policy=policy)
    workspace = tmp_path / 'agent-workspace'
    installed = prepare_workspace_skill_install(workspace, SKILL)
    broker = CodexGatewayBroker(skill_source=SKILL, invocation_skill_source=installed,
        expected_steps=protocol.steps, runner_cwd=workspace,
        expected_wwise_version='2021.1', project_modification_policy=policy, runner_environment={**task.env,
            'WWISE_WAAPI_HOST': '127.0.0.1', 'WWISE_WAAPI_PORT': '31337'},
        working_root=tmp_path / 'broker')
    if captured_brokers is not None:
        captured_brokers.append(broker)
    def provisioning(argv, *, environment, **kwargs):
        code, payload = gateway.execute_gateway(argv[3:], env=environment)
        return SimpleNamespace(returncode=code, stdout=json.dumps(payload), stderr='')
    monkeypatch.setattr(reconciliation, 'run_owned_gateway', provisioning)
    def launch(argv, *, runner_env):
        code, payload = gateway.execute_gateway(argv[3:], env=runner_env, client_factory=lambda url: task)
        if swap_child_parent and argv[3] == 'continue-source-copy-proof' and 'source_copy_saved_proof' in payload:
            payload = deepcopy(payload)
            payload['source_copy_saved_proof']['parent'] = {'transaction_id': 'another-parent'}
        return SimpleNamespace(returncode=code, stdout=json.dumps(payload), stderr='')
    monkeypatch.setattr(broker, '_launch_runner', launch)
    monkeypatch.setattr(broker, '_communicate_runner', lambda process: (process.stdout, process.stderr))
    responses, commands = {}, []
    prompts = ['Copy the pinned Source.'] + ['Confirm the current Preview.'] * (len(protocol.turn_prefix_counts) - 1)
    for step in protocol.steps:
        if step.source_copy_proof_role is not None and step.source_copy_proof_role.is_selection:
            prompts[step.source_copy_proof_role.user_turn - 1] = (
                'Confirm the current Preview.' if wrong_user_turn else step.source_copy_proof_role.user_prompt)
    with broker:
        environment = broker.model_environment_overrides()
        turn = 1
        for index, step in enumerate(protocol.steps):
            if stop_after_turn is not None and index >= protocol.turn_prefix_counts[stop_after_turn - 1]:
                break
            while index >= protocol.turn_prefix_counts[turn - 1]:
                turn += 1
            broker.bind_source_copy_user_turn(turn, prompts[turn - 1])
            argv = ['python', str(installed / 'scripts/run.py'), 'gateway.py', step.subcommand,
                *_render_step_arguments(step, responses)]
            command = shlex.join(argv)
            if step.source_copy_proof_role is not None and step.source_copy_proof_role.is_selection:
                source = responses[step.source_copy_proof_role.choice_step]
                choice = source['continuation']['next_command'] if step.source_copy_proof_role.is_decline else source['next_command']
                command = choice[choice['copy_instruction']['source_field']]
                assert shlex.split(command)[3:] == argv[3:]
                argv = shlex.split(command)
            elif commands:
                previous = next(reversed(responses.values()))
                next_command = previous.get('next_command')
                if next_command is not None:
                    command = next_command[next_command['copy_instruction']['source_field']]
                    assert shlex.split(command)[3:] == argv[3:]
                else:
                    _, candidates = _business_draft_continuation_candidates(previous, platform_name='posix')
                    matching = []
                    for mode, candidate in candidates:
                        prefix = shlex.split(candidate)
                        if prefix[3:] == argv[3:len(prefix)]:
                            matching.append((len(prefix), candidate, mode))
                    if matching:
                        length, candidate, mode = max(matching)
                        command = candidate + (' ' + shlex.join(argv[length:]) if mode == 'prefix' and argv[length:] else '')
                argv = shlex.split(command)
            completed = run_model_argv(argv, environment=environment, cwd=workspace,
                capture_output=True, text=True, timeout=30)
            if wrong_user_turn and completed.returncode != 0:
                assert 'Source-copy selection has no bound explicit user turn' in completed.stderr
                return protocol, broker.evidence(), commands, responses, writes, prompts
            if swap_child_parent and completed.returncode != 0:
                assert 'Source-copy owned continuation binding is invalid' in completed.stderr
                return protocol, broker.evidence(), commands, responses, writes, prompts
            assert completed.returncode == 0, completed.stderr
            payload = json.loads(completed.stdout)
            responses[step.name] = payload
            commands.append({'command': command, 'argv': argv,
                'aggregated_output': completed.stdout, 'exit_code': 0, 'status': 'completed',
                'has_shell_operators': False, 'parse_error': '', 'parser_kind': 'posix-native'})
        evidence = broker.evidence()
        assert evidence.complete is (stop_after_turn is None)
        assert all(record.succeeded for record in evidence.records)
        (tmp_path / 'original-broker.json').write_text(json.dumps(evidence.as_dict()))
        (tmp_path / 'original-commands.json').write_text(json.dumps(commands))
    return protocol, evidence, commands, responses, writes, prompts


def test_clean_source_copy_formal_broker_owns_generated_final_save(tmp_path, monkeypatch):
    protocol, evidence, commands, responses, writes, prompts = run_source_protocol(tmp_path, monkeypatch)
    assert responses[protocol.steps[-1].name]['verification']['verification_scope']['complete_copy_preservation'] is True
    assert [uri.rsplit('.', 1)[-1] for uri, args in writes] == ['copy', 'save']


def test_dirty_source_copy_generated_children_and_parent_cas_replay_same_broker_archive(tmp_path, monkeypatch):
    from tests.semantic.support.codex_prompt_provenance_v3 import serialize_protocol, deserialize_protocol
    from tests.semantic.run_codex_skill_campaign import _validate_heavy_v3_broker_records
    protocol, evidence, commands, responses, writes, prompts = run_source_protocol(tmp_path, monkeypatch, dirty=True)
    assert [uri.rsplit('.', 1)[-1] for uri, args in writes] == ['save', 'copy', 'save']
    restored = deserialize_protocol(serialize_protocol(protocol))
    assert restored == protocol
    from tests.semantic.support.codex_harness import gateway_continuation_binding_errors
    errors = gateway_continuation_binding_errors(commands, evidence.records, platform_name='posix')
    assert not errors, '\n'.join(errors)
    _validate_heavy_v3_broker_records(json.loads((tmp_path / 'original-broker.json').read_text())['records'], task_root=tmp_path,
        steps=restored.steps, command_records=commands,
        options=SimpleNamespace(skill_source=SKILL, windows_powershell_core_host=None),
        version='2021.1', label='Source-owned deterministic archive',
        expected_project_modification_policy='ask_before_changes')
    issue = next(index for index, step in enumerate(protocol.steps) if step.source_copy_proof_role is not None)
    for fault in ('changed_bytes', 'lost_reply'):
        altered = deepcopy(commands)
        if fault == 'changed_bytes':
            altered[issue]['command'] += ' '
        else:
            altered[issue]['aggregated_output'] = ''
        assert gateway_continuation_binding_errors(altered, evidence.records, platform_name='posix'), fault


@pytest.mark.parametrize('stage', ['baseline', 'final'])
def test_source_decline_uses_earlier_authenticated_choice_and_explicit_user_turn_in_archive(tmp_path, monkeypatch, stage):
    from tests.semantic.run_codex_skill_campaign import _validate_heavy_v3_broker_result
    from tests.semantic.support.codex_campaign import CampaignEvidenceError
    protocol, evidence, commands, responses, writes, prompts = run_source_protocol(
        tmp_path, monkeypatch, dirty=stage == 'baseline', decline_stage=stage)
    assert [uri.rsplit('.', 1)[-1] for uri, args in writes] == ['copy']
    assert responses[protocol.steps[-1].name]['verification']['verification_scope']['complete_copy_preservation'] is False
    def replay(user_prompts):
        _validate_heavy_v3_broker_result(json.loads((tmp_path / 'original-broker.json').read_text()),
            task_root=tmp_path, protocol=protocol, command_records=commands,
            options=SimpleNamespace(skill_source=SKILL, windows_powershell_core_host=None),
            version='2021.1', expected_project_modification_policy='ask_before_changes', user_prompts=user_prompts)
    replay(prompts)
    with pytest.raises(CampaignEvidenceError):
        replay(['Confirm the current Preview.'] * len(prompts))
    selected = next(index for index, step in enumerate(protocol.steps)
        if step.source_copy_proof_role is not None and step.source_copy_proof_role.is_decline)
    choice_index = next(index for index, step in enumerate(protocol.steps)
        if step.name == protocol.steps[selected].source_copy_proof_role.choice_step)
    original_commands = deepcopy(commands)
    for fault in ('lost_choice_frame', 'changed_selected_bytes'):
        if fault == 'lost_choice_frame':
            commands[choice_index]['aggregated_output'] = ''
        else:
            commands[selected]['command'] += ' '
        with pytest.raises(CampaignEvidenceError):
            replay(prompts)
        commands[:] = deepcopy(original_commands)
    from tests.semantic.support.codex_gateway_broker import reconcile_gateway_commands
    from tests.semantic.support.codex_task_runner_v3 import _bind_gateway_prefix_reconciliation
    raw = reconcile_gateway_commands([command['argv'] for command in commands], evidence,
        skill_source=SKILL, invocation_skill_source=tmp_path / 'agent-workspace/.agents/skills/waapi-skill')
    bound = _bind_gateway_prefix_reconciliation(raw, command_records=commands, broker_evidence=evidence,
        platform_name='posix', source_copy_protocol=protocol, source_copy_user_prompts=prompts)
    assert bound.passed, bound.errors


def test_generated_save_cannot_claim_another_public_parent(tmp_path, monkeypatch):
    protocol, evidence, commands, responses, writes, prompts = run_source_protocol(tmp_path, monkeypatch, swap_child_parent=True)
    assert not evidence.complete and any(not record.succeeded for record in evidence.records)
    assert [uri.rsplit('.', 1)[-1] for uri, args in writes] == ['copy']


@pytest.mark.parametrize('stage', ['baseline', 'final'])
def test_later_turn_reuses_retained_accept_frame_and_same_unattempted_child(tmp_path, monkeypatch, stage):
    from tests.semantic.run_codex_skill_campaign import _validate_heavy_v3_broker_result
    from tests.semantic.support.codex_campaign import CampaignEvidenceError
    protocol, evidence, commands, responses, writes, prompts = run_source_protocol(
        tmp_path, monkeypatch, dirty=stage == 'baseline', resume_stage=stage)
    original, resumed = responses[stage + '.issued-save'], responses[stage + '.resume']
    assert original['draft']['draft_id'] == resumed['draft']['draft_id']
    assert original['task_authority'] == resumed['task_authority']
    assert original['draft']['revision'] == resumed['draft']['revision'] == 3
    assert [uri.rsplit('.', 1)[-1] for uri, args in writes] == (['save', 'copy', 'save'] if stage == 'baseline' else ['copy', 'save'])
    def replay(user_prompts):
        _validate_heavy_v3_broker_result(json.loads((tmp_path / 'original-broker.json').read_text()),
            task_root=tmp_path, protocol=protocol, command_records=commands,
            options=SimpleNamespace(skill_source=SKILL, windows_powershell_core_host=None),
            version='2021.1', expected_project_modification_policy='ask_before_changes', user_prompts=user_prompts)
    replay(prompts)
    with pytest.raises(CampaignEvidenceError):
        replay(['Confirm the current Preview.'] * len(prompts))


@pytest.mark.parametrize('policy', ['read_only', 'allow_changes'])
def test_source_generated_save_keeps_existing_project_policy_boundary(tmp_path, monkeypatch, policy):
    from tests.semantic.run_codex_skill_campaign import _validate_heavy_v3_broker_result
    protocol, evidence, commands, responses, writes, prompts = run_source_protocol(tmp_path, monkeypatch, policy=policy)
    assert len(protocol.turn_prefix_counts) == 1
    if policy == 'read_only':
        assert not writes and [step.subcommand for step in protocol.steps] == ['operation-schema']
    else:
        assert [uri.rsplit('.', 1)[-1] for uri, args in writes] == ['copy', 'save']
        assert not any(step.subcommand in {'confirm', 'transaction-show'} for step in protocol.steps)
        _validate_heavy_v3_broker_result(json.loads((tmp_path / 'original-broker.json').read_text()),
            task_root=tmp_path, protocol=protocol, command_records=commands,
            options=SimpleNamespace(skill_source=SKILL, windows_powershell_core_host=None),
            version='2021.1', expected_project_modification_policy=policy, user_prompts=prompts)


@pytest.mark.parametrize('selection', ['decline', 'resume'])
def test_source_later_selection_without_explicit_user_intent_rejected_before_save(tmp_path, monkeypatch, selection):
    protocol, evidence, commands, responses, writes, prompts = run_source_protocol(tmp_path, monkeypatch,
        decline_stage='final' if selection == 'decline' else None,
        resume_stage='final' if selection == 'resume' else None, wrong_user_turn=True)
    assert not evidence.complete
    assert [uri.rsplit('.', 1)[-1] for uri, args in writes] == ['copy']


def test_source_protocol_rejects_unknown_command_role_fields_and_other_versions():
    from dataclasses import replace
    from tests.semantic.support.codex_source_copy_protocol import build_source_copy_saved_proof_protocol
    from tests.semantic.support.codex_gateway_broker import validate_operation_draft_protocol_steps
    from tests.semantic.support.codex_prompt_provenance_v3 import serialize_protocol, deserialize_protocol, PromptProvenanceError
    protocol = build_source_copy_saved_proof_protocol(source_request())
    marked = next(index for index, step in enumerate(protocol.steps) if step.source_copy_proof_role is not None)
    unknown = replace(protocol.steps[0], name='unknown.step', subcommand='unknown-command')
    with pytest.raises(ValueError, match='command outside the closed Source-copy protocol'):
        validate_operation_draft_protocol_steps((*protocol.steps, unknown))
    archive = serialize_protocol(protocol)
    archive['steps'][marked]['source_copy_proof_role']['unknown_authority'] = True
    with pytest.raises(PromptProvenanceError):
        deserialize_protocol(archive)
    for version in ('2022.1', '2023.1', '2024.1', '2025.1'):
        with pytest.raises(ValueError):
            build_source_copy_saved_proof_protocol({**source_request(), 'version': version})


@pytest.mark.parametrize('branch', ['dirty', 'baseline_decline', 'final_decline', 'resume'])
def test_mandatory_task_result_composer_consumer_seals_source_chains(tmp_path, monkeypatch, branch):
    from tests.semantic.support.codex_typed_draft_evidence_v3 import validate_typed_draft_evidence, TypedDraftEvidenceError
    protocol, evidence, commands, responses, writes, prompts = run_source_protocol(tmp_path, monkeypatch,
        dirty=branch in {'dirty', 'baseline_decline', 'resume'},
        decline_stage={'baseline_decline': 'baseline', 'final_decline': 'final'}.get(branch),
        resume_stage='baseline' if branch == 'resume' else None)
    arguments = dict(state_directory=tmp_path / 'broker/state', steps=protocol.steps,
        broker_records=json.loads((tmp_path / 'original-broker.json').read_text())['records'],
        user_prompts=prompts, turn_prefix_counts=protocol.turn_prefix_counts)
    sealed = validate_typed_draft_evidence(**arguments)
    assert sealed['flow_count'] == (3 if branch in {'dirty', 'resume'} else 2)
    assert sealed == validate_typed_draft_evidence(**arguments, allow_cleaned_file_evidence=True)
    changed = deepcopy(arguments['broker_records'])
    child = next(index for index, step in enumerate(protocol.steps)
        if step.source_copy_proof_role is not None and step.source_copy_proof_role.issues_save)
    changed[child]['payload']['task_authority'] = responses['tx01.draft-start']['task_authority']
    with pytest.raises(TypedDraftEvidenceError):
        validate_typed_draft_evidence(**{**arguments, 'broker_records': changed})
    terminal = next(index for index in reversed(range(len(arguments['broker_records'])))
        if 'verification_scope' in arguments['broker_records'][index]['payload'].get('verification', {}))
    for fault in ('omitted_scope', 'changed_scope'):
        changed = deepcopy(arguments['broker_records'])
        verification = changed[terminal]['payload']['verification']
        if fault == 'omitted_scope':
            verification.pop('verification_scope')
        else:
            verification['verification_scope'] = {'complete_copy_preservation': 'tampered'}
        with pytest.raises(TypedDraftEvidenceError):
            validate_typed_draft_evidence(**{**arguments, 'broker_records': changed})
    records_dir = tmp_path / 'broker/state/operation-drafts-v1/records'
    original = next(records_dir.glob('*.json'))
    extra = records_dir / 'unexpected.json'
    extra.write_bytes(original.read_bytes())
    with pytest.raises(TypedDraftEvidenceError):
        validate_typed_draft_evidence(**arguments)



def source_provenance(root, protocol, prompts):
    import hashlib
    from tests.semantic.support.codex_prompt_provenance_v3 import write_prompt_provenance
    (root / 'evidence').mkdir(parents=True, exist_ok=True)
    (root / 'owned').mkdir(exist_ok=True)
    scenario = SimpleNamespace(id='SOURCE-OWNED-01', api='ak.wwise.core.object.copy', versions=('2021.1',),
        prompt=prompts[0], prompt_sha256=hashlib.sha256(prompts[0].encode()).hexdigest(), visible_inputs=(), fixture={},
        primary_dispatch=SimpleNamespace(count=1), confirmation_turn_count=len(prompts) - 1,
        confirmation_prompt='Confirm the current Preview.', follow_up_prompts=tuple(prompts[1:]),
        scenario_family='source-copy-proof', render_prompt=lambda values: prompts[0])
    return scenario, write_prompt_provenance(scenario=scenario, version='2021.1', scenario_root=root,
        prompts=prompts, visible_values={}, protocol=protocol)


def test_actual_task_runner_seals_and_replays_original_dirty_source_result(tmp_path, monkeypatch):
    import hashlib
    import shutil
    from dataclasses import replace
    from tests.semantic.support import codex_task_runner_v3 as runner
    from tests.semantic.support.codex_source_copy_protocol import build_source_copy_saved_proof_protocol
    from tests.semantic.support.codex_business_oracle_plan_v3 import write_business_oracle_plan
    from tests.semantic.support.codex_gateway_broker import reconcile_gateway_command_prefix
    from tests.semantic.support.codex_typed_draft_evidence_v3 import validate_typed_draft_evidence
    from tests.semantic.run_codex_skill_campaign import _validate_heavy_v3_broker_result
    scenario_root = tmp_path / 'scenario'
    root = scenario_root / 'evidence/codex-task'
    protocol = build_source_copy_saved_proof_protocol(source_request(), dirty_baseline=True)
    prompts = ['Copy the pinned Source.'] + ['Confirm the current Preview.'] * (len(protocol.turn_prefix_counts) - 1)
    scenario, provenance = source_provenance(scenario_root, protocol, prompts)
    plan = write_business_oracle_plan(scenario_id=scenario.id, version='2021.1', api=scenario.api,
        runner='project', family='object', scenario_root=scenario_root,
        fixture_spec={'kind': 'scenario_fixture', 'sha256': hashlib.sha256(b'{}').hexdigest()},
        protocol_sha256=provenance.payload['protocol']['sha256'], provenance_sha256=provenance.sha256,
        primary_dispatch_count=1, payload_bindings={'primary_steps': ['tx01.execute'], 'verification_steps': ['tx01.saved-verify']},
        assertion_ids=('common.task-receipt',), static_expectation={}, live_binding={}, delta_rules=())
    root.mkdir()
    captured = []
    _, original, commands, _, _, _ = run_source_protocol(root, monkeypatch, dirty=True, captured_brokers=captured)
    retained = tmp_path / 'retained-original'
    shutil.move(str(root), retained)
    # Replay only the external Codex boundary. Packet payloads, argv, raw output,
    # fixed state paths and the actual mandatory task-result consumer stay intact.
    class RetainedBroker:
        prefix = 0
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def __getattr__(self, name): return getattr(captured[0], name)
        def model_environment_overrides(self): return {}
        def evidence(self):
            return replace(original, consumed_step_names=original.consumed_step_names[:self.prefix],
                records=original.records[:self.prefix], complete=self.prefix == len(protocol.steps),
                terminal_state='COMPLETE' if self.prefix == len(protocol.steps) else 'RUNNING')
        def reconcile_prefix(self, argv, *, expected_step_count):
            return reconcile_gateway_command_prefix(argv, self.evidence(), expected_step_count=expected_step_count,
                skill_source=SKILL, invocation_skill_source=root / 'agent-workspace/.agents/skills/waapi-skill')
    broker = RetainedBroker()
    class RetainedTask:
        def __init__(self, *args, **kwargs): self.turn = 0
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def run_initial(self, prompt, *, output_dir):
            if self.turn == 0:
                for path in retained.iterdir():
                    if path.name == 'agent-workspace': continue
                    target = root / path.name
                    if path.is_dir(): shutil.copytree(path, target)
                    else: shutil.copy2(path, target)
            previous = broker.prefix
            broker.prefix = protocol.turn_prefix_counts[self.turn]
            self.turn += 1
            return SimpleNamespace(thread_id='deterministic-retained-transport',
                command_facts=SimpleNamespace(command_records=tuple(SimpleNamespace(**value)
                    for value in commands[previous:broker.prefix]), skill_read_files=()),
                session_audit=SimpleNamespace(incomplete_command_count=0))
        run_followup = run_initial
    monkeypatch.setattr(runner, 'CodexGatewayBroker', lambda **kwargs: broker)
    monkeypatch.setattr(runner, 'CodexCliTask', RetainedTask)
    monkeypatch.setattr(runner, '_grade_common_turn', lambda *args, **kwargs: ((), {'external_codex_stub': True}))
    monkeypatch.setattr(runner, '_archive_turn', lambda *args, **kwargs: None)
    result = runner.run_v3_codex_task(scenario_id=scenario.id, version='2021.1', scenario=scenario,
        prompts=prompts, protocol=protocol, task_root=root, skill_source=SKILL,
        codex_binary=tmp_path / 'unused-codex', auth_json=tmp_path / 'unused-auth', model='deterministic-no-model',
        reasoning_effort='medium', service_tier='default', timeout_seconds=10,
        runner_environment={}, required_reference=None, business_oracle_plan=plan)
    assert result.passed
    sealed = json.loads((root / 'task-result.json').read_text())
    assert sealed['composer_evidence']['flow_count'] == 3
    _validate_heavy_v3_broker_result(sealed['broker'], task_root=root, protocol=protocol, command_records=commands,
        options=SimpleNamespace(skill_source=SKILL, windows_powershell_core_host=None), version='2021.1',
        expected_project_modification_policy='ask_before_changes', user_prompts=provenance.prompts)
    assert sealed['composer_evidence'] == validate_typed_draft_evidence(state_directory=root / 'broker/state',
        steps=protocol.steps, broker_records=sealed['broker']['records'], allow_cleaned_file_evidence=True,
        user_prompts=provenance.prompts, turn_prefix_counts=protocol.turn_prefix_counts)



def test_retryable_source_selection_prefix_uses_sealed_full_turn_provenance(tmp_path, monkeypatch):
    from tests.semantic.run_codex_skill_campaign import _validate_heavy_v3_retryable_partial_broker
    from tests.semantic.support.codex_campaign import CampaignEvidenceError
    from tests.semantic.support.codex_prompt_provenance_v3 import read_prompt_provenance, PromptProvenanceError
    protocol, evidence, commands, responses, writes, prompts = run_source_protocol(tmp_path, monkeypatch,
        resume_stage='final', stop_after_turn=3)
    assert [uri.rsplit('.', 1)[-1] for uri, args in writes] == ['copy']
    scenario, written = source_provenance(tmp_path, protocol, prompts)
    provenance = read_prompt_provenance(written.path, scenario=scenario, version='2021.1', scenario_root=tmp_path,
        expected_protocol=protocol, expected_prompts=prompts, require_paths=True)
    def replay(user_prompts):
        _validate_heavy_v3_retryable_partial_broker(json.loads((tmp_path / 'original-broker.json').read_text()),
            task_root=tmp_path, previous_prefix=protocol.turn_prefix_counts[2], failed_prefix=protocol.turn_prefix_counts[3],
            protocol=protocol, command_records=commands,
            options=SimpleNamespace(skill_source=SKILL, windows_powershell_core_host=None), version='2021.1',
            expected_project_modification_policy='ask_before_changes', user_prompts=user_prompts)
    replay(provenance.prompts)
    for malformed in ((), ['Confirm the current Preview.'] * len(prompts)):
        with pytest.raises(CampaignEvidenceError): replay(malformed)
    written.path.write_text('{}')
    with pytest.raises(PromptProvenanceError):
        read_prompt_provenance(written.path, scenario=scenario, version='2021.1', scenario_root=tmp_path,
            expected_protocol=protocol, expected_prompts=prompts, require_paths=True)



@pytest.mark.parametrize('fault', ['ordinary_copy', 'wrong_version', 'altered_role'])
def test_source_provenance_writer_and_strict_reader_reject_unowned_copy(tmp_path, fault):
    from dataclasses import replace
    import hashlib
    from tests.semantic.support.codex_eval_protocol_v3 import V3GatewayProtocol, build_object_lifecycle_business_transaction_steps
    from tests.semantic.support.codex_source_copy_protocol import build_source_copy_saved_proof_protocol
    from tests.semantic.support.codex_prompt_provenance_v3 import (
        write_prompt_provenance, read_prompt_provenance, serialize_protocol, PromptProvenanceError, HEAVY_APIS)
    protocol = build_source_copy_saved_proof_protocol(source_request())
    prompts = ['Copy the pinned Source.'] + ['Confirm the current Preview.'] * (len(protocol.turn_prefix_counts) - 1)
    scenario, sealed = source_provenance(tmp_path, protocol, prompts)
    assert scenario.api not in HEAVY_APIS
    read_prompt_provenance(sealed.path, scenario=scenario, version='2021.1', scenario_root=tmp_path,
        expected_protocol=protocol, expected_prompts=prompts, require_paths=True)
    changed_protocol, version = protocol, '2021.1'
    if fault == 'ordinary_copy':
        steps = build_object_lifecycle_business_transaction_steps(source_request(), label='tx01')
        changed_protocol = V3GatewayProtocol(steps, (len(steps),))
    elif fault == 'wrong_version':
        version = '2022.1'
    else:
        steps = list(protocol.steps)
        index = next(index for index, step in enumerate(steps) if step.source_copy_proof_role is not None)
        with pytest.raises(ValueError):
            steps[index] = replace(steps[index], source_copy_proof_role=replace(
                steps[index].source_copy_proof_role, parent_start='another-parent'))
            V3GatewayProtocol(tuple(steps), protocol.turn_prefix_counts)
    if fault != 'altered_role':
        with pytest.raises(PromptProvenanceError):
            write_prompt_provenance(scenario=scenario, version=version, scenario_root=tmp_path,
                prompts=prompts, visible_values={}, protocol=changed_protocol)
    payload = json.loads(sealed.path.read_text())
    payload['version'] = version
    payload['protocol']['value'] = serialize_protocol(changed_protocol)
    if fault == 'altered_role':
        payload['protocol']['value']['steps'][index]['source_copy_proof_role']['parent_start'] = 'another-parent'
    payload['protocol']['sha256'] = hashlib.sha256(json.dumps(payload['protocol']['value'], ensure_ascii=False,
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    sealed.path.write_text(json.dumps(payload))
    with pytest.raises(PromptProvenanceError):
        read_prompt_provenance(sealed.path, scenario=scenario, version=version, scenario_root=tmp_path,
            require_paths=True)
