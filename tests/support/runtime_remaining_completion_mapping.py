"""Exact remaining #186 native/public correspondence; mappings are not runtime observations."""
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
BASE = 'tests/fixtures/branch-evidence/product/runtime-remaining-195-r1/'
POLICY = 'docs/plans/full-waapi-coverage/SPEC.md'
PROFILER = 'ak.wwise.core.profiler.'
TRANSPORT = 'ak.wwise.core.transport.'
URIS = frozenset({PROFILER + name for name in ('enableProfilerData', 'getCpuUsage', 'getCursorTime',
    'getMeters', 'getPerformanceMonitor', 'getStreamedMedia', 'moveCursor', 'registerMeter',
    'saveCapture', 'setCursorTime', 'startCapture', 'stopCapture', 'unregisterMeter')} |
    {TRANSPORT + name for name in ('create', 'destroy', 'executeAction', 'getList', 'getState', 'prepare', 'useOriginals')})
OWNERS = dict.fromkeys(URIS, 186)
HISTORY = ['tests/fixtures/' + name + '/support-review.json' for name in (
    'runtime-capture-controls', 'runtime-cursor', 'runtime-transport', 'runtime-owned-controls',
    'runtime-extra-reads', 'runtime-meter')]
IMPORTED = [BASE + name + '/import-review.json' for name in ('retained-transport-r133', 'retained-meter-r137')]
SOURCES = [GATEWAY, *[LIB + name + '.py' for name in ('runtime_inspection_business',
    'runtime_inspection_business_contracts', 'runtime_transport_handles', 'profiler_meter_objects',
    'profiler_capture_artifact', 'operation_registry', 'builders/schema', 'typed_requests',
    'object_query_outputs')], 'tests/support/runtime_remaining_completion_mapping.py',
    'tests/support/topic_completion_mapping.py', 'tests/maintenance/map_runtime_remaining_completion.py',
    'tests/support/runtime_remaining_evidence.py', 'tests/semantic/support/codex_archive_paths.py',
    'tests/fixtures/runtime/runtime-remaining-policy-r127.json',
    POLICY, BASE + 'source-roster.json', BASE + 'accepted-history.json', BASE + 'selected-proof-plan.json', *HISTORY, *IMPORTED]


def discover_runtime(root):
    """Enumerate all ten source catalogs, keeping reference and recursive identities."""
    from wwise_waapi.native_catalog import load_native_catalog, NATIVE_HOSTS
    from wwise_waapi.schema_inventory import DefinitionGraph, resolve_schema_reference
    from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS
    root = Path(root).resolve()
    owners = json.loads((root / 'docs/branch-coverage-ownership.json').read_bytes())['routes']
    if any(owners.get('function|' + uri, {}).get('owner_issue') != 186 for uri in URIS):
        raise ValueError('Runtime exact remaining #186 ownership roster changed')
    routes, rows, catalogs, locations = [], {}, {}, defaultdict(list)
    for version in SUPPORTED_WWISE_VERSION_KEYS:
        for host in NATIVE_HOSTS:
            catalog = load_native_catalog(version, host, root=root / 'skills/waapi-skill/resources/native-catalog')
            build = catalog['provenance']['build']
            catalogs[f'{version}|{host}|{build}'] = catalog['content_sha256']
            wanted = set(URIS) & set(catalog['functions'])
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
                                if key not in active:
                                    visited.add(key)
                                    visit(target.target, ptr, context if target.document_name == '<schema>' else graph.documents[doc],
                                        doc, active | {key}, address)
                            if identity in rows and rows[identity] != row: raise ValueError('Runtime native identity collision')
                            rows[identity] = row
                    visit(schema, '/' + section, schema, '<schema>', set(), [])
    return {'routes': routes, 'catalogs': catalogs, 'obligations': sorted(rows.values(), key=lambda r: r['id'])}, dict(locations)


def _native_route_rows(native):
    routes = {}
    for row in native['routes']:
        identity = '|'.join(row[key] for key in ('version', 'host', 'build', 'kind', 'uri'))
        if row['id'] != identity or row['uri'] not in URIS or identity in routes:
            raise ValueError('Runtime unexpected native route identity')
        routes[identity] = row
    return routes


