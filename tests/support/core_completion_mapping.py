"""Exact #191 input/result mapping, with representative CODE proof kept separate.

Discovery reads all ten pinned catalogs before consulting the public contracts.
Table acceptance never manufactures native evidence or erases original failures.
"""
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
BASE = 'tests/fixtures/branch-evidence/product/core-195-r1/'
POLICY = 'docs/plans/full-waapi-coverage/SPEC.md'
TICKETS = ['docs/plans/full-waapi-coverage/tickets/17-complete-specialized-project-and-object-authoring-operations.md']
OWNERS = {"ak.wwise.core." + name: 191 for name in (
    'audio.mute', 'audio.resetMute', 'audio.resetSolo', 'audio.solo',
    'blendContainer.addAssignment', 'blendContainer.addTrack', 'blendContainer.getAssignments', 'blendContainer.removeAssignment',
    'gameParameter.setRange', 'object.getAttenuationCurve', 'object.pasteProperties', 'object.setAttenuationCurve',
    'object.setRandomizer', 'object.setStateGroups', 'object.setStateProperties', 'sound.setActiveSource',
    'switchContainer.addAssignment', 'switchContainer.getAssignments', 'switchContainer.removeAssignment')}
ACCEPTED_LIMITS = {
    'lightweight': 'complete closed versioned wrappers and representative CODE; original native facts retained without upgrade',
    'blend': 'indexed order and stable fields checked; requested edge applicability/effects and adjacent Automatic geometry remain unverified',
    'game_parameter': 'Min/Max readback does not prove dependent curve/Action effects',
    'paste_state_randomizer_audio': 'truthfully disclosed result-schema-only verification',
    'active_source': 'existing linkage; exact Tone host/build/context boundaries retained, not all source plugins excluded',
}

def discover_core(root):
    """Expand reachable definitions; retain every host/version and reference site."""
    from wwise_waapi.native_catalog import load_native_catalog, NATIVE_HOSTS
    from wwise_waapi.schema_inventory import DefinitionGraph, resolve_schema_reference
    from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS
    root = Path(root)
    owners = json.loads((root / 'docs/branch-coverage-ownership.json').read_bytes())['routes']
    if {key.split('|', 1)[1]: value['owner_issue'] for key, value in owners.items()
            if value['owner_issue'] == 191} != OWNERS:
        raise ValueError('Core exact #191 ownership roster changed')
    routes, rows, catalogs, locations = [], {}, {}, defaultdict(list)
    for version in SUPPORTED_WWISE_VERSION_KEYS:
        for host in NATIVE_HOSTS:
            catalog = load_native_catalog(version, host, root=root / 'skills/waapi-skill/resources/native-catalog')
            build = catalog['provenance']['build']
            catalogs[f'{version}|{host}|{build}'] = catalog['content_sha256']
            graph = DefinitionGraph(**{k: catalog['definitions'][k] for k in
                ('contract', 'version', 'wwise_build', 'source_file_names', 'documents', 'inventory_sha256')})
            # No assumption that Authoring and Console or version rosters agree.
            for uri in sorted(set(catalog['functions']) & set(OWNERS)):
                native = f'{version}|{host}|{build}|function|{uri}'
                routes.append({'id': native, 'version': version, 'host': host, 'build': build,
                    'kind': 'function', 'uri': uri, 'owner_issue': OWNERS[uri],
                    'native_schema_sha256': digest(catalog['schemas'][uri]),
                    'public_route': f'{version}|function|{uri}'})
                for section in ('argsSchema', 'optionsSchema', 'resultSchema'):
                    schema = catalog['schemas'][uri][section]
                    def visit(value, pointer, context, document, active, location):
                        for item in schema_branches(value, pointer):
                            identity = native + '|' + item['pointer']
                            address = location + _path(item['pointer'][len(pointer):], schema=value,
                                schema_pointer=pointer, legacy_paths=frozenset())
                            if address not in locations[identity]:
                                locations[identity].append(address)
                            row = {'id': identity, 'route': native, 'pointer': item['pointer'],
                                'kind': item['kind'], 'shape_sha256': digest(item['value']),
                                'owner_issue': OWNERS[uri], 'parent_issue': 174, 'blocks_issue': 195, 'state': 'unresolved'}
                            if item['kind'] != 'schema':
                                row['value'] = item['value']
                            if item['kind'] == 'reference':
                                target = resolve_schema_reference(item['value'], root_schema=context, graph=graph)
                                doc = document if target.document_name == '<schema>' else target.document_name
                                key = (doc, target.pointer)
                                ptr = '/' + section + '/@definition/' + doc + target.pointer
                                row['reference'] = {'target': native + '|' + ptr, 'recursive': key in active,
                                    'document': doc, 'target_sha256': digest(target.target)}
                                if key not in active:
                                    visit(target.target, ptr, context if target.document_name == '<schema>' else graph.documents[doc],
                                        doc, active | {key}, address)
                            if identity in rows and rows[identity] != row:
                                raise ValueError('Core reachable definition identity collision')
                            rows[identity] = row
                    visit(schema, '/' + section, schema, '<schema>', set(), [])
    return {'routes': routes, 'catalogs': catalogs, 'obligations': sorted(rows.values(), key=lambda r: r['id'])}, dict(locations)


