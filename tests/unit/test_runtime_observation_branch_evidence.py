"""One public runtime read reaches the existing exact branch audit consumer."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.unit.test_runtime_business_gateway import _RuntimeControlDraftClient, _env, gateway

FIXTURE = audit.ROOT / 'tests/fixtures/branch-evidence/product/runtime-read-r108'
URI = 'ak.wwise.core.profiler.getRTPCs'
ARGV = ['core-call', URI, '--profiler-position', '30837', '--max-results', '64']
IDENTITY = '2025.1|wwise-authoring|2025.1.7.9143|function|' + URI + '|/resultSchema/properties/return/items/properties/value'


def public_read(tmp_path):
    from tests.support.runtime_observation_evidence import program_source_context
    source_context = program_source_context()
    capture = json.loads((FIXTURE / 'original-capture.json').read_bytes())
    rows = capture['outcomes']['profiler-rtpcs-observation']['evidence']['agent_result']['return']
    class Client(_RuntimeControlDraftClient):
        def __init__(self):
            super().__init__(tmp_path)
            self.calls = []
        def call(self, uri, args=None, options=None):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            if uri == URI:
                return {'return': rows}
            result = super().call(uri, args, options)
            if uri == 'ak.wwise.core.getInfo':
                result['version'].update(minor=7, build=9143, displayName='v2025.1.7.9143')
            return result
    client = Client()
    code, payload = gateway.execute_gateway(['--state-dir', str(tmp_path / 'state'), *ARGV],
        env=_env(tmp_path), client_factory=lambda _: client)
    assert code == 0, json.dumps(payload)
    assert client.calls[-1] == (URI, {'time': 30837}, {})
    assert payload['agent_result']['return'][4] == {
        'id': '{63D15B0F-16E7-4B8A-B9CA-7BF10AD315B4}', 'name': 'RPM',
        'gameObjectId': 18446744073709551614, 'value': 1000.0}
    assert payload['agent_result']['complete'] is True
    return {'argv': ARGV, 'exit_code': code, 'payload': payload}, {
        'uri': URI, 'args': {'time': 30837}, 'options': {}, 'result': {'return': rows}}, source_context


def test_public_runtime_read_emits_only_after_actual_pytest_teardown(tmp_path, request):
    import os
    from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
    from tests.support.runtime_observation_evidence import write_program_receipt
    receipt, dispatch, source_context = public_read(tmp_path)
    destination = Path(os.environ.get('WAAPI_RUNTIME_OBSERVATION_CAPTURE', tmp_path / 'receipt.json'))
    register_exact_evidence_finalizer(request.node, lambda phases: write_program_receipt(
        destination, receipt, dispatch, nodeid=request.node.nodeid, phase_reports=phases, source_context=source_context))


@pytest.fixture(scope='module')
def inventory():
    return audit.build_inventory()


def test_original_runtime_read_completes_only_exact_value_leaf(tmp_path, inventory):
    from tests.support.runtime_observation_evidence import write_bundle, write_program_receipt
    receipt, dispatch, source_context = public_read(tmp_path)
    program = tmp_path / 'program.json'
    write_program_receipt(program, receipt, dispatch, nodeid='runtime-public-program',
        phase_reports={'setup': 'passed', 'call': 'passed', 'teardown': 'passed'}, source_context=source_context)
    index = write_bundle(tmp_path / 'bundle', program, FIXTURE, inventory=inventory)
    requirements = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, requirements)
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=requirements)
    selected = next(row for row in result['obligations'] if row['id'] == IDENTITY)
    assert selected['state'] == 'verified', json.dumps(selected)
    assert selected['evidence_results'] == {
        'program': {'outcome': 'passed', 'reason': None},
        'native': {'outcome': 'passed', 'reason': None}}
    assert all(row['state'] == 'unresolved' for row in result['obligations']
        if row['route'] == selected['route'] and row['id'] != IDENTITY)


def test_runtime_program_publisher_rejects_stale_source_before_final_pass(tmp_path):
    from tests.support.runtime_observation_evidence import write_program_receipt
    receipt, dispatch, source_context = public_read(tmp_path)
    with pytest.raises(ValueError, match='source'):
        write_program_receipt(tmp_path / 'stale.json', receipt, dispatch, nodeid='stale',
            phase_reports={'setup': 'passed', 'call': 'passed', 'teardown': 'passed'},
            source_context={'packaged': {}, 'capture': {}})


def test_runtime_publisher_preserves_blocked_native_without_emitting_pass(runtime_bundle, inventory, tmp_path):
    import shutil
    from tests.support.runtime_observation_evidence import write_bundle, write_json
    originals = tmp_path / 'blocked-originals'
    shutil.copytree(FIXTURE, originals)
    run = json.loads((originals / 'original-category.json').read_bytes())
    run['invocation']['outcome'] = 'BLOCKED'
    run['invocation']['node_outcomes'][0]['outcome'] = 'BLOCKED'
    write_json(originals / 'original-category.json', run)
    with pytest.raises(ValueError, match='no finalized PASS'):
        write_bundle(tmp_path / 'blocked-publication', runtime_bundle.parent / 'program-capture.json',
            originals, inventory=inventory)
    assert not (tmp_path / 'blocked-publication/native.json').exists()


def test_runtime_publisher_rejects_failed_program_capture(runtime_bundle, inventory, tmp_path):
    from tests.support.runtime_observation_evidence import write_bundle, write_json
    captured = json.loads((runtime_bundle.parent / 'program-capture.json').read_bytes())
    captured['phase_reports']['teardown'] = 'failed'
    write_json(tmp_path / 'failed-program.json', captured)
    with pytest.raises(ValueError, match='successful setup/call/teardown'):
        write_bundle(tmp_path / 'failed-publication', tmp_path / 'failed-program.json',
            FIXTURE, inventory=inventory)
    assert not (tmp_path / 'failed-publication/native.json').exists()


@pytest.fixture(scope='module')
def runtime_bundle(tmp_path_factory, inventory):
    from tests.support.runtime_observation_evidence import write_bundle, write_program_receipt
    root = tmp_path_factory.mktemp('runtime-observation-bundle')
    receipt, dispatch, source_context = public_read(root)
    program = root / 'program.json'
    write_program_receipt(program, receipt, dispatch, nodeid='runtime-public-program',
        phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=source_context)
    return write_bundle(root / 'bundle', program, FIXTURE, inventory=inventory)


def _case(index, inventory):
    requirements = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, requirements)
    def evaluate():
        result = completion.evaluate_coverage(audit.ROOT, inventory, document,
            digest=audit.digest, evidence_base=base, requirements_document=requirements)
        return next(row for row in result['obligations'] if row['id'] == IDENTITY)
    return document['bindings'][IDENTITY], base, evaluate


def test_runtime_native_archive_is_portable_with_original_locations_unavailable(runtime_bundle, inventory, monkeypatch):
    _, _, evaluate = _case(runtime_bundle, inventory)
    read = Path.read_bytes
    def read_portable(path):
        if str(path).startswith('/Users/xiye/Documents/Git/waapi-skills/.waapi-skill-state/'):
            raise AssertionError('Original native path must remain inert archive identity')
        return read(path)
    monkeypatch.setattr(Path, 'read_bytes', read_portable)
    assert evaluate()['state'] == 'verified'


@pytest.mark.parametrize('damage,reason', [
    ('row', 'differs from original node archive'),
    ('host', 'batch context or final proof differs'),
    ('build', 'batch context or final proof differs'),
    ('source', 'Runtime relevant source changed'),
    ('missing', 'Original runtime artifact missing'),
    ('blocked', 'no finalized PASS'),
    ('program-phases', 'Complete exact public program capture required'),
])
def test_final_runtime_audit_rejects_damaged_proof(runtime_bundle, inventory, tmp_path, damage, reason):
    import gzip
    import shutil
    from tests.support.runtime_observation_evidence import write_json, sha
    root = tmp_path / 'bundle'
    shutil.copytree(runtime_bundle.parent, root)
    binding, base, evaluate = _case(root / 'index.json', inventory)
    assert evaluate()['state'] == 'verified'
    proof = completion.read_sealed_artifact(binding['runtime_observation_attachment'], base)
    native_descriptor = binding['evidence']['native']
    native = completion.read_sealed_artifact(native_descriptor, base)
    if damage == 'row':
        capture = completion.read_sealed_artifact(proof['capture'], base)
        capture['outcomes']['profiler-rtpcs-observation']['evidence']['agent_result']['return'][4]['value'] = 2000.0
        proof['capture'] = write_json(base / 'original-capture.json', capture)
        native['observation_artifacts']['capture'] = proof['capture']
        binding['native_observations_sha256']['capture'] = proof['capture']['sha256']
    elif damage in {'host', 'build', 'blocked'}:
        run = completion.read_sealed_artifact(proof['native_run'], base)
        if damage == 'host':
            run['host']['is_command_line'] = True
        elif damage == 'build':
            run['host']['version']['build'] = 9999
        else:
            run['invocation']['outcome'] = 'BLOCKED'
            run['invocation']['node_outcomes'][0]['outcome'] = 'BLOCKED'
        rewritten = write_json(base / 'original-category.json', run)
        proof['native_run'].update(rewritten)
        native['native_runs'] = [proof['native_run']]
    elif damage == 'source':
        name = 'skills/waapi-skill/wwise_waapi/runtime_inspection_business.py'
        proof['relevant_sources'][name] = '0' * 64
    elif damage == 'missing':
        path = base / proof['archive']['artifact']
        archive = json.loads(gzip.decompress(path.read_bytes()))
        del archive['files'][next(key for key in archive['files'] if key.endswith('/profiler-capture.json'))]
        path.write_bytes(gzip.compress(json.dumps(archive).encode(), mtime=0))
        proof['archive']['sha256'] = sha(path.read_bytes())
    else:
        captured = completion.read_sealed_artifact(proof['program_capture'], base)
        captured['phase_reports']['teardown'] = 'failed'
        proof['program_capture'] = write_json(base / 'program-capture.json', captured)
    binding['runtime_observation_attachment'] = write_json(base / 'proof.json', proof)
    native_descriptor.update(write_json(base / 'native.json', native))
    selected = evaluate()
    assert selected['state'] == 'implemented_unverified'
    assert selected['evidence_results']['native']['outcome'] == 'missing'
    assert reason in selected['evidence_results']['native']['reason'], selected


@pytest.mark.parametrize('damage', ['duplicate-category', 'duplicate-selected', 'missing-node', 'extra-node'])
def test_runtime_batch_rejects_duplicate_categories_or_changed_node_set(damage):
    from tests.support.runtime_observation_evidence import archive_reader, sha
    run = json.loads((FIXTURE / 'original-category.json').read_bytes())
    read = archive_reader({'artifact': 'original-closure.json.gz',
        'sha256': sha((FIXTURE / 'original-closure.json.gz').read_bytes())}, FIXTURE)
    # This actual final writer emitted two outcomes owned by one selected node.
    assert len(run['categories']) == 2
    completion.validate_authoring_batch_finalization(run, FIXTURE, read_bytes=read)
    if damage == 'duplicate-category':
        run['categories'].append(deepcopy(run['categories'][0]))
    else:
        seal_path = run['categories'][0]['batch_finalization']['artifact']
        seal = json.loads(read(seal_path))
        if damage == 'duplicate-selected':
            seal['selected_test_nodeids'] *= 2
            run['invocation']['selected_test_nodeids'] *= 2
        elif damage == 'missing-node':
            seal['selected_test_nodeids'] = []
            run['invocation']['selected_test_nodeids'] = []
        else:
            run['categories'][0]['nodeid'] = 'unselected-extra-node'
        raw = json.dumps(seal).encode()
        for row in run['categories']:
            row['batch_finalization']['sha256'] = sha(raw)
        original_read = read
        read = lambda name: raw if name == seal_path else original_read(name)
    with pytest.raises(ValueError, match='batch context or final proof differs'):
        completion.validate_authoring_batch_finalization(run, FIXTURE, read_bytes=read)
