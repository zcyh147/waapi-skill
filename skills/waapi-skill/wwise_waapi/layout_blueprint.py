"""Closed layout declarations; native IDs and wire fields remain Gateway-owned."""
from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any, Mapping
from uuid import uuid4

CONTRACT = 'waapi-skill.layout-blueprint/v1'
MAX_NODES = 128
# A serialized stack adds a mapping and child list per level. Leave room for
# Layout/window wrappers under the existing 32-level bounded read contract.
MAX_DEPTH = 14
MAX_BYTES = 256 * 1024


def blueprint_schema() -> dict[str, Any]:
    text = {'type': 'string', 'maxLength': 4096, 'pattern': r'^[^\u0000]*$'}
    key = {'type': 'string', 'pattern': r'^[A-Za-z][A-Za-z0-9_-]{0,63}$'}
    common = {'key': key, 'width': text, 'height': text}
    stack = {'type': 'object', 'additionalProperties': False,
        'properties': {**common, 'kind': {'const': 'stack'}, 'label': text,
            'orientation': {'enum': ['horizontal', 'vertical']},
            'children': {'type': 'array', 'maxItems': MAX_NODES, 'uniqueItems': True, 'items': key}},
        'required': ['key', 'kind', 'label', 'orientation', 'children']}
    view = {'type': 'object', 'additionalProperties': False,
        'properties': {**common, 'kind': {'const': 'view'}, 'view_type': {**text, 'minLength': 1},
            'selection_channel': text},
        'required': ['key', 'kind', 'view_type', 'selection_channel']}
    return {'type': 'object', 'additionalProperties': False,
        'properties': {'contract': {'const': CONTRACT}, 'root': key,
            'workspace_name': {**text, 'description': 'Name inside the layout document; distinct from its temporary lookup name. Omission uses the lookup name.'},
            'nodes': {'type': 'array', 'minItems': 1, 'maxItems': MAX_NODES, 'items': {'oneOf': [stack, view]}}},
        'required': ['contract', 'root', 'nodes'],
        'gateway_bounds': {'maximum_depth': MAX_DEPTH, 'maximum_utf8_bytes': MAX_BYTES}}


