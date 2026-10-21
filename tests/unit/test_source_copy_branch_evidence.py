"""Source facts enter the existing branch reader through a closed portable proof."""
from copy import deepcopy
import json
import importlib
import shutil
from pathlib import Path

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.unit.test_source_copy_modern_collector import modern_collector_runtime, PROFILE


@pytest.fixture(scope='module')
def source_case(tmp_path_factory):
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
    inventory = audit.build_inventory()
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
