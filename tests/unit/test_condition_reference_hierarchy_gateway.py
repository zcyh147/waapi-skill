"""Source-grounded reference presence and exact group-parent target behavior.

Pinned XML and RPC schema establish this model; native instance/effect proof is
still required. No class or target hierarchy is inferred from a display name.
"""
from copy import deepcopy
import base64
import gzip
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from tests.unit.test_conditional_reference_gateway import ScalarPropertyTask, FIRST, SECOND, VERSIONS
from tests.unit.test_conditional_reference_gateway import AttenuationTask
from tests.unit.test_time_modulator_range_gateway import finish

GROUP = '{33333333-3333-3333-3333-333333333333}'
OTHER = '{44444444-4444-4444-4444-444444444444}'


def test_default_reference_model_retains_the_exact_five_version_source_rule():
    root = Path(__file__).parents[2]
    sources = json.loads(gzip.decompress((root / 'tests/fixtures/metadata-conditions/self-scalar-source-parents.json.gz').read_bytes()))
    versions = set()
    for key, document in sources['files'].items():
        if not key.endswith('|condition|WObjects/WObjects.xml'):
            continue
        raw = base64.b64decode(document['bytes_base64'])
        assert hashlib.sha256(raw).hexdigest() == document['sha256']
        definition = ET.fromstring(raw).find('./WwiseObject[@Name="SwitchContainer"]/Properties/Reference[@Name="DefaultSwitchOrState"]')
        dependency = definition.find('./Dependencies/ReferenceDependency')
        assert dependency.attrib == {'Name': 'SwitchGroupOrStateGroup', 'Action': 'Enable'}
        assert dependency.find('./Condition/ReferenceIsSet').attrib == {'Value': 'true'}
        assert definition.find('./Restrictions/IsChildOfReferenceRestriction/Reference').attrib == {'Name': 'SwitchGroupOrStateGroup'}
        assert {node.get('Name') for node in definition.findall('./Restrictions/TypeEnumerationRestriction/Type')} == {'Switch', 'State'}
        versions.add('.'.join(key.split('|')[0].split('.')[:2]))
    assert versions == set(VERSIONS)


class DefaultSwitchTask(ScalarPropertyTask):
    def __init__(self, path, version, *, parent=GROUP, operation='object.setReference'):
        super().__init__(path, version, operation=operation)
        self.metadata = {
            'DefaultSwitchOrState': {'name': 'DefaultSwitchOrState', 'type': '',
                'restriction': {'type': 'reference', 'restrictions': [
                    {'childOfReference': 'SwitchGroupOrStateGroup'}, {'type': ['Switch', 'State']}]},
                'dependencies': [{'type': 'reference', 'action': 'Enable', 'context': 'Self',
                    'property': 'SwitchGroupOrStateGroup', 'conditions': [{'referenceIsSet': True}]}]},
            'SwitchGroupOrStateGroup': {'name': 'SwitchGroupOrStateGroup', 'type': '',
                'restriction': {'type': 'reference', 'restrictions': [{'type': ['SwitchGroup', 'StateGroup']}]}}
        }
        self.objects[FIRST].update(type='SwitchContainer', DefaultSwitchOrState=None,
            SwitchGroupOrStateGroup={'id': GROUP})
        self.objects[SECOND].update(type='Switch', name='Concrete',
            path=r'\Switches\Default Work Unit\Surface\Concrete', parent={'id': parent})
        for identity, name in ((GROUP, 'Surface'), (OTHER, 'Weather')):
            self.objects[identity] = {'id': identity, 'name': name, 'type': 'SwitchGroup',
                'path': '\\Switches\\Default Work Unit\\' + name, 'parent': None}

    def declare_default(self):
        source, target = self.bind(FIRST), self.bind(SECOND)
        field = self.discover(source, 'DefaultSwitchOrState')
        code, declared = (self.step('draft-declare-field-change', '--object-handle', source,
            '--field-handle', field, '--target-handle', target) if self.operation == 'object.setReference' else
            self.step('draft-declare-existing', '--declaration-id', 'default-switch', '--object-handle', source,
                '--field-value', field, target))
        assert code == 0, declared


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('parent', [GROUP, OTHER])
def test_default_switch_target_must_belong_to_the_current_selected_group(tmp_path, version, parent):
    task = DefaultSwitchTask(tmp_path, version, parent=parent)
    before = deepcopy(task.objects)
    task.declare_default()
    code, checked = task.step('draft-check')
    if parent == OTHER:
        assert code == 2 and checked['error_code'] == 'INVALID_REFERENCE_TARGET', checked
        assert task.objects == before
        assert not any(uri.endswith(('setReference', 'setProperty', 'object.set')) for uri, _, _ in task.calls)
        return
    assert code == 0, checked
    preview, _, verified, _ = finish(task)
    assert verified['verified'] is True
    assert not preview['preview_summary'].get('derived_changes')
    assert task.objects == {**before, FIRST: {**before[FIRST], 'DefaultSwitchOrState': {'id': SECOND}}}
    assert [args for uri, args, _ in task.calls if uri.endswith('setReference')] == [
        {'object': FIRST, 'reference': 'DefaultSwitchOrState', 'value': SECOND}]


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('drift', ['group-before', 'parent-before', 'group-after', 'parent-after', 'metadata-before'])
def test_default_switch_parent_scope_is_guarded_and_verified(tmp_path, version, drift):
    task = DefaultSwitchTask(tmp_path, version)
    task.declare_default()
    code, checked = task.step('draft-check')
    assert code == 0, checked
    code, preview = task.step('preview-from-draft')
    assert code == 0, preview
    tx = preview['transaction_id']
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    def change():
        if drift.startswith('group'):
            task.objects[FIRST]['SwitchGroupOrStateGroup'] = {'id': OTHER}
        elif drift.startswith('parent'):
            task.objects[SECOND]['parent'] = {'id': OTHER}
        else:
            task.metadata['SwitchGroupOrStateGroup']['restriction']['restrictions'][0]['type'].append('Switch')
    if drift.endswith('before'):
        change()
    code, executed = task.run('execute', tx)
    if drift.endswith('before'):
        assert code == 2, executed
        assert not any(uri.endswith(('setReference', 'setProperty', 'object.set')) for uri, _, _ in task.calls)
        return
    assert code == 0, executed
    change()
    code, verified = task.run('verify', tx)
    assert code == 2 and verified.get('verified') is not True, verified


