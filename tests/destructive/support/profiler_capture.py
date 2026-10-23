"""Owned 2024 meter capture and 2025 meter/cursor/file/log observations.

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
CAPTURE_NODE_OUTCOMES = {NODEID: OUTCOMES, METER_2024_NODEID: OUTCOMES[:1]}
PREFIX = 'ak.wwise.core.'


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


def collect_owned_capture(batch, public_call):
    version = batch.runtime.version
    assert version in ('2024.1', '2025.1'), 'Capture cases are pinned to 2024.1/2025.1'
    nodeid = METER_2024_NODEID if version == '2024.1' else NODEID
    assert batch.selected_nodeids == (nodeid,), 'Capture requires its exact matching node'
    sound_id, bus_id, parent_id = (METER_2024_SOUND_ID, METER_2024_BUS_ID, METER_2024_PARENT_ID) if version == '2024.1' else (SOUND_ID, BUS_ID, PARENT_ID)
    parent_output, parent_key = ('volume-db', 'volume_db') if version == '2024.1' else ('work-unit-is-default', 'work_unit_is_default')
    destination = Path(batch.node_runtimes[nodeid].runner_environment['WWISE_EVIDENCE_DIR'])
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / 'profiler-capture.json'
    report = {'contract': 'waapi-skill.owned-profiler-capture/v1', 'candidate': batch.candidate,
        'host': batch.info, 'version': version, 'complete': False, 'setup': [], 'errors': [],
        'outcomes': {name: {'outcome': 'BLOCKED', 'reason': 'shared setup incomplete'} for name in CAPTURE_NODE_OUTCOMES[nodeid]},
        'cleanup': {'complete': False, 'receipts': [], 'errors': [],
            'capture_settings_prior_state_restored': False,
            'audition_media_prior_state_restored': False,
            'capture_settings_scope': 'Explicit enable/disable pair only; no prior global settings getter'},
        'limits': {'public_calls': 192, 'total_reply_bytes': 8 * 1024 * 1024,
            'reply_bytes': 1024 * 1024, 'meter_pages': 8}, 'public_call_count': 0, 'total_reply_bytes': 0}

    def persist():
        raw = (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode()
        assert len(raw) <= 1024 * 1024, 'Capture report byte bound exceeded'
        temporary = path.with_suffix('.tmp'); temporary.write_bytes(raw); temporary.replace(path)

    def call(argv):
        assert report['public_call_count'] < report['limits']['public_calls'], 'Capture public call bound exceeded'
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
        pending = [(name, action) for name, action in cleanup if name == label]
        assert len(pending) == 1, ('Cleanup ownership unavailable', label)
        name, action = pending[0]
        cleanup.remove(pending[0])
        try:
            result = action()
        except Exception as exc:
            report['cleanup']['errors'].append({'action': name, 'type': type(exc).__name__, 'message': str(exc)[:4096]})
            persist()
            raise
        report['cleanup']['receipts'].append({'action': name, 'result': result})
        persist()
        return result

    persist()
    try:
        from wwise_waapi.operation_soundbank import capture_file_proof
        media = batch.runtime.sandbox.sandbox_path / (METER_2024_MEDIA if version == '2024.1' else 'Originals/SFX/WAAPI Skill Integration V2/audit_tail.wav')
        proof = capture_file_proof(media, field='owned integration audio', io_root=batch.runtime.owned_root,
            max_bytes=16 * 1024 * 1024)
        with wave.open(str(media)) as source:
            assert source.getnframes() > 0 and source.getframerate() > 0
            duration = source.getnframes() / source.getframerate()
        report['fixture_media'] = {'proof': proof, 'duration_seconds': duration,
            'source_scope': ('One staged matching 2024 original; no authored XML/source edits' if version == '2024.1' else 'Existing integration-v2 audit_tail.wav; no source/media edits')}
        if version == '2024.1':
            staging = json.loads((batch.runtime.io_root / 'profiler-meter-media.json').read_text())
            assert proof['sha256'] == staging['source']['sha256'] == staging['staged']['sha256'] == METER_2024_MEDIA_SHA256
            report['fixture_media']['staging'] = staging
        looping = ['--include-field', 'IsLoopingEnabled', '--include-field', 'IsLoopingInfinite']
        if version == '2024.1':
            looping += ['--include', 'output-bus']
        original = exact(sound_id, *looping)
        assert original['name'] == ('MnGn_Barrel_Loop' if version == '2024.1' else 'RFL_Tail') and original['type'] == 'Sound', original
        props = original.get('properties', {})
        assert type(props.get('IsLoopingEnabled')) is bool and props.get('IsLoopingInfinite') is True, (
            'Owned fixture requires live boolean loop values and already-infinite mode', original)
        if version == '2024.1':
            assert props['IsLoopingEnabled'] is True and original.get('output_bus', {}).get('id') == bus_id, original
        bus_fields = ['--include', 'volume-db', '--include', 'parent']
        if version == '2024.1':
            bus_fields += ['--include-field', 'BusChannelConfig']
        before_bus = exact(bus_id, *bus_fields)
        before_parent = exact(parent_id, '--include', parent_output)
        assert before_bus['name'] == ('Guns' if version == '2024.1' else 'WAAPI_V2_Weapons') and before_bus['type'] == 'Bus', before_bus
        assert before_bus['parent']['id'] == parent_id, before_bus
        assert before_parent['type'] == ('Bus' if version == '2024.1' else 'WorkUnit'), before_parent
        assert type(before_parent.get(parent_key)) in ((int, float) if version == '2024.1' else (bool,)), before_parent
        report['fixture_before'] = {'sound': original, 'bus': before_bus, 'parent': before_parent}
        if version == '2024.1':
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
        report['setup'].append({'originals': effect('transport.useOriginals', ['--audition-media', 'originals'])})
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
        outcome(OUTCOMES[0], meters)
        # Freeze capture before independent cursor/file assertions. Each control
        # executes at most once; cleanup never repeats an attempted stop.
        report['setup'].append({'stop_capture': clean_one('stop-capture')})

        if version == '2025.1':
            def cursor():
                verified = effect('profiler.setCursorTime', ['--cursor-target-ms', fixed_time])
                scope = verified['verification']['verification_scope']['cursor_observation']
                read = call(['core-call', PREFIX + 'profiler.getCursorTime', '--profiler-cursor', 'user-cursor'])['agent_result']
                assert verified['verification']['business_state_verified'] is True and scope['outcome'] == 'matched', verified
                assert read['available'] is True and read['position_ms'] == scope['returned_time_ms'] == scope['observed_time_ms'], (scope, read)
                return {'requested_time_ms': position['position_ms'], 'snapped_time_ms': scope['returned_time_ms'],
                    'user_cursor': read, 'transaction': verified, 'capture_data_completeness_verified': False}
            outcome(OUTCOMES[1], cursor)

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

        if version == '2025.1':
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
                    'parent': exact(parent_id, '--include', parent_output)}
                report['fixture_after'] = after
                assert after == report['fixture_before'], 'Owned Sound/bus/parent values changed after cleanup'
        except Exception as exc:
            report['cleanup']['errors'].append({'action': 'fixture-preservation', 'type': type(exc).__name__, 'message': str(exc)[:4096]})
        report['cleanup']['complete'] = not report['cleanup']['errors']
        report['complete'] = (not report['errors'] and report['cleanup']['complete']
            and all(row['outcome'] == 'PASS' for row in report['outcomes'].values()))
        persist()
    assert report['complete'], report
