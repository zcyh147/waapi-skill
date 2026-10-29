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
        self.views = {name: [] for name in ('Designer', 'Profiler')}
        self.rectangles = {}
        self.layouts = {name: {'Layout': {'Name': name, 'StackPanel': {'Name': 'StackPanel', 'ID': NODE,
            'Orientation': 'Horizontal', '@Children': []}}} for name in ('Designer', 'Profiler')}
        super().__init__({'ak.wwise.core.getInfo': info,
            'ak.wwise.core.getProjectInfo': {'id': PROJECT, 'name': 'Sandbox', 'path': str(project)},
            URI + 'getLayoutNames': {'layouts': ['Designer', 'Profiler']},
            URI + 'getViewTypes': {'viewTypes': [{'viewName': 'ProjectExplorer', 'viewDisplayName': 'Project Explorer'}]},
            URI + 'getViewInstances': {'viewInstances': []}})

    def call(self, uri, args=None, options=None):
        if uri == URI + 'resetLayouts':
            self.calls.append((uri, args, options))
            return {}
        if uri == URI + 'getViewInstances':
            self.calls.append((uri, args, options))
            return {'viewInstances': deepcopy(self.views.get(args['name'], []))}
        if uri == URI + 'undockView':
            self.calls.append((uri, args, options))
            row = next(row for row in self.views[args['name']] if row['viewID'] == args['viewID'])
            row['viewIsDocked'] = False
            left, top = args.get('posX', 0), args.get('posY', 0)
            self.rectangles[row['viewID']] = {'left': left, 'top': top, 'right': left + 300, 'bottom': top + 400}
            return {}
        if uri == URI + 'closeView':
            self.calls.append((uri, args, options))
            self.views[self.current] = [row for row in self.views[self.current] if row['viewID'] != args['viewID']]
            return {}
        if uri == URI + 'getOrCreateView':
            self.calls.append((uri, args, options))
            existing = next((row for row in self.views[self.current] if row['viewName'] == args['name']), None)
            if existing:
                return {'id': existing['viewID']}
            view_id = '{22222222-2222-2222-2222-222222222222}'
            self.views[self.current].append({'viewID': view_id, 'viewName': args['name'], 'viewDisplayName': 'Project Explorer', 'viewIsDocked': False})
            left, top = args.get('posX', 100), args.get('posY', 200)
            self.rectangles[view_id] = {'left': left, 'top': top, 'right': left + 300, 'bottom': top + 400}
            return {'id': view_id}
        if uri == URI + 'getElementRectangle':
            self.calls.append((uri, args, options))
            return deepcopy(self.rectangles.get(args['id'], {}))
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
            self.views.setdefault(args['name'], [])
            return {}
        if uri == URI + 'removeLayout':
            self.calls.append((uri, args, options))
            self.layouts.pop(args['name'])
            self.views.pop(args['name'], None)
            return {}
        if uri == URI + 'getCurrentLayoutName':
            self.calls.append((uri, args, options))
            return {'name': self.current}
        if uri == URI + 'switchLayout':
            self.calls.append((uri, args, options))
            self.current = args['name']
            return {}
        return super().call(uri, args, options)


def switch_preview(tmp_path, *, version='2025.1', policy='ask_before_changes', operation='switchLayout', fields=(), client_setup=None, expect_check_error=False, expect_declaration_error=False, layout_name='Profiler', apply=False, expect_preview_error=False):
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version=version, project_modification_policy=policy)
    state_dir = tmp_path / 'state'
    state = ['--state-dir', str(state_dir)]
    client = LayoutClient(tmp_path, version=version)
    if client_setup is not None:
        client_setup(client)
    code, schema = gateway.execute_gateway(['--version', version, 'request-schema', URI + operation], env=env,
        client_factory=lambda _: pytest.fail('schema must stay offline'))
    assert code == 0, (schema.get('message'), schema.get('details'))
    code, inspected = gateway.execute_gateway([*state, 'layout-inspect', '--layout-name', layout_name],
        env=env, client_factory=lambda _: client)
    assert code == 0, inspected
    if callable(fields):
        fields = fields(inspected)
    code, started = gateway.execute_gateway([*state, *schema['continuation']['gateway_argv']], env=env,
        client_factory=lambda _: pytest.fail('Draft start must stay offline'))
    assert code == 0, (started.get('error_code'), started.get('message'), started.get('details'))
    draft = started['draft']
    authority = started['task_authority']
    code, declared = gateway.execute_gateway([*state, 'draft-declare-layout-plan', draft['draft_id'],
        '--task-authority', authority, '--expected-revision', str(draft['revision']),
        '--layout-handle', inspected['layout_handle'], *fields], env=env, client_factory=lambda _: client)
    if expect_declaration_error:
        assert code != 0, declared
        assert URI + operation not in [row[0] for row in client.calls]
        return env, state, client, declared
    assert code == 0, (declared.get('error_code'), declared.get('message'), declared.get('details'))
    code, checked = gateway.execute_gateway([*state, 'draft-check', draft['draft_id'],
        '--task-authority', authority, '--expected-revision', str(declared['draft']['revision'])],
        env=env, client_factory=lambda _: client)
    if expect_check_error:
        assert code != 0, checked
        assert URI + operation not in [call[0] for call in client.calls]
        return env, state, client, checked
    assert code == 0, (checked.get("error_code"), checked.get("message"), checked.get("details"))
    code, preview = gateway.execute_gateway([*state, 'preview-from-draft', draft['draft_id'],
        '--task-authority', authority, '--expected-revision', str(checked['draft']['revision']), *(['--apply'] if apply else [])],
        env=env, client_factory=lambda _: client)
    if expect_preview_error:
        assert code != 0, preview
        assert URI + operation not in [call[0] for call in client.calls]
        return env, state, client, preview
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


