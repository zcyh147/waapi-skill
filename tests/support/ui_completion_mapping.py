"""Exact #188/#189 lightweight UI correspondence; mapping is not UI effect proof."""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tests.maintenance.branch_coverage_audit import digest, schema_branches
from tests.support.topic_completion_mapping import _path

LIB = 'skills/waapi-skill/wwise_waapi/'
GATEWAY = 'skills/waapi-skill/scripts/gateway.py'
BASE = 'tests/fixtures/branch-evidence/product/ui-195-r1/'
POLICY = 'docs/plans/full-waapi-coverage/SPEC.md'
OWNERS = {
    **{'ak.wwise.ui.layout.' + name: 188 for name in ('closeView', 'dockView', 'getCurrentLayoutName',
        'getElementRectangle', 'getLayout', 'getLayoutNames', 'getOrCreateView', 'getViewHandle',
        'getViewInstances', 'getViewTypes', 'moveSplitter', 'removeLayout', 'resetLayouts', 'setLayout', 'switchLayout', 'undockView')},
    **{'ak.wwise.ui.' + name: 189 for name in ('model.createHandle', 'model.destroyHandle', 'model.getState',
        'model.registerWafm', 'model.setState', 'signal.emit', 'window.close', 'window.create', 'window.present')},
}
SOURCES = [GATEWAY, *[LIB + name + '.py' for name in ('authoring_layout', 'authoring_layout_business',
    'authoring_layout_handles', 'layout_blueprint', 'authoring_model_business', 'authoring_wafm',
    'authoring_resources', 'operation_registry', 'builders/schema')],
    'tests/support/ui_completion_mapping.py', 'tests/support/topic_completion_mapping.py', 'tests/maintenance/map_ui_completion.py',
    POLICY, BASE + 'source-roster.json']


def discover_ui(root):
    """Enumerate all ten source catalogs, keeping reference and recursive identities."""
    from wwise_waapi.native_catalog import load_native_catalog, NATIVE_HOSTS
    from wwise_waapi.schema_inventory import DefinitionGraph, resolve_schema_reference
    from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS
    root = Path(root)
    owners = json.loads((root / 'docs/branch-coverage-ownership.json').read_bytes())['routes']
    if {key.split('|', 1)[1]: row['owner_issue'] for key, row in owners.items()
            if row['owner_issue'] in (188, 189)} != OWNERS:
        raise ValueError('UI exact #188/#189 ownership roster changed')
    routes, rows, catalogs, locations = [], {}, {}, defaultdict(list)
    for version in SUPPORTED_WWISE_VERSION_KEYS:
        for host in NATIVE_HOSTS:
            catalog = load_native_catalog(version, host, root=root / 'skills/waapi-skill/resources/native-catalog')
            build = catalog['provenance']['build']
            catalogs[f'{version}|{host}|{build}'] = catalog['content_sha256']
            wanted = (set(OWNERS) - ({'ak.wwise.ui.layout.closeView', 'ak.wwise.ui.layout.resetLayouts'} if version == '2024.1' else set())
                if host == 'wwise-authoring' and version in ('2024.1', '2025.1') else set())
            if set(catalog['functions']) & set(OWNERS) != wanted:
                raise ValueError('UI native host/version roster changed')
            graph = DefinitionGraph(**{k: catalog['definitions'][k] for k in
                ('contract', 'version', 'wwise_build', 'source_file_names', 'documents', 'inventory_sha256')})
            for uri in sorted(wanted):
                native = f'{version}|{host}|{build}|function|{uri}'
                routes.append({'id': native, 'version': version, 'host': host, 'build': build, 'kind': 'function',
                    'uri': uri, 'native_schema_sha256': digest(catalog['schemas'][uri]), 'public_route': f'{version}|function|{uri}'})
                for section in ('argsSchema', 'optionsSchema', 'resultSchema'):
                    schema, visited = catalog['schemas'][uri][section], set()
                    def visit(value, pointer, context, document, active, location):
                        for item in schema_branches(value, pointer):
                            identity = native + '|' + item['pointer']
                            address = location + _path(item['pointer'][len(pointer):], schema=value,
                                schema_pointer=pointer, legacy_paths=frozenset())
                            if address not in locations[identity]: locations[identity].append(address)
                            row = {'id': identity, 'route': native, 'pointer': item['pointer'], 'kind': item['kind'],
                                'shape_sha256': digest(item['value']), 'owner_issue': OWNERS[uri],
                                'parent_issue': 174, 'blocks_issue': 195, 'state': 'unresolved'}
                            if item['kind'] != 'schema': row['value'] = item['value']
                            if item['kind'] == 'reference':
                                target = resolve_schema_reference(item['value'], root_schema=context, graph=graph)
                                doc = document if target.document_name == '<schema>' else target.document_name
                                key = (doc, target.pointer)
                                ptr = '/' + section + '/@definition/' + doc + target.pointer
                                row['reference'] = {'target': native + '|' + ptr, 'recursive': key in active,
                                    'document': doc, 'target_sha256': digest(target.target)}
                                if key not in visited:
                                    visited.add(key)
                                    visit(target.target, ptr, context if target.document_name == '<schema>' else graph.documents[doc],
                                        doc, active | {key}, address)
                            if identity in rows and rows[identity] != row: raise ValueError('UI native identity collision')
                            rows[identity] = row
                    visit(schema, '/' + section, schema, '<schema>', set(), [])
    return {'routes': routes, 'catalogs': catalogs, 'obligations': sorted(rows.values(), key=lambda r: r['id'])}, dict(locations)


