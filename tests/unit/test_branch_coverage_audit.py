"""Audit through the maintainer generator and its independent source boundary."""
from __future__ import annotations

import pytest

from tests.maintenance.branch_coverage_audit import schema_branches


@pytest.fixture(scope="module")
def frozen_inventory():
    from tests.maintenance.branch_coverage_audit import build_inventory
    return build_inventory()


def test_schema_inventory_retains_optional_enum_union_and_nested_collection_branches():
    schema = {"type": "object", "properties": {
        "mode": {"enum": ["create", "replace"]},
        "children": {"type": "array", "items": {"oneOf": [
            {"type": "string"}, {"type": "integer"}]}}
    }, "required": ["children"]}
    branches = {row["pointer"]: row for row in schema_branches(schema)}
    assert branches["/properties/mode/enum/1"]["value"] == "replace"
    assert branches["/properties/mode/@presence/absent"]["value"] == "absent"
    assert "/properties/children/@presence/absent" not in branches
    assert branches["/properties/children/items/oneOf/1"]["value"] == {"type": "integer"}


def test_independent_reflection_rejects_same_count_route_substitution():
    import json
    import pytest
    from tests.maintenance.branch_coverage_audit import ROOT, build_inventory
    surface = json.loads((ROOT / "skills/waapi-skill/resources/manifest/typed-request-surface.json").read_text())
    surface["lanes"][0]["uri"] = "ak.wwise.invented.sameCount"
    with pytest.raises(ValueError, match="route partition mismatch"):
        build_inventory(surface=surface)


def test_checker_rejects_removed_branch_mapping_and_shareset_false_completion(frozen_inventory):
    from copy import deepcopy
    from tests.maintenance.branch_coverage_audit import build_inventory, check_inventory
    inventory = frozen_inventory
    assert check_inventory(inventory, expected=frozen_inventory) == []
    missing = deepcopy(inventory)
    del missing["branches"][0]["mapping"]
    assert "branch ledger differs" in check_inventory(missing, expected=frozen_inventory)
    dishonest = deepcopy(inventory)
    shareset = next(row for row in dishonest["business_branches"] if row["id"] == "2025.1|independent-effect-shareset")
    shareset["implementation"] = "complete"
    assert "business ledger differs" in check_inventory(dishonest, expected=frozen_inventory)


def test_cli_distinguishes_reproducible_inventory_from_complete_coverage(tmp_path):
    import subprocess
    import sys
    from tests.maintenance.branch_coverage_audit import ROOT
    path = tmp_path / "audit.json"
    command = [sys.executable, str(ROOT / "tests/maintenance/branch_coverage_audit.py"), "--output", str(path)]
    generated = subprocess.run(command, capture_output=True, text=True)
    assert generated.returncode == 0, generated.stderr
    checked = subprocess.run(command + ["--check", "--require-complete"], capture_output=True, text=True)
    assert checked.returncode == 2, checked.stderr
    assert '"business_coverage": "incomplete"' in checked.stdout
    path.write_text('{"contract":"waapi-skill.branch-audit/v1"}')
    damaged = subprocess.run(command + ["--check"], capture_output=True, text=True)
    assert damaged.returncode == 1
    assert "branch ledger differs" in damaged.stdout


def test_schema_type_unions_and_unfamiliar_nested_keywords_cannot_disappear():
    branches = {row["pointer"]: row for row in schema_branches({
        "type": ["string", "null"], "futureBranch": {"enum": ["new"]}})}
    assert branches["/type/1"]["value"] == "null"
    assert branches["/futureBranch"]["kind"] == "unreviewed_keyword"


def test_audit_joins_selector_policy_without_inventing_branch_execution_credit(frozen_inventory):
    from tests.maintenance.branch_coverage_audit import build_inventory
    inventory = frozen_inventory
    assert inventory["summary"]["declared_selector_dispositions"] == 484
    branch = next(row for row in inventory["branches"] if row["route"] == "2025.1|function|ak.wwise.core.object.setReference" and row["pointer"] == "/argsSchema/properties/reference")
    mapping = inventory["mappings"][branch["mapping"]]
    assert mapping["basis"] == "native_surface_policy_selector"
    assert mapping["program_result"] == "not_established_by_source_mapping"
    route = next(row for row in inventory["routes"] if row["id"] == branch["route"])
    assert route["compiler"] != "unknown"
    assert route["public_contracts"]


