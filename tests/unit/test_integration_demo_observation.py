"""Developer observation uses a scoped build without changing catalog defaults."""
from pathlib import Path
import json
import pytest


def test_scoped_context_checks_source_parity_before_any_lifecycle(tmp_path):
    from tests.destructive.support.integration_demo import IntegrationDemoObservation
    with pytest.raises(ValueError, match='schema'):
        IntegrationDemoObservation.from_installed(
            bundle=tmp_path / 'Wwise_2025.1.11.9262' / 'Wwise.app',
            schemas=tmp_path / 'Schemas')


def _installed(tmp_path):
    import plistlib
    from tests.destructive.support import integration_demo as demo
    root = tmp_path / 'Wwise_2025.1.11.9262'
    bundle, schemas = root / 'Wwise.app', tmp_path / 'Schemas'
    target = bundle / 'Contents/Info.plist'
    target.parent.mkdir(parents=True)
    target.write_bytes(plistlib.dumps({'CFBundleVersion': demo.BUILD}))
    indexed = {uri: demo.CapabilityCatalog().describe_for_profile('2025.1', uri,
        profile='wwise-authoring-ui').schema for uri in demo.URIS}
    for uri in demo.URIS:
        path = schemas / 'WAAPI' / (uri + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'functions': [{'id': uri, **indexed[uri]}]}))
    definitions = json.loads((demo.SKILL / 'resources/manifest/2025.1/definitions.json').read_bytes())['documents']
    for name in {name for name, _ in demo.DEFINITIONS}:
        path = schemas / 'Definitions' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(definitions[name]))
    header = root / 'SDK/include/AK/AkWwiseSDKVersion.h'
    header.parent.mkdir(parents=True)
    header.write_text('#define AK_WWISESDK_VERSION_MAJOR 2025\n#define AK_WWISESDK_VERSION_MINOR 1\n#define AK_WWISESDK_VERSION_SUBMINOR 11\n#define AK_WWISESDK_VERSION_BUILD 9262\n')
    for relative in ('DemoPages/DemoPrepare.cpp', 'Mac/main.m', 'Mac/Platform.h'):
        path = root / 'SDK/samples/IntegrationDemo' / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('fake substituted installed source receipt\n')
    return demo.IntegrationDemoObservation.from_installed(bundle=bundle, schemas=schemas)


def test_lifecycle_accepts_private_exact_build_and_keeps_default_catalog_pin(tmp_path):
    from tests.semantic.support.codex_scenario_lifecycle_v3 import ScenarioLifecycle
    context = _installed(tmp_path)
    console = context.bundle / 'Contents/Tools/WwiseConsole.sh'
    options = dict(scenario_id='demo', version='2025.1', scenario_root=tmp_path / 'case',
        live_environment={'WWISE_CONSOLE': str(console), 'AK_AUTOMATION_MODE': '1'},
        host_kind='wwise-authoring', launch_environment_overrides={'HOME': str(tmp_path / 'case/owned/home')})
    default = ScenarioLifecycle(**options)
    assert default.authoring_build == '2025.1.7.9143'
    scoped = ScenarioLifecycle(**options, developer_observation=context)
    assert scoped.authoring_build == '2025.1.11.9262'
    assert scoped.developer_observation is context
    assert not scoped.scenario_root.exists()
    source = context.schemas / 'WAAPI/ak.wwise.core.getInfo.json'
    source.write_text('{}')
    with pytest.raises(ValueError, match='changed before launch'):
        ScenarioLifecycle(**options, developer_observation=context)
    assert not scoped.scenario_root.exists()


def test_live_reflection_requires_all_twelve_receipts_and_stops_on_mismatch(tmp_path):
    from tests.destructive.support.integration_demo import URIS
    context = _installed(tmp_path)
    info = {'version': {'year': 2025, 'major': 1, 'minor': 11, 'build': 9262},
        'isCommandLine': False, 'sessionId': 'one-owned-session', 'processId': 1234}
    calls = []
    def call(argv):
        calls.append(argv)
        if argv == ['status']:
            return {'wwise': info}
        return {'reflection_context': info, 'agent_result': json.loads(context.schema_bytes)[argv[1]]}
    result = context.reflect(call, expected_info=info)
    assert [row['uri'] for row in result['schemas']] == list(URIS)
    assert len(calls) == 14
    calls.clear()
    def mismatch(argv):
        payload = call(argv)
        if argv[0] == 'waapi-schema':
            payload['agent_result'] = {}
        return payload
    with pytest.raises(ValueError, match='live schema/session mismatch'):
        context.reflect(mismatch, expected_info=info)
    assert len(calls) == 2 and not any(row[0] == 'execute' for row in calls)

