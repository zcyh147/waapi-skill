"""Exact #180 object correspondence; mapping is separate from native effect proof."""
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
BASE = 'tests/fixtures/branch-evidence/product/object-195-r1/'
POLICY = 'docs/plans/full-waapi-coverage/SPEC.md'
OWNERS = {"ak.wwise.core." + name: 180 for name in (
    "object.copy", "object.create", "object.delete", "object.diff", "object.isLinked", "object.move",
    "object.set", "object.setLinked", "object.setName", "object.setNotes", "object.setProperty",
    "object.setReference", "workUnit.load", "workUnit.unload")}
VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
SOURCES = [GATEWAY, *[LIB + name + '.py' for name in (
    'object_graph_business', 'object_graph_business_contracts', 'object_lifecycle_business',
    'object_lifecycle_business_contracts', 'object_metadata_business', 'object_metadata_business_contracts',
    'core_business', 'core_business_contracts', 'operation_object', 'operation_plugin', 'object_capabilities',
    'documented_list_fields', 'planned_references', 'business_declarations', 'business_fields',
    'metadata_condition_contracts', 'action_construction', 'reference_kind_evidence', 'new_object_defaults', 'operation_registry', 'builders/schema')],
    'tests/support/object_completion_mapping.py', 'tests/support/topic_completion_mapping.py',
    'tests/maintenance/map_object_completion.py', POLICY, BASE + 'source-roster.json', BASE + 'business-source-roster.json',
    'skills/waapi-skill/resources/metadata/action-constructor-sources.json',
    'skills/waapi-skill/resources/metadata/reference-kind-sources.json',
    *['skills/waapi-skill/resources/metadata/' + version + '/' + name + '.json'
      for version in VERSIONS for name in ('object-types', 'documented-list-fields')]]


def discover_objects(root):
    """Enumerate all ten source catalogs, keeping reference and recursive identities."""
    from wwise_waapi.native_catalog import load_native_catalog, NATIVE_HOSTS
    from wwise_waapi.schema_inventory import DefinitionGraph, resolve_schema_reference
    from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS
    root = Path(root)
    owners = json.loads((root / 'docs/branch-coverage-ownership.json').read_bytes())['routes']
    if {key.split('|', 1)[1]: row['owner_issue'] for key, row in owners.items()
            if row['owner_issue'] in (180,)} != OWNERS:
        raise ValueError('Object exact #180 ownership roster changed')
    routes, rows, catalogs, locations = [], {}, {}, defaultdict(list)
    for version in SUPPORTED_WWISE_VERSION_KEYS:
        for host in NATIVE_HOSTS:
            catalog = load_native_catalog(version, host, root=root / 'skills/waapi-skill/resources/native-catalog')
            build = catalog['provenance']['build']
            catalogs[f'{version}|{host}|{build}'] = catalog['content_sha256']
            wanted = set(OWNERS)
            if version == '2021.1': wanted -= {'ak.wwise.core.' + n for n in ('object.diff', 'object.set', 'object.isLinked', 'object.setLinked', 'workUnit.load', 'workUnit.unload')}
            elif version == '2022.1': wanted -= {'ak.wwise.core.' + n for n in ('object.isLinked', 'object.setLinked', 'workUnit.load', 'workUnit.unload')}
            elif version in ('2023.1', '2024.1'): wanted -= {'ak.wwise.core.workUnit.load', 'ak.wwise.core.workUnit.unload'}
            if set(catalog['functions']) & set(OWNERS) != wanted:
                raise ValueError('Object native host/version roster changed')
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
                            if identity in rows and rows[identity] != row: raise ValueError('Object native identity collision')
                            rows[identity] = row
                    visit(schema, '/' + section, schema, '<schema>', set(), [])
    return {'routes': routes, 'catalogs': catalogs, 'obligations': sorted(rows.values(), key=lambda r: r['id'])}, dict(locations)


