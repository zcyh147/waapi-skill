"""Bind native creation results before dependent scalar references.

The original declaration and Preview stay immutable. Each native result and
materialized request is retained; a dependent write never gets identity from
array order, a prospective path, or an inferred native collision suffix.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Mapping

from .canonical import canonical_sha256
from .operation_object import DEFAULT_MAX_NODES, flatten_set_result, flatten_create_result

KIND = 'owned-ordinary-result-stages/v1'
GET = 'ak.wwise.core.object.get'
SET = 'ak.wwise.core.object.set'
CREATE = 'ak.wwise.core.object.create'
SET_REFERENCE = 'ak.wwise.core.object.setReference'
FIELDS = ['id', 'name', 'type', 'path', 'parent', 'classId', 'notes']


def native_node(args, path, specs=()):
    """Resolve normalized List paths only through sealed typed occurrences."""
    import re
    node, prefix = args, '$'
    tokens = list(re.finditer(r'\.(objects|children|lists)\[(\d+)\]', path))
    index = 0
    while index < len(tokens):
        token = tokens[index]
        key, position = token.group(1), int(token.group(2))
        prefix += token.group(0)
        if key == 'lists':
            matches = {spec['collection'] for spec in specs if re.fullmatch(re.escape(prefix) + r'\.objects\[\d+\]', spec['request_path'])
                and spec.get('documented_list_element_class') == spec.get('class_id')}
            if len(matches) != 1 or index + 1 >= len(tokens) or tokens[index + 1].group(1) != 'objects':
                raise ValueError('Native List path lacks one source-certified occurrence collection')
            index += 1
            prefix += tokens[index].group(0)
            node = node['@' + matches.pop()][int(tokens[index].group(2))]
        else:
            node = node[key][position]
        index += 1
    return node


def certify_inner_occurrences(specs, version):
    """Select the existing owned-stage consumer for exact certified Inner Lists."""
    from .documented_list_fields import METADATA_INNER_OWNERS, resolve_class_list_evidence, owned_inner_identity
    owners = {node['request_path']: node for node in specs}
    counts = {}
    for member in specs:
        owner = owners.get(member.get('parent_request_path'))
        if (member.get('existing_target') or version != '2025.1' or member.get('collection') != 'Metadata'
                or member.get('class_id') != 5570560 or owner is None
                or owner.get('class_id') not in METADATA_INNER_OWNERS):
            continue
        source = resolve_class_list_evidence(version, owner['class_id'], 'Metadata')
        inner = owned_inner_identity(source, member['class_id'])
        if member.get('class_metadata') != {'classId': 5570560, 'name': 'MetadataSlot', 'type': 'Inner'}:
            raise ValueError('Owned Inner occurrence requires its exact live class/category')
        member['inner_identity'] = inner
        key = (member['parent_request_path'], member['collection'])
        if member.get('preexisting_id') is None:
            counts[key] = counts.get(key, 0) + 1
    return any(count > 1 for count in counts.values())


def list_profiles(specs, guards, version):
    """Seal named owned Lists using the existing producer's source proof."""
    from .documented_list_fields import resolve_class_list_evidence, owned_inner_identity
    profiles = []
    for owner in specs:
        for snapshot in owner.get('list_snapshots', []):
            name = snapshot['list']
            members = [node for node in specs if node.get('parent_request_path') == owner['request_path']
                and node.get('collection') == name]
            matches = []
            for guard in guards:
                binding = guard.get('binding', guard.get('evidence', {}))
                if (binding.get('declaration', {}).get('name') == name
                        and binding.get('scope', {}).get('class_id') == owner['class_id']
                        and (binding.get('planned_owner', {}).get('request_path') == owner['request_path']
                            or binding.get('scope', {}).get('scope_kind') == 'object'
                            and binding['scope'].get('scope_value') == owner.get('target_id'))):
                    matches.append(guard)
            if len(matches) != 1 or not members:
                raise ValueError('Staged List needs its exact producer-owned class/source and member roster')
            guard = matches[0]
            binding = guard.get('binding', guard.get('evidence'))
            source = resolve_class_list_evidence(version, owner['class_id'], name)
            if (any(binding.get(key) != source[key] for key in ('kind', 'version', 'catalog_sha256',
                    'source_member', 'source_sha256', 'declaration'))
                    or binding.get('reference_targets') is not None or source['declaration']['unresolved_element_types']):
                raise ValueError('Staged owned List source is not one complete matching named profile')
            before = (guard.get('before') or {}).get('members', []) if 'binding' in guard else guard['members']
            if len(before) + len(members) > DEFAULT_MAX_NODES:
                raise ValueError('Staged List prefix and new occurrences exceed the complete membership bound')
            names = [member['name'].casefold() for member in before]
            allowed = {row['class_id'] for row in source['declaration']['element_classes']}
            for member in members:
                inner = owned_inner_identity(source, member['class_id'])
                if inner is not None:
                    metadata = member.get('class_metadata', {})
                    if metadata != {'classId': inner['element_class_id'], 'name': inner['class_name'], 'type': 'Inner'}:
                        raise ValueError('Owned Inner occurrence requires its exact live class/category')
                    member['inner_identity'] = inner
                if (not member.get('requested_name') or member.get('existing_target') or member.get('preexisting_id')
                        or member.get('documented_list_element_class') != member.get('class_id')
                        or member['class_id'] not in allowed
                        or member.get('on_name_conflict') not in ({'fail', 'rename', 'merge', 'replace'} if inner else {'fail', 'rename'})
                        or member['requested_name'].casefold() in names):
                    raise ValueError('Staged named owned List requires distinct fresh source-certified members')
                names.append(member['requested_name'].casefold())
            if (owner.get('list_mode', 'append') != 'append' and before
                    and not all(member.get('inner_identity') for member in members)):
                raise ValueError('Staged List replacement/removal needs its separate outcome contract')
            if [row['id'].upper() for row in before] != [row['id'].upper() for row in snapshot['rows']]:
                raise ValueError('Staged List prefix differs from its complete producer snapshot')
            profiles.append({'owner': owner['request_path'], 'name': name, 'source': source,
                'before': deepcopy(before), 'mode': owner.get('list_mode', 'append'),
                'members': [node['request_path'] for node in members]})
    return profiles


