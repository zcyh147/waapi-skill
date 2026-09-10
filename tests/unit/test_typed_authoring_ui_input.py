from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from wwise_waapi.authoring_ui_business import (
    append_authoring_ui_command,
    authoring_ui_business_is_complete,
    authoring_ui_command_id,
    materialize_authoring_ui_business_request,
)
from wwise_waapi.authoring_ui_business_cli import (
    AuthoringUiBusinessCliError,
    add_authoring_ui_command_arguments,
    add_authoring_ui_plan_arguments,
    authoring_ui_command_from_namespace,
    authoring_ui_plan_from_namespace,
)
from wwise_waapi.authoring_ui_business_contracts import (
    AUTHORING_UI_BUSINESS_OPERATIONS,
    authoring_ui_business_contract_data,
)
from wwise_waapi.business_adapters import business_adapter
from wwise_waapi.business_declaration_state import BusinessDeclarationSession
from wwise_waapi.business_declarations import (
    BusinessContext,
    BusinessDeclarationError,
)
from wwise_waapi.operation_registry import (
    BUSINESS_DECLARATION_INPUT_MODE,
    operation_business_contract,
    operation_input_mode,
    parse_operation_request,
)
from wwise_waapi.operation_ui_commands import (
    UNREGISTER_EXISTING_ACKNOWLEDGEMENT,
    USER_SUPPLIED_SOURCE_AUTHORITY,
)
from wwise_waapi.typed_operations import (
    draft_operation_request_contract,
    inline_operation_contract,
    materialize_inline_operation_request,
)


VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
OPERATIONS = (
    "ui.captureScreen",
    "ui.commands.execute",
    "ui.commands.register",
    "ui.commands.unregister",
)


def _session(version: str, *, project_id: str | None = None) -> BusinessDeclarationSession:
    return BusinessDeclarationSession.create(
        BusinessContext.create(
            task_authority="da1-" + "1" * 40,
            project_id=project_id or "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
            project_path="/fixtures/SampleProject.wproj",
            wwise_version=version,
            wwise_build=f"{version}.fixture",
        )
    )


def _plan_session(
    operation: str,
    version: str,
    plan: dict[str, object],
) -> BusinessDeclarationSession:
    session = _session(version).with_settings({"ui_plan": plan})
    assert business_adapter(operation).is_complete(session)
    return session


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("version", VERSIONS)
def test_every_authoring_ui_lane_has_one_deep_business_entry(
    operation: str,
    version: str,
) -> None:
    contract = authoring_ui_business_contract_data(operation, version)
    registry_contract = operation_business_contract(operation, version)

    assert set(AUTHORING_UI_BUSINESS_OPERATIONS) == set(OPERATIONS)
    assert operation_input_mode(operation, version) == BUSINESS_DECLARATION_INPUT_MODE
    assert registry_contract == contract
    assert contract["legacy_inline_typed_public"] is False
    assert contract["legacy_composer_public"] is False
    assert contract["binding"]["available"] is False
    assert contract["safety"]["fresh_command_inventory_owner"] == (
        "not_applicable"
        if operation == "ui.captureScreen"
        else "gateway_pre_dispatch"
    )
    if operation == "ui.commands.execute":
        assert "fresh_command_inventory" not in contract["responsibility_split"][
            "agent"
        ]
        assert "revalidate_fresh_inventory" in contract["responsibility_split"][
            "gateway"
        ]
    adapter = business_adapter(operation)
    assert adapter.family == "authoring-ui-business"
    assert adapter.accepts_update_command("draft-declare-ui-plan")
    assert adapter.accepts_update_command("draft-add-ui-command") is (
        operation == "ui.commands.register"
    )
    assert ("add-ui-command" in adapter.active_projection_actions) is (
        operation == "ui.commands.register"
    )


