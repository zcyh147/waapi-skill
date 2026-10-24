"""Owned ordinary Authoring resources through the public Gateway."""
from __future__ import annotations

import pytest
from tests.unit.test_waapi_gateway import gateway_env, waapi_gateway as gateway

PREFIX = 'ak.wwise.ui.'

@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
def test_window_creation_discloses_closed_owned_transaction(tmp_path, version):
    code, schema = gateway.execute_gateway(['--version', version, 'request-schema', PREFIX + 'window.create'],
        env=gateway_env(tmp_path), client_factory=lambda _: pytest.fail('offline schema opened a client'))
    assert code == 0, (schema.get("message"), schema.get("details"))
    adapter = schema['business_adapter']
    assert adapter['execution_shape'] == 'transaction'
    assert adapter['declaration']['schema']['additionalProperties'] is False
    assert adapter['resource_lifetime']['ownership'] == 'gateway_created_only'
    assert adapter['effect_verification']['native_effect_evidence'] == 'required_unfinished'

from tests.unit.test_authoring_layout_mutation_gateway import LayoutClient
from tests.support.gateway_config import set_gateway_config
import json


def model_preview(tmp_path, operation, plan, *, version='2025.1', policy='ask_before_changes', client=None):
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version=version, project_modification_policy=policy)
    state = ['--state-dir', str(tmp_path / 'state')]
    client = client or LayoutClient(tmp_path, version=version)
    code, schema = gateway.execute_gateway(['--version', version, 'request-schema', PREFIX + operation], env=env)
    assert code == 0, (schema.get("message"), schema.get("details"))
    code, start = gateway.execute_gateway([*state, *schema['continuation']['gateway_argv']], env=env)
    assert code == 0, (start.get("error_code"), start.get("message"), start.get("details"))
    draft = start['draft']
    code, declared = gateway.execute_gateway([*state, 'draft-declare-model-plan', draft['draft_id'],
        '--task-authority', start['task_authority'], '--expected-revision', str(draft['revision']),
        '--plan', json.dumps(plan)], env=env, client_factory=lambda _: client)
    assert code == 0, (declared.get("error_code"), declared.get("message"), declared.get("details"))
    code, checked = gateway.execute_gateway([*state, 'draft-check', draft['draft_id'],
        '--task-authority', start['task_authority'], '--expected-revision', str(declared['draft']['revision'])],
        env=env, client_factory=lambda _: client)
    assert code == 0, json.dumps(checked, ensure_ascii=False)
    code, preview = gateway.execute_gateway([*state, 'preview-from-draft', draft['draft_id'],
        '--task-authority', start['task_authority'], '--expected-revision', str(checked['draft']['revision'])],
        env=env, client_factory=lambda _: client)
    assert code == 0, (preview.get("error_code"), preview.get("message"), preview.get("details"))
    return env, state, client, preview


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
def test_window_creation_is_previewed_once_and_returns_owned_resource(tmp_path, version):
    client = LayoutClient(tmp_path, version=version)
    client.responses[PREFIX + 'window.create'] = {'windowID': '{33333333-3333-3333-3333-333333333333}'}
    env, state, client, preview = model_preview(tmp_path, 'window.create', {'title': 'Weather', 'width': 400, 'height': 300}, version=version, client=client)
    assert PREFIX + 'window.create' not in [row[0] for row in client.calls]
    verified = confirm_execute_verify(env, state, client, preview)
    assert verified['verified'] is False
    assert verified['agent_result']['business_result']['resource_handle'].startswith('ar1-')
    assert verified['agent_result']['business_result']['observable_effect_verified'] is False
    assert [row for row in client.calls if row[0] == PREFIX + 'window.create'] == [(PREFIX + 'window.create', {'title': 'Weather', 'size': {'width': 400, 'height': 300}}, {})]


