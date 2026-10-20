"""Localized Source completion uses ordinary public Draft/transaction phases."""
import json
from pathlib import Path
import pytest

from tests.unit.test_workflow_source_guard import workflow, _planned_source_characterization_runtime
from tests.unit.test_sound_voice_creation_gateway import declare_voice


def combined_task(tmp_path, workflow, *, references=False, unobserved=None):
    runtime, commands, writes, task = _planned_source_characterization_runtime(tmp_path, workflow, fault='staged-atomic-order')
    if unobserved in {'authoring', 'other-build'}:
        original_context_call = task.call
        def context_call(uri, args=None, options=None):
            result = original_context_call(uri, args, options)
            if uri.endswith('getInfo'):
                if unobserved == 'authoring':
                    result['isCommandLine'] = False
                else:
                    result['version'].update(build=9144, displayName='v2025.1.7.9144')
            return result
        task.call = context_call
    if unobserved == 'other-source-class':
        next(row for row in task.types if row['name'] == 'Wwise Tone Generator')['classId'] += 65536
    voice_extra = []
    source_extra = []
    if references:
        from tests.unit.test_sound_voice_creation_gateway import SECOND
        target = task.bind(SECOND)
        task.types.append({'classId': 917520, 'name': 'Curve', 'type': 'WObject'})
        task.metadata['Curve'] = {'name': 'Curve', 'type': 'Reference',
            'restriction': {'type': 'reference', 'restrictions': [{'type': ['Curve']}]}}
        task.metadata['SourceTarget'] = {'name': 'SourceTarget', 'type': 'Reference',
            'restriction': {'type': 'reference', 'restrictions': [{'type': ['WorkUnit']}]}}
        code, fields = task.step('draft-discover-fields', '--semantic-kind', 'sound-voice', '--meaning', 'Curve')
        assert code == 0, fields
        field = fields['meaning_results'][0]['candidates'][0]['handle']
        from tests.unit.test_object_inline_curve_gateway import POINTS
        voice_extra = ['--field-value', field, json.dumps({'curve_points': POINTS})]
        original_call = task.call
        def curve_call(uri, args=None, options=None):
            from copy import deepcopy
            result = original_call(uri, args, options)
            if uri.endswith('object.set'):
                for row in list(task.objects.values()):
                    curve = row.get('@Curve')
                    if isinstance(curve, dict) and curve.get('type') == 'Curve':
                        curve_id = '{CDCDCDCD-CDCD-CDCD-CDCD-CDCDCDCDCDCD}'
                        row['@Curve'] = {'id': curve_id, 'points': deepcopy(curve['points'])}
                        task.objects[curve_id] = {'id': curve_id, 'name': '', 'type': 'Curve', 'classId': 917520, 'notes': '',
                            'path': row['path'] + r'\[Curve]', 'parent': None, 'owner': {'id': row['id']}}
            return result
        task.call = curve_call
    code, voice = declare_voice(task, extra=('--field', 'language', 'English(US)', *voice_extra))
    assert code == 0, voice
    owner = voice['draft']['declared_object']['result_handle']
    code, found = task.step('draft-discover-types', '--role', 'source', '--meaning', 'Wwise Tone Generator')
    assert code == 0, found
    kind = found['type_candidates'][0]['handle']
    code, found = task.step('draft-discover-fields', '--type-handle', kind, '--meaning', 'Frequency')
    assert code == 0, found
    field, = [row['handle'] for row in found['meaning_results'][0]['candidates'] if row['metadata']['name'] == 'StartFreq']
    if references:
        code, fields = task.step('draft-discover-fields', '--type-handle', kind, '--meaning', 'SourceTarget')
        assert code == 0, fields
        source_extra = ['--field-value', fields['meaning_results'][0]['candidates'][0]['handle'], target]
    code, declared = task.step('draft-declare-new', '--declaration-id', 'source', '--parent-handle', owner,
        '--name', 'Tone', '--kind', kind, '--field', 'plugin_placement', 'owner',
        '--field', 'language', 'English(US)', '--field', 'notes', 'Keep my Source', '--field-value', field, '440', *source_extra)
    assert code == 0, declared
    return task, writes