@pytest.mark.parametrize("operation", ("ui.captureScreen", "ui.commands.execute"))
def test_retired_inline_typed_entry_cannot_reopen_ui_surface(operation: str) -> None:
    with pytest.raises(ValueError, match="No inline typed adapter"):
        inline_operation_contract(operation, "2025.1")
    with pytest.raises(ValueError, match="No inline typed adapter"):
        materialize_inline_operation_request(operation, "2025.1", {})


@pytest.mark.parametrize(
    "operation",
    ("ui.commands.register", "ui.commands.unregister"),
)
def test_retired_composer_entry_cannot_reopen_ui_surface(operation: str) -> None:
    with pytest.raises(ValueError, match="No typed Draft adapter"):
        draft_operation_request_contract(operation, "2025.1")


@pytest.mark.parametrize("version", VERSIONS)
def test_capture_business_outcome_compiles_to_canonical_rectangle(version: str) -> None:
    session = _plan_session(
        "ui.captureScreen",
        version,
        {
            "view_name": "Project Explorer",
            "view_channel": 2,
            "rectangle": {"x": 10, "y": 20, "width": 640, "height": 480},
        },
    )

    request = materialize_authoring_ui_business_request("ui.captureScreen", session)

    assert request["arguments"] == {
        "view_name": "Project Explorer",
        "view_channel": 2,
        "rect": {"x": 10, "y": 20, "width": 640, "height": 480},
    }
    parse_operation_request(request, expected_version=version)


@pytest.mark.parametrize("version", VERSIONS)
def test_execute_business_choice_compiles_without_native_field_authorship(
    version: str,
    tmp_path: Path,
) -> None:
    plan: dict[str, object] = {
        "command_id": "SaveProject",
        "objects": ["{11111111-1111-1111-1111-111111111111}"],
        "platforms": ["Windows"],
        "value": False,
    }
    if version == "2025.1":
        source = tmp_path / "input file.wav"
        source.write_bytes(b"RIFF")
        plan["files"] = [str(source)]
    session = _plan_session("ui.commands.execute", version, plan)

    request = materialize_authoring_ui_business_request("ui.commands.execute", session)

    assert request["arguments"]["command"] == "SaveProject"
    assert request["arguments"]["value"] is False
    assert "command_id" not in request["arguments"]
    if version == "2025.1":
        assert request["arguments"]["files"] == [str(source)]
    parse_operation_request(request, expected_version=version)


def test_execute_files_expose_an_explicit_version_boundary() -> None:
    session = _plan_session(
        "ui.commands.execute",
        "2024.1",
        {"command_id": "Import", "files": ["/tmp/source.wav"]},
    )

    with pytest.raises(BusinessDeclarationError) as exc_info:
        materialize_authoring_ui_business_request("ui.commands.execute", session)

    assert exc_info.value.repair["error_code"] == "VERSION_BEHAVIOR_BOUNDARY"
    assert exc_info.value.repair["field"] == "files"


