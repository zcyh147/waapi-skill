"""Explicit manual Marker fixture on an existing private Source; no import/media generation."""
import copy
import json
import math
import os
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

from tests.destructive.support.source_copy_fixture import read_file, sha, guid, _reject_symlink_chain
from tests.destructive.test_gateway_workflow_transaction_matrix import (
    workflow_sandbox_runtime, waapi_gateway, _start_business_draft, _bind_business_object,
    _update_business_draft, _complete_business_draft,
)
from tests.destructive.test_query_list_sequences import BUILDS, READ_APIS, _page_value
from tests.destructive.test_query_modern_markers import tree_frame, definition_evidence
from wwise_waapi.canonical import canonical_json_bytes, canonical_sha256
from wwise_waapi.host_paths import localize_waapi_host_path

pytestmark = [pytest.mark.live, pytest.mark.destructive,
    pytest.mark.skipif(os.environ.get('WWISE_VERSION') != '2025.1', reason='First manual Marker native witness is selected for2025.1.7.9143 only')]
REPO = Path(__file__).resolve().parents[2]
SOUND_SEGMENTS = ('Containers', 'Default Work Unit', 'WAAPI Skill Integration V2', 'WeaponsAudit', 'Pistol', 'Rifle_Close')
MEDIA_RELATIVE = Path('Originals/SFX/WAAPI Skill Integration V2/audit_outside.wav')
MAX_CALLS = 48
MAX_DISPATCHES = 160
MAX_PACKET_BYTES = 8 * 1024 * 1024
IDENTITY = ('id', 'name', 'type', 'path')


