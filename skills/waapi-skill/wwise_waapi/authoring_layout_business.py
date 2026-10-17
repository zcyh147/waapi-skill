"""Closed Authoring layout business declarations and live-state guards."""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import re
import time
from typing import Any, Mapping

from .authoring_layout import LAYOUT_VERSIONS, validate_layout_read_result
from .canonical import canonical_sha256

LAYOUT_SWITCH_URI = 'ak.wwise.ui.layout.switchLayout'
LAYOUT_SET_URI = 'ak.wwise.ui.layout.setLayout'
LAYOUT_REMOVE_URI = 'ak.wwise.ui.layout.removeLayout'
LAYOUT_MUTATION_URIS = frozenset({LAYOUT_SWITCH_URI, LAYOUT_SET_URI, LAYOUT_REMOVE_URI})
MUTATION_RESOURCE = 'authoring-layout-mutation-supplement.json'
MUTATION_SHA256: dict[str, str] = {'2024.1': '686880fd7c21a9e473e140166cd9dc55f936d53b179c2e8a34447848c6eee632', '2025.1': '38bb690fe9de967d90047d3488b07a731d704e57282973a4fa409d4787196a78'}


def layout_business_contract_data(operation: str, version: str) -> dict[str, Any]:
    if version not in LAYOUT_VERSIONS or operation not in LAYOUT_MUTATION_URIS:
        raise ValueError('Layout mutation requires the exact supported 2024.1/2025.1 Authoring lane')
    result = {'contract': 'waapi-skill.authoring-layout-business/v1', 'operation': operation,
        'version': version, 'input_mode': 'business_declaration', 'execution_shape': 'transaction',
        'start': {'subcommand': 'draft-start', 'gateway_argv': ['draft-start', operation],
                  'copy_exactly': True, 'append_arguments': 'forbidden'},
        'binding': {'available': False, 'roles': [], 'role_required': False,
                    'identity_discovery': ['layout-inspect', '--layout-name', '<observed-layout-name>']},
        'declaration': {'subcommand': 'draft-declare-layout-plan', 'settings_field': 'authoring_layout_plan',
            'submit_once': True, 'required_fields': ['layout_handle'], 'optional_fields': [],
            'public_fields': ['layout_handle'], 'field_types': {'layout_handle': 'scoped_layout_handle'},
            'input_forms': {'layout_handle': {'gateway_flag': '--layout-handle', 'shape': 'scalar'}}},
        'responsibility_split': {'agent': ['choose the discovered layout'],
            'gateway': ['resolve scoped identity', 'construct native request', 'revalidate live session and layout',
                        'switch once after authorization', 'verify current layout independently']},
        'gateway_derivations': ['native name from session-bound handle', 'native request envelope', 'current-layout verifier'],
        'legacy_typed_call_public': False, 'legacy_native_request_public': False,
        'safety': {'immutable_preview': True, 'single_execute': True, 'authoring_host_required': True,
                   'native_request_fields': 'gateway_owned', 'automatic_retry': False},
        'verifier': {'kind': 'authoring-layout-state', 'observation': 'independent current layout name'}}
    if operation == LAYOUT_SET_URI:
        result['declaration']['required_fields'].append('new_layout_name')
        result['declaration']['public_fields'].append('new_layout_name')
        result['declaration']['field_types']['new_layout_name'] = 'new_temporary_layout_name'
        result['declaration']['input_forms']['new_layout_name'] = {'gateway_flag': '--new-layout-name', 'shape': 'scalar'}
        result['responsibility_split']['agent'] = ['choose a new temporary layout name and discovered anchor layout']
        result['responsibility_split']['gateway'] = ['prove exact target absence', 'construct empty layout declaration',
            'bind to the discovered Authoring session', 'register once after authorization', 'read back the registered layout']
        result['verifier'] = {'kind': 'authoring-layout-state', 'observation': 'independent exact registered layout readback'}
    elif operation == LAYOUT_REMOVE_URI:
        result['responsibility_split']['agent'] = ['choose the discovered temporary layout to unregister']
        result['responsibility_split']['gateway'] = ['revalidate temporary layout identity', 'reject factory layouts',
            'unregister once after authorization', 'verify exact missing-layout native observation']
        result['verifier'] = {'kind': 'authoring-layout-state', 'observation': 'exact native missing-name error after unregister'}
    return result


def layout_business_catalog_rows() -> tuple[dict[str, Any], ...]:
    return tuple({'api': uri, 'intent': {LAYOUT_SWITCH_URI: 'switch layout', LAYOUT_SET_URI: 'register temporary layout', LAYOUT_REMOVE_URI: 'remove temporary layout'}[uri],
                  'supported_versions': list(LAYOUT_VERSIONS)} for uri in sorted(LAYOUT_MUTATION_URIS))


