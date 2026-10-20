"""Closed generated Save roles for the pinned Source-copy semantic workflow.

These are runner-owned protocol facts, never Agent input or a new public lane.
Ordinary protocols retain their original Draft topology and response checks.
"""
from dataclasses import dataclass, replace
from typing import Any, Mapping

SAVE = 'ak.wwise.core.project.save'
DECLINE_SAVE_PROMPT = ('Do not save the project for this proof. Decline the additional Save '
    'and finish with the available copy verification scope.')
RESUME_SAVE_PROMPT = ('Resume the same optional Source-proof Save using the earlier Gateway-issued '
    'parent continuation. Do not repeat the copy or any Save execution.')


@dataclass(frozen=True, slots=True)
class SourceCopyProofRole:
    kind: str
    parent_start: str
    choice_step: str
    user_turn: int = 0

    def __post_init__(self):
        if self.kind not in {'baseline_save', 'final_save', 'baseline_return', 'baseline_decline', 'final_decline', 'baseline_resume', 'final_resume'}:
            raise ValueError('unknown Source-copy proof role')
        if any(not isinstance(value, str) or not value for value in (self.parent_start, self.choice_step)):
            raise ValueError('Source-copy role requires exact prior response names')
        if type(self.user_turn) is not int or (self.user_turn < 2 if self.is_selection else self.user_turn != 0):
            raise ValueError('Source-copy selection must bind its later explicit user turn')

    @property
    def issues_save(self):
        return self.kind in {'baseline_save', 'final_save'}

    @property
    def is_decline(self):
        return self.kind in {'baseline_decline', 'final_decline'}

    @property
    def is_resume(self):
        return self.kind in {'baseline_resume', 'final_resume'}

    @property
    def is_selection(self):
        return self.is_decline or self.is_resume

    @property
    def user_prompt(self):
        return DECLINE_SAVE_PROMPT if self.is_decline else RESUME_SAVE_PROMPT


def source_copy_decline_command(payload, *, stage):
    """Validate the closed producer choice; return its exact envelope unchanged."""
    from tests.semantic.support.codex_gateway_broker import GatewayInvocationError
    try:
        choice = payload['continuation']
        if (set(choice) != {'contract', 'stage', 'selection_source', 'save_notice',
                'evaluate_in_order', 'first_true_choice_is_the_only_next_action', 'decline_outcome', 'next_command'}
                or choice['contract'] != 'waapi-skill.source-copy-save-choice/v1'
                or choice['stage'] != stage or stage not in {'baseline', 'final'}
                or choice['selection_source'] != 'explicit_decline_otherwise_existing_policy'
                or choice['save_notice'] != 'Save persists all pending changes in the current project, including changes outside this copy.'
                or choice['first_true_choice_is_the_only_next_action'] is not True
                or choice['evaluate_in_order'] != [
                    {'choice': 'decline_save', 'condition': 'user_explicitly_declines_save', 'command_pointer': '/continuation/next_command'},
                    {'choice': 'prepare_save', 'condition': 'otherwise_continue_under_existing_policy', 'command_pointer': '/next_command'}]
                or choice['decline_outcome'] != {'executes_save': False, 'complete_copy_preservation': False,
                    'remaining_scope': 'ordinary_live_copy_observations', 'remaining_action': (
                        'normal_copy_preview_and_authorization' if stage == 'baseline'
                        else 'finalize_existing_copy_without_complete_saved_proof')}
                or choice['next_command']['gateway_argv'] != [*payload['next_command']['gateway_argv'], '--decline-save']):
            raise ValueError('choice fields, condition or owner differ')
        return choice['next_command']
    except Exception as exc:
        raise GatewayInvocationError(f'Source-copy refusal disclosure is invalid: {exc}') from exc


def source_copy_selection_bindings(steps, records, *, user_prompts=(), turn_prefix_counts=()):
    """Derive choice indices from sealed protocol and actual trusted user turns."""
    indexes = {step.name: index for index, step in enumerate(steps)}
    selections = {}
    for index, step in enumerate(steps):
        role = step.source_copy_proof_role
        if role is None or not role.is_selection:
            continue
        turn = role.user_turn
        if (turn > len(user_prompts) or len(user_prompts) != len(turn_prefix_counts)
                or user_prompts[turn - 1] != role.user_prompt
                or not turn_prefix_counts[turn - 2] <= index < turn_prefix_counts[turn - 1]):
            raise ValueError('Source-copy refusal is not in its explicit user-selection turn')
        source = indexes.get(role.choice_step, index)
        if source >= index or source >= len(records):
            raise ValueError('Source-copy refusal has no earlier authenticated choice frame')
        selections[index] = (source, 'decline' if role.is_decline else 'resume')
    return selections