def confirm_execute_verify(env, state, client, preview, *, expect_verification_failure=False):
    tx = preview['transaction_id']
    code, shown = gateway.execute_gateway([*state, 'transaction-show', tx], env=env)
    assert code == 0, shown
    code, confirmed = gateway.execute_gateway([*state, 'confirm', tx, '--confirmation-token', shown['confirmation']['token']], env=env)
    assert code == 0, confirmed
    code, executed = gateway.execute_gateway([*state, 'execute', tx], env=env, client_factory=lambda _: client)
    assert code == 0, executed
    code, verified = gateway.execute_gateway([*state, 'verify', tx], env=env, client_factory=lambda _: client)
    assert (code != 0) if expect_verification_failure else (code == 0), verified
    return verified


@pytest.mark.parametrize('scope,selected,expected', [
    ('native_omission', (), {}), ('empty_selection', (), {'layouts': []}),
    ('selected_layouts', ('Profiler',), {'layouts': ['Profiler']}),
    ('selected_layouts', ('Profiler', 'Designer', 'Profiler'), {'layouts': ['Profiler', 'Designer', 'Profiler']}),
])
def test_reset_preserves_native_selection_forms_and_does_not_claim_default_effect(tmp_path, scope, selected, expected):
    def fields(inspected):
        # A second exact public inspection certifies each independently selected layout.
        result = ['--reset-scope', scope]
        for name in selected:
            if name == 'Profiler':
                handle = inspected['layout_handle']
            else:
                code, other = gateway.execute_gateway(['--state-dir', str(tmp_path / 'state'),
                    'layout-inspect', '--layout-name', name], env=env_holder[0], client_factory=lambda _: client_holder[0])
                assert code == 0, other
                handle = other['layout_handle']
            result.extend(['--reset-layout-handle', handle])
        return result
    env_holder, client_holder = [], []
    # The helper configures the same isolated file before calling our setup hook.
    def setup(client):
        client_holder.append(client)
        env_holder.append(gateway_env(tmp_path))
    env, state, client, preview = switch_preview(tmp_path, operation='resetLayouts', fields=fields, client_setup=setup)
    prepared = TransactionStore(Path(state[1])).load_preview(preview['transaction_id']).artifact['prepared_operation']
    assert prepared['dispatch'] == {'uri': URI + 'resetLayouts', 'args': expected, 'options': {}}
    verified = confirm_execute_verify(env, state, client, preview)
    assert verified['verification']['status'] == 'result_schema_checked'
    assert verified['verification']['business_state_verified'] is False
    assert verified['verified'] is False
    assert verified['verification']['verification_strength'] == 'result_schema_only'
    assert 'defaults' in prepared['verification_plan']['effect_boundary']
    code, repeated = gateway.execute_gateway([*state, 'execute', preview['transaction_id']], env=env, client_factory=lambda _: client)
    assert code != 0, repeated
    assert [call[0] for call in client.calls].count(URI + 'resetLayouts') == 1


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1'])
def test_reset_discovery_matches_independent_native_version_and_discloses_selection_uncertainty(tmp_path, version):
    from wwise_waapi.native_catalog import load_native_catalog
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version=version)
    native = load_native_catalog(version, 'wwise-authoring')
    assert (URI + 'resetLayouts' in native['functions']) is (version == '2025.1')
    code, schema = gateway.execute_gateway(['request-schema', URI + 'resetLayouts'], env=env,
        client_factory=lambda _: pytest.fail('schema discovery must stay offline'))
    if version != '2025.1':
        assert code != 0, schema
        return
    assert code == 0, schema
    text = str(schema)
    assert all(word in text for word in ('native_omission', 'empty_selection', 'selected_layouts', '--reset-layout-handle'))
    assert 'do not define' in text and 'default-state oracle' in text
    assert 'ordered native names only from selected handles' in text
    assert 'current-layout verifier' not in text
    code, described = gateway.execute_gateway(['describe', URI + 'resetLayouts', '--profile', 'wwise-authoring-ui'], env=env)
    assert code == 0, described
    assert described['availability'][version]['capability']['interface']['host_surface'] == 'wwise-authoring'


@pytest.mark.parametrize('fields', [(), ('--reset-scope', 'selected_layouts'),
    lambda i: ('--reset-scope', 'native_omission', '--reset-layout-handle', i['layout_handle']),
    lambda i: ('--reset-scope', 'empty_selection', '--reset-layout-handle', i['layout_handle']),
    lambda i: ['--reset-scope', 'selected_layouts', *(['--reset-layout-handle', i['layout_handle']] * 33)],
    ('--reset-scope', 'selected_layouts', '--reset-layout-handle', 'Profiler')])
def test_reset_rejects_incomplete_or_mixed_selection_and_unissued_names(tmp_path, fields):
    switch_preview(tmp_path, operation='resetLayouts', fields=fields, expect_declaration_error=True)


