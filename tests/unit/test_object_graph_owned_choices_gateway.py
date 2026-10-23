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
PROJECT_GROUP = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"


def test_documented_list_discovery_selects_sound_rtpc_omitted_by_live_names(tmp_path):
    task = FieldTask(tmp_path, "2025.1", "object.set")
    task.objects[FIRST] = {"id": FIRST, "name": "Rain", "type": "Sound", "classId": 65552,
        "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Rain", "parent": {"id": SECOND}}
    task.metadata = {"OutputBus": {"name": "OutputBus", "type": "", "restriction": {"type": "reference"}}}
    owner = task.bind(FIRST)
    code, listed = task.step("draft-discover-fields", "--object-handle", owner,
        "--field-source", "documented-lists", "--list")
    assert code == 0, listed
    rtpc = next(row for row in listed["agent_result"]["items"] if row["name"] == "RTPC")
    assert rtpc["field_kind"] == "list"
    assert rtpc["element_classes"] == [{"name": "RTPC", "class_id": 1441808}]
    code, selected = task.step("draft-discover-fields", "--object-handle", owner,
        "--field-source", "documented-lists", "--selection", rtpc["selection"])
    assert code == 0, selected
    field = selected["meaning_results"][0]["candidates"][0]
    assert field["handle"].startswith("bfh1-") and field["field_kind"] == "list"
    assert field["evidence"]["kind"] == "documented-list"
    assert not any(uri.endswith("getPropertyInfo") and args.get("property") == "RTPC"
        for uri, args, _ in task.calls)


def test_object_graph_next_action_discloses_documented_list_discovery(tmp_path):
    task = FieldTask(tmp_path, "2025.1", "object.set")
    task.objects[FIRST] = {"id": FIRST, "name": "Rain", "type": "Sound", "classId": 65552,
        "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Rain"}
    code, bound = task.step("draft-bind-object", "--object-id", FIRST)
    assert code == 0, bound
    continuation = bound["draft"]["next_action_binding"]
    disclosure = continuation["field_discovery"]["documented_lists"]
    assert disclosure["append"] == ["--field-source", "documented-lists", "--list"]
    assert disclosure["details_via"] == "more_actions"
    assert continuation["field_discovery"]["scope_decision"]["existing_object"] == [
        "--object-handle", "<bound-existing-target-handle>"]
    assert continuation["field_discovery"]["scope_decision"]["discovered_new_type"] == [
        "--type-handle", "<selected-type-handle>"]
    assert "draft-inspect" in continuation["more_actions"]["copy_command"]
    code, inspected = task.run("draft-inspect", task.draft, "--task-authority", task.authority)
    assert code == 0, inspected
    full_disclosure = inspected["draft"]["next_action_binding"]["field_discovery"]["documented_lists"]
    assert full_disclosure["scope"] == "copy_exact_bound_owner_handle_or_type_handle"
    code, listed = task.step("draft-discover-fields", "--object-handle", bound["bound_object"]["handle"],
        *disclosure["append"])
    assert code == 0, listed
    assert any(row["name"] == "RTPC" for row in listed["agent_result"]["items"])


