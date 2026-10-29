"""GUID-bound path preservation for explicitly renamed graph ancestors.

This observes existing identities and checks sealed name intent; it constructs
no graph, native mutation, suffix, or caller path expression.
"""
from __future__ import annotations

import re

from .operation_object import DEFAULT_MAX_DEPTH, DEFAULT_MAX_NODES
from .identity_limits import MULTI_IDENTITY_READ_MAX_IDS

FIELDS = ('id', 'name', 'type', 'path', 'parent', 'notes')
_GUID = re.compile(r'\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}')


def parent_id(value):
    return value.get('id') if isinstance(value, dict) else value


def read_identity(read, object_id):
    if not isinstance(object_id, str) or not _GUID.fullmatch(object_id):
        raise ValueError('Ancestor path binding needs an exact GUID')
    result = read('ak.wwise.core.object.get', {'from': {'id': [object_id]}}, {'return': list(FIELDS)})
    rows = result.get('return') if isinstance(result, dict) else None
    if (not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict)
            or not isinstance(rows[0].get('id'), str) or rows[0]['id'].casefold() != object_id.casefold()):
        raise ValueError('Ancestor identity must resolve exactly once')
    row = {key: rows[0][key] for key in FIELDS if key in rows[0]}
    if any(not isinstance(row.get(key), str) or (not row[key] and key != 'notes') for key in ('name', 'type', 'path', 'notes')):
        raise ValueError('Ancestor identity snapshot is incomplete')
    return row


def expected_snapshot(snapshot, *, edits, read_row):
    """Rewrite old path components only for exact-GUID admitted name edits."""
    if not isinstance(edits, (list, tuple)) or len(edits) > DEFAULT_MAX_NODES:
        raise ValueError('Ancestor edit context exceeds the graph node bound')
    row = dict(snapshot)
    segments = row['path'].split('\\')
    for node in edits:
        if (node.get('existing_target') is not True and node.get('preexisting_id') is None) or not isinstance(node.get('pre_state'), dict):
            continue
        before = node['pre_state']
        target_id = node.get('target_id', node.get('preexisting_id'))
        same = target_id.casefold() == row['id'].casefold()
        if same and node.get('notes_supplied') is True and node.get('existing_target') is True:
            row['notes'] = node['requested_notes']
        name = node.get('requested_name')
        old_path = before.get('path')
        if name == node.get('original_name', before.get('name')):
            continue
        if not isinstance(old_path, str):
            raise ValueError('A requested rename lacks its original path')
        path_affected = snapshot['path'] == old_path or snapshot['path'].startswith(old_path + '\\')
        projected_relations = [key for key in ('parent', 'owner') if isinstance(row.get(key), dict)
            and isinstance(row[key].get('id'), str) and row[key]['id'].casefold() == target_id.casefold()
            and 'name' in row[key]]
        if not path_affected and not projected_relations:
            continue
        actual = read_row(target_id)
        actual_name = actual.get('name')
        if (not isinstance(name, str) or not isinstance(actual_name, str) or not actual_name or '\\' in actual_name
                or actual_name != name):
            raise ValueError('Actual name differs from the sealed graph rename policy')
        if path_affected:
            segments[len(old_path.split('\\')) - 1] = actual_name
        if same:
            row['name'] = actual_name
        for relation in projected_relations:
            # Only the exact sealed renamed parent/owner may change its label.
            # Opaque member paths remain unchanged unless the prior path itself
            # contains the source-proven ancestor component above.
            row[relation] = {**row[relation], 'name': actual_name}
    row['path'] = '\\'.join(segments)
    return row


