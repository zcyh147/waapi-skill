"""New owned RTPC controls through the public Business Draft transaction seam.

Fixtures model the matching SDK's custom ModulatorTime example; fake execution
is program evidence only and never a native-Wwise receipt.
"""
from copy import deepcopy
import json
import pytest

from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, FIRST, SECOND, CHILD

RTPC = '{55555555-5555-5555-5555-555555555555}'
CURVE = '{66666666-6666-6666-6666-666666666666}'
CONTROL = '{77777777-7777-7777-7777-77777777777A}'


class OwnedControlTask(OwnedGraphTask):
    def __init__(self, path, version='2022.1', operation='object.setRTPC', input_type='ModulatorTime'):
        super().__init__(path, version, operation)
        self.input_type = input_type
        self.input_properties = {
            'ModulatorTime': {'TimeModDuration': 5, 'EnvelopeStopPlayback': False},
            'ModulatorLfo': {'LfoFrequency': 4},
            'ModulatorEnvelope': {'EnvelopeAttackTime': 0.2},
        }[input_type]
        self.input_classes = {'ModulatorTime': 5111824, 'ModulatorLfo': 4194320, 'ModulatorEnvelope': 4259856}
        self.operation = operation
        self.types = [{'name': name, 'classId': class_id, 'type': 'WObject'} for name, class_id in (
            ('Sound', 65552), ('RTPC', 1441808), ('Curve', 917520),
            ('ModulatorTime', 5111824), ('ModulatorLfo', 4194320), ('ModulatorEnvelope', 4259856))]
        self.objects = {
            FIRST: {'id': FIRST, 'name': 'Sound', 'type': 'Sound', 'classId': 65552,
                'path': r'\Actor-Mixer Hierarchy\Default Work Unit\Sound',
                'parent': {'id': SECOND}, 'notes': 'Keep sound', '@RTPC': []},
        }
        self.metadata = {
            'Volume': {'name': 'Volume', 'type': 'Real64', 'default': 0,
                'supports': {'rtpc': 'Additive'}, 'restriction': {'type': 'range', 'min': -200, 'max': 12}},
            'PropertyName': {'name': 'PropertyName', 'type': 'string', 'default': ''},
            'ControlInput': {'name': 'ControlInput', 'type': '', 'restriction': {'type': 'reference',
                'restrictions': [{'type': ['ModulatorTime', 'ModulatorLfo', 'ModulatorEnvelope', 'GameParameter', 'MidiParameter']}]}},
            'Curve': {'name': 'Curve', 'type': '', 'restriction': {'type': 'reference',
                'restrictions': [{'type': ['Curve']}, 'notNull']}},
            'TimeModDuration': {'name': 'TimeModDuration', 'type': 'Real64', 'default': 1,
                'restriction': {'type': 'range', 'min': 0.1, 'max': 100}},
            'LfoFrequency': {'name': 'LfoFrequency', 'type': 'Real64', 'default': 1,
                'restriction': {'type': 'range', 'min': 0, 'max': 20000}},
            'EnvelopeAttackTime': {'name': 'EnvelopeAttackTime', 'type': 'Real64', 'default': 0.2,
                'restriction': {'type': 'range', 'min': 0, 'max': 10000}},
            'EnvelopeStopPlayback': {'name': 'EnvelopeStopPlayback', 'type': 'bool', 'default': True},
        }
        self.writes = []
        self.fault = None

    def call(self, uri, args=None, options=None):
        if uri.endswith('isPropertyEnabled'):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': True}
        if uri.endswith('object.set'):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            self.writes.append(deepcopy(args))
            assert len(args['objects']) == 1
            item = args['objects'][0]
            planned = 'children' in item
            owner_id = CHILD if planned else FIRST
            if planned:
                assert item['object'] == SECOND and item['children'][0]['name'] == 'PlannedSound'
                self.objects[CHILD] = {'id': CHILD, 'name': 'PlannedSound', 'type': 'Sound', 'classId': 65552,
                    'path': self.objects[SECOND]['path'] + r'\PlannedSound', 'parent': {'id': SECOND}, 'notes': '', '@RTPC': []}
            node = (item['children'][0] if planned else item)['@RTPC'][0]
            assert node['@ControlInput'] == {'type': self.input_type, 'name': 'TimeMod',
                'notes': 'New time control', **{'@' + name: value for name, value in self.input_properties.items()}}
            self.objects[CONTROL] = {'id': CONTROL, 'name': 'TimeMod', 'type': self.input_type,
                'classId': self.input_classes[self.input_type], 'owner': {'id': RTPC}, 'path': r'\opaque-control',
                'notes': 'New time control', **{'@' + name: value for name, value in self.input_properties.items()}}
            self.objects[CURVE] = {'id': CURVE, 'name': '', 'type': 'Curve', 'classId': 917520,
                'owner': {'id': RTPC}, 'path': r'\opaque-curve', 'notes': ''}
            self.objects[RTPC] = {'id': RTPC, 'name': '', 'type': 'RTPC', 'classId': 1441808,
                'owner': {'id': owner_id}, 'path': r'\opaque-rtpc', 'notes': '',
                '@PropertyName': 'Volume', '@ControlInput': {'id': CONTROL},
                '@Curve': {'id': CURVE, 'points': [{'x': 0, 'y': -20, 'shape': 'Linear'},
                    {'x': 1000, 'y': 0, 'shape': 'Linear'}]}}
            self.objects[owner_id]['@RTPC'] = [*self.objects[owner_id]['@RTPC'], {'id': RTPC}]
            if self.fault == 'wrong-input-owner':
                self.objects[CONTROL]['owner'] = {'id': FIRST}
            elif self.fault == 'wrong-input-class':
                self.objects[CONTROL]['classId'] = 4194320
            elif self.fault == 'wrong-rtpc-class':
                self.objects[RTPC]['classId'] = 917520
            result = {'id': owner_id, 'name': 'PlannedSound' if planned else 'Sound', '@RTPC': [
                {'id': RTPC, 'name': '', '@ControlInput': {'id': CONTROL, 'name': 'TimeMod'}}]}
            return {'objects': [{'id': SECOND, 'name': 'Default Work Unit', 'children': [result]}] if planned else [result]}
        return super().call(uri, args, options)

    def class_field(self, kind, meaning):
        code, found = self.step('draft-discover-fields', '--type-handle', kind, '--meaning', meaning)
        assert code == 0, found
        return found['meaning_results'][0]['candidates'][0]['handle']


