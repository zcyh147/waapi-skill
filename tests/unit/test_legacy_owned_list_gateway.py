"""2021 source-owned music Lists use the existing closed root CREATE seam."""
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


def legacy_task(path, *, owner='MusicSegment', member='MusicCue', collection='Cues'):
    task = OwnedGraphTask(path, '2021.1', 'object.create')
    ids = {'MusicSegment': 1769488, 'MusicCue': 3866640, 'MusicTrackSequence': 3801104,
        'MusicClipMidi': 4063248, 'MusicClip': 3932176}
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


def test_legacy_owned_class_is_still_forbidden_as_arbitrary_hierarchy_child(tmp_path):
    task = OwnedGraphTask(tmp_path, '2021.1', 'object.create')
    task.types = [{'name': 'MusicClip', 'classId': 3932176, 'type': 'WObject'}]
    task.objects[FIRST].update(type='WorkUnit', classId=1638416)
    parent = task.bind(FIRST)
    code, types = task.step('draft-discover-types', '--role', 'object', '--meaning', 'MusicClip')
    assert code == 0, types
    code, declared = task.step('draft-declare-new', '--declaration-id', 'invalid', '--parent-handle', parent,
        '--kind', types['type_candidates'][0]['handle'], '--name', 'Wrong hierarchy')
    assert code == 0, declared
    code, failed = task.step('draft-check')
    assert code == 2 and failed['error_code'] == 'UNSUPPORTED_OBJECT_TYPE', failed
    assert not any(u.endswith('object.create') for u, _, _ in task.calls)
