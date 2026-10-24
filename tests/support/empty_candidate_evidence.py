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
    """Program rejection only; positive/native/business requirements are separate."""
    from tests.maintenance.branch_audit_completion import (pointer_value, exact_observation_pointer,
        native_host_context, validate_native_alternative)
    import re
    if (category != 'program' or classification['status'] != 'rejected'
            or binding.get('disposition') != 'schema_counterexample'
            or binding.get('empty_candidate') != classification
            or record.get('candidate_sha256') != candidate or record.get('scope_kind', 'product') != scope_kind):
        raise ValueError('exact current rejected-candidate program context missing')
    if (record.get('source_context') != counterexample_source_context(root)
            or record.get('phase_reports') != dict.fromkeys(('setup', 'call', 'teardown'), 'passed')):
        raise ValueError('current source closure and successful final phases missing')
    invocation = record.get('invocation', {})
    nodes = {row['nodeid']: row['outcome'] for row in invocation.get('node_outcomes', [])}
    if (invocation.get('phase') != 'final' or invocation.get('outcome') != 'PASS'
            or not descriptor.get('nodeid') or nodes.get(descriptor['nodeid']) != 'PASS'):
        raise ValueError('passing final counterexample test receipt missing')
    proof = record.get('counterexample', {})
    section = branch['pointer'].split('/')[1]
    if section not in ('argsSchema', 'optionsSchema', 'resultSchema'):
        raise ValueError('counterexample section remains unsupported')
    result_case = section == 'resultSchema'
    expected_keys = {'classification', 'valid'} if result_case else {'classification', 'valid', 'compiled', 'public_input_pointer'}
    if set(proof) != expected_keys or proof['classification'] != classification:
        raise ValueError('closed counterexample receipt or schema provenance changed')
    valid, gateway = proof['valid'], record['gateway']
    if (gateway['argv'] != binding.get('input', {}).get('gateway_argv') or not gateway['argv']
            or gateway['exit_code'] != 2 or valid['gateway']['exit_code'] != 0
            or valid['gateway']['payload'].get('ok') is not True):
        raise ValueError('public failure and successful counterpart receipts missing')
    version, host, build, kind, uri = branch['route'].split('|')
    if kind != 'function':
        raise ValueError('counterexample requires a public function receipt')
    def check_host(receipt):
        infos = [call['result'] for call in receipt['native_calls'] if call['uri'] == 'ak.wwise.core.getInfo']
        if not 1 <= len(infos) <= 8 or any(native_host_context(info, 'isCommandLine') != {'version': version, 'host': host, 'build': build} for info in infos):
            raise ValueError('counterexample actual host/build context mismatch: ' + repr([native_host_context(info, 'isCommandLine') for info in infos]))
    check_host(valid)
    native_section = {'argsSchema': 'args', 'optionsSchema': 'options', 'resultSchema': 'result'}[section]
    dispatch = binding.get('dispatch_pointer', '')
    observation = exact_observation_pointer(branch, binding, dispatch, native_section, reference_edges)
    assertion = record.get('branch_assertions', {}).get(branch['id'], {})
    if assertion.get('native_route') != branch['route'] or assertion.get('native_shape_sha256') != branch['shape_sha256']:
        raise ValueError('counterexample exact branch assertion missing')
    if result_case:
        check_host(record)
        if (not isinstance(gateway['payload'], dict) or gateway['payload'].get('ok') is not False
                or 'agent_result' in gateway['payload'] or gateway['argv'] != valid['gateway']['argv']):
            raise ValueError('result counterexample needs the same public input and failed result')
        if not re.fullmatch(r'/native_calls/[0-9]+', dispatch):
            raise ValueError('exact counterexample target dispatch missing')
        for receipt in (record, valid):
            call = pointer_value(receipt, dispatch)
            if call['uri'] != uri or len([call for call in receipt['native_calls'] if call['uri'] == uri]) != 1:
                raise ValueError('malformed result never reached exact target dispatch')
        good_value = pointer_value(valid, observation)
        if not _same(pointer_value(record, observation), classification['candidate']):
            raise ValueError('exact rejected result candidate missing')
        expected = deepcopy(valid['native_calls'])
        relative = observation[len('/native_calls'):]
        owner, _, token = relative.rpartition('/')
        container = pointer_value(expected, owner)
        container[int(token) if isinstance(container, list) else token.replace('~1', '/').replace('~0', '~')] = classification['candidate']
        if record['native_calls'] != expected:
            raise ValueError('result counterpart changes another native field or call')
        native_path = observation[len(dispatch) + 1:].split('/')
        error_field = native_path[0] + ''.join('[' + t + ']' if t.isdigit() else '.' + t.replace('~1', '/').replace('~0', '~') for t in native_path[1:])
        if not _field_error(gateway['payload'], error_field, native=True):
            raise ValueError('Gateway failure is not attributed to the selected native result field')
        expected_check = {'pointer': observation, 'equals': classification['candidate']}
    else:
        # Closed CLI enum grammar can reject before even opening a connection.
        # Preserve argparse's actual stderr/exit status, never invent error JSON.
        if gateway['payload'] is not None or record['native_calls'] or gateway.get('stdout') != '':
            raise ValueError('invalid closed public choice must fail before any dispatch')
        input_pointer = proof['public_input_pointer']
        if not re.fullmatch(r'/gateway/argv/[0-9]+', input_pointer):
            raise ValueError('exact invalid public choice occurrence missing')
        index = int(input_pointer.rsplit('/', 1)[1])
        if index < 1 or not gateway['argv'][index - 1].startswith('--'):
            raise ValueError('closed public choice flag missing')
        flag = gateway['argv'][index - 1]
        if not _same(pointer_value(record, input_pointer), classification['candidate']):
            raise ValueError('invalid public choice differs from selected candidate')
        expected_argv = deepcopy(valid['gateway']['argv'])
        expected_argv[index] = classification['candidate']
        error_line = r'(?m)^.*error: argument ' + re.escape(flag) + r": invalid choice: " + re.escape(repr(classification['candidate'])) + r' \(choose from .+\)$'
        if gateway['argv'] != expected_argv or not re.search(error_line, gateway.get('stderr', '')):
            raise ValueError('public parser failure is not causal to the selected choice')
        compiled = proof['compiled']
        check_host(compiled)
        if (compiled['gateway']['exit_code'] != 0 or compiled['gateway']['payload'].get('ok') is not True
                or any(call['uri'] == uri for call in valid['native_calls'] + compiled['native_calls'])):
            raise ValueError('valid counterpart must be a successful immutable public preview')
        request = compiled['gateway']['payload']['agent_result']['request']
        expected_dispatch = '/counterexample/compiled/gateway/payload/agent_result/request/arguments'
        if (dispatch != expected_dispatch or request.get('contract') != 'waapi-skill.operation-request/v1'
                or request.get('operation') != 'waapi.call' or request.get('version') != version
                or request['arguments'].get('api') != uri
                or compiled['gateway']['payload'].get('executed') is not False):
            raise ValueError('counterpart changes selected compiler route or dispatch')
        # The accepted declaration and preview must bind the same durable Draft.
        good_argv, compiled_argv = valid['gateway']['argv'], compiled['gateway']['argv']
        if 'draft-declare-runtime-control-plan' not in good_argv or 'preview-from-draft' not in compiled_argv:
            raise ValueError('closed public declaration/preview counterpart missing')
        draft = good_argv[good_argv.index('draft-declare-runtime-control-plan') + 1]
        if (compiled_argv[compiled_argv.index('preview-from-draft') + 1] != draft
                or valid['gateway']['payload']['draft']['draft_id'] != draft
                or valid['gateway']['payload']['draft']['binding'] != {**valid['gateway']['payload']['draft']['binding'], 'operation': uri, 'version': version}
                or good_argv[good_argv.index('--task-authority') + 1] != compiled_argv[compiled_argv.index('--task-authority') + 1]
                or good_argv[:good_argv.index('draft-declare-runtime-control-plan')] != compiled_argv[:compiled_argv.index('preview-from-draft')]):
            raise ValueError('counterpart changes durable public declaration context')
        good_value = pointer_value(record, observation)
        expected_check = {'pointer': input_pointer, 'equals': classification['candidate']}
    parent = {**branch, 'pointer': classification['parent_pointer'], 'shape_sha256': classification['parent_schema_sha256']}
    validate_native_alternative(root, parent, good_value, require_known=True)
    if _same(good_value, classification['candidate']):
        raise ValueError('valid counterpart must change the selected candidate')
    checks = assertion.get('checks', [])
    if expected_check not in checks:
        raise ValueError('exact counterexample candidate check missing')
    for check in checks:
        if set(check) != {'pointer', 'equals'} or not _same(pointer_value(record, check['pointer']), check['equals']):
            raise ValueError('counterexample assertion does not match preserved receipt')


