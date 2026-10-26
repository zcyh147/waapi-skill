"""Console project witnesses through the public Gateway and persisted writer."""
from pathlib import Path
from copy import deepcopy
import importlib
import json
import shutil
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from tests.semantic.support.codex_project_prelaunch_v3 import (
    normalize_project_copy, ProjectPrelaunchRequest, WWISE_2025_SOUNDBANK_AURO_PROFILE,
)
from tests.destructive.support import sandbox_fixture, exact_real_evidence
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
                if case == 'cli-create' and fault:
                    tree.find('./ProjectInfo/Project/Platforms/Platform').set('ReferencePlatform', 'Mac')
                tree.write(self.created_file)
                if uri == 'ak.wwise.console.project.create': self.active_file = self.created_file
                self.calls.append((uri, deepcopy(args), deepcopy(options)))
                if uri.startswith('ak.wwise.cli.'): self.terminal = True
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
                if not fault:
                    tree = ET.parse(self.project_file); tree.getroot().set('WwiseVersion', 'v2025.1.7'); tree.write(self.project_file)
                self.terminal = True
                return {'result': 0}
            if uri == 'ak.wwise.cli.addNewPlatform':
                self.calls.append((uri, deepcopy(args), deepcopy(options)))
                tree = ET.parse(self.project_file)
                ET.SubElement(tree.find('./ProjectInfo/Project/Platforms'), 'Platform',
                    Name='ReviewCopy', ReferencePlatform='Windows', ID='{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}')
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
                        document.find('./ProjectInfo/Project/PropertyList/Property[@Name="MediaIDsInSingleFile"]').set('Value', 'False')
                    if fault and not fault_applied[0] and document.find('.//MediaID') is not None:
                        media = document.find('.//MediaID'); media.set('ID', str(int(media.get('ID')) + 1))
                        fault_applied[0] = True
                    ET.ElementTree(document).write(path, encoding='utf-8')
                self.calls.append((uri, deepcopy(args), deepcopy(options))); self.terminal = True
                return {'result': 0}
            if uri == 'ak.wwise.cli.updateMediaIdsInSingleFile':
                from tests.destructive.support.console_project_acceptance import retained_mapping
                if not fault: self.project_file.with_suffix('.mediaid').write_bytes(retained_mapping()[0])
                self.calls.append((uri, deepcopy(args), deepcopy(options))); self.terminal = True
                return {'result': 0}
            return super().call(uri, args, options)
    fault_applied = [False]
    client = Client(tmp_path, version, 'ak.wwise.cli.createNewProject')
    client.unit = saved_fixture_project(client)
    prelaunch = None
    if case in {'media-back', 'media-refresh'}:
        from tests.destructive.support.console_project_acceptance import stage_media_storage_fixture
        owned = client.project_file.parent
        shutil.rmtree(owned)
        shutil.copytree(Path(__file__).resolve().parents[1] / '_org/2025.1', owned)
        client.project_file = owned / 'SampleProject.wproj'
        io = tmp_path / 'normalization'; io.mkdir()
        normalize_project_copy(client.project_file, io_root=io, owned_root=tmp_path,
            request=ProjectPrelaunchRequest(scenario_id='gateway-workflow-transaction-matrix',
                auro_isolation_profile=WWISE_2025_SOUNDBANK_AURO_PROFILE))
        prelaunch = stage_media_storage_fixture(client.project_file, central=case == 'media-back')
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
    sandbox = sandbox_fixture.SandboxProject(source_project, source, owned, owned, client.project_file, metadata)
    execute = public_gateway.execute_gateway
    monkeypatch.setattr(workflow.waapi_gateway, 'execute_gateway',
        lambda argv, **kwargs: execute(argv, **kwargs, client_factory=lambda _: client))
    runtime = workflow._WorkflowSandboxRuntime(version, sandbox,
        SimpleNamespace(host='127.0.0.1', port=31337, waapi_url='ws://127.0.0.1:31337/waapi'),
        tmp_path / 'collector-state', client.env, workflow.exact_git_candidate(workflow.REPO_ROOT), [])
    runtime.console_project_prelaunch = prelaunch
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
        assert receipt['created_project']['platforms'] == [['Windows', 'Windows'], ['Mac', 'Mac']]
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
    assert len([uri for uri, _, _ in client.calls if uri == 'ak.wwise.core.project.save']) == 1
    assert len([uri for uri, _, _ in client.calls if uri == 'ak.wwise.cli.moveMediaIdsToWorkUnits']) == 1


@pytest.mark.parametrize('fault', [False, True])
def test_media_refresh_collector_replaces_stale_owned_file_and_preserves_saved_sources(tmp_path, monkeypatch, fault):
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
    assert receipt['stale_mapping_records'] != receipt['prelaunch']['mapping_records']
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
