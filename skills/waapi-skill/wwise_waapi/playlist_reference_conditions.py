"""Pinned 2025 PlaylistSlot reference and prospective owner/direct-child proof.

The matching WObjects definition, SDK constructor and retained exact native
identity establish this finite case. Older List representations stay separate.
"""
from __future__ import annotations

from copy import deepcopy
import re
from .documented_list_fields import load_catalog, resolve_live_list_evidence, observe_list_binding

URI = 'ak.wwise.core.object.get'
GUID = re.compile(r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}')
RESTRICTION = {'type': 'reference', 'restrictions': [
    {'sharedOnlyTypes': [], 'type': ['Container', 'Switch Container', 'Blend Container', 'Sound']},
    'mustChildOf', 'notNull']}
TARGET_TYPES = ('RandomSequenceContainer', 'SwitchContainer', 'BlendContainer', 'Sound')
FIELDS = ['id', 'name', 'type', 'path', 'classId', 'owner', 'parent', 'notes']


def _guid(value):
    value = value.get('id') if isinstance(value, dict) else value
    if not isinstance(value, str) or not GUID.fullmatch(value):
        raise ValueError('Playlist relationships require canonical GUIDs')
    return value.upper()


def _rows(read, ids, fields):
    if not ids or len(ids) > 128 or len(set(ids)) != len(ids):
        raise ValueError('Playlist proof exceeds its exact distinct GUID bound')
    result = read(URI, {'from': {'id': ids}}, {'return': fields})
    rows = result.get('return') if isinstance(result, dict) else None
    if not isinstance(rows, list) or len(rows) != len(ids):
        raise ValueError('Playlist proof requires every exact GUID once')
    found = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Malformed Playlist proof row')
        key = _guid(row.get('id'))
        if key not in ids or key in found:
            raise ValueError('Playlist proof contains duplicate or extra GUIDs')
        found[key] = row
    return [found[key] for key in ids]


def _source(version, source_id, name, restriction, read):
    if version != '2025.1' or name != 'PlaylistObject' or restriction != RESTRICTION:
        raise ValueError('Only the pinned 2025 PlaylistSlot.PlaylistObject direct-child case is implemented')
    source = _rows(read, [source_id], FIELDS)[0]
    if (source.get('type') != 'PluginInnerObject' or source.get('name') != ''
            or type(source.get('classId')) is not int or source['classId'] != 5636096
            or 'parent' in source):
        raise ValueError('PlaylistSlot requires the observed exact native class and owner-only identity')
    from .business_declarations import normalize_live_object_identity
    normalize_live_object_identity(source)
    catalog = load_catalog(version)
    slots = [row for row in catalog['classes'] if row['class_id'] == 5636096]
    if len(slots) != 1 or slots[0]['name'] != 'PlaylistSlot' or name not in slots[0]['scalar_references']:
        raise ValueError('The matching SDK source must establish this exact scalar reference')
    return source, catalog


def discovery_target_types(*, version, source_id, name, restriction, read):
    _source(version, source_id, name, restriction, read)
    return TARGET_TYPES


def observe(*, version, source_id, target_id, name, restriction, read):
    source, catalog = _source(version, source_id, name, restriction, read)
    owner_id = _guid(source.get('owner'))
    owner = _rows(read, [owner_id], FIELDS)[0]
    evidence = resolve_live_list_evidence(version, owner_id, 'Playlist', read=read)
    if evidence['scope']['class_id'] != 589840 or evidence['scope']['owner']['type'] != 'RandomSequenceContainer':
        raise ValueError('PlaylistSlot owner must be the source-proven RandomSequenceContainer')
    guard = observe_list_binding(evidence, read=read)
    members = guard['members']
    selected = [row for row in members if row['id'].upper() == source_id]
    if len(selected) != 1 or selected[0] != source:
        raise ValueError('Selected PlaylistSlot must match its exact ordered owner Playlist observation')
    refs = _rows(read, [row['id'].upper() for row in members], ['id', 'PlaylistObject'])
    for row in refs:
        _guid(row.get('PlaylistObject'))
    target = _rows(read, [target_id], FIELDS)[0]
    target_classes = {row['name']: row['class_id'] for row in catalog['classes'] if row['name'] in TARGET_TYPES}
    if (target.get('type') not in target_classes or type(target.get('classId')) is not int
            or target['classId'] != target_classes[target['type']]
            or _guid(target.get('parent')) != owner_id):
        raise ValueError('Playlist target must have an allowed exact class and be a direct child of its owner')
    from .business_declarations import normalize_live_object_identity
    normalize_live_object_identity(target)
    return {'kind': 'playlist_slot_direct_child', 'version': version, 'source_id': source_id,
        'target_id': target_id, 'reference': name, 'restriction': deepcopy(restriction),
        'source': source, 'owner': owner, 'target': target, 'list_guard': guard, 'references': refs}


