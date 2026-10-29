"""Closed, bounded discovery of ordinary Authoring layouts and views.

Native layout documents are observations, never accepted as mutation requests.
The pinned definitions retain their source spelling and contradictions; this
read lane reports them without silently rewriting native schema semantics.
"""
from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from .canonical import canonical_sha256

LAYOUT_VERSIONS = ('2024.1', '2025.1')
LAYOUT_READS = {
    'names': 'ak.wwise.ui.layout.getLayoutNames',
    'current': 'ak.wwise.ui.layout.getCurrentLayoutName',
    'contents': 'ak.wwise.ui.layout.getLayout',
    'instances': 'ak.wwise.ui.layout.getViewInstances',
    'types': 'ak.wwise.ui.layout.getViewTypes',
    'rectangle': 'ak.wwise.ui.layout.getElementRectangle',
    'frontend': 'ak.wwise.ui.layout.getViewHandle',
}
LAYOUT_READ_URIS = frozenset(LAYOUT_READS.values())
MAX_LAYOUT_RESULT_BYTES = 256 * 1024
MAX_LAYOUT_ROWS = 1024
FILENAME = 'authoring-layout-read-supplement.json'
PINNED_SHA256: dict[str, str] = {'2024.1': 'b908f2ce9c4cff713bff4d3b6fb1644bacb2ff023e4527a8248eecdd1ad9ee66', '2025.1': 'b40bce2f7e506c420de3e26cefd57b5f92585e2af49d7e80ed7a0fecec027dfb'}
_GUID = re.compile(r'^\{[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}\}$')


def load_layout_read_evidence(root: Path, version: str) -> dict[str, Any]:
    """Exact retained native schemas/definitions, without normalizing their semantics."""
    payload = json.loads((root / version / FILENAME).read_text(encoding='utf-8'))
    if (canonical_sha256(payload) != PINNED_SHA256[version]
            or payload.get('version') != version or payload.get('host') != 'wwise-authoring'
            or set(payload.get('schemas', {})) != LAYOUT_READ_URIS):
        raise ValueError('Authoring layout read evidence identity or digest mismatch')
    return payload


def merge_authoring_layout_reads(manifest: Mapping[str, Any], *, root: Path | None, version: str) -> dict[str, Any]:
    result = deepcopy(dict(manifest))
    if version not in LAYOUT_VERSIONS:
        return result
    if root is None:
        raise ValueError('Authoring layout reads require pinned resources')
    payload = load_layout_read_evidence(root, version)
    existing = {row['uri'] for row in result['functions']}
    for uri, schema in sorted(payload['schemas'].items()):
        if uri in existing:
            raise ValueError('Authoring layout supplement cannot replace an existing route')
        result['functions'].append({'uri': uri, 'description': schema['description'], 'host_surface': 'wwise-authoring'})
        result['schemas'].append({'uri': uri, 'status': 'ok', 'schema': schema})
    result['functions'].sort(key=lambda row: row['uri'])
    result['schemas'].sort(key=lambda row: row['uri'])
    result.setdefault('metadata', {})['authoring_layout_read_evidence'] = {
        'build': payload['build'], 'sha256': PINNED_SHA256[version],
        'native_catalog_sha256': payload['native_catalog_sha256'],
    }
    return result


