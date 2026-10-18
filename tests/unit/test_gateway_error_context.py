"""Public contextual error receipts must not be replaced by constructor errors."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from tests.unit import test_core_business_gateway as core


@pytest.mark.parametrize('problem,reason', [
    ('malformed', 'malformed_identity'), ('duplicate', 'duplicate_identity'), ('extra', 'identity_set_mismatch')])
def test_core_business_identity_failures_keep_exact_error_and_stop_before_operation(tmp_path, problem, reason):
    source = {'id': core.SOURCE_ID, 'name': 'Source', 'type': 'Sound', 'path': r'\Actor-Mixer Hierarchy\Source'}
    target = {'id': core.TARGET_ID, 'name': 'Target', 'type': 'Sound', 'path': r'\Actor-Mixer Hierarchy\Target'}
    if problem == 'malformed':
        target.pop('name')
    elif problem == 'duplicate':
        target = dict(source)
    else:
        target['id'] = '{33333333-3333-3333-3333-333333333333}'
    client = core.FakeClient({'ak.wwise.core.getInfo': [core._info()],
        'ak.wwise.core.getProjectInfo': [core._project(tmp_path)],
        'ak.wwise.core.object.get': [{'return': [source, target]}]})
    code, result = core.gateway.execute_gateway(['core-call', 'ak.wwise.core.object.diff',
        '--source-id', core.SOURCE_ID, '--target-id', core.TARGET_ID],
        env=core._env(tmp_path), client_factory=lambda _: client)
    assert code == 2 and result['error_code'] == 'CORE_BUSINESS_IDENTITY_MISMATCH', result
    assert result['details']['reason'] == reason
    assert result['details']['operation_dispatched'] is False
    assert result['details']['requested_ids'] == [core.SOURCE_ID, core.TARGET_ID]
    assert [uri for uri, _, _ in client.calls] == ['ak.wwise.core.getInfo', 'ak.wwise.core.getProjectInfo', 'ak.wwise.core.object.get']
    assert len(json.dumps(result, ensure_ascii=False).encode()) < 16 * 1024


def test_packaged_gateway_shape_errors_supply_context_at_each_call_site():
    packaged = Path(__file__).resolve().parents[2] / 'skills' / 'waapi-skill'
    missing = []
    for path in packaged.rglob('*.py'):
        if any(part in {'.venv', '__pycache__'} for part in path.parts):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else None
            if name == 'GatewayResultShapeError':
                detail = next((keyword.value for keyword in node.keywords if keyword.arg == 'details'), None)
                if detail is None or (isinstance(detail, ast.Dict) and not detail.keys) or (isinstance(detail, ast.Constant) and detail.value is None):
                    missing.append(f'{path.relative_to(packaged)}:{node.lineno}')
    assert missing == []


@pytest.mark.parametrize('roots,reason', [(None, 'directory_map_missing'), ({'root': '', 'originals': None}, 'directory_roots_invalid')])
def test_source_control_missing_roots_keep_context_without_dispatching_mutation(tmp_path, roots, reason):
    from tests.unit import test_remaining_core_business_gateway as source
    class Client(source._SourceControlDraftClient):
        def __init__(self, path):
            super().__init__(path)
            self.calls = []
        def call(self, uri, args=None, options=None):
            self.calls.append(uri)
            value = super().call(uri, args, options)
            if uri.endswith('getProjectInfo'):
                value.pop('directories')
                if roots is not None:
                    value['directories'] = roots
            return value
    client = Client(tmp_path)
    prefix = ['--state-dir', str(tmp_path / 'state')]
    code, started = source.gateway.execute_gateway([*prefix, 'draft-start', source.SOURCE_CONTROL_COMMIT_URI], env=source._env(tmp_path))
    assert code == 0, started
    code, result = source.gateway.execute_gateway([*prefix, 'draft-declare-source-control-plan', started['draft']['draft_id'],
        '--task-authority', started['task_authority'], '--expected-revision', str(started['draft']['revision']),
        '--project-file', 'Events/Owned.wwu', '--commit-message', 'Owned change'],
        env=source._env(tmp_path), client_factory=lambda _: client)
    assert code == 2 and result['error_code'] == 'SOURCE_CONTROL_ROOTS_UNAVAILABLE', result
    assert result['details']['reason'] == reason
    assert result['details']['required_fields'] == ['directories.root', 'directories.originals']
    assert result['details']['operation_dispatched'] is False
    assert client.calls == ['ak.wwise.core.getInfo', 'ak.wwise.core.getProjectInfo']


def test_invalid_draft_type_catalog_keeps_metadata_error_without_advancing_selection(tmp_path):
    from tests.unit.test_field_interface_closure_gateway import CreateTask, FIRST
    task = CreateTask(tmp_path, '2025.1')
    task.bind(FIRST)
    task.types = [{'name': None, 'type': 'WObject'}]
    revision = task.revision
    code, result = task.step('draft-discover-types', '--meaning', 'Event', '--role', 'object')
    assert code == 2 and result['error_code'] == 'INVALID_METADATA_RESULT', result
    assert result['details']['api'] == 'ak.wwise.core.object.getTypes'
    assert result['details']['requested_role'] == 'object'
    assert result['details']['selection_advanced'] is False
    assert task.revision == revision
    assert not any(uri.endswith(('create', 'setProperty', 'setReference')) for uri, _, _ in task.calls)


def test_soundengine_read_missing_game_object_handle_keeps_store_error_before_read(tmp_path):
    from tests.unit import test_soundengine_business_gateway as sound
    client = sound._SoundEngineDraftClient(tmp_path)
    code, result = sound.gateway.execute_gateway(['--state-dir', str(tmp_path / 'state'), 'core-call',
        'ak.soundengine.getSwitch', '--switch-group-id', client.switch_group_id,
        '--game-object-handle', 'goh1-' + 'a' * 32], env=sound._env(tmp_path), client_factory=lambda _: client)
    assert code == 2 and result['error_code'] == 'GAME_OBJECT_HANDLE_NOT_AVAILABLE', result
    assert result['details']['api'] == 'ak.soundengine.getSwitch'
    assert result['details']['handle_kind'] == 'game_object'
    assert result['details']['operation_dispatched'] is False
    assert client.soundengine_calls == []


def test_transport_read_missing_build_keeps_binding_error_before_store_or_transport_call(tmp_path):
    from tests.unit import test_runtime_business_gateway as runtime
    class Client(runtime._RuntimeControlDraftClient):
        def __init__(self, path):
            super().__init__(path)
            self.calls = []
        def call(self, uri, args=None, options=None):
            self.calls.append(uri)
            value = super().call(uri, args, options)
            if uri.endswith('getInfo'):
                value['version'].pop('displayName')
            return value
    client = Client(tmp_path)
    state = tmp_path / 'state'
    handle = runtime._issue_transport_handle(state, project_path=client.project_file)
    code, result = runtime.gateway.execute_gateway(['--state-dir', str(state), 'core-call',
        runtime.TRANSPORT_GET_STATE_URI, '--transport-handle', handle], env=runtime._env(tmp_path), client_factory=lambda _: client)
    assert code == 2 and result['error_code'] == 'INVALID_STATUS_RESULT', result
    assert result['details']['required_field'] == 'version.displayName'
    assert result['details']['binding'] == 'runtime_transport_context'
    assert client.calls == ['ak.wwise.core.getInfo', 'ak.wwise.core.getProjectInfo']


def test_project_loss_during_verification_preserves_already_executed_state_without_replay(tmp_path):
    from tests.unit import test_soundengine_business_gateway as sound
    class Client(sound._SoundEngineDraftClient):
        project_missing = False
        def call(self, uri, args=None, options=None):
            if self.project_missing and uri.endswith('getProjectInfo'):
                return {}
            return super().call(uri, args, options)
    client = Client(tmp_path)
    env, state = sound._env(tmp_path), tmp_path / 'state'
    preview, _ = sound._preview_soundengine_plan(tmp_path=tmp_path, state_dir=state, env=env, client=client,
        operation='ak.soundengine.registerGameObj', declaration=['--game-object-name', 'Owned Listener'])
    tx = preview['transaction_id']
    snapshot = sound.TransactionStore(state).load_snapshot(tx)
    code, confirmed = sound.gateway.execute_gateway(['--state-dir', str(state), 'confirm', tx,
        '--confirmation-token', snapshot.confirmation_token], env=env)
    assert code == 0, confirmed
    code, executed = sound.gateway.execute_gateway(['--state-dir', str(state), 'execute', tx], env=env, client_factory=lambda _: client)
    assert code == 0 and executed['executed'] is True, executed
    client.project_missing = True
    code, deferred = sound.gateway.execute_gateway(['--state-dir', str(state), 'verify', tx], env=env, client_factory=lambda _: client)
    assert code == 2 and deferred['error_code'] == 'INVALID_PROJECT_RESULT', deferred
    assert deferred['status'] == 'verification_deferred'
    assert deferred['state'] == 'executed_unverified'
    assert deferred['automatic_retry'] is False
    assert deferred['manual_verification_retry_allowed'] is True
    assert deferred['details']['invalid_fields'] == ['id', 'name', 'path']
    assert client.soundengine_calls == ['ak.soundengine.registerGameObj']
    code, replay = sound.gateway.execute_gateway(['--state-dir', str(state), 'execute', tx], env=env, client_factory=lambda _: client)
    assert code == 2, replay
    assert client.soundengine_calls == ['ak.soundengine.registerGameObj']
    client.project_missing = False
    code, result = sound.gateway.execute_gateway(['--state-dir', str(state), 'verify', tx], env=env, client_factory=lambda _: client)
    assert code == 0 and result['state'] in {'verified', 'result_schema_checked'}, result
    assert client.soundengine_calls == ['ak.soundengine.registerGameObj']


def test_field_discovery_error_keeps_complete_keys_after_large_rejected_candidates(tmp_path):
    from tests.unit.test_field_interface_closure_gateway import CreateTask, FIRST
    task = CreateTask(tmp_path, '2025.1')
    task.bind(FIRST)
    task.types = [{'name': 'AuxBus', 'classId': 3997712, 'type': 'WObject'}]
    kind = task.discover_kind('AuxBus')
    # The real failing neighbours; all eight are class-scope conditional fields.
    task.metadata = {f'UserAuxSend{band}{index}': {
        'name': f'UserAuxSend{band}{index}', 'type': 'int16',
        'display': {'name': f'User-Defined Auxiliary {band} {index}'},
        'restriction': {'type': 'range', 'min': 0, 'max': 100},
        'dependencies': [{'action': 'Show', 'context': 'Self', 'type': 'isMasterBus', 'value': False},
            {'action': 'Enable', 'context': 'Self',
            'property': 'OverrideUserAuxSends', 'type': 'override'}],
    } for band in ('HPF', 'LPF') for index in range(4)}
    revision = task.revision
    code, result = task.step('draft-discover-fields', '--type-handle', kind,
        '--meaning', 'User-Defined Auxiliary Send 0')
    assert code == 2 and result['message'] == 'Selected live fields could not be bound', json.dumps({'result': result, 'calls': task.calls})
    assert result['details']['draft_changed'] is False
    rejected = result['details']['rejected_candidates']
    assert len(rejected) == 8
    assert all(set(row) == {'error_code', 'field_kind', 'field', 'reason', 'details'} for row in rejected)
    assert all(row['details']['draft_changed'] is False for row in rejected)
    assert task.revision == revision
    assert not any(uri.endswith(('create', 'set', 'setProperty', 'setReference')) for uri, _, _ in task.calls)
    assert len(json.dumps(result, ensure_ascii=False).encode('utf-8')) < 32 * 1024
