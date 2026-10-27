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
def test_object_editor_and_tab_panels_keep_explicit_state_and_empty_editor_lists(tmp_path, version):
    blueprint = _blueprint()
    blueprint['nodes'][0]['children'] = ['panel', 'tabs']
    blueprint['nodes'][1:] = [
        {'key': 'panel', 'kind': 'object_panel', 'label': 'Object editor',
         'editor_state': 'maximized', 'bottom_editor_state': 'minimized',
         'editor_priority': [], 'preferred_heights': [],
         'sidebar': {'width': '210', 'collapse_state': ''}},
        {'key': 'tabs', 'kind': 'object_tabs', 'label': 'Object tabs', 'height': '480'}]
    env, state, client, preview = switch_preview(tmp_path, version=version, operation='setLayout',
        fields=('--new-layout-name', 'EditorWorkspace', '--blueprint', json.dumps(blueprint)))
    verified = confirm_execute_verify(env, state, client, preview)
    assert verified['verification']['business_state_verified'] is True
    panel, tabs = client.layouts['EditorWorkspace']['Layout']['StackPanel']['@Children']
    assert panel == {'@type': 'ObjectPanel', 'ID': panel['ID'], 'Name': 'Object editor',
        'EditorState': 'Maximized', 'BottomEditorState': 'Minimized', 'EditorPriority': [],
        'PreferredHeights': [], 'SideBar': {'@type': 'SideBar', 'Width': '210', 'CollapseState': ''}}
    assert tabs == {'@type': 'ObjectTabPanel', 'ID': tabs['ID'], 'Name': 'Object tabs', 'Height': '480'}


def test_editor_preferences_keep_order_repeats_and_optional_editor_tags(tmp_path):
    blueprint = _blueprint()
    blueprint['nodes'][2] = {'key': 'editors', 'kind': 'object_panel', 'label': 'Editors',
        'editor_priority': [
            {'view_identifier': 'PropertyEditor', 'plugin_identifier': '', 'effect_index': '0'},
            {'view_identifier': 'PropertyEditor', 'plugin_identifier': '', 'effect_index': '0', 'include_type': True}],
        'preferred_heights': [{'view_identifier': 'EffectEditor', 'plugin_identifier': '1058', 'effect_index': '2', 'height': '320'}]}
    env, state, client, preview = switch_preview(tmp_path, operation='setLayout',
        fields=('--new-layout-name', 'EditorPreferences', '--blueprint', json.dumps(blueprint)))
    verified = confirm_execute_verify(env, state, client, preview)
    assert verified['verification']['business_state_verified'] is True
    panel = client.layouts['EditorPreferences']['Layout']['StackPanel']['@Children'][1]
    assert panel['EditorPriority'] == [
        {'UniqueViewId': 'PropertyEditor', 'PluginId': '', 'EffectIndex': '0'},
        {'UniqueViewId': 'PropertyEditor', 'PluginId': '', 'EffectIndex': '0', '@type': 'EditorId'}]
    assert panel['PreferredHeights'] == [{'@type': 'PreferredHeight', 'UniqueViewId': 'EffectEditor',
        'PluginId': '1058', 'EffectIndex': '2', 'Height': '320'}]
    assert 'EditorState' not in panel and 'SideBar' not in panel


