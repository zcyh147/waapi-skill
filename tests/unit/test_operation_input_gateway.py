from __future__ import annotations

import copy
import importlib.util
import json
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.operation_registry import (  # pyright: ignore[reportMissingImports]
    COMPOSER_INPUT_MODE,
    LEGACY_JSON_INPUT_MODE,
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
        "path": "/project/SampleProject.wproj",
    }


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


def _without_route_specific_schema_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(payload))
    result.pop("command", None)
    result.pop("compatibility", None)
    operation = result.get("operation")
    if isinstance(operation, dict):
        operation.pop("summary", None)
        operation.pop("selection_guidance", None)
    invocation = result.get("request_envelope_policy", {}).get(
        "preview_invocation", {}
    )
    if isinstance(invocation, dict):
        intended = invocation.get("intended_change")
        if isinstance(intended, dict):
            intended.pop("subcommand", None)
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
    assert schema["request_envelope"] is None
    assert schema["request_envelope_policy"] == {
        "status": "composer_ready",
        "complete_request_authored_by_gateway": True,
    }
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
        "selector_only_allowed_for": [
            "nested_children",
            "closed_lists",
            "embedded_import",
        ],
    }
    assert schema["composer"]["start"] == {
        "subcommand": "draft-start",
        "gateway_argv": ["draft-start", "object.set"],
    }
    assert schema["composer"]["apply"]["gateway_argv"] == [
        "draft-apply",
        "<draft_id>",
        "--task-authority",
        "<task_authority>",
        "--expected-revision",
        "<revision>",
        "--compact",
        "--action-json",
        "<typed-action-json>",
    ]
    assert schema["composer"]["apply"]["revision_discipline"] == {
        "mode": "one_action_then_read_next_response",
        "expected_revision_source": "/draft/revision",
        "next_action_template_source": (
            "/draft/next_action_binding/fixed_full_argv_template"
        ),
        "replace_only": [
            "<task-authority-from-draft-start>",
            "<typed-action-json>",
        ],
        "precompute_or_increment_revision": False,
    }
    assert schema["composer"]["completion_discipline"] == {
        "successful_action_response_is_complete": True,
        "compact_projection_is_not_truncation": True,
        "schema_required_fields_status_scope": (
            "structural_preview_readiness_only"
        ),
        "user_intent_coverage": (
            "compare_planned_actions_before_draft-check"
        ),
        "draft_inspect_required_before_next_planned_action": False,
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
    assert schema["request_envelope"] is None
    assert schema["request_envelope_policy"] == {
        "status": "composer_ready",
        "complete_request_authored_by_gateway": True,
    }
    assert schema["composer"]["operation"] == "audio.import"
    assert schema["composer"]["start"]["gateway_argv"] == [
        "draft-start",
        "audio.import",
    ]
    assert schema["composer"]["start"]["preconditions"] == {
        "dynamic_metadata": {
            "fields": ["properties", "references"],
            "query_granularity": "one_successful_command_per_object_type",
            "all_required_tokens_share_that_result": True,
            "split_required_tokens_across_queries": False,
            "action_fields_source": "explicit_user_request_only",
            "unrequested_dependency_candidates": (
                "validation_only_do_not_copy_into_action"
            ),
            "complete_before": (
                "first-draft-apply-using-properties-or-references"
            ),
            "schema_and_metadata_may_swap": True,
            "draft_start_may_precede": True,
            "successful_result_survives_metadata_independent_actions": True,
            "repeat_successful_query": False,
        },
        "draft_start_may_precede": True,
        "metadata_independent_actions_may_precede": True,
        "successful_metadata_survives_metadata_independent_actions": True,
        "repeat_successful_metadata": False,
        "actions_using_properties_or_references_wait_for": [
            "dynamic_metadata"
        ],
        "failure_policy": "do_not_apply_dynamic_fields_then_backfill_metadata",
    }
    assert schema["composer"]["action_shapes"]["add_import_row"] == {
        "fixed_fields": {
            "contract": "waapi-skill.operation-draft-action/v1",
            "action": "add_import_row",
        },
        "required_fields": [],
        "optional_fields": [
            "audio_file",
            "audio_file_base64",
            "audio_source_notes",
            "dialogue_event",
            "event",
            "import_language",
            "import_location",
            "notes",
            "object_path",
            "object_type",
            "originals_subfolder",
            "properties",
            "references",
        ],
        "construction_discipline": {
            "initial_action_by_intent": {
                "row_with_switch_assignment": (
                    "add_switch_assigned_import_row"
                ),
                "ordinary_row": "add_import_row",
            },
            "select_initial_action_before_action_shape": True,
            "include_every_known_field": True,
            "same_action_fields": [
                "switch_assignment",
                "event",
                "properties",
                "references",
            ],
            "requested_switch_assignment_stays_on_initial_row": True,
            "split_initial_row_across_follow_up_actions": False,
            "follow_up_row_actions": "corrections_only",
            "metadata_dependency_activation": "gateway_owned_do_not_submit",
        },
        "user_fact_checklist": {
            "copy_every_explicit_fact_for_this_row": True,
            "copy_only_explicit_user_facts": True,
            "unrequested_dependency_candidates_are_not_action_fields": True,
            "batch_facts_apply_to_each_affected_row": True,
            "mixed_structure_and_media_defaults_are_not_safe": True,
            "media_row_examples": [
                "import_language",
                "object_type",
                "event",
                "properties",
                "references",
                "switch_assignment",
            ],
            "distinct_metadata_tokens_are_independent_facts": True,
            "requested_switch_assignment_is_not_a_later_action": True,
        },
    }
    assert schema["composer"]["action_shapes"][
        "add_switch_assigned_import_row"
    ] == {
        "fixed_fields": {
            "contract": "waapi-skill.operation-draft-action/v1",
            "action": "add_switch_assigned_import_row",
        },
        "required_fields": ["switch_assignment"],
        "optional_fields": [
            "audio_file",
            "audio_file_base64",
            "audio_source_notes",
            "dialogue_event",
            "event",
            "import_language",
            "import_location",
            "notes",
            "object_path",
            "object_type",
            "originals_subfolder",
            "properties",
            "references",
        ],
        "construction_discipline": schema["composer"][
            "flat_import_row_discipline"
        ],
        "user_fact_checklist": schema["composer"]["action_shapes"][
            "add_import_row"
        ]["user_fact_checklist"],
    }
    assert schema["composer"]["planning_discipline"][
        "dynamic_metadata"
    ] == {
        "fields": ["properties", "references"],
        "query_granularity": "one_successful_command_per_object_type",
        "all_required_tokens_share_that_result": True,
        "split_required_tokens_across_queries": False,
        "action_fields_source": "explicit_user_request_only",
        "unrequested_dependency_candidates": (
            "validation_only_do_not_copy_into_action"
        ),
        "complete_before": (
            "first-draft-apply-using-properties-or-references"
        ),
        "schema_and_metadata_may_swap": True,
        "draft_start_may_precede": True,
        "successful_result_survives_metadata_independent_actions": True,
        "repeat_successful_query": False,
    }
    assert schema["composer"]["planning_discipline"]["import_operation"] == {
        "source": "registry_fragments.request_options.import_operation",
        "action": "set_import_option",
        "gateway_default": "createNew",
        "default_is_materialized_at": "draft-start",
        "action_required_only_for": ["useExisting", "replaceExisting"],
        "do_not_submit_redundant_default": True,
    }
    assert schema["composer"]["action_shapes"]["add_import_row"][
        "construction_discipline"
    ] == schema["composer"]["flat_import_row_discipline"]
    assert list(schema["composer"]).index(
        "flat_import_row_discipline"
    ) < list(schema["composer"]).index("action_shapes")
    assert schema["composer"]["actions"].index(
        "add_switch_assigned_import_row"
    ) < schema["composer"]["actions"].index("add_import_row")
    assert schema["composer"]["action_shapes"]["add_import_row"][
        "user_fact_checklist"
    ] == {
        "copy_every_explicit_fact_for_this_row": True,
        "copy_only_explicit_user_facts": True,
        "unrequested_dependency_candidates_are_not_action_fields": True,
        "batch_facts_apply_to_each_affected_row": True,
        "mixed_structure_and_media_defaults_are_not_safe": True,
        "media_row_examples": [
            "import_language",
            "object_type",
            "event",
            "properties",
            "references",
            "switch_assignment",
        ],
        "distinct_metadata_tokens_are_independent_facts": True,
        "requested_switch_assignment_is_not_a_later_action": True,
    }
    assert schema["composer"]["flat_import_row_discipline"][
        "metadata_dependency_activation"
    ] == "gateway_owned_do_not_submit"
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
    assert tab_schema["operation"]["input_mode"] == LEGACY_JSON_INPUT_MODE
    assert tab_schema["request_envelope"]["operation"] == (
        "audio.importTabDelimited"
    )
    assert "composer" not in tab_schema

    normal_surfaces = json.dumps({"schema": schema, "detail": detail})
    assert "legacy-preview" not in normal_surfaces
    assert "legacy-operation-schema" not in normal_surfaces


def test_legacy_schema_is_explicit_deprecated_and_uses_the_same_registry_contract(
    tmp_path: Path,
) -> None:
    normal_code, normal = offline_execute(
        tmp_path,
        "--version",
        "2022.1",
        "operation-schema",
        "object.setNotes",
    )
    legacy_code, legacy = offline_execute(
        tmp_path,
        "--version",
        "2022.1",
        "legacy-operation-schema",
        "object.setNotes",
    )

    assert normal_code == legacy_code == 0
    assert legacy["compatibility"] == {
        "contract": "waapi-skill.legacy-operation-json-adapter/v1",
        "deprecation_status": "deprecated",
        "input_mode": LEGACY_JSON_INPUT_MODE,
        "submit_command": "legacy-preview",
    }
    assert legacy["operation"]["input_mode"] == LEGACY_JSON_INPUT_MODE
    assert {
        key: value
        for key, value in normal["operation"].items()
        if key not in {"summary", "selection_guidance"}
    } == legacy["operation"]
    assert legacy["request_envelope"] == normal["request_envelope"]
    assert legacy["request_envelope_policy"]["preview_invocation"][
        "intended_change"
    ]["subcommand"] == "legacy-preview"
    assert _without_route_specific_schema_fields(legacy) == (
        _without_route_specific_schema_fields(normal)
    )
    assert "\n" not in waapi_gateway.gateway_stdout_json_encoder(legacy).encode(
        legacy
    )


def test_object_set_legacy_schema_retains_only_the_explicit_compatibility_contract(
    tmp_path: Path,
) -> None:
    normal_code, normal = offline_execute(
        tmp_path,
        "--version",
        "2022.1",
        "operation-schema",
        "object.set",
    )
    legacy_code, legacy = offline_execute(
        tmp_path,
        "--version",
        "2022.1",
        "legacy-operation-schema",
        "object.set",
    )

    assert normal_code == legacy_code == 0
    assert normal["operation"]["input_mode"] == COMPOSER_INPUT_MODE
    assert normal["request_envelope"] is None
    assert "request_contract" not in normal["operation"]
    assert legacy["compatibility"]["input_mode"] == LEGACY_JSON_INPUT_MODE
    assert legacy["compatibility"]["submit_command"] == "legacy-preview"
    assert legacy["operation"]["input_mode"] == LEGACY_JSON_INPUT_MODE
    assert legacy["request_envelope"]["operation"] == "object.set"
    expected_operation = describe_operation("object.set").as_dict(version="2022.1")
    expected_operation.pop("summary", None)
    expected_operation.pop("selection_guidance", None)
    expected_operation["input_mode"] = LEGACY_JSON_INPUT_MODE
    assert legacy["operation"] == expected_operation


def test_all_legacy_operation_schemas_fit_the_existing_compact_output_budget(
    tmp_path: Path,
) -> None:
    for version in waapi_gateway.SUPPORTED_WWISE_VERSION_KEYS:
        for spec in waapi_gateway.list_operation_specs():
            exit_code, payload = offline_execute(
                tmp_path / version.replace(".", "-"),
                "--version",
                version,
                "legacy-operation-schema",
                spec.name,
                version=version,
            )
            encoded = (
                waapi_gateway.gateway_stdout_json_encoder(payload).encode(payload)
                + "\n"
            )

            assert exit_code == 0, (version, spec.name)
            assert len(encoded.encode("utf-8")) < 32 * 1024, (
                version,
                spec.name,
                len(encoded.encode("utf-8")),
            )


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
        ("object.setRTPC", "2025.1", LEGACY_JSON_INPUT_MODE),
        ("object.createPlugin", "2025.1", LEGACY_JSON_INPUT_MODE),
        ("lua.executeCoreInline", "2025.1", LEGACY_JSON_INPUT_MODE),
        ("lua.executeCoreFile", "2025.1", LEGACY_JSON_INPUT_MODE),
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


@pytest.mark.parametrize(
    ("operation", "version", "expected_status"),
    [
        ("object.copy", "2022.1", "unsupported_boundary"),
        ("object.set", "2021.1", "ok"),
    ],
)
def test_schema_routes_keep_unimplemented_and_unsupported_version_results_equivalent(
    tmp_path: Path,
    operation: str,
    version: str,
    expected_status: str,
) -> None:
    normal_code, normal = offline_execute(
        tmp_path,
        "--version",
        version,
        "operation-schema",
        operation,
        version=version,
    )
    legacy_code, legacy = offline_execute(
        tmp_path,
        "--version",
        version,
        "legacy-operation-schema",
        operation,
        version=version,
    )

    assert normal_code == legacy_code == 0
    assert normal["status"] == legacy["status"] == expected_status
    assert {
        key: value
        for key, value in normal["operation"].items()
        if key not in {"summary", "selection_guidance"}
    } == legacy["operation"]
    assert legacy["request_envelope"] == normal["request_envelope"]
    assert legacy["request_envelope_policy"]["status"] == normal[
        "request_envelope_policy"
    ]["status"]


def test_schema_routes_keep_unknown_operation_errors_equivalent(tmp_path: Path) -> None:
    normal_code, normal = offline_execute(
        tmp_path,
        "operation-schema",
        "missing.operation",
    )
    legacy_code, legacy = offline_execute(
        tmp_path,
        "legacy-operation-schema",
        "missing.operation",
    )

    assert normal_code == legacy_code == 2
    assert normal["error_code"] == legacy["error_code"] == "UNKNOWN_OPERATION"
    assert normal["message"] == legacy["message"]
    assert normal["details"] == legacy["details"]


@pytest.mark.parametrize(
    "document",
    [
        '{"contract":"first","contract":"second"}',
        json.dumps({"nested": [[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]}),
        json.dumps({"value": "x" * (384 * 1024)}),
    ],
    ids=("duplicate-key", "depth", "bytes"),
)
def test_preview_routes_share_duplicate_depth_and_byte_strict_json_rejection(
    tmp_path: Path,
    document: str,
) -> None:
    results: list[tuple[int, dict[str, Any]]] = []
    connections: list[str] = []
    for command in ("preview", "legacy-preview"):
        results.append(
            waapi_gateway.execute_gateway(
                [command, "--request-json", document],
                env=gateway_env(tmp_path),
                client_factory=lambda url: connections.append(url),
            )
        )

    assert connections == []
    assert results[0][0] == results[1][0] == 2
    assert results[0][1]["error_code"] == results[1][1]["error_code"]
    assert results[0][1]["message"] == results[1][1]["message"]


def test_legacy_preview_apply_uses_the_same_preconnection_policy_gate(
    tmp_path: Path,
) -> None:
    request_json = json.dumps(set_notes_request())
    results: list[tuple[int, dict[str, Any]]] = []
    connections: list[str] = []
    for command in ("preview", "legacy-preview"):
        results.append(
            waapi_gateway.execute_gateway(
                [command, "--apply", "--request-json", request_json],
                env=gateway_env(tmp_path, policy="read_only"),
                client_factory=lambda url: connections.append(url),
            )
        )

    assert connections == []
    assert results[0][0] == results[1][0] == 2
    assert results[0][1]["error_code"] == results[1][1]["error_code"]
    assert results[0][1]["message"] == results[1][1]["message"]


def test_preview_routes_share_transaction_timeout_and_live_dispatch_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[str, float]] = []

    def fake_dispatch_transaction_command(
        args: Any,
        *,
        connection: Any,
        common: Mapping[str, Any],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        observed.append((args.command, connection.timeout))
        return {"ok": True, "status": "ok", **dict(common)}

    monkeypatch.setattr(
        waapi_gateway,
        "dispatch_transaction_command",
        fake_dispatch_transaction_command,
    )
    request_json = json.dumps(set_notes_request())
    for command in ("preview", "legacy-preview"):
        client = FakeClient({"ak.wwise.core.getInfo": [live_info()]})
        exit_code, payload = waapi_gateway.execute_gateway(
            [command, "--request-json", request_json],
            env=gateway_env(tmp_path),
            client_factory=lambda _url, client=client: client,
        )

        assert exit_code == 0
        assert payload["command"] == command

    assert observed == [
        ("preview", waapi_gateway.DEFAULT_TRANSACTION_TIMEOUT),
        ("legacy-preview", waapi_gateway.DEFAULT_TRANSACTION_TIMEOUT),
    ]


def test_preview_and_legacy_preview_create_identical_canonical_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_builder = waapi_gateway.build_transaction_preview_artifact
    fixed_now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)

    def deterministic_builder(*args: Any, **kwargs: Any) -> Any:
        kwargs["now"] = fixed_now
        return original_builder(*args, **kwargs)

    monkeypatch.setattr(
        waapi_gateway,
        "build_transaction_preview_artifact",
        deterministic_builder,
    )
    request = set_notes_request()
    request_json = json.dumps(request, ensure_ascii=False)
    results: dict[str, tuple[dict[str, Any], dict[str, Any], FakeClient]] = {}
    for command in ("preview", "legacy-preview"):
        state_dir = tmp_path / command
        client = preview_client()
        exit_code, payload = waapi_gateway.execute_gateway(
            [
                "--state-dir",
                str(state_dir),
                command,
                "--request-json",
                request_json,
            ],
            env=gateway_env(tmp_path),
            client_factory=lambda _url, client=client: client,
        )
        assert exit_code == 0, payload
        artifact = TransactionStore(state_dir).load_preview(
            payload["transaction_id"]
        ).artifact
        results[command] = (payload, artifact, client)

    normal_payload, normal_artifact, normal_client = results["preview"]
    legacy_payload, legacy_artifact, legacy_client = results["legacy-preview"]
    assert normal_payload["artifact_hash"] == legacy_payload["artifact_hash"]
    assert normal_artifact == legacy_artifact
    assert normal_artifact["request"] == request
    assert normal_client.calls == legacy_client.calls


def test_legacy_preview_keeps_its_truthful_command_on_early_live_boundaries(
    tmp_path: Path,
) -> None:
    request_payload = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "ui.commands.execute",
        "arguments": {},
    }

    for command in ("preview", "legacy-preview"):
        client = FakeClient({"ak.wwise.core.getInfo": [live_info()]})
        exit_code, payload = waapi_gateway.execute_gateway(
            [command, "--request-json", json.dumps(request_payload)],
            env=gateway_env(tmp_path),
            client_factory=lambda _url, client=client: client,
        )

        assert exit_code == 2
        assert payload["error_code"] == "AUTHORING_HOST_REQUIRED"
        assert payload["command"] == command


