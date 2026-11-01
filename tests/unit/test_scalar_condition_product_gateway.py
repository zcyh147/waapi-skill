"""Bounded scalar changes through the closed field workflow."""
from copy import deepcopy
import json
import pytest
from tests.unit.test_conditional_reference_gateway import ScalarPropertyTask, FIRST, condition
from tests.unit.test_time_modulator_range_gateway import finish


def scalar_workflow(path, version, field, metadata, requested, *, gate=True):
    task = ScalarPropertyTask(path, version)
    task.metadata = {field: {'name': field, **metadata, 'dependencies': [condition('Gate')]},
                     'Gate': {'name': 'Gate', 'type': 'bool'}}
    task.objects[FIRST].update({field: False if type(requested) is bool else '' if isinstance(requested, str) else 0, 'Gate': gate})
    before = deepcopy(task.objects[FIRST])
    target = task.bind(FIRST)
    selected = task.discover(target, field)
    value = requested if isinstance(requested, str) else json.dumps(requested)
    code, declared = task.step('draft-declare-field-change', '--object-handle', target,
                              '--field-handle', selected, '--business-value', value)
    assert code == 0, declared
    if not gate:
        code, rejected = task.step('draft-check')
        assert code == 2, rejected
        assert task.objects[FIRST] == before
        assert not any(uri.endswith(('setProperty', 'setReference', 'object.set')) for uri, _, _ in task.calls)
        return
    preview, code, verified, _ = finish(task)
    assert code == 0 and verified['verified'] is True
    assert not preview['preview_summary'].get('derived_changes')
    assert task.objects[FIRST] == {**before, field: requested}
    writes = [args for uri, args, _ in task.calls if uri.endswith('setProperty')]
    assert writes == [{'object': FIRST, 'property': field, 'value': requested}]
    assert type(writes[0]['value']) is type(requested)


@pytest.mark.parametrize('version', ['2021.1','2022.1','2023.1','2024.1','2025.1'])
@pytest.mark.parametrize('kind,value', [('bool', True), ('int16', 7), ('Real64', 3.5), ('string', 'literal cue')])
def test_condition_scalar_type_preservation(tmp_path, version, kind, value):
    scalar_workflow(tmp_path, version, 'Value', {'type': kind}, value)


def test_condition_scalar_requires_explicit_prerequisite(tmp_path):
    scalar_workflow(tmp_path, '2025.1', 'Value', {'type': 'Real64'}, 3.5, gate=False)
