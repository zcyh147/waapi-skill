"""Finite Control Surface child roles on the existing typed object graph.

Sources authorize stored configuration, not reserved-role automatic birth or
hardware behavior. Normal names are checked against actual mutation/read results.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path

from .canonical import canonical_sha256
from .business_declarations import normalize_live_object_identity
from .builders.query import STRUCTURED_GUID_PATTERN

SOURCE = Path(__file__).resolve().parents[1] / 'resources/metadata/control-surface-constructor-sources.json'
CLASSES = {'ControlSurfaceSession': 4325392, 'ControlSurfaceBindingGroup': 4456464, 'ControlSurfaceBinding': 4390928}
GROUP = 'ControlSurfaceBindingGroup'
BINDING = 'ControlSurfaceBinding'
GET = 'ak.wwise.core.object.get'
INFO = 'ak.wwise.core.object.getPropertyInfo'
PEER_FIELDS = ['id', 'name', 'type', 'path', 'classId', 'parent', 'notes']
FIELDS = [*PEER_FIELDS, 'GroupType']


def fail(message, code='CONTROL_SURFACE_ROLE_BOUNDARY'):
    from .operation_registry import OperationContractError
    raise OperationContractError(code, message)


def authority(version):
    source = json.loads(SOURCE.read_bytes())
    if (source.get('contract') != 'waapi-skill.control-surface-constructor-sources/v1'
            or source.get('sha256') != canonical_sha256({key: value for key, value in source.items() if key != 'sha256'})):
        fail('Control Surface constructor source changed.', 'CONTROL_SURFACE_SOURCE_INVALID')
    lane = source['versions'][version]
    if lane['classes'] != CLASSES or lane['group_roles'] != {
            'Global': 0, 'User Binding Group': 2, 'User Binding Group Root': 3, 'Current Selection': 4}:
        fail('Control Surface source class or role differs.', 'CONTROL_SURFACE_SOURCE_INVALID')
    return {'version': version, 'source_sha256': source['sha256'], **lane}


def declaration_contract(version):
    proof = authority(version)
    return {'source_sha256': proof['source_sha256'], 'build': proof['build'], 'classes': CLASSES,
        'user_group': {'kind': 'selected_ControlSurfaceBindingGroup_Type_Handle',
            'parent': 'selected_exact_ControlSurfaceBindingGroup_with_live_GroupType_User_Binding_Group_Root_3',
            'required': 'explicit_class_GroupType_Field_Handle_choice_User_Binding_Group_2; never_default_Global_0'},
        'binding': {'kind': 'selected_ControlSurfaceBinding_Type_Handle',
            'parent': 'selected_or_planned_exact_ControlSurfaceBindingGroup_with_GroupType_0_2_or_4'},
        'fields': 'live_class_Field_Handles; TargetObject_uses_bound_Object_Handle',
        'reserved_groups': 'creation_of_Global_0_User_Binding_Group_Root_3_Current_Selection_4_not_admitted; automatic_birth_not_claimed',
        'names': 'nonempty_requested_names; actual_result_and_GUID_readback_verify_conflict_outcome; no_new_reserved_or_derived_name_rename_authority',
        'hardware_assignment': 'only_explicit_user_or_existing_text_through_bounded_HardwareControllerKey_Field_Handle; encoding_and_hardware_effect_not_claimed',
        'verification': 'stored_GUID_class_parent_membership_role_and_requested_fields; hardware_operation_not_verified'}


def role(node):
    values = [field['value'] for field in node.get('properties', []) if field['name'] == 'GroupType']
    return values[0] if len(values) == 1 and type(values[0]) is int else None


def canonical_guid(value):
    if not isinstance(value, str) or re.fullmatch(STRUCTURED_GUID_PATTERN, value) is None:
        fail('Control Surface readback requires a canonical GUID.', 'CONTROL_SURFACE_READBACK_INVALID')
    return value.upper()


def normalize_row(row, *, parent_id=None):
    """Validate complete requested evidence; never fill absent native values."""
    if (not isinstance(row, Mapping) or not set(PEER_FIELDS) <= row.keys()
            or type(row['classId']) is not int or not 0 <= row['classId'] <= 0xFFFFFFFF
            or not isinstance(row['notes'], str) or not isinstance(row['parent'], Mapping)
            or 'GroupType' in row and type(row['GroupType']) is not int):
        fail('Control Surface identity/class/parent/notes projection is incomplete or malformed.', 'CONTROL_SURFACE_READBACK_INVALID')
    try:
        normalize_live_object_identity(row)
    except ValueError as exc:
        fail(str(exc), 'CONTROL_SURFACE_READBACK_INVALID')
    actual_parent = canonical_guid(row['parent'].get('id'))
    if parent_id is not None and actual_parent != canonical_guid(parent_id):
        fail('Control Surface child is not under its exact selected parent.', 'CONTROL_SURFACE_READBACK_INVALID')
    return dict(row)


def children(identity, read):
    canonical_guid(identity)
    rows = read(GET, {'from': {'id': [identity]}, 'transform': [{'select': ['children']}]}, {'return': PEER_FIELDS}).get('return')
    if not isinstance(rows, list) or len(rows) > 256:
        fail('Control Surface children must be a bounded set of unique GUIDs.')
    rows = [normalize_row(row, parent_id=identity) for row in rows]
    if len({canonical_guid(row['id']) for row in rows}) != len(rows):
        fail('Control Surface children must be a bounded set of unique GUIDs.')
    return sorted(rows, key=lambda row: canonical_guid(row['id']))


def prepare(nodes, *, parent, version, read, conflict='fail'):
    selected = [node for node in nodes if node.get('existing_target') is not True and node['canonical_type'] in {GROUP, BINDING}]
    if not selected:
        return None
    proof = authority(version)
    by_path = {node['request_path']: node for node in nodes}
    snapshots, owners = {}, {}
    for node in selected:
        kind = node['canonical_type']
        if node['class_id'] != CLASSES[kind] or node.get('collection') != 'children':
            fail('Control Surface construction requires its exact source class as an ordinary child.')
        if kind == GROUP and node.get('preexisting_id'):
            existing = read(GET, {'from': {'id': [node['preexisting_id']]}}, {'return': FIELDS}).get('return')
            if (not isinstance(existing, list) or len(existing) != 1 or existing[0].get('id') != node['preexisting_id']
                    or existing[0].get('classId') != CLASSES[GROUP] or existing[0].get('type') != GROUP
                    or type(existing[0].get('GroupType')) is not int or existing[0]['GroupType'] != 2):
                fail('Merge can retain an existing user group (2), never convert a reserved group.')
            snapshots[node['preexisting_id']] = normalize_row(existing[0])
        owner = by_path.get(node.get('parent_request_path'))
        if owner and owner.get('existing_target') is not True:
            owner_type, owner_role = owner['canonical_type'], role(owner)
            if owner_type != GROUP or owner['class_id'] != CLASSES[GROUP]:
                fail('A planned Control Surface parent must be an explicit user binding group.')
        else:
            expected = owner.get('pre_state') if owner else parent
            identity = owner.get('target_id') if owner else parent.get('id')
            if not isinstance(expected, dict) or expected.get('type') != GROUP:
                fail('Select an exact existing binding group; reserved Session children are not constructed.')
            if identity not in snapshots:
                rows = read(GET, {'from': {'id': [identity]}}, {'return': FIELDS}).get('return')
                if (not isinstance(rows, list) or len(rows) != 1 or rows[0].get('id') != identity
                        or rows[0].get('type') != GROUP or rows[0].get('classId') != CLASSES[GROUP]
                        or any(rows[0].get(key) != expected[key] for key in ('id', 'name', 'type', 'path', 'classId', 'parent') if key in expected)):
                    fail('Selected Control Surface parent needs one exact live GUID/class/hierarchy identity.')
                snapshots[identity] = normalize_row(rows[0])
            owner_type = GROUP
            owner_role = snapshots[identity].get('GroupType')
            if owner and (owner.get('requested_name') != expected.get('name')
                    or owner.get('notes_supplied') or owner.get('properties') or owner.get('references')):
                fail('Configure the selected parent separately before binding it for child construction.')
        if owner_type != GROUP or type(owner_role) is not int:
            fail('The selected parent must expose its exact live GroupType; names do not establish roles.')
        owner_path = owner['request_path'] if owner else None
        owner_id = (owner.get('target_id') or owner.get('preexisting_id')) if owner else parent.get('id')
        key = owner_path or owner_id
        if key not in owners:
            owners[key] = {'request_path': owner_path, 'id': owner_id,
                'before': children(owner_id, read) if owner_id else [], 'new_paths': [], 'occurrences': [], 'edited_ids': [], 'retired_ids': []}
        frame = owners[key]
        frame['new_paths'].append(node['request_path'])
        frame['occurrences'].append({'request_path': node['request_path'], 'merge_id': node.get('preexisting_id')})
        if node.get('preexisting_id'):
            frame['edited_ids'].append(node['preexisting_id'])
        if node.get('on_name_conflict', conflict) == 'replace':
            collisions = [row for row in frame['before'] if row['name'].casefold() == node['requested_name'].casefold()]
            for collision in collisions if kind == GROUP else []:
                rows = read(GET, {'from': {'id': [collision['id']]}}, {'return': FIELDS}).get('return')
                if (not isinstance(rows, list) or len(rows) != 1 or rows[0].get('id') != collision['id']
                        or rows[0].get('classId') != CLASSES[GROUP] or rows[0].get('type') != GROUP
                        or type(rows[0].get('GroupType')) is not int or rows[0]['GroupType'] != 2):
                    fail('Replacement may replace an explicitly owned user group (2), never a reserved group.')
                snapshots[collision['id']] = normalize_row(rows[0])
            frame['retired_ids'].extend(row['id'] for row in collisions)
        if kind == GROUP and not (role(node) == 2 and owner_role == 3):
            fail('New user groups require explicit User Binding Group (2) under an existing User Binding Group Root (3); reserved roles and native default Global (0) are not constructors.')
        if kind == BINDING and owner_role not in (0, 2, 4):
            fail('New bindings require a selected Global (0), User Binding Group (2) or Current Selection (4) group.')
        node['control_surface_constructor'] = {'version': version, 'class_id': CLASSES[kind]}
        node['structural_class_id'] = CLASSES[kind]
    metadata = read(INFO, {'classId': CLASSES[GROUP], 'property': 'GroupType'}, {})
    choices = metadata.get('restriction', {}).get('values', [])
    if (metadata.get('name') != 'GroupType' or metadata.get('type') != 'int16'
            or type(metadata.get('default')) is not int or metadata['default'] != 0
            or len(choices) != 4 or {row.get('value') for row in choices} != set(proof['group_roles'].values())
            or any(type(row.get('value')) is not int for row in choices)):
        fail('Live GroupType metadata must match the source-defined roles/default.', 'CONTROL_SURFACE_METADATA_UNPROVEN')
    return {'source': proof, 'parents': list(snapshots.values()), 'retired_ids': [identity for frame in owners.values() for identity in frame['retired_ids']], 'owners': list(owners.values()), 'group_metadata': metadata}


def guard_assertions(boundary, *, read, after_write=False):
    try:
        current = authority(boundary['source']['version']) == boundary['source']
        current = current and all(isinstance(owner.get('occurrences'), list) and owner['occurrences'] for owner in boundary['owners'])
        current = current and read(INFO, {'classId': CLASSES[GROUP], 'property': 'GroupType'}, {}) == boundary['group_metadata']
        parents = [row for row in boundary['parents'] if not (after_write and row['id'] in boundary['retired_ids'])]
        rows = [read(GET, {'from': {'id': [row['id']]}}, {'return': FIELDS}).get('return') for row in parents]
        current = current and all(isinstance(actual, list) and len(actual) == 1 and normalize_row(actual[0]) == expected
            for actual, expected in zip(rows, parents))
        if not after_write:
            current = current and all(children(owner['id'], read) == owner['before'] for owner in boundary['owners'] if owner['id'])
    except (OSError, ValueError, KeyError, TypeError):
        current, rows = False, []
    return [{'name': 'Control Surface source, selected parent class and role remain bound',
        'passed': bool(current), 'evidence': {'parents': rows, 'expected': boundary}}]


def verification_assertions(boundary, identities, *, read):
    assertions = []
    before_ids = {canonical_guid(row['id']) for owner in boundary['owners'] for row in owner['before']}
    before_ids.update(canonical_guid(row['id']) for row in boundary['parents'])
    seen_ids = set()
    for owner in boundary['owners']:
        identity = owner['id'] or identities.get(owner['request_path'])
        freshness = []
        try:
            actual = children(identity, read)
            current = {canonical_guid(row['id']): row for row in actual}
            retired = {canonical_guid(value) for value in owner['retired_ids']}
            retained = {canonical_guid(row['id']): row for row in owner['before'] if canonical_guid(row['id']) not in retired}
            new_ids = []
            for occurrence in owner['occurrences']:
                result_id = canonical_guid(identities.get(occurrence['request_path']))
                merge_id = occurrence['merge_id']
                valid = (result_id == canonical_guid(merge_id) if merge_id is not None else result_id not in before_ids)
                valid = valid and result_id not in seen_ids
                freshness.append({'request_path': occurrence['request_path'], 'id': result_id, 'merge_id': merge_id, 'passed': valid})
                seen_ids.add(result_id)
                new_ids.append(result_id)
            expected = set(retained) | set(new_ids)
            edited = {canonical_guid(value) for value in owner['edited_ids']}
            passed = bool(identity and new_ids and all(item['passed'] for item in freshness) and set(current) == expected
                and all(current.get(key) == row for key, row in retained.items() if key not in edited))
        except (ValueError, KeyError, TypeError):
            actual, passed = [], False
        assertions.append({'name': 'Control Surface exact child membership and unrequested peers are preserved',
            'passed': passed, 'evidence': {'owner': identity, 'before': owner, 'actual': actual, 'occurrence_identities': freshness}})
    return assertions
