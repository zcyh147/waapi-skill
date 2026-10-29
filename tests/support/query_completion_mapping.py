"""Exact owner #181 joins against ten pinned catalogs; mappings are not receipts.

Closed business declarations and the separately bounded advanced read compiler
own construction. This exporter adds no public request or native payload input.
"""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import re
from pathlib import Path
from tests.maintenance.branch_coverage_audit import digest, schema_branches

LIB = 'skills/waapi-skill/wwise_waapi/'
GATEWAY = 'skills/waapi-skill/scripts/gateway.py'
POLICY = 'docs/plans/full-waapi-coverage/tickets/07-complete-object-queries-and-metadata-discovery-projections.md'
BASE = 'tests/fixtures/branch-evidence/product/query-mapping-195-r1/'
VERSIONS = ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1')
URIS = tuple('ak.wwise.core.' + name for name in (
    'audioSourcePeaks.getMinMaxPeaksInRegion', 'audioSourcePeaks.getMinMaxPeaksInTrimmedRegion',
    'mediaPool.get', 'mediaPool.getFields', 'object.get', 'object.getPropertyAndReferenceNames',
    'object.getPropertyInfo', 'object.getTypes', 'object.isPropertyEnabled'))


def discover_queries(root):
    """Expand native sources before joining any public surface or evidence."""
    from wwise_waapi.native_catalog import load_native_catalog, NATIVE_HOSTS
    from wwise_waapi.schema_inventory import DefinitionGraph, resolve_schema_reference
    root = Path(root)
    owners = json.loads((root / 'docs/branch-coverage-ownership.json').read_bytes())['routes']
    if {key for key, row in owners.items() if row['owner_issue'] == 181} != {'function|' + uri for uri in URIS}:
        raise ValueError('Query exact owner #181 URI roster differs')
    catalogs, routes, rows = {}, [], []
    for version in VERSIONS:
        for host in NATIVE_HOSTS:
            catalog = load_native_catalog(version, host, root=root / 'skills/waapi-skill/resources/native-catalog')
            build = catalog['provenance']['build']
            catalogs[f'{version}|{host}|{build}'] = catalog['content_sha256']
            graph = DefinitionGraph(**{key: catalog['definitions'][key] for key in
                ('contract', 'version', 'wwise_build', 'source_file_names', 'documents', 'inventory_sha256')})
            wanted = {uri for uri in URIS if '.mediaPool.' not in uri or version == '2025.1'}
            if set(URIS) & set(catalog['functions']) != wanted:
                raise ValueError('Query native host/version roster differs')
            for uri in sorted(wanted):
                identity = f'{version}|{host}|{build}|function|{uri}'
                routes.append({'id': identity, 'version': version, 'host': host, 'build': build,
                    'kind': 'function', 'uri': uri, 'native_schema_sha256': digest(catalog['schemas'][uri]),
                    'public_route': f'{version}|function|{uri}'})
                for section in ('argsSchema', 'optionsSchema', 'resultSchema'):
                    schema = catalog['schemas'][uri][section]
                    visited = set()
                    def visit(value, pointer, context, document, active):
                        for item in schema_branches(value, pointer):
                            row = {'id': identity + '|' + item['pointer'], 'route': identity,
                                'pointer': item['pointer'], 'kind': item['kind'], 'shape_sha256': digest(item['value']),
                                'owner_issue': 181, 'parent_issue': 174, 'blocks_issue': 195, 'state': 'unresolved'}
                            if item['kind'] != 'schema':
                                row['value'] = item['value']
                            rows.append(row)
                            if item['kind'] != 'reference':
                                continue
                            target = resolve_schema_reference(item['value'], root_schema=context, graph=graph)
                            doc = document if target.document_name == '<schema>' else target.document_name
                            key = (doc, target.pointer)
                            ptr = '/' + section + '/@definition/' + doc + target.pointer
                            row['reference'] = {'target': identity + '|' + ptr, 'recursive': key in active,
                                'document': doc, 'target_sha256': digest(target.target)}
                            if key not in visited:
                                visited.add(key)
                                visit(target.target, ptr, context if target.document_name == '<schema>' else graph.documents[doc], doc, active | {key})
                    visit(schema, '/' + section, schema, '<schema>', set())
    if len(routes) != 74 or len(rows) != len({row['id'] for row in rows}):
        raise ValueError('Query duplicate or missing native route/branch')
    return {'catalogs': catalogs, 'routes': routes, 'obligations': rows}


