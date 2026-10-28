"""Exact modern anonymous Marker declarations through the public Gateway."""
from copy import deepcopy
import json
import re

import pytest

from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, FIRST, SECOND, ROOT, CHILD
from tests.unit.test_list_merge_existing_conditions_gateway import select_field

VERSIONS = ('2023.1', '2024.1', '2025.1')
MARKER = '{99999999-9999-9999-9999-999999999999}'
UNTOUCHED_MARKER = '{88888888-8888-8888-8888-888888888888}'


def marker_task(path, version='2025.1', *, fault=None, omit_empty_markers=False):
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
            if args.get('listMode') == 'replaceAll':
                for member in task.objects[FIRST]['@Markers']: del task.objects[member['id']]
                task.objects[FIRST]['@Markers'] = []
            task.objects[MARKER] = {'id': MARKER, 'name': '', 'type': 'Marker', 'classId': 5373968,
                'path': '[Marker]' if version == '2025.1' else r'\opaque-marker',
                'owner': {'id': FIRST}, 'notes': '', '@Time': 0.0, '@Label': 'R90_MARKER'}
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
        result = original(uri, args, options)
        if omit_empty_markers and uri.endswith('object.get'):
            for row in result.get('return', []):
                if row.get('@Markers') == []:
                    row.pop('@Markers')
        return result
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
    assert contract['on_name_conflict']['supported'] == ['fail', 'rename', 'merge', 'replace']
    assert contract['on_name_conflict']['list_modes'] == ['append', 'replaceAll']
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


@pytest.mark.parametrize('version,conflict,list_mode', [('2023.1', 'merge', 'append'), ('2024.1', 'replace', 'replace-all'), ('2025.1', 'rename', 'append')])
@pytest.mark.parametrize('fault', [None, 'class'])
def test_manual_marker_name_policies_share_source_proven_list_population(tmp_path, version, conflict, list_mode, fault):
    task = marker_task(tmp_path, version, fault=fault)
    task.objects[CHILD] = {'id': CHILD, 'name': '', 'type': 'Marker', 'classId': 5373968,
        'path': r'\older-opaque-marker', 'owner': {'id': FIRST}, 'notes': 'Retain marker', '@Time': 0.02, '@Label': 'Retained'}
    task.objects[FIRST]['@Markers'] = [{'id': CHILD}]
    before = deepcopy(task.objects[CHILD])
    code, result = declare_marker(task); assert code == 0, result
    code, result = task.step('draft-business-configure', '--name-conflict', conflict, '--list-behavior', list_mode)
    assert code == 0, result
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == (2 if fault else 0), verified
    assert len(task.writes) == 1 and task.writes[0]['onNameConflict'] == conflict
    if list_mode == 'append': assert task.objects[CHILD] == before
    else: assert CHILD not in task.objects
    if fault:
        code, rejected = task.run('execute', tx)
        assert code == 2 and len(task.writes) == 1, rejected


def test_manual_marker_owner_class_cannot_substitute_another_actual_object_type(tmp_path):
    task = marker_task(tmp_path)
    task.objects[FIRST]['type'] = 'Sound'
    code, result = declare_marker(task); assert code == 0, result
    code, result = task.step('draft-check')
    assert code == 2 and task.writes == [], result


def retained_marker_task(path, version='2025.1'):
    task = marker_task(path, version)
    task.objects[MARKER] = {'id': MARKER, 'name': '', 'type': 'Marker', 'classId': 5373968,
        'path': '[Marker]' if version == '2025.1' else r'\opaque-retained-marker',
        'owner': {'id': FIRST}, 'notes': '', '@Time': 0.0, '@Label': 'Retained'}
    task.objects[FIRST].update({'@MarkerInputMode': 2, '@Markers': [{'id': MARKER}]})
    return task


