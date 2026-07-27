from __future__ import annotations

import copy
import os
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

import wwise_waapi.operation_ui_commands as ui_commands  # pyright: ignore[reportMissingImports]
from wwise_waapi.canonical import canonical_sha256  # pyright: ignore[reportMissingImports]
from wwise_waapi.operation_ui_commands import (  # pyright: ignore[reportMissingImports]
    MAX_ARGUMENT_TOKENS,
    MAX_COMMANDS_PER_PLAN,
    MAX_OBJECT_ARGUMENTS,
    UNREGISTER_EXISTING_ACKNOWLEDGEMENT,
    USER_SUPPLIED_SOURCE_AUTHORITY,
    UiCommandContractError,
    build_ui_command_execute_plan,
    build_ui_commands_register_plan,
    build_ui_commands_unregister_descriptors_plan,
    build_ui_commands_unregister_existing_plan,
    build_ui_commands_unregister_plan,
    revalidate_ui_command_file_proofs,
    validate_empty_ui_command_result,
    validate_ui_command_plan,
    validate_ui_command_runtime_preconditions,
    verify_ui_command_inventory_postcondition,
)


SUPPORTED_VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")


@pytest.mark.parametrize("version", SUPPORTED_VERSIONS)
def test_execute_plan_is_closed_versioned_and_live_inventory_bound(
    version: str,
) -> None:
    plan = build_ui_command_execute_plan(
        version=version,
        command="ShowPropertyEditor(Deprecated)1",
        objects=[
            "{01234567-89AB-CDEF-0123-456789ABCDEF}",
            r"\Actor-Mixer Hierarchy\Default Work Unit\Footstep",
        ],
        platforms=["Mac"],
        value=None,
    )

    assert validate_ui_command_plan(plan) == plan
    assert plan["safety"] == {
        "arbitrary_waapi_payload_allowed": False,
        "automatic_retry": False,
        "model_generated_code_allowed": False,
        "raw_shell_string_allowed": False,
        "requires_preview_authorization": True,
        "accepted_authorization_modes": [
            "explicit_confirmation",
            "policy_authorization",
        ],
        "same_turn_execution_allowed_by_policy": True,
        "structured_argument_tokens_required": True,
    }
    assert plan["dispatch"] == {
        "arguments": {
            "command": "ShowPropertyEditor(Deprecated)1",
            "objects": [
                "{01234567-89AB-CDEF-0123-456789ABCDEF}",
                r"\Actor-Mixer Hierarchy\Default Work Unit\Footstep",
            ],
            "platforms": ["Mac"],
            "value": None,
        },
        "options": {},
        "uri": "ak.wwise.ui.commands.execute",
    }
    guard = plan["runtime_preconditions"]["command_inventory"]
    assert guard["source_uri"] == "ak.wwise.ui.commands.getCommands"
    assert guard["timing"] == "immediately_before_dispatch"
    assert guard["expected_membership"] == "present"
    assert plan["verification"] == {
        "command_effect_readback_available": False,
        "expected_result": {},
        "kind": "result_schema_only",
        "pre_dispatch_inventory_is_effect_verification": False,
        "uri": "ak.wwise.ui.commands.execute",
    }

    evidence = validate_ui_command_runtime_preconditions(
        plan,
        {
            "commands": [
                "Copy",
                "ShowPropertyEditor(Deprecated)1",
            ]
        },
    )
    assert evidence["passed"] is True
    assert evidence["command_inventory"]["present_command_ids"] == [
        "ShowPropertyEditor(Deprecated)1"
    ]
    result_evidence = validate_empty_ui_command_result(plan, {})
    assert result_evidence["effect_verified"] is False
    assert result_evidence["verification_strength"] == "result_schema_only"