def confirm_execute_verify(env, state, client, preview):
    tx = preview['transaction_id']
    code, shown = gateway.execute_gateway([*state, 'transaction-show', tx], env=env)
    assert code == 0, shown
    code, confirmed = gateway.execute_gateway([*state, 'confirm', tx, '--confirmation-token', shown['confirmation']['token']], env=env)
    assert code == 0, confirmed
    code, executed = gateway.execute_gateway([*state, 'execute', tx], env=env, client_factory=lambda _: client)
    assert code == 0, (executed.get('error_code'), executed.get('message'), executed.get('details'))
    code, verified = gateway.execute_gateway([*state, 'verify', tx], env=env, client_factory=lambda _: client)
    assert code == 0, (verified.get('error_code'), verified.get('message'), verified.get('details'))
    return verified

@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
def test_owned_window_can_be_presented_then_closed_and_cannot_be_reused(tmp_path, version):
    client = LayoutClient(tmp_path, version=version)
    client.responses.update({PREFIX + 'window.create': {'windowID': '{33333333-3333-3333-3333-333333333333}'},
        PREFIX + 'window.present': {}, PREFIX + 'window.close': {}})
    env, state, client, create = model_preview(tmp_path, 'window.create', {'title': '', 'width': 1, 'height': 1}, version=version, client=client)
    handle = confirm_execute_verify(env, state, client, create)['agent_result']['business_result']['resource_handle']
    env, state, client, present = model_preview(tmp_path, 'window.present', {'window': handle}, version=version, client=client)
    result = confirm_execute_verify(env, state, client, present)
    assert result['verified'] is False
    env, state, client, close = model_preview(tmp_path, 'window.close', {'window': handle}, version=version, client=client)
    confirm_execute_verify(env, state, client, close)
    # A different transaction cannot revive or close a consumed resource.
    code, start = gateway.execute_gateway([*state, 'draft-start', PREFIX + 'window.present'], env=env)
    assert code == 0, start
    code, result = gateway.execute_gateway([*state, 'draft-declare-model-plan', start['draft']['draft_id'],
        '--task-authority', start['task_authority'], '--expected-revision', str(start['draft']['revision']), '--plan', json.dumps({'window': handle})],
        env=env, client_factory=lambda _: client)
    assert code != 0, result
    assert len([row for row in client.calls if row[0] == PREFIX + 'window.close']) == 1


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
def test_closed_template_registration_owns_names_and_constructs_nested_widgets(tmp_path, version):
    client = LayoutClient(tmp_path, version=version)
    client.responses[PREFIX + 'model.registerWafm'] = {'success': True}
    plan = {'template_key': 'Weather', 'root_widget': 'Root',
        'widgets': [{'key': 'Rain', 'kind': 'Checkbox', 'attributes': [{'attribute': 'Text', 'value': {'kind': 'text', 'text': 'Rain'}}]}],
        'layouts': [{'key': 'Root', 'kind': 'AnchorLayout', 'attributes': [
            {'attribute': 'Width', 'value': {'kind': 'integer', 'integer': 400}},
            {'attribute': 'Height', 'value': {'kind': 'integer', 'integer': 300}}],
            'children': [{'widget': 'Rain', 'positions': [0, 0, 100, 30], 'anchors': ['side-left', 'side-top']}]}]}
    env, state, client, preview = model_preview(tmp_path, 'model.registerWafm', plan, version=version, client=client)
    result = confirm_execute_verify(env, state, client, preview)
    resource = result['agent_result']['business_result']
    assert resource['resource_kind'] == 'template'
    call = next(row for row in client.calls if row[0] == PREFIX + 'model.registerWafm')
    native = call[1]['wafm']
    assert native['template'].startswith('Gateway_')
    assert native['definition']['Widgets'] == [{'Name': 'Rain', 'Type': 'Checkbox', 'Text': 'Rain'}]
    assert native['definition']['Layouts']['Settings'][0]['Children'] == [{'Name': 'Rain', 'Positions': [0, 0, 100, 30], 'AnchorSets': ['side-left', 'side-top']}]


