"""Model witnesses cross public Gateway construction, observer and final writer."""
from copy import deepcopy
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.destructive.support import authoring_batch, model_workflows as witness
from tests.unit.test_authoring_batch_adapter import owned_authoring
from tests.unit.test_authoring_model_gateway import ModelClient
from tests.unit.test_waapi_gateway import FakeEventHandler, gateway_env, waapi_gateway as gateway
from tests.semantic.support.codex_expansion_case_helpers import CaseBoundaryError


def _host(tmp_path, monkeypatch, owner, *, damage=None, paired=False):
    from tests.semantic.support import codex_scenario_lifecycle_v3 as lifecycle
    from wwise_waapi.headless import CleanupReport, HeadlessLifecycle
    for name in ('WWISE_LIVE', 'WWISE_DESTRUCTIVE', 'WWISE_AUTHORING_LIVE'):
        monkeypatch.setenv(name, '1')
    native = importlib.import_module('tests.destructive.test_authoring_ui_business_live')
    root = tmp_path / 'native-client'
    root.mkdir()
    owner.runtime.lifecycle.ready_result['processPath'] = str(root / 'Wwise')
    owner.runtime.lifecycle.ready_result['version']['schema'] = 152
    owner.runtime.lifecycle.ready_result['version']['displayName'] = '.'.join(
        str(owner.runtime.lifecycle.ready_result['version'][key]) for key in ('year', 'major', 'minor', 'build'))
    events = []

    class Client(ModelClient):
        def __init__(self):
            super().__init__(root, version=owner.version)
            self.responses['ak.wwise.core.getInfo'].update(deepcopy(owner.runtime.lifecycle.ready_result))
            self.responses['ak.wwise.core.getProjectInfo']['path'] = str(owner.runtime.sandbox.sandbox_project)
            self.responses['ak.wwise.core.getProjectInfo']['name'] = 'SampleProject'
            self.widget_values = {'State': {'Checked': False}, 'Trigger': {}}
            self.callbacks = {}
            self.responses.update({witness.URI + suffix: {} for suffix in ('window.present', 'window.close')})
        def subscribe(self, uri, callback, options=None):
            events.append('subscribe')
            self.callbacks[uri] = callback
            handler = FakeEventHandler()
            self.handlers.append(handler)
            return handler
        def call(self, uri, args=None, options=None):
            if uri == witness.URI + 'signal.emit':
                self.calls.append((uri, args, options))
                events.append('emit')
                if damage == 'silence': return {}
                self.callbacks[args['signal']]({'handleID': '{55555555-5555-5555-5555-555555555555}', 'widgetID': args['widgetID']})
                self.callbacks[args['signal']]({'handleID': args['handleID'], 'widgetID': args['widgetID']})
                return {}
            if damage == 'create-readback' and uri == witness.URI + 'model.getState' and not args['state'][0]['state']:
                self.calls.append((uri, args, options))
                return [{'widgetID': row['widgetID'], 'state': [{'attribute': 'Checked', 'value': False}]} for row in args['state']]
            if damage == 'destroy' and uri == witness.URI + 'model.destroyHandle':
                self.calls.append((uri, args, options))
                raise TimeoutError('Unknown destruction result; never replay')
            return super().call(uri, args, options)
    client = Client()
    if damage == 'silence': monkeypatch.setattr(witness, 'OBSERVER_SECONDS', 2.0)
    original_observer = native.gateway.execute_gateway
    def observer(argv, **kwargs):
        sink = kwargs.get('stream_sink')
        if damage == 'duplicate-ack':
            def duplicate(record):
                sink(record)
                if record.get('record_type') == 'started': sink(record)
            kwargs['stream_sink'] = duplicate
        return original_observer(argv, **kwargs, client_factory=lambda _: client)
    monkeypatch.setattr(native.gateway, 'execute_gateway', observer)
    def factory(*, skill_source, runtime, version, receipts):
        env = gateway_env(runtime.owned_root)
        env['WAAPI_SKILL_CONFIG_PATH'] = str(runtime.owned_root / 'setup-config.json')
        def call(argv, **kwargs):
            code, payload = gateway.execute_gateway(['--state-dir', str(runtime.owned_root / 'setup-state'), *argv],
                env=env, client_factory=lambda _: client)
            receipts.append({'argv': list(argv), 'exit_code': code, 'payload': payload})
            if code or payload.get('ok') is not True: raise CaseBoundaryError(str(payload))
            if damage == 'stale-session' and argv[0] == 'topic-schema':
                client.responses['ak.wwise.core.getInfo']['sessionId'] = 'other-session'
            return payload
        return call
    monkeypatch.setattr(authoring_batch, 'fixture_gateway', factory)
    def shutdown(process, sandbox, **kwargs):
        process.process = None
        process.cleanup_report = CleanupReport(launch_pid=1234, wine_prefix=None, process_exited=True)
        sandbox.metadata.process_cleanup_result = 'cleaned'
        sandbox.metadata.process_cleanup_details = {'residual_processes': []}
    monkeypatch.setattr(lifecycle, 'shutdown_sandboxed_wwise', shutdown)
    monkeypatch.setattr(authoring_batch, 'wait_for_port_release', lambda *_: None)
    monkeypatch.setattr(HeadlessLifecycle, '_process_rows', lambda *_, **__: [(12345, 'fake pytest process')])
    nodeid = witness.COMMON_NODE if owner.version == '2024.1' else witness.FILE_NODE
    from tests.destructive.support.layout_workflows import COMMON_NODE as LAYOUT_COMMON, CLOSE_NODE as LAYOUT_CLOSE
    layout_node = LAYOUT_COMMON if owner.version == '2024.1' else LAYOUT_CLOSE
    selected = [layout_node, nodeid] if paired else [nodeid]
    batch = authoring_batch.AuthoringBatchAdapter(owner=owner, repo_root=tmp_path, selected_nodeids=selected)
    call = batch.node_gateway(nodeid)
    target = tmp_path / 'categories.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(target))
    run = native.test_authoring_model_2024_state_click if owner.version == '2024.1' else native.test_authoring_model_2025_file_state_toggle
    return batch, call, client, run, nodeid, target, events


