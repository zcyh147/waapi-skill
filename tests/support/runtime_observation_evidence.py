"""Portable read observations for the existing branch audit, never execution.

Original native archives retain their exact bytes and verdicts. This adapter
only adds locator transport and exact public-read assertions; mutations and
qualified non-PASS producers are deliberately outside its contract.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'artifact': path.name, 'sha256': sha(path.read_bytes())}


def program_source_context(root=audit.ROOT, *, flow=None):
    import subprocess
    names = subprocess.check_output(['git', 'ls-files', '--', 'skills/waapi-skill'],
        cwd=root, text=True).splitlines()
    dependencies = ['tests/support/runtime_observation_evidence.py',
        'tests/support/console_runtime_read_evidence.py',
        'tests/unit/test_console_runtime_read_evidence.py',
        'tests/fixtures/runtime-console-reads/r125-profiles.json',
        'tests/support/qualified_runtime_read_evidence.py',
        'tests/unit/test_qualified_runtime_read_evidence.py',
        'tests/unit/test_runtime_observation_branch_evidence.py',
        'tests/unit/test_rtpc_field_branch_evidence.py',
        'tests/unit/test_runtime_business_gateway.py', 'tests/support/gateway_config.py',
        'tests/support/exact_evidence_finalization.py', 'tests/conftest.py',
        'tests/fixtures/runtime/runtime-opaque-policy-r126.json',
        'tests/maintenance/branch_coverage_audit.py', 'tests/maintenance/branch_audit_completion.py']
    if flow in {'ak.wwise.core.log.' + name for name in ('get','addItem','clear')}:
        dependencies.extend(('tests/support/runtime_remaining_evidence.py',
            'tests/support/runtime_log_retained_evidence.py',
            'tests/fixtures/runtime-log/retained-log-support.json',
            'tests/fixtures/runtime/runtime-remaining-policy-r127.json',
            'tests/fixtures/runtime-log/r122-support.json',
            'tests/unit/test_runtime_log_branch_evidence.py'))
    if flow in {'ak.wwise.core.profiler.' + name for name in ('getVoices', 'getBusses', 'getAudioObjects', 'getGameObjects')}:
        dependencies.extend(('tests/support/fixed_runtime_read_evidence.py', 'tests/unit/test_fixed_runtime_read_branch_evidence.py'))
    if flow == 'ak.wwise.core.profiler.getLoadedMedia':
        dependencies.extend(('tests/support/loaded_media_runtime_evidence.py',
            'tests/unit/test_loaded_media_runtime_evidence.py', 'tests/support/fixed_runtime_read_evidence.py',
            'tests/fixtures/runtime-loaded-media/support-review.json',
            'tests/unit/test_loaded_media_composite_evidence.py',
            'tests/fixtures/runtime-loaded-media/composite-review.json',
            'tests/unit/test_console_loaded_media_evidence.py',
            'tests/fixtures/runtime-loaded-media/console-review.json'))
    if flow == 'ak.wwise.core.profiler.getVoiceContributions':
        dependencies.append('tests/unit/test_contribution_branch_evidence.py')
    return {group: {name: sha((root / name).read_bytes()) for name in sorted(paths)}
            for group, paths in (('packaged', names), ('capture', dependencies))}


def write_program_receipt(path, gateway, native_call, *, nodeid, phase_reports, source_context, native_reads=None, public_calls=None):
    if phase_reports != {'setup': 'passed', 'call': 'passed', 'teardown': 'passed'}:
        raise ValueError('Runtime program proof requires successful setup/call/teardown')
    if gateway['exit_code'] != 0 or gateway['payload'].get('ok') is not True:
        raise ValueError('Runtime program proof requires successful public Gateway read')
    if source_context != program_source_context(flow=native_call['uri']):
        raise ValueError('Runtime program source changed during public read')
    return write_json(path, {'contract': 'waapi-skill.runtime-read-program/v1',
        'phase_reports': phase_reports, 'nodeid': nodeid,
        'source_context': source_context, 'source_unchanged': True,
        'gateway': gateway, 'native_call': native_call,
        **({'native_reads': native_reads} if native_reads is not None else {}),
        **({'public_calls': public_calls} if public_calls is not None else {})})



def register_runtime_program_output(item, path, **inputs):
    """Write from the actual public execution only after this node's final reports."""
    from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
    register_exact_evidence_finalizer(item, lambda phases: write_program_receipt(
        path, nodeid=item.nodeid, phase_reports=phases, **inputs))


def archive_reader(descriptor, base):
    """Resolve original POSIX archive identities without touching their old paths."""
    import base64
    import gzip
    import io
    from pathlib import PurePosixPath
    _portable_descriptor(descriptor, base)
    path = base / descriptor['artifact']
    raw = path.read_bytes()
    if len(raw) > 4_000_000 or sha(raw) != descriptor['sha256']:
        raise ValueError('Runtime archive digest/size mismatch')
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            content = stream.read(16_000_001)
    except (OSError, EOFError) as exc:
        raise ValueError('Runtime compressed archive is corrupt') from exc
    if len(content) > 16_000_000:
        raise ValueError('Runtime archive uncompressed ceiling exceeded')
    archive = json.loads(content)
    if set(archive) != {'contract', 'files'} or archive['contract'] != 'waapi-skill.runtime-observation-archive/v1':
        raise ValueError('Closed runtime observation archive required')
    files = archive['files']
    if not isinstance(files, dict) or not 1 <= len(files) <= 512:
        raise ValueError('Bounded runtime archive files required')
    for name in files:
        path = PurePosixPath(name)
        if not path.is_absolute() or '..' in path.parts or str(path) != name:
            raise ValueError('Original runtime archive identity differs')
    def read(name):
        if name not in files:
            raise ValueError('Original runtime artifact missing from portable closure')
        return base64.b64decode(files[name], validate=True)
    return read


def _proof(binding, base):
    proof = completion.read_sealed_artifact(binding['runtime_observation_attachment'], base)
    expected = {'contract', 'branch_id', 'native_shape_sha256', 'mapping', 'native_run',
                'archive', 'capture', 'capture_original_path', 'program_capture', 'relevant_sources'}
    if set(proof) not in (expected, expected | {'source_review'}) or proof['contract'] != 'waapi-skill.runtime-observation-proof/v1':
        raise ValueError('Closed runtime read observation proof required')
    for key in ('native_run', 'archive', 'capture', 'program_capture'):
        _portable_descriptor(proof[key], base)
    return proof


def _portable_descriptor(descriptor, base):
    path = Path(descriptor['artifact'])
    if (path.is_absolute() or '..' in path.parts
            or not (base / path).resolve().is_relative_to(base.resolve())):
        raise ValueError('Runtime descriptor escapes portable bundle')


def validate_rtpc_program(record, binding, branch, root, reference_edges=None):
    """Apply actual read capture requirements to ordinary program evidence."""
    captured = record.get('runtime_read_program')
    if not isinstance(captured, dict):
        raise ValueError('RTPC program needs exact current public read capture')
    version, host, _, kind, uri = branch['route'].split('|')
    payload = captured['gateway']['payload']
    if (uri != RTPC_URI or kind != 'function'
            or captured.get('contract') != 'waapi-skill.runtime-read-program/v1'
            or captured.get('phase_reports') != dict.fromkeys(('setup', 'call', 'teardown'), 'passed')
            or captured.get('source_unchanged') is not True
            or captured.get('source_context') != program_source_context(root)
            or record.get('relevant_sources') != captured['source_context']['packaged']
            or captured['gateway'] != record['gateway'] or captured['native_call'] != record['native_call']
            or captured['gateway']['argv'] != binding['input']['gateway_argv']
            or payload.get('is_command_line') != (host == 'wwise-console')
            or any(payload['schema_validation'][section]['version'] != version for section in ('request', 'result'))):
        raise ValueError('RTPC program needs exact current public read capture')
    argv = captured['gateway']['argv']
    position = argv[argv.index('--profiler-position') + 1]
    from wwise_waapi.runtime_inspection_business import _profiler_time, RuntimeInspectionBusinessError
    try:
        requested = _profiler_time(position)
        reported = _profiler_time(payload['agent_result']['profiler_position'])
    except (RuntimeInspectionBusinessError, TypeError) as exc:
        raise ValueError('RTPC capture must satisfy the public profiler-position contract') from exc
    native_time = record['native_call']['args']['time']
    if type(requested) is int:
        if type(native_time) is not int or type(reported) is not int or native_time != requested or reported != requested:
            raise ValueError('RTPC numeric profiler position must match native and public time')
    elif requested != reported:
        # Recognized cursor choices remain a separate normalization path;
        # this does not prove its unresolved two-read cursor branches.
        raise ValueError('RTPC cursor position must retain its explicit reported choice')
    native_rows = record['native_call']['result']['return']
    public_rows = record['gateway']['payload']['agent_result']['return']
    # These complete RTPC reads copy the entire array without transformation.
    # Canonical JSON also distinguishes int/float/bool values that Python ==
    # would otherwise conflate when comparing nested containers.
    if (payload['agent_result'].get('complete') is not True
            or not isinstance(native_rows, list) or not isinstance(public_rows, list)
            or audit.digest(native_rows) != audit.digest(public_rows)):
        raise ValueError('Program must preserve complete native/public RTPC return arrays')
    if branch['pointer'] == '/resultSchema' or branch['pointer'].startswith('/resultSchema/'):
        pointer = (binding['program_observation_pointer'] if binding.get('runtime_observation_attachment')
            else binding['observation_pointer'])
        parent = '/native_call/result/return'
        result_root = branch['pointer'] in {'/resultSchema', '/resultSchema/additionalProperties'}
        expected_public = ('/gateway/payload/agent_result' if result_root else pointer.replace(
            '/native_call/result', '/gateway/payload/agent_result', 1))
        if ((pointer != '/native_call/result' if result_root else pointer != parent and not pointer.startswith(parent + '/'))
                or binding['gateway_observation_pointer'] != expected_public):
            raise ValueError('RTPC result needs the corresponding exact public field occurrence')
        if branch['kind'] == 'optional_presence' and branch.get('value') == 'absent':
            public_pointer = binding['gateway_observation_pointer']
            native_parent = completion.pointer_value(record, pointer.rsplit('/', 1)[0])
            public_parent = completion.pointer_value(record, public_pointer.rsplit('/', 1)[0])
            field = pointer.rsplit('/', 1)[1]
            if (not isinstance(native_parent, dict) or not isinstance(public_parent, dict)
                    or field in native_parent or field in public_parent):
                raise ValueError('RTPC absence needs an existing native/public row and same absent field')
    if branch['kind'] == 'constraint' and branch['pointer'].startswith('/resultSchema/'):
        _validate_rtpc_scalar(record, binding, branch, root)
    if branch['pointer'] in RTPC_STRUCTURE_POINTERS:
        _validate_rtpc_structure(record, binding, branch, root)
    return _validate_rtpc_cursor(record, binding, branch, root, reference_edges or {})


def _validate_rtpc_cursor(record, binding, branch, root, reference_edges):
    """Return a branch-bound construction proof for the closed cursor chain."""
    cursor_time = '/argsSchema/@definition/waapi_definitions.json/definitions/cursorTime'
    cursor = '/argsSchema/@definition/waapi_definitions.json/definitions/profilerCursor'
    allowed = {cursor_time + '/oneOf/1', cursor_time + '/oneOf/1/$ref', cursor,
               cursor + '/enum/0', cursor + '/enum/1'}
    if branch['pointer'] not in allowed:
        return None
    from wwise_waapi.native_catalog import load_native_catalog
    version, host, build, _, _ = branch['route'].split('|')
    catalog = load_native_catalog(version, host, root=root / 'skills/waapi-skill/resources/native-catalog')
    _, rest = branch['pointer'].split('/@definition/', 1)
    document, suffix = rest.split('/', 1)
    node = completion.pointer_value(catalog['definitions']['documents'][document], '/' + suffix)
    first = branch['route'] + '|/argsSchema/properties/time/$ref'
    second = branch['route'] + '|' + cursor_time + '/oneOf/1/$ref'
    chain = [first] if branch['pointer'].startswith(cursor_time) else [first, second]
    if (catalog['provenance']['build'] != build or audit.digest(node) != branch['shape_sha256']
            or binding.get('reference_chain') != chain
            or reference_edges[first]['reference']['target'] != branch['route'] + '|' + cursor_time
            or reference_edges[second]['reference']['target'] != branch['route'] + '|' + cursor):
        raise ValueError('RTPC exact cursor normalization branch/reflection differs')
    # Validate the original RTPC field/reference context independently of the
    # intermediate getCursorTime occurrence used for construction evidence.
    completion.exact_observation_pointer(branch,
        {**binding, 'observation_pointer': '/native_call/args/time'}, '/native_call', 'args', reference_edges)
    captured = record['runtime_read_program']
    trace = captured.get('native_reads')
    if (not isinstance(trace, list) or not 2 <= len(trace) <= 16
            or any(set(row) != {'ordinal', 'uri', 'args', 'options', 'result'}
                or type(row['ordinal']) is not int or row['ordinal'] != index for index, row in enumerate(trace))):
        raise ValueError('RTPC ordered cursor normalization trace missing or invalid')
    relevant = [row for row in trace if row['uri'] in {RTPC_URI, 'ak.wwise.core.profiler.getCursorTime'}]
    argv = record['gateway']['argv']
    choice = argv[argv.index('--profiler-position') + 1]
    enum = {'capture-latest': 'capture', 'user-cursor': 'user'}.get(choice)
    if enum is None or len(relevant) != 2:
        raise ValueError('RTPC ordered cursor normalization trace requires one owned two-read chain')
    source, final = relevant
    native = record['native_call']
    time = source['result'].get('return') if type(source['result']) is dict else None
    if (source['uri'] != 'ak.wwise.core.profiler.getCursorTime' or source['args'] != {'cursor': enum}
            or source['options'] != {} or source['result'] != {'return': time}
            or type(time) is not int or time < 0 or final['uri'] != RTPC_URI
            or source['ordinal'] >= final['ordinal'] or final['args'] != {'time': time}
            or type(final['args'].get('time')) is not int or type(native['args'].get('time')) is not int
            or final['options'] != {} or native['args'] != {'time': time} or native['options'] != {}
            or audit.digest({key: final[key] for key in ('uri', 'args', 'options', 'result')}) != audit.digest(native)
            or record['gateway']['payload']['agent_result']['profiler_position'] != choice):
        raise ValueError('RTPC ordered cursor normalization trace differs from actual public construction')
    expected = f"/runtime_read_program/native_reads/{source['ordinal']}/args/cursor"
    if (binding['observation_pointer'] != expected
            or binding['gateway_observation_pointer'] != '/gateway/payload/agent_result/profiler_position'
            or branch['kind'] == 'enum_value' and (type(node) is not str or node != enum)):
        raise ValueError('RTPC exact cursor normalization occurrence/choice differs')
    return {'branch_id': branch['id'], 'observation_pointer': expected}


def _validate_rtpc_scalar(record, binding, branch, root):
    """Check the exact pinned predicate at its independently mapped scalar."""
    import re
    from wwise_waapi.native_catalog import load_native_catalog
    version, host, _, _, _ = branch['route'].split('|')
    catalog = load_native_catalog(version, host, root=root / 'skills/waapi-skill/resources/native-catalog')
    pointer = branch['pointer']
    if '/@definition/' not in pointer:
        raise ValueError('RTPC pinned scalar predicate must have its exact definition')
    _, rest = pointer.split('/@definition/', 1)
    document, suffix = rest.split('/', 1)
    predicate = completion.pointer_value(catalog['definitions']['documents'][document], '/' + suffix)
    if audit.digest(predicate) != branch['shape_sha256']:
        raise ValueError('RTPC pinned scalar predicate shape differs')
    predicate_kind = pointer.rsplit('/', 1)[1]
    field, index = (('gameObjectId', 0 if predicate_kind == 'minimum' else 1)
        if predicate_kind in {'minimum', 'maximum'} else
        ('id', 0) if '/definitions/guid/pattern' in pointer else ('name', 1))
    definition = 'gameObject' if field == 'gameObjectId' else 'guid' if field == 'id' else 'uniqueName'
    if not pointer.endswith('/definitions/' + definition + '/' + predicate_kind):
        raise ValueError('RTPC pinned scalar predicate is outside approved scope')
    expected = f'/native_call/result/return/{index}/{field}'
    if binding['observation_pointer'] != expected:
        raise ValueError('RTPC pinned scalar predicate occurrence differs')
    observed = completion.pointer_value(record, expected)
    valid = (type(observed) is int and observed == predicate if field == 'gameObjectId'
        else type(observed) is str and re.search(predicate, observed) is not None)
    if not valid:
        raise ValueError('RTPC pinned scalar predicate failed')
    if field == 'name':
        metadata = record['gateway']['payload']['schema_validation']['result']
        expected_rule = {'rule': 'rtpc-legacy-name-label-preservation',
            'section': '$.return[*].name', 'definition': 'waapi_definitions.json#/definitions/uniqueName',
            'reflected_pattern': predicate, 'enforced_type': 'string', 'pattern_enforced': False,
            'behavior': 'Preserve native labels unchanged, including labels outside the reflected pattern'}
        broader = completion.pointer_value(record, '/native_call/result/return/2/name')
        if (version == '2025.1' or metadata.get('compatibility_rules') != [expected_rule]
                or type(broader) is not str or re.search(predicate, broader) is not None):
            raise ValueError('RTPC legacy matching-name predicate needs explicit broader-label compatibility')