def object_component(root):
    from tests.maintenance.branch_audit_completion import candidate_identity
    from tests.maintenance.branch_audit_mapping import debug_control_component
    root = Path(root)
    native, locations = discover_objects(root)
    observed = {'catalogs': native['catalogs'], 'entries': {r['id']: {'kind': r['kind'], 'shape_sha256': r['shape_sha256']} for r in native['obligations']}}
    if json.loads((root / BASE / 'source-roster.json').read_bytes()) != observed:
        raise ValueError('Object native field/choice/version/definition differs from reviewed roster')
    wanted = {r['public_route'] for r in native['routes']}
    public = [deepcopy(r) for r in json.loads((root / 'docs/branch-coverage-inventory.json').read_bytes())['routes'] if r['id'] in wanted]
    if {r['id'] for r in public} != wanted: raise ValueError('Object current public route/version missing')
    sources = debug_control_component(root)['sources']
    sources.update({name: digest((root / name).read_text(encoding='utf-8')) for name in SOURCES})
    business = business_correspondence(root)
    if json.loads((root / BASE / 'business-source-roster.json').read_bytes()) != business_source_roster(business):
        raise ValueError('Object class/plugin/List source member roster differs from reviewed inputs')
    inventory = {'business_correspondence': business, 'component': 'object-195-r1', 'routes': public, 'sources': sources, 'native_locations': locations, 'native_coverage': native}
    native['candidate_sha256'] = candidate_identity(root, inventory, native['catalogs'], digest=digest)
    inventory['object_roster_sha256'] = digest([(r['id'], r['shape_sha256']) for r in native['obligations']])
    inventory['object_routes_sha256'] = digest(native['routes'])
    return inventory


def business_correspondence(root):
    """Join existing #178/#179 inputs without claiming the metadata denominator."""
    from wwise_waapi.documented_list_fields import load_catalog
    from wwise_waapi.object_graph_business_contracts import object_graph_business_contract_data
    from wwise_waapi.operation_plugin import PLUGIN_TYPE_CATEGORIES, PLUGIN_SHARESET_HIERARCHIES, SOURCE_TARGET_TYPES, EFFECT_TARGET_TYPES
    from wwise_waapi.object_capabilities import object_child_capability
    lanes = {}
    for version in VERSIONS:
        types = json.loads((Path(root) / 'skills/waapi-skill/resources/metadata' / version / 'object-types.json').read_bytes())
        lists = load_catalog(version)
        contracts = {op: object_graph_business_contract_data(op, version) for op in
            (('object.create',) if version == '2021.1' else ('object.create', 'object.set', 'object.createPlugin', 'object.setRTPC'))}
        lanes[version] = {'type_source': types['metadata'], 'class_inputs': types['types'],
            'class_admission': 'selected live Type Handle and matching class Field Handles; parent compatibility, constructor prerequisites, exact native class/condition checks and disclosed boundaries apply; discovery does not assert every class is constructible',
            'parent_choices': {row['name']: {'allowed_children': list(object_child_capability(version=version, parent_type=row['name'], child_types=()).allowed_child_types)}
                for row in types['types'] if object_child_capability(version=version, parent_type=row['name'], child_types=()).writable_parent},
            'owned_lists': {'catalog_sha256': lists['catalog_sha256'], 'source': lists['source'],
                'coverage': lists['coverage'], 'classes': lists['classes'],
                'input': 'draft-discover-fields --field-source documented-lists --list; selected List Field Handle; new root object_list or recursive object.set declaration and explicit append/replace-all/clear',
                'admission': 'exact version/class/source, allowed element class, owner/membership and constructor proof; missing source/unknown member class is unresolved, never native absence'},
            'business_contracts': {op: {'sha256': digest(contract), 'contract': contract} for op, contract in contracts.items()},
            'plugin_inputs': {'discovery_roles': PLUGIN_TYPE_CATEGORIES, 'independent_hierarchies': PLUGIN_SHARESET_HIERARCHIES,
                'source_owner_types': sorted(SOURCE_TARGET_TYPES), 'effect_owner_types': sorted(EFFECT_TARGET_TYPES),
                'routes': ['object.create', 'object.copy'] if version == '2021.1' else ['object.createPlugin', 'object.set'],
                '2021_selected_sink_metadata': 'accepted donor-free selected AudioDevice/Metadata creation boundary; no native absence or all-plugin exclusion',
                'native_class_id': 'Gateway derived from fresh selected Type Handle; live class Field Handles own properties/references'},
            'native_effect': 'not_claimed'}
    return {'related_owners': [178, 179], 'lanes': lanes, 'non_uri_metadata_inventory_join_pending': True,
        'metadata_completion_claimed': False,
        'scope': 'Exact existing graph/class/plugin/List input correspondence only; separate source-condition/field/placement business obligation identities and original native evidence remain final-join inputs',
        'remaining_runtime_work': {'owner': 180, 'parent': 174, 'blocks': 195,
            'Action': ['non-fail collision modes', 'multiple new unnamed Actions under one Event in one Preview', 'targetless constructors'],
            'Source': ['non-fail construction collision modes'], 'anonymous_lists': ['non-fail construction collision modes']}}