def replacement_scopes(specs, snapshots, path_snapshots):
    """Associate existing authorized replacement snapshots with one root stage."""
    from .operation_registry import _same_identity, _parent_value
    by_path = {node['request_path']: node for node in specs}
    scopes = []
    for snapshot in snapshots:
        sources = [(view, row) for view in path_snapshots for row in view['rows']
            if _same_identity(row.get('id'), snapshot['root_id'])]
        if len(sources) != 1:
            raise ValueError('Replacement stage requires one exact original collision image')
        view, before = sources[0]
        matches = [node for node in specs if node.get('on_name_conflict') == 'replace'
            and node.get('collection') in {None, 'children'} and node['requested_name'] == before['name']
            and _same_identity(_parent_value(before.get('parent')),
                by_path.get(node.get('parent_request_path'), {}).get('target_id'))]
        if len(matches) != 1:
            raise ValueError('Replacement snapshot is not one declared root under its sealed parent GUID')
        scopes.append({'root': matches[0]['request_path'], 'root_id': snapshot['root_id'],
            'before': deepcopy(before), 'fields': list(view['fields']), 'platform': view.get('platform'), 'rows': deepcopy(snapshot['rows'])})
    if sum(len(scope['rows']) for scope in scopes) > DEFAULT_MAX_NODES:
        raise ValueError('Replacement stage forest exceeds its existing complete roster bound')
    return scopes


def active_replaced_ids(plan, identities):
    return {row['id'].upper() for scope in plan.get('replacements', []) if scope['root'] in identities
        for row in scope['rows']}


def preservation_reads(records):
    return [item for row in records for item in ([row, row['membership']] if 'membership' in row else [row])]


def fields_for(spec):
    return [*FIELDS, 'owner'] if spec.get('collection') not in {None, 'children'} else FIELDS


def observe_lists(prepared, identities, *, read):
    """Prove exact ordered partial membership, typed ownership and retained prefix."""
    from .documented_list_fields import observe_planned_list
    from .constructor_inputs import observe as observe_constructor_inputs
    observe_constructor_inputs(prepared['verification_plan']['nodes'], identities, read=read)
    for profile in prepared['pre_state']['owned_result_stages'].get('lists', []):
        owner = identities.get(profile['owner'])
        if owner is None:
            retained = next((node for node in prepared['verification_plan']['nodes']
                if node['request_path'] == profile['owner'] and (node.get('existing_target') or node.get('preexisting_id'))), None)
            owner = retained['pre_state'] if retained is not None else None
        if owner is None:
            continue
        actual = observe_planned_list(profile['source'], owner['id'], read=read)
        created = [identities[path] for path in profile['members'] if path in identities]
        prefix = [] if profile.get('mode') == 'replaceAll' and created else profile['before']
        members = actual['members']
        if profile.get('mode') == 'replaceAll' and created and profile['before']:
            removed = read(GET, {'from': {'id': [row['id'] for row in profile['before']]}}, {'return': ['id']})
            if not isinstance(removed, Mapping) or removed.get('return') != []:
                raise ValueError('Replaced Inner member GUIDs remain present; later creation stopped')
        if ([row['id'].upper() for row in members] != [row['id'].upper() for row in [*prefix, *created]]
                or members[:len(prefix)] != prefix
                or any(any(row.get(key) != expected.get(key) or (key in row) != (key in expected)
                    for key in expected) for row, expected in zip(members[len(prefix):], created, strict=True))):
            raise ValueError('Owned List changed its exact ordered prefix, members, class or ownership')