def _validate_rtpc_structure(record, binding, branch, root):
    """Prove only the addressed native container, never its descendants."""
    from wwise_waapi.native_catalog import load_native_catalog
    version, host, _, _, _ = branch['route'].split('|')
    catalog = load_native_catalog(version, host, root=root / 'skills/waapi-skill/resources/native-catalog')
    schema = catalog['schemas'][RTPC_URI]
    node = completion.pointer_value(schema, branch['pointer'])
    if audit.digest(node) != branch['shape_sha256']:
        raise ValueError('RTPC structural predicate reflection shape differs')
    if branch['pointer'].endswith('/additionalProperties'):
        if node is not False:
            raise ValueError('RTPC structural predicate requires exact closed native properties')
        node = completion.pointer_value(schema, branch['pointer'].rsplit('/', 1)[0])
    pointer = (binding['program_observation_pointer'] if binding.get('runtime_observation_attachment')
        else binding['observation_pointer'])
    expected = RTPC_STRUCTURE_POINTERS[branch['pointer']]
    if pointer != expected:
        raise ValueError('RTPC exact native structural observation differs')
    observed = completion.pointer_value(record, expected)
    if node.get('type') == 'object':
        if (type(observed) is not dict or not set(node.get('required', ())) <= observed.keys()
                or node.get('additionalProperties') is False and not observed.keys() <= node.get('properties', {}).keys()):
            raise ValueError('RTPC exact native object structure predicate failed')
    elif node.get('type') == 'array':
        if type(observed) is not list:
            raise ValueError('RTPC exact native array structure predicate failed')
    else:
        raise ValueError('RTPC structural predicate is outside approved container scope')


def validate_runtime_evidence(record, binding, branch, category, base, root, reference_edges=None):
    from tests.support.runtime_remaining_evidence import selected as remaining_selected, validate_evidence as validate_remaining
    if remaining_selected(branch['id'], root):
        return validate_remaining(record,binding,branch,category,base,root,reference_edges or {})
    from tests.support.console_runtime_read_evidence import selected, validate_evidence as validate_console_read
    if selected(branch['id'], root):
        return validate_console_read(record,binding,branch,category,base,root,reference_edges or {})
    if branch['route'].endswith('|function|ak.wwise.core.profiler.getLoadedMedia'):
        from tests.support.loaded_media_runtime_evidence import validate_evidence
        return validate_evidence(record, binding, branch, category, base, root, reference_edges or {})
    from tests.support.fixed_runtime_read_evidence import URIS, validate_evidence
    if branch['route'].split('|')[4] in URIS:
        return validate_evidence(record, binding, branch, category, base, root, reference_edges or {})
    if branch['route'].endswith('|function|ak.wwise.core.profiler.getVoiceContributions'):
        return validate_contribution_evidence(record, binding, branch, category, base, root, reference_edges or {})
    from wwise_waapi.runtime_inspection_business_contracts import runtime_inspection_business_read_operations
    # This adapter cannot accept mutation, absence, or qualified-failure credit.
    if category not in {'program', 'native'} or branch['route'].split('|')[4] not in runtime_inspection_business_read_operations():
        raise ValueError('Runtime attachment permits only existing public inspection reads')
    proof = _proof(binding, base)
    mapping = proof['mapping']
    if (proof['branch_id'] != branch['id'] or proof['native_shape_sha256'] != branch['shape_sha256']
            or mapping['branch_id'] != branch['id'] or mapping['native_shape_sha256'] != branch['shape_sha256']
            or not branch['pointer'].startswith('/resultSchema/')
            or binding['observation_pointer'] != mapping['native_pointer']
            or binding['program_observation_pointer'] != mapping['program_pointer']):
        raise ValueError('Runtime exact read branch mapping differs')
    chain = mapping.get('reference_chain', [])
    if binding.get('reference_chain', []) != chain:
        raise ValueError('Runtime exact reference-chain mapping differs')
    completion.exact_observation_pointer(branch,
        {'observation_pointer': mapping['program_pointer'], 'reference_chain': chain},
        '/native_call', 'result', reference_edges or {})
    completion.exact_observation_pointer(branch,
        {'observation_pointer': mapping['native_pointer'], 'reference_chain': chain},
        mapping['native_result_parent'], 'agent_result', reference_edges or {})
    captured = completion.read_sealed_artifact(proof['program_capture'], base)
    if (captured.get('contract') != 'waapi-skill.runtime-read-program/v1'
            or captured.get('phase_reports') != dict.fromkeys(('setup', 'call', 'teardown'), 'passed')
            or captured.get('source_unchanged') is not True
            or captured.get('source_context') != program_source_context(root)
            or captured['gateway']['argv'] != binding['input']['gateway_argv']):
        raise ValueError('Complete exact public program capture required')
    import hashlib
    sources = proof['relevant_sources']
    if not sources or sorted(sources) != sorted(binding['relevant_sources']):
        raise ValueError('Runtime source closure differs')
    for name, seal in sources.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != seal:
            raise ValueError('Runtime relevant source changed')
    if category == 'program':
        validate_rtpc_program({**record, 'runtime_read_program': captured}, binding, branch, root)
        if record['gateway'] != captured['gateway'] or record['native_call'] != captured['native_call']:
            raise ValueError('Runtime program changed original public receipt/construction')
        return
    read = archive_reader(proof['archive'], base)
    context = completion.read_category_run(proof['native_run'], base)
    completion.validate_authoring_batch_finalization(context['record'], base, read_bytes=read)
    if record['native_runs'] != [proof['native_run']] or record['observation_artifacts'] != {'capture': proof['capture']}:
        raise ValueError('Runtime native branch must retain original producer and observations')
    capture_raw = (base / proof['capture']['artifact']).read_bytes()
    if read(proof['capture_original_path']) != capture_raw or sha(capture_raw) != proof['capture']['sha256']:
        raise ValueError('Runtime observation differs from original node archive')
    capture = json.loads(capture_raw)
    if capture.get('complete') is not True or capture['candidate'] != context['candidate']:
        raise ValueError('Runtime original capture incomplete or stale')
    outcome = completion.pointer_value({'observations': {'capture': capture}},
        mapping['native_result_parent'].rsplit('/', 1)[0])
    if outcome.get('outcome') != 'PASS' or outcome.get('evidence', {}).get('complete') is not True:
        raise ValueError('Runtime exact read observation must be complete PASS')
    seal = json.loads(read(context['record']['categories'][0]['batch_finalization']['artifact']))
    node = json.loads(read(seal['observations'][proof['native_run']['nodeid']]['path']))
    original_sources = node['source_context']['sources']
    expected_sources = {k: v for k, v in original_sources.items() if k.startswith('skills/waapi-skill/')}
    if sources != expected_sources:
        validate_rtpc_source_review(proof.get('source_review', {}), expected_sources, branch, root, base)
    matching = [row for row in node['receipts'] if row['argv'] == binding['input']['gateway_argv']]
    if len(matching) != 1 or matching[0]['exit_code'] != 0 or matching[0]['payload'].get('ok') is not True:
        raise ValueError('Original native public Gateway receipt missing')
    original_result = matching[0]['payload']['agent_result']
    observed_result = completion.pointer_value({'observations': {'capture': capture}}, mapping['native_result_parent'] + '/agent_result')
    if original_result != observed_result:
        raise ValueError('Runtime observation changes original public result')
    assertion = record['branch_assertions'][branch['id']]
    if assertion['checks'] != mapping['native_checks']:
        raise ValueError('Runtime exact native assertion policy differs')


def attach_runtime_observations(descriptors, bindings, read, base, requirements, captures):
    if not isinstance(descriptors, list):
        raise ValueError('Closed runtime observation attachment list required')
    attached = set()
    for descriptor in descriptors:
        attachment = read(descriptor)
        if (set(attachment) != {'contract', 'branch_id', 'proof', 'evidence', 'native_equivalence'}
                or attachment['contract'] != 'waapi-skill.runtime-observation-attachment/v1'):
            raise ValueError('Closed runtime observation attachment required')
        identity = attachment['branch_id']
        if identity in attached or identity not in bindings:
            raise ValueError('Duplicate or unbound runtime observation')
        attached.add(identity)
        _portable_descriptor(attachment['evidence'], base)
        _portable_descriptor(attachment['native_equivalence'], base)
        binding = bindings[identity]
        proof = read(attachment['proof'])
        policy = requirements['branches'].get(identity, {})
        if (policy.get('categories') != ['program', 'native']
                or policy.get('native_shape_sha256') != binding['native_shape_sha256']
                or set(binding['evidence']) != {'program'}
                or captures[identity] != read(proof['program_capture'])):
            raise ValueError('Runtime observation requires exact reviewed program/native policy')
        observation_hashes = {'capture': proof['capture']['sha256']}
        from tests.support.fixed_runtime_read_evidence import URIS
        from tests.support.console_runtime_read_evidence import selected as selected_console_read
        from tests.support.runtime_remaining_evidence import selected as remaining_selected
        if remaining_selected(identity) or selected_console_read(identity) or identity.split('|')[4] in URIS | {'ak.wwise.core.profiler.getVoiceContributions', 'ak.wwise.core.profiler.getLoadedMedia'}:
            raw = proof['mapping']['raw_observation']
            _portable_descriptor(raw, base)
            observation_hashes['raw'] = raw['sha256']
        binding.update(runtime_observation_attachment=attachment['proof'],
            program_observation_pointer=proof['mapping']['program_pointer'],
            observation_pointer=proof['mapping']['native_pointer'],
            native_observations_sha256=observation_hashes,
            native_equivalence=attachment['native_equivalence'])
        binding['evidence']['native'] = attachment['evidence']