class ModelClient(LayoutClient):
    def __init__(self, tmp_path, *, version='2025.1'):
        super().__init__(tmp_path, version=version)
        self.responses.update({PREFIX + 'window.create': {'windowID': '{33333333-3333-3333-3333-333333333333}'},
            PREFIX + 'model.registerWafm': {'success': True}})
        self.widget_values = {'Rain': {'Checked': False, 'Enabled': True, 'Text': 'Rain'}}
        self.created_model = False

    def call(self, uri, args=None, options=None):
        if uri == PREFIX + 'model.createHandle':
            self.calls.append((uri, args, options))
            self.created_model = True
            return {'handleID': '{44444444-4444-4444-4444-444444444444}'}
        if uri == PREFIX + 'model.setState':
            self.calls.append((uri, args, options))
            for widget in args['state']:
                for state in widget['state']:
                    self.widget_values[widget['widgetID']][state['attribute']] = state['value']
            return {}
        if uri == PREFIX + 'model.getState':
            self.calls.append((uri, args, options))
            if not self.created_model:
                raise RuntimeError('frontend handle is absent')
            return [{'widgetID': row['widgetID'], 'state': [
                {'attribute': name, 'value': self.widget_values[row['widgetID']][name]} for name in row['state']]} for row in args['state']]
        if uri == PREFIX + 'model.destroyHandle':
            self.calls.append((uri, args, options))
            self.created_model = False
            return {}
        return super().call(uri, args, options)


def rain_template():
    return {'template_key': 'Weather', 'root_widget': 'Root', 'widgets': [{'key': 'Rain', 'kind': 'Checkbox'}],
        'layouts': [{'key': 'Root', 'kind': 'AnchorLayout', 'attributes': [
            {'attribute': 'Width', 'value': {'kind': 'integer', 'integer': 400}},
            {'attribute': 'Height', 'value': {'kind': 'integer', 'integer': 300}}], 'children': [{'widget': 'Rain', 'positions': [0, 0, 100, 30], 'anchors': ['side-left', 'side-top']}]}]}


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
def test_owned_model_state_roundtrip_uses_registered_widget_and_independent_readback(tmp_path, version):
    client = ModelClient(tmp_path, version=version)
    env, state, client, preview = model_preview(tmp_path, 'window.create', {'title': 'Weather', 'width': 400, 'height': 300}, version=version, client=client)
    window = confirm_execute_verify(env, state, client, preview)['agent_result']['business_result']['resource_handle']
    env, state, client, preview = model_preview(tmp_path, 'model.registerWafm', rain_template(), version=version, client=client)
    template = confirm_execute_verify(env, state, client, preview)['agent_result']['business_result']['resource_handle']
    env, state, client, preview = model_preview(tmp_path, 'model.createHandle', {'window': window, 'template': template}, version=version, client=client)
    model = confirm_execute_verify(env, state, client, preview)['agent_result']['business_result']['resource_handle']
    env, state, client, preview = model_preview(tmp_path, 'model.setState', {'model': model, 'widgets': [
        {'widget': 'Rain', 'attributes': [{'attribute': 'Checked', 'value': {'kind': 'boolean', 'boolean': True}}]}]}, version=version, client=client)
    assert client.widget_values['Rain']['Checked'] is False
    result = confirm_execute_verify(env, state, client, preview)
    assert result['verified'] is True
    assert client.widget_values['Rain']['Checked'] is True
    assert next(row for row in reversed(client.calls) if row[0] == PREFIX + 'model.getState')[1] == {
        'handleID': '{44444444-4444-4444-4444-444444444444}', 'state': [{'widgetID': 'Rain', 'state': ['Checked']}]}
    env, state, client, preview = model_preview(tmp_path, 'model.getState', {'model': model, 'widgets': [
        {'widget': 'Rain', 'attributes': ['Checked']}]}, version=version, client=client)
    confirm_execute_verify(env, state, client, preview)
    # Emission is fixed to an owned widget but the native schema permits an
    # exact Topic URI; producer descriptions are not receiver allowlists.
    client.responses[PREFIX + 'signal.emit'] = {}
    for signal in ['click', {'topic_uri': 'example.custom.signal'}]:
        env, state, client, emitted = model_preview(tmp_path, 'signal.emit', {'model': model, 'widget': 'Rain', 'signal': signal}, version=version, client=client)
        emission = confirm_execute_verify(env, state, client, emitted)
        assert emission['verified'] is False
    assert [row[1]['signal'] for row in client.calls if row[0] == PREFIX + 'signal.emit'] == [PREFIX + 'signal.click', 'example.custom.signal']
    # Close cannot discard the owning window while its frontend is still active.
    code, start = gateway.execute_gateway([*state, 'draft-start', PREFIX + 'window.close'], env=env)
    code, rejected = gateway.execute_gateway([*state, 'draft-declare-model-plan', start['draft']['draft_id'],
        '--task-authority', start['task_authority'], '--expected-revision', str(start['draft']['revision']), '--plan', json.dumps({'window': window})], env=env, client_factory=lambda _: client)
    assert code != 0, rejected
    assert PREFIX + 'window.close' not in [row[0] for row in client.calls]
    env, state, client, preview = model_preview(tmp_path, 'model.destroyHandle', {'model': model}, version=version, client=client)
    confirm_execute_verify(env, state, client, preview)
    assert client.created_model is False
    client.responses[PREFIX + 'window.close'] = {}
    env, state, client, preview = model_preview(tmp_path, 'window.close', {'window': window}, version=version, client=client)
    confirm_execute_verify(env, state, client, preview)


