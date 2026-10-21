"""Source facts enter the existing branch reader through a closed portable proof."""
from copy import deepcopy
import json
import hashlib
import importlib
import shutil
from pathlib import Path

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.unit.test_source_copy_modern_collector import modern_collector_runtime, PROFILE


@pytest.fixture(scope='module')
def inventory():
    return audit.build_inventory()


@pytest.fixture(scope='module')
def source_case(tmp_path_factory, inventory):
    tmp_path = tmp_path_factory.mktemp('source-branch')
    with pytest.MonkeyPatch.context() as environment:
        environment.setenv('WWISE_LIVE', '1')
        environment.setenv('WWISE_DESTRUCTIVE', '1')
        workflow = importlib.import_module('tests.destructive.test_gateway_workflow_transaction_matrix')
    from tests.support.source_copy_branch_evidence import write_source_program_bundle

    (tmp_path / 'public').mkdir()
    runtime, _, _ = modern_collector_runtime(tmp_path / 'public')
    category = workflow._collect_legacy_source_copy_feasibility(runtime, prefix='SOURCE_BRANCH', saved_copy=True,
        saved_copy_protocol='gateway-owned-save-children/v1', fixture_profile=PROFILE)
    receipt = Path(category['observation_path'])
    index = write_source_program_bundle(tmp_path / 'portable', receipt,
        inventory=inventory, nodeid='controlled-source-2022', phase_reports={
            'setup': 'passed', 'call': 'passed', 'teardown': 'passed'}, scope_kind='controlled')
    receipt.parent.rename(receipt.parent.with_name(receipt.parent.name + '-unavailable'))
    return index, inventory


def test_2022_public_source_chain_is_portable_exact_branch_evidence(source_case):
    index, inventory = source_case
    requirements = json.loads((index.parent / 'requirements.json').read_bytes())
    # Original absolute locators are provenance only. The portable reader must
    # succeed with the old facts unavailable and retain byte-identical receipts.
    document, base, projection = audit.portable_binding_inputs(index, requirements)
    assert len(document['bindings']) == 4
    assert projection['source_business_facts'] == ['2022.1|source-copy-synth-owned-graph']
    branches = {row['id']: row for row in inventory['native_coverage']['obligations']}
    for identity, binding in document['bindings'].items():
        assert completion.evidence_result(binding['evidence']['program'], branches[identity],
            inventory['native_coverage']['candidate_sha256'], 'program', 'controlled', base,
            binding, source_root=audit.ROOT,
            reference_edges={row['id']: row for row in inventory['native_coverage']['obligations'] if row['kind'] == 'reference'}) == ('passed', None)
        assert set(binding['evidence']) == {'program'}  # No fake-native credit.
    original = json.loads((index.parent / 'proof.json').read_bytes())
    assert original['contract'] == 'waapi-skill.source-copy-portable-proof/v1'
    raw_receipt = completion.read_sealed_artifact(original['files'][original['receipt']['path']], index.parent)
    assert raw_receipt['diagnostic_only'] is True and raw_receipt['business_effect_verified'] is False



def test_source_program_binding_completes_exact_leaves_and_missing_selector_loses_implementation(source_case):
    index, inventory = source_case
    document, base, _ = audit.portable_binding_inputs(index,
        json.loads((index.parent / 'requirements.json').read_bytes()))
    selected = set(document['bindings'])
    route = next(row['route'] for row in inventory['native_coverage']['obligations'] if row['id'] in selected)
    scope = {'contract': 'waapi-skill.controlled-branch-scope/v1',
        'id': 'source-copy-public-binding-program-only', 'credit': 'controlled_program_only',
        'requirements': ['program'], 'native_catalogs': inventory['native_coverage']['catalogs'],
        'route_ids': [route], 'obligation_ids': [row['id'] for row in inventory['native_coverage']['obligations']
                                               if row['route'] == route]}
    def evaluate(bindings):
        result = completion.evaluate_coverage(audit.ROOT, inventory, bindings,
            digest=audit.digest, scope=scope, evidence_base=base)
        return {row['id']: row for row in result['obligations'] if row['id'] in selected}
    completed = evaluate(document)
    assert len(completed) == 4
    assert {row['state'] for row in completed.values()} == {'verified'}
    assert all(row['requirements'] == ['program']
        and row['evidence_results'] == {'program': {'outcome': 'passed', 'reason': None}}
        for row in completed.values())
    damaged = deepcopy(document)
    missing = next(iter(damaged['bindings']))
    del damaged['bindings'][missing]['input']['selector']
    rejected = evaluate(damaged)
    assert rejected[missing]['state'] == 'missing_implementation'
    assert rejected[missing]['evidence_results'] == {}
    assert rejected[missing]['reasons'] == ['exact public input/construction/validation/verifier binding missing or stale']
    assert all(row['state'] == 'verified' for identity, row in rejected.items() if identity != missing)

