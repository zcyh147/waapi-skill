"""Diagnostic collection through the public Gateway, with independent native packets."""
from copy import deepcopy
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tests.unit.test_workflow_source_guard import workflow
from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, SECOND, CHILD
from tests.unit.test_object_graph_business_gateway import gateway


def notes_runtime(tmp_path, workflow, monkeypatch, *, fault=None):
    task = OwnedGraphTask(tmp_path, '2025.1', 'object.create')
    task.objects = {SECOND: {'id': SECOND, 'name': 'Default Work Unit', 'type': 'WorkUnit',
        'classId': 3, 'path': r'\Containers\Default Work Unit', 'notes': ''}}
    source = tmp_path / 'immutable.wproj'; source.write_text('immutable source')
    task.env['WWISE_EVIDENCE_DIR'] = str(tmp_path / 'native')
    original = task.call
    callbacks, writes, trace = [], [], []
    active = []
    # Literal Notes fields/values observed at native 8f7d4432; the owned test
    # identity is rebound here. This is not generated from the reflected schema.
    packet = {'summary': 'Set Notes', 'objects': [{'object': {
        'id': CHILD, 'name': 'WAAPI_NOTES_TEST', 'type': 'PropertyContainer',
        'path': r'\Containers\Default Work Unit\WAAPI_NOTES_TEST', 'notes': 'topic-notes-after'},
        'changes': [{'type': 'notesChange', 'notesChange': {
            'oldNotes': 'topic-notes-before', 'newNotes': 'topic-notes-after'}}]}]}
    if fault == 'names-only':
        packet['objects'][0]['changes'][0]['notesChange'] = {
            'oldName': 'topic-notes-before', 'newName': 'topic-notes-after'}
    if fault == 'wrong-guid': packet['objects'][0]['object']['id'] = SECOND
    if fault == 'incomplete-diagnostic': packet['padding'] = 'x' * 2200

    def call(uri, args=None, options=None):
        if uri.endswith('object.get') and args.get('waql', '').startswith('from object "'):
            identity = args['waql'].split('"')[1]
            rows = [row for row in task.objects.values() if row['id'] == identity or row['path'] == identity]
            return {'return': task.project_rows(rows, options)}
        if uri.endswith('object.setNotes'):
            trace.append('setNotes'); writes.append((uri, deepcopy(args)))
            assert active and args == {'object': CHILD, 'value': 'topic-notes-after'}
            task.objects[CHILD]['notes'] = args['value']
            callbacks.append(deepcopy(packet)); active[0](deepcopy(packet))
            return {}
        if uri.endswith('object.delete'):
            writes.append((uri, deepcopy(args))); del task.objects[args['object']]
            return {}
        result = original(uri, args, options)
        if uri.endswith('getInfo'): result['version'].update(minor=7, build=9143)
        return result

    def subscribe(uri, callback, options=None):
        assert uri == 'ak.wwise.core.object.structureChanged'
        assert options == {'return': ['id', 'name', 'type', 'path', 'notes']}
        trace.append('subscribed'); active.append(callback)
        def unsubscribe():
            trace.append('unsubscribe')
            if fault == 'cleanup': return False
            active.clear(); return True
        return SimpleNamespace(unsubscribe=unsubscribe)

    task.call, task.subscribe = call, subscribe
    class Runtime(SimpleNamespace):
        def packaged_topic_producer(self, argv):
            return workflow._WorkflowSandboxRuntime.packaged_topic_producer(self, argv)
    runtime = Runtime(version='2025.1', candidate='a' * 40, category_results=[],
        state_dir=tmp_path / 'state', env=task.env, port=31337,
        sandbox=SimpleNamespace(source_project=source, sandbox_project=task.project_file),
        lifecycle=SimpleNamespace(host='127.0.0.1', waapi_url='ws://127.0.0.1:31337/waapi'))
    def raw(argv, *, stream_sink=None):
        def sink(record):
            trace.append(record['record_type'])
            stream_sink(record)
            if fault == 'duplicate-started' and record['record_type'] == 'started':
                stream_sink(deepcopy(record))
        def observer_client(_url):
            assert not active, 'Observer process opened a peer client while subscribed'
            return task
        return gateway.execute_gateway(['--state-dir', str(runtime.state_dir), *argv], env=task.env,
            client_factory=observer_client, stream_sink=sink if stream_sink else None)
    runtime.raw_gateway = raw
    from tests.semantic.support import codex_expansion_reconciliation as processes
    launches = []
    def producer(command, *, environment, timeout_seconds, cwd=None, text=True):
        assert active and command[:3] == [sys.executable, str(workflow.REPO_ROOT / 'skills/waapi-skill/scripts/run.py'), 'gateway.py']
        assert command[3:7] == ['--timeout', '10', '--state-dir', str(runtime.state_dir)]
        assert environment == {**runtime.env, 'PYTHONIOENCODING': 'utf-8:strict', 'PYTHONUTF8': '1'}
        assert environment is not runtime.env and cwd == workflow.REPO_ROOT / 'skills/waapi-skill'
        assert 0 < timeout_seconds <= 30 and text is True
        argv = command[7:]; launches.append(list(argv)); trace.append('producer:' + argv[0])
        # Separate peer facade: the observer must not open/close a peer transport.
        peer = SimpleNamespace(call=task.call, disconnect=lambda: None)
        code, payload = gateway.execute_gateway(command[3:], env=environment, client_factory=lambda _url: peer)
        return subprocess.CompletedProcess(command, code, json.dumps(payload), '')
    monkeypatch.setattr(processes, 'run_owned_gateway', producer)
    task.producer_launches = launches
    return runtime, task, packet, callbacks, writes, trace, active