def test_creation_identity_can_be_recovered_for_cleanup_when_effect_verification_fails(tmp_path):
    client = LayoutClient(tmp_path)
    client.responses[PREFIX + 'window.create'] = {'windowID': '{33333333-3333-3333-3333-333333333333}', 'unexpected': True}
    env, state, client, preview = model_preview(tmp_path, 'window.create', {'title': 'Owned', 'width': 10, 'height': 10}, client=client)
    tx = preview['transaction_id']
    _, shown = gateway.execute_gateway([*state, 'transaction-show', tx], env=env)
    code, _ = gateway.execute_gateway([*state, 'confirm', tx, '--confirmation-token', shown['confirmation']['token']], env=env)
    assert code == 0
    code, execution = gateway.execute_gateway([*state, 'execute', tx], env=env, client_factory=lambda _: client)
    assert code == 0, execution
    code, failed = gateway.execute_gateway([*state, 'verify', tx], env=env, client_factory=lambda _: client)
    assert code != 0 and failed['status'] == 'verification_failed', failed
    code, recovered = gateway.execute_gateway([*state, 'authoring-resource', tx], env=env, client_factory=lambda _: client)
    assert code == 0, recovered
    assert recovered['agent_result']['resource_handle'].startswith('ar1-')
    assert recovered['agent_result']['observable_effect_verified'] is False
    client.responses[PREFIX + 'window.close'] = {}
    env, state, client, cleanup = model_preview(tmp_path, 'window.close', {'window': recovered['agent_result']['resource_handle']}, client=client)
    confirm_execute_verify(env, state, client, cleanup)
    assert len([row for row in client.calls if row[0] == PREFIX + 'window.create']) == 1


