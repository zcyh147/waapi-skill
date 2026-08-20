from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest

from wwise_waapi.schema_inventory import load_definition_graph
from wwise_waapi.operation_composer import draft_operation_request_contract
from wwise_waapi.typed_requests import (
    compile_typed_request_contract,
    request_contract,
)


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "skills/waapi-skill/scripts/gateway.py"
SPEC = importlib.util.spec_from_file_location("waapi_gateway_complex_typed_tests", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)

VALIDATE_URI = "ak.wwise.debug.validateCall"
AUDIO_CONVERT_URI = "ak.wwise.core.audio.convert"
MEDIA_POOL_URI = "ak.wwise.core.mediaPool.get"


class FakeClient:
    def __init__(self, version: str) -> None:
        self.version = version
        self.calls: list[tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]] = []

    def call(self, uri: str, args=None, options=None):
        self.calls.append((uri, args, options))
        if uri == "ak.wwise.core.getInfo":
            year, major = (int(item) for item in self.version.split("."))
            return {"isCommandLine": False, "version": {"year": year, "major": major}}
        return {}

    def disconnect(self) -> None:
        pass


def _env(tmp_path: Path, version: str) -> dict[str, str]:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"wwise_version": version, "waapi_host": "127.0.0.1", "waapi_port": 31337}), encoding="utf-8")
    return {
        "WAAPI_SKILL_CONFIG_PATH": str(config),
        "WAAPI_SKILL_STATE_DIR": str(tmp_path / "state"),
        "WWISE_VERSION": version,
    }


def test_media_pool_schema_marks_scalar_array_items_as_append_facts(
    tmp_path: Path,
) -> None:
    exit_code, schema = gateway.execute_gateway(
        ["request-schema", MEDIA_POOL_URI],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("schema must be offline"),
    )

    assert exit_code == 0, schema
    databases = next(
        field for field in schema["fields"] if field["path"] == ["args", "databases"]
    )
    assert databases["fact_construction"] == {
        "nonempty_scalar_items": {
            "phase": "before_dynamic_disclosure",
            "fact_action": "append",
            "repeat_for_each_item": True,
        },
        "empty_array_only": {
            "phase": "before_dynamic_disclosure",
            "fact_action": "present",
            "must_not_accompany": ["append"],
        },
    }
    filters = next(
        field for field in schema["fields"] if field["path"] == ["args", "filters"]
    )
    plan = schema["top_level_fact_plan"]
    assert plan["business_fact_selection"] == (
        "submit only prompt-present values; omit absent defaults"
    )
    assert plan["business_pointer_source"] == (
        "this table's business_pointer column"
    )
    plan_rows = [
        dict(zip(plan["columns"], row, strict=True)) for row in plan["rows"]
    ]
    assert next(row for row in plan_rows if row["name"] == "filters")[
        "business_pointer"
    ] == "/args/filters"
    filter_row = next(row for row in plan["rows"] if row[1] == "filters")
    assert filter_row[0] == filters["handle"]
    assert filters["fact_construction"]["business_cardinality_authority"] == {
        "source": "current_business_request",
        "schema_does_not_require_another_item": True,
        "do_not_disclose_absent_index": True,
    }


