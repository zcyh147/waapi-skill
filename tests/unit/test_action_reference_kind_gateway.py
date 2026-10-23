"""Existing Action retargeting through the public Field/Draft transaction flow."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.unit.test_field_interface_closure_gateway import FieldTask, FIRST, SECOND, VERSIONS

OLD = "{33333333-3333-3333-3333-333333333333}"
EVENT = "{44444444-4444-4444-4444-444444444444}"
SAMPLES = json.loads((Path(__file__).parents[1] / "fixtures/metadata-conditions/action-target-class-unknown.json").read_text())["samples"]


class ActionTask(FieldTask):
    def __init__(self, path, version):
        super().__init__(path, version, "object.setReference")
        # 2024/25 use a controlled unknown-kind shape, not invented native receipts.
        sample = SAMPLES.get(version, SAMPLES["2023.1"])
        self.metadata = {"Target": deepcopy(sample["metadata"]),
            "ActionType": {"name": "ActionType", "type": "int16"}}
        self.objects = {
            FIRST: {"id": FIRST, "name": "", "type": "Action", "classId": 327696,
                "path": r"\Events\Default Work Unit\Play_Rain\[Play - Rain]",
                "parent": {"id": EVENT}, "notes": "keep action", "ActionType": 1, "Target": {"id": OLD}},
            SECOND: {"id": SECOND, "name": "Wind", "type": "Sound", "classId": 65552,
                "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Wind", "notes": "keep target"},
            OLD: {"id": OLD, "name": "Rain", "type": "Sound", "classId": 65552,
                "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Rain", "notes": "keep old"},
        }
        self.types = [{"classId": 327696, "name": "Action", "type": "WObject"},
            {"classId": 65552, "name": "Sound", "type": "WObject"}]
        self.drop_write = False

    def call(self, uri, args=None, options=None):
        if uri.endswith("object.setReference"):
            self.calls.append((uri, deepcopy(args), options))
            if not self.drop_write:
                self.objects[args["object"]][args["reference"]] = {"id": args["value"]}
                # Derived display path is allowed to follow the new target.
                self.objects[FIRST]["path"] = r"\Events\Default Work Unit\Play_Rain\[Play - Wind]"
            return {}
        return super().call(uri, args, options)

    def declare(self):
        source, target = self.bind(FIRST), self.bind(SECOND)
        code, discovered = self.step("draft-discover-fields", "--object-handle", source, "--meaning", "Target")
        assert code == 0, discovered
        field, = discovered["meaning_results"][0]["candidates"]
        code, declared = self.step("draft-declare-field-change", "--object-handle", source,
            "--field-handle", field["handle"], "--target-handle", target)
        assert code == 0, declared
        return field

    def preview(self):
        code, checked = self.step("draft-check")
        assert code == 0, checked
        code, preview = self.step("preview-from-draft")
        assert code == 0, preview
        self.last_preview = preview
        code, shown = self.run("transaction-show", preview["transaction_id"])
        assert code == 0, shown
        return preview["transaction_id"], shown


@pytest.mark.parametrize("version", VERSIONS)
def test_existing_action_target_uses_documented_kind_without_inventing_native_type(tmp_path, version):
    task = ActionTask(tmp_path, version)
    before = deepcopy(task.objects)
    field = task.declare()
    assert field["field_kind"] == "reference"
    assert field["metadata"]["type"] == "" and field["metadata"]["restriction"] == {}
    assert field["kind_evidence"]["kind"] == "documented-reference-kind"
    tx, shown = task.preview()
    prepared = shown["artifact"]["prepared_operation"]
    assert prepared["pre_state"]["field_info"]["type"] == ""
    assert prepared["pre_state"]["field_info"]["reference_kind_evidence"]["object_id"] == FIRST
    assert prepared["dispatch"]["args"] == {"object": FIRST, "reference": "Target", "value": SECOND}
    notice, = task.last_preview["preview_summary"]["reference_kind_evidence"]
    assert notice["field"] == "Target" and notice["authority"] == "pinned_sdk_field_kind"
    assert notice["restrictions_authority"] == "native_getPropertyInfo"
    assert task.objects == before
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    code, executed = task.run("execute", tx)
    assert code == 0, executed
    code, verified = task.run("verify", tx)
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[FIRST] == {**before[FIRST], "Target": {"id": SECOND},
        "path": r"\Events\Default Work Unit\Play_Rain\[Play - Wind]"}
    assert task.objects[OLD] == before[OLD] and task.objects[SECOND] == before[SECOND]
    assert len([uri for uri, _, _ in task.calls if uri.endswith("setReference")]) == 1
    assert not any(uri.endswith("isPropertyEnabled") for uri, _, _ in task.calls)


def confirm(task, tx, shown):
    code, result = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, result


@pytest.mark.parametrize("version", VERSIONS)
def test_documented_reference_kind_preserves_generic_reference_restrictions_and_action_type(version, tmp_path):
    task = ActionTask(tmp_path, version)
    # Matching Help documents Set Game Parameter; no extra Sound-only kind gate.
    task.objects[FIRST]["ActionType"] = 38
    task.set_object_type(SECOND, "GameParameter", 1507344)
    field = task.declare()
    assert field["kind_evidence"]["identity"]["ActionType"] == 38
    tx, shown = task.preview()
    confirm(task, tx, shown)
    code, result = task.run("execute", tx)
    assert code == 0, result
    code, result = task.run("verify", tx)
    assert code == 0 and result["verified"] is True, result
    assert task.objects[FIRST]["ActionType"] == 38


@pytest.mark.parametrize("shape", ["omitted-type", "omitted-name-and-type", "native-type", "native-restriction"])
def test_optional_native_kind_and_name_stay_separate_from_documented_evidence(tmp_path, shape):
    task = ActionTask(tmp_path, "2025.1")
    if shape.startswith("omitted"):
        task.metadata["Target"].pop("type")
        if shape == "omitted-name-and-type":
            task.metadata["Target"].pop("name")
    elif shape == "native-type":
        task.metadata["Target"]["type"] = "Reference"
    else:
        task.metadata["Target"]["restriction"] = {"type": "reference", "restrictions": [{"type": ["Sound"]}]}
    field = task.declare()
    assert ("kind_evidence" in field) is shape.startswith("omitted")
    tx, shown = task.preview()
    confirm(task, tx, shown)
    code, result = task.run("execute", tx)
    assert code == 0, result
    code, result = task.run("verify", tx)
    assert code == 0 and result["verified"] is True, result


@pytest.mark.parametrize("damage", ["other-class", "wrong-class-id", "missing-class-id", "scalar-kind", "malformed-kind", "unknown-token", "malformed-action-type"])
def test_kind_evidence_does_not_admit_unknown_or_contradictory_fields(tmp_path, damage):
    task = ActionTask(tmp_path, "2025.1")
    if damage == "other-class":
        task.set_object_type(FIRST, "Sound", 65552)
        task.objects[FIRST].update(name="Other", path=r"\Actor-Mixer Hierarchy\Default Work Unit\Other")
    elif damage == "wrong-class-id":
        task.objects[FIRST]["classId"] = 1
    elif damage == "missing-class-id":
        task.objects[FIRST].pop("classId")
    elif damage == "scalar-kind":
        task.metadata["Target"]["type"] = "Real64"
    elif damage == "malformed-kind":
        task.metadata["Target"]["type"] = False
    elif damage == "unknown-token":
        task.metadata["Other"] = {**task.metadata.pop("Target"), "name": "Other"}
    else:
        task.objects[FIRST]["ActionType"] = True
    source = task.bind(FIRST)
    before = deepcopy(task.objects)
    code, result = task.step("draft-discover-fields", "--object-handle", source,
        "--meaning", "Other" if damage == "unknown-token" else "Target")
    assert code == 2, result
    assert task.objects == before
    assert not any(uri.endswith("setReference") for uri, _, _ in task.calls)


@pytest.mark.parametrize("phase", ["before-preview", "before-execute", "after-execute"])
@pytest.mark.parametrize("damage", ["action-type", "class-id", "native-restriction"])
def test_source_kind_identity_controller_and_metadata_drift_stop_completion(tmp_path, phase, damage):
    task = ActionTask(tmp_path, "2025.1")
    task.declare()
    if phase != "before-preview":
        tx, shown = task.preview()
        confirm(task, tx, shown)
        if phase == "after-execute":
            code, result = task.run("execute", tx)
            assert code == 0, result
    if damage == "action-type":
        task.objects[FIRST]["ActionType"] = 2
    elif damage == "class-id":
        task.objects[FIRST]["classId"] = 1
    else:
        task.metadata["Target"].pop("restriction")
    if phase == "before-preview":
        code, result = task.step("draft-check")
    else:
        code, result = task.run("verify" if phase == "after-execute" else "execute", tx)
    assert code == 2, result
    if phase != "after-execute":
        assert not any(uri.endswith("setReference") for uri, _, _ in task.calls)
    else:
        assert result.get("verified") is not True


def test_documented_kind_detects_a_dropped_write(tmp_path):
    task = ActionTask(tmp_path, "2025.1")
    task.declare()
    tx, shown = task.preview()
    task.drop_write = True
    confirm(task, tx, shown)
    code, result = task.run("execute", tx)
    assert code == 0, result
    code, result = task.run("verify", tx)
    assert code == 2 and result.get("verified") is not True, result


def test_native_target_restriction_is_not_replaced_by_kind_source(tmp_path):
    task = ActionTask(tmp_path, "2025.1")
    task.metadata["Target"]["restriction"] = {"type": "reference", "restrictions": [{"type": ["GameParameter"]}]}
    source, target = task.bind(FIRST), task.bind(SECOND)
    code, discovered = task.step("draft-discover-fields", "--object-handle", source, "--meaning", "Target")
    assert code == 0, discovered
    field, = discovered["meaning_results"][0]["candidates"]
    assert "kind_evidence" not in field
    code, rejected = task.step("draft-declare-field-change", "--object-handle", source,
        "--field-handle", field["handle"], "--target-handle", target)
    assert code == 2 and rejected["error_code"] == "REFERENCE_TARGET_TYPE_MISMATCH", rejected
    assert not any(uri.endswith("setReference") for uri, _, _ in task.calls)
