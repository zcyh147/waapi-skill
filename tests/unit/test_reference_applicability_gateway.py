"""Public reference visibility uses structural evidence, not property enabled state."""
from copy import deepcopy

import pytest

from tests.unit.test_conditional_reference_gateway import MasterBusDeviceTask
from tests.unit.test_field_interface_closure_gateway import FIRST, SECOND

WORKUNIT = "{33333333-3333-3333-3333-333333333333}"
ROOT = "{44444444-4444-4444-4444-444444444444}"
SYSTEM = "{77777777-7777-7777-7777-777777777777}"


class StructuralMasterTask(MasterBusDeviceTask):
    def __init__(self, path, version="2024.1", operation="object.setReference"):
        super().__init__(path, version, operation)
        self.operation = operation
        root = "Busses" if version == "2025.1" else "Master-Mixer Hierarchy"
        self.objects[FIRST].update(classId=1376272, path="\\" + root + "\\Default Work Unit\\Main Mix",
            parent={"id": WORKUNIT, "name": "Default Work Unit"})
        self.objects[SECOND].update(classId=11862023, name="No_Output", path=r"\Audio Devices\Default Work Unit\No_Output")
        self.objects[SYSTEM] = {"id": SYSTEM, "name": "System", "type": "AudioDevice", "classId": 11403271,
            "path": r"\Audio Devices\Default Work Unit\System"}
        self.objects[FIRST]["AudioDevice"] = {"id": SYSTEM}
        self.objects[WORKUNIT] = {"id": WORKUNIT, "name": "Default Work Unit", "type": "WorkUnit",
            "classId": 1638416, "path": "\\" + root + "\\Default Work Unit", "parent": {"id": ROOT, "name": root}}
        # A hierarchy root is an observed read-only boundary, not a guessed class.
        self.objects[ROOT] = {"id": ROOT, "name": root, "path": "\\" + root}
        self.types = [{"classId": 1376272, "name": "Bus", "type": "WObject"},
            {"classId": 11862023, "name": "AudioDevice", "type": "WObject"},
            {"classId": 1638416, "name": "WorkUnit", "type": "WObject"},
            {"classId": 131088, "name": "Folder", "type": "WObject"}]
        # Literal R75 R1/R2 metadata shape; empty type and spaced target label.
        self.metadata["AudioDevice"].update(default=None, supports={"unlink": True, "randomizer": False, "rtpc": "None"},
            restriction={"type": "reference", "restrictions": [{"type": ["Audio Device"], "sharedOnlyTypes": []}, "notNull"]})

    def call(self, uri, args=None, options=None):
        if uri.endswith("isPropertyEnabled") and args["property"] == "AudioDevice":
            self.calls.append((uri, deepcopy(args), options))
            raise RuntimeError("ak.wwise.invalid_arguments: Property doesn't exist on the object.")
        return super().call(uri, args, options)


def prepare(task, platform=None):
    source, target = task.bind(FIRST), task.bind(SECOND)
    code, discovered = task.step("draft-discover-fields", "--object-handle", source, "--meaning", "AudioDevice", *(["--platform", platform] if platform else []))
    assert code == 0, discovered
    candidate, = discovered["meaning_results"][0]["candidates"]
    assert candidate["applicability"]["kind"] == "structural-reference-visibility"
    assert candidate["applicability"]["native_enabled_state"] == "not_queried"
    code, declared = (task.step("draft-declare-field-change", "--object-handle", source,
        "--field-handle", candidate["handle"], "--target-handle", target) if task.operation == "object.setReference" else
        task.step("draft-declare-existing", "--declaration-id", "device", "--object-handle", source,
            "--field-value", candidate["handle"], target))
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    assert preview["preview_summary"]["reference_applicability"][0]["native_enabled_state"] == "not_queried"
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    return tx, shown


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
@pytest.mark.parametrize("operation", ["object.setReference", "object.set"])
def test_public_native_shaped_master_reference_uses_structural_applicability(tmp_path, version, operation):
    task = StructuralMasterTask(tmp_path, version, operation)
    before = deepcopy(task.objects)
    tx, shown = prepare(task)
    state = shown["artifact"]["prepared_operation"]["pre_state"]
    condition = state["condition_metadata"] if operation == "object.setReference" else state["condition_metadata_guards"][0]
    assert condition["structural_applicability"][0]["kind"] == "structural-reference-visibility"
    if operation == "object.setReference":
        assert shown["artifact"]["prepared_operation"]["dispatch"]["args"] == {"object": FIRST, "reference": "AudioDevice", "value": SECOND}
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    code, executed = task.run("execute", tx)
    assert code == 0, executed
    code, verified = task.run("verify", tx)
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects == {**before, FIRST: {**before[FIRST], "AudioDevice": {"id": SECOND}}}
    assert not any(uri.endswith("isPropertyEnabled") for uri, _, _ in task.calls)
    assert sum(uri.endswith(("setReference", "setProperty", "object.set")) for uri, _, _ in task.calls) == 1


