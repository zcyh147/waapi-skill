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
    if fault == 'approved-voice-anchors':
        for optional in ('gameAuxSendVolume', 'envelope', 'normalizationGain', 'lowPassFilter', 'highPassFilter'):
            voice.pop(optional)
    game = voice['gameObjectID']
    bus_id = '{1514A4D8-1DA6-412A-A17E-75CA0C2149F3}'
    client.rows[CAPTURE_RPM_ID] = {'id': CAPTURE_RPM_ID, 'name': 'RPM', 'type': 'GameParameter',
        'path': r'\Game Parameters\Default Work Unit\RPM'}
    original = client.call
    host_drift_ready = False
    def call(uri, args=None, options=None):
        nonlocal host_drift_ready
        if uri == PREFIX + 'getVoices':
            host_drift_ready = fault == 'host-drift'
            client.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': [] if fault == 'empty-voices' else [
                {key: value for key, value in voice.items() if key in options['return']}]}
        if uri in {PREFIX + name for name in ('getBusses', 'getAudioObjects', 'getRTPCs', 'getGameObjects', 'getVoiceContributions')}:
            client.calls.append((uri, deepcopy(args), deepcopy(options)))
            if fault == 'connection' and uri.endswith('getBusses'):
                raise ConnectionResetError('controlled shared connection loss')
            if fault == 'game-objects-dispatch' and uri.endswith('getGameObjects'):
                raise RuntimeError('controlled reader-specific GameObjects dispatch failure')
            if fault == 'invalid-game-objects' and uri.endswith('getGameObjects'):
                return {'return': [{}]}
            if fault == 'invalid-busses' and uri.endswith('getBusses'):
                return {'return': [{'gameObjectID': 'not-an-integer'}]}
            if uri.endswith('getBusses'):
                host_drift_ready = False
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
                if fault == 'empty-contribution':
                    return {'return': {'objects': []}}
                if fault == 'partial-contribution':
                    return {'return': {'LPF': 0, 'objects': []}}
                return {'return': {'volume': -8.9, 'LPF': 0, 'HPF': 0,
                    **({'DSF': 0} if version == '2025.1' else {}), 'objects': []}}
            if options and 'return' in options:
                row = {key: value for key, value in row.items() if key in options['return']}
            return {'return': [] if fault == 'empty-audio' and uri.endswith('getAudioObjects') else [row]}
        result = original(uri, args, options)
        if fault == 'host-drift' and host_drift_ready and uri == 'ak.wwise.core.getInfo':
            result['isCommandLine'] = False
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


@pytest.mark.parametrize('fault,failed', [('empty-audio', 'audio_objects'), ('invalid-busses', 'busses'), ('empty-voices', 'voices'), ('invalid-game-objects', 'game_objects'), ('game-objects-dispatch', 'game_objects')])
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
    if fault == 'game-objects-dispatch':
        packet = report['outcomes']['game_objects']['evidence']['gateway_result']
        assert packet['semantic_preview']['uri'] == packet['call']['api'] == PREFIX + 'getGameObjects'
        assert packet['call']['error_code'] == 'RuntimeError'
        assert sum(uri == PREFIX + 'getGameObjects' for uri, _, _ in client.calls) == 1
        assert sum(uri == PREFIX + 'getVoiceContributions' for uri, _, _ in client.calls) == 1
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


def test_older_empty_contribution_retains_missing_values_and_successful_siblings(tmp_path, monkeypatch):
    context = _grouped_context(tmp_path, monkeypatch, version='2022.1', fault='empty-contribution')
    workflow, runtime, client, _, _ = context
    with pytest.raises(AssertionError, match='Console playback/data probe incomplete') as caught:
        getattr(workflow, NODE)(runtime)
    final = _finish(context, tmp_path, monkeypatch, [(NODE, caught.value)])[-1]
    report = json.loads(Path(final['categories'][0]['observation_path']).read_text())
    contribution = report['outcomes']['contributions_dry']
    assert contribution['outcome'] == 'BLOCKED' and contribution['evidence']['nonempty'] is False
    result = contribution['evidence']['agent_result']
    assert result['contribution_reported'] is True and result['objects'] == []
    assert result['volume'] is result['lpf'] is result['hpf'] is None
    assert result['unreported_fields'] == ['volume', 'lpf', 'hpf']
    assert all(row['outcome'] == 'PASS' for name, row in report['outcomes'].items() if name != 'contributions_dry')
    assert report['cleanup']['complete'] and report['fixture_before'] == report['fixture_after']
    assert final['invocation']['outcome'] == 'FAIL' and final['residual_state']['sandbox'] == 'quarantined'
    assert sum(uri == PREFIX + 'getVoiceContributions' for uri, _, _ in client.calls) == 1


