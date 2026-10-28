"""Saved WorkUnit/Query construction uses the existing public Draft transaction."""
import json

import pytest

from tests.unit.test_field_interface_closure_gateway import FIRST, SECOND, VERSIONS
from tests.unit.test_object_graph_business_gateway import gateway
from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask


class ConstructorTask(OwnedGraphTask):
    def __init__(self, path, version, operation="object.create", hierarchy="Queries"):
        super().__init__(path, version, operation)
        self.types = [{"classId": 1638416, "name": "WorkUnit", "type": "WObject"},
            {"classId": 2097168, "name": "Query", "type": "WObject"},
            {"classId": 2162704, "name": "SearchCriteria", "type": "WObject"},
            {"classId": 131088, "name": "Folder", "type": "WObject"}]
        self.creation_classes.update({row["name"]: row["classId"] for row in self.types})
        self.objects = {SECOND: {"id": SECOND, "name": "Default Work Unit", "type": "WorkUnit",
            "classId": 1638416, "path": "\\" + hierarchy + "\\Default Work Unit", "parent": None,
            "workunitType": "rootFile", "filePath": str(self.project_file.parent / hierarchy / "Default Work Unit.wwu"), "notes": "Keep owner"}}
        self.config = path / "config.json"

    def _create(self, node, parent, *, owned=False):
        if node["type"] == "SearchCriteria":
            # The retained factory WWU's display name is independent of the
            # SDK-prescribed native constructor name sent by the Gateway.
            assert node["name"] == "{43981FC3-FF8B-4EE7-87FA-1C2A4BDD04C8}"
            node = {**node, "name": "SourceChannels"}
        return super()._create(node, parent, owned=owned)

    def discover_kind(self, meaning):
        code, value = self.step("draft-discover-types", "--role", "object", "--meaning", meaning)
        assert code == 0, value
        assert len(value["type_candidates"]) == 1, value
        return value["type_candidates"][0]["handle"]

    def declare(self, kind, name, parent=None):
        owner = self.bind(SECOND) if parent is None else parent
        code, value = self.step("draft-declare-new", "--declaration-id", "constructor",
            "--parent-handle", owner, "--name", name, "--kind", self.discover_kind(kind))
        assert code == 0, value
        return value["draft"]["declared_object"]["result_handle"]


@pytest.mark.parametrize("version", VERSIONS)
def test_workunit_creation_discloses_saved_file_and_irreversible_history_effects(tmp_path, version):
    task = ConstructorTask(tmp_path, version, hierarchy="Events")
    task.declare("WorkUnit", "Weather")
    tx, shown = task.preview()
    prepared = shown["artifact"]["prepared_operation"]
    boundary = prepared["pre_state"]["saved_object_constructors"]
    assert boundary["workunit_effects"] == ["undo_redo_history_cleared", "clipboard_cleared", "corresponding_WWU_saved_in_active_project"]
    assert boundary["verification"]["unobserved"] == ["history_and_clipboard_contents", "WWU_file_bytes_and_save_completeness"]
    assert any("clipboard" in warning and "WWU" in warning for warning in prepared["warnings"])
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is False, verified
    assert verified["verification"]["verification_scope"]["unobserved"] == boundary["verification"]["unobserved"]
    code, repeated = task.run("execute", tx)
    assert code == 2, repeated
    assert len([call for call in task.calls if call[0].endswith("object.create")]) == 1


@pytest.mark.parametrize("version", VERSIONS)
def test_saved_query_constructor_has_exact_version_gate(tmp_path, version):
    task = ConstructorTask(tmp_path, version)
    task.declare("Query", "Weather")
    code, checked = task.step("draft-check")
    if version in VERSIONS[:2]:
        assert code == 2 and "QUERY_CONSTRUCTOR_UNAVAILABLE" in json.dumps(checked), checked
        assert not any(uri.endswith("object.create") for uri, _, _ in task.calls)
        return
    assert code == 0, checked
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, verified


