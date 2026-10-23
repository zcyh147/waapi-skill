"""Shared Authoring nodes receive credit only after the owned batch finishes."""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.destructive.support.authoring_batch import AuthoringBatchAdapter


def test_authoring_batch_rejects_environment_only_ownership(tmp_path, monkeypatch):
    monkeypatch.setenv('WWISE_AUTHORING_SANDBOX_PROJECT', str(tmp_path / 'claimed.wproj'))
    with pytest.raises(ValueError, match='active ScenarioLifecycle'):
        AuthoringBatchAdapter(owner=None, repo_root=tmp_path, selected_nodeids=['node'])


@pytest.fixture
def owned_authoring(tmp_path, monkeypatch, request):
    from types import SimpleNamespace
    from tests.destructive.support import authoring_batch
    monkeypatch.setattr(authoring_batch, "candidate_source_context", lambda _: {"candidate": "a" * 40, "sources": {"fake-code": "b" * 64}})
    from tests.semantic.support.codex_scenario_lifecycle_v3 import ScenarioLifecycle, ScenarioRuntime
    from tests.destructive.support.sandbox_fixture import SandboxMetadata, SandboxProject, hash_project
    from wwise_waapi.headless import HeadlessLifecycle
    version = getattr(request, 'param', '2025.1')
    build = {'2021.1': (2021, 1, 14, 8108), '2022.1': (2022, 1, 19, 8584),
        '2023.1': (2023, 1, 19, 8928), '2025.1': (2025, 1, 7, 9143)}[version]
    root = tmp_path / 'batch'
    import os
    user_keys = ('USERPROFILE', 'APPDATA', 'LOCALAPPDATA') if os.name == 'nt' else ('HOME',)
    isolated = {key: str(root / 'owned' / key.lower()) for key in user_keys}
    owner = ScenarioLifecycle(scenario_id='owned-authoring', version=version, scenario_root=root,
        live_environment={}, launch_environment_overrides=isolated, lock_root=tmp_path / 'lock')
    source = tmp_path / 'source'
    source.mkdir()
    source_project = source / 'SampleProject.wproj'
    source_project.write_text('<WwiseDocument/>')
    owned = root / 'owned'
    sandbox_path = owned / 'sandbox-root/case'
    sandbox_path.mkdir(parents=True)
    project = sandbox_path / 'SampleProject.wproj'
    project.write_bytes(source_project.read_bytes())
    for path in isolated.values():
        Path(path).mkdir(parents=True)
    proof = hash_project(source, preferred_strategy='full')
    metadata = SandboxMetadata(source_path=str(source_project), source_root=str(source),
        sandbox_path=str(sandbox_path), sandbox_project_path=str(project), wwise_version=version,
        copy_duration_seconds=0, source_hash=proof, sandbox_hash=proof,
        source_mtime_before=source_project.stat().st_mtime, identity_verified=True,
        launch_project_path=str(project), process_pid=1234, selected_port=31337)
    sandbox = SandboxProject(source_project=source_project, source_root=source,
        sandbox_root=owned / 'sandbox-root', sandbox_path=sandbox_path, sandbox_project=project, metadata=metadata)
    info = {'displayName': 'Wwise', 'isCommandLine': False, 'processId': 1234, 'sessionId': 'owned-session',
        'version': dict(zip(('year', 'major', 'minor', 'build'), build))}
    process = HeadlessLifecycle(console_path=tmp_path / 'Wwise.exe', project_path=project, port=31337)
    process.process = SimpleNamespace(pid=1234, poll=lambda: None)
    process.command = ['Wwise.exe', str(project)]
    process.launch_cwd = sandbox.sandbox_root
    process.ready_result = info
    sandbox.wine_prefix_path.mkdir()
    process.launch_env = {'WINEPREFIX': str(sandbox.wine_prefix_path)}
    evidence = root / 'evidence'
    evidence.mkdir()
    owner.runtime = ScenarioRuntime(scenario_id=owner.scenario_id, version=owner.version,
        scenario_root=root, evidence_root=evidence, owned_root=owned, asset_root=owned / 'assets',
        io_root=owned / 'io', sandbox=sandbox, lifecycle=process, runner_environment=isolated,
        source_hash_before=proof, source_mtime_before_ns=source_project.stat().st_mtime_ns)
    owner.lock.__enter__()
    owner._lock_acquired = True
    try:
        yield owner
    finally:
        if owner._lock_acquired:
            owner.lock.__exit__(None, None, None)
            owner._lock_acquired = False


