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


def test_r124_qualified_seed_admission_reads_exact_owned_array():
    from tests.support.qualified_runtime_read_evidence import retained_read
    original = retained_read('2023.1', 'profiler-voices-seed')
    assert len(original['raw']['result']['return']) == 1
    assert len(original['raw']['result']['return'][0]) == 20
    assert original['receipt']['argv'][3] == '28746'
    assert original['capture']['cleanup']['complete'] is True


def _r124_inventory(scope_path=None):
    """Read only43 selected obligations plus their reference edges; no generator."""
    import gzip
    from tests.support.qualified_runtime_read_evidence import ANCHOR_SELECTORS
    scope = json.loads((audit.ROOT / (scope_path or ANCHOR_SELECTORS)).read_bytes())
    selected = {s['id'] for p in scope['profiles'].values() for s in p['selectors']}
    routes = {p['route'] for p in scope['profiles'].values()}
    stored = json.loads((audit.ROOT / 'docs/branch-coverage-inventory.json').read_bytes())
    packed = json.loads(gzip.decompress((audit.ROOT / 'docs/branch-coverage-inventory.native-obligations.json.gz').read_bytes()))
    rows = []
    for encoded in packed['rows']:
        if encoded.get('route') is None or packed['routes'][encoded['route']] not in routes:
            continue
        route = packed['routes'][encoded['route']]
        if route + '|' + encoded['pointer'] not in selected and encoded['kind'] != 'reference' and not (scope_path and route.endswith('.getRTPCs')):
            continue
        row = dict(encoded); row.update(packed['contexts'][row.pop('context')])
        row.update(route=route, id=route + '|' + row['pointer'], shape_sha256=packed['shapes'][row.pop('shape')])
        rows.append(row)
    native_routes = [r for r in stored['native_coverage']['routes'] if r['id'] in routes]
    public = {r['public_route'] for r in native_routes}
    return {'routes': [r for r in stored['routes'] if r['id'] in public], 'native_coverage': {
        'candidate_sha256': 'b' * 64, 'catalogs': stored['native_coverage']['catalogs'],
        'routes': native_routes, 'obligations': rows}}


@pytest.fixture(scope='module')
def r124_cases(tmp_path_factory):
    from tests.support.qualified_runtime_read_evidence import (anchor_profile, retained_read,
        retained_contribution_inputs, write_qualified_read_bundle, fixture_path)
    from tests.unit.test_fixed_runtime_read_branch_evidence import public_fixed_read
    from tests.unit.test_contribution_branch_evidence import public_contribution_flow
    inventory = _r124_inventory()
    cases = {}
    for version in ('2021.1', '2023.1', '2024.1'):
        categories = ['profiler-voices-seed', 'profiler-busses-seed']
        if version == '2021.1': categories.append('profiler-contributions-bus-observation')
        for category in categories:
            root = tmp_path_factory.mktemp('r124-' + version + '-' + category)
            retained = retained_read(version, category)
            if category.endswith('-seed'):
                receipt, native, context, trace = public_fixed_read(root / 'public', version=version,
                    uri=retained['raw']['api'], position=str(retained['profile']['time']), rows=retained['raw']['result']['return'])
                calls = [{'gateway': receipt, 'native_start': 0, 'native_end': len(trace)}]
            else:
                receipt, native, context, trace, calls, _ = public_contribution_flow(root / 'public', version,
                    retained=retained_contribution_inputs(version))
            assert native['result'] == retained['raw']['result']
            capture = root / 'program.json'
            write_program_receipt(capture, receipt, native, nodeid=version + '-' + category,
                phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context,
                native_reads=trace, public_calls=calls)
            selected = {s['id'] for s in anchor_profile(version, category)['selectors']}
            index = write_qualified_read_bundle(root / 'bundle', capture, fixture_path(version),
                inventory=inventory, version=version, category=category, selected=selected)
            policy = json.loads((index.parent / 'requirements.json').read_bytes())
            document, base, _ = audit.portable_binding_inputs(index, policy)
            cases[version, category] = (inventory, index, policy, document, base, selected)
    return cases