def authorize(task, tx, shown):
    code, result = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, result


@pytest.mark.parametrize("root_parent", ["omitted", None])
@pytest.mark.parametrize("platform", [None, "{55555555-5555-5555-5555-555555555555}"])
def test_structural_reference_preserves_native_root_shape_and_selected_platform(tmp_path, root_parent, platform):
    task = StructuralMasterTask(tmp_path)
    if root_parent != "omitted":
        task.objects[ROOT]["parent"] = root_parent
    before = deepcopy(task.objects)
    tx, shown = prepare(task, platform)
    proof = shown["artifact"]["prepared_operation"]["pre_state"]["condition_metadata"]["structural_applicability"][0]
    assert proof["rows"][-1] == before[ROOT]
    assert proof["platform"] == platform
    authorize(task, tx, shown)
    assert task.run("execute", tx)[0] == 0
    code, verified = task.run("verify", tx)
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[ROOT] == before[ROOT]
    assert task.objects[FIRST]["AudioDevice"] == {"id": SECOND}


def add_folder(task, kind="Folder"):
    folder = "{66666666-6666-6666-6666-666666666666}"
    root = task.objects[ROOT]
    task.objects[folder] = {"id": folder, "name": "Nested", "type": kind,
        "classId": 131088 if kind == "Folder" else 1376272,
        "path": root["path"] + "\\Nested", "parent": {"id": ROOT, "name": root["name"]}}
    task.objects[WORKUNIT]["parent"] = {"id": folder, "name": "Nested"}
    for identity in (WORKUNIT, FIRST):
        task.objects[identity]["path"] = task.objects[identity]["path"].replace(root["path"], root["path"] + "\\Nested", 1)
    return folder


def test_topmost_bus_may_have_virtual_folder_and_workunit_ancestors(tmp_path):
    task = StructuralMasterTask(tmp_path)
    add_folder(task)
    tx, shown = prepare(task)
    authorize(task, tx, shown)
    assert task.run("execute", tx)[0] == 0
    code, verified = task.run("verify", tx)
    assert code == 0 and verified["verified"] is True, verified


@pytest.mark.parametrize("damage", ["bus-above-workunit", "missing-parent", "cycle", "wrong-class", "numeric-class", "wrong-root", "missing-root", "duplicate-root"])
def test_unproven_master_reference_context_stops_discovery_without_write(tmp_path, damage):
    task = StructuralMasterTask(tmp_path)
    if damage == "bus-above-workunit":
        add_folder(task, "Bus")
    elif damage == "missing-parent":
        del task.objects[WORKUNIT]["parent"]
    elif damage == "cycle":
        task.objects[WORKUNIT]["parent"] = {"id": FIRST}
    elif damage in {"wrong-class", "numeric-class"}:
        task.objects[WORKUNIT]["classId"] = 131088 if damage == "wrong-class" else True
    elif damage == "wrong-root":
        task.objects[ROOT]["path"] = "\\Events"
    elif damage == "missing-root":
        del task.objects[ROOT]
    else:
        original = task.call
        def call(uri, args=None, options=None):
            result = original(uri, args, options)
            if uri.endswith("object.get") and args.get("from", {}).get("id") == [ROOT]:
                result["return"] *= 2
            return result
        task.call = call
    source = task.bind(FIRST)
    before = deepcopy(task.objects)
    code, rejected = task.step("draft-discover-fields", "--object-handle", source, "--meaning", "AudioDevice")
    assert code == 2, rejected
    assert task.objects == before
    assert not any(uri.endswith(("isPropertyEnabled", "setReference", "object.set")) for uri, _, _ in task.calls)


