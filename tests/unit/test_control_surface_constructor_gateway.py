"""Control Surface roles use typed graphs and persisted public transactions."""
from copy import deepcopy
import json

import pytest

from tests.unit.test_field_interface_closure_gateway import FIRST, SECOND, VERSIONS
from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, ROOT, CHILD

GROUP_CLASS = 4456464
BINDING_CLASS = 4390928
SESSION_CLASS = 4325392


class SurfaceTask(OwnedGraphTask):
    def __init__(self, path, version='2025.1', operation='object.create', role=3):
        super().__init__(path, version, operation)
        self.types = [{'name': name, 'classId': class_id, 'type': 'WObject'} for name, class_id in (
            ('ControlSurfaceSession', SESSION_CLASS), ('ControlSurfaceBindingGroup', GROUP_CLASS),
            ('ControlSurfaceBinding', BINDING_CLASS), ('WorkUnit', 1638416))]
        self.creation_classes.update({row['name']: row['classId'] for row in self.types})
        self.objects = {
            SECOND: {'id': SECOND, 'name': 'Session', 'type': 'ControlSurfaceSession', 'classId': SESSION_CLASS,
                'path': r'\Control Surface Sessions\Default Work Unit\Session', 'notes': 'Keep session'},
            FIRST: {'id': FIRST, 'name': 'View Groups', 'type': 'ControlSurfaceBindingGroup', 'classId': GROUP_CLASS,
                'path': r'\Control Surface Sessions\Default Work Unit\Session\View Groups', 'parent': {'id': SECOND},
                'notes': 'Keep selected parent', '@GroupType': role},
        }
        self.metadata = {
            'GroupType': {'name': 'GroupType', 'type': 'int16', 'default': 0, 'restriction': {'type': 'enum', 'values': [
                {'value': 0, 'displayName': 'Global'}, {'value': 2, 'displayName': 'User Binding Group'},
                {'value': 3, 'displayName': 'User Binding Group Root'}, {'value': 4, 'displayName': 'Current Selection'}]}},
            'ObjectIndexInView': {'name': 'ObjectIndexInView', 'type': 'int32', 'default': 1,
                'restriction': {'type': 'range', 'min': 1, 'max': 128}},
            'HardwareControllerKey': {'name': 'HardwareControllerKey', 'type': 'string', 'default': ''},
        }

    def _create(self, node, parent, *, owned=False):
        # Native constructor notes apply only to new occurrences. The general
        # fixture also models explicit existing-field edits; keep this exact
        # source-owned constructor behavior at the external Wwise boundary.
        if self.conflict == 'merge' and any(row.get('parent') == {'id': parent}
                and row['name'] == node['name'] for row in self.objects.values()):
            node = {key: value for key, value in node.items() if key != 'notes'}
        return super()._create(node, parent, owned=owned)

    def kind(self, meaning):
        code, found = self.step('draft-discover-types', '--role', 'object', '--meaning', meaning)
        assert code == 0, found
        return found['type_candidates'][0]['handle']

    def field(self, kind, meaning):
        code, selected = self.step('draft-discover-fields', '--type-handle', kind, '--meaning', meaning)
        assert code == 0, selected
        return selected['meaning_results'][0]['candidates'][0]['handle']

    def group(self, role=2, parent=None, name='Layers'):
        parent = self.bind(FIRST) if parent is None else parent
        kind = self.kind('ControlSurfaceBindingGroup')
        fields = [] if role is None else ['--field-value', self.field(kind, 'GroupType'), str(role)]
        return self.step('draft-declare-new', '--declaration-id', 'group', '--parent-handle', parent,
            '--name', name, '--kind', kind, *fields)


def test_user_group_creation_preserves_selected_root_and_verifies_once(tmp_path):
    task = SurfaceTask(tmp_path)
    before = deepcopy(task.objects)
    code, declared = task.group()
    assert code == 0, declared
    tx, shown = task.preview()
    assert task.objects == before
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert task.objects[FIRST] == before[FIRST] and task.objects[SECOND] == before[SECOND]
    assert task.objects[ROOT]['@GroupType'] == 2
    assert task.objects[ROOT]['parent'] == {'id': FIRST}
    code, repeated = task.run('execute', tx)
    assert code == 2, repeated
    assert len([uri for uri, _, _ in task.calls if uri.endswith('object.create')]) == 1


