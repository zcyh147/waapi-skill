"""The accepted #192 correspondence reaches the ordinary completion reader."""
from copy import deepcopy
import json
import pytest
from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance.branch_audit_completion import evaluate_coverage


@pytest.fixture(scope='module')
def history_inventory():
    from tests.support.history_completion_mapping import history_component
    return history_component(audit.ROOT)


def test_history_mapping_retains_versioned_owned_lifecycle_and_result_only_scope(tmp_path, history_inventory):
    from tests.maintenance.map_history_completion import main
    assert main(['--output-directory', str(tmp_path)]) == 2
    published = json.loads((tmp_path / 'assessment.json').read_bytes())
    requirements = audit.load(tmp_path / 'requirements.json')
    bindings, base, _ = audit.portable_binding_inputs(tmp_path / 'evidence-index.json', requirements)
    report = evaluate_coverage(audit.ROOT, history_inventory, bindings, digest=audit.digest,
        evidence_base=base, requirements_document=requirements)
    assert report['completion'] == published['completion']
    assert len({row['uri'] for row in history_inventory['native_coverage']['routes']}) == 14
    assert len(history_inventory['routes']) == 49
    assert len(history_inventory['native_coverage']['routes']) == 98
    assert {row['state'] for row in report['obligations']} == {'implemented_unverified'}
    assert all(row['requirements'] == ['program'] and 'native' not in row['evidence_results'] for row in report['obligations'])
    mapped = [binding['input']['correspondence'] for binding in bindings['bindings'].values()]
    assert any(m['rule'] == 'owned_undo_group_lifecycle' and 'display_name' in m['public_fields'] for m in mapped)
    assert any(m.get('cancellation_choices') == {'native-default': {}, 'preserve-changes': {'undo': False}, 'undo-changes': {'undo': True}} for m in mapped)
    assert any(m.get('cancellation_choices') == {'native-default': {}} for m in mapped)
    assert any(m.get('provider_selection') == {'disabled': '', 'provider': 'exact configured provider name'} for m in mapped)
    assert any(m.get('source_file_defaults') == {'usage_scope': 'all', 'recursive': True, 'originals_folder': 'omitted_native_Originals_root'} for m in mapped)
    assert any(m['rule'] == 'empty_native_history_envelope' and m['public_fields'] == ['expectation_receipt', 'history_scope'] for m in mapped)
    assert all(m['native_effect'] == 'not_claimed' for m in mapped)
    assert published['summary']['canonical_import_pending'] is True


@pytest.mark.parametrize('damage', ['choice', 'host'])
def test_history_mapping_rejects_missing_native_member(history_inventory, damage):
    from tests.support.history_completion_mapping import history_bindings
    broken = deepcopy(history_inventory)
    broken['native_coverage']['obligations' if damage == 'choice' else 'routes'].pop()
    with pytest.raises(ValueError, match='History.*roster'):
        history_bindings(audit.ROOT, broken)


def test_history_mapping_rejects_removed_disclosed_usage_output(history_inventory, monkeypatch):
    import wwise_waapi.source_control_business_contracts as business
    from tests.support.history_completion_mapping import history_bindings
    original = business.source_control_business_contract_data
    def missing(operation, version):
        contract = original(operation, version)
        if operation.endswith('getSourceFiles'):
            contract['declaration']['usage_output_choices'].pop('short-id')
        return contract
    monkeypatch.setattr(business, 'source_control_business_contract_data', missing)
    with pytest.raises(ValueError, match='History.*public.*short-id'):
        history_bindings(audit.ROOT, history_inventory)


def test_history_mapping_rejects_removed_private_provider_field(history_inventory, monkeypatch):
    import wwise_waapi.source_control_business_contracts as business
    from tests.support.history_completion_mapping import history_bindings
    original = business.source_control_business_contract_data
    def missing(operation, version):
        contract = original(operation, version)
        if operation.endswith('setProvider'):
            contract['declaration']['provider_profile']['connection_fields'].remove('server')
        return contract
    monkeypatch.setattr(business, 'source_control_business_contract_data', missing)
    with pytest.raises(ValueError, match='History.*public.*server'):
        history_bindings(audit.ROOT, history_inventory)


def test_history_program_anchor_rejects_unfinalized_code_capture(tmp_path, history_inventory):
    from tests.support.history_completion_mapping import history_program_anchors
    for name in ('run.plan.json', 'run.result.json', 'run.summary.json'):
        (tmp_path / name).write_text('{}')
    with pytest.raises(ValueError, match='History selected code anchor is missing or unfinalized'):
        history_program_anchors(audit.ROOT, history_inventory, tmp_path / 'out', tmp_path)


def test_history_mapping_missing_source_is_rejected_by_ordinary_reader(tmp_path, history_inventory):
    from tests.support.history_completion_mapping import export_history_mapping
    from tests.maintenance.branch_audit_mapping import read_mapping_attachments
    output = export_history_mapping(audit.ROOT, tmp_path, inventory=history_inventory)
    index = json.loads(output['index_path'].read_bytes())
    attachment = json.loads((tmp_path / index['mapping_attachments'][0]['artifact']).read_bytes())
    requirements = deepcopy(output['requirements'])
    mechanism = attachment['mechanisms'][0]
    construction = next(iter(attachment['bindings'].values()))['construction']['source'].split('#')[0]
    requirements['representative_mechanisms'][mechanism]['sources'].pop(construction)
    attachment['requirements_sha256'] = audit.digest(requirements)
    with pytest.raises(ValueError, match='source closure is incomplete'):
        read_mapping_attachments([{'fixture_only': True}], requirements, lambda _: attachment, audit.ROOT)
