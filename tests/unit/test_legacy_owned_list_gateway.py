"""Source-owned music Lists use exact closed CREATE and SET placement seams."""
from copy import deepcopy
import base64
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

import pytest

from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, FIRST, SECOND, CHILD

ROOT = Path(__file__).parents[2]


def legacy_task(path, *, owner='MusicSegment', member='MusicCue', collection='Cues',
        version='2021.1', operation='object.create'):
    task = OwnedGraphTask(path, version, operation)
    ids = {'MusicSegment': 1769488, 'MusicCue': 3866640, 'MusicTrackSequence': 3801104,
        'MusicClipMidi': 4063248, 'MusicClip': 3932176, 'MusicStinger': 2490384, 'WorkUnit': 3}
    task.types = [{'name': name, 'classId': identity, 'type': 'WObject'} for name, identity in ids.items()]
    task.creation_classes.update(ids)
    task.objects[FIRST].update(type=owner, classId=ids[owner], **{'@' + collection: []})
    task.objects[FIRST].pop('@CustomList')
    task.require_class_projection = True
    parent = task.bind(FIRST)
    code, fields = task.step('draft-discover-fields', '--object-handle', parent,
        '--field-source', 'documented-lists', '--list')
    assert code == 0, fields
    choice, = [r for r in fields['agent_result']['items'] if r['name'] == collection]
    code, selected = task.step('draft-discover-fields', '--object-handle', parent,
        '--field-source', 'documented-lists', '--selection', choice['selection'])
    assert code == 0, selected
    field = selected['meaning_results'][0]['candidates'][0]['handle']
    code, discovered = task.step('draft-discover-types', '--role', 'object', '--meaning', member)
    assert code == 0, discovered
    kind = discovered['type_candidates'][0]['handle']
    code, declared = task.step('draft-declare-new', '--declaration-id', 'owned',
        '--parent-handle', parent, '--kind', kind, '--name', 'Owned music', '--field', 'object_list', field)
    assert code == 0, declared
    task.owned_result = declared['draft']['declared_object']['result_handle']
    if operation == 'object.set':
        original = task.call
        def call(uri, args=None, options=None):
            if uri.endswith('object.set'):
                task.calls.append((uri, deepcopy(args), deepcopy(options)))
                task.conflict = args.get('onNameConflict', 'fail')
                results = []
                for item in args['objects']:
                    if item['object'] == SECOND:
                        assert set(item) == {'object', '@OwnedTarget'}
                        assert item['@OwnedTarget'] == task.objects[FIRST]['path'] + r'\Owned music'
                        task.objects[SECOND]['@OwnedTarget'] = {'id': CHILD}
                        results.append({'id': SECOND, 'name': task.objects[SECOND]['name']})
                        continue
                    assert set(item) == {'object', '@' + collection} and item['object'] == FIRST
                    members = [task._create(node, FIRST, owned=True) for node in item['@' + collection]]
                    task.objects[FIRST]['@' + collection].extend({'id': row['id']} for row in members)
                    results.append({'id': FIRST, 'name': task.objects[FIRST]['name'], '@' + collection: members})
                return {'objects': results}
            return original(uri, args, options)
        task.call = call
    return task


@pytest.mark.parametrize('owner,member,collection', [('MusicSegment', 'MusicCue', 'Cues'),
    ('MusicTrackSequence', 'MusicClipMidi', 'Clips')])
def test_legacy_source_list_create_verifies_actual_class_owner_and_membership(tmp_path, owner, member, collection):
    task = legacy_task(tmp_path, owner=owner, member=member, collection=collection)
    before = deepcopy(task.objects[SECOND])
    tx, shown = task.preview()
    call = shown['artifact']['prepared_operation']['dispatch']
    assert call['uri'] == 'ak.wwise.core.object.create'
    assert call['args']['type'] == member and call['args']['list'] == collection
    assert 'classId' not in call['args']
    code, result = task.finish(tx, shown)
    assert code == 0 and result['verified'] is True, result
    assert task.objects[CHILD]['owner'] == {'id': FIRST}
    assert task.objects[FIRST]['@' + collection] == [{'id': CHILD}]
    assert task.objects[SECOND] == before
    assert sum(u.endswith('object.create') for u, _, _ in task.calls) == 1


