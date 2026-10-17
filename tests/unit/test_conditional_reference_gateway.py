"""Public attenuation activation from the recorded live dependency shape."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from tests.unit.test_field_interface_closure_gateway import FieldTask, FIRST, SECOND, VERSIONS, gateway


@pytest.fixture
def condition_product_capture(request, tmp_path):
    from tests.support.condition_branch_evidence import prepare_condition_capture, finish_condition_capture
    root = Path(os.environ.get("WAAPI_CONDITION_BRANCH_EVIDENCE_ROOT", str(tmp_path / "condition-product-evidence"))).resolve()
    capture = prepare_condition_capture(root, request.node.nodeid)
    observed = {}
    from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
    register_exact_evidence_finalizer(request.node, lambda reports: finish_condition_capture(capture, reports, observed))
    yield observed


def test_product_slew_rate_show_condition_changes_only_the_selected_field(tmp_path, condition_product_capture):
    task = ScalarPropertyTask(tmp_path, "2025.1")
    dependency = {"type": "property", "action": "Show", "context": "Self", "property": "RTPCRamping",
                  "conditions": [{"restriction": {"type": "enum", "values": [{"value": 1}]}}]}
    task.metadata = {"SlewRateUp": {"name": "SlewRateUp", "type": "Real64", "dependencies": [dependency]},
                     "RTPCRamping": {"name": "RTPCRamping", "type": "int16"}}
    task.objects[FIRST].update(type="GameParameter", name="OwnedVisibilityTarget",
        path=r"\Game Parameters\Default Work Unit\OwnedVisibilityTarget", RTPCRamping=0, SlewRateUp=0.0)
    before = deepcopy(task.objects[FIRST])
    target = task.bind(FIRST)
    field = task.discover(target, "SlewRateUp")
    code, declared = task.step("draft-declare-field-change", "--object-handle", target,
                              "--field-handle", field, "--business-value", "37")
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
    after = deepcopy(task.objects[FIRST])
    assert after == {**before, "SlewRateUp": 37}
    writes = [{"uri": uri, "args": args, "options": options} for uri, args, options in task.calls
              if uri.endswith(("setProperty", "setReference", "object.set"))]
    assert len(writes) == 1 and writes[0]["args"]["property"] == "SlewRateUp"
    condition_product_capture.update(
        gateway={"argv": ["--state-dir", str(task.path / "state"), "verify", tx], "exit_code": code, "payload": verified},
        native_call=writes[0], observations={"wwise-console": {"metadata": deepcopy(task.metadata["SlewRateUp"]),
            "observations": [{"controller_before": before, "controller_after": after, "before": before, "after": after}]}},
    )


def condition(name="ListenerRelativeRouting", value=True):
    return {"action": "Enable", "conditions": [{"restriction": {"type": "enum", "values": [{"displayName": "True" if value else "False", "value": value}]}}],
            "context": "Self", "property": name, "type": "property"}


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("operation", ["object.setProperty", "object.setReference", "object.set"])
def test_public_existing_field_schema_discloses_gateway_condition_ownership(tmp_path, version, operation):
    task = FieldTask(tmp_path, version, "object.setProperty")
    code, payload = task.run("--version", version, "operation-schema", operation)
    assert code == 0, payload
    if version == "2021.1" and operation == "object.set":
        assert payload["operation"]["availability"]["status"] == "unsupported_version"
        return
    condition_contract = payload["business_adapter"]["activation_prerequisites"]
    assert condition_contract["contract"] == "waapi-skill.existing-field-conditions/v1"
    assert condition_contract["owner"] == "gateway"
    scalar = condition_contract["conditions"]["property"]
    assert scalar["restrictions"] == ["enum", "range"]
    assert scalar["satisfied_value"] == "preserve_exact_native_value"
    assert scalar["multiple_choices"] == "require_explicit_user_value_when_current_value_does_not_satisfy"
    assert condition_contract["conditions"]["reference"]["condition"] == "referenceIsSet_boolean"
    assert condition_contract["conditions"]["visibility"]["prerequisite_write"] is False
    assert condition_contract["conditions"]["association_owner"]["source_type"] == "ObjectSettingAssociation"
    assert condition_contract["conditions"]["association_owner"]["recursive_prerequisites"] == ["property", "override", "reference"]
    assert condition_contract["safety"]["related_object_writes"] == "separately_preview_and_authorize"
    assert condition_contract["safety"]["revalidate"] == ["identities", "relationships", "metadata", "prerequisite_values"]
    assert condition_contract["atomic_batch_alternative"] == ("object.set" if version != "2021.1" else None)
    assert task.calls == []


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


class PlatformConditionTask(ScalarPropertyTask):
    platform = "{33333333-3333-3333-3333-333333333333}"

    def call(self, uri, args=None, options=None):
        result = super().call(uri, args, options)
        if uri.endswith("object.get") and options and options.get("platform") == self.platform:
            for row in result.get("return", []):
                if row.get("id") == FIRST:
                    row.update(getattr(self, "platform_values", {FIRST: {"LfoWaveform": 2}}).get(FIRST, {}))
                else:
                    row.update(getattr(self, "platform_values", {}).get(row.get("id"), {}))
        return result


@pytest.mark.parametrize("version,operation", [
    (version, operation) for version in VERSIONS for operation in ("object.setProperty", "object.set")
    if version != "2021.1" or operation != "object.set"
])
@pytest.mark.parametrize("phase", ["before", "after"])
@pytest.mark.parametrize("observed", [1.0, True, 1.000001])
def test_numeric_prerequisite_guards_accept_representation_only_and_reject_value_or_boolean_drift(tmp_path, version, operation, phase, observed):
    task = ScalarPropertyTask(tmp_path, version, operation=operation)
    task.metadata["LfoWaveform"]["type"] = "Real64"
    task.objects[FIRST]["LfoWaveform"] = 1
    target = task.bind(FIRST)
    field = task.discover(target, "LfoSmoothing")
    code, declared = (task.step("draft-declare-field-change", "--object-handle", target,
                              "--field-handle", field, "--business-value", "50") if operation == "object.setProperty" else
                      task.step("draft-declare-existing", "--declaration-id", "smoothing", "--object-handle", target,
                                "--field-value", field, "50"))
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
    valid = type(observed) is float and observed == 1
    if phase == "before":
        task.objects[FIRST]["LfoWaveform"] = observed
    code, executed = task.run("execute", tx)
    if phase == "before" and not valid:
        assert code == 2, executed
        assert not any(uri.endswith(("setProperty", "object.set")) for uri, _, _ in task.calls)
        return
    assert code == 0, executed
    if phase == "after":
        task.objects[FIRST]["LfoWaveform"] = observed
    code, verified = task.run("verify", tx)
    assert code == (0 if valid else 2), verified


@pytest.mark.parametrize("version,operation", [
    (version, operation) for version in VERSIONS
    for operation in ("object.setProperty", "object.setReference", "object.set")
    if version != "2021.1" or operation != "object.set"
])
def test_condition_reads_use_requested_platform_and_preserve_its_satisfied_value(tmp_path, version, operation):
    task = PlatformConditionTask(tmp_path, version, operation=operation)
    task.objects[FIRST]["LfoWaveform"] = 1
    meaning, value = "LfoSmoothing", "50"
    if operation == "object.setReference":
        task.metadata["Attenuation"] = {"name": "Attenuation", "type": "", "restriction": {
            "type": "reference", "restrictions": [{"type": ["Attenuation"]}]},
            "dependencies": deepcopy(task.metadata["LfoSmoothing"]["dependencies"])}
        meaning = "Attenuation"
    target = task.bind(FIRST)
    code, discovered = task.step("draft-discover-fields", "--object-handle", target, "--meaning", meaning, "--platform", task.platform)
    assert code == 0, discovered
    field = discovered["meaning_results"][0]["candidates"][0]["handle"]
    if operation == "object.setReference":
        selected = task.bind(SECOND)
        code, declared = task.step("draft-declare-field-change", "--object-handle", target, "--field-handle", field, "--target-handle", selected)
    elif operation == "object.setProperty":
        code, declared = task.step("draft-declare-field-change", "--object-handle", target, "--field-handle", field, "--business-value", value)
    else:
        code, declared = task.step("draft-declare-existing", "--declaration-id", "smoothing", "--object-handle", target,
                                  "--field-value", field, value)
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    assert "derived_changes" not in preview["preview_summary"]
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    code, executed = task.run("execute", tx)
    assert code == 0, executed
    code, verified = task.run("verify", tx)
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[FIRST]["LfoWaveform"] == 1
    condition_reads = [options for uri, _, options in task.calls if uri.endswith("object.get") and "LfoWaveform" in options.get("return", [])]
    assert condition_reads and all(row.get("platform") == task.platform for row in condition_reads)


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
@pytest.mark.parametrize("condition_value", [2, 2.0])
def test_atomic_property_condition_is_previewed_guarded_and_verified(tmp_path, version, drift, condition_value):
    task = ScalarPropertyTask(tmp_path, version, operation="object.set")
    task.metadata["LfoPWM"] = {"name": "LfoPWM", "type": "Real64", "dependencies": [{
        "type": "property", "action": "Enable", "context": "Self", "property": "LfoWaveform",
        "conditions": [{"restriction": {"type": "enum", "values": [{"value": condition_value}]}}],
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
    assert type(writes[0]["objects"][0]["@LfoWaveform"]) is int


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


class PlatformPresenceTask(ReferencePresenceTask):
    platform = PlatformConditionTask.platform

    def call(self, uri, args=None, options=None):
        result = super().call(uri, args, options)
        if uri.endswith("object.get") and options and options.get("platform") == self.platform:
            for row in result.get("return", []):
                if row.get("id") == FIRST:
                    row["UserAuxSend0"] = {"id": SECOND}
        return result


@pytest.mark.parametrize("version,operation", [
    (version, operation) for version in VERSIONS for operation in ("object.setProperty", "object.set")
    if version != "2021.1" or operation != "object.set"
])
def test_reference_presence_reads_and_guards_use_the_selected_platform(tmp_path, version, operation):
    task = PlatformPresenceTask(tmp_path, version, operation=operation)
    task.objects[FIRST]["UserAuxSend0"] = None
    target = task.bind(FIRST)
    code, discovered = task.step("draft-discover-fields", "--object-handle", target, "--meaning", "UserAuxSendVolume0", "--platform", task.platform)
    assert code == 0, discovered
    field = discovered["meaning_results"][0]["candidates"][0]["handle"]
    code, declared = (task.step("draft-declare-field-change", "--object-handle", target,
                              "--field-handle", field, "--business-value", "-6") if operation == "object.setProperty" else
                      task.step("draft-declare-existing", "--declaration-id", "aux-volume", "--object-handle", target,
                                "--field-value", field, "-6"))
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
    assert task.objects[FIRST]["UserAuxSend0"] is None
    reads = [options for uri, _, options in task.calls if uri.endswith("object.get") and "UserAuxSend0" in options.get("return", [])]
    assert reads and all(row.get("platform") == task.platform for row in reads)


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


class ChangingScalarTask(ScalarPropertyTask):
    def call(self, uri, args=None, options=None):
        if uri.endswith("object.get") and options:
            fields = options.get("return", [])
            if fields == ["id", "LfoWaveform"]:
                self.objects[FIRST]["LfoWaveform"] = 1
            elif "LfoWaveform" in fields and "LfoSmoothing" in fields:
                self.objects[FIRST]["LfoWaveform"] = self.final_value
        return super().call(uri, args, options)


@pytest.mark.parametrize("version", VERSIONS[1:])
@pytest.mark.parametrize("final_value", [2, 0])
def test_final_preview_snapshot_preserves_a_satisfied_condition_and_never_reuses_a_stale_choice(tmp_path, version, final_value):
    task = ChangingScalarTask(tmp_path, version, operation="object.set")
    task.final_value = final_value
    task.objects[FIRST]["LfoWaveform"] = final_value
    target = task.bind(FIRST)
    field = task.discover(target, "LfoSmoothing")
    code, declared = task.step("draft-declare-existing", "--declaration-id", "smoothing", "--object-handle", target,
                              "--field-value", field, "50")
    assert code == 0, declared
    code, checked = task.step("draft-check")
    if final_value == 0:
        assert code == 2 and checked["details"]["issues"][0]["error_code"] == "REFERENCE_ACTIVATION_REQUIRED", checked
        assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)
        return
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, json.dumps(preview)
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
    assert task.objects[FIRST]["LfoWaveform"] == 2


@pytest.mark.parametrize("drift", ["none", "owner-before", "value-before", "value-after", "metadata-before"])
@pytest.mark.parametrize("operation", ["object.setProperty", "object.set"])
@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("platform", [None, PlatformConditionTask.platform])
def test_association_parent_condition_uses_exact_owner_and_guards_it(tmp_path, drift, operation, enabled, platform):
    task = (PlatformConditionTask if platform is not None else ScalarPropertyTask)(tmp_path, "2025.1", operation=operation)
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
    if platform is not None:
        task.objects[SECOND]["SwitchBehavior"] = 0
        task.platform_values = {SECOND: {"SwitchBehavior": 1}}
    target = task.bind(FIRST)
    code, discovered = task.step("draft-discover-fields", "--object-handle", target, "--meaning", "ContinuePlay",
                                *(["--platform", platform] if platform is not None else []))
    assert code == 0, discovered
    field = discovered["meaning_results"][0]["candidates"][0]["handle"]
    code, declared = (task.step("draft-declare-field-change", "--object-handle", target,
                              "--field-handle", field, "--business-value", "true") if operation == "object.setProperty" else
                      task.step("draft-declare-existing", "--declaration-id", "continue-play", "--object-handle", target,
                                "--field-value", field, "true"))
    assert code == 0, declared
    code, checked = task.step("draft-check")
    if platform is not None and not enabled:
        assert code == 2, checked
        issues = checked.get("details", {}).get("issues", [])
        assert (issues[0]["error_code"] if issues else checked["error_code"]) == "PROPERTY_DISABLED_FOR_PLATFORM", checked
        assert not any(uri.endswith(("setProperty", "object.set")) for uri, _, _ in task.calls)
        return
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
        if platform is not None:
            task.platform_values[SECOND]["SwitchBehavior"] = 0
        else:
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
        if platform is not None:
            task.platform_values[SECOND]["SwitchBehavior"] = 0
        else:
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
    reads = [options for uri, _, options in task.calls if uri.endswith("object.get") and "SwitchBehavior" in options.get("return", [])]
    assert reads and all(row.get("platform") == platform for row in reads)


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


@pytest.mark.parametrize("drift", ["none", "before", "after", "metadata-before", "unsatisfied"])
@pytest.mark.parametrize("version,operation", [(version, operation) for version in VERSIONS
    for operation in (["object.setProperty"] if version == "2021.1" else ["object.setProperty", "object.set"])])
@pytest.mark.parametrize("prerequisite_kind", ["property", "reference", "override"])
@pytest.mark.parametrize("platform", [None, PlatformConditionTask.platform])
def test_association_owner_satisfied_recursive_condition_is_guarded_without_owner_writes(tmp_path, drift, operation, prerequisite_kind, version, platform):
    task = (PlatformConditionTask if platform else ScalarPropertyTask)(tmp_path, version, operation=operation)
    task.metadata = {
        "ContinuePlay": {"name": "ContinuePlay", "type": "bool", "dependencies": [{
            "type": "property", "action": "Enable", "context": "AssocParent", "property": "SwitchBehavior",
            "conditions": [{"restriction": {"type": "enum", "values": [{"value": 1}]}}],
        }]},
        "SwitchBehavior": {"name": "SwitchBehavior", "type": "int16", "dependencies": [condition("OverridePlayback")]},
        "OverridePlayback": {"name": "OverridePlayback", "type": "bool"},
    }
    task.objects[FIRST].update(name="", type="ObjectSettingAssociation", parent=None, owner={"id": SECOND}, ContinuePlay=False)
    task.objects[SECOND].update(type="SwitchContainer", SwitchBehavior=1, OverridePlayback=True)
    if prerequisite_kind == "reference":
        task.metadata["SwitchBehavior"]["dependencies"] = [{"type": "reference", "action": "Enable", "context": "Self",
            "property": "OutputBus", "conditions": [{"referenceIsSet": True}]}]
        task.metadata["OutputBus"] = {"name": "OutputBus", "type": "Reference"}
        task.objects[SECOND]["OutputBus"] = {"id": FIRST}
    if prerequisite_kind == "override":
        task.metadata["SwitchBehavior"]["dependencies"] = [{"type": "override", "action": "Enable",
            "context": "Self", "property": "OverridePlayback"}]
        task.metadata["OverridePlayback"]["default"] = True
    if platform is not None:
        task.platform_values = {SECOND: {"SwitchBehavior": 1, "OverridePlayback": True, "OutputBus": {"id": FIRST}}}
        task.objects[SECOND].update(SwitchBehavior=0, OverridePlayback=False, OutputBus=None)
    owner_values = task.platform_values[SECOND] if platform else task.objects[SECOND]
    if drift == "unsatisfied":
        owner_values["OutputBus" if prerequisite_kind == "reference" else "OverridePlayback"] = None if prerequisite_kind == "reference" else False
    target = task.bind(FIRST)
    code, discovered = task.step("draft-discover-fields", "--object-handle", target, "--meaning", "ContinuePlay",
                                *(["--platform", platform] if platform is not None else []))
    assert code == 0, discovered
    field = discovered["meaning_results"][0]["candidates"][0]["handle"]
    code, declared = (task.step("draft-declare-field-change", "--object-handle", target, "--field-handle", field,
                               "--business-value", "true") if operation == "object.setProperty" else
                      task.step("draft-declare-existing", "--declaration-id", "continue-play", "--object-handle", target,
                                "--field-value", field, "true"))
    assert code == 0, declared
    code, checked = task.step("draft-check")
    if drift == "unsatisfied":
        assert code == 2, checked
        issue = checked.get("details", {}).get("issues", [checked])[0]
        assert issue["error_code"] == "REFERENCE_ACTIVATION_REQUIRED", checked
        details = issue.get("details", {})
        assert details.get("owner_id", details.get("object_id")) == SECOND, checked
        assert not any(uri.endswith(("setProperty", "setReference", "object.set")) for uri, _, _ in task.calls)
        return
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    if drift == "metadata-before":
        dependency = task.metadata["SwitchBehavior"]["dependencies"][0]
        if prerequisite_kind == "override":
            task.metadata["OverridePlayback"]["default"] = 1
        elif prerequisite_kind == "reference":
            dependency["conditions"][0]["referenceIsSet"] = 1
        else:
            dependency["conditions"][0]["restriction"]["values"][0]["value"] = 1
    if drift == "before":
        owner_values["OutputBus" if prerequisite_kind == "reference" else "OverridePlayback"] = None if prerequisite_kind == "reference" else False
    code, executed = task.run("execute", tx)
    if drift.endswith("before"):
        assert code == 2, executed
        assert not any(uri.endswith(("setProperty", "object.set")) for uri, _, _ in task.calls)
        return
    assert code == 0, executed
    if drift == "after":
        owner_values["OutputBus" if prerequisite_kind == "reference" else "OverridePlayback"] = None if prerequisite_kind == "reference" else False
    code, verified = task.run("verify", tx)
    assert code == (2 if drift == "after" else 0), verified
    writes = [args for uri, args, _ in task.calls if uri.endswith(("setProperty", "object.set"))]
    assert len(writes) == 1
    assert writes[0].get("object", writes[0].get("objects", [{}])[0].get("object")) == FIRST
    assert owner_values["SwitchBehavior"] == 1
    reads = [options for uri, _, options in task.calls if uri.endswith("object.get")
             and any(name in options.get("return", []) for name in ("SwitchBehavior", "OverridePlayback", "OutputBus"))]
    assert reads and all(options.get("platform") == platform for options in reads)


def test_association_owner_condition_depth_budget_includes_the_original_field(tmp_path):
    task = ScalarPropertyTask(tmp_path, "2025.1")
    task.metadata = {
        "ContinuePlay": {"name": "ContinuePlay", "type": "bool", "dependencies": [{
            "type": "property", "action": "Enable", "context": "AssocParent", "property": "SwitchBehavior",
            "conditions": [{"restriction": {"type": "enum", "values": [{"value": 1}]}}],
        }]},
        "SwitchBehavior": {"name": "SwitchBehavior", "type": "int16", "dependencies": [condition("Step0")]},
    }
    for index in range(7):
        name = f"Step{index}"
        task.metadata[name] = {"name": name, "type": "bool", "dependencies": [condition(f"Step{index + 1}")] if index < 6 else []}
    task.objects[FIRST].update(name="", type="ObjectSettingAssociation", parent=None, owner={"id": SECOND}, ContinuePlay=False)
    task.objects[SECOND].update(type="SwitchContainer", SwitchBehavior=1, **{f"Step{index}": True for index in range(7)})
    target = task.bind(FIRST)
    field = task.discover(target, "ContinuePlay")
    code, declared = task.step("draft-declare-field-change", "--object-handle", target, "--field-handle", field,
                              "--business-value", "true")
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 2, checked
    assert checked["error_code"] == "REFERENCE_DEPENDENCY_LIMIT", checked
    assert not any(uri.endswith(("setProperty", "setReference", "object.set")) for uri, _, _ in task.calls)


def test_atomic_related_condition_large_repair_retains_exact_owner_at_output_boundary(tmp_path):
    task = ScalarPropertyTask(tmp_path, "2025.1", operation="object.set")
    task.metadata = {
        "ContinuePlay": {"name": "ContinuePlay", "type": "bool", "dependencies": [{
            "type": "property", "action": "Enable", "context": "AssocParent", "property": "SwitchBehavior",
            "conditions": [{"restriction": {"type": "enum", "values": [{"value": 1}]}}],
        }]},
        "SwitchBehavior": {"name": "SwitchBehavior", "type": "int16", "dependencies": [condition("OwnerMode")]},
        "OwnerMode": {"name": "OwnerMode", "type": "int16"},
    }
    task.metadata["SwitchBehavior"]["dependencies"][0]["conditions"][0]["restriction"]["values"] = [
        {"value": index + 1, "displayName": "Native enumerated prerequisite " + "x" * 100} for index in range(600)
    ]
    task.objects[FIRST].update(name="", type="ObjectSettingAssociation", parent=None, owner={"id": SECOND}, ContinuePlay=False)
    task.objects[SECOND].update(type="SwitchContainer", SwitchBehavior=1, OwnerMode=0)
    target = task.bind(FIRST)
    field = task.discover(target, "ContinuePlay")
    code, declared = task.step("draft-declare-existing", "--declaration-id", "continue-play", "--object-handle", target,
                              "--field-value", field, "true")
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 2, checked
    issue = checked["details"]["issues"][0]
    assert issue["error_code"] == "REFERENCE_ACTIVATION_REQUIRED", checked
    assert issue["details"]["owner_id"] == SECOND, checked
    assert issue["details"]["mutation_dispatched"] is False
    assert issue["details"]["repair_details"] == "exceeds_batch_check_budget_use_separate_exact_field_preview"
    assert len(json.dumps(checked).encode()) < 65536
    assert not any(uri.endswith(("setProperty", "setReference", "object.set")) for uri, _, _ in task.calls)


class NameOmittingConditionTask(ScalarPropertyTask):
    def call(self, uri, args=None, options=None):
        result = super().call(uri, args, options)
        if uri.endswith("getPropertyInfo"):
            result.pop("name", None)
            if getattr(self, "omit_type", False):
                result.pop("type", None)
        if uri.endswith("getPropertyAndReferenceNames") and getattr(self, "remove_field_token", False):
            result["return"] = [name for name in result["return"] if name != "LfoSmoothing"]
        return result


@pytest.mark.parametrize("version,operation", [(version, operation) for version in VERSIONS
    for operation in (["object.setProperty"] if version == "2021.1" else ["object.setProperty", "object.set"])])
@pytest.mark.parametrize("drift", ["none", "token-before", "type-before"])
def test_exact_discovered_field_token_binds_missing_native_name_without_inventing_metadata(tmp_path, version, operation, drift):
    task = NameOmittingConditionTask(tmp_path, version, operation=operation)
    target = task.bind(FIRST)
    code, discovered = task.step("draft-discover-fields", "--object-handle", target, "--meaning", "LfoSmoothing")
    assert code == 0, discovered
    candidate = discovered["meaning_results"][0]["candidates"][0]
    assert "name" not in candidate["metadata"]
    assert candidate["metadata"]["type"] == "Real64"
    assert candidate.get("handle"), discovered
    field = candidate["handle"]
    code, declared = (task.step("draft-declare-field-change", "--object-handle", target, "--field-handle", field,
                               "--business-value", "50") if operation == "object.setProperty" else
                      task.step("draft-declare-existing", "--declaration-id", "smoothing", "--object-handle", target,
                                "--field-value", field, "50"))
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    prepared = shown["artifact"]["prepared_operation"]
    state = prepared["pre_state"]
    groups = state.get("condition_metadata_guards", []) if operation == "object.set" else [state["condition_metadata"]]
    bound = next(info for group in groups for info in group["fields"] if info.get("field_binding", {}).get("token") == "LfoSmoothing")
    assert bound["name"] is None
    assert bound["field_binding"]["source"] == "exact_scoped_getPropertyAndReferenceNames"
    metadata_reads = [row for row in prepared["preflight_reads"] if row["uri"].endswith("getPropertyInfo")]
    assert metadata_reads and all("name" not in row["result"] for row in metadata_reads)
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    task.remove_field_token = drift == "token-before"
    task.omit_type = drift == "type-before"
    code, executed = task.run("execute", tx)
    if drift != "none":
        assert code == 2, executed
        assert not any(uri.endswith(("setProperty", "setReference", "object.set")) for uri, _, _ in task.calls)
        return
    assert code == 0, executed
    code, verified = task.run("verify", tx)
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[FIRST]["LfoSmoothing"] == 50
    assert task.objects[FIRST]["LfoWaveform"] == 3


@pytest.mark.parametrize("version", VERSIONS)
def test_missing_native_scalar_type_stops_field_acquisition_despite_proven_token(tmp_path, version):
    task = NameOmittingConditionTask(tmp_path, version)
    task.omit_type = True
    target = task.bind(FIRST)
    code, discovered = task.step("draft-discover-fields", "--object-handle", target, "--meaning", "LfoSmoothing")
    assert code == 2, discovered
    assert discovered["details"]["rejected_candidates"][0]["error_code"] == "FIELD_TYPE_UNAVAILABLE", discovered
    assert not any(uri.endswith(("setProperty", "setReference", "object.set")) for uri, _, _ in task.calls)
    assert task.objects[FIRST]["LfoSmoothing"] == 0.0


class UntypedReferenceConditionTask(AttenuationTask):
    def call(self, uri, args=None, options=None):
        result = super().call(uri, args, options)
        if uri.endswith("getPropertyInfo"):
            if not getattr(self, "native_name_present", False):
                result.pop("name", None)
            if args["property"] == "Attenuation":
                result.pop("type", None)
                if getattr(self, "remove_reference_proof", False):
                    result.pop("restriction", None)
        return result


@pytest.mark.parametrize("version,operation", [(version, operation) for version in VERSIONS
    for operation in (["object.setReference"] if version == "2021.1" else ["object.setReference", "object.set"])])
@pytest.mark.parametrize("native_name_present", [True, False])
@pytest.mark.parametrize("drift", ["none", "reference-proof-before"])
def test_native_reference_restriction_certifies_reference_when_optional_type_is_absent(tmp_path, version, operation, native_name_present, drift):
    task = UntypedReferenceConditionTask(tmp_path, version, operation=operation)
    task.native_name_present = native_name_present
    task.objects[FIRST].update(ListenerRelativeRouting=True, OverridePositioning=True)
    source, target = task.bind(FIRST), task.bind(SECOND)
    code, discovered = task.step("draft-discover-fields", "--object-handle", source, "--meaning", "Attenuation")
    assert code == 0, discovered
    candidate = discovered["meaning_results"][0]["candidates"][0]
    assert candidate["field_kind"] == "reference" and "type" not in candidate["metadata"]
    assert ("name" in candidate["metadata"]) is native_name_present
    assert candidate["value_type"] == "reference"
    field = candidate["handle"]
    code, declared = (task.step("draft-declare-field-change", "--object-handle", source, "--field-handle", field,
                               "--target-handle", target) if operation == "object.setReference" else
                      task.step("draft-declare-existing", "--declaration-id", "attenuation", "--object-handle", source,
                                "--field-value", field, target))
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    state = shown["artifact"]["prepared_operation"]["pre_state"]
    groups = state.get("condition_metadata_guards", []) if operation == "object.set" else [state["condition_metadata"]]
    reference_metadata = next(info for group in groups for info in group["fields"]
                              if info.get("restriction", {}).get("type") == "reference")
    assert reference_metadata["type"] is None
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    task.remove_reference_proof = drift != "none"
    code, executed = task.run("execute", tx)
    if drift != "none":
        assert code == 2, executed
        assert not any(uri.endswith(("setProperty", "setReference", "object.set")) for uri, _, _ in task.calls)
        return
    assert code == 0, executed
    code, verified = task.run("verify", tx)
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[FIRST]["Attenuation"] == {"id": SECOND}
    assert task.objects[FIRST]["ListenerRelativeRouting"] is True
    assert task.objects[FIRST]["OverridePositioning"] is True


@pytest.mark.parametrize("version,operation", [(version, operation) for version in VERSIONS
    for operation in (["object.setReference"] if version == "2021.1" else ["object.setReference", "object.set"])])
@pytest.mark.parametrize("original,current,metadata_type,expected_code", [(True, 1, "bool", 2), (1, 1.0, "int16", 0)])
def test_condition_metadata_numeric_equivalence_keeps_boolean_distinction(tmp_path, version, operation, original, current, metadata_type, expected_code):
    task = AttenuationTask(tmp_path, version, operation=operation)
    task.objects[FIRST].update(ListenerRelativeRouting=True, OverridePositioning=True, ControllerMode=original)
    task.metadata["ControllerMode"] = {"name": "ControllerMode", "type": metadata_type}
    task.metadata["Attenuation"]["dependencies"] = [condition("ControllerMode", original)]
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
    task.metadata["Attenuation"]["dependencies"][0]["conditions"][0]["restriction"]["values"][0]["value"] = current
    code, executed = task.run("execute", tx)
    assert code == expected_code, executed
    if expected_code == 2:
        assert not any(uri.endswith(("setProperty", "setReference", "object.set")) for uri, _, _ in task.calls)
        assert task.objects[FIRST]["Attenuation"] is None
        return
    code, verified = task.run("verify", tx)
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[FIRST]["Attenuation"] == {"id": SECOND}
