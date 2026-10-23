"""Resolve finite condition source consumers without granting runtime evidence.

The frozen scalar plan remains unchanged. This separate source-only assessment
retains every original member and records declared inheritance, catalog identity
and the exact controller declaration available at each consumer.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import gzip
import hashlib
import json
import xml.etree.ElementTree as ET

from tests.maintenance.branch_coverage_audit import digest
from tests.support.condition_scalar_batch import scalar_manifest, scalar_plan

_SNAPSHOT = 'tests/fixtures/metadata-conditions/self-scalar-source-parents.json.gz'
_KINDS = {'WwiseObject': 0, 'InnerType': 0, 'EffectPlugin': 3,
          'SourcePlugin': 2, 'SinkPlugin': 7, 'ConversionPlugin': 1}


def _pointer(root, target):
    def visit(node, path):
        here = path + '/' + node.tag + ('[' + node.get('Name') + ']' if node.get('Name') else '')
        if node is target:
            return here
        for child in node:
            found = visit(child, here)
            if found:
                return found
        return None
    return visit(root, '').lstrip('/')


def _catalog_identity(node, catalog):
    try:
        class_id = (int(node.attrib['PluginID']) << 16) | (int(node.attrib['CompanyID']) << 4) | _KINDS[node.tag]
    except (KeyError, ValueError):
        return None
    matches = [row for row in catalog if row['classId'] == class_id]
    if len(matches) != 1:
        return None
    return deepcopy(matches[0])


def _scope(root, node):
    """Resolve exact direct ObjectBaseRef edges; conflicting fields stay visible."""
    bases = {}
    for item in root.findall('./ObjectBase'):
        bases.setdefault(item.get('Name'), []).append(item)
    nodes = []
    def walk(current, path):
        if current in path:
            raise ValueError('condition source inheritance cycle')
        for ref in current.findall('./ObjectBaseRef'):
            matches = bases.get(ref.get('Name'), [])
            if len(matches) != 1:
                raise ValueError('condition source base is missing or ambiguous')
            walk(matches[0], (*path, current))
        if current not in nodes:
            nodes.append(current)
    walk(node, ())
    fields = {}
    for item in nodes:
        for field in item.findall('./Properties/*'):
            if field.tag not in {'Property', 'Reference'}:
                continue
            fields.setdefault(field.get('Name'), []).append(field)
    return nodes, fields


def _controller(root, fields, name):
    matches = fields.get(name, [])
    if len(matches) != 1:
        return {'name': name, 'state': 'missing_source_declaration' if not matches else 'ambiguous_source_declaration',
                'source_pointers': [_pointer(root, n) for n in matches], 'source_only': True}
    node = matches[0]
    return {'name': name, 'type': node.get('Type'), 'state': 'declared',
            'source_pointer': _pointer(root, node), 'source_only': True,
            'declaration_sha256': hashlib.sha256(ET.tostring(node)).hexdigest()}


def reconcile_sources(root):
    """Return exact scalar source membership plus source-only consumer resolution."""
    manifest = scalar_manifest(root)
    raw = (root / _SNAPSHOT).read_bytes()
    snapshot = json.loads(gzip.decompress(raw))
    roots = {}
    for key, value in snapshot['files'].items():
        source = base64.b64decode(value['bytes_base64'], validate=True)
        if hashlib.sha256(source).hexdigest() != value['sha256']:
            raise ValueError('condition source snapshot changed')
        roots[key] = ET.fromstring(source)
    ownership = json.loads((root / 'docs/branch-coverage-ownership.json').read_bytes())['routes']
    catalogs = {version: json.loads((root / f'skills/waapi-skill/resources/metadata/{version}/object-types.json').read_bytes())['types']
                for version in sorted({c['version'] for c in manifest['occurrences']})}
    plan = scalar_plan(manifest)
    program_groups = {member['id']: group['id'] for group in plan['groups'] for member in group['members']}
    from tests.support.condition_mechanism_reuse import load_review
    review = load_review(root)
    scopes = {}
    rows = []
    for case in manifest['occurrences']:
        key = '|'.join((case['build'], case['corpus'], case['file']))
        source_root = roots[key]
        top_pointer = '/'.join(case['pointer'].split('/')[:2])
        top = next((n for n in source_root if _pointer(source_root, n) == top_pointer), None)
        if top is None:
            raise ValueError('condition source scope missing')
        inner = None
        if '/InnerTypes/InnerType[' in case['pointer']:
            inner = next((n for n in top.findall('./InnerTypes/InnerType')
                          if case['pointer'].startswith(_pointer(source_root, n) + '/')), None)
            if inner is None:
                raise ValueError('condition inner scope missing')
        candidates = [inner] if inner is not None else ([top] if top.tag != 'ObjectBase' else source_root.findall('./WwiseObject'))
        consumers = []
        for node in candidates:
            scope_key = (key, node)
            if scope_key not in scopes:
                scopes[scope_key] = _scope(source_root, node)
            lineage, fields = scopes[scope_key]
            if inner is None and top not in lineage:
                continue
            consumers.append({'source_pointer': _pointer(source_root, node),
                              'catalog': _catalog_identity(node, catalogs[case['version']]),
                              'source_lineage': [_pointer(source_root, n) for n in lineage],
                              'controller': _controller(source_root, fields, case['controller'])})
        row = {'occurrence_id': case['id'], 'version': case['version'], 'build': case['build'],
               'source_file': case['file'], 'source_pointer': case['pointer'],
               'source_file_sha256': snapshot['files'][key]['sha256'],
               'members': deepcopy(case['members']), 'predicate': deepcopy(case['predicate']),
               'field': case['receiver']['field'], 'consumers': consumers,
               'scope': 'inner-tool-record' if inner is not None else ('inherited-group' if case['receiver']['kind'] == 'inherited-base' else 'field'),
               'native_instance_effect': 'unobserved', 'coverage_credit': 'none'}
        selected_scope = inner if inner is not None else top
        row['source_fields'] = [{'name': n.get('Name'), 'kind': n.tag,
            'type': n.get('Type'), 'source_pointer': _pointer(source_root, n)}
            for n in selected_scope.findall('./Properties/*') if n.tag in {'Property', 'Reference'}]
        row['resolution'] = ('declared_group_without_selected_field'
            if row['scope'] == 'inherited-group' and not row['source_fields'] else
            'controller_source_unresolved' if any(c['controller']['state'] != 'declared' for c in consumers) else
            'source_consumer_resolved')
        if not consumers:
            row['resolution'] = 'source_consumer_unresolved'
        elif any(c['catalog'] is None for c in consumers):
            row['resolution'] = 'catalog_consumer_unresolved'
        row['condition_owner_issue'] = 177
        row['current_public_mechanism'] = {
            'operation': ('object.setProperty' if row['scope'] == 'field' and row['resolution'] == 'source_consumer_resolved' else None),
            'candidate_operation': 'object.setProperty',
            'construction': 'skills/waapi-skill/wwise_waapi/operation_registry.py#_apply_reference_activation_dependencies',
            'validation': 'skills/waapi-skill/wwise_waapi/metadata_restrictions.py#condition_restriction',
            'verifier': 'skills/waapi-skill/wwise_waapi/operation_registry.py#verify_prepared_operation',
            'source_linkage_only': True}
        row['original_program_groups'] = sorted({program_groups[m['id']] for m in row['members'] if m['id'] in program_groups})
        row['accepted_mechanism_review'] = (review['review_id'] if
            {m['id']: m['shape_sha256'] for m in row['members']} == review['selected_members'] else None)
        row['control_dependencies'] = []
        if inner is not None and inner.get('Name') == 'BatchRenameSettings':
            route = 'function|ak.wwise.ui.commands.execute'
            row['control_dependencies'] = [{
                'owner_issue': ownership[route]['owner_issue'], 'parent_issue': ownership[route]['parent_issue'],
                'route': route,
                'missing_fact': 'Addressable Batch Rename settings and the supported control/verification path; ShowBatchRename is only a retained command snapshot, not a setter or runtime allowlist.'}]
        if top.get('Name') == 'MusicPlaylistItem' and row['resolution'] == 'controller_source_unresolved':
            for route, missing in (
                ('function|ak.wwise.core.object.set', 'Exact MusicPlaylistItem addressability and supported existing List/object edit path.'),
                ('function|ak.wwise.core.object.getPropertyInfo', 'Actual scoped LoopCount/IsLoopingInfinite metadata; the matching source does not declare the controller.')):
                row['control_dependencies'].append({'owner_issue': ownership[route]['owner_issue'],
                    'parent_issue': ownership[route]['parent_issue'], 'route': route, 'missing_fact': missing})
        rows.append(row)
    return {'contract': 'waapi-skill.condition-source-resolution/v1',
            'scope': 'frozen_self_scalar_enable_source_members_only', 'whole_ticket_completion': False,
            'source_manifest_sha256': manifest['source_sha256'], 'snapshot_sha256': hashlib.sha256(raw).hexdigest(),
            'coverage_credit': 'none', 'occurrences': rows,
            'members_sha256': digest(sorted((m['id'], m['shape_sha256']) for r in rows for m in r['members']))}
