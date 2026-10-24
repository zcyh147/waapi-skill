"""Console candidate: real public Gateway, substituted external host only."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.unit.test_runtime_business_gateway import (
    _TransportCreateAssociationClient, _public_runtime_preview, gateway, _env,
)


def test_2025_console_create_publishes_usable_zero_transport(tmp_path):
    client = _TransportCreateAssociationClient(tmp_path, version='2025.1',
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


def _console_context(tmp_path, monkeypatch, fault=None):
    import hashlib
    import wave
    from tests.unit.test_profiler_input_native_fixture import _runtime
    from tests.unit.test_profiler_capture_native_fixture import _committed_car_capture_objects
    from tests.destructive.support import profiler_capture
    context = _runtime(tmp_path, monkeypatch)
    workflow, runtime, client, _, _ = context
    rows = _committed_car_capture_objects('2025.1')
    car = profiler_capture.CAPTURE_CAR_ID
    source = profiler_capture.CAPTURE_CAR_SOURCE_ID
    installed = tmp_path / 'installed/SampleProject2025.1.7.9143/SampleProject'
    media = installed / profiler_capture.CAPTURE_CAR_MEDIA
    media.parent.mkdir(parents=True)
    with wave.open(str(media), 'wb') as stream:
        stream.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        stream.writeframes(b'\x00\x01' * 8000)
    monkeypatch.setattr(profiler_capture, 'CAPTURE_SAMPLE_ROOT', tmp_path / 'installed')
    monkeypatch.setattr(profiler_capture, 'CAPTURE_CAR_SHA256', hashlib.sha256(media.read_bytes()).hexdigest())
    runtime.state_dir.mkdir(parents=True, exist_ok=True)
    # Stage through the actual existing attestation/staging helper.
    profiler_capture.stage_owned_capture_read_media(runtime.sandbox, runtime.state_dir, version='2025.1')
    rows[source]['originalFilePath'] = str(runtime.sandbox.sandbox_path / profiler_capture.CAPTURE_CAR_MEDIA)
    client.rows, client.transport_rows, client.playing, client.created = rows, [], False, False
    original = client.call
    def call(uri, args=None, options=None):
        if uri.endswith('object.get'):
            client.calls.append((uri, deepcopy(args), deepcopy(options)))
            ids = args.get('from', {}).get('id', [])
            if 'waql' in args:
                ids = [identity for identity in rows if identity in args['waql']]
            return {'return': [{key: deepcopy(row.get(key, row.get('@' + key)))
                for key in options['return'] if key in row or '@' + key in row}
                for identity in ids if (row := rows.get(identity))]}
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
            return {'return': [] if fault == 'empty' else [row]}
        return original(uri, args, options)
    client.call = call
    if fault == 'missing-media':
        (runtime.sandbox.sandbox_path / profiler_capture.CAPTURE_CAR_MEDIA).rename(runtime.state_dir / 'removed.wav')
    return context


def test_console_car_capture_reaches_actual_archived_final_category(tmp_path, monkeypatch):
    from tests.unit.test_profiler_input_native_fixture import _finish
    context = _console_context(tmp_path, monkeypatch)
    workflow, runtime, client, _, _ = context
    from tests.destructive.support.console_profiler_probe import collect_console_profiler, NODE_NAME
    collect_console_profiler(runtime)
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


@pytest.mark.parametrize('fault', ['missing-media', 'nonplaying', 'empty', 'cleanup'])
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
    if fault == 'missing-media':
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
    if fault == 'cleanup':
        assert report['outcomes']['voices']['outcome'] == 'PASS'
        assert report['cleanup']['complete'] is False
        assert report['cleanup']['errors'][0]['action'] == 'stop-transport'
        assert uris.count('ak.wwise.core.profiler.stopCapture') == 1
    else:
        assert report['cleanup']['complete'] is True
