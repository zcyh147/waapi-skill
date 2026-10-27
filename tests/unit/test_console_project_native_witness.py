"""Console project witnesses through the public Gateway and persisted writer."""
from pathlib import Path
from copy import deepcopy
import importlib
import json
import os
import shutil
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from tests.semantic.support.codex_project_prelaunch_v3 import (
    normalize_project_copy, ProjectPrelaunchRequest, WWISE_2025_SOUNDBANK_AURO_PROFILE,
)
from tests.destructive.support import sandbox_fixture, exact_real_evidence
from tests.semantic.support.codex_archive_paths import parse_archive_relative_path, archive_relative_from_absolute
from tests.unit.test_console_project_alternatives_gateway import CliProjectTask, ConsoleProjectTask, saved_fixture_project, WaapiRequestFailed
from tests.unit.test_object_graph_business_gateway import gateway as public_gateway


def _collector_runtime(tmp_path, monkeypatch, case, *, fault=False, donor=None):
    tmp_path.mkdir(exist_ok=True)
    monkeypatch.setenv('WWISE_LIVE', '1'); monkeypatch.setenv('WWISE_DESTRUCTIVE', '1')
    workflow = importlib.import_module('tests.destructive.test_gateway_workflow_transaction_matrix')
    version = '2024.1' if case == 'cli-create' else '2025.1'
    class Client(CliProjectTask):
        def disconnect(self): pass
        def call(self, uri, args=None, options=None):
            if getattr(self, 'terminal', False):
                assert uri == 'ak.wwise.core.getInfo', 'Only existing Gateway runtime attestation may follow a terminal CLI dispatch'
            if uri == 'ak.wwise.core.getProjectInfo' or (uri.endswith('object.get') and 'Project' in json.dumps(args)):
                self.calls.append((uri, deepcopy(args), deepcopy(options)))
                if getattr(self, 'closed', False):
                    if uri.endswith('object.get'): return {'return': []}
                    raise WaapiRequestFailed(uri)
                file = getattr(self, 'active_file', self.project_file)
                node = ET.parse(file).find('./ProjectInfo/Project')
                row = {'id': node.get('ID'), 'name': node.get('Name'), 'path': str(file)}
                if uri.endswith('getProjectInfo'): return row
                return {'return': [{'id': row['id'], 'name': row['name'], 'type': 'Project', 'path': '\\', 'filePath': str(file)}]}
            if uri in ('ak.wwise.cli.createNewProject', 'ak.wwise.console.project.create'):
                self.created_file = Path(args.get('project', args.get('path')))
                self.created_file.parent.mkdir(parents=True)
                create_args = ({'platforms': [{'basePlatform': value, 'name': value} for value in args['platform']]}
                    if uri.startswith('ak.wwise.cli.') else args)
                ConsoleProjectTask.write_created_project(self, create_args)
                tree = ET.parse(self.created_file)
                tree.find('./ProjectInfo/Project').set('Name', self.created_file.stem)
                if case == 'cli-create' and fault is True:
                    tree.find('./ProjectInfo/Project/Platforms/Platform').set('ReferencePlatform', 'Mac')
                platforms = tree.find('./ProjectInfo/Project/Platforms')
                platforms[:] = sorted(platforms, key=lambda row: row.get('Name'))
                if fault == 'missing-default':
                    tree.find('./ProjectInfo/Project/PropertyList/Property[@Name="DefaultLanguage"]').attrib.pop('Value')
                elif case == 'create-close':
                    project = tree.find('./ProjectInfo/Project'); properties = project.find('PropertyList')
                    properties.remove(properties.find('./Property[@Name="DefaultLanguage"]'))
                    backing = ET.SubElement(ET.SubElement(ET.SubElement(project, 'SharedValues'), 'SharedPropertyList'), 'PropertyList')
                    field = ET.SubElement(backing, 'Property', Name='DefaultLanguage', Type='string')
                    ET.SubElement(ET.SubElement(field, 'ValueList'), 'Value').text = 'English(US)'
                    languages = project.find('LanguageList')
                    ET.SubElement(languages, 'Language', Name='External', ID='{C5B109DA-F3FD-485F-833F-8FB61F6FF042}')
                    ET.SubElement(languages, 'Language', Name='Mixed', ID='{2B5DFEAD-36EC-4AE6-900D-8DD49E09E25A}')
                    languages[:] = sorted(languages, key=lambda row: row.get('Name'))
                tree.write(self.created_file)
                if uri == 'ak.wwise.console.project.create': self.active_file = self.created_file
                self.calls.append((uri, deepcopy(args), deepcopy(options)))
                if uri.startswith('ak.wwise.cli.'): self.terminal = True
                if isinstance(fault, str) and fault.startswith('partial-'):
                    self.created_file.unlink()
                    events = self.created_file.parent / 'Events'; events.mkdir()
                    (events / 'partial.wwu').write_bytes(b'partial native Work Unit bytes')
                    (self.created_file.parent / 'Unfinished' / 'Empty').mkdir(parents=True)
                    (self.created_file.parent / 'creation.log').write_bytes(b'partial creation log')
                    if fault == 'partial-link':
                        outside = tmp_path / 'outside-target.bin'; outside.write_bytes(b'outside target bytes')
                        (events / 'unsafe.wwu').symlink_to(outside)
                    if fault == 'partial-archive-file':
                        (events / 'nonportable:entry.wwu').write_bytes(b'nonportable file bytes')
                    if fault == 'partial-archive-directory':
                        (self.created_file.parent / 'nonportable:directory').mkdir()
                    if fault == 'partial-oversize':
                        with (events / 'oversized.bin').open('wb') as stream: stream.truncate(8 * 1024 * 1024 + 1)
                    raise TimeoutError('Native outcome unknown with partial target subtree')
                if fault == 'indeterminate-created': raise TimeoutError('Native outcome unknown after creating owned output')
                return {'result': 0} if uri.startswith('ak.wwise.cli.') else {}
            if uri == 'ak.wwise.console.project.close':
                self.calls.append((uri, deepcopy(args), deepcopy(options)))
                self.closed = not fault
                return {'hadProjectOpen': True}
            if uri == 'ak.wwise.core.project.save':
                self.calls.append((uri, deepcopy(args), deepcopy(options)))
                return {}
            if uri == 'ak.wwise.cli.migrate':
                self.calls.append((uri, deepcopy(args), deepcopy(options)))
                target = Path(args['project'])
                if case == 'migrate-committed-2024':
                    assert target != self.project_file
                    assert ET.parse(target).getroot().get('WwiseVersion') == 'v2024.1.0'
                    assert ET.parse(self.project_file).getroot().get('WwiseVersion') == 'v2025.1.7'
                if fault != 'wrong-version' and (not fault or case == 'migrate-committed-2024'):
                    tree = ET.parse(target); tree.getroot().set('WwiseVersion', 'v2025.1.7')
                    if case == 'migrate-committed-2024':
                        tree.getroot().set('WwiseBuild', '9143'); tree.getroot().set('SchemaVersion', '133')
                    tree.write(target)
                    if case == 'migrate-committed-2024' and fault == 'preservation':
                        for unit in sorted((target.parent / 'Actor-Mixer Hierarchy').glob('*.wwu')):
                            tree = ET.parse(unit); sound = tree.find('.//Sound')
                            if sound is not None:
                                sound.set('Name', 'Unexpected migration rename'); tree.write(unit); break
                        else:
                            raise AssertionError('The authentic old fixture must contain a Sound for the preservation fault')
                self.terminal = True
                if case == 'migrate-committed-2024' and fault in {'archive-file', 'archive-directory'}:
                    bad = target.parent / 'nonportable:entry'
                    if fault == 'archive-file': bad.write_bytes(b'nonportable filename')
                    else: bad.mkdir()
                if case == 'migrate-committed-2024' and fault == 'missing-project':
                    self.remaining_unit = sorted(target.parent.rglob('*.wwu'))[-1]
                    self.remaining_bytes = self.remaining_unit.read_bytes()
                    target.unlink()
                    raise TimeoutError('Migration outcome unknown; target project is absent')
                return {'result': 0}
            if uri == 'ak.wwise.cli.addNewPlatform':
                self.calls.append((uri, deepcopy(args), deepcopy(options)))
                tree = ET.parse(self.project_file)
                ET.SubElement(tree.find('./ProjectInfo/Project/Platforms'), 'Platform',
                    Name='ReviewCopy', ReferencePlatform='Windows', ID='{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}')
                for name in ('SoundBankPaths', 'ExternalSourcesOutputPath'):
                    values = tree.find('./ProjectInfo/Project/PropertyList/Property[@Name="' + name + '"]/ValueList')
                    ET.SubElement(values, 'Value', Platform='ReviewCopy').text = 'native-ReviewCopy-' + name
                tree.write(self.project_file)
                tree = ET.parse(self.unit)
                for parent in tree.iter():
                    for child in list(parent):
                        if child.get('Platform') == 'Windows':
                            copied = deepcopy(child); copied.set('Platform', 'ReviewCopy')
                            if fault is True: copied.text = '-12'
                            parent.append(copied)
                if fault == 'preservation':
                    tree.find('.//Sound').set('Name', 'Unexpected rename')
                tree.write(self.unit)
                self.terminal = True
                return {'result': 0}
            if uri == 'ak.wwise.cli.moveMediaIdsToWorkUnits':
                from tests.destructive.support.console_project_acceptance import media_model
                from wwise_waapi.console_media_ids import mapping_records
                records = mapping_records(ET.parse(self.project_file.with_suffix('.mediaid')).getroot())
                by_owner = {}
                for row in records: by_owner.setdefault(row[0], []).append(row[-1])
                for path, (document, _) in media_model(self.project_file)[2].items():
                    for source in document.iter():
                        if source.tag in {'AudioFileSource', 'MidiFileSource', 'PluginMediaSource'} and source.get('ID', '').upper() in by_owner:
                            ids = ET.SubElement(source, 'MediaIDList')
                            for attributes in by_owner[source.get('ID').upper()]:
                                ET.SubElement(ids, 'MediaID', dict(attributes))
                    if path == self.project_file:
                        properties = document.find('./ProjectInfo/Project/PropertyList')
                        properties.remove(properties.find('./Property[@Name="MediaIDsInSingleFile"]'))
                    if fault and not fault_applied[0] and document.find('.//MediaID') is not None:
                        media = document.find('.//MediaID'); media.set('ID', str(int(media.get('ID')) + 1))
                        fault_applied[0] = True
                    ET.ElementTree(document).write(path, encoding='utf-8')
                self.project_file.with_suffix('.mediaid').unlink()
                self.calls.append((uri, deepcopy(args), deepcopy(options))); self.terminal = True
                return {'result': 0}
            if uri == 'ak.wwise.cli.updateMediaIdsInSingleFile':
                from tests.destructive.support.console_project_acceptance import retained_mapping
                from wwise_waapi.console_media_ids import project_storage_mode
                if project_storage_mode(ET.parse(self.project_file).getroot()) is not True:
                    raise WaapiRequestFailed(uri, 'ak.wwise.MediaIdUpdateError')
                raw = retained_mapping()[0]
                if fault:
                    tree = ET.fromstring(raw)
                    media = next(tree.iter('MediaID')); media.set('ID', str(int(media.get('ID')) + 1))
                    raw = ET.tostring(tree, encoding='utf-8')
                self.project_file.with_suffix('.mediaid').write_bytes(raw)
                self.calls.append((uri, deepcopy(args), deepcopy(options))); self.terminal = True
                return {'result': 0}
            return super().call(uri, args, options)
    fault_applied = [False]
    client = Client(tmp_path, version, 'ak.wwise.cli.createNewProject')
    client.unit = saved_fixture_project(client)
    if case == 'add-copy':
        tree = ET.parse(client.project_file)
        for name in ('SoundBankPaths', 'ExternalSourcesOutputPath'):
            field = ET.SubElement(tree.find('./ProjectInfo/Project/PropertyList'), 'Property', Name=name, Type='string')
            ET.SubElement(ET.SubElement(field, 'ValueList'), 'Value', Platform='Windows').text = 'original-Windows-' + name
        tree.write(client.project_file)
        tree = ET.parse(client.unit)
        field = ET.SubElement(tree.find('.//Sound/PropertyList'), 'Property', Name='SoundBankPaths', Type='string')
        ET.SubElement(ET.SubElement(field, 'ValueList'), 'Value', Platform='Windows').text = 'keep-sound-scope'
        tree.write(client.unit)
    prelaunch = None
    if case in {'media-back', 'media-refresh', 'migrate-committed-2024'}:
        from tests.destructive.support.console_project_acceptance import stage_media_storage_fixture
        owned = client.project_file.parent
        shutil.rmtree(owned)
        if case == 'migrate-committed-2024':
            owned = tmp_path / 'case-owned' / 'host-2025'
        shutil.copytree(Path(__file__).resolve().parents[1] / '_org/2025.1', owned)
        client.project_file = owned / 'SampleProject.wproj'
        owner = owned.parent if case == 'migrate-committed-2024' else tmp_path
        io = owner / 'normalization'; io.mkdir()
        normalize_project_copy(client.project_file, io_root=io, owned_root=owner,
            request=ProjectPrelaunchRequest(scenario_id='gateway-workflow-transaction-matrix',
                auro_isolation_profile=WWISE_2025_SOUNDBANK_AURO_PROFILE))
        if case != 'migrate-committed-2024':
            prelaunch = stage_media_storage_fixture(client.project_file, central=True)
    if donor is not None:
        owned = client.project_file.parent
        shutil.rmtree(owned); shutil.copytree(donor.parent, owned)
        client.project_file = owned / donor.name
        source, source_project = donor.parent, donor
    else:
        source = tmp_path / 'immutable-source'
        shutil.copytree(client.project_file.parent, source)
        source_project = source / client.project_file.name
    proof = sandbox_fixture.hash_project(source)
    owned = client.project_file.parent
    metadata = sandbox_fixture.SandboxMetadata(str(source_project), str(source), str(owned), str(client.project_file),
        version, 0, proof, sandbox_fixture.hash_project(owned), source_project.stat().st_mtime,
        process_cleanup_result='cleaned', process_cleanup_details={'residual_processes': []})
    sandbox = sandbox_fixture.SandboxProject(source_project, source, owned.parent if case == 'migrate-committed-2024' else owned, owned, client.project_file, metadata)
    execute = public_gateway.execute_gateway
    monkeypatch.setattr(workflow.waapi_gateway, 'execute_gateway',
        lambda argv, **kwargs: execute(argv, **kwargs, client_factory=lambda _: client))
    runtime = workflow._WorkflowSandboxRuntime(version, sandbox,
        SimpleNamespace(host='127.0.0.1', port=31337, waapi_url='ws://127.0.0.1:31337/waapi'),
        tmp_path / 'collector-state', client.env, workflow.exact_git_candidate(workflow.REPO_ROOT), [])
    runtime.console_project_prelaunch = prelaunch
    if case == 'migrate-committed-2024':
        metadata.launch_project_path = str(client.project_file)
        metadata.ready_duration_seconds = 0.01
        metadata.get_info_version = {'year': 2025, 'major': 1, 'minor': 7, 'build': 9143}
        console = tmp_path / 'not-launched-console'; console.write_bytes(b'never executed')
        config = tmp_path / 'copy-environment.json'
        config.write_text(json.dumps({'versions': {'2025.1': {'wwise_console': str(console), 'sample_project': str(source_project)}}}))
        runtime.env.update(WWISE_LIVE='1', WWISE_DESTRUCTIVE='1', WWISE_VERSION='2025.1', WWISE_TEST_CONFIG=str(config), WWISE_CONSOLE=str(console))
        runtime.env['WAAPI_CONSOLE184_CREATED_MANIFEST'] = str(tmp_path / 'must-not-read-failed-A.json')
    return workflow, runtime, client, proof


