from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_transaction_gateway import (
    FakeClient,
    confirm,
    execute,
    live_info,
    local_project,
    preview,
    project,
)
from wwise_waapi.builders.debug_lua import LUA_SOURCE_AUTHORITY
from wwise_waapi.operation_registry import (
    OPERATION_REQUEST_CONTRACT,
    operation_request_schema_digest,
)
from wwise_waapi.transactions import TransactionState, TransactionStore


def _request(
    operation: str,
    arguments: dict[str, Any],
    *,
    version: str,
) -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": operation,
        "arguments": arguments,
    }


def _preview_and_confirm(
    request: dict[str, Any],
    *,
    tmp_path: Path,
    state_dir: Path,
    project_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    version = str(request["version"])
    year = int(version.split(".", 1)[0])
    active_project = project() if project_result is None else project_result
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=year)],
            "ak.wwise.core.getProjectInfo": [active_project],
        }
    )
    operation = str(request["operation"])
    if operation.startswith("debug."):
        argv = [
            "typed-operation",
            operation,
            "--schema-digest",
            operation_request_schema_digest(operation, version),
            "--apply",
        ]
        if operation in {"debug.setAsserts", "debug.setAutomationMode"}:
            argv.extend(
                ["--enable", "true" if request["arguments"]["enable"] else "false"]
            )
        code, transaction = execute(
            argv,
            tmp_path=tmp_path,
            state_dir=state_dir,
            client=client,
            version=version,
        )
        assert code == 0, transaction
    else:
        transaction = preview(
            request,
            tmp_path=tmp_path,
            state_dir=state_dir,
            client=client,
        )
    confirm(
        transaction["transaction_id"],
        transaction["artifact_hash"],
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    return transaction


@pytest.mark.parametrize(
    ("operation", "arguments"),
    (
        (
            "lua.executeCliFile",
            {
                "script_file": "/remote-only/script.lua",
                "io_root": "/remote-only",
                "source_authority": LUA_SOURCE_AUTHORITY,
            },
        ),
        (
            "lua.executeCoreFile",
            {
                "script_file": "/remote-only/script.lua",
                "io_root": "/remote-only",
                "source_authority": LUA_SOURCE_AUTHORITY,
            },
        ),
        (
            "lua.executeCoreInline",
            {
                "lua_code": "return true",
                "io_root": "/remote-only",
                "source_authority": LUA_SOURCE_AUTHORITY,
            },
        ),
    ),
)
def test_remote_lua_preview_fails_before_project_or_local_source_proof(
    tmp_path: Path,
    operation: str,
    arguments: dict[str, Any],
) -> None:
    client = FakeClient(
        {"ak.wwise.core.getInfo": [live_info(year=2025)]}
    )
    exit_code, payload = execute(
        [
            "--host",
            "wwise-studio",
            "legacy-preview",
            "--request-json",
            json.dumps(_request(operation, arguments, version="2025.1")),
        ],
        tmp_path=tmp_path,
        state_dir=tmp_path / operation.replace(".", "-"),
        client=client,
        version="2025.1",
    )

    assert exit_code == 2
    assert payload["error_code"] == "LOCAL_WAAPI_HOST_REQUIRED"
    assert payload["details"]["path_roles"][0] == "arguments.io_root"
    assert payload["executed"] is False
    assert [row[0] for row in client.calls] == ["ak.wwise.core.getInfo"]


@pytest.mark.parametrize(
    "operation",
    (
        "lua.executeCliFile",
        "lua.executeCoreFile",
        "lua.executeCoreInline",
    ),
)
def test_confirmed_lua_transaction_cannot_switch_to_remote_execute(
    tmp_path: Path,
    operation: str,
) -> None:
    state_dir = tmp_path / operation.replace(".", "-")
    io_root = tmp_path / "lua-io"
    io_root.mkdir()
    if operation == "lua.executeCoreInline":
        arguments = {
            "lua_code": "return true",
            "io_root": str(io_root),
            "source_authority": LUA_SOURCE_AUTHORITY,
        }
    else:
        script = io_root / "user-script.lua"
        script.write_text("return true\n", encoding="utf-8")
        arguments = {
            "script_file": str(script),
            "io_root": str(io_root),
            "source_authority": LUA_SOURCE_AUTHORITY,
        }
    transaction = _preview_and_confirm(
        _request(operation, arguments, version="2025.1"),
        tmp_path=tmp_path,
        state_dir=state_dir,
        project_result=local_project(tmp_path),
    )
    remote_client = FakeClient(
        {"ak.wwise.core.getInfo": [live_info(year=2025)]}
    )

    exit_code, payload = execute(
        [
            "--host",
            "192.0.2.10",
            "execute",
            transaction["transaction_id"],
        ],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=remote_client,
        version="2025.1",
    )

    assert exit_code == 2
    assert payload["error_code"] == "LOCAL_WAAPI_HOST_REQUIRED"
    assert payload["command"] == "execute"
    assert payload["executed"] is False
    assert [row[0] for row in remote_client.calls] == [
        "ak.wwise.core.getInfo"
    ]


def test_cli_lua_file_runs_once_then_finishes_at_result_schema_only(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "lua-state"
    io_root = tmp_path / "lua-io"
    io_root.mkdir()
    script = io_root / "user-script.lua"
    script.write_text("return wa_args.request_id\n", encoding="utf-8")
    active_project = local_project(tmp_path)
    request = _request(
        "lua.executeCliFile",
        {
            "script_file": str(script),
            "io_root": str(io_root),
            "source_authority": LUA_SOURCE_AUTHORITY,
            "wa_args": {"request_id": "gateway-full-chain"},
            "watchdog_seconds": 15,
        },
        version="2025.1",
    )
    transaction = _preview_and_confirm(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
        project_result=active_project,
    )
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2025)],
            "ak.wwise.core.getProjectInfo": [active_project],
            "ak.wwise.cli.executeLuaScript": [{"result": 0}],
        }
    )

    execute_exit, executed = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        version="2025.1",
    )

    assert execute_exit == 0, executed
    assert executed["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert executed["automatic_retry"] is False
    assert executed["verified"] is False
    lua_calls = [
        call
        for call in execute_client.calls
        if call[0] == "ak.wwise.cli.executeLuaScript"
    ]
    assert lua_calls == [
        (
            "ak.wwise.cli.executeLuaScript",
            {
                "request_id": "gateway-full-chain",
                "lua-script": str(script.resolve()),
                "watchdog-timeout": 15,
            },
            {},
        )
    ]

    verify_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info(year=2025)],
            "ak.wwise.core.getProjectInfo": [active_project],
        }
    )
    verify_exit, verified = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=verify_client,
        version="2025.1",
    )

    assert verify_exit == 0, verified
    assert verified["status"] == "result_schema_checked"
    assert verified["state"] == TransactionState.RESULT_SCHEMA_CHECKED.value
    assert verified["result_schema_checked"] is True
    assert verified["verified"] is False
    assert verified["verification"]["business_state_verified"] is False
    assert verified["verification_strength"] == "partial_reflected_schema"
    assert verified["automatic_retry"] is False
    assert not any(
        call[0] == "ak.wwise.cli.executeLuaScript"
        for call in verify_client.calls
    )
    events = TransactionStore(state_dir).read_events(transaction["transaction_id"])
    assert [event["event_type"] for event in events].count("execution_started") == 1
    assert [event["event_type"] for event in events].count("execution_completed") == 1


