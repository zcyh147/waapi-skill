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


def program_source_context(root=audit.ROOT):
    import subprocess
    names = subprocess.check_output(['git', 'ls-files', '--', 'skills/waapi-skill'],
        cwd=root, text=True).splitlines()
    dependencies = ['tests/support/runtime_observation_evidence.py',
        'tests/unit/test_runtime_observation_branch_evidence.py',
        'tests/unit/test_rtpc_field_branch_evidence.py',
        'tests/unit/test_runtime_business_gateway.py', 'tests/support/gateway_config.py',
        'tests/support/exact_evidence_finalization.py', 'tests/conftest.py',
        'tests/maintenance/branch_coverage_audit.py', 'tests/maintenance/branch_audit_completion.py']
    return {group: {name: sha((root / name).read_bytes()) for name in sorted(paths)}
            for group, paths in (('packaged', names), ('capture', dependencies))}


def write_program_receipt(path, gateway, native_call, *, nodeid, phase_reports, source_context):
    if phase_reports != {'setup': 'passed', 'call': 'passed', 'teardown': 'passed'}:
        raise ValueError('Runtime program proof requires successful setup/call/teardown')
    if gateway['exit_code'] != 0 or gateway['payload'].get('ok') is not True:
        raise ValueError('Runtime program proof requires successful public Gateway read')
    if source_context != program_source_context():
        raise ValueError('Runtime program source changed during public read')
    return write_json(path, {'contract': 'waapi-skill.runtime-read-program/v1',
        'phase_reports': phase_reports, 'nodeid': nodeid,
        'source_context': source_context, 'source_unchanged': True,
        'gateway': gateway, 'native_call': native_call})


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


def validate_rtpc_program(record, binding, branch, root):
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
    native_rows = record['native_call']['result']['return']
    public_rows = record['gateway']['payload']['agent_result']['return']
    # These complete RTPC reads copy the entire array without transformation.
    # Canonical JSON also distinguishes int/float/bool values that Python ==
    # would otherwise conflate when comparing nested containers.
    if (payload['agent_result'].get('complete') is not True
            or not isinstance(native_rows, list) or not isinstance(public_rows, list)
            or audit.digest(native_rows) != audit.digest(public_rows)):
        raise ValueError('Program must preserve complete native/public RTPC return arrays')
    if branch['pointer'].startswith('/resultSchema/'):
        pointer = binding.get('program_observation_pointer', binding['observation_pointer'])
        parent = '/native_call/result/return'
        if (pointer != parent and not pointer.startswith(parent + '/')
                or binding['gateway_observation_pointer'] != pointer.replace(
                    '/native_call/result', '/gateway/payload/agent_result', 1)):
            raise ValueError('RTPC result needs the corresponding exact public field occurrence')