def business_source_roster(business):
    return {version: {key: digest(lane[key]) for key in ('class_inputs', 'parent_choices', 'owned_lists', 'plugin_inputs')}
        for version, lane in business['lanes'].items()}


LIFECYCLE = {'copy', 'delete', 'move', 'setName', 'setNotes'}
METADATA = {'setProperty', 'setReference', 'setLinked'}


def _contract(route):
    from wwise_waapi.object_graph_business_contracts import object_graph_business_contract_data
    from wwise_waapi.object_lifecycle_business_contracts import object_lifecycle_business_contract_data
    from wwise_waapi.object_metadata_business_contracts import object_metadata_business_contract_data
    from wwise_waapi.core_business_contracts import core_business_contract_data
    uri, version = route['uri'], route['version']
    name = uri.rsplit('.', 1)[1]
    if name in {'create', 'set'}: return object_graph_business_contract_data('object.' + name, version)
    if name in LIFECYCLE: return object_lifecycle_business_contract_data('object.' + name, version)
    if name in METADATA: return object_metadata_business_contract_data('object.' + name, version)
    return core_business_contract_data(uri, version)


def _mechanism(uri):
    name = uri.rsplit('.', 1)[1]
    return ('graph' if name in {'create', 'set'} else 'lifecycle' if name in LIFECYCLE else
        'metadata' if name in METADATA else 'core')


def _disclosed(contract):
    declaration = contract['declaration']
    fields = set()
    for key in ('required_fields', 'optional_fields', 'target_fields', 'existing_required_fields', 'new_required_fields'):
        fields.update(declaration.get(key, []))
    for key in ('field_types', 'stable_fields', 'field_value_types'):
        fields.update(declaration.get(key, {}))
    if declaration.get('bound_field_handle_container'): fields.add(declaration['bound_field_handle_container'])
    return fields


def _graph_fields(route, address, contract):
    """Resolve exact native locations through the existing graph declarations."""
    path = [token for token in address if token is not None]
    if not path: return [], 'closed_argument_envelope'
    if 'import' in path:
        tail = path[path.index('import') + 1:]
        mapping = {'audioFile': 'media_files[].media_file', 'audioFileBase64': 'media_files[].inline_wav',
            'language': 'media_files[].language', 'objectType': 'media_files[].kind',
            'originalsSubFolder': 'media_files[].originals_subfolder', 'autoAddToSourceControl': 'media_files[].add_to_source_control',
            'files': 'media_files', '*': 'media_files'}
        field = next((mapping[token] for token in reversed(tail) if token in mapping), 'media_files')
        return [field], 'owned_media_import'
    leaf = path[-1]
    if leaf == 'id' and not {'object', 'parent'} & set(path):
        return [], 'native_internal_id_prohibited'
    if '*' in path:
        # The native @ token is issued by exact metadata/List discovery. The
        # whole union (scalar/null/reference array/owned object/Curve) stays here.
        return ['field_values'], 'metadata_authorized_native_value_union'
    if route['uri'].endswith('.create'):
        mapping = {'parent': 'parent_handle', 'type': 'kind', 'name': 'name', 'notes': 'notes',
            'list': 'object_list', 'platform': 'platform', 'autoAddToSourceControl': 'add_to_source_control',
            'onNameConflict': 'name_conflict', 'children': 'parent_handle'}
    else:
        mapping = {'objects': 'object_handle', 'object': 'object_handle', 'type': 'kind', 'classId': 'kind',
            'name': 'name' if 'children' in path else 'new_name', 'notes': 'notes', 'platform': 'platform',
            'language': 'language', 'onNameConflict': 'name_conflict', 'listMode': 'list_behavior',
            'autoAddToSourceControl': 'add_to_source_control', 'children': 'parent_handle'}
    token = next((token for token in reversed(path) if token in mapping), None)
    if token is None: raise ValueError('Object native field has no reviewed graph mapping: ' + repr(address))
    return [mapping[token]], 'recursive_graph_declaration'


