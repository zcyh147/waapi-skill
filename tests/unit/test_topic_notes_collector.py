"""Diagnostic collection through the public Gateway, with independent native packets."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from tests.unit.test_workflow_source_guard import workflow
from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, SECOND, CHILD
from tests.unit.test_object_graph_business_gateway import gateway


def notes_runtime(tmp_path, *, fault=None):
    task = OwnedGraphTask(tmp_path, '2025.1', 'object.create')
    task.objects = {SECOND: {'id': SECOND, 'name': 'Default Work Unit', 'type': 'WorkUnit',
        'classId': 3, 'path': r'\Containers\Default Work Unit', 'notes': ''}}
    source = tmp_path / 'immutable.wproj'; source.write_text('immutable source')
    task.env['WWISE_EVIDENCE_DIR'] = str(tmp_path / 'native')
    original = task.call
    callbacks, writes, trace = [], [], []
    active = []
    packet = {'summary': 'Set Notes', 'objects': [{'object': {
        'id': CHILD, 'name': 'WAAPI_NOTES_TEST', 'type': 'PropertyContainer',
        'path': r'\Containers\Default Work Unit\WAAPI_NOTES_TEST', 'notes': 'topic-notes-after'},
        'changes': [{'type': 'notesChange', 'notesChange': {
            'oldName': 'topic-notes-before', 'newName': 'topic-notes-after'}}]}]}
    if fault == 'wrong-guid': packet['objects'][0]['object']['id'] = SECOND
    if fault == 'incomplete-diagnostic': packet['padding'] = 'x' * 2200
    if fault == 'both':
        packet['objects'][0]['changes'][0]['notesChange'].update(
            oldNotes='topic-notes-before', newNotes='topic-notes-after')

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
    runtime = SimpleNamespace(version='2025.1', candidate='a' * 40, category_results=[],
        state_dir=tmp_path / 'state', env=task.env, port=31337,
        sandbox=SimpleNamespace(source_project=source, sandbox_project=task.project_file),
        lifecycle=SimpleNamespace(host='127.0.0.1', waapi_url='ws://127.0.0.1:31337/waapi'))
    def raw(argv, *, stream_sink=None):
        def sink(record):
            trace.append(record['record_type'])
            stream_sink(record)
            if fault == 'duplicate-started' and record['record_type'] == 'started':
                stream_sink(deepcopy(record))
        return gateway.execute_gateway(['--state-dir', str(runtime.state_dir), *argv], env=task.env,
            client_factory=lambda _url: task, stream_sink=sink if stream_sink else None)
    runtime.raw_gateway = raw
    return runtime, task, packet, callbacks, writes, trace, active


def test_notes_diagnostic_retains_actual_rejected_packet_and_independent_readback(tmp_path, workflow):
    runtime, task, packet, callbacks, writes, trace, active = notes_runtime(tmp_path)
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
def test_notes_collector_rejects_unusable_evidence_without_replaying_trigger(tmp_path, workflow, fault, message):
    runtime, task, packet, callbacks, writes, trace, active = notes_runtime(tmp_path, fault=fault)
    with pytest.raises(AssertionError, match=message):
        workflow._collect_structure_changed_notes_diagnostic(runtime, name='WAAPI_NOTES_TEST')
    receipt = json.loads((runtime.state_dir / 'structure-changed-notes-diagnostic.json').read_text())
    assert receipt['collection_complete'] is False and receipt['native_delivery_pass'] is False
    assert runtime.category_results[0]['status'] == 'FAIL'
    assert len([uri for uri, _ in writes if uri.endswith('object.setNotes')]) == 1
    assert not any(uri.endswith('object.delete') for uri, _ in writes)
    assert CHILD in task.objects  # Existing finalizer must quarantine this failed sandbox.
    assert bool(active) is (fault == 'cleanup')


def test_notes_collector_preserves_both_field_pairs_without_claiming_coverage(tmp_path, workflow):
    runtime, task, packet, callbacks, writes, trace, active = notes_runtime(tmp_path, fault='both')
    category = workflow._collect_structure_changed_notes_diagnostic(runtime, name='WAAPI_NOTES_TEST')
    receipt = json.loads((runtime.state_dir / 'structure-changed-notes-diagnostic.json').read_text())
    assert receipt['collection_complete'] is True and receipt['schema_validation'] == 'accepted'
    assert receipt['event'] == packet == callbacks[0] and receipt['notes_shape'] == 'both'
    assert category['diagnostic_only'] is True and category['coverage_credit'] == 'none'
    assert receipt['native_delivery_pass'] is False and not active
