"""Concrete empty alternatives in the existing audit; no runtime/native waiver."""
from copy import deepcopy
import hashlib
import json


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def empty_value(branch):
    kinds = {'empty_string': ('/@empty/string', ''), 'empty_object': ('/@empty/object', {})}
    if branch.get('kind') == 'collection_cardinality' and branch.get('value') == 'empty':
        return '/@cardinality/empty', []
    return kinds.get(branch.get('kind'))


def classify_empty_candidate(root, branch, *, cache=None):
    """Classify only one concrete value, preserving every original branch identity.

    Cache lifetime is one immutable audit operation; catalog bytes are validated
    by the existing loader. Results are keyed by full catalog/context/schema.
    """
    selected = empty_value(branch)
    if selected is None:
        return None
    from tests.maintenance.branch_audit_completion import pointer_value, validate_native_alternative
    from wwise_waapi.native_catalog import load_native_catalog
    cache = {} if cache is None else cache
    suffix, candidate = selected
    result = {'contract': 'waapi-skill.empty-candidate-classification/v1', 'status': 'unknown',
              'candidate': candidate, 'native_route': branch.get('route'), 'pointer': branch['pointer']}
    try:
        if not branch['pointer'].endswith(suffix) or branch['shape_sha256'] != _digest(branch.get('value')):
            raise ValueError('synthetic candidate shape changed')
        if branch['kind'] != 'collection_cardinality' and (type(branch.get('value')) is not type(candidate) or branch['value'] != candidate):
            raise ValueError('synthetic candidate value changed')
        version, host, build, _, uri = branch['route'].split('|')
        catalogs = cache.setdefault('catalogs', {})
        key = (str(root.resolve()), version, host)
        if key not in catalogs:
            catalogs[key] = load_native_catalog(version, host, root=root / 'skills/waapi-skill/resources/native-catalog')
        catalog = catalogs[key]
        if catalog['provenance']['build'] != build:
            raise ValueError('alternative native build changed')
        parent = branch['pointer'][:-len(suffix)]
        section = parent.split('/')[1]
        context = catalog['schemas'][uri][section]
        if '/@definition/' in parent:
            _, rest = parent.split('/@definition/', 1)
            name, separator, tail = rest.partition('/')
            # <schema> means exactly the owning URI/section's local root.
            if name != '<schema>':
                context = catalog['definitions']['documents'][name]
            schema = pointer_value(context, '/' + tail if separator else '')
        else:
            schema = pointer_value(catalog['schemas'][uri], parent)
        result.update(parent_pointer=parent, parent_schema_sha256=_digest(schema),
                      context_sha256=_digest(context), catalog_sha256=catalog['content_sha256'],
                      definitions_sha256=catalog['definitions']['inventory_sha256'],
                      owning_section_sha256=_digest(catalog['schemas'][uri][section]))
        validation_key = (catalog['content_sha256'], result['context_sha256'], result['parent_schema_sha256'], _digest(candidate))
        validations = cache.setdefault('validations', {})
        if validation_key not in validations:
            try:
                validate_native_alternative(root, {**branch, 'pointer': parent, 'shape_sha256': _digest(schema)},
                                            candidate, catalog=catalog, require_known=True)
            except ValueError as exc:
                from wwise_waapi.builders.common import SemanticValidationError
                rejected = (str(exc) == 'observation does not satisfy selected native alternative'
                            and isinstance(exc.__cause__, SemanticValidationError))
                validations[validation_key] = ('rejected' if rejected else 'unknown',
                    'resolved schema rejects concrete candidate' if rejected else str(exc))
            else:
                validations[validation_key] = ('accepted', 'resolved schema accepts concrete candidate')
        result['status'], result['reason'] = validations[validation_key]
    except (KeyError, ValueError, TypeError, IndexError, OSError) as exc:
        result['reason'] = str(exc)
    return result


def _same(value, expected):
    return type(value) is type(expected) and value == expected


def _field_error(payload, field, *, native=False):
    """Only the structured failure location can attribute the rejected field."""
    if not isinstance(payload, dict):
        return False
    if native and payload.get('section') == field:
        return True
    if not native and payload.get('field') == field:
        return True
    return any(_field_error(value, field, native=native) for key, value in payload.items()
               if key in ('details', 'repair', 'error', 'validation_failure') and isinstance(value, dict))


