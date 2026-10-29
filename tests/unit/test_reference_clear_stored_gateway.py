"""A stored-reference clear must not be confused with inherited authoring state."""
from copy import deepcopy

import pytest

from tests.unit.test_conditional_reference_gateway import AttenuationTask, FIRST, SECOND, VERSIONS
from tests.unit.test_playlist_reference_gateway import preview_and_confirm, writes
from tests.unit.test_time_modulator_range_gateway import finish
from wwise_waapi.transactions import TransactionState, TransactionStore

PARENT = '{33333333-3333-3333-3333-333333333333}'
INHERITED = '{44444444-4444-4444-4444-444444444444}'
NULL = '{00000000-0000-0000-0000-000000000000}'


class StoredReferenceTask(AttenuationTask):
    def __init__(self, path, version='2025.1'):
        super().__init__(path, version, operation='object.setReference')
        self.objects[FIRST].update(Attenuation={'id': SECOND}, parent={'id': PARENT})
        self.objects[PARENT] = {'id': PARENT, 'name': 'Parent', 'type': 'RandomSequenceContainer',
            'classId': 2, 'path': r'\Actor-Mixer Hierarchy\Default Work Unit\Parent',
            'Attenuation': {'id': INHERITED}, 'OverridePositioning': True, 'notes': 'retain parent'}
        self.objects[INHERITED] = {'id': INHERITED, 'name': 'Inherited', 'type': 'Attenuation',
            'classId': 3, 'path': r'\Attenuations\Default Work Unit\Inherited'}

    def call(self, uri, args=None, options=None):
        if uri.endswith('setReference') and args['value'] == NULL:
            self.calls.append((uri, deepcopy(args), options))
            if not getattr(self, 'drop_clear', False):
                self.objects[args['object']][args['reference']] = deepcopy(getattr(self, 'clear_result', None))
            return {}
        result = super().call(uri, args, options)
        if uri.endswith('object.get') and args.get('from', {}).get('id'):
            for row in result['return']:
                if row['id'] != FIRST:
                    continue
                for field in options['return']:
                    if field == '@Attenuation':
                        row[field] = deepcopy(self.objects[FIRST]['Attenuation'])
                        fault = getattr(self, 'local_read_fault', None)
                        if fault == 'missing':
                            del row[field]
                        elif fault == 'malformed':
                            row[field] = {'id': 'not-a-guid'}
                        elif fault == 'malformed-name':
                            row[field] = {'id': SECOND, 'name': False}
                        elif fault == 'missing-id':
                            row[field] = {'future': {'id': SECOND}}
                    elif field == 'Attenuation':
                        source = FIRST if self.objects[FIRST]['OverridePositioning'] else PARENT
                        row[field] = deepcopy(self.objects[source]['Attenuation'])
        return result

    def declare_clear(self):
        source = self.bind(FIRST)
        field = self.discover(source, 'Attenuation')
        code, declared = self.step('draft-declare-field-change', '--object-handle', source,
            '--field-handle', field, '--clear-reference')
        assert code == 0, declared


@pytest.mark.parametrize('version', VERSIONS)
def test_clear_stored_reference_verifies_while_the_inherited_reference_still_applies(tmp_path, version):
    task = StoredReferenceTask(tmp_path, version)
    before = deepcopy(task.objects)
    task.declare_clear()
    preview, _, verified, tx = finish(task)
    assert verified['verified'] is True
    assert task.objects == {**before, FIRST: {**before[FIRST], 'Attenuation': None}}
    writes = [args for uri, args, _ in task.calls if uri.endswith('setReference')]
    assert writes == [{'object': FIRST, 'reference': 'Attenuation', 'value': NULL}]
    observation = preview['preview_summary']['verification_plan']['reference_observation']
    assert observation['value_source'] == 'local_stored'
    assert observation['outcome'] == 'stored reference cleared; an inherited reference may still apply'
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    before_field = shown['artifact']['prepared_operation']['pre_state']['field_before']
    assert before_field['value'] == {'id': SECOND}
    assert before_field['resolved_value'] == {'id': INHERITED}
    code, schema = task.run('--version', version, 'operation-schema', 'object.setReference')
    assert code == 0 and 'inherited reference may still apply' in str(schema), schema


