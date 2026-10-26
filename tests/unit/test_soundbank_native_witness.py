"""Core file witnesses reach the existing persisted category writer without Wwise."""
from copy import deepcopy
import importlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from tests.destructive.support import sandbox_fixture, exact_real_evidence
from tests.semantic.support.codex_project_prelaunch_v3 import (
    normalize_project_copy, ProjectPrelaunchRequest, WWISE_2025_SOUNDBANK_AURO_PROFILE,
)
from tests.unit.test_operation_registry_soundbank import _project, _row, CONVERSION_ID
from tests.unit.test_soundbank_business_gateway import _env, _info

NODE = 'test_core_audio_conversion_temporary_bank_and_default_external_conversion'


@pytest.mark.parametrize('missing_artifact', [False, True])
def test_core_soundbank_collector_reaches_persisted_final_writer(tmp_path, monkeypatch, missing_artifact):
    monkeypatch.setenv('WWISE_LIVE', '1'); monkeypatch.setenv('WWISE_DESTRUCTIVE', '1')
    workflow = importlib.import_module('tests.destructive.test_gateway_workflow_transaction_matrix')
    source = tmp_path / 'source'
    shutil.copytree(Path(__file__).resolve().parents[1] / '_org/2025.1', source)
    proof = sandbox_fixture.hash_project(source)
    io_root, project = _project(tmp_path)
    project_root = Path(project['path']).parent
    shutil.copytree(source, project_root, dirs_exist_ok=True)
    prelaunch_io = io_root / 'prelaunch-io'; prelaunch_io.mkdir()
    prelaunch = normalize_project_copy(Path(project['path']), io_root=prelaunch_io, owned_root=io_root,
        request=ProjectPrelaunchRequest(scenario_id='gateway-workflow-transaction-matrix',
            auro_isolation_profile=WWISE_2025_SOUNDBANK_AURO_PROFILE)).as_dict()
    project['id'] = ET.parse(project['path']).find('./ProjectInfo/Project').attrib['ID']
    platform = project['platforms'][0]
    platform.update(name='Windows', baseName='Windows', baseDisplayName='Windows',
        soundBankPath=str(prelaunch_io / 'soundbanks/Windows'), copiedMediaPath=str(prelaunch_io / 'soundbanks/Windows'))
    project['directories'].update(cache=str(prelaunch_io / 'cache'), soundBankOutputRoot=str(prelaunch_io / 'soundbanks'))
    event_xml = ET.parse(project_root / 'Events/Default Work Unit.wwu')
    event = event_xml.find(".//Event[@Name='Play_Rifle']")
    event_row = _row(event.attrib['ID'], event.attrib['Name'], 'Event',
        r'\Events\Default Work Unit\WAAPI_Skill_Integration_V2\Play_Rifle')

    sound = ET.parse(project_root / 'Containers/Default Work Unit.wwu').find(".//Sound[@Name='Metal_Step_01']")
    source_node = sound.find('./ChildrenList/AudioFileSource')
    original = project_root / 'Originals/SFX/WAAPI Skill Integration V2/metal_step_01.wav'
    converted = prelaunch_io / 'cache/Windows/SFX/metal_step_01.wem'
    sound_row = _row(sound.attrib['ID'], sound.attrib['Name'], 'Sound', r'\Containers\Default Work Unit\Metal_Step_01')
    sound_row.update({'@IsVoice': False, 'activeSource': {'id': source_node.attrib['ID']},
        'originalFilePath': str(original), 'convertedFilePath': str(converted)})
    source_row = _row(source_node.attrib['ID'], source_node.attrib['Name'], 'AudioFileSource',
        sound_row['path'] + '\\' + source_node.attrib['Name'], parent=sound_row['id'])
    source_row.update(originalFilePath=str(original), convertedFilePath=str(converted), **{'audioSource:language': {
        'id': '{85A66963-A627-476E-91C1-2770B39D245A}', 'name': 'SFX'}})

    class Client:
        def __init__(self): self.calls = []; self.writes = []
        def disconnect(self): pass
        def call(self, uri, args=None, options=None):
            args, options = args or {}, options or {}
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            if uri == 'ak.wwise.core.getInfo':
                info = _info(); info['version'].update(minor=7, build=9143, displayName='v2025.1.7.9143'); return info
            if uri == 'ak.wwise.core.getProjectInfo': return deepcopy(project)
            if uri == 'ak.wwise.core.object.get':
                ids = args.get('from', {}).get('id', [])
                if ids == [event_row['id']] or event_row['id'].casefold() in json.dumps(args).casefold(): return {'return': [deepcopy(event_row)]}
                for row in (sound_row, source_row):
                    if row['id'].casefold() in json.dumps(args).casefold(): return {'return': [deepcopy(row)]}
                if ids == [CONVERSION_ID]: return {'return': [_row(CONVERSION_ID, 'PCM', 'Conversion', r'\Conversion Settings\PCM')]}
                return {'return': []}
            if uri == 'ak.wwise.core.audio.convert':
                self.writes.append((uri, deepcopy(args)))
                assert args == {'objects': [sound_row['id']], 'platforms': ['Windows'], 'languages': ['SFX']}
                converted.parent.mkdir(parents=True, exist_ok=True); converted.write_bytes(b'RIFF-native-converted-audio')
                return {'errors': []}
            if uri == 'ak.wwise.core.soundbank.generate':
                self.writes.append((uri, deepcopy(args)))
                bank = Path(platform['soundBankPath']) / (args['soundbanks'][0]['name'] + '.bnk')
                bank.parent.mkdir(parents=True, exist_ok=True); bank.write_bytes(b'BKHD-native-bank')
                return {}
            if uri == 'ak.wwise.core.soundbank.convertExternalSources':
                self.writes.append((uri, deepcopy(args)))
                assert 'output' not in args['sources'][0]
                output = Path(project['directories']['cache']) / 'ExternalSources/Windows/CoreWitness/external.wem'
                output.parent.mkdir(parents=True, exist_ok=True); output.write_bytes(b'RIFF-native-wem')
                return {}
            raise AssertionError((uri, args, options))
    client = Client()
    execute = workflow.waapi_gateway.execute_gateway
    def gateway(argv, **kwargs):
        code, payload = execute(argv, **kwargs, client_factory=lambda _: client)
        if missing_artifact and 'verify' in argv and len(client.writes) == 1 and code == 0:
            # External file loss after a genuine successful Gateway verification
            # must still fail the collector's independent artifact observation.
            converted.unlink()
        return code, payload
    monkeypatch.setattr(workflow.waapi_gateway, 'execute_gateway', gateway)
    source_project = source / 'SampleProject.wproj'
    metadata = sandbox_fixture.SandboxMetadata(str(source_project), str(source), str(project_root), project['path'],
        '2025.1', 0, proof, sandbox_fixture.hash_project(project_root), source_project.stat().st_mtime,
        process_cleanup_result='cleaned', process_cleanup_details={'residual_processes': []})
    sandbox = sandbox_fixture.SandboxProject(source_project, source, io_root, project_root, Path(project['path']), metadata)
    lock = sandbox_fixture.LiveSandboxLock(tmp_path / 'locks'); lock.__enter__()
    env = _env(tmp_path); env['WWISE_EVIDENCE_DIR'] = str(tmp_path / 'native')
    runtime = workflow._WorkflowSandboxRuntime('2025.1', sandbox,
        SimpleNamespace(host='127.0.0.1', port=31337, waapi_url='ws://127.0.0.1:31337/waapi'),
        tmp_path / 'state', env, workflow.exact_git_candidate(workflow.REPO_ROOT), [])
    runtime.soundbank_prelaunch = prelaunch
    failure = None
    try:
        getattr(workflow, NODE)(runtime)
    except Exception as exc:
        failure = exc
    assert (failure is not None) is missing_artifact, failure
    assert len(client.writes) == (1 if missing_artifact else 3)
    category_path = tmp_path / 'category.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(category_path))
    monkeypatch.setattr(sandbox_fixture, 'KEEP_ON_FAILURE_ROOT', tmp_path / 'retained')
    nodeid = 'tests/destructive/test_gateway_workflow_transaction_matrix.py::' + NODE
    item = SimpleNamespace(path=workflow.__file__, nodeid=nodeid,
        _waapi_phase_reports={'setup': 'passed', 'call': 'failed' if failure else 'passed'})
    assert sandbox_fixture.hash_project(source) == proof
    final_error = exact_real_evidence.finalize_exact_real_evidence(
        repo_root=workflow.REPO_ROOT, candidate=runtime.candidate, version=runtime.version,
        request=SimpleNamespace(session=SimpleNamespace(items=[item])), module_file=Path(workflow.__file__),
        started_at_unix_ns=1, active_error=failure, deferred_error=None, sandbox=sandbox, lock=lock,
        state_dir=runtime.state_dir, host={'is_command_line': True, 'version': '2025.1.7.9143'},
        categories=runtime.category_results, source={'hash_before': proof.digest,
            'hash_after': sandbox_fixture.hash_project(source).digest}, case_cleanup_root=io_root)
    assert final_error is None
    assert not io_root.exists(), 'The entire owned parent, including sibling cache/output roots, must be cleaned'
    rows = [json.loads(line) for line in category_path.read_text().splitlines()]
    final = rows[-1]
    assert final['invocation']['phase'] == 'final'
    assert final['invocation']['outcome'] == ('FAIL' if missing_artifact else 'PASS')
    assert len(final['transactions']) == (1 if missing_artifact else 3)
    statuses = [item['status'] for item in final['categories']]
    assert statuses == (['FAIL', 'blocked', 'blocked'] if missing_artifact else ['PASS', 'PASS', 'PASS'])
    assert final['residual_state']['sandbox'] == ('quarantined' if missing_artifact else 'deleted')
    receipt = json.loads(Path(final['categories'][0]['observation_path']).read_text())
    assert receipt['complete'] is (not missing_artifact)
    assert receipt['input_preservation_verified'] is True
    assert receipt['audio_conversion']['diagnostic_result'] == {'errors': []}
    assert receipt['audio_conversion']['sound_after']['converted_file_path'] == receipt['audio_conversion']['source_after']['converted_file_path']
    assert receipt['phases'][0]['verify']['verification']['business_state_verified'] is False
    assert receipt['phases'][0]['verify']['state'] == 'result_schema_checked'
    assert receipt['phases'][0]['effect_verified'] is (not missing_artifact)
    if missing_artifact:
        assert receipt['failure']['details']['error_code'] == 'MISSING_PATH'
    assert len(receipt['phases']) == (1 if missing_artifact else 3)
    if not missing_artifact:
        assert all(phase['effect_verified'] for phase in receipt['phases'])
        assert all(phase['verify']['verification']['business_state_verified'] for phase in receipt['phases'][1:])
        assert len(receipt['audio_conversion']['new_converted_paths']) == 1
    assert receipt['prelaunch']['auro_soundbank_isolation']['profile'] == WWISE_2025_SOUNDBANK_AURO_PROFILE
    assert [row['input_sha256'] for row in receipt['prelaunch']['auro_soundbank_isolation']['work_units']] == [
        '0d06c10e0e632bdb723d00922d38e1796561c781b11c8d71f5b7eeedb10130b6',
        '66ef565e7b4e28ed39b189284700d44f67cdb8c4f9035fa5a04842d2c050e29a']