def prepare(uri, args, options, specs, context, version, *, force=False, root_parent=None, parent_children=(), list_guards=()):
    if not force and (not context or not (context.get('renames') or context.get('duplicate_sibling_groups'))):
        return None
    if force and not any(not node.get('existing_target') for node in specs):
        return None
    if uri not in {SET, CREATE} or uri == SET and version == '2021.1':
        raise ValueError('Owned ordinary creation requires its pinned native constructor')
    profiles = list_profiles(specs, list_guards, version)
    list_paths = {path for profile in profiles for path in profile['members']}
    owner_paths = {profile['owner'] for profile in profiles}
    if profiles and uri != SET:
        raise ValueError('Named owned List staging currently requires the pinned SET constructor')
    if (not specs or len(specs) > DEFAULT_MAX_NODES or any(
            (node.get('collection') not in {None, 'children'} and node['request_path'] not in list_paths)
            or (node.get('preexisting_id') is not None
                and not (node['request_path'] in owner_paths and node.get('on_name_conflict') == 'merge'))
            or ((node.get('list_request_paths') or node.get('list_snapshots')) and node['request_path'] not in owner_paths)
            or node.get('import_requested')
            or node.get('requested_language') or node.get('graph_plugin_native') or node.get('rtpc_binding')
            or any('array' in field or 'curve' in field for field in node.get('references', []))
            for node in specs)):
        raise ValueError('Native-name staging needs the complete ordinary new-child graph; richer alternatives remain #178/#192 obligations')
    deferred = [{'source': node['request_path'], 'field': field['name'], 'target': field['target_request_path'],
                 'platform': node.get('platform', args.get('platform'))}
        for node in specs for field in node.get('references', []) if 'target_request_path' in field]
    # Required constructor references cannot be repaired after creation. This
    # stage seam only substitutes owned parents, not reference dependencies.
    if any(field['field'] in node.get('constructor_inputs', {}).get('required_references', [])
            for field in deferred for node in specs if node['request_path'] == field['source']):
        raise ValueError('Mandatory constructor reference needs a previously verified target; planned-target staging remains assigned to #178/#179/#192')
    if len(deferred) > DEFAULT_MAX_NODES:
        raise ValueError('Native-name staging requires bounded ordinary result-reference dependencies')
    by_path = {node['request_path']: node for node in specs}
    for node in specs:
        if node.get('existing_target') and (node.get('requested_name') != node.get('original_name')
                or node.get('notes_supplied') or node.get('properties')
                or any('target_request_path' not in ref for ref in node.get('references', []))):
            raise ValueError('Existing field edits plus native-name creation need a separate declared child; this stage retains existing roots')
        children = [child for child in specs if child.get('parent_request_path') == node['request_path']]
        if not node.get('existing_target') and node.get('parent_request_path') not in by_path and not (uri == CREATE and node['request_path'] == '$'):
            raise ValueError('Every staged new occurrence needs its declared parent association')
    creation = deepcopy(args)
    for field in deferred:
        del native_node(creation, field['source'], specs)['@' + field['field']]
    def prune(node, path):
        children = [child for child in specs if child.get('parent_request_path') == path]
        for collection in dict.fromkeys(child.get('collection') or 'children' for child in children):
            group = [child for child in children if (child.get('collection') or 'children') == collection]
            key = collection if collection == 'children' else '@' + collection
            if any(child['request_path'] not in paths for child in group):
                node.pop(key, None)
            else:
                for child, raw in zip(group, node.get(key, []), strict=True):
                    prune(raw, child['request_path'])
    stages = []
    if uri == SET and creation_stage_count(specs) > 1:
        started_lists = set()
        for root, paths in creation_chunks(specs):
            parent = by_path[root['parent_request_path']]
            retained = parent
            while not retained.get('existing_target'):
                retained = by_path[retained['parent_request_path']]
            inherited = native_node(creation, retained['request_path'], specs)
            parent_args = {key: deepcopy(inherited[key]) for key in ('platform', 'onNameConflict', 'listMode') if key in inherited}
            if parent.get('existing_target'):
                parent_args['object'] = parent['target_id']
            else:
                native_parent = native_node(creation, parent['request_path'], specs)
                if 'platform' in native_parent:
                    parent_args['platform'] = native_parent['platform']
            list_key = (parent['request_path'], root.get('collection'))
            if root['request_path'] in list_paths:
                # The first call applies the declared replacement.
                # Later fragments append to its proven owned partial roster;
                # repeating replaceAll would delete earlier created members.
                if list_key in started_lists and parent_args.get('listMode', creation.get('listMode', 'append')) == 'replaceAll':
                    parent_args['listMode'] = 'append'
                started_lists.add(list_key)
            chunk = deepcopy(native_node(creation, root['request_path'], specs))
            prune(chunk, root['request_path'])
            stages.append({'root': root['request_path'], 'parent': parent['request_path'], 'node_paths': paths,
                **({'owned_parent': True} if not parent.get('existing_target') else {}),
                'args': {**deepcopy(creation), 'objects': [{**parent_args, ('children' if root.get('collection') in {None, 'children'} else '@' + root['collection']): [chunk]}]}})
    if uri == CREATE and creation_stage_count(specs) > 1:
        for root, paths in creation_chunks(specs):
            chunk = deepcopy(native_node(creation, root['request_path'], specs))
            prune(chunk, root['request_path'])
            parent_path = root.get('parent_request_path')
            controls = {key: deepcopy(creation[key]) for key in ('onNameConflict', 'autoAddToSourceControl', 'platform') if key in creation}
            if parent_path is None:
                controls['parent'] = creation['parent']
            stages.append({'constructor': CREATE, 'root': root['request_path'], 'parent': parent_path,
                'node_paths': paths, **({'owned_parent': True} if parent_path is not None else {}),
                'args': {**chunk, **controls}})
    return {'kind': KIND, 'version': version, 'uri': uri, 'creation_args': creation,
            'options': deepcopy(options), 'deferred': deferred,
            **({'lists': profiles} if profiles else {}),
            **({'creation_stages': stages, 'pre_creation_roster_check': True} if stages else {}),
            'prospective_paths': prospective_paths(specs, root_parent=root_parent),
            **({'parent_before': dict(root_parent), 'parent_children': list(parent_children), 'parent_id': args['parent']} if uri == CREATE else {})}


def creation_chunks(specs):
    """Cut ambiguous sibling frontiers within each typed collection."""
    children = {}
    for node in specs:
        children.setdefault(node.get('parent_request_path'), []).append(node)
    roots = []
    def visit(root):
        paths = []
        deferred = []
        def collect(node):
            paths.append(node['request_path'])
            descendants = children.get(node['request_path'], [])
            for collection in dict.fromkeys(child.get('collection') for child in descendants):
                group = [child for child in descendants if child.get('collection') == collection]
                if (len({child['requested_name'].casefold() for child in group}) != len(group)
                        or len(group) > 1 and any(child.get('inner_identity') for child in group)):
                    deferred.extend(group)
                else:
                    for child in group:
                        collect(child)
        collect(root)
        roots.append((root, paths))
        for child in deferred:
            visit(child)
    for parent in specs:
        if parent.get('existing_target'):
            for root in children.get(parent['request_path'], []):
                visit(root)
    if not any(node.get('existing_target') for node in specs):
        for root in children.get(None, []):
            visit(root)
    return roots


def creation_stage_count(specs):
    return max(1, len(creation_chunks(specs)))


def materialize_creation_args(stage, identities):
    args = deepcopy(stage['args'])
    if stage.get('owned_parent'):
        parent = identities.get(stage['parent'])
        if parent is None:
            raise ValueError('Creation stage lacks its earlier owned parent association')
        if stage.get('constructor') == CREATE:
            args['parent'] = parent['id']
        else:
            args['objects'][0]['object'] = parent['id']
    return args


def prospective_paths(specs, *, root_parent=None):
    """Business overlap scope only; these paths never certify created identity."""
    paths = {node['request_path']: node['pre_state']['path'] for node in specs if node.get('existing_target')}
    if root_parent is not None:
        paths['$'] = root_parent['path'] + '\\' + specs[0]['requested_name']
    pending = {node['request_path']: node for node in specs if not node.get('existing_target') and node['request_path'] not in paths}
    while pending:
        ready = [path for path, node in pending.items() if node.get('parent_request_path') in paths]
        if not ready:
            raise ValueError('Owned creation overlap scope lacks connected declared parents')
        for path in ready:
            node = pending.pop(path)
            parent_path = paths[node['parent_request_path']]
            paths[path] = (None if node.get('inner_identity') or parent_path is None
                else parent_path + '\\' + node['requested_name'])
    return paths


