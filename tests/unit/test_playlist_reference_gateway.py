"""The documented 2025 direct-child PlaylistSlot edit through public Gateway."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.unit.test_conditional_reference_gateway import AttenuationTask, FIRST, SECOND
from tests.unit.test_time_modulator_range_gateway import finish

OWNER = '{33333333-3333-3333-3333-333333333333}'
PEER = '{44444444-4444-4444-4444-444444444444}'
OLD = '{55555555-5555-5555-5555-555555555555}'
FACTS = json.loads((Path(__file__).parents[1] / 'fixtures/metadata-conditions/playlist-object-2025.json').read_text())


class PlaylistTask(AttenuationTask):
    def __init__(self, path, version='2025.1', target_type='Sound', operation='object.setReference'):
        super().__init__(path, version, operation=operation)
        self.metadata = {'PlaylistObject': deepcopy(FACTS['metadata'])}
        classes = {'PlaylistSlot': 5636096, 'Sound': 65552, 'RandomSequenceContainer': 589840,
                   'SwitchContainer': 655376, 'BlendContainer': 1900560}
        self.types = [{'classId': value, 'name': name, 'type': 'Inner' if name == 'PlaylistSlot' else 'WObject'}
                      for name, value in classes.items()]
        base = r'\Containers\Default Work Unit\Numbers'
        self.objects = {
            FIRST: {'id': FIRST, 'name': '', 'type': 'PluginInnerObject', 'classId': 5636096,
                    'path': base + r'\[PlaylistSlot: (First)]', 'owner': {'id': OWNER}, 'PlaylistObject': {'id': OLD}, 'notes': 'keep'},
            PEER: {'id': PEER, 'name': '', 'type': 'PluginInnerObject', 'classId': 5636096,
                   'path': base + r'\[PlaylistSlot: (Second)]', 'owner': {'id': OWNER}, 'PlaylistObject': {'id': SECOND}},
            OWNER: {'id': OWNER, 'name': 'Numbers', 'type': 'RandomSequenceContainer', 'classId': 589840,
                    'path': base, '@Playlist': [{'id': FIRST}, {'id': PEER}]},
            SECOND: {'id': SECOND, 'name': 'Second', 'type': target_type, 'classId': classes[target_type],
                     'path': base + r'\Second', 'parent': {'id': OWNER}},
            OLD: {'id': OLD, 'name': 'First', 'type': 'Sound', 'classId': 65552,
                  'path': base + r'\First', 'parent': {'id': OWNER}},
        }
        if target_type == 'RandomSequenceContainer':
            self.objects[SECOND]['@RandomOrSequence'] = 1

    def call(self, uri, args=None, options=None):
        result = super().call(uri, args, options)
        if uri.endswith('object.get') and '@PlaylistObject' in (options or {}).get('return', []):
            for row in result.get('return', []):
                source = self.objects.get(row.get('id'), {})
                if 'PlaylistObject' in source:
                    row['@PlaylistObject'] = deepcopy(source['PlaylistObject'])
        if uri.endswith('setReference') and getattr(self, 'display_path_changes', False):
            owner_path = self.objects[OWNER]['path']
            self.objects[FIRST]['path'] = owner_path + '\\[PlaylistSlot: (' + self.objects[args['value']]['name'] + ')]'
        return result

    def declare_playlist(self):
        source, target = self.bind(FIRST), self.bind(SECOND)
        field = self.discover(source, 'Playlist Object')
        code, payload = self.step('draft-declare-field-change', '--object-handle', source,
                                  '--field-handle', field, '--target-handle', target)
        assert code == 0, payload


@pytest.mark.parametrize('target_type', ['Sound', 'RandomSequenceContainer', 'SwitchContainer', 'BlendContainer'])
@pytest.mark.parametrize('display_path_changes', [False, True])
def test_existing_playlist_slot_changes_to_a_direct_child_without_changing_its_list(tmp_path, target_type, display_path_changes):
    task = PlaylistTask(tmp_path, target_type=target_type)
    task.display_path_changes = display_path_changes
    before = deepcopy(task.objects)
    task.declare_playlist()
    preview, _, verified, _ = finish(task)
    assert verified['verified'] is True
    assert not preview['preview_summary'].get('derived_changes')
    expected_path = before[OWNER]['path'] + r'\[PlaylistSlot: (Second)]' if display_path_changes else before[FIRST]['path']
    assert task.objects == {**before, FIRST: {**before[FIRST], 'path': expected_path, 'PlaylistObject': {'id': SECOND}}}
    assert [args for uri, args, _ in task.calls if uri.endswith('setReference')] == [
        {'object': FIRST, 'reference': 'PlaylistObject', 'value': SECOND}]


def preview_and_confirm(task):
    code, checked = task.step('draft-check')
    assert code == 0, checked
    code, preview = task.step('preview-from-draft')
    assert code == 0, preview
    tx = preview['transaction_id']
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    assert list(preview)[-1] == 'agent_result'
    return tx


def writes(task):
    return [(uri, args) for uri, args, _ in task.calls if uri.endswith(('setReference', 'setProperty', 'object.set', 'setName', 'setNotes'))]


def damage(task, change):
    if change == 'source-class':
        task.objects[FIRST]['classId'] = 1
    elif change == 'source-name':
        task.objects[FIRST]['name'] = 'Unexpected'
    elif change == 'source-owner':
        task.objects[FIRST]['owner'] = {'id': SECOND}
    elif change == 'source-parent':
        task.objects[FIRST]['parent'] = {'id': OWNER}
    elif change == 'source-path':
        task.objects[FIRST]['path'] += 'unexpected'
    elif change == 'target-class':
        task.objects[SECOND]['classId'] = 589840
    elif change == 'target-parent':
        task.objects[SECOND]['parent'] = {'id': PEER}
    elif change == 'owner-class':
        task.objects[OWNER]['classId'] = 65552
    elif change == 'owner-parent':
        task.objects[OWNER]['parent'] = {'id': SECOND}
    elif change == 'list-order':
        task.objects[OWNER]['@Playlist'].reverse()
    elif change == 'list-membership':
        task.objects[OWNER]['@Playlist'] = [{'id': PEER}]
    elif change == 'peer-reference':
        task.objects[PEER]['PlaylistObject'] = {'id': OLD}
    elif change == 'peer-notes':
        task.objects[PEER]['notes'] = 'unexpected'
    elif change == 'metadata':
        task.metadata['PlaylistObject']['restriction']['restrictions'].remove('mustChildOf')
    else:
        raise AssertionError(change)


@pytest.mark.parametrize('change', ['source-class', 'source-name', 'source-owner', 'source-parent', 'source-path',
    'target-class', 'target-parent', 'owner-class', 'owner-parent', 'list-order', 'list-membership', 'peer-reference', 'peer-notes', 'metadata'])
@pytest.mark.parametrize('stage', ['before-execute', 'after-execute'])
def test_playlist_preview_rejects_material_drift_and_never_retries(tmp_path, change, stage):
    task = PlaylistTask(tmp_path)
    task.declare_playlist()
    tx = preview_and_confirm(task)
    if stage == 'after-execute':
        code, executed = task.run('execute', tx)
        assert code == 0, executed
    damage(task, change)
    before = deepcopy(task.objects)
    code, result = task.run('execute' if stage == 'before-execute' else 'verify', tx)
    assert code == 2, result
    assert task.objects == before
    assert len(writes(task)) == (0 if stage == 'before-execute' else 1)
    code, replay = task.run('execute', tx)
    assert code == 2, replay
    assert len(writes(task)) == (0 if stage == 'before-execute' else 1)


@pytest.mark.parametrize('class_id', [None, True, 1, 5505040])
def test_unrelated_unnamed_plugin_inner_objects_do_not_gain_playlist_identity(tmp_path, class_id):
    task = PlaylistTask(tmp_path)
    if class_id is None:
        del task.objects[FIRST]['classId']
    else:
        task.objects[FIRST]['classId'] = class_id
    code, result = task.step('draft-bind-object', '--object-id', FIRST)
    assert code == 2 and result['error_code'] == 'BUSINESS_OBJECT_BINDING_MISMATCH', result
    assert writes(task) == []


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1', '2024.1'])
def test_playlist_slot_identity_does_not_claim_older_list_implementations(tmp_path, version):
    task = PlaylistTask(tmp_path, version)
    code, result = task.step('draft-bind-object', '--object-id', FIRST)
    assert code == 2, result
    assert writes(task) == []


def test_playlist_reference_cannot_be_cleared_when_native_metadata_requires_a_target(tmp_path):
    task = PlaylistTask(tmp_path)
    source = task.bind(FIRST)
    field = task.discover(source, 'Playlist Object')
    code, declared = task.step('draft-declare-field-change', '--object-handle', source,
        '--field-handle', field, '--clear-reference')
    assert code == 0, declared
    code, result = task.step('draft-check')
    assert code == 2 and 'REFERENCE_NOT_CLEARABLE' in json.dumps(result), result
    assert writes(task) == []


@pytest.mark.parametrize('shape', ['reference-only', 'reference-and-notes', 'notes-only'])
@pytest.mark.parametrize('policy', ['read_only', 'ask_before_changes', 'allow_changes'])
def test_direct_playlist_object_set_is_rejected_before_preview_without_writes(tmp_path, shape, policy):
    task = PlaylistTask(tmp_path, operation='object.set')
    code, configured = task.run('config-set', '--project-modification-policy', policy)
    assert code == 0, configured
    before = deepcopy(task.objects)
    source = task.bind(FIRST)
    fields = []
    if shape != 'notes-only':
        target = task.bind(SECOND)
        field = task.discover(source, 'Playlist Object')
        fields.extend(['--field-value', field, target])
    if shape != 'reference-only':
        fields.extend(['--field', 'notes', 'Requested playlist notes'])
    code, declared = task.step('draft-declare-existing', '--declaration-id', 'slot',
        '--object-handle', source, *fields)
    assert code == 0, declared
    code, result = task.step('draft-check')
    assert code == 2 and 'PLAYLIST_SLOT_OBJECT_SET_UNPROVEN' in json.dumps(result), result
    diagnostic = json.dumps(result)
    assert 'object.setReference' in diagnostic and 'object.setNotes' in diagnostic
    assert 'separately previewed and authorized' in diagnostic and '2025.1.7.9143' in diagnostic
    assert 'objectType' in diagnostic and '50' in diagnostic
    assert 'transaction_id' not in result
    assert task.objects == before and writes(task) == []


@pytest.mark.parametrize('case', ['wrong-class', 'wrong-parent', 'missing-owner', 'absent-member', 'overflow', 'unknown-flag'])
def test_invalid_playlist_reference_is_rejected_before_preview(tmp_path, case):
    task = PlaylistTask(tmp_path)
    task.declare_playlist()
    if case == 'wrong-class':
        task.objects[SECOND]['classId'] = 589840
    elif case == 'wrong-parent':
        task.objects[SECOND]['parent'] = {'id': PEER}
    elif case == 'missing-owner':
        del task.objects[FIRST]['owner']
    elif case == 'absent-member':
        task.objects[OWNER]['@Playlist'] = [{'id': PEER}]
    elif case == 'overflow':
        task.objects[OWNER]['@Playlist'] = [{'id': FIRST}] * 129
    else:
        task.metadata['PlaylistObject']['restriction']['restrictions'].append('unknown')
    before = deepcopy(task.objects)
    code, result = task.step('draft-check')
    assert code == 2, result
    assert task.objects == before and writes(task) == []


@pytest.mark.parametrize('policy', ['read_only', 'ask_before_changes', 'allow_changes'])
def test_playlist_reference_retains_each_modification_policy(tmp_path, policy):
    task = PlaylistTask(tmp_path)
    code, configured = task.run('config-set', '--project-modification-policy', policy)
    assert code == 0, configured
    task.declare_playlist()
    code, checked = task.step('draft-check')
    assert code == 0, checked
    code, preview = task.step('preview-from-draft', *(['--apply'] if policy == 'allow_changes' else []))
    if policy == 'read_only':
        # Read-only policy can retain an unexecuted Preview, but never writes.
        if code == 0:
            code, rejected = task.run('execute', preview['transaction_id'])
            assert code == 2, rejected
        assert writes(task) == []
        return
    assert code == 0, preview
    tx = preview['transaction_id']
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    if policy == 'ask_before_changes':
        code, rejected = task.run('execute', tx)
        assert code == 2 and writes(task) == [], rejected
        code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
        assert code == 0, confirmed
    else:
        assert shown['authorization']['mode'] == 'policy_authorization'
    code, executed = task.run('execute', tx)
    assert code == 0, executed
    code, verified = task.run('verify', tx)
    assert code == 0 and verified['verified'] is True, verified
    assert len(writes(task)) == 1


class InnerRenameTask(PlaylistTask):
    """A controlled native name outcome, not evidence that Wwise supports it."""

    def __init__(self, path, *, fault=None, kind='PlaylistSlot', operation='object.setName'):
        super().__init__(path, operation=operation)
        self.fault = fault
        if kind == 'MetadataSlot':
            self.types.extend([{'classId': 5570560, 'name': 'MetadataSlot', 'type': 'Inner'},
                {'classId': 58982409, 'name': 'Wwise System Output Settings', 'type': 'Metadata'}])
            self.objects[OWNER]['@Metadata'] = self.objects[OWNER].pop('@Playlist')
            for identity in (FIRST, PEER):
                row = self.objects[identity]
                row['classId'] = 5570560
                row['@Metadata'] = [row.pop('PlaylistObject')]
            for identity in (OLD, SECOND):
                self.objects[identity].update(type='Metadata', classId=58982409)
        else:
            assert kind == 'PlaylistSlot'

    def call(self, uri, args=None, options=None):
        if uri.endswith('setName'):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            if self.fault == 'native-rejection':
                from tests.unit.test_debug_read_gateway import WaapiRequestFailed
                raise WaapiRequestFailed('ak.wwise.invalid_arguments', {'message': 'Controlled native rename rejection'})
            if self.fault != 'native-no-effect':
                self.objects[args['object']]['name'] = args['value']
            return {}
        return super().call(uri, args, options)


@pytest.mark.parametrize('initial_name', ['', 'PreviouslyNamed'])
def test_observed_playlist_slot_rename_rejection_is_a_prewrite_boundary(tmp_path, initial_name):
    task = InnerRenameTask(tmp_path)
    task.objects[FIRST]['name'] = initial_name
    before = deepcopy(task.objects)
    task.bind(FIRST)
    code, declared = task.step('draft-declare-object-change', '--new-name', 'RenamedSlot')
    assert code == 0, declared
    code, rejected = task.step('draft-check')
    assert code == 2 and 'PLAYLIST_SLOT_RENAME_NATIVE_BOUNDARY' in json.dumps(rejected), rejected
    diagnostic = json.dumps(rejected)
    assert "Can't rename this object." in diagnostic and '2025.1.7.9143' in diagnostic
    assert 'other hosts and builds remain unobserved' in diagnostic
    assert 'transaction_id' not in rejected and writes(task) == [] and task.objects == before


def test_playlist_name_boundary_discloses_original_native_rejection_without_regrading_it(tmp_path):
    task = InnerRenameTask(tmp_path)
    code, schema = task.run('--version', '2025.1', 'operation-schema', 'object.setName')
    assert code == 0, schema
    boundary, = schema['business_adapter']['native_name_limitations']
    assert boundary['class_id'] == 5636096 and boundary['observed_native_build'] == '2025.1.7.9143'
    assert boundary['observed_host'] == 'wwise-console' and boundary['native_message'] == "Can't rename this object."
    assert 'MetadataSlot class 5570560' in boundary['unobserved_contexts']
    assert boundary['observation']['original_verdict'] == 'FAIL'
    assert boundary['observation']['original_transaction_state'] == 'indeterminate'
    assert boundary['observation']['observation_sha256'] == '5e897cd2a0232c5058d0327fa1682a972880145fe4b5c6072c20b4b832fc0f63'
    assert boundary['preserved_outcomes'][:2] == ['object.setNotes', 'object.setReference']
    assert task.calls == []


@pytest.mark.parametrize('kind', ['MetadataSlot'])
def test_existing_inner_slot_rename_verifies_actual_name_and_preserves_owner_list_and_references(tmp_path, kind):
    task = InnerRenameTask(tmp_path, kind=kind)
    before = deepcopy(task.objects)
    task.bind(FIRST)
    code, declared = task.step('draft-declare-object-change', '--new-name', 'RenamedSlot')
    assert code == 0, declared
    preview, _, verified, tx = finish(task)
    assert preview['change_requested'] is True and verified['verified'] is True
    assert task.objects == {**before, FIRST: {**before[FIRST], 'name': 'RenamedSlot'}}
    assert writes(task) == [('ak.wwise.core.object.setName', {'object': FIRST, 'value': 'RenamedSlot'})]
    assert task.run('execute', tx)[0] == 2
    assert len(writes(task)) == 1


@pytest.mark.parametrize('fault', ['native-rejection', 'native-no-effect'])
def test_inner_rename_never_claims_success_or_retries_after_native_rejection_or_no_effect(tmp_path, fault):
    task = InnerRenameTask(tmp_path, fault=fault, kind='MetadataSlot')
    before = deepcopy(task.objects)
    task.bind(FIRST)
    assert task.step('draft-declare-object-change', '--new-name', 'RenamedSlot')[0] == 0
    tx = preview_and_confirm(task)
    code, executed = task.run('execute', tx)
    assert code == (2 if fault == 'native-rejection' else 0), executed
    if fault == 'native-no-effect':
        code, verified = task.run('verify', tx)
        assert code == 2 and verified.get('verified') is not True, verified
        assert any(row['name'] == 'new name matches' and row['passed'] is False
            for row in verified['verification']['assertions']), verified
    else:
        assert executed['automatic_retry'] is False, executed
    assert task.objects == before and len(writes(task)) == 1
    assert task.run('execute', tx)[0] == 2
    assert len(writes(task)) == 1


@pytest.mark.parametrize('change', ['source-class', 'source-owner', 'list-order', 'peer-reference', 'target-class'])
@pytest.mark.parametrize('stage', ['before-execute', 'after-execute'])
def test_inner_rename_retains_exact_identity_owner_peers_and_references(tmp_path, change, stage):
    task = InnerRenameTask(tmp_path, kind='MetadataSlot')
    task.bind(FIRST)
    assert task.step('draft-declare-object-change', '--new-name', 'RenamedSlot')[0] == 0
    tx = preview_and_confirm(task)
    if stage == 'after-execute':
        assert task.run('execute', tx)[0] == 0
    if change == 'list-order':
        task.objects[OWNER]['@Metadata'].reverse()
    elif change == 'peer-reference':
        task.objects[PEER]['@Metadata'] = [{'id': OLD}]
    else:
        damage(task, change)
    code, result = task.run('execute' if stage == 'before-execute' else 'verify', tx)
    assert code == 2 and result.get('verified') is not True, result
    assert len(writes(task)) == (0 if stage == 'before-execute' else 1)
    assert task.run('execute', tx)[0] == 2
    assert len(writes(task)) == (0 if stage == 'before-execute' else 1)


@pytest.mark.parametrize('kind', ['PlaylistSlot', 'MetadataSlot'])
@pytest.mark.parametrize('initial_name', ['', 'PreviouslyNamed'])
def test_inner_graph_rename_requires_the_separately_scoped_public_name_workflow(tmp_path, kind, initial_name):
    task = InnerRenameTask(tmp_path, kind=kind, operation='object.set')
    task.objects[FIRST]['name'] = initial_name
    before = deepcopy(task.objects)
    source = task.bind(FIRST)
    code, rejected = task.step('draft-declare-existing', '--declaration-id', 'rename',
        '--object-handle', source, '--field', 'new_name', 'Renamed', '--field', 'notes', 'Requested notes')
    if code == 0:
        code, rejected = task.step('draft-check')
    assert code == 2 and 'INNER_GRAPH_RENAME_REQUIRES_SCOPED_OPERATION' in json.dumps(rejected), rejected
    diagnostic = json.dumps(rejected)
    assert 'object.setName' in diagnostic and 'separately previewed and authorized' in diagnostic
    assert 'native absence' in diagnostic and 'new_name' in diagnostic
    assert 'transaction_id' not in rejected
    assert writes(task) == [] and task.objects == before
    if kind == 'MetadataSlot' and initial_name == '':
        code, declared = task.step('draft-declare-existing', '--declaration-id', 'notes',
            '--object-handle', source, '--field', 'notes', 'Requested notes')
        assert code == 0, declared
        code, checked = task.step('draft-check')
        assert code == 0, checked
        assert writes(task) == [] and task.objects == before


@pytest.mark.parametrize('operation,identity,argv', [
    ('object.setName', SECOND, ['--new-name', 'Renamed']),
    ('object.setNotes', FIRST, ['--notes', 'Documented without renaming']),
])
def test_playlist_name_boundary_preserves_other_proven_lifecycle_previews(tmp_path, operation, identity, argv):
    task = PlaylistTask(tmp_path, operation=operation)
    before = deepcopy(task.objects)
    task.bind(identity)
    code, declared = task.step('draft-declare-object-change', *argv)
    assert code == 0, declared
    code, checked = task.step('draft-check')
    assert code == 0, checked
    code, preview = task.step('preview-from-draft')
    assert code == 0 and preview['change_requested'] is True, preview
    assert task.objects == before and writes(task) == []