def prepare_ancestor_path_guards(specs, *, read):
    """Acquire only missing ancestry needed by an explicit ancestor rename."""
    roots = [node for node in specs if node.get('existing_target') is True]
    cache = {node['target_id'].casefold(): {key: node['pre_state'][key] for key in FIELDS if key in node['pre_state']}
             for node in roots}
    renamed = [node for node in roots if node.get('requested_name') != node.get('original_name')]
    added = {}
    for node in roots:
        source = cache[node['target_id'].casefold()]
        needed = {ancestor['target_id'].casefold() for ancestor in renamed
            if source['path'].startswith(ancestor['pre_state']['path'] + '\\')}
        if not needed:
            continue
        if not isinstance(parent_id(source.get('parent')), str) and node.get('requested_name') == node.get('original_name'):
            # No ordinary parent chain or static renamed-source path to repair.
            # Owned-member preservation remains on the separate List/owner guards.
            continue
        current, chain, visited = source, [], {source['id'].casefold()}
        for _ in range(DEFAULT_MAX_DEPTH):
            object_id = parent_id(current.get('parent'))
            if not isinstance(object_id, str) or not _GUID.fullmatch(object_id) or object_id.casefold() in visited:
                raise ValueError('Requested ancestor rename has a missing or cyclic GUID parent chain')
            key = object_id.casefold()
            if key not in cache:
                if len(cache) >= MULTI_IDENTITY_READ_MAX_IDS:
                    raise ValueError('Ancestor identity set exceeds the existing read bound')
                cache[key] = read_identity(read, object_id)
                added[key] = cache[key]
            parent = cache[key]
            if current['path'] != parent['path'] + '\\' + current['name']:
                raise ValueError('Requested ancestor rename lacks matching GUID/path ancestry')
            chain.append(parent)
            visited.add(key)
            needed.discard(key)
            if not needed:
                break
            current = parent
        if needed:
            raise ValueError('Requested ancestor rename exceeds the existing graph depth bound')
        node['ancestor_rename_path_guard'] = {'source': source, 'ancestors': chain}
    return list(added.values())


def verify_ancestor_path_guard(guard, *, edits, read):
    snapshots = [guard['source'], *guard['ancestors']]
    if len(snapshots) > DEFAULT_MAX_DEPTH + 1:
        raise ValueError('Ancestor proof exceeds the graph depth bound')
    cache = {}
    def read_row(object_id):
        key = object_id.casefold()
        if key not in cache:
            cache[key] = read_identity(read, object_id)
        return cache[key]
    expected_rows = [expected_snapshot(row, edits=edits, read_row=read_row) for row in snapshots]
    passed = all(read_row(row['id']) == expected for row, expected in zip(snapshots, expected_rows))
    return passed, expected_rows[0]['path'], {'expected': expected_rows, 'actual': list(cache.values())}


def compound_rename_edits(calls):
    """Normalize only original, explicit existing-object name outcomes."""
    edits = []
    for call in calls:
        child = call.get('prepared_operation', {})
        plan, state = child.get('verification_plan', {}), child.get('pre_state', {})
        if plan.get('kind') == 'same-guid-renamed':
            before = state['object']
            edits.append({'existing_target': True, 'target_id': plan['object_id'],
                'pre_state': before, 'original_name': before['name'],
                'requested_name': plan['expected_name'], 'on_name_conflict': 'fail'})
        elif plan.get('kind') == 'object-set-batch':
            edits.extend(dict(node) for node in plan.get('nodes', [])
                if node.get('existing_target') is True and node.get('requested_name') != node.get('original_name'))
    return edits


def compound_expected_context(context, calls):
    """Reconstruct declared final notes without changing the sealed path context."""
    validate_compound_path_context(context, calls)
    notes = {}
    for call in calls:
        plan = call.get('prepared_operation', {}).get('verification_plan', {})
        if plan.get('kind') == 'same-guid-notes':
            notes[plan['object_id'].casefold()] = plan['expected_notes']
        elif plan.get('kind') == 'object-set-batch':
            for node in plan.get('nodes', []):
                if node.get('existing_target') is True and node.get('notes_supplied') is True:
                    notes[node['target_id'].casefold()] = node['requested_notes']
    return {**context, 'notes_outcomes': notes}


def project_compound_path(path, context):
    if not context:
        return path
    return expected_snapshot({'id': '', 'name': path.rsplit('\\', 1)[-1], 'path': path},
        edits=context['edits'], read_row=lambda key: {'name': next(node['requested_name']
            for node in context['edits'] if node['target_id'].casefold() == key.casefold())})['path']