def bind(prepared, result, *, read):
    """Prove every actual returned occurrence and complete direct membership."""
    from .operation_registry import _same_identity, _object_type_matches
    specs = prepared['verification_plan']['nodes']
    plan = prepared['pre_state']['owned_result_stages']
    by_path = {node['request_path']: node for node in specs}
    returned = flatten_create_result(result) if plan['uri'] == CREATE else flatten_set_result(result, allowed_lists=[row['name'] for row in plan.get('lists', [])])
    returned_children, bound, seen = {}, {}, set()
    for node in returned:
        if node.parent_request_path is not None:
            returned_children.setdefault(node.parent_request_path, []).append(node)
    def bind_occurrence(node, spec):
        path, identity = spec['request_path'], node.object.upper()
        if path in bound or identity in seen:
            raise ValueError('Native result contains a duplicate occurrence or GUID')
        bound[path] = node
        seen.add(identity)
        children = [child for child in specs if child.get('parent_request_path') == path]
        actual = returned_children.get(node.request_path, [])
        if len(actual) != len(children):
            raise ValueError('Native child association omitted or added a declared occurrence')
        for child in actual:
            # A sole child below an existing exact GUID is the owned creation
            # occurrence. Its native suffix is never an identity expression.
            group = [candidate for candidate in children if candidate.get('collection') == child.collection]
            from .documented_list_fields import inner_result_candidate
            sealed = [candidate for candidate in group if candidate.get('preexisting_id')
                and _same_identity(candidate['preexisting_id'], child.object)]
            matches = sealed or [candidate for candidate in group
                if inner_result_candidate(candidate, child.object, child.name) is True
                or not candidate.get('inner_identity') and (spec.get('existing_target') and len(group) == 1
                    or candidate['requested_name'] == child.name)]
            if len(matches) != 1:
                raise ValueError('Native result cannot uniquely associate this child declaration')
            bind_occurrence(child, matches[0])
    for node in returned:
        if node.parent_request_path is None:
            matches = ([by_path[plan.get('stage_root', '$')]] if plan['uri'] == CREATE else [spec for spec in specs if spec.get('existing_target') and _same_identity(spec.get('target_id'), node.object)])
            if len(matches) != 1:
                raise ValueError('Native parent association is not one sealed exact GUID')
            bind_occurrence(node, matches[0])
    if any(not spec.get('existing_target') and path not in bound for path, spec in by_path.items()):
        raise ValueError('Native result omitted a newly declared occurrence')
    identities, records = {}, []
    def retained(uri, args, options):
        payload = read(uri, args, options)
        records.append({'uri': uri, 'args': args, 'options': options, 'result': payload})
        return payload
    def observe(args, fields=FIELDS):
        payload = retained(GET, args, {'return': fields})
        rows = payload.get('return') if isinstance(payload, Mapping) else None
        if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
            raise ValueError('Owned result observation requires a complete bounded row set')
        return rows
    all_before = {str(row['id']).upper() for node in specs for row in node.get('preexisting_children', [])}
    all_before.update(str(row['id']).upper() for profile in plan.get('lists', []) for row in profile['before'])
    all_before.update(str(node['target_id']).upper() for node in specs if node.get('existing_target'))
    all_before.update(row['id'].upper() for scope in plan.get('replacements', []) for row in scope['rows'])
    if plan['uri'] == CREATE:
        all_before.update(str(row['id']).upper() for row in plan['parent_children'])
        all_before.add(plan['parent_id'].upper())
    for path, spec in by_path.items():
        returned = bound.get(path)
        object_id = spec.get('target_id') if spec.get('existing_target') else returned.object if returned else None
        rows = observe({'from': {'id': [object_id]}}, fields_for(spec))
        if len(rows) != 1 or not _same_identity(rows[0].get('id'), object_id):
            raise ValueError('Actual returned GUID must resolve exactly once')
        row = rows[0]
        if not spec.get('existing_target'):
            inner = spec.get('inner_identity')
            if inner is not None:
                from .documented_list_fields import owned_inner_identity
                sources = [profile['source'] for profile in plan.get('lists', []) if path in profile['members']]
                if (len(sources) != 1 or inner != owned_inner_identity(sources[0], spec['class_id'])
                        or row.get('type') != inner['native_type'] or row.get('name') != inner['native_name']):
                    raise ValueError('Inner occurrence class/collection/name/type profile is not independently proved')
            retained_merge = spec.get('preexisting_id')
            if (retained_merge is not None and not _same_identity(object_id, retained_merge)):
                raise ValueError('Merged occurrence did not retain its sealed GUID')
            if ((not retained_merge and str(object_id).upper() in all_before) or not returned or row.get('name') != returned.name
                    or type(row.get('classId')) is not int or row['classId'] != spec['class_id']
                    or not _object_type_matches(row.get('type'), spec, actual_class_id=row['classId'])):
                raise ValueError('Returned created GUID/name/class differs from its live occurrence')
        identities[path] = dict(row)
    if len({row['id'].upper() for row in identities.values()}) != len(identities):
        raise ValueError('Owned occurrence identities are not a GUID bijection')
    for path, spec in by_path.items():
        row = identities[path]
        parent_path = spec.get('parent_request_path')
        if not spec.get('existing_target'):
            parent = identities.get(parent_path)
            if parent is None:
                parent_id = prepared['verification_plan'].get('parent_id')
                parents = observe({'from': {'id': [parent_id]}})
                if len(parents) != 1 or not _same_identity(parents[0].get('id'), parent_id):
                    raise ValueError('Created root parent lacks its actual GUID observation')
                parent = parents[0]
            owned = spec.get('collection') not in {None, 'children'}
            edge = row.get('owner' if owned else 'parent')
            if (not _same_identity(edge.get('id') if isinstance(edge, Mapping) else edge, parent['id'])
                    or not owned and row.get('path') != parent['path'] + '\\' + row['name']):
                raise ValueError('Actual created occurrence parent/path does not match declared topology')
        children = [identities[child['request_path']]['id'].upper() for child in specs if child.get('parent_request_path') == path
            and child.get('collection') in {None, 'children'}]
        expected = {str(child['id']).upper() for child in spec.get('preexisting_children', [])} | set(children)
        rows = observe({'from': {'id': [row['id']]}, 'transform': [{'select': ['children']}]})
        actual = [str(child.get('id')).upper() for child in rows]
        if len(actual) != len(set(actual)) or set(actual) != expected:
            raise ValueError('Actual parent membership differs from complete sealed and returned GUID roster')
    observe_lists(prepared, identities, read=retained)
    observe_reference_metadata(prepared, identities, read=retained)
    return identities, records


