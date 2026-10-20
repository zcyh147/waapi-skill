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