def query_component(root):
    from tests.maintenance.branch_audit_mapping import debug_control_component
    from tests.maintenance.branch_audit_completion import candidate_identity
    native = discover_queries(root)
    roster = json.loads((root / BASE / 'source-roster.json').read_bytes())
    if roster != {'catalogs': native['catalogs'], 'entries': {
            row['id']: {'kind': row['kind'], 'shape_sha256': row['shape_sha256']} for row in native['obligations']}}:
        raise ValueError('Query unhandled or missing exact native field/choice/definition')
    wanted = {row['public_route'] for row in native['routes']}
    public = [deepcopy(row) for row in json.loads((root / 'docs/branch-coverage-inventory.json').read_bytes())['routes'] if row['id'] in wanted]
    if {row['id'] for row in public} != wanted:
        raise ValueError('Query public route roster differs')
    sources = debug_control_component(root)['sources']
    for name in (POLICY, 'tests/support/query_completion_mapping.py', BASE + 'source-roster.json'):
        sources[name] = digest((root / name).read_text(encoding='utf-8'))
    inventory = {'component': 'query-mapping-195-r1', 'routes': public, 'sources': sources, 'native_coverage': native}
    native['candidate_sha256'] = candidate_identity(root, inventory, native['catalogs'], digest=digest)
    inventory['query_roster_sha256'] = digest([(row['id'], row['shape_sha256']) for row in native['obligations']])
    return inventory


def _native_paths(rows, section):
    """Use the ordinary reader's projection helper for every reference occurrence."""
    from tests.maintenance.branch_audit_completion import native_observation_pattern
    paths = {row['id']: [] for row in rows}
    def add(identity, path):
        if path not in paths[identity]:
            paths[identity].append(path)
            return True
        return False
    for row in rows:
        if '/@definition/' not in row['pointer'] and row['pointer'].startswith('/' + section):
            add(row['id'], native_observation_pattern(row['pointer']))
    changed = True
    while changed:
        changed = False
        for source in rows:
            if 'reference' not in source or source['reference']['recursive']:
                continue
            target = source['reference']['target']
            for row in rows:
                if row['id'] != target and not row['id'].startswith(target + '/'):
                    continue
                suffix = native_observation_pattern(row['id'][len(target):])
                for path in paths[source['id']]:
                    changed = add(row['id'], path + suffix) or changed
    return paths


QUERY_MECHANISMS = {
    'sources': GATEWAY + '#preflight_query_object_input',
    'compiler': LIB + 'builders/query.py#build_object_get_query',
    'projection': GATEWAY + '#_compile_query_business_projection',
    'metadata_fields': GATEWAY + '#_bind_query_custom_fields_from_live_metadata',
    'related': LIB + 'object_query_related_lists.py#RelatedListPlan',
    'result': GATEWAY + '#_project_query_business_rows',
    'pages': LIB + 'object_query_result_pages.py#ObjectQueryPlanStore',
}


