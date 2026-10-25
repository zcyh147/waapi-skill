"""The legacy Playlist is ordered references to preserved hierarchy children."""
from copy import deepcopy
import json
import pytest
from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, FIRST, SECOND, ROOT, CHILD


def playlist_task(tmp_path, version, mode, *, fault=None, planned=None):
    task = OwnedGraphTask(tmp_path, version, "object.set")
    task.types = [{"classId": 589840, "name": "RandomSequenceContainer", "type": "WObject"},
        {"classId": 65552, "name": "Sound", "type": "WObject"},
        {"classId": 1638416, "name": "WorkUnit", "type": "WObject"}]
    task.objects[SECOND].update(classId=1638416)
    task.objects[FIRST] = {"id": FIRST, "name": "Numbers", "type": "RandomSequenceContainer", "classId": 589840,
        "path": task.objects[SECOND]["path"] + r"\Numbers", "parent": {"id": SECOND},
        "notes": "Keep owner", "@RandomOrSequence": 1, "@Playlist": [{"id": ROOT}]}
    for identity, name in [(ROOT, "One"), (CHILD, "Two")]:
        task.objects[identity] = {"id": identity, "name": name, "type": "Sound", "classId": 65552,
            "path": task.objects[FIRST]["path"] + "\\" + name, "parent": {"id": FIRST}, "notes": "Keep " + name}
    task.objects[CHILD]["owner"] = None
    owner = task.bind(FIRST)
    targets = [task.bind(CHILD), task.bind(CHILD)] if mode == "replace-all" else [task.bind(CHILD)]
    scope = ["--object-handle", owner]
    if planned:
        parent = task.bind(SECOND)
        code, discovered = task.step("draft-discover-types", "--role", "object", "--meaning", "RandomSequenceContainer")
        assert code == 0, discovered
        kind = discovered["type_candidates"][0]["handle"]
        scope = ["--type-handle", kind]
    code, listed = task.step("draft-discover-fields", *scope,
        "--field-source", "documented-lists", "--list")
    assert code == 0, listed
    choice = next(row for row in listed["agent_result"]["items"] if row["name"] == "Playlist")
    code, selected = task.step("draft-discover-fields", *scope,
        "--field-source", "documented-lists", "--selection", choice["selection"])
    assert code == 0, selected
    field = selected["meaning_results"][0]["candidates"][0]["handle"]
    if mode != "clear":
        code, configured = task.step("draft-business-configure", "--list-behavior", mode,
            *(["--name-conflict", "merge"] if planned == "merge" else []))
        assert code == 0, configured
    if mode == "clear":
        code, declared = task.step("draft-clear-object-list", "--declaration-id", "clear", "--object-handle", owner, "--list-name", field)
    elif planned:
        code, declared = task.step("draft-declare-new", "--declaration-id", "playlist", "--parent-handle", parent,
            "--kind", kind, "--name", "Numbers" if planned == "merge" else "Fresh", "--field-value", field, json.dumps(targets))
    else:
        code, declared = task.step("draft-declare-existing", "--declaration-id", "playlist", "--object-handle", owner,
            "--field-value", field, json.dumps(targets))
    assert code == 0, declared
    preserved = deepcopy(task.objects)
    original = task.call
    def call(uri, args=None, options=None):
        if uri == "ak.wwise.core.object.set":
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            expected = [] if mode == "clear" else [CHILD, CHILD] if mode == "replace-all" else [CHILD]
            native_owner = args["objects"][0]["children"][0] if planned else args["objects"][0]
            assert native_owner["@Playlist"] == expected
            roster = [] if mode in {"clear", "replace-all"} else [ROOT]
            task.objects[FIRST]["@Playlist"] = [{"id": value} for value in [*roster, *expected]]
            if fault == "lost-prefix":
                task.objects[FIRST]["@Playlist"] = [{"id": CHILD}]
            elif fault == "retained-member":
                task.objects[FIRST]["@Playlist"].insert(0, {"id": ROOT})
            elif fault == "changed-target":
                task.objects[ROOT]["notes"] = "Unexpected"
            elif fault == "deleted-target":
                del task.objects[ROOT]
            elif fault == "missing-roster":
                del task.objects[FIRST]["@Playlist"]
            return {"objects": ([{"id": SECOND, "name": "Default Work Unit", "children": [{"id": FIRST, "name": "Numbers"}]}]
                if planned else [{"id": FIRST, "name": "Numbers"}])}
        return original(uri, args, options)
    task.call = call
    return task, preserved


