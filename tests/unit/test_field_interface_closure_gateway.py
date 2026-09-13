"""Public field acquisition and declaration invariants, without a live host."""

from __future__ import annotations

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
            value: {"id": value, "name": "", "type": "Action",
                    "path": f"\\Events\\Default Work Unit\\Event{index}\\[Play]"}
            for index, value in enumerate((FIRST, SECOND))
        }
        config = path / "config.json"
        config.write_text(json.dumps({"wwise_version": None, "waapi_port": None,
                                      "project_modification_policy": "ask_before_changes"}))
        self.env = {"WAAPI_SKILL_CONFIG_PATH": str(config),
                    "WWISE_VERSION": version, "WWISE_WAAPI_HOST": "127.0.0.1",
                    "WWISE_WAAPI_PORT": "31337"}
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
                return {"return": [{"id": PROJECT, "name": "Fixture", "type": "Project",
                                    "path": "\\", "filePath": str(self.project_file)} ]}
            return {"return": [self.objects[value] for value in args["from"]["id"]]}
        if uri.endswith("getPropertyAndReferenceNames"):
            return {"return": list(self.metadata)}
        if uri.endswith("getPropertyInfo"):
            return self.metadata[args["property"]]
        if uri.endswith("getTypes"):
            if hasattr(self, "types"):
                return {"return": self.types}
            return {"return": [{"classId": 1, "name": "Action", "type": "Action"},
                               {"classId": 2, "name": "Sound", "type": "Sound"}]}
        raise AssertionError((uri, args, options))

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
    task.objects[FIRST]["type"] = object_type
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