@pytest.mark.parametrize('owned_authoring', ['2024.1', '2025.1'], indirect=True)
def test_model_cohort_reaches_final_writer_with_exact_budget_and_independent_outcomes(owned_authoring, tmp_path, monkeypatch):
    batch, call, client, run, nodeid, target, events = _host(tmp_path, monkeypatch, owned_authoring, paired=True)
    # Reuse the frozen #188 witness bytes in this newly approved shared owner.
    from tests.unit.test_authoring_layout_native_fixture import _layout_cohort_host
    from tests.destructive.support.layout_workflows import COMMON_NODE as LAYOUT_COMMON
    layout_root = tmp_path / 'layout-boundary'; layout_root.mkdir()
    _layout_cohort_host(layout_root, monkeypatch, owned_authoring)
    native = importlib.import_module('tests.destructive.test_authoring_ui_business_live')
    layout_node = batch.selected_nodeids[0]
    layout_call = batch.node_gateway(layout_node)
    layout_run = native.test_authoring_layout_2024_construction_arrangement if layout_node == LAYOUT_COMMON else native.test_authoring_layout_2025_construction_close_reset
    layout_run((batch, layout_call))
    run((batch, call))
    runtime = batch.node_runtimes[nodeid]
    report = json.loads((runtime.owned_root / 'native-evidence' / witness.FILENAME).read_text())
    assert [row['operation'] for row in report['effects']] == [witness.URI + op for op in witness.expected_operations(owned_authoring.version)]
    assert len(report['effects']) == (9 if owned_authoring.version == '2024.1' else 8)
    assert events == ['subscribe', 'emit'] and client.handlers[0].unsubscribe_calls == 1
    assert report['signal']['event']['widgetID'] == ('Trigger' if owned_authoring.version == '2024.1' else 'State')
    assert report['state_observed'] and client.widget_values['State']['Checked'] is True
    assert all(row['gateway_retired'] and row['native_disappearance_independently_verified'] is False for row in report['retirements'])
    receipts = batch.receipts[nodeid]
    def validate(changed, rows=receipts):
        witness.validate_model_report(changed, nodeid=nodeid, candidate=batch.candidate, version=owned_authoring.version,
            receipts=rows, state_root=runtime.owned_root / 'setup-state')
    # Meaningful final-consumer negatives reuse this one public witness packet.
    for field in ('state_observed', 'complete'):
        changed = deepcopy(report); changed[field] = False
        with pytest.raises(ValueError): validate(changed)
    changed = deepcopy(report); changed['boundaries']['visible_window_effect_verified'] = True
    with pytest.raises(ValueError): validate(changed)
    changed = deepcopy(report); changed['signal']['event']['widgetID'] = 'Other'
    with pytest.raises(ValueError): validate(changed)
    changed = deepcopy(report); changed['signal']['model'] = 'ar1-' + '0' * 32
    with pytest.raises(ValueError): validate(changed)
    rows = deepcopy(receipts)
    rows.append(next(r for r in rows if r['argv'] == ['execute', report['effects'][-3]['transaction_id']]))
    with pytest.raises(ValueError): validate(report, rows)
    stream = next(r for r in receipts if r['argv'][0] == 'stream-topic')
    changed_rows = deepcopy(receipts)
    next(r for r in changed_rows if r['argv'][0] == 'stream-topic')['payload']['cleanup'] = 'unknown'
    with pytest.raises(ValueError): validate(report, changed_rows)
    assert stream['argv'][1] == report['signal']['topic']
    items = [SimpleNamespace(nodeid=identity, _waapi_phase_reports={'setup': 'passed', 'call': 'passed'})
        for identity in batch.selected_nodeids]
    batch.prepare_stop(items)
    for item in items: item._waapi_phase_reports['teardown'] = 'passed'
    assert batch.finalize(items)['outcome'] == 'PASS'
    final = json.loads(target.read_text().splitlines()[-1])
    categories = {r['category']: r for r in final['categories']}
    assert categories['authoring-model-widget-state']['status'] == 'PASS'
    assert categories['authoring-owned-signal-' + ('click' if owned_authoring.version == '2024.1' else 'toggle')]['status'] == 'PASS'
    assert categories['authoring-model-handle-retirement']['native_disappearance_independently_verified'] is False
    assert categories['authoring-model-window-native-results']['status'] == 'blocked'
    assert categories['authoring-model-window-native-results']['visible_window_effect_verified'] is False
    assert categories['authoring-model-session-cleanup']['status'] == 'PASS'
    assert len(final['transactions']) == (18 if owned_authoring.version == '2024.1' else 16)
    if owned_authoring.version == '2025.1':
        reset = categories['authoring-layout-selected-reset-observation']
        assert reset['status'] == 'blocked' and reset['business_state_verified'] is False
        assert reset['coverage_credit'] == 'none; diagnostic observation only'


