"""Exact Parent Show input facts through existing-object Gateway changes."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.unit.test_conditional_reference_gateway import (
    ScalarPropertyTask, FIRST, SECOND, VERSIONS, condition_product_capture,
)


FACTS = json.loads((Path(__file__).parents[1] / "fixtures/metadata-conditions/parent-weight-show.json").read_text())


def change_weight(tmp_path, version, operation, mode):
    task = ScalarPropertyTask(tmp_path, version, operation)
    task.metadata = deepcopy(FACTS["versions"][version]["fields"])
    task.objects[FIRST].update(name="OwnedWeight", type="Sound", path=r"\Actor-Mixer Hierarchy\Default Work Unit\OwnedContainer\OwnedWeight",
                               parent={"id": SECOND}, Weight=50.0)
    task.objects[SECOND].update(name="OwnedContainer", type="RandomSequenceContainer",
                                path=r"\Actor-Mixer Hierarchy\Default Work Unit\OwnedContainer", RandomOrSequence=mode)
    before = deepcopy(task.objects)
    source = task.bind(FIRST)
    field = task.discover(source, "Weight")
    code, declared = (task.step("draft-declare-field-change", "--object-handle", source, "--field-handle", field,
                              "--business-value", "37") if operation == "object.setProperty" else
                      task.step("draft-declare-existing", "--declaration-id", "weight", "--object-handle", source,
                                "--field-value", field, "37"))
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
    assert after == {**before, FIRST: {**before[FIRST], "Weight": 37}}
    writes = [{"uri": uri, "args": args, "options": options} for uri, args, options in task.calls
              if uri.endswith(("setProperty", "setReference", "object.set"))]
    assert len(writes) == 1
    if operation == "object.setProperty":
        assert writes[0]["args"]["object"] == FIRST and writes[0]["args"]["property"] == "Weight"
    else:
        assert writes[0]["args"]["objects"] == [{"object": FIRST, "@Weight": 37}]
    return task, before, after, writes[0], code, verified, tx


@pytest.mark.parametrize("version,operation", [(v, op) for v in VERSIONS for op in ("object.setProperty", "object.set")
                                             if v != "2021.1" or op != "object.set"])
@pytest.mark.parametrize("mode", [0, 1])
def test_recorded_parent_show_condition_preserves_parent_in_both_visibility_states(tmp_path, version, operation, mode):
    change_weight(tmp_path, version, operation, mode)


@pytest.mark.parametrize("version,condition_product_capture", [(v, f"parent-weight-show-{v}") for v in VERSIONS],
                         indirect=["condition_product_capture"])
def test_product_parent_weight_show_changes_child_without_changing_parent(tmp_path, version, condition_product_capture):
    task, before, after, write, code, verified, tx = change_weight(tmp_path, version, "object.setProperty", 0)
    condition_product_capture.update(
        gateway={"argv": ["--state-dir", str(task.path / "state"), "verify", tx], "exit_code": code, "payload": verified},
        native_call=write, observations={"wwise-console": {"metadata": deepcopy(task.metadata["Weight"]),
            "observations": [{"controller_before": before[SECOND], "controller_after": after[SECOND],
                "before": before[FIRST], "after": after[FIRST]}]}},
        recorded_input_provenance=deepcopy(FACTS["versions"][version]),
    )
