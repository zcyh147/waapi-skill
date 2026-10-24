"""Grouped Console collector reaches Gateway and durable final writer; Wwise only is fake."""
import base64
from copy import deepcopy
import gzip
import json
from pathlib import Path

import pytest

from tests.unit.test_console_profiler_transport import _console_context, _forbid_real_client_or_socket
from tests.unit.test_profiler_input_native_fixture import _finish
from tests.destructive.support.profiler_capture import CAPTURE_CAR_ID, CAPTURE_RPM_ID

PREFIX = 'ak.wwise.core.profiler.'
NODE = 'test_console_owned_runtime_read_batch'


def _grouped_context(tmp_path, monkeypatch, *, version='2024.1', fault=None):
    context = _console_context(tmp_path, monkeypatch,
        'nonplaying' if fault == 'shared-playback' else 'cleanup' if fault == 'cleanup' else None, version=version)
    _, runtime, client, _, _ = context
    if version != '2025.1':
        # Actual R119 native diagnostics packet, unchanged (handles are issued anew).
        archive = Path(__file__).parents[1] / 'fixtures/branch-evidence/product/runtime-fixed-reads-r121' / (
            'r119-' + version[:4] + '-originals.json.gz')
        files = json.loads(gzip.decompress(archive.read_bytes()))['files']
        report, = [json.loads(base64.b64decode(value)) for key, value in files.items()
            if key.endswith('/console-profiler-probe.json')]
        voice = report['outcomes']['voices']['evidence']['agent_result']['return'][0]
        voice = {key: value for key, value in voice.items() if key != 'voice_instance_handle'}
    else:
        voice = {'pipelineID': 1, 'playingID': 1, 'soundID': 564536357,
            'objectGUID': CAPTURE_CAR_ID, 'objectName': 'Outside_Idle_1000',
            'gameObjectID': 123, 'gameObjectName': 'Transport/Soundcaster',
            'baseVolume': -8.9, 'gameAuxSendVolume': 0, 'envelope': 0, 'normalizationGain': 0,
            'lowPassFilter': 0, 'highPassFilter': 0, 'priority': 50,
            'isStarted': True, 'isVirtual': False, 'isForcedVirtual': False}
    game = voice['gameObjectID']
    bus_id = '{1514A4D8-1DA6-412A-A17E-75CA0C2149F3}'
    client.rows[CAPTURE_RPM_ID] = {'id': CAPTURE_RPM_ID, 'name': 'RPM', 'type': 'GameParameter',
        'path': r'\Game Parameters\Default Work Unit\RPM'}
    original = client.call
    def call(uri, args=None, options=None):
        if uri == PREFIX + 'getVoices':
            client.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': [] if fault == 'empty-voices' else [
                {key: value for key, value in voice.items() if key in options['return']}]}
        if uri in {PREFIX + name for name in ('getBusses', 'getAudioObjects', 'getRTPCs', 'getGameObjects', 'getVoiceContributions')}:
            client.calls.append((uri, deepcopy(args), deepcopy(options)))
            if fault == 'connection' and uri.endswith('getBusses'):
                raise ConnectionResetError('controlled shared connection loss')
            if fault == 'invalid-game-objects' and uri.endswith('getGameObjects'):
                return {'return': [{}]}
            if fault == 'invalid-busses' and uri.endswith('getBusses'):
                return {'return': [{'gameObjectID': 'not-an-integer'}]}
            if uri.endswith('getBusses'):
                row = {'pipelineID': 2, 'objectGUID': bus_id, 'objectName': 'Main Audio Bus',
                    'gameObjectID': game, 'gameObjectName': 'Transport/Soundcaster',
                    'volume': 0, 'downstreamGain': 0, 'voiceCount': 1, 'depth': 0}
            elif uri.endswith('getAudioObjects'):
                row = {'audioObjectID': 3, 'audioObjectName': '', 'busPipelineID': 2, 'busGUID': bus_id,
                    'busName': 'Main Audio Bus', 'gameObjectID': game, 'gameObjectName': 'Transport/Soundcaster',
                    'instigatorPipelineID': voice['pipelineID'], 'metadata': [], 'rmsMeter': [-12.5], 'peakMeter': [-10.5]}
            elif uri.endswith('getRTPCs'):
                row = {'id': CAPTURE_RPM_ID, 'name': 'RPM', 'gameObjectId': game, 'value': 1000}
            elif uri.endswith('getGameObjects'):
                row = {'id': game, 'name': 'Transport/Soundcaster',
                    'registrationTime' if version == '2022.1' else 'registerTime': 0,
                    'unregistrationTime' if version == '2022.1' else 'unregisterTime': -1}
            else:
                return {'return': {'volume': -8.9, 'LPF': 0, 'HPF': 0,
                    **({'DSF': 0} if version == '2025.1' else {}), 'objects': []}}
            if options and 'return' in options:
                row = {key: value for key, value in row.items() if key in options['return']}
            return {'return': [] if fault == 'empty-audio' and uri.endswith('getAudioObjects') else [row]}
        result = original(uri, args, options)
        if uri.endswith('transport.getList'):
            for row in result['list']:
                row['gameObject'] = game
        return result
    client.call = call
    return context


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1'])
def test_grouped_console_reads_reach_final_writer_at_one_numeric_position(tmp_path, monkeypatch, version):
    context = _grouped_context(tmp_path, monkeypatch, version=version)
    workflow, runtime, client, _, _ = context
    getattr(workflow, NODE)(runtime)
    final = _finish(context, tmp_path, monkeypatch, [(NODE, None)])[-1]
    category, = final['categories']
    report = json.loads(Path(category['observation_path']).read_text())
    assert final['invocation']['outcome'] == 'PASS' and report['complete']
    assert set(report['outcomes']) == {'voices', 'busses', 'audio_objects', 'game_objects', 'rtpcs', 'contributions_dry'}
    assert all(row['outcome'] == ('UNAVAILABLE' if name == 'game_objects' and version == '2021.1' else 'PASS')
        for name, row in report['outcomes'].items())
    assert report['cleanup']['complete'] and report['fixture_before'] == report['fixture_after']
    assert final['residual_state']['sandbox'] == 'deleted'
    assert report['public_call_count'] == {'2021.1': 79, '2022.1': 88, '2023.1': 96, '2024.1': 96, '2025.1': 96}[version]
    assert report['limits']['public_calls'] == 128 and report['limits']['cleanup_reserve_calls'] == 36
    assert all(call['cleanup_phase'] or index < 92 for index, call in enumerate(report['calls']))
    expected_datasets = ['voices', 'voiceInspector', 'audioObjects'] + ([] if version == '2021.1' else ['gameSyncs'])
    assert [args['dataTypes'] for uri, args, _ in client.calls if uri == PREFIX + 'enableProfilerData'] == [
        [{'dataType': dataset, 'enable': mode} for dataset in expected_datasets] for mode in (True, False)]
    reads = [(uri, args) for uri, args, _ in client.calls if uri.startswith(PREFIX) and 'time' in (args or {})]
    assert {args['time'] for _, args in reads} == {1500}
    assert all(sum(uri == PREFIX + name for uri, _ in reads) == 1 for name in
        ('getBusses', 'getAudioObjects', 'getRTPCs', 'getVoiceContributions'))
    assert sum(uri == PREFIX + 'getGameObjects' for uri, _ in reads) == (0 if version == '2021.1' else 1)
    assert next(args for uri, args in reads if uri.endswith('getVoiceContributions'))['bussesPipelineID'] == []
    assert report['outcomes']['audio_objects']['evidence']['agent_result']['return'][0]['metadata'] == []
    assert report['outcomes']['contributions_dry']['evidence']['agent_result']['objects'] == []
    assert report['outcomes']['rtpcs']['evidence']['setter_effect_verified'] is False


