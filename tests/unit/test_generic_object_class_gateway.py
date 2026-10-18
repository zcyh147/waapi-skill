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