def test_legacy_source_list_does_not_admit_another_member_class(tmp_path):
    task = legacy_task(tmp_path, owner='MusicSegment', member='MusicClip', collection='Cues')
    code, failed = task.step('draft-check')
    assert code == 2 and failed['error_code'] == 'DOCUMENTED_LIST_ELEMENT_CLASS_INVALID', failed
    assert not any(u.endswith('object.create') for u, _, _ in task.calls)


def test_legacy_overlay_retains_exact_xml_and_seven_member_families():
    from wwise_waapi.documented_list_fields import load_catalog
    source = json.loads((ROOT / 'skills/waapi-skill/resources/metadata/2021.1/installed-owned-list-fields.json').read_bytes())
    snapshot = json.loads(gzip.decompress((ROOT / 'tests/fixtures/metadata-conditions/self-scalar-source-parents.json.gz').read_bytes()))
    original = snapshot['files']['2021.1.14.8108|condition|WObjects/WObjects.xml']
    xml = base64.b64decode(original['bytes_base64'])
    assert hashlib.sha256(xml).hexdigest() == source['source']['sha256']
    assert {e['name'] for r in source['rows'] for e in r['field']['element_classes']} == {
        'MusicCue', 'MusicStinger', 'MusicTrackSequence', 'MusicClip', 'MusicClipMidi', 'MusicEventCue', 'Metadata'}
    tree = ET.fromstring(xml)
    for row in source['rows']:
        kind, rest = row['source_member'].split('#', 1)[1].split('[', 1)
        name = rest.split(']', 1)[0]
        owner, = [n for n in tree if n.tag == kind and n.get('Name') == name]
        field, = [n for n in owner.findall('./ObjectLists/ObjectList') if n.get('Name') == row['field']['name']]
        assert ET.tostring(field, encoding='unicode') == row['declaration_xml']
    catalog = load_catalog('2021.1')
    assert catalog['coverage']['installed_owned_list_declarations'] == 17
    assert not any(f['name'] == 'Playlist' for r in catalog['classes'] for f in r['lists'])


@pytest.mark.parametrize('fault', ['source', 'owner'])
def test_legacy_source_list_revalidates_before_the_only_write(tmp_path, monkeypatch, fault):
    from wwise_waapi import documented_list_fields
    task = legacy_task(tmp_path)
    tx, shown = task.preview()
    if fault == 'source':
        copied = tmp_path / 'catalog-copy'
        shutil.copytree(documented_list_fields.CATALOG_ROOT / '2021.1', copied / '2021.1')
        monkeypatch.setattr(documented_list_fields, 'CATALOG_ROOT', copied)
        path = copied / '2021.1/installed-owned-list-fields.json'
        path.write_bytes(path.read_bytes() + b'changed-source')
    else:
        task.objects[FIRST]['classId'] = 1835024
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, rejected = task.run('execute', tx)
    assert code == 2 and rejected.get('verified') is not True, rejected
    assert not any(u.endswith('object.create') for u, _, _ in task.calls)


@pytest.mark.parametrize('version,operation', [('2021.1', 'object.create'), ('2025.1', 'object.set')])
def test_legacy_owned_class_is_still_forbidden_as_arbitrary_hierarchy_child(tmp_path, version, operation):
    task = OwnedGraphTask(tmp_path, version, operation)
    task.types = [{'name': 'MusicClip', 'classId': 3932176, 'type': 'WObject'},
        {'name': 'WorkUnit', 'classId': 1638416, 'type': 'WObject'}]
    task.objects[FIRST].update(type='WorkUnit', classId=1638416)
    parent = task.bind(FIRST)
    code, types = task.step('draft-discover-types', '--role', 'object', '--meaning', 'MusicClip')
    assert code == 0, types
    code, declared = task.step('draft-declare-new', '--declaration-id', 'invalid', '--parent-handle', parent,
        '--kind', types['type_candidates'][0]['handle'], '--name', 'Wrong hierarchy')
    assert code == 0, declared
    code, failed = task.step('draft-check')
    error = failed['error_code'] if operation == 'object.create' else failed['details']['issues'][0]['error_code']
    assert code == 2 and error == 'UNSUPPORTED_OBJECT_TYPE', failed
    assert not any(u.endswith(operation) for u, _, _ in task.calls)


