"""Condition producer uses the original lifecycle until actual final reports."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from tests.unit.test_authoring_batch_adapter import owned_authoring
from pathlib import Path
from tests.support.exact_evidence_finalization import finalize_reported_node_evidence


def inputs(tmp_path, monkeypatch):
    from tests.destructive.support import category_evidence
    monkeypatch.setattr(category_evidence, 'current_evidence_platform', lambda: 'macos')
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(tmp_path / 'category.jsonl'))
    nodeid = 'tests/destructive/test_condition_visibility_gateway.py::test_show_visibility_does_not_change_native_prerequisite[Self]'
    observation = tmp_path / 'original-observation.json'
    observed = {'observations': [{'after': {'SlewRateUp': 37.0}}]}
    observation.write_text(json.dumps(observed))
    return {'nodeid': nodeid, 'root': tmp_path / 'unused-publisher'}, {
        'repo_root': Path(__file__).parents[2], 'candidate': 'a' * 40,
        'version': '2025.1', 'started_at_unix_ns': 1, 'observation_path': observation}, observed


@pytest.fixture
def condition_owner(owned_authoring, tmp_path, monkeypatch):
    from tests.semantic.support import codex_scenario_lifecycle_v3 as lifecycle
    from wwise_waapi.headless import CleanupReport, HeadlessLifecycle
    from tests.destructive.support import category_evidence
    owner = owned_authoring
    owner.runtime.lifecycle.ready_result['isCommandLine'] = True
    def shutdown(process, sandbox, **kwargs):
        process.process = None
        process.cleanup_report = CleanupReport(launch_pid=1234, wine_prefix=str(process._owned_wine_prefix()), process_exited=True)
        sandbox.metadata.process_cleanup_result = 'cleaned'
        sandbox.metadata.process_cleanup_details = {'residual_processes': []}
    monkeypatch.setattr(lifecycle, 'shutdown_sandboxed_wwise', shutdown)
    monkeypatch.setattr(HeadlessLifecycle, '_process_rows', lambda *_, **__: [(11111, 'unrelated fake pytest process')])
    monkeypatch.setattr(category_evidence, 'current_evidence_platform', lambda: 'macos')
    yield owner


def prepare(owner, tmp_path, monkeypatch, *, item=None):
    from tests.destructive.support import condition_finalization
    monkeypatch.setattr(condition_finalization, 'assert_port_free', lambda *_: None)
    capture, kwargs, observed = inputs(tmp_path, monkeypatch)
    observed['host'] = deepcopy(owner.runtime.lifecycle.ready_result)
    kwargs['observation_path'].write_text(json.dumps(observed))
    item = item or SimpleNamespace(nodeid=capture['nodeid'], _waapi_phase_reports={'setup': 'passed', 'call': 'passed'})
    capture['nodeid'] = item.nodeid
    prepared = condition_finalization.prepare_condition_finalization(
        item=item, owner=owner, status='PASS', reason='', repo_root=kwargs['repo_root'],
        candidate=kwargs['candidate'], version=kwargs['version'], started_at_unix_ns=kwargs['started_at_unix_ns'],
        host=observed['host'], observation_path=kwargs['observation_path'], transactions=[])
    return item, capture, prepared


@pytest.mark.parametrize('late_phase', ['failed', None])
def test_actual_late_or_missing_teardown_retains_original_sandbox_and_withholds_native_pass(condition_owner, tmp_path, monkeypatch, late_phase):
    item, capture, prepared = prepare(condition_owner, tmp_path, monkeypatch)
    assert prepared.final_status == 'PREPARED' and prepared.cleanup_deferred
    assert condition_owner.runtime.sandbox.sandbox_project.exists()
    assert condition_owner._lock_acquired
    if late_phase is not None:
        item._waapi_phase_reports['teardown'] = late_phase
    report = SimpleNamespace(when='teardown', outcome=late_phase or 'passed')
    finalize_reported_node_evidence(item, report)
    assert condition_owner.runtime.sandbox.sandbox_project.exists()
    assert condition_owner.runtime.owned_root.exists()
    assert not condition_owner._lock_acquired
    assert not capture['root'].exists()
    rows = [json.loads(line) for line in (tmp_path / 'category.jsonl').read_text().splitlines()] if (tmp_path / 'category.jsonl').exists() else []
    assert all(row['invocation']['outcome'] != 'PASS' for row in rows)
    with pytest.raises(Exception, match='prepared'):
        condition_owner.release_prepared_cleanup(post_teardown_check=lambda _: None)


def test_successful_final_reports_release_and_publish_once_under_original_lock(condition_owner, tmp_path, monkeypatch):
    item, _, _ = prepare(condition_owner, tmp_path, monkeypatch)
    item._waapi_phase_reports['teardown'] = 'passed'
    report = SimpleNamespace(when='teardown', outcome='passed')
    finalize_reported_node_evidence(item, report)
    assert report.outcome == 'passed', getattr(report, 'longrepr', None)
    assert not condition_owner._lock_acquired
    assert not condition_owner.runtime.sandbox.sandbox_path.exists()
    first = (tmp_path / 'category.jsonl').read_bytes()
    finalize_reported_node_evidence(item, report)
    assert (tmp_path / 'category.jsonl').read_bytes() == first



def test_publication_failure_withholds_acceptance_without_rewriting_truthful_cleanup(condition_owner, tmp_path, monkeypatch):
    from tests.destructive.support import condition_finalization
    def broken(**kwargs):
        raise OSError('publication failed after native cleanup')
    monkeypatch.setattr(condition_finalization, 'append_finalized_scenario_evidence', broken)
    item, _, _ = prepare(condition_owner, tmp_path, monkeypatch)
    item._waapi_phase_reports['teardown'] = 'passed'
    report = SimpleNamespace(when='teardown', outcome='passed')
    finalize_reported_node_evidence(item, report)
    assert report.outcome == 'failed'
    assert not condition_owner.runtime.owned_root.exists()
    final = json.loads((condition_owner.runtime.evidence_root / 'lifecycle-final.json').read_text())
    assert final['final_status'] == 'PASS' and final['sandbox_retained'] is False
    error = json.loads((condition_owner.runtime.evidence_root / 'condition-finalization-error.json').read_text())
    assert error['phase'] == 'publication' and error['acceptance'] == 'withheld'
    assert not condition_owner._lock_acquired



def test_failed_preparation_still_stops_original_native_owner_and_retains_resources(condition_owner, tmp_path, monkeypatch):
    from tests.destructive.support import condition_finalization
    capture, kwargs, observed = inputs(tmp_path, monkeypatch)
    observed['host'] = deepcopy(condition_owner.runtime.lifecycle.ready_result)
    kwargs['observation_path'].unlink()
    with pytest.raises(FileNotFoundError):
        condition_finalization.prepare_condition_finalization(
            item=SimpleNamespace(nodeid=capture['nodeid']), owner=condition_owner, status='PASS', reason='',
            repo_root=kwargs['repo_root'], candidate=kwargs['candidate'], version=kwargs['version'],
            started_at_unix_ns=1, host=observed['host'], observation_path=kwargs['observation_path'],
            transactions=[])
    assert condition_owner._finished
    assert condition_owner.runtime.lifecycle.process is None
    assert not condition_owner._lock_acquired
    assert condition_owner.runtime.sandbox.sandbox_project.exists()


@pytest.mark.parametrize('late_failure', [False, True])
def test_real_pytest_module_teardown_precedes_condition_cleanup_and_acceptance(condition_owner, tmp_path, monkeypatch, late_failure):
    from tests import conftest
    original = []
    filename = tmp_path / f'test_owned_condition_{int(late_failure)}.py'
    filename.write_text('def test_probe(owned_probe):\n    owned_probe()\n')
    class OwnerPlugin:
        @pytest.fixture(scope='module', autouse=True)
        def late_teardown(self):
            yield
            assert condition_owner._lock_acquired
            assert condition_owner.runtime.sandbox.sandbox_project.exists()
            if late_failure:
                raise RuntimeError('actual late module fixture failure')
        @pytest.fixture
        def owned_probe(self, request):
            def run():
                original.append(prepare(condition_owner, tmp_path, monkeypatch, item=request.node))
            return run
    monkeypatch.setenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
    class ReportsPlugin:
        pytest_runtest_makereport = staticmethod(conftest.pytest_runtest_makereport)
    code = pytest.main([str(filename), '--rootdir', str(tmp_path), '-q', '-p', 'no:cacheprovider'], plugins=[OwnerPlugin(), ReportsPlugin()])
    assert int(code) == (1 if late_failure else 0)
    assert not condition_owner._lock_acquired
    _, capture, _ = original[0]
    assert condition_owner.runtime.sandbox.sandbox_path.exists() is late_failure
    rows = [json.loads(line) for line in (tmp_path / 'category.jsonl').read_text().splitlines()]
    assert any(row['invocation']['outcome'] == 'PASS' for row in rows) is (not late_failure)


@pytest.mark.parametrize('damage', ['source-seal', 'observation', 'owned-process', 'released-lock'])
def test_fresh_post_teardown_fault_retains_resources_and_cannot_publish_native_pass(condition_owner, tmp_path, monkeypatch, damage):
    from wwise_waapi.headless import HeadlessLifecycle
    item, capture, _ = prepare(condition_owner, tmp_path, monkeypatch)
    if damage == 'source-seal':
        source = condition_owner.runtime.sandbox.source_root / 'SampleProject.wproj'
        source.write_bytes(source.read_bytes() + b'changed')
    elif damage == 'observation':
        (tmp_path / 'original-observation.json').write_text('{}')
    elif damage == 'owned-process':
        prefix = condition_owner.runtime.lifecycle._owned_wine_prefix()
        monkeypatch.setattr(HeadlessLifecycle, '_process_rows', lambda *_, **__: [(98765, f'WINEPREFIX={prefix} WwiseConsole.exe')])
    else:
        condition_owner.lock.__exit__(None, None, None)
    item._waapi_phase_reports['teardown'] = 'passed'
    report = SimpleNamespace(when='teardown', outcome='passed')
    finalize_reported_node_evidence(item, report)
    assert report.outcome == 'failed'
    assert condition_owner.runtime.sandbox.sandbox_project.exists()
    assert condition_owner.runtime.owned_root.exists()
    assert not capture['root'].exists()
    assert not condition_owner._lock_acquired
    assert not (condition_owner.runtime.evidence_root / 'lifecycle-final.json').exists()
    error = json.loads((condition_owner.runtime.evidence_root / 'condition-finalization-error.json').read_text())
    assert error['phase'] == 'post-teardown-or-cleanup' and error['sandbox_retained'] is True