def _finalize(tmp_path, monkeypatch, workflow, runtime, proof, *, failure=None, node):
    category_path = tmp_path / 'category.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(category_path))
    monkeypatch.setattr(sandbox_fixture, 'KEEP_ON_FAILURE_ROOT', tmp_path / 'retained')
    lock = sandbox_fixture.LiveSandboxLock(tmp_path / 'locks'); lock.__enter__()
    item = SimpleNamespace(path=workflow.__file__, nodeid='tests/destructive/test_gateway_workflow_transaction_matrix.py::' + node,
        _waapi_phase_reports={'setup': 'passed', 'call': 'failed' if failure else 'passed'})
    assert sandbox_fixture.hash_project(runtime.sandbox.source_root) == proof
    error = exact_real_evidence.finalize_exact_real_evidence(
        repo_root=workflow.REPO_ROOT, candidate=runtime.candidate, version=runtime.version,
        request=SimpleNamespace(session=SimpleNamespace(items=[item])), module_file=Path(workflow.__file__),
        started_at_unix_ns=1, active_error=failure, deferred_error=None, sandbox=runtime.sandbox, lock=lock,
        state_dir=runtime.state_dir, host={'is_command_line': True, 'version': runtime.version + '.test'},
        categories=runtime.category_results, source={'hash_before': proof.digest, 'hash_after': proof.digest},
        case_cleanup_root=runtime.sandbox.sandbox_root)
    assert error is None
    final = json.loads(category_path.read_text().splitlines()[-1])
    assert final['invocation']['phase'] == 'final'
    assert final['invocation']['outcome'] == ('FAIL' if failure else 'PASS')
    return final