@pytest.mark.parametrize("version,fault", (("2023.1", None), ("2024.1", None), ("2025.1", "wrong-target-class"), ("2023.1", "reversed-effect"), ("2024.1", "missing-effect-field"), ("2023.1", "changed-reference-notes")))
def test_documented_arguments_assigns_existing_references_with_order_and_preservation(tmp_path, version, fault):
    task = OwnedGraphTask(tmp_path, version, "object.set")
    task.types = [{"classId": 2293776, "name": "MusicSwitchContainer", "type": "WObject"},
        {"classId": 1245200, "name": "SwitchGroup", "type": "WObject"},
        {"classId": 458768, "name": "StateGroup", "type": "WObject"}]
    task.objects = {
        FIRST: {"id": FIRST, "name": "Music", "type": "MusicSwitchContainer", "classId": 2293776,
            "path": r"\Interactive Music Hierarchy\Default Work Unit\Music", "parent": None,
            "notes": "Keep music", "@Arguments": [{"id": SECOND}]},
        SECOND: {"id": SECOND, "name": "Surface", "type": "SwitchGroup", "classId": 1245200,
            "path": r"\Switches\Default Work Unit\Surface", "parent": {"id": PROJECT_GROUP}, "notes": "Keep group"},
        ROOT: {"id": ROOT, "name": "Weather", "type": "StateGroup", "classId": 458768,
            "path": r"\States\Default Work Unit\Weather", "parent": {"id": PROJECT_GROUP}, "owner": None},
    }
    preserved = deepcopy(task.objects)
    owner = task.bind(FIRST)
    targets = [task.bind(ROOT), task.bind(SECOND)]
    code, listed = task.step("draft-discover-fields", "--object-handle", owner,
        "--field-source", "documented-lists", "--list")
    assert code == 0, listed
    arguments = next(row for row in listed["agent_result"]["items"] if row["name"] == "Arguments")
    code, selected = task.step("draft-discover-fields", "--object-handle", owner,
        "--field-source", "documented-lists", "--selection", arguments["selection"])
    assert code == 0, selected
    field = selected["meaning_results"][0]["candidates"][0]["handle"]
    code, declared = task.step("draft-declare-existing", "--declaration-id", "music", "--object-handle", owner,
        "--field-value", field, json.dumps(targets))
    assert code == 0, declared
    if fault == "wrong-target-class":
        code, rejected = task.step("draft-check")
        assert code == 2, rejected
        assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)
        return
    original = task.call
    def call(uri, args=None, options=None):
        if uri == "ak.wwise.core.object.set":
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args["objects"] == [{"object": FIRST, "@Arguments": [ROOT, SECOND]}]
            task.objects[FIRST]["@Arguments"] = [{"id": ROOT}, {"id": SECOND}]
            if fault == "reversed-effect":
                task.objects[FIRST]["@Arguments"].reverse()
            elif fault == "changed-reference-notes":
                task.objects[SECOND]["notes"] = "Unrequested change"
            elif fault == "missing-effect-field":
                del task.objects[FIRST]["@Arguments"]
            return {"objects": [{"id": FIRST, "name": "Music"}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == (0 if fault is None else 2), verified
    assert (verified.get("verified") is True) == (fault is None), verified
    if fault == "changed-reference-notes":
        return
    assert task.objects[SECOND] == preserved[SECOND] and task.objects[ROOT] == preserved[ROOT]
    assert "owner" not in task.objects[SECOND] and task.objects[ROOT]["owner"] is None
    assert not any(uri.endswith("getPropertyInfo") and args.get("property") == "Arguments"
        for uri, args, _ in task.calls)


def _documented_metadata_clear_case(tmp_path, version="2025.1", *, alias=False, select=True, list_name="Metadata", clear=True, operation="object.set"):
    task = OwnedGraphTask(tmp_path, version, operation)
    task.require_class_projection = True
    element_class = 5570560 if version == "2025.1" else 5308432
    element_name = "MetadataSlot" if version == "2025.1" else "Metadata"
    if list_name == "RTPC":
        element_name, element_class = "RTPC", 1441808
    elif list_name == "Effects":
        element_name, element_class = "EffectSlot", 5505040
    accessor = {"Metadata": "@Metadata", "RTPC": "@RTPC", "Effects": "@Effects"}[list_name]
    task.types = [{"classId": 65552, "name": "Sound", "type": "WObject"},
                  {"classId": element_class, "name": element_name, "type": "WObject"}]
    task.objects[SECOND]["classId"] = 1638416
    task.objects[FIRST] = {"id": FIRST, "name": "Rain", "type": "Sound", "classId": 65552,
        "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Rain", "parent": {"id": SECOND},
        "notes": "Keep sound", accessor: [{"id": CHILD}]}
    task.objects[CHILD] = {"id": CHILD, "name": list_name, "type": "RTPC" if list_name == "RTPC" else "PluginInnerObject", "classId": element_class,
        "path": task.objects[FIRST]["path"] + r"\Metadata", "owner": {"id": FIRST}, "parent": None, "notes": "Old slot"}
    owner = task.bind(FIRST)
    task.list_owner_handle = owner
    field = list_name
    if select:
        code, listed = task.step("draft-discover-fields", "--object-handle", owner,
            "--field-source", "documented-lists", "--list")
        assert code == 0, listed
        choice = next(row for row in listed["agent_result"]["items"] if row["name"] == list_name)
        code, selected = task.step("draft-discover-fields", "--object-handle", owner,
            "--field-source", "documented-lists", "--selection", choice["selection"])
        assert code == 0, selected
        field = selected["meaning_results"][0]["candidates"][0]["handle"]
    task.list_field_handle = field
    calls_before = len(task.calls)
    if clear:
        code, declared = task.step("draft-clear-object-list", "--declaration-id", "clear",
            "--object-handle", owner, "--list-name", list_name if alias else field)
        assert code == 0, declared
    if not select:
        assert len(task.calls) == calls_before
    original = task.call
    def call(uri, args=None, options=None):
        if uri == "ak.wwise.core.object.set":
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args["objects"] == [{"object": FIRST, "listMode": "replaceAll", accessor: []}]
            task.objects[FIRST][accessor] = []
            del task.objects[CHILD]
            return {"objects": [{"id": FIRST, "name": "Rain"}]}
        return original(uri, args, options)
    task.call = call
    return task, element_class


@pytest.mark.parametrize("fault", (None, "native-generic-type", "wrong-requested-class", "wrong-effect-class", "wrong-effect-owner", "missing-effect-membership", "reversed-effect-order"))
def test_documented_metadata_list_handle_constructs_member_and_verifies_actual_class(tmp_path, fault):
    task, _ = _documented_metadata_clear_case(tmp_path)
    # Revise the same draft into append construction of one exact discovered class.
    del task.objects[CHILD]
    task.objects[FIRST]["@Metadata"] = []
    code, types = task.step("draft-discover-types", "--role", "object", "--meaning", "Sound" if fault == "wrong-requested-class" else "MetadataSlot")
    assert code == 0, types
    kind = types["type_candidates"][0]["handle"]
    code, listed = task.step("draft-discover-fields", "--object-handle", task.list_owner_handle,
        "--field-source", "documented-lists", "--list")
    choice = next(row for row in listed["agent_result"]["items"] if row["name"] == "Metadata")
    code, selected = task.step("draft-discover-fields", "--object-handle", task.list_owner_handle,
        "--field-source", "documented-lists", "--selection", choice["selection"])
    field = selected["meaning_results"][0]["candidates"][0]["handle"]
    code, created = task.step("draft-declare-new", "--declaration-id", "slot", "--parent-handle", task.list_owner_handle,
        "--name", "New metadata", "--kind", kind, "--field", "object_list", field,
        "--field", "list_behavior", "replace-all")
    assert code == 0, created
    if fault == "wrong-requested-class":
        code, rejected = task.step("draft-check")
        assert code == 2, rejected
        assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)
        return
    if fault == "reversed-effect-order":
        code, created = task.step("draft-declare-new", "--declaration-id", "second-slot", "--parent-handle", task.list_owner_handle,
            "--name", "Second metadata", "--kind", kind, "--field", "object_list", field,
            "--field", "list_behavior", "replace-all")
        assert code == 0, created
    original = task.call
    def call(uri, args=None, options=None):
        if uri == "ak.wwise.core.object.set":
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            expected_nodes = [{"type": "MetadataSlot", "name": "New metadata"}]
            if fault == "reversed-effect-order":
                expected_nodes.append({"type": "MetadataSlot", "name": "Second metadata"})
            assert args["objects"] == [{"object": FIRST, "listMode": "replaceAll", "@Metadata": expected_nodes}]
            task.objects[CHILD] = {"id": CHILD, "name": "New metadata", "type": "MetadataSlot", "classId": 5570560,
                "path": task.objects[FIRST]["path"] + r"\New metadata", "owner": {"id": FIRST}, "parent": None, "notes": ""}
            task.objects[FIRST]["@Metadata"] = [{"id": CHILD}]
            if fault == "native-generic-type":
                task.objects[CHILD]["type"] = "PluginInnerObject"
                del task.objects[CHILD]["parent"]
            elif fault == "wrong-effect-class":
                task.objects[CHILD]["classId"] = 1441808
            elif fault == "wrong-effect-owner":
                task.objects[CHILD]["owner"] = {"id": SECOND}
            elif fault == "missing-effect-membership":
                task.objects[FIRST]["@Metadata"] = []
            results = [{"id": CHILD, "name": "New metadata"}]
            if fault == "reversed-effect-order":
                task.objects[ROOT] = {**task.objects[CHILD], "id": ROOT, "name": "Second metadata",
                    "path": task.objects[FIRST]["path"] + r"\Second metadata"}
                task.objects[FIRST]["@Metadata"] = [{"id": ROOT}, {"id": CHILD}]
                results.append({"id": ROOT, "name": "Second metadata"})
            return {"objects": [{"id": FIRST, "name": "Rain", "@Metadata": results}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == (0 if fault in (None, "native-generic-type") else 2), verified
    assert (verified.get("verified") is True) == (fault in (None, "native-generic-type")), verified
    if fault == "reversed-effect-order":
        assert verified.get("verified") is False and "ordered membership matches" in json.dumps(verified), verified


def test_documented_list_guard_allows_requested_owner_rename_while_verifying_class_and_clear(tmp_path):
    task, _ = _documented_metadata_clear_case(tmp_path, clear=False)
    code, declared = task.step("draft-declare-existing", "--declaration-id", "owner", "--object-handle", task.list_owner_handle,
        "--field", "new_name", "Storm")
    assert code == 0, declared
    code, declared = task.step("draft-clear-object-list", "--declaration-id", "owner", "--object-handle", task.list_owner_handle,
        "--list-name", task.list_field_handle)
    assert code == 0, declared
    original = task.call
    def call(uri, args=None, options=None):
        if uri == "ak.wwise.core.object.set":
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args["objects"] == [{"object": FIRST, "name": "Storm", "listMode": "replaceAll", "@Metadata": []}]
            task.objects[FIRST].update(name="Storm", path=r"\Actor-Mixer Hierarchy\Default Work Unit\Storm")
            task.objects[FIRST]["@Metadata"] = []
            del task.objects[CHILD]
            return {"objects": [{"id": FIRST, "name": "Storm"}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, verified


@pytest.mark.parametrize("conflict,fault", (("fail", None), ("rename", None), ("merge", None),
    ("fail", "wrong-class"), ("fail", "wrong-owner"), ("fail", "reversed-order"), ("fail", "unrequested-notes"), ("fail", "wrong-requested-class"), ("fail", "alias"), ("fail", "wrong-handle-owner")))
def test_documented_list_handle_places_created_root_and_verifies_native_class_owner_and_preservation(tmp_path, conflict, fault):
    task, _ = _documented_metadata_clear_case(tmp_path, clear=False, operation="object.create", select=fault != "alias")
    if conflict in {"rename", "merge"}:
        task.objects[CHILD].update(name="New metadata", path=task.objects[FIRST]["path"] + r"\New metadata")
    preserved = deepcopy(task.objects[CHILD])
    code, configured = task.step("draft-business-configure", "--name-conflict", conflict)
    assert code == 0, configured
    code, types = task.step("draft-discover-types", "--role", "object", "--meaning", "Sound" if fault == "wrong-requested-class" else "MetadataSlot")
    assert code == 0, types
    owner = task.bind(SECOND) if fault == "wrong-handle-owner" else task.list_owner_handle
    code, declared = task.step("draft-declare-new", "--declaration-id", "slot", "--parent-handle", owner,
        "--name", "New metadata", "--kind", types["type_candidates"][0]["handle"],
        "--field", "object_list", task.list_field_handle)
    if fault == "wrong-handle-owner":
        assert code == 2 and declared["error_code"] == "DOCUMENTED_LIST_SELECTION_REQUIRED", declared
        assert "choices" in json.dumps(declared)
        assert not any(uri.endswith("object.create") for uri, _, _ in task.calls)
        return
    assert code == 0, declared
    if fault == "wrong-requested-class":
        code, rejected = task.step("draft-check")
        assert code == 2 and rejected["error_code"] == "DOCUMENTED_LIST_ELEMENT_CLASS_INVALID", rejected
        assert not any(uri.endswith("object.create") for uri, _, _ in task.calls)
        return
    original = task.call
    def call(uri, args=None, options=None):
        if uri == "ak.wwise.core.object.create":
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args == {"parent": FIRST, "type": "MetadataSlot", "name": "New metadata", "list": "Metadata",
                "onNameConflict": conflict, "autoAddToSourceControl": False}
            if conflict == "merge":
                return {"id": CHILD, "name": "New metadata"}
            result_name = "New metadata_01" if conflict == "rename" else "New metadata"
            task.objects[ROOT] = {"id": ROOT, "name": result_name, "type": "PluginInnerObject", "classId": 5570560,
                "path": task.objects[FIRST]["path"] + "\\" + result_name, "owner": {"id": FIRST}, "notes": ""}
            task.objects[FIRST]["@Metadata"] = [{"id": CHILD}, {"id": ROOT}]
            if fault == "wrong-class":
                task.objects[ROOT]["classId"] = 1441808
            elif fault == "wrong-owner":
                task.objects[ROOT]["owner"] = {"id": SECOND}
            elif fault == "reversed-order":
                task.objects[FIRST]["@Metadata"].reverse()
            elif fault == "unrequested-notes":
                task.objects[CHILD]["notes"] = "Unexpected"
            return {"id": ROOT, "name": result_name}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    success = fault in {None, "alias"}
    assert code == (0 if success else 2), verified
    assert (verified.get("verified") is True) == success, verified
    if success:
        assert task.objects[CHILD] == preserved and task.objects[FIRST]["notes"] == "Keep sound"


@pytest.mark.parametrize("conflict,list_mode,slot_collision,drift", (("fail", "append", False, None), ("merge", "append", False, None), ("merge", "replace-all", False, None), ("rename", "append", False, None), ("replace", "append", False, None), ("merge", "append", True, None), ("merge", "append", False, "owner-class"), ("merge", "append", False, "member-class"), ("fail", "append", False, "live-class")))
def test_documented_list_class_handle_builds_slot_under_planned_owner_in_same_transaction(tmp_path, conflict, list_mode, slot_collision, drift):
    task, _ = _documented_metadata_clear_case(tmp_path, clear=False)
    task.types.append({"classId": 1638416, "name": "WorkUnit", "type": "WObject"})
    old_slot = "{66666666-6666-6666-6666-666666666666}"
    if conflict != "fail":
        task.objects[ROOT] = {"id": ROOT, "name": "New sound", "type": "Sound", "classId": 65552,
            "path": task.objects[SECOND]["path"] + r"\New sound", "parent": {"id": SECOND}, "notes": "Keep old owner",
            "@Metadata": [{"id": old_slot}]}
        slot_name = "New metadata" if slot_collision else "Old metadata"
        task.objects[old_slot] = {"id": old_slot, "name": slot_name, "type": "PluginInnerObject", "classId": 5570560,
            "path": task.objects[ROOT]["path"] + "\\" + slot_name, "owner": {"id": ROOT}, "notes": "Keep old metadata"}
    preserved = deepcopy(task.objects)
    initial = ["--list-behavior", list_mode] if list_mode == "replace-all" else []
    code, configured = task.step("draft-business-configure", "--name-conflict", conflict, *initial)
    assert code == 0, configured
    parent = task.bind(SECOND)
    code, owner_types = task.step("draft-discover-types", "--role", "object", "--meaning", "Sound")
    assert code == 0, owner_types
    owner_type = owner_types["type_candidates"][0]["handle"]
    code, slot_types = task.step("draft-discover-types", "--role", "object", "--meaning", "MetadataSlot")
    assert code == 0, slot_types
    slot_type = slot_types["type_candidates"][0]["handle"]
    code, listed = task.step("draft-discover-fields", "--type-handle", owner_type,
        "--field-source", "documented-lists", "--list")
    assert code == 0, listed
    choice = next(row for row in listed["agent_result"]["items"] if row["name"] == "Metadata")
    code, selected = task.step("draft-discover-fields", "--type-handle", owner_type,
        "--field-source", "documented-lists", "--selection", choice["selection"])
    assert code == 0, selected
    list_field = selected["meaning_results"][0]["candidates"][0]["handle"]
    code, owner = task.step("draft-declare-new", "--declaration-id", "new-sound", "--parent-handle", parent,
        "--name", "New sound", "--kind", owner_type)
    assert code == 0, json.dumps(owner)
    owner_result = owner["draft"]["declared_object"]["result_handle"]
    if list_mode == "replace-all":
        code, incomplete = task.step("draft-check")
        assert code == 2, incomplete
        assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)
    code, slot = task.step("draft-declare-new", "--declaration-id", "slot", "--parent-handle", owner_result,
        "--name", "New metadata", "--kind", slot_type, "--field", "object_list", list_field)
    assert code == 0, slot
    if list_mode != "replace-all":
        code, configured = task.step("draft-business-configure", "--name-conflict", conflict, "--list-behavior", list_mode)
        assert code == 0, configured
    fresh_slot = old_slot if slot_collision else "{77777777-7777-7777-7777-777777777777}"
    actual_owner = "{88888888-8888-8888-8888-888888888888}" if conflict in {"rename", "replace"} else ROOT
    actual_owner_name = "New sound_01" if conflict == "rename" else "New sound"
    original = task.call
    def call(uri, args=None, options=None):
        if uri == "ak.wwise.core.object.set":
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args["objects"] == [{"object": SECOND, "children": [{"type": "Sound", "name": "New sound",
                "@Metadata": [{"type": "MetadataSlot", "name": "New metadata"}]}]}]
            assert args["listMode"] == ("replaceAll" if list_mode == "replace-all" else "append")
            assert args["onNameConflict"] == conflict
            if conflict == "replace":
                del task.objects[ROOT], task.objects[old_slot]
            if conflict == "merge" and list_mode == "replace-all":
                del task.objects[old_slot]
            keep_old = conflict == "merge" and list_mode == "append" and not slot_collision
            task.objects[actual_owner] = {"id": actual_owner, "name": actual_owner_name, "type": "Sound", "classId": 65552,
                "path": task.objects[SECOND]["path"] + "\\" + actual_owner_name, "parent": {"id": SECOND},
                "notes": "Keep old owner" if conflict == "merge" else "",
                "@Metadata": ([{"id": old_slot}] if keep_old else []) + [{"id": fresh_slot}]}
            task.objects[fresh_slot] = {"id": fresh_slot, "name": "New metadata", "type": "PluginInnerObject", "classId": 5570560,
                "path": task.objects[actual_owner]["path"] + r"\New metadata", "owner": {"id": actual_owner}, "notes": "Keep old metadata" if slot_collision else ""}
            return {"objects": [{"id": SECOND, "name": "Default Work Unit", "children": [{"id": actual_owner, "name": actual_owner_name,
                "@Metadata": [{"id": fresh_slot, "name": "New metadata"}]}]}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    guards = shown["artifact"]["prepared_operation"]["pre_state"]["documented_planned_list_guards"]
    assert guards[0]["binding"]["planned_owner"] == {"result_handle": owner_result, "request_path": "$.objects[0].children[0]"}
    if drift is not None:
        code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
        assert code == 0, confirmed
        if drift == "owner-class":
            task.objects[ROOT]["classId"] = 2293776
        elif drift == "member-class":
            task.objects[old_slot]["classId"] = 1441808
        else:
            next(row for row in task.types if row["name"] == "Sound")["classId"] = 2293776
        code, rejected = task.run("execute", tx)
        assert code == 2 and rejected.get("executed") is not True, rejected
        assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)
        return
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[CHILD] == preserved[CHILD] and task.objects[FIRST] == preserved[FIRST]
    if conflict == "rename":
        assert task.objects[ROOT] == preserved[ROOT] and task.objects[old_slot] == preserved[old_slot]
    elif conflict == "merge" and list_mode == "append":
        assert task.objects[old_slot] == preserved[old_slot]
    elif conflict != "fail":
        assert old_slot not in task.objects


@pytest.mark.parametrize("fault", (None, "wrong-inner-class", "wrong-inner-owner", "missing-inner-membership", "changed-slot-reference", "changed-reference-notes", "missing-inner-result"))
def test_documented_nested_lists_and_inline_slot_references_share_one_planned_graph(tmp_path, fault):
    task, _ = _documented_metadata_clear_case(tmp_path, clear=False)
    task.objects[SECOND]["path"] = r"\Interactive Music Hierarchy\Default Work Unit"
    task.objects[FIRST]["parent"] = {"id": PROJECT_GROUP}
    task.types.extend({"classId": class_id, "name": name, "type": "WObject"} for name, class_id in (
        ("WorkUnit", 1638416), ("MusicSwitchContainer", 2293776), ("MusicArgumentsSlot", 5832704),
        ("MultiSwitchEntry", 5439504), ("EntryPathSlot", 5767168), ("SwitchGroup", 1245200), ("Switch", 1310736)))
    group_id, value_id = "{55555555-5555-5555-5555-555555555555}", "{66666666-6666-6666-6666-666666666666}"
    task.objects[group_id] = {"id": group_id, "name": "Surface", "type": "SwitchGroup", "classId": 1245200,
        "path": r"\Switches\Default Work Unit\Surface", "notes": "Keep group", "parent": {"id": PROJECT_GROUP}}
    task.objects[value_id] = {"id": value_id, "name": "Wood", "type": "Switch", "classId": 1310736,
        "path": task.objects[group_id]["path"] + r"\Wood", "notes": "Keep value", "parent": {"id": group_id}}
    parent, group, value = task.bind(SECOND), task.bind(group_id), task.bind(value_id)
    preserved = deepcopy(task.objects)
    original = task.call
    fields = {5832704: ("Argument", "Argument", ["SwitchGroup", "StateGroup"]),
        5767168: ("EntryPathObject", "EntryPath Object", ["SwitchGroup", "Switch", "StateGroup", "State"])}
    def call(uri, args=None, options=None):
        if uri.endswith(("getPropertyAndReferenceNames", "getPropertyInfo")):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            spec = fields.get(args.get("classId"))
            if uri.endswith("getPropertyAndReferenceNames"):
                return {"return": [spec[0]] if spec else []}
            assert spec and args["property"] == spec[0], args
            return {"name": spec[0], "type": "Reference", "display": {"name": spec[1]},
                "restriction": {"type": "reference", "restrictions": [{"type": spec[2]}, "notNull"]}}
        if uri == "ak.wwise.core.object.set":
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args["objects"] == [{"object": SECOND, "children": [{"type": "MusicSwitchContainer", "name": "Music",
                "@Arguments": [{"type": "MusicArgumentsSlot", "name": "Surface argument", "@Argument": group_id}],
                "@Entries": [{"type": "MultiSwitchEntry", "name": "Wood entry",
                    "@EntryPath": [{"type": "EntryPathSlot", "name": "Wood path", "@EntryPathObject": value_id}]}]}]}]
            arg, entry, path = "{77777777-7777-7777-7777-777777777777}", "{88888888-8888-8888-8888-888888888888}", "{99999999-9999-9999-9999-999999999999}"
            music_path = task.objects[SECOND]["path"] + r"\Music"
            task.objects[ROOT] = {"id": ROOT, "name": "Music", "type": "MusicSwitchContainer", "classId": 2293776,
                "path": music_path, "parent": {"id": SECOND}, "notes": "", "@Arguments": [{"id": arg}], "@Entries": [{"id": entry}]}
            task.objects[arg] = {"id": arg, "name": "Surface argument", "type": "PluginInnerObject", "classId": 5832704,
                "path": music_path + r"\Surface argument", "owner": {"id": ROOT}, "notes": "", "@Argument": {"id": group_id}}
            task.objects[entry] = {"id": entry, "name": "Wood entry", "type": "PluginInnerObject", "classId": 5439504,
                "path": music_path + r"\Wood entry", "owner": {"id": ROOT}, "notes": "", "@EntryPath": [{"id": path}]}
            task.objects[path] = {"id": path, "name": "Wood path", "type": "PluginInnerObject", "classId": 5767168,
                "path": task.objects[entry]["path"] + r"\Wood path", "owner": {"id": entry}, "notes": "", "@EntryPathObject": {"id": value_id}}
            if fault == "wrong-inner-class":
                task.objects[path]["classId"] = 5832704
            elif fault == "wrong-inner-owner":
                task.objects[path]["owner"] = {"id": ROOT}
            elif fault == "missing-inner-membership":
                task.objects[entry]["@EntryPath"] = []
            elif fault == "changed-slot-reference":
                task.objects[path]["@EntryPathObject"] = {"id": group_id}
            elif fault == "changed-reference-notes":
                task.objects[value_id]["notes"] = "Unexpected"
            result_path = [] if fault == "missing-inner-result" else [{"id": path, "name": "Wood path"}]
            return {"objects": [{"id": SECOND, "name": "Default Work Unit", "children": [{"id": ROOT, "name": "Music",
                "@Arguments": [{"id": arg, "name": "Surface argument"}], "@Entries": [{"id": entry, "name": "Wood entry",
                    "@EntryPath": result_path}]}]}]}
        return original(uri, args, options)
    task.call = call
    kinds = {}
    for name in ("MusicSwitchContainer", "MusicArgumentsSlot", "MultiSwitchEntry", "EntryPathSlot"):
        code, types = task.step("draft-discover-types", "--role", "object", "--meaning", name)
        assert code == 0, types
        kinds[name] = types["type_candidates"][0]["handle"]
    list_fields = {}
    for owner_type, name in (("MusicSwitchContainer", "Arguments"), ("MusicSwitchContainer", "Entries"), ("MultiSwitchEntry", "EntryPath")):
        code, listed = task.step("draft-discover-fields", "--type-handle", kinds[owner_type], "--field-source", "documented-lists", "--list")
        assert code == 0, listed
        choice = next(row for row in listed["agent_result"]["items"] if row["name"] == name)
        code, selected = task.step("draft-discover-fields", "--type-handle", kinds[owner_type], "--field-source", "documented-lists", "--selection", choice["selection"])
        assert code == 0, selected
        list_fields[name] = selected["meaning_results"][0]["candidates"][0]["handle"]
    references = {}
    for owner_type, meaning in (("MusicArgumentsSlot", "Argument"), ("EntryPathSlot", "EntryPath Object")):
        code, selected = task.step("draft-discover-fields", "--type-handle", kinds[owner_type], "--meaning", meaning)
        assert code == 0, selected
        references[owner_type] = selected["meaning_results"][0]["candidates"][0]["handle"]
    handles = {}
    for declaration_id, parent_handle, name, kind, extra in (
        ("music", parent, "Music", "MusicSwitchContainer", []),
        ("argument", "music", "Surface argument", "MusicArgumentsSlot", ["--field", "object_list", list_fields["Arguments"], "--field-value", references["MusicArgumentsSlot"], group]),
        ("entry", "music", "Wood entry", "MultiSwitchEntry", ["--field", "object_list", list_fields["Entries"]]),
        ("path", "entry", "Wood path", "EntryPathSlot", ["--field", "object_list", list_fields["EntryPath"], "--field-value", references["EntryPathSlot"], value])):
        code, declared = task.step("draft-declare-new", "--declaration-id", declaration_id, "--parent-handle", handles.get(parent_handle, parent_handle),
            "--name", name, "--kind", kinds[kind], *extra)
        assert code == 0, declared
        handles[declaration_id] = declared["draft"]["declared_object"]["result_handle"]
    tx, shown = task.preview()
    assert len(shown["artifact"]["prepared_operation"]["pre_state"]["documented_planned_list_guards"]) == 3
    code, verified = task.finish(tx, shown)
    assert code == (0 if fault is None else 2), verified
    assert (verified.get("verified") is True) == (fault is None), verified
    if fault is None:
        assert task.objects[group_id] == preserved[group_id] and task.objects[value_id] == preserved[value_id]


@pytest.mark.parametrize("version,fault", (("2022.1", "source-absent"), ("2023.1", None), ("2024.1", None), ("2025.1", "wrong-target-class"),
    ("2023.1", "duplicate-targets"), ("2023.1", "owner-class-effect"), ("2024.1", "reversed-effect"), ("2023.1", "target-notes-effect"), ("2024.1", "target-class-before"), ("2023.1", "merge-owner")))
def test_documented_reference_list_class_handle_assigns_array_on_planned_owner_without_property_info(tmp_path, version, fault):
    task, _ = _documented_metadata_clear_case(tmp_path, version, clear=False)
    task.types.extend({"classId": class_id, "name": name, "type": "WObject"} for name, class_id in (
        ("WorkUnit", 1638416), ("MusicSwitchContainer", 2293776), ("SwitchGroup", 1245200), ("StateGroup", 458768)))
    task.objects[SECOND]["path"] = r"\Interactive Music Hierarchy\Default Work Unit"
    task.objects[FIRST]["parent"] = {"id": PROJECT_GROUP}
    state_id, fresh_owner = "{55555555-5555-5555-5555-555555555555}", "{66666666-6666-6666-6666-666666666666}"
    task.objects[ROOT] = {"id": ROOT, "name": "Surface", "type": "SwitchGroup", "classId": 1245200,
        "path": r"\Switches\Default Work Unit\Surface", "parent": {"id": PROJECT_GROUP}, "notes": "Keep surface"}
    task.objects[state_id] = {"id": state_id, "name": "Weather", "type": "StateGroup", "classId": 458768,
        "path": r"\States\Default Work Unit\Weather", "parent": {"id": PROJECT_GROUP}, "notes": "Keep weather", "owner": None}
    if fault == "merge-owner":
        task.objects[fresh_owner] = {"id": fresh_owner, "name": "Music", "type": "MusicSwitchContainer", "classId": 2293776,
            "path": task.objects[SECOND]["path"] + r"\Music", "parent": {"id": SECOND}, "notes": "Keep existing music", "@Arguments": []}
        code, configured = task.step("draft-business-configure", "--name-conflict", "merge")
        assert code == 0, configured
    parent, switch, state = task.bind(SECOND), task.bind(ROOT), task.bind(state_id)
    preserved = deepcopy(task.objects)
    code, types = task.step("draft-discover-types", "--role", "object", "--meaning", "MusicSwitchContainer")
    assert code == 0, types
    kind = types["type_candidates"][0]["handle"]
    code, listed = task.step("draft-discover-fields", "--type-handle", kind, "--field-source", "documented-lists", "--list")
    assert code == 0, listed
    if fault == "source-absent":
        assert "Arguments" not in {row["name"] for row in listed["agent_result"]["items"]}
        assert listed["agent_result"]["native_unavailability_proven"] is False
        return
    choice = next(row for row in listed["agent_result"]["items"] if row["name"] == "Arguments")
    code, selected = task.step("draft-discover-fields", "--type-handle", kind, "--field-source", "documented-lists", "--selection", choice["selection"])
    assert code == 0, selected
    field = selected["meaning_results"][0]["candidates"][0]["handle"]
    code, declared = task.step("draft-declare-new", "--declaration-id", "music", "--parent-handle", parent,
        "--name", "Music", "--kind", kind, "--field-value", field, json.dumps([state, state] if fault == "duplicate-targets" else [state, switch]))
    assert code == 0, declared
    if fault in {"wrong-target-class", "duplicate-targets", "target-class-before"}:
        if fault == "target-class-before":
            task.objects[ROOT]["classId"] = 5832704
        code, rejected = task.step("draft-check")
        assert code == 2, rejected
        assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)
        return
    original = task.call
    def call(uri, args=None, options=None):
        if uri == "ak.wwise.core.object.set":
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args["objects"] == [{"object": SECOND, "children": [{"type": "MusicSwitchContainer", "name": "Music", "@Arguments": [state_id, ROOT]}]}]
            task.objects[fresh_owner] = {"id": fresh_owner, "name": "Music", "type": "MusicSwitchContainer", "classId": 2293776,
                "path": task.objects[SECOND]["path"] + r"\Music", "parent": {"id": SECOND}, "notes": "Keep existing music" if fault == "merge-owner" else "", "@Arguments": [{"id": state_id}, {"id": ROOT}]}
            if fault == "owner-class-effect":
                task.objects[fresh_owner]["classId"] = 65552
            elif fault == "reversed-effect":
                task.objects[fresh_owner]["@Arguments"].reverse()
            elif fault == "target-notes-effect":
                task.objects[ROOT]["notes"] = "Unexpected"
            return {"objects": [{"id": SECOND, "name": "Default Work Unit", "children": [{"id": fresh_owner, "name": "Music"}]}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    success = fault in {None, "merge-owner"}
    assert code == (0 if success else 2), verified
    assert (verified.get("verified") is True) == success, verified
    if success:
        assert task.objects[ROOT] == preserved[ROOT] and task.objects[state_id] == preserved[state_id]
    assert not any(uri.endswith("getPropertyInfo") and args.get("property") == "Arguments" for uri, args, _ in task.calls)


def test_documented_list_exact_alias_resolves_at_preview_without_hidden_live_declaration(tmp_path):
    task, _ = _documented_metadata_clear_case(tmp_path, alias=True, select=False)
    tx, shown = task.preview()
    guards = shown["artifact"]["prepared_operation"]["pre_state"]["documented_list_guards"]
    assert guards[0]["evidence"]["declaration"]["name"] == "Metadata"
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, verified


@pytest.mark.parametrize("version", VERSIONS[1:])
@pytest.mark.parametrize("alias", (False, True))
def test_documented_metadata_list_handle_clears_through_one_verified_transaction(tmp_path, version, alias):
    task, element_class = _documented_metadata_clear_case(tmp_path, version, alias=alias)
    tx, shown = task.preview()
    proofs = shown["artifact"]["prepared_operation"]["pre_state"]["documented_list_guards"]
    assert proofs[0]["evidence"]["source_member"] == "wwiseobject_sound.html"
    assert proofs[0]["members"][0]["classId"] == element_class
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[FIRST]["notes"] == "Keep sound"
    assert CHILD not in task.objects


@pytest.mark.parametrize("list_name", ("RTPC", "Effects"))
def test_documented_specialized_list_uses_same_closed_generic_clear_and_actual_owner_proof(tmp_path, list_name):
    task, expected_class = _documented_metadata_clear_case(tmp_path, list_name=list_name)
    tx, shown = task.preview()
    guard = shown["artifact"]["prepared_operation"]["pre_state"]["documented_list_guards"][0]
    assert guard["evidence"]["declaration"]["name"] == list_name
    assert guard["members"][0]["classId"] == expected_class
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, verified
    assert CHILD not in task.objects and task.objects[FIRST]["notes"] == "Keep sound"


@pytest.mark.parametrize("fault", ("wrong-member-class", "bool-member-class", "missing-member-class", "duplicate-member", "missing-member-owner", "null-member-owner", "wrong-member-owner"))
def test_documented_list_preview_requires_actual_member_class_and_ownership(tmp_path, fault):
    task, _ = _documented_metadata_clear_case(tmp_path)
    if fault == "wrong-member-class":
        task.objects[CHILD]["classId"] = 1441808  # RTPC, independently declared by its own source page.
    elif fault == "bool-member-class":
        task.objects[CHILD]["classId"] = True
    elif fault == "missing-member-class":
        del task.objects[CHILD]["classId"]
    elif fault == "duplicate-member":
        task.objects[FIRST]["@Metadata"].append({"id": CHILD})
    elif fault == "missing-member-owner":
        del task.objects[CHILD]["owner"]
    elif fault == "null-member-owner":
        task.objects[CHILD]["owner"] = None
    else:
        task.objects[CHILD]["owner"] = {"id": SECOND}
    code, rejected = task.step("draft-check")
    assert code == 2, rejected
    assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)


def test_documented_list_unknown_or_scalar_alias_reports_exact_legal_choices(tmp_path):
    task, _ = _documented_metadata_clear_case(tmp_path)
    code, rejected = task.step("draft-clear-object-list", "--declaration-id", "clear",
        "--object-handle", task.list_owner_handle, "--list-name", "OutputBus")
    assert code == 0, rejected  # Offline declaration performs no hidden live alias probe.
    code, rejected = task.step("draft-check")
    assert code == 2 and rejected["error_code"] == "DOCUMENTED_LIST_SELECTION_REQUIRED", rejected
    assert rejected["details"]["repair"]["choices"] == ["Effects", "Metadata", "RTPC"]


@pytest.mark.parametrize("fault", ("member-class", "member-order", "owner-class", "source"))
def test_documented_list_immutable_preview_blocks_class_source_and_order_drift(tmp_path, monkeypatch, fault):
    task, _ = _documented_metadata_clear_case(tmp_path)
    if fault == "member-order":
        task.objects[ROOT] = {**task.objects[CHILD], "id": ROOT, "name": "Second", "path": task.objects[CHILD]["path"] + "Two"}
        task.objects[FIRST]["@Metadata"].append({"id": ROOT})
    if fault == "source":
        from wwise_waapi import documented_list_fields
        source_root = tmp_path / "source"
        (source_root / "2025.1").mkdir(parents=True)
        source = source_root / "2025.1" / "documented-list-fields.json"
        source.write_bytes((documented_list_fields.CATALOG_ROOT / "2025.1" / source.name).read_bytes())
        monkeypatch.setattr(documented_list_fields, "CATALOG_ROOT", source_root)
    tx, shown = task.preview()
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    if fault == "member-class":
        task.objects[CHILD]["classId"] = 1441808
    elif fault == "member-order":
        task.objects[FIRST]["@Metadata"].reverse()
    elif fault == "owner-class":
        task.objects[FIRST]["classId"] = 2293776
    else:
        import hashlib
        catalog = json.loads(source.read_text())
        next(row for row in catalog["classes"] if row["name"] == "Sound")["source_sha256"] = "0" * 64
        unsigned = {key: value for key, value in catalog.items() if key != "catalog_sha256"}
        catalog["catalog_sha256"] = hashlib.sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        source.write_text(json.dumps(catalog))
    code, rejected = task.run("execute", tx)
    assert code == 2 and rejected.get("executed") is not True, rejected
    assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)


def test_2021_documented_list_discovery_reports_missing_source_without_native_absence(tmp_path):
    task = FieldTask(tmp_path, "2021.1", "object.create")
    task.objects[FIRST] = {"id": FIRST, "name": "Rain", "type": "Sound", "classId": 65552,
        "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Rain"}
    owner = task.bind(FIRST)
    code, listed = task.step("draft-discover-fields", "--object-handle", owner,
        "--field-source", "documented-lists", "--list")
    assert code == 0, listed
    observed = listed["agent_result"]
    assert observed["items"] == [] and observed["native_unavailability_proven"] is False
    assert observed["availability"] == "source_does_not_establish_list_fields_for_this_class"
    assert observed["source_coverage"]["indexed_pages"] == 96


@pytest.mark.parametrize("fault", ("version", "class", "malformed"))
def test_documented_list_catalog_failure_never_issues_a_mutation_field(tmp_path, monkeypatch, fault):
    from wwise_waapi import documented_list_fields
    task = FieldTask(tmp_path, "2025.1", "object.set")
    task.objects[FIRST] = {"id": FIRST, "name": "Rain", "type": "Sound", "classId": 65552,
        "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Rain"}
    owner = task.bind(FIRST)
    root = tmp_path / "catalog"
    (root / "2025.1").mkdir(parents=True)
    source = root / "2025.1" / "documented-list-fields.json"
    catalog = json.loads((documented_list_fields.CATALOG_ROOT / "2025.1" / source.name).read_text())
    if fault == "version":
        catalog["version"] = "2024.1"
    elif fault == "class":
        catalog["classes"][0]["class_id"] = True
    else:
        catalog["classes"] = [None]
    import hashlib
    unsigned = {key: value for key, value in catalog.items() if key != "catalog_sha256"}
    catalog["catalog_sha256"] = hashlib.sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    source.write_text(json.dumps(catalog))
    monkeypatch.setattr(documented_list_fields, "CATALOG_ROOT", root)
    code, rejected = task.step("draft-discover-fields", "--object-handle", owner,
        "--field-source", "documented-lists", "--list")
    assert code == 2, rejected
    assert "field_candidates" not in rejected and "meaning_results" not in rejected
    assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)


class OwnedGraphTask(FieldTask):
    def __init__(self, path: Path, version: str, operation: str) -> None:
        super().__init__(path, version, operation)
        self.objects = {
            FIRST: {"id": FIRST, "name": "Weather", "type": "ActorMixer", "classId": 1,
                    "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Weather",
                    "parent": {"id": SECOND}, "notes": "Keep owner", "@CustomList": []},
            SECOND: {"id": SECOND, "name": "Default Work Unit", "type": "WorkUnit", "classId": 3,
                     "path": r"\Actor-Mixer Hierarchy\Default Work Unit", "notes": "Keep parent"},
        }
        self.types = [{"classId": 1, "name": "ActorMixer", "type": "WObject"},
                      {"classId": 2, "name": "Sound", "type": "WObject"},
                      {"classId": 3, "name": "WorkUnit", "type": "WObject"}]
        if version == "2025.1":
            self.types[0]["name"] = "PropertyContainer"
            self.objects[FIRST]["type"] = "PropertyContainer"
        # Stored native creation facts stay independent from mutable getTypes responses.
        self.creation_classes = {"ActorMixer": 1, "PropertyContainer": 1, "Sound": 2, "WorkUnit": 3}
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
        if existing is None:
            row["classId"] = self.creation_classes[row["type"]]
        self.objects[object_id] = row
        row.update({key: deepcopy(value) for key, value in node.items() if key.startswith("@") and key != "@CustomList"})
        children = [self._create(child, object_id) for child in node.get("children", [])]
        result = {"id": object_id, "name": row["name"], **({"children": children} if children else {})}
        for key, values in node.items():
            if key == "@CustomList" and isinstance(values, list):
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
            return {"return": self.project_rows(rows, options)}
        if uri.endswith("object.create"):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            self.conflict = args.get("onNameConflict", "fail")
            result = self._create(args, args["parent"], owned="list" in args)
            if "list" in args:
                members = self.objects[args["parent"]].setdefault("@" + args["list"], [])
                if {"id": result["id"]} not in members:
                    members.append({"id": result["id"]})
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
                for key, value in item.items():
                    if key.startswith("@") and key != "@CustomList":
                        row[key] = deepcopy(value)
                for key, values in item.items():
                    if key == "@CustomList" and isinstance(values, list):
                        previous = [member for member in row.get(key, []) if member["id"] in self.objects]
                        members = [self._create(member, row["id"], owned=True) for member in values]
                        previous = [member for member in previous if member["id"] in self.objects]
                        row[key] = [*previous, *({"id": member["id"]} for member in members if {"id": member["id"]} not in previous)]
                        result_row[key] = members
                results.append(result_row)
            if self.bad_result == "reverse-reference-array":
                self.objects[FIRST]["@Targets"].reverse()
            elif self.bad_result == "omit-reference-array":
                del self.objects[FIRST]["@Targets"]
            elif self.bad_result == "retain-cleared-reference":
                self.objects[FIRST]["@Target"] = SECOND
            elif self.bad_result == "omit-cleared-reference":
                del self.objects[FIRST]["@Target"]
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
        assert code == 0, json.dumps(checked)
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




class SetReplaceTask(OwnedGraphTask):
    """Model native replace deleting a collision before creating fresh GUIDs."""
    def __init__(self, path: Path, version: str) -> None:
        super().__init__(path, version, "object.set")
        self.retain_old_descendant = False
        self.objects[ROOT] = {"id": ROOT, "name": "LAYERS", "type": "Sound", "classId": 2,
            "path": self.objects[FIRST]["path"] + r"\LAYERS", "parent": {"id": FIRST}, "notes": "Old root"}
        self.objects[CHILD] = {"id": CHILD, "name": "Old child", "type": "Sound", "classId": 2,
            "path": self.objects[ROOT]["path"] + r"\Old child", "parent": {"id": ROOT}, "notes": "Old child"}
        self.old_child = deepcopy(self.objects[CHILD])
        self.objects["{77777777-7777-7777-7777-777777777777}"] = {
            "id": "{77777777-7777-7777-7777-777777777777}", "name": "Wind", "type": "Sound", "classId": 2,
            "path": self.objects[FIRST]["path"] + r"\Wind", "parent": {"id": FIRST}, "notes": "Keep wind"}

    def call(self, uri: str, args: Any = None, options: Any = None) -> Any:
        if uri.endswith("object.set"):
            for item in args["objects"]:
                if "name" not in item:
                    continue
                source = self.objects[item["object"]]
                before_path = source["path"]
                after_path = before_path.rsplit("\\", 1)[0] + "\\" + item["name"]
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
def test_set_rejects_fictitious_custom_list_without_source_or_live_list_evidence(tmp_path, version):
    task = OwnedGraphTask(tmp_path, version, "object.set")
    next(row for row in task.types if row["name"] == "Sound")["classId"] = 65552
    task.objects[FIRST].update({"type": "Sound", "classId": 65552})
    owner = task.bind(FIRST)
    code, configured = task.step("draft-business-configure", "--name-conflict", "replace")
    assert code == 0, configured
    code, declared = task.step("draft-declare-new", "--declaration-id", "layers", "--parent-handle", owner,
        "--name", "Layers", "--kind", "actor-mixer", "--field", "object_list", "CustomList")
    assert code == 0, declared
    code, rejected = task.step("draft-check")
    assert code == 2 and rejected["error_code"] == "DOCUMENTED_LIST_SELECTION_REQUIRED", rejected
    assert "Metadata" in rejected["details"]["repair"]["choices"]
    assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)


def test_documented_list_merge_uses_explicit_actual_class_projection_without_rewriting_native_type(tmp_path):
    task, _ = _documented_metadata_clear_case(tmp_path, clear=False)
    code, types = task.step("draft-discover-types", "--role", "object", "--meaning", "MetadataSlot")
    assert code == 0, types
    code, configured = task.step("draft-business-configure", "--name-conflict", "merge")
    assert code == 0, configured
    code, declared = task.step("draft-declare-new", "--declaration-id", "slot", "--parent-handle", task.list_owner_handle,
        "--name", "Metadata", "--kind", types["type_candidates"][0]["handle"],
        "--field", "notes", "Updated slot", "--field", "object_list", task.list_field_handle)
    assert code == 0, declared
    original = task.call
    def call(uri, args=None, options=None):
        if uri == "ak.wwise.core.object.set":
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args["objects"] == [{"object": FIRST,
                "@Metadata": [{"type": "MetadataSlot", "name": "Metadata", "notes": "Updated slot"}]}]
            task.objects[CHILD]["notes"] = "Updated slot"
            return {"objects": [{"id": FIRST, "name": "Rain", "@Metadata": [{"id": CHILD, "name": "Metadata"}]}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[CHILD]["type"] == "PluginInnerObject" and task.objects[CHILD]["notes"] == "Updated slot"


@pytest.mark.parametrize("fault", (None, "name", "notes", "path", "rename-owner-good-path", "rename-owner-bad-path"))
def test_documented_list_replace_collision_preserves_unrequested_member(tmp_path, fault):
    task, _ = _documented_metadata_clear_case(tmp_path, clear=False)
    task.objects[ROOT] = {**task.objects[CHILD], "id": ROOT, "name": "Spare",
        "path": task.objects[FIRST]["path"] + r"\Spare", "notes": "Keep spare"}
    preserved = deepcopy(task.objects[ROOT])
    task.objects[FIRST]["@Metadata"].append({"id": ROOT})
    code, types = task.step("draft-discover-types", "--role", "object", "--meaning", "MetadataSlot")
    assert code == 0, types
    code, configured = task.step("draft-business-configure", "--name-conflict", "replace")
    assert code == 0, configured
    if fault in {"rename-owner-good-path", "rename-owner-bad-path"}:
        code, renamed = task.step("draft-declare-existing", "--declaration-id", "owner", "--object-handle", task.list_owner_handle,
            "--field", "new_name", "Storm")
        assert code == 0, renamed
    code, declared = task.step("draft-declare-new", "--declaration-id", "slot", "--parent-handle", task.list_owner_handle,
        "--name", "Metadata", "--kind", types["type_candidates"][0]["handle"],
        "--field", "object_list", task.list_field_handle)
    assert code == 0, declared
    original = task.call
    fresh_id = "{77777777-7777-7777-7777-777777777777}"
    def call(uri, args=None, options=None):
        if uri == "ak.wwise.core.object.set":
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            expected = {"object": FIRST, "@Metadata": [{"type": "MetadataSlot", "name": "Metadata"}]}
            if fault in {"rename-owner-good-path", "rename-owner-bad-path"}:
                expected["name"] = "Storm"
                task.objects[FIRST].update(name="Storm", path=r"\Actor-Mixer Hierarchy\Default Work Unit\Storm")
                task.objects[ROOT]["path"] = task.objects[FIRST]["path"] + r"\Spare"
                if fault == "rename-owner-bad-path":
                    task.objects[ROOT]["path"] += " Unexpected"
            assert args["objects"] == [expected]
            del task.objects[CHILD]
            task.objects[fresh_id] = {"id": fresh_id, "name": "Metadata", "type": "PluginInnerObject", "classId": 5570560,
                "path": task.objects[FIRST]["path"] + r"\Metadata", "owner": {"id": FIRST}, "notes": ""}
            task.objects[FIRST]["@Metadata"] = [{"id": ROOT}, {"id": fresh_id}]
            if fault in {"name", "notes", "path"}:
                task.objects[ROOT][fault] += " Unexpected"
            return {"objects": [{"id": FIRST, "name": task.objects[FIRST]["name"], "@Metadata": [{"id": fresh_id, "name": "Metadata"}]}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    assert {row["id"] for row in shown["artifact"]["prepared_operation"]["verification_plan"]["replaced_list_subtree_rows"]} == {CHILD}
    code, verified = task.finish(tx, shown)
    success = fault in (None, "rename-owner-good-path")
    assert code == (0 if success else 2), verified
    assert verified.get("verified") is success, verified
    if success:
        if fault == "rename-owner-good-path":
            preserved["path"] = r"\Actor-Mixer Hierarchy\Default Work Unit\Storm\Spare"
        assert CHILD not in task.objects and task.objects[ROOT] == preserved


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
def test_set_replace_renames_owner_to_absent_name_and_replaces_its_colliding_child(tmp_path: Path, version: str) -> None:
    task = SetReplaceTask(tmp_path, version)
    source = task.bind(FIRST)
    code, configured = task.step("draft-business-configure", "--name-conflict", "replace")
    assert code == 0, configured
    code, declared = task.step("draft-declare-existing", "--declaration-id", "source", "--object-handle", source,
                               "--field", "new_name", "Storm")
    assert code == 0, declared
    code, child = task.step("draft-declare-new", "--declaration-id", "layers", "--parent-handle", source,
                            "--name", "Layers", "--kind", "actor-mixer")
    assert code == 0, child
    tx, shown = task.preview()
    assert {row["id"] for row in shown["artifact"]["prepared_operation"]["verification_plan"]["replaced_subtree_rows"]} == {ROOT, CHILD}
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, json.dumps(verified)
    assert task.objects[FIRST]["name"] == "Storm" and ROOT not in task.objects and CHILD not in task.objects
    wind = task.objects["{77777777-7777-7777-7777-777777777777}"]
    assert wind["parent"] == {"id": FIRST} and wind["notes"] == "Keep wind"


@pytest.mark.parametrize("version", VERSIONS[1:])
def test_set_reference_array_uses_only_bound_handles_and_verifies_ordered_guids(tmp_path: Path, version: str) -> None:
    task = OwnedGraphTask(tmp_path, version, "object.set")
    task.metadata["Targets"] = {"name": "Targets", "type": "Reference", "display": {"name": "Target objects"}}
    owner, target = task.bind(FIRST), task.bind(SECOND)
    code, discovered = task.step("draft-discover-fields", "--object-handle", owner, "--meaning", "Target objects")
    assert code == 0, discovered
    candidate = discovered["meaning_results"][0]["candidates"][0]
    assert "json_array_of_bound_object_handles" not in candidate["value_input"]["accepted_forms"]
    field = candidate["handle"]
    code, before = task.run("draft-inspect", task.draft, "--task-authority", task.authority)
    assert code == 0, before
    code, declared = task.step("draft-declare-existing", "--declaration-id", "owner", "--object-handle", owner,
                               "--field-value", field, "  " + json.dumps([target, owner]) + "  ")
    expected = "NATIVE_VALUE_UNION_UNAVAILABLE" if version == "2022.1" else "REFERENCE_LIST_EVIDENCE_REQUIRED"
    assert code == 2 and declared["error_code"] == expected, declared
    code, after = task.run("draft-inspect", task.draft, "--task-authority", task.authority)
    assert code == 0 and after["draft"] == before["draft"], after
    assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", VERSIONS[1:])
def test_new_set_descendant_reference_array_uses_the_same_version_boundary(tmp_path: Path, version: str) -> None:
    task = OwnedGraphTask(tmp_path, version, "object.set")
    task.metadata["Targets"] = {"name": "Targets", "type": "Reference", "display": {"name": "Target objects"}}
    owner, target = task.bind(FIRST), task.bind(SECOND)
    code, discovered = task.step("draft-discover-fields", "--semantic-kind", "sound-sfx", "--meaning", "Target objects")
    assert code == 0, discovered
    field = discovered["meaning_results"][0]["candidates"][0]["handle"]
    code, before = task.run("draft-inspect", task.draft, "--task-authority", task.authority)
    assert code == 0, before
    code, declared = task.step("draft-declare-new", "--declaration-id", "rain", "--parent-handle", owner,
        "--kind", "sound-sfx", "--name", "Rain", "--field-value", field, json.dumps([target, owner]))
    expected = "NATIVE_VALUE_UNION_UNAVAILABLE" if version == "2022.1" else "REFERENCE_LIST_EVIDENCE_REQUIRED"
    assert code == 2 and declared["error_code"] == expected, declared
    code, after = task.run("draft-inspect", task.draft, "--task-authority", task.authority)
    assert code == 0 and after["draft"] == before["draft"], after
    assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", VERSIONS)
def test_reference_array_business_schema_matches_each_pinned_lane(tmp_path: Path, version: str) -> None:
    from tests.unit.test_object_graph_business_gateway import _offline
    code, schema = _offline(tmp_path, "operation-schema", "object.set", version=version)
    if version == "2021.1":
        assert code == 0 and schema["operation"]["availability"]["status"] == "unsupported_version", schema
        return
    assert code == 0, schema
    reference_values = schema["business_adapter"]["reference_values"]
    assert ("json_array_of_bound_object_handles" in reference_values["forms"]) is (version != "2022.1")
    assert "curve_points" in reference_values["inline_curve"]["input"]


@pytest.mark.parametrize("version", VERSIONS[1:])
@pytest.mark.parametrize("bad_result", (None, "retain-cleared-reference", "omit-cleared-reference"))
def test_set_reference_null_clears_the_exact_field_with_independent_readback(
    tmp_path: Path, version: str, bad_result: str | None,
) -> None:
    task = OwnedGraphTask(tmp_path, version, "object.set")
    task.metadata["Target"] = {"name": "Target", "type": "Reference", "display": {"name": "Target object"}}
    task.objects[FIRST]["@Target"] = SECOND
    owner = task.bind(FIRST)
    field = task.discover(owner, "Target object")
    code, declared = task.step("draft-declare-existing", "--declaration-id", "owner", "--object-handle", owner,
                               "--field-value", field, "null")
    assert code == 0, declared
    tx, shown = task.preview()
    assert shown["artifact"]["prepared_operation"]["dispatch"]["args"]["objects"] == [{"object": FIRST, "@Target": None}]
    task.bad_result = bad_result
    code, verified = task.finish(tx, shown)
    assert code == (0 if bad_result is None else 2) and verified["verified"] is (bad_result is None), json.dumps(verified)


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("form", ("array", "empty-array", "null"))
def test_create_reference_unions_use_class_field_evidence_and_exact_bound_targets(
    tmp_path: Path, version: str, form: str,
) -> None:
    task = OwnedGraphTask(tmp_path, version, "object.create")
    task.metadata["Targets"] = {"name": "Targets", "type": "Reference", "display": {"name": "Target objects"}}
    owner, target = task.bind(FIRST), task.bind(SECOND)
    code, discovered = task.step("draft-discover-fields", "--semantic-kind", "actor-mixer", "--meaning", "Target objects")
    assert code == 0, discovered
    field = discovered["meaning_results"][0]["candidates"][0]["handle"]
    value = [target, owner] if form == "array" else [] if form == "empty-array" else None
    code, declared = task.step("draft-declare-new", "--declaration-id", "layers", "--parent-handle", owner,
                               "--name", "Layers", "--kind", "actor-mixer",
                               "--field-value", field, json.dumps(value))
    if form != "null":
        if code == 0:
            _, shown = task.preview()
            prepared = shown["artifact"]["prepared_operation"]
            pytest.fail("Unsupported create array accepted: " + json.dumps({"dispatch": prepared["dispatch"],
                        "semantic_preview": prepared["semantic_preview"]}))
        assert code == 2 and declared["error_code"] == "NATIVE_VALUE_UNION_UNAVAILABLE", declared
        assert not any(uri.endswith("object.create") for uri, _, _ in task.calls)
        return
    assert code == 0, declared
    tx, shown = task.preview()
    expected = None
    assert shown["artifact"]["prepared_operation"]["dispatch"]["args"]["@Targets"] == expected
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, json.dumps(verified)


@pytest.mark.parametrize("version", VERSIONS[2:])
@pytest.mark.parametrize("bad_value", ("raw-id", "too-many", "wrong-type"))
def test_set_reference_arrays_reject_unbound_oversized_or_disallowed_targets_without_draft_change(
    tmp_path: Path, version: str, bad_value: str,
) -> None:
    task = OwnedGraphTask(tmp_path, version, "object.set")
    task.metadata["Targets"] = {"name": "Targets", "type": "Reference", "display": {"name": "Target objects"},
        "restriction": {"type": "reference", "restrictions": [{"type": ["WorkUnit"]}]}}
    owner, target = task.bind(FIRST), task.bind(SECOND)
    field = task.discover(owner, "Target objects")
    value = [SECOND] if bad_value == "raw-id" else [target] * 33 if bad_value == "too-many" else [target, owner]
    code, before = task.run("draft-inspect", task.draft, "--task-authority", task.authority)
    assert code == 0, before
    code, rejected = task.step("draft-declare-existing", "--declaration-id", "owner", "--object-handle", owner,
                               "--field-value", field, json.dumps(value))
    assert code == 2, rejected
    code, after = task.run("draft-inspect", task.draft, "--task-authority", task.authority)
    assert code == 0 and after["draft"] == before["draft"], after
    assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)


@pytest.mark.parametrize("version,conflict", [(version, "replace") for version in VERSIONS[1:]] + [("2025.1", "rename")])
def test_set_child_replace_policy_does_not_authorize_existing_target_rename_collision(tmp_path: Path, version: str, conflict: str) -> None:
    task = SetReplaceTask(tmp_path, version)
    task.objects[ROOT].update({"parent": {"id": SECOND}, "path": task.objects[SECOND]["path"] + r"\LAYERS"})
    task.objects[CHILD]["path"] = task.objects[ROOT]["path"] + r"\Old child"
    owner = task.bind(FIRST)
    code, configured = task.step("draft-business-configure", "--name-conflict", conflict)
    assert code == 0, configured
    code, declared = task.step("draft-declare-existing", "--declaration-id", "owner", "--object-handle", owner,
                               "--field", "new_name", "Layers")
    assert code == 0, declared
    code, rejected = task.step("draft-check")
    assert code == 2 and rejected["details"]["issues"][0]["error_code"] == "TARGET_EXISTS", rejected
    assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)


@pytest.mark.parametrize("version,placement", [(version, placement) for version in VERSIONS
    for placement in (("create",) if version == "2021.1" else ("create", "planned", "planned-clear"))])
def test_fictitious_list_never_becomes_business_authority_for_created_or_planned_owner(tmp_path, version, placement):
    """Former ActorMixer.CustomList/Sound effect fixtures had no field/class proof."""
    operation = "object.create" if placement == "create" else "object.set"
    task = OwnedGraphTask(tmp_path, version, operation)
    task.objects[FIRST]["classId"] = 524304
    owner = task.bind(FIRST)
    if placement == "create":
        code, declared = task.step("draft-declare-new", "--declaration-id", "root", "--parent-handle", owner,
            "--name", "Layers", "--kind", "actor-mixer", "--field", "object_list", "CustomList")
        assert code == 0, declared
        code, rejected = task.step("draft-check")
    else:
        code, declared = task.step("draft-declare-new", "--declaration-id", "root", "--parent-handle", owner,
            "--name", "Layers", "--kind", "actor-mixer")
        assert code == 0, declared
        result = declared["draft"]["declared_object"]["result_handle"]
        if placement == "planned-clear":
            code, rejected = task.step("draft-clear-object-list", "--declaration-id", "root",
                "--object-handle", result, "--list-name", "CustomList")
        else:
            code, rejected = task.step("draft-declare-new", "--declaration-id", "member", "--parent-handle", result,
                "--name", "Rain", "--kind", "sound-sfx", "--field", "object_list", "CustomList")
    assert code == 2, rejected
    assert "DOCUMENTED_LIST_SELECTION_REQUIRED" in json.dumps(rejected), rejected
    assert not any(uri.endswith(("object.create", "object.set")) for uri, _, _ in task.calls)


@pytest.mark.parametrize("drift", (None, "membership"))
def test_documented_list_alias_clears_merged_planned_owner_and_keeps_other_graph_state(tmp_path, drift):
    task, _ = _documented_metadata_clear_case(tmp_path, clear=False)
    task.types.append({"classId": 1638416, "name": "WorkUnit", "type": "WObject"})
    task.objects[ROOT] = {"id": ROOT, "name": "New sound", "type": "Sound", "classId": 65552,
        "path": task.objects[SECOND]["path"] + r"\New sound", "parent": {"id": SECOND},
        "notes": "Keep owner", "@Metadata": [{"id": "{77777777-7777-7777-7777-777777777777}"}]}
    old_slot = "{77777777-7777-7777-7777-777777777777}"
    task.objects[old_slot] = {"id": old_slot, "name": "Old metadata", "type": "PluginInnerObject", "classId": 5570560,
        "path": task.objects[ROOT]["path"] + r"\Old metadata", "owner": {"id": ROOT}, "notes": "Old"}
    keep = deepcopy(task.objects[FIRST])
    parent = task.bind(SECOND)
    code, configured = task.step("draft-business-configure", "--name-conflict", "merge")
    assert code == 0, configured
    code, owner = task.step("draft-declare-new", "--declaration-id", "owner", "--parent-handle", parent,
        "--name", "New sound", "--kind", "sound-sfx")
    assert code == 0, owner
    code, cleared = task.step("draft-clear-object-list", "--declaration-id", "owner",
        "--object-handle", owner["draft"]["declared_object"]["result_handle"], "--list-name", "Metadata")
    assert code == 0, cleared
    original = task.call
    def call(uri, args=None, options=None):
        if uri == "ak.wwise.core.object.set":
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args["objects"] == [{"object": SECOND, "listMode": "replaceAll", "children": [
                {"type": "Sound", "name": "New sound", "@Metadata": []}]}]
            task.objects[ROOT]["@Metadata"] = []
            del task.objects[old_slot]
            return {"objects": [{"id": SECOND, "name": "Default Work Unit", "children": [{"id": ROOT, "name": "New sound"}]}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    if drift:
        code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
        assert code == 0, confirmed
        task.objects[ROOT]["@Metadata"] = []
        code, rejected = task.run("execute", tx)
        assert code == 2 and rejected.get("executed") is not True, rejected
        assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)
        return
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, verified
    assert old_slot not in task.objects and task.objects[ROOT]["notes"] == "Keep owner"
    assert task.objects[FIRST] == keep


@pytest.mark.parametrize("fault", (None, "wrong-target-type", "reference-effect"))
def test_planned_metadata_slot_scalar_reference_stays_distinct_from_sound_metadata_list(tmp_path, fault):
    """2025 Objects Reference: Sound.Metadata List; MetadataSlot.Metadata Reference."""
    task, _ = _documented_metadata_clear_case(tmp_path, clear=False)
    task.types.extend(({"classId": 1638416, "name": "WorkUnit", "type": "WObject"},
        {"classId": 5308432, "name": "Metadata", "type": "WObject"}))
    metadata_id = "{55555555-5555-5555-5555-555555555555}"
    task.objects[metadata_id] = {"id": metadata_id, "name": "Room metadata", "type": "Sound" if fault == "wrong-target-type" else "Metadata",
        "classId": 5308432, "path": r"\Metadata\Default Work Unit\Room metadata", "parent": {"id": PROJECT_GROUP}, "notes": "Keep metadata"}
    parent, target = task.bind(SECOND), task.bind(metadata_id)
    original = task.call
    def call(uri, args=None, options=None):
        if uri.endswith(("getPropertyAndReferenceNames", "getPropertyInfo")):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args.get("classId") == 5570560, args
            if uri.endswith("getPropertyAndReferenceNames"):
                return {"return": ["Metadata"]}
            assert args["property"] == "Metadata"
            return {"name": "Metadata", "type": "Reference", "display": {"name": "Metadata"},
                "restriction": {"type": "reference", "restrictions": [{"type": ["Metadata"]}, "notNull"]}}
        if uri == "ak.wwise.core.object.set":
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args["objects"] == [{"object": SECOND, "children": [{"type": "Sound", "name": "New sound",
                "@Metadata": [{"type": "MetadataSlot", "name": "Room slot", "@Metadata": metadata_id}]}]}]
            task.objects[ROOT] = {"id": ROOT, "name": "New sound", "type": "Sound", "classId": 65552,
                "path": task.objects[SECOND]["path"] + r"\New sound", "parent": {"id": SECOND}, "notes": "", "@Metadata": [{"id": "{77777777-7777-7777-7777-777777777777}"}]}
            slot = "{77777777-7777-7777-7777-777777777777}"
            task.objects[slot] = {"id": slot, "name": "Room slot", "type": "PluginInnerObject", "classId": 5570560,
                "path": task.objects[ROOT]["path"] + r"\Room slot", "owner": {"id": ROOT}, "notes": "",
                "@Metadata": {"id": SECOND if fault == "reference-effect" else metadata_id}}
            return {"objects": [{"id": SECOND, "name": "Default Work Unit", "children": [{"id": ROOT, "name": "New sound",
                "@Metadata": [{"id": slot, "name": "Room slot"}]}]}]}
        return original(uri, args, options)
    task.call = call
    kinds = {}
    for name in ("Sound", "MetadataSlot"):
        code, types = task.step("draft-discover-types", "--role", "object", "--meaning", name)
        assert code == 0, types
        kinds[name] = types["type_candidates"][0]["handle"]
    code, listed = task.step("draft-discover-fields", "--type-handle", kinds["Sound"], "--field-source", "documented-lists", "--list")
    assert code == 0, listed
    choice = next(row for row in listed["agent_result"]["items"] if row["name"] == "Metadata")
    code, selected = task.step("draft-discover-fields", "--type-handle", kinds["Sound"], "--field-source", "documented-lists", "--selection", choice["selection"])
    assert code == 0, selected
    list_field = selected["meaning_results"][0]["candidates"][0]["handle"]
    code, selected = task.step("draft-discover-fields", "--type-handle", kinds["MetadataSlot"], "--meaning", "Metadata")
    assert code == 0, selected
    scalar_field = selected["meaning_results"][0]["candidates"][0]["handle"]
    code, owner = task.step("draft-declare-new", "--declaration-id", "owner", "--parent-handle", parent,
        "--name", "New sound", "--kind", kinds["Sound"])
    assert code == 0, owner
    code, declared = task.step("draft-declare-new", "--declaration-id", "slot", "--parent-handle", owner["draft"]["declared_object"]["result_handle"],
        "--name", "Room slot", "--kind", kinds["MetadataSlot"], "--field", "object_list", list_field, "--field-value", scalar_field, target)
    if fault == "wrong-target-type":
        assert code == 2 and declared["error_code"] == "REFERENCE_TARGET_TYPE_MISMATCH", declared
        assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)
        return
    assert code == 0, declared
    tx, shown = task.preview()
    prepared = shown["artifact"]["prepared_operation"]
    assert len(prepared["pre_state"]["documented_planned_list_guards"]) == 1
    assert "documented_planned_reference_guards" not in prepared["pre_state"]
    code, verified = task.finish(tx, shown)
    assert code == (0 if fault is None else 2), verified
    assert (verified.get("verified") is True) == (fault is None), verified
    assert any(uri.endswith("getPropertyInfo") and args.get("classId") == 5570560 and args.get("property") == "Metadata"
        for uri, args, _ in task.calls)


@pytest.mark.parametrize("fault", (None, "wrong-reference-effect", "wrong-class-effect", "missing-target-effect", "duplicate-target-result", "wrong-planned-type", "foreign-result", "not-null", "field-drift", "class-drift"))
def test_new_slot_scalar_reference_uses_same_graph_target_result_handle_and_actual_guid(tmp_path, fault):
    task, _ = _documented_metadata_clear_case(tmp_path, clear=False)
    task.types.extend({"classId": cid, "name": name, "type": "WObject"} for name, cid in (
        ("WorkUnit", 1638416), ("SwitchGroup", 1245200), ("MusicSwitchContainer", 2293776), ("MusicArgumentsSlot", 5832704)))
    switch_parent_id = "{ABABABAB-ABAB-ABAB-ABAB-ABABABABABAB}"
    music_parent_id = "{CDCDCDCD-CDCD-CDCD-CDCD-CDCDCDCDCDCD}"
    task.objects[switch_parent_id] = {"id": switch_parent_id, "name": "Default Work Unit", "type": "WorkUnit", "classId": 1638416,
        "path": r"\Switches\Default Work Unit", "parent": None, "notes": "Keep switches"}
    task.objects[music_parent_id] = {"id": music_parent_id, "name": "Default Work Unit", "type": "WorkUnit", "classId": 1638416,
        "path": r"\Interactive Music Hierarchy\Default Work Unit", "parent": None, "notes": "Keep music"}
    switch_parent, music_parent = task.bind(switch_parent_id), task.bind(music_parent_id)
    original = task.call
    group_id, slot_id = "{55555555-5555-5555-5555-555555555555}", "{77777777-7777-7777-7777-777777777777}"
    def call(uri, args=None, options=None):
        if uri.endswith(("getPropertyAndReferenceNames", "getPropertyInfo")):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args.get("classId") == 5832704, args
            if uri.endswith("getPropertyAndReferenceNames"):
                return {"return": ["Argument"]}
            assert args["property"] == "Argument", args
            return {"name": "Argument", "type": "Reference", "display": {"name": "Argument"},
                "restriction": {"type": "reference", "restrictions": [{"type": ["StateGroup"] if getattr(task, "reference_drift", False) else ["SwitchGroup", "StateGroup"]}, "notNull"]}}
        if uri == "ak.wwise.core.object.set":
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args["objects"] == [
                {"object": switch_parent_id, "children": [{"type": "SwitchGroup", "name": "Surface"}]},
                {"object": music_parent_id, "children": [{"type": "MusicSwitchContainer", "name": "Music",
                    "@Arguments": [{"type": "MusicArgumentsSlot", "name": "Surface argument", "@Argument": r"\Switches\Default Work Unit\Surface"}]}]}]
            task.objects[group_id] = {"id": group_id, "name": "Surface", "type": "SwitchGroup", "classId": 1245200,
                "path": r"\Switches\Default Work Unit\Surface", "parent": {"id": switch_parent_id}, "notes": ""}
            task.objects[ROOT] = {"id": ROOT, "name": "Music", "type": "MusicSwitchContainer", "classId": 2293776,
                "path": task.objects[music_parent_id]["path"] + r"\Music", "parent": {"id": music_parent_id}, "notes": "", "@Arguments": [{"id": slot_id}]}
            task.objects[slot_id] = {"id": slot_id, "name": "Surface argument", "type": "PluginInnerObject", "classId": 5832704,
                "path": task.objects[ROOT]["path"] + r"\Surface argument", "owner": {"id": ROOT}, "notes": "", "@Argument": {"id": music_parent_id if fault == "wrong-reference-effect" else group_id}}
            if fault == "wrong-class-effect":
                task.objects[group_id]["classId"] = 65552
            elif fault == "missing-target-effect":
                del task.objects[group_id]
            target_results = [{"id": group_id, "name": "Surface"}] * (2 if fault == "duplicate-target-result" else 1)
            return {"objects": [{"id": switch_parent_id, "name": "Default Work Unit", "children": target_results},
                {"id": music_parent_id, "name": "Default Work Unit", "children": [{"id": ROOT, "name": "Music", "@Arguments": [{"id": slot_id, "name": "Surface argument"}]}]}]}
        return original(uri, args, options)
    task.call = call
    kinds = {}
    for name in ("SwitchGroup", "MusicSwitchContainer", "MusicArgumentsSlot", "Sound"):
        code, found = task.step("draft-discover-types", "--role", "object", "--meaning", name)
        assert code == 0, found
        kinds[name] = found["type_candidates"][0]["handle"]
    code, listed = task.step("draft-discover-fields", "--type-handle", kinds["MusicSwitchContainer"], "--field-source", "documented-lists", "--list")
    assert code == 0, listed
    choice = next(row for row in listed["agent_result"]["items"] if row["name"] == "Arguments")
    code, found = task.step("draft-discover-fields", "--type-handle", kinds["MusicSwitchContainer"], "--field-source", "documented-lists", "--selection", choice["selection"])
    assert code == 0, found
    list_field = found["meaning_results"][0]["candidates"][0]["handle"]
    code, found = task.step("draft-discover-fields", "--type-handle", kinds["MusicArgumentsSlot"], "--meaning", "Argument")
    assert code == 0, found
    argument = found["meaning_results"][0]["candidates"][0]["handle"]
    code, group = task.step("draft-declare-new", "--declaration-id", "group", "--parent-handle", switch_parent,
        "--name", "Surface", "--kind", kinds["Sound" if fault == "wrong-planned-type" else "SwitchGroup"])
    assert code == 0, group
    code, music = task.step("draft-declare-new", "--declaration-id", "music", "--parent-handle", music_parent,
        "--name", "Music", "--kind", kinds["MusicSwitchContainer"])
    assert code == 0, music
    code, slot = task.step("draft-declare-new", "--declaration-id", "slot", "--parent-handle", music["draft"]["declared_object"]["result_handle"],
        "--name", "Surface argument", "--kind", kinds["MusicArgumentsSlot"], "--field", "object_list", list_field,
        "--field-value", argument, "null" if fault == "not-null" else "bnh1-" + "0" * 32 if fault == "foreign-result" else group["draft"]["declared_object"]["result_handle"])
    if fault in {"wrong-planned-type", "foreign-result"}:
        assert code == 2 and slot["error_code"] == ("REFERENCE_TARGET_TYPE_MISMATCH" if fault == "wrong-planned-type" else "PLANNED_REFERENCE_TARGET_NOT_AVAILABLE"), slot
        assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)
        return
    assert code == 0, slot
    if fault == "not-null":
        code, rejected = task.step("draft-check")
        assert code == 2 and "INVALID_REFERENCE_TARGET" in json.dumps(rejected), rejected
        assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)
        return
    tx, shown = task.preview()
    if fault in {"field-drift", "class-drift"}:
        code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
        assert code == 0, confirmed
        if fault == "field-drift":
            task.reference_drift = True
        else:
            next(row for row in task.types if row["name"] == "SwitchGroup")["classId"] = 65552
        code, rejected = task.run("execute", tx)
        assert code == 2 and rejected.get("executed") is not True, rejected
        assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)
        return
    code, verified = task.finish(tx, shown)
    assert code == (0 if fault is None else 2), verified
    assert (verified.get("verified") is True) == (fault is None), verified
    if fault is None:
        assert task.objects[slot_id]["@Argument"] == {"id": group_id}
    assert len([uri for uri, _, _ in task.calls if uri.endswith("object.set")]) == 1


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("fault", (None, "wrong-reference-effect", "nullable"))
def test_create_auxbus_sibling_reference_uses_new_result_or_native_nullable_value(tmp_path, version, fault):
    """AuxBus.UserAuxSend0 is a scalar AuxBus reference in all five Objects References."""
    task = OwnedGraphTask(tmp_path, version, "object.create")
    task.require_class_projection = True
    task.types = [{"classId": cid, "name": name, "type": "WObject"} for name, cid in (
        ("WorkUnit", 1638416), ("Bus", 1376272), ("AuxBus", 3997712))]
    bus_parent_id = "{ABABABAB-ABAB-ABAB-ABAB-ABABABABABAB}"
    task.objects[bus_parent_id] = {"id": bus_parent_id, "name": "Default Work Unit", "type": "WorkUnit", "classId": 1638416,
        "path": r"\Master-Mixer Hierarchy\Default Work Unit", "parent": None, "notes": "Keep buses"}
    parent = task.bind(bus_parent_id)
    target_id, source_id = "{55555555-5555-5555-5555-555555555555}", "{66666666-6666-6666-6666-666666666666}"
    original = task.call
    def call(uri, args=None, options=None):
        if uri.endswith(("getPropertyAndReferenceNames", "getPropertyInfo")):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args.get("classId") == 3997712, args
            if uri.endswith("getPropertyAndReferenceNames"):
                return {"return": ["UserAuxSend0"]}
            assert args["property"] == "UserAuxSend0", args
            return {"name": "UserAuxSend0", "type": "Reference", "display": {"name": "User-Defined Auxiliary Send 0"},
                "restriction": {"type": "reference", "restrictions": [{"type": ["AuxBus"]}]}}
        if uri == "ak.wwise.core.object.create":
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            target_value = None if fault == "nullable" else r"\Master-Mixer Hierarchy\Default Work Unit\Routing\Destination"
            assert args == {"parent": bus_parent_id, "type": "Bus", "name": "Routing", "children": [
                {"type": "AuxBus", "name": "Destination"}, {"type": "AuxBus", "name": "Sender", "@UserAuxSend0": target_value}],
                "onNameConflict": "fail", "autoAddToSourceControl": False}
            base = task.objects[bus_parent_id]["path"] + r"\Routing"
            task.objects[ROOT] = {"id": ROOT, "name": "Routing", "type": "Bus", "classId": 1376272,
                "path": base, "parent": {"id": bus_parent_id}, "notes": ""}
            for identity, name in ((target_id, "Destination"), (source_id, "Sender")):
                task.objects[identity] = {"id": identity, "name": name, "type": "AuxBus", "classId": 3997712,
                    "path": base + "\\" + name, "parent": {"id": ROOT}, "notes": ""}
            task.objects[source_id]["@UserAuxSend0"] = None if fault == "nullable" else {"id": ROOT if fault == "wrong-reference-effect" else target_id}
            return {"id": ROOT, "name": "Routing", "children": [{"id": target_id, "name": "Destination"}, {"id": source_id, "name": "Sender"}]}
        return original(uri, args, options)
    task.call = call
    kinds = {}
    for name in ("Bus", "AuxBus"):
        code, found = task.step("draft-discover-types", "--role", "object", "--meaning", name)
        assert code == 0, found
        kinds[name] = found["type_candidates"][0]["handle"]
    code, found = task.step("draft-discover-fields", "--type-handle", kinds["AuxBus"], "--meaning", "User-Defined Auxiliary Send 0")
    assert code == 0, found
    field = found["meaning_results"][0]["candidates"][0]["handle"]
    code, root = task.step("draft-declare-new", "--declaration-id", "root", "--parent-handle", parent, "--name", "Routing", "--kind", kinds["Bus"])
    assert code == 0, root
    root_handle = root["draft"]["declared_object"]["result_handle"]
    code, target = task.step("draft-declare-new", "--declaration-id", "target", "--parent-handle", root_handle, "--name", "Destination", "--kind", kinds["AuxBus"])
    assert code == 0, target
    code, source = task.step("draft-declare-new", "--declaration-id", "source", "--parent-handle", root_handle, "--name", "Sender", "--kind", kinds["AuxBus"],
        "--field-value", field, "null" if fault == "nullable" else target["draft"]["declared_object"]["result_handle"])
    assert code == 0, source
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == (2 if fault == "wrong-reference-effect" else 0), verified
    assert (verified.get("verified") is True) == (fault != "wrong-reference-effect"), verified
    assert len([uri for uri, _, _ in task.calls if uri.endswith("object.create")]) == 1


@pytest.mark.parametrize("receiver,field_style,rename_case", (("existing", "handle", None), ("existing", "stable", None), ("new", "handle", None), ("new", "stable", None),
    ("existing", "handle", "collision"), ("new", "handle", "collision"), ("existing", "handle", "old-notes-effect"), ("existing", "handle", "collision-drift"), ("existing", "handle", "parent-rename"), ("existing", "handle", "parent-collision"), ("existing", "handle", "parent-merge")))
def test_object_set_orders_new_bus_target_before_new_or_existing_sound_receiver(tmp_path, receiver, field_style, rename_case):
    task = OwnedGraphTask(tmp_path, "2025.1", "object.set")
    task.require_class_projection = True
    task.types = [{"classId": cid, "name": name, "type": "WObject"} for name, cid in (
        ("Sound", 65552), ("WorkUnit", 1638416), ("Bus", 1376272))]
    task.objects[FIRST].update(type="Sound", classId=65552)
    task.objects[SECOND].update(classId=1638416, parent=None)
    bus_parent = "{ABABABAB-ABAB-ABAB-ABAB-ABABABABABAB}"
    task.objects[bus_parent] = {"id": bus_parent, "name": "Default Work Unit", "type": "WorkUnit", "classId": 1638416,
        "path": r"\Master-Mixer Hierarchy\Default Work Unit", "parent": None, "notes": "Keep buses"}
    target_collision = rename_case in {"collision", "old-notes-effect", "collision-drift"}
    parent_rename = rename_case in {"parent-rename", "parent-collision", "parent-merge"}
    prepared_bus_name = "New bus17" if target_collision else "New bus"
    prepared_parent_name = "Renamed routing_waapi_1" if rename_case == "parent-collision" else "Renamed routing"
    if parent_rename:
        work_unit = "{BCBCBCBC-BCBC-BCBC-BCBC-BCBCBCBCBCBC}"
        task.objects[work_unit] = deepcopy(task.objects[bus_parent])
        task.objects[work_unit]["id"] = work_unit
        task.objects[bus_parent].update(type="Bus", classId=1376272, name="Routing", parent={"id": work_unit},
            path=task.objects[work_unit]["path"] + r"\Routing")
        if rename_case == "parent-collision":
            task.objects[CHILD] = {"id": CHILD, "name": "Renamed routing", "type": "Bus", "classId": 1376272,
                "path": task.objects[work_unit]["path"] + r"\Renamed routing", "parent": {"id": work_unit}, "notes": "Keep old collision"}
    prepared_parent_path = (task.objects[work_unit]["path"] + "\\" + prepared_parent_name) if parent_rename else task.objects[bus_parent]["path"]
    prepared_bus_path = prepared_parent_path + "\\" + prepared_bus_name
    if target_collision:
        task.objects[CHILD] = {"id": CHILD, "name": "New bus", "type": "Bus", "classId": 1376272,
            "path": task.objects[bus_parent]["path"] + r"\New bus", "parent": {"id": bus_parent}, "notes": "Keep old collision"}
    parent, owner, destination = task.bind(SECOND), task.bind(FIRST), task.bind(bus_parent)
    if rename_case:
        code, configured = task.step("draft-business-configure", "--name-conflict", "merge" if rename_case == "parent-merge" else "rename")
        assert code == 0, configured
    original = task.call
    bus_id, sound_id = "{55555555-5555-5555-5555-555555555555}", FIRST if receiver == "existing" else ROOT
    sound_name = task.objects[FIRST]["name"] if receiver == "existing" else "New sound"
    native_receiver = {"object": FIRST, "@OutputBus": prepared_bus_path} if receiver == "existing" else {
        "object": SECOND, "children": [{"type": "Sound", "name": sound_name, "@OutputBus": prepared_bus_path}]}
    expected_objects = [{"object": bus_parent, **({"name": prepared_parent_name} if parent_rename else {}),
        "children": [{"type": "Bus", "name": prepared_bus_name}]}, native_receiver]
    expected_creation = deepcopy(expected_objects)
    if target_collision:
        expected_creation[0]['children'][0]['name'] = 'New bus'
        if receiver == 'existing':
            del expected_creation[1]['@OutputBus']
        else:
            del expected_creation[1]['children'][0]['@OutputBus']
    def call(uri, args=None, options=None):
        if uri.endswith(("getPropertyAndReferenceNames", "getPropertyInfo")):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args.get("object") in {FIRST, sound_id} or args.get("classId") == 65552, args
            if uri.endswith("getPropertyAndReferenceNames"):
                return {"return": ["OutputBus"]}
            assert args["property"] == "OutputBus", args
            return {"name": "OutputBus", "type": "Reference", "display": {"name": "Output Bus"},
                "restriction": {"type": "reference", "restrictions": [{"type": ["Bus"]}]}}
        if uri == "ak.wwise.core.object.set":
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            if target_collision and all('children' not in item for item in args['objects']):
                assert args == {'objects': [{'object': sound_id, '@OutputBus': prepared_bus_path}]}
                task.objects[sound_id]['@OutputBus'] = {'id': bus_id}
                return {'objects': []}
            assert args["objects"] == expected_creation
            if parent_rename:
                task.objects[bus_parent].update(name=prepared_parent_name, path=prepared_parent_path)
            task.objects[bus_id] = {"id": bus_id, "name": prepared_bus_name, "type": "Bus", "classId": 1376272,
                "path": prepared_bus_path, "parent": {"id": bus_parent}, "notes": ""}
            if receiver == "new":
                task.objects[sound_id] = {"id": sound_id, "name": sound_name, "type": "Sound", "classId": 65552,
                    "path": task.objects[SECOND]["path"] + "\\" + sound_name, "parent": {"id": SECOND}, "notes": ""}
            if not target_collision:
                task.objects[sound_id]["@OutputBus"] = {"id": bus_id}
            if rename_case == "old-notes-effect":
                task.objects[CHILD]["notes"] = "Unexpected"
            source_result = {"id": FIRST, "name": sound_name} if receiver == "existing" else {
                "id": SECOND, "name": "Default Work Unit", "children": [{"id": sound_id, "name": sound_name}]}
            return {"objects": [{"id": bus_parent, "name": prepared_parent_name if parent_rename else "Default Work Unit", "children": [{"id": bus_id, "name": prepared_bus_name}]}, source_result]}
        return original(uri, args, options)
    task.call = call
    kinds = {}
    for name in ("Bus", "Sound"):
        code, found = task.step("draft-discover-types", "--role", "object", "--meaning", name)
        assert code == 0, found
        kinds[name] = found["type_candidates"][0]["handle"]
    field = None
    if field_style == "handle":
        code, found = task.step("draft-discover-fields", *( ["--object-handle", owner] if receiver == "existing" else ["--type-handle", kinds["Sound"]]), "--meaning", "Output Bus")
        assert code == 0, found
        field = found["meaning_results"][0]["candidates"][0]["handle"]
    if parent_rename:
        code, changed = task.step("draft-declare-existing", "--declaration-id", "rename-parent", "--object-handle", destination,
            "--field", "new_name", "Renamed routing")
        assert code == 0, changed
    code, target = task.step("draft-declare-new", "--declaration-id", "bus", "--parent-handle", destination,
        "--name", "New bus", "--kind", kinds["Bus"])
    assert code == 0, target
    target_handle = target["draft"]["declared_object"]["result_handle"]
    assignment = ["--field", "output_bus", target_handle] if field_style == "stable" else ["--field-value", field, target_handle]
    if receiver == "existing":
        code, source = task.step("draft-declare-existing", "--declaration-id", "source", "--object-handle", owner, *assignment)
    else:
        code, source = task.step("draft-declare-new", "--declaration-id", "source", "--parent-handle", parent,
            "--name", sound_name, "--kind", kinds["Sound"], *assignment)
    assert code == 0, source
    if rename_case == 'parent-collision':
        code, rejected = task.step('draft-check')
        assert code == 2 and rejected['error_code'] == 'TARGET_EXISTS', rejected
        assert not any(uri.endswith('object.set') for uri, _, _ in task.calls)
        assert not (task.path / 'state' / 'transactions').exists()
        return
    tx, shown = task.preview()
    assert shown["artifact"]["prepared_operation"]["dispatch"]["args"]["objects"] == (expected_objects if not target_collision else [
        {"object": bus_parent, "children": [{"type": "Bus", "name": "New bus"}]},
        {"object": FIRST, "@OutputBus": task.objects[bus_parent]['path'] + r'\New bus'} if receiver == 'existing' else {
            "object": SECOND, "children": [{"type": "Sound", "name": sound_name, "@OutputBus": task.objects[bus_parent]['path'] + r'\New bus'}]}])
    if rename_case:
        assert shown["artifact"]["prepared_operation"]["dispatch"]["args"]["onNameConflict"] == ("merge" if rename_case == "parent-merge" else "rename")
        assert (prepared_parent_name if parent_rename else "New bus") in json.dumps(shown)
        assert '_waapi_' not in json.dumps(shown)
    if rename_case == "collision-drift":
        code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
        assert code == 0, confirmed
        task.objects[CHILD]['notes'] = 'Unreviewed collision drift'
        code, rejected = task.run("execute", tx)
        assert code == 2 and rejected.get("executed") is not True, rejected
        assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)
        return
    if rename_case == 'old-notes-effect':
        assert task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
        code, rejected = task.run('execute', tx)
        assert code == 2 and rejected['state'] == 'indeterminate', rejected
        assert len([row for row in task.calls if row[0].endswith('object.set')]) == 1
        return
    code, verified = task.finish(tx, shown)
    assert code == 0, json.dumps(verified)
    assert (verified.get("verified") is True) == (rename_case != "old-notes-effect"), verified
    if rename_case == "collision":
        assert task.objects[CHILD]["notes"] == "Keep old collision"
    assert task.objects[sound_id]["@OutputBus"] == {"id": bus_id}


