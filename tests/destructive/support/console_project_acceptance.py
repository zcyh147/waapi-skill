"""Bounded Console project witnesses; native I/O stays in the existing lifecycle."""
from __future__ import annotations

import gzip
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

from wwise_waapi.console_media_ids import compact_records, mapping_records, work_unit_records, project_storage_mode, project_storage_observation
from wwise_waapi.console_project_operations import _read_xml_artifact, _project_model_paths
from wwise_waapi.operation_soundbank import capture_artifact_tree, capture_file_proof, prove_artifact_path
from wwise_waapi.transactions import TransactionStore
from tests.destructive.support.console_file_observation import observe_console_file, ConsoleModelImageIndex
from tests.semantic.support.codex_archive_paths import parse_archive_relative_path, archive_relative_from_absolute

FIXTURES = Path(__file__).resolve().parents[2] / 'fixtures/console-project-184'
COMMITTED_MIGRATION_PROJECT = Path(__file__).resolve().parents[2] / '_org/2024.1/SampleProject.wproj'
NODE_CASES = {
    'test_console_project_cli_create_acceptance': ('cli-create', '2024.1', 1),
    'test_console_project_create_close_acceptance': ('create-close', '2025.1', 2),
    'test_console_project_add_platform_copy_acceptance': ('add-copy', '2025.1', 2),
    'test_console_project_migrate_created_fixture_acceptance': ('migrate', '2025.1', 1),
    'test_console_project_migrate_committed_2024_fixture_acceptance': ('migrate-committed-2024', '2025.1', 1),
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


# Matching Project SoundBanks/External Sources tabs are excluded from Copy
# Settings by the pinned manual; same-named fields on other owners still copy.
PROJECT_COPY_TAB_FIELDS = frozenset({'SoundBankPaths', 'SoundBankPreGenerateCustomCmdDescription',
    'SoundBankPreGenerateCustomCmdLines', 'SoundBankPostGenerateCustomCmdDescription',
    'SoundBankPostGenerateCustomCmdLines', 'ExternalSourcesInputPath', 'ExternalSourcesOutputPath'})


def project_copy_tab_values(project, platform):
    document, _ = _read_xml_artifact(str(project), str(project.parent))
    return sorted([{'property': field.get('Name'), 'type': field.get('Type'), 'value': value.text or ''}
        for field in document.findall('./ProjectInfo/Project/PropertyList/Property')
        if field.get('Name') in PROJECT_COPY_TAB_FIELDS
        for value in field.findall('./ValueList/Value') if value.get('Platform') == platform],
        key=lambda row: (row['property'], row['type'] or '', row['value']))


def platform_values(project, platform):
    rows = []
    for path in _project_model_paths(str(project), str(project.parent)):
        document, _ = _read_xml_artifact(path, str(project.parent))
        excluded = {id(field) for field in document.findall('./ProjectInfo/Project/PropertyList/Property')
            if Path(path) == project and field.get('Name') in PROJECT_COPY_TAB_FIELDS}
        def visit(node, owners):
            if node.tag == 'Property' and id(node) not in excluded:
                for value in node.findall('./ValueList/Value'):
                    if value.get('Platform') == platform:
                        rows.append([Path(path).relative_to(project.parent).as_posix(), owners,
                            node.get('Name'), node.get('Type'), value.text,
                            sorted((key, item) for key, item in value.attrib.items() if key != 'Platform')])
            owner = [node.tag, node.get('ID', ''), node.get('Name', '')]
            for child in node:
                visit(child, [*owners, owner])
        visit(document, [])
    return sorted(rows, key=repr)


def retain_model(project, root, phase):
    root.mkdir(parents=True, exist_ok=True)
    link = {}; image = ConsoleModelImageIndex(root=root, project=project, phase=phase, link=link)
    for path in _project_model_paths(str(project), str(project.parent)):
        image.save(Path(path), observe_console_file(Path(path), io_root=project.parent))
    image.finish()
    return link


def retain_created_target_tree(project, root, owned_root, link):
    """Retain only the requested creation subtree, including non-project files."""
    from wwise_waapi.filesystem_security import metadata_is_link_or_reparse
    limits = dict(max_files=512, max_entries=16384, max_total_bytes=32 * 1024 * 1024,
        max_file_bytes=8 * 1024 * 1024, max_depth=64)
    body = {'contract': 'waapi-skill.created-target-tree/v1', 'target': str(project.parent),
        'requested_project': str(project), 'complete': False, 'files': [], 'directories': [],
        'errors': [], 'limits': {**limits, 'manifest_bytes': 2 * 1024 * 1024}}
    manifest = root / 'target-tree.json'
    destination = root / 'target'
    def snapshot():
        observed = capture_artifact_tree(project.parent, io_root=owned_root, **limits)
        for row in observed['files']:
            if parse_archive_relative_path(row['path']).canonical != row['path']:
                raise ValueError('Created file inventory must use canonical archive identities')
        return observed
    def error(exc):
        body['errors'].append({'code': getattr(exc, 'error_code', type(exc).__name__), 'message': str(exc)[:2048]})
    try:
        project.parent.relative_to(owned_root)
        before = snapshot()
        body['source_before'] = before
        if not before['exists']:
            raise ValueError('Requested creation target directory is absent')
        destination.mkdir(exist_ok=False)
        # Snapshot helper owns file/link/byte limits. Preserve empty directories
        # too, with a separately bounded no-follow walk before copying files.
        pending, entries = [(project.parent, 0)], 0
        while pending:
            directory, depth = pending.pop()
            if depth > limits['max_depth']:
                raise ValueError('Creation target changed beyond its directory depth bound')
            prove_artifact_path(directory, io_root=owned_root, field='created directory', must_exist=True, expect_directory=True)
            with os.scandir(directory) as scan:
                for entry in scan:
                    entries += 1
                    if entries > limits['max_entries']:
                        raise ValueError('Creation target changed beyond its entry bound')
                    if metadata_is_link_or_reparse(entry.stat(follow_symlinks=False)):
                        raise ValueError('Creation target gained a linked or reparse entry')
                    if entry.is_dir(follow_symlinks=False):
                        child = parse_archive_relative_path(archive_relative_from_absolute(entry.path, project.parent).canonical)
                        pending.append((Path(entry.path), depth + 1))
                        target = destination.joinpath(*child.parts)
                        prove_artifact_path(target, io_root=root, field='created directory image', must_exist=False, expect_directory=True)
                        target.mkdir(exist_ok=False)
                        body['directories'].append(child.canonical)
        for row in before['files']:
            relative = parse_archive_relative_path(row['path'])
            path = project.parent.joinpath(*relative.parts)
            observation = observe_console_file(path, io_root=project.parent)
            raw = base64.b64decode(observation['content_base64'], validate=True)
            proof = observation['file_proof']
            if (proof['size'], proof['sha256']) != (row['size'], row['sha256']):
                raise ValueError('Created file changed after its inventory')
            target = destination.joinpath(*relative.parts)
            prove_artifact_path(target, io_root=root, field='created file image', must_exist=False, expect_directory=False)
            with target.open('xb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            copied = capture_file_proof(target, field='created file image', io_root=root, max_bytes=limits['max_file_bytes'])
            if (copied['size'], copied['sha256']) != (row['size'], row['sha256']):
                raise ValueError('Created file image differs from its observed bytes')
            body['files'].append({**row, 'path': relative.canonical,
                'artifact_path': archive_relative_from_absolute(target, root).canonical,
                'file_proof': proof, 'artifact_proof': copied})
        after = snapshot()
        body['source_after'] = after
        if before != after:
            raise ValueError('Created target changed during bounded capture')
        body['directories'].sort()
        body['complete'] = True
    except Exception as exc:
        error(exc)
    finally:
        raw = json.dumps(body, ensure_ascii=False, sort_keys=True, indent=2).encode()
        if len(raw) > body['limits']['manifest_bytes']:
            body.update(complete=False, files=[], directories=[], inventory_omitted='manifest byte bound')
            body.pop('source_before', None); body.pop('source_after', None)
            error(ValueError('Creation target inventory exceeds manifest byte bound'))
            raw = json.dumps(body, ensure_ascii=False, sort_keys=True, indent=2).encode()
        assert len(raw) <= body['limits']['manifest_bytes']
        with manifest.open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        proof = capture_file_proof(manifest, field='created target manifest', io_root=root,
            max_bytes=body['limits']['manifest_bytes'])
        link.update(manifest_path=str(manifest), manifest_sha256=proof['sha256'], complete=body['complete'],
            file_count=len(body['files']), total_bytes=sum(row['size'] for row in body['files']))


def collect_console_project_acceptance(runtime, case):
    """One selected witness, captured through the existing public Gateway path."""
    from tests.destructive.test_gateway_workflow_transaction_matrix import (
        _start_business_draft, _update_business_draft, _complete_business_draft, _save_sandbox_project,
        _hash_mutation_bearing_project_files, _source_tree_inventory,
    )
    assert case in {'cli-create', 'create-close', 'add-copy', 'migrate', 'migrate-committed-2024', 'media-back', 'media-refresh'}
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
    observed_model_project = runtime.sandbox.sandbox_project
    migration_sources = None
    migration_project = None
    budget = next(count for selected, _, count in NODE_CASES.values() if selected == case)
    def persist():
        raw = json.dumps(receipt, ensure_ascii=False, indent=2).encode()
        assert len(raw) <= receipt['limits']['receipt_bytes']
        pending = output.with_suffix('.pending'); pending.write_bytes(raw); pending.replace(output)
        category['observation_sha256'] = hashlib.sha256(raw).hexdigest()
    def retain_created_output(transaction):
        stored = TransactionStore(runtime.state_dir).load_preview(transaction)
        request = stored.artifact['request']['arguments']
        api = request.get('api')
        if api not in {'ak.wwise.cli.createNewProject', 'ak.wwise.console.project.create'}:
            return
        project = Path(request['args']['project' if api.startswith('ak.wwise.cli.') else 'path'])
        project.relative_to(runtime.sandbox.sandbox_root)
        root = runtime.state_dir / 'console184-created-output'
        root.mkdir(exist_ok=False)
        link = {'requested_project': str(project), 'api': api, 'transaction_id': transaction,
            'captured_before_verification': True}
        receipt['created_output'] = link
        link['target_tree'] = {}
        retain_created_target_tree(project, root, runtime.sandbox.sandbox_root, link['target_tree'])
        image = ConsoleModelImageIndex(root=root, project=project, phase='after', link=link)
        try:
            image.save(project, observe_console_file(project, io_root=project.parent))
        except Exception as exc:
            image.error(project, exc)
        finally:
            image.finish()
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
                if argv[0] == 'execute':
                    try:
                        retain_created_output(argv[1])
                    except Exception as capture:
                        receipt['created_output_capture_error'] = str(capture)[:2048]
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
    def retain_migration_target(phase):
        root = runtime.state_dir / 'console184-migration-target' / phase
        root.mkdir(parents=True, exist_ok=False)
        link = {'requested_project_exists': migration_project.is_file()}
        receipt['target_tree_' + phase] = link
        retain_created_target_tree(migration_project, root, runtime.sandbox.sandbox_root, link)
        assert link['complete'], 'Migration target tree was not completely retained'
    def immutable_source_observations():
        return {name: {'project': str(project),
            'full_tree_hash': list(_hash_mutation_bearing_project_files(project.parent)),
            'tree_metadata': list(_source_tree_inventory(project.parent)), 'project_mtime_ns': project.stat().st_mtime_ns}
            for name, project in migration_sources.items()}

    try:
        if case == 'cli-create':
            project = runtime.sandbox.sandbox_root / 'Blank2024' / 'Blank2024.wproj'
            complete('ak.wwise.cli.createNewProject', ['--value', 'project_file', str(project),
                '--item', 'platforms', 'Windows', '--item', 'platforms', 'Mac'])
            observed = saved_project(project)
            assert observed['name'] == 'Blank2024'
            assert len(observed['platforms']) == 2 and {tuple(row) for row in observed['platforms']} == {('Windows', 'Windows'), ('Mac', 'Mac')}
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
            assert len(observed['platforms']) == 2 and {tuple(row) for row in observed['platforms']} == {('Windows_Studio', 'Windows'), ('Mac', 'Mac')}
            requested_languages = {'English(US)', 'Japanese'}
            # Native empty creation includes these implicit names in the exact
            # retained2025 project; order of saved rows is not a requested effect.
            assert len(observed['languages']) == len(set(observed['languages']))
            assert requested_languages <= set(observed['languages']) <= requested_languages | {'External', 'Mixed', 'SFX'}
            document, _ = _read_xml_artifact(str(project), str(project.parent))
            fields = document.findall('./ProjectInfo/Project/PropertyList/Property[@Name="DefaultLanguage"]')
            default = {'value': fields[0].get('Value'), 'representation': 'explicit'} if fields else None
            if default is None:
                source = Path(__file__).resolve().parents[3] / 'skills/waapi-skill/resources/semantic/2025.1/project_default_language.json'
                proof = capture_file_proof(source, field='Project default language source', io_root=source.parent, max_bytes=16384)
                definition = json.loads(source.read_bytes())
                assert definition['version'] == runtime.version and definition['property'] == 'DefaultLanguage'
                assert definition['class'] == {'Name': 'Project', 'CompanyID': '1', 'PluginID': '3'}
                default = {'value': definition['default'], 'representation': 'default_elided', 'source_proof': proof}
            assert default['value'] == 'English(US)'
            receipt['created_default_language'] = default
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
            receipt['excluded_project_settings'] = {'source': project_copy_tab_values(project, 'Windows')}
            complete('ak.wwise.cli.addNewPlatform', ['--value', 'project_file', str(project),
                '--value', 'base_platform', 'Windows', '--value', 'platform_name', 'ReviewCopy',
                '--value', 'copy_settings_from_platform', 'Windows'])
            receipt['copied_values'] = platform_values(project, 'ReviewCopy')
            receipt['excluded_project_settings']['target'] = project_copy_tab_values(project, 'ReviewCopy')
            assert receipt['copied_values'] == expected
            receipt['model_after'] = retain_model(project, runtime.state_dir / 'console184-model-images', 'after')
        elif case == 'migrate-committed-2024':
            from tests.destructive.support.sandbox_fixture import prepare_sample_project_sandbox
            metadata = runtime.sandbox.metadata
            assert metadata.launch_project_path == str(runtime.sandbox.sandbox_project)
            assert metadata.ready_duration_seconds is not None and metadata.get_info_version['year'] == 2025
            host = saved_project(runtime.sandbox.sandbox_project)
            assert host['wwise_version'].startswith('v2025.1.')
            copy_root = runtime.sandbox.sandbox_root / 'migration-committed-2024'
            assert not copy_root.exists() and not copy_root.is_relative_to(runtime.sandbox.sandbox_path)
            migration_sources = {'host': runtime.sandbox.source_project, 'migration': COMMITTED_MIGRATION_PROJECT}
            receipt['immutable_sources_before'] = immutable_source_observations()
            copy_environment = {**runtime.env, 'WWISE_SAMPLE_PROJECT_PATH': str(COMMITTED_MIGRATION_PROJECT)}
            secondary = prepare_sample_project_sandbox(copy_environment, sandbox_root=copy_root, hash_strategy='full')
            assert secondary.metadata.source_hash.digest == secondary.metadata.sandbox_hash.digest
            migration_project = observed_model_project = project = secondary.sandbox_project
            assert project != runtime.sandbox.sandbox_project
            receipt['migration_fixture'] = {'authority': 'committed-tests-org-2024.1',
                'source_project': str(COMMITTED_MIGRATION_PROJECT), 'target_project': str(project),
                'host_launch_project': metadata.launch_project_path, 'host_project': host,
                'host_ready_duration_seconds': metadata.ready_duration_seconds,
                'created_after_host_readiness': True, 'source_copy_sha256': secondary.metadata.source_hash.digest,
                'copied_payload_matches_source': True}
            retain_migration_target('before')
            receipt['project_before'] = saved_project(project)
            assert receipt['project_before']['wwise_version'].startswith('v2024.1.')
            receipt['model_before'] = retain_model(project, runtime.state_dir / 'console184-model-images', 'before')
            assert immutable_source_observations() == receipt['immutable_sources_before'], 'Immutable migration sources changed before Preview'
            complete('ak.wwise.cli.migrate', ['--value', 'project_file', str(project)])
            receipt['project_after'] = saved_project(project)
            assert receipt['project_after']['wwise_version'].startswith('v2025.1.')
            assert receipt['project_after']['id'] == receipt['project_before']['id']
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
            records = mapping_records(_read_xml_artifact(str(mapping_file), str(project.parent), require_wwise_document=False)[0])
            assert before == [] and compact_records(records) == receipt['prelaunch']['mapping_records']
            assert project_storage_mode(documents[project][0]) is True
            if case == 'media-refresh':
                # Native refresh owns an existing active central map. Preserve
                # its valid Preview records; no stale-ID repair is promised.
                receipt['refresh_scope'] = 'existing_valid_central_mapping_preservation'
            receipt['mapping_before'] = observe_console_file(mapping_file, io_root=project.parent)
            receipt['model_before'] = retain_model(project, runtime.state_dir / 'console184-model-images', 'before')
            api = 'ak.wwise.cli.moveMediaIdsToWorkUnits' if case == 'media-back' else 'ak.wwise.cli.updateMediaIdsInSingleFile'
            complete(api, ['--value', 'project_file', str(project)])
            after, after_descriptors, documents = media_model(project)
            assert compact_records(after) == compact_records(records if case == 'media-back' else before)
            assert compact_records(descriptors) == compact_records(after_descriptors)
            receipt['storage_after'] = project_storage_observation(documents[project][0])
            assert receipt['storage_after']['value'] is (case == 'media-refresh')
            if case == 'media-refresh':
                refreshed = mapping_records(_read_xml_artifact(str(mapping_file), str(project.parent), require_wwise_document=False)[0])
                assert compact_records(refreshed) == compact_records(records)
            receipt['media_records_after'] = compact_records(after)
            receipt['model_after'] = retain_model(project, runtime.state_dir / 'console184-model-images', 'after')
        if case in {'cli-create', 'create-close'}:
            assert (receipt['created_output']['complete'] and receipt['created_output']['target_tree']['complete']
                and not receipt.get('created_output_capture_error')), \
                'Created project output was not completely retained before verification'
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
                receipt['model_after'] = retain_model(observed_model_project,
                    runtime.state_dir / 'console184-model-images', 'after')
            except Exception as capture:
                receipt['after_capture_error'] = str(capture)[:2048]
                if receipt['complete']:
                    receipt['complete'] = False; category['status'] = 'FAIL'
                    persist()
                    raise
        if migration_sources is not None:
            try:
                try:
                    if migration_project is not None:
                        retain_migration_target('after')
                finally:
                    receipt['immutable_sources_after'] = immutable_source_observations()
                    receipt['immutable_sources_verified'] = receipt['immutable_sources_before'] == receipt['immutable_sources_after']
                    category['immutable_sources_verified'] = receipt['immutable_sources_verified']
                    assert receipt['immutable_sources_verified'], 'Immutable migration source changed'
            except Exception as capture:
                category['immutable_sources_verified'] = receipt.get('immutable_sources_verified', False)
                receipt['migration_preservation_error'] = str(capture)[:2048]
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