def test_notes_diagnostic_retains_actual_rejected_packet_and_independent_readback(tmp_path, workflow, monkeypatch):
    runtime, task, packet, callbacks, writes, trace, active = notes_runtime(tmp_path, workflow, monkeypatch, fault='names-only')
    with pytest.raises(AssertionError, match='Notes event schema rejected; exact diagnostic retained'):
        workflow._collect_structure_changed_notes_diagnostic(runtime, name='WAAPI_NOTES_TEST')
    receipt = json.loads((runtime.state_dir / 'structure-changed-notes-diagnostic.json').read_text())
    assert receipt['collection_complete'] is True
    assert receipt['event'] == packet == callbacks[0]
    assert receipt['notes_shape'] == 'oldName/newName'
    assert receipt['after']['notes'] == 'topic-notes-after'
    assert receipt['native_delivery_pass'] is False and receipt['diagnostic_only'] is True
    assert receipt['object_cleanup'] == 'verified_absent'
    assert receipt['stream']['payload']['error_code'] == 'TOPIC_EVENT_SCHEMA_MISMATCH'
    assert trace.index('subscribed') < trace.index('started') < trace.index('setNotes') < trace.index('unsubscribe')
    trigger = next(row for row in receipt['calls'] if row['argv'] == ['execute', receipt['notes_transaction_id']])
    authorization = next(row for row in receipt['calls'] if row['argv'][:2] == ['confirm', receipt['notes_transaction_id']])
    assert authorization['started_monotonic_ns'] < receipt['started_monotonic_ns'] < trigger['started_monotonic_ns']
    assert not active and CHILD not in task.objects
    assert len([uri for uri, _ in writes if uri.endswith('object.setNotes')]) == 1
    assert runtime.category_results[0]['status'] == 'FAIL'


@pytest.mark.parametrize('fault,message', [
    ('wrong-guid', 'Wrong GUID in Notes event'),
    ('incomplete-diagnostic', 'Incomplete Notes event diagnostic'),
    ('cleanup', 'Notes subscription cleanup not proven'),
    ('duplicate-started', 'Duplicate started record'),
])
def test_notes_collector_rejects_unusable_evidence_without_replaying_trigger(tmp_path, workflow, monkeypatch, fault, message):
    runtime, task, packet, callbacks, writes, trace, active = notes_runtime(tmp_path, workflow, monkeypatch, fault=fault)
    with pytest.raises(AssertionError, match=message):
        workflow._collect_structure_changed_notes_diagnostic(runtime, name='WAAPI_NOTES_TEST')
    receipt = json.loads((runtime.state_dir / 'structure-changed-notes-diagnostic.json').read_text())
    assert receipt['collection_complete'] is False and receipt['native_delivery_pass'] is False
    assert runtime.category_results[0]['status'] == 'FAIL'
    assert len([uri for uri, _ in writes if uri.endswith('object.setNotes')]) == 1
    assert not any(uri.endswith('object.delete') for uri, _ in writes)
    assert CHILD in task.objects  # Existing finalizer must quarantine this failed sandbox.
    assert bool(active) is (fault == 'cleanup')
    if fault == 'cleanup':
        assert receipt['records'][1]['event'] == packet == callbacks[0]
        terminal = receipt['stream']['payload']
        assert terminal['error_code'] == 'SUBSCRIPTION_CLEANUP_FAILED'
        assert terminal['monitoring_outcome']['event_count'] == 1
        assert terminal['monitoring_outcome']['target_completed'] is False
        assert terminal['cleanup'] == 'unsubscribe_failed'