def _validate_fields(route, fields, contract):
    exposed = _disclosed(contract)
    if _mechanism(route['uri']) == 'graph':
        exposed.update(contract.get('settings', {}))
        # These are structural declaration inputs, distinct from field_values.
        for key in ('existing_required_fields', 'new_required_fields', 'target_fields'):
            exposed.update(contract['declaration'].get(key, []))
    for field in fields:
        if field.startswith('binding.') or field.startswith('field_discovery.'): continue
        if field.startswith('media_files'):
            if 'media_declaration' not in contract: raise ValueError('Object media field is not disclosed')
            if '.' in field and field.rsplit('.', 1)[1] not in {*contract['media_declaration']['optional_fields'], 'media_file', 'inline_wav'}:
                raise ValueError('Object media field is not disclosed: ' + field)
            continue
        if field not in exposed: raise ValueError('Object public field is not disclosed: ' + route['uri'] + ' ' + field)


def _correspondence(row, route, addresses, contract):
    uri, section = route['uri'], row['pointer'].split('/')[1]
    name = uri.rsplit('.', 1)[1]
    fields, rules = set(), set()
    if section == 'optionsSchema':
        rule = 'gateway_owned_verification_projection'
    elif section == 'resultSchema':
        rule = 'bounded_native_result_and_independent_verifier'
    elif row['pointer'].endswith('/additionalProperties'):
        rule = 'closed_native_envelope'
    elif _mechanism(uri) == 'graph':
        for address in addresses:
            mapped, found = _graph_fields(route, address, contract)
            fields.update(mapped)
            rules.add(found)
        rule = ('native_internal_id_prohibited' if 'native_internal_id_prohibited' in rules else
            'metadata_authorized_native_value_union' if 'metadata_authorized_native_value_union' in rules else
            'owned_media_import' if 'owned_media_import' in rules else 'recursive_graph_declaration')
    else:
        mapping = ({'object': 'binding.object', 'parent': 'binding.parent',
            'onNameConflict': 'name_conflict', 'autoAddToSourceControl': 'add_to_source_control',
            'autoCheckOutToSourceControl': 'check_out_from_source_control',
            'value': 'new_name' if name == 'setName' else 'notes'} if name in LIFECYCLE else
            {'object': 'object_handle', 'property': 'field_handle', 'reference': 'field_handle',
            'platform': 'field_discovery.platform', 'linked': 'link_state',
            'value': 'business_value' if name == 'setProperty' else 'reference_outcome'} if name in METADATA else
            {'source': 'source_id', 'target': 'target_id'} if name == 'diff' else
            {'object': 'object_id', 'property': 'field_meaning', 'platform': 'platform_name'} if name == 'isLinked' else
            {'object': 'work_unit_handle'})
        for address in addresses:
            if address:
                if address[0] not in mapping: raise ValueError('Object native field has no reviewed mapping: ' + uri + repr(address))
                fields.add(mapping[address[0]])
        rule = 'bound_lifecycle_declaration' if name in LIFECYCLE else 'metadata_authorized_field_change' if name in METADATA else 'closed_core_read_or_workunit_plan'
    if section == 'argsSchema': _validate_fields(route, fields, contract)
    correspondence = {'rule': rule, 'native_addresses': addresses, 'public_fields': sorted(fields),
        'public_contract_sha256': digest(contract), 'native_effect': 'not_claimed',
        'encoding': 'Gateway owns identity/type/class/field tokens, native envelopes, order and bounded projection; literal scalar types, omission, explicit Boolean, null and ordered repeats retained where the exact contract admits them',
        'limits': 'Configuration/policy/immutable Preview/execute-once and independent drift/value checks retained; no new native/Fresh or per-leaf execution credit',
        'verification': 'independent actual GUID/class/parent/owner, requested values and declared preservation, or the existing explicit weaker result boundary'}
    if row['kind'] == 'enum_value':
        value = row['value']
        choice = {'replaceAll': 'replace-all'}.get(value, value)
        correspondence.update(native_choice=value, public_choice=choice)
        if section == 'argsSchema' and any('onNameConflict' in a for a in addresses):
            choices = (contract.get('settings', {}).get('name_conflict') if _mechanism(uri) == 'graph'
                else ['fail', 'rename', 'replace'] if contract['declaration'].get('field_types', {}).get('name_conflict') == 'fail_or_rename_or_replace' else None)
            if not isinstance(choices, list) or choice not in choices: raise ValueError('Object public conflict choice missing: ' + str(choice))
        if section == 'argsSchema' and any('listMode' in a for a in addresses):
            if choice not in contract['settings']['list_behavior']: raise ValueError('Object public list choice missing: ' + str(choice))
        if section == 'argsSchema' and 'curveShape' in row['pointer']:
            if value not in contract['rtpc_declaration']['points']['point_shapes']: raise ValueError('Object public Curve choice missing: ' + str(value))
        if section == 'optionsSchema': correspondence['public_choice'] = {'gateway_owned_projection_token': value, 'additional_read': 'query-schema business projection or bounded advanced read'}
    if row['kind'] == 'boolean_value' and name == 'setLinked' and section == 'argsSchema' and any('linked' in a for a in addresses):
        correspondence['public_choice'] = 'linked' if row['value'] else 'unlinked'
    if 'reference' in row: correspondence['reference'] = row['reference']
    if rule == 'native_internal_id_prohibited': correspondence['boundary'] = 'Pinned description: For internal use only; model-assigned creation GUIDs never admitted'
    if section == 'optionsSchema': correspondence['projection'] = 'Mutation response projection is fixed by the Gateway verifier; additional information is a separate bounded query, never a caller native return grammar'
    if section == 'resultSchema': correspondence['result'] = 'Exact bounded execution result and final agent_result preserved; successful native acknowledgement does not certify identity, topology, field values, source-control effect, WorkUnit load state or lifecycle cleanup'
    return correspondence


