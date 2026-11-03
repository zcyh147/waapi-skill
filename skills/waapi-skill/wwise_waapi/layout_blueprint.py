"""Closed layout declarations; native IDs and wire fields remain Gateway-owned."""
from __future__ import annotations

from copy import deepcopy
import json
import math
import re
from typing import Any, Mapping
from uuid import uuid4

from .authoring_layout import MAX_LAYOUT_RESULT_BYTES, validate_layout_read_result
from .canonical import canonical_json_bytes

CONTRACT = 'waapi-skill.layout-blueprint/v1'
MAX_NODES = 128
# A serialized stack adds a mapping and child list per level. Leave room for
# Layout/window wrappers under the existing 32-level bounded read contract.
MAX_DEPTH = 14
# Existing Draft seals are capped at 256 KiB and retain both the compiled request
# and its closed declaration proof. Bound each part to 112 KiB, leaving 32 KiB
# for identities, connection/project proof and seal framing. These are Gateway
# resource policies, not native Wwise restrictions.
MAX_BYTES = 112 * 1024
MAX_COMPILED_BYTES = 112 * 1024
DRAFT_SEAL_FRAME_RESERVE_BYTES = 32 * 1024
READBACK_FRAME_RESERVE_BYTES = MAX_LAYOUT_RESULT_BYTES - MAX_COMPILED_BYTES
EDITOR_STATES = {'normal': 'Normal', 'maximized': 'Maximized', 'minimized': 'Minimized'}
ELEMENT_TYPES = {'stack': 'StackPanel', 'view': 'View', 'object_panel': 'ObjectPanel', 'object_tabs': 'ObjectTabPanel'}
PLACEMENT_FIELDS = {'flags': 'WindowPlacement_Flags', 'minimum_x': 'WindowPlacement_MinPos_X',
    'minimum_y': 'WindowPlacement_MinPos_Y', 'maximum_x': 'WindowPlacement_MaxPos_X', 'maximum_y': 'WindowPlacement_MaxPos_Y',
    'left': 'WindowPlacement_NormalPos_Left', 'top': 'WindowPlacement_NormalPos_Top',
    'right': 'WindowPlacement_NormalPos_Right', 'bottom': 'WindowPlacement_NormalPos_Bottom'}
HISTORY_FIELDS = {'audio_devices': 'AudioDeviceLastTabPositions', 'effects': 'EffectLastTabPositions',
    'fallback': 'FallbackLastTabPositions', 'last_positions': 'LastPositions', 'metadata': 'MetadataLastTabPositions',
    'object_types': 'ObjectTypeLastTabPositions', 'plugin_inner_objects': 'PluginInnerObjectLastTabPositions',
    'source_plugins': 'SourcePluginLastTabPositions'}


def _text(value: Any) -> bool:
    return isinstance(value, str) and '\x00' not in value and len(value) <= 4096


def _validate_placement(value: Any) -> None:
    if (not isinstance(value, dict) or not set(PLACEMENT_FIELDS) <= set(value)
            or not set(value) <= set(PLACEMENT_FIELDS) | {'state'}
            or any(not _text(value[field]) for field in PLACEMENT_FIELDS)
            or ('state' in value and (not isinstance(value['state'], str) or value['state'] not in EDITOR_STATES))):
        raise ValueError('Layout blueprint window placement requires closed position strings and optional normal, maximized or minimized state')


def _compile_placement(value: Mapping[str, Any]) -> dict[str, str]:
    result = {native: value[field] for field, native in PLACEMENT_FIELDS.items()}
    if 'state' in value: result['WindowPlacement_ShowCmd'] = EDITOR_STATES[value['state']]
    return result