@pytest.mark.parametrize('version', VERSIONS)
def test_missing_group_has_a_usable_explicit_reference_repair(tmp_path, version):
    from tests.unit.test_time_modulator_range_gateway import start
    task = DefaultSwitchTask(tmp_path, version)
    task.objects[FIRST]['SwitchGroupOrStateGroup'] = None
    task.declare_default()
    original = task.draft, task.authority, task.revision
    code, checked = task.step('draft-check')
    assert code == 2 and checked['error_code'] == 'REFERENCE_ACTIVATION_REQUIRED', checked
    repair = checked['details']['prerequisite_changes'][0]
    assert repair['operation'] == 'object.setReference' and repair['required_presence'] is True
    assert repair['discovery_meaning'] == 'SwitchGroupOrStateGroup'
    assert not any(uri.endswith(('setReference', 'object.set')) for uri, _, _ in task.calls)
    start(task)
    source, selected_group = task.bind(FIRST), task.bind(GROUP)
    field = task.discover(source, repair['discovery_meaning'])
    code, declared = task.step('draft-declare-field-change', '--object-handle', source,
        '--field-handle', field, '--target-handle', selected_group)
    assert code == 0, declared
    finish(task)
    task.draft, task.authority, task.revision = original
    finish(task)
    assert task.objects[FIRST]['SwitchGroupOrStateGroup'] == {'id': GROUP}
    assert task.objects[FIRST]['DefaultSwitchOrState'] == {'id': SECOND}
    assert [args for uri, args, _ in task.calls if uri.endswith('setReference')] == [
        {'object': FIRST, 'reference': 'SwitchGroupOrStateGroup', 'value': GROUP},
        {'object': FIRST, 'reference': 'DefaultSwitchOrState', 'value': SECOND}]


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('rule', ['cycle', 'conflict'])
def test_cyclic_or_conflicting_reference_parent_rules_are_closed(tmp_path, version, rule):
    task = DefaultSwitchTask(tmp_path, version)
    if rule == 'cycle':
        task.metadata['SwitchGroupOrStateGroup']['restriction']['restrictions'].append({'childOfReference': 'DefaultSwitchOrState'})
    else:
        task.metadata['OtherGroup'] = deepcopy(task.metadata['SwitchGroupOrStateGroup'])
        task.metadata['OtherGroup']['name'] = 'OtherGroup'
        task.objects[FIRST]['OtherGroup'] = {'id': OTHER}
        task.metadata['DefaultSwitchOrState']['restriction']['restrictions'].append({'childOfReference': 'OtherGroup'})
    task.declare_default()
    code, checked = task.step('draft-check')
    expected = {'REFERENCE_DEPENDENCY_CYCLE', 'CONSTRAINED_REFERENCE_BOUNDARY'} if rule == 'cycle' else {'INVALID_REFERENCE_TARGET'}
    assert code == 2 and checked['error_code'] in expected, json.dumps(checked)
    assert not any(uri.endswith(('setReference', 'object.set')) for uri, _, _ in task.calls)


@pytest.mark.parametrize('version', VERSIONS[1:])
@pytest.mark.parametrize('parent', [GROUP, OTHER])
@pytest.mark.parametrize('reverse', [False, True])
def test_atomic_group_and_default_reference_use_the_explicit_staged_parent(tmp_path, version, parent, reverse):
    task = DefaultSwitchTask(tmp_path, version, parent=parent, operation='object.set')
    task.objects[FIRST]['SwitchGroupOrStateGroup'] = {'id': OTHER}
    source, selected, group = task.bind(FIRST), task.bind(SECOND), task.bind(GROUP)
    default_field = task.discover(source, 'DefaultSwitchOrState')
    group_field = task.discover(source, 'SwitchGroupOrStateGroup')
    values = [(default_field, selected), (group_field, group)]
    if reverse:
        values.reverse()
    fields = [token for field, target in values for token in ('--field-value', field, target)]
    code, declared = task.step('draft-declare-existing', '--declaration-id', 'switch-group-and-default',
        '--object-handle', source, *fields)
    assert code == 0, declared
    code, checked = task.step('draft-check')
    if parent == OTHER:
        assert code == 2, checked
        assert not any(uri.endswith(('setReference', 'object.set')) for uri, _, _ in task.calls)
        return
    assert code == 0, checked
    _, _, verified, _ = finish(task)
    assert verified['verified'] is True
    assert task.objects[FIRST]['SwitchGroupOrStateGroup'] == {'id': GROUP}
    assert task.objects[FIRST]['DefaultSwitchOrState'] == {'id': SECOND}
    writes = [args for uri, args, _ in task.calls if uri.endswith('object.set')]
    assert len(writes) == 1
    assert writes[0]['objects'][0]['@SwitchGroupOrStateGroup'] == GROUP
    assert writes[0]['objects'][0]['@DefaultSwitchOrState'] == SECOND


@pytest.mark.parametrize('version,rows', [
    *((version, [{'type': ['Attenuation'], 'sharedOnlyTypes': ['Attenuation']}]) for version in VERSIONS[1:]),
    *((version, [{'type': ['Attenuation']}, {'category': ['UnclassifiedNativeCategory']}]) for version in VERSIONS),
    ('2025.1', [{'type': ['Attenuation']}, 'mustChildOf']),
])
def test_unclassified_native_target_constraint_is_a_closed_boundary(tmp_path, version, rows):
    task = AttenuationTask(tmp_path, version, operation='object.setReference')
    task.objects[FIRST].update(ListenerRelativeRouting=True, OverridePositioning=True)
    task.metadata['Attenuation']['restriction']['restrictions'] = deepcopy(rows)
    if 'mustChildOf' in rows:
        source = task.bind(FIRST)
        code, discovered = task.step('draft-discover-fields', '--object-handle', source, '--meaning', 'Attenuation')
        assert code == 2 and 'CONSTRAINED_REFERENCE_BOUNDARY' in json.dumps(discovered), discovered
        assert 'INVALID_METADATA' not in json.dumps(discovered), discovered
        return
    task.declare()
    code, checked = task.step('draft-check')
    assert code == 2 and checked['error_code'] == 'CONSTRAINED_REFERENCE_BOUNDARY', json.dumps(checked)
    assert not any(uri.endswith(('setReference', 'setProperty', 'object.set')) for uri, _, _ in task.calls)


@pytest.mark.parametrize('version', VERSIONS[1:])
@pytest.mark.parametrize('shared_only', [[], ['Effect']])
def test_empty_or_inapplicable_shared_only_subset_preserves_valid_targets(tmp_path, version, shared_only):
    task = AttenuationTask(tmp_path, version, operation='object.setReference')
    task.objects[FIRST].update(ListenerRelativeRouting=True, OverridePositioning=True)
    task.metadata['Attenuation']['restriction']['restrictions'] = [
        {'type': ['Attenuation', 'Effect'], 'sharedOnlyTypes': shared_only}]
    task.declare()
    _, _, verified, _ = finish(task)
    assert verified['verified'] is True