def object_bindings(root, inventory):
    native = inventory['native_coverage']
    if (digest([(r['id'], r['shape_sha256']) for r in native['obligations']]) != inventory['object_roster_sha256']
            or digest(native['routes']) != inventory['object_routes_sha256']):
        raise ValueError('Object mapping native field/choice/host/version roster differs')
    public = {r['id']: r for r in inventory['routes']}
    if {r['public_route'] for r in native['routes']} != set(public): raise ValueError('Object mapping public route roster differs')
    routes = {r['id']: r for r in native['routes']}
    contracts = {r['public_route']: _contract(r) for r in native['routes']}
    bindings = {}
    for row in native['obligations']:
        route = routes[row['route']]
        uri, group = route['uri'], _mechanism(route['uri'])
        name = uri.removeprefix('ak.wwise.core.')
        module = {'graph': 'object_graph_business', 'lifecycle': 'object_lifecycle_business', 'metadata': 'object_metadata_business', 'core': 'core_business'}[group]
        construct = {'graph': 'materialize_object_graph_business_request', 'lifecycle': 'materialize_object_lifecycle_business_request',
            'metadata': 'materialize_object_metadata_business_request', 'core': 'materialize_core_business_request'}[group]
        contract = contracts[route['public_route']]
        argv = ['core-call', uri] if contract.get('execution_shape') == 'bounded_read' else ['draft-start', uri if group == 'core' else name]
        read = contract.get('execution_shape') == 'bounded_read'
        bindings[row['id']] = {'branch_id': row['id'], 'native_shape_sha256': row['shape_sha256'],
            'public_route': route['public_route'], 'public_route_sha256': digest(public[route['public_route']]),
            'input': {'gateway_argv': argv, 'selector': row['pointer'],
                'correspondence': _correspondence(row, route, inventory['native_locations'][row['id']], contract)},
            'construction': {'source': LIB + module + '.py#' + construct, 'selector': row['pointer']},
            'validation': {'source': (LIB + 'builders/schema.py#validate_semantic_result' if read else LIB + 'operation_registry.py#prepare_operation'), 'selector': row['pointer']},
            'verifier': {'source': (LIB + 'builders/schema.py#validate_semantic_result' if read else LIB + 'operation_registry.py#verify_prepared_operation'), 'selector': row['pointer']},
            'representative_mechanism': 'object195-' + group + '-v1', 'evidence': {}}
    return bindings