def _compile_data_entries(entries: Any, *, depth: int = 0, budget: list[int] | None = None) -> dict[str, Any]:
    """Construct the source-open ViewData object from closed, typed entry facts."""
    budget = [0] if budget is None else budget
    if not isinstance(entries, list) or len(entries) > MAX_NODES:
        raise ValueError('Layout blueprint data_entries requires a bounded list of typed entries')
    result = {}
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) != {'name', 'value'} or not _text(entry['name'])
                or entry['name'] in result):
            raise ValueError('Layout blueprint data entry requires a unique bounded name and typed value')
        result[entry['name']] = _compile_data_value(entry['value'], depth=depth, budget=budget)
    return result


def _compile_data_value(value: Any, *, depth: int, budget: list[int]) -> Any:
    budget[0] += 1
    if budget[0] > 4096 or depth > 8 or not isinstance(value, dict) or not isinstance(value.get('kind'), str):
        raise ValueError('Layout blueprint typed data exceeds its depth/node budget or lacks a closed kind')
    kind = value['kind']
    field = {'object': 'entries', 'array': 'items', 'null': None}.get(kind, 'value')
    if set(value) != ({'kind', field} if field else {'kind'}):
        raise ValueError('Layout blueprint typed data value has missing or unknown fields')
    if kind == 'null': return None
    if kind == 'object': return _compile_data_entries(value['entries'], depth=depth + 1, budget=budget)
    if kind == 'array':
        if not isinstance(value['items'], list) or len(value['items']) > MAX_NODES:
            raise ValueError('Layout blueprint typed data array exceeds its item bound')
        return [_compile_data_value(item, depth=depth + 1, budget=budget) for item in value['items']]
    item = value['value']
    if ((kind == 'string' and _text(item)) or (kind == 'boolean' and type(item) is bool)
            or (kind == 'integer' and type(item) is int)
            or (kind == 'number' and type(item) in (int, float) and (type(item) is int or math.isfinite(item)))):
        return item
    raise ValueError('Layout blueprint typed data value must match its disclosed scalar kind')