@pytest.mark.parametrize('version', VERSIONS)
def test_clear_preserves_native_reference_extensions_and_accepts_an_extended_null_guid(tmp_path, version):
    task = StoredReferenceTask(tmp_path, version)
    for identity in (FIRST, PARENT):
        task.objects[identity]['Attenuation'].update(name='Reference target', future={'enabled': False, 'count': 0})
    task.clear_result = {'id': NULL, 'name': '', 'future': {'enabled': False, 'count': 0}}
    before = deepcopy(task.objects)
    task.declare_clear()
    _, _, verified, tx = finish(task)
    assert verified['verified'] is True
    assert task.objects == {**before, FIRST: {**before[FIRST], 'Attenuation': task.clear_result}}
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    field_before = shown['artifact']['prepared_operation']['pre_state']['field_before']
    assert field_before['value'] == before[FIRST]['Attenuation']
    assert field_before['resolved_value'] == before[PARENT]['Attenuation']
    assert len(writes(task)) == 1


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('drift', ['stored', 'resolved'])
def test_clear_revalidates_stored_reference_and_the_original_resolved_context(tmp_path, version, drift):
    task = StoredReferenceTask(tmp_path, version)
    task.declare_clear()
    tx = preview_and_confirm(task)
    if drift == 'stored':
        task.objects[FIRST]['Attenuation'] = {'id': INHERITED}
    else:
        task.objects[PARENT]['Attenuation'] = {'id': SECOND}
    before = deepcopy(task.objects)
    code, rejected = task.run('execute', tx)
    assert code == 2, rejected
    assert task.objects == before and writes(task) == []


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('view', ['stored', 'resolved'])
@pytest.mark.parametrize('member', ['enabled', 'count'])
def test_clear_guards_native_reference_extension_boolean_number_drift(tmp_path, version, view, member):
    task = StoredReferenceTask(tmp_path, version)
    identity = FIRST if view == 'stored' else PARENT
    task.objects[identity]['Attenuation']['future'] = {'enabled': False, 'count': 0}
    task.declare_clear()
    tx = preview_and_confirm(task)
    task.objects[identity]['Attenuation']['future'][member] = 0 if member == 'enabled' else False
    before = deepcopy(task.objects)
    code, rejected = task.run('execute', tx)
    assert code == 2 and writes(task) == [] and task.objects == before, rejected


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('resolved_null', [False, True])
def test_dropped_clear_never_verifies_from_the_resolved_value_alone(tmp_path, version, resolved_null):
    task = StoredReferenceTask(tmp_path, version)
    task.drop_clear = True
    if resolved_null:
        task.objects[PARENT]['Attenuation'] = None
    task.declare_clear()
    tx = preview_and_confirm(task)
    code, executed = task.run('execute', tx)
    assert code == 0, executed
    code, verified = task.run('verify', tx)
    assert code == 2 and verified['verified'] is False, verified
    assert task.objects[FIRST]['Attenuation'] == {'id': SECOND}
    code, replay = task.run('execute', tx)
    assert code == 2 and len(writes(task)) == 1, replay


