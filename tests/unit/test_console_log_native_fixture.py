"""Console addition collector reaches the existing durable category writer."""
from copy import deepcopy
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.destructive.support import exact_real_evidence, sandbox_fixture
from tests.unit.test_console_log_observer_gateway import ADD, ConsoleLogClient
from tests.unit.test_runtime_business_gateway import _env


@pytest.mark.parametrize('version', ('2023.1', '2024.1', '2025.1'))
@pytest.mark.parametrize('scenario', ('matched', 'native-error'))
def test_console_log_native_node_persists_final_outcome_and_partial_failure(tmp_path, monkeypatch, version, scenario, peer=False, getter=False):
    monkeypatch.setenv('WWISE_LIVE', '1')
    monkeypatch.setenv('WWISE_DESTRUCTIVE', '1')
    workflow = importlib.import_module('tests.destructive.test_gateway_workflow_transaction_matrix')
    node = workflow.test_console_log_addition_observer
    client = ConsoleLogClient(tmp_path, version=version, scenario=scenario)
    env = _env(tmp_path, version=version)
    native = client.call
    def call(uri, args=None, options=None):
        result = native(uri, args, options)
        if uri == 'ak.wwise.core.getInfo':
            result = deepcopy(result)
            minor, build = {'2023.1': (19, 8928), '2024.1': (13, 9056), '2025.1': (7, 9143)}[version]
            result['version'].update(minor=minor, build=build, displayName=f'v{version}.{minor}.{build}')
        return result
    client.call = call
    connections = []
    class Connection:
        def __getattr__(self, name):
            return getattr(client, name)
    def factory(_url):
        connection = Connection()
        connections.append(connection)
        return connection
    monkeypatch.setattr(workflow.waapi_gateway, 'default_client_factory', factory)
    source = tmp_path / 'source'
    source.mkdir()
    source_project = source / 'SampleProject.wproj'
    source_project.write_text('immutable fixture', encoding='utf-8')
    source_hash = sandbox_fixture.hash_project(source)
    metadata = sandbox_fixture.SandboxMetadata(str(source_project), str(source), str(client.project_root),
        str(client.project_file), version, 0, source_hash, sandbox_fixture.hash_project(client.project_root),
        source_project.stat().st_mtime, process_cleanup_result='cleaned', process_cleanup_details={'residual_processes': []})
    sandbox = sandbox_fixture.SandboxProject(source_project, source, tmp_path, client.project_root, client.project_file, metadata)
    lock = sandbox_fixture.LiveSandboxLock(tmp_path / 'locks')
    lock.__enter__()
    endpoint = SimpleNamespace(host='127.0.0.1', port=31337, waapi_url='ws://127.0.0.1:31337/waapi')
    runtime = workflow._WorkflowSandboxRuntime(version, sandbox, endpoint, tmp_path / 'state', env,
        workflow.exact_git_candidate(workflow.REPO_ROOT), [])
    nodeid = 'tests/destructive/test_gateway_workflow_transaction_matrix.py::test_console_log_addition_observer'
    item = SimpleNamespace(path=workflow.__file__, nodeid=nodeid, _waapi_phase_reports={'setup': 'passed'})
    error = None
    try:
        node(runtime)
    except AssertionError as exc:
        error = exc
    item._waapi_phase_reports['call'] = 'passed' if error is None else 'failed'
    evidence = tmp_path / 'category.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(evidence))
    monkeypatch.setattr(sandbox_fixture, 'KEEP_ON_FAILURE_ROOT', tmp_path / 'retained')
    final_error = exact_real_evidence.finalize_exact_real_evidence(repo_root=workflow.REPO_ROOT,
        candidate=runtime.candidate, version=version, request=SimpleNamespace(session=SimpleNamespace(items=[item])),
        module_file=Path(workflow.__file__), started_at_unix_ns=1, active_error=error, deferred_error=None,
        sandbox=sandbox, lock=lock, state_dir=runtime.state_dir,
        host={'is_command_line': True, 'version': version}, categories=runtime.category_results,
        source={'hash_before': source_hash.digest, 'hash_after': sandbox_fixture.hash_project(source).digest})
    assert final_error is None
    records = [json.loads(line) for line in evidence.read_text().splitlines()]
    final = records[-1]
    assert final['contract'] == 'waapi-skill.host-category-evidence/v3'
    assert final['invocation']['phase'] == 'final'
    category, = final['categories']
    assert category['category'] == 'console-log-addition-observer'
    receipt = json.loads(Path(category['receipt_path']).read_text())
    if getter:
        return client, connections, receipt, final, error, records
    transaction, = final['transactions']
    assert transaction['transaction_id'] == receipt['transaction']['transaction_id']
    if peer:
        return client, connections, receipt, final, error, records
    assert client.order == (['subscribed', 'add', 'unsubscribed'] if version == '2025.1' else ['add'])
    assert sum(uri == ADD for uri, _, _ in client.calls) == 1
    assert not any(uri.endswith('log.clear') for uri, _, _ in client.calls)
    assert all('subscribe' not in vars(connection) for connection in connections)
    if scenario == 'matched' and version == '2025.1':
        assert error is None
        assert [row['invocation']['outcome'] for row in records] == ['PENDING', 'PASS']
        assert category['status'] == 'PASS' and transaction['state'] == 'verified'
        assert final['residual_state']['sandbox'] == 'deleted'
        assert not sandbox.sandbox_path.exists()
        assert receipt['durable_observation'] == receipt['transaction']['execute']['dispatch_result']['log_item_observation']
        assert receipt['transaction']['verify']['verification']['verification_scope']['log_observation']['effect_observed'] is True
    else:
        assert error is not None
        assert [row['invocation']['outcome'] for row in records] == ['FAIL']
        expected_state = 'indeterminate' if scenario == 'native-error' else 'result_schema_checked'
        assert category['status'] == 'FAIL' and transaction['state'] == expected_state
        assert final['residual_state']['sandbox'] == 'quarantined'
        assert Path(final['residual_state']['quarantine_path']).is_dir()
        if version != '2025.1':
            assert 'log_item_observation' not in receipt['transaction']['execute']['dispatch_result']
            return
        assert receipt['transaction']['execute']['dispatch_result']['log_item_observation']['subscribed'] is True
        if scenario == 'missing':
            assert receipt['transaction']['execute']['dispatch_result']['result'] == {}
            assert receipt['transaction']['verify']['verified'] is False
            assert receipt['transaction']['verify']['verification']['verification_scope']['log_observation']['outcome'] == 'timeout'
        else:
            assert receipt['transaction']['execute']['automatic_retry'] is False
            assert 'verify' not in receipt['transaction']