def test_execute_plan_fails_closed_for_missing_command_raw_fields_and_limits() -> None:
    plan = build_ui_command_execute_plan(
        version="2022.1",
        command="SaveProject",
    )
    with pytest.raises(
        UiCommandContractError,
        match="does not satisfy",
    ) as missing:
        validate_ui_command_runtime_preconditions(
            plan,
            {"commands": ["Copy", "Paste"]},
        )
    assert missing.value.error_code == "COMMAND_INVENTORY_PRECONDITION_FAILED"

    invalid_requests = [
        {"version": "2022.1", "command": "SaveProject", "objects": ["x"] * (MAX_OBJECT_ARGUMENTS + 1)},
        {"version": "2022.1", "command": "SaveProject", "objects": [{"raw": True}]},
        {"version": "2022.1", "command": "SaveProject", "value": {"raw": True}},
        {"version": "2099.1", "command": "SaveProject"},
    ]
    for request in invalid_requests:
        with pytest.raises(UiCommandContractError):
            build_ui_command_execute_plan(**request)

    tampered = copy.deepcopy(plan)
    tampered["dispatch"]["arguments"]["raw"] = {"uri": "anything"}
    with pytest.raises(UiCommandContractError) as error:
        validate_ui_command_plan(tampered)
    assert error.value.error_code == "PLAN_TAMPERED"


@pytest.mark.parametrize("version", SUPPORTED_VERSIONS)
def test_execute_files_are_2025_only_and_every_path_is_sealed(
    version: str,
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    first.write_bytes(b"RIFF-first")
    second.write_bytes(b"RIFF-second")
    files = [str(first), str(second)]

    if version != "2025.1":
        with pytest.raises(UiCommandContractError) as boundary:
            build_ui_command_execute_plan(
                version=version,
                command="ImportFiles",
                files=files,
            )
        assert boundary.value.error_code == "VERSION_BEHAVIOR_BOUNDARY"
        assert boundary.value.details == {
            "supported_versions": ["2025.1"],
            "version": version,
        }
        return

    plan = build_ui_command_execute_plan(
        version=version,
        command="ImportFiles",
        files=files,
    )
    assert plan["request"]["files"] == files
    assert plan["dispatch"]["arguments"]["files"] == files
    proofs = plan["runtime_preconditions"]["file_proofs"]
    assert [
        (row["command_id"], row["request_field"], row["proof"]["path"])
        for row in proofs
    ] == [
        ("ImportFiles", "files[0]", str(first)),
        ("ImportFiles", "files[1]", str(second)),
    ]
    for row in proofs:
        proof = row["proof"]
        assert proof["role"] == "command_file"
        assert proof["kind"] == "file"
        assert proof["executable"] is False
        assert proof["size"] > 0
        assert isinstance(proof["mtime_ns"], int)
        assert isinstance(proof["inode"], int)
        assert len(proof["content_sha256"]) == 64
        assert len(proof["proof_sha256"]) == 64
    assert validate_ui_command_plan(plan) == plan
    assert len(revalidate_ui_command_file_proofs(plan)) == 2
    evidence = validate_ui_command_runtime_preconditions(
        plan,
        {"commands": ["ImportFiles"]},
    )
    assert evidence["passed"] is True
    assert len(evidence["file_proofs"]) == 2

    unproved = copy.deepcopy(plan)
    unproved["runtime_preconditions"]["file_proofs"] = []
    unproved["plan_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in unproved.items()
            if key != "plan_sha256"
        }
    )
    with pytest.raises(UiCommandContractError) as missing_proofs:
        validate_ui_command_plan(unproved)
    assert missing_proofs.value.error_code == "INVALID_PLAN"


def test_execute_files_fail_pre_dispatch_when_content_drifts(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"version-one")
    plan = build_ui_command_execute_plan(
        version="2025.1",
        command="ImportFiles",
        files=[str(source)],
    )

    source.write_bytes(b"version-two")
    with pytest.raises(UiCommandContractError) as changed:
        validate_ui_command_runtime_preconditions(
            plan,
            {"commands": ["ImportFiles"]},
        )
    assert changed.value.error_code == "PATH_CHANGED"
    assert changed.value.details["command_id"] == "ImportFiles"
    assert changed.value.details["request_field"] == "files[0]"
    assert "content_sha256" in changed.value.details["changed_fields"]