def write_bundle(output, program_path, originals, *, inventory):
    """Publish a single reviewed mapping; preserve all original native bytes."""
    import gzip
    import shutil
    captured = json.loads(Path(program_path).read_bytes())
    if captured.get('phase_reports') != dict.fromkeys(('setup', 'call', 'teardown'), 'passed'):
        raise ValueError('Runtime publication requires successful setup/call/teardown')
    if captured.get('source_context') != program_source_context():
        raise ValueError('Runtime program source is stale before publication')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    for name in ('original-category.json', 'original-capture.json', 'original-closure.json.gz'):
        shutil.copyfile(originals / name, output / name)
    def descriptor(name):
        return {'artifact': name, 'sha256': sha((output / name).read_bytes())}
    shutil.copyfile(program_path, output / 'program-capture.json')
    plan = json.loads((originals / 'mapping.json').read_bytes())
    identity = plan['branch_id']
    branch = next(row for row in inventory['native_coverage']['obligations'] if row['id'] == identity)
    public = next(row for row in inventory['routes'] if row['id'] == plan['public_route'])
    run = completion.read_category_run({**descriptor('original-category.json'), 'nodeid': plan['native_node']}, output)
    read = archive_reader(descriptor('original-closure.json.gz'), output)
    seal = json.loads(read(run['record']['categories'][0]['batch_finalization']['artifact']))
    original = json.loads(read(seal['observations'][plan['native_node']]['path']))
    original_sources = {k: v for k, v in original['source_context']['sources'].items() if k.startswith('skills/waapi-skill/')}
    sources = captured['source_context']['packaged']
    source_review = _write_rtpc_source_review(output, '', original_sources, captured,
        descriptor('original-capture.json'), branch, output / 'program-capture.json')
    candidate = inventory['native_coverage']['candidate_sha256']
    assertion = {'native_shape_sha256': branch['shape_sha256'], 'native_route': branch['route']}
    invocation = {'phase': 'final', 'outcome': 'PASS', 'node_outcomes': [{'nodeid': captured['nodeid'], 'outcome': 'PASS'}]}
    program = {'candidate_sha256': candidate, 'scope_kind': 'product', 'relevant_sources': sources,
        'gateway': captured['gateway'], 'native_call': captured['native_call'], 'invocation': invocation,
        'branch_assertions': {identity: {**assertion, 'checks': plan['program_checks']}}}
    program_descriptor = {**write_json(output / 'program.json', program), 'nodeid': captured['nodeid']}
    policy = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {identity: {
        'native_shape_sha256': branch['shape_sha256'], 'categories': ['program', 'native'],
        'reason': plan['requirements_reason']}}}
    policy_descriptor = write_json(output / 'requirements.json', policy)
    binding = {'branch_id': identity, 'native_shape_sha256': branch['shape_sha256'],
        'public_route': public['id'], 'public_route_sha256': audit.digest(public),
        'input': {'gateway_argv': captured['gateway']['argv'], 'selector': plan['program_pointer']},
        **{key: {'source': plan[key], 'selector': branch['pointer']} for key in ('construction', 'validation', 'verifier')},
        'dispatch_pointer': '/native_call', 'observation_pointer': plan['program_pointer'],
        'gateway_observation_pointer': plan['public_pointer'],
        'relevant_sources': sorted(sources), 'evidence': {'program': program_descriptor}}
    document = {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': {identity: deepcopy(binding)}}
    bindings_descriptor = write_json(output / 'bindings.json', document)
    native_run = {**descriptor('original-category.json'), 'nodeid': plan['native_node'],
        'observation_sha256': [descriptor('original-capture.json')['sha256']]}
    archived_paths = json.loads(gzip.decompress((output / 'original-closure.json.gz').read_bytes()))['files']
    capture_paths = [name for name in archived_paths if name.endswith('/' + plan['capture_filename'])]
    if len(capture_paths) != 1:
        raise ValueError('Runtime observation must select one exact original capture artifact')
    capture_path = capture_paths[0]
    proof = {'contract': 'waapi-skill.runtime-observation-proof/v1', 'branch_id': identity,
        'native_shape_sha256': branch['shape_sha256'], 'mapping': plan,
        'native_run': native_run, 'archive': descriptor('original-closure.json.gz'),
        'capture': descriptor('original-capture.json'), 'capture_original_path': capture_path,
        'program_capture': descriptor('program-capture.json'), 'relevant_sources': sources,
        **({'source_review': source_review} if source_review else {})}
    proof_descriptor = write_json(output / 'proof.json', proof)
    binding.update(runtime_observation_attachment=proof_descriptor,
        program_observation_pointer=plan['program_pointer'], observation_pointer=plan['native_pointer'],
        native_observations_sha256={'capture': descriptor('original-capture.json')['sha256']})
    native = {'candidate_sha256': candidate, 'scope_kind': 'product', 'evidence_kind': 'native_execution',
        'relevant_sources': sources, 'invocation': run['record']['invocation'], 'native_runs': [native_run],
        'observation_artifacts': {'capture': descriptor('original-capture.json')},
        'branch_assertions': {identity: {**assertion, 'checks': plan['native_checks']}}}
    native_descriptor = {**write_json(output / 'native.json', native), 'nodeid': plan['native_node']}
    equivalence = {'contract': 'waapi-skill.branch-evidence-equivalence/v1',
        'from_candidate': run['candidate'], 'to_candidate': candidate, 'branch_id': identity,
        'native_shape_sha256': branch['shape_sha256'], 'native_route': branch['route'],
        'evidence_sha256': native_run['sha256'], 'binding_semantics_sha256': audit.digest(completion.binding_semantics(binding)),
        'reviewed_reason': (RTPC_REVIEWED_SOURCE_REASON
            if source_review else 'All original packaged runtime/resource sources byte-identical; original finalized PASS retained.'),
        'sources': original_sources, **({'runtime_read_review': source_review} if source_review else {})}
    equivalence_descriptor = write_json(output / 'native-equivalence.json', equivalence)
    attachment = {'contract': 'waapi-skill.runtime-observation-attachment/v1', 'branch_id': identity,
        'proof': proof_descriptor, 'evidence': native_descriptor, 'native_equivalence': equivalence_descriptor}
    attachment_descriptor = write_json(output / 'attachment.json', attachment)
    return output / write_json(output / 'index.json', {'contract': 'waapi-skill.branch-evidence-index/v1', 'base': '.',
        'entries': [{'id': plan['entry_id'], 'bindings': bindings_descriptor,
            'origin': {'bindings': bindings_descriptor, 'program': descriptor('program.json'),
                       'requirements': policy_descriptor, 'capture': descriptor('program-capture.json')}}],
        'runtime_observation_attachments': [attachment_descriptor]})['artifact']


RTPC_URI = 'ak.wwise.core.profiler.getRTPCs'
RTPC_STRUCTURE_POINTERS = {
    '/argsSchema': '/native_call/args',
    '/argsSchema/additionalProperties': '/native_call/args',
    '/optionsSchema': '/native_call/options',
    '/optionsSchema/additionalProperties': '/native_call/options',
    '/resultSchema': '/native_call/result',
    '/resultSchema/properties/return': '/native_call/result/return',
    '/resultSchema/properties/return/items': '/native_call/result/return/0',
    '/resultSchema/properties/return/items/additionalProperties': '/native_call/result/return/0',
    '/resultSchema/additionalProperties': '/native_call/result'}
RTPC_SOURCE = 'skills/waapi-skill/wwise_waapi/runtime_inspection_business.py#'
RTPC_NATIVE_PARENT = '/observations/capture/outcomes/profiler-rtpcs-observation/evidence'
RTPC_ORIGINAL_CANDIDATE = '503688449ba9f9db964a5fb7116ac6be2fb07198'
RTPC_GUARD_FILE = RTPC_SOURCE.split('#')[0]
RTPC_GUARD_CHANGE = {
    'before': '62e4ed3eca63a62637e7b8e1ab4c5c55c18ceffb49d91d4e318cecec44ce116c',
    'after': 'dba2653f3583ab5cfd9a5ffce02fe711cdad19fea6e1b0c9216cd8611811ffc3'}
UNICODE_CONTEXT_SOURCE = 'skills/waapi-skill/wwise_waapi/business_declarations.py'
UNICODE_CONTEXT_SOURCE_CHANGE = {'before': 'aee2a6cc97e5ccb0340a0f99f520969571e5e2dcf4d48695a396fca29dbeb7b3', 'after': '9f196a80ac7e2d82daf7fe0cb452735c9f50b2da825ba7ac2dafae02da700070'}
METER_SOURCE = 'skills/waapi-skill/wwise_waapi/profiler_meter_objects.py'
METER_SOURCE_CHANGE = {'before': '33b8f0571516710b76f68943e797ff46c95588e70965f1be2fb8c2d15094cd7b', 'after': '980ecacb9f9048c44e95b8a240e2a4c02e1a308f0bbcd1e824004a91f7224a63'}
METER_SOURCE_SYMBOLS = ['METER_OUTPUT_NAMES: admit existing media-size-bytes -> mediaSize binding; meter-root only; nearby comment']
METER_SOURCE_REASON = 'Reviewed e6cef72e meter-root allowlist admits existing media-size-bytes binding only; comment updated. No imports, functions, classes or other assignments change; retained nonmeter reader request/result/cleanup semantics are unchanged.'
LOG_MESSAGE_SOURCE_CHANGES = {'skills/waapi-skill/scripts/gateway.py': {'before': 'c8dfcff8ae13c9e5b192f4ca7f1e1cd7b52a9f20e5327b33bec15e8a1ecb0bc4', 'after': '27b53029238e27b59edc83fa2f1c65c4a50ff125a222d9ce71099a9cd69c64fb'}, 'skills/waapi-skill/wwise_waapi/runtime_inspection_business.py': {'before': '06442176e0aa4f5862feb0c66ef9878221494145755d700c02029353641e9f4d', 'after': 'dba2653f3583ab5cfd9a5ffce02fe711cdad19fea6e1b0c9216cd8611811ffc3'}, 'skills/waapi-skill/wwise_waapi/runtime_inspection_business_contracts.py': {'before': 'f93e41345477d0e3346230c12ebc056511b4c348ee253cb3df33c91d8bd4658d', 'after': '14fb6f062baf80566961b9304eff1d13b89fdab5afaa731910261bfcfbf02594'}}
LOG_MESSAGE_SOURCE_SYMBOLS = {'skills/waapi-skill/scripts/gateway.py': ['module import: MAX_LOG_MESSAGE_BYTES', 'transaction_verify_terminal_budget: exact valid2023-25 log.addItem rendered allowance only, resolved native request validation; ordinary global24576B retained', 'project_successful_transaction_verify_payload: successful exact log-only duplicate scope projection; exact agent_result/full durable journal retained'], 'skills/waapi-skill/wwise_waapi/runtime_inspection_business.py': ['module import: MAX_LOG_MESSAGE_BYTES', 'materialize_runtime_control_business_request: log.addItem exact empty/whitespace UTF-8 message only; no NUL, required type/field and16KiB bound retained'], 'skills/waapi-skill/wwise_waapi/runtime_inspection_business_contracts.py': ['MAX_LOG_MESSAGE_BYTES = 16 * 1024', '_CONTRACTS[LOG_ADD_ITEM_URI]: input_forms/field_types message disclosure only']}
LOG_MESSAGE_SOURCE_REASON = 'Reviewed fc170122 exact log.addItem message materialization/disclosure and successful log transaction projection/resolved rendered-budget guard only. Profiler read request/result/normalizer, capture cursor, host requirements and Source copy/Save/graph verification paths are unchanged; global24KiB and ordinary non-log output paths remain unchanged. No original native map, fact, failure or archive is rewritten; complete current public replay remains required by existing consumers.'
RTPC_REVIEWED_SOURCE_CHANGES = {
    METER_SOURCE: METER_SOURCE_CHANGE,
    UNICODE_CONTEXT_SOURCE: UNICODE_CONTEXT_SOURCE_CHANGE,
    'skills/waapi-skill/wwise_waapi/runtime_inspection_business_contracts.py': {
        'before': '69b33beb785880102003179f943d3cdb90c2229bd9adeacfb81993a39d8a85c4',
        'after': '14fb6f062baf80566961b9304eff1d13b89fdab5afaa731910261bfcfbf02594'},
    RTPC_GUARD_FILE: RTPC_GUARD_CHANGE,
    'skills/waapi-skill/scripts/gateway.py': {
        'before': '9ea8d1c0c79c9323c8ee0e48b8cb9444c54c8d73f9f7330ed827563f31f42f03',
        'after': '27b53029238e27b59edc83fa2f1c65c4a50ff125a222d9ce71099a9cd69c64fb'},
    'skills/waapi-skill/wwise_waapi/builders/stable_reads.py': {
        'before': '21108e298bc83cdf2eda6269db3d440a0865cacbab7c953d9ef57f84217fe62a',
        'after': 'ea1c39a5480afc5720f99a0acb85015c7c7d028d8ee53eb1937ff079fce9d7d8'},
    'skills/waapi-skill/wwise_waapi/builders/schema.py': {
        'before': '4a1ac5146edc65eb8e58defd689051f79a198bafb2d5d2134d912bd9a862fd6d',
        'after': 'cd11309c557b68ea7bcb7d82c2bcbc1a448d08f8e283fab50a0424555fc4f8f2'},
    'skills/waapi-skill/wwise_waapi/operation_registry.py': {
        'before': 'f96a2233a98e03dd62de261a24b3f81876284af28f0973758cf1f8a805b5dd5a', 'after': '3b298a11c9326d47b968783e536d09d290a8fff4a5a7080b5f5f99d5e7c2734d'},
    'skills/waapi-skill/wwise_waapi/runtime_log_effects.py': {
        'before': '62c28fc9bb92ccd8e8efb3ccbfe5b187d6df1d3086c2def79e1d11dbc81ddfe8', 'after': '1f03a038ba77a0ab62fba014329eeeb6962de86902f14fcb60cbfb4de19dea00'}}
RTPC_REVIEWED_SOURCE_SYMBOLS = {
    METER_SOURCE: METER_SOURCE_SYMBOLS,
    UNICODE_CONTEXT_SOURCE: ['BusinessHandleRegistry._require_context: exact UTF-8 byte comparison; no normalization'],
    'skills/waapi-skill/wwise_waapi/runtime_inspection_business_contracts.py': [
        'field ceiling', 'profiler_result_field_choices', 'three fixed row declarations', 'runtime_inspection_business_contract_data',
        'runtime_transport_requires_authoring', 'runtime_inspection_business_catalog_rows: exact registered-version Console transport admission and metadata-only finalization',
        'runtime_log_observation_support/CONSOLE_LOG_ADD_OBSERVER; runtime_inspection_business_catalog_rows/runtime_inspection_business_contract_data: exact log metadata only'],
    RTPC_GUARD_FILE: ['module import: builders.query.STRUCTURED_GUID_PATTERN',
        '_validate_rtpc_rows', 'normalize_runtime_inspection_result', 'rtpc_validated_name_compatibility',
        'Sequence/field-contract imports', 'materialize_runtime_inspection_business_request'],
    'skills/waapi-skill/scripts/gateway.py': ['_execute_gateway_unconstrained: retain only already-attested getInfo bool in missing finish host context; preserve exact agent_result last; no additional call or successful read request/result change', 'module import: builders.schema.validate_resolved_semantic_result',
        'module import: runtime_inspection_business.rtpc_validated_name_compatibility',
        'module import: builders.stable_reads.MAX_GAME_OBJECT_ROWS/MAX_STABLE_STRING_BYTES',
        'build_parser', 'dispatch_command', 'resolve_profiler_voice_path', 'dispatch_profiler_voice_contributions_request',
        'runtime_authoring_host_required_payload', 'dispatch_offline_command', 'dispatch_business_runtime_control_plan',
        'dispatch_runtime_inspection_business_read', 'preflight_stable_read_input', 'fixed_command_route_payload', 'preflight_core_business_input',
        'runtime_log_observation_support import; live_log_topic_boundary; dispatch_command/dispatch_topic_stream: exact log Topic guard',
        'dispatch_offline_command/dispatch_runtime_inspection_business_read: exact log disclosure only',
        '_dispatch_transaction_command_with_execution_lease: exact log observation-plan drift/event selection only'],
    'skills/waapi-skill/wwise_waapi/builders/stable_reads.py': ['build_profiler_voice_contributions_request',
        'normalize_profiler_voice_contributions_result', 'normalize_profiler_game_objects_result'],
    'skills/waapi-skill/wwise_waapi/builders/schema.py': ['validate_resolved_semantic_result',
        '_validate_resolved_sections', '_runtime_result_reference_schema'],
    'skills/waapi-skill/wwise_waapi/operation_registry.py': [
        'prepare_operation/verify_prepared_operation: exact log observation plan, verifier selection and message only'],
    'skills/waapi-skill/wwise_waapi/runtime_log_effects.py': [
        'compare_channel: exact Console log observation guard only']}
RTPC_REVIEWED_SOURCE_SYMBOLS['skills/waapi-skill/scripts/gateway.py'] += LOG_MESSAGE_SOURCE_SYMBOLS['skills/waapi-skill/scripts/gateway.py']
RTPC_REVIEWED_SOURCE_SYMBOLS['skills/waapi-skill/wwise_waapi/runtime_inspection_business.py'] += LOG_MESSAGE_SOURCE_SYMBOLS['skills/waapi-skill/wwise_waapi/runtime_inspection_business.py']
RTPC_REVIEWED_SOURCE_SYMBOLS['skills/waapi-skill/wwise_waapi/runtime_inspection_business_contracts.py'] += LOG_MESSAGE_SOURCE_SYMBOLS['skills/waapi-skill/wwise_waapi/runtime_inspection_business_contracts.py']
RTPC_REVIEWED_SOURCE_REASON = (
    METER_SOURCE_REASON + ' ' + LOG_MESSAGE_SOURCE_REASON + ' Reviewed already-attested host finish metadata only; no additional call or successful Profiler request/result change. '
    'Exact reviewed nine-file RTPC guard and closed non-RTPC result-validation source delta; '
    'three fixed-reader-only closed result-field selection delta leaves absent result_fields requests unchanged; post-success legacy name compatibility disclosure; RTPC conservative validator/request/normalizer behavior retained and complete original '
    'arrays unchanged through current public Gateway; contribution-only bus choice/partial projection/versioned identity/fixed cursor snapshot/mixed identity Bus selection delta irrelevant to RTPC; '
    'Exact registered-version Console transport predicate/catalog admission and error-message/catalog-docstring finalization does not change these non-transport read paths; '
    'GameObjects-only optional row fields/versioned ID domains/timestamp aliases and fixed request-schema disclosure do not change RTPC or contribution behavior; exact UTF-8 context comparator preserves successful original ASCII equality decisions with no native non-ASCII claim; exact log-only host/patch observation policy, Topic/transaction guards and metadata leave Profiler reads unchanged; original finalized PASS retained')
RTPC_ORIGINALS = {
    '2022.1': ('2022.1.19.8584', 'e9d4b86aaccaccb9b1603d37ba5bc7255034c09d2c05b7685beb254e6642adfd', 17, 23637),
    '2025.1': ('2025.1.7.9143', 'e7ef187ef0ed855819cfa007375f3ca8c1d4cfc1e3697f8c5b9e870c1441690c', 5, 30837)}


def validate_rtpc_source_review(descriptor, historical_sources, branch, root, base):
    """Accept only the pinned reviewed nine-file delta for original RTPC reads."""
    review = completion.read_sealed_artifact(descriptor, base)
    version, host, build, kind, uri = branch['route'].split('|')
    if version not in RTPC_ORIGINALS or host != 'wwise-authoring' or kind != 'function' or uri != RTPC_URI:
        raise ValueError('RTPC source review is limited to witnessed Authoring reads')
    expected_build, original_sha, count, position = RTPC_ORIGINALS[version]
    allowed = {'/resultSchema/properties/return/@cardinality/multiple'}
    for field in ('id', 'name', 'gameObjectId', 'value'):
        pointer = '/resultSchema/properties/return/items/properties/' + field
        allowed.update((pointer, pointer + '/$ref'))
        if version == '2022.1':
            allowed.add(pointer + '/@presence/present')
    for document, definition in (('waapi_definitions.json', 'gameObject'),
            ('waapi_definitions.json' if version == '2022.1' else 'common_definitions.json', 'guid')):
        allowed.add(f'/resultSchema/@definition/{document}/definitions/{definition}')
    if version == '2022.1':
        allowed.add('/resultSchema/@definition/waapi_definitions.json/definitions/uniqueName')
    current = program_source_context(root)['packaged']
    changes = {name: {'before': historical_sources.get(name), 'after': current.get(name)}
        for name in historical_sources.keys() | current.keys() if historical_sources.get(name) != current.get(name)}
    expected = {'contract', 'historical_candidate', 'historical_sources', 'current_sources',
        'changed_files', 'changed_symbols', 'scope', 'original_capture', 'program_replay'}
    scope = {'version': version, 'host': host, 'build': expected_build, 'uri': uri,
        'original_capture_sha256': original_sha, 'original_rows_pointer': '/outcomes/profiler-rtpcs-observation/evidence/agent_result/return',
        'original_row_count': count}
    if (set(review) != expected or review['contract'] != 'waapi-skill.runtime-read-source-review/v1'
            or build != expected_build or branch['pointer'] not in allowed
            or review['historical_candidate'] != RTPC_ORIGINAL_CANDIDATE
            or len(historical_sources) != 413 or review['historical_sources'] != historical_sources
            or review['current_sources'] != current or review['changed_files'] != changes
            or changes != RTPC_REVIEWED_SOURCE_CHANGES
            or review['changed_symbols'] != RTPC_REVIEWED_SOURCE_SYMBOLS
            or review['scope'] != scope or review['original_capture']['sha256'] != original_sha):
        raise ValueError('RTPC reviewed guard source/branch closure differs')
    for key in ('original_capture', 'program_replay'):
        _portable_descriptor(review[key], base)
    original = completion.read_sealed_artifact(review['original_capture'], base)
    rows = completion.pointer_value(original, scope['original_rows_pointer'])
    replay = completion.read_sealed_artifact(review['program_replay'], base)
    gateway, native = replay['gateway'], replay['native_call']
    argv = ['core-call', RTPC_URI, '--profiler-position', str(position), '--max-results', '64']
    if (len(rows) != count or replay.get('contract') != 'waapi-skill.runtime-read-program/v1'
            or replay.get('phase_reports') != dict.fromkeys(('setup', 'call', 'teardown'), 'passed')
            or replay.get('source_unchanged') is not True or replay.get('source_context') != program_source_context(root)
            or gateway['argv'] != argv or gateway['exit_code'] != 0 or gateway['payload'].get('ok') is not True
            or gateway['payload'].get('is_command_line') is not False
            or gateway['payload']['schema_validation']['result']['version'] != version
            or audit.digest(gateway['payload']['agent_result']['return']) != audit.digest(rows)
            or gateway['payload']['agent_result']['complete'] is not True
            or audit.digest(native) != audit.digest({'uri': RTPC_URI, 'args': {'time': position},
                'options': {}, 'result': {'return': rows}})):
        raise ValueError('RTPC guard review needs current complete original-array public replay')


def _write_rtpc_source_review(output, prefix, historical_sources, captured, original_capture, branch, replay_path):
    current = captured['source_context']['packaged']
    if historical_sources == current:
        return None
    import shutil
    replay = output / (prefix + 'guard-program-replay.json')
    shutil.copyfile(replay_path, replay)
    version, host, build, _, uri = branch['route'].split('|')
    expected_build, original_sha, count, _ = RTPC_ORIGINALS[version]
    descriptor = write_json(output / (prefix + 'guard-source-review.json'), {
        'contract': 'waapi-skill.runtime-read-source-review/v1', 'historical_candidate': RTPC_ORIGINAL_CANDIDATE,
        'historical_sources': historical_sources, 'current_sources': current,
        'changed_files': RTPC_REVIEWED_SOURCE_CHANGES,
        'changed_symbols': RTPC_REVIEWED_SOURCE_SYMBOLS,
        'scope': {'version': version, 'host': host, 'build': expected_build, 'uri': uri,
            'original_capture_sha256': original_sha,
            'original_rows_pointer': '/outcomes/profiler-rtpcs-observation/evidence/agent_result/return',
            'original_row_count': count}, 'original_capture': original_capture,
        'program_replay': {'artifact': replay.name, 'sha256': sha(replay.read_bytes())}})
    validate_rtpc_source_review(descriptor, historical_sources, branch, audit.ROOT, output)
    return descriptor


def rtpc_field_mappings(inventory, *, version, host, mode):
    """Select exact reflected branches; never infer descendants from a parent."""
    route = next(row for row in inventory['native_coverage']['routes']
        if row['version'] == version and row['host'] == host and row['uri'] == RTPC_URI)
    rows = {row['pointer']: row for row in inventory['native_coverage']['obligations'] if row['route'] == route['id']}
    selected = []
    def add(pointer, observed, chain=()):
        row = rows[pointer]
        selected.append({'branch': row, 'program_pointer': observed, 'reference_chain': list(chain)})
    if mode == 'construction':
        edge = rows['/argsSchema/properties/time/$ref']
        target = edge['reference']['target'].split('|', 5)[5]
        add('/argsSchema/properties/time', '/native_call/args/time')
        add(edge['pointer'], '/native_call/args/time')
        for suffix in ('', '/oneOf/0', '/oneOf/0/minimum'):
            add(target + suffix, '/native_call/args/time', [edge['id']])
        add('/optionsSchema/@empty/object', '/native_call/options')
    elif mode == 'data':
        for field in ('id', 'name', 'gameObjectId', 'value'):
            pointer = '/resultSchema/properties/return/items/properties/' + field
            observed = '/native_call/result/return/1/' + field
            add(pointer, observed)
            if pointer + '/$ref' in rows:
                edge = rows[pointer + '/$ref']
                add(edge['pointer'], observed)
                add(edge['reference']['target'].split('|', 5)[5], observed, [edge['id']])
            if pointer + '/@presence/present' in rows:
                add(pointer + '/@presence/present', observed)
        add('/resultSchema/properties/return/@cardinality/multiple', '/native_call/result/return')
    elif mode in {'cursor-capture', 'cursor-user'}:
        first = rows['/argsSchema/properties/time/$ref']
        target = first['reference']['target'].split('|', 5)[5]
        second = rows[target + '/oneOf/1/$ref']
        reached = second['reference']['target'].split('|', 5)[5]
        if mode == 'cursor-capture':
            add(target + '/oneOf/1', '', [first['id']])
            add(second['pointer'], '', [first['id']])
            add(reached, '', [first['id'], second['id']])
        add(reached + ('/enum/1' if mode == 'cursor-capture' else '/enum/0'), '', [first['id'], second['id']])
    elif mode == 'scalar':
        for field, index, predicates in (('id', 0, ('pattern',)),
                ('gameObjectId', 0, ('minimum', 'maximum')), ('name', 1, ('pattern',))):
            source = '/resultSchema/properties/return/items/properties/' + field + '/$ref'
            if source not in rows:
                continue
            edge = rows[source]
            target = edge['reference']['target'].split('|', 5)[5]
            for predicate in predicates:
                if target + '/' + predicate in rows:
                    add(target + '/' + predicate,
                        f'/native_call/result/return/{1 if predicate == "maximum" else index}/{field}', [edge['id']])
    elif mode == 'single':
        add('/resultSchema/properties/return/@cardinality/single', '/native_call/result/return')
        for field in ('id', 'name', 'gameObjectId', 'value'):
            pointer = '/resultSchema/properties/return/items/properties/' + field + '/@presence/absent'
            if pointer in rows:
                add(pointer, '/native_call/result/return/0/' + field)
        pointer = '/resultSchema/properties/return/items/@empty/object'
        if pointer in rows:
            add(pointer, '/native_call/result/return/0')
        pointer = '/resultSchema/properties/return/items/properties/name/@empty/string'
        if pointer in rows:
            add(pointer, '/native_call/result/return/0/name')
    elif mode == 'empty':
        add('/resultSchema/properties/return/@cardinality/empty', '/native_call/result/return')
    elif mode == 'structure':
        for pointer, observed in RTPC_STRUCTURE_POINTERS.items():
            add(pointer, observed)
    else:
        raise ValueError('RTPC mappings support only data or deterministic construction')
    return route, selected


def write_field_bundle(output, program_path, originals, *, inventory, version, host, mode, name_prefix="", guard_replay=None, mappings=None):
    """One flow publisher owns many independent RTPC assertion identities."""
    import gzip
    import shutil
    output = Path(output)
    captured = json.loads(Path(program_path).read_bytes())
    if (captured.get('contract') != 'waapi-skill.runtime-read-program/v1'
            or captured.get('phase_reports') != dict.fromkeys(('setup', 'call', 'teardown'), 'passed')
            or captured.get('source_context') != program_source_context()
            or captured.get('source_unchanged') is not True):
        raise ValueError('RTPC fields need current successful setup/call/teardown capture')
    route, default_mappings = rtpc_field_mappings(inventory, version=version, host=host, mode=mode)
    mappings = default_mappings if mappings is None else mappings
    public = next(row for row in inventory['routes'] if row['id'] == route['public_route'])
    argv = captured['gateway']['argv']
    if argv[:2] != ['core-call', RTPC_URI] or captured['native_call']['uri'] != RTPC_URI:
        raise ValueError('RTPC field publisher needs its exact public read')
    payload = captured['gateway']['payload']
    if (payload.get('is_command_line') != (host == 'wwise-console')
            or any(payload['schema_validation'][section]['version'] != version for section in ('request', 'result'))):
        raise ValueError('RTPC field publisher requires exact public host/version')
    if name_prefix and (not name_prefix.endswith('-') or '/' in name_prefix or '..' in name_prefix):
        raise ValueError('RTPC flow prefix must be a simple filename prefix')
    output.mkdir(parents=True, exist_ok=bool(name_prefix))
    def destination(name):
        return output / (name_prefix + name)
    shutil.copyfile(program_path, destination('program-capture.json'))
    def descriptor(name):
        return {'artifact': name_prefix + name, 'sha256': sha((destination(name)).read_bytes())}
    sources = captured['source_context']['packaged']
    candidate = inventory['native_coverage']['candidate_sha256']
    policy = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {}}
    document = {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': {}}
    program = {'candidate_sha256': candidate, 'scope_kind': 'product', 'relevant_sources': sources,
        'gateway': captured['gateway'], 'native_call': captured['native_call'],
        'runtime_read_program': captured,
        'invocation': {'phase': 'final', 'outcome': 'PASS', 'node_outcomes': [{'nodeid': captured['nodeid'], 'outcome': 'PASS'}]},
        'branch_assertions': {}}
    native = None
    source_review = None
    if originals is not None:
        if mode != 'data' or host != 'wwise-authoring' or version not in {'2022.1', '2025.1'}:
            raise ValueError('Unqualified native RTPC producer cannot be attached')
        for name in ('original-category.json', 'original-capture.json', 'original-closure.json.gz'):
            shutil.copyfile(originals / name, destination(name))
        native_run = {**descriptor('original-category.json'),
            'nodeid': 'tests/destructive/test_authoring_ui_business_live.py::test_runtime_owned_missing_profiler_reads',
            'observation_sha256': [descriptor('original-capture.json')['sha256']]}
        context = completion.read_category_run(native_run, output)
        read = archive_reader(descriptor('original-closure.json.gz'), output)
        completion.validate_authoring_batch_finalization(context['record'], output, read_bytes=read)
        if any(context[key] != route[key] for key in ('host', 'version', 'build')):
            raise ValueError('RTPC native host/build differs from exact mapped route')
        seal = json.loads(read(context['record']['categories'][0]['batch_finalization']['artifact']))
        node = json.loads(read(seal['observations'][native_run['nodeid']]['path']))
        original_sources = {k: v for k, v in node['source_context']['sources'].items() if k.startswith('skills/waapi-skill/')}
        capture = json.loads((destination('original-capture.json')).read_bytes())
        source_review = _write_rtpc_source_review(output, name_prefix, original_sources, captured,
            descriptor('original-capture.json'), mappings[0]['branch'], guard_replay or program_path)
        evidence = capture['outcomes']['profiler-rtpcs-observation']['evidence']
        owned = set(evidence['owned_game_object_row_indexes']) & set(evidence['rpm_read_row_indexes'])
        if len(owned) != 1:
            raise ValueError('RTPC native owned RPM witness is not unique')
        native_index = next(iter(owned))
        native_row = evidence['agent_result']['return'][native_index]
        if native_row != {'id': '{63D15B0F-16E7-4B8A-B9CA-7BF10AD315B4}', 'name': 'RPM',
                'gameObjectId': 18446744073709551614, 'value': 1000.0}:
            raise ValueError('RTPC exact native RPM identity/value differs')
        native = {'candidate_sha256': candidate, 'scope_kind': 'product', 'evidence_kind': 'native_execution',
            'relevant_sources': sources, 'invocation': context['record']['invocation'],
            'native_runs': [native_run], 'observation_artifacts': {'capture': descriptor('original-capture.json')},
            'branch_assertions': {}}
    for mapping in mappings:
        branch = mapping['branch']
        if mode in {'cursor-capture', 'cursor-user'}:
            trace = captured.get('native_reads', [])
            cursor_read = next(row for row in trace if row['uri'] == 'ak.wwise.core.profiler.getCursorTime')
            mapping['program_pointer'] = f"/runtime_read_program/native_reads/{cursor_read['ordinal']}/args/cursor"
        identity, pointer = branch['id'], mapping['program_pointer']
        absent = branch['kind'] == 'optional_presence' and branch.get('value') == 'absent'
        value = None if absent else completion.pointer_value({'runtime_read_program': captured}, pointer) if mode.startswith('cursor-') else completion.pointer_value(captured, pointer)
        public_pointer = (pointer.replace('/native_call/result', '/gateway/payload/agent_result')
            if branch['pointer'].startswith('/resultSchema') else '/gateway/payload/agent_result/profiler_position')
        check = ({'pointer': pointer, 'absent': True} if absent else
            {'pointer': pointer, 'cardinality': branch['value']} if branch['kind'] == 'collection_cardinality'
            else {'pointer': pointer, 'equals': value})
        checks = [check, ({'pointer': public_pointer, 'absent': True} if absent else
            {'pointer': public_pointer, 'equals': completion.pointer_value(captured, public_pointer)}),
            {'pointer': '/gateway/payload/agent_result/complete', 'equals': True}]
        if mode == 'scalar' and branch['pointer'].endswith('/uniqueName/pattern'):
            for extra in ('/gateway/payload/agent_result/return/2/name',
                    '/gateway/payload/schema_validation/result/compatibility_rules'):
                checks.append({'pointer': extra, 'equals': completion.pointer_value(captured, extra)})
        if absent:
            parent = public_pointer.rsplit('/', 1)[0]
            checks.append({'pointer': parent, 'equals': completion.pointer_value(captured, parent)})
        assertion = {'native_shape_sha256': branch['shape_sha256'], 'native_route': branch['route']}
        program['branch_assertions'][identity] = {**assertion, 'checks': checks}
        policy['branches'][identity] = {'native_shape_sha256': branch['shape_sha256'],
            'categories': ['program', 'native'] if mode == 'data' else ['program'],
            'reason': ('Exact observed RTPC data/reference/presence/cardinality; independent native fact required'
                if mode == 'data' else 'Deterministic closed numeric time/reference/minimum/empty-options construction; no native data/effect inference'
                if mode == 'construction' else 'SPEC section 5 exact pinned scalar validation/preservation; legacy matching-name domain preserves broader string labels; no actual native occurrence/data/effect claim'
                if mode == 'scalar' else 'SPEC section 5 exact public choice to ordered cursor read to numeric RTPC construction; no actual native occurrence/data/effect claim'
                if mode.startswith('cursor-') else 'SPEC section 5 deterministic RTPC decoder/structure preservation; no actual native occurrence/data/effect or descendant credit')}
        binding = {'branch_id': identity, 'native_shape_sha256': branch['shape_sha256'],
            'runtime_read_program': True,
            'public_route': public['id'], 'public_route_sha256': audit.digest(public),
            'input': {'gateway_argv': argv, 'selector': pointer}, 'dispatch_pointer': '/native_call',
            'observation_pointer': pointer, 'gateway_observation_pointer': public_pointer,
            'reference_chain': mapping['reference_chain'],
            'relevant_sources': sorted(sources), 'evidence': {},
            **{key: {'source': RTPC_SOURCE + symbol, 'selector': branch['pointer']} for key, symbol in (
                ('construction', 'materialize_runtime_inspection_business_request'),
                ('validation', 'normalize_runtime_inspection_result' if branch['pointer'].startswith('/resultSchema') else (
                    'materialize_runtime_inspection_business_request' if mode == 'structure' or branch['pointer'].startswith('/optionsSchema/') else '_profiler_time')),
                ('verifier', 'normalize_runtime_inspection_result'))}}
        document['bindings'][identity] = binding
        if native is not None:
            suffix = pointer.removeprefix('/native_call/result')
            suffix = suffix.replace('/return/1/', f'/return/{native_index}/')
            native_pointer = RTPC_NATIVE_PARENT + '/agent_result' + suffix
            native_value = completion.pointer_value({'observations': {'capture': capture}}, native_pointer)
            native_check = ({'pointer': native_pointer, 'cardinality': 'multiple'}
                if branch['kind'] == 'collection_cardinality' else {'pointer': native_pointer, 'equals': native_value})
            native_checks = [native_check,
                {'pointer': RTPC_NATIVE_PARENT + '/complete', 'equals': True},
                {'pointer': RTPC_NATIVE_PARENT + '/position_ms', 'equals': int(argv[argv.index('--profiler-position') + 1])},
                {'pointer': RTPC_NATIVE_PARENT + '/setter_effect_verified', 'equals': False}]
            native['branch_assertions'][identity] = {**assertion, 'checks': native_checks}
            mapping.update(branch_id=identity, native_shape_sha256=branch['shape_sha256'],
                native_pointer=native_pointer, native_result_parent=RTPC_NATIVE_PARENT,
                public_pointer=public_pointer, native_checks=native_checks)
    program_descriptor = {**write_json(destination('program.json'), program), 'nodeid': captured['nodeid']}
    for binding in document['bindings'].values():
        binding['evidence']['program'] = deepcopy(program_descriptor)
    bindings_descriptor = write_json(destination('bindings.json'), document)
    requirements_descriptor = write_json(destination('requirements.json'), policy)
    attachments = []
    if native is not None:
        native_descriptor = {**write_json(destination('native.json'), native), 'nodeid': native_run['nodeid']}
        archived_paths = json.loads(gzip.decompress((destination('original-closure.json.gz')).read_bytes()))['files']
        capture_path = next(name for name in archived_paths if name.endswith('/profiler-capture.json'))
        for index, mapping in enumerate(mappings):
            branch = mapping['branch']; identity = branch['id']; binding = deepcopy(document['bindings'][identity])
            proof = {'contract': 'waapi-skill.runtime-observation-proof/v1', 'branch_id': identity,
                'native_shape_sha256': branch['shape_sha256'], 'mapping': {k: v for k, v in mapping.items() if k != 'branch'},
                'native_run': native_run, 'archive': descriptor('original-closure.json.gz'),
                'capture': descriptor('original-capture.json'), 'capture_original_path': capture_path,
                'program_capture': descriptor('program-capture.json'), 'relevant_sources': sources,
                **({'source_review': source_review} if source_review else {})}
            proof_descriptor = write_json(destination(f'proof-{index}.json'), proof)
            binding.update(runtime_observation_attachment=proof_descriptor,
                program_observation_pointer=mapping['program_pointer'], observation_pointer=mapping['native_pointer'],
                native_observations_sha256={'capture': descriptor('original-capture.json')['sha256']})
            equivalence = {'contract': 'waapi-skill.branch-evidence-equivalence/v1',
                'from_candidate': context['candidate'], 'to_candidate': candidate, 'branch_id': identity,
                'native_shape_sha256': branch['shape_sha256'], 'native_route': branch['route'],
                'evidence_sha256': native_run['sha256'], 'binding_semantics_sha256': audit.digest(completion.binding_semantics(binding)),
                'reviewed_reason': (RTPC_REVIEWED_SOURCE_REASON + '; independent field/reference witness only'
                    if source_review else 'Original finalized PASS and complete packaged runtime sources unchanged; exact independent field/reference witness only'),
                'sources': original_sources, **({'runtime_read_review': source_review} if source_review else {})}
            equivalence_descriptor = write_json(destination(f'native-equivalence-{index}.json'), equivalence)
            attachments.append(write_json(destination(f'attachment-{index}.json'), {
                'contract': 'waapi-skill.runtime-observation-attachment/v1', 'branch_id': identity,
                'proof': proof_descriptor, 'evidence': native_descriptor, 'native_equivalence': equivalence_descriptor}))
    write_json(destination('index.json'), {'contract': 'waapi-skill.branch-evidence-index/v1', 'base': '.',
        'entries': [{'id': f'rtpc-{version}-{host}-{mode}', 'bindings': bindings_descriptor,
            'origin': {'bindings': bindings_descriptor, 'program': descriptor('program.json'),
                'requirements': requirements_descriptor, 'capture': descriptor('program-capture.json')}}],
        **({'runtime_observation_attachments': attachments} if attachments else {})})
    return destination('index.json')


def write_field_stage(output, captures, originals, *, inventory, guard_replays=None, family_prefix="", selected_ids=None):
    """Combine five-version read flows in the ordinary portable index format."""
    if family_prefix not in {'', 'rtpc-'}:
        raise ValueError('Closed RTPC family prefix required')
    versions = ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1')
    fields = {(version, host, mode) for version in versions
        for host in ('wwise-console', 'wwise-authoring') for mode in ('construction', 'data')}
    shapes = {(version, host, mode) for version in versions
        for host in ('wwise-console', 'wwise-authoring') for mode in ('structure', 'empty', 'single')}
    frontier = {(version, host, mode) for version in versions
        for host in ('wwise-console', 'wwise-authoring') for mode in ('scalar', 'cursor-capture', 'cursor-user')}
    expected = set(captures)
    if expected not in (fields, shapes, frontier, fields | shapes, fields | shapes | frontier) or set(originals) - {'2022.1', '2025.1'}:
        raise ValueError('RTPC stage requires all exact five-version public flows and only qualified originals')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    policy = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {}}
    index = {'contract': 'waapi-skill.branch-evidence-index/v1', 'base': '.', 'entries': []}
    attachments = []
    wanted = None if selected_ids is None else set(selected_ids)
    if wanted is not None and not wanted <= {b['id'] for b in inventory['native_coverage']['obligations'] if (b.get('route') or '').endswith('|function|' + RTPC_URI)}:
        raise ValueError('RTPC stage selected IDs escape its exact routes')
    for version, host, mode in sorted(expected):
        if wanted is not None and not any(i.startswith(f'{version}|{host}|') for i in wanted):
            continue
        original = originals.get(version) if host == 'wwise-authoring' and mode == 'data' else None
        mappings = None
        if wanted is not None:
            _, mappings = rtpc_field_mappings(inventory, version=version, host=host, mode=mode)
            mappings = [m for m in mappings if m['branch']['id'] in wanted]
            if not mappings: continue
        flow = write_field_bundle(output, captures[version, host, mode], original,
            inventory=inventory, version=version, host=host, mode=mode, mappings=mappings,
            name_prefix=f'{family_prefix}{version}-{host}-{mode}-', guard_replay=(guard_replays or {}).get(version))
        document = json.loads(flow.read_bytes())
        index['entries'].extend(document['entries'])
        attachments.extend(document.get('runtime_observation_attachments', []))
        flow_policy = completion.read_sealed_artifact(document['entries'][0]['origin']['requirements'], output)
        if policy['branches'].keys() & flow_policy['branches'].keys():
            raise ValueError('RTPC stage repeats an exact native branch')
        policy['branches'].update(flow_policy['branches'])
    if wanted is not None and set(policy['branches']) != wanted:
        raise ValueError('RTPC stage has unproved selected branches')
    if attachments:
        index['runtime_observation_attachments'] = attachments
    write_json(output / 'requirements.json', policy)
    write_json(output / 'index.json', index)
    return output / 'index.json'


