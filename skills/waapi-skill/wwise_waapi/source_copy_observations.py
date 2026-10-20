"""Default-view Source-copy observations, deliberately excluding owned graph proof."""
from __future__ import annotations

from typing import Mapping

from .object_lifecycle_graph import (
    GET, MAX_NODES, LifecycleGraphError, capture_lifecycle_fields,
    lifecycle_snapshot_equal,
)

FRAME = ('id', 'name', 'type', 'path', 'parent', 'notes', 'classId')


def exact_frame(identity, *, read, fields=FRAME):
    rows = read(GET, {'from': {'id': [identity]}}, {'return': list(fields)}).get('return')
    if (not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping)
            or str(rows[0].get('id', '')).upper() != identity.upper()
            or any(key not in rows[0] for key in FRAME)
            or any(not isinstance(rows[0].get(key), str) for key in ('name', 'type', 'path', 'notes'))):
        raise LifecycleGraphError('Source-copy observation lost its exact object identity')
    return dict(rows[0])


def capture_source(identity, *, read, version):
    # File accessors are observed only when returned; no media-state inference.
    file_field = 'originalWavFilePath' if version == '2021.1' else 'originalFilePath'
    frame = exact_frame(identity, read=read, fields=(*FRAME, 'audioSource:language'))
    if frame['type'] == 'AudioFileSource':
        frame.update(exact_frame(identity, read=read, fields=(*FRAME, file_field)))
    fields = capture_lifecycle_fields(identity, read=read, strict=False)
    # The field inventory is already represented once by field_types. Avoid
    # repeating that inventory in every per-field metadata record.
    for metadata in fields['field_metadata'].values():
        metadata.pop('available_names', None)
        metadata.pop('scope', None)
    return {'frame': frame, **fields}


def capture_owners(identities, *, read, copied_id=None):
    owners = {}
    for identity in sorted({identity.upper() for identity in identities}):
        frame = exact_frame(identity, read=read, fields=(*FRAME, '@IsVoice'))
        if '@IsVoice' in frame and not isinstance(frame['@IsVoice'], bool):
            raise LifecycleGraphError('Source-copy Sound IsVoice observation requires an actual Boolean')
        rows = read(GET, {'from': {'id': [identity]},
            'transform': [{'select': ['children']}, {'range': [0, MAX_NODES + 2]}]},
            {'return': list(FRAME)}).get('return')
        if (not isinstance(rows, list) or len(rows) > MAX_NODES + 2
                or any(not isinstance(row, Mapping) or not isinstance(row.get('id'), str) for row in rows)
                or len({row['id'].upper() for row in rows}) != len(rows)):
            raise LifecycleGraphError('Source-copy owner children must be complete, bounded and unique')
        retained = [row for row in rows if copied_id is None or row['id'].upper() != copied_id.upper()]
        complete = len(rows) < MAX_NODES + 2 and len(retained) <= MAX_NODES
        owners[identity] = {'frame': frame, 'children_complete': complete,
            'children': sorted(retained, key=lambda row: row['id'].upper()) if complete else None}
    return owners


def capture_source_copy(source, destination, *, read, version):
    observed = capture_source(source, read=read, version=version)
    parent = observed['frame'].get('parent')
    parent = parent.get('id') if isinstance(parent, Mapping) else parent
    if not isinstance(parent, str):
        raise LifecycleGraphError('Source-copy original owner is unavailable')
    return {'source': observed, 'destination': destination.upper(), 'version': version,
        'owners': capture_owners([parent, destination], read=read)}


