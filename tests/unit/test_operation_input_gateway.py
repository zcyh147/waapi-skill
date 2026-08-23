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
    COMPOSER_INPUT_MODE,
    INTERNAL_CANONICAL_INPUT_MODE,
    OPERATION_INPUT_MODE_LANES,
    OPERATION_REQUEST_CONTRACT,
    OperationInputModeLane,
    describe_operation,
)
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


def test_inline_operation_schema_exposes_one_typed_continuation(tmp_path: Path) -> None:
    code, payload = offline_execute(
        tmp_path,
        "--version",
        "2025.1",
        "operation-schema",
        "object.setReference",
    )

    assert code == 0
    assert "request_envelope" not in payload
    assert payload["operation"]["input_mode"] == "inline_typed"
    assert payload["typed_operation"]["continuation"]["subcommand"] == "typed-operation"
    assert "request-json" not in json.dumps(payload["typed_operation"])


def test_generic_draft_start_requires_first_fact_batch_before_disclosure(
    tmp_path: Path,
) -> None:
    schema_code, schema = offline_execute(
        tmp_path,
        "operation-schema",
        "object.create",
        version="2021.1",
    )
    assert schema_code == 0, schema
    schema = json.loads(
        waapi_gateway.gateway_stdout_json_encoder(schema).encode(schema)
    )
    branch_table = schema["composer"]["top_level_fact_plan"][
        "branch_choice_handle_table"
    ]
    assert branch_table["columns"] == [
        "field_handle",
        "constant_field",
        "choices",
    ]
    assert branch_table["rows"][0] == [
        "trh1-04ddc827227ba0c5ff771edd",
        "kind",
        [
            ["id", "trh1-a5081819643837eefc0e55fb"],
            ["path", "trh1-29073152c568e1f82b5621b7"],
            ["exact-type-name", "trh1-022ff465c2cb2094f5442531"],
            ["direct-child", "trh1-9b6f1d5e8be362bdbfda1cf8"],
            ["scoped-name", "trh1-059c99da4210b53a0d7a5c4c"],
        ],
    ]
    code, payload = offline_execute(
        tmp_path,
        "--state-dir",
        str(tmp_path / "state"),
        "draft-start",
        "object.create",
        version="2021.1",
    )

    assert code == 0, payload
    binding = payload["draft"]["next_action_binding"]
    assert binding["required_next_phase"] == "typed_fact_batch"
    assert binding["fact_order_source"] == (
        "/operation-schema/composer/construction_order"
    )
    assert binding["first_batch_rule"] == (
        "submit the next 6 schema-ordered facts when available; otherwise "
        "submit every remaining fact before disclosure"
    )
    assert binding["branch_choice_rule"] == (
        "after choose, add required selected-branch constant and prompt-value "
        "facts before the next top-level fact"
    )
    assert binding["selected_branch_fact_completion"] == {
        "choose_only": "invalid",
        "same_batch_before_next_top_level_fact": True,
        "path_selector_exact_sequence": [
            "choose branch handle with the path choice handle",
            "set selected path choice kind handle to string path",
            "set selected path choice value handle to the exact business path",
        ],
        "exact_type_name_selector_exact_sequence": [
            "choose branch handle with the exact-type-name choice handle",
            "set selected choice kind handle to string exact-type-name",
            "set selected choice type handle to the exact business object type",
            "set selected choice name handle to the exact business object name",
        ],
        "copy_handles_from_operation_schema_exactly": True,
    }
    assert binding["dynamic_disclosure_before_first_fact"] == "invalid"
    disclosures = binding["root_dynamic_disclosure_commands"]
    assert disclosures["selection"] == (
        "first unsubmitted business-present root in schema order"
    )
    assert disclosures["activation_gate"] == {
        "source": "/draft/next_action_binding/next_phase_decision",
        "required_selected_candidate": "dynamic_disclosure",
        "while_remaining_top_level_fact_batch_is_selected": "do_not_execute_any_row",
    }
    children = next(
        row for row in disclosures["rows"] if row["name"] == "children"
    )
    assert children["business_value_pointer"] == "/args/children"
    assert children["argv_by_shape"]["object"] == [
        "request-array-item",
        "object.create",
        "--schema-digest",
        payload["draft"]["binding"]["schema_digest"],
        "--array-handle",
        children["field_handle"],
        "--index",
        "0",
        "--shape",
        "object",
    ]
    expected_disclosure_argv = [
        "python",
        str(waapi_gateway.GATEWAY_RUNNER_PATH),
        "gateway.py",
        *children["argv_by_shape"]["object"],
    ]
    assert children["copy_command_by_shape"]["object"] == (
        waapi_gateway.operation_draft_copy_command(expected_disclosure_argv)
    )
    assert children["copy_instruction"] == {
        "contract": "waapi-skill.operation-draft-command-copy-instruction/v1",
        "source_field": "copy_command_by_shape.object",
        "action": "execute_verbatim_as_one_shell_tool_call",
        "forbidden_transformations": [
            "reconstruct",
            "shorten",
            "normalize",
            "substitute_path_segments",
            "select_another_field",
        ],
    }
    assert disclosures["copy_selected_argv_exactly"] is True
    assert disclosures["copy_selected_command_exactly"] is True

    type_handle = next(
        field.handle
        for field in waapi_gateway.draft_operation_request_contract(
            "object.create", "2021.1"
        ).fields
        if field.parent_handle is None and field.name == "type"
    )
    apply_code, applied = offline_execute(
        tmp_path,
        "--state-dir",
        str(tmp_path / "state"),
        "draft-apply",
        payload["draft"]["draft_id"],
        "--task-authority",
        payload["task_authority"],
        "--expected-revision",
        "1",
        "--compact",
        "--facts",
        "--action",
        "add_typed_fact",
        "--fact-action",
        "set",
        "--field-handle",
        type_handle,
        "--value-type",
        "string",
        "--fact-value",
        "ActorMixer",
        version="2021.1",
    )
    assert apply_code == 0, applied
    assert applied["draft"]["next_action_binding"][
        "root_dynamic_disclosure_commands"
    ] == disclosures
    assert applied["draft"]["next_action_binding"][
        "prompt_fact_completion_guard"
    ] == {
        "schema_optional_is_not_evidence_of_prompt_absence": True,
        "account_for_every_prompt_present_scalar_array_item_and_map_entry": True,
        "copy_boolean_values_exactly": True,
        "infer_or_replace_prompt_values": "invalid",
    }
    assert applied["draft"]["agent_control"] == {
        "terminal": False,
        "required_outcome_before_reply": "preview_or_structured_refusal",
        "next": "follow_next_action_binding",
        "reply_or_claim_preview_now": "invalid",
    }
    public_payload = waapi_gateway.gateway_stdout_payload(applied)
    encoded = waapi_gateway.gateway_stdout_json_encoder(public_payload).encode(
        public_payload
    )
    assert '"completion_candidate"' not in encoded
    assert '"root_dynamic_disclosure_commands"' in encoded
    assert '"draft-apply"' in encoded[:4096]