@pytest.mark.parametrize('drift', ['selected-layout', 'catalog', 'current', 'session', 'host'])
def test_reset_revalidates_actual_selected_layout_and_live_instance_before_dispatch(tmp_path, drift):
    holder = []
    def fields(inspected):
        code, selected = gateway.execute_gateway(['--state-dir', str(tmp_path / 'state'),
            'layout-inspect', '--layout-name', 'Designer'], env=gateway_env(tmp_path), client_factory=lambda _: holder[0])
        assert code == 0, selected
        return ['--reset-scope', 'selected_layouts', '--reset-layout-handle', selected['layout_handle']]
    env, state, client, preview = switch_preview(tmp_path, operation='resetLayouts', fields=fields, client_setup=holder.append)
    tx = preview['transaction_id']
    _, shown = gateway.execute_gateway([*state, 'transaction-show', tx], env=env)
    code, confirmed = gateway.execute_gateway([*state, 'confirm', tx, '--confirmation-token', shown['confirmation']['token']], env=env)
    assert code == 0, confirmed
    original = client.call
    def changed(uri, args=None, options=None):
        result = original(uri, args, options)
        if drift == 'selected-layout' and uri == URI + 'getLayout' and args['name'] == 'Designer':
            result['Layout']['StackPanel']['Orientation'] = 'Vertical'
        if drift == 'catalog' and uri == URI + 'getLayoutNames':
            result = {'layouts': ['Designer', 'Profiler', 'NewlyRegistered']}
        if drift == 'current' and uri == URI + 'getCurrentLayoutName':
            result = {'name': 'Profiler'}
        if uri == 'ak.wwise.core.getInfo':
            if drift == 'session': result = {**result, 'sessionId': 'another-session'}
            if drift == 'host': result = {**result, 'isCommandLine': True}
        return result
    client.call = changed
    code, rejected = gateway.execute_gateway([*state, 'execute', tx], env=env, client_factory=lambda _: client)
    assert code != 0, rejected
    assert URI + 'resetLayouts' not in [call[0] for call in client.calls]


@pytest.mark.parametrize('policy', ['read_only', 'ask_before_changes', 'allow_changes'])
def test_reset_retains_each_modification_policy_and_separate_durable_authority(tmp_path, policy):
    env, state, client, result = switch_preview(tmp_path, operation='resetLayouts', policy=policy,
        fields=('--reset-scope', 'native_omission'), apply=True, expect_preview_error=policy == 'read_only')
    assert URI + 'resetLayouts' not in [call[0] for call in client.calls]
    if policy == 'read_only':
        assert 'read_only' in str(result)
        return
    assert result['state'] == ('policy_authorized' if policy == 'allow_changes' else 'awaiting_confirmation')
    code, executed = gateway.execute_gateway([*state, 'execute', result['transaction_id']], env=env, client_factory=lambda _: client)
    assert (code == 0) is (policy == 'allow_changes'), executed
    events = TransactionStore(Path(state[1])).read_events(result['transaction_id'])
    assert any(row['event_type'] == 'policy_authorized' for row in events) is (policy == 'allow_changes')


@pytest.mark.parametrize('failure', ['extra-native-result', 'omitted-post-layout'])
def test_reset_does_not_hide_invalid_native_result_or_missing_post_observation(tmp_path, failure):
    env, state, client, preview = switch_preview(tmp_path, operation='resetLayouts',
        fields=lambda inspected: ['--reset-scope', 'selected_layouts', '--reset-layout-handle', inspected['layout_handle']])
    original = client.call
    dispatched = []
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri == URI + 'resetLayouts':
            dispatched.append(True)
            if failure == 'extra-native-result': return {'unexpected': 'original-result'}
        if dispatched and failure == 'omitted-post-layout' and uri == URI + 'getLayout':
            return {}
        return result
    client.call = call
    verified = confirm_execute_verify(env, state, client, preview, expect_verification_failure=True)
    assert verified['verification']['business_state_verified'] is False
    if failure == 'omitted-post-layout':
        assert any(row.get('uri') == URI + 'getLayout' and row['result'] == {} for row in verified['verification']['readbacks'])
    assert len(dispatched) == 1


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


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
@pytest.mark.parametrize('coordinates', [{}, {'initial_x': 17}, {'initial_y': 29}, {'initial_x': -1, 'initial_y': 45}])
def test_create_or_get_view_owns_live_type_and_preserves_each_optional_coordinate(tmp_path, version, coordinates):
    fields = ['--view-type', 'ProjectExplorer']
    for key, value in coordinates.items():
        fields.extend(['--' + key.replace('_', '-'), str(value)])
    env, state, client, preview = switch_preview(tmp_path, version=version, operation='getOrCreateView',
        layout_name='Designer', fields=fields)
    prepared = TransactionStore(Path(state[1])).load_preview(preview['transaction_id']).artifact['prepared_operation']
    expected = {'name': 'ProjectExplorer', **{ {'initial_x': 'posX', 'initial_y': 'posY'}[key]: value for key, value in coordinates.items()}}
    assert prepared['dispatch'] == {'uri': URI + 'getOrCreateView', 'args': expected, 'options': {}}
    verified = confirm_execute_verify(env, state, client, preview)
    assert verified['verification']['business_state_verified'] is True
    assert [row[0] for row in client.calls].count(URI + 'getOrCreateView') == 1
    assert client.views['Designer'][0]['viewName'] == 'ProjectExplorer'


