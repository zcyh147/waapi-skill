"""Accepted lightweight UI mappings reach the ordinary completion consumer."""
from copy import deepcopy
import json
import hashlib
import pytest
from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance.branch_audit_completion import evaluate_coverage

@pytest.fixture(scope='module')
def ui_inventory():
    from tests.support.ui_completion_mapping import ui_component
    return ui_component(audit.ROOT)


def test_ui_cohort_maps_exact_sources_without_manufacturing_effect_proof(tmp_path, ui_inventory):
    from tests.maintenance.map_ui_completion import main
    assert main(['--output-directory', str(tmp_path)]) == 2
    published = json.loads((tmp_path / 'assessment.json').read_bytes())
    summary = published['summary']
    requirements = audit.load(tmp_path / 'requirements.json')
    bindings, base, _ = audit.portable_binding_inputs(tmp_path / 'evidence-index.json', requirements)
    report = evaluate_coverage(audit.ROOT, ui_inventory, bindings, digest=audit.digest,
        evidence_base=base, requirements_document=requirements)
    assert report['completion'] == published['completion']
    assert len(ui_inventory['routes']) == len(ui_inventory['native_coverage']['routes']) == 48
    assert {row['state'] for row in report['obligations']} == {'implemented_unverified'}
    assert all(row['requirements'] == ['program'] and 'native' not in row['evidence_results'] for row in report['obligations'])
    assert summary['native_effect_credit'] is False
    assert summary['requirements_parts']
    assert set(bindings['bindings']) == {row['id'] for row in ui_inventory['native_coverage']['obligations']}
    mapped = [b['input']['correspondence'] for b in bindings['bindings'].values()]
    assert any('blueprint.nodes[].orientation' in m['public_fields'] and m.get('native_choice') == 'Horizontal' for m in mapped)
    assert any(m['rule'] == 'accepted_unresolved_native_definition' for m in mapped)
    assert any('registration_medium' in m['public_fields'] for m in mapped)
    assert all(m['native_effect'] == 'not_claimed' for m in mapped)


@pytest.mark.parametrize('damage', ['choice', 'host'])
def test_ui_mapping_rejects_missing_native_member(ui_inventory, damage):
    from tests.support.ui_completion_mapping import ui_bindings
    broken = deepcopy(ui_inventory)
    broken['native_coverage']['obligations' if damage == 'choice' else 'routes'].pop()
    with pytest.raises(ValueError, match='UI mapping.*roster'):
        ui_bindings(audit.ROOT, broken)


@pytest.mark.parametrize('damage', ['catalog', 'schema'])
def test_ui_mapping_rejects_removed_public_constructor_choice(ui_inventory, monkeypatch, damage):
    import wwise_waapi.authoring_model_business as business
    from tests.support.ui_completion_mapping import ui_bindings
    original = business.model_business_contract
    def missing(operation, version):
        contract = original(operation, version)
        if operation.endswith('registerWafm'):
            if damage == 'catalog': contract['construction']['widget_kinds'].pop('PushButton')
            else: contract['declaration']['schema']['properties']['widgets']['items']['properties']['kind']['enum'].remove('PushButton')
        return contract
    monkeypatch.setattr(business, 'model_business_contract', missing)
    with pytest.raises(ValueError, match='UI.*public.*PushButton'):
        ui_bindings(audit.ROOT, ui_inventory)


def test_ui_mapping_missing_source_is_rejected_by_ordinary_reader(tmp_path, ui_inventory):
    from tests.support.ui_completion_mapping import export_mapping
    exported = export_mapping(audit.ROOT, tmp_path, inventory=ui_inventory)
    requirements = deepcopy(exported['requirements'])
    mechanism = next(iter(requirements['representative_mechanisms'].values()))
    mechanism['sources'].pop('skills/waapi-skill/wwise_waapi/authoring_layout_business.py')
    index = json.loads(exported['index_path'].read_bytes())
    for descriptor in index['mapping_attachments']:
        path = tmp_path / descriptor['artifact']
        attachment = json.loads(path.read_bytes())
        attachment['requirements_sha256'] = audit.digest(requirements)
        path.write_text(json.dumps(attachment))
        descriptor['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    exported['index_path'].write_text(json.dumps(index))
    with pytest.raises(ValueError, match='source closure is incomplete'):
        audit.portable_binding_inputs(exported['index_path'], requirements)


def test_ui_program_anchor_rejects_unfinalized_code_capture(tmp_path, ui_inventory):
    from tests.support.ui_completion_mapping import program_anchors
    for name in ('run.plan.json', 'run.result.json', 'run.summary.json'):
        (tmp_path / name).write_text('{}')
    with pytest.raises(ValueError, match='UI selected code anchor is missing or unfinalized'):
        program_anchors(audit.ROOT, ui_inventory, tmp_path / 'out', tmp_path)
