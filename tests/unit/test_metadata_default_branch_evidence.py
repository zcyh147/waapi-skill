"""Exact portable metadata-default program proof; no synthetic native credit."""
from copy import deepcopy
import json

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion


# Exact reviewed scope, independent of the capture validator's policy table.
APPROVED_ABSENT_DEFAULTS = {
    version + '|wwise-console|' + build + '|function|ak.wwise.core.object.getPropertyInfo|/resultSchema/properties/default/@presence/absent'
    for version, build in (
        ('2021.1', '2021.1.14.8108'), ('2022.1', '2022.1.19.8584'),
        ('2023.1', '2023.1.19.8928'), ('2024.1', '2024.1.13.9056'),
        ('2025.1', '2025.1.7.9143'))
}


def test_selected_metadata_policy_accepts_only_the_reviewed_decoder_split():
    from tests.support.metadata_read_branch_evidence import validate_selected_metadata_requirement
    policy = audit.load(audit.ROOT / 'docs/branch-coverage-requirements.json')
    metadata = {identity: requirement for identity, requirement in policy['branches'].items()
        if '|function|ak.wwise.core.object.getPropertyInfo|' in identity}
    assert len(metadata) == 65
    assert {identity for identity, requirement in metadata.items()
        if requirement['categories'] == ['program']} == APPROVED_ABSENT_DEFAULTS
    for identity, requirement in metadata.items():
        branch = {'id': identity, 'shape_sha256': requirement['native_shape_sha256']}
        validate_selected_metadata_requirement(branch, requirement)
        weakened = {**requirement, 'categories': ['program']}
        if identity not in APPROVED_ABSENT_DEFAULTS:
            with pytest.raises(ValueError, match='evidence policy changed'):
                validate_selected_metadata_requirement(branch, weakened)


def selected_defaults(rows):
    return [row for row in rows if row['route'] and '|wwise-console|' in row['route']
        and row['route'].endswith('|ak.wwise.core.object.getPropertyInfo')
        and (row['pointer'].startswith('/resultSchema/properties/default')
             or any(row['pointer'].startswith('/resultSchema/@definition/' + document + '/definitions/propertyValue')
                    for document in ('waapi_definitions.json', 'common_definitions.json')))]


@pytest.fixture(scope='module')
def product_defaults():
    inventory = audit.build_inventory()
    policy = audit.load(audit.ROOT / 'docs/branch-coverage-requirements.json')
    bindings, base, _ = audit.portable_binding_inputs(audit.ROOT / 'docs/branch-coverage-evidence-index.json', policy)
    return inventory, policy, bindings, base


@pytest.fixture(scope='module')
def original_defaults():
    """Read original receipts under their own sealed policy, never current-product credit."""
    inventory = audit.build_inventory()
    index_path = audit.ROOT / 'docs/branch-coverage-evidence-index.json'
    index = audit.load(index_path)
    base = (index_path.parent / index['base']).resolve()
    original_policy = deepcopy(audit.load(audit.ROOT / 'docs/branch-coverage-requirements.json'))
    recovered = set()
    for entry in index['entries']:
        policy = completion.read_sealed_artifact(entry['origin']['requirements'], base)
        for identity in APPROVED_ABSENT_DEFAULTS & policy['branches'].keys():
            assert identity not in recovered
            original_policy['branches'][identity] = policy['branches'][identity]
            recovered.add(identity)
    assert recovered == APPROVED_ABSENT_DEFAULTS
    bindings, base, _ = audit.portable_binding_inputs(index_path, original_policy)
    return inventory, original_policy, bindings, base


