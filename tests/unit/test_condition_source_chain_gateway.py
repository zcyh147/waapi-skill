"""Pinned recursive conditions must reach the ordinary closed field workflow."""
from copy import deepcopy
from pathlib import Path

import pytest

from tests.support.condition_scalar_batch import scalar_manifest, scalar_plan
from tests.unit.test_scalar_condition_product_gateway import run_scalar_public_group


@pytest.fixture(scope='module')
def source_plan():
    return scalar_plan(scalar_manifest(Path(__file__).parents[2]))


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1'])
def test_pinned_play_mechanism_loop_count_reaches_closed_preview_and_verification(tmp_path, source_plan, version):
    group = next(g for g in source_plan['groups'] if g['version'] == version and g['field'] == 'PlayMechanismLoopCount')
    assert group['model']['before'] == {'PlayMechanismLoopCount': 2,
        'PlayMechanismInfiniteOrNumberOfLoops': 0, 'PlayMechanismLoop': True, 'PlayMechanismStepOrContinuous': 0}
    observed = run_scalar_public_group(tmp_path / 'workflow', group)
    assert len(observed['workflows']) == 1
    actual = next(iter(observed['workflows'].values()))
    assert actual['gateway']['payload']['verified'] is True
    assert actual['native_call']['args']['property'] == 'PlayMechanismLoopCount'
    assert actual['observations']['after'] == {**actual['observations']['before'], 'PlayMechanismLoopCount': 1}


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


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1'])
def test_source_string_field_uses_the_literal_business_value_contract(tmp_path, source_plan, version):
    group = next(g for g in source_plan['groups'] if g['version'] == version and g['field'] == 'ExitSourceCustomCueMatchName')
    observed = run_scalar_public_group(tmp_path / 'workflow', group)
    assert {flow['observations']['before']['ExitSourceAt'] for flow in observed['workflows'].values()} == {4, 5}
    for actual in observed['workflows'].values():
        assert actual['native_call']['args']['value'] == group['model']['requested']
        assert type(actual['native_call']['args']['value']) is str


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1'])
def test_real_field_witness_uses_the_public_number_representation(tmp_path, source_plan, version):
    group = next(g for g in source_plan['groups'] if g['version'] == version and g['field'] == 'PlayMechanismTransitionTime')
    assert group['model']['metadata'][group['field']]['type'] == 'Real64'
    assert type(group['model']['requested']) is float
    observed = run_scalar_public_group(tmp_path / 'workflow', group)
    for actual in observed['workflows'].values():
        assert type(actual['native_call']['args']['value']) is float
        assert actual['native_call']['args']['value'] == group['model']['requested']