def test_get_existing_view_does_not_claim_initial_position_was_applied(tmp_path):
    existing = '{33333333-3333-3333-3333-333333333333}'
    def setup(client):
        client.views['Designer'] = [{'viewID': existing, 'viewName': 'ProjectExplorer', 'viewIsDocked': True}]
    env, state, client, preview = switch_preview(tmp_path, operation='getOrCreateView', layout_name='Designer',
        fields=('--view-type', 'ProjectExplorer', '--initial-x', '17', '--initial-y', '29'), client_setup=setup)
    verified = confirm_execute_verify(env, state, client, preview)
    assert verified['verification']['business_state_verified'] is True
    assert client.views['Designer'] == [{'viewID': existing, 'viewName': 'ProjectExplorer', 'viewIsDocked': True}]
    assert URI + 'getElementRectangle' not in [row[0] for row in client.calls]


@pytest.mark.parametrize('failure', ['unknown_type', 'omitted_catalog', 'wrong_current_layout'])
def test_create_view_requires_fresh_type_authority_and_current_layout(tmp_path, failure):
    fields = ('--view-type', 'NoSuchView' if failure == 'unknown_type' else 'ProjectExplorer')
    setup = (lambda client: client.responses.update({URI + 'getViewTypes': {}})) if failure == 'omitted_catalog' else None
    switch_preview(tmp_path, operation='getOrCreateView', fields=fields,
        layout_name='Profiler' if failure == 'wrong_current_layout' else 'Designer', client_setup=setup, expect_check_error=True)


@pytest.mark.parametrize('drift', ['catalog', 'instances'])
def test_create_view_revalidates_live_catalog_and_instances_before_dispatch(tmp_path, drift):
    env, state, client, preview = switch_preview(tmp_path, operation='getOrCreateView', layout_name='Designer',
        fields=('--view-type', 'ProjectExplorer'))
    tx = preview['transaction_id']
    _, shown = gateway.execute_gateway([*state, 'transaction-show', tx], env=env)
    _, confirmed = gateway.execute_gateway([*state, 'confirm', tx, '--confirmation-token', shown['confirmation']['token']], env=env)
    assert confirmed['state'] == 'confirmed'
    if drift == 'catalog':
        client.responses[URI + 'getViewTypes'] = {'viewTypes': []}
    else:
        client.views['Designer'].append({'viewID': '{33333333-3333-3333-3333-333333333333}', 'viewName': 'ProjectExplorer'})
    code, rejected = gateway.execute_gateway([*state, 'execute', tx], env=env, client_factory=lambda _: client)
    assert code != 0, rejected
    assert URI + 'getOrCreateView' not in [row[0] for row in client.calls]


@pytest.mark.parametrize('failure', ['omitted_id', 'malformed_id', 'coordinate_mismatch'])
def test_created_view_return_is_not_enough_to_verify_identity_or_position(tmp_path, failure):
    env, state, client, preview = switch_preview(tmp_path, operation='getOrCreateView', layout_name='Designer',
        fields=('--view-type', 'ProjectExplorer', '--initial-x', '17'))
    original = client.call
    def damaged_result(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri == URI + 'getOrCreateView':
            if failure == 'omitted_id':
                return {}
            if failure == 'malformed_id':
                return {'id': 'not-a-guid'}
        if uri == URI + 'getElementRectangle' and failure == 'coordinate_mismatch':
            result['left'] = 18
        return result
    client.call = damaged_result
    verified = confirm_execute_verify(env, state, client, preview, expect_verification_failure=True)
    assert verified['verification']['business_state_verified'] is False
    if failure != 'coordinate_mismatch':
        assert verified['verification']['readbacks'] == []
    assert [row[0] for row in client.calls].count(URI + 'getOrCreateView') == 1


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1'])
def test_layout_version_absence_is_backed_by_independent_authoring_catalog(tmp_path, version):
    from wwise_waapi.authoring_layout import LAYOUT_READ_URIS
    from wwise_waapi.authoring_layout_business import LAYOUT_MUTATION_URIS
    from wwise_waapi.native_catalog import load_native_catalog
    native = load_native_catalog(version, 'wwise-authoring')
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version=version)
    for api in LAYOUT_READ_URIS | LAYOUT_MUTATION_URIS:
        assert api not in native['functions']
        code, rejected = gateway.execute_gateway(['request-schema', api], env=env,
            client_factory=lambda _: pytest.fail('native catalog absence must stay offline'))
        assert code != 0, rejected


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


def test_close_view_uses_discovered_identity_and_independent_absence_readback(tmp_path):
    def seed(client):
        client.views['Designer'] = [{'viewID': NODE, 'viewName': 'ProjectExplorer',
            'viewDisplayName': 'Project Explorer', 'viewIsDocked': False}]
    env, state, client, preview = switch_preview(tmp_path, operation='closeView', layout_name='Designer',
        fields=lambda inspected: ('--view-handle', inspected['views'][0]['handle']), client_setup=seed)
    prepared = TransactionStore(Path(state[1])).load_preview(preview['transaction_id']).artifact['prepared_operation']
    assert prepared['dispatch'] == {'uri': URI + 'closeView', 'args': {'viewID': NODE}, 'options': {}}
    assert URI + 'closeView' not in [row[0] for row in client.calls]
    verified = confirm_execute_verify(env, state, client, preview)
    assert verified['verification']['business_state_verified'] is True
    assert client.views['Designer'] == []
    assert [row[0] for row in client.calls].count(URI + 'closeView') == 1


