"""Recursive condition budget through the closed Gateway."""
from copy import deepcopy

def test_full_controller_budget_reaches_closed_check_preview_and_verify(tmp_path):
    from tests.unit.test_conditional_reference_gateway import ScalarPropertyTask, FIRST, condition
    from tests.unit.test_time_modulator_range_gateway import finish
    task = ScalarPropertyTask(tmp_path, '2025.1')
    task.metadata = {'Value': {'name': 'Value', 'type': 'Real64', 'dependencies': [condition('Gate0')]}}
    for index in range(16):
        name = 'Gate' + str(index)
        task.metadata[name] = {'name': name, 'type': 'bool', 'dependencies': [condition('Gate' + str(index + 1))] if index < 15 else []}
    task.objects[FIRST].update(Value=0.0, **{'Gate' + str(index): True for index in range(16)})
    before = deepcopy(task.objects[FIRST])
    target = task.bind(FIRST)
    field = task.discover(target, 'Value')
    code, declared = task.step('draft-declare-field-change', '--object-handle', target, '--field-handle', field, '--business-value', '37.0')
    assert code == 0, declared
    preview, _, verified, _ = finish(task)
    assert not preview['preview_summary'].get('derived_changes')
    assert verified['verified'] is True
    assert task.objects[FIRST] == {**before, 'Value': 37.0}
    assert [args for uri, args, _ in task.calls if uri.endswith('setProperty')] == [{'object': FIRST, 'property': 'Value', 'value': 37.0}]