@pytest.mark.parametrize('version,category', [
    (v, c) for v in ('2021.1', '2023.1', '2024.1') for c in ('profiler-voices-seed', 'profiler-busses-seed')
] + [('2021.1', 'profiler-contributions-bus-observation')])
def test_r124_all43_native_anchors_replay_complete_original_public_packets(r124_cases, version, category):
    inventory, index, policy, document, base, selected = r124_cases[version, category]
    result = completion.evaluate_coverage(audit.ROOT, inventory, document, digest=audit.digest,
        evidence_base=base, requirements_document=policy)
    observed = [r for r in result['obligations'] if r['id'] in selected]
    assert len(observed) == (7 if category != 'profiler-busses-seed' else 5)
    assert all(r['state'] == 'verified' and r['evidence_results']['native']['outcome'] == 'passed' for r in observed), json.dumps(observed)
    assessment = completion.read_sealed_artifact(next(iter(document['bindings'].values()))['qualified_runtime_read_attachment'], base)
    assert assessment['original_workflow_outcome'] == assessment['original_finalization'] == 'BLOCKED'
    assert assessment['successful_finalization'] is False
    assert len(assessment['lifecycle_obligations']) == (3 if version == '2021.1' else 2)
    assert all(r['status'] == 'BLOCKED' for r in assessment['lifecycle_obligations'])
    print('R124_RETAINED_NATIVE_ANCHORS', version, category, len(observed))


