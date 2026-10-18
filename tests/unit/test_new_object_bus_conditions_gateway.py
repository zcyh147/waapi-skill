"""Prospective bus conditions use proved class/placement, never guessed native state."""
from copy import deepcopy
import json

import pytest

from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, FIRST, SECOND, ROOT, CHILD


def _bus_children_task(tmp_path, *, source_kind="AuxBus", parent_kind="Bus", explicit=None, fault=None):
    task = OwnedGraphTask(tmp_path, "2025.1", "object.set")
    classes = {"Bus": 1376272, "AuxBus": 3997712, "WorkUnit": 1638416}
    task.require_class_projection = True
    task.types = [{"name": name, "classId": value, "type": "WObject"} for name, value in classes.items()]
    task.objects = {
        SECOND: {"id": SECOND, "name": "Default Work Unit", "type": "WorkUnit", "classId": classes["WorkUnit"],
            "path": r"\Busses\Default Work Unit", "notes": "Keep Work Unit"},
        FIRST: {"id": FIRST, "name": "Routing", "type": parent_kind, "classId": classes[parent_kind],
            "path": r"\Busses\Default Work Unit\Routing", "parent": {"id": SECOND}, "notes": "Keep existing bus"},
    }
    # Exact observed 2025 reference dependency grammar; controller row remains fixture-only.
    task.metadata = {
        "UserAuxSend0": {"name": "UserAuxSend0", "type": "", "default": None,
            "restriction": {"type": "reference", "restrictions": [{"type": ["Auxiliary Bus"], "sharedOnlyTypes": []}]},
            "dependencies": [{"type": "isMasterBus", "action": "Show", "context": "Self", "value": False},
                {"type": "override", "action": "Enable", "context": "Self", "property": "OverrideUserAuxSends"}]},
        "OverrideUserAuxSends": {"name": "OverrideUserAuxSends", "type": "bool", "default": False,
            "dependencies": [{"type": "override", "action": "Enable", "context": "Self", "property": "OverrideUserAuxSends"}]},
    }
    parent = task.bind(FIRST)
    kinds = {}
    for name in ("Bus", "AuxBus"):
        code, found = task.step("draft-discover-types", "--role", "object", "--meaning", name)
        assert code == 0, found
        kinds[name] = found["type_candidates"][0]["handle"]
    code, found = task.step("draft-discover-fields", "--type-handle", kinds[source_kind], "--list")
    selected = next(row["selection"] for row in found["agent_result"]["fields"] if row["name"] == "UserAuxSend0")
    code, found = task.step("draft-discover-fields", "--type-handle", kinds[source_kind], "--selection", selected)
    assert code == 0, found
    field = found["meaning_results"][0]["candidates"][0]["handle"]
    code, target = task.step("draft-declare-new", "--declaration-id", "target", "--parent-handle", parent,
        "--name", "Destination", "--kind", kinds["AuxBus"])
    assert code == 0, target
    target_handle = target["draft"]["declared_object"]["result_handle"]
    extra = []
    if explicit is not None:
        code, listed = task.step("draft-discover-fields", "--type-handle", kinds[source_kind], "--list")
        assert code == 0, listed
        selected = next(row["selection"] for row in listed["agent_result"]["fields"] if row["name"] == "OverrideUserAuxSends")
        code, found = task.step("draft-discover-fields", "--type-handle", kinds[source_kind], "--selection", selected)
        assert code == 0, found
        switch = found["meaning_results"][0]["candidates"][0]["handle"]
        extra = ["--field-value", switch, "true" if explicit else "false"]
    code, declared = task.step("draft-declare-new", "--declaration-id", "source", "--parent-handle", parent,
        "--name", "Sender", "--kind", kinds[source_kind], "--field-value", field, target_handle, *extra)
    assert code == 0, declared
    original = task.call
    writes = []
    def call(uri, args=None, options=None):
        if uri.endswith("object.set"):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            writes.append(deepcopy(args))
            assert args["objects"] == [{"object": FIRST, "children": [
                {"type": "AuxBus", "name": "Destination"}, {"type": source_kind, "name": "Sender",
                    "@UserAuxSend0": task.objects[FIRST]["path"] + r"\Destination", "@OverrideUserAuxSends": True}]}]
            for identity, name, kind in ((ROOT, "Destination", "AuxBus"), (CHILD, "Sender", source_kind)):
                task.objects[identity] = {"id": identity, "name": name, "type": kind, "classId": classes[kind],
                    "path": task.objects[FIRST]["path"] + "\\" + name, "parent": {"id": FIRST}, "notes": ""}
            task.objects[CHILD].update({"@UserAuxSend0": {"id": ROOT}, "@OverrideUserAuxSends": True})
            if fault == "parent-class-effect": task.objects[FIRST]["classId"] = 65552
            return {"objects": [{"id": FIRST, "name": "Routing", "children": [
                {"id": ROOT, "name": "Destination"}, {"id": CHILD, "name": "Sender"}]}]}
        return original(uri, args, options)
    task.call = call
    return task, writes