@pytest.mark.parametrize('fault', [False, True])
def test_cli_create_collector_reaches_existing_final_writer_and_retains_created_fixture(tmp_path, monkeypatch, fault):
    workflow, runtime, client, proof = _collector_runtime(tmp_path, monkeypatch, 'cli-create', fault=fault)
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(tmp_path / 'category.jsonl'))
    failure = None
    try:
        workflow.test_console_project_cli_create_acceptance(runtime)
    except Exception as exc:
        failure = exc
    assert (failure is not None) is fault, failure
    final = _finalize(tmp_path, monkeypatch, workflow, runtime, proof, failure=failure,
        node='test_console_project_cli_create_acceptance')
    assert final['categories'][0]['status'] == ('FAIL' if fault else 'PASS')
    assert len(final['transactions']) == 1
    receipt = json.loads(Path(final['categories'][0]['observation_path']).read_text())
    assert receipt['complete'] is (not fault)
    if not fault:
        assert receipt['created_fixture']['manifest_sha256']
        assert Path(receipt['created_fixture']['manifest']).is_file()
        assert receipt['created_project']['platforms'] == [['Mac', 'Mac'], ['Windows', 'Windows']]
    assert len([uri for uri, _, _ in client.calls if uri.startswith('ak.wwise.cli.')]) == 1