@pytest.mark.parametrize('outcome', ['delayed', 'pending'])
def test_close_view_polls_bounded_readbacks_without_repeating_mutation(tmp_path, outcome):
    def seed(client):
        client.views['Designer'] = [{'viewID': NODE, 'viewName': 'ProjectExplorer',
            'viewDisplayName': 'Project Explorer', 'viewIsDocked': False}]
    env, state, client, preview = switch_preview(tmp_path, operation='closeView', layout_name='Designer',
        fields=lambda inspected: ('--view-handle', inspected['views'][0]['handle']), client_setup=seed)
    original = client.call
    polls = []
    requested = False
    def call(uri, args=None, options=None):
        nonlocal requested
        if uri == URI + 'closeView':
            client.calls.append((uri, args, options))
            requested = True
            return {}
        if requested and uri == URI + 'getViewInstances':
            polls.append(uri)
            if outcome == 'delayed' and len(polls) == 3:
                client.views['Designer'] = []
        return original(uri, args, options)
    client.call = call
    verified = confirm_execute_verify(env, state, client, preview, expect_verification_failure=outcome == 'pending')
    assert len(polls) == (3 if outcome == 'delayed' else 16)
    assert verified['verification']['business_state_verified'] is (outcome == 'delayed')
    assert [row[0] for row in client.calls].count(URI + 'closeView') == 1
    if outcome == 'pending':
        pending_checks = [row for row in verified['verification']['assertions']
                          if row['evidence'].get('pending_async_close') is True]
        assert len(pending_checks) == 1
        assert pending_checks[0]['passed'] is False
        assert pending_checks[0]['evidence'] == {'view_id': NODE, 'pending_async_close': True, 'polls': 16}


@pytest.mark.parametrize('operation', ['closeView', 'undockView'])
@pytest.mark.parametrize('drift', ['view', 'disappeared', 'current'])
def test_scoped_view_mutations_revalidate_discovery_immediately_before_dispatch(tmp_path, drift, operation):
    def seed(client):
        client.views['Designer'] = [{'viewID': NODE, 'viewName': 'ProjectExplorer',
            'viewDisplayName': 'Project Explorer', 'viewIsDocked': False}]
    env, state, client, preview = switch_preview(tmp_path, operation=operation, layout_name='Designer',
        fields=lambda inspected: ('--view-handle', inspected['views'][0]['handle']), client_setup=seed)
    if drift == 'view':
        client.views['Designer'][0]['viewIsDocked'] = True
    elif drift == 'disappeared':
        client.views['Designer'] = []
    else:
        client.current = 'Profiler'
    tx = preview['transaction_id']
    code, shown = gateway.execute_gateway([*state, 'transaction-show', tx], env=env)
    assert code == 0, shown
    code, confirmed = gateway.execute_gateway([*state, 'confirm', tx, '--confirmation-token', shown['confirmation']['token']], env=env)
    assert code == 0, confirmed
    code, rejected = gateway.execute_gateway([*state, 'execute', tx], env=env, client_factory=lambda _: client)
    assert code != 0, rejected
    assert URI + operation not in [row[0] for row in client.calls]


def test_close_view_2024_absence_is_independently_reflected_and_rejected_offline(tmp_path):
    from wwise_waapi.native_catalog import load_native_catalog
    assert URI + 'closeView' not in load_native_catalog('2024.1', 'wwise-authoring')['functions']
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version='2024.1')
    code, schema = gateway.execute_gateway(['request-schema', URI + 'closeView'], env=env,
        client_factory=lambda _: pytest.fail('unsupported schema must not connect'))
    assert code != 0, schema


@pytest.mark.parametrize('operation', ['closeView', 'undockView'])
@pytest.mark.parametrize('kind', ['layout', 'element'])
def test_scoped_view_mutations_reject_other_handle_roles_without_dispatch(tmp_path, kind, operation):
    switch_preview(tmp_path, operation=operation, layout_name='Designer', expect_declaration_error=True,
        fields=lambda inspected: ('--view-handle', inspected['layout_handle'] if kind == 'layout' else inspected['elements'][0]['handle']))


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
@pytest.mark.parametrize('coordinates', [{}, {'position_x': 30}, {'position_y': 50}, {'position_x': -5, 'position_y': 10}])
def test_undock_view_preserves_optional_position_choices_and_verifies_floating_identity(tmp_path, version, coordinates):
    def seed(client):
        client.views['Designer'] = [{'viewID': NODE, 'viewName': 'ProjectExplorer',
            'viewDisplayName': 'Project Explorer', 'viewIsDocked': True}]
    def fields(inspected):
        result = ['--view-handle', inspected['views'][0]['handle']]
        for key, value in coordinates.items():
            result.extend(['--' + key.replace('_', '-'), str(value)])
        return result
    env, state, client, preview = switch_preview(tmp_path, version=version, operation='undockView', layout_name='Designer',
        fields=fields, client_setup=seed)
    prepared = TransactionStore(Path(state[1])).load_preview(preview['transaction_id']).artifact['prepared_operation']
    native_args = {'name': 'Designer', 'viewID': NODE}
    native_args.update({{'position_x': 'posX', 'position_y': 'posY'}[key]: value for key, value in coordinates.items()})
    assert prepared['dispatch'] == {'uri': URI + 'undockView', 'args': native_args, 'options': {}}
    verified = confirm_execute_verify(env, state, client, preview)
    assert verified['verification']['business_state_verified'] is True
    assert client.views['Designer'][0]['viewIsDocked'] is False
    assert [row[0] for row in client.calls].count(URI + 'undockView') == 1