def layout_read_contract(version: str, uri: str) -> dict[str, Any]:
    if version not in LAYOUT_VERSIONS or uri not in LAYOUT_READ_URIS:
        raise ValueError('Layout discovery is absent from the exact 2021.1–2023.1 native catalogs; this route requires 2024.1 or 2025.1 Authoring')
    subject = next(key for key, value in LAYOUT_READS.items() if value == uri)
    named = subject in {'contents', 'instances'}
    scoped = subject in {'rectangle', 'frontend'}
    contract = {
        'contract': 'waapi-skill.layout-read/v1', 'command': 'request-schema',
        'ok': True, 'status': 'ok', 'offline': True, 'version': version, 'api': uri,
        'input_mode': 'bounded_business_read', 'host_surface': 'wwise-authoring',
        'result_scope': {'names': 'factory_layout_names', 'current': 'current_layout_name',
                         'contents': 'bounded_native_document_with_unresolved_definition_semantics',
                         'instances': 'layout_view_instances', 'types': 'currently_registered_view_types',
                         'rectangle': 'allocated_element_rectangle', 'frontend': 'instantiated_view_frontend_handles'}[subject],
        'continuation': {'gateway_argv': ['layout-read', subject],
                         'append': ['--layout-name <exact-discovered-layout-name>'] if named else []},
        'business_fields': {'layout_name': {'type': 'string', 'max_utf8_bytes': 4096,
                            'empty_allowed': True}} if named else {},
        'safety': {'read_only': True, 'native_request_input': 'forbidden',
                   'live_host_detection': True, 'mutation_identity_authority': False},
        'limits': {'timeout_seconds': 10, 'result_bytes': MAX_LAYOUT_RESULT_BYTES,
                   'rows': MAX_LAYOUT_ROWS, 'nesting_depth': 32, 'nodes': 32768},
    }
    if scoped:
        field = 'element_handle' if subject == 'rectangle' else 'view_handle'
        contract['business_fields'] = {field: {'type': 'string', 'pattern': '^lh1-[0-9a-f]{32}$',
                                               'authority': 'Gateway-issued scoped identity'}}
        contract['continuation']['append'] = ['--' + field.replace('_', '-') + ' <discovered-handle>']
        contract['identity_discovery'] = {'gateway_argv': ['layout-inspect'],
            'append': ['--layout-name <exact-discovered-layout-name>'],
            'expires_after_seconds': 900,
            'live_session_project_and_configuration_bound': True}
    return contract


def layout_catalog_rows() -> tuple[dict[str, Any], ...]:
    return tuple({'api': uri, 'intent': subject,
                  'supported_versions': list(LAYOUT_VERSIONS)}
                 for subject, uri in LAYOUT_READS.items())


def layout_read_arguments(subject: str, name: str | None, native_id: str | None = None) -> dict[str, Any]:
    if subject not in LAYOUT_READS:
        raise ValueError('Unknown layout observation')
    if subject in {'rectangle', 'frontend'}:
        if name is not None or not isinstance(native_id, str) or not native_id:
            raise ValueError('Scoped layout reads require their discovered identity handle')
        return {'id' if subject == 'rectangle' else 'viewID': native_id}
    if subject in {'contents', 'instances'}:
        if not isinstance(name, str) or '\x00' in name or len(name.encode('utf-8')) > 4096:
            raise ValueError('layout contents/instances require --layout-name with an exact bounded name')
        return {'name': name}
    if name is not None:
        raise ValueError('--layout-name is accepted only for contents and instances')
    return {}