def _query_correspondence(row, version, fields):
    from wwise_waapi.object_query_outputs import available_query_outputs
    section, pointer = row['pointer'].split('/')[1], row['pointer']
    outputs = available_query_outputs(version)
    native = row.get('value') if row['kind'] == 'enum_value' and '/definitions/returnExpression/items/anyOf/0' in pointer else None
    if '/definitions/objectReturn/properties/' in pointer:
        native = pointer.split('/definitions/objectReturn/properties/')[1].split('/')[0]
    choices = [name for name, (accessor, _) in outputs.items() if accessor == native] if native else []
    if native in {'id', 'name', 'type', 'path'}:
        choices = ['automatic_identity']
    if native and not choices:
        raise ValueError('Query native return choice lacks closed public correspondence: ' + str(native))
    if section == 'argsSchema':
        source_rules = {
            'id': '--exact-id fixes one canonical GUID; --short-id plus disclosed business kind resolves typed candidates to GUIDs before the requested read; multi-object source semantics use bounded advanced expression',
            'search': '--search-text forwards one validated literal search term to the owned WAQL source; explicit max-results',
            'name': '--kind/--custom-kind/--type-selection plus --predicate name-equals selects literal type/name candidates; exact selection retains ambiguity and exact-ID follow-up; qualified native name input is not reopened',
            'path': '--path-segment literal names build one exact Wwise path; multi-source selection requires bounded advanced expression',
            'ofType': '--kind selects closed type token, --custom-kind/--type-selection binds current exact getTypes name; multiple types require bounded advanced expression; native getTypes membership does not prove queryability',
            'query': '--query-id or --query-path-segment resolves a Query Editor object; no caller native query array',
            'select': '--relationship emits its fixed native WAQL relationship token in requested order',
            'distinct': 'advanced-waql exact distinct construct when server-side deduplication changes the bounded set; Gateway appends final take',
            'range': 'advanced-waql skip/take semantics when server-side slicing changes the bounded set; Gateway owns final take ceiling',
            'where': 'closed --predicate field/operator/value compiler, or a bounded advanced-waql predicate for otherwise inexpressible server-side semantics',
            'waql': 'closed sources, predicates, relationships and metadata-bound conditions compile WAQL; explicit bounded advanced-waql only after schema disclosure',
        }
        tokens = re.findall(r'/properties/([^/]+)', pointer)
        selected = next((token for token in reversed(tokens) if token in source_rules), None)
        if row.get('value') == 'distinct':
            selected = 'distinct'
        relation = None
        if row['kind'] == 'enum_value' and '/properties/select/' in pointer:
            from tests.maintenance.interface_depth_inventory import _gateway_module
            registry = _gateway_module().QUERY_BUSINESS_RELATIONSHIPS
            relation = [business for business, native in registry.items() if native == row['value']]
            if not relation:
                raise ValueError('Query relationship lacks closed public correspondence')
        return {'rule': 'controlled_read_compiler', 'selected_native_semantic': selected,
            'value_mapping': source_rules.get(selected, 'closed source/transform envelope; each exact child mapping remains separate'),
            'public_choices': relation or [], 'native_fields': sorted(fields) or ['from', 'transform', 'waql'],
            'public_inputs': ['query-schema', 'query-object --exact-id/--short-id/--path-segment/--kind/--type-selection',
                '--relationship', '--predicate', '--max-results', 'query-schema --advanced; query-object --advanced-waql'],
            'construction': 'closed declaration compiles WAQL; typed Short-ID prerequisite resolves exact GUID; advanced fixed object.get expression appends final take',
            'legacy_forms': 'from id/search/name/path/ofType/query and select/distinct/range/where transforms map to closed sources/relationships/predicates or the bounded advanced expression; no native from/transform input',
            'raw_args_options': 'rejected', 'native_language_equivalence': 'not_claimed',
            'bounds': 'Gateway owns explicit row/time/UTF-8/transport limits and framing; empty inputs, comments, semicolons and unclosed literals rejected',
            'mutation_authority': 'candidate selection requires exact-ID revalidation; advanced query never certifies uniqueness'}
    accessor = '/definitions/returnExpression/items/anyOf/1' in pointer
    return {'rule': 'metadata_compiled_accessor' if accessor else 'closed_query_return' if section == 'optionsSchema' else 'lossless_bounded_query_result',
        'native_fields': [native] if native else sorted(fields), 'public_choices': choices,
        'public_inputs': sorted('--' + field for field in fields & {'platform', 'language'}) if fields & {'platform', 'language'} else
            ['--include', '--include-field', '--include-override-source-value', '--include-local-reference', '--include-related', '--include-related-field', '--include-related-override-source-value', '--include-related-local-reference'],
        'projection': 'fixed business output key or metadata-bound property/reference key; declared spellings preserve actual native keys/values together without attribution; absent values unavailable, explicit null retained',
        'boundary': '2021 stored property-to-RTPC association unsupported; existing RTPC/Game Parameter/typed ControlInput reads retained; 2021 activeSource uses file-backed derivation after documented Console rejection',
        'native_language_equivalence': 'not_claimed', 'helper_provenance': 'grouped/sequence/context helpers retain provenance; no atomic-native-equivalence claim',
        'continuation': 'entire native result, exact fields, config, project, build/session revalidated; lossless value/document fragments; no query-exhaustion or mutation-selection claim',
        'mechanisms': QUERY_MECHANISMS}