def test_checker_rejects_lost_enum_union_and_policy_mapping_evidence(frozen_inventory):
    from copy import deepcopy
    from tests.maintenance.branch_coverage_audit import build_inventory, check_inventory
    inventory = frozen_inventory
    for kind in ('enum_value', 'type_variant'):
        changed = deepcopy(inventory)
        branch = next(row for row in changed['branches'] if row['kind'] == kind)
        changed['branches'].remove(branch)
        assert 'branch ledger differs' in check_inventory(changed, expected=frozen_inventory)
    changed = deepcopy(inventory)
    del changed['mappings'][next(iter(changed['mappings']))]
    assert 'selector mappings differs' in check_inventory(changed, expected=frozen_inventory)
    native_changed = deepcopy(inventory)
    native_enum = next(r for r in native_changed['native_coverage']['obligations'] if r['kind'] == 'enum_value')
    native_changed['native_coverage']['obligations'].remove(native_enum)
    assert 'native coverage differs' in check_inventory(native_changed, expected=frozen_inventory)

    assert inventory['current_business_branches'] != inventory['business_branches']
    assert all(row['residual_group'] in inventory['residual_groups'] for row in inventory['branches'])


def test_generator_rejects_policy_with_a_missing_selector():
    import json
    import pytest
    from tests.maintenance.branch_coverage_audit import ROOT, build_inventory
    policy = json.loads((ROOT / 'skills/waapi-skill/resources/native_surface_policy.json').read_text())
    classifications = policy['rules'][0]['scopes'][0]['classifications']
    selectors = next(value for value in classifications.values() if value)
    selectors.pop()
    with pytest.raises(ValueError):
        build_inventory(native_policy=policy)


def test_selector_attribution_requires_matching_profile_schema_occurrence(frozen_inventory):
    from copy import deepcopy
    from tests.maintenance.branch_coverage_audit import build_inventory, check_inventory
    inventory = frozen_inventory
    assert any(branch['mapping'] in inventory['mappings'] for branch in inventory['branches'])
    for branch in inventory['branches']:
        if branch['mapping'] not in inventory['mappings']:
            continue
        version, source, uri, _ = branch['id'].split('|', 3)
        occurrence = '|'.join((version, source, uri))
        expected = inventory['mappings'][branch['mapping']]['schema_sha256_by_version'][version]
        assert inventory['schema_occurrences'][occurrence] == expected
    changed = deepcopy(inventory)
    occurrence = next(iter(changed['schema_occurrences']))
    changed['schema_occurrences'][occurrence] = '0' * 64
    assert 'schema occurrences differs' in check_inventory(changed, expected=frozen_inventory)


def test_native_denominator_keeps_unimplemented_authoring_routes_and_exact_builds(frozen_inventory):
    from tests.maintenance.branch_coverage_audit import build_inventory
    inventory = frozen_inventory
    native = inventory['native_coverage']
    assert len(native['catalogs']) == 10
    row = next(r for r in native['routes'] if r['version'] == '2025.1'
               and r['host'] == 'wwise-authoring'
               and r['uri'] == 'ak.wwise.ui.layout.getLayoutNames')
    assert row['build'] == '2025.1.7.9143'
    assert row['public_route'] is None
    obligations = [r for r in native['obligations'] if r['route'] == row['id']]
    assert obligations and all(r['owner_issue'] == 188 for r in obligations)
    assert all(r['state'] == 'missing_implementation' for r in obligations)
    assert native['completion']['complete'] is False


def test_native_reference_graph_retains_capital_oneof_and_recursive_result_edges(frozen_inventory):
    from tests.maintenance.branch_coverage_audit import build_inventory
    native = frozen_inventory['native_coverage']
    layout = [r for r in native['obligations'] if '2025.1|wwise-authoring|' in r['id']
              and '|ak.wwise.ui.layout.getLayout|' in r['id']]
    assert any('/definitions/Element/OneOf/4' in r['pointer'] for r in layout)
    assert any(r['kind'] == 'reference' and r['reference']['recursive'] for r in layout)
    assert all(r['owner_issue'] == 188 for r in layout)
    assert any(r['kind'] == 'collection_cardinality' and r['value'] == 'empty' for r in layout)
    alternatives = list(schema_branches({'type': ['array', 'null'], 'default': [], 'items': {'OneOf': [{'enum': ['a', 'b']}, {'type': 'integer'}]}}))
    assert any(r['kind'] == 'default' and r['value'] == [] for r in alternatives)
    assert any(r['pointer'] == '/items/OneOf/0/enum/1' and r['value'] == 'b' for r in alternatives)