@pytest.mark.parametrize('version', VERSIONS)
def test_retained_marker_binds_discovers_reads_and_prepares_exact_guid_edit_without_execution(tmp_path, version):
    task = retained_marker_task(tmp_path, version)
    before = deepcopy(task.objects)
    handle = task.bind(MARKER)
    time = select_field(task, owner=handle, token='Time')
    label = select_field(task, owner=handle, token='Label')
    assert time != label
    code, result = task.run('query-object', '--exact-id', MARKER, '--max-results', '1', '--include-field', 'Time', '--include-field', 'Label')
    assert code == 0 and result['agent_result'][0]['properties'] == {'Time': 0.0, 'Label': 'Retained'}, result
    code, result = task.step('draft-declare-existing', '--declaration-id', 'edit', '--object-handle', handle,
        '--field-value', label, 'R90_PREPARED_ONLY')
    assert code == 0, result
    tx, shown = task.preview()
    assert shown['artifact']['prepared_operation']['dispatch']['args']['objects'] == [{'object': MARKER, '@Label': 'R90_PREPARED_ONLY'}]
    assert task.objects == before and task.writes == []
    code, result = task.run('execute', tx)
    assert code == 2 and task.writes == [], result


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('fault', ['missing-membership', 'wrong-owner', 'wrong-class', 'wrong-type', 'wrong-owner-class', 'wrong-owner-type'])
def test_retained_marker_empty_name_requires_exact_live_owning_source_and_membership(tmp_path, version, fault):
    task = retained_marker_task(tmp_path, version)
    if fault == 'missing-membership': task.objects[FIRST]['@Markers'] = []
    elif fault == 'wrong-owner': task.objects[MARKER]['owner'] = {'id': SECOND}
    elif fault == 'wrong-class': task.objects[MARKER]['classId'] = 16
    elif fault == 'wrong-type': task.objects[MARKER]['type'] = 'PluginInnerObject'
    elif fault == 'wrong-owner-class': task.objects[FIRST]['classId'] = 65552
    else: task.objects[FIRST]['type'] = 'Sound'
    before = deepcopy(task.objects)
    code, result = task.step('draft-bind-object', '--object-id', MARKER)
    assert code == 2 and task.writes == [] and task.objects == before, result


@pytest.mark.parametrize('fault', ['owner', 'class', 'name', 'prefix'])
def test_retained_marker_binding_revalidates_actual_guid_and_complete_fresh_prefix_before_edit(tmp_path, fault):
    task = retained_marker_task(tmp_path)
    handle = task.bind(MARKER)
    label = select_field(task, owner=handle, token='Label')
    code, result = task.step('draft-declare-existing', '--declaration-id', 'edit', '--object-handle', handle,
        '--field-value', label, 'R90_PREPARED_ONLY'); assert code == 0, result
    if fault == 'owner': task.objects[MARKER]['owner'] = {'id': SECOND}
    elif fault == 'class': task.objects[MARKER]['classId'] = 16
    elif fault == 'name': task.objects[MARKER]['name'] = 'Changed after binding'
    else:
        task.objects[CHILD] = {'id': CHILD, 'name': '', 'type': 'Marker', 'classId': 5373968,
            'path': r'\another-retained-marker', 'owner': {'id': FIRST}, 'notes': '', '@Time': 0.02, '@Label': 'Another'}
        task.objects[FIRST]['@Markers'].append({'id': CHILD})
    code, result = task.step('draft-check')
    assert code == 2 and task.writes == [], result


@pytest.mark.parametrize('version', VERSIONS)
def test_omitted_empty_marker_projection_uses_fresh_source_bound_proof_through_public_transaction(tmp_path, version):
    task = marker_task(tmp_path, version, omit_empty_markers=True)
    code, result = declare_marker(task); assert code == 0, result
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert len(task.writes) == 1 and task.objects[FIRST]['@Markers'] == [{'id': MARKER}]
    proofs = [args for uri, args, options in task.calls if uri.endswith('object.get')
        and args == {'waql': f'from object "{FIRST}" select @Markers take 1'} and options == {'return': ['id']}]
    assert len(proofs) >= 3, 'Preparation and execution must independently prove the still-empty List'


