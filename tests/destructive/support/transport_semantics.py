"""Owned versioned transport observations; no inferred native semantics."""
from __future__ import annotations

import json
import hashlib
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
OLDER_NODEID = ('tests/destructive/test_authoring_ui_business_live.py::'
    'test_runtime_owned_older_transport_semantics')
OLDER_CONTRACT = 'waapi-skill.older-transport-observations/v1'
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
OLDER_CASES = tuple((case, action, (state, 'stopped')) for case, action, state in CASES) + MIXED_CASES
_LOOP_FIXTURES = (
    ('{DB017C8E-EC99-415B-93CF-F7A6136D1AC2}', '{D6978600-772E-4D5E-8E67-A7C50CBCD7E0}',
     'MnGn_Barrel_Loop', 'Originals/SFX/Minigun/MnGn_Barrel_Loop.wav'),
    ('{9EEFCC8E-7FC2-4CDC-8BE9-C682F2CA77CC}', '{48770A4D-B8C3-41CF-AE3E-FB8651347736}',
     'Outside_Idle_1000', 'Originals/SFX/Car Engine/Porsche_Outside_Idle_1000_01.wav'),
)
# Each lane was independently checked against its matching committed WWU.
OLDER_FIXTURES = {
    '2021.1': _LOOP_FIXTURES,
    '2022.1': (
        ('{5D8F74B3-15C9-455F-8D95-8A877E59A7E1}', '{928E4D01-61C6-48E8-B633-06B9CA74916F}',
         'RFL_Tail', 'Originals/SFX/WAAPI Skill Integration V2/audit_tail.wav'),
        ('{324FA8E7-3AB1-4500-B326-09FBBB96A173}', '{9C7FEE5C-EC50-4339-BA6E-AB8007FDFB15}',
         'Rifle_Mechanical', 'Originals/SFX/WAAPI Skill Integration V2/rifle_mechanical_old.wav'),
    ),
    '2023.1': _LOOP_FIXTURES,
    '2024.1': _LOOP_FIXTURES,
}
INSTALLED_SAMPLE_ROOT = Path('/Applications/Audiokinetic')
OLDER_MEDIA_HASHES = {
    'Originals/SFX/Minigun/MnGn_Barrel_Loop.wav': '637e45b1415306ab6833da81607a4d1405136830b7828a291fa8721806dccb7d',
    'Originals/SFX/Car Engine/Porsche_Outside_Idle_1000_01.wav': '939e2d62dd820cb10ba571d769f7dbc0b5a3f170efaed94014e46df6f1e4038e',
}


def stage_owned_older_transport_media(sandbox, io_root, *, version):
    """Stage only the matching missing originals in the already-owned copy."""
    from wwise_waapi.filesystem_security import path_is_link_or_reparse
    from wwise_waapi.native_catalog import load_native_catalog
    from wwise_waapi.operation_soundbank import capture_file_proof, prove_artifact_path
    assert version in OLDER_FIXTURES
    if version == '2022.1':
        return
    build = load_native_catalog(version, 'wwise-authoring')['provenance']['build']
    source_root = INSTALLED_SAMPLE_ROOT / ('SampleProject' + build) / 'SampleProject'
    assert sandbox.sandbox_path.resolve(strict=True) != sandbox.source_root.resolve(strict=True)
    report = {'version': version, 'build': build, 'staged': [], 'complete': False, 'authored_xml_changed': False}
    report_path = io_root / 'transport-media.json'
    def persist():
        report_path.write_text(json.dumps(report, ensure_ascii=False) + '\n', encoding='utf-8')
    persist()
    for _, _, _, relative in OLDER_FIXTURES[version]:
        source, target = source_root / relative, sandbox.sandbox_path / relative
        expected = OLDER_MEDIA_HASHES[relative]
        before = capture_file_proof(source, field='matching installed original', io_root=source_root,
            max_bytes=16 * 1024 * 1024)
        assert before['sha256'] == expected, 'Matching installed original differs'
        with wave.open(str(source)) as pcm:
            assert pcm.getnframes() > 0 and pcm.getframerate() > 0
        prove_artifact_path(target, field='owned original destination', io_root=sandbox.sandbox_path,
            expect_directory=False)
        assert not any(path_is_link_or_reparse(part) for part in (target, *target.parents)
            if part.exists() or part.is_symlink()), 'Original destination traverses a link'
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open('rb') as original:
            raw = original.read(16 * 1024 * 1024 + 1)
        assert len(raw) == before['size'] and hashlib.sha256(raw).hexdigest() == expected
        with target.open('xb') as output:
            output.write(raw)
        staged = capture_file_proof(target, field='owned staged original', io_root=sandbox.sandbox_path,
            max_bytes=16 * 1024 * 1024)
        after = capture_file_proof(source, field='matching installed original', io_root=source_root,
            max_bytes=16 * 1024 * 1024)
        assert before == after and staged['sha256'] == expected, 'Original changed during staging'
        report['staged'].append({'source': before, 'staged': staged})
        persist()
    report['complete'] = True
    persist()