def test_execute_files_enforce_count_path_and_byte_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files: list[str] = []
    for index in range(ui_commands.MAX_COMMAND_FILES):
        path = tmp_path / f"{index:02d}.wav"
        path.write_bytes(bytes([index]))
        files.append(str(path))
    plan = build_ui_command_execute_plan(
        version="2025.1",
        command="ImportFiles",
        files=files,
    )
    assert len(plan["runtime_preconditions"]["file_proofs"]) == 64

    extra = tmp_path / "overflow.wav"
    extra.write_bytes(b"x")
    with pytest.raises(UiCommandContractError) as count:
        build_ui_command_execute_plan(
            version="2025.1",
            command="ImportFiles",
            files=[*files, str(extra)],
        )
    assert count.value.error_code == "LIMIT_EXCEEDED"
    assert count.value.details["limit"] == 64

    with pytest.raises(UiCommandContractError) as relative:
        build_ui_command_execute_plan(
            version="2025.1",
            command="ImportFiles",
            files=["relative.wav"],
        )
    assert relative.value.error_code == "INVALID_PATH"

    directory = tmp_path / "directory"
    directory.mkdir()
    with pytest.raises(UiCommandContractError) as wrong_kind:
        build_ui_command_execute_plan(
            version="2025.1",
            command="ImportFiles",
            files=[str(directory)],
        )
    assert wrong_kind.value.error_code == "INVALID_PATH_KIND"

    symlink = tmp_path / "link.wav"
    symlink.symlink_to(extra)
    with pytest.raises(UiCommandContractError) as linked:
        build_ui_command_execute_plan(
            version="2025.1",
            command="ImportFiles",
            files=[str(symlink)],
        )
    assert linked.value.error_code == "SYMLINK_NOT_ALLOWED"

    per_file = tmp_path / "per-file.wav"
    per_file.write_bytes(b"12345")
    monkeypatch.setattr(ui_commands, "MAX_COMMAND_FILE_BYTES", 4)
    with pytest.raises(UiCommandContractError) as per_file_limit:
        build_ui_command_execute_plan(
            version="2025.1",
            command="ImportFiles",
            files=[str(per_file)],
        )
    assert per_file_limit.value.error_code == "LIMIT_EXCEEDED"
    assert per_file_limit.value.details["limit"] == 4

    first = tmp_path / "aggregate-a.wav"
    second = tmp_path / "aggregate-b.wav"
    first.write_bytes(b"123456")
    second.write_bytes(b"abcdef")
    monkeypatch.setattr(ui_commands, "MAX_COMMAND_FILE_BYTES", 8)
    monkeypatch.setattr(ui_commands, "MAX_COMMAND_FILES_TOTAL_BYTES", 10)
    with pytest.raises(UiCommandContractError) as aggregate:
        build_ui_command_execute_plan(
            version="2025.1",
            command="ImportFiles",
            files=[str(first), str(second)],
        )
    assert aggregate.value.error_code == "LIMIT_EXCEEDED"
    assert aggregate.value.details == {"limit": 10, "size": 12}


