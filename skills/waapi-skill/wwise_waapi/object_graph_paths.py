"""GUID-bound path preservation for explicitly renamed graph ancestors.

This observes existing identities and checks sealed name intent; it constructs
no graph, native mutation, suffix, or caller path expression.
"""
from __future__ import annotations

import re

from .operation_object import DEFAULT_MAX_DEPTH, DEFAULT_MAX_NODES
from .identity_limits import MULTI_IDENTITY_READ_MAX_IDS

FIELDS = ('id', 'name', 'type', 'path', 'parent', 'notes')
_GUID = re.compile(r'\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}')


def parent_id(value):
    return value.get('id') if isinstance(value, dict) else value


def read_identity(read, object_id):
    if not isinstance(object_id, str) or not _GUID.fullmatch(object_id):
        raise ValueError('Ancestor path binding needs an exact GUID')
    result = read('ak.wwise.core.object.get', {'from': {'id': [object_id]}}, {'return': list(FIELDS)})
    rows = result.get('return') if isinstance(result, dict) else None
    if (not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict)
            or not isinstance(rows[0].get('id'), str) or rows[0]['id'].casefold() != object_id.casefold()):
        raise ValueError('Ancestor identity must resolve exactly once')
    row = {key: rows[0][key] for key in FIELDS if key in rows[0]}
    if any(not isinstance(row.get(key), str) or (not row[key] and key != 'notes') for key in ('name', 'type', 'path', 'notes')):
        raise ValueError('Ancestor identity snapshot is incomplete')
    return row


def expected_snapshot(snapshot, *, edits, read_row):
    """Rewrite old path components only for exact-GUID admitted name edits."""
    if not isinstance(edits, (list, tuple)) or len(edits) > DEFAULT_MAX_NODES:
        raise ValueError('Ancestor edit context exceeds the graph node bound')
    row = dict(snapshot)
    segments = row['path'].split('\\')
    for node in edits:
        if node.get('existing_target') is not True or not isinstance(node.get('pre_state'), dict):
            continue
        before = node['pre_state']
        same = node['target_id'].casefold() == row['id'].casefold()
        if same and node.get('notes_supplied') is True:
            row['notes'] = node['requested_notes']
        name = node.get('requested_name')
        old_path = before.get('path')
        if name == node.get('original_name'):
            continue
        if not isinstance(old_path, str):
            raise ValueError('A requested rename lacks its original path')
        if not (snapshot['path'] == old_path or snapshot['path'].startswith(old_path + '\\')):
            continue
        actual = read_row(node['target_id'])
        actual_name = actual.get('name')
        if (not isinstance(name, str) or not isinstance(actual_name, str) or not actual_name or '\\' in actual_name
                or not (actual_name == name or (node.get('on_name_conflict') == 'rename' and actual_name.startswith(name)))):
            raise ValueError('Actual name differs from the sealed graph rename policy')
        segments[len(old_path.split('\\')) - 1] = actual_name
        if same:
            row['name'] = actual_name
        reference = row.get('parent')
        if (isinstance(reference, dict) and isinstance(reference.get('id'), str)
                and reference['id'].casefold() == node['target_id'].casefold() and 'name' in reference):
            # Native identity references may also project the parent label. Only
            # that exact renamed parent may change it; keep its GUID and every
            # other projected field subject to the ordinary preservation check.
            row['parent'] = {**reference, 'name': actual_name}
    row['path'] = '\\'.join(segments)
    return row


def prepare_ancestor_path_guards(specs, *, read):
    """Acquire only missing ancestry needed by an explicit ancestor rename."""
    roots = [node for node in specs if node.get('existing_target') is True]
    cache = {node['target_id'].casefold(): {key: node['pre_state'][key] for key in FIELDS if key in node['pre_state']}
             for node in roots}
    renamed = [node for node in roots if node.get('requested_name') != node.get('original_name')]
    added = {}
    for node in roots:
        source = cache[node['target_id'].casefold()]
        needed = {ancestor['target_id'].casefold() for ancestor in renamed
            if source['path'].startswith(ancestor['pre_state']['path'] + '\\')}
        if not needed:
            continue
        if not isinstance(parent_id(source.get('parent')), str) and node.get('requested_name') == node.get('original_name'):
            # No ordinary parent chain or static renamed-source path to repair.
            # Owned-member preservation remains on the separate List/owner guards.
            continue
        current, chain, visited = source, [], {source['id'].casefold()}
        for _ in range(DEFAULT_MAX_DEPTH):
            object_id = parent_id(current.get('parent'))
            if not isinstance(object_id, str) or not _GUID.fullmatch(object_id) or object_id.casefold() in visited:
                raise ValueError('Requested ancestor rename has a missing or cyclic GUID parent chain')
            key = object_id.casefold()
            if key not in cache:
                if len(cache) >= MULTI_IDENTITY_READ_MAX_IDS:
                    raise ValueError('Ancestor identity set exceeds the existing read bound')
                cache[key] = read_identity(read, object_id)
                added[key] = cache[key]
            parent = cache[key]
            if current['path'] != parent['path'] + '\\' + current['name']:
                raise ValueError('Requested ancestor rename lacks matching GUID/path ancestry')
            chain.append(parent)
            visited.add(key)
            needed.discard(key)
            if not needed:
                break
            current = parent
        if needed:
            raise ValueError('Requested ancestor rename exceeds the existing graph depth bound')
        node['ancestor_rename_path_guard'] = {'source': source, 'ancestors': chain}
    return list(added.values())


def verify_ancestor_path_guard(guard, *, edits, read):
    snapshots = [guard['source'], *guard['ancestors']]
    if len(snapshots) > DEFAULT_MAX_DEPTH + 1:
        raise ValueError('Ancestor proof exceeds the graph depth bound')
    cache = {}
    def read_row(object_id):
        key = object_id.casefold()
        if key not in cache:
            cache[key] = read_identity(read, object_id)
        return cache[key]
    expected_rows = [expected_snapshot(row, edits=edits, read_row=read_row) for row in snapshots]
    passed = all(read_row(row['id']) == expected for row, expected in zip(snapshots, expected_rows))
    return passed, expected_rows[0]['path'], {'expected': expected_rows, 'actual': list(cache.values())}
