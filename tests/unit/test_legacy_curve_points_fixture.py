"""2021 Curve capability collector reaches the existing durable final writer."""
import copy
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from tests.unit.test_query_legacy_curve_points import curve_task, CURVE, POINTS
from tests.unit.test_workflow_source_guard import workflow
from tests.destructive.support import exact_real_evidence, sandbox_fixture


def exercise_collector(tmp_path, workflow, monkeypatch, fault=None):
    from tests.destructive import test_query_legacy_curve_points as witness
    source = tmp_path / 'source'; shutil.copytree(witness.REPO / 'tests/_org/2021.1', source)
    owned = tmp_path / 'owned'; project_root = owned / 'project'; shutil.copytree(source, project_root)
    source_project = source / 'SampleProject.wproj'; project = project_root / 'SampleProject.wproj'
    # The real workflow's 2021 branch is a copy-only prelaunch, with no normalizer.
    source_hash = sandbox_fixture.hash_project(source)
    metadata = sandbox_fixture.SandboxMetadata(str(source_project), str(source), str(project_root),
        str(project), '2021.1', 0, source_hash, sandbox_fixture.hash_project(project_root),
        source_project.stat().st_mtime, process_cleanup_result='cleaned', process_cleanup_details={'residual_processes': []})
    metadata.get_info_version = dict(zip(('year','major','minor','build'), (2021,1,14,8108)))
    sandbox = sandbox_fixture.SandboxProject(source_project, source, owned, project_root, project, metadata)
    backend = tmp_path / 'backend'; backend.mkdir(); task = curve_task(backend)
    task.info['version'].update(metadata.get_info_version)
    task.project['filePath'] = str(project)
    if fault == 'missing': task.row.pop('points')
    elif fault == 'null': task.row['points'] = None
    elif fault == 'wrong-shape': task.row['points'][0]['shape'] = 'unrecognized'
    elif fault == 'wrong-value': task.row['points'][0]['y'] = 123
    elif fault == 'float32': task.row['points'][0]['y'] = -5.670529842376709
    native = task.call
    def call(uri, args=None, options=None):
        if fault == 'rejection' and uri.endswith('object.get') and 'points' in (options or {}).get('return', []):
            task.calls.append((uri, copy.deepcopy(args), copy.deepcopy(options)))
            raise RuntimeError('selected 2021 points accessor rejected')
        return native(uri, args, options)
    task.call = call
    packets = owned / 'packets'; packets.mkdir()
    task.env.update(WWISE_EVIDENCE_DIR=str(packets))
    def forbidden(*args, **kwargs): raise AssertionError('Fake collector must not create a socket')
    monkeypatch.setattr(workflow.waapi_gateway, 'default_client_factory', forbidden)
    execute = workflow.waapi_gateway.execute_gateway
    def injected(argv, **kwargs): return execute(argv, client_factory=lambda _: task, **kwargs)
    monkeypatch.setattr(workflow.waapi_gateway, 'execute_gateway', injected)
    runtime = workflow._WorkflowSandboxRuntime('2021.1', sandbox,
        SimpleNamespace(host='127.0.0.1',port=31337,waapi_url='ws://127.0.0.1:31337/waapi'),
        owned / 'state', task.env, workflow.exact_git_candidate(workflow.REPO_ROOT), [])
    lock = sandbox_fixture.LiveSandboxLock(tmp_path / 'locks'); lock.__enter__()
    item = SimpleNamespace(path=witness.__file__, nodeid='tests/destructive/test_query_legacy_curve_points.py::test_exact_legacy_curve_points_capability',
        _waapi_phase_reports={'setup':'passed'})
    error = None
    try: witness.test_exact_legacy_curve_points_capability(runtime, monkeypatch)
    except AssertionError as exc: error = exc
    item._waapi_phase_reports['call'] = 'failed' if error else 'passed'
    target = tmp_path / 'category.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(target))
    monkeypatch.setattr(sandbox_fixture, 'KEEP_ON_FAILURE_ROOT', tmp_path / 'quarantine')
    final_error = exact_real_evidence.finalize_exact_real_evidence(repo_root=workflow.REPO_ROOT,
        candidate=runtime.candidate,version='2021.1',request=SimpleNamespace(session=SimpleNamespace(items=[item])),
        module_file=Path(witness.__file__),started_at_unix_ns=1,active_error=error,deferred_error=None,
        sandbox=sandbox,lock=lock,state_dir=runtime.state_dir,host={'is_command_line':True,'version':'2021.1'},
        categories=runtime.category_results,source={'hash_before':source_hash.digest,'hash_after':sandbox_fixture.hash_project(source).digest})
    assert final_error is None
    final = [json.loads(line) for line in target.read_text().splitlines()][-1]
    category, = final['categories']; receipt = json.loads(Path(category['observation_path']).read_text())
    return task, receipt, final, error


