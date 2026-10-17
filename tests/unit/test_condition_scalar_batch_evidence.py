"""Exact installed scalar members are declared before original public witnesses."""
from pathlib import Path
from copy import deepcopy
import json

import pytest

from tests.support import condition_scalar_batch as batch


def test_scalar_manifest_retains_every_exact_source_alternative_and_unknown_receiver():
    manifest = batch.scalar_manifest(Path(__file__).parents[2])
    assert manifest["contract"] == "waapi-skill.condition-scalar-members/v1"
    assert len(manifest["occurrences"]) == 1522
    members = [member for case in manifest["occurrences"] for member in case["members"]]
    assert len(members) == len({m["id"] for m in members}) == 5669
    assert sum(case["receiver"]["kind"] == "Property" for case in manifest["occurrences"]) == 1468
    assert sum(case["receiver"]["kind"] == "Reference" for case in manifest["occurrences"]) == 2
    assert sum(case["receiver"]["kind"] == "inherited-base" for case in manifest["occurrences"]) == 52
    time = next(c for c in manifest["occurrences"] if c["version"] == "2025.1" and c["controller"] == "TimeModLoops")
    assert time["predicate"] == {"kind": "range", "type": "int32", "min": 1, "max": 100}
    assert time["native_applicability"] == "unverified"
    assert time["receiver"]["native_type"] is None
    assert {m["alternative"] for m in time["members"]} == {"condition", "Range/2"}
    assert time["attributes"] == {"Name": "TimeModLoops", "Action": "Enable"}
    assert all(m["shape_sha256"] and m["source_file_sha256"] for m in members)


def test_parent_source_type_and_constraints_are_not_lost_by_dependency_extraction():
    cases = batch.scalar_manifest(Path(__file__).parents[2])["occurrences"]
    prefetch = next(c for c in cases if c["version"] == "2025.1" and c["receiver"]["field"] == "PreFetchLength")
    assert prefetch["receiver"]["source_declared_type"] == "int16"
    assert prefetch["receiver"]["source_default"] == 100
    assert prefetch["receiver"]["source_restriction"] == {"type": "range", "min": 0, "max": 10000}
    assert prefetch["receiver"]["native_type"] is None
    model = batch.scalar_model(prefetch)
    assert model["metadata"]["PreFetchLength"]["type"] == "int16"
    assert model["metadata"]["PreFetchLength"]["restriction"] == {"type": "range", "min": 0, "max": 10000}
    assert model["provenance"]["dependent_type"] == "exact_installed_parent_Property_Type"


def test_unresolved_inherited_or_reference_receiver_cannot_become_a_product_model():
    cases = batch.scalar_manifest(Path(__file__).parents[2])["occurrences"]
    for case in cases:
        if case["receiver"]["kind"] == "Property":
            assert case["receiver"]["source_declared_type"] is not None
        else:
            assert case["receiver"]["source_declared_type"] is None
            with pytest.raises(ValueError, match="separate exact field applicability"):
                batch.scalar_model(case)


def test_field_source_model_retains_all_sibling_enable_conditions():
    cases = batch.scalar_manifest(Path(__file__).parents[2])["occurrences"]
    case = next(c for c in cases if c["version"] == "2025.1" and c["receiver"]["field"] == "GainBand1")
    model = batch.scalar_model(case)
    dependencies = model["metadata"]["GainBand1"]["dependencies"]
    assert {d["property"] for d in dependencies if d["action"] == "Enable"} == {"OnOffBand1", "FilterTypeBand1"}
    assert {d["property"] for d in dependencies if d["action"] == "Show"} == {"NumBands"}
    assert model["before"]["OnOffBand1"] is True
    assert model["before"]["FilterTypeBand1"] in {4, 5, 6}
    assert model["provenance"]["isolated_predicate_only"] is False


def test_recursive_controller_source_metadata_is_not_assumed_terminal():
    cases = batch.scalar_manifest(Path(__file__).parents[2])["occurrences"]
    case = next(c for c in cases if c["version"] == "2025.1" and c["receiver"]["field"] == "GainBand1")
    model = batch.scalar_model(case)
    controller = model["metadata"]["FilterTypeBand1"]
    assert controller["type"] == "int32"
    assert any(d["property"] == "OnOffBand1" and d["action"] == "Enable" for d in controller["dependencies"])
    assert any(d["property"] == "NumBands" and d["action"] == "Show" for d in controller["dependencies"])
    assert model["provenance"]["controller_recursive_metadata"] == "exact_scoped_installed_declarations"


def test_inner_type_declarations_remain_separate_from_object_field_applicability():
    cases = batch.scalar_manifest(Path(__file__).parents[2])["occurrences"]
    case = next(c for c in cases if c["version"] == "2025.1" and c["receiver"]["field"] == "ReplaceFindWhat")
    assert case["receiver"]["source_declared_type"] == "string"
    assert case["receiver"]["source_scope_kind"] == "inner-type-property"
    assert "ReplaceFindWhat" in case["source_scope_fields"]
    with pytest.raises(ValueError, match="inner-type public field applicability"):
        batch.scalar_model(case)


