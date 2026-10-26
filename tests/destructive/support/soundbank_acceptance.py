"""Two bounded Core file effects under the existing workflow sandbox/finalizer."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import uuid
import xml.etree.ElementTree as ET

from tests.destructive.support.console_file_observation import observe_console_file
from tests.semantic.support.codex_project_prelaunch_v3 import WWISE_2025_SOUNDBANK_AURO_PROFILE
from wwise_waapi.operation_soundbank import capture_file_proof
from wwise_waapi.transactions import TransactionStore


def collect_core_file_acceptance(runtime):
    from tests.destructive.test_gateway_workflow_transaction_matrix import (
        _start_business_draft, _update_business_draft, _bind_business_object,
        _complete_business_draft, _write_fixture_wav, _write_external_sources_document,
    )
    output = runtime.state_dir / 'core-soundbank-file-acceptance.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    assert not output.exists(), 'Never replace an original Core file witness'
    categories = [{"category": category, "status": "FAIL", "transaction_ids": [],
        "observation_path": str(output), "verifier_strength": "public_verification_plus_independent_file_input_identity_preservation"}
        for category in ('core-soundbank-temporary-file', 'core-external-sources-default-output')]
    runtime.category_results.extend(categories)
    receipt = {"contract": "waapi-skill.core-soundbank-file-acceptance/v1", "version": runtime.version,
        "candidate": runtime.candidate, "prelaunch": runtime.soundbank_prelaunch,
        "complete": False, "calls": [], "phases": [], "inputs_before": {}, "failure": None,
        "limits": {"calls": 64, "reply_bytes": 262144, "receipt_bytes": 2097152}}
    attempted = set()

    def persist():
        raw = json.dumps(receipt, ensure_ascii=False, indent=2).encode('utf-8')
        assert len(raw) <= receipt['limits']['receipt_bytes']
        temporary = output.with_suffix('.tmp'); temporary.write_bytes(raw); temporary.replace(output)
        for category in categories:
            category['observation_sha256'] = hashlib.sha256(raw).hexdigest()

    class Gateway:
        version, lifecycle, port = runtime.version, runtime.lifecycle, runtime.port
        def raw_gateway(self, argv):
            assert len(receipt['calls']) < receipt['limits']['calls']
            if argv[0] == 'execute':
                assert argv[1] not in attempted, 'Never retry a Core file transaction'
                attempted.add(argv[1])
            row = {'argv': list(argv)}; receipt['calls'].append(row)
            try:
                code, payload = runtime.raw_gateway(argv)
                row.update(exit_code=code, payload=payload)
                assert len(json.dumps(payload, ensure_ascii=False).encode('utf-8')) <= receipt['limits']['reply_bytes']
                return code, payload
            finally:
                persist()
        def gateway(self, argv, *, live):
            code, payload = self.raw_gateway(argv)
            assert code == 0 and payload.get('ok') is True, payload
            if live:
                assert payload['detected_version'] == runtime.version
                assert payload['endpoint'] == {'host': runtime.lifecycle.host, 'port': runtime.port, 'url': runtime.lifecycle.waapi_url}
            return payload
    gateway = Gateway()
    owned = runtime.sandbox.sandbox_root.resolve(strict=True)

    def proof(path):
        return capture_file_proof(path, field='Core witness file', io_root=owned, max_bytes=8 * 1024 * 1024)

    def exact_event(identity):
        payload = gateway.gateway(['query-object', '--exact-id', identity, '--max-results', '2'], live=True)
        assert payload.get('projection_complete') is not False and payload.get('limit_reached') is not True
        assert payload['count'] == 1 and len(payload['objects']) == 1, payload
        return payload['objects'][0]

    def complete(draft, category, *, phase_name):
        phase = {'name': phase_name, 'effect_verified': False}; receipt['phases'].append(phase)
        def inspect(preview):
            category['transaction_ids'].append(preview['transaction_id'])
            phase['transaction_id'] = preview['transaction_id']
        result = _complete_business_draft(gateway, draft, inspect_preview=inspect, phase_receipt=phase)
        prepared = TransactionStore(runtime.state_dir).load_preview(phase['transaction_id']).artifact['prepared_operation']
        phase['native_dispatch'] = prepared['dispatch']
        plan = prepared['verification_plan']['plan']
        return phase, result, plan

    persist()
    try:
        assert runtime.version == '2025.1'
        isolation = receipt['prelaunch']['auro_soundbank_isolation']
        assert isolation['profile'] == WWISE_2025_SOUNDBANK_AURO_PROFILE
        assert isolation['remaining_auro_plugin_instances'] == isolation['remaining_auro_object_references'] == 0
        event_file = runtime.sandbox.sandbox_path / 'Events' / 'Default Work Unit.wwu'
        receipt['event_work_unit'] = observe_console_file(event_file, io_root=owned)
        events = ET.fromstring(base64.b64decode(receipt['event_work_unit']['content_base64'])).findall(".//Event[@Name='Play_Rifle']")
        assert len(events) == 1, 'Copied fixture must have one exact Play_Rifle Event'
        event_id = events[0].attrib['ID']
        event_before = exact_event(event_id)
        assert event_before['id'].casefold() == event_id.casefold() and event_before['name'] == 'Play_Rifle' and event_before['type'] == 'Event'
        receipt['event_before'] = event_before
        receipt['inputs_before'][str(event_file)] = proof(event_file)
        receipt['inputs_before'][str(runtime.sandbox.sandbox_project)] = proof(runtime.sandbox.sandbox_project)
        bank_name = 'Core_Witness_' + uuid.uuid4().hex[:12]
        draft = _start_business_draft(gateway, 'soundbank.generate')
        event = _bind_business_object(gateway, draft, object_id=event_id, role='event')
        _update_business_draft(gateway, draft, 'draft-declare-soundbank-plan', [
            '--temporary-soundbank', bank_name, 'nonlocalized', '--event', bank_name, event,
            '--platform', 'Windows', '--write-to-disk', 'true', '--skip-languages', 'true',
            '--io-root', str(owned)], live=True)
        phase, result, plan = complete(draft, categories[0], phase_name='temporary_bank_file')
        artifact, = plan['artifact_plan']['platforms'][0]['expected_user_soundbanks'][0]['expected_artifacts']
        phase['expected_artifact_path'] = artifact['path']
        phase['artifact'] = proof(Path(artifact['path']))
        assert phase['artifact']['size'] > 0
        assert phase['native_dispatch']['args']['soundbanks'][0]['events'] == [event_id]
        phase['event_after'] = exact_event(event_id)
        assert phase['event_after'] == event_before
        phase['inputs_after'] = {path: proof(Path(path)) for path in receipt['inputs_before']}
        assert phase['inputs_after'] == receipt['inputs_before'], 'Generation changed fixture inputs'
        phase['effect_verified'] = True; categories[0]['status'] = 'PASS'; persist()

        media = _write_fixture_wav(owned / 'core-external-media', 'external')
        source_list = owned / 'core-external.wsources'
        _write_external_sources_document(source_list, media_root=media.parent,
            project_root=runtime.sandbox.sandbox_path, source_file=media, destination='CoreWitness/external.wav')
        for path in (media, source_list): receipt['inputs_before'][str(path)] = proof(path)
        draft = _start_business_draft(gateway, 'soundbank.convertExternalSources')
        _update_business_draft(gateway, draft, 'draft-declare-soundbank-plan', [
            '--source', str(source_list), 'Windows', '--io-root', str(owned)], live=True)
        phase, result, plan = complete(draft, categories[1], phase_name='external_conversion_native_output_default')
        native_row, = phase['native_dispatch']['args']['sources']
        assert 'output' not in native_row, 'The witness must exercise real native output omission'
        request, = plan['requests']; artifact, = request['expected_outputs']
        phase['expected_artifact_path'] = artifact['absolute_path']
        phase['artifact'] = proof(Path(artifact['absolute_path']))
        assert phase['artifact']['size'] > 0 and Path(phase['artifact']['path']).suffix == '.wem'
        receipt['inputs_after'] = {path: proof(Path(path)) for path in receipt['inputs_before']}
        assert receipt['inputs_after'] == receipt['inputs_before'], 'Core file inputs changed'
        receipt['event_after'] = exact_event(event_id)
        assert receipt['event_after'] == event_before
        assert len(attempted) == 2 and len(receipt['phases']) == 2
        phase['effect_verified'] = True; categories[1]['status'] = 'PASS'
        receipt['complete'] = True
        return categories
    except BaseException as exc:
        receipt['failure'] = {'type': type(exc).__name__, 'message': str(exc)[:4096]}
        if hasattr(exc, 'as_dict'): receipt['failure']['details'] = exc.as_dict()
        raise
    finally:
        if not receipt['complete']:
            try:
                receipt['inputs_after'] = {path: proof(Path(path)) for path in receipt['inputs_before']}
                receipt['input_preservation_verified'] = bool(receipt['inputs_before']) and receipt['inputs_after'] == receipt['inputs_before']
            except Exception as exc:
                receipt['input_preservation_verified'] = False
                receipt['input_preservation_error'] = {'type': type(exc).__name__, 'message': str(exc)[:2048]}
        else:
            receipt['input_preservation_verified'] = True
        persist()