def test_register_is_count_bound_and_gateway_derives_stable_project_ids(
    tmp_path: Path,
) -> None:
    program = tmp_path / "owned program"
    program.write_bytes(b"program")
    script = tmp_path / "owned script.lua"
    script.write_text("return 1\n", encoding="utf-8")
    session = _session("2025.1").with_settings(
        {"ui_plan": {"command_count": 3, "commands": []}}
    )
    assert not authoring_ui_business_is_complete("ui.commands.register", session)

    session = append_authoring_ui_command(
        session,
        {
            "key": "notify-selection",
            "display_name": "Notify",
            "handler": {"kind": "notification"},
        },
    )
    session = append_authoring_ui_command(
        session,
        {
            "key": "open-owned-tool",
            "display_name": "Open Tool",
            "handler": {
                "kind": "program",
                "program_path": str(program),
                "start_mode": "SingleSelectionSingleProcess",
                "redirect_outputs": False,
            },
            "default_shortcut": "Ctrl+Alt+O",
            "context_menu": {
                "base_path": ["WAAPI Skill", "Tools"],
                "visible_for": ["Sound"],
                "enabled_for": ["Sound"],
            },
        },
    )
    session = append_authoring_ui_command(
        session,
        {
            "key": "inspect-owned-script",
            "display_name": "Inspect",
            "handler": {
                "kind": "lua_script",
                "lua_script_path": str(script),
                "lua_module_directories": [str(tmp_path)],
                "lua_selected_return": ["id", "name"],
            },
            "main_menu": {"base_path": ["WAAPI Skill", "Inspect"]},
        },
    )
    assert authoring_ui_business_is_complete("ui.commands.register", session)

    request = materialize_authoring_ui_business_request("ui.commands.register", session)
    commands = request["arguments"]["commands"]

    assert len(commands) == 3
    assert request["arguments"]["source_authority"] == USER_SUPPLIED_SOURCE_AUTHORITY
    assert commands[0]["id"] == authoring_ui_command_id(session, "notify-selection")
    assert commands[1]["id"].startswith("waapi.skill.open.owned.tool.")
    assert commands[2]["handler"]["lua_script_path"] == str(script)
    assert all("key" not in command for command in commands)
    assert authoring_ui_command_id(session, "notify-selection") == (
        authoring_ui_command_id(_session("2025.1"), "notify-selection")
    )
    assert authoring_ui_command_id(
        _session(
            "2025.1",
            project_id="{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
        ),
        "notify-selection",
    ) != commands[0]["id"]
    parse_operation_request(request, expected_version="2025.1")


@pytest.mark.parametrize("version", ("2021.1", "2022.1"))
def test_register_lua_handler_has_a_closed_version_repair(version: str) -> None:
    session = _session(version).with_settings(
        {
            "ui_plan": {
                "command_count": 1,
                "commands": [
                    {
                        "key": "lua",
                        "display_name": "Lua",
                        "handler": {
                            "kind": "lua_script",
                            "lua_script_path": "/tmp/tool.lua",
                        },
                    }
                ],
            }
        }
    )

    with pytest.raises(BusinessDeclarationError) as exc_info:
        materialize_authoring_ui_business_request("ui.commands.register", session)

    assert exc_info.value.repair["error_code"] == "VERSION_BEHAVIOR_BOUNDARY"


def test_register_rejects_duplicate_business_keys_before_native_ids_exist() -> None:
    session = _session("2025.1").with_settings(
        {"ui_plan": {"command_count": 2, "commands": []}}
    )
    session = append_authoring_ui_command(
        session,
        {"key": "Open Tool", "display_name": "One", "handler": {"kind": "notification"}},
    )

    with pytest.raises(BusinessDeclarationError) as exc_info:
        append_authoring_ui_command(
            session,
            {"key": "open tool", "display_name": "Two", "handler": {"kind": "notification"}},
        )

    assert exc_info.value.repair["error_code"] == "DUPLICATE_BUSINESS_KEY"


def test_register_rejects_generic_program_arguments_on_the_append_step(
    tmp_path: Path,
) -> None:
    program = tmp_path / "owned-program"
    program.write_bytes(b"program")
    session = _session("2025.1").with_settings(
        {"ui_plan": {"command_count": 2, "commands": []}}
    )

    with pytest.raises(BusinessDeclarationError) as exc_info:
        append_authoring_ui_command(
            session,
            {
                "key": "parameterized-program",
                "display_name": "Parameterized program",
                "handler": {
                    "kind": "program",
                    "program_path": str(program),
                    "argument_tokens": ["--object", "${id}"],
                },
            },
        )

    assert exc_info.value.repair["error_code"] == (
        "PROGRAM_ARGUMENTS_UNSUPPORTED"
    )
    assert session.revision == 1


