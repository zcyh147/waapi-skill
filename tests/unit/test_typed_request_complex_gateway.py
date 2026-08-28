from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest

from wwise_waapi.schema_inventory import load_definition_graph
from wwise_waapi.operation_composer import draft_operation_request_contract
from wwise_waapi.typed_operations import TypedOperationInputError
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

AUDIO_CONVERT_URI = "ak.wwise.core.audio.convert"
MEDIA_POOL_URI = "ak.wwise.core.mediaPool.get"
SYNTHETIC_URI = MEDIA_POOL_URI


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
        "complete_command_formula": [
            "copy_every_prefix_argv_from_prefix_source",
            "append_current_node_deferred_parent_fact_when_present",
            "append_every_business_present_child_contract_fact_in_schema_order",
            "execute_once_as_one_shell_tool_call",
        ],
        "runner_only_or_prefix_only_command": "invalid",
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
    assert item["child_contract"]["branch_fact_group_policy"] == {
        "actions": ["choose_dynamic_argv", "map_put_argv"],
        "group_size": 2,
        "split_across_apply_batches": "forbidden",
        "insufficient_remaining_slots": "start_group_in_next_batch",
        "greedy_batching": {
            "parent_fact_action_count": 1,
            "maximum_groups_with_parent_fact": 2,
            "maximum_groups_without_parent_fact": 3,
            "exact_group_count": (
                "with the parent fact use min(2,business-present queued groups); "
                "without it use min(3,remaining business-present queued groups)"
            ),
            "early_execute_with_a_business_present_group_unpacked": "invalid",
            "rule": (
                "start with the deferred parent fact, append exactly the next up "
                "to two business-present complete branch groups, execute, read the "
                "new revision, then pack exactly the next up to three remaining "
                "business-present complete groups per later batch"
            ),
        },
    }
    assert gateway.gateway_stdout_payload(item)["child_contract"][
        "branch_fact_group_policy"
    ] == item["child_contract"]["branch_fact_group_policy"]
    assert [
        (
            branch["key"],
            branch["business_value_pointer"],
            branch["condition"],
        )
        for branch in branch_choices
    ] == [
        ("type", "/args/filters/0/type", "current_business_request_contains_member"),
        ("value", "/args/filters/0/value", "current_business_request_contains_member"),
        ("field", "/args/filters/0/field", "current_business_request_contains_member"),
        ("operator", "/args/filters/0/operator", "current_business_request_contains_member"),
    ]
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
    completion = applied["draft"]["next_action_binding"]["completion_candidate"]
    completion_argv = [
        "python",
        str(gateway.GATEWAY_RUNNER_PATH),
        "gateway.py",
        "draft-check",
        started["draft"]["draft_id"],
        "--task-authority",
        started["task_authority"],
        "--expected-revision",
        "2",
    ]
    assert completion == {
        "condition": (
            "all_current_business_request_facts_and_disclosures_submitted"
        ),
        "business_completion_check": {
            "source": "current_user_business_request",
            "schema_required_fields_complete_is_insufficient": True,
            "all_user_present_optional_map_and_constant_facts_required": True,
            "exact_values_and_object_types_required": True,
        },
        "is_next_command_when_condition_true": True,
        "fixed_argv_prefix": completion_argv,
        "copy_exactly": True,
        "copy_instruction": {
            "contract": (
                "waapi-skill.operation-draft-command-copy-instruction/v1"
            ),
            "source_field": "copy_command",
            "action": "execute_verbatim_as_one_shell_tool_call",
            "forbidden_transformations": [
                "reconstruct",
                "shorten",
                "normalize",
                "substitute_path_segments",
                "select_another_field",
            ],
        },
        "copy_command": gateway.operation_draft_copy_command(completion_argv),
        "allowed_suffix_source": "request_schema_terminal_arguments_only",
        "request_schema_terminal_arguments": {
            "source_pointer": "/request-schema/result_filter",
            "append_before_execute": True,
            "contract": contract.as_gateway_payload()["result_filter"],
        },
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


def test_audio_convert_business_schema_requires_complete_language_collection(
    tmp_path: Path,
) -> None:
    exit_code, schema = gateway.execute_gateway(
        ["request-schema", AUDIO_CONVERT_URI],
        env=_env(tmp_path, "2024.1"),
        client_factory=lambda _url: pytest.fail("schema must be offline"),
    )

    assert exit_code == 0, schema
    declaration = schema["business_adapter"]["declaration"]
    assert "languages" in declaration["required_fields"]
    assert declaration["field_types"]["languages"] == "language_name_list"
    assert "fields" not in schema
    assert "schema_digest" not in schema


def test_audio_convert_business_draft_keeps_exact_io_authority_in_one_plan(
    tmp_path: Path,
) -> None:
    exit_code, schema = gateway.execute_gateway(
        ["request-schema", AUDIO_CONVERT_URI],
        env=_env(tmp_path, "2024.1"),
        client_factory=lambda _url: pytest.fail("schema must be offline"),
    )
    assert exit_code == 0
    continuation = schema["continuation"]
    assert continuation["gateway_argv"] == ["draft-start", AUDIO_CONVERT_URI]
    assert continuation["copy_exactly"] is True
    assert continuation["append_arguments"] == "forbidden"
    declaration = schema["business_adapter"]["declaration"]
    assert declaration["field_types"]["io_root"] == "exact_user_io_root"
    assert "typed-call" not in str(schema)


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
        uri=SYNTHETIC_URI,
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
            "request-array-item", SYNTHETIC_URI,
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


def test_nested_dynamic_lineage_discloses_deep_opaque_choice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = compile_typed_request_contract(
        version="2025.1",
        uri=SYNTHETIC_URI,
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
            "request-array-item", SYNTHETIC_URI,
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
            "request-array-item", SYNTHETIC_URI,
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


def test_anchored_regex_requires_exact_member_key_disclosure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = compile_typed_request_contract(
        version="2025.1",
        uri=SYNTHETIC_URI,
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
            "request-array-item", SYNTHETIC_URI,
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


def test_nested_options_local_reference_keeps_its_origin_section(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = compile_typed_request_contract(
        version="2025.1",
        uri=SYNTHETIC_URI,
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
            "request-array-item", SYNTHETIC_URI,
            "--schema-digest", contract.schema_digest,
            "--array-handle", matrix.handle,
            "--index", "0", "--shape", "array",
        ],
        env=_env(tmp_path, "2025.1"), client_factory=lambda _url: pytest.fail("offline"),
    )
    assert code == 0
    code, row = gateway.execute_gateway(
        [
            "request-array-item", SYNTHETIC_URI,
            "--schema-digest", contract.schema_digest,
            "--array-handle", inner["handle"],
            "--index", "0", "--shape", "object", "--member-key", "v",
            "--parent-schema-token", inner["schema_lineage_token"],
        ],
        env=_env(tmp_path, "2025.1"), client_factory=lambda _url: pytest.fail("offline"),
    )
    assert code == 0
    assert row["child_contract"]["branch_choices"][0]["key"] == "v"


def test_object_create_archive_typed_disclosure_is_not_public(
    tmp_path: Path,
) -> None:
    with pytest.raises(TypedOperationInputError):
        draft_operation_request_contract("object.create", "2021.1")

    code, root = gateway.execute_gateway(
        [
            "--version",
            "2021.1",
            "operation-schema",
            "object.create",
        ],
        env=_env(tmp_path, "2021.1"),
        client_factory=lambda _url: pytest.fail("disclosure must be offline"),
    )
    assert code == 0, root
    assert root["operation"]["input_mode"] == "business_declaration"
    assert "business_adapter" in root
    assert "composer" not in root
    return
    root_projected = gateway.gateway_stdout_payload(root)
    root_encoded = gateway.gateway_stdout_json_encoder(root_projected).encode(
        root_projected
    )
    assert len((root_encoded + "\n").encode("utf-8")) < 7 * 1024
    assert "session_context" not in root_projected
    assert root_projected["response_integrity"] == {
        "complete": True,
        "truncated": False,
    }
    assert root_projected["response_end"] == {
        "contract": "waapi-skill.gateway-response-end/v1",
        "marker": "WAAPI_TYPED_CONTAINER_RESPONSE_END",
        "complete": True,
        "truncated": False,
        "agent_action": "continue_same_turn",
    }
    assert list(root_projected)[-1] == "response_end"
    assert root_encoded.endswith(
        '"response_end":{"contract":"waapi-skill.gateway-response-end/v1",'
        '"marker":"WAAPI_TYPED_CONTAINER_RESPONSE_END","complete":true,'
        '"truncated":false,"agent_action":"continue_same_turn"}}'
    )
    assert root_encoded.index('"response_integrity":{') < root_encoded.index(
        '"continuation":{'
    ) < root_encoded.index('"child_contract":{')
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
    ][0]["command_key"] == "deferred_fact"
    assert child_array_projected["continuation"]["deferred_fact"][
        "complete_command_assembly"
    ] == {
        "fixed_argv_prefix_source": (
            "latest_draft_response.next_action_binding.fixed_argv_prefix"
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
    assert len((encoded + "\n").encode("utf-8")) < 4 * 1024
    assert projected["handle"] == leaf["handle"]
    assert projected["schema_lineage_token"] == leaf["schema_lineage_token"]
    assert projected["response_integrity"] == root_projected["response_integrity"]
    assert projected["response_end"] == root_projected["response_end"]
    assert list(projected)[-1] == "response_end"
    assert encoded.index('"response_integrity":{') < encoded.index(
        '"continuation":{'
    ) < encoded.index('"child_contract":{')
    projected_scalar_table = projected["child_contract"][
        "fixed_scalar_member_fact_table"
    ]
    assert projected_scalar_table["columns"] == [
        "key",
        "required",
        "accepted_types",
    ]
    raw_scalar_table = leaf["child_contract"][
        "fixed_scalar_member_fact_table"
    ]
    business_pointers = [row[3] for row in raw_scalar_table["rows"]]
    assert len({pointer.rsplit("/", 1)[0] for pointer in business_pointers}) == 1
    assert projected_scalar_table["business_object_pointer"] == (
        business_pointers[0].rsplit("/", 1)[0]
    )
    assert projected_scalar_table["rows"] == [
        row[:3] for row in raw_scalar_table["rows"]
    ]
    assert projected_scalar_table["exact_type_tokens"] == {
        "Actor Mixer": "ActorMixer",
        "Random Container": "RandomSequenceContainer",
        "随机容器": "RandomSequenceContainer",
        "Blend Container": "BlendContainer",
        "混合容器": "BlendContainer",
        "Sound": "Sound",
        "forbidden": ["RandomContainer"],
    }
    assert projected_scalar_table["row_policy"] == (
        "all_present_rows_in_order_skip_absent_optional"
    )
    assert projected_scalar_table["fact_command_assembly"] == {
        "fixed_argv_prefix": [
            "--action",
            "add_typed_fact",
            "--fact-action",
            "map-put",
            "--field-handle",
            leaf["handle"],
        ],
        "append_for_each_business_present_row": [
            "--value-type",
            "<selected-accepted-type>",
            "--fact-value",
            "<business-value>",
            "--key",
            "<row-key>",
        ],
    }
    fact_prefix = projected_scalar_table["fact_command_assembly"][
        "fixed_argv_prefix"
    ]
    for projected_row, raw_row in zip(
        projected_scalar_table["rows"], raw_scalar_table["rows"], strict=True
    ):
        key, _required, accepted_types = projected_row
        assert len(accepted_types) == 1
        assert [
            *fact_prefix,
            "--value-type",
            accepted_types[0],
            "--fact-value",
            "<business-value>",
            "--key",
            key,
        ] == raw_row[4][accepted_types[0]]
    assert "shared_policy" not in projected_scalar_table
    raw_nested_rows = leaf["continuation"]["nested_container_disclosures"]
    nested_table = projected["continuation"]["nested_container_disclosures"]
    nested_business_pointers = [
        row["business_value_pointer"] for row in raw_nested_rows
    ]
    assert len(
        {pointer.rsplit("/", 1)[0] for pointer in nested_business_pointers}
    ) == 1
    assert nested_table["business_object_pointer"] == (
        nested_business_pointers[0].rsplit("/", 1)[0]
    )
    assert nested_table["selection"] == (
        "first_row_with_present_business_value_pointer_in_queue_order"
    )
    assert nested_table["absent_business_values"] == (
        "skip_without_gateway_command"
    )
    assert nested_table["allowed_members"] == [
        row["key"] for row in raw_nested_rows
    ]
    assert nested_table["shape"] == "array"
    assert nested_table["replace_only"] == ["<selected-business-member>"]
    for raw_row in raw_nested_rows:
        assert [
            raw_row["key"]
            if token == "<selected-business-member>"
            else token
            for token in nested_table["argv_template"]
        ] == raw_row["argv"]
    assert projected["continuation"]["next_command_decision"][
        "evaluate_in_order"
    ][0]["command_key"] == "deferred_fact"
    assert "root_fact_queue_anchor" not in projected["continuation"]
    assert projected["continuation"]["next_command_decision"][
        "evaluate_in_order"
    ][0]["candidate"] == "deferred_fact_queue"
    nested_candidate = next(
        row
        for row in projected["continuation"]["next_command_decision"][
            "evaluate_in_order"
        ]
        if row["candidate"] == "nested_container_disclosures"
    )
    assert nested_candidate["command_key"] == "nested_container_disclosures"
    assert list(projected["continuation"])[:5] == [
        "next_command_decision",
        "deferred_fact",
        "nested_container_disclosures",
        "business_sibling_transition",
        "subcommand",
    ]
    assert "--no-dynamic-descendants" not in encoded

    sibling = leaf["continuation"]["business_sibling_transition"]
    sibling_argv = sibling["argv_by_shape"]["object"]
    assert sibling["copy_command_by_shape"]["object"] == (
        gateway.operation_draft_copy_command(
            [
                "python",
                str(gateway.GATEWAY_RUNNER_PATH),
                "gateway.py",
                *sibling_argv,
            ]
        )
    )
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
    assert last_decision["evaluate_in_order"][0]["command_key"] == (
        "deferred_fact"
    )
    assert "root_fact_queue_anchor" not in last_projected["continuation"]
    assert last_projected["continuation"]["business_sibling_transition"][
        "when_absent"
    ] == "nearest_ancestor_business_sibling"
    last_encoded = gateway.gateway_stdout_json_encoder(last_projected).encode(
        last_projected
    )
    assert '"root_fact_queue_anchor":{' not in last_encoded


def _archive_test_dynamic_container_schema_exposes_one_standard_argv_per_shape(
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