@pytest.mark.parametrize("version,operation", [("2023.1", "object.create"), ("2024.1", "object.set"), ("2025.1", "object.create")])
def test_query_criterion_choice_owns_native_name_and_retains_live_field_validation(tmp_path, version, operation):
    task = ConstructorTask(tmp_path, version, operation)
    task.objects[FIRST] = {"id": FIRST, "name": "Weather", "type": "Query", "classId": 2097168,
        "path": r"\Queries\Default Work Unit\Weather", "parent": {"id": SECOND}, "notes": "Keep query"}
    parent = task.bind(FIRST)
    kind = task.discover_kind("SearchCriteria")
    task.metadata = {"SourceChannelsOthersCount": {"name": "SourceChannelsOthersCount", "type": "int32",
        "restriction": {"type": "range", "min": 0, "max": 100}}}
    code, selected = task.step("draft-discover-fields", "--type-handle", kind, "--meaning", "SourceChannelsOthersCount")
    assert code == 0, selected
    field = selected["meaning_results"][0]["candidates"][0]["handle"]
    code, value = task.step("draft-declare-new", "--declaration-id", "channels", "--parent-handle", parent,
        "--name", "SourceChannels", "--kind", kind, "--field-value", field, "2")
    assert code == 0, value
    tx, shown = task.preview()
    prepared = shown["artifact"]["prepared_operation"]
    args = prepared["dispatch"]["args"]
    node = args if operation == "object.create" else args["objects"][0]["children"][0]
    assert node["name"] == "{43981FC3-FF8B-4EE7-87FA-1C2A4BDD04C8}" and node["@SourceChannelsOthersCount"] == 2
    assert any("Query matches" in text for text in prepared["warnings"])
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is False, verified
    assert verified["verification"]["verification_scope"]["unobserved"] == ["SearchOperationID", "saved_Query_matches"]


@pytest.mark.parametrize("fault", ["caller-guid", "wrong-owner", "wrong-class"])
def test_criterion_rejects_unowned_native_name_or_invalid_query_owner(tmp_path, fault):
    task = ConstructorTask(tmp_path, "2025.1")
    if fault != "wrong-owner":
        task.objects[SECOND].update(type="Query", classId=2097168 if fault != "wrong-class" else 1)
    choice = "{43981FC3-FF8B-4EE7-87FA-1C2A4BDD04C8}" if fault == "caller-guid" else "SourceChannels"
    if fault == "wrong-owner":
        parent = task.bind(SECOND)
        code, checked = task.step("draft-declare-new", "--declaration-id", "criterion", "--parent-handle", parent,
            "--name", choice, "--kind", task.discover_kind("SearchCriteria"))
    else:
        task.declare("SearchCriteria", choice)
        code, checked = task.step("draft-check")
    assert code == 2, checked
    expected = {"caller-guid": "QUERY_CRITERION_CHOICE_REQUIRED", "wrong-owner": "INVALID_CREATE_PARENT_TYPE_FOR_CHILD", "wrong-class": "SAVED_CONSTRUCTOR_PARENT_INVALID"}[fault]
    assert expected in json.dumps(checked), checked
    assert not any(uri.endswith(("object.create", "object.set")) for uri, _, _ in task.calls)