def declare_time(task, owner=None, property_field=None):
    owner = task.bind(FIRST) if owner is None else owner
    property_field = task.discover(owner, 'Volume') if property_field is None else property_field
    code, types = task.step('draft-discover-types', '--role', 'object', '--meaning', task.input_type)
    assert code == 0, types
    kind = types['type_candidates'][0]['handle']
    values = []
    for name, value in task.input_properties.items():
        values.extend(('--new-control-input-field-value', task.class_field(kind, name), json.dumps(value)))
    code, declared = task.step('draft-declare-rtpc', *(['--declaration-id', 'curve'] if task.operation == 'object.set' else []), '--object-handle', owner,
        '--field-handle', property_field, '--new-control-input-kind', kind,
        '--new-control-input-name', 'TimeMod', '--new-control-input-notes', 'New time control',
        *values,
        '--point', '0', '-20', 'Linear', '--point', '1000', '0', 'Linear')
    assert code == 0, declared
    return task


def test_public_time_input_creates_owned_reference_and_verifies_once(tmp_path):
    task = declare_time(OwnedControlTask(tmp_path))
    tx, shown = task.preview()
    assert task.writes == []
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, json.dumps(verified)
    assert len(task.writes) == 1
    code, repeated = task.run('execute', tx)
    assert code == 2 and len(task.writes) == 1, repeated


@pytest.mark.parametrize('fault', ['wrong-input-owner', 'wrong-input-class', 'wrong-rtpc-class'])
def test_owned_time_input_rejects_independent_identity_or_ownership_mismatch(tmp_path, fault):
    task = declare_time(OwnedControlTask(tmp_path))
    task.fault = fault
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 2 and verified.get('verified') is False, verified
    assert len(task.writes) == 1


def test_new_owned_input_cannot_reuse_and_reparent_a_prior_rtpc_control(tmp_path):
    task = OwnedControlTask(tmp_path)
    old_curve = '{88888888-8888-8888-8888-888888888888}'
    task.objects[CONTROL] = {'id': CONTROL, 'name': 'TimeMod', 'type': 'ModulatorTime', 'classId': 5111824,
        'path': r'\old-control', 'owner': {'id': CHILD}, 'notes': 'Old input'}
    task.objects[CHILD] = {'id': CHILD, 'name': '', 'type': 'RTPC', 'classId': 1441808,
        'path': r'\old-rtpc', 'owner': {'id': FIRST}, 'notes': 'Keep old',
        '@PropertyName': 'Pitch', '@ControlInput': {'id': CONTROL.lower()},
        '@Curve': {'id': old_curve, 'points': [{'x': 0, 'y': 0, 'shape': 'Linear'}]}}
    task.objects[FIRST]['@RTPC'] = [{'id': CHILD}]
    declare_time(task)
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert 'new ControlInput identity is absent from the complete owning baseline' in json.dumps(verified), json.dumps(verified)
    assert code == 2 and verified.get('verified') is False, verified
    assert len(task.writes) == 1


