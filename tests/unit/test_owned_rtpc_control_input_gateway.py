"""New owned RTPC controls through the public Business Draft transaction seam.

Fixtures model the matching SDK's custom ModulatorTime example; fake execution
is program evidence only and never a native-Wwise receipt.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
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
        self.input_platform = None
        self.native_curve_points = [{'x': 0, 'y': -20, 'shape': 'Linear'},
            {'x': 5 if input_type == 'ModulatorTime' else 1000, 'y': 0, 'shape': 'Linear'}]

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
                self.objects.setdefault(CHILD, {'id': CHILD, 'name': 'PlannedSound', 'type': 'Sound', 'classId': 65552,
                    'path': self.objects[SECOND]['path'] + r'\PlannedSound', 'parent': {'id': SECOND}, 'notes': '', '@RTPC': []})
            node = (item['children'][0] if planned else item)['@RTPC'][0]
            assert node['@ControlInput'] == {'type': self.input_type, 'name': 'TimeMod',
                'notes': 'New time control', **({'platform': self.input_platform} if self.input_platform else {}),
                **{'@' + name: value for name, value in self.input_properties.items()}}
            self.objects[CONTROL] = {'id': CONTROL, 'name': 'TimeMod', 'type': self.input_type,
                'classId': self.input_classes[self.input_type], 'owner': {'id': RTPC}, 'path': r'\opaque-control',
                'notes': 'New time control', **({'@TimeModLoops': 1, '@TimeModDuration': 1} if self.input_type == 'ModulatorTime' else {}),
                **{'@' + name: value for name, value in self.input_properties.items()}}
            self.objects[CURVE] = {'id': CURVE, 'name': '', 'type': 'Curve', 'classId': 917520,
                'owner': {'id': RTPC}, 'path': r'\opaque-curve', 'notes': ''}
            self.objects[RTPC] = {'id': RTPC, 'name': '', 'type': 'RTPC', 'classId': 1441808,
                'owner': {'id': owner_id}, 'path': r'\opaque-rtpc', 'notes': '',
                '@PropertyName': 'Volume', '@ControlInput': {'id': CONTROL},
                '@Curve': {'id': CURVE, 'points': deepcopy(self.native_curve_points)}}
            self.objects[owner_id]['@RTPC'] = [*self.objects[owner_id]['@RTPC'], {'id': RTPC}]
            if self.fault == 'wrong-input-owner':
                self.objects[CONTROL]['owner'] = {'id': FIRST}
            elif self.fault == 'wrong-input-class':
                self.objects[CONTROL]['classId'] = 4194320
            elif self.fault == 'wrong-rtpc-class':
                self.objects[RTPC]['classId'] = 917520
            elif self.fault == 'wrong-input-value':
                self.objects[CONTROL]['@TimeModDuration'] = 6
            result = {'id': owner_id, 'name': 'PlannedSound' if planned else 'Sound', '@RTPC': [
                {'id': RTPC, 'name': '', '@ControlInput': {'id': CONTROL, 'name': 'TimeMod'}}]}
            if self.fault == 'duplicate-result':
                result['@RTPC'].append(deepcopy(result['@RTPC'][0]))
            elif self.fault == 'missing-result':
                result['@RTPC'] = []
            elif self.fault == 'foreign-result':
                result['id'] = SECOND
            return {'objects': [{'id': SECOND, 'name': 'Default Work Unit', 'children': [result]}] if planned else [result]}
        result = super().call(uri, args, options)
        if self.input_platform and uri.endswith('object.get') and CONTROL in args.get('from', {}).get('id', []) and options.get('platform') != self.input_platform:
            for row in result.get('return', []):
                for name in self.input_properties:
                    if name in row:
                        row[name] = None
                    if '@' + name in row:
                        row['@' + name] = None
        return result

    def class_field(self, kind, meaning):
        platform = getattr(self, 'field_platforms', {}).get(meaning, self.input_platform)
        code, found = self.step('draft-discover-fields', '--type-handle', kind, '--meaning', meaning,
            *(['--platform', platform] if platform else []))
        assert code == 0, found
        return found['meaning_results'][0]['candidates'][0]['handle']


def declare_time(task, owner=None, property_field=None, declaration_id='curve', expected_code=0, end_y=0, end_x=None, start_x=0):
    owner = task.bind(FIRST) if owner is None else owner
    property_field = task.discover(owner, 'Volume') if property_field is None else property_field
    code, types = task.step('draft-discover-types', '--role', 'object', '--meaning', task.input_type)
    assert code == 0, types
    kind = types['type_candidates'][0]['handle']
    values = []
    for name, value in task.input_properties.items():
        values.extend(('--new-control-input-field-value', task.class_field(kind, name), json.dumps(value)))
    code, declared = task.step('draft-declare-rtpc', *(['--declaration-id', declaration_id] if task.operation == 'object.set' else []), '--object-handle', owner,
        '--field-handle', property_field, '--new-control-input-kind', kind,
        '--new-control-input-name', 'TimeMod', '--new-control-input-notes', 'New time control',
        *values,
        '--point', str(start_x), '-20', 'Linear', '--point', str(end_x if end_x is not None else 5 if task.input_type == 'ModulatorTime' else 1000), str(end_y), 'Linear')
    assert code == expected_code, declared
    task.declaration_reply = declared
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


def test_native_2022_reference_labels_allow_the_declared_custom_time_class(tmp_path):
    fixture = json.loads((Path(__file__).parents[1] / 'fixtures/metadata/owned-control-input-2022-native-reference.json').read_text())
    task = OwnedControlTask(tmp_path)
    task.metadata['ControlInput'] = deepcopy(fixture['result'])
    task.metadata.update({name: deepcopy(capture['result']) for name, capture in fixture['selected_input_fields'].items()})
    declare_time(task)
    tx, shown = task.preview()
    assert task.writes == []
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified.get('verified') is True, verified
    assert len(task.writes) == 1


def test_native_2022_time_curve_change_is_rejected_before_write(tmp_path):
    fixture = json.loads((Path(__file__).parents[1] / 'fixtures/metadata/owned-control-input-2022-native-curve-change.json').read_text())
    assert fixture['request']['@Curve']['points'][-1]['x'] == 1000
    assert fixture['rtpc_readback']['Curve']['points'][-1]['x'] == 5
    task = declare_time(OwnedControlTask(tmp_path), end_x=1000)
    code, rejected = task.step('draft-check')
    assert code == 2 and rejected.get('error_code') == 'CONTROL_INPUT_TIME_AXIS_OUT_OF_RANGE', rejected
    assert rejected['details']['x_range_seconds'] == [0, 5] and task.writes == [], rejected


def test_time_axis_default_is_sealed_without_assigning_unrequested_duration(tmp_path):
    task = OwnedControlTask(tmp_path)
    task.input_properties.pop('TimeModDuration')
    task.native_curve_points[-1]['x'] = 1
    declare_time(task, end_x=1)
    tx, shown = task.preview()
    proof, = [node['owned_control_input'] for node in shown['artifact']['prepared_operation']['pre_state']['object_set_nodes'] if node.get('owned_control_input')]
    assert proof['time_axis']['x_range_seconds'] == [0, 1]
    assert proof['time_axis']['effective_duration_source'] == 'class_default'
    assert proof['time_axis']['native_domain_complete'] is False
    assert proof['constructor_authority']['time_axis']['unit'] == 'seconds'
    native = shown['artifact']['prepared_operation']['dispatch']['args']['objects'][0]['@RTPC'][0]['@ControlInput']
    assert '@TimeModDuration' not in native
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified.get('verified') is True, verified


@pytest.mark.parametrize('default', ['absent', None, pytest.param(10**400, id='oversized-integer')])
def test_time_axis_missing_default_gives_explicit_field_handle_repair(tmp_path, default):
    task = OwnedControlTask(tmp_path)
    task.input_properties.pop('TimeModDuration')
    if default == 'absent': task.metadata['TimeModDuration'].pop('default')
    else: task.metadata['TimeModDuration']['default'] = default
    declare_time(task, end_x=1)
    code, rejected = task.step('draft-check')
    assert code == 2 and rejected.get('error_code') == 'CONTROL_INPUT_TIME_DURATION_REQUIRED', rejected
    repair = rejected['details']['repair']
    assert repair['discover_field']['subcommand'] == 'draft-discover-fields'
    assert repair['discover_field']['meaning'] == 'Duration'
    assert repair['declare']['option'] == '--new-control-input-field-value' and task.writes == []


def test_time_axis_default_drift_blocks_before_source_write(tmp_path):
    task = OwnedControlTask(tmp_path)
    task.input_properties.pop('TimeModDuration')
    declare_time(task, end_x=1)
    tx, shown = task.preview()
    task.metadata['TimeModDuration']['default'] = 2
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, rejected = task.run('execute', tx)
    assert code == 2 and task.writes == [], rejected
    assert 'new object class metadata TimeModDuration unchanged' in json.dumps(rejected)


@pytest.mark.parametrize('operation', ['object.setRTPC', 'object.set'])
@pytest.mark.parametrize('start_x,end_x', [(0, 1000), (-1, 5)])
def test_time_axis_rejects_explicit_outside_points_through_named_and_graph_routes(tmp_path, operation, start_x, end_x):
    task = declare_time(OwnedControlTask(tmp_path, operation=operation), start_x=start_x, end_x=end_x)
    code, rejected = task.step('draft-check')
    assert code == 2 and rejected.get('error_code') == 'CONTROL_INPUT_TIME_AXIS_OUT_OF_RANGE', rejected
    assert rejected['details']['x_range_seconds'] == [0, 5] and task.writes == [], rejected


def test_time_axis_explicit_field_value_repairs_an_unproved_default(tmp_path):
    task = OwnedControlTask(tmp_path)
    task.metadata['TimeModDuration'].pop('default')
    declare_time(task)
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified.get('verified') is True, verified


def test_time_axis_admission_does_not_relax_exact_curve_verification(tmp_path):
    task = declare_time(OwnedControlTask(tmp_path))
    task.native_curve_points[-1]['x'] = 4
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 2 and verified.get('verified') is False, verified
    assert 'UNEXPECTED_RESULT_NODE' in json.dumps(verified) and len(task.writes) == 1


@pytest.mark.parametrize('restriction', ['excluded', 'shared-only'])
def test_native_2022_reference_labels_preserve_owned_target_constraints(tmp_path, restriction):
    fixture = json.loads((Path(__file__).parents[1] / 'fixtures/metadata/owned-control-input-2022-native-reference.json').read_text())
    task = OwnedControlTask(tmp_path)
    task.metadata['ControlInput'] = deepcopy(fixture['result'])
    row, = task.metadata['ControlInput']['restriction']['restrictions']
    if restriction == 'excluded': row['type'].remove('Modulator Time')
    else: row['sharedOnlyTypes'].append('Modulator Time')
    declare_time(task)
    code, rejected = task.step('draft-check')
    assert code == 2 and rejected.get('error_code') == 'INVALID_CONTROL_INPUT_TYPE', rejected
    expected = 'does not permit' if restriction == 'excluded' else 'requires a shared reference'
    assert expected in rejected['message'] and task.writes == [], rejected


@pytest.mark.parametrize('shared,allowed', [([''], 'unchanged'), (['Sound'], 'unchanged'), ([], None)])
def test_owned_reference_rejects_malformed_shared_type_metadata_before_write(tmp_path, shared, allowed):
    task = OwnedControlTask(tmp_path)
    task.metadata['ControlInput']['restriction']['restrictions'][0]['sharedOnlyTypes'] = shared
    if allowed is None: task.metadata['ControlInput']['restriction']['restrictions'][0]['type'] = None
    declare_time(task)
    code, rejected = task.step('draft-check')
    assert code == 2 and rejected.get('error_code') == 'INVALID_METADATA', rejected
    assert task.writes == []


@pytest.mark.parametrize('fault', ['wrong-input-owner', 'wrong-input-class', 'wrong-rtpc-class', 'wrong-input-value'])
def test_owned_time_input_rejects_independent_identity_or_ownership_mismatch(tmp_path, fault):
    task = declare_time(OwnedControlTask(tmp_path))
    task.fault = fault
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    if fault == 'wrong-rtpc-class':
        # The shared graph verifier rejects the malformed complete-list
        # readback, before it can certify a business-state verdict.
        assert code == 2 and verified.get('error_code') == 'INVALID_READBACK', verified
    else:
        assert code == 2 and verified.get('verified') is False, verified
    assert len(task.writes) == 1


@pytest.mark.parametrize('operation', ['object.setRTPC', 'object.set'])
def test_new_owned_input_cannot_reuse_and_reparent_a_prior_rtpc_control(tmp_path, operation):
    task = OwnedControlTask(tmp_path, operation=operation)
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


@pytest.mark.parametrize('conflict', ['fail', 'merge'])
def test_owned_time_input_below_a_planned_owner_has_no_invented_rtpc_path(tmp_path, conflict):
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
    if conflict != 'fail':
        code, configured = task.step('draft-business-configure', '--name-conflict', conflict)
        assert code == 0, configured
    tx, shown = task.preview()
    facts = shown['artifact']['prepared_operation']['pre_state']['planned_reference_context']['facts']
    assert len([fact for fact in facts.values() if fact['path'] is None]) == 2
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, json.dumps(verified)


def test_time_axis_rejection_also_precedes_planned_owner_creation(tmp_path):
    task = OwnedControlTask(tmp_path, operation='object.set')
    task.types.append({'name': 'WorkUnit', 'classId': 1638416, 'type': 'WObject'})
    task.objects[SECOND] = {'id': SECOND, 'name': 'Default Work Unit', 'type': 'WorkUnit', 'classId': 1638416,
        'path': r'\Actor-Mixer Hierarchy\Default Work Unit', 'parent': None, 'notes': 'Keep work unit'}
    parent = task.bind(SECOND)
    code, types = task.step('draft-discover-types', '--role', 'object', '--meaning', 'Sound')
    assert code == 0, types
    field = task.class_field(types['type_candidates'][0]['handle'], 'Volume')
    code, declared = task.step('draft-declare-new', '--declaration-id', 'sound', '--parent-handle', parent,
        '--kind', 'sound-sfx', '--name', 'PlannedSound')
    assert code == 0, declared
    declare_time(task, declared['draft']['declared_object']['result_handle'], field, end_x=1000)
    code, rejected = task.step('draft-check')
    assert code == 2 and rejected.get('error_code') == 'CONTROL_INPUT_TIME_AXIS_OUT_OF_RANGE', rejected
    assert task.writes == [] and CHILD not in task.objects

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
                {'x': 5 if self.input_type == 'ModulatorTime' else 1000, 'y': 0, 'shape': 'Linear'}]}}
        self.objects[FIRST]['@RTPC'] = [{'id': RTPC}]
        self.objects[CHILD] = {**deepcopy(self.objects[RTPC]), 'id': CHILD, '@PropertyName': 'Pitch',
            'notes': 'Keep unrelated RTPC', '@Curve': {'id': '{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD}',
                'points': [{'x': 0, 'y': 2, 'shape': 'Linear'}]}}
        self.objects[FIRST]['@RTPC'].append({'id': CHILD})

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
            elif self.fault == 'unrelated-rtpc-changed':
                self.objects[CHILD]['notes'] = 'Unexpected unrelated change'
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


@pytest.mark.parametrize('point', [None, {'x': '5', 'y': 0, 'shape': 'Linear'},
    {'x': True, 'y': 0, 'shape': 'Linear'}, {'x': 10**400, 'y': 0, 'shape': 'Linear'}],
    ids=['null-point', 'string-x', 'boolean-x', 'oversized-integer'])
def test_time_replacement_rejects_malformed_preserved_curve_readback_before_write(tmp_path, point):
    task = ReplacementTask(tmp_path)
    task.objects[RTPC]['@Curve']['points'] = [point]
    before = deepcopy(task.objects)
    declare_replacement(task)
    code, rejected = task.step('draft-check')
    assert code == 2 and rejected.get('error_code') == 'INVALID_READBACK', rejected
    assert task.writes == [] and task.objects == before


@pytest.mark.parametrize('duration', [5, 6])
def test_time_replacement_preserves_curve_or_requires_supported_duration_choice(tmp_path, duration):
    task = ReplacementTask(tmp_path)
    task.objects[RTPC]['@Curve']['points'][-1]['x'] = 6
    task.input_properties['TimeModDuration'] = duration
    before = deepcopy(task.objects)
    declare_replacement(task)
    if duration == 5:
        code, rejected = task.step('draft-check')
        assert code == 2 and rejected.get('error_code') == 'CONTROL_INPUT_TIME_AXIS_OUT_OF_RANGE', rejected
        repair = rejected['details']['repair']
        assert repair['declare']['subcommand'] == 'draft-declare-field-change'
        assert repair['declare']['option'] == '--new-control-input-field-value'
        assert 'cannot rewrite' in repair['preservation'] and 'draft-declare-rtpc' in repair['preservation']
        assert task.writes == [] and task.objects == before
    else:
        tx, shown = task.preview()
        code, verified = task.finish(tx, shown)
        assert code == 0 and verified.get('verified') is True, verified
        assert task.objects[RTPC]['@Curve'] == before[RTPC]['@Curve']
        assert '@Curve' not in task.writes[0]['objects'][0]


@pytest.mark.parametrize('version', ['2022.1', '2023.1', '2024.1', '2025.1'])
@pytest.mark.parametrize('input_type', ['ModulatorLfo', 'ModulatorEnvelope', 'ModulatorTime'])
def test_existing_rtpc_replacement_keeps_curve_identity_list_and_shared_input(tmp_path, version, input_type):
    task = ReplacementTask(tmp_path, version, input_type)
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
    assert '"unit": "seconds"' in encoded and '"native_domain_complete": false' in encoded
    assert 'partial_duration_endpoints' in encoded and 'native_field_order' in encoded
    assert 'non_fail_conflicts' not in encoded and 'nested_RTPCs' not in encoded
    assert 'mixed_platform_workflow' in encoded and 'new_object.setProperty_Draft' in encoded
    code, named = task.run('operation-schema', 'object.setRTPC')
    assert code == 0 and '"unit": "seconds"' in json.dumps(named), named
    assert '"native_domain_complete": false' in json.dumps(named)
    code, schema = task.run('operation-schema', 'object.setReference')
    assert code == 0, schema
    assert 'new_owned_ControlInput_requires_object.set_Business_Draft' in json.dumps(schema)


@pytest.mark.parametrize('fault', ['shared-input-changed', 'curve-changed', 'rtpc-notes-changed',
    'unrelated-rtpc-changed', 'owner-membership-changed', 'wrong-input-owner', 'wrong-input-class'])
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


@pytest.mark.parametrize('operation', ['object.setRTPC', 'object.set'])
def test_new_input_keeps_class_field_platform_through_native_and_readback(tmp_path, operation):
    task = OwnedControlTask(tmp_path, operation=operation)
    task.input_platform = 'Windows'
    declare_time(task)
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified.get('verified') is True, verified
    assert len(task.writes) == 1
    assert any(uri.endswith('object.get') and CONTROL in args.get('from', {}).get('id', [])
        and options.get('platform') == 'Windows' for uri, args, options in task.calls)


@pytest.mark.parametrize('different_curve', [False, True])
def test_owned_outcomes_bind_without_native_order_or_confusing_distinct_curves(tmp_path, different_curve):
    task = OwnedControlTask(tmp_path, operation='object.set')
    owner = task.bind(FIRST)
    field = task.discover(owner, 'Volume')
    for declaration in ['a', 'b']:
        declare_time(task, owner, field, declaration_id=declaration,
            end_y=2 if different_curve and declaration == 'b' else 0)
    original = task.call
    second_rtpc = '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}'
    second_input = '{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}'
    second_curve = '{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}'
    def call(uri, args=None, options=None):
        if not uri.endswith('object.set'):
            return original(uri, args, options)
        nodes = args['objects'][0]['@RTPC']
        assert len(nodes) == 2 and (nodes[0] != nodes[1]) == different_curve
        single = deepcopy(args)
        single['objects'][0]['@RTPC'] = [nodes[0]]
        original(uri, single, options)
        task.objects[second_rtpc] = {**deepcopy(task.objects[RTPC]), 'id': second_rtpc,
            '@ControlInput': {'id': second_input}, '@Curve': {'id': second_curve, 'points': deepcopy(nodes[1]['@Curve']['points'])}}
        task.objects[second_input] = {**deepcopy(task.objects[CONTROL]), 'id': second_input, 'owner': {'id': second_rtpc}}
        task.objects[second_curve] = {**deepcopy(task.objects[CURVE]), 'id': second_curve, 'owner': {'id': second_rtpc}}
        task.objects[FIRST]['@RTPC'].append({'id': second_rtpc})
        return {'objects': [{'id': FIRST, 'name': 'Sound', '@RTPC': [
            {'id': second_rtpc, 'name': ''}, {'id': RTPC, 'name': ''}]}]}
    task.call = call
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified.get('verified') is True, json.dumps(verified)
    assert len(task.writes) == 1


@pytest.mark.parametrize('operation', ['object.setRTPC', 'object.set'])
def test_new_input_combines_class_field_dependency_requirements_before_write(tmp_path, operation):
    task = OwnedControlTask(tmp_path, operation=operation)
    task.metadata['EnvelopeStopPlayback']['dependencies'] = [{'type': 'property', 'action': 'Enable',
        'context': 'Self', 'property': 'TimeModLoops',
        'conditions': [{'restriction': {'type': 'range', 'min': 1, 'max': 100}}]}]
    task.metadata['TimeModLoops'] = {'name': 'TimeModLoops', 'type': 'int32', 'default': 1,
        'restriction': {'type': 'range', 'min': 0, 'max': 100}}
    task.input_properties['TimeModLoops'] = 0
    declare_time(task)
    code, checked = task.step('draft-check')
    assert code == 2 and 'NEW_OBJECT_DEPENDENCY_CONFLICT' in json.dumps(checked), checked
    assert task.writes == []


def test_public_2021_boundary_is_limited_to_the_constructor_introduced_in_2022(tmp_path):
    task = OwnedControlTask(tmp_path)
    code, unavailable = task.run('--version', '2021.1', 'operation-schema', 'object.setRTPC')
    assert code == 0 and '2021.1' not in unavailable['operation']['supported_versions'], unavailable
    code, modern = task.run('operation-schema', 'object.setRTPC')
    assert code == 0, modern
    assert 'constructor_introduced_2022.1' in json.dumps(modern) and 'this_property_bound_RTPC_owned_ControlInput_constructor_only' in json.dumps(modern)
    assert task.writes == []


def test_owned_input_graph_counts_rtpc_curve_and_input_against_existing_node_cap(tmp_path):
    task = OwnedControlTask(tmp_path, operation='object.set')
    task.objects[SECOND] = {**deepcopy(task.objects[FIRST]), 'id': SECOND, 'name': 'Other',
        'path': r'\Actor-Mixer Hierarchy\Default Work Unit\Other', 'parent': None}
    owner = task.bind(FIRST)
    field = task.discover(owner, 'Volume')
    for index in range(32):
        declare_time(task, owner, field, declaration_id=str(index))
    owner = task.bind(SECOND)
    field = task.discover(owner, 'Volume')
    for index in range(32, 42):
        declare_time(task, owner, field, declaration_id=str(index))
    declare_time(task, owner, field, declaration_id='over-limit', expected_code=2)
    assert task.declaration_reply['error_code'] == 'NODE_LIMIT_EXCEEDED', task.declaration_reply
    assert task.writes == []


def test_mixed_generic_and_explicit_new_input_field_platforms_do_not_lose_intent(tmp_path):
    task = OwnedControlTask(tmp_path)
    task.input_platform = 'Windows'
    task.field_platforms = {'EnvelopeStopPlayback': None}
    declare_time(task, expected_code=2)
    assert task.declaration_reply['error_code'] == 'OWNED_CONTROL_INPUT_PLATFORM_ASSIGNMENTS_UNRESOLVED'
    assert '180' in json.dumps(task.declaration_reply) and task.writes == []


def test_generic_new_input_fields_do_not_inherit_a_different_graph_platform(tmp_path):
    task = OwnedControlTask(tmp_path, operation='object.set')
    declare_time(task)
    code, configured = task.step('draft-business-configure', '--platform', 'Windows')
    assert code == 0, configured
    code, rejected = task.step('draft-check')
    assert code == 2 and 'OWNED_CONTROL_INPUT_PLATFORM_ASSIGNMENTS_UNRESOLVED' in json.dumps(rejected), rejected
    assert task.writes == []


def seed_old_pair(task):
    old_curve = '{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD}'
    task.objects[OLD_CONTROL] = {'id': OLD_CONTROL, 'name': 'Intensity', 'type': 'GameParameter',
        'classId': 1507344, 'path': r'\Game Parameters\Default Work Unit\Intensity',
        'parent': {'id': SECOND}, 'owner': None, 'notes': 'Keep shared'}
    task.objects[CHILD] = {'id': CHILD, 'name': '', 'type': 'RTPC', 'classId': 1441808,
        'path': r'\old-rtpc', 'owner': {'id': FIRST}, 'notes': 'Keep old',
        '@PropertyName': 'Volume', '@ControlInput': {'id': OLD_CONTROL},
        '@Curve': {'id': old_curve, 'points': [{'x': 0, 'y': 0, 'shape': 'Linear'}]}}
    task.objects[old_curve] = {'id': old_curve, 'name': '', 'type': 'Curve', 'classId': 917520,
        'path': r'\old-curve', 'owner': {'id': CHILD}, 'notes': ''}
    task.objects[FIRST]['@RTPC'] = [{'id': CHILD}]
    return old_curve


@pytest.mark.parametrize('operation', ['object.setRTPC', 'object.set'])
def test_new_owned_input_preserves_additive_existing_pair_and_curve(tmp_path, operation):
    task = OwnedControlTask(tmp_path, operation=operation)
    seed_old_pair(task)
    before = deepcopy(task.objects[CHILD])
    declare_time(task)
    if operation == 'object.set':
        code, configured = task.step('draft-business-configure', '--name-conflict', 'merge')
        assert code == 0, configured
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified.get('verified') is True, verified
    assert task.objects[CHILD] == before and task.objects[FIRST]['@RTPC'] == [{'id': CHILD}, {'id': RTPC}]


@pytest.mark.parametrize('operation', ['object.setRTPC', 'object.set'])
def test_fresh_owned_input_does_not_bypass_exclusive_existing_property_limit(tmp_path, operation):
    task = OwnedControlTask(tmp_path, operation=operation)
    seed_old_pair(task)
    task.metadata['Volume']['supports']['rtpc'] = 'Exclusive'
    declare_time(task)
    code, rejected = task.step('draft-check')
    assert code == 2 and 'RTPC_EXCLUSIVE_CONFLICT' in json.dumps(rejected), rejected
    assert task.writes == []


def test_owned_replace_all_uses_final_exclusive_count_and_keeps_shared_input(tmp_path):
    task = OwnedControlTask(tmp_path, operation='object.set')
    old_curve = seed_old_pair(task)
    shared = deepcopy(task.objects[OLD_CONTROL])
    task.metadata['Volume']['supports']['rtpc'] = 'Exclusive'
    declare_time(task)
    code, configured = task.step('draft-business-configure', '--list-behavior', 'replace-all')
    assert code == 0, configured
    original = task.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('object.set'):
            assert args['listMode'] == 'replaceAll'
            del task.objects[CHILD]
            del task.objects[old_curve]
            task.objects[FIRST]['@RTPC'] = [{'id': RTPC}]
        return result
    task.call = call
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified.get('verified') is True, verified
    assert task.objects[OLD_CONTROL] == shared and len(task.writes) == 1


@pytest.mark.parametrize('fault', ['duplicate-result', 'missing-result', 'wrong-input-value'])
def test_graph_owned_input_rejects_incomplete_or_contrary_native_results(tmp_path, fault):
    task = declare_time(OwnedControlTask(tmp_path, operation='object.set'))
    task.fault = fault
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 2 and verified.get('verified') is False, verified
    assert len(task.writes) == 1


@pytest.mark.parametrize('fault', ['duplicate-result', 'missing-result', 'foreign-result'])
def test_named_new_input_rejects_malformed_or_foreign_result_associations(tmp_path, fault):
    task = declare_time(OwnedControlTask(tmp_path))
    task.fault = fault
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 2 and verified.get('verified') is False, verified
    assert len(task.writes) == 1


def test_existing_rtpc_replacement_seals_and_verifies_its_nonshareable_occurrence(tmp_path):
    task = declare_replacement(ReplacementTask(tmp_path))
    tx, shown = task.preview()
    state = shown['artifact']['prepared_operation']['pre_state']
    facts = state['planned_reference_context']['facts']
    assert len(facts) == 1, facts
    fact, = facts.values()
    assert fact['result_handle'].startswith('bnh1-') and fact['parent_identity'] == RTPC
    assert fact['path'] is None and fact['relation'] == 'owner'
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified.get('verified') is True, verified
    code, recorded = task.run('transaction-show', tx)
    assert code == 0, recorded
    verification, = [event['details']['verification'] for event in recorded['events']
        if event['event_type'] == 'verification_recorded']
    identities = [check for check in verification['assertions']
        if check.get('kind') == 'verified_owned_control_input_identity']
    assert len(identities) == 1 and identities[0]['passed'] is True, identities
    assert identities[0]['evidence']['result_handle'] == fact['result_handle']
    assert identities[0]['evidence']['object']['id'] == CONTROL


def test_replacement_existing_reference_drift_cannot_rebind_the_sealed_outcome(tmp_path):
    task = declare_replacement(ReplacementTask(tmp_path))
    tx, shown = task.preview()
    task.objects[RTPC]['@ControlInput'] = {'id': CONTROL}
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, rejected = task.run('execute', tx)
    assert code == 2 and task.writes == [], rejected


@pytest.mark.parametrize('operation', ['object.setRTPC', 'object.set', 'replacement'])
def test_constructor_authority_drift_blocks_before_single_write(tmp_path, monkeypatch, operation):
    from wwise_waapi import owned_control_inputs
    root = tmp_path / 'authority'
    resource = root / '2022.1' / 'owned-control-input-construction.json'
    resource.parent.mkdir(parents=True)
    packaged = Path(owned_control_inputs.__file__).parents[1] / 'resources' / 'metadata' / '2022.1' / resource.name
    resource.write_bytes(packaged.read_bytes())
    monkeypatch.setattr(owned_control_inputs, 'CONSTRUCTION_AUTHORITY_ROOT', root, raising=False)
    task = (declare_replacement(ReplacementTask(tmp_path)) if operation == 'replacement' else
        declare_time(OwnedControlTask(tmp_path, operation=operation)))
    tx, shown = task.preview()
    resource.write_bytes(resource.read_bytes() + b'\n')
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, rejected = task.run('execute', tx)
    assert code == 2 and task.writes == [], rejected
    assert 'constructor source authority unchanged' in json.dumps(rejected), rejected


def test_public_preview_seals_exact_versioned_constructor_source_without_sdk_runtime(tmp_path):
    task = declare_time(OwnedControlTask(tmp_path, version='2025.1'))
    _, shown = task.preview()
    nodes = shown['artifact']['prepared_operation']['pre_state']['object_set_nodes']
    proof, = [node['owned_control_input']['constructor_authority'] for node in nodes if node.get('owned_control_input')]
    resource = Path(__file__).parents[2] / 'skills/waapi-skill/resources/metadata/2025.1/owned-control-input-construction.json'
    assert proof['version'] == '2025.1' and proof['resource_sha256'] == sha256(resource.read_bytes()).hexdigest()
    assert proof['time_axis']['unit'] == 'seconds' and proof['time_axis']['complete_native_domain'] is False


def test_invalid_constructor_source_is_a_structured_no_write_preview_boundary(tmp_path, monkeypatch):
    from wwise_waapi import owned_control_inputs
    root = tmp_path / 'authority'
    resource = root / '2022.1' / 'owned-control-input-construction.json'
    resource.parent.mkdir(parents=True)
    resource.write_text('{"contract":"foreign"}')
    monkeypatch.setattr(owned_control_inputs, 'CONSTRUCTION_AUTHORITY_ROOT', root)
    task = declare_time(OwnedControlTask(tmp_path))
    code, rejected = task.step('draft-check')
    assert code == 2 and rejected['error_code'] == 'OWNED_CONTROL_INPUT_SOURCE_INVALID', rejected
    assert task.writes == []


def test_new_owned_input_rejects_a_scalar_handle_from_another_class(tmp_path):
    task = OwnedControlTask(tmp_path, operation='object.set')
    owner = task.bind(FIRST)
    owner_field = task.discover(owner, 'Volume')
    code, found = task.step('draft-discover-types', '--role', 'object', '--meaning', 'ModulatorTime')
    assert code == 0, found
    code, wrong = task.step('draft-discover-types', '--role', 'object', '--meaning', 'Sound')
    assert code == 0, wrong
    wrong_field = task.class_field(wrong['type_candidates'][0]['handle'], 'Volume')
    code, rejected = task.step('draft-declare-rtpc', '--declaration-id', 'curve', '--object-handle', owner, '--field-handle', owner_field,
        '--new-control-input-kind', found['type_candidates'][0]['handle'], '--new-control-input-name', 'TimeMod',
        '--new-control-input-field-value', wrong_field, '5', '--point', '0', '-20', 'Linear', '--point', '1000', '0', 'Linear')
    assert code == 2 and rejected['error_code'] == 'FIELD_HANDLE_SCOPE_MISMATCH', rejected
    assert task.writes == []


@pytest.mark.parametrize('replacement', [False, True])
def test_two_new_owned_inputs_obey_combined_exclusive_final_count(tmp_path, replacement):
    task = OwnedControlTask(tmp_path, operation='object.set')
    task.metadata['Volume']['supports']['rtpc'] = 'Exclusive'
    owner = task.bind(FIRST)
    field = task.discover(owner, 'Volume')
    for declaration in ['a', 'b']:
        declare_time(task, owner, field, declaration_id=declaration)
    if replacement:
        code, configured = task.step('draft-business-configure', '--list-behavior', 'replace-all')
        assert code == 0, configured
    code, rejected = task.step('draft-check')
    assert code == 2 and 'RTPC_EXCLUSIVE_CONFLICT' in json.dumps(rejected), rejected
    assert task.writes == []


@pytest.mark.parametrize('version,fault', [('2022.1', None), ('2025.1', None),
    ('2022.1', 'stale-curve'), ('2022.1', 'missing-result'), ('2022.1', 'changed-old-curve'),
    ('2022.1', 'exclusive')])
def test_parent_merge_adds_owned_control_and_preserves_existing_rtpc_pair(tmp_path, version, fault):
    task = OwnedControlTask(tmp_path, version=version, operation='object.set')
    task.types.extend([{'name': 'WorkUnit', 'classId': 1638416, 'type': 'WObject'},
        {'name': 'GameParameter', 'classId': 1507344, 'type': 'WObject'}])
    task.objects[SECOND] = {'id': SECOND, 'name': 'Default Work Unit', 'type': 'WorkUnit',
        'classId': 1638416, 'path': r'\Actor-Mixer Hierarchy\Default Work Unit', 'parent': None, 'notes': 'Keep work unit'}
    old_rtpc = '{88888888-8888-8888-8888-888888888888}'
    old_curve = '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}'
    task.objects[CHILD] = {'id': CHILD, 'name': 'PlannedSound', 'type': 'Sound', 'classId': 65552,
        'path': task.objects[SECOND]['path'] + r'\PlannedSound', 'parent': {'id': SECOND},
        'notes': 'Keep merged owner', '@RTPC': [{'id': old_rtpc}]}
    task.objects[OLD_CONTROL] = {'id': OLD_CONTROL, 'name': 'Intensity', 'type': 'GameParameter',
        'classId': 1507344, 'path': r'\Game Parameters\Default Work Unit\Intensity',
        'parent': {'id': SECOND}, 'owner': None, 'notes': 'Keep shared'}
    task.objects[old_curve] = {'id': old_curve, 'name': '', 'type': 'Curve', 'classId': 917520,
        'path': r'\old-curve', 'owner': {'id': old_rtpc}, 'notes': 'Keep Curve'}
    task.objects[old_rtpc] = {'id': old_rtpc, 'name': '', 'type': 'RTPC', 'classId': 1441808,
        'path': r'\old-rtpc', 'owner': {'id': CHILD}, 'notes': 'Keep existing RTPC',
        '@PropertyName': 'Volume', '@ControlInput': {'id': OLD_CONTROL},
        '@Curve': {'id': old_curve, 'points': [{'x': 0, 'y': 2, 'shape': 'Linear'}]}}
    before = deepcopy(task.objects)
    if fault == 'exclusive':
        task.metadata['Volume']['supports']['rtpc'] = 'Exclusive'
    parent = task.bind(SECOND)
    code, types = task.step('draft-discover-types', '--role', 'object', '--meaning', 'Sound')
    assert code == 0, types
    field = task.class_field(types['type_candidates'][0]['handle'], 'Volume')
    code, declared = task.step('draft-declare-new', '--declaration-id', 'sound', '--parent-handle', parent,
        '--kind', 'sound-sfx', '--name', 'PlannedSound')
    assert code == 0, declared
    declare_time(task, declared['draft']['declared_object']['result_handle'], field)
    code, configured = task.step('draft-business-configure', '--name-conflict', 'merge')
    assert code == 0, configured
    if fault == 'exclusive':
        code, rejected = task.step('draft-check')
        assert code == 2 and rejected['error_code'] == 'RTPC_EXCLUSIVE_CONFLICT', rejected
        assert task.writes == [] and task.objects == before
        return
    original = task.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('object.set') and fault == 'changed-old-curve':
            task.objects[old_rtpc]['@Curve']['points'][0]['y'] = 3
        return result
    task.call = call
    task.fault = fault
    tx, shown = task.preview()
    if fault == 'stale-curve':
        task.objects[old_rtpc]['@Curve']['points'][0]['y'] = 3
        code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
        assert code == 0, confirmed
        code, rejected = task.run('execute', tx)
        assert code == 2 and task.writes == [], rejected
        assert 'graph complete RTPC list pre-state unchanged' in json.dumps(rejected)
        return
    code, verified = task.finish(tx, shown)
    if fault is not None:
        assert code == 2 and verified.get('verified') is False, json.dumps(verified)
        assert len(task.writes) == 1
        expected_failure = ('MISSING_RESULT_NODES' if fault == 'missing-result' else
            'unrequested RTPC complete state and curve remain unchanged')
        assert expected_failure in json.dumps(verified), verified
        return
    assert code == 0 and verified.get('verified') is True, json.dumps(verified)
    assert len(task.writes) == 1 and task.writes[0]['onNameConflict'] == 'merge'
    assert task.objects[CHILD]['@RTPC'] == [{'id': old_rtpc}, {'id': RTPC}]
    assert task.objects[CHILD]['notes'] == before[CHILD]['notes']
    assert all(task.objects[key] == before[key] for key in (SECOND, old_rtpc, old_curve, OLD_CONTROL))
    assert task.objects[RTPC]['owner'] == {'id': CHILD}
    assert task.objects[CONTROL]['owner'] == {'id': RTPC}
    code, recorded = task.run('transaction-show', tx)
    assert code == 0, recorded
    verification, = [event['details']['verification'] for event in recorded['events']
        if event['event_type'] == 'verification_recorded']
    identities = [check for check in verification['assertions']
        if check.get('kind') == 'verified_owned_control_input_identity']
    assert len(identities) == 1 and identities[0]['passed'] is True, identities
    assert identities[0]['evidence']['object']['id'] == CONTROL
    facts = shown['artifact']['prepared_operation']['pre_state']['planned_reference_context']['facts']
    fact = next(fact for fact in facts.values() if fact['type'] == 'ModulatorTime')
    assert identities[0]['evidence']['result_handle'] == fact['result_handle']


def test_verified_input_accepts_separately_previewed_platform_field_assignment(tmp_path):
    task = declare_time(OwnedControlTask(tmp_path, operation='object.set'))
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified.get('verified') is True, verified
    before = deepcopy(task.objects)
    original, platform_duration = task.call, None
    def call(uri, args=None, options=None):
        nonlocal platform_duration
        if uri.endswith('object.setProperty'):
            assert args == {'object': CONTROL, 'platform': 'Windows', 'property': 'TimeModDuration', 'value': 6.0}
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            task.writes.append(deepcopy(args))
            platform_duration = 6.0
            return {'objects': [{'id': CONTROL, 'name': 'TimeMod'}]}
        result = original(uri, args, options)
        if (uri.endswith('object.get') and CONTROL in args.get('from', {}).get('id', [])
                and options.get('platform') == 'Windows' and platform_duration is not None):
            for row in result['return']:
                for token in ('TimeModDuration', '@TimeModDuration'):
                    if token in row:
                        row[token] = platform_duration
        return result
    task.call = call
    code, started = task.run('draft-start', 'object.setProperty')
    assert code == 0, started
    task.draft, task.authority = started['draft']['draft_id'], started['task_authority']
    task.revision = started['draft']['revision']
    target = task.bind(CONTROL)
    code, found = task.step('draft-discover-fields', '--object-handle', target,
        '--meaning', 'TimeModDuration', '--platform', 'Windows')
    assert code == 0, found
    field = found['meaning_results'][0]['candidates'][0]['handle']
    code, declared = task.step('draft-declare-field-change', '--object-handle', target,
        '--field-handle', field, '--business-value', '6')
    assert code == 0, json.dumps(declared)
    followup, shown = task.preview()
    assert followup != tx and len(task.writes) == 1 and platform_duration is None
    code, rejected = task.run('execute', followup)
    assert code == 2 and len(task.writes) == 1, rejected
    code, confirmed = task.run('confirm', followup, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, executed = task.run('execute', followup)
    assert code == 0, executed
    code, verified = task.run('verify', followup)
    assert code == 0 and verified.get('verified') is True, verified
    assert len(task.writes) == 2 and platform_duration == 6.0
    assert task.objects == before  # Generic values, RTPC/Curve and identity stay fixed.
