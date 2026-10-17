"""Nested layout construction through the public closed business declaration."""
from pathlib import Path
import json
import re
import pytest

from tests.unit.test_authoring_layout_mutation_gateway import URI, switch_preview, confirm_execute_verify, gateway, LayoutClient
from tests.support.gateway_config import set_gateway_config
from tests.unit.test_waapi_gateway import gateway_env
from wwise_waapi.transactions import TransactionStore


def _blueprint():
    return {'contract': 'waapi-skill.layout-blueprint/v1', 'root': 'main', 'nodes': [
        {'key': 'main', 'kind': 'stack', 'label': 'Main workspace', 'orientation': 'horizontal', 'children': ['tools', 'editors']},
        {'key': 'tools', 'kind': 'view', 'view_type': 'ProjectExplorer', 'selection_channel': '1', 'width': '280'},
        {'key': 'editors', 'kind': 'stack', 'label': 'Editors', 'orientation': 'vertical', 'children': []}]}


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
def test_nested_blueprint_owns_stable_ids_and_verifies_declared_stack_and_view_state(tmp_path, version):
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version=version)
    code, schema = gateway.execute_gateway(['--version', version, 'request-schema', URI + 'setLayout'], env=env)
    assert code == 0
    assert 'blueprint' in schema['business_adapter']['declaration']['public_fields']
    env, state, client, preview = switch_preview(tmp_path, version=version, operation='setLayout',
        fields=('--new-layout-name', 'NestedOwnedLayout', '--blueprint', json.dumps(_blueprint())))
    prepared = TransactionStore(Path(state[1])).load_preview(preview['transaction_id']).artifact['prepared_operation']
    root = prepared['dispatch']['args']['layout']['Layout']['StackPanel']
    assert root['Name'] == 'Main workspace' and root['Orientation'] == 'Horizontal'
    assert root['@Children'][0]['Name'] == 'ProjectExplorer'
    assert root['@Children'][0]['SelectionChannel'] == '1'
    assert root['@Children'][0]['Width'] == '280'
    assert root['@Children'][1]['Orientation'] == 'Vertical'
    identities = [root['ID'], root['@Children'][0]['ID'], root['@Children'][1]['ID']]
    assert len(set(identities)) == 3
    assert all(re.fullmatch(r'\{[0-9A-F]{8}-(?:[0-9A-F]{4}-){3}[0-9A-F]{12}\}', identity) for identity in identities)
    assert URI + 'setLayout' not in [row[0] for row in client.calls]
    verified = confirm_execute_verify(env, state, client, preview)
    assert verified['verification']['business_state_verified'] is True
    assert client.layouts['NestedOwnedLayout']['Layout']['StackPanel'] == root
    assert [row[0] for row in client.calls].count(URI + 'setLayout') == 1


def test_invalid_nested_tree_is_rejected_before_opening_live_connection(tmp_path):
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version='2025.1')
    blueprint = _blueprint()
    blueprint['nodes'][2]['children'] = ['main']
    state = ['--state-dir', str(tmp_path / 'state')]
    client = LayoutClient(tmp_path)
    code, inspected = gateway.execute_gateway([*state, 'layout-inspect', '--layout-name', 'Designer'], env=env, client_factory=lambda _: client)
    assert code == 0
    _, schema = gateway.execute_gateway(['--version', '2025.1', 'request-schema', URI + 'setLayout'], env=env)
    code, started = gateway.execute_gateway([*state, *schema['continuation']['gateway_argv']], env=env)
    assert code == 0
    code, result = gateway.execute_gateway([*state, 'draft-declare-layout-plan', started['draft']['draft_id'],
        '--task-authority', started['task_authority'], '--expected-revision', str(started['draft']['revision']), '--layout-handle', inspected['layout_handle'],
        '--new-layout-name', 'NeverWritten', '--blueprint', json.dumps(blueprint)], env=env,
        client_factory=lambda _: pytest.fail('invalid blueprint must stop before opening a client'))
    assert code != 0
    assert 'blueprint' in result['message'].lower()


def test_nested_blueprint_requires_its_exact_view_types_in_fresh_catalog(tmp_path):
    blueprint = _blueprint()
    blueprint['nodes'][1]['view_type'] = 'UnobservedView'
    _, _, _, rejected = switch_preview(tmp_path, operation='setLayout',
        fields=('--new-layout-name', 'NeverWritten', '--blueprint', json.dumps(blueprint)), expect_check_error=True)
    assert rejected['error_code'] == 'INVALID_LAYOUT_BLUEPRINT_VIEW_TYPE'


