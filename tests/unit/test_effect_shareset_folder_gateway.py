"""Effect-only Folder placement uses actual owning ancestry at the public Gateway."""
from copy import deepcopy
import json

import pytest

from tests.unit.test_plugin_shareset_gateway import (
    ShareSetClient, CLASS_ID, PARENT, declare_plugin, execute_shareset, gateway,
)

WORKUNIT = '{ABABABAB-ABAB-ABAB-ABAB-ABABABABABAB}'


class FolderShareSetClient(ShareSetClient):
    def __init__(self, version):
        super().__init__(version, target_type='Folder', target_path=r'\Effects\Default Work Unit\ShareSets')
        # Pinned object-type catalogs and all five SampleProject Factory Effects
        # Work Units prove these concrete Folder/WorkUnit class identities.
        self.target.update(name='ShareSets', classId=131088, parent={'id': WORKUNIT}, notes='Keep Folder')
        self.workunit = {'id': WORKUNIT, 'name': 'Default Work Unit', 'type': 'WorkUnit',
            'classId': 1638416, 'path': r'\Effects\Default Work Unit', 'notes': 'Keep WorkUnit'}
        self.types = [{'classId': CLASS_ID, 'name': 'Wwise RoomVerb', 'type': 'Effect'},
            {'classId': 131088, 'name': 'Folder', 'type': 'WObject'},
            {'classId': 1638416, 'name': 'WorkUnit', 'type': 'WObject'}]
        self.after_write = None

    def call(self, uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri.endswith('object.getTypes'):
            self.calls.append((uri, args, options))
            return {'return': deepcopy(self.types)}
        if uri.endswith('object.get') and args.get('from') == {'id': [WORKUNIT]}:
            self.calls.append((uri, args, options))
            return {'return': [{key: self.workunit[key] for key in options['return'] if key in self.workunit}]}
        result = super().call(uri, args, options)
        if uri.endswith('object.set') and self.after_write:
            self.after_write()
        return result


@pytest.mark.parametrize('version', ['2022.1', '2023.1', '2024.1', '2025.1'])
def test_effect_shareset_folder_constructs_once_with_exact_identity_and_preserved_ancestors(tmp_path, version):
    client = FolderShareSetClient(version)
    before = deepcopy((client.target, client.workunit))
    code, verified = execute_shareset(tmp_path, version, client, with_property=True)
    assert code == 0 and verified['state'] == 'verified', verified
    assert (client.target, client.workunit) == before
    writes = [args for uri, args, _ in client.calls if uri.endswith('object.set')]
    assert writes == [{'objects': [{'object': PARENT, 'onNameConflict': 'fail', 'children': [
        {'type': 'Effect', 'name': 'Room', 'classId': CLASS_ID, '@RoomSize': 0.5}]}],
        'autoAddToSourceControl': False}]


@pytest.mark.parametrize('fault', ['hierarchy', 'owner', 'class', 'class-type-mismatch', 'missing-parent', 'cycle'])
def test_effect_shareset_folder_requires_source_class_and_complete_independent_ancestry(tmp_path, fault):
    client = FolderShareSetClient('2025.1')
    if fault == 'hierarchy': client.workunit['path'] = r'\Actor-Mixer Hierarchy\Default Work Unit'
    if fault == 'owner': client.target['owner'] = {'id': WORKUNIT}
    if fault == 'class': client.target['classId'] = CLASS_ID
    if fault == 'class-type-mismatch': client.target['classId'] = 1638416
    if fault == 'missing-parent': del client.target['parent']
    if fault == 'cycle': client.target['parent'] = {'id': PARENT}
    code, declared, step, _ = declare_plugin(tmp_path, '2025.1', client)
    assert code == 0, declared
    code, rejected = step('draft-check')
    assert code == 2, rejected
    assert not any(uri.endswith('object.set') for uri, _, _ in client.calls)


@pytest.mark.parametrize('fault', ['class', 'owner', 'notes', 'parent', 'catalog'])
def test_effect_shareset_folder_revalidates_complete_placement_before_dispatch(tmp_path, fault):
    client = FolderShareSetClient('2025.1')
    code, declared, step, env = declare_plugin(tmp_path, '2025.1', client)
    assert code == 0, declared
    code, checked = step('draft-check')
    assert code == 0, checked
    code, preview = step('preview-from-draft')
    assert code == 0, preview
    tx = preview['transaction_id']
    code, shown = gateway.execute_gateway(['transaction-show', tx], env=env)
    assert code == 0, shown
    if fault == 'class': client.workunit['classId'] = CLASS_ID
    if fault == 'owner': client.workunit['owner'] = {'id': PARENT}
    if fault == 'notes': client.workunit['notes'] = 'Unexpected mutation'
    if fault == 'parent': client.target['parent'] = {'id': PARENT}
    if fault == 'catalog': client.types[-1]['type'] = 'DifferentBaseClass'
    code, confirmed = gateway.execute_gateway(['confirm', tx, '--confirmation-token', shown['confirmation']['token']], env=env)
    assert code == 0, confirmed
    code, rejected = gateway.execute_gateway(['execute', tx], env=env, client_factory=lambda _: client)
    assert code == 2 and rejected.get('executed') is not True, json.dumps(rejected)
    assert not any(uri.endswith('object.set') for uri, _, _ in client.calls)


@pytest.mark.parametrize('fault', ['notes', 'owner', 'parent', 'catalog'])
def test_effect_shareset_folder_does_not_certify_unrequested_ancestor_changes(tmp_path, fault):
    client = FolderShareSetClient('2025.1')
    def corrupt():
        if fault == 'notes': client.workunit['notes'] = 'Reset'
        if fault == 'owner': client.target['owner'] = {'id': WORKUNIT}
        if fault == 'parent': client.target['parent'] = {'id': PARENT}
        if fault == 'catalog': client.types[-1]['type'] = 'DifferentBaseClass'
    client.after_write = corrupt
    code, result = execute_shareset(tmp_path, '2025.1', client)
    assert code == 2 and result.get('verified') is not True, json.dumps(result)
    assert sum(uri.endswith('object.set') for uri, _, _ in client.calls) == 1


@pytest.mark.parametrize('kind', ['sink', 'metadata'])
def test_effect_folder_extension_does_not_widen_other_plugin_kinds(tmp_path, kind):
    from tests.unit.test_plugin_kind_placements_gateway import KindClient, declare
    client = KindClient('2025.1', kind)
    client.target['type'] = 'Folder'
    client.target['path'] += r'\ShareSets'
    code, declared, step, _ = declare(tmp_path, '2025.1', client)
    assert code == 0, declared
    code, rejected = step('draft-check')
    assert code == 2 and rejected['error_code'] == 'INVALID_SHARESET_TARGET', rejected
    assert not any(uri.endswith('object.set') for uri, _, _ in client.calls)


@pytest.mark.parametrize('version', ['2022.1', '2023.1', '2024.1', '2025.1'])
def test_named_graph_effect_shareset_folder_uses_same_closure_without_anonymous_list(tmp_path, version):
    from tests.unit.test_anonymous_effect_slot_graph_gateway import anonymous_task
    from tests.unit.test_list_merge_existing_conditions_gateway import EFFECT_PARENT
    task = anonymous_task(tmp_path, version)
    folder = '{BEBEBEBE-BEBE-BEBE-BEBE-BEBEBEBEBEBE}'
    new_effect = '{CECECECE-CECE-CECE-CECE-CECECECECECE}'
    task.types.append({'classId': 131088, 'name': 'Folder', 'type': 'WObject'})
    task.objects[folder] = {'id': folder, 'name': 'ShareSets', 'type': 'Folder', 'classId': 131088,
        'path': task.objects[EFFECT_PARENT]['path'] + r'\ShareSets', 'parent': {'id': EFFECT_PARENT}, 'notes': 'Keep'}
    before = deepcopy(task.objects)
    parent = task.bind(folder)
    code, types = task.step('draft-discover-types', '--role', 'effect', '--meaning', 'Wwise Meter')
    assert code == 0, types
    code, declared = task.step('draft-declare-new', '--declaration-id', 'new-effect', '--parent-handle', parent,
        '--name', 'Meter', '--kind', types['type_candidates'][0]['handle'], '--field', 'plugin_placement', 'shareset')
    assert code == 0, declared
    tx, shown = task.preview()
    original, writes = task.call, []
    def call(uri, args=None, options=None):
        if uri.endswith('object.set'):
            writes.append(deepcopy(args))
            assert args['objects'] == [{'object': folder, 'children': [
                {'type': 'Effect', 'name': 'Meter', 'classId': 8454147}]}]
            task.objects[new_effect] = {'id': new_effect, 'name': 'Meter', 'type': 'Effect', 'classId': 8454147,
                'path': task.objects[folder]['path'] + r'\Meter', 'parent': {'id': folder}, 'notes': ''}
            return {'objects': [{'id': folder, 'name': 'ShareSets', 'children': [{'id': new_effect, 'name': 'Meter'}]}]}
        return original(uri, args, options)
    task.call = call
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified.get('verified') is True, json.dumps(verified)
    assert len(writes) == 1
    assert all(task.objects[identity] == row for identity, row in before.items())
