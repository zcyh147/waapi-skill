"""Input legality collectors reach the real durable writer; external Wwise is fake."""
from copy import deepcopy
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.destructive.support import exact_real_evidence, sandbox_fixture
from tests.unit.test_runtime_business_gateway import _RuntimeControlDraftClient, _env

PREFIX = 'ak.wwise.core.profiler.'
MODULE = 'tests/destructive/test_gateway_workflow_transaction_matrix.py::'
BUILDS = {'2021.1': (14, 8108), '2022.1': (19, 8584), '2023.1': (19, 8928),
    '2024.1': (13, 9056), '2025.1': (7, 9143)}


def _runtime(tmp_path, monkeypatch, version='2025.1', fault=None):
    monkeypatch.setenv('WWISE_LIVE', '1')
    monkeypatch.setenv('WWISE_DESTRUCTIVE', '1')
    workflow = importlib.import_module('tests.destructive.test_gateway_workflow_transaction_matrix')

    class Client(_RuntimeControlDraftClient):
        def __init__(self):
            super().__init__(tmp_path, version=version)
            self.calls, self.enable_count, self.user_time = [], 0, 1470
        def call(self, uri, args=None, options=None):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            if uri == PREFIX + 'enableProfilerData':
                self.enable_count += 1
                if self.enable_count == 2 and fault == 'enable-error':
                    raise RuntimeError('fake native interrupted enablement; outcome uncertain')
                return {}
            if uri == PREFIX + 'getCursorTime':
                return {'return': (1500 if fault != 'capture-unavailable' else -1)
                    if args['cursor'] == 'capture' else self.user_time}
            if uri == PREFIX + 'setCursorTime':
                if args['time'] < 0 and fault == 'cursor-native-error':
                    raise RuntimeError('fake native cursor execution lost; no retry')
                self.user_time = 1480 if args['time'] < 0 else args['time']
                if args['time'] < 0 and fault == 'signed-unavailable':
                    self.user_time = -1
                if args['time'] < 0 and fault == 'signed-changed':
                    self.user_time = 1490
                    return {'return': 1480}
                if args['time'] < 0 and fault == 'signed-below-domain':
                    self.user_time = -2
                return {'return': self.user_time}
            if uri in (PREFIX + 'startCapture', PREFIX + 'stopCapture'):
                if uri.endswith('stopCapture') and fault == 'stop-error':
                    raise RuntimeError('fake native stop lost; no retry')
                return {'return': 1500}
            if uri == 'ak.wwise.core.object.get' and version == '2021.1' and (
                    args.get('from', {}).get('id') == ['{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}']
                    or 'AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA' in args.get('waql', '')):
                return {'return': [{'id': '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}', 'name': 'SampleProject',
                    'type': 'Project', 'path': '\\', 'filePath': str(self.project_file)}]}
            result = super().call(uri, args, options)
            if uri == 'ak.wwise.core.getInfo':
                result['isCommandLine'] = True
                minor, build = BUILDS[version]
                result['version'].update(minor=minor, build=build, displayName=f'v{version}.{minor}.{build}')
            if uri == 'ak.wwise.core.getProjectInfo':
                result['isDirty'] = False
            return result
    client = Client()
    execute = workflow.waapi_gateway.execute_gateway
    monkeypatch.setattr(workflow.waapi_gateway, 'execute_gateway',
        lambda argv, **kwargs: execute(argv, **kwargs, client_factory=lambda _: client))
    source = tmp_path / 'source'; source.mkdir()
    project = source / 'SampleProject.wproj'; project.write_text('immutable input probe source')
    proof = sandbox_fixture.hash_project(source)
    metadata = sandbox_fixture.SandboxMetadata(str(project), str(source), str(client.project_root),
        str(client.project_file), version, 0, proof, sandbox_fixture.hash_project(client.project_root),
        project.stat().st_mtime, process_cleanup_result='cleaned', process_cleanup_details={'residual_processes': []})
    sandbox = sandbox_fixture.SandboxProject(project, source, tmp_path, client.project_root, client.project_file, metadata)
    lock = sandbox_fixture.LiveSandboxLock(tmp_path / 'locks'); lock.__enter__()
    env = _env(tmp_path, version=version)
    env['WWISE_EVIDENCE_DIR'] = str(tmp_path / 'native')
    endpoint = SimpleNamespace(host='127.0.0.1', port=31337, waapi_url='ws://127.0.0.1:31337/waapi')
    runtime = workflow._WorkflowSandboxRuntime(version, sandbox, endpoint, tmp_path / 'state', env,
        workflow.exact_git_candidate(workflow.REPO_ROOT), [])
    return workflow, runtime, client, lock, proof


