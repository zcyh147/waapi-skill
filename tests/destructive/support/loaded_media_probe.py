"""One owned 2025 Event-preparation probe, using only public Gateway calls."""
from __future__ import annotations

import json
from pathlib import Path
import time
import wave

from wwise_waapi.host_paths import localize_waapi_host_path
from wwise_waapi.operation_soundbank import capture_file_proof

NODEID = ('tests/destructive/test_authoring_ui_business_live.py::'
    'test_runtime_owned_2025_loaded_media_event_probe')
OUTCOME = 'profiler-loaded-media-observation'
EVENT = '{0112B248-632B-4DF4-BC80-4CD8270250BA}'
ACTION = '{8257E0BC-513A-4DFA-B85C-22C6997A5B19}'
SOUND = '{67C60B1B-CA2D-4DC5-B149-F773AE2C95A3}'
SOURCE = '{98D57DD7-9AB1-41D1-8178-817BE1CA061E}'
MEDIA = 'Originals/SFX/WAAPI Skill Integration V2/audit_close.wav'
FIXTURE_FILES = {
    'Events/Default Work Unit.wwu': '4228ada70ee414159caa1da41681d647956d2105c73ca7436fcd14bd57dab1be',
    'Containers/Default Work Unit.wwu': '23937bb856894f08578aecf93e3e44da31fbffd37a00efbd0144f2b11161b6ff',
    MEDIA: 'b1b29883097591b1de9a67ea780e0a2fef53784d2cd389c11d94bcaa0d695a97',
}
PREFIX = 'ak.wwise.core.'


