"""Public structural property targets preserve native identity omissions."""
from copy import deepcopy
import json

import pytest

from tests.unit.test_field_interface_closure_gateway import VERSIONS

from tests.unit.test_conditional_reference_gateway import ScalarPropertyTask, FIRST, SECOND

CHILD = "{33333333-3333-3333-3333-333333333333}"


class ContextTask(ScalarPropertyTask):
    def __init__(self, path, version="2021.1", native_type=False):
        super().__init__(path, version)
        self.objects = {
            FIRST: {"id": FIRST, "name": "", "path": r"\Containers\Shells\<Unnamed Object Setting Association>",
                "classId": 1572880, "owner": {"id": SECOND}, "notes": "", "ContinuePlay": False, "FadeInTime": 0.0},
            SECOND: {"id": SECOND, "name": "Shells", "type": "SwitchContainer", "classId": 655376,
                "path": r"\Containers\Shells", "SwitchBehavior": 1, "notes": "owner"},
            CHILD: {"id": CHILD, "name": "Concrete", "type": "RandomSequenceContainer", "classId": 589840,
                "path": r"\Containers\Shells\Concrete", "parent": {"id": SECOND},
                "switchContainerChildContext": {"id": FIRST}, "@RandomOrSequence": 1, "notes": "child"},
        }
        if native_type:
            self.objects[FIRST]["type"] = "ObjectSettingAssociation"
        self.types = [{"name": name, "classId": number, "type": "WObject"} for name, number in
            (("ObjectSettingAssoc", 1572880), ("SwitchContainer", 655376), ("RandomSequenceContainer", 589840))]
        dep = [{"type": "property", "action": "Enable", "context": "AssocParent", "property": "SwitchBehavior",
            "conditions": [{"restriction": {"type": "enum", "values": [{"value": 1}]}}]}]
        self.metadata = {
            "ContinuePlay": {"name": "ContinuePlay", "type": "bool", "default": False, "dependencies": dep,
                "supports": {"unlink": False}},
            "FadeInTime": {"name": "FadeInTime", "type": "Real64", "default": 0.0, "dependencies": deepcopy(dep),
                "restriction": {"type": "range", "min": 0, "max": 60}, "supports": {"unlink": True}},
            "SwitchBehavior": {"name": "SwitchBehavior", "type": "int16", "dependencies": [],
                "restriction": {"type": "enum", "values": [{"value": 0}, {"value": 1}]}},
        }

    def bind_context(self):
        owner, child = self.bind(SECOND), self.bind(CHILD)
        code, result = self.step("draft-bind-switch-child-context", "--owner-handle", owner, "--child-handle", child)
        assert code == 0, json.dumps(result)
        return result["bound_context"]["handle"]


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("native_type", [False, True])
@pytest.mark.parametrize("meaning,value,platform", [("ContinuePlay", True, None), ("FadeInTime", 0, None),
    ("FadeInTime", 2.5, "{44444444-4444-4444-4444-444444444444}")])
def test_existing_type_absent_context_changes_property_through_owner_child_binding(tmp_path, version, native_type, meaning, value, platform):
    task = ContextTask(tmp_path, version, native_type)
    before = deepcopy(task.objects)
    target = task.bind_context()
    code, discovered = task.step("draft-discover-fields", "--object-handle", target, "--meaning", meaning,
        *(["--platform", platform] if platform else []))
    assert code == 0, discovered
    field = discovered["meaning_results"][0]["candidates"][0]["handle"]
    code, result = task.step("draft-declare-field-change", "--object-handle", target,
        "--field-handle", field, "--business-value", json.dumps(value))
    assert code == 0, json.dumps(result)
    code, checked = task.step("draft-check")
    assert code == 0, json.dumps(checked)
    code, preview = task.step("preview-from-draft")
    assert code == 0, json.dumps(preview)
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    assert shown["artifact"]["prepared_operation"]["dispatch"]["args"] == {
        "object": FIRST, "property": meaning, "value": value, **({"platform": platform} if platform else {})}
    for command, args in (("confirm", ("--confirmation-token", shown["confirmation"]["token"])), ("execute", ()), ("verify", ())):
        code, result = task.run(command, tx, *args)
        assert code == 0, json.dumps(result)
    assert result["verified"] is True
    assert task.objects == {**before, FIRST: {**before[FIRST], meaning: value}}
    assert ("type" in task.objects[FIRST]) is native_type


