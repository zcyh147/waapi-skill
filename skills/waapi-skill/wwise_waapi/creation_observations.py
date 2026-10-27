"""Canonical structured creation identity shared by Gateway and receipt observers."""
from __future__ import annotations

from typing import Any, Mapping

from .business_declarations import normalize_live_object_identity


def ordinary_creation_fields(node: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    """Return materialized ordinary fields; richer graph unions need their own proof."""
    fields = []
    for kind, key in (("scalar", "properties"), ("reference", "references")):
        for item in node.get(key, []):
            if (not isinstance(item, Mapping) or not isinstance(item.get("name"), str)
                    or (kind == "reference" and "target_request_path" not in item and ("target_id" not in item
                        or (item["target_id"] is not None and not isinstance(item["target_id"], str))))):
                return None
            fields.append({"kind": kind, **dict(item)})
    return fields


def ordinary_creation_graph(plan, state, *, parent, max_observations=128):
    """Validate the complete ordinary new hierarchy, never a supported subset."""
    nodes = plan.get('nodes')
    if (not isinstance(nodes, list) or not nodes or not all(isinstance(node, Mapping) for node in nodes)
            or plan.get('on_name_conflict') != 'fail'
            or plan.get('list') is not None or plan.get('preexisting_root_rows') != []
            or plan.get('replaced_subtree_rows') != []):
        raise ValueError('Creation history needs a complete ordinary new fail-mode hierarchy; List/merge/replace/restoration remain implementation obligations')
    paths, field_count = {}, 0
    for node in nodes:
        path = node.get('request_path')
        fields = ordinary_creation_fields(node)
        if (not isinstance(path, str) or path in paths or fields is None
                or type(node.get('class_id')) is not int or node['class_id'] <= 0
                or node.get('collection') != 'children' or node.get('existing_target') is not False
                or node.get('preexisting_id') is not None or node.get('requested_language') is not None
                or node.get('list_request_paths') or node.get('import_requested') or 'import' in node
                or 'graph_plugin_native' in node or any('curve' in field or 'array' in field for field in fields)
                or len({field['name'] for field in fields}) != len(fields)):
            raise ValueError('Creation history requires every declared node and field to have an ordinary hierarchy observation')
        paths[path] = node
        field_count += len(fields)
    if len(nodes) + field_count > max_observations:
        raise ValueError('Creation history complete graph exceeds its combined observation bound')
    if nodes[0].get('request_path') != '$' or nodes[0].get('parent_request_path') is not None:
        raise ValueError('Creation history requires one exact declared root')
    for node in nodes:
        path = node['request_path']
        if path != '$' and node.get('parent_request_path') not in paths:
            raise ValueError('Creation history node lacks its declared parent')
        current, seen = path, set()
        while current != '$':
            if current in seen or current not in paths:
                raise ValueError('Creation history graph is not a connected hierarchy')
            seen.add(current)
            current = paths[current].get('parent_request_path')
        children = [child['request_path'] for child in nodes if child.get('parent_request_path') == path]
        if 'children_request_paths' in node and node['children_request_paths'] != children:
            raise ValueError('Creation history declared child roster is incomplete')
        for field in ordinary_creation_fields(node):
            if 'target_request_path' in field and field['target_request_path'] not in paths:
                raise ValueError('Creation history reference lacks its declared graph target')
    parent_identity = normalize_live_object_identity(parent)
    if parent_identity.object_id.upper() != str(plan.get('parent_id')).upper():
        raise ValueError('Creation history requires its exact sealed parent identity')
    root_path = parent_identity.path.rstrip('\\') + '\\' + nodes[0]['requested_name']
    roots = [row for row in state.get('object_graph_guard', {}).get('path_snapshots', [])
             if row.get('path') == root_path]
    if not roots or any(row.get('rows') != [] for row in roots):
        raise ValueError('Creation history requires one sealed absent root path')
    expected_paths = {'$': root_path}
    pending = dict(paths)
    while pending:
        ready = [path for path, node in pending.items() if path == '$' or node['parent_request_path'] in expected_paths]
        if not ready:
            raise ValueError('Creation history graph has no connected traversal')
        for path in ready:
            node = pending.pop(path)
            if path != '$':
                expected_paths[path] = expected_paths[node['parent_request_path']] + '\\' + node['requested_name']
    if len({path.casefold() for path in expected_paths.values()}) != len(nodes):
        raise ValueError('Creation history graph has duplicate native hierarchy paths')
    return nodes, expected_paths


def require_compound_creation_scope(calls):
    """Bound complete source scopes independently of optional history eligibility."""
    from .operation_registry import OperationContractError
    from .edit_history_business import MAX_OBSERVATIONS
    prepared = [row.get('prepared_operation', {}) for row in calls]
    if not any(child.get('verification_plan', {}).get('kind') == 'object-create-graph'
            or child.get('pre_state', {}).get('owned_result_stages') for child in prepared):
        return
    graphs, known_count = [], 0
    for child in prepared:
        plan, state = child.get('verification_plan', {}), child.get('pre_state', {})
        kind = plan.get('kind')
        stage = state.get('owned_result_stages', {})
        if kind in {'object-create-graph', 'object-set-batch'} and (stage.get('lists')
                or any('targets' in field for field in stage.get('deferred', []))):
            # Validate source ownership, but do not budget an unavailable optional
            # history observer. Source node/List/field/plan limits still apply.
            compound_source_creation_graphs(plan, state)
            continue
        chains = state.get('effect_render_chains', [])
        covered = {}
        for chain in chains:
            # Arity only. Actual source observations are still required before
            # any receipt can certify the fields or the preservation image.
            known_count += 1 + sum(len(snapshot.get('after_changes', {})) for snapshot in chain.get('snapshots', []))
            for item in chain.get('metadata', []):
                key = (str(item['scope'].get('object_id')).upper(), chain.get('platform'))
                covered.setdefault(key, set()).add(item['field'])
        if kind in {'object-create-graph', 'object-set-batch'} and state.get('owned_result_stages'):
            groups = compound_source_creation_graphs(plan, state)
            graphs.append(True)
            from .owned_result_stages import preservation_rows
            known_count += sum(len(group['nodes']) + sum(len(ordinary_creation_fields(node))
                for node in group['nodes']) for group in groups) + len(preservation_rows(child))
            continue
        if kind == 'object-create-graph':
            nodes, _ = ordinary_creation_graph(plan, state,
                parent=child.get('resolved_roles', {}).get('parent', {}).get('row'), max_observations=MAX_OBSERVATIONS)
            graphs.append(True)
            known_count += len(nodes) + sum(len(ordinary_creation_fields(node)) for node in nodes)
        elif kind == 'same-guid-renamed':
            known_count += 1
        elif kind in {'same-guid-notes', 'same-guid-property', 'same-guid-reference'} and not state.get('effect_render_chains'):
            known_count += 1
        elif kind == 'object-set-batch':
            for node in plan.get('nodes', []):
                proofs = [proof for proof in state.get('existing_field_observations', [])
                    if proof.get('request_path') == node.get('request_path')]
                view = proofs[0].get('field_read_platform', {}).get('platform_id') if len(proofs) == 1 else None
                excluded = covered.get((str(node.get('target_id')).upper(), view), set())
                fields = ({'name'} if node.get('requested_name') != node.get('original_name') else set())
                fields.update({'notes'} if node.get('notes_supplied') else ())
                fields.update(item['name'] for key in ('properties', 'references') for item in node.get(key, []))
                known_count += len(fields - excluded)
    if not graphs:
        return
    if known_count > MAX_OBSERVATIONS:
        raise OperationContractError('UNDO_GROUP_OBSERVATION_LIMIT_EXCEEDED',
            'Compound created graph and known companion outcomes exceed the complete history observation bound.')


def ordinary_staged_creation_graphs(plan, state):
    """Admit complete staged ordinary new trees below retained exact parents."""
    nodes = plan.get('nodes', [])
    if (not state.get('owned_result_stages') or plan.get('on_name_conflict') not in {'fail', 'rename'}
            or not nodes or len(nodes) > 128 or plan.get('replaced_subtree_rows') or plan.get('replaced_list_subtree_rows')):
        raise ValueError('Set creation history needs its complete owned ordinary stage plan')
    existing = {node['request_path']: node for node in nodes if node.get('existing_target') is True}
    new = {node['request_path']: node for node in nodes if node.get('existing_target') is False}
    if not new or len(new) + len(existing) != len(nodes):
        raise ValueError('Set creation history requires a complete distinct existing/new roster')
    for node in nodes:
        fields = ordinary_creation_fields(node)
        if (fields is None or type(node.get('class_id')) is not int or node['class_id'] <= 0
                or node.get('preexisting_id') is not None or node.get('collection') not in {None, 'children'}
                or node.get('list_request_paths') or node.get('list_snapshots') or node.get('import_requested')
                or node.get('requested_language') or node.get('graph_plugin_native')
                or any('curve' in field or 'array' in field for field in fields)):
            raise ValueError('Every set creation node requires its complete ordinary hierarchy observation')
        if node.get('existing_target') and (fields or node.get('notes_supplied')
                or node.get('requested_name') != node.get('original_name')):
            raise ValueError('Staged set creation history currently retains its existing parents without field edits')
    if plan.get('kind') == 'object-create-graph':
        stage = state['owned_result_stages']
        if (existing or plan.get('list') is not None or nodes[0]['request_path'] != '$'
                or nodes[0].get('parent_request_path') is not None
                or stage.get('uri') != 'ak.wwise.core.object.create'
                or str(stage.get('parent_id')).upper() != str(plan.get('parent_id')).upper()
                or any(node['request_path'] != '$' and node.get('parent_request_path') not in new for node in nodes)
                or any('target_request_path' in field and field['target_request_path'] not in new
                    for node in nodes for field in ordinary_creation_fields(node))
                or len(new) + sum(len(ordinary_creation_fields(node)) for node in nodes) > 128):
            raise ValueError('Staged CREATE history requires its complete bounded new graph and exact retained parent')
        return [{'root': '$', 'parent_id': plan['parent_id'], 'nodes': nodes}]
    groups, visited = [], set()
    for path, root in new.items():
        parent = existing.get(root.get('parent_request_path'))
        if parent is None:
            continue
        group = [node for child_path, node in new.items() if child_path == path or child_path.startswith(path + '.')]
        paths = {node['request_path'] for node in group}
        if any(node is not root and node.get('parent_request_path') not in paths for node in group):
            raise ValueError('Set creation graph is not connected to its retained parent')
        if any('target_request_path' in field and field['target_request_path'] not in new
                for node in group for field in ordinary_creation_fields(node)):
            raise ValueError('Creation references require their complete shared new-node observation roster')
        groups.append({'root': path, 'parent_id': parent['target_id'], 'nodes': group})
        visited.update(paths)
    if visited != set(new) or len(visited) + sum(len(ordinary_creation_fields(node)) for node in new.values()) > 128:
        raise ValueError('Set creation history lacks a complete bounded new graph partition')
    return groups


def compound_source_creation_graphs(plan, state):
    """Project supported source groups without granting history-observer authority."""
    try:
        return ordinary_staged_creation_graphs(plan, state)
    except ValueError:
        pass
    from copy import deepcopy
    from .owned_result_stages import list_profiles

    stage = state.get('owned_result_stages', {})
    nodes = plan.get('nodes', [])
    profiles = stage.get('lists', [])
    arrays = [{'source': node['request_path'], 'field': field['name'], 'targets': field['target_results'],
        'list_mode': field['list_mode'], 'binding': field['list_binding'],
        'platform': node.get('platform', stage.get('creation_args', {}).get('platform'))}
        for node in nodes for field in node.get('references', []) if 'target_results' in field]
    if (plan.get('kind') != 'object-set-batch' or stage.get('uri') != 'ak.wwise.core.object.set'
            or not (profiles or arrays) or stage.get('version') != plan.get('version')
            or not nodes or len(nodes) > 128 or len({node['request_path'] for node in nodes}) != len(nodes)):
        raise ValueError('Compound source needs a complete supported staged creation graph')
    by_path = {node['request_path']: node for node in nodes}
    if arrays != [field for field in stage.get('deferred', []) if 'targets' in field]:
        raise ValueError('Compound reference Lists differ from their complete producer-owned declarations')
    from .documented_list_fields import legacy_playlist_authority
    for field in arrays:
        owner, binding = by_path[field['source']], field['binding']
        if (owner.get('existing_target') is not False or owner.get('preexisting_id') is not None
                or legacy_playlist_authority(binding) is None or binding.get('version') != plan['version']
                or binding.get('planned_owner', {}).get('request_path') != owner['request_path']
                or binding.get('scope', {}).get('class_id') != owner['class_id']
                or not field['targets'] or any(set(target) != {'request_path'}
                    or target['request_path'] not in by_path
                    or by_path[target['request_path']].get('parent_request_path') != owner['request_path']
                    or by_path[target['request_path']].get('collection') != 'children'
                    for target in field['targets'])):
            raise ValueError('Compound reference List needs its exact source-certified new owner and direct-child targets')
    members = set()
    declared_members = {path for profile in profiles for path in profile['members']}
    for profile in profiles:
        owner = by_path.get(profile['owner'])
        if (owner is None or type(owner.get('existing_target')) is not bool
                or owner.get('preexisting_id') is not None and owner.get('on_name_conflict') != 'merge'
                or owner.get('collection') not in {None, 'children'} and owner['request_path'] not in declared_members
                or not profile.get('members')):
            raise ValueError('Compound owned Lists require an exact ordinary new or retained source owner')
        for path in profile['members']:
            node = by_path.get(path)
            fields = ordinary_creation_fields(node) if node is not None else None
            if (path in members or node is None or node.get('parent_request_path') != profile['owner']
                    or node.get('collection') != profile['name'] or node.get('existing_target') is not False
                    or node.get('preexisting_id') is not None or fields is None
                    or node.get('import_requested') or node.get('requested_language') or node.get('graph_plugin_native')
                    or any('curve' in field or 'array' in field for field in fields)):
                raise ValueError('Compound source List needs every fresh source-certified occurrence')
            members.add(path)
    guards = [*state.get('documented_planned_list_guards', []), *state.get('documented_list_guards', [])]
    if list_profiles(deepcopy(nodes), guards, plan['version']) != profiles:
        raise ValueError('Compound source List differs from its exact producer-owned source and complete roster')
    if {node['request_path'] for node in nodes if node.get('collection') not in {None, 'children'}} != members:
        raise ValueError('Compound source contains an unowned List occurrence')
    replaced = {str(row['id']).upper() for profile in profiles if profile.get('mode') == 'replaceAll'
        for row in profile['before']}
    if {str(row['id']).upper() for row in plan.get('replaced_list_subtree_rows', [])} != replaced:
        raise ValueError('Compound source List replacement needs its complete source-certified leaf roster')
    if plan.get('replaced_subtree_rows', []) != [row for scope in stage.get('replacements', []) for row in scope['rows']]:
        raise ValueError('Compound source replacement differs from its exact producer-owned original subtree')
    new_paths = {node['request_path'] for node in nodes if node.get('existing_target') is False}
    ordinary = []
    for node in nodes:
        fields = ordinary_creation_fields({**node,
            'references': [field for field in node.get('references', []) if 'target_results' not in field]})
        if (fields is None or any('curve' in field or 'array' in field for field in fields)
                or any('target_request_path' in field and field['target_request_path'] not in new_paths for field in fields)):
            raise ValueError('Compound source requires every field and shared new-node reference target')
        projected = dict(node)
        projected['list_request_paths'], projected['list_snapshots'] = [], []
        # Only the request-path partition is shared with ordinary creation.
        # Actual List ownership, membership and replacement remain in the exact
        # source profiles and original nodes returned below, never native paths.
        if node['request_path'] in members:
            projected['collection'] = 'children'
        if node.get('existing_target'):
            if (node.get('requested_name') != node.get('original_name') or node.get('notes_supplied')
                    or node.get('properties') or any('target_request_path' not in field
                        for field in node.get('references', []))):
                raise ValueError('Compound staged source retains existing owners except its closed result references and Lists')
        if node.get('preexisting_id') is not None:
            if node['request_path'] not in {profile['owner'] for profile in profiles} or node.get('on_name_conflict') != 'merge':
                raise ValueError('Compound merged source requires its exact producer-owned List owner')
            projected.update(existing_target=True, target_id=node['preexisting_id'], preexisting_id=None,
                original_name=node['pre_state']['name'], notes_supplied=False)
        # Source fields have their own producer bounds; do not count them again
        # against the optional ordinary history observer's combined budget.
        projected['properties'], projected['references'] = [], []
        ordinary.append(projected)
    groups = ordinary_staged_creation_graphs({**plan, 'nodes': ordinary,
        'on_name_conflict': 'fail' if plan.get('on_name_conflict') in {'merge', 'replace'} else plan.get('on_name_conflict'),
        'replaced_subtree_rows': [], 'replaced_list_subtree_rows': []}, state)
    result = [{**group, 'nodes': [node for node in nodes if node['request_path'] == group['root']
        or node['request_path'].startswith(group['root'] + '.')]} for group in groups]
    if {node['request_path'] for group in result for node in group['nodes']} != {
            node['request_path'] for node in nodes if node.get('existing_target') is False and node.get('preexisting_id') is None}:
        raise ValueError('Compound source graph partition is incomplete')
    return result


def compound_source_removed_ids(plan, state):
    """Exact source-owned removals, never inferred from prospective native paths."""
    stage = state.get('owned_result_stages', {})
    return {str(row['id']).upper() for scope in stage.get('replacements', []) for row in scope['rows']} | {
        str(row['id']).upper() for profile in stage.get('lists', []) if profile.get('mode') == 'replaceAll'
        for row in profile['before']}


def capture_created_field_metadata(node: Mapping[str, Any], object_id: str, *, read: Any) -> list[dict[str, Any]]:
    """Retain optional exact-object facts without changing source-write verification."""
    from .operation_registry import OperationContractError
    fields = ordinary_creation_fields(node)
    if not fields:
        return []
    records = []
    requests = [("ak.wwise.core.object.getPropertyAndReferenceNames", {"object": object_id}),
        *(("ak.wwise.core.object.getPropertyInfo", {"object": object_id, "property": item["name"]}) for item in fields)]
    for uri, args in requests:
        record = {"role": "created-root-history-field-metadata", "request_path": node["request_path"],
            "uri": uri, "args": args, "options": {}}
        records.append(record)
        try:
            record["result"] = read(uri, args, {})
        except OperationContractError as exc:
            if exc.error_code not in {"READBACK_FAILED", "INVALID_READBACK", "RESULT_TOO_LARGE"}:
                raise
            record["error"] = exc.as_dict()
            break
    return records


def verified_created_root_identity(verification: Mapping[str, Any]) -> dict[str, str] | None:
    """Use the verifier's structured identity witness, even if a field failed."""
    witnesses = [row.get("evidence") for row in verification.get("assertions", [])
                 if isinstance(row, Mapping) and row.get("kind") == "verified_created_root_identity"
                 and row.get("passed") is True]
    if len(witnesses) != 1 or not isinstance(witnesses[0], Mapping):
        return None
    try:
        value = normalize_live_object_identity(witnesses[0])
    except ValueError:
        return None
    return {"id": value.object_id, "name": value.name, "type": value.object_type, "path": value.path}


def verified_created_objects(verification):
    """Project independently verified occurrences without merging native results."""
    from copy import deepcopy
    if verification.get("business_state_verified") is not True:
        return []
    return [{**deepcopy(row["evidence"]),
        **({"compound_child_index": row["compound_child_index"]} if "compound_child_index" in row else {})}
        for row in verification.get("assertions", [])
        if row.get("kind") in {"verified_created_node_identity", "verified_created_list_member_identity"} and row.get("passed") is True]


def verified_created_occurrence_identity(verification, result_handle):
    """Select one sealed ordinary creation witness, never a changed existing node."""
    rows = [row for row in verified_created_objects(verification)
        if row.get('result_handle') == result_handle and 'parent_id' in row
        and 'owner_id' not in row and 'compound_child_index' not in row]
    if len(rows) != 1 or type(rows[0].get('class_id')) is not int:
        return None
    try:
        identity = normalize_live_object_identity({**rows[0]['object'], 'classId': rows[0]['class_id']})
    except (ValueError, KeyError, TypeError):
        return None
    return {'id': identity.object_id, 'name': identity.name, 'type': identity.object_type, 'path': identity.path, 'classId': rows[0]['class_id']}
