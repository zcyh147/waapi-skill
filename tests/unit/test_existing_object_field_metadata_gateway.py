"""Existing-object metadata remains authoritative even without dependencies."""
from copy import deepcopy

import pytest

from tests.unit.test_conditional_reference_gateway import AttenuationTask, FIRST, SECOND, VERSIONS
from tests.unit.test_generic_object_class_gateway import class_task, execute
from tests.unit.test_playlist_reference_gateway import preview_and_confirm, writes


@pytest.mark.parametrize('version', VERSIONS[1:])
@pytest.mark.parametrize('stage', ['unchanged', 'before-execute', 'after-execute'])
@pytest.mark.parametrize('field_kind', ['reference', 'property'])
def test_dependency_free_field_metadata_is_bound_through_object_set_verification(tmp_path, version, stage, field_kind):
    task = AttenuationTask(tmp_path, version, operation='object.set')
    task.metadata['Attenuation']['dependencies'] = []
    if field_kind == 'property':
        task.metadata['Volume'] = {'name': 'Volume', 'type': 'Real64',
            'restriction': {'type': 'range', 'min': -96, 'max': 12}}
    before = deepcopy(task.objects)
    if field_kind == 'reference':
        task.declare()
    else:
        source = task.bind(FIRST)
        field = task.discover(source, 'Volume')
        code, declared = task.step('draft-declare-existing', '--declaration-id', 'volume',
            '--object-handle', source, '--field-value', field, '-6')
        assert code == 0, declared
    tx = preview_and_confirm(task)
    def change_metadata():
        if field_kind == 'reference':
            task.metadata['Attenuation']['restriction']['restrictions'][0]['type'].append('Sound')
        else:
            task.metadata['Volume']['restriction']['max'] = 10
    if stage == 'before-execute':
        change_metadata()
    code, executed = task.run('execute', tx)
    if stage == 'before-execute':
        assert code == 2, executed
        assert task.objects == before and writes(task) == []
    else:
        assert code == 0, executed
        if stage == 'after-execute':
            change_metadata()
        code, verified = task.run('verify', tx)
        assert code == (0 if stage == 'unchanged' else 2), verified
        assert (verified['verified'] is True) is (stage == 'unchanged')
        intended = {'Attenuation': {'id': SECOND}} if field_kind == 'reference' else {'Volume': -6}
        assert task.objects == {**before, FIRST: {**before[FIRST], **intended}}
        assert len(writes(task)) == 1
    code, replay = task.run('execute', tx)
    assert code == 2, replay
    assert len(writes(task)) == (0 if stage == 'before-execute' else 1)


@pytest.mark.parametrize('version', VERSIONS[1:])
def test_notes_only_object_set_does_not_acquire_field_metadata(tmp_path, version):
    task = class_task(tmp_path, operation='object.set', version=version)
    source = task.bind(FIRST)
    code, declared = task.step('draft-declare-existing', '--declaration-id', 'notes',
        '--object-handle', source, '--field', 'notes', 'Reviewed note')
    assert code == 0, declared
    tx, shown = task.preview()
    execute(task, tx, shown)
    code, verified = task.run('verify', tx)
    assert code == 0 and verified['verified'] is True, verified
    assert task.objects[FIRST]['notes'] == 'Reviewed note'
    assert not any(uri.endswith('getPropertyInfo') for uri, _, _ in task.calls)