@pytest.mark.parametrize('row', [
    {'type': None},
    {'type': ['Attenuation'], 'sharedOnlyTypes': 'Attenuation'},
    {'type': ['Attenuation'], 'sharedOnlyTypes': ['Effect']},
    {'type': ['Attenuation'], 'unknown': []},
    {'unknown': []},
])
def test_malformed_reference_constraint_cannot_become_an_unrestricted_target(tmp_path, row):
    task = AttenuationTask(tmp_path, '2025.1', operation='object.setReference')
    task.objects[FIRST].update(ListenerRelativeRouting=True, OverridePositioning=True)
    task.metadata['Attenuation']['restriction']['restrictions'] = [row]
    task.declare()
    code, checked = task.step('draft-check')
    assert code == 2 and checked['error_code'] == 'INVALID_METADATA', checked
    assert not any(uri.endswith(('setReference', 'setProperty', 'object.set')) for uri, _, _ in task.calls)


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('classifier,value,accepted', [
    ('category', 'RecordedCategory', True), ('category', 'OtherCategory', False),
    ('isPlayable', True, True), ('isPlayable', False, False),
])
def test_native_target_classifier_controls_the_selected_reference(tmp_path, version, classifier, value, accepted):
    """RPC schema model; effective instance metadata/native effects remain unverified."""
    task = AttenuationTask(tmp_path, version, operation='object.setReference')
    task.objects[FIRST].update(ListenerRelativeRouting=True, OverridePositioning=True)
    task.objects[SECOND][classifier] = value
    rows = [{'category': ['RecordedCategory']}] if classifier == 'category' else ['playable']
    task.metadata['Attenuation']['restriction']['restrictions'] = rows
    task.declare()
    code, checked = task.step('draft-check')
    if not accepted:
        assert code == 2 and checked['error_code'] == 'INVALID_REFERENCE_TARGET', checked
        assert not any(uri.endswith(('setReference', 'setProperty', 'object.set')) for uri, _, _ in task.calls)
        return
    assert code == 0, checked
    _, _, verified, _ = finish(task)
    assert verified['verified'] is True
    assert task.objects[FIRST]['Attenuation'] == {'id': SECOND}
    reads = [(args, options) for uri, args, options in task.calls if uri.endswith('object.get')
             and classifier in options.get('return', [])]
    assert reads and all(args == {'from': {'id': [SECOND]}} for args, _ in reads)


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('classifier,initial,changed', [('category', 'RecordedCategory', 'OtherCategory'),
                                                      ('isPlayable', True, False)])
@pytest.mark.parametrize('phase', ['before', 'after'])
def test_native_target_classifier_is_revalidated_and_verified(tmp_path, version, classifier, initial, changed, phase):
    task = AttenuationTask(tmp_path, version, operation='object.setReference')
    task.objects[FIRST].update(ListenerRelativeRouting=True, OverridePositioning=True)
    task.objects[SECOND][classifier] = initial
    task.metadata['Attenuation']['restriction']['restrictions'] = (
        [{'category': ['RecordedCategory']}] if classifier == 'category' else ['playable'])
    task.declare()
    code, checked = task.step('draft-check')
    assert code == 0, checked
    code, preview = task.step('preview-from-draft')
    assert code == 0, preview
    tx = preview['transaction_id']
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    if phase == 'before':
        task.objects[SECOND][classifier] = changed
    code, executed = task.run('execute', tx)
    if phase == 'before':
        assert code == 2, executed
        assert not any(uri.endswith(('setReference', 'setProperty', 'object.set')) for uri, _, _ in task.calls)
        return
    assert code == 0, executed
    task.objects[SECOND][classifier] = changed
    code, verified = task.run('verify', tx)
    assert code == 2 and verified.get('verified') is not True, verified


@pytest.mark.parametrize('version', VERSIONS)
def test_target_classifier_accessors_are_declared_by_the_exact_version(version):
    root = Path(__file__).parents[2]
    definitions = json.loads((root / 'skills/waapi-skill/resources/manifest' / version / 'definitions.json').read_text())
    properties = definitions['documents']['waapi_definitions.json']['definitions']['objectReturn']['properties']
    assert properties['category']['type'] == 'string'
    assert properties['isPlayable']['type'] == 'boolean'
    assert 'isShared' not in properties


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('classifier,value', [('category', None), ('category', True), ('category', '__missing__'),
                                              ('isPlayable', None), ('isPlayable', 1), ('isPlayable', '__missing__')])
def test_unavailable_or_malformed_target_classifier_cannot_authorize_a_write(tmp_path, version, classifier, value):
    task = AttenuationTask(tmp_path, version, operation='object.setReference')
    task.objects[FIRST].update(ListenerRelativeRouting=True, OverridePositioning=True)
    if value != '__missing__':
        task.objects[SECOND][classifier] = value
    task.metadata['Attenuation']['restriction']['restrictions'] = (
        [{'category': ['RecordedCategory']}] if classifier == 'category' else ['playable'])
    task.declare()
    code, checked = task.step('draft-check')
    expected = 'CONSTRAINED_REFERENCE_BOUNDARY' if value == '__missing__' else 'INVALID_READBACK'
    assert code == 2 and checked['error_code'] == expected, checked
    assert not any(uri.endswith(('setReference', 'setProperty', 'object.set')) for uri, _, _ in task.calls)