@pytest.mark.parametrize('fault', [False, True])
def test_console_create_close_collector_uses_two_authorized_transitions_and_final_writer(tmp_path, monkeypatch, fault):
    workflow, runtime, client, proof = _collector_runtime(tmp_path, monkeypatch, 'create-close', fault=fault)
    failure = None
    try:
        workflow.test_console_project_create_close_acceptance(runtime)
    except Exception as exc:
        failure = exc
    assert (failure is not None) is fault, failure
    final = _finalize(tmp_path, monkeypatch, workflow, runtime, proof, failure=failure,
        node='test_console_project_create_close_acceptance')
    assert len(final['transactions']) == 2
    receipt = json.loads(Path(final['categories'][0]['observation_path']).read_text())
    assert receipt['complete'] is (not fault)
    assert receipt['created_project']['languages'] == ['English(US)', 'External', 'Japanese', 'Mixed', 'SFX']
    assert receipt['created_default_language']['value'] == 'English(US)'
    assert len([uri for uri, _, _ in client.calls if uri == 'ak.wwise.console.project.create']) == 1
    assert len([uri for uri, _, _ in client.calls if uri == 'ak.wwise.console.project.close']) == 1


@pytest.mark.parametrize('fault', [False, True, 'preservation'])
def test_platform_copy_collector_retains_actual_copy_and_preservation_outcome(tmp_path, monkeypatch, fault):
    workflow, runtime, client, proof = _collector_runtime(tmp_path, monkeypatch, 'add-copy', fault=fault)
    failure = None
    try:
        workflow.test_console_project_add_platform_copy_acceptance(runtime)
    except Exception as exc:
        failure = exc
    assert (failure is not None) is bool(fault), failure
    final = _finalize(tmp_path, monkeypatch, workflow, runtime, proof, failure=failure,
        node='test_console_project_add_platform_copy_acceptance')
    assert len(final['transactions']) == 2
    receipt = json.loads(Path(final['categories'][0]['observation_path']).read_text())
    assert receipt['complete'] is (not fault)
    if not fault:
        assert receipt['excluded_project_settings']['source'] != receipt['excluded_project_settings']['target']
        assert {row['property'] for row in receipt['excluded_project_settings']['target']} == {'SoundBankPaths', 'ExternalSourcesOutputPath'}
        assert any(row[2] == 'SoundBankPaths' for row in receipt['explicit_source_values'])
    assert [uri for uri, _, _ in client.calls if uri in ('ak.wwise.core.project.save', 'ak.wwise.cli.addNewPlatform')] == [
        'ak.wwise.core.project.save', 'ak.wwise.cli.addNewPlatform']