def _metadata_correspondence(row, name, fields):
    section = row['pointer'].split('/')[1]
    inputs = {'classId': ['--kind', '--custom-kind', '--type-selection'],
        'object': ['--exact-id', '--path-segment'], 'property': ['--selection', '--meaning'], 'platform': ['--platform']}
    return {'rule': 'fixed_empty_options' if section == 'optionsSchema' else 'scoped_live_metadata' if section == 'argsSchema' else 'lossless_metadata_page',
        'native_fields': sorted(fields), 'scope_identity': 'native GUID/path/name/class/short-ID forms resolve through closed exact-object query or live type selection to one canonical scope; caller raw objectArg/classId/property is unavailable', 'public_inputs': sorted({flag for field in fields for flag in inputs.get(field, [])}),
        'scope': 'exact current object or exact live type/class; type/field selections bind inventory/config/project/version/build/session/expiry; no stale substitution',
        'property': 'Gateway selects exact token from current scoped names; raw name absence preserved and bound token separate; null/mismatch rejected',
        'result': 'raw native fields, defaults, constraints, enums, conditions, supports, extensions and unknown units preserved; omission differs from null; raw/choices/dependencies/detail-item pages or lossless fragments',
        'projection': LIB + 'metadata_detail.py#detail_page',
        'read_only': True, 'mutation_authority': False}


def _media_correspondence(row, uri, fields):
    section, pointer = row['pointer'].split('/')[1], row['pointer']
    if 'audioSourcePeaks' in uri:
        rules = {'object': '--audio-source-id: exact AudioFileSource GUID', 'numPeaks': '--peak-pair-count: whole 1..16384 pairs per channel',
            'timeFrom': '--start-seconds: finite nonnegative seconds', 'timeTo': '--end-seconds: after start_seconds',
            'getCrossChannelPeaks': '--channel-mode: per-channel=false (public default); cross-channel=true; native-default omits the native field without inferring its default'}
        return {'rule': 'closed_peak_read' if section == 'argsSchema' else 'fixed_empty_options' if section == 'optionsSchema' else 'decoded_peak_pairs_and_bounded_pages',
            'native_fields': sorted(fields), 'public_inputs': {field: rules[field] for field in fields if field in rules},
            'result': 'strict binary size/channel/pair checks then decoded min/max pairs; exact raw result digest and source/config/project/build/session bind channel-preserving pages; maxAbsValue and optional channelConfig preserved; no waveform-math or audio-effect claim'}
    mapping = {'databases': ['database_scopes', 'database_ids'], 'filters': ['text_filters', 'number_filters', 'audio_descriptions', 'weighted_audio_descriptions', 'audio_similarity_files', 'weighted_audio_similarity_files'],
        'maxResults': ['max_results'], 'searchText': ['search_text'], 'return': ['return_field_meanings']}
    return {'rule': 'closed_media_pool_read' if section != 'resultSchema' else 'lossless_media_pool_result',
        'native_fields': sorted(fields), 'public_inputs': {field: mapping[field] for field in fields if field in mapping},
        'filters': {'field': 'fresh getFields exact field binding; text/number value identity, including empty text',
            'operator': 'same finite operator spelling; text/numeric applicability checked',
            'type': 'field/audioDescription/audioSimilarity from selected declaration', 'value': 'typed text/finite number/exact safe audio-file path; no caller JSON',
            'weight': 'explicit finite weight identity; omission keeps default, no clamping'},
        'empty_input': 'empty search text and text field-filter values preserved; empty field meanings, audio descriptions and source filenames rejected before transport',
        'returns': 'exact live-field choices plus search-score=Score, file-size-bytes=Size, markers=Markers, detected-regions=DetectedRegions; Path/FileId/Db identity always retained; null distinct from missing',
        'pages': 'bounded prefix continuation revalidates prior result, field inventory and host/project/config; explicit ceiling never claims query exhaustion; fields inventory has lossless detail fragments',
        'version': '2025.1 only; earlier-version code gate, no invented native absence'}


