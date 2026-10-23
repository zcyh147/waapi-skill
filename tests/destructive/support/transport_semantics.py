"""Owned 2025 selected and mixed observations; no inferred native semantics."""
from __future__ import annotations

import json
from pathlib import Path
from time import monotonic_ns
import wave

from tests.semantic.support.typed_gateway_input import discovered_business_field_handle

NODEID = ('tests/destructive/test_authoring_ui_business_live.py::'
    'test_runtime_owned_2025_selected_transport_semantics')
CONTRACT = 'waapi-skill.selected-transport-observations/v1'
MIXED_NODEID = ('tests/destructive/test_authoring_ui_business_live.py::'
    'test_runtime_owned_2025_mixed_transport_semantics')
MIXED_CONTRACT = 'waapi-skill.mixed-transport-observations/v1'
SOUND_ID = '{FBF74BF9-8B83-44A8-AC8A-BA85372ECDC4}'
SOURCE_ID = '{6F767F75-9ED2-4860-A745-A5D905C6DF9C}'
FIXTURES = (
    (SOUND_ID, SOURCE_ID, 'RFL_Tail', 'audit_tail.wav'),
    ('{80876919-C42E-4807-9595-900CC8405222}', '{66BDDC06-5699-4C17-A9DD-58119D7CE6BC}',
     'Rifle_Mechanical', 'rifle_mechanical_old.wav'),
)
PREFIX = 'ak.wwise.core.transport.'
CASES = (('D-one', 'play-directly', 'stopped'), ('P-one', 'pause', 'stopped'),
         ('T-one', 'toggle-play-stop', 'paused'))
MIXED_CASES = (('D-all', 'play-directly', ('playing', 'paused')),
    ('P-all-SP', 'pause', ('stopped', 'playing')),
    ('P-all-PQ', 'pause', ('playing', 'paused')),
    ('T-all-SP', 'toggle-play-stop', ('stopped', 'playing')),
    ('T-all-QS', 'toggle-play-stop', ('paused', 'stopped')))


def collect_selected_transport_semantics(batch, public_call):
    return _collect_transport_semantics(batch, public_call, mixed=False)


def collect_mixed_transport_semantics(batch, public_call):
    return _collect_transport_semantics(batch, public_call, mixed=True)