def test_r124_qualified_anchor_controls_reuse_one_complete_public_capture(tmp_path):
    """One original packet supports related admission damage controls, not new native credit."""
    import shutil
    from tests.maintenance import branch_coverage_audit as audit
    from tests.maintenance import branch_audit_completion as completion
    from tests.support import qualified_runtime_read_evidence as qualified
    from tests.support.runtime_observation_evidence import write_json, write_program_receipt
    from tests.unit.test_fixed_runtime_read_branch_evidence import public_fixed_read
    inventory = _r124_inventory()
    retained = qualified.retained_read('2021.1', 'profiler-voices-seed')
    receipt, native, context, trace = public_fixed_read(tmp_path / 'public', version='2021.1',
        uri='ak.wwise.core.profiler.getVoices', position='24202', rows=retained['raw']['result']['return'])
    capture = tmp_path / 'program.json'
    write_program_receipt(capture, receipt, native, nodeid='r124-control-program',
        phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context,
        native_reads=trace, public_calls=[{'gateway': receipt, 'native_start': 0, 'native_end': len(trace)}])
    source_index = qualified.write_qualified_read_bundle(tmp_path / 'source', capture, qualified.fixture_path('2021.1'),
        inventory=inventory, version='2021.1', category='profiler-voices-seed')
    base = tmp_path / 'bundle'
    shutil.copytree(source_index.parent, base)
    policy = json.loads((base / 'requirements.json').read_bytes())
    document, _, _ = audit.portable_binding_inputs(base / source_index.name, policy)
    target = next(i for i in document['bindings'] if i.endswith('/voiceReturn/properties/baseVolume'))
    original_binding = document['bindings'][target]
    policy['branches'] = {target: policy['branches'][target]}
    for damage in ('value', 'version', 'category', 'time', 'source', 'truncated', 'archive', 'lifecycle', 'missing-program', 'empty'):
        binding = deepcopy(original_binding)
        assessment = completion.read_sealed_artifact(binding['qualified_runtime_read_attachment'], base)
        evidence = completion.read_sealed_artifact(binding['evidence']['native'], base)
        if damage == 'value':
            evidence['observed'] += 1.0
        elif damage == 'version':
            assessment['version'] = '2024.1'
        elif damage == 'category':
            assessment['category'] = 'profiler-busses-seed'
        elif damage == 'archive':
            assessment['archive']['sha256'] = '0' * 64
        elif damage == 'lifecycle':
            assessment['lifecycle_obligations'] = [r for r in assessment['lifecycle_obligations'] if r['version'] != '2021.1']
        else:
            program = completion.read_sealed_artifact(binding['evidence']['program'], base)
            capture = program['runtime_read_program']
            if damage == 'time':
                program['native_call']['args']['time'] += 1
            elif damage == 'source':
                capture['source_context']['capture']['tests/support/qualified_runtime_read_evidence.py'] = '0' * 64
            elif damage == 'empty':
                program['native_call']['result']['return'] = []
            elif damage == 'truncated':
                program['gateway']['payload']['agent_result'].update(complete=False, truncated=True)
            else:
                capture['phase_reports']['teardown'] = 'failed'
            capture['gateway'] = deepcopy(program['gateway']); capture['native_call'] = deepcopy(program['native_call'])
            assessment['program_capture'] = write_json(base / (damage + '-capture.json'), capture)
            binding['evidence']['program'].update(write_json(base / (damage + '-program.json'), program))
        binding['qualified_runtime_read_attachment'] = write_json(base / (damage + '-assessment.json'), assessment)
        evidence['assessment_sha256'] = binding['qualified_runtime_read_attachment']['sha256']
        binding['evidence']['native'].update(write_json(base / (damage + '-native.json'), evidence))
        result = completion.evaluate_coverage(audit.ROOT, inventory,
            {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': {target: binding}},
            digest=audit.digest, evidence_base=base, requirements_document=policy)
        row = next(r for r in result['obligations'] if r['id'] == target)
        assert row['state'] != 'verified', (damage, row)
        assert row['evidence_results']['native']['outcome'] == 'missing', (damage, row)
    assessment = completion.read_sealed_artifact(original_binding['qualified_runtime_read_attachment'], base)
    capture = base / assessment['program_capture']['artifact']
    extra = target.rsplit('/', 1)[0] + '/objectName'
    with pytest.raises(ValueError, match='no independently observed native result fact'):
        qualified.write_qualified_read_bundle(tmp_path / 'extra', capture, qualified.fixture_path('2021.1'),
            inventory=inventory, version='2021.1', category='profiler-voices-seed', selected={extra})
    with pytest.raises(ValueError, match='exact retained read categories'):
        qualified.retained_read('2021.1', 'profiler-rtpcs-observation')


def test_r125_assessed_r104_reads_preserve_failed_workflow_and_completed_cleanup():
    from tests.support.qualified_runtime_read_evidence import retained_read
    retained = retained_read('2021.1', 'r104-object-rtpcs-observation')
    assert retained['raw']['result']['return'] == [
        {'gameObjectId': 18446744073709551614, 'id': '{63D15B0F-16E7-4B8A-B9CA-7BF10AD315B4}', 'name': 'RPM', 'value': 1000.0},
        {'gameObjectId': 18446744073709551614, 'id': '{EB92D28A-BB63-4332-8166-0AC95BAD9EFE}', 'name': 'Engine_Load', 'value': 1.0}]
    assert retained['facts']['original_workflow_outcome'] == 'BLOCKED'
    assert retained['facts']['original_read_outcome'] == 'BLOCKED'
    assert retained['facts']['collector_owned_identity_observed'] is False
    assert retained['facts']['physical_cleanup_complete'] is True
    assert retained['facts']['post_terminal_port_8080_bindable'] is True
    assert retained['facts']['qualified_scope'] == 'object-specific read facts only; global setter effect unverified'


@pytest.fixture(scope='module')
def r125_cases(tmp_path_factory):
    from tests.support import qualified_runtime_read_evidence as q
    from tests.unit.test_fixed_runtime_read_branch_evidence import public_fixed_read
    inventory = _r124_inventory(q.R104_SELECTORS)
    scope = json.loads((audit.ROOT / q.R104_SELECTORS).read_bytes())
    cases = {}
    for key, profile in scope['profiles'].items():
        version, category = key.split('|'); root = tmp_path_factory.mktemp('r125-' + key.replace('|', '-'))
        retained = q.retained_read(version, category); rows = retained['raw']['result']['return']
        if category == 'r104-object-rtpcs-observation':
            receipt, native, context = public_rtpc_read(root / 'public', version=version,
                position=str(profile['time']), rows=rows)
            extra = {}
        else:
            receipt, native, context, trace = public_fixed_read(root / 'public', version=version,
                uri=profile['uri'], position=str(profile['time']), rows=rows)
            extra = {'native_reads': trace, 'public_calls': [{'gateway': receipt, 'native_start': 0, 'native_end': len(trace)}]}
        assert receipt['argv'] == profile['public_argv']
        assert native['result'] == retained['raw']['result']
        capture = root / 'program.json'
        write_program_receipt(capture, receipt, native, nodeid='r125-' + key,
            phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), source_context=context, **extra)
        selected = {s['id'] for s in profile['selectors']}
        index = q.write_qualified_read_bundle(root / 'bundle', capture, q.r104_fixture_path(version),
            inventory=inventory, version=version, category=category, selected=selected)
        policy = json.loads((index.parent / 'requirements.json').read_bytes())
        document, base, _ = audit.portable_binding_inputs(index, policy)
        cases[key] = (inventory, index, policy, document, base, selected)
    return cases


