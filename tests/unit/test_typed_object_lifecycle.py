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
    assert payload["composer"]["typed_request_fields"]

    children = next(
        field
        for field in payload["composer"]["typed_request_fields"]
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
            "--schema-digest", payload["composer"]["typed_request_schema_digest"],
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
        "argv_by_shape": {
            "object": [
                "request-array-item",
                "object.create",
                "--schema-digest",
                payload["composer"]["typed_request_schema_digest"],
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
        "next_item_disclosure",
        "all_descendant_disclosures",
    ]
    grandchild_code, grandchild = waapi_gateway.execute_gateway(
        [
            "--version", "2025.1", "request-array-item", "object.create",
            "--schema-digest", payload["composer"]["typed_request_schema_digest"],
            "--array-handle", nested_children["handle"], "--index", "0",
            "--shape", "object", "--parent-schema-token",
            nested_children["schema_lineage_token"],
        ],
        env=_gateway_env(tmp_path),
        client_factory=lambda url: (_ for _ in ()).throw(AssertionError(url)),
    )
    assert grandchild_code == 0, grandchild
    assert grandchild["child_contract"]["required_keys"] == ["type", "name"]


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
        for field in schema["composer"]["typed_request_fields"]
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
