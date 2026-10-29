"""Recursive prerequisites are accumulated before the Gateway chooses values.

These are public contract models for the observed scalar dependency grammar;
they do not claim native effects for the composed graph.
"""
from copy import deepcopy

import pytest

from tests.unit.test_conditional_reference_gateway import ScalarPropertyTask, FIRST, SECOND, VERSIONS, condition
from tests.unit.test_time_modulator_range_gateway import finish, start, declare


def closure_task(tmp_path, version='2025.1', *, reverse=False, operation='object.set', reference=False, explicit_mode=None):
    task = ScalarPropertyTask(tmp_path, version, operation=operation)
    roots = [condition('GateA'), condition('GateB')]
    if reverse:
        roots.reverse()
    def mode(values):
        rule = condition('Mode')
        rule['conditions'][0]['restriction']['values'] = [{'value': value} for value in values]
        return rule
    task.metadata = {
        'Value': {'name': 'Value', 'type': 'Real64', 'dependencies': roots},
        'GateA': {'name': 'GateA', 'type': 'bool', 'dependencies': [mode([1, 2])]},
        'GateB': {'name': 'GateB', 'type': 'bool', 'dependencies': [mode([2, 3])]},
        'Mode': {'name': 'Mode', 'type': 'int16'},
    }
    if reference:
        task.metadata['Attenuation'] = {**task.metadata.pop('Value'), 'name': 'Attenuation', 'type': '',
            'restriction': {'type': 'reference', 'restrictions': [{'type': ['Attenuation']}]}}
    task.objects[FIRST].update(Value=0.0, GateA=True, GateB=True, Mode=0)
    source = task.bind(FIRST)
    field = task.discover(source, 'Attenuation' if reference else 'Value')
    business_value = task.bind(SECOND) if reference else '37.0'
    if operation == 'object.set':
        extra = [] if explicit_mode is None else ['--field-value', task.discover(source, 'Mode'), str(explicit_mode)]
        code, declared = task.step('draft-declare-existing', '--declaration-id', 'closed-prerequisites',
            '--object-handle', source, '--field-value', field, business_value, *extra)
    else:
        code, declared = task.step('draft-declare-field-change', '--object-handle', source,
            '--field-handle', field, '--target-handle' if reference else '--business-value', business_value)
    assert code == 0, declared
    return task


@pytest.mark.parametrize('version', VERSIONS[1:])
@pytest.mark.parametrize('reverse', [False, True])
def test_recursive_controller_intersection_is_previewed_as_one_unique_change(tmp_path, version, reverse):
    task = closure_task(tmp_path, version, reverse=reverse)
    before = deepcopy(task.objects[FIRST])
    preview, _, verified, _ = finish(task)
    assert [(row['field'], row['value']) for row in preview['preview_summary']['derived_changes']] == [('Mode', 2)]
    assert verified['verified'] is True
    assert task.objects[FIRST] == {**before, 'Value': 37.0, 'Mode': 2}
    writes = [args for uri, args, _ in task.calls if uri.endswith('object.set')]
    assert len(writes) == 1
    assert writes[0]['objects'][0]['@Mode'] == 2


@pytest.mark.parametrize('version', VERSIONS)
def test_reference_assignment_reuses_the_complete_satisfied_scalar_closure(tmp_path, version):
    task = closure_task(tmp_path, version, operation='object.setReference', reference=True)
    task.objects[FIRST]['Mode'] = 2
    before = deepcopy(task.objects[FIRST])
    preview, _, _, _ = finish(task)
    assert not preview['preview_summary'].get('derived_changes')
    assert task.objects[FIRST] == {**before, 'Attenuation': {'id': SECOND}}
    assert [args for uri, args, _ in task.calls if uri.endswith('setReference')] == [
        {'object': FIRST, 'reference': 'Attenuation', 'value': SECOND}]
    assert not any(uri.endswith('setProperty') for uri, _, _ in task.calls)


