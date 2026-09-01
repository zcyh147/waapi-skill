from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.operation_registry import (  # pyright: ignore[reportMissingImports]
    BUSINESS_DECLARATION_INPUT_MODE,
    COMPOSER_INPUT_MODE,
    INTERNAL_CANONICAL_INPUT_MODE,
    OPERATION_REQUEST_CONTRACT,
    describe_operation,
)
from wwise_waapi.operation_composer import operation_composer_digest
from wwise_waapi.operation_drafts import OperationDraftStore
from wwise_waapi.transactions import (  # pyright: ignore[reportMissingImports]
    TransactionStore,
)


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_operation_input_gateway_script",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
waapi_gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = waapi_gateway
SPEC.loader.exec_module(waapi_gateway)


OBJECT_GUID = "{11111111-1111-1111-1111-111111111111}"
PARENT_GUID = "{22222222-2222-2222-2222-222222222222}"
PROJECT_GUID = "{33333333-3333-3333-3333-333333333333}"


class FakeClient:
    def __init__(self, responses: Mapping[str, Sequence[Any]]) -> None:
        self.responses = {uri: deque(values) for uri, values in responses.items()}
        self.calls: list[
            tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]
        ] = []
        self.disconnected = False

    def call(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Any:
        self.calls.append((uri, args, options))
        values = self.responses.get(uri)
        if not values:
            raise AssertionError(f"Unexpected or exhausted WAAPI call: {uri}")
        return values.popleft()

    def disconnect(self) -> None:
        self.disconnected = True


class ObjectLifecycleClient:
    """Small live-Wwise Adapter for the public Draft-to-Preview seam."""

    CURRENT_PARENT_GUID = "{44444444-4444-4444-4444-444444444444}"

    def __init__(self) -> None:
        self.calls: list[
            tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]
        ] = []
        self.source = {
            **object_row(),
            "parent": {"id": self.CURRENT_PARENT_GUID},
        }
        self.parent = {
            "id": PARENT_GUID,
            "name": "Destination",
            "type": "ActorMixer",
            "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Destination",
            "parent": {"id": self.CURRENT_PARENT_GUID},
            "notes": "",
        }

    def call(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Any:
        self.calls.append((uri, args, options))
        if uri == "ak.wwise.core.getInfo":
            return live_info()
        if uri == "ak.wwise.core.getProjectInfo":
            return project_row()
        if uri == "ak.wwise.core.object.getTypes":
            return {"return": [{"classId": 1, "name": "Sound", "type": "Sound"}]}
        if uri == "ak.wwise.core.object.get":
            selector = dict(args or {})
            source = selector.get("from")
            if isinstance(source, Mapping) and isinstance(source.get("id"), list):
                rows = []
                for object_id in source["id"]:
                    if str(object_id).upper() == OBJECT_GUID.upper():
                        rows.append(dict(self.source))
                    elif str(object_id).upper() == PARENT_GUID.upper():
                        rows.append(dict(self.parent))
                return {"return": rows}
            if isinstance(source, Mapping) and isinstance(source.get("path"), list):
                rows = []
                for path in source["path"]:
                    if path == self.source["path"]:
                        rows.append(dict(self.source))
                    elif path == self.parent["path"]:
                        rows.append(dict(self.parent))
                return {"return": rows}
            if "waql" in selector:
                return {"return": []}
            raise AssertionError(f"Unexpected object.get selector: {selector!r}")
        raise AssertionError(f"Unexpected WAAPI call: {uri}")

    def disconnect(self) -> None:
        return None


def gateway_env(
    tmp_path: Path,
    *,
    version: str = "2022.1",
    policy: str = "ask_before_changes",
) -> dict[str, str]:
    config_path = tmp_path / "config" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "wwise_version": None,
                "waapi_host": "127.0.0.1",
                "waapi_port": None,
                "project_modification_policy": policy,
            }
        ),
        encoding="utf-8",
    )
    return {
        "WAAPI_SKILL_CONFIG_PATH": str(config_path),
        "WWISE_WAAPI_HOST": "127.0.0.1",
        "WWISE_WAAPI_PORT": "31337",
        "WWISE_VERSION": version,
    }


def live_info(*, year: int = 2022) -> dict[str, Any]:
    return {
        "displayName": "Wwise",
        "isCommandLine": True,
        "sessionId": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
        "processId": 4242,
        "processPath": "/Applications/Wwise/WwiseConsole",
        "apiVersion": 1,
        "platform": "macosx",
        "configuration": "release",
        "version": {
            "year": year,
            "major": 1,
            "minor": 0,
            "build": 1,
            "displayName": f"v{year}.1.0",
        },
    }


def project_row() -> dict[str, Any]:
    return {
        "id": PROJECT_GUID,
        "name": "SampleProject",
        "path": _native_project_path("SampleProject.wproj"),
    }