def test_media_pool_dynamic_child_applies_parent_before_descendant_disclosure(
    tmp_path: Path,
) -> None:
    contract = request_contract("2025.1", MEDIA_POOL_URI)
    filters = next(field for field in contract.fields if field.name == "filters")

    exit_code, item = gateway.execute_gateway(
        [
            "--version", "2025.1", "request-array-item", MEDIA_POOL_URI,
            "--schema-digest", contract.schema_digest,
            "--array-handle", filters.handle,
            "--index", "0", "--shape", "object",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("disclosure must be offline"),
    )

    assert exit_code == 0, item
    assert item["construction_state"] == {
        "complete": False,
        "disclosure_replay_allowed": False,
        "next_phase": "apply_current_node_facts_then_continue_dynamic_disclosures",
        "completion_boundary": "draft-check",
        "construction_boundary": {
            "phase": "read_request_construction",
            "mutation": False,
            "complete": False,
            "required_terminal": "draft_check_result",
            "before": "continue_no_confirm_no_end",
        },
    }
    assert item["continuation"]["request_wide_order"] == {
        "phase": "node_local_disclosure_then_facts",
        "root_boundary": "finish_current_root_nodes_before_next_root",
        "traversal": "response_tree_preorder",
        "nested_member_order": "schema_property_order",
        "child_fact_order": "child_contract_schema_order",
        "deferred_fact_queue": {
            "traversal": "response_tree_preorder",
            "node_steps": [
                "deferred_parent_fact",
                "child_contract_facts",
                "then_descendant_response_nodes",
            ],
            "forbidden": [
                "descendant_fact_before_current_node_parent_or_child_facts",
                "next_outer_sibling_disclosure_before_current_root_facts",
                "one_fact_apply_batch_spanning_disclosed_nodes",
            ],
        },
        "this_handle_is_not_a_complete_request": True,
    }
    assert item["continuation"]["deferred_fact"]["argv"] == [
        "--action", "add_typed_fact", "--fact-action", "append",
        "--field-handle", filters.handle, "--value-type", "object",
        "--fact-value", item["handle"],
    ]
    assert item["continuation"]["draft_fact_execution"] == {
        "prefix_source": (
            "latest_draft_response.next_action_binding.fixed_argv_prefix"
        ),
        "batch_scope": "current_disclosed_node_only",
        "complete_action_groups_in_queue_order": True,
        "maximum_actions": 6,
        "count_each_literal_action_flag": True,
        "seventh_action": "stop_before_it_execute_first_six_then_read_response",
        "copy_returned_handles_exactly": True,
    }
    deferred_candidate = next(
        row
        for row in item["continuation"]["next_command_decision"][
            "evaluate_in_order"
        ]
        if row["candidate"] == "deferred_fact_queue"
    )
    assert deferred_candidate["batch_facts"] == (
        "current_disclosed_node_only_up_to_6_facts_in_queue_order"
    )
    assert deferred_candidate["first_fact_only"] == (
        "valid_only_when_current_node_has_no_other_business_facts"
    )
    assert item["child_contract"]["fact_literal_policy"] == {
        "copy_handles_and_choice_handles_exactly": True,
        "placeholder_or_added_punctuation": "invalid",
        "business_value_placeholders_must_be_replaced": True,
    }
    assert "branch_disclosure" not in item["continuation"]
    branch_choices = item["child_contract"]["branch_choices"]
    assert branch_choices
    assert [branch["key"] for branch in branch_choices] == [
        "type",
        "value",
        "field",
        "operator",
    ]
    assert [branch["queue_index"] for branch in branch_choices] == [1, 2, 3, 4]
    assert all(
        branch["fact_sequence"]
        == "choose_one_then_map_put_same_key_before_next_branch"
        and branch["next_branch_blocked_until_complete"] is True
        for branch in branch_choices
    )
    type_branch = next(row for row in branch_choices if row["key"] == "type")
    field_choice = next(
        choice
        for choice in type_branch["choices"]
        if choice.get("enum") == ["field"]
    )
    assert type_branch["fact_construction"]["choose_dynamic_argv"] == [
        "--action", "add_typed_fact", "--fact-action", "choose-dynamic",
        "--field-handle", item["handle"], "--fact-value",
        "<selected-choice-handle>", "--key", "type",
    ]
    assert type_branch["fact_construction"]["map_put_argv"] == [
        "--action", "add_typed_fact", "--fact-action", "map-put",
        "--field-handle", item["handle"], "--key", "type",
        "--value-type", "<selected-accepted-type>", "--fact-value",
        "<selected-choice-enum-or-business-value>",
    ]
    assert type_branch["fact_construction"]["execute_after"] == (
        "deferred_parent_fact"
    )
    assert type_branch["fact_construction"]["consume_each_fact_once"] is True
    assert type_branch["fact_construction"]["replay_allowed"] is False
    assert type_branch["fact_construction"]["queue_phase"] == "child_contract"
    assert type_branch["fact_construction"]["queue_order_ref"] == (
        "/continuation/request_wide_order/deferred_fact_queue"
    )
    assert "deferred_fact" not in field_choice
    assert "typed_fact" not in field_choice
    assert field_choice["map_put_required"] is True
    assert field_choice["map_put_value_source"] == "sole_enum"
    value_branch = next(row for row in branch_choices if row["key"] == "value")
    string_value = next(
        choice
        for choice in value_branch["choices"]
        if choice["accepted_types"] == ["string"]
    )
    assert string_value["map_put_required"] is True
    assert string_value["map_put_value_source"] == "business_value"
    assert item["continuation"]["deferred_fact"]["execute_after"] == (
        "current_container_disclosure"
    )
    assert item["continuation"]["deferred_fact"]["queue_phase"] == (
        "parent_response"
    )
    assert item["continuation"]["deferred_fact"]["must_precede"] == {
        "all_facts_with_field_handle": item["handle"],
        "reason": "attach_returned_handle_to_its_parent_first",
    }
    assert item["continuation"]["deferred_fact"]["queue_order_ref"] == (
        "/continuation/request_wide_order/deferred_fact_queue"
    )
    assert item["continuation"]["deferred_fact"]["is_next_command"] is False
    assert item["business_value_scope"] == {
        "current_value_pointer": "/args/filters/0",
        "outermost_disclosed_root_pointer": "/args/filters/0",
        "current_value_only": True,
        "unrelated_prompt_objects_do_not_satisfy_member_conditions": True,
    }
    assert item["continuation"]["business_sibling_transition"][
        "is_next_command"
    ] is False
    assert item["continuation"]["business_sibling_transition"][
        "business_value_pointer"
    ] == "/args/filters/1"
    assert item["continuation"]["business_sibling_transition"]["after"] == (
        "current_root_fact_apply_success"
    )
    assert next(iter(item["continuation"])) == "business_sibling_transition"
    assert item["continuation"]["root_fact_queue_anchor"][
        "first_fact_argv"
    ] == item["continuation"]["deferred_fact"]["argv"]
    assert [
        row["candidate"]
        for row in item["continuation"]["next_command_decision"][
            "evaluate_in_order"
        ]
    ] == ["deferred_fact_queue", "business_sibling_transition"]
    assert item["continuation"]["next_command_decision"][
        "draft_check_or_cancel_with_remaining_candidate_or_deferred_fact"
    ] == "invalid"
    assert item["continuation"]["next_command_decision"][
        "schema_members_are_not_business_facts"
    ] is True
    assert item["continuation"]["next_command_decision"][
        "candidate_without_its_exact_business_pointer"
    ] == "forbidden"
    assert "business_sibling_transition" not in item["continuation"][
        "deferred_fact"
    ].get("blocked_by", ())
    assert "deferred_action_argv" not in item["continuation"]


def test_media_pool_compact_draft_action_requires_read_result_not_preview(
    tmp_path: Path,
) -> None:
    contract = request_contract("2025.1", MEDIA_POOL_URI)
    databases = next(field for field in contract.fields if field.name == "databases")
    env = _env(tmp_path, "2025.1")
    start_code, started = gateway.execute_gateway(
        ["--version", "2025.1", "draft-start", MEDIA_POOL_URI],
        env=env,
        client_factory=lambda _url: pytest.fail("draft-start must be offline"),
    )
    assert start_code == 0, started

    apply_code, applied = gateway.execute_gateway(
        [
            "--version", "2025.1", "draft-apply",
            started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", "1", "--compact", "--facts",
            "--action", "add_typed_fact", "--fact-action", "append",
            "--field-handle", databases.handle,
            "--value-type", "string", "--fact-value", "\\Databases\\Project Originals",
        ],
        env=env,
        client_factory=lambda _url: pytest.fail("draft-apply must be offline"),
    )

    assert apply_code == 0, applied
    assert applied["draft"]["response_integrity"]["construction_boundary"] == {
        "phase": "read_request_construction",
        "mutation": False,
        "complete": False,
        "required_terminal": "draft_check_result",
        "before": "continue_no_confirm_no_end",
    }
    assert applied["draft"]["next_action_binding"]["fixed_argv_prefix"][6] == (
        started["task_authority"]
    )
    assert applied["draft"]["next_action_binding"]["completion_candidate"] == {
        "condition": (
            "all_current_business_request_facts_and_disclosures_submitted"
        ),
        "is_next_command_when_condition_true": True,
        "fixed_argv_prefix": [
            "python",
            str(gateway.GATEWAY_RUNNER_PATH),
            "gateway.py",
            "draft-check",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            "2",
        ],
        "allowed_suffix_source": "request_schema_terminal_arguments_only",
        "draft_apply_action_check": "invalid",
        "when_condition_false": (
            "continue_with_one_atomic_typed_action_batch_or_dynamic_disclosure"
        ),
    }


def test_media_pool_dynamic_child_stdout_is_complete_within_visible_budget(
    tmp_path: Path,
) -> None:
    """The public child disclosure must not rely on a truncated tool result."""

    contract = request_contract("2025.1", MEDIA_POOL_URI)
    filters = next(field for field in contract.fields if field.name == "filters")
    exit_code, item = gateway.execute_gateway(
        [
            "request-array-item", MEDIA_POOL_URI,
            "--schema-digest", contract.schema_digest,
            "--array-handle", filters.handle,
            "--index", "0", "--shape", "object",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("disclosure must be offline"),
    )

    assert exit_code == 0, item
    encoded = gateway.gateway_stdout_json_encoder(item).encode(item)
    assert len((encoded + "\n").encode("utf-8")) < 20 * 1024
    assert json.loads(encoded) == item
    assert gateway.gateway_stdout_json_encoder(item).indent is None


def test_dynamic_child_puts_the_next_action_before_the_schema_table(
    tmp_path: Path,
) -> None:
    """A tool-output prefix must carry control flow before optional schema detail."""

    contract = request_contract("2025.1", MEDIA_POOL_URI)
    filters = next(field for field in contract.fields if field.name == "filters")
    exit_code, item = gateway.execute_gateway(
        [
            "request-array-item", MEDIA_POOL_URI,
            "--schema-digest", contract.schema_digest,
            "--array-handle", filters.handle,
            "--index", "0", "--shape", "object",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("disclosure must be offline"),
    )

    assert exit_code == 0, item
    keys = tuple(item)
    assert keys.index("continuation") < keys.index("child_contract")
    encoded = gateway.gateway_stdout_json_encoder(item).encode(item)
    assert encoded.index('"continuation"') < encoded.index('"child_contract"')


def test_compact_dynamic_fact_receipt_keeps_disclosed_sequence_active(
    tmp_path: Path,
) -> None:
    contract = request_contract("2025.1", MEDIA_POOL_URI)
    filters = next(field for field in contract.fields if field.name == "filters")
    env = _env(tmp_path, "2025.1")
    start_code, started = gateway.execute_gateway(
        ["--version", "2025.1", "draft-start", MEDIA_POOL_URI],
        env=env,
        client_factory=lambda _url: pytest.fail("draft-start must be offline"),
    )
    assert start_code == 0, started
    item_code, item = gateway.execute_gateway(
        [
            "request-array-item", MEDIA_POOL_URI,
            "--schema-digest", contract.schema_digest,
            "--array-handle", filters.handle,
            "--index", "0", "--shape", "object",
        ],
        env=env,
        client_factory=lambda _url: pytest.fail("disclosure must be offline"),
    )
    assert item_code == 0, item
    type_branch = next(
        row for row in item["child_contract"]["branch_choices"]
        if row["key"] == "type"
    )
    field_choice = next(
        row for row in type_branch["choices"] if row.get("enum") == ["field"]
    )

    append_code, appended = gateway.execute_gateway(
        [
            "--version", "2025.1", "draft-apply",
            started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", "1", "--compact", "--facts",
            "--action", "add_typed_fact", "--fact-action", "append",
            "--field-handle", filters.handle, "--value-type", "object",
            "--fact-value", item["handle"],
        ],
        env=env,
        client_factory=lambda _url: pytest.fail("draft-apply must be offline"),
    )
    assert append_code == 0, appended
    assert appended["draft"]["action_result"]["construction_continuation"] == {
        "source": "most_recent_typed_container_handle_response",
        "response_was_complete_not_truncated": True,
        "current_handle": item["handle"],
        "completed_fact_action": "append",
        "next_rule": "continue_with_child_contract_facts_for_the_appended_value",
        "stop_cancel_or_claim_truncation_before_current_root_is_complete": "invalid",
    }
    assert "completion_candidate" not in appended["draft"]["next_action_binding"]

    choose_code, chosen = gateway.execute_gateway(
        [
            "--version", "2025.1", "draft-apply",
            started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", "2", "--compact", "--facts",
            "--action", "add_typed_fact", "--fact-action", "choose-dynamic",
            "--field-handle", item["handle"], "--key", "type",
            "--fact-value", field_choice["handle"],
        ],
        env=env,
        client_factory=lambda _url: pytest.fail("draft-apply must be offline"),
    )
    assert choose_code == 0, chosen
    assert chosen["draft"]["action_result"]["construction_continuation"] == {
        "source": "most_recent_typed_container_handle_response",
        "response_was_complete_not_truncated": True,
        "current_handle": item["handle"],
        "completed_fact_action": "choose-dynamic",
        "current_key": "type",
        "next_rule": "map_put_the_same_key_from_its_disclosed_choice",
        "stop_cancel_or_claim_truncation_before_current_root_is_complete": "invalid",
    }
    assert "completion_candidate" not in chosen["draft"]["next_action_binding"]

    put_code, put = gateway.execute_gateway(
        [
            "--version", "2025.1", "draft-apply",
            started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", "3", "--compact", "--facts",
            "--action", "add_typed_fact", "--fact-action", "map-put",
            "--field-handle", item["handle"], "--key", "type",
            "--value-type", "string", "--fact-value", "field",
        ],
        env=env,
        client_factory=lambda _url: pytest.fail("draft-apply must be offline"),
    )
    assert put_code == 0, put
    continuation = put["draft"]["action_result"]["construction_continuation"]
    assert continuation["response_was_complete_not_truncated"] is True
    assert continuation["current_handle"] == item["handle"]
    assert continuation["current_key"] == "type"
    assert continuation["next_rule"] == (
        "continue_with_the_next_business_present_child_contract_fact_in_queue_index_order"
    )
    assert "completion_candidate" not in put["draft"]["next_action_binding"]


def test_audio_convert_schema_forbids_present_with_nonempty_languages(
    tmp_path: Path,
) -> None:
    exit_code, schema = gateway.execute_gateway(
        ["request-schema", AUDIO_CONVERT_URI],
        env=_env(tmp_path, "2024.1"),
        client_factory=lambda _url: pytest.fail("schema must be offline"),
    )

    assert exit_code == 0, schema
    languages = next(
        field for field in schema["fields"] if field["path"] == ["args", "languages"]
    )
    assert languages["fact_construction"]["nonempty_scalar_items"] == {
        "phase": "before_dynamic_disclosure",
        "fact_action": "append",
        "repeat_for_each_item": True,
    }
    assert languages["fact_construction"]["empty_array_only"] == {
        "phase": "before_dynamic_disclosure",
        "fact_action": "present",
        "must_not_accompany": ["append"],
    }


@pytest.mark.parametrize("version", ("2024.1", "2025.1"))
def test_complex_tracer_uses_open_map_facts_and_existing_debug_dispatch(
    tmp_path: Path, version: str
) -> None:
    exit_code, schema = gateway.execute_gateway(
        ["request-schema", VALIDATE_URI],
        env=_env(tmp_path, version),
        client_factory=lambda _url: pytest.fail("schema must be offline"),
    )
    assert exit_code == 0
    handles = {
        field["name"]: field["handle"]
        for field in schema["fields"]
        if "parent_handle" not in field
    }
    client = FakeClient(version)
    exit_code, payload = gateway.execute_gateway(
        [
            "typed-call", VALIDATE_URI,
            "--schema-digest", schema["schema_digest"],
            "--set", handles["id"], "string", "ak.wwise.core.getInfo",
            "--map-put", handles["args"], "sentinel", "integer", "42",
            "--map-correct", handles["args"], "sentinel", "integer", "43",
            "--map-put", handles["args"], "removed", "null", "null",
            "--map-remove", handles["args"], "removed",
        ],
        env=_env(tmp_path, version),
        client_factory=lambda _url: client,
    )
    assert exit_code == 0
    assert payload["agent_result"] == {
        "validated_api": "ak.wwise.core.getInfo",
        "supplied_sections": ["args"],
        "accepted_by_wwise": True,
    }
    assert list(payload)[-1] == "agent_result"
    assert client.calls[-1] == (
        VALIDATE_URI,
        {"id": "ak.wwise.core.getInfo", "args": {"sentinel": 43}},
        {},
    )


def test_complex_tracer_is_unavailable_before_2024_without_connection(tmp_path: Path) -> None:
    exit_code, payload = gateway.execute_gateway(
        ["request-schema", VALIDATE_URI],
        env=_env(tmp_path, "2023.1"),
        client_factory=lambda _url: pytest.fail("unsupported discovery must be offline"),
    )
    assert exit_code == 2
    assert payload["ok"] is False


def test_open_map_container_handle_is_gateway_issued_and_version_bound(tmp_path: Path) -> None:
    exit_code, schema = gateway.execute_gateway(
        ["request-schema", VALIDATE_URI],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("schema must be offline"),
    )
    assert exit_code == 0
    args_handle = next(
        field["handle"] for field in schema["fields"] if field["name"] == "args"
    )

    exit_code, payload = gateway.execute_gateway(
        [
            "request-map-container", VALIDATE_URI,
            "--schema-digest", schema["schema_digest"],
            "--map-handle", args_handle,
            "--key", "nested",
            "--shape", "object",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("handle issuance must be offline"),
    )
    assert exit_code == 0
    assert payload["handle"].startswith("trm1-")
    assert payload["continuation"]["deferred_fact"]["argv"] == [
        "--map-put", args_handle, "nested", "object", payload["handle"]
    ]

    stale_code, stale = gateway.execute_gateway(
        [
            "request-map-container", VALIDATE_URI,
            "--schema-digest", schema["schema_digest"],
            "--map-handle", args_handle,
            "--key", "nested",
            "--shape", "object",
        ],
        env=_env(tmp_path, "2024.1"),
        client_factory=lambda _url: pytest.fail("stale handle must fail offline"),
    )
    assert stale_code == 2
    assert stale["ok"] is False

    nested_code, nested = gateway.execute_gateway(
        [
            "request-map-container", VALIDATE_URI,
            "--schema-digest", schema["schema_digest"],
            "--map-handle", payload["handle"],
            "--key", "items",
            "--shape", "array",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("nested handle issuance must be offline"),
    )
    assert nested_code == 0
    assert nested["parent_handle"] == payload["handle"]
    assert nested["handle"].startswith("trm1-")


def test_complex_schema_discloses_one_complete_non_json_continuation(tmp_path: Path) -> None:
    exit_code, schema = gateway.execute_gateway(
        ["request-schema", VALIDATE_URI],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("schema must be offline"),
    )
    assert exit_code == 0
    continuation = schema["continuation"]
    dynamic = continuation["dynamic_container_commands"]
    assert dynamic["map_value"] == "request-map-container"
    assert dynamic["array_item"] == "request-array-item"
    assert dynamic["draft_binding"] is False
    assert dynamic["map_value_argv"][:5] == [
        "request-map-container",
        VALIDATE_URI,
        "--schema-digest",
        schema["schema_digest"],
        "--map-handle",
    ]
    assert dynamic["array_item_argv"][:5] == [
        "request-array-item",
        VALIDATE_URI,
        "--schema-digest",
        schema["schema_digest"],
        "--array-handle",
    ]
    assert "--schema-digest" not in dynamic["nested_map_value_argv"]
    assert "--schema-digest" not in dynamic["nested_array_item_argv"]
    assert "--parent-schema-token" in dynamic["nested_map_value_argv"]
    assert "--parent-schema-token" in dynamic["nested_array_item_argv"]
    assert "nested_parent_argv" not in dynamic
    assert continuation["gateway_argv_prefix"] == [
        "typed-call",
        VALIDATE_URI,
        "--schema-digest",
        schema["schema_digest"],
    ]
    assert set(continuation["fact_flags"]) == {
        "scalar", "array_item", "container", "branch", "dynamic_branch", "map_put",
        "map_correct", "map_remove",
    }
    encoded = json.dumps(schema)
    assert "args-json" not in encoded
    assert "options-json" not in encoded
    assert "action-json" not in encoded


def test_isolated_typed_call_prefix_places_io_authority_before_every_fact(
    tmp_path: Path,
) -> None:
    exit_code, schema = gateway.execute_gateway(
        ["request-schema", AUDIO_CONVERT_URI],
        env=_env(tmp_path, "2024.1"),
        client_factory=lambda _url: pytest.fail("schema must be offline"),
    )
    assert exit_code == 0
    continuation = schema["continuation"]
    assert continuation["gateway_argv_prefix"] == [
        "typed-call",
        AUDIO_CONVERT_URI,
        "--schema-digest",
        schema["schema_digest"],
        "--apply",
        "--io-root",
        "<absolute-allowed-root>",
    ]
    assert continuation["apply"] is True
    assert "io_root_flag" not in continuation


def test_nested_container_handles_can_be_issued_before_one_atomic_typed_call(
    tmp_path: Path,
) -> None:
    exit_code, schema = gateway.execute_gateway(
        ["request-schema", VALIDATE_URI],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("schema must be offline"),
    )
    assert exit_code == 0
    handles = {
        field["name"]: field["handle"]
        for field in schema["fields"]
        if "parent_handle" not in field
    }
    _, object_handle = gateway.execute_gateway(
        [
            "request-map-container", VALIDATE_URI,
            "--schema-digest", schema["schema_digest"],
            "--map-handle", handles["args"],
            "--key", "nested", "--shape", "object",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("handle issuance must be offline"),
    )
    _, array_handle = gateway.execute_gateway(
        [
            "request-map-container", VALIDATE_URI,
            "--schema-digest", schema["schema_digest"],
            "--map-handle", object_handle["handle"],
            "--key", "items", "--shape", "array",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("handle issuance must be offline"),
    )
    client = FakeClient("2025.1")
    exit_code, _payload = gateway.execute_gateway(
        [
            "typed-call", VALIDATE_URI,
            "--schema-digest", schema["schema_digest"],
            "--set", handles["id"], "string", "ak.wwise.core.getInfo",
            # Child facts may arrive before their parents; the Gateway validates
            # the complete signed chain atomically before opening the transport.
            "--append", array_handle["handle"], "integer", "42",
            "--map-put", object_handle["handle"], "items", "array", array_handle["handle"],
            "--map-put", handles["args"], "nested", "object", object_handle["handle"],
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: client,
    )
    assert exit_code == 0
    assert client.calls[-1] == (
        VALIDATE_URI,
        {
            "id": "ak.wwise.core.getInfo",
            "args": {"nested": {"items": [42]}},
        },
        {},
    )


def test_array_item_handle_is_gateway_issued_and_schema_bound(tmp_path: Path) -> None:
    # The public command rejects an array handle from another exact schema
    # before any transport is opened.
    exit_code, schema = gateway.execute_gateway(
        ["request-schema", "ak.wwise.core.profiler.getVoiceContributions"],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("schema must be offline"),
    )
    assert exit_code == 0
    scalar_array = next(
        field["handle"] for field in schema["fields"] if field["name"] == "bussesPipelineID"
    )
    exit_code, payload = gateway.execute_gateway(
        [
            "request-array-item", "ak.wwise.core.profiler.getVoiceContributions",
            "--schema-digest", schema["schema_digest"],
            "--array-handle", scalar_array,
            "--index", "0",
            "--shape", "object",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("invalid handle request must be offline"),
    )
    assert exit_code == 2
    assert payload["ok"] is False


def test_dynamic_open_array_can_issue_and_materialize_nonempty_object_item(
    tmp_path: Path,
) -> None:
    exit_code, schema = gateway.execute_gateway(
        ["request-schema", VALIDATE_URI],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("schema must be offline"),
    )
    assert exit_code == 0
    handles = {field["name"]: field["handle"] for field in schema["fields"] if "parent_handle" not in field}
    _, array_payload = gateway.execute_gateway(
        [
            "request-map-container", VALIDATE_URI,
            "--schema-digest", schema["schema_digest"],
            "--map-handle", handles["args"],
            "--key", "items", "--shape", "array",
        ], env=_env(tmp_path, "2025.1"), client_factory=lambda _url: pytest.fail("offline")
    )
    _, object_payload = gateway.execute_gateway(
        [
            "request-array-item", VALIDATE_URI,
            "--schema-digest", schema["schema_digest"],
            "--array-handle", array_payload["handle"],
            "--index", "0", "--shape", "object",
        ], env=_env(tmp_path, "2025.1"), client_factory=lambda _url: pytest.fail("offline")
    )
    client = FakeClient("2025.1")
    exit_code, _ = gateway.execute_gateway(
        [
            "typed-call", VALIDATE_URI,
            "--schema-digest", schema["schema_digest"],
            "--set", handles["id"], "string", "ak.wwise.core.getInfo",
            "--map-put", object_payload["handle"], "x", "integer", "1",
            "--append", array_payload["handle"], "object", object_payload["handle"],
            "--map-put", handles["args"], "items", "array", array_payload["handle"],
        ], env=_env(tmp_path, "2025.1"), client_factory=lambda _url: client,
    )
    assert exit_code == 0
    assert client.calls[-1][1] == {
        "id": "ak.wwise.core.getInfo",
        "args": {"items": [{"x": 1}]},
    }


@pytest.mark.parametrize(
    "member_schema,member_key",
    (
        (
            {
                "type": "object",
                "additionalProperties": False,
                "patternProperties": {
                    "^x-": {"oneOf": [{"type": "integer"}, {"type": "string"}]}
                },
            },
            "x-value",
        ),
        (
            {
                "type": "object",
                "additionalProperties": {
                    "oneOf": [{"type": "integer"}, {"type": "string"}]
                },
            },
            "custom",
        ),
    ),
)
def test_gateway_discloses_opaque_choice_for_exact_dynamic_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    member_schema: dict[str, Any],
    member_key: str,
) -> None:
    contract = compile_typed_request_contract(
        version="2025.1",
        uri=VALIDATE_URI,
        schema={
            "argsSchema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "rows"],
                "properties": {
                    "id": {"type": "string"},
                    "rows": {
                        "type": "array",
                        "items": member_schema,
                    },
                },
            },
            "optionsSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {},
            },
        },
        graph=load_definition_graph("2025.1"),
    )
    monkeypatch.setattr(gateway, "request_contract", lambda _version, _api: contract)
    rows = next(field for field in contract.fields if field.name == "rows")

    code, initial = gateway.execute_gateway(
        [
            "request-array-item", VALIDATE_URI,
            "--schema-digest", contract.schema_digest,
            "--array-handle", rows.handle,
            "--index", "0",
            "--shape", "object",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("disclosure must be offline"),
    )
    assert code == 0, initial
    assert initial["child_contract"]["member_key_disclosure_required"] is True
    row_handle = initial["handle"]

    disclosed_command = [
        member_key if token == "<exact-key>" else token
        for token in initial["continuation"]["branch_disclosure"]
    ]
    code, disclosed = gateway.execute_gateway(
        disclosed_command,
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("disclosure must be offline"),
    )
    assert code == 0
    choices = disclosed["child_contract"]["branch_choices"][0]
    assert choices["key"] == member_key
    integer_choice = next(
        choice["handle"]
        for choice in choices["choices"]
        if choice["accepted_types"] == ["integer"]
    )
    assert integer_choice.startswith("trc1-")

    id_handle = next(field for field in contract.fields if field.name == "id").handle
    parser = gateway.build_parser()
    accepted = parser.parse_args(
        [
            "typed-call", VALIDATE_URI,
            "--schema-digest", contract.schema_digest,
            "--set", id_handle, "string", "ak.wwise.core.getInfo",
            "--append", rows.handle, "object", row_handle,
            "--choose-dynamic", row_handle, member_key, integer_choice,
            "--map-put", row_handle, member_key, "integer", "7",
        ]
    )
    gateway.preflight_typed_request_input(
        accepted,
        env=_env(tmp_path, "2025.1"),
    )
    assert accepted.typed_request.args == {
        "id": "ak.wwise.core.getInfo",
        "rows": [{member_key: 7}],
    }

    rejected_code, rejected = gateway.execute_gateway(
        [
            "typed-call", VALIDATE_URI,
            "--schema-digest", contract.schema_digest,
            "--set", id_handle, "string", "ak.wwise.core.getInfo",
            "--append", rows.handle, "object", row_handle,
            "--choose-dynamic", row_handle, member_key, "0",
            "--map-put", row_handle, member_key, "integer", "7",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("numeric choice must fail before transport"),
    )
    assert rejected_code == 2
    assert rejected["ok"] is False


def test_nested_dynamic_lineage_discloses_deep_opaque_choice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = compile_typed_request_contract(
        version="2025.1",
        uri=VALIDATE_URI,
        schema={
            "argsSchema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "matrix"],
                "properties": {
                    "id": {"type": "string"},
                    "matrix": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["v"],
                                "properties": {
                                    "v": {
                                        "oneOf": [
                                            {"type": "integer"},
                                            {"type": "string"},
                                        ]
                                    }
                                },
                            },
                        },
                    },
                },
            },
            "optionsSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {},
            },
        },
        graph=load_definition_graph("2025.1"),
    )
    monkeypatch.setattr(gateway, "request_contract", lambda _version, _api: contract)
    matrix = next(field for field in contract.fields if field.name == "matrix")

    code, inner = gateway.execute_gateway(
        [
            "request-array-item", VALIDATE_URI,
            "--schema-digest", contract.schema_digest,
            "--array-handle", matrix.handle,
            "--index", "0", "--shape", "array",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("offline"),
    )
    assert code == 0
    code, row = gateway.execute_gateway(
        [
            "request-array-item", VALIDATE_URI,
            "--schema-digest", contract.schema_digest,
            "--array-handle", inner["handle"],
            "--index", "0", "--shape", "object",
            "--member-key", "v",
            "--parent-schema-token", inner["schema_lineage_token"],
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("offline"),
    )
    assert code == 0
    choices = row["child_contract"]["branch_choices"][0]["choices"]
    integer_choice = next(
        choice["handle"]
        for choice in choices
        if choice["accepted_types"] == ["integer"]
    )
    assert integer_choice.startswith("trc1-")

    id_handle = next(field for field in contract.fields if field.name == "id").handle
    parsed = gateway.build_parser().parse_args(
        [
            "typed-call", VALIDATE_URI,
            "--schema-digest", contract.schema_digest,
            "--set", id_handle, "string", "ak.wwise.core.getInfo",
            "--append", matrix.handle, "array", inner["handle"],
            "--append", inner["handle"], "object", row["handle"],
            "--choose-dynamic", row["handle"], "v", integer_choice,
            "--map-put", row["handle"], "v", "integer", "1",
        ]
    )
    gateway.preflight_typed_request_input(parsed, env=_env(tmp_path, "2025.1"))
    assert parsed.typed_request.args == {
        "id": "ak.wwise.core.getInfo",
        "matrix": [[{"v": 1}]],
    }


def test_anchored_regex_requires_exact_member_key_disclosure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = compile_typed_request_contract(
        version="2025.1",
        uri=VALIDATE_URI,
        schema={
            "argsSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "rows": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "patternProperties": {
                                "^x-[a-z]+$": {
                                    "oneOf": [
                                        {"type": "integer"},
                                        {"type": "string"},
                                    ]
                                }
                            },
                        },
                    }
                },
            },
            "optionsSchema": {
                "type": "object", "additionalProperties": False, "properties": {}
            },
        },
        graph=load_definition_graph("2025.1"),
    )
    monkeypatch.setattr(gateway, "request_contract", lambda _version, _api: contract)
    rows = next(field for field in contract.fields if field.name == "rows")
    code, payload = gateway.execute_gateway(
        [
            "request-array-item", VALIDATE_URI,
            "--schema-digest", contract.schema_digest,
            "--array-handle", rows.handle,
            "--index", "0", "--shape", "object",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("offline"),
    )
    assert code == 0
    assert payload["child_contract"]["branch_choices"] == []
    assert payload["child_contract"]["member_key_disclosure_required"] is True


def test_schema_lineage_token_cannot_invent_a_child_schema(
    tmp_path: Path,
) -> None:
    code, schema = gateway.execute_gateway(
        ["request-schema", VALIDATE_URI],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("offline"),
    )
    assert code == 0
    args_handle = next(
        field["handle"] for field in schema["fields"] if field["name"] == "args"
    )
    code, parent = gateway.execute_gateway(
        [
            "request-map-container", VALIDATE_URI,
            "--schema-digest", schema["schema_digest"],
            "--map-handle", args_handle,
            "--key", "nested", "--shape", "object",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("offline"),
    )
    assert code == 0
    token = parent["schema_lineage_token"]
    assert token.startswith("trl2-")
    assert len(token) < 96
    wrong_digest_code, wrong_digest = gateway.execute_gateway(
        [
            "request-map-container", VALIDATE_URI,
            "--schema-digest", "0" * 64,
            "--map-handle", parent["handle"],
            "--key", "child", "--shape", "object",
            "--parent-schema-token", token,
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("wrong digest must fail offline"),
    )
    assert wrong_digest_code == 2
    assert wrong_digest["ok"] is False

    root_without_digest_code, root_without_digest = gateway.execute_gateway(
        [
            "request-map-container", VALIDATE_URI,
            "--map-handle", args_handle,
            "--key", "nested", "--shape", "object",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("unbound root must fail offline"),
    )
    assert root_without_digest_code == 2
    assert root_without_digest["ok"] is False

    from base64 import urlsafe_b64decode, urlsafe_b64encode
    raw = token.removeprefix("trl2-")
    decoded = json.loads(
        urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8")
    )
    decoded[0][1] = "invented"
    forged = "trl2-" + urlsafe_b64encode(
        json.dumps(decoded, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).decode("ascii").rstrip("=")
    rejected_code, rejected = gateway.execute_gateway(
        [
            "request-map-container", VALIDATE_URI,
            "--schema-digest", schema["schema_digest"],
            "--map-handle", parent["handle"],
            "--key", "child", "--shape", "object",
            "--parent-schema-token", forged,
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("forgery must fail offline"),
    )
    assert rejected_code == 2
    assert rejected["ok"] is False

    stale_code, stale = gateway.execute_gateway(
        [
            "request-map-container", VALIDATE_URI,
            "--schema-digest", schema["schema_digest"],
            "--map-handle", parent["handle"],
            "--key", "child", "--shape", "object",
            "--parent-schema-token", token.replace("trl2-", "trl1-", 1),
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("stale token must fail offline"),
    )
    assert stale_code == 2
    assert stale["ok"] is False

    oversized_code, oversized = gateway.execute_gateway(
        [
            "request-map-container", VALIDATE_URI,
            "--schema-digest", schema["schema_digest"],
            "--map-handle", parent["handle"],
            "--key", "child", "--shape", "object",
            "--parent-schema-token", "trl2-" + "A" * (64 * 1024 * 2 + 1),
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("oversized token must fail offline"),
    )
    assert oversized_code == 2
    assert oversized["ok"] is False


def test_nested_options_local_reference_keeps_its_origin_section(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = compile_typed_request_contract(
        version="2025.1",
        uri=VALIDATE_URI,
        schema={
            "argsSchema": {
                "type": "object", "additionalProperties": False, "properties": {}
            },
            "optionsSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "matrix": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {"$ref": "#/definitions/row"},
                        },
                    }
                },
                "definitions": {
                    "row": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "v": {
                                "oneOf": [
                                    {"type": "integer"}, {"type": "string"}
                                ]
                            }
                        },
                    }
                },
            },
        },
        graph=load_definition_graph("2025.1"),
    )
    monkeypatch.setattr(gateway, "request_contract", lambda _version, _api: contract)
    matrix = next(field for field in contract.fields if field.name == "matrix")
    assert matrix.section == "options"
    code, inner = gateway.execute_gateway(
        [
            "request-array-item", VALIDATE_URI,
            "--schema-digest", contract.schema_digest,
            "--array-handle", matrix.handle,
            "--index", "0", "--shape", "array",
        ],
        env=_env(tmp_path, "2025.1"), client_factory=lambda _url: pytest.fail("offline"),
    )
    assert code == 0
    code, row = gateway.execute_gateway(
        [
            "request-array-item", VALIDATE_URI,
            "--schema-digest", contract.schema_digest,
            "--array-handle", inner["handle"],
            "--index", "0", "--shape", "object", "--member-key", "v",
            "--parent-schema-token", inner["schema_lineage_token"],
        ],
        env=_env(tmp_path, "2025.1"), client_factory=lambda _url: pytest.fail("offline"),
    )
    assert code == 0
    assert row["child_contract"]["branch_choices"][0]["key"] == "v"


def test_object_create_leaf_stdout_keeps_complete_facts_below_tool_ceiling(
    tmp_path: Path,
) -> None:
    contract = draft_operation_request_contract("object.create", "2021.1")
    children = next(
        field
        for field in contract.fields
        if field.path == ("children",) and field.shape == "array"
    )

    code, root = gateway.execute_gateway(
        [
            "--version", "2021.1", "request-array-item", "object.create",
            "--schema-digest", contract.schema_digest,
            "--array-handle", children.handle,
            "--index", "0", "--shape", "object",
        ],
        env=_env(tmp_path, "2021.1"),
        client_factory=lambda _url: pytest.fail("disclosure must be offline"),
    )
    assert code == 0, root
    root_projected = gateway.gateway_stdout_payload(root)
    root_encoded = gateway.gateway_stdout_json_encoder(root_projected).encode(
        root_projected
    )
    assert len((root_encoded + "\n").encode("utf-8")) < 7 * 1024
    assert "session_context" not in root_projected
    assert list(root_projected["continuation"])[:4] == [
        "next_command_decision",
        "root_fact_queue_anchor",
        "deferred_fact",
        "nested_container_disclosures",
    ]
    assert root_projected["continuation"]["root_fact_queue_anchor"] == root[
        "continuation"
    ]["root_fact_queue_anchor"]
    assert "request_wide_order" not in root_projected["continuation"]
    assert root_projected["continuation"]["next_command_decision"][
        "evaluate_in_order"
    ][0]["candidate"] == "deferred_fact_queue"
    child_array_argv = next(
        row["argv"]
        for row in root["continuation"]["nested_container_disclosures"]
        if row["key"] == "children"
    )
    code, child_array = gateway.execute_gateway(
        ["--version", "2021.1", *child_array_argv],
        env=_env(tmp_path, "2021.1"),
        client_factory=lambda _url: pytest.fail("disclosure must be offline"),
    )
    assert code == 0, child_array
    child_array_projected = gateway.gateway_stdout_payload(child_array)
    assert "root_fact_queue_anchor" not in child_array_projected["continuation"]
    assert child_array_projected["continuation"]["next_command_decision"][
        "evaluate_in_order"
    ][0]["first_command_pointer"] == "/continuation/deferred_fact/argv"
    assert child_array_projected["continuation"]["deferred_fact"][
        "complete_command_assembly"
    ] == {
        "fixed_argv_prefix_source": (
            "most_recent_successful_draft_action_response/"
            "draft/next_action_binding/fixed_argv_prefix"
        ),
        "append_this_fact_argv_exactly": True,
    }
    leaf_argv = [
        "0" if token == "<zero_based_business_present_index>" else token
        for token in child_array["continuation"]["next_item_disclosure"][
            "argv_by_shape"
        ]["object"]
    ]
    code, leaf = gateway.execute_gateway(
        ["--version", "2021.1", *leaf_argv],
        env=_env(tmp_path, "2021.1"),
        client_factory=lambda _url: pytest.fail("disclosure must be offline"),
    )
    assert code == 0, leaf

    projected = gateway.gateway_stdout_payload(leaf)
    encoded = gateway.gateway_stdout_json_encoder(projected).encode(projected)
    assert len((encoded + "\n").encode("utf-8")) < 10 * 1024
    assert projected["handle"] == leaf["handle"]
    assert projected["schema_lineage_token"] == leaf["schema_lineage_token"]
    assert projected["child_contract"]["fixed_scalar_member_fact_table"] == (
        leaf["child_contract"]["fixed_scalar_member_fact_table"]
    )
    assert projected["continuation"]["next_command_decision"][
        "evaluate_in_order"
    ][0]["first_command_pointer"] == (
        "/continuation/deferred_fact/argv"
    )
    assert "root_fact_queue_anchor" not in projected["continuation"]
    assert projected["continuation"]["next_command_decision"][
        "evaluate_in_order"
    ][0]["candidate"] == "deferred_fact_queue"
    assert list(projected["continuation"])[:5] == [
        "next_command_decision",
        "deferred_fact",
        "nested_container_disclosures",
        "business_sibling_transition",
        "subcommand",
    ]
    assert "--no-dynamic-descendants" not in encoded

    last_leaf_argv = [
        "1" if token == "<zero_based_business_present_index>" else token
        for token in child_array["continuation"]["next_item_disclosure"][
            "argv_by_shape"
        ]["object"]
    ]
    code, last_leaf = gateway.execute_gateway(
        ["--version", "2021.1", *last_leaf_argv],
        env=_env(tmp_path, "2021.1"),
        client_factory=lambda _url: pytest.fail("disclosure must be offline"),
    )
    assert code == 0, last_leaf
    last_projected = gateway.gateway_stdout_payload(last_leaf)
    last_decision = last_projected["continuation"]["next_command_decision"]
    assert last_decision["evaluate_in_order"][0]["first_command_pointer"] == (
        "/continuation/deferred_fact/argv"
    )
    assert "root_fact_queue_anchor" not in last_projected["continuation"]
    last_encoded = gateway.gateway_stdout_json_encoder(last_projected).encode(
        last_projected
    )
    assert '"root_fact_queue_anchor":{' not in last_encoded


def test_dynamic_container_schema_exposes_one_standard_argv_per_shape(
    tmp_path: Path,
) -> None:
    contract = draft_operation_request_contract("object.create", "2021.1")
    children = next(
        field
        for field in contract.fields
        if field.path == ("children",) and field.shape == "array"
    )

    code, payload = gateway.execute_gateway(
        [
            "--version",
            "2021.1",
            "request-array-item",
            "object.create",
            "--schema-digest",
            contract.schema_digest,
            "--array-handle",
            children.handle,
            "--index",
            "0",
            "--shape",
            "object",
        ],
        env=_env(tmp_path, "2021.1"),
        client_factory=lambda _url: pytest.fail("disclosure must be offline"),
    )

    assert code == 0, payload
    encoded = gateway.gateway_stdout_json_encoder(payload).encode(payload)
    assert "no_dynamic_descendants" not in encoded
    assert "--no-dynamic-descendants" not in encoded