@pytest.mark.parametrize('version,owner,member,collection', [
    ('2022.1', 'MusicTrackSequence', 'MusicClipMidi', 'Clips'),
    ('2025.1', 'MusicSegment', 'MusicStinger', 'Stingers')])
def test_source_owned_music_set_reaches_verified_exact_list_insertion(tmp_path, version, owner, member, collection):
    task = legacy_task(tmp_path, version=version, operation='object.set',
        owner=owner, member=member, collection=collection)
    if version == '2025.1':
        # One same-graph reference forces Registry's prospective result resolver
        # as well as its final List-node preparation to use the exact List proof.
        task.metadata['OwnedTarget'] = {'name': 'OwnedTarget', 'type': 'Reference'}
        task.objects[SECOND]['@OwnedTarget'] = None
        referrer = task.bind(SECOND)
        code, fields = task.step('draft-discover-fields', '--object-handle', referrer, '--meaning', 'OwnedTarget')
        assert code == 0, fields
        reference = fields['meaning_results'][0]['candidates'][0]['handle']
        code, declared = task.step('draft-declare-existing', '--declaration-id', 'reference',
            '--object-handle', referrer, '--field-value', reference, task.owned_result)
        assert code == 0, declared
    preserved = deepcopy(task.objects[SECOND])
    tx, shown = task.preview()
    dispatch = shown['artifact']['prepared_operation']['dispatch']
    assert dispatch['uri'] == 'ak.wwise.core.object.set'
    assert dispatch['args']['objects'][0] == {'object': FIRST, '@' + collection: [
        {'type': member, 'name': 'Owned music'}]}
    if version == '2025.1':
        assert dispatch['args']['objects'][1] == {'object': SECOND,
            '@OwnedTarget': task.objects[FIRST]['path'] + r'\Owned music'}
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert task.objects[CHILD]['owner'] == {'id': FIRST}
    assert task.objects[FIRST]['@' + collection] == [{'id': CHILD}]
    if version == '2025.1':
        preserved['@OwnedTarget'] = {'id': CHILD}
    assert task.objects[SECOND] == preserved
    assert sum(u.endswith('object.set') for u, _, _ in task.calls) == 1


def test_source_owned_music_set_rejects_wrong_list_member_before_write(tmp_path):
    task = legacy_task(tmp_path, version='2022.1', operation='object.set', member='MusicClip')
    code, rejected = task.step('draft-check')
    assert code == 2 and rejected['details']['issues'][0]['error_code'] == 'DOCUMENTED_LIST_ELEMENT_CLASS_INVALID', rejected
    assert not any(u.endswith('object.set') for u, _, _ in task.calls)


@pytest.mark.parametrize('fault', ['source', 'owner'])
def test_source_owned_music_set_revalidates_exact_context_before_write(tmp_path, monkeypatch, fault):
    from wwise_waapi import documented_list_fields
    task = legacy_task(tmp_path, version='2022.1', operation='object.set',
        owner='MusicTrackSequence', member='MusicClipMidi', collection='Clips')
    tx, shown = task.preview()
    if fault == 'source':
        copied = tmp_path / 'changed-catalog'
        shutil.copytree(documented_list_fields.CATALOG_ROOT / '2022.1', copied / '2022.1')
        monkeypatch.setattr(documented_list_fields, 'CATALOG_ROOT', copied)
        path = copied / '2022.1/documented-list-fields.json'
        path.write_bytes(path.read_bytes() + b'changed-source')
    else:
        task.objects[FIRST]['classId'] = 1769488
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, rejected = task.run('execute', tx)
    assert code == 2 and rejected.get('verified') is not True, rejected
    assert not any(u.endswith('object.set') for u, _, _ in task.calls)