def _native_project_path(filename: str) -> str:
    if os.name == "nt":
        return rf"C:\project\{filename}"
    return f"/project/{filename}"


def object_row() -> dict[str, Any]:
    return {
        "id": OBJECT_GUID,
        "name": "OldName",
        "type": "Sound",
        "path": r"\Actor-Mixer Hierarchy\Default Work Unit\OldName",
        "parent": {"id": PARENT_GUID},
        "notes": "before",
    }


def set_notes_request(*, version: str = "2022.1") -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": "object.setNotes",
        "arguments": {
            "object": {"kind": "id", "value": OBJECT_GUID},
            "value": "after",
        },
    }


def object_set_request(*, version: str = "2022.1") -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": "object.set",
        "arguments": {
            "objects": [
                {
                    "object": {"kind": "id", "value": OBJECT_GUID},
                    "notes": "after",
                }
            ]
        },
    }


def preview_client(*, year: int = 2022) -> FakeClient:
    return FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=year)],
            "ak.wwise.core.getProjectInfo": [project_row()],
            "ak.wwise.core.object.getTypes": [
                {"return": [{"classId": 1, "name": "Sound", "type": "Sound"}]}
            ],
            "ak.wwise.core.object.get": [
                {"return": [object_row()]},
                {"return": [object_row()]},
                {"return": []},
            ],
        }
    )


def offline_execute(
    tmp_path: Path,
    *arguments: str,
    version: str = "2022.1",
) -> tuple[int, dict[str, Any]]:
    def fail_if_connected(url: str) -> None:
        raise AssertionError(f"Offline operation input command connected to {url}")

    return waapi_gateway.execute_gateway(
        list(arguments),
        env=gateway_env(tmp_path, version=version),
        client_factory=fail_if_connected,
    )


def test_metadata_operation_schema_exposes_one_business_continuation(tmp_path: Path) -> None:
    code, payload = offline_execute(
        tmp_path,
        "--version",
        "2025.1",
        "operation-schema",
        "object.setReference",
    )

    assert code == 0
    assert "request_envelope" not in payload
    assert payload["operation"]["input_mode"] == BUSINESS_DECLARATION_INPUT_MODE
    assert "typed_operation" not in payload
    adapter = payload["business_adapter"]
    assert adapter["contract"] == "waapi-skill.object-metadata-business/v1"
    assert adapter["field_discovery"]["subcommand"] == "draft-discover-fields"
    assert adapter["field_discovery"]["input"] == "user_facing_meaning"
    assert adapter["declaration"]["subcommand"] == "draft-declare-field-change"
    assert "--token" not in json.dumps(adapter)


def test_switch_assignment_schema_exposes_only_business_handles(
    tmp_path: Path,
) -> None:
    code, payload = offline_execute(
        tmp_path,
        "--version",
        "2022.1",
        "operation-schema",
        "switchContainer.removeAssignment",
    )

    assert code == 0, payload
    assert payload["operation"]["input_mode"] == BUSINESS_DECLARATION_INPUT_MODE
    assert "typed_operation" not in payload
    adapter = payload["business_adapter"]
    assert adapter["contract"] == "waapi-skill.switch-assignment-business/v1"
    assert adapter["binding"]["roles"] == [
        "switch_container",
        "child",
        "state_or_switch",
    ]
    assert adapter["declaration"]["subcommand"] == (
        "draft-declare-switch-assignment"
    )


def test_metadata_business_contract_binds_field_to_exact_target_object(
    tmp_path: Path,
) -> None:
    code, payload = offline_execute(
        tmp_path,
        "--version",
        "2025.1",
        "operation-schema",
        "object.setReference",
    )

    assert code == 0, payload
    discovery = payload["business_adapter"]["field_discovery"]
    assert discovery["scope"] == "bound_target_object"
    assert discovery["result"] == "copy_one_gateway_returned_field_handle"
    assert discovery["platform"] == "optional_and_sealed_into_handle"


@pytest.mark.parametrize(
    ("operation", "versions"),
    [
        (
            "object.setProperty",
            ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
        ),
        (
            "object.setReference",
            ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
        ),
        ("object.setLinked", ("2023.1", "2024.1", "2025.1")),
    ],
)
def test_every_metadata_field_lane_exposes_only_business_handles(
    tmp_path: Path,
    operation: str,
    versions: tuple[str, ...],
) -> None:
    for version in versions:
        code, payload = offline_execute(
            tmp_path / f"{operation}-{version}",
            "--version",
            version,
            "operation-schema",
            operation,
            version=version,
        )

        assert code == 0, payload
        assert payload["operation"]["input_mode"] == (
            BUSINESS_DECLARATION_INPUT_MODE
        )
        assert payload["business_adapter"]["version"] == version
        assert "typed_operation" not in payload
        assert "argument_contract" not in payload["operation"]
        assert "--token" not in json.dumps(payload)


