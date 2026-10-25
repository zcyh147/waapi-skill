"""Exercise the native observer's exact public read path without starting Wwise."""
from types import SimpleNamespace

import pytest

from tests.support.playlist_reference_observation import collect_playlist_slot_reference_metadata
from tests.unit import test_metadata_discovery_gateway as public


@pytest.mark.parametrize("has_flag", [True, False])
def test_playlist_observer_preserves_disclosed_restrictions(tmp_path, has_flag):
    responses = public._metadata_responses(tmp_path, version="2025.1", names=("PlaylistObject",))
    responses[public.GET_TYPES_URI] = {
        "return": [{"classId": 5636096, "name": "PlaylistSlot", "type": "WObject"}]
    }
    responses[public.GET_PROPERTY_INFO_URI] = {
        "name": "PlaylistObject", "type": "", "default": None,
        "restriction": {
            "type": "reference",
            "restrictions": [{"type": ["Sound", "RandomSequenceContainer", "SwitchContainer", "BlendContainer"]},
                             "notNull", *(["mustChildOf"] if has_flag else [])],
        },
    }
    client = public.FakeClient(responses)
    env = public._gateway_env(tmp_path, version="2025.1")
    code, payload = public.waapi_gateway.execute_gateway(
        ["config-set", "--project-modification-policy", "read_only"], env=env,
    )
    assert code == 0, payload
    runtime = SimpleNamespace(candidate="controlled-program-only", version="2025.1",
        state_dir=tmp_path / "observations", category_results=[], raw_gateway=lambda argv:
        public.waapi_gateway.execute_gateway(argv, env=env, client_factory=lambda _: client))
    if has_flag:
        collect_playlist_slot_reference_metadata(runtime)
        assert runtime.category_results[0]["status"] == "PASS"
    else:
        with pytest.raises(AssertionError):
            collect_playlist_slot_reference_metadata(runtime)
        assert runtime.category_results[0]["status"] == "FAIL"
    assert runtime.category_results[0]["business_effect_verified"] is False
    assert (tmp_path / "observations" / "playlist-reference-metadata.json").is_file()


