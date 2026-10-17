"""Closed Authoring layout mutations through public Draft/Preview/execute/verify."""
from __future__ import annotations

from pathlib import Path
from copy import deepcopy
import pytest

from tests.support.gateway_config import set_gateway_config
from tests.unit.test_waapi_gateway import FakeClient, gateway_env, live_info, waapi_gateway as gateway
from wwise_waapi.transactions import TransactionStore
from tests.unit.test_debug_read_gateway import WaapiRequestFailed

URI = 'ak.wwise.ui.layout.'
PROJECT = '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}'
NODE = '{11111111-1111-1111-1111-111111111111}'


class LayoutClient(FakeClient):
    def __init__(self, tmp_path: Path, *, version='2025.1'):
        info = live_info(year=int(version[:4]), command_line=False)
        info.update(processId=1234, sessionId='layout-session-1', platform='macosx')
        info['version']['schema'] = 152
        project = tmp_path / 'project' / 'Sandbox.wproj'
        project.parent.mkdir(exist_ok=True)
        project.write_text('<WwiseDocument/>', encoding='utf-8')
        self.current = 'Designer'
        self.missing_failure = None
        self.layouts = {name: {'Layout': {'Name': name, 'StackPanel': {'Name': 'StackPanel', 'ID': NODE,
            'Orientation': 'Horizontal', '@Children': []}}} for name in ('Designer', 'Profiler')}
        super().__init__({'ak.wwise.core.getInfo': info,
            'ak.wwise.core.getProjectInfo': {'id': PROJECT, 'name': 'Sandbox', 'path': str(project)},
            URI + 'getLayoutNames': {'layouts': ['Designer', 'Profiler']},
            URI + 'getViewInstances': {'viewInstances': []}})

    def call(self, uri, args=None, options=None):
        if uri == URI + 'getLayout':
            self.calls.append((uri, args, options))
            if args['name'] not in self.layouts:
                if self.missing_failure is not None:
                    raise self.missing_failure
                raise WaapiRequestFailed('ak.wwise.unavailable', {'details': {'procedureUri': uri},
                    'message': "Layout '" + args['name'] + "' could not be found."})
            return deepcopy(self.layouts[args['name']])
        if uri == URI + 'setLayout':
            self.calls.append((uri, args, options))
            self.layouts[args['name']] = deepcopy(args['layout'])
            return {}
        if uri == URI + 'removeLayout':
            self.calls.append((uri, args, options))
            self.layouts.pop(args['name'])
            return {}
        if uri == URI + 'getCurrentLayoutName':
            self.calls.append((uri, args, options))
            return {'name': self.current}
        if uri == URI + 'switchLayout':
            self.calls.append((uri, args, options))
            self.current = args['name']
            return {}
        return super().call(uri, args, options)