def core_component(root):
    from tests.maintenance.branch_audit_completion import candidate_identity
    from tests.maintenance.branch_audit_mapping import debug_control_component
    root = Path(root)
    native, locations = discover_core(root)
    observed = {row['id']: {'kind': row['kind'], 'shape_sha256': row['shape_sha256']} for row in native['obligations']}
    roster = json.loads((root / BASE / 'source-roster.json').read_bytes())
    if roster != {'catalogs': native['catalogs'], 'entries': observed}:
        raise ValueError('Core native field/choice/version/definition differs from reviewed roster')
    wanted = {route['public_route'] for route in native['routes']}
    public = [deepcopy(row) for row in json.loads((root / 'docs/branch-coverage-inventory.json').read_bytes())['routes']
        if row['id'] in wanted]
    if {row['id'] for row in public} != wanted:
        raise ValueError('Core current public route/version missing')
    sources = debug_control_component(root)['sources']
    for name in [*TICKETS, POLICY,
            'tests/support/core_completion_mapping.py', 'tests/support/topic_completion_mapping.py',
            'tests/maintenance/map_core_completion.py', 'docs/plans/full-waapi-coverage/SPECIALIZED_LIGHTWEIGHT.md',
            'tests/semantic/support/codex_archive_paths.py', BASE + 'source-roster.json', BASE + 'accepted-history.json',
            *[str(path.relative_to(root)) for path in sorted((root / BASE / 'historical').glob('*.json'))]]:
        sources[name] = digest((root / name).read_text(encoding='utf-8'))
    component = {'component': 'core-195-r1', 'routes': public, 'sources': sources,
        'native_locations': locations, 'native_coverage': native, 'accepted_limits': ACCEPTED_LIMITS}
    native['candidate_sha256'] = candidate_identity(root, component, native['catalogs'], digest=digest)
    return component



FIELDS = {
    'audio.mute': {'objects': ['object_handles'], 'value': ['muted']},
    'audio.solo': {'objects': ['object_handles'], 'value': ['soloed']},
    'audio.resetMute': {}, 'audio.resetSolo': {},
    'blendContainer.addAssignment': {'object': ['blend_track_handle'], 'child': ['child_handle'],
        'index': ['insertion_index'], 'edges': ['edges'], 'edgePosition': ['edges[].edge_position'],
        'fadeMode': ['edges[].fade_mode'], 'fadePosition': ['edges[].fade_position'], 'fadeShape': ['edges[].shape']},
    'blendContainer.addTrack': {'object': ['blend_container_handle'], 'name': ['track_name'], 'id': []},
    'blendContainer.getAssignments': {'object': ['object_id']},
    'blendContainer.removeAssignment': {'object': ['blend_track_handle'], 'child': ['child_handle']},
    'gameParameter.setRange': {'object': ['game_parameter_handle'], 'min': ['minimum'], 'max': ['maximum'], 'onCurveUpdate': ['curve_update_outcome']},
    'object.getAttenuationCurve': {'object': ['exact_id', 'path_segments'], 'curveType': ['curve_role'], 'platform': ['platform']},
    'object.setAttenuationCurve': {'object': ['attenuation_handle'], 'curveType': ['curve_kind'], 'use': ['curve_source'],
        'points': ['points'], 'x': ['points[].x'], 'y': ['points[].y'], 'shape': ['points[].shape'], 'platform': ['platform_name']},
    'object.pasteProperties': {'source': ['source_handle'], 'targets': ['target_handles'],
        'inclusion': ['include_field_handles'], 'exclusion': ['exclude_field_handles'], 'pasteMode': ['list_mode']},
    'object.setRandomizer': {'object': ['object_handle'], 'property': ['field_handle'], 'enabled': ['enabled'],
        'min': ['minimum_offset'], 'max': ['maximum_offset'], 'platform': ['platform_name']},
    'object.setStateGroups': {'object': ['object_handle'], 'stateGroups': ['state_group_handles']},
    'object.setStateProperties': {'object': ['object_handle'], 'stateProperties': ['field_handles']},
    'sound.setActiveSource': {'sound': ['sound_handle'], 'source': ['source_handle'], 'platform': ['platform_name']},
    'switchContainer.addAssignment': {'child': ['child_handle'], 'stateOrSwitch': ['state_or_switch_handle']},
    'switchContainer.removeAssignment': {'child': ['child_handle'], 'stateOrSwitch': ['state_or_switch_handle']},
    'switchContainer.getAssignments': {'id': ['object_id']},
}