def ui_component(root):
    from tests.maintenance.branch_audit_completion import candidate_identity
    from tests.maintenance.branch_audit_mapping import debug_control_component
    root = Path(root)
    native, locations = discover_ui(root)
    observed = {'catalogs': native['catalogs'], 'entries': {r['id']: {'kind': r['kind'], 'shape_sha256': r['shape_sha256']} for r in native['obligations']}}
    if json.loads((root / BASE / 'source-roster.json').read_bytes()) != observed:
        raise ValueError('UI native field/choice/version/definition differs from reviewed roster')
    wanted = {r['public_route'] for r in native['routes']}
    public = [deepcopy(r) for r in json.loads((root / 'docs/branch-coverage-inventory.json').read_bytes())['routes'] if r['id'] in wanted]
    if {r['id'] for r in public} != wanted: raise ValueError('UI current public route/version missing')
    sources = debug_control_component(root)['sources']
    sources.update({name: digest((root / name).read_text(encoding='utf-8')) for name in SOURCES})
    inventory = {'component': 'ui-195-r1', 'routes': public, 'sources': sources, 'native_locations': locations, 'native_coverage': native}
    native['candidate_sha256'] = candidate_identity(root, inventory, native['catalogs'], digest=digest)
    inventory['ui_roster_sha256'] = digest([(r['id'], r['shape_sha256']) for r in native['obligations']])
    inventory['ui_routes_sha256'] = digest(native['routes'])
    return inventory


LAYOUT_FIELDS = {
    'switchLayout': {'name': ['layout_handle']}, 'removeLayout': {'name': ['layout_handle']},
    'setLayout': {'name': ['new_layout_name'], 'layout': ['blueprint']},
    'getOrCreateView': {'name': ['view_type'], 'posX': ['initial_x'], 'posY': ['initial_y']},
    'closeView': {'viewID': ['view_handle']}, 'undockView': {'name': ['layout_handle'], 'viewID': ['view_handle'], 'posX': ['position_x'], 'posY': ['position_y']},
    'dockView': {'name': ['layout_handle'], 'viewID': ['view_handle'], 'targetID': ['target_element_handle'], 'side': ['dock_side']},
    'moveSplitter': {'id': ['splitter_handle'], 'delta': ['pixel_delta']},
    'resetLayouts': {'layouts': ['reset_scope', 'reset_layout_handles']},
}
MODEL_FIELDS = {
    'window.create': {'title': ['title'], 'size': ['width', 'height']},
    'window.present': {'windowID': ['window']}, 'window.close': {'windowID': ['window']},
    'model.createHandle': {'container': ['window'], 'template': ['template', 'template_key']},
    'model.destroyHandle': {'handleID': ['model']},
    'model.getState': {'handleID': ['model'], 'state': ['widgets']},
    'model.setState': {'handleID': ['model'], 'state': ['widgets']},
    'signal.emit': {'handleID': ['model'], 'widgetID': ['widget'], 'signal': ['signal']},
    'model.registerWafm': {'wafm': ['template_key', 'root_widget', 'widgets', 'layouts', 'templates',
        'registration_medium', 'registration_form', 'template_version', 'metadata']},
}