@pytest.mark.parametrize("operation", ["object.setReference", "object.set"])
@pytest.mark.parametrize("stage", ["before", "after"])
@pytest.mark.parametrize("damage", ["parent", "metadata", "typed-parent-extension", "root-presence"])
def test_structural_reference_ancestry_and_metadata_remain_bound_through_execution(tmp_path, operation, stage, damage):
    task = StructuralMasterTask(tmp_path, operation=operation)
    task.objects[WORKUNIT]["parent"]["future"] = {"enabled": False, "count": 0}
    tx, shown = prepare(task)
    authorize(task, tx, shown)
    def drift():
        if damage == "parent":
            task.objects[WORKUNIT]["parent"]["id"] = SECOND
        elif damage == "metadata":
            task.metadata["AudioDevice"]["dependencies"][0]["value"] = 1
        elif damage == "typed-parent-extension":
            task.objects[WORKUNIT]["parent"]["future"]["enabled"] = 0
        else:
            task.objects[ROOT]["parent"] = None
    if stage == "before":
        drift()
    code, executed = task.run("execute", tx)
    if stage == "before":
        assert code == 2, executed
        assert not any(uri.endswith(("setReference", "object.set")) for uri, _, _ in task.calls)
    else:
        assert code == 0, executed
        drift()
        code, verified = task.run("verify", tx)
        assert code == 2 and verified["verified"] is False, verified
        assert task.objects[FIRST]["AudioDevice"] == {"id": SECOND}


def test_structural_reference_refresh_rejects_ancestry_drift_before_preview(tmp_path):
    task = StructuralMasterTask(tmp_path)
    source, target = task.bind(FIRST), task.bind(SECOND)
    field = task.discover(source, "AudioDevice")
    task.objects[WORKUNIT]["parent"]["future"] = False
    code, result = task.step("draft-declare-field-change", "--object-handle", source, "--field-handle", field, "--target-handle", target)
    if code == 0:
        code, result = task.step("draft-check")
    assert code == 2, result
    assert not any(uri.endswith(("setReference", "object.set")) for uri, _, _ in task.calls)


def test_structural_proof_cannot_hide_a_dropped_reference_write(tmp_path):
    task = StructuralMasterTask(tmp_path)
    original_reference = deepcopy(task.objects[FIRST]["AudioDevice"])
    tx, shown = prepare(task)
    authorize(task, tx, shown)
    original = task.call
    def call(uri, args=None, options=None):
        if uri.endswith("setReference"):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {}
        return original(uri, args, options)
    task.call = call
    assert task.run("execute", tx)[0] == 0
    code, result = task.run("verify", tx)
    assert code == 2 and result["verified"] is False, result
    assert task.objects[FIRST]["AudioDevice"] == original_reference


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1"])
def test_unpinned_master_descriptor_cannot_create_reference_authority(tmp_path, version):
    task = StructuralMasterTask(tmp_path, version)
    source = task.bind(FIRST)
    code, result = task.step("draft-discover-fields", "--object-handle", source, "--meaning", "AudioDevice")
    assert code == 2, result
    assert not any(uri.endswith(("isPropertyEnabled", "setReference", "object.set")) for uri, _, _ in task.calls)