def counterexample_source_context(root):
    """Exact current packaged sources plus this producer/consumer closure."""
    import subprocess
    paths = subprocess.check_output(['git', 'ls-files', '--', 'skills/waapi-skill'], cwd=root, text=True).splitlines()
    paths += ['tests/maintenance/branch_coverage_audit.py', 'tests/maintenance/branch_audit_completion.py',
        'tests/support/empty_candidate_evidence.py', 'tests/unit/test_empty_candidate_evidence.py',
        'tests/unit/test_runtime_business_gateway.py', 'tests/unit/test_console_log_observer_gateway.py',
        'tests/support/gateway_config.py', 'tests/support/exact_evidence_finalization.py', 'tests/conftest.py']
    # The reviewed log producer can compose this writer after its separate merge.
    # These closed optional historical/current dependencies are never a caller
    # supplied source allowlist; adding/changing any present file changes context.
    paths += [name for name in ('tests/support/runtime_remaining_evidence.py',
        'tests/unit/test_runtime_log_branch_evidence.py', 'tests/support/runtime_log_retained_evidence.py',
        'tests/support/runtime_observation_evidence.py',
        'tests/fixtures/runtime/runtime-remaining-policy-r127.json',
        'tests/fixtures/runtime-log/r122-category.json', 'tests/fixtures/runtime-log/r122-original.json.gz',
        'tests/fixtures/runtime-log/r122-support.json', 'tests/fixtures/runtime-log/retained-log-support.json') if (root / name).is_file()]
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sorted(set(paths))}


