"""Unnamed RTPC pairs remain typed graph outcomes through the public Gateway."""
from copy import deepcopy
import json

import pytest

from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, FIRST, SECOND, ROOT, CHILD
from tests.unit.test_list_merge_existing_conditions_gateway import select_field

CURVE_A = '{55555555-5555-5555-5555-555555555555}'
CURVE_B = '{66666666-6666-6666-6666-666666666666}'
RTPC_B = '{77777777-7777-7777-7777-777777777777}'
POINTS = [(0, -48), (100, 0)]


def rtpc_task(tmp_path, version='2025.1', fault=None, operation='object.set'):
    tmp_path.mkdir(parents=True, exist_ok=True)
    task = OwnedGraphTask(tmp_path, version, operation)
    task.types = [{'name': name, 'classId': value, 'type': 'WObject'} for name, value in
        [('Sound', 65552), ('GameParameter', 1507344), ('RTPC', 1441808), ('Curve', 917520), ('WorkUnit', 1638416)]]
    base = r'\Actor-Mixer Hierarchy\Default Work Unit'
    task.objects = {
        FIRST: {'id': FIRST, 'name': 'Sender', 'type': 'Sound', 'classId': 65552,
            'path': base + r'\Sender', 'parent': {'id': SECOND}, 'notes': 'Keep sound', '@RTPC': []},
        SECOND: {'id': SECOND, 'name': 'Default Work Unit', 'type': 'WorkUnit', 'classId': 1638416,
            'path': base, 'parent': None, 'notes': 'Keep work unit'},
        ROOT: {'id': ROOT, 'name': 'Intensity', 'type': 'GameParameter', 'classId': 1507344,
            'path': r'\Game Parameters\Default Work Unit\Intensity', 'parent': {'id': SECOND}, 'notes': 'Keep input'},
    }
    # Normalized source-shaped fixtures only; no claim these are native receipts.
    task.metadata = {
        'Volume': {'name': 'Volume', 'type': 'Real64', 'default': 0,
            'supports': {'rtpc': 'Additive'}, 'restriction': {'type': 'range', 'min': -200, 'max': 12}},
        'Pitch': {'name': 'Pitch', 'type': 'Real64', 'default': 0,
            'supports': {'rtpc': 'Additive'}, 'restriction': {'type': 'range', 'min': -2400, 'max': 2400}},
        'PropertyName': {'name': 'PropertyName', 'type': 'string', 'default': ''},
        'ControlInput': {'name': 'ControlInput', 'type': '',
            'restriction': {'type': 'reference', 'restrictions': [{'type': ['GameParameter']}]}},
        'Curve': {'name': 'Curve', 'type': '', 'restriction': {'type': 'reference',
            'restrictions': [{'type': ['Curve']}, 'notNull']}},
    }
    original = task.call
    writes = []
    def call(uri, args=None, options=None):
        if uri.endswith('isPropertyEnabled'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': True}
        if uri.endswith('object.set'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            writes.append(deepcopy(args))
            nodes = args['objects'][0]['@RTPC']
            assert len(nodes) == 2 and all(node['name'] == '' and node['type'] == 'RTPC' for node in nodes)
            assert [node['@PropertyName'] for node in nodes] == ['Volume', 'Pitch']
            for node, identity, curve in zip(nodes, (CHILD, RTPC_B), (CURVE_A, CURVE_B)):
                task.objects[identity] = {'id': identity, 'name': '', 'type': 'RTPC', 'classId': 1441808,
                    'path': '\\opaque-' + identity, 'owner': {'id': FIRST}, 'notes': node.get('notes', ''),
                    '@PropertyName': node['@PropertyName'], '@ControlInput': {'id': node['@ControlInput']},
                    '@Curve': {'id': curve, 'points': deepcopy(node['@Curve']['points'])}}
                task.objects[curve] = {'id': curve, 'name': '', 'type': 'Curve', 'classId': 917520,
                    'path': '\\opaque-curve-' + curve, 'owner': {'id': identity}, 'notes': ''}
            task.objects[FIRST]['@RTPC'] = [{'id': CHILD}, {'id': RTPC_B}]
            if fault == 'wrong-pair':
                task.objects[CHILD]['@PropertyName'] = 'Unrequested'
            elif fault == 'wrong-value':
                task.objects[CHILD]['@Curve']['points'][0]['y'] = -47
            elif fault == 'wrong-owner':
                task.objects[CHILD]['owner'] = {'id': SECOND}
            elif fault == 'missing-member':
                task.objects[FIRST]['@RTPC'] = [{'id': RTPC_B}]
            elif fault == 'partial-curve':
                del task.objects[CHILD]['@Curve']['points']
            return {'objects': [{'id': FIRST, 'name': 'Sender', '@RTPC': [
                {'id': CHILD, 'name': ''}, {'id': RTPC_B, 'name': ''}]}]}
        result = original(uri, args, options)
        if uri.endswith('object.get'):
            return {'return': [{key: deepcopy(row.get(key, row.get('@' + key))) for key in options['return']
                if key in row or '@' + key in row} for row in result['return']]}
        return result
    task.call = call
    return task, writes


def declare_rtpc(task, owner, control, token, declaration_id):
    field = select_field(task, owner=owner, token=token)
    code, declared = task.step('draft-declare-rtpc', '--declaration-id', declaration_id,
        '--object-handle', owner, '--field-handle', field, '--control-input-handle', control,
        '--mode', 'add-only', '--point', '0', '-48', 'Linear', '--point', '100', '0', 'Linear')
    assert code == 0, json.dumps(declared)
    return declared


@pytest.mark.parametrize('version,fault', [(version, None) for version in ['2022.1', '2023.1', '2024.1', '2025.1']] +
    [('2025.1', fault) for fault in ['wrong-pair', 'wrong-value', 'wrong-owner', 'missing-member', 'partial-curve']])
def test_graph_adds_two_unnamed_rtpc_pairs_in_one_public_transaction(tmp_path, version, fault):
    task, writes = rtpc_task(tmp_path, version, fault=fault)
    owner, control = task.bind(FIRST), task.bind(ROOT)
    first = declare_rtpc(task, owner, control, 'Volume', 'volume')
    second = declare_rtpc(task, owner, control, 'Pitch', 'pitch')
    assert first['draft']['declared_object']['result_handle'] != second['draft']['declared_object']['result_handle']
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    if code:
        (tmp_path / 'rtpc-verification.json').write_text(json.dumps(verified, indent=2))
    assert code == (0 if fault is None else 2), verified
    assert (verified.get('verified') is True) == (fault is None), verified
    assert len(writes) == 1
    if fault is None:
        assert task.objects[CHILD]['@PropertyName'] == 'Volume' and task.objects[RTPC_B]['@PropertyName'] == 'Pitch'


def seed_pair(task, identity=CHILD, property_name='Volume', curve=CURVE_A):
    row = {'id': identity, 'name': '', 'type': 'RTPC', 'classId': 1441808,
        'path': '\\opaque-' + identity, 'owner': {'id': FIRST}, 'notes': 'Keep RTPC',
        '@PropertyName': property_name, '@ControlInput': {'id': ROOT},
        '@Curve': {'id': curve, 'points': [{'x': 0, 'y': -12, 'shape': 'Linear'}, {'x': 100, 'y': 0, 'shape': 'Linear'}]}}
    task.objects[identity] = row
    task.objects[curve] = {'id': curve, 'name': '', 'type': 'Curve', 'classId': 917520,
        'path': '\\opaque-curve-' + curve, 'owner': {'id': identity}, 'notes': ''}
    task.objects[FIRST]['@RTPC'].append({'id': identity})
    return deepcopy(row)


def test_graph_updates_unique_pair_by_actual_guid_and_preserves_other_curve(tmp_path):
    task, _ = rtpc_task(tmp_path)
    seed_pair(task)
    unrequested = seed_pair(task, identity=RTPC_B, property_name='Pitch', curve=CURVE_B)
    owner, control = task.bind(FIRST), task.bind(ROOT)
    field = select_field(task, owner=owner, token='Volume')
    code, declared = task.step('draft-declare-rtpc', '--declaration-id', 'volume',
        '--object-handle', owner, '--field-handle', field, '--control-input-handle', control,
        '--point', '0', '-48', 'Linear', '--point', '100', '0', 'Linear')
    assert code == 0, declared
    original, writes = task.call, []
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            writes.append(deepcopy(args))
            assert args['objects'] == [{'object': CHILD, '@Curve': {'type': 'Curve',
                'points': [{'x': 0, 'y': -48, 'shape': 'Linear'}, {'x': 100, 'y': 0, 'shape': 'Linear'}]}}]
            task.objects[CHILD]['@Curve']['points'] = deepcopy(args['objects'][0]['@Curve']['points'])
            return {'objects': []}  # Native field-only associations may be sparse.
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified.get('verified') is True, verified
    assert len(writes) == 1 and task.objects[RTPC_B] == unrequested


def test_graph_places_unnamed_rtpc_below_new_owner_with_class_field(tmp_path):
    task, _ = rtpc_task(tmp_path)
    parent, control = task.bind(SECOND), task.bind(ROOT)
    code, found = task.step('draft-discover-types', '--role', 'object', '--meaning', 'Sound')
    assert code == 0, found
    kind = found['type_candidates'][0]['handle']
    code, declared = task.step('draft-declare-new', '--declaration-id', 'new-sound',
        '--parent-handle', parent, '--name', 'New sound', '--kind', kind)
    assert code == 0, declared
    owner = declared['draft']['declared_object']['result_handle']
    field = select_field(task, kind=kind, token='Volume')
    code, declared = task.step('draft-declare-rtpc', '--declaration-id', 'volume',
        '--object-handle', owner, '--field-handle', field, '--control-input-handle', control,
        '--point', '0', '-48', 'Linear', '--point', '100', '0', 'Linear')
    assert code == 0, declared
    original, writes = task.call, []
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            writes.append(deepcopy(args))
            assert args['objects'][0]['object'] == SECOND
            sound = args['objects'][0]['children'][0]
            assert sound['name'] == 'New sound' and sound['type'] == 'Sound'
            rtpc = sound['@RTPC'][0]
            assert rtpc['name'] == '' and rtpc['@PropertyName'] == 'Volume'
            task.objects[CHILD] = {'id': CHILD, 'name': 'New sound', 'type': 'Sound', 'classId': 65552,
                'path': task.objects[SECOND]['path'] + '\\New sound', 'parent': {'id': SECOND},
                'notes': '', '@RTPC': [{'id': RTPC_B}]}
            seed_pair(task, identity=RTPC_B, curve=CURVE_B)
            task.objects[RTPC_B]['owner'] = {'id': CHILD}
            task.objects[RTPC_B]['@Curve']['points'] = deepcopy(rtpc['@Curve']['points'])
            return {'objects': [{'id': SECOND, 'name': 'Default Work Unit', 'children': [
                {'id': CHILD, 'name': 'New sound', '@RTPC': [{'id': RTPC_B, 'name': ''}]}]}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified.get('verified') is True, verified
    assert len(writes) == 1


@pytest.mark.parametrize('fault', ['duplicate-pair', 'wrong-class', 'wrong-owner', 'add-collision'])
def test_graph_pair_binding_rejects_ambiguous_or_invalid_actual_members(tmp_path, fault):
    task, writes = rtpc_task(tmp_path)
    seed_pair(task)
    if fault == 'duplicate-pair':
        seed_pair(task, identity=RTPC_B, property_name='Volume', curve=CURVE_B)
    elif fault == 'wrong-class':
        task.objects[CHILD]['classId'] = 917520
    elif fault == 'wrong-owner':
        task.objects[CHILD]['owner'] = {'id': SECOND}
    owner, control = task.bind(FIRST), task.bind(ROOT)
    field = select_field(task, owner=owner, token='Volume')
    args = ['--mode', 'add-only'] if fault == 'add-collision' else []
    code, declared = task.step('draft-declare-rtpc', '--declaration-id', 'volume',
        '--object-handle', owner, '--field-handle', field, '--control-input-handle', control,
        '--point', '0', '-48', 'Linear', '--point', '100', '0', 'Linear', *args)
    assert code == 0, declared
    code, checked = task.step('draft-check')
    assert code == 2, checked
    assert not writes


@pytest.mark.parametrize('fault', ['list-drift', 'class-drift', 'owner-drift', 'metadata-drift', 'partial-curve'])
def test_graph_revalidates_complete_pair_state_before_single_write(tmp_path, fault):
    task, writes = rtpc_task(tmp_path)
    seed_pair(task, identity=RTPC_B, property_name='Unrequested', curve=CURVE_B)
    owner, control = task.bind(FIRST), task.bind(ROOT)
    declare_rtpc(task, owner, control, 'Volume', 'volume')
    declare_rtpc(task, owner, control, 'Pitch', 'pitch')
    tx, shown = task.preview()
    if fault == 'list-drift':
        task.objects[FIRST]['@RTPC'] = []
    elif fault == 'class-drift':
        task.objects[RTPC_B]['classId'] = 917520
    elif fault == 'owner-drift':
        task.objects[RTPC_B]['owner'] = {'id': SECOND}
    elif fault == 'metadata-drift':
        task.metadata['Volume']['supports']['rtpc'] = 'None'
    else:
        del task.objects[RTPC_B]['@Curve']['points']
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, result = task.run('execute', tx)
    assert code == 2 and result.get('verified') is not True, result
    assert not writes


def test_graph_does_not_certify_unrequested_curve_corruption(tmp_path):
    task, _ = rtpc_task(tmp_path)
    seed_pair(task, identity=RTPC_B, property_name='Unrequested', curve=CURVE_B)
    owner, control = task.bind(FIRST), task.bind(ROOT)
    declare_rtpc(task, owner, control, 'Volume', 'volume')
    original, writes = task.call, []
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            writes.append(deepcopy(args))
            node = args['objects'][0]['@RTPC'][0]
            seed_pair(task)
            task.objects[CHILD]['@Curve']['points'] = deepcopy(node['@Curve']['points'])
            task.objects[RTPC_B]['@Curve']['points'][0]['y'] = -99
            return {'objects': [{'id': FIRST, 'name': 'Sender', '@RTPC': [{'id': CHILD, 'name': ''}]}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    code, result = task.finish(tx, shown)
    assert code == 2 and result.get('verified') is not True, result
    assert len(writes) == 1


def test_replace_all_removes_old_pairs_and_does_not_update_them_by_guid(tmp_path):
    task, _ = rtpc_task(tmp_path)
    seed_pair(task)
    owner, control = task.bind(FIRST), task.bind(ROOT)
    code, configured = task.step('draft-business-configure', '--list-behavior', 'replace-all')
    assert code == 0, configured
    field = select_field(task, owner=owner, token='Volume')
    code, declared = task.step('draft-declare-rtpc', '--declaration-id', 'new-volume',
        '--object-handle', owner, '--field-handle', field, '--control-input-handle', control,
        '--point', '0', '-48', 'Linear', '--point', '100', '0', 'Linear')
    assert code == 0, declared
    original, writes = task.call, []
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            writes.append(deepcopy(args))
            assert args['listMode'] == 'replaceAll' and len(args['objects']) == 1
            node = args['objects'][0]['@RTPC'][0]
            assert node['type'] == 'RTPC' and node['name'] == ''
            del task.objects[CHILD]
            del task.objects[CURVE_A]
            task.objects[FIRST]['@RTPC'] = []
            seed_pair(task, identity=RTPC_B, curve=CURVE_B)
            task.objects[RTPC_B]['@Curve']['points'] = deepcopy(node['@Curve']['points'])
            return {'objects': [{'id': FIRST, 'name': 'Sender', '@RTPC': [{'id': RTPC_B, 'name': ''}]}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified.get('verified') is True, verified
    assert len(writes) == 1 and CHILD not in task.objects


def test_planned_owner_merge_updates_existing_unnamed_pair_in_same_batch(tmp_path):
    task, _ = rtpc_task(tmp_path)
    seed_pair(task)
    parent, control = task.bind(SECOND), task.bind(ROOT)
    code, found = task.step('draft-discover-types', '--role', 'object', '--meaning', 'Sound')
    assert code == 0, found
    kind = found['type_candidates'][0]['handle']
    code, configured = task.step('draft-business-configure', '--name-conflict', 'merge')
    assert code == 0, configured
    code, declared = task.step('draft-declare-new', '--declaration-id', 'sender', '--parent-handle', parent,
        '--name', 'Sender', '--kind', kind)
    assert code == 0, declared
    owner = declared['draft']['declared_object']['result_handle']
    field = select_field(task, kind=kind, token='Volume')
    code, declared = task.step('draft-declare-rtpc', '--declaration-id', 'volume',
        '--object-handle', owner, '--field-handle', field, '--control-input-handle', control,
        '--point', '0', '-48', 'Linear', '--point', '100', '0', 'Linear')
    assert code == 0, declared
    original, writes = task.call, []
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            writes.append(deepcopy(args))
            update = next(row for row in args['objects'] if row['object'] == CHILD)
            assert update == {'object': CHILD, '@Curve': {'type': 'Curve',
                'points': [{'x': 0, 'y': -48, 'shape': 'Linear'}, {'x': 100, 'y': 0, 'shape': 'Linear'}]}}
            owner_row = next(row for row in args['objects'] if row['object'] == SECOND)
            assert owner_row['children'] == [{'type': 'Sound', 'name': 'Sender'}]
            task.objects[CHILD]['@Curve']['points'] = deepcopy(update['@Curve']['points'])
            return {'objects': [{'id': SECOND, 'name': 'Default Work Unit', 'children': [{'id': FIRST, 'name': 'Sender'}]}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    if code:
        (tmp_path / 'merge-rtpc-verification.json').write_text(json.dumps(verified, indent=2))
    assert code == 0 and verified.get('verified') is True, verified
    assert len(writes) == 1


def test_graph_schema_and_copied_continuation_disclose_rtpc_arguments(tmp_path):
    task, _ = rtpc_task(tmp_path)
    code, schema = task.run('operation-schema', 'object.set')
    assert code == 0, schema
    # Public projection may nest the versioned business contract; inspect its
    # actual JSON rather than importing a private contract constructor.
    encoded = json.dumps(schema)
    assert 'rtpc_declaration' in encoded and 'draft-declare-rtpc' in encoded
    assert 'add-only' in encoded and 'add-or-update' in encoded
    assert '2022.1' in encoded and '2025.1' in encoded
    code, bound = task.step('draft-bind-object', '--object-id', FIRST)
    assert code == 0, bound
    action = bound['draft']['next_action_binding']['declare_rtpc']
    assert '--declaration-id' in action['append'] and '--control-input-handle' in action['append']
    assert action['semantics']['existing_pair_update'] == 'exact_actual_RTPC_GUID_row_in_same_object_set;_no_name_merge'


def test_rtpc_descriptor_does_not_relax_ordinary_object_names(tmp_path):
    task, writes = rtpc_task(tmp_path)
    parent = task.bind(SECOND)
    code, result = task.step('draft-declare-new', '--declaration-id', 'ordinary', '--parent-handle', parent,
        '--name', '', '--kind', 'sound-sfx')
    assert code == 2, result
    assert not writes


@pytest.mark.parametrize('fault', [None, 'unrequested-path', 'unrequested-curve'])
def test_requested_owner_rename_preserves_unrequested_rtpc_suffix_and_curve(tmp_path, fault):
    task, _ = rtpc_task(tmp_path)
    seed_pair(task, identity=RTPC_B, property_name='Pitch', curve=CURVE_B)
    # Literal retained native RTPC readbacks use an owner path plus an RTPC
    # display component. Only the admitted owner prefix is changed here.
    task.objects[RTPC_B]['path'] = task.objects[FIRST]['path'] + r'\[RTPC: Voice Pitch, Intensity]'
    owner, control = task.bind(FIRST), task.bind(ROOT)
    code, declared = task.step('draft-declare-existing', '--declaration-id', 'owner', '--object-handle', owner,
        '--field', 'new_name', 'Renamed')
    assert code == 0, declared
    declare_rtpc(task, owner, control, 'Volume', 'volume')
    original, writes = task.call, []
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            writes.append(deepcopy(args))
            row = args['objects'][0]
            assert row['name'] == 'Renamed'
            old_path = task.objects[FIRST]['path']
            task.objects[FIRST]['name'] = 'Renamed'
            task.objects[FIRST]['path'] = old_path.rsplit('\\', 1)[0] + '\\Renamed'
            task.objects[RTPC_B]['path'] = task.objects[FIRST]['path'] + r'\[RTPC: Voice Pitch, Intensity]'
            if fault == 'unrequested-path':
                task.objects[RTPC_B]['path'] += '-wrong'
            elif fault == 'unrequested-curve':
                task.objects[RTPC_B]['@Curve']['points'][0]['y'] = -99
            seed_pair(task)
            task.objects[CHILD]['@Curve']['points'] = deepcopy(row['@RTPC'][0]['@Curve']['points'])
            return {'objects': [{'id': FIRST, 'name': 'Renamed', '@RTPC': [{'id': CHILD, 'name': ''}]}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == (0 if fault is None else 2), verified
    assert (verified.get('verified') is True) == (fault is None), verified
    assert len(writes) == 1


def seed_many_pairs(task, count):
    from uuid import UUID
    for index in range(count):
        seed_pair(task, identity='{' + str(UUID(int=1000 + index)).upper() + '}',
            property_name='Unrequested' + str(index), curve='{' + str(UUID(int=2000 + index)).upper() + '}')


def test_graph_aggregate_new_pairs_cannot_cross_complete_owner_list_cap(tmp_path):
    task, writes = rtpc_task(tmp_path)
    # Runtime's retained complete-list cap is128; each of the two new pairs
    # alone fits below it, while their combined requested effect does not.
    seed_many_pairs(task, 127)
    owner, control = task.bind(FIRST), task.bind(ROOT)
    declare_rtpc(task, owner, control, 'Volume', 'volume')
    declare_rtpc(task, owner, control, 'Pitch', 'pitch')
    code, checked = task.step('draft-check')
    assert code == 2, checked
    assert 'RTPC_LIST_LIMIT_EXCEEDED' in json.dumps(checked), checked
    assert not writes


def test_two_pairs_share_one_complete_owner_snapshot_in_each_fresh_phase(tmp_path):
    task, writes = rtpc_task(tmp_path)
    seed_many_pairs(task, 12)
    owner, control = task.bind(FIRST), task.bind(ROOT)
    declare_rtpc(task, owner, control, 'Volume', 'volume')
    declare_rtpc(task, owner, control, 'Pitch', 'pitch')
    original = task.call
    def call(uri, args=None, options=None):
        old_members = deepcopy(task.objects[FIRST]['@RTPC'])
        result = original(uri, args, options)
        if uri.endswith('object.set'):
            task.objects[FIRST]['@RTPC'] = old_members + task.objects[FIRST]['@RTPC']
        return result
    task.call = call
    def phase_snapshot_reads(start):
        # This is the public RPC projection of the complete Curve/pair snapshot,
        # distinct from ordinary owner/List identity proof and per-node effect reads.
        return [args for uri, args, options in task.calls[start:] if uri.endswith('object.get')
            and options.get('return') == ['id', 'name', 'type', 'path', 'notes', '@PropertyName', '@ControlInput', '@Curve']]
    def owner_member_class_reads(start):
        return [args for uri, args, options in task.calls[start:] if uri.endswith('object.get')
            and '@Curve' in options.get('return', []) and 'classId' in options.get('return', [])
            and 'owner' in options.get('return', [])]
    start = len(task.calls)
    code, checked = task.step('draft-check')
    assert code == 0, checked
    assert len(phase_snapshot_reads(start)) == 1, phase_snapshot_reads(start)
    assert len(owner_member_class_reads(start)) == 12
    start = len(task.calls)
    code, preview = task.step('preview-from-draft')
    assert code == 0, preview
    assert len(phase_snapshot_reads(start)) == 1, phase_snapshot_reads(start)
    assert len(owner_member_class_reads(start)) == 12
    tx = preview['transaction_id']
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    start = len(task.calls)
    code, executed = task.run('execute', tx)
    assert code == 0, executed
    assert len(phase_snapshot_reads(start)) == 1, phase_snapshot_reads(start)
    assert len(owner_member_class_reads(start)) == 12
    start = len(task.calls)
    code, verified = task.run('verify', tx)
    assert code == 0 and verified.get('verified') is True, verified
    assert len(phase_snapshot_reads(start)) == 1, phase_snapshot_reads(start)
    assert len(owner_member_class_reads(start)) == 14
    assert len(writes) == 1


def test_graph_discloses_all_accepted_curve_shapes_in_schema_and_continuation(tmp_path):
    expected = {'Constant', 'Linear', 'Log3', 'Log2', 'Log1', 'InvertedSCurve', 'SCurve', 'Exp1', 'Exp2', 'Exp3'}
    task, _ = rtpc_task(tmp_path / 'schema')
    code, schema = task.run('operation-schema', 'object.set')
    assert code == 0, schema
    def find_contract(value):
        if isinstance(value, dict):
            if 'rtpc_declaration' in value:
                return value['rtpc_declaration']
            for nested in value.values():
                found = find_contract(nested)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for nested in value:
                found = find_contract(nested)
                if found is not None:
                    return found
    declaration = find_contract(schema)
    assert set(declaration['points']['point_shapes']) == expected
    assert declaration['points']['terminal_shape'] == 'gateway_normalized_to_Linear'
    code, bound = task.step('draft-bind-object', '--object-id', FIRST)
    assert code == 0, bound
    points = bound['draft']['next_action_binding']['declare_rtpc']['semantics']['points']
    assert set(points['point_shapes']) == expected
    # Every disclosed non-terminal shape must pass the real public parser,
    # declaration materializer and normalizer, rather than just a schema snapshot.
    for shape in sorted(expected):
        candidate, _ = rtpc_task(tmp_path / shape)
        owner, control = candidate.bind(FIRST), candidate.bind(ROOT)
        field = select_field(candidate, owner=owner, token='Volume')
        code, declared = candidate.step('draft-declare-rtpc', '--declaration-id', 'curve',
            '--object-handle', owner, '--field-handle', field, '--control-input-handle', control,
            '--point', '0', '-48', shape, '--point', '100', '0', 'Exp3')
        assert code == 0, (shape, declared)
        code, checked = candidate.step('draft-check')
        assert code == 0, (shape, checked)


@pytest.mark.parametrize('mode', ['update-plus-add', 'replace-all'])
def test_owner_capacity_counts_only_actual_new_pairs_for_the_selected_mode(tmp_path, mode):
    task, writes = rtpc_task(tmp_path)
    seed_many_pairs(task, 127)
    owner, control = task.bind(FIRST), task.bind(ROOT)
    if mode == 'update-plus-add':
        first = task.objects[FIRST]['@RTPC'][0]['id']
        task.objects[first]['@PropertyName'] = 'Volume'
    else:
        code, configured = task.step('draft-business-configure', '--list-behavior', 'replace-all')
        assert code == 0, configured
    for token in ('Volume', 'Pitch'):
        field = select_field(task, owner=owner, token=token)
        code, declared = task.step('draft-declare-rtpc', '--declaration-id', token.lower(),
            '--object-handle', owner, '--field-handle', field, '--control-input-handle', control,
            '--point', '0', '-48', 'Linear', '--point', '100', '0', 'Linear')
        assert code == 0, declared
    code, checked = task.step('draft-check')
    assert code == 0, checked
    assert not writes  # Construction/preflight proof, not an effect acceptance.


def test_graph_rtpc_accepts_live_proven_omitted_empty_owner_list(tmp_path):
    task, writes = rtpc_task(tmp_path)
    original = task.call
    proof_calls = []
    def call(uri, args=None, options=None):
        if uri.endswith('object.get') and args.get('waql') == f'from object "{FIRST}" select @RTPC take 1':
            proof_calls.append((deepcopy(args), deepcopy(options)))
            return {'return': []}
        result = original(uri, args, options)
        if (uri.endswith('object.get') and options.get('return') == ['id', '@RTPC']
                and args == {'from': {'id': [FIRST]}} and not task.objects[FIRST]['@RTPC']):
            return {'return': [{'id': FIRST}]}
        return result
    task.call = call
    owner, control = task.bind(FIRST), task.bind(ROOT)
    declare_rtpc(task, owner, control, 'Volume', 'volume')
    declare_rtpc(task, owner, control, 'Pitch', 'pitch')
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, json.dumps(verified)
    assert len(writes) == 1 and proof_calls
    assert all(options == {'return': ['id']} for _args, options in proof_calls)