def validate_blueprint(value: Any) -> dict[str, Any]:
    try:
        size = len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8'))
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError('Layout blueprint must be a bounded JSON business declaration') from exc
    if size > MAX_BYTES:
        raise ValueError('Layout blueprint exceeds its UTF-8 byte bound')
    if (not isinstance(value, dict) or not {'contract', 'root', 'nodes'} <= set(value)
            or not set(value) <= {'contract', 'root', 'nodes', 'workspace_name'}
            or value['contract'] != CONTRACT or not isinstance(value['nodes'], list)
            or not 1 <= len(value['nodes']) <= MAX_NODES):
        raise ValueError('Layout blueprint requires its exact bounded closed node declaration')
    if 'workspace_name' in value and (not isinstance(value['workspace_name'], str)
            or '\x00' in value['workspace_name'] or len(value['workspace_name']) > 4096):
        raise ValueError('Layout blueprint workspace name must be a bounded string without NUL')
    def local_key(key: Any) -> bool:
        return isinstance(key, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', key) is not None
    if not local_key(value['root']):
        raise ValueError('Layout blueprint root must be a local node key')
    for node in value['nodes']:
        if not isinstance(node, dict) or not isinstance(node.get('kind'), str) or node['kind'] not in {'stack', 'view'}:
            raise ValueError('Layout blueprint node requires a disclosed closed kind')
        required = ({'key', 'kind', 'label', 'orientation', 'children'} if node['kind'] == 'stack' else
                    {'key', 'kind', 'view_type', 'selection_channel'})
        if not required <= set(node) or not set(node) <= required | {'width', 'height'} or not local_key(node['key']):
            raise ValueError('Layout blueprint node has missing or unknown closed fields')
        text_fields = ['label'] if node['kind'] == 'stack' else ['view_type', 'selection_channel']
        text_fields += [field for field in ('width', 'height') if field in node]
        if any(not isinstance(node[field], str) or '\x00' in node[field] or len(node[field]) > 4096 for field in text_fields):
            raise ValueError('Layout blueprint text values must be bounded strings without NUL')
        if node['kind'] == 'stack':
            if (not isinstance(node['orientation'], str) or node['orientation'] not in {'horizontal', 'vertical'}
                    or not isinstance(node['children'], list) or len(node['children']) > MAX_NODES
                    or any(not local_key(child) for child in node['children'])
                    or len(set(node['children'])) != len(node['children'])):
                raise ValueError('Layout blueprint stack requires an exact orientation and ordered unique children')
        elif not node['view_type']:
            raise ValueError('Layout blueprint view requires a nonempty live view type')
    nodes = {row['key']: row for row in value['nodes']}
    if len(nodes) != len(value['nodes']) or value['root'] not in nodes or nodes[value['root']]['kind'] != 'stack':
        raise ValueError('Layout blueprint requires unique local node keys and one stack root')
    visited: set[str] = set()
    def walk(key: str, depth: int) -> None:
        if depth > MAX_DEPTH or key not in nodes or key in visited:
            raise ValueError('Layout blueprint must be one bounded tree without cycles or shared nodes')
        visited.add(key)
        for child in nodes[key].get('children', []):
            walk(child, depth + 1)
    walk(value['root'], 1)
    if visited != set(nodes):
        raise ValueError('Layout blueprint contains disconnected nodes')
    return deepcopy(value)


def mint_blueprint_ids(blueprint: Any) -> dict[str, str]:
    checked = validate_blueprint(blueprint)
    return {row['key']: '{' + str(uuid4()).upper() + '}' for row in checked['nodes']}


def compile_blueprint(blueprint: Any, *, name: str, node_ids: Mapping[str, str]) -> dict[str, Any]:
    checked = validate_blueprint(blueprint)
    nodes = {row['key']: row for row in checked['nodes']}
    if (not isinstance(node_ids, Mapping) or set(node_ids) != set(nodes)
            or any(not isinstance(identity, str) or not re.fullmatch(
                r'\{[0-9A-F]{8}-(?:[0-9A-F]{4}-){3}[0-9A-F]{12}\}', identity) for identity in node_ids.values())
            or len(set(node_ids.values())) != len(nodes)):
        raise ValueError('Layout blueprint lacks its exact unique Gateway-generated node identities')
    def emit(key: str) -> dict[str, Any]:
        node = nodes[key]
        result = {'@type': 'StackPanel' if node['kind'] == 'stack' else 'View', 'ID': node_ids[key]}
        if node['kind'] == 'stack':
            result.update(Name=node['label'], Orientation={'horizontal': 'Horizontal', 'vertical': 'Vertical'}[node['orientation']],
                **{'@Children': [emit(child) for child in node['children']]})
        else:
            result.update(Name=node['view_type'], SelectionChannel=node['selection_channel'])
        for field in ('width', 'height'):
            if field in node:
                result[field.title()] = node[field]
        return result
    return {'Layout': {'Name': checked.get('workspace_name', name), 'StackPanel': emit(checked['root'])}}


def blueprint_view_types(blueprint: Any) -> list[str]:
    checked = validate_blueprint(blueprint)
    return sorted({row['view_type'] for row in checked['nodes'] if row['kind'] == 'view'})


def declared_layout_matches(expected: Any, actual: Any) -> bool:
    """Native default fields may be added; declared fields/order must be retained."""
    if isinstance(expected, Mapping):
        return isinstance(actual, Mapping) and all(key in actual and declared_layout_matches(value, actual[key])
            for key, value in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(expected) == len(actual) and all(
            declared_layout_matches(left, right) for left, right in zip(expected, actual))
    return type(expected) is type(actual) and expected == actual
