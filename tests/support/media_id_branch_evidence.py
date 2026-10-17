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
             if path.is_file() and path.suffix in {'.py', '.json', '.md'}
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
