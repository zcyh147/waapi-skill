"""Older codec read/metadata observations through Gateway and durable finalizer."""
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


@pytest.mark.parametrize('version,fault', [(version, fault)
    for version in ('2021.1', '2022.1', '2023.1') for fault in (None, 'native-not-found', 'missing-detail')]
    + [('2021.1', 'missing-owner'), ('2021.1', 'retained-wrapper'),
       ('2022.1', 'retained-wrapper'), ('2021.1', 'wrong-owner'),
       ('2022.1', 'malformed-class'), ('2021.1', 'empty-fields')])
def test_older_codec_read_reaches_exact_final_writer(tmp_path, monkeypatch, version, fault):
    monkeypatch.setenv('WWISE_LIVE', '1')
    monkeypatch.setenv('WWISE_DESTRUCTIVE', '1')
    collector = importlib.import_module('tests.destructive.test_older_codec_read_probe')
    workflow = importlib.import_module('tests.destructive.test_gateway_workflow_transaction_matrix')
    committed = workflow.REPO_ROOT / 'tests/_org' / version
    pin = collector.source_identity(committed, version)
    task = OwnedGraphTask(tmp_path, version, 'object.create')
    project = {'id': pin['project_id'], 'name': 'SampleProject', 'type': 'Project',
        'path': '\\', 'filePath': str(task.project_file)}
    task.objects = {
        pin['owner_id']: {'id': pin['owner_id'], 'name': 'Voice', 'type': 'Conversion',
            'classId': 3604496, 'path': pin['owner_path']},
        pin['codec_id']: {'id': pin['codec_id'], 'name': '', 'type': 'ConversionPlugin',
            'classId': 262145, 'pluginName': 'Vorbis', 'path': pin['owner_path'] + '\\[Vorbis:Mac]',
            'owner': {'id': pin['owner_id'], 'name': 'Voice'}},
    }
    wrapper = fault in {'retained-wrapper', 'wrong-owner', 'malformed-class', 'empty-fields'}
    if wrapper:
        # Exact result row retained in both original older native observations.
        task.objects[pin['codec_id']] = {
            'classId': 2818064, 'id': '{6DBA16C0-4F5A-4268-8760-61425C95747B}',
            'name': '', 'owner': {'id': '{E9AAECFC-E18A-40E5-91F8-BFCF00FD8CAA}', 'name': 'Voice'},
            'path': '<Unnamed Conversion plugin>', 'pluginName': '', 'type': 'ConversionPlugin'}
    if fault == 'wrong-owner':
        task.objects[pin['codec_id']]['owner']['id'] = pin['codec_id']
    if fault == 'malformed-class':
        task.objects[pin['codec_id']]['classId'] = '2818064'
    if fault == 'missing-owner':
        task.objects[pin['codec_id']]['owner'] = None
    task.types = [{'name': 'Vorbis', 'type': 'Conversion', 'classId': 262145}]
    task.metadata = {'QualityFactor': {'name': 'QualityFactor', 'type': 'Real32', 'default': 3.0,
        'restriction': {'type': 'range', 'min': -2.0, 'max': 10.0}}}
    if fault == 'empty-fields':
        task.metadata = {}
    original = task.call

    def call(uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri.endswith('getInfo'):
            result = original(uri, args, options)
            result['version'].update(zip(('year', 'major', 'minor', 'build'), pin['build']))
            result['version']['displayName'] = 'v' + '.'.join(map(str, pin['build']))
            return result
        if uri.endswith('getProjectInfo'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'id': pin['project_id'], 'name': 'SampleProject', 'path': str(task.project_file)}
        if uri.endswith('object.get'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            query = args.get('waql', '')
            if query == 'from type Project take 1':
                rows = [project]
            else:
                identities = args.get('from', {}).get('id')
                if identities is None:
                    assert query.startswith('from object "') and ' select ' not in query, query
                    identities = [query.split('"')[1]]
                if fault == 'native-not-found' and pin['codec_id'] in identities:
                    raise WaapiRequestFailed('ak.wwise.query.invalid_query', {'message': 'Object not found'})
                rows = [project if identity == pin['project_id'] else task.objects[identity]
                    for identity in identities if identity == pin['project_id'] or identity in task.objects]
            return {'return': task.project_rows(rows, options)}
        if uri.endswith('getPropertyInfo') and fault == 'missing-detail':
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'name': 'QualityFactor', 'type': 42}
        assert uri in {'ak.wwise.core.object.getTypes', 'ak.wwise.core.object.getPropertyAndReferenceNames',
            'ak.wwise.core.object.getPropertyInfo'}, uri
        return original(uri, args, options)

    task.call = call
    source = tmp_path / 'source'
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
        sandbox=sandbox, state_dir=tmp_path / 'state', category_results=[], raw_gateway=lambda argv: task.run(*argv))
    error = None
    try:
        collector.collect_older_codec_read(runtime)
    except pytest.skip.Exception as exc:
        error = exc
    success = fault in (None, 'retained-wrapper')
    assert (error is None) is success
    category, = runtime.category_results
    body = Path(category['observation_path']).read_bytes()
    receipt = json.loads(body)
    assert receipt['read_metadata_complete'] is success
    assert receipt['project_mutation_count'] == 0 and receipt['transactions'] == []
    assert receipt['business_effect_verified'] is False and receipt['platform_association_proven'] is False
    assert category['observation_sha256'] == hashlib.sha256(body).hexdigest()
    assert receipt['source']['codec_id'] == '{6DBA16C0-4F5A-4268-8760-61425C95747B}'
    assert len(receipt['calls']) <= receipt['limits']['public_calls']
    assert not any('--advanced-waql' in row['argv'] for row in receipt['calls'])
    if fault == 'native-not-found':
        assert receipt['access_outcome'] == 'native_read_unresolved' and 'field_list' not in receipt
        assert receipt['codec_result']['call']['waapi_error_uri'] == 'ak.wwise.query.invalid_query'
    elif fault in ('missing-owner', 'wrong-owner', 'malformed-class'):
        assert receipt['access_outcome'] == 'identity_facts_unresolved' and 'field_list' not in receipt
        if fault == 'missing-owner':
            assert receipt['native_record']['result']['return'][0]['owner'] is None
    elif fault == 'empty-fields':
        assert receipt['access_outcome'] == 'quality_field_not_disclosed_within_bound'
        assert receipt['field_list']['fields'] == [] and 'detail_result' not in receipt
    elif fault == 'missing-detail':
        assert receipt['access_outcome'] == 'metadata_unresolved'
        assert receipt['field_list']['fields'][0]['name'] == 'QualityFactor'
        assert 'detail_result' in receipt
    else:
        assert receipt['access_outcome'] == 'read_and_metadata_observed'
        assert receipt['detail_result']['agent_result']['metadata']['name'] == 'QualityFactor'
    if wrapper and success:
        assert receipt['identity_representation'] == 'pinned_older_generic_wrapper'
        assert receipt['concrete_codec_class_id'] is None
        assert receipt['native_record']['result']['return'][0] == task.objects[pin['codec_id']]
        assert receipt['wrapper_source']['native_record_sha256'] in {
            '3a054be2b3f126ebf71811c7a06fe93015a8e160faaf16795ec7ed603d52a27f',
            'd91831514fcf3b0c6c9a9ca4402f71a39f7fb10fbe29c65442fd856dec90cee5'}
    assert all(uri in {'ak.wwise.core.getInfo', 'ak.wwise.core.getProjectInfo', 'ak.wwise.core.object.get',
        'ak.wwise.core.object.getTypes', 'ak.wwise.core.object.getPropertyAndReferenceNames',
        'ak.wwise.core.object.getPropertyInfo'} for uri, _, _ in task.calls)
    assert sandbox_fixture.hash_project(source) == proof and (source / 'SampleProject.wproj').stat().st_mtime_ns == mtime
    lock = sandbox_fixture.LiveSandboxLock(tmp_path / 'locks')
    lock.__enter__()
    evidence = tmp_path / 'category.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(evidence))
    monkeypatch.setattr(sandbox_fixture, 'KEEP_ON_FAILURE_ROOT', tmp_path / 'retained')
    node = 'tests/destructive/test_older_codec_read_probe.py::test_' + version[:4] + '_codec_read_metadata'
    item = SimpleNamespace(path=collector.__file__, nodeid=node,
        _waapi_phase_reports={'setup': 'passed', 'call': 'skipped' if error else 'passed'})
    final_error = exact_real_evidence.finalize_exact_real_evidence(repo_root=workflow.REPO_ROOT,
        candidate=runtime.candidate, version=version, request=SimpleNamespace(session=SimpleNamespace(items=[item])),
        module_file=Path(collector.__file__), started_at_unix_ns=1, active_error=error, deferred_error=None,
        sandbox=sandbox, lock=lock, state_dir=runtime.state_dir, host={'version': version, 'is_command_line': True},
        categories=runtime.category_results, source={'hash_before': proof.digest,
            'hash_after': sandbox_fixture.hash_project(source).digest, 'project_mtime_unchanged': True})
    assert final_error is None
    records = [json.loads(line) for line in evidence.read_text().splitlines()]
    final = records[-1]
    assert final['transactions'] == [] and final['source']['hash_before'] == final['source']['hash_after']
    assert final['categories'][0]['observation_sha256'] == hashlib.sha256(body).hexdigest()
    assert final['residual_state']['process_cleanup'] == 'cleaned'
    if success:
        assert [row['invocation']['outcome'] for row in records] == ['PENDING', 'PASS']
        assert final['residual_state']['sandbox'] == 'deleted'
    else:
        assert [row['invocation']['outcome'] for row in records] == ['SKIP']
        assert final['categories'][0]['status'] == 'blocked'
        assert final['residual_state']['sandbox'] == 'quarantined'
        assert Path(final['residual_state']['quarantine_path']).is_dir()