def _contract(route):
    from wwise_waapi.core_business_contracts import core_business_contract_data
    from wwise_waapi.project_setting_business_contracts import project_setting_business_contract_data
    from wwise_waapi.switch_assignment_business_contracts import switch_assignment_business_contract_data
    uri, version = route['uri'], route['version']
    name = uri.removeprefix('ak.wwise.core.')
    if name in ('sound.setActiveSource', 'gameParameter.setRange'):
        return project_setting_business_contract_data(uri, version)
    if name in ('switchContainer.addAssignment', 'switchContainer.removeAssignment'):
        return switch_assignment_business_contract_data(name, version)
    if name in ('audio.resetMute', 'audio.resetSolo'):
        from wwise_waapi.typed_requests import request_contract
        contract = request_contract(version, uri)
        if contract.fields: raise ValueError('Core reset no longer has an empty native input')
        return {'schema_digest': contract.schema_digest, 'declaration': {'required_fields': [], 'optional_fields': []},
            'start': {'gateway_argv': ['request-schema', uri]}, 'execution': 'typed-zero-call --apply, immutable preview then authorization/execute/verify'}
    if name == 'object.getAttenuationCurve':
        from tests.unit.test_core_business_gateway import gateway
        return {'declaration': {'required_fields': ['exact_id', 'path_segments', 'curve_role'], 'optional_fields': ['platform']},
            'curve_roles': gateway.metadata_attenuation_curve_roles(version),
            'start': {'gateway_argv': ['metadata', 'attenuation']}}
    return core_business_contract_data(uri, version)


def _mechanism(uri):
    name = uri.removeprefix('ak.wwise.core.')
    if name.startswith('audio.'): return 'audio'
    if name.startswith('blendContainer.'): return 'blend'
    if name.startswith('switchContainer.'): return 'switch'
    if name.endswith('AttenuationCurve'): return 'curve'
    if name.startswith(('gameParameter.', 'sound.')): return 'project-setting'
    return 'fields'


def _choice_map(name, field, contract):
    # GET and SET intentionally have different versioned native shelf spellings.
    from wwise_waapi.core_business_contracts import _CURVE_KINDS, _CURVE_SOURCES, _CURVE_SHAPES
    from wwise_waapi.core_business_contracts import _PASTE_MODES, _FADE_MODES
    from wwise_waapi.project_setting_business_contracts import _CURVE_UPDATE_OUTCOMES
    if field == 'curve_role': return contract['curve_roles']
    if field == 'curve_kind': return _CURVE_KINDS
    if field == 'curve_source': return _CURVE_SOURCES
    if field in ('points[].shape', 'edges[].shape'): return _CURVE_SHAPES
    if field == 'edges[].fade_mode': return _FADE_MODES
    if field == 'list_mode': return _PASTE_MODES
    if field == 'curve_update_outcome': return _CURVE_UPDATE_OUTCOMES
    return None