def _finish(context, tmp_path, monkeypatch, nodes):
    workflow, runtime, client, lock, proof = context
    items = [SimpleNamespace(path=workflow.__file__, nodeid=MODULE + node,
        _waapi_phase_reports={'setup': 'passed', 'call': 'failed' if error else 'passed'}) for node, error in nodes]
    output = tmp_path / 'category.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(output))
    monkeypatch.setattr(sandbox_fixture, 'KEEP_ON_FAILURE_ROOT', tmp_path / 'retained')
    source = runtime.sandbox.source_root
    assert sandbox_fixture.hash_project(source) == proof
    final_error = exact_real_evidence.finalize_exact_real_evidence(repo_root=workflow.REPO_ROOT,
        candidate=runtime.candidate, version=runtime.version,
        request=SimpleNamespace(session=SimpleNamespace(items=items)), module_file=Path(workflow.__file__),
        started_at_unix_ns=1, active_error=next((e for _, e in nodes if e), None), deferred_error=None,
        sandbox=runtime.sandbox, lock=lock, state_dir=runtime.state_dir,
        host={'is_command_line': True, 'version': runtime.version}, categories=runtime.category_results,
        source={'hash_before': proof.digest, 'hash_after': sandbox_fixture.hash_project(source).digest})
    assert final_error is None
    return [json.loads(line) for line in output.read_text().splitlines()]


@pytest.mark.parametrize('version', tuple(BUILDS))
def test_enable_input_observations_reach_persisted_final_record(tmp_path, monkeypatch, version):
    context = _runtime(tmp_path, monkeypatch, version)
    workflow, runtime, client, _, _ = context
    node = 'test_profiler_enablement_input_shape_native_observations'
    getattr(workflow, node)(runtime)
    records = _finish(context, tmp_path, monkeypatch, [(node, None)])
    assert [row['invocation']['outcome'] for row in records] == ['PENDING', 'PASS']
    final = records[-1]
    category, = final['categories']
    assert category['status'] == 'blocked' and category['observation_task_status'] == 'PASS'
    assert category['business_effect_verified'] is False
    report = json.loads(Path(category['observation_path']).read_text())
    assert report['complete'] is True and report['version'] == version
    assert report['host']['isCommandLine'] is True and report['host']['version']['build'] == BUILDS[version][1]
    assert [case['native_outcome'] for case in report['cases']] == ['accepted'] * 3
    assert [args for uri, args, _ in client.calls if uri == PREFIX + 'enableProfilerData'] == [
        {'dataTypes': []}, {'dataTypes': [{'dataType': 'voices', 'enable': True}, {'dataType': 'voices', 'enable': True}]},
        {'dataTypes': [{'dataType': 'voices', 'enable': True}, {'dataType': 'voices', 'enable': False}]}]
    assert len(final['transactions']) == 3
    assert {row['state'] for row in final['transactions']} == {'result_schema_checked'}
    assert final['residual_state']['sandbox'] == 'deleted'
    assert not runtime.sandbox.sandbox_path.exists()
    assert all(case['verify']['verification']['business_state_verified'] is False for case in report['cases'])
    assert all(case['verify']['agent_result'] == next(call['payload']['agent_result'] for call in report['calls']
        if call['argv'] == ['verify', case['transaction_id']]) for case in report['cases'])


def test_enable_input_partial_failure_retains_earlier_observations(tmp_path, monkeypatch):
    context = _runtime(tmp_path, monkeypatch, fault='enable-error')
    workflow, runtime, client, _, _ = context
    node = 'test_profiler_enablement_input_shape_native_observations'
    with pytest.raises(AssertionError) as failure:
        getattr(workflow, node)(runtime)
    records = _finish(context, tmp_path, monkeypatch, [(node, failure.value)])
    assert [row['invocation']['outcome'] for row in records] == ['FAIL']
    final = records[-1]
    category, = final['categories']
    report = json.loads(Path(category['observation_path']).read_text())
    assert category['status'] == 'FAIL' and category['observation_task_status'] == 'BLOCKED'
    assert report['complete'] is False
    assert [case['native_outcome'] for case in report['cases']] == ['accepted', 'indeterminate', 'not_attempted']
    assert report['cases'][1]['execute']['automatic_retry'] is False
    assert 'verify' not in report['cases'][1] and 'transaction_id' not in report['cases'][2]
    assert len([uri for uri, _, _ in client.calls if uri == PREFIX + 'enableProfilerData']) == 2
    assert {row['state'] for row in final['transactions']} == {'result_schema_checked', 'indeterminate'}
    assert final['residual_state']['sandbox'] == 'quarantined'
    assert Path(final['residual_state']['quarantine_path']).is_dir()