@pytest.mark.parametrize('failure_stage', ['journal', 'atomic-retirement'])
def test_failed_execution_journal_does_not_consume_an_undispatched_window(tmp_path, monkeypatch, failure_stage):
    from wwise_waapi.transactions import TransactionStore
    client = LayoutClient(tmp_path)
    client.responses.update({PREFIX + 'window.create': {'windowID': '{33333333-3333-3333-3333-333333333333}'}, PREFIX + 'window.close': {}})
    env, state, client, create = model_preview(tmp_path, 'window.create', {'title': 'Owned', 'width': 10, 'height': 10}, client=client)
    handle = confirm_execute_verify(env, state, client, create)['agent_result']['business_result']['resource_handle']
    env, state, client, close = model_preview(tmp_path, 'window.close', {'window': handle}, client=client)
    tx = close['transaction_id']
    _, shown = gateway.execute_gateway([*state, 'transaction-show', tx], env=env)
    gateway.execute_gateway([*state, 'confirm', tx, '--confirmation-token', shown['confirmation']['token']], env=env)
    import wwise_waapi.transactions as transactions
    original, original_writer = TransactionStore.begin_execution, transactions._atomic_write_json
    def fail_begin(self, transaction_id, **kwargs):
        raise OSError('injected durable execution journal failure')
    def fail_retirement(path, payload):
        if str(path).endswith('.consumed.json'):
            raise OSError('injected atomic retirement failure')
        return original_writer(path, payload)
    if failure_stage == 'journal':
        monkeypatch.setattr(TransactionStore, 'begin_execution', fail_begin)
    else:
        monkeypatch.setattr(transactions, '_atomic_write_json', fail_retirement)
    code, failed = gateway.execute_gateway([*state, 'execute', tx], env=env, client_factory=lambda _: client)
    assert code != 0 and 'failure' in failed['message'], failed
    if failure_stage == 'atomic-retirement':
        assert failed['native_dispatch_attempted'] is False and failed['automatic_retry'] is False
    assert PREFIX + 'window.close' not in [row[0] for row in client.calls]
    monkeypatch.setattr(TransactionStore, 'begin_execution', original)
    monkeypatch.setattr(transactions, '_atomic_write_json', original_writer)
    # A public declaration still resolves the live resource; the failed journal
    # did not turn the unattempted close into a consumed handle.
    model_preview(tmp_path, 'window.present', {'window': handle}, client=client)
    if failure_stage == 'journal':
        code, executed = gateway.execute_gateway([*state, 'execute', tx], env=env, client_factory=lambda _: client)
        assert code == 0, executed
    else:
        # The exact original execution has a durable terminal no-dispatch failure;
        # use a distinct authorized Preview rather than replaying that transaction.
        env, state, client, replacement = model_preview(tmp_path, 'window.close', {'window': handle}, client=client)
        confirm_execute_verify(env, state, client, replacement)
    assert len([row for row in client.calls if row[0] == PREFIX + 'window.close']) == 1


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1'])
@pytest.mark.parametrize('operation', ['window.create', 'model.registerWafm', 'model.getState', 'signal.emit'])
def test_older_captured_lanes_do_not_advertise_unlisted_native_routes(tmp_path, version, operation):
    code, result = gateway.execute_gateway(['--version', version, 'request-schema', PREFIX + operation], env=gateway_env(tmp_path),
        client_factory=lambda _: pytest.fail('offline route boundary opened a client'))
    assert code != 0, result