def test_default_index_selects_exact_five_version_metadata_defaults_without_live_credit(product_defaults):
    inventory, policy, bindings, base = product_defaults
    selected = selected_defaults(inventory['native_coverage']['obligations'])
    assert len(selected) == 65
    assert {row['owner_issue'] for row in selected} == {181}
    for branch in selected:
        expected_categories = ['program'] if branch['id'] in APPROVED_ABSENT_DEFAULTS else ['program', 'live_metadata']
        assert policy['branches'][branch['id']]['categories'] == expected_categories
        assert branch['id'] in bindings['bindings']
    result = completion.evaluate_coverage(audit.ROOT, inventory, bindings, digest=audit.digest,
        requirements_document=policy, evidence_base=base)
    selected_ids = {row['id'] for row in selected}
    actual = [row for row in result['obligations'] if row['id'] in selected_ids]
    assert len(actual) == 65
    for row in actual:
        import hashlib
        binding=bindings['bindings'][row['id']]
        receipt = completion.read_sealed_artifact(binding['evidence']['program'], base)
        current_sources=all(hashlib.sha256((audit.ROOT/name).read_bytes()).hexdigest()==value
            for name,value in receipt['relevant_sources'].items())
        expected = 'passed' if receipt['candidate_sha256'] == result['candidate_sha256'] and current_sources else 'missing'
        assert row['evidence_results']['program']['outcome'] == expected
        if row['id'] in APPROVED_ABSENT_DEFAULTS:
            assert set(row['evidence_results']) == {'program'}
            assert 'live_metadata' not in binding['evidence']  # Real occurrence stays unobserved.
            assert (row['state'] == 'verified') == (expected == 'passed')
            continue
        native=row['evidence_results']['live_metadata']['outcome']
        if 'live_metadata' not in binding['evidence']:
            assert native=='missing'  # Assigned unobserved alternatives remain required.
        else:
            original=completion.read_sealed_artifact(binding['evidence']['live_metadata'],base)
            assert original['evidence_kind'] in {'historical_metadata_current_program_replay',
                'current_public_class_metadata','historical_class_metadata_current_program_replay'}
            assert native in {'passed','missing'}  # Current source drift is honestly missing.
        assert (row['state']=='verified') == (expected=='passed' and native=='passed')
    assert result['completion']['obligations'] == 272313
    assert result['completion']['complete'] is False
    unrelated = [row for row in result['obligations'] if row['id'] not in selected_ids]
    assert len(unrelated)==result['completion']['obligations']-len(selected)
    for row in unrelated:
        if row['state']=='verified':
            assert row['id'] in bindings['bindings'] and all(
                value['outcome']=='passed' for value in row['evidence_results'].values())


@pytest.mark.parametrize('damage', ['missing-check', 'wrong-sibling', 'null-is-not-absence',
    'present-public-default', 'missing-public-parent', 'missing-whole-result-proof', 'source-drift'])
