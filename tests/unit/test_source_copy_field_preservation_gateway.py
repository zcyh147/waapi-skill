"""Source-copy state proof through the ordinary public Draft transaction flow."""
from copy import deepcopy

import pytest

from tests.unit.test_copy_move_custom_workunit_gateway import TransferTask, OLD_PARENT, COPIED
from tests.unit.test_field_interface_closure_gateway import FIRST, SECOND


def source_copy_task(path, version='2021.1', *, fault=None, conflict='fail'):
    task = TransferTask(path, version, 'object.copy', source=True)
    # Genuine Synth fields/types and nondefault MIDI values retained in R50/R51,
    # plus the Sound IsVoice Boolean. These fakes do not claim native coverage.
    task.metadata = {'Osc1Transpose': {'name': 'Osc1Transpose', 'type': 'int32'},
        'Osc1Level': {'name': 'Osc1Level', 'type': 'Real32'},
        'Osc1Invert': {'name': 'Osc1Invert', 'type': 'bool'},
        'IsVoice': {'name': 'IsVoice', 'type': 'bool'}}
    task.objects[FIRST].update({'@Osc1Transpose': -1200, '@Osc1Level': -5.0, '@Osc1Invert': False})
    for identity in (OLD_PARENT, SECOND): task.objects[identity]['@IsVoice'] = False
    if conflict != 'fail':
        collision = add_retained_child(task)
        task.objects[collision].update(name=task.objects[FIRST]['name'],
            path=task.objects[SECOND]['path'] + '\\' + task.objects[FIRST]['name'])
        def declare():
            for role, identity in [('object', FIRST), ('parent', SECOND)]:
                code, result = task.step('draft-bind-object', '--role', role, '--object-id', identity)
                assert code == 0, result
            code, result = task.step('draft-declare-object-change', '--name-conflict', conflict)
            assert code == 0, result
        task.declare = declare
    original = task.call
    def call(uri, args=None, options=None):
        if uri.endswith('getPropertyAndReferenceNames'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': [key[1:] for key in task.objects[args['object']] if key.startswith('@')]}
        result = original(uri, args, options)
        if uri.endswith('getProjectInfo'): result['platforms'] = []
        if uri.endswith('object.copy'):
            if conflict == 'rename':
                task.objects[COPIED]['name'] += '_1'
                task.objects[COPIED]['path'] += '_1'
            elif conflict == 'replace': del task.objects[collision]

            if fault == 'copied-field': task.objects[COPIED]['@Osc1Transpose'] = 0
            if fault == 'owner-IsVoice': task.objects[OLD_PARENT]['@IsVoice'] = True
            result = deepcopy(task.objects[COPIED])
        return result
    task.call = call
    return task


@pytest.mark.parametrize('fault', [None, 'copied-field', 'owner-IsVoice'])
def test_source_copy_checks_live_fields_and_original_owner_after_single_write(tmp_path, fault):
    task = source_copy_task(tmp_path, fault=fault)
    task.declare(); tx, shown = task.preview()
    code, result = task.finish(tx, shown)
    assert code == (0 if fault is None else 2), result
    assert result['verified'] is (fault is None), result
    assert len(task.writes) == 1
    if fault:
        assert result['verification']['status'] == 'verification_failed'
        assert task.run('execute', tx)[0] == 2 and len(task.writes) == 1


def test_source_copy_discloses_partial_scope_in_preview_and_terminal(tmp_path):
    task = source_copy_task(tmp_path)
    task.declare(); tx, shown = task.preview()
    scope = shown['artifact']['prepared_operation']['verification_plan']['verification_scope']
    assert scope['complete_copy_preservation'] is False
    assert scope['field_count'] == 3 and scope['owner_is_voice_count'] == 2
    code, result = task.run('transaction-show', tx, '--summary-only')
    assert code == 0, result
    assert result['preview_summary']['verification_plan']['verification_scope'] == scope
    code, result = task.finish(tx, shown)
    assert code == 0 and result['verified'] is True, result
    assert result['verification']['verification_scope'] == scope
    assert result['verification_strength'] == 'source_default_view_fields_and_owner_frames_only'


def add_retained_child(task, index=0):
    identity = '{88888888-8888-8888-8888-%012d}' % index
    task.objects[identity] = {**deepcopy(task.objects[FIRST]), 'id': identity,
        'name': 'Retained%d' % index, 'path': task.objects[SECOND]['path'] + '\\Retained%d' % index,
        'parent': {'id': SECOND}}
    return identity


@pytest.mark.parametrize('large', [False, True])
def test_source_copy_keeps_large_owner_admitted_and_small_childset_protected(tmp_path, large):
    task = source_copy_task(tmp_path)
    child = add_retained_child(task)
    if large:
        for index in range(1, 129): add_retained_child(task, index)
    original = task.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('object.copy') and not large:
            task.objects[child]['notes'] = 'Unrequested damage'
        return result
    task.call = call
    task.declare(); tx, shown = task.preview()
    code, result = task.finish(tx, shown)
    assert code == (0 if large else 2), result
    assert len(task.writes) == 1
    if large:
        scope = result['verification']['verification_scope']
        assert scope['complete_copy_preservation'] is False
        assert scope['complete_owner_childset_count'] == 1
        assert 'owner_childsets_over_observation_budget' in scope['unobserved']
    else:
        assert result['verification']['status'] == 'verification_failed'


@pytest.mark.parametrize('fault', ['field', 'IsVoice', 'field-metadata'])
def test_source_copy_execution_rejects_sealed_state_drift_without_write(tmp_path, fault):
    task = source_copy_task(tmp_path)
    task.declare(); tx, shown = task.preview()
    code, result = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, result
    if fault == 'field': task.objects[FIRST]['@Osc1Level'] = -8.0
    elif fault == 'IsVoice': task.objects[SECOND]['@IsVoice'] = True
    else: task.metadata['Osc1Level']['default'] = 2.0
    code, result = task.run('execute', tx)
    assert code == 2 and task.writes == [], result


@pytest.mark.parametrize('conflict', ['rename', 'replace'])
@pytest.mark.parametrize('fault', [None, 'copied-field'])
def test_source_copy_retains_nonfail_conflicts_and_replace_boundary(tmp_path, conflict, fault):
    task = source_copy_task(tmp_path, '2025.1', conflict=conflict, fault=fault)
    task.declare(); tx, shown = task.preview()
    code, result = task.finish(tx, shown)
    assert len(task.writes) == 1
    assert result['verification']['verification_scope']['complete_copy_preservation'] is False
    if fault:
        assert code == 2 and result['verification']['status'] == 'verification_failed', result
    elif conflict == 'replace':
        assert code == 2 and result['verification']['status'] == 'indeterminate', result
        assert all(row['passed'] for row in result['verification']['assertions'])
    else:
        assert code == 0 and result['verified'] is True, result


@pytest.mark.parametrize('version', ['2022.1', '2025.1'])
def test_source_copy_keeps_uncertified_fields_explicit_without_rejecting_copy(tmp_path, version):
    task = source_copy_task(tmp_path, version)
    # Inject a metadata omission on a genuine Synth field; this is a partial
    # observer control, not a claim that either native version omits its type.
    task.metadata['Osc1Invert'] = {'name': 'Osc1Invert', 'type': ''}
    task.declare(); tx, shown = task.preview()
    code, result = task.finish(tx, shown)
    assert code == 0 and result['verified'] is True, result
    scope = result['verification']['verification_scope']
    assert scope['field_count'] == 2 and scope['uncertified_field_count'] == 1
    assert scope['complete_copy_preservation'] is False


@pytest.mark.parametrize('version', ['2021.1', '2025.1'])
@pytest.mark.parametrize('fault', [None, 'changed', 'omitted'])
def test_file_source_copy_uses_version_accessor_without_claiming_media_proof(tmp_path, version, fault):
    task = source_copy_task(tmp_path, version)
    source = task.objects[FIRST]
    for field in [key for key in source if key.startswith('@')]: del source[field]
    accessor = 'originalWavFilePath' if version == '2021.1' else 'originalFilePath'
    source.update(type='AudioFileSource', classId=16, **{accessor: '/Originals/SFX/Recording.wav',
        'audioSource:language': {'id': '{99999999-9999-9999-9999-999999999999}', 'name': 'SFX'}})
    original = task.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('object.copy'):
            if fault == 'changed': task.objects[COPIED][accessor] = '/Originals/SFX/Wrong.wav'
            elif fault == 'omitted': del task.objects[COPIED][accessor]
        return result
    task.call = call
    task.declare(); tx, shown = task.preview()
    code, result = task.finish(tx, shown)
    assert code == (0 if fault is None else 2) and result['verified'] is (fault is None), result
    if fault: assert result['verification']['status'] == 'verification_failed'
    assert len(task.writes) == 1
    assert result['verification']['verification_scope']['file_reference_observed'] is True
    assert 'media_copy_state' in result['verification']['verification_scope']['unobserved']
    assert any(uri.endswith('object.get') and accessor in options.get('return', [])
        for uri, args, options in task.calls)


def test_source_copy_rename_within_original_sound_deduplicates_owner_and_keeps_source(tmp_path):
    task = source_copy_task(tmp_path, conflict='rename')
    del task.objects['{88888888-8888-8888-8888-000000000000}']
    task.objects[FIRST].update(parent={'id': SECOND},
        path=task.objects[SECOND]['path'] + '\\' + task.objects[FIRST]['name'])
    task.declare(); tx, shown = task.preview()
    code, result = task.finish(tx, shown)
    assert code == 0 and result['verified'] is True, result
    assert result['verification']['verification_scope']['owner_count'] == 1
    assert task.objects[FIRST]['name'] == 'Wwise Synth One' and len(task.writes) == 1