@pytest.mark.parametrize('version', VERSIONS[1:])
@pytest.mark.parametrize('classifier,value', [('category', 'RecordedCategory'), ('isPlayable', True)])
def test_atomic_reference_assignment_retains_native_classifier_guards(tmp_path, version, classifier, value):
    task = AttenuationTask(tmp_path, version, operation='object.set')
    task.objects[FIRST].update(ListenerRelativeRouting=True, OverridePositioning=True)
    task.objects[SECOND][classifier] = value
    task.metadata['Attenuation']['restriction']['restrictions'] = (
        [{'category': ['RecordedCategory']}] if classifier == 'category' else ['playable'])
    task.declare()
    _, _, verified, _ = finish(task)
    assert verified['verified'] is True
    assert task.objects[FIRST]['Attenuation'] == {'id': SECOND}


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('matched', ['type', 'category'])
def test_mixed_type_category_admission_semantics_are_not_guessed(tmp_path, version, matched):
    task = AttenuationTask(tmp_path, version, operation='object.setReference')
    task.objects[FIRST].update(ListenerRelativeRouting=True, OverridePositioning=True)
    task.objects[SECOND]['category'] = 'RecordedCategory' if matched == 'category' else 'OtherCategory'
    task.metadata['Attenuation']['restriction']['restrictions'] = [
        {'type': ['Attenuation' if matched == 'type' else 'Effect']}, {'category': ['RecordedCategory']}]
    task.declare()
    code, checked = task.step('draft-check')
    assert code == 2 and checked['error_code'] == 'CONSTRAINED_REFERENCE_BOUNDARY', checked
    assert not any(uri.endswith(('setReference', 'setProperty', 'object.set')) for uri, _, _ in task.calls)


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('shape', ['mixed', 'repeated-category'])
def test_every_disclosed_target_row_can_be_satisfied_without_boolean_combination_guessing(tmp_path, version, shape):
    task = _joint_classifier_task(tmp_path, version, shape)
    task.declare()
    start = len(task.calls)
    code, checked = task.step('draft-check')
    assert code == 0, checked
    classifiers = [(args, options) for uri, args, options in task.calls[start:]
                   if uri.endswith('object.get') and 'category' in options.get('return', [])]
    assert len(classifiers) == 1
    assert classifiers[0][0] == {'from': {'id': [SECOND]}}
    assert classifiers[0][1]['return'] == (['id', 'type', 'category'] if shape == 'mixed' else ['id', 'category'])
    before = deepcopy(task.objects)
    preview, _, verified, _ = finish(task)
    assert verified['verified'] is True
    assert not preview['preview_summary'].get('derived_changes')
    assert task.objects == {**before, FIRST: {**before[FIRST], 'Attenuation': {'id': SECOND}}}
    writes = [args for uri, args, _ in task.calls if uri.endswith(('setReference', 'setProperty', 'object.set'))]
    assert writes == [{'object': FIRST, 'reference': 'Attenuation', 'value': SECOND}]


def _joint_classifier_task(path, version, shape, operation='object.setReference'):
    task = AttenuationTask(path, version, operation=operation)
    task.objects[FIRST].update(ListenerRelativeRouting=True, OverridePositioning=True)
    task.objects[SECOND]['category'] = 'RecordedCategory'
    task.metadata['Attenuation']['restriction']['restrictions'] = (
        [{'type': ['Attenuation', 'Effect']}, {'category': ['RecordedCategory', 'OtherCategory']}]
        if shape == 'mixed' else
        [{'category': ['RecordedCategory', 'FirstCategory']}, {'category': ['SecondCategory', 'RecordedCategory']}])
    return task


@pytest.mark.parametrize('version', VERSIONS[1:])
@pytest.mark.parametrize('shape', ['mixed', 'repeated-category'])
def test_atomic_reference_edit_can_satisfy_every_disclosed_target_row(tmp_path, version, shape):
    task = _joint_classifier_task(tmp_path, version, shape, operation='object.set')
    task.metadata['Attenuation']['restriction']['restrictions'].reverse()
    task.declare()
    preview, _, verified, _ = finish(task)
    assert verified['verified'] is True
    assert not preview['preview_summary'].get('derived_changes')
    assert task.objects[FIRST]['Attenuation'] == {'id': SECOND}
    writes = [row for row in task.calls if row[0].endswith(('setReference', 'setProperty', 'object.set'))]
    assert len(writes) == 1 and writes[0][0].endswith('object.set')


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('category', ['FirstCategory', 'SecondCategory'])
def test_partial_repeated_category_matches_remain_an_explicit_native_question(tmp_path, version, category):
    task = _joint_classifier_task(tmp_path, version, 'repeated-category')
    task.objects[SECOND]['category'] = category
    task.declare()
    code, checked = task.step('draft-check')
    assert code == 2 and checked['error_code'] == 'CONSTRAINED_REFERENCE_BOUNDARY', checked
    assert not any(uri.endswith(('setReference', 'setProperty', 'object.set')) for uri, _, _ in task.calls)


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('shape', ['mixed', 'repeated-category'])
@pytest.mark.parametrize('drift', ['category', 'raw-metadata'])
@pytest.mark.parametrize('phase', ['before', 'after'])
def test_joint_classifier_and_raw_metadata_drift_cannot_write_or_report_success(tmp_path, version, shape, drift, phase):
    from wwise_waapi.transactions import TransactionStore, TransactionState
    task = _joint_classifier_task(tmp_path, version, shape)
    task.declare()
    code, checked = task.step('draft-check')
    assert code == 0, checked
    code, preview = task.step('preview-from-draft')
    assert code == 0, preview
    tx = preview['transaction_id']
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    def change():
        if drift == 'category':
            task.objects[SECOND]['category'] = 'UnmatchedCategory'
        else:
            # Every membership still holds; only the sealed raw row order changes.
            task.metadata['Attenuation']['restriction']['restrictions'].reverse()
    if phase == 'before':
        change()
    code, executed = task.run('execute', tx)
    if phase == 'before':
        assert code == 2, executed
        assert not any(uri.endswith(('setReference', 'setProperty', 'object.set')) for uri, _, _ in task.calls)
        return
    assert code == 0, executed
    change()
    code, verified = task.run('verify', tx)
    assert code == 2 and verified['state'] == 'verification_failed', verified
    assert verified['automatic_retry'] is False
    store = TransactionStore(task.path / 'state')
    assert store.load(tx).state is TransactionState.VERIFICATION_FAILED
    assert store.read_events(tx)[-1]['event_type'] == 'verification_recorded'
    code, repeated = task.run('execute', tx)
    assert code == 2, repeated
    assert len([row for row in task.calls if row[0].endswith(('setReference', 'setProperty', 'object.set'))]) == 1


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('damage', ['missing-type', 'malformed-category', 'transport'])
def test_unavailable_joint_classifier_postread_remains_unknown_without_second_write(tmp_path, version, damage):
    from wwise_waapi.transactions import TransactionStore, TransactionState
    task = _joint_classifier_task(tmp_path, version, 'mixed')
    tx = _execute_target_assignment(task)
    normal_call = task.call
    def call(uri, args=None, options=None):
        if uri.endswith('object.get') and 'category' in options.get('return', []):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            if damage == 'transport':
                raise RuntimeError('controlled classifier read unavailable')
            return {'return': [{'id': SECOND, 'category': 'RecordedCategory'}] if damage == 'missing-type'
                    else [{'id': SECOND, 'type': 'Attenuation', 'category': None}]}
        return normal_call(uri, args, options)
    task.call = call
    code, verified = task.run('verify', tx)
    assert code == 2 and verified['state'] == 'executed_unverified', verified
    assert verified['status'] == 'verification_deferred'
    assert verified['manual_verification_retry_allowed'] is True
    assert verified['automatic_retry'] is False
    store = TransactionStore(task.path / 'state')
    assert store.load(tx).state is TransactionState.EXECUTED_UNVERIFIED
    assert not any(event['event_type'] == 'verification_recorded' for event in store.read_events(tx))
    code, repeated = task.run('execute', tx)
    assert code == 2, repeated
    assert len([row for row in task.calls if row[0].endswith(('setReference', 'setProperty', 'object.set'))]) == 1