def test_installed_conditions_keep_existing_new_and_plugin_placement_obligations(frozen_inventory):
    from tests.maintenance.branch_coverage_audit import build_inventory
    native = frozen_inventory['native_coverage']
    conditions = [r for r in native['obligations'] if r['kind'] == 'metadata_condition']
    assert conditions
    sample = [r for r in conditions if 'LfoSmoothing' in r['pointer']]
    assert {r['owner_issue'] for r in sample} == {177, 178}
    assert {r['business_dimensions']['operation_mode'] for r in sample} == {'existing-object', 'new-object'}
    assert all(r['source_evidence_kind'] == 'installed_definition_only' and r['state'] == 'unresolved' for r in conditions)
    plugins = [r for r in native['obligations'] if r['kind'] == 'plugin_topology'
               and r['business_dimensions']['class_name'] == 'Wwise RoomVerb']
    assert {r['business_dimensions']['placement'] for r in plugins} == {'owner-local-effect', 'independent-shareset'}
    assert all(r['owner_issue'] == 179 for r in plugins)
    assert all(r['owner_issue'] in range(177, 194) for r in native['obligations'])


def test_existing_plugin_condition_grammar_does_not_depend_on_plugin_creation(frozen_inventory):
    from tests.maintenance.branch_coverage_audit import ROOT, load
    rows = frozen_inventory['native_coverage']['obligations']
    original = load(ROOT / 'docs/branch-coverage-inventory.json')['native_coverage']['obligations']
    # Changing dependency scheduling must retain the independently enumerated
    # denominator, exact ownership, and unresolved proof obligations.
    assert {(r['id'], r['owner_issue']) for r in rows} == {(r['id'], r['owner_issue']) for r in original}
    for version in ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1'):
        plugin_conditions = [r for r in rows if r['kind'] == 'metadata_condition'
                             and r.get('version') == version and '|plugin-condition|' in r['id']]
        existing = [r for r in plugin_conditions if r['business_dimensions']['operation_mode'] == 'existing-object']
        new = [r for r in plugin_conditions if r['business_dimensions']['operation_mode'] == 'new-object']
        assert existing and new
        assert all(r['owner_issue'] == 177 and r['dependencies'] == [] for r in existing)
        assert all(r['owner_issue'] == 178 and r['dependencies'] == [177, 179] for r in new)
        topology = [r for r in rows if r['kind'] == 'plugin_topology' and r.get('version') == version]
        assert topology and all(r['owner_issue'] == 179 and r['dependencies'] == [177, 178] for r in topology)
    assert all(r['state'] == 'unresolved' and not r['requirements']
               for r in rows if r['kind'] == 'metadata_condition')


def test_finite_and_unfamiliar_schema_alternatives_remain_explicit():
    rows = list(schema_branches({'type': 'object', 'properties': {
        'enabled': {'type': 'boolean', 'default': False},
        'future': {'futureCondition': {'enum': ['left', 'right']}},
        'level': {'type': 'integer', 'minimum': 0, 'maximum': 3}}}))
    assert {r['value'] for r in rows if r['kind'] == 'boolean_value'} == {True, False}
    assert any(r['kind'] == 'empty_object' for r in rows)
    assert any(r['pointer'] == '/properties/future/futureCondition/enum/1' and r['value'] == 'right' for r in rows)
    assert any(r['kind'] == 'constraint' and r['pointer'] == '/properties/level/maximum' and r['value'] == 3 for r in rows)


def test_target_applicability_does_not_inherit_create_or_edit_family_completion(frozen_inventory):
    from tests.maintenance.branch_coverage_audit import build_inventory
    rows = [r for r in frozen_inventory['native_coverage']['obligations'] if r['kind'] == 'target_applicability'
            and r['version'] == '2025.1' and r['business_dimensions']['class_name'] == 'GameParameter']
    assert {r['business_dimensions']['operation_mode'] for r in rows} == {'new-object', 'existing-object'}
    assert all(r['state'] == 'unresolved' for r in rows)
    assert {r['owner_issue'] for r in rows} == {178, 180}


def test_union_empty_values_have_distinct_branch_identities():
    rows = list(schema_branches({'type': ['object', 'string']}))
    assert len({r['pointer'] for r in rows}) == len(rows)


def test_cli_preserves_all_native_rows_in_a_sealed_companion(tmp_path, capsys):
    import json
    from tests.maintenance.branch_coverage_audit import main, load
    target = tmp_path / 'ledger.json'
    assert main(['--output', str(target), '--require-complete']) == 2
    raw = json.loads(target.read_text())
    descriptor = raw['native_coverage']['obligations_artifact']
    hydrated = load(target)
    assert len(hydrated['native_coverage']['obligations']) == descriptor['rows']
    assert len({r['id'] for r in hydrated['native_coverage']['obligations']}) == descriptor['rows']
    assert main(['--output', str(target), '--check', '--require-complete']) == 2
    artifact = target.parent / descriptor['path']
    artifact.write_bytes(artifact.read_bytes()[:-1])
    assert main(['--output', str(target), '--check']) == 1
    assert 'digest mismatch' in capsys.readouterr().out