def _layout_blueprint_fields(row):
    from wwise_waapi.layout_blueprint import PLACEMENT_FIELDS, HISTORY_FIELDS
    pointer = row['pointer']
    definition = pointer.split('/definitions/')[-1].split('/')[0]
    properties = pointer.split('/properties/')
    field = properties[-1].split('/')[0] if len(properties) > 1 else None
    if definition == 'Splitter' or (definition == 'Element' and row.get('value') == '#/definitions/Splitter'):
        return [], 'accepted_unresolved_native_definition'
    if definition in {'Element', 'LayoutEntity'}:
        return ['blueprint.nodes', 'blueprint.root', 'blueprint.floating_windows'], 'closed_recursive_layout_graph'
    if definition == 'Layout':
        mapping = {'Name': ['blueprint.workspace_name'], 'StackPanel': ['blueprint.root'],
            'Undocked': ['blueprint.floating_windows'], **{native: ['blueprint.position_history.' + business] for business, native in HISTORY_FIELDS.items()}}
    elif definition in {'ViewHolder', 'ViewPosition'}:
        prefix = 'blueprint.floating_windows[].' if definition == 'ViewHolder' else 'blueprint.position_history.*[].'
        mapping = {native: [prefix + 'placement.' + business] for business, native in PLACEMENT_FIELDS.items()}
        mapping.update({'@type': [prefix + 'placement'], 'WindowPlacement_ShowCmd': [prefix + 'placement.state'],
            'StackPanel': [prefix + 'root'], 'Name': [prefix + 'view_name']})
    elif definition in {'EditorId', 'PreferredHeight', 'SideBar'}:
        prefix = 'blueprint.nodes[].' + {'EditorId': 'editor_priority[].', 'PreferredHeight': 'preferred_heights[].', 'SideBar': 'sidebar.'}[definition]
        mapping = {native: [prefix + public] for native, public in {'UniqueViewId': 'view_identifier', 'PluginId': 'plugin_identifier',
            'EffectIndex': 'effect_index', 'Height': 'height', 'Width': 'width', 'CollapseState': 'collapse_state', '@type': 'include_type'}.items()}
        if definition in {'PreferredHeight', 'SideBar'}: mapping['@type'] = [prefix.rstrip('.')]
    elif definition in {'EditorState', 'BottomEditorState', 'EditorPriority', 'PreferredHeights'}:
        return ['blueprint.nodes[].' + {'EditorState': 'editor_state', 'BottomEditorState': 'bottom_editor_state',
            'EditorPriority': 'editor_priority', 'PreferredHeights': 'preferred_heights'}[definition]], 'closed_layout_editor_state'
    elif definition in {'View', 'StackPanel', 'ObjectPanel', 'ObjectTabPanel'}:
        mapping = {native: ['blueprint.nodes[].' + public] for native, public in {'ID': 'key', '@type': 'kind',
            'Width': 'width', 'Height': 'height', 'Orientation': 'orientation', '@Children': 'children',
            'SelectionChannel': 'selection_channel', 'ViewData': 'data_entries', 'EditorState': 'editor_state',
            'BottomEditorState': 'bottom_editor_state', 'EditorPriority': 'editor_priority',
            'PreferredHeights': 'preferred_heights', 'SideBar': 'sidebar', 'Name': 'view_type' if definition == 'View' else 'label'}.items()}
    else:
        raise ValueError('UI unhandled layout definition: ' + definition)
    if field is not None and field not in mapping: raise ValueError('UI unhandled layout native field: ' + definition + '/' + field)
    return mapping.get(field, ['blueprint']), 'closed_layout_blueprint'


def _wafm_fields(row, contract):
    pointer = row['pointer']
    definition = pointer.split('/definitions/')[-1].split('/')[0]
    properties = pointer.split('/properties/')
    field = properties[1].split('/')[0] if len(properties) > 1 else None
    construction = contract['construction']
    if row['kind'] == 'enum_value' and field == 'Type' and row['value'] != 'Dialog':
        choice = row['value']
        if choice not in construction['widget_kinds'] and choice not in construction['layout']['kinds']:
            raise ValueError('UI native constructor has no closed public choice: ' + choice)
    if definition == 'wafm':
        return ['registration_form', 'registration_medium', 'templates', 'template_key'], 'owned_wafm_registration_forms'
    if definition == 'wafmDefinition':
        mapping = {'Version': 'template_version', 'Type': 'template_key', 'RootWidget': 'root_widget',
            'Widgets': 'widgets', 'Layouts': 'layouts', 'Settings': 'layouts', 'Metadata': 'metadata'}
        if field is not None and field not in mapping: raise ValueError('UI unhandled WAFM definition field: ' + str(field))
        return [mapping[field]] if field else ['template_key', 'root_widget', 'widgets', 'layouts'], 'closed_template_definition'
    if definition in {'layoutChild', 'positionsAttribute'}:
        return ['layouts[].children[].' + key for key in ('widget', 'layout', 'positions', 'anchors', 'section', 'width', 'minimum_size')], 'closed_recursive_layout_child'
    is_layout = definition.endswith('Definition') and definition != 'widgetDefinition'
    prefix = 'layouts[]' if is_layout else 'widgets[]'
    if is_layout and field == 'Children' and len(properties) > 2:
        field = properties[-1].split('/')[0]
        if field == 'Width': return [prefix + '.children[].width'], 'closed_wafm_layout_structure'
    child_fields = {'Children': prefix + '.children', 'Splitters': prefix + '.splitters',
        'Positions': prefix + '.children[].positions', 'AnchorSets': prefix + '.children[].anchors',
        'Section': prefix + '.children[].section', 'MinSize': prefix + '.children[].minimum_size'}
    if is_layout and field in child_fields: return [child_fields[field]], 'closed_wafm_layout_structure'
    if field == 'Type': return [prefix + '.kind'], 'closed_wafm_constructor_kind'
    if field == 'Name' or definition == 'widgetDefinition':
        return [prefix + '.key', 'layouts[].children[].widget'], 'owned_widget_or_layout_key'
    if definition in {'int32', 'uint32'}:
        return ['widgets[].attributes[].value', 'layouts[].attributes[].value', 'template_version'], 'typed_native_scalar'
    # Exact attribute name is the public assignment token. Its value uses the
    # closed typed value constructor, then the complete matching native schema.
    if field is not None:
        catalogs = [*construction['widget_kinds'].values(), *construction['layout']['kinds'].values()]
        if not any(field in entry['attributes'] for entry in catalogs):
            raise ValueError('UI native attribute has no closed public assignment: ' + str(field))
    return [prefix + '.attributes[].attribute', prefix + '.attributes[].value'], 'exact_attribute_typed_value'