def collect_selected_transport_semantics(batch, public_call):
    return _collect_transport_semantics(batch, public_call, mixed=False)


def collect_mixed_transport_semantics(batch, public_call):
    return _collect_transport_semantics(batch, public_call, mixed=True)


def collect_older_transport_semantics(batch, public_call):
    return _collect_transport_semantics(batch, public_call, mixed=True, older=True)


def _collect_transport_semantics(batch, public_call, *, mixed, older=False):
    nodeid = OLDER_NODEID if older else MIXED_NODEID if mixed else NODEID
    version = batch.runtime.version
    assert version in (OLDER_FIXTURES if older else ('2025.1',)) and batch.selected_nodeids == (nodeid,)
    destination = Path(batch.node_runtimes[nodeid].runner_environment['WWISE_EVIDENCE_DIR'])
    destination.mkdir(parents=True, exist_ok=True)
    report_path = destination / ('transport-older-semantics.json' if older else 'transport-mixed-semantics.json' if mixed else 'transport-semantics.json')
    report = {'contract': OLDER_CONTRACT if older else MIXED_CONTRACT if mixed else CONTRACT, 'candidate': batch.candidate, 'version': version,
        'host': batch.info, 'complete': False, 'observation_task_status': 'BLOCKED',
        'business_effect_verified': False, 'coverage_credit': 'none_pending_semantics',
        'scope': ('three selected and five mixed pairs only; no acoustic, restart or bypass proof' if older else
            'five mixed all-active pairs only; no acoustic, restart or bypass proof' if mixed else
            'three selected edges only; no all-active, acoustic, restart or bypass proof'),
        **({'observation_time_boundary': 'Sequential verifier reads within the recorded call interval; no atomic snapshot or exact per-member observation time'} if mixed else {}),
        'limits': {'public_calls': 480 if mixed else 210, 'cleanup_reserved_calls': 64 if mixed else 48,
            'reply_bytes': 1024 * 1024, 'total_reply_bytes': 8 * 1024 * 1024,
            'report_bytes': 1024 * 1024}, 'public_call_count': 0, 'total_reply_bytes': 0,
        'cases': [{'case_id': case, 'action': action, 'required_prestate': list(state) if mixed else state,
                   'observation_status': 'BLOCKED', 'business_effect_verified': False,
                   **({'scope': 'one-transport' if case.endswith('-one') else 'all-active'} if older else {}),
                   'coverage_credit': 'none_pending_semantics'} for case, action, state in (OLDER_CASES if older else MIXED_CASES if mixed else CASES)],
        'setup': [], 'errors': [], 'cleanup': {'complete': False, 'receipts': [], 'errors': [],
            'audition_media_prior_state_restored': False,
            'audition_media_scope': ('No global audition-mode selection available or claimed on this version; preparation/playback checks only'
                if older and version in ('2021.1','2022.1') else
                'Explicit originals setup only; prior global mode is not observed or restored')}}
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
        if older and version == '2021.1':
            # The existing 2021 business output derives source identity in an
            # explicit view; it never dispatches a native activeSource accessor.
            fields += ['--platform','Mac','--language','SFX','--max-results','1']
        if older and version != '2022.1':
            staging = json.loads((batch.runtime.io_root / 'transport-media.json').read_text(encoding='utf-8'))
            assert staging['version'] == version and staging['complete'] is True and len(staging['staged']) == 2, staging
            report['media_staging'] = staging
        media_proofs = []
        fixtures = OLDER_FIXTURES[version] if older else FIXTURES if mixed else FIXTURES[:1]
        for sound_id, source_id, name, filename in fixtures:
            media = batch.runtime.sandbox.sandbox_path / (filename if older else 'Originals/SFX/WAAPI Skill Integration V2/' + filename)
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
        if older and version != '2022.1':
            for proof, staged in zip(media_proofs, report['media_staging']['staged']):
                assert all(proof[key] == staged['staged'][key] for key in ('path','sha256','size')), 'Staged original differs from its launch receipt'
        # The copied fixture owns the original PCM, not a converted cache.
        # Select it explicitly through the same public setup used by capture.
        if not older or version in ('2023.1','2024.1'):
            originals = {'business_effect_verified': False}
            report['setup'].append({'originals': originals})
            selected = execute(draft(PREFIX + 'useOriginals', ['--audition-media', 'originals']), record=originals)
            originals['verification_state'] = selected['state']
            assert selected['state'] == 'result_schema_checked' and selected['verified'] is False, selected
        if older and version == '2022.1':
            call(['request-schema', PREFIX + 'prepare'])
        persist()
        for fixture in fixture_before:
            original = fixture['sound']
            if not original['properties']['IsLoopingEnabled']:
                # Restoration ownership precedes the attempted write.
                restore_loops.append(original['id'])
                report['setup'].append({'loop_enabled': set_loop(True, original['id'])})
            if older and version == '2022.1':
                prepared = {'object_id': original['id'], 'business_effect_verified': False}
                report['setup'].append({'prepared': prepared})
                result = execute(draft(PREFIX + 'prepare', [], identity=original['id']), record=prepared)
                prepared['verification_state'] = result['state']
                assert result['state'] == 'result_schema_checked' and result['verified'] is False, result
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
            if older:
                report['playback_gate'] = {'complete': False, 'receipts': []}
                for selected_handle in handles:
                    for control in ('play','stop'):
                        record = {'action': control, 'transport_handle': selected_handle}
                        report['playback_gate']['receipts'].append(record)
                        result = action(control, selected_handle=selected_handle, record=record)
                        record['observation'] = result['verification']['verification_scope']['observation']
                        assert result['verification']['business_state_verified'] is True, result
                report['playback_gate']['complete'] = True
                persist()
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
                all_active = case.get('scope', 'all-active') == 'all-active'
                verified = action(case['action'], selected_handle=handles[0], all_active=all_active, before_execute=observe_pair, record=case)
                scope = verified['verification']['verification_scope']['observation']
                selected_members = members if all_active else members[:1]
                assert scope['membership_matches'] is True and scope['scope'] == case.get('scope', 'all-active'), scope
                assert {row['transport'] for row in scope['targets']} == {row['transport'] for row in selected_members}, scope
                case.update(after=[next(row for row in scope['targets'] if row['transport'] == member['transport'])
                        for member in selected_members], verification_state=verified['state'],
                    gateway_business_state_verified=verified['verification']['business_state_verified'],
                    verification_observed_at_ns=monotonic_ns())
                if not all_active:
                    case['unselected_after'] = state(handles[1])
                    case['unselected_state_matches_before'] = case['unselected_after']['state'] == case['before'][1]['state']
                case['observation_status'] = 'OBSERVED'
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
            case.update(after=target, verification_state=verified['state'],
                gateway_business_state_verified=verified['verification']['business_state_verified'],
                verification_observed_at_ns=monotonic_ns(), observation_status='OBSERVED')
            persist()
    except Exception as exc:
        report['errors'].append({'type': type(exc).__name__, 'message': str(exc)[:4096]})
    finally:
        cleanup_phase = True
        cleanup_start = report['public_call_count']
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
        if older:
            report['cleanup']['public_call_count'] = report['public_call_count'] - cleanup_start
        report['complete'] = (not report['errors'] and report['cleanup']['complete']
            and all(case['observation_status'] == 'OBSERVED' for case in report['cases']))
        report['observation_task_status'] = 'PASS' if report['complete'] else 'BLOCKED'
        persist()
    assert report['complete'], report
    return report
