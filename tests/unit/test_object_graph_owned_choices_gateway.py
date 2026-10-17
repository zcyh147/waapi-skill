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
    disclosure = bound["draft"]["next_action_binding"]["field_discovery"]["documented_lists"]
    assert disclosure["append"] == ["--field-source", "documented-lists", "--list"]
    assert disclosure["scope"] == "copy_exact_bound_owner_handle_or_type_handle"


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


def _documented_metadata_clear_case(tmp_path, version="2025.1", *, alias=False, select=True, list_name="Metadata", clear=True):
    task = OwnedGraphTask(tmp_path, version, "object.set")
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
            if getattr(self, "require_class_projection", False) and "classId" not in options.get("return", []):
                rows = [{key: value for key, value in row.items() if key != "classId"} for row in rows]
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


def test_documented_list_replace_collision_preserves_unrequested_member(tmp_path):
    task, _ = _documented_metadata_clear_case(tmp_path, clear=False)
    task.objects[ROOT] = {**task.objects[CHILD], "id": ROOT, "name": "Spare",
        "path": task.objects[FIRST]["path"] + r"\Spare", "notes": "Keep spare"}
    preserved = deepcopy(task.objects[ROOT])
    task.objects[FIRST]["@Metadata"].append({"id": ROOT})
    code, types = task.step("draft-discover-types", "--role", "object", "--meaning", "MetadataSlot")
    assert code == 0, types
    code, configured = task.step("draft-business-configure", "--name-conflict", "replace")
    assert code == 0, configured
    code, declared = task.step("draft-declare-new", "--declaration-id", "slot", "--parent-handle", task.list_owner_handle,
        "--name", "Metadata", "--kind", types["type_candidates"][0]["handle"],
        "--field", "object_list", task.list_field_handle)
    assert code == 0, declared
    original = task.call
    fresh_id = "{77777777-7777-7777-7777-777777777777}"
    def call(uri, args=None, options=None):
        if uri == "ak.wwise.core.object.set":
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args["objects"] == [{"object": FIRST, "@Metadata": [{"type": "MetadataSlot", "name": "Metadata"}]}]
            del task.objects[CHILD]
            task.objects[fresh_id] = {"id": fresh_id, "name": "Metadata", "type": "PluginInnerObject", "classId": 5570560,
                "path": task.objects[FIRST]["path"] + r"\Metadata", "owner": {"id": FIRST}, "notes": ""}
            task.objects[FIRST]["@Metadata"] = [{"id": ROOT}, {"id": fresh_id}]
            return {"objects": [{"id": FIRST, "name": "Rain", "@Metadata": [{"id": fresh_id, "name": "Metadata"}]}]}
        return original(uri, args, options)
    task.call = call
    tx, shown = task.preview()
    assert {row["id"] for row in shown["artifact"]["prepared_operation"]["verification_plan"]["replaced_list_subtree_rows"]} == {CHILD}
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, verified
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
                               "--name", "Layers", "--kind", "actor-mixer", "--field", "object_list", "CustomList",
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


@pytest.mark.parametrize("version", VERSIONS[1:])
def test_set_child_replace_policy_does_not_authorize_existing_target_rename_collision(tmp_path: Path, version: str) -> None:
    task = SetReplaceTask(tmp_path, version)
    task.objects[ROOT].update({"parent": {"id": SECOND}, "path": task.objects[SECOND]["path"] + r"\LAYERS"})
    task.objects[CHILD]["path"] = task.objects[ROOT]["path"] + r"\Old child"
    owner = task.bind(FIRST)
    code, configured = task.step("draft-business-configure", "--name-conflict", "replace")
    assert code == 0, configured
    code, declared = task.step("draft-declare-existing", "--declaration-id", "owner", "--object-handle", owner,
                               "--field", "new_name", "Layers")
    assert code == 0, declared
    code, rejected = task.step("draft-check")
    assert code == 2 and rejected["details"]["issues"][0]["error_code"] == "TARGET_EXISTS", rejected
    assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)