def switch_preview(tmp_path, *, version='2025.1', policy='ask_before_changes', operation='switchLayout', fields=(), client_setup=None, expect_check_error=False):
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version=version, project_modification_policy=policy)
    state_dir = tmp_path / 'state'
    state = ['--state-dir', str(state_dir)]
    client = LayoutClient(tmp_path, version=version)
    if client_setup is not None:
        client_setup(client)
    code, schema = gateway.execute_gateway(['--version', version, 'request-schema', URI + operation], env=env,
        client_factory=lambda _: pytest.fail('schema must stay offline'))
    assert code == 0, schema
    code, inspected = gateway.execute_gateway([*state, 'layout-inspect', '--layout-name', 'Profiler'],
        env=env, client_factory=lambda _: client)
    assert code == 0, inspected
    code, started = gateway.execute_gateway([*state, *schema['continuation']['gateway_argv']], env=env,
        client_factory=lambda _: pytest.fail('Draft start must stay offline'))
    assert code == 0, (started.get('error_code'), started.get('message'), started.get('details'))
    draft = started['draft']
    authority = started['task_authority']
    code, declared = gateway.execute_gateway([*state, 'draft-declare-layout-plan', draft['draft_id'],
        '--task-authority', authority, '--expected-revision', str(draft['revision']),
        '--layout-handle', inspected['layout_handle'], *fields], env=env, client_factory=lambda _: client)
    assert code == 0, declared
    code, checked = gateway.execute_gateway([*state, 'draft-check', draft['draft_id'],
        '--task-authority', authority, '--expected-revision', str(declared['draft']['revision'])],
        env=env, client_factory=lambda _: client)
    if expect_check_error:
        assert code != 0, checked
        assert URI + operation not in [call[0] for call in client.calls]
        return env, state, client, checked
    assert code == 0, (checked.get("error_code"), checked.get("message"), checked.get("details"))
    code, preview = gateway.execute_gateway([*state, 'preview-from-draft', draft['draft_id'],
        '--task-authority', authority, '--expected-revision', str(checked['draft']['revision'])],
        env=env, client_factory=lambda _: client)
    assert code == 0, (preview.get('error_code'), preview.get('message'), preview.get('details'))
    artifact = TransactionStore(state_dir).load_preview(preview['transaction_id']).artifact
    if operation == 'switchLayout':
        assert artifact['prepared_operation']['dispatch'] == {'uri': URI + 'switchLayout', 'args': {'name': 'Profiler'}, 'options': {}}
        assert artifact['prepared_operation']['verification_plan']['kind'] == 'authoring-layout-state'
    assert client.current == 'Designer'
    assert URI + 'switchLayout' not in [call[0] for call in client.calls]
    return env, state, client, preview


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
def test_register_empty_owned_layout_uses_exact_absence_proof_and_closed_name(tmp_path, version):
    env, state, client, preview = switch_preview(tmp_path, version=version, operation='setLayout',
        fields=('--new-layout-name', 'GatewayOwnedLayout'))
    prepared = TransactionStore(Path(state[1])).load_preview(preview['transaction_id']).artifact['prepared_operation']
    assert prepared['dispatch'] == {'uri': URI + 'setLayout', 'args': {
        'name': 'GatewayOwnedLayout', 'layout': {'Layout': {'Name': 'GatewayOwnedLayout'}}}, 'options': {}}
    assert prepared['pre_state']['layout_target_absence']['absent'] is True
    assert URI + 'setLayout' not in [row[0] for row in client.calls]


def confirm_execute_verify(env, state, client, preview):
    tx = preview['transaction_id']
    code, shown = gateway.execute_gateway([*state, 'transaction-show', tx], env=env)
    assert code == 0, shown
    code, confirmed = gateway.execute_gateway([*state, 'confirm', tx, '--confirmation-token', shown['confirmation']['token']], env=env)
    assert code == 0, confirmed
    code, executed = gateway.execute_gateway([*state, 'execute', tx], env=env, client_factory=lambda _: client)
    assert code == 0, executed
    code, verified = gateway.execute_gateway([*state, 'verify', tx], env=env, client_factory=lambda _: client)
    assert code == 0, verified
    return verified


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
def test_registered_layout_has_separately_previewed_removal_and_absence_verifier(tmp_path, version):
    env, state, client, preview = switch_preview(tmp_path, version=version, operation='setLayout', fields=('--new-layout-name', 'GatewayOwnedLayout'))
    prepared = TransactionStore(Path(state[1])).load_preview(preview['transaction_id']).artifact['prepared_operation']
    assert prepared['cleanup']['cleanup_requirement'] == 'required_cleanup'
    assert prepared['cleanup']['companion_request']['api'] == URI + 'removeLayout'
    confirm_execute_verify(env, state, client, preview)
    assert 'GatewayOwnedLayout' in client.layouts
    code, inspected = gateway.execute_gateway([*state, 'layout-inspect', '--layout-name', 'GatewayOwnedLayout'], env=env, client_factory=lambda _: client)
    assert code == 0, inspected
    code, schema = gateway.execute_gateway(['request-schema', URI + 'removeLayout'], env=env)
    assert code == 0, schema
    code, started = gateway.execute_gateway([*state, *schema['continuation']['gateway_argv']], env=env)
    assert code == 0, started
    draft, authority = started['draft'], started['task_authority']
    code, declared = gateway.execute_gateway([*state, 'draft-declare-layout-plan', draft['draft_id'], '--task-authority', authority,
        '--expected-revision', str(draft['revision']), '--layout-handle', inspected['layout_handle']], env=env, client_factory=lambda _: client)
    assert code == 0, declared
    code, checked = gateway.execute_gateway([*state, 'draft-check', draft['draft_id'], '--task-authority', authority,
        '--expected-revision', str(declared['draft']['revision'])], env=env, client_factory=lambda _: client)
    assert code == 0, checked
    code, removal = gateway.execute_gateway([*state, 'preview-from-draft', draft['draft_id'], '--task-authority', authority,
        '--expected-revision', str(checked['draft']['revision'])], env=env, client_factory=lambda _: client)
    assert code == 0, removal
    verified = confirm_execute_verify(env, state, client, removal)
    assert verified['verification']['business_state_verified'] is True
    assert 'GatewayOwnedLayout' not in client.layouts
    assert [row[0] for row in client.calls].count(URI + 'setLayout') == 1
    assert [row[0] for row in client.calls].count(URI + 'removeLayout') == 1


