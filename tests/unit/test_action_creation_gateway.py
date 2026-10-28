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
            'restriction': {'type': 'enum', 'values': [{'value': 1, 'displayName': '/Play'}, {'value': 2, 'displayName': '/Stop/Stop'}, {'value': 3, 'displayName': '/Stop/Stop All'}]}},
            'Target': {'name': 'Target', 'type': '', 'restriction': {}}}
        self.drop = None

    def call(self, uri, args=None, options=None):
        if uri in {'ak.wwise.core.object.create', 'ak.wwise.core.object.set'}:
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            nodes = [args] if uri.endswith('.create') else args['objects'][0]['children']
            created = []
            for index, node in enumerate(nodes):
                identity = CREATED if index == 0 else '{66666666-6666-6666-6666-666666666666}'
                row = {'id': identity, 'name': '', 'type': 'Action', 'classId': 327696,
                    'path': self.objects[SECOND]['path'] + ('\\[Play - Rain]' if index == 0 else '\\[Stop All]'),
                    'parent': {'id': SECOND}, 'notes': node.get('notes', ''), 'ActionType': node['@ActionType'],
                    'Target': {'id': node['@Target']} if node.get('@Target') else None}
                if self.drop == 'type': row['ActionType'] = 2
                if self.drop == 'target': row['Target'] = {'id': FIRST}
                if self.drop == 'parent': row['parent'] = {'id': FIRST}
                if self.drop == 'class': row['classId'] = 1
                if self.drop == 'recycled': row['id'] = OLD
                if self.drop == 'retained': self.objects[OLD]['Target'] = {'id': FIRST}
                if self.drop == 'duplicate' and index: row['id'] = CREATED
                self.objects[row['id']] = row
                created.append({'id': row['id'], 'name': ''})
            if getattr(self, 'reverse_results', False): created.reverse()
            if self.drop == 'missing': created.pop()
            return created[0] if uri.endswith('.create') else {'objects': [{'id': SECOND, 'name': self.objects[SECOND]['name'], 'children': created}]}
        return super().call(uri, args, options)

    def declare_action(self, *, targetless=False, declaration_id='play', parent_handle=None, notes=None):
        if not hasattr(self, 'action_handles'):
            self.action_handles = (self.bind(SECOND), self.bind(TARGET), self.discover_kind('Action'))
        parent, target, kind = self.action_handles
        if parent_handle is not None: parent = parent_handle
        code, fields = self.step('draft-discover-fields', '--type-handle', kind, '--meaning', 'ActionType', '--meaning', 'Target')
        assert code == 0, fields
        handles = {row['meaning']: row['candidates'][0]['handle'] for row in fields['meaning_results']}
        code, declared = self.step('draft-declare-new', '--declaration-id', declaration_id, '--parent-handle', parent,
            '--name', 'play-rain-local-label' if declaration_id == 'play' else declaration_id, '--kind', kind,
            '--field-value', handles['ActionType'], '3' if targetless else '1',
            '--field-value', handles['Target'], 'null' if targetless else target,
            *(('--field', 'notes', notes) if notes is not None else ()))
        assert code == 0, declared
        return declared


def preview(task):
    code, checked = task.step('draft-check')
    assert code == 0, json.dumps(checked)
    code, shown = task.step('preview-from-draft')
    assert code == 0, shown
    tx = shown['transaction_id']
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    return tx, shown


@pytest.mark.parametrize('version,operation', [(version, 'object.create') for version in VERSIONS] + [('2025.1', 'object.set')])
@pytest.mark.parametrize('conflict', ['rename', 'merge', 'replace'])
def test_action_collision_policies_bind_one_exact_event_occurrence(tmp_path, version, operation, conflict):
    task = ActionCreateTask(tmp_path, version, operation)
    task.declare_action(notes='new Action notes')
    old = deepcopy(task.objects[OLD])
    original = task.call
    def call(uri, args=None, options=None):
        if uri in {'ak.wwise.core.object.create', 'ak.wwise.core.object.set'} and conflict != 'rename':
            if conflict == 'replace':
                del task.objects[OLD]
                return original(uri, args, options)
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            node = args if uri.endswith('.create') else args['objects'][0]['children'][0]
            task.objects[OLD].update(ActionType=node['@ActionType'], Target={'id': node['@Target']},
                path=task.objects[SECOND]['path'] + r'\[Play - Rain]')
            result = {'id': OLD, 'name': ''}
            return result if uri.endswith('.create') else {'objects': [{'id': SECOND, 'name': task.objects[SECOND]['name'], 'children': [result]}]}
        return original(uri, args, options)
    task.call = call
    settings = ['--name-conflict', conflict]
    if operation == 'object.create' and conflict == 'replace': settings += ['--replace-owner-handle', task.action_handles[0]]
    code, configured = task.step('draft-business-configure', *settings)
    assert code == 0, configured
    tx, shown = preview(task)
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, executed = task.run('execute', tx)
    assert code == 0, json.dumps(executed)
    code, verified = task.run('verify', tx)
    assert code == 0 and verified['verified'] is True, json.dumps([row for row in verified.get('verification', {}).get('assertions', []) if row.get('passed') is False])
    if conflict == 'merge':
        assert CREATED not in task.objects and task.objects[OLD]['notes'] == old['notes']
        assert task.objects[OLD]['ActionType'] == 1
    elif conflict == 'replace':
        assert OLD not in task.objects and task.objects[CREATED]['notes'] == 'new Action notes'
    else:
        assert task.objects[OLD] == old and task.objects[CREATED]['notes'] == 'new Action notes'


