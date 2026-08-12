from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

import pytest

from wwise_waapi.operation_registry import parse_operation_request
from wwise_waapi.typed_operations import (
    draft_operation_request_contract,
    inline_operation_contract,
    materialize_inline_operation_request,
)
from wwise_waapi.typed_requests import (
    TypedRequestFact,
    dynamic_array_item_handle,
    dynamic_container_disclosure,
    dynamic_map_entry_handle,
    materialize_typed_request,
)


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill" / "scripts" / "gateway.py"
SPEC = importlib.util.spec_from_file_location("waapi_typed_authoring_ui_gateway", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)

VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
INLINE = ("ui.captureScreen", "ui.commands.execute")
DRAFT = ("ui.commands.register", "ui.commands.unregister")


def _env(tmp_path: Path, version: str) -> dict[str, str]:
    config = tmp_path / f"config-{version}.json"
    config.write_text(
        json.dumps({"wwise_version": version, "project_modification_policy": "ask_before_changes"}),
        encoding="utf-8",
    )
    return {"WAAPI_SKILL_CONFIG_PATH": str(config), "WWISE_WAAPI_PORT": "8080"}


@pytest.mark.parametrize("operation", (*INLINE, *DRAFT))
@pytest.mark.parametrize("version", VERSIONS)
def test_every_authoring_ui_lane_has_one_public_typed_entry(
    tmp_path: Path, operation: str, version: str
) -> None:
    code, payload = gateway.execute_gateway(
        ["--version", version, "operation-schema", operation],
        env=_env(tmp_path, version),
        client_factory=lambda url: pytest.fail(f"schema connected to {url}"),
    )
    assert code == 0, payload
    assert payload["operation"]["input_mode"] == (
        "inline_typed" if operation in INLINE else "composer"
    )
    if operation in INLINE:
        assert inline_operation_contract(operation, version)["continuation"]["operation"] == operation
        assert payload["typed_operation"]["continuation"]["subcommand"] == "typed-operation"
    else:
        assert draft_operation_request_contract(operation, version).uri == operation
        assert payload["composer"]["start"]["subcommand"] == "draft-start"


@pytest.mark.parametrize("version", VERSIONS)
def test_capture_screen_materializes_typed_bounded_options(version: str) -> None:
    request = materialize_inline_operation_request(
        "ui.captureScreen",
        version,
        {
            "view_name": "Project Explorer",
            "view_channel": "2",
            "rect": ("10", "20", "640", "480"),
        },
    )
    assert request["arguments"] == {
        "view_name": "Project Explorer",
        "view_channel": 2,
        "rect": {"x": 10, "y": 20, "width": 640, "height": 480},
    }
    parse_operation_request(request, expected_version=version)


@pytest.mark.parametrize("version", VERSIONS)
def test_command_execute_materializes_typed_values(version: str, tmp_path: Path) -> None:
    values: dict[str, Any] = {
        "command": "SaveProject",
        "objects": ("{11111111-1111-1111-1111-111111111111}",),
        "platforms": ("Windows",),
        "value_type": "boolean",
        "value": "true",
    }
    if version == "2025.1":
        source = tmp_path / "input.wav"
        source.write_bytes(b"RIFF")
        values["files"] = (str(source),)
    request = materialize_inline_operation_request("ui.commands.execute", version, values)
    assert request["arguments"]["command"] == "SaveProject"
    assert request["arguments"]["value"] is True
    if version == "2025.1":
        assert request["arguments"]["files"] == [str(source)]
    parse_operation_request(request, expected_version=version)


def test_capture_and_execute_invalid_values_fail_before_live_connection(tmp_path: Path) -> None:
    cases = (
        ("ui.captureScreen", ["--view-channel", "5"]),
        ("ui.commands.execute", ["--command", "", "--value", "number", "NaN"]),
    )
    for operation, argv in cases:
        digest = inline_operation_contract(operation, "2025.1")["schema_digest"]
        code, payload = gateway.execute_gateway(
            [
                "--version", "2025.1", "typed-operation", operation,
                "--schema-digest", digest, *argv, "--apply",
            ],
            env=_env(tmp_path, "2025.1"),
            client_factory=lambda url: pytest.fail(f"invalid input connected to {url}"),
        )
        assert code == 2, payload