@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1'])
def test_original_default_program_cannot_certify_unobserved_fact(original_defaults, tmp_path, damage, version):
    """Historical reader controls; current-product evidence is evaluated separately."""
    inventory, _, bindings, base = original_defaults
    selected = selected_defaults(inventory['native_coverage']['obligations'])
    branch = next(row for row in selected if row['id'].startswith(version + '|')
        and row['pointer'].endswith('/@presence/absent'))
    binding = deepcopy(bindings['bindings'][branch['id']])
    descriptor = binding['evidence']['program']
    record = completion.read_sealed_artifact(descriptor, base)
    # A successor may honestly lack current proof. These structural controls
    # must still start from a valid original receipt, never that stale failure.
    original_candidate = record['candidate_sha256']
    assert completion.evidence_result(descriptor, branch, original_candidate,
        'program', 'product', base, binding, source_root=audit.ROOT) == ('passed', None)
    if damage == 'missing-check':
        record['branch_assertions'][branch['id']]['checks'] = [check for check in
            record['branch_assertions'][branch['id']]['checks'] if check['pointer'] != binding['observation_pointer']]
    elif damage == 'wrong-sibling':
        binding['observation_pointer'] = '/native_call/result/restriction'
    elif damage == 'null-is-not-absence':
        record['native_call']['result']['default'] = None
    elif damage == 'present-public-default':
        record['gateway']['payload']['agent_result']['metadata']['default'] = None
    elif damage == 'missing-public-parent':
        del record['gateway']['payload']['agent_result']['metadata']
        # Keep the whole-result assertion exact so only the missing containing
        # object (not an unrelated stale assertion) can reject the omission.
        for check in record['branch_assertions'][branch['id']]['checks']:
            if check['pointer'] == '/gateway/payload/agent_result':
                check['equals'] = deepcopy(record['gateway']['payload']['agent_result'])
    elif damage == 'missing-whole-result-proof':
        record['branch_assertions'][branch['id']]['checks'] = [check for check in
            record['branch_assertions'][branch['id']]['checks'] if check['pointer'] != '/gateway/payload/agent_result']
    else:
        record['candidate_sha256'] = '0' * 64
    path = tmp_path / 'damaged.json'
    path.write_text(json.dumps(record), encoding='utf-8')
    import hashlib
    changed = {**descriptor, 'artifact': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    result = completion.evidence_result(changed, branch, original_candidate,
        'program', 'product', base, binding, source_root=audit.ROOT)
    assert result[0] == 'missing'


@pytest.mark.parametrize('damage', ['wrong-build', 'wrong-host', 'wrong-field', 'wrong-shape',
    'missing-reason', 'missing-program', 'extra-native'])
def test_decoder_policy_does_not_exempt_a_changed_identity_or_shape(damage):
    from tests.support.metadata_read_branch_evidence import validate_selected_metadata_requirement
    identity = sorted(APPROVED_ABSENT_DEFAULTS)[0]
    policy = deepcopy(audit.load(audit.ROOT / 'docs/branch-coverage-requirements.json')['branches'][identity])
    branch = {'id': identity, 'shape_sha256': policy['native_shape_sha256']}
    if damage == 'wrong-build':
        branch['id'] = identity.replace('2021.1.14.8108', '2021.1.0.1')
    elif damage == 'wrong-host':
        branch['id'] = identity.replace('wwise-console', 'wwise-authoring')
    elif damage == 'wrong-field':
        branch['id'] = identity.replace('/default/', '/type/')
    elif damage == 'wrong-shape':
        branch['shape_sha256'] = policy['native_shape_sha256'] = '0' * 64
    elif damage == 'missing-reason':
        policy['reason'] = ''
    elif damage == 'missing-program':
        policy['categories'] = []
    else:
        policy['categories'] = ['program', 'live_metadata']
    with pytest.raises(ValueError, match='evidence policy changed'):
        validate_selected_metadata_requirement(branch, policy)


def test_replay_preparation_requires_exact_default_membership_and_policies():
    from tests.support.metadata_replay_branch_evidence import validate_default_replay_requirements
    inventory = audit.build_inventory()
    policy = audit.load(audit.ROOT / 'docs/branch-coverage-requirements.json')
    expected = {row['id'] for row in selected_defaults(inventory['native_coverage']['obligations'])}
    assert validate_default_replay_requirements(inventory, policy) == expected
    unrelated = next(identity for identity in expected if identity not in APPROVED_ABSENT_DEFAULTS)
    weakened = deepcopy(policy)
    weakened['branches'][unrelated]['categories'] = ['program']
    with pytest.raises(ValueError, match='evidence policy changed'):
        validate_default_replay_requirements(inventory, weakened)
    # A substituted identity cannot keep the original set merely by preserving count.
    substituted = deepcopy(policy)
    identity = sorted(APPROVED_ABSENT_DEFAULTS)[0]
    substituted['branches'][identity.replace('/default/', '/type/')] = substituted['branches'].pop(identity)
    with pytest.raises(ValueError, match='default requirements changed'):
        validate_default_replay_requirements(inventory, substituted)


def test_portable_originals_reject_a_tampered_requirement(original_defaults):
    _, original_policy, _, _ = original_defaults
    tampered = deepcopy(original_policy)
    identity = sorted(APPROVED_ABSENT_DEFAULTS)[0]
    tampered['branches'][identity]['reason'] += ' Unreviewed policy change.'
    with pytest.raises(ValueError, match='portable requirement differs from reviewed exact branch policy'):
        audit.portable_binding_inputs(audit.ROOT / 'docs/branch-coverage-evidence-index.json', tampered)