from tests.unit.test_authoring_batch_adapter import owned_authoring


@pytest.mark.parametrize('failure', [None, 'empty', 'unrelated', 'cleanup', 'schema-mismatch', 'wrong-ui-token', 'ui-timeout', 'partial', 'discovery-warmup', 'discovery-empty', 'discovery-ambiguous', 'startup-exit', 'startup-timeout', 'output-overflow', 'cleanup-kill', 'startup-deadline', 'discovery-deadline', 'port-fd-missing'])
def test_stock_demo_producer_gateway_and_final_writer(owned_authoring, tmp_path, monkeypatch, failure):
    """All producer/Gateway/finalizer code runs; only process/UI are fake."""
    import subprocess
    from types import SimpleNamespace
    from tests.destructive.support import integration_demo as demo
    from tests.destructive.support import sandbox_fixture
    from tests.semantic.support import codex_harness
    from tests.unit.test_loaded_media_event_probe import _host, _archived
    from tests.unit.test_profiler_capture_native_fixture import _finish
    context = _installed(tmp_path)
    app = context.bundle.parent / 'SDK/Mac_Xcode1600/Profile/bin/IntegrationDemo/IntegrationDemo.app'
    binary = app / 'Contents/MacOS/IntegrationDemo'
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b'fake external SDK executable')
    binary.chmod(0o755)
    batch, call, client, probe = _host(owned_authoring, tmp_path, monkeypatch,
        failure=failure, demo_context=context, count=1000 if failure == 'partial' else 1)
    banks = context.bundle.parent / 'SDK/samples/IntegrationDemo/WwiseProject/GeneratedSoundBanks/Mac'
    for name in ('Init.bnk', 'PrepareDemo.bnk', 'Media/124871431.wem'):
        path = banks / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'fake external SDK bank/media')
    (banks / 'SoundbanksInfo.xml').write_text('<SoundBanksInfo><SoundBanks><SoundBank><ShortName>PrepareDemo</ShortName><IncludedEvents><Event Name="Enter_Area_1"><ReferencedStreamedFiles><MediaRef Id="124871431"/></ReferencedStreamedFiles></Event></IncludedEvents></SoundBank></SoundBanks></SoundBanksInfo>')
    from tests.destructive.support.sandbox_fixture import hash_project
    from dataclasses import replace
    proof = hash_project(batch.runtime.sandbox.source_root, preferred_strategy='full')
    batch.runtime.sandbox.metadata.source_hash = proof
    batch.owner.runtime = batch.runtime = replace(batch.runtime, source_hash_before=proof)
    producer = demo.OwnedIntegrationDemo(context, batch.runtime)
    startup_case = failure in ('discovery-warmup', 'discovery-empty', 'discovery-ambiguous',
        'startup-exit', 'startup-timeout', 'startup-deadline', 'discovery-deadline', 'output-overflow', 'cleanup-kill')
    passed = failure in (None, 'discovery-warmup', 'cleanup-kill')
    readiness_failure = failure in ('discovery-empty', 'discovery-ambiguous', 'startup-exit', 'startup-timeout', 'startup-deadline', 'discovery-deadline', 'output-overflow', 'port-fd-missing')
    launches = []
    from io import BytesIO
    class Child:
        pid = 23456
        returncode = 7 if failure == 'startup-exit' else None
        stdout = BytesIO(b'')
        stderr = BytesIO(b'x' * 65537 if failure == 'output-overflow' else b'optional plugin warning')
        def poll(self):
            return self.returncode
        def wait(self, timeout):
            if failure == 'cleanup-kill' and self.returncode is None:
                raise subprocess.TimeoutExpired('fake owned Demo', timeout)
            return self.returncode
    child = Child()
    def popen(argv, **kwargs):
        launches.append((argv, kwargs))
        return child
    monkeypatch.setattr(subprocess, 'Popen', popen)
    def no_residual_group(*args):
        raise ProcessLookupError
    monkeypatch.setattr(__import__('os'), 'killpg', no_residual_group)
    socket_packets = json.loads((Path(__file__).parents[1] / 'fixtures/integration-demo-startup-2025.1.11.9262.json').read_text())
    socket_calls = []
    def run(argv, **kwargs):
        assert argv[:3] == ['/usr/sbin/lsof', '-nP', '-a']
        assert argv[argv.index('-p') + 1] == '23456'
        if '-iUDP' in argv:
            socket_calls.append((argv, kwargs))
            packet = socket_packets['socket_snapshots'][0 if len(socket_calls) == 1 or failure in ('startup-timeout', 'startup-deadline') else 1]
            raw = packet['socket_stdout'].replace(str(socket_packets['pid']), '23456').replace('61758', '32123').encode()
            return SimpleNamespace(returncode=packet['socket_exit'], stdout=raw, stderr=b'')
        assert '-iTCP:32123' in argv
        assert 0 < kwargs['timeout'] <= 5
        if failure == 'port-fd-missing':
            return SimpleNamespace(returncode=0, stdout=b'p23456\n', stderr=b'')
        control = json.loads((Path(__file__).parents[1] / 'fixtures/integration-demo-lsof-field-control.json').read_text())
        return SimpleNamespace(returncode=0, stdout=control['stdout'].replace(str(control['pid']), '23456').encode(), stderr=b'')
    monkeypatch.setattr(subprocess, 'run', run)
    monkeypatch.setattr(codex_harness, 'terminate_process_group', lambda process: None if failure == 'cleanup-kill' else setattr(process, 'returncode', 0))
    monkeypatch.setattr(codex_harness, 'kill_process_group', lambda process: setattr(process, 'returncode', -9))
    monkeypatch.setattr(sandbox_fixture, 'wait_for_port_release', lambda *args: None)
    elapsed = {'seconds': 0}
    original_clock = probe.time.monotonic
    monkeypatch.setattr(probe.time, 'monotonic', lambda: original_clock() + elapsed['seconds'])
    def main_cua(_seconds):
        elapsed['seconds'] += _seconds
        if failure == 'startup-deadline':
            elapsed['seconds'] += 45
        if failure == 'discovery-deadline' and getattr(client, 'discovery_count', 0):
            elapsed['seconds'] += 60
        if failure == 'ui-timeout' and producer.ready.exists():
            elapsed['seconds'] += 121
            return
        if producer.ready.exists() and not producer.action.exists():
            ready = json.loads(producer.ready.read_bytes())
            screenshot = batch.runtime.evidence_root / 'fake-external-cua.png'
            screenshot.write_bytes(b'fake substituted CUA screenshot')
            producer.action.write_text(json.dumps({key: ready[key] for key in ('token', 'pid', 'build', 'page', 'area')} | {
                'token': 'wrong' if failure == 'wrong-ui-token' else ready['token'],
                'action': 'focused-stock-prepare-area1', 'screenshot': str(screenshot)}))
    monkeypatch.setattr(probe.time, 'sleep', main_cua)
    if passed:
        probe.collect_loaded_event_probe(batch, call, demo=producer)
    else:
        with pytest.raises(AssertionError):
            probe.collect_loaded_event_probe(batch, call, demo=producer)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=passed)
    report = _archived(batch)
    assert final['outcome'] == ('PASS' if passed else 'FAIL')
    category, = record['categories']
    assert category['status'] == ('PASS' if passed else 'blocked')
    assert report['cleanup']['complete'] is (failure != 'cleanup')
    assert report['fixture_before'] == report['fixture_after']
    assert sum(uri.endswith('profiler.getLoadedMedia') for uri, _, _ in client.calls) == (0 if readiness_failure or failure in ('schema-mismatch', 'wrong-ui-token', 'ui-timeout') else 1)
    assert not any('.transport.' in uri for uri, _, _ in client.calls)
    if failure == 'schema-mismatch' or readiness_failure:
        assert not any(row['argv'][0] == 'execute' for row in batch.receipts[demo.NODEID])
    assert len(launches) == (0 if failure == 'schema-mismatch' else 1)
    if failure != 'schema-mismatch':
        assert child.returncode == (-9 if failure == 'cleanup-kill' else 7 if failure == 'startup-exit' else 0)
        argv, kwargs = launches[0]
        assert 'SDK/Mac_Xcode1600/Profile/bin/IntegrationDemo/IntegrationDemo.app/Contents/MacOS/IntegrationDemo' in argv[0]
        assert kwargs['start_new_session'] is True and Path(kwargs['cwd']).is_relative_to(batch.runtime.owned_root)
    if failure == 'partial':
        evidence = report['outcomes'][probe.OUTCOME]['evidence']
        assert len(evidence['pages']) == 8 and evidence['complete'] is False
        assert evidence['pages'][-1]['next_command']
    if passed:
        assert category['owned_identity_observed'] is True
        assert category['attribution_scope'] == 'owned-sdk-prepare-area1'
        assert report['reflection']['build'] == '2025.1.11.9262'
        assert report['outcomes'][probe.OUTCOME]['evidence']['attributed_rows'][0]['mediaId'] == 124871431
        assert not batch.runtime.owned_root.exists()
    else:
        assert batch.lifecycle_result.quarantine_path

    if startup_case:
        startup = report['demo_startup']
        assert len(startup['samples']) <= 24 and len(startup['discovery']) <= 5
        if failure in ('startup-exit', 'output-overflow'):
            assert startup['samples'] == []
        else:
            assert startup['samples'][0]['ready'] is False
        assert all(sample[1]['timeout'] <= 2 for sample in socket_calls)
        discovery_calls = [(argv, timeout) for argv, timeout in client.gateway_timeouts
            if 'typed-zero-call' in argv and 'ak.wwise.core.remote.getAvailableConsoles' in argv]
        assert all(timeout <= 3 and float(argv[argv.index('--timeout') + 1]) == timeout
                   for argv, timeout in discovery_calls)
        stopped = next(row['result'] for row in report['cleanup']['receipts'] if row['action'] == 'owned-demo-stop')
        assert stopped['pre_cleanup_returncode'] == (7 if failure == 'startup-exit' else None)
        assert stopped['final_returncode'] == child.returncode
        assert stopped['streams']['stderr']['bytes_retained'] <= 65536
        if failure == 'discovery-warmup':
            assert len(discovery_calls) == 2
            assert startup['discovery'][0]['result'] == {'consoles': []}
            assert startup['discovery'][1]['result']['consoles'][0]['commandPort'] == 32123
            assert len(startup['samples']) == 2 and startup['samples'][-1]['ready'] is True
            assert startup['discovery'][0]['before']['elapsed_seconds'] >= startup['samples'][-1]['elapsed_seconds']
            assert next(i for i, (_, timeout) in enumerate(client.gateway_timeouts) if timeout <= 3) > 0
            assert sum(uri.endswith('remote.connect') for uri, _, _ in client.calls) == 1
            assert stopped['streams']['stderr']['text'] == 'optional plugin warning'
        elif readiness_failure:
            expected = {'startup-exit': 'Owned Demo exited', 'startup-timeout': 'communication not ready', 'startup-deadline': 'communication not ready',
                'discovery-deadline': 'discovery empty with live sockets',
                'discovery-empty': 'discovery empty with live sockets', 'discovery-ambiguous': 'discovery ambiguous',
                'output-overflow': 'output exceeds'}[failure]
            assert expected in report['errors'][0]['message']
            assert not discovery_calls if failure.startswith('startup-') or failure == 'output-overflow' else discovery_calls
        if failure == 'discovery-empty':
            assert len(discovery_calls) == 5
        if failure == 'startup-timeout':
            assert len(startup['samples']) == 24
        if failure == 'startup-deadline':
            assert len(startup['samples']) == 1 and startup['process']['elapsed_seconds'] >= 45
        if failure == 'discovery-deadline':
            assert len(discovery_calls) == 1 and startup['process']['elapsed_seconds'] >= 60
        output_receipt = json.loads(Path(report['demo']['process_output_receipt']).read_text())
        assert output_receipt['poll'] == child.returncode and stopped['process_group_absent'] is True
        if failure == 'cleanup-kill':
            assert stopped['cleanup_action'] == 'kill'

    if failure == 'port-fd-missing':
        assert report['remote_port_ownership']['owned'] is False
        assert report['remote_port_ownership']['stdout'] == 'p23456\n'
        assert report['remote_port_ownership']['exit_code'] == 0
        assert producer.command_port is None
        assert 'not owned by the exact Demo PID' in report['errors'][0]['message']