def test_batch_predeclares_each_alternative_at_its_actual_metadata_observation():
    manifest = batch.scalar_manifest(Path(__file__).parents[2])
    plan = batch.scalar_plan(manifest)
    assert plan["credit"] == "none_before_original_observation_and_reviewed_requirements"
    all_ids = [m["id"] for group in plan["groups"] for m in group["members"]]
    all_ids.extend(row["id"] for row in plan["unresolved"])
    assert len(all_ids) == len(set(all_ids)) == 5669
    gain = next(g for g in plan["groups"] if g["version"] == "2025.1" and g["field"] == "GainBand1")
    assert len(gain["members"]) == 8
    true_value = next(m for m in gain["members"] if m["id"].endswith("/Enumeration/2/value/0")
                      and "OnOffBand1" in m["source_attributes"]["Name"])
    assert true_value["observation_pointer"] == "/observations/metadata/dependencies/0/conditions/0/restriction/values/0/value"
    assert true_value["expected"] is True
    assert true_value["source_value"] == "true"
    range_case = next(g for g in plan["groups"] if g["version"] == "2025.1" and g["field"] == "EnvelopeStopPlayback")
    range_shape = next(m for m in range_case["members"] if m["alternative"] == "Range/2")
    assert range_shape["expected"] == {"type": "range", "min": 1, "max": 100}
    assert all(row["reason"] for row in plan["unresolved"])


def test_member_predicate_cannot_be_replaced_by_a_different_same_controller_shape():
    manifest = batch.scalar_manifest(Path(__file__).parents[2])
    case = next(c for c in manifest["occurrences"] if c["version"] == "2025.1" and c["receiver"]["field"] == "GainBand1"
                and c["controller"] == "OnOffBand1")
    case["predicate"]["values"] = [False]
    with pytest.raises(ValueError, match="source predicate differs"):
        batch.scalar_plan(manifest)


def test_enum_values_and_range_bounds_require_distinct_predeclared_behavioral_workflows():
    plan = batch.scalar_plan(batch.scalar_manifest(Path(__file__).parents[2]))
    gain = next(g for g in plan["groups"] if g["version"] == "2025.1" and g["field"] == "GainBand1")
    flows = {flow["id"]: flow for flow in gain["workflows"]}
    values = [m for m in gain["members"] if m["alternative"].startswith("Enumeration/2/value/")
              and m["source_attributes"]["Name"] == "FilterTypeBand1"]
    assert {m["expected"] for m in values} == {4, 5, 6}
    for member in values:
        assert len(member["behavioral_workflow_ids"]) == 1
        flow = flows[member["behavioral_workflow_ids"][0]]
        assert flow["before"]["FilterTypeBand1"] == member["expected"]
        assert flow["before"]["OnOffBand1"] is True
    time = next(g for g in plan["groups"] if g["version"] == "2025.1" and g["field"] == "EnvelopeStopPlayback")
    shape = next(m for m in time["members"] if m["alternative"] == "Range/2")
    flows = {flow["id"]: flow for flow in time["workflows"]}
    assert {flows[i]["before"]["TimeModLoops"] for i in shape["behavioral_workflow_ids"]} == {1, 50, 100}
    assert time["negative_controls"][0]["before"]["TimeModLoops"] == 0
    assert time["negative_controls"][0]["expected_error_code"] == "REFERENCE_ACTIVATION_REQUIRED"