@pytest.mark.parametrize('conflict', ['merge', 'replace'])
def test_action_collision_cannot_choose_between_multiple_empty_name_actions(tmp_path, conflict):
    task = ActionCreateTask(tmp_path, '2025.1', 'object.set')
    extra = '{88888888-8888-8888-8888-888888888888}'
    task.objects[extra] = {**deepcopy(task.objects[OLD]), 'id': extra, 'path': r'\Other Action display path'}
    task.declare_action()
    code, configured = task.step('draft-business-configure', '--name-conflict', conflict)
    assert code == 0, configured
    code, rejected = task.step('draft-check')
    assert code == 2 and 'AMBIGUOUS_ACTION_COLLISION' in json.dumps(rejected), rejected
    assert not any(uri in {'ak.wwise.core.object.create', 'ak.wwise.core.object.set'} for uri, _, _ in task.calls)


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
    request = shown['artifact']['request']['arguments']
    request_node = request if operation == 'object.create' else request['objects'][0]['children'][0]
    assert request_node['name'] == 'play-rain-local-label'
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


@pytest.mark.parametrize('version,operation', [('2021.1', 'object.create'), ('2025.1', 'object.set')])
def test_selected_targetless_action_uses_null_reference_and_verifies_it(tmp_path, version, operation):
    task = ActionCreateTask(tmp_path, version, operation)
    task.declare_action(targetless=True)
    tx, shown = preview(task)
    args = shown['artifact']['prepared_operation']['dispatch']['args']
    node = args if operation == 'object.create' else args['objects'][0]['children'][0]
    assert node['@ActionType'] == 3 and node['@Target'] is None
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, executed = task.run('execute', tx)
    assert code == 0, executed
    code, verified = task.run('verify', tx)
    assert code == 0 and verified['verified'] is True, json.dumps(verified, indent=2)


@pytest.mark.parametrize('outcomes', ['distinct', 'identical', 'reversed', 'overlapping'])
def test_two_new_actions_bind_distinct_occurrences_and_preserve_event_children(tmp_path, outcomes):
    task = ActionCreateTask(tmp_path, '2025.1', 'object.set')
    before = deepcopy(task.objects)
    task.declare_action()
    task.declare_action(targetless=outcomes in {'distinct', 'reversed'}, declaration_id='stop-all',
        notes='Only this occurrence has explicit notes' if outcomes == 'overlapping' else None)
    task.reverse_results = outcomes == 'reversed'
    tx, shown = preview(task)
    nodes = shown['artifact']['prepared_operation']['dispatch']['args']['objects'][0]['children']
    assert [(row['name'], row['@ActionType'], row['@Target']) for row in nodes] == [('', 1, TARGET), ('', 1, TARGET) if outcomes in {'identical', 'overlapping'} else ('', 3, None)]
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, executed = task.run('execute', tx)
    assert code == 0, executed
    code, verified = task.run('verify', tx)
    assert code == 0 and verified['verified'] is True, json.dumps(verified, indent=2)
    assert all(task.objects[key] == value for key, value in before.items())
    assert len(task.objects) == len(before) + 2


@pytest.mark.parametrize('fault', ['duplicate', 'missing', 'retained', 'target'])
def test_multiple_action_associations_cannot_hide_loss_aliasing_or_wrong_state(tmp_path, fault):
    task = ActionCreateTask(tmp_path, '2025.1', 'object.set')
    task.declare_action()
    task.declare_action(targetless=True, declaration_id='stop-all')
    tx, shown = preview(task)
    task.drop = fault
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, executed = task.run('execute', tx)
    assert code == 0, executed
    code, verified = task.run('verify', tx)
    assert code == 2 and verified.get('verified') is not True, verified


def test_new_event_can_own_two_selected_action_occurrences_in_create(tmp_path):
    task = ActionCreateTask(tmp_path, '2021.1')
    parent = task.bind(FIRST)
    kind = task.discover_kind('Event')
    code, event = task.step('draft-declare-new', '--declaration-id', 'event', '--parent-handle', parent,
        '--name', 'New Event', '--kind', kind)
    assert code == 0, event
    event_handle = event['draft']['declared_object']['result_handle']
    task.declare_action(parent_handle=event_handle)
    task.declare_action(targetless=True, declaration_id='stop-all', parent_handle=event_handle)
    original = task.call
    event_id = '{77777777-7777-7777-7777-777777777777}'
    def call(uri, args=None, options=None):
        if uri.endswith('object.create'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            event_path = task.objects[FIRST]['path'] + r'\New Event'
            task.objects[event_id] = {'id': event_id, 'name': 'New Event', 'type': 'Event', 'classId': 131088,
                'path': event_path, 'parent': {'id': FIRST}, 'notes': ''}
            children = []
            for index, node in enumerate(args['children']):
                identity = CREATED if index == 0 else '{66666666-6666-6666-6666-666666666666}'
                task.objects[identity] = {'id': identity, 'name': '', 'type': 'Action', 'classId': 327696,
                    'path': event_path + ('\\[Play - Rain]' if index == 0 else '\\[Stop All]'),
                    'parent': {'id': event_id}, 'notes': '', 'ActionType': node['@ActionType'],
                    'Target': {'id': node['@Target']} if node['@Target'] else None}
                children.append({'id': identity, 'name': ''})
            return {'id': event_id, 'name': 'New Event', 'children': children}
        return original(uri, args, options)
    task.call = call
    tx, shown = preview(task)
    nodes = shown['artifact']['prepared_operation']['dispatch']['args']['children']
    assert [node['name'] for node in nodes] == ['', '']
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, executed = task.run('execute', tx)
    assert code == 0, executed
    code, verified = task.run('verify', tx)
    assert code == 0 and verified['verified'] is True, json.dumps(verified, indent=2)
