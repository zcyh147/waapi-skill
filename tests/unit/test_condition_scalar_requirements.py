"""Review proposals preserve exact members without granting shared native credit."""
from pathlib import Path

from tests.support.condition_scalar_batch import scalar_manifest, scalar_plan
from tests.support import condition_scalar_requirements as requirements


def test_exact_requirements_keep_native_behavior_linkage_and_unknown_applicability():
    plan = scalar_plan(scalar_manifest(Path(__file__).parents[2]))
    proposal = requirements.requirements_proposal(plan)
    assert proposal["review_status"] == "pending"
    assert proposal["coverage_credit"] == "none"
    assert len(proposal["members"]) == 5669
    gain = next(g for g in plan["groups"] if g["version"] == "2025.1" and g["field"] == "GainBand1")
    member = proposal["members"][gain["members"][0]["id"]]
    mechanism = proposal["mechanisms"][member["mechanism_key"]]
    assert member["required_categories"] == ["program", "live_metadata", "native"]
    assert mechanism["signature"]["combined_show_enable"] is True
    assert mechanism["signature"]["recursive_controller_conditions"] is True
    assert mechanism["signature"]["dependent_source_type"] == "Real32"
    assert mechanism["signature"]["controller_comparison_kinds"] == ["boolean", "integer"]
    assert mechanism["existing_native_witness_ids"] == []
    assert mechanism["native_witness_state"] == "missing"
    assert member["native_witness_ids"] == [mechanism["planned_native_witness_id"]]
    assert member["equivalence_review"] == "unreviewed_no_inheritance"
    live = proposal["live_metadata_requirements"][member["live_metadata_key"]]
    assert live["source_class"]["Name"] == "Wwise Parametric EQ"
    assert live["effective_instance_metadata"] == "unobserved"
    assert live["controller_types"] == {"FilterTypeBand1": "int32", "NumBands": "int32", "OnOffBand1": "bool"}
    unknown = next(row for row in proposal["members"].values() if row["mechanism_key"] is None)
    assert unknown["state"] == "unresolved" and unknown["reason"]
    assert all(row["equivalence_review"] == "unreviewed_no_inheritance" for row in proposal["members"].values())


def test_proposed_mechanism_key_preserves_controller_edges_and_own_value_domains():
    from copy import deepcopy
    plan = scalar_plan(scalar_manifest(Path(__file__).parents[2]))
    gain = next(g for g in plan['groups'] if g['version'] == '2025.1' and g['field'] == 'GainBand1')
    def key(group):
        proposal = requirements.requirements_proposal({'groups': [group], 'unresolved': []})
        return next(iter(proposal['mechanisms']))
    original = key(gain)
    changed = deepcopy(gain)
    changed['model']['metadata']['GainBand1']['dependencies'][1]['property'] = 'NumBands'
    assert key(changed) != original
    changed = deepcopy(gain)
    changed['model']['metadata']['FilterTypeBand1']['restriction']['values'].pop()
    assert key(changed) != original