def test_conflicting_sibling_choices_remain_exactly_unresolved_per_source_occurrence():
    # Controlled source fixture: duplicate controller constraints have distinct slots.
    def dependency(values):
        return '<PropertyDependency Name="Mode" Action="Enable"><Condition><Enumeration Type="int32">' + ''.join(
            '<Value>' + str(value) + '</Value>' for value in values) + '</Enumeration></Condition></PropertyDependency>'
    parent = '<Property Name="Gain" Type="Real64"><DefaultValue>0</DefaultValue><Dependencies>' + dependency([4, 5, 6]) + dependency([4, 5]) + '</Dependencies></Property>'
    cases = []
    for index, values in enumerate(([4, 5, 6], [4, 5])):
        identity = 'controlled-source-slot-' + str(index)
        alternatives = [('condition', None), ('Enumeration/2', None), *[
            ('Enumeration/2/value/' + str(i), str(value)) for i, value in enumerate(values)]]
        cases.append({'id': identity, 'version': '2025.1', 'build': '2025.1.7.9143', 'class': None,
            'receiver': {'source_parent_key': 'controlled-parent', 'kind': 'Property', 'field': 'Gain',
                'source_scope_kind': 'source-property', 'source_declared_type': 'Real64', 'source_default': 0.0},
            'source_scope_error': None, 'source_parent_xml': parent, 'source_dependency_index': index,
            'source_scope_fields': {'Gain': parent, 'Mode': '<Property Name="Mode" Type="int32"><DefaultValue>4</DefaultValue></Property>'},
            'attributes': {'Name': 'Mode', 'Action': 'Enable'}, 'controller': 'Mode',
            'predicate': {'kind': 'enum', 'type': 'int32', 'values': values},
            'members': [{'id': identity + '/' + alternative, 'shape_sha256': 'c' * 64,
                'source_file_sha256': 'd' * 64, 'alternative': alternative, 'value': value} for alternative, value in alternatives]})
    plan = batch.scalar_plan({'occurrences': cases})
    members = {m['id']: m for g in plan['groups'] for m in g['members']}
    unresolved = {m['id']: m for m in plan['unresolved']}
    assert 'controlled-source-slot-0/Enumeration/2/value/2' in unresolved
    assert 'controlled-source-slot-0/Enumeration/2' in unresolved
    assert 'controlled-source-slot-1/Enumeration/2' in members
    assert 'conflicts' in unresolved['controlled-source-slot-0/Enumeration/2/value/2']['reason']
    assert len(members) + len(unresolved) == 9


def test_parent_collector_refuses_a_changed_installed_file_before_extracting_its_type(tmp_path):
    from tests.maintenance.condition_parent_sources import collect
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/branch-coverage-condition-sources.json").write_text(json.dumps({"corpora": [{
        "name": "condition", "lanes": [{"build": "2025.1.7.9143",
        "files": [{"path": "WObjects/WObjects.xml", "sha256": "0" * 64}], "rows": [{
            "file": "WObjects/WObjects.xml", "path": "PluginModule/WwiseObject[Sound]/Properties/Property[PreFetchLength]/Dependencies",
            "tag": "PropertyDependency", "attributes": {"Name": "IsStreamingEnabled", "Action": "Enable"},
            "xml": '<PropertyDependency Name="IsStreamingEnabled"><Condition><Enumeration Type="bool"><Value>true</Value></Enumeration></Condition></PropertyDependency>'}]}]}]}))
    path = tmp_path / "installed/Wwise 2025.1.7.9143/Authoring/Data/WObjects/WObjects.xml"
    path.parent.mkdir(parents=True)
    path.write_text('<PluginModule><WwiseObject Name="Sound"><Properties><Property Name="PreFetchLength" Type="bool" /></Properties></WwiseObject></PluginModule>')
    with pytest.raises(ValueError, match="pinned installed source digest mismatch"):
        collect(tmp_path, tmp_path / "installed")


@pytest.mark.parametrize("version,controller", [("2021.1", "LfoWaveform"), ("2022.1", "SystemAudioObjectsPolicy"),
    ("2023.1", "TimeModLoops"), ("2024.1", "IsStreamingEnabled"), ("2025.1", "PreEQBand1FilterType"),
    ("2025.1", "OnOffBand1")])
def test_exact_source_model_runs_the_public_field_workflow(tmp_path, version, controller):
    from tests.unit.test_conditional_reference_gateway import ScalarPropertyTask, FIRST
    from tests.unit.test_time_modulator_range_gateway import finish

    cases = batch.scalar_manifest(Path(__file__).parents[2])["occurrences"]
    case = next(c for c in cases if c["version"] == version and c["controller"] == controller
                and c["receiver"]["kind"] == "Property" and c["receiver"]["field"] != controller)
    model = batch.scalar_model(case)
    task = ScalarPropertyTask(tmp_path, version)
    task.metadata = deepcopy(model["metadata"])
    task.objects[FIRST].update(model["before"])
    target = task.bind(FIRST)
    code, discovered = task.step("draft-discover-fields", "--object-handle", target, "--meaning", model["field"])
    assert code == 0, discovered
    candidate = discovered["meaning_results"][0]["candidates"][0]
    assert candidate["metadata"]["dependencies"] == model["metadata"][model["field"]]["dependencies"]
    code, declared = task.step("draft-declare-field-change", "--object-handle", target,
        "--field-handle", candidate["handle"], "--business-value", json.dumps(model["requested"]))
    assert code == 0, declared
    before = deepcopy(task.objects[FIRST])
    preview, _, verified, _ = finish(task)
    assert not preview["preview_summary"].get("derived_changes"), preview
    assert verified["verified"] is True
    assert task.objects[FIRST] == {**before, model["field"]: model["requested"]}
    writes = [args for uri, args, _ in task.calls if uri.endswith("setProperty")]
    assert writes == [{"object": FIRST, "property": model["field"], "value": model["requested"]}]
    assert model["provenance"]["dependent_type"] == "exact_installed_parent_Property_Type"