@pytest.mark.parametrize('role,parent_role', [(None, 3), (0, 3), (3, 3), (4, 3), (2, 4)])
def test_user_group_requires_explicit_user_role_under_selected_user_root(tmp_path, role, parent_role):
    task = SurfaceTask(tmp_path, role=parent_role)
    code, result = task.group(role)
    if code == 0:
        code, result = task.step('draft-check')
    assert code == 2 and 'CONTROL_SURFACE_ROLE_BOUNDARY' in json.dumps(result), result
    assert not any(uri.endswith('object.create') for uri, _, _ in task.calls)


def test_user_group_with_binding_uses_live_fields_and_retains_unrequested_peers(tmp_path):
    task = SurfaceTask(tmp_path, '2022.1', 'object.set')
    task.objects['{55555555-5555-5555-5555-555555555555}'] = {
        'id': '{55555555-5555-5555-5555-555555555555}', 'name': 'Existing',
        'type': 'ControlSurfaceBindingGroup', 'classId': GROUP_CLASS, 'parent': {'id': FIRST},
        'path': task.objects[FIRST]['path'] + r'\Existing', 'notes': 'Keep peer', '@GroupType': 2}
    before = deepcopy(task.objects)
    code, declared = task.group()
    assert code == 0, declared
    group = declared['draft']['declared_object']['result_handle']
    kind = task.kind('ControlSurfaceBinding')
    code, declared = task.step('draft-declare-new', '--declaration-id', 'binding', '--parent-handle', group,
        '--name', 'Binding', '--kind', kind,
        '--field-value', task.field(kind, 'ObjectIndexInView'), '7',
        '--field-value', task.field(kind, 'HardwareControllerKey'), 'user supplied existing assignment')
    assert code == 0, declared
    tx, shown = task.preview()
    assert task.objects == before
    assert any('Hardware' in warning for warning in shown['artifact']['prepared_operation']['warnings'])
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert all(task.objects[key] == row for key, row in before.items())
    assert task.objects[CHILD]['@ObjectIndexInView'] == 7
    assert task.objects[CHILD]['@HardwareControllerKey'] == 'user supplied existing assignment'
    assert task.objects[CHILD]['parent'] == {'id': ROOT}
    code, repeated = task.run('execute', tx)
    assert code == 2, repeated
    assert len([uri for uri, _, _ in task.calls if uri.endswith('object.set')]) == 1


@pytest.mark.parametrize('fault', ['parent-role', 'parent-class', 'selected-class', 'group-metadata', 'source', 'config'])
def test_constructor_preview_binds_parent_role_class_metadata_source_and_config(tmp_path, monkeypatch, fault):
    task = SurfaceTask(tmp_path)
    code, declared = task.group()
    assert code == 0, declared
    tx, shown = task.preview()
    if fault == 'parent-role': task.objects[FIRST]['@GroupType'] = 4
    elif fault == 'parent-class': task.objects[FIRST]['classId'] = BINDING_CLASS
    elif fault == 'selected-class': task.types[1]['classId'] = BINDING_CLASS
    elif fault == 'group-metadata': task.metadata['GroupType']['default'] = 2
    elif fault == 'source':
        from wwise_waapi import control_surface_construction
        changed = tmp_path / 'changed.json'
        changed.write_text('{}')
        monkeypatch.setattr(control_surface_construction, 'SOURCE', changed)
    else:
        config = tmp_path / 'config.json'
        data = json.loads(config.read_text())
        data['waapi_port'] = 31338
        config.write_text(json.dumps(data))
    code, result = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    if code == 0:
        code, result = task.run('execute', tx)
    assert code == 2, result
    assert not any(uri.endswith('object.create') for uri, _, _ in task.calls)