@pytest.mark.parametrize("fault", ["replace", "wrong-owner", "external-file", "source-drift", "config-drift"])
def test_workunit_constructor_rejects_unsupported_mode_scope_or_stale_binding(tmp_path, monkeypatch, fault):
    task = ConstructorTask(tmp_path, "2025.1", hierarchy="Events")
    if fault == "wrong-owner":
        task.objects[SECOND]["type"] = "Query"
    if fault == "external-file":
        task.objects[SECOND]["filePath"] = str(tmp_path / "External.wwu")
    if fault == "wrong-owner":
        parent = task.bind(SECOND)
        code, rejected = task.step("draft-declare-new", "--declaration-id", "workunit", "--parent-handle", parent,
            "--name", "Weather", "--kind", task.discover_kind("WorkUnit"))
        assert code == 2 and "INVALID_CREATE_CHILD_TYPE_FOR_PARENT" in json.dumps(rejected), rejected
        assert not any(uri.endswith(("object.create", "object.set")) for uri, _, _ in task.calls)
        return
    task.declare("WorkUnit", "Weather")
    if fault == "replace":
        owner = task.bind(SECOND)
        code, configured = task.step("draft-business-configure", "--name-conflict", "replace", "--replace-owner-handle", owner)
        assert code == 0, configured
    if fault in {"replace", "wrong-owner", "external-file"}:
        code, checked = task.step("draft-check")
        assert code == 2, checked
    else:
        tx, shown = task.preview()
        code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
        assert code == 0, confirmed
        if fault == "config-drift":
            config = json.loads(task.config.read_text()); config["waapi_port"] += 1
            task.config.write_text(json.dumps(config))
        else:
            from wwise_waapi import saved_object_construction
            bad = tmp_path / "changed-source.json"
            data = json.loads(saved_object_construction.SOURCE.read_text())
            data["versions"]["2025.1"]["sdk_sha256"] = "0" * 64
            bad.write_text(json.dumps(data))
            monkeypatch.setattr(saved_object_construction, "SOURCE", bad)
        code, rejected = task.run("execute", tx)
        assert code == 2, rejected
    assert not any(uri.endswith(("object.create", "object.set")) for uri, _, _ in task.calls)


def test_workunit_batch_constructor_discloses_same_save_boundary(tmp_path):
    task = ConstructorTask(tmp_path, "2025.1", "object.set", hierarchy="Events")
    task.declare("WorkUnit", "Weather")
    tx, shown = task.preview()
    assert shown["artifact"]["prepared_operation"]["pre_state"]["saved_object_constructor_batches"][0]["workunit_effects"]
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is False, verified


@pytest.mark.parametrize("policy", ["read_only", "ask_before_changes", "allow_changes"])
def test_saved_constructor_keeps_modification_policy_authority(tmp_path, policy):
    task = ConstructorTask(tmp_path, "2025.1", hierarchy="Events")
    assert task.run("config-set", "--project-modification-policy", policy)[0] == 0
    task.declare("WorkUnit", "Weather")
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert not any(uri.endswith("object.create") for uri, _, _ in task.calls)
    if policy == "read_only":
        assert code == 2 and "read_only" in json.dumps(preview), preview
        return
    assert code == 0, preview
    assert preview["state"] == ("policy_authorized" if policy == "allow_changes" else "awaiting_confirmation")
    code, executed = task.run("execute", preview["transaction_id"])
    assert (code == 0) == (policy == "allow_changes"), executed


def test_workunit_physical_hierarchy_root_uses_same_project_file_boundary(tmp_path):
    task = ConstructorTask(tmp_path, "2025.1", hierarchy="Events")
    task.objects[SECOND].update(name="Events", path=r"\Events", workunitType="folder",
        filePath=str(task.project_file.parent / "Events"))
    task.declare("WorkUnit", "Weather")
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is False, verified