@pytest.mark.parametrize('fault', ['hidden-member', 'malformed-proof', 'extra-proof-field', 'native-error', 'owner-extra-field', 'owner-type', 'owner-class'])
def test_omitted_marker_projection_is_not_empty_without_exact_source_and_independent_read(tmp_path, fault):
    task = marker_task(tmp_path, omit_empty_markers=True)
    code, result = declare_marker(task); assert code == 0, result
    if fault == 'hidden-member':
        task.objects[CHILD] = {'id': CHILD, 'name': '', 'type': 'Marker', 'classId': 5373968,
            'path': r'\hidden-marker', 'owner': {'id': FIRST}, '@Time': 0.02, '@Label': 'Retain'}
        task.objects[FIRST]['@Markers'] = [{'id': CHILD}]
    elif fault == 'owner-type': task.objects[FIRST]['type'] = 'Sound'
    elif fault == 'owner-class': task.objects[FIRST]['classId'] = 65552
    original = task.call
    def native(uri, args=None, options=None):
        if uri.endswith('object.get') and args == {'waql': f'from object "{FIRST}" select @Markers take 1'}:
            if fault == 'malformed-proof': return {'return': None}
            if fault == 'extra-proof-field': return {'return': [], 'extra': True}
            if fault == 'native-error': raise RuntimeError('independent empty proof failed')
        result = original(uri, args, options)
        if uri.endswith('object.get') and options == {'return': ['id', '@Markers']}:
            for row in result['return']:
                row.pop('@Markers', None)
                if fault == 'owner-extra-field': row['unexpected'] = True
        return result
    task.call = native
    code, rejected = task.step('draft-check')
    assert code == 2 and task.writes == [], rejected


