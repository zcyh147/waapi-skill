"""Reviewed native getPropertyInfo result witnesses, independent of the reader.

These literals follow the five pinned native result schemas. They describe read
observations only; a condition's presence proves no activation or write effect.
"""
from copy import deepcopy


def metadata_result_cases(version: str) -> dict[str, dict]:
    base = {"name": "Volume", "type": "Real32"}
    cases = {
        "omitted": {},
        "empty-containers": {"display": {}, "supports": {}, "ui": {}, "restriction": {}, "dependencies": []},
        "empty-ui-objects": {"ui": {"value": {}, "displayAs": {}}},
        "empty-type": {"type": ""},
        "number-false-none": {**base, "audioEngineId": 0, "default": -1.25,
            "display": {"name": "", "group": "", "index": -1},
            "supports": {"unlink": False, "randomizer": False, "rtpc": "None"},
            "ui": {"autoUpdate": False, "dataMeaning": "None",
                "displayAs": {"bitfield": False, "lrMix": False, "musicNote": False, "percentage": False},
                "value": {"decimals": 2, "fine": 0.01, "infinity": -1000, "min": -96.3, "max": 12, "step": 0.1}}},
        "boolean-true-additive-frequency": {**base, "type": "bool", "default": True,
            "display": {"name": "Owned live field", "group": "Mix", "index": 0},
            "supports": {"unlink": True, "randomizer": True, "rtpc": "Additive"},
            "ui": {"autoUpdate": True, "dataMeaning": "Frequency",
                "displayAs": {"bitfield": True, "lrMix": True, "musicNote": True, "percentage": True}}},
        "empty-string-exclusive-decibels": {**base, "type": "String", "default": "",
            "supports": {"rtpc": "Exclusive"}, "ui": {"dataMeaning": "Decibels"}},
        "null-multiplicative-pitch": {**base, "type": "Reference", "audioEngineId": 4294967295, "default": None,
            "supports": {"rtpc": "Multiplicative"}, "ui": {"dataMeaning": "PitchCents"}},
        "default-false": {**base, "type": "bool", "default": False},
        "default-text": {**base, "type": "String", "default": "风声 \\\" quoted"},
        "range": {**base, "restriction": {"type": "range", "min": -96.3, "max": 12}},
        "reference-empty": {**base, "restriction": {"type": "reference", "restrictions": []}},
        "reference-single": {**base, "restriction": {"type": "reference", "restrictions": [{"type": ["Sound"]}]}},
        "reference-multiple": {**base, "restriction": {"type": "reference", "restrictions": [
            {"type": ["Effect", "Bus"]}, {"category": ["Event", "Bus"]},
            {"childOfReference": "OutputBus"}, "mustChildOf", "notNull", "playable"]}},
        "reference-empty-members": {**base, "restriction": {"type": "reference", "restrictions": [
            {"type": []}, {"category": []}, {"childOfReference": ""}]}},
        "reference-empty-strings": {**base, "restriction": {"type": "reference", "restrictions": [
            {"type": [""]}, {"category": [""]}]}},
        "enum-empty": {**base, "restriction": {"type": "enum", "values": []}},
        "enum-empty-object": {**base, "restriction": {"type": "enum", "values": [{}]}},
        "enum-number": {**base, "restriction": {"type": "enum", "values": [{"value": 1, "displayName": ""}]}},
        "enum-booleans": {**base, "type": "bool", "restriction": {"type": "enum", "values": [
            {"value": True, "displayName": "On"}, {"value": False, "displayName": "Off"}]}},
        "dependency-minimal": {**base, "dependencies": [{"type": "override", "action": "", "context": ""}]},
        "dependency-empty-conditions": {**base, "dependencies": [
            {"type": "property", "action": "Enable", "context": "Self", "property": "Mode", "conditions": []}]},
        "dependency-reference-presence": {**base, "dependencies": [
            {"type": "reference", "action": "Enable", "context": "Parent", "property": "OutputBus",
                "conditions": [{"referenceIsSet": True}, {"referenceIsSet": False}]}]},
        "dependency-object-type": {**base, "dependencies": [
            {"type": "objectType", "action": "Show", "context": "Self"}]},
        "dependency-restrictions": {**base, "dependencies": [
            {"type": "property", "action": "Enable", "context": "Self", "property": "Mode", "conditions": [
                {"restriction": {}}, {"restriction": {"type": "range", "min": 0, "max": 10}},
                {"restriction": {"type": "enum", "values": [{"value": 1}]}},
                {"restriction": {"type": "reference", "restrictions": [{"type": ["Bus"]}]}}]}]},
    }
    for name, case in cases.items():
        if name.startswith("reference-"):
            case["type"] = "Reference"
    # Exact pinned schema deltas; these fields/flags do not exist in older lanes.
    if version not in {"2024.1", "2025.1"}:
        for name in ("number-false-none", "boolean-true-additive-frequency"):
            cases[name]["ui"]["displayAs"].pop("percentage")
    if version != "2025.1":
        cases["reference-multiple"]["restriction"]["restrictions"].remove("mustChildOf")
    if version != "2021.1":
        cases["reference-multiple"]["restriction"]["restrictions"][0]["sharedOnlyTypes"] = ["Effect"]
        cases["reference-empty-members"]["restriction"]["restrictions"][0]["sharedOnlyTypes"] = []
        cases["reference-empty-strings"]["restriction"]["restrictions"][0]["sharedOnlyTypes"] = [""]
    if version in {"2024.1", "2025.1"}:
        cases["dependency-master-bus"] = {**base, "dependencies": [
            {"type": "isMasterBus", "action": "Show", "context": "Self", "value": True},
            {"type": "isMasterBus", "action": "Show", "context": "Self", "value": False}]}
    return deepcopy(cases)