@pytest.mark.parametrize('fault', ['parent-role', 'created-role', 'created-class', 'parent-edge', 'result-name', 'actual-name', 'peer'])
def test_constructor_independent_state_and_result_faults_fail_without_retry(tmp_path, fault):
    task = SurfaceTask(tmp_path)
    peer = '{55555555-5555-5555-5555-555555555555}'
    task.objects[peer] = {'id': peer, 'name': 'Retained', 'type': 'ControlSurfaceBindingGroup',
        'classId': GROUP_CLASS, 'path': task.objects[FIRST]['path'] + r'\Retained',
        'parent': {'id': FIRST}, 'notes': 'Keep peer', '@GroupType': 2}
    code, declared = task.group()
    assert code == 0, declared
    original = task.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('object.create'):
            if fault == 'parent-role': task.objects[FIRST]['@GroupType'] = 4
            elif fault == 'created-role': task.objects[ROOT]['@GroupType'] = 0
            elif fault == 'created-class': task.objects[ROOT]['classId'] = BINDING_CLASS
            elif fault == 'parent-edge': task.objects[ROOT]['parent'] = {'id': SECOND}
            elif fault == 'result-name': result['name'] = 'Not the stored name'
            elif fault == 'actual-name': task.objects[ROOT]['name'] = 'Native derived label'
            elif fault == 'peer': task.objects[peer]['notes'] = 'Unexpected change'
        return result
    task.call = call
    tx, shown = task.preview()
    code, result = task.finish(tx, shown)
    assert code == 2 and result.get('verified') is not True, result
    code, result = task.run('execute', tx)
    assert code == 2, result
    assert len([uri for uri, _, _ in task.calls if uri.endswith('object.create')]) == 1


@pytest.mark.parametrize('version', VERSIONS)
def test_five_version_definitions_disclose_source_roles_and_precise_boundaries(tmp_path, version):
    import base64
    import gzip
    import hashlib
    from pathlib import Path
    import xml.etree.ElementTree as ET
    from wwise_waapi.control_surface_construction import authority
    root = Path(__file__).parents[2]
    source = authority(version)
    original = json.loads(gzip.decompress((root / 'tests/fixtures/metadata-conditions/self-scalar-source-parents.json.gz').read_bytes()))
    record = original['files'][source['xml_source']]
    raw = base64.b64decode(record['bytes_base64'], validate=True)
    assert hashlib.sha256(raw).hexdigest() == source['xml_sha256'] == record['sha256']
    tree = ET.fromstring(raw)
    for name, declaration in source['declarations'].items():
        node, = [node for node in tree if node.get('Name') == name]
        assert ET.tostring(node, encoding='unicode') == declaration
    roles = {node.get('DisplayName'): int(node.text) for node in tree.findall(
        './WwiseObject[@Name="ControlSurfaceBindingGroup"]/Properties/Property[@Name="GroupType"]/Restrictions/ValueRestriction/Enumeration/Value')}
    assert roles == {'Global': 0, 'User Binding Group': 2, 'User Binding Group Root': 3, 'Current Selection': 4}
    assert source['classes'] == {'ControlSurfaceSession': SESSION_CLASS, 'ControlSurfaceBindingGroup': GROUP_CLASS, 'ControlSurfaceBinding': BINDING_CLASS}
    task = SurfaceTask(tmp_path, version)
    code, schema = task.run('operation-schema', 'object.create')
    assert code == 0, schema
    encoded = json.dumps(schema)
    assert 'explicit_class_GroupType_Field_Handle_choice_User_Binding_Group_2' in encoded
    assert 'automatic_birth_not_claimed' in encoded
    assert 'hardware_effect_not_claimed' in encoded


@pytest.mark.parametrize('role', [0, 4])
def test_selected_global_and_current_selection_groups_admit_binding_configuration(tmp_path, role):
    task = SurfaceTask(tmp_path, role=role)
    parent = task.bind(FIRST)
    kind = task.kind('ControlSurfaceBinding')
    code, result = task.step('draft-declare-new', '--declaration-id', 'binding', '--parent-handle', parent,
        '--name', 'Binding', '--kind', kind, '--field-value', task.field(kind, 'ObjectIndexInView'), '8')
    assert code == 0, result
    code, result = task.step('draft-check')
    assert code == 0, result
    assert not any(uri.endswith('object.create') for uri, _, _ in task.calls)