def _placement():
    return {'flags': '0', 'minimum_x': '-1', 'minimum_y': '-1', 'maximum_x': '0', 'maximum_y': '0',
        'left': '20', 'top': '30', 'right': '420', 'bottom': '530'}


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
def test_floating_only_workspace_and_position_histories_preserve_optional_forms(tmp_path, version):
    blueprint = {'contract': 'waapi-skill.layout-blueprint/v1', 'workspace_name': '', 'nodes': [
        {'key': 'floating', 'kind': 'stack', 'label': 'Floating', 'orientation': 'vertical', 'children': ['tools']},
        {'key': 'tools', 'kind': 'view', 'view_type': 'ProjectExplorer', 'selection_channel': ''}],
        'floating_windows': [{'root': 'floating', 'placement': {**_placement(), 'state': 'normal'}}, {'placement': _placement()}],
        'position_history': {'audio_devices': [], 'effects': [], 'fallback': [],
            'last_positions': [{'view_name': 'ProjectExplorer', 'placement': _placement()},
                               {'view_name': 'ProjectExplorer', 'placement': {**_placement(), 'state': 'minimized'}}],
            'metadata': [], 'object_types': [], 'plugin_inner_objects': [], 'source_plugins': []}}
    env, state, client, preview = switch_preview(tmp_path, version=version, operation='setLayout',
        fields=('--new-layout-name', 'FloatingWorkspace', '--blueprint', json.dumps(blueprint)))
    verified = confirm_execute_verify(env, state, client, preview)
    assert verified['verification']['business_state_verified'] is True
    layout = client.layouts['FloatingWorkspace']['Layout']
    assert layout['Name'] == '' and 'StackPanel' not in layout
    window, empty_window = layout['Undocked']
    assert window['@type'] == 'ViewHolder' and window['StackPanel']['Name'] == 'Floating'
    assert window['WindowPlacement_NormalPos_Left'] == '20' and window['WindowPlacement_ShowCmd'] == 'Normal'
    assert 'StackPanel' not in empty_window and 'WindowPlacement_ShowCmd' not in empty_window
    assert layout['AudioDeviceLastTabPositions'] == [] and layout['SourcePluginLastTabPositions'] == []
    assert layout['LastPositions'][0]['Name'] == 'ProjectExplorer'
    assert 'WindowPlacement_ShowCmd' not in layout['LastPositions'][0]
    assert layout['LastPositions'][1]['WindowPlacement_ShowCmd'] == 'Minimized'


