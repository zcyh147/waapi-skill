"""Owned graph choices retain their meaning through the public transaction chain."""
from __future__ import annotations

from copy import deepcopy
import json
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
        self.conflict = "fail"
        self.list_mode = "append"

    def _create(self, node: dict[str, Any], parent: str, *, owned: bool = False) -> dict[str, Any]:
        object_id = {"Layers": ROOT, "List Group": CHILD, "Rain": "{99999999-9999-9999-9999-999999999999}"}.get(node["name"], CHILD)
        if node["name"] == "Rain" and parent == FIRST:
            object_id = CHILD
        if node["name"] == "Rain" and parent == ROOT:
            object_id = CHILD
        matching = [row for row in self.objects.values() if row["name"] == node["name"] and (
            row.get("owner") == {"id": parent} if owned else row.get("parent") == {"id": parent})]
        existing = matching[0] if matching and self.conflict == "merge" else None
        if existing is not None:
            object_id = existing["id"]
        row = {**({} if existing is None else existing), "id": object_id, "name": node["name"], "type": (
                   "PropertyContainer" if self.version == "2025.1" and node["type"] == "ActorMixer" else node["type"]),
               "path": self.objects[parent]["path"] + "\\" + node["name"],
               "notes": node.get("notes", "" if existing is None else existing["notes"]),
               **({"owner": {"id": parent}, "parent": None} if owned else {"parent": {"id": parent}})}
        self.objects[object_id] = row
        row.update({key: deepcopy(value) for key, value in node.items() if key.startswith("@") and not isinstance(value, list)})
        children = [self._create(child, object_id) for child in node.get("children", [])]
        result = {"id": object_id, "name": row["name"], **({"children": children} if children else {})}
        for key, values in node.items():
            if key.startswith("@") and isinstance(values, list):
                previous = row.get(key, [])
                if self.list_mode == "replaceAll":
                    old_ids = {member["id"] for member in previous}
                    old_paths = [self.objects[old_id]["path"] for old_id in old_ids]
                    for old_id, old_row in list(self.objects.items()):
                        if old_id in old_ids or any(old_row["path"].startswith(path + "\\") for path in old_paths):
                            del self.objects[old_id]
                    previous = []
                members = [self._create(member, object_id, owned=True) for member in values]
                row[key] = [*previous, *({"id": member["id"]} for member in members if {"id": member["id"]} not in previous)]
                result[key] = members
        return result

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
            self.conflict = args.get("onNameConflict", "fail")
            result = self._create(args, args["parent"], owned=True)
            if {"id": ROOT} not in self.objects[args["parent"]]["@CustomList"]:
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
            self.conflict = args.get("onNameConflict", "fail")
            self.list_mode = args.get("listMode", "append")
            results = []
            for item in args["objects"]:
                self.list_mode = item.get("listMode", args.get("listMode", "append"))
                self.conflict = item.get("onNameConflict", args.get("onNameConflict", "fail"))
                row = self.objects[item["object"]]
                row["notes"] = item.get("notes", row["notes"])
                children = [self._create(child, row["id"]) for child in item.get("children", [])]
                results.append({"id": row["id"], "name": row["name"],
                                **({"children": children} if children else {})})
            if self.bad_result == "alter-unrequested":
                for row in self.objects.values():
                    if row["name"] == "Wind":
                        row["notes"] = "Unexpected change"
            if self.bad_result == "missing-owned-membership":
                self.objects[ROOT]["@CustomList"] = []
            elif self.bad_result == "wrong-owned-owner":
                self.objects[CHILD]["owner"] = {"id": SECOND}
            elif self.bad_result == "duplicate-owned-result":
                members = results[0]["children"][0]["@CustomList"]
                members.append(deepcopy(members[0]))
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


