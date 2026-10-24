"""One owned version-pinned Console playback/data observation."""
from __future__ import annotations

import hashlib
import json
import math
import time
import wave
from pathlib import Path

from wwise_waapi.host_paths import localize_waapi_host_path, parse_absolute_host_path
from wwise_waapi.operation_soundbank import capture_file_proof
from tests.destructive.support.profiler_input_shapes import BUILDS
from tests.destructive.support.profiler_capture import (
    CAPTURE_CAR_ID, CAPTURE_CAR_SOURCE_ID, CAPTURE_CAR_PARENT_ID, CAPTURE_CAR_MEDIA, CAPTURE_RPM_ID,
)

NODE_NAME = 'test_console_owned_2025_transport_profiler_probe'
NODEID = 'tests/destructive/test_gateway_workflow_transaction_matrix.py::' + NODE_NAME
DIAGNOSTIC_NAME = 'test_console_owned_2025_transport_profiler_diagnostic'
DIAGNOSTIC_NODEID = 'tests/destructive/test_gateway_workflow_transaction_matrix.py::' + DIAGNOSTIC_NAME
OLDER_NAME = 'test_console_owned_older_transport_profiler_diagnostic'
OLDER_NODEID = 'tests/destructive/test_gateway_workflow_transaction_matrix.py::' + OLDER_NAME
BATCH_NAME = 'test_console_owned_runtime_read_batch'
BATCH_NODEID = 'tests/destructive/test_gateway_workflow_transaction_matrix.py::' + BATCH_NAME
PREFIX = 'ak.wwise.core.'


