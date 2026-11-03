"""Prepared Marker fixture through the real Gateway; no Wwise process or socket."""
import copy
import json
from pathlib import Path
import re
import shutil
from types import SimpleNamespace
import uuid

import pytest

from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, SECOND
from tests.unit.test_workflow_source_guard import workflow


def marker_runtime(tmp_path, workflow, monkeypatch, fault='none'):
    from tests.destructive import test_query_modern_markers as witness
    source = tmp_path / 'source'
    shutil.copytree(witness.REPO / 'tests/_org/2025.1', source)
    owned = tmp_path / 'owned'; sandbox = owned / 'project'
    shutil.copytree(source, sandbox)
    prelaunch_io = owned / 'prelaunch-io'; prelaunch_io.mkdir()
    prepared = workflow.normalize_project_copy(sandbox / 'SampleProject.wproj', io_root=prelaunch_io,
        owned_root=owned, request=workflow.ProjectPrelaunchRequest(scenario_id='gateway-workflow-transaction-matrix',
            auro_isolation_profile=workflow.WWISE_2025_SOUNDBANK_AURO_PROFILE))
    assert prepared.auro_soundbank_isolation is not None
    (owned / 'prelaunch-helper-report.json').write_text(json.dumps(prepared.as_dict(), indent=2))
    transport = tmp_path / 'transport'; transport.mkdir()
    task = OwnedGraphTask(transport, '2025.1', 'audio.import')
    task.project_file = sandbox / 'SampleProject.wproj'
    parent = {'id': SECOND, 'name': 'Default Work Unit', 'type': 'WorkUnit', 'classId': 1638416,
        'path': r'\Containers\Default Work Unit', 'notes': ''}
    task.objects = {SECOND: parent}
    task.types = [{'name': kind, 'classId': class_id, 'type': 'WObject'} for kind, class_id in
        [('WorkUnit', 1638416), ('Sound', 65552), ('AudioFileSource', 16), ('Marker', 5373968)]]
    task.metadata = {'IsVoice': {'name': 'IsVoice', 'type': 'bool', 'default': False},
        'MarkerInputMode': {'name': 'MarkerInputMode', 'type': 'int16', 'default': 0,
            'restriction': {'type': 'enum', 'values': [{'value': n} for n in (0, 1, 2)]}},
        'Time': {'name': 'Time', 'type': 'Real64', 'default': 0},
        'Label': {'name': 'Label', 'type': 'string', 'default': ''}}
    original = task.call; writes = []; membership = []; commands = []
    def native(uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri.endswith('getInfo'):
            result = original(uri, args, options)
            result['version'].update(dict(zip(('year', 'major', 'minor', 'build'), witness.BUILDS['2025.1'])))
            return result
        if uri.endswith('getProjectInfo'):
            from tests.unit.test_object_native_surface import _project_info
            return {**_project_info(sandbox, language='SFX'), **original(uri, args, options)}
        if uri.endswith('audio.import'):
            task.calls.append((uri, copy.deepcopy(args), copy.deepcopy(options))); writes.append(copy.deepcopy(args))
            result = []; files = []
            for node in args['imports']:
                path = re.sub(r'<[^>]+>', '', node['objectPath'])
                identity = '{' + str(uuid.uuid4()).upper() + '}'
                assert node['objectType'] == 'Sound SFX' and node['importLanguage'] == 'SFX'
                owner = {'id': identity, 'name': path.rsplit('\\', 1)[1], 'type': 'Sound', 'classId': 65552,
                    'path': path, 'parent': {'id': SECOND}, 'notes': '', '@IsVoice': False}
                task.objects[identity] = owner
                if 'audioFile' in node:
                    identity = '{' + str(uuid.uuid4()).upper() + '}'
                    copied = sandbox / 'Originals/SFX' / Path(node['audioFile']).name
                    copied.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(node['audioFile'], copied)
                    files.append(str(copied))
                    row = {'id': identity, 'name': Path(node['audioFile']).stem, 'type': 'AudioFileSource', 'classId': 16,
                        'path': path + '\\' + Path(node['audioFile']).stem, 'parent': {'id': owner['id']}, 'notes': '', 'originalFilePath': str(copied),
                        'audioSource:language': {'name': 'SFX'}, '@MarkerInputMode': 1 if fault == 'mode' else 0}
                    owner.update(activeSource={'id': identity}, originalFilePath=str(copied))
                    marker_id = '{' + str(uuid.uuid4()).upper() + '}'
                    task.objects[marker_id] = {'id': marker_id, 'name': '', 'type': 'Marker', 'classId': 5373968,
                        'path': row['path'] + r'\[Marker]', 'owner': {'id': identity}, '@Time': 0.0, '@Label': 'R89_MARKER'}
                    row['@Markers'] = [{'id': marker_id}]
                    task.objects[identity] = row; result.append(row)
                result.append(owner)
            return {'objects': task.project_rows(result, options), 'log': [], 'files': files}
        if uri.endswith('object.get') and args.get('waql', '').startswith('from object "'):
            task.calls.append((uri, copy.deepcopy(args), copy.deepcopy(options)))
            match = re.fullmatch(r'from object "([^"]+)"( select @Markers)? take ([12])', args['waql'])
            assert match, args
            rows = [row for row in task.objects.values() if match[1] in (row['id'], row['path'])]
            if match[2]:
                membership.append(copy.deepcopy(args))
                rows = [task.objects[member['id']] for row in rows for member in row['@Markers']]
                if fault == 'empty': rows = []
                elif fault == 'wrong-owner': rows = [{**row, 'owner': {'id': SECOND}} for row in rows]
                elif fault == 'wrong-class': rows = [{**row, 'classId': 16} for row in rows]
                elif fault == 'bound': rows = rows * 2
                elif fault == 'record': rows = [{'Time': 0.0, 'Label': 'R89_MARKER'}]
            return {'return': task.project_rows(rows[:int(match[3])], options)}
        return original(uri, args, options)
    task.call = native
    packets = owned / 'packets'; packets.mkdir()
    runtime = SimpleNamespace(version='2025.1', candidate='program-only', category_results=[], state_dir=owned / 'state',
        sandbox=SimpleNamespace(source_root=source, sandbox_path=sandbox, sandbox_project=task.project_file,
            metadata=SimpleNamespace(get_info_version=dict(zip(('year','major','minor','build'), witness.BUILDS['2025.1'])))),
        env=task.env, port=31337, lifecycle=SimpleNamespace(host='127.0.0.1', waapi_url='ws://127.0.0.1:31337/waapi'))
    task.env.update(WWISE_EVIDENCE_DIR=str(packets), WAAPI_SKILL_STATE_DIR=str(runtime.state_dir))
    def forbidden(*args, **kwargs): raise AssertionError('No real client or socket is permitted')
    monkeypatch.setattr(workflow.waapi_gateway, 'default_client_factory', forbidden)
    execute = workflow.waapi_gateway.execute_gateway
    def injected(argv, **kwargs): return execute(argv, client_factory=lambda _: task, **kwargs)
    monkeypatch.setattr(workflow.waapi_gateway, 'execute_gateway', injected)
    def raw(argv):
        commands.append(list(argv))
        return workflow.waapi_gateway.execute_gateway(['--timeout', '30', '--state-dir', str(runtime.state_dir), *argv], env=runtime.env)
    runtime.raw_gateway = raw
    return runtime, task, commands, writes, membership


def test_modern_marker_import_and_positive_read_use_whole_public_flow(tmp_path, workflow, monkeypatch):
    from tests.destructive import test_query_modern_markers as witness
    runtime, task, commands, writes, membership = marker_runtime(tmp_path, workflow, monkeypatch)
    witness.test_imported_modern_marker_has_canonical_identity_and_typed_values(runtime, monkeypatch)
    category, = runtime.category_results
    body = Path(category['observation_path']).read_bytes()
    assert witness.sha(body) == category['observation_sha256']
    receipt = json.loads(body)
    assert category['status'] == 'PASS' and receipt['positive_marker_proof'] is True
    assert receipt['setup_coverage_credit'] is False and receipt['transaction_count'] == 1
    assert len(writes) == len(membership) == 1
    assert [command[0] for command in commands].count('execute') == 1
    assert [command[0] for command in commands].count('verify') == 1
    assert receipt['baseline_before'] == receipt['baseline_after']
    assert receipt['marker']['properties'] == {'Time': 0.0, 'Label': 'R89_MARKER'}
    assert receipt['budget']['dispatcher_packets'] > 0
    assert receipt['budget']['native_calls'] == len(task.calls)


@pytest.mark.parametrize('fault', ['wrong-owner', 'wrong-class', 'empty', 'bound', 'record', 'mode'])
def test_marker_transport_blocker_stops_without_value_read_or_second_import(tmp_path, workflow, monkeypatch, fault):
    from tests.destructive import test_query_modern_markers as witness
    runtime, task, commands, writes, membership = marker_runtime(tmp_path, workflow, monkeypatch, fault)
    with pytest.raises(AssertionError):
        witness.test_imported_modern_marker_has_canonical_identity_and_typed_values(runtime, monkeypatch)
    category, = runtime.category_results
    body = Path(category['observation_path']).read_bytes()
    assert witness.sha(body) == category['observation_sha256']
    receipt = json.loads(body)
    assert category['status'] == 'FAIL' and receipt['positive_marker_proof'] is False
    assert receipt['business_effect_verified'] is False and receipt['transaction_count'] == 1
    assert receipt['observation_blocker']['native_absence_proven'] is False
    assert receipt['observation_blocker']['retry_performed'] is False
    assert len(writes) == 1 and len(membership) == (0 if fault == 'mode' else 1)
    assert [command[0] for command in commands].count('execute') == 1
    assert [command[0] for command in commands].count('verify') == 1
    assert not any('@Time' in (options or {}).get('return', []) for uri, _, options in task.calls)
    assert 'marker' not in receipt


@pytest.mark.parametrize('version', ['2023.1', '2024.1', '2025.1'])
def test_modern_marker_candidate_uses_matching_wobject_and_list_definitions(workflow, version):
    from tests.destructive.test_query_modern_markers import definition_evidence
    evidence = definition_evidence(version)
    assert evidence['version'] == version and evidence['native_transport_proven'] is False
    assert evidence['marker']['source_member'] == 'wwiseobject_marker.html'


def test_extracted_riff_helpers_keep_accepted_concrete_bytes():
    # SHA-256 values evaluated with the original, byte-identical17ccde20 helper
    # bodies. This narrow extraction check does not rerun Tone acceptance.
    from tests.support.riff_wave import _tone_wav_bytes, _tone_marker_chunks
    from tests.unit.test_host_ui_debug_business_adapter import _tone_wav_bytes as retained_name
    from hashlib import sha256
    assert retained_name is _tone_wav_bytes
    fixtures = [
        (_tone_wav_bytes(), 'aad9bd98948ae3da32bfc9064b922cf586122a966a256373126f389d32d4ae7f'),
        (_tone_wav_bytes(floating=True), 'dd1f0e1bf4f4d1bca52af2c98568c6cb28561c6618819d802a237102ff7f3225'),
        (_tone_wav_bytes(extra=_tone_marker_chunks([(91, 0, b'A\0'), (13, 2, b'C'), (42, 0, b'B\0')])),
            '458542bbe3f676c5d6b71558a3c657fba26e36b895a450ecadd3032ff318f9cb'),
        (_tone_wav_bytes(channels=1, rate=8000, samples=[0] * 800,
            extra=_tone_marker_chunks([(91, 0, b'R89_MARKER\0')])),
            '1a25124ce4894e408a39da858cc72762d3cd26d01620cc16e954e58cb82b19c8'),
    ]
    assert [sha256(body).hexdigest() for body, _ in fixtures] == [expected for _, expected in fixtures]