@pytest.mark.parametrize('scenario', ('matched', 'native-error', 'missing'))
def test_opted_in_console_log_diagnostic_reaches_final_writer_and_restores_hooks(tmp_path, monkeypatch, scenario, subscription_id=42):
    import asyncio
    from autobahn.asyncio.wamp import ApplicationSession
    from autobahn.wamp.message import Event, Subscribed
    from autobahn.wamp.request import Handler, SubscribeRequest
    from waapi.client.event import EventHandler
    import sys

    clients = []
    class DecodedClient(ConsoleLogClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            clients.append(self)
            self.session = ApplicationSession()
            self.session._session_id = 123
            self.original_callback = None
            self.handler = None

        def subscribe(self, uri, callback, options=None):
            self.order.append('subscribed')
            self.original_callback = callback
            self.handler = EventHandler(self, callback)
            # External WAMP acknowledgment follows the pinned parser and actual
            # session's SUBSCRIBED dispatch, including its valid zero-ID edge.
            loop = asyncio.new_event_loop()
            try:
                replied = loop.create_future()
                self.session._subscribe_reqs[1] = SubscribeRequest(1, uri, replied, Handler(self.handler.on_event))
                self.session.onMessage(Subscribed.parse([Subscribed.MESSAGE_TYPE, 1, subscription_id]))
                self.handler.subscription = replied.result()
            finally:
                loop.close()
            return self.handler

        def unsubscribe(self, handler):
            assert handler is self.handler
            self.order.append('unsubscribed')
            return True

        def call(self, uri, args=None, options=None):
            if uri != ADD:
                return super().call(uri, args, options)
            self.order.append('add')
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            if scenario == 'native-error':
                raise RuntimeError('external add failed without an EVENT')
            if scenario == 'missing':
                return {}
            if self.handler is not None:
                self.session.onMessage(Event(subscription_id, 99, kwargs={'channel': args['channel'],
                'item': {'message': args['message'], 'severity': args['severity'], 'time': 1720000000, 'messageId': 'Custom'}}))
            return {}

    monkeypatch.setattr(sys.modules[__name__], 'ConsoleLogClient', DecodedClient)
    monkeypatch.setenv('WWISE_CONSOLE_LOG_DIAGNOSTIC', 'decoded-event-v1')
    if scenario == 'missing':
        from wwise_waapi import runtime_log_observer
        ticks = iter((0, 6))
        monkeypatch.setattr(runtime_log_observer, 'monotonic', lambda: next(ticks, 6))
    test_console_log_native_node_persists_final_outcome_and_partial_failure(tmp_path, monkeypatch, '2023.1', scenario)
    receipt = json.loads((tmp_path / 'state/console-log-addition-observer.json').read_text())
    diagnostic = receipt['delivery_diagnostic']
    assert diagnostic['contract'] == 'waapi-skill.console-log-decoded-event-diagnostic/v1'
    assert diagnostic['subscription_id'] is None and diagnostic['installed'] is False
    expected = 0
    assert diagnostic['decoded_events'] == diagnostic['callback_entries'] == expected
    assert diagnostic['restored'] is True
    assert len(json.dumps(diagnostic).encode()) <= 4096
    client, = clients
    assert 'onMessage' not in vars(client.session)
    assert 'subscribe' not in vars(client)
    assert client.handler is None


@pytest.mark.parametrize('scenario', ('matched', 'missing', 'native-error'))
def test_zero_subscription_ack_diagnostic_reaches_final_writer(tmp_path, monkeypatch, scenario):
    test_opted_in_console_log_diagnostic_reaches_final_writer_and_restores_hooks(
        tmp_path, monkeypatch, scenario, subscription_id=0)


@pytest.mark.parametrize('boundary', ('message', 'callback', 'body'))
def test_log_diagnostic_delegates_original_exception_and_restores_exact_attributes(monkeypatch, boundary):
    from autobahn.asyncio.wamp import ApplicationSession
    from autobahn.wamp.message import Event
    from autobahn.wamp.request import Handler, Subscription
    from waapi.client.event import EventHandler
    from tests.destructive.support.console_log_diagnostic import TOPIC, decoded_log_diagnostic

    sentinel = RuntimeError('original failure')
    calls = []
    result = object()
    def original_message(message):
        calls.append(('message', message.subscription))
        if boundary == 'message':
            raise sentinel
        return result
    def original_callback(*args, **kwargs):
        calls.append(('callback', args, kwargs))
        if boundary == 'callback':
            raise sentinel
        return result
    session = ApplicationSession()
    session.onMessage = original_message
    handler = EventHandler(callback=original_callback)
    handler.subscription = Subscription(42, TOPIC, session, Handler(handler.on_event))
    def subscribe(*args, **kwargs):
        calls.append(('subscribe', args, kwargs))
        return handler
    client = SimpleNamespace(subscribe=subscribe)
    factory = lambda _: client
    gateway = SimpleNamespace(default_client_factory=factory)
    receipt = {}
    monkeypatch.setenv('WWISE_CONSOLE_LOG_DIAGNOSTIC', 'decoded-event-v1')
    with pytest.raises(RuntimeError) as failure:
        with decoded_log_diagnostic(gateway, receipt, version='2023.1'):
            assert gateway.default_client_factory('unused').subscribe(TOPIC, original_callback) is handler
            if boundary == 'message':
                session.onMessage(Event(42, 99))
            else:
                assert session.onMessage(Event(43, 99)) is result
                assert receipt['delivery_diagnostic']['decoded_events'] == 0
                assert handler.on_event('unchanged', value=7) is None
                raise sentinel
    assert failure.value is sentinel
    assert calls == ([('subscribe', (TOPIC, original_callback), {}), ('message', 42)] if boundary == 'message' else
        [('subscribe', (TOPIC, original_callback), {}), ('message', 43), ('callback', ('unchanged',), {'value': 7})])
    assert gateway.default_client_factory is factory and client.subscribe is subscribe
    assert session.onMessage is original_message and handler._callback is original_callback
    assert receipt['delivery_diagnostic']['restored'] is True


def test_log_diagnostic_dependency_preflight_blocks_before_any_client(monkeypatch):
    from tests.destructive.support import console_log_diagnostic
    gateway = SimpleNamespace(default_client_factory=lambda _: pytest.fail('preflight connected'))
    original = gateway.default_client_factory
    monkeypatch.setenv('WWISE_CONSOLE_LOG_DIAGNOSTIC', 'decoded-event-v1')
    monkeypatch.setattr(console_log_diagnostic, 'distribution_version', lambda _: 'unsupported')
    receipt = {}
    with pytest.raises(AssertionError, match='dependency versions differ'):
        with console_log_diagnostic.decoded_log_diagnostic(gateway, receipt, version='2023.1'):
            pytest.fail('unsupported preflight yielded')
    assert gateway.default_client_factory is original
    assert receipt['delivery_diagnostic']['installed'] is False


def test_known_old_console_peer_boundary_prevents_execution_and_reaches_final_writer(tmp_path, monkeypatch):
    import socket
    import waapi
    def forbidden(*args, **kwargs):
        pytest.fail('Console log fake chain forbids real client/socket construction', pytrace=False)
    monkeypatch.setattr(waapi, 'WaapiClient', forbidden)
    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setenv('WWISE_CONSOLE_LOG_PEER_DIAGNOSTIC', 'independent-session-v1')
    client, connections, receipt, final, error, records = test_console_log_native_node_persists_final_outcome_and_partial_failure(
        tmp_path, monkeypatch, '2023.1', 'matched', peer=True)
    peer = receipt['peer_diagnostic']
    assert error is not None and final['invocation']['outcome'] == 'FAIL'
    assert final['residual_state']['sandbox'] == 'quarantined'
    assert not peer['ack_before_execute'] and not peer['execute_attempted'] and not peer['complete']
    assert peer['terminal']['error_code'] == 'NATIVE_LOG_OBSERVATION_UNAVAILABLE'
    assert not client.order and not any(uri == ADD for uri, _, _ in client.calls)
    assert 'execute' not in receipt['transaction']
    assert final['source']['hash_before'] == final['source']['hash_after']


@pytest.mark.parametrize('fault', ['matched', 'empty-getter', 'uncleared'])
def test_owned_console_getter_clear_workflow_reaches_final_writer(tmp_path, monkeypatch, fault):
    import socket
    import sys
    import waapi
    def forbidden(*args, **kwargs):
        pytest.fail('Console log fake chain forbids real client/socket construction', pytrace=False)
    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setattr(waapi, 'WaapiClient', forbidden)
    class GetterClient(ConsoleLogClient):
        def call(self, uri, args=None, options=None):
            if uri.endswith('log.clear') and fault == 'uncleared': self.after = list(self.rows)
            result = super().call(uri, args, options)
            if uri == ADD and fault != 'empty-getter':
                self.rows.append({'message': args['message'], 'severity': args['severity'], 'time': 1720000000, 'messageId': ''})
            return result
    monkeypatch.setattr(sys.modules[__name__], 'ConsoleLogClient', GetterClient)
    monkeypatch.setenv('WWISE_CONSOLE_LOG_GETTER_WORKFLOW', 'owned-get-clear-v1')
    client, connections, receipt, final, error, records = test_console_log_native_node_persists_final_outcome_and_partial_failure(
        tmp_path, monkeypatch, '2025.1', 'matched', getter=True)
    observed = receipt['getter_workflow']
    assert sum(uri == ADD for uri, _, _ in client.calls) == 1
    assert sum(uri.endswith('log.clear') for uri, _, _ in client.calls) == (0 if fault == 'empty-getter' else 1)
    assert final['source']['hash_before'] == final['source']['hash_after']
    if fault == 'matched':
        assert error is None and final['invocation']['outcome'] == 'PASS'
        assert len(final['transactions']) == 2 and all(row['state'] == 'verified' for row in final['transactions'])
        assert observed['post_add']['truncated'] is False and observed['post_add']['items']
        assert observed['clear_prestate']['items'] and observed['post_clear']['items'] == []
        assert final['residual_state']['sandbox'] == 'deleted'
    else:
        assert error is not None and final['invocation']['outcome'] == 'FAIL'
        assert final['residual_state']['sandbox'] == 'quarantined'
        if fault == 'empty-getter': assert 'clear_transaction' not in receipt
        else: assert receipt['clear_transaction']['verify']['state'] == 'result_schema_checked'
