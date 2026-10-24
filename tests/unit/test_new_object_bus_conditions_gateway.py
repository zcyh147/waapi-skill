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
    # Exact observed 2025 reference dependency grammar; no controller exists on this class.
    task.metadata = {
        "UserAuxSend0": {"name": "UserAuxSend0", "type": "", "default": None,
            "restriction": {"type": "reference", "restrictions": [{"type": ["Auxiliary Bus"], "sharedOnlyTypes": []}]},
            "dependencies": [{"type": "isMasterBus", "action": "Show", "context": "Self", "value": False},
                {"type": "override", "action": "Enable", "context": "Self", "property": "OverrideUserAuxSends"}]},
        "OverrideUserAuxSends": {"name": "OverrideUserAuxSends", "type": "bool", "default": False,
            "dependencies": [{"type": "override", "action": "Enable", "context": "Self", "property": "OverrideUserAuxSends"}]},
    }
    if explicit is None:
        del task.metadata["OverrideUserAuxSends"]
    task.metadata["UserAuxSend0"]["supports"] = {"unlink": False, "rtpc": "None", "randomizer": False}
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
                    "@UserAuxSend0": task.objects[FIRST]["path"] + r"\Destination"}]}]
            for identity, name, kind in ((ROOT, "Destination", "AuxBus"), (CHILD, "Sender", source_kind)):
                task.objects[identity] = {"id": identity, "name": name, "type": kind, "classId": classes[kind],
                    "path": task.objects[FIRST]["path"] + "\\" + name, "parent": {"id": FIRST}, "notes": ""}
            task.objects[CHILD].update({"@UserAuxSend0": {"id": ROOT}})
            if fault == "parent-class-effect": task.objects[FIRST]["classId"] = 65552
            return {"objects": [{"id": FIRST, "name": "Routing", "children": [
                {"id": ROOT, "name": "Destination"}, {"id": CHILD, "name": "Sender"}]}]}
        return original(uri, args, options)
    task.call = call
    return task, writes


@pytest.mark.parametrize("source_kind,parent_kind,explicit", [("AuxBus", "Bus", None), ("Bus", "AuxBus", None), ("Bus", "Bus", None), ("AuxBus", "AuxBus", None)])
def test_new_bus_reference_below_existing_bus_keeps_same_graph_and_controller_intent(tmp_path, source_kind, parent_kind, explicit):
    task, writes = _bus_children_task(tmp_path, source_kind=source_kind, parent_kind=parent_kind, explicit=explicit)
    tx, shown = task.preview()
    nodes = shown["artifact"]["prepared_operation"]["verification_plan"]["nodes"]
    source = next(node for node in nodes if node.get("requested_name") == "Sender")
    evidence = source["new_object_default_evidence"][0]
    assert evidence["structural_visibility"][0]["proof"]["parent"]["object_id"] == FIRST
    assert evidence["requirements"] == [] and evidence["derived_properties"] == {}
    assert evidence["override_applicability"][0]["kind"] == "not_applicable_on_class"
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
    assert rejected["error_code"] == ("OVERRIDE_APPLICABILITY_INVALID" if fault == "explicit-false" else "INVALID_OBJECT_TYPE" if fault == "wrong-parent-class" else "NEW_OBJECT_DEPENDENCY_UNSUPPORTED")
    if fault == "wrong-parent-class":
        assert task.objects[FIRST]["classId"] == 65552
        assert "class" in json.dumps(rejected).lower()
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


def _non_bus_reference_task(tmp_path, version='2025.1'):
    from tests.unit.test_workflow_source_guard import _created_fields_history_runtime, _CREATED_HISTORY_NATIVE_2025_METADATA
    _runtime, _commands, writes, task = _created_fields_history_runtime(tmp_path, None, version,
        source_metadata=_CREATED_HISTORY_NATIVE_2025_METADATA)
    task.objects[ROOT] = {'id': ROOT, 'name': 'Existing attenuation', 'type': 'Attenuation', 'classId': 655376,
        'path': r'\Attenuations\Default Work Unit\Existing attenuation', 'notes': 'Keep target',
        'parent': {'id': '{66666666-6666-6666-6666-666666666666}'}}
    parent, target = task.bind(SECOND), task.bind(ROOT)
    code, fields = task.step('draft-discover-fields', '--semantic-kind', 'sound-sfx', '--meaning', 'Attenuation')
    assert code == 0, fields
    reference = fields['meaning_results'][0]['candidates'][0]['handle']
    code, declared = task.step('draft-declare-new', '--declaration-id', 'source', '--parent-handle', parent,
        '--kind', 'sound-sfx', '--name', 'Rain', '--field', 'loop', 'infinite', '--field-value', reference, target)
    assert code == 0, declared
    return task, writes


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1'])
def test_new_known_non_bus_class_keeps_same_call_reference_conditions(tmp_path, version):
    #2025 raw condition grammar replay, version-pinned class proof only; no native applicability claim.
    task, writes = _non_bus_reference_task(tmp_path, version)
    tx, shown = task.preview()
    spec, = shown['artifact']['prepared_operation']['verification_plan']['nodes']
    evidence, = spec['new_object_default_evidence']
    rule, = evidence['structural_visibility']
    assert rule['field'] == 'Attenuation' and rule['proof']['kind'] == 'non_bus_class'
    assert rule['proof']['class_id'] == 65552 and rule['proof']['parent'] == {}
    assert rule['proof']['bus_classes'] == {'Bus': 1376272, 'AuxBus': 3997712}
    assert evidence['derived_properties'] == {'OverridePositioning': True}
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert len(writes) == 1 and writes[0][1]['@OverridePositioning'] is True
    assert writes[0][1]['@IsLoopingEnabled'] is True and writes[0][1]['@IsLoopingInfinite'] is True
    assert task.objects[ROOT]['notes'] == 'Keep target'


@pytest.mark.parametrize('fault', ['wrong-class', 'prewrite-class', 'effect-class', 'master-predicate'])
def test_new_non_bus_visibility_never_accepts_unproved_class_or_wrong_created_class(tmp_path, fault):
    task, writes = _non_bus_reference_task(tmp_path)
    if fault in {'wrong-class', 'master-predicate'}:
        if fault == 'wrong-class': next(row for row in task.types if row['name'] == 'Sound')['classId'] = 65553
        else: task.metadata['Attenuation']['dependencies'][0]['value'] = True
        code, rejected = task.step('draft-check')
        assert code == 2 and rejected['error_code'] == ('FIELD_HANDLE_STALE' if fault == 'master-predicate' else 'NEW_OBJECT_DEPENDENCY_UNSUPPORTED'), rejected
        assert writes == []
        return
    tx, shown = task.preview()
    if fault == 'prewrite-class':
        next(row for row in task.types if row['name'] == 'Sound')['classId'] = 65553
        code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
        assert code == 0, confirmed
        code, rejected = task.run('execute', tx)
        assert code == 2 and writes == [], rejected
    else:
        original = task.call
        def wrong_effect(uri, args=None, options=None):
            result = original(uri, args, options)
            if uri.endswith('object.create'): task.objects[result['id']]['classId'] = 1376272
            return result
        task.call = wrong_effect
        code, rejected = task.finish(tx, shown)
        assert code == 2 and rejected.get('verified') is not True and len(writes) == 1, rejected