def validate_layout_read_result(subject: str, result: Any) -> dict[str, Any]:
    """Validate the business observation without pretending broken schemas prove arrangements."""
    nodes = 0
    def bounded(value: Any, depth: int = 0) -> None:
        nonlocal nodes
        nodes += 1
        if depth > 32 or nodes > 32768:
            raise ValueError('layout result exceeds the bounded nesting/node budget')
        if isinstance(value, dict):
            if not all(isinstance(key, str) for key in value):
                raise ValueError('layout result keys must be strings')
            for child in value.values(): bounded(child, depth + 1)
        elif isinstance(value, list):
            if len(value) > MAX_LAYOUT_ROWS:
                raise ValueError('layout result exceeds the row ceiling; no partial result is accepted')
            for child in value: bounded(child, depth + 1)
        elif value is not None and not isinstance(value, (str, bool, int, float)):
            raise ValueError('layout result must be strict JSON')
        elif isinstance(value, float) and not math.isfinite(value):
            raise ValueError('layout result numbers must be finite')
    bounded(result)
    if subject == 'frontend':
        if not isinstance(result, list) or any(not isinstance(row, str) or not _GUID.fullmatch(row) for row in result):
            raise ValueError('view frontend handles must be a bounded GUID array')
        return {'kind': 'bounded_native_observation', 'business_arrangement_verified': False,
                'native_schema_status': 'closed_result_validated', 'native_definition_issues': []}
    if not isinstance(result, dict):
        raise ValueError('layout result must be a JSON object')
    if subject == 'rectangle':
        if not set(result) <= {'left', 'top', 'right', 'bottom'} or any(type(v) not in (int, float) for v in result.values()):
            raise ValueError('element rectangle accepts only finite numeric edges')
        return {'kind': 'bounded_native_observation', 'business_arrangement_verified': False,
                'native_schema_status': 'closed_result_validated', 'native_definition_issues': []}
    key = {'names': 'layouts', 'current': 'name', 'contents': 'Layout',
           'instances': 'viewInstances', 'types': 'viewTypes'}[subject]
    if not result:
        return {'kind': 'bounded_native_observation', 'business_arrangement_verified': False,
                'native_schema_status': 'optional_result_field_omitted', 'native_definition_issues': []}
    if set(result) != {key}:
        raise ValueError(f'layout result accepts only optional {key}')
    value = result[key]
    if subject == 'current':
        if not isinstance(value, str): raise ValueError('current layout name must be a string')
    elif subject == 'contents':
        if not isinstance(value, dict) or not isinstance(value.get('Name'), str):
            raise ValueError('layout contents require a Layout object with its Name')
    else:
        if not isinstance(value, list): raise ValueError(f'{key} must be an array')
        for row in value:
            if subject == 'names':
                if not isinstance(row, str): raise ValueError('layout names must be strings')
            else:
                fields = {'viewName', 'viewDisplayName'}
                if subject == 'instances': fields |= {'viewID', 'viewIsDocked'}
                if not isinstance(row, dict) or not set(row) <= fields:
                    raise ValueError(f'{key} row accepts only {sorted(fields)}')
                if not all(isinstance(row[field], str) for field in ('viewName', 'viewDisplayName') if field in row):
                    raise ValueError('view type/display names must be strings')
                if subject == 'instances' and (('viewID' in row and (not isinstance(row['viewID'], str)
                        or not _GUID.fullmatch(row['viewID'])))
                        or ('viewIsDocked' in row and type(row['viewIsDocked']) is not bool)):
                    raise ValueError('view instance requires a GUID and Boolean docking state')
    return {'kind': 'bounded_native_observation', 'business_arrangement_verified': False,
            'native_schema_status': 'definition_semantics_unresolved' if subject == 'contents' else 'closed_result_validated',
            'native_definition_issues': [
                {'pointer': '/definitions/Element/OneOf', 'issue': 'native capital OneOf is not silently normalized'},
                {'pointer': '/definitions/Splitter', 'issue': 'required @Children absent from properties with additionalProperties false'},
                {'pointer': '/definitions/ViewHolder', 'issue': 'ViewHolder tag conflicts with allOf Element alternatives'},
            ] if subject == 'contents' else []}


def layout_identity_rows(layout: Mapping[str, Any], instances: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Project only native-observed identity authority; exact duplicate view rows coalesce."""
    elements: dict[str, dict[str, Any]] = {}
    def walk(value: Any, pointer: str) -> None:
        if isinstance(value, dict):
            native_id = value.get('ID')
            kind = value.get('@type') or ('StackPanel' if pointer == '/Layout/StackPanel' else None)
            if isinstance(native_id, str) and native_id and kind in {'StackPanel', 'View', 'Splitter', 'ObjectPanel', 'ObjectTabPanel', 'ViewHolder'}:
                row = {'kind': kind, 'native_id': native_id, 'observation': value, 'location': pointer}
                key = native_id.lower() if _GUID.fullmatch(native_id) else native_id
                previous = elements.get(key)
                if previous is not None and (previous['kind'] != kind or previous['observation'] != value):
                    raise ValueError('Conflicting duplicate element identity; no handles issued')
                elements[key] = row
            for key in ('Layout', 'StackPanel', 'Undocked', '@Children'):
                if key in value: walk(value[key], pointer + '/' + key)
        elif isinstance(value, list):
            for index, child in enumerate(value): walk(child, pointer + '/' + str(index))
    walk(layout, '')
    views: dict[str, dict[str, Any]] = {}
    if not isinstance(instances.get('viewInstances'), list):
        raise ValueError('Native view instances were omitted; no identity handles can be issued')
    for row in instances['viewInstances']:
        native_id = row.get('viewID')
        if native_id is None:
            continue
        key = native_id.lower()
        previous = views.get(key)
        if previous is not None and previous['observation'] != row:
            raise ValueError('Conflicting duplicate view identity; no handles issued')
        views[key] = {'kind': row.get('viewName'), 'native_id': native_id, 'observation': row}
    return list(elements.values()), list(views.values())