CONTRIBUTION_URI = 'ak.wwise.core.profiler.getVoiceContributions'
CONTRIBUTION_PARENT = '/outcomes/profiler-contributions-bus-observation/evidence'
CONTRIBUTION_CURSOR_TIME = '/argsSchema/@definition/waapi_definitions.json/definitions/cursorTime'
CONTRIBUTION_CURSOR = '/argsSchema/@definition/waapi_definitions.json/definitions/profilerCursor'
CONTRIBUTION_CURSOR_POINTERS = frozenset((CONTRIBUTION_CURSOR_TIME + '/oneOf/1',
    CONTRIBUTION_CURSOR_TIME + '/oneOf/1/$ref', CONTRIBUTION_CURSOR,
    CONTRIBUTION_CURSOR + '/enum/0', CONTRIBUTION_CURSOR + '/enum/1'))
CONTRIBUTION_ORIGINALS = {
    '2022.1': {'args': '9abe0fa40c8494ef2f2ad15e6ac6ec52f1dbf0ac893698538a066e092a9129c5',
        'result': 'b2bee9592e16fb4af107ed33b144d3b239a43992aa314e81e139c698ee622f1d',
        'projection': '5bf6fcc09670728d193e282b077068db2976171c12f06f98889b1ae523b776e5'},
    '2025.1': {'args': '6d641abaf0d3b10ebb4d348657e124277746ce703bb845d4e5bb0513d11a58b8',
        'result': '64ef5da195a57284e0f7ea003ec51485a3120c25f7679dc2e21e07ff7789e355',
        'projection': '38e500923e7345eb5422f3e749bd8ff4d6c2995ede40557bf3a5f8b7349e178a'},
}