def observe_reference_metadata(prepared, identities, *, read):
    from .operation_registry import _read_property_info, _same_identity
    plan = prepared['pre_state']['owned_result_stages']
    by_path = {node['request_path']: node for node in prepared['verification_plan']['nodes']}
    context = prepared['pre_state'].get('planned_reference_context') or {'metadata': []}
    if plan.get('creation_stages') and plan['deferred']:
        # Earlier roots may have been created before other owned stages. A
        # dependent reference must still consume their exact actual identity.
        paths = list(dict.fromkeys(path for field in plan['deferred'] for path in (field['source'], field['target'])))
        for path in paths:
            payload = read(GET, {'from': {'id': [identities[path]['id']]}}, {'return': fields_for(by_path[path])})
            if not isinstance(payload, Mapping) or payload.get('return') != [identities[path]]:
                raise ValueError('Owned reference source/target drifted after its actual creation stage')
    for field in plan['deferred']:
        source = by_path[field['source']]
        metadata = [row['metadata'] for row in context['metadata'] if row['name'] == field['field']
            and (row.get('class_id') == source['class_id'] or isinstance(row.get('object_id'), str) and _same_identity(row['object_id'], source.get('target_id')))]
        actual = _read_property_info(read, object_id=identities[field['source']]['id'], name=field['field'])
        if not metadata or any(actual.as_dict() != row for row in metadata):
            raise ValueError('Actual created receiver field metadata differs from its sealed class/field authority')


def split_stage_prepared(prepared, stage, identities):
    """Materialize one sealed root against its proven parent and earlier roster."""
    nodes = prepared['verification_plan']['nodes']
    if stage.get('constructor') == CREATE:
        plan = prepared['pre_state']['owned_result_stages']
        parent = identities[stage['parent']] if stage.get('owned_parent') else plan['parent_before']
        previous = [row for row in identities.values()
            if str(row.get('parent', {}).get('id') if isinstance(row.get('parent'), Mapping) else row.get('parent')).upper() == parent['id'].upper()]
        children = ([] if stage.get('owned_parent') else plan['parent_children']) + previous
        return {**prepared, 'verification_plan': {**prepared['verification_plan'], 'parent_id': parent['id'],
                'nodes': [node for node in nodes if node['request_path'] in stage['node_paths']]},
            'pre_state': {**prepared['pre_state'], 'owned_result_stages': {**plan, 'deferred': [],
                'stage_root': stage['root'], 'parent_id': parent['id'], 'parent_children': children}}}
    parent = deepcopy(next(node for node in nodes if node['request_path'] == stage['parent']))
    if stage.get('owned_parent'):
        actual = identities[stage['parent']]
        parent.update(existing_target=True, target_id=actual['id'], pre_state=actual,
            original_name=actual['name'], requested_name=actual['name'],
            preexisting_children=parent.get('preexisting_children', []) if (parent.get('preexisting_id') or '').upper() == actual['id'].upper() else [])
    children = [row for path, row in identities.items() if path != stage['parent']
        and str(row.get('parent', {}).get('id') if isinstance(row.get('parent'), Mapping) else row.get('parent')).upper() == parent['target_id'].upper()]
    replacements = prepared['pre_state']['owned_result_stages'].get('replacements', [])
    removed = {row['id'].upper() for scope in replacements if scope['root'] == stage['root'] for row in scope['rows']}
    parent['preexisting_children'] = [child for child in [*parent.get('preexisting_children', []), *children]
        if child['id'].upper() not in removed]
    scoped = [parent, *(node for node in nodes if node['request_path'] in stage['node_paths'])]
    stage_plan = {**prepared['pre_state']['owned_result_stages'], 'deferred': []}
    scoped_paths = {node['request_path'] for node in scoped}
    if stage_plan.get('lists'):
        profiles = []
        for profile in stage_plan['lists']:
            if profile['owner'] not in scoped_paths:
                continue
            prior = [identities[path] for path in profile['members'] if path in identities]
            continued_replacement = profile.get('mode') == 'replaceAll' and bool(prior)
            profiles.append({**profile,
                'before': ([] if continued_replacement else profile['before']) + prior,
                'mode': 'append' if continued_replacement else profile.get('mode', 'append'),
                'members': [path for path in profile['members'] if path in stage['node_paths']]})
        stage_plan['lists'] = profiles
    return {**prepared, 'verification_plan': {**prepared['verification_plan'], 'nodes': scoped},
        'pre_state': {**prepared['pre_state'], 'owned_result_stages': stage_plan}}


def observe_owned_roster(prepared, identities, *, read):
    """Recheck every cumulative new identity and its complete direct membership."""
    nodes = prepared['verification_plan']['nodes']
    if len(nodes) > DEFAULT_MAX_NODES or len(identities) > DEFAULT_MAX_NODES:
        raise ValueError('Owned creation roster exceeds its sealed node bound')
    for node in nodes:
        path = node['request_path']
        if node.get('existing_target') or path not in identities:
            continue
        expected = identities[path]
        actual = read(GET, {'from': {'id': [expected['id']]}}, {'return': fields_for(node)})
        if not isinstance(actual, Mapping) or actual.get('return') != [expected]:
            raise ValueError('An earlier owned created identity changed between creation stages')
        children = {row['id'].upper() for row in node.get('preexisting_children', [])}
        children.update(identities[child['request_path']]['id'].upper() for child in nodes
            if child.get('parent_request_path') == path and child['request_path'] in identities
            and child.get('collection') in {None, 'children'})
        payload = read(GET, {'from': {'id': [expected['id']]}, 'transform': [{'select': ['children']}]}, {'return': ['id']})
        rows = payload.get('return') if isinstance(payload, Mapping) else None
        if (not isinstance(rows, list) or any(not isinstance(row, Mapping) or not isinstance(row.get('id'), str) for row in rows)
                or len(rows) != len(children) or {row['id'].upper() for row in rows} != children):
            raise ValueError('An earlier owned created subtree changed its complete child membership')

    observe_lists(prepared, identities, read=read)