def test_business_draft_start_discloses_binding_before_declaration(
    tmp_path: Path,
) -> None:
    schema_code, schema = offline_execute(
        tmp_path,
        "operation-schema",
        "object.create",
        version="2021.1",
    )
    assert schema_code == 0, schema
    assert schema["operation"]["input_mode"] == BUSINESS_DECLARATION_INPUT_MODE
    assert schema["business_adapter"]["start"]["next_command"]["gateway_argv"] == [
        "draft-start",
        "object.create",
    ]
    assert "composer" not in schema

    code, payload = offline_execute(
        tmp_path,
        "--state-dir",
        str(tmp_path / "state"),
        "draft-start",
        "object.create",
        version="2021.1",
    )

    assert code == 0, payload
    draft = payload["draft"]
    assert draft["missing_fields"] == ["business_declaration"]
    assert draft["allowed_actions"] == ["bind-object"]
    binding = draft["next_action_binding"]
    assert binding["required_next_phase"] == "bind_existing_business_object"
    assert binding["responsibility_split"] == {
        "agent": "natural_language_to_closed_high_level_business_facts",
        "gateway": "business_facts_to_exact_waapi_request_and_execution_plan",
    }
    assert binding["forbidden_inputs"] == [
        "native_request",
        "model_invented_object_path",
        "object_type",
        "metadata_scope",
        "waapi_args",
        "waapi_options",
    ]
    assert "typed_fact_batch_discipline" not in binding
    assert "draft-apply" not in json.dumps(binding)


