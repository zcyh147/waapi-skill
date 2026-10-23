"""Non-live controls for the bounded existing-EQ native observation oracle."""
from copy import deepcopy
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def collector(monkeypatch):
    monkeypatch.setenv("WWISE_LIVE", "1")
    monkeypatch.setenv("WWISE_DESTRUCTIVE", "1")
    return importlib.import_module("tests.destructive.test_eq_gain_condition")


def test_eq_witness_collects_one_existing_lifecycle_node(collector, request):
    module = pytest.Module.from_parent(request.session, path=Path(collector.__file__))
    items = list(module.collect())
    assert [item.name for item in items] == ["test_existing_eq_gain_preserves_condition_controllers_and_context"]
    assert "workflow_sandbox_runtime" in items[0].fixturenames


def _metadata(collector):
    return {"GainBand1": {"name": "GainBand1", "type": "Real32", "supports": {"unlink": False},
            "restriction": {"type": "range", "min": -24.0, "max": 24.0},
            "dependencies": deepcopy([collector.SHOW, collector.ENABLE, collector.FILTER])},
        "OnOffBand1": {"name": "OnOffBand1", "type": "bool", "supports": {"unlink": False},
            "dependencies": deepcopy([collector.SHOW])},
        "FilterTypeBand1": {"name": "FilterTypeBand1", "type": "int32", "supports": {"unlink": False},
            "restriction": {"type": "enum", "values": [{"value": value} for value in (0, 1, 7, 8, 2, 3, 6, 4, 5)]},
            "dependencies": deepcopy([collector.SHOW, collector.ENABLE])},
        "NumBands": {"name": "NumBands", "type": "int32", "supports": {"unlink": False},
            "restriction": {"type": "range", "min": 1, "max": 8}, "dependencies": []}}


def test_eq_metadata_accepts_native_order_and_labels_without_dropping_siblings(collector):
    info = _metadata(collector)
    for dependency in info["GainBand1"]["dependencies"]:
        for choice in dependency["conditions"][0]["restriction"].get("values", []):
            choice["displayName"] = "native label"
    info["FilterTypeBand1"]["restriction"]["values"].reverse()
    collector._assert_metadata(info)


@pytest.mark.parametrize("fault", ["missing-show", "missing-enable", "recursive-show", "boolean-number", "wrong-kind"])
def test_eq_metadata_rejects_incomplete_or_wrongly_typed_closure(collector, fault):
    info = _metadata(collector)
    if fault == "missing-show":
        info["GainBand1"]["dependencies"].pop(0)
    elif fault == "missing-enable":
        info["GainBand1"]["dependencies"].pop(2)
    elif fault == "recursive-show":
        info["FilterTypeBand1"]["dependencies"].pop(0)
    elif fault == "boolean-number":
        info["GainBand1"]["dependencies"][1]["conditions"][0]["restriction"]["values"][0]["value"] = 1
    else:
        info["FilterTypeBand1"]["type"] = "bool"
    with pytest.raises(AssertionError):
        collector._assert_metadata(info)


def _before(collector):
    target = {"id": collector.TARGET, "name": "Voice_EQ", "type": "Effect", "class_id": collector.CLASS_ID,
        "parent": {"id": collector.PARENT}, "properties": {field: 0.0 for field in collector.FIELDS}}
    target["properties"].update(GainBand1=4.0, FilterTypeBand1=4, NumBands=3, OnOffBand1=True)
    peer = {"id": collector.PEER, "name": "Club_Next_Door", "type": "Effect", "class_id": collector.CLASS_ID,
        "parent": {"id": collector.PARENT}, "properties": {"GainBand1": 0.0}}
    return {"target": target, "peer": peer, "members": [{"id": collector.TARGET}, {"id": collector.PEER}]}


@pytest.mark.parametrize("fault", ["wrong-class", "filter-choice", "disabled", "band-count", "duplicate-member"])
def test_eq_fixture_rejects_unproved_identity_or_controller_prestate(collector, fault):
    before = _before(collector)
    collector._assert_before(before)
    if fault == "wrong-class":
        before["target"]["class_id"] += 1
    elif fault == "filter-choice":
        before["target"]["properties"]["FilterTypeBand1"] = 5
    elif fault == "disabled":
        before["target"]["properties"]["OnOffBand1"] = False
    elif fault == "band-count":
        before["target"]["properties"]["NumBands"] = True
    else:
        before["members"].append(deepcopy(before["members"][0]))
    with pytest.raises(AssertionError):
        collector._assert_before(before)


@pytest.mark.parametrize("fault", ["gain-not-changed", "controller", "other-band", "peer", "membership"])
def test_eq_effect_oracle_rejects_missing_effect_and_extra_changes(collector, fault):
    before = _before(collector)
    after = deepcopy(before)
    after["target"]["properties"]["GainBand1"] = 3.0
    collector._assert_preserved(before, after)
    if fault == "gain-not-changed":
        after["target"]["properties"]["GainBand1"] = 4.0
    elif fault == "controller":
        after["target"]["properties"]["NumBands"] = 4
    elif fault == "other-band":
        after["target"]["properties"]["GainBand3"] = 7.0
    elif fault == "peer":
        after["peer"]["properties"]["GainBand1"] = 1.0
    else:
        after["members"].pop()
    with pytest.raises(AssertionError):
        collector._assert_preserved(before, after)


def test_eq_gain_readback_accepts_numeric_representation_without_relaxing_other_fields(collector):
    before = _before(collector)
    before["target"]["properties"]["GainBand1"] = 4
    collector._assert_before(before)
    after = deepcopy(before)
    after["target"]["properties"]["GainBand1"] = 3
    collector._assert_preserved(before, after)
    after["target"]["properties"]["OnOffBand1"] = 1
    with pytest.raises(AssertionError):
        collector._assert_preserved(before, after)


@pytest.mark.parametrize("fault", ["derived-controller", "wrong-property", "wrong-platform"])
def test_eq_preview_oracle_rejects_hidden_controller_or_wrong_dispatch(collector, fault):
    platform = "{11111111-1111-1111-1111-111111111111}"
    preview = {"preview_summary": {}}
    prepared = {"dispatch": {"uri": "ak.wwise.core.object.setProperty", "options": {},
        "args": {"object": collector.TARGET, "property": "GainBand1", "value": 3.0, "platform": platform}}}
    collector._assert_dispatch(preview, prepared, platform)
    if fault == "derived-controller":
        preview["preview_summary"]["derived_changes"] = [{"field": "FilterTypeBand1", "value": 4}]
    elif fault == "wrong-property":
        prepared["dispatch"]["args"]["property"] = "GainBand3"
    else:
        prepared["dispatch"]["args"]["platform"] = "{22222222-2222-2222-2222-222222222222}"
    with pytest.raises(AssertionError):
        collector._assert_dispatch(preview, prepared, platform)