@pytest.mark.parametrize("version", VERSIONS)
def test_unregister_owned_keys_derives_ids_and_hidden_acknowledgement(version: str) -> None:
    session = _plan_session(
        "ui.commands.unregister",
        version,
        {"registered_command_keys": ["notify", "inspect"]},
    )

    request = materialize_authoring_ui_business_request("ui.commands.unregister", session)

    assert request["arguments"] == {
        "command_ids": [
            authoring_ui_command_id(session, "notify"),
            authoring_ui_command_id(session, "inspect"),
        ],
        "acknowledgement": UNREGISTER_EXISTING_ACKNOWLEDGEMENT,
    }
    parse_operation_request(request, expected_version=version)


def test_unregister_existing_ids_requires_business_confirmation_but_derives_literal() -> None:
    session = _plan_session(
        "ui.commands.unregister",
        "2025.1",
        {
            "existing_command_ids": ["third.party.command"],
            "confirm_unknown_ownership": True,
        },
    )

    request = materialize_authoring_ui_business_request("ui.commands.unregister", session)

    assert request["arguments"] == {
        "command_ids": ["third.party.command"],
        "acknowledgement": UNREGISTER_EXISTING_ACKNOWLEDGEMENT,
    }
    assert "confirm_unknown_ownership" not in request["arguments"]
    parse_operation_request(request, expected_version="2025.1")


def _parser(*, command: bool) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    if command:
        add_authoring_ui_command_arguments(parser)
    else:
        add_authoring_ui_plan_arguments(parser)
    return parser


def test_cli_translates_business_terms_without_native_payload_fields() -> None:
    plan_args = _parser(command=False).parse_args(
        [
            "--command-id",
            "SaveProject",
            "--command-object",
            "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
            "--value",
            "boolean",
            "false",
        ]
    )
    command_args = _parser(command=True).parse_args(
        [
            "--key",
            "inspect",
            "--display-name",
            "Inspect",
            "--handler-kind",
            "lua_script",
            "--handler-path",
            "/tmp/inspect.lua",
            "--argument-token=--mode",
            "--argument-token",
            "safe",
            "--main-menu-segment",
            "WAAPI Skill",
        ]
    )

    assert authoring_ui_plan_from_namespace(
        plan_args,
        operation="ui.commands.execute",
    ) == {
        "command_id": "SaveProject",
        "objects": ["{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"],
        "value": False,
    }
    assert authoring_ui_command_from_namespace(command_args) == {
        "key": "inspect",
        "display_name": "Inspect",
        "handler": {
            "kind": "lua_script",
            "lua_script_path": "/tmp/inspect.lua",
            "argument_tokens": ["--mode", "safe"],
        },
        "main_menu": {"base_path": ["WAAPI Skill"]},
    }


def test_cli_rejects_cross_operation_and_unknown_ownership_shortcuts() -> None:
    args = _parser(command=False).parse_args(["--existing-command-id", "third.party"])
    with pytest.raises(AuthoringUiBusinessCliError, match="requires"):
        authoring_ui_plan_from_namespace(args, operation="ui.commands.unregister")

    args = _parser(command=False).parse_args(
        ["--view-name", "Project Explorer", "--command-count", "1"]
    )
    with pytest.raises(AuthoringUiBusinessCliError, match="does not accept"):
        authoring_ui_plan_from_namespace(args, operation="ui.captureScreen")


@pytest.mark.parametrize(
    "irrelevant",
    (
        ["--argument-token", "ignored"],
        ["--working-directory", "/tmp"],
        ["--start-mode", "SingleSelectionSingleProcess"],
    ),
)
def test_cli_rejects_irrelevant_notification_handler_fields(
    irrelevant: list[str],
) -> None:
    args = _parser(command=True).parse_args(
        [
            "--key",
            "notify",
            "--display-name",
            "Notify",
            "--handler-kind",
            "notification",
            *irrelevant,
        ]
    )

    with pytest.raises(
        AuthoringUiBusinessCliError,
        match="notification handlers do not accept",
    ):
        authoring_ui_command_from_namespace(args)