@pytest.mark.parametrize('fault', ['none', 'missing-independent-created'])
def test_new_playlist_append_collector_persists_independent_outcome_with_real_gateway(tmp_path, monkeypatch, fault):
    import hashlib
    import importlib
    import json
    from pathlib import Path
    from tests.unit.test_owned_named_list_stages_gateway import playlist_creation_task
    monkeypatch.setenv('WWISE_LIVE', '1')
    monkeypatch.setenv('WWISE_DESTRUCTIVE', '1')
    collector = importlib.import_module('tests.destructive.test_playlist_reference_metadata')
    owner = '{8C0FD1AD-E45D-408D-9BF3-874970CCC123}'
    target = '{DB017C8E-EC99-415B-93CF-F7A6136D1AC2}'
    first = '{7571D6B0-D614-40B5-B02D-0012FE3743A7}'
    peer = '{6298C41E-F7C6-40B6-BFFE-E0B02EE7DC72}'
    new = '{77777777-7777-7777-7777-777777777777}'
    task = playlist_creation_task(tmp_path, fixture_ids=(owner, target, first, peer, new))
    original = task.call
    independent_phase = False
    def call(uri, args=None, options=None):
        if (fault == 'missing-independent-created' and independent_phase and uri.endswith('object.get')
                and (args == {'from': {'id': [new]}} or args.get('waql', '').startswith(f'from object "{new}" take '))):
            task.calls.append((uri, args, options))
            return {'return': []}
        return original(uri, args, options)
    task.call = call
    def raw(argv):
        nonlocal independent_phase
        result = task.run(*argv)
        if argv[0] == 'verify' and result[0] == 0:
            independent_phase = True
        return result
    runtime = SimpleNamespace(version='2025.1', candidate='program-only', state_dir=tmp_path / 'state',
        sandbox=SimpleNamespace(metadata=SimpleNamespace(get_info_version=dict(year=2025, major=1, minor=7, build=9143))),
        category_results=[], raw_gateway=raw)
    from tests.destructive.support import sandbox_fixture
    from tests.unit import test_profiler_input_native_fixture as finalizer
    workflow = importlib.import_module('tests.destructive.test_gateway_workflow_transaction_matrix')
    source = tmp_path / 'source'
    source.mkdir()
    source_project = source / 'SampleProject.wproj'
    source_project.write_text('immutable Playlist collector source')
    proof = sandbox_fixture.hash_project(source)
    project_root = task.project_file.parent
    metadata = sandbox_fixture.SandboxMetadata(str(source_project), str(source), str(project_root),
        str(task.project_file), '2025.1', 0, proof, sandbox_fixture.hash_project(project_root),
        source_project.stat().st_mtime, process_cleanup_result='cleaned', process_cleanup_details={'residual_processes': []})
    metadata.get_info_version = dict(year=2025, major=1, minor=7, build=9143)
    runtime.sandbox = sandbox_fixture.SandboxProject(source_project, source, tmp_path, project_root, task.project_file, metadata)
    runtime.candidate = workflow.exact_git_candidate(workflow.REPO_ROOT)
    lock = sandbox_fixture.LiveSandboxLock(tmp_path / 'locks')
    lock.__enter__()
    error = None
    try:
        collector.test_new_playlist_slot_append_preserves_existing_peers(runtime)
    except AssertionError as exc:
        error = exc
    assert (error is not None) == (fault != 'none'), error
    category, = runtime.category_results
    body = Path(category['observation_path']).read_bytes()
    observation = json.loads(body)
    assert category['observation_sha256'] == hashlib.sha256(body).hexdigest()
    assert len(task.writes) == 1
    assert observation['transactions'][0]['verify']['verified'] is True
    assert [row['argv'][0] for row in observation['calls']].count('execute') == 1
    assert [row['argv'][0] for row in observation['calls']].count('verify') == 1
    monkeypatch.setattr(finalizer, 'MODULE', 'tests/destructive/test_playlist_reference_metadata.py::')
    module = SimpleNamespace(__file__=collector.__file__, REPO_ROOT=workflow.REPO_ROOT)
    node = 'test_new_playlist_slot_append_preserves_existing_peers'
    records = finalizer._finish((module, runtime, task, lock, proof), tmp_path, monkeypatch, [(node, error)])
    final = records[-1]
    assert final['invocation']['phase'] == 'final'
    assert final['invocation']['node_outcomes'] == [{'nodeid': 'tests/destructive/test_playlist_reference_metadata.py::' + node,
        'outcome': 'PASS' if error is None else 'FAIL'}]
    assert final['source']['hash_before'] == final['source']['hash_after'] == proof.digest
    assert final['residual_state']['process_cleanup'] == 'cleaned'
    assert final['transactions'][0]['state'] == 'verified'
    final_category, = final['categories']
    assert final_category['observation_sha256'] == hashlib.sha256(body).hexdigest()
    if fault == 'none':
        assert category['status'] == 'PASS' and observation['business_effect_verified'] is True
        assert observation['created']['id'] == new and observation['created']['name'] == ''
        assert observation['created']['class_id'] == 5636096 and observation['created']['owner']['id'] == owner
        assert [row['id'] for row in observation['after_members']] == [first, peer, new]
        assert observation['new_reference']['id'] == target
        assert final['invocation']['outcome'] == final_category['status'] == 'PASS'
        assert final['residual_state']['sandbox'] == 'deleted'
    else:
        assert category['status'] == 'FAIL' and observation['business_effect_verified'] is False
        assert 'error' in observation and 'created' not in observation
        assert final['invocation']['outcome'] == final_category['status'] == 'FAIL'
        assert final['residual_state']['sandbox'] == 'quarantined'
        assert Path(final['residual_state']['quarantine_path']).is_dir()