@pytest.mark.parametrize("version", VERSIONS[1:])
@pytest.mark.parametrize("outcome", (None, "missing-owned-membership", "wrong-owned-owner", "duplicate-owned-result"))
def test_set_creates_recursive_owned_lists_and_regular_descendants_in_one_preview(
    tmp_path: Path, version: str, outcome: str | None,
) -> None:
    task = OwnedGraphTask(tmp_path, version, "object.set")
    owner = task.bind(FIRST)
    code, root = task.step("draft-declare-new", "--declaration-id", "layers", "--parent-handle", owner,
                           "--name", "Layers", "--kind", "actor-mixer")
    assert code == 0, root
    code, member = task.step("draft-declare-new", "--declaration-id", "member", "--parent-handle",
                             root["draft"]["declared_object"]["result_handle"], "--name", "List Group", "--kind", "actor-mixer",
                             "--field", "object_list", "CustomList")
    assert code == 0, member
    code, child = task.step("draft-declare-new", "--declaration-id", "rain", "--parent-handle",
                            member["draft"]["declared_object"]["result_handle"], "--name", "Rain", "--kind", "sound-sfx",
                            "--field", "notes", "Nested rain")
    assert code == 0, child
    tx, shown = task.preview()
    native = shown["artifact"]["prepared_operation"]["dispatch"]["args"]
    assert native["objects"] == [{"object": FIRST, "children": [{"type": "ActorMixer", "name": "Layers",
        "@CustomList": [{"type": "ActorMixer", "name": "List Group", "children": [
            {"type": "Sound", "name": "Rain", "notes": "Nested rain"}]}]}]}]
    task.bad_result = outcome
    code, verified = task.finish(tx, shown)
    if outcome is not None:
        assert code == 2 and verified.get("verified") is not True, verified
        return
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[CHILD]["owner"] == {"id": ROOT}


@pytest.mark.parametrize("version", VERSIONS[1:])
@pytest.mark.parametrize("corrupt_unrequested", (False, True))
def test_set_merges_nested_list_member_preserving_unrequested_children(
    tmp_path: Path, version: str, corrupt_unrequested: bool,
) -> None:
    task = OwnedGraphTask(tmp_path, version, "object.set")
    old_child = "{77777777-7777-7777-7777-777777777777}"
    root_type = "PropertyContainer" if version == "2025.1" else "ActorMixer"
    task.objects[ROOT] = {"id": ROOT, "name": "Layers", "type": root_type,
        "path": task.objects[FIRST]["path"] + r"\Layers", "parent": {"id": FIRST}, "notes": "Keep layers",
        "@CustomList": [{"id": CHILD}]}
    task.objects[CHILD] = {"id": CHILD, "name": "List Group", "type": root_type,
        "path": task.objects[ROOT]["path"] + r"\List Group", "parent": None, "owner": {"id": ROOT}, "notes": "Keep group"}
    task.objects[old_child] = {"id": old_child, "name": "Wind", "type": "Sound",
        "path": task.objects[CHILD]["path"] + r"\Wind", "parent": {"id": CHILD}, "notes": "Keep wind"}
    owner = task.bind(FIRST)
    code, configured = task.step("draft-business-configure", "--name-conflict", "merge")
    assert code == 0, configured
    code, root = task.step("draft-declare-new", "--declaration-id", "layers", "--parent-handle", owner,
                           "--name", "Layers", "--kind", "actor-mixer")
    assert code == 0, root
    code, member = task.step("draft-declare-new", "--declaration-id", "member", "--parent-handle",
                             root["draft"]["declared_object"]["result_handle"], "--name", "List Group", "--kind", "actor-mixer",
                             "--field", "object_list", "CustomList")
    assert code == 0, member
    code, child = task.step("draft-declare-new", "--declaration-id", "rain", "--parent-handle",
                            member["draft"]["declared_object"]["result_handle"], "--name", "Rain", "--kind", "sound-sfx")
    assert code == 0, child
    tx, shown = task.preview()
    task.bad_result = "alter-unrequested" if corrupt_unrequested else None
    code, verified = task.finish(tx, shown)
    if corrupt_unrequested:
        assert code == 2 and verified.get("verified") is not True, verified
        return
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[ROOT]["notes"] == "Keep layers"
    assert task.objects[CHILD]["notes"] == "Keep group"
    assert task.objects[old_child]["notes"] == "Keep wind"


