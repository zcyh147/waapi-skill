from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.operation_registry import (  # pyright: ignore[reportMissingImports]
    OPERATION_REQUEST_CONTRACT,
    OperationContractError,
    parse_operation_request,
    prepare_operation,
    validate_prepared_roles,
    verify_prepared_operation,
)


GET_INFO_URI = "ak.wwise.core.getInfo"
GET_COMMANDS_URI = "ak.wwise.ui.commands.getCommands"


def operation_request(
    operation: str,
    arguments: Mapping[str, Any],
    *,
    version: str = "2024.1",
) -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": operation,
        "arguments": dict(arguments),
    }


def test_execute_registry_plan_replays_inventory_and_verifies_only_result_schema() -> None:
    request = parse_operation_request(
        operation_request(
            "ui.commands.execute",
            {
                "command": "SaveProject",
                "objects": [r"\Actor-Mixer Hierarchy\Default Work Unit"],
            },
        )
    )
    prepared = prepare_operation(
        request,
        read_call=lambda *_: pytest.fail("execute preview must not read live state"),
    ).as_dict()

    assert prepared["dispatch"] == {
        "uri": "ak.wwise.ui.commands.execute",
        "args": {
            "command": "SaveProject",
            "objects": [r"\Actor-Mixer Hierarchy\Default Work Unit"],
        },
        "options": {},
    }
    assert prepared["preflight_reads"] == []
    reads: list[str] = []

    def role_read(
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        reads.append(uri)
        assert args == {}
        assert options == {}
        return {"commands": ["Copy", "SaveProject"]}

    role_validation = validate_prepared_roles(prepared, read_call=role_read)
    assert role_validation["ok"] is True
    assert reads == [GET_COMMANDS_URI]

    verification = verify_prepared_operation(
        prepared,
        execution_result={"result": {}},
        read_call=lambda *_: pytest.fail("execute verification has no effect readback"),
    )
    assert verification.status == "result_schema_checked"
    assert verification.business_state_verified is False
    assert verification.verification_strength == "result_schema_only"


@pytest.mark.parametrize(
    ("platform", "mapped"),
    (("x64", "windows"), ("win32", "windows"), ("macosx", "macos")),
)
def test_register_registry_derives_platform_only_from_live_get_info(
    platform: str,
    mapped: str,
) -> None:
    request = parse_operation_request(
        operation_request(
            "ui.commands.register",
            {
                "commands": [
                    {
                        "id": "example.notify",
                        "display_name": "Notify",
                        "handler": {"kind": "notification"},
                    }
                ]
            },
        )
    )
    reads: list[str] = []

    def preview_read(
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        reads.append(uri)
        assert args == {}
        assert options == {}
        return {"isCommandLine": False, "platform": platform}

    prepared = prepare_operation(request, read_call=preview_read).as_dict()
    assert reads == [GET_INFO_URI]
    assert prepared["pre_state"]["ui_command_live_host"] == {
        "isCommandLine": False,
        "platform": platform,
        "mapped_host_platform": mapped,
    }
    assert (
        prepared["pre_state"]["ui_command_plan"]["host_platform"] == mapped
    )
    assert "host_platform" not in prepared["request"]["arguments"]


@pytest.mark.parametrize("platform", ("linux", "", None, "windows"))
def test_register_registry_rejects_unmapped_live_platform(platform: Any) -> None:
    request = parse_operation_request(
        operation_request(
            "ui.commands.register",
            {
                "commands": [
                    {
                        "id": "example.notify",
                        "display_name": "Notify",
                        "handler": {"kind": "notification"},
                    }
                ]
            },
        )
    )
    with pytest.raises(OperationContractError) as error:
        prepare_operation(
            request,
            read_call=lambda *_: {
                "isCommandLine": False,
                "platform": platform,
            },
        )
    assert error.value.error_code == "HOST_PLATFORM_UNAVAILABLE"


def test_register_and_unregister_inventory_postconditions_are_strong() -> None:
    register_request = parse_operation_request(
        operation_request(
            "ui.commands.register",
            {
                "commands": [
                    {
                        "id": "example.notify",
                        "display_name": "Notify",
                        "handler": {"kind": "notification"},
                    }
                ]
            },
        )
    )
    prepared_register = prepare_operation(
        register_request,
        read_call=lambda *_: {
            "isCommandLine": False,
            "platform": "macosx",
        },
    ).as_dict()
    replay_reads = iter(
        (
            {"isCommandLine": False, "platform": "macosx"},
            {"commands": ["Copy"]},
        )
    )
    assert (
        validate_prepared_roles(
            prepared_register,
            read_call=lambda *_: next(replay_reads),
        )["ok"]
        is True
    )
    verified_register = verify_prepared_operation(
        prepared_register,
        execution_result={"result": {}},
        read_call=lambda *_: {"commands": ["Copy", "example.notify"]},
    )
    assert verified_register.status == "verified"
    assert verified_register.business_state_verified is True

    unregister_request = parse_operation_request(
        operation_request(
            "ui.commands.unregister",
            {
                "command_ids": ["example.notify"],
                "acknowledgement": (
                    "unregister_existing_commands_without_definition"
                ),
            },
        )
    )
    prepared_unregister = prepare_operation(
        unregister_request,
        read_call=lambda *_: pytest.fail("unregister preview must not read"),
    ).as_dict()
    assert (
        validate_prepared_roles(
            prepared_unregister,
            read_call=lambda *_: {"commands": ["Copy", "example.notify"]},
        )["ok"]
        is True
    )
    verified_unregister = verify_prepared_operation(
        prepared_unregister,
        execution_result={"result": {}},
        read_call=lambda *_: {"commands": ["Copy"]},
    )
    assert verified_unregister.status == "verified"
    assert verified_unregister.business_state_verified is True
    assert prepared_unregister["cleanup"]["reversible"] is False


def test_descriptor_unregister_is_publicly_reachable_but_not_reversible() -> None:
    request = parse_operation_request(
        operation_request(
            "ui.commands.unregister",
            {
                "commands": [
                    {
                        "id": "example.notify",
                        "display_name": "Notify",
                        "handler": {"kind": "notification"},
                    }
                ]
            },
        )
    )
    prepared = prepare_operation(
        request,
        read_call=lambda *_: {
            "isCommandLine": False,
            "platform": "x64",
        },
    ).as_dict()
    plan = prepared["pre_state"]["ui_command_plan"]

    assert plan["mode"] == "unknown_ownership_descriptors"
    assert plan["host_platform"] == "windows"
    assert prepared["dispatch"] == {
        "uri": "ak.wwise.ui.commands.unregister",
        "args": {"commands": ["example.notify"]},
        "options": {},
    }
    assert prepared["cleanup"]["reversible"] is False
    assert prepared["cleanup"]["dispatch"] is None
    assert plan["runtime_preconditions"]["ownership_known"] is False
    assert plan["runtime_preconditions"]["live_definition_match_proven"] is False
    assert "relationship_sha256" not in plan["request"]
    assert "source_register_plan_sha256" not in plan["request"]
    reads = iter(
        (
            {"isCommandLine": False, "platform": "x64"},
            {"commands": ["Copy", "example.notify"]},
        )
    )
    assert (
        validate_prepared_roles(
            prepared,
            read_call=lambda *_: next(reads),
        )["ok"]
        is True
    )
    verified = verify_prepared_operation(
        prepared,
        execution_result={"result": {}},
        read_call=lambda *_: {"commands": ["Copy"]},
    )
    assert verified.status == "verified"
    assert verified.business_state_verified is True


def test_2025_execute_file_drift_requires_repreview_before_dispatch(
    tmp_path: Path,
) -> None:
    source = tmp_path / "selection.wav"
    source.write_bytes(b"first")
    request = parse_operation_request(
        operation_request(
            "ui.commands.execute",
            {"command": "ImportFiles", "files": [str(source)]},
            version="2025.1",
        )
    )
    prepared = prepare_operation(
        request,
        read_call=lambda *_: pytest.fail("execute preview must not read"),
    ).as_dict()
    source.write_bytes(b"second")

    validation = validate_prepared_roles(
        prepared,
        read_call=lambda *_: {"commands": ["ImportFiles"]},
    )
    assert validation["ok"] is False
    assert validation["status"] == "repreview_required"
    failure_codes = {
        assertion.get("evidence", {}).get("error_code")
        for assertion in validation["assertions"]
        if isinstance(assertion.get("evidence"), Mapping)
    }
    assert "PATH_CHANGED" in failure_codes


def test_console_get_info_cannot_prepare_registration() -> None:
    request = parse_operation_request(
        operation_request(
            "ui.commands.register",
            {
                "commands": [
                    {
                        "id": "example.notify",
                        "display_name": "Notify",
                        "handler": {"kind": "notification"},
                    }
                ]
            },
        )
    )
    with pytest.raises(OperationContractError) as error:
        prepare_operation(
            request,
            read_call=lambda *_: {
                "isCommandLine": True,
                "platform": "x64",
            },
        )
    assert error.value.error_code == "AUTHORING_HOST_REQUIRED"
