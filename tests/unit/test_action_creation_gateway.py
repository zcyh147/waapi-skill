"""Source-certified unnamed Action construction through ordinary object Drafts."""
from copy import deepcopy
import json
import pytest
from tests.unit.test_field_interface_closure_gateway import CreateTask, FIRST, SECOND, VERSIONS

TARGET = '{33333333-3333-3333-3333-333333333333}'
CREATED = '{44444444-4444-4444-4444-444444444444}'
OLD = '{55555555-5555-5555-5555-555555555555}'


class ActionCreateTask(CreateTask):
    def __init__(self, path, version, operation='object.create'):
        super().__init__(path, version, operation)
        self.types = [{'name': 'Folder', 'type': 'WObject', 'classId': 1},
            {'name': 'Event', 'type': 'WObject', 'classId': 131088},
            {'name': 'Action', 'type': 'WObject', 'classId': 327696},
            {'name': 'Sound', 'type': 'WObject', 'classId': 65552}]
        self.objects[SECOND]['classId'] = 131088
        self.objects[TARGET] = {'id': TARGET, 'name': 'Rain', 'type': 'Sound', 'classId': 65552,
            'path': r'\Actor-Mixer Hierarchy\Default Work Unit\Rain', 'parent': {'id': FIRST}, 'notes': ''}
        self.objects[OLD] = {'id': OLD, 'name': '', 'type': 'Action', 'classId': 327696,
            'path': self.objects[SECOND]['path'] + r'\[Stop - Rain]', 'parent': {'id': SECOND},
            'notes': 'retained', 'ActionType': 2, 'Target': {'id': TARGET}}
        self.metadata = {'ActionType': {'name': 'ActionType', 'type': 'int16', 'default': 1,
            'restriction': {'type': 'enum', 'values': [{'value': 1, 'displayName': '/Play'}, {'value': 2, 'displayName': '/Stop/Stop'}]}},
            'Target': {'name': 'Target', 'type': '', 'restriction': {}}}
        self.drop = None

    def call(self, uri, args=None, options=None):
        if uri in {'ak.wwise.core.object.create', 'ak.wwise.core.object.set'}:
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            node = args if uri.endswith('.create') else args['objects'][0]['children'][0]
            row = {'id': CREATED, 'name': '', 'type': 'Action', 'classId': 327696,
                'path': self.objects[SECOND]['path'] + r'\[Play - Rain]', 'parent': {'id': SECOND},
                'notes': '', 'ActionType': node['@ActionType'], 'Target': {'id': node['@Target']}}
            if self.drop == 'type': row['ActionType'] = 2
            if self.drop == 'target': row['Target'] = {'id': FIRST}
            if self.drop == 'parent': row['parent'] = {'id': FIRST}
            if self.drop == 'class': row['classId'] = 1
            if self.drop == 'recycled': row['id'] = OLD
            if self.drop == 'retained': self.objects[OLD]['Target'] = {'id': FIRST}
            self.objects[row['id']] = row
            created = {'id': row['id'], 'name': ''}
            return created if uri.endswith('.create') else {'objects': [{'id': SECOND, 'name': self.objects[SECOND]['name'], 'children': [created]}]}
        return super().call(uri, args, options)

    def declare_action(self):
        parent, target = self.bind(SECOND), self.bind(TARGET)
        kind = self.discover_kind('Action')
        code, fields = self.step('draft-discover-fields', '--type-handle', kind, '--meaning', 'ActionType', '--meaning', 'Target')
        assert code == 0, fields
        handles = {row['meaning']: row['candidates'][0]['handle'] for row in fields['meaning_results']}
        code, declared = self.step('draft-declare-new', '--declaration-id', 'play', '--parent-handle', parent,
            '--name', 'play-rain-local-label', '--kind', kind,
            '--field-value', handles['ActionType'], '1', '--field-value', handles['Target'], target)
        assert code == 0, declared
        return declared


def preview(task):
    code, checked = task.step('draft-check')
    assert code == 0, checked
    code, shown = task.step('preview-from-draft')
    assert code == 0, shown
    tx = shown['transaction_id']
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    return tx, shown