@pytest.mark.parametrize("version", ["2023.1", "2024.1"])
def test_legacy_playlist_replaces_ordered_references_and_preserves_hierarchy(tmp_path, version):
    task, before = playlist_task(tmp_path, version, "replace-all")
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[FIRST]["@Playlist"] == [{"id": CHILD}, {"id": CHILD}]
    assert task.objects[ROOT] == before[ROOT] and task.objects[CHILD] == before[CHILD]


@pytest.mark.parametrize("version", ["2023.1", "2024.1"])
def test_legacy_playlist_append_keeps_ordered_existing_prefix(tmp_path, version):
    task, before = playlist_task(tmp_path, version, "append")
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[FIRST]["@Playlist"] == [{"id": ROOT}, {"id": CHILD}]
    assert task.objects[ROOT] == before[ROOT] and task.objects[CHILD] == before[CHILD]


@pytest.mark.parametrize("version", ["2023.1", "2024.1"])
def test_legacy_playlist_clear_removes_references_and_retains_all_hierarchy_targets(tmp_path, version):
    task, before = playlist_task(tmp_path, version, "clear")
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[FIRST]["@Playlist"] == []
    assert task.objects[ROOT] == before[ROOT] and task.objects[CHILD] == before[CHILD]


@pytest.mark.parametrize("version", ["2023.1", "2024.1"])
@pytest.mark.parametrize("fault", ["wrong-parent", "parent-drift", "roster-drift"])
def test_legacy_playlist_rejects_nonchild_and_preview_drift_before_write(tmp_path, version, fault):
    task, _ = playlist_task(tmp_path, version, "append")
    if fault == "wrong-parent":
        task.objects[CHILD]["parent"] = {"id": SECOND}
        code, rejected = task.step("draft-check")
        assert code == 2, rejected
    else:
        tx, shown = task.preview()
        if fault == "parent-drift":
            task.objects[CHILD]["parent"] = {"id": SECOND}
        else:
            task.objects[FIRST]["@Playlist"] = [{"id": CHILD}]
        code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
        assert code == 0, confirmed
        code, rejected = task.run("execute", tx)
        assert code == 2, rejected
    assert not any(uri.endswith(("object.set", "object.delete")) for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", ["2023.1", "2024.1"])
@pytest.mark.parametrize("mode,fault", [("append", "lost-prefix"), ("clear", "retained-member"),
    ("clear", "changed-target"), ("replace-all", "deleted-target"), ("clear", "missing-roster")])
def test_legacy_playlist_never_certifies_wrong_roster_or_lost_target_proof(tmp_path, version, mode, fault):
    task, _ = playlist_task(tmp_path, version, mode, fault=fault)
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 2 and verified.get("verified") is not True, verified
    assert len([uri for uri, _, _ in task.calls if uri.endswith("object.set")]) == 1
    assert not any(uri.endswith("object.delete") for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", ["2023.1", "2024.1"])
def test_legacy_playlist_class_selection_rejects_existing_targets_for_uncreated_owner(tmp_path, version):
    task, _ = playlist_task(tmp_path, version, "append", planned="new")
    code, rejected = task.step("draft-check")
    assert code == 2, rejected
    assert "direct child" in json.dumps(rejected), rejected
    assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", ["2023.1", "2024.1"])
def test_legacy_playlist_class_selection_merges_actual_owner_and_preserves_prefix(tmp_path, version):
    task, before = playlist_task(tmp_path, version, "append", planned="merge")
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[FIRST]["@Playlist"] == [{"id": ROOT}, {"id": CHILD}]
    assert task.objects[ROOT] == before[ROOT] and task.objects[CHILD] == before[CHILD]


@pytest.mark.parametrize("version", ["2023.1", "2024.1"])
@pytest.mark.parametrize("fault", ["wrong-parent", "changed-target"])
def test_legacy_playlist_merged_owner_retains_reference_parent_and_preservation_proof(tmp_path, version, fault):
    task, _ = playlist_task(tmp_path, version, "append", planned="merge", fault=fault)
    if fault == "wrong-parent":
        task.objects[CHILD]["parent"] = {"id": SECOND}
        code, rejected = task.step("draft-check")
        assert code == 2, rejected
        assert not any(uri.endswith("object.set") for uri, _, _ in task.calls)
    else:
        tx, shown = task.preview()
        code, verified = task.finish(tx, shown)
        assert code == 2 and verified.get("verified") is not True, verified