def test_object_graph_declaration_rejects_audio_only_switch_value(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    code, started = offline_execute(
        tmp_path,
        "--state-dir",
        str(state_dir),
        "--version",
        "2022.1",
        "draft-start",
        "object.create",
    )
    assert code == 0, started
    record_path = (
        state_dir
        / "operation-drafts-v1"
        / "records"
        / f"{started['draft']['draft_id']}.json"
    )
    before = record_path.read_bytes()

    rejected_code, rejected = offline_execute(
        tmp_path,
        "--state-dir",
        str(state_dir),
        "draft-declare-new",
        started["draft"]["draft_id"],
        "--task-authority",
        started["task_authority"],
        "--expected-revision",
        "1",
        "--declaration-id",
        "new-child",
        "--parent-handle",
        "obj-unbound",
        "--name",
        "Snow",
        "--kind",
        "random-container",
        "--switch-value",
        "Snow",
    )

    assert rejected_code == 2
    assert rejected["error_code"] == "GatewayInputError"
    assert rejected["message"] == (
        "--switch-value is available only for audio.import business declarations"
    )
    assert record_path.read_bytes() == before


def test_object_create_discloses_collision_policy_as_business_setting(
    tmp_path: Path,
) -> None:
    code, payload = offline_execute(
        tmp_path,
        "operation-schema",
        "object.create",
        version="2023.1",
    )

    assert code == 0, payload
    adapter = payload["business_adapter"]
    assert adapter["settings"]["name_conflict"] == [
        "fail",
        "rename",
        "merge",
        "replace",
    ]
    assert adapter["declaration"]["bound_field_handle_container"] == "field_values"
    assert "composer" not in payload
def test_migrated_object_change_rejects_the_legacy_typed_operation_ingress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[Mapping[str, Any]] = []

    def fake_preview(request_payload: Mapping[str, Any], **_kwargs: Any) -> dict[str, Any]:
        captured.append(request_payload)
        return {"ok": True, "status": "ok", "request": request_payload}

    monkeypatch.setattr(waapi_gateway, "create_transaction_preview", fake_preview)
    digest = waapi_gateway.operation_request_schema_digest(
        "object.setNotes", "2022.1"
    )
    client = FakeClient({"ak.wwise.core.getInfo": [live_info()]})
    code, payload = waapi_gateway.execute_gateway(
        [
            "typed-operation",
            "object.setNotes",
            "--schema-digest",
            digest,
            "--apply",
            "--object",
            "id-string",
            OBJECT_GUID,
            "--text",
            "",
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert code == 2
    assert captured == []
    assert payload["error_code"] == "GatewayInputError"
    assert payload["message"] == (
        "This operation is not available through the concise typed-operation entry"
    )


@pytest.mark.parametrize(
    "operation",
    ("switchContainer.addAssignment", "switchContainer.removeAssignment"),
)
def _archive_test_typed_switch_assignment_enters_the_single_preview_ingress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    captured: list[Mapping[str, Any]] = []

    def fake_preview(request_payload: Mapping[str, Any], **_kwargs: Any) -> dict[str, Any]:
        captured.append(request_payload)
        return {"ok": True, "status": "ok", "request": request_payload}

    monkeypatch.setattr(waapi_gateway, "create_transaction_preview", fake_preview)
    digest = waapi_gateway.operation_request_schema_digest(operation, "2022.1")
    client = FakeClient({"ak.wwise.core.getInfo": [live_info()]})
    code, payload = waapi_gateway.execute_gateway(
        [
            "typed-operation", operation, "--schema-digest", digest, "--apply",
            "--switch-container", "id-string", OBJECT_GUID,
            "--child", "id-string", PARENT_GUID,
            "--state-or-switch", "path", r"\Switches\Default Work Unit\Ground",
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert code == 0, payload
    assert captured == [
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2022.1",
            "operation": operation,
            "arguments": {
                "switch_container": {"kind": "id", "value": OBJECT_GUID},
                "child": {"kind": "id", "value": PARENT_GUID},
                "state_or_switch": {
                    "kind": "path",
                    "value": r"\Switches\Default Work Unit\Ground",
                },
            },
        }
    ]
    assert payload["request"] == captured[0]


def test_typed_definition_files_is_not_public_after_business_cutover(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[Mapping[str, Any]] = []

    def fake_preview(request_payload: Mapping[str, Any], **_kwargs: Any) -> dict[str, Any]:
        captured.append(request_payload)
        return {"ok": True, "status": "ok", "request": request_payload}

    monkeypatch.setattr(waapi_gateway, "create_transaction_preview", fake_preview)
    operation = "soundbank.processDefinitionFiles"
    digest = waapi_gateway.operation_request_schema_digest(operation, "2022.1")
    definition = str((tmp_path / "Definition File.tsv").resolve())
    io_root = str(tmp_path.resolve())
    client = FakeClient({"ak.wwise.core.getInfo": [live_info()]})
    with pytest.raises(SystemExit) as removed:
        waapi_gateway.execute_gateway(
            [
                "typed-operation", operation, "--schema-digest", digest, "--apply",
                "--file", definition, "--io-root", io_root,
            ],
            env=gateway_env(tmp_path),
            client_factory=lambda _url: client,
        )

    assert removed.value.code == 2
    assert captured == []


def test_retired_typed_tab_import_is_absent_from_the_public_parser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[Mapping[str, Any]] = []

    def fake_preview(request_payload: Mapping[str, Any], **_kwargs: Any) -> dict[str, Any]:
        captured.append(request_payload)
        return {"ok": True, "status": "ok", "request": request_payload}

    monkeypatch.setattr(waapi_gateway, "create_transaction_preview", fake_preview)
    operation = "audio.importTabDelimited"
    digest = waapi_gateway.operation_request_schema_digest(operation, "2022.1")
    source = str((tmp_path / "Import.tsv").resolve())
    location = r"\Actor-Mixer Hierarchy\Default Work Unit"
    client = FakeClient({"ak.wwise.core.getInfo": [live_info()]})
    with pytest.raises(SystemExit) as exc_info:
        waapi_gateway.execute_gateway(
            [
                "typed-operation", operation, "--schema-digest", digest, "--apply",
                "--import-file", source,
                "--import-location", "path", location,
                "--import-language", "SFX",
                "--import-operation", "useExisting",
                "--auto-add", "true",
            ],
            env=gateway_env(tmp_path),
            client_factory=lambda _url: client,
        )

    assert exc_info.value.code == 2
    assert captured == []


def _without_route_specific_schema_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(payload))
    result.pop("command", None)
    result.pop("compatibility", None)
    operation = result.get("operation")
    if isinstance(operation, dict):
        operation.pop("summary", None)
        operation.pop("selection_guidance", None)
    return result


def test_normal_object_set_schema_and_detail_expose_only_business_input(
    tmp_path: Path,
) -> None:
    schema_code, schema = offline_execute(
        tmp_path,
        "--version",
        "2022.1",
        "operation-schema",
        "object.set",
    )
    detail_code, detail = offline_execute(tmp_path, "operations", "--detail")

    assert schema_code == detail_code == 0
    assert schema["operation"]["input_mode"] == BUSINESS_DECLARATION_INPUT_MODE
    assert "composer" not in schema
    adapter = schema["business_adapter"]
    assert adapter["input_mode"] == BUSINESS_DECLARATION_INPUT_MODE
    assert adapter["legacy_shallow_composer_public"] is False
    assert adapter["declaration"]["subcommands"] == [
        "draft-declare-existing",
        "draft-declare-new",
    ]
    encoded = json.dumps(schema)
    for native_term in (
        "registry_fragments",
        "top_level_fact_plan",
        "property_token",
        "waapi_args",
        "waapi_options",
    ):
        assert native_term not in encoded

    expected_modes = {
        "2022.1": BUSINESS_DECLARATION_INPUT_MODE,
        "2023.1": BUSINESS_DECLARATION_INPUT_MODE,
        "2024.1": BUSINESS_DECLARATION_INPUT_MODE,
        "2025.1": BUSINESS_DECLARATION_INPUT_MODE,
    }
    rows = {row["name"]: row for row in detail["operations"]}
    assert rows["object.set"]["input_modes_by_version"] == expected_modes
    assert "composer_contracts_by_version" not in rows["object.set"]
def test_normal_audio_import_schema_exposes_only_its_business_declaration_input(
    tmp_path: Path,
) -> None:
    schema_code, schema = offline_execute(
        tmp_path,
        "--version",
        "2022.1",
        "operation-schema",
        "audio.import",
    )
    detail_code, detail = offline_execute(tmp_path, "operations", "--detail")
    tab_code, tab_schema = offline_execute(
        tmp_path,
        "--version",
        "2022.1",
        "operation-schema",
        "audio.importTabDelimited",
    )

    assert schema_code == detail_code == tab_code == 0
    assert schema["operation"]["input_mode"] == BUSINESS_DECLARATION_INPUT_MODE
    assert "request_envelope" not in schema
    assert "request_envelope_policy" not in schema
    assert "composer" not in schema
    assert schema["business_adapter"]["operation"] == "audio.import"
    assert schema["business_adapter"]["legacy_shallow_composer_public"] is False
    assert schema["business_adapter"]["start"]["next_command"]["gateway_argv"] == [
        "draft-start",
        "audio.import",
    ]
    assert schema["business_adapter"]["start"]["copy_exactly"] is True
    assert schema["business_adapter"]["start"]["append_arguments"] == "forbidden"
    transport = schema["business_adapter"]["field_transport"]
    assert "switch_value" in transport["literal_fields"]
    assert transport["dedicated_declaration_parameters"] == {
        "switch_value": "--switch-value"
    }
    assert transport["generic_declaration_field_exclusions"] == ["switch_value"]
    assert transport["bound_object_handle_fields"] == ["output_bus"]
    assert transport["reference_value_rule"] == (
        "copy_one_bound_object_handle_never_a_path_or_name"
    )
    declaration = schema["business_adapter"]["declaration_discipline"]
    assert declaration["task_local_id"] == "bounded_unique_not_business_data"
    assert declaration["known_user_fields"] == "complete_on_first_submission"
    rows = {row["name"]: row for row in detail["operations"]}
    assert rows["audio.import"]["input_modes_by_version"] == {
        version: BUSINESS_DECLARATION_INPUT_MODE
        for version in ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
    }
    assert tab_schema["operation"]["input_mode"] == BUSINESS_DECLARATION_INPUT_MODE
    assert tab_schema["business_adapter"]["contract"] == (
        "waapi-skill.exact-artifact-business/v1"
    )
    assert "typed_operation" not in tab_schema
    assert "composer" not in tab_schema


def test_object_set_name_schema_exposes_only_closed_business_input(
    tmp_path: Path,
) -> None:
    code, schema = offline_execute(
        tmp_path,
        "--version",
        "2022.1",
        "operation-schema",
        "object.setName",
    )

    assert code == 0
    assert schema["operation"]["input_mode"] == BUSINESS_DECLARATION_INPUT_MODE
    assert "typed_operation" not in schema
    assert "composer" not in schema
    assert "request_contract" not in schema["operation"]
    assert "argument_contract" not in schema["operation"]
    adapter = schema["business_adapter"]
    assert adapter["contract"] == "waapi-skill.object-lifecycle-business/v1"
    assert adapter["operation"] == "object.setName"
    assert adapter["start"]["next_command"]["gateway_argv"] == [
        "draft-start",
        "object.setName",
    ]
    assert adapter["declaration"] == {
        "subcommand": "draft-declare-object-change",
        "required_fields": ["object_handle", "new_name"],
        "optional_fields": [],
        "field_types": {
            "object_handle": "bound_object_handle",
            "new_name": "string",
        },
    }
    assert set(adapter["gateway_derivations"]) >= {
        "closed_object_identity",
        "native_request",
        "continuation",
    }
    assert adapter["legacy_inline_typed_public"] is False


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize(
    "operation",
    (
        "object.copy",
        "object.delete",
        "object.move",
        "object.setName",
        "object.setNotes",
    ),
)
def test_every_object_lifecycle_schema_has_one_deep_business_continuation(
    tmp_path: Path,
    version: str,
    operation: str,
) -> None:
    code, schema = offline_execute(
        tmp_path / f"{version}-{operation}",
        "--version",
        version,
        "operation-schema",
        operation,
        version=version,
    )

    assert code == 0, schema
    assert schema["operation"]["input_mode"] == BUSINESS_DECLARATION_INPUT_MODE
    assert schema["business_adapter"]["operation"] == operation
    assert schema["business_adapter"]["version"] == version
    assert schema["business_adapter"]["start"]["next_command"]["gateway_argv"] == [
        "draft-start",
        operation,
    ]
    assert "typed_operation" not in schema
    assert "composer" not in schema
    assert "argument_contract" not in schema["operation"]
    assert "required_arguments" not in schema["operation"]
    assert "optional_arguments" not in schema["operation"]


def test_operation_inventory_does_not_republish_native_fields_for_business_lanes(
    tmp_path: Path,
) -> None:
    compact_code, compact = offline_execute(tmp_path, "operations")
    code, detail = offline_execute(tmp_path, "operations", "--detail")
    assert compact_code == 0, compact
    assert code == 0, detail
    compact_rows = {row["name"]: row for row in compact["operations"]}
    rows = {row["name"]: row for row in detail["operations"]}

    for operation in (
        "audio.import",
        "object.copy",
        "object.delete",
        "object.move",
        "object.setName",
        "object.setNotes",
        "object.setLinked",
        "object.setProperty",
        "object.setReference",
    ):
        compact_row = compact_rows[operation]
        assert compact_row["input_mode"] == BUSINESS_DECLARATION_INPUT_MODE
        assert compact_row["next_command"] == ["operation-schema", operation]
        assert "required_arguments" not in compact_row
        assert "optional_arguments" not in compact_row
        row = rows[operation]
        assert set(row["input_modes_by_version"].values()) == {
            BUSINESS_DECLARATION_INPUT_MODE
        }
        assert set(row["business_contracts_by_version"]) == set(
            row["supported_versions"]
        )
        assert "argument_contract" not in row
        assert "required_arguments" not in row
        assert "optional_arguments" not in row


def test_object_set_name_draft_start_returns_only_business_continuation(
    tmp_path: Path,
) -> None:
    code, started = offline_execute(
        tmp_path,
        "--state-dir",
        str(tmp_path / "state"),
        "--version",
        "2022.1",
        "draft-start",
        "object.setName",
    )

    assert code == 0, started
    binding = started["draft"]["next_action_binding"]
    assert binding["required_next_phase"] == "bind_existing_business_object"
    assert binding["business_contract"]["operation"] == "object.setName"
    assert binding["object_binding"]["result"] == (
        "copy_the_returned_bound_object.handle"
    )
    assert binding["object_binding"]["use_only_for"] == ["object"]
    assert "draft-apply" not in json.dumps(binding)
    assert "typed-operation" not in json.dumps(binding)


def test_object_set_business_draft_binds_unnamed_direct_child(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    code, started = offline_execute(
        tmp_path,
        "--state-dir",
        str(state_dir),
        "--version",
        "2022.1",
        "draft-start",
        "object.set",
    )
    assert code == 0, started
    action_row = {
        "id": OBJECT_GUID,
        "name": "",
        "type": "Action",
        "path": r"\Events\Default Work Unit\Play_Rain\[Play - Rain]",
    }
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project_row()],
            "ak.wwise.core.object.get": [{"return": [action_row]}],
        }
    )

    bind_code, bound = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-bind-object",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            "1",
            "--direct-child-type",
            "Action",
            "--parent-path-segment",
            "Events",
            "--parent-path-segment",
            "Default Work Unit",
            "--parent-path-segment",
            "Play_Rain",
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert bind_code == 0, bound
    object_get = next(call for call in client.calls if call[0] == "ak.wwise.core.object.get")
    assert object_get[1] == {
        "waql": (
            'from object "\\Events\\Default Work Unit\\Play_Rain" '
            'select children where type = "Action" take 2'
        )
    }
    assert bound["bound_object"]["type"] == "Action"
    assert bound["bound_object"]["name"] == ""
    assert bound["bound_object"]["handle"].startswith("boh1-")


def test_object_set_business_draft_binds_event_action_from_event_path(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    code, started = offline_execute(
        tmp_path,
        "--state-dir",
        str(state_dir),
        "--version",
        "2022.1",
        "draft-start",
        "object.set",
    )
    assert code == 0, started
    shortcut = started["draft"]["next_action_binding"]["object_binding"][
        "event_action_by_event_path_segments"
    ]
    assert shortcut["append_repeated"] == [
        "--event-action-of-path-segment",
        "<one-exact-event-path-segment-without-separators>",
    ]
    assert shortcut["gateway_owned_resolution"] == (
        "the_single_direct_Action_child_of_the_exact_Event"
    )
    action_row = {
        "id": OBJECT_GUID,
        "name": "",
        "type": "Action",
        "path": r"\Events\Default Work Unit\Play_Rain\[Play - Rain]",
    }
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project_row()],
            "ak.wwise.core.object.get": [{"return": [action_row]}],
        }
    )

    bind_code, bound = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-bind-object",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            "1",
            "--event-action-of-path-segment",
            "Events",
            "--event-action-of-path-segment",
            "Default Work Unit",
            "--event-action-of-path-segment",
            "Play_Rain",
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert bind_code == 0, bound
    object_get = next(call for call in client.calls if call[0] == "ak.wwise.core.object.get")
    assert object_get[1] == {
        "waql": (
            'from object "\\Events\\Default Work Unit\\Play_Rain" '
            'select children where type = "Action" take 2'
        )
    }
    assert bound["bound_object"]["type"] == "Action"
    assert bound["bound_object"]["name"] == ""