def export_mapping(root, destination, *, inventory=None, anchors=None):
    """One cohort, standard mapping attachments and ordinary requirements parts."""
    from tests.maintenance.branch_coverage_audit import write_requirements
    root, destination = Path(root).resolve(), Path(destination).resolve()
    inventory = object_component(root) if inventory is None else inventory
    bindings = object_bindings(root, inventory)
    destination.mkdir(parents=True, exist_ok=True)
    anchors = anchors or {}
    if set(anchors) - set(bindings): raise ValueError('Object selected anchor is outside exact family')
    for identity, anchor in anchors.items():
        if (set(anchor) != {'ordinary_test_run_attachment', 'relevant_sources', 'evidence'}
                or anchor['ordinary_test_run_attachment'] is not True or set(anchor['evidence']) != {'program'}):
            raise ValueError('Object anchor requires original ordinary program evidence')
        bindings[identity].update(deepcopy(anchor))
    rows = {r['id']: r for r in inventory['native_coverage']['obligations']}
    groups = defaultdict(dict)
    requirements = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {}, 'representative_mechanisms': {}}
    for identity, binding in bindings.items():
        mechanism = binding['representative_mechanism']
        groups[mechanism][identity] = binding
        requirements['branches'][identity] = {'native_shape_sha256': rows[identity]['shape_sha256'], 'categories': ['program'],
            'representative_mechanism': mechanism, 'reason': POLICY + ': accepted lightweight #180 wrapper/code proof; no native effect inferred'}
    for mechanism, members in groups.items():
        selected = sorted(set(members) & set(anchors))
        if len(selected) > 1: raise ValueError('Object mechanism uses one selected ordinary anchor')
        requirements['representative_mechanisms'][mechanism] = {
            'contract': 'waapi-skill.representative-branch-mechanism/v1', 'scope_kind': 'product',
            'candidate_sha256': inventory['native_coverage']['candidate_sha256'],
            'reviewed_reason': 'Exact lightweight Object wrapper mapping with truthful schema/host/version/effect limits; aggregate CODE only',
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
        'canonical_import_pending': True, 'non_uri_metadata_completion_claimed': False, 'requirements_parts': json.loads((destination / 'requirements.json').read_bytes()).get('parts', [])}
    summary['known_runtime_work'] = inventory['business_correspondence']['remaining_runtime_work']
    summary['business_correspondence'] = write('business-correspondence.json', inventory['business_correspondence'])
    write('summary.json', summary)
    return {'index_path': destination / 'evidence-index.json', 'requirements_path': destination / 'requirements.json', 'requirements': requirements, 'summary': summary}


