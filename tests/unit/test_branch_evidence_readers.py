"""Existing producer compatibility, independent of new branch coverage claims."""
import hashlib
import json
from pathlib import Path
from copy import deepcopy

import pytest

from tests.maintenance import branch_audit_completion as completion

FIXTURES = Path(__file__).parents[1] / 'fixtures/branch-evidence'


def sealed(path, **extra):
    return {'artifact': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), **extra}


def test_existing_category_v3_positive_and_forged_host_negative(tmp_path):
    path = FIXTURES / 'category-v3.json'
    original = json.loads(path.read_text())
    descriptor = sealed(path, nodeid=original['invocation']['node_outcomes'][0]['nodeid'])
    context = completion.read_category_run(descriptor, tmp_path)
    assert context['candidate'] == original['candidate']
    assert context['host'] == 'wwise-console' and context['version'] == '2024.1'
    assert context['build'] == '.'.join(str(original['host']['version'][k]) for k in ('year', 'major', 'minor', 'build'))
    forged = deepcopy(original)
    forged['host'] = {'wwise_build': context['build'], 'native_host': 'wwise-console', 'candidate_source_sha256': 'a' * 64}
    target = tmp_path / 'forged.json';target.write_text(json.dumps(forged))
    with pytest.raises((ValueError, KeyError)):
        completion.read_category_run(sealed(target, nodeid=descriptor['nodeid']), tmp_path)


def metadata_descriptor():
    root = FIXTURES / 'metadata'
    return {'seal': sealed(root / 'seal.json'), 'root': str(root), 'receipt': '006', 'status_receipt': '003'}


def test_existing_scenario_metadata_positive_and_exact_receipt_corruption(tmp_path):
    descriptor = metadata_descriptor()
    result = completion.read_metadata_run(descriptor, tmp_path)
    assert result['version'] == '2021.1' and result['host'] == 'wwise-console'
    assert result['build'] == '2021.1.14.8108'
    assert result['gateway']['payload']['agent_result']['metadata']['name'] == 'ContinuePlay'
    assert result['candidate'] == 'e0f2d2952488223865a1c52cd485a7ed897184a4'
    import shutil
    copied = tmp_path / 'metadata';shutil.copytree(FIXTURES / 'metadata', copied)
    damaged = deepcopy(descriptor);damaged['root'] = str(copied)
    (copied / '006.stdout').write_text('{}')
    with pytest.raises(ValueError, match='seal'):
        completion.read_metadata_run(damaged, tmp_path)


@pytest.mark.parametrize('per_record', [False, True])
def test_metadata_branch_uses_original_receipt_and_reviewed_source_equivalence(tmp_path, per_record):
    from tests.maintenance import branch_coverage_audit as audit
    context = completion.read_metadata_run(metadata_descriptor(), tmp_path)
    branch = {'id': 'controlled-original-metadata', 'route': None, 'version': '2021.1', 'build': '2021.1.14.8108',
              'pointer': '/installed/condition', 'kind': 'metadata_condition', 'shape_sha256': 'b' * 64}
    candidate = 'c' * 64
    sources = ['skills/waapi-skill/scripts/run.py', 'skills/waapi-skill/scripts/gateway.py']
    binding = {'input': {'gateway_argv': context['gateway']['argv']}, 'native_hosts': ['wwise-console'],
        'observation_pointer': '/gateway/payload/agent_result/metadata/dependencies/0/context', 'relevant_sources': sources,
        **{key: {'source': 'skills/waapi-skill/scripts/gateway.py#execute_gateway', 'selector': branch['pointer']}
           for key in ('construction', 'validation', 'verifier')}}
    record = {'candidate_sha256': candidate, 'scope_kind': 'controlled', 'metadata_run': metadata_descriptor(),
        'invocation': {'phase': 'final', 'outcome': 'PASS', 'node_outcomes': [{'nodeid': 'preserved-metadata', 'outcome': 'PASS'}]},
        'branch_assertions': {branch['id']: {'native_shape_sha256': branch['shape_sha256'], 'native_route': None,
          'checks': [{'pointer': binding['observation_pointer'], 'equals': 'AssocParent'}]}}}
    path = tmp_path / 'mapped.json';path.write_text(json.dumps(record))
    descriptor = sealed(path, nodeid='preserved-metadata')
    proof = {'contract': 'waapi-skill.branch-evidence-equivalence/v1', 'reviewed_reason': 'Controlled reader compatibility: original metadata source files unchanged.',
        'from_candidate': context['candidate'], 'to_candidate': candidate, 'branch_id': branch['id'],
        'native_shape_sha256': branch['shape_sha256'], 'native_route': None,
        'evidence_sha256': context['receipt_sha256'], 'binding_semantics_sha256': audit.digest(completion.binding_semantics(binding)),
        'sources': {name: context['relevant_sources'][name] for name in sources}}
    proof_path = tmp_path / 'reuse.json';proof_path.write_text(json.dumps(proof))
    binding['native_equivalence'] = ({context['receipt_sha256']: sealed(proof_path)} if per_record else sealed(proof_path))
    assert completion.evidence_result(descriptor, branch, candidate, 'live_metadata', 'controlled', tmp_path, binding) == ('passed', None)
    assert completion.evidence_result(descriptor, branch, candidate, 'native', 'controlled', tmp_path, binding)[0] == 'missing'
    assert completion.evidence_result(descriptor, branch, candidate, 'fresh', 'controlled', tmp_path, binding)[0] == 'missing'
    record['branch_assertions'][branch['id']]['checks'][0]['equals'] = 'Parent'
    path.write_text(json.dumps(record));descriptor = sealed(path, nodeid='preserved-metadata')
    assert completion.evidence_result(descriptor, branch, candidate, 'live_metadata', 'controlled', tmp_path, binding)[0] == 'missing'


def test_native_absence_requires_omission_in_each_exact_host_observation():
    hosts = {'wwise-console', 'wwise-authoring'}
    binding = {'absence_observation_pointers': {host: f'/observations/{host}/capabilities/field' for host in hosts}}
    record = {'observations': {host: {'capabilities': {}} for host in hosts}}
    checks = [{'pointer': pointer, 'absent': True} for pointer in binding['absence_observation_pointers'].values()]
    completion.validate_native_absence_observations(record, binding, checks, hosts)
    record['observations']['wwise-console']['capabilities']['field'] = True
    with pytest.raises(ValueError, match='present'):
        completion.validate_native_absence_observations(record, binding, checks, hosts)
    record['observations']['wwise-console']['capabilities'].clear()
    binding['absence_observation_pointers']['wwise-authoring'] = binding['absence_observation_pointers']['wwise-console']
    with pytest.raises(ValueError, match='host'):
        completion.validate_native_absence_observations(record, binding, checks, hosts)