def test_register_program_plan_uses_final_file_proof_with_no_argument_channel(
    tmp_path: Path,
) -> None:
    program = tmp_path / "safe tool"
    program.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    program.chmod(0o700)
    working_directory = tmp_path / "working"
    working_directory.mkdir()
    descriptors = [
        {
            "id": "example.notify.selection",
            "display_name": "Notify selection",
            "handler": {"kind": "notification"},
            "main_menu": {"base_path": ["Extra", "Skill tools"]},
        },
        {
            "id": "example.open.asset",
            "display_name": "Open selected asset",
            "handler": {
                "kind": "program",
                "program_path": str(program),
                "argument_tokens": [],
                "working_directory": str(working_directory),
                "start_mode": "SingleSelectionSingleProcess",
                "redirect_outputs": False,
            },
            "context_menu": {
                "base_path": ["Editors"],
                "enabled_for": ["Sound", "MusicTrack"],
                "visible_for": ["Sound", "MusicTrack"],
            },
        },
    ]

    with pytest.raises(UiCommandContractError) as missing_authority:
        build_ui_commands_register_plan(
            version="2022.1",
            host_platform="macos",
            commands=descriptors,
        )
    assert missing_authority.value.error_code == "SOURCE_AUTHORITY_REQUIRED"
    assert missing_authority.value.details[
        "runtime_can_prove_conversational_provenance"
    ] is False

    plan = build_ui_commands_register_plan(
        version="2022.1",
        host_platform="macos",
        commands=descriptors,
        source_authority=USER_SUPPLIED_SOURCE_AUTHORITY,
    )
    assert validate_ui_command_plan(plan) == plan
    native = plan["dispatch"]["arguments"]["commands"]
    assert [row["id"] for row in native] == [
        "example.notify.selection",
        "example.open.asset",
    ]
    program_row = native[1]
    assert program_row["program"] == str(program)
    assert "args" not in program_row
    assert program_row["cwd"] == str(working_directory)
    assert "argument_tokens" not in program_row
    assert "payload" not in program_row
    assert plan["request"]["commands"][1]["handler"]["argument_tokens"] == []
    assert (
        plan["request"]["source_authority"]
        == USER_SUPPLIED_SOURCE_AUTHORITY
    )
    authority = plan["runtime_preconditions"]["source_authority"]
    assert authority == {
        "assertion": USER_SUPPLIED_SOURCE_AUTHORITY,
        "eligible_only_when_current_user_message_supplied_exact_existing_path_and_fields": True,
        "model_generated_repaired_or_wrapped_code_eligible": False,
        "required": True,
        "runtime_can_prove_conversational_provenance": False,
    }
    assert len(plan["runtime_preconditions"]["file_proofs"]) == 2
    assert revalidate_ui_command_file_proofs(plan)

    command_ids = [row["id"] for row in native]
    assert plan["cleanup"]["dispatch"] == {
        "arguments": {"commands": command_ids},
        "options": {},
        "uri": "ak.wwise.ui.commands.unregister",
    }
    pre = validate_ui_command_runtime_preconditions(
        plan,
        {"commands": ["Copy", "Paste"]},
    )
    assert pre["passed"] is True
    post = verify_ui_command_inventory_postcondition(
        plan,
        {"commands": ["Copy", *command_ids]},
    )
    assert post["passed"] is True


def test_unbound_register_plan_cannot_claim_reversible_unregister() -> None:
    register = build_ui_commands_register_plan(
        version="2025.1",
        host_platform="macos",
        commands=[
            {
                "id": "example.notify",
                "display_name": "Notify",
                "handler": {"kind": "notification"},
            }
        ],
    )

    with pytest.raises(UiCommandContractError) as error:
        build_ui_commands_unregister_plan(register)

    assert error.value.error_code == "VERIFIED_REGISTER_TRANSACTION_REQUIRED"
    assert error.value.details == {
        "source_register_plan_sha256": register["plan_sha256"],
        "standalone_inverse_supported": False,
    }


