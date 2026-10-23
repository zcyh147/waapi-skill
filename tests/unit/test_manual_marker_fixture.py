"""Owned manual Marker collector with real Gateway and existing-media fake transport."""
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from tests.unit.test_manual_marker_gateway import marker_task, FIRST, SECOND
from tests.unit.test_workflow_source_guard import workflow


def runtime_with_existing_source(tmp_path, workflow, monkeypatch, fault=None):
    from tests.destructive import test_query_manual_markers as witness
    source = tmp_path / 'source'; shutil.copytree(witness.REPO / 'tests/_org/2025.1', source)
    owned = tmp_path / 'owned'; sandbox = owned / 'project'; shutil.copytree(source, sandbox)
    prelaunch_io = owned / 'prelaunch-io'; prelaunch_io.mkdir()
    prepared = workflow.normalize_project_copy(sandbox / 'SampleProject.wproj', io_root=prelaunch_io, owned_root=owned,
        request=workflow.ProjectPrelaunchRequest(scenario_id='gateway-workflow-transaction-matrix',
            auro_isolation_profile=workflow.WWISE_2025_SOUNDBANK_AURO_PROFILE))
    assert prepared.auro_soundbank_isolation is not None
    (owned / 'prelaunch-helper-report.json').write_text(json.dumps(prepared.as_dict(), indent=2))
    transport = tmp_path / 'transport'; transport.mkdir(); task = marker_task(transport, fault=fault)
    task.project_file = sandbox / 'SampleProject.wproj'
    sound_path = '\\' + '\\'.join(witness.SOUND_SEGMENTS)
    task.objects[SECOND].update(name='Rifle_Close', path=sound_path)
    task.objects[FIRST].update(name='audit_outside', path=sound_path + r'\audit_outside',
        originalFilePath=str(sandbox / witness.MEDIA_RELATIVE))
    original = task.call
    if fault == 'nonempty-baseline': task.objects[FIRST]['@Markers'] = [{'id': SECOND}]
    def native(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('getInfo'):
            result['version'].update(dict(zip(('year','major','minor','build'), witness.BUILDS['2025.1'])))
        return result
    task.call = native
    packets = owned / 'packets'; packets.mkdir()
    runtime = SimpleNamespace(version='2025.1', candidate='program-only', category_results=[], state_dir=owned / 'state',
        sandbox=SimpleNamespace(source_root=source, sandbox_path=sandbox, sandbox_project=task.project_file,
            metadata=SimpleNamespace(get_info_version=dict(zip(('year','major','minor','build'), witness.BUILDS['2025.1'])))),
        env=task.env, port=31337, lifecycle=SimpleNamespace(host='127.0.0.1', waapi_url='ws://127.0.0.1:31337/waapi'))
    task.env.update(WWISE_EVIDENCE_DIR=str(packets), WAAPI_SKILL_STATE_DIR=str(runtime.state_dir))
    def forbidden(*args, **kwargs): raise AssertionError('Fake collector cannot create a socket or real client')
    monkeypatch.setattr(workflow.waapi_gateway, 'default_client_factory', forbidden)
    execute = workflow.waapi_gateway.execute_gateway
    def injected(argv, **kwargs): return execute(argv, client_factory=lambda _: task, **kwargs)
    monkeypatch.setattr(workflow.waapi_gateway, 'execute_gateway', injected)
    commands = []
    def raw(argv):
        commands.append(list(argv))
        code, result = workflow.waapi_gateway.execute_gateway(['--timeout','30','--state-dir',str(runtime.state_dir),*argv], env=runtime.env)
        if fault == 'media-change' and argv[0] == 'verify' and code == 0:
            path = sandbox / witness.MEDIA_RELATIVE
            path.write_bytes(path.read_bytes() + b'changed after verified setup')
        return code, result
    runtime.raw_gateway = raw
    return runtime, task, commands


def test_manual_marker_collector_runs_one_explicit_transaction_on_existing_media(tmp_path, workflow, monkeypatch):
    from tests.destructive import test_query_manual_markers as witness
    runtime, task, commands = runtime_with_existing_source(tmp_path, workflow, monkeypatch)
    witness.test_manual_marker_keeps_exact_source_and_typed_member_scope(runtime, monkeypatch)
    category, = runtime.category_results
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert category['status'] == 'PASS' and receipt['business_effect_verified'] is True
    assert receipt['setup_coverage_credit'] is False and receipt['transaction_count'] == 1
    assert receipt['baseline_before'] == receipt['baseline_after']
    assert receipt['marker']['properties'] == {'Time': 0.0, 'Label': 'R90_MARKER'}
    assert receipt['retained_edit_preparation']['ok'] is True and receipt['retained_edit_executed'] is False
    assert [cmd[0] for cmd in commands].count('draft-bind-object') == 2
    assert [cmd[0] for cmd in commands].count('preview-from-draft') == 1
    assert len(task.writes) == 1 and [cmd[0] for cmd in commands].count('verify') == 1
    assert not any('audio.import' in uri or 'generateTone' in uri for uri, _, _ in task.calls)
    assert receipt['budget']['native_calls'] == len(task.calls)


@pytest.mark.parametrize('fault', ['owner', 'media-change', 'nonempty-baseline'])
def test_manual_marker_collector_retains_failed_effect_or_prerequisite_without_retry(tmp_path, workflow, monkeypatch, fault):
    from tests.destructive import test_query_manual_markers as witness
    runtime, task, commands = runtime_with_existing_source(tmp_path, workflow, monkeypatch, fault)
    with pytest.raises(AssertionError):
        witness.test_manual_marker_keeps_exact_source_and_typed_member_scope(runtime, monkeypatch)
    category, = runtime.category_results
    raw = Path(category['observation_path']).read_bytes(); receipt = json.loads(raw)
    assert witness.sha(raw) == category['observation_sha256']
    assert category['status'] == 'FAIL' and receipt['business_effect_verified'] is False
    assert receipt['observation_blocker']['native_absence_proven'] is False
    count = 0 if fault == 'nonempty-baseline' else 1
    assert len(task.writes) == receipt['transaction_count'] == count
    assert [cmd[0] for cmd in commands].count('execute') == count
    if fault == 'media-change': assert receipt['setup_transaction']['verify']['verification']['business_state_verified'] is True
    elif fault == 'owner': assert commands[-1][0] == 'verify'
    else: assert not any(cmd[0] == 'draft-start' for cmd in commands)