@pytest.mark.parametrize("source_kind,parent_kind,explicit", [("AuxBus", "Bus", None), ("Bus", "AuxBus", None), ("Bus", "Bus", True), ("AuxBus", "AuxBus", True)])
def test_new_bus_reference_below_existing_bus_keeps_same_graph_and_controller_intent(tmp_path, source_kind, parent_kind, explicit):
    task, writes = _bus_children_task(tmp_path, source_kind=source_kind, parent_kind=parent_kind, explicit=explicit)
    tx, shown = task.preview()
    nodes = shown["artifact"]["prepared_operation"]["verification_plan"]["nodes"]
    source = next(node for node in nodes if node.get("requested_name") == "Sender")
    evidence = source["new_object_default_evidence"][0]
    assert evidence["structural_visibility"][0]["proof"]["parent"]["object_id"] == FIRST
    assert evidence["requirements"][0]["source"] == ("explicit" if explicit else "derived")
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, verified
    assert len(writes) == 1 and task.objects[FIRST]["notes"] == "Keep existing bus"


@pytest.mark.parametrize("fault", ("explicit-false", "root-master-placement", "wrong-parent-class"))
def test_new_bus_reference_rejects_conflict_or_unproved_existing_parent_before_write(tmp_path, fault):
    task, writes = _bus_children_task(tmp_path, parent_kind="WorkUnit" if fault == "root-master-placement" else "Bus",
        explicit=False if fault == "explicit-false" else None)
    if fault == "wrong-parent-class": task.objects[FIRST]["classId"] = 65552
    code, rejected = task.step("draft-check")
    assert code == 2, rejected
    assert rejected["error_code"] == ("NEW_OBJECT_DEPENDENCY_CONFLICT" if fault == "explicit-false" else "NEW_OBJECT_DEPENDENCY_UNSUPPORTED")
    assert not writes


@pytest.mark.parametrize("fault", ("parent-class-drift", "source-drift", "parent-class-effect"))
def test_new_bus_reference_revalidates_existing_parent_and_source_and_effect(tmp_path, monkeypatch, fault):
    from wwise_waapi import documented_list_fields
    from wwise_waapi.documented_list_fields import canonical_sha256
    task, writes = _bus_children_task(tmp_path, fault=fault)
    if fault == "source-drift":
        source = tmp_path / "catalog" / "2025.1" / "documented-list-fields.json"
        source.parent.mkdir(parents=True)
        source.write_bytes((documented_list_fields.CATALOG_ROOT / "2025.1" / source.name).read_bytes())
        monkeypatch.setattr(documented_list_fields, "CATALOG_ROOT", source.parents[1])
    tx, shown = task.preview()
    if fault == "parent-class-effect":
        code, verified = task.finish(tx, shown)
        assert code == 2 and verified.get("verified") is not True, verified
        assert len(writes) == 1
        return
    if fault == "parent-class-drift": task.objects[FIRST]["classId"] = 65552
    if fault == "source-drift":
        catalog = json.loads(source.read_text())
        catalog["source"]["build"] += "-changed"
        catalog["catalog_sha256"] = canonical_sha256({key: value for key, value in catalog.items() if key != "catalog_sha256"})
        source.write_text(json.dumps(catalog))
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    code, rejected = task.run("execute", tx)
    assert code == 2 and rejected.get("executed") is not True, rejected
    assert not writes