def validate_source_copy_steps(steps):
    """Check each issued capability separately, retaining ordinary validation."""
    from tests.semantic.support.codex_gateway_broker import ResponseBinding, validate_operation_draft_protocol_steps
    by_name = {step.name: step for step in steps}
    marked = [step for step in steps if step.source_copy_proof_role is not None]
    if len(by_name) != len(steps):
        raise ValueError('Source-copy protocol names must be unique')
    roots = {step.source_copy_proof_role.parent_start for step in marked}
    if len(roots) != 1:
        raise ValueError('Source-copy proof requires one owning copy Draft')
    root_name, = roots
    root = by_name.get(root_name)
    if root is None or root.subcommand != 'draft-start' or root.arguments != ('object.copy',):
        raise ValueError('Source-copy proof has no exact ordinary copy owner')
    from tests.semantic.support.codex_draft_commands import DRAFT_GATEWAY_SUBCOMMANDS
    owners = {step.name for step in marked if step.source_copy_proof_role.issues_save} | {root_name}
    groups = {name: [] for name in owners}
    for step in steps:
        role = step.source_copy_proof_role
        if role:
            if step.subcommand != 'continue-source-copy-proof' or role.choice_step not in by_name:
                raise ValueError('Source-copy role has no public continuation/prior source')
            if steps.index(by_name[role.choice_step]) >= steps.index(step):
                raise ValueError('Source-copy role source must precede its continuation')
            if role.kind in {'baseline_save', 'baseline_decline', 'baseline_resume'}:
                expected = (ResponseBinding(role.choice_step, '/draft/draft_id'), '--task-authority',
                    ResponseBinding(root_name, '/task_authority'), '--expected-revision',
                    ResponseBinding(role.choice_step, '/draft/revision'))
                if by_name[role.choice_step].subcommand != 'draft-check':
                    raise ValueError('Baseline Save must follow its checked parent')
            elif role.kind in {'final_save', 'final_decline', 'final_resume'}:
                expected = (ResponseBinding(role.choice_step, '/transaction_id'),)
                if by_name[role.choice_step].subcommand != 'verify':
                    raise ValueError('Final Save must follow pending copy verification')
            else:
                issued = by_name[role.choice_step]
                if not issued.source_copy_proof_role or issued.source_copy_proof_role.kind != 'baseline_save':
                    raise ValueError('Baseline return must consume its generated baseline child')
                expected = (ResponseBinding(role.choice_step, '/draft/draft_id'),)
            if role.is_decline:
                expected = (*expected, '--decline-save')
            if step.arguments != expected:
                raise ValueError('Source-copy continuation does not bind its exact issued owner')
            if role.is_resume:
                prior = [candidate for candidate in steps[:steps.index(step)]
                    if candidate.source_copy_proof_role is not None
                    and candidate.source_copy_proof_role.kind == role.kind.replace('_resume', '_save')
                    and candidate.source_copy_proof_role.choice_step == role.choice_step]
                if len(prior) != 1:
                    raise ValueError('Source-copy recovery must reuse one earlier issued Save owner')
            if role.issues_save:
                groups[step.name].append(replace(step, subcommand='draft-start', arguments=(SAVE,), source_copy_proof_role=None))
            elif not role.is_resume and role.kind != 'final_decline':
                groups[root_name].append(replace(step, subcommand='draft-inspect', arguments=(
                    ResponseBinding(root_name, '/draft/draft_id'), '--task-authority',
                    ResponseBinding(root_name, '/task_authority')), source_copy_proof_role=None))
        elif step.subcommand in DRAFT_GATEWAY_SUBCOMMANDS:
            binding = step.arguments[0] if step.arguments else None
            owner = step.name if step.name in owners else binding.step if isinstance(binding, ResponseBinding) else None
            if owner not in groups:
                raise ValueError('Source-copy Draft step has no issued owner')
            groups[owner].append(step)
        elif step.subcommand not in {'operation-schema', 'transaction-show', 'confirm', 'execute', 'verify'}:
            raise ValueError('command outside the closed Source-copy protocol')
    for group in groups.values():
        validate_operation_draft_protocol_steps(group)


