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
    assert mapping["native_pointer"] == branch["pointer"]
    assert branch["mapping_relation"] == "selector"
    route = next(row for row in inventory["routes"] if row["id"] == branch["route"])
    assert route["public_commands"]


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


def test_finite_and_unfamiliar_schema_alternatives_remain_explicit():
    rows = list(schema_branches({'type': 'object', 'properties': {
        'enabled': {'type': 'boolean', 'default': False},
        'future': {'futureCondition': {'enum': ['left', 'right']}},
        'level': {'type': 'integer', 'minimum': 0, 'maximum': 3}}}))
    assert {r['value'] for r in rows if r['kind'] == 'boolean_value'} == {True, False}
    assert any(r['kind'] == 'empty_object' for r in rows)
    assert any(r['pointer'] == '/properties/future/futureCondition/enum/1' and r['value'] == 'right' for r in rows)
    assert any(r['kind'] == 'constraint' and r['pointer'] == '/properties/level/maximum' and r['value'] == 3 for r in rows)


def test_union_empty_values_have_distinct_branch_identities():
    rows = list(schema_branches({'type': ['object', 'string']}))
    assert len({r['pointer'] for r in rows}) == len(rows)
