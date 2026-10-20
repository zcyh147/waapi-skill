"""Ordinary Source children use bound live owners, not staged provenance."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.unit.test_workflow_source_guard import workflow, _source_plugin_selection_runtime
from tests.unit.test_voice_source_staging_gateway import finish
from tests.unit.test_field_interface_closure_gateway import FIRST, SECOND

RETAINED = '{ABABABAB-ABAB-ABAB-ABAB-ABABABABABAB}'


def existing_source_task(tmp_path, workflow, *, voice=True, version='2025.1'):
    runtime, commands, writes, selections, task = _source_plugin_selection_runtime(tmp_path, workflow, version=version)
    if version != '2025.1':
        captured = json.loads((Path(__file__).parents[1] / 'fixtures/metadata/tone-source-existing-owner-2022-2024.json').read_text())[version]
        task.types = deepcopy(captured['types'])
        task.metadata.update(deepcopy(captured['metadata']))
    task.objects[FIRST] = {'id': FIRST, 'name': 'Existing owner', 'type': 'Sound', 'classId': 65552,
        'path': task.objects[SECOND]['path'] + r'\Existing owner', 'parent': {'id': SECOND},
        'notes': 'Keep existing owner', '@IsVoice': voice, '@Volume': -6}
    task.objects[RETAINED] = {'id': RETAINED, 'name': 'Retained Tone', 'type': 'SourcePlugin', 'classId': 6684674,
        'path': task.objects[FIRST]['path'] + r'\Retained Tone', 'parent': {'id': FIRST},
        'notes': 'Keep retained Source', '@StartFreq': 660.0, '@WaveType': 0,
        'audioSource:language': {'name': 'English(US)' if voice else 'SFX'}}
    owner = task.bind(FIRST)
    code, found = task.step('draft-discover-types', '--role', 'source', '--meaning', 'Wwise Tone Generator')
    assert code == 0, found
    candidate, = found['type_candidates']
    kind = candidate['handle']
    code, found = task.step('draft-discover-fields', '--type-handle', kind, '--meaning', 'Start Frequency')
    assert code == 0, found
    field, = [row['handle'] for row in found['meaning_results'][0]['candidates'] if row['metadata']['name'] == 'StartFreq']
    extra = ('--field', 'language', 'English(US)') if voice else ()
    code, declared = task.step('draft-declare-new', '--declaration-id', 'source', '--parent-handle', owner,
        '--name', 'Tone', '--kind', kind, '--field', 'plugin_placement', 'owner',
        '--field', 'notes', 'New Source', '--field-value', field, '440', *extra)
    assert code == 0, declared
    return task, writes


@pytest.mark.parametrize('version,voice', [('2022.1', False), ('2023.1', False), ('2024.1', True), ('2025.1', True)])
def test_existing_sound_adds_source_without_recreating_owner_or_retained_child(tmp_path, workflow, version, voice):
    task, writes = existing_source_task(tmp_path, workflow, voice=voice, version=version)
    retained = deepcopy(task.objects[RETAINED]); owner = deepcopy(task.objects[FIRST])
    tx, shown = task.preview()
    code, schema = task.run('--version', version, 'operation-schema', 'object.set')
    assert code == 0, schema
    assert 'bound_existing' in schema['business_adapter']['declaration']['graph_plugin']['source_parent']
    assert 'staged_completion' not in shown
    args = shown['artifact']['prepared_operation']['dispatch']['args']
    assert args['objects'] == [{'object': FIRST, 'children': [{'type': 'Source', 'name': 'Tone',
        'classId': 6684674, 'notes': 'New Source', **({'language': 'English(US)'} if voice else {}), '@StartFreq': 440.0}]}]
    finish(task, tx, shown)
    assert len(writes) == 1 and task.objects[RETAINED] == retained
    assert all(task.objects[FIRST][key] == value for key, value in owner.items())
    code, result = task.run('query-object', '--exact-id', FIRST, '--relationship', 'children',
        '--include', 'class-id', '--include', 'parent', '--include', 'notes', '--max-results', '8')
    assert code == 0, result
    assert {row['name'] for row in result['objects']} == {'Retained Tone', 'Tone'}


def test_source_append_cannot_verify_changed_retained_plugin_fields(tmp_path, workflow):
    task, writes = existing_source_task(tmp_path, workflow)
    tx, shown = task.preview()
    original = task.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('object.set'):
            task.objects[RETAINED]['@StartFreq'] = 999.0
        return result
    task.call = call
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, executed = task.run('execute', tx)
    assert code == 0, executed
    code, verified = task.run('verify', tx)
    assert code == 2 and verified.get('verified') is not True, verified
    code, repeated = task.run('execute', tx)
    assert code == 2 and len(writes) == 1, repeated


@pytest.mark.parametrize('fault', ['voice', 'metadata', 'retained-field'])
def test_source_owner_or_retained_state_drift_stops_before_write(tmp_path, workflow, fault):
    task, writes = existing_source_task(tmp_path, workflow)
    tx, shown = task.preview()
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    if fault == 'voice':
        task.objects[FIRST]['@IsVoice'] = False
    elif fault == 'metadata':
        task.metadata['IsVoice']['type'] = 'int32'
    else:
        task.objects[RETAINED]['@StartFreq'] = 999.0
    code, stopped = task.run('execute', tx)
    assert code == 2 and stopped.get('executed') is not True, stopped
    assert writes == []


@pytest.mark.parametrize('fault', ['numeric-voice', 'missing-voice', 'sfx-locale', 'arbitrary-child', 'source-conflict'])
def test_existing_source_owner_rejects_invalid_or_unresolved_intent_without_write(tmp_path, workflow, fault):
    task, writes = existing_source_task(tmp_path, workflow)
    if fault == 'numeric-voice':
        task.objects[FIRST]['@IsVoice'] = 1
    elif fault == 'missing-voice':
        del task.objects[FIRST]['@IsVoice']
    elif fault == 'sfx-locale':
        task.objects[FIRST]['@IsVoice'] = False
    elif fault == 'arbitrary-child':
        owner = task.bind(FIRST)
        code, declared = task.step('draft-declare-new', '--declaration-id', 'invalid-child',
            '--parent-handle', owner, '--name', 'Unrelated Sound', '--kind', 'sound-sfx')
        assert code == 2 and declared['error_code'] == 'INVALID_CREATE_PARENT_TYPE', declared
        assert writes == []
        return
    else:
        code, result = task.step('draft-business-configure', '--name-conflict', 'merge')
        assert code == 0, result
    code, rejected = task.step('draft-check')
    assert code == 2 and rejected['ok'] is False, rejected
    expected = {'numeric-voice': 'INVALID_READBACK', 'missing-voice': 'INVALID_READBACK',
        'sfx-locale': 'PLUGIN_LANGUAGE_UNAVAILABLE', 'arbitrary-child': 'INVALID_CREATE_PARENT_TYPE',
        'source-conflict': 'SOURCE_CONFLICT_UNRESOLVED'}[fault]
    assert any(row['error_code'] == expected for row in rejected.get('details', {}).get('issues', [])), rejected
    assert writes == []