def merge_layout_mutations(manifest: Mapping[str, Any], *, root: Path | None, version: str) -> dict[str, Any]:
    result = deepcopy(dict(manifest))
    if version not in LAYOUT_VERSIONS:
        return result
    if root is None:
        raise ValueError('Authoring layout mutations require pinned resources')
    payload = json.loads((root / version / MUTATION_RESOURCE).read_text(encoding='utf-8'))
    if canonical_sha256(payload) != MUTATION_SHA256[version] or payload.get('version') != version or set(payload.get('schemas', {})) != LAYOUT_MUTATION_URIS:
        raise ValueError('Authoring layout mutation source identity/digest mismatch')
    known = {row['uri'] for row in result['functions']}
    for uri, schema in sorted(payload['schemas'].items()):
        if uri in known:
            raise ValueError('Authoring layout mutation supplement cannot replace a route')
        result['functions'].append({'uri': uri, 'description': schema['description'], 'host_surface': 'wwise-authoring'})
        result['schemas'].append({'uri': uri, 'status': 'ok', 'schema': schema})
    result['functions'].sort(key=lambda row: row['uri'])
    result['schemas'].sort(key=lambda row: row['uri'])
    return result


def layout_binding_descriptor(record: Mapping[str, Any], *, registration_name: str | None = None) -> dict[str, Any]:
    body = {key: record[key] for key in ('handle', 'context', 'layout_name', 'role', 'native_id', 'expires_at')}
    body['observation_sha256'] = canonical_sha256(record['observation'])
    if registration_name is not None:
        body['registration_name'] = validate_new_layout_name(registration_name)
    return {**body, 'binding_sha256': canonical_sha256(body)}


def validate_layout_binding(binding: Any) -> dict[str, Any]:
    expected = {'handle', 'context', 'layout_name', 'role', 'native_id', 'expires_at', 'observation_sha256', 'binding_sha256'}
    if not isinstance(binding, Mapping) or set(binding) not in (expected, expected | {'registration_name'}):
        raise ValueError('Layout mutation lacks an exact Gateway-owned identity binding')
    body = dict(binding)
    digest = body.pop('binding_sha256')
    if canonical_sha256(body) != digest or body['role'] != 'layout' or body['native_id'] != body['layout_name']:
        raise ValueError('Layout mutation identity binding is malformed')
    if not isinstance(body['context'], Mapping) or not isinstance(body['layout_name'], str):
        raise ValueError('Layout mutation identity binding context is malformed')
    context = body['context']
    session = context.get('session')
    if (set(context) != {'configuration', 'project_path', 'session'}
            or not isinstance(context['configuration'], Mapping)
            or not isinstance(context['project_path'], str)
            or not isinstance(session, Mapping)
            or set(session) != {'endpoint', 'process_id', 'project_id', 'resource_digest', 'schema_version', 'session_id', 'wwise_build'}
            or any(not isinstance(session[key], str) or not session[key] for key in
                   ('endpoint', 'project_id', 'resource_digest', 'schema_version', 'session_id', 'wwise_build'))
            or type(session['process_id']) is not int or session['process_id'] <= 0
            or not re.fullmatch(r'lh1-[0-9a-f]{32}', str(body['handle']))
            or not re.fullmatch(r'[0-9a-f]{64}', str(body['observation_sha256']))
            or not body['layout_name'] or '\x00' in body['layout_name']
            or len(body['layout_name'].encode('utf-8')) > 4096
            or type(body['expires_at']) not in (int, float) or not math.isfinite(body['expires_at'])):
        raise ValueError('Layout mutation identity binding fields are malformed')
    if 'registration_name' in body:
        validate_new_layout_name(body['registration_name'])
    return dict(binding)


