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
