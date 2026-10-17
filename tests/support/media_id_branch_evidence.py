"""Exact moveSingle receipts through existing Gateway/finalizer/audit seams.

Native attachments refer to immutable original producer bytes. They never
launch a host or turn a changed-source historical PASS into current credit.
"""
from __future__ import annotations

from copy import deepcopy
import base64
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
from xml.etree import ElementTree as ET

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion


URI = 'ak.wwise.cli.moveMediaIdsToSingleFile'
PUBLIC_TEST = 'tests/unit/test_console_project_alternatives_gateway.py::test_cli_media_id_move_verifies_exact_source_mapping_and_storage_mode'
NATIVE_NODE = 'tests/destructive/test_gateway_workflow_transaction_matrix.py::test_cli_console_media_id_file_observation'
BUILDS = {'2021.1': '2021.1.14.8108', '2022.1': '2022.1.19.8584', '2023.1': '2023.1.19.8928',
          '2024.1': '2024.1.13.9056', '2025.1': '2025.1.7.9143'}
SOURCE_SYMBOLS = {
    'construction': 'skills/waapi-skill/wwise_waapi/cli_console_business.py#materialize_cli_console_business_request',
    'validation': 'skills/waapi-skill/wwise_waapi/builders/schema.py#validate_semantic_result',
    'verifier': 'skills/waapi-skill/wwise_waapi/operation_registry.py#verify_prepared_operation',
}


def _git(*args, binary=False):
    return subprocess.check_output(['git', *args], cwd=audit.ROOT, text=not binary)