def test_2025_voice_requires_approved_anchors_without_optional_diagnostics(tmp_path, monkeypatch):
    context = _grouped_context(tmp_path, monkeypatch, version='2025.1', fault='approved-voice-anchors')
    workflow, runtime, client, _, _ = context
    getattr(workflow, NODE)(runtime)
    final = _finish(context, tmp_path, monkeypatch, [(NODE, None)])[-1]
    report = json.loads(Path(final['categories'][0]['observation_path']).read_text())
    assert final['invocation']['outcome'] == 'PASS' and report['cleanup']['complete']
    assert final['residual_state']['sandbox'] == 'deleted'
    voice = report['outcomes']['voices']['evidence']['agent_result']['return'][0]
    assert {field: voice[field] for field in ('baseVolume', 'soundID', 'priority', 'isStarted', 'isVirtual', 'isForcedVirtual')} == {
        'baseVolume': -8.9, 'soundID': 564536357, 'priority': 50, 'isStarted': True, 'isVirtual': False, 'isForcedVirtual': False}
    assert not set(('gameAuxSendVolume', 'envelope', 'normalizationGain', 'lowPassFilter', 'highPassFilter')) & voice.keys()
    assert report['outcomes']['voices']['outcome'] == report['outcomes']['contributions_dry']['outcome'] == 'PASS'
    assert sum(uri == PREFIX + 'getVoiceContributions' for uri, _, _ in client.calls) == 1


def test_grouped_reader_host_drift_stops_console_claims_and_later_reads(tmp_path, monkeypatch):
    context = _grouped_context(tmp_path, monkeypatch, fault='host-drift')
    workflow, runtime, client, _, _ = context
    with pytest.raises(AssertionError, match='Console playback/data probe incomplete') as caught:
        getattr(workflow, NODE)(runtime)
    final = _finish(context, tmp_path, monkeypatch, [(NODE, caught.value)])[-1]
    report = json.loads(Path(final['categories'][0]['observation_path']).read_text())
    assert report['outcomes']['voices']['outcome'] == 'PASS'
    busses = report['outcomes']['busses']
    assert busses['outcome'] == 'BLOCKED'
    assert busses['evidence']['gateway_result']['is_command_line'] is False
    assert not any(uri in (PREFIX + 'getAudioObjects', PREFIX + 'getRTPCs', PREFIX + 'getVoiceContributions')
        for uri, _, _ in client.calls)
    assert report['cleanup']['complete'] and report['fixture_before'] == report['fixture_after']
    assert final['invocation']['outcome'] == 'FAIL' and final['residual_state']['sandbox'] == 'quarantined'


@pytest.mark.parametrize('host', [True, False, None], ids=['console', 'authoring', 'unknown'])
def test_gateway_result_error_preserves_only_attested_boolean_host(tmp_path, host):
    from tests.unit.test_stable_read_adapters import FakeClient, _live_info, _gateway_env, waapi_gateway
    info = _live_info('2024.1')
    if host is None:
        info.pop('isCommandLine')
    else:
        info['isCommandLine'] = host
    client = FakeClient({'ak.wwise.core.getInfo': info, PREFIX + 'getGameObjects': {'return': [{}]}})
    code, payload = waapi_gateway.execute_gateway(['profiler-game-objects', '--capture-ms', '1500'],
        env=_gateway_env(tmp_path, '2024.1'), client_factory=lambda _: client)
    assert code == 2 and payload['error_code'] == 'SemanticValidationError'
    assert payload['details']['uri'] == PREFIX + 'getGameObjects'
    if host is None:
        assert 'is_command_line' not in payload
    else:
        assert payload['is_command_line'] is host
    assert payload['detected_version'] == '2024.1' and client.disconnected
    assert [uri for uri, _, _ in client.calls] == ['ak.wwise.core.getInfo', PREFIX + 'getGameObjects']