def validate_runtime_evidence(record, binding, branch, category, base, root, reference_edges=None):
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
        binding.update(runtime_observation_attachment=attachment['proof'],
            program_observation_pointer=proof['mapping']['program_pointer'],
            observation_pointer=proof['mapping']['native_pointer'],
            native_observations_sha256={'capture': proof['capture']['sha256']},
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
RTPC_SOURCE = 'skills/waapi-skill/wwise_waapi/runtime_inspection_business.py#'
RTPC_NATIVE_PARENT = '/observations/capture/outcomes/profiler-rtpcs-observation/evidence'
RTPC_ORIGINAL_CANDIDATE = '503688449ba9f9db964a5fb7116ac6be2fb07198'
RTPC_GUARD_FILE = RTPC_SOURCE.split('#')[0]
RTPC_GUARD_CHANGE = {
    'before': '62e4ed3eca63a62637e7b8e1ab4c5c55c18ceffb49d91d4e318cecec44ce116c',
    'after': 'a34a6b5f4b54b6f9ab80e3f3a07c6ff7bb2d5dbf34a5757bcf4520f8301a5699'}
RTPC_REVIEWED_SOURCE_CHANGES = {
    RTPC_GUARD_FILE: RTPC_GUARD_CHANGE,
    'skills/waapi-skill/scripts/gateway.py': {
        'before': '9ea8d1c0c79c9323c8ee0e48b8cb9444c54c8d73f9f7330ed827563f31f42f03',
        'after': 'fcaaa2341a14690741e6c3fa4a50a252ac229ab2403173051847b4c4b11a1f8e'},
    'skills/waapi-skill/wwise_waapi/builders/schema.py': {
        'before': '4a1ac5146edc65eb8e58defd689051f79a198bafb2d5d2134d912bd9a862fd6d',
        'after': 'cd11309c557b68ea7bcb7d82c2bcbc1a448d08f8e283fab50a0424555fc4f8f2'}}
RTPC_REVIEWED_SOURCE_SYMBOLS = {
    RTPC_GUARD_FILE: ['module import: builders.query.STRUCTURED_GUID_PATTERN',
        '_validate_rtpc_rows', 'normalize_runtime_inspection_result'],
    'skills/waapi-skill/scripts/gateway.py': ['module import: builders.schema.validate_resolved_semantic_result',
        'resolve_profiler_voice_path', 'dispatch_profiler_voice_contributions_request',
        'dispatch_runtime_inspection_business_read'],
    'skills/waapi-skill/wwise_waapi/builders/schema.py': ['validate_resolved_semantic_result',
        '_validate_resolved_sections', '_runtime_result_reference_schema']}
RTPC_REVIEWED_SOURCE_REASON = (
    'Exact reviewed RTPC guard and closed non-RTPC result-validation source delta; '
    'RTPC conservative validator/request/normalizer behavior retained and complete original '
    'arrays unchanged through current public Gateway; original finalized PASS retained')
RTPC_ORIGINALS = {
    '2022.1': ('2022.1.19.8584', 'e9d4b86aaccaccb9b1603d37ba5bc7255034c09d2c05b7685beb254e6642adfd', 17, 23637),
    '2025.1': ('2025.1.7.9143', 'e7ef187ef0ed855819cfa007375f3ca8c1d4cfc1e3697f8c5b9e870c1441690c', 5, 30837)}


def validate_rtpc_source_review(descriptor, historical_sources, branch, root, base):
    """Accept only the pinned reviewed three-file delta for original RTPC reads."""
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
    else:
        raise ValueError('RTPC mappings support only data or deterministic construction')
    return route, selected


def write_field_bundle(output, program_path, originals, *, inventory, version, host, mode, name_prefix="", guard_replay=None):
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
    route, mappings = rtpc_field_mappings(inventory, version=version, host=host, mode=mode)
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
        identity, pointer = branch['id'], mapping['program_pointer']
        value = completion.pointer_value(captured, pointer)
        public_pointer = (pointer.replace('/native_call/result', '/gateway/payload/agent_result')
            if mode == 'data' else '/gateway/payload/agent_result/profiler_position')
        check = ({'pointer': pointer, 'cardinality': 'multiple'}
            if branch['kind'] == 'collection_cardinality' else {'pointer': pointer, 'equals': value})
        checks = [check, {'pointer': public_pointer, 'equals': completion.pointer_value(captured, public_pointer)},
            {'pointer': '/gateway/payload/agent_result/complete', 'equals': True}]
        assertion = {'native_shape_sha256': branch['shape_sha256'], 'native_route': branch['route']}
        program['branch_assertions'][identity] = {**assertion, 'checks': checks}
        policy['branches'][identity] = {'native_shape_sha256': branch['shape_sha256'],
            'categories': ['program', 'native'] if mode == 'data' else ['program'],
            'reason': ('Exact observed RTPC data/reference/presence/cardinality; independent native fact required'
                if mode == 'data' else 'Deterministic closed numeric time/reference/minimum/empty-options construction; no native data/effect inference')}
        binding = {'branch_id': identity, 'native_shape_sha256': branch['shape_sha256'],
            'runtime_read_program': True,
            'public_route': public['id'], 'public_route_sha256': audit.digest(public),
            'input': {'gateway_argv': argv, 'selector': pointer}, 'dispatch_pointer': '/native_call',
            'observation_pointer': pointer, 'gateway_observation_pointer': public_pointer,
            'reference_chain': mapping['reference_chain'],
            'relevant_sources': sorted(sources), 'evidence': {},
            **{key: {'source': RTPC_SOURCE + symbol, 'selector': branch['pointer']} for key, symbol in (
                ('construction', 'materialize_runtime_inspection_business_request'),
                ('validation', 'normalize_runtime_inspection_result' if mode == 'data' else (
                    'materialize_runtime_inspection_business_request' if branch['pointer'].startswith('/optionsSchema/') else '_profiler_time')),
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


def write_field_stage(output, captures, originals, *, inventory, guard_replays=None):
    """Combine five-version read flows in the ordinary portable index format."""
    versions = ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1')
    expected = {(version, host, mode) for version in versions
        for host in ('wwise-console', 'wwise-authoring') for mode in ('construction', 'data')}
    if set(captures) != expected or set(originals) - {'2022.1', '2025.1'}:
        raise ValueError('RTPC stage requires all exact five-version public flows and only qualified originals')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    policy = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {}}
    index = {'contract': 'waapi-skill.branch-evidence-index/v1', 'base': '.', 'entries': []}
    attachments = []
    for version, host, mode in sorted(expected):
        original = originals.get(version) if host == 'wwise-authoring' and mode == 'data' else None
        flow = write_field_bundle(output, captures[version, host, mode], original,
            inventory=inventory, version=version, host=host, mode=mode,
            name_prefix=f'{version}-{host}-{mode}-', guard_replay=(guard_replays or {}).get(version))
        document = json.loads(flow.read_bytes())
        index['entries'].extend(document['entries'])
        attachments.extend(document.get('runtime_observation_attachments', []))
        flow_policy = completion.read_sealed_artifact(document['entries'][0]['origin']['requirements'], output)
        if policy['branches'].keys() & flow_policy['branches'].keys():
            raise ValueError('RTPC stage repeats an exact native branch')
        policy['branches'].update(flow_policy['branches'])
    if attachments:
        index['runtime_observation_attachments'] = attachments
    write_json(output / 'requirements.json', policy)
    write_json(output / 'index.json', index)
    return output / 'index.json'
