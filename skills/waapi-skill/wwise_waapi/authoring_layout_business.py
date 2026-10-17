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
LAYOUT_UNDOCK_URI = 'ak.wwise.ui.layout.undockView'
LAYOUT_CLOSE_URI = 'ak.wwise.ui.layout.closeView'
LAYOUT_GET_OR_CREATE_URI = 'ak.wwise.ui.layout.getOrCreateView'
LAYOUT_MUTATION_URIS = frozenset({LAYOUT_SWITCH_URI, LAYOUT_SET_URI, LAYOUT_REMOVE_URI, LAYOUT_GET_OR_CREATE_URI, LAYOUT_CLOSE_URI, LAYOUT_UNDOCK_URI})
MUTATION_RESOURCE = 'authoring-layout-mutation-supplement.json'
MUTATION_SHA256: dict[str, str] = {'2024.1': '9f2ec68caecb598ae96cbb6a46840046ea21871c942cf745dade7c86589aab20', '2025.1': '14c085f77d5c2c0cf6474733f7db15129446caf7eb46e7329c1916671dd65413'}


def layout_mutation_versions(operation: str) -> tuple[str, ...]:
    return ('2025.1',) if operation == LAYOUT_CLOSE_URI else LAYOUT_VERSIONS if operation in LAYOUT_MUTATION_URIS else ()


def layout_mutation_uris(version: str) -> frozenset[str]:
    return frozenset(uri for uri in LAYOUT_MUTATION_URIS if version in layout_mutation_versions(uri))


def layout_business_contract_data(operation: str, version: str) -> dict[str, Any]:
    if version not in layout_mutation_versions(operation):
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
    elif operation == LAYOUT_GET_OR_CREATE_URI:
        result['declaration']['required_fields'].append('view_type')
        result['declaration']['optional_fields'] = ['initial_x', 'initial_y']
        result['declaration']['public_fields'].extend(['view_type', 'initial_x', 'initial_y'])
        result['declaration']['field_types'].update(view_type='live_view_type_name', initial_x='integer', initial_y='integer')
        result['declaration']['input_forms'].update(view_type={'gateway_flag': '--view-type', 'shape': 'scalar'},
            initial_x={'gateway_flag': '--initial-x', 'shape': 'integer'}, initial_y={'gateway_flag': '--initial-y', 'shape': 'integer'})
        result['responsibility_split']['agent'] = ['choose a live view type and optional initial coordinates']
        result['responsibility_split']['gateway'] = ['require the selected layout to be current', 'validate the fresh live view type catalog',
            'preserve omitted coordinate fields', 'get or create once after authorization', 'verify the returned view identity and applicable initial coordinates']
        result['coordinate_scope'] = 'initial positions apply only to a newly created view; an existing view is reused'
        result['verifier'] = {'kind': 'authoring-layout-state', 'observation': 'independent view instances, plus explicit initial coordinate readbacks when created'}
    elif operation in {LAYOUT_CLOSE_URI, LAYOUT_UNDOCK_URI}:
        result['declaration']['required_fields'].append('view_handle')
        result['declaration']['public_fields'].append('view_handle')
        result['declaration']['field_types']['view_handle'] = 'scoped_view_handle'
        result['declaration']['input_forms']['view_handle'] = {'gateway_flag': '--view-handle', 'shape': 'scalar'}
        result['responsibility_split']['gateway'] = ['require the selected layout to be current', 'revalidate the exact discovered view',
            'request close once after authorization', 'poll bounded independent instances for exact disappearance']
        result['verifier'] = {'kind': 'authoring-layout-state', 'observation': 'exact view absent from independently read instances',
            'maximum_polls': 16, 'poll_interval_seconds': 0.2, 'incomplete_boundary': 'pending_async_close'}
        if operation == LAYOUT_UNDOCK_URI:
            result['declaration']['optional_fields'] = ['position_x', 'position_y']
            for field in ('position_x', 'position_y'):
                result['declaration']['public_fields'].append(field)
                result['declaration']['field_types'][field] = 'integer'
                result['declaration']['input_forms'][field] = {'gateway_flag': '--' + field.replace('_', '-'), 'shape': 'integer'}
            result['responsibility_split']['gateway'] = ['require the selected layout to be current', 'revalidate the exact discovered view',
                'preserve omitted positions', 'undock once after authorization', 'verify floating identity and explicit positions independently']
            result['verifier'] = {'kind': 'authoring-layout-state', 'observation': 'independent floating view identity and explicit position readbacks'}
    return result