def _validate_public_inputs():
    from tests.maintenance.interface_depth_inventory import _gateway_subparsers
    expected = {
        'query-object': {'--exact-id', '--path-segment', '--kind', '--custom-kind', '--type-selection', '--short-id', '--short-id-kind', '--search-text', '--query-id', '--query-path-segment', '--relationship', '--predicate', '--max-results', '--advanced-waql', '--include', '--include-field', '--include-override-source-value', '--include-local-reference', '--include-related', '--include-related-field', '--include-related-override-source-value', '--include-related-local-reference', '--platform', '--language', '--result-query', '--result-page'},
        'metadata': {'--exact-id', '--path-segment', '--kind', '--custom-kind', '--type-selection', '--meaning', '--selection', '--platform', '--page', '--page-size', '--detail-page', '--detail-view', '--detail-item'},
        'core-call': {'--audio-source-id', '--start-seconds', '--end-seconds', '--peak-pair-count', '--channel-mode', '--peak-page', '--max-results', '--database-scope', '--database-id', '--search-text', '--text-filter', '--number-filter', '--audio-description', '--weighted-audio-description', '--audio-similarity-file', '--weighted-audio-similarity-file', '--include-field', '--media-page'},
    }
    parsers = _gateway_subparsers()
    for command, flags in expected.items():
        exposed = {flag for action in parsers[command]._actions for flag in action.option_strings}
        if flags - exposed:
            raise ValueError('Query closed public input correspondence missing: ' + command + str(sorted(flags - exposed)))
    operations = next(action.choices for action in parsers['metadata']._actions if action.dest == 'operation')
    if not {'types', 'list', 'detail', 'discover', 'property-state', 'media-pool-fields'} <= set(operations):
        raise ValueError('Query metadata public operation missing')


def _validate_media_choice(row):
    if row['kind'] != 'enum_value':
        return
    from wwise_waapi.media_build_business_contracts import (MEDIA_POOL_TEXT_OPERATOR_TOKENS,
        MEDIA_POOL_NUMBER_OPERATOR_TOKENS, MEDIA_POOL_RETURN_ONLY_FIELDS)
    pointer, value = row['pointer'], row['value']
    if '/properties/operator/' in pointer and value not in set(MEDIA_POOL_TEXT_OPERATOR_TOKENS) | set(MEDIA_POOL_NUMBER_OPERATOR_TOKENS):
        raise ValueError('Query Media Pool operator lacks closed public correspondence')
    if '/properties/type/' in pointer and value not in {'field', 'audioDescription', 'audioSimilarity'}:
        raise ValueError('Query Media Pool filter type lacks closed public correspondence')
    if '/definitions/mediaPoolReturnOption/' in pointer and value not in {'Path', 'FileId', 'Db'} | {item['field'] for item in MEDIA_POOL_RETURN_ONLY_FIELDS.values()}:
        raise ValueError('Query Media Pool return choice lacks closed public correspondence')