@pytest.mark.parametrize('fault', [False, True])
def test_migration_uses_sealed_created_source_in_fresh_runtime_and_final_writer(tmp_path, monkeypatch, fault):
    from tests.destructive.support.console_project_acceptance import load_created_fixture, prepare_console_project_environment
    first = tmp_path / 'creation'
    workflow, creation, _, proof = _collector_runtime(first, monkeypatch, 'cli-create')
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(first / 'category.jsonl'))
    workflow.test_console_project_cli_create_acceptance(creation)
    original = _finalize(first, monkeypatch, workflow, creation, proof, node='test_console_project_cli_create_acceptance')
    manifest = Path(original['categories'][0]['created_fixture']['manifest'])
    donor, _ = load_created_fixture(manifest)
    selected = prepare_console_project_environment({'WAAPI_CONSOLE184_CREATED_MANIFEST': str(manifest)}, 'migrate')
    assert selected['WWISE_SAMPLE_PROJECT_PATH'] == str(donor)
    source_bytes = donor.read_bytes()
    workflow, runtime, client, proof = _collector_runtime(tmp_path / 'migration', monkeypatch, 'migrate', fault=fault, donor=donor)
    runtime.env['WAAPI_CONSOLE184_CREATED_MANIFEST'] = str(manifest)
    failure = None
    try:
        workflow.test_console_project_migrate_created_fixture_acceptance(runtime)
    except Exception as exc:
        failure = exc
    assert (failure is not None) is fault, failure
    final = _finalize(tmp_path / 'migration', monkeypatch, workflow, runtime, proof, failure=failure,
        node='test_console_project_migrate_created_fixture_acceptance')
    assert len(final['transactions']) == 1
    assert donor.read_bytes() == source_bytes
    assert len([uri for uri, _, _ in client.calls if uri == 'ak.wwise.cli.migrate']) == 1


@pytest.mark.parametrize('fault', [False, True])
def test_media_transfer_collector_uses_complete_native_fixture_and_persisted_writer(tmp_path, monkeypatch, fault):
    workflow, runtime, client, proof = _collector_runtime(tmp_path, monkeypatch, 'media-back', fault=fault)
    failure = None
    try:
        workflow.test_console_project_media_ids_to_work_units_acceptance(runtime)
    except Exception as exc:
        failure = exc
    assert (failure is not None) is fault, failure
    final = _finalize(tmp_path, monkeypatch, workflow, runtime, proof, failure=failure,
        node='test_console_project_media_ids_to_work_units_acceptance')
    assert len(final['transactions']) == 2
    receipt = json.loads(Path(final['categories'][0]['observation_path']).read_text())
    assert receipt['complete'] is (not fault)
    assert receipt['prelaunch']['mapping_records']['count'] == 749
    if not fault:
        observed = next(call['payload']['verification']['readbacks'][1] for call in receipt['calls']
            if call['argv'][0] == 'verify' and call['payload'].get('verified') is True)
        assert observed['project_storage_mode_after']['value'] is False
        assert observed['project_storage_mode_after']['representation'] == 'default_elided'
        assert observed['project_storage_mode_after']['source']['installed_build'] == '2025.1.7.9143'
        assert receipt['mapping_after'] == {'exists': False}
    assert len([uri for uri, _, _ in client.calls if uri == 'ak.wwise.core.project.save']) == 1
    assert len([uri for uri, _, _ in client.calls if uri == 'ak.wwise.cli.moveMediaIdsToWorkUnits']) == 1


@pytest.mark.parametrize('fault', [False, True])
def test_media_refresh_collector_preserves_existing_valid_central_mapping_and_sources(tmp_path, monkeypatch, fault):
    workflow, runtime, client, proof = _collector_runtime(tmp_path, monkeypatch, 'media-refresh', fault=fault)
    failure = None
    try:
        workflow.test_console_project_media_ids_refresh_acceptance(runtime)
    except Exception as exc:
        failure = exc
    assert (failure is not None) is fault, failure
    final = _finalize(tmp_path, monkeypatch, workflow, runtime, proof, failure=failure,
        node='test_console_project_media_ids_refresh_acceptance')
    assert len(final['transactions']) == 2
    receipt = json.loads(Path(final['categories'][0]['observation_path']).read_text())
    assert receipt['complete'] is (not fault)
    assert receipt['prelaunch']['mapping_records']['count'] == 749
    assert 'stale_mapping_records' not in receipt
    assert receipt['refresh_scope'] == 'existing_valid_central_mapping_preservation'
    if not fault:
        assert receipt['storage_after']['value'] is True
        assert receipt['media_records_after']['count'] == 0
        assert receipt['mapping_after']['file_proof']['sha256'] == receipt['mapping_before']['file_proof']['sha256']
    assert len([uri for uri, _, _ in client.calls if uri == 'ak.wwise.core.project.save']) == 1
    assert len([uri for uri, _, _ in client.calls if uri == 'ak.wwise.cli.updateMediaIdsInSingleFile']) == 1


