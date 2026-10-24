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
def test_console_log_native_node_persists_final_outcome_and_partial_failure(tmp_path, monkeypatch, version, scenario, peer=False):
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
    transaction, = final['transactions']
    assert transaction['transaction_id'] == receipt['transaction']['transaction_id']
    if peer:
        return client, connections, receipt, final, error, records
    assert client.order == ['subscribed', 'add', 'unsubscribed']
    assert sum(uri == ADD for uri, _, _ in client.calls) == 1
    assert not any(uri.endswith('log.clear') for uri, _, _ in client.calls)
    assert all('subscribe' not in vars(connection) for connection in connections)
    if scenario == 'matched':
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
        expected_state = 'result_schema_checked' if scenario == 'missing' else 'indeterminate'
        assert category['status'] == 'FAIL' and transaction['state'] == expected_state
        assert final['residual_state']['sandbox'] == 'quarantined'
        assert Path(final['residual_state']['quarantine_path']).is_dir()
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
    assert diagnostic['subscription_id'] == subscription_id and diagnostic['installed'] is True
    expected = 1 if scenario == 'matched' else 0
    assert diagnostic['decoded_events'] == diagnostic['callback_entries'] == expected
    assert diagnostic['restored'] is True
    assert len(json.dumps(diagnostic).encode()) <= 4096
    client, = clients
    assert 'onMessage' not in vars(client.session)
    assert 'subscribe' not in vars(client)
    assert client.handler._callback is client.original_callback


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


