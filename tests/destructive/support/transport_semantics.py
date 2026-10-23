"""Three owned 2025 selected-edge observations; no inferred native semantics."""
from __future__ import annotations

import json
from pathlib import Path
from time import monotonic_ns
import wave

from tests.semantic.support.typed_gateway_input import discovered_business_field_handle

NODEID = ('tests/destructive/test_authoring_ui_business_live.py::'
    'test_runtime_owned_2025_selected_transport_semantics')
CONTRACT = 'waapi-skill.selected-transport-observations/v1'
SOUND_ID = '{FBF74BF9-8B83-44A8-AC8A-BA85372ECDC4}'
SOURCE_ID = '{6F767F75-9ED2-4860-A745-A5D905C6DF9C}'
PREFIX = 'ak.wwise.core.transport.'
CASES = (('D-one', 'play-directly', 'stopped'), ('P-one', 'pause', 'stopped'),
         ('T-one', 'toggle-play-stop', 'paused'))


def collect_selected_transport_semantics(batch, public_call):
    assert batch.runtime.version == '2025.1' and batch.selected_nodeids == (NODEID,)
    destination = Path(batch.node_runtimes[NODEID].runner_environment['WWISE_EVIDENCE_DIR'])
    destination.mkdir(parents=True, exist_ok=True)
    report_path = destination / 'transport-semantics.json'
    report = {'contract': CONTRACT, 'candidate': batch.candidate, 'version': '2025.1',
        'host': batch.info, 'complete': False, 'observation_task_status': 'BLOCKED',
        'business_effect_verified': False, 'coverage_credit': 'none_pending_semantics',
        'scope': 'three selected edges only; no all-active, acoustic, restart or bypass proof',
        'limits': {'public_calls': 210, 'cleanup_reserved_calls': 48,
            'reply_bytes': 1024 * 1024, 'total_reply_bytes': 8 * 1024 * 1024,
            'report_bytes': 1024 * 1024}, 'public_call_count': 0, 'total_reply_bytes': 0,
        'cases': [{'case_id': case, 'action': action, 'required_prestate': state,
                   'observation_status': 'BLOCKED', 'business_effect_verified': False,
                   'coverage_credit': 'none_pending_semantics'} for case, action, state in CASES],
        'setup': [], 'errors': [], 'cleanup': {'complete': False, 'receipts': [], 'errors': [],
            'audition_media_prior_state_restored': False,
            'audition_media_scope': 'Explicit originals setup only; prior global mode is not observed or restored'}}
    cleanup_phase, unsafe, handle, restore_loop = False, False, None, False
    original = None

    def persist():
        raw = (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        assert len(raw) <= report['limits']['report_bytes'], 'Transport report byte ceiling exceeded'
        temporary = report_path.with_suffix('.tmp')
        temporary.write_bytes(raw)
        temporary.replace(report_path)

    def call(argv):
        nonlocal unsafe
        ceiling = report['limits']['public_calls'] - (0 if cleanup_phase else report['limits']['cleanup_reserved_calls'])
        assert report['public_call_count'] < ceiling, 'Transport observation call budget exhausted'
        report['public_call_count'] += 1
        try:
            result = public_call(argv)
            size = len(json.dumps(result, ensure_ascii=False).encode('utf-8'))
            report['total_reply_bytes'] += size
            assert size <= report['limits']['reply_bytes'] and report['total_reply_bytes'] <= report['limits']['total_reply_bytes']
            return result
        except Exception:
            # No subsequent runtime/project write after an unavailable/unknown
            # Gateway outcome. Owned host shutdown still belongs to the owner.
            unsafe = True
            raise
        finally:
            persist()

    def exact(identity, *fields):
        result = call(['query-object', '--exact-id', identity, *fields])
        assert result['count'] == 1 and result.get('projection_complete') is not False, result
        row, = result['objects']
        assert row['id'] == identity and all(isinstance(row[key], str) and row[key] for key in ('name','type','path')), row
        return row

    def draft(operation, fields, *, identity=None, field=False):
        start = call(['draft-start', operation])
        current, authority = start['draft'], start['task_authority']
        def step(command, values=()):
            nonlocal current
            result = call([command, current['draft_id'], '--task-authority', authority,
                '--expected-revision', str(current['revision']), *values])
            current = result.get('draft', current)
            return result
        if identity:
            bound = step('draft-bind-object', [*(['--role','target'] if not field else []), '--object-id', identity])
            object_handle = bound['bound_object']['handle']
            if field:
                discovered = step('draft-discover-fields', ['--object-handle', object_handle, '--meaning', 'IsLoopingEnabled'])
                field_handle = discovered_business_field_handle(discovered, 'IsLoopingEnabled')
                step('draft-declare-field-change', ['--object-handle', object_handle,
                    '--field-handle', field_handle, '--business-value', *fields])
            else:
                step('draft-declare-runtime-control-plan', ['--target-handle', object_handle, *fields])
        else:
            step('draft-declare-runtime-control-plan', fields)
        step('draft-check')
        return step('preview-from-draft')

    def execute(preview, *, before_execute=None, record=None):
        nonlocal unsafe
        tx = preview['transaction_id']
        if record is not None:
            record.update(transaction_id=tx, artifact_hash=preview['artifact_hash'],
                journal_relative_path=f'setup-state/transactions/{tx}/events.jsonl')
        shown = call(['transaction-show', tx])
        call(['confirm', tx, '--confirmation-token', shown['confirmation']['token']])
        if before_execute:
            before_execute()
        if record is not None:
            record['execute_started_ns'] = monotonic_ns()
            persist()
        unsafe = True
        executed = call(['execute', tx])
        assert executed['state'] == 'executed_unverified', executed
        unsafe = False
        if record is not None:
            record['acknowledgement'] = {'state': executed['state'], 'executed': executed.get('executed'),
                'observed_at_ns': monotonic_ns()}
            persist()
        return call(['verify', tx])

    def action(name, *, before_execute=None, record=None):
        return execute(draft(PREFIX + 'executeAction', ['--audition-action', name,
            '--transport-scope','one-transport','--transport-handle', handle]),
            before_execute=before_execute, record=record)

    def state():
        value = call(['core-call', PREFIX + 'getState', '--transport-handle', handle])['agent_result']
        assert value['transport_handle'] == handle and value['state'] in {'playing','paused','stopped'}, value
        return {**value, 'observed_at_ns': monotonic_ns()}

    def set_loop(value):
        result = execute(draft('object.setProperty', [json.dumps(value)], identity=SOUND_ID, field=True))
        assert result['verification']['business_state_verified'] is True, result
        return result

    persist()
    try:
        from wwise_waapi.operation_soundbank import capture_file_proof
        media = batch.runtime.sandbox.sandbox_path / 'Originals/SFX/WAAPI Skill Integration V2/audit_tail.wav'
        report['media'] = capture_file_proof(media, field='owned existing transport media',
            io_root=batch.runtime.owned_root, max_bytes=16 * 1024 * 1024)
        with wave.open(str(media)) as source:
            assert source.getnframes() > 0 and source.getframerate() > 0
        fields = ['--include-field','IsLoopingEnabled','--include-field','IsLoopingInfinite','--include','active-source']
        original = exact(SOUND_ID, *fields)
        assert original['name'] == 'RFL_Tail' and original['type'] == 'Sound', original
        assert original['active_source']['id'] == SOURCE_ID, original
        source = exact(SOURCE_ID)
        assert source['type'] == 'AudioFileSource', source
        props = original['properties']
        assert type(props['IsLoopingEnabled']) is bool and props['IsLoopingInfinite'] is True, props
        report['fixture_before'] = {'sound': original, 'source': source}
        # The copied fixture owns the original PCM, not a converted cache.
        # Select it explicitly through the same public setup used by capture.
        originals = {'business_effect_verified': False}
        report['setup'].append({'originals': originals})
        selected = execute(draft(PREFIX + 'useOriginals', ['--audition-media', 'originals']), record=originals)
        originals['verification_state'] = selected['state']
        assert selected['state'] == 'result_schema_checked' and selected['verified'] is False, selected
        persist()
        if not props['IsLoopingEnabled']:
            # Restoration ownership precedes the attempted write.
            restore_loop = True
            report['setup'].append({'loop_enabled': set_loop(True)})
        created = execute(draft(PREFIX + 'create', [], identity=SOUND_ID))
        handle = created['agent_result']['business_result']['transport_handle']
        report['setup'].append({'created': created})
        for case in report['cases']:
            # Each case starts afresh from a known stopped target. These are
            # separately previewed setup calls, never retries of an edge action.
            stopped = action('stop')
            assert stopped['verification']['business_state_verified'] is True, stopped
            if case['required_prestate'] == 'paused':
                played = action('play')
                assert played['verification']['business_state_verified'] is True, played
                paused = action('pause')
                assert paused['verification']['business_state_verified'] is True, paused
            def observe_before():
                case['before'] = state()
                assert case['before']['state'] == case['required_prestate'], case
            case.update(controlled_object={key: original[key] for key in ('id','name','type','path')},
                source_id=SOURCE_ID, transport_handle=handle,
                association_journal_relative_path=f"setup-state/transactions/{created['transaction_id']}/events.jsonl")
            verified = action(case['action'], before_execute=observe_before, record=case)
            scope = verified['verification']['verification_scope']['observation']
            target, = scope['targets']
            assert scope['membership_matches'] is True and scope['scope'] == 'one-transport', scope
            assert target['outcome'] == 'semantics_unresolved' and verified['verified'] is False, verified
            case.update(after=target, verification_state=verified['state'],
                verification_observed_at_ns=monotonic_ns(), observation_status='OBSERVED')
            persist()
    except Exception as exc:
        report['errors'].append({'type': type(exc).__name__, 'message': str(exc)[:4096]})
    finally:
        cleanup_phase = True
        if unsafe:
            report['cleanup']['errors'].append({'action': 'further-writes-suppressed',
                'reason': 'Gateway outcome unavailable/uncertain; owner must stop and quarantine host'})
        else:
            steps = []
            if handle:
                steps.extend([('stop', lambda: action('stop')),
                    ('destroy', lambda: execute(draft(PREFIX + 'destroy', ['--transport-handle', handle])))])
            if restore_loop:
                steps.append(('restore-loop', lambda: set_loop(False)))
            for label, operation in steps:
                try:
                    result = operation()
                    assert result['verification']['business_state_verified'] is True, result
                    report['cleanup']['receipts'].append({'action': label, 'transaction_id': result['transaction_id']})
                except Exception as exc:
                    report['cleanup']['errors'].append({'action': label, 'type': type(exc).__name__, 'message': str(exc)[:4096]})
                    break
                finally:
                    persist()
            if not report['cleanup']['errors'] and original is not None:
                try:
                    report['fixture_after'] = {'sound': exact(SOUND_ID, *fields), 'source': exact(SOURCE_ID)}
                    assert report['fixture_after'] == report['fixture_before'], 'Selected transport fixture changed after cleanup'
                except Exception as exc:
                    report['cleanup']['errors'].append({'action': 'fixture-preservation', 'message': str(exc)[:4096]})
        report['cleanup']['complete'] = not report['cleanup']['errors']
        report['complete'] = (not report['errors'] and report['cleanup']['complete']
            and all(case['observation_status'] == 'OBSERVED' for case in report['cases']))
        report['observation_task_status'] = 'PASS' if report['complete'] else 'BLOCKED'
        persist()
    assert report['complete'], report
    return report