@pytest.mark.parametrize('gate', ['before-final', 'final-failed', 'mutated-donor'])
def test_created_project_donor_requires_final_success_and_immutable_bytes(tmp_path, monkeypatch, gate):
    from tests.destructive.support.console_project_acceptance import load_created_fixture, prepare_console_project_environment
    workflow, runtime, _, proof = _collector_runtime(tmp_path, monkeypatch, 'cli-create')
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(tmp_path / 'category.jsonl'))
    workflow.test_console_project_cli_create_acceptance(runtime)
    manifest = Path(runtime.category_results[0]['created_fixture']['manifest'])
    if gate != 'before-final':
        _finalize(tmp_path, monkeypatch, workflow, runtime, proof,
            failure=AssertionError('late lifecycle failure') if gate == 'final-failed' else None,
            node='test_console_project_cli_create_acceptance')
    if gate == 'mutated-donor':
        donor, _ = load_created_fixture(manifest)
        donor.write_bytes(donor.read_bytes() + b'\n')
    with pytest.raises((AssertionError, ValueError)):
        prepare_console_project_environment({'WAAPI_CONSOLE184_CREATED_MANIFEST': str(manifest)}, 'migrate')


@pytest.mark.parametrize('invalid', ['wrong-version', 'multiple-nodes'])
def test_console_project_witness_selection_is_singleton_and_version_pinned(invalid):
    from tests.destructive.support.console_project_acceptance import select_console_project_case
    node = 'tests/destructive/test_gateway_workflow_transaction_matrix.py::test_console_project_cli_create_acceptance'
    assert select_console_project_case([node], '2024.1') == 'cli-create'
    with pytest.raises(AssertionError):
        select_console_project_case([node] if invalid == 'wrong-version' else [node, node], '2025.1' if invalid == 'wrong-version' else '2024.1')


@pytest.mark.parametrize('wrong_record', [False, True])
def test_complete_retained_media_fixture_matches_normalized_source_before_staging(tmp_path, wrong_record):
    from tests.destructive.support.console_project_acceptance import stage_media_storage_fixture
    source = Path(__file__).resolve().parents[1] / '_org/2025.1'
    project_root = tmp_path / 'project'
    shutil.copytree(source, project_root)
    project = project_root / 'SampleProject.wproj'
    io = tmp_path / 'normalization'; io.mkdir()
    normalize_project_copy(project, io_root=io, owned_root=tmp_path,
        request=ProjectPrelaunchRequest(scenario_id='gateway-workflow-transaction-matrix',
            auro_isolation_profile=WWISE_2025_SOUNDBANK_AURO_PROFILE))
    if wrong_record:
        unit = project_root / 'Containers/Ambisonics.wwu'
        tree = ET.parse(unit)
        media = tree.find('.//MediaID')
        media.set('ID', str(int(media.get('ID')) + 1))
        tree.write(unit)
    if wrong_record:
        with pytest.raises(AssertionError, match='complete source/media records'):
            stage_media_storage_fixture(project, central=True)
    else:
        proof = stage_media_storage_fixture(project, central=True)
        assert proof['mapping_records'] == proof['work_unit_records_before']
        assert proof['mapping_records']['count'] == 749
        assert proof['work_unit_records_after']['count'] == 0
        assert proof['source_descriptors_preserved'] is True


@pytest.mark.parametrize('case,fault', [('create-close', 'missing-default'), ('create-close', 'indeterminate-created'),
    ('cli-create', 'indeterminate-created')])
def test_creation_failure_retains_exact_requested_output_before_verification_and_cleanup(tmp_path, monkeypatch, case, fault):
    import hashlib
    workflow, runtime, client, proof = _collector_runtime(tmp_path, monkeypatch, case, fault=fault)
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(tmp_path / 'category.jsonl'))
    node = ('test_console_project_create_close_acceptance' if case == 'create-close'
        else 'test_console_project_cli_create_acceptance')
    with pytest.raises(AssertionError) as failure:
        getattr(workflow, node)(runtime)
    expected = client.created_file.read_bytes()
    receipt = json.loads((runtime.state_dir / ('console184-' + case + '.json')).read_text())
    captured = receipt['created_output']
    assert captured['requested_project'] == str(client.created_file)
    index = json.loads(Path(captured['index_path']).read_text())
    image = Path(captured['index_path']).parent.parent / index['files'][client.created_file.name]['artifact_path']
    assert image.read_bytes() == expected
    assert index['files'][client.created_file.name]['sha256'] == hashlib.sha256(expected).hexdigest()
    assert captured['complete'] is True and receipt['complete'] is False
    final = _finalize(tmp_path, monkeypatch, workflow, runtime, proof, failure=failure.value, node=node)
    assert final['transactions'][0]['state'] == ('verification_failed' if fault == 'missing-default' else 'indeterminate')
    assert Path(captured['index_path']).is_file() and image.read_bytes() == expected
    assert not any(uri == 'ak.wwise.console.project.close' for uri, _, _ in client.calls)
    create_uri = 'ak.wwise.console.project.create' if case == 'create-close' else 'ak.wwise.cli.createNewProject'
    target = next(i for i, (uri, _, _) in enumerate(client.calls) if uri == create_uri)
    if fault == 'indeterminate-created':
        assert all(uri == 'ak.wwise.core.getInfo' for uri, _, _ in client.calls[target + 1:])