@pytest.mark.parametrize('owned_authoring', ['2021.1', '2022.1', '2023.1', '2025.1'], indirect=True)
def test_authoring_batch_rejects_console_context_before_any_node(owned_authoring, tmp_path):
    owned_authoring.runtime.lifecycle.ready_result['isCommandLine'] = True
    with pytest.raises(ValueError, match='Authoring'):
        AuthoringBatchAdapter(owner=owned_authoring, repo_root=tmp_path, selected_nodeids=['node'])


@pytest.mark.parametrize('owned_authoring', ['2021.1', '2022.1', '2023.1', '2025.1'], indirect=True)
@pytest.mark.parametrize('damage', ['build', 'source-project', 'metadata', 'port', 'runtime-version', 'source-content', 'released-lock'])
def test_authoring_batch_rejects_mismatched_owned_context(owned_authoring, tmp_path, damage):
    from dataclasses import replace
    runtime = owned_authoring.runtime
    if damage == 'build':
        runtime.lifecycle.ready_result['version']['build'] = 9000
    elif damage == 'source-project':
        runtime.sandbox.sandbox_project = runtime.sandbox.source_project
    elif damage == 'metadata':
        runtime.sandbox.metadata.launch_project_path = str(runtime.sandbox.source_project)
    elif damage == 'port':
        runtime.sandbox.metadata.selected_port += 1
    elif damage == 'runtime-version':
        owned_authoring.runtime = replace(runtime, version='2024.1')
    elif damage == 'source-content':
        runtime.sandbox.source_project.write_text('source drift')
    else:
        owned_authoring.lock.__exit__(None, None, None)
        owned_authoring._lock_acquired = False
    with pytest.raises(ValueError, match='ownership|build|source|context|active ScenarioLifecycle'):
        AuthoringBatchAdapter(owner=owned_authoring, repo_root=tmp_path, selected_nodeids=['node'])


def _install_public_gateway(monkeypatch, owner, *, damage=None):
    from copy import deepcopy
    from tests.destructive.support import authoring_batch
    calls = []
    def factory(*, skill_source, runtime, version, receipts):
        import json
        evidence = Path(runtime.runner_environment['WWISE_EVIDENCE_DIR'])
        evidence.mkdir(parents=True)
        def call(argv, **kwargs):
            calls.append(list(argv))
            payload = {'ok': True}
            if argv == ['status']:
                info = deepcopy(owner.runtime.lifecycle.ready_result)
                project = str(owner.runtime.sandbox.sandbox_project)
                host, port = runtime.host, runtime.port
                if damage == 'build':
                    info['version']['build'] = 9000
                elif damage == 'session':
                    info['sessionId'] = 'unowned-session'
                elif damage == 'project':
                    project = str(owner.runtime.sandbox.source_project)
                elif damage == 'endpoint':
                    port += 1
                elif damage == 'console':
                    info['isCommandLine'] = True
                payload.update(wwise=info, project={'path': project, 'id': '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}'},
                    endpoint={'host': host, 'port': port, 'url': f'ws://{host}:{port}/waapi'})
            receipts.append({'argv': list(argv), 'exit_code': 0, 'payload': payload})
            (evidence / f'{len(receipts)}-fake-dispatch.json').write_text(json.dumps({'argv': list(argv), 'result': payload}))
            return payload
        return call
    monkeypatch.setattr(authoring_batch, 'fixture_gateway', factory)
    return calls


def test_authoring_node_attaches_through_public_status_and_retains_its_own_receipts(owned_authoring, tmp_path, monkeypatch):
    calls = _install_public_gateway(monkeypatch, owned_authoring)
    batch = AuthoringBatchAdapter(owner=owned_authoring, repo_root=tmp_path, selected_nodeids=['node-a', 'node-b'])
    node = batch.node_gateway('node-a')
    assert calls[0][0] == 'config-set'
    assert calls[1] == ['status']
    node(['layout-read', 'current'])
    assert [row['argv'] for row in batch.receipts['node-a']] == calls
    assert 'node-b' not in batch.receipts


