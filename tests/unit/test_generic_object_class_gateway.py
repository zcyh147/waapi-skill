"""Actual class identity is mandatory at the public object construction boundary."""
from copy import deepcopy
import json

import pytest

from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, FIRST, SECOND, ROOT, CHILD


def class_task(path, *, operation='object.create', version='2025.1'):
    task = OwnedGraphTask(path, version, operation)
    # Independent native fixture facts; never copy class identity from a Draft.
    task.objects[FIRST]['classId'] = 1
    task.objects[SECOND]['classId'] = 3
    task.require_class_projection = True
    original = task.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith(('object.create', 'object.set')):
            for row in task.objects.values():
                if row['name'] == 'Layers':
                    row['classId'] = 1
                elif row['name'] == 'Rain':
                    row['classId'] = 2
        return result
    task.call = call
    return task


def declare_sound(task, *, nested=False):
    parent = task.bind(SECOND)
    if nested:
        code, result = task.step('draft-declare-new', '--declaration-id', 'layers',
            '--parent-handle', parent, '--kind', 'actor-mixer', '--name', 'Layers')
        assert code == 0, result
        parent = result['draft']['declared_object']['result_handle']
    code, result = task.step('draft-declare-new', '--declaration-id', 'rain',
        '--parent-handle', parent, '--kind', 'sound-sfx', '--name', 'Rain')
    assert code == 0, result


def execute(task, tx, shown):
    code, result = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, result
    code, result = task.run('execute', tx)
    assert code == 0, result


def test_ordinary_create_cannot_verify_contradictory_actual_class(tmp_path):
    task = class_task(tmp_path)
    declare_sound(task)
    tx, shown = task.preview()
    execute(task, tx, shown)
    task.objects['{99999999-9999-9999-9999-999999999999}']['classId'] = 1  # Sound type token, ActorMixer class.
    code, result = task.run('verify', tx)
    assert code == 2 and result.get('verified') is not True, json.dumps(result)


@pytest.mark.parametrize('operation,nested,actual_class', [
    ('object.create', True, 1), ('object.create', False, None),
    ('object.create', False, True), ('object.create', False, '2'),
    ('object.set', False, 2), ('object.set', True, 1)])
def test_created_node_class_is_strict_and_projected_at_every_depth(tmp_path, operation, nested, actual_class):
    task = class_task(tmp_path, operation=operation)
    declare_sound(task, nested=nested)
    tx, shown = task.preview()
    execute(task, tx, shown)
    sound = next(row for row in task.objects.values() if row['name'] == 'Rain')
    sound['classId'] = actual_class
    code, result = task.run('verify', tx)
    accepted = operation == 'object.set' and not nested
    assert code == (0 if accepted else 2), json.dumps(result)
    assert (result.get('verified') is True) is accepted


@pytest.mark.parametrize('phase', ['unchanged', 'before-write', 'after-write'])
def test_existing_graph_root_class_is_bound_before_write_and_verified(tmp_path, phase):
    task = class_task(tmp_path, operation='object.set')
    owner = task.bind(FIRST)
    code, result = task.step('draft-declare-existing', '--declaration-id', 'owner',
        '--object-handle', owner, '--field', 'notes', 'Reviewed note')
    assert code == 0, result
    tx, shown = task.preview()
    code, result = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, result
    if phase == 'before-write':
        task.objects[FIRST]['classId'] = 2
    code, result = task.run('execute', tx)
    if phase == 'before-write':
        assert code == 2 and not any(uri.endswith('object.set') for uri, _, _ in task.calls), result
        return
    assert code == 0, result
    if phase == 'after-write':
        task.objects[FIRST]['classId'] = 2
    code, result = task.run('verify', tx)
    assert code == (0 if phase == 'unchanged' else 2), json.dumps(result)
    assert (result.get('verified') is True) is (phase == 'unchanged')


@pytest.mark.parametrize('fault', ['wrong-at-preview', 'drift-before-write'])
def test_ordinary_merge_collision_requires_actual_class_before_dispatch(tmp_path, fault):
    task = class_task(tmp_path)
    task.objects[CHILD] = {'id': CHILD, 'name': 'Rain', 'type': 'Sound', 'classId': 1 if fault == 'wrong-at-preview' else 2,
        'path': task.objects[SECOND]['path'] + r'\Rain', 'parent': {'id': SECOND}, 'notes': 'Keep'}
    task.bind(SECOND)
    code, configured = task.step('draft-business-configure', '--name-conflict', 'merge')
    assert code == 0, configured
    declare_sound(task)
    if fault == 'wrong-at-preview':
        code, result = task.step('draft-check')
        assert code == 2, result
    else:
        tx, shown = task.preview()
        code, result = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
        assert code == 0, result
        task.objects[CHILD]['classId'] = 1
        code, result = task.run('execute', tx)
        assert code == 2, result
    assert not any(uri.endswith('object.create') for uri, _, _ in task.calls)


@pytest.mark.parametrize('phase', ['unchanged-alias', 'before-write', 'after-write'])
def test_class_catalogue_binding_preserves_actor_alias_and_rejects_drift(tmp_path, phase):
    task = class_task(tmp_path)
    parent = task.bind(SECOND)
    code, result = task.step('draft-declare-new', '--declaration-id', 'layers',
        '--parent-handle', parent, '--kind', 'actor-mixer', '--name', 'Layers')
    assert code == 0, result
    tx, shown = task.preview()
    code, result = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, result
    if phase == 'before-write':
        task.types[0]['classId'] = 4
    code, result = task.run('execute', tx)
    if phase == 'before-write':
        assert code == 2 and not any(uri.endswith('object.create') for uri, _, _ in task.calls), result
        return
    assert code == 0, result
    if phase == 'after-write':
        task.types[0]['classId'] = 4
    code, result = task.run('verify', tx)
    assert code == (0 if phase == 'unchanged-alias' else 2), result
    assert task.objects[ROOT]['type'] == 'PropertyContainer'