@pytest.mark.parametrize('scenario', ['both', 'independent-only', 'unrelated', 'neither', 'missing-ack', 'wrong-ack', 'cleanup', 'native-error'])
def test_independent_console_log_peer_waits_for_ack_and_retains_same_session_result(tmp_path, monkeypatch, scenario):
    monkeypatch.setenv('WWISE_LIVE', '1')
    monkeypatch.setenv('WWISE_DESTRUCTIVE', '1')
    import subprocess
    import socket
    import sys
    import waapi
    def forbidden(*args, **kwargs):
        pytest.fail('Console log fake chain forbids real client/socket construction', pytrace=False)
    monkeypatch.setattr(waapi, 'WaapiClient', forbidden)
    monkeypatch.setattr(socket, 'socket', forbidden)
    active, trace = [], []
    class PeerClient(ConsoleLogClient):
        def subscribe(self, uri, callback, options=None):
            assert uri == 'ak.wwise.core.log.itemAdded' and options in (None, {})
            if not active and scenario == 'missing-ack':
                raise RuntimeError('controlled independent subscription rejection')
            independent = not active
            active.append(callback)
            trace.append('subscribe-' + str(len(active)))
            def unsubscribe():
                active.remove(callback); trace.append('unsubscribe'); return not (independent and scenario == 'cleanup')
            return SimpleNamespace(unsubscribe=unsubscribe)
        def call(self, uri, args=None, options=None):
            if uri == ADD:
                self.calls.append((uri, deepcopy(args), deepcopy(options)))
                assert len(active) == 2 and trace[-2:] == ['execute-peer', 'subscribe-2']
                trace.append('add')
                payload = {'channel': args['channel'], 'item': {'message': args['message'],
                    'severity': args['severity'], 'time': 1720000000, 'messageId': 'Custom'}}
                if scenario == 'native-error':
                    raise RuntimeError('controlled native add uncertainty')
                if scenario in ('both', 'cleanup'):
                    for callback in list(active): callback(**deepcopy(payload))
                elif scenario == 'independent-only':
                    active[0](**deepcopy(payload))
                elif scenario == 'unrelated':
                    payload['item']['message'] = 'another writer'
                    active[0](**deepcopy(payload))
                return {}
            return super().call(uri, args, options)
    monkeypatch.setattr(sys.modules[__name__], 'ConsoleLogClient', PeerClient)
    monkeypatch.setenv('WWISE_CONSOLE_LOG_PEER_DIAGNOSTIC', 'independent-session-v1')
    from tests.semantic.support import codex_expansion_reconciliation as processes
    def producer(command, *, environment, timeout_seconds, cwd=None, text=True):
        workflow = importlib.import_module('tests.destructive.test_gateway_workflow_transaction_matrix')
        assert active and command[7] in ('execute', 'verify')
        trace.append(command[7] + '-peer')
        code, payload = workflow.waapi_gateway.execute_gateway(command[3:], env=environment)
        return subprocess.CompletedProcess(command, code, json.dumps(payload), '')
    monkeypatch.setattr(processes, 'run_owned_gateway', producer)
    workflow = importlib.import_module('tests.destructive.test_gateway_workflow_transaction_matrix')
    original_raw = workflow._WorkflowSandboxRuntime.raw_gateway
    def raw(self, argv, *, stream_sink=None):
        def sink(record):
            if record.get('record_type') == 'started' and scenario == 'wrong-ack':
                record = {**record, 'topic_contract_digest': 'wrong'}
            stream_sink(record)
        return original_raw(self, argv, stream_sink=sink if stream_sink else None)
    monkeypatch.setattr(workflow._WorkflowSandboxRuntime, 'raw_gateway', raw)
    if scenario in ('independent-only', 'unrelated', 'neither'):
        from wwise_waapi import runtime_log_observer
        ticks = iter((0, 6))
        monkeypatch.setattr(runtime_log_observer, 'monotonic', lambda: next(ticks, 6))
    client, connections, receipt, final, error, records = test_console_log_native_node_persists_final_outcome_and_partial_failure(
        tmp_path, monkeypatch, '2023.1', 'matched', peer=True)
    peer = receipt['peer_diagnostic']
    assert sum(uri == ADD for uri, _, _ in client.calls) == (0 if scenario in ('missing-ack', 'wrong-ack') else 1)
    assert not active and not any(uri.endswith('log.clear') for uri, _, _ in client.calls)
    assert final['source']['hash_before'] == final['source']['hash_after']
    assert len(json.dumps(receipt).encode('utf-8')) <= peer['limits']['receipt_bytes']
    if scenario == 'both':
        assert error is None and final['invocation']['outcome'] == 'PASS'
        assert peer['classification'] == 'both_sessions_matched'
        assert peer['ack_before_execute'] is True and peer['cleanup'] == 'unsubscribed'
        assert peer['same_session']['outcome'] == 'matched'
        event, = peer['events']
        assert event['matches_expected'] and event['event']['item']['message'] == receipt['expected']['message']
        assert trace == ['subscribe-1', 'execute-peer', 'subscribe-2', 'add', 'unsubscribe', 'verify-peer', 'unsubscribe']
        assert final['residual_state']['sandbox'] == 'deleted'
    else:
        assert error is not None and final['invocation']['outcome'] == 'FAIL'
        assert final['residual_state']['sandbox'] == 'quarantined'
        if scenario in ('missing-ack', 'wrong-ack'):
            assert peer['execute_attempted'] is False
            assert 'execute' not in receipt['transaction']
        elif scenario == 'native-error':
            assert peer['same_session']['outcome'] == 'native_call_failed'
            assert 'verify' not in receipt['transaction']
            assert receipt['transaction']['execute']['automatic_retry'] is False
        else:
            internal = receipt['transaction']['execute']['dispatch_result']['log_item_observation']
            assert peer['same_session'] == internal
            assert peer['classification'] == ('both_sessions_matched' if scenario == 'cleanup' else
                'independent_session_only' if scenario == 'independent-only' else 'neither_session_matched')
            if scenario == 'cleanup':
                assert peer['cleanup'] != 'unsubscribed' and not peer['complete']
            else:
                assert internal['outcome'] == 'timeout' and receipt['transaction']['verify']['state'] == 'result_schema_checked'
                assert peer['cleanup'] == 'unsubscribed' and peer['complete']
                assert peer['classification'] != 'both_sessions_matched'
                if scenario == 'independent-only':
                    assert peer['events'][0]['matches_expected'] is True
                elif scenario == 'unrelated':
                    assert peer['events'][0]['matches_expected'] is False
                else:
                    assert peer['events'] == []