@pytest.mark.parametrize('failure', ['generic', 'wrong_procedure', 'wrong_name'])
def test_registration_never_treats_other_unavailable_errors_as_absence(tmp_path, failure):
    details = {'details': {'procedureUri': URI + 'getLayout'},
        'message': "Layout 'GatewayOwnedLayout' could not be found."}
    if failure == 'generic':
        details['message'] = 'Procedure not available for this type of Wwise instance.'
    elif failure == 'wrong_procedure':
        details['details']['procedureUri'] = 'ak.wwise.core.object.get'
    else:
        details['message'] = "Layout 'SomeOtherLayout' could not be found."
    switch_preview(tmp_path, operation='setLayout', fields=('--new-layout-name', 'GatewayOwnedLayout'),
        client_setup=lambda client: setattr(client, 'missing_failure', WaapiRequestFailed('ak.wwise.unavailable', details)),
        expect_check_error=True)


def test_registration_rejects_existing_name_and_factory_removal_is_forbidden(tmp_path):
    create_root, remove_root = tmp_path / 'create', tmp_path / 'remove'
    create_root.mkdir()
    remove_root.mkdir()
    switch_preview(create_root, operation='setLayout', fields=('--new-layout-name', 'Designer'), expect_check_error=True)
    switch_preview(remove_root, operation='removeLayout', expect_check_error=True)


def test_registration_rechecks_absence_after_confirmation_without_overwrite(tmp_path):
    env, state, client, preview = switch_preview(tmp_path, operation='setLayout', fields=('--new-layout-name', 'GatewayOwnedLayout'))
    tx = preview['transaction_id']
    _, shown = gateway.execute_gateway([*state, 'transaction-show', tx], env=env)
    code, confirmed = gateway.execute_gateway([*state, 'confirm', tx, '--confirmation-token', shown['confirmation']['token']], env=env)
    assert code == 0, confirmed
    client.layouts['GatewayOwnedLayout'] = {'Layout': {'Name': 'GatewayOwnedLayout'}}
    code, rejected = gateway.execute_gateway([*state, 'execute', tx], env=env, client_factory=lambda _: client)
    assert code != 0, rejected
    assert URI + 'setLayout' not in [row[0] for row in client.calls]