def test_offline_gateway_does_not_invent_attested_host(tmp_path):
    from tests.unit.test_stable_read_adapters import _gateway_env, waapi_gateway
    code, payload = waapi_gateway.execute_gateway(['request-schema', PREFIX + 'getVoices'],
        env=_gateway_env(tmp_path, '2024.1'), client_factory=lambda _: pytest.fail('Offline route connected'))
    assert code == 0 and 'is_command_line' not in payload


def test_older_partial_contribution_preserves_unreported_optional_scalars(tmp_path, monkeypatch):
    context = _grouped_context(tmp_path, monkeypatch, version='2022.1', fault='partial-contribution')
    workflow, runtime, client, _, _ = context
    getattr(workflow, NODE)(runtime)
    final = _finish(context, tmp_path, monkeypatch, [(NODE, None)])[-1]
    report = json.loads(Path(final['categories'][0]['observation_path']).read_text())
    contribution = report['outcomes']['contributions_dry']
    assert contribution['outcome'] == 'PASS' and contribution['evidence']['reported_finite_scalar'] is True
    result = contribution['evidence']['agent_result']
    assert result['lpf'] == 0 and result['volume'] is result['hpf'] is None
    assert result['objects'] == [] and result['unreported_fields'] == ['volume', 'hpf']
    assert report['cleanup']['complete'] and final['invocation']['outcome'] == 'PASS'
    assert final['residual_state']['sandbox'] == 'deleted'
    assert sum(uri == PREFIX + 'getVoiceContributions' for uri, _, _ in client.calls) == 1


ADDITIONAL_NODE = 'test_console_owned_additional_runtime_read_batch'
ADDITIONAL_READERS = {'loaded_media': 'getLoadedMedia', 'cpu': 'getCpuUsage',
    'performance': 'getPerformanceMonitor', 'streamed_media': 'getStreamedMedia'}


def _additional_context(tmp_path, monkeypatch, *, version='2024.1', fault=None):
    context = _console_context(tmp_path, monkeypatch, 'cleanup' if fault == 'cleanup' else None, version=version)
    _, runtime, client, _, _ = context
    rows = {'getCpuUsage': [dict(id=i, type='', elementName='CAkAudioMgr::Perform', instances=2,
        millisecondsExclusive=0.014, millisecondsInclusive=0.2167, percentExclusive=0.13, percentInclusive=2.03) for i in range(257 if fault == 'row-bound' else 65)],
        'getPerformanceMonitor': [{'id':'ActiveTransitions','name':'Number of Transitions/Interpolations','value':0}],
        'getLoadedMedia': ([{'mediaId':124871431,'fileName':'Ambience_40.wav','format':'VORBIS','size':160821,'soundBank':'Prepared'}]
            if version == '2025.1' else []), 'getStreamedMedia': []}
    original = client.call
    def call(uri, args=None, options=None):
        if uri in {PREFIX + suffix for suffix in ADDITIONAL_READERS.values()}:
            client.calls.append((uri, deepcopy(args), deepcopy(options)))
            if uri.endswith('getCpuUsage') and fault == 'reader': return {'return':[{'millisecondsExclusive':'invalid'}]}
            if uri.endswith('getCpuUsage') and fault == 'connection': raise ConnectionResetError('controlled extra-reader connection failure')
            return {'return':deepcopy(rows[uri.rsplit('.',1)[-1]])}
        return original(uri,args,options)
    client.call = call
    if fault == 'page-drift':
        raw_gateway = type(runtime).raw_gateway
        def changed_page(self, argv, **kwargs):
            code, payload = raw_gateway(self, argv, **kwargs)
            if '--runtime-page' in argv and payload.get('ok'):
                payload['agent_result']['snapshot_sha256'] = '0' * 64
            return code, payload
        monkeypatch.setattr(type(runtime), 'raw_gateway', changed_page)
    return context, rows