@pytest.mark.parametrize('mechanism', ['floating', 'history', 'empty_floating', 'empty_history'])
@pytest.mark.parametrize('tamper', [False, True])
def test_rootless_layout_verification_checks_declared_windows_histories_and_explicit_empty_forms(tmp_path, mechanism, tamper):
    blueprint = {'contract': 'waapi-skill.layout-blueprint/v1', 'nodes': []}
    if mechanism in {'floating', 'empty_floating'}:
        blueprint['floating_windows'] = [{'placement': _placement()}] if mechanism == 'floating' else []
    else:
        blueprint['position_history'] = {'last_positions': [{'view_name': 'ProjectExplorer', 'placement': _placement()}]
            if mechanism == 'history' else []}
    env, state, client, preview = switch_preview(tmp_path, operation='setLayout',
        fields=('--new-layout-name', 'RootlessWorkspace', '--blueprint', json.dumps(blueprint)))
    original = client.call
    def changed_state(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri == URI + 'setLayout' and tamper:
            layout = client.layouts['RootlessWorkspace']['Layout']
            if mechanism == 'floating': layout['Undocked'][0]['WindowPlacement_NormalPos_Left'] = '21'
            elif mechanism == 'history': layout['LastPositions'][0]['Name'] = 'DifferentView'
            elif mechanism == 'empty_floating': del layout['Undocked']
            else: del layout['LastPositions']
        return result
    client.call = changed_state
    verified = confirm_execute_verify(env, state, client, preview, expect_verification_failure=tamper)
    assert verified['verification']['business_state_verified'] is not tamper
    if tamper:
        assertion = next(row for row in verified['verification']['assertions']
            if row['name'] == 'Registered layout retains every declared nested field and child order')
        assert assertion['evidence']['mismatches']


@pytest.mark.parametrize('variant', ['splitter', 'tab_children', 'sidebars'])
def test_retained_read_shapes_do_not_establish_unresolved_layout_input_legality(tmp_path, variant):
    blueprint = _blueprint()
    if variant == 'splitter': blueprint['nodes'][2] = {'key': 'editors', 'kind': 'splitter'}
    elif variant == 'tab_children': blueprint['nodes'][2] = {'key': 'editors', 'kind': 'object_tabs', 'label': 'Tabs', 'children': []}
    else: blueprint['nodes'][2] = {'key': 'editors', 'kind': 'object_panel', 'label': 'Editor',
        'sidebar_left': {'width': '400', 'collapse_state': '0', 'visible': False}}
    _, _, _, rejected = switch_preview(tmp_path, operation='setLayout',
        fields=('--new-layout-name', 'NeverWritten', '--blueprint', json.dumps(blueprint)), expect_declaration_error=True)
    assert 'input remains unresolved' in rejected['message']


@pytest.mark.parametrize('empty', [False, True])
def test_view_data_is_built_from_typed_entries_with_nested_values_and_no_raw_map(tmp_path, empty):
    blueprint = _blueprint()
    blueprint['nodes'][1]['data_entries'] = [] if empty else [
        {'name': 'selection', 'value': {'kind': 'object', 'entries': [
            {'name': 'enabled', 'value': {'kind': 'boolean', 'value': False}},
            {'name': 'positions', 'value': {'kind': 'array', 'items': [
                {'kind': 'integer', 'value': 0}, {'kind': 'number', 'value': 1.25},
                {'kind': 'string', 'value': ''}, {'kind': 'null'}]}}]}}]
    env, state, client, preview = switch_preview(tmp_path, operation='setLayout',
        fields=('--new-layout-name', 'ViewDataWorkspace', '--blueprint', json.dumps(blueprint)))
    verified = confirm_execute_verify(env, state, client, preview)
    assert verified['verification']['business_state_verified'] is True
    view = client.layouts['ViewDataWorkspace']['Layout']['StackPanel']['@Children'][0]
    assert view['ViewData'] == ({} if empty else {'selection': {'enabled': False, 'positions': [0, 1.25, '', None]}})


@pytest.mark.parametrize('tamper', [False, True])
def test_preferred_height_readback_understands_retained_editor_field_names_without_ignoring_values(tmp_path, tamper):
    blueprint = _blueprint()
    blueprint['nodes'][2] = {'key': 'editors', 'kind': 'object_panel', 'label': 'Editors',
        'preferred_heights': [{'view_identifier': 'AttenuationEditor', 'plugin_identifier': '4294967295',
            'effect_index': '0', 'height': '621.4757'}]}
    env, state, client, preview = switch_preview(tmp_path, operation='setLayout',
        fields=('--new-layout-name', 'EditorHeightWorkspace', '--blueprint', json.dumps(blueprint)))
    original = client.call
    def observed_names(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri == URI + 'setLayout':
            row = client.layouts['EditorHeightWorkspace']['Layout']['StackPanel']['@Children'][1]['PreferredHeights'][0]
            row['EditorUniqueViewId'] = row.pop('UniqueViewId')
            row['EditorPluginId'] = row.pop('PluginId')
            row['EditorEffectIndex'] = row.pop('EffectIndex')
            if tamper: row['EditorEffectIndex'] = '1'
        return result
    client.call = observed_names
    verified = confirm_execute_verify(env, state, client, preview, expect_verification_failure=tamper)
    assert verified['verification']['business_state_verified'] is not tamper


@pytest.mark.parametrize('tamper', ['binding_digest', 'declaration', 'non_layout_fields'])
def test_deep_constructor_settings_never_grant_capacity_to_forged_or_mismatched_facts(tmp_path, tamper):
    from copy import deepcopy
    from wwise_waapi.business_declaration_state import BusinessDeclarationSession
    from tests.unit.test_business_declaration_state import _context
    blueprint = _blueprint()
    env, state, client, preview = switch_preview(tmp_path, operation='setLayout',
        fields=('--new-layout-name', 'BoundWorkspace', '--blueprint', json.dumps(blueprint)))
    request = TransactionStore(Path(state[1])).load_preview(preview['transaction_id']).artifact['request']
    binding = deepcopy(request['arguments']['layout_binding'])
    settings = {'authoring_layout_plan': {'layout_handle': binding['handle'], 'new_layout_name': 'BoundWorkspace', 'blueprint': blueprint},
        'authoring_layout_binding': binding}
    if tamper == 'binding_digest': binding['binding_sha256'] = '0' * 64
    elif tamper == 'declaration': settings['authoring_layout_plan']['blueprint']['nodes'][0]['label'] = 'Different requested workspace'
    else:
        deep = 'leaf'
        for _ in range(13): deep = {'child': deep}
        settings['ordinary'] = deep
    with pytest.raises(ValueError):
        BusinessDeclarationSession.create(_context(version='2025.1')).with_settings(settings)


@pytest.mark.parametrize('node_kind', ['stack', 'view'])
def test_optional_element_type_omission_remains_distinct_from_explicit_type(tmp_path, node_kind):
    blueprint = _blueprint()
    blueprint['nodes'][0 if node_kind == 'stack' else 1]['include_type'] = False
    env, state, client, preview = switch_preview(tmp_path, operation='setLayout',
        fields=('--new-layout-name', 'OptionalTypeWorkspace', '--blueprint', json.dumps(blueprint)))
    verified = confirm_execute_verify(env, state, client, preview)
    assert verified['verification']['business_state_verified'] is True
    root = client.layouts['OptionalTypeWorkspace']['Layout']['StackPanel']
    selected = root if node_kind == 'stack' else root['@Children'][0]
    assert '@type' not in selected


def test_omitted_optional_type_does_not_verify_an_explicitly_different_element_kind(tmp_path):
    blueprint = _blueprint()
    blueprint['nodes'][1]['include_type'] = False
    env, state, client, preview = switch_preview(tmp_path, operation='setLayout',
        fields=('--new-layout-name', 'WrongElementKind', '--blueprint', json.dumps(blueprint)))
    original = client.call
    def wrong_kind(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri == URI + 'setLayout':
            client.layouts['WrongElementKind']['Layout']['StackPanel']['@Children'][0]['@type'] = 'ObjectPanel'
        return result
    client.call = wrong_kind
    verified = confirm_execute_verify(env, state, client, preview, expect_verification_failure=True)
    assert verified['verification']['business_state_verified'] is False


@pytest.mark.parametrize('risk', ['duplicate_data_key', 'wrong_scalar_type', 'shared_floating_root', 'unknown_placement_field', 'native_editor_field'])
def test_closed_nested_settings_reject_ambiguous_identity_data_and_native_fields(tmp_path, risk):
    blueprint = _blueprint()
    if risk in {'duplicate_data_key', 'wrong_scalar_type'}:
        entry = {'name': 'visible', 'value': {'kind': 'boolean', 'value': False}}
        blueprint['nodes'][1]['data_entries'] = [entry, entry] if risk == 'duplicate_data_key' else [
            {'name': 'visible', 'value': {'kind': 'boolean', 'value': 'false'}}]
    elif risk == 'shared_floating_root': blueprint['floating_windows'] = [{'root': 'main', 'placement': _placement()}]
    elif risk == 'unknown_placement_field': blueprint['floating_windows'] = [{'placement': {**_placement(), 'WindowPlacement_ShowCmd': 'Normal'}}]
    else: blueprint['nodes'][2] = {'key': 'editors', 'kind': 'object_panel', 'label': 'Editor',
        'editor_priority': [{'UniqueViewId': 'EffectEditor', 'plugin_identifier': '1058', 'effect_index': '0'}]}
    _, _, _, rejected = switch_preview(tmp_path, operation='setLayout',
        fields=('--new-layout-name', 'NeverWritten', '--blueprint', json.dumps(blueprint)), expect_declaration_error=True)
    assert 'blueprint' in rejected['message'].lower()


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
    nested = next(row for row in verified['verification']['assertions']
        if row['name'] == 'Registered layout retains every declared nested field and child order')
    assert nested['evidence']['mismatches']
    assert all(row['path'].startswith('/Layout') for row in nested['evidence']['mismatches'])
    assert len(nested['evidence']['mismatches']) <= 16
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
    code, inspected = gateway.execute_gateway([*state, 'layout-inspect', '--layout-name', 'TemporaryLookupName'],
        env=env, client_factory=lambda _: client)
    assert code == 0, inspected
    assert inspected['layout_name'] == 'TemporaryLookupName'
    assert inspected['workspace_name'] == 'SerializedLayout'
    assert inspected['agent_result']['workspace_name'] == 'SerializedLayout'
    code, schema = gateway.execute_gateway(['request-schema', URI + 'removeLayout'], env=env)
    assert code == 0, schema
    code, started = gateway.execute_gateway([*state, *schema['continuation']['gateway_argv']], env=env)
    assert code == 0, started
    draft, authority = started['draft'], started['task_authority']
    code, declared = gateway.execute_gateway([*state, 'draft-declare-layout-plan', draft['draft_id'],
        '--task-authority', authority, '--expected-revision', str(draft['revision']),
        '--layout-handle', inspected['layout_handle']], env=env, client_factory=lambda _: client)
    assert code == 0, declared
    code, checked = gateway.execute_gateway([*state, 'draft-check', draft['draft_id'], '--task-authority', authority,
        '--expected-revision', str(declared['draft']['revision'])], env=env, client_factory=lambda _: client)
    assert code == 0, checked
    code, removal = gateway.execute_gateway([*state, 'preview-from-draft', draft['draft_id'], '--task-authority', authority,
        '--expected-revision', str(checked['draft']['revision'])], env=env, client_factory=lambda _: client)
    assert code == 0, removal
    removed = confirm_execute_verify(env, state, client, removal)
    assert removed['verified'] is True
    assert 'TemporaryLookupName' not in client.layouts
    assert [row[1] for row in client.calls if row[0] == URI + 'removeLayout'] == [{'name': 'TemporaryLookupName'}]


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


def test_compiled_blueprint_must_fit_bounded_native_readback_before_any_write(tmp_path):
    # This 113926-byte business declaration fits the input ceiling; generated
    # native fields/GUIDs produce 114698 bytes, exceeding the 112 KiB compiled cap.
    blueprint = {'contract': 'waapi-skill.layout-blueprint/v1', 'root': 'main', 'nodes': [
        {'key': 'main', 'kind': 'stack', 'label': 'Main', 'orientation': 'horizontal',
            'children': ['v' + str(index) for index in range(63)]},
        *[{'key': 'v' + str(index), 'kind': 'view', 'view_type': 'ProjectExplorer',
            'selection_channel': '1', 'width': '1' * 1696} for index in range(63)]]}
    assert len(json.dumps(blueprint).encode()) == 113926
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version='2025.1')
    state = ['--state-dir', str(tmp_path / 'state')]
    client = LayoutClient(tmp_path)
    _, inspected = gateway.execute_gateway([*state, 'layout-inspect', '--layout-name', 'Designer'], env=env, client_factory=lambda _: client)
    _, schema = gateway.execute_gateway(['--version', '2025.1', 'request-schema', URI + 'setLayout'], env=env)
    _, started = gateway.execute_gateway([*state, *schema['continuation']['gateway_argv']], env=env)
    code, result = gateway.execute_gateway([*state, 'draft-declare-layout-plan', started['draft']['draft_id'],
        '--task-authority', started['task_authority'], '--expected-revision', str(started['draft']['revision']),
        '--layout-handle', inspected['layout_handle'], '--new-layout-name', 'Owned', '--blueprint', json.dumps(blueprint)],
        env=env, client_factory=lambda _: client)
    assert code != 0
    assert 'byte' in result['message'].lower() or 'readback' in result['message'].lower()
    assert URI + 'setLayout' not in [row[0] for row in client.calls]


@pytest.mark.parametrize('text', ['1' * 1695, '界' * 565, '"\\' * 423 + 'abc'],
    ids=['ascii', 'multibyte', 'quoted-backslash'])
def test_near_compiled_byte_ceiling_layout_completes_public_roundtrip(tmp_path, text, monkeypatch, capsys):
    blueprint = {'contract': 'waapi-skill.layout-blueprint/v1', 'root': 'main', 'nodes': [
        {'key': 'main', 'kind': 'stack', 'label': 'Main', 'orientation': 'horizontal',
            'children': ['v' + str(index) for index in range(63)]},
        *[{'key': 'v' + str(index), 'kind': 'view', 'view_type': 'ProjectExplorer',
            'selection_channel': '1', 'width': text} for index in range(63)]]}
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version='2025.1')
    _, schema = gateway.execute_gateway(['--version', '2025.1', 'request-schema', URI + 'setLayout'], env=env)
    limits = schema['business_adapter']['blueprint_schema']['gateway_bounds']
    assert limits['maximum_serialized_layout_utf8_bytes'] == 114688
    assert limits['maximum_readback_utf8_bytes'] == 262144
    assert limits['maximum_rendered_terminal_request_utf8_bytes'] == 262144
    assert limits['maximum_terminal_stdout_utf8_bytes'] == 286720
    def enrich(client):
        client.responses['ak.wwise.core.getInfo']['sessionId'] = '界\"\\' * 500
    env, state, client, preview = switch_preview(tmp_path, operation='setLayout',
        fields=('--new-layout-name', 'Owned', '--blueprint', json.dumps(blueprint, ensure_ascii=False)), client_setup=enrich)
    artifact = TransactionStore(Path(state[1])).load_preview(preview['transaction_id']).artifact
    native = artifact['prepared_operation']['dispatch']['args']['layout']
    compiled_bytes = len(json.dumps(native, ensure_ascii=False, separators=(',', ':')).encode())
    assert 114000 < compiled_bytes <= 114688
    verified = confirm_execute_verify(env, state, client, preview)
    assert verified['verified'] is True
    assert verified['stdout_projection']['stdout_budget_bytes'] == 286720
    rendered = gateway.gateway_stdout_json_encoder(verified).encode(gateway.gateway_stdout_payload(verified)) + '\n'
    # Exercise the actual final CLI emitter with the already-observed public
    # result; this does not repeat verify or open another fake/live connection.
    with monkeypatch.context() as emitting:
        emitting.setattr(gateway, 'execute_gateway', lambda argv: (0, verified))
        assert gateway.main(['verify', preview['transaction_id']]) == 0
    assert capsys.readouterr().out == rendered
    assert len(rendered.encode('utf-8')) <= 286720
    (tmp_path / 'terminal.stdout.json').write_text(rendered, encoding='utf-8')
    decoded = json.loads(rendered)
    assert decoded['agent_result']['request'] == artifact['request']
    assert decoded['agent_result'] == verified['agent_result']
    assert list(decoded)[-1] == 'agent_result'
    events = TransactionStore(Path(state[1])).read_events(preview['transaction_id'])
    evidence = next(row['details']['verification'] for row in events if row['event_type'] == 'verification_recorded')
    assert evidence['business_state_verified'] is True
    assert artifact['prepared_operation']['verification_plan']['expected_layout'] == native
    assert verified['stdout_projection']['verification_canonical_sha256'] == gateway.canonical_sha256(evidence)
    assert evidence['readbacks'][-1]['result'] == native
    assert [row[0] for row in client.calls].count(URI + 'setLayout') == 1


@pytest.mark.parametrize('operation,fields', [('switchLayout', ()), ('setLayout', ('--new-layout-name', 'SmallOwned')),
    ('setLayout', ('--new-layout-name', 'SmallNested', '--blueprint', json.dumps(_blueprint())))])
def test_small_constructor_and_other_operations_keep_ordinary_terminal_budget(tmp_path, operation, fields):
    env, state, client, preview = switch_preview(tmp_path, operation=operation, fields=fields)
    verified = confirm_execute_verify(env, state, client, preview)
    assert verified['stdout_projection']['stdout_budget_bytes'] == 24576
    rendered = gateway.gateway_stdout_json_encoder(verified).encode(gateway.gateway_stdout_payload(verified)) + '\n'
    assert len(rendered.encode('utf-8')) <= 24576
    assert list(json.loads(rendered))[-1] == 'agent_result'


def _deep_wide_blueprint(width):
    return {'contract': 'waapi-skill.layout-blueprint/v1', 'root': 's0', 'nodes': [
        *[{'key': 's' + str(index), 'kind': 'stack', 'label': 'Nested', 'orientation': 'horizontal',
            'children': ['s' + str(index + 1)] if index < 12 else ['v' + str(child) for child in range(115)]}
            for index in range(13)],
        *[{'key': 'v' + str(index), 'kind': 'view', 'view_type': 'ProjectExplorer',
            'selection_channel': '1', 'width': '1' * width} for index in range(115)]]}


def test_constructor_terminal_fit_rejects_deep_rendering_before_write(tmp_path):
    # Both input (94,532 bytes) and compiled document (96,208 bytes) fit their
    # budgets, but the exact deeply indented terminal request exceeds 256 KiB.
    _, _, client, result = switch_preview(tmp_path, operation='setLayout',
        fields=('--new-layout-name', 'NeverWritten', '--blueprint', json.dumps(_deep_wide_blueprint(700))),
        expect_declaration_error=True)
    assert 'terminal' in result['message'].lower(), result
    assert URI + 'setLayout' not in [row[0] for row in client.calls]


def test_oversized_business_blueprint_stops_before_any_client(tmp_path):
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version='2025.1')
    state = ['--state-dir', str(tmp_path / 'state')]
    client = LayoutClient(tmp_path)
    _, inspected = gateway.execute_gateway([*state, 'layout-inspect', '--layout-name', 'Designer'], env=env, client_factory=lambda _: client)
    _, schema = gateway.execute_gateway(['--version', '2025.1', 'request-schema', URI + 'setLayout'], env=env)
    _, started = gateway.execute_gateway([*state, *schema['continuation']['gateway_argv']], env=env)
    code, result = gateway.execute_gateway([*state, 'draft-declare-layout-plan', started['draft']['draft_id'],
        '--task-authority', started['task_authority'], '--expected-revision', str(started['draft']['revision']),
        '--layout-handle', inspected['layout_handle'], '--new-layout-name', 'NeverWritten',
        '--blueprint', json.dumps(_deep_wide_blueprint(900))], env=env,
        client_factory=lambda _: pytest.fail('business resource bound must reject before client'))
    assert code != 0 and 'byte' in result['message'].lower()
    assert URI + 'setLayout' not in [row[0] for row in client.calls]