def layout_business_catalog_rows() -> tuple[dict[str, Any], ...]:
    return tuple({'api': uri, 'intent': {LAYOUT_SWITCH_URI: 'switch layout', LAYOUT_SET_URI: 'register temporary layout', LAYOUT_REMOVE_URI: 'remove temporary layout', LAYOUT_GET_OR_CREATE_URI: 'get or create a live view', LAYOUT_CLOSE_URI: 'close a discovered view', LAYOUT_UNDOCK_URI: 'float a discovered view'}[uri],
                  'supported_versions': list(layout_mutation_versions(uri))} for uri in sorted(LAYOUT_MUTATION_URIS))


def merge_layout_mutations(manifest: Mapping[str, Any], *, root: Path | None, version: str) -> dict[str, Any]:
    result = deepcopy(dict(manifest))
    if version not in LAYOUT_VERSIONS:
        return result
    if root is None:
        raise ValueError('Authoring layout mutations require pinned resources')
    payload = json.loads((root / version / MUTATION_RESOURCE).read_text(encoding='utf-8'))
    if canonical_sha256(payload) != MUTATION_SHA256[version] or payload.get('version') != version or set(payload.get('schemas', {})) != layout_mutation_uris(version):
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


def layout_binding_descriptor(record: Mapping[str, Any], *, registration_name: str | None = None,
                              view_request: Mapping[str, Any] | None = None,
                              view_identity: Mapping[str, Any] | None = None,
                              position_request: Mapping[str, Any] | None = None) -> dict[str, Any]:
    body = {key: record[key] for key in ('handle', 'context', 'layout_name', 'role', 'native_id', 'expires_at')}
    body['observation_sha256'] = canonical_sha256(record['observation'])
    if registration_name is not None:
        body['registration_name'] = validate_new_layout_name(registration_name)
    if view_request is not None:
        native_view_request(view_request)
        body['view_request'] = dict(view_request)
    if view_identity is not None:
        body['view_identity'] = layout_binding_descriptor(view_identity)
    if position_request is not None:
        native_position_request(position_request)
        body['position_request'] = dict(position_request)
    return {**body, 'binding_sha256': canonical_sha256(body)}


def validate_layout_binding(binding: Any, *, role: str = 'layout') -> dict[str, Any]:
    expected = {'handle', 'context', 'layout_name', 'role', 'native_id', 'expires_at', 'observation_sha256', 'binding_sha256'}
    if not isinstance(binding, Mapping) or set(binding) not in (expected, expected | {'registration_name'}, expected | {'view_request'}, expected | {'view_identity'}, expected | {'view_identity', 'position_request'}):
        raise ValueError('Layout mutation lacks an exact Gateway-owned identity binding')
    body = dict(binding)
    digest = body.pop('binding_sha256')
    if (canonical_sha256(body) != digest or body['role'] != role
            or (role == 'layout' and body['native_id'] != body['layout_name'])
            or (role == 'view' and (set(binding) != expected or not re.fullmatch(
                r'\{[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\}', str(body['native_id']))))):
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
    if 'view_request' in body:
        native_view_request(body['view_request'])
    if 'position_request' in body:
        native_position_request(body['position_request'])
    if 'view_identity' in body:
        view = validate_layout_binding(body['view_identity'], role='view')
        if view['context'] != body['context'] or view['layout_name'] != body['layout_name']:
            raise ValueError('View and layout identities must share their exact live scope')
    return dict(binding)


def materialize_layout_business_request(operation: str, session: Any) -> Mapping[str, Any]:
    from .operation_registry import parse_operation_request
    contract = layout_business_contract_data(operation, session.context.wwise_version)
    if set(session.settings) != {'authoring_layout_plan', 'authoring_layout_binding'}:
        raise ValueError('Submit the complete disclosed layout business plan')
    plan = session.settings['authoring_layout_plan']
    binding = validate_layout_binding(session.settings['authoring_layout_binding'])
    if (not isinstance(plan, Mapping) or not set(contract['declaration']['required_fields']) <= set(plan)
            or not set(plan) <= set(contract['declaration']['public_fields']) or plan['layout_handle'] != binding['handle']):
        raise ValueError('Layout plan requires the exact discovered layout handle')
    native_args = {'name': binding['layout_name']}
    if operation == LAYOUT_SET_URI:
        name = validate_new_layout_name(plan['new_layout_name'])
        if name != binding.get('registration_name'):
            raise ValueError('New layout name differs from the Gateway-owned declaration binding')
        native_args = {'name': name, 'layout': {'Layout': {'Name': name}}}
    elif operation == LAYOUT_GET_OR_CREATE_URI:
        view_request = {key: value for key, value in plan.items() if key != 'layout_handle'}
        if binding.get('view_request') != view_request:
            raise ValueError('View declaration differs from its Gateway-owned binding')
        native_args = native_view_request(view_request)
    elif operation in {LAYOUT_CLOSE_URI, LAYOUT_UNDOCK_URI}:
        view = binding.get('view_identity', {})
        if plan['view_handle'] != view.get('handle'):
            raise ValueError('View declaration differs from its Gateway-owned discovered identity')
        native_args = {'viewID': view['native_id']}
        if operation == LAYOUT_UNDOCK_URI:
            position = {key: value for key, value in plan.items() if key not in {'layout_handle', 'view_handle'}}
            if position != binding.get('position_request'):
                raise ValueError('Floating position differs from its Gateway-owned declaration binding')
            native_args.update(name=binding['layout_name'], **native_position_request(position))
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
    elif api == LAYOUT_GET_OR_CREATE_URI:
        expected = native_view_request(verified.get('view_request'))
    elif api in {LAYOUT_CLOSE_URI, LAYOUT_UNDOCK_URI}:
        view = validate_layout_binding(verified.get('view_identity'), role='view')
        expected = {'viewID': view['native_id']}
        if api == LAYOUT_UNDOCK_URI:
            expected.update(name=verified['layout_name'], **native_position_request(verified.get('position_request')))
    if dict(args) != expected or options:
        raise ValueError('Layout native request differs from the Gateway-owned business binding')
    return verified