@pytest.mark.parametrize('version', ['2023.1','2024.1','2025.1'])
def test_additional_console_readers_keep_complete_paged_arrays_and_empty_availability(tmp_path, monkeypatch, version):
    context, rows = _additional_context(tmp_path, monkeypatch, version=version)
    workflow, runtime, client, _, _ = context
    getattr(workflow, ADDITIONAL_NODE)(runtime)
    final = _finish(context,tmp_path,monkeypatch,[(ADDITIONAL_NODE,None)])[-1]
    category, = final['categories'];report = json.loads(Path(category['observation_path']).read_bytes())
    assert final['invocation']['outcome']=='PASS' and final['residual_state']['sandbox']=='deleted'
    assert category['category']=='console-additional-runtime-read-batch'
    assert set(report['outcomes'])==set(ADDITIONAL_READERS) and report['complete'] and report['cleanup']['complete']
    assert report['fixture_before']==report['fixture_after']
    for key,suffix in ADDITIONAL_READERS.items():
        entry=report['outcomes'][key];evidence=entry['evidence']
        assert entry['outcome']=='PASS' and evidence['available'] and evidence['complete']
        assert evidence['retained_rows']==rows[suffix] and evidence['nonempty']==bool(rows[suffix])
        assert evidence['position_ms']==1500 and evidence['control_effect_verified'] is False
        calls=[args for uri,args,_ in client.calls if uri==PREFIX+suffix]
        assert calls==[{'time':1500}]
    cpu=report['outcomes']['cpu']['evidence']
    assert len(cpu['agent_result_pages'])==3 and cpu['agent_result_pages'][0]['truncated']
    assert cpu['retained_page_calls']==2
    assert report['outcomes']['streamed_media']['evidence']['claim']=='availability_only'
    assert report['outcomes']['loaded_media']['evidence']['claim']==('actual_returned_diagnostics' if version=='2025.1' else 'availability_only')
    enable=[args['dataTypes'] for uri,args,_ in client.calls if uri==PREFIX+'enableProfilerData']
    assert enable==[[{'dataType':token,'enable':mode} for token in ('voices','cpu','loadedMedia','stream')] for mode in (True,False)]
    assert report['limits']['public_calls']==128 and report['limits']['cleanup_reserve_calls']==36
    assert report['public_call_count']==len(report['calls'])<=128
    assert not any(uri.endswith('getMeters') or uri.endswith('setCursorTime') for uri,_,_ in client.calls)


@pytest.mark.parametrize('fault', ['reader', 'connection', 'cleanup'])
def test_additional_reader_failure_and_cleanup_remain_independent(tmp_path, monkeypatch, fault):
    context, _ = _additional_context(tmp_path, monkeypatch, fault=fault)
    workflow, runtime, client, _, _ = context
    with pytest.raises(AssertionError, match='Console playback/data probe incomplete') as caught:
        getattr(workflow, ADDITIONAL_NODE)(runtime)
    final = _finish(context, tmp_path, monkeypatch, [(ADDITIONAL_NODE, caught.value)])[-1]
    report = json.loads(Path(final['categories'][0]['observation_path']).read_bytes())
    assert final['invocation']['outcome'] == 'FAIL' and final['residual_state']['sandbox'] == 'quarantined'
    assert not report['complete'] and report['fixture_before'] == report['fixture_after']
    assert report['outcomes']['loaded_media']['outcome'] == 'PASS'
    assert sum(uri.endswith('transport.destroy') for uri, _, _ in client.calls) == 1
    assert sum(uri == PREFIX + 'stopCapture' for uri, _, _ in client.calls) == 1
    assert sum(uri == PREFIX + 'getCpuUsage' for uri, _, _ in client.calls) == 1
    if fault == 'cleanup':
        assert {row['outcome'] for row in report['outcomes'].values()} == {'PASS'}
        assert not report['cleanup']['complete'] and report['cleanup']['errors'][0]['action'] == 'stop-transport'
    else:
        assert report['cleanup']['complete']
        cpu = report['outcomes']['cpu']
        assert cpu['outcome'] == 'FAIL' and cpu['evidence']['gateway_results'][0]['ok'] is False
        for name, suffix in (('performance', 'getPerformanceMonitor'), ('streamed_media', 'getStreamedMedia')):
            assert report['outcomes'][name]['outcome'] == ('BLOCKED' if fault == 'connection' else 'PASS')
            assert sum(uri == PREFIX + suffix for uri, _, _ in client.calls) == (0 if fault == 'connection' else 1)
    executed = [call['argv'][1] for call in report['calls'] if call['argv'][0] == 'execute']
    assert len(executed) == len(set(executed))