def contribution_public_pointer(pointer):
    """Only the existing contribution projection renames these native fields."""
    if pointer == '/native_call/result':
        return '/gateway/payload/agent_result'
    parent = '/native_call/result/return'
    if pointer == parent:
        return '/gateway/payload/agent_result'
    if pointer.startswith(parent + '/'):
        field, _, rest = pointer[len(parent) + 1:].partition('/')
        field = {'LPF': 'lpf', 'HPF': 'hpf', 'DSF': 'dsf/value'}.get(field, field)
        return '/gateway/payload/agent_result/' + field + ('/' + rest if rest else '')
    return pointer.replace('/native_call/', '/gateway/payload/semantic_preview/', 1)


def validate_contribution_program(record, binding, branch, root, reference_edges=None):
    """Validate one exact branch within the dedicated captured public flow."""
    _validate_contribution_capture(record, binding['input']['gateway_argv'], branch['route'], root)
    pointer = binding.get('program_observation_pointer') if binding.get('runtime_observation_attachment') else binding['observation_pointer']
    if binding['gateway_observation_pointer'] != contribution_branch_public_pointer(branch, pointer):
        raise ValueError('Contribution needs the corresponding exact public projection occurrence')
    if branch['pointer'] in CONTRIBUTION_CURSOR_POINTERS:
        return _validate_contribution_cursor(record, binding, branch, root, reference_edges or {})
    _validate_contribution_branch(record, binding, branch, root)


def _validate_contribution_cursor(record, binding, branch, root, reference_edges):
    """Bind only five reflected contribution cursor leaves to their snapshot."""
    node = _contribution_node(branch, root)
    first = branch['route'] + '|/argsSchema/properties/time/$ref'
    second = branch['route'] + '|' + CONTRIBUTION_CURSOR_TIME + '/oneOf/1/$ref'
    chain = [first] if branch['pointer'].startswith(CONTRIBUTION_CURSOR_TIME) else [first, second]
    completion.exact_observation_pointer(branch,
        {**binding, 'observation_pointer': '/native_call/args/time'}, '/native_call', 'args', reference_edges)
    if (audit.digest(node) != branch['shape_sha256'] or binding.get('reference_chain') != chain
            or reference_edges[first]['reference']['target'] != branch['route'] + '|' + CONTRIBUTION_CURSOR_TIME
            or reference_edges[second]['reference']['target'] != branch['route'] + '|' + CONTRIBUTION_CURSOR):
        raise ValueError('Contribution exact cursor normalization branch/reflection differs')
    captured = record['runtime_read_program']
    final_call = captured['public_calls'][-1]
    cursor, = [row for row in captured['native_reads'][final_call['native_start']:]
        if row['uri'] == 'ak.wwise.core.profiler.getCursorTime']
    expected = f"/runtime_read_program/native_reads/{cursor['ordinal']}/args/cursor"
    if (binding['observation_pointer'] != expected
            or not _contribution_predicate(branch, node, cursor['args']['cursor'], root=root)):
        raise ValueError('Contribution exact cursor normalization occurrence/choice differs')
    return {'branch_id': branch['id'], 'observation_pointer': expected}


def _validate_contribution_capture(record, argv, route, root):
    """Check the complete projection and typed handle/request relations."""
    from wwise_waapi.builders.schema import validate_resolved_semantic_result
    from wwise_waapi.builders.stable_reads import normalize_profiler_voice_contributions_result
    version, host, _, kind, uri = route.split('|')
    captured = record.get('runtime_read_program')
    if not isinstance(captured, dict):
        raise ValueError('Contribution needs exact current public read capture')
    gateway, native = captured['gateway'], captured['native_call']
    payload = gateway['payload']
    if (uri != CONTRIBUTION_URI or kind != 'function'
            or captured.get('contract') != 'waapi-skill.runtime-read-program/v1'
            or captured.get('phase_reports') != dict.fromkeys(('setup', 'call', 'teardown'), 'passed')
            or captured.get('source_unchanged') is not True
            or captured.get('source_context') != program_source_context(root, flow=uri)
            or record.get('relevant_sources') != captured['source_context']['packaged']
            or gateway != record['gateway'] or native != record['native_call']
            or gateway['argv'] != argv or gateway['argv'][0] != 'profiler-voice-contributions'
            or gateway['exit_code'] != 0 or payload.get('ok') is not True
            or payload.get('is_command_line') != (host == 'wwise-console')
            or any(payload['schema_validation'][section]['version'] != version for section in ('request', 'result'))
            or native['uri'] != uri or native['options'] != {}
            or audit.digest(payload['semantic_preview']['args']) != audit.digest(native['args'])):
        raise ValueError('Contribution needs exact current public read capture')
    validate_resolved_semantic_result(uri, native['result'], version=version)
    projected = normalize_profiler_voice_contributions_result(version=version, result=native['result'])
    if audit.digest(projected) != audit.digest(payload['agent_result']):
        raise ValueError('Program must preserve complete contribution projection')
    trace, calls = captured.get('native_reads'), captured.get('public_calls')
    if (not isinstance(trace, list) or not 1 <= len(trace) <= 128 or not isinstance(calls, list) or not 1 <= len(calls) <= 8
            or any(set(row) != {'ordinal', 'uri', 'args', 'options', 'result'} or row['ordinal'] != index
                or type(row['ordinal']) is not int for index, row in enumerate(trace))):
        raise ValueError('Contribution ordered public/native trace is incomplete')
    end = 0
    for call in calls:
        if (set(call) != {'gateway', 'native_start', 'native_end'} or type(call['native_start']) is not int
                or type(call['native_end']) is not int or call['native_start'] != end
                or not end < call['native_end'] <= len(trace)
                or call['gateway']['exit_code'] != 0 or call['gateway']['payload'].get('ok') is not True):
            raise ValueError('Contribution ordered public/native trace is incomplete')
        end = call['native_end']
    if end != len(trace) or calls[-1]['gateway'] != gateway:
        raise ValueError('Contribution final public/native trace differs')
    final_trace = trace[calls[-1]['native_start']:]
    final, = [row for row in final_trace if row['uri'] == uri]
    if final['ordinal'] != len(trace) - 1 or audit.digest({key: final[key] for key in native}) != audit.digest(native):
        raise ValueError('Contribution final native request/result differs')
    argv = gateway['argv']
    def values(flag):
        return [argv[index + 1] for index, value in enumerate(argv[:-1]) if value == flag]
    time = native['args']['time']
    if '--capture-ms' in argv:
        position, = values('--capture-ms')
        if not position.isascii() or not position.isdecimal() or type(time) is not int or int(position) != time:
            raise ValueError('Contribution selected capture time differs')
    else:
        choice, = values('--capture')
        cursor = {'latest': 'capture', 'user-cursor': 'user'}[choice]
        cursors = [row for row in final_trace if row['uri'] == 'ak.wwise.core.profiler.getCursorTime']
        dependent = [row for row in final_trace if row['uri'] in {
            'ak.wwise.core.profiler.getVoices', 'ak.wwise.core.profiler.getBusses', CONTRIBUTION_URI}]
        source_time = (cursors[0]['result'].get('return')
            if len(cursors) == 1 and type(cursors[0]['result']) is dict else None)
        if (len(cursors) != 1 or cursors[0]['args'] != {'cursor': cursor} or cursors[0]['options'] != {}
                or type(source_time) is not int or source_time < 0
                or type(time) is not int or time < 0 or cursors[0]['result'] != {'return': time}
                or any(row['ordinal'] <= cursors[0]['ordinal'] or type(row['args'].get('time')) is not int
                    or row['args']['time'] != time for row in dependent)):
            raise ValueError('Contribution fixed cursor construction trace differs')
    voice_rows = [row for row in final_trace if row['uri'] == 'ak.wwise.core.profiler.getVoices']
    bus_rows = [row for row in final_trace if row['uri'] == 'ak.wwise.core.profiler.getBusses']
    if len(voice_rows) != 1 or voice_rows[0]['args'] != {'time': time}:
        raise ValueError('Contribution requires same-time unique voice revalidation')
    voices = voice_rows[0]['result']['return']
    voice, = [row for row in voices if row['pipelineID'] == native['args']['voicePipelineID']]
    pipeline_ids = native['args'].get('bussesPipelineID')
    if pipeline_ids:
        if len(bus_rows) != 1 or bus_rows[0]['args'] != {'time': time}:
            raise ValueError('Contribution requires same-time unique Bus revalidation')
        selected_busses = []
        for identity in pipeline_ids:
            bus, = [row for row in bus_rows[0]['result']['return'] if row['pipelineID'] == identity
                and row['gameObjectID'] == voice['gameObjectID']]
            selected_busses.append(bus)
    else:
        selected_busses = []
    if '--bus-path' in argv:
        mode, = values('--bus-path')
        if (values('--bus-object-id') or values('--bus-instance-handle')
                or mode == 'wwise-default' and 'bussesPipelineID' in native['args']
                or mode == 'dry-path' and pipeline_ids != []):
            raise ValueError('Contribution explicit bus path construction differs')
    elif not values('--bus-object-id') and not values('--bus-instance-handle') and pipeline_ids != []:
        raise ValueError('Contribution default dry path construction differs')
    def issued_row(handle, kind, revalidated):
        field = kind + '_instance_handle'
        uri = 'ak.wwise.core.profiler.' + ('getVoices' if kind == 'voice' else 'getBusses')
        matches = []
        for call in calls[:-1]:
            public = call['gateway']
            if public['argv'][:2] != ['core-call', uri]:
                continue
            reads = [row for row in trace[call['native_start']:call['native_end']] if row['uri'] == uri]
            if len(reads) != 1 or reads[0]['args'] != {'time': time}:
                raise ValueError('Contribution handle seed capture time differs')
            for raw in reads[0]['result']['return']:
                for row in public['payload']['agent_result']['return']:
                    if row.get(field) == handle and raw['pipelineID'] == revalidated['pipelineID']:
                        expected = {key: value for key, value in raw.items() if key != 'pipelineID'}
                        expected[field] = handle
                        if (audit.digest(row) != audit.digest(expected)
                                or any(raw.get(key) != revalidated.get(key) for key in ('objectGUID', 'gameObjectID'))):
                            raise ValueError('Contribution issued handle identity differs from same-time revalidation')
                        matches.append(row)
        if len(matches) != 1:
            raise ValueError('Contribution issued handle relation is missing or ambiguous')
    if '--voice-object-id' in argv:
        requested, = values('--voice-object-id')
        game = values('--game-object-id')
        matches = [row for row in voices if row['objectGUID'].casefold() == requested.casefold()
            and (not game or row['gameObjectID'] == int(game[0]))]
        if len(matches) != 1 or matches[0] != voice:
            raise ValueError('Contribution exact object/game-object selection differs')
    else:
        handle, = values('--voice-instance-handle')
        issued_row(handle, 'voice', voice)
    if values('--bus-object-id'):
        if [row['objectGUID'].casefold() for row in selected_busses] != [value.casefold() for value in values('--bus-object-id')]:
            raise ValueError('Contribution ordered Bus object selection differs')
    else:
        handles = values('--bus-instance-handle')
        if len(handles) != len(selected_busses):
            raise ValueError('Contribution selected Bus handle count differs')
        for handle, row in zip(handles, selected_busses):
            issued_row(handle, 'bus', row)


