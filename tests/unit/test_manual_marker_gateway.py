"""Exact modern anonymous Marker declarations through the public Gateway."""
from copy import deepcopy
import json
import re

import pytest

from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, FIRST, SECOND, ROOT, CHILD
from tests.unit.test_list_merge_existing_conditions_gateway import select_field

VERSIONS = ('2023.1', '2024.1', '2025.1')
MARKER = '{99999999-9999-9999-9999-999999999999}'


def marker_task(path, version='2025.1', *, fault=None):
    task = OwnedGraphTask(path, version, 'object.set')
    base = r'\Containers' if version == '2025.1' else r'\Actor-Mixer Hierarchy'
    task.types = [{'name': kind, 'classId': cid, 'type': 'WObject'} for kind, cid in
        [('WorkUnit', 1638416), ('Sound', 65552), ('AudioFileSource', 16), ('Marker', 5373968)]]
    task.objects = {
        ROOT: {'id': ROOT, 'name': 'Default Work Unit', 'type': 'WorkUnit', 'classId': 1638416,
            'path': base + r'\Default Work Unit', 'notes': 'Keep unit'},
        SECOND: {'id': SECOND, 'name': 'Sound', 'type': 'Sound', 'classId': 65552,
            'path': base + r'\Default Work Unit\Sound', 'parent': {'id': ROOT}, 'notes': 'Keep Sound', 'activeSource': {'id': FIRST}},
        FIRST: {'id': FIRST, 'name': 'Source', 'type': 'AudioFileSource', 'classId': 16,
            'path': base + r'\Default Work Unit\Sound\Source', 'parent': {'id': SECOND},
            'notes': 'Keep source', '@MarkerInputMode': 0, '@Markers': []},
    }
    task.metadata = {'MarkerInputMode': {'name': 'MarkerInputMode', 'type': 'int16', 'default': 0,
        'restriction': {'type': 'enum', 'values': [{'value': n} for n in (0, 1, 2)]}},
        'Time': {'name': 'Time', 'type': 'Real64', 'default': 0},
        'Label': {'name': 'Label', 'type': 'string', 'default': ''}}
    original = task.call; task.writes = []
    def native(uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri.endswith('getPropertyAndReferenceNames'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            marker_scope = args.get('classId') == 5373968 or task.objects.get(args.get('object'), {}).get('type') == 'Marker'
            return {'return': ['Time', 'Label'] if marker_scope else ['MarkerInputMode']}
        if uri.endswith('object.get') and (args.get('transform') == [{'select': ['@Markers']}] or args.get('waql', '').startswith('from object "')):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            if 'waql' in args:
                match = re.fullmatch(r'from object "([^"]+)"( select @Markers)? take ([12])', args['waql'])
                assert match, args
                rows = [row for row in task.objects.values() if match[1] in (row['id'], row['path'])]
                if match[2]: rows = [task.objects[member['id']] for row in rows for member in row['@Markers']]
                rows = rows[:int(match[3])]
            else:
                rows = [task.objects[identity] for identity in args['from']['id']]
                assert args['transform'] == [{'select': ['@Markers']}], args
                rows = [task.objects[member['id']] for row in rows for member in row['@Markers']]
            return {'return': task.project_rows(rows, options)}
        if uri.endswith('object.set'):
            task.calls.append((uri, deepcopy(args), deepcopy(options))); task.writes.append(deepcopy(args))
            row, = args['objects']; assert row['object'] == FIRST
            task.objects[FIRST]['@MarkerInputMode'] = row.get('@MarkerInputMode', task.objects[FIRST]['@MarkerInputMode'])
            node, = row['@Markers']
            assert node == {'type': 'Marker', 'name': '', '@Time': 0.0, '@Label': 'R90_MARKER'}
            task.objects[MARKER] = {'id': MARKER, 'name': '', 'type': 'Marker', 'classId': 5373968,
                'path': r'\opaque-marker', 'owner': {'id': FIRST}, 'notes': '', '@Time': 0.0, '@Label': 'R90_MARKER'}
            if args.get('listMode') == 'replaceAll': task.objects[FIRST]['@Markers'] = []
            task.objects[FIRST]['@Markers'].append({'id': MARKER})
            if fault == 'owner': task.objects[MARKER]['owner'] = {'id': SECOND}
            elif fault == 'class': task.objects[MARKER]['classId'] = 16
            elif fault == 'name': task.objects[MARKER]['name'] = 'Guessed name'
            elif fault == 'label': task.objects[MARKER]['@Label'] = 'Other'
            elif fault == 'time': task.objects[MARKER]['@Time'] = 1.0
            elif fault == 'membership': task.objects[FIRST]['@Markers'] = []
            elif fault == 'extra-member': task.objects[FIRST]['@Markers'].append({'id': SECOND})
            elif fault == 'mode': task.objects[FIRST]['@MarkerInputMode'] = 0
            elif fault == 'source-notes': task.objects[FIRST]['notes'] = 'Changed'
            return {'objects': [{'id': FIRST, 'name': task.objects[FIRST]['name'], '@Markers': [{'id': MARKER, 'name': ''}]}]}
        return original(uri, args, options)
    task.call = native
    return task


def declare_marker(task, *, fields=True):
    owner = task.bind(FIRST)
    mode = select_field(task, owner=owner, token='MarkerInputMode')
    code, changed = task.step('draft-declare-existing', '--declaration-id', 'source', '--object-handle', owner,
        '--field-value', mode, '2')
    assert code == 0, changed
    code, listed = task.step('draft-discover-fields', '--object-handle', owner, '--field-source', 'documented-lists', '--list')
    assert code == 0, listed
    field, = [row for row in listed['agent_result']['items'] if row['name'] == 'Markers']
    code, selected = task.step('draft-discover-fields', '--object-handle', owner, '--field-source', 'documented-lists', '--selection', field['selection'])
    assert code == 0, selected
    marker_list = selected['meaning_results'][0]['candidates'][0]['handle']
    code, found = task.step('draft-discover-types', '--role', 'object', '--meaning', 'Marker')
    assert code == 0, found
    kind, = found['type_candidates']; kind = kind['handle']
    if not fields:
        return task.step('draft-declare-new', '--declaration-id', 'marker', '--parent-handle', owner, '--kind', kind,
            '--field', 'object_list', marker_list)
    time = select_field(task, kind=kind, token='Time'); label = select_field(task, kind=kind, token='Label')
    return task.step('draft-declare-new', '--declaration-id', 'marker', '--parent-handle', owner, '--kind', kind,
        '--field', 'object_list', marker_list, '--field-value', time, '0', '--field-value', label, 'R90_MARKER')


@pytest.mark.parametrize('version', VERSIONS)
def test_manual_marker_closed_declaration_verifies_exact_wobject_without_new_media(tmp_path, version):
    task = marker_task(tmp_path, version)
    before = deepcopy(task.objects)
    code, declared = declare_marker(task)
    assert code == 0, declared
    tx, shown = task.preview()
    args = shown['artifact']['prepared_operation']['dispatch']['args']
    assert args['objects'] == [{'object': FIRST, '@MarkerInputMode': 2, '@Markers': [
        {'type': 'Marker', 'name': '', '@Time': 0.0, '@Label': 'R90_MARKER'}]}]
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert len(task.writes) == 1
    assert task.objects[SECOND] == before[SECOND] and task.objects[ROOT] == before[ROOT]
    assert task.objects[FIRST] == {**before[FIRST], '@MarkerInputMode': 2, '@Markers': [{'id': MARKER}]}
    assert task.objects[MARKER]['owner'] == {'id': FIRST} and task.objects[MARKER]['name'] == ''


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('fault', ['owner', 'class', 'name', 'label', 'time', 'membership', 'extra-member', 'mode', 'source-notes'])
def test_manual_marker_verifier_rejects_wrong_identity_field_or_membership_without_replay(tmp_path, version, fault):
    task = marker_task(tmp_path, version, fault=fault)
    code, declared = declare_marker(task); assert code == 0, declared
    tx, shown = task.preview()
    code, result = task.finish(tx, shown)
    assert code == 2 and result.get('verified') is not True, result
    code, repeated = task.run('execute', tx)
    assert code == 2, repeated
    assert len(task.writes) == 1


@pytest.mark.parametrize('version', ['2021.1', '2022.1'])
def test_older_inner_marker_is_not_admitted_as_modern_anonymous_wobject(tmp_path, version):
    if version == '2021.1':
        from tests.unit.test_object_graph_business_gateway import gateway
        config = tmp_path / 'config.json'
        config.write_text(json.dumps({'wwise_version': version, 'waapi_host': '127.0.0.1', 'waapi_port': 31337,
            'project_modification_policy': 'ask_before_changes'}))
        code, result = gateway.execute_gateway(['--state-dir', str(tmp_path / 'state'), 'draft-start', 'object.set'],
            env={'WAAPI_SKILL_CONFIG_PATH': str(config)})
        assert code == 2 and result['error_code'] == 'UNAVAILABLE_IN_VERSION', result
        return
    task = marker_task(tmp_path, version)
    task.types[-1].update(classId=65077248, type='Inner')
    owner = task.bind(FIRST)
    code, result = task.step('draft-discover-fields', '--object-handle', owner, '--field-source', 'documented-lists', '--list')
    assert code == 0 and not any(row['name'] == 'Markers' for row in result['agent_result']['items']), result
    code, found = task.step('draft-discover-types', '--role', 'object', '--meaning', 'Marker'); assert code == 0, found
    kind, = found['type_candidates']
    code, result = task.step('draft-declare-new', '--declaration-id', 'marker', '--parent-handle', owner,
        '--kind', kind['handle'], '--field', 'object_list', 'Markers')
    assert code == 2, result
    assert task.writes == []


@pytest.mark.parametrize('version', VERSIONS)
def test_manual_marker_schema_and_draft_continuation_disclose_exact_matching_profile(tmp_path, version):
    task = marker_task(tmp_path, version)
    code, schema = task.run('operation-schema', 'object.set'); assert code == 0, schema
    def profile(value):
        if isinstance(value, dict):
            if 'anonymous_list_member' in value: return value['anonymous_list_member']
            for child in value.values():
                found = profile(child)
                if found is not None: return found
        if isinstance(value, list):
            for child in value:
                found = profile(child)
                if found is not None: return found
    contract = profile(schema)
    marker = contract['profiles']['manual_marker']
    assert (marker['version'], marker['owner_class_id'], marker['collection'], marker['element_class_id']) == (version, 16, 'Markers', 5373968)
    assert marker['native_name'] == '' and marker['element_type'] == 'Marker'
    assert marker['source']['member'] == 'ak_wwise_core_object_set_example_adding_a_marker_to_an_audio_source.html'
    assert contract['on_name_conflict']['supported'] == ['fail']
    assert contract['on_name_conflict']['pending_source_native_proof'] == ['rename', 'merge', 'replace']
    task.bind(FIRST)
    code, result = task.step('draft-discover-types', '--role', 'object', '--meaning', 'Marker'); assert code == 0, result
    continuation = result['draft']['next_action_binding']['declare_new']['anonymous_list_member']
    assert continuation['semantics']['profiles']['manual_marker'] == marker
    assert '--name' not in continuation['append']


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('fault', ['owner-class', 'member-class', 'time-field-kind'])
def test_manual_marker_constructor_requires_exact_owner_member_and_field_scope(tmp_path, version, fault):
    task = marker_task(tmp_path, version)
    if fault == 'owner-class':
        task.objects[FIRST]['classId'] = 65552
        owner = task.bind(FIRST)
        code, result = task.step('draft-discover-fields', '--object-handle', owner, '--field-source', 'documented-lists', '--list')
        assert code == 0 and not any(row['name'] == 'Markers' for row in result['agent_result']['items']), result
    else:
        if fault == 'member-class': task.types[-1]['classId'] = 16
        else: task.metadata['Time']['type'] = 'bool'
        code, result = declare_marker(task, fields=fault != 'member-class')
        assert code == 2, result
    assert task.writes == []


def test_manual_marker_append_preserves_existing_member_values_and_identity(tmp_path):
    task = marker_task(tmp_path)
    task.objects[CHILD] = {'id': CHILD, 'name': '', 'type': 'Marker', 'classId': 5373968,
        'path': r'\older-opaque-marker', 'owner': {'id': FIRST}, 'notes': 'Retain marker', '@Time': 0.02, '@Label': 'Retained'}
    task.objects[FIRST]['@Markers'] = [{'id': CHILD}]
    before = deepcopy(task.objects[CHILD])
    code, result = declare_marker(task); assert code == 0, result
    tx, shown = task.preview(); code, result = task.finish(tx, shown)
    assert code == 0 and result['verified'] is True, result
    assert task.objects[CHILD] == before and task.objects[FIRST]['@Markers'] == [{'id': CHILD}, {'id': MARKER}]


def test_manual_marker_owner_class_cannot_substitute_another_actual_object_type(tmp_path):
    task = marker_task(tmp_path)
    task.objects[FIRST]['type'] = 'Sound'
    code, result = declare_marker(task); assert code == 0, result
    code, result = task.step('draft-check')
    assert code == 2 and task.writes == [], result
