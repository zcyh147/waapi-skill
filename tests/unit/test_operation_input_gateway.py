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
    OPERATION_INPUT_MODE_LANES,
    OPERATION_REQUEST_CONTRACT,
    OperationInputModeLane,
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


def test_inline_mutation_continuation_requires_exact_prefix_before_business_fields(
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
    continuation = payload["typed_operation"]["continuation"]
    assert continuation["assembly_order"] == [
        "copy_every_gateway_argv_prefix_element_in_order",
        "append_each_business_field_as_separate_argv",
    ]
    assert continuation["gateway_argv_prefix_copy_policy"] == {
        "verbatim": True,
        "required_flag_included": "--apply",
        "omission_or_reordering": "invalid",
    }
    assert continuation["gateway_argv_prefix"][-1] == "--apply"


def test_inline_metadata_dependency_selects_exact_guid_for_one_existing_object(
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
    dependency = payload["typed_operation"]["metadata_dependency"]
    assert dependency["scope_selection"] == {
        "one_existing_object": {
            "flag": "--object",
            "value": "canonical_guid_from_prior_exact_read",
            "object_type_flag": "invalid",
        },
        "multiple_existing_objects_one_proven_type": {
            "flag": "--object-type",
            "value": "exact_shared_object_type",
        },
        "new_or_imported_object_type": {
            "flag": "--object-type",
            "value": "exact_object_type",
        },
        "path_value_for_object_flag": "invalid",
    }


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
    assert schema["business_adapter"]["start"]["gateway_argv"] == [
        "draft-start",
        "audio.import",
    ]
    assert schema["business_adapter"]["start"]["copy_exactly"] is True
    assert schema["business_adapter"]["start"]["append_arguments"] == "forbidden"
    transport = schema["business_adapter"]["field_transport"]
    assert "switch_value" in transport["literal_fields"]
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
    assert tab_schema["operation"]["input_mode"] == "inline_typed"
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
    assert adapter["start"]["gateway_argv"] == [
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
    assert schema["business_adapter"]["start"]["gateway_argv"] == [
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
    code, detail = offline_execute(tmp_path, "operations", "--detail")
    assert code == 0, detail
    rows = {row["name"]: row for row in detail["operations"]}

    for operation in (
        "object.copy",
        "object.delete",
        "object.move",
        "object.setName",
        "object.setNotes",
    ):
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
    assert checked["draft"]["next_action_binding"]["fixed_full_argv"][-1] == (
        "--apply"
    )
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
            "--apply",
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


def test_structurally_distinct_adapters_share_one_public_lifecycle(
    tmp_path: Path,
) -> None:
    projections: dict[str, dict[str, Any]] = {}
    for operation in ("object.set", "object.create"):
        code, payload = offline_execute(
            tmp_path / operation.replace(".", "-"),
            "--version",
            "2022.1",
            "operation-schema",
            operation,
        )
        assert code == 0
        projections[operation] = payload["composer"]

    audio_code, audio_payload = offline_execute(
        tmp_path / "audio-import",
        "--version",
        "2022.1",
        "operation-schema",
        "audio.import",
    )
    assert audio_code == 0
    assert audio_payload["business_adapter"]["input_mode"] == (
        BUSINESS_DECLARATION_INPUT_MODE
    )
    assert audio_payload["business_adapter"]["start"]["gateway_argv"] == [
        "draft-start",
        "audio.import",
    ]
    assert audio_payload["business_adapter"]["commands"][-2:] == [
        "draft-check",
        "preview-from-draft",
    ]
    assert "composer" not in audio_payload
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