def blueprint_schema() -> dict[str, Any]:
    text = {'type': 'string', 'maxLength': 4096, 'pattern': r'^[^\u0000]*$'}
    key = {'type': 'string', 'pattern': r'^[A-Za-z][A-Za-z0-9_-]{0,63}$'}
    common = {'key': key, 'width': text, 'height': text}
    data_entries = {'type': 'array', 'maxItems': MAX_NODES, 'items': {'type': 'object', 'additionalProperties': False,
        'properties': {'name': text, 'value': {'$ref': '#/$defs/data_value'}}, 'required': ['name', 'value']}}
    data_variants = [{'type': 'object', 'additionalProperties': False,
        'properties': {'kind': {'const': kind}, 'value': schema}, 'required': ['kind', 'value']}
        for kind, schema in [('string', text), ('boolean', {'type': 'boolean'}), ('integer', {'type': 'integer'}), ('number', {'type': 'number'})]]
    data_variants += [
        {'type': 'object', 'additionalProperties': False, 'properties': {'kind': {'const': 'null'}}, 'required': ['kind']},
        {'type': 'object', 'additionalProperties': False, 'properties': {'kind': {'const': 'object'}, 'entries': data_entries}, 'required': ['kind', 'entries']},
        {'type': 'object', 'additionalProperties': False, 'properties': {'kind': {'const': 'array'},
            'items': {'type': 'array', 'maxItems': MAX_NODES, 'items': {'$ref': '#/$defs/data_value'}}}, 'required': ['kind', 'items']}]
    placement = {'type': 'object', 'additionalProperties': False,
        'properties': {**{field: text for field in PLACEMENT_FIELDS}, 'state': {'enum': list(EDITOR_STATES)}},
        'required': list(PLACEMENT_FIELDS)}
    history_row = {'type': 'object', 'additionalProperties': False,
        'properties': {'view_name': text, 'placement': placement}, 'required': ['view_name', 'placement']}
    editor_fields = {'view_identifier': {**text, 'description': 'Serialized editor identifier, not authority to target a live view.'},
        'plugin_identifier': text, 'effect_index': text}
    editor = {'type': 'object', 'additionalProperties': False,
        'properties': {**editor_fields, 'include_type': {'type': 'boolean'}}, 'required': list(editor_fields)}
    preferred = {'type': 'object', 'additionalProperties': False,
        'properties': {**editor_fields, 'height': text}, 'required': [*editor_fields, 'height']}
    stack = {'type': 'object', 'additionalProperties': False,
        'properties': {**common, 'kind': {'const': 'stack'}, 'label': text, 'include_type': {'type': 'boolean'},
            'orientation': {'enum': ['horizontal', 'vertical']},
            'children': {'type': 'array', 'maxItems': MAX_NODES, 'uniqueItems': True, 'items': key}},
        'required': ['key', 'kind', 'label', 'orientation', 'children']}
    view = {'type': 'object', 'additionalProperties': False,
        'properties': {**common, 'kind': {'const': 'view'}, 'view_type': {**text, 'minLength': 1},
            'selection_channel': text, 'data_entries': data_entries, 'include_type': {'type': 'boolean'}},
        'required': ['key', 'kind', 'view_type', 'selection_channel']}
    tabs = {'type': 'object', 'additionalProperties': False,
        'properties': {**common, 'kind': {'const': 'object_tabs'}, 'label': text},
        'required': ['key', 'kind', 'label']}
    sidebar_properties = {'width': text, 'collapse_state': text}
    panel = {'type': 'object', 'additionalProperties': False,
        'properties': {**common, 'kind': {'const': 'object_panel'}, 'label': text,
            'editor_state': {'enum': list(EDITOR_STATES)}, 'bottom_editor_state': {'enum': list(EDITOR_STATES)},
            'editor_priority': {'type': 'array', 'maxItems': MAX_NODES, 'items': editor},
            'preferred_heights': {'type': 'array', 'maxItems': MAX_NODES, 'items': preferred},
            'sidebar': {'type': 'object', 'additionalProperties': False,
                'properties': sidebar_properties, 'required': ['width', 'collapse_state']}},
        'required': ['key', 'kind', 'label']}
    return {'$id': 'urn:waapi-skill:layout-blueprint:v1', '$defs': {'data_value': {'oneOf': data_variants}},
        'type': 'object', 'additionalProperties': False,
        'properties': {'contract': {'const': CONTRACT}, 'root': key,
            'workspace_name': {**text, 'description': 'Name inside the layout document; distinct from its temporary lookup name. Omission uses the lookup name.'},
            'nodes': {'type': 'array', 'minItems': 0, 'maxItems': MAX_NODES, 'items': {'oneOf': [stack, view, panel, tabs]}},
            'floating_windows': {'type': 'array', 'maxItems': MAX_NODES, 'items': {'type': 'object', 'additionalProperties': False,
                'properties': {'root': key, 'placement': placement}, 'required': ['placement']}},
            'position_history': {'type': 'object', 'additionalProperties': False,
                'properties': {field: {'type': 'array', 'maxItems': MAX_NODES, 'items': history_row} for field in HISTORY_FIELDS}}},
        'required': ['contract', 'nodes'],
        'source_interpretations': {
            'Element': 'The retained capital OneOf lists the supported element kinds; the source definition is not globally rewritten.',
            'SideBar': 'The reflected singular sidebar remains available. The 2024 enum is a malformed scalar SideBar; the local constructor uses that exact tag, without rewriting the source schema.',
            'ViewHolder': 'Floating windows follow the explicit ViewHolder fields; conflicting allOf Element is retained as unresolved source semantics.',
            'native_acceptance': 'Closed construction and retained read serialization do not prove native setLayout input acceptance.'},
        'unresolved_inputs': {
            'splitter': 'The request definition requires @Children but declares no such property and forbids extra properties. Retained read-only childless @type/ID rows do not establish setLayout input legality.',
            'object_tabs.children': 'Retained read-only ObjectTabPanel rows contain @Children; the request definition forbids this property. No input alternative is inferred.',
            'object_panel.sidebar_left,sidebar_right': 'Retained read-only rows contain SideBarLeft/SideBarRight and Visibility; the request definition exposes only SideBar. No input alternative is inferred.',
            'preferred_heights': 'Requests use the reflected unprefixed editor identifiers. Readbacks may use the three retained Editor-prefixed aliases; this does not establish their request legality.'},
        'gateway_bounds': {'maximum_depth': MAX_DEPTH, 'maximum_business_input_utf8_bytes': MAX_BYTES,
            'maximum_view_data_depth': 8, 'maximum_view_data_nodes': 4096,
            'maximum_serialized_layout_utf8_bytes': MAX_COMPILED_BYTES,
            'maximum_readback_utf8_bytes': MAX_LAYOUT_RESULT_BYTES,
            'readback_frame_reserve_bytes': READBACK_FRAME_RESERVE_BYTES,
            'draft_seal_frame_reserve_bytes': DRAFT_SEAL_FRAME_RESERVE_BYTES,
            'maximum_rendered_terminal_request_utf8_bytes': 256 * 1024,
            'maximum_terminal_stdout_utf8_bytes': 280 * 1024,
            'terminal_capacity_scope': 'exact closed setLayout blueprint only; ordinary terminal budget remains 24 KiB'}}