def _notification_descriptor_facts(operation: str) -> tuple[Any, list[TypedRequestFact]]:
    contract = draft_operation_request_contract(operation, "2024.1")
    commands = next(field for field in contract.fields if field.path == ("commands",))
    row = dynamic_array_item_handle(
        contract, array_handle=commands.handle, index=0, shape="object"
    )
    row_disclosure = dynamic_container_disclosure(
        contract,
        parent_handle=commands.handle,
        key="0",
        shape="object",
        child_handle=row,
    )
    handler_choice = next(
        choice["handle"]
        for branch in row_disclosure["branch_choices"]
        if branch["key"] == "handler"
        for choice in branch["choices"]
        if choice["constant_fields"] == {"kind": "notification"}
    )
    handler = dynamic_map_entry_handle(
        contract,
        map_handle=row,
        key="handler",
        shape="object",
        choice_handle=handler_choice,
        parent_schema=row_disclosure["schema_lineage"],
    )
    return contract, [
        TypedRequestFact("append", commands.handle, "object", row),
        TypedRequestFact("map-put", row, "string", "example.notify", key="id"),
        TypedRequestFact("map-put", row, "string", "Notify", key="display_name"),
        TypedRequestFact("choose-dynamic", row, "choice", handler_choice, key="handler"),
        TypedRequestFact("map-put", row, "object", handler, key="handler"),
        TypedRequestFact("map-put", handler, "string", "notification", key="kind"),
    ]


@pytest.mark.parametrize("operation", DRAFT)
def test_register_and_descriptor_unregister_materialize_explicit_owned_shape(
    operation: str,
) -> None:
    contract, facts = _notification_descriptor_facts(operation)
    request = materialize_typed_request(
        contract, schema_digest=contract.schema_digest, facts=facts
    )
    assert request.args == {
        "commands": [
            {
                "id": "example.notify",
                "display_name": "Notify",
                "handler": {"kind": "notification"},
            }
        ]
    }
    parsed = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2024.1",
        "operation": operation,
        "arguments": request.args,
    }
    parse_operation_request(parsed, expected_version="2024.1")


def test_unregister_existing_ids_requires_explicit_destructive_branch() -> None:
    contract = draft_operation_request_contract("ui.commands.unregister", "2024.1")
    ids = next(field for field in contract.fields if field.path == ("command_ids",))
    acknowledgement = next(
        field for field in contract.fields if field.path == ("acknowledgement",)
    )
    assert acknowledgement.as_dict()["constant_values"] == [
        "unregister_existing_commands_without_definition"
    ]
    source_authority = next(
        field for field in contract.fields if field.path == ("source_authority",)
    )
    assert source_authority.as_dict()["constant_values"] == [
        "user_supplied_verbatim"
    ]
    complete = materialize_typed_request(
        contract,
        schema_digest=contract.schema_digest,
        facts=(
            TypedRequestFact("append", ids.handle, "string", "example.notify"),
            TypedRequestFact(
                "set",
                acknowledgement.handle,
                "string",
                "unregister_existing_commands_without_definition",
            ),
        ),
    )
    assert complete.args["command_ids"] == ["example.notify"]
    parse_operation_request(
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": "2024.1",
            "operation": "ui.commands.unregister",
            "arguments": complete.args,
        },
        expected_version="2024.1",
    )

    incomplete = materialize_typed_request(
        contract,
        schema_digest=contract.schema_digest,
        facts=(TypedRequestFact("append", ids.handle, "string", "example.notify"),),
    )
    with pytest.raises(Exception, match="acknowledgement"):
        parse_operation_request(
            {
                "contract": "waapi-skill.operation-request/v1",
                "version": "2024.1",
                "operation": "ui.commands.unregister",
                "arguments": incomplete.args,
            },
            expected_version="2024.1",
        )