def test_normal_preview_enforces_the_exact_operation_version_input_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import wwise_waapi.operation_registry as registry

    migrated_lanes = tuple(
        OperationInputModeLane(
            operation=lane.operation,
            version=lane.version,
            input_mode=(
                COMPOSER_INPUT_MODE
                if lane.operation == "object.setNotes" and lane.version == "2022.1"
                else lane.input_mode
            ),
        )
        for lane in OPERATION_INPUT_MODE_LANES
    )
    monkeypatch.setattr(registry, "OPERATION_INPUT_MODE_LANES", migrated_lanes)
    connections: list[str] = []

    exit_code, payload = waapi_gateway.execute_gateway(
        ["preview", "--request-json", json.dumps(set_notes_request())],
        env=gateway_env(tmp_path),
        client_factory=lambda url: connections.append(url),
    )

    assert exit_code == 2
    assert payload["error_code"] == "INPUT_MODE_MISMATCH"
    assert payload["details"] == {
        "operation": "object.setNotes",
        "version": "2022.1",
        "required_input_mode": COMPOSER_INPUT_MODE,
        "submitted_input_mode": LEGACY_JSON_INPUT_MODE,
    }
    assert connections == []

    state_dir = tmp_path / "legacy-after-migration"
    client = preview_client()
    legacy_code, legacy = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "legacy-preview",
            "--request-json",
            json.dumps(set_notes_request()),
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert legacy_code == 0, legacy
    stored = TransactionStore(state_dir).load_preview(legacy["transaction_id"])
    assert stored.artifact["request"] == set_notes_request()