def test_notes_collector_uses_isolated_producer_and_preserves_observed_old_notes_packet(tmp_path, workflow, monkeypatch):
    runtime, task, packet, callbacks, writes, trace, active = notes_runtime(tmp_path, workflow, monkeypatch)
    category = workflow._collect_structure_changed_notes_diagnostic(runtime, name='WAAPI_NOTES_TEST')
    receipt = json.loads((runtime.state_dir / 'structure-changed-notes-diagnostic.json').read_text())
    assert receipt['collection_complete'] is True and receipt['schema_validation'] == 'accepted'
    assert receipt['event'] == packet == callbacks[0] and receipt['notes_shape'] == 'oldNotes/newNotes'
    transaction = receipt['notes_transaction_id']
    assert task.producer_launches == [['execute', transaction], ['verify', transaction]]
    assert [row['execution_context'] for row in receipt['calls']
        if row['argv'] in task.producer_launches] == ['separate_packaged_gateway_process'] * 2
    assert len([uri for uri, _ in writes if uri.endswith('object.setNotes')]) == 1
    assert category['diagnostic_only'] is True and category['coverage_credit'] == 'none'
    assert receipt['native_delivery_pass'] is False and not active


def test_packaged_notes_producer_preserves_unicode_under_inherited_non_utf8_environment(tmp_path, workflow, monkeypatch):
    skill = tmp_path / 'skills/waapi-skill'
    scripts = skill / 'scripts'; scripts.mkdir(parents=True)
    # Independent external CLI fixture: real stdout encoding/strict UTF-8
    # decoding must preserve this literal JSON, without a Wwise connection.
    (scripts / 'run.py').write_text(
        "import os, sys\n"
        "sys.stdout.write('{\"ok\":true,\"result\":{\"name\":\"Café\"}}\\n')\n"
        "assert os.environ['PYTHONIOENCODING'] == 'utf-8:strict'\n"
        "assert os.environ['PYTHONUTF8'] == '1'\n"
        "assert sys.argv[1] == 'gateway.py'\n",
        encoding='utf-8',
    )
    config = tmp_path / 'private-config.json'; config.write_bytes(b'{"private":true}')
    environment = {**os.environ, 'PYTHONIOENCODING': 'latin-1:strict', 'PYTHONUTF8': '0',
        'WAAPI_SKILL_CONFIG_PATH': str(config)}
    before = dict(environment)
    runtime = SimpleNamespace(env=environment, state_dir=tmp_path / 'private-state')
    monkeypatch.setattr(workflow, 'REPO_ROOT', tmp_path)
    code, result = workflow._WorkflowSandboxRuntime.packaged_topic_producer(
        runtime, ['execute', 'tx1-aaaaaaaaaaaaaaaaaaaa'])
    assert code == 0 and result == {'ok': True, 'result': {'name': 'Café'}}
    assert runtime.env == before and config.read_bytes() == b'{"private":true}'


def test_filtered_notes_collector_uses_both_disclosed_fixed_fields(tmp_path, workflow, monkeypatch):
    runtime, task, packet, callbacks, writes, trace, active = notes_runtime(tmp_path, workflow, monkeypatch)
    category = workflow._collect_structure_changed_notes_diagnostic(runtime, name='WAAPI_NOTES_TEST', filtered=True)
    receipt = json.loads((runtime.state_dir / 'structure-changed-notes-filtered-diagnostic.json').read_text())
    assert category['category'] == 'structure-changed-notes-filtered-diagnostic'
    assert receipt['event'] == packet == callbacks[0] and receipt['collection_complete'] is True
    assert receipt['stream']['payload']['match'] == {'objects': [{'changes': [{'notesChange': {
        'oldNotes': 'topic-notes-before', 'newNotes': 'topic-notes-after'}}]}]}
    disclosures = [row['argv'] for row in receipt['calls'] if '--row-field-group' in row['argv']]
    assert [argv[-1] for argv in disclosures] == ['notes-change-old-notes', 'notes-change-new-notes']
    assert not (runtime.state_dir / 'structure-changed-notes-diagnostic.json').exists()
    assert receipt['native_delivery_pass'] is False and not active