def _public_nodes(schema, field):
    """Resolve one disclosed nested business field, including constructor unions."""
    def walk(node, tokens, seen):
        if not isinstance(node, dict): return []
        key = (id(node), tuple(tokens))
        if key in seen: return []
        seen = seen | {key}
        if '$ref' in node:
            target = schema
            for token in node['$ref'].removeprefix('#/').split('/'):
                target = target[token]
            return walk(target, tokens, seen)
        if not tokens: return [node]
        result = []
        for keyword in ('oneOf', 'anyOf', 'allOf'):
            for child in node.get(keyword, []): result.extend(walk(child, tokens, seen))
        token, *remaining = tokens
        array = token.endswith('[]')
        name = token.removesuffix('[]')
        children = list(node.get('properties', {}).values()) if name == '*' else [node.get('properties', {}).get(name)]
        for child in children:
            if array and isinstance(child, dict): child = child.get('items')
            result.extend(walk(child, remaining, seen))
        return result
    return walk(schema, field.split('.'), set())


def _correspondence(row, route, addresses, contract):
    uri, pointer = route['uri'], row['pointer']
    section, name = pointer.split('/')[1], uri.rsplit('.', 1)[1]
    fields, rule = [], 'closed_argument_envelope'
    if section == 'optionsSchema': rule = 'fixed_empty_options'
    elif section == 'resultSchema':
        rule = 'bounded_native_result_preserved'
    elif '.layout.' in uri:
        if name in LAYOUT_FIELDS:
            if '/@definition/waapi_ui_definitions.json/' in pointer:
                fields, rule = _layout_blueprint_fields(row)
            else:
                fields = sorted({field for address in addresses if address for field in LAYOUT_FIELDS[name].get(address[0], [])})
                rule = 'scoped_layout_plan'
        else:
            fields = sorted({{'name': 'layout_name', 'id': 'element_handle', 'viewID': 'view_handle'}[address[0]] for address in addresses if address and address[0] != '*'})
            rule = 'bounded_layout_read'
    else:
        if '/@definition/wafm_definitions.json/' in pointer or (name == 'registerWafm' and '/@definition/common_definitions.json/' in pointer):
            fields, rule = _wafm_fields(row, contract)
        else:
            key = uri.removeprefix('ak.wwise.ui.')
            fields = sorted({field for address in addresses if address for field in MODEL_FIELDS[key].get(address[0], [])})
            rule = 'owned_resource_plan'
            if key == 'window.create' and any(len(a) > 1 and a[0] == 'size' for a in addresses):
                fields = sorted({a[1] for a in addresses if len(a) > 1 and a[0] == 'size' and a[1] != '*'})
            if key in {'model.getState', 'model.setState'} and any(a and a[0] == 'state' for a in addresses):
                fields = ['widgets[].widget', 'widgets[].attributes']
                if key.endswith('setState'): fields += ['widgets[].attributes[].attribute', 'widgets[].attributes[].value']
    if section == 'argsSchema':
        declaration = contract.get('declaration', contract)
        if '.layout.' in uri and name in LAYOUT_FIELDS:
            exposed = set(declaration['public_fields'])
        elif '.layout.' in uri:
            exposed = {'layout_name', 'element_handle', 'view_handle'}
        else:
            exposed = set(declaration['schema']['properties'])
        if {field.split('.')[0].split('[')[0] for field in fields} - exposed:
            raise ValueError('UI mapped public field is not disclosed: ' + uri + ' ' + repr(fields))
        for field in fields:
            if field.startswith('blueprint.'):
                nodes = _public_nodes(contract['blueprint_schema'], field.removeprefix('blueprint.'))
            elif '.layout.' not in uri:
                nodes = _public_nodes(declaration['schema'], field)
            else:
                continue
            if not nodes: raise ValueError('UI nested public field is not disclosed: ' + field)
    correspondence = {'rule': rule, 'native_addresses': addresses, 'public_fields': fields,
        'public_contract_sha256': digest(contract), 'native_effect': 'not_claimed',
        'encoding': 'Gateway owns native IDs/envelopes; literal values, empty arrays, omission and ordered repeats preserved within disclosed resource bounds; no caller native payload',
        'accepted_boundary': '2024.1/2025.1 Authoring only; close/reset 2025.1 only; no additional native/Fresh/UI QA; source schema contradictions, preferred-height/sidebar/frontend limits retained',
        'verification': contract.get('verifier', contract.get('effect_verification', contract.get('result_scope')))}
    if row['kind'] == 'enum_value':
        value = row['value']
        correspondence.update(native_choice=value, public_choice={
            'Horizontal': 'horizontal', 'Vertical': 'vertical', 'Normal': 'normal', 'Maximized': 'maximized', 'Minimized': 'minimized',
            'StackPanel': 'stack', 'View': 'view', 'ObjectPanel': 'object_panel', 'ObjectTabPanel': 'object_tabs'}.get(value, value)
            if section == 'argsSchema' and uri.endswith('layout.setLayout') else value)
        if section == 'argsSchema' and uri.endswith('layout.setLayout') and '/definitions/SideBar/' in pointer:
            correspondence['public_choice'] = {'gateway_constant': 'SideBar', 'source_boundary': '2024 malformed scalar enum is retained; its character rows are not selectable choices'}
        if rule == 'accepted_unresolved_native_definition': correspondence['public_choice'] = {'accepted_boundary': 'contradictory_native_definition_no_constructor'}
    if 'reference' in row: correspondence['reference'] = row['reference']
    if name == 'registerWafm' and '/@definition/wafm_definitions.json/' in pointer:
        parts = pointer.split('/properties/')
        correspondence['native_attribute'] = parts[1].split('/')[0] if len(parts) > 1 else None
        correspondence['typed_value_encoding'] = 'text/integer/number/boolean/null/list/record constructors; nested attribute keys and enum values retained exactly; matching resolved schema validates each complete constructor'
    if section == 'resultSchema':
        correspondence['public_result'] = ('result and exact final agent_result, same native keys/values' if '.layout.' in uri and name not in LAYOUT_FIELDS else
            'agent_result.business_result.resource_handle from owned native identity; observable_effect_verified=false' if uri.endswith(('window.create', 'model.createHandle', 'model.registerWafm')) else
            'verification.readbacks[].result and canonical widget/attribute state, selected fields only' if uri.endswith('model.getState') else
            'transaction execution native result and separate verification outcome; acknowledgement is not observable effect')
        correspondence['result'] = 'Exact bounded native fields and absent/null distinctions retained; no window visibility/closure or signal-delivery proof; getState independently reads only selected widget attributes'
    if name == 'resetLayouts': correspondence['selection_forms'] = {'native_omission': 'omit layouts', 'empty_selection': [], 'selected_layouts': 'ordered names from handles, repeats retained; scope/effect not inferred'}
    return correspondence


