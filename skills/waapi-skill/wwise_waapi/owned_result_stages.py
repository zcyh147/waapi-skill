"""Bound native creation results before dependent ordinary scalar references.

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


def native_node(args, path):
    import re
    node = args
    for key, index in re.findall(r'\.(objects|children)\[(\d+)\]', path):
        node = node[key][int(index)]
    return node


def prepare(uri, args, options, specs, context, version, *, force=False, root_parent=None, parent_children=()):
    if not force and (not context or not context.get('renames')):
        return None
    if force and not any(not node.get('existing_target') for node in specs):
        return None
    if uri not in {SET, CREATE} or uri == SET and version == '2021.1':
        raise ValueError('Owned ordinary creation requires its pinned native constructor')
    if (not specs or len(specs) > DEFAULT_MAX_NODES or any(
            node.get('collection') not in {None, 'children'} or node.get('preexisting_id') is not None
            or node.get('list_request_paths') or node.get('list_snapshots') or node.get('import_requested')
            or node.get('requested_language') or node.get('graph_plugin_native') or node.get('rtpc_binding')
            or any('array' in field or 'curve' in field for field in node.get('references', []))
            for node in specs)):
        raise ValueError('Native-name staging needs the complete ordinary new-child graph; richer alternatives remain #178/#192 obligations')
    deferred = [{'source': node['request_path'], 'field': field['name'], 'target': field['target_request_path'],
                 'platform': node.get('platform', args.get('platform'))}
        for node in specs for field in node.get('references', []) if 'target_request_path' in field]
    if len(deferred) > DEFAULT_MAX_NODES:
        raise ValueError('Native-name staging requires bounded ordinary result-reference dependencies')
    by_path = {node['request_path']: node for node in specs}
    for node in specs:
        if node.get('existing_target') and (node.get('requested_name') != node.get('original_name')
                or node.get('notes_supplied') or node.get('properties')
                or any('target_request_path' not in ref for ref in node.get('references', []))):
            raise ValueError('Existing field edits plus native-name creation need a separate declared child; this stage retains existing roots')
        children = [child for child in specs if child.get('parent_request_path') == node['request_path']]
        if node.get('existing_target') and len(children) > 1:
            raise ValueError('Native-name association currently needs one new child per retained parent; multi-collision alternatives remain #178/#192')
        if len({child['requested_name'].casefold() for child in children}) != len(children):
            raise ValueError('Fresh-parent siblings require distinct exact declared names')
        if not node.get('existing_target') and node.get('parent_request_path') not in by_path and not (uri == CREATE and node['request_path'] == '$'):
            raise ValueError('Every staged new occurrence needs its declared parent association')
    creation = deepcopy(args)
    for field in deferred:
        del native_node(creation, field['source'])['@' + field['field']]
    return {'kind': KIND, 'version': version, 'uri': uri, 'creation_args': creation,
            'options': deepcopy(options), 'deferred': deferred,
            'prospective_paths': prospective_paths(specs, root_parent=root_parent),
            **({'parent_before': dict(root_parent), 'parent_children': list(parent_children), 'parent_id': args['parent']} if uri == CREATE else {})}


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
            paths[path] = paths[node['parent_request_path']] + '\\' + node['requested_name']
    return paths


def bind(prepared, result, *, read):
    """Prove every actual returned occurrence and complete direct membership."""
    from .operation_registry import _same_identity, _object_type_matches
    specs = prepared['verification_plan']['nodes']
    plan = prepared['pre_state']['owned_result_stages']
    by_path = {node['request_path']: node for node in specs}
    returned = flatten_create_result(result) if plan['uri'] == CREATE else flatten_set_result(result)
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
            matches = children if spec.get('existing_target') else [candidate for candidate in children
                if candidate['requested_name'] == child.name]
            if len(matches) != 1:
                raise ValueError('Native result cannot uniquely associate this child declaration')
            bind_occurrence(child, matches[0])
    for node in returned:
        if node.parent_request_path is None:
            matches = ([by_path['$']] if plan['uri'] == CREATE else [spec for spec in specs if spec.get('existing_target') and _same_identity(spec.get('target_id'), node.object)])
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
    def observe(args):
        payload = retained(GET, args, {'return': FIELDS})
        rows = payload.get('return') if isinstance(payload, Mapping) else None
        if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
            raise ValueError('Owned result observation requires a complete bounded row set')
        return rows
    all_before = {str(row['id']).upper() for node in specs for row in node.get('preexisting_children', [])}
    all_before.update(str(node['target_id']).upper() for node in specs if node.get('existing_target'))
    if plan['uri'] == CREATE:
        all_before.update(str(row['id']).upper() for row in plan['parent_children'])
        all_before.add(plan['parent_id'].upper())
    for path, spec in by_path.items():
        returned = bound.get(path)
        object_id = spec.get('target_id') if spec.get('existing_target') else returned.object if returned else None
        rows = observe({'from': {'id': [object_id]}})
        if len(rows) != 1 or not _same_identity(rows[0].get('id'), object_id):
            raise ValueError('Actual returned GUID must resolve exactly once')
        row = rows[0]
        if not spec.get('existing_target'):
            if (str(object_id).upper() in all_before or not returned or row.get('name') != returned.name
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
            edge = row.get('parent')
            if (not _same_identity(edge.get('id') if isinstance(edge, Mapping) else edge, parent['id'])
                    or row.get('path') != parent['path'] + '\\' + row['name']):
                raise ValueError('Actual created occurrence parent/path does not match declared topology')
        children = [identities[child['request_path']]['id'].upper() for child in specs if child.get('parent_request_path') == path]
        expected = {str(child['id']).upper() for child in spec.get('preexisting_children', [])} | set(children)
        rows = observe({'from': {'id': [row['id']]}, 'transform': [{'select': ['children']}]})
        actual = [str(child.get('id')).upper() for child in rows]
        if len(actual) != len(set(actual)) or set(actual) != expected:
            raise ValueError('Actual parent membership differs from complete sealed and returned GUID roster')
    from .operation_registry import _read_property_info
    context = prepared['pre_state'].get('planned_reference_context') or {'metadata': []}
    for field in plan['deferred']:
        source = by_path[field['source']]
        metadata = [row['metadata'] for row in context['metadata'] if row['name'] == field['field']
            and (row.get('class_id') == source['class_id'] or isinstance(row.get('object_id'), str) and _same_identity(row['object_id'], source.get('target_id')))]
        actual = _read_property_info(retained, object_id=identities[field['source']]['id'], name=field['field'])
        if not metadata or any(actual.as_dict() != row for row in metadata):
            raise ValueError('Actual created receiver field metadata differs from its sealed class/field authority')
    return identities, records


def reference_args(plan, identities):
    rows = []
    for field in plan['deferred']:
        source, target = identities[field['source']], identities[field['target']]
        row = next((row for row in rows if row['object'] == source['id'] and row.get('platform') == field['platform']), None)
        if row is None:
            row = {'object': source['id'], **({'platform': field['platform']} if field['platform'] is not None else {})}
            rows.append(row)
        row['@' + field['field']] = target['path']
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


def validate(prepared, execution, *, context=None):
    """Rebuild the association solely from retained actual native/read evidence."""
    from .builders.schema import validate_semantic_payload, validate_semantic_result
    plan = prepared['pre_state']['owned_result_stages']
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
        preserved_reads.extend([record, record['membership']])
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
    for rename in (prepared['pre_state'].get('planned_reference_context') or {}).get('renames', []):
        for snapshot in rename['collision_state']:
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
    for before, children in preservation_rows(prepared):
        expected = project_compound_snapshot(before, context)
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
        passed = passed and isinstance(found, list) and len(ids) == len(set(ids)) and set(ids) == set(children) | set(created)
        records.append({'role': 'owned-result-preservation', 'object_id': before['id'], 'passed': bool(passed),
            'uri': GET, 'args': args, 'options': options, 'result': payload,
            'membership': {'uri': GET, 'args': child_args, 'options': {'return': ['id']}, 'result': membership}})
    return records