@pytest.mark.parametrize('damage', ['build', 'session', 'project', 'endpoint', 'console'])
def test_authoring_node_rejects_live_ownership_drift_before_layout_call(owned_authoring, tmp_path, monkeypatch, damage):
    calls = _install_public_gateway(monkeypatch, owned_authoring, damage=damage)
    batch = AuthoringBatchAdapter(owner=owned_authoring, repo_root=tmp_path, selected_nodeids=['node'])
    with pytest.raises(ValueError, match='live Authoring ownership'):
        batch.node_gateway('node')
    assert [argv[0] for argv in calls] == ['config-set', 'status']


@pytest.mark.parametrize('damage', ['missing-private-user-state', 'unbound-private-user-state'])
def test_authoring_batch_rejects_unisolated_authoring_preferences(owned_authoring, tmp_path, damage):
    from dataclasses import replace
    if damage == 'missing-private-user-state':
        owned_authoring.launch_environment_overrides.clear()
    else:
        owned_authoring.runtime = replace(owned_authoring.runtime, runner_environment={})
    with pytest.raises(ValueError, match='isolated user state'):
        AuthoringBatchAdapter(owner=owned_authoring, repo_root=tmp_path, selected_nodeids=['node'])


def test_authoring_batch_stays_prepared_until_last_teardown_report(owned_authoring, tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from tests.destructive.support import authoring_batch
    monkeypatch.setattr(authoring_batch, 'exact_git_candidate', lambda _: 'a' * 40)
    target = tmp_path / 'category.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(target))
    _install_public_gateway(monkeypatch, owned_authoring)
    batch = AuthoringBatchAdapter(owner=owned_authoring, repo_root=tmp_path, selected_nodeids=['last-node'])
    batch.node_gateway('last-node')
    item = SimpleNamespace(nodeid='last-node', _waapi_phase_reports={'setup': 'passed', 'call': 'passed'})
    result = batch.finalize([item], terminal=False)
    assert result['outcome'] == 'PENDING'
    assert owned_authoring._finished is False
    assert owned_authoring.runtime.sandbox.sandbox_project.exists()
    record = json.loads(target.read_text())
    assert record['invocation']['phase'] == 'prepared'
    assert record['invocation']['outcome'] == 'PENDING'
    assert record['invocation']['node_outcomes'] == [{'nodeid': 'last-node', 'outcome': 'BLOCKED'}]
    assert record['residual_state']['sandbox'] == 'retained'


@pytest.mark.parametrize('owned_authoring', ['2021.1', '2022.1', '2023.1', '2025.1'], indirect=True)
def test_shared_owner_stops_prepared_then_releases_after_last_teardown(owned_authoring, tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from tests.destructive.support import authoring_batch
    from tests.semantic.support import codex_scenario_lifecycle_v3 as lifecycle
    from wwise_waapi.headless import CleanupReport, HeadlessLifecycle
    calls = []
    def shutdown(process, sandbox, **kwargs):
        calls.append('shutdown')
        process.process = None
        process.cleanup_report = CleanupReport(launch_pid=1234, wine_prefix=None, process_exited=True)
        sandbox.metadata.process_cleanup_result = 'cleaned'
        sandbox.metadata.process_cleanup_details = {'residual_processes': []}
    monkeypatch.setattr(lifecycle, 'shutdown_sandboxed_wwise', shutdown)
    monkeypatch.setattr(authoring_batch, 'wait_for_port_release', lambda *_: None)
    monkeypatch.setattr(HeadlessLifecycle, '_process_rows', lambda *_, **__: [(12345, 'fake pytest process')])
    target = tmp_path / 'category.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(target))
    _install_public_gateway(monkeypatch, owned_authoring)
    batch = AuthoringBatchAdapter(owner=owned_authoring, repo_root=tmp_path, selected_nodeids=['last-node'])
    batch.node_gateway('last-node')
    item = SimpleNamespace(nodeid='last-node', _waapi_phase_reports={'setup': 'passed', 'call': 'passed'})
    batch.prepare_stop([item])
    assert calls == ['shutdown']
    assert owned_authoring._finished is True
    assert owned_authoring.runtime.owned_root.exists()
    assert all(row['invocation']['outcome'] == 'PENDING' for row in map(json.loads, target.read_text().splitlines()))
    item._waapi_phase_reports['teardown'] = 'passed'
    result = batch.finalize([item], terminal=True)
    assert result['outcome'] == 'PASS'
    assert calls == ['shutdown']
    assert not owned_authoring.runtime.owned_root.exists()
    rows = list(map(json.loads, target.read_text().splitlines()))
    assert rows[-1]['invocation']['phase'] == 'final'
    assert rows[-1]['invocation']['node_outcomes'] == [{'nodeid': 'last-node', 'outcome': 'PASS'}]
    assert rows[-1]['residual_state']['sandbox'] == 'deleted'
    artifact = rows[-1]['categories'][0]['observation_artifact']
    original = json.loads(Path(artifact['path']).read_text())
    assert original['nodeid'] == 'last-node'
    assert original['receipts'][1]['argv'] == ['status']


def _batch_ready_for_final_reports(owner, tmp_path, monkeypatch, *, nodeids=('last-node',), prepare=True):
    from types import SimpleNamespace
    from tests.destructive.support import authoring_batch
    from tests.semantic.support import codex_scenario_lifecycle_v3 as lifecycle
    from wwise_waapi.headless import CleanupReport, HeadlessLifecycle
    def shutdown(process, sandbox, **kwargs):
        process.process = None
        process.cleanup_report = CleanupReport(launch_pid=1234, wine_prefix=str(process._owned_wine_prefix()), process_exited=True)
        sandbox.metadata.process_cleanup_result = 'cleaned'
        sandbox.metadata.process_cleanup_details = {'residual_processes': []}
    monkeypatch.setattr(lifecycle, 'shutdown_sandboxed_wwise', shutdown)
    monkeypatch.setattr(authoring_batch, 'wait_for_port_release', lambda *_: None)
    monkeypatch.setattr(HeadlessLifecycle, '_process_rows', lambda *_, **__: [(12345, 'fake pytest process')])
    target = tmp_path / 'category.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(target))
    _install_public_gateway(monkeypatch, owner)
    batch = AuthoringBatchAdapter(owner=owner, repo_root=tmp_path, selected_nodeids=nodeids)
    for nodeid in nodeids:
        batch.node_gateway(nodeid)
    items = [SimpleNamespace(nodeid=nodeid, _waapi_phase_reports={'setup': 'passed', 'call': 'passed'}) for nodeid in nodeids]
    if prepare:
        batch.prepare_stop(items)
    return batch, items[0] if len(items) == 1 else items, target


@pytest.mark.parametrize('damage', ['teardown-fail', 'teardown-absent', 'source-content', 'source-mtime', 'resource', 'code', 'receipt', 'lock'])
def test_late_batch_failures_cannot_release_or_leave_a_pass_record(owned_authoring, tmp_path, monkeypatch, damage):
    import json
    import os
    from tests.destructive.support import authoring_batch
    from wwise_waapi.headless import HeadlessLifecycle
    batch, item, target = _batch_ready_for_final_reports(owned_authoring, tmp_path, monkeypatch)
    item._waapi_phase_reports['teardown'] = 'passed'
    if damage == 'teardown-fail':
        item._waapi_phase_reports['teardown'] = 'failed'
    elif damage == 'teardown-absent':
        item._waapi_phase_reports.pop('teardown')
    elif damage == 'source-content':
        owned_authoring.runtime.sandbox.source_project.write_text('late source mutation')
    elif damage == 'source-mtime':
        source = owned_authoring.runtime.sandbox.source_project
        os.utime(source, ns=(source.stat().st_atime_ns, source.stat().st_mtime_ns + 1000000))
    elif damage == 'resource':
        prefix = owned_authoring.runtime.lifecycle._owned_wine_prefix()
        monkeypatch.setattr(HeadlessLifecycle, '_process_rows', lambda *_, **__: [(98765, f'WINEPREFIX={prefix} Wwise.exe')])
    elif damage == 'code':
        monkeypatch.setattr(authoring_batch, 'candidate_source_context', lambda _: {'candidate': 'a' * 40, 'sources': {'fake-code': 'c' * 64}})
    elif damage == 'receipt':
        batch.receipts['last-node'].append({'argv': ['layout-read', 'current'], 'payload': {'ok': True}})
    else:
        owned_authoring.lock.__exit__(None, None, None)
    result = batch.finalize([item], terminal=True)
    assert result['outcome'] in {'FAIL', 'BLOCKED'}
    assert owned_authoring.runtime.owned_root.exists()
    rows = list(map(json.loads, target.read_text().splitlines()))
    assert rows[-1]['invocation']['phase'] == 'final'
    assert all(row['invocation']['outcome'] != 'PASS' for row in rows)
    assert all(category['status'] != 'PASS' for row in rows for category in row['categories'])
    with pytest.raises(Exception, match='prepared'):
        owned_authoring.release_prepared_cleanup(post_teardown_check=lambda _: None)


@pytest.mark.parametrize('failure', ['none', 'resource', 'receipt-write'])
def test_sessionfinish_propagates_batch_failures_to_pytest_exit_status(owned_authoring, tmp_path, monkeypatch, failure):
    from types import SimpleNamespace
    from wwise_waapi.headless import HeadlessLifecycle
    batch, item, target = _batch_ready_for_final_reports(owned_authoring, tmp_path, monkeypatch)
    item._waapi_phase_reports['teardown'] = 'passed'
    if failure == 'resource':
        prefix = owned_authoring.runtime.lifecycle._owned_wine_prefix()
        monkeypatch.setattr(HeadlessLifecycle, '_process_rows', lambda *_, **__: [(98765, f'WINEPREFIX={prefix} Wwise.exe')])
    elif failure == 'receipt-write':
        target.rename(tmp_path / 'original-prepared-category.jsonl')
        target.mkdir()
    session = SimpleNamespace(items=[item], exitstatus=0)
    hook = batch.pytest_sessionfinish(session, exitstatus=0)
    next(hook)
    with pytest.raises(StopIteration):
        hook.send(SimpleNamespace(get_result=lambda: None))
    assert session.exitstatus == (0 if failure == 'none' else 1)
    if failure == 'receipt-write':
        assert (owned_authoring.runtime.evidence_root / 'authoring-batch-sessionfinish-error.json').exists()
        assert (tmp_path / 'original-prepared-category.jsonl').exists()


def test_batch_plugin_requires_the_exact_collected_nodes_and_records_every_report(owned_authoring, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from tests.destructive.support.authoring_batch import install_authoring_batch
    registered = []
    config = SimpleNamespace(pluginmanager=SimpleNamespace(register=lambda plugin, name: registered.append((plugin, name))))
    batch = install_authoring_batch(config, owner=owned_authoring, repo_root=tmp_path, selected_nodeids=['node'])
    assert config._waapi_authoring_batch is batch
    assert registered == [(batch, 'waapi-owned-authoring-batch')]
    item = SimpleNamespace(nodeid='node')
    hook = batch.pytest_collection_modifyitems([item])
    next(hook)
    with pytest.raises(StopIteration):
        hook.send(None)
    for phase in ('setup', 'call', 'teardown'):
        hook = batch.pytest_runtest_makereport(item, None)
        next(hook)
        with pytest.raises(StopIteration):
            hook.send(SimpleNamespace(get_result=lambda: SimpleNamespace(when=phase, outcome='passed')))
    assert item._waapi_phase_reports == {'setup': 'passed', 'call': 'passed', 'teardown': 'passed'}
    mismatch = batch.pytest_collection_modifyitems([item, SimpleNamespace(nodeid='unowned-node')])
    next(mismatch)
    with pytest.raises(pytest.UsageError, match='exact owned Authoring node selection'):
        mismatch.send(None)


def test_partial_multinode_publication_cannot_grant_either_node_acceptance(owned_authoring, tmp_path, monkeypatch):
    from hashlib import sha256
    import json
    from types import SimpleNamespace
    from tests.destructive.support import authoring_batch
    from tests.maintenance.branch_audit_completion import read_category_run
    batch, items, target = _batch_ready_for_final_reports(
        owned_authoring, tmp_path, monkeypatch, nodeids=('first-node', 'last-node'))
    for item in items:
        item._waapi_phase_reports['teardown'] = 'passed'
    original = authoring_batch.append_category_evidence
    def partial_publication(**kwargs):
        original(**kwargs)
        if kwargs['invocation']['outcome'] == 'PASS':
            raise OSError('disk failure after category write')
    monkeypatch.setattr(authoring_batch, 'append_category_evidence', partial_publication)
    session = SimpleNamespace(items=items, exitstatus=0)
    hook = batch.pytest_sessionfinish(session, exitstatus=0)
    next(hook)
    with pytest.raises(StopIteration):
        hook.send(SimpleNamespace(get_result=lambda: None))
    assert session.exitstatus != 0
    raw = target.read_bytes()
    rows = list(map(json.loads, raw.splitlines()))
    indices = [index for index, row in enumerate(rows) if row['invocation']['outcome'] == 'PASS']
    assert indices, 'The injected failure must retain the partially published original PASS'
    for node in ('first-node', 'last-node'):
        with pytest.raises(ValueError, match='batch finalization'):
            read_category_run({'artifact': str(target), 'sha256': sha256(raw).hexdigest(),
                               'record_index': indices[0], 'nodeid': node}, tmp_path)


@pytest.mark.parametrize('damage', ['none', 'seal-missing', 'original-receipt', 'native-artifact'])
def test_final_batch_seal_binds_every_nodes_original_observations(owned_authoring, tmp_path, monkeypatch, damage):
    from hashlib import sha256
    import json
    from tests.maintenance.branch_audit_completion import read_category_run
    batch, items, target = _batch_ready_for_final_reports(
        owned_authoring, tmp_path, monkeypatch, nodeids=('first-node', 'last-node'))
    for item in items:
        item._waapi_phase_reports['teardown'] = 'passed'
    assert batch.finalize(items)['outcome'] == 'PASS'
    seal = json.loads(batch.batch_seal_path.read_text())
    assert seal['resources']['cleanup_report']['process_exited'] is True
    assert seal['resources']['cleanup_report']['launch_pid'] == 1234
    assert seal['resources']['cleanup_report']['residual_processes'] == []
    assert seal['resources']['port'] == {'host': '127.0.0.1', 'port': 31337, 'released': True}
    raw = target.read_bytes()
    if damage == 'seal-missing':
        batch.batch_seal_path.rename(tmp_path / 'retained-original-batch-seal.json')
    elif damage == 'original-receipt':
        Path(batch.observation_artifacts['first-node']['path']).write_text('{}')
    elif damage == 'native-artifact':
        node = json.loads(Path(batch.observation_artifacts['first-node']['path']).read_text())
        artifact = node['artifacts']['native-evidence']
        (Path(artifact['path']) / artifact['files'][0]['path']).write_text('{}')
    for node in ('first-node', 'last-node'):
        descriptor = {'artifact': str(target), 'sha256': sha256(raw).hexdigest(),
                      'record_index': len(raw.splitlines()) - 1, 'nodeid': node}
        if damage == 'none':
            assert read_category_run(descriptor, tmp_path)['candidate'] == 'a' * 40
        else:
            with pytest.raises(ValueError, match='batch finalization'):
                read_category_run(descriptor, tmp_path)


@pytest.mark.parametrize('late_failure', [False, True])
def test_actual_pytest_waits_for_the_last_module_teardown_before_batch_credit(owned_authoring, tmp_path, monkeypatch, late_failure):
    import json
    filename = f'test_owned_node_{int(late_failure)}.py'
    nodeids = (filename + '::test_one', filename + '::test_two')
    batch, _, target = _batch_ready_for_final_reports(
        owned_authoring, tmp_path, monkeypatch, nodeids=nodeids, prepare=False)
    test_file = tmp_path / filename
    test_file.write_text('def test_one():\n    assert True\n\ndef test_two():\n    assert True\n')
    class StopOwner:
        @pytest.fixture(scope='module', autouse=True)
        def owned_host(self, request):
            yield
            batch.prepare_stop(request.session.items)
            last = request.session.items[-1]
            assert 'teardown' not in last._waapi_phase_reports
            assert all(row['invocation']['outcome'] == 'PENDING' for row in map(json.loads, target.read_text().splitlines()))
            assert owned_authoring._lock_acquired
            if late_failure:
                raise RuntimeError('last module teardown failed after host shutdown')
    monkeypatch.setenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
    code = pytest.main([str(test_file), '--rootdir', str(tmp_path), '-q', '-p', 'no:cacheprovider'], plugins=[batch, StopOwner()])
    assert int(code) == (1 if late_failure else 0)
    assert not owned_authoring._lock_acquired
    rows = list(map(json.loads, target.read_text().splitlines()))
    assert rows[-1]['invocation']['outcome'] == ('FAIL' if late_failure else 'PASS')
    assert batch.batch_seal_path.exists() is (not late_failure)


def test_batch_cannot_substitute_a_process_list_without_prefix_environment_proof(owned_authoring, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from wwise_waapi import headless
    original_snapshot = headless.HeadlessLifecycle._process_rows
    batch, item, _ = _batch_ready_for_final_reports(owned_authoring, tmp_path, monkeypatch)
    item._waapi_phase_reports['teardown'] = 'passed'
    monkeypatch.setattr(headless.HeadlessLifecycle, '_process_rows', original_snapshot)
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        if command == ['ps', 'eww', '-axo', 'pid=,command=']:
            return SimpleNamespace(returncode=1, stdout='')
        return SimpleNamespace(returncode=0, stdout='1234 ordinary process list without environments\n')
    monkeypatch.setattr(headless.subprocess, 'run', run)
    assert batch.finalize([item])['outcome'] == 'BLOCKED'
    assert commands == [['ps', 'eww', '-axo', 'pid=,command=']]
    assert owned_authoring.runtime.owned_root.exists()


@pytest.mark.parametrize('release', [True, False], ids=['busy-then-free', 'still-busy-at-deadline'])
def test_authoring_finalization_waits_boundedly_for_exact_port_release(owned_authoring, tmp_path, monkeypatch, release):
    import json
    from tests.destructive.support import authoring_batch, sandbox_fixture
    from wwise_waapi import headless
    batch, item, target = _batch_ready_for_final_reports(owned_authoring, tmp_path, monkeypatch)
    item._waapi_phase_reports['teardown'] = 'passed'
    # Keep the real existing wildcard-bind probe and release helper. Only the
    # OS socket/time boundaries are fake; final categories and owner are real.
    monkeypatch.setattr(authoring_batch, 'wait_for_port_release', sandbox_fixture.wait_for_port_release)
    clock, attempts = [0.0], []
    class Socket:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def bind(self, endpoint):
            attempts.append(endpoint)
            if not release or len(attempts) < 3:
                raise OSError('owned socket not yet bindable')
    monkeypatch.setattr(headless.socket, 'socket', lambda *_: Socket())
    monkeypatch.setattr(sandbox_fixture.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(sandbox_fixture.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    outcome = batch.finalize([item], terminal=True)
    records = [json.loads(line) for line in target.read_text().splitlines()]
    assert attempts and set(attempts) == {('0.0.0.0', 31337)}
    if release:
        assert outcome['outcome'] == 'PASS'
        assert len(attempts) == 3 and 0 < clock[0] < 15
        assert records[-1]['invocation']['outcome'] == 'PASS'
        assert records[-1]['residual_state']['sandbox'] == 'deleted'
    else:
        assert outcome['outcome'] == 'BLOCKED'
        assert 15 <= clock[0] <= 15.11
        assert all(row['invocation']['outcome'] != 'PASS' for row in records)
        assert owned_authoring.runtime.sandbox.sandbox_project.exists()
        assert (owned_authoring.runtime.evidence_root / 'lifecycle-release-error.json').exists()
    assert [row['argv'][0] for row in batch.receipts['last-node']] == ['config-set', 'status']


@pytest.mark.parametrize('owned_authoring', ['2021.1', '2022.1', '2023.1'], indirect=True)
def test_authoring_batch_admits_matching_older_catalog_context(owned_authoring, tmp_path, monkeypatch):
    calls = _install_public_gateway(monkeypatch, owned_authoring)
    batch = AuthoringBatchAdapter(owner=owned_authoring, repo_root=tmp_path, selected_nodeids=['future-owned-node'])
    batch.node_gateway('future-owned-node')
    assert calls[0] == ['config-set', '--wwise-version', owned_authoring.version, '--waapi-host', '127.0.0.1',
        '--waapi-port', '31337', '--project-modification-policy', 'ask_before_changes']
    assert calls[1] == ['status']
    assert owned_authoring._lock_acquired is True