def source_copy_scope(snapshot):
    source = snapshot['source']
    file_field = 'originalWavFilePath' if snapshot['version'] == '2021.1' else 'originalFilePath'
    return {'complete_copy_preservation': False,
        'observed': ['source_identity_class_notes', 'certified_default_view_scalars',
            'original_source_fields', 'owner_frames_and_bounded_childsets'],
        'field_count': len(source['field_values']),
        'copied_scalar_field_count': sum(name not in source['reference_fields'] for name in source['field_values']),
        'owned_role_count': 0,
        'language_observed': 'audioSource:language' in source['frame'],
        'file_reference_observed': file_field in source['frame'],
        'discovered_field_count': source['field_inventory']['count'],
        'uncertified_field_count': source['field_inventory']['count'] - len(source['field_values']),
        'owner_count': len(snapshot['owners']),
        'complete_owner_childset_count': sum(row['children_complete'] for row in snapshot['owners'].values()),
        'owner_is_voice_count': sum('@IsVoice' in row['frame'] for row in snapshot['owners'].values()),
        'unobserved': ['owned_membership_and_values', 'curve_points', 'copied_reference_remapping',
            'other_platform_views_and_links', 'media_copy_state']
            + (['file_reference_unavailable'] if source['frame']['type'] == 'AudioFileSource' and file_field not in source['frame'] else [])
            + (['default_fields_over_observation_budget'] if '*' in source['unreadable_fields'] else [])
            + (['owner_is_voice_unavailable'] if any('@IsVoice' not in row['frame'] for row in snapshot['owners'].values()) else [])
            + (['owner_childsets_over_observation_budget'] if any(not row['children_complete'] for row in snapshot['owners'].values()) else [])}


def verify_source_copy(snapshot, copied_id, *, read, replaced_ids=()):
    source_id = snapshot['source']['frame']['id']
    original = capture_source(source_id, read=read, version=snapshot['version'])
    copied = capture_source(copied_id, read=read, version=snapshot['version'])
    owners = capture_owners(snapshot['owners'], read=read, copied_id=copied_id)
    expected = snapshot['source']
    # References may identify cloned owned state. This slice certifies scalar
    # fields only on the copy; original reference values remain exact guards.
    scalars = [name for name in expected['field_values'] if name not in expected['reference_fields']]
    checks = [('original Source fields and frame are unchanged', lifecycle_snapshot_equal(original, expected)),
        ('copied Source preserves certified default-view scalar fields',
            lifecycle_snapshot_equal(copied['field_inventory'], expected['field_inventory'])
            and lifecycle_snapshot_equal(copied['field_types'], expected['field_types'])
            and lifecycle_snapshot_equal(copied['unreadable_fields'], expected['unreadable_fields'])
            and lifecycle_snapshot_equal(copied['field_metadata'], expected['field_metadata'])
            and all(name in copied['field_values'] and lifecycle_snapshot_equal(copied['field_values'][name], expected['field_values'][name]) for name in scalars)),
        ('copied Source preserves notes', copied['frame'].get('notes') == expected['frame'].get('notes'))]
    if 'audioSource:language' in expected['frame']:
        checks.append(('copied Source preserves observed language', lifecycle_snapshot_equal(
            copied['frame'].get('audioSource:language'), expected['frame']['audioSource:language'])))
    file_field = 'originalWavFilePath' if snapshot['version'] == '2021.1' else 'originalFilePath'
    if file_field in expected['frame']:
        checks.append(('copied file Source preserves its observed original-file reference',
            isinstance(expected['frame'][file_field], str) and isinstance(copied['frame'].get(file_field), str)
            and lifecycle_snapshot_equal(copied['frame'][file_field], expected['frame'][file_field])))
    removed = {str(identity).upper() for identity in replaced_ids}
    for identity, before in snapshot['owners'].items():
        after = owners[identity]
        checks.append(('Source-copy owner frame unchanged: ' + identity,
            lifecycle_snapshot_equal(before['frame'], after['frame'])))
        if before['children_complete']:
            expected_children = [row for row in before['children'] if row['id'].upper() not in removed]
            checks.append(('Source-copy complete retained owner childset unchanged: ' + identity,
                after['children_complete'] and lifecycle_snapshot_equal(expected_children, after['children'])))
    return checks
