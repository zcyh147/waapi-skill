"""Bus-family parent constraints at the public business-declaration boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.test_field_interface_closure_gateway import FIRST, FieldTask, VERSIONS


OPERATIONS = tuple((version, "object.create") for version in VERSIONS) + tuple(
    (version, "object.set") for version in VERSIONS[1:]
)


def _task(tmp_path: Path, version: str, operation: str, parent_type: str):
    task = FieldTask(tmp_path, version, operation)
    task.objects[FIRST] = {
        "id": FIRST, "name": "Parent", "type": parent_type,
        "path": r"\Master-Mixer Hierarchy\Default Work Unit\Parent",
    }
    task.types = [
        {"classId": index, "name": name, "type": "WObject"}
        for index, name in enumerate(("Bus", "AuxBus", "Sound", "State", "Switch"), 1)
    ]
    return task, task.bind(FIRST)


def _type_handle(task: FieldTask, name: str) -> str:
    code, found = task.step(
        "draft-discover-types", "--meaning", name, "--role", "object",
    )
    assert code == 0, found
    matches = [row for row in found["type_candidates"] if row["label"] == name]
    assert len(matches) == 1, found
    return matches[0]["handle"]


def _declare(task: FieldTask, parent: str, kind: str):
    return task.step(
        "draft-declare-new", "--declaration-id", "child",
        "--parent-handle", parent, "--name", "Child", "--kind", kind,
    )


@pytest.mark.parametrize(("version", "operation"), OPERATIONS)
@pytest.mark.parametrize("parent_type", ("Bus", "AuxBus", "WorkUnit"))
@pytest.mark.parametrize("child_type", ("Bus", "AuxBus"))
def test_bus_family_accepts_reviewed_bus_children(
    tmp_path: Path, version: str, operation: str, parent_type: str, child_type: str,
) -> None:
    task, parent = _task(tmp_path, version, operation, parent_type)
    kind = _type_handle(task, child_type)
    code, declared = _declare(task, parent, kind)
    assert code == 0, declared
    assert declared["draft"]["declared_object"]["declaration_id"] == "child"
    assert not any(uri.endswith(("object.create", "object.set")) for uri, _, _ in task.calls)


@pytest.mark.parametrize(("version", "operation"), OPERATIONS)
@pytest.mark.parametrize("parent_type", ("Bus", "AuxBus"))
@pytest.mark.parametrize("child_form", ("sound-sfx", "discovered-Sound", "discovered-State"))
def test_bus_family_rejects_other_children_without_changing_draft(
    tmp_path: Path, version: str, operation: str, parent_type: str, child_form: str,
) -> None:
    task, parent = _task(tmp_path, version, operation, parent_type)
    kind = (
        _type_handle(task, child_form.removeprefix("discovered-"))
        if child_form.startswith("discovered-") else child_form
    )
    revision = task.revision
    code, rejected = _declare(task, parent, kind)
    assert code == 2, rejected
    assert rejected["error_code"] == "INVALID_CREATE_CHILD_TYPE_FOR_PARENT", rejected
    assert task.revision == revision
    assert not any(uri.endswith(("object.create", "object.set")) for uri, _, _ in task.calls)


@pytest.mark.parametrize(("version", "operation"), OPERATIONS)
@pytest.mark.parametrize(("parent_type", "child_type"), (("StateGroup", "State"), ("SwitchGroup", "Switch")))
def test_game_sync_specialized_parent_rules_remain_available(
    tmp_path: Path, version: str, operation: str, parent_type: str, child_type: str,
) -> None:
    task, parent = _task(tmp_path, version, operation, parent_type)
    code, declared = _declare(task, parent, _type_handle(task, child_type))
    assert code == 0, declared
