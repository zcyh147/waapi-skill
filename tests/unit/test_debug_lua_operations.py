from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from wwise_waapi.builders.debug_lua import (
    LUA_SOURCE_AUTHORITY,
    DebugLuaContractError,
    normalize_wal_tree_result,
)
from wwise_waapi.operation_registry import (
    OPERATION_REQUEST_CONTRACT,
    OperationContractError,
    describe_operation,
    parse_operation_request,
    prepare_operation,
    validate_prepared_roles,
    verify_prepared_operation,
)


def _no_read(
    uri: str,
    args: Mapping[str, Any],
    options: Mapping[str, Any],
) -> Mapping[str, Any]:
    raise AssertionError(f"closed debug/Lua operations must not issue a preview read: {uri}")


def _request(
    operation: str,
    arguments: Mapping[str, Any],
    *,
    version: str,
) -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": operation,
        "arguments": dict(arguments),
    }


def test_cli_lua_file_is_verbatim_isolated_and_rechecked_before_execution(
    tmp_path: Path,
) -> None:
    script = tmp_path / "user-script.lua"
    script.write_text("return wa_args.request_id\n", encoding="utf-8")
    request = parse_operation_request(
        _request(
            "lua.executeCliFile",
            {
                "script_file": str(script),
                "io_root": str(tmp_path),
                "source_authority": LUA_SOURCE_AUTHORITY,
                "wa_args": {"request_id": "abc"},
                "watchdog_seconds": 15,
            },
            version="2025.1",
        )
    )
    prepared = prepare_operation(request, read_call=_no_read).as_dict()

    assert prepared["dispatch"] == {
        "uri": "ak.wwise.cli.executeLuaScript",
        "args": {
            "request_id": "abc",
            "lua-script": str(script.resolve()),
            "watchdog-timeout": 15,
        },
        "options": {},
    }
    proof = prepared["pre_state"]["lua_source_proof"]
    assert proof["authority"] == LUA_SOURCE_AUTHORITY
    assert proof["kind"] == "file"
    assert proof["file"]["path"] == str(script.resolve())
    assert proof["file"]["size"] == len(script.read_bytes())
    assert len(proof["file"]["sha256"]) == 64
    assert prepared["pre_state"]["implicit_side_effect_confinement"] == "not_proven"
    assert prepared["cleanup"]["automatic_retry"] is False

    unchanged = validate_prepared_roles(prepared, read_call=_no_read)
    assert unchanged["ok"] is True

    script.write_text("return 'changed after preview'\n", encoding="utf-8")
    changed = validate_prepared_roles(prepared, read_call=_no_read)
    assert changed["ok"] is False
    assert changed["status"] == "repreview_required"


def test_core_inline_lua_is_exactly_user_text_and_only_available_in_2025(
    tmp_path: Path,
) -> None:
    lua_code = "local x = wa_args.value\nreturn x + 1\n"
    request = parse_operation_request(
        _request(
            "lua.executeCoreInline",
            {
                "lua_code": lua_code,
                "io_root": str(tmp_path),
                "source_authority": LUA_SOURCE_AUTHORITY,
                "wa_args": {"value": 41},
            },
            version="2025.1",
        )
    )
    prepared = prepare_operation(request, read_call=_no_read).as_dict()

    assert prepared["dispatch"]["uri"] == "ak.wwise.core.executeLuaScript"
    assert prepared["dispatch"]["args"] == {
        "value": 41,
        "luaString": lua_code,
    }
    assert prepared["pre_state"]["lua_source_proof"]["kind"] == "inline"
    assert (
        prepared["semantic_preview"]["envelope"]["metadata"]["model_authored_code"]
        is False
    )
    assert validate_prepared_roles(prepared, read_call=_no_read)["ok"] is True
    authority_schema = describe_operation("lua.executeCoreInline").as_dict()[
        "argument_contract"
    ]["properties"]["source_authority"]
    assert "current user message" in authority_schema["description"]
    assert "runtime cannot independently prove provenance" in authority_schema[
        "description"
    ]

    with pytest.raises(OperationContractError, match="not reflected"):
        parse_operation_request(
            _request(
                "lua.executeCoreInline",
                {
                    "lua_code": lua_code,
                    "io_root": str(tmp_path),
                    "source_authority": LUA_SOURCE_AUTHORITY,
                },
                version="2024.1",
            )
        )


def test_lua_boundary_rejects_hidden_loaders_wrong_authority_and_paths(
    tmp_path: Path,
) -> None:
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    script = isolated / "script.lua"
    script.write_text("return true\n", encoding="utf-8")

    with pytest.raises(OperationContractError, match="supplied verbatim"):
        parse_operation_request(
            _request(
                "lua.executeCoreFile",
                {
                    "script_file": str(script),
                    "io_root": str(isolated),
                    "source_authority": "model_generated",
                },
                version="2025.1",
            )
        )

    with pytest.raises(OperationContractError, match="source or loader"):
        parse_operation_request(
            _request(
                "lua.executeCoreFile",
                {
                    "script_file": str(script),
                    "io_root": str(isolated),
                    "source_authority": LUA_SOURCE_AUTHORITY,
                    "wa_args": {"luaPaths": [str(tmp_path)]},
                },
                version="2025.1",
            )
        )

    outside = tmp_path / "outside.lua"
    outside.write_text("return false\n", encoding="utf-8")
    with pytest.raises(OperationContractError, match="contained by io_root"):
        parse_operation_request(
            _request(
                "lua.executeCoreFile",
                {
                    "script_file": str(outside),
                    "io_root": str(isolated),
                    "source_authority": LUA_SOURCE_AUTHORITY,
                },
                version="2025.1",
            )
        )

    symlink = isolated / "linked.lua"
    symlink.symlink_to(outside)
    with pytest.raises(OperationContractError, match="non-symlink"):
        parse_operation_request(
            _request(
                "lua.executeCoreFile",
                {
                    "script_file": str(symlink),
                    "io_root": str(isolated),
                    "source_authority": LUA_SOURCE_AUTHORITY,
                },
                version="2025.1",
            )
        )