def collect_console_profiler(runtime, *, diagnostic=False, grouped_runtime_reads=False):
    assert not (diagnostic and grouped_runtime_reads), 'Select one closed collector mode'
    assert runtime.version in BUILDS and (grouped_runtime_reads or diagnostic or runtime.version == '2025.1'), 'Select one pinned Console lane'
    report_path = runtime.state_dir / ('console-runtime-read-batch.json' if grouped_runtime_reads else 'console-profiler-probe.json')
    report_path.parent.mkdir(parents=True, exist_ok=True)
    category = {'category': 'console-runtime-read-batch' if grouped_runtime_reads else 'console-transport-profiler-probe', 'status': 'blocked',
        'observation_task_status': 'BLOCKED', 'diagnostic_enabled': diagnostic, 'observation_path': str(report_path),
        'transaction_ids': [], 'verifier_strength': 'owned_playback_and_complete_same_time_voice',
        'native_host_support_inferred': False}
    if grouped_runtime_reads:
        category['verifier_strength'] = 'independent_complete_same_frame_owned_runtime_reads'
    runtime.category_results.append(category)
    report = {'contract': 'waapi-skill.console-profiler-probe/v1', 'candidate': runtime.candidate,
        'version': runtime.version, 'complete': False, 'calls': [], 'public_call_count': 0,
        'total_reply_bytes': 0, 'setup': {}, 'outcomes': {}, 'errors': [],
        'cleanup': {'complete': False, 'receipts': [], 'errors': [],
            'prior_capture_settings_restored': False, 'prior_originals_mode_restored': False,
            'restoration_scope': 'Owned fresh host teardown; explicit capture disable is not prior-setting restoration'},
        'limits': {'public_calls': 128, 'reply_bytes': 1024 * 1024,
            'total_reply_bytes': 8 * 1024 * 1024, 'report_bytes': (40 if diagnostic else 24) * 1024 * 1024,
            'ordinary_seconds': 120, 'cleanup_seconds': 60, 'cleanup_reserve_calls': 36,
            'cleanup_reserve_bytes': 3 * 1024 * 1024}}
    if grouped_runtime_reads:
        report['contract'] = 'waapi-skill.console-runtime-read-batch/v1'
        report['outcomes'] = {name: {'outcome': 'BLOCKED', 'reason': 'Shared setup not completed'}
            for name in ('voices', 'busses', 'audio_objects', 'rtpcs', 'contributions_dry', 'game_objects')}
        if runtime.version == '2021.1':
            report['outcomes']['game_objects'] = {'outcome': 'UNAVAILABLE',
                'reason': 'getGameObjects absent from matching 2021.1 Console catalog; no call or gameSyncs substitution'}
    cleanup = []
    cleanup_active = False
    deadline = time.monotonic() + 120

    def persist():
        raw = (json.dumps(report, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
        assert len(raw) <= report['limits']['report_bytes'], 'Console report byte bound exceeded'
        temporary = report_path.with_suffix('.pending')
        temporary.write_bytes(raw)
        temporary.replace(report_path)
        category['observation_sha256'] = hashlib.sha256(raw).hexdigest()

    def call(argv, *, producer=False, stream_sink=None, strict=True):
        reserve = 0 if cleanup_active else report['limits']['cleanup_reserve_calls']
        assert report['public_call_count'] < 128 - reserve, 'Console public call budget exhausted'
        assert report['total_reply_bytes'] + 1024 * 1024 <= 8 * 1024 * 1024, 'Console total reply budget exhausted'
        if not cleanup_active:
            assert report['total_reply_bytes'] + 1024 * 1024 <= 5 * 1024 * 1024, 'Console cleanup byte reserve unavailable'
        remaining = deadline - time.monotonic()
        assert remaining > 0, 'Console elapsed-time budget exhausted'
        entry = {'argv': list(argv), 'cleanup_phase': cleanup_active,
            'execution_context': 'separate_packaged_gateway_process' if producer else 'observer_process'}
        report['calls'].append(entry)
        report['public_call_count'] += 1
        try:
            code, payload = (runtime.packaged_topic_producer(argv) if producer else
                runtime.raw_gateway(['--timeout', str(min(10, remaining)), *argv], stream_sink=stream_sink))
            entry.update(exit_code=code, payload=payload)
            size = len(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
            report['total_reply_bytes'] += size
            assert size <= 1024 * 1024 and report['total_reply_bytes'] <= 8 * 1024 * 1024, 'Console reply byte bound exceeded'
            if strict:
                assert code == 0 and payload.get('ok') is True, payload
            return payload
        except Exception as exc:
            entry['error'] = {'type': type(exc).__name__, 'message': str(exc)[:1024]}
            raise
        finally:
            persist()

    def exact(identity, *fields):
        result = call(['query-object', '--exact-id', identity, '--max-results', '1', *fields])
        assert result['count'] == 1 and result.get('projection_complete') is not False, result
        row, = result['objects']
        assert row['id'] == identity and all(isinstance(row.get(key), str) for key in ('name', 'type', 'path')), row
        return row

    def effect(suffix, fields=(), *, identity=None, before_execute=None, zero=False):
        operation = PREFIX + suffix
        if zero:
            schema = call(['request-schema', operation])
            preview = call(schema['continuation']['gateway_argv'])
        else:
            started = call(['draft-start', operation])
            current, authority = started['draft'], started['task_authority']
            draft_id = current['draft_id']
            def step(command, values=()):
                nonlocal current
                result = call([command, draft_id, '--task-authority', authority,
                    '--expected-revision', str(current['revision']), *values])
                current = result.get('draft', current)
                return result
            declared = list(fields)
            if identity is not None:
                bound = step('draft-bind-object', ['--role', 'target', '--object-id', identity])
                declared = ['--target-handle', bound['bound_object']['handle'], *declared]
            step('draft-declare-runtime-control-plan', declared)
            step('draft-check')
            preview = step('preview-from-draft')
        tx = preview['transaction_id']
        category['transaction_ids'].append(tx)
        shown = call(['transaction-show', tx])
        call(['confirm', tx, '--confirmation-token', shown['confirmation']['token']])
        if before_execute:
            before_execute()
        if diagnostic and suffix == 'transport.executeAction' and 'play' in fields:
            verified = observe_play(tx)
        else:
            executed = call(['execute', tx])
            assert executed.get('state') == 'executed_unverified', executed
            verified = call(['verify', tx])
        assert verified.get('state') in ('verified', 'result_schema_checked'), verified
        assert verified.get('verification', {}).get('status') in ('verified', 'result_schema_checked'), verified
        return verified

    def observe_play(tx):
        # Reuse the established single public stream + isolated packaged producer
        # seam. Its started packet is emitted only after the native subscribe ACK.
        from copy import deepcopy
        from wwise_waapi.canonical import canonical_sha256
        from wwise_waapi.native_catalog import load_native_catalog
        topic = PREFIX + 'profiler.captureLog.itemAdded'
        schema = call(['topic-schema', topic])
        digest = schema['continuation']['contract_binding']['value']
        cursor = lambda: call(['core-call', PREFIX + 'profiler.getCursorTime',
            '--profiler-cursor', 'capture-latest'])['agent_result']
        before = cursor()
        observation = {'topic': topic, 'contract_digest': digest, 'records': [], 'events': [],
            'started_before_execute': False, 'cause_proven': False,
            'silence_meaning': 'inconclusive; no host absence inferred', 'cleanup': 'unknown',
            'capture_before': before, 'limits': {'events': 8, 'total_seconds': 10,
                'idle_seconds': 2, 'records': 10, 'record_bytes': 1024 * 1024},
            'native_schema_sha256': canonical_sha256(load_native_catalog(runtime.version, 'wwise-console')['schemas'][topic])}
        report['play_diagnostic'] = observation
        verified = None
        endpoint = {'host': runtime.lifecycle.host, 'port': runtime.lifecycle.port, 'url': runtime.lifecycle.waapi_url}
        def observe(record):
            nonlocal verified
            assert len(observation['records']) < 10, 'Console diagnostic stream record bound exceeded'
            assert len(json.dumps(record).encode('utf-8')) <= 1024 * 1024, 'Console diagnostic record byte bound exceeded'
            observation['records'].append(deepcopy(record))
            persist()
            if record.get('record_type') == 'started':
                assert not observation['started_before_execute'], 'Duplicate ACK; never repeat play'
                assert (record.get('contract') == 'waapi-skill.topic-stream/v1'
                    and record.get('topic') == topic and record.get('topic_contract_digest') == digest
                    and record.get('status') == 'streaming' and record.get('ok') is True
                    and record.get('endpoint') == endpoint and record.get('detected_version') == runtime.version
                    and record.get('is_command_line') is True and record.get('event_count_limit') == 8), record
                observation['started_before_execute'] = True
                observation['effect_started_monotonic_ns'] = time.monotonic_ns()
                persist()
                executed = call(['execute', tx], producer=True)
                assert executed.get('state') == 'executed_unverified', executed
                verified = call(['verify', tx], producer=True)
                observation['effect_finished_monotonic_ns'] = time.monotonic_ns()
                persist()
        terminal = call(['--timeout', '10', 'stream-topic', topic, '--topic-contract-digest', digest,
            '--event-count', '8', '--idle-timeout', '2'], stream_sink=observe, strict=False)
        observation.update(terminal=terminal, cleanup=terminal.get('cleanup', 'unknown'))
        if observation['cleanup'] != 'unsubscribed':
            report['cleanup']['errors'].append({'action': 'capture-log-unsubscribe',
                'message': 'Public stream did not prove unsubscribe; owned teardown still required'})
        after = cursor()
        observation['capture_after'] = after
        for record in observation['records']:
            if record.get('record_type') != 'event':
                continue
            event = record['event']
            identity_match = (event.get('objectId') == CAPTURE_CAR_ID
                and event.get('gameObjectId') == report['transport_association']['gameObject'])
            interval_match = (before.get('available') is True and after.get('available') is True
                and type(event.get('time')) is int
                and before['position_ms'] <= event['time'] <= after['position_ms'])
            observation['events'].append({'event': deepcopy(event), 'schema_validation': 'accepted_by_gateway',
                'correlation': 'matching_identity_and_capture_interval' if identity_match and interval_match
                else 'identity_only_time_unresolved' if identity_match else 'unrelated_or_identity_unresolved',
                'cause_proven': False})
        persist()
        assert observation['started_before_execute'] and verified is not None, 'No valid ACK; play not attempted'
        assert observation['cleanup'] == 'unsubscribed', 'Console diagnostic unsubscribe unproven'
        assert terminal.get('error_code') in (None, 'TIMEOUT'), terminal
        return verified

    def own(label, action):
        cleanup.append((label, action))

    query_fields = ['--include', 'parent', '--include', 'active-source', '--include', 'output-bus',
        '--include-field', 'IsLoopingEnabled', '--include-field', 'IsLoopingInfinite']
    if runtime.version == '2021.1':
        query_fields += ['--platform', 'Mac', '--language', 'SFX']
    persist()
    try:
        status = call(['status'])
        report['host'] = info = status['wwise']
        if grouped_runtime_reads:
            report['endpoint'] = status['endpoint']
        assert info.get('isCommandLine') is True
        assert tuple(info['version'][key] for key in ('year', 'major', 'minor', 'build')) == BUILDS[runtime.version]
        project = status['project']
        if runtime.version == '2021.1':
            observed = exact(project['id'], '--include', 'file-path')
            assert all(observed[key] == project[key] for key in ('id', 'name', 'type', 'path'))
            project_path = observed['file_path']
        else:
            project_path = project['path']
        assert Path(localize_waapi_host_path(project_path)).resolve() == runtime.sandbox.sandbox_project.resolve()
        media = runtime.sandbox.sandbox_path / CAPTURE_CAR_MEDIA
        proof = capture_file_proof(media, field='owned existing Car original', io_root=runtime.sandbox.sandbox_path,
            max_bytes=16 * 1024 * 1024)
        staging = json.loads((runtime.state_dir / 'capture-read-media.json').read_text())
        assert all(proof[key] == staging['staged'][key] for key in ('path', 'sha256', 'size'))
        with wave.open(str(media)) as wav:
            assert wav.getnframes() > 0 and wav.getframerate() > 0
        report['media'] = {'proof': proof, 'staging': staging}
        sound = exact(CAPTURE_CAR_ID, *query_fields)
        source = exact(CAPTURE_CAR_SOURCE_ID, '--include', 'original-file-path')
        assert sound['name'] == 'Outside_Idle_1000' and sound['type'] == 'Sound'
        assert sound['parent']['id'] == CAPTURE_CAR_PARENT_ID
        assert sound['active_source']['id'] == CAPTURE_CAR_SOURCE_ID
        assert sound['properties']['IsLoopingEnabled'] is True and sound['properties']['IsLoopingInfinite'] is True
        assert source['type'] == 'AudioFileSource'
        assert Path(localize_waapi_host_path(source['original_file_path'])).resolve() == media.resolve()
        bus = exact(sound['output_bus']['id'])
        assert bus['type'] == 'Bus'
        report['fixture_before'] = {'sound': sound, 'source': source, 'bus': bus}
        native_path = source['original_file_path']
        parsed = parse_absolute_host_path(native_path)
        if parsed.flavor in ('drive', 'unc'):
            # Matching pinned Windows AkTypes.h headers define AK_MAX_PATH=260.
            # Measure the original native spelling, not the localized POSIX path.
            units = len(native_path.encode('utf-16-le')) // 2 + 1
            report['native_source_path_limit'] = {'flavor': parsed.flavor,
                'utf16_units_including_nul': units, 'allowed_units_including_nul': 260}
            assert units <= 260, f'Console original path {units} UTF-16 units including NUL exceeds allowed 260'
        report['media_resolution'] = {
            'originals_selection_available': runtime.version in ('2023.1', '2024.1', '2025.1'),
            'prepare_available': runtime.version != '2021.1',
            'boundary': 'Original file proof and preparation acknowledgment do not prove native media readiness; no conversion/cache workaround'}
        if runtime.version in ('2023.1', '2024.1', '2025.1'):
            report['setup']['originals'] = effect('transport.useOriginals', ['--audition-media', 'originals'])
        if runtime.version != '2021.1':
            report['setup']['prepare'] = effect('transport.prepare', identity=CAPTURE_CAR_ID)
        datasets = ['voices']
        if grouped_runtime_reads:
            parameter = exact(CAPTURE_RPM_ID)
            assert parameter['type'] == 'GameParameter' and parameter['name'] == 'RPM', parameter
            report['game_parameter'] = parameter
            datasets += ['voice-inspector', 'audio-objects']
            if runtime.version != '2021.1':
                datasets += ['game-syncs']
            report['capture_datasets'] = datasets
        def directives(mode):
            return [token for dataset in datasets for token in ('--capture-data', dataset, mode)]
        report['setup']['enable'] = effect('profiler.enableProfilerData', directives('enable'),
            before_execute=lambda: own('disable-voices', lambda: effect('profiler.enableProfilerData', directives('disable'))))
        report['setup']['capture'] = effect('profiler.startCapture', zero=True,
            before_execute=lambda: own('stop-capture', lambda: effect('profiler.stopCapture', zero=True)))
        # Creation cleanup is Gateway-bound to its exact execution result. Never
        # reconstruct an unknown ID or repeat creation after an ambiguous result.
        created = effect('transport.create', identity=CAPTURE_CAR_ID,
            before_execute=lambda: report.update(transport_creation_uncertain=True))
        report['setup']['create'] = created
        handle = created['agent_result']['business_result']['transport_handle']
        report['transport_creation_uncertain'] = False
        own('destroy-transport', lambda: effect('transport.destroy', ['--transport-handle', handle]))
        own('stop-transport', lambda: effect('transport.executeAction', ['--audition-action', 'stop',
            '--transport-scope', 'one-transport', '--transport-handle', handle]))
        if diagnostic:
            schema = call(['request-schema', PREFIX + 'transport.getList'])
            membership = call(schema['continuation']['gateway_argv'])['agent_result']['list']
            association, = [row for row in membership if row['object'] == CAPTURE_CAR_ID]
            report['transport_association'] = association
        report['setup']['play'] = effect('transport.executeAction', ['--audition-action', 'play',
            '--transport-scope', 'one-transport', '--transport-handle', handle])
        state = call(['core-call', PREFIX + 'transport.getState', '--transport-handle', handle])['agent_result']
        report['playback'] = state
        assert state['state'] == 'playing', 'Console playback not observed; no data read'
        schema = call(['request-schema', PREFIX + 'transport.getList'])
        membership = call(schema['continuation']['gateway_argv'])['agent_result']['list']
        association, = [row for row in membership if row['object'] == CAPTURE_CAR_ID]
        report['transport_association'] = association
        position = call(['core-call', PREFIX + 'profiler.getCursorTime', '--profiler-cursor', 'capture-latest'])['agent_result']
        report['capture_position'] = position
        assert position['available'] is True and type(position['position_ms']) is int and position['position_ms'] >= 0
        if grouped_runtime_reads:
            _collect_runtime_read_batch(call, report, persist, position_ms=position['position_ms'])
        else:
            result = call(['core-call', PREFIX + 'profiler.getVoices', '--profiler-position', str(position['position_ms']),
                '--result-view', ('identity' if runtime.version == '2025.1' else 'diagnostics'), '--max-results', '64'])['agent_result']
            evidence = {'agent_result': result, 'nonempty': bool(result['return']), 'complete': result.get('complete'),
                'position_ms': position['position_ms'], 'owned_voice_observed': False}
            report['outcomes']['voices'] = {'outcome': 'BLOCKED', 'evidence': evidence}
            owned = [row for row in result['return'] if row.get('objectGUID') == CAPTURE_CAR_ID
                and row.get('gameObjectID') == association['gameObject']]
            evidence['owned_voice_observed'] = bool(owned)
            assert result.get('complete') is True and owned, 'Complete owned Console voice unavailable'
            report['outcomes']['voices']['outcome'] = 'PASS'
    except Exception as exc:
        report['errors'].append({'type': type(exc).__name__, 'message': str(exc)[:2048]})
    finally:
        cleanup_active = True
        deadline = time.monotonic() + 60
        for label, action in reversed(cleanup):
            try:
                report['cleanup']['receipts'].append({'action': label, 'result': action()})
            except Exception as exc:
                report['cleanup']['errors'].append({'action': label, 'type': type(exc).__name__, 'message': str(exc)[:1024]})
            persist()
        try:
            if 'fixture_before' in report:
                report['fixture_after'] = {'sound': exact(CAPTURE_CAR_ID, *query_fields),
                    'source': exact(CAPTURE_CAR_SOURCE_ID, '--include', 'original-file-path'),
                    'bus': exact(report['fixture_before']['bus']['id'])}
                assert report['fixture_before'] == report['fixture_after'], 'Console fixture identity/properties changed'
                assert capture_file_proof(media, field='owned existing Car original', io_root=runtime.sandbox.sandbox_path,
                    max_bytes=16 * 1024 * 1024) == proof, 'Console input changed'
        except Exception as exc:
            report['cleanup']['errors'].append({'action': 'preservation', 'type': type(exc).__name__, 'message': str(exc)[:1024]})
        if report.get('transport_creation_uncertain'):
            report['cleanup']['errors'].append({'action': 'create-transport',
                'message': 'Creation attempted without a verified issued handle; owned host teardown required; no retry'})
        report['cleanup']['complete'] = not report['cleanup']['errors']
        readers_complete = (all(row['outcome'] == ('UNAVAILABLE' if name == 'game_objects' and runtime.version == '2021.1' else 'PASS')
            for name, row in report['outcomes'].items()) if grouped_runtime_reads else report['outcomes'].get('voices', {}).get('outcome') == 'PASS')
        report['complete'] = not report['errors'] and report['cleanup']['complete'] and readers_complete
        category.update(status='PASS' if report['complete'] else 'blocked',
            observation_task_status='PASS' if report['complete'] else 'BLOCKED',
            cleanup_complete=report['cleanup']['complete'])
        persist()
    assert report['complete'], 'Console playback/data probe incomplete: ' + json.dumps(report['errors'])


def _collect_runtime_read_batch(call, report, persist, *, position_ms):
    """One snapshot per reader. Only contributions depend on a complete owned voice seed."""
    game_object = report['transport_association']['gameObject']
    assert type(game_object) is int and 0 <= game_object < 1 << 64, 'Malformed owned transport association'
    fixed = str(position_ms)
    voice = None
    bus_rows = []

    def observe(name, argv, *, row_field='return'):
        evidence = {'position_ms': position_ms, 'owned_identity_observed': False}
        observation = report['outcomes'][name] = {'outcome': 'BLOCKED', 'evidence': evidence}
        # A failed native connection, elapsed/byte reserve or unknown Gateway context
        # stops the group. Only a response attributable to this reader is independent.
        payload = call(argv, strict=False)
        evidence['gateway_result'] = payload
        assert payload.get('endpoint') == report['endpoint'] and payload.get('detected_version') == report['version'], (
            'Shared connection/version context changed; remaining readers not attempted')
        if payload.get('ok') is not True:
            code = payload.get('error_code') or payload.get('call', {}).get('error_code')
            expected_api = PREFIX + 'profiler.' + {
                'voices': 'getVoices', 'busses': 'getBusses', 'audio_objects': 'getAudioObjects',
                'rtpcs': 'getRTPCs', 'game_objects': 'getGameObjects', 'contributions_dry': 'getVoiceContributions'}[name]
            details = payload.get('details') or {}
            result_failure = (code in ('RUNTIME_INSPECTION_RESULT_INVALID', 'INVALID_STABLE_READ_RESULT')
                or (code in ('SemanticValidationError', 'SEMANTIC_SCHEMA_MISMATCH')
                    and str(details.get('section', '')).startswith('result')))
            attributable = (payload.get('api_attempted') == expected_api
                or (result_failure and details.get('uri', details.get('api')) == expected_api))
            fatal = code in ('TIMEOUT', 'ConnectionError', 'ConnectionRefusedError', 'ConnectionResetError',
                'ConnectionClosed', 'ConnectionClosedError', 'OSError', 'VERSION_MISMATCH')
            observation.update(outcome='FAIL', reason='Reader failed; exact Gateway failure retained')
            persist()
            assert attributable and not fatal, 'Shared connection/context failure; remaining readers not attempted'
            return None
        result = payload['agent_result']
        evidence['agent_result'] = result  # Preserve the exact final public object.
        rows = result.get(row_field)
        if row_field == 'objects' and rows is None and result.get('contribution_reported') is False:
            rows = []
        assert isinstance(rows, list) and all(isinstance(row, dict) for row in rows), 'Malformed public reader array'
        evidence['nonempty'] = bool(rows) or (name == 'contributions_dry' and result.get('contribution_reported') is True)
        evidence['complete'] = result.get('complete', not result.get('truncated', False)) is True
        owned = []
        if name == 'voices':
            owned = [i for i, row in enumerate(rows) if row.get('objectGUID') == CAPTURE_CAR_ID
                and row.get('gameObjectID') == game_object]
            evidence['older_diagnostics_role'] = 'same-frame seed only; no additional coverage claim'
            if report['version'] == '2025.1':
                owned = [i for i in owned if all(field in rows[i] for field in (
                    'soundID', 'baseVolume', 'gameAuxSendVolume', 'envelope', 'normalizationGain',
                    'lowPassFilter', 'highPassFilter', 'priority', 'isStarted', 'isVirtual', 'isForcedVirtual'))]
        elif name == 'busses':
            owned = [i for i, row in enumerate(rows) if row.get('gameObjectID') == game_object
                and isinstance(row.get('objectGUID'), str) and isinstance(row.get('objectName'), str)
                and type(row.get('volume')) in (int, float) and math.isfinite(row['volume'])]
            evidence['logical_bus_equivalence_claimed'] = False
        elif name == 'audio_objects':
            owned = [i for i, row in enumerate(rows) if row.get('gameObjectID') == game_object
                and type(row.get('audioObjectID')) is int and isinstance(row.get('busGUID'), str)
                and type(row.get('busPipelineID')) is int]
            evidence['same_frame_bus_matches'] = {str(i): [j for j, bus in enumerate(bus_rows)
                if bus.get('gameObjectID') == row.get('gameObjectID') and bus.get('objectGUID') == row.get('busGUID')
                and bus.get('pipelineID') == row.get('busPipelineID')] for i, row in enumerate(rows)}
            evidence['metadata_population_claimed'] = False
        elif name == 'game_objects':
            owned = [i for i, row in enumerate(rows) if row.get('id') == game_object]
        elif name == 'rtpcs':
            owned = [i for i, row in enumerate(rows) if row.get('id') == report['game_parameter']['id']
                and row.get('name') == report['game_parameter']['name']
                and row.get('gameObjectId') in (game_object, (1 << 64) - 1)
                and type(row.get('value')) in (int, float) and math.isfinite(row['value'])]
            evidence['setter_effect_verified'] = False
            evidence['global_scope_sentinel'] = (1 << 64) - 1
        else:
            evidence['selected_observed_voice'] = voice
            evidence['path'] = 'default-dry-path; no selected Bus path or rich-tree claim'
            evidence['owned_identity_observed'] = evidence['nonempty']
        evidence['owned_row_indexes'] = owned
        if name != 'contributions_dry':
            evidence['owned_identity_observed'] = bool(owned)
        if evidence['complete'] and evidence['nonempty'] and evidence['owned_identity_observed']:
            observation['outcome'] = 'PASS'
        else:
            observation['reason'] = 'Complete nonempty attributable data unavailable; no repeat or inferred native absence'
        persist()
        return rows if observation['outcome'] == 'PASS' else None

    def reader(name, suffix):
        argv = ['core-call', PREFIX + 'profiler.' + suffix, '--profiler-position', fixed, '--max-results', '64']
        if name in ('voices', 'busses', 'audio_objects'):
            argv += ['--result-view', 'diagnostics']
        return observe(name, argv)

    voices = reader('voices', 'getVoices')
    if voices:
        owned = [row for row in voices if row.get('objectGUID') == CAPTURE_CAR_ID
            and row.get('gameObjectID') == game_object and isinstance(row.get('voice_instance_handle'), str)]
        # Do not choose arbitrarily if the complete frame contains multiple owned instances.
        voice = owned[0] if len(owned) == 1 else None
    bus_rows = reader('busses', 'getBusses') or []
    reader('audio_objects', 'getAudioObjects')
    if report['version'] != '2021.1':
        observe('game_objects', ['profiler-game-objects', '--capture-ms', fixed], row_field='game_objects')
    reader('rtpcs', 'getRTPCs')
    if voice is None:
        report['outcomes']['contributions_dry']['reason'] = 'No unique complete same-frame owned voice handle; no contribution call'
        persist()
    else:
        observe('contributions_dry', ['profiler-voice-contributions', '--capture-ms', fixed,
            '--voice-instance-handle', voice['voice_instance_handle']], row_field='objects')