def _retained_profile_route(routes, source, identity, profile):
    result_profiles = {'tests/fixtures/runtime-extra-reads/support-review.json',
        'tests/fixtures/runtime-meter/support-review.json'}
    if source not in HISTORY:
        raise ValueError('Runtime unexpected retained profile identity source')
    # Three older providers key profiles by the complete native route and
    # have no separate route member. Other providers disclose it explicitly.
    route = profile.get('route')
    if route is None and identity in routes:
        route = routes[identity]['id']
    expected = route + '|/resultSchema' if source in result_profiles and isinstance(route, str) else route
    if route not in routes or identity != expected:
        raise ValueError('Runtime unexpected retained profile identity: ' + str(identity))
    if any(key in profile and profile[key] != routes[route][key] for key in ('version', 'host', 'build')):
        raise ValueError('Runtime retained profile identity context differs')
    return route


def retained_profile_mappings(native, source, document):
    """Join each source's exact profile protocol, never split a schema pointer."""
    routes = _native_route_rows(native)
    result = {}
    for identity, profile in document['profiles'].items():
        route = _retained_profile_route(routes, source, identity, profile)
        result[identity] = {'route': route, 'profile_sha256': digest(profile)}
    return result


def build_retained_history(root, native):
    """Preserve reviewed archive seals and retain original IDs beside route joins."""
    root = Path(root)
    history = json.loads((root / BASE / 'accepted-history.json').read_bytes())
    if set(history['sources']) != set(HISTORY):
        raise ValueError('Runtime retained history source roster changed')
    for source, record in history['sources'].items():
        raw = (root / source).read_bytes()
        if hashlib.sha256(raw).hexdigest() != record['sha256']:
            raise ValueError('Runtime retained history source seal changed')
        mappings = retained_profile_mappings(native, source, json.loads(raw))
        record['native_routes'] = sorted({item['route'] for item in mappings.values()})
        record['original_profile_ids'] = sorted(mappings)
        record['profile_mappings'] = mappings
    return history


def selected_proof_plan(native, history):
    routes = _native_route_rows(native)
    members = defaultdict(list)
    for member in native['obligations']:
        route = member['route']
        if route not in routes or member['id'] != route + '|' + member['pointer']:
            raise ValueError('Runtime unexpected native member identity')
        members[route].append(member)
    profiles = defaultdict(list)
    if set(history['sources']) != set(HISTORY):
        raise ValueError('Runtime unexpected retained profile identity source roster')
    for source, record in history['sources'].items():
        if set(record['original_profile_ids']) != set(record['profile_mappings']):
            raise ValueError('Runtime retained profile identity roster differs')
        for identity, profile in record['profile_mappings'].items():
            route = _retained_profile_route(routes, source, identity, profile)
            profiles[route].append({'source': source, 'id': identity,
                'profile_sha256': profile['profile_sha256']})
    rows = {}
    for uri in sorted(URIS):
        selected = sorted(row['id'] for row in routes.values() if row['uri'] == uri)
        name = uri.rsplit('.', 1)[1]
        group = ('zero' if uri in ZERO else 'transport' if uri.startswith(TRANSPORT) else
            'meter' if name == 'getMeters' else 'fixed-read' if name in {
                'getCpuUsage', 'getCursorTime', 'getPerformanceMonitor', 'getStreamedMedia'} else 'control')
        rows[uri] = {'source_members': sum(len(members[route]) for route in selected),
            'native_routes': selected, 'retained_native_profiles': [route for route in selected if profiles[route]],
            'retained_profile_identities': [profile for route in selected for profile in profiles[route]],
            'routes_without_profile': [route for route in selected if not profiles[route]],
            'code_mechanism': group, 'new_native_receipts_required': 'not_inferred_from_route_count',
            'actual_product_gap': ('getMeters omitted exact declared return spellings and namespaced source outputs; now reuses existing closed projection'
                if name == 'getMeters' else 'none_demonstrated'),
            'current_native_effect_admission': 'not_claimed; Main must join unchanged observations with exact selected host/effect risk and source equivalence'}
    return {'contract': 'waapi-skill.runtime-remaining-selected-proof-plan/v1',
        'legacy_gate': 'same-route native resultSchema root for every branch; 144 roots, preserved unchanged in exported requirements',
        'reconciliation_proposal': 'Review exact source-backed native facts per meaningful effect/host mechanism; admit CODE siblings through existing representative layer; do not infer current native PASS or new host facts. Missing native source slots remain observation limits unless actual host/effect risk requires a selected witness.',
        'canonical_index_remaining_bindings': 0, 'retained_native_profiles': sum(len(items) for items in profiles.values()), 'rows': rows}


