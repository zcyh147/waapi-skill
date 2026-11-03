"""Source-backed database/directory creation through persisted public transactions."""
from copy import deepcopy
import json

import pytest

from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, ROOT, CHILD
from tests.unit.test_list_merge_existing_conditions_gateway import select_field

USER_DATABASES = '{8452BD49-9264-4A56-A3BB-047FA7F119BE}'
DIRECTORY = r'C:\WAV\FootSteps'


def database_task(tmp_path, version='2025.1', *, fault=None):
    task = OwnedGraphTask(tmp_path, version, 'object.set')
    task.types = [
        {'name': 'Folder', 'classId': 131088, 'type': 'WObject'},
        {'name': 'MediaPoolDatabase', 'classId': 5832720, 'type': 'WObject'},
        {'name': 'MediaPoolDatabasePath', 'classId': 5898240, 'type': 'Inner'},
    ]
    task.objects = {USER_DATABASES: {'id': USER_DATABASES, 'name': 'User Databases',
        'type': 'Folder', 'classId': 131088, 'path': r'\Databases\User Databases', 'notes': 'Keep folder'}}
    task.metadata = {'Path': {'name': 'Path', 'type': 'string', 'default': ''}}
    original = task.call
    task.writes = []
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            task.writes.append(deepcopy(args))
            row, = args['objects']
            assert row['object'] == USER_DATABASES
            node, = row['children']
            assert node == {'type': 'MediaPoolDatabase', 'name': 'FootSteps', '@Paths': [
                {'type': 'MediaPoolDatabasePath', 'name': '', '@Path': DIRECTORY}]}
            task.objects[ROOT] = {'id': ROOT, 'name': 'FootSteps', 'type': 'MediaPoolDatabase', 'classId': 5832720,
                'parent': {'id': USER_DATABASES}, 'path': r'\Databases\User Databases\FootSteps',
                'notes': '', '@Paths': [{'id': CHILD}]}
            # Runtime spelling is deliberately not inferred from another Inner profile.
            task.objects[CHILD] = {'id': CHILD, 'name': '', 'type': 'PluginInnerObject', 'classId': 5898240,
                'owner': {'id': ROOT}, 'path': r'\opaque-directory', 'notes': '', '@Path': DIRECTORY}
            if fault == 'owner': task.objects[CHILD]['owner'] = {'id': USER_DATABASES}
            elif fault == 'class': task.objects[CHILD]['classId'] = 131088
            elif fault == 'path': task.objects[CHILD]['@Path'] = r'C:\Other'
            elif fault == 'membership': task.objects[ROOT]['@Paths'] = []
            return {'objects': [{'id': USER_DATABASES, 'name': 'User Databases', 'children': [
                {'id': ROOT, 'name': 'FootSteps', '@Paths': [{'id': CHILD, 'name': ''}]}]}]}
        return original(uri, args, options)
    task.call = call
    return task


def discover_type(task, meaning):
    code, found = task.step('draft-discover-types', '--role', 'object', '--meaning', meaning)
    assert code == 0, found
    return found['type_candidates'][0]['handle']


def declare_database(task, *, directory=DIRECTORY, member_name=None, wrong_owner=False):
    parent = task.bind(USER_DATABASES)
    kind = discover_type(task, 'MediaPoolDatabase')
    code, declared = task.step('draft-declare-new', '--declaration-id', 'database', '--parent-handle', parent,
        '--name', 'FootSteps', '--kind', kind)
    assert code == 0, declared
    owner = declared['draft']['declared_object']['result_handle']
    code, listed = task.step('draft-discover-fields', '--type-handle', kind, '--field-source', 'documented-lists', '--list')
    assert code == 0, listed
    choice, = listed['agent_result']['items']
    assert choice['name'] == 'Paths'
    code, selected = task.step('draft-discover-fields', '--type-handle', kind,
        '--field-source', 'documented-lists', '--selection', choice['selection'])
    assert code == 0, selected
    paths = selected['meaning_results'][0]['candidates'][0]['handle']
    member = discover_type(task, 'MediaPoolDatabasePath')
    path_field = select_field(task, kind=member, token='Path')
    return task.step('draft-declare-new', '--declaration-id', 'directory', '--parent-handle', parent if wrong_owner else owner, '--kind', member,
        '--field', 'object_list', paths, '--field-value', path_field, directory if isinstance(directory, str) else json.dumps(directory),
        *([] if member_name is None else ['--name', member_name]))


def test_database_directory_survives_persisted_preview_authorization_and_verification(tmp_path):
    task = database_task(tmp_path)
    before = deepcopy(task.objects)
    code, declared = declare_database(task)
    assert code == 0, declared
    tx, shown = task.preview()
    assert task.objects == before and task.writes == []
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified.get('verified') is True, json.dumps(verified)
    assert task.objects[USER_DATABASES] == before[USER_DATABASES]
    assert task.objects[CHILD]['@Path'] == DIRECTORY
    assert task.objects[CHILD]['owner'] == {'id': ROOT}
    assert len(task.writes) == 1
    code, refused = task.run('execute', tx)
    assert code == 2, refused
    assert len(task.writes) == 1


