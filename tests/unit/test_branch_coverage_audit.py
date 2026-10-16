"""Audit through the maintainer generator and its independent source boundary."""
from __future__ import annotations

from tests.maintenance.branch_coverage_audit import schema_branches


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


def test_checker_rejects_removed_branch_mapping_and_shareset_false_completion():
    from copy import deepcopy
    from tests.maintenance.branch_coverage_audit import build_inventory, check_inventory
    inventory = build_inventory()
    assert check_inventory(inventory) == []
    missing = deepcopy(inventory)
    del missing["branches"][0]["mapping"]
    assert "branch ledger differs" in check_inventory(missing)
    dishonest = deepcopy(inventory)
    shareset = next(row for row in dishonest["business_branches"] if row["id"] == "2025.1|independent-effect-shareset")
    shareset["implementation"] = "complete"
    assert "business ledger differs" in check_inventory(dishonest)


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


def test_audit_joins_selector_policy_without_inventing_branch_execution_credit():
    from tests.maintenance.branch_coverage_audit import build_inventory
    inventory = build_inventory()
    assert inventory["summary"]["declared_selector_dispositions"] == 484
    branch = next(row for row in inventory["branches"] if row["route"] == "2025.1|function|ak.wwise.core.object.setReference" and row["pointer"] == "/argsSchema/properties/reference")
    mapping = inventory["mappings"][branch["mapping"]]
    assert mapping["basis"] == "native_surface_policy_selector"
    assert mapping["program_result"] == "not_established_by_source_mapping"
    route = next(row for row in inventory["routes"] if row["id"] == branch["route"])
    assert route["compiler"] != "unknown"
    assert route["public_contracts"]


def test_checker_rejects_lost_enum_union_and_policy_mapping_evidence():
    from copy import deepcopy
    from tests.maintenance.branch_coverage_audit import build_inventory, check_inventory
    inventory = build_inventory()
    for kind in ('enum_value', 'type_variant'):
        changed = deepcopy(inventory)
        branch = next(row for row in changed['branches'] if row['kind'] == kind)
        changed['branches'].remove(branch)
        assert 'branch ledger differs' in check_inventory(changed)
    changed = deepcopy(inventory)
    del changed['mappings'][next(iter(changed['mappings']))]
    assert 'selector mappings differs' in check_inventory(changed)
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


def test_selector_attribution_requires_matching_profile_schema_occurrence():
    from copy import deepcopy
    from tests.maintenance.branch_coverage_audit import build_inventory, check_inventory
    inventory = build_inventory()
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
    assert 'schema occurrences differs' in check_inventory(changed)