@pytest.mark.parametrize('key', [
    '2021.1|r104-audio-objects-observation', '2021.1|r104-object-rtpcs-observation',
    '2022.1|r104-audio-objects-observation', '2022.1|r104-game-objects-observation',
    '2023.1|r104-audio-objects-observation', '2023.1|r104-game-objects-observation',
    '2024.1|r104-audio-objects-observation', '2024.1|r104-game-objects-observation'])
def test_r125_all22_native_anchors_replay_eight_complete_original_public_packets(r125_cases, key):
    inventory, index, policy, document, base, selected = r125_cases[key]
    result = completion.evaluate_coverage(audit.ROOT, inventory, document, digest=audit.digest,
        evidence_base=base, requirements_document=policy)
    observed = [r for r in result['obligations'] if r['id'] in selected]
    assert len(observed) == (4 if 'audio' in key else 3 if 'rtpcs' in key else 1)
    assert all(r['state'] == 'verified' and r['evidence_results']['native']['outcome'] == 'passed' for r in observed), json.dumps(observed)
    assessment = completion.read_sealed_artifact(next(iter(document['bindings'].values()))['qualified_runtime_read_attachment'], base)
    assert assessment['original_workflow_outcome'] == assessment['original_finalization'] == 'BLOCKED'
    assert assessment['successful_finalization'] is False
    assert assessment['lifecycle_obligations'] == []
    facts = assessment['retained_facts']
    assert facts['physical_cleanup_complete'] is True and facts['post_terminal_port_8080_bindable'] is True
    assert facts['cleanup_credit_transferred'] is False
    if '2022.1|r104-game' in key:
        assert facts['original_public_exit_code'] == 2 and facts['original_read_outcome'] == 'FAIL'
    if 'rtpcs' in key:
        assert facts['original_read_outcome'] == 'BLOCKED' and facts['collector_owned_identity_observed'] is False
        assert 'global setter effect unverified' in facts['qualified_scope']
    print('R125_RETAINED_NATIVE_ANCHORS', key, len(observed))


