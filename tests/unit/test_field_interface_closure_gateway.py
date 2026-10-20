"""Public field acquisition and declaration invariants, without a live host."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_object_graph_business_gateway import gateway
from wwise_waapi.operation_drafts import OperationDraftStore


VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
PROJECT = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
FIRST = "{11111111-1111-1111-1111-111111111111}"
SECOND = "{22222222-2222-2222-2222-222222222222}"


class FieldTask:
    def __init__(self, path: Path, version: str, operation: str) -> None:
        self.path, self.version = path, version
        self.calls: list[tuple[str, Any, Any]] = []
        self.metadata = {
            "FadeTime": {
                "name": "FadeTime", "type": "Real64",
                "display": {"name": "Fade Time"},
                "restriction": {"type": "range", "min": 0, "max": 60},
            },
        }
        self.objects = {
            value: {"id": value, "name": "", "type": "Action", "classId": 1,
                    "path": f"\\Events\\Default Work Unit\\Event{index}\\[Play]"}
            for index, value in enumerate((FIRST, SECOND))
        }
        self.types = [{"classId": 1, "name": "Action", "type": "Action"},
                      {"classId": 2, "name": "Sound", "type": "Sound"}]
        config = path / "config.json"
        config.write_text(json.dumps({"wwise_version": version, "waapi_port": 31337, "waapi_host": "127.0.0.1",
                                      "project_modification_policy": "ask_before_changes"}))
        self.env = {"WAAPI_SKILL_CONFIG_PATH": str(config)}
        self.project_file = path / "project" / "Fixture.wproj"
        self.project_file.parent.mkdir()
        self.project_file.write_text("<Project />")
        code, payload = self.run("draft-start", operation)
        assert code == 0, payload
        self.draft = payload["draft"]["draft_id"]
        self.authority = payload["task_authority"]
        self.revision = payload["draft"]["revision"]

    def call(self, uri: str, args: Any = None, options: Any = None) -> Any:
        self.calls.append((uri, args, options))
        if uri.endswith("getInfo"):
            return {"displayName": "Wwise", "isCommandLine": True,
                    "sessionId": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
                    "processId": 42, "processPath": "/fixtures/WwiseConsole",
                    "apiVersion": 1, "platform": "macosx", "configuration": "release",
                    "version": {"year": int(self.version[:4]), "major": 1,
                                "minor": 0, "build": 1,
                                "displayName": self.version + ".0.1"}}
        if uri.endswith("getProjectInfo"):
            return {"id": PROJECT, "name": "Fixture", "path": str(self.project_file)}
        if uri.endswith("object.get"):
            if args.get("waql") == "from type Project take 1":
                return {"return": self.project_rows([{"id": PROJECT, "name": "Fixture", "type": "Project",
                                    "path": "\\", "filePath": str(self.project_file)}], options)}
            return {"return": self.project_rows(
                [self.objects[value] for value in args["from"]["id"] if value in self.objects], options)}
        if uri.endswith("getPropertyAndReferenceNames"):
            return {"return": list(self.metadata)}
        if uri.endswith("getPropertyInfo"):
            return self.metadata[args["property"]]
        if uri.endswith("getTypes"):
            return {"return": deepcopy(self.types)}
        raise AssertionError((uri, args, options))

    @staticmethod
    def project_rows(rows, options):
        fields = options["return"]
        return [{key: deepcopy(row[key] if key in row else row["@" + key])
                 for key in fields if key in row or "@" + key in row} for row in rows]

    def set_object_type(self, object_id, name, class_id):
        """Explicitly model a native type change, including its independent catalog."""
        existing = [row for row in self.types if row["name"] == name]
        if existing:
            assert len(existing) == 1 and existing[0]["classId"] == class_id
        else:
            self.types.append({"classId": class_id, "name": name, "type": "WObject"})
        self.objects[object_id].update(type=name, classId=class_id)

    def disconnect(self) -> None:
        pass

    def run(self, *argv: str) -> tuple[int, dict[str, Any]]:
        return gateway.execute_gateway(
            ["--state-dir", str(self.path / "state"), *argv], env=self.env,
            client_factory=lambda _url: self,
        )

    def step(self, command: str, *argv: str) -> tuple[int, dict[str, Any]]:
        code, payload = self.run(command, self.draft, "--task-authority", self.authority,
                                 "--expected-revision", str(self.revision), *argv)
        if code == 0 and "draft" in payload:
            self.revision = payload["draft"]["revision"]
        return code, payload

    def bind(self, object_id: str) -> str:
        code, payload = self.step("draft-bind-object", "--object-id", object_id)
        assert code == 0, json.dumps(payload)
        return payload["bound_object"]["handle"]

    def discover(self, target: str, meaning: str = "Fade Time") -> str:
        code, payload = self.step("draft-discover-fields", "--object-handle", target,
                                  "--meaning", meaning)
        assert code == 0, payload
        return payload["meaning_results"][0]["candidates"][0]["handle"]


class CreateTask(FieldTask):
    """Read-only Wwise boundary for public create declarations and previews."""

    def __init__(self, path: Path, version: str, operation: str = "object.create") -> None:
        super().__init__(path, version, operation)
        parent_path = r"\Events\Default Work Unit\Owned"
        self.objects = {
            FIRST: {"id": FIRST, "name": "Owned", "type": "Folder", "classId": 1,
                    "path": parent_path, "parent": {"id": PROJECT}},
            SECOND: {"id": SECOND, "name": "Play_Weather", "type": "Event", "classId": 2,
                     "path": parent_path + r"\Play_Weather", "parent": {"id": FIRST}},
        }
        self.types = [
            {"classId": 1, "name": "Folder", "type": "WObject"},
            {"classId": 2, "name": "Event", "type": "WObject"},
            {"classId": 3, "name": "Action", "type": "WObject"},
        ]
        self.metadata["Delay"] = {
            "name": "Delay", "type": "Real64",
            "restriction": {"type": "range", "min": 0, "max": 60},
        }

    def call(self, uri: str, args: Any = None, options: Any = None) -> Any:
        if uri == "ak.wwise.core.object.get" and "from" in args:
            self.calls.append((uri, args, options))
            source = args["from"]
            if "id" in source:
                rows = [self.objects[key] for key in source["id"] if key in self.objects]
            else:
                assert set(source) == {"path"}, args
                rows = [row for row in self.objects.values() if row["path"] in source["path"]]
            if "transform" in args:
                assert len(rows) == 1, args
                parent = rows[0]
                if args["transform"] == [{"select": ["children"]}]:
                    rows = [row for row in self.objects.values()
                            if row["parent"]["id"] == parent["id"]]
                else:
                    assert args["transform"] == [{"select": ["descendants"]}], args
                    rows = [row for row in self.objects.values()
                            if row["path"].startswith(parent["path"] + "\\")]
            return {"return": self.project_rows(rows, options)}
        return super().call(uri, args, options)

    def discover_kind(self, meaning: str) -> str:
        code, payload = self.step("draft-discover-types", "--role", "object",
                                  "--meaning", meaning)
        assert code == 0, payload
        assert len(payload["type_candidates"]) == 1
        return payload["type_candidates"][0]["handle"]

    def preview_artifact(self) -> dict[str, Any]:
        before = deepcopy(self.objects)
        project_before = self.project_file.read_bytes()
        code, checked = self.step("draft-check")
        assert code == 0, checked
        code, preview = self.step("preview-from-draft")
        assert code == 0, preview
        code, shown = self.run("transaction-show", preview["transaction_id"])
        assert code == 0, shown
        assert shown["state"] == "awaiting_confirmation"
        assert self.objects == before
        assert self.project_file.read_bytes() == project_before
        assert all(uri in {
            "ak.wwise.core.getInfo", "ak.wwise.core.getProjectInfo",
            "ak.wwise.core.object.get", "ak.wwise.core.object.getTypes",
            "ak.wwise.core.object.getPropertyAndReferenceNames",
            "ak.wwise.core.object.getPropertyInfo",
        } for uri, _, _ in self.calls)
        return shown["artifact"]


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("conflict", ("rename", "replace"))
def test_create_conflict_declaration_reaches_preview_without_writing(
    tmp_path: Path, version: str, conflict: str,
) -> None:
    task = CreateTask(tmp_path, version)
    parent = task.bind(FIRST)
    kind = task.discover_kind("Event")
    settings = ["--name-conflict", conflict]
    if conflict == "replace":
        settings.extend(["--replace-owner-handle", parent])
    code, configured = task.step("draft-business-configure", *settings)
    assert code == 0, configured
    code, declared = task.step(
        "draft-declare-new", "--declaration-id", "weather", "--parent-handle", parent,
        "--name", "Play_Weather", "--kind", kind,
    )
    assert code == 0, declared
    artifact = task.preview_artifact()
    expected = {
        "parent": {"kind": "id", "value": FIRST}, "type": "Event",
        "name": "Play_Weather", "on_name_conflict": conflict,
    }
    if conflict == "replace":
        expected["replace_owned_root"] = {"kind": "id", "value": FIRST}
    assert artifact["request"]["arguments"] == expected
    assert artifact["prepared_operation"]["dispatch"]["args"]["onNameConflict"] == conflict


@pytest.mark.parametrize("version", VERSIONS)
def test_create_replace_without_owner_cannot_produce_a_preview(
    tmp_path: Path, version: str,
) -> None:
    task = CreateTask(tmp_path, version)
    parent = task.bind(FIRST)
    kind = task.discover_kind("Event")
    code, configured = task.step("draft-business-configure", "--name-conflict", "replace")
    assert code == 0, configured
    before = deepcopy(task.objects)
    revision = task.revision
    code, before_draft = task.run("draft-inspect", task.draft,
                                  "--task-authority", task.authority)
    assert code == 0, before_draft
    task.calls.clear()
    code, declared = task.step(
        "draft-declare-new", "--declaration-id", "weather", "--parent-handle", parent,
        "--name", "Play_Weather", "--kind", kind,
    )
    assert code == 2, declared
    assert declared["error_code"] == "REPLACE_OWNERSHIP_REQUIRED"
    assert declared["details"]["repair"]["draft_changed"] is False
    assert task.revision == revision
    assert task.objects == before
    assert task.calls == []
    code, after_draft = task.run("draft-inspect", task.draft,
                                 "--task-authority", task.authority)
    assert code == 0, after_draft
    assert after_draft["draft"] == before_draft["draft"]
    code, no_preview = task.step("preview-from-draft")
    assert code == 2, no_preview
    assert "transaction_id" not in no_preview
    assert all(uri == "ak.wwise.core.getInfo" for uri, _, _ in task.calls)


@pytest.mark.parametrize("version,operation", [
    *((version, "object.create") for version in VERSIONS),
    *((version, "object.set") for version in VERSIONS[1:]),
])
def test_action_creation_has_explicit_boundary_without_writing(
    tmp_path: Path, version: str, operation: str,
) -> None:
    task = CreateTask(tmp_path, version, operation)
    parent = task.bind(SECOND)
    kind = task.discover_kind("Action")
    before = deepcopy(task.objects)
    task.calls.clear()
    code, declared = task.step(
        "draft-declare-new", "--declaration-id", "play", "--parent-handle", parent,
        "--name", "Play", "--kind", kind,
    )
    # This is boundary evidence, not positive Action-creation timing coverage.
    # Event parenting and Action derived identity need a separate runtime repair.
    assert code == 2, declared
    assert declared["error_code"] == "ACTION_CREATION_UNAVAILABLE"
    assert declared["details"]["repair"]["draft_changed"] is False
    assert "transaction_id" not in declared
    assert task.objects == before
    assert task.calls == []


@pytest.mark.parametrize("version", VERSIONS)
def test_create_schema_does_not_advertise_unavailable_action_durations(
    tmp_path: Path, version: str,
) -> None:
    task = CreateTask(tmp_path, version)
    code, schema = task.run("operation-schema", "object.create")
    assert code == 0, schema
    declaration = schema["business_adapter"]["declaration"]
    for key in ("stable_fields", "field_value_types", "field_semantics"):
        assert not {"fade_time_ms", "delay_ms"}.intersection(declaration.get(key, {}))
    assert schema["business_adapter"]["creation_boundaries"]["Action"] == {
        "status": "unsupported_by_skill_interface",
        "reason": "event_parent_and_derived_action_identity_require_a_dedicated_creation_contract",
        "existing_object_edits": "supported_through_object_set_or_metadata_operations",
    }


@pytest.mark.parametrize("version", VERSIONS[1:])
def test_set_schema_keeps_existing_action_duration_fields(
    tmp_path: Path, version: str,
) -> None:
    task = FieldTask(tmp_path, version, "object.set")
    code, schema = task.run("operation-schema", "object.set")
    assert code == 0, schema
    declaration = schema["business_adapter"]["declaration"]
    assert declaration["field_value_types"]["fade_time_ms"] == "number"
    assert declaration["field_value_types"]["delay_ms"] == "number"
    assert declaration["field_semantics"]["fade_time_ms"]["unit"] == "milliseconds"


@pytest.mark.parametrize("version", ("2022.1", "2025.1"))
def test_music_transition_exact_guid_binding_accepts_observed_owned_display_path(
    tmp_path: Path, version: str,
) -> None:
    task = FieldTask(tmp_path, version, "object.setProperty")
    task.objects[FIRST] = {"id": FIRST, "name": "Transition", "type": "MusicTransition",
                           "path": r"Root\Transition"}
    handle = task.bind(FIRST)
    code, inspected = task.run("draft-inspect", task.draft, "--task-authority", task.authority)
    assert code == 0, inspected
    assert handle.startswith("boh1-"), handle
    assert all(uri in {"ak.wwise.core.getInfo", "ak.wwise.core.getProjectInfo", "ak.wwise.core.object.get"}
               for uri, _, _ in task.calls)


@pytest.mark.parametrize("object_type,path", [
    ("Sound", r"Root\Transition"),
    ("MusicTransition", r"Other\Transition"),
    ("MusicTransition", r"Root\Other"),
    ("MusicTransition", r"..\Transition"),
    ("MusicTransition", "Root/Transition"),
])
def test_transition_display_exception_does_not_relax_other_live_identities(
    tmp_path: Path, object_type: str, path: str,
) -> None:
    task = FieldTask(tmp_path, "2025.1", "object.setProperty")
    task.objects[FIRST] = {"id": FIRST, "name": "Transition", "type": object_type, "path": path}
    code, rejected = task.step("draft-bind-object", "--object-id", FIRST)
    assert code == 2, rejected
    assert rejected["error_code"] == "BUSINESS_OBJECT_BINDING_MISMATCH"


def test_owned_transition_name_cannot_be_rewritten_as_an_intrinsic_name(tmp_path: Path) -> None:
    task = FieldTask(tmp_path, "2025.1", "object.setName")
    task.objects[FIRST] = {"id": FIRST, "name": "Transition", "type": "MusicTransition",
                           "path": r"Root\Transition"}
    task.bind(FIRST)
    code, declared = task.step("draft-declare-object-change", "--new-name", "Renamed")
    assert code == 0, declared
    code, rejected = task.step("draft-check")
    assert code == 2, rejected
    assert rejected["error_code"] == "DERIVED_OBJECT_NAME_BOUNDARY"


@pytest.mark.parametrize("version", VERSIONS[1:])
def test_unknown_batch_fixed_field_is_not_reinterpreted_as_search(
    tmp_path: Path, version: str,
) -> None:
    task = FieldTask(tmp_path, version, "object.set")
    target = task.bind(FIRST)
    task.calls.clear()
    code, payload = task.step(
        "draft-declare-existing-batch", "--row-order", "rain", "--row", "rain", target,
        "--field", "rain", "Action Fade Time", "0.25",
    )
    assert code == 2, payload
    assert payload["error_code"] == "UNKNOWN_BUSINESS_FIELD"
    assert payload["details"]["declaration_id"] == "rain"
    assert payload["details"]["field"] == "Action Fade Time"
    assert task.revision == 2
    assert not any(uri.endswith("getPropertyInfo") for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", VERSIONS[1:])
def test_batch_uses_discovered_fields_and_rejects_cross_object_handles_atomically(
    tmp_path: Path, version: str,
) -> None:
    task = FieldTask(tmp_path, version, "object.set")
    first, second = task.bind(FIRST), task.bind(SECOND)
    first_field, second_field = task.discover(first), task.discover(second)
    store = OperationDraftStore(tmp_path / "state")
    before = store.inspect(task.draft, task_authority=task.authority)
    rows = ("--row-order", "rain", "--row-order", "wind", "--row", "rain", first,
            "--row", "wind", second, "--field-value", "rain", first_field, "0.25")
    code, failed = task.step("draft-declare-existing-batch", *rows,
                             "--field-value", "wind", first_field, "0.4")
    assert code == 2, failed
    assert failed["error_code"] == "FIELD_HANDLE_SCOPE_MISMATCH"
    after = store.inspect(task.draft, task_authority=task.authority)
    assert after.revision == before.revision
    assert after.composition == before.composition
    code, applied = task.step("draft-declare-existing-batch", *rows,
                              "--field-value", "wind", second_field, "0.4")
    assert code == 0, applied
    assert applied["batch_receipt"]["row_count"] == 2
    assert applied["batch_receipt"]["field_count"] == 2
    assert task.revision == before.revision + 1


@pytest.mark.parametrize("version", VERSIONS)
def test_import_discovers_custom_fields_without_native_class_or_token(
    tmp_path: Path, version: str,
) -> None:
    task = FieldTask(tmp_path, version, "audio.import")
    task.objects[FIRST] = {"id": FIRST, "name": "Weather", "type": "ActorMixer",
                           "path": "\\Actor-Mixer Hierarchy\\Default Work Unit\\Weather"}
    target = task.bind(FIRST)
    code, payload = task.step("draft-discover-fields", "--semantic-kind", "sound-sfx",
                              "--meaning", "Fade Time")
    assert code == 0, payload
    field = payload["meaning_results"][0]["candidates"][0]
    assert field["label"] == "Fade Time"
    assert field["handle"].startswith("bfh1-")
    assert "--token" not in json.dumps(payload)
    assert "--class-name" not in json.dumps(payload)


def test_native_field_binder_is_not_a_public_command(tmp_path: Path) -> None:
    task = FieldTask(tmp_path, "2024.1", "object.create")
    with pytest.raises(SystemExit) as error:
        task.run("draft-bind-field", task.draft, "--task-authority", task.authority,
                 "--expected-revision", "1", "--class-name", "Action", "--token", "FadeTime")
    assert error.value.code == 2
    assert task.calls == []


@pytest.mark.parametrize("version", VERSIONS)
def test_discovered_enum_names_can_be_used_without_guessing_wire_numbers(
    tmp_path: Path, version: str,
) -> None:
    task = FieldTask(tmp_path, version, "object.setProperty")
    task.metadata = {"Mode": {"name": "Mode", "type": "int32",
        "display": {"name": "Playback Mode"}, "restriction": {"type": "enum", "values": [
            {"displayName": "First mode", "value": 0},
            {"displayName": "Second mode", "value": 1}]}}}
    target = task.bind(FIRST)
    code, found = task.step("draft-discover-fields", "--object-handle", target,
                            "--meaning", "Playback Mode")
    assert code == 0, found
    field = found["meaning_results"][0]["candidates"][0]
    assert field["restrictions"]["enum_labels"] == [
        {"label": "First mode", "value": 0}, {"label": "Second mode", "value": 1}]
    code, declared = task.step("draft-declare-field-change", "--object-handle", target,
                               "--field-handle", field["handle"],
                               "--business-value", "Second mode")
    assert code == 0, declared
    record = OperationDraftStore(tmp_path / "state").inspect(task.draft, task_authority=task.authority)
    assert record.composition["business_session"]["declarations"][0]["fields"]["business_value"] == 1


@pytest.mark.parametrize("version", VERSIONS[1:])
def test_action_fixed_durations_materialize_seconds(
    tmp_path: Path, version: str,
) -> None:
    task = FieldTask(tmp_path, version, "object.set")
    target = task.bind(FIRST)
    code, declared = task.step("draft-declare-existing-batch", "--row-order", "rain",
        "--row", "rain", target, "--field", "rain", "fade_time_ms", "250",
        "--field", "rain", "delay_ms", "80")
    assert code == 0, declared
    code, inspected = task.run("draft-inspect", task.draft, "--task-authority", task.authority)
    assert code == 0, inspected
    record = OperationDraftStore(tmp_path / "state").inspect(task.draft, task_authority=task.authority)
    from wwise_waapi.business_adapters import business_adapter
    from wwise_waapi.business_declaration_state import BusinessDeclarationSession
    request = business_adapter("object.set").materialize(
        BusinessDeclarationSession.from_dict(record.composition["business_session"]))
    assert request["arguments"]["objects"][0]["properties"] == [
        {"name": "FadeTime", "value": 0.25}, {"name": "Delay", "value": 0.08}]


@pytest.mark.parametrize("version", VERSIONS)
def test_field_discovery_distinguishes_no_match_from_multiple_matches(
    tmp_path: Path, version: str,
) -> None:
    task = FieldTask(tmp_path, version, "object.setProperty")
    target = task.bind(FIRST)
    code, failed = task.step("draft-discover-fields", "--object-handle", target,
                             "--meaning", "Unrelated missing field")
    assert code == 2, failed
    assert failed["details"]["object_handle"] == target
    assert failed["details"]["meaning_results"][0] == {
        "meaning": "Unrelated missing field", "candidate_count": 0, "match_status": "no_matches"}
    assert task.revision == 2
    task.metadata["OtherFade"] = {"name": "OtherFade", "type": "Real64",
                                  "display": {"name": "Fade Time"}}
    code, found = task.step("draft-discover-fields", "--object-handle", target, "--meaning", "Fade Time")
    assert code == 0, found
    assert found["selection_required"] is True
    assert found["meaning_results"][0]["candidate_count"] == 2


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("object_type", ("Action", "Sound"))
def test_time_suffix_has_action_scope_not_just_a_matching_token(
    tmp_path: Path, version: str, object_type: str,
) -> None:
    task = FieldTask(tmp_path, version, "object.setProperty")
    task.set_object_type(FIRST, object_type, 1 if object_type == "Action" else 2)
    if object_type == "Sound":
        task.objects[FIRST]["name"] = "FixtureSound"
        task.objects[FIRST]["path"] = "\\Actor-Mixer Hierarchy\\Default Work Unit\\FixtureSound"
    target = task.bind(FIRST)
    handle = task.discover(target)
    revision = task.revision
    code, payload = task.step("draft-declare-field-change", "--object-handle", target,
                              "--field-handle", handle, "--business-value", "250 milliseconds")
    assert code == (0 if object_type == "Action" else 2), payload
    record = OperationDraftStore(tmp_path / "state").inspect(task.draft, task_authority=task.authority)
    if object_type == "Action":
        assert record.composition["business_session"]["declarations"][0]["fields"]["business_value"] == 0.25
    else:
        assert record.revision == revision
        assert record.composition["business_session"]["declarations"] == []


@pytest.mark.parametrize("value", ("-1", "NaN", "inf"))
def test_fixed_duration_rejects_invalid_values_without_draft_update(tmp_path: Path, value: str) -> None:
    task = FieldTask(tmp_path, "2024.1", "object.set")
    target = task.bind(FIRST)
    code, payload = task.step("draft-declare-existing", "--declaration-id", "rain",
                              "--object-handle", target, "--field", "delay_ms", value)
    assert code == 2, payload
    assert task.revision == 2


def test_enum_duplicate_labels_require_a_disclosed_distinct_value(tmp_path: Path) -> None:
    task = FieldTask(tmp_path, "2024.1", "object.setProperty")
    task.metadata = {"Mode": {"name": "Mode", "type": "int32",
        "restriction": {"type": "enum", "values": [
            {"displayName": "Same", "value": 0}, {"displayName": "Same", "value": 1}]}}}
    target = task.bind(FIRST)
    field = task.discover(target, "Mode")
    before = task.revision
    args = ("--object-handle", target, "--field-handle", field, "--business-value")
    code, failed = task.step("draft-declare-field-change", *args, "Same")
    assert code == 2 and failed["error_code"] == "FIELD_CHOICE_AMBIGUOUS", failed
    assert task.revision == before
    code, applied = task.step("draft-declare-field-change", *args, "1")
    assert code == 0, applied


def test_discovery_discloses_time_value_unit(tmp_path: Path) -> None:
    task = FieldTask(tmp_path, "2024.1", "object.setProperty")
    target = task.bind(FIRST)
    code, found = task.step("draft-discover-fields", "--object-handle", target, "--meaning", "Fade Time")
    assert code == 0, found
    assert found["meaning_results"][0]["candidates"][0]["value_input"]["bare_number_unit"] == "seconds"


def test_enum_label_value_collision_requires_copying_an_explicit_choice(tmp_path: Path) -> None:
    task = FieldTask(tmp_path, "2024.1", "object.setProperty")
    task.metadata = {"Mode": {"name": "Mode", "type": "String",
        "restriction": {"type": "enum", "values": [
            {"displayName": "First", "value": "Second"},
            {"displayName": "Second", "value": "actual"}]}}}
    target = task.bind(FIRST)
    code, found = task.step("draft-discover-fields", "--object-handle", target, "--meaning", "Mode")
    assert code == 0, found
    field = found["meaning_results"][0]["candidates"][0]
    args = ("--object-handle", target, "--field-handle", field["handle"], "--business-value")
    code, failed = task.step("draft-declare-field-change", *args, "Second")
    assert code == 2 and failed["error_code"] == "FIELD_CHOICE_AMBIGUOUS", failed
    assert failed["details"]["candidate_count"] == 2
    choice = field["value_input"]["choices"][0]
    assert choice["value"] == "Second"
    code, applied = task.step("draft-declare-field-change", *args, choice["input"])
    assert code == 0, applied
    record = OperationDraftStore(tmp_path / "state").inspect(task.draft, task_authority=task.authority)
    assert record.composition["business_session"]["declarations"][0]["fields"]["business_value"] == "Second"


def test_plugin_named_action_does_not_inherit_builtin_duration_units(tmp_path: Path) -> None:
    task = FieldTask(tmp_path, "2024.1", "object.createPlugin")
    task.objects[FIRST] = {"id": FIRST, "name": "Weather", "type": "ActorMixer",
                           "path": "\\Actor-Mixer Hierarchy\\Default Work Unit\\Weather"}
    task.types = [{"classId": 90001, "name": "Action", "type": "Effect"}]
    task.bind(FIRST)
    code, types = task.step("draft-discover-types", "--role", "effect", "--meaning", "Action")
    assert code == 0, types
    type_handle = types["type_candidates"][0]["handle"]
    code, fields = task.step("draft-discover-fields", "--type-handle", type_handle, "--meaning", "Fade Time")
    assert code == 0, fields
    assert "bare_number_unit" not in fields["meaning_results"][0]["candidates"][0]["value_input"]


@pytest.mark.parametrize("version", VERSIONS[1:])
def test_fixed_action_durations_reach_immutable_preview(tmp_path: Path, version: str) -> None:
    task = FieldTask(tmp_path, version, "object.set")
    task.metadata["Delay"] = {"name": "Delay", "type": "Real64",
                              "restriction": {"type": "range", "min": 0, "max": 60}}
    task.objects[FIRST].update({"@FadeTime": 0.0, "@Delay": 0.0})
    target = task.bind(FIRST)
    code, declared = task.step("draft-declare-existing", "--declaration-id", "rain",
                               "--object-handle", target, "--field", "fade_time_ms", "250",
                               "--field", "delay_ms", "80")
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 0, json.dumps(checked)
    code, preview = task.step("preview-from-draft")
    assert code == 0, json.dumps(preview)
    assert preview["transaction_id"].startswith("tx1-")
    assert not any(uri == "ak.wwise.core.object.set" for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", VERSIONS[1:])
def test_fixed_action_duration_is_rejected_on_an_unrelated_object(tmp_path: Path, version: str) -> None:
    task = FieldTask(tmp_path, version, "object.set")
    task.objects[FIRST] = {"id": FIRST, "name": "Weather", "type": "ActorMixer",
                           "path": "\\Actor-Mixer Hierarchy\\Default Work Unit\\Weather"}
    target = task.bind(FIRST)
    code, failed = task.step("draft-declare-existing-batch", "--row-order", "weather",
                             "--row", "weather", target, "--field", "weather", "delay_ms", "250")
    assert code == 2 and failed["error_code"] == "BUSINESS_FIELD_SCOPE_MISMATCH", failed
    record = OperationDraftStore(tmp_path / "state").inspect(task.draft, task_authority=task.authority)
    assert record.revision == 2
    assert record.composition["business_session"]["declarations"] == []
