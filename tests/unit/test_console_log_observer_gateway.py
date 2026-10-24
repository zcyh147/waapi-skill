"""Console log additions are observed during their one public execution."""
from copy import deepcopy
from pathlib import Path

import pytest

from tests.unit.test_runtime_business_gateway import (
    _LogControlClient, _env, _public_runtime_preview, gateway,
)

ADD = 'ak.wwise.core.log.addItem'
TOPIC = 'ak.wwise.core.log.itemAdded'


class ConsoleLogClient(_LogControlClient):
    def __init__(self, tmp_path, *, version='2025.1', scenario='matched'):
        super().__init__(tmp_path, version=version)
        self.console = True
        self.rows = []
        self.callback = None
        self.order = []
        self.scenario = scenario

    def subscribe(self, uri, callback, options=None):
        assert uri == TOPIC and options in (None, {})
        self.order.append('subscribed')
        if self.scenario == 'subscribe-error':
            raise RuntimeError('external subscription unavailable')
        self.callback = callback
        return self

    def unsubscribe(self):
        self.order.append('unsubscribed')
        if self.scenario == 'overflow-during-close' and self.callback:
            for _ in range(65):
                self.callback(channel='general', item={'message': 'competing',
                    'severity': 'Message', 'time': 1720000000, 'messageId': 'Custom'})
        self.callback = None
        if self.scenario == 'close-error':
            raise RuntimeError('external unsubscribe failed')
        if self.scenario == 'close-false':
            return False
        return True

    def call(self, uri, args=None, options=None):
        if uri == 'ak.wwise.core.getInfo':
            result = super().call(uri, args, options)
            minor, build = {'2023.1': (19, 8928), '2024.1': (13, 9056), '2025.1': (7, 9143)}[self.version]
            result['version'].update(minor=minor, build=build)
            return result
        if uri == ADD:
            self.order.append('add')
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            payload = {'channel': args['channel'], 'item': {'message': args['message'],
                'severity': args['severity'], 'time': 1720000000, 'messageId': 'Custom'}}
            if self.scenario == 'wrong-channel': payload['channel'] = 'general'
            if self.scenario == 'wrong-message': payload['item']['message'] = 'competing writer'
            if self.scenario == 'wrong-severity': payload['item']['severity'] = 'Error'
            if self.scenario == 'malformed': payload['item']['parameters'] = [42]
            if self.scenario == 'too-large': payload['item']['message'] = '界' * 30000
            if self.scenario == 'not-json': payload['item']['time'] = float('nan')
            count = 65 if self.scenario == 'overflow' else 64 if self.scenario == 'event-limit' else 1
            if self.scenario == 'event-limit': payload['item']['message'] = 'competing writer'
            if self.callback and self.scenario != 'missing':
                for _ in range(count): self.callback(**deepcopy(payload))
            if self.scenario == 'native-error': raise RuntimeError('external add outcome unavailable')
            if self.scenario == 'malformed-ack': return {'unexpected': True}
            return {}
        return super().call(uri, args, options)


@pytest.mark.parametrize('version', ('2025.1',))
def test_console_add_observes_before_once_execution_and_verifies_from_durable_event(tmp_path: Path, version):
    client = ConsoleLogClient(tmp_path, version=version)
    state = tmp_path / 'state'
    preview, invoke = _public_runtime_preview(tmp_path, client, state, ADD,
        ('--message', 'owned console receipt', '--log-channel', 'source-control', '--severity', 'warning'))
    assert client.order == []
    executed = invoke(['execute', preview['transaction_id']])
    assert client.order == ['subscribed', 'add', 'unsubscribed']

    shown = invoke(['transaction-show', preview['transaction_id']])
    execution = next(row['details']['dispatch_result'] for row in shown['events']
        if row['event_type'] == 'execution_completed')
    assert execution['result'] == {}
    observation = execution['log_item_observation']
    assert observation['outcome'] == 'matched'
    assert observation['cleanup']['status'] == 'unsubscribed'
    assert observation['event']['channel'] == 'sourceControl'
    # Verification is a separate public invocation; no live event remains.
    verified = invoke(executed['next_command']['gateway_argv'])
    assert verified['verified'] is True
    scope = verified['verification']['verification_scope']['log_observation']
    assert scope['outcome'] == 'matching_item_event'
    assert scope['exclusive_causation_verified'] is False
    assert scope['continuing_channel_state_verified'] is False
    assert client.order == ['subscribed', 'add', 'unsubscribed']
    code, replay = gateway.execute_gateway(['--state-dir', str(state), 'execute', preview['transaction_id']],
        env=_env(tmp_path, version=version), client_factory=lambda _: client)
    assert code == 2, replay
    assert client.order == ['subscribed', 'add', 'unsubscribed']