def test_legacy_curve_collector_reaches_final_writer_with_independent_source_xy(tmp_path, workflow, monkeypatch):
    task, receipt, final, error = exercise_collector(tmp_path, workflow, monkeypatch, 'float32')
    assert error is None and final['invocation']['outcome'] == 'PASS'
    assert final['residual_state']['sandbox'] == 'deleted'
    assert receipt['ordered_source_xy_verified'] is True and receipt['transaction_count'] == 0
    assert receipt['source_oracle']['xy'] == [[0.0,-5.67053],[1.0,0.0]]
    assert receipt['source_oracle']['stored_flags'] == ['21','53']
    native_points = copy.deepcopy(POINTS); native_points[0]['y'] = -5.670529842376709
    assert receipt['public_curve']['curve_points'] == native_points
    assert receipt['public_curve']['curve_points'][0]['y'] != receipt['source_oracle']['xy'][0][1]
    assert receipt['source_before'] == receipt['source_after']
    assert receipt['invocation_count'] == 1 and receipt['dispatch_count'] == 1
    assert len([call for call in task.calls if call[0].endswith('object.get')]) == 1


@pytest.mark.parametrize('fault', ['missing','null','rejection','wrong-shape','wrong-value'])
def test_legacy_curve_collector_retains_nonproof_and_original_packet_without_retry(tmp_path, workflow, monkeypatch, fault):
    task, receipt, final, error = exercise_collector(tmp_path, workflow, monkeypatch, fault)
    assert isinstance(error, AssertionError) and final['invocation']['outcome'] == 'FAIL'
    assert final['residual_state']['sandbox'] == 'quarantined'
    assert receipt['ordered_source_xy_verified'] is False and receipt['business_effect_verified'] is False
    assert receipt['native_absence_proven'] is False and receipt['transaction_count'] == 0
    assert receipt['invocation_count'] == receipt['dispatch_count'] == 1
    assert receipt['source_before'] == receipt['source_after']
    assert len([call for call in task.calls if call[0].endswith('object.get')]) == 1
    packet_ref, = receipt['native_packets']; packet_path = Path(packet_ref['path'])
    from tests.destructive.support.source_copy_fixture import sha
    raw = packet_path.read_bytes(); assert sha(raw) == packet_ref['sha256'] and len(raw) == packet_ref['bytes']
    packet = json.loads(raw)
    if fault == 'rejection':
        assert packet['ok'] is False and 'selected 2021 points accessor rejected' in packet['message']
    elif fault == 'wrong-shape':
        assert packet['result']['return'][0]['points'][0]['shape'] == 'unrecognized'
        assert receipt['payload']['error_code'] == 'RELATED_QUERY_CURVE_POINTS'
    else:
        native_row, = packet['result']['return']
        if fault == 'missing': assert 'points' not in native_row
        elif fault == 'null': assert native_row['points'] is None
        else: assert native_row['points'][0]['y'] == 123