def _correspondence(row, route, addresses, contract):
    uri, pointer = route['uri'], row['pointer']
    name, section = uri.removeprefix('ak.wwise.core.'), pointer.split('/')[1]
    fields, rule = [], 'closed_argument_envelope'
    if section == 'optionsSchema':
        rule = 'fixed_empty_options'
    elif section == 'resultSchema':
        rule = 'bounded_native_result_preserved'
    else:
        for path in addresses:
            if not path or path == ['*']: continue
            top = path[0]
            # Reachable object/platform GUID/path alternatives all resolve through
            # the same exact bound identity, never raw caller native envelopes.
            native = path[-1] if name == 'blendContainer.addAssignment' and top == 'edges' and path[-1] in FIELDS[name] else top
            if name == 'object.setAttenuationCurve' and top == 'points' and path[-1] in ('x', 'y', 'shape'): native = path[-1]
            if native not in FIELDS[name]: raise ValueError('Core unreviewed native argument: ' + name + '/' + repr(path))
            fields.extend(FIELDS[name][native])
        fields = sorted(set(fields))
        exposed = set(contract['declaration']['required_fields']) | set(contract['declaration'].get('optional_fields', []))
        if {f.split('[')[0].split('.')[0] for f in fields} - exposed:
            raise ValueError('Core mapped public field is not disclosed: ' + uri + ' ' + repr(fields))
        rule = 'internal_identifier_not_public' if name == 'blendContainer.addTrack' and any(p and p[0] == 'id' for p in addresses) else 'closed_business_fields'
    mapped = {'rule': rule, 'native_addresses': addresses, 'public_fields': fields,
        'public_contract_sha256': digest(contract), 'native_effect': 'not_claimed',
        'choice': {'kind': row['kind'], **({'value': row['value']} if 'value' in row else {})},
        'encoding': 'Gateway owns canonical GUID placement, native envelopes and enum translation; finite business scalars and ordered rows preserved within disclosed bounds',
        'result_boundary': 'bounded native result/verification retained; schema acknowledgement is not independent state/effect proof',
        'accepted_limits': ACCEPTED_LIMITS}
    if row['kind'] == 'enum_value':
        mapped['native_choice'] = row['value']
        choices = sorted({business for field in fields for business, native in (_choice_map(name, field, contract) or {}).items() if native == row['value']})
        if section == 'argsSchema':
            enum_fields = [f for f in fields if _choice_map(name, f, contract) is not None]
            if enum_fields and not choices: raise ValueError('Core native enum has no public choice: ' + str(row['value']))
            for field in enum_fields:
                domains = contract['declaration'].get('value_domains', {})
                domain = ({'choices': domains.get('points', {}).get('shape_choices')} if field == 'points[].shape' else
                    {'choices': domains.get('edges', {}).get('shape_choices' if field == 'edges[].shape' else 'fade_mode_choices')}
                    if field in ('edges[].shape', 'edges[].fade_mode') else domains.get(field, {}))
                if domain.get('choices') is not None and not set(choices) <= set(domain['choices']):
                    raise ValueError('Core missing public choice: ' + repr(choices))
        mapped['public_choices'] = choices
    if 'reference' in row: mapped['reference'] = row['reference']
    if name.startswith('blendContainer.'):
        mapped['ordered_assignment_scope'] = 'indexed_order_and_stable_fields; Automatic_adjacent_geometry_unverified'
        mapped['blend_defaults'] = 'omit index = append, explicit integer clamped to [0,n]; omit edges = native defaults; two ordered left/right edges when supplied; fade_position used only in Manual mode'
    if name in ('object.setStateGroups', 'object.setStateProperties'):
        mapped['empty_replacement'] = True
        mapped['array_semantics'] = 'explicit --empty clears replacement; omission rejected; nonempty ordered bound members retained'
    if name == 'object.pasteProperties':
        mapped['paste_semantics'] = 'omitted inclusion = all, omitted exclusion = none; both accepted with no inferred precedence/effect; omitted list_mode = native replaceEntire (public replace)'
        mapped['empty_noop_boundary'] = 'empty inclusion/targets has no requested transfer and is not a business mutation; empty exclusion normalized by omission; fields remain source-scoped'
    if name == 'object.setRandomizer': mapped['omission'] = 'one or more of enabled/minimum_offset/maximum_offset required; omitted fields remain omitted; min<=0,max>=0; platform omitted or exact name/GUID'
    if name.endswith('AttenuationCurve'):
        mapped['curve_scope'] = 'read role maps to exact getter enum, setter kind to exact setter enum; Custom requires supplied ordered finite points, non-Custom requires empty points; no automatic distance/range editing'
        mapped['platform_scope'] = 'omitted native context or supplied platform spelling including null GUID for unlinked reference; no inferred platform-linkage effect'
    return mapped


