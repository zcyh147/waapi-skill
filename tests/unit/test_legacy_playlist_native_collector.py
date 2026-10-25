"""Legacy native collector reaches the persisted final writer with fake Wwise."""
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask


@pytest.mark.parametrize('fault', ['none', 'unrelated-read', 'missing-target-proof', 'append-replaces'])
def test_legacy_playlist_native_workflow_persists_completed_phases_and_failures(tmp_path, monkeypatch, fault):
    monkeypatch.setenv('WWISE_LIVE', '1')
    monkeypatch.setenv('WWISE_DESTRUCTIVE', '1')
    collector = importlib.import_module('tests.destructive.test_legacy_playlist_reference_workflow')
    workflow = importlib.import_module('tests.destructive.test_gateway_workflow_transaction_matrix')
    from tests.destructive.support import sandbox_fixture
    from tests.unit import test_profiler_input_native_fixture as finalizer
    from tests.unit.test_debug_read_gateway import WaapiRequestFailed

    owner, up, loop = collector.OWNER, collector.UP, collector.LOOP
    task = OwnedGraphTask(tmp_path, '2023.1', 'object.set')
    owner_path = r'\Actor-Mixer Hierarchy\Minigun\Minigun\Barrel\Minigun_Barrel_Start'
    task.types = [{'classId': 589840, 'name': 'RandomSequenceContainer', 'type': 'WObject'},
        {'classId': 65552, 'name': 'Sound', 'type': 'WObject'}]
    task.objects = {
        owner: {'id': owner, 'name': 'Minigun_Barrel_Start', 'type': 'RandomSequenceContainer', 'classId': 589840,
            'path': owner_path, 'parent': {'id': '{971E5493-DD6B-4E7E-A321-E37AD6F9D3E4}'},
            'notes': 'Keep owner', '@RandomOrSequence': 0, '@Playlist': [{'id': up}, {'id': loop}]},
        up: {'id': up, 'name': 'MnGn_Barrel_Up', 'type': 'Sound', 'classId': 65552,
            'path': owner_path + r'\MnGn_Barrel_Up', 'parent': {'id': owner}, 'notes': 'Keep Up'},
        loop: {'id': loop, 'name': 'MnGn_Barrel_Loop', 'type': 'Sound', 'classId': 65552,
            'path': owner_path + r'\MnGn_Barrel_Loop', 'parent': {'id': owner}, 'owner': None, 'notes': 'Keep Loop'},
    }
    original, verified_count = task.call, 0
    def call(uri, args=None, options=None):
        if uri.endswith('getInfo'):
            result = original(uri, args, options)
            result['version'].update(minor=19, build=8928, displayName='v2023.1.19.8928')
            return result
        if uri.endswith('getProjectInfo'):
            return {'id': collector.PROJECT, 'name': 'SampleProject', 'path': str(task.project_file)}
        if uri.endswith('object.set'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            item, = args['objects']
            mode = item.get('listMode', args.get('listMode', 'append'))
            values = item['@Playlist']
            prefix = task.objects[owner]['@Playlist'] if mode == 'append' and fault != 'append-replaces' else []
            task.objects[owner]['@Playlist'] = [*deepcopy(prefix), *({'id': value} for value in values)]
            return {'objects': [{'id': owner, 'name': 'Minigun_Barrel_Start'}]}
        query = (args or {}).get('waql', '')
        if uri.endswith('object.get') and query.startswith('from object "'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            identity = query.split('"')[1]
            if 'select @Playlist' in query:
                if verified_count == 2 and fault == 'unrelated-read':
                    raise WaapiRequestFailed('ak.wwise.query.invalid_query', {'message': 'Unrelated native query failure'})
                return {'return': task.project_rows([task.objects[row['id']] for row in task.objects[owner]['@Playlist']], options)}
            rows = [task.objects[identity]] if identity in task.objects else []
            if verified_count == 2 and fault == 'missing-target-proof' and identity == up:
                rows = []
            return {'return': task.project_rows(rows, options)}
        return original(uri, args, options)
    task.call = call
    def raw(argv):
        nonlocal verified_count
        result = task.run(*argv)
        if argv[0] == 'verify':
            verified_count += 1
        return result

    source = tmp_path / 'source'
    source.mkdir()
    committed = workflow.REPO_ROOT / 'tests' / '_org' / '2023.1'
    source_project = source / 'SampleProject.wproj'
    source_project.write_bytes((committed / 'SampleProject.wproj').read_bytes())
    source_wwu = source / collector.SOURCE_MEMBER
    source_wwu.parent.mkdir(parents=True)
    source_wwu.write_bytes((committed / collector.SOURCE_MEMBER).read_bytes())
    proof = sandbox_fixture.hash_project(source)
    metadata = sandbox_fixture.SandboxMetadata(str(source_project), str(source), str(task.project_file.parent),
        str(task.project_file), '2023.1', 0, proof, sandbox_fixture.hash_project(task.project_file.parent),
        source_project.stat().st_mtime, process_cleanup_result='cleaned', process_cleanup_details={'residual_processes': []})
    metadata.get_info_version = dict(year=2023, major=1, minor=19, build=8928)
    sandbox = sandbox_fixture.SandboxProject(source_project, source, tmp_path, task.project_file.parent, task.project_file, metadata)
    runtime = SimpleNamespace(version='2023.1', candidate=workflow.exact_git_candidate(workflow.REPO_ROOT),
        sandbox=sandbox, state_dir=tmp_path / 'state', category_results=[], raw_gateway=raw)
    lock = sandbox_fixture.LiveSandboxLock(tmp_path / 'locks'); lock.__enter__()
    node = 'test_legacy_playlist_replace_append_clear_preserves_hierarchy'
    error = None
    try:
        getattr(collector, node)(runtime)
    except AssertionError as exc:
        error = exc
    assert (error is None) == (fault == 'none'), error
    category, = runtime.category_results
    body = Path(category['observation_path']).read_bytes()
    observation = json.loads(body)
    assert category['observation_sha256'] == hashlib.sha256(body).hexdigest()
    monkeypatch.setattr(finalizer, 'MODULE', 'tests/destructive/test_legacy_playlist_reference_workflow.py::')
    module = SimpleNamespace(__file__=collector.__file__, REPO_ROOT=workflow.REPO_ROOT)
    final = finalizer._finish((module, runtime, task, lock, proof), tmp_path, monkeypatch, [(node, error)])[-1]
    expected_count = 3 if fault == 'none' else 2
    assert len(final['transactions']) == expected_count
    assert sum(uri.endswith('object.set') for uri, _, _ in task.calls) == expected_count
    assert final['categories'][0]['observation_sha256'] == hashlib.sha256(body).hexdigest()
    assert final['source']['hash_before'] == final['source']['hash_after'] == proof.digest
    assert final['residual_state']['process_cleanup'] == 'cleaned'
    assert observation['phases'][0]['business_effect_verified'] is True
    assert observation['phases'][0]['actual_roster'] == [up, loop, loop]
    if fault == 'none':
        assert observation['business_effect_verified'] is True
        assert observation['phases'][1]['actual_roster'] == [up, loop, loop, up]
        assert observation['phases'][2]['actual_roster'] == []
        assert final['invocation']['outcome'] == final['categories'][0]['status'] == 'PASS'
        assert final['residual_state']['sandbox'] == 'deleted'
    else:
        assert observation['business_effect_verified'] is False and observation['phases'][1]['business_effect_verified'] is False
        assert observation['phases'][2]['status'] == 'not_attempted'
        assert final['invocation']['outcome'] == final['categories'][0]['status'] == 'FAIL'
        assert final['residual_state']['sandbox'] == 'quarantined'
        assert Path(final['residual_state']['quarantine_path']).is_dir()
        if fault == 'append-replaces':
            assert observation['phases'][1]['actual_roster'] == [up]
            assert observation['phases'][1]['verify_exit_code'] == 2
