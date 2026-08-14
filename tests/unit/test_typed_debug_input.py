from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

from tests.unit.test_transaction_gateway import (
    FakeClient,
    execute,
    live_info,
    project,
)
from wwise_waapi.operation_registry import operation_request_schema_digest
from wwise_waapi.transactions import TransactionState, TransactionStore


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill" / "scripts" / "gateway.py"
SPEC = importlib.util.spec_from_file_location("waapi_typed_debug_gateway", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)


def _env(tmp_path: Path, version: str) -> dict[str, str]:
    config = tmp_path / f"config-{version}.json"
    config.write_text(
        json.dumps(
            {"wwise_version": version, "project_modification_policy": "allow_changes"}
        ),
        encoding="utf-8",
    )
    return {"WAAPI_SKILL_CONFIG_PATH": str(config), "WWISE_WAAPI_PORT": "8080"}


@pytest.mark.parametrize(
    ("operation", "versions", "api"),
    (
        (
            "debug.restartWaapiServers",
            ("2023.1", "2024.1", "2025.1"),
            "ak.wwise.debug.restartWaapiServers",
        ),
        (
            "debug.testAssert",
            ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
            "ak.wwise.debug.testAssert",
        ),
        (
            "debug.testCrash",
            ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
            "ak.wwise.debug.testCrash",
        ),
    ),
)
def test_debug_host_controls_disclose_one_zero_value_confirmation_entry(
    tmp_path: Path,
    operation: str,
    versions: tuple[str, ...],
    api: str,
) -> None:
    for version in versions:
        code, payload = gateway.execute_gateway(
            ["--version", version, "operation-schema", operation],
            env=_env(tmp_path, version),
            client_factory=lambda url: pytest.fail(f"schema connected to {url}"),
        )
        assert code == 0, payload
        typed = payload["typed_operation"]
        assert payload["operation"]["input_mode"] == "inline_typed"
        assert typed["input_shape"] == "zero"
        assert typed["continuation"] == {
            "subcommand": "typed-operation",
            "operation": operation,
            "schema_digest": typed["schema_digest"],
            "gateway_argv_prefix": [
                "typed-operation",
                operation,
                "--schema-digest",
                typed["schema_digest"],
                "--apply",
            ],
            "required_flag": "--apply",
            "fields": [],
        }
        assert typed["business_values_required"] is False
        assert typed["risk"]["expected_disconnect"] is (
            operation != "debug.testAssert"
        )
        assert typed["risk"]["process_expectation"]
        assert "selector_grammar" not in typed
        assert "acknowledge" not in json.dumps(payload)

        generic_code, generic = gateway.execute_gateway(
            ["--version", version, "request-schema", api],
            env=_env(tmp_path, version),
            client_factory=lambda url: pytest.fail(f"request-schema connected to {url}"),
        )
        assert generic_code == 2, generic
        assert generic["error_code"] == "GatewayInputError"
        assert f"operation-schema {operation}" in generic["message"]

        reflected = gateway.request_contract(version, api)
        direct_code, direct = gateway.execute_gateway(
            [
                "--version", version, "typed-zero-call", api,
                "--schema-digest", reflected.schema_digest, "--apply",
            ],
            env=_env(tmp_path, version),
            client_factory=lambda url: pytest.fail(f"typed-zero connected to {url}"),
        )
        assert direct_code == 2, direct
        assert direct["error_code"] == "GatewayInputError"
        assert f"operation-schema {operation}" in direct["message"]


