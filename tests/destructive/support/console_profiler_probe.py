"""One owned 2025 Console playback/data experiment, never a host-capability claim."""
from __future__ import annotations

import hashlib
import json
import time
import wave
from pathlib import Path

from wwise_waapi.host_paths import localize_waapi_host_path
from wwise_waapi.operation_soundbank import capture_file_proof
from tests.destructive.support.profiler_input_shapes import BUILDS
from tests.destructive.support.profiler_capture import (
    CAPTURE_CAR_ID, CAPTURE_CAR_SOURCE_ID, CAPTURE_CAR_PARENT_ID, CAPTURE_CAR_MEDIA,
)

NODE_NAME = 'test_console_owned_2025_transport_profiler_probe'
NODEID = 'tests/destructive/test_gateway_workflow_transaction_matrix.py::' + NODE_NAME
DIAGNOSTIC_NAME = 'test_console_owned_2025_transport_profiler_diagnostic'
DIAGNOSTIC_NODEID = 'tests/destructive/test_gateway_workflow_transaction_matrix.py::' + DIAGNOSTIC_NAME
PREFIX = 'ak.wwise.core.'


def collect_console_profiler(runtime, *, diagnostic=False):
    assert runtime.version == '2025.1', 'Console playback probe is pinned to2025.1'
    report_path = runtime.state_dir / 'console-profiler-probe.json'
    report_path.parent.mkdir(parents=True, exist_ok=True)
    category = {'category': 'console-transport-profiler-probe', 'status': 'blocked',
        'observation_task_status': 'BLOCKED', 'diagnostic_enabled': diagnostic, 'observation_path': str(report_path),
        'transaction_ids': [], 'verifier_strength': 'owned_playback_and_complete_same_time_voice',
        'native_host_support_inferred': False}
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
            'native_schema_sha256': canonical_sha256(load_native_catalog('2025.1', 'wwise-console')['schemas'][topic])}
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
                    and record.get('endpoint') == endpoint and record.get('detected_version') == '2025.1'
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
    persist()
    try:
        status = call(['status'])
        report['host'] = info = status['wwise']
        assert info.get('isCommandLine') is True
        assert tuple(info['version'][key] for key in ('year', 'major', 'minor', 'build')) == BUILDS['2025.1']
        assert Path(localize_waapi_host_path(status['project']['path'])).resolve() == runtime.sandbox.sandbox_project.resolve()
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
        report['setup']['originals'] = effect('transport.useOriginals', ['--audition-media', 'originals'])
        report['setup']['prepare'] = effect('transport.prepare', identity=CAPTURE_CAR_ID)
        report['setup']['enable'] = effect('profiler.enableProfilerData', ['--capture-data', 'voices', 'enable'],
            before_execute=lambda: own('disable-voices', lambda: effect('profiler.enableProfilerData', ['--capture-data', 'voices', 'disable'])))
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
        result = call(['core-call', PREFIX + 'profiler.getVoices', '--profiler-position', str(position['position_ms']),
            '--result-view', 'identity', '--max-results', '64'])['agent_result']
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
        report['complete'] = not report['errors'] and report['cleanup']['complete'] and report['outcomes'].get('voices', {}).get('outcome') == 'PASS'
        category.update(status='PASS' if report['complete'] else 'blocked',
            observation_task_status='PASS' if report['complete'] else 'BLOCKED',
            cleanup_complete=report['cleanup']['complete'])
        persist()
    assert report['complete'], 'Console playback/data probe incomplete: ' + json.dumps(report['errors'])