SELECTED_TESTS = {
    'graph': [
        'tests/unit/test_action_creation_gateway.py::test_new_action_uses_discovered_fields_empty_name_and_exact_parent',
        'tests/unit/test_action_creation_gateway.py::test_action_native_acknowledgement_cannot_hide_wrong_effect_or_reused_guid',
        'tests/unit/test_object_graph_business_gateway.py::test_gateway_adds_subordinate_media_without_model_authored_json',
        'tests/unit/test_object_graph_owned_choices_gateway.py::test_reference_array_business_schema_matches_each_pinned_lane',
        'tests/unit/test_object_graph_owned_choices_gateway.py::test_create_reference_unions_use_class_field_evidence_and_exact_bound_targets',
        'tests/unit/test_object_graph_owned_choices_gateway.py::test_documented_metadata_list_handle_clears_through_one_verified_transaction',
        'tests/unit/test_plugin_kind_placements_gateway.py::test_independent_plugin_kind_uses_exact_live_class_and_hierarchy',
        'tests/unit/test_plugin_shareset_gateway.py::test_shareset_executes_once_and_verifies_its_own_identity'],
    'lifecycle': [
        'tests/unit/test_object_lifecycle_replace_gateway.py::test_replace_lifecycle_seals_exact_deleted_tree_and_verifies_source_distinction',
        'tests/unit/test_object_lifecycle_replace_gateway.py::test_replace_revalidates_complete_source_and_destination_before_dispatch'],
    'metadata': [
        'tests/unit/test_object_metadata_business_gateway.py::test_property_draft_discovers_opaque_field_and_materializes_business_value'],
    'core': [
        'tests/unit/test_core_business_gateway.py::test_core_call_resolves_two_exact_objects_and_dispatches_one_bounded_diff',
        'tests/unit/test_core_business_gateway.py::test_core_call_discovers_is_linked_field_from_business_meaning'],
}

RUNTIME_SOURCES = {name for name in SOURCES if name.startswith('skills/waapi-skill/')}
RUNTIME_SOURCES.update({*(node.split('::')[0] for nodes in SELECTED_TESTS.values() for node in nodes),
    'tests/unit/test_field_interface_closure_gateway.py', 'tests/unit/test_action_reference_kind_gateway.py',
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
        raise ValueError('Object selected code anchor is missing or unfinalized')
    if not {node for nodes in SELECTED_TESTS.values() for node in nodes} <= set(plan['argv'][6:]):
        raise ValueError('Object code anchor omits a selected representative mechanism')
    originals = {}
    for name in RUNTIME_SOURCES | RUNNER_SOURCES:
        raw = subprocess.run(['git', 'show', plan['candidate'] + ':' + name], cwd=root,
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
        originals[name] = hashlib.sha256(raw).hexdigest()
        if name in RUNTIME_SOURCES and hashlib.sha256((root / name).read_bytes()).hexdigest() != originals[name]:
            raise ValueError('Object relevant selected source changed: ' + name)
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
    for identity, binding in object_bindings(root, inventory).items():
        selected.setdefault(binding['representative_mechanism'], (identity, binding))
    anchors = {}
    for number, (mechanism, (identity, binding)) in enumerate(sorted(selected.items()), 1):
        anchor = {'ordinary_test_run_attachment': True, 'relevant_sources': sorted(RUNTIME_SOURCES), 'evidence': {}}
        binding.update(anchor)
        group = mechanism.removeprefix('object195-').removesuffix('-v1')
        proof = {'contract': 'waapi-skill.ordinary-test-run-attachment/v1', 'scope_kind': 'product',
            'candidate_sha256': inventory['native_coverage']['candidate_sha256'], 'original_candidate': plan['candidate'],
            'files': files, 'original_sources': originals, 'skip_lines': [],
            'review': {'reason': 'Byte-identical relevant sources in an actual focused aggregate CODE run; no native/per-node observation inferred',
                'selection_reason': 'Accepted #180 representative closed construction and safety/weak-result controls; original native histories remain separate, not rerun per mapping leaf',
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