@pytest.mark.parametrize('version', VERSIONS)
def test_joint_classifier_type_fact_must_match_the_exact_bound_identity(tmp_path, version):
    task = _joint_classifier_task(tmp_path, version, 'mixed')
    task.declare()
    normal_call = task.call
    def call(uri, args=None, options=None):
        if uri.endswith('object.get') and 'category' in options.get('return', []):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': [{'id': SECOND, 'type': 'Effect', 'category': 'RecordedCategory'}]}
        return normal_call(uri, args, options)
    task.call = call
    code, checked = task.step('draft-check')
    assert code == 2 and checked['error_code'] == 'INVALID_READBACK', checked
    assert not any(uri.endswith(('setReference', 'setProperty', 'object.set')) for uri, _, _ in task.calls)


@pytest.mark.parametrize('version', VERSIONS)
def test_joint_classifier_exact_type_drift_is_known_false_even_when_new_type_is_allowed(tmp_path, version):
    from wwise_waapi.transactions import TransactionStore, TransactionState
    task = _joint_classifier_task(tmp_path, version, 'mixed')
    tx = _execute_target_assignment(task)
    task.objects[SECOND]['type'] = 'Effect'
    code, verified = task.run('verify', tx)
    assert code == 2 and verified['state'] == 'verification_failed', verified
    store = TransactionStore(task.path / 'state')
    assert store.load(tx).state is TransactionState.VERIFICATION_FAILED
    assert store.read_events(tx)[-1]['event_type'] == 'verification_recorded'
    code, repeated = task.run('execute', tx)
    assert code == 2, repeated
    assert len([row for row in task.calls if row[0].endswith(('setReference', 'setProperty', 'object.set'))]) == 1