def query_bindings(root, inventory):
    _validate_public_inputs()
    rows = inventory['native_coverage']['obligations']
    if digest([(row['id'], row['shape_sha256']) for row in rows]) != inventory['query_roster_sha256']:
        raise ValueError('Query mapping native choice roster differs')
    public = {row['id']: row for row in inventory['routes']}
    if {route['public_route'] for route in inventory['native_coverage']['routes']} != set(public) or len(inventory['native_coverage']['routes']) != 74:
        raise ValueError('Query mapping host/public route roster differs')
    grouped = defaultdict(list)
    for row in rows:
        grouped[row['route']].append(row)
    bindings = {}
    for route in inventory['native_coverage']['routes']:
        uri, version = route['uri'], route['version']
        paths = {section: _native_paths(grouped[route['id']], section) for section in ('argsSchema', 'optionsSchema', 'resultSchema')}
        name = uri.rsplit('.', 1)[1]
        group = 'object-query' if name == 'get' and '.object.' in uri else 'peaks' if '.audioSourcePeaks.' in uri else 'media-pool' if '.mediaPool.' in uri else 'metadata'
        for row in grouped[route['id']]:
            if '.mediaPool.' in uri:
                _validate_media_choice(row)
            section, pointer = row['pointer'].split('/')[1], row['pointer']
            native_paths = paths[section][row['id']]
            fields = {path[0] for path in native_paths if path and isinstance(path[0], str)}
            correspondence = (_query_correspondence(row, version, fields) if group == 'object-query' else
                _metadata_correspondence(row, name, fields) if group == 'metadata' else _media_correspondence(row, uri, fields))
            correspondence['native_paths'] = native_paths
            if row['kind'] != 'schema' and row['kind'] != 'reference':
                correspondence['native_choice'] = row['value']
            command = ['query-object'] if group == 'object-query' else ['metadata', {'getTypes': 'types', 'getPropertyAndReferenceNames': 'list', 'getPropertyInfo': 'detail', 'isPropertyEnabled': 'property-state'}[name]] if group == 'metadata' else ['metadata', 'media-pool-fields'] if name == 'getFields' else ['core-call', uri]
            construct = (GATEWAY + '#_compile_query_business_projection' if group == 'object-query' else LIB + 'metadata_discovery.py#browse_metadata_types' if name == 'getTypes' else GATEWAY + '#dispatch_command' if name == 'isPropertyEnabled' else LIB + 'metadata_discovery.py#browse_metadata' if group == 'metadata' else LIB + 'media_build_business.py#materialize_media_build_business_request' if name != 'getFields' else LIB + 'media_pool_field_discovery.py#browse_media_pool_fields')
            bindings[row['id']] = {'branch_id': row['id'], 'native_shape_sha256': row['shape_sha256'],
                'public_route': route['public_route'], 'public_route_sha256': digest(public[route['public_route']]),
                'input': {'gateway_argv': command, 'selector': pointer, 'correspondence': correspondence},
                'construction': {'source': construct, 'selector': pointer},
                'validation': {'source': LIB + 'builders/schema.py#' + ('validate_semantic_result' if section == 'resultSchema' else 'validate_semantic_payload'), 'selector': pointer},
                'verifier': {'source': GATEWAY + '#_finish_object_query_result' if group == 'object-query' else LIB + 'metadata_detail.py#detail_page' if group == 'metadata' else GATEWAY + '#dispatch_media_build_business_read', 'selector': pointer},
                'representative_mechanism': f'query195:{group}:{version}', 'evidence': {}}
    return bindings