@pytest.mark.parametrize('mutation', ['unknown-field', 'invalid-enum', 'raw-value', 'unknown-widget', 'old-version-kind'])
def test_malformed_template_constructors_fail_before_registration(tmp_path, mutation):
    plan = rain_template()
    if mutation == 'unknown-field': plan['widgets'][0]['native_json'] = {}
    elif mutation == 'invalid-enum': plan['widgets'][0]['attributes'] = [{'attribute': 'PropertyType', 'value': {'kind': 'text', 'text': 'not-a-native-choice'}}]
    elif mutation == 'raw-value': plan['widgets'][0]['attributes'] = [{'attribute': 'Text', 'value': {'Text': 'native dump'}}]
    elif mutation == 'unknown-widget': plan['layouts'][0]['children'][0]['widget'] = 'Absent'
    else: plan['widgets'][0]['kind'] = 'Image'
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version='2024.1')
    client = LayoutClient(tmp_path, version='2024.1')
    state = ['--state-dir', str(tmp_path / 'state')]
    _, started = gateway.execute_gateway([*state, 'draft-start', PREFIX + 'model.registerWafm'], env=env)
    code, rejected = gateway.execute_gateway([*state, 'draft-declare-model-plan', started['draft']['draft_id'],
        '--task-authority', started['task_authority'], '--expected-revision', str(started['draft']['revision']), '--plan', json.dumps(plan)], env=env, client_factory=lambda _: client)
    assert code != 0, rejected
    assert PREFIX + 'model.registerWafm' not in [row[0] for row in client.calls]


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
def test_owned_wafm_file_alternative_seals_and_dispatches_a_generated_data_file(tmp_path, version):
    from pathlib import Path
    from wwise_waapi.transactions import TransactionStore
    client = ModelClient(tmp_path, version=version)
    client.responses['ak.wwise.core.getInfo']['processPath'] = str(tmp_path / 'Wwise')
    plan = {**rain_template(), 'registration_medium': 'file'}
    env, state, client, preview = model_preview(tmp_path, 'model.registerWafm', plan, version=version, client=client)
    prepared = TransactionStore(Path(state[1])).load_preview(preview['transaction_id']).artifact['prepared_operation']
    artifact = Path(prepared['dispatch']['args']['wafm'])
    assert artifact.is_file() and artifact.suffix == '.wafm'
    content = json.loads(artifact.read_text(encoding='utf-8'))
    assert content['definition']['Widgets'] == [{'Name': 'Rain', 'Type': 'Checkbox'}]
    verified = confirm_execute_verify(env, state, client, preview)
    assert verified['agent_result']['business_result']['resource_kind'] == 'template'
    assert verified['agent_result']['business_result']['cleanup_route'] is None
    native = next(row for row in client.calls if row[0] == PREFIX + 'model.registerWafm')
    assert native[1] == {'wafm': str(artifact)}


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
def test_contract_discloses_owned_constructor_fields_and_exact_version_choices(tmp_path, version):
    _, result = gateway.execute_gateway(['--version', version, 'request-schema', PREFIX + 'model.registerWafm'], env=gateway_env(tmp_path))
    contract = result['business_adapter']
    schema = contract['declaration']['schema']
    assert schema['properties']['widgets']['items']['additionalProperties'] is False
    assert schema['properties']['registration_medium']['enum'] == ['inline', 'file']
    assert ('Image' in schema['properties']['widgets']['items']['properties']['kind']['enum']) == (version == '2025.1')
    assert ('BinLayout' in schema['properties']['layouts']['items']['properties']['kind']['enum']) == (version == '2025.1')


