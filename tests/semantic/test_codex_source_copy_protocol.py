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


def run_source_protocol(tmp_path, monkeypatch, *, dirty=False, decline_stage=None, swap_child_parent=False, resume_stage=None, policy="ask_before_changes", wrong_user_turn=False):
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
        assert evidence.complete and all(record.succeeded for record in evidence.records)
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
