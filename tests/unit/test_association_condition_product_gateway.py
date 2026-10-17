"""One exact observed association context, with unobserved facts explicit."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.unit.test_conditional_reference_gateway import ScalarPropertyTask, FIRST, SECOND, condition_product_capture


FACTS = json.loads((Path(__file__).parents[1] / "fixtures/metadata-conditions/association-continue-play-2025.json").read_text())


class AssociationTask(ScalarPropertyTask):
    def __init__(self, path):
        super().__init__(path, "2025.1")
        self.metadata = {"ContinuePlay": deepcopy(FACTS["field_metadata"]),
                         "SwitchBehavior": deepcopy(FACTS["owner_metadata_model"])}
        self.objects[FIRST].update(**FACTS["relationship"]["source"],
            path=r"\Containers\OwnedSwitch\<Unnamed Object Setting Association>", owner={"id": SECOND},
            ContinuePlay=FACTS["relationship"]["source_value"])
        self.objects[SECOND].update(name="OwnedSwitch", type=FACTS["relationship"]["owner_type"],
            path=r"\Containers\OwnedSwitch", SwitchBehavior=FACTS["relationship"]["owner_value"])

    def call(self, uri, args=None, options=None):
        if uri.endswith("getPropertyAndReferenceNames"):
            self.calls.append((uri, deepcopy(args), options))
            assert args["object"] in (FIRST, SECOND)
            return {"return": ["ContinuePlay"] if args["object"] == FIRST else ["SwitchBehavior"]}
        if uri.endswith("getPropertyInfo"):
            assert args["object"] == (FIRST if args["property"] == "ContinuePlay" else SECOND), args
        return super().call(uri, args, options)


def change_continue_play(tmp_path):
    task = AssociationTask(tmp_path)
    before = deepcopy(task.objects)
    source = task.bind(FIRST)
    field = task.discover(source, "ContinuePlay")
    code, declared = task.step("draft-declare-field-change", "--object-handle", source, "--field-handle", field, "--business-value", "true")
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
    assert after == {**before, FIRST: {**before[FIRST], "ContinuePlay": True}}
    writes = [{"uri": uri, "args": args, "options": options} for uri, args, options in task.calls
              if uri.endswith(("setProperty", "setReference", "object.set"))]
    assert len(writes) == 1 and writes[0]["args"] == {"object": FIRST, "property": "ContinuePlay", "value": True}
    owner_metadata_reads = [args for uri, args, _ in task.calls if uri.endswith("getPropertyInfo") and args["property"] == "SwitchBehavior"]
    assert len(owner_metadata_reads) >= 3 and all(row["object"] == SECOND for row in owner_metadata_reads)
    return task, before, after, writes[0], code, verified, tx


def test_recorded_association_relationship_uses_exact_owner_metadata_scope(tmp_path):
    change_continue_play(tmp_path)


def test_unsatisfied_association_owner_can_be_repaired_by_a_separately_authorized_public_preview(tmp_path):
    from tests.unit.test_time_modulator_range_gateway import start, finish
    task = AssociationTask(tmp_path)
    task.objects[SECOND]['SwitchBehavior'] = 0
    before = deepcopy(task.objects)
    source = task.bind(FIRST)
    field = task.discover(source, 'ContinuePlay')
    code, declared = task.step('draft-declare-field-change', '--object-handle', source,
        '--field-handle', field, '--business-value', 'true')
    assert code == 0, declared
    child_draft = (task.draft, task.authority, task.revision)
    code, checked = task.step('draft-check')
    assert code == 2 and checked['error_code'] == 'REFERENCE_ACTIVATION_REQUIRED', checked
    repair = checked['details']['prerequisite_changes'][0]
    assert repair['object_id'] == SECOND and repair['discovery_meaning'] == 'SwitchBehavior'
    assert repair['required_value'] == 1
    assert task.objects == before
    assert not any(uri.endswith(('setProperty', 'setReference', 'object.set')) for uri, _, _ in task.calls)

    start(task)
    owner = task.bind(repair['object_id'])
    controller = task.discover(owner, repair['discovery_meaning'])
    code, declared = task.step('draft-declare-field-change', '--object-handle', owner,
        '--field-handle', controller, '--business-value', '1')
    assert code == 0, declared
    owner_preview, _, _, _ = finish(task)
    assert not owner_preview['preview_summary'].get('derived_changes')
    assert task.objects == {**before, SECOND: {**before[SECOND], 'SwitchBehavior': 1}}

    task.draft, task.authority, task.revision = child_draft
    child_preview, _, verified, _ = finish(task)
    assert verified['verified'] is True
    assert not child_preview['preview_summary'].get('derived_changes')
    assert task.objects == {**before, SECOND: {**before[SECOND], 'SwitchBehavior': 1},
        FIRST: {**before[FIRST], 'ContinuePlay': True}}
    writes = [args for uri, args, _ in task.calls if uri.endswith('setProperty')]
    assert writes == [{'object': SECOND, 'property': 'SwitchBehavior', 'value': 1},
        {'object': FIRST, 'property': 'ContinuePlay', 'value': True}]


@pytest.mark.parametrize("condition_product_capture", ["association-continue-play-2025.1"], indirect=True)
def test_product_association_continue_play_preserves_owner(tmp_path, condition_product_capture):
    task, before, after, write, code, verified, tx = change_continue_play(tmp_path)
    condition_product_capture.update(
        gateway={"argv": ["--state-dir", str(task.path / "state"), "verify", tx], "exit_code": code, "payload": verified},
        native_call=write, observations={"wwise-console": {"metadata": deepcopy(task.metadata["ContinuePlay"]),
            "observations": [{"controller_before": before[SECOND], "controller_after": after[SECOND],
                "before": before[FIRST], "after": after[FIRST]}]}},
        input_fact_provenance=deepcopy(FACTS),
    )