def prepare_compound_path_context(calls, *, read):
    """Seal missing GUID ancestry without changing any original child artifact."""
    edits = compound_rename_edits(calls)
    graphs = [call['prepared_operation'] for call in calls
        if call.get('prepared_operation', {}).get('verification_plan', {}).get('kind') == 'object-create-graph'
        or call.get('prepared_operation', {}).get('pre_state', {}).get('owned_result_stages')]
    from .creation_observations import compound_source_removed_ids
    removed = {object_id.casefold() for child in graphs
        for object_id in compound_source_removed_ids(child['verification_plan'], child['pre_state'])}
    def affected(row):
        return isinstance(row, dict) and isinstance(row.get('path'), str) and any(
            row['path'] == node['pre_state']['path'] or row['path'].startswith(node['pre_state']['path'] + '\\')
            for node in edits)
    render_chains = [chain for call in calls
        for chain in call.get('prepared_operation', {}).get('pre_state', {}).get('effect_render_chains', [])]
    owned_members = {item['object_id'].casefold() for chain in render_chains for item in chain.get('snapshots', [])
        if isinstance(parent_id(item.get('before', {}).get('owner')), str)
        and parent_id(item['before']['owner']).casefold() == str(chain.get('owner_id')).casefold()}
    render_rows = [row for chain in render_chains
        for row in [chain.get('source', {}).get('scope', {}).get('owner'),
            *(item.get('before') for item in chain.get('snapshots', [])),
            *(item.get('before') for item in chain.get('targets', []))]]
    if not edits or not (any(affected(role.get('row')) for child in graphs
            for role in child.get('resolved_roles', {}).values()) or any(affected(row) for row in render_rows)):
        return None
    identities = {}
    def collect(value):
        if isinstance(value, dict):
            # Owned List members retain their opaque path/owner proof in the
            # complete Render model, not an invented ordinary parent chain.
            if (all(isinstance(value.get(key), str) for key in ('id', 'name', 'type', 'path'))
                    and _GUID.fullmatch(value['id']) and value['id'].casefold() not in owned_members | removed):
                if any(value['path'] == node['pre_state']['path'] or value['path'].startswith(node['pre_state']['path'] + '\\') for node in edits):
                    key = value['id'].casefold()
                    if key in identities and any(identities[key][field] != value[field] for field in ('id', 'name', 'type', 'path')):
                        raise ValueError('Compound path roles disagree about their original GUID identity')
                    identities[key] = value
            for item in value.values(): collect(item)
        elif isinstance(value, list):
            for item in value: collect(item)
    for call in calls: collect(call.get('prepared_operation', {}))
    for node in edits: identities[node['target_id'].casefold()] = node['pre_state']
    if len(identities) > MULTI_IDENTITY_READ_MAX_IDS:
        raise ValueError('Compound ancestor identities exceed the existing identity read bound')
    roots, snapshots, cache = [], {}, {}
    def cached_read(uri, args, options):
        object_id, = args['from']['id']
        key = object_id.casefold()
        if key not in cache:
            if len(cache) >= MULTI_IDENTITY_READ_MAX_IDS:
                raise ValueError('Compound ancestor identities exceed the existing identity read bound')
            cache[key] = read(uri, args, options)
        return cache[key]
    for key, before in sorted(identities.items()):
        actual = canonical_path_row(read_identity(cached_read, before['id']))
        if any(actual.get(field) != canonical_path_row(before).get(field) for field in ('id', 'name', 'type', 'path')):
            raise ValueError('Compound path role differs from its exact live GUID identity')
        snapshots[key] = actual
        edit = next((node for node in edits if node['target_id'].casefold() == key), None)
        roots.append({'existing_target': True, 'target_id': actual['id'], 'pre_state': actual,
            'original_name': actual['name'], 'requested_name': edit['requested_name'] if edit else actual['name']})
    for row in prepare_ancestor_path_guards(roots, read=lambda uri, args, options: {'return': [canonical_path_row(row) for row in cached_read(uri, args, options)['return']]}):
        snapshots[row['id'].casefold()] = canonical_path_row(row)
    context = {'edits': edits, 'snapshots': [snapshots[key] for key in sorted(snapshots)],
        'guards': [node['ancestor_rename_path_guard'] for node in roots if 'ancestor_rename_path_guard' in node]}
    ordinary = [project_compound_path(node['pre_state']['path'], context).casefold()
        for node in edits if node.get('collection') in {None, 'children'}]
    if len(ordinary) != len(set(ordinary)):
        raise ValueError('Compound final ordinary hierarchy rename paths have a collision')
    return context