def finish(task, tx, shown):
    code, result = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, result
    code, result = task.run('execute', tx)
    assert code == 0, json.dumps(result)
    code, result = task.run('verify', tx)
    assert code == 0 and result['verified'] is True, json.dumps(result)
    return result


def test_combined_voice_localized_source_finishes_in_two_owned_stages_and_reuses_continuation(tmp_path, workflow):
    task, writes = combined_task(tmp_path, workflow)
    code, pending = task.step('draft-check')
    assert code == 2 and pending['error_code'] == 'VOICE_SOURCE_STAGED_COMPLETION_REQUIRED', pending
    assert 'native evidence' not in pending['message']
    assert not any(uri.endswith(('object.create', 'object.set')) for uri, _, _ in task.calls)
    code, configured = task.run(*pending['next_command']['gateway_argv'])
    assert code == 0, configured
    task.revision = configured['draft']['revision']
    tx, shown = task.preview()
    created = finish(task, tx, shown)
    stage = created['agent_result']['business_result']['staged_completion']
    assert stage['complete'] is False and stage['current_stage'] == 'voice_created_source_pending'
    assert shown['staged_completion']['current_stage'] == 'voice'
    assert shown['staged_completion']['atomic'] is False
    command = created['next_command']['gateway_argv']
    code, source = task.run(*command)
    assert code == 0, json.dumps(source)
    code, repeated = task.run(*command)
    assert code == 0 and repeated['draft']['draft_id'] == source['draft']['draft_id'], repeated
    task.draft = source['draft']['draft_id']
    task.authority = source['task_authority']
    task.revision = source['draft']['revision']
    source_tx, source_shown = task.preview()
    done = finish(task, source_tx, source_shown)
    assert done['agent_result']['business_result']['staged_completion']['complete'] is True
    code, repeated = task.run(*command)
    assert code == 0 and repeated['draft']['draft_id'] == task.draft, repeated
    assert repeated['status'] == 'sealed'
    assert repeated['staged_completion']['complete'] is True
    assert len(writes) == 2
    assert len(writes[0]["objects"][0]["children"]) == 1
    assert "children" not in writes[0]["objects"][0]["children"][0]
    voice, = [row for row in task.objects.values() if row['name'] == 'Rain']
    assert voice['@IsVoice'] is True and voice['@Volume'] == -6 and voice['notes'] == 'Keep voice'
    source, = [row for row in task.objects.values() if row['name'] == 'Tone']
    assert source['parent'] == {'id': voice['id']} and source['@StartFreq'] == 440
    assert source['notes'] == 'Keep my Source' and source['audioSource:language']['name'] == 'English(US)'
    assert sum(uri.endswith(('object.create', 'object.set')) for uri, _, _ in task.calls) == 2


def create_first_stage(task):
    code, configured = task.step('draft-business-configure', '--voice-source-completion', 'separate-previews')
    assert code == 0, configured
    tx, shown = task.preview()
    result = finish(task, tx, shown)
    return result['next_command']['gateway_argv']


def test_staged_completion_preserves_admitted_voice_inline_curve_and_source_reference(tmp_path, workflow):
    from tests.unit.test_sound_voice_creation_gateway import SECOND
    task, writes = combined_task(tmp_path, workflow, references=True)
    code, configured = task.step('draft-business-configure', '--platform', 'Windows', '--add-to-source-control')
    assert code == 0, configured
    command = create_first_stage(task)
    code, child = task.run(*command)
    assert code == 0, json.dumps(child)
    adopt(task, child)
    tx, shown = task.preview()
    finish(task, tx, shown)
    voice, = [row for row in task.objects.values() if row['name'] == 'Rain']
    source, = [row for row in task.objects.values() if row['name'] == 'Tone']
    from tests.unit.test_object_inline_curve_gateway import POINTS
    assert voice['@Curve']['points'] == POINTS and voice['@Volume'] == -6 and voice['notes'] == 'Keep voice'
    assert source['@SourceTarget'] == SECOND and source['@StartFreq'] == 440
    assert [row.get('platform') for row in writes] == ['Windows', 'Windows']
    assert all(row['autoAddToSourceControl'] is True for row in writes)


def adopt(task, result):
    task.draft = result['draft']['draft_id']
    task.authority = result['task_authority']
    task.revision = result['draft']['revision']