@pytest.mark.parametrize('fault', ['row-bound', 'page-drift'])
def test_additional_incomplete_or_changed_retained_array_never_claims_complete(tmp_path, monkeypatch, fault):
    context, _ = _additional_context(tmp_path, monkeypatch, fault=fault)
    workflow, runtime, client, _, _ = context
    with pytest.raises(AssertionError, match='Console playback/data probe incomplete') as caught:
        getattr(workflow, ADDITIONAL_NODE)(runtime)
    final = _finish(context, tmp_path, monkeypatch, [(ADDITIONAL_NODE, caught.value)])[-1]
    report = json.loads(Path(final['categories'][0]['observation_path']).read_bytes())
    assert final['invocation']['outcome'] == 'FAIL' and report['cleanup']['complete']
    assert report['fixture_before'] == report['fixture_after']
    cpu = report['outcomes']['cpu']
    assert cpu['outcome'] == ('BLOCKED' if fault == 'row-bound' else 'FAIL')
    assert cpu['evidence']['complete'] is False
    assert cpu['evidence']['retained_page_calls'] == (0 if fault == 'row-bound' else 1)
    assert report['outcomes']['performance']['outcome'] == report['outcomes']['streamed_media']['outcome'] == 'PASS'
    assert sum(uri == PREFIX + 'getCpuUsage' for uri, _, _ in client.calls) == 1
    assert sum(uri.endswith('transport.destroy') for uri, _, _ in client.calls) == 1


@pytest.mark.parametrize('version', ['2021.1', '2022.1'])
def test_additional_console_reader_node_rejects_older_versions_before_dispatch(tmp_path, monkeypatch, version):
    workflow, runtime, client, _, _ = _console_context(tmp_path, monkeypatch, version=version)
    before = deepcopy(client.calls)
    with pytest.raises(AssertionError, match='Additional Console reader versions'):
        getattr(workflow, ADDITIONAL_NODE)(runtime)
    assert client.calls == before and runtime.category_results == []
    assert not (runtime.state_dir / 'console-additional-runtime-read-batch.json').exists()


CONTROL_NODE = 'test_console_owned_2025_meter_cursor_capture'


def _controls_context(tmp_path, monkeypatch, fault=None):
    context = _console_context(tmp_path, monkeypatch, 'cleanup' if fault == 'cleanup' else None)
    _, runtime, client, _, _ = context
    original = client.call
    bus_id = client.rows[CAPTURE_CAR_ID]['OutputBus']['id']

    def call(uri, args=None, options=None):
        if fault == 'stop-unknown' and uri == PREFIX + 'stopCapture':
            client.calls.append((uri, deepcopy(args), deepcopy(options)))
            raise RuntimeError('external capture stop outcome unknown; never retry')
        if uri in {PREFIX + suffix for suffix in ('registerMeter', 'unregisterMeter', 'getMeters', 'moveCursor', 'saveCapture')}:
            client.calls.append((uri, deepcopy(args), deepcopy(options)))
            if uri.endswith('getMeters'):
                row = client.rows[bus_id]
                return {'meters': [{'object': {key: deepcopy(row[key]) for key in options.get('return', ['id', 'name']) if key in row},
                    'source': 'Bus', 'configurationName': '1.0', 'configurationMask': 4,
                    'configurationType': 'Standard', 'channels': [{'name': 'C', 'value': -12.5}]}]}
            if uri.endswith('moveCursor'):
                client.user_time -= 10
                return {'return': client.user_time}
            if uri.endswith('saveCapture'):
                Path(args['file']).write_bytes(b'opaque external capture; no format claim')
            return {}
        if fault == 'cursor-unavailable' and uri == PREFIX + 'setCursorTime':
            client.calls.append((uri, deepcopy(args), deepcopy(options)))
            client.user_time = -1
            return {'return': -1}
        return original(uri, args, options)
    client.call = call
    return context