@pytest.mark.parametrize("version", VERSIONS[1:])
def test_set_clears_list_on_merged_planned_owner_and_verifies_old_member_absence(
    tmp_path: Path, version: str,
) -> None:
    task = OwnedGraphTask(tmp_path, version, "object.set")
    root_type = "PropertyContainer" if version == "2025.1" else "ActorMixer"
    task.objects[ROOT] = {"id": ROOT, "name": "Layers", "type": root_type,
        "path": task.objects[FIRST]["path"] + r"\Layers", "parent": {"id": FIRST}, "notes": "Keep layers", "@CustomList": [{"id": CHILD}]}
    task.objects[CHILD] = {"id": CHILD, "name": "Old member", "type": "Sound",
        "path": task.objects[ROOT]["path"] + r"\Old member", "parent": None, "owner": {"id": ROOT}, "notes": "Old"}
    owner = task.bind(FIRST)
    code, configured = task.step("draft-business-configure", "--name-conflict", "merge")
    assert code == 0, configured
    code, root = task.step("draft-declare-new", "--declaration-id", "layers", "--parent-handle", owner,
                           "--name", "Layers", "--kind", "actor-mixer")
    assert code == 0, root
    code, cleared = task.step("draft-clear-object-list", "--declaration-id", "layers",
                              "--object-handle", root["draft"]["declared_object"]["result_handle"], "--list-name", "CustomList")
    assert code == 0, cleared
    tx, shown = task.preview()
    assert shown["artifact"]["prepared_operation"]["dispatch"]["args"]["objects"] == [
        {"object": FIRST, "listMode": "replaceAll", "children": [{"type": "ActorMixer", "name": "Layers", "@CustomList": []}]}]
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, json.dumps(verified, ensure_ascii=False)
    assert CHILD not in task.objects


@pytest.mark.parametrize("bad_name", ("@CustomList", "Custom List", "CustomList;other", ""))
def test_nested_list_name_rejection_keeps_the_business_draft_unchanged(
    tmp_path: Path, bad_name: str,
) -> None:
    task = OwnedGraphTask(tmp_path, "2025.1", "object.set")
    owner = task.bind(FIRST)
    code, root = task.step("draft-declare-new", "--declaration-id", "layers", "--parent-handle", owner,
                           "--name", "Layers", "--kind", "actor-mixer")
    assert code == 0, root
    code, before = task.run("draft-inspect", task.draft, "--task-authority", task.authority)
    assert code == 0, before
    task.calls.clear()
    code, rejected = task.step("draft-declare-new", "--declaration-id", "member", "--parent-handle",
                               root["draft"]["declared_object"]["result_handle"], "--name", "Rain", "--kind", "sound-sfx",
                               "--field", "object_list", bad_name)
    assert code == 2 and rejected["error_code"] == "OBJECT_SET_LIST_NAME_INVALID", rejected
    code, after = task.run("draft-inspect", task.draft, "--task-authority", task.authority)
    assert code == 0 and after["draft"] == before["draft"], after
    assert task.calls == []