def validate_source_copy_role_payload(broker, step, payload):
    """Bind generated issuance/parent CAS to canonical durable production state."""
    from wwise_waapi.operation_drafts import load_operation_draft_archive_records, operation_draft_authority_digest
    from wwise_waapi.source_copy_proof import ORIGIN, DECISION, baseline_origin, execution, copied_id
    from wwise_waapi.transactions import load_transaction_archive_snapshot
    from tests.semantic.support.codex_gateway_broker import GatewayInvocationError
    role = step.source_copy_proof_role
    try:
        root = broker._payloads_by_step[role.parent_start]
        root_id = root['draft']['draft_id']
        choice = broker._payloads_by_step[role.choice_step]
        if role.is_decline:
            issued = next(prior for prior in broker._execution_steps if prior.source_copy_proof_role is not None
                and prior.source_copy_proof_role.kind == role.kind.replace('_decline', '_save')
                and prior.source_copy_proof_role.choice_step == role.choice_step)
            child_payload = broker._payloads_by_step[issued.name]
        else:
            child_payload = payload if role.issues_save or role.is_resume else choice
        child_id = child_payload['draft']['draft_id']
        state = broker._state_directory or broker._existing_state_directory
        issued_ids = {root_id, child_id}
        issued_ids.update(getattr(broker, '_source_copy_archive_draft_ids', ()))
        for prior in broker._execution_steps:
            if prior.source_copy_proof_role is not None and prior.source_copy_proof_role.issues_save:
                receipt = broker._payloads_by_step.get(prior.name)
                if receipt is not None:
                    issued_ids.add(receipt['draft']['draft_id'])
        records = load_operation_draft_archive_records(state, tuple(sorted(issued_ids)), allow_cleaned_file_evidence=True)
        parent, child = records[root_id], records[child_id]
        if (parent.operation != 'object.copy' or parent.version != '2021.1'
                or parent.authority_digest != operation_draft_authority_digest(root['task_authority'])
                or child.operation != SAVE or child.version != '2021.1'
                or child.connection_binding != parent.connection_binding
                or child.authority_digest != operation_draft_authority_digest(child_payload['task_authority'])):
            raise ValueError('issued Save differs from its exact parent/capability/configuration')
        origin = child.composition[ORIGIN]
        if role.kind in {'baseline_save', 'baseline_return', 'baseline_decline', 'baseline_resume'}:
            decision = parent.composition.get(DECISION)
            if decision is not None:
                expected_origin = decision['origin']
            else:
                expected_origin = baseline_origin(parent, parent.check['request_digest'], {
                    'project_guard': parent.check['project_guard'],
                    'binding': {'project_guard': parent.check['project_guard'],
                        'connection_configuration': parent.connection_binding['configuration']}})
            if (origin != expected_origin or origin['parent']['draft_id'] != root_id
                    or origin['parent']['authority_digest'] != parent.authority_digest):
                raise ValueError('baseline Save has another checked parent origin')
            if role.kind in {'baseline_save', 'baseline_resume'} and origin['parent']['source_revision'] != choice['draft']['revision']:
                raise ValueError('baseline Save has another checked revision')
        else:
            transaction = load_transaction_archive_snapshot(state, choice['transaction_id'])
            baseline = transaction.preview.artifact['prepared_operation']['pre_state']['source_copy_saved_proof']
            expected_origin = {'contract': 'waapi-skill.source-copy-saved-proof/v1', 'version': '2021.1',
                'stage': 'final', 'baseline_digest': baseline['digest'], 'context': baseline['context'],
                'parent': {'transaction_id': transaction.record.transaction_id,
                    'artifact_hash': transaction.preview.artifact_hash,
                    'execution_event_hash': execution(transaction)['event_hash'], 'copied_id': copied_id(transaction)}}
            if (origin != expected_origin or parent.seal is None
                    or parent.seal['transaction_id'] != transaction.record.transaction_id):
                raise ValueError('final Save has another executed copy origin')
        if role.kind == 'final_decline':
            scope = payload['verification']['verification_scope']
            saved = load_transaction_archive_snapshot(state, child.seal['transaction_id'])
            if (transaction.record.state.value != 'verified' or payload['transaction_id'] != transaction.record.transaction_id
                    or payload.get('verified') is not True or scope['complete_copy_preservation'] is not False
                    or scope['saved_proof_incomplete_reason'] != 'final_Save_declined'
                    or any(event['event_type'] == 'execution_started' for event in saved.events)):
                raise ValueError('final refusal does not prove incomplete scope without a Save attempt')
        elif role.issues_save or role.is_resume:
            if role.is_resume:
                issued = next(prior for prior in broker._execution_steps if prior.source_copy_proof_role is not None
                    and prior.source_copy_proof_role.kind == role.kind.replace('_resume', '_save')
                    and prior.source_copy_proof_role.choice_step == role.choice_step)
                original = broker._payloads_by_step[issued.name]
                if (payload['task_authority'] != original['task_authority']
                        or any(payload['draft'][key] != original['draft'][key]
                            for key in ('draft_id', 'revision', 'binding', 'lifecycle_state'))):
                    raise ValueError('recovery differs from the earlier unattempted child capability/revision')
            if payload['source_copy_saved_proof']['parent'] != {
                    key: value for key, value in origin['parent'].items() if key in {'draft_id', 'transaction_id'}}:
                raise ValueError('generated Save public parent differs from its durable origin')
            draft = payload['draft']
            if (draft['binding'] != {'operation': SAVE, 'version': '2021.1', 'schema_digest': child.schema_digest}
                    or draft['revision'] != 3 or draft['lifecycle_state'] != 'editable'
                    or not any(event['event_type'] == 'source_copy.save_started' for event in child.audit)):
                raise ValueError('generated Save is not the production-issued editable child')
        else:
            decision = parent.composition[DECISION]
            receipt = decision['receipt']
            saved = load_transaction_archive_snapshot(state, child.seal['transaction_id'])
            saved_expected = (decision['status'] == 'baseline_saved' and receipt['transaction_id'] == saved.record.transaction_id
                and saved.record.state.value in {'verified', 'result_schema_checked'}) if role.kind == 'baseline_return' else (
                    decision['status'] == 'declined' and receipt is None
                    and not any(event['event_type'] == 'execution_started' for event in saved.events))
            if (not saved_expected
                    or payload['draft']['draft_id'] != root_id
                    or payload['draft']['revision'] != origin['parent']['source_revision'] + 1
                    or not any(event['event_type'] == 'source_copy.baseline_decided'
                        and event['revision'] == payload['draft']['revision'] for event in parent.audit)
                    or payload['next_command']['gateway_argv'] != ['draft-check', root_id, '--task-authority',
                        root['task_authority'], '--expected-revision', str(payload['draft']['revision'])]):
                raise ValueError('baseline return does not bind its verified child and exact parent CAS')
    except Exception as exc:
        raise GatewayInvocationError(f'Source-copy owned continuation binding is invalid: {exc}') from exc