@pytest.mark.parametrize('failure', ['no-effect', 'missing', 'different-type', 'coordinate'])
def test_undock_never_certifies_a_returned_empty_result_without_requested_business_state(tmp_path, failure):
    def seed(client):
        client.views['Designer'] = [{'viewID': NODE, 'viewName': 'ProjectExplorer',
            'viewDisplayName': 'Project Explorer', 'viewIsDocked': True}]
    env, state, client, preview = switch_preview(tmp_path, operation='undockView', layout_name='Designer',
        fields=lambda inspected: ('--view-handle', inspected['views'][0]['handle'], '--position-x', '30'), client_setup=seed)
    original = client.call
    def wrong_effect(uri, args=None, options=None):
        if uri == URI + 'undockView':
            if failure == 'no-effect':
                client.calls.append((uri, args, options))
            else:
                original(uri, args, options)
                if failure == 'missing':
                    client.views['Designer'] = []
                elif failure == 'different-type':
                    client.views['Designer'][0]['viewName'] = 'SomeOtherView'
                else:
                    client.rectangles[NODE]['left'] = 31
            return {}
        return original(uri, args, options)
    client.call = wrong_effect
    verified = confirm_execute_verify(env, state, client, preview, expect_verification_failure=True)
    assert verified['verification']['business_state_verified'] is False
    assert [row[0] for row in client.calls].count(URI + 'undockView') == 1


def _seed_dock_client(client, *, initially_docked=False):
    view_id = '{22222222-2222-2222-2222-222222222222}'
    client.views['Designer'] = [{'viewID': view_id, 'viewName': 'ProjectExplorer',
        'viewDisplayName': 'Project Explorer', 'viewIsDocked': initially_docked}]
    anchor_id = '{33333333-3333-3333-3333-333333333333}'
    client.layouts['Designer']['Layout']['StackPanel']['@Children'] = [
        {'@type': 'ObjectPanel', 'ID': anchor_id, 'Name': 'Existing target contents'}]
    client.rectangles[anchor_id] = {'left': 100, 'top': 100, 'right': 400, 'bottom': 500}
    client.rectangles[NODE] = dict(client.rectangles[anchor_id])
    client.rectangles[view_id] = {'left': 600, 'top': 100, 'right': 900, 'bottom': 500}
    if initially_docked:
        client.layouts['Designer']['Layout']['StackPanel']['@Children'].append(
            {'@type': 'View', 'ID': view_id, 'Name': 'ProjectExplorer', 'SelectionChannel': '1'})
        client.rectangles[NODE]['right'] = 900
    original = client.call
    def dock(uri, args=None, options=None):
        if uri == URI + 'dockView':
            client.calls.append((uri, args, options))
            client.views['Designer'][0]['viewIsDocked'] = True
            client.rectangles[view_id] = {
                'left': {'left': 0, 'top': 100, 'right': 90, 'bottom': 500},
                'right': {'left': 410, 'top': 100, 'right': 500, 'bottom': 500},
                'top': {'left': 100, 'top': 0, 'right': 400, 'bottom': 90},
                'bottom': {'left': 100, 'top': 510, 'right': 400, 'bottom': 600},
            }[args['side']]
            stack = client.layouts['Designer']['Layout']['StackPanel']
            anchor = deepcopy(next(child for child in stack['@Children'] if child['ID'] == anchor_id))
            view = {'@type': 'View', 'ID': view_id, 'Name': 'ProjectExplorer', 'SelectionChannel': '1'}
            stack['Orientation'] = 'Horizontal' if args['side'] in {'left', 'right'} else 'Vertical'
            stack['@Children'] = [view, anchor] if args['side'] in {'left', 'top'} else [anchor, view]
            v, a = client.rectangles[view_id], client.rectangles[anchor_id]
            client.rectangles[NODE] = {'left': min(v['left'], a['left']), 'top': min(v['top'], a['top']),
                'right': max(v['right'], a['right']), 'bottom': max(v['bottom'], a['bottom'])}
            return {}
        return original(uri, args, options)
    client.call = dock

@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
@pytest.mark.parametrize('side', ['left', 'right', 'top', 'bottom'])
@pytest.mark.parametrize('initially_docked', [False, True], ids=['floating', 'redock'])
def test_dock_view_binds_exact_target_side_and_verifies_independent_geometry(tmp_path, version, side, initially_docked):
    view_id = '{22222222-2222-2222-2222-222222222222}'
    def seed(client):
        _seed_dock_client(client, initially_docked=initially_docked)
    env, state, client, preview = switch_preview(tmp_path, version=version, operation='dockView', layout_name='Designer',
        fields=lambda inspected: ('--view-handle', inspected['views'][0]['handle'],
            '--target-element-handle', inspected['elements'][0]['handle'], '--dock-side', side), client_setup=seed)
    prepared = TransactionStore(Path(state[1])).load_preview(preview['transaction_id']).artifact['prepared_operation']
    assert prepared['dispatch'] == {'uri': URI + 'dockView', 'args': {
        'name': 'Designer', 'viewID': view_id, 'targetID': NODE, 'side': side}, 'options': {}}
    verified = confirm_execute_verify(env, state, client, preview)
    assert verified['verification']['business_state_verified'] is True
    assert [row[0] for row in client.calls].count(URI + 'dockView') == 1