@pytest.mark.parametrize('version', ('2025.1',))
def test_log_schema_and_console_preview_disclose_add_observer_and_clear_limit(tmp_path, version):
    code, schema = gateway.execute_gateway(['request-schema', ADD], env=_env(tmp_path, version=version),
        client_factory=lambda _: pytest.fail('Schema discovery must be offline'))
    assert code == 0
    disclosure = schema['business_adapter']['declaration']['verification']['console_add_observer']
    assert disclosure['topic'] == TOPIC
    assert disclosure['wait_seconds'] == 5
    assert disclosure['maximum_events'] == 64
    assert disclosure['maximum_event_bytes'] == 65536
    assert disclosure['matching'] == 'exact_sealed_channel_message_severity'
    client = ConsoleLogClient(tmp_path, version=version)
    preview, invoke = _public_runtime_preview(tmp_path, client, tmp_path / 'state', ADD,
        ('--message', 'owned console receipt'))
    shown = invoke(['transaction-show', preview['transaction_id']])
    plan = shown['artifact']['prepared_operation']['verification_plan']
    assert plan['console_add_observer'] == disclosure
    assert client.order == []
    clear = 'ak.wwise.core.log.clear'
    code, schema = gateway.execute_gateway(['request-schema', clear], env=_env(tmp_path, version=version),
        client_factory=lambda _: pytest.fail('Schema discovery must be offline'))
    assert code == 0
    assert schema['business_adapter']['declaration']['verification']['native_log_observation_policy']['console_minimum_version'] == '2025.1.4'


@pytest.mark.parametrize('version', ('2025.1',))
@pytest.mark.parametrize('scenario,outcome', [('close-false', 'console_event_cleanup_failed'),
    ('close-error', 'console_event_cleanup_failed'), ('malformed', 'malformed_event'),
    ('overflow', 'overflow'), ('too-large', 'invalid_event_ingress'), ('not-json', 'invalid_event_ingress')])
def test_console_add_invalid_observation_or_cleanup_fails_without_replaying(tmp_path, monkeypatch, version, scenario, outcome):
    client = ConsoleLogClient(tmp_path, version=version, scenario=scenario)
    state = tmp_path / 'state'
    preview, invoke = _public_runtime_preview(tmp_path, client, state, ADD,
        ('--message', 'owned console receipt', '--severity', 'warning', '--log-channel', 'source-control'))
    code, executed = gateway.execute_gateway(['--state-dir', str(state), 'execute', preview['transaction_id']],
        env=_env(tmp_path, version=version), client_factory=lambda _: client)
    assert code == (2 if scenario.startswith('close') else 0), executed
    assert executed['state'] == 'executed_unverified'
    code, verified = gateway.execute_gateway(['--state-dir', str(state), *executed['next_command']['gateway_argv']],
        env=_env(tmp_path, version=version), client_factory=lambda _: client)
    assert code == 2 and verified['state'] == 'verification_failed', verified
    scope = verified['verification']['verification_scope']['log_observation']
    assert scope['outcome'] == outcome and scope['effect_observed'] is False
    assert scope['execution_observation']['cleanup']['status'] == ('unsubscribe_failed' if scenario.startswith('close') else 'unsubscribed')
    order = ['subscribed', 'add', 'unsubscribed'] + (['unsubscribed'] if scenario.startswith('close') else [])
    assert client.order == order
    code, replay = gateway.execute_gateway(['--state-dir', str(state), 'execute', preview['transaction_id']],
        env=_env(tmp_path, version=version), client_factory=lambda _: client)
    assert code == 2 and client.order == order, replay