@pytest.mark.parametrize('fault', ['wrong-parent-class', 'wrong-child-class', 'session-parent', 'root-binding', 'empty-name', 'path-name', 'field-range'])
def test_constructor_rejects_unproved_class_placement_and_name_before_write(tmp_path, fault):
    task = SurfaceTask(tmp_path)
    if fault == 'wrong-parent-class': task.objects[FIRST]['classId'] = 17
    if fault == 'wrong-child-class': task.types[1]['classId'] = 17
    parent = task.bind(SECOND if fault == 'session-parent' else FIRST)
    if fault in ('root-binding', 'field-range'):
        kind = task.kind('ControlSurfaceBinding')
        code, result = task.step('draft-declare-new', '--declaration-id', 'binding', '--parent-handle', parent,
            '--name', 'Binding', '--kind', kind,
            *(['--field-value', task.field(kind, 'ObjectIndexInView'), '129'] if fault == 'field-range' else []))
    else:
        code, result = task.group(parent=parent, name='' if fault == 'empty-name' else 'A\\B' if fault == 'path-name' else 'Layers')
    if code == 0:
        code, result = task.step('draft-check')
    assert code == 2, result
    assert not any(uri.endswith('object.create') for uri, _, _ in task.calls)


def test_rename_conflict_uses_actual_native_name_without_guessing_a_prefix(tmp_path):
    task = SurfaceTask(tmp_path)
    task.bind(FIRST)
    code, configured = task.step('draft-business-configure', '--name-conflict', 'rename')
    assert code == 0, json.dumps(configured)
    code, declared = task.group()
    assert code == 0, declared
    original = task.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('object.create'):
            task.objects[ROOT].update(name='Native User Group 6', path=task.objects[FIRST]['path'] + r'\Native User Group 6')
            result['name'] = 'Native User Group 6'
        return result
    task.call = call
    tx, shown = task.preview()
    code, result = task.finish(tx, shown)
    assert code == 0 and result['verified'] is True, json.dumps([check for check in result.get('verification', {}).get('assertions', []) if not check.get('passed')])
    assert task.objects[ROOT]['name'] == 'Native User Group 6'


@pytest.mark.parametrize('conflict', ['merge', 'replace'])
def test_constructor_conflicts_cannot_convert_or_replace_a_reserved_group(tmp_path, conflict):
    task = SurfaceTask(tmp_path)
    task.objects[ROOT] = {'id': ROOT, 'name': 'Layers', 'type': 'ControlSurfaceBindingGroup',
        'classId': GROUP_CLASS, 'parent': {'id': FIRST}, 'path': task.objects[FIRST]['path'] + r'\Layers',
        'notes': 'Reserved role remains', '@GroupType': 0}
    owner = task.bind(FIRST)
    code, result = task.step('draft-business-configure', '--name-conflict', conflict,
        *(['--replace-owner-handle', owner] if conflict == 'replace' else []))
    assert code == 0, result
    code, result = task.group(parent=owner)
    assert code == 0, result
    code, result = task.step('draft-check')
    assert code == 2 and 'CONTROL_SURFACE_ROLE_BOUNDARY' in json.dumps(result), result
    assert not any(uri.endswith('object.create') for uri, _, _ in task.calls)


def test_set_rename_binds_actual_native_name_before_independent_verification(tmp_path):
    task = SurfaceTask(tmp_path, '2022.1', 'object.set')
    owner = task.bind(FIRST)
    code, configured = task.step('draft-business-configure', '--name-conflict', 'rename')
    assert code == 0, configured
    code, declared = task.group(parent=owner)
    assert code == 0, declared
    original = task.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('object.set'):
            task.objects[ROOT].update(name='Native User Group 6', path=task.objects[FIRST]['path'] + r'\Native User Group 6')
            result['objects'][0]['children'][0]['name'] = 'Native User Group 6'
        return result
    task.call = call
    tx, shown = task.preview()
    code, result = task.finish(tx, shown)
    assert code == 0 and result['verified'] is True, json.dumps(result)
    assert task.objects[ROOT]['name'] == 'Native User Group 6'


