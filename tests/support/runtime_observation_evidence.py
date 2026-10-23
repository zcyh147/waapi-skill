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
    if set(proof) != expected or proof['contract'] != 'waapi-skill.runtime-observation-proof/v1':
        raise ValueError('Closed runtime read observation proof required')
    for key in ('native_run', 'archive', 'capture', 'program_capture'):
        _portable_descriptor(proof[key], base)
    return proof


def _portable_descriptor(descriptor, base):
    path = Path(descriptor['artifact'])
    if (path.is_absolute() or '..' in path.parts
            or not (base / path).resolve().is_relative_to(base.resolve())):
        raise ValueError('Runtime descriptor escapes portable bundle')


def validate_runtime_evidence(record, binding, branch, category, base, root):
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
    completion.exact_observation_pointer(branch, {'observation_pointer': mapping['program_pointer']},
        '/native_call', 'result', {})
    completion.exact_observation_pointer(branch, {'observation_pointer': mapping['native_pointer']},
        mapping['native_result_parent'], 'agent_result', {})
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
        raise ValueError('Runtime proof omits original packaged source closure')
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
    sources = {k: v for k, v in original['source_context']['sources'].items() if k.startswith('skills/waapi-skill/')}
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
        'program_capture': descriptor('program-capture.json'), 'relevant_sources': sources}
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
        'reviewed_reason': 'All original packaged runtime/resource sources byte-identical; test/docs-only successors do not change observed read semantics. Original finalized PASS retained.',
        'sources': sources}
    equivalence_descriptor = write_json(output / 'native-equivalence.json', equivalence)
    attachment = {'contract': 'waapi-skill.runtime-observation-attachment/v1', 'branch_id': identity,
        'proof': proof_descriptor, 'evidence': native_descriptor, 'native_equivalence': equivalence_descriptor}
    attachment_descriptor = write_json(output / 'attachment.json', attachment)
    return output / write_json(output / 'index.json', {'contract': 'waapi-skill.branch-evidence-index/v1', 'base': '.',
        'entries': [{'id': plan['entry_id'], 'bindings': bindings_descriptor,
            'origin': {'bindings': bindings_descriptor, 'program': descriptor('program.json'),
                       'requirements': policy_descriptor, 'capture': descriptor('program-capture.json')}}],
        'runtime_observation_attachments': [attachment_descriptor]})['artifact']