def test_explicit_atomic_voice_source_requirement_preserves_intent_without_writing(tmp_path, workflow):
    task, writes = combined_task(tmp_path, workflow)
    code, result = task.step('draft-business-configure', '--voice-source-completion', 'atomic-required')
    assert code == 0, result
    code, result = task.step('draft-check')
    assert code == 2 and result['error_code'] == 'VOICE_SOURCE_ATOMIC_UNRESOLVED', result
    assert result['staged_completion']['atomic_requirement'] is True
    assert result['staged_completion']['declarations_preserved'] is True
    assert 'next_command' not in result and writes == []
    assert not any(uri.endswith(('object.create', 'object.set')) for uri, _, _ in task.calls)


@pytest.mark.parametrize('fault', ['language', 'metadata', 'voice'])
def test_staged_source_live_binding_drift_keeps_created_voice_and_writes_no_source(tmp_path, workflow, fault):
    task, writes = combined_task(tmp_path, workflow)
    command = create_first_stage(task)
    if fault == 'language':
        task.languages[0]['id'] = '{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD}'
    elif fault == 'metadata':
        task.metadata['StartFreq']['default'] = 1200
    else:
        next(row for row in task.objects.values() if row['name'] == 'Rain')['@IsVoice'] = False
    code, rejected = task.run(*command)
    assert code == 2 and rejected['ok'] is False, rejected
    assert len(writes) == 1
    assert sum(uri.endswith(('object.create', 'object.set')) for uri, _, _ in task.calls) == 1


@pytest.mark.parametrize('fault', ['operation', 'staged-record', 'ordinary-source-without-provenance', 'ordinary-source-with-stale-composer'])
def test_forged_cross_operation_or_staged_record_is_rejected_at_public_check(tmp_path, workflow, fault):
    from wwise_waapi.canonical import canonical_sha256, canonical_json_bytes
    from wwise_waapi.operation_drafts import OPERATION_DRAFT_RECORD_DIGEST_CONTRACT
    task, writes = combined_task(tmp_path, workflow)
    command = create_first_stage(task)
    code, child = task.run(*command)
    assert code == 0, json.dumps(child)
    adopt(task, child)
    path, = list(tmp_path.rglob(task.draft + '.json'))
    payload = json.loads(path.read_text())
    if fault == 'operation':
        payload['operation'] = 'object.create'
    elif fault == 'staged-record':
        payload['composition']['voice_source_origin']['original_declarations_sha256'] = '0' * 64
    else:
        del payload['composition']['voice_source_origin']
        if fault == 'ordinary-source-with-stale-composer':
            payload['composer_digest'] = '0' * 64
    payload['record_digest'] = canonical_sha256({'contract': OPERATION_DRAFT_RECORD_DIGEST_CONTRACT,
        'record': {key: value for key, value in payload.items() if key != 'record_digest'}})
    path.write_bytes(canonical_json_bytes(payload))
    code, rejected = task.step('draft-check')
    assert code == 2 and rejected['ok'] is False, rejected
    if fault == 'staged-record':
        assert rejected['error_code'] == 'OPERATION_DRAFT_ACTION_INVALID', rejected
    assert len(writes) == 1 and sum(uri.endswith(('object.create', 'object.set')) for uri, _, _ in task.calls) == 1


def test_indeterminate_source_reports_partial_completion_and_cannot_repeat_either_write(tmp_path, workflow):
    from copy import deepcopy
    task, writes = combined_task(tmp_path, workflow)
    command = create_first_stage(task)
    code, child = task.run(*command)
    assert code == 0, json.dumps(child)
    adopt(task, child)
    tx, shown = task.preview()
    original = task.call
    class WaapiRequestFailed(Exception):
        uri = 'ak.wwise.invalid_language'
        kwargs = {'message': 'Language can only be used on the Source of a Voice.'}
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            writes.append(deepcopy(args)); task.calls.append((uri, deepcopy(args), deepcopy(options)))
            raise WaapiRequestFailed('Captured native Source-language rejection')
        return original(uri, args, options)
    task.call = call
    code, result = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, result
    code, result = task.run('execute', tx)
    assert code == 2 and result['state'] == 'indeterminate', result
    assert result['cleanup']['staged_completion']['complete'] is False
    assert 'Source_incomplete' in result['cleanup']['staged_completion']['partial_failure']
    code, repeated = task.run(*command)
    assert code == 0 and repeated['staged_completion']['source_state'] == 'indeterminate', repeated
    code, repeated = task.run('execute', tx)
    assert code == 2, repeated
    assert len(writes) == 2 and sum(uri.endswith(('object.create', 'object.set')) for uri, _, _ in task.calls) == 2


