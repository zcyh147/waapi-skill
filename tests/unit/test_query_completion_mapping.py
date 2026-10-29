"""Owner #181 correspondence through the ordinary attachment/completion reader."""
from copy import deepcopy
import pytest
from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance.branch_audit_completion import evaluate_coverage

@pytest.fixture(scope='module')
def query_inventory():
    from tests.support.query_completion_mapping import query_component
    return query_component(audit.ROOT)


def test_query_export_reaches_completion_without_inventing_missing_proof(tmp_path, query_inventory):
    from tests.support.query_completion_mapping import export_mapping
    exported = export_mapping(audit.ROOT, tmp_path, inventory=query_inventory)
    requirements = audit.load(exported['requirements_path'])
    assert requirements == exported['requirements']
    bindings, base, _ = audit.portable_binding_inputs(exported['index_path'], requirements)
    result = evaluate_coverage(audit.ROOT, query_inventory, bindings, digest=audit.digest,
        evidence_base=base, requirements_document=exported['requirements'])
    assert set(bindings['bindings']) == {r['id'] for r in query_inventory['native_coverage']['obligations']}
    assert result['completion']['complete'] is False
    assert {r['state'] for r in result['obligations']} == {'implemented_unverified'}
    assert all('native' not in r['evidence_results'] for r in result['obligations'])
    assert exported['summary']['mapping_is_not_execution_credit'] is True
    assert len(exported['summary']['requirements_parts']) == 5
    assert max(p.stat().st_size for p in tmp_path.rglob('*.json')) < 100 * 1024 * 1024


@pytest.mark.parametrize('damage', ['choice', 'route'])
def test_query_mapping_rejects_missing_source_member(query_inventory, damage):
    from tests.support.query_completion_mapping import query_bindings
    broken = deepcopy(query_inventory)
    key = 'obligations' if damage == 'choice' else 'routes'
    broken['native_coverage'][key].pop()
    with pytest.raises(ValueError, match='Query mapping.*roster'):
        query_bindings(audit.ROOT, broken)


def test_query_mapping_rejects_removed_declared_choice(query_inventory, monkeypatch):
    import wwise_waapi.object_query_outputs as outputs
    from tests.support.query_completion_mapping import query_bindings
    original = outputs.available_query_outputs
    def removed(version):
        return {k: v for k, v in original(version).items() if k != 'suppportsRandomizer'}
    monkeypatch.setattr(outputs, 'available_query_outputs', removed)
    with pytest.raises(ValueError, match='return choice.*suppportsRandomizer'):
        query_bindings(audit.ROOT, query_inventory)


def test_query_mapping_rejects_removed_public_metadata_selection(query_inventory, monkeypatch):
    from tests.maintenance.interface_depth_inventory import _gateway_subparsers
    from tests.support.query_completion_mapping import query_bindings
    parser = _gateway_subparsers()['metadata']
    selection = next(action for action in parser._actions if '--selection' in action.option_strings)
    monkeypatch.setattr(selection, 'option_strings', [])
    with pytest.raises(ValueError, match='public input.*metadata.*selection'):
        query_bindings(audit.ROOT, query_inventory)


def test_query_shared_definitions_keep_exact_return_scope_and_nested_projection_paths(query_inventory):
    from tests.support.query_completion_mapping import query_bindings
    bindings = query_bindings(audit.ROOT, query_inventory)
    prefix = '2025.1|wwise-console|2025.1.7.9143|function|ak.wwise.core.object.get|'
    platform = bindings[prefix + '/optionsSchema/@definition/waapi_definitions.json/definitions/objectReturnOptions/properties/platform']
    assert platform['input']['correspondence']['native_paths'] == [['platform']]
    assert platform['input']['correspondence']['public_inputs'] == ['--platform']
    typo = next(row for key, row in bindings.items() if key.startswith(prefix + '/optionsSchema/') and row['input']['correspondence'].get('native_choice') == 'suppportsRandomizer')
    assert typo['input']['correspondence']['public_choices'] == ['suppportsRandomizer']
    assert typo['input']['correspondence']['native_paths'] == [['return', '*']]
    legacy = next(row for key, row in bindings.items() if key.startswith(prefix + '/optionsSchema/') and row['input']['correspondence'].get('native_choice') == 'sound:originalWavFilePath')
    assert legacy['input']['correspondence']['public_choices'] == ['sound:originalWavFilePath']


def test_query_program_anchor_rejects_missing_finalization(query_inventory, tmp_path):
    import json
    from tests.support.query_completion_mapping import program_anchors
    review = tmp_path / 'review.json'
    review.write_text(json.dumps({'record': {'contract': 'waapi-skill.ordinary-test-run-attachment/v1',
        'scope_kind': 'product', 'files': {}}, 'selected_tests': ['unobserved']}))
    with pytest.raises(ValueError, match='original finalized ordinary run'):
        program_anchors(audit.ROOT, query_inventory, tmp_path / 'output', review)