@pytest.mark.parametrize(
    ("operation", "uri"),
    (
        ("debug.setAsserts", "ak.wwise.debug.enableAsserts"),
        ("debug.setAutomationMode", "ak.wwise.debug.enableAutomationMode"),
    ),
)
def test_debug_mode_changes_are_closed_nonretry_transactions(
    operation: str,
    uri: str,
) -> None:
    request = parse_operation_request(
        _request(operation, {"enable": True}, version="2022.1")
    )
    prepared = prepare_operation(request, read_call=_no_read).as_dict()

    assert prepared["dispatch"] == {
        "uri": uri,
        "args": {"enable": True},
        "options": {},
    }
    assert prepared["verification_plan"]["kind"] == "result-schema"
    assert prepared["verification_plan"]["business_state_verified"] is False
    assert prepared["cleanup"]["automatic_retry"] is False
    assert validate_prepared_roles(prepared, read_call=_no_read)["ok"] is True

    verification = verify_prepared_operation(
        prepared,
        execution_result={"result": {}},
        read_call=_no_read,
    )
    assert verification.ok is True
    assert verification.status == "result_schema_checked"
    assert verification.business_state_verified is False


@pytest.mark.parametrize(
    ("operation", "version", "acknowledgement", "uri", "disconnect"),
    (
        (
            "debug.restartWaapiServers",
            "2023.1",
            "restart_waapi_servers",
            "ak.wwise.debug.restartWaapiServers",
            True,
        ),
        (
            "debug.testAssert",
            "2022.1",
            "trigger_debug_assert",
            "ak.wwise.debug.testAssert",
            False,
        ),
        (
            "debug.testCrash",
            "2022.1",
            "crash_wwise_process",
            "ak.wwise.debug.testCrash",
            True,
        ),
    ),
)
def test_dangerous_debug_host_controls_are_explicit_terminal_nonretry_transactions(
    operation: str,
    version: str,
    acknowledgement: str,
    uri: str,
    disconnect: bool,
) -> None:
    request = parse_operation_request(
        _request(
            operation,
            {"acknowledge": acknowledgement},
            version=version,
        )
    )
    prepared = prepare_operation(request, read_call=_no_read).as_dict()

    assert prepared["dispatch"] == {"uri": uri, "args": {}, "options": {}}
    assert prepared["verification_plan"]["kind"] == "host-control-terminal"
    assert prepared["verification_plan"]["expected_disconnect"] is disconnect
    assert prepared["verification_plan"]["generic_verify_allowed"] is False
    assert prepared["cleanup"] == {
        "kind": "none",
        "automatic": False,
        "automatic_retry": False,
        "reconnect": False,
        "process_cleanup": False,
    }
    assert validate_prepared_roles(prepared, read_call=_no_read)["ok"] is True

    with pytest.raises(
        OperationContractError,
        match="exact immutable acknowledgement",
    ):
        parse_operation_request(
            _request(
                operation,
                {"acknowledge": "yes"},
                version=version,
            )
        )


def test_wal_tree_projection_is_deterministic_bounded_and_strict() -> None:
    result = {
        "return": {
            "nodes": {
                "z": {"id": 3, "name": "Z", "type": "Sound"},
                "a": {"id": 1, "name": "A", "type": "Bus"},
                "m": {"id": 2, "name": "M", "type": "Event"},
            }
        }
    }

    assert normalize_wal_tree_result(result, take=2) == {
        "nodes": [
            {"key": "a", "id": 1, "name": "A", "type": "Bus"},
            {"key": "m", "id": 2, "name": "M", "type": "Event"},
        ],
        "returned_count": 2,
        "total_count": 3,
        "possibly_truncated": True,
        "take": 2,
    }

    with pytest.raises(DebugLuaContractError, match="name/type"):
        normalize_wal_tree_result(
            {"return": {"nodes": {"x": {"id": 1, "name": "missing type"}}}},
            take=1,
        )


@pytest.mark.parametrize(
    "invalid_id",
    (
        float("nan"),
        float("inf"),
        float("-inf"),
        1.5,
        -1,
        1 << 32,
        True,
    ),
)
def test_wal_tree_rejects_non_uint32_node_ids(invalid_id: Any) -> None:
    with pytest.raises(
        DebugLuaContractError,
        match="uint32 integer id",
    ) as caught:
        normalize_wal_tree_result(
            {
                "return": {
                    "nodes": {
                        "node": {
                            "id": invalid_id,
                            "name": "Node",
                            "type": "Sound",
                        }
                    }
                }
            },
            take=1,
        )
    json.dumps(caught.value.as_dict(), allow_nan=False)


def test_wal_tree_rejects_the_actual_result_before_unbounded_sorting() -> None:
    nodes = {
        f"node-{index:04d}": {
            "id": index,
            "name": f"Node {index}",
            "type": "Sound",
        }
        for index in range(257)
    }

    with pytest.raises(DebugLuaContractError, match="more than 256 nodes") as caught:
        normalize_wal_tree_result(
            {"return": {"nodes": nodes}},
            take=1,
        )

    assert caught.value.error_code == "LIMIT_EXCEEDED"
    assert caught.value.details == {"node_count": 257, "limit": 256}