@pytest.mark.parametrize('version', ('2025.1',))
def test_console_add_overflow_before_unsubscribe_finishes_cannot_verify_matching_event(tmp_path, version):
    client = ConsoleLogClient(tmp_path, version=version, scenario='overflow-during-close')
    state = tmp_path / 'state'
    preview, invoke = _public_runtime_preview(tmp_path, client, state, ADD, ('--message', 'owned receipt'))
    executed = invoke(['execute', preview['transaction_id']])
    code, verified = gateway.execute_gateway(['--state-dir', str(state), *executed['next_command']['gateway_argv']],
        env=_env(tmp_path, version=version), client_factory=lambda _: client)
    assert code == 2 and verified['state'] == 'verification_failed', verified
    observed = verified['verification']['verification_scope']['log_observation']
    assert observed['outcome'] == 'overflow' and observed['effect_observed'] is False
    assert observed['execution_observation']['event']['item']['message'] == 'owned receipt'
    assert observed['execution_observation']['cleanup']['status'] == 'unsubscribed'
    assert client.order == ['subscribed', 'add', 'unsubscribed']


@pytest.mark.parametrize('version', ('2025.1',))
@pytest.mark.parametrize('scenario,outcome', [('missing', 'timeout'),
    ('wrong-channel', 'no_matching_event'), ('wrong-message', 'no_matching_event'),
    ('wrong-severity', 'no_matching_event'), ('event-limit', 'event_limit')])
def test_console_add_missing_exact_event_stays_acknowledged_unverified(tmp_path, monkeypatch, version, scenario, outcome):
    from wwise_waapi import runtime_log_observer
    # Time is an external boundary: exhaust only this observer's wait clock.
    ticks = iter((0, 6) if scenario == 'missing' else (0, 0, 6))
    if scenario != 'event-limit':
        monkeypatch.setattr(runtime_log_observer, 'monotonic', lambda: next(ticks, 6))
    client = ConsoleLogClient(tmp_path, version=version, scenario=scenario)
    state = tmp_path / 'state'
    preview, invoke = _public_runtime_preview(tmp_path, client, state, ADD,
        ('--message', 'owned console receipt', '--severity', 'warning', '--log-channel', 'source-control'))
    executed = invoke(['execute', preview['transaction_id']])
    verified = invoke(executed['next_command']['gateway_argv'])
    assert verified['state'] == 'result_schema_checked' and verified['verified'] is False
    observation = verified['verification']['verification_scope']['log_observation']
    assert observation['outcome'] == outcome and observation['effect_observed'] is False
    assert observation['execution_observation']['cleanup']['status'] == 'unsubscribed'
    assert observation['execution_observation']['events_observed'] == (0 if scenario == 'missing' else 64 if scenario == 'event-limit' else 1)
    code, replay = gateway.execute_gateway(['--state-dir', str(state), 'execute', preview['transaction_id']],
        env=_env(tmp_path, version=version), client_factory=lambda _: client)
    assert code == 2 and client.order == ['subscribed', 'add', 'unsubscribed'], replay


@pytest.mark.parametrize('version', ('2025.1',))
@pytest.mark.parametrize('scenario', ('native-error', 'subscribe-error', 'malformed-ack'))
def test_console_add_native_or_subscription_failure_retains_once_attempt_and_original_result(tmp_path, version, scenario):
    client = ConsoleLogClient(tmp_path, version=version, scenario=scenario)
    state = tmp_path / 'state'
    preview, invoke = _public_runtime_preview(tmp_path, client, state, ADD,
        ('--message', 'owned console receipt'))
    code, executed = gateway.execute_gateway(['--state-dir', str(state), 'execute', preview['transaction_id']],
        env=_env(tmp_path, version=version), client_factory=lambda _: client)
    assert code == (0 if scenario == 'malformed-ack' else 2), executed
    if scenario == 'malformed-ack':
        code, verified = gateway.execute_gateway(['--state-dir', str(state), *executed['next_command']['gateway_argv']],
            env=_env(tmp_path, version=version), client_factory=lambda _: client)
        assert code == 2 and verified['state'] == 'verification_failed', verified
    else:
        assert executed['state'] == 'indeterminate' and executed['automatic_retry'] is False
    shown = invoke(['transaction-show', preview['transaction_id']])
    saved = next(row['details']['dispatch_result'] for row in shown['events']
        if isinstance(row.get('details'), dict) and 'dispatch_result' in row['details'])
    assert saved['log_item_observation']['outcome'] == ('subscription_failed' if scenario == 'subscribe-error'
        else 'native_call_failed' if scenario == 'native-error' else 'matched')
    if scenario == 'malformed-ack': assert saved['result'] == {'unexpected': True}
    order = ['subscribed'] if scenario == 'subscribe-error' else ['subscribed', 'add', 'unsubscribed']
    assert client.order == order
    code, replay = gateway.execute_gateway(['--state-dir', str(state), 'execute', preview['transaction_id']],
        env=_env(tmp_path, version=version), client_factory=lambda _: client)
    assert code == 2 and client.order == order, replay


