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