def test_automation_mode_runs_once_then_finishes_at_result_schema_only(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "automation-state"
    request = _request(
        "debug.setAutomationMode",
        {"enable": True},
        version="2022.1",
    )
    transaction = _preview_and_confirm(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    execute_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
            "ak.wwise.debug.enableAutomationMode": [{}],
        }
    )

    execute_exit, executed = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
    )

    assert execute_exit == 0, executed
    assert executed["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert executed["automatic_retry"] is False
    assert [
        call
        for call in execute_client.calls
        if call[0] == "ak.wwise.debug.enableAutomationMode"
    ] == [
        (
            "ak.wwise.debug.enableAutomationMode",
            {"enable": True},
            {},
        )
    ]

    verify_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project()],
        }
    )
    verify_exit, verified = execute(
        ["verify", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=verify_client,
    )

    assert verify_exit == 0, verified
    assert verified["status"] == "result_schema_checked"
    assert verified["state"] == TransactionState.RESULT_SCHEMA_CHECKED.value
    assert verified["result_schema_checked"] is True
    assert verified["verified"] is False
    assert verified["verification"]["business_state_verified"] is False
    assert verified["verification_strength"] == "complete_reflected_schema"
    assert verified["automatic_retry"] is False
    assert not any(
        call[0] == "ak.wwise.debug.enableAutomationMode"
        for call in verify_client.calls
    )


@pytest.mark.parametrize(
    (
        "operation",
        "version",
        "acknowledgement",
        "uri",
        "expected_disconnect",
        "process_expectation",
        "dispatch_loses_connection",
    ),
    (
        (
            "debug.restartWaapiServers",
            "2023.1",
            "restart_waapi_servers",
            "ak.wwise.debug.restartWaapiServers",
            True,
            "wwise_process_remains_running_waapi_servers_restart",
            True,
        ),
        (
            "debug.testAssert",
            "2022.1",
            "trigger_debug_assert",
            "ak.wwise.debug.testAssert",
            False,
            "assert_handler_or_dialog_is_host_build_dependent",
            False,
        ),
        (
            "debug.testCrash",
            "2022.1",
            "crash_wwise_process",
            "ak.wwise.debug.testCrash",
            True,
            "wwise_process_termination",
            True,
        ),
    ),
)
def test_host_controls_are_single_dispatch_terminal_and_never_retried(
    tmp_path: Path,
    operation: str,
    version: str,
    acknowledgement: str,
    uri: str,
    expected_disconnect: bool,
    process_expectation: str,
    dispatch_loses_connection: bool,
) -> None:
    state_dir = tmp_path / operation.replace(".", "-")
    request = _request(
        operation,
        {"acknowledge": acknowledgement},
        version=version,
    )
    transaction = _preview_and_confirm(
        request,
        tmp_path=tmp_path,
        state_dir=state_dir,
    )
    year = int(version.split(".", 1)[0])
    responses: dict[str, list[Any]] = {
        "ak.wwise.core.getInfo": [live_info(year=year)],
        "ak.wwise.core.getProjectInfo": [project()],
    }
    errors: dict[str, list[BaseException]] = {}
    if dispatch_loses_connection:
        errors[uri] = [ConnectionError("synthetic host-control disconnect")]
    else:
        responses[uri] = [{}]
    execute_client = FakeClient(responses, errors=errors)

    execute_exit, terminal = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=execute_client,
        version=version,
    )

    assert execute_exit == 2
    assert terminal["ok"] is False
    assert terminal["state"] == TransactionState.INDETERMINATE.value
    assert terminal["status"] == (
        "expected_disconnect_indeterminate"
        if expected_disconnect
        else "host_control_effect_indeterminate"
    )
    assert terminal["expected_disconnect"] is expected_disconnect
    assert terminal["dispatch_delivery"] == (
        "indeterminate_after_dispatch_attempt"
        if dispatch_loses_connection
        else "waapi_result_returned"
    )
    assert terminal["dispatch_accepted"] is (not dispatch_loses_connection)
    assert terminal["process_lifecycle"] == {
        "expected": process_expectation,
        "observed": "not_observed_by_gateway",
        "gateway_process_action": "none",
        "reconnect_attempted": False,
    }
    assert terminal["automatic_retry"] is False
    assert terminal["reconnect_attempted"] is False
    assert terminal["generic_verify_allowed"] is False
    assert "next_command" not in terminal
    assert [call[0] for call in execute_client.calls].count(uri) == 1

    events = TransactionStore(state_dir).read_events(transaction["transaction_id"])
    event_types = [event["event_type"] for event in events]
    assert event_types.count("execution_started") == 1
    assert event_types.count("execution_indeterminate") == 1
    assert "execution_completed" not in event_types

    retry_client = FakeClient(
        {"ak.wwise.core.getInfo": [live_info(year=year)]}
    )
    retry_exit, retry = execute(
        ["execute", transaction["transaction_id"]],
        tmp_path=tmp_path,
        state_dir=state_dir,
        client=retry_client,
        version=version,
    )
    assert retry_exit == 2
    assert retry["error_code"] == "InvalidTransition"
    assert [call[0] for call in retry_client.calls] == [
        "ak.wwise.core.getInfo"
    ]
    assert (
        TransactionStore(state_dir).load(transaction["transaction_id"]).state
        is TransactionState.INDETERMINATE
    )
