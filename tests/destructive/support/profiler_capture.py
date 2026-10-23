"""Owned 2024 meters and bounded 2025 capture/read observations.

This collector uses only the public Gateway. The existing Authoring batch owns
launch, source integrity, process cleanup, archival and final acceptance.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path
import wave
import uuid

from tests.semantic.support.typed_gateway_input import discovered_business_field_handle

NODEID = ('tests/destructive/test_authoring_ui_business_live.py::'
    'test_runtime_owned_2025_meter_cursor_capture')
METER_2024_NODEID = ('tests/destructive/test_authoring_ui_business_live.py::'
    'test_runtime_owned_2024_meter_projection')
READERS_2025_NODEID = ('tests/destructive/test_authoring_ui_business_live.py::'
    'test_runtime_owned_2025_profiler_readers')
CAPTURE_READS_NODEID = ('tests/destructive/test_authoring_ui_business_live.py::'
    'test_runtime_owned_profiler_capture_reads')
CAPTURE_MISSING_NODEID = ('tests/destructive/test_authoring_ui_business_live.py::'
    'test_runtime_owned_missing_profiler_reads')
CURSOR_MOVES_NODEID = ('tests/destructive/test_authoring_ui_business_live.py::'
    'test_runtime_owned_2025_profiler_cursor_moves')
CURSOR_MOVE_OUTCOMES = tuple('profiler-cursor-' + move + '-frame'
    for move in ('first', 'next', 'last', 'previous'))
METER_2024_SOUND_ID = '{DB017C8E-EC99-415B-93CF-F7A6136D1AC2}'
METER_2024_BUS_ID = '{06362E8D-5A32-497A-B063-3DA95963CE47}'
METER_2024_PARENT_ID = '{ED2BCAC8-D7B6-4448-8900-439B557894F4}'
METER_2024_MEDIA = 'Originals/SFX/Minigun/MnGn_Barrel_Loop.wav'
METER_2024_MEDIA_SOURCE = Path('/Applications/Audiokinetic/SampleProject2024.1.13.9056/SampleProject') / METER_2024_MEDIA
METER_2024_MEDIA_SHA256 = '637e45b1415306ab6833da81607a4d1405136830b7828a291fa8721806dccb7d'
SOUND_ID = '{FBF74BF9-8B83-44A8-AC8A-BA85372ECDC4}'
BUS_ID = '{8DD26D7F-389D-4487-B09F-5C675BF2E8D9}'
# Structural parent in the committed Busses WWU; Main Audio Bus is a sibling.
PARENT_ID = '{A74EEB4A-0805-4AFA-969C-53DCB862B550}'
OUTCOMES = ('profiler-meter-object-observation', 'profiler-cursor-snap-readback',
    'profiler-saved-capture-artifact', 'runtime-owned-log-add', 'runtime-owned-log-clear')
READER_OUTCOMES = ('profiler-voices-observation', 'profiler-busses-observation',
    'profiler-audio-objects-observation', 'profiler-game-objects-observation',
    'profiler-voice-instance-filter', 'profiler-bus-instance-filter', 'profiler-audio-objects-bus-filter')
CAPTURE_NODE_OUTCOMES = {NODEID: OUTCOMES, METER_2024_NODEID: OUTCOMES[:1],
    READERS_2025_NODEID: READER_OUTCOMES}
CAPTURE_READ_OUTCOMES = ('profiler-rtpcs-observation', 'profiler-contributions-dry-observation',
    'profiler-contributions-bus-observation', 'profiler-cpu-observation', 'profiler-loaded-media-observation',
    'profiler-performance-observation', 'profiler-streamed-media-observation')
CAPTURE_NODE_OUTCOMES[CAPTURE_READS_NODEID] = CAPTURE_READ_OUTCOMES
CAPTURE_NODE_OUTCOMES[CAPTURE_MISSING_NODEID] = (CAPTURE_READ_OUTCOMES[0], CAPTURE_READ_OUTCOMES[2])
CAPTURE_NODE_OUTCOMES[CURSOR_MOVES_NODEID] = CURSOR_MOVE_OUTCOMES
CAPTURE_CAR_ID = '{9EEFCC8E-7FC2-4CDC-8BE9-C682F2CA77CC}'
CAPTURE_CAR_SOURCE_ID = '{48770A4D-B8C3-41CF-AE3E-FB8651347736}'
CAPTURE_CAR_PARENT_ID = '{97A58685-6231-4227-9BAB-451E089615A8}'
CAPTURE_RPM_ID = '{63D15B0F-16E7-4B8A-B9CA-7BF10AD315B4}'
CAPTURE_CAR_MEDIA = 'Originals/SFX/Car Engine/Porsche_Outside_Idle_1000_01.wav'
CAPTURE_CAR_MEDIA_ID = 416741917
CAPTURE_CAR_SHA256 = '939e2d62dd820cb10ba571d769f7dbc0b5a3f170efaed94014e46df6f1e4038e'
CAPTURE_SAMPLE_ROOT = Path('/Applications/Audiokinetic')
PREFIX = 'ak.wwise.core.'


def capture_node_outcomes(nodeid, version):
    if nodeid == CAPTURE_MISSING_NODEID:
        return CAPTURE_NODE_OUTCOMES[nodeid][1:] if version == '2021.1' else CAPTURE_NODE_OUTCOMES[nodeid]
    if nodeid != CAPTURE_READS_NODEID:
        return CAPTURE_NODE_OUTCOMES[nodeid]
    basic = () if version == '2025.1' else tuple(name for name in READER_OUTCOMES
        if version != '2021.1' or name != READER_OUTCOMES[3])
    extra = CAPTURE_READ_OUTCOMES if version in ('2023.1', '2024.1', '2025.1') else CAPTURE_READ_OUTCOMES[:3]
    return (*basic, *extra, *(OUTCOMES[2:] if version in ('2023.1', '2024.1') else ()))


def capture_read_fixture(version):
    return CAPTURE_CAR_ID, None, CAPTURE_CAR_PARENT_ID, 'Outside_Idle_1000', None, CAPTURE_CAR_MEDIA


def stage_owned_capture_read_media(sandbox, io_root, *, version):
    """One attested existing original; 2022 explicitly uses common 2025 PCM."""
    from wwise_waapi.native_catalog import load_native_catalog
    from wwise_waapi.operation_soundbank import capture_file_proof, prove_artifact_path
    from wwise_waapi.filesystem_security import path_is_link_or_reparse
    build = '2025.1.7.9143' if version == '2022.1' else load_native_catalog(version, 'wwise-authoring')['provenance']['build']
    source_root = CAPTURE_SAMPLE_ROOT / ('SampleProject' + build) / 'SampleProject'
    source = source_root / CAPTURE_CAR_MEDIA
    before = capture_file_proof(source, field='attested existing Car original', io_root=source_root, max_bytes=16 * 1024 * 1024)
    assert before['sha256'] == CAPTURE_CAR_SHA256, 'Attested Car PCM differs'
    assert sandbox.sandbox_path.resolve(strict=True) != sandbox.source_root.resolve(strict=True)
    target = sandbox.sandbox_path / CAPTURE_CAR_MEDIA
    prove_artifact_path(target, field='owned Car original', io_root=sandbox.sandbox_path, expect_directory=False)
    assert not any(path_is_link_or_reparse(part) for part in (target, *target.parents)
        if part.exists() or part.is_symlink()), 'Car destination traverses a link'
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as stream:
        raw = stream.read(16 * 1024 * 1024 + 1)
    assert len(raw) == before['size'] and hashlib.sha256(raw).hexdigest() == CAPTURE_CAR_SHA256
    with target.open('xb') as stream:
        stream.write(raw)
    staged = capture_file_proof(target, field='owned staged Car original', io_root=sandbox.sandbox_path, max_bytes=16 * 1024 * 1024)
    after = capture_file_proof(source, field='attested existing Car original', io_root=source_root, max_bytes=16 * 1024 * 1024)
    assert before == after and staged['sha256'] == before['sha256']
    (io_root / 'capture-read-media.json').write_text(json.dumps({'source': before, 'staged': staged,
        'version': version, 'source_build': build, 'authored_xml_changed': False,
        'provenance': 'common attested PCM bound to committed 2022 source; not installed 2022 media evidence'
            if version == '2022.1' else 'matching installed original; existing committed source binding'}) + '\n', encoding='utf-8')


def _collect_readers(call, report, persist, *, fixed_time, sound_id, bus_id, seed_only=False):
    """One fixed frame, no live paging, replay or invented pipeline selectors."""
    report['reader_call_count'] = 0
    game_object = report['transport_association']['gameObject']
    observations = {}
    outcomes = report.setdefault('seed_observations', {}) if seed_only else report['outcomes']

    def seed_complete(name):
        observation = outcomes.get(name, {})
        evidence = observation.get('evidence', {})
        return (observation.get('outcome') == 'PASS' and evidence.get('complete') is True
            and evidence.get('observation_status') == 'PASS')

    def mixing_candidates(rows):
        if not seed_complete(READER_OUTCOMES[0]):
            return []
        owned_voices = [row for row in observations.get(READER_OUTCOMES[0], [])
            if row.get('gameObjectID') == game_object]
        if len(owned_voices) != 1 or owned_voices[0].get('objectGUID') != sound_id:
            return []
        return [i for i, row in enumerate(rows) if row.get('gameObjectID') == game_object
            and row.get('voiceCount') == 1 and isinstance(row.get('bus_instance_handle'), str)]

    def observe(name, argv, *, row_field='return', selected=None, identity_fields=()):
        report['reader_call_count'] += 1
        assert report['reader_call_count'] <= report['limits']['reader_calls'], 'Profiler reader call bound exceeded'
        evidence = {'position_ms': int(fixed_time), 'observation_status': 'BLOCKED',
            'owned_identity_observed': False}
        outcomes[name] = {'outcome': 'BLOCKED', 'evidence': evidence}
        try:
            payload = call(argv)
            result = payload['agent_result']
            evidence['agent_result'] = result  # Keep the exact Gateway projection.
            rows = result[row_field]
            assert isinstance(rows, list) and len(rows) <= 64, 'Profiler reader row bound exceeded'
            assert all(isinstance(row, dict) for row in rows), 'Malformed Profiler reader rows'
            ties = evidence['identity_ties'] = {
                'sound_row_indexes': [i for i, row in enumerate(rows) if row.get('objectGUID') == sound_id],
                'bus_row_indexes': [i for i, row in enumerate(rows)
                    if row.get('objectGUID') == bus_id or row.get('busGUID') == bus_id],
                'transport_game_object_row_indexes': [i for i, row in enumerate(rows)
                    if row.get('id' if row_field == 'game_objects' else 'gameObjectID') == game_object],
            }
            evidence['nonempty'] = bool(rows)
            evidence['complete'] = result.get('complete', not result.get('truncated', False)) is True
            relevant = ('sound_row_indexes',) if name in (READER_OUTCOMES[0], READER_OUTCOMES[4]) else (
                ('bus_row_indexes',) if name in (READER_OUTCOMES[1], READER_OUTCOMES[5]) else
                ('transport_game_object_row_indexes',) if name == READER_OUTCOMES[3] else
                ('bus_row_indexes', 'transport_game_object_row_indexes'))
            if report.get('capture_read_batch') and name in (READER_OUTCOMES[1], READER_OUTCOMES[5]):
                candidates = ties['mixing_bus_candidate_row_indexes'] = mixing_candidates(rows)
                ties['unique_owned_mixing_bus_row_indexes'] = candidates if len(candidates) == 1 else []
                relevant = ('unique_owned_mixing_bus_row_indexes',)
            evidence['owned_identity_observed'] = any(ties[key] for key in relevant)
            if not evidence['complete']:
                outcomes[name]['reason'] = 'Retained first page incomplete; no additional native read or paging scheduled'
            elif not rows:
                if report.get('capture_read_batch'):
                    evidence['observation_status'] = 'PASS'
                outcomes[name]['reason'] = 'No rows observed at the one fixed capture time'
            elif selected is not None and any(
                    any(row.get(key) != selected.get(key) for key in identity_fields) for row in rows):
                outcomes[name]['outcome'] = 'FAIL'
                outcomes[name]['reason'] = 'Filtered rows differ from the selected observed instance identity'
                evidence['observation_status'] = 'FAIL'
            else:
                evidence['observation_status'] = 'PASS'
                if evidence['owned_identity_observed']:
                    outcomes[name]['outcome'] = 'PASS'
                else:
                    outcomes[name]['reason'] = 'Nonempty rows observed, but no required owned Sound/Bus/GameObject association established'
            observations[name] = rows
        except Exception as exc:
            evidence['observation_status'] = 'FAIL'
            outcomes[name].update(outcome='FAIL', error={
                'type': type(exc).__name__, 'message': str(exc)[:4096]})
        finally:
            persist()

    def reader(suffix, *selection):
        return ['core-call', PREFIX + 'profiler.' + suffix, '--profiler-position', fixed_time,
            '--result-view', 'diagnostics', '--max-results', '64', *selection]

    observe(READER_OUTCOMES[0], reader('getVoices'))
    observe(READER_OUTCOMES[1], reader('getBusses'))
    if not seed_only:
        observe(READER_OUTCOMES[2], reader('getAudioObjects'))
        if report['version'] != '2021.1':
            observe(READER_OUTCOMES[3], ['profiler-game-objects', '--capture-ms', fixed_time], row_field='game_objects')

    # Prefer owned identities. If only unrelated rows exist, retain that truth
    # and use an actually issued instance; never assert fixture attribution.
    def select(name, handle, expected_guid):
        rows = [row for row in observations.get(name, []) if isinstance(row.get(handle), str)]
        if report.get('capture_read_batch') and not all(seed_complete(seed) for seed in READER_OUTCOMES[:2]):
            return None
        if report.get('capture_read_batch') and name == READER_OUTCOMES[1]:
            candidates = mixing_candidates(rows)
            return rows[candidates[0]] if len(candidates) == 1 else None
        return next((row for row in rows if row.get('objectGUID') == expected_guid), rows[0] if rows else None)

    voice = select(READER_OUTCOMES[0], 'voice_instance_handle', sound_id)
    bus = select(READER_OUTCOMES[1], 'bus_instance_handle', bus_id)
    if report.get('capture_read_batch'):
        report['runtime_mixing_bus'] = {'logical_output_bus_id': bus_id,
            'selected_observed_instance': bus,
            'logical_output_equals_runtime_bus': bus.get('objectGUID') == bus_id if bus else None,
            'association_boundary': 'Unique observed mixing pipeline on owned transport with isolated Car voice; no inferred logical-bus GUID equivalence or arbitrary path-order proof'}
        persist()
    if seed_only:
        return voice, bus
    for name, suffix, row, flag, keys in (
        (READER_OUTCOMES[4], 'getVoices', voice, 'voice_instance_handle', ('pipelineID', 'objectGUID', 'gameObjectID')),
        (READER_OUTCOMES[5], 'getBusses', bus, 'bus_instance_handle', ('pipelineID', 'objectGUID', 'gameObjectID')),
        (READER_OUTCOMES[6], 'getAudioObjects', bus, 'bus_instance_handle', ('gameObjectID',)),
    ):
        if row is None:
            outcomes[name] = {'outcome': 'BLOCKED', 'reason': (
                'No complete attributable Voices/Busses seeds for safe instance selection'
                if report.get('capture_read_batch') else 'Unfiltered read issued no usable instance handle'),
                'evidence': {'position_ms': int(fixed_time), 'observation_status': 'BLOCKED',
                    'owned_identity_observed': False}}
            persist()
            continue
        selected = row if suffix != 'getAudioObjects' else {
            'busPipelineID': row['pipelineID'], 'busGUID': row['objectGUID'], 'gameObjectID': row['gameObjectID']}
        if suffix == 'getAudioObjects':
            keys = ('busPipelineID', 'busGUID', 'gameObjectID')
        observe(name, reader(suffix, '--' + flag.replace('_', '-'), row[flag]),
            selected=selected, identity_fields=keys)
        outcomes[name]['evidence']['selected_observed_instance'] = row
        persist()
    return voice, bus


def _retained_cpu_rows(call, report, evidence, first, *, fixed_time):
    """Deliver one retained native snapshot; continuations never read Wwise."""
    pages = evidence['agent_result_pages'] = [first]
    rows = list(first['return'])
    total = first.get('total_count')
    snapshot = first.get('snapshot_sha256')
    handle = None
    while (not pages[-1].get('complete') and type(total) is int and total <= report['limits']['reader_rows']
            and 'row_fragment' not in pages[-1] and len(pages) < report['limits']['retained_cpu_pages']):
        prior = pages[-1]
        continuation = prior.get('next_command', {}).get('gateway_argv')
        assert (isinstance(continuation, list) and len(continuation) == 6
            and continuation[:3] == ['core-call', PREFIX + 'profiler.getCpuUsage', '--runtime-observation']
            and continuation[4] == '--runtime-page'
            and all(isinstance(value, str) for value in continuation)), 'Malformed retained CPU continuation'
        handle = handle or continuation[3]
        assert continuation[3] == handle, 'Retained CPU observation changed'
        payload = call(continuation)  # Copy the exact Gateway-owned continuation.
        assert payload.get('native_read_dispatched') is False and payload.get('retained_observation') is True
        page = payload['agent_result']
        pages.append(page)
        report['retained_page_call_count'] = report.get('retained_page_call_count', 0) + 1
        assert (page.get('snapshot_sha256') == snapshot and page.get('total_count') == total
            and page.get('profiler_position') == fixed_time), 'Retained CPU snapshot context changed'
        assert (page['page']['offset_from_end'] == prior['page']['next_offset_from_end']
            and page['page']['next_offset_from_end'] > page['page']['offset_from_end']
            and page['page']['next_offset_from_end'] - page['page']['offset_from_end'] == len(page['return'])
            and page.get('returned_count') == len(page['return'])
            and 'row_fragment' not in page), 'Retained CPU page gap, overlap or unsupported fragment'
        rows = [*page['return'], *rows]  # Newest ranges are delivered first.
        assert len(rows) <= 64 and all(isinstance(row, dict) for row in rows)
    complete = pages[-1].get('complete') is True and len(rows) == total
    evidence['rows_native_order'] = rows
    return rows, complete


def _collect_capture_reads(call, report, persist, *, fixed_time, sound_id, bus_id):
    voice, bus = _collect_readers(call, report, persist, fixed_time=fixed_time,
        sound_id=sound_id, bus_id=bus_id, seed_only=report['version'] == '2025.1' or report.get('missing_only', False))
    game_object = report['transport_association']['gameObject']

    def observe(name, argv, *, scope='owned-game-object', contribution=False):
        evidence = {'position_ms': int(fixed_time), 'observation_status': 'BLOCKED',
            'owned_identity_observed': False, 'attribution_scope': scope}
        observation = report['outcomes'][name] = {'outcome': 'BLOCKED', 'evidence': evidence}
        try:
            report['reader_call_count'] += 1
            assert report['reader_call_count'] <= report['limits']['reader_calls'], 'Profiler reader call bound exceeded'
            result = call(argv)['agent_result']
            evidence['agent_result'] = result
            rows = result.get('objects') if contribution else result['return']
            cpu_complete = None
            if name == CAPTURE_READ_OUTCOMES[3]:
                rows, cpu_complete = _retained_cpu_rows(call, report, evidence, result, fixed_time=fixed_time)
            if rows is None and contribution and result.get('contribution_reported') is False:
                rows = []
            assert isinstance(rows, list) and len(rows) <= (8192 if contribution else 64), 'Capture read row bound exceeded'
            assert all(isinstance(row, dict) for row in rows), 'Malformed capture rows'
            evidence['nonempty'] = bool(rows) or (contribution and result.get('contribution_reported') is True)
            if contribution:
                evidence['tree_nonempty'] = bool(rows)
            evidence['complete'] = result.get('complete', not result.get('truncated', False)) is True
            if cpu_complete is not None:
                evidence['complete'] = cpu_complete
            evidence['owned_game_object_row_indexes'] = [i for i, row in enumerate(rows)
                if row.get('gameObjectId') == game_object]
            evidence['owned_identity_observed'] = evidence['nonempty'] and (contribution or bool(evidence['owned_game_object_row_indexes']))
            if name == CAPTURE_READ_OUTCOMES[0]:
                evidence['rpm_read_row_indexes'] = [i for i, row in enumerate(rows)
                    if row.get('id') == CAPTURE_RPM_ID and row.get('name') == 'RPM'
                    and type(row.get('value')) in (int, float) and math.isfinite(row['value'])
                    and row.get('gameObjectId') in (game_object, (1 << 64) - 1)]
                evidence['owned_identity_observed'] = bool(evidence['rpm_read_row_indexes'])
                evidence['setter_effect_verified'] = False
                evidence['association_boundary'] = 'Actual owned/global RPM read with observed Car voice/committed curve; no setter effect or per-row Sound identity'
            if name == CAPTURE_READ_OUTCOMES[4]:
                evidence['source_media_id_row_indexes'] = [i for i, row in enumerate(rows)
                    if row.get('mediaId') == CAPTURE_CAR_MEDIA_ID]
                evidence['owned_identity_observed'] = bool(evidence['source_media_id_row_indexes'])
            if name == CAPTURE_READ_OUTCOMES[6]:
                evidence['owned_identity_observed'] = False
                evidence['association_boundary'] = 'Stream names have no established owned-media identity rule'
            if name in (CAPTURE_READ_OUTCOMES[4], CAPTURE_READ_OUTCOMES[6]):
                evidence['preparation_or_streaming_control_effect_verified'] = False
            if not evidence['complete']:
                observation['reason'] = 'Incomplete retained data or delivery bound reached; no additional native read'
            else:
                evidence['observation_status'] = 'PASS'
                if not evidence['nonempty']:
                    observation['reason'] = 'Valid empty capture observation; required nonempty data remains missing'
                elif evidence['owned_identity_observed'] or scope == 'capture':
                    observation['outcome'] = 'PASS'
                else:
                    observation['reason'] = 'Nonempty observation retained; required owned association remains unestablished'
        except Exception as exc:
            evidence['observation_status'] = 'FAIL'
            observation.update(outcome='FAIL', error={'type': type(exc).__name__, 'message': str(exc)[:4096]})
        finally:
            persist()

    def row_read(name, suffix, scope):
        observe(name, ['core-call', PREFIX + 'profiler.' + suffix, '--profiler-position', fixed_time,
            '--max-results', '64'], scope=scope)

    if CAPTURE_READ_OUTCOMES[0] in report['outcomes']:
        row_read(CAPTURE_READ_OUTCOMES[0], 'getRTPCs', 'owned-rtpc-read')
    for name, use_bus in ((CAPTURE_READ_OUTCOMES[1], False), (CAPTURE_READ_OUTCOMES[2], True)):
        if name not in report['outcomes']:
            continue
        valid = (voice is not None and voice.get('objectGUID') == sound_id
            and voice.get('gameObjectID') == game_object and (not use_bus or bus is not None
                and bus.get('gameObjectID') == game_object))
        if not valid:
            report['outcomes'][name] = {'outcome': 'BLOCKED', 'reason': 'No safe owned voice/Bus selection from complete seed observations',
                'evidence': {'position_ms': int(fixed_time), 'observation_status': 'BLOCKED', 'owned_identity_observed': False}}
            persist()
            continue
        argv = ['profiler-voice-contributions', '--capture-ms', fixed_time,
            '--voice-instance-handle', voice['voice_instance_handle']]
        if use_bus:
            argv += ['--bus-instance-handle', bus['bus_instance_handle']]
        observe(name, argv, scope='owned-voice-path', contribution=True)
    if report['version'] in ('2023.1', '2024.1', '2025.1'):
        for name, suffix, scope in (
            (CAPTURE_READ_OUTCOMES[3], 'getCpuUsage', 'capture'),
            (CAPTURE_READ_OUTCOMES[4], 'getLoadedMedia', 'capture'),
            (CAPTURE_READ_OUTCOMES[5], 'getPerformanceMonitor', 'capture'),
            (CAPTURE_READ_OUTCOMES[6], 'getStreamedMedia', 'capture'),
        ):
            if name in report['outcomes']:
                row_read(name, suffix, scope)


def stage_owned_2024_meter_media(sandbox, io_root):
    """Supply one omitted original in the owned copy; authored XML is untouched."""
    from wwise_waapi.filesystem_security import path_is_link_or_reparse
    from wwise_waapi.operation_soundbank import capture_file_proof, prove_artifact_path
    source = METER_2024_MEDIA_SOURCE
    before = capture_file_proof(source, field='matching installed 2024 original',
        io_root=source.parents[2], max_bytes=16 * 1024 * 1024)
    assert before['sha256'] == METER_2024_MEDIA_SHA256, 'Matching installed 2024 original differs'
    assert sandbox.sandbox_path.resolve(strict=True) != sandbox.source_root.resolve(strict=True)
    target = sandbox.sandbox_path / METER_2024_MEDIA
    prove_artifact_path(target, field='owned 2024 original destination', io_root=sandbox.sandbox_path,
        expect_directory=False)
    assert not any(path_is_link_or_reparse(part) for part in (target, *target.parents)
        if part.exists() or part.is_symlink()), '2024 media destination traverses a link'
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as original:
        raw = original.read(16 * 1024 * 1024 + 1)
    assert len(raw) == before['size'] and hashlib.sha256(raw).hexdigest() == METER_2024_MEDIA_SHA256
    with target.open('xb') as output:
        output.write(raw)
    staged = capture_file_proof(target, field='owned staged 2024 original',
        io_root=sandbox.sandbox_path, max_bytes=16 * 1024 * 1024)
    after = capture_file_proof(source, field='matching installed 2024 original',
        io_root=source.parents[2], max_bytes=16 * 1024 * 1024)
    assert after == before and staged['sha256'] == before['sha256'], '2024 original changed during staging'
    (io_root / 'profiler-meter-media.json').write_text(json.dumps({'source': before, 'staged': staged,
        'authored_xml_changed': False, 'scope': 'One existing missing original copied only into owned sandbox'}) + '\n')


def _collect_cursor_moves(call, report, persist, *, effect, zero, own, clean_one):
    """One stopped buffer; each source-defined move executes exactly once."""
    report['setup'].append({'originals': effect('transport.useOriginals', ['--audition-media', 'originals'])})
    report['setup'].append({'enable_voices': effect('profiler.enableProfilerData', ['--capture-data', 'voices', 'enable'],
        before_execute=lambda: own('disable-voices-data',
            lambda: effect('profiler.enableProfilerData', ['--capture-data', 'voices', 'disable'])))})
    report['setup'].append({'start_capture': zero('profiler.startCapture',
        before_execute=lambda: own('stop-capture', lambda: zero('profiler.stopCapture')))})
    created = effect('transport.create', role='target', identity=SOUND_ID)
    handle = created['agent_result']['business_result']['transport_handle']
    own('destroy-transport', lambda: effect('transport.destroy', ['--transport-handle', handle]))
    own('stop-transport', lambda: effect('transport.executeAction', ['--audition-action', 'stop',
        '--transport-scope', 'one-transport', '--transport-handle', handle]))
    report['setup'].append({'create_transport': created})
    report['setup'].append({'play': effect('transport.executeAction', ['--audition-action', 'play',
        '--transport-scope', 'one-transport', '--transport-handle', handle])})
    # Same fixed capture interval as the existing fixture, never a retry/poll loop.
    time.sleep(0.25)
    report['setup'].append({'stop_capture': clean_one('stop-capture')})
    position = call(['core-call', PREFIX + 'profiler.getCursorTime', '--profiler-cursor', 'capture-latest'])['agent_result']
    report['capture_position'] = position
    for name, move in zip(CURSOR_MOVE_OUTCOMES, ('first', 'next', 'last', 'previous')):
        observation = report['outcomes'][name] = {'outcome': 'BLOCKED', 'evidence': {
            'cursor_move': move + '-frame', 'capture_data_completeness_verified': False}}
        evidence = observation['evidence']
        try:
            verified = effect('profiler.moveCursor', ['--cursor-move', move + '-frame'])
            evidence['transaction'] = verified
            scope = verified['verification']['verification_scope']['cursor_observation']
            evidence.update(returned_time_ms=scope['returned_time_ms'], observed_time_ms=scope['observed_time_ms'])
            if scope['outcome'] == 'unavailable':
                observation['reason'] = 'Returned or independent user-cursor time unavailable; no retry'
            else:
                assert verified['verification']['business_state_verified'] is True and scope['outcome'] == 'matched', verified
                assert type(scope['returned_time_ms']) is int and scope['returned_time_ms'] >= 0
                assert scope['returned_time_ms'] == scope['observed_time_ms']
                observation['outcome'] = 'PASS'
        except Exception as exc:
            observation.update(outcome='FAIL', error={'type': type(exc).__name__, 'message': str(exc)[:4096]})
        finally:
            persist()

    first, next_frame, last, previous = (report['outcomes'][name] for name in CURSOR_MOVE_OUTCOMES)
    if last['outcome'] == 'PASS':
        if position.get('available') is not True:
            last.update(outcome='BLOCKED', reason='Stopped capture cursor unavailable; endpoint not established')
        elif last['evidence']['returned_time_ms'] != position['position_ms']:
            last.update(outcome='FAIL', reason='Last frame differs from stopped capture-latest cursor')
    endpoints = first['outcome'] == last['outcome'] == 'PASS'
    low = first['evidence'].get('returned_time_ms')
    high = last['evidence'].get('returned_time_ms')
    if endpoints and low > high:
        first.update(outcome='FAIL', reason='First captured frame follows last captured frame')
        endpoints = False
    for observation, forward in ((next_frame, True), (previous, False)):
        if observation['outcome'] != 'PASS':
            continue
        if not endpoints or low == high:
            observation.update(outcome='BLOCKED', reason='Insufficient distinct endpoint observations for frame relationship')
        else:
            value = observation['evidence']['returned_time_ms']
            valid = low < value <= high if forward else low <= value < high
            observation['evidence']['frame_relationship_verified'] = valid
            if not valid:
                observation.update(outcome='FAIL', reason='Observed cursor violates source-defined next/previous frame relationship')
    report['frame_relationship_scope'] = {
        'first_time_ms': low, 'last_time_ms': high,
        'first_frame_boundary': 'Source-defined first frame; no independent earliest-time API or first=0 assumption',
        'distinct_endpoint_times_observed': endpoints and low < high,
        'adjacent_frame_index_or_duration_verified': False}
    persist()


def collect_owned_capture(batch, public_call):
    version = batch.runtime.version
    cursor_moves = batch.selected_nodeids == (CURSOR_MOVES_NODEID,)
    if cursor_moves:
        assert version == '2025.1', 'Cursor moves require the matching 2025 Authoring host'
    missing_only = batch.selected_nodeids == (CAPTURE_MISSING_NODEID,)
    capture_reads = missing_only or batch.selected_nodeids == (CAPTURE_READS_NODEID,)
    assert version in (('2021.1', '2022.1', '2023.1', '2024.1', '2025.1') if capture_reads
        else ('2024.1', '2025.1')), 'Capture version is not admitted for this node'
    readers = capture_reads or batch.selected_nodeids == (READERS_2025_NODEID,)
    nodeid = CURSOR_MOVES_NODEID if cursor_moves else CAPTURE_MISSING_NODEID if missing_only else CAPTURE_READS_NODEID if capture_reads else READERS_2025_NODEID if readers and version == '2025.1' else METER_2024_NODEID if version == '2024.1' else NODEID
    assert batch.selected_nodeids == (nodeid,), 'Capture requires its exact matching node'
    sound_id, bus_id, parent_id = (METER_2024_SOUND_ID, METER_2024_BUS_ID, METER_2024_PARENT_ID) if version == '2024.1' else (SOUND_ID, BUS_ID, PARENT_ID)
    parent_output, parent_key = ('volume-db', 'volume_db') if version == '2024.1' else ('work-unit-is-default', 'work_unit_is_default')
    sound_name, bus_name, media_relative = ('MnGn_Barrel_Loop', 'Guns', METER_2024_MEDIA) if version == '2024.1' else (
        'RFL_Tail', 'WAAPI_V2_Weapons', 'Originals/SFX/WAAPI Skill Integration V2/audit_tail.wav')
    parent_fields = ['--include', parent_output]
    if capture_reads:
        sound_id, bus_id, parent_id, sound_name, bus_name, media_relative = capture_read_fixture(version)
        parent_fields = []
    destination = Path(batch.node_runtimes[nodeid].runner_environment['WWISE_EVIDENCE_DIR'])
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / 'profiler-capture.json'
    report = {'contract': 'waapi-skill.owned-profiler-capture/v1', 'candidate': batch.candidate,
        'host': batch.info, 'version': version, 'complete': False, 'setup': [], 'errors': [],
        'outcomes': {name: {'outcome': 'BLOCKED', 'reason': 'shared setup incomplete'} for name in capture_node_outcomes(nodeid, version)},
        'cleanup': {'complete': False, 'receipts': [], 'errors': [],
            'capture_settings_prior_state_restored': False,
            'audition_media_prior_state_restored': False,
            'capture_settings_scope': 'Explicit enable/disable pair only; no prior global settings getter'},
        'limits': {'public_calls': 192, 'total_reply_bytes': 8 * 1024 * 1024,
            'reply_bytes': 1024 * 1024, 'meter_pages': 8}, 'public_call_count': 0, 'total_reply_bytes': 0}
    if readers:
        report['limits'].update(reader_calls=7, reader_rows=64)
        report['scope'] = 'One owned 2025.1 capture; no 2021.1–2024.1 reader evidence or acoustic proof'
    if capture_reads:
        report['capture_read_batch'] = True
        report['limits']['retained_cpu_pages'] = 8
        report['limits']['reader_calls'] = {'2021.1': 9, '2022.1': 10, '2023.1': 14, '2024.1': 14, '2025.1': 9}[version]
        report['scope'] = 'Only missing read observations at one capture time; no acoustic or missing-version credit'
    if missing_only:
        report['missing_only'] = True
        report['limits']['reader_calls'] = 3 if version == '2021.1' else 4
        report['scope'] = 'Only selected missing reads at this new capture; historical native facts are separate and #186 remains incomplete'
        report['reused_capture_evidence'] = {'candidate': 'a5884dcbb655d03a4537ed1e3553ac01e1d2fdb8',
            'root': 'r104-capture-reads-native-' + version[:4] + '-r1',
            'capture_time_ms': {'2021.1': 34752, '2022.1': 39861, '2023.1': 45888,
                '2024.1': 45621, '2025.1': 46869}[version],
            'original_verdict': 'FAIL', 'boundary': 'Separate retained facts; not measurements at this new capture time'}
        report['remaining_same_parent_obligations'] = {
            'profiler-loaded-media-observation': ['2023.1', '2024.1', '2025.1']}

    cleanup_active = False
    if cursor_moves:
        report['scope'] = 'Four 2025.1 user-cursor moves on one stopped capture; no acoustic or capture-content completeness proof'
        report['limits'].update(public_calls=128, cleanup_reserve_calls=30,
            cleanup_reserve_reply_bytes=2 * 1024 * 1024)

    def persist():
        raw = (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode()
        assert len(raw) <= 1024 * 1024, 'Capture report byte bound exceeded'
        temporary = path.with_suffix('.tmp'); temporary.write_bytes(raw); temporary.replace(path)

    def call(argv):
        reserve = report['limits'].get('cleanup_reserve_calls', 0) if not cleanup_active else 0
        assert report['public_call_count'] < report['limits']['public_calls'] - reserve, 'Capture public call bound exceeded'
        if cursor_moves and not cleanup_active:
            assert report['total_reply_bytes'] + report['limits']['reply_bytes'] <= (
                report['limits']['total_reply_bytes'] - report['limits']['cleanup_reserve_reply_bytes']), 'Capture cleanup byte reserve unavailable'
        report['public_call_count'] += 1
        try:
            result = public_call(argv)
            size = len(json.dumps(result, ensure_ascii=False).encode())
            report['total_reply_bytes'] += size
            assert size <= report['limits']['reply_bytes'] and report['total_reply_bytes'] <= report['limits']['total_reply_bytes']
            return result
        finally:
            persist()

    def exact(identity, *fields):
        result = call(['query-object', '--exact-id', identity, *fields])
        assert result['count'] == 1 and result.get('projection_complete') is not False, result
        row, = result['objects']
        assert row['id'] == identity and all(isinstance(row[key], str) and row[key] for key in ('name', 'type', 'path')), row
        return row

    def draft(operation, fields, *, role=None, identity=None, field_meaning=None, field_choice=None):
        started = call(['draft-start', operation])
        current, authority = started['draft'], started['task_authority']
        draft_id = current['draft_id']
        def step(command, values=()):
            nonlocal current
            result = call([command, draft_id, '--task-authority', authority,
                '--expected-revision', str(current['revision']), *values])
            current = result.get('draft', current)
            return result
        arguments = list(fields)
        if identity:
            bound = step('draft-bind-object', [*(['--role', role] if role else []), '--object-id', identity])
            handle = bound['bound_object']['handle']
            if field_meaning:
                discovered = step('draft-discover-fields', ['--object-handle', handle, '--meaning', field_meaning])
                field_handle = discovered_business_field_handle(discovered, field_meaning)
                if field_choice is not None:
                    candidates = discovered.get('field_candidates', []) or [candidate
                        for row in discovered.get('meaning_results', []) for candidate in row.get('candidates', [])]
                    candidate, = [row for row in candidates if row['handle'] == field_handle]
                    value_input = candidate['value_input']
                    value, label = field_choice
                    assert value_input['type'] == 'integer', candidate
                    choices = [row for row in value_input.get('choices', [])
                        if type(row.get('value')) is int and row['value'] == value
                        and (label is None or label in row.get('labels', []))]
                    assert len(choices) == 1, ('Required source-backed choice not uniquely disclosed by live metadata', field_meaning, field_choice)
                    arguments = ['--business-value', choices[0]['input']]
                step('draft-declare-field-change', ['--object-handle', handle, '--field-handle', field_handle, *arguments])
            else:
                step('draft-declare-runtime-control-plan', ['--' + role.replace('_', '-') + '-handle', handle, *arguments])
        else:
            step('draft-declare-runtime-control-plan', arguments)
        step('draft-check')
        return step('preview-from-draft')

    def execute(preview, *, before_execute=None):
        tx = preview['transaction_id']
        shown = call(['transaction-show', tx])
        call(['confirm', tx, '--confirmation-token', shown['confirmation']['token']])
        if before_execute:
            before_execute()
        executed = call(['execute', tx])
        assert executed['state'] == 'executed_unverified', executed
        verified = call(['verify', tx])
        return verified

    def effect(suffix, fields=(), *, role=None, identity=None, before_execute=None):
        return execute(draft(PREFIX + suffix, fields, role=role, identity=identity), before_execute=before_execute)

    def zero(suffix, *, before_execute=None):
        schema = call(['request-schema', PREFIX + suffix])
        return execute(call(schema['continuation']['gateway_argv']), before_execute=before_execute)

    def set_loop(value, *, before_execute=None):
        result = execute(draft('object.setProperty', ['--business-value', json.dumps(value)],
            identity=sound_id, field_meaning='IsLoopingEnabled'), before_execute=before_execute)
        assert result['verification']['business_state_verified'] is True, result
        return result

    def set_stream(value, *, before_execute=None):
        result = execute(draft('object.setProperty', ['--business-value', json.dumps(value)],
            identity=sound_id, field_meaning='IsStreamingEnabled'), before_execute=before_execute)
        assert result['verification']['business_state_verified'] is True, result
        return result

    def set_bus_configuration(value, *, label=None, before_execute=None):
        result = execute(draft('object.setProperty', [], identity=bus_id,
            field_meaning='BusChannelConfig', field_choice=(value, label)), before_execute=before_execute)
        assert result['verification']['business_state_verified'] is True, result
        return result

    def outcome(name, operation):
        try:
            report['outcomes'][name] = {'outcome': 'PASS', 'evidence': operation()}
        except Exception as exc:
            report['outcomes'][name] = {'outcome': 'FAIL', 'error': {'type': type(exc).__name__, 'message': str(exc)[:4096]}}
        finally:
            persist()

    cleanup = []
    def own(label, action):
        cleanup.append((label, action))

    def clean_one(label):
        nonlocal cleanup_active
        pending = [(name, action) for name, action in cleanup if name == label]
        assert len(pending) == 1, ('Cleanup ownership unavailable', label)
        name, action = pending[0]
        cleanup.remove(pending[0])
        previous_cleanup = cleanup_active
        cleanup_active = True
        try:
            result = action()
        except Exception as exc:
            report['cleanup']['errors'].append({'action': name, 'type': type(exc).__name__, 'message': str(exc)[:4096]})
            persist()
            raise
        finally:
            cleanup_active = previous_cleanup
        report['cleanup']['receipts'].append({'action': name, 'result': result})
        persist()
        return result

    def finish():
        nonlocal cleanup_active
        cleanup_active = True
        for label, action in reversed(cleanup):
            try:
                report['cleanup']['receipts'].append({'action': label, 'result': action()})
            except Exception as exc:
                report['cleanup']['errors'].append({'action': label, 'type': type(exc).__name__, 'message': str(exc)[:4096]})
            persist()
        try:
            if 'fixture_before' in report:
                after = {'sound': exact(sound_id, *looping),
                    'bus': exact(bus_id, *bus_fields),
                    'parent': exact(parent_id, *parent_fields)}
                if capture_reads and 'source' in report['fixture_before']:
                    after.update(source=exact(CAPTURE_CAR_SOURCE_ID))
                report['fixture_after'] = after
                assert after == report['fixture_before'], 'Owned Sound/bus/parent values changed after cleanup'
        except Exception as exc:
            report['cleanup']['errors'].append({'action': 'fixture-preservation', 'type': type(exc).__name__, 'message': str(exc)[:4096]})
        report['cleanup']['complete'] = not report['cleanup']['errors']
        report['complete'] = (not report['errors'] and report['cleanup']['complete']
            and all(row['outcome'] == 'PASS' for row in report['outcomes'].values()))
        persist()

    if cursor_moves:
        persist()
        try:
            _collect_cursor_moves(call, report, persist, effect=effect, zero=zero,
                own=own, clean_one=clean_one)
        except Exception as exc:
            report['errors'].append({'type': type(exc).__name__, 'message': str(exc)[:4096]})
        finally:
            finish()
        assert report['complete'], report
        return

    persist()
    try:
        from wwise_waapi.operation_soundbank import capture_file_proof
        media = batch.runtime.sandbox.sandbox_path / media_relative
        proof = capture_file_proof(media, field='owned integration audio', io_root=batch.runtime.owned_root,
            max_bytes=16 * 1024 * 1024)
        with wave.open(str(media)) as source:
            assert source.getnframes() > 0 and source.getframerate() > 0
            duration = source.getnframes() / source.getframerate()
        report['fixture_media'] = {'proof': proof, 'duration_seconds': duration,
            'source_scope': ('One staged matching 2024 original; no authored XML/source edits' if version == '2024.1' else 'Existing integration-v2 audit_tail.wav; no source/media edits')}
        if capture_reads:
            staging = json.loads((batch.runtime.io_root / 'capture-read-media.json').read_text())
            assert all(proof[key] == staging['staged'][key] for key in ('path', 'sha256', 'size'))
            report['fixture_media'].update(staging=staging, source_scope=staging['provenance'], media_id=CAPTURE_CAR_MEDIA_ID)
        elif version == '2024.1':
            staging = json.loads((batch.runtime.io_root / 'profiler-meter-media.json').read_text())
            assert proof['sha256'] == staging['source']['sha256'] == staging['staged']['sha256'] == METER_2024_MEDIA_SHA256
            report['fixture_media']['staging'] = staging
        looping = ['--include-field', 'IsLoopingEnabled', '--include-field', 'IsLoopingInfinite']
        if version == '2024.1' or readers:
            looping += ['--include', 'output-bus']
        if capture_reads:
            looping += ['--include', 'parent', '--include', 'override-output', '--include', 'active-source',
                '--include-field', 'IsStreamingEnabled']
            if version == '2021.1':
                looping += ['--platform', 'Mac', '--language', 'SFX', '--max-results', '1']
        original = exact(sound_id, *looping)
        assert original['name'] == sound_name and original['type'] == 'Sound', original
        props = original.get('properties', {})
        assert type(props.get('IsLoopingEnabled')) is bool and props.get('IsLoopingInfinite') is True, (
            'Owned fixture requires live boolean loop values and already-infinite mode', original)
        if version == '2024.1' and not capture_reads:
            assert props['IsLoopingEnabled'] is True and original.get('output_bus', {}).get('id') == bus_id, original
        if capture_reads:
            bus_id = original.get('output_bus', {}).get('id')
            assert isinstance(bus_id, str) and bus_id, 'Effective OutputBus reference unavailable'
            assert original['parent']['id'] == parent_id and original['active_source']['id'] == CAPTURE_CAR_SOURCE_ID
        elif readers:
            assert original.get('output_bus', {}).get('id') == bus_id, original
        bus_fields = ['--include', 'volume-db', '--include', 'parent']
        if version == '2024.1' and not capture_reads:
            bus_fields += ['--include-field', 'BusChannelConfig']
        before_bus = exact(bus_id, *bus_fields)
        before_parent = exact(parent_id, *parent_fields)
        assert before_bus['type'] == 'Bus' and (capture_reads or before_bus['name'] == bus_name), before_bus
        if not capture_reads:
            assert before_bus['parent']['id'] == parent_id, before_bus
        assert before_parent['type'] == ('BlendContainer' if capture_reads else 'Bus' if bus_name == 'Guns' else 'WorkUnit'), before_parent
        if not capture_reads:
            assert type(before_parent.get(parent_key)) in ((int, float) if version == '2024.1' else (bool,)), before_parent
        report['fixture_before'] = {'sound': original, 'bus': before_bus, 'parent': before_parent}
        if capture_reads:
            source = exact(CAPTURE_CAR_SOURCE_ID)
            assert source['type'] == 'AudioFileSource'
            report['fixture_before'].update(source=source)
            streaming = props.get('IsStreamingEnabled')
            assert type(streaming) is bool
            if not streaming and not missing_only:
                report['setup'].append({'enable_streaming': set_stream(True,
                    before_execute=lambda: own('restore-streaming', lambda: set_stream(False)))})
        if version == '2024.1' and not capture_reads:
            original_configuration = before_bus.get('properties', {}).get('BusChannelConfig')
            assert type(original_configuration) is int and original_configuration == 0, before_bus
            # Matching 2024 WObjects: 0=Same as parent, 12546=2.0. Authoring
            # Help ch34s11s01: explicit channel configuration makes a bus mix;
            # non-mixing buses have no meter. Live disclosure must match first.
            report['setup'].append({'bus_processing': set_bus_configuration(12546, label='2.0',
                before_execute=lambda: own('restore-bus-configuration',
                    lambda: set_bus_configuration(original_configuration)))})
        # The matching WObjects.xml defines Loop Enable as bool, default false;
        # Infinite defaults true and requires Enable. Fresh Draft discovery owns
        # actual metadata before the one changed flag; never write a disabled child.
        if not props['IsLoopingEnabled']:
            report['setup'].append({'loop_enabled': set_loop(True,
                before_execute=lambda: own('restore-loop-enabled', lambda: set_loop(False)))})
        if version in ('2023.1', '2024.1', '2025.1'):
            report['setup'].append({'originals': effect('transport.useOriginals', ['--audition-media', 'originals'])})
        if capture_reads and not missing_only and version != '2021.1':
            report['setup'].append({'prepare': effect('transport.prepare', role='target', identity=sound_id)})
        if capture_reads:
            data_sets = ('voices', 'voice-inspector', *(() if version == '2021.1' else ('game-syncs',)),
                *(() if version == '2025.1' or missing_only else ('audio-objects',)),
                *(('cpu', 'loaded-media', 'streaming') if not missing_only and version in ('2023.1', '2024.1', '2025.1') else ()))
            def data_changes(outcome):
                return [value for data in data_sets for value in ('--capture-data', data, outcome)]
            report['setup'].append({'enable_capture_reads': effect('profiler.enableProfilerData', data_changes('enable'),
                before_execute=lambda: own('disable-capture-read-data',
                    lambda: effect('profiler.enableProfilerData', data_changes('disable'))))})
        elif readers:
            for data in ('voices', 'audio-objects'):
                report['setup'].append({'enable_' + data: effect('profiler.enableProfilerData', ['--capture-data', data, 'enable'],
                    before_execute=lambda data=data: own('disable-' + data + '-data',
                        lambda: effect('profiler.enableProfilerData', ['--capture-data', data, 'disable'])))})
        else:
            report['setup'].append({'enable_meters': effect('profiler.enableProfilerData', ['--capture-data', 'meters', 'enable'],
                before_execute=lambda: own('disable-meters-data', lambda: effect('profiler.enableProfilerData', ['--capture-data', 'meters', 'disable'])))})
            report['setup'].append({'register_meter': effect('profiler.registerMeter', role='meter_object', identity=bus_id,
                before_execute=lambda: own('unregister-meter', lambda: effect('profiler.unregisterMeter', role='meter_object', identity=bus_id)))})
        report['setup'].append({'start_capture': zero('profiler.startCapture',
            before_execute=lambda: own('stop-capture', lambda: zero('profiler.stopCapture')))})
        created = effect('transport.create', role='target', identity=sound_id)
        handle = created['agent_result']['business_result']['transport_handle']
        own('destroy-transport', lambda: effect('transport.destroy', ['--transport-handle', handle]))
        own('stop-transport', lambda: effect('transport.executeAction', ['--audition-action', 'stop',
            '--transport-scope', 'one-transport', '--transport-handle', handle]))
        report['setup'].append({'create_transport': created})
        report['setup'].append({'play': effect('transport.executeAction', ['--audition-action', 'play',
            '--transport-scope', 'one-transport', '--transport-handle', handle])})
        if readers:
            state = call(['core-call', PREFIX + 'transport.getState', '--transport-handle', handle])['agent_result']
            assert state['state'] == 'playing', state
            report['transport_playing_observation'] = state
            membership = call(['request-schema', PREFIX + 'transport.getList'])['continuation']['gateway_argv']
            rows = call(membership)['agent_result']['list']
            association, = [row for row in rows if row['object'] == sound_id]
            report['transport_association'] = association
        time.sleep(0.25)
        position = call(['core-call', PREFIX + 'profiler.getCursorTime', '--profiler-cursor', 'capture-latest'])['agent_result']
        assert position['available'] is True and position['position_ms'] >= 0, position
        report['capture_position'] = position
        fixed_time = str(position['position_ms'])

        def meters():
            payload = call(['core-call', PREFIX + 'profiler.getMeters', '--profiler-position', fixed_time,
                '--max-results', '64', '--meter-object-include', 'volume-db',
                '--meter-object-include-related', 'parent', parent_output])
            pages = [payload['agent_result']]
            while not pages[-1]['complete']:
                assert len(pages) < report['limits']['meter_pages'], 'Meter page bound exceeded'
                pages.append(call(pages[-1]['next_command']['gateway_argv'])['agent_result'])
            rows = [row for page in pages for row in page['meters']]
            observed = [row for row in rows if row['object'].get('id') == bus_id]
            assert observed, 'Non-default registered bus missing from actual meter frame'
            for row in observed:
                obj = row['object']
                assert all(obj[key] == before_bus[key] for key in ('id', 'name', 'type', 'path')), obj
                assert obj['volume_db'] == before_bus['volume_db'], obj
                parent = obj['related']['parent']
                assert parent['object']['id'] == parent_id and parent['object']['name'] == before_parent['name'], parent
                assert type(parent.get(parent_key)) in ((int, float) if version == '2024.1' else (bool,)) and parent[parent_key] == before_parent[parent_key], parent
                assert isinstance(row['source'], str) and row['source'], row
                assert isinstance(row['configurationName'], str) and row['configurationName']
                assert isinstance(row['configurationType'], str) and row['configurationType']
                assert type(row['configurationMask']) is int and row['configurationMask'] >= 0
                assert row['channels'] and all(isinstance(channel.get('name'), str) and channel['name']
                    and type(channel.get('value')) in (int, float) and math.isfinite(channel['value']) for channel in row['channels']), row
            return {'position_ms': position['position_ms'], 'meters': observed, 'page_count': len(pages),
                'capture_frame_not_current_authoring_values': ['source', 'configurationName', 'configurationMask', 'configurationType', 'channels'],
                'nested_authoring_values': ['identity', 'volume_db', 'related.parent'], 'nonzero_audio_level_claimed': False}
        if capture_reads:
            _collect_capture_reads(call, report, persist, fixed_time=fixed_time, sound_id=sound_id, bus_id=bus_id)
        elif readers:
            _collect_readers(call, report, persist, fixed_time=fixed_time, sound_id=sound_id, bus_id=bus_id)
        else:
            outcome(OUTCOMES[0], meters)
        # Freeze capture before independent cursor/file assertions. Each control
        # executes at most once; cleanup never repeats an attempted stop.
        report['setup'].append({'stop_capture': clean_one('stop-capture')})
        optional_effects = False
        if capture_reads and not missing_only and version in ('2023.1', '2024.1'):
            budget = report['optional_effect_budget'] = {'calls_before': report['public_call_count'],
                'effect_calls': 29, 'cleanup_reserve_calls': 52}
            optional_effects = budget['admitted'] = budget['calls_before'] + 29 + 52 <= report['limits']['public_calls']
            if not optional_effects:
                for name in OUTCOMES[2:]:
                    report['outcomes'][name] = {'outcome': 'BLOCKED', 'reason': 'Optional file/log effects exceed owned cleanup call reserve'}
            persist()

        if version == '2025.1' and not readers:
            def cursor():
                verified = effect('profiler.setCursorTime', ['--cursor-target-ms', fixed_time])
                scope = verified['verification']['verification_scope']['cursor_observation']
                read = call(['core-call', PREFIX + 'profiler.getCursorTime', '--profiler-cursor', 'user-cursor'])['agent_result']
                assert verified['verification']['business_state_verified'] is True and scope['outcome'] == 'matched', verified
                assert read['available'] is True and read['position_ms'] == scope['returned_time_ms'] == scope['observed_time_ms'], (scope, read)
                return {'requested_time_ms': position['position_ms'], 'snapped_time_ms': scope['returned_time_ms'],
                    'user_cursor': read, 'transaction': verified, 'capture_data_completeness_verified': False}
            outcome(OUTCOMES[1], cursor)

        if (version == '2025.1' and not readers) or optional_effects:
            def saved():
                output = destination / 'saved-capture'; output.mkdir()
                sibling = output / 'preserve.txt'; sibling.write_bytes(b'owned sibling preservation sentinel\n')
                before = hashlib.sha256(sibling.read_bytes()).hexdigest()
                verified = effect('profiler.saveCapture', ['--capture-output-directory', str(output), '--capture-name', 'OwnedCapture'])
                assert verified['verification']['business_state_verified'] is True, verified
                scope = verified['verification']['verification_scope']
                proof = capture_file_proof(output / 'OwnedCapture.prof', field='exact saved capture',
                    io_root=destination, max_bytes=512 * 1024 * 1024)
                assert proof['size'] > 0 and hashlib.sha256(sibling.read_bytes()).hexdigest() == before
                return {**scope, 'file': proof, 'sibling_sha256': before, 'transaction': verified}
            outcome(OUTCOMES[2], saved)
        clean_one('stop-transport')
        state = call(['core-call', PREFIX + 'transport.getState', '--transport-handle', handle])['agent_result']
        assert state['state'] == 'stopped', state
        report['cleanup']['transport_stopped_observation'] = state
        clean_one('destroy-transport')

        if (version == '2025.1' and not readers) or optional_effects:
            # General log belongs to this isolated host. Other-channel contents are
            # observed separately; no continuous/exclusive log-state promise is made.
            def log(channel):
                result = call(['core-call', PREFIX + 'log.get', '--log-channel', channel, '--max-results', '40'])['agent_result']
                assert result['truncated'] is False, 'Owned log baseline exceeds the 40-row collection bound'
                return result['items']
            before_other = log('source-control')
            report['logs'] = {'other_channel': 'source-control', 'other_before': before_other,
                'general_before': log('general'), 'scope': 'Exact owned Authoring host; selected General channel only'}
            message = 'WAAPI owned capture ' + uuid.uuid4().hex
            report['logs']['message'] = message
            def add_log():
                verified = effect('log.addItem', ['--message', message, '--severity', 'message'])
                observed = verified['verification']['verification_scope']['log_observation']
                assert verified['verification']['business_state_verified'] is True and observed['outcome'] == 'new_matching_item', verified
                rows = log('general')
                assert sum(row.get('message') == message and row.get('severity') == 'Message' for row in rows) == 1, rows
                return {'message': message, 'rows_after': rows, 'transaction': verified,
                    'exclusive_causation_verified': False}
            outcome(OUTCOMES[3], add_log)
            def clear_log():
                verified = effect('log.clear', ['--log-channel', 'general'])
                observed = verified['verification']['verification_scope']['log_observation']
                assert verified['verification']['business_state_verified'] is True and observed['outcome'] == 'prior_contents_absent', verified
                rows, other = log('general'), log('source-control')
                assert not any(row.get('message') == message for row in rows), rows
                assert other == before_other, 'Unselected source-control log changed'
                return {'rows_after': rows, 'other_after': other, 'transaction': verified,
                    'continuing_channel_state_verified': False}
            outcome(OUTCOMES[4], clear_log)
    except Exception as exc:
        report['errors'].append({'type': type(exc).__name__, 'message': str(exc)[:4096]})
    finally:
        finish()
    assert report['complete'], report