def validate_new_layout_name(name: Any) -> str:
    if not isinstance(name, str) or not name or '\x00' in name or len(name.encode('utf-8')) > 4096:
        raise ValueError('A new temporary layout requires an exact nonempty bounded name')
    return name


def native_position_request(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, Mapping) or not set(plan) <= {'position_x', 'position_y'}:
        raise ValueError('Floating placement accepts only the disclosed optional position choices')
    result = {}
    for field, native in (('position_x', 'posX'), ('position_y', 'posY')):
        if field in plan:
            if type(plan[field]) is not int:
                raise ValueError('Floating positions must be JSON integers')
            result[native] = plan[field]
    return result


def native_view_request(plan: Any) -> dict[str, Any]:
    if (not isinstance(plan, Mapping) or 'view_type' not in plan
            or not set(plan) <= {'view_type', 'initial_x', 'initial_y'}):
        raise ValueError('View creation requires one closed view type and optional initial coordinates')
    name = validate_new_layout_name(plan['view_type'])
    args = {'name': name}
    for field, native in (('initial_x', 'posX'), ('initial_y', 'posY')):
        if field in plan:
            if type(plan[field]) is not int:
                raise ValueError('View initial coordinates must be JSON integers')
            args[native] = plan[field]
    return args


def canonical_view_instances(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    validate_layout_read_result('instances', result)
    if 'viewInstances' not in result:
        raise ValueError('View instances were omitted; live view identity is unknown')
    by_id = {}
    for row in result['viewInstances']:
        identity, name = row.get('viewID'), row.get('viewName')
        if (not isinstance(identity, str) or not re.fullmatch(r'\{[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\}', identity)
                or not isinstance(name, str) or not name):
            raise ValueError('View instance lacks a complete native GUID/type identity')
        key = identity.upper()
        if key in by_id and by_id[key] != row:
            raise ValueError('Conflicting duplicate view identity cannot authorize a mutation')
        by_id[key] = dict(row)
    return [by_id[key] for key in sorted(by_id)]


def view_creation_observation(binding: Mapping[str, Any], *, read: Any) -> dict[str, Any]:
    requested_type = binding['view_request']['view_type']
    types = read('ak.wwise.ui.layout.getViewTypes', {}, {})
    validate_layout_read_result('types', types)
    matches = [row for row in types.get('viewTypes', []) if row.get('viewName') == requested_type]
    if not matches or any(row != matches[0] for row in matches):
        raise ValueError('The requested view type is not uniquely described by the fresh live view catalog')
    instances = canonical_view_instances(read('ak.wwise.ui.layout.getViewInstances', {'name': binding['layout_name']}, {}))
    return {'view_type': dict(matches[0]), 'instances': instances}


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


def validate_layout_view_binding(binding: Mapping[str, Any], *, read: Any) -> Mapping[str, Any]:
    view = validate_layout_binding(binding['view_identity'], role='view')
    if not time.time() < view['expires_at']:
        raise ValueError('The discovered view identity expired; inspect again')
    instances = canonical_view_instances(read('ak.wwise.ui.layout.getViewInstances', {'name': binding['layout_name']}, {}))
    matches = [row for row in instances if row['viewID'].upper() == view['native_id'].upper()]
    if len(matches) != 1 or canonical_sha256(matches[0]) != view['observation_sha256']:
        raise ValueError('The discovered view changed or disappeared; inspect and preview again')
    return matches[0]
