"""Bounded input observations through existing Console Gateway transactions.

These observations establish exact submissions, not hidden profiler settings,
repeated-row precedence, negative sentinels or capture completeness.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from wwise_waapi.host_paths import localize_waapi_host_path

PREFIX = 'ak.wwise.core.profiler.'
BUILDS = {'2021.1': (2021, 1, 14, 8108), '2022.1': (2022, 1, 19, 8584),
    '2023.1': (2023, 1, 19, 8928), '2024.1': (2024, 1, 13, 9056), '2025.1': (2025, 1, 7, 9143)}
ENABLE_CASES = (
    ('empty', ['--capture-data-empty']),
    ('identical-voices-enable', ['--capture-data', 'voices', 'enable', '--capture-data', 'voices', 'enable']),
    ('voices-enable-disable', ['--capture-data', 'voices', 'enable', '--capture-data', 'voices', 'disable']),
)


class _InputObservation:
    def __init__(self, runtime, name, cases):
        self.runtime = runtime
        runtime.state_dir.mkdir(parents=True, exist_ok=True)
        self.path = runtime.state_dir / (name + '.json')
        self.category = {'category': name, 'status': 'FAIL', 'observation_task_status': 'BLOCKED',
            'verifier_strength': 'exact_once_native_submission_and_existing_gateway_verification',
            'business_effect_verified': False, 'coverage_credit': 'input_observation_only',
            'observation_path': str(self.path), 'transaction_ids': []}
        runtime.category_results.append(self.category)
        self.report = {'contract': 'waapi-skill.profiler-input-observations/v1',
            'candidate': runtime.candidate, 'version': runtime.version, 'complete': False,
            'business_effect_verified': False, 'cases': [{'name': name, 'native_outcome': 'not_attempted'} for name in cases],
            'calls': [], 'setup': [], 'cleanup': {'complete': True,
                'prior_capture_settings_restored': False,
                'scope': 'No enabled-settings getter; owned host shutdown is separate lifecycle cleanup'},
            'limits': {'public_calls': 128, 'reply_bytes': 1024 * 1024,
                'total_reply_bytes': 8 * 1024 * 1024, 'report_bytes': 12 * 1024 * 1024},
            'total_reply_bytes': 0,
            'unobserved': ['empty-array effect', 'repeated-row precedence', 'prior enabled settings',
                'capture completeness', 'negative setter sentinel meaning']}
        self.persist()

    def persist(self):
        raw = (json.dumps(self.report, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        assert len(raw) <= self.report['limits']['report_bytes'], 'Profiler input report byte bound exceeded'
        pending = self.path.with_suffix('.pending')
        pending.write_bytes(raw)
        pending.replace(self.path)
        self.category['observation_sha256'] = hashlib.sha256(raw).hexdigest()

    def raw(self, argv):
        assert len(self.report['calls']) < self.report['limits']['public_calls'], 'Profiler input public call bound exceeded'
        row = {'argv': list(argv)}
        self.report['calls'].append(row)
        try:
            code, payload = self.runtime.raw_gateway(argv)
            row.update(exit_code=code, payload=payload)
            size = len(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
            self.report['total_reply_bytes'] += size
            assert size <= self.report['limits']['reply_bytes'], 'Profiler input reply byte bound exceeded'
            assert self.report['total_reply_bytes'] <= self.report['limits']['total_reply_bytes'], 'Profiler input total reply bound exceeded'
            return code, payload
        except Exception as exc:
            row['error'] = {'type': type(exc).__name__, 'message': str(exc)[:2048]}
            raise
        finally:
            self.persist()

    def call(self, argv):
        code, payload = self.raw(argv)
        assert code == 0 and payload.get('ok') is True, payload
        return payload

    def attest(self):
        status = self.call(['status'])
        info = status['wwise']
        self.report['host'] = info
        assert info['isCommandLine'] is True, 'Profiler input collector requires its owned Console host'
        assert tuple(info['version'][key] for key in ('year', 'major', 'minor', 'build')) == BUILDS[self.runtime.version], status
        project = status['project']
        if self.runtime.version == '2021.1':
            observed = self.call(['query-object', '--exact-id', project['id'], '--include', 'file-path', '--max-results', '1'])
            assert observed['count'] == 1 and observed.get('projection_complete') is not False, observed
            row, = observed['objects']
            assert all(row[key] == project[key] for key in ('id', 'name', 'type', 'path')), observed
            project_path = row['file_path']
        else:
            project_path = project['path']
        assert Path(localize_waapi_host_path(project_path)).resolve() == self.runtime.sandbox.sandbox_project.resolve(), status
        self.persist()

    def transaction(self, suffix, fields, case):
        operation = PREFIX + suffix
        schema = self.call(['request-schema', operation])
        started = self.call(schema['continuation']['gateway_argv'])
        current, authority = started['draft'], started['task_authority']
        draft_id = current['draft_id']
        for command, values in (('draft-declare-runtime-control-plan', fields), ('draft-check', []), ('preview-from-draft', [])):
            reply = self.call([command, draft_id, '--task-authority', authority,
                '--expected-revision', str(current['revision']), *values])
            current = reply.get('draft', current)
        case.update(declaration=list(fields), preview=reply)
        return self.execute_preview(reply, case)

    def zero(self, suffix, case, *, before_execute=None):
        schema = self.call(['request-schema', PREFIX + suffix])
        preview = self.call(schema['continuation']['gateway_argv'])
        case['preview'] = preview
        return self.execute_preview(preview, case, before_execute=before_execute)

    def execute_preview(self, preview, case, *, before_execute=None):
        tx = preview['transaction_id']
        case['transaction_id'] = tx
        self.category['transaction_ids'].append(tx)
        shown = self.call(['transaction-show', tx])
        case['sealed_preview'] = shown['artifact']
        self.call(['confirm', tx, '--confirmation-token', shown['confirmation']['token']])
        # Until a successful structured native acknowledgment is retained, a
        # failed execution is uncertain. Native errors never imply safe replay.
        if before_execute:
            before_execute()
        case['native_outcome'] = 'indeterminate'
        self.persist()
        code, executed = self.raw(['execute', tx])
        case['execute'] = executed
        dispatch = executed.get('dispatch_result', {})
        if dispatch.get('ok') is True:
            case['native_outcome'] = 'accepted'
        self.persist()
        assert code == 0 and executed.get('ok') is True and executed.get('state') == 'executed_unverified', executed
        code, verified = self.raw(['verify', tx])
        case['verify'] = verified
        self.persist()
        assert code == 0 and verified.get('ok') is True, verified
        return verified

    def fail(self, exc):
        self.report['failure'] = {'type': type(exc).__name__, 'message': str(exc)[:2048]}

    def finish(self):
        self.category['observation_task_status'] = 'PASS' if self.report['complete'] else 'BLOCKED'
        self.category['status'] = 'blocked' if self.report['complete'] else 'FAIL'
        self.persist()


def collect_enablement_inputs(runtime):
    observed = _InputObservation(runtime, 'profiler-enablement-input-shapes', [name for name, _ in ENABLE_CASES])
    try:
        observed.attest()
        for case, (_, fields) in zip(observed.report['cases'], ENABLE_CASES, strict=True):
            verified = observed.transaction('enableProfilerData', fields, case)
            verification = verified['verification']
            assert verification['status'] == 'result_schema_checked' and verification['business_state_verified'] is False, verified
        observed.report['complete'] = True
    except BaseException as exc:
        observed.fail(exc)
        raise
    finally:
        observed.finish()


def collect_signed_cursor_inputs(runtime):
    assert runtime.version == '2025.1', 'Signed cursor observations require the matching2025 definition'
    observed = _InputObservation(runtime, 'profiler-signed-cursor-inputs', ['minus-one', 'minus-two'])
    report = observed.report
    report['cleanup'].update(complete=False, capture_stop_acknowledged=False,
        capture_state_independently_observed=False)
    capture_may_have_started, stop_attempted, prior, primary_error = False, False, None, None
    def arm_capture_cleanup():
        nonlocal capture_may_have_started
        capture_may_have_started = True
    def stop_capture():
        nonlocal stop_attempted
        stop_attempted = True  # No retry even when stop outcome is uncertain.
        phase = {'name': 'stop-capture'}
        report['cleanup']['stop_capture'] = phase
        observed.zero('stopCapture', phase)
        report['cleanup']['capture_stop_acknowledged'] = True
    try:
        observed.attest()
        start = {'name': 'start-capture'}
        report['setup'].append(start)
        observed.zero('startCapture', start, before_execute=arm_capture_cleanup)
        deadline = time.monotonic() + 2.0
        report['capture_read_attempts'] = 0
        for _ in range(2):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            report['capture_read_attempts'] += 1
            payload = observed.call(['--timeout', str(remaining), 'core-call', PREFIX + 'getCursorTime',
                '--profiler-cursor', 'capture-latest'])
            position = report['capture_position'] = payload['agent_result']
            if position['available'] is True:
                assert type(position['position_ms']) is int and position['position_ms'] >= 0, position
                break
            remaining = deadline - time.monotonic()
            if remaining > 0 and report['capture_read_attempts'] < 2:
                time.sleep(min(0.25, remaining))
        stop_capture()
        assert report.get('capture_position', {}).get('available') is True, (
            'Console captured cursor unavailable; signed probes not attempted')
        prior = observed.call(['core-call', PREFIX + 'getCursorTime', '--profiler-cursor', 'user-cursor'])['agent_result']
        report['user_cursor_before'] = prior
        for case, target in zip(report['cases'], (-1, -2), strict=True):
            verified = observed.transaction('setCursorTime', ['--cursor-target-ms', str(target)], case)
            # The existing verifier owns one returned-time/user-cursor comparison.
            # Preserve unavailable/changed results; never reinterpret the input.
            case['cursor_observation'] = verified['verification']['verification_scope']['cursor_observation']
    except BaseException as exc:
        primary_error = exc
        observed.fail(exc)
        raise
    finally:
        cleanup_error = None
        try:
            if capture_may_have_started and not stop_attempted:
                stop_capture()
            uncertain = any(case['native_outcome'] == 'indeterminate' for case in report['cases'])
            accepted = any(case['native_outcome'] == 'accepted' for case in report['cases'])
            if accepted and not uncertain and prior is not None and prior['available'] is True:
                restoration = {'name': 'restore-observed-user-cursor'}
                report['cleanup']['cursor_restoration'] = restoration
                verified = observed.transaction('setCursorTime', ['--cursor-target-ms', str(prior['position_ms'])], restoration)
                scope = verified['verification']['verification_scope']['cursor_observation']
                assert scope['outcome'] == 'matched' and scope['observed_time_ms'] == prior['position_ms'], verified
                report['cleanup']['cursor_restored_to_observed_time_ms'] = scope['observed_time_ms']
            elif accepted:
                report['cleanup']['cursor_restoration_boundary'] = (
                    'withheld after uncertain execution' if uncertain else 'prior user cursor unavailable')
            report['cleanup']['complete'] = report['cleanup']['capture_stop_acknowledged'] and not uncertain
        except BaseException as exc:
            cleanup_error = exc
            report['cleanup']['error'] = {'type': type(exc).__name__, 'message': str(exc)[:2048]}
            report['cleanup']['complete'] = False
        report['complete'] = (primary_error is None and cleanup_error is None
            and report['cleanup']['complete'] and all(case['native_outcome'] == 'accepted' for case in report['cases']))
        observed.finish()
        if primary_error is None and cleanup_error is not None:
            raise cleanup_error
