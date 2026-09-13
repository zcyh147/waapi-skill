"""State and Switch creation use ordinary children, not invented object lists."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_field_interface_closure_gateway import FIRST, SECOND, FieldTask, VERSIONS


OPERATIONS = tuple((version, "object.create") for version in VERSIONS) + tuple(
    (version, "object.set") for version in VERSIONS[1:]
)


class GameSyncTask(FieldTask):
    """The external Wwise boundary exposes game-sync values as normal children."""

    def call(self, uri: str, args: Any = None, options: Any = None) -> Any:
        if uri.endswith("object.get"):
            fields = (options or {}).get("return", [])
            if any(field in {"@States", "@Switches"} for field in fields):
                self.calls.append((uri, args, options))
                raise RuntimeError("Unknown property States/Switches")
            if "path" in args.get("from", {}) or args.get("transform") == [
                {"select": ["children"]},
            ]:
                self.calls.append((uri, args, options))
                return {"return": []}
        return super().call(uri, args, options)


@pytest.mark.parametrize(("version", "operation"), OPERATIONS)
@pytest.mark.parametrize(("group_type", "value_type"), (("StateGroup", "State"), ("SwitchGroup", "Switch")))
def test_game_sync_value_reaches_preview_through_normal_children(
    tmp_path: Path, version: str, operation: str, group_type: str, value_type: str,
) -> None:
    task = GameSyncTask(tmp_path, version, operation)
    hierarchy = "States" if value_type == "State" else "Switches"
    task.objects[FIRST] = {
        "id": FIRST, "name": "Group", "type": group_type,
        "path": f"\\{hierarchy}\\Default Work Unit\\Group",
    }
    task.types = [
        {"classId": 1, "name": group_type, "type": "WObject"},
        {"classId": 2, "name": value_type, "type": "WObject"},
    ]
    parent = task.bind(FIRST)
    code, found = task.step(
        "draft-discover-types", "--meaning", value_type, "--role", "object",
    )
    assert code == 0, found
    kind = next(row["handle"] for row in found["type_candidates"] if row["label"] == value_type)
    code, declared = task.step(
        "draft-declare-new", "--declaration-id", "value",
        "--parent-handle", parent, "--name", "New Value", "--kind", kind,
    )
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    assert preview["transaction_id"].startswith("tx1-"), preview
    assert preview["state"] == "awaiting_confirmation", preview
    for uri, _args, options in task.calls:
        assert not uri.endswith(("object.create", "object.set")), task.calls
        assert not {"@States", "@Switches"}.intersection((options or {}).get("return", []))
    if operation == "object.set":
        assert any(
            uri.endswith("object.get") and args.get("transform") == [{"select": ["children"]}]
            for uri, args, _options in task.calls
        ), task.calls


def _move_task(tmp_path: Path, version: str, operation: str, value_type: str,
               *, same_group: bool = False) -> GameSyncTask:
    task = GameSyncTask(tmp_path, version, operation)
    source_group = "{33333333-3333-3333-3333-333333333333}"
    hierarchy = "States" if value_type == "State" else "Switches"
    task.objects = {
        FIRST: {
            "id": FIRST, "name": "Value", "type": value_type,
            "path": f"\\{hierarchy}\\Default Work Unit\\Source\\Value",
            "parent": {"id": source_group}, "notes": "",
        },
        SECOND: {
            "id": SECOND, "name": "Destination", "type": value_type + "Group",
            "path": f"\\{hierarchy}\\Default Work Unit\\Destination", "notes": "",
        },
        source_group: {
            "id": source_group, "name": "Source", "type": value_type + "Group",
            "path": f"\\{hierarchy}\\Default Work Unit\\Source", "notes": "",
        },
    }
    for role, value in (("object", FIRST), ("parent", source_group if same_group else SECOND)):
        code, bound = task.step("draft-bind-object", "--role", role, "--object-id", value)
        assert code == 0, bound
    code, declared = task.step("draft-declare-object-change", "--name-conflict", "fail")
    assert code == 0, declared
    return task


@pytest.mark.parametrize("version", VERSIONS[2:])
@pytest.mark.parametrize("value_type", ("State", "Switch"))
def test_newer_game_sync_reparent_stops_before_preview(
    tmp_path: Path, version: str, value_type: str,
) -> None:
    """2023–25 Console probes reject this move; 2021/22 probes succeed."""
    task = _move_task(tmp_path, version, "object.move", value_type)
    code, rejected = task.step("draft-check")
    assert code == 2, rejected
    assert rejected["error_code"] == "GAME_SYNC_REPARENT_UNSUPPORTED", rejected
    assert rejected["details"]["version"] == version, rejected
    assert rejected["details"]["object_type"] == value_type, rejected
    assert not rejected.get("transaction_id"), rejected
    assert not any(uri.endswith("object.move") for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", VERSIONS[:2])
@pytest.mark.parametrize("value_type", ("State", "Switch"))
def test_older_game_sync_move_still_reaches_preview(
    tmp_path: Path, version: str, value_type: str,
) -> None:
    task = _move_task(tmp_path, version, "object.move", value_type)
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0 and preview["state"] == "awaiting_confirmation", preview


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("value_type", ("State", "Switch"))
def test_game_sync_move_boundary_does_not_disable_copy(
    tmp_path: Path, version: str, value_type: str,
) -> None:
    task = _move_task(tmp_path, version, "object.copy", value_type)
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0 and preview["state"] == "awaiting_confirmation", preview


@pytest.mark.parametrize("version", VERSIONS[2:])
@pytest.mark.parametrize("value_type", ("State", "Switch"))
def test_game_sync_reparent_boundary_does_not_apply_to_same_group(
    tmp_path: Path, version: str, value_type: str,
) -> None:
    task = _move_task(tmp_path, version, "object.move", value_type, same_group=True)
    code, checked = task.step("draft-check")
    assert code == 0, checked
