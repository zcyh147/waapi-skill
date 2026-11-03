"""One closed import fixture and bounded modern Marker transport observation."""
import copy
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import time
from types import SimpleNamespace
import uuid

import pytest

from tests.destructive.support.sandbox_fixture import hash_project
from tests.destructive.support.source_copy_fixture import read_file, sha, guid, _reject_symlink_chain
from tests.destructive.test_gateway_workflow_transaction_matrix import (
    workflow_sandbox_runtime, waapi_gateway,
    _start_business_draft, _bind_business_object, _update_business_draft, _complete_business_draft,
)
from tests.destructive.test_query_list_sequences import BUILDS, READ_APIS, _page_value
from tests.support.riff_wave import _tone_wav_bytes, _tone_marker_chunks
from wwise_waapi.canonical import canonical_json_bytes, canonical_sha256
from wwise_waapi.host_paths import localize_waapi_host_path

pytestmark = [pytest.mark.live, pytest.mark.destructive,
    pytest.mark.skipif(os.environ.get('WWISE_VERSION') != '2025.1',
        reason='First modern Marker transport observation is selected for2025.1.7.9143 only')]
REPO = Path(__file__).resolve().parents[2]
MODERN = ('2023.1', '2024.1', '2025.1')
MAX_DISPATCHES = 96
MAX_PACKET_BYTES = 8 * 1024 * 1024
MAX_CALLS = 20
IDENTITY = ('id', 'name', 'type', 'path')


def definition_evidence(version):
    """Packaged matching SDK declarations certify a candidate, never transport."""
    assert version in MODERN
    root = REPO / 'skills/waapi-skill'
    lists = json.loads((root / 'resources/metadata' / version / 'documented-list-fields.json').read_text())
    source, = [row for row in lists['classes'] if row['name'] == 'AudioFileSource']
    marker, = [row for row in lists['classes'] if row['name'] == 'Marker']
    field, = [row for row in source['lists'] if row['name'] == 'Markers']
    assert source['class_id'] == 16 and marker['class_id'] == 5373968
    assert field['declared_kind'] == 'List' and field['element_classes'] == [{'name': 'Marker', 'class_id': 5373968}]
    assert field['unresolved_element_types'] == []
    types = json.loads((root / 'resources/metadata' / version / 'object-types.json').read_text())
    row, = [row for row in types['types'] if row['name'] == 'Marker']
    assert row == {'name': 'Marker', 'classId': 5373968, 'type': 'WObject'}
    query = json.loads((root / 'references/semantic' / version / 'query-list-output-sources.json').read_text())
    assert 'markers.any()' in json.dumps(query) and 'Markers.{time, label}' in json.dumps(query)
    assert lists['source']['build'] == query['wwise_build'] == '.'.join(map(str, BUILDS[version]))
    return {'version': version, 'sdk': lists['source'], 'audio_file_source': source,
        'marker': marker, 'query_source_sha256': canonical_sha256(query), 'native_transport_proven': False}


def tree_frame(root, project):
    _reject_symlink_chain(project, owned_input=root, label='Marker fixture project')
    assert project.resolve().is_relative_to(root.resolve())
    return {'tree': asdict(hash_project(root, preferred_strategy='full')), 'project_mtime_ns': project.stat().st_mtime_ns}


