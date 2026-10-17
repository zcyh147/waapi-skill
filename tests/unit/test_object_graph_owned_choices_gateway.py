"""Owned graph choices retain their meaning through the public transaction chain."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_field_interface_closure_gateway import FieldTask, FIRST, SECOND, VERSIONS


ROOT = "{33333333-3333-3333-3333-333333333333}"
CHILD = "{44444444-4444-4444-4444-444444444444}"


class OwnedGraphTask(FieldTask):
    def __init__(self, path: Path, version: str, operation: str) -> None:
        super().__init__(path, version, operation)
        self.objects = {
            FIRST: {"id": FIRST, "name": "Weather", "type": "ActorMixer",
                    "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Weather",
                    "parent": {"id": SECOND}, "notes": "Keep owner", "@CustomList": []},
            SECOND: {"id": SECOND, "name": "Default Work Unit", "type": "WorkUnit",
                     "path": r"\Actor-Mixer Hierarchy\Default Work Unit", "notes": "Keep parent"},
        }
        self.types = [{"classId": 1, "name": "ActorMixer", "type": "WObject"},
                      {"classId": 2, "name": "Sound", "type": "WObject"},
                      {"classId": 3, "name": "WorkUnit", "type": "WObject"}]
        if version == "2025.1":
            self.types[0]["name"] = "PropertyContainer"
            self.objects[FIRST]["type"] = "PropertyContainer"
        self.bad_result: str | None = None

    def _create(self, node: dict[str, Any], parent: str, *, owned: bool = False) -> dict[str, Any]:
        object_id = ROOT if node["name"] == "Layers" else CHILD
        row = {"id": object_id, "name": node["name"], "type": (
                   "PropertyContainer" if self.version == "2025.1" and node["type"] == "ActorMixer" else node["type"]),
               "path": self.objects[parent]["path"] + "\\" + node["name"],
               "notes": node.get("notes", ""),
               **({"owner": {"id": parent}, "parent": None} if owned else {"parent": {"id": parent}})}
        self.objects[object_id] = row
        children = [self._create(child, object_id) for child in node.get("children", [])]
        return {"id": object_id, "name": row["name"], **({"children": children} if children else {})}

    def call(self, uri: str, args: Any = None, options: Any = None) -> Any:
        if uri.endswith("object.get") and args.get("waql") != "from type Project take 1":
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            source = args.get("from", {})
            if "id" in source:
                rows = [row for key, row in self.objects.items() if key in source["id"]]
            elif "path" in source:
                paths = {path.casefold() for path in source["path"]}
                rows = [row for row in self.objects.values() if row["path"].casefold() in paths]
            else:
                expression = args["waql"]
                assert expression.startswith('from object "'), expression
                identity = expression.split('"')[1]
                rows = [row for key, row in self.objects.items() if key == identity or row["path"] == identity]
                assert expression.endswith(" take 1"), expression
            if args.get("transform"):
                assert len(rows) == 1, args
                parent = rows[0]
                if args["transform"] == [{"select": ["children"]}]:
                    rows = [row for row in self.objects.values() if row.get("parent") == {"id": parent["id"]}]
                else:
                    assert args["transform"] == [{"select": ["descendants"]}], args
                    rows = [row for row in self.objects.values() if row["path"].startswith(parent["path"] + "\\")]
            return {"return": deepcopy(rows)}
        if uri.endswith("object.create"):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            result = self._create(args, args["parent"], owned=True)
            self.objects[args["parent"]]["@CustomList"].append({"id": ROOT})
            if self.bad_result == "owner":
                self.objects[ROOT]["owner"] = {"id": SECOND}
            elif self.bad_result == "missing-child":
                del self.objects[CHILD]
            elif self.bad_result == "duplicate-child":
                result["children"].append(deepcopy(result["children"][0]))
            return result
        if uri.endswith("object.set"):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            results = []
            for item in args["objects"]:
                row = self.objects[item["object"]]
                row["notes"] = item["notes"]
                children = [self._create(child, row["id"]) for child in item.get("children", [])]
                results.append({"id": row["id"], "name": row["name"],
                                **({"children": children} if children else {})})
            return {"objects": results}
        return super().call(uri, args, options)

    def preview(self) -> tuple[str, dict[str, Any]]:
        before = deepcopy(self.objects)
        code, checked = self.step("draft-check")
        assert code == 0, checked
        code, preview = self.step("preview-from-draft")
        assert code == 0, preview
        code, shown = self.run("transaction-show", preview["transaction_id"])
        assert code == 0, shown
        assert shown["state"] == "awaiting_confirmation"
        assert self.objects == before
        return preview["transaction_id"], shown

    def finish(self, tx: str, shown: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        code, unauthorized = self.run("execute", tx)
        assert code == 2, unauthorized
        assert not any(uri.endswith(("object.create", "object.set")) for uri, _, _ in self.calls)
        code, confirmed = self.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
        assert code == 0, confirmed
        code, executed = self.run("execute", tx)
        assert code == 0, executed
        before_verify = len(self.calls)
        result = self.run("verify", tx)
        self.verification_calls = self.calls[before_verify:]
        return result


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("conflict", ("fail", "rename", "merge"))
def test_owned_list_creation_reaches_native_dispatch_and_topology_verification(
    tmp_path: Path, version: str, conflict: str,
) -> None:
    task = OwnedGraphTask(tmp_path, version, "object.create")
    owner = task.bind(FIRST)
    code, configured = task.step("draft-business-configure", "--name-conflict", conflict)
    assert code == 0, configured
    code, root = task.step("draft-declare-new", "--declaration-id", "layers", "--parent-handle", owner,
                           "--name", "Layers", "--kind", "actor-mixer", "--field", "object_list", "CustomList")
    assert code == 0, root
    code, child = task.step("draft-declare-new", "--declaration-id", "rain", "--parent-handle",
                            root["draft"]["declared_object"]["result_handle"], "--name", "Rain", "--kind", "sound-sfx")
    assert code == 0, child
    tx, shown = task.preview()
    expected = {"parent": FIRST, "type": "ActorMixer", "name": "Layers", "list": "CustomList",
                "children": [{"type": "Sound", "name": "Rain"}], "onNameConflict": conflict,
                "autoAddToSourceControl": False}
    assert shown["artifact"]["prepared_operation"]["dispatch"]["args"] == expected
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, verified
    writes = [(uri, args, options) for uri, args, options in task.calls if uri.endswith("object.create")]
    assert writes == [("ak.wwise.core.object.create", expected, {})]
    assert task.objects[FIRST]["notes"] == "Keep owner"
    # The created root is list-owned while its descendant has an ordinary parent.
    assert task.objects[ROOT]["owner"] == {"id": FIRST}
    assert task.objects[CHILD]["parent"] == {"id": ROOT}


@pytest.mark.parametrize("version", VERSIONS[1:])
@pytest.mark.parametrize("conflict", ("fail", "rename", "merge"))
def test_set_platform_and_target_conflict_survive_preview_execute_and_verify(
    tmp_path: Path, version: str, conflict: str,
) -> None:
    task = OwnedGraphTask(tmp_path, version, "object.set")
    owner = task.bind(FIRST)
    parent = task.bind(SECOND)
    code, configured = task.step("draft-business-configure", "--platform", "Windows", "--name-conflict", "fail")
    assert code == 0, configured
    for declaration, handle, extra in (
        ("owner", owner, ["--field", "platform", "Mac", "--field", "name_conflict", conflict]),
        ("parent", parent, []),
    ):
        code, declared = task.step("draft-declare-existing", "--declaration-id", declaration,
                                   "--object-handle", handle, "--field", "notes", declaration + " updated", *extra)
        assert code == 0, declared
    code, child = task.step("draft-declare-new", "--declaration-id", "rain", "--parent-handle", owner,
                            "--name", "Rain", "--kind", "sound-sfx")
    assert code == 0, child
    tx, shown = task.preview()
    expected = {"objects": [
        {"object": FIRST, "notes": "owner updated", "platform": "Mac", "onNameConflict": conflict,
         "children": [{"type": "Sound", "name": "Rain"}]},
        {"object": SECOND, "notes": "parent updated"},
    ], "platform": "Windows", "onNameConflict": "fail", "listMode": "append", "autoAddToSourceControl": False}
    assert shown["artifact"]["prepared_operation"]["dispatch"]["args"] == expected
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, verified
    writes = [(args, options) for uri, args, options in task.calls if uri.endswith("object.set")]
    assert len(writes) == 1 and writes[0][0] == expected
    views = {(args["from"]["id"][0], options.get("platform"))
             for uri, args, options in task.verification_calls
             if uri.endswith("object.get") and "id" in args.get("from", {})}
    assert (FIRST, "Mac") in views and (SECOND, "Windows") in views and (CHILD, "Mac") in views


@pytest.mark.parametrize("bad_result", ("owner", "missing-child", "duplicate-child"))
def test_owned_list_creation_does_not_certify_malformed_or_partial_native_effects(
    tmp_path: Path, bad_result: str,
) -> None:
    task = OwnedGraphTask(tmp_path, "2025.1", "object.create")
    owner = task.bind(FIRST)
    code, root = task.step("draft-declare-new", "--declaration-id", "layers", "--parent-handle", owner,
                           "--name", "Layers", "--kind", "actor-mixer", "--field", "object_list", "CustomList")
    assert code == 0, root
    code, child = task.step("draft-declare-new", "--declaration-id", "rain", "--parent-handle",
                            root["draft"]["declared_object"]["result_handle"], "--name", "Rain", "--kind", "sound-sfx")
    assert code == 0, child
    tx, shown = task.preview()
    task.bad_result = bad_result
    code, verified = task.finish(tx, shown)
    assert code == 2, verified
    assert verified.get("verified") is not True
    assert verified["state"] in {"verification_failed", "executed_unverified"}, verified