@pytest.mark.parametrize("version,state,fault", [(version, False, None) for version in VERSIONS[1:]] +
    [("2022.1", True, None), ("2025.1", True, None)] + [("2025.1", False, fault) for fault in
        ("reverse-fields", "missing-controller", "wrong-controller", "wrong-parent-effect", "nullable-default")])
def test_new_result_reference_hierarchy_reuses_explicit_planned_controller_and_parent_proof(tmp_path, version, state, fault):
    task = OwnedGraphTask(tmp_path, version, "object.set")
    task.require_class_projection = True
    group_type, value_type = ("StateGroup", "State") if state else ("SwitchGroup", "Switch")
    group_class, value_class = (458768, 393232) if state else (1245200, 1310736)
    group_path = (r"\States" if state else r"\Switches") + r"\Default Work Unit\Surface"
    task.types = [{"classId": cid, "name": name, "type": "WObject"} for name, cid in (
        ("WorkUnit", 1638416), (group_type, group_class), (value_type, value_class), ("SwitchContainer", 655376))]
    switch_parent = "{ABABABAB-ABAB-ABAB-ABAB-ABABABABABAB}"
    task.objects[switch_parent] = {"id": switch_parent, "name": "Default Work Unit", "type": "WorkUnit", "classId": 1638416,
        "path": group_path.rsplit("\\", 1)[0], "parent": None, "notes": "Keep switches"}
    task.objects[SECOND]["classId"] = 1638416
    parent, group_parent = task.bind(SECOND), task.bind(switch_parent)
    group_id, value_id = "{55555555-5555-5555-5555-555555555555}", "{66666666-6666-6666-6666-666666666666}"
    metadata = {
        "DefaultSwitchOrState": {"name": "DefaultSwitchOrState", "type": "", "default": None,
            "restriction": {"type": "reference", "restrictions": [{"childOfReference": "SwitchGroupOrStateGroup"}, {"type": ["Switch", "State"]}]},
            "dependencies": [{"type": "reference", "action": "Enable", "context": "Self", "property": "SwitchGroupOrStateGroup", "conditions": [{"referenceIsSet": True}]}]},
        "SwitchGroupOrStateGroup": {"name": "SwitchGroupOrStateGroup", "type": "", "default": None,
            "restriction": {"type": "reference", "restrictions": [{"type": ["SwitchGroup", "StateGroup"]}]}}}
    original = task.call
    def call(uri, args=None, options=None):
        if uri.endswith(("getPropertyAndReferenceNames", "getPropertyInfo")):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args.get("classId") == 655376, args
            if uri.endswith("getPropertyAndReferenceNames"):
                return {"return": list(metadata)}
            return deepcopy(metadata[args["property"]])
        if uri == "ak.wwise.core.object.set":
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args["objects"] == [{"object": switch_parent, "children": [{"type": group_type, "name": "Surface",
                "children": [{"type": value_type, "name": "Concrete"}]}]},
                {"object": SECOND, "children": [{"type": "SwitchContainer", "name": "Footsteps",
                    "@DefaultSwitchOrState": None if fault == "nullable-default" else group_path + r"\Concrete",
                    "@SwitchGroupOrStateGroup": group_path}]}]
            task.objects[group_id] = {"id": group_id, "name": "Surface", "type": group_type, "classId": group_class,
                "path": group_path, "parent": {"id": switch_parent}, "notes": ""}
            task.objects[value_id] = {"id": value_id, "name": "Concrete", "type": value_type, "classId": value_class,
                "path": task.objects[group_id]["path"] + r"\Concrete", "parent": {"id": SECOND if fault == "wrong-parent-effect" else group_id}, "notes": ""}
            task.objects[ROOT] = {"id": ROOT, "name": "Footsteps", "type": "SwitchContainer", "classId": 655376,
                "path": task.objects[SECOND]["path"] + r"\Footsteps", "parent": {"id": SECOND}, "notes": "",
                "@DefaultSwitchOrState": None if fault == "nullable-default" else {"id": value_id}, "@SwitchGroupOrStateGroup": {"id": group_id}}
            return {"objects": [{"id": switch_parent, "name": "Default Work Unit", "children": [{"id": group_id, "name": "Surface", "children": [{"id": value_id, "name": "Concrete"}]}]},
                {"id": SECOND, "name": "Default Work Unit", "children": [{"id": ROOT, "name": "Footsteps"}]}]}
        return original(uri, args, options)
    task.call = call
    kinds, fields = {}, {}
    for name in (group_type, value_type, "SwitchContainer"):
        code, found = task.step("draft-discover-types", "--role", "object", "--meaning", name)
        assert code == 0, found
        kinds[name] = found["type_candidates"][0]["handle"]
    for name in metadata:
        code, found = task.step("draft-discover-fields", "--type-handle", kinds["SwitchContainer"], "--meaning", name)
        assert code == 0, found
        fields[name] = found["meaning_results"][0]["candidates"][0]["handle"]
    code, group = task.step("draft-declare-new", "--declaration-id", "group", "--parent-handle", group_parent, "--name", "Surface", "--kind", kinds[group_type])
    assert code == 0, group
    group_handle = group["draft"]["declared_object"]["result_handle"]
    code, value = task.step("draft-declare-new", "--declaration-id", "value", "--parent-handle", group_handle, "--name", "Concrete", "--kind", kinds[value_type])
    assert code == 0, value
    controller = group_handle
    if fault == "wrong-controller":
        code, other = task.step("draft-declare-new", "--declaration-id", "other", "--parent-handle", group_parent, "--name", "Other group", "--kind", kinds[group_type])
        assert code == 0, other
        controller = other["draft"]["declared_object"]["result_handle"]
    assignments = [(fields["DefaultSwitchOrState"], "null" if fault == "nullable-default" else value["draft"]["declared_object"]["result_handle"])]
    if fault != "missing-controller":
        assignments.append((fields["SwitchGroupOrStateGroup"], controller))
    if fault == "reverse-fields":
        assignments.reverse()
    code, source = task.step("draft-declare-new", "--declaration-id", "source", "--parent-handle", parent, "--name", "Footsteps", "--kind", kinds["SwitchContainer"],
        *(argument for field, handle in assignments for argument in ("--field-value", field, handle)))
    assert code == 0, source
    if fault in {"missing-controller", "wrong-controller"}:
        code, rejected = task.step("draft-check")
        assert code == 2 and ("REFERENCE_ACTIVATION_REQUIRED" if fault == "missing-controller" else "INVALID_REFERENCE_TARGET") in json.dumps(rejected), rejected
        assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)
        return
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == (2 if fault == "wrong-parent-effect" else 0), verified
    assert (verified.get("verified") is True) == (fault != "wrong-parent-effect"), verified


def test_existing_guid_rename_cannot_verify_a_native_creation_suffix(tmp_path):
    task = OwnedGraphTask(tmp_path, '2025.1', 'object.set')
    task.types = [{'name': name, 'classId': cid, 'type': 'WObject'} for name, cid in
        [('Sound', 65552), ('WorkUnit', 1638416)]]
    task.objects[FIRST].update(type='Sound', classId=65552)
    task.objects[SECOND]['classId'] = 1638416
    owner = task.bind(FIRST)
    assert task.step('draft-business-configure', '--name-conflict', 'rename')[0] == 0
    assert task.step('draft-declare-existing', '--declaration-id', 'rename', '--object-handle', owner,
        '--field', 'new_name', 'Exact requested name')[0] == 0
    original = task.call
    def wrong_name(uri, args=None, options=None):
        if uri.endswith('object.set'):
            row = task.objects[FIRST]
            row.update(name='Exact requested name_7', path=task.objects[SECOND]['path'] + r'\Exact requested name_7')
        return original(uri, args, options)
    task.call = wrong_name
    tx, shown = task.preview()
    code, failed = task.finish(tx, shown)
    assert code == 2 and failed['verified'] is False, failed