def test_source_attachment_rejects_wrong_branch_before_import(source_case, tmp_path):
    from tests.support.source_copy_branch_evidence import write_json
    original, _ = source_case
    root = tmp_path / 'wrong-branch'
    shutil.copytree(original.parent, root)
    index = json.loads((root / 'index.json').read_bytes())
    attachment = json.loads((root / 'attachment.json').read_bytes())
    attachment['branch_ids'][0] = attachment['branch_ids'][0].replace('/anyOf/1', '/anyOf/0')
    index['source_attachments'] = [write_json(root / 'attachment.json', attachment)]
    write_json(root / 'index.json', index)
    requirements = json.loads((root / 'requirements.json').read_bytes())
    with pytest.raises(ValueError, match='unsupported exact Source branch'):
        audit.portable_binding_inputs(root / 'index.json', requirements)


def test_source_attachment_rejects_forged_transitive_link(source_case, tmp_path):
    from tests.support.source_copy_branch_evidence import write_json
    original, _ = source_case
    root = tmp_path / 'forged-link'
    shutil.copytree(original.parent, root)
    index = json.loads((root / 'index.json').read_bytes())
    attachment = json.loads((root / 'attachment.json').read_bytes())
    proof = json.loads((root / 'proof.json').read_bytes())
    # Re-seal the outer documents, but point a receipt-owned query reply at
    # different intact bytes. A caller-controlled manifest cannot forge ownership.
    receipt = completion.read_sealed_artifact(proof['files'][proof['receipt']['path']], root)
    first, second = receipt['calls'][0]['reply']['path'], receipt['calls'][1]['reply']['path']
    proof['files'][first] = deepcopy(proof['files'][second])
    attachment['proof'] = write_json(root / 'proof.json', proof)
    index['source_attachments'] = [write_json(root / 'attachment.json', attachment)]
    write_json(root / 'index.json', index)
    requirements = json.loads((root / 'requirements.json').read_bytes())
    with pytest.raises(ValueError, match='link digest/size mismatch'):
        audit.portable_binding_inputs(root / 'index.json', requirements)


def test_source_producer_changes_current_candidate_identity(tmp_path):
    # candidate_identity owns this existing source boundary. A new adapter must
    # never be mutable while its program candidate hash remains unchanged.
    names = ('skills/waapi-skill/SKILL.md', 'tests/maintenance/branch_coverage_audit.py',
        'tests/maintenance/branch_audit_completion.py', 'docs/branch-coverage-ownership.json',
        'docs/branch-coverage-condition-sources.json', 'docs/branch-coverage-requirements.json',
        'tests/support/source_copy_branch_evidence.py')
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((audit.ROOT / name).read_bytes())
    before = completion.candidate_identity(tmp_path, {'sources': {}}, {}, digest=audit.digest)
    producer = tmp_path / names[-1]
    producer.write_bytes(producer.read_bytes() + b'\n# changed producer\n')
    after = completion.candidate_identity(tmp_path, {'sources': {}}, {}, digest=audit.digest)
    assert after != before