def test_database_public_schema_discloses_source_scoped_directory_outcome(tmp_path):
    task = database_task(tmp_path)
    code, schema = task.run('operation-schema', 'object.set')
    assert code == 0, schema
    def find(value):
        if isinstance(value, dict):
            if 'anonymous_list_member' in value:
                return value['anonymous_list_member']['profiles']['media_pool_directory']
            for nested in value.values():
                result = find(nested)
                if result is not None: return result
        if isinstance(value, list):
            for nested in value:
                result = find(nested)
                if result is not None: return result
    profile = find(schema)
    assert profile['version'] == '2025.1'
    assert profile['database_class'] == 5832720 and profile['path_class'] == 5898240
    assert profile['directory']['maximum_utf8_bytes'] == 4096
    assert 'index_completion_not_claimed' in profile['verification']
    assert profile['sdk_sha256'] == 'de5de9c1908f5dbcd810714bb1f9dc693bb05764da85a1cdd0493cc75bc5d708'


@pytest.mark.parametrize('fault', ['owner', 'class', 'path', 'membership'])
def test_database_verification_rejects_wrong_owned_directory_without_retry(tmp_path, fault):
    task = database_task(tmp_path, fault=fault)
    code, declared = declare_database(task)
    assert code == 0, declared
    tx, shown = task.preview()
    code, result = task.finish(tx, shown)
    assert code == 2 and result.get('verified') is not True, result
    code, repeated = task.run('execute', tx)
    assert code == 2, repeated
    assert len(task.writes) == 1


@pytest.mark.parametrize('directory', ['relative/directory', 'C:\\WAV\\..\\Other', 'C:\\WAV\x00Other', 'C:\\' + 'x' * 4096])
def test_database_malformed_directory_fails_before_preview(tmp_path, directory):
    task = database_task(tmp_path)
    code, declared = declare_database(task, directory=directory)
    if code == 0:
        code, declared = task.step('draft-check')
    assert code == 2 and declared['error_code'] == 'INVALID_MEDIA_POOL_DIRECTORY', declared
    assert task.writes == []


@pytest.mark.parametrize('fault', ['wrong-owner', 'wrong-member-class', 'named-member'])
def test_database_directory_constructor_rejects_unproved_roles(tmp_path, fault):
    task = database_task(tmp_path)
    if fault == 'wrong-member-class':
        task.types[-1]['classId'] = 17
    code, result = declare_database(task, wrong_owner=fault == 'wrong-owner',
        member_name='Caller label' if fault == 'named-member' else None)
    if code == 0:
        code, result = task.step('draft-check')
    assert code == 2, result
    assert task.writes == []


@pytest.mark.parametrize('fault', ['parent-identity', 'member-class', 'field-metadata', 'source'])
def test_database_directory_preview_rejects_drift_before_write(tmp_path, monkeypatch, fault):
    task = database_task(tmp_path)
    code, declared = declare_database(task)
    assert code == 0, declared
    tx, shown = task.preview()
    if fault == 'parent-identity': task.objects[USER_DATABASES]['name'] = 'Changed folder'
    elif fault == 'member-class': task.types[-1]['classId'] = 17
    elif fault == 'field-metadata': task.metadata['Path']['default'] = 'Changed metadata'
    else:
        from wwise_waapi import media_pool_database
        changed_source = tmp_path / 'changed-source.html'
        changed_source.write_bytes(media_pool_database.SOURCE.read_bytes() + b'changed')
        monkeypatch.setattr(media_pool_database, 'SOURCE', changed_source)
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, result = task.run('execute', tx)
    assert code == 2, result
    assert task.writes == []


@pytest.mark.parametrize('version', ['2022.1', '2023.1', '2024.1'])
def test_database_directory_not_admitted_from_unproved_older_registration(tmp_path, version):
    task = database_task(tmp_path, version)
    parent = task.bind(USER_DATABASES)
    kind = discover_type(task, 'MediaPoolDatabasePath')
    code, result = task.step('draft-declare-new', '--declaration-id', 'directory', '--parent-handle', parent,
        '--kind', kind, '--field', 'object_list', 'Paths')
    assert code == 2 and result['error_code'] == 'ANONYMOUS_LIST_PLACEMENT_INVALID', result
    assert task.writes == []
    code, schema = task.run('operation-schema', 'object.set')
    assert code == 0, schema
    serialized = json.dumps(schema)
    assert 'matching_source_unproved; constructor_not_admitted' in serialized
    assert '"native_absence_claim": false' in serialized


def test_database_constructor_requires_matching_source_class_not_name_alone(tmp_path):
    task = database_task(tmp_path)
    task.types[1]['classId'] = 17
    parent = task.bind(USER_DATABASES)
    kind = discover_type(task, 'MediaPoolDatabase')
    code, declared = task.step('draft-declare-new', '--declaration-id', 'database', '--parent-handle', parent,
        '--name', 'FootSteps', '--kind', kind)
    assert code == 0, declared
    code, result = task.step('draft-check')
    assert code == 2 and result['error_code'] == 'OPERATION_DRAFT_CHECK_FAILED', result
    assert result['details']['issues'][0]['error_code'] == 'MEDIA_POOL_DATABASE_CLASS_UNPROVEN', result
    assert task.writes == []