@pytest.mark.parametrize('fault,failed', [('empty-audio', 'audio_objects'), ('invalid-busses', 'busses'), ('empty-voices', 'voices'), ('invalid-game-objects', 'game_objects')])
def test_grouped_reader_failure_preserves_sibling_facts_after_final_cleanup(tmp_path, monkeypatch, fault, failed):
    context = _grouped_context(tmp_path, monkeypatch, fault=fault)
    workflow, runtime, client, _, _ = context
    with pytest.raises(AssertionError, match='Console playback/data probe incomplete') as caught:
        getattr(workflow, NODE)(runtime)
    final = _finish(context, tmp_path, monkeypatch, [(NODE, caught.value)])[-1]
    category, = final['categories']
    report = json.loads(Path(category['observation_path']).read_text())
    assert final['invocation']['outcome'] == 'FAIL' and category['status'] == 'blocked'
    assert final['residual_state']['sandbox'] == 'quarantined'
    assert report['cleanup']['complete'] and report['fixture_before'] == report['fixture_after']
    assert report['outcomes'][failed]['outcome'] in ('BLOCKED', 'FAIL')
    assert report['outcomes']['rtpcs']['outcome'] == 'PASS'
    if failed != 'game_objects':
        assert report['outcomes']['game_objects']['outcome'] == 'PASS'
    assert report['outcomes']['rtpcs']['evidence']['agent_result']['return'][0]['value'] == 1000
    assert report['outcomes']['rtpcs']['evidence']['gateway_result']['agent_result'] == report['outcomes']['rtpcs']['evidence']['agent_result']
    if failed == 'voices':
        assert report['outcomes']['contributions_dry']['outcome'] == 'BLOCKED'
        assert not any(uri.endswith('getVoiceContributions') for uri, _, _ in client.calls)
    else:
        assert report['outcomes']['voices']['outcome'] == report['outcomes']['contributions_dry']['outcome'] == 'PASS'
        assert report['outcomes']['voices']['evidence']['agent_result']['return'][0]['soundID'] == 564536357
    if fault == 'invalid-busses':
        assert report['outcomes']['busses']['evidence']['gateway_result']['ok'] is False
        assert report['outcomes']['audio_objects']['outcome'] == 'PASS'
    assert sum(uri == PREFIX + 'getRTPCs' for uri, _, _ in client.calls) == 1
    assert sum(uri.endswith('transport.destroy') for uri, _, _ in client.calls) == 1