def prepare(task):
    target = task.bind_context()
    field = task.discover(target, "ContinuePlay")
    code, result = task.step("draft-declare-field-change", "--object-handle", target,
        "--field-handle", field, "--business-value", "true")
    assert code == 0, result
    code, result = task.step("draft-check")
    assert code == 0, result
    code, result = task.step("preview-from-draft")
    assert code == 0, result
    tx = result["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    code, result = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, result
    return tx, shown


@pytest.mark.parametrize("damage", ["child-parent", "child-context", "context-owner", "class", "type", "catalog"])
def test_structural_binding_rejects_false_ownership_or_class_without_writes(tmp_path, damage):
    task = ContextTask(tmp_path)
    owner, child = task.bind(SECOND), task.bind(CHILD)
    if damage == "child-parent": task.objects[CHILD]["parent"] = {"id": FIRST}
    if damage == "child-context": task.objects[CHILD]["switchContainerChildContext"] = {"id": SECOND}
    if damage == "context-owner": task.objects[FIRST]["owner"] = {"id": CHILD}
    if damage == "class": task.objects[FIRST]["classId"] = 655376
    if damage == "type": task.objects[FIRST]["type"] = None
    if damage == "catalog": task.types[0]["name"] = "GuessedAssociation"
    code, result = task.step("draft-bind-switch-child-context", "--owner-handle", owner, "--child-handle", child)
    assert code == 2, result
    assert not any(uri.endswith("setProperty") for uri, _, _ in task.calls)


@pytest.mark.parametrize("phase", ["before", "after"])
@pytest.mark.parametrize("damage", ["child-parent", "context-guid", "context-owner", "native-type-presence", "class", "owner-value", "metadata", "json-type"])
def test_immutable_context_proof_and_condition_guard_reject_drift(tmp_path, phase, damage):
    task = ContextTask(tmp_path)
    task.objects[CHILD]["parent"]["future"] = {"enabled": False}
    tx, shown = prepare(task)
    if phase == "after":
        code, result = task.run("execute", tx)
        assert code == 0, result
    if damage == "child-parent": task.objects[CHILD]["parent"] = {"id": FIRST}
    if damage == "context-guid": task.objects[CHILD]["switchContainerChildContext"] = {"id": SECOND}
    if damage == "context-owner": task.objects[FIRST]["owner"] = {"id": CHILD}
    if damage == "native-type-presence": task.objects[FIRST]["type"] = "ObjectSettingAssociation"
    if damage == "class": task.objects[FIRST]["classId"] = 655376
    if damage == "owner-value": task.objects[SECOND]["SwitchBehavior"] = 0
    if damage == "metadata": task.metadata["SwitchBehavior"]["default"] = 1
    if damage == "json-type": task.objects[CHILD]["parent"]["future"]["enabled"] = 0
    code, result = task.run("execute" if phase == "before" else "verify", tx)
    assert code == 2, result
    writes = [uri for uri, _, _ in task.calls if uri.endswith("setProperty")]
    assert len(writes) == (0 if phase == "before" else 1)


def test_ordinary_exact_id_binding_still_rejects_missing_native_type(tmp_path):
    task = ContextTask(tmp_path)
    code, result = task.step("draft-bind-object", "--object-id", FIRST)
    assert code == 2, result
    assert not any(uri.endswith("setProperty") for uri, _, _ in task.calls)


def test_schema_discloses_binding_and_history_recovery_boundary(tmp_path):
    task = ContextTask(tmp_path, "2025.1")
    code, result = task.run("--version", "2025.1", "operation-schema", "object.setProperty")
    assert code == 0, result
    binding = result["business_adapter"]["structural_property_target"]
    assert binding["subcommand"] == "draft-bind-switch-child-context"
    assert binding["history_recovery"] == {"status": "unavailable", "tracking_issue": 192}
    tx, shown = prepare(task)
    for command in ("execute", "verify"):
        code, result = task.run(command, tx)
        assert code == 0, result
    code, started = task.run("draft-start", "ak.wwise.core.undo.undo")
    assert code == 0, started
    code, result = task.run("draft-declare-core-plan", started["draft"]["draft_id"],
        "--task-authority", started["task_authority"], "--expected-revision", str(started["draft"]["revision"]),
        "--value", "history_scope", "latest_project_history", "--value", "expectation_receipt", tx)
    assert code == 2 and "#192" in result["message"], result
    assert not any(uri == "ak.wwise.core.undo.undo" for uri, _, _ in task.calls)


def test_dropped_write_fails_verification_and_execution_is_once_only(tmp_path):
    task = ContextTask(tmp_path)
    tx, _ = prepare(task)
    original = task.call
    def dropped(uri, args=None, options=None):
        if uri.endswith("setProperty"):
            task.calls.append((uri, deepcopy(args), options))
            return {}
        return original(uri, args, options)
    task.call = dropped
    code, result = task.run("execute", tx)
    assert code == 0, result
    code, result = task.run("execute", tx)
    assert code == 2, result
    code, result = task.run("verify", tx)
    assert code == 2 and result.get("verified") is not True, result
    assert sum(uri.endswith("setProperty") for uri, _, _ in task.calls) == 1


def test_context_proof_revalidates_before_field_discovery(tmp_path):
    task = ContextTask(tmp_path)
    target = task.bind_context()
    task.objects[CHILD]["switchContainerChildContext"] = {"id": SECOND}
    code, result = task.step("draft-discover-fields", "--object-handle", target, "--meaning", "ContinuePlay")
    assert code == 2, result
    assert not any(uri.endswith("setProperty") for uri, _, _ in task.calls)


def test_other_operation_cannot_mint_a_structural_property_target(tmp_path):
    task = ContextTask(tmp_path)
    code, started = task.run("draft-start", "object.setReference")
    assert code == 0, started
    task.draft, task.authority, task.revision = started["draft"]["draft_id"], started["task_authority"], started["draft"]["revision"]
    owner, child = task.bind(SECOND), task.bind(CHILD)
    code, result = task.step("draft-bind-switch-child-context", "--owner-handle", owner, "--child-handle", child)
    assert code == 2, result
    assert not any(uri.endswith("setProperty") for uri, _, _ in task.calls)


def test_structural_binding_is_disclosed_by_draft_continuation(tmp_path):
    task = ContextTask(tmp_path)
    code, result = task.run("draft-inspect", task.draft, "--task-authority", task.authority)
    assert code == 0, result
    # Discovery is available in the complete generated continuation; no Skill
    # prose or caller-authored proof is needed to learn the new command.
    assert "draft-bind-switch-child-context" in json.dumps(result["draft"]["next_action_binding"])


def test_structural_binding_public_receipt_replays_through_formal_business_consumer(tmp_path, monkeypatch):
    from tests.semantic.support.codex_gateway_broker import ExpectedGatewayStep
    from tests.semantic.support.codex_typed_draft_evidence_v3 import validate_typed_draft_evidence
    original = ContextTask.run
    steps, records = [], []
    def recorded(self, *argv):
        code, result = original(self, *argv)
        name = f"tx01.step{len(steps):03}"
        steps.append(ExpectedGatewayStep(name, argv[0], tuple(argv[1:])))
        records.append({"step_name": name, "succeeded": code == 0,
            "gateway_arguments": list(argv), "payload": result})
        return code, result
    monkeypatch.setattr(ContextTask, "run", recorded)
    task = ContextTask(tmp_path)
    prepare(task)
    evidence = validate_typed_draft_evidence(state_directory=task.path / "state", steps=steps, broker_records=records)
    assert evidence["canonical_request"]["arguments"]["switch_child_context"]["context_id"] == FIRST