def validate_runtime_source_review(descriptor, sources, branch, root, base):
    from tests.support.fixed_runtime_read_evidence import URIS, validate_source_review
    from tests.support import console_runtime_read_evidence as console
    if console.selected(branch['id'], root):
        return console.validate_source_review(descriptor, sources, branch, root, base)
    if branch['route'].split('|')[4] in URIS:
        return validate_source_review(descriptor, sources, branch, root, base)
    if branch['route'].endswith('|function|' + CONTRIBUTION_URI):
        return validate_contribution_source_review(descriptor, sources, branch, root, base)
    return validate_rtpc_source_review(descriptor, sources, branch, root, base)


def validate_contribution_source_review(descriptor, historical_sources, branch, root, base):
    review = completion.read_sealed_artifact(descriptor, base)
    version, host, build, kind, uri = branch['route'].split('|')
    if (version not in CONTRIBUTION_ORIGINALS or host != 'wwise-authoring' or kind != 'function'
            or uri != CONTRIBUTION_URI or not branch['pointer'].startswith('/resultSchema/')):
        raise ValueError('Contribution source review is limited to exact witnessed Authoring result branches')
    current = program_source_context(root, flow=uri)['packaged']
    changes = {name: {'before': historical_sources.get(name), 'after': current.get(name)}
        for name in historical_sources.keys() | current.keys() if historical_sources.get(name) != current.get(name)}
    expected = {'contract', 'historical_candidate', 'historical_sources', 'current_sources', 'changed_files',
        'changed_symbols', 'scope', 'original_capture', 'program_replay'}
    scope = {'version': version, 'host': host, 'build': RTPC_ORIGINALS[version][0], 'uri': uri,
        'original_capture_sha256': RTPC_ORIGINALS[version][1], **CONTRIBUTION_ORIGINALS[version]}
    if (set(review) != expected or review['contract'] != 'waapi-skill.runtime-read-source-review/v1'
            or review['historical_candidate'] != RTPC_ORIGINAL_CANDIDATE or build != scope['build']
            or len(historical_sources) != 413 or review['historical_sources'] != historical_sources
            or review['current_sources'] != current or review['changed_files'] != changes
            or changes != RTPC_REVIEWED_SOURCE_CHANGES or review['changed_symbols'] != RTPC_REVIEWED_SOURCE_SYMBOLS
            or review['scope'] != scope or review['original_capture']['sha256'] != scope['original_capture_sha256']):
        raise ValueError('Contribution exact reviewed source/branch closure differs')
    for key in ('original_capture', 'program_replay'):
        _portable_descriptor(review[key], base)
    original = completion.read_sealed_artifact(review['original_capture'], base)
    if audit.digest(completion.pointer_value(original, CONTRIBUTION_PARENT + '/agent_result')) != scope['projection']:
        raise ValueError('Contribution original complete projection differs')
    replay = completion.read_sealed_artifact(review['program_replay'], base)
    if (replay.get('phase_reports') != dict.fromkeys(('setup', 'call', 'teardown'), 'passed')
            or replay.get('source_unchanged') is not True or replay.get('source_context') != program_source_context(root, flow=uri)
            or audit.digest(replay['native_call']['args']) != scope['args']
            or audit.digest(replay['native_call']['result']) != scope['result']
            or audit.digest(replay['gateway']['payload']['agent_result']) != scope['projection']):
        raise ValueError('Contribution complete original public replay differs')
    provisional = {'gateway': replay['gateway'], 'native_call': replay['native_call'], 'runtime_read_program': replay,
        'relevant_sources': current}
    _validate_contribution_capture(provisional, replay['gateway']['argv'], branch['route'], root)


def validate_contribution_evidence(record, binding, branch, category, base, root, reference_edges):
    if category not in {'program', 'native'}:
        raise ValueError('Contribution attachment permits only program/native read observations')
    proof = _proof(binding, base)
    mapping = proof['mapping']
    chain = mapping.get('reference_chain', [])
    if (proof['branch_id'] != branch['id'] or proof['native_shape_sha256'] != branch['shape_sha256']
            or mapping['branch_id'] != branch['id'] or mapping['native_shape_sha256'] != branch['shape_sha256']
            or binding.get('reference_chain', []) != chain or not branch['pointer'].startswith('/resultSchema/')
            or binding['observation_pointer'] != mapping['native_pointer']
            or binding['program_observation_pointer'] != mapping['program_pointer']):
        raise ValueError('Contribution exact result branch/ref mapping differs')
    completion.exact_observation_pointer(branch, {'observation_pointer': mapping['program_pointer'], 'reference_chain': chain},
        '/native_call', 'result', reference_edges)
    completion.exact_observation_pointer(branch, {'observation_pointer': mapping['native_pointer'], 'reference_chain': chain},
        '/observations/raw', 'result', reference_edges)
    captured = completion.read_sealed_artifact(proof['program_capture'], base)
    if category == 'program':
        validate_contribution_program({**record, 'runtime_read_program': captured}, binding, branch, root, reference_edges)
        return
    read = archive_reader(proof['archive'], base)
    context = completion.read_category_run(proof['native_run'], base)
    completion.validate_authoring_batch_finalization(context['record'], base, read_bytes=read)
    _portable_descriptor(mapping['raw_observation'], base)
    expected_artifacts = {'capture': proof['capture'], 'raw': mapping['raw_observation']}
    if (record['native_runs'] != [proof['native_run']] or record['observation_artifacts'] != expected_artifacts
            or read(proof['capture_original_path']) != (base / proof['capture']['artifact']).read_bytes()
            or read(mapping['raw_original_path']) != (base / mapping['raw_observation']['artifact']).read_bytes()):
        raise ValueError('Contribution must retain exact original finalized artifacts')
    capture = completion.read_sealed_artifact(proof['capture'], base)
    raw = completion.read_sealed_artifact(mapping['raw_observation'], base)
    outcome = completion.pointer_value(capture, CONTRIBUTION_PARENT.rsplit('/', 1)[0])
    if (capture.get('complete') is not True or capture['candidate'] != context['candidate']
            or outcome.get('outcome') != 'PASS' or outcome['evidence'].get('complete') is not True
            or raw.get('ok') is not True or raw['api'] != CONTRIBUTION_URI):
        raise ValueError('Contribution original exact observation must be complete PASS')
    seal = json.loads(read(context['record']['categories'][0]['batch_finalization']['artifact']))
    node = json.loads(read(seal['observations'][proof['native_run']['nodeid']]['path']))
    receipts = [row for row in node['receipts'] if row['argv'] == mapping['original_gateway_argv']]
    if len(receipts) != 1 or receipts[0]['exit_code'] != 0 or receipts[0]['payload'].get('ok') is not True:
        raise ValueError('Contribution original exact public receipt missing')
    original = receipts[0]['payload']
    if (audit.digest(original['agent_result']) != audit.digest(outcome['evidence']['agent_result'])
            or audit.digest(original['semantic_preview']['args']) != audit.digest(captured['native_call']['args'])
            or audit.digest(raw['result']) != audit.digest(captured['native_call']['result'])
            or not mapping['raw_original_path'].endswith('/' + original['call']['evidence_path'].rsplit('/', 1)[1])):
        raise ValueError('Contribution original receipt/raw/current replay relation differs')
    historical = {key: value for key, value in node['source_context']['sources'].items() if key.startswith('skills/waapi-skill/')}
    if proof['relevant_sources'] != historical or binding['relevant_sources'] != sorted(historical):
        raise ValueError('Contribution historical source map differs')
    validate_contribution_source_review(proof['source_review'], historical, branch, root, base)
    if record['branch_assertions'][branch['id']]['checks'] != mapping['native_checks']:
        raise ValueError('Contribution exact native assertion policy differs')


