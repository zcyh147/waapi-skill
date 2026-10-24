"""Separately assess four exact retained read facts without repairing BLOCKED roots."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support.runtime_observation_evidence import write_json, write_program_receipt
from tests.unit.test_rtpc_field_branch_evidence import public_rtpc_read

RTPC_CATEGORY = 'profiler-rtpcs-observation'
NODE = 'd6e9da42fb2f751cbc535eeb'


def rtpc_program(tmp_path, version):
    from tests.support.qualified_runtime_read_evidence import retained_read, fixture_path
    original = fixture_path(version)
    capture = retained_read(version, RTPC_CATEGORY)['capture']
    rows = capture['outcomes'][RTPC_CATEGORY]['evidence']['agent_result']['return']
    receipt, native, context = public_rtpc_read(tmp_path / 'public', version=version,
        position=str(capture['capture_position']['position_ms']), rows=rows)
    assert len(native['result']['return']) == 15
    assert receipt['payload']['agent_result']['return'][7] == {
        'id': '{63D15B0F-16E7-4B8A-B9CA-7BF10AD315B4}', 'name': 'RPM',
        'gameObjectId': 18446744073709551614, 'value': 1000.0}
    path = tmp_path / 'program-capture.json'
    write_program_receipt(path, receipt, native, nodeid=f'qualified-{version}-rtpc',
        phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context)
    return path, original


@pytest.fixture(scope='module')
def inventory():
    return audit.build_inventory()


def test_one_qualified_read_reaches_final_consumer_without_regrading_lifecycle(tmp_path, inventory):
    capture, original = rtpc_program(tmp_path, '2023.1')
    from tests.support.qualified_runtime_read_evidence import write_qualified_read_bundle
    route = next(row for row in inventory['native_coverage']['routes']
        if row['version'] == '2023.1' and row['host'] == 'wwise-authoring' and row['uri'].endswith('getRTPCs'))
    identity = route['id'] + '|/resultSchema/properties/return/items/properties/value'
    index = write_qualified_read_bundle(tmp_path / 'bundle', capture, original,
        inventory=inventory, version='2023.1', category=RTPC_CATEGORY, selected={identity})
    requirements = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, requirements)
    def observed():
        result = completion.evaluate_coverage(audit.ROOT, inventory, document,
            digest=audit.digest, evidence_base=base, requirements_document=requirements)
        return next(row for row in result['obligations'] if row['id'] == identity)
    row = observed()
    assert row['state'] == 'verified', json.dumps(row)
    assert row['requirements'] == ['native', 'program']
    binding = document['bindings'][identity]
    assessment = completion.read_sealed_artifact(binding['qualified_runtime_read_attachment'], base)
    assert assessment['original_workflow_outcome'] == 'BLOCKED'
    assert assessment['original_finalization'] == 'BLOCKED'
    assert assessment['successful_finalization'] is False
    assert assessment['qualified_read_fact'] == 'PASS'
    assert len(assessment['lifecycle_obligations']) == 2
    assert all(item['issue'] == 186 and item['status'] == 'BLOCKED' for item in assessment['lifecycle_obligations'])
    assessment['lifecycle_obligations'][0]['status'] = 'PASS'
    replacement = write_json(base / 'forged-assessment.json', assessment)
    binding['qualified_runtime_read_attachment'] = replacement
    native = completion.read_sealed_artifact(binding['evidence']['native'], base)
    native['assessment_sha256'] = replacement['sha256']
    binding['evidence']['native'].update(write_json(base / 'forged-native.json', native))
    damaged = observed()
    assert damaged['evidence_results']['native']['outcome'] == 'missing', json.dumps(damaged)
    assert 'lifecycle obligations remain BLOCKED' in damaged['evidence_results']['native']['reason']


@pytest.mark.parametrize('version', ('2023.1', '2024.1'))
@pytest.mark.parametrize('category', (RTPC_CATEGORY, 'profiler-contributions-bus-observation'))
def test_all_independently_observed_result_selectors_reach_final_consumer(tmp_path, inventory, version, category):
    from tests.support.qualified_runtime_read_evidence import write_qualified_read_bundle
    if category == RTPC_CATEGORY:
        capture, original = rtpc_program(tmp_path, version)
    else:
        from tests.support.qualified_runtime_read_evidence import retained_contribution_inputs
        from tests.unit.test_contribution_branch_evidence import public_contribution_flow
        inputs = retained_contribution_inputs(version)
        receipt, native, context, trace, calls, original = public_contribution_flow(
            tmp_path / 'public', version, retained=inputs)
        assert receipt['payload']['agent_result']['volume'] == -9.0
        assert len(receipt['payload']['agent_result']['objects']) == 7
        capture = tmp_path / 'program-capture.json'
        write_program_receipt(capture, receipt, native, nodeid=f'qualified-{version}-contribution',
            phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context,
            native_reads=trace, public_calls=calls)
    index = write_qualified_read_bundle(tmp_path / 'bundle', capture, original,
        inventory=inventory, version=version, category=category)
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, policy)
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    selected = [row for row in result['obligations'] if row['id'] in document['bindings']]
    assert len(selected) == len(document['bindings'])
    assert all(row['requirements'] == ['native', 'program'] for row in selected)
    assert {row['state'] for row in selected} == {'verified'}, json.dumps(selected)
    print(f'R114_NATIVE_COUNT {version} {category} {len(selected)}')


@pytest.fixture(scope='module')
def one_value_bundle(tmp_path_factory, inventory):
    from tests.support.qualified_runtime_read_evidence import write_qualified_read_bundle
    root = tmp_path_factory.mktemp('qualified-controls')
    capture, original = rtpc_program(root, '2023.1')
    route = next(row for row in inventory['native_coverage']['routes']
        if row['version'] == '2023.1' and row['host'] == 'wwise-authoring' and row['uri'].endswith('getRTPCs'))
    identity = route['id'] + '|/resultSchema/properties/return/items/properties/value'
    return write_qualified_read_bundle(root / 'bundle', capture, original, inventory=inventory,
        version='2023.1', category=RTPC_CATEGORY, selected={identity})


@pytest.mark.parametrize('damage,reason', [
    ('native-value', 'exact original branch occurrence'),
    ('wrong-host', 'exact current public read capture'),
    ('wrong-time', 'Original RTPC request/time differs'),
    ('stale-source', 'exact current public read capture'),
    ('failed-phase', 'exact current public read capture'),
    ('other-category', 'exact route/result scope differs'),
    ('different-failure', 'Exact retained original closure differs'),
    ('missing-artifact', 'Exact retained original closure differs'),
])
def test_qualified_final_reader_rejects_resealed_causal_corruption(
        tmp_path, inventory, one_value_bundle, damage, reason):
    import base64
    import gzip
    import shutil
    from tests.support.runtime_observation_evidence import sha
    base = tmp_path / 'bundle'
    shutil.copytree(one_value_bundle.parent, base)
    policy = json.loads((base / 'requirements.json').read_bytes())
    document, _, _ = audit.portable_binding_inputs(base / 'index.json', policy)
    identity, binding = next(iter(document['bindings'].items()))
    assessment = completion.read_sealed_artifact(binding['qualified_runtime_read_attachment'], base)
    native = completion.read_sealed_artifact(binding['evidence']['native'], base)
    if damage == 'native-value':
        native['observed'] = 1001.0
    elif damage == 'other-category':
        assessment['category'] = 'profiler-capture-stop'
    elif damage in {'different-failure', 'missing-artifact'}:
        path = base / assessment['archive']['artifact']
        archive = json.loads(gzip.decompress(path.read_bytes()))
        if damage == 'different-failure':
            name = next(key for key in archive['files'] if key.endswith('/authoring-batch-finalization-error.json'))
            failure = json.loads(base64.b64decode(archive['files'][name]))
            failure['error']['message'] = 'a different failure'
            archive['files'][name] = base64.b64encode(json.dumps(failure).encode()).decode()
        else:
            name = next(key for key in archive['files'] if key.endswith('/profiler-capture.json'))
            del archive['files'][name]
        path.write_bytes(gzip.compress(json.dumps(archive).encode(), mtime=0))
        assessment['archive']['sha256'] = sha(path.read_bytes())
    else:
        program = completion.read_sealed_artifact(binding['evidence']['program'], base)
        capture = program['runtime_read_program']
        if damage == 'wrong-host':
            program['gateway']['payload']['is_command_line'] = True
        elif damage == 'wrong-time':
            time = program['native_call']['args']['time'] + 1
            program['gateway']['argv'][3] = str(time)
            program['gateway']['payload']['agent_result']['profiler_position'] = str(time)
            program['native_call']['args']['time'] = time
            binding['input']['gateway_argv'] = deepcopy(program['gateway']['argv'])
        elif damage == 'stale-source':
            key = next(iter(capture['source_context']['capture']))
            capture['source_context']['capture'][key] = '0' * 64
        elif damage == 'failed-phase':
            capture['phase_reports']['teardown'] = 'failed'
        capture['gateway'] = deepcopy(program['gateway'])
        capture['native_call'] = deepcopy(program['native_call'])
        assessment['program_capture'] = write_json(base / 'changed-capture.json', capture)
        binding['evidence']['program'].update(write_json(base / 'changed-program.json', program))
    binding['qualified_runtime_read_attachment'] = write_json(base / 'changed-assessment.json', assessment)
    native['assessment_sha256'] = binding['qualified_runtime_read_attachment']['sha256']
    binding['evidence']['native'].update(write_json(base / 'changed-native.json', native))
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    row = next(row for row in result['obligations'] if row['id'] == identity)
    assert row['evidence_results']['native']['outcome'] == 'missing', json.dumps(row)
    assert reason in row['evidence_results']['native']['reason'], json.dumps(row)