def test_object_set_name_business_draft_binds_declares_and_materializes(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    code, started = offline_execute(
        tmp_path,
        "--state-dir",
        str(state_dir),
        "--version",
        "2022.1",
        "draft-start",
        "object.setName",
    )
    assert code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    record_path = (
        state_dir / "operation-drafts-v1" / "records" / f"{draft_id}.json"
    )
    before_legacy = record_path.read_bytes()
    legacy_code, legacy = offline_execute(
        tmp_path,
        "--state-dir",
        str(state_dir),
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
    )
    assert legacy_code == 2
    assert "no longer accepts shallow draft-apply" in legacy["message"]
    assert record_path.read_bytes() == before_legacy
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project_row()],
            "ak.wwise.core.object.get": [{"return": [object_row()]}],
        }
    )

    bind_code, bound = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-bind-object",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "1",
            "--object-id",
            OBJECT_GUID,
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert bind_code == 0, bound
    handle = bound["bound_object"]["handle"]
    assert bound["draft"]["next_action_binding"]["required_next_phase"] == (
        "declare_complete_object_change"
    )

    declare_code, declared = offline_execute(
        tmp_path,
        "--state-dir",
        str(state_dir),
        "draft-declare-object-change",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "2",
        "--object-handle",
        handle,
        "--new-name",
        "新名称 & Rain",
    )
    assert declare_code == 0, declared
    assert declared["draft"]["next_action_binding"]["required_next_phase"] == (
        "check_complete_business_declaration"
    )
    before_stale = record_path.read_bytes()
    stale_code, stale = offline_execute(
        tmp_path,
        "--state-dir",
        str(state_dir),
        "draft-declare-object-change",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "2",
        "--object-handle",
        handle,
        "--new-name",
        "stale overwrite",
    )
    assert stale_code == 2
    assert stale["error_code"] == "OPERATION_DRAFT_REVISION_CONFLICT"
    assert record_path.read_bytes() == before_stale
    materialized = OperationDraftStore(state_dir).materialize_request(
        draft_id,
        task_authority=authority,
        expected_revision=3,
        schema_digest=waapi_gateway.operation_draft_schema_digest(
            "object.setName",
            "2022.1",
        ),
        composer_digest=operation_composer_digest(
            "object.setName",
            "2022.1",
        ),
    )
    assert materialized.request["arguments"] == {
        "object": {"kind": "id", "value": OBJECT_GUID},
        "value": "新名称 & Rain",
    }
    check_client = preview_client()
    check_code, checked = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-check",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "3",
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: check_client,
    )
    assert check_code == 0, json.dumps(checked, ensure_ascii=False)
    assert checked["draft"]["check"]["status"] == "passed"
    assert "--apply" not in checked["draft"]["next_action_binding"][
        "fixed_full_argv"
    ]
    preview_live = preview_client()
    preview_code, previewed = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "preview-from-draft",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "4",
            "--ttl",
            "300",
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: preview_live,
    )
    assert preview_code == 0, json.dumps(previewed, ensure_ascii=False)
    assert previewed["state"] == "awaiting_confirmation"
    assert previewed["change_requested"] is True
    assert previewed["executed"] is False
    assert previewed["agent_result"]["request"]["arguments"] == {
        "object": {"kind": "id", "value": OBJECT_GUID},
        "value": "新名称 & Rain",
    }
    assert all(
        uri != "ak.wwise.core.object.setName"
        for uri, _args, _options in preview_live.calls
    )