def test_known_old_console_log_topic_refuses_before_subscription(tmp_path):
    client = ConsoleLogClient(tmp_path, version='2023.1')
    original = client.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri == 'ak.wwise.core.getInfo':
            result['version'].update(minor=19, build=8928)
        return result
    client.call = call
    code, schema = gateway.execute_gateway(['topic-schema', TOPIC], env=_env(tmp_path, version='2023.1'),
        client_factory=lambda _: pytest.fail('offline schema connected'))
    assert code == 0, schema
    digest = schema['continuation']['contract_binding']['value']
    code, result = gateway.execute_gateway(['--timeout', '0.05', 'wait-topic', TOPIC,
        '--event-count', '1', '--topic-contract-digest', digest], env=_env(tmp_path, version='2023.1'),
        client_factory=lambda _: client)
    assert code == 2 and result['error_code'] == 'NATIVE_LOG_OBSERVATION_UNAVAILABLE', result
    assert client.order == []


def test_supported_console_clear_verifies_actual_nonempty_getter_removal(tmp_path):
    client = _LogControlClient(tmp_path, version='2025.1')
    client.console = True
    original = client.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri == 'ak.wwise.core.getInfo':
            result['version'].update(minor=7, build=9143)
        return result
    client.call = call
    assert client.rows
    client.after = []
    preview, invoke = _public_runtime_preview(tmp_path, client, tmp_path / 'state',
        'ak.wwise.core.log.clear', ('--log-channel', 'general'))
    executed = invoke(['execute', preview['transaction_id']])
    verified = invoke(executed['next_command']['gateway_argv'])
    assert verified['verified'] is True, verified
    observation = verified['verification']['verification_scope']['log_observation']
    assert observation['outcome'] == 'prior_contents_absent' and observation['post_channel_empty']
    assert sum(uri == 'ak.wwise.core.log.clear' for uri, _, _ in client.calls) == 1


@pytest.mark.parametrize('command', ['wait-topic', 'stream-topic'])
@pytest.mark.parametrize('version,minor,build,console,state', [
    ('2021.1', 14, 8108, True, 'unavailable'), ('2022.1', 19, 8584, True, 'unavailable'),
    ('2023.1', 19, 8928, True, 'unavailable'), ('2024.1', 13, 9056, True, 'unavailable'),
    ('2025.1', 3, 9000, True, 'unavailable'), ('2025.1', 4, 9000, True, 'supported'),
    ('2025.1', None, 9143, True, 'unknown'), ('2023.1', 19, 8928, False, 'supported')])
def test_log_topic_public_host_build_policy(tmp_path, command, version, minor, build, console, state):
    client = _LogControlClient(tmp_path, version=version)
    client.console = console
    original = client.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri == 'ak.wwise.core.getInfo':
            result['version'].update(minor=minor, build=build)
            if minor is None: result['version'].pop('minor')
        return result
    client.call = call
    subscriptions = []
    def subscribe(uri, callback, options=None):
        subscriptions.append(uri)
        callback(channel='general', item={'message': 'owned', 'severity': 'Message', 'time': 1, 'messageId': ''})
        class Handle:
            def unsubscribe(self): return True
        return Handle()
    client.subscribe = subscribe
    env = _env(tmp_path, version=version)
    code, schema = gateway.execute_gateway(['topic-schema', TOPIC], env=env,
        client_factory=lambda _: pytest.fail('offline disclosure connected'))
    assert code == 0 and schema['native_log_observation_policy']['native_change'] == 'WG-80630'
    digest = schema['continuation']['contract_binding']['value']
    code, result = gateway.execute_gateway(['--timeout', '1', command, TOPIC, '--event-count', '1',
        '--topic-contract-digest', digest], env=env, client_factory=lambda _: client, stream_sink=lambda _: None)
    if state == 'supported':
        assert code == 0, result
        assert subscriptions == [TOPIC]
    else:
        assert code == 2 and result['native_observation_support']['state'] == state, result
        assert subscriptions == []


@pytest.mark.parametrize('version', ['2023.1', '2024.1'])
@pytest.mark.parametrize('operation,declaration', [(ADD, ('--message', 'one owned marker')),
    ('ak.wwise.core.log.clear', ('--log-channel', 'general'))])
