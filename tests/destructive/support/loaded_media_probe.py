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


def collect_loaded_event_probe(batch, public_call, *, demo=None):
    """Attach to the existing owner; preserve blocked/partial data for finalization."""
    from tests.destructive.support.integration_demo import NODEID as DEMO_NODEID
    nodeid = DEMO_NODEID if demo is not None else NODEID
    assert batch.selected_nodeids == (nodeid,) and batch.runtime.version == '2025.1'
    if demo is not None:
        assert demo.context is batch.owner.developer_observation and demo.runtime is batch.runtime
    runtime = batch.runtime
    destination = Path(batch.node_runtimes[nodeid].runner_environment['WWISE_EVIDENCE_DIR'])
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / 'profiler-capture.json'
    report = {'contract': 'waapi-skill.owned-profiler-capture/v1', 'candidate': batch.candidate,
        'host': batch.info, 'version': '2025.1', 'complete': False, 'setup': [], 'errors': [],
        'scope': 'One 2025 capture-level Loaded Media read after Event preparation; no SDK-equivalence or causal proof',
        'outcomes': {OUTCOME: {'outcome': 'BLOCKED', 'reason': 'Probe setup incomplete'}},
        'limits': {'public_calls': 96, 'reply_bytes': 1024 * 1024,
            'total_reply_bytes': 8 * 1024 * 1024, 'reader_pages': 8},
        # node_gateway already performed config-set/status ownership checks.
        'public_call_count': len(batch.receipts[nodeid]),
        'total_reply_bytes': sum(len(json.dumps(receipt.get('payload', receipt), ensure_ascii=False).encode())
            for receipt in batch.receipts[nodeid]),
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
        before = len(batch.receipts[nodeid])
        try:
            return public_call(argv)
        finally:
            for receipt in batch.receipts[nodeid][before:]:
                size = len(json.dumps(receipt.get('payload', receipt), ensure_ascii=False).encode())
                report['total_reply_bytes'] += size
                assert size <= report['limits']['reply_bytes'], 'Loaded probe reply exceeds byte bound'
            assert report['total_reply_bytes'] <= report['limits']['total_reply_bytes'], 'Loaded probe replies exceed aggregate byte bound'
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

    def read_zero(suffix):
        schema = call(['request-schema', PREFIX + suffix])
        return call(schema['continuation']['gateway_argv'])

    def exact(identity, kind, *fields):
        result = call(['query-object', '--exact-id', identity, '--max-results', '1', *fields])
        assert result['count'] == 1 and result.get('projection_complete') is not False, result
        row, = result['objects']
        assert row['id'] == identity and row['type'] == kind, row
        return row

    def fixture():
        if demo is not None:
            return demo.proof()
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
        if demo is not None:
            report['scope'] = 'One matching 2025.1.11.9262 stock SDK PrepareEvent Area1 LoadedMedia observation; separate from pinned 9143 and old R106'
            report['reflection'] = demo.context.reflect(call, expected_info=batch.info)
            cleanup.append(('owned-demo-stop', demo.stop))
            report['demo'] = demo.start()
            time.sleep(1.0)  # One finite discovery interval, no discovery polling.
            consoles = read_zero('remote.getAvailableConsoles')['agent_result']['consoles']
            matches = [row for row in consoles if row.get('appName') == 'Integration Demo']
            assert len(matches) == 1, 'Owned Demo discovery is absent or ambiguous'
            console, = matches
            report['remote_port_ownership'] = demo.owns_port(console['commandPort'], console['host'])
            report['setup'].append(effect('remote.connect', ['--remote-host', console['host'],
                '--application-name', console['appName'], '--command-port', str(console['commandPort'])],
                before_execute=lambda: cleanup.append(('remote-disconnect', lambda: zero('remote.disconnect')))))
            connected = read_zero('remote.getConnectionStatus')['agent_result']
            assert connected.get('isConnected') is True and all(connected.get('console', {}).get(key) == console[key] for key in ('host', 'appName')), connected
            report['remote_connection'] = connected
        else:
            report['setup'].append(effect('transport.useOriginals', ['--audition-media', 'originals']))
        disable = lambda: effect('profiler.enableProfilerData', ['--capture-data', 'loaded-media', 'disable'])
        report['setup'].append(effect('profiler.enableProfilerData', ['--capture-data', 'loaded-media', 'enable'],
            before_execute=lambda: cleanup.append(('disable-loaded-media', disable))))
        report['setup'].append(zero('profiler.startCapture',
            lambda: cleanup.append(('stop-capture', lambda: zero('profiler.stopCapture')))))
        if demo is not None:
            report['producer_action'] = demo()
            report['preparation'] = {'producer': 'stock SDK DemoPrepare::EnterArea(1)',
                'sdk_prepare_event_source_backed': True, 'business_effect_requires_attributed_native_row': True}
        else:
            prepared = effect('transport.prepare', event=True)
            report['preparation'] = {'transaction': prepared, 'verification': prepared['verification'],
                'sdk_prepare_event_equivalence_verified': False}
            assert report['preparation']['verification']['status'] == 'result_schema_checked'
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
            if evidence['pages']:
                assert payload.get('retained_observation') is True and payload.get('native_read_dispatched') is False
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
                if evidence['complete']:
                    assert sum(len(page['return']) for page in evidence['pages']) == result['total_count'], 'Retained observation is missing rows'
                break
            if len(evidence['pages']) >= 8 or 'next_command' not in result:
                observation['reason'] = 'Retained page bound exhausted or continuation unavailable; partial observation retained'
                break
            argv = result['next_command']['gateway_argv']
        if evidence['complete']:
            evidence['observation_status'] = 'PASS'
            if evidence['nonempty']:
                if demo is not None:
                    rows = [row for page in evidence['pages'] for row in page['return']]
                    attributed = [row for row in rows if row.get('mediaId') == 124871431
                        and all(key in row for key in ('mediaId', 'fileName', 'format', 'size', 'soundBank'))
                        and type(row['size']) is int and row['size'] > 0
                        and all(isinstance(row[key], str) and row[key] for key in ('fileName', 'format', 'soundBank'))]
                    evidence.update(attribution_scope='owned-sdk-prepare-area1', owned_identity_observed=bool(attributed),
                        attributed_rows=attributed, unrelated_rows=[row for row in rows if row.get('mediaId') != 124871431])
                    if not attributed:
                        observation['reason'] = 'Complete snapshot lacks positive attributable Area1 media124871431'
                    else:
                        observation['outcome'] = 'PASS'
                else:
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