def test_ordinary_set_creation_cannot_supply_a_staged_root_witness(tmp_path, workflow):
    runtime, commands, writes, task = _planned_source_characterization_runtime(tmp_path, workflow)
    code, declared = declare_voice(task)
    assert code == 0, declared
    tx, shown = task.preview()
    result = finish(task, tx, shown)
    from wwise_waapi.transactions import TransactionStore
    recorded, = [event['details']['verification'] for event in TransactionStore(runtime.state_dir).read_events(tx)
        if event['event_type'] == 'verification_recorded']
    assert not any(row.get('kind') == 'verified_created_root_identity' for row in recorded['assertions'])
    before = len(writes)
    code, rejected = task.run('continue-voice-source', tx)
    assert code == 2 and rejected['ok'] is False, rejected
    assert len(writes) == before == 1


def test_copied_stage_record_cannot_grant_an_ordinary_set_continuation_authority(tmp_path, workflow):
    from wwise_waapi.canonical import canonical_sha256, canonical_json_bytes
    from wwise_waapi.operation_drafts import OPERATION_DRAFT_RECORD_DIGEST_CONTRACT
    staged_path = tmp_path / 'staged'; staged_path.mkdir()
    task, writes = combined_task(staged_path, workflow)
    code, configured = task.step('draft-business-configure', '--voice-source-completion', 'separate-previews')
    assert code == 0, configured
    tx, shown = task.preview()
    record = shown['artifact']['request']['arguments']['voice_source_staging']
    ordinary_path = tmp_path / 'ordinary'; ordinary_path.mkdir()
    runtime, commands, ordinary_writes, ordinary = _planned_source_characterization_runtime(ordinary_path, workflow)
    code, declared = declare_voice(ordinary)
    assert code == 0, declared
    path, = list(ordinary_path.rglob(ordinary.draft + '.json'))
    data = json.loads(path.read_text())
    data['composition']['voice_source_origin'] = record
    data['record_digest'] = canonical_sha256({'contract': OPERATION_DRAFT_RECORD_DIGEST_CONTRACT,
        'record': {key: value for key, value in data.items() if key != 'record_digest'}})
    path.write_bytes(canonical_json_bytes(data))
    code, rejected = ordinary.step('draft-check')
    assert code == 2 and rejected['ok'] is False, rejected
    assert ordinary_writes == [] and writes == []


@pytest.mark.parametrize('context', ['authoring', 'other-build', 'other-source-class', 'explicit-view', 'other-graph'])
def test_default_atomic_boundary_does_not_classify_unobserved_contexts(tmp_path, workflow, context):
    task, writes = combined_task(tmp_path, workflow, unobserved=context)
    if context == 'explicit-view':
        code, configured = task.step('draft-business-configure', '--platform', 'Windows')
        assert code == 0, configured
    elif context == 'other-graph':
        code, inspected = task.run('draft-inspect', task.draft, '--task-authority', task.authority)
        assert code == 0, inspected
        parent = next(row['target']['parent_handle'] for row in inspected['draft']['declarations'] if row['declaration_id'] == 'voice')
        code, declared = task.step('draft-declare-new', '--declaration-id', 'other',
            '--parent-handle', parent, '--name', 'Other', '--kind', 'sound-sfx')
        assert code == 0, declared
    code, checked = task.step('draft-check')
    assert code == 0 and checked['ok'] is True, checked
    assert writes == [] and not any(uri.endswith(('object.create', 'object.set')) for uri, _, _ in task.calls)

    if context == 'other-graph':
        code, rejected = task.step('draft-business-configure', '--voice-source-completion', 'separate-previews')
        assert code == 2 and rejected['error_code'] == 'VOICE_SOURCE_STAGE_INVALID', rejected
        assert writes == []