def refresh_selected_proof_plan(root):
    """Refresh only the finite history/plan accounting, retaining native artifacts."""
    root = Path(root)
    native, _ = discover_runtime(root)
    history = build_retained_history(root, native)
    plan = selected_proof_plan(native, history)
    for name, document in [('accepted-history.json', history), ('selected-proof-plan.json', plan)]:
        (root / BASE / name).write_text(json.dumps(document, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    return plan


def runtime_component(root):
    from tests.maintenance.branch_audit_completion import candidate_identity
    from tests.maintenance.branch_audit_mapping import debug_control_component
    root = Path(root).resolve()
    history = json.loads((root / BASE / 'accepted-history.json').read_bytes())
    if set(history['sources']) != set(HISTORY):
        raise ValueError('Runtime retained native history roster changed')
    for name, record in history['sources'].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('Runtime retained native review changed: ' + name)
        for archive, descriptor in record['archives'].items():
            from tests.semantic.support.codex_archive_paths import archive_relative_from_absolute
            path = root / archive
            if archive_relative_from_absolute(path, root).canonical != archive or not path.is_file():
                raise ValueError('Runtime original archive identity changed')
            if path.stat().st_size != descriptor['bytes']:
                raise ValueError('Runtime original archive size changed')
    native, locations = discover_runtime(root)
    observed = {'catalogs': native['catalogs'], 'entries': {r['id']: {'kind': r['kind'], 'shape_sha256': r['shape_sha256']} for r in native['obligations']}}
    if json.loads((root / BASE / 'source-roster.json').read_bytes()) != observed:
        raise ValueError('Runtime native field/choice/version/definition differs from reviewed roster')
    wanted = {r['public_route'] for r in native['routes']}
    public = [deepcopy(r) for r in json.loads((root / 'docs/branch-coverage-inventory.json').read_bytes())['routes'] if r['id'] in wanted]
    if {r['id'] for r in public} != wanted: raise ValueError('Runtime current public route/version missing')
    for route in public:
        version, _, uri = route['id'].split('|')
        route['public_contracts'] = [digest(public_contract(uri, version))]
    sources = debug_control_component(root)['sources']
    sources.update({name: digest((root / name).read_text(encoding='utf-8')) for name in SOURCES})
    inventory = {'component': 'runtime-remaining-195-r1', 'routes': public, 'sources': sources, 'native_locations': locations, 'native_coverage': native}
    native['candidate_sha256'] = candidate_identity(root, inventory, native['catalogs'], digest=digest)
    inventory['runtime_roster_sha256'] = digest([(r['id'], r['shape_sha256']) for r in native['obligations']])
    inventory['runtime_routes_sha256'] = digest(native['routes'])
    return inventory



FIELDS = {
    'enableProfilerData': {'dataTypes': ['capture_data_changes']},
    'getCpuUsage': {'time': ['profiler_position']}, 'getPerformanceMonitor': {'time': ['profiler_position']},
    'getStreamedMedia': {'time': ['profiler_position']}, 'getMeters': {'time': ['profiler_position']},
    'getCursorTime': {'cursor': ['profiler_cursor']}, 'moveCursor': {'position': ['cursor_move']},
    'setCursorTime': {'time': ['cursor_target_ms']},
    'registerMeter': {'object': ['meter_object_handle']}, 'unregisterMeter': {'object': ['meter_object_handle']},
    'saveCapture': {'file': ['capture_output_directory', 'capture_name']},
    'startCapture': {}, 'stopCapture': {}, 'getList': {},
    'create': {'object': ['target_handle'], 'gameObject': ['game_object_id']},
    'prepare': {'object': ['target_handle']}, 'destroy': {'transport': ['transport_handle']},
    'getState': {'transport': ['transport_handle']},
    'executeAction': {'action': ['audition_action'], 'transport': ['transport_scope', 'transport_handle']},
    'useOriginals': {'enable': ['audition_media']},
}
ZERO = frozenset({PROFILER + 'startCapture', PROFILER + 'stopCapture', TRANSPORT + 'getList'})


def public_contract(uri, version):
    from wwise_waapi.runtime_inspection_business_contracts import runtime_inspection_business_contract_data
    from wwise_waapi.typed_requests import request_contract
    return request_contract(version, uri).as_gateway_payload() if uri in ZERO else runtime_inspection_business_contract_data(uri, version)


def _correspondence(row, route, addresses, contract):
    from wwise_waapi import runtime_inspection_business as business
    from wwise_waapi import runtime_inspection_business_contracts as contracts
    from wwise_waapi.profiler_meter_objects import meter_named_outputs
    uri, version, pointer = route['uri'], route['version'], row['pointer']
    section, name = pointer.split('/')[1], uri.rsplit('.', 1)[1]
    declaration = contract.get('declaration', {})
    fields, choices, rule = [], [], 'fixed_empty_envelope'
    if section == 'argsSchema':
        fields = sorted({field for address in addresses if address for field in FIELDS[name].get(address[0], [])})
        if any(address and address[0] != '*' and address[0] not in FIELDS[name] for address in addresses):
            raise ValueError('Runtime unhandled native argument: ' + uri + ' ' + repr(addresses))
        if set(fields) - set(declaration.get('required_fields', []) + declaration.get('optional_fields', [])):
            raise ValueError('Runtime mapped public field is not disclosed: ' + repr(fields))
        rule = 'closed_runtime_declaration' if fields else 'fixed_zero_input'
        if name == 'enableProfilerData':
            rule = 'ordered_capture_directives_and_documented_true_normalization'
            if row['kind'] == 'enum_value':
                choices = [choice for choice in contracts.PROFILER_CAPTURE_DATA_CHOICES[version]
                    if business._capture_data_native(version, choice) == row['value']]
                if not choices: raise ValueError('Runtime native capture choice is not disclosed: ' + repr(row['value']))
        elif name == 'executeAction' and row['kind'] == 'enum_value':
            choices = [choice for choice, native in contracts.AUDITION_ACTION_MEANINGS.items() if native == row['value']]
            if not choices: raise ValueError('Runtime native action choice is not disclosed')
        elif name == 'moveCursor' and row['kind'] == 'enum_value':
            choices = [choice for choice, native in contracts.PROFILER_CURSOR_MOVE_MEANINGS.items() if native == row['value']]
            if not choices: raise ValueError('Runtime native cursor move choice is not disclosed')
        elif row['kind'] == 'enum_value' and row['value'] in ('capture', 'user'):
            choices = [choice for choice, native in contracts.PROFILER_CURSOR_MEANINGS.items() if native == row['value']]
            if not choices: raise ValueError('Runtime native cursor choice is not disclosed')
    elif section == 'optionsSchema' and name == 'getMeters':
        top = {address[0] for address in addresses if address and address[0] != '*'}
        if top - {'return', 'platform', 'language'}: raise ValueError('Runtime unhandled meter option')
        fields = sorted({field for item in top for field in {
            'return': ['meter_object_outputs', 'meter_object_fields', 'meter_object_override_source_values',
                'meter_object_local_references', 'meter_object_related_outputs', 'meter_object_related_fields',
                'meter_object_related_override_source_values', 'meter_object_related_local_references', 'meter_object_empty_selection'],
            'platform': ['meter_platform'], 'language': ['meter_language']}[item]})
        if set(fields) - set(declaration['optional_fields']): raise ValueError('Runtime meter field is not disclosed')
        rule = 'metadata_compiled_meter_accessor' if '/returnExpression/items/anyOf/1' in pointer else 'closed_meter_object_projection'
        if row['kind'] == 'enum_value' and '/returnExpression/items/anyOf/0' in pointer:
            native = row['value']
            choices = ['automatic_identity'] if native in {'id', 'name', 'type', 'path'} else [
                choice for choice, (accessor, _) in meter_named_outputs(version).items() if accessor == native]
            if not choices: raise ValueError('Runtime meter return choice has no public correspondence: ' + str(native))
    elif section == 'resultSchema':
        rule = 'whole_bounded_native_result_and_separate_verification'
    result = {'rule': rule, 'native_addresses': addresses, 'public_fields': fields,
        'public_choices': choices, 'public_contract_sha256': digest(contract), 'native_effect': 'not_claimed',
        'native_language_equivalence': 'not_claimed',
        'presence': 'Required fields remain required; explicit false/zero/empty arrays and ordered repeated rows retained. Optional transport gameObject and all-active transport are omitted when selected. Meter omitted return/platform/language retain native defaults; empty return remains distinct.',
        'resource_lifetime': 'Only Gateway-issued live transport handles; context/source/row revalidation, execute once, no retry; stop/destroy or paired unregister cleanup; unavailable or ambiguous outcomes retain their separate state.',
        'verification': 'Native result schema is distinct from business state; cursor returns/readback, owned transport list/state, and bounded capture artifact checks retain their exact scope. Capture enable/start/stop, prepare, media mode and meter registration ACKs do not prove hidden settings, audible output, native capture validity or restoration.',
        'accepted_boundary': '2023.1 useOriginals optional native enable still requires explicit originals/converted under accepted policy; host/SDK/Debug observation limits remain; missing prereqs and preserved FAIL/BLOCKED roots are not passes.'}
    if section == 'argsSchema':
        disclosed = declaration.get('value_choices', {})
        choice_field = {'enableProfilerData': 'capture_data_changes.data_set', 'executeAction': 'audition_action',
            'moveCursor': 'cursor_move', 'getCursorTime': 'profiler_cursor'}.get(name)
        if choices and choice_field and not set(choices) <= set(disclosed.get(choice_field, [])):
            raise ValueError('Runtime mapped public choice is not disclosed: ' + repr(choices))
        encodings = {
            'dataTypes': 'ordered [business data-set, enable|disable] rows -> dataType version token and explicit boolean; explicit empty input -> []; no deduplication',
            'time': ('signed integer milliseconds exactly, including negative values without assigning sentinel meaning' if name == 'setCursorTime' else
                'capture-latest -> capture; user-cursor -> user; 1..1024 ASCII decimal digits -> nonnegative integer milliseconds; live named cursor frozen before read'),
            'cursor': 'capture-latest -> capture; user-cursor -> user',
            'position': 'first-frame -> first; last-frame -> last; next-frame -> next; previous-frame -> previous',
            'object': 'exact bound role identity -> canonical GUID; permitted native GUID/name/path alternatives normalize through the Gateway object binding and exact live revalidation',
            'gameObject': 'optional unsigned 64-bit game_object_id -> gameObject; explicit 0 retained; absent field omitted without inventing a default',
            'transport': 'one-transport -> live uint32 from context-bound Gateway handle; all-active action scope -> native transport omitted; numeric IDs never accepted as caller authority',
            'action': 'play -> play; stop -> stop; pause -> pause; toggle-play-stop -> playStop; play-directly -> playDirectly',
            'enable': 'originals -> true; converted -> false; explicit choice retained for 2023.1 optional native enable; no omitted-native default asserted',
            'file': 'authorized exact host directory + host-valid capture_name -> .prof destination; immutable path/artifact ownership checks',
        }
        result['value_mapping'] = {field: encodings[field] for field in sorted({a[0] for a in addresses if a and a[0] != '*'})}
    if row['kind'] in {'presence', 'default', 'enum_value', 'union', 'required'}:
        result['native_branch_value'] = row.get('value')
    if section == 'resultSchema':
        result['result_addresses'] = addresses
        result['result_delivery'] = 'Exact native result retained in execution evidence or bounded read pages; public normalized output and verification outcome remain separate; no direct per-member execution inferred.'
    if row['kind'] == 'enum_value': result['native_choice'] = row['value']
    if 'reference' in row: result['reference'] = row['reference']
    if name == 'enableProfilerData' and '/enable' in pointer:
        result['normalized_equivalent'] = {'native_absent': 'documented default true', 'public': '--capture-data <data-set> enable',
            'native_wire_omission_observed': False, 'source': 'exact pinned dataTypes.items.properties.enable description in all five lanes'}
    if name == 'useOriginals':
        result['media_choice'] = {'originals': True, 'converted': False, '2023.1_omission': 'accepted_explicit_choice_boundary_no_default_claim'}
    if name == 'getMeters':
        result['projection'] = 'Native meter roots at one frozen time; identity plus selected named/metadata fields; absent unavailable, explicit null retained. Related helpers retain provenance and never claim native expression equivalence.'
    return result


def runtime_bindings(root, inventory):
    native = inventory['native_coverage']
    if (digest([(r['id'], r['shape_sha256']) for r in native['obligations']]) != inventory['runtime_roster_sha256']
            or digest(native['routes']) != inventory['runtime_routes_sha256']):
        raise ValueError('Runtime mapping native choice/host/version roster differs')
    public = {r['id']: r for r in inventory['routes']}
    routes = {r['id']: r for r in native['routes']}
    contracts = {r['public_route']: public_contract(r['uri'], r['version']) for r in routes.values()}
    bindings = {}
    for row in native['obligations']:
        route, pointer = routes[row['route']], row['pointer']
        uri, name = route['uri'], route['uri'].rsplit('.', 1)[1]
        section = pointer.split('/')[1]
        group = ('zero' if uri in ZERO else 'transport' if uri.startswith(TRANSPORT) else 'meter' if name == 'getMeters'
            else 'fixed-read' if name in {'getCpuUsage', 'getCursorTime', 'getPerformanceMonitor', 'getStreamedMedia'} else 'control')
        construction = (GATEWAY + '#preflight_typed_zero_input' if uri in ZERO else
            LIB + 'profiler_meter_objects.py#compile_meter_object_options' if name == 'getMeters' and section == 'optionsSchema' else
            LIB + 'runtime_inspection_business.py#materialize_runtime_inspection_business_request' if group in {'meter', 'fixed-read'} or name == 'getState' else
            LIB + 'runtime_inspection_business.py#materialize_runtime_control_business_request')
        argv = ['core-call', uri] if group in {'meter', 'fixed-read'} or name == 'getState' else ['request-schema', uri] if uri in ZERO else ['draft-start', uri]
        bindings[row['id']] = {'branch_id': row['id'], 'native_shape_sha256': row['shape_sha256'],
            'public_route': route['public_route'], 'public_route_sha256': digest(public[route['public_route']]),
            'input': {'gateway_argv': argv, 'selector': pointer,
                'correspondence': _correspondence(row, route, inventory['native_locations'][row['id']], contracts[route['public_route']])},
            'construction': {'source': construction, 'selector': pointer},
            'validation': {'source': LIB + 'builders/schema.py#' + ('validate_resolved_semantic_result' if section == 'resultSchema' else 'validate_semantic_payload'), 'selector': pointer},
            'verifier': {'source': LIB + 'runtime_inspection_business.py#normalize_runtime_inspection_result' if group in {'meter', 'fixed-read'} or name == 'getState' else LIB + 'operation_registry.py#verify_prepared_operation', 'selector': pointer},
            'representative_mechanism': 'runtime195-remaining-' + group + ('-native-root' if pointer == '/resultSchema' else '') + '-v1', 'evidence': {}}
    return bindings


SELECTED_TESTS = {
    'zero': ['tests/unit/test_typed_request_gateway.py::test_zero_input_mutation_cannot_bypass_preview_before_connection'],
    'control': ['tests/unit/test_runtime_business_gateway.py::test_profiler_capture_data_rows_execute_once_without_claiming_settings[enable-disable-2025.1]',
        'tests/unit/test_runtime_business_gateway.py::test_profiler_cursor_setter_verifies_returned_snapped_time_through_public_transaction'],
    'transport': ['tests/unit/test_runtime_business_gateway.py::test_transport_create_matching_association_publishes_usable_zero_id_handle[native-default-2025.1]',
        'tests/unit/test_runtime_business_gateway.py::test_transport_state_read_maps_gateway_handle_without_exposing_native_id'],
    'fixed-read': ['tests/unit/test_runtime_business_gateway.py::test_profiler_cursor_read_maps_business_cursor_and_projects_milliseconds',
        'tests/unit/test_runtime_result_reference_gateway.py::test_performance_counter_validates_local_result_references'],
    'meter': ['tests/unit/test_profiler_meter_objects_gateway.py::test_declared_meter_return_spellings_keep_exact_selection_and_unattributed_values[2025.1]',
        'tests/unit/test_profiler_meter_objects_gateway.py::test_meter_namespaced_source_outputs_reuse_known_business_fields[2024.1]'],
}

def export_mapping(root, destination, *, inventory=None, anchors=None):
    """One cohort, standard mapping attachments and ordinary requirements parts."""
    from tests.maintenance.branch_coverage_audit import write_requirements
    from tests.support import runtime_remaining_evidence as remaining
    root, destination = Path(root).resolve(), Path(destination).resolve()
    inventory = runtime_component(root) if inventory is None else inventory
    bindings = runtime_bindings(root, inventory)
    destination.mkdir(parents=True, exist_ok=True)
    anchors = anchors or {}
    if set(anchors) - set(bindings): raise ValueError('Runtime selected anchor is outside exact family')
    for identity, anchor in anchors.items():
        if (set(anchor) != {'ordinary_test_run_attachment', 'relevant_sources', 'evidence'}
                or anchor['ordinary_test_run_attachment'] is not True or set(anchor['evidence']) != {'program'}):
            raise ValueError('Runtime anchor requires original ordinary program evidence')
        bindings[identity].update(deepcopy(anchor))
    rows = {r['id']: r for r in inventory['native_coverage']['obligations']}
    groups = defaultdict(dict)
    requirements = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {}, 'representative_mechanisms': {}}
    preserved = remaining.review(root)['entries']
    for identity, binding in bindings.items():
        mechanism = binding['representative_mechanism']
        groups[mechanism][identity] = binding
        branch = rows[identity]
        policy = (remaining.counterexample_policy(branch, root) if branch['route'].endswith('.moveCursor')
            and branch['pointer'] == '/argsSchema/properties/position/@empty/string' else remaining.policy(preserved[identity]))
        requirements['branches'][identity] = {**policy, 'representative_mechanism': mechanism}
    for mechanism, members in groups.items():
        selected = sorted(set(members) & set(anchors))
        if len(selected) > 1: raise ValueError('Runtime mechanism uses one selected ordinary anchor')
        requirements['representative_mechanisms'][mechanism] = {
            'contract': 'waapi-skill.representative-branch-mechanism/v1', 'scope_kind': 'product',
            'candidate_sha256': inventory['native_coverage']['candidate_sha256'],
            'reviewed_reason': 'Exact remaining runtime wrapper mapping with truthful schema/host/version/effect limits; aggregate CODE only',
            'sources': {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in SOURCES},
            'members': {identity: {'native_route': rows[identity]['route'], 'native_shape_sha256': rows[identity]['shape_sha256'],
                'mapping_sha256': digest({k: v for k, v in binding.items() if k != 'evidence'})} for identity, binding in members.items()},
            'selected_proofs': {'program': selected or [min(members)],
                **({'native': [min(identity for identity in members if 'native' in requirements['branches'][identity]['categories'])]}
                   if any('native' in requirements['branches'][identity]['categories'] for identity in members) else {})}}
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
        raise ValueError('Runtime selected code anchor is missing or unfinalized')
    if not {node for nodes in SELECTED_TESTS.values() for node in nodes} <= set(plan['argv'][6:]):
        raise ValueError('Runtime code anchor omits a selected representative mechanism')
    originals = {}
    for name in RUNTIME_SOURCES | RUNNER_SOURCES:
        raw = subprocess.run(['git', 'show', plan['candidate'] + ':' + name], cwd=root,
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
        originals[name] = hashlib.sha256(raw).hexdigest()
        if name in RUNTIME_SOURCES and hashlib.sha256((root / name).read_bytes()).hexdigest() != originals[name]:
            raise ValueError('Runtime relevant selected source changed: ' + name)
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
    for identity, binding in runtime_bindings(root, inventory).items():
        selected.setdefault(binding['representative_mechanism'], (identity, binding))
    anchors = {}
    for number, (mechanism, (identity, binding)) in enumerate(sorted(selected.items()), 1):
        anchor = {'ordinary_test_run_attachment': True, 'relevant_sources': sorted(RUNTIME_SOURCES), 'evidence': {}}
        binding.update(anchor)
        group = mechanism.removeprefix('runtime195-remaining-').removesuffix('-v1').removesuffix('-native-root')
        proof = {'contract': 'waapi-skill.ordinary-test-run-attachment/v1', 'scope_kind': 'product',
            'candidate_sha256': inventory['native_coverage']['candidate_sha256'], 'original_candidate': plan['candidate'],
            'files': files, 'original_sources': originals, 'skip_lines': [],
            'review': {'reason': 'Byte-identical relevant sources in an actual focused aggregate CODE run; no native/per-node observation inferred',
                'selection_reason': 'Accepted #186 representative closed construction, ownership, normalized-default and weak-result controls; original native histories remain separate, not rerun per mapping leaf',
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