def test_descriptor_unregister_is_unknown_ownership_and_non_reversible(
    tmp_path: Path,
) -> None:
    program = tmp_path / "processor"
    program.write_bytes(b"safe executable")
    program.chmod(0o700)
    descriptors = [
        {
            "id": "example.processor",
            "display_name": "Process selected object",
            "handler": {
                "kind": "program",
                "program_path": str(program),
                "argument_tokens": [],
            },
        }
    ]
    unregister = build_ui_commands_unregister_descriptors_plan(
        version="2025.1",
        host_platform="macos",
        source_authority=USER_SUPPLIED_SOURCE_AUTHORITY,
        commands=descriptors,
    )

    assert validate_ui_command_plan(unregister) == unregister
    assert unregister["mode"] == "unknown_ownership_descriptors"
    assert unregister["dispatch"] == {
        "arguments": {"commands": ["example.processor"]},
        "options": {},
        "uri": "ak.wwise.ui.commands.unregister",
    }
    assert unregister["cleanup"]["dispatch"] is None
    assert unregister["cleanup"]["reversible"] is False
    assert unregister["runtime_preconditions"]["ownership_known"] is False
    assert (
        unregister["runtime_preconditions"]["live_definition_match_proven"]
        is False
    )
    assert unregister["runtime_preconditions"]["file_proofs"]
    assert "relationship_sha256" not in unregister["request"]
    assert "source_register_plan_sha256" not in unregister["request"]
    assert (
        unregister["request"]["source_authority"]
        == USER_SUPPLIED_SOURCE_AUTHORITY
    )
    assert unregister["runtime_preconditions"]["source_authority"][
        "runtime_can_prove_conversational_provenance"
    ] is False
    assert revalidate_ui_command_file_proofs(unregister)

    validate_ui_command_runtime_preconditions(
        unregister,
        {"commands": ["example.processor"]},
    )
    verified = verify_ui_command_inventory_postcondition(
        unregister,
        {"commands": ["Copy"]},
    )
    assert verified["absent_command_ids"] == ["example.processor"]


def test_existing_id_unregister_is_acknowledged_and_explicitly_not_reversible() -> None:
    with pytest.raises(UiCommandContractError) as error:
        build_ui_commands_unregister_existing_plan(
            version="2024.1",
            command_ids=["third.party.command"],
            acknowledgement="yes",
        )
    assert error.value.error_code == "ACKNOWLEDGEMENT_REQUIRED"

    plan = build_ui_commands_unregister_existing_plan(
        version="2024.1",
        command_ids=["third.party.command"],
        acknowledgement=UNREGISTER_EXISTING_ACKNOWLEDGEMENT,
    )
    assert validate_ui_command_plan(plan) == plan
    assert plan["cleanup"]["dispatch"] is None
    assert plan["cleanup"]["reversible"] is False
    assert plan["runtime_preconditions"]["ownership_known"] is False
    validate_ui_command_runtime_preconditions(
        plan,
        {"commands": ["third.party.command"]},
    )
    verified = verify_ui_command_inventory_postcondition(
        plan,
        {"commands": ["Copy"]},
    )
    assert verified["passed"] is True


def test_lua_registration_is_versioned_and_accepts_only_existing_script_paths(
    tmp_path: Path,
) -> None:
    script = tmp_path / "user_owned.lua"
    script.write_text("return true\n", encoding="utf-8")
    modules = tmp_path / "lua_modules"
    modules.mkdir()
    descriptor = {
        "id": "example.lua.inspect",
        "display_name": "Inspect selection",
        "handler": {
            "kind": "lua_script",
            "lua_script_path": str(script),
            "argument_tokens": ["--selection", "${id}"],
            "lua_module_directories": [str(modules)],
            "lua_selected_return": ["id", "name", "path"],
        },
    }

    for version in ("2021.1", "2022.1"):
        with pytest.raises(UiCommandContractError) as error:
            build_ui_commands_register_plan(
                version=version,
                host_platform="macos",
                commands=[descriptor],
                source_authority=USER_SUPPLIED_SOURCE_AUTHORITY,
            )
        assert error.value.error_code == "VERSION_BEHAVIOR_BOUNDARY"

    for version in ("2023.1", "2024.1", "2025.1"):
        plan = build_ui_commands_register_plan(
            version=version,
            host_platform="macos",
            commands=[descriptor],
            source_authority=USER_SUPPLIED_SOURCE_AUTHORITY,
        )
        native = plan["dispatch"]["arguments"]["commands"][0]
        assert native["luaScript"] == str(script)
        assert native["luaPaths"] == [f"{modules}/?.lua"]
        assert native["luaSelectedReturn"] == ["id", "name", "path"]
        assert "script_source" not in plan["request"]["commands"][0]["handler"]
        assert validate_ui_command_plan(plan) == plan


