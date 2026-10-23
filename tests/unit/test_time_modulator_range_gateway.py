"""Public range workflow from recorded class metadata; native effects missing."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.unit.test_conditional_reference_gateway import ScalarPropertyTask, FIRST, condition_product_capture

FACTS = json.loads((Path(__file__).parents[1] / "fixtures/metadata-conditions/time-modulator-range.json").read_text())
VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")


def start(task):
    code, payload = task.run("draft-start", task.operation)
    assert code == 0, payload
    task.draft, task.authority, task.revision = payload["draft"]["draft_id"], payload["task_authority"], payload["draft"]["revision"]


def time_task(tmp_path, version, loops=50, operation="object.setProperty"):
    task = ScalarPropertyTask(tmp_path, version, operation)
    facts = FACTS["versions"][version]
    task.metadata = {"EnvelopeStopPlayback": deepcopy(facts["field_metadata"]), "TimeModLoops": deepcopy(facts["controller_metadata_model"])}
    task.set_object_type(FIRST, "ModulatorTime", facts["metadata_scope"]["resolved"]["classId"])
    task.objects[FIRST].update(name="OwnedTime",
        path=r"\Modulators\Default Work Unit\OwnedTime", TimeModLoops=loops, EnvelopeStopPlayback=True)
    return task


def declare(task, field_name, value):
    target = task.bind(FIRST)
    field = task.discover(target, field_name)
    code, payload = task.step("draft-declare-field-change", "--object-handle", target, "--field-handle", field,
                              "--business-value", json.dumps(value))
    assert code == 0, payload


def finish(task):
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
    return preview, code, verified, tx


@pytest.mark.parametrize("version", ["2021.1", "2025.1"])
@pytest.mark.parametrize("loops", [1, 50, 100])
def test_recorded_range_preserves_endpoints_and_representative_satisfied_interior(tmp_path, version, loops):
    task = time_task(tmp_path, version, loops)
    before = deepcopy(task.objects)
    declare(task, "EnvelopeStopPlayback", False)
    preview, _, _, _ = finish(task)
    assert not preview["preview_summary"].get("derived_changes"), preview
    assert task.objects == {**before, FIRST: {**before[FIRST], "EnvelopeStopPlayback": False}}


@pytest.mark.parametrize("version", ["2021.1", "2025.1"])
def test_outside_range_requires_explicit_user_prerequisite_without_selecting_a_number(tmp_path, version):
    task = time_task(tmp_path, version, loops=0)
    before = deepcopy(task.objects)
    declare(task, "EnvelopeStopPlayback", False)
    code, checked = task.step("draft-check")
    assert code == 2 and "REFERENCE_ACTIVATION_REQUIRED" in json.dumps(checked), checked
    assert task.objects == before
    assert not any(uri.endswith(("setProperty", "object.set")) for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", ["2021.1", "2025.1"])
def test_explicit_separately_authorized_range_repair_precedes_dependent_edit(tmp_path, version):
    task = time_task(tmp_path, version, loops=0)
    before = deepcopy(task.objects)
    declare(task, "TimeModLoops", 25)
    _, _, _, first_tx = finish(task)
    assert task.objects == {**before, FIRST: {**before[FIRST], "TimeModLoops": 25}}
    start(task)
    declare(task, "EnvelopeStopPlayback", False)
    _, _, _, second_tx = finish(task)
    assert second_tx != first_tx
    assert task.objects == {**before, FIRST: {**before[FIRST], "TimeModLoops": 25, "EnvelopeStopPlayback": False}}
    writes = [args for uri, args, _ in task.calls if uri.endswith("setProperty")]
    assert writes == [{"object": FIRST, "property": "TimeModLoops", "value": 25},
                      {"object": FIRST, "property": "EnvelopeStopPlayback", "value": False}]


def test_explicit_range_repair_and_dependent_change_share_one_atomic_preview_when_supported(tmp_path):
    task = time_task(tmp_path, "2025.1", loops=0, operation="object.set")
    before = deepcopy(task.objects)
    target = task.bind(FIRST)
    loops = task.discover(target, "TimeModLoops")
    stop = task.discover(target, "EnvelopeStopPlayback")
    code, declared = task.step("draft-declare-existing", "--declaration-id", "explicit-loop-count",
        "--object-handle", target, "--field-value", loops, "25", "--field-value", stop, "false")
    assert code == 0, declared
    preview, _, _, _ = finish(task)
    assert not preview["preview_summary"].get("derived_changes"), preview
    assert task.objects == {**before, FIRST: {**before[FIRST], "TimeModLoops": 25, "EnvelopeStopPlayback": False}}
    writes = [args for uri, args, _ in task.calls if uri.endswith("object.set")]
    assert len(writes) == 1 and writes[0]["objects"] == [{"object": FIRST, "@EnvelopeStopPlayback": False, "@TimeModLoops": 25}]


@pytest.mark.parametrize("version", VERSIONS)
def test_exact_time_class_public_edit_preserves_loop_count_and_peer(tmp_path, version):
    from tests.unit.test_new_object_conditions_gateway import ClassTask
    from tests.unit.test_gameparameter_class_fields_gateway import CREATED
    task = ClassTask(tmp_path, version)
    facts = FACTS["versions"][version]
    task.metadata = {"EnvelopeStopPlayback": {**deepcopy(facts["field_metadata"]), "default": True},
        "TimeModLoops": {**deepcopy(facts["controller_metadata_model"]), "default": 1}}
    task.objects[FIRST].update(classId=1638416, path=r"\Modulators\Default Work Unit")
    for row in task.types:
        if row["name"] == "WorkUnit":
            row["classId"] = 1638416
    before = deepcopy(task.objects)
    task.declare(TimeModLoops=50)
    _, _, _, setup_tx = finish(task)
    assert task.objects[CREATED]["type"] == "ModulatorTime" and task.objects[CREATED]["classId"] == 5111824
    assert task.objects[CREATED]["TimeModLoops"] == 50 and task.objects[CREATED]["EnvelopeStopPlayback"] is True
    created = deepcopy(task.objects[CREATED])
    task.operation = "object.setProperty"
    start(task)
    target = task.bind(CREATED)
    field = task.discover(target, "EnvelopeStopPlayback")
    code, declared = task.step("draft-declare-field-change", "--object-handle", target,
        "--field-handle", field, "--business-value", "false")
    assert code == 0, declared
    preview, _, verified, tx = finish(task)
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    prepared = shown["artifact"]["prepared_operation"]
    assert prepared["resolved_roles"]["object"]["row"]["type"] == "ModulatorTime"
    assert prepared["pre_state"]["field_before"]["activation_requirements"] == {"TimeModLoops": 50}
    assert not preview["preview_summary"].get("derived_changes"), preview
    assert task.objects == {**before, CREATED: {**created, "EnvelopeStopPlayback": False}}
    assert verified["verified"] is True and setup_tx != tx
    writes = [(uri, args) for uri, args, _ in task.calls if uri.endswith(("object.create", "setProperty"))]
    assert len(writes) == 2 and writes[0][0].endswith("object.create")
    assert writes[0][1]["type"] == "ModulatorTime" and writes[0][1]["@TimeModLoops"] == 50
    assert "@EnvelopeStopPlayback" not in writes[0][1]
    assert writes[1][1] == {"object": CREATED, "property": "EnvelopeStopPlayback", "value": False}


@pytest.mark.parametrize("version,condition_product_capture", [(v, f"time-modulator-range-{v}") for v in ("2021.1", "2025.1")],
                         indirect=["condition_product_capture"])
def test_product_time_modulator_range_preserves_explicit_satisfied_loop_count(tmp_path, version, condition_product_capture):
    task = time_task(tmp_path, version)
    before = deepcopy(task.objects[FIRST])
    declare(task, "EnvelopeStopPlayback", False)
    _, code, verified, tx = finish(task)
    after = deepcopy(task.objects[FIRST])
    assert after == {**before, "EnvelopeStopPlayback": False}
    writes = [{"uri": uri, "args": args, "options": options} for uri, args, options in task.calls if uri.endswith("setProperty")]
    assert len(writes) == 1
    condition_product_capture.update(
        gateway={"argv": ["--state-dir", str(task.path / "state"), "verify", tx], "exit_code": code, "payload": verified},
        native_call=writes[0], observations={"wwise-console": {"metadata": deepcopy(task.metadata["EnvelopeStopPlayback"]),
            "observations": [{"controller_before": before, "controller_after": after, "before": before, "after": after}]}},
        input_fact_provenance=deepcopy(FACTS["versions"][version]),
    )
