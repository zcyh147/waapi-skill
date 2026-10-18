"""Exclusive is property cardinality, rather than property/input-pair identity."""
from copy import deepcopy
import json

import pytest

from tests.unit.test_unnamed_rtpc_graph_gateway import rtpc_task, seed_pair, FIRST, ROOT, CHILD, CURVE_A
from tests.unit.test_list_merge_existing_conditions_gateway import select_field

OTHER = '{88888888-8888-8888-8888-888888888888}'


def support_task(tmp_path, *, version='2025.1', operation='object.set'):
    task, writes = rtpc_task(tmp_path, version, operation=operation)
    task.objects[OTHER] = {**deepcopy(task.objects[ROOT]), 'id': OTHER, 'name': 'Other Input',
        'path': r'\Game Parameters\Default Work Unit\Other Input'}
    # Primary WObjects CenterPercentage: int32,0..100,Exclusive. This is a
    # fixture of the cardinality fact, not a literal observed native metadata
    # record or proof of its positioning activation/visibility dependencies.
    task.metadata['CenterPercentage'] = {'name': 'CenterPercentage', 'type': 'int32', 'default': 0,
        'supports': {'rtpc': 'Exclusive'}, 'restriction': {'type': 'range', 'min': 0, 'max': 100}}
    return task, writes


def declare_center(task, owner, control, *, declaration_id=None):
    field = select_field(task, owner=owner, token='CenterPercentage')
    args = ['--declaration-id', declaration_id] if declaration_id else []
    return task.step('draft-declare-rtpc', *args, '--object-handle', owner, '--field-handle', field,
        '--control-input-handle', control, '--point', '0', '0', 'Linear', '--point', '100', '100', 'Linear')


def test_two_new_inputs_cannot_bypass_one_exclusive_property_limit(tmp_path):
    task, writes = support_task(tmp_path)
    owner, first, other = task.bind(FIRST), task.bind(ROOT), task.bind(OTHER)
    for declaration_id, control in [('first', first), ('other', other)]:
        code, declared = declare_center(task, owner, control, declaration_id=declaration_id)
        assert code == 0, declared
    code, checked = task.step('draft-check')
    assert code == 2, checked
    assert 'RTPC_EXCLUSIVE_CONFLICT' in json.dumps(checked), checked
    assert not writes


@pytest.mark.parametrize('version', ['2022.1', '2023.1', '2024.1', '2025.1'])
@pytest.mark.parametrize('operation', ['object.set', 'object.setRTPC'])
def test_different_input_append_preserves_existing_exclusive_pair_before_dispatch(tmp_path, version, operation):
    task, writes = support_task(tmp_path, version=version, operation=operation)
    before = seed_pair(task, property_name='CenterPercentage')
    owner, other = task.bind(FIRST), task.bind(OTHER)
    code, declared = declare_center(task, owner, other, declaration_id='other' if operation == 'object.set' else None)
    assert code == 0, declared
    code, checked = task.step('draft-check')
    assert code == 2, checked
    assert 'RTPC_EXCLUSIVE_CONFLICT' in json.dumps(checked), checked
    assert not writes and task.objects[CHILD] == before


@pytest.mark.parametrize('operation', ['object.set', 'object.setRTPC'])
def test_same_exclusive_pair_updates_its_actual_guid_without_removing_old_state(tmp_path, operation):
    task, _ = support_task(tmp_path, operation=operation)
    seed_pair(task, property_name='CenterPercentage')
    owner, control = task.bind(FIRST), task.bind(ROOT)
    before_owner = deepcopy(task.objects[FIRST])
    code, declared = declare_center(task, owner, control, declaration_id='curve' if operation == 'object.set' else None)
    assert code == 0, declared
    original, writes = task.call, []
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            writes.append(deepcopy(args))
            assert args['objects'] == [{'object': CHILD, '@Curve': {'type': 'Curve',
                'points': [{'x': 0, 'y': 0, 'shape': 'Linear'}, {'x': 100, 'y': 100, 'shape': 'Linear'}]}}]
            task.objects[CHILD]['@Curve']['points'] = deepcopy(args['objects'][0]['@Curve']['points'])
            return {'objects': []}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified.get('verified') is True, verified
    assert len(writes) == 1 and task.objects[FIRST] == before_owner


