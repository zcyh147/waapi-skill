"""Exact #191 correspondence reaches the ordinary completion reader."""
from copy import deepcopy
import json
import pytest
from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance.branch_audit_completion import evaluate_coverage

@pytest.fixture(scope='module')
def core_inventory():
    from tests.support.core_completion_mapping import core_component
    return core_component(audit.ROOT)


def test_core_mapping_keeps_exact_choices_defaults_and_weak_effect_scope(tmp_path, core_inventory):
    from tests.maintenance.map_core_completion import main
    assert main(['--output-directory', str(tmp_path)]) == 2
    published = json.loads((tmp_path / 'assessment.json').read_bytes())
    requirements = audit.load(tmp_path / 'requirements.json')
    bindings, base, _ = audit.portable_binding_inputs(tmp_path / 'evidence-index.json', requirements)
    report = evaluate_coverage(audit.ROOT, core_inventory, bindings, digest=audit.digest,
        evidence_base=base, requirements_document=requirements)
    assert report['completion'] == published['completion']
    assert len({row['uri'] for row in core_inventory['native_coverage']['routes']}) == 19
    assert len(core_inventory['routes']) == 66
    assert len(core_inventory['native_coverage']['routes']) == 132
    assert len(core_inventory['native_coverage']['obligations']) == 5916
    assert {row['state'] for row in report['obligations']} == {'implemented_unverified'}
    assert all(row['requirements'] == ['program'] and 'native' not in row['evidence_results'] for row in report['obligations'])
    mapped = [binding['input']['correspondence'] for binding in bindings['bindings'].values()]
    assert any(m.get('native_choice') == 'DualShelfUsage' and m['public_choices'] == ['dual-shelf'] for m in mapped)
    assert any(m.get('native_choice') == 'HighShelfUsage' and m['public_choices'] == ['high-shelf'] for m in mapped)
    assert any(m.get('native_choice') == 'preserveX' and m['public_choices'] == ['preserve-x'] for m in mapped)
    assert any(m.get('native_choice') == 'addKeep' and m['public_choices'] == ['merge-keep'] for m in mapped)
    assert all(m['native_effect'] == 'not_claimed' for m in mapped)
    assert any(m['rule'] == 'internal_identifier_not_public' for m in mapped)
    assert any(m.get('ordered_assignment_scope') == 'indexed_order_and_stable_fields; Automatic_adjacent_geometry_unverified' for m in mapped)
    assert any(m.get('empty_replacement') is True for m in mapped)
    assert published['summary']['canonical_import_pending'] is True


@pytest.mark.parametrize('damage', ['choice', 'host'])
def test_core_mapping_rejects_missing_native_member(core_inventory, damage):
    from tests.support.core_completion_mapping import core_bindings
    broken = deepcopy(core_inventory)
    broken['native_coverage']['obligations' if damage == 'choice' else 'routes'].pop()
    with pytest.raises(ValueError, match='Core.*roster'):
        core_bindings(audit.ROOT, broken)


def test_core_mapping_rejects_removed_disclosed_curve_choice(core_inventory, monkeypatch):
    import wwise_waapi.core_business_contracts as business
    from tests.support.core_completion_mapping import core_bindings
    original = business.core_business_contract_data
    def missing(operation, version):
        contract = original(operation, version)
        if operation.endswith('setAttenuationCurve'):
            contract['declaration']['value_domains']['curve_kind']['choices'].remove('volume-dry')
        return contract
    monkeypatch.setattr(business, 'core_business_contract_data', missing)
    with pytest.raises(ValueError, match='Core.*public.*volume-dry'):
        core_bindings(audit.ROOT, core_inventory)


def test_core_program_anchor_rejects_missing_finalized_code_proof(tmp_path, core_inventory):
    from tests.support.core_completion_mapping import core_program_anchors
    for name in ('run.plan.json', 'run.result.json', 'run.summary.json'):
        (tmp_path / name).write_text('{}')
    with pytest.raises(ValueError, match='Core selected code anchor is missing or unfinalized'):
        core_program_anchors(audit.ROOT, core_inventory, tmp_path / 'out', tmp_path)


@pytest.mark.parametrize('damage', ['paste', 'blend', 'range'])
def test_core_mapping_rejects_removed_public_mode(core_inventory, monkeypatch, damage):
    import tests.support.core_completion_mapping as mapping
    original = mapping._contract
    def missing(route):
        contract = original(route)
        name = route['uri']
        domains = contract['declaration'].get('value_domains', {})
        if damage == 'paste' and name.endswith('pasteProperties'):
            domains['list_mode']['choices'].remove('merge-keep')
        if damage == 'blend' and name.endswith('blendContainer.addAssignment'):
            domains['edges']['fade_mode_choices'].remove('manual')
        if damage == 'range' and name.endswith('setRange'):
            domains['curve_update_outcome']['choices'].remove('preserve-x')
        return contract
    monkeypatch.setattr(mapping, '_contract', missing)
    with pytest.raises(ValueError, match='Core missing public choice'):
        mapping.core_bindings(audit.ROOT, core_inventory)


def test_core_mapping_missing_source_is_rejected_by_ordinary_reader(tmp_path, core_inventory):
    from tests.support.core_completion_mapping import export_core_mapping
    from tests.maintenance.branch_audit_mapping import read_mapping_attachments
    output = export_core_mapping(audit.ROOT, tmp_path, inventory=core_inventory)
    index = json.loads(output['index_path'].read_bytes())
    attachment = json.loads((tmp_path / index['mapping_attachments'][0]['artifact']).read_bytes())
    requirements = deepcopy(output['requirements'])
    mechanism = attachment['mechanisms'][0]
    construction = next(iter(attachment['bindings'].values()))['construction']['source'].split('#')[0]
    requirements['representative_mechanisms'][mechanism]['sources'].pop(construction)
    attachment['requirements_sha256'] = audit.digest(requirements)
    with pytest.raises(ValueError, match='source closure is incomplete'):
        read_mapping_attachments([{'fixture_only': True}], requirements, lambda _: attachment, audit.ROOT)
