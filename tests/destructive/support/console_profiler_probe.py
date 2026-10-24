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
PREFIX = 'ak.wwise.core.'


def collect_console_profiler(runtime):
    assert runtime.version == '2025.1', 'Console playback probe is pinned to2025.1'
    report_path = runtime.state_dir / 'console-profiler-probe.json'
    report_path.parent.mkdir(parents=True, exist_ok=True)
    category = {'category': 'console-transport-profiler-probe', 'status': 'blocked',
        'observation_task_status': 'BLOCKED', 'observation_path': str(report_path),
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
            'total_reply_bytes': 8 * 1024 * 1024, 'report_bytes': 24 * 1024 * 1024,
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

    def call(argv):
        reserve = 0 if cleanup_active else report['limits']['cleanup_reserve_calls']
        assert report['public_call_count'] < 128 - reserve, 'Console public call budget exhausted'
        assert report['total_reply_bytes'] + 1024 * 1024 <= 8 * 1024 * 1024, 'Console total reply budget exhausted'
        if not cleanup_active:
            assert report['total_reply_bytes'] + 1024 * 1024 <= 5 * 1024 * 1024, 'Console cleanup byte reserve unavailable'
        remaining = deadline - time.monotonic()
        assert remaining > 0, 'Console elapsed-time budget exhausted'
        entry = {'argv': list(argv), 'cleanup_phase': cleanup_active}
        report['calls'].append(entry)
        report['public_call_count'] += 1
        try:
            code, payload = runtime.raw_gateway(['--timeout', str(min(10, remaining)), *argv])
            entry.update(exit_code=code, payload=payload)
            size = len(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
            report['total_reply_bytes'] += size
            assert size <= 1024 * 1024 and report['total_reply_bytes'] <= 8 * 1024 * 1024, 'Console reply byte bound exceeded'
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
        executed = call(['execute', tx])
        assert executed.get('state') == 'executed_unverified', executed
        verified = call(['verify', tx])
        assert verified.get('state') in ('verified', 'result_schema_checked'), verified
        assert verified.get('verification', {}).get('status') in ('verified', 'result_schema_checked'), verified
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
