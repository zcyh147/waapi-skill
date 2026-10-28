"""Finite Topic correspondence through the existing mapping/evidence readers.

Mapping is not event delivery. The lightweight wrapper assessment is program-only;
original native observations remain separate and are never synthesized here.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from tests.maintenance.branch_coverage_audit import digest, schema_branches
from tests.maintenance.branch_audit_completion import candidate_identity
from tests.maintenance.branch_audit_mapping import debug_control_component

LIB = 'skills/waapi-skill/wwise_waapi/'
GATEWAY = 'skills/waapi-skill/scripts/gateway.py'
POLICY = 'docs/plans/full-waapi-coverage/AUTHORING_MODEL_TOPIC_CLOSEOUT.md'


def _path(pointer, *, schema, schema_pointer, legacy_paths):
    """Derive data addresses using the exact reflected legacy-property parser."""
    from wwise_waapi.schema_inventory import _is_legacy_implicit_property
    parts = pointer.split('/')[1:]
    result = []
    node = schema
    raw_path = schema_pointer
    index = 0
    while index < len(parts):
        token = parts[index]
        if token in ('properties', 'patternProperties') and index + 1 < len(parts):
            name = parts[index + 1].replace('~1', '/').replace('~0', '~')
            result.append('*' if token == 'patternProperties' else name)
            node = node.get(token, {}).get(name) if isinstance(node, dict) else None
            raw_path += '/' + token + '/' + parts[index + 1]
            index += 2
            continue
        if token == 'items':
            result.append(None)
        elif token == 'additionalProperties':
            result.append('*')
        elif isinstance(node, dict) and _is_legacy_implicit_property(
                node, token.replace('~1', '/').replace('~0', '~'),
                node_path=raw_path, allowed_paths=legacy_paths):
            result.append(token.replace('~1', '/').replace('~0', '~'))
        if isinstance(node, dict):
            node = node.get(token.replace('~1', '/').replace('~0', '~'))
        elif isinstance(node, list) and token.isdigit() and int(token) < len(node):
            node = node[int(token)]
        else:
            node = None
        raw_path += '/' + token
        index += 1
    return result


def topic_component(root):
    """Enumerate only Topics from all ten independently sealed native catalogs."""
    from wwise_waapi.native_catalog import load_native_catalog, NATIVE_HOSTS
    from wwise_waapi.schema_inventory import (DefinitionGraph, resolve_schema_reference,
        LEGACY_2021_SOUNDBANK_IMPLICIT_PROPERTY_PATHS)
    from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS
    root = Path(root)
    snapshot = json.loads((root / 'docs/branch-coverage-inventory.json').read_bytes())
    public = {row['id']: deepcopy(row) for row in snapshot['routes'] if '|topic|' in row['id']}
    owners = json.loads((root / 'docs/branch-coverage-ownership.json').read_bytes())['routes']
    catalogs, routes, rows, locations = {}, [], [], {}
    for version in SUPPORTED_WWISE_VERSION_KEYS:
        for host in NATIVE_HOSTS:
            catalog = load_native_catalog(version, host, root=root / 'skills/waapi-skill/resources/native-catalog')
            build = catalog['provenance']['build']
            catalogs[f'{version}|{host}|{build}'] = catalog['content_sha256']
            graph = DefinitionGraph(**{k: catalog['definitions'][k] for k in
                ('contract', 'version', 'wwise_build', 'source_file_names', 'documents', 'inventory_sha256')})
            for uri in catalog['topics']:
                if owners.get('topic|' + uri, {}).get('owner_issue') != 187:
                    raise ValueError('Topic ownership differs from the finite #187 roster')
                native = f'{version}|{host}|{build}|topic|{uri}'
                public_id = f'{version}|topic|{uri}'
                if public_id not in public:
                    raise ValueError('Topic native route has no public lane')
                routes.append({'id': native, 'version': version, 'host': host, 'build': build,
                    'kind': 'topic', 'uri': uri, 'native_schema_sha256': digest(catalog['schemas'][uri]),
                    'public_route': public_id})
                for section, schema in catalog['schemas'][uri].items():
                    if section in ('description', 'subscribe', 'publish', 'options', 'uri'):
                        continue
                    if section not in ('optionsSchema', 'publishSchema'):
                        raise ValueError('Unhandled Topic schema section: ' + section)
                    visited = set()
                    legacy = (LEGACY_2021_SOUNDBANK_IMPLICIT_PROPERTY_PATHS if version == '2021.1'
                              and uri == 'ak.wwise.core.soundbank.generated' else frozenset())
                    def visit(value, pointer, context, document, active, location):
                        for item in schema_branches(value, pointer):
                            identity = native + '|' + item['pointer']
                            logical = location + _path(item['pointer'][len(pointer):], schema=value,
                                schema_pointer=pointer, legacy_paths=legacy)
                            locations[identity] = logical
                            row = {'id': identity, 'route': native, 'pointer': item['pointer'],
                                'kind': item['kind'], 'shape_sha256': digest(item['value']),
                                'owner_issue': 187, 'parent_issue': 174, 'blocks_issue': 195, 'state': 'unresolved'}
                            if item['kind'] != 'schema':
                                row['value'] = item['value']
                            rows.append(row)
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
                                        doc, active | {key}, logical)
                    visit(schema, '/' + section, schema, '<schema>', set(), [])
    if {r['public_route'] for r in routes} != set(public) or len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Topic public/native roster differs or duplicate native branch')
    # Reuse the existing candidate-source closure rather than inventing an ID.
    source_inputs = debug_control_component(root)['sources']
    for name in ('tests/support/topic_completion_mapping.py',
                 'tests/maintenance/map_topic_completion.py', 'tests/unit/test_topic_completion_mapping.py', POLICY):
        source_inputs[name] = digest((root / name).read_text(encoding='utf-8'))
    result = {'component': 'topic-closed-wrappers-195-v1', 'routes': list(public.values()), 'sources': source_inputs,
        'topic_locations': locations, 'topic_roster_sha256': digest([(r['id'], r['shape_sha256']) for r in rows]),
        'native_coverage': {'catalogs': catalogs, 'routes': routes, 'obligations': rows}}
    result['native_coverage']['candidate_sha256'] = candidate_identity(root, result, catalogs, digest=digest)
    return result


def _validate_disclosed_channels(contract):
    """Check public channels, without requiring a predicate for each output.

    Existing business compilers own the declaration. Comparing their declared
    surface and private addresses prevents a removed public channel from being
    silently reclassified as output-only. It never supplies a missing channel.
    """
    from wwise_waapi.topic_business import (
        _business_fields, _business_empty_fields, _business_row_fields, _business_entry_fields,
    )
    from wwise_waapi.typed_topics import topic_options_contract, topic_match_contract
    options = topic_options_contract(contract.version, contract.topic)
    match = topic_match_contract(contract.version, contract.topic)
    expected = {
        'option_fields': _business_fields(options.fields, section='options'),
        'match_fields': _business_fields(match.fields, section='match'),
        'option_empty_fields': _business_empty_fields(options.fields, section='options'),
        'match_empty_fields': _business_empty_fields(match.fields, section='match'),
        'row_fields': _business_row_fields(match), 'entry_fields': _business_entry_fields(match),
    }
    def identity(field):
        result = {'disclosure': field.as_dict()}
        if hasattr(field, '_path'):
            result['native_path'] = field._path
        if hasattr(field, '_candidates'):
            result['candidates'] = [(item.path, item.shape, digest(item.variants)) for item in field._candidates]
        if hasattr(field, 'fields'):
            result['fields'] = [identity(item) for item in field.fields]
        if hasattr(field, 'object_fields'):
            result['object_fields'] = [identity(item) for item in field.object_fields]
            result['row_fields'] = [identity(item) for item in field.row_fields]
        for name in ('_variants', '_scalar_variants'):
            if hasattr(field, name):
                result[name] = digest(getattr(field, name))
        return result
    for name, fields in expected.items():
        if [identity(item) for item in fields] != [identity(item) for item in getattr(contract, name)]:
            raise ValueError('Topic closed public correspondence differs: '
                + contract.version + '|' + contract.topic + '|' + name)


def _public_addresses(contract):
    _validate_disclosed_channels(contract)
    from wwise_waapi.topic_business import topic_business_value_choices
    addresses = defaultdict(list)
    def add(section, path, item, *, accepted=(), channel=None, owner=()):
        item = {**item, 'native_path': list(path)}
        if accepted:
            item['accepted_value_kinds'] = list(accepted)
        if len(accepted) > 1:
            choices = topic_business_value_choices(contract, channel=channel, owner=owner)
            if len(choices) != len(accepted) or {choice._kind for choice in choices} != set(accepted):
                raise ValueError('Topic public choice disclosure is missing or changed: ' + '/'.join(owner))
            item['action'] += '-as'
            item['value_choices'] = [{'kind': choice._kind, 'meaning': choice.meaning, 'handle': choice.handle}
                                     for choice in choices]
        addresses[(section, tuple(path))].append(item)
    for section, fields, action, channel in (
        ('optionsSchema', contract.option_fields, '--topic-option', 'topic-option'),
        ('publishSchema', contract.match_fields, '--event-match', 'event-match')):
        for field in fields:
            for candidate in field._candidates:
                add(section, candidate.path, {'action': action, 'field': field.token},
                    accepted=field.accepted_value_kinds, channel=channel, owner=(field.token,))
    for row in contract.row_fields:
        for field in row.fields:
            add('publishSchema', (*row._path, *field._path),
                {'action': '--event-row', 'collection': row.token, 'index_depth': row.index_depth, 'field': field.token},
                accepted=field.accepted_value_kinds, channel='event-row', owner=(row.token, field.token))
        add('publishSchema', row._path[:-1], {'action': '--event-row-empty', 'collection': row.token,
            'index_depth': row.index_depth - 1})
    for entry in contract.entry_fields:
        path = (*entry._path, '*')
        add('publishSchema', path, {'action': '--event-entry', 'scope': entry.token,
            'index_depth': entry.index_depth, 'key_mode': 'exact_user_key_matching_native_schema'},
            accepted=entry.accepted_value_kinds, channel='event-entry', owner=(entry.token,))
        for fields, row_path, action, channel, open_members in (
            (entry.object_fields, path, '--event-entry-object', 'event-entry-object', entry._open_object_fields),
            (entry.row_fields, (*path, None), '--event-entry-row', 'event-entry-row', entry._open_row_fields)):
            for field in fields:
                add('publishSchema', (*row_path, *field._path), {'action': action, 'scope': entry.token,
                    'index_depth': entry.index_depth, 'field': field.token},
                    accepted=field.accepted_value_kinds, channel=channel, owner=(entry.token, field.token))
            if open_members:
                add('publishSchema', (*row_path, '*'), {'action': action, 'scope': entry.token,
                    'index_depth': entry.index_depth, 'field': '*', 'field_mode': 'exact_user_key'},
                    accepted=entry.accepted_value_kinds, channel=channel, owner=(entry.token, '*'))
        add('publishSchema', path, {'action': '--event-entry-empty', 'scope': entry.token,
            'index_depth': entry.index_depth, 'shapes': ['object', 'list']})
    for section, fields, action in (
        ('optionsSchema', contract.option_empty_fields, '--topic-option-empty'),
        ('publishSchema', contract.match_empty_fields, '--event-empty')):
        for field in fields:
            add(section, field._path, {'action': action, 'field': field.token, 'shape': field.shape})
    return {key: list({json.dumps(v, sort_keys=True): v for v in values}.values()) for key, values in addresses.items()}


def topic_bindings(root, inventory):
    """Bind exact native pointers to closed inputs and preserved event output."""
    from wwise_waapi.topic_business import topic_business_contract
    rows = inventory['native_coverage']['obligations']
    if inventory['topic_roster_sha256'] != digest([(r['id'], r['shape_sha256']) for r in rows]):
        raise ValueError('Topic mapping roster omits or changes a native field/choice')
    public = {row['id']: row for row in inventory['routes']}
    routes = {row['id']: row for row in inventory['native_coverage']['routes']}
    expected_routes = {row['route'] for row in rows}
    if set(routes) != expected_routes or {r['public_route'] for r in routes.values()} != set(public):
        raise ValueError('Topic mapping version/host/public route roster differs')
    contracts, addresses = {}, {}
    for route in routes.values():
        key = route['public_route']
        if key not in contracts:
            contracts[key] = topic_business_contract(route['version'], route['uri'])
            addresses[key] = _public_addresses(contracts[key])
    result = {}
    for row in rows:
        route, pointer = routes[row['route']], row['pointer']
        key = route['public_route']; section = pointer.split('/')[1]
        path = inventory['topic_locations'][row['id']]
        public_inputs = addresses[key].get((section, tuple(path)), [])
        # Scalar arrays are supplied by repeated closed facts, not a second
        # caller-authored item grammar. Their schema descendants retain the
        # exact field's choice/constraint identity.
        if not public_inputs:
            array_path = path[:-1] if path and path[-1] is None else path
            public_inputs = addresses[key].get((section, tuple(array_path)), [])
        if section == 'optionsSchema' and path and path[-1] != '*' and not public_inputs:
            raise ValueError('Topic option lacks closed public correspondence: ' + row['id'])
        if '.ui.signal.' in route['uri']:
            public_inputs = [{'action': '--signal-model', 'with': '--signal-widget',
                'native_path': entry['native_path'],
                'binding': 'active_owned_model_widget_configuration_host_build_session_project'}
                for entry in public_inputs]
        special = ('soundbank-2021-recursive' if route['version'] == '2021.1' and route['uri'].endswith('soundbank.generated')
            else 'notes-2025-compatibility' if route['version'] == '2025.1' and route['uri'].endswith('object.structureChanged')
            else 'owned-signal' if '.ui.signal.' in route['uri'] else 'closed-topic')
        mechanism = ':'.join(('topic195', special, section, route['version'], route['host']))
        correspondence = {'rule': 'closed_subscription_options' if section == 'optionsSchema' else 'validated_event_identity_projection',
            'native_path': path, 'public_inputs': public_inputs,
            'choice': {'kind': row['kind'], **({'value': row['value']} if 'value' in row else {})},
            'output': 'unchanged_native_event_keys_and_values' if section == 'publishSchema' else 'gateway_owned_native_options',
            'contract_sha256': contracts[key].contract_digest,
            'input_role': ('closed_disclosed_channel' if public_inputs else
                           'output_only_no_predicate_required' if section == 'publishSchema' else 'closed_schema_control')}
        if row['kind'] == 'reference':
            correspondence['reference'] = row['reference']
        if '/@definition/' in pointer:
            correspondence['address_rule'] = 'substitute_definition_at_each_exact_reference_site; native_path_is_first_reachable_site'
        result[row['id']] = {'branch_id': row['id'], 'native_shape_sha256': row['shape_sha256'],
            'public_route': key, 'public_route_sha256': digest(public[key]),
            'input': {'gateway_argv': ['topic-schema', route['uri']], 'selector': pointer,
                'continuations': ['wait-topic', 'stream-topic'], 'correspondence': correspondence},
            'construction': {'source': LIB + 'topic_business.py#materialize_topic_business_inputs', 'selector': pointer},
            'validation': {'source': (GATEWAY + '#validate_monitored_topic_event' if section == 'publishSchema'
                else LIB + 'topic_business.py#materialize_topic_business_inputs'), 'selector': pointer},
            'verifier': {'source': GATEWAY + '#dispatch_topic_stream', 'selector': pointer},
            'representative_mechanism': mechanism, 'evidence': {}}
    return result


def export_mapping(root, destination, *, inventory=None, anchors=None):
    """Emit bounded host/version partitions; never overwrite global documents.

    ``anchors`` contains existing selected bindings and ordinary-reader evidence,
    not generated PASS flags. Missing evidence intentionally leaves the batch
    incomplete. Original mappings/evidence are preserved by exact predecessors.
    """
    root, destination = Path(root), Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    inventory = topic_component(root) if inventory is None else inventory
    bindings = topic_bindings(root, inventory)
    rows = {row['id']: row for row in inventory['native_coverage']['obligations']}
    candidate = inventory['native_coverage']['candidate_sha256']
    anchors = anchors or {}
    if set(anchors) - set(bindings):
        raise ValueError('Topic selected anchor is outside the exact family')
    for identity, anchor in anchors.items():
        if (not isinstance(anchor, dict)
                or set(anchor) != {'ordinary_test_run_attachment', 'relevant_sources', 'evidence'}
                or anchor['ordinary_test_run_attachment'] is not True
                or set(anchor['evidence']) != {'program'}):
            raise ValueError('Topic anchor requires existing ordinary program evidence')
        bindings[identity].update(deepcopy(anchor))
    requirements = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {}, 'representative_mechanisms': {}}
    groups = defaultdict(dict)
    for identity, binding in bindings.items():
        groups[binding['representative_mechanism']][identity] = binding
        requirements['branches'][identity] = {'native_shape_sha256': rows[identity]['shape_sha256'],
            'categories': ['program'], 'reason': POLICY + ': accepted closed-wrapper code proof; native member delivery not observed',
            'representative_mechanism': binding['representative_mechanism']}
    for mechanism, members in groups.items():
        if len(set(members) & set(anchors)) > 1:
            raise ValueError('Topic mechanism uses one selected shared program anchor')
        selected = sorted(set(members) & set(anchors)) or [min(members)]
        sources = {binding[key]['source'].split('#')[0] for binding in members.values()
            for key in ('construction', 'validation', 'verifier')}
        sources.update({LIB + 'typed_topics.py', LIB + 'topic_compatibility.py', LIB + 'subscriptions.py', POLICY})
        requirements['representative_mechanisms'][mechanism] = {
            'contract': 'waapi-skill.representative-branch-mechanism/v1', 'scope_kind': 'product',
            'candidate_sha256': candidate, 'reviewed_reason': 'Exact versioned Topic wrapper mapping; shared program proof only, no sibling event-delivery claim.',
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
                    'meaning': 'reviewed existing ordinary program proof; no individual event delivery'})}})
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
    # Each file remains an existing standard requirements document. The caller
    # receives the merged in-memory document for the existing consumer; these
    # parts do not introduce a new canonical loader or publish global policy.
    requirement_parts = []
    for version in sorted({identity.split('|')[0] for identity in rows}):
        selected_members = {identity: policy for identity, policy in requirements['branches'].items()
                            if identity.startswith(version + '|')}
        selected_mechanisms = {policy['representative_mechanism'] for policy in selected_members.values()}
        part = {'contract': requirements['contract'], 'branches': selected_members,
            'representative_mechanisms': {key: requirements['representative_mechanisms'][key]
                                        for key in sorted(selected_mechanisms)}}
        requirement_parts.append(write(f'requirements-{version}.json', part))
    index = {'contract': 'waapi-skill.branch-evidence-index/v1', 'base': '.', 'entries': entries, 'mapping_attachments': descriptors}
    write('evidence-index.json', index)
    summary = {'component': inventory['component'], 'public_routes': len(inventory['routes']),
        'native_routes': len(inventory['native_coverage']['routes']), 'native_members': len(rows),
        'mechanisms': {key: len(value) for key, value in sorted(groups.items())},
        'catalogs': inventory['native_coverage']['catalogs'], 'candidate_sha256': candidate,
        'mapping_is_not_execution_credit': True, 'native_delivery_credit': False,
        'requirements_parts': requirement_parts, 'merged_requirements_sha256': requirements_sha256,
        'canonical_requirements_import_ready': False,
        'largest_mapping_bytes': max((destination / d['artifact']).stat().st_size for d in descriptors)}
    write('summary.json', summary)
    return {'index_path': destination / 'evidence-index.json', 'requirements': requirements,
        'summary': summary, 'bindings': {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': bindings}}


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
        raise ValueError('Topic program review requires one original ordinary record and selected tests')
    record = review['record']
    if (record.get('contract') != 'waapi-skill.ordinary-test-run-attachment/v1'
            or record.get('scope_kind') != 'product'
            or set(record.get('files', {})) != {'plan', 'result', 'summary', 'log', 'exit'}):
        raise ValueError('Topic program review requires the original finalized ordinary run')
    destination.mkdir(parents=True, exist_ok=True)
    copied = {}
    for name, descriptor in record['files'].items():
        if set(descriptor) != {'artifact', 'sha256'}:
            raise ValueError('Topic original program file descriptor differs')
        source = Path(descriptor['artifact'])
        raw = (source if source.is_absolute() else review_path.parent / source).read_bytes()
        if hashlib.sha256(raw).hexdigest() != descriptor['sha256']:
            raise ValueError('Topic original program file seal differs')
        # The existing finalizer binds summary.original_receipt to the result
        # basename. Relocation preserves that name and all original bytes.
        path = destination / 'original' / source.name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(raw)
        copied[name] = {'artifact': archive_relative_from_absolute(path, destination).canonical, 'sha256': descriptor['sha256']}
    bindings = topic_bindings(root, inventory)
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