@pytest.mark.parametrize('fault', ['type', 'target', 'parent', 'class', 'recycled', 'retained'])
def test_action_native_acknowledgement_cannot_hide_wrong_effect_or_reused_guid(tmp_path, fault):
    task = ActionCreateTask(tmp_path, '2025.1')
    task.declare_action()
    tx, shown = preview(task)
    task.drop = fault
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, executed = task.run('execute', tx)
    assert code == 0, executed
    code, verified = task.run('verify', tx)
    assert code == 2 and verified.get('verified') is not True, verified


@pytest.mark.parametrize('version,operation', [(v, op) for op in ('object.create', 'object.set') for v in (VERSIONS if op == 'object.create' else VERSIONS[1:])])
def test_new_action_uses_discovered_fields_empty_name_and_exact_parent(tmp_path, version, operation):
    task = ActionCreateTask(tmp_path, version, operation)
    before = deepcopy(task.objects)
    task.declare_action()
    code, checked = task.step('draft-check')
    assert code == 0, checked
    code, previewed = task.step('preview-from-draft')
    assert code == 0, previewed
    tx = previewed['transaction_id']
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    dispatch = shown['artifact']['prepared_operation']['dispatch']
    node = dispatch['args'] if operation == 'object.create' else dispatch['args']['objects'][0]['children'][0]
    assert node['name'] == '' and node['type'] == 'Action'
    assert node['@ActionType'] == 1 and node['@Target'] == TARGET
    assert task.objects == before
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, executed = task.run('execute', tx)
    assert code == 0, executed
    code, verified = task.run('verify', tx)
    assert code == 0 and verified['verified'] is True, json.dumps(verified, indent=2)
    assert all(task.objects[key] == row for key, row in before.items())
    assert len([uri for uri, _, _ in task.calls if uri in {'ak.wwise.core.object.create', 'ak.wwise.core.object.set'}]) == 1


@pytest.mark.parametrize('fault', ['enum', 'parent', 'retained'])
def test_action_preview_revalidates_class_fields_parent_and_retained_children(tmp_path, fault):
    task = ActionCreateTask(tmp_path, '2025.1')
    task.declare_action()
    tx, shown = preview(task)
    if fault == 'enum': task.metadata['ActionType']['restriction']['values'].pop(0)
    if fault == 'parent': task.objects[SECOND]['type'] = 'Sound'
    if fault == 'retained': task.objects[OLD]['ActionType'] = 1
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, executed = task.run('execute', tx)
    assert code == 2 and executed.get('executed') is not True, executed
    assert not any(uri in {'ak.wwise.core.object.create', 'ak.wwise.core.object.set'} for uri, _, _ in task.calls)


def test_action_class_reference_evidence_never_overrides_contradictory_scalar_kind(tmp_path):
    task = ActionCreateTask(tmp_path, '2025.1')
    task.bind(SECOND)
    kind = task.discover_kind('Action')
    task.metadata['Target']['type'] = 'Real64'
    code, fields = task.step('draft-discover-fields', '--type-handle', kind, '--meaning', 'Target')
    assert code == 0, fields
    field, = fields['meaning_results'][0]['candidates']
    assert field['field_kind'] == 'property' and 'kind_evidence' not in field


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1'])
def test_action_constructor_preserves_retained_native_unknown_kind_metadata(tmp_path, version):
    from pathlib import Path
    samples = json.loads((Path(__file__).parents[1] / 'fixtures/metadata-conditions/action-target-class-unknown.json').read_bytes())['samples']
    task = ActionCreateTask(tmp_path, version)
    task.metadata['Target'] = deepcopy(samples[version]['metadata'])
    original = deepcopy(task.metadata['Target'])
    task.declare_action()
    tx, shown = preview(task)
    assert task.metadata['Target'] == original
    node, = shown['artifact']['prepared_operation']['pre_state']['object_create_nodes']
    normalized = node['new_object_default_evidence'][0]['metadata']['Target']
    assert normalized['type'] == original['type'] == ''
    assert normalized['reference_kind_evidence']['kind'] == 'documented-class-reference-kind'
    assert normalized['restriction'] == original['restriction']