@pytest.mark.parametrize('fault', ['shared-playback', 'connection', 'cleanup'])
def test_grouped_shared_failure_stops_dependents_and_cleanup_cannot_create_pass(tmp_path, monkeypatch, fault):
    context = _grouped_context(tmp_path, monkeypatch, fault=fault)
    workflow, runtime, client, _, _ = context
    with pytest.raises(AssertionError, match='Console playback/data probe incomplete') as caught:
        getattr(workflow, NODE)(runtime)
    final = _finish(context, tmp_path, monkeypatch, [(NODE, caught.value)])[-1]
    report = json.loads(Path(final['categories'][0]['observation_path']).read_text())
    assert not report['complete'] and final['invocation']['outcome'] == 'FAIL'
    assert final['residual_state']['sandbox'] == 'quarantined'
    assert report['fixture_before'] == report['fixture_after']
    assert sum(uri.endswith('transport.destroy') for uri, _, _ in client.calls) == 1
    assert sum(uri == PREFIX + 'stopCapture' for uri, _, _ in client.calls) == 1
    if fault == 'cleanup':
        assert {row['outcome'] for row in report['outcomes'].values()} == {'PASS'}
        assert not report['cleanup']['complete']
        assert report['cleanup']['errors'][0]['action'] == 'stop-transport'
    else:
        assert report['cleanup']['complete']
        assert not any(uri == PREFIX + 'getRTPCs' for uri, _, _ in client.calls)
        assert not any(uri == PREFIX + 'getVoiceContributions' for uri, _, _ in client.calls)
        if fault == 'shared-playback':
            assert not any(uri == PREFIX + 'getVoices' for uri, _, _ in client.calls)
        else:
            assert report['outcomes']['voices']['outcome'] == 'PASS'
            assert report['outcomes']['busses']['evidence']['gateway_result']['call']['error_code'] == 'ConnectionResetError'
            assert not any(uri == PREFIX + 'getAudioObjects' for uri, _, _ in client.calls)
    executed = [call['argv'][1] for call in report['calls'] if call['argv'][0] == 'execute']
    assert len(executed) == len(set(executed))