def test_console_signed_cursor_observations_reach_persisted_final_record(tmp_path, monkeypatch):
    context = _runtime(tmp_path, monkeypatch)
    workflow, runtime, client, _, _ = context
    node = 'test_profiler_signed_cursor_input_native_observations'
    getattr(workflow, node)(runtime)
    records = _finish(context, tmp_path, monkeypatch, [(node, None)])
    assert [row['invocation']['outcome'] for row in records] == ['PENDING', 'PASS']
    category, = records[-1]['categories']
    report = json.loads(Path(category['observation_path']).read_text())
    assert report['complete'] is True and report['capture_position']['available'] is True
    assert [case['native_outcome'] for case in report['cases']] == ['accepted', 'accepted']
    assert [args['time'] for uri, args, _ in client.calls if uri == PREFIX + 'setCursorTime'] == [-1, -2, 1470]
    assert report['cleanup']['cursor_restored_to_observed_time_ms'] == 1470
    assert report['cleanup']['complete'] is True
    assert category['status'] == 'blocked' and category['business_effect_verified'] is False
    for case in report['cases']:
        scope = case['verify']['verification']['verification_scope']['cursor_observation']
        assert scope['outcome'] == 'matched' and scope['returned_time_ms'] == scope['observed_time_ms'] == 1480
    assert sum(uri == PREFIX + 'startCapture' for uri, _, _ in client.calls) == 1
    assert sum(uri == PREFIX + 'stopCapture' for uri, _, _ in client.calls) == 1
    assert not any(uri.startswith(('ak.wwise.core.transport.', 'ak.wwise.core.log.')) or uri.endswith(('getMeters', 'saveCapture'))
        for uri, _, _ in client.calls)


def test_console_unavailable_capture_retains_prerequisite_and_skips_signed_dispatch(tmp_path, monkeypatch):
    context = _runtime(tmp_path, monkeypatch, fault='capture-unavailable')
    workflow, runtime, client, _, _ = context
    node = 'test_profiler_signed_cursor_input_native_observations'
    with pytest.raises(AssertionError, match='captured cursor unavailable') as failure:
        getattr(workflow, node)(runtime)
    final, = _finish(context, tmp_path, monkeypatch, [(node, failure.value)])
    category, = final['categories']
    report = json.loads(Path(category['observation_path']).read_text())
    assert category['status'] == 'FAIL' and report['complete'] is False
    assert report['capture_read_attempts'] == 2 and report['capture_position'] == {
        'profiler_cursor': 'capture-latest', 'available': False, 'position_ms': None}
    capture_reads = [row for row in report['calls'] if '--profiler-cursor' in row['argv']]
    assert len(capture_reads) == 2 and all(0 < float(row['argv'][1]) <= 2 for row in capture_reads)
    assert [case['native_outcome'] for case in report['cases']] == ['not_attempted'] * 2
    assert not any(uri == PREFIX + 'setCursorTime' for uri, _, _ in client.calls)
    assert sum(uri == PREFIX + 'stopCapture' for uri, _, _ in client.calls) == 1
    assert report['cleanup']['capture_stop_acknowledged'] is True
    assert len(final['transactions']) == 2 and Path(final['residual_state']['quarantine_path']).is_dir()


