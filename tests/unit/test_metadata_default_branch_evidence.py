"""Exact portable metadata-default program proof; no synthetic native credit."""
from copy import deepcopy
import json

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion


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


def test_default_index_selects_exact_five_version_metadata_defaults_without_live_credit(product_defaults):
    inventory, policy, bindings, base = product_defaults
    selected = selected_defaults(inventory['native_coverage']['obligations'])
    assert len(selected) == 65
    assert {row['owner_issue'] for row in selected} == {181}
    for branch in selected:
        assert policy['branches'][branch['id']]['categories'] == ['program', 'live_metadata']
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
def test_original_default_program_cannot_certify_unobserved_fact(product_defaults, tmp_path, damage):
    """Historical reader controls; current-product evidence is evaluated separately."""
    inventory, _, bindings, base = product_defaults
    selected = selected_defaults(inventory['native_coverage']['obligations'])
    branch = next(row for row in selected if row['pointer'].endswith('/@presence/absent'))
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