def bind_split_stage(prepared, stage, result, identities, *, read, context, binding=None):
    binding = binding if binding is not None else {'readbacks': [], 'preservation': []}
    def observed_read(uri, args, options):
        payload = read(uri, args, options)
        binding['readbacks'].append({'uri': uri, 'args': args, 'options': options, 'result': payload})
        return payload
    scoped = split_stage_prepared(prepared, stage, identities)
    bound, _ = bind(scoped, result, read=observed_read)
    old_ids = {row['id'].upper() for row in identities.values()}
    if any(bound[path]['id'].upper() in old_ids for path in stage['node_paths']):
        raise ValueError('A later creation stage reused an earlier owned GUID')
    if any(bound[path] != row for path, row in identities.items() if path in bound):
        raise ValueError('An earlier owned parent identity changed during a later creation stage')
    actual = {**identities, **bound}
    if identities:
        observe_owned_roster(prepared, actual, read=observed_read)
    preserved = observe_preservation(prepared, actual, read=read, context=context)
    binding['preservation'] = preserved
    if not all(row['passed'] for row in preserved):
        raise ValueError('A creation stage changed its sealed retained scope; remaining writes stopped')
    return actual, binding['readbacks'], preserved


def observe_before_creation(prepared, identities, *, read, context, binding):
    if not identities:
        return
    def observed(uri, args, options):
        result = read(uri, args, options)
        binding['before_readbacks'].append({'uri': uri, 'args': args, 'options': options, 'result': result})
        return result
    observe_owned_roster(prepared, identities, read=observed)
    binding['before_preservation'] = observe_preservation(prepared, identities, read=read, context=context)
    if not all(row['passed'] for row in binding['before_preservation']):
        raise ValueError('Earlier creation changed its sealed preservation scope; later write stopped')


def reference_args(plan, identities):
    rows = []
    for field in plan['deferred']:
        source, target = identities[field['source']], identities[field['target']]
        row = next((row for row in rows if row['object'] == source['id'] and row.get('platform') == field['platform']), None)
        if row is None:
            row = {'object': source['id'], **({'platform': field['platform']} if field['platform'] is not None else {})}
            rows.append(row)
        owned_list_paths = {path for profile in plan.get('lists', []) for path in profile['members']}
        row['@' + field['field']] = target['id'] if field['target'] in owned_list_paths else target['path']
    return {'objects': rows}


def reference_calls(plan, identities):
    if plan['uri'] == SET:
        return [{'uri': SET, 'args': reference_args(plan, identities), 'options': plan['options']}] if plan['deferred'] else []
    return [{'uri': SET_REFERENCE, 'args': {'object': identities[field['source']]['id'], 'reference': field['field'],
        'value': identities[field['target']]['id'], **({'platform': field['platform']} if field['platform'] is not None else {})},
        'options': {}} for field in plan['deferred']]


def execute(prepared, *, write, read, context=None):
    """Execute the sealed stage pair once, retaining uncertainty as evidence."""
    from .builders.schema import validate_semantic_result
    plan = prepared['pre_state']['owned_result_stages']
    if plan.get('creation_stages'):
        return execute_split(prepared, write=write, read=read, context=context)
    records = []
    first = write(plan['uri'], plan['creation_args'], plan['options'])
    records.append({'uri': plan['uri'], 'args': plan['creation_args'], 'options': plan['options'], 'dispatch_result': first})
    if first.get('ok') is not True:
        return {**first, 'error_code': 'OWNED_RESULT_STAGE_INDETERMINATE',
            'owned_result_execution': {'kind': KIND, 'plan_sha256': canonical_sha256(plan), 'stages': records, 'automatic_retry': False}}
    try:
        validate_semantic_result(plan['uri'], first.get('result'), version=plan['version'])
        identities, observations = bind(prepared, first['result'], read=read)
        preservation = observe_preservation(prepared, identities, read=read, context=context)
        if not all(row['passed'] for row in preservation):
            raise ValueError('Creation changed its sealed retained parent/collision scope; dependent write stopped')
        for call in reference_calls(plan, identities):
            second = write(call['uri'], call['args'], call['options'])
            records.append({**call, 'dispatch_result': second})
            if second.get('ok') is not True:
                raise ValueError('Dependent reference stage was not acknowledged; do not replay')
            validate_semantic_result(call['uri'], second.get('result'), version=plan['version'])
        return {**first, 'owned_result_execution': {'kind': KIND, 'plan_sha256': canonical_sha256(plan),
            'stages': records, 'identities': identities, 'readbacks': observations,
            'preservation': preservation, 'phase_context': context}}
    except Exception as exc:
        return {**first, 'ok': False, 'error_code': 'OWNED_RESULT_STAGE_INDETERMINATE', 'message': str(exc),
            'owned_result_execution': {'kind': KIND, 'plan_sha256': canonical_sha256(plan), 'stages': records,
                'automatic_retry': False, 'failure': str(exc)}}


def execute_split(prepared, *, write, read, context):
    """Keep each actual creation result separate while proving one business roster."""
    from .builders.schema import validate_semantic_result
    plan = prepared['pre_state']['owned_result_stages']
    records, bindings, identities, metadata_reads = [], [], {}, []
    first = {}
    try:
        for stage in plan['creation_stages']:
            binding = {'readbacks': [], 'preservation': [], 'before_readbacks': [], 'before_preservation': []}
            bindings.append(binding)
            observe_before_creation(prepared, identities, read=read, context=context, binding=binding)
            args = materialize_creation_args(stage, identities)
            result = write(plan['uri'], args, plan['options'])
            records.append({'uri': plan['uri'], 'args': args, 'options': plan['options'], 'dispatch_result': result})
            if not first:
                first = result
            if result.get('ok') is not True:
                raise ValueError('Creation stage was not acknowledged; do not replay')
            validate_semantic_result(plan['uri'], result.get('result'), version=plan['version'])
            identities, _, _ = bind_split_stage(prepared, stage, result['result'], identities, read=read, context=context, binding=binding)
        def metadata_read(uri, args, options):
            result = read(uri, args, options)
            metadata_reads.append({'uri': uri, 'args': args, 'options': options, 'result': result})
            return result
        observe_reference_metadata(prepared, identities, read=metadata_read)
        for call in reference_calls(plan, identities):
            result = write(call['uri'], call['args'], call['options'])
            records.append({**call, 'dispatch_result': result})
            if result.get('ok') is not True:
                raise ValueError('Dependent reference stage was not acknowledged; do not replay')
            validate_semantic_result(call['uri'], result.get('result'), version=plan['version'])
        return {**first, 'owned_result_execution': {'kind': KIND, 'plan_sha256': canonical_sha256(plan), 'stages': records,
            'creation_bindings': bindings, 'identities': identities, 'readbacks': metadata_reads, 'phase_context': context}}
    except Exception as exc:
        return {**first, 'ok': False, 'error_code': 'OWNED_RESULT_STAGE_INDETERMINATE', 'message': str(exc),
            'owned_result_execution': {'kind': KIND, 'plan_sha256': canonical_sha256(plan), 'stages': records,
                'creation_bindings': bindings, 'automatic_retry': False, 'failure': str(exc)}}