@pytest.mark.parametrize("version", VERSIONS[1:])
def test_nested_list_clear_preview_rejects_changed_membership_before_mutation(
    tmp_path: Path, version: str,
) -> None:
    task = OwnedGraphTask(tmp_path, version, "object.set")
    root_type = "PropertyContainer" if version == "2025.1" else "ActorMixer"
    task.objects[ROOT] = {"id": ROOT, "name": "Layers", "type": root_type,
        "path": task.objects[FIRST]["path"] + r"\Layers", "parent": {"id": FIRST}, "notes": "Keep layers", "@CustomList": []}
    owner = task.bind(FIRST)
    code, configured = task.step("draft-business-configure", "--name-conflict", "merge")
    assert code == 0, configured
    code, root = task.step("draft-declare-new", "--declaration-id", "layers", "--parent-handle", owner,
                           "--name", "Layers", "--kind", "actor-mixer")
    assert code == 0, root
    code, cleared = task.step("draft-clear-object-list", "--declaration-id", "layers",
                              "--object-handle", root["draft"]["declared_object"]["result_handle"], "--list-name", "CustomList")
    assert code == 0, cleared
    tx, shown = task.preview()
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    task.objects[CHILD] = {"id": CHILD, "name": "External", "type": "Sound", "notes": "Unreviewed",
        "path": task.objects[ROOT]["path"] + r"\External", "parent": None, "owner": {"id": ROOT}}
    task.objects[ROOT]["@CustomList"] = [{"id": CHILD}]
    code, rejected = task.run("execute", tx)
    assert code == 2, rejected
    assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", VERSIONS[1:])
def test_set_keeps_reference_bindings_local_to_each_new_graph_root(
    tmp_path: Path, version: str,
) -> None:
    task = OwnedGraphTask(tmp_path, version, "object.set")
    bus_id = "{10101010-1010-1010-1010-101010101010}"
    task.objects[bus_id] = {"id": bus_id, "name": "Weather Bus", "type": "Bus",
        "path": r"\Master-Mixer Hierarchy\Default Work Unit\Weather Bus", "notes": "Keep bus"}
    task.metadata["OutputBus"] = {"name": "OutputBus", "type": "Reference"}
    owner, bus = task.bind(FIRST), task.bind(bus_id)
    for declaration, name in (("layers", "Layers"), ("wind", "Wind")):
        code, declared = task.step("draft-declare-new", "--declaration-id", declaration,
                                   "--parent-handle", owner, "--name", name, "--kind", "actor-mixer",
                                   "--field", "output_bus", bus)
        assert code == 0, declared
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, json.dumps(verified)
    writes = [args for uri, args, _ in task.calls if uri.endswith("object.set")]
    assert len(writes) == 1
    assert [row["@OutputBus"] for row in writes[0]["objects"][0]["children"]] == [bus_id, bus_id]


@pytest.mark.parametrize("version", VERSIONS)
def test_create_merges_owned_list_root_and_descendants_preserving_existing_child(
    tmp_path: Path, version: str,
) -> None:
    task = OwnedGraphTask(tmp_path, version, "object.create")
    old_child = "{77777777-7777-7777-7777-777777777777}"
    root_type = "PropertyContainer" if version == "2025.1" else "ActorMixer"
    task.objects[FIRST]["@CustomList"] = [{"id": ROOT}]
    task.objects[ROOT] = {"id": ROOT, "name": "Layers", "type": root_type,
        "path": task.objects[FIRST]["path"] + r"\Layers", "parent": None, "owner": {"id": FIRST}, "notes": "Keep layers"}
    task.objects[old_child] = {"id": old_child, "name": "Wind", "type": "Sound",
        "path": task.objects[ROOT]["path"] + r"\Wind", "parent": {"id": ROOT}, "notes": "Keep wind"}
    owner = task.bind(FIRST)
    code, configured = task.step("draft-business-configure", "--name-conflict", "merge")
    assert code == 0, configured
    code, root = task.step("draft-declare-new", "--declaration-id", "layers", "--parent-handle", owner,
                           "--name", "Layers", "--kind", "actor-mixer", "--field", "object_list", "CustomList")
    assert code == 0, root
    code, child = task.step("draft-declare-new", "--declaration-id", "rain", "--parent-handle",
                            root["draft"]["declared_object"]["result_handle"], "--name", "Rain", "--kind", "sound-sfx")
    assert code == 0, child
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, json.dumps(verified)
    assert task.objects[ROOT]["notes"] == "Keep layers" and task.objects[old_child]["notes"] == "Keep wind"