@pytest.mark.parametrize('fault', ['partial-no-project', 'partial-link', 'partial-oversize'])
def test_partial_creation_retains_bounded_owned_subtree_without_a_project_file(tmp_path, monkeypatch, fault):
    import hashlib
    workflow, runtime, client, proof = _collector_runtime(tmp_path, monkeypatch, 'cli-create', fault=fault)
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(tmp_path / 'category.jsonl'))
    with pytest.raises(AssertionError) as failure:
        workflow.test_console_project_cli_create_acceptance(runtime)
    receipt = json.loads((runtime.state_dir / 'console184-cli-create.json').read_text())
    capture = receipt['created_output']['target_tree']
    manifest_path = Path(capture['manifest_path'])
    manifest = json.loads(manifest_path.read_text())
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == capture['manifest_sha256']
    assert receipt['complete'] is False and not client.created_file.exists()
    assert receipt.get('created_fixture') is None
    if fault == 'partial-no-project':
        assert capture['complete'] is True and capture['file_count'] == 2
        expected = {'Events/partial.wwu': b'partial native Work Unit bytes', 'creation.log': b'partial creation log'}
        assert {row['path'] for row in manifest['files']} == set(expected)
        assert manifest['directories'] == ['Events', 'Unfinished', 'Unfinished/Empty']
        assert (manifest_path.parent / 'target/Unfinished/Empty').is_dir()
        for row in manifest['files']:
            image = manifest_path.parent.joinpath(*parse_archive_relative_path(row['artifact_path']).parts)
            identity = parse_archive_relative_path(row['path'])
            assert identity.canonical == row['path']
            assert image.read_bytes() == expected[identity.canonical]
            assert row['sha256'] == hashlib.sha256(expected[row['path']]).hexdigest()
    else:
        assert capture['complete'] is False
        assert manifest['errors'][0]['code'] == ('SYMLINK_NOT_ALLOWED' if fault == 'partial-link' else 'LIMIT_EXCEEDED')
        assert manifest['files'] == []
        if fault == 'partial-link': assert (tmp_path / 'outside-target.bin').read_bytes() == b'outside target bytes'
    final = _finalize(tmp_path, monkeypatch, workflow, runtime, proof, failure=failure.value,
        node='test_console_project_cli_create_acceptance')
    assert final['transactions'][0]['state'] == 'indeterminate'
    assert not client.created_file.parent.exists() and manifest_path.is_file()
    assert len([uri for uri, _, _ in client.calls if uri == 'ak.wwise.cli.createNewProject']) == 1
    target = next(i for i, (uri, _, _) in enumerate(client.calls) if uri == 'ak.wwise.cli.createNewProject')
    assert all(uri == 'ak.wwise.core.getInfo' for uri, _, _ in client.calls[target + 1:])


@pytest.mark.skipif(os.name == 'nt', reason='Windows cannot create the physical nonportable POSIX names under test')
@pytest.mark.parametrize('fault', ['partial-archive-file', 'partial-archive-directory'])
def test_creation_capture_rejects_nonportable_physical_archive_identities(tmp_path, monkeypatch, fault):
    workflow, runtime, client, proof = _collector_runtime(tmp_path, monkeypatch, 'cli-create', fault=fault)
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(tmp_path / 'category.jsonl'))
    with pytest.raises(AssertionError) as failure:
        workflow.test_console_project_cli_create_acceptance(runtime)
    receipt = json.loads((runtime.state_dir / 'console184-cli-create.json').read_text())
    capture = receipt['created_output']['target_tree']
    manifest_path = Path(capture['manifest_path'])
    manifest = json.loads(manifest_path.read_text())
    assert capture['complete'] is False
    assert manifest['errors'][0]['code'] == 'ArchiveRelativePathError'
    assert not any(':' in row['path'] for row in manifest['files'])
    assert not any(':' in row for row in manifest['directories'])
    final = _finalize(tmp_path, monkeypatch, workflow, runtime, proof, failure=failure.value,
        node='test_console_project_cli_create_acceptance')
    assert final['transactions'][0]['state'] == 'indeterminate' and manifest_path.is_file()