def test_r125_qualified_r104_controls_preserve_exact_scope_and_failures(r125_cases):
    """Reuse admitted packets for related, resealed damage; never invent a new workflow PASS."""
    from tests.support import qualified_runtime_read_evidence as q
    inventory, index, policy, document, base, selected = r125_cases['2021.1|r104-object-rtpcs-observation']
    target = next(i for i in selected if i.endswith('/value')); original = document['bindings'][target]
    policy = deepcopy(policy); policy['branches'] = {target: policy['branches'][target]}
    for damage in ('value', 'global-effect-pass', 'cleanup-credit', 'workflow-pass', 'r105-lifecycle',
                   'public-pass', 'r105-source', 'archive', 'category', 'time', 'empty', 'drop-second-row',
                   'stale-source', 'failed-teardown', 'truncated'):
        binding = deepcopy(original)
        assessment = completion.read_sealed_artifact(binding['qualified_runtime_read_attachment'], base)
        native = completion.read_sealed_artifact(binding['evidence']['native'], base)
        if damage == 'value': native['observed'] = 2575.0
        elif damage == 'global-effect-pass': assessment['retained_facts']['collector_owned_identity_observed'] = True
        elif damage == 'cleanup-credit': assessment['retained_facts']['cleanup_credit_transferred'] = True
        elif damage == 'workflow-pass': assessment['original_workflow_outcome'] = 'PASS'
        elif damage == 'public-pass': assessment['retained_facts']['original_read_outcome'] = 'PASS'
        elif damage == 'r105-lifecycle': assessment['lifecycle_obligations'] = q.lifecycle_obligations('2021.1')
        elif damage == 'r105-source': assessment['source_changes'] = q.runtime.RTPC_REVIEWED_SOURCE_CHANGES
        elif damage == 'archive': assessment['archive']['sha256'] = '0' * 64
        elif damage == 'category': assessment['category'] = 'profiler-rtpcs-observation'
        else:
            program = completion.read_sealed_artifact(binding['evidence']['program'], base)
            capture = program['runtime_read_program']
            if damage == 'time': program['native_call']['args']['time'] += 1
            elif damage == 'empty': program['native_call']['result']['return'] = []
            elif damage == 'drop-second-row': program['native_call']['result']['return'].pop()
            elif damage == 'stale-source': capture['source_context']['capture']['tests/support/qualified_runtime_read_evidence.py'] = '0' * 64
            elif damage == 'failed-teardown': capture['phase_reports']['teardown'] = 'failed'
            elif damage == 'truncated': program['gateway']['payload']['agent_result'].update(complete=False, truncated=True)
            capture['gateway'] = deepcopy(program['gateway']); capture['native_call'] = deepcopy(program['native_call'])
            assessment['program_capture'] = write_json(base / (damage + '-capture.json'), capture)
            binding['evidence']['program'].update(write_json(base / (damage + '-program.json'), program))
        binding['qualified_runtime_read_attachment'] = write_json(base / (damage + '-assessment.json'), assessment)
        native['assessment_sha256'] = binding['qualified_runtime_read_attachment']['sha256']
        binding['evidence']['native'].update(write_json(base / (damage + '-native.json'), native))
        result = completion.evaluate_coverage(audit.ROOT, inventory,
            {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': {target: binding}},
            digest=audit.digest, evidence_base=base, requirements_document=policy)
        row = next(r for r in result['obligations'] if r['id'] == target)
        assert row['state'] != 'verified', (damage, row)
        assert row['evidence_results']['native']['outcome'] == 'missing', (damage, row)
    # The raw-only exception is not permission to manufacture a historical public success.
    inventory, index, policy, document, base, selected = r125_cases['2022.1|r104-game-objects-observation']
    target, = selected; binding = deepcopy(document['bindings'][target])
    assessment = completion.read_sealed_artifact(binding['qualified_runtime_read_attachment'], base)
    assessment['retained_facts']['original_public_exit_code'] = 0
    binding['qualified_runtime_read_attachment'] = write_json(base / 'forged-public-pass-assessment.json', assessment)
    native = completion.read_sealed_artifact(binding['evidence']['native'], base)
    native['assessment_sha256'] = binding['qualified_runtime_read_attachment']['sha256']
    binding['evidence']['native'].update(write_json(base / 'forged-public-pass-native.json', native))
    result = completion.evaluate_coverage(audit.ROOT, inventory,
        {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': {target: binding}}, digest=audit.digest,
        evidence_base=base, requirements_document=policy)
    row = next(r for r in result['obligations'] if r['id'] == target)
    assert row['evidence_results']['native']['outcome'] == 'missing'
    with pytest.raises(ValueError, match='Only exact22 assessed R104'):
        q.retained_read('2022.1', 'r104-object-rtpcs-observation')
    # A real but unapproved field does not inherit native credit from its row.
    retained = q.retained_read('2021.1', 'r104-object-rtpcs-observation')
    extra = retained['profile']['route'] + '|/resultSchema/properties/return/items/properties/name'
    source = r125_cases['2021.1|r104-object-rtpcs-observation']
    assessment = completion.read_sealed_artifact(source[3]['bindings'][next(iter(source[5]))]['qualified_runtime_read_attachment'], source[4])
    with pytest.raises(ValueError, match='no independently observed native result fact'):
        q.write_qualified_read_bundle(base / 'extra', source[4] / assessment['program_capture']['artifact'], q.r104_fixture_path('2021.1'),
            inventory=source[0], version='2021.1', category='r104-object-rtpcs-observation', selected={extra})