def test_manual_marker_keeps_exact_source_and_typed_member_scope(workflow_sandbox_runtime, monkeypatch):
    runtime = workflow_sandbox_runtime
    assert runtime.version == '2025.1'
    assert tuple(runtime.sandbox.metadata.get_info_version[key] for key in ('year','major','minor','build')) == BUILDS[runtime.version]
    output = runtime.state_dir / 'query-manual-marker.json'; output.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_chain(output.parent, owned_input=runtime.state_dir, label='Manual Marker observation')
    assert not output.exists() and not output.is_symlink()
    evidence_root = Path(runtime.env['WWISE_EVIDENCE_DIR'])
    source_root = runtime.sandbox.source_root
    assert source_root.resolve() != runtime.sandbox.sandbox_path.resolve()
    source_project = source_root / runtime.sandbox.sandbox_project.name
    observation = {'candidate': runtime.candidate, 'version': runtime.version, 'calls': [],
        'definitions': definition_evidence(runtime.version), 'transaction_count': 0, 'setup_coverage_credit': False,
        'positive_marker_proof': False, 'business_effect_verified': False,
        'scope': 'one explicit manual WObject construction, canonical typed read and retained-GUID edit preparation without execution; imported/effective and older Inner Marker remain separate',
        'limits': {'public_calls': MAX_CALLS, 'dispatcher_packets': MAX_DISPATCHES, 'native_packet_bytes': MAX_PACKET_BYTES,
            'membership_rows': 2, 'exact_rows': 1, 'transactions': 1, 'new_imports': 0, 'new_wavs': 0}}
    category = {'category': 'query-manual-marker', 'status': 'FAIL', 'observation_path': str(output),
        'verifier_strength': 'explicit_manual_preview_once_existing_source_file_preservation_canonical_marker_class_owner_and_native_typed_values'}
    runtime.category_results.append(category)
    status = 'FAIL'; dispatch_count = 0; packet_bytes = 0; continuation_count = 0; started = time.monotonic()
    original_dispatch = waapi_gateway.WwiseDispatcher.dispatch
    config = Path(runtime.env['WAAPI_SKILL_CONFIG_PATH']); config_before = sha(read_file(config))
    def invoke(argv):
        nonlocal dispatch_count, packet_bytes
        assert len(observation['calls']) < MAX_CALLS
        before = set(evidence_root.glob('*.json')); calls = []
        record = {'argv': list(argv), 'dispatch_calls': calls, 'native_packets': []}; observation['calls'].append(record)
        def capture(dispatcher, api, **kwargs):
            nonlocal dispatch_count
            assert dispatch_count < MAX_DISPATCHES
            dispatch_count += 1
            call = {'api': api, **copy.deepcopy({key: kwargs.get(key) for key in ('version','args','options')})}; calls.append(call)
            result = original_dispatch(dispatcher, api, **kwargs)
            call.update(ok=result['ok'], evidence_path=result.get('evidence_path'), result_sha256=canonical_sha256(result.get('result')))
            return result
        with monkeypatch.context() as patch:
            patch.setattr(waapi_gateway.WwiseDispatcher, 'dispatch', capture)
            code, payload = runtime.raw_gateway(argv)
        record.update(exit_code=code, payload=payload)
        packets = {}
        for path in sorted(set(evidence_root.glob('*.json')) - before):
            body = read_file(path, MAX_PACKET_BYTES); packet_bytes += len(body)
            assert packet_bytes <= MAX_PACKET_BYTES
            record['native_packets'].append({'path': str(path), 'bytes': len(body), 'sha256': sha(body)})
            packets[str(path)] = json.loads(body)
        assert {call['evidence_path'] for call in calls} == set(packets)
        for call in calls:
            packet = packets[call['evidence_path']]
            assert packet['api'] == call['api'] and call['version'] == runtime.version
            assert packet['ok'] == call['ok'] and canonical_sha256(packet['result']) == call['result_sha256']
        # A new shape or native error is an observation blocker. Never try a
        # second grammar, add hidden settings, or replay the original write.
        assert code == 0 and payload.get('ok') is True, payload
        return payload, calls, packets

    def gateway(command, *, live):
        payload, _, _ = invoke(command)
        if live:
            assert payload['detected_version'] == runtime.version
            assert payload['endpoint'] == {'host': runtime.lifecycle.host, 'port': runtime.port, 'url': runtime.lifecycle.waapi_url}
        return payload

    business = SimpleNamespace(gateway=gateway)

    def read(argv):
        nonlocal continuation_count
        entries = []; encoding = None; offset = 0; all_calls = []; packets = {}
        while True:
            payload, calls, current = invoke(argv); all_calls.extend(calls); packets.update(current)
            assert all(call['api'] in READ_APIS for call in calls)
            assert list(payload)[-1] == 'agent_result'
            value = payload['agent_result']
            if isinstance(value, list):
                assert not entries and payload.get('projection_complete') is not False
                return value, all_calls, packets
            assert isinstance(value, dict) and 'entries_encoding' in value, value
            if encoding is None: encoding = value['entries_encoding']
            assert encoding == value['entries_encoding'] and value['page']['offset'] == offset
            entries.extend(value['entries']); offset += len(value['entries']); assert value['page']['next_offset'] == offset
            if value['projection_complete']: return _page_value(entries, encoding)['objects'], all_calls, packets
            assert continuation_count < 2, 'Unexpected delivery cost; stop without increasing the limit'
            continuation_count += 1; argv = value['next_command']['gateway_argv']
            assert 'query-object' in argv and '--result-query' in argv and '--result-page' in argv

    def exact(identity, *fields):
        rows, calls, packets = read(['query-object', '--exact-id', identity, '--max-results', '1',
            '--include', 'class-id', '--include', 'owner', *fields])
        row, = rows
        assert row['id'] == guid(identity) == identity
        assert all(isinstance(row[key], str) for key in IDENTITY) and row['path']
        assert type(row['class_id']) is int
        return row, calls, packets

    def original_row(calls, packets, identity, fields):
        rows = [row for call in calls if call['api'].endswith('object.get')
            and set(fields) <= set((call['options'] or {}).get('return', []))
            for row in packets[call['evidence_path']]['result']['return'] if row.get('id') == identity]
        row, = rows
        return row

    def membership(source_id):
        return read(['query-object', '--advanced-waql', f'from object "{source_id}" select @Markers',
            '--max-results', '2', '--include', 'class-id', '--include', 'owner'])

    def baseline(sound_id, source_id, expected_mode=None):
        sound, _, _ = exact(sound_id, '--include', 'active-source', '--include', 'parent', '--include', 'notes')
        source, calls, packets = exact(source_id, '--include', 'parent', '--include', 'notes', '--include', 'original-file-path',
            '--include-field', 'MarkerInputMode')
        assert sound['type'] == 'Sound' and sound['class_id'] == 65552 and guid(sound['active_source']) == source_id
        assert source['type'] == 'AudioFileSource' and source['class_id'] == 16 and guid(source['parent']) == sound_id
        value = source['properties']['MarkerInputMode']
        assert type(value) is int and value in (0, 1, 2) and (expected_mode is None or value == expected_mode)
        native = original_row(calls, packets, source_id, ['@MarkerInputMode'])
        assert type(native['@MarkerInputMode']) is int and native['@MarkerInputMode'] == value
        infos = [packets[c['evidence_path']]['result'] for c in calls
            if c['api'].endswith('getPropertyInfo') and c['args'].get('property') == 'MarkerInputMode']
        assert infos and all(info.get('type') == 'int16' and info.get('restriction', {}).get('type') == 'enum'
            and 2 in [row.get('value') for row in info['restriction'].get('values', [])] for info in infos)
        media = Path(localize_waapi_host_path(source['original_file_path']))
        expected = runtime.sandbox.sandbox_path / MEDIA_RELATIVE
        _reject_symlink_chain(media, owned_input=runtime.sandbox.sandbox_path / 'Originals', label='Existing manual Marker media')
        assert media.resolve() == expected.resolve()
        body = read_file(media, 16384)
        assert body == read_file(source_root / MEDIA_RELATIVE, 16384), 'Existing media changed'
        return {'sound': sound, 'source': source, 'media': {'path': str(media), 'bytes': len(body), 'sha256': sha(body)},
            'prepared': tree_frame(runtime.sandbox.sandbox_path, runtime.sandbox.sandbox_project)}

    try:
        observation['source_before'] = tree_frame(source_root, source_project)
        rows, _, _ = read(['query-object', *[arg for segment in SOUND_SEGMENTS for arg in ('--path-segment', segment)],
            '--max-results', '1', '--include', 'class-id', '--include', 'active-source'])
        selected, = rows
        assert selected['type'] == 'Sound' and selected['class_id'] == 65552
        sound_id, source_id = guid(selected), guid(selected['active_source'])
        initial = baseline(sound_id, source_id); observation['before_setup'] = initial
        empty, _, _ = membership(source_id)
        observation['before_setup_membership'] = empty
        assert empty == [], 'Manual fixture requires a complete empty stored Marker baseline below the two-row bound'
        draft = _start_business_draft(business, 'object.set')
        owner = _bind_business_object(business, draft, object_id=source_id)
        def field(scope, meaning):
            result = _update_business_draft(business, draft, 'draft-discover-fields', [*scope, '--meaning', meaning], live=True)
            candidates = [candidate for row in result['meaning_results'] for candidate in row['candidates']]
            candidate, = candidates
            return candidate['handle']
        mode = field(['--object-handle', owner], 'MarkerInputMode')
        _update_business_draft(business, draft, 'draft-declare-existing',
            ['--declaration-id', 'source', '--object-handle', owner, '--field-value', mode, '2'], live=False)
        listed = _update_business_draft(business, draft, 'draft-discover-fields',
            ['--object-handle', owner, '--field-source', 'documented-lists', '--list'], live=True)
        marker_list, = [row for row in listed['agent_result']['items'] if row['name'] == 'Markers']
        bound = _update_business_draft(business, draft, 'draft-discover-fields',
            ['--object-handle', owner, '--field-source', 'documented-lists', '--selection', marker_list['selection']], live=True)
        marker_list = bound['meaning_results'][0]['candidates'][0]['handle']
        found = _update_business_draft(business, draft, 'draft-discover-types', ['--role', 'object', '--meaning', 'Marker'], live=True)
        kind, = found['type_candidates']; kind = kind['handle']
        marker_time, label = field(['--type-handle', kind], 'Time'), field(['--type-handle', kind], 'Label')
        _update_business_draft(business, draft, 'draft-declare-new',
            ['--declaration-id', 'marker', '--parent-handle', owner, '--kind', kind, '--field', 'object_list', marker_list,
                '--field-value', marker_time, '0', '--field-value', label, 'R90_MARKER'], live=False)
        observation['setup_transaction'] = _complete_business_draft(business, draft)
        observation['baseline_before'] = before = baseline(sound_id, source_id, 2)
        expected = copy.deepcopy(initial); expected['source']['properties']['MarkerInputMode'] = 2
        assert before == expected, 'Source, Sound or media changed outside the requested manual mode/list setup'
        rows, calls, packets = membership(source_id); observation['membership'] = rows
        assert 0 < len(rows) < 2, 'Manual Marker population empty or reached the two-row observation bound'
        marker, = rows; marker_id = guid(marker)
        assert marker['id'] == marker_id and marker['name'] == '' and marker['type'] == 'Marker'
        assert type(marker['class_id']) is int and marker['class_id'] == 5373968 and guid(marker['owner']) == source_id
        native = original_row(calls, packets, marker_id, ['classId', 'owner'])
        assert native['name'] == '' and native['classId'] == 5373968 and guid(native['owner']) == source_id
        row, calls, packets = exact(marker_id, '--include-field', 'Time', '--include-field', 'Label')
        assert all(row[key] == marker[key] for key in (*IDENTITY, 'class_id', 'owner'))
        values = row['properties']
        assert type(values['Time']) in (int, float) and math.isfinite(values['Time']) and values['Time'] == 0
        assert type(values['Label']) is str and values['Label'] == 'R90_MARKER'
        native = original_row(calls, packets, marker_id, ['@Time', '@Label'])
        assert type(native['@Time']) in (int, float) and math.isfinite(native['@Time']) and native['@Time'] == 0
        assert native['@Label'] == 'R90_MARKER'
        observation['marker'] = row
        edit = _start_business_draft(business, 'object.set')
        retained = _bind_business_object(business, edit, object_id=marker_id)
        found = _update_business_draft(business, edit, 'draft-discover-fields',
            ['--object-handle', retained, '--meaning', 'Label'], live=True)
        selected_label, = [candidate for meaning in found['meaning_results'] for candidate in meaning['candidates']]
        _update_business_draft(business, edit, 'draft-declare-existing',
            ['--declaration-id', 'retained-marker', '--object-handle', retained,
                '--field-value', selected_label['handle'], 'R90_PREPARED_ONLY'], live=False)
        observation['retained_edit_preparation'] = _update_business_draft(business, edit, 'draft-check', live=True)
        observation['retained_edit_executed'] = False
        unchanged, _, _ = exact(marker_id, '--include-field', 'Time', '--include-field', 'Label')
        assert unchanged == row, 'Read-only retained Marker preparation changed actual identity or values'
        observation['baseline_after'] = after = baseline(sound_id, source_id, 2)
        assert after == before and membership(source_id)[0] == rows, 'Exact Source/member/media baseline changed during the read group'
        observation['source_after'] = tree_frame(source_root, source_project)
        assert observation['source_after'] == observation['source_before']
        observation.update(positive_marker_proof=True, business_effect_verified=True); status = 'PASS'
    except BaseException as exc:
        observation['observation_blocker'] = {'type': type(exc).__name__, 'message': str(exc)[:4096],
            'native_absence_proven': False, 'retry_performed': False}
        raise
    finally:
        config_stable = sha(read_file(config)) == config_before
        if not config_stable:
            status = 'FAIL'; observation.update(positive_marker_proof=False, business_effect_verified=False, finalization_error='Configuration drift')
        calls = observation['calls']
        observation['transaction_count'] = len({row['argv'][1] for row in calls if row['argv'][0] == 'execute'})
        handshakes = sum(row['argv'][0] not in waapi_gateway.OFFLINE_COMMANDS for row in calls)
        observation['budget'] = {'public_calls': len(calls), 'dispatcher_packets': dispatch_count,
            'version_handshakes': handshakes, 'native_calls': dispatch_count + handshakes, 'native_packet_bytes': packet_bytes,
            'continuations': continuation_count, 'reply_bytes': sum(len(canonical_json_bytes(row.get('payload'))) for row in calls),
            'elapsed_seconds': round(time.monotonic() - started, 6)}
        body = json.dumps(observation, ensure_ascii=False, indent=2).encode(); bounded = len(body) <= 16 * 1024 * 1024
        if not bounded:
            status = 'FAIL'; observation.update(positive_marker_proof=False, business_effect_verified=False, finalization_error='Observation exceeded16MiB; retained without truncation')
            body = json.dumps(observation, ensure_ascii=False, indent=2).encode()
        with output.open('xb') as stream: stream.write(body)
        category.update(status=status, observation_sha256=sha(body), business_effect_verified=observation['business_effect_verified'])
        assert config_stable and bounded
