"""Copy and move replace one exact reviewed destination subtree once."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_field_interface_closure_gateway import FIRST, SECOND, VERSIONS
from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, ROOT, CHILD


SOURCE_PARENT = "{55555555-5555-5555-5555-555555555555}"
SOURCE_CHILD = "{66666666-6666-6666-6666-666666666666}"
COPIED_ROOT = "{77777777-7777-7777-7777-777777777777}"
COPIED_CHILD = "{88888888-8888-8888-8888-888888888888}"


class ReplaceTask(OwnedGraphTask):
    def __init__(self, path: Path, version: str, operation: str) -> None:
        super().__init__(path, version, operation)
        root_type = "PropertyContainer" if version == "2025.1" else "ActorMixer"
        base = r"\Actor-Mixer Hierarchy\Default Work Unit"
        self.objects = {
            FIRST: {"id": FIRST, "name": "Weather", "type": root_type,
                    "path": base + r"\Sources\Weather", "parent": {"id": SOURCE_PARENT}, "notes": "Source notes"},
            SOURCE_CHILD: {"id": SOURCE_CHILD, "name": "Rain", "type": "Sound",
                           "path": base + r"\Sources\Weather\Rain", "parent": {"id": FIRST}, "notes": "Rain notes"},
            SOURCE_PARENT: {"id": SOURCE_PARENT, "name": "Sources", "type": root_type,
                            "path": base + r"\Sources", "parent": {"id": SECOND}, "notes": "Keep source parent"},
            SECOND: {"id": SECOND, "name": "Destination", "type": root_type,
                     "path": base + r"\Destination", "parent": {"id": SOURCE_PARENT}, "notes": "Keep destination"},
            ROOT: {"id": ROOT, "name": "Weather", "type": root_type,
                   "path": base + r"\Destination\Weather", "parent": {"id": SECOND}, "notes": "Replace old"},
            CHILD: {"id": CHILD, "name": "Old", "type": "Sound",
                    "path": base + r"\Destination\Weather\Old", "parent": {"id": ROOT}, "notes": "Old child"},
        }
        self.operation = operation
        self.failure: str | None = None
        self.metadata = {"Volume": {"name": "Volume", "type": "Real64"},
                         "Target": {"name": "Target", "type": "reference"}}
        for row in self.objects.values():
            row["@Volume"] = -3.0 if row["id"] in {FIRST, SOURCE_CHILD} else -8.0
            row["@Target"] = {"id": FIRST} if row["id"] == SOURCE_CHILD else None

    def declare(self) -> None:
        for role, object_id in (("object", FIRST), ("parent", SECOND)):
            code, bound = self.step("draft-bind-object", "--role", role, "--object-id", object_id)
            assert code == 0, bound
        code, declared = self.step("draft-declare-object-change", "--name-conflict", "replace")
        assert code == 0, declared

    def call(self, uri: str, args: Any = None, options: Any = None) -> Any:
        if uri.endswith("getProjectInfo"):
            return {**super().call(uri, args, options), "platforms": []}
        if uri.endswith("object.getTypes") and self.version == "2021.1":
            return {"return": [*super().call(uri, args, options)["return"],
                               {"classId": 4522000, "name": "Platform", "type": "WObject"}]}
        if uri.endswith("object.get") and args.get("from") == {"ofType": ["Platform"]}:
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args["transform"] == [{"range": [0, 33]}] and options == {"return": ["id", "name"]}
            return {"return": deepcopy(getattr(self, "platforms", []))[:33]}
        if uri.endswith(("object.copy", "object.move")):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args["object"] == FIRST and args["parent"] == SECOND
            assert args["onNameConflict"] == "replace"
            is_copy = uri.endswith("object.copy")
            old_source = deepcopy(self.objects[FIRST])
            old_child = deepcopy(self.objects[SOURCE_CHILD])
            for object_id in (ROOT, CHILD):
                if self.failure != "retained-old-child" or object_id != CHILD:
                    self.objects.pop(object_id, None)
            root_id, child_id = (COPIED_ROOT, COPIED_CHILD) if is_copy else (FIRST, SOURCE_CHILD)
            self.objects[root_id] = {**old_source, "id": root_id, "path": self.objects[SECOND]["path"] + r"\Weather", "parent": {"id": SECOND}}
            self.objects[child_id] = {**old_child, "id": child_id, "path": self.objects[root_id]["path"] + r"\Rain", "parent": {"id": root_id}}
            if is_copy:
                self.objects[child_id]["@Target"] = {"id": root_id}
            if self.failure == "changed-copy-source" and is_copy:
                self.objects[SOURCE_CHILD]["notes"] = "Wrongly altered source"
            if self.failure == "missing-new-child":
                del self.objects[child_id]
            if self.failure == "wrong-value":
                self.objects[child_id]["@Volume"] = -12.0
            if self.failure == "wrong-reference":
                self.objects[child_id]["@Target"] = {"id": SECOND}
            return {"id": root_id, "name": "Weather"}
        return super().call(uri, args, options)


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("operation", ("object.copy", "object.move"))
def test_replace_lifecycle_seals_exact_deleted_tree_and_verifies_source_distinction(
    tmp_path: Path, version: str, operation: str,
) -> None:
    task = ReplaceTask(tmp_path, version, operation)
    task.declare()
    tx, shown = task.preview()
    prepared = shown["artifact"]["prepared_operation"]
    assert prepared["dispatch"]["args"]["onNameConflict"] == "replace"
    assert {row["id"] for row in prepared["verification_plan"]["replaced_subtree_rows"]} == {ROOT, CHILD}
    code, verified = task.finish(tx, shown)
    assert code == 2 and verified.get("verified") is not True, verified
    assert verified["verification"]["business_state_verified"] is False
    assert verified["verification"]["status"] == "indeterminate"
    assert all(row["passed"] for row in verified["verification"]["assertions"])
    assert ROOT not in task.objects and CHILD not in task.objects
    if operation == "object.copy":
        assert task.objects[FIRST]["path"].endswith(r"\Sources\Weather")
        assert task.objects[SOURCE_CHILD]["notes"] == "Rain notes"
        assert task.objects[COPIED_CHILD]["parent"] == {"id": COPIED_ROOT}
    else:
        assert task.objects[FIRST]["path"].endswith(r"\Destination\Weather")
        assert task.objects[SOURCE_CHILD]["parent"] == {"id": FIRST}
    assert len([uri for uri, _, _ in task.calls if uri.endswith(("object.copy", "object.move"))]) == 1


@pytest.mark.parametrize(("operation", "failure"), [
    (operation, failure)
    for operation in ("object.copy", "object.move")
    for failure in ("retained-old-child", "missing-new-child", "wrong-value", "wrong-reference", "changed-copy-source")
    if operation == "object.copy" or failure != "changed-copy-source"
])
def test_replace_lifecycle_rejects_partial_effects_and_preservation_failures(
    tmp_path: Path, operation: str, failure: str,
) -> None:
    task = ReplaceTask(tmp_path, "2025.1", operation)
    task.declare()
    tx, shown = task.preview()
    task.failure = failure
    code, verified = task.finish(tx, shown)
    assert code == 2 and verified.get("verified") is not True, verified
    code, replay = task.run("execute", tx)
    assert code == 2, replay
    assert len([uri for uri, _, _ in task.calls if uri.endswith(("object.copy", "object.move"))]) == 1


@pytest.mark.parametrize("scope", ("source", "replacement"))
@pytest.mark.parametrize("change", ("notes", "value", "topology"))
def test_replace_revalidates_complete_source_and_destination_before_dispatch(
    tmp_path: Path, scope: str, change: str,
) -> None:
    task = ReplaceTask(tmp_path, "2025.1", "object.copy")
    task.declare()
    tx, shown = task.preview()
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    changed_id = SOURCE_CHILD if scope == "source" else CHILD
    if change == "topology":
        del task.objects[changed_id]
    else:
        task.objects[changed_id]["notes" if change == "notes" else "@Volume"] = "changed" if change == "notes" else -100.0
    code, rejected = task.run("execute", tx)
    assert code == 2, rejected
    assert not any(uri.endswith(("object.copy", "object.move")) for uri, _, _ in task.calls)


@pytest.mark.parametrize("operation", ("object.copy", "object.move"))
@pytest.mark.parametrize("collision", ("absent", "case-insensitive"))
def test_replace_keeps_native_absent_and_case_insensitive_collision_choices(
    tmp_path: Path, operation: str, collision: str,
) -> None:
    task = ReplaceTask(tmp_path, "2025.1", operation)
    if collision == "absent":
        del task.objects[ROOT], task.objects[CHILD]
    else:
        task.objects[ROOT]["name"] = "WEATHER"
        task.objects[ROOT]["path"] = task.objects[ROOT]["path"].replace("Weather", "WEATHER")
        task.objects[CHILD]["path"] = task.objects[CHILD]["path"].replace("Weather", "WEATHER")
    task.declare()
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 2 and verified["verification"]["status"] == "indeterminate", verified
    assert all(row["passed"] for row in verified["verification"]["assertions"])


def test_copy_snapshot_preserves_guid_text_properties_without_reference_rebinding(tmp_path: Path) -> None:
    task = ReplaceTask(tmp_path, "2025.1", "object.copy")
    task.metadata["UserMarker"] = {"name": "UserMarker", "type": "string"}
    for row in task.objects.values():
        row["@UserMarker"] = FIRST
    task.declare()
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 2 and verified["verification"]["status"] == "indeterminate", verified
    assert all(row["passed"] for row in verified["verification"]["assertions"])
    assert task.objects[COPIED_ROOT]["@UserMarker"] == FIRST
    assert task.objects[COPIED_CHILD]["@Target"] == {"id": COPIED_ROOT}


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("operation", ("object.copy", "object.move"))
def test_replace_snapshot_binds_omitted_metadata_identity_to_exact_scoped_names(
    tmp_path: Path, version: str, operation: str,
) -> None:
    task = ReplaceTask(tmp_path, version, operation)
    task.metadata["Volume"] = {"type": "Real64"}
    task.metadata["Target"] = {"restriction": {"type": "reference"}}
    task.declare()
    tx, shown = task.preview()
    snapshot = shown["artifact"]["prepared_operation"]["pre_state"]["copy_move_collision_guard"]["source_snapshot"][0]
    evidence = snapshot["field_metadata"]["Target"]
    assert evidence["raw"] == {"restriction": {"type": "reference"}}
    assert evidence["name"] is None and evidence["type"] is None
    assert evidence["field_binding"] == {"token": "Target", "source": "exact_scoped_getPropertyAndReferenceNames"}
    assert evidence["scope"] == {"object": FIRST}
    assert evidence["available_names"] == ["Target", "Volume"]
    code, verified = task.finish(tx, shown)
    assert code == 2 and verified["verification"]["status"] == "indeterminate", verified
    assert all(row["passed"] for row in verified["verification"]["assertions"])


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("metadata", (
    {"name": "AnotherField", "type": "Real64"},
    {"type": "UnrecognizedNativeScalar"},
    {},
))
def test_replace_snapshot_rejects_wrong_identity_or_uncertified_scalar_type(
    tmp_path: Path, version: str, metadata: dict[str, Any],
) -> None:
    task = ReplaceTask(tmp_path, version, "object.copy")
    task.metadata["Volume"] = metadata
    task.declare()
    code, rejected = task.step("draft-check")
    assert code == 2, rejected
    assert not any(uri.endswith(("object.copy", "object.move")) for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", VERSIONS)
def test_replace_guard_retains_raw_metadata_omission_provenance(
    tmp_path: Path, version: str,
) -> None:
    task = ReplaceTask(tmp_path, version, "object.copy")
    task.metadata["Target"] = {"restriction": {"type": "reference"}}
    task.declare()
    tx, shown = task.preview()
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    # Same effective field type/value, but a changed native observation must re-preview.
    task.metadata["Target"] = {"name": "Target", "type": "Reference", "restriction": {"type": "reference"}}
    code, rejected = task.run("execute", tx)
    assert code == 2, rejected
    assert not any(uri.endswith(("object.copy", "object.move")) for uri, _, _ in task.calls)


PLATFORMS = [
    {"id": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}", "name": "Desktop"},
    {"id": "{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD}", "name": "Mobile"},
]


class PlatformReplaceTask(ReplaceTask):
    def __init__(self, path: Path, version: str, operation: str) -> None:
        super().__init__(path, version, operation)
        self.platforms = deepcopy(PLATFORMS)
        self.metadata["Volume"]["supports"] = {"unlink": True}
        self.metadata["Target"]["supports"] = {"unlink": False}
        self.platform_values = {row["id"]: {platform["id"]: -10.0 - offset
            for offset, platform in enumerate(PLATFORMS)} for row in self.objects.values()}
        self.platform_links = {row["id"]: {platform["id"]: offset == 0
            for offset, platform in enumerate(PLATFORMS)} for row in self.objects.values()}

    def call(self, uri: str, args: Any = None, options: Any = None) -> Any:
        if uri.endswith("getProjectInfo"):
            result = super().call(uri, args, options)
            return {**result, "platforms": deepcopy(self.platforms)}
        if uri.endswith("object.isLinked"):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert self.version in VERSIONS[2:] and args["property"] == "Volume"
            return {"linked": self.platform_links[args["object"]][args["platform"]]}
        result = super().call(uri, args, options)
        if uri.endswith(("object.copy", "object.move")):
            root_id, child_id = (COPIED_ROOT, COPIED_CHILD) if self.operation == "object.copy" else (FIRST, SOURCE_CHILD)
            for old_id, new_id in ((FIRST, root_id), (SOURCE_CHILD, child_id)):
                self.platform_values[new_id] = deepcopy(self.platform_values[old_id])
                self.platform_links[new_id] = deepcopy(self.platform_links[old_id])
            if self.failure == "wrong-platform-value":
                self.platform_values[child_id][PLATFORMS[1]["id"]] = -100.0
            elif self.failure == "wrong-platform-link":
                self.platform_links[child_id][PLATFORMS[1]["id"]] = True
            elif self.failure == "default-number-bool":
                self.objects[child_id]["@Volume"] = True
            elif self.failure == "platform-number-bool":
                self.platform_values[child_id][PLATFORMS[1]["id"]] = True
            elif self.failure == "default-number-float":
                self.objects[child_id]["@Volume"] = 1.0
            elif self.failure == "platform-number-float":
                self.platform_values[child_id][PLATFORMS[1]["id"]] = 1.0
        if uri.endswith("object.get") and options.get("platform") is not None:
            for row in result["return"]:
                row["@Volume"] = self.platform_values[row["id"]][options["platform"]]
        return result


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("operation", ("object.copy", "object.move"))
def test_replace_preserves_every_project_platform_field_view_and_available_link_flags(
    tmp_path: Path, version: str, operation: str,
) -> None:
    task = PlatformReplaceTask(tmp_path, version, operation)
    task.declare()
    tx, shown = task.preview()
    prepared = shown["artifact"]["prepared_operation"]
    observation = prepared["verification_plan"]["source_subtree_rows"][0]["platform_observation"]
    assert observation["platforms"] == PLATFORMS
    assert observation["values"][PLATFORMS[1]["id"]]["Volume"] == -11.0
    assert observation["link_flags_complete"] is (version in VERSIONS[2:])
    scope = prepared["verification_plan"]["verification_scope"]
    assert "unlinked_platform_views" not in scope["unobserved"]
    assert "owned_lists_and_plugin_state" in scope["unobserved"]
    code, verified = task.finish(tx, shown)
    assert code == 2 and verified["verification"]["status"] == "indeterminate", verified
    assert all(assertion["passed"] for assertion in verified["verification"]["assertions"])


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("operation", ("object.copy", "object.move"))
def test_replace_detects_a_changed_nondefault_platform_value(tmp_path: Path, version: str, operation: str) -> None:
    task = PlatformReplaceTask(tmp_path, version, operation)
    task.declare()
    tx, shown = task.preview()
    task.failure = "wrong-platform-value"
    code, verified = task.finish(tx, shown)
    assert code == 2 and verified["verification"]["status"] == "verification_failed", verified
    assert any(not assertion["passed"] for assertion in verified["verification"]["assertions"])


@pytest.mark.parametrize("version", VERSIONS[2:])
@pytest.mark.parametrize("operation", ("object.copy", "object.move"))
def test_replace_detects_changed_platform_link_flags(tmp_path: Path, version: str, operation: str) -> None:
    task = PlatformReplaceTask(tmp_path, version, operation)
    task.declare()
    tx, shown = task.preview()
    task.failure = "wrong-platform-link"
    code, verified = task.finish(tx, shown)
    assert code == 2 and verified["verification"]["status"] == "verification_failed", verified
    assert any(not assertion["passed"] for assertion in verified["verification"]["assertions"])


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("scope", ("source", "replacement", "inventory"))
def test_replace_revalidates_platform_views_and_inventory_before_dispatch(
    tmp_path: Path, version: str, scope: str,
) -> None:
    task = PlatformReplaceTask(tmp_path, version, "object.copy")
    task.declare()
    tx, shown = task.preview()
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    if scope == "inventory":
        task.platforms[1]["name"] = "Renamed platform"
    else:
        task.platform_values[SOURCE_CHILD if scope == "source" else CHILD][PLATFORMS[1]["id"]] = -99.0
    code, rejected = task.run("execute", tx)
    assert code == 2, rejected
    assert not any(uri.endswith(("object.copy", "object.move")) for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("malformed", ("duplicate", "oversized", "missing-name"))
def test_replace_rejects_incomplete_or_ambiguous_platform_inventory_without_write(
    tmp_path: Path, version: str, malformed: str,
) -> None:
    task = PlatformReplaceTask(tmp_path, version, "object.copy")
    if malformed == "duplicate":
        task.platforms.append(deepcopy(task.platforms[0]))
    elif malformed == "oversized":
        task.platforms = [deepcopy(task.platforms[0]) for _ in range(33)]
    else:
        del task.platforms[0]["name"]
    task.declare()
    code, rejected = task.step("draft-check")
    assert code == 2, rejected
    assert not any(uri.endswith(("object.copy", "object.move")) for uri, _, _ in task.calls)


def test_2021_platform_discovery_is_a_bounded_fixed_live_type_read(tmp_path: Path) -> None:
    task = PlatformReplaceTask(tmp_path, "2021.1", "object.copy")
    task.declare()
    _, shown = task.preview()
    observation = shown["artifact"]["prepared_operation"]["verification_plan"]["source_subtree_rows"][0]["platform_observation"]
    assert observation["discovery"] == {"source": "live_getTypes_and_fixed_ofType",
        "class": {"classId": 4522000, "name": "Platform", "type": "WObject"}}
    assert not any(uri.endswith("getProjectInfo") or uri.endswith("object.isLinked") for uri, _, _ in task.calls)
    queries = [(args, options) for uri, args, options in task.calls
               if uri.endswith("object.get") and args.get("from") == {"ofType": ["Platform"]}]
    assert queries and all(args == {"from": {"ofType": ["Platform"]}, "transform": [{"range": [0, 33]}]}
                           and options == {"return": ["id", "name"]} for args, options in queries)


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("operation", ("object.copy", "object.move"))
@pytest.mark.parametrize("view", ("default", "platform"))
def test_replace_does_not_equate_numeric_one_with_boolean_readback(
    tmp_path: Path, version: str, operation: str, view: str,
) -> None:
    task = PlatformReplaceTask(tmp_path, version, operation)
    task.objects[SOURCE_CHILD]["@Volume"] = 1
    task.platform_values[SOURCE_CHILD][PLATFORMS[1]["id"]] = 1
    task.declare()
    tx, shown = task.preview()
    task.failure = view + "-number-bool"
    code, verified = task.finish(tx, shown)
    assert code == 2 and verified["verification"]["status"] == "verification_failed", verified
    assert any(not assertion["passed"] for assertion in verified["verification"]["assertions"])


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("view", ("default", "platform"))
def test_replace_prewrite_guard_rejects_numeric_one_becoming_boolean(
    tmp_path: Path, version: str, view: str,
) -> None:
    task = PlatformReplaceTask(tmp_path, version, "object.copy")
    task.objects[SOURCE_CHILD]["@Volume"] = 1
    task.platform_values[SOURCE_CHILD][PLATFORMS[1]["id"]] = 1
    task.declare()
    tx, shown = task.preview()
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    if view == "default":
        task.objects[SOURCE_CHILD]["@Volume"] = True
    else:
        task.platform_values[SOURCE_CHILD][PLATFORMS[1]["id"]] = True
    code, rejected = task.run("execute", tx)
    assert code == 2, rejected
    assert not any(uri.endswith(("object.copy", "object.move")) for uri, _, _ in task.calls)


@pytest.mark.parametrize("metadata_type", ("Real64", "Int32"))
@pytest.mark.parametrize("view", ("default", "platform"))
def test_replace_numeric_equivalence_requires_the_exact_live_scalar_type(
    tmp_path: Path, metadata_type: str, view: str,
) -> None:
    task = PlatformReplaceTask(tmp_path, "2025.1", "object.copy")
    task.metadata["Volume"]["type"] = metadata_type
    for row in task.objects.values():
        row["@Volume"] = 1
    for values in task.platform_values.values():
        values.update({platform["id"]: 1 for platform in PLATFORMS})
    task.declare()
    tx, shown = task.preview()
    task.failure = view + "-number-float"
    code, verified = task.finish(tx, shown)
    expected_status = "indeterminate" if metadata_type == "Real64" else "verification_failed"
    assert code == 2 and verified["verification"]["status"] == expected_status, verified
    assert all(row["passed"] for row in verified["verification"]["assertions"]) is (metadata_type == "Real64")