def collect_loaded_event_probe(batch, public_call):
    """Attach to the existing owner; preserve blocked/partial data for finalization."""
    assert batch.selected_nodeids == (NODEID,) and batch.runtime.version == '2025.1'
    runtime = batch.runtime
    destination = Path(batch.node_runtimes[NODEID].runner_environment['WWISE_EVIDENCE_DIR'])
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / 'profiler-capture.json'
    report = {'contract': 'waapi-skill.owned-profiler-capture/v1', 'candidate': batch.candidate,
        'host': batch.info, 'version': '2025.1', 'complete': False, 'setup': [], 'errors': [],
        'scope': 'One 2025 capture-level Loaded Media read after Event preparation; no SDK-equivalence or causal proof',
        'outcomes': {OUTCOME: {'outcome': 'BLOCKED', 'reason': 'Probe setup incomplete'}},
        'limits': {'public_calls': 96, 'reply_bytes': 1024 * 1024,
            'total_reply_bytes': 8 * 1024 * 1024, 'reader_pages': 8},
        # node_gateway already performed config-set/status ownership checks.
        'public_call_count': len(batch.receipts[NODEID]), 'total_reply_bytes': 0,
        'cleanup': {'complete': False, 'receipts': [], 'errors': [],
            'capture_settings_prior_state_restored': False, 'audition_media_prior_state_restored': False,
            'boundary': 'Explicit owned capture stop/disable only; prior settings unknown; owned host teardown required'}}
    cleanup = []

    def persist():
        raw = (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode()
        assert len(raw) <= 1024 * 1024, 'Loaded probe report exceeds byte bound'
        temporary = path.with_suffix('.tmp')
        temporary.write_bytes(raw)
        temporary.replace(path)

    def call(argv):
        assert report['public_call_count'] < 96, 'Loaded probe public call bound exceeded'
        report['public_call_count'] += 1
        try:
            result = public_call(argv)
            size = len(json.dumps(result, ensure_ascii=False).encode())
            report['total_reply_bytes'] += size
            assert size <= report['limits']['reply_bytes'] and report['total_reply_bytes'] <= report['limits']['total_reply_bytes']
            return result
        finally:
            persist()

    def execute(preview, before_execute=None):
        tx = preview['transaction_id']
        shown = call(['transaction-show', tx])
        call(['confirm', tx, '--confirmation-token', shown['confirmation']['token']])
        if before_execute:
            before_execute()
        executed = call(['execute', tx])
        assert executed['state'] == 'executed_unverified', executed
        return call(['verify', tx])

    def effect(suffix, fields=(), *, event=False, before_execute=None):
        started = call(['draft-start', PREFIX + suffix])
        current, authority = started['draft'], started['task_authority']
        draft_id = current['draft_id']
        def step(command, values=()):
            nonlocal current
            result = call([command, draft_id, '--task-authority', authority,
                '--expected-revision', str(current['revision']), *values])
            current = result.get('draft', current)
            return result
        if event:
            bound = step('draft-bind-object', ['--role', 'target', '--object-id', EVENT])
            fields = ['--target-handle', bound['bound_object']['handle'], *fields]
        step('draft-declare-runtime-control-plan', fields)
        step('draft-check')
        return execute(step('preview-from-draft'), before_execute)

    def zero(suffix, before_execute=None):
        schema = call(['request-schema', PREFIX + suffix])
        return execute(call(schema['continuation']['gateway_argv']), before_execute)

    def exact(identity, kind, *fields):
        result = call(['query-object', '--exact-id', identity, '--max-results', '1', *fields])
        assert result['count'] == 1 and result.get('projection_complete') is not False, result
        row, = result['objects']
        assert row['id'] == identity and row['type'] == kind, row
        return row

    def fixture():
        files = {}
        for relative, expected in FIXTURE_FILES.items():
            proof = capture_file_proof(runtime.sandbox.sandbox_path / relative,
                field='owned Loaded probe fixture', io_root=runtime.owned_root, max_bytes=1024 * 1024)
            assert proof['sha256'] == expected, ('Loaded probe fixture differs', relative, proof)
            files[relative] = proof
        assert files[MEDIA]['size'] == 12404
        with wave.open(str(runtime.sandbox.sandbox_path / MEDIA)) as media:
            assert media.getnframes() > 0 and media.getframerate() > 0
        event = exact(EVENT, 'Event', '--include', 'child-count')
        action = exact(ACTION, 'Action', '--include', 'parent', '--include', 'action-type', '--include', 'target')
        sound = exact(SOUND, 'Sound', '--include', 'active-source')
        source = exact(SOURCE, 'AudioFileSource', '--include', 'parent', '--include', 'original-file-path')
        assert event['name'] == 'Play_Rifle_Close' and event['child_count'] == 1
        assert action['parent']['id'] == EVENT and action['action_type'] == 1 and action['target']['id'] == SOUND
        assert sound['active_source']['id'] == SOURCE and source['parent']['id'] == SOUND
        assert Path(localize_waapi_host_path(source['original_file_path'])).resolve(strict=True) == (runtime.sandbox.sandbox_path / MEDIA).resolve(strict=True)
        return {'files': files, 'event': event, 'action': action, 'sound': sound, 'source': source}

    persist()
    try:
        report['fixture_before'] = fixture()
        report['setup'].append(effect('transport.useOriginals', ['--audition-media', 'originals']))
        disable = lambda: effect('profiler.enableProfilerData', ['--capture-data', 'loaded-media', 'disable'])
        report['setup'].append(effect('profiler.enableProfilerData', ['--capture-data', 'loaded-media', 'enable'],
            before_execute=lambda: cleanup.append(('disable-loaded-media', disable))))
        report['setup'].append(zero('profiler.startCapture',
            lambda: cleanup.append(('stop-capture', lambda: zero('profiler.stopCapture')))))
        report['preparation'] = effect('transport.prepare', event=True)
        report['preparation']['sdk_prepare_event_equivalence_verified'] = False
        assert report['preparation']['verification']['business_state_verified'] is False
        time.sleep(0.25)
        position = call(['core-call', PREFIX + 'profiler.getCursorTime', '--profiler-cursor', 'capture-latest'])['agent_result']
        report['capture_position'] = position
        assert position['available'] is True and type(position['position_ms']) is int and position['position_ms'] >= 0
        evidence = {'position_ms': position['position_ms'], 'attribution_scope': 'capture',
            'owned_identity_observed': False, 'observation_status': 'BLOCKED',
            'preparation_or_streaming_control_effect_verified': False, 'pages': [], 'nonempty': False, 'complete': False}
        observation = report['outcomes'][OUTCOME] = {'outcome': 'BLOCKED', 'evidence': evidence}
        argv = ['core-call', PREFIX + 'profiler.getLoadedMedia', '--profiler-position', str(position['position_ms']), '--max-results', '64']
        snapshot = None
        while True:
            payload = call(argv)
            result = payload['agent_result']
            evidence['pages'].append(result)
            assert result.get('observation') == 'retained_profiler_capture_snapshot'
            assert isinstance(result.get('snapshot_sha256'), str) and len(result['snapshot_sha256']) == 64
            if snapshot is None:
                snapshot = (result['snapshot_sha256'], result['total_count'])
            assert (result['snapshot_sha256'], result['total_count']) == snapshot, 'Retained observation changed'
            assert isinstance(result['return'], list) and all(isinstance(row, dict) for row in result['return'])
            evidence['nonempty'] |= bool(result['return'])
            evidence['complete'] = result.get('complete') is True and not any('row_fragment' in page for page in evidence['pages'])
            if result.get('complete') is True:
                break
            if len(evidence['pages']) >= 8 or 'next_command' not in result:
                observation['reason'] = 'Retained page bound exhausted or continuation unavailable; partial observation retained'
                break
            argv = result['next_command']['gateway_argv']
        if evidence['complete']:
            evidence['observation_status'] = 'PASS'
            if evidence['nonempty']:
                observation['outcome'] = 'PASS'
            else:
                observation['reason'] = 'Valid empty capture observation; nonempty Loaded Media remains unresolved'
        else:
            observation.setdefault('reason', 'Incomplete retained observation; no additional native read')
    except Exception as exc:
        report['errors'].append({'type': type(exc).__name__, 'message': str(exc)[:4096]})
    finally:
        for label, action in reversed(cleanup):
            try:
                report['cleanup']['receipts'].append({'action': label, 'result': action()})
            except Exception as exc:
                report['cleanup']['errors'].append({'action': label, 'type': type(exc).__name__, 'message': str(exc)[:4096]})
            persist()
        try:
            report['fixture_after'] = fixture()
            assert report.get('fixture_before') == report['fixture_after'], 'Loaded probe fixture changed'
        except Exception as exc:
            report['cleanup']['errors'].append({'action': 'fixture-preservation', 'type': type(exc).__name__, 'message': str(exc)[:4096]})
        report['cleanup']['complete'] = not report['cleanup']['errors']
        report['complete'] = (not report['errors'] and report['cleanup']['complete']
            and report['outcomes'][OUTCOME]['outcome'] == 'PASS')
        persist()
    assert report['complete'], report