@pytest.mark.parametrize('unowned_shape', ['other-operation', 'other-api', 'invalid-binding'])
def test_other_or_unbound_requests_cannot_claim_constructor_terminal_capacity(tmp_path, unowned_shape):
    from copy import deepcopy
    env, state, client, preview = switch_preview(tmp_path, operation='setLayout',
        fields=('--new-layout-name', 'SmallNested', '--blueprint', json.dumps(_blueprint())))
    verified = confirm_execute_verify(env, state, client, preview)
    payload = deepcopy(verified)
    events = TransactionStore(Path(state[1])).read_events(preview['transaction_id'])
    payload['verification'] = deepcopy(next(row['details']['verification'] for row in events
        if row['event_type'] == 'verification_recorded'))
    payload['agent_result']['request']['arguments']['extra_padding'] = 'x' * 30000
    if unowned_shape == 'other-operation':
        payload['agent_result']['operation'] = 'object.setNotes'
        payload['agent_result']['request']['operation'] = 'object.setNotes'
        payload['verification']['operation'] = 'object.setNotes'
    elif unowned_shape == 'other-api':
        payload['agent_result']['request']['arguments'].pop('extra_padding')
        payload['agent_result']['request']['arguments']['api'] = URI + 'switchLayout'
        payload['agent_result']['request']['arguments']['args']['padding'] = 'x' * 30000
    else:
        payload['agent_result']['request']['arguments'].pop('extra_padding')
        payload['agent_result']['request']['arguments']['layout_binding']['layout_blueprint']['nodes'][0]['label'] = 'x' * 30000
    with pytest.raises(gateway.GatewayResultShapeError) as caught:
        gateway.project_successful_transaction_verify_payload(payload)
    assert caught.value.error_code == 'VERIFY_SUCCESS_SUMMARY_BUDGET_EXCEEDED'
    assert caught.value.details['limit_bytes'] == 22528


