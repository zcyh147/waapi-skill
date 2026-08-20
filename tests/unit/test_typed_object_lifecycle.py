from __future__ import annotations

import pytest  # pyright: ignore[reportMissingImports]

from collections import deque
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from wwise_waapi.operation_registry import (  # pyright: ignore[reportMissingImports]
    OperationContractError,
    parse_operation_request,
    validate_prepared_roles,
    verify_prepared_operation,
)
from wwise_waapi.typed_operations import (  # pyright: ignore[reportMissingImports]
    draft_operation_request_contract,
    materialize_inline_operation_request,
)
from wwise_waapi.typed_requests import (  # pyright: ignore[reportMissingImports]
    expand_gateway_field_table,
    typed_request_construction_for_values,
)

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill" / "scripts" / "gateway.py"
SPEC = importlib.util.spec_from_file_location("waapi_typed_object_lifecycle_gateway", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
waapi_gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = waapi_gateway
SPEC.loader.exec_module(waapi_gateway)


def _gateway_env(tmp_path: Path) -> dict[str, str]:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"wwise_version": None, "waapi_host": "127.0.0.1", "waapi_port": None, "project_modification_policy": "ask_before_changes"}),
        encoding="utf-8",
    )
    return {"WAAPI_SKILL_CONFIG_PATH": str(config), "WWISE_VERSION": "2025.1"}