def core_bindings(root, inventory):
    root = Path(root)
    native = inventory['native_coverage']
    roster = json.loads((root / BASE / 'source-roster.json').read_bytes())
    if roster != {'catalogs': native['catalogs'], 'entries': {r['id']: {'kind': r['kind'], 'shape_sha256': r['shape_sha256']} for r in native['obligations']}}:
        raise ValueError('Core native field/choice/version roster differs')
    public, routes = {r['id']: r for r in inventory['routes']}, {r['id']: r for r in native['routes']}
    if {r['route'] for r in native['obligations']} != set(routes) or {r['public_route'] for r in routes.values()} != set(public):
        raise ValueError('Core native/public route roster differs')
    contracts = {r['public_route']: _contract(r) for r in routes.values()}
    bindings = {}
    for row in native['obligations']:
        route = routes[row['route']]; uri, section = route['uri'], row['pointer'].split('/')[1]
        name = uri.removeprefix('ak.wwise.core.'); contract = contracts[route['public_route']]
        module, symbol = ('project_setting_business', 'materialize_project_setting_business_request') if name.startswith(('gameParameter.', 'sound.')) else (
            ('switch_assignment_business', 'materialize_switch_assignment_business_request') if name in ('switchContainer.addAssignment', 'switchContainer.removeAssignment') else
            ('operation_registry', 'prepare_operation') if name in ('audio.resetMute', 'audio.resetSolo') else
            ('core_business', 'materialize_core_business_request'))
        construction = LIB + module + '.py#' + symbol
        if name == 'object.getAttenuationCurve': construction = GATEWAY + '#preflight_metadata_input'
        argv = contract.get('start', {}).get('gateway_argv', contract.get('start', {}).get('gateway_argv_prefix', ['core-call', uri]))
        bindings[row['id']] = {'branch_id': row['id'], 'native_shape_sha256': row['shape_sha256'],
            'public_route': route['public_route'], 'public_route_sha256': digest(public[route['public_route']]),
            'input': {'gateway_argv': argv, 'declaration': contract.get('declaration', {}).get('subcommand'), 'selector': row['pointer'],
                'correspondence': _correspondence(row, route, inventory['native_locations'][row['id']], contract)},
            'construction': {'source': construction, 'selector': row['pointer']},
            'validation': {'source': LIB + 'builders/schema.py#' + ('validate_semantic_result' if section == 'resultSchema' else 'validate_semantic_payload'), 'selector': row['pointer']},
            'verifier': {'source': LIB + 'operation_registry.py#verify_prepared_operation', 'selector': row['pointer']},
            'representative_mechanism': 'core195-' + _mechanism(uri) + '-v1', 'evidence': {}}
    return bindings

SELECTED_TESTS = {
    'curve': ['tests/unit/test_attenuation_curve_business_gateway.py::test_bound_curve_continuation_keeps_public_domains_and_accepts_disclosed_linear',
        'tests/unit/test_metadata_discovery_gateway.py::test_metadata_attenuation_compiles_business_curve_role'],
    'fields': ['tests/unit/test_core_business_gateway.py::test_randomizer_core_plan_discovers_field_by_meaning_then_closes_values',
        'tests/unit/test_core_business_gateway.py::test_state_replacement_explicit_empty_is_callable_and_result_only',
        'tests/unit/test_core_business_gateway.py::test_paste_accepts_both_documented_lists_without_claiming_combined_effect',
        'tests/unit/test_specialized_core_choices_gateway.py::test_paste_schema_discloses_all_list_outcomes_and_documented_default'],
    'blend': ['tests/unit/test_core_business_gateway.py::test_blend_assignment_documented_positions_and_retained_edges',
        'tests/unit/test_core_business_gateway.py::test_blend_automatic_neighbor_geometry_remains_disclosed_partial_observation',
        'tests/unit/test_core_business_gateway.py::test_blend_assignment_prewrite_snapshot_drift_never_dispatches',
        'tests/unit/test_specialized_core_choices_gateway.py::test_blend_schema_discloses_closed_edge_modes_shapes_and_order'],
    'switch': ['tests/unit/test_switch_assignment_business_gateway.py::test_gateway_binds_three_roles_then_materializes_assignment',
        'tests/unit/test_switch_assignment_business_gateway.py::test_switch_child_accepts_an_additional_distinct_value_and_preserves_old_pair'],
    'audio': ['tests/unit/test_transaction_gateway.py::test_zero_input_generic_mutation_enters_existing_preview_lifecycle',
        'tests/unit/test_core_business_adapter.py::test_simple_core_business_outcomes_compile_only_bound_roles'],
    'project-setting': ['tests/unit/test_remaining_core_business_gateway.py::test_project_setting_gateway_binds_exact_roles_then_seals_readback_preview',
        'tests/unit/test_remaining_core_business_gateway.py::test_game_parameter_exact_name_binding_resolves_inside_the_draft'],
}
RUNTIME_SOURCES = {GATEWAY, 'tests/support/gateway_config.py',
    *(node.split('::')[0] for nodes in SELECTED_TESTS.values() for node in nodes),
    *(LIB + name + '.py' for name in ('core_business', 'core_business_contracts', 'project_setting_business',
        'project_setting_business_contracts', 'switch_assignment_business', 'switch_assignment_business_contracts',
        'blend_assignment', 'business_adapters', 'business_declaration_state', 'business_declarations', 'business_fields',
        'operation_registry', 'operation_drafts', 'operation_composer', 'transactions', 'transaction_runtime',
        'transaction_cleanup', 'dispatcher', 'config', 'capabilities', 'execution_contracts', 'builders/schema', 'typed_requests', 'io_policy'))}