def _collect_transport_semantics(batch, public_call, *, mixed):
    nodeid = MIXED_NODEID if mixed else NODEID
    assert batch.runtime.version == '2025.1' and batch.selected_nodeids == (nodeid,)
    destination = Path(batch.node_runtimes[nodeid].runner_environment['WWISE_EVIDENCE_DIR'])
    destination.mkdir(parents=True, exist_ok=True)
    report_path = destination / ('transport-mixed-semantics.json' if mixed else 'transport-semantics.json')
    report = {'contract': MIXED_CONTRACT if mixed else CONTRACT, 'candidate': batch.candidate, 'version': '2025.1',
        'host': batch.info, 'complete': False, 'observation_task_status': 'BLOCKED',
        'business_effect_verified': False, 'coverage_credit': 'none_pending_semantics',
        'scope': ('five mixed all-active pairs only; no acoustic, restart or bypass proof' if mixed else
            'three selected edges only; no all-active, acoustic, restart or bypass proof'),
        **({'observation_time_boundary': 'Sequential verifier reads within the recorded call interval; no atomic snapshot or exact per-member observation time'} if mixed else {}),
        'limits': {'public_calls': 480 if mixed else 210, 'cleanup_reserved_calls': 64 if mixed else 48,
            'reply_bytes': 1024 * 1024, 'total_reply_bytes': 8 * 1024 * 1024,
            'report_bytes': 1024 * 1024}, 'public_call_count': 0, 'total_reply_bytes': 0,
        'cases': [{'case_id': case, 'action': action, 'required_prestate': list(state) if mixed else state,
                   'observation_status': 'BLOCKED', 'business_effect_verified': False,
                   'coverage_credit': 'none_pending_semantics'} for case, action, state in (MIXED_CASES if mixed else CASES)],
        'setup': [], 'errors': [], 'cleanup': {'complete': False, 'receipts': [], 'errors': [],
            'audition_media_prior_state_restored': False,
            'audition_media_scope': 'Explicit originals setup only; prior global mode is not observed or restored'}}
    cleanup_phase, unsafe, handle = False, False, None
    handles, restore_loops, fixture_before = [], [], []
    list_command = None
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
        if mixed and record is not None:
            record['verification_interval'] = {'started_ns': monotonic_ns()}
            try:
                return call(['verify', tx])
            finally:
                record['verification_interval']['finished_ns'] = monotonic_ns()
                persist()
        return call(['verify', tx])

    def action(name, *, selected_handle=None, all_active=False, before_execute=None, record=None):
        return execute(draft(PREFIX + 'executeAction', ['--audition-action', name,
            '--transport-scope', *(['all-active'] if all_active else
                ['one-transport', '--transport-handle', selected_handle or handle])]),
            before_execute=before_execute, record=record)

    def state(selected_handle=None):
        selected_handle = selected_handle or handle
        value = call(['core-call', PREFIX + 'getState', '--transport-handle', selected_handle])['agent_result']
        assert value['transport_handle'] == selected_handle and value['state'] in {'playing','paused','stopped'}, value
        return {**value, 'observed_at_ns': monotonic_ns()}

    def set_loop(value, identity=SOUND_ID):
        result = execute(draft('object.setProperty', [json.dumps(value)], identity=identity, field=True))
        assert result['verification']['business_state_verified'] is True, result
        return result

    def membership():
        nonlocal list_command
        if list_command is None:
            list_command = call(['request-schema', PREFIX + 'getList'])['continuation']['gateway_argv']
        rows = call(list_command)['agent_result']['list']
        assert len(rows) == 2 and len({row['transport'] for row in rows}) == 2, rows
        assert len({row['object'] for row in rows}) == 2, rows
        return sorted(rows, key=lambda row: row['transport'])

    persist()
    try:
        from wwise_waapi.operation_soundbank import capture_file_proof
        fields = ['--include-field','IsLoopingEnabled','--include-field','IsLoopingInfinite','--include','active-source']
        media_proofs = []
        for sound_id, source_id, name, filename in (FIXTURES if mixed else FIXTURES[:1]):
            media = batch.runtime.sandbox.sandbox_path / 'Originals/SFX/WAAPI Skill Integration V2' / filename
            media_proofs.append(capture_file_proof(media, field='owned existing transport media',
                io_root=batch.runtime.owned_root, max_bytes=16 * 1024 * 1024))
            with wave.open(str(media)) as source:
                assert source.getnframes() > 0 and source.getframerate() > 0
            original = exact(sound_id, *fields)
            assert original['name'] == name and original['type'] == 'Sound', original
            assert original['active_source']['id'] == source_id, original
            source = exact(source_id)
            assert source['type'] == 'AudioFileSource', source
            props = original['properties']
            assert type(props['IsLoopingEnabled']) is bool and props['IsLoopingInfinite'] is True, props
            fixture_before.append({'sound': original, 'source': source})
        report['fixture_before'] = fixture_before if mixed else fixture_before[0]
        report['media'] = media_proofs if mixed else media_proofs[0]
        # The copied fixture owns the original PCM, not a converted cache.
        # Select it explicitly through the same public setup used by capture.
        originals = {'business_effect_verified': False}
        report['setup'].append({'originals': originals})
        selected = execute(draft(PREFIX + 'useOriginals', ['--audition-media', 'originals']), record=originals)
        originals['verification_state'] = selected['state']
        assert selected['state'] == 'result_schema_checked' and selected['verified'] is False, selected
        persist()
        for fixture in fixture_before:
            original = fixture['sound']
            if not original['properties']['IsLoopingEnabled']:
                # Restoration ownership precedes the attempted write.
                restore_loops.append(original['id'])
                report['setup'].append({'loop_enabled': set_loop(True, original['id'])})
            created = execute(draft(PREFIX + 'create', [], identity=original['id']))
            handle = created['agent_result']['business_result']['transport_handle']
            handles.append(handle)
            report['setup'].append({'created': created})
        if mixed:
            assert len(set(handles)) == 2, handles
            bound = membership()
            members = []
            for fixture, selected_handle, setup in zip(fixture_before, handles,
                    [step['created'] for step in report['setup'] if 'created' in step]):
                association, = [row for row in bound if row['object'] == fixture['sound']['id']]
                members.append({**association, 'transport_handle': selected_handle,
                    'controlled_object': {key: fixture['sound'][key] for key in ('id','name','type','path')},
                    'source_id': fixture['source']['id'],
                    'association_journal_relative_path': f"setup-state/transactions/{setup['transaction_id']}/events.jsonl"})
            report['members'] = members
            for case in report['cases']:
                case['setup'] = []
                # Never use an investigated outcome as the next precondition.
                for selected_handle, required in zip(handles, case['required_prestate']):
                    controls = ['stop'] + ([] if required == 'stopped' else ['play']) + (['pause'] if required == 'paused' else [])
                    for control in controls:
                        record = {'action': control, 'transport_handle': selected_handle}
                        case['setup'].append(record)
                        result = action(control, selected_handle=selected_handle, record=record)
                        assert result['verification']['business_state_verified'] is True, result
                def observe_pair():
                    case['membership_before'] = membership()
                    assert case['membership_before'] == bound, case
                    case['before'] = [state(selected_handle) for selected_handle in handles]
                    assert [row['state'] for row in case['before']] == list(case['required_prestate']), case
                verified = action(case['action'], all_active=True, before_execute=observe_pair, record=case)
                scope = verified['verification']['verification_scope']['observation']
                assert scope['membership_matches'] is True and scope['scope'] == 'all-active', scope
                assert {row['transport'] for row in scope['targets']} == {row['transport'] for row in members}, scope
                case.update(after=[next(row for row in scope['targets'] if row['transport'] == member['transport'])
                        for member in members], verification_state=verified['state'],
                    gateway_business_state_verified=verified['verification']['business_state_verified'],
                    verification_observed_at_ns=monotonic_ns(), observation_status='OBSERVED')
                persist()
        for case in ([] if mixed else report['cases']):
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
            for selected_handle in handles:
                steps.extend([('stop', lambda selected_handle=selected_handle: action('stop', selected_handle=selected_handle)),
                    ('destroy', lambda selected_handle=selected_handle: execute(draft(PREFIX + 'destroy', ['--transport-handle', selected_handle])))])
            for identity in restore_loops:
                steps.append(('restore-loop', lambda identity=identity: set_loop(False, identity)))
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
                    after = [{'sound': exact(fixture['sound']['id'], *fields), 'source': exact(fixture['source']['id'])}
                        for fixture in fixture_before]
                    report['fixture_after'] = after if mixed else after[0]
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
