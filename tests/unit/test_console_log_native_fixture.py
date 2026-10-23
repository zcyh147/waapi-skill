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
def test_console_log_native_node_persists_final_outcome_and_partial_failure(tmp_path, monkeypatch, version, scenario):
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
    execute = workflow.waapi_gateway.execute_gateway
    monkeypatch.setattr(workflow.waapi_gateway, 'execute_gateway',
        lambda argv, **kwargs: execute(argv, **kwargs, client_factory=lambda _: client))
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
    assert client.order == ['subscribed', 'add', 'unsubscribed']
    assert sum(uri == ADD for uri, _, _ in client.calls) == 1
    assert not any(uri.endswith('log.clear') for uri, _, _ in client.calls)
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
        assert category['status'] == 'FAIL' and transaction['state'] == 'indeterminate'
        assert final['residual_state']['sandbox'] == 'quarantined'
        assert Path(final['residual_state']['quarantine_path']).is_dir()
        assert receipt['transaction']['execute']['automatic_retry'] is False
        assert receipt['transaction']['execute']['dispatch_result']['log_item_observation']['subscribed'] is True
        assert 'verify' not in receipt['transaction']