@pytest.mark.parametrize('version', ['2022.1', '2023.1', '2024.1', '2025.1'])
@pytest.mark.parametrize('input_type', ['ModulatorLfo', 'ModulatorEnvelope', 'ModulatorTime'])
@pytest.mark.parametrize('operation', ['object.setRTPC', 'object.set'])
def test_each_modern_owned_modulator_uses_scoped_fields_and_exact_ownership(tmp_path, version, input_type, operation):
    task = declare_time(OwnedControlTask(tmp_path, version, input_type=input_type, operation=operation))
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert len(task.writes) == 1


@pytest.mark.parametrize('drift', ['class', 'property', 'reference'])
def test_owned_control_class_or_metadata_drift_blocks_before_write(tmp_path, drift):
    task = declare_time(OwnedControlTask(tmp_path))
    tx, shown = task.preview()
    if drift == 'class':
        next(row for row in task.types if row['name'] == 'ModulatorTime')['classId'] = 4194320
    elif drift == 'property':
        task.metadata['TimeModDuration']['restriction']['max'] = 4
    else:
        task.metadata['ControlInput']['restriction']['restrictions'] = [{'type': ['GameParameter']}]
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, rejected = task.run('execute', tx)
    assert code == 2 and task.writes == [], rejected


def test_graph_time_control_input_binds_both_owned_occurrences(tmp_path):
    task = declare_time(OwnedControlTask(tmp_path, operation='object.set'))
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert len(task.writes) == 1


def test_owned_time_input_below_a_planned_owner_has_no_invented_rtpc_path(tmp_path):
    task = OwnedControlTask(tmp_path, operation='object.set')
    task.types.append({'name': 'WorkUnit', 'classId': 1638416, 'type': 'WObject'})
    task.objects[SECOND] = {'id': SECOND, 'name': 'Default Work Unit', 'type': 'WorkUnit', 'classId': 1638416,
        'path': r'\Actor-Mixer Hierarchy\Default Work Unit', 'parent': None, 'notes': 'Keep work unit'}
    parent = task.bind(SECOND)
    code, types = task.step('draft-discover-types', '--role', 'object', '--meaning', 'Sound')
    assert code == 0, types
    property_field = task.class_field(types['type_candidates'][0]['handle'], 'Volume')
    code, declared = task.step('draft-declare-new', '--declaration-id', 'sound', '--parent-handle', parent,
        '--kind', 'sound-sfx', '--name', 'PlannedSound')
    assert code == 0, declared
    planned = declared['draft']['declared_object']['result_handle']
    declare_time(task, planned, property_field)
    tx, shown = task.preview()
    facts = shown['artifact']['prepared_operation']['pre_state']['planned_reference_context']['facts']
    assert len([fact for fact in facts.values() if fact['path'] is None]) == 2
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, json.dumps(verified)

OLD_CONTROL = '{99999999-9999-9999-9999-999999999999}'


class ReplacementTask(OwnedControlTask):
    def __init__(self, path, version='2022.1', input_type='ModulatorTime'):
        super().__init__(path, version, operation='object.set', input_type=input_type)
        self.types.append({'name': 'GameParameter', 'classId': 1507344, 'type': 'WObject'})
        self.objects[OLD_CONTROL] = {'id': OLD_CONTROL, 'name': 'Intensity', 'type': 'GameParameter',
            'classId': 1507344, 'path': r'\Game Parameters\Default Work Unit\Intensity',
            'parent': {'id': SECOND}, 'owner': None, 'notes': 'Keep shared', '@Volume': 3}
        self.objects[RTPC] = {'id': RTPC, 'name': '', 'type': 'RTPC', 'classId': 1441808,
            'owner': {'id': FIRST}, 'path': r'\opaque-rtpc', 'notes': 'Keep RTPC',
            '@PropertyName': 'Volume', '@ControlInput': {'id': OLD_CONTROL},
            '@Curve': {'id': CURVE, 'points': [{'x': 0, 'y': -20, 'shape': 'Linear'},
                {'x': 1000, 'y': 0, 'shape': 'Linear'}]}}
        self.objects[FIRST]['@RTPC'] = [{'id': RTPC}]

    def call(self, uri, args=None, options=None):
        if uri.endswith('object.get') and args.get('waql', '').startswith('from object "' + OLD_CONTROL):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': [{'id': OLD_CONTROL}] + ([{'id': RTPC}] if self.objects[OLD_CONTROL].get('owner') else [])}
        if uri.endswith('object.set'):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            self.writes.append(deepcopy(args))
            assert len(args['objects']) == 1
            assert set(args['objects'][0]) == {'object', '@ControlInput'}
            assert args['objects'][0]['object'] == RTPC
            expected = {'type': self.input_type, 'name': 'TimeMod', 'notes': 'New time control',
                **{'@' + key: value for key, value in self.input_properties.items()}}
            assert args['objects'][0]['@ControlInput'] == expected
            self.objects[CONTROL] = {'id': CONTROL, 'name': 'TimeMod', 'type': self.input_type,
                'classId': self.input_classes[self.input_type], 'owner': {'id': RTPC}, 'path': r'\opaque-new-input',
                'notes': 'New time control', **{'@' + key: value for key, value in self.input_properties.items()}}
            self.objects[RTPC]['@ControlInput'] = {'id': CONTROL}
            if self.fault == 'shared-input-changed':
                self.objects[OLD_CONTROL]['@Volume'] = 9
            elif self.fault == 'curve-changed':
                self.objects[RTPC]['@Curve']['points'][0]['y'] = -19
            elif self.fault == 'rtpc-notes-changed':
                self.objects[RTPC]['notes'] = 'Unexpected change'
            elif self.fault == 'owner-membership-changed':
                self.objects[FIRST]['@RTPC'] = []
            elif self.fault == 'wrong-input-owner':
                self.objects[CONTROL]['owner'] = {'id': FIRST}
            elif self.fault == 'wrong-input-class':
                self.objects[CONTROL]['classId'] = 4194320
            return {'objects': []}  # Native field-only associations may be sparse.
        return super().call(uri, args, options)


