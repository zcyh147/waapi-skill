"""Console candidate: real public Gateway, substituted external host only."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.unit.test_runtime_business_gateway import (
    _TransportCreateAssociationClient, _public_runtime_preview, gateway, _env,
)


@pytest.fixture(autouse=True)
def _forbid_real_client_or_socket(monkeypatch):
    import socket
    import waapi
    def forbidden(*_args, **_kwargs):
        pytest.fail('Console program tests forbid real WAAPI client/socket construction', pytrace=False)
    monkeypatch.setattr(waapi, 'WaapiClient', forbidden)
    monkeypatch.setattr(socket, 'socket', forbidden)


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1'])
def test_console_create_publishes_usable_zero_transport(tmp_path, version):
    client = _TransportCreateAssociationClient(tmp_path, version=version,
        observed_object='{11111111-1111-1111-1111-111111111111}', observed_game_object=123)
    original = client.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri == 'ak.wwise.core.getInfo':
            result['isCommandLine'] = True
            result['displayName'] = 'WwiseConsole'
        return result
    client.call = call
    preview, invoke = _public_runtime_preview(tmp_path, client, tmp_path / 'state',
        'ak.wwise.core.transport.create')
    executed = invoke(['execute', preview['transaction_id']])
    verified = invoke(executed['next_command']['gateway_argv'])
    assert verified['state'] == 'verified', verified
    handle = verified['agent_result']['business_result']['transport_handle']
    state = invoke(['core-call', 'ak.wwise.core.transport.getState', '--transport-handle', handle])
    assert state['agent_result']['state'] == 'stopped'
    assert sum(uri == 'ak.wwise.core.transport.create' for uri, _, _ in client.calls) == 1
    assert all(args == {'transport': 0} for uri, args, _ in client.calls if uri.endswith('transport.getState'))


def _console_context(tmp_path, monkeypatch, fault=None, *, version='2025.1'):
    import hashlib
    import wave
    from tests.unit.test_profiler_input_native_fixture import _runtime
    from tests.unit.test_profiler_capture_native_fixture import _committed_car_capture_objects
    from tests.destructive.support import profiler_capture
    context = _runtime(tmp_path, monkeypatch, version)
    workflow, runtime, client, _, _ = context
    rows = _committed_car_capture_objects(version)
    rows['{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}'] = {'id': '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}',
        'name': 'SampleProject', 'type': 'Project', 'path': '\\', 'filePath': str(client.project_file)}
    car = profiler_capture.CAPTURE_CAR_ID
    source = profiler_capture.CAPTURE_CAR_SOURCE_ID
    from tests.destructive.support.profiler_input_shapes import BUILDS
    build = '2025.1.7.9143' if version == '2022.1' else '.'.join(map(str, BUILDS[version]))
    installed = tmp_path / ('installed/SampleProject' + build + '/SampleProject')
    media = installed / profiler_capture.CAPTURE_CAR_MEDIA
    media.parent.mkdir(parents=True)
    with wave.open(str(media), 'wb') as stream:
        stream.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        stream.writeframes(b'\x00\x01' * 8000)
    monkeypatch.setattr(profiler_capture, 'CAPTURE_SAMPLE_ROOT', tmp_path / 'installed')
    monkeypatch.setattr(profiler_capture, 'CAPTURE_CAR_SHA256', hashlib.sha256(media.read_bytes()).hexdigest())
    runtime.state_dir.mkdir(parents=True, exist_ok=True)
    # Stage through the actual existing attestation/staging helper.
    profiler_capture.stage_owned_capture_read_media(runtime.sandbox, runtime.state_dir, version=version)
    rows[source]['originalFilePath'] = str(runtime.sandbox.sandbox_path / profiler_capture.CAPTURE_CAR_MEDIA)
    if version == '2021.1':
        rows['{44444444-4444-4444-4444-444444444444}'] = {
            'id': '{44444444-4444-4444-4444-444444444444}', 'name': 'Mac', 'type': 'Platform', 'path': 'Mac'}
        language = {'id': '{55555555-5555-5555-5555-555555555555}', 'name': 'SFX'}
        rows[language['id']] = {**language, 'type': 'Language', 'path': r'\Languages\SFX'}
        rows[car].update({'originalWavFilePath': rows[source]['originalFilePath'], 'audioSource:language': language})
        rows[source].update({'classId': 16, 'parent': {'id': car}, 'audioSource:language': language,
            'originalWavFilePath': rows[source]['originalFilePath']})
    client.rows, client.transport_rows, client.playing, client.created = rows, [], False, False
    original = client.call
    def call(uri, args=None, options=None):
        if uri.endswith('object.get'):
            client.calls.append((uri, deepcopy(args), deepcopy(options)))
            ids = args.get('from', {}).get('id', [])
            if args.get('from', {}).get('ofType') == ['Project']:
                ids = ['{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}']
            if args.get('waql') == 'from type Project take 1':
                ids = ['{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}']
            elif args.get('waql', '').startswith('from type Platform'):
                ids = ['{44444444-4444-4444-4444-444444444444}']
            elif args.get('waql', '').startswith('from type Language'):
                ids = ['{55555555-5555-5555-5555-555555555555}']
            elif 'select children' in args.get('waql', ''):
                ids = [source]
            elif 'waql' in args:
                ids = [identity for identity in rows if identity in args['waql']]
            return {'return': [{key: deepcopy(row.get(key, row.get('@' + key)))
                for key in options['return'] if key in row or '@' + key in row}
                for identity in ids if (row := rows.get(identity))]}
        if uri.endswith('object.getTypes'):
            return {'return': [{'classId': 65552, 'name': 'Sound', 'type': 'WObject'},
                {'classId': 16, 'name': 'AudioSource', 'type': 'WObject'}]}
        if uri.endswith('getPropertyAndReferenceNames'):
            return {'return': ['IsLoopingEnabled', 'IsLoopingInfinite']}
        if uri.endswith('getPropertyInfo'):
            return {'name': args['property'], 'type': 'bool', 'default': False,
                'supports': {'unlink': False}, 'dependencies': []}
        if uri.startswith('ak.wwise.core.transport.'):
            client.calls.append((uri, deepcopy(args), deepcopy(options)))
            if uri.endswith('getList'):
                return {'list': deepcopy(client.transport_rows)}
            if uri.endswith('create'):
                client.created = True
                client.transport_rows = [{'transport': 0, 'object': car, 'gameObject': 123}]
                return {'transport': 0}
            if uri.endswith('destroy'):
                client.transport_rows = []
                return {}
            if uri.endswith('executeAction'):
                if args['action'] == 'stop' and fault == 'cleanup':
                    raise RuntimeError('uncertain native stop, never retry')
                client.playing = args['action'] == 'play' and fault != 'nonplaying'
                return {}
            if uri.endswith('getState'):
                return {'state': 'playing' if client.playing else 'stopped'}
            return {}
        if uri.endswith('profiler.getVoices'):
            client.calls.append((uri, deepcopy(args), deepcopy(options)))
            row = {'pipelineID': 0, 'playingID': 42, 'objectGUID': car, 'objectName': 'Outside_Idle_1000',
                'gameObjectID': 123, 'gameObjectName': 'Transport/Soundcaster', 'isStarted': True}
            return {'return': [] if fault == 'empty' else
                [dict(row, pipelineID=index, playingID=42 + index) for index in range(65)]
                if fault == 'partial' else [row]}
        return original(uri, args, options)
    client.call = call
    if fault == 'missing-media':
        (runtime.sandbox.sandbox_path / profiler_capture.CAPTURE_CAR_MEDIA).rename(runtime.state_dir / 'removed.wav')
    if fault == 'changed-media':
        with (runtime.sandbox.sandbox_path / profiler_capture.CAPTURE_CAR_MEDIA).open('ab') as stream:
            stream.write(b'changed')
    return context


def test_console_car_capture_reaches_actual_archived_final_category(tmp_path, monkeypatch):
    from tests.unit.test_profiler_input_native_fixture import _finish
    context = _console_context(tmp_path, monkeypatch)
    workflow, runtime, client, _, _ = context
    from tests.destructive.support.console_profiler_probe import collect_console_profiler, NODE_NAME
    getattr(workflow, NODE_NAME)(runtime)
    pending, final = _finish(context, tmp_path, monkeypatch, [(NODE_NAME, None)])
    assert final['invocation']['outcome'] == 'PASS'
    category, = final['categories']
    assert category['status'] == 'PASS'
    report = json.loads(Path(category['observation_path']).read_text())
    assert report['complete'] and report['cleanup']['complete']
    assert report['host']['isCommandLine'] is True
    assert report['public_call_count'] == len(report['calls']) <= 128
    assert report['fixture_before'] == report['fixture_after']
    assert report['outcomes']['voices']['evidence']['agent_result']['return'][0]['voice_instance_handle'].startswith('rph1-')
    uris = [uri for uri, _, _ in client.calls]
    assert uris.count('ak.wwise.core.transport.create') == uris.count('ak.wwise.core.transport.prepare') == 1
    assert uris.count('ak.wwise.core.transport.destroy') == uris.count('ak.wwise.core.profiler.getVoices') == 1
    assert [args['action'] for uri, args, _ in client.calls if uri.endswith('transport.executeAction')] == ['play', 'stop']
    assert report['setup']['prepare']['verification']['business_state_verified'] is False
    assert final['residual_state']['sandbox'] == 'deleted'


@pytest.mark.parametrize('fault', ['missing-media', 'changed-media', 'nonplaying', 'empty', 'partial', 'cleanup'])
def test_console_probe_retains_blocked_failure_and_finishes_owned_cleanup(tmp_path, monkeypatch, fault):
    from tests.unit.test_profiler_input_native_fixture import _finish
    from tests.destructive.support.console_profiler_probe import collect_console_profiler, NODE_NAME
    context = _console_context(tmp_path, monkeypatch, fault)
    _, runtime, client, _, _ = context
    with pytest.raises(AssertionError, match='Console playback/data probe incomplete') as failure:
        collect_console_profiler(runtime)
    final, = _finish(context, tmp_path, monkeypatch, [(NODE_NAME, failure.value)])
    category, = final['categories']
    assert final['invocation']['outcome'] == 'FAIL'
    assert final['residual_state']['sandbox'] == 'quarantined'
    assert category['status'] == 'blocked' and category['observation_task_status'] == 'BLOCKED'
    report = json.loads(Path(category['observation_path']).read_text())
    assert not report['complete']
    assert report['public_call_count'] <= 128
    assert Path(category['observation_path']).stat().st_size <= report['limits']['report_bytes']
    uris = [uri for uri, _, _ in client.calls]
    if fault in ('missing-media', 'changed-media'):
        assert not any(uri.startswith('ak.wwise.core.transport.') for uri in uris)
    else:
        assert uris.count('ak.wwise.core.transport.create') == uris.count('ak.wwise.core.transport.destroy') == 1
        assert [args['action'] for uri, args, _ in client.calls if uri.endswith('transport.executeAction')] == ['play', 'stop']
        assert report['fixture_before'] == report['fixture_after']
    if fault == 'nonplaying':
        assert 'ak.wwise.core.profiler.getVoices' not in uris
    if fault == 'empty':
        voices = report['outcomes']['voices']
        assert voices['outcome'] == 'BLOCKED'
        assert voices['evidence']['complete'] is True and voices['evidence']['nonempty'] is False
        assert uris.count('ak.wwise.core.profiler.getVoices') == 1
    if fault == 'partial':
        voices = report['outcomes']['voices']
        assert voices['outcome'] == 'BLOCKED' and voices['evidence']['complete'] is False
        assert voices['evidence']['nonempty'] is True
        assert uris.count('ak.wwise.core.profiler.getVoices') == 1
    if fault == 'cleanup':
        assert report['outcomes']['voices']['outcome'] == 'PASS'
        assert report['cleanup']['complete'] is False
        assert report['cleanup']['errors'][0]['action'] == 'stop-transport'
        assert uris.count('ak.wwise.core.profiler.stopCapture') == 1
        assert uris.count('ak.wwise.core.profiler.enableProfilerData') == 2
    else:
        assert report['cleanup']['complete'] is True


@pytest.mark.parametrize('version,fault', [('2025.1', fault) for fault in
    [None, 'playing', 'unrelated', 'stale-time', 'silence', 'malformed', 'cleanup', 'missing-ack', 'wrong-ack', 'duplicate-ack']]
    + [(version, 'playing') for version in ['2021.1', '2022.1', '2023.1', '2024.1']])
def test_console_capture_log_ack_gates_one_play_and_archives_correlated_diagnostic(tmp_path, monkeypatch, version, fault):
    import subprocess
    from types import SimpleNamespace
    from tests.destructive.support.console_profiler_probe import collect_console_profiler
    from tests.unit.test_profiler_input_native_fixture import _finish
    from tests.destructive.support.profiler_capture import CAPTURE_CAR_ID
    context = _console_context(tmp_path, monkeypatch, None if fault == 'playing' else 'nonplaying', version=version)
    workflow, runtime, client, _, _ = context
    topic = 'ak.wwise.core.profiler.captureLog.itemAdded'
    packet = {'time': 1500, 'type': 'Message', 'description': 'controlled media-open failure',
        'severity': 'Error', 'errorCodeName': 'FileNotFound', 'objectId': CAPTURE_CAR_ID,
        'gameObjectId': 123, 'playingId': 42}
    if version == '2021.1':
        packet.pop('errorCodeName')
    if fault == 'unrelated':
        packet['objectId'] = '{11111111-1111-1111-1111-111111111111}'
    if fault == 'playing':
        packet.update(severity='Normal', description='controlled start')
    if fault == 'stale-time':
        packet['time'] = 1499
    if fault == 'malformed':
        packet.pop('time')
    active, trace = [], []
    original = client.call
    def call(uri, args=None, options=None):
        if uri.endswith('transport.executeAction') and args['action'] == 'play':
            assert active and trace[-1] == 'execute-peer'
            trace.append('play')
            if fault != 'silence':
                active[0](deepcopy(packet))
        return original(uri, args, options)
    client.call = call
    def subscribe(uri, callback, options=None):
        assert uri == topic and not options
        if fault == 'missing-ack':
            raise RuntimeError('controlled native subscription rejection')
        trace.append('subscribed'); active.append(callback)
        def unsubscribe():
            trace.append('unsubscribed'); active.clear(); return fault != 'cleanup'
        return SimpleNamespace(unsubscribe=unsubscribe)
    client.subscribe = subscribe
    from tests.semantic.support import codex_expansion_reconciliation as processes
    def producer(command, *, environment, timeout_seconds, cwd=None, text=True):
        assert active and command[7] in ('execute', 'verify')
        trace.append(command[7] + '-peer')
        code, payload = workflow.waapi_gateway.execute_gateway(command[3:], env=environment)
        return subprocess.CompletedProcess(command, code, json.dumps(payload), '')
    monkeypatch.setattr(processes, 'run_owned_gateway', producer)
    original_raw = type(runtime).raw_gateway
    def raw(self, argv, *, stream_sink=None):
        def sink(record):
            if record.get('record_type') == 'started' and fault == 'wrong-ack':
                record = {**record, 'topic_contract_digest': 'wrong'}
            stream_sink(record)
            if record.get('record_type') == 'started' and fault == 'duplicate-ack':
                stream_sink(deepcopy(record))
        return original_raw(self, argv, stream_sink=sink if stream_sink else None)
    monkeypatch.setattr(type(runtime), 'raw_gateway', raw)
    failure = None
    if fault == 'playing':
        getattr(workflow, 'test_console_owned_2025_transport_profiler_diagnostic' if version == '2025.1'
            else 'test_console_owned_older_transport_profiler_diagnostic')(runtime)
    else:
        with pytest.raises(AssertionError, match='Console playback/data probe incomplete') as caught:
            getattr(workflow, 'test_console_owned_2025_transport_profiler_diagnostic' if version == '2025.1'
            else 'test_console_owned_older_transport_profiler_diagnostic')(runtime)
        failure = caught.value
    node = 'test_console_owned_2025_transport_profiler_diagnostic' if version == '2025.1' else 'test_console_owned_older_transport_profiler_diagnostic'
    final = _finish(context, tmp_path, monkeypatch, [(node, failure)])[-1]
    report = json.loads(Path(final['categories'][0]['observation_path']).read_text())
    observed = report['play_diagnostic']
    assert final['categories'][0]['status'] == ('PASS' if fault == 'playing' else 'blocked')
    if fault == 'playing':
        assert report['outcomes']['voices']['outcome'] == 'PASS' and report['complete']
        assert final['invocation']['outcome'] == 'PASS'
    else:
        assert report['outcomes'] == {}
    actions = [args['action'] for uri, args, _ in client.calls if uri.endswith('transport.executeAction')]
    assert actions.count('play') == (0 if fault in ('missing-ack', 'wrong-ack') else 1)
    assert actions.count('stop') == 1
    assert observed['cause_proven'] is False
    if version != '2025.1':
        uris = [uri for uri, _, _ in client.calls]
        assert uris.count('ak.wwise.core.transport.useOriginals') == (1 if version in ('2023.1', '2024.1') else 0)
        assert uris.count('ak.wwise.core.transport.prepare') == (0 if version == '2021.1' else 1)
        assert uris.count('ak.wwise.core.profiler.getVoices') == 1
        from wwise_waapi.native_catalog import load_native_catalog
        pinned = load_native_catalog(version, 'wwise-console')['definitions']['documents']['waapi_definitions.json']['definitions']['voiceReturnOptions']['items']['enum']
        _, _, options = next(call for call in client.calls if call[0] == 'ak.wwise.core.profiler.getVoices')
        assert set(options['return']) == set(pinned) and len(options['return']) == len(pinned)
    if fault in ('missing-ack', 'wrong-ack'):
        assert not observed['started_before_execute']
        assert not observed['events']
    elif fault == 'duplicate-ack':
        assert actions.count('play') == 1
    else:
        assert observed['started_before_execute']
        assert trace[:4] == ['subscribed', 'execute-peer', 'play', 'verify-peer']
        assert trace[4:] == ['unsubscribed'] * (2 if fault == 'cleanup' else 1)
        if fault == 'cleanup':
            assert observed['cleanup'] != 'unsubscribed'
            assert report['cleanup']['complete'] is False
        else:
            assert observed['cleanup'] == 'unsubscribed'
        if fault == 'malformed':
            assert observed['terminal']['error_code'] == 'TOPIC_EVENT_SCHEMA_MISMATCH'
            raw = observed['terminal']['details']['event_diagnostic']
            assert raw['complete'] and json.loads(raw['json']) == packet
        elif fault == 'silence':
            assert not observed['events']
            assert observed['silence_meaning'].startswith('inconclusive')
        else:
            event, = observed['events']
            assert event['event'] == packet and event['cause_proven'] is False
            assert event['correlation'] == ('unrelated_or_identity_unresolved' if fault == 'unrelated'
                else 'identity_only_time_unresolved' if fault == 'stale-time'
                else 'matching_identity_and_capture_interval')
        if fault not in ('malformed', 'cleanup'):
            assert report['playback']['state'] == ('playing' if fault == 'playing' else 'stopped')


@pytest.mark.parametrize('version,operation', [('2021.1', 'prepare'), ('2021.1', 'useOriginals'), ('2022.1', 'useOriginals')])
def test_missing_transport_api_is_a_version_boundary_without_connection(tmp_path, version, operation):
    code, payload = gateway.execute_gateway(['request-schema', 'ak.wwise.core.transport.' + operation],
        env=_env(tmp_path, version=version), client_factory=lambda _: pytest.fail('Absent route connected'))
    assert code == 2 and payload.get('ok') is False, payload
    assert payload['error_code'] != 'AUTHORING_HOST_REQUIRED'


def test_overlong_native_original_blocks_before_any_runtime_effect(tmp_path, monkeypatch):
    from tests.destructive.support.console_profiler_probe import NODE_NAME
    from tests.destructive.support.profiler_capture import CAPTURE_CAR_SOURCE_ID, CAPTURE_CAR_MEDIA
    from tests.unit.test_profiler_input_native_fixture import _finish
    owned = tmp_path / ('long-owned-' + 'x' * 120)
    owned.mkdir()
    context = _console_context(owned, monkeypatch)
    workflow, runtime, client, _, _ = context
    media = runtime.sandbox.sandbox_path / CAPTURE_CAR_MEDIA
    native = 'Z:' + media.as_posix()
    assert len(native) + 1 > 260  # ASCII fixture exceeds the verified Windows bound.
    client.rows[CAPTURE_CAR_SOURCE_ID]['originalFilePath'] = native
    with pytest.raises(AssertionError, match='Console playback/data probe incomplete') as caught:
        getattr(workflow, NODE_NAME)(runtime)
    final = _finish(context, owned, monkeypatch, [(NODE_NAME, caught.value)])[-1]
    report = json.loads(Path(final['categories'][0]['observation_path']).read_text())
    assert report['native_source_path_limit'] == {'flavor': 'drive',
        'utf16_units_including_nul': len(native) + 1, 'allowed_units_including_nul': 260}
    assert f"{len(native) + 1} UTF-16 units including NUL exceeds allowed 260" in report['errors'][0]['message']
    assert report['setup'] == {} and final['transactions'] == []
    assert not any(uri.startswith(('ak.wwise.core.transport.', 'ak.wwise.core.profiler.'))
        for uri, _, _ in client.calls)
    assert report['fixture_before'] == report['fixture_after'] and report['cleanup']['complete']
    assert final['residual_state']['sandbox'] == 'quarantined'


@pytest.mark.parametrize('namespace,allowed', [('windows-260', True), ('windows-261', False), ('long-posix', True)])
def test_console_native_path_limit_counts_utf16_and_preserves_posix(tmp_path, monkeypatch, namespace, allowed):
    from tests.destructive.support.console_profiler_probe import NODE_NAME
    from tests.destructive.support.profiler_capture import CAPTURE_CAR_SOURCE_ID, CAPTURE_CAR_MEDIA
    from tests.unit.test_profiler_input_native_fixture import _finish
    if namespace == 'long-posix':
        owned = tmp_path / ('x' * 120)
    else:
        # The rejected path includes U+1F697: two UTF-16 units, one Python
        # character, four UTF-8 bytes. The allowed ASCII path is exactly 260 units.
        target = 260 if allowed else 261
        stem = 'car-' if allowed else 'car-🚗-'
        base = 'Z:' + (tmp_path / stem / 'SampleProject' / CAPTURE_CAR_MEDIA).as_posix()
        padding = target - (len(base) + 1 + (0 if allowed else 1))
        assert padding > 0
        owned = tmp_path / (stem + 'x' * padding)
    owned.mkdir()
    context = _console_context(owned, monkeypatch)
    workflow, runtime, client, _, _ = context
    media = runtime.sandbox.sandbox_path / CAPTURE_CAR_MEDIA
    native = media.as_posix() if namespace == 'long-posix' else 'Z:' + media.as_posix()
    client.rows[CAPTURE_CAR_SOURCE_ID]['originalFilePath'] = native
    failure = None
    if allowed:
        getattr(workflow, NODE_NAME)(runtime)
    else:
        with pytest.raises(AssertionError, match='261 UTF-16 units including NUL exceeds allowed 260') as caught:
            getattr(workflow, NODE_NAME)(runtime)
        failure = caught.value
    final = _finish(context, owned, monkeypatch, [(NODE_NAME, failure)])[-1]
    report = json.loads(Path(final['categories'][0]['observation_path']).read_text())
    if namespace == 'long-posix':
        assert len(native) + 1 > 260
        assert 'native_source_path_limit' not in report
    else:
        assert report['native_source_path_limit']['utf16_units_including_nul'] == (260 if allowed else 261)
        assert report['native_source_path_limit']['allowed_units_including_nul'] == 260
    assert report['complete'] is allowed
    assert final['invocation']['outcome'] == ('PASS' if allowed else 'FAIL')
    assert final['residual_state']['sandbox'] == ('deleted' if allowed else 'quarantined')
    assert report['fixture_before'] == report['fixture_after'] and report['cleanup']['complete']
    if not allowed:
        assert final['transactions'] == [] and report['setup'] == {}
        assert not any(uri.startswith(('ak.wwise.core.transport.', 'ak.wwise.core.profiler.'))
            for uri, _, _ in client.calls)


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1'])
@pytest.mark.parametrize('changed_binding', [False, True])
def test_unicode_project_draft_preserves_exact_binding(tmp_path, monkeypatch, version, changed_binding):
    owned = tmp_path / '项目-é-🚗'
    owned.mkdir()
    client = _TransportCreateAssociationClient(owned, version=version,
        observed_object='{11111111-1111-1111-1111-111111111111}')
    env = _env(owned, version=version)
    state = owned / 'state'
    def run(*argv):
        return gateway.execute_gateway(['--state-dir', str(state), *argv], env=env,
            client_factory=lambda _: client)
    code, started = run('draft-start', 'ak.wwise.core.transport.create')
    assert code == 0, started
    draft, authority = started['draft']['draft_id'], started['task_authority']
    code, bound = run('draft-bind-object', draft, '--task-authority', authority,
        '--expected-revision', str(started['draft']['revision']), '--role', 'target', '--object-id', client.target_id)
    assert code == 0, bound
    revision = bound['draft']['revision']
    if changed_binding:
        # Visually equivalent but byte-distinct project path must not acquire
        # the original Draft/handle authority through Unicode normalization.
        if version == '2021.1':
            # This version reports the Project hierarchy path (\), not its
            # file path, in the business context; change its live GUID instead.
            original = client.call
            def changed_project(uri, args=None, options=None):
                result = original(uri, args, options)
                if uri.endswith('object.get') and args.get('waql') == 'from type Project take 1':
                    result['return'][0]['id'] = '{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}'
                return result
            client.call = changed_project
        else:
            client.project_file = Path(str(client.project_file).replace('é', 'e\u0301'))
    code, declared = run('draft-declare-runtime-control-plan', draft, '--task-authority', authority,
        '--expected-revision', str(revision), '--target-handle', bound['bound_object']['handle'])
    if changed_binding:
        assert code == 2 and declared['error_code'] == 'OPERATION_DRAFT_BINDING_DRIFT', declared
        code, shown = run('draft-inspect', draft, '--task-authority', authority)
        assert code == 0 and shown['draft']['revision'] == revision, shown
        assert not client.created
        return
    assert code == 0, declared
    for phase in ('draft-check', 'preview-from-draft'):
        code, declared = run(phase, draft, '--task-authority', authority,
            '--expected-revision', str(declared['draft']['revision']))
        assert code == 0, declared
    transaction = declared['transaction_id']
    code, shown = run('transaction-show', transaction)
    assert code == 0 and shown['confirmation']['token']
    assert not client.created
    code, confirmed = run('confirm', transaction, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, executed = run('execute', transaction)
    assert code == 0 and executed['state'] == 'executed_unverified', executed
    code, verified = run('verify', transaction)
    assert code == 0 and verified['agent_result']['business_result']['transport_handle'].startswith('trh1-'), verified
    code, repeated = run('execute', transaction)
    assert code == 2, repeated
    assert sum(uri == 'ak.wwise.core.transport.create' for uri, _, _ in client.calls) == 1


def test_unicode_260_unit_original_reaches_archived_console_result(tmp_path, monkeypatch):
    from tests.destructive.support.console_profiler_probe import NODE_NAME
    from tests.destructive.support.profiler_capture import CAPTURE_CAR_SOURCE_ID, CAPTURE_CAR_MEDIA
    from tests.unit.test_profiler_input_native_fixture import _finish
    stem = '项目-é-🚗-'
    base = 'Z:' + (tmp_path / stem / 'SampleProject' / CAPTURE_CAR_MEDIA).as_posix()
    owned = tmp_path / (stem + 'x' * (260 - len(base) - 2))
    owned.mkdir()
    context = _console_context(owned, monkeypatch)
    workflow, runtime, client, _, _ = context
    native = 'Z:' + (runtime.sandbox.sandbox_path / CAPTURE_CAR_MEDIA).as_posix()
    assert len(native) + 2 == 260  # One supplementary character plus NUL.
    client.rows[CAPTURE_CAR_SOURCE_ID]['originalFilePath'] = native
    getattr(workflow, NODE_NAME)(runtime)
    final = _finish(context, owned, monkeypatch, [(NODE_NAME, None)])[-1]
    report = json.loads(Path(final['categories'][0]['observation_path']).read_text())
    assert final['invocation']['outcome'] == 'PASS' and report['complete']
    assert report['cleanup']['complete'] and report['fixture_before'] == report['fixture_after']
    assert final['residual_state']['sandbox'] == 'deleted'
    assert [args['action'] for uri, args, _ in client.calls if uri.endswith('transport.executeAction')] == ['play', 'stop']
