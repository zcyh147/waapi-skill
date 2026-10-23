"""Existing-instance condition behavior from sealed class-metadata facts only."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.unit.test_conditional_reference_gateway import ScalarPropertyTask, FIRST, condition_product_capture


FACTS = json.loads((Path(__file__).parents[1] / "fixtures/metadata-conditions/3d-audio-bed-mixer.json").read_text())


def bed_mixer_task(tmp_path, version, operation, policy):
    facts = FACTS["versions"][version]
    task = ScalarPropertyTask(tmp_path, version, operation)
    task.metadata = {name: deepcopy(field["metadata"]) for name, field in facts["fields"].items()}
    task.types = [deepcopy(facts["class"])]
    task.objects[FIRST].update(name="OwnedBedMixer", type="Effect", classId=facts["class"]["classId"], path=r"\Effects\Default Work Unit\OwnedBedMixer",
                               SystemAudioObjectLimit=64, SystemAudioObjectsPolicy=policy)
    task.enabled = policy in (0, 1)
    return task


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
@pytest.mark.parametrize("operation", ["object.setProperty", "object.set"])
@pytest.mark.parametrize("policy", [0, 1, 2])
def test_existing_bed_mixer_limit_preserves_satisfied_policy_or_requires_explicit_choice(tmp_path, version, operation, policy):
    task = bed_mixer_task(tmp_path, version, operation, policy)
    before = deepcopy(task.objects)
    target = task.bind(FIRST)
    field = task.discover(target, "SystemAudioObjectLimit")
    code, declared = (task.step("draft-declare-field-change", "--object-handle", target, "--field-handle", field,
                              "--business-value", "128") if operation == "object.setProperty" else
                      task.step("draft-declare-existing", "--declaration-id", "limit", "--object-handle", target,
                                "--field-value", field, "128"))
    assert code == 0, declared
    code, checked = task.step("draft-check")
    if policy == 2:
        assert code == 2, checked
        assert "SystemAudioObjectsPolicy" in json.dumps(checked)
        assert task.objects == before
        assert not any(uri.endswith(("setProperty", "setReference", "object.set")) for uri, _, _ in task.calls)
        return
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    assert not preview["preview_summary"].get("derived_changes"), preview
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    code, executed = task.run("execute", tx)
    assert code == 0, executed
    code, verified = task.run("verify", tx)
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects == {**before, FIRST: {**before[FIRST], "SystemAudioObjectLimit": 128}}
    assert sum(uri.endswith(("setProperty", "setReference", "object.set")) for uri, _, _ in task.calls) == 1


@pytest.mark.parametrize("version,condition_product_capture", [
    ("2022.1", "existing-bed-mixer-2022.1"), ("2025.1", "existing-bed-mixer-2025.1")], indirect=["condition_product_capture"])
def test_product_existing_bed_mixer_condition_preserves_native_uint16_policy(tmp_path, version, condition_product_capture):
    task = bed_mixer_task(tmp_path, version, "object.setProperty", 1)
    before = deepcopy(task.objects)
    target = task.bind(FIRST)
    field = task.discover(target, "SystemAudioObjectLimit")
    code, declared = task.step("draft-declare-field-change", "--object-handle", target, "--field-handle", field, "--business-value", "128")
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    assert not preview["preview_summary"].get("derived_changes"), preview
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    code, executed = task.run("execute", tx)
    assert code == 0, executed
    code, verified = task.run("verify", tx)
    assert code == 0 and verified["verified"] is True, verified
    after = deepcopy(task.objects)
    assert after == {**before, FIRST: {**before[FIRST], "SystemAudioObjectLimit": 128}}
    writes = [{"uri": uri, "args": args, "options": options} for uri, args, options in task.calls
              if uri.endswith(("setProperty", "setReference", "object.set"))]
    assert len(writes) == 1 and writes[0]["args"]["property"] == "SystemAudioObjectLimit"
    condition_product_capture.update(
        gateway={"argv": ["--state-dir", str(task.path / "state"), "verify", tx], "exit_code": code, "payload": verified},
        native_call=writes[0], observations={"wwise-console": {"metadata": deepcopy(task.metadata["SystemAudioObjectLimit"]),
            "observations": [{"controller_before": before[FIRST], "controller_after": after[FIRST],
                "before": before[FIRST], "after": after[FIRST]}]}},
        recorded_class_metadata_provenance=deepcopy(FACTS["versions"][version]),
    )


@pytest.mark.parametrize("version", ["2022.1", "2023.1", "2024.1", "2025.1"])
def test_public_bed_shareset_setup_then_limit_edit_uses_one_selected_platform(tmp_path, version):
    from tests.unit.test_new_object_conditions_gateway import ClassTask
    from tests.unit.test_gameparameter_class_fields_gateway import CREATED
    from tests.unit.test_time_modulator_range_gateway import start, finish
    platform = "{33333333-3333-3333-3333-333333333333}"
    facts = FACTS["versions"][version]
    task = ClassTask(tmp_path, version, class_name="Effect")
    task.class_id = facts["class"]["classId"]
    task.types = [row for row in task.types if row["name"] != "Effect"] + [deepcopy(facts["class"])]
    task.objects[FIRST].update(classId=1638416, path=r"\Effects\Default Work Unit")
    for row in task.types:
        if row["name"] == "WorkUnit":
            row["classId"] = 1638416
    # Explicit installed defaults/supports supplement the compact input facts;
    # other-version models are never labeled native metadata captures.
    task.metadata = {name: {**deepcopy(row["metadata"]), "default": 64 if name == "SystemAudioObjectLimit" else 0,
        "supports": {"unlink": True}} for name, row in facts["fields"].items()}
    before = deepcopy(task.objects)
    original = task.call

    def selected_view(uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri.endswith("object.get") and any(field.lstrip("@") in task.metadata for field in options.get("return", [])):
            assert options.get("platform") == platform, (args, options)
        if uri.endswith("isPropertyEnabled") or uri.endswith("setProperty"):
            assert args.get("platform") == platform, args
        result = original(uri, args, options)
        if uri.endswith("object.get"):
            # The ordinary class fixture stores bare scalar keys; the native
            # ShareSet verifier explicitly requests directly stored @fields.
            for row in result.get("return", []):
                native = task.objects.get(row.get("id"), {})
                for field in options.get("return", []):
                    if field.startswith("@") and field[1:] in task.metadata and field[1:] in native:
                        row[field] = deepcopy(native[field[1:]])
        return result

    task.call = selected_view
    task.operation = "object.createPlugin"
    start(task)
    parent = task.bind(FIRST)
    code, kinds = task.step("draft-discover-types", "--role", "effect", "--meaning", "Wwise 3D Audio Bed Mixer")
    assert code == 0, kinds
    kind, = kinds["type_candidates"]
    code, found = task.step("draft-discover-fields", "--type-handle", kind["handle"],
        "--meaning", "SystemAudioObjectsPolicy", "--platform", platform)
    assert code == 0, found
    policy = found["field_candidates"][0]["handle"]
    code, declared = task.step("draft-declare-existing", "--declaration-id", "bed", "--object-handle", parent,
        "--field", "plugin_role", "effect", "--field", "plugin_placement", "shareset",
        "--field", "plugin_name", "OwnedBed", "--field", "plugin_type_handle", kind["handle"],
        "--field", "platform", platform, "--field-value", policy, "1")
    assert code == 0, declared
    _, _, _, setup_tx = finish(task)
    created = deepcopy(task.objects[CREATED])
    assert created["type"] == "Effect" and created["classId"] == 12451843
    assert created["SystemAudioObjectsPolicy"] == 1 and created["SystemAudioObjectLimit"] == 64
    task.operation = "object.setProperty"
    start(task)
    target = task.bind(CREATED)
    code, found = task.step("draft-discover-fields", "--object-handle", target,
        "--meaning", "SystemAudioObjectLimit", "--platform", platform)
    assert code == 0, found
    field = found["meaning_results"][0]["candidates"][0]["handle"]
    code, declared = task.step("draft-declare-field-change", "--object-handle", target,
        "--field-handle", field, "--business-value", "128")
    assert code == 0, declared
    preview, _, _, tx = finish(task)
    assert tx != setup_tx and not preview["preview_summary"].get("derived_changes"), preview
    assert task.objects == {**before, CREATED: {**created, "SystemAudioObjectLimit": 128}}
    writes = [(uri, args) for uri, args, _ in task.calls if uri.endswith(("object.set", "setProperty"))]
    assert len(writes) == 2
    assert writes[0][1]["objects"] == [{"object": FIRST, "onNameConflict": "fail", "children": [
        {"type": "Effect", "name": "OwnedBed", "classId": 12451843, "platform": platform, "@SystemAudioObjectsPolicy": 1}]}]
    assert writes[1][1] == {"object": CREATED, "property": "SystemAudioObjectLimit", "value": 128, "platform": platform}