@pytest.mark.parametrize('stage', ['execute', 'verify'])
def test_omitted_marker_projection_is_rechecked_at_prewrite_and_verification_without_reexecution(tmp_path, stage):
    task = marker_task(tmp_path, omit_empty_markers=True)
    code, result = declare_marker(task); assert code == 0, result
    tx, shown = task.preview()
    code, result = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token']); assert code == 0, result
    if stage == 'verify':
        code, result = task.run('execute', tx); assert code == 0 and len(task.writes) == 1, result
    task.objects[CHILD] = {'id': CHILD, 'name': '', 'type': 'Marker', 'classId': 5373968,
        'path': r'\late-marker', 'owner': {'id': FIRST}, '@Time': 0.02, '@Label': 'Late member'}
    task.objects[FIRST]['@Markers'].append({'id': CHILD})
    original = task.call
    def native(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('object.get') and options == {'return': ['id', '@Markers']}:
            for row in result['return']: row.pop('@Markers', None)
        return result
    task.call = native
    code, rejected = task.run(stage, tx)
    count = 1 if stage == 'verify' else 0
    assert code == 2 and len(task.writes) == count, rejected
    code, rejected = task.run('execute', tx)
    assert code == 2 and len(task.writes) == count, rejected


@pytest.mark.parametrize('version,path', [('2025.1', '[Other]'), ('2025.1', 'Marker'),
    ('2025.1', '[Marker]\\Child'), ('2025.1', '[marker]'), ('2025.1', '[Marker]\n'),
    ('2023.1', '[Marker]'), ('2024.1', '[Marker]')])
def test_relative_marker_display_requires_exact_observed_version_and_spelling(tmp_path, version, path):
    task = retained_marker_task(tmp_path, version)
    task.objects[MARKER]['path'] = path
    code, rejected = task.step('draft-bind-object', '--object-id', MARKER)
    assert code == 2 and task.writes == [], rejected


@pytest.mark.parametrize('fault', ['owner', 'class', 'path', 'membership'])
def test_relative_marker_preview_revalidates_owned_guid_context_before_any_write(tmp_path, fault):
    task = retained_marker_task(tmp_path)
    handle = task.bind(MARKER); label = select_field(task, owner=handle, token='Label')
    code, result = task.step('draft-declare-existing', '--declaration-id', 'edit', '--object-handle', handle,
        '--field-value', label, 'R90_PREPARED_ONLY'); assert code == 0, result
    tx, shown = task.preview()
    code, result = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token']); assert code == 0, result
    if fault == 'owner': task.objects[MARKER]['owner'] = {'id': SECOND}
    elif fault == 'class': task.objects[MARKER]['classId'] = 16
    elif fault == 'path': task.objects[MARKER]['path'] = '[Other]'
    else: task.objects[FIRST]['@Markers'] = []
    code, rejected = task.run('execute', tx)
    assert code == 2 and task.writes == [], rejected
    code, rejected = task.run('execute', tx)
    assert code == 2 and task.writes == [], rejected


@pytest.mark.parametrize('shape', ['rename', 'child', 'import'])
def test_relative_marker_display_cannot_derive_mutation_paths(tmp_path, shape):
    task = retained_marker_task(tmp_path)
    handle = task.bind(MARKER)
    code, result = task.step('draft-declare-existing', '--declaration-id', 'edit', '--object-handle', handle,
        *(['--field', 'new_name', 'Requested name'] if shape == 'rename' else ['--field', 'notes', 'Requested notes']))
    assert code == 0, result
    if shape == 'child':
        code, found = task.step('draft-discover-types', '--role', 'object', '--meaning', 'AudioFileSource'); assert code == 0, found
        kind, = found['type_candidates']
        code, result = task.step('draft-declare-new', '--declaration-id', 'child', '--parent-handle', handle,
            '--kind', kind['handle'], '--name', 'Child')
    elif shape == 'import':
        from pathlib import Path
        media = Path(__file__).parents[1] / '_org/2025.1/Originals/SFX/WAAPI Skill Integration V2/audit_outside.wav'
        code, result = task.step('draft-add-media', '--declaration-id', 'edit', '--media-file', str(media))
    if code == 0: code, result = task.step('draft-check')
    assert code == 2 and task.writes == [], result


def relative_marker_notes_task(path, *, value='Requested Marker notes', fault=None, untouched_peer=False):
    task = retained_marker_task(path)
    task.objects[MARKER]['notes'] = 'Keep selected notes'
    task.objects[CHILD] = {'id': CHILD, 'name': '', 'type': 'Marker', 'classId': 5373968,
        'path': '[Marker]', 'owner': {'id': FIRST}, 'notes': 'Keep peer notes', '@Time': 0.02, '@Label': 'Peer'}
    task.objects[FIRST]['@Markers'].append({'id': CHILD})
    if untouched_peer:
        task.objects[UNTOUCHED_MARKER] = {'id': UNTOUCHED_MARKER, 'name': '', 'type': 'Marker', 'classId': 5373968,
            'path': '[Marker]', 'owner': {'id': FIRST}, 'notes': 'Keep untouched notes', '@Time': 0.03, '@Label': 'Untouched'}
        task.objects[FIRST]['@Markers'].append({'id': UNTOUCHED_MARKER})
    handle = task.bind(MARKER)
    code, result = task.step('draft-declare-existing', '--declaration-id', 'edit', '--object-handle', handle,
        '--field', 'notes', value); assert code == 0, result
    original = task.call
    def native(uri, args=None, options=None):
        if uri.endswith('object.set'):
            assert args['objects'] == [{'object': MARKER, 'notes': value}]
            task.calls.append((uri, deepcopy(args), deepcopy(options))); task.writes.append(deepcopy(args))
            task.objects[MARKER]['notes'] = 'Wrong selected notes' if fault == 'selected-notes' else value
            if fault == 'peer-notes': task.objects[CHILD]['notes'] = 'Unexpected peer edit'
            elif fault == 'peer-path': task.objects[CHILD]['path'] = '[Other]'
            elif fault == 'owner': task.objects[MARKER]['owner'] = {'id': SECOND}
            elif fault == 'order': task.objects[FIRST]['@Markers'].reverse()
            elif fault == 'class': task.objects[MARKER]['classId'] = 16
            elif fault == 'path': task.objects[MARKER]['path'] = '[Other]'
            return {'objects': [{'id': MARKER, 'name': ''}]}
        return original(uri, args, options)
    task.call = native
    return task


@pytest.mark.parametrize('value', ['Requested Marker notes', ''])
def test_relative_marker_declared_notes_execute_once_and_verify_without_identity_drift(tmp_path, value):
    task = relative_marker_notes_task(tmp_path, value=value)
    before = deepcopy(task.objects)
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True and len(task.writes) == 1, verified
    assert task.objects == {**before, MARKER: {**before[MARKER], 'notes': value}}
    code, rejected = task.run('execute', tx)
    assert code == 2 and len(task.writes) == 1, rejected


@pytest.mark.parametrize('fault', ['selected-notes', 'peer-notes', 'peer-path', 'owner', 'order', 'class', 'path'])
def test_relative_marker_notes_verifier_preserves_selected_intent_and_owned_context_without_retry(tmp_path, fault):
    task = relative_marker_notes_task(tmp_path, fault=fault)
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 2 and verified['verified'] is False and len(task.writes) == 1, verified
    code, rejected = task.run('execute', tx)
    assert code == 2 and len(task.writes) == 1, rejected


@pytest.mark.parametrize('fault', ['selected-notes', 'peer-notes', 'order', 'owner'])
def test_relative_marker_notes_prewrite_keeps_original_selected_and_peer_proof(tmp_path, fault):
    task = relative_marker_notes_task(tmp_path)
    tx, shown = task.preview()
    if fault == 'selected-notes': task.objects[MARKER]['notes'] = 'Requested Marker notes'
    elif fault == 'peer-notes': task.objects[CHILD]['notes'] = 'Unexpected peer edit'
    elif fault == 'order': task.objects[FIRST]['@Markers'].reverse()
    else: task.objects[MARKER]['owner'] = {'id': SECOND}
    code, result = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token']); assert code == 0, result
    code, rejected = task.run('execute', tx)
    assert code == 2 and task.writes == [], rejected
    code, rejected = task.run('execute', tx)
    assert code == 2 and task.writes == [], rejected


def relative_marker_batch_notes_task(path, *, fault=None):
    task = relative_marker_notes_task(path, untouched_peer=True)
    peer = task.bind(CHILD)
    code, result = task.step('draft-declare-existing', '--declaration-id', 'peer-edit', '--object-handle', peer,
        '--field', 'notes', ''); assert code == 0, result
    original = task.call
    def native(uri, args=None, options=None):
        if uri.endswith('object.set'):
            assert args['objects'] == [{'object': MARKER, 'notes': 'Requested Marker notes'}, {'object': CHILD, 'notes': ''}]
            task.calls.append((uri, deepcopy(args), deepcopy(options))); task.writes.append(deepcopy(args))
            for row in args['objects']: task.objects[row['object']]['notes'] = row['notes']
            if fault == 'first-notes': task.objects[MARKER]['notes'] = 'Wrong first notes'
            elif fault == 'second-notes': task.objects[CHILD]['notes'] = 'Wrong second notes'
            elif fault == 'untouched-notes': task.objects[UNTOUCHED_MARKER]['notes'] = 'Unexpected notes'
            elif fault == 'untouched-path': task.objects[UNTOUCHED_MARKER]['path'] = '[Other]'
            elif fault == 'order': task.objects[FIRST]['@Markers'].reverse()
            elif fault == 'owner': task.objects[CHILD]['owner'] = {'id': SECOND}
            elif fault == 'class': task.objects[CHILD]['classId'] = 16
            return {'objects': [{'id': CHILD, 'name': ''}, {'id': MARKER, 'name': ''}]}
        return original(uri, args, options)
    task.call = native
    return task


def test_relative_marker_notes_batch_projects_all_declared_guids_and_preserves_untouched_peer(tmp_path):
    task = relative_marker_batch_notes_task(tmp_path)
    before = deepcopy(task.objects)
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True and len(task.writes) == 1, verified
    assert task.objects == {**before, MARKER: {**before[MARKER], 'notes': 'Requested Marker notes'},
        CHILD: {**before[CHILD], 'notes': ''}}
    code, rejected = task.run('execute', tx)
    assert code == 2 and len(task.writes) == 1, rejected


@pytest.mark.parametrize('fault', ['first-notes', 'second-notes', 'untouched-notes', 'untouched-path', 'order', 'owner', 'class'])
def test_relative_marker_notes_batch_rejects_wrong_intent_or_undeclared_peer_change_without_retry(tmp_path, fault):
    task = relative_marker_batch_notes_task(tmp_path, fault=fault)
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 2 and verified['verified'] is False and len(task.writes) == 1, verified
    code, rejected = task.run('execute', tx)
    assert code == 2 and len(task.writes) == 1, rejected


@pytest.mark.parametrize('identity', [MARKER, CHILD, UNTOUCHED_MARKER])
def test_relative_marker_notes_batch_prewrite_uses_original_full_roster(tmp_path, identity):
    task = relative_marker_batch_notes_task(tmp_path)
    tx, shown = task.preview()
    task.objects[identity]['notes'] = 'Premature notes change'
    code, result = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token']); assert code == 0, result
    code, rejected = task.run('execute', tx)
    assert code == 2 and task.writes == [], rejected
    code, rejected = task.run('execute', tx)
    assert code == 2 and task.writes == [], rejected
