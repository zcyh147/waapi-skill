"""Ordinary Source children use bound live owners, not staged provenance."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.unit.test_workflow_source_guard import workflow, _source_plugin_selection_runtime
from tests.unit.test_voice_source_staging_gateway import finish
from tests.unit.test_field_interface_closure_gateway import FIRST, SECOND

RETAINED = '{ABABABAB-ABAB-ABAB-ABAB-ABABABABABAB}'


def existing_source_task(tmp_path, workflow, *, voice=True, version='2025.1', source_notes='New Source'):
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
        '--field', 'notes', source_notes, '--field-value', field, '440', *extra)
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


@pytest.mark.parametrize('fault', ['numeric-voice', 'missing-voice', 'sfx-locale', 'arbitrary-child'])
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
    code, rejected = task.step('draft-check')
    assert code == 2 and rejected['ok'] is False, rejected
    expected = {'numeric-voice': 'INVALID_READBACK', 'missing-voice': 'INVALID_READBACK',
        'sfx-locale': 'PLUGIN_LANGUAGE_UNAVAILABLE', 'arbitrary-child': 'INVALID_CREATE_PARENT_TYPE'}[fault]
    assert any(row['error_code'] == expected for row in rejected.get('details', {}).get('issues', [])), rejected
    assert writes == []


@pytest.mark.parametrize('fault', [None, 'original-path', 'class'])
def test_source_append_preserves_file_backed_source_observations(tmp_path, workflow, fault):
    task, writes = existing_source_task(tmp_path, workflow, voice=False)
    file_id = '{ACACACAC-ACAC-ACAC-ACAC-ACACACACACAC}'
    from wwise_waapi.metadata_catalog import ObjectTypeCatalogStore
    source_class = ObjectTypeCatalogStore().load('2025.1').by_name('AudioFileSource')
    assert source_class.class_id == 16 and source_class.type == 'WObject'
    # Boundary observations only: no media file existence/content is fabricated.
    task.objects[file_id] = {'id': file_id, 'name': 'Retained recording', 'type': 'AudioFileSource', 'classId': 16,
        'path': task.objects[FIRST]['path'] + r'\Retained recording', 'parent': {'id': FIRST},
        'notes': 'Keep recording', 'audioSource:language': {'name': 'SFX'},
        'originalFilePath': '/fixtures/originals/Retained recording.wav'}
    original = task.call
    def call(uri, args=None, options=None):
        if uri.endswith('getPropertyAndReferenceNames') and (args or {}).get('object') == file_id:
            return {'return': []}
        result = original(uri, args, options)
        if uri.endswith('object.set'):
            if fault == 'original-path': task.objects[file_id]['originalFilePath'] = '/fixtures/changed.wav'
            elif fault == 'class': task.objects[file_id]['classId'] = 6684674
        return result
    task.call = call
    tx, shown = task.preview()
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, executed = task.run('execute', tx)
    assert code == 0, executed
    code, result = task.run('verify', tx)
    assert code == (0 if fault is None else 2) and (result.get('verified') is True) == (fault is None), result
    assert len(writes) == 1


@pytest.mark.parametrize('corrupt_later_page', [False, True])
def test_retained_source_fields_use_bounded_projection_pages(tmp_path, workflow, monkeypatch, corrupt_later_page):
    import wwise_waapi.builders.query as query
    # Exercise pagination with genuine Tone field names and a smaller injected
    # Gateway projection budget; this is not a claimed native field-count limit.
    monkeypatch.setattr(query, 'MAX_STRUCTURED_RETURN_FIELDS', 16)
    task, writes = existing_source_task(tmp_path, workflow)
    fixture = json.loads((Path(__file__).parents[1] / 'fixtures/metadata/tone-source-2025-native-catalog.json').read_text())
    metadata = json.loads((Path(__file__).parents[1] / 'fixtures/metadata/tone-source-2025.1-properties.json').read_text())['metadata']
    last_field = next(name for name in reversed(fixture['property_names']['return']) if name in metadata)
    observed = metadata[last_field]['default']
    task.objects[RETAINED]['@' + last_field] = observed
    original = task.call
    projections = []
    def call(uri, args=None, options=None):
        if uri.endswith('object.get') and (args or {}).get('from', {}).get('id') == [RETAINED]:
            fields = options['return']
            assert len(fields) <= 16, fields
            if any(field.startswith('@') for field in fields): projections.append(fields)
        result = original(uri, args, options)
        if uri.endswith('object.set') and corrupt_later_page:
            task.objects[RETAINED]['@' + last_field] = observed + 1
        return result
    task.call = call
    tx, shown = task.preview()
    if corrupt_later_page:
        code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
        assert code == 0, confirmed
        code, executed = task.run('execute', tx)
        assert code == 0, executed
        code, result = task.run('verify', tx)
        assert code == 2 and result.get('verified') is not True, result
    else:
        finish(task, tx, shown)
    assert len(writes) == 1 and len(projections) > 1
    projected = {name for fields in projections for name in fields}
    fixture = json.loads((Path(__file__).parents[1] / 'fixtures/metadata/tone-source-2025-native-catalog.json').read_text())
    assert {'@' + name for name in fixture['property_names']['return']} <= projected
    first_field = fixture['property_names']['return'][0]
    assert any('@' + last_field in fields and '@' + first_field not in fields for fields in projections)


def test_named_source_rename_creates_a_fresh_child_and_preserves_collision(tmp_path, workflow):
    task, writes = existing_source_task(tmp_path, workflow, voice=False)
    task.objects[RETAINED].update(name='Tone', path=task.objects[FIRST]['path'] + r'\Tone')
    before = deepcopy(task.objects[RETAINED])
    create = task._create
    def renamed(node, parent, *, owned=False):
        # Documented rename outcome: native chooses a unique numeric suffix.
        # The Gateway must verify the actual identity/name, not predict it.
        if node['type'] == 'Source':
            node = {**node, 'name': 'Tone_01'}
        return create(node, parent, owned=owned)
    task._create = renamed
    code, configured = task.step('draft-business-configure', '--name-conflict', 'rename')
    assert code == 0, configured
    tx, shown = task.preview()
    finish(task, tx, shown)
    assert len(writes) == 1 and task.objects[RETAINED] == before
    created, = [row for key, row in task.objects.items() if key not in {FIRST, SECOND, RETAINED} and row['type'] == 'SourcePlugin']
    assert created['name'] == 'Tone_01' and created['@StartFreq'] == 440.0


def test_named_source_merge_reuses_exact_source_and_preserves_unselected_fields(tmp_path, workflow):
    task, writes = existing_source_task(tmp_path, workflow)
    task.objects[RETAINED].update(name='Tone', path=task.objects[FIRST]['path'] + r'\Tone')
    before = deepcopy(task.objects[RETAINED])
    create = task._create
    def merged(node, parent, *, owned=False):
        if node['type'] == 'Source':
            row = task.objects[RETAINED]
            assert row['parent'] == {'id': parent} and row['name'] == node['name']
            row.update({key: deepcopy(value) for key, value in node.items() if key.startswith('@')})
            return {'id': RETAINED, 'name': row['name']}
        return create(node, parent, owned=owned)
    task._create = merged
    code, configured = task.step('draft-business-configure', '--name-conflict', 'merge')
    assert code == 0, configured
    tx, shown = task.preview()
    finish(task, tx, shown)
    assert len(writes) == 1
    expected = {**before, '@StartFreq': 440.0}
    assert task.objects[RETAINED] == expected
    assert shown['artifact']['prepared_operation']['semantic_preview']['envelope']['metadata']['constructor_notes']['merged_existing'] == 'preserve_existing_notes'
    assert len([row for row in task.objects.values() if row['type'] == 'SourcePlugin']) == 1


def test_named_source_replace_retires_collision_and_preserves_other_source(tmp_path, workflow):
    task, writes = existing_source_task(tmp_path, workflow, voice=False)
    task.objects[RETAINED].update(name='Tone', path=task.objects[FIRST]['path'] + r'\Tone')
    peer = '{ACACACAC-ACAC-ACAC-ACAC-ACACACACACAC}'
    task.objects[peer] = {**deepcopy(task.objects[RETAINED]), 'id': peer, 'name': 'Peer',
        'path': task.objects[FIRST]['path'] + r'\Peer'}
    before = deepcopy(task.objects[peer])
    create = task._create
    def replaced(node, parent, *, owned=False):
        if node['type'] == 'Source':
            del task.objects[RETAINED]
        return create(node, parent, owned=owned)
    task._create = replaced
    code, configured = task.step('draft-business-configure', '--name-conflict', 'replace')
    assert code == 0, configured
    tx, shown = task.preview()
    finish(task, tx, shown)
    assert len(writes) == 1 and RETAINED not in task.objects and task.objects[peer] == before
    created, = [row for key, row in task.objects.items() if key != peer and row['type'] == 'SourcePlugin']
    assert created['name'] == 'Tone' and created['@StartFreq'] == 440.0


@pytest.mark.parametrize('conflict', ['merge', 'replace'])
def test_named_source_collision_drift_stops_before_write(tmp_path, workflow, conflict):
    task, writes = existing_source_task(tmp_path, workflow)
    task.objects[RETAINED].update(name='Tone', path=task.objects[FIRST]['path'] + r'\Tone')
    code, configured = task.step('draft-business-configure', '--name-conflict', conflict)
    assert code == 0, configured
    tx, shown = task.preview()
    task.objects[RETAINED]['@WaveType'] = 1
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, stopped = task.run('execute', tx)
    assert code == 2 and stopped.get('executed') is not True, stopped
    assert writes == []


@pytest.mark.parametrize('conflict', ['merge'])
def test_named_source_collision_cannot_retarget_existing_language(tmp_path, workflow, conflict):
    task, writes = existing_source_task(tmp_path, workflow)
    task.objects[RETAINED].update(name='Tone', path=task.objects[FIRST]['path'] + r'\Tone',
        **{'audioSource:language': {'name': 'French'}})
    code, configured = task.step('draft-business-configure', '--name-conflict', conflict)
    assert code == 0, configured
    code, rejected = task.step('draft-check')
    assert code == 2 and 'SOURCE_LANGUAGE_COLLISION_MISMATCH' in json.dumps(rejected), rejected
    assert writes == []


@pytest.mark.parametrize('version', ['2023.1', '2024.1', '2025.1'])
def test_source_replace_can_retire_other_language_and_create_selected_language(tmp_path, workflow, version):
    task, writes = existing_source_task(tmp_path, workflow, version=version)
    task.objects[RETAINED].update(name='Tone', path=task.objects[FIRST]['path'] + r'\Tone',
        **{'audioSource:language': {'name': 'French'}})
    create = task._create
    def replace(node, parent, *, owned=False):
        if node['type'] == 'Source': del task.objects[RETAINED]
        return create(node, parent, owned=owned)
    task._create = replace
    code, result = task.step('draft-business-configure', '--name-conflict', 'replace')
    assert code == 0, result
    tx, shown = task.preview()
    finish(task, tx, shown)
    created, = [row for row in task.objects.values() if row['type'] == 'SourcePlugin']
    assert len(writes) == 1 and RETAINED not in task.objects
    assert created['audioSource:language']['name'] == 'English(US)' and created['notes'] == 'New Source'
    collision, = shown['artifact']['prepared_operation']['semantic_preview']['envelope']['metadata']['source_language_collisions']
    assert collision['source_id'] == RETAINED and collision['existing_language']['name'] == 'French'
    assert collision['selected_language']['name'] == 'English(US)' and collision['effect'] == 'retire_collision_and_create_selected_language'


def test_source_constructor_merge_does_not_verify_overwritten_existing_notes(tmp_path, workflow):
    task, writes = existing_source_task(tmp_path, workflow)
    task.objects[RETAINED].update(name='Tone', path=task.objects[FIRST]['path'] + r'\Tone')
    code, result = task.step('draft-business-configure', '--name-conflict', 'merge')
    assert code == 0, result
    create = task._create
    def wrongly_overwritten(node, parent, *, owned=False):
        if node['type'] == 'Source':
            task.objects[RETAINED].update({'@StartFreq': 440.0, 'notes': node['notes']})
            return {'id': RETAINED, 'name': 'Tone'}
        return create(node, parent, owned=owned)
    task._create = wrongly_overwritten
    tx, shown = task.preview()
    code, result = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, result
    code, result = task.run('execute', tx)
    assert code == 0, result
    code, rejected = task.run('verify', tx)
    assert code == 2 and rejected.get('verified') is not True, rejected
    assert len(writes) == 1


@pytest.mark.parametrize('wrong_language_id', [False, True])
def test_cross_language_source_rename_can_keep_native_name_but_must_match_exposed_language_guid(tmp_path, workflow, wrong_language_id):
    task, writes = existing_source_task(tmp_path, workflow)
    task.objects[RETAINED].update(name='Tone', path=task.objects[FIRST]['path'] + r'\Tone',
        **{'audioSource:language': {'name': 'French'}})
    before = deepcopy(task.objects[RETAINED])
    create = task._create
    language = next(row for row in task.languages if row['name'] == 'English(US)')
    def native_same_name(node, parent, *, owned=False):
        result = create(node, parent, owned=owned)
        if node['type'] == 'Source':
            task.objects[result['id']]['audioSource:language'] = {'name': 'English(US)',
                'id': '{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}' if wrong_language_id else language['id']}
        return result
    task._create = native_same_name
    code, result = task.step('draft-business-configure', '--name-conflict', 'rename')
    assert code == 0, result
    tx, shown = task.preview()
    code, result = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, result
    code, result = task.run('execute', tx)
    assert code == 0, result
    code, verified = task.run('verify', tx)
    assert code == (2 if wrong_language_id else 0), verified
    assert len(writes) == 1 and task.objects[RETAINED] == before


def test_source_collision_cannot_choose_between_same_names_in_two_languages(tmp_path, workflow):
    task, writes = existing_source_task(tmp_path, workflow)
    task.objects[RETAINED].update(name='Tone', path=task.objects[FIRST]['path'] + r'\Tone')
    peer = '{ACACACAC-ACAC-ACAC-ACAC-ACACACACACAC}'
    task.objects[peer] = {**deepcopy(task.objects[RETAINED]), 'id': peer, 'audioSource:language': {'name': 'French'}}
    original = task.call
    def native_path_selects_one(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('object.get') and args.get('from', {}).get('path') == [task.objects[RETAINED]['path']]:
            result['return'] = result['return'][:1]
        return result
    task.call = native_path_selects_one
    code, result = task.step('draft-business-configure', '--name-conflict', 'replace')
    assert code == 0, result
    code, rejected = task.step('draft-check')
    assert code == 2 and 'AMBIGUOUS_SOURCE_COLLISION' in json.dumps(rejected), rejected
    assert writes == []