@pytest.mark.parametrize('fault', ('signed-unavailable', 'signed-changed', 'signed-below-domain', 'cursor-native-error', 'stop-error'))
def test_signed_cursor_unavailable_or_changed_readback_retains_actual_outcome(tmp_path, monkeypatch, fault):
    context = _runtime(tmp_path, monkeypatch, fault=fault)
    workflow, runtime, client, _, _ = context
    node = 'test_profiler_signed_cursor_input_native_observations'
    error = None
    try:
        getattr(workflow, node)(runtime)
    except AssertionError as exc:
        error = exc
    final = _finish(context, tmp_path, monkeypatch, [(node, error)])[-1]
    category, = final['categories']
    report = json.loads(Path(category['observation_path']).read_text())
    targets = [args['time'] for uri, args, _ in client.calls if uri == PREFIX + 'setCursorTime']
    assert sum(uri == PREFIX + 'stopCapture' for uri, _, _ in client.calls) == 1
    assert category['business_effect_verified'] is False
    if fault == 'signed-unavailable':
        assert error is None and final['invocation']['outcome'] == 'PASS'
        assert targets == [-1, -2, 1470]
        assert report['complete'] is True and category['status'] == 'blocked'
        assert all(case['cursor_observation']['outcome'] == 'unavailable' for case in report['cases'])
        assert all(case['verify']['verification']['business_state_verified'] is False for case in report['cases'])
    else:
        assert error is not None and final['invocation']['outcome'] == 'FAIL'
        assert category['status'] == 'FAIL' and report['complete'] is False
        assert Path(final['residual_state']['quarantine_path']).is_dir()
        assert report['cases'][1]['native_outcome'] == 'not_attempted'
        if fault == 'stop-error':
            assert targets == [] and report['cleanup']['complete'] is False
            assert report['cleanup']['stop_capture']['execute']['automatic_retry'] is False
        elif fault == 'cursor-native-error':
            assert targets == [-1] and report['cleanup']['complete'] is False
            assert report['cases'][0]['native_outcome'] == 'indeterminate'
            assert report['cases'][0]['execute']['automatic_retry'] is False
            assert 'cursor_restoration' not in report['cleanup']
        else:
            assert targets == [-1, 1470] and report['cases'][0]['native_outcome'] == 'accepted'
            verify = report['cases'][0]['verify']
            assert verify['state'] == 'verification_failed'
            assert verify['verification']['business_state_verified'] is False
            assert report['cleanup']['cursor_restored_to_observed_time_ms'] == 1470
            if fault == 'signed-changed':
                assert verify['verification']['verification_scope']['cursor_observation']['outcome'] == 'changed'


def test_shared_console_log_success_and_enable_failure_keep_independent_final_outcomes(tmp_path, monkeypatch):
    from tests.unit.test_console_log_observer_gateway import ConsoleLogClient, ADD
    context = _runtime(tmp_path, monkeypatch, fault='enable-error')
    workflow, runtime, client, _, _ = context
    log_root = tmp_path / 'external-log'; log_root.mkdir()
    log = ConsoleLogClient(log_root)
    native = client.call
    def call(uri, args=None, options=None):
        if uri.startswith('ak.wwise.core.log.'):
            return log.call(uri, args, options)
        assert log.callback is None, 'Profiler calls must begin after log observer cleanup'
        return native(uri, args, options)
    client.call, client.subscribe = call, log.subscribe
    log_node, enable_node = 'test_console_log_addition_observer', 'test_profiler_enablement_input_shape_native_observations'
    getattr(workflow, log_node)(runtime)
    assert log.order == ['subscribed', 'add', 'unsubscribed'] and log.callback is None
    with pytest.raises(AssertionError) as failure:
        getattr(workflow, enable_node)(runtime)
    final, = _finish(context, tmp_path, monkeypatch, [(log_node, None), (enable_node, failure.value)])
    assert final['invocation']['outcome'] == 'FAIL'
    assert final['invocation']['node_outcomes'] == [
        {'nodeid': MODULE + log_node, 'outcome': 'PASS'}, {'nodeid': MODULE + enable_node, 'outcome': 'FAIL'}]
    categories = {row['category']: row for row in final['categories']}
    assert categories['console-log-addition-observer']['status'] == 'PASS'
    assert categories['profiler-enablement-input-shapes']['status'] == 'FAIL'
    log_report = json.loads(Path(categories['console-log-addition-observer']['receipt_path']).read_text())
    enable_report = json.loads(Path(categories['profiler-enablement-input-shapes']['observation_path']).read_text())
    assert log_report['transaction']['verify']['verification']['business_state_verified'] is True
    assert [case['native_outcome'] for case in enable_report['cases']] == ['accepted', 'indeterminate', 'not_attempted']
    assert len({row['transaction_id'] for row in final['transactions']}) == 3
    assert sum(uri == ADD for uri, _, _ in log.calls) == 1
    assert Path(final['residual_state']['quarantine_path']).is_dir()
