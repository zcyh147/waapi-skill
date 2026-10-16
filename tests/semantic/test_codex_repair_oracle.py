from copy import deepcopy

from tests.semantic.support.codex_repair_oracle import assess_repair_state

PARENT = "{11111111-1111-1111-1111-111111111111}"
TARGET = "{22222222-2222-2222-2222-222222222222}"
KEEP = "{33333333-3333-3333-3333-333333333333}"


def snapshot(rows):
    return {"objects": rows, "source_integrity": {"sha256": "a" * 64, "mtime_ns": 42},
            "media": {"untouched.wav": "b" * 64}, "complete": True}


def test_creation_oracle_proves_business_values_and_rejects_unrelated_write():
    before = snapshot({KEEP: {"id": KEEP, "name": "Existing", "properties": {"Min": 0}}})
    after = deepcopy(before)
    after["objects"][TARGET] = {"id": TARGET, "name": "Repair_WindRange", "type": "GameParameter",
        "path": r"\Game Parameters\Default Work Unit\Repair_WindRange", "parent": PARENT,
        "properties": {"Min": -12, "Max": 36, "InitialValue": 7}}
    expected = {"name": "Repair_WindRange", "type": "GameParameter", "parent": PARENT,
                "path": r"\Game Parameters\Default Work Unit\Repair_WindRange",
                "properties": {"Min": -12, "Max": 36, "InitialValue": 7}}
    assert all(assess_repair_state("F3", before, after, target_id=TARGET, expected=expected).values())
    after["objects"][KEEP]["properties"]["Min"] = 1
    assert not assess_repair_state("F3", before, after, target_id=TARGET, expected=expected)["other_objects_unchanged"]


import pytest


@pytest.mark.parametrize("defect", ["wrong_value", "extra_object", "source_changed", "media_changed", "incomplete", "missing_target"])
def test_creation_never_credits_missing_incomplete_or_changed_evidence(defect):
    before = snapshot({KEEP: {"id": KEEP, "name": "Existing"}})
    expected = {"name": "Repair_WindRange", "type": "GameParameter", "parent": PARENT,
                "path": r"\Game Parameters\Default Work Unit\Repair_WindRange",
                "properties": {"Min": -12, "Max": 36, "InitialValue": 7}}
    after = deepcopy(before)
    after["objects"][TARGET] = {"id": TARGET, **deepcopy(expected)}
    if defect == "wrong_value":
        after["objects"][TARGET]["properties"]["InitialValue"] = 8
    elif defect == "extra_object":
        after["objects"][PARENT] = {"id": PARENT}
    elif defect == "source_changed":
        after["source_integrity"]["mtime_ns"] += 1
    elif defect == "media_changed":
        after["media"]["untouched.wav"] = "c" * 64
    elif defect == "incomplete":
        after["complete"] = False
    else:
        del after["objects"][TARGET]
    assert not all(assess_repair_state("F3", before, after, target_id=TARGET, expected=expected).values())


def test_plugin_configuration_preserves_other_properties_and_identity():
    target = {"id": TARGET, "name": "Repair_Metadata_Room", "type": "Effect",
              "parent": PARENT, "path": r"\Effects\Default Work Unit\Repair_Metadata_Room",
              "class_id": 7733251, "properties": {"PreDelay": 0, "RoomSize": 50}}
    before = snapshot({TARGET: target})
    after = deepcopy(before)
    after["objects"][TARGET]["properties"]["PreDelay"] = 24
    expected = {key: target[key] for key in ("name", "type", "parent", "path")}
    expected["properties"] = {"PreDelay": 24}
    assert all(assess_repair_state("F1", before, after, target_id=TARGET, expected=expected).values())
    after["objects"][TARGET]["properties"]["RoomSize"] = 51
    assert not assess_repair_state("F1", before, after, target_id=TARGET, expected=expected)["target_values"]


def test_read_only_state_never_credits_a_write():
    expected = {"name": "Repair_WindVelocity", "type": "GameParameter", "parent": PARENT,
                "path": r"\Game Parameters\Default Work Unit\Repair_WindVelocity",
                "properties": {"Min": -12, "Max": 36, "InitialValue": 7}}
    before = snapshot({TARGET: {"id": TARGET, **deepcopy(expected)}})
    assert all(assess_repair_state("F2", before, deepcopy(before), target_id=TARGET, expected=expected).values())
    after = deepcopy(before)
    after["objects"][TARGET]["notes"] = "unexpected change"
    assert not assess_repair_state("F2", before, after, target_id=TARGET, expected=expected)["target_values"]


def test_shareset_requires_independent_effect_of_the_exact_plugin_class():
    expected = {"name": "Repair_Independent_Room", "type": "Effect", "parent": PARENT,
                "path": r"\Effects\Default Work Unit\Repair_Independent_Room", "class_id": 7733251}
    before = snapshot({KEEP: {"id": KEEP, "name": "Existing"}})
    after = deepcopy(before)
    after["objects"][TARGET] = {"id": TARGET, **expected}
    assert all(assess_repair_state("F4", before, after, target_id=TARGET, expected=expected).values())
    after["objects"][TARGET]["owner"] = KEEP
    assert not assess_repair_state("F4", before, after, target_id=TARGET, expected=expected)["target_identity"]