@pytest.mark.parametrize('fault', [False, 'wrong-version', 'preservation'])
def test_committed_2024_migration_uses_separate_target_after_host_ready_and_final_writer(tmp_path, monkeypatch, fault):
    workflow, runtime, client, proof = _collector_runtime(tmp_path, monkeypatch, 'migrate-committed-2024', fault=fault)
    host_bytes = runtime.sandbox.sandbox_project.read_bytes()
    assert not (runtime.sandbox.sandbox_root / 'migration-committed-2024').exists()
    failure = None
    try:
        workflow.test_console_project_migrate_committed_2024_fixture_acceptance(runtime)
    except Exception as exc:
        failure = exc
    assert (failure is not None) is bool(fault), failure
    assert runtime.sandbox.sandbox_project.read_bytes() == host_bytes
    targets = [(args, options) for uri, args, options in client.calls if uri == 'ak.wwise.cli.migrate']
    assert len(targets) == 1
    args, options = targets[0]
    assert options == {} and set(args) == {'project'}
    target = Path(args['project'])
    assert target != runtime.sandbox.sandbox_project and not target.is_relative_to(runtime.sandbox.sandbox_path)
    assert not any(uri in {'ak.wwise.core.project.save', 'ak.wwise.console.project.open', 'ak.wwise.console.project.create',
        'ak.wwise.cli.createNewProject'} for uri, _, _ in client.calls)
    final = _finalize(tmp_path, monkeypatch, workflow, runtime, proof, failure=failure,
        node='test_console_project_migrate_committed_2024_fixture_acceptance')
    assert len(final['transactions']) == 1
    assert final['categories'][0]['status'] == ('FAIL' if fault else 'PASS')
    receipt = json.loads(Path(final['categories'][0]['observation_path']).read_text())
    assert receipt['case'] == 'migrate-committed-2024'
    assert receipt['migration_fixture']['authority'] == 'committed-tests-org-2024.1'
    assert receipt['migration_fixture']['created_after_host_readiness'] is True
    assert receipt['project_before']['wwise_version'] == 'v2024.1.0'
    assert receipt['model_before']['complete'] is receipt['model_after']['complete'] is True
    assert receipt['immutable_sources_before'] == receipt['immutable_sources_after']
    assert receipt['immutable_sources_verified'] is True
    assert set(receipt['immutable_sources_before']) == {'host', 'migration'}
    assert receipt['phases'][0]['verify']['state'] == ('verification_failed' if fault else 'verified')
    assert not runtime.sandbox.sandbox_root.exists()
    assert Path(receipt['model_after']['index_path']).is_file()
    for phase in ('before', 'after'):
        capture = receipt['target_tree_' + phase]
        assert capture['complete'] is True and capture['requested_project_exists'] is True
        manifest = json.loads(Path(capture['manifest_path']).read_text())
        for row in manifest['files']:
            assert parse_archive_relative_path(row['path']).canonical == row['path']
            assert parse_archive_relative_path(row['artifact_path']).canonical == row['artifact_path']


def test_migration_retains_remaining_work_units_when_indeterminate_project_disappears(tmp_path, monkeypatch):
    workflow, runtime, client, proof = _collector_runtime(tmp_path, monkeypatch, 'migrate-committed-2024', fault='missing-project')
    with pytest.raises(AssertionError) as failure:
        workflow.test_console_project_migrate_committed_2024_fixture_acceptance(runtime)
    final = _finalize(tmp_path, monkeypatch, workflow, runtime, proof, failure=failure.value,
        node='test_console_project_migrate_committed_2024_fixture_acceptance')
    receipt = json.loads(Path(final['categories'][0]['observation_path']).read_text())
    assert final['categories'][0]['status'] == 'FAIL'
    assert final['transactions'][0]['state'] == 'indeterminate'
    assert receipt['immutable_sources_verified'] is True
    assert not runtime.sandbox.sandbox_root.exists()
    capture = receipt['target_tree_after']
    assert isinstance(capture, dict), 'Migration must retain raw target-tree bytes after the project disappears'
    assert capture['requested_project_exists'] is False
    manifest_path = Path(capture['manifest_path'])
    manifest = json.loads(manifest_path.read_text())
    assert capture['complete'] is True
    relative = archive_relative_from_absolute(client.remaining_unit, manifest['target']).canonical
    row = next(row for row in manifest['files'] if row['path'] == relative)
    image = manifest_path.parent.joinpath(*parse_archive_relative_path(row['artifact_path']).parts)
    assert image.read_bytes() == client.remaining_bytes
    assert receipt['after_capture_error']
    assert len([uri for uri, _, _ in client.calls if uri == 'ak.wwise.cli.migrate']) == 1


@pytest.mark.skipif(os.name == 'nt', reason='Windows cannot create the physical nonportable POSIX names under test')
@pytest.mark.parametrize('fault', ['archive-file', 'archive-directory'])
def test_migration_capture_rejects_nonportable_target_archive_identities(tmp_path, monkeypatch, fault):
    workflow, runtime, client, proof = _collector_runtime(tmp_path, monkeypatch, 'migrate-committed-2024', fault=fault)
    with pytest.raises(AssertionError) as failure:
        workflow.test_console_project_migrate_committed_2024_fixture_acceptance(runtime)
    final = _finalize(tmp_path, monkeypatch, workflow, runtime, proof, failure=failure.value,
        node='test_console_project_migrate_committed_2024_fixture_acceptance')
    receipt = json.loads(Path(final['categories'][0]['observation_path']).read_text())
    assert final['categories'][0]['status'] == 'FAIL'
    assert receipt['complete'] is False and receipt['immutable_sources_verified'] is True
    capture = receipt['target_tree_after']
    manifest = json.loads(Path(capture['manifest_path']).read_text())
    assert capture['complete'] is False and receipt['migration_preservation_error']
    assert manifest['errors'][0]['code'] == 'ArchiveRelativePathError'
    assert not any(':' in row['path'] for row in manifest['files'])
    assert not any(':' in row for row in manifest['directories'])
    assert not runtime.sandbox.sandbox_root.exists()
    assert len([uri for uri, _, _ in client.calls if uri == 'ak.wwise.cli.migrate']) == 1
