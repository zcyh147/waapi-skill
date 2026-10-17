"""Copy and move replace one exact reviewed destination subtree once."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_field_interface_closure_gateway import FIRST, SECOND, VERSIONS
from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, ROOT, CHILD


SOURCE_PARENT = "{55555555-5555-5555-5555-555555555555}"
SOURCE_CHILD = "{66666666-6666-6666-6666-666666666666}"
COPIED_ROOT = "{77777777-7777-7777-7777-777777777777}"
COPIED_CHILD = "{88888888-8888-8888-8888-888888888888}"


class ReplaceTask(OwnedGraphTask):
    def __init__(self, path: Path, version: str, operation: str) -> None:
        super().__init__(path, version, operation)
        root_type = "PropertyContainer" if version == "2025.1" else "ActorMixer"
        base = r"\Actor-Mixer Hierarchy\Default Work Unit"
        self.objects = {
            FIRST: {"id": FIRST, "name": "Weather", "type": root_type,
                    "path": base + r"\Sources\Weather", "parent": {"id": SOURCE_PARENT}, "notes": "Source notes"},
            SOURCE_CHILD: {"id": SOURCE_CHILD, "name": "Rain", "type": "Sound",
                           "path": base + r"\Sources\Weather\Rain", "parent": {"id": FIRST}, "notes": "Rain notes"},
            SOURCE_PARENT: {"id": SOURCE_PARENT, "name": "Sources", "type": root_type,
                            "path": base + r"\Sources", "parent": {"id": SECOND}, "notes": "Keep source parent"},
            SECOND: {"id": SECOND, "name": "Destination", "type": root_type,
                     "path": base + r"\Destination", "parent": {"id": SOURCE_PARENT}, "notes": "Keep destination"},
            ROOT: {"id": ROOT, "name": "Weather", "type": root_type,
                   "path": base + r"\Destination\Weather", "parent": {"id": SECOND}, "notes": "Replace old"},
            CHILD: {"id": CHILD, "name": "Old", "type": "Sound",
                    "path": base + r"\Destination\Weather\Old", "parent": {"id": ROOT}, "notes": "Old child"},
        }
        self.operation = operation
        self.failure: str | None = None
        self.metadata = {"Volume": {"name": "Volume", "type": "Real64"},
                         "Target": {"name": "Target", "type": "reference"}}
        for row in self.objects.values():
            row["@Volume"] = -3.0 if row["id"] in {FIRST, SOURCE_CHILD} else -8.0
            row["@Target"] = {"id": FIRST} if row["id"] == SOURCE_CHILD else None

    def declare(self) -> None:
        for role, object_id in (("object", FIRST), ("parent", SECOND)):
            code, bound = self.step("draft-bind-object", "--role", role, "--object-id", object_id)
            assert code == 0, bound
        code, declared = self.step("draft-declare-object-change", "--name-conflict", "replace")
        assert code == 0, declared

    def call(self, uri: str, args: Any = None, options: Any = None) -> Any:
        if uri.endswith(("object.copy", "object.move")):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args["object"] == FIRST and args["parent"] == SECOND
            assert args["onNameConflict"] == "replace"
            is_copy = uri.endswith("object.copy")
            old_source = deepcopy(self.objects[FIRST])
            old_child = deepcopy(self.objects[SOURCE_CHILD])
            for object_id in (ROOT, CHILD):
                if self.failure != "retained-old-child" or object_id != CHILD:
                    self.objects.pop(object_id, None)
            root_id, child_id = (COPIED_ROOT, COPIED_CHILD) if is_copy else (FIRST, SOURCE_CHILD)
            self.objects[root_id] = {**old_source, "id": root_id, "path": self.objects[SECOND]["path"] + r"\Weather", "parent": {"id": SECOND}}
            self.objects[child_id] = {**old_child, "id": child_id, "path": self.objects[root_id]["path"] + r"\Rain", "parent": {"id": root_id}}
            if is_copy:
                self.objects[child_id]["@Target"] = {"id": root_id}
            if self.failure == "changed-copy-source" and is_copy:
                self.objects[SOURCE_CHILD]["notes"] = "Wrongly altered source"
            if self.failure == "missing-new-child":
                del self.objects[child_id]
            if self.failure == "wrong-value":
                self.objects[child_id]["@Volume"] = -12.0
            if self.failure == "wrong-reference":
                self.objects[child_id]["@Target"] = {"id": SECOND}
            return {"id": root_id, "name": "Weather"}
        return super().call(uri, args, options)


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("operation", ("object.copy", "object.move"))
def test_replace_lifecycle_seals_exact_deleted_tree_and_verifies_source_distinction(
    tmp_path: Path, version: str, operation: str,
) -> None:
    task = ReplaceTask(tmp_path, version, operation)
    task.declare()
    tx, shown = task.preview()
    prepared = shown["artifact"]["prepared_operation"]
    assert prepared["dispatch"]["args"]["onNameConflict"] == "replace"
    assert {row["id"] for row in prepared["verification_plan"]["replaced_subtree_rows"]} == {ROOT, CHILD}
    code, verified = task.finish(tx, shown)
    assert code == 2 and verified.get("verified") is not True, verified
    assert verified["verification"]["business_state_verified"] is False
    assert verified["verification"]["status"] == "indeterminate"
    assert all(row["passed"] for row in verified["verification"]["assertions"])
    assert ROOT not in task.objects and CHILD not in task.objects
    if operation == "object.copy":
        assert task.objects[FIRST]["path"].endswith(r"\Sources\Weather")
        assert task.objects[SOURCE_CHILD]["notes"] == "Rain notes"
        assert task.objects[COPIED_CHILD]["parent"] == {"id": COPIED_ROOT}
    else:
        assert task.objects[FIRST]["path"].endswith(r"\Destination\Weather")
        assert task.objects[SOURCE_CHILD]["parent"] == {"id": FIRST}
    assert len([uri for uri, _, _ in task.calls if uri.endswith(("object.copy", "object.move"))]) == 1


@pytest.mark.parametrize(("operation", "failure"), [
    (operation, failure)
    for operation in ("object.copy", "object.move")
    for failure in ("retained-old-child", "missing-new-child", "wrong-value", "wrong-reference", "changed-copy-source")
    if operation == "object.copy" or failure != "changed-copy-source"
])
def test_replace_lifecycle_rejects_partial_effects_and_preservation_failures(
    tmp_path: Path, operation: str, failure: str,
) -> None:
    task = ReplaceTask(tmp_path, "2025.1", operation)
    task.declare()
    tx, shown = task.preview()
    task.failure = failure
    code, verified = task.finish(tx, shown)
    assert code == 2 and verified.get("verified") is not True, verified
    code, replay = task.run("execute", tx)
    assert code == 2, replay
    assert len([uri for uri, _, _ in task.calls if uri.endswith(("object.copy", "object.move"))]) == 1


@pytest.mark.parametrize("scope", ("source", "replacement"))
@pytest.mark.parametrize("change", ("notes", "value", "topology"))
def test_replace_revalidates_complete_source_and_destination_before_dispatch(
    tmp_path: Path, scope: str, change: str,
) -> None:
    task = ReplaceTask(tmp_path, "2025.1", "object.copy")
    task.declare()
    tx, shown = task.preview()
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    changed_id = SOURCE_CHILD if scope == "source" else CHILD
    if change == "topology":
        del task.objects[changed_id]
    else:
        task.objects[changed_id]["notes" if change == "notes" else "@Volume"] = "changed" if change == "notes" else -100.0
    code, rejected = task.run("execute", tx)
    assert code == 2, rejected
    assert not any(uri.endswith(("object.copy", "object.move")) for uri, _, _ in task.calls)


@pytest.mark.parametrize("operation", ("object.copy", "object.move"))
@pytest.mark.parametrize("collision", ("absent", "case-insensitive"))
def test_replace_keeps_native_absent_and_case_insensitive_collision_choices(
    tmp_path: Path, operation: str, collision: str,
) -> None:
    task = ReplaceTask(tmp_path, "2025.1", operation)
    if collision == "absent":
        del task.objects[ROOT], task.objects[CHILD]
    else:
        task.objects[ROOT]["name"] = "WEATHER"
        task.objects[ROOT]["path"] = task.objects[ROOT]["path"].replace("Weather", "WEATHER")
        task.objects[CHILD]["path"] = task.objects[CHILD]["path"].replace("Weather", "WEATHER")
    task.declare()
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 2 and verified["verification"]["status"] == "indeterminate", verified
    assert all(row["passed"] for row in verified["verification"]["assertions"])