def test_object_create_prioritizes_collision_policy_before_optional_containers(
    tmp_path: Path,
) -> None:
    code, payload = offline_execute(
        tmp_path,
        "operation-schema",
        "object.create",
        version="2023.1",
    )

    assert code == 0, payload
    rows = payload["composer"]["top_level_fact_plan"]["rows"]
    names = [row[1] for row in rows]
    assert names.index("on_name_conflict") < names.index("notes")
    assert names.index("on_name_conflict") < names.index("properties")


def test_typed_operation_materializes_exact_request_into_the_single_preview_ingress(
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

    assert code == 0, payload
    assert captured == [set_notes_request() | {"arguments": {**set_notes_request()["arguments"], "value": ""}}]
    assert payload["request"] == captured[0]


@pytest.mark.parametrize(
    "operation",
    ("switchContainer.addAssignment", "switchContainer.removeAssignment"),
)
def test_typed_switch_assignment_enters_the_single_preview_ingress(
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


def test_typed_definition_files_enters_the_single_preview_ingress(
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
    code, payload = waapi_gateway.execute_gateway(
        [
            "typed-operation", operation, "--schema-digest", digest, "--apply",
            "--file", definition, "--io-root", io_root,
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
            "arguments": {"files": [definition], "io_root": io_root},
        }
    ]
    assert payload["request"] == captured[0]


def test_typed_tab_import_enters_the_single_preview_ingress(
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
    code, payload = waapi_gateway.execute_gateway(
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

    assert code == 0, payload
    assert captured == [
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2022.1",
            "operation": operation,
            "arguments": {
                "import_file": source,
                "import_location": {"kind": "path", "value": location},
                "import_language": "SFX",
                "import_operation": "useExisting",
                "auto_add_to_source_control": True,
            },
        }
    ]
    assert payload["request"] == captured[0]


def _without_route_specific_schema_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(payload))
    result.pop("command", None)
    result.pop("compatibility", None)
    operation = result.get("operation")
    if isinstance(operation, dict):
        operation.pop("summary", None)
        operation.pop("selection_guidance", None)
    return result


def test_normal_object_set_schema_and_detail_expose_only_composer_input(
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
    assert schema["operation"]["input_mode"] == COMPOSER_INPUT_MODE
    assert "input_modes_by_version" not in schema["operation"]
    expected_modes = {
        "2022.1": COMPOSER_INPUT_MODE,
        "2023.1": COMPOSER_INPUT_MODE,
        "2024.1": COMPOSER_INPUT_MODE,
        "2025.1": COMPOSER_INPUT_MODE,
    }
    rows = {row["name"]: row for row in detail["operations"]}
    assert rows["object.set"]["input_modes_by_version"] == expected_modes
    assert "input_mode" not in rows["object.set"]
    assert "request_envelope" not in schema
    assert "request_envelope_policy" not in schema
    assert schema["composer"]["contract"] == "waapi-skill.operation-composer/v1"
    assert schema["composer"]["action_shapes"]["add_target"] == {
        "fixed_fields": {
            "contract": "waapi-skill.operation-draft-action/v1",
            "action": "add_target",
        },
        "required_fields": ["selector"],
        "optional_fields": [
            "name",
            "notes",
            "platform",
            "list_mode",
            "on_name_conflict",
            "properties",
            "references",
        ],
    }
    assert schema["composer"]["flat_target_row_discipline"] == {
        "initial_action": "add_target",
        "prior_gateway_id": "opaque_exact_copy_only",
        "include_every_known_field": [
            "name",
            "notes",
            "platform",
            "list_mode",
            "on_name_conflict",
            "properties",
            "references",
        ],
        "split_initial_row_across_follow_up_actions": False,
        "follow_up_flat_actions": "corrections_only",
        "metadata_dependency_activation": (
            "agent_selects_only_requested_exact_tokens; Gateway validates and "
            "activates required dependency values"
        ),
        "unrequested_dependency_flags_are_not_action_fields": True,
        "reference_companion_fact_policy": {
            "submit_reference_only_when_that_is_the_user_fact": True,
            "reference_does_not_authorize_a_companion_property_fact": True,
            "gateway_owns_required_reference_activation": True,
            "output_bus_example": (
                "OutputBus does not authorize an OverrideOutput action field"
            ),
        },
        "selector_only_allowed_for": [
            "nested_children",
            "closed_lists",
            "embedded_import",
        ],
    }
    assert schema["composer"]["start"][
        "subcommand_after_preconditions"
    ] == "draft-start"
    assert schema["composer"]["start"][
        "gateway_argv_after_preconditions"
    ] == [
        "draft-start",
        "object.set",
    ]
    assert "required_sequence" not in schema["composer"]["start"]["preconditions"]
    assert schema["composer"]["start"]["preconditions"][
        "activation_decision"
    ]["when_skipped_continue_same_turn_with"] == "draft-start"
    assert schema["composer"]["start"]["preconditions"][
        "metadata_gateway_argv_template"
    ] == [
        "metadata",
        "discover",
        "--object-type",
        "<exact-shared-target-type>",
        "--query",
        "<requested-field-name>",
        "--limit",
        "<1..8>",
    ]
    assert schema["composer"]["start"]["preconditions"][
        "forbidden_scope_flags"
    ] == ["--object"]
    assert schema["composer"]["apply"]["gateway_argv"] == [
        "draft-apply",
        "<draft_id>",
        "--task-authority",
        "<task_authority>",
        "--expected-revision",
        "<revision>",
        "--compact",
        "--facts",
        "--action",
        "<action-name>",
        "<typed-fact-arguments>",
    ]
    assert len(
        json.dumps(
            schema,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ) < 32 * 1024
    assert schema["composer"]["apply"]["revision_discipline"] == {
        "mode": "one_ordered_atomic_batch_then_read",
        "action_count": {"minimum": 1, "maximum": 6},
        "batch_fill": {
            "mode": "greedy_schema_order",
            "rule": (
                "append the next complete handle-independent action while it "
                "fits; execute a shorter batch only when the next action "
                "depends on a returned handle or no action remains"
            ),
            "split_one_complete_action": "forbidden",
        },
        "repeat_complete_action_group": [
            "--action",
            "<action-name>",
            "<typed-fact-arguments>",
        ],
        "revision_delta": "action_count",
        "failure": "unchanged",
        "expected_revision_source": "/draft/revision",
        "next_action_template_source": (
            "/draft/next_action_binding/fixed_argv_prefix"
        ),
        "precompute_or_increment_revision": False,
    }
    assert schema["composer"]["completion_discipline"] == {
        "successful_action_response_is_complete": True,
        "compact_projection_is_not_truncation": True,
        "schema_required_fields_status_scope": (
            "structural_preview_readiness_only"
        ),
        "construction_boundary": {
            "phase": "preview_construction",
            "mutation": False,
            "complete": False,
            "required_terminal": "preview",
            "before": "continue_no_confirm_no_end",
        },
    }
    assert schema["composer"]["check"]["gateway_argv"] == [
        "draft-check",
        "<draft_id>",
        "--task-authority",
        "<task_authority>",
        "--expected-revision",
        "<revision>",
    ]
    assert schema["composer"]["seal"]["gateway_argv"] == [
        "preview-from-draft",
        "<draft_id>",
        "--task-authority",
        "<task_authority>",
        "--expected-revision",
        "<revision>",
        "--apply",
    ]
    assert "optional_apply_flag" not in schema["composer"]["seal"]
    assert schema["composer"]["cancel"]["gateway_argv"] == [
        "draft-cancel",
        "<draft_id>",
        "--task-authority",
        "<task_authority>",
        "--expected-revision",
        "<revision>",
    ]
    assert schema["composer"]["seal_subcommand"] == "preview-from-draft"
    assert "request_contract" not in schema["operation"]
    assert "argument_contract" not in schema["operation"]
    assert "required_arguments" not in schema["operation"]
    assert "optional_arguments" not in schema["operation"]
    assert "request_contract" not in rows["object.set"]
    assert "argument_contract" not in rows["object.set"]
    assert set(rows["object.set"]["composer_contracts_by_version"]) == set(
        expected_modes
    )
    assert "legacy-preview" not in json.dumps(schema)
    assert "legacy-operation-schema" not in json.dumps(schema)
    assert "legacy-preview" not in json.dumps(detail)
    assert "legacy-operation-schema" not in json.dumps(detail)


def test_normal_audio_import_schema_exposes_only_its_composer_input(
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
    assert schema["operation"]["input_mode"] == COMPOSER_INPUT_MODE
    assert "request_envelope" not in schema
    assert "request_envelope_policy" not in schema
    assert schema["composer"]["operation"] == "audio.import"
    assert schema["composer"]["start"][
        "gateway_argv_after_preconditions"
    ] == [
        "draft-start",
        "audio.import",
    ]
    action_argv = schema["composer"]["apply"]["action_argv"]
    assert "typed_fact_flags" not in schema["composer"]["apply"]
    assert action_argv["add_import_row"][:4] == [
        "--object-path",
        "PATH",
        "--object-type",
        "TYPE",
    ]
    assert "assign_import_row_switch" not in action_argv
    assert schema["composer"]["start"]["preconditions"] == {
        "metadata_gate": {
            "before_draft_start": (
                "required unless same-conversation metadata discover already "
                "covers every requested property/reference"
            ),
            "prompt_or_schema_names_are_live_evidence": False,
            "query_inventory": (
                "union shared and all rows, including one-row-only fields"
            ),
            "draft_start_before_gate": "invalid",
        },
        "agent_metadata_command_required": (
            "when_dynamic_token_is_not_already_exact_live_evidence"
        ),
        "workflow_control": {
            "metadata_success_is_terminal": False,
            "continue_same_turn_after_metadata": "draft-start",
            "reply_before_draft_start": "invalid",
        },
        "activation_decision": {
            "run_metadata_when": (
                "one_or_more_required_tokens_lack_prior_successful_live_result"
            ),
            "skip_metadata_when": (
                "every_required_token_has_prior_successful_live_result"
            ),
            "live_token_proof": "successful_metadata_discover_only",
            "when_skipped_continue_same_turn_with": "draft-start",
        },
        "metadata_query_batch": {
            "scope": "one exact object, class, or object-type scope",
            "reconcile_before_command": (
                "list every requested property/reference assignment across all "
                "rows, then require equal distinct checklist and --query counts; "
                "familiar one-row fields such as Volume and OutputBus still count"
            ),
            "first_request": (
                "include every distinct prompt-present dynamic property/reference "
                "token for this operation and scope"
            ),
            "row_field_inventory": (
                "include shared and every row-local dynamic property/reference, "
                "including scalar fields whose values differ by row"
            ),
            "one_to_eight_queries": "one metadata discover command",
            "split_within_limit": "invalid",
            "successful_complete_scope_result": "do_not_query_that_scope_again",
            "partial_fallback": (
                "one broader retry only when explicitly reported partial"
            ),
            "limit_by_query_count": {
                "1..2": 8,
                "3..4": 3,
                "5..8": 2,
            },
            "required_final_argv": [
                "--limit",
                "<derived-from-query-count>",
            ],
        },
        "submit_only_explicit_user_facts": True,
        "draft_check_revalidates_dynamic_metadata": True,
    }
    row_shape = schema["composer"]["action_shapes"]["add_import_row"]
    assert row_shape["required_fields"] == ["object_path", "assignment"]
    assert "assignment" not in row_shape["optional_fields"]
    assert row_shape["construction_discipline"] == schema["composer"][
        "flat_import_row_discipline"
    ]
    assert row_shape["construction_discipline"]["switch_assignment"] == {
        "required_in_initial_row_action": True,
        "ordinary_row": {"mode": "none"},
        "when_user_requested": {"mode": "switch", "value": "VALUE"},
        "applies_to": "this_row_object_path",
        "new_parent_or_container": "switch_when_user_assigns_that_object",
        "other_rows": "none_unless_user_assigns_that_row",
    }
    assert row_shape["user_fact_checklist"][
        "switch_assignment_value_only_when_explicit"
    ] is True
    assert "assign_import_row_switch" not in schema["composer"]["action_shapes"]
    assert "add_switch_assigned_import_row" not in schema["composer"]["action_shapes"]
    assert schema["composer"]["planning_discipline"]["dynamic_metadata"][
        "discovery_owner"
    ] == "agent_metadata_discover"
    assert schema["composer"]["planning_discipline"]["dynamic_metadata"][
        "validation_owner"
    ] == "gateway_draft_check"
    assert schema["composer"]["planning_discipline"]["dynamic_metadata"][
        "property_value_type"
    ] == {
        "source": "metadata.candidates[].metadata.typed_value_type",
        "copy_to": "--property NAME <typed_value_type> VALUE",
        "native_metadata_type_is_not_action_type": True,
    }
    assert schema["composer"]["planning_discipline"]["import_operation"] == {
        "source": "registry_fragments.request_options.import_operation",
        "action": "set_import_operation",
        "gateway_default": "createNew",
        "default_is_materialized_at": "draft-start",
        "action_required_only_for": ["useExisting", "replaceExisting"],
        "do_not_submit_redundant_default": True,
    }
    assert list(schema["composer"]).index(
        "flat_import_row_discipline"
    ) < list(schema["composer"]).index("action_shapes")
    assert schema["composer"]["flat_import_row_discipline"][
        "metadata_dependency_activation"
    ] == "agent_selects_exact_token_gateway_validates_dependencies"
    assert schema["composer"]["registry_fragments"][
        "metadata_dependency_closure"
    ]["materialization"]["supported_reference_activation"]["owner"] == (
        "gateway"
    )
    assert "request_contract" not in schema["operation"]
    assert "argument_contract" not in schema["operation"]

    rows = {row["name"]: row for row in detail["operations"]}
    assert rows["audio.import"]["input_modes_by_version"] == {
        version: COMPOSER_INPUT_MODE
        for version in ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
    }
    assert "request_contract" not in rows["audio.import"]
    assert set(rows["audio.import"]["composer_contracts_by_version"]) == {
        "2021.1",
        "2022.1",
        "2023.1",
        "2024.1",
        "2025.1",
    }
    assert tab_schema["operation"]["input_mode"] == "inline_typed"
    assert "request_envelope" not in tab_schema
    assert tab_schema["typed_operation"]["operation"] == "audio.importTabDelimited"
    tab_continuation = tab_schema["typed_operation"]["continuation"]
    assert tab_continuation["gateway_argv_prefix"][-1] == "--apply"
    assert tab_continuation["selector_argv"]["path"] == [
        "--import-location",
        "path",
        "<complete_wwise_path>",
    ]
    assert "composer" not in tab_schema
    normal_surfaces = json.dumps({"schema": schema, "detail": detail})
    assert "legacy-preview" not in normal_surfaces
    assert "legacy-operation-schema" not in normal_surfaces


def test_structurally_distinct_adapters_share_one_public_lifecycle(
    tmp_path: Path,
) -> None:
    projections: dict[str, dict[str, Any]] = {}
    for operation in ("object.set", "audio.import", "object.create"):
        code, payload = offline_execute(
            tmp_path / operation.replace(".", "-"),
            "--version",
            "2022.1",
            "operation-schema",
            operation,
        )
        assert code == 0
        projections[operation] = payload["composer"]

    create_dynamic = projections["object.create"]["dynamic_container_commands"]
    assert create_dynamic["draft_binding"] is False
    assert create_dynamic["array_item_argv"][:2] == [
        "request-array-item",
        "object.create",
    ]
    assert "never consumes or changes the Draft revision" in create_dynamic[
        "sequence"
    ]
    assert "required_sequence" not in projections["object.create"]["start"][
        "preconditions"
    ]
    assert projections["object.create"]["start"]["preconditions"][
        "activation_decision"
    ]["when_skipped_continue_same_turn_with"] == "draft-start"
    assert "fact-action map-put" in create_dynamic["scalar_map_entry_action"]

    shared_keys = {
        "contract",
        "action_contract",
        "action_construction",
        "composition_contract",
        "complete_request_is_never_an_action",
        "completion_discipline",
        "check",
        "seal",
        "cancel",
        "check_subcommand",
        "seal_subcommand",
        "cancel_subcommand",
        "complete_request_authored_by_gateway",
    }
    object_set = projections["object.set"]
    audio_import = projections["audio.import"]
    assert {key: object_set[key] for key in shared_keys} == {
        key: audio_import[key] for key in shared_keys
    }
    for composer in (object_set, audio_import):
        assert composer["apply"]["subcommand"] == "draft-apply"
        assert composer["apply"]["action_flag"] == "--action"
        assert composer["apply"]["scalar_types"] == [
            "string",
            "number",
            "integer",
            "boolean",
        ]
        assert composer["apply"]["scalar_type_discipline"] == {
            "cli_type_source": "scalar_types",
            "metadata_type_tokens_as_cli_types": "invalid",
            "metadata_examples": {"Real64": "number", "int16": "integer"},
        }
        assert composer["apply"]["selector_kinds"] == [
            "id-string VALUE",
            "id-integer VALUE",
            "path VALUE",
            "exact-type-name TYPE NAME",
            "direct-child TYPE PARENT_SELECTOR...",
            "scoped-name TYPE NAME PARENT_SELECTOR...",
        ]
        assert "action_argv" in composer["apply"]
        assert "typed_fact_flags" not in composer["apply"]
    assert "selector_kinds" not in projections["object.create"]["apply"]
    assert projections["object.create"]["apply"]["fact_action_argv"] == {
        "set": [
            "--fact-action",
            "set",
            "--field-handle",
            "HANDLE",
            "--value-type",
            "TYPE",
            "--fact-value",
            "VALUE",
        ],
        "append": [
            "--fact-action",
            "append",
            "--field-handle",
            "HANDLE",
            "--value-type",
            "TYPE",
            "--fact-value",
            "VALUE",
        ],
        "present": [
            "--fact-action",
            "present",
            "--field-handle",
            "HANDLE",
        ],
        "choose": [
            "--fact-action",
            "choose",
            "--field-handle",
            "HANDLE",
            "--fact-value",
            "CHOICE_HANDLE",
        ],
        "choose-dynamic": [
            "--fact-action",
            "choose-dynamic",
            "--field-handle",
            "HANDLE",
            "--key",
            "KEY",
            "--fact-value",
            "CHOICE_HANDLE",
        ],
        "map-put": [
            "--fact-action",
            "map-put",
            "--field-handle",
            "HANDLE",
            "--key",
            "KEY",
            "--value-type",
            "TYPE",
            "--fact-value",
            "VALUE",
        ],
    }
    assert "set_scalar" not in json.dumps(projections["object.create"]["apply"])
    assert object_set["start"][
        "subcommand_after_preconditions"
    ] == "draft-start"
    assert audio_import["start"][
        "subcommand_after_preconditions"
    ] == "draft-start"
    assert object_set["start"]["gateway_argv_after_preconditions"] == [
        "draft-start",
        "object.set",
    ]
    assert audio_import["start"]["gateway_argv_after_preconditions"] == [
        "draft-start",
        "audio.import",
    ]
    assert "required_sequence" not in object_set["start"]["preconditions"]
    assert "preconditions" in audio_import["start"]
    assert set(object_set["actions"]) != set(audio_import["actions"])


def test_schema_input_mode_projection_is_isolated_by_exact_operation_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import wwise_waapi.operation_registry as registry

    migrated_names = {"object.set"}
    monkeypatch.setattr(
        registry,
        "OPERATION_INPUT_MODE_LANES",
        tuple(
            OperationInputModeLane(
                operation=lane.operation,
                version=lane.version,
                input_mode=(
                    COMPOSER_INPUT_MODE
                    if lane.operation in migrated_names
                    else lane.input_mode
                ),
            )
            for lane in OPERATION_INPUT_MODE_LANES
        ),
    )

    cases = (
        ("object.set", "2025.1", COMPOSER_INPUT_MODE),
        ("object.setRTPC", "2025.1", COMPOSER_INPUT_MODE),
        ("object.createPlugin", "2025.1", COMPOSER_INPUT_MODE),
        ("lua.executeCoreInline", "2025.1", COMPOSER_INPUT_MODE),
        ("lua.executeCoreFile", "2025.1", COMPOSER_INPUT_MODE),
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