def test_reference_ancestry_exceeding_existing_graph_bound_has_no_write_authority(tmp_path):
    task = StructuralMasterTask(tmp_path)
    child = task.objects[WORKUNIT]
    root = task.objects[ROOT]
    for index in range(9):
        identity = "{%08d-7777-7777-7777-777777777777}" % index
        child["parent"] = {"id": identity}
        task.objects[identity] = {"id": identity, "name": "Folder" + str(index), "type": "Folder", "classId": 131088,
            "path": root["path"] + "\\" + "\\".join("Folder" + str(i) for i in reversed(range(index, 9))),
            "parent": {"id": ROOT}}
        child = task.objects[identity]
    # Set every path from its actual canonical edge, retaining a valid deep
    # tree: rejection must be the fixed depth boundary, not path corruption.
    cursor = child
    for index in reversed(range(9)):
        row = task.objects["{%08d-7777-7777-7777-777777777777}" % index]
        row["path"] = (root["path"] if index == 8 else cursor["path"]) + "\\" + row["name"]
        cursor = row
    task.objects[WORKUNIT]["path"] = cursor["path"] + "\\Default Work Unit"
    task.objects[FIRST]["path"] = task.objects[WORKUNIT]["path"] + "\\Main Mix"
    source = task.bind(FIRST)
    code, result = task.step("draft-discover-fields", "--object-handle", source, "--meaning", "AudioDevice")
    assert code == 2, result
    assert "depth" in str(result).lower(), result
    assert not any(uri.endswith(("setReference", "object.set")) for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
@pytest.mark.parametrize("enabled", [True, False])
def test_scalar_master_condition_keeps_native_property_enabled_semantics(tmp_path, version, enabled):
    task = StructuralMasterTask(tmp_path, version, "object.setProperty")
    task.enabled = enabled
    task.metadata = {"Volume": {"name": "Volume", "type": "Real64", "restriction": {"type": "range", "min": -200, "max": 12},
        "dependencies": [{"type": "isMasterBus", "value": True, "action": "Show", "context": "Self"}]}}
    source = task.bind(FIRST)
    code, found = task.step("draft-discover-fields", "--object-handle", source, "--meaning", "Volume")
    if not enabled:
        assert code == 2, found
        assert task.enabled_reads
        assert not any(uri.endswith("setProperty") for uri, _, _ in task.calls)
        return
    assert code == 0, found
    candidate, = found["meaning_results"][0]["candidates"]
    assert "applicability" not in candidate
    code, result = task.step("draft-declare-field-change", "--object-handle", source,
        "--field-handle", candidate["handle"], "--business-value", "-3")
    assert code == 0, result
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    authorize(task, tx, shown)
    assert task.run("execute", tx)[0] == 0
    code, verified = task.run("verify", tx)
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[FIRST]["Volume"] == -3
    assert len(task.enabled_reads) >= 3


@pytest.mark.parametrize("stage", ["unexecuted", "executed", "indeterminate", "previously-verified"])
def test_legacy_reference_without_structural_proof_needs_fresh_preview_and_never_replays(tmp_path, stage):
    from wwise_waapi.transactions import TransactionStore, TransactionState
    task = StructuralMasterTask(tmp_path)
    original, _shown = prepare(task)
    store = TransactionStore(tmp_path / "state")
    artifact = deepcopy(store.load_preview(original).artifact)
    artifact["prepared_operation"]["pre_state"]["condition_metadata"].pop("structural_applicability")
    tx = "legacy-master-reference"
    created = store.create_preview(tx, artifact)
    store.submit_for_confirmation(tx)
    store.confirm(tx, artifact_hash=created.artifact_hash)
    if stage != "unexecuted":
        store.begin_execution(tx, expected_authorization=TransactionState.CONFIRMED)
        if stage == "indeterminate":
            store.mark_execution_indeterminate(tx, details={"reason": "historical ambiguous dispatch"})
        else:
            task.objects[FIRST]["AudioDevice"] = {"id": SECOND}
            store.mark_executed_unverified(tx, details={"dispatch_result": {"status": "ok", "result": {}}})
            if stage == "previously-verified":
                store.record_verification(tx, "verified", details={"historical_result": "preserve original verdict"})
                events = store.read_events(tx)
                assert task.run("verify", tx)[0] == 2
                assert store.read_events(tx) == events
            else:
                code, result = task.run("verify", tx)
                assert code == 2 and result["verified"] is False, result
    code, result = task.run("execute", tx)
    assert code == 2, result
    if stage == "unexecuted":
        assert store.load(tx).state is TransactionState.REPREVIEW_REQUIRED
        assert "fresh Preview" in str(result)
    assert not any(uri.endswith(("isPropertyEnabled", "setReference", "setProperty", "object.set")) for uri, _, _ in task.calls)
