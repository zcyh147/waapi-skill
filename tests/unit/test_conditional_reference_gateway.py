"""Public attenuation activation from the recorded live dependency shape."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.unit.test_field_interface_closure_gateway import FieldTask, FIRST, SECOND, VERSIONS, gateway


def condition(name="ListenerRelativeRouting", value=True):
    return {"action": "Enable", "conditions": [{"restriction": {"type": "enum", "values": [{"displayName": "True" if value else "False", "value": value}]}}],
            "context": "Self", "property": name, "type": "property"}


class AttenuationTask(FieldTask):
    def __init__(self, path, version, kind="Sound", operation="object.set"):
        super().__init__(path, version, operation)
        self.operation = operation
        self.objects = {
            FIRST: {"id": FIRST, "name": "Rain", "type": kind, "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Rain", "parent": {"id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"}, "notes": "preserve",
                    "Attenuation": None, "ListenerRelativeRouting": False, "OverridePositioning": False, "Volume": -7.0, "@RandomOrSequence": 0},
            SECOND: {"id": SECOND, "name": "Near", "type": "Attenuation", "path": r"\Attenuations\Default Work Unit\Near"},
        }
        self.metadata = {
            "Attenuation": {"name": "Attenuation", "type": "", "restriction": {"type": "reference", "restrictions": [{"sharedOnlyTypes": [], "type": ["Attenuation"]}]},
                            "dependencies": [condition(), condition(), {"action": "Enable", "context": "Self", "property": "OverridePositioning", "type": "override"}]},
            "ListenerRelativeRouting": {"name": "ListenerRelativeRouting", "type": "bool", "default": True},
            "OverridePositioning": {"name": "OverridePositioning", "type": "bool", "default": False},
        }
        self.types = [{"classId": i + 1, "name": name, "type": "WObject"} for i, name in enumerate(("Sound", "RandomSequenceContainer", "Attenuation"))]

    def call(self, uri, args=None, options=None):
        if uri == "ak.wwise.core.object.get" and args.get("transform"):
            self.calls.append((uri, args, options))
            return {"return": []}
        if uri == "ak.wwise.core.object.isPropertyEnabled":
            self.calls.append((uri, deepcopy(args), options))
            return {"return": False}
        if uri == "ak.wwise.core.object.setProperty":
            self.calls.append((uri, deepcopy(args), options))
            self.objects[args["object"]][args["property"]] = args["value"]
            return {}
        if uri == "ak.wwise.core.object.setReference":
            self.calls.append((uri, deepcopy(args), options))
            self.objects[args["object"]][args["reference"]] = {"id": args["value"]}
            return {}
        if uri == "ak.wwise.core.object.set":
            self.calls.append((uri, deepcopy(args), options))
            for row in args["objects"]:
                for key, value in row.items():
                    if key.startswith("@"):
                        is_reference = self.metadata.get(key[1:], {}).get("restriction", {}).get("type") == "reference"
                        self.objects[row["object"]][key[1:]] = {"id": value} if is_reference else value
            return {"objects": [{"id": FIRST, "name": self.objects[FIRST]["name"], "type": self.objects[FIRST]["type"]}]}
        result = super().call(uri, args, options)
        return deepcopy(result)

    def declare(self):
        source, target = self.bind(FIRST), self.bind(SECOND)
        field = self.discover(source, "Attenuation")
        if self.operation == "object.setReference":
            code, payload = self.step("draft-declare-field-change", "--object-handle", source,
                                      "--field-handle", field, "--target-handle", target)
            assert code == 0, payload
            return
        code, payload = self.step("draft-declare-existing", "--object-handle", source,
                                   "--declaration-id", "attenuation", "--field-value", field, target)
        assert code == 0, payload


@pytest.mark.parametrize("version", VERSIONS[1:])
@pytest.mark.parametrize("kind", ["Sound", "RandomSequenceContainer"])
def test_conditional_attenuation_dependencies_are_previewed_and_verified(tmp_path: Path, version: str, kind: str):
    task = AttenuationTask(tmp_path, version, kind)
    task.metadata["Attenuation"]["dependencies"].insert(0, {
        "type": "isMasterBus", "value": False, "action": "Show", "context": "Self"})
    override = {"type": "override", "action": "Enable", "property": "OverridePositioning", "context": "Self"}
    task.metadata["ListenerRelativeRouting"]["dependencies"] = [override]
    task.metadata["OverridePositioning"]["dependencies"] = [override]
    task.declare()
    code, checked = task.step("draft-check")
    assert code == 0, json.dumps(checked)
    code, preview = task.step("preview-from-draft")
    assert code == 0, json.dumps(preview)
    changes = preview["preview_summary"]["derived_changes"]
    assert {row["field"]: row["value"] for row in changes} == {
        "ListenerRelativeRouting": True, "OverridePositioning": True}
    assert all(row["object_id"] == FIRST and "Attenuation" in row["activates_references"] for row in changes)
    assert list(preview)[-1] == "agent_result"
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    dispatch = shown["artifact"]["prepared_operation"]["dispatch"]["args"]["objects"][0]
    assert dispatch["@Attenuation"] == SECOND
    assert dispatch["@ListenerRelativeRouting"] is True
    assert dispatch["@OverridePositioning"] is True
    assert task.objects[FIRST]["ListenerRelativeRouting"] is False
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    code, executed = task.run("execute", tx)
    assert code == 0, json.dumps(executed)
    code, verified = task.run("verify", tx)
    assert code == 0 and verified["verified"] is True, json.dumps(verified)
    assert task.objects[FIRST]["Attenuation"] == {"id": SECOND}
    assert task.objects[FIRST]["ListenerRelativeRouting"] is True
    assert task.objects[FIRST]["OverridePositioning"] is True
    assert task.objects[FIRST]["Volume"] == -7
    assert task.objects[FIRST]["notes"] == "preserve"
    writes = [args for uri, args, _ in task.calls if uri == "ak.wwise.core.object.set"]
    assert len(writes) == 1
    assert writes[0]["objects"][0]["@ListenerRelativeRouting"] is True


def test_recursive_activation_is_included_in_same_preview(tmp_path: Path):
    task = AttenuationTask(tmp_path, "2025.1")
    task.metadata["ListenerRelativeRouting"]["dependencies"] = [condition("RoutingPrerequisite")]
    task.metadata["RoutingPrerequisite"] = {"name": "RoutingPrerequisite", "type": "bool"}
    task.objects[FIRST]["RoutingPrerequisite"] = False
    task.declare()
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    code, shown = task.run("transaction-show", preview["transaction_id"])
    assert code == 0, shown
    assert shown["artifact"]["prepared_operation"]["dispatch"]["args"]["objects"][0]["@RoutingPrerequisite"] is True


@pytest.mark.parametrize("version", VERSIONS[1:])
def test_satisfied_activation_is_guarded_without_redundant_property_writes(tmp_path: Path, version: str):
    task = AttenuationTask(tmp_path, version)
    task.objects[FIRST].update({"ListenerRelativeRouting": True, "OverridePositioning": True})
    task.declare()
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    code, shown = task.run("transaction-show", preview["transaction_id"])
    assert code == 0, shown
    assert "derived_changes" not in preview["preview_summary"]
    prepared = shown["artifact"]["prepared_operation"]
    row = prepared["dispatch"]["args"]["objects"][0]
    assert "@ListenerRelativeRouting" not in row
    assert "@OverridePositioning" not in row
    expected = prepared["verification_plan"]["nodes"][0]["properties"]
    assert {row["name"] for row in expected} == {"ListenerRelativeRouting", "OverridePositioning"}


@pytest.mark.parametrize("version", VERSIONS)
def test_reference_route_requires_explicit_prerequisite_previews(tmp_path: Path, version: str):
    task = AttenuationTask(tmp_path, version, operation="object.setReference")
    task.declare()
    code, rejected = task.step("draft-check")
    assert code == 2, rejected
    assert rejected["error_code"] == "REFERENCE_ACTIVATION_REQUIRED", rejected
    repairs = rejected["details"]["prerequisite_changes"]
    assert {row["discovery_meaning"] for row in repairs} == {"ListenerRelativeRouting", "OverridePositioning"}
    assert all(row["operation"] == "object.setProperty" and row["required_value"] is True for row in repairs)
    assert all(row["selection"] == "live_discovered_Field_Handle" for row in repairs)
    assert not any(uri in {"ak.wwise.core.object.set", "ak.wwise.core.object.setProperty", "ak.wwise.core.object.setReference"} for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("drift", ["none", "before-execute", "after-execute"])
def test_reference_route_guards_and_verifies_satisfied_activation(tmp_path: Path, version: str, drift: str):
    task = AttenuationTask(tmp_path, version, operation="object.setReference")
    task.objects[FIRST].update({"ListenerRelativeRouting": True, "OverridePositioning": True})
    task.declare()
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    if drift == "before-execute":
        task.objects[FIRST]["ListenerRelativeRouting"] = False
    code, executed = task.run("execute", tx)
    if drift == "before-execute":
        assert code == 2, executed
        assert not any(uri == "ak.wwise.core.object.setReference" for uri, _, _ in task.calls)
        return
    assert code == 0, json.dumps(executed)
    if drift == "after-execute":
        task.objects[FIRST]["OverridePositioning"] = False
    code, verified = task.run("verify", tx)
    if drift == "after-execute":
        assert code == 2 and verified.get("verified") is not True, verified
    else:
        assert code == 0 and verified["verified"] is True, verified
        assert task.objects[FIRST]["Attenuation"] == {"id": SECOND}
    assert sum(uri == "ak.wwise.core.object.setReference" for uri, _, _ in task.calls) == 1
    assert not any(uri in {"ak.wwise.core.object.set", "ak.wwise.core.object.setProperty"} for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", VERSIONS[1:])
@pytest.mark.parametrize("failure", ["conflict", "cycle", "unknown-condition"])
def test_conditional_activation_fails_closed(tmp_path: Path, version: str, failure: str):
    task = AttenuationTask(tmp_path, version)
    if failure == "conflict":
        task.metadata["Attenuation"]["dependencies"].append(condition("OverridePositioning", False))
    elif failure == "cycle":
        task.metadata["ListenerRelativeRouting"]["dependencies"] = [condition("OverridePositioning")]
        task.metadata["OverridePositioning"]["dependencies"] = [condition("ListenerRelativeRouting")]
    else:
        task.metadata["Attenuation"]["dependencies"][0]["conditions"][0]["operator"] = "guessed"
    task.declare()
    code, failed = task.step("draft-check")
    assert code == 2, failed
    codes = {issue["error_code"] for issue in failed["details"].get("issues", [])} | {failed["error_code"]}
    assert {"REFERENCE_DEPENDENCY_CONFLICT", "REFERENCE_DEPENDENCY_CYCLE", "CONSTRAINED_REFERENCE_BOUNDARY"} & codes, failed
    assert not any(uri == "ak.wwise.core.object.set" for uri, _, _ in task.calls)


def test_2021_atomic_object_set_remains_an_explicit_native_boundary(tmp_path: Path):
    task = AttenuationTask(tmp_path, "2021.1", operation="object.setReference")
    code, failed = task.run("draft-start", "object.set")
    assert code == 2 and failed["error_code"] == "UNAVAILABLE_IN_VERSION", failed


@pytest.mark.parametrize("version", VERSIONS[1:])
def test_exact_false_condition_is_not_guessed_as_true(tmp_path: Path, version: str):
    task = AttenuationTask(tmp_path, version)
    task.metadata["Attenuation"]["dependencies"] = [condition(value=False)]
    task.objects[FIRST]["ListenerRelativeRouting"] = True
    task.declare()
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    code, shown = task.run("transaction-show", preview["transaction_id"])
    assert code == 0, shown
    assert shown["artifact"]["prepared_operation"]["dispatch"]["args"]["objects"][0]["@ListenerRelativeRouting"] is False


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("name", ["OverridePositioning", "OverrideOutput"])
def test_terminal_override_is_editable_through_separate_property_preview(tmp_path: Path, version: str, name: str):
    task = AttenuationTask(tmp_path, version, operation="object.setProperty")
    task.metadata[name] = {"name": name, "type": "bool", "dependencies": [{
        "type": "override", "action": "Enable", "context": "Self", "property": name}]}
    task.objects[FIRST][name] = False
    target = task.bind(FIRST)
    field = task.discover(target, name)
    code, declared = task.step("draft-declare-field-change", "--object-handle", target,
                              "--field-handle", field, "--business-value", "true")
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    code, executed = task.run("execute", tx)
    assert code == 0, executed
    code, verified = task.run("verify", tx)
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[FIRST][name] is True
    assert task.objects[FIRST]["Attenuation"] is None
    assert sum(uri == "ak.wwise.core.object.setProperty" for uri, _, _ in task.calls) == 1


@pytest.mark.parametrize("version", VERSIONS[1:])
@pytest.mark.parametrize("restriction,current", [
    ({"type": "enum", "values": [{"value": 1}, {"value": 2}, {"value": 3}, {"value": 4}]}, 3),
    ({"type": "range", "min": 1, "max": 100}, 37),
])
def test_satisfied_scalar_condition_preserves_value_and_guards_drift(tmp_path, version, restriction, current):
    task = AttenuationTask(tmp_path, version)
    task.metadata["Attenuation"]["dependencies"] = [{
        "type": "property", "action": "Enable", "context": "Self", "property": "Mode",
        "conditions": [{"restriction": restriction}],
    }]
    task.metadata["Mode"] = {"name": "Mode", "type": "int16", "restriction": {"type": "range", "min": 0, "max": 100}}
    task.objects[FIRST]["Mode"] = current
    task.declare()
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    prepared = shown["artifact"]["prepared_operation"]
    assert "@Mode" not in prepared["dispatch"]["args"]["objects"][0]
    assert any(row["name"] == "Mode" and row["value"] == current for row in prepared["verification_plan"]["nodes"][0]["properties"])
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    task.objects[FIRST]["Mode"] = 0
    code, executed = task.run("execute", tx)
    assert code == 2, executed
    assert not any(uri == "ak.wwise.core.object.set" for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", VERSIONS[1:])
def test_accumulated_conditions_choose_only_the_unique_shared_value(tmp_path, version):
    task = AttenuationTask(tmp_path, version)
    task.metadata["Attenuation"]["dependencies"] = [
        {"type": "property", "action": "Enable", "context": "Self", "property": "Mode",
         "conditions": [{"restriction": {"type": "enum", "values": [{"value": n} for n in choices]}}]}
        for choices in ((1, 2), (2, 3))
    ]
    task.metadata["Mode"] = {"name": "Mode", "type": "int16", "restriction": {"type": "range", "min": 0, "max": 3}}
    task.objects[FIRST]["Mode"] = 0
    task.declare()
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    assert [(row["field"], row["value"]) for row in preview["preview_summary"]["derived_changes"]] == [("Mode", 2)]
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    code, executed = task.run("execute", tx)
    assert code == 0, executed
    code, verified = task.run("verify", tx)
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[FIRST]["Mode"] == 2
    assert task.objects[FIRST]["Volume"] == -7
    writes = [args for uri, args, _ in task.calls if uri.endswith("object.set")]
    assert len(writes) == 1 and writes[0]["objects"][0]["@Mode"] == 2


class ScalarPropertyTask(AttenuationTask):
    def __init__(self, path, version, operation="object.setProperty"):
        super().__init__(path, version, operation=operation)
        self.metadata = {
            "LfoSmoothing": {"name": "LfoSmoothing", "type": "Real64", "dependencies": [{
                "type": "property", "action": "Enable", "context": "Self", "property": "LfoWaveform",
                "conditions": [{"restriction": {"type": "enum", "values": [{"value": n} for n in (1, 2, 3, 4)]}}],
            }]},
            "LfoWaveform": {"name": "LfoWaveform", "type": "int16", "restriction": {"type": "range", "min": 0, "max": 5}},
        }
        self.objects[FIRST].update(LfoSmoothing=0.0, LfoWaveform=3)

    def call(self, uri, args=None, options=None):
        if uri.endswith("isPropertyEnabled"):
            self.calls.append((uri, deepcopy(args), options))
            return {"return": getattr(self, "enabled", True)}
        return super().call(uri, args, options)


@pytest.mark.parametrize("version", VERSIONS)
def test_disabled_scalar_property_discloses_exact_prerequisite_choice_without_writing(tmp_path, version):
    task = ScalarPropertyTask(tmp_path, version)
    task.enabled = False
    task.objects[FIRST]["LfoWaveform"] = 0
    target = task.bind(FIRST)
    field = task.discover(target, "LfoSmoothing")
    code, declared = task.step("draft-declare-field-change", "--object-handle", target,
                              "--field-handle", field, "--business-value", "50")
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 2 and checked["error_code"] == "REFERENCE_ACTIVATION_REQUIRED", checked
    repair = checked["details"]["prerequisite_changes"][0]
    assert repair["operation"] == "object.setProperty"
    assert repair["discovery_meaning"] == "LfoWaveform"
    assert repair["selection"] == "live_discovered_Field_Handle"
    assert [row["value"] for row in repair["restriction"]["values"]] == [1, 2, 3, 4]
    assert "required_value" not in repair
    assert task.objects[FIRST]["LfoWaveform"] == 0
    assert not any(uri.endswith(("object.set", "setProperty", "setReference")) for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", VERSIONS[1:])
@pytest.mark.parametrize("drift", ["none", "before", "after", "metadata"])
def test_atomic_property_condition_is_previewed_guarded_and_verified(tmp_path, version, drift):
    task = ScalarPropertyTask(tmp_path, version, operation="object.set")
    task.metadata["LfoPWM"] = {"name": "LfoPWM", "type": "Real64", "dependencies": [{
        "type": "property", "action": "Enable", "context": "Self", "property": "LfoWaveform",
        "conditions": [{"restriction": {"type": "enum", "values": [{"value": 2}]}}],
    }]}
    task.objects[FIRST].update(LfoPWM=0.0, LfoWaveform=0)
    source = task.bind(FIRST)
    field = task.discover(source, "LfoPWM")
    code, declared = task.step("draft-declare-existing", "--declaration-id", "pulse-width",
                              "--object-handle", source, "--field-value", field, "50")
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    assert [(row["field"], row["value"]) for row in preview["preview_summary"]["derived_changes"]] == [("LfoWaveform", 2)]
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    if drift == "before":
        task.objects[FIRST]["LfoWaveform"] = 3
    if drift == "metadata":
        task.metadata["LfoPWM"]["dependencies"][0]["conditions"][0]["restriction"]["values"] = [{"value": 3}]
    code, executed = task.run("execute", tx)
    if drift in {"before", "metadata"}:
        assert code == 2, executed
        assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)
        return
    assert code == 0, executed
    if drift == "after":
        task.objects[FIRST]["LfoWaveform"] = 0
    code, verified = task.run("verify", tx)
    assert code == (2 if drift == "after" else 0), verified
    assert task.objects[FIRST]["LfoPWM"] == 50
    assert task.objects[FIRST]["Volume"] == -7
    writes = [args for uri, args, _ in task.calls if uri.endswith("object.set")]
    assert len(writes) == 1 and writes[0]["objects"][0]["@LfoWaveform"] == 2


@pytest.mark.parametrize("version", VERSIONS[1:])
def test_atomic_field_conditions_are_combined_before_choosing_a_prerequisite(tmp_path, version):
    task = ScalarPropertyTask(tmp_path, version, operation="object.set")
    task.metadata["LfoPWM"] = {"name": "LfoPWM", "type": "Real64", "dependencies": [{
        "type": "property", "action": "Enable", "context": "Self", "property": "LfoWaveform",
        "conditions": [{"restriction": {"type": "enum", "values": [{"value": 2}]}}],
    }]}
    task.objects[FIRST].update(LfoPWM=0.0, LfoWaveform=0)
    target = task.bind(FIRST)
    smoothing = task.discover(target, "LfoSmoothing")
    pwm = task.discover(target, "LfoPWM")
    code, declared = task.step("draft-declare-existing", "--declaration-id", "wave-shape",
                              "--object-handle", target, "--field-value", smoothing, "50",
                              "--field-value", pwm, "60")
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    assert [(row["field"], row["value"]) for row in preview["preview_summary"]["derived_changes"]] == [("LfoWaveform", 2)]
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    code, executed = task.run("execute", tx)
    assert code == 0, executed
    code, verified = task.run("verify", tx)
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[FIRST]["LfoWaveform"] == 2
    assert task.objects[FIRST]["LfoSmoothing"] == 50 and task.objects[FIRST]["LfoPWM"] == 60
    assert task.objects[FIRST]["Volume"] == -7


class ReferencePresenceTask(AttenuationTask):
    def __init__(self, path, version, operation="object.setProperty"):
        super().__init__(path, version, operation=operation)
        self.metadata = {
            "UserAuxSendVolume0": {"name": "UserAuxSendVolume0", "type": "Real64", "dependencies": [{
                "type": "reference", "action": "Enable", "context": "Self", "property": "UserAuxSend0",
                "conditions": [{"referenceIsSet": True}],
            }]},
            "UserAuxSend0": {"name": "UserAuxSend0", "type": "", "restriction": {
                "type": "reference", "restrictions": [{"type": ["AuxBus"]}],
            }},
        }
        self.objects[FIRST].update(UserAuxSendVolume0=0.0, UserAuxSend0={"id": SECOND})
        self.objects[SECOND].update(type="AuxBus", path=r"\Master-Mixer Hierarchy\Default Work Unit\Near")

    def call(self, uri, args=None, options=None):
        if uri.endswith("isPropertyEnabled"):
            self.calls.append((uri, deepcopy(args), options))
            return {"return": getattr(self, "enabled", True)}
        return super().call(uri, args, options)


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("drift", ["none", "before", "after", "metadata"])
def test_reference_presence_condition_is_preserved_guarded_and_verified(tmp_path, version, drift):
    task = ReferencePresenceTask(tmp_path, version)
    target = task.bind(FIRST)
    field = task.discover(target, "UserAuxSendVolume0")
    code, declared = task.step("draft-declare-field-change", "--object-handle", target,
                              "--field-handle", field, "--business-value", "-6")
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    if drift == "before":
        task.objects[FIRST]["UserAuxSend0"] = None
    if drift == "metadata":
        task.metadata["UserAuxSendVolume0"]["dependencies"][0]["conditions"][0]["referenceIsSet"] = False
    code, executed = task.run("execute", tx)
    if drift in {"before", "metadata"}:
        assert code == 2, executed
        assert not any(uri.endswith("setProperty") for uri, _, _ in task.calls)
        return
    assert code == 0, executed
    if drift == "after":
        task.objects[FIRST]["UserAuxSend0"] = None
    code, verified = task.run("verify", tx)
    assert code == (2 if drift == "after" else 0), verified
    assert task.objects[FIRST]["UserAuxSendVolume0"] == -6
    assert task.objects[FIRST]["Volume"] == -7
    assert sum(uri.endswith("setProperty") for uri, _, _ in task.calls) == 1
    assert not any(uri.endswith(("object.set", "setReference")) for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", VERSIONS)
def test_missing_reference_discloses_target_choice_without_inventing_a_reference(tmp_path, version):
    task = ReferencePresenceTask(tmp_path, version)
    task.enabled = False
    task.objects[FIRST]["UserAuxSend0"] = None
    target = task.bind(FIRST)
    field = task.discover(target, "UserAuxSendVolume0")
    code, declared = task.step("draft-declare-field-change", "--object-handle", target,
                              "--field-handle", field, "--business-value", "-6")
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 2 and checked["error_code"] == "REFERENCE_ACTIVATION_REQUIRED", checked
    repair = checked["details"]["prerequisite_changes"][0]
    assert repair == {"operation": "object.setReference", "discovery_meaning": "UserAuxSend0",
                      "selection": "live_discovered_Field_Handle", "required_presence": True,
                      "target_selection": "user_chosen_exact_object"}
    assert not any(uri.endswith(("object.set", "setProperty", "setReference")) for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", VERSIONS[1:])
@pytest.mark.parametrize("existing", [None, "{33333333-3333-3333-3333-333333333333}"])
def test_explicit_reference_satisfies_atomic_property_presence_condition(tmp_path, version, existing):
    task = ReferencePresenceTask(tmp_path, version, operation="object.set")
    task.objects[FIRST]["UserAuxSend0"] = None if existing is None else {"id": existing}
    source, target = task.bind(FIRST), task.bind(SECOND)
    volume = task.discover(source, "UserAuxSendVolume0")
    reference = task.discover(source, "UserAuxSend0")
    code, declared = task.step("draft-declare-existing", "--declaration-id", "send",
                              "--object-handle", source, "--field-value", volume, "-6",
                              "--field-value", reference, target)
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    assert "derived_changes" not in preview["preview_summary"]
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    code, executed = task.run("execute", tx)
    assert code == 0, executed
    code, verified = task.run("verify", tx)
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[FIRST]["UserAuxSend0"] == {"id": SECOND}
    assert task.objects[FIRST]["UserAuxSendVolume0"] == -6 and task.objects[FIRST]["Volume"] == -7
    writes = [args for uri, args, _ in task.calls if uri.endswith("object.set")]
    assert len(writes) == 1 and writes[0]["objects"][0]["@UserAuxSend0"] == SECOND


@pytest.mark.parametrize("version", VERSIONS[1:])
@pytest.mark.parametrize("drift", ["none", "before", "after", "metadata"])
def test_atomic_presence_guard_preserves_an_existing_reference_without_rewriting_it(tmp_path, version, drift):
    task = ReferencePresenceTask(tmp_path, version, operation="object.set")
    target = task.bind(FIRST)
    field = task.discover(target, "UserAuxSendVolume0")
    code, declared = task.step("draft-declare-existing", "--declaration-id", "send-volume",
                              "--object-handle", target, "--field-value", field, "-6")
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    if drift == "before":
        task.objects[FIRST]["UserAuxSend0"] = None
    if drift == "metadata":
        task.metadata["UserAuxSendVolume0"]["dependencies"][0]["conditions"][0]["referenceIsSet"] = False
    code, executed = task.run("execute", tx)
    if drift in {"before", "metadata"}:
        assert code == 2, executed
        assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)
        return
    assert code == 0, executed
    if drift == "after":
        task.objects[FIRST]["UserAuxSend0"] = None
    code, verified = task.run("verify", tx)
    assert code == (2 if drift == "after" else 0), verified
    writes = [args for uri, args, _ in task.calls if uri.endswith("object.set")]
    assert len(writes) == 1 and "@UserAuxSend0" not in writes[0]["objects"][0]
    assert task.objects[FIRST]["UserAuxSendVolume0"] == -6 and task.objects[FIRST]["Volume"] == -7


@pytest.mark.parametrize("version", VERSIONS)
def test_conflicting_reference_presence_conditions_reject_before_any_write(tmp_path, version):
    task = ReferencePresenceTask(tmp_path, version)
    contradictory = deepcopy(task.metadata["UserAuxSendVolume0"]["dependencies"][0])
    contradictory["conditions"][0]["referenceIsSet"] = False
    task.metadata["UserAuxSendVolume0"]["dependencies"].append(contradictory)
    target = task.bind(FIRST)
    field = task.discover(target, "UserAuxSendVolume0")
    code, declared = task.step("draft-declare-field-change", "--object-handle", target,
                              "--field-handle", field, "--business-value", "-6")
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 2 and checked["error_code"] == "REFERENCE_DEPENDENCY_CONFLICT", checked
    assert not any(uri.endswith(("object.set", "setProperty", "setReference")) for uri, _, _ in task.calls)


class SerializedScalarTask(ScalarPropertyTask):
    def call(self, uri, args=None, options=None):
        # Exercise independent JSON values as the external WAAPI transport does.
        return json.loads(json.dumps(super().call(uri, args, options)))


@pytest.mark.parametrize("drift", ["none", "owner-before", "value-before", "value-after", "metadata-before"])
@pytest.mark.parametrize("operation", ["object.setProperty", "object.set"])
@pytest.mark.parametrize("enabled", [True, False])
def test_association_parent_condition_uses_exact_owner_and_guards_it(tmp_path, drift, operation, enabled):
    task = ScalarPropertyTask(tmp_path, "2025.1", operation=operation)
    task.enabled = enabled
    task.metadata = {
        "ContinuePlay": {"name": "ContinuePlay", "type": "bool", "dependencies": [{
            "type": "property", "action": "Enable", "context": "AssocParent", "property": "SwitchBehavior",
            "conditions": [{"restriction": {"type": "enum", "values": [{"value": 1}]}}],
        }]},
        "SwitchBehavior": {"name": "SwitchBehavior", "type": "int16"},
    }
    task.objects[FIRST].update(name="", type="ObjectSettingAssociation",
        path=r"\Containers\Minigun\Shells\<Unnamed Object Setting Association>",
        parent=None, owner={"id": SECOND}, ContinuePlay=False)
    task.objects[SECOND].update(name="Shells", type="SwitchContainer", path=r"\Containers\Minigun\Shells", SwitchBehavior=1)
    target = task.bind(FIRST)
    field = task.discover(target, "ContinuePlay")
    code, declared = (task.step("draft-declare-field-change", "--object-handle", target,
                              "--field-handle", field, "--business-value", "true") if operation == "object.setProperty" else
                      task.step("draft-declare-existing", "--declaration-id", "continue-play", "--object-handle", target,
                                "--field-value", field, "true"))
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    if drift == "owner-before":
        task.objects[FIRST]["owner"] = None
    if drift == "value-before":
        task.objects[SECOND]["SwitchBehavior"] = 0
    if drift == "metadata-before":
        task.metadata["SwitchBehavior"]["default"] = 0
    code, executed = task.run("execute", tx)
    if drift.endswith("before"):
        assert code == 2, executed
        assert not any(uri.endswith(("setProperty", "object.set")) for uri, _, _ in task.calls)
        return
    assert code == 0, executed
    if drift == "value-after":
        task.objects[SECOND]["SwitchBehavior"] = 0
    code, verified = task.run("verify", tx)
    assert code == (2 if drift == "value-after" else 0), json.dumps(verified)
    assert task.objects[FIRST]["ContinuePlay"] is True
    writes = [(uri, args) for uri, args, _ in task.calls if uri.endswith(("setProperty", "object.set"))]
    assert len(writes) == 1
    if operation == "object.setProperty":
        assert writes[0][1]["object"] == FIRST
    else:
        assert writes[0][1]["objects"][0]["object"] == FIRST
        assert "@SwitchBehavior" not in writes[0][1]["objects"][0]


@pytest.mark.parametrize("version", VERSIONS[1:])
@pytest.mark.parametrize("current,metadata_type,restriction", [
    (999.0, "Real64", {"type": "range", "min": 1, "max": 1000}),
    (1, "int16", {"type": "enum", "values": [{"value": 1.0}]}),
])
def test_satisfied_numeric_condition_preserves_native_value_across_json_reads(tmp_path, version, current, metadata_type, restriction):
    task = SerializedScalarTask(tmp_path, version, operation="object.set")
    task.metadata["LfoSmoothing"]["dependencies"][0]["conditions"][0]["restriction"] = restriction
    task.metadata["LfoWaveform"] = {"name": "LfoWaveform", "type": metadata_type,
                                    "restriction": {"type": "range", "min": 0, "max": 1000}}
    task.objects[FIRST]["LfoWaveform"] = current
    target = task.bind(FIRST)
    field = task.discover(target, "LfoSmoothing")
    code, declared = task.step("draft-declare-existing", "--declaration-id", "smoothing",
                              "--object-handle", target, "--field-value", field, "50")
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    assert "derived_changes" not in preview["preview_summary"]
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    assert "@LfoWaveform" not in shown["artifact"]["prepared_operation"]["dispatch"]["args"]["objects"][0]
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    code, executed = task.run("execute", tx)
    assert code == 0, executed
    code, verified = task.run("verify", tx)
    assert code == 0 and verified["verified"] is True, verified
    assert type(task.objects[FIRST]["LfoWaveform"]) is type(current)
    assert task.objects[FIRST]["LfoWaveform"] == current


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("context", ["Self", "Parent"])
@pytest.mark.parametrize("visibility_values", [(1,), (0, 1)])
def test_visibility_condition_does_not_derive_or_require_a_prerequisite_write(tmp_path, version, context, visibility_values):
    task = AttenuationTask(tmp_path, version, operation="object.setProperty")
    task.metadata = {
        "SlewRateUp": {"name": "SlewRateUp", "type": "Real64", "dependencies": [{
            "type": "property", "action": "Show", "context": context,
            "property": "RTPCRamping", "conditions": [{"restriction": {
                "type": "enum", "values": [{"value": 1}]}}],
        }]},
        "RTPCRamping": {"name": "RTPCRamping", "type": "int16"},
    }
    dependency = task.metadata["SlewRateUp"]["dependencies"][0]
    task.metadata["SlewRateUp"]["dependencies"] = [
        {**deepcopy(dependency), "conditions": [{"restriction": {"type": "enum", "values": [{"value": value}]}}]}
        for value in visibility_values
    ]
    task.objects[FIRST].update(SlewRateUp=0.0, RTPCRamping=0)
    target = task.bind(FIRST)
    field = task.discover(target, "SlewRateUp")
    code, declared = task.step("draft-declare-field-change", "--object-handle", target,
                              "--field-handle", field, "--business-value", "25")
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    assert "derived_changes" not in preview["preview_summary"]
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    code, executed = task.run("execute", tx)
    assert code == 0, executed
    code, verified = task.run("verify", tx)
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[FIRST]["SlewRateUp"] == 25
    assert task.objects[FIRST]["RTPCRamping"] == 0
    assert task.objects[FIRST]["Volume"] == -7
    assert [args["property"] for uri, args, _ in task.calls if uri.endswith("setProperty")] == ["SlewRateUp"]


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("drift", ["none", "before", "after", "metadata"])
def test_property_condition_is_preserved_revalidated_and_verified(tmp_path, version, drift):
    task = ScalarPropertyTask(tmp_path, version)
    target = task.bind(FIRST)
    field = task.discover(target, "LfoSmoothing")
    code, declared = task.step("draft-declare-field-change", "--object-handle", target,
                              "--field-handle", field, "--business-value", "50")
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    if drift == "before":
        task.objects[FIRST]["LfoWaveform"] = 0
    if drift == "metadata":
        task.metadata["LfoSmoothing"]["dependencies"][0]["conditions"][0]["restriction"]["values"] = [{"value": 0}]
    code, executed = task.run("execute", tx)
    if drift in {"before", "metadata"}:
        assert code == 2, executed
        assert not any(uri.endswith("setProperty") for uri, _, _ in task.calls)
        return
    assert code == 0, executed
    if drift == "after":
        task.objects[FIRST]["LfoWaveform"] = 0
    code, verified = task.run("verify", tx)
    assert code == (2 if drift == "after" else 0), verified
    assert task.objects[FIRST]["LfoSmoothing"] == 50
    assert task.objects[FIRST]["Volume"] == -7
    writes = [args for uri, args, _ in task.calls if uri.endswith("setProperty")]
    assert len(writes) == 1 and writes[0]["property"] == "LfoSmoothing"