def test_2025_public_source_chain_retains_crlf_and_explicit_false_leaves(tmp_path, inventory):
    from tests.support.source_copy_branch_evidence import write_source_program_bundle
    with pytest.MonkeyPatch.context() as environment:
        environment.setenv('WWISE_LIVE', '1')
        environment.setenv('WWISE_DESTRUCTIVE', '1')
        workflow = importlib.import_module('tests.destructive.test_gateway_workflow_transaction_matrix')
    (tmp_path / 'public').mkdir()
    runtime, _, _ = modern_collector_runtime(tmp_path / 'public', '2025.1')
    category = workflow._collect_legacy_source_copy_feasibility(runtime, prefix='SOURCE_BRANCH', saved_copy=True,
        saved_copy_protocol='gateway-owned-save-children/v1', fixture_profile=PROFILE)
    receipt = Path(category['observation_path'])
    index = write_source_program_bundle(tmp_path / 'portable', receipt, inventory=inventory,
        nodeid='controlled-source-2025', phase_reports={'setup': 'passed', 'call': 'passed', 'teardown': 'passed'},
        scope_kind='controlled')
    receipt.parent.rename(receipt.parent.with_name(receipt.parent.name + '-unavailable'))
    document, base, projection = audit.portable_binding_inputs(index, json.loads((index.parent / 'requirements.json').read_bytes()))
    assert len(document['bindings']) == 6
    assert projection['source_business_facts'] == ['2025.1|source-copy-synth-owned-graph']
    branches = {row['id']: row for row in inventory['native_coverage']['obligations']}
    for identity, binding in document['bindings'].items():
        assert completion.evidence_result(binding['evidence']['program'], branches[identity],
            inventory['native_coverage']['candidate_sha256'], 'program', 'controlled', base, binding,
            source_root=audit.ROOT, reference_edges={key: row for key, row in branches.items() if row['kind'] == 'reference'}) == ('passed', None)
    proof = json.loads((index.parent / 'proof.json').read_bytes())
    raw = completion.read_sealed_artifact(proof['files'][proof['receipt']['path']], base)
    snapshots = completion.read_sealed_artifact(proof['files'][raw['copied_scalar_observation']['path']], base)
    assert snapshots['rtpc']['values']['PropertyName'] == 'OutputLevel'
    program = completion.read_sealed_artifact(next(iter(document['bindings'].values()))['evidence']['program'], base)
    assert program['native_call']['args']['autoAddToSourceControl'] is False
    assert program['native_call']['args']['autoCheckOutToSourceControl'] is False
    notes = [completion.read_sealed_artifact(proof['files'][call['reply']['path']], base).get('agent_result')
        for call in raw['calls'] if call['argv'][:2] == ['query-object', '--exact-id']]
    source_notes = [row['notes'] for rows in notes if isinstance(rows, list) for row in rows
        if row.get('class_id') == 9699330]
    assert source_notes and all(value.count('\r\n') == 8 for value in source_notes)
    print('portable2025 selected origins/bytes:', len(proof['files']), sum(path.stat().st_size for path in (base / 'facts').iterdir()))


@pytest.mark.parametrize('version,build', [('2023.1', '2023.1.19.8928'), ('2024.1', '2024.1.13.9056')])
def test_intermediate_source_leaves_keep_matching_build_and_explicit_false(inventory, version, build):
    from tests.support.source_copy_branch_evidence import selected_branches
    from tests.destructive.support.source_copy_fixture import source_graph, SOURCE, SOURCE_OWNER
    rows = selected_branches(inventory, version)
    assert len(rows) == 6 and all(row['route'] == f'{version}|wwise-console|{build}|function|ak.wwise.core.object.copy' for row in rows)
    booleans = [row for row in rows if row['pointer'].endswith('/@boolean/false')]
    assert len(booleans) == 2 and all(row['value'] is False for row in booleans)
    original = (audit.ROOT / 'tests/_org' / version / 'Actor-Mixer Hierarchy/MIDI.wwu').read_bytes()
    nodes = source_graph([original], SOURCE, SOURCE_OWNER, version=version)
    assert nodes['source'].find('ObjectLists/ObjectList/Reference/Local/RTPC') is nodes['rtpc']


def test_source_attachment_rejects_consistent_native_points_disagreeing_with_saved_xml(source_case, tmp_path):
    from tests.support.source_copy_branch_evidence import write_json
    original, _ = source_case
    root = tmp_path / 'wrong-points'
    shutil.copytree(original.parent, root)
    proof = json.loads((root / 'proof.json').read_bytes())
    receipt = completion.read_sealed_artifact(proof['files'][proof['receipt']['path']], root)
    def alter(value):
        if isinstance(value, dict):
            if set(value) == {'x', 'y', 'shape'}:
                value['y'] += 0.5
                return True
            changed = [alter(child) for child in value.values()]
            return any(changed)
        if isinstance(value, list):
            changed = [alter(child) for child in value]
            return any(changed)
        return False
    def replace(link, value):
        raw = json.dumps(value, ensure_ascii=False).encode()
        seal = hashlib.sha256(raw).hexdigest()
        name = 'facts/' + seal
        (root / name).write_bytes(raw)
        link.update(sha256=seal, size=len(raw))
        proof['files'][link.get('path', link.get('index_path'))] = {'artifact': name, 'sha256': seal, 'size': len(raw)}
    for call in receipt['calls']:
        if call['argv'][0] != 'query-object': continue
        payload = completion.read_sealed_artifact(proof['files'][call['reply']['path']], root)
        if alter(payload): replace(call['reply'], payload)
    for link in [receipt['fixture_acceptance'][key] for key in ('loaded_scalar_observation', 'scalar_observation')] + [
            receipt[key] for key in ('copied_scalar_observation', 'retained_scalar_observation')]:
        snapshot = completion.read_sealed_artifact(proof['files'][link['path']], root)
        assert alter(snapshot)
        replace(link, snapshot)
    replace(proof['receipt'], receipt)
    attachment = json.loads((root / 'attachment.json').read_bytes())
    attachment['proof'] = write_json(root / 'proof.json', proof)
    index = json.loads((root / 'index.json').read_bytes())
    index['source_attachments'] = [write_json(root / 'attachment.json', attachment)]
    write_json(root / 'index.json', index)
    with pytest.raises(ValueError, match='native/saved Curve points differ'):
        audit.portable_binding_inputs(root / 'index.json', json.loads((root / 'requirements.json').read_bytes()))


