"""Existing exact MetadataSlot GUIDs retain their source-proven owned identity."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.unit.test_conditional_reference_gateway import AttenuationTask, FIRST, SECOND
from tests.unit.test_time_modulator_range_gateway import finish

OWNER = '{33333333-3333-3333-3333-333333333333}'
PEER = '{44444444-4444-4444-4444-444444444444}'
OLD = '{55555555-5555-5555-5555-555555555555}'
PEER_REFERENCE = '{66666666-6666-6666-6666-666666666666}'
FACTS = json.loads((Path(__file__).parents[1] / 'fixtures/metadata/metadata-slot-local-reference-2025.json').read_text())


class RetainedMetadataTask(AttenuationTask):
    def __init__(self, path):
        super().__init__(path, '2025.1', operation='object.setReference')
        self.metadata = {'Metadata': deepcopy(FACTS['field_metadata']['result'])}
        self.types = [{'classId': 5570560, 'name': 'MetadataSlot', 'type': 'Inner'},
            {'classId': 65552, 'name': 'Sound', 'type': 'WObject'},
            {'classId': 58982409, 'name': 'Wwise System Output Settings', 'type': 'Metadata'}]
        base = r'\Containers\Default Work Unit\Retained Sound'
        self.objects = {
            OWNER: {'id': OWNER, 'name': 'Retained Sound', 'type': 'Sound', 'classId': 65552,
                'path': base, 'notes': 'Keep owner', '@Metadata': [{'id': FIRST}, {'id': PEER}]},
            FIRST: {'id': FIRST, 'name': '', 'type': 'PluginInnerObject', 'classId': 5570560,
                'path': base + r'\[MetadataSlot: (Old)]', 'owner': {'id': OWNER},
                'notes': 'Keep selected notes', '@Metadata': [{'id': OLD, 'name': 'Old'}]},
            PEER: {'id': PEER, 'name': '', 'type': 'PluginInnerObject', 'classId': 5570560,
                'path': base + r'\[MetadataSlot: (New)]', 'owner': {'id': OWNER},
                'notes': 'Keep peer', '@Metadata': [{'id': PEER_REFERENCE, 'name': 'Peer target'}]},
            OLD: {'id': OLD, 'name': 'Old', 'type': 'Metadata', 'classId': 58982409,
                'path': r'\Metadata\Default Work Unit\Old', 'notes': 'Keep old target'},
            PEER_REFERENCE: {'id': PEER_REFERENCE, 'name': 'Peer target', 'type': 'Metadata', 'classId': 58982409,
                'path': r'\Metadata\Default Work Unit\Peer target', 'notes': 'Keep peer target'},
            SECOND: {'id': SECOND, 'name': 'New', 'type': 'Metadata', 'classId': 58982409,
                'path': r'\Metadata\Default Work Unit\New', 'notes': 'Keep new target'},
        }

    def run(self, *argv):
        code, payload = super().run(*argv)
        records = getattr(self, 'responses', [])
        records.append({'argv': list(argv), 'exit_code': code, 'payload': payload})
        self.responses = records
        (self.path / 'retained-calls.json').write_text(json.dumps(records, indent=2))
        return code, payload

    def call(self, uri, args=None, options=None):
        if uri.endswith('setReference'):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            self.objects[args['object']]['@' + args['reference']] = [
                {'id': args['value'], 'name': self.objects[args['value']]['name']}]
            return {}
        result = super().call(uri, args, options)
        if uri.endswith('object.get'):
            for row in result.get('return', []):
                if row.get('id') in {FIRST, PEER}:
                    row.pop('Metadata', None)  # Unprefixed shape is not observed by R89.
        return result


def test_retained_metadata_slot_binds_discovers_and_edits_exact_reference(tmp_path):
    task = RetainedMetadataTask(tmp_path)
    before = deepcopy(task.objects)
    source, target = task.bind(FIRST), task.bind(SECOND)
    field = task.discover(source, 'Metadata')
    code, declared = task.step('draft-declare-field-change', '--object-handle', source,
        '--field-handle', field, '--target-handle', target)
    assert code == 0, declared
    _, _, verified, _ = finish(task)
    assert verified['verified'] is True
    assert task.objects == {**before, FIRST: {**before[FIRST], '@Metadata': [{'id': SECOND, 'name': 'New'}]}}
    assert [args for uri, args, _ in task.calls if uri.endswith('setReference')] == [
        {'object': FIRST, 'reference': 'Metadata', 'value': SECOND}]


@pytest.mark.parametrize('fault', ['wrong-class', 'wrong-owner', 'wrong-owner-type', 'missing-membership'])
def test_retained_metadata_identity_requires_exact_class_owner_and_membership(tmp_path, fault):
    task = RetainedMetadataTask(tmp_path)
    if fault == 'wrong-class':
        task.objects[FIRST]['classId'] = 5505040
    elif fault == 'wrong-owner':
        task.objects[FIRST]['owner'] = {'id': SECOND}
    elif fault == 'wrong-owner-type':
        task.objects[OWNER]['type'] = 'Bus'
    else:
        task.objects[OWNER]['@Metadata'] = [{'id': PEER}]
    code, rejected = task.step('draft-bind-object', '--object-id', FIRST)
    assert code == 2 and rejected['error_code'] == 'BUSINESS_OBJECT_BINDING_MISMATCH', rejected
    assert not any(uri.endswith(('setReference', 'object.set')) for uri, _, _ in task.calls)