def test_saved_constructor_sources_and_criterion_choices_match_exact_version_artifacts():
    import base64
    import gzip
    import hashlib
    import html
    import re
    import xml.etree.ElementTree as ET
    from pathlib import Path
    from wwise_waapi import saved_object_construction
    root = Path(__file__).resolve().parents[2]
    archived = json.loads(gzip.decompress((root / "tests/fixtures/metadata-conditions/saved-constructor-sdk-sources.json.gz").read_bytes()))
    packaged = json.loads(saved_object_construction.SOURCE.read_text())
    for version in VERSIONS:
        proof = saved_object_construction.authority(version, "WorkUnit")
        sdk = next(row for row in archived["sources"] if row["build"] == proof["build"])
        source = base64.b64decode(sdk["bytes_base64"])
        assert hashlib.sha256(source).hexdigest() == proof["sdk_sha256"]
        assert b"requires the undo/redo history and the clipboard to be cleared" in source
        text = html.unescape(re.sub("<[^>]+>", "", source.decode("utf-8")))
        assert "corresponding WWU file in the project" in text and "The 'replace' mode is not supported" in text
        lane = packaged["versions"][version]
        unavailable = b"It is not possible to create Query objects" in source
        assert lane["query_constructible"] is (not unavailable)
        native_types = json.loads((root / f"skills/waapi-skill/resources/metadata/{version}/object-types.json").read_text())["types"]
        for kind, key in (("WorkUnit", "workunit_class_id"), ("Query", "query_class_id"), ("SearchCriteria", "criterion_class_id")):
            assert [row["classId"] for row in native_types if row["name"] == kind] == [packaged[key]]
        if unavailable:
            assert lane["criteria"] == {}
        else:
            factory = (root / lane["factory_member"]).read_bytes()
            assert hashlib.sha256(factory).hexdigest() == lane["factory_sha256"]
            choices = {row.get("Name"): row.get("SearchOperationID") for row in ET.fromstring(factory).iter("SearchCriteria")}
            assert lane["criteria"] == choices
        code, schema = gateway.execute_gateway(
            ["--version", version, "operation-schema", "object.create"])
        assert code == 0, schema
        contract = schema["business_adapter"]["creation_boundaries"]["Query"]
        assert contract["status"] == ("unavailable_in_matching_SDK" if unavailable else "supported")
        assert contract["criteria"]["choices"] == list(lane["criteria"])
        assert "query_matches_unobserved" in contract["criteria"]["verification"]


def test_workunit_parent_directory_drift_cannot_redirect_implicit_save(tmp_path):
    task = ConstructorTask(tmp_path, "2025.1", hierarchy="Events")
    directory = task.project_file.parent / "Events"
    directory.mkdir()
    task.declare("WorkUnit", "Weather")
    tx, shown = task.preview()
    outside = tmp_path / "outside"
    outside.mkdir()
    directory.rename(task.project_file.parent / "OldEvents")
    directory.symlink_to(outside, target_is_directory=True)
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    code, rejected = task.run("execute", tx)
    assert code == 2, rejected
    assert not any(uri.endswith("object.create") for uri, _, _ in task.calls)


def test_workunit_history_clear_cannot_enter_an_undo_group(tmp_path):
    task = ConstructorTask(tmp_path, "2025.1", hierarchy="Events")
    code, parent = task.run("draft-start", "waapi.undoGroup")
    assert code == 0, parent
    parent_id, parent_authority = parent["draft"]["draft_id"], parent["task_authority"]
    code, child = task.run("draft-start-undo-child", parent_id, "--task-authority", parent_authority,
        "--expected-revision", str(parent["draft"]["revision"]), "--operation", "object.create")
    assert code == 0, child
    task.draft, task.authority, task.revision = child["draft"]["draft_id"], child["task_authority"], child["draft"]["revision"]
    task.declare("WorkUnit", "Weather")
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, inspected = task.run("draft-inspect", parent_id, "--task-authority", parent_authority)
    assert code == 0, inspected
    code, declared = task.run("draft-declare-undo-plan", parent_id, "--task-authority", parent_authority,
        "--expected-revision", str(inspected["draft"]["revision"]), "--display-name", "WorkUnit group",
        "--child-draft", task.draft, task.authority)
    assert code == 0, declared
    code, rejected = task.run("draft-check", parent_id, "--task-authority", parent_authority,
        "--expected-revision", str(declared["draft"]["revision"]))
    assert code == 2 and "WORKUNIT_UNDO_GROUP_UNSUPPORTED" in json.dumps(rejected), rejected
    assert not any(uri.endswith(("object.create", "undo.beginGroup")) for uri, _, _ in task.calls)


def test_workunit_name_cannot_become_a_filesystem_path(tmp_path):
    task = ConstructorTask(tmp_path, "2025.1", hierarchy="Events")
    parent = task.bind(SECOND)
    code, value = task.step("draft-declare-new", "--declaration-id", "unsafe", "--parent-handle", parent,
        "--name", "../outside", "--kind", task.discover_kind("WorkUnit"))
    if code == 0:
        code, value = task.step("draft-check")
    assert code == 2, value
    assert not any(uri.endswith("object.create") for uri, _, _ in task.calls)
