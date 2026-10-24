"""The existing collected-test owner installs the one private Demo context."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from tests.destructive.support import authoring_batch, integration_demo as demo
from tests.unit.test_integration_demo_observation import _installed
from tests.unit.test_authoring_batch_owner import _config, _fakes, NODE


def _configuration(tmp_path, monkeypatch):
    context = _installed(tmp_path)
    console = context.bundle / 'Contents/Tools/WwiseConsole.sh'
    console.parent.mkdir(parents=True, exist_ok=True)
    console.write_text('#!/bin/sh\n')
    console.chmod(0o755)
    project = context.bundle.parent / 'SDK/samples/IntegrationDemo/WwiseProject/IntegrationDemo.wproj'
    project.parent.mkdir(parents=True)
    project.write_text('<WwiseDocument/>')
    root = tmp_path / 'batch'
    path = tmp_path / 'demo-live-environment.json'
    selected = {'wwise_console': str(console), 'sample_project': str(project),
        'sandbox_root': str(root / 'owned/sandbox-root')}
    path.write_text(json.dumps({'versions': {'2025.1': selected}}))
    monkeypatch.setattr(demo, 'INSTALLED_BUNDLE', context.bundle, raising=False)
    monkeypatch.setattr(demo, 'INSTALLED_SCHEMAS', context.schemas, raising=False)
    monkeypatch.setenv('WWISE_TEST_CONFIG', str(path))
    for key, value in zip(('WWISE_CONSOLE', 'WWISE_SAMPLE_PROJECT_PATH', 'WWISE_SANDBOX_ROOT'), selected.values()):
        monkeypatch.setenv(key, value)
    return context, path, root


def test_existing_batch_factory_loads_named_demo_context_before_owner_start(tmp_path, monkeypatch):
    events = _fakes(monkeypatch, tmp_path)
    context, path, root = _configuration(tmp_path, monkeypatch)
    config = _config(tmp_path)
    config.args = [demo.NODEID]
    authoring_batch.configure_authoring_batch_owner(config, [SimpleNamespace(nodeid=demo.NODEID)], repo_root=tmp_path)
    assert [event[0] for event in events] == ['construct', 'start', 'install']
    options = events[0][1]
    assert options['developer_observation'] == context
    assert options['live_environment']['AK_AUTOMATION_MODE'] == '1'
    assert options['scenario_root'] == root
    assert options['live_environment']['WWISE_TEST_CONFIG'] == str(path)
    assert events[2][1]['selected_nodeids'] == (demo.NODEID,)


@pytest.mark.parametrize('failure', ['mixed', 'unknown', 'missing-config', 'wrong-source', 'schema-mismatch'])
def test_named_demo_invalid_selection_or_source_never_allocates_owner(tmp_path, monkeypatch, failure):
    events = _fakes(monkeypatch, tmp_path)
    context, path, root = _configuration(tmp_path, monkeypatch)
    config = _config(tmp_path)
    config.args = [demo.NODEID]
    if failure == 'mixed':
        config.args.append(NODE)
    elif failure == 'unknown':
        config.args.append('tests/destructive/unknown.py::test_unknown')
    elif failure == 'missing-config':
        monkeypatch.delenv('WWISE_TEST_CONFIG')
    elif failure == 'wrong-source':
        payload = json.loads(path.read_text())
        payload['versions']['2025.1']['sample_project'] = str(tmp_path / 'user.wproj')
        path.write_text(json.dumps(payload))
    else:
        (context.schemas / 'WAAPI/ak.wwise.core.profiler.getLoadedMedia.json').write_text('{}')
    with pytest.raises((ValueError, pytest.UsageError)):
        authoring_batch.configure_authoring_batch_owner(config,
            [SimpleNamespace(nodeid=node) for node in config.args], repo_root=tmp_path)
    assert not events and not root.exists()


def test_actual_collection_installs_demo_owner_dispatches_node_and_finalizes_once(tmp_path, monkeypatch):
    """Driver control only; the existing producer/Gateway full-chain test is separate."""
    from tests import conftest as root_conftest
    from tests.semantic.support import codex_scenario_lifecycle_v3 as lifecycle
    from tests.destructive.support import loaded_media_probe as probe
    from wwise_waapi.headless import HeadlessLifecycle, CleanupReport
    from tests.unit.test_runtime_business_gateway import _RuntimeControlDraftClient, _env, gateway
    from tests.support.gateway_config import set_gateway_config
    context, config_path, root = _configuration(tmp_path, monkeypatch)
    for key in ('WWISE_LIVE', 'WWISE_DESTRUCTIVE', 'WWISE_AUTHORING_LIVE'):
        monkeypatch.setenv(key, '1')
    monkeypatch.setenv('WWISE_VERSION', '2025.1')
    target = tmp_path / 'driver-final-categories.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(target))
    monkeypatch.setattr(authoring_batch, 'candidate_source_context', lambda _: {'candidate': 'a' * 40, 'sources': {'fake': 'b' * 64}})
    # Only the external Authoring launch/inspection/shutdown is substituted.
    events, launched = [], []
    def launch(sandbox, env, **kwargs):
        events.append('launch')
        assert kwargs['developer_observation'] == context and env['AK_AUTOMATION_MODE'] == '1'
        home = Path(env['HOME'])
        prefix = kwargs['wine_prefix_path']
        prefix.mkdir(parents=True)
        wine = context.bundle / 'Contents/SharedSupport/Wwise2019x64/bin/wine'
        managed = wine.parent.parent / 'support/Wwise2019x64'
        environment = {**env, 'WINEPREFIX': str(prefix), 'CX_BOTTLE': 'Wwise2019x64',
            'CX_BOTTLE_PATH': str(prefix.parent),
            'CX_MANAGED_BOTTLE_PATH': str(home / 'Library/Application Support/Wwise2019/BuiltinBottles')}
        bottle_env = {key: environment[key] for key in ('HOME', 'WINEPREFIX', 'CX_BOTTLE', 'CX_BOTTLE_PATH', 'CX_MANAGED_BOTTLE_PATH')}
        native = 'Z:\\owned\\IntegrationDemo.wproj'
        process = HeadlessLifecycle(console_path=context.bundle / 'Contents/Tools/WwiseConsole.sh',
            project_path=sandbox.sandbox_project, host_kind='wwise-authoring', authoring_build=context.build,
            authoring_owned_root=kwargs['case_owned_root'], port=8080, launch_env=environment)
        process._authoring_context = SimpleNamespace()  # External preparation succeeded.
        process.process = SimpleNamespace(pid=1234, poll=lambda: None)
        process.command = [str(wine), 'start.exe', '/wait',
            'c:/Program Files/Audiokinetic/Wwise 2025.1.11.9262/Authoring/x64/Release/bin/Wwise.exe', '-AutomationMode', native]
        process.launch_cwd = sandbox.sandbox_root
        process.ready_result = {'displayName': 'Wwise', 'isCommandLine': False, 'processId': 1234,
            'sessionId': 'fake-driver-session', 'version': {'year': 2025, 'major': 1, 'minor': 11, 'build': 9262, 'displayName': 'v2025.1.11.9262'}}
        process.launch_project_attestation = {'method': 'owned_winepath_roundtrip', 'project': str(sandbox.sandbox_project),
            'roundtrip_project': str(sandbox.sandbox_project), 'native_project': native, 'build': context.build,
            'bottle_resolution': {'name': 'Wwise2019x64', 'private_prefix': str(prefix), 'managed_reference': str(managed),
                'configuration': str(prefix / 'cxbottle.conf'), 'environment': bottle_env}}
        sandbox.metadata.selected_port = 8080
        sandbox.metadata.process_pid = 1234
        sandbox.metadata.launch_project_path = str(sandbox.sandbox_project)
        sandbox.metadata.identity_verified = True
        launched.append(process)
        return process
    monkeypatch.setattr(lifecycle, 'launch_sandboxed_wwise', launch)
    def shutdown(process, sandbox, **kwargs):
        events.append('shutdown')
        process.process = None
        process.cleanup_report = CleanupReport(launch_pid=1234, wine_prefix=None, process_exited=True)
        sandbox.metadata.process_cleanup_result = 'cleaned'
        sandbox.metadata.process_cleanup_details = {'residual_processes': []}
    monkeypatch.setattr(lifecycle, 'shutdown_sandboxed_wwise', shutdown)
    monkeypatch.setattr(authoring_batch, 'wait_for_port_release', lambda *_: None)
    monkeypatch.setattr(HeadlessLifecycle, '_process_rows', lambda *_, **__: [(99999, 'fake pytest process')])
    # Gateway subprocess/WAAPI transport is replaced; public Gateway parsing is real.
    def factory(*, skill_source, runtime, version, receipts):
        class Client(_RuntimeControlDraftClient):
            def call(self, uri, args=None, options=None):
                if uri.endswith('getInfo'):
                    return {**super().call(uri, args, options), **runtime.lifecycle.ready_result}
                if uri.endswith('getProjectInfo'):
                    return {'id': '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}', 'name': 'IntegrationDemo',
                        'path': str(runtime.sandbox.sandbox_project), 'isDirty': False}
                return super().call(uri, args, options)
        client = Client(tmp_path, version=version)
        env = _env(runtime.owned_root, version=version)
        set_gateway_config(env, wwise_version=version, project_modification_policy='ask_before_changes')
        def call(argv):
            code, payload = gateway.execute_gateway(['--state-dir', str(runtime.owned_root / 'setup-state'), *argv],
                env=env, client_factory=lambda _: client)
            receipts.append({'argv': list(argv), 'exit_code': code, 'payload': payload})
            assert code == 0, payload
            return payload
        return call
    monkeypatch.setattr(authoring_batch, 'fixture_gateway', factory)
    def control(batch, call, *, demo):
        events.append('node-dispatch')
        assert batch.selected_nodeids == (demo_module.NODEID,) and batch.owner._lock_acquired
        assert demo.context == context and call(['status'])['wwise']['version']['build'] == 9262
        destination = Path(batch.node_runtimes[demo_module.NODEID].runner_environment['WWISE_EVIDENCE_DIR'])
        destination.mkdir(parents=True, exist_ok=True)
        (destination / 'profiler-capture.json').write_text(json.dumps({
            'contract': 'waapi-skill.owned-profiler-capture/v1', 'candidate': batch.candidate, 'version': '2025.1',
            'scope': 'FAKE DRIVER CONTROL ONLY; no native observation', 'cleanup': {'complete': True},
            'outcomes': {probe.OUTCOME: {'outcome': 'PASS', 'evidence': {'observation_status': 'PASS'}}}}))
    demo_module = demo
    monkeypatch.setattr(probe, 'collect_loaded_event_probe', control)
    ini = tmp_path / 'pytest.ini'
    ini.write_text('[pytest]\n')
    code = pytest.main([demo.NODEID, '-c', str(ini), '--rootdir', str(root_conftest.REPO_ROOT),
        '--owned-authoring-batch-root=' + str(root), '-q'])
    assert code == 0
    assert events == ['launch', 'node-dispatch', 'shutdown'] and len(launched) == 1
    rows = [json.loads(line) for line in target.read_text().splitlines()]
    assert [row['invocation']['phase'] for row in rows] == ['prepared', 'final']
    assert rows[-1]['invocation']['outcome'] == 'PASS'
    assert not (root / 'owned').exists()
    receipt = json.loads((root / 'evidence/integration-demo-fixture-context.json').read_text())
    assert receipt['context_identity'] == context.identity and receipt['build'] == '2025.1.11.9262'
    assert receipt['source_config']['path'] == str(config_path)