def test_imported_modern_marker_has_canonical_identity_and_typed_values(workflow_sandbox_runtime, monkeypatch):
    runtime = workflow_sandbox_runtime
    assert runtime.version == '2025.1'
    assert tuple(runtime.sandbox.metadata.get_info_version[key] for key in ('year','major','minor','build')) == BUILDS[runtime.version]
    output = runtime.state_dir / 'query-modern-marker.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_chain(output.parent, owned_input=runtime.state_dir, label='Marker observation')
    assert not output.exists() and not output.is_symlink()
    evidence_root = Path(runtime.env['WWISE_EVIDENCE_DIR'])
    started = time.monotonic()
    observation = {'candidate': runtime.candidate, 'version': runtime.version, 'calls': [],
        'definitions': definition_evidence(runtime.version), 'transaction_count': 0,
        'setup_coverage_credit': False, 'positive_marker_proof': False, 'business_effect_verified': False,
        'scope': 'modern object-identity transport and typed Time/Label; no legacy Inner or complete-list support claim',
        'limits': {'public_calls': MAX_CALLS, 'dispatcher_packets': MAX_DISPATCHES,
            'native_packet_bytes': MAX_PACKET_BYTES, 'membership_rows': 2, 'exact_rows': 1, 'transactions': 1}}
    category = {'category': 'query-modern-marker', 'status': 'FAIL', 'observation_path': str(output),
        'verifier_strength': 'closed_import_media_hash_actual_source_mode_canonical_marker_class_owner_time_label_original_packets'}
    runtime.category_results.append(category)
    status = 'FAIL'; dispatch_count = 0; packet_bytes = 0; continuation_count = 0
    original_dispatch = waapi_gateway.WwiseDispatcher.dispatch
    config = Path(runtime.env['WAAPI_SKILL_CONFIG_PATH']); config_before = sha(read_file(config))
    source_root = runtime.sandbox.source_root
    assert source_root.resolve() != runtime.sandbox.sandbox_path.resolve()
    source_project = source_root / runtime.sandbox.sandbox_project.name

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
        # second grammar, silently set Manual Markers, or replay the import.
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

    def source_snapshot(identity):
        row, calls, packets = exact(identity, '--include', 'parent', '--include', 'original-file-path',
            '--include-field', 'MarkerInputMode')
        assert row['type'] == 'AudioFileSource' and row['class_id'] == 16
        value = row['properties']['MarkerInputMode']
        assert type(value) is int and value == 0, 'Fixture prerequisite: actual MarkerInputMode must be Import From File'
        native = original_row(calls, packets, identity, ['@MarkerInputMode'])
        assert type(native['@MarkerInputMode']) is int and native['@MarkerInputMode'] == 0
        infos = [packets[c['evidence_path']]['result'] for c in calls
            if c['api'].endswith('getPropertyInfo') and c['args'].get('property') == 'MarkerInputMode']
        assert infos and all(info.get('type') == 'int16' for info in infos)
        assert all(info.get('restriction', {}).get('type') == 'enum'
            and 0 in [item.get('value') for item in info['restriction'].get('values', [])] for info in infos)
        return row

    def baseline(sound_id, source_id):
        sound, _, _ = exact(sound_id, '--include', 'active-source', '--include', 'parent')
        source = source_snapshot(source_id)
        assert sound['type'] == 'Sound' and sound['class_id'] == 65552
        assert guid(sound['active_source']) == source_id and guid(source['parent']) == sound_id
        copied = Path(localize_waapi_host_path(source['original_file_path']))
        _reject_symlink_chain(copied, owned_input=runtime.sandbox.sandbox_path / 'Originals', label='Marker imported Originals')
        assert copied.resolve().is_relative_to((runtime.sandbox.sandbox_path / 'Originals').resolve())
        copied_body = read_file(copied, 16384)
        assert sha(copied_body) == observation['input_wav']['sha256']
        return {'sound': sound, 'source': source, 'copied_media': {'path': str(copied), 'bytes': len(copied_body), 'sha256': sha(copied_body)},
            'prepared': tree_frame(runtime.sandbox.sandbox_path, runtime.sandbox.sandbox_project)}

    try:
        observation['source_before'] = tree_frame(source_root, source_project)
        media_root = runtime.sandbox.sandbox_path / 'GatewayMarkerAudio'
        _reject_symlink_chain(media_root.parent, owned_input=runtime.sandbox.sandbox_path, label='Marker input parent')
        assert not media_root.exists() and not media_root.is_symlink()
        media_root.mkdir(exist_ok=False)
        media = media_root / 'R89_MARKER.wav'
        body = _tone_wav_bytes(channels=1, rate=8000, samples=[0] * 800,
            extra=_tone_marker_chunks([(91, 0, b'R89_MARKER\0')]))
        with media.open('xb') as stream: stream.write(body)
        observation['input_wav'] = {'path': str(media), 'bytes': len(body), 'sha256': sha(body),
            'pcm': {'channels': 1, 'bits': 16, 'rate_hz': 8000, 'frames': 800},
            'cue': {'file_identifier': 91, 'sample_offset': 0, 'label': 'R89_MARKER'}, 'native_record_count_assumed': False}
        draft = _start_business_draft(business, 'audio.import')
        parent = _bind_business_object(business, draft, path_segments=('Containers', 'Default Work Unit'))
        name = 'WAAPI_MARKER_' + uuid.uuid4().hex[:12]
        _update_business_draft(business, draft, 'draft-declare-import-batch',
            ['--row-order', 'marker', '--new-row', 'marker', parent, name, 'sound-sfx',
                '--media-directory', str(media_root), '--media-file', 'marker', media.name], live=False)
        setup = _complete_business_draft(business, draft)
        observation['transaction_count'] = 1
        observation['setup_transaction'] = setup
        imported = setup['execute']['dispatch_result']['result']['objects']
        sounds = [row for row in imported if row.get('type') == 'Sound']
        sound, = sounds; sound_id = guid(sound)
        # Resolve the actual active Source, then compare it with the import
        # result. A filename/cue ID is never used to invent a native identity.
        selected, _, _ = exact(sound_id, '--include', 'active-source')
        source_id = guid(selected['active_source'])
        candidates = [row for row in imported if row.get('id') == source_id and row.get('type') == 'AudioFileSource']
        imported_source, = candidates
        observation['baseline_before'] = before = baseline(sound_id, source_id)
        assert {key: before['source'][key] for key in IDENTITY} == {key: imported_source[key] for key in IDENTITY}
        rows, calls, packets = read(['query-object', '--advanced-waql', f'from object "{source_id}" select @Markers',
            '--max-results', '2', '--include', 'class-id', '--include', 'owner'])
        observation['membership'] = rows
        assert 0 < len(rows) < 2, 'Marker transport observation blocker: empty or reached the membership bound'
        assert all(isinstance(row, dict) and all(isinstance(row.get(key), str) for key in IDENTITY)
            and isinstance(row.get('owner'), dict) for row in rows), 'Marker transport observation blocker: non-object records require shape review'
        assert len({guid(row) for row in rows}) == len(rows), 'Marker transport identity association is ambiguous'
        for candidate in rows:
            marker_id = guid(candidate)
            assert candidate['id'] == marker_id and candidate['type'] == 'Marker' and candidate['class_id'] == 5373968
            assert type(candidate['class_id']) is int and guid(candidate['owner']) == source_id, 'Marker transport class/owner differs'
            native = original_row(calls, packets, marker_id, ['classId', 'owner'])
            assert native['classId'] == 5373968 and guid(native['owner']) == source_id
            row, value_calls, value_packets = exact(marker_id, '--include-field', 'Time', '--include-field', 'Label')
            assert all(row[key] == candidate[key] for key in (*IDENTITY, 'class_id', 'owner'))
            values = row['properties']
            assert type(values['Time']) in (int, float) and math.isfinite(values['Time']) and values['Time'] == 0
            assert type(values['Label']) is str and values['Label'] == 'R89_MARKER'
            raw = original_row(value_calls, value_packets, marker_id, ['@Time', '@Label'])
            assert type(raw['@Time']) in (int, float) and math.isfinite(raw['@Time']) and raw['@Time'] == 0
            assert raw['@Label'] == 'R89_MARKER'
            observation['marker'] = row
        observation['baseline_after'] = after = baseline(sound_id, source_id)
        assert canonical_json_bytes(before) == canonical_json_bytes(after), 'Exact imported baseline changed during read group'
        observation['source_after'] = tree_frame(source_root, source_project)
        assert observation['source_after'] == observation['source_before'], 'Immutable source changed'
        assert read_file(media, 16384) == body, 'Input cue WAV changed'
        observation.update(positive_marker_proof=True, business_effect_verified=True)
        status = 'PASS'
    except BaseException as exc:
        observation['observation_blocker'] = {'type': type(exc).__name__, 'message': str(exc)[:4096],
            'native_absence_proven': False, 'retry_performed': False}
        raise
    finally:
        config_stable = sha(read_file(config)) == config_before
        if not config_stable:
            status = 'FAIL'; observation.update(positive_marker_proof=False, business_effect_verified=False,
                finalization_error='Marker configuration drift')
        calls = observation['calls']
        observation['transaction_count'] = len({row['argv'][1] for row in calls if row['argv'][0] == 'execute'})
        handshakes = sum(row['argv'][0] not in waapi_gateway.OFFLINE_COMMANDS for row in calls)
        observation['budget'] = {'public_calls': len(calls), 'dispatcher_packets': dispatch_count,
            'version_handshakes': handshakes, 'native_calls': dispatch_count + handshakes,
            'native_packet_bytes': packet_bytes, 'continuations': continuation_count,
            'reply_bytes': sum(len(canonical_json_bytes(row.get('payload'))) for row in calls),
            'elapsed_seconds': round(time.monotonic() - started, 6)}
        body = json.dumps(observation, ensure_ascii=False, indent=2).encode()
        bounded = len(body) <= 16 * 1024 * 1024
        if not bounded:
            status = 'FAIL'; observation.update(positive_marker_proof=False, business_effect_verified=False,
                finalization_error='Observation exceeded16MiB; retained without truncation')
            body = json.dumps(observation, ensure_ascii=False, indent=2).encode()
        with output.open('xb') as stream: stream.write(body)
        category.update(status=status, observation_sha256=sha(body), business_effect_verified=observation['business_effect_verified'])
        assert config_stable, 'Marker configuration drift'
        assert bounded, 'Finalized observation exceeded16MiB'
