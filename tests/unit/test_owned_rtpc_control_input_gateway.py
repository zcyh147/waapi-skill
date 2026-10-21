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
CONTROL = '{77777777-7777-7777-7777-777777777777}'


class OwnedControlTask(OwnedGraphTask):
    def __init__(self, path, version='2022.1', operation='object.setRTPC'):
        super().__init__(path, version, operation)
        self.types = [{'name': name, 'classId': class_id, 'type': 'WObject'} for name, class_id in (
            ('Sound', 65552), ('RTPC', 1441808), ('Curve', 917520), ('ModulatorTime', 5111824))]
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
            node = args['objects'][0]['@RTPC'][0]
            assert node['@ControlInput'] == {'type': 'ModulatorTime', 'name': 'TimeMod',
                'notes': 'New time control', '@TimeModDuration': 5, '@EnvelopeStopPlayback': False}
            self.objects[CONTROL] = {'id': CONTROL, 'name': 'TimeMod', 'type': 'ModulatorTime',
                'classId': 5111824, 'owner': {'id': RTPC}, 'path': r'\opaque-control',
                'notes': 'New time control', '@TimeModDuration': 5, '@EnvelopeStopPlayback': False}
            self.objects[CURVE] = {'id': CURVE, 'name': '', 'type': 'Curve', 'classId': 917520,
                'owner': {'id': RTPC}, 'path': r'\opaque-curve', 'notes': ''}
            self.objects[RTPC] = {'id': RTPC, 'name': '', 'type': 'RTPC', 'classId': 1441808,
                'owner': {'id': FIRST}, 'path': r'\opaque-rtpc', 'notes': '',
                '@PropertyName': 'Volume', '@ControlInput': {'id': CONTROL},
                '@Curve': {'id': CURVE, 'points': [{'x': 0, 'y': -20, 'shape': 'Linear'},
                    {'x': 1000, 'y': 0, 'shape': 'Linear'}]}}
            self.objects[FIRST]['@RTPC'] = [{'id': RTPC}]
            if self.fault == 'wrong-input-owner':
                self.objects[CONTROL]['owner'] = {'id': FIRST}
            elif self.fault == 'wrong-input-class':
                self.objects[CONTROL]['classId'] = 4194320
            elif self.fault == 'wrong-rtpc-class':
                self.objects[RTPC]['classId'] = 917520
            return {'objects': [{'id': FIRST, 'name': 'Sound', '@RTPC': [
                {'id': RTPC, 'name': '', '@ControlInput': {'id': CONTROL, 'name': 'TimeMod'}}]}]}
        return super().call(uri, args, options)

    def class_field(self, kind, meaning):
        code, found = self.step('draft-discover-fields', '--type-handle', kind, '--meaning', meaning)
        assert code == 0, found
        return found['meaning_results'][0]['candidates'][0]['handle']


def declare_time(task):
    owner = task.bind(FIRST)
    property_field = task.discover(owner, 'Volume')
    code, types = task.step('draft-discover-types', '--role', 'object', '--meaning', 'ModulatorTime')
    assert code == 0, types
    kind = types['type_candidates'][0]['handle']
    duration = task.class_field(kind, 'TimeModDuration')
    stop = task.class_field(kind, 'EnvelopeStopPlayback')
    code, declared = task.step('draft-declare-rtpc', '--object-handle', owner,
        '--field-handle', property_field, '--new-control-input-kind', kind,
        '--new-control-input-name', 'TimeMod', '--new-control-input-notes', 'New time control',
        '--new-control-input-field-value', duration, '5',
        '--new-control-input-field-value', stop, 'false',
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