def write_counterexample_bundle(output, record, *, branch, binding, inventory, root, nodeid, phase_reports, source_context):
    """Ordinary portable index, published by the existing pytest finalizer.

    No new attachment, native category, descriptor rewriting, or implied parent
    credit. Filename namespace derives from the immutable complete branch ID.
    """
    from pathlib import Path
    if (phase_reports != dict.fromkeys(('setup', 'call', 'teardown'), 'passed')
            or source_context != counterexample_source_context(root)):
        raise ValueError('counterexample publication needs successful phases and unchanged current sources')
    classification = classify_empty_candidate(root, branch)
    if classification is None or classification['status'] != 'rejected' or binding.get('empty_candidate') != classification:
        raise ValueError('counterexample publisher requires exact rejected-candidate binding')
    candidate = inventory['native_coverage']['candidate_sha256']
    program = deepcopy(record)
    program.update(candidate_sha256=candidate, source_context=source_context, phase_reports=phase_reports,
        invocation={'phase': 'final', 'outcome': 'PASS', 'node_outcomes': [{'nodeid': nodeid, 'outcome': 'PASS'}]})
    edges = {row['id']: row for row in inventory['native_coverage']['obligations'] if row['kind'] == 'reference'}
    validate_counterexample(program, {'nodeid': nodeid}, branch, classification, candidate, 'program',
                            program.get('scope_kind', 'product'), binding, root, edges)
    output = Path(output)
    prefix = 'empty-counterexample-' + hashlib.sha256(branch['id'].encode()).hexdigest() + '-'
    names = {kind: prefix + kind + '.json' for kind in ('program', 'bindings', 'requirements', 'index')}
    if any((output / name).exists() for name in names.values()):
        raise ValueError('counterexample publication filename collision')
    output.mkdir(parents=True, exist_ok=True)
    def write(kind, value):
        raw = (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + '\n').encode()
        (output / names[kind]).write_bytes(raw)
        return {'artifact': names[kind], 'sha256': hashlib.sha256(raw).hexdigest()}
    program_descriptor = write('program', program)
    published = deepcopy(binding)
    published['evidence'] = {'program': {**program_descriptor, 'nodeid': nodeid}}
    bindings_descriptor = write('bindings', {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': {branch['id']: published}})
    policy = {'native_shape_sha256': branch['shape_sha256'], 'categories': ['program'], 'empty_candidate': classification,
              'reason': 'Resolved reflected schema rejects this concrete synthetic candidate; exact public counterexample program proof required. No native absence/effect or parent credit.'}
    requirements_descriptor = write('requirements', {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {branch['id']: policy}})
    write('index', {'contract': 'waapi-skill.branch-evidence-index/v1', 'base': '.', 'entries': [
        {'id': prefix[:-1], 'bindings': bindings_descriptor, 'origin': {'bindings': bindings_descriptor,
            'program': program_descriptor, 'requirements': requirements_descriptor, 'capture': program_descriptor}}]})
    return output / names['index']