def test_register_rejects_raw_shell_fields_interpreters_and_unbounded_batches(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "tool"
    executable.write_bytes(b"tool")
    executable.chmod(0o700)
    base = {
        "id": "example.tool",
        "display_name": "Tool",
        "handler": {
            "kind": "program",
            "program_path": str(executable),
        },
    }
    invalid = [
        {**base, "handler": {**base["handler"], "args": "--raw && rm -rf /"}},
        {**base, "handler": {**base["handler"], "script_source": "print('x')"}},
        {**base, "payload": {"uri": "ak.wwise.core.object.delete"}},
        {
            **base,
            "handler": {
                **base["handler"],
                "argument_tokens": ["x"] * (MAX_ARGUMENT_TOKENS + 1),
            },
        },
    ]
    for descriptor in invalid:
        with pytest.raises(UiCommandContractError):
            build_ui_commands_register_plan(
                version="2025.1",
                host_platform="macos",
                commands=[descriptor],
            )

    shell = tmp_path / "bash"
    shell.write_bytes(b"shell")
    shell.chmod(0o700)
    with pytest.raises(UiCommandContractError) as shell_error:
        build_ui_commands_register_plan(
            version="2025.1",
            host_platform="macos",
            commands=[
                {
                    **base,
                    "handler": {
                        "kind": "program",
                        "program_path": str(shell),
                    },
                }
            ],
        )
    assert shell_error.value.error_code == "SHELL_EXECUTABLE_NOT_ALLOWED"

    with pytest.raises(UiCommandContractError, match="non-empty bounded array"):
        build_ui_commands_register_plan(
            version="2025.1",
            host_platform="macos",
            commands=[],
        )
    with pytest.raises(UiCommandContractError):
        build_ui_commands_register_plan(
            version="2025.1",
            host_platform="macos",
            commands=[base] * (MAX_COMMANDS_PER_PLAN + 1),
        )


@pytest.mark.parametrize(
    "executable_name",
    (
        "env",
        "python3",
        "node",
        "osascript",
        "xcrun",
        "open",
        "java",
        "dotnet",
        "busybox",
        "nohup",
        "powershell.exe",
        "ssh",
        "sqlite3",
    ),
)
def test_register_rejects_generic_interpreters_launchers_and_prefixes(
    tmp_path: Path,
    executable_name: str,
) -> None:
    executable = tmp_path / executable_name
    executable.write_bytes(b"generic execution host")
    executable.chmod(0o700)

    with pytest.raises(UiCommandContractError) as rejected:
        build_ui_commands_register_plan(
            version="2025.1",
            host_platform="macos",
            source_authority=USER_SUPPLIED_SOURCE_AUTHORITY,
            commands=[
                {
                    "id": "example.indirect",
                    "display_name": "Indirect execution",
                    "handler": {
                        "kind": "program",
                        "program_path": str(executable),
                        "argument_tokens": [],
                    },
                }
            ],
        )

    assert rejected.value.error_code in {
        "GENERIC_EXECUTION_HOST_NOT_ALLOWED",
        "SHELL_EXECUTABLE_NOT_ALLOWED",
    }


@pytest.mark.parametrize(
    "tokens",
    (
        ["safe"],
        ["--asset", "${id}"],
        ["PAYLOAD=/tmp/unproved.py"],
        ["--loader=/tmp/loader.js"],
        ["-c", "print(1)"],
        ["@/tmp/response.rsp"],
        ["/tmp/unproved.py"],
        ["relative/payload"],
        ["payload.lua"],
    ),
)
def test_register_rejects_every_nonempty_generic_program_argument_list(
    tmp_path: Path,
    tokens: list[str],
) -> None:
    executable = tmp_path / "final-proved-tool"
    executable.write_bytes(b"final executable")
    executable.chmod(0o700)

    with pytest.raises(UiCommandContractError) as rejected:
        build_ui_commands_register_plan(
            version="2025.1",
            host_platform="macos",
            source_authority=USER_SUPPLIED_SOURCE_AUTHORITY,
            commands=[
                {
                    "id": "example.direct",
                    "display_name": "Direct execution",
                    "handler": {
                        "kind": "program",
                        "program_path": str(executable),
                        "argument_tokens": tokens,
                    },
                }
            ],
        )

    assert rejected.value.error_code == "PROGRAM_ARGUMENTS_UNSUPPORTED"
    assert rejected.value.details == {
        "argument_count": len(tokens),
        "closed_adapter_required": True,
        "generic_program_argument_tokens_allowed": False,
    }


def test_redirect_outputs_is_windows_only(tmp_path: Path) -> None:
    executable = tmp_path / "tool"
    executable.write_bytes(b"tool")
    executable.chmod(0o700)
    descriptor = {
        "id": "example.redirect",
        "display_name": "Redirect output",
        "handler": {
            "kind": "program",
            "program_path": str(executable),
            "redirect_outputs": True,
        },
    }

    with pytest.raises(UiCommandContractError) as macos:
        build_ui_commands_register_plan(
            version="2025.1",
            host_platform="macos",
            commands=[descriptor],
            source_authority=USER_SUPPLIED_SOURCE_AUTHORITY,
        )
    assert macos.value.error_code == "HOST_BEHAVIOR_BOUNDARY"

    windows = build_ui_commands_register_plan(
        version="2025.1",
        host_platform="windows",
        commands=[descriptor],
        source_authority=USER_SUPPLIED_SOURCE_AUTHORITY,
    )
    assert windows["dispatch"]["arguments"]["commands"][0][
        "redirectOutputs"
    ] is True
    assert validate_ui_command_plan(windows) == windows


def test_program_proof_rejects_non_executable_and_detects_drift(
    tmp_path: Path,
) -> None:
    program = tmp_path / "program"
    program.write_bytes(b"v1")
    descriptor = {
        "id": "example.program",
        "display_name": "Program",
        "handler": {
            "kind": "program",
            "program_path": str(program),
        },
    }
    with pytest.raises(UiCommandContractError) as not_executable:
        build_ui_commands_register_plan(
            version="2025.1",
            host_platform="macos",
            commands=[descriptor],
        )
    assert not_executable.value.error_code == "PATH_NOT_EXECUTABLE"

    program.chmod(0o700)
    plan = build_ui_commands_register_plan(
        version="2025.1",
        host_platform="macos",
        commands=[descriptor],
        source_authority=USER_SUPPLIED_SOURCE_AUTHORITY,
    )
    program.write_bytes(b"v2")
    os.chmod(program, 0o700)
    with pytest.raises(UiCommandContractError) as changed:
        revalidate_ui_command_file_proofs(plan)
    assert changed.value.error_code == "PATH_CHANGED"


def test_execute_value_rejects_non_finite_and_unrepresentable_numbers() -> None:
    for value in (float("nan"), float("inf"), float("-inf"), 2**1024):
        with pytest.raises(UiCommandContractError, match="finite WAAPI double|finite JSON number"):
            build_ui_command_execute_plan(
                version="2025.1",
                command="ExampleCommand",
                value=value,
            )

    assert build_ui_command_execute_plan(
        version="2025.1",
        command="ExampleCommand",
        value=2**1023,
    )["request"]["value"] == 2**1023


def test_notification_only_registration_can_omit_source_authority() -> None:
    plan = build_ui_commands_register_plan(
        version="2021.1",
        host_platform="macos",
        commands=[
            {
                "id": "example.notification",
                "display_name": "Notify WAAPI subscriber",
                "handler": {"kind": "notification"},
            }
        ],
    )

    assert "source_authority" not in plan["request"]
    assert plan["runtime_preconditions"]["source_authority"] == {
        "assertion": None,
        "eligible_only_when_current_user_message_supplied_exact_existing_path_and_fields": True,
        "model_generated_repaired_or_wrapped_code_eligible": False,
        "required": False,
        "runtime_can_prove_conversational_provenance": False,
    }
    assert validate_ui_command_plan(plan) == plan