def test_inactive_clear_does_not_admit_an_ordinary_non_null_restoration(tmp_path):
    task = StoredReferenceTask(tmp_path)
    task.declare_clear()
    finish(task)
    before = deepcopy(task.objects)
    code, started = task.run('draft-start', 'object.setReference')
    assert code == 0, started
    task.draft, task.authority = started['draft']['draft_id'], started['task_authority']
    task.revision = started['draft']['revision']
    source, target = task.bind(FIRST), task.bind(SECOND)
    field = task.discover(source, 'Attenuation')
    code, declared = task.step('draft-declare-field-change', '--object-handle', source,
        '--field-handle', field, '--target-handle', target)
    assert code == 0, declared
    code, rejected = task.step('draft-check')
    assert code == 2 and rejected['error_code'] == 'REFERENCE_ACTIVATION_REQUIRED', rejected
    assert task.objects == before and len(writes(task)) == 1
    assert task.objects[FIRST]['OverridePositioning'] is False
    assert task.objects[PARENT]['Attenuation'] == {'id': INHERITED}


@pytest.mark.parametrize('fault', ['missing', 'malformed', 'malformed-name', 'missing-id'])
@pytest.mark.parametrize('stage', ['preview', 'before-execute', 'after-execute'])
def test_local_reference_projection_is_required_at_each_clear_phase(tmp_path, fault, stage):
    task = StoredReferenceTask(tmp_path)
    task.declare_clear()
    if stage == 'preview':
        task.local_read_fault = fault
        code, rejected = task.step('draft-check')
        assert code == 2 and writes(task) == [], rejected
        return
    tx = preview_and_confirm(task)
    if stage == 'after-execute':
        code, executed = task.run('execute', tx)
        assert code == 0, executed
    task.local_read_fault = fault
    code, rejected = task.run('execute' if stage == 'before-execute' else 'verify', tx)
    assert code == 2, rejected
    assert len(writes(task)) == (1 if stage == 'after-execute' else 0)


@pytest.mark.parametrize('stage', ['unexecuted', 'executed', 'indeterminate', 'previously-verified'])
def test_legacy_clear_never_reinterprets_resolved_prestate_or_replays_a_write(tmp_path, stage):
    task = StoredReferenceTask(tmp_path)
    task.declare_clear()
    original = preview_and_confirm(task)
    store = TransactionStore(tmp_path / 'state')
    artifact = deepcopy(store.load_preview(original).artifact)
    prepared = artifact['prepared_operation']
    before = prepared['pre_state']['field_before']
    # A sealed pre-R70 artifact observed the bare, resolved value only.
    prepared['verification_plan'].pop('reference_observation')
    before.pop('reference_observation')
    before['value'] = before.pop('resolved_value')
    before['row'].pop('@Attenuation')
    tx = 'legacy-clear'
    created = store.create_preview(tx, artifact)
    store.submit_for_confirmation(tx)
    store.confirm(tx, artifact_hash=created.artifact_hash)
    if stage != 'unexecuted':
        store.begin_execution(tx, expected_authorization=TransactionState.CONFIRMED)
        if stage == 'indeterminate':
            store.mark_execution_indeterminate(tx, details={'reason': 'historical ambiguous dispatch'})
        else:
            task.objects[FIRST]['Attenuation'] = None
            store.mark_executed_unverified(tx, details={'dispatch_result': {'status': 'ok', 'result': {}}})
            if stage == 'previously-verified':
                store.record_verification(tx, 'verified', details={'historical_result': 'preserve original verdict'})
                original_events = store.read_events(tx)
                code, rejected = task.run('verify', tx)
                assert code == 2 and store.read_events(tx) == original_events, rejected
            else:
                code, verified = task.run('verify', tx)
                assert code == 2 and verified['verified'] is False, verified
                assert 'unobserved_stored_reference' in str(verified), verified
    before_objects = deepcopy(task.objects)
    code, rejected = task.run('execute', tx)
    assert code == 2 and writes(task) == [] and task.objects == before_objects, rejected
    expected_state = (TransactionState.REPREVIEW_REQUIRED if stage == 'unexecuted'
        else TransactionState.VERIFIED if stage == 'previously-verified' else TransactionState.INDETERMINATE)
    assert store.load(tx).state is expected_state
    if stage == 'unexecuted':
        assert 'REFERENCE_CLEAR_REPREVIEW_REQUIRED' in str(rejected), rejected