def test_object_set_json_submission_requires_the_explicit_legacy_surface(
    tmp_path: Path,
) -> None:
    request = object_set_request()
    connections: list[str] = []

    normal_code, normal = waapi_gateway.execute_gateway(
        ["preview", "--request-json", json.dumps(request)],
        env=gateway_env(tmp_path),
        client_factory=lambda url: connections.append(url),
    )

    assert normal_code == 2
    assert normal["error_code"] == "INPUT_MODE_MISMATCH"
    assert normal["details"] == {
        "operation": "object.set",
        "version": "2022.1",
        "required_input_mode": COMPOSER_INPUT_MODE,
        "submitted_input_mode": LEGACY_JSON_INPUT_MODE,
    }
    assert connections == []

    state_dir = tmp_path / "object-set-legacy"
    client = preview_client()
    legacy_code, legacy = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "legacy-preview",
            "--request-json",
            json.dumps(request),
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert legacy_code == 0, legacy
    stored = TransactionStore(state_dir).load_preview(legacy["transaction_id"])
    assert stored.artifact["request"] == request


def test_audio_import_json_submission_requires_the_explicit_legacy_surface(
    tmp_path: Path,
) -> None:
    request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "audio.import",
        "arguments": {
            "imports": [
                {
                    "object_path": (
                        r"\Actor-Mixer Hierarchy\Default Work Unit\Target"
                    ),
                    "object_type": "Sound",
                }
            ]
        },
    }
    connections: list[str] = []

    exit_code, payload = waapi_gateway.execute_gateway(
        ["preview", "--request-json", json.dumps(request)],
        env=gateway_env(tmp_path),
        client_factory=lambda url: connections.append(url),
    )

    assert exit_code == 2
    assert payload["error_code"] == "INPUT_MODE_MISMATCH"
    assert payload["details"] == {
        "operation": "audio.import",
        "version": "2022.1",
        "required_input_mode": COMPOSER_INPUT_MODE,
        "submitted_input_mode": LEGACY_JSON_INPUT_MODE,
    }
    assert connections == []


@pytest.mark.parametrize(
    "request_payload",
    [
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2022.1",
            "operation": "object.copy",
            "arguments": {},
        },
        set_notes_request(version="2025.1"),
    ],
)
def test_preview_routes_keep_boundary_and_live_version_mismatch_errors_equivalent(
    tmp_path: Path,
    request_payload: Mapping[str, Any],
) -> None:
    results: list[tuple[int, dict[str, Any]]] = []
    for command in ("preview", "legacy-preview"):
        client = FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info()],
                "ak.wwise.core.getProjectInfo": [project_row()],
            }
        )
        results.append(
            waapi_gateway.execute_gateway(
                [
                    "--state-dir",
                    str(tmp_path / command),
                    command,
                    "--request-json",
                    json.dumps(request_payload),
                ],
                env=gateway_env(tmp_path),
                client_factory=lambda _url, client=client: client,
            )
        )

    assert results[0][0] == results[1][0] == 2
    assert results[0][1]["error_code"] == results[1][1]["error_code"]
    assert results[0][1]["message"] == results[1][1]["message"]
    assert results[0][1]["details"] == results[1][1]["details"]