@pytest.mark.parametrize('damage', ['orientation', 'order', 'selection-channel', 'width', 'view-type', 'child-missing', 'node-id', 'name-only'])
def test_nested_registration_does_not_certify_name_without_every_requested_field_and_order(tmp_path, damage):
    env, state, client, preview = switch_preview(tmp_path, operation='setLayout',
        fields=('--new-layout-name', 'NestedOwnedLayout', '--blueprint', json.dumps(_blueprint())))
    original = client.call
    def wrong_layout(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri == URI + 'setLayout':
            layout = client.layouts['NestedOwnedLayout']['Layout']
            root = layout['StackPanel']
            if damage == 'orientation':
                root['Orientation'] = 'Vertical'
            elif damage == 'order':
                root['@Children'].reverse()
            elif damage == 'selection-channel':
                root['@Children'][0]['SelectionChannel'] = '2'
            elif damage == 'width':
                root['@Children'][0]['Width'] = '281'
            elif damage == 'view-type':
                root['@Children'][0]['Name'] = 'Transport'
            elif damage == 'child-missing':
                root['@Children'].pop()
            elif damage == 'node-id':
                root['ID'] = '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}'
            else:
                del layout['StackPanel']
        return result
    client.call = wrong_layout
    verified = confirm_execute_verify(env, state, client, preview, expect_verification_failure=True)
    assert verified['verification']['business_state_verified'] is False
    assert [row[0] for row in client.calls].count(URI + 'setLayout') == 1


def test_nested_registration_rechecks_exact_view_catalog_before_write(tmp_path):
    env, state, client, preview = switch_preview(tmp_path, operation='setLayout',
        fields=('--new-layout-name', 'NestedOwnedLayout', '--blueprint', json.dumps(_blueprint())))
    tx = preview['transaction_id']
    _, shown = gateway.execute_gateway([*state, 'transaction-show', tx], env=env)
    code, _ = gateway.execute_gateway([*state, 'confirm', tx, '--confirmation-token', shown['confirmation']['token']], env=env)
    assert code == 0
    original = client.call
    def changed_catalog(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri == URI + 'getViewTypes':
            return {'viewTypes': []}
        return result
    client.call = changed_catalog
    code, result = gateway.execute_gateway([*state, 'execute', tx], env=env, client_factory=lambda _: client)
    assert code != 0, result
    assert URI + 'setLayout' not in [row[0] for row in client.calls]


@pytest.mark.parametrize('malformation', ['native-fields', 'native-id', 'shared-node', 'dangling-node', 'disconnected-node', 'duplicate-key', 'unknown-kind', 'numeric-width', 'duplicate-child'])
def test_blueprint_closed_graph_rejects_native_escape_and_invalid_structure_before_client(tmp_path, malformation):
    blueprint = _blueprint()
    if malformation == 'native-fields':
        blueprint['Layout'] = {'Name': 'native'}
    elif malformation == 'native-id':
        blueprint['nodes'][0]['ID'] = '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}'
    elif malformation == 'shared-node':
        blueprint['nodes'][2]['children'] = ['tools']
    elif malformation == 'dangling-node':
        blueprint['nodes'][0]['children'].append('absent')
    elif malformation == 'disconnected-node':
        blueprint['nodes'][0]['children'] = ['tools']
    elif malformation == 'duplicate-key':
        blueprint['nodes'][2]['key'] = 'main'
    elif malformation == 'unknown-kind':
        blueprint['nodes'][1]['kind'] = 'raw-node'
    elif malformation == 'numeric-width':
        blueprint['nodes'][1]['width'] = 280
    else:
        blueprint['nodes'][0]['children'].append('tools')
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version='2025.1')
    state = ['--state-dir', str(tmp_path / 'state')]
    client = LayoutClient(tmp_path)
    code, inspected = gateway.execute_gateway([*state, 'layout-inspect', '--layout-name', 'Designer'], env=env, client_factory=lambda _: client)
    assert code == 0
    _, schema = gateway.execute_gateway(['--version', '2025.1', 'request-schema', URI + 'setLayout'], env=env)
    code, started = gateway.execute_gateway([*state, *schema['continuation']['gateway_argv']], env=env)
    assert code == 0
    code, result = gateway.execute_gateway([*state, 'draft-declare-layout-plan', started['draft']['draft_id'], '--task-authority', started['task_authority'],
        '--expected-revision', str(started['draft']['revision']), '--layout-handle', inspected['layout_handle'], '--new-layout-name', 'NeverWritten',
        '--blueprint', json.dumps(blueprint)], env=env, client_factory=lambda _: pytest.fail('invalid graph must remain offline'))
    assert code != 0
    assert 'blueprint' in result['message'].lower()


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
def test_nested_workspace_name_can_differ_from_temporary_lookup_name(tmp_path, version):
    # Matching 2025 SDK getLayout example documents this distinction; this is fake
    # contract coverage and does not claim native divergent-name write acceptance.
    blueprint = _blueprint()
    blueprint['workspace_name'] = 'SerializedLayout'
    env, state, client, preview = switch_preview(tmp_path, version=version, operation='setLayout',
        fields=('--new-layout-name', 'TemporaryLookupName', '--blueprint', json.dumps(blueprint)))
    prepared = TransactionStore(Path(state[1])).load_preview(preview['transaction_id']).artifact['prepared_operation']
    assert prepared['dispatch']['args']['name'] == 'TemporaryLookupName'
    assert prepared['dispatch']['args']['layout']['Layout']['Name'] == 'SerializedLayout'
    verified = confirm_execute_verify(env, state, client, preview)
    assert verified['verification']['business_state_verified'] is True
    assert client.layouts['TemporaryLookupName']['Layout']['Name'] == 'SerializedLayout'


def test_advertised_maximum_blueprint_depth_can_be_read_back_and_verified(tmp_path):
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version='2025.1')
    _, schema = gateway.execute_gateway(['--version', '2025.1', 'request-schema', URI + 'setLayout'], env=env)
    depth = schema['business_adapter']['blueprint_schema']['gateway_bounds']['maximum_depth']
    blueprint = {'contract': 'waapi-skill.layout-blueprint/v1', 'root': 'n0', 'nodes': [
        {'key': 'n' + str(index), 'kind': 'stack', 'label': 'Nested workspace', 'orientation': 'vertical',
            'children': ['n' + str(index + 1)] if index + 1 < depth else []} for index in range(depth)]}
    env, state, client, preview = switch_preview(tmp_path, operation='setLayout',
        fields=('--new-layout-name', 'DeepOwnedLayout', '--blueprint', json.dumps(blueprint)))
    verified = confirm_execute_verify(env, state, client, preview)
    assert verified['verification']['business_state_verified'] is True