def test_owned_wafm_file_drift_is_rejected_before_registration(tmp_path):
    from pathlib import Path
    from wwise_waapi.transactions import TransactionStore
    client = ModelClient(tmp_path)
    client.responses['ak.wwise.core.getInfo']['processPath'] = str(tmp_path / 'Wwise')
    env, state, client, preview = model_preview(tmp_path, 'model.registerWafm', {**rain_template(), 'registration_medium': 'file'}, client=client)
    tx = preview['transaction_id']
    artifact = TransactionStore(Path(state[1])).load_preview(tx).artifact['prepared_operation']['dispatch']['args']['wafm']
    Path(artifact).write_text('{}', encoding='utf-8')
    _, shown = gateway.execute_gateway([*state, 'transaction-show', tx], env=env)
    gateway.execute_gateway([*state, 'confirm', tx, '--confirmation-token', shown['confirmation']['token']], env=env)
    code, rejected = gateway.execute_gateway([*state, 'execute', tx], env=env, client_factory=lambda _: client)
    assert code != 0, rejected
    assert PREFIX + 'model.registerWafm' not in [row[0] for row in client.calls]


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
def test_named_template_collection_is_owned_and_frontend_selects_one_exact_template(tmp_path, version):
    client = ModelClient(tmp_path, version=version)
    first, second = rain_template(), {**rain_template(), 'template_key': 'Second'}
    env, state, client, preview = model_preview(tmp_path, 'model.registerWafm', {'templates': [first, second]}, version=version, client=client)
    template = confirm_execute_verify(env, state, client, preview)['agent_result']['business_result']['resource_handle']
    native_templates = next(row[1]['wafm'] for row in client.calls if row[0] == PREFIX + 'model.registerWafm')
    assert len(native_templates) == 2 and all(key.startswith('Gateway_') for key in native_templates)
    env, state, client, preview = model_preview(tmp_path, 'window.create', {'title': 'Weather', 'width': 400, 'height': 300}, version=version, client=client)
    window = confirm_execute_verify(env, state, client, preview)['agent_result']['business_result']['resource_handle']
    env, state, client, preview = model_preview(tmp_path, 'model.createHandle', {'window': window, 'template': template, 'template_key': 'Second'}, version=version, client=client)
    result = confirm_execute_verify(env, state, client, preview)
    assert result['agent_result']['business_result']['cleanup_route'] == ['request-schema', PREFIX + 'model.destroyHandle']
    native_choice = next(row[1]['template'] for row in client.calls if row[0] == PREFIX + 'model.createHandle')
    assert native_choice in native_templates


def test_rejected_registration_never_recovers_a_usable_template(tmp_path):
    client = ModelClient(tmp_path)
    client.responses[PREFIX + 'model.registerWafm'] = {'success': False}
    env, state, client, preview = model_preview(tmp_path, 'model.registerWafm', rain_template(), client=client)
    tx = preview['transaction_id']
    _, shown = gateway.execute_gateway([*state, 'transaction-show', tx], env=env)
    gateway.execute_gateway([*state, 'confirm', tx, '--confirmation-token', shown['confirmation']['token']], env=env)
    code, executed = gateway.execute_gateway([*state, 'execute', tx], env=env, client_factory=lambda _: client)
    assert code == 0, executed
    code, rejected = gateway.execute_gateway([*state, 'verify', tx], env=env, client_factory=lambda _: client)
    assert code != 0 and rejected['verified'] is False, rejected
    code, recovered = gateway.execute_gateway([*state, 'authoring-resource', tx], env=env, client_factory=lambda _: client)
    assert code != 0, recovered
    assert 'Rejected template registration' in recovered['message']
    assert len([row for row in client.calls if row[0] == PREFIX + 'model.registerWafm']) == 1


def test_window_close_preview_cannot_overtake_a_frontend_awaiting_ownership_verification(tmp_path):
    client = ModelClient(tmp_path)
    client.responses[PREFIX + 'window.close'] = {}
    env, state, client, preview = model_preview(tmp_path, 'model.registerWafm', rain_template(), client=client)
    template = confirm_execute_verify(env, state, client, preview)['agent_result']['business_result']['resource_handle']
    env, state, client, preview = model_preview(tmp_path, 'window.create', {'title': 'Owned', 'width': 10, 'height': 10}, client=client)
    window = confirm_execute_verify(env, state, client, preview)['agent_result']['business_result']['resource_handle']
    env, state, client, close = model_preview(tmp_path, 'window.close', {'window': window}, client=client)
    env, state, client, frontend = model_preview(tmp_path, 'model.createHandle', {'window': window, 'template': template}, client=client)
    for preview in (close, frontend):
        _, shown = gateway.execute_gateway([*state, 'transaction-show', preview['transaction_id']], env=env)
        code, confirmed = gateway.execute_gateway([*state, 'confirm', preview['transaction_id'], '--confirmation-token', shown['confirmation']['token']], env=env)
        assert code == 0, confirmed
    code, executed = gateway.execute_gateway([*state, 'execute', frontend['transaction_id']], env=env, client_factory=lambda _: client)
    assert code == 0, executed
    code, blocked = gateway.execute_gateway([*state, 'execute', close['transaction_id']], env=env, client_factory=lambda _: client)
    assert code != 0 and 'unresolved cleanup ownership' in blocked['message'], blocked
    assert PREFIX + 'window.close' not in [row[0] for row in client.calls]
    code, recovered = gateway.execute_gateway([*state, 'authoring-resource', frontend['transaction_id']], env=env, client_factory=lambda _: client)
    assert code == 0 and recovered['agent_result']['resource_kind'] == 'model', recovered
    env, state, client, destroy = model_preview(tmp_path, 'model.destroyHandle', {'model': recovered['agent_result']['resource_handle']}, client=client)
    confirm_execute_verify(env, state, client, destroy)
    code, executed = gateway.execute_gateway([*state, 'execute', close['transaction_id']], env=env, client_factory=lambda _: client)
    assert code == 0, executed
    assert len([row for row in client.calls if row[0] == PREFIX + 'model.createHandle']) == 1


