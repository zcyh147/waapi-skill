"""Actual public Gateway workflows for predeclared exact source field models."""
from copy import deepcopy
import json

from tests.unit.test_conditional_reference_gateway import ScalarPropertyTask, FIRST
from tests.unit.test_time_modulator_range_gateway import finish


def run_scalar_public_workflow(path, group):
    path.mkdir()
    model = group["model"]
    task = ScalarPropertyTask(path, group["version"])
    task.metadata = deepcopy(model["metadata"])
    task.objects[FIRST].update(deepcopy(model["before"]))
    target = task.bind(FIRST)
    code, discovered = task.step("draft-discover-fields", "--object-handle", target, "--meaning", group["field"])
    assert code == 0, discovered
    candidates = [row for row in discovered["meaning_results"][0]["candidates"]
                  if row["metadata"].get("name") == group["field"]]
    assert len(candidates) == 1, discovered
    candidate = candidates[0]
    assert candidate["metadata"] == model["metadata"][group["field"]]
    code, declared = task.step("draft-declare-field-change", "--object-handle", target,
        "--field-handle", candidate["handle"], "--business-value", json.dumps(model["requested"]))
    assert code == 0, declared
    before = deepcopy(task.objects[FIRST])
    preview, code, verified, transaction = finish(task)
    assert not preview["preview_summary"].get("derived_changes"), preview
    after = deepcopy(task.objects[FIRST])
    assert after == {**before, group["field"]: model["requested"]}
    writes = [{"uri": uri, "args": args, "options": options} for uri, args, options in task.calls
              if uri.endswith(("setProperty", "setReference", "object.set"))]
    assert len(writes) == 1
    assert writes[0]["args"] == {"object": FIRST, "property": group["field"], "value": model["requested"]}
    return {"gateway": {"argv": ["--state-dir", str(path / "state"), "verify", transaction],
                        "exit_code": code, "payload": verified},
            "native_call": writes[0], "observations": {"metadata": deepcopy(candidate["metadata"]),
                "before": before, "after": after}, "input_fact_provenance": deepcopy(model["provenance"])}
