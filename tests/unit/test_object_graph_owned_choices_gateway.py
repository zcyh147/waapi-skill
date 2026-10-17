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
                result_row = {"id": row["id"], "name": row["name"],
                              **({"children": children} if children else {})}
                for key, values in item.items():
                    if key.startswith("@") and isinstance(values, list):
                        previous = [member for member in row.get(key, []) if member["id"] in self.objects]
                        members = [self._create(member, row["id"], owned=True) for member in values]
                        previous = [member for member in previous if member["id"] in self.objects]
                        row[key] = [*previous, *({"id": member["id"]} for member in members if {"id": member["id"]} not in previous)]
                        result_row[key] = members
                results.append(result_row)
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


class SetReplaceTask(OwnedGraphTask):
    """Model native replace deleting a collision before creating fresh GUIDs."""
    def __init__(self, path: Path, version: str) -> None:
        super().__init__(path, version, "object.set")
        self.retain_old_descendant = False
        self.objects[ROOT] = {"id": ROOT, "name": "LAYERS", "type": "Sound",
            "path": self.objects[FIRST]["path"] + r"\LAYERS", "parent": {"id": FIRST}, "notes": "Old root"}
        self.objects[CHILD] = {"id": CHILD, "name": "Old child", "type": "Sound",
            "path": self.objects[ROOT]["path"] + r"\Old child", "parent": {"id": ROOT}, "notes": "Old child"}
        self.old_child = deepcopy(self.objects[CHILD])
        self.objects["{77777777-7777-7777-7777-777777777777}"] = {
            "id": "{77777777-7777-7777-7777-777777777777}", "name": "Wind", "type": "Sound",
            "path": self.objects[FIRST]["path"] + r"\Wind", "parent": {"id": FIRST}, "notes": "Keep wind"}

    def call(self, uri: str, args: Any = None, options: Any = None) -> Any:
        if uri.endswith("object.set"):
            for item in args["objects"]:
                if "name" not in item:
                    continue
                source = self.objects[item["object"]]
                before_path = source["path"]
                after_path = before_path.rsplit("\\", 1)[0] + "\\" + item["name"]
                if item.get("onNameConflict", args.get("onNameConflict")) == "replace":
                    collisions = [row for row in self.objects.values() if row["id"] != source["id"]
                                  and row["path"].casefold() == after_path.casefold()]
                    for collision in collisions:
                        for object_id, row in list(self.objects.items()):
                            if object_id == collision["id"] or row["path"].startswith(collision["path"] + "\\"):
                                del self.objects[object_id]
                source["name"] = item["name"]
                for row in self.objects.values():
                    if row["path"] == before_path or row["path"].startswith(before_path + "\\"):
                        row["path"] = after_path + row["path"][len(before_path):]
        return super().call(uri, args, options)

    def _create(self, node: dict[str, Any], parent: str, *, owned: bool = False) -> dict[str, Any]:
        if self.conflict == "replace":
            collisions = [row for row in self.objects.values()
                          if row["name"].casefold() == node["name"].casefold()
                          and row.get("owner" if owned else "parent") == {"id": parent}]
            for collision in collisions:
                for object_id, row in list(self.objects.items()):
                    if object_id == collision["id"] or row["path"].startswith(collision["path"] + "\\"):
                        del self.objects[object_id]
        result = super()._create(node, parent, owned=owned)
        if self.conflict == "replace":
            # Native replacement allocates fresh IDs, even if names/types match.
            old_id = result["id"]
            new_id = {ROOT: "{88888888-8888-8888-8888-888888888888}",
                      CHILD: "{99999999-9999-9999-9999-999999999999}"}.get(old_id, old_id)
            row = self.objects.pop(old_id)
            row["id"] = result["id"] = new_id
            self.objects[new_id] = row
            for child in self.objects.values():
                if child.get("parent") == {"id": old_id}:
                    child["parent"] = {"id": new_id}
            if self.retain_old_descendant and node["name"] == "Layers":
                self.objects[CHILD] = deepcopy(self.old_child)
        return result


def _declare_set_replacement(task: SetReplaceTask, *, per_target: bool = False) -> None:
    owner = task.bind(FIRST)
    if per_target:
        code, declared = task.step("draft-declare-existing", "--declaration-id", "owner",
                                   "--object-handle", owner, "--field", "notes", "Owner updated",
                                   "--field", "name_conflict", "replace")
    else:
        code, declared = task.step("draft-business-configure", "--name-conflict", "replace")
    assert code == 0, declared
    code, root = task.step("draft-declare-new", "--declaration-id", "layers", "--parent-handle", owner,
                           "--name", "Layers", "--kind", "actor-mixer")
    assert code == 0, root
    code, child = task.step("draft-declare-new", "--declaration-id", "rain", "--parent-handle",
                            root["draft"]["declared_object"]["result_handle"], "--name", "Rain", "--kind", "sound-sfx")
    assert code == 0, child


@pytest.mark.parametrize("version", VERSIONS[1:])
@pytest.mark.parametrize("per_target", (False, True))
def test_set_replace_seals_case_insensitive_collision_and_verifies_fresh_subtree(
    tmp_path: Path, version: str, per_target: bool,
) -> None:
    task = SetReplaceTask(tmp_path, version)
    _declare_set_replacement(task, per_target=per_target)
    tx, shown = task.preview()
    prepared = shown["artifact"]["prepared_operation"]
    assert prepared["dispatch"]["args"]["objects"][0].get("onNameConflict", prepared["dispatch"]["args"]["onNameConflict"]) == "replace"
    assert {row["id"] for row in prepared["verification_plan"]["replaced_subtree_rows"]} == {ROOT, CHILD}
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, json.dumps(verified)
    assert ROOT not in task.objects and CHILD not in task.objects
    assert task.objects["{88888888-8888-8888-8888-888888888888}"]["name"] == "Layers"
    assert task.objects["{77777777-7777-7777-7777-777777777777}"]["notes"] == "Keep wind"
    assert len([uri for uri, _, _ in task.calls if uri.endswith("object.set")]) == 1