def test_creation_recovery_rejects_an_older_live_authoring_version_before_context_lookup(tmp_path):
    client = ModelClient(tmp_path, version='2024.1')
    env, state, client, preview = model_preview(tmp_path, 'window.create', {'title': 'Owned', 'width': 10, 'height': 10}, version='2024.1', client=client)
    confirm_execute_verify(env, state, client, preview)
    set_gateway_config(env, wwise_version='2022.1', project_modification_policy='ask_before_changes')
    older_client = LayoutClient(tmp_path, version='2022.1')
    code, rejected = gateway.execute_gateway([*state, 'authoring-resource', preview['transaction_id']], env=env, client_factory=lambda _: older_client)
    assert code != 0, rejected
    assert 'Selected connection configuration changed after Preview creation' in rejected['message'], rejected
    assert 'KeyError' not in json.dumps(rejected)
    assert not any(uri.startswith(PREFIX + 'window.') or uri.startswith(PREFIX + 'model.') for uri, _, _ in older_client.calls)


@pytest.mark.parametrize(('version', 'digest'), [
    ('2024.1', 'ef6edeaae18bf7b879acec3aca0f4353bdf220827791351203812d2ef922bf90'),
    ('2025.1', 'b2bc3ec3e63e151ee0d52748b5b5a2f25fa7777179b0763669b2b2f76753fa50'),
])
def test_wafm_public_schema_reuses_one_fresh_catalog_without_changing_content(tmp_path, monkeypatch, version, digest):
    from pathlib import Path
    from wwise_waapi.canonical import canonical_sha256
    from wwise_waapi.native_catalog import NATIVE_CATALOG_ROOT

    source = NATIVE_CATALOG_ROOT / version / 'wwise-authoring.json'
    read_bytes = Path.read_bytes
    reads = []
    damaged = False

    def read(path):
        raw = read_bytes(path)
        if path == source:
            reads.append(path)
            return raw + b' ' if damaged else raw
        return raw

    monkeypatch.setattr(Path, 'read_bytes', read)
    argv = ['--version', version, 'request-schema', PREFIX + 'model.registerWafm']
    env = gateway_env(tmp_path)
    code, response = gateway.execute_gateway(argv, env=env, client_factory=lambda _: pytest.fail('offline schema opened client'))
    assert code == 0, response
    assert canonical_sha256(response['business_adapter']) == digest
    assert len(reads) == 1, 'one public schema call must verify one fresh graph, then reuse its immutable data'
    response['business_adapter']['construction']['widget_kinds']['Checkbox']['attributes'].clear()
    code, repeated = gateway.execute_gateway(argv, env=env)
    assert code == 0 and canonical_sha256(repeated['business_adapter']) == digest
    assert len(reads) == 2, 'a later command must independently verify its current catalog bytes'
    damaged = True
    code, rejected = gateway.execute_gateway(argv, env=env)
    assert code != 0 and 'digest mismatch' in str(rejected), rejected
    assert len(reads) == 3