@pytest.mark.parametrize('mode', ['Additive', 'Multiplicative'])
def test_nonexclusive_property_keeps_multiple_distinct_inputs(tmp_path, mode):
    task, _ = support_task(tmp_path)
    if mode == 'Additive':
        token, points = 'Volume', [('0', '-48'), ('100', '0')]
    else:
        # Primary PlaybackSpeed: Real64,0.25..4,Multiplicative; fixture-only
        # normalized metadata, not an invented native response receipt.
        token, points = 'PlaybackSpeed', [('0', '0.5'), ('100', '2')]
        task.metadata[token] = {'name': token, 'type': 'Real64', 'default': 1,
            'supports': {'rtpc': 'Multiplicative'}, 'restriction': {'type': 'range', 'min': 0.25, 'max': 4}}
    owner, first, other = task.bind(FIRST), task.bind(ROOT), task.bind(OTHER)
    field = select_field(task, owner=owner, token=token)
    for declaration_id, control in [('first', first), ('other', other)]:
        code, declared = task.step('draft-declare-rtpc', '--declaration-id', declaration_id,
            '--object-handle', owner, '--field-handle', field, '--control-input-handle', control,
            '--point', *points[0], 'Linear', '--point', *points[1], 'Linear')
        assert code == 0, declared
    original, writes = task.call, []
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            writes.append(deepcopy(args))
            nodes = args['objects'][0]['@RTPC']
            assert len(nodes) == 2 and all(node['@PropertyName'] == token for node in nodes)
            assert [node['@ControlInput'] for node in nodes] == [ROOT, OTHER]
            from tests.unit.test_unnamed_rtpc_graph_gateway import RTPC_B, CURVE_B
            task.objects[FIRST]['@RTPC'] = []
            for node, identity, curve in zip(nodes, [CHILD, RTPC_B], [CURVE_A, CURVE_B]):
                seed_pair(task, identity=identity, property_name=token, curve=curve)
                task.objects[identity]['@ControlInput'] = {'id': node['@ControlInput']}
                task.objects[identity]['@Curve']['points'] = deepcopy(node['@Curve']['points'])
            return {'objects': [{'id': FIRST, 'name': 'Sender', '@RTPC': [
                {'id': CHILD, 'name': ''}, {'id': RTPC_B, 'name': ''}]}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified.get('verified') is True, verified
    assert len(writes) == 1


def test_standalone_revalidates_support_mode_before_exclusive_conflict_can_write(tmp_path):
    task, _ = support_task(tmp_path, operation='object.setRTPC')
    seed_pair(task, property_name='Volume')
    owner, other = task.bind(FIRST), task.bind(OTHER)
    field = select_field(task, owner=owner, token='Volume')
    code, declared = task.step('draft-declare-rtpc', '--object-handle', owner, '--field-handle', field,
        '--control-input-handle', other, '--point', '0', '-48', 'Linear', '--point', '100', '0', 'Linear')
    assert code == 0, declared
    tx, shown = task.preview()
    task.metadata['Volume']['supports']['rtpc'] = 'Exclusive'
    original, writes = task.call, []
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            writes.append(deepcopy(args))
            raise RuntimeError('Unexpected write after property support drift')
        return original(uri, args, options)
    task.call = call
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, rejected = task.run('execute', tx)
    assert code == 2, rejected
    assert not writes


@pytest.mark.parametrize('two_inputs', [False, True])
def test_explicit_replace_all_obeys_exclusive_final_property_count(tmp_path, two_inputs):
    task, _ = support_task(tmp_path)
    before = seed_pair(task, property_name='CenterPercentage')
    owner, first, other = task.bind(FIRST), task.bind(ROOT), task.bind(OTHER)
    code, configured = task.step('draft-business-configure', '--list-behavior', 'replace-all')
    assert code == 0, configured
    code, declared = declare_center(task, owner, other, declaration_id='replacement')
    assert code == 0, declared
    if two_inputs:
        code, declared = declare_center(task, owner, first, declaration_id='another')
        assert code == 0, declared
        code, checked = task.step('draft-check')
        assert code == 2 and 'RTPC_EXCLUSIVE_CONFLICT' in json.dumps(checked), checked
        assert task.objects[CHILD] == before
        assert not any(uri.endswith('object.set') for uri, _, _ in task.calls)
        return
    original, writes = task.call, []
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            writes.append(deepcopy(args))
            assert args['listMode'] == 'replaceAll' and len(args['objects']) == 1
            node = args['objects'][0]['@RTPC'][0]
            assert node['@PropertyName'] == 'CenterPercentage' and node['@ControlInput'] == OTHER
            from tests.unit.test_unnamed_rtpc_graph_gateway import RTPC_B, CURVE_B
            del task.objects[CHILD]
            del task.objects[CURVE_A]
            task.objects[FIRST]['@RTPC'] = []
            seed_pair(task, identity=RTPC_B, property_name='CenterPercentage', curve=CURVE_B)
            task.objects[RTPC_B]['@ControlInput'] = {'id': OTHER}
            task.objects[RTPC_B]['@Curve']['points'] = deepcopy(node['@Curve']['points'])
            return {'objects': [{'id': FIRST, 'name': 'Sender', '@RTPC': [{'id': RTPC_B, 'name': ''}]}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified.get('verified') is True, verified
    assert len(writes) == 1 and CHILD not in task.objects


def test_planned_owner_class_support_cannot_admit_two_exclusive_inputs(tmp_path):
    from tests.unit.test_unnamed_rtpc_graph_gateway import SECOND
    task, writes = support_task(tmp_path)
    parent, first, other = task.bind(SECOND), task.bind(ROOT), task.bind(OTHER)
    code, found = task.step('draft-discover-types', '--role', 'object', '--meaning', 'Sound')
    assert code == 0, found
    kind = found['type_candidates'][0]['handle']
    code, declared = task.step('draft-declare-new', '--declaration-id', 'sound', '--parent-handle', parent,
        '--name', 'New sound', '--kind', kind)
    assert code == 0, declared
    owner = declared['draft']['declared_object']['result_handle']
    field = select_field(task, kind=kind, token='CenterPercentage')
    for declaration_id, control in [('first', first), ('other', other)]:
        code, declared = task.step('draft-declare-rtpc', '--declaration-id', declaration_id,
            '--object-handle', owner, '--field-handle', field, '--control-input-handle', control,
            '--point', '0', '0', 'Linear', '--point', '100', '100', 'Linear')
        assert code == 0, declared
    code, checked = task.step('draft-check')
    assert code == 2 and 'RTPC_EXCLUSIVE_CONFLICT' in json.dumps(checked), checked
    assert not writes


@pytest.mark.parametrize('operation', ['object.set', 'object.setRTPC'])
def test_public_schema_discloses_exclusive_cardinality_and_explicit_replacement(tmp_path, operation):
    task, _ = support_task(tmp_path, operation=operation)
    code, schema = task.run('operation-schema', operation)
    assert code == 0, schema

    def find_cardinality(value):
        if isinstance(value, dict):
            if 'property_cardinality' in value:
                return value['property_cardinality']
            for nested in value.values():
                found = find_cardinality(nested)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for nested in value:
                found = find_cardinality(nested)
                if found is not None:
                    return found

    cardinality = find_cardinality(schema)
    assert cardinality == {
        'metadata_source': 'selected_owner_property_supports.rtpc',
        'Exclusive': 'at_most_one_RTPC_per_property_regardless_of_ControlInput',
        'Additive': 'distinct_ControlInput_pairs_remain_allowed_within_the_list_bounds',
        'Multiplicative': 'distinct_ControlInput_pairs_remain_allowed_within_the_list_bounds',
        'same_pair_update': 'retain_the_exact_existing_RTPC_GUID',
        'different_input_append': 'cannot_remove_an_unrequested_existing_Exclusive_pair',
        'replace_all': 'explicit_complete_list_replacement_still_obeys_each_Exclusive_property_limit',
    }
