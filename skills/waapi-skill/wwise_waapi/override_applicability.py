"""Source-sealed applicability of the Bus/AuxBus user-send inheritance switch.

A shared UI dependency may name a switch that the concrete class does not
have. This proof represents inapplicability, never a Boolean/default value.
Native same-graph effect acceptance remains separate from source/program proof.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from .canonical import canonical_sha256
from .builders.metadata import parse_get_types_result, parse_property_and_reference_names_result, parse_get_property_info_result

CATALOG_ROOT = Path(__file__).resolve().parents[1] / 'resources/metadata'
BUILDS = {'2021.1': '2021.1.14.8108', '2022.1': '2022.1.19.8584', '2023.1': '2023.1.19.8928',
          '2024.1': '2024.1.13.9056', '2025.1': '2025.1.7.9143'}
VERSIONS = frozenset(BUILDS)
DEPENDENCY = {'type': 'override', 'action': 'Enable', 'context': 'Self', 'property': 'OverrideUserAuxSends'}
_HASH = re.compile(r'[0-9a-f]{64}')
_NAME = re.compile(r'[A-Za-z0-9_]+')


def load_source(version):
    if version not in VERSIONS:
        raise ValueError('No pinned override applicability source for this version')
    raw = (CATALOG_ROOT / version / 'override-applicability.json').read_bytes()
    if len(raw) > 256 * 1024:
        raise ValueError('Override source exceeds its resource bound')
    value = json.loads(raw)
    if (set(value) != {'contract', 'version', 'source', 'classes', 'nodes', 'group', 'catalog_sha256'}
            or value['contract'] != 'waapi-skill.override-applicability-source/v2' or value['version'] != version
            or canonical_sha256({key: item for key, item in value.items() if key != 'catalog_sha256'}) != value['catalog_sha256']
            or set(value['source']) != {'member', 'sha256', 'build', 'indexed_nodes'}
            or value['source'].get('build') != BUILDS[version]
            or type(value['source'].get('indexed_nodes')) is not int
            or not 1 <= value['source']['indexed_nodes'] <= 4096
            or value['source'].get('member') != 'Authoring/Data/WObjects/WObjects.xml'
            or not _HASH.fullmatch(value['source'].get('sha256', ''))):
        raise ValueError('Override applicability source seal is invalid')
    if not isinstance(value['nodes'], list) or not 1 <= len(value['nodes']) <= 512:
        raise ValueError('Override class closure exceeds its node bound')
    nodes = {}
    for node in value['nodes']:
        if (set(node) != {'key', 'refs', 'fields', 'source_node_sha256'} or node['key'] in nodes
                or not _HASH.fullmatch(node['source_node_sha256'])
                or not isinstance(node['refs'], list) or len(node['refs']) > 128 or len(set(node['refs'])) != len(node['refs'])
                or any(not isinstance(ref, str) or not ref.startswith('ObjectBase:') for ref in node['refs'])
                or not isinstance(node['fields'], list) or len(node['fields']) > 512
                or len({field['name'] for field in node['fields']}) != len(node['fields'])):
            raise ValueError('Malformed explicit class closure node')
        for field in node['fields']:
            if (set(field) != {'name', 'kind', 'has_own_dependencies'} or not _NAME.fullmatch(field['name'])
                    or field['kind'] not in {'Property', 'Reference'} or type(field['has_own_dependencies']) is not bool):
                raise ValueError('Malformed complete field declaration')
        nodes[node['key']] = node
    memo = {}
    def closure(key, path=()):
        if key in path or len(path) >= 128 or key not in nodes:
            raise ValueError('Source class closure is cyclic or incomplete')
        if key in memo:
            return memo[key]
        result = {key}
        for ref in nodes[key]['refs']:
            result |= closure(ref, (*path, key))
        memo[key] = result
        return result
    if (not isinstance(value['classes'], list) or len(value['classes']) != 3
            or {row['name'] for row in value['classes']} != {'AuxBus', 'Bus', 'Sound'}
            or len({row['class_id'] for row in value['classes']}) != 3):
        raise ValueError('Concrete source receivers are incomplete')
    closures = {}
    for row in value['classes']:
        if (set(row) != {'name', 'class_id', 'root'} or row['root'] != 'WwiseObject:' + row['name']
                or type(row['class_id']) is not int or not 0 < row['class_id'] <= 0xFFFFFFFF):
            raise ValueError('Concrete source class identity is invalid')
        closures[row['name']] = closure(row['root'])
    group = value['group']
    expected_dependencies = [DEPENDENCY]
    if version in {'2024.1', '2025.1'}:
        expected_dependencies.append({'type': 'isMasterBus', 'action': 'Show', 'context': 'Self', 'value': False})
    if (set(group) != {'node', 'controller', 'dependencies', 'field_dependencies'} or group['node'] != 'ObjectBase:UserAuxSends'
            or group['node'] not in nodes or group['controller'] != DEPENDENCY['property']
            or sorted(group['dependencies'], key=canonical_sha256) != sorted(expected_dependencies, key=canonical_sha256)):
        raise ValueError('Unreviewed user-send group dependency source')
    fields = nodes[group['node']]['fields']
    if (not isinstance(group['field_dependencies'], dict)
            or set(group['field_dependencies']) != {field['name'] for field in fields}):
        raise ValueError('User-send field condition source is incomplete')
    for field in fields:
        own = group['field_dependencies'][field['name']]
        if (not isinstance(own, list) or len(own) > 1 or bool(own) != field['has_own_dependencies']):
            raise ValueError('User-send field condition declaration contradicts complete source')
        if own:
            expected = {'type': 'reference', 'action': 'Enable', 'context': 'Self',
                'property': 'UserAuxSend' + field['name'][-1], 'conditions': [{'referenceIsSet': True}]}
            if (version not in {'2021.1', '2022.1', '2023.1'}
                    or re.fullmatch(r'UserAuxSend(?:Volume|LPF|HPF)[0-3]', field['name']) is None
                    or own != [expected]):
                raise ValueError('Unreviewed own user-send field condition source')
    return value, nodes, closures


def prove_absent_override(*, version, class_id, info, dependency, read, structural_proof=None, discovery=False):
    """Return a scoped applicability proof or leave ordinary dependencies intact."""
    if dependency != DEPENDENCY:
        return None
    source, nodes, closures = load_source(version)
    rows = [row for row in source['classes'] if row['class_id'] == class_id]
    if len(rows) != 1 or rows[0]['name'] not in {'Bus', 'AuxBus'}:
        return None
    row = rows[0]
    closure = closures[row['name']]
    fields = [field for key in closure for field in nodes[key]['fields']]
    if any(field['name'] == DEPENDENCY['property'] for field in fields):
        return None  # A declared switch retains its ordinary Boolean planner.
    members = [field for field in nodes[source['group']['node']]['fields'] if field['name'] == info.name]
    if len(members) != 1 or source['group']['node'] not in closure:
        return None
    expected_dependencies = source['group']['dependencies'] + source['group']['field_dependencies'][info.name]
    if sorted(info.dependencies, key=canonical_sha256) != sorted(expected_dependencies, key=canonical_sha256):
        raise ValueError('Selected field conditions differ from the source-proven user-send group')
    requires_child = any(item.get('type') == 'isMasterBus' for item in source['group']['dependencies'])
    allowed_kinds = {None, 'existing-non-master-bus'}
    if not requires_child:
        allowed_kinds.add('existing-bus-identity')
    if not discovery and (requires_child or structural_proof is not None) and (not isinstance(structural_proof, dict)
            or structural_proof.get('kind') not in allowed_kinds
            or structural_proof.get('version') != version
            or structural_proof.get('class_id') != class_id or structural_proof.get('type') != row['name']):
        raise ValueError('Absent user-send override needs its exact source-required placement proof')
    types = parse_get_types_result(read('ak.wwise.core.object.getTypes', {}, {}))
    if ([item.class_id for item in types if item.name == row['name']] != [class_id]
            or [item.name for item in types if item.class_id == class_id] != [row['name']]):
        raise ValueError('Native concrete class differs from the source receiver')
    names = [item.name for item in parse_property_and_reference_names_result(
        read('ak.wwise.core.object.getPropertyAndReferenceNames', {'classId': class_id}, {}))]
    if (len(names) > 4096 or len(set(names)) != len(names) or info.name not in names
            or DEPENDENCY['property'] in names):
        raise ValueError('Fresh complete names contradict absent-controller applicability')
    return {'kind': 'not_applicable_on_class', 'version': version, 'class_id': class_id, 'class_name': row['name'],
        'field': info.name, 'dependency': dict(dependency), 'catalog_sha256': source['catalog_sha256'],
        'source_sha256': source['source']['sha256'], 'closure_sha256': canonical_sha256([nodes[key] for key in sorted(closure)]),
        'metadata_sha256': canonical_sha256(info.as_dict()), 'names_sha256': canonical_sha256(names),
        'structural_proof': structural_proof,
        **({'purpose': 'class_discovery', 'placement_required': True, 'mutation_authority': False} if discovery else {})}


def proof_current(proof, *, read, after_write=False, edits=()):
    from .new_object_defaults import structural_bus_proof_current
    if proof.get('purpose', 'mutation') != 'mutation':
        return False
    structural = proof['structural_proof']
    if structural is None:
        # Older source groups have no placement predicate. Re-prove the class
        # fact; the ordinary operation guards still bind its target/parent.
        info = parse_get_property_info_result(read('ak.wwise.core.object.getPropertyInfo',
            {'classId': proof['class_id'], 'property': proof['field']}, {}))
        return proof == prove_absent_override(version=proof['version'], class_id=proof['class_id'],
            info=info, dependency=proof['dependency'], read=read)
    if structural.get('kind') in {'existing-non-master-bus', 'existing-bus-identity'}:
        object_id = structural['source']['id']
        info = parse_get_property_info_result(read('ak.wwise.core.object.getPropertyInfo',
            {'object': object_id, 'property': proof['field']}, {}))
        expected = dict(proof)
        if after_write:
            expected['structural_proof'] = _expected_existing_structure(structural, read=read, edits=edits)
        return expected == prove_existing_absent_override(version=proof['version'], object_id=object_id,
            info=info, dependency=proof['dependency'], read=read)
    if not structural_bus_proof_current(structural, read=read, after_write=after_write):
        return False
    info = parse_get_property_info_result(read('ak.wwise.core.object.getPropertyInfo',
        {'classId': proof['class_id'], 'property': proof['field']}, {}))
    return proof == prove_absent_override(version=proof['version'], class_id=proof['class_id'], info=info,
        dependency=proof['dependency'], read=read, structural_proof=structural)


_GUID = re.compile(r'\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}')
_EXISTING_FIELDS = ('id', 'name', 'type', 'path', 'classId', 'parent', 'notes')


def _existing_row(read, object_id):
    if not isinstance(object_id, str) or not _GUID.fullmatch(object_id):
        raise ValueError('Existing bus proof needs an exact canonical GUID')
    result = read('ak.wwise.core.object.get', {'from': {'id': [object_id]}}, {'return': list(_EXISTING_FIELDS)})
    rows = result.get('return') if isinstance(result, dict) else None
    if (not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict)
            or not isinstance(rows[0].get('id'), str) or rows[0]['id'].casefold() != object_id.casefold()):
        raise ValueError('Existing bus identity must resolve exactly once')
    return {key: rows[0][key] for key in _EXISTING_FIELDS if key in rows[0]}


def prove_existing_absent_override(*, version, object_id, info, dependency, read):
    """Bind group applicability to actual source/parent, never class defaults."""
    if dependency != DEPENDENCY:
        return None
    source = _existing_row(read, object_id)
    if source.get('type') not in {'Bus', 'AuxBus'}:
        return None
    catalog, _nodes, _closures = load_source(version)
    requires_child = any(item.get('type') == 'isMasterBus' for item in catalog['group']['dependencies'])
    classes = {row['name']: row['class_id'] for row in catalog['classes']}
    if type(source.get('classId')) is not int or source['classId'] != classes[source['type']]:
        raise ValueError('Existing bus source class contradicts its actual type')
    parent_id = source.get('parent', {}).get('id') if isinstance(source.get('parent'), dict) else None
    parent = _existing_row(read, parent_id)
    if (type(parent.get('classId')) is not int or parent['classId'] <= 0
            or (requires_child and (parent.get('type') not in {'Bus', 'AuxBus'}
                or parent['classId'] != classes[parent['type']]))
            or source['id'].casefold() == parent['id'].casefold()
            or any(not isinstance(row.get(key), str) or (not row[key] and key != 'notes')
                   for row in (source, parent) for key in ('name', 'path', 'notes'))
            or source['path'] != parent['path'] + '\\' + source['name']):
        raise ValueError('Existing source needs its exact actual parent identity and source-required placement')
    types = parse_get_types_result(read('ak.wwise.core.object.getTypes', {}, {}))
    if ([row.class_id for row in types if row.name == parent['type']] != [parent['classId']]
            or [row.name for row in types if row.class_id == parent['classId']] != [parent['type']]):
        raise ValueError('Actual parent class differs from fresh native types')
    class_info = parse_get_property_info_result(read('ak.wwise.core.object.getPropertyInfo',
        {'classId': source['classId'], 'property': info.name}, {}))
    if class_info.as_dict() != info.as_dict():
        raise ValueError('Object/class user-send metadata does not match')
    structural = {'kind': 'existing-non-master-bus' if requires_child else 'existing-bus-identity',
        'version': version, 'class_id': source['classId'],
        'type': source['type'], 'source': source, 'parent': parent}
    proof = prove_absent_override(version=version, class_id=source['classId'], info=info,
        dependency=dependency, read=read, structural_proof=structural)
    if proof is None:
        return None
    names = [row.name for row in parse_property_and_reference_names_result(
        read('ak.wwise.core.object.getPropertyAndReferenceNames', {'object': object_id}, {}))]
    if len(names) > 4096 or len(set(names)) != len(names) or info.name not in names or DEPENDENCY['property'] in names:
        raise ValueError('Actual source names contradict class override applicability')
    return {**proof, 'metadata_scope': {'object': object_id}, 'object_names_sha256': canonical_sha256(names)}


def _expected_existing_structure(structural, *, read, edits):
    """Use the shared graph name/path semantics for actual applicability state."""
    from .object_graph_paths import expected_snapshot
    return {**structural,
        'source': expected_snapshot(structural['source'], edits=edits, read_row=lambda object_id: _existing_row(read, object_id)),
        'parent': expected_snapshot(structural['parent'], edits=edits, read_row=lambda object_id: _existing_row(read, object_id))}