def validate_blueprint(value: Any) -> dict[str, Any]:
    try:
        size = len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8'))
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError('Layout blueprint must be a bounded JSON business declaration') from exc
    if size > MAX_BYTES:
        raise ValueError('Layout blueprint exceeds its UTF-8 byte bound')
    if (not isinstance(value, dict) or not {'contract', 'nodes'} <= set(value)
            or not set(value) <= {'contract', 'root', 'nodes', 'workspace_name', 'floating_windows', 'position_history'}
            or value['contract'] != CONTRACT or not isinstance(value['nodes'], list)
            or not 0 <= len(value['nodes']) <= MAX_NODES):
        raise ValueError('Layout blueprint requires its exact bounded closed node declaration')
    if 'workspace_name' in value and (not isinstance(value['workspace_name'], str)
            or '\x00' in value['workspace_name'] or len(value['workspace_name']) > 4096):
        raise ValueError('Layout blueprint workspace name must be a bounded string without NUL')
    def local_key(key: Any) -> bool:
        return isinstance(key, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', key) is not None
    if 'root' in value and not local_key(value['root']):
        raise ValueError('Layout blueprint root must be a local node key')
    windows = value.get('floating_windows', [])
    if not isinstance(windows, list) or len(windows) > MAX_NODES:
        raise ValueError('Layout blueprint floating_windows requires a bounded array')
    for window in windows:
        if (not isinstance(window, dict) or 'placement' not in window or not set(window) <= {'root', 'placement'}
                or ('root' in window and not local_key(window['root']))):
            raise ValueError('Layout blueprint floating window requires placement and an optional local root')
        _validate_placement(window['placement'])
    histories = value.get('position_history', {})
    if not isinstance(histories, dict) or not set(histories) <= set(HISTORY_FIELDS):
        raise ValueError('Layout blueprint position_history requires disclosed history names')
    for rows in histories.values():
        if not isinstance(rows, list) or len(rows) > MAX_NODES:
            raise ValueError('Layout blueprint position history requires bounded arrays')
        for row in rows:
            if not isinstance(row, dict) or set(row) != {'view_name', 'placement'} or not _text(row['view_name']):
                raise ValueError('Layout blueprint position history row requires a view_name and placement')
            _validate_placement(row['placement'])
    for node in value['nodes']:
        if isinstance(node, dict):
            if node.get('kind') == 'splitter':
                raise ValueError('Layout blueprint splitter input remains unresolved: contradictory required @Children lacks a request property shape; read-only serialization is not input proof')
            if node.get('kind') == 'object_tabs' and 'children' in node:
                raise ValueError('Layout blueprint object_tabs children input remains unresolved: the request definition forbids @Children despite retained read-only serialization')
            if node.get('kind') == 'object_panel' and {'sidebar_left', 'sidebar_right'} & set(node):
                raise ValueError('Layout blueprint left/right sidebar input remains unresolved: the request definition exposes only the singular sidebar despite retained read-only serialization')
        if not isinstance(node, dict) or not isinstance(node.get('kind'), str) or node['kind'] not in ELEMENT_TYPES:
            raise ValueError('Layout blueprint node requires a disclosed closed kind')
        required = {'key', 'kind', 'label'}
        optional = {'width', 'height'}
        if node['kind'] == 'stack': required |= {'orientation', 'children'}
        elif node['kind'] == 'view':
            required = {'key', 'kind', 'view_type', 'selection_channel'}
            optional.add('data_entries')
        elif node['kind'] == 'object_panel': optional |= {'editor_state', 'bottom_editor_state', 'editor_priority', 'preferred_heights', 'sidebar'}
        if node['kind'] in {'stack', 'view'}: optional.add('include_type')
        if not required <= set(node) or not set(node) <= required | optional or not local_key(node['key']):
            raise ValueError('Layout blueprint node has missing or unknown closed fields')
        text_fields = ['view_type', 'selection_channel'] if node['kind'] == 'view' else (['label'] if 'label' in node else [])
        text_fields += [field for field in ('width', 'height') if field in node]
        if any(not isinstance(node[field], str) or '\x00' in node[field] or len(node[field]) > 4096 for field in text_fields):
            raise ValueError('Layout blueprint text values must be bounded strings without NUL')
        if 'include_type' in node and type(node['include_type']) is not bool:
            raise ValueError('Layout blueprint include_type requires an explicit Boolean')
        if node['kind'] == 'stack' and (not isinstance(node['orientation'], str) or node['orientation'] not in {'horizontal', 'vertical'}):
            raise ValueError('Layout blueprint stack requires horizontal or vertical orientation')
        if 'children' in node:
            if (not isinstance(node['children'], list) or len(node['children']) > MAX_NODES
                    or any(not local_key(child) for child in node['children'])
                    or len(set(node['children'])) != len(node['children'])):
                raise ValueError('Layout blueprint stack requires an exact orientation and ordered unique children')
        elif node['kind'] == 'view' and not node['view_type']:
            raise ValueError('Layout blueprint view requires a nonempty live view type')
        if 'data_entries' in node: _compile_data_entries(node['data_entries'])
        if node['kind'] == 'object_panel':
            for field in ('editor_state', 'bottom_editor_state'):
                if field in node and (not isinstance(node[field], str) or node[field] not in EDITOR_STATES):
                    raise ValueError('Layout blueprint editor state requires normal, maximized or minimized')
            for field in ('editor_priority', 'preferred_heights'):
                if field in node:
                    rows = node[field]
                    if not isinstance(rows, list) or len(rows) > MAX_NODES:
                        raise ValueError('Layout blueprint editor lists require bounded arrays')
                    for row in rows:
                        required_fields = {'view_identifier', 'plugin_identifier', 'effect_index'}
                        optional_fields = {'include_type'} if field == 'editor_priority' else set()
                        if field == 'preferred_heights': required_fields.add('height')
                        if (not isinstance(row, dict) or not required_fields <= set(row)
                                or not set(row) <= required_fields | optional_fields
                                or any(not isinstance(row[token], str) or '\x00' in row[token] or len(row[token]) > 4096 for token in required_fields)
                                or ('include_type' in row and type(row['include_type']) is not bool)):
                            raise ValueError('Layout blueprint editor row requires closed string identifiers and preferences')
            for field in ('sidebar',):
                if field not in node: continue
                sidebar = node[field]
                fields = {'width', 'collapse_state'}
                if (not isinstance(sidebar, dict) or set(sidebar) != fields
                        or any(not _text(sidebar[token]) for token in ('width', 'collapse_state'))
                        ):
                    raise ValueError('Layout blueprint sidebar requires bounded width and collapse_state strings')
    nodes = {row['key']: row for row in value['nodes']}
    roots = ([value['root']] if 'root' in value else []) + [window['root'] for window in windows if 'root' in window]
    if len(nodes) != len(value['nodes']) or any(key not in nodes or nodes[key]['kind'] != 'stack' for key in roots):
        raise ValueError('Layout blueprint requires unique local node keys and stack roots')
    visited: set[str] = set()
    def walk(key: str, depth: int) -> None:
        if depth > MAX_DEPTH or key not in nodes or key in visited:
            raise ValueError('Layout blueprint must be one bounded tree without cycles or shared nodes')
        visited.add(key)
        for child in nodes[key].get('children', []):
            walk(child, depth + 1)
    for root in roots: walk(root, 1)
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
        result = {'@type': ELEMENT_TYPES[node['kind']], 'ID': node_ids[key]}
        if node.get('include_type') is False: del result['@type']
        if node['kind'] == 'stack':
            result.update(Name=node['label'], Orientation={'horizontal': 'Horizontal', 'vertical': 'Vertical'}[node['orientation']],
                **{'@Children': [emit(child) for child in node['children']]})
        elif node['kind'] == 'view':
            result.update(Name=node['view_type'], SelectionChannel=node['selection_channel'])
            if 'data_entries' in node: result['ViewData'] = _compile_data_entries(node['data_entries'])
        else:
            if 'label' in node: result['Name'] = node['label']
            if 'children' in node: result['@Children'] = [emit(child) for child in node['children']]
            for field in ('editor_state', 'bottom_editor_state'):
                if field in node:
                    result[{'editor_state': 'EditorState', 'bottom_editor_state': 'BottomEditorState'}[field]] = EDITOR_STATES[node[field]]
            for field, native in (('editor_priority', 'EditorPriority'), ('preferred_heights', 'PreferredHeights')):
                if field in node:
                    result[native] = []
                    for row in node[field]:
                        item = {'UniqueViewId': row['view_identifier'], 'PluginId': row['plugin_identifier'], 'EffectIndex': row['effect_index']}
                        if field == 'preferred_heights': item.update({'@type': 'PreferredHeight', 'Height': row['height']})
                        elif row.get('include_type', False): item['@type'] = 'EditorId'
                        result[native].append(item)
            if 'sidebar' in node:
                result['SideBar'] = {'@type': 'SideBar', 'Width': node['sidebar']['width'], 'CollapseState': node['sidebar']['collapse_state']}
        for field in ('width', 'height'):
            if field in node:
                result[field.title()] = node[field]
        return result
    layout = {'Name': checked.get('workspace_name', name)}
    if 'root' in checked: layout['StackPanel'] = emit(checked['root'])
    if 'floating_windows' in checked:
        layout['Undocked'] = [{'@type': 'ViewHolder', **_compile_placement(window['placement']),
            **({'StackPanel': emit(window['root'])} if 'root' in window else {})} for window in checked['floating_windows']]
    for field, rows in checked.get('position_history', {}).items():
        layout[HISTORY_FIELDS[field]] = [{'@type': 'ViewPosition', 'Name': row['view_name'], **_compile_placement(row['placement'])} for row in rows]
    result = {'Layout': layout}
    if len(canonical_json_bytes(result)) > MAX_COMPILED_BYTES:
        raise ValueError('Compiled layout exceeds the bounded native readback byte ceiling')
    validate_layout_read_result('contents', result)
    return result


def blueprint_view_types(blueprint: Any) -> list[str]:
    checked = validate_blueprint(blueprint)
    return sorted({row['view_type'] for row in checked['nodes'] if row['kind'] == 'view'})


def _preferred_height_readback(expected: Any, actual: Any, path: str) -> Any:
    # These three spelling differences are present in both retained Authoring
    # reads. Apply them only to actual PreferredHeights rows, never ViewData.
    if (isinstance(expected, Mapping) and isinstance(actual, Mapping)
            and expected.get('@type') == actual.get('@type') == 'PreferredHeight'
            and re.search(r'/PreferredHeights/[0-9]+$', path) and '/ViewData/' not in path):
        normalized = dict(actual)
        for field in ('UniqueViewId', 'PluginId', 'EffectIndex'):
            alias = 'Editor' + field
            if alias in actual:
                if field in actual and actual[field] != actual[alias]: return {}
                normalized[field] = actual[alias]
        return normalized
    return actual


def _optional_type_mismatch(expected: Mapping[str, Any], actual: Any, path: str) -> bool:
    if not isinstance(actual, Mapping) or '@type' in expected or '@type' not in actual or '/ViewData/' in path:
        return False
    kind = None
    if 'ID' in expected:
        if {'Name', 'SelectionChannel'} <= set(expected): kind = 'View'
        elif {'Orientation', '@Children'} <= set(expected): kind = 'StackPanel'
    elif re.search(r'/EditorPriority/[0-9]+$', path) and {'UniqueViewId', 'PluginId', 'EffectIndex'} <= set(expected):
        kind = 'EditorId'
    return kind is not None and actual['@type'] != kind


def _root_stack_readback(expected: Mapping[str, Any], actual: Any, path: str) -> Any:
    # Layout.StackPanel fixes the structural kind in both pinned definitions;
    # its @type is optional and matching native serializers omit only this root
    # tag. Keep explicit conflicts and every other declared field observable.
    if (path == '/Layout/StackPanel' and expected.get('@type') == 'StackPanel'
            and isinstance(actual, Mapping) and '@type' not in actual):
        return {**actual, '@type': 'StackPanel'}
    return actual


def declared_layout_matches(expected: Any, actual: Any, *, _path: str = '') -> bool:
    """Native default fields may be added; declared fields/order must be retained."""
    if isinstance(expected, Mapping):
        if _optional_type_mismatch(expected, actual, _path): return False
        actual = _root_stack_readback(expected, _preferred_height_readback(expected, actual, _path), _path)
        return isinstance(actual, Mapping) and all(key in actual and declared_layout_matches(value, actual[key],
            _path=_path + '/' + key.replace('~', '~0').replace('/', '~1'))
            for key, value in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(expected) == len(actual) and all(
            declared_layout_matches(left, right, _path=_path + '/' + str(index)) for index, (left, right) in enumerate(zip(expected, actual)))
    return type(expected) is type(actual) and expected == actual


def declared_layout_mismatches(expected: Any, actual: Any) -> list[dict[str, str]]:
    """Describe at most sixteen declared-field mismatches without copying values."""
    mismatches: list[dict[str, str]] = []
    def walk(left: Any, right: Any, path: str) -> None:
        if len(mismatches) >= 16:
            return
        if isinstance(left, Mapping):
            if _optional_type_mismatch(left, right, path):
                mismatches.append({'path': path + '/@type', 'reason': 'explicit type conflicts with the declared element kind'})
                return
            right = _root_stack_readback(left, _preferred_height_readback(left, right, path), path)
            if not isinstance(right, Mapping):
                mismatches.append({'path': path, 'reason': 'expected object'})
                return
            for key, value in left.items():
                child_path = path + '/' + key.replace('~', '~0').replace('/', '~1')
                if key not in right:
                    if len(mismatches) < 16:
                        mismatches.append({'path': child_path, 'reason': 'declared field missing'})
                else:
                    walk(value, right[key], child_path)
        elif isinstance(left, list):
            if not isinstance(right, list):
                mismatches.append({'path': path, 'reason': 'expected ordered array'})
                return
            if len(left) != len(right):
                mismatches.append({'path': path, 'reason': 'declared child count changed'})
            for index, (left_item, right_item) in enumerate(zip(left, right)):
                walk(left_item, right_item, path + '/' + str(index))
        elif type(left) is not type(right) or left != right:
            mismatches.append({'path': path, 'reason': 'declared value or type changed'})
    walk(expected, actual, '')
    return mismatches