def _write(path, value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode('utf-8')
    path.write_bytes(raw)
    return {'artifact': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest()}


def _seals(names):
    return {name: hashlib.sha256((audit.ROOT / name).read_bytes()).hexdigest() for name in sorted(set(names))}


def relevant_sources():
    names = [str(path.relative_to(audit.ROOT)) for path in (audit.ROOT / 'skills/waapi-skill').rglob('*')
             if path.is_file() and path.suffix in {'.py', '.json', '.md', '.gz'}
             and not {'.venv', '__pycache__', 'data'}.intersection(path.relative_to(audit.ROOT / 'skills/waapi-skill').parts)]
    # Include the original producer/lifecycle behavior, independently of this
    # new attachment's own frozen capture-source seal.
    names.extend(str(path.relative_to(audit.ROOT)) for folder in ('tests/destructive', 'tests/semantic/support')
                 for path in (audit.ROOT / folder).rglob('*.py') if '__pycache__' not in path.parts)
    return _seals(names)


def _capture_sources():
    return _seals(['tests/support/media_id_branch_evidence.py', 'tests/support/exact_evidence_finalization.py',
        'tests/unit/test_console_project_alternatives_gateway.py', 'tests/unit/test_branch_evidence_readers.py',
        'tests/conftest.py', 'tests/maintenance/branch_coverage_audit.py', 'tests/maintenance/branch_audit_completion.py'])


def _unchanged(context):
    return (context['git_candidate'] == _git('rev-parse', 'HEAD').strip()
        and context['relevant_sources'] == relevant_sources() and context['capture_sources'] == _capture_sources())


def prepare_media_id_capture(root: Path, *, versions=('2025.1',)) -> Path:
    """Freeze a clean product candidate before selecting existing pytest nodes."""
    if _git('status', '--porcelain').strip():
        raise ValueError('Exact media-ID product capture requires a clean committed candidate')
    if not versions or len(set(versions)) != len(versions) or set(versions) - set(BUILDS):
        raise ValueError('Select exact supported media-ID versions')
    inventory = audit.build_inventory()
    branches = {row['id']: row for row in inventory['native_coverage']['obligations']}
    selected = {}
    for version in versions:
        node = f'{PUBLIC_TEST}[{version}-AudioFileSource-None]'
        branch = branches[f'{version}|wwise-console|{BUILDS[version]}|function|{URI}|/resultSchema']
        if branch['owner_issue'] != 184:
            raise ValueError('Exact moveSingle ownership changed')
        selected[node] = {'version': version, 'branch': branch,
            'public': next(row for row in inventory['routes'] if row['id'] == f'{version}|function|{URI}')}
    root.mkdir(parents=True, exist_ok=False)
    context = {'contract': 'waapi-skill.media-id-program-capture-context/v1', 'root': str(root.resolve()),
        'candidate_sha256': inventory['native_coverage']['candidate_sha256'], 'git_candidate': _git('rev-parse', 'HEAD').strip(),
        'relevant_sources': relevant_sources(), 'capture_sources': _capture_sources(), 'nodes': selected}
    path = root / 'context.json'
    _write(path, context)
    return path


def load_media_id_capture(path: Path, nodeid: str):
    context = json.loads(path.read_bytes())
    if (context.get('contract') != 'waapi-skill.media-id-program-capture-context/v1'
        or nodeid not in context['nodes'] or not _unchanged(context)):
        raise ValueError('Exact media-ID capture node or frozen sources changed')
    return {**context, **context['nodes'][nodeid], 'nodeid': nodeid}


def public_media_id_observation(*, gateway, public_invocations, native_observations):
    """Retain actual public calls and actual injected native return values."""
    if (len(native_observations) != 1 or native_observations[0].get('uri') != URI
        or native_observations[0].get('result') != {'result': 2}
        or gateway.get('exit_code') != 0 or gateway['payload'].get('verified') is not True
        or gateway['payload'].get('agent_result', {}).get('result') != {'result': 2}):
        raise ValueError('Exact moveSingle capture requires its actual dispatch and verified public result')
    return {'gateway': deepcopy(gateway), 'public_invocations': deepcopy(public_invocations),
        'observations': {'dispatch': deepcopy(native_observations[0])}, 'target_dispatch_count': 1}


def finish_media_id_capture(context, phase_reports, observed):
    """Publish after the shared pytest finalizer receives all three phases."""
    target = Path(context['root']) / context['version']
    if target.exists():
        raise ValueError('Original media-ID evidence output already exists')
    unchanged = _unchanged(context)
    passed = unchanged and all(phase_reports.get(phase) == 'passed' for phase in ('setup', 'call', 'teardown'))
    outcome = 'PASS' if passed else 'FAIL'
    branch, public, nodeid = context['branch'], context['public'], context['nodeid']
    record = {'candidate_sha256': context['candidate_sha256'], 'git_candidate': context['git_candidate'],
        'scope_kind': 'product', 'evidence_kind': 'injected_client_program',
        'relevant_sources': context['relevant_sources'], 'capture_sources': context['capture_sources'],
        'invocation': {'phase': 'final', 'outcome': outcome, 'node_outcomes': [{'nodeid': nodeid, 'outcome': outcome}]},
        **deepcopy(observed), 'branch_assertions': {branch['id']: {'native_shape_sha256': branch['shape_sha256'],
            'native_route': branch['route'], 'checks': [
                {'pointer': '/observations/dispatch/result', 'equals': {'result': 2}},
                {'pointer': '/target_dispatch_count', 'equals': 1},
                {'pointer': '/gateway/payload/verified', 'equals': True},
                {'pointer': '/gateway/payload/agent_result', 'equals': observed.get('gateway', {}).get('payload', {}).get('agent_result')}]}}}
    binding = {'branch_id': branch['id'], 'native_shape_sha256': branch['shape_sha256'],
        'public_route': public['id'], 'public_route_sha256': audit.digest(public),
        'input': {'gateway_argv': observed.get('gateway', {}).get('argv', []),
            'selector': 'closed_project_file_Draft_immutable_Preview_confirm_execute_once_exact_saved_mapping_verify'},
        **{key: {'source': source, 'selector': '/resultSchema'} for key, source in SOURCE_SYMBOLS.items()},
        'dispatch_pointer': '/observations/dispatch', 'observation_pointer': '/observations/dispatch/result',
        'gateway_observation_pointer': '/gateway/payload/agent_result', 'native_hosts': ['wwise-console'],
        'relevant_sources': list(context['relevant_sources']), 'evidence': {}}
    pending = Path(tempfile.mkdtemp(prefix=f'.{context["version"]}-program-pending-', dir=context['root']))
    descriptor = {**_write(pending / 'program.json', record), 'nodeid': nodeid}
    if passed:
        result = completion.evidence_result(descriptor, branch, context['candidate_sha256'], 'program', 'product',
            pending, binding, source_root=audit.ROOT)
        if result != ('passed', None):
            raise ValueError(f'Exact program reader rejected the original capture: {result}')
    binding['evidence']['program'] = {**descriptor, 'artifact': str((target / 'program.json').resolve())}
    _write(pending / 'bindings.json', {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': {branch['id']: binding}})
    _write(pending / 'requirements.json', {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {
        branch['id']: {'native_shape_sha256': branch['shape_sha256'], 'categories': ['program', 'native'],
            'reason': 'Exact Console moveSingle result shape plus independent saved-media migration effects; injected public Gateway proof alone does not certify native effects. This fixed file-based slice needs no metadata/Fresh requirement.'}}})
    _write(pending / 'capture.json', {'contract': 'waapi-skill.media-id-program-capture/v1', 'outcome': outcome,
        'candidate_sha256': context['candidate_sha256'], 'git_candidate': context['git_candidate'],
        'branch_id': branch['id'], 'phase_reports': phase_reports, 'source_unchanged': unchanged,
        'scope_kind': 'product', 'native_credit': False})
    pending.rename(target)


def _original_source_context(target, git_candidate, inventory, selected):
    """Hash fixed Git bytes with the existing candidate function; import none.

    source_index identifies the audit inputs hashed as text; other original
    inventory inputs are JSON values. The native catalogs must also match.
    """
    target.mkdir(parents=True, exist_ok=False)
    required = set(inventory['sources']) | set(selected) | {
        'tests/maintenance/branch_audit_completion.py', 'tests/maintenance/branch_coverage_audit.py',
        'docs/branch-coverage-ownership.json', 'docs/branch-coverage-condition-sources.json',
        'docs/branch-coverage-requirements.json'}
    prefixes = ('skills/waapi-skill', 'tests/destructive', 'tests/semantic/support')
    paths = [*prefixes, *(name for name in sorted(required) if not any(name.startswith(prefix + '/') for prefix in prefixes))]
    raw = _git('archive', '--format=tar', git_candidate, '--', *paths, binary=True)
    if len(raw) > 256 * 1024 * 1024:
        raise ValueError('Original source archive exceeds its bounded attachment capacity')
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for entry in archive:
            if entry.isdir():
                continue
            path = (target / entry.name).resolve()
            if not entry.isfile() or not path.is_relative_to(target.resolve()):
                raise ValueError('Original source archive contains an unsupported entry')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.extractfile(entry).read())
    text_sources = {row['path'] for row in inventory['source_index'].values()}
    sources = {name: audit.digest((target / name).read_text(encoding='utf-8')) if name in text_sources
        else audit.digest(json.loads((target / name).read_bytes())) for name in inventory['sources']}
    from wwise_waapi.native_catalog import load_native_catalog
    catalogs = {identity: load_native_catalog(identity.split('|')[0], identity.split('|')[1],
        root=target / 'skills/waapi-skill/resources/native-catalog')['content_sha256']
        for identity in inventory['native_coverage']['catalogs']}
    if catalogs != inventory['native_coverage']['catalogs']:
        raise ValueError('Historical native catalogs changed; exact branch/source reconciliation required')
    candidate = completion.candidate_identity(target, {'sources': sources}, catalogs, digest=audit.digest)
    old_names = [str(path.relative_to(target)) for path in (target / 'skills/waapi-skill').rglob('*')
        if path.is_file() and path.suffix in {'.py', '.json', '.md', '.gz'}
        and not {'.venv', '__pycache__', 'data'}.intersection(path.relative_to(target / 'skills/waapi-skill').parts)]
    old_names.extend(str(path.relative_to(target)) for folder in ('tests/destructive', 'tests/semantic/support')
        for path in (target / folder).rglob('*.py') if '__pycache__' not in path.parts)
    seals = {name: hashlib.sha256((target / name).read_bytes()).hexdigest() for name in sorted(old_names)}
    _write(target / 'media-id-source-context.json', {'git_candidate': git_candidate, 'candidate_sha256': candidate,
        'relevant_sources': seals, 'native_catalogs': catalogs, 'original_bytes_only': True})
    return candidate, seals


def _file_bytes(observation):
    raw = base64.b64decode(observation['content_base64'], validate=True)
    proof = observation['file_proof']
    if len(raw) > 64 * 1024 * 1024 or len(raw) != proof['size'] or hashlib.sha256(raw).hexdigest() != proof['sha256']:
        raise ValueError('Original native file bytes differ from their preserved file proof')
    return raw


def attach_original_media_id_native(output: Path, program: Path, *, category, dispatch, verification, inventory):
    """Attach reviewed original v3 evidence, without relabeling its source.

    Both original-context and successor descriptors are emitted. Existing
    strict equivalence readers decide whether current source can reuse it.
    """
    if output.exists():
        raise ValueError('Native attachment output exists; preserve original attempts')
    bindings = json.loads((program / 'bindings.json').read_bytes())
    requirements = json.loads((program / 'requirements.json').read_bytes())
    if len(bindings['bindings']) != 1:
        raise ValueError('Select one exact moveSingle program branch')
    branch_id, binding = next(iter(bindings['bindings'].items()))
    binding = deepcopy(binding)
    branch = next(row for row in inventory['native_coverage']['obligations'] if row['id'] == branch_id)
    version, host, build, kind, uri = branch['route'].split('|')
    if host != 'wwise-console' or kind != 'function' or uri != URI or branch['pointer'] != '/resultSchema':
        raise ValueError('Native attachment must name the exact Console moveSingle result branch')
    context = completion.read_category_run(category, output.parent)
    original = context['record']
    if (context['host'] != 'wwise-console' or context['version'] != version or context['build'] != build
        or category['nodeid'] != NATIVE_NODE or original['invocation']['selected_test_nodeids'] != [NATIVE_NODE]
        or original['invocation']['node_outcomes'] != [{'nodeid': NATIVE_NODE, 'outcome': 'PASS'}]):
        raise ValueError('Original native exact node/host/version/build mismatch')
    native_call = completion.read_sealed_artifact(dispatch, output.parent)
    if (native_call.get('api') != URI or native_call.get('ok') is not True or native_call.get('dry_run') is not False
        or native_call.get('result') != {'result': 2} or native_call.get('version') != version):
        raise ValueError('Original native moveSingle dispatcher/result mismatch')
    rows = [row for row in original['categories'] if row.get('category') == 'cli-media-id-file-format-observation']
    if len(rows) != 1 or rows[0].get('status') != 'PASS' or rows[0].get('baseline_setup') != 'public_gateway_project_save_before_capture':
        raise ValueError('Original independent saved-media oracle missing')
    oracle = rows[0]
    transactions = [row for row in original['transactions'] if row['transaction_id'] == oracle['transaction_id']]
    event = completion.read_sealed_artifact(verification, output.parent)
    verified = event.get('details', {}).get('verification', {})
    if (len(transactions) != 1 or transactions[0]['state'] != 'verified'
        or event.get('transaction_id') != oracle['transaction_id'] or event.get('event_type') != 'verification_recorded'
        or event.get('to_state') != 'verified' or event.get('artifact_hash') != transactions[0]['artifact_hash']
        or verified.get('status') != 'verified' or verified.get('ok') is not True or verified.get('business_state_verified') is not True
        or verified.get('verification_strength') != 'independent_console_project_file_artifact'
        or not verified.get('assertions') or any(row.get('passed') is not True for row in verified['assertions'])):
        raise ValueError('Original final strong media transaction verification missing')
    mapping = ET.fromstring(_file_bytes(oracle['mapping_file']))
    actual = [[owner.attrib['ID'].upper(), media.attrib['ID']]
        for owner in mapping.findall('./MediaIDInfo/MediaIDs/Language/File/WObject') for media in owner.findall('MediaID')]
    expected = oracle['baseline_media_pairs']
    if not 1 <= len(expected) <= 100000 or Counter(map(tuple, actual)) != Counter(map(tuple, expected)):
        raise ValueError('Original central mapping differs from independent saved-media baseline')
    _file_bytes(oracle['source_work_unit'])
    if ET.fromstring(_file_bytes(oracle['source_work_unit_after'])).findall('.//MediaIDList/MediaID'):
        raise ValueError('Original observed Work Unit still owns migrated media IDs')
    media = [row for row in verified['readbacks'] if row.get('kind') == 'cli-media-id-artifacts']
    if (len(media) != 1 or media[0]['work_unit_media_id_count_before'] != len(expected)
        or media[0]['work_unit_media_id_count_after'] != 0 or media[0].get('unresolved') != []
        or media[0]['mapping_file']['media_count'] != len(expected)):
        raise ValueError('Original transaction media-count/oracle preservation proof differs')
    output.parent.mkdir(parents=True, exist_ok=True)
    pending = Path(tempfile.mkdtemp(prefix=f'.{output.name}-pending-', dir=output.parent))
    original_root = pending / 'original-source'
    old_candidate, old_sources = _original_source_context(original_root, context['candidate'], inventory, binding['relevant_sources'])
    observations = {'dispatch': dispatch, 'category': category, 'verification': verification}
    binding['native_observations_sha256'] = {key: value['sha256'] for key, value in observations.items()}
    checks = [{'pointer': '/observations/dispatch/result', 'equals': {'result': 2}},
        {'pointer': '/observations/dispatch/api', 'equals': URI}, {'pointer': '/observations/dispatch/ok', 'equals': True},
        {'pointer': '/observations/verification/details/verification/business_state_verified', 'equals': True},
        {'pointer': '/observations/verification/details/verification/status', 'equals': 'verified'},
        {'pointer': f'/observations/category/categories/{original["categories"].index(oracle)}/baseline_media_pairs', 'equals': expected},
        {'pointer': f'/observations/category/categories/{original["categories"].index(oracle)}/mapping_file/file_proof/sha256',
            'equals': oracle['mapping_file']['file_proof']['sha256']}]
    record = {'candidate_sha256': old_candidate, 'git_candidate': context['candidate'], 'scope_kind': 'product',
        'evidence_kind': 'native_execution', 'relevant_sources': old_sources, 'invocation': original['invocation'],
        'native_runs': [{**category, 'observation_sha256': sorted(set(value['sha256'] for value in observations.values()))}],
        'observation_artifacts': observations, 'branch_assertions': {branch_id: {
            'native_shape_sha256': branch['shape_sha256'], 'native_route': branch['route'], 'checks': checks}}}
    native_descriptor = {**_write(pending / 'native.json', record), 'nodeid': NATIVE_NODE,
        'artifact': str((output / 'native.json').resolve())}
    binding['evidence']['native'] = native_descriptor
    def proof(name, from_candidate, to_candidate, evidence_sha256, semantic_binding):
        return {**_write(pending / name, {'contract': 'waapi-skill.branch-evidence-equivalence/v1',
            'from_candidate': from_candidate, 'to_candidate': to_candidate, 'branch_id': branch_id,
            'native_shape_sha256': branch['shape_sha256'], 'native_route': branch['route'],
            'evidence_sha256': evidence_sha256, 'binding_semantics_sha256': audit.digest(completion.binding_semantics(semantic_binding)), 'sources': old_sources,
            'reviewed_reason': 'Exact original Console result and strong saved-media oracle attachment. Reuse requires every selected whole-file source to remain byte-identical; original verdict is never changed.'}),
            'artifact': str((output / name).resolve())}
    current_candidate = inventory['native_coverage']['candidate_sha256']
    binding['equivalence'] = proof('evidence-equivalence.json', old_candidate, current_candidate, native_descriptor['sha256'], binding)
    binding['native_equivalence'] = proof('native-equivalence.json', context['candidate'], current_candidate, category['sha256'], binding)
    original_binding = deepcopy(binding)
    original_binding.pop('equivalence')
    original_binding['relevant_sources'] = list(old_sources)
    original_binding['native_equivalence'] = proof('original-native-equivalence.json', context['candidate'], old_candidate, category['sha256'], original_binding)
    bindings = {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': {branch_id: binding}}
    _write(pending / 'bindings.json', bindings)
    _write(pending / 'requirements.json', requirements)
    _write(pending / 'original-bindings.json', {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': {branch_id: original_binding}})
    report = {'bindings': bindings, 'requirements': requirements, 'original_binding': original_binding,
        'original_candidate_sha256': old_candidate, 'original_git_candidate': context['candidate'],
        'original_source_root': str((output / 'original-source').resolve()), 'native_mapping_pair_count': len(expected),
        'source_differences': [name for name in sorted(set(old_sources) | set(binding['relevant_sources']))
            if name not in old_sources or not (audit.ROOT / name).is_file()
            or hashlib.sha256((audit.ROOT / name).read_bytes()).hexdigest() != old_sources[name]]}
    _write(pending / 'attachment.json', report)
    # Re-read original bytes after all work. Any changed original stays unaccepted.
    for descriptor in observations.values():
        completion.read_sealed_artifact(descriptor, output.parent)
    pending.rename(output)
    return report