def ui_bindings(root, inventory):
    from wwise_waapi.authoring_layout import LAYOUT_READS, layout_read_contract
    from wwise_waapi.authoring_layout_business import layout_business_contract_data
    from wwise_waapi.authoring_model_business import model_business_contract
    native = inventory['native_coverage']
    if (digest([(r['id'], r['shape_sha256']) for r in native['obligations']]) != inventory['ui_roster_sha256']
            or digest(native['routes']) != inventory['ui_routes_sha256']):
        raise ValueError('UI mapping native choice/host/version roster differs')
    public = {r['id']: r for r in inventory['routes']}
    if {r['public_route'] for r in native['routes']} != set(public): raise ValueError('UI mapping public route roster differs')
    routes = {r['id']: r for r in native['routes']}
    contracts = {r['public_route']: (layout_read_contract(r['version'], r['uri']) if r['uri'] in LAYOUT_READS.values()
        else layout_business_contract_data(r['uri'], r['version']) if '.layout.' in r['uri'] else model_business_contract(r['uri'], r['version'])) for r in routes.values()}
    for row in native['obligations']:
        if (row['kind'] == 'enum_value' and 'model.registerWafm' in row['id']
                and '/argsSchema/' in row['pointer'] and '/properties/Type/' in row['pointer'] and row['value'] != 'Dialog'):
            construction = contracts[routes[row['route']]['public_route']]['construction']
            schema = contracts[routes[row['route']]['public_route']]['declaration']['schema']
            disclosed = {choice for path in ('widgets[].kind', 'layouts[].kind') for node in _public_nodes(schema, path) for choice in node.get('enum', [])}
            if (row['value'] not in construction['widget_kinds'] and row['value'] not in construction['layout']['kinds']) or row['value'] not in disclosed:
                raise ValueError('UI native constructor has no closed public choice: ' + row['value'])
    bindings = {}
    for row in native['obligations']:
        route, pointer = routes[row['route']], row['pointer']
        uri, section = route['uri'], pointer.split('/')[1]
        read = uri in LAYOUT_READS.values()
        module = 'authoring_layout' if read else 'authoring_layout_business' if '.layout.' in uri else 'authoring_model_business'
        construct = 'layout_read_arguments' if read else 'materialize_layout_business_request' if '.layout.' in uri else 'materialize_model_business'
        argv = ['layout-read', next(k for k, v in LAYOUT_READS.items() if v == uri)] if read else ['draft-start', uri]
        bindings[row['id']] = {'branch_id': row['id'], 'native_shape_sha256': row['shape_sha256'],
            'public_route': route['public_route'], 'public_route_sha256': digest(public[route['public_route']]),
            'input': {'gateway_argv': argv, 'selector': pointer, 'correspondence': _correspondence(row, route, inventory['native_locations'][row['id']], contracts[route['public_route']])},
            'construction': {'source': LIB + module + '.py#' + construct, 'selector': pointer},
            'validation': {'source': (LIB + 'builders/schema.py#validate_semantic_result' if section == 'resultSchema' and not read else
                LIB + module + '.py#' + ('validate_layout_read_result' if read else 'validate_layout_call' if '.layout.' in uri else 'validate_model_call')), 'selector': pointer},
            'verifier': {'source': LIB + 'authoring_layout.py#validate_layout_read_result' if read else LIB + 'operation_registry.py#verify_prepared_operation', 'selector': pointer},
            'representative_mechanism': 'ui195-' + ('layout-read' if read else 'layout-plan' if '.layout.' in uri else 'model-resource') + '-v1', 'evidence': {}}
    return bindings