@pytest.mark.parametrize('value', [1, 2])
def test_explicit_controller_intent_is_checked_against_the_entire_closure(tmp_path, value):
    task = closure_task(tmp_path, explicit_mode=value)
    before = deepcopy(task.objects)
    code, checked = task.step('draft-check')
    if value == 1:
        assert code == 2 and 'REFERENCE_DEPENDENCY_CONFLICT' in str(checked), checked
        assert task.objects == before
        assert not any(uri.endswith(('setProperty', 'object.set')) for uri, _, _ in task.calls)
    else:
        assert code == 0, checked
        preview, _, _, _ = finish(task)
        assert not preview['preview_summary'].get('derived_changes')
        assert task.objects[FIRST] == {**before[FIRST], 'Mode': 2, 'Value': 37.0}


@pytest.mark.parametrize('version', VERSIONS)
def test_single_field_discloses_and_accepts_the_complete_recursive_repair(tmp_path, version):
    task = closure_task(tmp_path, version, operation='object.setProperty')
    before = deepcopy(task.objects[FIRST])
    original = task.draft, task.authority, task.revision
    code, checked = task.step('draft-check')
    assert code == 2 and checked['error_code'] == 'REFERENCE_ACTIVATION_REQUIRED', checked
    assert checked['details']['prerequisite_changes'] == [{
        'operation': 'object.setProperty', 'discovery_meaning': 'Mode',
        'required_value': 2, 'selection': 'live_discovered_Field_Handle'}]
    assert task.objects[FIRST] == before
    assert not any(uri.endswith(('setProperty', 'object.set')) for uri, _, _ in task.calls)
    start(task)
    declare(task, 'Mode', 2)
    finish(task)
    task.draft, task.authority, task.revision = original
    preview, _, _, _ = finish(task)
    assert not preview['preview_summary'].get('derived_changes')
    assert task.objects[FIRST] == {**before, 'Mode': 2, 'Value': 37.0}
    assert [args for uri, args, _ in task.calls if uri.endswith('setProperty')] == [
        {'object': FIRST, 'property': 'Mode', 'value': 2},
        {'object': FIRST, 'property': 'Value', 'value': 37.0}]


@pytest.mark.parametrize('failure', ['conflict', 'cycle', 'malformed', 'wrong-controller'])
def test_invalid_recursive_closure_never_reaches_mutation(tmp_path, failure):
    task = closure_task(tmp_path)
    before = deepcopy(task.objects)
    if failure == 'conflict':
        task.metadata['GateB']['dependencies'][0]['conditions'][0]['restriction']['values'] = [{'value': 3}]
    elif failure == 'cycle':
        task.metadata['Mode']['dependencies'] = [condition('GateA')]
    elif failure == 'malformed':
        task.metadata['GateB']['dependencies'][0]['conditions'] = [{'restriction': {'type': 'unknown'}}]
    else:
        task.metadata['Mode']['name'] = 'OtherMode'
    code, checked = task.step('draft-check')
    assert code == 2, checked
    expected = {'conflict': 'REFERENCE_DEPENDENCY_CONFLICT', 'cycle': 'REFERENCE_DEPENDENCY_CYCLE',
                'malformed': 'CONSTRAINED_REFERENCE_BOUNDARY', 'wrong-controller': 'INVALID_METADATA'}[failure]
    assert expected in str(checked), checked
    assert task.objects == before
    assert not any(uri.endswith(('setProperty', 'setReference', 'object.set')) for uri, _, _ in task.calls)


@pytest.mark.parametrize('drift', ['before', 'after'])
def test_every_branch_of_recursive_metadata_closure_is_guarded(tmp_path, drift):
    task = closure_task(tmp_path)
    code, checked = task.step('draft-check')
    assert code == 0, checked
    code, preview = task.step('preview-from-draft')
    assert code == 0, preview
    tx = preview['transaction_id']
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    def change():
        task.metadata['GateB']['dependencies'][0]['conditions'][0]['restriction']['values'] = [{'value': 3}]
    if drift == 'before':
        change()
    code, executed = task.run('execute', tx)
    if drift == 'before':
        assert code == 2, executed
        assert not any(uri.endswith('object.set') for uri, _, _ in task.calls)
    else:
        assert code == 0, executed
        change()
        code, verified = task.run('verify', tx)
        assert code == 2 and verified.get('verified') is not True, verified