def test_default_source_product_requirements_reach_evidence_and_omission_stays_unresolved(source_case):
    index, inventory = source_case
    document, base, _ = audit.portable_binding_inputs(index,
        json.loads((index.parent / 'requirements.json').read_bytes()))
    selected = set(document['bindings'])
    # No controlled scope or requirements override: use the default product file.
    coverage = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base)
    rows = {row['id']: row for row in coverage['obligations'] if row['id'] in selected}
    assert len(rows) == 4
    assert {row['state'] for row in rows.values()} == {'implemented_unverified'}
    assert all(row['requirements'] == ['native', 'program']
        and set(row['evidence_results']) == {'program', 'native'} for row in rows.values())
    # Controlled fake-client evidence cannot become product/native credit.
    assert all(row['evidence_results']['native']['outcome'] == 'missing' for row in rows.values())
    policy = json.loads((audit.ROOT / 'docs/branch-coverage-requirements.json').read_bytes())
    missing = next(iter(document['bindings']))
    del policy['branches'][missing]
    rejected = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    row = next(row for row in rejected['obligations'] if row['id'] == missing)
    assert row['state'] == 'unresolved' and row['requirements'] == [] and row['evidence_results'] == {}
    assert row['reasons'] == ['reviewed exact branch evidence requirements missing or stale']


@pytest.mark.parametrize('version', ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1'))
def test_default_source_product_policy_matches_generated_bundle_requirements(tmp_path, inventory, source_case, version):
    from tests.support.source_copy_branch_evidence import write_source_program_bundle, dependency_review
    if version == '2022.1':
        index, _ = source_case
    else:
        with pytest.MonkeyPatch.context() as environment:
            environment.setenv('WWISE_LIVE', '1'); environment.setenv('WWISE_DESTRUCTIVE', '1')
            workflow = importlib.import_module('tests.destructive.test_gateway_workflow_transaction_matrix')
        public = tmp_path / 'public'; public.mkdir()
        if version == '2021.1':
            from tests.unit.test_source_copy_repeated_fixture import repeated_collector_runtime
            runtime, _, _ = repeated_collector_runtime(public)
            profile = '2021-native-donor-two-properties/v1'
        else:
            runtime, _, _ = modern_collector_runtime(public, version)
            profile = PROFILE
        category = workflow._collect_legacy_source_copy_feasibility(runtime, prefix='SOURCE_POLICY', saved_copy=True,
            saved_copy_protocol='gateway-owned-save-children/v1', fixture_profile=profile)
        index = write_source_program_bundle(tmp_path / 'portable', Path(category['observation_path']),
            inventory=inventory, nodeid='controlled-source-policy-' + version,
            phase_reports=dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), scope_kind='controlled')
    generated = json.loads((index.parent / 'requirements.json').read_bytes())['branches']
    reviewed = {identity: shape for identity, shape in dependency_review()['selected_native_shapes'].items()
                if identity.startswith(version + '|')}
    assert set(generated) == set(reviewed)
    assert len(generated) == (4 if version in ('2021.1', '2022.1') else 6)
    default = json.loads((audit.ROOT / 'docs/branch-coverage-requirements.json').read_bytes())['branches']
    assert {identity: default.get(identity) for identity in reviewed} == generated
    assert all(row['native_shape_sha256'] == reviewed[identity]
        and row['categories'] == ['program', 'native']
        and row['reason'] == 'Exact Source copy leaf and scoped #180 graph fact; separate native evidence required.'
        for identity, row in generated.items())