def export_mapping(root, destination, *, inventory=None, anchors=None):
    """One cohort, standard mapping attachments and ordinary requirements parts."""
    from tests.maintenance.branch_coverage_audit import write_requirements
    root, destination = Path(root).resolve(), Path(destination).resolve()
    inventory = ui_component(root) if inventory is None else inventory
    bindings = ui_bindings(root, inventory)
    destination.mkdir(parents=True, exist_ok=True)
    anchors = anchors or {}
    if set(anchors) - set(bindings): raise ValueError('UI selected anchor is outside exact family')
    for identity, anchor in anchors.items():
        if (set(anchor) != {'ordinary_test_run_attachment', 'relevant_sources', 'evidence'}
                or anchor['ordinary_test_run_attachment'] is not True or set(anchor['evidence']) != {'program'}):
            raise ValueError('UI anchor requires original ordinary program evidence')
        bindings[identity].update(deepcopy(anchor))
    rows = {r['id']: r for r in inventory['native_coverage']['obligations']}
    groups = defaultdict(dict)
    requirements = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {}, 'representative_mechanisms': {}}
    for identity, binding in bindings.items():
        mechanism = binding['representative_mechanism']
        groups[mechanism][identity] = binding
        requirements['branches'][identity] = {'native_shape_sha256': rows[identity]['shape_sha256'], 'categories': ['program'],
            'representative_mechanism': mechanism, 'reason': POLICY + ': accepted lightweight #188/#189 wrapper/code proof; no native effect inferred'}
    for mechanism, members in groups.items():
        selected = sorted(set(members) & set(anchors))
        if len(selected) > 1: raise ValueError('UI mechanism uses one selected ordinary anchor')
        requirements['representative_mechanisms'][mechanism] = {
            'contract': 'waapi-skill.representative-branch-mechanism/v1', 'scope_kind': 'product',
            'candidate_sha256': inventory['native_coverage']['candidate_sha256'],
            'reviewed_reason': 'Exact lightweight UI wrapper mapping with truthful schema/host/version/effect limits; aggregate CODE only',
            'sources': {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in SOURCES},
            'members': {identity: {'native_route': rows[identity]['route'], 'native_shape_sha256': rows[identity]['shape_sha256'],
                'mapping_sha256': digest({k: v for k, v in binding.items() if k != 'evidence'})} for identity, binding in members.items()},
            'selected_proofs': {'program': selected or [min(members)]}}
    def write(name, body):
        path = destination / name
        path.write_text(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n', encoding='utf-8')
        return {'artifact': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    entries, attachments = [], []
    for number, (mechanism, members) in enumerate(sorted(groups.items()), 1):
        for identity in sorted(set(members) & set(anchors)):
            original = deepcopy(members[identity])
            descriptor = write(f'selected-{number:02}.json', {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': {identity: original}})
            policy = write(f'selected-policy-{number:02}.json', {'contract': requirements['contract'], 'branches': {identity: requirements['branches'][identity]}})
            entries.append({'id': identity, 'bindings': descriptor, 'origin': {'bindings': descriptor, 'program': original['evidence']['program'],
                'requirements': policy, 'capture': write(f'selected-review-{number:02}.json', {'mechanism': mechanism, 'scope': 'actual ordinary aggregate proof; no native/per-node observations'})}})
        proposed = deepcopy(members)
        for binding in proposed.values(): binding['evidence'] = {}
        predecessors = {identity: {'binding_sha256': digest(binding), 'policy_sha256': digest(requirements['branches'][identity])}
            if identity in anchors else None for identity, binding in members.items()}
        attachments.append(write(f'mapping-{number:02}.json', {'contract': 'waapi-skill.branch-mapping-attachment/v1', 'scope_kind': 'product',
            'requirements_sha256': digest(requirements), 'mechanisms': [mechanism], 'bindings': proposed, 'predecessors': predecessors}))
    write_requirements(destination / 'requirements.json', requirements)
    write('evidence-index.json', {'contract': 'waapi-skill.branch-evidence-index/v1', 'base': '.', 'entries': entries, 'mapping_attachments': attachments})
    summary = {'component': inventory['component'], 'public_routes': len(inventory['routes']), 'native_routes': len(inventory['native_coverage']['routes']),
        'native_members': len(rows), 'catalogs': inventory['native_coverage']['catalogs'], 'candidate_sha256': inventory['native_coverage']['candidate_sha256'],
        'mechanisms': {k: len(v) for k, v in sorted(groups.items())}, 'mapping_is_not_execution_credit': True, 'native_effect_credit': False,
        'canonical_import_pending': True, 'requirements_parts': json.loads((destination / 'requirements.json').read_bytes()).get('parts', [])}
    write('summary.json', summary)
    return {'index_path': destination / 'evidence-index.json', 'requirements_path': destination / 'requirements.json', 'requirements': requirements, 'summary': summary}


SELECTED_TESTS = {
    'layout-read': [
        'tests/unit/test_authoring_layout_gateway.py::test_layout_discovery_schema_reaches_bounded_authoring_read',
        'tests/unit/test_authoring_layout_gateway.py::test_view_frontend_read_uses_live_scoped_identity_and_preserves_array_result',
        'tests/unit/test_authoring_layout_gateway.py::test_scoped_layout_read_rejects_stale_or_wrong_authority_before_target_dispatch'],
    'layout-plan': [
        'tests/unit/test_authoring_layout_blueprint_gateway.py::test_nested_blueprint_owns_stable_ids_and_verifies_declared_stack_and_view_state',
        'tests/unit/test_authoring_layout_mutation_gateway.py::test_reset_preserves_native_selection_forms_and_does_not_claim_default_effect',
        'tests/unit/test_authoring_layout_mutation_gateway.py::test_dock_view_binds_exact_target_side_and_verifies_independent_geometry[floating-left-2024.1]',
        'tests/unit/test_authoring_layout_splitter_gateway.py::test_splitter_owns_native_id_and_axis_and_verifies_exact_signed_delta[15-Horizontal-{44444444-4444-4444-4444-444444444444}-x-2025.1]'],
    'model-resource': [
        'tests/unit/test_authoring_model_gateway.py::test_owned_window_can_be_presented_then_closed_and_cannot_be_reused',
        'tests/unit/test_authoring_model_gateway.py::test_owned_model_state_roundtrip_uses_registered_widget_and_independent_readback',
        'tests/unit/test_authoring_model_gateway.py::test_owned_wafm_file_alternative_seals_and_dispatches_a_generated_data_file',
        'tests/unit/test_authoring_model_gateway.py::test_named_template_collection_is_owned_and_frontend_selects_one_exact_template'],
}
RUNTIME_SOURCES = {name for name in SOURCES if name.startswith('skills/waapi-skill/')}
RUNTIME_SOURCES.update({*(node.split('::')[0] for nodes in SELECTED_TESTS.values() for node in nodes),
    'tests/support/gateway_config.py', 'tests/unit/test_waapi_gateway.py', 'tests/unit/test_debug_read_gateway.py',
    *(LIB + name + '.py' for name in ('operation_drafts', 'operation_composer', 'transactions', 'transaction_runtime',
        'transaction_cleanup', 'business_adapters', 'business_declaration_state', 'business_declarations',
        'dispatcher', 'capabilities', 'execution_contracts', 'config', 'io_policy'))})


def program_anchors(root, inventory, destination, run):
    """Copy finalized ordinary aggregate CODE proof; never invent node outcomes."""
    import subprocess
    from tests.maintenance.branch_audit_completion import binding_semantics
    from tests.support.ordinary_test_run_evidence import RUNNER_SOURCES
    from tests.semantic.support.codex_archive_paths import archive_relative_from_absolute
    root, destination, run = Path(root).resolve(), Path(destination).resolve(), Path(run).resolve()
    plan = json.loads((run / 'run.plan.json').read_bytes())
    result = json.loads((run / 'run.result.json').read_bytes())
    summary = json.loads((run / 'run.summary.json').read_bytes())
    if (result.get('candidate_unchanged') is not True or result.get('exit_code') != 0
            or result.get('git_status') != '' or result.get('remaining_owned_processes') != []
            or summary.get('status') != 'PASS' or summary.get('source_unchanged') is not True
            or summary.get('skipped') != 0 or result.get('head_after') != plan.get('candidate')):
        raise ValueError('UI selected code anchor is missing or unfinalized')
    if not {node for nodes in SELECTED_TESTS.values() for node in nodes} <= set(plan['argv'][6:]):
        raise ValueError('UI code anchor omits a selected representative mechanism')
    originals = {}
    for name in RUNTIME_SOURCES | RUNNER_SOURCES:
        raw = subprocess.run(['git', 'show', plan['candidate'] + ':' + name], cwd=root,
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
        originals[name] = hashlib.sha256(raw).hexdigest()
        if name in RUNTIME_SOURCES and hashlib.sha256((root / name).read_bytes()).hexdigest() != originals[name]:
            raise ValueError('UI relevant selected source changed: ' + name)
    destination.mkdir(parents=True, exist_ok=True)
    files = {}
    for key, name in {'plan': 'run.plan.json', 'result': 'run.result.json', 'summary': 'run.summary.json',
            'log': 'run.log', 'exit': 'run.exit'}.items():
        raw = (run / name).read_bytes()
        target = destination / 'original' / name
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(raw)
        files[key] = {'artifact': archive_relative_from_absolute(target, destination).canonical,
            'sha256': hashlib.sha256(raw).hexdigest()}
    selected = {}
    for identity, binding in ui_bindings(root, inventory).items():
        selected.setdefault(binding['representative_mechanism'], (identity, binding))
    anchors = {}
    for number, (mechanism, (identity, binding)) in enumerate(sorted(selected.items()), 1):
        anchor = {'ordinary_test_run_attachment': True, 'relevant_sources': sorted(RUNTIME_SOURCES), 'evidence': {}}
        binding.update(anchor)
        group = mechanism.removeprefix('ui195-').removesuffix('-v1')
        proof = {'contract': 'waapi-skill.ordinary-test-run-attachment/v1', 'scope_kind': 'product',
            'candidate_sha256': inventory['native_coverage']['candidate_sha256'], 'original_candidate': plan['candidate'],
            'files': files, 'original_sources': originals, 'skip_lines': [],
            'review': {'reason': 'Byte-identical relevant sources in an actual focused aggregate CODE run; no native/per-node observation inferred',
                'selection_reason': 'Accepted #188/#189 representative closed construction and safety/weak-result controls; original native histories remain separate, not rerun per mapping leaf',
                'sources': {name: {'original_sha256': originals[name], 'current_sha256': originals[name],
                    'reviewed_reason': 'Byte-identical relevant source'} for name in sorted(RUNTIME_SOURCES)}, 'skip_attribution': {}},
            'mechanism': {'branch_id': identity, 'native_route': identity.rsplit('|', 1)[0],
                'native_shape_sha256': binding['native_shape_sha256'],
                'binding_semantics_sha256': digest(binding_semantics(binding)), 'selected_tests': SELECTED_TESTS[group]}}
        target = destination / f'program-anchor-{number:02}.json'
        target.write_text(json.dumps(proof, sort_keys=True, separators=(',', ':')) + '\n', encoding='utf-8')
        anchor['evidence']['program'] = {'artifact': archive_relative_from_absolute(target, destination).canonical,
            'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
        anchors[identity] = anchor
    return anchors

