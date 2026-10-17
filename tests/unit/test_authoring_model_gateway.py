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
        '--task-authority', start['task_authority'], '--expected-revision', '0', '--plan', json.dumps({'window': handle})],
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