def core_program_anchors(root, inventory, destination, run):
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
        raise ValueError('Core selected code anchor is missing or unfinalized')
    if not {node for nodes in SELECTED_TESTS.values() for node in nodes} <= set(plan['argv'][6:]):
        raise ValueError('Core code anchor omits a selected representative mechanism')
    originals = {}
    for name in RUNTIME_SOURCES | RUNNER_SOURCES:
        raw = subprocess.run(['git', 'show', plan['candidate'] + ':' + name], cwd=root,
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
        originals[name] = hashlib.sha256(raw).hexdigest()
        if name in RUNTIME_SOURCES and hashlib.sha256((root / name).read_bytes()).hexdigest() != originals[name]:
            raise ValueError('Core relevant selected source changed: ' + name)
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
    for identity, binding in core_bindings(root, inventory).items():
        selected.setdefault(binding['representative_mechanism'], (identity, binding))
    anchors = {}
    for number, (mechanism, (identity, binding)) in enumerate(sorted(selected.items()), 1):
        anchor = {'ordinary_test_run_attachment': True, 'relevant_sources': sorted(RUNTIME_SOURCES), 'evidence': {}}
        binding.update(anchor)
        group = mechanism.removeprefix('core195-').removesuffix('-v1')
        proof = {'contract': 'waapi-skill.ordinary-test-run-attachment/v1', 'scope_kind': 'product',
            'candidate_sha256': inventory['native_coverage']['candidate_sha256'], 'original_candidate': plan['candidate'],
            'files': files, 'original_sources': originals, 'skip_lines': [],
            'review': {'reason': 'Byte-identical relevant sources in an actual focused aggregate CODE run; no native/per-node observation inferred',
                'selection_reason': 'Accepted #191 representative closed construction and safety/weak-result controls; original native histories remain separate, not rerun per mapping leaf',
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


def export_core_mapping(root, destination, *, inventory=None, anchors=None):
    """Use standard mapping attachments and bounded requirements parts only."""
    from tests.maintenance.branch_coverage_audit import write_requirements
    from tests.semantic.support.codex_archive_paths import archive_relative_from_absolute
    root, destination = Path(root).resolve(), Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    inventory = core_component(root) if inventory is None else inventory
    bindings = core_bindings(root, inventory)
    anchors = anchors or {}
    if set(anchors) - set(bindings):
        raise ValueError('Core selected anchor is outside exact family')
    for identity, anchor in anchors.items():
        if (set(anchor) != {'ordinary_test_run_attachment', 'relevant_sources', 'evidence'}
                or anchor['ordinary_test_run_attachment'] is not True or set(anchor['evidence']) != {'program'}):
            raise ValueError('Core anchor requires original ordinary program evidence')
        bindings[identity].update(deepcopy(anchor))
    rows = {row['id']: row for row in inventory['native_coverage']['obligations']}
    requirements = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {}, 'representative_mechanisms': {}}
    groups = defaultdict(dict)
    for identity, binding in bindings.items():
        mechanism = binding['representative_mechanism']
        groups[mechanism][identity] = binding
        requirements['branches'][identity] = {'native_shape_sha256': rows[identity]['shape_sha256'],
            'categories': ['program'], 'representative_mechanism': mechanism,
            'reason': 'Accepted #191 representative mapping/code policy; retained native proof and limits separately attributed; no new per-leaf/native credit'}
    for mechanism, members in groups.items():
        selected = sorted(set(members) & set(anchors))
        if len(selected) > 1:
            raise ValueError('Core mechanism requires one selected ordinary anchor')
        sources = {binding[key]['source'].split('#')[0] for binding in members.values()
            for key in ('construction', 'validation', 'verifier')}
        sources.update({POLICY, *TICKETS, LIB + 'core_business_contracts.py', LIB + 'project_setting_business_contracts.py',
            LIB + 'switch_assignment_business_contracts.py', LIB + 'blend_assignment.py'})
        requirements['representative_mechanisms'][mechanism] = {
            'contract': 'waapi-skill.representative-branch-mechanism/v1', 'scope_kind': 'product',
            'candidate_sha256': inventory['native_coverage']['candidate_sha256'],
            'reviewed_reason': 'Exact versioned #191 closed mapping and accepted verification limits; aggregate CODE mechanism only, no member native effect claim',
            'sources': {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sorted(sources)},
            'members': {identity: {'native_route': rows[identity]['route'], 'native_shape_sha256': rows[identity]['shape_sha256'],
                'mapping_sha256': digest({key: value for key, value in binding.items() if key != 'evidence'})} for identity, binding in members.items()},
            'selected_proofs': {'program': selected or [min(members)]}}
    def write(name, body):
        path = destination / name
        path.write_text(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n', encoding='utf-8')
        return {'artifact': archive_relative_from_absolute(path, destination).canonical,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    entries, descriptors = [], []
    for number, (mechanism, members) in enumerate(sorted(groups.items()), 1):
        for identity in sorted(set(members) & set(anchors)):
            original = deepcopy(members[identity])
            record = {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': {identity: original}}
            binding_descriptor = write(f'selected-{number:02}.json', record)
            policy_descriptor = write(f'selected-policy-{number:02}.json', {'contract': requirements['contract'],
                'branches': {identity: requirements['branches'][identity]}})
            entries.append({'id': identity, 'bindings': binding_descriptor, 'origin': {
                'bindings': binding_descriptor, 'program': original['evidence']['program'], 'requirements': policy_descriptor,
                'capture': write(f'selected-review-{number:02}.json', {'mechanism': mechanism,
                    'scope': 'actual aggregate CODE proof; no per-node/native observation'})}})
        proposed = deepcopy(members)
        predecessors = {identity: {'binding_sha256': digest(binding), 'policy_sha256': digest(requirements['branches'][identity])}
            if identity in anchors else None for identity, binding in members.items()}
        for binding in proposed.values():
            binding['evidence'] = {}
        descriptors.append(write(f'mapping-{number:02}.json', {'contract': 'waapi-skill.branch-mapping-attachment/v1',
            'scope_kind': 'product', 'requirements_sha256': digest(requirements), 'mechanisms': [mechanism],
            'bindings': proposed, 'predecessors': predecessors}))
    write_requirements(destination / 'requirements.json', requirements)
    index = {'contract': 'waapi-skill.branch-evidence-index/v1', 'base': '.', 'entries': entries, 'mapping_attachments': descriptors}
    write('evidence-index.json', index)
    summary = {'component': inventory['component'], 'public_routes': len(inventory['routes']),
        'native_routes': len(inventory['native_coverage']['routes']), 'native_members': len(rows),
        'catalogs': inventory['native_coverage']['catalogs'], 'candidate_sha256': inventory['native_coverage']['candidate_sha256'],
        'mechanisms': {key: len(members) for key, members in sorted(groups.items())},
        'mapping_is_not_execution_credit': True, 'native_or_fresh_started': False,
        'canonical_import_pending': True, 'largest_mapping_bytes': max((destination / d['artifact']).stat().st_size for d in descriptors)}
    write('summary.json', summary)
    return {'index_path': destination / 'evidence-index.json', 'requirements': requirements, 'summary': summary}