def validate_split(prepared, execution, *, context):
    """Replay only retained evidence, never invent a merged native result tree."""
    from .builders.schema import validate_semantic_payload, validate_semantic_result
    plan = prepared['pre_state']['owned_result_stages']
    proof = execution.get('owned_result_execution', {})
    stages = proof.get('stages', [])
    creations = plan['creation_stages']
    bindings = proof.get('creation_bindings', [])
    if (proof.get('kind') != KIND or proof.get('plan_sha256') != canonical_sha256(plan)
            or proof.get('phase_context') != context or len(bindings) != len(creations)
            or len(stages) != len(creations) + (len(plan['deferred']) if plan['uri'] == CREATE else bool(plan['deferred']))
            or stages[0].get('dispatch_result', {}).get('result') != execution.get('result')):
        raise ValueError('Owned creation stages differ from their sealed source association')
    def replay(records, operation):
        reads = iter(records)
        def retained(uri, args, options):
            row = next(reads)
            if row.get('uri') != uri or row.get('args') != args or row.get('options') != options:
                raise ValueError('Owned creation stage lost its exact read association')
            validate_semantic_result(uri, row.get('result'), version=plan['version'])
            return row['result']
        result = operation(retained)
        if next(reads, None) is not None:
            raise ValueError('Owned creation stage has extra retained reads')
        return result
    identities = {}
    for stage, actual, binding in zip(creations, stages[:len(creations)], bindings, strict=True):
        if any(actual.get(key) != value for key, value in {'uri': plan['uri'], 'args': materialize_creation_args(stage, identities), 'options': plan['options']}.items()):
            raise ValueError('Creation stage is not its exact sealed ordinary root')
        if plan.get('pre_creation_roster_check'):
            before_preserved = binding.get('before_preservation', [])
            before_reads = [*binding.get('before_readbacks', []), *preservation_reads(before_preserved)]
            rebuilt_before = {'before_readbacks': [], 'before_preservation': []}
            replay(before_reads, lambda read: observe_before_creation(prepared, identities,
                read=read, context=context, binding=rebuilt_before))
            if rebuilt_before != {key: binding.get(key, []) for key in rebuilt_before}:
                raise ValueError('Before-creation proof differs from its sealed partial roster')
        preserved = binding.get('preservation', [])
        reads = [*binding.get('readbacks', []), *preservation_reads(preserved)]
        identities, observations, rebuilt = replay(reads, lambda read: bind_split_stage(prepared, stage,
            actual.get('dispatch_result', {}).get('result'), identities, read=read, context=context))
        if observations != binding.get('readbacks') or rebuilt != preserved:
            raise ValueError('Creation stage readbacks differ from the actual ownership proof')
    replay(proof.get('readbacks', []), lambda read: observe_reference_metadata(prepared, identities, read=read))
    if identities != proof.get('identities'):
        raise ValueError('Owned business roster differs from its actual per-stage observations')
    for stage, call in zip(stages[len(creations):], reference_calls(plan, identities), strict=True):
        if any(stage.get(key) != call[key] for key in ('uri', 'args', 'options')):
            raise ValueError('Dependent stage did not use its complete owned business roster')
    for stage in stages:
        if stage.get('dispatch_result', {}).get('ok') is not True:
            raise ValueError('Owned stage acknowledgement is incomplete')
        validate_semantic_payload(stage['uri'], stage['args'], stage['options'], version=plan['version'])
        validate_semantic_result(stage['uri'], stage['dispatch_result'].get('result'), version=plan['version'])
    return identities


def validate(prepared, execution, *, context=None):
    """Rebuild the association solely from retained actual native/read evidence."""
    from .builders.schema import validate_semantic_payload, validate_semantic_result
    plan = prepared['pre_state']['owned_result_stages']
    if plan.get('creation_stages'):
        return validate_split(prepared, execution, context=context)
    proof = execution.get('owned_result_execution', {})
    stages = proof.get('stages', [])
    if (proof.get('kind') != KIND or proof.get('plan_sha256') != canonical_sha256(plan) or len(stages) != 1 + (len(plan['deferred']) if plan['uri'] == CREATE else bool(plan['deferred']))
            or proof.get('phase_context') != context
            or stages[0].get('uri') != plan['uri'] or stages[0].get('args') != plan['creation_args']
            or stages[0].get('options') != plan['options']
            or stages[0].get('dispatch_result', {}).get('result') != execution.get('result')):
        raise ValueError('Owned stage association differs from immutable Preview and actual source result')
    reads = iter(proof.get('readbacks', []))
    def retained(uri, args, options):
        row = next(reads)
        if row.get('uri') != uri or row.get('args') != args or row.get('options') != options:
            raise ValueError('Owned stage binding lost its exact actual read association')
        validate_semantic_result(uri, row.get('result'), version=plan['version'])
        return row['result']
    identities, _ = bind(prepared, execution['result'], read=retained)
    if next(reads, None) is not None or identities != proof.get('identities'):
        raise ValueError('Owned result proof contains missing, extra or changed identity observations')
    preservation = iter(proof.get('preservation', []))
    preserved_reads = []
    for record in preservation:
        preserved_reads.extend(preservation_reads([record]))
    preserved_reads = iter(preserved_reads)
    def retained_preservation(uri, args, options):
        row = next(preserved_reads)
        if row.get('uri') != uri or row.get('args') != args or row.get('options') != options:
            raise ValueError('Owned preservation lost its exact native read association')
        validate_semantic_result(uri, row.get('result'), version=plan['version'])
        return row['result']
    preserved = observe_preservation(prepared, identities, read=retained_preservation, context=context)
    if next(preserved_reads, None) is not None or preserved != proof.get('preservation') or not all(row['passed'] for row in preserved):
        raise ValueError('Owned creation preservation differs from its complete actual stage proof')
    calls = reference_calls(plan, identities)
    if any(any(stage.get(key) != call[key] for key in ('uri', 'args', 'options'))
            for stage, call in zip(stages[1:], calls, strict=True)):
        raise ValueError('Dependent stage did not use the observed owned GUID and native reference identity')
    for stage in stages:
        if stage.get('dispatch_result', {}).get('ok') is not True:
            raise ValueError('Owned stage acknowledgement is incomplete')
        validate_semantic_payload(stage['uri'], stage['args'], stage['options'], version=plan['version'])
        validate_semantic_result(stage['uri'], stage['dispatch_result'].get('result'), version=plan['version'])
    return identities