@pytest.mark.parametrize('failure', ['wrong-side', 'missing-view', 'different-view-type', 'missing-target', 'current-layout', 'container-overlap', 'no-perpendicular-overlap', 'unrelated-placement', 'wrong-order', 'wrong-orientation', 'no-effect'])
def test_dock_does_not_certify_a_docked_flag_without_exact_target_side_effect(tmp_path, failure):
    env, state, client, preview = switch_preview(tmp_path, operation='dockView', layout_name='Designer',
        fields=lambda inspected: ('--view-handle', inspected['views'][0]['handle'],
            '--target-element-handle', inspected['elements'][0]['handle'], '--dock-side', 'left'), client_setup=_seed_dock_client)
    original = client.call
    view_id = '{22222222-2222-2222-2222-222222222222}'
    def wrong_effect(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri == URI + 'dockView':
            if failure == 'wrong-side':
                client.rectangles[view_id] = {'left': 410, 'top': 100, 'right': 500, 'bottom': 500}
            elif failure == 'missing-view':
                client.views['Designer'] = []
            elif failure == 'different-view-type':
                client.views['Designer'][0]['viewName'] = 'OtherView'
            elif failure == 'missing-target':
                client.layouts['Designer']['Layout']['StackPanel']['ID'] = '{33333333-3333-3333-3333-333333333333}'
            elif failure == 'current-layout':
                client.current = 'Profiler'
            elif failure == 'container-overlap':
                client.rectangles[view_id] = {'left': 100, 'top': 100, 'right': 200, 'bottom': 500}
            elif failure == 'no-perpendicular-overlap':
                client.rectangles[view_id] = {'left': 0, 'top': 600, 'right': 90, 'bottom': 700}
            elif failure == 'unrelated-placement':
                client.layouts['Designer']['Layout']['StackPanel']['@Children'] = []
            elif failure == 'wrong-order':
                client.layouts['Designer']['Layout']['StackPanel']['@Children'].reverse()
            elif failure == 'wrong-orientation':
                client.layouts['Designer']['Layout']['StackPanel']['Orientation'] = 'Vertical'
            else:
                client.views['Designer'][0]['viewIsDocked'] = False
        return result
    client.call = wrong_effect
    verified = confirm_execute_verify(env, state, client, preview, expect_verification_failure=True)
    assert verified['verification']['business_state_verified'] is False
    assert [row[0] for row in client.calls].count(URI + 'dockView') == 1


def test_dock_revalidates_target_rectangle_immediately_before_the_single_write(tmp_path):
    env, state, client, preview = switch_preview(tmp_path, operation='dockView', layout_name='Designer',
        fields=lambda inspected: ('--view-handle', inspected['views'][0]['handle'],
            '--target-element-handle', inspected['elements'][0]['handle'], '--dock-side', 'left'), client_setup=_seed_dock_client)
    tx = preview['transaction_id']
    _, shown = gateway.execute_gateway([*state, 'transaction-show', tx], env=env)
    code, _ = gateway.execute_gateway([*state, 'confirm', tx, '--confirmation-token', shown['confirmation']['token']], env=env)
    assert code == 0
    client.rectangles[NODE]['left'] = 101
    code, result = gateway.execute_gateway([*state, 'execute', tx], env=env, client_factory=lambda _: client)
    assert code != 0, result
    assert URI + 'dockView' not in [row[0] for row in client.calls]


def test_dock_rejects_the_same_native_view_and_target_even_with_different_role_handles(tmp_path):
    def seed(client):
        _seed_dock_client(client)
        client.views['Designer'][0]['viewID'] = NODE
    switch_preview(tmp_path, operation='dockView', layout_name='Designer',
        fields=lambda inspected: ('--view-handle', inspected['views'][0]['handle'],
            '--target-element-handle', inspected['elements'][0]['handle'], '--dock-side', 'left'), client_setup=seed,
        expect_declaration_error=True)


def test_dock_accepts_finite_fractional_native_rectangles_without_integer_coercion(tmp_path):
    def seed(client):
        _seed_dock_client(client)
        client.rectangles[NODE] = {'left': 100.5, 'top': 100.5, 'right': 400.5, 'bottom': 500.5}
        client.rectangles['{33333333-3333-3333-3333-333333333333}'] = dict(client.rectangles[NODE])
    env, state, client, preview = switch_preview(tmp_path, operation='dockView', layout_name='Designer',
        fields=lambda inspected: ('--view-handle', inspected['views'][0]['handle'],
            '--target-element-handle', inspected['elements'][0]['handle'], '--dock-side', 'left'), client_setup=seed)
    prepared = TransactionStore(Path(state[1])).load_preview(preview['transaction_id']).artifact['prepared_operation']
    assert prepared['pre_state']['layout_dock_prestate']['rectangles']['target']['left'] == 100.5
    assert confirm_execute_verify(env, state, client, preview)['verification']['business_state_verified'] is True


@pytest.mark.parametrize('wrong_target', ['view-role', 'other-layout'])
def test_dock_rejects_wrong_role_or_foreign_layout_target_before_any_write(tmp_path, wrong_target):
    env, state, client, _ = switch_preview(tmp_path, operation='dockView', layout_name='Designer',
        fields=lambda inspected: ('--view-handle', inspected['views'][0]['handle'],
            '--target-element-handle', inspected['elements'][0]['handle'], '--dock-side', 'left'), client_setup=_seed_dock_client)
    _, selected = gateway.execute_gateway([*state, 'layout-inspect', '--layout-name', 'Designer'], env=env, client_factory=lambda _: client)
    if wrong_target == 'view-role':
        target = selected['views'][0]['handle']
    else:
        _, foreign = gateway.execute_gateway([*state, 'layout-inspect', '--layout-name', 'Profiler'], env=env, client_factory=lambda _: client)
        target = foreign['elements'][0]['handle']
    _, schema = gateway.execute_gateway(['--version', '2025.1', 'request-schema', URI + 'dockView'], env=env)
    _, started = gateway.execute_gateway([*state, *schema['continuation']['gateway_argv']], env=env)
    draft = started['draft']
    code, result = gateway.execute_gateway([*state, 'draft-declare-layout-plan', draft['draft_id'],
        '--task-authority', started['task_authority'], '--expected-revision', str(draft['revision']),
        '--layout-handle', selected['layout_handle'], '--view-handle', selected['views'][0]['handle'],
        '--target-element-handle', target, '--dock-side', 'left'], env=env, client_factory=lambda _: client)
    assert code != 0, result
    assert URI + 'dockView' not in [row[0] for row in client.calls]


@pytest.mark.parametrize('target_kind', ['ObjectPanel', 'ObjectTabPanel', 'View', 'StackPanel'])
@pytest.mark.parametrize('side', ['left', 'bottom'])
def test_dock_keeps_exact_leaf_and_nested_container_target_kinds_representable(tmp_path, target_kind, side):
    target_id = '{33333333-3333-3333-3333-333333333333}'
    def seed(client):
        _seed_dock_client(client)
        anchor = client.layouts['Designer']['Layout']['StackPanel']['@Children'][0]
        anchor['@type'] = target_kind
        if target_kind == 'StackPanel':
            anchor.update(Orientation='Vertical', **{'@Children': [{'@type': 'ObjectPanel', 'ID': 'retained inner panel'}]})
    env, state, client, preview = switch_preview(tmp_path, operation='dockView', layout_name='Designer',
        fields=lambda inspected: ('--view-handle', inspected['views'][0]['handle'], '--target-element-handle',
            next(row['handle'] for row in inspected['elements'] if row.get('name') == 'Existing target contents'), '--dock-side', side), client_setup=seed)
    prepared = TransactionStore(Path(state[1])).load_preview(preview['transaction_id']).artifact['prepared_operation']
    assert prepared['dispatch']['args']['targetID'] == target_id
    verified = confirm_execute_verify(env, state, client, preview)
    assert verified['verification']['business_state_verified'] is True
    assert [row[0] for row in client.calls].count(URI + 'dockView') == 1


@pytest.mark.parametrize('damage', ['dropped', 'retagged'])
def test_dock_rejects_correct_side_when_an_unrelated_existing_view_is_lost_or_retagged(tmp_path, damage):
    unrelated_id = '{55555555-5555-5555-5555-555555555555}'
    def seed(client):
        _seed_dock_client(client)
        client.views['Designer'].append({'viewID': unrelated_id, 'viewName': 'Transport',
            'viewDisplayName': 'Transport', 'viewIsDocked': True})
        client.layouts['Designer']['Layout']['StackPanel']['@Children'].append(
            {'@type': 'View', 'ID': unrelated_id, 'Name': 'Transport'})
    env, state, client, preview = switch_preview(tmp_path, operation='dockView', layout_name='Designer',
        fields=lambda inspected: ('--view-handle', inspected['views'][0]['handle'],
            '--target-element-handle', inspected['elements'][0]['handle'], '--dock-side', 'left'), client_setup=seed)
    original = client.call
    def damage_other_view(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri == URI + 'dockView':
            if damage == 'dropped':
                client.views['Designer'] = [row for row in client.views['Designer'] if row['viewID'] != unrelated_id]
            else:
                next(row for row in client.views['Designer'] if row['viewID'] == unrelated_id)['viewName'] = 'QueryEditor'
        return result
    client.call = damage_other_view
    verified = confirm_execute_verify(env, state, client, preview, expect_verification_failure=True)
    assert verified['verification']['business_state_verified'] is False
    assert [row[0] for row in client.calls].count(URI + 'dockView') == 1


@pytest.mark.parametrize('initially_docked', [False, True], ids=['floating', 'redock'])
def test_dock_preserves_other_views_while_allowing_container_restructuring_and_dock_state_changes(tmp_path, initially_docked):
    unrelated_id = '{55555555-5555-5555-5555-555555555555}'
    unrelated_node = {'@type': 'View', 'ID': unrelated_id, 'Name': 'Transport'}
    def seed(client):
        _seed_dock_client(client, initially_docked=initially_docked)
        client.views['Designer'].append({'viewID': unrelated_id, 'viewName': 'Transport',
            'viewDisplayName': 'Transport', 'viewIsDocked': False})
        client.layouts['Designer']['Layout']['StackPanel']['@Children'].append(
            {'@type': 'StackPanel', 'ID': 'old wrapper', 'Orientation': 'Vertical', '@Children': [unrelated_node]})
    env, state, client, preview = switch_preview(tmp_path, operation='dockView', layout_name='Designer',
        fields=lambda inspected: ('--view-handle', inspected['views'][0]['handle'],
            '--target-element-handle', inspected['elements'][0]['handle'], '--dock-side', 'left'), client_setup=seed)
    original = client.call
    def restructure(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri == URI + 'dockView':
            client.layouts['Designer']['Layout']['StackPanel']['@Children'].append(deepcopy(unrelated_node))
            client.views['Designer'][1]['viewIsDocked'] = True
        return result
    client.call = restructure
    verified = confirm_execute_verify(env, state, client, preview)
    assert verified['verification']['business_state_verified'] is True
    assert 'old wrapper' not in str(client.layouts['Designer'])
    assert [row[0] for row in client.calls].count(URI + 'dockView') == 1
