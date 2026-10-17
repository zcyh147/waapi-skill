"""Controlled widget/template constructors grounded in exact WAFM definitions."""
from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Mapping


MAX_NODES = 2048
MAX_DEPTH = 16
MAX_TEXT = 8192


def _object(value: Any, required: set[str], optional: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not required <= set(value) or set(value) - required - optional:
        raise ValueError(label + ' requires ' + ', '.join(sorted(required)) + '; only disclosed optional fields are accepted')
    return dict(value)


def text(value: Any, label: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value) or '\x00' in value or len(value.encode('utf-8')) > MAX_TEXT:
        raise ValueError(label + ' requires bounded UTF-8 text')
    return value


def value_schema() -> dict[str, Any]:
    return {'description': 'Closed recursive value constructors; no native JSON envelope or model dump.',
        'oneOf': [
            {'type': 'object', 'additionalProperties': False, 'required': ['kind', field],
             'properties': {'kind': {'const': kind}, field: schema}}
            for kind, field, schema in [('text', 'text', {'type': 'string', 'maxLength': MAX_TEXT}),
                ('integer', 'integer', {'type': 'integer'}), ('number', 'number', {'type': 'number'}),
                ('boolean', 'boolean', {'type': 'boolean'}),
                ('list', 'items', {'type': 'array', 'maxItems': MAX_NODES, 'items': {'$ref': '#/definitions/businessValue'}}),
                ('record', 'entries', {'type': 'array', 'maxItems': MAX_NODES, 'items': {
                    'type': 'object', 'additionalProperties': False, 'required': ['key', 'value'],
                    'properties': {'key': {'type': 'string'}, 'value': {'$ref': '#/definitions/businessValue'}}}})]
            ] + [{'type': 'object', 'additionalProperties': False, 'required': ['kind'], 'properties': {'kind': {'const': 'null'}}}]}


def compile_value(value: Any, *, _budget: list[int] | None = None, _depth: int = 0) -> Any:
    budget = [MAX_NODES] if _budget is None else _budget
    budget[0] -= 1
    if budget[0] < 0 or _depth > MAX_DEPTH:
        raise ValueError('Widget value exceeds its construction node/depth budget')
    if not isinstance(value, Mapping):
        raise ValueError('Widget values use a disclosed typed value constructor')
    kind = value.get('kind')
    fields = {'text': 'text', 'integer': 'integer', 'number': 'number', 'boolean': 'boolean', 'list': 'items', 'record': 'entries'}
    if kind == 'null':
        _object(value, {'kind'}, set(), 'Null value')
        return None
    if kind not in fields:
        raise ValueError('Unknown widget value kind; choose text, integer, number, boolean, null, list or record')
    field = fields[kind]
    _object(value, {'kind', field}, set(), 'Widget value')
    raw = value[field]
    if kind == 'text': return text(raw, 'Text value', empty=True)
    if kind == 'integer' and type(raw) is int: return raw
    if kind == 'number' and type(raw) in (int, float) and math.isfinite(raw): return raw
    if kind == 'boolean' and type(raw) is bool: return raw
    if kind in {'list', 'record'} and isinstance(raw, list) and len(raw) <= MAX_NODES:
        if kind == 'list':
            return [compile_value(child, _budget=budget, _depth=_depth + 1) for child in raw]
        result = {}
        for child in raw:
            row = _object(child, {'key', 'value'}, set(), 'Record entry')
            key = text(row['key'], 'Record key', empty=True)
            if key in result: raise ValueError('Record value contains duplicate keys')
            result[key] = compile_value(row['value'], _budget=budget, _depth=_depth + 1)
        return result
    raise ValueError('Widget value does not match its declared kind')


def _definition(version: str, name: str, document: str = 'wafm_definitions.json', *, graph: Any = None) -> dict[str, Any]:
    from .schema_inventory import load_authoring_definition_graph
    graph = load_authoring_definition_graph(version) if graph is None else graph
    def resolve(node: Mapping[str, Any], doc: str) -> dict[str, Any]:
        result = deepcopy(dict(node))
        if '$ref' in result:
            ref = result.pop('$ref')
            external, fragment = ref.split('#', 1)
            target_doc = external or doc
            target = graph.documents[target_doc]
            for segment in fragment.lstrip('/').split('/'):
                target = target[segment]
            result = {**resolve(target, target_doc), **result}
        properties = dict(result.get('properties', {}))
        required = list(result.get('required', []))
        for base in result.pop('allOf', []):
            inherited = resolve(base, doc)
            properties = {**inherited.get('properties', {}), **properties}
            required = list(dict.fromkeys([*inherited.get('required', []), *required]))
        if properties: result['properties'] = properties
        if required: result['required'] = required
        return result
    return resolve(graph.documents[document]['definitions'][name], document)


def widget_catalog(version: str) -> dict[str, Any]:
    from .schema_inventory import load_authoring_definition_graph
    graph = load_authoring_definition_graph(version)
    definitions = graph.documents['wafm_definitions.json']['definitions']
    result = {}
    for name in definitions:
        if name.endswith('Descriptor') and name != 'widgetDescriptor':
            schema = _definition(version, name, graph=graph)
            for kind in schema.get('properties', {}).get('Type', {}).get('enum', []):
                result[kind] = {'definition': name, 'attributes': {key: value for key, value in schema['properties'].items() if key not in {'Name', 'Type'}}}
    return result


def _attributes(value: Any, *, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(value, list) or len(value) > 128:
        raise ValueError('Widget/layout attributes require at most 128 typed assignments')
    result = {}
    budget = [MAX_NODES]
    for row in value:
        row = _object(row, {'attribute', 'value'}, set(), 'Attribute assignment')
        name = row['attribute']
        if not isinstance(name, str) or name not in allowed or name in result:
            raise ValueError('Unknown, reserved or duplicate widget/layout attribute: ' + str(name) + '; choose ' + ', '.join(sorted(allowed)))
        result[name] = compile_value(row['value'], _budget=budget)
    return result


def compile_template(plan: Mapping[str, Any], *, version: str, template_name: str) -> dict[str, Any]:
    _object(plan, {'template_key', 'root_widget', 'widgets', 'layouts'}, {'registration_form', 'template_version', 'metadata'}, 'Template plan')
    text(plan['template_key'], 'Template key')
    root = text(plan['root_widget'], 'Root widget')
    if not isinstance(plan['widgets'], list) or not isinstance(plan['layouts'], list) or len(plan['widgets']) + len(plan['layouts']) > MAX_NODES:
        raise ValueError('Template widgets/layouts exceed their bounded collection')
    catalog = widget_catalog(version)
    names = set()
    widgets = []
    for raw in plan['widgets']:
        row = _object(raw, {'key', 'kind'}, {'attributes'}, 'Widget constructor')
        name = text(row['key'], 'Widget key')
        if name in names: raise ValueError('Template has duplicate widget/layout keys')
        names.add(name)
        if row['kind'] not in catalog: raise ValueError('Unknown widget kind; choose ' + ', '.join(sorted(catalog)))
        attributes = _attributes(row.get('attributes', []), allowed=set(catalog[row['kind']]['attributes']))
        widgets.append({'Name': name, 'Type': row['kind'], **attributes})
    widget_names = set(names)
    kinds = {'AnchorLayout': 'anchorLayoutDefinition', 'BinLayout': 'binLayoutDefinition', 'GroupBox': 'groupBoxDefinition',
             'OverflowHBox': 'overflowHBoxDefinition', 'SplitLayout': 'splitLayoutDefinition', 'DockWidgetArea': 'dockWidgetAreaDefinition'}
    from .schema_inventory import load_authoring_definition_graph
    graph = load_authoring_definition_graph(version)
    kinds = {kind: name for kind, name in kinds.items() if name in graph.documents['wafm_definitions.json']['definitions']}
    budget = [MAX_NODES]
    def layout(raw: Any, depth: int = 0) -> dict[str, Any]:
        budget[0] -= 1
        if depth > MAX_DEPTH or budget[0] < 0: raise ValueError('Layout construction exceeds its node/depth budget')
        row = _object(raw, {'key', 'kind', 'children'}, {'attributes', 'splitters'}, 'Layout constructor')
        name = text(row['key'], 'Layout key')
        if name in names: raise ValueError('Template has duplicate widget/layout keys')
        names.add(name)
        kind = row['kind']
        if kind not in kinds: raise ValueError('Unknown layout kind; choose ' + ', '.join(kinds))
        schema = _definition(version, kinds[kind], graph=graph)
        allowed = set(schema['properties']) - {'Name', 'Type', 'Children', 'Splitters'}
        result = {'Name': name, 'Type': kind, **_attributes(row.get('attributes', []), allowed=allowed)}
        if not isinstance(row['children'], list) or len(row['children']) > MAX_NODES:
            raise ValueError('Layout children require a bounded collection')
        children = []
        for child in row['children']:
            child = _object(child, set(), {'widget', 'layout', 'positions', 'anchors', 'section', 'width', 'minimum_size'}, 'Layout child')
            if ('widget' in child) == ('layout' in child): raise ValueError('Layout child chooses exactly one owned widget or nested layout')
            if 'widget' in child:
                if child['widget'] not in widget_names: raise ValueError('Layout child references an unknown template widget')
                native = {'Name': child['widget']}
            else:
                native = layout(child['layout'], depth + 1)
            for key, native_key in [('positions','Positions'), ('anchors','AnchorSets'), ('section','Section'), ('width','Width'), ('minimum_size','MinSize')]:
                if key in child: native[native_key] = deepcopy(child[key])
            children.append(native)
        result['Children'] = children
        if 'splitters' in row:
            if kind != 'SplitLayout' or not isinstance(row['splitters'], list) or len(row['splitters']) > MAX_NODES:
                raise ValueError('Only SplitLayout accepts a bounded splitter constructor collection')
            splitters = []
            for splitter in row['splitters']:
                splitter = _object(splitter, {'key', 'attributes'}, set(), 'Splitter constructor')
                splitter_name = text(splitter['key'], 'Splitter key')
                if splitter_name in names: raise ValueError('Template has duplicate splitter/widget/layout keys')
                names.add(splitter_name)
                fields = set(widget_catalog(version)['LayoutSplitter']['attributes'])
                splitters.append({'Name': splitter_name, 'Type': 'LayoutSplitter', **_attributes(splitter['attributes'], allowed=fields)})
            result['Splitters'] = splitters
        return result
    layouts = [layout(row) for row in plan['layouts']]
    if root not in names: raise ValueError('Template root must name one of its constructed widgets/layouts')
    definition = {'Version': plan.get('template_version', 1), 'Type': 'Dialog', 'RootWidget': root,
                  'Widgets': widgets, 'Layouts': {'Settings': layouts}}
    if 'metadata' in plan:
        metadata = compile_value(plan['metadata'])
        if not isinstance(metadata, dict): raise ValueError('Template metadata must use a record value constructor')
        definition['Metadata'] = metadata
    form = plan.get('registration_form', 'template_attribute')
    if form not in {'template_attribute', 'named_template'}: raise ValueError('Unknown template registration form')
    wafm = {'template': template_name, 'definition': definition} if form == 'template_attribute' else {template_name: definition}
    from .builders.schema import validate_resolved_semantic_payload
    validate_resolved_semantic_payload('ak.wwise.ui.model.registerWafm', {'wafm': wafm}, {}, version=version, authoring_ui_profile=True)
    # Reject native-schema permissiveness: all constructor fields are closed,
    # including attribute records whose native value branch is intentionally open.
    return wafm