def build_source_copy_saved_proof_protocol(request: Mapping[str, Any], *, dirty_baseline=False, decline_stage=None, resume_stage=None, policy="ask_before_changes"):
    """Schedule the existing copy declaration and separately authorized Saves."""
    from tests.semantic.support.codex_gateway_broker import ExpectedGatewayStep as Step, ResponseBinding as Bound
    from tests.semantic.support.codex_eval_protocol_v3 import build_object_lifecycle_business_transaction_steps, V3GatewayProtocol
    if request.get('version') != '2021.1' or request.get('operation') != 'object.copy':
        raise ValueError('saved Source proof is restricted to the pinned 2021.1 copy lane')
    if request.get('arguments', {}).get('on_name_conflict') == 'replace':
        raise ValueError('replace has no complete saved Source proof')
    if (type(dirty_baseline) is not bool or decline_stage not in {None, 'baseline', 'final'}
            or resume_stage not in {None, 'baseline', 'final'} or decline_stage is not None and resume_stage is not None
            or (decline_stage == 'baseline' or resume_stage == 'baseline') and not dirty_baseline):
        raise ValueError('Source-copy proof branch is not supported')
    if policy not in {'read_only', 'ask_before_changes', 'allow_changes'}:
        raise ValueError('unknown project modification policy')
    parent = list(build_object_lifecycle_business_transaction_steps(request, label='tx01'))
    if policy == 'read_only':
        return V3GatewayProtocol((parent[0],), (1,))
    preview = parent.pop()
    check = parent[-1].name
    root = 'tx01.draft-start'
    steps, prefixes = list(parent), []
    def finish(label, preview_name):
        if policy == 'allow_changes':
            steps.extend([
                Step(label + '.execute', 'execute', (Bound(preview_name, '/transaction_id'),)),
                Step(label + '.verify', 'verify', (Bound(label + '.execute', '/transaction_id'),)),
            ])
            return label + '.verify'
        steps.extend([
            Step(label + '.show', 'transaction-show', (Bound(preview_name, '/transaction_id'), '--summary-only')),
            Step(label + '.confirm', 'confirm', (Bound(label + '.show', '/transaction_id'), '--confirmation-token', Bound(label + '.show', '/confirmation/token'))),
            Step(label + '.execute', 'execute', (Bound(label + '.confirm', '/transaction_id'),)),
            Step(label + '.verify', 'verify', (Bound(label + '.execute', '/transaction_id'),)),
        ])
        return label + '.verify'
    def save(label, choice, stage):
        issue = label + '.issued-save'
        args = ((Bound(choice, '/draft/draft_id'), '--task-authority', Bound(root, '/task_authority'),
            '--expected-revision', Bound(choice, '/draft/revision')) if stage == 'baseline'
            else (Bound(choice, '/transaction_id'),))
        steps.append(Step(issue, 'continue-source-copy-proof', args,
            source_copy_proof_role=SourceCopyProofRole(stage + '_save', root, choice)))
        if resume_stage == stage:
            prefixes.append(len(steps))
            steps.append(Step(label + '.resume', 'continue-source-copy-proof', args,
                source_copy_proof_role=SourceCopyProofRole(stage + '_resume', root, choice, len(prefixes) + 1)))
        prefix = (Bound(issue, '/draft/draft_id'), '--task-authority', Bound(issue, '/task_authority'), '--expected-revision')
        steps.append(Step(label + '.check', 'draft-check', (*prefix, Bound(issue, '/draft/revision'))))
        steps.append(Step(label + '.preview', 'preview-from-draft', (*prefix, Bound(label + '.check', '/draft/revision')),
            expected_operation_request={'contract': 'waapi-skill.operation-request/v1', 'version': '2021.1',
                'operation': 'waapi.call', 'arguments': {'api': SAVE, 'args': {}, 'options': {}}}))
        if policy == 'ask_before_changes' or decline_stage == stage:
            prefixes.append(len(steps))
        declined = None
        if decline_stage == stage:
            declined = label + '.decline'
            steps.append(Step(declined, 'continue-source-copy-proof', (*args, '--decline-save'),
                source_copy_proof_role=SourceCopyProofRole(stage + '_decline', root, choice, len(prefixes) + 1)))
        else:
            finish(label, label + '.preview')
        return issue, declined
    if dirty_baseline:
        issued, returned = save('baseline', check, 'baseline')
        if returned is None:
            returned = 'tx01.baseline-return'
            steps.append(Step(returned, 'continue-source-copy-proof', (Bound(issued, '/draft/draft_id'),),
                source_copy_proof_role=SourceCopyProofRole('baseline_return', root, issued)))
        steps.append(Step('tx01.recheck', 'draft-check', (Bound(root, '/draft/draft_id'), '--task-authority',
            Bound(root, '/task_authority'), '--expected-revision', Bound(returned, '/draft/revision'))))
        preview = replace(preview, arguments=(*preview.arguments[:4], Bound('tx01.recheck', '/draft/revision')))
    steps.append(preview)
    if policy == 'ask_before_changes':
        prefixes.append(len(steps))
    pending = finish('tx01', preview.name)
    if decline_stage != 'baseline':
        _, declined = save('final', pending, 'final')
        if declined is None:
            steps.append(Step('tx01.saved-verify', 'verify', (Bound('tx01.execute', '/transaction_id'),)))
    prefixes.append(len(steps))
    return V3GatewayProtocol(tuple(steps), tuple(prefixes))
