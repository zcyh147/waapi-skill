from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

from wwise_waapi.operation_registry import OPERATION_REQUEST_CONTRACT, parse_operation_request
from wwise_waapi.typed_operations import (
    TypedOperationInputError,
    inline_operation_contract,
    materialize_inline_operation_request,
)


VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
CONTAINER = ("id-string", "{11111111-1111-1111-1111-111111111111}")
CHILD = ("direct-child", "Sound", "id-string", CONTAINER[1])
VALUE = (
    "scoped-name",
    "Switch",
    "Ground",
    "path",
    r"\Switches\Default Work Unit\Surface",
)
SCRIPT_PATH = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill" / "scripts" / "gateway.py"
SPEC = importlib.util.spec_from_file_location("waapi_typed_switch_assignment_gateway", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)


def _env(tmp_path: Path, version: str) -> dict[str, str]:
    config = tmp_path / f"config-{version}.json"
    config.write_text(
        json.dumps({"wwise_version": version, "project_modification_policy": "ask_before_changes"}),
        encoding="utf-8",
    )
    return {"WAAPI_SKILL_CONFIG_PATH": str(config)}


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize(
    "operation",
    ("switchContainer.addAssignment", "switchContainer.removeAssignment"),
)
def test_switch_assignment_materializes_three_exact_typed_identities(
    version: str,
    operation: str,
) -> None:
    request = materialize_inline_operation_request(
        operation,
        version,
        {
            "switch_container": CONTAINER,
            "child": CHILD,
            "state_or_switch": VALUE,
        },
    )

    assert request == {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": operation,
        "arguments": {
            "switch_container": {"kind": "id", "value": CONTAINER[1]},
            "child": {
                "kind": "direct-child",
                "type": "Sound",
                "parent": {"kind": "id", "value": CONTAINER[1]},
            },
            "state_or_switch": {
                "kind": "scoped-name",
                "type": "Switch",
                "name": "Ground",
                "parent": {
                    "kind": "path",
                    "value": r"\Switches\Default Work Unit\Surface",
                },
            },
        },
    }
    assert parse_operation_request(request, expected_version=version).operation == operation


@pytest.mark.parametrize(
    "operation",
    ("switchContainer.addAssignment", "switchContainer.removeAssignment"),
)
def test_switch_assignment_contract_has_one_relationship_specific_continuation(
    operation: str,
) -> None:
    contract = inline_operation_contract(operation, "2025.1")

    assert contract["input_shape"] == "inline"
    assert contract["continuation"]["subcommand"] == "typed-operation"
    assert contract["continuation"]["fields"] == [
        "--switch-container SELECTOR",
        "--child SELECTOR",
        "--state-or-switch SELECTOR",
    ]
    assert "object.set" not in str(contract)
    assert "request-json" not in str(contract).lower()


def test_switch_assignment_rejects_missing_or_extra_relationship_facts() -> None:
    with pytest.raises(TypedOperationInputError, match="missing"):
        materialize_inline_operation_request(
            "switchContainer.addAssignment",
            "2025.1",
            {"switch_container": CONTAINER, "child": CHILD},
        )
    with pytest.raises(TypedOperationInputError, match="unexpected"):
        materialize_inline_operation_request(
            "switchContainer.removeAssignment",
            "2025.1",
            {
                "switch_container": CONTAINER,
                "child": CHILD,
                "state_or_switch": VALUE,
                "object": CONTAINER,
            },
        )


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize(
    "operation",
    ("switchContainer.addAssignment", "switchContainer.removeAssignment"),
)
def test_public_switch_assignment_schema_and_preflight_use_only_typed_relationship_flags(
    tmp_path: Path,
    version: str,
    operation: str,
) -> None:
    env = _env(tmp_path, version)
    schema_code, schema = gateway.execute_gateway(
        ["--version", version, "operation-schema", operation],
        env=env,
        client_factory=lambda url: pytest.fail(f"schema connected to {url}"),
    )
    assert schema_code == 0, schema
    assert schema["operation"]["input_mode"] == "inline_typed"
    continuation = schema["typed_operation"]["continuation"]
    assert continuation["operation"] == operation
    assert continuation["fields"] == [
        "--switch-container SELECTOR",
        "--child SELECTOR",
        "--state-or-switch SELECTOR",
    ]

    rejected_code, rejected = gateway.execute_gateway(
        [
            "--version", version, "typed-operation", operation,
            "--schema-digest", schema["typed_operation"]["schema_digest"], "--apply",
            "--switch-container", *CONTAINER,
            "--child", *CHILD,
        ],
        env=env,
        client_factory=lambda url: pytest.fail(f"invalid preflight connected to {url}"),
    )
    assert rejected_code == 2, rejected
    assert rejected["error_code"] == "GatewayInputError"