@pytest.mark.parametrize('drift', ['workspace', 'nested-state', 'lookup'])
def test_divergent_workspace_identity_still_rechecks_exact_lookup_and_document_before_write(tmp_path, drift):
    def setup(client):
        client.layouts['Profiler']['Layout']['Name'] = 'SerializedWorkspace'
    env, state, client, preview = switch_preview(tmp_path, client_setup=setup)
    tx = preview['transaction_id']
    _, shown = gateway.execute_gateway([*state, 'transaction-show', tx], env=env)
    code, _ = gateway.execute_gateway([*state, 'confirm', tx, '--confirmation-token', shown['confirmation']['token']], env=env)
    assert code == 0
    if drift == 'workspace':
        client.layouts['Profiler']['Layout']['Name'] = 'DifferentWorkspace'
    elif drift == 'nested-state':
        client.layouts['Profiler']['Layout']['StackPanel']['Name'] = 'ChangedPanel'
    else:
        client.layouts['OtherLookup'] = client.layouts.pop('Profiler')
    code, rejected = gateway.execute_gateway([*state, 'execute', tx], env=env, client_factory=lambda _: client)
    assert code != 0, rejected
    assert URI + 'switchLayout' not in [row[0] for row in client.calls]


def test_equal_workspace_names_never_merge_different_lookup_authorities(tmp_path):
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version='2025.1')
    state = ['--state-dir', str(tmp_path / 'state')]
    client = LayoutClient(tmp_path)
    for name in ('Designer', 'Profiler'):
        client.layouts[name]['Layout']['Name'] = 'SharedWorkspace'
    client.views['Profiler'] = [{'viewID': '{33333333-3333-3333-3333-333333333333}',
        'viewName': 'ProjectExplorer', 'viewDisplayName': 'Project Explorer', 'viewIsDocked': True}]
    code, selected = gateway.execute_gateway([*state, 'layout-inspect', '--layout-name', 'Designer'],
        env=env, client_factory=lambda _: client)
    assert code == 0, selected
    code, foreign = gateway.execute_gateway([*state, 'layout-inspect', '--layout-name', 'Profiler'],
        env=env, client_factory=lambda _: client)
    assert code == 0, foreign
    assert selected['workspace_name'] == foreign['workspace_name'] == 'SharedWorkspace'
    _, schema = gateway.execute_gateway(['request-schema', URI + 'undockView'], env=env)
    _, started = gateway.execute_gateway([*state, *schema['continuation']['gateway_argv']], env=env)
    code, rejected = gateway.execute_gateway([*state, 'draft-declare-layout-plan', started['draft']['draft_id'],
        '--task-authority', started['task_authority'], '--expected-revision', str(started['draft']['revision']),
        '--layout-handle', selected['layout_handle'], '--view-handle', foreign['views'][0]['handle']],
        env=env, client_factory=lambda _: client)
    assert code != 0 and 'same layout' in rejected['message'].lower(), rejected
    assert URI + 'undockView' not in [row[0] for row in client.calls]