def assertion(expected, *, read, after_write):
    try:
        actual = observe(version=expected['version'], source_id=expected['source_id'], target_id=expected['target_id'],
            name=expected['reference'], restriction=expected['restriction'], read=read)
        compared = deepcopy(actual)
        if after_write:
            source_id = expected['source_id']
            old_path = expected['source']['path']
            owner_path = expected['list_guard']['evidence']['scope']['owner']['path']
            new_path = owner_path + '\\[PlaylistSlot: (' + expected['target']['name'] + ')]'
            if actual['source']['path'] not in {old_path, new_path}:
                raise ValueError('PlaylistSlot display path changed beyond the requested reference')
            compared['source']['path'] = old_path
            for row in compared['list_guard']['members']:
                if row['id'].upper() == source_id:
                    row['path'] = old_path
            for row in compared['references']:
                if row['id'].upper() == source_id:
                    if _guid(row.get('PlaylistObject')) != expected['target_id']:
                        raise ValueError('PlaylistSlot did not retain the requested reference')
                    old = next(item for item in expected['references'] if item['id'].upper() == source_id)
                    row['PlaylistObject'] = deepcopy(old['PlaylistObject'])
        passed = compared == expected
    except (ValueError, KeyError, TypeError) as exc:
        actual, passed = {'error': str(exc)}, False
    return {'name': 'PlaylistSlot exact class, owner, direct-child target and ordered Playlist remain bound',
        'passed': passed, 'evidence': {'expected': expected, 'actual': actual}}


def discovery_class_target_types(*, version, class_id, name, restriction):
    if (version, class_id, name, restriction) != ('2025.1', 5636096, 'PlaylistObject', RESTRICTION):
        raise ValueError('Only the pinned 2025 PlaylistSlot class reference is implemented')
    catalog = load_catalog(version)
    slots = [row for row in catalog['classes'] if row['class_id'] == class_id]
    if len(slots) != 1 or slots[0]['name'] != 'PlaylistSlot' or name not in slots[0]['scalar_references']:
        raise ValueError('PlaylistSlot lost its exact scalar-reference source')
    return TARGET_TYPES


def observe_prospective(*, version, owner_id, target_id, name, restriction, read, list_mode="append"):
    discovery_class_target_types(version=version, class_id=5636096, name=name, restriction=restriction)
    if list_mode not in {'append', 'replaceAll'}:
        raise ValueError('Playlist construction requires a closed native List mode')
    evidence = resolve_live_list_evidence(version, owner_id, 'Playlist', read=read)
    if evidence['scope']['class_id'] != 589840 or evidence['scope']['owner']['type'] != 'RandomSequenceContainer':
        raise ValueError('New PlaylistSlot requires its exact RandomSequenceContainer owner')
    guard = observe_list_binding(evidence, read=read)
    references = (_rows(read, [row['id'].upper() for row in guard['members']], ['id', 'PlaylistObject'])
                  if guard['members'] else [])
    for row in references:
        _guid(row.get('PlaylistObject'))
    target = _rows(read, [target_id], FIELDS)[0]
    classes = {row['name']: row['class_id'] for row in load_catalog(version)['classes'] if row['name'] in TARGET_TYPES}
    if (target.get('type') not in classes or type(target.get('classId')) is not int
            or target['classId'] != classes[target['type']] or _guid(target.get('parent')) != owner_id):
        raise ValueError('Playlist target must have an allowed exact class and be a direct child of its owner')
    return {'kind': 'prospective_playlist_slot_direct_child', 'version': version, 'owner_id': owner_id, 'list_mode': list_mode,
        'target_id': target_id, 'reference': name, 'restriction': deepcopy(restriction),
        'target': target, 'list_guard': guard, 'references': references}


def prospective_assertion(expected, *, read, after_write):
    try:
        actual = observe_prospective(version=expected['version'], owner_id=expected['owner_id'],
            target_id=expected['target_id'], name=expected['reference'], restriction=expected['restriction'], read=read,
            list_mode=expected.get('list_mode', 'append'))
        compared = deepcopy(actual)
        if after_write:
            # The graph verifier proves every new occurrence and final roster;
            # this condition retains the original ordered peers and references.
            if expected.get('list_mode') == 'replaceAll':
                # Replacement intentionally removes old member GUIDs. The
                # existing graph verifier owns their absence and new roster.
                compared['list_guard']['members'] = expected['list_guard']['members']
                compared['references'] = expected['references']
            else:
                count = len(expected['list_guard']['members'])
                compared['list_guard']['members'] = compared['list_guard']['members'][:count]
                compared['references'] = compared['references'][:count]
        passed = compared == expected
    except (ValueError, KeyError, TypeError) as exc:
        actual, passed = {'error': str(exc)}, False
    return {'name': 'new PlaylistSlot direct-child target and original ordered peers remain bound',
        'passed': passed, 'evidence': {'expected': expected, 'actual': actual}}
