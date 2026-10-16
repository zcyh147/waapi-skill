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
                        self.objects[row["object"]][key[1:]] = {"id": value} if key == "@Attenuation" else value
            return {"objects": [{"id": FIRST, "name": "Rain", "type": self.objects[FIRST]["type"]}]}
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
def test_terminal_override_is_editable_through_separate_property_preview(tmp_path: Path, version: str):
    task = AttenuationTask(tmp_path, version, operation="object.setProperty")
    task.metadata["OverridePositioning"]["dependencies"] = [{
        "type": "override", "action": "Enable", "context": "Self", "property": "OverridePositioning"}]
    target = task.bind(FIRST)
    field = task.discover(target, "OverridePositioning")
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
    assert task.objects[FIRST]["OverridePositioning"] is True
    assert task.objects[FIRST]["Attenuation"] is None
    assert sum(uri == "ak.wwise.core.object.setProperty" for uri, _, _ in task.calls) == 1
