"""Public transfers select exact compatible destinations, independent of WWU name."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, FIRST, SECOND
from tests.unit.test_field_interface_closure_gateway import VERSIONS

OLD_PARENT = '{55555555-5555-5555-5555-555555555555}'
COPIED = '{77777777-7777-7777-7777-777777777777}'


class TransferTask(OwnedGraphTask):
    def __init__(self, path, version, operation, *, nested=False, source=False, default=False):
        super().__init__(path, version, operation)
        self.operation, self.writes = operation, []
        catalog = json.loads((Path(__file__).parents[2] / f'skills/waapi-skill/resources/metadata/{version}/object-types.json').read_text())
        self.types = catalog['types']  # Matching reflected catalog, not a guessed plugin alias.
        root = r'\Containers' if version == '2025.1' else r'\Actor-Mixer Hierarchy'
        destination = root + ('\\Default Work Unit' if default else '\\MIDI')
        parent_type = 'WorkUnit'
        if nested:
            destination += r'\Synths'
            parent_type = 'PropertyContainer' if version == '2025.1' else 'ActorMixer'
        if source:
            # Actual fixture destination: MIDI WWU's existing Synth One Sound.
            destination = root + ('\\Default Work Unit' if default else '\\MIDI') + r'\Synth'
            parent_type = 'Sound'
        class_by_name = {row['name']: row['classId'] for row in self.types}
        self.objects = {
            OLD_PARENT: {'id': OLD_PARENT, 'name': 'Source owner', 'type': 'Sound' if source else 'WorkUnit',
                'classId': class_by_name['Sound' if source else 'WorkUnit'], 'path': root + r'\Original', 'parent': None, 'notes': 'Keep source owner'},
            FIRST: {'id': FIRST, 'name': 'Wwise Synth One' if source else 'Rain', 'type': 'SourcePlugin' if source else 'Sound',
                'classId': class_by_name['Wwise Synth One' if source else 'Sound'],
                'path': root + '\\Original\\' + ('Wwise Synth One' if source else 'Rain'), 'parent': {'id': OLD_PARENT}, 'notes': 'Keep source'},
            SECOND: {'id': SECOND, 'name': destination.rsplit('\\', 1)[1], 'type': parent_type,
                'classId': class_by_name[parent_type], 'path': destination, 'parent': None, 'notes': 'Keep destination'},
        }

    def declare(self):
        for role, identity in [('object', FIRST), ('parent', SECOND)]:
            code, result = self.step('draft-bind-object', '--role', role, '--object-id', identity)
            assert code == 0, result
        code, result = self.step('draft-declare-object-change', '--name-conflict', 'fail')
        assert code == 0, result

    def call(self, uri, args=None, options=None):
        if uri.endswith(('object.copy', 'object.move')):
            self.calls.append((uri, deepcopy(args), deepcopy(options))); self.writes.append(deepcopy(args))
            identity = COPIED if self.operation == 'object.copy' else FIRST
            row = deepcopy(self.objects[FIRST]); row.update(id=identity, parent={'id': SECOND}, path=self.objects[SECOND]['path'] + '\\' + row['name'])
            self.objects[identity] = row
            return deepcopy(row)
        return super().call(uri, args, options)


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('operation', ['object.copy', 'object.move'])
@pytest.mark.parametrize('nested', [False, True])
def test_public_copy_move_accepts_custom_workunit_and_nested_destination(tmp_path, version, operation, nested):
    task = TransferTask(tmp_path, version, operation, nested=nested)
    task.declare()
    tx, shown = task.preview()
    args = shown['artifact']['prepared_operation']['dispatch']['args']
    assert args['object'] == FIRST and args['parent'] == SECOND
    code, result = task.finish(tx, shown)
    assert code == 0 and result['verified'] is True, result
    assert len(task.writes) == 1


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('operation', ['object.copy', 'object.move'])
def test_public_source_transfer_uses_exact_sound_in_midi_workunit(tmp_path, version, operation):
    task = TransferTask(tmp_path, version, operation, source=True)
    task.declare(); tx, shown = task.preview()
    code, result = task.finish(tx, shown)
    assert code == 0 and result['verified'] is True and len(task.writes) == 1, result


@pytest.mark.parametrize('version', ['2021.1', '2025.1'])
@pytest.mark.parametrize('operation', ['object.copy', 'object.move'])
def test_source_transfer_keeps_default_workunit_admission(tmp_path, version, operation):
    task = TransferTask(tmp_path, version, operation, source=True, default=True)
    task.declare(); tx, shown = task.preview()
    code, result = task.finish(tx, shown)
    assert code == 0 and result['verified'] is True and len(task.writes) == 1, result


@pytest.mark.parametrize('version', ['2021.1', '2025.1'])
@pytest.mark.parametrize('operation', ['object.copy', 'object.move'])
def test_file_source_transfer_uses_version_pinned_class_and_actual_object_type(tmp_path, version, operation):
    task = TransferTask(tmp_path, version, operation, source=True)
    # Pinned2021 getTypes names class16 AudioSource; object.get reports
    # AudioFileSource. Modern getTypes names that same class AudioFileSource.
    task.objects[FIRST].update(type='AudioFileSource', classId=16, name='Recording',
        path=task.objects[OLD_PARENT]['path'] + r'\Recording')
    code, schema = task.run('--version', version, 'operation-schema', operation)
    assert code == 0, schema
    assert schema['business_adapter']['safety']['destination']['admission'].endswith('independent_of_WorkUnit_name')
    task.declare(); tx, shown = task.preview()
    code, result = task.finish(tx, shown)
    assert code == 0 and result['verified'] is True and len(task.writes) == 1, result


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('fault', ['project-root', 'management-root', 'unknown-root', 'leaf', 'wrong-group-child', 'source-under-workunit', 'protected-source'])
def test_transfer_rejects_protected_or_incompatible_destinations_without_write(tmp_path, version, fault):
    task = TransferTask(tmp_path, version, 'object.copy', source=fault == 'source-under-workunit')
    parent = task.objects[SECOND]
    if fault == 'project-root': parent.update(type='Project', path='\\')
    elif fault == 'management-root': parent.update(type='WorkUnit', path='\\Containers' if version == '2025.1' else '\\Actor-Mixer Hierarchy')
    elif fault == 'unknown-root': parent['path'] = r'\Invented Hierarchy\Custom'
    elif fault == 'leaf': parent['type'] = 'Sound'
    elif fault == 'wrong-group-child': parent['type'] = 'StateGroup'
    elif fault == 'source-under-workunit': parent['type'] = 'WorkUnit'
    else: task.objects[FIRST].update(type='WorkUnit', name='Default Work Unit',
        path=('\\Containers' if version == '2025.1' else '\\Actor-Mixer Hierarchy') + '\\Default Work Unit')
    if fault == 'project-root':
        code, result = task.step('draft-bind-object', '--role', 'parent', '--object-id', SECOND)
        assert code == 2 and result.get('ok') is False and task.writes == [], result
        return  # Public object binding itself rejects a Project-root identity.
    task.declare()
    code, result = task.step('draft-check')
    assert code == 2 and result.get('ok') is False and task.writes == [], result


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('fault', ['path', 'type', 'parent-class', 'source-class', 'source-category', 'missing-parent'])
def test_source_transfer_revalidates_preview_identity_classes_and_live_catalog_before_write(tmp_path, version, fault):
    task = TransferTask(tmp_path, version, 'object.copy', source=True)
    task.declare(); tx, shown = task.preview()
    code, result = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, result
    if fault == 'path': task.objects[SECOND]['path'] += '_changed'
    elif fault == 'type': task.objects[SECOND]['type'] = 'Event'
    elif fault == 'parent-class': task.objects[SECOND]['classId'] = 16
    elif fault == 'source-class': task.objects[FIRST]['classId'] = 16
    elif fault == 'source-category': next(row for row in task.types if row['classId'] == task.objects[FIRST]['classId'])['type'] = 'Effect'
    else: del task.objects[SECOND]
    code, result = task.run('execute', tx)
    assert code == 2 and result.get('executed') is not True and task.writes == [], result


@pytest.mark.parametrize('fault', ['copied-class', 'parent-class', 'source-category'])
def test_source_transfer_verification_rejects_class_contradiction_after_one_write(tmp_path, fault):
    task = TransferTask(tmp_path, '2025.1', 'object.copy', source=True)
    task.declare(); tx, shown = task.preview()
    code, result = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token']); assert code == 0, result
    code, result = task.run('execute', tx); assert code == 0, result
    if fault == 'copied-class': task.objects[COPIED]['classId'] = 16
    elif fault == 'parent-class': task.objects[SECOND]['classId'] = 16
    else: next(row for row in task.types if row['classId'] == task.objects[FIRST]['classId'])['type'] = 'Effect'
    code, result = task.run('verify', tx)
    assert code == 2 and result.get('verified') is not True and len(task.writes) == 1, result