@pytest.mark.parametrize('damage', ['create-readback', 'destroy', 'duplicate-ack', 'stale-session', 'silence'])
def test_model_cohort_failure_never_replays_or_claims_cleanup(owned_authoring, tmp_path, monkeypatch, damage):
    batch, call, client, run, nodeid, target, events = _host(tmp_path, monkeypatch, owned_authoring, damage=damage)
    with pytest.raises((Exception, BaseExceptionGroup)):
        run((batch, call))
    runtime = batch.node_runtimes[nodeid]
    report = json.loads((runtime.owned_root / 'native-evidence' / witness.FILENAME).read_text())
    assert not report['complete'] and report['errors']
    writes = [uri for uri, _, _ in client.calls]
    assert writes.count(witness.URI + 'model.createHandle') == 1
    assert writes.count(witness.URI + 'signal.emit') == (0 if damage in ('create-readback', 'stale-session') else 1)
    if damage == 'create-readback':
        assert report['recoveries'] == [{'kind': 'model', 'transaction_id': report['effects'][2]['transaction_id']}]
        assert report['cleanup']['local_resources_retired']
        assert witness.URI + 'model.setState' not in writes
    elif damage == 'destroy':
        assert writes.count(witness.URI + 'model.destroyHandle') == 1
        assert witness.URI + 'window.close' not in writes
        assert not report['cleanup']['local_resources_retired']
    elif damage in ('duplicate-ack', 'silence'):
        assert client.handlers[0].unsubscribe_calls == 1
        assert not report['signal']['target_completed']
    else:
        assert events == [] and not report['cleanup']['local_resources_retired']
    item = SimpleNamespace(nodeid=nodeid, _waapi_phase_reports={'setup': 'passed', 'call': 'failed'})
    batch.prepare_stop([item]); item._waapi_phase_reports['teardown'] = 'passed'
    assert batch.finalize([item], exitstatus=1)['outcome'] == 'FAIL'
    assert not any(r['status'] == 'PASS' for line in target.read_text().splitlines() for r in json.loads(line)['categories'])


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
@pytest.mark.parametrize('variant', ['pair', 'unrelated', 'cross-version', 'triple'])
def test_owner_admits_only_exact_matching_layout_model_pair(tmp_path, monkeypatch, version, variant):
    from tests.unit.test_authoring_batch_owner import _fakes, _config
    from tests.destructive.support.layout_workflows import COMMON_NODE as LAYOUT_COMMON, CLOSE_NODE as LAYOUT_CLOSE
    events = _fakes(monkeypatch, tmp_path)
    monkeypatch.setenv('WWISE_VERSION', version)
    pair = [LAYOUT_COMMON, witness.COMMON_NODE] if version == '2024.1' else [LAYOUT_CLOSE, witness.FILE_NODE]
    selected = list(pair)
    if variant == 'unrelated': selected[0] = authoring_batch.PROFILER_CAPTURE_NODEID
    if variant == 'cross-version': selected[1] = witness.FILE_NODE if version == '2024.1' else witness.COMMON_NODE
    if variant == 'triple': selected.append(authoring_batch.OWNED_AUTHORING_NODEIDS[-1])
    config = _config(tmp_path); config.args = selected
    items = [SimpleNamespace(nodeid=nodeid) for nodeid in selected]
    if variant == 'pair':
        authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
        assert [r[0] for r in events] == ['construct', 'start', 'install']
        assert set(events[-1][1]['selected_nodeids']) == set(pair)
    else:
        with pytest.raises(pytest.UsageError):
            authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
        assert events == []