def test_switch_layout_uses_closed_business_handle_and_immutable_preview(tmp_path):
    switch_preview(tmp_path)


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
def test_switch_executes_once_and_verifies_independent_current_layout(tmp_path, version):
    env, state, client, preview = switch_preview(tmp_path, version=version)
    tx = preview['transaction_id']
    code, shown = gateway.execute_gateway([*state, 'transaction-show', tx], env=env,
        client_factory=lambda _: pytest.fail('transaction review must stay offline'))
    assert code == 0, shown
    code, confirmed = gateway.execute_gateway([*state, 'confirm', tx,
        '--confirmation-token', shown['confirmation']['token']], env=env,
        client_factory=lambda _: pytest.fail('confirmation must stay offline'))
    assert code == 0, confirmed
    code, executed = gateway.execute_gateway([*state, 'execute', tx], env=env, client_factory=lambda _: client)
    assert code == 0, executed
    assert client.current == 'Profiler'
    snapshot = TransactionStore(Path(state[1])).load_snapshot(tx)
    completed = next(event for event in snapshot.events if event['event_type'] == 'execution_completed')
    assert [row['uri'] for row in completed['details']['role_validation']['readbacks']] == [
        'ak.wwise.core.getInfo', 'ak.wwise.core.getProjectInfo', URI + 'getLayout',
        URI + 'getCurrentLayoutName']
    code, verified = gateway.execute_gateway([*state, 'verify', tx], env=env, client_factory=lambda _: client)
    assert code == 0, verified
    assert verified['verification']['status'] == 'verified'
    code, repeated = gateway.execute_gateway([*state, 'execute', tx], env=env, client_factory=lambda _: client)
    assert code != 0, repeated
    assert [call[0] for call in client.calls].count(URI + 'switchLayout') == 1


@pytest.mark.parametrize('drift', ['process', 'session', 'layout', 'current', 'host'])
def test_switch_rejects_live_identity_or_layout_drift_before_dispatch(tmp_path, drift):
    env, state, client, preview = switch_preview(tmp_path)
    tx = preview['transaction_id']
    code, shown = gateway.execute_gateway([*state, 'transaction-show', tx], env=env)
    assert code == 0, shown
    code, confirmed = gateway.execute_gateway([*state, 'confirm', tx,
        '--confirmation-token', shown['confirmation']['token']], env=env)
    assert code == 0, confirmed
    original_call = client.call
    def drifted_call(uri, args=None, options=None):
        result = original_call(uri, args, options)
        if uri == 'ak.wwise.core.getInfo' and drift in {'process', 'session'}:
            result = dict(result)
            result['processId' if drift == 'process' else 'sessionId'] = 'changed'
        if uri == 'ak.wwise.core.getInfo' and drift == 'host':
            result = {**result, 'isCommandLine': True}
        if uri == URI + 'getLayout' and drift == 'layout':
            result['Layout']['StackPanel']['Orientation'] = 'Vertical'
        if uri == URI + 'getCurrentLayoutName' and drift == 'current':
            result = {'name': 'SoundBank'}
        return result
    client.call = drifted_call
    code, rejected = gateway.execute_gateway([*state, 'execute', tx], env=env, client_factory=lambda _: client)
    assert code != 0, rejected
    assert URI + 'switchLayout' not in [call[0] for call in client.calls]


def test_switch_success_result_cannot_substitute_for_business_verification(tmp_path):
    env, state, client, preview = switch_preview(tmp_path)
    tx = preview['transaction_id']
    _, shown = gateway.execute_gateway([*state, 'transaction-show', tx], env=env)
    _, confirmed = gateway.execute_gateway([*state, 'confirm', tx,
        '--confirmation-token', shown['confirmation']['token']], env=env)
    assert confirmed['state'] == 'confirmed'
    original_call = client.call
    def ignored_switch(uri, args=None, options=None):
        result = original_call(uri, args, options)
        if uri == URI + 'switchLayout':
            client.current = 'Designer'
        return result
    client.call = ignored_switch
    code, executed = gateway.execute_gateway([*state, 'execute', tx], env=env, client_factory=lambda _: client)
    assert code == 0, executed
    code, verified = gateway.execute_gateway([*state, 'verify', tx], env=env, client_factory=lambda _: client)
    assert code != 0, verified
    assert verified['verification']['business_state_verified'] is False
    assert [call[0] for call in client.calls].count(URI + 'switchLayout') == 1
