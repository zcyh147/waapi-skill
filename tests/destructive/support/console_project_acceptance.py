"""Bounded Console project witnesses; native I/O stays in the existing lifecycle."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

from wwise_waapi.console_media_ids import compact_records, mapping_records, work_unit_records, project_storage_mode
from wwise_waapi.console_project_operations import _read_xml_artifact, _project_model_paths
from wwise_waapi.operation_soundbank import capture_artifact_tree, capture_file_proof
from wwise_waapi.transactions import TransactionStore
from tests.destructive.support.console_file_observation import observe_console_file, ConsoleModelImageIndex

FIXTURES = Path(__file__).resolve().parents[2] / 'fixtures/console-project-184'
NODE_CASES = {
    'test_console_project_cli_create_acceptance': ('cli-create', '2024.1', 1),
    'test_console_project_create_close_acceptance': ('create-close', '2025.1', 2),
    'test_console_project_add_platform_copy_acceptance': ('add-copy', '2025.1', 2),
    'test_console_project_migrate_created_fixture_acceptance': ('migrate', '2025.1', 1),
    'test_console_project_media_ids_to_work_units_acceptance': ('media-back', '2025.1', 2),
    'test_console_project_media_ids_refresh_acceptance': ('media-refresh', '2025.1', 2),
}


def select_console_project_case(nodeids, version):
    selected = [NODE_CASES[node.split('::')[-1]] for node in nodeids if node.split('::')[-1] in NODE_CASES]
    if not selected: return None
    assert len(selected) == len(nodeids) == 1, 'Console project witnesses require one exact node per owned lifecycle'
    case, expected_version, _ = selected[0]
    assert version == expected_version, 'Console project witness version differs from its pinned selection'
    return case


def prepare_console_project_environment(environment, case):
    """Validate donor authority before the ordinary lifecycle copies or launches."""
    environment = dict(environment)
    if case == 'cli-create':
        destination = environment.get('WWISE_CATEGORY_EVIDENCE_PATH')
        assert destination and Path(destination).is_absolute(), 'Pin the existing category writer path before CLI creation'
    if case == 'migrate':
        manifest = environment.get('WAAPI_CONSOLE184_CREATED_MANIFEST')
        assert manifest, 'Migration needs the original successful CLI-create manifest'
        project, _ = load_created_fixture(manifest)
        environment['WWISE_SAMPLE_PROJECT_PATH'] = str(project)
    return environment


def retained_mapping():
    metadata = json.loads((FIXTURES / 'media-ids-2025.1.json').read_text())
    compressed = (FIXTURES / 'media-ids-2025.1.xml.gz').read_bytes()
    assert hashlib.sha256(compressed).hexdigest() == metadata['compressed_sha256']
    raw = gzip.decompress(compressed)
    assert len(raw) == metadata['mapping_bytes'] <= 8 * 1024 * 1024
    assert hashlib.sha256(raw).hexdigest() == metadata['mapping_sha256']
    document = ET.fromstring(raw)
    records = mapping_records(document)
    assert len(records) == metadata['expected_media_records']
    return raw, records, metadata


def media_model(project):
    project = Path(project)
    rows, descriptors, documents = [], [], {}
    for path in _project_model_paths(str(project), str(project.parent)):
        document, proof = _read_xml_artifact(path, str(project.parent))
        records, sources, unresolved = work_unit_records(document)
        assert not unresolved, 'Unestablished saved media descriptors'
        rows.extend(records); descriptors.extend(sources)
        documents[Path(path)] = (document, proof)
    return rows, descriptors, documents


def stage_media_storage_fixture(project, *, central):
    """Apply only the captured storage projection to an owned prelaunch copy."""
    project = Path(project)
    raw, expected, metadata = retained_mapping()
    rows, sources, documents = media_model(project)
    expected_sources = list({row[0]: row[:4] for row in expected}.values())
    assert compact_records(rows) == compact_records(expected) and compact_records(sources) == compact_records(expected_sources), \
        'Retained mapping must match complete source/media records before fixture staging'
    before = compact_records(rows)
    for path, (document, _) in documents.items():
        if path == project:
            # Captured native save adds this direct setting while leaving the
            # source SharedValues settings intact. Never reinterpret that backing
            # row as the active field or remove it from model preservation.
            assert project_storage_mode(document) is None
            properties = document.find('./ProjectInfo/Project/PropertyList')
            if properties is None:
                properties = ET.SubElement(document.find('./ProjectInfo/Project'), 'PropertyList')
            field = ET.fromstring(metadata['direct_storage_property_xml'])
            field.set('Value', 'True' if central else 'False')
            properties.append(field)
        elif central:
            for source in document.iter():
                for ids in source.findall('MediaIDList'):
                    assert source.tag in {'AudioFileSource', 'MidiFileSource', 'PluginMediaSource'}
                    source.remove(ids)
        if path == project or central:
            ET.ElementTree(document).write(path, encoding='utf-8', xml_declaration=True)
    if central:
        project.with_suffix('.mediaid').write_bytes(raw)
    after, after_sources, _ = media_model(project)
    assert compact_records(sources) == compact_records(after_sources)
    return {'donor': metadata, 'mapping_records': compact_records(expected),
        'work_unit_records_before': before, 'work_unit_records_after': compact_records(after),
        'source_descriptors_preserved': True}


def file_inventory(root):
    tree = capture_artifact_tree(root, io_root=root, max_files=512, max_entries=16384,
        max_total_bytes=32 * 1024 * 1024, max_file_bytes=8 * 1024 * 1024, max_depth=64)
    return [{key: row[key] for key in ('path', 'size', 'sha256')} for row in tree['files']]


def saved_project(project):
    document, proof = _read_xml_artifact(str(project), str(Path(project).parent))
    node = document.find('./ProjectInfo/Project')
    assert node is not None
    return {'id': node.get('ID'), 'name': node.get('Name'), 'wwise_version': document.get('WwiseVersion'),
        'platforms': [[p.get('Name'), p.get('ReferencePlatform')] for p in node.findall('./Platforms/Platform')],
        'languages': [p.get('Name') for p in node.findall('./LanguageList/Language')], 'file_proof': proof}


def export_created_fixture(project, destination, *, runtime, transaction):
    assert not destination.exists()
    rows, _, _ = media_model(project)
    assert rows == [], 'Migration donor must be the native-created media-free project'
    inventory = file_inventory(project.parent)
    shutil.copytree(project.parent, destination / 'project')
    assert inventory == file_inventory(destination / 'project') == file_inventory(project.parent)
    manifest = destination / 'manifest.json'
    data = {'contract': 'waapi-skill.console-created-project-donor/v1', 'version': runtime.version,
        'candidate': runtime.candidate, 'project_name': project.name, 'files': inventory,
        'creation_transaction': transaction, 'category_evidence': os.environ['WWISE_CATEGORY_EVIDENCE_PATH']}
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2).encode()
    manifest.write_bytes(raw)
    return {'manifest': str(manifest), 'manifest_sha256': hashlib.sha256(raw).hexdigest()}


def load_created_fixture(manifest):
    """A is reusable only after its actual existing final writer seals PASS."""
    manifest = Path(manifest)
    assert manifest.is_absolute()
    proof = capture_file_proof(manifest, field='created project manifest', io_root=manifest.parent, max_bytes=1024 * 1024)
    data = json.loads(manifest.read_bytes())
    assert data['contract'] == 'waapi-skill.console-created-project-donor/v1' and data['version'] == '2024.1'
    name = data['project_name']
    assert Path(name).name == name and Path(name).suffix == '.wproj'
    root = manifest.parent / 'project'
    assert file_inventory(root) == data['files'], 'Created donor bytes differ from their sealed inventory'
    evidence = Path(data['category_evidence'])
    capture_file_proof(evidence, field='original creation category evidence', io_root=evidence.parent, max_bytes=8 * 1024 * 1024)
    matching = [row for line in evidence.read_text().splitlines() for row in [json.loads(line)]
        if row.get('candidate') == data['candidate'] and row.get('version') == '2024.1'
        and row.get('invocation', {}).get('phase') == 'final' and row['invocation']['outcome'] == 'PASS'
        and any(c.get('created_fixture') == {'manifest': str(manifest), 'manifest_sha256': proof['sha256']}
            and c['status'] == 'PASS' for c in row['categories'])
        and any(t['transaction_id'] == data['creation_transaction'] and t['state'] == 'verified' for t in row['transactions'])]
    assert len(matching) == 1, 'Created donor requires one original final PASS with its exact manifest and transaction'
    project = root / name
    observed = saved_project(project)
    assert observed['wwise_version'].startswith('v2024.1.') and observed['name'] == project.stem
    assert media_model(project)[0] == []
    return project, {**data, 'manifest': str(manifest), 'manifest_sha256': proof['sha256']}


def platform_values(project, platform):
    rows = []
    for path in _project_model_paths(str(project), str(project.parent)):
        document, _ = _read_xml_artifact(path, str(project.parent))
        for field in document.iter('Property'):
            for value in field.findall('./ValueList/Value'):
                if value.get('Platform') == platform:
                    rows.append([Path(path).relative_to(project.parent).as_posix(), field.get('Name'),
                        value.text, sorted((key, item) for key, item in value.attrib.items() if key != 'Platform')])
    return sorted(rows, key=repr)


def retain_model(project, root, phase):
    root.mkdir(parents=True, exist_ok=True)
    link = {}; image = ConsoleModelImageIndex(root=root, project=project, phase=phase, link=link)
    for path in _project_model_paths(str(project), str(project.parent)):
        image.save(Path(path), observe_console_file(Path(path), io_root=project.parent))
    image.finish()
    return link


def collect_console_project_acceptance(runtime, case):
    """One selected witness, captured through the existing public Gateway path."""
    from tests.destructive.test_gateway_workflow_transaction_matrix import (
        _start_business_draft, _update_business_draft, _complete_business_draft, _save_sandbox_project,
    )
    assert case in {'cli-create', 'create-close', 'add-copy', 'migrate', 'media-back', 'media-refresh'}
    assert runtime.version == ('2024.1' if case == 'cli-create' else '2025.1')
    if case == 'cli-create':
        assert os.environ.get('WWISE_CATEGORY_EVIDENCE_PATH'), 'Pin the existing final category writer path for the migration donor'
    output = runtime.state_dir / ('console184-' + case + '.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    assert not output.exists(), 'Never replace a Console witness'
    category = {'category': 'console184-' + case, 'status': 'FAIL', 'transaction_ids': [],
        'observation_path': str(output), 'verifier_strength': 'public_gateway_and_independent_saved_project_effect'}
    runtime.category_results.append(category)
    receipt = {'contract': 'waapi-skill.console-project-acceptance/v1', 'case': case,
        'candidate': runtime.candidate, 'version': runtime.version, 'complete': False, 'calls': [], 'phases': [],
        'limits': {'calls': 96, 'reply_bytes': 512 * 1024, 'receipt_bytes': 8 * 1024 * 1024}}
    attempted = set()
    terminal_transaction = None
    budget = next(count for selected, _, count in NODE_CASES.values() if selected == case)
    def persist():
        raw = json.dumps(receipt, ensure_ascii=False, indent=2).encode()
        assert len(raw) <= receipt['limits']['receipt_bytes']
        pending = output.with_suffix('.pending'); pending.write_bytes(raw); pending.replace(output)
        category['observation_sha256'] = hashlib.sha256(raw).hexdigest()
    class Gateway:
        def __getattr__(self, key): return getattr(runtime, key)
        def raw_gateway(self, argv):
            nonlocal terminal_transaction
            assert len(receipt['calls']) < receipt['limits']['calls']
            if terminal_transaction is not None:
                assert list(argv) == ['verify', terminal_transaction], 'No collector-added command may follow terminal CLI execution except its required Gateway verification'
            if argv[0] == 'execute':
                assert argv[1] not in attempted, 'Never retry a Console transaction'
                assert len(attempted) < budget, 'Console witness transaction budget exceeded'
                attempted.add(argv[1])
            call = {'argv': list(argv)}; receipt['calls'].append(call)
            try:
                code, payload = runtime.raw_gateway(argv)
                assert len(json.dumps(payload, ensure_ascii=False).encode()) <= receipt['limits']['reply_bytes']
                call.update(exit_code=code, payload=payload)
                if argv[0] == 'execute':
                    stored = TransactionStore(runtime.state_dir).load_preview(argv[1])
                    if stored.artifact['request']['arguments'].get('api', '').startswith('ak.wwise.cli.'):
                        terminal_transaction = argv[1]
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
    def complete(api, arguments):
        phase = {'api': api}; receipt['phases'].append(phase)
        draft = _start_business_draft(gateway, api)
        _update_business_draft(gateway, draft, 'draft-declare-cli-console-plan', arguments, live=True)
        def bind(preview):
            if not receipt.get('model_before'): return
            stored = TransactionStore(runtime.state_dir).load_preview(preview['transaction_id'])
            effect = stored.artifact['prepared_operation']['pre_state']['cli_project_effect']
            index = Path(receipt['model_before']['index_path'])
            proof = capture_file_proof(index, field='retained model index', io_root=index.parent, max_bytes=2 * 1024 * 1024)
            assert proof['sha256'] == receipt['model_before']['sha256']
            images = json.loads(index.read_bytes())
            files = {Path(relative).as_posix(): value for relative, value in effect['model_before']['files'].items()}
            assert images['complete'] and set(images['files']) == set(files)
            assert all(row['file_proof'] == files[path]['proof'] for path, row in images['files'].items())
            if receipt.get('mapping_before'):
                assert receipt['mapping_before']['file_proof'] == effect['mapping_before']['file_proof']
            receipt['preview_binding'] = {'transaction_id': preview['transaction_id'],
                'artifact_hash': stored.artifact_hash, 'matches_before_images': True}
        try:
            return _complete_business_draft(gateway, draft, phase_receipt=phase, inspect_preview=bind)
        finally:
            if phase.get('transaction_id'):
                category['transaction_ids'].append(phase['transaction_id'])
    try:
        if case == 'cli-create':
            project = runtime.sandbox.sandbox_root / 'Blank2024' / 'Blank2024.wproj'
            complete('ak.wwise.cli.createNewProject', ['--value', 'project_file', str(project),
                '--item', 'platforms', 'Windows', '--item', 'platforms', 'Mac'])
            observed = saved_project(project)
            assert observed['name'] == 'Blank2024' and observed['platforms'] == [['Windows', 'Windows'], ['Mac', 'Mac']]
            receipt['created_project'] = observed
            receipt['created_fixture'] = export_created_fixture(project, runtime.state_dir / 'console184-created-donor',
                runtime=runtime, transaction=category['transaction_ids'][0])
            category['created_fixture'] = receipt['created_fixture']
        elif case == 'create-close':
            project = runtime.sandbox.sandbox_root / 'ConsoleCreated' / 'ConsoleCreated.wproj'
            complete('ak.wwise.console.project.create', ['--value', 'project_file', str(project),
                '--mapping', 'platforms', 'Windows', 'Windows_Studio', '--mapping', 'platforms', 'Mac', 'Mac',
                '--item', 'languages', 'English(US)', '--item', 'languages', 'Japanese'])
            observed = saved_project(project)
            assert observed['name'] == 'ConsoleCreated'
            assert observed['platforms'] == [['Windows_Studio', 'Windows'], ['Mac', 'Mac']]
            assert [language for language in observed['languages'] if language != 'SFX'] == ['English(US)', 'Japanese']
            receipt['created_project'] = observed
            schema = gateway.gateway(['request-schema', 'ak.wwise.console.project.close'], live=False)
            assert schema['input_shape'] == 'zero'
            phase = {'api': 'ak.wwise.console.project.close'}; receipt['phases'].append(phase)
            preview = gateway.gateway(schema['continuation']['gateway_argv'], live=True)
            tx = preview['transaction_id']; phase.update(transaction_id=tx, preview=preview)
            category['transaction_ids'].append(tx)
            shown = gateway.gateway(['transaction-show', tx, '--summary-only'], live=False)
            gateway.gateway(['confirm', tx, '--confirmation-token', shown['confirmation']['token']], live=False)
            phase['execute'] = gateway.gateway(['execute', tx], live=True)
            phase['verify'] = gateway.gateway(['verify', tx], live=True)
            assert phase['verify']['verified'] is True
        elif case == 'add-copy':
            project = runtime.sandbox.sandbox_project
            saved = _save_sandbox_project(gateway)
            category['transaction_ids'].append(saved['preview']['transaction_id'])
            receipt['phases'].append({'api': 'ak.wwise.core.project.save', 'setup_only': True, **saved})
            receipt['model_before'] = retain_model(project, runtime.state_dir / 'console184-model-images', 'before')
            expected = platform_values(project, 'Windows')
            assert expected and not platform_values(project, 'ReviewCopy'), 'Copy fixture needs explicit source values and no unregistered target values'
            receipt['explicit_source_values'] = expected
            complete('ak.wwise.cli.addNewPlatform', ['--value', 'project_file', str(project),
                '--value', 'base_platform', 'Windows', '--value', 'platform_name', 'ReviewCopy',
                '--value', 'copy_settings_from_platform', 'Windows'])
            receipt['copied_values'] = platform_values(project, 'ReviewCopy')
            assert receipt['copied_values'] == expected
            receipt['model_after'] = retain_model(project, runtime.state_dir / 'console184-model-images', 'after')
        elif case == 'migrate':
            donor, binding = load_created_fixture(runtime.env['WAAPI_CONSOLE184_CREATED_MANIFEST'])
            project = runtime.sandbox.sandbox_project
            assert donor.resolve() != project.resolve(), 'Migration must use a fresh owned clone'
            assert saved_project(project)['wwise_version'].startswith('v2024.1.'), 'Do not pre-save the migration input with2025.1'
            for row in binding['files']:
                file = project.parent / row['path']
                proof = capture_file_proof(file, field='created project clone', io_root=project.parent, max_bytes=8 * 1024 * 1024)
                assert proof['size'] == row['size'] and proof['sha256'] == row['sha256']
            receipt['created_fixture_binding'] = binding
            receipt['project_before'] = saved_project(project)
            receipt['model_before'] = retain_model(project, runtime.state_dir / 'console184-model-images', 'before')
            complete('ak.wwise.cli.migrate', ['--value', 'project_file', str(project)])
            receipt['project_after'] = saved_project(project)
            assert receipt['project_after']['wwise_version'].startswith('v2025.1.')
            assert receipt['project_after']['id'] == receipt['project_before']['id']
            assert file_inventory(donor.parent) == binding['files'], 'Immutable created donor changed during migration'
            receipt['model_after'] = retain_model(project, runtime.state_dir / 'console184-model-images', 'after')
        else:
            project = runtime.sandbox.sandbox_project
            assert runtime.console_project_prelaunch is not None
            receipt['prelaunch'] = runtime.console_project_prelaunch
            saved = _save_sandbox_project(gateway)
            category['transaction_ids'].append(saved['preview']['transaction_id'])
            receipt['phases'].append({'api': 'ak.wwise.core.project.save', 'setup_only': True, **saved})
            before, descriptors, documents = media_model(project)
            mapping_file = project.with_suffix('.mediaid')
            if case == 'media-back':
                records = mapping_records(_read_xml_artifact(str(mapping_file), str(project.parent), require_wwise_document=False)[0])
                assert before == [] and compact_records(records) == receipt['prelaunch']['mapping_records']
                assert project_storage_mode(documents[project][0]) is True
            else:
                assert compact_records(before) == receipt['prelaunch']['mapping_records']
                assert project_storage_mode(documents[project][0]) is False
                raw, records, _ = retained_mapping()
                stale = ET.fromstring(raw)
                media = list(stale.iter('MediaID'))
                replacement = next(row.get('ID') for row in media if row.get('ID') != media[0].get('ID'))
                media[0].set('ID', replacement)
                ET.ElementTree(stale).write(mapping_file, encoding='utf-8', xml_declaration=True)
                receipt['stale_mapping_records'] = compact_records(mapping_records(stale))
                assert receipt['stale_mapping_records'] != compact_records(before)
            receipt['mapping_before'] = observe_console_file(mapping_file, io_root=project.parent)
            receipt['model_before'] = retain_model(project, runtime.state_dir / 'console184-model-images', 'before')
            api = 'ak.wwise.cli.moveMediaIdsToWorkUnits' if case == 'media-back' else 'ak.wwise.cli.updateMediaIdsInSingleFile'
            complete(api, ['--value', 'project_file', str(project)])
            after, after_descriptors, documents = media_model(project)
            assert compact_records(after) == compact_records(records)
            assert compact_records(descriptors) == compact_records(after_descriptors)
            assert project_storage_mode(documents[project][0]) is False
            if case == 'media-refresh':
                refreshed = mapping_records(_read_xml_artifact(str(mapping_file), str(project.parent), require_wwise_document=False)[0])
                assert compact_records(refreshed) == compact_records(before) == compact_records(after)
            receipt['media_records_after'] = compact_records(after)
            receipt['model_after'] = retain_model(project, runtime.state_dir / 'console184-model-images', 'after')
        receipt['complete'] = True; category['status'] = 'PASS'
    except Exception as exc:
        receipt['failure'] = {'type': type(exc).__name__, 'details': str(exc)[:16384]}
        raise
    finally:
        if case in {'media-back', 'media-refresh'}:
            mapping = runtime.sandbox.sandbox_project.with_suffix('.mediaid')
            if mapping.exists():
                try:
                    receipt['mapping_after'] = observe_console_file(mapping, io_root=mapping.parent)
                except Exception as capture:
                    receipt['mapping_after_capture_error'] = str(capture)[:2048]
                    if receipt['complete']:
                        receipt['complete'] = False; category['status'] = 'FAIL'
                        persist()
                        raise
            else:
                receipt['mapping_after'] = {'exists': False}
        if receipt.get('model_before') and not receipt.get('model_after'):
            try:
                receipt['model_after'] = retain_model(runtime.sandbox.sandbox_project,
                    runtime.state_dir / 'console184-model-images', 'after')
            except Exception as capture:
                receipt['after_capture_error'] = str(capture)[:2048]
                if receipt['complete']:
                    receipt['complete'] = False; category['status'] = 'FAIL'
                    persist()
                    raise
        receipt['transaction_count'] = len(list((runtime.state_dir / 'transactions').glob('*/preview.json')))
        if receipt['complete'] and not receipt['transaction_count'] == len(attempted) == budget:
            receipt['complete'] = False; category['status'] = 'FAIL'
            persist()
            raise AssertionError('Console witness transaction budget did not match its actual durable transactions')
        persist()