def public_result(result):
    """Disclose owned-stage provenance without duplicating durable read images."""
    projected = deepcopy(result)
    for phase in projected.get('phases', []):
        dispatch = phase.get('dispatch_result', {})
        proof = dispatch.get('owned_result_execution')
        if proof is not None:
            dispatch['owned_result_execution'] = {'kind': proof['kind'], 'plan_sha256': proof['plan_sha256'],
                'canonical_sha256': canonical_sha256(proof), 'stage_count': len(proof['stages']),
                'full_stage_evidence_in_result': False,
                'exact_evidence_path': 'events[event_type=execution_completed].details.dispatch_result.result.phases[index=' + str(phase['index']) + '].dispatch_result.owned_result_execution'}
    return projected


def preservation_rows(prepared):
    """Complete ordinary retained parent and collision subtree images."""
    rows = {}
    stage_plan = prepared['pre_state']['owned_result_stages']
    if stage_plan['uri'] == CREATE:
        before = stage_plan['parent_before']
        rows[before['id'].upper()] = (before, sorted(str(row['id']).upper() for row in stage_plan['parent_children']))
    for spec in prepared['verification_plan']['nodes']:
        if spec.get('existing_target'):
            before = {**spec['pre_state'], 'classId': spec['class_id']}
            rows[before['id'].upper()] = (before, sorted(str(row['id']).upper() for row in spec.get('preexisting_children', [])))
    snapshots = [snapshot for rename in (prepared['pre_state'].get('planned_reference_context') or {}).get('renames', [])
        for snapshot in rename['collision_state']] + stage_plan.get('collision_state', []) + stage_plan.get('merge_state', [])
    for snapshot in snapshots:
        for before in snapshot['rows']:
            children = [row['id'].upper() for row in snapshot['rows']
                if str(row.get('parent', {}).get('id') if isinstance(row.get('parent'), Mapping) else row.get('parent')).upper() == before['id'].upper()]
            rows[before['id'].upper()] = (before, sorted(children))
    if len(rows) > DEFAULT_MAX_NODES or any(type(row.get('classId')) is not int or 'parent' not in row
            or not isinstance(row.get('notes'), str) for row, _ in rows.values()):
        raise ValueError('Owned result preservation requires complete bounded class/parent/notes images')
    return list(rows.values())


def observe_preservation(prepared, identities, *, read, context=None):
    from .object_graph_paths import project_compound_snapshot
    from .operation_registry import _same_identity
    records = []
    plan = prepared['pre_state']['owned_result_stages']
    removed = active_replaced_ids(plan, identities)
    for before, children in preservation_rows(prepared):
        expected = project_compound_snapshot(before, context)
        for node in prepared['verification_plan']['nodes']:
            if (node.get('preexisting_id') and node['request_path'] in identities
                    and _same_identity(node['preexisting_id'], before['id']) and node.get('notes_supplied')):
                expected['notes'] = node['requested_notes']
        args, options = {'from': {'id': [before['id']]}}, {'return': FIELDS}
        payload = read(GET, args, options)
        rows = payload.get('return') if isinstance(payload, Mapping) else None
        passed = isinstance(rows, list) and len(rows) == 1 and all(
            _same_identity(rows[0].get(key).get('id') if isinstance(rows[0].get(key), Mapping) else rows[0].get(key),
                expected.get(key).get('id') if isinstance(expected.get(key), Mapping) else expected.get(key))
            if key in {'id', 'parent'} else type(rows[0].get(key)) is type(expected.get(key)) and rows[0].get(key) == expected.get(key)
            for key in FIELDS)
        created = [row['id'].upper() for path, row in identities.items()
            if not next(node for node in prepared['verification_plan']['nodes'] if node['request_path'] == path).get('existing_target')
            and str(row.get('parent', {}).get('id') if isinstance(row.get('parent'), Mapping) else row.get('parent')).upper() == before['id'].upper()]
        child_args = {'from': {'id': [before['id']]}, 'transform': [{'select': ['children']}]}
        membership = read(GET, child_args, {'return': ['id']})
        found = membership.get('return') if isinstance(membership, Mapping) else None
        ids = [str(row.get('id')).upper() for row in found] if isinstance(found, list) else []
        passed = passed and isinstance(found, list) and len(ids) == len(set(ids)) and set(ids) == (set(children) - removed) | set(created)
        records.append({'role': 'owned-result-preservation', 'object_id': before['id'], 'passed': bool(passed),
            'uri': GET, 'args': args, 'options': options, 'result': payload,
            'membership': {'uri': GET, 'args': child_args, 'options': {'return': ['id']}, 'result': membership}})
    for scope in plan.get('replacements', []):
        active = scope['root'] in identities
        args = {'from': {'id': [row['id'] for row in scope['rows']] if active else [scope['root_id']]}}
        options = {'return': ['id', 'path'] if active else scope['fields']}
        if not active and scope.get('platform') is not None:
            options['platform'] = scope['platform']
        payload = read(GET, args, options)
        passed = isinstance(payload, Mapping) and payload.get('return') == ([] if active else [scope['before']])
        record = {'role': 'owned-result-replacement', 'object_id': scope['root_id'], 'passed': bool(passed),
            'uri': GET, 'args': args, 'options': options, 'result': payload}
        if not active:
            child_args = {'from': {'id': [scope['root_id']]}, 'transform': [{'select': ['descendants']}]}
            membership = read(GET, child_args, {'return': ['id', 'path']})
            found = membership.get('return') if isinstance(membership, Mapping) else None
            expected = [row for row in scope['rows'] if row['id'].upper() != scope['root_id'].upper()]
            passed = passed and isinstance(found, list) and sorted(found, key=lambda row: str(row.get('id'))) == sorted(expected, key=lambda row: row['id'])
            record.update(passed=bool(passed), membership={'uri': GET, 'args': child_args,
                'options': {'return': ['id', 'path']}, 'result': membership})
        records.append(record)
    return records