def write_read_bundle(output, program_path, originals, *, inventory, version, host, mode, mappings=None, name_prefix=""):
    """Publish independent branches from one dedicated captured read flow."""
    import gzip
    import shutil
    captured = json.loads(Path(program_path).read_bytes())
    if (captured.get('phase_reports') != dict.fromkeys(('setup', 'call', 'teardown'), 'passed')
            or captured.get('source_context') != program_source_context(flow=CONTRIBUTION_URI)):
        raise ValueError('Dedicated read publication needs exact successful current phases/sources')
    route = next(row for row in inventory['native_coverage']['routes']
        if row['version'] == version and row['host'] == host and row['uri'] == CONTRIBUTION_URI)
    public = next(row for row in inventory['routes'] if row['id'] == route['public_route'])
    if mappings is None:
        if mode == 'top-data':
            fields = ('volume', 'LPF', 'HPF', 'DSF') if version == '2025.1' else ('volume', 'LPF', 'HPF')
            selected = {route['id'] + '|/resultSchema/properties/return/properties/' + field for field in fields}
        elif mode in {'cursor-capture', 'cursor-user'}:
            selected = {route['id'] + '|' + pointer for pointer in CONTRIBUTION_CURSOR_POINTERS}
        else:
            raise ValueError('Dedicated contribution mapping mode requires an exact branch selection')
        _, mappings = contribution_field_mappings(inventory, captured, version=version, host=host, selected=selected)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=bool(name_prefix))
    if name_prefix and (not name_prefix.endswith('-') or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789.-' for c in name_prefix)):
        raise ValueError('Closed contribution file prefix required')
    def destination(name):
        return output / (name_prefix + name)
    def descriptor(name):
        return {'artifact': name_prefix + name, 'sha256': sha(destination(name).read_bytes())}
    shutil.copyfile(program_path, destination('program-capture.json'))
    candidate = inventory['native_coverage']['candidate_sha256']
    sources = captured['source_context']['packaged']
    program = {'candidate_sha256': candidate, 'scope_kind': 'product', 'relevant_sources': sources,
        'gateway': captured['gateway'], 'native_call': captured['native_call'], 'runtime_read_program': captured,
        'invocation': {'phase': 'final', 'outcome': 'PASS', 'node_outcomes': [{'nodeid': captured['nodeid'], 'outcome': 'PASS'}]},
        'branch_assertions': {}}
    native = context = source_review = original_gateway_argv = raw_path = capture_path = None
    historical = None
    if originals is not None:
        if host != 'wwise-authoring' or version not in CONTRIBUTION_ORIGINALS:
            raise ValueError('Only qualified original contribution Authoring producers may attach')
        for name in ('original-category.json', 'original-capture.json', 'original-closure.json.gz'):
            shutil.copyfile(originals / name, destination(name))
        native_run = {**descriptor('original-category.json'),
            'nodeid': 'tests/destructive/test_authoring_ui_business_live.py::test_runtime_owned_missing_profiler_reads'}
        context = completion.read_category_run(native_run, output)
        read = archive_reader(descriptor('original-closure.json.gz'), output)
        completion.validate_authoring_batch_finalization(context['record'], output, read_bytes=read)
        seal = json.loads(read(context['record']['categories'][0]['batch_finalization']['artifact']))
        node = json.loads(read(seal['observations'][native_run['nodeid']]['path']))
        original_receipt, = [row for row in node['receipts'] if row['argv'][0] == 'profiler-voice-contributions'
            and '--bus-instance-handle' in row['argv']]
        original_gateway_argv = original_receipt['argv']
        files = json.loads(gzip.decompress((destination('original-closure.json.gz')).read_bytes()))['files']
        capture_path, = [name for name in files if name.endswith('/profiler-capture.json')]
        raw_path, = [name for name in files if name.endswith('/' + original_receipt['payload']['call']['evidence_path'].rsplit('/', 1)[1])]
        (destination('original-native-result.json')).write_bytes(read(raw_path))
        native_run['observation_sha256'] = [descriptor('original-capture.json')['sha256'], descriptor('original-native-result.json')['sha256']]
        historical = {key: value for key, value in node['source_context']['sources'].items() if key.startswith('skills/waapi-skill/')}
        source_review = write_json(destination('source-review.json'), {
            'contract': 'waapi-skill.runtime-read-source-review/v1', 'historical_candidate': RTPC_ORIGINAL_CANDIDATE,
            'historical_sources': historical, 'current_sources': sources, 'changed_files': RTPC_REVIEWED_SOURCE_CHANGES,
            'changed_symbols': RTPC_REVIEWED_SOURCE_SYMBOLS,
            'scope': {'version': version, 'host': host, 'build': route['build'], 'uri': CONTRIBUTION_URI,
                'original_capture_sha256': RTPC_ORIGINALS[version][1], **CONTRIBUTION_ORIGINALS[version]},
            'original_capture': descriptor('original-capture.json'), 'program_replay': descriptor('program-capture.json')})
        native = {'candidate_sha256': candidate, 'scope_kind': 'product', 'evidence_kind': 'native_execution',
            'relevant_sources': historical, 'invocation': context['record']['invocation'], 'native_runs': [native_run],
            'observation_artifacts': {'capture': descriptor('original-capture.json'), 'raw': descriptor('original-native-result.json')},
            'branch_assertions': {}}
    document = {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': {}}
    policy = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {}}
    for mapping in mappings:
        branch, pointer = mapping['branch'], mapping['program_pointer']
        identity = branch['id']
        public_pointer = contribution_branch_public_pointer(branch, pointer)
        program['branch_assertions'][identity] = {'native_shape_sha256': branch['shape_sha256'], 'native_route': branch['route'],
            'checks': [({'pointer': pointer, 'absent': True} if branch['kind'] == 'optional_presence' and branch['value'] == 'absent'
                else {'pointer': pointer, 'cardinality': branch['value']} if branch['kind'] == 'collection_cardinality'
                else {'pointer': pointer, 'equals': completion.pointer_value(program, pointer)}),
                {'pointer': public_pointer, 'equals': completion.pointer_value(captured, public_pointer)}]}
        if branch['pointer'] in CONTRIBUTION_CURSOR_POINTERS:
            choice = '/gateway/argv/' + str(captured['gateway']['argv'].index('--capture') + 1)
            program['branch_assertions'][identity]['checks'].extend([
                {'pointer': choice, 'equals': completion.pointer_value(captured, choice)},
                {'pointer': '/native_call/args/time', 'equals': captured['native_call']['args']['time']}])
        elif not branch['pointer'].startswith('/resultSchema'):
            semantic = contribution_public_pointer(pointer)
            semantic_check = ({'pointer': semantic, 'absent': True}
                if branch['kind'] == 'optional_presence' and branch['value'] == 'absent'
                else {'pointer': semantic, 'equals': completion.pointer_value(captured, semantic)})
            program['branch_assertions'][identity]['checks'].append(semantic_check)
        binding = {'branch_id': identity, 'native_shape_sha256': branch['shape_sha256'],
            'public_route': public['id'], 'public_route_sha256': audit.digest(public),
            'input': {'gateway_argv': captured['gateway']['argv'], 'selector': pointer},
            'dispatch_pointer': '/native_call', 'observation_pointer': pointer,
            'gateway_observation_pointer': public_pointer, 'reference_chain': mapping['reference_chain'],
            'relevant_sources': sorted(sources), 'evidence': {},
            'construction': {'source': 'skills/waapi-skill/wwise_waapi/builders/stable_reads.py#build_profiler_voice_contributions_request', 'selector': branch['pointer']},
            'validation': {'source': 'skills/waapi-skill/wwise_waapi/builders/schema.py#validate_resolved_semantic_result', 'selector': branch['pointer']},
            'verifier': {'source': 'skills/waapi-skill/wwise_waapi/builders/stable_reads.py#normalize_profiler_voice_contributions_result', 'selector': branch['pointer']}}
        document['bindings'][identity] = binding
        policy['branches'][identity] = {'native_shape_sha256': branch['shape_sha256'], 'categories': mapping['categories'],
            'reason': ('Exact reported contribution data/reference/presence/multiple occurrence; independent native fact required'
                if mapping['categories'] == ['program', 'native'] else
                'SPEC section 5 exact public choice to one cursor snapshot to same-time identity/final numeric construction; no actual native occurrence/data/effect claim'
                if branch['pointer'] in CONTRIBUTION_CURSOR_POINTERS else
                'SPEC section 5 exact contribution construction/predicate/decoder preservation; no actual native occurrence/data/effect or descendant claim')}
        if native is not None and mapping['categories'] == ['program', 'native']:
            native_pointer = pointer.replace('/native_call', '/observations/raw', 1)
            raw_record = {'observations': {'raw': json.loads((destination('original-native-result.json')).read_bytes())}}
            checks = [({'pointer': native_pointer, 'cardinality': branch['value']}
                if branch['kind'] == 'collection_cardinality'
                else {'pointer': native_pointer, 'equals': completion.pointer_value(raw_record, native_pointer)}),
                {'pointer': '/observations/capture/complete', 'equals': True}]
            native['branch_assertions'][identity] = {'native_shape_sha256': branch['shape_sha256'], 'native_route': branch['route'], 'checks': checks}
            mapping.update(branch_id=identity, native_shape_sha256=branch['shape_sha256'], native_pointer=native_pointer,
                native_result_parent='/observations/raw', native_checks=checks, original_gateway_argv=original_gateway_argv,
                raw_observation=descriptor('original-native-result.json'), raw_original_path=raw_path)
    program_descriptor = {**write_json(destination('program.json'), program), 'nodeid': captured['nodeid']}
    for binding in document['bindings'].values():
        binding['evidence']['program'] = deepcopy(program_descriptor)
    bindings_descriptor = write_json(destination('bindings.json'), document)
    requirements_descriptor = write_json(destination('requirements.json'), policy)
    attachments = []
    if native is not None:
        native_descriptor = {**write_json(destination('native.json'), native), 'nodeid': native_run['nodeid']}
        for index, mapping in enumerate(mappings):
            if mapping['categories'] != ['program', 'native']:
                continue
            branch = mapping['branch']; identity = branch['id']; binding = deepcopy(document['bindings'][identity])
            proof = {'contract': 'waapi-skill.runtime-observation-proof/v1', 'branch_id': identity,
                'native_shape_sha256': branch['shape_sha256'], 'mapping': {key: value for key, value in mapping.items() if key != 'branch'},
                'native_run': native_run, 'archive': descriptor('original-closure.json.gz'), 'capture': descriptor('original-capture.json'),
                'capture_original_path': capture_path, 'program_capture': descriptor('program-capture.json'),
                'relevant_sources': historical, 'source_review': source_review}
            proof_descriptor = write_json(destination(f'proof-{index}.json'), proof)
            binding.update(runtime_observation_attachment=proof_descriptor, program_observation_pointer=mapping['program_pointer'],
                observation_pointer=mapping['native_pointer'], native_observations_sha256={
                    'capture': descriptor('original-capture.json')['sha256'], 'raw': descriptor('original-native-result.json')['sha256']})
            equivalence = {'contract': 'waapi-skill.branch-evidence-equivalence/v1', 'from_candidate': context['candidate'],
                'to_candidate': candidate, 'branch_id': identity, 'native_shape_sha256': branch['shape_sha256'], 'native_route': branch['route'],
                'evidence_sha256': native_run['sha256'], 'binding_semantics_sha256': audit.digest(completion.binding_semantics(binding)),
                'reviewed_reason': 'Exact reviewed contribution result/identity guard and disclosed business choice/optional decoder delta; complete original native request/result and public projection preserved',
                'sources': historical, 'runtime_read_review': source_review}
            equivalence_descriptor = write_json(destination(f'native-equivalence-{index}.json'), equivalence)
            attachments.append(write_json(destination(f'attachment-{index}.json'), {'contract': 'waapi-skill.runtime-observation-attachment/v1',
                'branch_id': identity, 'proof': proof_descriptor, 'evidence': native_descriptor, 'native_equivalence': equivalence_descriptor}))
    write_json(destination('index.json'), {'contract': 'waapi-skill.branch-evidence-index/v1', 'base': '.',
        'entries': [{'id': f'contribution-{version}-{host}-{mode}', 'bindings': bindings_descriptor,
            'origin': {'bindings': bindings_descriptor, 'program': descriptor('program.json'),
                'requirements': requirements_descriptor, 'capture': descriptor('program-capture.json')}}],
        **({'runtime_observation_attachments': attachments} if attachments else {})})
    return destination('index.json')


def _contribution_node(branch, root=audit.ROOT):
    from wwise_waapi.native_catalog import load_native_catalog
    version, host, _, _, uri = branch['route'].split('|')
    catalog = load_native_catalog(version, host, root=root / 'skills/waapi-skill/resources/native-catalog')
    pointer = branch['pointer'].split('/@presence/')[0].split('/@cardinality/')[0].split('/@empty/')[0]
    if '/@definition/' in pointer:
        _, rest = pointer.split('/@definition/', 1)
        name, suffix = rest.split('/', 1)
        return completion.pointer_value(catalog['definitions']['documents'][name], '/' + suffix)
    return completion.pointer_value(catalog['schemas'][uri], pointer)


def _contribution_categories(branch, node):
    if not branch['pointer'].startswith('/resultSchema'):
        return ['program']
    if (branch['kind'] in {'constraint', 'empty_object', 'empty_string'}
            or branch['kind'] == 'optional_presence' and branch['value'] == 'absent'
            or branch['kind'] == 'collection_cardinality' and branch['value'] in {'empty', 'single'}):
        return ['program']
    if branch['kind'] == 'schema' and (node is False or isinstance(node, dict) and (
            node.get('type') in {'object', 'array'} or 'voiceContributionsObject' in node.get('$ref', ''))):
        return ['program']
    return ['program', 'native']


def _contribution_predicate(branch, node, value, *, root=audit.ROOT):
    import re
    kind = branch['kind']
    if kind == 'optional_presence':
        return value is _CONTRIBUTION_ABSENT if branch['value'] == 'absent' else value is not _CONTRIBUTION_ABSENT
    if value is _CONTRIBUTION_ABSENT:
        return False
    if kind == 'collection_cardinality':
        return isinstance(value, list) and branch['value'] == ('empty' if not value else 'single' if len(value) == 1 else 'multiple')
    if kind in {'empty_object', 'empty_string', 'enum_value'}:
        return type(value) is type(branch['value']) and value == branch['value']
    if kind == 'constraint':
        predicate = branch['pointer'].rsplit('/', 1)[1]
        return (type(value) is str and re.search(node, value) is not None if predicate == 'pattern'
            else type(value) is int and value == node if predicate in {'minimum', 'maximum'} else False)
    if kind == 'reference':
        parent = {**branch, 'kind': 'schema', 'pointer': branch['pointer'].rsplit('/', 1)[0]}
        parent_node = _contribution_node(parent, root)
        # The pinned recursive contribution object uses the already mandatory
        # resolved result guard, including its disclosed legacy driver rule.
        if 'voiceContributionsObject' in node:
            return type(value) is dict
        try:
            completion.validate_native_alternative(root, {**parent, 'shape_sha256': audit.digest(parent_node)}, value)
        except (ValueError, TypeError):
            return False
        return True
    if kind != 'schema':
        return False
    if node is False:
        parent = _contribution_node({**branch, 'pointer': branch['pointer'].rsplit('/', 1)[0]}, root)
        return type(value) is dict and set(value) <= set(parent.get('properties', {}))
    if not isinstance(node, dict):
        return False
    if re.search(r'/oneOf/[0-9]+$', branch['pointer']):
        try:
            completion.validate_native_alternative(root, branch, value)
        except (ValueError, TypeError):
            return False
        if branch['pointer'].endswith('/properties/driver/oneOf/1'):
            return type(value) is str and not re.fullmatch(r'\{[a-fA-F0-9-]{36}\}', value)
        return True
    types = {'object': (dict,), 'array': (list,), 'string': (str,), 'integer': (int,), 'number': (int, float)}
    if 'type' in node and type(value) not in types.get(node['type'], ()):
        return False
    if node.get('type') == 'object':
        return (set(node.get('required', ())) <= value.keys()
            and (node.get('additionalProperties') is not False or value.keys() <= node.get('properties', {}).keys()))
    if 'pattern' in node and (type(value) is not str or re.search(node['pattern'], value) is None):
        return False
    if 'enum' in node and not any(type(value) is type(choice) and value == choice for choice in node['enum']):
        return False
    if '$ref' in node and 'voiceContributionsObject' not in node['$ref']:
        try:
            completion.validate_native_alternative(root, branch, value)
        except (ValueError, TypeError):
            return False
    return True


_CONTRIBUTION_ABSENT = object()


def _contribution_chains(branch, edges):
    if '/@definition/' not in branch['pointer']:
        return [[]]
    candidates = []
    def visit(chain, target, seen):
        if branch['pointer'] == target or branch['pointer'].startswith(target + '/'):
            candidates.append(chain)
        if len(chain) >= 4:
            return
        for edge in edges.values():
            if edge['route'] != branch['route'] or not edge['pointer'].startswith(target + '/'):
                continue
            reached = edge['reference']['target'].split('|', 5)[5]
            if reached in seen:
                continue
            visit(chain + [edge['id']], reached, seen | {reached})
    section = '/' + branch['pointer'].split('/')[1]
    for edge in edges.values():
        if edge['route'] == branch['route'] and edge['pointer'].startswith(section + '/') and '/@definition/' not in edge['pointer']:
            target = edge['reference']['target'].split('|', 5)[5]
            visit([edge['id']], target, {target})
    return candidates


def _contribution_pattern(branch, chain, edges):
    previous, pattern = None, []
    for identity in chain:
        edge = edges[identity]
        source = edge['pointer'] if previous is None else edge['pointer'][len(previous):]
        pattern += completion.native_observation_pattern(source)
        previous = edge['reference']['target'].split('|', 5)[5]
    pattern += completion.native_observation_pattern(branch['pointer'] if previous is None else branch['pointer'][len(previous):])
    section = {'argsSchema': 'args', 'optionsSchema': 'options', 'resultSchema': 'result'}[branch['pointer'].split('/')[1]]
    return ['native_call', section, *pattern]


def _contribution_occurrences(record, tokens, prefix=''):
    if not tokens:
        yield prefix, record
        return
    token, rest = tokens[0], tokens[1:]
    if token == '*':
        if type(record) is list:
            for index, value in enumerate(record):
                yield from _contribution_occurrences(value, rest, prefix + '/' + str(index))
    elif type(record) is dict:
        if token in record:
            yield from _contribution_occurrences(record[token], rest, prefix + '/' + token)
        elif not rest:
            yield prefix + '/' + token, _CONTRIBUTION_ABSENT


def contribution_field_mappings(inventory, captured, *, version, host, selected=None):
    route = next(row for row in inventory['native_coverage']['routes']
        if row['version'] == version and row['host'] == host and row['uri'] == CONTRIBUTION_URI)
    rows = [row for row in inventory['native_coverage']['obligations'] if row['route'] == route['id']]
    edges = {row['id']: row for row in rows if row['kind'] == 'reference'}
    mappings = []
    for branch in rows:
        if selected is not None and branch['id'] not in selected:
            continue
        node = _contribution_node(branch)
        if branch['pointer'] in CONTRIBUTION_CURSOR_POINTERS:
            argv = captured['gateway']['argv']
            cursors = [row for row in captured.get('native_reads', [])
                if row['uri'] == 'ak.wwise.core.profiler.getCursorTime']
            if '--capture' in argv and len(cursors) == 1 and _contribution_predicate(branch, node, cursors[0]['args']['cursor']):
                mappings.append({'branch': branch,
                    'program_pointer': f"/runtime_read_program/native_reads/{cursors[0]['ordinal']}/args/cursor",
                    'reference_chain': _contribution_chains(branch, edges)[0], 'categories': ['program']})
            continue
        for chain in _contribution_chains(branch, edges):
            match = next(((pointer, value) for pointer, value in _contribution_occurrences(captured,
                _contribution_pattern(branch, chain, edges)) if _contribution_predicate(branch, node, value)), None)
            if match is not None:
                mappings.append({'branch': branch, 'program_pointer': match[0], 'reference_chain': chain,
                    'categories': _contribution_categories(branch, node)})
                break
    return route, mappings


def contribution_branch_public_pointer(branch, pointer):
    if not branch['pointer'].startswith('/resultSchema'):
        return '/gateway/payload/agent_result'
    public = contribution_public_pointer(pointer)
    if (branch['kind'] == 'optional_presence' and branch['value'] == 'absent'
            and (pointer.startswith('/native_call/args/') or pointer.startswith('/native_call/result/return/objects/'))):
        return public.rsplit('/', 1)[0]
    return public


def _validate_contribution_branch(record, binding, branch, root):
    node = _contribution_node(branch, root)
    if branch['kind'] in {'schema', 'reference', 'constraint'} and audit.digest(node) != branch['shape_sha256']:
        raise ValueError('Contribution exact pinned predicate shape differs')
    pointer = binding.get('program_observation_pointer') if binding.get('runtime_observation_attachment') else binding['observation_pointer']
    if branch['kind'] == 'optional_presence' and branch['value'] == 'absent':
        parent = completion.pointer_value(record, pointer.rsplit('/', 1)[0])
        if type(parent) is not dict or pointer.rsplit('/', 1)[1] in parent:
            raise ValueError('Contribution absence requires the existing exact parent and missing field')
        value = _CONTRIBUTION_ABSENT
    else:
        value = completion.pointer_value(record, pointer)
    if not _contribution_predicate(branch, node, value, root=root):
        raise ValueError('Contribution exact pinned branch predicate failed')
    version = branch['route'].split('|')[0]
    if version in {'2021.1', '2022.1', '2023.1'} and '/properties/driver' in branch['pointer']:
        rules = record['gateway']['payload']['schema_validation']['result'].get('compatibility_rules', [])
        if not any(rule.get('rule_id') == 'profiler-contribution-driver-reason-or-guid/v1'
                and rule.get('version') == version and rule.get('uri') == CONTRIBUTION_URI
                and rule.get('reflected_definition_sha256') == '65a31a502cc581aebc372d674d16d60e772329b957474418d10aec3fa70f02f7' for rule in rules):
            raise ValueError('Contribution legacy driver preservation requires its explicit pinned compatibility disclosure')


def write_read_stage(output, captures, originals, *, inventory, family_prefix="", selected_ids=None):
    """Join independently selected contribution branches in one portable index."""
    if family_prefix not in {'', 'contribution-'}:
        raise ValueError('Closed contribution family prefix required')
    versions = ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1')
    expected = {(version, host, mode) for version in versions for host in ('wwise-console', 'wwise-authoring')
        for mode in ('rich', 'single', 'empty', 'absent', 'omit', 'cursor-capture', 'cursor-user')}
    expected |= {(version, host, 'partial') for version in versions[:2] for host in ('wwise-console', 'wwise-authoring')}
    expected |= {(version, 'wwise-authoring', 'original') for version in ('2022.1', '2025.1')}
    cursor_only = {(version, host, mode) for version in versions for host in ('wwise-console', 'wwise-authoring')
        for mode in ('cursor-capture', 'cursor-user')}
    cursor_scope = set(captures) == cursor_only and not originals
    if not cursor_scope and (set(captures) != expected or set(originals) != {'2022.1', '2025.1'}):
        raise ValueError('Contribution stage requires the complete exact five-version public flow set')
    if cursor_scope:
        expected = cursor_only
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    policy = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {}}
    index = {'contract': 'waapi-skill.branch-evidence-index/v1', 'base': '.', 'entries': []}
    attachments, selected = [], set()
    wanted = {row['id'] for row in inventory['native_coverage']['obligations']
        if (row.get('route') or '').endswith('|function|' + CONTRIBUTION_URI)
        and (not cursor_scope or row['pointer'] in CONTRIBUTION_CURSOR_POINTERS)}
    if selected_ids is not None:
        if not set(selected_ids) <= wanted: raise ValueError('Contribution stage selected IDs escape its exact routes')
        wanted = set(selected_ids)
    for version, host, mode in sorted(expected, key=lambda key: (key[2] != 'original', key)):
        captured = json.loads(Path(captures[version, host, mode]).read_bytes())
        route_ids = {row['id'] for row in inventory['native_coverage']['obligations']
            if row['route'] is not None and row['route'].split('|')[:2] == [version, host]
            and row['route'].endswith('|function|' + CONTRIBUTION_URI)
            and (not cursor_scope or row['pointer'] in CONTRIBUTION_CURSOR_POINTERS)}
        _, mappings = contribution_field_mappings(inventory, captured, version=version, host=host, selected=route_ids & wanted - selected)
        if not mappings:
            continue
        flow = write_read_bundle(output, captures[version, host, mode], originals.get(version) if mode == 'original' else None,
            inventory=inventory, version=version, host=host, mode=mode, mappings=mappings,
            name_prefix=f'{family_prefix}{version}-{host}-{mode}-')
        document = json.loads(flow.read_bytes())
        index['entries'].extend(document['entries'])
        attachments.extend(document.get('runtime_observation_attachments', []))
        flow_policy = completion.read_sealed_artifact(document['entries'][0]['origin']['requirements'], output)
        if selected & flow_policy['branches'].keys():
            raise ValueError('Contribution batch repeats an exact branch')
        selected |= flow_policy['branches'].keys()
        policy['branches'].update(flow_policy['branches'])
    if selected != wanted:
        raise ValueError('Contribution batch has unproved exact branches: ' + repr(sorted(wanted - selected)))
    if attachments:
        index['runtime_observation_attachments'] = attachments
    write_json(output / 'index.json', index)
    write_json(output / 'requirements.json', policy)
    return output / 'index.json'