@pytest.mark.parametrize(
    ("operation", "api"),
    (
        ("debug.setAsserts", "ak.wwise.debug.enableAsserts"),
        ("debug.setAutomationMode", "ak.wwise.debug.enableAutomationMode"),
    ),
)
@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_debug_boolean_controls_use_one_inline_typed_submission(
    tmp_path: Path,
    operation: str,
    api: str,
    version: str,
) -> None:
    schema_code, schema = gateway.execute_gateway(
        ["--version", version, "operation-schema", operation],
        env=_env(tmp_path, version),
        client_factory=lambda url: pytest.fail(f"schema connected to {url}"),
    )
    assert schema_code == 0, schema
    assert schema["operation"]["input_mode"] == "inline_typed"
    assert schema["typed_operation"]["continuation"]["fields"] == [
        "--enable true|false"
    ]

    captured: list[dict[str, object]] = []
    original = gateway.create_transaction_preview

    def fake_preview(request: dict[str, object], **_kwargs: object) -> dict[str, object]:
        captured.append(request)
        return {"ok": True, "status": "ok", "request": request}

    gateway.create_transaction_preview = fake_preview
    try:
        code, payload = gateway.execute_gateway(
            [
                "--version", version, "typed-operation", operation,
                "--schema-digest", operation_request_schema_digest(operation, version),
                "--apply", "--enable", "true",
            ],
            env=_env(tmp_path, version),
            client_factory=lambda _url: FakeClient(
                {"ak.wwise.core.getInfo": [live_info(year=int(version[:4]))]}
            ),
        )
    finally:
        gateway.create_transaction_preview = original
    assert code == 0, payload
    assert captured == [
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": version,
            "operation": operation,
            "arguments": {"enable": True},
        }
    ]


def test_zero_debug_preview_internalizes_ack_and_remains_confirmation_only(
    tmp_path: Path,
) -> None:
    version = "2023.1"
    operation = "debug.restartWaapiServers"
    api = "ak.wwise.debug.restartWaapiServers"
    state_dir = tmp_path / "debug-zero-state"
    schema_code, schema = gateway.execute_gateway(
        ["--version", version, "operation-schema", operation],
        env=_env(tmp_path, version),
        client_factory=lambda url: pytest.fail(f"schema connected to {url}"),
    )
    assert schema_code == 0, schema
    continuation = schema["typed_operation"]["continuation"]
    code, previewed = execute(
        [
            "typed-operation", operation,
            "--schema-digest", schema["typed_operation"]["schema_digest"],
            "--apply",
        ],
        tmp_path=tmp_path,
        state_dir=state_dir,
        version=version,
        policy="allow_changes",
        client=FakeClient(
            {
                "ak.wwise.core.getInfo": [live_info(year=2023)],
                "ak.wwise.core.getProjectInfo": [project()],
            }
        ),
    )
    assert continuation["subcommand"] == "typed-operation"
    assert code == 0, previewed
    assert previewed["state"] == TransactionState.AWAITING_CONFIRMATION.value
    artifact = TransactionStore(state_dir).load_preview(previewed["transaction_id"]).artifact
    assert artifact["request"] == {
        "contract": "waapi-skill.operation-request/v1",
        "version": version,
        "operation": operation,
        "arguments": {"acknowledge": "restart_waapi_servers"},
    }
    assert artifact["prepared_operation"]["pre_state"]["host_control"] == {
        "operation": operation,
        "uri": api,
        "acknowledge": "restart_waapi_servers",
        "expected_disconnect": True,
        "process_expectation": "wwise_process_remains_running_waapi_servers_restart",
        "process_observation": "not_performed_by_gateway",
    }


@pytest.mark.parametrize("version", ("2021.1", "2022.1"))
def test_unsupported_restart_lane_discloses_only_the_version_boundary(
    tmp_path: Path,
    version: str,
) -> None:
    code, payload = gateway.execute_gateway(
        ["--version", version, "operation-schema", "debug.restartWaapiServers"],
        env=_env(tmp_path, version),
        client_factory=lambda url: pytest.fail(f"schema connected to {url}"),
    )

    assert code == 0, payload
    assert "request_envelope" not in payload
    assert "request_envelope_policy" not in payload
    assert payload["operation"]["availability"] == {
        "status": "unsupported_version",
        "requested_version": version,
        "supported_versions": ["2023.1", "2024.1", "2025.1"],
    }
    serialized = json.dumps(payload)
    assert "acknowledge" not in serialized
    assert "request-json" not in serialized
    assert "preview_invocation" not in serialized