def export_mapping(root, destination, *, inventory=None, anchors=None):
    """Emit bounded host/version partitions; never overwrite global documents.

    ``anchors`` contains existing selected bindings and ordinary-reader evidence,
    not generated PASS flags. Missing evidence intentionally leaves the batch
    incomplete. Original mappings/evidence are preserved by exact predecessors.
    """
    root, destination = Path(root), Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    inventory = query_component(root) if inventory is None else inventory
    bindings = query_bindings(root, inventory)
    rows = {row['id']: row for row in inventory['native_coverage']['obligations']}
    candidate = inventory['native_coverage']['candidate_sha256']
    anchors = anchors or {}
    if set(anchors) - set(bindings):
        raise ValueError('Query selected anchor is outside the exact family')
    for identity, anchor in anchors.items():
        if (not isinstance(anchor, dict)
                or set(anchor) != {'ordinary_test_run_attachment', 'relevant_sources', 'evidence'}
                or anchor['ordinary_test_run_attachment'] is not True
                or set(anchor['evidence']) != {'program'}):
            raise ValueError('Query anchor requires existing ordinary program evidence')
        bindings[identity].update(deepcopy(anchor))
    requirements = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {}, 'representative_mechanisms': {}}
    groups = defaultdict(dict)
    for identity, binding in bindings.items():
        groups[binding['representative_mechanism']][identity] = binding
        requirements['branches'][identity] = {'native_shape_sha256': rows[identity]['shape_sha256'],
            'categories': ['program'], 'reason': POLICY + ': accepted closed-wrapper code proof; native effects are separately retained and not manufactured by mapping',
            'representative_mechanism': binding['representative_mechanism']}
    for mechanism, members in groups.items():
        if len(set(members) & set(anchors)) > 1:
            raise ValueError('Query mechanism uses one selected shared program anchor')
        selected = sorted(set(members) & set(anchors)) or [min(members)]
        sources = {binding[key]['source'].split('#')[0] for binding in members.values()
            for key in ('construction', 'validation', 'verifier')}
        sources.update({name.split('#')[0] for name in QUERY_MECHANISMS.values()})
        sources.update({'tests/support/query_completion_mapping.py', BASE + 'source-roster.json',
            LIB + 'builders/metadata.py', LIB + 'metadata_detail.py', LIB + 'media_build_business.py', LIB + 'media_pool_field_discovery.py', LIB + 'builders/query.py', LIB + 'object_query_outputs.py', LIB + 'metadata_discovery.py', LIB + 'object_query_result_pages.py', LIB + 'media_pool_continuation.py', LIB + 'peak_read_continuation.py', LIB + 'media_build_business_contracts.py', POLICY})
        requirements['representative_mechanisms'][mechanism] = {
            'contract': 'waapi-skill.representative-branch-mechanism/v1', 'scope_kind': 'product',
            'candidate_sha256': candidate, 'reviewed_reason': 'Exact versioned Query wrapper mapping; shared program proof only, no per-leaf native effect claim.',
            'sources': {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sorted(sources)},
            'members': {identity: {'native_route': rows[identity]['route'],
                'native_shape_sha256': rows[identity]['shape_sha256'],
                'mapping_sha256': digest({k: v for k, v in binding.items() if k != 'evidence'})} for identity, binding in members.items()},
            'selected_proofs': {'program': selected}}
    def write(name, body):
        path = destination / name
        path.write_text(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n', encoding='utf-8')
        return {'artifact': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    # Partition by mechanism so each review's exact member set remains closed.
    descriptors = []
    entries = []
    requirements_sha256 = digest(requirements)
    for number, (mechanism, members) in enumerate(sorted(groups.items()), 1):
        for identity in set(members) & set(anchors):
            original = deepcopy(members[identity])
            record = {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': {identity: original}}
            binding_descriptor = write(f'selected-{number:02}.json', record)
            original_policy = {'contract': requirements['contract'],
                'branches': {identity: requirements['branches'][identity]}}
            policy_descriptor = write(f'selected-policy-{number:02}.json', original_policy)
            entries.append({'id': identity, 'bindings': binding_descriptor, 'origin': {
                'bindings': binding_descriptor, 'program': original['evidence']['program'],
                'requirements': policy_descriptor,
                'capture': write(f'selected-review-{number:02}.json', {'mechanism': mechanism,
                    'meaning': 'reviewed existing ordinary program proof; no per-leaf native effect'})}})
        proposed = deepcopy(members)
        predecessors = {}
        for identity, binding in proposed.items():
            predecessors[identity] = ({'binding_sha256': digest(members[identity]),
                'policy_sha256': digest(requirements['branches'][identity])} if identity in anchors else None)
            binding['evidence'] = {}
        attachment = {'contract': 'waapi-skill.branch-mapping-attachment/v1', 'scope_kind': 'product',
            'requirements_sha256': requirements_sha256, 'mechanisms': [mechanism],
            'bindings': proposed, 'predecessors': predecessors}
        descriptors.append(write(f'mapping-{number:02}.json', attachment))
    # Adjacent standard requirements parts use the existing ordinary loader.
    requirement_parts = []
    for version in sorted({identity.split('|')[0] for identity in rows}):
        selected_members = {identity: policy for identity, policy in requirements['branches'].items()
                            if identity.startswith(version + '|')}
        selected_mechanisms = {policy['representative_mechanism'] for policy in selected_members.values()}
        part = {'contract': requirements['contract'], 'branches': selected_members,
            'representative_mechanisms': {key: requirements['representative_mechanisms'][key]
                                        for key in sorted(selected_mechanisms)}}
        requirement_parts.append(write(f'requirements-{version}.json', part))
    write('requirements-index.json', {'contract': 'waapi-skill.branch-evidence-requirements-index/v1',
        'parts': [{'path': item['artifact'], 'sha256': item['sha256']} for item in requirement_parts],
        'document_sha256': requirements_sha256})
    index = {'contract': 'waapi-skill.branch-evidence-index/v1', 'base': '.', 'entries': entries, 'mapping_attachments': descriptors}
    write('evidence-index.json', index)
    summary = {'component': inventory['component'], 'public_routes': len(inventory['routes']),
        'native_routes': len(inventory['native_coverage']['routes']), 'native_members': len(rows),
        'mechanisms': {key: len(value) for key, value in sorted(groups.items())},
        'catalogs': inventory['native_coverage']['catalogs'], 'candidate_sha256': candidate,
        'mapping_is_not_execution_credit': True, 'native_effect_credit': False,
        'requirements_parts': requirement_parts, 'merged_requirements_sha256': requirements_sha256,
        'canonical_requirements_import_ready': False,
        'largest_mapping_bytes': max((destination / d['artifact']).stat().st_size for d in descriptors)}
    write('summary.json', summary)
    return {'index_path': destination / 'evidence-index.json', 'requirements': requirements,
        'requirements_path': destination / 'requirements-index.json', 'summary': summary, 'bindings': {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': bindings}}


def program_anchors(root, inventory, destination, review_path):
    """Bind an actual finalized ordinary run to finite reviewed wrapper anchors.

    The existing ordinary reader verifies the original run, collection, Git
    sources, unchanged candidate and exact current mapping before granting proof.
    This only copies original bytes and supplies the exact selected mapping.
    """
    from tests.maintenance.branch_audit_completion import binding_semantics
    from tests.semantic.support.codex_archive_paths import archive_relative_from_absolute
    root, destination, review_path = Path(root), Path(destination).resolve(), Path(review_path)
    review = json.loads(review_path.read_bytes())
    if set(review) != {'record', 'selected_tests'} or not review['selected_tests']:
        raise ValueError('Query program review requires one original ordinary record and selected tests')
    record = review['record']
    if (record.get('contract') != 'waapi-skill.ordinary-test-run-attachment/v1'
            or record.get('scope_kind') != 'product'
            or set(record.get('files', {})) != {'plan', 'result', 'summary', 'log', 'exit'}):
        raise ValueError('Query program review requires the original finalized ordinary run')
    destination.mkdir(parents=True, exist_ok=True)
    copied = {}
    for name, descriptor in record['files'].items():
        if set(descriptor) != {'artifact', 'sha256'}:
            raise ValueError('Query original program file descriptor differs')
        source = Path(descriptor['artifact'])
        raw = (source if source.is_absolute() else review_path.parent / source).read_bytes()
        if hashlib.sha256(raw).hexdigest() != descriptor['sha256']:
            raise ValueError('Query original program file seal differs')
        # The existing finalizer binds summary.original_receipt to the result
        # basename. Relocation preserves that name and all original bytes.
        path = destination / 'original' / source.name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(raw)
        copied[name] = {'artifact': archive_relative_from_absolute(path, destination).canonical, 'sha256': descriptor['sha256']}
    bindings = query_bindings(root, inventory)
    selected = {}
    for identity, binding in sorted(bindings.items()):
        selected.setdefault(binding['representative_mechanism'], identity)
    result = {}
    for number, identity in enumerate(selected.values(), 1):
        binding = bindings[identity]
        anchor = {'ordinary_test_run_attachment': True,
            'relevant_sources': sorted(record['review']['sources']), 'evidence': {}}
        binding.update(anchor)
        proof = deepcopy(record)
        proof.update(candidate_sha256=inventory['native_coverage']['candidate_sha256'], files=copied,
            mechanism={'branch_id': identity, 'native_route': identity.rsplit('|', 1)[0],
                'native_shape_sha256': binding['native_shape_sha256'],
                'binding_semantics_sha256': digest(binding_semantics(binding)),
                'selected_tests': review['selected_tests']})
        path = destination / f'program-anchor-{number:02}.json'
        path.write_text(json.dumps(proof, sort_keys=True, separators=(',', ':')) + '\n', encoding='utf-8')
        anchor['evidence'] = {'program': {'artifact': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}}
        result[identity] = anchor
    return result
