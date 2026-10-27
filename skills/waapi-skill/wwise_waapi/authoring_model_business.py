"""Gateway-owned Authoring windows, frontend models and widget signals.

Native catalogs are immutable source evidence; business plans never accept a
native envelope, a model dump, or executable widget content.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping

from .canonical import canonical_sha256
from .authoring_wafm import compile_template, value_schema, compile_value, text, template_constructor_schemas, attribute_assignment_schema, compile_template_registration, select_registered_template

VERSIONS = ('2024.1', '2025.1')
PREFIX = 'ak.wwise.ui.'
MODEL_OPERATIONS = frozenset(PREFIX + name for name in (
    'window.create', 'window.present', 'window.close', 'model.registerWafm',
    'model.createHandle', 'model.destroyHandle', 'model.getState', 'model.setState', 'signal.emit'))
MODEL_READ_URI = PREFIX + 'model.getState'
RESOURCE = 'authoring-model-supplement.json'
PINNED: dict[str, str] = {'2024.1': 'b81c9ccb0f81cc2469ea8c7cc9f9eb52352d33c5d57c4b5a14d27aee52ca4e3f', '2025.1': '2b50be3ca68e115edf638280b56b9e784116a05f583d202ec0373460e5febf79'}


def merge_authoring_models(manifest: Mapping[str, Any], *, root: Path | None, version: str) -> dict[str, Any]:
    result = deepcopy(dict(manifest))
    if version not in VERSIONS:
        return result
    if root is None:
        raise ValueError('Authoring models require pinned source evidence')
    evidence = json.loads((root / version / RESOURCE).read_text(encoding='utf-8'))
    if (canonical_sha256(evidence) != PINNED[version] or evidence['version'] != version
            or evidence['host'] != 'wwise-authoring' or set(evidence['schemas']) != MODEL_OPERATIONS):
        raise ValueError('Authoring model source identity/digest mismatch')
    known = {row['uri'] for row in result['functions']}
    for uri, schema in sorted(evidence['schemas'].items()):
        if uri in known:
            raise ValueError('Authoring model supplement cannot replace an existing route')
        result['functions'].append({'uri': uri, 'description': schema['description'], 'host_surface': 'wwise-authoring'})
        result['schemas'].append({'uri': uri, 'status': 'ok', 'schema': schema})
    result['functions'].sort(key=lambda row: row['uri'])
    result['schemas'].sort(key=lambda row: row['uri'])
    return result


def model_business_contract(operation: str, version: str) -> dict[str, Any]:
    if operation not in MODEL_OPERATIONS or version not in VERSIONS:
        raise ValueError('This exact Authoring model/window/signal route requires 2024.1 or 2025.1; earlier native catalogs do not list it')
    properties = {'title': {'type': 'string', 'maxLength': 4096},
                  'width': {'type': 'integer', 'minimum': 1}, 'height': {'type': 'integer', 'minimum': 1}}
    required = ['title', 'width', 'height']
    if operation == PREFIX + 'model.registerWafm':
        constructors = template_constructor_schemas(version)
        properties = {'template_key': {'type': 'string', 'minLength': 1}, 'root_widget': {'type': 'string'},
            'widgets': {'type': 'array', 'maxItems': 2048, 'items': constructors['widget']},
            'layouts': {'type': 'array', 'maxItems': 2048, 'items': constructors['layout']},
            'registration_medium': {'enum': ['inline', 'file']},
            'registration_form': {'enum': ['template_attribute', 'named_template']},
            'template_version': {'type': 'integer', 'minimum': 1}, 'metadata': value_schema()}
        unit_properties = {key: value for key, value in properties.items() if key not in {'registration_medium', 'registration_form'}}
        properties['templates'] = {'type': 'array', 'maxItems': 128, 'items': {
            'type': 'object', 'additionalProperties': False, 'required': ['template_key', 'root_widget', 'widgets', 'layouts'], 'properties': unit_properties}}
        required = []
    if operation in {PREFIX + 'window.present', PREFIX + 'window.close'}:
        properties = {'window': {'type': 'string', 'pattern': '^ar1-[0-9a-f]{32}$'}}
        required = ['window']
    if operation == PREFIX + 'model.createHandle':
        properties = {'window': {'type': 'string', 'pattern': '^ar1-[0-9a-f]{32}$'},
                      'template': {'type': 'string', 'pattern': '^ar1-[0-9a-f]{32}$'}, 'template_key': {'type': 'string', 'minLength': 1}}
        required = ['window', 'template']
    if operation in {PREFIX + 'model.destroyHandle', MODEL_READ_URI, PREFIX + 'model.setState', PREFIX + 'signal.emit'}:
        properties = {'model': {'type': 'string', 'pattern': '^ar1-[0-9a-f]{32}$'}}
        required = ['model']
        if operation in {MODEL_READ_URI, PREFIX + 'model.setState'}:
            attribute = {'type': 'string', 'minLength': 1, 'maxLength': 8192} if operation == MODEL_READ_URI else attribute_assignment_schema()
            properties['widgets'] = {'type': 'array', 'maxItems': 2048, 'items': {
                'type': 'object', 'additionalProperties': False, 'required': ['widget', 'attributes'],
                'properties': {'widget': {'type': 'string', 'minLength': 1},
                    'attributes': {'type': 'array', 'maxItems': 128, 'items': attribute}}}}
            required.append('widgets')
        if operation == PREFIX + 'signal.emit':
            properties.update(widget={'type': 'string', 'minLength': 1}, signal={'oneOf': [{'enum': ['click', 'toggle']}, {'type': 'object', 'additionalProperties': False,
                'required': ['topic_uri'], 'properties': {'topic_uri': {'type': 'string', 'minLength': 1, 'maxLength': 8192}}}]})
            required.extend(['widget', 'signal'])
    return {'contract': 'waapi-skill.authoring-model-business/v1', 'operation': operation,
        'version': version, 'input_mode': 'business_declaration', 'execution_shape': 'transaction',
        'start': {'subcommand': 'draft-start', 'gateway_argv': ['draft-start', operation],
                  'copy_exactly': True, 'append_arguments': 'forbidden'},
        'binding': {'available': False, 'roles': [], 'role_required': False},
        'declaration': {'subcommand': 'draft-declare-model-plan', 'settings_field': 'authoring_model_plan',
            'submit_once': True, 'required_fields': ['plan'], 'optional_fields': [],
            'input_forms': {'plan': {'gateway_flag': '--plan', 'shape': 'json'}},
            'schema': {'type': 'object', 'additionalProperties': False, 'required': required, 'properties': properties,
                'definitions': constructors['definitions'] if operation == PREFIX + 'model.registerWafm' else {'businessValue': value_schema()},
                **({'oneOf': [{'required': ['template_key', 'root_widget', 'widgets', 'layouts'], 'not': {'required': ['templates']}},
                    {'required': ['templates'], 'not': {'anyOf': [{'required': [key]} for key in ('template_key', 'root_widget', 'widgets', 'layouts', 'metadata', 'template_version', 'registration_form')]}}]}
                   if operation == PREFIX + 'model.registerWafm' else {})}},
        'responsibility_split': {'agent': ['choose the window, model and widget business outcome'],
            'gateway': ['construct native payload', 'bind owned resources to configuration and live host session',
                        'execute at most once after authorization', 'retain unknown native effects explicitly']},
        'gateway_derivations': ['native request envelope', 'owned native identifiers', 'resource lifetime'],
        'resource_lifetime': {'ownership': 'gateway_created_only',
            'ownership_recovery': ['authoring-resource', '<creation_transaction_id>'], 'scope': 'configuration_host_build_session_project',
            'cleanup': 'separately_previewed_owned_close_or_destroy', 'unknown_creation': 'never_retry'},
        'effect_verification': {'native_effect_evidence': 'not_independently_verified',
            'window_effect': 'native_result_does_not_establish_visible_or_closed_window',
            'signal_delivery': 'emit_result_is_not_delivery_proof; start an owned Topic observer before separately authorized emission',
            'exact_topic_semantics': 'native accepts or rejects the selected URI; no availability is inferred from its spelling'},
        **({'construction': {'widget_kinds': constructors['widget_catalog'],
            'widget': {'required': ['key', 'kind'], 'optional': ['attributes']},
            'attribute': {'required': ['attribute', 'value'], 'value': value_schema()},
            'layout': {'required': ['key', 'kind', 'children'], 'optional': ['attributes', 'splitters'],
                'kinds': constructors['layout_catalog']},
            'child': {'choose_one': ['widget', 'layout'], 'optional': ['positions', 'anchors', 'section', 'width', 'minimum_size']},
            'limits': {'construction_depth': 16, 'construction_nodes': 2048, 'plan_utf8_bytes': 262144},
            'root_layout_scope': '2024.1 only AnchorLayout; 2025.1 permits AnchorLayout, BinLayout, GroupBox, OverflowHBox, SplitLayout',
            'native_schema_validation': 'complete_reachable_definitions', 'native_file_alternative': 'Gateway_owned_generated_WAFM_artifact_with_immutable_file_proof'}}
           if operation == PREFIX + 'model.registerWafm' else {}),
        'safety': {'immutable_preview': True, 'single_execute': True, 'authoring_host_required': True,
                   'native_request_fields': 'gateway_owned', 'automatic_retry': False}}


def model_catalog_rows() -> tuple[dict[str, Any], ...]:
    return tuple({'api': uri, 'intent': uri.removeprefix(PREFIX), 'supported_versions': list(VERSIONS)}
                 for uri in sorted(MODEL_OPERATIONS))


def validate_model_plan(operation: str, version: str, plan: Any) -> dict[str, Any]:
    from .builders.schema import _SchemaWalker
    schema = model_business_contract(operation, version)['declaration']['schema']
    _SchemaWalker(uri=operation, version=version).validate(schema, plan, path='plan')
    if len(json.dumps(plan, ensure_ascii=False, allow_nan=False).encode('utf-8')) > 256 * 1024:
        raise ValueError('Authoring business plan exceeds its bounded byte ceiling')
    return deepcopy(dict(plan))


def compile_model_plan(operation: str, version: str, plan: Any, resources: Mapping[str, Any]) -> dict[str, Any]:
    plan = validate_model_plan(operation, version, plan)
    if operation == PREFIX + 'window.create':
        return {'title': plan['title'], 'size': {'width': plan['width'], 'height': plan['height']}}
    if operation in {PREFIX + 'window.present', PREFIX + 'window.close'}:
        resource = require_model_resource(plan, resources, 'window', 'window')
        return {'windowID': resource['native_id']}
    if operation == PREFIX + 'model.registerWafm':
        name = resources.get('registration_name')
        if not isinstance(name, str) or not name.startswith('Gateway_'):
            raise ValueError('Template registration requires its frozen Gateway-owned namespace')
        wafm = compile_template_registration(plan, version=version, namespace=name)
        if plan.get('registration_medium', 'inline') == 'file':
            from .operation_import import verify_regular_file_proof
            from .canonical import canonical_json_bytes
            import hashlib
            proof = resources.get('wafm_file')
            if not isinstance(proof, Mapping) or proof.get('sha256') != hashlib.sha256(canonical_json_bytes(wafm) + b'\n').hexdigest():
                raise ValueError('Owned WAFM artifact differs from its complete closed template construction')
            verify_regular_file_proof(proof, field='owned_wafm_file')
            return {'wafm': proof['path']}
        return {'wafm': wafm}
    if operation == PREFIX + 'model.createHandle':
        window = require_model_resource(plan, resources, 'window', 'window')
        template = require_model_resource(plan, resources, 'template', 'template')
        _, native_name = select_registered_template(template, plan.get('template_key'))
        return {'container': window['native_id'], 'template': native_name}
    if operation in {PREFIX + 'model.destroyHandle', MODEL_READ_URI, PREFIX + 'model.setState', PREFIX + 'signal.emit'}:
        model = require_model_resource(plan, resources, 'model', 'model')
        native = {'handleID': model['native_id']}
        if operation == PREFIX + 'model.destroyHandle': return native
        widgets = model['description']['template']['widgets']
        known = {row['key']: row for row in widgets}
        if operation == PREFIX + 'signal.emit':
            widget = require_owned_widget(model, plan['widget'])
            # Topic descriptions describe usual producers, not emit receiver restrictions.
            signal = plan['signal']
            uri = text(signal['topic_uri'], 'Exact signal Topic URI') if isinstance(signal, Mapping) else PREFIX + 'signal.' + signal
            return {**native, 'widgetID': plan['widget'], 'signal': uri}
        state = []
        seen = set()
        for row in plan['widgets']:
            if not isinstance(row, Mapping) or set(row) != {'widget', 'attributes'} or not isinstance(row['attributes'], list):
                raise ValueError('Widget state requires exactly widget and a bounded attributes collection')
            key = row['widget']
            require_owned_widget(model, key)
            if key in seen or len(row['attributes']) > 128: raise ValueError('Duplicate widget or oversized state attribute collection')
            seen.add(key)
            if operation == MODEL_READ_URI:
                attributes = [text(value, 'State attribute') for value in row['attributes']]
            else:
                attributes = []
                for attribute in row['attributes']:
                    if not isinstance(attribute, Mapping) or set(attribute) != {'attribute', 'value'}:
                        raise ValueError('State assignment requires exactly attribute and typed value')
                    attributes.append({'attribute': text(attribute['attribute'], 'State attribute'), 'value': compile_value(attribute['value'])})
            names = attributes if operation == MODEL_READ_URI else [item['attribute'] for item in attributes]
            if len(names) != len(set(names)): raise ValueError('State attributes must be unique per widget')
            state.append({'widgetID': key, 'state': attributes})
        return {**native, 'state': state}
    raise ValueError('Authoring business operation implementation remains unfinished')


def materialize_model_business(operation: str, session: Any) -> Mapping[str, Any]:
    from .operation_registry import parse_operation_request
    if set(session.settings) != {'authoring_model_plan', 'authoring_model_binding'}:
        raise ValueError('Submit the complete disclosed Authoring model/window plan')
    binding = session.settings['authoring_model_binding']
    args = compile_model_plan(operation, session.context.wwise_version,
        session.settings['authoring_model_plan'], binding['resources'])
    request = {'contract': 'waapi-skill.operation-request/v1', 'operation': 'waapi.call', 'version': session.context.wwise_version,
               'arguments': {'api': operation, 'args': args, 'options': {}, 'model_binding': binding}}
    parse_operation_request(request, expected_version=session.context.wwise_version)
    return request


def validate_model_call(version: str, operation: str, args: Mapping[str, Any], options: Mapping[str, Any], binding: Any) -> None:
    if not isinstance(binding, Mapping) or set(binding) != {'operation', 'context', 'plan', 'resources', 'sha256'} or binding.get('operation') != operation:
        raise ValueError('Authoring operation requires its Gateway-owned business binding')
    body = {k: v for k, v in binding.items() if k != 'sha256'}
    expected = set(model_resource_roles(operation)) | ({'registration_name'} if operation == PREFIX + 'model.registerWafm' else set())
    if operation == PREFIX + 'model.registerWafm' and binding['plan'].get('registration_medium', 'inline') == 'file':
        expected.add('wafm_file')
    if not isinstance(binding['resources'], Mapping) or set(binding['resources']) != expected:
        raise ValueError('Authoring operation has incomplete or extra resource bindings')
    for field in model_resource_roles(operation):
        if binding['resources'][field].get('context') != binding['context']:
            raise ValueError('Authoring resource bindings must share their exact configuration/host/session/project')
    if canonical_sha256(body) != binding['sha256'] or options or args != compile_model_plan(operation, version, binding['plan'], binding['resources']):
        raise ValueError('Authoring native request differs from its sealed business declaration')


def require_model_resource(plan: Mapping[str, Any], resources: Mapping[str, Any], field: str, kind: str) -> Mapping[str, Any]:
    record = resources.get(field)
    if not isinstance(record, Mapping) or record.get('handle') != plan[field] or record.get('kind') != kind or record.get('status') != 'active':
        raise ValueError('Authoring plan requires its exact owned ' + field + ' resource')
    return record


def model_resource_roles(operation: str) -> dict[str, str]:
    if operation in {PREFIX + 'window.present', PREFIX + 'window.close'}:
        return {'window': 'window'}
    if operation == PREFIX + 'model.createHandle':
        return {'window': 'window', 'template': 'template'}
    if operation in {PREFIX + 'model.destroyHandle', MODEL_READ_URI, PREFIX + 'model.setState', PREFIX + 'signal.emit'}:
        return {'model': 'model'}
    return {}


def require_owned_widget(model: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    text(key, 'Widget key')
    rows = [row for row in model['description']['template']['widgets'] if row['key'] == key]
    if len(rows) != 1:
        raise ValueError('Widget does not belong to the selected owned frontend template')
    return rows[0]


def state_query_from_assignments(native: Mapping[str, Any]) -> dict[str, Any]:
    return {'handleID': native['handleID'], 'state': [{'widgetID': row['widgetID'],
        'state': [item['attribute'] for item in row['state']]} for row in native['state']]}


def canonical_state_result(result: Any, query: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if not isinstance(result, list) or len(result) != len(query['state']):
        raise ValueError('State observation omitted or added widgets')
    expected = {row['widgetID']: row['state'] for row in query['state']}
    actual = {}
    for row in result:
        if not isinstance(row, Mapping) or set(row) != {'widgetID', 'state'} or row['widgetID'] not in expected or row['widgetID'] in actual or not isinstance(row['state'], list):
            raise ValueError('State observation has missing, duplicate, extra or malformed widgets')
        attributes = {}
        for item in row['state']:
            if not isinstance(item, Mapping) or not {'attribute', 'value'} <= set(item) or item['attribute'] not in expected[row['widgetID']] or item['attribute'] in attributes:
                raise ValueError('State observation has missing, duplicate, extra or malformed attributes')
            attributes[item['attribute']] = item['value']
        if set(attributes) != set(expected[row['widgetID']]): raise ValueError('State observation omitted attributes')
        actual[row['widgetID']] = attributes
    return actual


def creation_resource_receipt(request: Mapping[str, Any], execution_result: Mapping[str, Any], *,
    transaction_id: str, context: Mapping[str, Any], store: Any) -> dict[str, Any]:
    import re
    operation = request['arguments']['api']
    binding = request['arguments']['model_binding']
    if binding['context'] != context or execution_result.get('ok') is not True:
        raise ValueError('Creation ownership recovery requires the exact successful dispatch and unchanged Authoring session')
    result = execution_result.get('result')
    if not isinstance(result, Mapping): raise ValueError('Creation did not return a recoverable native identity')
    if operation == PREFIX + 'model.registerWafm':
        if result.get('success') is not True:
            raise ValueError('Rejected template registration cannot become an owned template')
        kind = 'template'
        native_id = binding['resources']['registration_name']
    elif operation in {PREFIX + 'window.create', PREFIX + 'model.createHandle'}:
        kind = 'window' if operation.endswith('window.create') else 'model'
        native_id = result.get('windowID' if kind == 'window' else 'handleID')
        if not isinstance(native_id, str) or not re.fullmatch(r'\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}', native_id):
            raise ValueError('Creation returned no exact recoverable native GUID; never recreate the resource')
    else:
        raise ValueError('Only a recorded window/frontend creation or accepted template registration owns a resource')
    description = dict(binding['plan']) if kind != 'model' else {
        'template': select_registered_template(binding['resources']['template'], binding['plan'].get('template_key'))[0], 'window': binding['plan']['window']}
    parents = [binding['plan']['window'], binding['plan']['template']] if kind == 'model' else []
    receipt = store.issue(transaction_id=transaction_id, context=context, kind=kind,
        native_id=native_id, description=description, parents=parents)
    return {'resource_handle': receipt['handle'], 'resource_kind': kind, 'observable_effect_verified': False,
        'cleanup_required': True, 'cleanup_route': (['request-schema', PREFIX + ('window.close' if kind == 'window' else 'model.destroyHandle')] if kind != 'template' else None),
        'cleanup_mechanism': 'separately_previewed_owned_close' if kind != 'template' else 'Authoring_session_end_no_reflected_unregister_function',
        'cleanup_complete': False, 'automatic_retry': False}


def model_file_audit(binding: Mapping[str, Any]) -> dict[str, Any] | None:
    proof = binding['resources'].get('wafm_file')
    if proof is None: return None
    return {'contract': 'waapi-skill.wwise-wire-path-input-audit/v1', 'uri': PREFIX + 'model.registerWafm',
        'paths': [{'section': 'args', 'json_path': '$.args.wafm', 'field': 'wafm', 'role': 'read',
                   'raw_path': proof['path'], 'resolved_path': proof['path']}],
        'owned_artifact': True, 'source_sha256': proof['sha256']}