@pytest.mark.parametrize('version', VERSIONS)
def test_joint_classifier_read_keeps_the_explicit_selected_platform(tmp_path, version):
    platform = '{77777777-7777-7777-7777-777777777777}'
    task = _joint_classifier_task(tmp_path, version, 'mixed')
    normal_call = task.call
    def call(uri, args=None, options=None):
        if uri.endswith('isPropertyEnabled'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': True}
        return normal_call(uri, args, options)
    task.call = call
    source, target = task.bind(FIRST), task.bind(SECOND)
    code, discovered = task.step('draft-discover-fields', '--object-handle', source,
        '--meaning', 'Attenuation', '--platform', platform)
    assert code == 0, discovered
    field = discovered['meaning_results'][0]['candidates'][0]['handle']
    code, declared = task.step('draft-declare-field-change', '--object-handle', source,
        '--field-handle', field, '--target-handle', target)
    assert code == 0, declared
    _, _, verified, _ = finish(task)
    assert verified['verified'] is True
    reads = [options for uri, args, options in task.calls if uri.endswith('object.get')
             and 'category' in options.get('return', [])]
    assert reads and all(len(options['return']) == 3 and set(options['return']) == {'id', 'type', 'category'}
                         and options['platform'] == platform for options in reads)


@pytest.mark.parametrize('version', VERSIONS[1:])
@pytest.mark.parametrize('shared', [False, True])
def test_joint_target_classifiers_keep_independent_playable_and_shared_only_rules(tmp_path, version, shared):
    task = SharedReferenceTask(tmp_path, version, shared=shared)
    task.objects[SECOND].update(category='RecordedCategory', isPlayable=True)
    task.metadata['Attenuation']['restriction']['restrictions'].extend([
        {'category': ['RecordedCategory']}, 'playable'])
    task.declare()
    code, checked = task.step('draft-check')
    if not shared:
        assert code == 2 and checked['error_code'] == 'INVALID_REFERENCE_TARGET', checked
        assert not any(uri.endswith(('setReference', 'setProperty', 'object.set')) for uri, _, _ in task.calls)
        return
    assert code == 0, checked
    _, _, verified, _ = finish(task)
    assert verified['verified'] is True
    assert len([row for row in task.calls if row[0].endswith(('setReference', 'setProperty', 'object.set'))]) == 1


@pytest.mark.parametrize('phase', ['before', 'after'])
def test_atomic_target_classifier_drift_cannot_verify_a_changed_target(tmp_path, phase):
    task = AttenuationTask(tmp_path, '2025.1', operation='object.set')
    task.objects[FIRST].update(ListenerRelativeRouting=True, OverridePositioning=True)
    task.objects[SECOND].update(category='RecordedCategory', isPlayable=True)
    task.metadata['Attenuation']['restriction']['restrictions'] = [{'category': ['RecordedCategory']}, 'playable']
    task.declare()
    code, checked = task.step('draft-check')
    assert code == 0, checked
    code, preview = task.step('preview-from-draft')
    assert code == 0, preview
    tx = preview['transaction_id']
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    if phase == 'before':
        task.objects[SECOND]['isPlayable'] = False
    code, executed = task.run('execute', tx)
    if phase == 'before':
        assert code == 2, executed
        assert not any(uri.endswith(('setReference', 'setProperty', 'object.set')) for uri, _, _ in task.calls)
        return
    assert code == 0, executed
    task.objects[SECOND]['category'] = 'OtherCategory'
    code, verified = task.run('verify', tx)
    assert code == 2 and verified.get('verified') is not True, verified


@pytest.mark.parametrize('invalid_rows', [[], [{'id': GROUP, 'category': 'RecordedCategory'}],
    [{'id': SECOND, 'category': 'RecordedCategory'}, {'id': SECOND, 'category': 'RecordedCategory'}]])
def test_target_classifier_read_requires_one_exact_selected_guid(tmp_path, invalid_rows):
    task = AttenuationTask(tmp_path, '2025.1', operation='object.setReference')
    task.objects[FIRST].update(ListenerRelativeRouting=True, OverridePositioning=True)
    task.metadata['Attenuation']['restriction']['restrictions'] = [{'category': ['RecordedCategory']}]
    normal_call = task.call
    def call(uri, args=None, options=None):
        if uri.endswith('object.get') and 'category' in options.get('return', []):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': invalid_rows}
        return normal_call(uri, args, options)
    task.call = call
    task.declare()
    code, checked = task.step('draft-check')
    assert code == 2 and checked['error_code'] == 'INVALID_READBACK', checked
    assert not any(uri.endswith(('setReference', 'setProperty', 'object.set')) for uri, _, _ in task.calls)


@pytest.mark.parametrize('version', VERSIONS)
def test_target_classifier_reads_keep_the_selected_platform_scope(tmp_path, version):
    task = AttenuationTask(tmp_path, version, operation='object.setReference')
    platform = '{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}'
    task.objects[FIRST].update(ListenerRelativeRouting=True, OverridePositioning=True)
    task.objects[SECOND]['category'] = 'RecordedCategory'
    task.metadata['Attenuation']['restriction']['restrictions'] = [{'category': ['RecordedCategory']}]
    normal_call = task.call
    def call(uri, args=None, options=None):
        if uri.endswith('isPropertyEnabled'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': True}
        return normal_call(uri, args, options)
    task.call = call
    source, target = task.bind(FIRST), task.bind(SECOND)
    code, discovered = task.step('draft-discover-fields', '--object-handle', source,
                                '--meaning', 'Attenuation', '--platform', platform)
    assert code == 0, discovered
    field = discovered['meaning_results'][0]['candidates'][0]['handle']
    code, declared = task.step('draft-declare-field-change', '--object-handle', source,
                              '--field-handle', field, '--target-handle', target)
    assert code == 0, declared
    _, _, verified, _ = finish(task)
    assert verified['verified'] is True
    reads = [options for uri, _, options in task.calls if uri.endswith('object.get') and 'category' in options.get('return', [])]
    assert reads and all(options['platform'] == platform for options in reads)


class SharedReferenceTask(AttenuationTask):
    """SDK relationship model; predicate outcome is independent of JSON omission."""
    def __init__(self, path, version, *, shared=True, operation='object.setReference'):
        super().__init__(path, version, operation=operation)
        self.shared = shared
        self.objects[FIRST].update(ListenerRelativeRouting=True, OverridePositioning=True)
        self.objects[SECOND]['parent'] = {'id': GROUP}
        self.metadata['Attenuation']['restriction']['restrictions'] = [
            {'type': ['Attenuation'], 'sharedOnlyTypes': ['Attenuation']}]

    def call(self, uri, args=None, options=None):
        expected = f'from object "{SECOND}" where owner = null take 1'
        if uri.endswith('object.get') and args.get('waql') == expected:
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert options['return'] == ['id']
            return {'return': [{'id': SECOND}] if self.shared else []}
        return super().call(uri, args, options)


@pytest.mark.parametrize('version', VERSIONS[1:])
@pytest.mark.parametrize('shared', [True, False])
def test_shared_only_target_uses_an_owned_native_predicate_not_owner_omission(tmp_path, version, shared):
    task = SharedReferenceTask(tmp_path, version, shared=shared)
    assert 'owner' not in task.objects[SECOND]
    task.declare()
    code, checked = task.step('draft-check')
    if not shared:
        assert code == 2 and checked['error_code'] == 'INVALID_REFERENCE_TARGET', checked
        assert not any(uri.endswith(('setReference', 'object.set')) for uri, _, _ in task.calls)
        return
    assert code == 0, checked
    _, _, verified, _ = finish(task)
    assert verified['verified'] is True
    assert task.objects[FIRST]['Attenuation'] == {'id': SECOND}


@pytest.mark.parametrize('version', VERSIONS[1:])
@pytest.mark.parametrize('drift', ['owner-before', 'parent-before', 'owner-after', 'parent-after'])
def test_shared_only_owner_predicate_and_parent_are_guarded_through_verification(tmp_path, version, drift):
    task = SharedReferenceTask(tmp_path, version)
    task.declare()
    code, checked = task.step('draft-check')
    assert code == 0, checked
    code, preview = task.step('preview-from-draft')
    assert code == 0, preview
    tx = preview['transaction_id']
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    def change():
        if drift.startswith('owner'):
            task.shared = False
        else:
            task.objects[SECOND]['parent'] = {'id': OTHER}
    if drift.endswith('before'):
        change()
    code, executed = task.run('execute', tx)
    if drift.endswith('before'):
        assert code == 2, executed
        assert not any(uri.endswith(('setReference', 'object.set')) for uri, _, _ in task.calls)
        return
    assert code == 0, executed
    change()
    code, verified = task.run('verify', tx)
    assert code == 2 and verified.get('verified') is not True, verified


@pytest.mark.parametrize('response', [None, [], {}, {'return': None}, {'return': [7]}, {'return': [{}]},
    {'return': [{'id': GROUP}]}, {'return': [{'id': SECOND}, {'id': SECOND}]},
    {'return': [{'id': SECOND}, {'id': GROUP}]}])
def test_shared_only_predicate_rejects_malformed_duplicate_extra_or_wrong_identity(tmp_path, response):
    task = SharedReferenceTask(tmp_path, '2025.1')
    normal_call = task.call
    def call(uri, args=None, options=None):
        if uri.endswith('object.get') and args.get('waql', '').endswith('where owner = null take 1'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return response
        return normal_call(uri, args, options)
    task.call = call
    task.declare()
    code, checked = task.step('draft-check')
    assert code == 2 and checked['error_code'] == 'INVALID_READBACK', checked
    assert not any(uri.endswith(('setReference', 'object.set')) for uri, _, _ in task.calls)


@pytest.mark.parametrize('parent', [None, {}, {'id': 'not-a-guid'}, 7])
def test_shared_only_predicate_never_replaces_the_canonical_parent_fact(tmp_path, parent):
    task = SharedReferenceTask(tmp_path, '2025.1')
    task.objects[SECOND]['parent'] = parent
    task.declare()
    code, checked = task.step('draft-check')
    expected = 'CONSTRAINED_REFERENCE_BOUNDARY' if parent is None or parent == {} else 'INVALID_READBACK'
    assert code == 2 and checked['error_code'] == expected, checked
    assert not any(uri.endswith(('setReference', 'object.set')) for uri, _, _ in task.calls)


@pytest.mark.parametrize('version', VERSIONS[1:])
def test_shared_only_classification_supports_an_atomic_reference_preview(tmp_path, version):
    task = SharedReferenceTask(tmp_path, version, operation='object.set')
    task.declare()
    _, _, verified, _ = finish(task)
    assert verified['verified'] is True
    assert task.objects[FIRST]['Attenuation'] == {'id': SECOND}


def test_shared_only_2021_metadata_extension_is_not_assumed_to_have_later_semantics(tmp_path):
    task = SharedReferenceTask(tmp_path, '2021.1')
    task.declare()
    code, checked = task.step('draft-check')
    assert code == 2 and checked['error_code'] == 'CONSTRAINED_REFERENCE_BOUNDARY', checked
    assert not any(uri.endswith(('setReference', 'object.set')) or 'owner = null' in (args or {}).get('waql', '')
                   for uri, args, _ in task.calls)


@pytest.mark.parametrize('version', VERSIONS[1:])
def test_shared_only_predicate_keeps_the_selected_platform_and_read_meaning(tmp_path, version):
    task = SharedReferenceTask(tmp_path, version)
    platform = '{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}'
    normal_call = task.call
    def call(uri, args=None, options=None):
        if uri.endswith('isPropertyEnabled'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': True}
        return normal_call(uri, args, options)
    task.call = call
    source, target = task.bind(FIRST), task.bind(SECOND)
    code, discovered = task.step('draft-discover-fields', '--object-handle', source,
                                '--meaning', 'Attenuation', '--platform', platform)
    assert code == 0, discovered
    field = discovered['meaning_results'][0]['candidates'][0]['handle']
    code, declared = task.step('draft-declare-field-change', '--object-handle', source,
                              '--field-handle', field, '--target-handle', target)
    assert code == 0, declared
    _, _, verified, _ = finish(task)
    assert verified['verified'] is True
    reads = [(args, options) for uri, args, options in task.calls if uri.endswith('object.get')
             and ('parent' in options.get('return', []) or 'owner = null' in args.get('waql', ''))]
    classification_reads = [(args, options) for args, options in reads
                            if options.get('return') in (['id', 'parent'], ['id'])]
    assert classification_reads and all(options['platform'] == platform for _, options in classification_reads)
    predicates = [args['waql'] for args, options in classification_reads if 'waql' in args]
    assert predicates and set(predicates) == {f'from object "{SECOND}" where owner = null take 1'}


@pytest.mark.parametrize('phase', ['before', 'after'])
def test_shared_only_guard_seals_query_meaning_even_if_changed_query_returns_same_id(tmp_path, monkeypatch, phase):
    from wwise_waapi.builders.query import WaqlQueryBuilder
    task = SharedReferenceTask(tmp_path, '2025.1')
    task.declare()
    code, checked = task.step('draft-check')
    assert code == 0, checked
    code, preview = task.step('preview-from-draft')
    assert code == 0, preview
    tx = preview['transaction_id']
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    normal_build = WaqlQueryBuilder.build
    normal_call = task.call
    def changed_build(self, request):
        result = normal_build(self, request)
        result.envelope.args['waql'] = result.envelope.args['waql'].replace('owner = null', 'owner != null')
        return result
    def call(uri, args=None, options=None):
        if uri.endswith('object.get') and args.get('waql', '').endswith('where owner != null take 1'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': [{'id': SECOND}]}
        return normal_call(uri, args, options)
    task.call = call
    if phase == 'before':
        monkeypatch.setattr(WaqlQueryBuilder, 'build', changed_build)
    code, executed = task.run('execute', tx)
    if phase == 'before':
        assert code == 2, executed
        assert not any(uri.endswith(('setReference', 'object.set')) for uri, _, _ in task.calls)
        return
    assert code == 0, executed
    monkeypatch.setattr(WaqlQueryBuilder, 'build', changed_build)
    code, verified = task.run('verify', tx)
    assert code == 2 and verified.get('verified') is not True, verified


NULL_GUID = '{00000000-0000-0000-0000-000000000000}'


@pytest.mark.parametrize('version', VERSIONS[1:])
def test_shared_only_preview_cannot_certify_a_native_null_guid_parent(tmp_path, version):
    task = SharedReferenceTask(tmp_path, version)
    task.objects[SECOND]['parent'] = {'id': NULL_GUID}
    task.declare()
    code, checked = task.step('draft-check')
    if code == 2:
        assert checked['error_code'] == 'CONSTRAINED_REFERENCE_BOUNDARY', checked
        assert not any(uri.endswith(('setReference', 'object.set')) for uri, _, _ in task.calls)
        return
    assert code == 0, checked
    code, preview = task.step('preview-from-draft')
    assert code == 2 and preview['error_code'] == 'CONSTRAINED_REFERENCE_BOUNDARY', preview
    assert not any(uri.endswith(('setReference', 'object.set')) for uri, _, _ in task.calls)


@pytest.mark.parametrize('version', VERSIONS[1:])
@pytest.mark.parametrize('phase', ['before', 'after'])
def test_shared_only_parent_drift_to_native_null_guid_cannot_write_or_verify(tmp_path, version, phase):
    task = SharedReferenceTask(tmp_path, version)
    task.declare()
    code, checked = task.step('draft-check')
    assert code == 0, checked
    code, preview = task.step('preview-from-draft')
    assert code == 0, preview
    tx = preview['transaction_id']
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    if phase == 'before':
        task.objects[SECOND]['parent'] = {'id': NULL_GUID}
    code, executed = task.run('execute', tx)
    if phase == 'before':
        assert code == 2, executed
        assert not any(uri.endswith(('setReference', 'object.set')) for uri, _, _ in task.calls)
        return
    assert code == 0, executed
    task.objects[SECOND]['parent'] = {'id': NULL_GUID}
    code, verified = task.run('verify', tx)
    assert code == 2 and verified.get('verified') is not True, verified


@pytest.mark.parametrize('version', VERSIONS)
def test_child_of_reference_preview_treats_zero_guid_controller_as_unset(tmp_path, version):
    task = DefaultSwitchTask(tmp_path, version)
    task.declare_default()
    code, checked = task.step('draft-check')
    assert code == 0, checked
    task.objects[FIRST]['SwitchGroupOrStateGroup'] = {'id': NULL_GUID}
    task.objects[SECOND]['parent'] = {'id': NULL_GUID}
    code, preview = task.step('preview-from-draft')
    assert code == 2 and preview['error_code'] == 'REFERENCE_ACTIVATION_REQUIRED', preview
    assert not any(uri.endswith(('setReference', 'object.set')) for uri, _, _ in task.calls)


def _execute_target_assignment(task):
    task.declare()
    code, checked = task.step('draft-check')
    assert code == 0, checked
    code, preview = task.step('preview-from-draft')
    assert code == 0, preview
    tx = preview['transaction_id']
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, executed = task.run('execute', tx)
    assert code == 0, executed
    return tx


@pytest.mark.parametrize('version', VERSIONS[1:])
@pytest.mark.parametrize('observation', ['owner-present', 'null-parent'])
def test_observed_false_shared_target_postcondition_is_terminal_without_second_write(tmp_path, version, observation):
    from wwise_waapi.transactions import TransactionStore, TransactionState
    task = SharedReferenceTask(tmp_path, version)
    tx = _execute_target_assignment(task)
    if observation == 'owner-present':
        task.shared = False
    else:
        task.objects[SECOND]['parent'] = {'id': NULL_GUID}
    code, verified = task.run('verify', tx)
    assert code == 2 and verified['state'] == 'verification_failed', verified
    assert verified['verification']['status'] == 'verification_failed'
    assert verified['automatic_retry'] is False
    store = TransactionStore(task.path / 'state')
    assert store.load(tx).state is TransactionState.VERIFICATION_FAILED
    events = store.read_events(tx)
    assert events[-1]['event_type'] == 'verification_recorded'
    assert events[-1]['to_state'] == 'verification_failed'
    writes = [row for row in task.calls if row[0].endswith(('setReference', 'object.set'))]
    assert len(writes) == 1
    code, repeated = task.run('execute', tx)
    assert code == 2, repeated
    assert [row for row in task.calls if row[0].endswith(('setReference', 'object.set'))] == writes


@pytest.mark.parametrize('classifier,before,after', [('category', 'RecordedCategory', 'OtherCategory'),
                                                    ('isPlayable', True, False)])
def test_observed_false_category_or_playable_postcondition_is_terminal(tmp_path, classifier, before, after):
    from wwise_waapi.transactions import TransactionStore, TransactionState
    task = AttenuationTask(tmp_path, '2025.1', operation='object.setReference')
    task.objects[FIRST].update(ListenerRelativeRouting=True, OverridePositioning=True)
    task.objects[SECOND][classifier] = before
    task.metadata['Attenuation']['restriction']['restrictions'] = (
        [{'category': ['RecordedCategory']}] if classifier == 'category' else ['playable'])
    tx = _execute_target_assignment(task)
    task.objects[SECOND][classifier] = after
    code, verified = task.run('verify', tx)
    assert code == 2 and verified['state'] == 'verification_failed', verified
    assert TransactionStore(task.path / 'state').load(tx).state is TransactionState.VERIFICATION_FAILED
    code, repeated = task.run('execute', tx)
    assert code == 2, repeated
    assert len([row for row in task.calls if row[0].endswith(('setReference', 'object.set'))]) == 1


@pytest.mark.parametrize('failure', ['malformed', 'transport', 'parent-omitted', 'parent-malformed'])
def test_unavailable_shared_target_postread_stays_unverified_without_second_write(tmp_path, failure):
    from wwise_waapi.transactions import TransactionStore, TransactionState
    task = SharedReferenceTask(tmp_path, '2025.1')
    tx = _execute_target_assignment(task)
    normal_call = task.call
    def call(uri, args=None, options=None):
        if uri.endswith('object.get') and options.get('return') == ['id', 'parent'] and failure.startswith('parent'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': [{'id': SECOND, **({'parent': 7} if failure == 'parent-malformed' else {})}]}
        if uri.endswith('object.get') and args.get('waql', '').endswith('where owner = null take 1'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            if failure == 'transport':
                raise RuntimeError('controlled classifier read unavailable')
            return {'return': [7]}
        return normal_call(uri, args, options)
    task.call = call
    code, verified = task.run('verify', tx)
    assert code == 2 and verified['state'] == 'executed_unverified', verified
    assert verified['status'] == 'verification_deferred'
    assert verified['automatic_retry'] is False
    assert verified['manual_verification_retry_allowed'] is True
    store = TransactionStore(task.path / 'state')
    assert store.load(tx).state is TransactionState.EXECUTED_UNVERIFIED
    assert not any(event['event_type'] == 'verification_recorded' for event in store.read_events(tx))
    code, repeated = task.run('execute', tx)
    assert code == 2, repeated
    assert len([row for row in task.calls if row[0].endswith(('setReference', 'object.set'))]) == 1


@pytest.mark.parametrize('classifier,before,after', [('category', 'RecordedCategory', None), ('isPlayable', True, 1)])
def test_malformed_classifier_postread_remains_unknown_rather_than_proven_false(tmp_path, classifier, before, after):
    from wwise_waapi.transactions import TransactionStore, TransactionState
    task = AttenuationTask(tmp_path, '2025.1', operation='object.setReference')
    task.objects[FIRST].update(ListenerRelativeRouting=True, OverridePositioning=True)
    task.objects[SECOND][classifier] = before
    task.metadata['Attenuation']['restriction']['restrictions'] = (
        [{'category': ['RecordedCategory']}] if classifier == 'category' else ['playable'])
    tx = _execute_target_assignment(task)
    task.objects[SECOND][classifier] = after
    code, verified = task.run('verify', tx)
    assert code == 2 and verified['state'] == 'executed_unverified', verified
    assert verified['status'] == 'verification_deferred' and verified['automatic_retry'] is False
    store = TransactionStore(task.path / 'state')
    assert store.load(tx).state is TransactionState.EXECUTED_UNVERIFIED
    assert not any(event['event_type'] == 'verification_recorded' for event in store.read_events(tx))
    code, repeated = task.run('execute', tx)
    assert code == 2, repeated
    assert len([row for row in task.calls if row[0].endswith(('setReference', 'object.set'))]) == 1


def test_shared_only_canonical_null_parent_id_cannot_hide_behind_additional_pointer_fields(tmp_path):
    task = SharedReferenceTask(tmp_path, '2025.1')
    task.objects[SECOND]['parent'] = {'id': NULL_GUID, 'extra_native_fact': True}
    task.declare()
    code, checked = task.step('draft-check')
    if code == 2:
        assert checked['error_code'] in {'CONSTRAINED_REFERENCE_BOUNDARY', 'INVALID_READBACK'}, checked
        return
    assert code == 0, checked
    code, preview = task.step('preview-from-draft')
    assert code == 2, preview


def test_scalar_null_guid_parent_postread_is_malformed_not_a_proven_missing_parent(tmp_path):
    from wwise_waapi.transactions import TransactionStore, TransactionState
    task = SharedReferenceTask(tmp_path, '2025.1')
    tx = _execute_target_assignment(task)
    task.objects[SECOND]['parent'] = NULL_GUID
    code, verified = task.run('verify', tx)
    assert code == 2 and verified['state'] == 'executed_unverified', verified
    assert verified['status'] == 'verification_deferred'
    assert TransactionStore(task.path / 'state').load(tx).state is TransactionState.EXECUTED_UNVERIFIED
    code, repeated = task.run('execute', tx)
    assert code == 2, repeated
    assert len([row for row in task.calls if row[0].endswith(('setReference', 'object.set'))]) == 1