@pytest.mark.parametrize(
    ("operation", "field_path", "expected"),
    (
        ("ui.commands.register", ("source_authority",), "user_supplied_verbatim"),
        ("ui.commands.unregister", ("source_authority",), "user_supplied_verbatim"),
        (
            "ui.commands.unregister",
            ("acknowledgement",),
            "unregister_existing_commands_without_definition",
        ),
    ),
)
def test_public_composer_schema_discloses_required_ui_safety_constants(
    tmp_path: Path,
    operation: str,
    field_path: tuple[str, ...],
    expected: str,
) -> None:
    code, payload = gateway.execute_gateway(
        ["--version", "2024.1", "operation-schema", operation],
        env=_env(tmp_path, "2024.1"),
        client_factory=lambda url: pytest.fail(f"schema connected to {url}"),
    )
    assert code == 0, payload
    field = next(
        item
        for item in payload["composer"]["typed_request_fields"]
        if item["path"] == ["args", *field_path]
    )
    assert field["constant_values"] == [expected]


@pytest.mark.parametrize(
    ("version", "expected_kinds"),
    (
        ("2021.1", {"notification", "program"}),
        ("2022.1", {"notification", "program"}),
        ("2023.1", {"notification", "program", "lua_script"}),
        ("2024.1", {"notification", "program", "lua_script"}),
        ("2025.1", {"notification", "program", "lua_script"}),
    ),
)
def test_public_ui_handler_choices_are_exactly_versioned(
    tmp_path: Path,
    version: str,
    expected_kinds: set[str],
) -> None:
    operation = "ui.commands.register"
    code, schema = gateway.execute_gateway(
        ["--version", version, "operation-schema", operation],
        env=_env(tmp_path, version),
        client_factory=lambda url: pytest.fail(f"schema connected to {url}"),
    )
    assert code == 0, schema
    typed = schema["composer"]
    commands = next(
        field
        for field in typed["typed_request_fields"]
        if field["path"] == ["args", "commands"]
    )
    code, row = gateway.execute_gateway(
        [
            "--version",
            version,
            "request-array-item",
            operation,
            "--schema-digest",
            typed["typed_request_schema_digest"],
            "--array-handle",
            commands["handle"],
            "--index",
            "0",
            "--shape",
            "object",
        ],
        env=_env(tmp_path, version),
        client_factory=lambda url: pytest.fail(f"disclosure connected to {url}"),
    )
    assert code == 0, row
    handler = next(
        branch
        for branch in row["child_contract"]["branch_choices"]
        if branch["key"] == "handler"
    )
    assert {
        choice["constant_fields"]["kind"] for choice in handler["choices"]
    } == expected_kinds


@pytest.mark.parametrize("version", ("2021.1", "2022.1"))
def test_old_ui_lanes_reject_lua_handler_during_canonical_parse(version: str) -> None:
    with pytest.raises(Exception, match="not available"):
        parse_operation_request(
            {
                "contract": "waapi-skill.operation-request/v1",
                "version": version,
                "operation": "ui.commands.register",
                "arguments": {
                    "commands": [
                        {
                            "id": "example.lua",
                            "display_name": "Lua",
                            "handler": {
                                "kind": "lua_script",
                                "lua_script_path": "/tmp/example.lua",
                            },
                        }
                    ],
                    "source_authority": "user_supplied_verbatim",
                },
            },
            expected_version=version,
        )


@pytest.mark.parametrize(
    "operation", ("ui.commands.register", "ui.commands.unregister")
)
def test_program_handlers_require_source_authority_in_canonical_parser(
    operation: str,
) -> None:
    with pytest.raises(Exception, match="requires source_authority"):
        parse_operation_request(
            {
                "contract": "waapi-skill.operation-request/v1",
                "version": "2024.1",
                "operation": operation,
                "arguments": {
                    "commands": [
                        {
                            "id": "example.program",
                            "display_name": "Program",
                            "handler": {
                                "kind": "program",
                                "program_path": "/bin/echo",
                            },
                        }
                    ]
                },
            },
            expected_version="2024.1",
        )