def materialize_layout_business_request(operation: str, session: Any) -> Mapping[str, Any]:
    from .operation_registry import parse_operation_request
    contract = layout_business_contract_data(operation, session.context.wwise_version)
    if set(session.settings) != {'authoring_layout_plan', 'authoring_layout_binding'}:
        raise ValueError('Submit the complete disclosed layout business plan')
    plan = session.settings['authoring_layout_plan']
    binding = validate_layout_binding(session.settings['authoring_layout_binding'])
    if not isinstance(plan, Mapping) or set(plan) != set(contract['declaration']['public_fields']) or plan['layout_handle'] != binding['handle']:
        raise ValueError('Layout plan requires the exact discovered layout handle')
    native_args = {'name': binding['layout_name']}
    if operation == LAYOUT_SET_URI:
        name = validate_new_layout_name(plan['new_layout_name'])
        if name != binding.get('registration_name'):
            raise ValueError('New layout name differs from the Gateway-owned declaration binding')
        native_args = {'name': name, 'layout': {'Layout': {'Name': name}}}
    request = {'contract': 'waapi-skill.operation-request/v1', 'version': session.context.wwise_version,
        'operation': 'waapi.call', 'arguments': {'api': operation, 'args': native_args,
            'options': {}, 'layout_binding': binding}}
    parse_operation_request(request, expected_version=session.context.wwise_version)
    return request


def validate_layout_call(version: str, api: str, args: Mapping[str, Any], options: Mapping[str, Any], binding: Any) -> dict[str, Any]:
    layout_business_contract_data(api, version)
    verified = validate_layout_binding(binding)
    expected = {'name': verified['layout_name']}
    if api == LAYOUT_SET_URI:
        name = validate_new_layout_name(verified.get('registration_name'))
        expected = {'name': name, 'layout': {'Layout': {'Name': name}}}
    if dict(args) != expected or options:
        raise ValueError('Layout native request differs from the Gateway-owned business binding')
    return verified


def validate_new_layout_name(name: Any) -> str:
    if not isinstance(name, str) or not name or '\x00' in name or len(name.encode('utf-8')) > 4096:
        raise ValueError('A new temporary layout requires an exact nonempty bounded name')
    return name


def require_layout_absence(name: str, *, read: Any) -> dict[str, Any]:
    """Only the exact native missing-name error proves layout absence."""
    from .operation_registry import OperationContractError
    uri = 'ak.wwise.ui.layout.getLayout'
    try:
        read(uri, {'name': name}, {})
    except OperationContractError as exc:
        call = exc.details.get('call') if isinstance(exc.details, Mapping) else None
        error = call.get('waapi_error_details') if isinstance(call, Mapping) else None
        details = error.get('details') if isinstance(error, Mapping) else None
        if (exc.error_code == 'READBACK_FAILED' and isinstance(call, Mapping) and call.get('api') == uri
                and call.get('waapi_error_uri') == 'ak.wwise.unavailable'
                and isinstance(details, Mapping) and details.get('procedureUri') == uri
                and error.get('message') == "Layout '" + name + "' could not be found."):
            # Evidence paths/timestamps change on every read; only exact native failure semantics
            # participate in immutable check-to-preview comparison.
            stable_error = {key: call[key] for key in ('api', 'error_code', 'waapi_error_uri', 'waapi_error_details')}
            return {'absent': True, 'name': name, 'uri': uri, 'native_error': stable_error}
        raise
    raise ValueError('A layout already exists under the requested registration name; overwrite is forbidden')


def require_temporary_layout(name: str, *, read: Any) -> Mapping[str, Any]:
    factory = read('ak.wwise.ui.layout.getLayoutNames', {}, {})
    validate_layout_read_result('names', factory)
    if 'layouts' not in factory or name in factory['layouts']:
        raise ValueError('Removing a factory layout is forbidden; require a freshly observed temporary layout')
    return factory


def validate_layout_live_binding(binding: Mapping[str, Any], *, read: Any) -> None:
    """Revalidate process/session/project and the exact observed layout on every phase."""
    context = binding['context']
    session = context['session']
    info = read('ak.wwise.core.getInfo', {}, {})
    project = read('ak.wwise.core.getProjectInfo', {}, {})
    version = info.get('version')
    if not isinstance(version, Mapping):
        raise ValueError('Live Authoring version is malformed')
    build = '.'.join(str(version.get(key)) for key in ('year', 'major', 'minor', 'build'))
    if (info.get('isCommandLine') is not False or info.get('processId') != session['process_id']
            or info.get('sessionId') != session['session_id'] or build != session['wwise_build']
            or str(version.get('schema')) != session['schema_version'] or project.get('id') != session['project_id']
            or project.get('path') != context['project_path']):
        raise ValueError('Authoring layout handle live session/process/build/project drifted')
    if not time.time() < binding['expires_at']:
        raise ValueError('Authoring layout identity binding expired; inspect and preview again')
    layout = read('ak.wwise.ui.layout.getLayout', {'name': binding['layout_name']}, {})
    validate_layout_read_result('contents', layout)
    if canonical_sha256(layout) != binding['observation_sha256']:
        raise ValueError('Authoring layout changed since discovery; inspect and preview again')