def _composer_fields(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    composer = payload["composer"]
    fields = composer.get("typed_request_fields")
    if isinstance(fields, list):
        return fields
    return expand_gateway_field_table(composer["typed_request_field_table"])


VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
SOURCE = ("id-string", "{11111111-1111-1111-1111-111111111111}")
PARENT = ("path", r"\Actor-Mixer Hierarchy\Default Work Unit\Target")


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("operation", ("object.copy", "object.move"))
def test_copy_and_move_materialize_exact_closed_requests(version: str, operation: str) -> None:
    request = materialize_inline_operation_request(
        operation,
        version,
        {"object": SOURCE, "parent": PARENT, "on_name_conflict": "fail"},
    )

    parsed = parse_operation_request(request, expected_version=version)
    assert parsed.operation == operation
    assert parsed.arguments["on_name_conflict"] == "fail"
    assert parsed.arguments["parent"] == {"kind": "path", "value": PARENT[1]}


@pytest.mark.parametrize("version", VERSIONS)
def test_delete_typed_input_preserves_versioned_checkout_omission(version: str) -> None:
    values: dict[str, object] = {"object": SOURCE}
    if version >= "2023.1":
        values["auto_check_out_to_source_control"] = "false"
    request = materialize_inline_operation_request("object.delete", version, values)
    parse_operation_request(request, expected_version=version)


def test_delete_rejects_checkout_before_2023() -> None:
    with pytest.raises(Exception, match="2023.1"):
        materialize_inline_operation_request(
            "object.delete",
            "2022.1",
            {"object": SOURCE, "auto_check_out_to_source_control": "true"},
        )


@pytest.mark.parametrize("version", VERSIONS)
def test_object_create_uses_shared_recursive_typed_core(version: str) -> None:
    contract = draft_operation_request_contract("object.create", version)
    payload = contract.as_gateway_payload()

    assert payload["input_shape"] == "draft"
    assert any(field["name"] == "children" for field in payload["fields"])
    assert payload["continuation"]["subcommand"] == "draft-start"
    assert payload["continuation"]["operation"] == "object.create"


def test_object_create_inverse_facts_follow_the_public_child_contract_order() -> None:
    contract = draft_operation_request_contract("object.create", "2023.1")
    construction = typed_request_construction_for_values(
        contract,
        args={
            "parent": {"kind": "path", "value": PARENT[1]},
            "type": "ActorMixer",
            "name": "Impact_Library",
            "on_name_conflict": "rename",
            "children": [
                {
                    "type": "RandomSequenceContainer",
                    "name": "Metal",
                    "notes": "reviewed",
                    "children": [
                        {"type": "Sound", "name": "Light"},
                        {"type": "Sound", "name": "Heavy"},
                    ],
                }
            ],
        },
        options={},
    )

    root_children = next(
        fact
        for fact in construction.facts
        if fact.action == "append" and fact.handle.startswith("trh1-")
    )
    member_keys = [
        fact.key
        for fact in construction.facts
        if fact.action == "map-put" and fact.handle == root_children.value
    ]
    assert member_keys == ["type", "name", "notes", "children"]


def test_public_object_create_schema_exposes_one_followable_typed_draft(tmp_path: Path) -> None:
    code, payload = waapi_gateway.execute_gateway(
        ["--version", "2025.1", "operation-schema", "object.create"],
        env=_gateway_env(tmp_path),
        client_factory=lambda url: (_ for _ in ()).throw(AssertionError(url)),
    )

    assert code == 0, payload
    assert payload["operation"]["input_mode"] == "composer"
    assert payload["composer"]["start"]["gateway_argv"] == [
        "draft-start",
        "object.create",
    ]
    metadata_decision = payload["composer"]["start_preconditions"][
        "next_step_decision"
    ]
    assert metadata_decision == (
        "metadata discover when required; otherwise draft-start"
    )
    assert payload["composer"]["typed_request_field_table"]["rows"]

    children = next(
        field
        for field in _composer_fields(payload)
        if field["name"] == "children"
    )
    container_code, container = waapi_gateway.execute_gateway(
        [
            "--version", "2025.1", "request-array-item", "object.create",
            "--schema-digest", payload["composer"]["typed_request_schema_digest"],
            "--array-handle", children["handle"], "--index", "0", "--shape", "object",
        ],
        env=_gateway_env(tmp_path),
        client_factory=lambda url: (_ for _ in ()).throw(AssertionError(url)),
    )
    assert container_code == 0, container
    assert container["continuation"]["subcommand"] == "draft-apply"
    assert [
        (row["key"], row["shape"])
        for row in container["continuation"]["nested_container_disclosures"]
    ] == [
        ("properties", "array"),
        ("references", "array"),
        ("children", "array"),
    ]
    assert "action_argv" not in container["continuation"]
    deferred_argv = container["continuation"]["deferred_fact"]["argv"]
    assert deferred_argv[
        deferred_argv.index("--fact-value")
        + 1
    ] == container["handle"]

    nested_code, nested_children = waapi_gateway.execute_gateway(
        [
            "--version", "2025.1", "request-map-container", "object.create",
            "--map-handle", container["handle"], "--key", "children",
            "--shape", "array", "--parent-schema-token",
            container["schema_lineage_token"],
        ],
        env=_gateway_env(tmp_path),
        client_factory=lambda url: (_ for _ in ()).throw(AssertionError(url)),
    )
    assert nested_code == 0, nested_children
    assert nested_children["continuation"]["next_item_disclosure"] == {
        "condition": "for_each_business_present_item",
        "index_order": "ascending_zero_based_index",
        "must_finish_before": "deferred_fact",
        "is_next_command": True,
        "business_cardinality_authority": {
            "source": "current_business_request",
            "schema_does_not_require_another_item": True,
            "do_not_disclose_absent_index": True,
        },
        "argv_by_shape": {
            "object": [
                "request-array-item",
                "object.create",
                "--array-handle",
                nested_children["handle"],
                "--index",
                "<zero_based_business_present_index>",
                "--shape",
                "object",
                "--parent-schema-token",
                nested_children["schema_lineage_token"],
            ]
        },
    }
    assert nested_children["continuation"]["deferred_fact"]["blocked_by"] == [
        "ancestor_deferred_parent_facts",
        "ancestor_child_contract_facts",
        "next_item_disclosure",
        "all_descendant_disclosures",
    ]
    grandchild_code, grandchild = waapi_gateway.execute_gateway(
        [
            "--version", "2025.1", "request-array-item", "object.create",
            "--array-handle", nested_children["handle"], "--index", "0",
            "--shape", "object", "--parent-schema-token",
            nested_children["schema_lineage_token"],
        ],
        env=_gateway_env(tmp_path),
        client_factory=lambda url: (_ for _ in ()).throw(AssertionError(url)),
    )
    assert grandchild_code == 0, grandchild
    assert grandchild["child_contract"]["required_keys"] == ["type", "name"]
    assert grandchild["business_value_scope"] == {
        "current_value_pointer": "/args/children/0/children/0",
        "outermost_disclosed_root_pointer": "/args/children/0",
        "current_value_only": True,
        "unrelated_prompt_objects_do_not_satisfy_member_conditions": True,
    }
    assert next(iter(grandchild["continuation"])) == (
        "business_sibling_transition"
    )
    assert grandchild["continuation"]["business_sibling_transition"] == {
        "condition": "current_business_request_contains_next_complex_item",
        "business_value_pointer": "/args/children/0/children/1",
        "index": 1,
        "first_when_current_business_object_is_leaf": True,
        "leaf_nested_container_disclosures": "forbidden",
        "otherwise_after": (
            "all_business_present_current_item_descendant_disclosures_if_any"
        ),
        "must_precede": "current_root_deferred_facts",
        "when_absent": {
            "next_action": (
                "unwind_drain_current_root_deferred_facts_then_use_nearest_"
                "ancestor_business_sibling_exact_argv"
            ),
        },
        "absent_or_scalar_next_item_forbidden": True,
        "is_next_command": True,
        "argv_by_shape": {
            "object": [
                "request-array-item",
                "object.create",
                "--array-handle",
                nested_children["handle"],
                "--index",
                "1",
                "--shape",
                "object",
                "--parent-schema-token",
                nested_children["schema_lineage_token"],
            ]
        },
    }
    assert grandchild["continuation"]["root_fact_queue_anchor"] == {
        "outermost_disclosed_root_pointer": "/args/children/0",
        "first_fact_argv": [
            "--action",
            "add_typed_fact",
            "--fact-action",
            "append",
            "--field-handle",
            children["handle"],
            "--value-type",
            "object",
            "--fact-value",
            container["handle"],
        ],
        "first_batch_must_start_with_first_fact": True,
        "batch_limit": 6,
    }
    next_decision = grandchild["continuation"]["next_command_decision"]
    assert list(grandchild["continuation"])[:3] == [
        "business_sibling_transition",
        "root_fact_queue_anchor",
        "next_command_decision",
    ]
    assert next_decision == {
        "business_presence_source": "current_user_business_request",
        "current_business_object_pointer": "/args/children/0/children/0",
        "schema_members_are_not_business_facts": True,
        "candidate_without_its_exact_business_pointer": "forbidden",
        "conditional_candidates_do_not_block_when_absent": True,
        "preview_construction_boundary": {
            "complete": False,
            "confirmation_before_preview": "invalid",
            "final_response_before_preview": "invalid",
            "ask_user_to_continue_before_preview": "invalid",
            "same_turn_requirement": (
                "continue_until_preview_or_structured_gateway_error"
            ),
        },
        "deferred_fact_root_barrier": {
            "outermost_disclosed_root_pointer": "/args/children/0",
            "start_at_response_with_current_value_pointer": "/args/children/0",
            "descendant_facts_before_root_parent_and_child_facts": "forbidden",
        },
        "evaluate_in_order": [
            {
                "candidate": "business_sibling_transition",
                "condition": (
                    "explicit_leaf_or_no_business_nested_member_and_sibling_present"
                ),
                "business_value_pointer": "/args/children/0/children/1",
                "command_pointer": (
                    "/continuation/business_sibling_transition/argv_by_shape/"
                    "<exact-business-shape>"
                ),
                "explicit_leaf_rule": {
                    "user_says_no_properties_references_children": (
                        "copy_exact_command_now"
                    ),
                    "nested_disclosures": "forbidden",
                },
            },
            {
                "candidate": "nested_container_disclosures",
                "condition": (
                    "first_business_present_member_by_queue_index_on_exact_current_object"
                ),
                "business_value_pointers": [
                    "/args/children/0/children/0/properties",
                    "/args/children/0/children/0/references",
                    "/args/children/0/children/0/children",
                ],
                "command_pointer": (
                    "/continuation/nested_container_disclosures/<selected>/argv"
                ),
            },
            {
                "candidate": "deferred_fact_queue",
                "condition": (
                    "no_earlier_business_present_disclosure_for_exact_current_object"
                ),
                "action": (
                    "return_to_outermost_disclosed_root_then_drain_"
                    "response_tree_preorder"
                ),
                "start_at": "outermost_disclosed_root_response",
                "first_command_pointer": (
                    "/continuation/root_fact_queue_anchor/first_fact_argv"
                ),
                "batch_facts": (
                    "current_root_only_next_up_to_6_deferred_facts_in_queue_order"
                ),
                "first_fact_only": "invalid",
            },
        ],
        "first_true_candidate_is_the_only_next_action": True,
        "draft_check_or_cancel_with_remaining_candidate_or_deferred_fact": "invalid",
    }
    assert grandchild["schema_lineage_authority"] == {
        "returned_token_scope": "direct_descendants_of_this_handle_only",
        "returned_token_handle": grandchild["handle"],
        "not_valid_for": "sibling_items_in_parent_array",
        "sibling_item_parent": {
            "array_handle": nested_children["handle"],
            "parent_schema_token": nested_children["schema_lineage_token"],
            "copy_parent_schema_token_exactly": True,
            "index_source": "next_business_present_sibling_index",
            "disclosure_condition": (
                "current_business_request_contains_that_index"
            ),
            "allowed_after": (
                "all_business_present_current_item_descendant_disclosures_if_any"
            ),
            "absent_index_forbidden": True,
            "is_next_command": False,
        },
    }
    assert grandchild["construction_state"] == {
        "complete": False,
        "disclosure_replay_allowed": False,
        "next_phase": "finish_dynamic_disclosures_then_apply_deferred_facts",
        "completion_boundary": "draft-check_then_preview",
        "construction_boundary": {
            "phase": "preview_construction",
            "mutation": False,
            "complete": False,
            "required_terminal": "preview",
            "before": "continue_no_confirm_no_end",
        },
    }
    assert grandchild["continuation"]["request_wide_order"]["traversal"] == (
        "response_tree_preorder"
    )
    assert grandchild["continuation"]["nested_container_order"] == (
        "schema_members_then_descendants_then_facts"
    )
    assert all(
        row["condition"] == "current_business_request_contains_member"
        and row["queue_index"] == index
        and row["is_next_command"] is False
        and "blocked_by" not in row
        for index, row in enumerate(
            grandchild["continuation"]["nested_container_disclosures"], start=1
        )
    )
    assert [
        row["business_value_pointer"]
        for row in grandchild["continuation"]["nested_container_disclosures"]
    ] == [
        "/args/children/0/children/0/properties",
        "/args/children/0/children/0/references",
        "/args/children/0/children/0/children",
    ]
    assert grandchild["continuation"][
        "next_business_present_nested_disclosure"
    ] == {
        "candidate_pointer": "/continuation/nested_container_disclosures",
        "selection": "first_business_present_member_by_queue_index",
        "repeat_for_descendants": True,
        "when_none": (
            "follow_business_sibling_transition_then_drain_deferred_fact_queue"
        ),
        "is_next_command": False,
        "becomes_next_command_only_after_exact_business_pointer_match": True,
        "absent_business_pointer": "forbidden",
    }
    assert grandchild["continuation"]["deferred_fact"]["blocked_by"] == [
        "ancestor_deferred_parent_facts",
        "ancestor_child_contract_facts",
        "business_sibling_transition",
        "all_descendant_disclosures",
    ]
    assert grandchild["continuation"]["deferred_fact"]["consume_once"] is True
    assert grandchild["continuation"]["deferred_fact"]["replay_allowed"] is False
    scalar_table = grandchild["child_contract"]["fixed_scalar_member_fact_table"]
    assert scalar_table["shared_policy"] == {
        "condition": "current_business_request_contains_member",
        "execute_after": "deferred_parent_fact",
        "queue_phase": "child_contract",
        "queue_order_ref": "/continuation/request_wide_order/deferred_fact_queue",
        "must_precede": "all_descendant_response_facts",
        "is_next_command": False,
        "consume_once": True,
        "replay_allowed": False,
    }
    scalar_rows = [
        dict(zip(scalar_table["columns"], row, strict=True))
        for row in scalar_table["rows"]
    ]
    assert [row["key"] for row in scalar_rows] == ["type", "name", "notes"]
    assert [row["required"] for row in scalar_rows] == [True, True, False]
    assert [row["business_value_pointer"] for row in scalar_rows] == [
        "/args/children/0/children/0/type",
        "/args/children/0/children/0/name",
        "/args/children/0/children/0/notes",
    ]
    for row in scalar_rows:
        argv = row["fact_argv_by_type"]["string"]
        assert argv[argv.index("--field-handle") + 1] == grandchild["handle"]
        assert argv[argv.index("--key") + 1] == row["key"]
    encoded = waapi_gateway.gateway_stdout_json_encoder(grandchild).encode(grandchild)
    assert len((encoded + "\n").encode("utf-8")) < 12 * 1024


def test_public_object_create_draft_start_uses_the_dedicated_typed_contract(
    tmp_path: Path,
) -> None:
    schema_code, schema = waapi_gateway.execute_gateway(
        ["--version", "2025.1", "operation-schema", "object.create"],
        env=_gateway_env(tmp_path),
        client_factory=lambda url: (_ for _ in ()).throw(AssertionError(url)),
    )
    assert schema_code == 0, schema
    code, payload = waapi_gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "--state-dir",
            str(tmp_path / "state"),
            "draft-start",
            "object.create",
        ],
        env=_gateway_env(tmp_path),
        client_factory=lambda url: (_ for _ in ()).throw(AssertionError(url)),
    )

    assert code == 0, payload
    assert payload["status"] == "editable"
    assert payload["draft"]["binding"]["operation"] == "object.create"
    assert payload["draft"]["current_facts"] == []

    type_handle = next(
        field["handle"]
        for field in _composer_fields(schema)
        if field["path"] == ["args", "type"]
    )
    apply_code, applied = waapi_gateway.execute_gateway(
        [
            "--version", "2025.1", "--state-dir", str(tmp_path / "state"),
            "draft-apply", payload["draft"]["draft_id"], "--task-authority",
            payload["task_authority"], "--expected-revision", "1", "--facts",
            "--action", "add_typed_fact", "--fact-action", "set",
            "--field-handle", type_handle, "--value-type", "string",
            "--fact-value", "ActorMixer",
        ],
        env=_gateway_env(tmp_path),
        client_factory=lambda url: (_ for _ in ()).throw(AssertionError(url)),
    )
    assert apply_code == 0, applied
    assert applied["draft"]["revision"] == 2
    assert applied["draft"]["current_facts"][0]["value"] == "ActorMixer"


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("operation", ("object.copy", "object.move"))
def test_copy_and_move_source_control_fields_are_versioned(
    version: str, operation: str
) -> None:
    values: dict[str, object] = {"object": SOURCE, "parent": PARENT}
    if version >= "2023.1":
        values["auto_check_out_to_source_control"] = "false"
        if operation == "object.copy":
            values["auto_add_to_source_control"] = "false"
    request = materialize_inline_operation_request(operation, version, values)
    parse_operation_request(request, expected_version=version)