# User-approved exact successor; historical requirement packages remain immutable.
RUNTIME_RISK_POLICY = 'tests/fixtures/runtime/runtime-risk-policy-r124.json'
RUNTIME_RISK_POLICY_SHA = 'a139358c1f98a15ce99e28961bb1e4b8e059976a8665df5ab350637ccd6e2a57'
RUNTIME_OPAQUE_POLICY = 'tests/fixtures/runtime/runtime-opaque-policy-r126.json'
RUNTIME_OPAQUE_POLICY_SHA = '00b3d385535770ba2315f1a06fc64f002d8a4a43507e841736b08c42620ea591'
RUNTIME_RISK_URIS = frozenset('ak.wwise.core.profiler.' + name for name in
    ('getVoices', 'getBusses', 'getAudioObjects', 'getGameObjects', 'getVoiceContributions', 'getRTPCs'))


def runtime_risk_review(root):
    raw = (root / RUNTIME_RISK_POLICY).read_bytes()
    if sha(raw) != RUNTIME_RISK_POLICY_SHA:
        raise ValueError('Exact reviewed runtime risk policy changed')
    review = json.loads(raw)
    if (len(review['entries']) != 6292 or len(review['changed_ids']) != 2076
            or len(review['still_native_anchor_ids']) != 316):
        raise ValueError('Runtime risk policy roster differs')
    for package in review['historical_packages'].values():
        if sha((root / package['path']).read_bytes()) != package['sha256']:
            raise ValueError('Immutable historical runtime requirements changed')
    return _runtime_opaque_successor(review, root)


def _runtime_opaque_successor(predecessor, root):
    """Compose the exact source-owned delta without rewriting the R124 record."""
    raw = (root / RUNTIME_OPAQUE_POLICY).read_bytes()
    if sha(raw) != RUNTIME_OPAQUE_POLICY_SHA:
        raise ValueError('Exact reviewed runtime opaque successor changed')
    delta = json.loads(raw)
    if (delta['predecessor'] != {'path': RUNTIME_RISK_POLICY, 'sha256': RUNTIME_RISK_POLICY_SHA}
            or len(delta['entries']) != 44 or len(delta['dependency_updates']) != 144):
        raise ValueError('Runtime opaque successor roster differs')
    result = deepcopy(predecessor)
    changed = set(delta['entries'])
    if not changed <= set(predecessor['still_native_anchor_ids']):
        raise ValueError('Runtime opaque successor must retain exact predecessor identities')
    for identity, transition in delta['entries'].items():
        entry = result['entries'][identity]
        if (audit.digest(entry) != transition['before_entry_sha256']
                or audit.digest(transition['before_policy']) != entry['old_policy_sha256']
                or any(transition[key] != entry[key] for key in
                    ('route', 'pointer', 'kind', 'native_shape_sha256', 'owner_issue', 'parent_issue', 'blocks_issue'))):
            raise ValueError('Runtime opaque successor predecessor differs')
        entry.update(proposed_categories=['program'], role='conditional_opaque_result_preservation',
            rationale_key=transition['rationale_key'], required_native_anchor_ids=transition['required_native_anchor_ids'])
        if transition['after_policy'] != runtime_preservation_policy(entry):
            raise ValueError('Runtime opaque successor proposed policy differs')
    for identity, transition in delta['dependency_updates'].items():
        entry = result['entries'][identity]
        if (entry['required_native_anchor_ids'] != transition['before']
                or transition['after'] != [anchor for anchor in transition['before'] if anchor not in changed]):
            raise ValueError('Runtime opaque successor dependency transition differs')
        entry['required_native_anchor_ids'] = transition['after']
    result['changed_ids'] = sorted(set(predecessor['changed_ids']) | changed)
    result['still_native_anchor_ids'] = sorted(set(predecessor['still_native_anchor_ids']) - changed)
    for route in result['by_route_anchors'].values():
        for field in ('all_retained_native_ids', 'retained_native_semantic_ids'):
            route[field] = [identity for identity in route[field] if identity not in changed]
    retained = set(result['still_native_anchor_ids'])
    for identity in result['changed_ids']:
        entry = result['entries'][identity]
        anchors = entry['required_native_anchor_ids']
        if (not anchors or not set(anchors) <= retained
                or any(result['entries'][anchor]['route'] != entry['route'] for anchor in anchors)):
            raise ValueError('Runtime opaque preservation requires retained same-route native anchors')
    if len(result['changed_ids']) != 2120 or len(retained) != 272:
        raise ValueError('Runtime opaque successor effective counts differ')
    result['counts'].update(changed_ids=2120, proposed_native_ids=272, native_to_program=2120)
    result['opaque_successor'] = {'path': RUNTIME_OPAQUE_POLICY, 'sha256': RUNTIME_OPAQUE_POLICY_SHA}
    return result


def runtime_preservation_policy(entry):
    return {'native_shape_sha256': entry['native_shape_sha256'], 'categories': ['program'],
        'reason': 'User-approved runtime risk policy: ' + entry['rationale_key']
            + '; exact native anchors required; native value occurrence unclaimed'}


def runtime_successor_requirements(requirements, root=audit.ROOT):
    """Produce only the sealed per-ID successor; no caller-selected downgrade."""
    review = runtime_risk_review(root)
    result = deepcopy(requirements)
    changed = set(review['changed_ids'])
    for identity, policy in result['branches'].items():
        if identity in changed:
            entry = review['entries'][identity]
            if audit.digest(policy) != entry['old_policy_sha256']:
                raise ValueError('Runtime successor requires exact original policy digest')
            result['branches'][identity] = runtime_preservation_policy(entry)
    return result


def runtime_risk_route(identity):
    parts = identity.split('|')
    return len(parts) >= 5 and parts[4] in RUNTIME_RISK_URIS


def runtime_successor_policy_matches(review, identity, original, proposed):
    entry = review['entries'].get(identity, {})
    return (identity in review['changed_ids']
        and audit.digest(original) == entry['old_policy_sha256']
        and proposed == runtime_preservation_policy(entry))


def runtime_preservation_gates(root, policies, obligations):
    """Flat exact-route anchor prerequisites for this closed runtime roster only."""
    if not any(branch['id'] in policies and runtime_risk_route(branch['id']) for branch in obligations):
        return {}
    review = runtime_risk_review(root)
    changed = set(review['changed_ids'])
    gates = {}
    for branch in obligations:
        identity = branch['id']
        if identity not in changed or identity not in policies:
            continue
        entry, policy = review['entries'][identity], policies[identity]
        if 'native' in policy.get('categories', []):
            continue  # Existing stricter packages/qualified assessments retain their own policy and facts.
        if (policy != runtime_preservation_policy(entry)
                or branch['shape_sha256'] != entry['native_shape_sha256']
                or branch['route'] != entry['route']
                or any(branch.get(key) != entry[key] for key in ('owner_issue', 'parent_issue', 'blocks_issue'))):
            gates[identity] = None
        else:
            gates[identity] = entry['required_native_anchor_ids']
    return gates


def apply_runtime_preservation_gates(obligations, policies, gates):
    rows = {row['id']: row for row in obligations}
    for identity, anchors in gates.items():
        row = rows[identity]
        failed = []
        for anchor in anchors or ():
            witness = rows.get(anchor, {})
            if (witness.get('route') != row['route']
                    or 'native' not in policies.get(anchor, {}).get('categories', [])
                    or witness.get('state') != 'verified'
                    or witness.get('evidence_results', {}).get('native', {}).get('outcome') != 'passed'):
                failed.append(anchor)
        row['runtime_native_anchor_requirements'] = anchors
        row['runtime_native_anchor_status'] = 'passed' if anchors is not None and not failed else 'missing'
        if anchors is None or failed:
            if anchors is None and row['state'] != 'missing_implementation':
                row['state'] = 'unresolved'
            elif row['state'] == 'verified':
                row['state'] = 'implemented_unverified'
            row['reasons'].append('Exact reviewed runtime preservation policy or native anchors missing: '
                + (', '.join(failed) if anchors is not None else 'unreviewed successor'))


def validate_runtime_file_prefix(prefix):
    if prefix and (len(prefix) > 128 or not prefix.endswith('-') or '..' in prefix
            or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789.-' for c in prefix)):
        raise ValueError('Closed runtime filename prefix required')


def copy_runtime_common_base_file(source, destination):
    """Project exact bytes at the existing relative locator, never overwrite."""
    raw = Path(source).read_bytes(); destination = Path(destination)
    if destination.exists():
        if destination.read_bytes() != raw:
            raise ValueError('Runtime common-base path collision')
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(raw)


def write_runtime_composition(output, components):
    """Compose existing ordinary indices without changing nested descriptors."""
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    base = output / 'evidence'
    index = {'contract': 'waapi-skill.branch-evidence-index/v1', 'base': 'evidence', 'entries': []}
    policy = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {}}
    entry_ids = set()
    attachment_keys = ('metadata_attachments','source_attachments','source_native_attachments',
        'runtime_observation_attachments','qualified_runtime_read_attachments',
        'condition_mechanism_attachments','condition_definition_attachments')
    for index_path, original_policy in components:
        index_path = Path(index_path); document = json.loads(index_path.read_bytes())
        source = (index_path.parent / document['base']).resolve()
        if (set(document) - {'contract','base','entries',*attachment_keys}
                or document['contract'] != index['contract'] or original_policy['contract'] != policy['contract']
                or policy['branches'].keys() & original_policy['branches'].keys()):
            raise ValueError('Runtime composition duplicates an exact branch or contract')
        for entry in document['entries']:
            if entry['id'] in entry_ids:
                raise ValueError('Runtime composition duplicates an entry identity')
            entry_ids.add(entry['id'])
        seen = {}
        def retain(value):
            if isinstance(value, dict):
                # The existing portable importer projects these origin locators.
                if value.get('contract') == 'waapi-skill.branch-bindings/v1': return
                if value.get('contract') == 'waapi-skill.class-metadata-read/v1':
                    seal = json.loads((source / value['seal']['artifact']).read_bytes())
                    for item in seal['files']:
                        retain({'artifact':str(Path(value['root']) / item['path']), 'sha256':item['sha256']})
                if isinstance(value.get('artifact'), str) and isinstance(value.get('sha256'), str):
                    name = value['artifact']
                    if not Path(name).is_absolute():
                        origin = source / name
                        if not origin.resolve().is_relative_to(source):
                            raise ValueError('Runtime common-base artifact escapes its original base')
                        raw = origin.read_bytes()
                        if sha(raw) != value['sha256'] or name in seen and seen[name] != value['sha256']:
                            raise ValueError('Runtime common-base original descriptor changed')
                        if name not in seen:
                            seen[name] = value['sha256']
                            copy_runtime_common_base_file(origin, base / name)
                            if origin.suffix in {'.json', '.jsonl'}:
                                try: records = [json.loads(raw)]
                                except json.JSONDecodeError as error:
                                    if error.msg != 'Extra data': raise
                                    records = [json.loads(line) for line in raw.splitlines() if line.strip()]
                                for row in records: retain(row)
                for child in value.values(): retain(child)
            elif isinstance(value, list):
                for child in value: retain(child)
        retain(document)
        index['entries'].extend(document['entries'])
        for key in attachment_keys:
            if document.get(key): index.setdefault(key, []).extend(document[key])
        policy['branches'].update(original_policy['branches'])
    write_json(output / 'requirements.json', policy)
    write_json(output / 'index.json', index)
    return output / 'index.json', policy


def runtime_publication_plan(root=audit.ROOT):
    """Allocate the accepted native roster first; generic flows own the remainder."""
    from tests.support import console_runtime_read_evidence as console
    from tests.support import qualified_runtime_read_evidence as qualified
    review = runtime_risk_review(root); anchors = set(review['still_native_anchor_ids'])
    owners = {}; external = set(); packets = {'console': [], 'qualified': [], 'strict-seed': []}
    def take(kind, version, category, identities):
        identities = sorted(set(identities) & anchors - owners.keys())
        if identities:
            owners.update(dict.fromkeys(identities, kind))
            if kind in packets:
                packets[kind].append({'version':version, 'category':category, 'ids':identities})
                external.update(identities)
    scope = console.profiles(root)
    for version, profile in scope['profiles'].items():
        for category, reader in profile['readers'].items():
            take('console', version, category, reader['selectors'])
    for path, seal in ((qualified.ANCHOR_SELECTORS, qualified.ANCHOR_SELECTORS_SHA),
                       (qualified.R104_SELECTORS, qualified.R104_SELECTORS_SHA)):
        raw = (root / path).read_bytes()
        if sha(raw) != seal: raise ValueError('Runtime publication qualified roster changed')
        for key, profile in json.loads(raw)['profiles'].items():
            version, category = key.split('|')
            take('qualified', version, category, [row['id'] for row in profile['selectors']])
    # These four original R114 packets already have qualified admission. Select
    # only their remaining semantic anchors, not the former82 codec occurrences.
    for version in ('2023.1', '2024.1'):
        for category in ('profiler-rtpcs-observation', 'profiler-contributions-bus-observation'):
            route = f"{version}|wwise-authoring|{qualified.PROFILES[version]['build']}|function|{qualified.CATEGORIES[category]}"
            take('qualified', version, category, [i for i in anchors if review['entries'][i]['route'] == route])
    seed_path = root / 'tests/fixtures/runtime-fixed-reads/r105-2022-seed-selectors.json'
    raw = seed_path.read_bytes()
    if sha(raw) != '0af89b4294b789f910a876fbe2d8debf9944ea0a128f6521bd2207a03c08e626':
        raise ValueError('Runtime publication strict seed roster changed')
    for name, profile in json.loads(raw)['profiles'].items():
        take('strict-seed', '2022.1', name, profile['matching_missing_ids'])
    for family, directory in (('rtpc','runtime-rtpc-complete-r112'),
            ('contribution','runtime-contributions-r113'), ('fixed','runtime-fixed-reads-r121')):
        base = root / 'tests/fixtures/branch-evidence/product' / directory
        index = json.loads((base / 'index.json').read_bytes())
        for descriptor in index.get('runtime_observation_attachments', []):
            item = completion.read_sealed_artifact(descriptor, base)
            take('existing-' + family, None, None, [item['branch_id']])
    if set(owners) != anchors:
        raise ValueError('Runtime publication lacks an accepted native source: ' + repr(sorted(anchors - owners.keys())))
    program = {family:sorted(i for i,e in review['entries'].items() if e['family'] == family and i not in external)
        for family in ('fixed','rtpc','contribution')}
    assigned = [i for values in program.values() for i in values] + [i for rows in packets.values() for row in rows for i in row['ids']]
    if len(assigned) != 6292 or set(assigned) != set(review['entries']) or len(set(assigned)) != len(assigned):
        raise ValueError('Runtime publication exact6292 union is not unique')
    return {'native_owners':owners, 'console_packets':packets['console'], 'qualified_packets':packets['qualified'],
        'strict_seed_packets':packets['strict-seed'], 'program_ids':program}