def test_old_console_log_commands_execute_once_without_observer(tmp_path, version, operation, declaration):
    client = ConsoleLogClient(tmp_path, version=version)
    state = tmp_path / 'state'
    preview, invoke = _public_runtime_preview(tmp_path, client, state, operation, declaration)
    executed = invoke(['execute', preview['transaction_id']])
    verified = invoke(executed['next_command']['gateway_argv'])
    assert verified['state'] == 'result_schema_checked' and not verified['verified']
    scope = verified['verification']['verification_scope']['log_observation']
    assert scope['outcome'] == 'console_log_unobservable'
    assert scope['native_observation_support']['state'] == 'unavailable'
    assert 'subscribed' not in client.order
    assert sum(uri == operation for uri, _, _ in client.calls) == 1
    code, replay = gateway.execute_gateway(['--state-dir', str(state), 'execute', preview['transaction_id']],
        env=_env(tmp_path, version=version), client_factory=lambda _: client)
    assert code == 2 and sum(uri == operation for uri, _, _ in client.calls) == 1


@pytest.mark.parametrize('remaining', ['competing', 'unchanged', 'already-empty', 'malformed', 'drift'])
def test_supported_console_clear_retains_readback_and_drift_boundaries(tmp_path, remaining):
    client = _LogControlClient(tmp_path, version='2025.1')
    client.console = True
    original = client.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri == 'ak.wwise.core.getInfo': result['version'].update(minor=7, build=9143)
        return result
    client.call = call
    old = dict(client.rows[0])
    if remaining == 'already-empty': client.rows = []
    client.after = ([old] if remaining == 'unchanged' else [{'message': 'other', 'severity': 'Warning',
        'messageId': '', 'time': 2}] if remaining == 'competing' else [{'message': 42}] if remaining == 'malformed' else [])
    state = tmp_path / 'state'
    preview, invoke = _public_runtime_preview(tmp_path, client, state, 'ak.wwise.core.log.clear', ('--log-channel', 'general'))
    if remaining == 'drift': client.rows = []
    code, executed = gateway.execute_gateway(['--state-dir', str(state), 'execute', preview['transaction_id']],
        env=_env(tmp_path), client_factory=lambda _: client)
    if remaining == 'drift':
        assert code == 2 and not any(uri.endswith('log.clear') for uri, _, _ in client.calls), executed
        return
    assert code == 0, executed
    code, verified = gateway.execute_gateway(['--state-dir', str(state), 'verify', preview['transaction_id']],
        env=_env(tmp_path), client_factory=lambda _: client)
    if remaining == 'malformed':
        assert code == 2 and not verified['verified'], verified
    else:
        assert code == 0 and verified['verified'] is (remaining != 'unchanged'), verified
        observed = verified['verification']['verification_scope']['log_observation']
        assert observed['continuing_channel_state_verified'] is False
    assert sum(uri.endswith('log.clear') for uri, _, _ in client.calls) == 1


def test_console_log_host_patch_drift_requires_repreview_before_effect(tmp_path):
    client = ConsoleLogClient(tmp_path, version='2025.1')
    state = tmp_path / 'state'
    preview, invoke = _public_runtime_preview(tmp_path, client, state, ADD, ('--message', 'owned'))
    original = client.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri == 'ak.wwise.core.getInfo': result['version']['minor'] = 3
        return result
    client.call = call
    code, result = gateway.execute_gateway(['--state-dir', str(state), 'execute', preview['transaction_id']],
        env=_env(tmp_path), client_factory=lambda _: client)
    assert code == 2 and result['state'] == 'repreview_required', result
    assert not client.order and not any(uri == ADD for uri, _, _ in client.calls)


def test_supported_console_get_keeps_real_nonempty_rows_and_partial_bounds(tmp_path):
    client = ConsoleLogClient(tmp_path, version='2025.1')
    client.rows = [{'message': text, 'severity': 'Message', 'time': 1, 'messageId': ''} for text in ['one', 'two']]
    code, result = gateway.execute_gateway(['--state-dir', str(tmp_path / 'state'), 'core-call', 'ak.wwise.core.log.get', '--log-channel', 'general',
        '--max-results', '1'], env=_env(tmp_path), client_factory=lambda _: client)
    import json
    assert code == 0, json.dumps(result, ensure_ascii=False)
    assert result['native_observation_support']['state'] == 'supported'
    assert result['agent_result']['items'][0]['message'] == 'two'
    assert result['agent_result']['complete'] is False and result['agent_result']['total_count'] == 2
