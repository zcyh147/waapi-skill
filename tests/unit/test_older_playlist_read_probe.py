"""Older read collector reaches the actual two-phase writer with fake Wwise."""
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.destructive.support import exact_real_evidence, sandbox_fixture
from tests.unit.test_debug_read_gateway import WaapiRequestFailed
from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask


@pytest.mark.parametrize('version', ['2021.1', '2022.1'])
@pytest.mark.parametrize('fault,outcome', [
    (None, 'matching_membership'), ('empty', 'empty_or_unattributable'),
    ('omitted-identity', 'empty_or_unattributable'), ('wrong-member', 'empty_or_unattributable'),
    ('native-reject', 'native_path_rejected'), ('native-error', 'native_error_unresolved'),
    ('gateway-refused', 'gateway_refused'),
])
def test_older_playlist_probe_finalizes_exact_read_outcome(tmp_path, monkeypatch, version, fault, outcome):
    monkeypatch.setenv('WWISE_LIVE', '1')
    monkeypatch.setenv('WWISE_DESTRUCTIVE', '1')
    collector = importlib.import_module('tests.destructive.test_older_playlist_read_probe')
    workflow = importlib.import_module('tests.destructive.test_gateway_workflow_transaction_matrix')
    pin = collector.source_identity(workflow.REPO_ROOT / 'tests/_org' / version, version)
    task = OwnedGraphTask(tmp_path, version, 'object.create')
    task.types = [{'name': 'RandomSequenceContainer', 'type': 'WObject', 'classId': 589840},
        {'name': 'Sound', 'type': 'WObject', 'classId': 65552}]
    task.objects = {pin['owner']: {'id': pin['owner'], 'name': pin['owner_name'],
        'type': 'RandomSequenceContainer', 'classId': 589840, 'path': pin['owner_path'],
        'parent': {'id': pin['owner_parent']}, '@RandomOrSequence': 0}}
    task.objects.update({row['id']: {**row, 'type': 'Sound', 'classId': 65552,
        'parent': {'id': pin['owner']}} for row in pin['targets']})
    project = {'id': pin['project_id'], 'name': 'SampleProject', 'type': 'Project',
        'path': '\\', 'filePath': str(task.project_file)}
    original = task.call

    def call(uri, args=None, options=None):
        if uri.endswith('getInfo'):
            result = original(uri, args, options)
            result['version'].update(zip(('year', 'major', 'minor', 'build'), pin['build']))
            result['version']['displayName'] = 'v' + '.'.join(map(str, pin['build']))
            return result
        if uri.endswith('getProjectInfo'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'id': pin['project_id'], 'name': 'SampleProject', 'path': str(task.project_file)}
        if uri.endswith('object.get') and (args.get('waql') == 'from type Project take 1' or
                args.get('from', {}).get('id') == [pin['project_id']] or
                args.get('waql', '').startswith('from object "' + pin['project_id'] + '"')):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': task.project_rows([project], options)}
        if uri.endswith('object.get') and 'select @Playlist' in args.get('waql', ''):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args['waql'] == f'from object "{pin["owner"]}" select @Playlist take 32'
            if fault == 'native-reject':
                raise WaapiRequestFailed('ak.wwise.query.invalid_query', {'message': 'Unknown accessor Playlist'})
            if fault == 'native-error':
                raise RuntimeError('Native transport failed during the read; access remains unresolved')
            rows = [task.objects[identity] for identity in pin['roster']]
            if fault == 'empty':
                rows = []
            elif fault == 'omitted-identity':
                rows = [{}]
            elif fault == 'wrong-member':
                rows = [task.objects[pin['owner']]]
            return {'return': task.project_rows(rows, options)}
        if uri.endswith('object.get') and args.get('waql', '').startswith('from object "'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            identity = args['waql'].split('"')[1]
            return {'return': task.project_rows([task.objects[identity]] if identity in task.objects else [], options)}
        assert uri in {'ak.wwise.core.object.get', 'ak.wwise.core.object.getTypes',
            'ak.wwise.core.object.getPropertyAndReferenceNames', 'ak.wwise.core.object.getPropertyInfo'}, uri
        return original(uri, args, options)

    task.call = call
    calls = []

    def raw(argv):
        calls.append(list(argv))
        if fault == 'gateway-refused' and '--advanced-waql' in argv:
            return 2, {'ok': False, 'error_code': 'EXPLICIT_TEST_GATEWAY_REFUSAL', 'agent_result': None}
        return task.run(*argv)

    source = tmp_path / 'source'
    source.mkdir()
    committed = workflow.REPO_ROOT / 'tests/_org' / version
    for relative in ('SampleProject.wproj', collector.MEMBER):
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((committed / relative).read_bytes())
    proof = sandbox_fixture.hash_project(source)
    mtime = (source / 'SampleProject.wproj').stat().st_mtime_ns
    metadata = sandbox_fixture.SandboxMetadata(str(source / 'SampleProject.wproj'), str(source),
        str(task.project_file.parent), str(task.project_file), version, 0, proof,
        sandbox_fixture.hash_project(task.project_file.parent), (source / 'SampleProject.wproj').stat().st_mtime,
        process_cleanup_result='cleaned', process_cleanup_details={'residual_processes': []})
    metadata.get_info_version = dict(zip(('year', 'major', 'minor', 'build'), pin['build']))
    metadata.launch_project_path = str(task.project_file)
    sandbox = sandbox_fixture.SandboxProject(source / 'SampleProject.wproj', source, tmp_path,
        task.project_file.parent, task.project_file, metadata)
    runtime = SimpleNamespace(version=version, candidate=workflow.exact_git_candidate(workflow.REPO_ROOT),
        sandbox=sandbox, state_dir=tmp_path / 'state', category_results=[], raw_gateway=raw)
    error = None
    try:
        collector.collect_older_playlist_read(runtime)
    except pytest.skip.Exception as exc:
        error = exc
    assert (error is None) == (fault is None)
    category, = runtime.category_results
    body = Path(category['observation_path']).read_bytes()
    observation = json.loads(body)
    assert category['observation_sha256'] == hashlib.sha256(body).hexdigest()
    assert observation['access_outcome'] == outcome
    assert observation['membership_verified'] is (fault is None)
    assert observation['business_effect_verified'] is False and observation['project_mutation_count'] == 0
    assert observation['source']['serialized_relationship'] == 'RandomSequenceContainer/Playlist/ItemRef'
    assert observation['documented_playlist'] == []
    assert len(calls) <= observation['limits']['public_calls'] == 12
    assert sum('--advanced-waql' in argv for argv in calls) == 1
    assert all(not any(command in argv for command in ('preview', 'preview-from-draft', 'execute',
        'verify', 'config-set', 'draft-declare-new', 'draft-declare-existing')) for argv in calls)
    assert all(uri in {'ak.wwise.core.getInfo', 'ak.wwise.core.getProjectInfo', 'ak.wwise.core.object.get',
        'ak.wwise.core.object.getTypes', 'ak.wwise.core.object.getPropertyAndReferenceNames',
        'ak.wwise.core.object.getPropertyInfo'} for uri, _, _ in task.calls)
    if fault != 'gateway-refused':
        assert observation['native_record']['api'] == 'ak.wwise.core.object.get'
        if fault == 'omitted-identity':
            assert observation['native_record']['result'] == {'return': [{}]}
        if fault == 'native-reject':
            assert observation['native_record']['waapi_error_uri'] == 'ak.wwise.query.invalid_query'
    assert sandbox_fixture.hash_project(source) == proof
    assert (source / 'SampleProject.wproj').stat().st_mtime_ns == mtime

    # Exercise the original final writer, including its observed quarantine path.
    lock = sandbox_fixture.LiveSandboxLock(tmp_path / 'locks')
    lock.__enter__()
    evidence = tmp_path / 'category.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(evidence))
    monkeypatch.setattr(sandbox_fixture, 'KEEP_ON_FAILURE_ROOT', tmp_path / 'retained')
    node = 'test_' + version[:4] + '_playlist_read_access'
    item = SimpleNamespace(path=collector.__file__, nodeid='tests/destructive/test_older_playlist_read_probe.py::' + node,
        _waapi_phase_reports={'setup': 'passed', 'call': 'skipped' if error else 'passed'})
    result = exact_real_evidence.finalize_exact_real_evidence(repo_root=workflow.REPO_ROOT,
        candidate=runtime.candidate, version=version, request=SimpleNamespace(session=SimpleNamespace(items=[item])),
        module_file=Path(collector.__file__), started_at_unix_ns=1, active_error=error, deferred_error=None,
        sandbox=sandbox, lock=lock, state_dir=runtime.state_dir, host={'version': version, 'is_command_line': True},
        categories=runtime.category_results, source={'hash_before': proof.digest,
            'hash_after': sandbox_fixture.hash_project(source).digest, 'project_mtime_unchanged': True})
    assert result is None
    records = [json.loads(line) for line in evidence.read_text().splitlines()]
    final = records[-1]
    assert final['source']['hash_before'] == final['source']['hash_after'] == proof.digest
    assert final['transactions'] == [] and final['residual_state']['process_cleanup'] == 'cleaned'
    assert final['categories'][0]['observation_sha256'] == hashlib.sha256(body).hexdigest()
    if fault is None:
        assert [row['invocation']['outcome'] for row in records] == ['PENDING', 'PASS']
        assert final['categories'][0]['status'] == 'PASS' and final['residual_state']['sandbox'] == 'deleted'
    else:
        assert [row['invocation']['outcome'] for row in records] == ['SKIP']
        assert final['categories'][0]['status'] == 'blocked' and final['residual_state']['sandbox'] == 'quarantined'
        assert Path(final['residual_state']['quarantine_path']).is_dir()


@pytest.mark.parametrize('version', ['2021.1', '2022.1'])
def test_older_playlist_pin_rejects_source_change(tmp_path, monkeypatch, version):
    monkeypatch.setenv('WWISE_LIVE', '1')
    monkeypatch.setenv('WWISE_DESTRUCTIVE', '1')
    collector = importlib.import_module('tests.destructive.test_older_playlist_read_probe')
    path = tmp_path / collector.MEMBER
    path.parent.mkdir(parents=True)
    path.write_text('<RandomSequenceContainer><Playlist /></RandomSequenceContainer>')
    with pytest.raises(AssertionError, match='Matching source Work Unit changed'):
        collector.source_identity(tmp_path, version)