def test_console_meter_cursor_save_reaches_final_writer(tmp_path, monkeypatch):
    context = _controls_context(tmp_path, monkeypatch)
    workflow, runtime, client, _, _ = context
    getattr(workflow, CONTROL_NODE)(runtime)
    final = _finish(context, tmp_path, monkeypatch, [(CONTROL_NODE, None)])[-1]
    category, = final['categories']
    report = json.loads(Path(category['observation_path']).read_text())
    assert final['invocation']['outcome'] == 'PASS' and report['complete']
    assert {key: row['outcome'] for key, row in report['outcomes'].items()} == {
        'meters': 'PASS', 'cursor_set': 'PASS', 'cursor_move': 'PASS', 'capture_file': 'PASS'}
    assert report['outcomes']['cursor_set']['evidence']['returned_time_ms'] == 1500
    assert report['outcomes']['cursor_move']['evidence']['returned_time_ms'] == 1490
    assert report['outcomes']['meters']['evidence']['registration_membership_verified'] is False
    assert report['outcomes']['capture_file']['evidence']['file']['size'] > 0
    assert final['residual_state']['sandbox'] == 'deleted' and report['cleanup']['complete']
    uris = [uri for uri, _, _ in client.calls]
    for suffix in ('registerMeter', 'unregisterMeter', 'getMeters', 'setCursorTime', 'moveCursor', 'saveCapture', 'stopCapture'):
        assert uris.count(PREFIX + suffix) == 1
    assert uris.index(PREFIX + 'getMeters') < uris.index(PREFIX + 'stopCapture') < uris.index(PREFIX + 'setCursorTime')
    assert not any(uri.endswith(('getVoices', 'getBusses', 'getRTPCs')) for uri in uris)
    assert report['public_call_count'] < report['limits']['public_calls']
    assert report['fixture_before'] == report['fixture_after']


def test_unavailable_console_cursor_preserves_meter_and_saved_file(tmp_path, monkeypatch):
    context = _controls_context(tmp_path, monkeypatch, 'cursor-unavailable')
    workflow, runtime, client, _, _ = context
    with pytest.raises(AssertionError, match='Console playback/data probe incomplete') as caught:
        getattr(workflow, CONTROL_NODE)(runtime)
    final = _finish(context, tmp_path, monkeypatch, [(CONTROL_NODE, caught.value)])[-1]
    report = json.loads(Path(final['categories'][0]['observation_path']).read_text())
    assert final['invocation']['outcome'] == 'FAIL' and final['residual_state']['sandbox'] == 'quarantined'
    assert report['outcomes']['cursor_set']['outcome'] == report['outcomes']['cursor_move']['outcome'] == 'BLOCKED'
    assert report['outcomes']['cursor_set']['evidence']['transaction']['state'] == 'result_schema_checked'
    assert report['outcomes']['meters']['outcome'] == report['outcomes']['capture_file']['outcome'] == 'PASS'
    assert report['outcomes']['meters']['evidence']['gateway_result']['agent_result'] == report['outcomes']['meters']['evidence']['agent_result']
    assert report['cleanup']['complete'] and report['fixture_before'] == report['fixture_after']
    uris = [uri for uri, _, _ in client.calls]
    assert uris.count(PREFIX + 'setCursorTime') == uris.count(PREFIX + 'saveCapture') == 1
    assert PREFIX + 'moveCursor' not in uris


def test_unknown_console_capture_stop_is_not_replayed_or_reported_clean(tmp_path, monkeypatch):
    context = _controls_context(tmp_path, monkeypatch, 'stop-unknown')
    workflow, runtime, client, _, _ = context
    with pytest.raises(AssertionError, match='Console playback/data probe incomplete') as caught:
        getattr(workflow, CONTROL_NODE)(runtime)
    final = _finish(context, tmp_path, monkeypatch, [(CONTROL_NODE, caught.value)])[-1]
    report = json.loads(Path(final['categories'][0]['observation_path']).read_text())
    assert final['invocation']['outcome'] == 'FAIL' and final['residual_state']['sandbox'] == 'quarantined'
    assert report['mutation_outcome_unknown'] and not report['cleanup']['complete']
    assert report['cleanup']['errors'][0]['action'] == 'stop-capture'
    assert report['outcomes']['meters']['outcome'] == 'PASS'
    assert all(report['outcomes'][key]['outcome'] == 'BLOCKED' for key in ('cursor_set', 'cursor_move', 'capture_file'))
    uris = [uri for uri, _, _ in client.calls]
    assert uris.count(PREFIX + 'stopCapture') == 1
    assert uris.count(PREFIX + 'unregisterMeter') <= 1
    assert uris.count('ak.wwise.core.transport.destroy') == 1
    assert not any(uri == PREFIX + suffix for uri in uris for suffix in ('setCursorTime', 'moveCursor', 'saveCapture'))
    assert any(tx['state'] == 'indeterminate' for tx in final['transactions'])