@pytest.mark.parametrize(
    ("operation", "declaration_tail", "verification_kind"),
    (
        (
            "object.copy",
            ("--parent-handle", "<parent>", "--name-conflict", "rename"),
            "copied-guid-under-parent",
        ),
        ("object.delete", (), "guid-absent"),
        (
            "object.move",
            ("--parent-handle", "<parent>", "--name-conflict", "rename"),
            "moved-guid-under-parent",
        ),
        (
            "object.setName",
            ("--new-name", "新名称 & Rain"),
            "same-guid-renamed",
        ),
        (
            "object.setNotes",
            ("--notes", 'line 1\n"quoted" & <tag>'),
            "same-guid-notes",
        ),
    ),
)
def test_every_object_lifecycle_adapter_reaches_immutable_preview_with_its_verifier(
    tmp_path: Path,
    operation: str,
    declaration_tail: tuple[str, ...],
    verification_kind: str,
) -> None:
    state_dir = tmp_path / "state"
    code, started = offline_execute(
        tmp_path,
        "--state-dir",
        str(state_dir),
        "--version",
        "2022.1",
        "draft-start",
        operation,
    )
    assert code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    client = ObjectLifecycleClient()

    def bind(object_id: str, expected_revision: int) -> tuple[str, dict[str, Any]]:
        bind_code, payload = waapi_gateway.execute_gateway(
            [
                "--state-dir",
                str(state_dir),
                "draft-bind-object",
                draft_id,
                "--task-authority",
                authority,
                "--expected-revision",
                str(expected_revision),
                "--object-id",
                object_id,
            ],
            env=gateway_env(tmp_path),
            client_factory=lambda _url: client,
        )
        assert bind_code == 0, payload
        return payload["bound_object"]["handle"], payload

    object_handle, bound = bind(OBJECT_GUID, started["draft"]["revision"])
    parent_handle: str | None = None
    if operation in {"object.copy", "object.move"}:
        parent_handle, bound = bind(PARENT_GUID, bound["draft"]["revision"])
    rendered_tail = tuple(
        parent_handle if value == "<parent>" else value
        for value in declaration_tail
    )
    declare_code, declared = offline_execute(
        tmp_path,
        "--state-dir",
        str(state_dir),
        "draft-declare-object-change",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        str(bound["draft"]["revision"]),
        "--object-handle",
        object_handle,
        *rendered_tail,
    )
    assert declare_code == 0, declared

    check_code, checked = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-check",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(declared["draft"]["revision"]),
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert check_code == 0, json.dumps(checked, ensure_ascii=False)
    assert checked["draft"]["check"]["status"] == "passed"
    assert "--apply" not in checked["draft"]["next_action_binding"][
        "fixed_full_argv"
    ]

    preview_code, previewed = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "preview-from-draft",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(checked["draft"]["revision"]),
            "--ttl",
            "300",
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert preview_code == 0, json.dumps(previewed, ensure_ascii=False)
    assert previewed["state"] == "awaiting_confirmation"
    assert previewed["executed"] is False
    artifact = TransactionStore(state_dir).load_preview(
        previewed["transaction_id"]
    ).artifact
    assert artifact["request"]["operation"] == operation
    assert artifact["prepared_operation"]["verification_plan"]["kind"] == (
        verification_kind
    )
    native_uri = describe_operation(operation).uri
    assert all(uri != native_uri for uri, _args, _options in client.calls)