def test_fifteen_level_blueprint_exceeds_gateway_resource_bound_before_any_client_or_write(tmp_path):
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version='2025.1')
    state = ['--state-dir', str(tmp_path / 'state')]
    client = LayoutClient(tmp_path)
    _, inspected = gateway.execute_gateway([*state, 'layout-inspect', '--layout-name', 'Designer'], env=env, client_factory=lambda _: client)
    _, schema = gateway.execute_gateway(['--version', '2025.1', 'request-schema', URI + 'setLayout'], env=env)
    assert schema['business_adapter']['blueprint_schema']['gateway_bounds']['maximum_depth'] == 14
    _, started = gateway.execute_gateway([*state, *schema['continuation']['gateway_argv']], env=env)
    blueprint = {'contract': 'waapi-skill.layout-blueprint/v1', 'root': 'n0', 'nodes': [
        {'key': 'n' + str(index), 'kind': 'stack', 'label': 'Nested workspace', 'orientation': 'vertical',
            'children': ['n' + str(index + 1)] if index < 14 else []} for index in range(15)]}
    calls_before = list(client.calls)
    code, result = gateway.execute_gateway([*state, 'draft-declare-layout-plan', started['draft']['draft_id'],
        '--task-authority', started['task_authority'], '--expected-revision', str(started['draft']['revision']),
        '--layout-handle', inspected['layout_handle'], '--new-layout-name', 'NeverWritten', '--blueprint', json.dumps(blueprint)],
        env=env, client_factory=lambda _: pytest.fail('resource bound must stop before opening a client'))
    assert code != 0 and 'blueprint' in result['message'].lower()
    assert client.calls == calls_before
    assert URI + 'setLayout' not in [row[0] for row in client.calls]