def validate_compound_path_context(context, calls):
    from .canonical import canonical_sha256
    if not isinstance(context, dict) or set(context) != {'edits', 'snapshots', 'guards'}:
        raise ValueError('Compound path context is malformed')
    if canonical_sha256(context['edits']) != canonical_sha256(compound_rename_edits(calls)):
        raise ValueError('Compound path context differs from the original child rename intent')
    snapshots = context['snapshots']
    if not isinstance(snapshots, list) or len(snapshots) > MULTI_IDENTITY_READ_MAX_IDS:
        raise ValueError('Compound ancestor context exceeds the existing identity bound')
    rows = {row['id'].casefold(): row for row in snapshots}
    if len(rows) != len(snapshots):
        raise ValueError('Compound path context repeats an ancestor GUID')
    def sealed_read(uri, args, options):
        object_id, = args['from']['id']
        row = rows.get(object_id.casefold())
        if row is None:
            raise ValueError('Compound context omits a required original GUID ancestor')
        return {'return': [row]}
    rebuilt = prepare_compound_path_context(calls, read=sealed_read)
    if canonical_sha256(context) != canonical_sha256(rebuilt):
        raise ValueError('Compound context does not cover every required original GUID ancestry edge')
    return context


def compound_context_expected(context):
    expected = []
    for row in context['snapshots']:
        projected = project_compound_snapshot(row, context)
        if row['id'].casefold() not in context.get('notes_outcomes', {}):
            projected.pop('notes', None)  # Unrequested notes retain their existing preservation observers.
        expected.append(projected)
    return expected


def observe_compound_path_context(context, *, read):
    from .canonical import canonical_sha256
    expected = compound_context_expected(context)
    args = {'from': {'id': [row['id'] for row in expected]}}
    options = {'return': list(FIELDS)}
    result = read('ak.wwise.core.object.get', args, options)
    record = {'role': 'compound-path-context', 'uri': 'ak.wwise.core.object.get', 'args': args,
        'options': options, 'result': result}
    passed = compound_context_result_matches(context, record)
    missing_parent = [row['id'] for row in context['snapshots'] if 'parent' not in row]
    return {'name': 'compound final GUID ancestry matches sealed name intent', 'kind': 'compound_path_context',
        'passed': passed, 'evidence': {'sha256': canonical_sha256(context),
            **({'missing_original_parent_facts': missing_parent} if missing_parent else {})}}, record


def compound_context_result_matches(context, record):
    expected = compound_context_expected(context)
    if any('parent' not in row for row in expected):
        return False
    if (record.get('role') != 'compound-path-context' or record.get('uri') != 'ak.wwise.core.object.get'
            or record.get('args') != {'from': {'id': [row['id'] for row in expected]}}
            or record.get('options') != {'return': list(FIELDS)} or 'error' in record):
        return False
    result = record.get('result')
    rows = result.get('return') if isinstance(result, dict) and set(result) == {'return'} else None
    if not isinstance(rows, list) or len(rows) != len(expected) or any(not isinstance(row, dict) for row in rows):
        return False
    actual = {str(row.get('id')).casefold(): canonical_path_row(row) for row in rows}
    return len(actual) == len(rows) and all(all(actual.get(row['id'].casefold(), {}).get(key) == value
        for key, value in row.items()) for row in expected)