class _Reader:
    def __init__(self, rows: list[Mapping[str, Any]]) -> None:
        self.rows = deque(rows)

    def __call__(
        self, _uri: str, _args: Mapping[str, Any], _options: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        return self.rows.popleft()


def _prepared_lifecycle(kind: str) -> dict[str, object]:
    return {
        "contract": "waapi-skill.prepared-operation/v1",
        "operation": "object.copy" if kind.startswith("copied") else "object.move",
        "verification_plan": {
            "kind": kind,
            "source_id": SOURCE[1],
            "source_name": "Source",
            "old_path": r"\Actor-Mixer Hierarchy\Default Work Unit\Source",
            "expected_parent_id": "{22222222-2222-2222-2222-222222222222}",
            "expected_parent_path": PARENT[1],
        },
    }


def test_copy_verifier_requires_new_returned_guid_parent_and_path() -> None:
    copied = "{33333333-3333-3333-3333-333333333333}"
    result = verify_prepared_operation(
        _prepared_lifecycle("copied-guid-under-parent"),
        execution_result={"return": [{"id": copied}]},
        read_call=_Reader(
            [
                {
                    "return": [
                        {
                            "id": copied,
                            "name": "Source",
                            "type": "Sound",
                            "path": PARENT[1] + r"\Source",
                            "parent": {"id": "{22222222-2222-2222-2222-222222222222}"},
                        }
                    ]
                }
            ]
        ),
    )
    assert result.status == "verified"

    unverifiable = verify_prepared_operation(
        _prepared_lifecycle("copied-guid-under-parent"),
        execution_result={},
        read_call=_Reader([]),
    )
    assert unverifiable.status == "verification_failed"


def test_move_verifier_requires_returned_source_guid_and_old_path_absence() -> None:
    result = verify_prepared_operation(
        _prepared_lifecycle("moved-guid-under-parent"),
        execution_result={"return": [{"id": SOURCE[1]}]},
        read_call=_Reader(
            [
                {
                    "return": [
                        {
                            "id": SOURCE[1],
                            "name": "Source",
                            "type": "Sound",
                            "path": PARENT[1] + r"\Source",
                            "parent": {"id": "{22222222-2222-2222-2222-222222222222}"},
                        }
                    ]
                },
                {"return": []},
            ]
        ),
    )
    assert result.status == "verified"

    wrong_identity = verify_prepared_operation(
        _prepared_lifecycle("moved-guid-under-parent"),
        execution_result={"return": [{"id": "{99999999-9999-9999-9999-999999999999}"}]},
        read_call=_Reader([{"return": []}, {"return": []}]),
    )
    assert wrong_identity.status == "verification_failed"


@pytest.mark.parametrize("operation", ("object.copy", "object.move"))
def test_copy_and_move_never_expose_native_replace(operation: str) -> None:
    with pytest.raises(Exception, match="on_name_conflict"):
        materialize_inline_operation_request(
            operation,
            "2025.1",
            {"object": SOURCE, "parent": PARENT, "on_name_conflict": "replace"},
        )


@pytest.mark.parametrize(
    ("kind", "operation"),
    (("copied-guid-under-parent", "object.copy"), ("moved-guid-under-parent", "object.move")),
)
def test_copy_and_move_rename_accept_gateway_observed_result_name(
    kind: str, operation: str
) -> None:
    created = (
        "{33333333-3333-3333-3333-333333333333}"
        if operation == "object.copy"
        else SOURCE[1]
    )
    prepared = _prepared_lifecycle(kind)
    prepared["verification_plan"]["on_name_conflict"] = "rename"  # type: ignore[index]
    result = verify_prepared_operation(
        prepared,
        execution_result={"return": [{"id": created}]},
        read_call=_Reader(
            [
                {
                    "return": [
                        {
                            "id": created,
                            "name": "Source_01",
                            "type": "Sound",
                            "path": PARENT[1] + r"\Source_01",
                            "parent": {"id": "{22222222-2222-2222-2222-222222222222}"},
                        }
                    ]
                },
                *([{"return": []}] if operation == "object.move" else []),
            ]
        ),
    )
    assert result.status == "verified"


def test_copy_move_collision_guard_detects_appearance_before_execution() -> None:
    prepared = {
        "contract": "waapi-skill.prepared-operation/v1",
        "operation": "object.copy",
        "request": {
            "contract": "waapi-skill.operation-request/v1",
            "version": "2025.1",
            "operation": "object.copy",
            "arguments": {"object": {"kind": "id", "value": SOURCE[1]}, "parent": {"kind": "path", "value": PARENT[1]}},
        },
        "dispatch": {"uri": "ak.wwise.core.object.copy", "args": {}, "options": {}},
        "resolved_roles": {},
        "pre_state": {
            "copy_move_collision_guard": {"path": PARENT[1] + r"\Source", "rows": []}
        },
    }
    validation = validate_prepared_roles(
        prepared,
        read_call=_Reader(
            [{"return": [{"id": "{99999999-9999-9999-9999-999999999999}", "name": "Source"}]}]
        ),
    )
    assert validation["status"] == "repreview_required"