def validate_counterexample(record, descriptor, branch, classification, candidate, category, scope_kind, binding, root, reference_edges):
    """Require a passing public failure test paired with its causal valid input.

    This grants program rejection credit only. It cannot satisfy a native or
    business-effect requirement and cannot create a native absence claim.
    """
    from tests.maintenance.branch_audit_completion import (pointer_value, exact_observation_pointer,
        native_host_context, validate_native_alternative)
    if (category != 'program' or classification['status'] != 'rejected'
            or binding.get('disposition') != 'schema_counterexample'
            or binding.get('empty_candidate') != classification
            or record.get('candidate_sha256') != candidate or record.get('scope_kind', 'product') != scope_kind):
        raise ValueError('exact current rejected-candidate program context missing')
    invocation = record.get('invocation', {})
    nodes = {row['nodeid']: row['outcome'] for row in invocation.get('node_outcomes', [])}
    if (invocation.get('phase') != 'final' or invocation.get('outcome') != 'PASS'
            or not descriptor.get('nodeid') or nodes.get(descriptor['nodeid']) != 'PASS'):
        raise ValueError('passing final counterexample test receipt missing')
    proof = record.get('counterexample', {})
    if set(proof) not in ({'classification', 'valid'}, {'classification', 'valid', 'public_input_pointer'}):
        raise ValueError('closed counterexample receipt missing')
    if proof['classification'] != classification:
        raise ValueError('counterexample schema provenance changed')
    valid = proof['valid']
    gateway = record['gateway']
    if (gateway['argv'] != binding.get('input', {}).get('gateway_argv') or not gateway['argv']
            or gateway['exit_code'] != 2 or gateway['payload'].get('ok') is not False
            or 'agent_result' in gateway['payload'] or valid['gateway']['exit_code'] != 0
            or valid['gateway']['payload'].get('ok') is not True):
        raise ValueError('public failure and successful counterpart receipts missing')
    version, host, build, kind, uri = branch['route'].split('|')
    if kind != 'function':
        raise ValueError('counterexample requires a public function receipt')
    for receipt in (record, valid):
        infos = [call['result'] for call in receipt['native_calls'] if call['uri'] == 'ak.wwise.core.getInfo']
        if len(infos) != 1 or native_host_context(infos[0], 'isCommandLine') != {'version': version, 'host': host, 'build': build}:
            raise ValueError('counterexample actual host/build context mismatch')
    section = branch['pointer'].split('/')[1]
    if section not in ('argsSchema', 'optionsSchema', 'resultSchema'):
        raise ValueError('counterexample section remains unsupported')
    native_section = {'argsSchema': 'args', 'optionsSchema': 'options', 'resultSchema': 'result'}[section]
    dispatch = binding.get('dispatch_pointer', '')
    # A fixed dispatch list occurrence is required; aliases cannot change arrays.
    import re
    if not re.fullmatch(r'/native_calls/[0-9]+', dispatch):
        raise ValueError('exact counterexample target dispatch missing')
    observation = exact_observation_pointer(branch, binding, dispatch, native_section, reference_edges)
    good_call = pointer_value(valid, dispatch)
    if good_call['uri'] != uri or len([call for call in valid['native_calls'] if call['uri'] == uri]) != 1:
        raise ValueError('valid counterpart target route mismatch')
    good_value = pointer_value(valid, observation)
    parent = {**branch, 'pointer': classification['parent_pointer'], 'shape_sha256': classification['parent_schema_sha256']}
    validate_native_alternative(root, parent, good_value, require_known=True)
    if _same(good_value, classification['candidate']):
        raise ValueError('valid counterpart must change the selected candidate')
    assertion = record.get('branch_assertions', {}).get(branch['id'], {})
    if assertion.get('native_route') != branch['route'] or assertion.get('native_shape_sha256') != branch['shape_sha256']:
        raise ValueError('counterexample exact branch assertion missing')
    if section == 'resultSchema':
        if set(proof) != {'classification', 'valid'} or gateway['argv'] != valid['gateway']['argv']:
            raise ValueError('result counterexample must reuse the same public input')
        bad_call = pointer_value(record, dispatch)
        if bad_call['uri'] != uri or len([call for call in record['native_calls'] if call['uri'] == uri]) != 1:
            raise ValueError('malformed result never reached exact target dispatch')
        if not _same(pointer_value(record, observation), classification['candidate']):
            raise ValueError('exact rejected result candidate missing')
        expected = deepcopy(valid['native_calls'])
        relative = observation[len('/native_calls'):]
        owner, _, token = relative.rpartition('/')
        container = pointer_value(expected, owner)
        container[int(token) if isinstance(container, list) else token.replace('~1', '/').replace('~0', '~')] = classification['candidate']
        if record['native_calls'] != expected:
            raise ValueError('result counterpart changes another native field or call')
        # Match the validator's actual structured result path, not any prose mentioning the field.
        native_path = observation[len(dispatch) + 1:].split('/')
        error_field = native_path[0] + ''.join('[' + t + ']' if t.isdigit() else '.' + t.replace('~1', '/').replace('~0', '~') for t in native_path[1:])
        if not _field_error(gateway['payload'], error_field, native=True):
            raise ValueError('Gateway failure is not attributed to the selected native result field')
        expected_check = {'pointer': observation, 'equals': classification['candidate']}
    else:
        if any(call['uri'] == uri for call in record['native_calls']):
            raise ValueError('invalid public choice reached target dispatch')
        input_pointer = proof.get('public_input_pointer', '')
        if not re.fullmatch(r'/gateway/argv/[0-9]+', input_pointer):
            raise ValueError('exact invalid public choice occurrence missing')
        index = int(input_pointer.rsplit('/', 1)[1])
        if index < 1 or not gateway['argv'][index - 1].startswith('--'):
            raise ValueError('closed public choice flag missing')
        public_field = gateway['argv'][index - 1][2:].replace('-', '_')
        if not _same(pointer_value(record, input_pointer), classification['candidate']):
            raise ValueError('invalid public choice differs from selected candidate')
        good_argv = valid['gateway']['argv']
        expected_argv = deepcopy(good_argv)
        expected_argv[index] = classification['candidate']
        if gateway['argv'] != expected_argv or not _field_error(gateway['payload'], public_field):
            raise ValueError('public argument failure is not causal to the selected choice')
        if gateway['payload'].get('error_code') != 'BUSINESS_ENUM_INVALID':
            raise ValueError('closed public choice enum rejection missing')
        expected_check = {'pointer': input_pointer, 'equals': classification['candidate']}
    if expected_check not in assertion.get('checks', []):
        raise ValueError('exact counterexample candidate check missing')
