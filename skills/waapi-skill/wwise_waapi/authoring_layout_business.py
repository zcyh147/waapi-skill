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
LAYOUT_SPLITTER_URI = 'ak.wwise.ui.layout.moveSplitter'
LAYOUT_DOCK_URI = 'ak.wwise.ui.layout.dockView'
LAYOUT_UNDOCK_URI = 'ak.wwise.ui.layout.undockView'
LAYOUT_CLOSE_URI = 'ak.wwise.ui.layout.closeView'
LAYOUT_GET_OR_CREATE_URI = 'ak.wwise.ui.layout.getOrCreateView'
LAYOUT_MUTATION_URIS = frozenset({LAYOUT_SWITCH_URI, LAYOUT_SET_URI, LAYOUT_REMOVE_URI, LAYOUT_GET_OR_CREATE_URI, LAYOUT_CLOSE_URI, LAYOUT_UNDOCK_URI, LAYOUT_DOCK_URI, LAYOUT_SPLITTER_URI})
MUTATION_RESOURCE = 'authoring-layout-mutation-supplement.json'
MUTATION_SHA256: dict[str, str] = {'2024.1': 'a93363f7c0cf837f90eff10ae04430854405dcb22ecc1fb000e583d5ee04486e', '2025.1': 'ff8bf4e3072c20fa93bb5de34f4ed897bb29449173a8b2d3f8a7005ca849e7d3'}


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
    elif operation == LAYOUT_SPLITTER_URI:
        for field, kind in (('splitter_handle', 'scoped_element_handle'), ('pixel_delta', 'integer')):
            result['declaration']['required_fields'].append(field)
            result['declaration']['public_fields'].append(field)
            result['declaration']['field_types'][field] = kind
            result['declaration']['input_forms'][field] = {'gateway_flag': '--' + field.replace('_', '-'), 'shape': 'integer' if kind == 'integer' else 'scalar'}
        result['responsibility_split']['agent'] = ['choose a discovered splitter and signed pixel displacement']
        result['responsibility_split']['gateway'] = ['revalidate the exact splitter in the current layout',
            'derive the movement axis from its parent stack', 'freeze the exact rectangle',
            'move once after authorization', 'verify the exact displacement, size and perpendicular coordinates']
        result['gateway_derivations'].append('movement axis from the discovered parent stack orientation')
        result['verifier'] = {'kind': 'authoring-layout-state', 'observation': 'independent exact splitter rectangle delta and parent axis',
            'clipped_or_incomplete_effect': 'not_verified; never replay the movement'}
    elif operation in {LAYOUT_CLOSE_URI, LAYOUT_UNDOCK_URI, LAYOUT_DOCK_URI}:
        result['declaration']['required_fields'].append('view_handle')
        result['declaration']['public_fields'].append('view_handle')
        result['declaration']['field_types']['view_handle'] = 'scoped_view_handle'
        result['declaration']['input_forms']['view_handle'] = {'gateway_flag': '--view-handle', 'shape': 'scalar'}
        result['responsibility_split']['gateway'] = ['require the selected layout to be current', 'revalidate the exact discovered view',
            'request close once after authorization', 'poll bounded independent instances for exact disappearance']
        result['verifier'] = {'kind': 'authoring-layout-state', 'observation': 'exact view absent from independently read instances',
            'maximum_polls': 16, 'poll_interval_seconds': 0.2, 'incomplete_boundary': 'pending_async_close'}
        if operation == LAYOUT_DOCK_URI:
            for field, kind in (('target_element_handle', 'scoped_element_handle'), ('dock_side', 'enum:left,right,top,bottom')):
                result['declaration']['required_fields'].append(field)
                result['declaration']['public_fields'].append(field)
                result['declaration']['field_types'][field] = kind
                result['declaration']['input_forms'][field] = {'gateway_flag': '--' + field.replace('_', '-'), 'shape': 'scalar'}
            result['responsibility_split']['agent'] = ['choose a discovered view, target element and exact docking side']
            result['responsibility_split']['gateway'] = ['revalidate both identities in the current layout',
                'dock or redock once without an extra undock write', 'verify the same view and exact target-relative side']
            result['verifier'] = {'kind': 'authoring-layout-state', 'observation': 'independent exact docked topology, order, orientation and target-relative rectangles'}
            result['verifier']['unresolved_native_effects'] = ['owned native characterization of target-kind topology semantics', 'omitted or nonpositive target rectangles']
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
    return tuple({'api': uri, 'intent': {LAYOUT_SWITCH_URI: 'switch layout', LAYOUT_SET_URI: 'register temporary layout', LAYOUT_REMOVE_URI: 'remove temporary layout', LAYOUT_GET_OR_CREATE_URI: 'get or create a live view', LAYOUT_CLOSE_URI: 'close a discovered view', LAYOUT_UNDOCK_URI: 'float a discovered view', LAYOUT_DOCK_URI: 'dock or redock a discovered view', LAYOUT_SPLITTER_URI: 'move a discovered splitter by signed pixels'}[uri],
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
                              position_request: Mapping[str, Any] | None = None,
                              target_identity: Mapping[str, Any] | None = None,
                              dock_request: Mapping[str, Any] | None = None,
                              splitter_identity: Mapping[str, Any] | None = None,
                              splitter_request: Mapping[str, Any] | None = None) -> dict[str, Any]:
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
    if target_identity is not None:
        body['target_identity'] = layout_binding_descriptor(target_identity)
    if dock_request is not None:
        native_dock_side(dock_request)
        body['dock_request'] = dict(dock_request)
    if splitter_identity is not None:
        body['splitter_identity'] = layout_binding_descriptor(splitter_identity)
    if splitter_request is not None:
        native_splitter_request(splitter_request)
        body['splitter_request'] = dict(splitter_request)
    return {**body, 'binding_sha256': canonical_sha256(body)}


def validate_layout_binding(binding: Any, *, role: str = 'layout') -> dict[str, Any]:
    expected = {'handle', 'context', 'layout_name', 'role', 'native_id', 'expires_at', 'observation_sha256', 'binding_sha256'}
    if not isinstance(binding, Mapping) or set(binding) not in (expected, expected | {'registration_name'}, expected | {'view_request'}, expected | {'view_identity'}, expected | {'view_identity', 'position_request'}, expected | {'view_identity', 'target_identity', 'dock_request'}, expected | {'splitter_identity', 'splitter_request'}):
        raise ValueError('Layout mutation lacks an exact Gateway-owned identity binding')
    body = dict(binding)
    digest = body.pop('binding_sha256')
    if (canonical_sha256(body) != digest or body['role'] != role
            or (role != 'layout' and set(binding) != expected)
            or (role == 'layout' and body['native_id'] != body['layout_name'])
            or (role == 'view' and (set(binding) != expected or not re.fullmatch(
                r'\{[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\}', str(body['native_id']))))):
        raise ValueError('Layout mutation identity binding is malformed')
    if (not isinstance(body['context'], Mapping) or not isinstance(body['layout_name'], str)
            or not isinstance(body['native_id'], str) or not body['native_id'] or '\x00' in body['native_id']
            or len(body['native_id'].encode('utf-8')) > 4096):
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
    if 'target_identity' in body:
        target = validate_layout_binding(body['target_identity'], role='element')
        if (target['context'] != body['context'] or target['layout_name'] != body['layout_name']
                or target['native_id'].upper() == body['view_identity']['native_id'].upper()
                or not re.fullmatch(r'\{[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\}', target['native_id'])):
            raise ValueError('Dock target must be a different exact GUID element in the same layout scope')
        native_dock_side(body['dock_request'])
    if 'splitter_identity' in body:
        splitter = validate_layout_binding(body['splitter_identity'], role='element')
        if splitter['context'] != body['context'] or splitter['layout_name'] != body['layout_name']:
            raise ValueError('Splitter and layout identities must share their exact live scope')
        native_splitter_request(body['splitter_request'])
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
    elif operation == LAYOUT_SPLITTER_URI:
        if (plan['splitter_handle'] != binding.get('splitter_identity', {}).get('handle')
                or {'pixel_delta': plan['pixel_delta']} != binding.get('splitter_request')):
            raise ValueError('Splitter declaration differs from its scoped identity and displacement binding')
        native_args = {'id': binding['splitter_identity']['native_id'], **native_splitter_request(binding['splitter_request'])}
    elif operation in {LAYOUT_CLOSE_URI, LAYOUT_UNDOCK_URI, LAYOUT_DOCK_URI}:
        view = binding.get('view_identity', {})
        if plan['view_handle'] != view.get('handle'):
            raise ValueError('View declaration differs from its Gateway-owned discovered identity')
        native_args = {'viewID': view['native_id']}
        if operation == LAYOUT_UNDOCK_URI:
            position = {key: value for key, value in plan.items() if key not in {'layout_handle', 'view_handle'}}
            if position != binding.get('position_request'):
                raise ValueError('Floating position differs from its Gateway-owned declaration binding')
            native_args.update(name=binding['layout_name'], **native_position_request(position))
        elif operation == LAYOUT_DOCK_URI:
            if (plan['target_element_handle'] != binding.get('target_identity', {}).get('handle')
                    or {'dock_side': plan['dock_side']} != binding.get('dock_request')):
                raise ValueError('Dock declaration differs from its exact target/side binding')
            native_args.update(name=binding['layout_name'], targetID=binding['target_identity']['native_id'],
                side=native_dock_side(binding['dock_request']))
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
    elif api == LAYOUT_SPLITTER_URI:
        expected = {'id': verified['splitter_identity']['native_id'], **native_splitter_request(verified['splitter_request'])}
    elif api in {LAYOUT_CLOSE_URI, LAYOUT_UNDOCK_URI, LAYOUT_DOCK_URI}:
        view = validate_layout_binding(verified.get('view_identity'), role='view')
        expected = {'viewID': view['native_id']}
        if api == LAYOUT_UNDOCK_URI:
            expected.update(name=verified['layout_name'], **native_position_request(verified.get('position_request')))
        elif api == LAYOUT_DOCK_URI:
            expected.update(name=verified['layout_name'], targetID=verified['target_identity']['native_id'],
                side=native_dock_side(verified['dock_request']))
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


def validate_layout_view_binding(binding: Mapping[str, Any], *, read: Any,
                                 instances: list[dict[str, Any]] | None = None) -> Mapping[str, Any]:
    view = validate_layout_binding(binding['view_identity'], role='view')
    if not time.time() < view['expires_at']:
        raise ValueError('The discovered view identity expired; inspect again')
    if instances is None:
        instances = canonical_view_instances(read('ak.wwise.ui.layout.getViewInstances', {'name': binding['layout_name']}, {}))
    matches = [row for row in instances if row['viewID'].upper() == view['native_id'].upper()]
    if len(matches) != 1 or canonical_sha256(matches[0]) != view['observation_sha256']:
        raise ValueError('The discovered view changed or disappeared; inspect and preview again')
    return matches[0]


def native_dock_side(plan: Any) -> str:
    if not isinstance(plan, Mapping) or set(plan) != {'dock_side'} or plan['dock_side'] not in ('left', 'right', 'top', 'bottom'):
        raise ValueError('Docking requires one exact left/right/top/bottom side')
    return plan['dock_side']


def require_layout_rectangle(value: Any) -> dict[str, int | float]:
    validate_layout_read_result('rectangle', value)
    if (not isinstance(value, Mapping) or set(value) != {'left', 'top', 'right', 'bottom'}
            or any(type(edge) not in (int, float) or not math.isfinite(edge) for edge in value.values())
            or value['right'] <= value['left'] or value['bottom'] <= value['top']):
        raise ValueError('Layout effect requires a complete positive native rectangle')
    return dict(value)


def layout_element_observation(layout: Mapping[str, Any], identity: str) -> Mapping[str, Any]:
    from .authoring_layout import layout_identity_rows
    validate_layout_read_result('contents', layout)
    elements, _ = layout_identity_rows(layout, {'viewInstances': []})
    matches = [row for row in elements if _element_identity(row['native_id']) == _element_identity(identity)]
    if len(matches) != 1:
        raise ValueError('The exact discovered layout element is missing or ambiguous')
    return matches[0]


def dock_state_observation(binding: Mapping[str, Any], *, read: Any) -> dict[str, Any]:
    instances = canonical_view_instances(read('ak.wwise.ui.layout.getViewInstances', {'name': binding['layout_name']}, {}))
    view = validate_layout_view_binding(binding, read=read, instances=instances)
    target = validate_layout_binding(binding['target_identity'], role='element')
    if not time.time() < target['expires_at']:
        raise ValueError('The discovered dock target expired; inspect again')
    layout = read('ak.wwise.ui.layout.getLayout', {'name': binding['layout_name']}, {})
    element = layout_element_observation(layout, target['native_id'])
    if canonical_sha256(element['observation']) != target['observation_sha256']:
        raise ValueError('The discovered dock target changed; inspect again')
    return {'view': dict(view), 'instances': instances, 'target': dict(element), 'rectangles': {
        role: require_layout_rectangle(read('ak.wwise.ui.layout.getElementRectangle', {'id': identity}, {}))
        for role, identity in (('view', view['viewID']), ('target', target['native_id']))}}


def docking_side_matches(view: Mapping[str, Any], target: Mapping[str, Any], side: str) -> bool:
    view, target = require_layout_rectangle(view), require_layout_rectangle(target)
    vertical_overlap = min(view['bottom'], target['bottom']) > max(view['top'], target['top'])
    horizontal_overlap = min(view['right'], target['right']) > max(view['left'], target['left'])
    return {'left': view['right'] <= target['left'] and vertical_overlap,
            'right': view['left'] >= target['right'] and vertical_overlap,
            'top': view['bottom'] <= target['top'] and horizontal_overlap,
            'bottom': view['top'] >= target['bottom'] and horizontal_overlap}[side]


def _element_identity(value: str) -> str:
    return value.upper() if re.fullmatch(r'\{[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\}', value) else value


def _content_children(node: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    children = node.get('@Children', [])
    if not isinstance(children, list) or any(not isinstance(child, Mapping) for child in children):
        raise ValueError('Dock topology children are malformed')
    return [child for child in children if child.get('@type') != 'Splitter']


def layout_subtree_ids(node: Mapping[str, Any]) -> list[str]:
    result = []
    def walk(current):
        if isinstance(current.get('ID'), str):
            result.append(current['ID'])
        for child in _content_children(current):
            walk(child)
    walk(node)
    return sorted(set(result))


def docking_topology_proof(layout: Mapping[str, Any], *, view_id: str, target_id: str,
                           side: str, previous_target_ids: list[str]) -> dict[str, Any]:
    """Require an exact ordered stack relationship; geometry alone is insufficient."""
    validate_layout_read_result('contents', layout)
    root = layout.get('Layout', {}).get('StackPanel')
    if not isinstance(root, Mapping):
        raise ValueError('Docked stack topology was omitted')
    paths = {view_id: [], target_id: []}
    def walk(node, parents):
        path = [*parents, node]
        for identity in paths:
            if isinstance(node.get('ID'), str) and _element_identity(node['ID']) == _element_identity(identity):
                paths[identity].append(path)
        for child in _content_children(node):
            walk(child, path)
    walk(root, [])
    if any(len(matches) != 1 for matches in paths.values()):
        raise ValueError('Exact view and target must each occur once in the docked topology')
    view_path, target_path = paths[view_id][0], paths[target_id][0]
    if view_path[-1].get('@type') != 'View':
        raise ValueError('Docked view identity has no exact serialized View node')
    def require_stack(node):
        if (node is not root and node.get('@type') != 'StackPanel') or node.get('Orientation') != (
                'Horizontal' if side in {'left', 'right'} else 'Vertical'):
            raise ValueError('Dock topology orientation does not prove the requested side')
    def transparent_to(branch, identity):
        while _element_identity(str(branch.get('ID', ''))) != _element_identity(identity):
            children = _content_children(branch)
            if branch.get('@type') != 'StackPanel' or len(children) != 1:
                raise ValueError('Intervening panes prevent an exact target-relative docking proof')
            branch = children[0]
    common = 0
    while common < min(len(view_path), len(target_path)) and view_path[common] is target_path[common]:
        common += 1
    before = side in {'left', 'top'}
    if common == len(target_path):
        parent = target_path[-1]
        require_stack(parent)
        children = _content_children(parent)
        branch = view_path[common]
        transparent_to(branch, view_id)
        index = next(i for i, child in enumerate(children) if child is branch)
        if len(children) < 2 or index != (0 if before else len(children) - 1):
            raise ValueError('View is not at the requested container boundary')
        peer = children[1 if before else -2]
        known = {_element_identity(value) for value in previous_target_ids if _element_identity(value) != _element_identity(view_id)}
        while _element_identity(str(peer.get('ID', ''))) not in known:
            descendants = _content_children(peer)
            if peer.get('@type') != 'StackPanel' or len(descendants) != 1:
                raise ValueError('Container docking lacks an exact retained target peer')
            peer = descendants[0]
        return {'relationship': 'container_boundary', 'parent_id': parent.get('ID'),
                'orientation': parent['Orientation'], 'peer_id': peer['ID']}
    if not common or common >= len(view_path):
        raise ValueError('View and target have no provable sibling stack relationship')
    parent = view_path[common - 1]
    require_stack(parent)
    view_branch, target_branch = view_path[common], target_path[common]
    transparent_to(view_branch, view_id)
    transparent_to(target_branch, target_id)
    children = _content_children(parent)
    vi = next(i for i, child in enumerate(children) if child is view_branch)
    ti = next(i for i, child in enumerate(children) if child is target_branch)
    if vi != ti + (-1 if before else 1):
        raise ValueError('View and exact dock target are not adjacent in the requested order')
    return {'relationship': 'adjacent_stack_children', 'parent_id': parent.get('ID'),
            'orientation': parent['Orientation'], 'peer_id': target_id}


def native_splitter_request(plan: Any) -> dict[str, int]:
    if not isinstance(plan, Mapping) or set(plan) != {'pixel_delta'} or type(plan['pixel_delta']) is not int:
        raise ValueError('Splitter movement requires one signed integer pixel displacement')
    return {'delta': plan['pixel_delta']}


def splitter_element_context(layout: Mapping[str, Any], identity: str) -> dict[str, Any]:
    validate_layout_read_result('contents', layout)
    matches, stacks = [], set()
    def walk(value, parent=None, implicit_stack=False):
        if isinstance(value, list):
            for child in value:
                walk(child, parent)
        elif isinstance(value, Mapping):
            if implicit_stack or value.get('@type') == 'StackPanel':
                stacks.add(id(value))
            if isinstance(value.get('ID'), str) and _element_identity(value['ID']) == _element_identity(identity):
                matches.append((value, parent))
            for field in ('Layout', 'StackPanel', 'Undocked', '@Children'):
                if field in value:
                    walk(value[field], value if field == '@Children' else None, field == 'StackPanel')
    walk(layout)
    if len(matches) != 1:
        raise ValueError('The exact splitter has no unique serialized parent context')
    element, parent = matches[0]
    if (element.get('@type') != 'Splitter' or parent is None or id(parent) not in stacks
            or parent.get('Orientation') not in {'Horizontal', 'Vertical'}
            or not isinstance(parent.get('ID'), str) or not parent['ID']):
        raise ValueError('A splitter requires its exact typed parent stack and orientation')
    return {'element': dict(element), 'parent_id': parent['ID'], 'orientation': parent['Orientation'],
            'axis': 'x' if parent['Orientation'] == 'Horizontal' else 'y'}


def splitter_state_observation(binding: Mapping[str, Any], *, read: Any) -> dict[str, Any]:
    splitter = validate_layout_binding(binding['splitter_identity'], role='element')
    if not time.time() < splitter['expires_at']:
        raise ValueError('The discovered splitter expired; inspect again')
    layout = read('ak.wwise.ui.layout.getLayout', {'name': binding['layout_name']}, {})
    observed = splitter_element_context(layout, splitter['native_id'])
    if canonical_sha256(observed['element']) != splitter['observation_sha256']:
        raise ValueError('The discovered splitter changed; inspect again')
    instances = canonical_view_instances(read('ak.wwise.ui.layout.getViewInstances', {'name': binding['layout_name']}, {}))
    return {**observed, 'instances': instances, 'rectangle': require_layout_rectangle(
        read('ak.wwise.ui.layout.getElementRectangle', {'id': splitter['native_id']}, {}))}


def layout_view_identities(instances: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Preserve view identity/type while allowing native pane and dock-state changes."""
    rows = canonical_view_instances({'viewInstances': instances})
    return sorted([{'view_id': _element_identity(row['viewID']), 'view_type': row['viewName']}
                   for row in rows], key=lambda row: (row['view_id'], row['view_type']))