def import_task(path, *, version='2022.1'):
    from tests.unit.test_anonymous_effect_slot_graph_gateway import legacy_render_import_task
    task, writes = legacy_render_import_task(path, version, media=True)
    task.types.append({'name': 'AudioSource' if version == '2021.1' else 'AudioFileSource',
        'classId': 16, 'type': 'WObject'})
    task.require_class_projection = True
    if version == '2021.1':
        import xml.etree.ElementTree as ET
        from tests.unit.test_operation_registry_import_verifier import WWISE_2021_PROJECT
        tree = ET.parse(WWISE_2021_PROJECT)
        project = tree.find('./ProjectInfo/Project')
        project.set('Name', 'Fixture'); project.set('ID', '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}')
        tree.write(task.project_file, encoding='utf-8', xml_declaration=True)
        (task.project_file.parent / 'Originals').mkdir()
    original = task.call
    def call(uri, args=None, options=None):
        if uri.endswith('object.get') and args.get('waql') in {'from type Project take 1', 'from type Project take 2'}:
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': [{'id': '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}', 'name': 'Fixture',
                'type': 'Project', 'path': '\\', 'filePath': str(task.project_file), 'workunitIsDirty': False}]}
        if uri.endswith('getProjectInfo') and version == '2021.1':
            from tests.unit.test_object_native_surface import _project_info
            return {**_project_info(task.project_file.parent, language='SFX'), **original(uri, args, options)}
        result = original(uri, args, options)
        if uri.endswith('audio.import'):
            for row in task.objects.values():
                if row['type'] == 'AudioFileSource':
                    row['classId'] = 16
                if version == '2021.1' and 'originalFilePath' in row:
                    row['originalWavFilePath'] = row['sound:originalWavFilePath'] = row['originalFilePath']
        return result
    task.call = call
    return task, writes


def declare_import(task, path):
    import wave
    source = path / 'independent.wav'
    with wave.open(str(source), 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(48000); wav.writeframes(b'\0\0' * 8)
    parent = task.bind(SECOND)
    code, declared = task.step('draft-declare-new', '--declaration-id', 'rain',
        '--parent-handle', parent, '--kind', 'sound-sfx', '--name', 'New Sound',
        '--field', 'media_file', str(source), '--field', 'volume_db', '-9')
    assert code == 0, declared


@pytest.mark.parametrize('fault', ['target-class', 'source-class', None])
def test_import_independent_target_and_source_reads_require_live_classes(tmp_path, fault):
    task, writes = import_task(tmp_path)
    declare_import(task, tmp_path)
    tx, shown = task.preview()
    execute(task, tx, shown)
    target = next(row for row in task.objects.values() if row['name'] == 'New Sound')
    source = task.objects[target['activeSource']['id']]
    if fault == 'target-class':
        target['classId'] = 16
    elif fault == 'source-class':
        source['classId'] = 65552
    code, result = task.run('verify', tx)
    assert code == (0 if fault is None else 2), json.dumps(result)
    assert (result.get('verified') is True) is (fault is None)
    assert len(writes) == 1


def test_2021_import_uses_pinned_live_audio_source_class_without_changing_actual_type(tmp_path):
    task, writes = import_task(tmp_path, version='2021.1')
    declare_import(task, tmp_path)
    tx, shown = task.preview()
    execute(task, tx, shown)
    code, result = task.run('verify', tx)
    assert code == 0 and result['verified'] is True, json.dumps(result)
    assert next(row for row in task.types if row['name'] == 'AudioSource')['classId'] == 16
    assert any(row['type'] == 'AudioFileSource' and row['classId'] == 16 for row in task.objects.values())
    assert len(writes) == 1


@pytest.mark.parametrize('fault', ['valid', 'wrong-source-class', 'wrong-target-class'])
def test_object_set_import_reads_actual_source_and_requested_sound_classes(tmp_path, fault):
    from tests.unit.test_object_graph_business_gateway import _public_inline_wav_preview, INLINE_PCM_PADDED
    code, result, calls = _public_inline_wav_preview(tmp_path, '2025.1',
        'Inline.wav|' + INLINE_PCM_PADDED, nested=False, verification_case=fault)
    assert code == (0 if fault == 'valid' else 2), json.dumps(result)
    assert (result.get('verified') is True) is (fault == 'valid')
    assert calls.count('ak.wwise.core.object.set') == 1


def test_existing_ordinary_root_type_and_live_class_must_agree_at_preview(tmp_path):
    task = class_task(tmp_path, operation='object.set')
    task.objects[FIRST]['type'] = 'Sound'  # Still has independently supplied ActorMixer class 1.
    owner = task.bind(FIRST)
    code, declared = task.step('draft-declare-existing', '--declaration-id', 'owner',
        '--object-handle', owner, '--field', 'notes', 'Reviewed')
    assert code == 0, declared
    code, rejected = task.step('draft-check')
    assert code == 2 and not any(uri.endswith('object.set') for uri, _, _ in task.calls), rejected