def declare_replacement(task):
    target = task.bind(RTPC)
    field = task.discover(target, 'ControlInput')
    code, types = task.step('draft-discover-types', '--role', 'object', '--meaning', task.input_type)
    assert code == 0, types
    kind = types['type_candidates'][0]['handle']
    values = []
    for name, value in task.input_properties.items():
        values.extend(('--new-control-input-field-value', task.class_field(kind, name), json.dumps(value)))
    code, declared = task.step('draft-declare-field-change', '--object-handle', target, '--field-handle', field,
        '--new-control-input-kind', kind, '--new-control-input-name', 'TimeMod',
        '--new-control-input-notes', 'New time control', *values)
    assert code == 0, declared
    return task


def test_existing_rtpc_replacement_keeps_curve_identity_list_and_shared_input(tmp_path):
    task = ReplacementTask(tmp_path)
    before = deepcopy(task.objects)
    declare_replacement(task)
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, json.dumps(verified)
    assert len(task.writes) == 1
    assert task.objects[OLD_CONTROL] == before[OLD_CONTROL]
    assert task.objects[FIRST] == before[FIRST]
    assert {key: value for key, value in task.objects[RTPC].items() if key != '@ControlInput'} == {
        key: value for key, value in before[RTPC].items() if key != '@ControlInput'}


def test_public_schema_discloses_closed_existing_rtpc_owned_reference_route(tmp_path):
    task = ReplacementTask(tmp_path)
    code, schema = task.run('operation-schema', 'object.set')
    assert code == 0, schema
    encoded = json.dumps(schema)
    assert 'replace_owned_control_input' in encoded and 'draft-declare-field-change' in encoded
    code, schema = task.run('operation-schema', 'object.setReference')
    assert code == 0, schema
    assert 'new_owned_ControlInput_requires_object.set_Business_Draft' in json.dumps(schema)


@pytest.mark.parametrize('fault', ['shared-input-changed', 'curve-changed', 'rtpc-notes-changed',
    'owner-membership-changed', 'wrong-input-owner', 'wrong-input-class'])
def test_replacement_rejects_changed_preserved_state_or_wrong_owned_identity(tmp_path, fault):
    task = declare_replacement(ReplacementTask(tmp_path))
    task.fault = fault
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 2 and verified.get('verified') is False, verified
    assert len(task.writes) == 1


def test_replacing_a_prior_owned_input_stops_before_preview_or_write(tmp_path):
    task = ReplacementTask(tmp_path)
    task.objects[OLD_CONTROL]['owner'] = {'id': RTPC}
    declare_replacement(task)
    code, checked = task.step('draft-check')
    assert code == 2 and 'OWNED_INPUT_REPLACEMENT_DISPOSITION_UNPROVEN' in json.dumps(checked), checked
    assert task.writes == []


def test_graph_replacement_has_copy_ready_business_declaration(tmp_path):
    task = ReplacementTask(tmp_path)
    task.bind(RTPC)
    code, inspected = task.run('draft-inspect', task.draft, '--task-authority', task.authority)
    assert code == 0, inspected
    action = inspected['draft']['next_action_binding']['replace_owned_control_input']
    assert 'draft-declare-field-change' in json.dumps(action)
    assert '--new-control-input-kind' in action['append']