def test_constructor_cannot_seal_an_incomplete_peer_projection(tmp_path):
    task = SurfaceTask(tmp_path)
    peer = '{55555555-5555-5555-5555-555555555555}'
    # Both reads omit evidence rather than mutating a known value afterward.
    task.objects[peer] = {'id': peer, 'name': 'Retained', 'type': 'ControlSurfaceBindingGroup',
        'path': task.objects[FIRST]['path'] + r'\Retained', 'parent': {'id': FIRST}, '@GroupType': 2}
    code, result = task.group()
    assert code == 0, result
    code, result = task.step('draft-check')
    assert code == 2 and 'CONTROL_SURFACE' in json.dumps(result), result
    assert not any(uri.endswith('object.create') for uri, _, _ in task.calls)


@pytest.mark.parametrize('operation', ['object.create', 'object.set'])
def test_rename_cannot_report_an_unchanged_existing_peer_as_new(tmp_path, operation):
    task = SurfaceTask(tmp_path, '2022.1', operation)
    peer = '{55555555-5555-5555-5555-555555555555}'
    task.objects[peer] = {'id': peer, 'name': 'Retained', 'type': 'ControlSurfaceBindingGroup',
        'classId': GROUP_CLASS, 'path': task.objects[FIRST]['path'] + r'\Retained',
        'parent': {'id': FIRST}, 'notes': '', '@GroupType': 2}
    before = deepcopy(task.objects)
    owner = task.bind(FIRST)
    code, configured = task.step('draft-business-configure', '--name-conflict', 'rename')
    assert code == 0, configured
    code, declared = task.group(parent=owner)
    assert code == 0, declared
    original = task.call
    def call(uri, args=None, options=None):
        if uri == 'ak.wwise.core.' + operation:
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            occurrence = {'id': peer, 'name': 'Retained'}
            return occurrence if operation == 'object.create' else {'objects': [
                {'id': FIRST, 'name': task.objects[FIRST]['name'], 'children': [occurrence]}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    code, result = task.finish(tx, shown)
    assert code == 2 and result.get('verified') is not True, result
    assert task.objects == before
    code, result = task.run('execute', tx)
    assert code == 2, result
    assert len([uri for uri, _, _ in task.calls if uri == 'ak.wwise.core.' + operation]) == 1


def test_genuine_merge_retains_bound_guid_notes_and_empty_notes_peer(tmp_path):
    task = SurfaceTask(tmp_path, '2022.1', 'object.set')
    peer = '{55555555-5555-5555-5555-555555555555}'
    task.objects[ROOT] = {'id': ROOT, 'name': 'Layers', 'type': 'ControlSurfaceBindingGroup',
        'classId': GROUP_CLASS, 'path': task.objects[FIRST]['path'] + r'\Layers',
        'parent': {'id': FIRST}, 'notes': 'Keep existing group notes', '@GroupType': 2}
    task.objects[peer] = {'id': peer, 'name': 'Retained', 'type': 'ControlSurfaceBinding',
        'classId': BINDING_CLASS, 'path': task.objects[ROOT]['path'] + r'\Retained',
        'parent': {'id': ROOT}, 'notes': ''}
    before = deepcopy(task.objects)
    owner = task.bind(FIRST)
    code, result = task.step('draft-business-configure', '--name-conflict', 'merge')
    assert code == 0, result
    kind = task.kind('ControlSurfaceBindingGroup')
    code, result = task.step('draft-declare-new', '--declaration-id', 'group', '--parent-handle', owner,
        '--name', 'Layers', '--kind', kind, '--field', 'notes', 'Constructor notes apply only to new groups',
        '--field-value', task.field(kind, 'GroupType'), '2')
    assert code == 0, result
    merged_group = result['draft']['declared_object']['result_handle']
    kind = task.kind('ControlSurfaceBinding')
    code, result = task.step('draft-declare-new', '--declaration-id', 'binding', '--parent-handle', merged_group,
        '--name', 'Binding', '--kind', kind)
    assert code == 0, result
    tx, shown = task.preview()
    code, result = task.finish(tx, shown)
    assert code == 0 and result['verified'] is True, json.dumps([check for check in result.get('verification', {}).get('assertions', []) if not check.get('passed')])
    assert all(task.objects[key] == row for key, row in before.items())
    assert task.objects[CHILD]['parent'] == {'id': ROOT}