def canonical_path_row(row):
    """Canonical relation identity, preserving omission separately from null."""
    result = {key: value for key, value in row.items() if key in FIELDS}
    if isinstance(result.get('id'), str):
        result['id'] = result['id'].upper()
    if 'parent' in result:
        from .edit_history_business import _reference_value
        result['parent'] = _reference_value(result['parent'])
    return result


def compound_phase_arguments(calls, index, context):
    """Materialize only declared internal graph references at their actual phase."""
    from copy import deepcopy
    child = calls[index].get('prepared_operation', {})
    original = child.get('dispatch', {}).get('args', calls[index].get('args', {}))
    args = deepcopy(original)
    if (not context or child.get('verification_plan', {}).get('kind') != 'object-create-graph'
            or child.get('pre_state', {}).get('owned_result_stages')):
        return args
    from .creation_observations import ordinary_creation_graph
    plan = child['verification_plan']
    _, paths = ordinary_creation_graph(plan, child['pre_state'], parent=child['resolved_roles']['parent']['row'])
    earlier = {'edits': compound_rename_edits(calls[:index])}
    for spec in plan['nodes']:
        node = args
        for token in re.findall(r'\.children\[(\d+)\]', spec['request_path']):
            node = node['children'][int(token)]
        for field in spec.get('references', []):
            if 'target_request_path' in field:
                node['@' + field['name']] = project_compound_path(paths[field['target_request_path']], earlier)
    return args


def project_compound_snapshot(row, context):
    """Expected final identity; callers retain original evidence separately."""
    if not context:
        return dict(row)
    def intent(key):
        return {'name': next(node['requested_name'] for node in context['edits']
            if node['target_id'].casefold() == key.casefold())}
    projected = expected_snapshot(row, edits=context['edits'], read_row=intent)
    key = str(row.get('id')).casefold()
    if key in context.get('notes_outcomes', {}):
        projected['notes'] = context['notes_outcomes'][key]
    return projected


def compound_created_child_roots(calls, phases):
    """Associate actual sibling create roots with their original child and parent."""
    from .operation_object import flatten_create_result
    roots = []
    for index, call in enumerate(calls):
        child = call.get('prepared_operation', {})
        plan = child.get('verification_plan', {})
        if child.get('pre_state', {}).get('owned_result_stages'):
            from .owned_result_stages import validate as validate_owned_stages
            from .creation_observations import compound_source_creation_graphs
            phase = phases[index + 1]
            if phase.get('phase') != 'inner' or type(phase.get('index')) is not int or phase['index'] != index:
                raise ValueError('Staged created root lacks its actual indexed parent-owned phase')
            result = phase.get('dispatch_result', {})
            if result.get('ok') is not True:
                raise ValueError('Staged created root lacks successful actual native acknowledgements')
            actual = validate_owned_stages(child, result, context={'edits': compound_rename_edits(calls[:index])})
            for group in compound_source_creation_graphs(plan, child['pre_state']):
                root = next(node for node in group['nodes'] if node['request_path'] == group['root'])
                if root.get('collection') not in {None, 'children'}:
                    continue  # Owned List occurrences are not ordinary sibling roots.
                roots.append({'child_index': index, 'request_path': group['root'],
                    'parent_id': group['parent_id'].upper(), 'object_id': actual[group['root']]['id'].upper()})
            continue
        if child.get('operation') != 'object.create' or plan.get('kind') != 'object-create-graph':
            continue
        if plan.get('list') is not None:
            continue  # This root is an owned List occurrence, never an ordinary sibling.
        phase = phases[index + 1]
        result = phase.get('dispatch_result', {})
        if (phase.get('phase') != 'inner' or type(phase.get('index')) is not int or phase['index'] != index
                or result.get('ok') is not True):
            raise ValueError('Compound created child root lacks its successful actual sibling phase')
        returned = [row for row in flatten_create_result(result.get('result')) if row.request_path == '$']
        if len(returned) != 1 or returned[0].name != plan['nodes'][0]['requested_name']:
            raise ValueError('Compound sibling root differs from its original creation declaration')
        roots.append({'child_index': index, 'request_path': '$', 'parent_id': plan['parent_id'].upper(),
            'object_id': returned[0].object.upper()})
    return roots