@pytest.mark.parametrize("version", VERSIONS[1:])
def test_set_replace_rejects_changed_old_subtree_before_dispatch(tmp_path: Path, version: str) -> None:
    task = SetReplaceTask(tmp_path, version)
    _declare_set_replacement(task)
    tx, shown = task.preview()
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    task.objects[CHILD]["path"] += " renamed"
    code, rejected = task.run("execute", tx)
    assert code == 2, rejected
    assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", VERSIONS[1:])
def test_set_replace_does_not_verify_surviving_old_descendant(tmp_path: Path, version: str) -> None:
    task = SetReplaceTask(tmp_path, version)
    _declare_set_replacement(task)
    tx, shown = task.preview()
    task.retain_old_descendant = True
    code, verified = task.finish(tx, shown)
    assert code == 2 and verified["verified"] is False, verified


@pytest.mark.parametrize("version", VERSIONS[1:])
def test_set_replace_list_collision_preserves_unrequested_member(tmp_path: Path, version: str) -> None:
    task = SetReplaceTask(tmp_path, version)
    task.objects[ROOT].update({"parent": None, "owner": {"id": FIRST}})
    wind = "{77777777-7777-7777-7777-777777777777}"
    task.objects[wind].update({"parent": None, "owner": {"id": FIRST}})
    task.objects[FIRST]["@CustomList"] = [{"id": ROOT}, {"id": wind}]
    owner = task.bind(FIRST)
    code, configured = task.step("draft-business-configure", "--name-conflict", "replace")
    assert code == 0, configured
    code, root = task.step("draft-declare-new", "--declaration-id", "layers", "--parent-handle", owner,
                           "--name", "Layers", "--kind", "actor-mixer", "--field", "object_list", "CustomList")
    assert code == 0, root
    code, child = task.step("draft-declare-new", "--declaration-id", "rain", "--parent-handle",
                            root["draft"]["declared_object"]["result_handle"], "--name", "Rain", "--kind", "sound-sfx")
    assert code == 0, child
    tx, shown = task.preview()
    prepared = shown["artifact"]["prepared_operation"]
    assert {row["id"] for row in prepared["verification_plan"]["replaced_list_subtree_rows"]} == {ROOT, CHILD}
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, json.dumps(verified)
    assert task.objects[FIRST]["@CustomList"] == [{"id": wind}, {"id": "{88888888-8888-8888-8888-888888888888}"}]
    assert task.objects[wind]["notes"] == "Keep wind"


@pytest.mark.parametrize("version", VERSIONS[1:])
def test_set_replace_rejects_deleting_another_explicit_batch_target(tmp_path: Path, version: str) -> None:
    task = SetReplaceTask(tmp_path, version)
    _declare_set_replacement(task)
    old_child = task.bind(CHILD)
    code, rejected = task.step("draft-declare-existing", "--declaration-id", "old-child",
                               "--object-handle", old_child, "--field", "notes", "Conflicting update")
    # The declaration remains mutable until Preview seals the whole batch.
    if code == 0:
        code, rejected = task.step("draft-check")
    assert code == 2 and rejected["error_code"] == "REPLACE_DEPENDENCY_CONFLICT", rejected
    assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", VERSIONS[1:])
def test_set_replace_without_collision_creates_the_requested_graph(tmp_path: Path, version: str) -> None:
    task = SetReplaceTask(tmp_path, version)
    del task.objects[ROOT], task.objects[CHILD]
    _declare_set_replacement(task)
    tx, shown = task.preview()
    assert shown["artifact"]["prepared_operation"]["verification_plan"]["replaced_subtree_rows"] == []
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, json.dumps(verified)


@pytest.mark.parametrize("version", VERSIONS[1:])
def test_set_replace_rename_keeps_source_identity_and_replaces_exact_sibling(tmp_path: Path, version: str) -> None:
    task = SetReplaceTask(tmp_path, version)
    task.objects[ROOT].update({"parent": {"id": SECOND}, "path": task.objects[SECOND]["path"] + r"\LAYERS"})
    task.objects[CHILD]["path"] = task.objects[ROOT]["path"] + r"\Old child"
    source = task.bind(FIRST)
    code, configured = task.step("draft-business-configure", "--name-conflict", "replace")
    assert code == 0, configured
    code, declared = task.step("draft-declare-existing", "--declaration-id", "source", "--object-handle", source,
                               "--field", "new_name", "Layers")
    assert code == 0, declared
    tx, shown = task.preview()
    assert {row["id"] for row in shown["artifact"]["prepared_operation"]["verification_plan"]["replaced_subtree_rows"]} == {ROOT, CHILD}
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, json.dumps(verified)
    assert task.objects[FIRST]["name"] == "Layers" and ROOT not in task.objects and CHILD not in task.objects
    wind = task.objects["{77777777-7777-7777-7777-777777777777}"]
    assert wind["parent"] == {"id": FIRST} and wind["notes"] == "Keep wind"