def test_object_lifecycle_draft_check_rejects_stale_bound_identity(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    code, started = offline_execute(
        tmp_path,
        "--state-dir",
        str(state_dir),
        "--version",
        "2022.1",
        "draft-start",
        "object.setNotes",
    )
    assert code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    client = ObjectLifecycleClient()
    bind_code, bound = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-bind-object",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(started["draft"]["revision"]),
            "--object-id",
            OBJECT_GUID,
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert bind_code == 0, bound
    declare_code, declared = offline_execute(
        tmp_path,
        "--state-dir",
        str(state_dir),
        "draft-declare-object-change",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        str(bound["draft"]["revision"]),
        "--object-handle",
        bound["bound_object"]["handle"],
        "--notes",
        "after",
    )
    assert declare_code == 0, declared
    client.source["path"] = (
        r"\Actor-Mixer Hierarchy\Default Work Unit\MovedElsewhere"
    )

    check_code, rejected = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-check",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(declared["draft"]["revision"]),
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert check_code == 2
    assert rejected["error_code"] == "OBJECT_HANDLE_STALE"
    assert all(
        uri != "ak.wwise.core.object.setNotes"
        for uri, _args, _options in client.calls
    )


def test_structurally_distinct_adapters_share_one_public_lifecycle(
    tmp_path: Path,
) -> None:
    for operation in ("object.set", "object.create", "audio.import"):
        code, payload = offline_execute(
            tmp_path / operation.replace(".", "-"),
            "--version",
            "2022.1",
            "operation-schema",
            operation,
        )

        assert code == 0
        adapter = payload["business_adapter"]
        assert adapter["input_mode"] == BUSINESS_DECLARATION_INPUT_MODE
        assert adapter["start"]["next_command"]["gateway_argv"] == [
            "draft-start",
            operation,
        ]
        assert adapter["legacy_shallow_composer_public"] is False
        assert "composer" not in payload
def test_schema_input_mode_projection_is_isolated_by_exact_operation_key(
    tmp_path: Path,
) -> None:
    cases = (
        ("object.set", "2025.1", BUSINESS_DECLARATION_INPUT_MODE),
        ("object.setRTPC", "2025.1", BUSINESS_DECLARATION_INPUT_MODE),
        ("object.createPlugin", "2025.1", BUSINESS_DECLARATION_INPUT_MODE),
        ("lua.executeCoreInline", "2025.1", BUSINESS_DECLARATION_INPUT_MODE),
        ("lua.executeCoreFile", "2025.1", BUSINESS_DECLARATION_INPUT_MODE),
    )
    for operation, version, expected in cases:
        exit_code, payload = offline_execute(
            tmp_path,
            "--version",
            version,
            "operation-schema",
            operation,
            version=version,
        )

        assert exit_code == 0
        assert payload["operation"]["input_mode"] == expected
