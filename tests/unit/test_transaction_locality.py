from __future__ import annotations

from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.execution_contracts import ExecutionContractRegistry
from wwise_waapi.operation_registry import (
    CONDITIONAL_LOCAL_FILESYSTEM_OPERATIONS,
    DYNAMIC_LOCAL_FILESYSTEM_OPERATIONS,
    LOCAL_FILESYSTEM_OPERATION_ROLES,
    NO_LOCAL_FILESYSTEM_OPERATIONS,
    OPERATION_REQUEST_CONTRACT,
    list_operation_specs,
)
from wwise_waapi.transaction_locality import (
    is_loopback_waapi_host,
    local_filesystem_path_roles,
)


def request(
    operation: str,
    arguments: Mapping[str, Any],
    *,
    version: str = "2025.1",
) -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": operation,
        "arguments": dict(arguments),
    }


def _contains_absolute_filesystem_marker(value: Any) -> bool:
    if isinstance(value, Mapping):
        if value.get("absoluteRegularFile") is True:
            return True
        if value.get("absoluteExistingDirectory") is True:
            return True
        return any(
            _contains_absolute_filesystem_marker(item)
            for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_absolute_filesystem_marker(item) for item in value)
    return False


def test_locality_contract_covers_every_closed_operation_schema_with_local_paths() -> None:
    specs = list_operation_specs()
    by_name = {spec.name: spec for spec in specs}

    assert set(LOCAL_FILESYSTEM_OPERATION_ROLES) == {
        "audio.import",
        "audio.importTabDelimited",
        "lua.executeCliFile",
        "lua.executeCoreFile",
        "lua.executeCoreInline",
        "soundbank.convertExternalSources",
        "soundbank.generate",
        "soundbank.processDefinitionFiles",
    }
    partitions = (
        set(LOCAL_FILESYSTEM_OPERATION_ROLES),
        set(CONDITIONAL_LOCAL_FILESYSTEM_OPERATIONS),
        set(DYNAMIC_LOCAL_FILESYSTEM_OPERATIONS),
        set(NO_LOCAL_FILESYSTEM_OPERATIONS),
    )
    assert all(
        not left & right
        for index, left in enumerate(partitions)
        for right in partitions[index + 1 :]
    )
    assert set().union(*partitions) == set(by_name)
    assert CONDITIONAL_LOCAL_FILESYSTEM_OPERATIONS == frozenset(
        {
            "object.set",
            "ui.commands.execute",
            "ui.commands.register",
            "ui.commands.unregister",
        }
    )
    assert DYNAMIC_LOCAL_FILESYSTEM_OPERATIONS == frozenset({"waapi.call"})
    assert "ui.captureScreen" in NO_LOCAL_FILESYSTEM_OPERATIONS

    io_root_operations = {
        spec.name
        for spec in specs
        if "io_root" in {
            *spec.required_arguments,
            *spec.optional_arguments,
        }
    }
    assert io_root_operations == {
        "lua.executeCliFile",
        "lua.executeCoreFile",
        "lua.executeCoreInline",
        "soundbank.convertExternalSources",
        "soundbank.generate",
        "soundbank.processDefinitionFiles",
        "waapi.call",
    }

    absolute_path_schema_operations = {
        spec.name
        for spec in specs
        if _contains_absolute_filesystem_marker(spec.argument_contract)
    }
    assert absolute_path_schema_operations == {
        "audio.import",
        "audio.importTabDelimited",
        "lua.executeCliFile",
        "lua.executeCoreFile",
        "lua.executeCoreInline",
        "object.set",
        "soundbank.convertExternalSources",
            "soundbank.processDefinitionFiles",
            "ui.commands.execute",
            "ui.commands.register",
            "ui.commands.unregister",
        }

    # These schemas intentionally describe the path-bearing branch in prose or
    # use live project/output paths rather than an absolute-path schema marker.
    assert "commands" in by_name["ui.commands.register"].required_arguments
    assert "commands" in by_name["ui.commands.unregister"].optional_arguments
    assert "io_root" in by_name["soundbank.generate"].required_arguments


@pytest.mark.parametrize(
    "operation",
    tuple(sorted(LOCAL_FILESYSTEM_OPERATION_ROLES)),
)
def test_every_dedicated_local_filesystem_operation_is_unconditional(
    operation: str,
) -> None:
    assert local_filesystem_path_roles(request(operation, {}))


def test_ui_locality_is_conditional_and_capture_screen_stays_remote_capable() -> None:
    assert local_filesystem_path_roles(
        request("ui.commands.execute", {"command": "Copy"})
    ) == ()
    assert local_filesystem_path_roles(
        request(
            "ui.commands.execute",
            {"command": "ImportFiles", "files": ["/remote/input.wav"]},
        )
    ) == ("arguments.files",)
    assert local_filesystem_path_roles(
        request(
            "ui.commands.register",
            {
                "commands": [
                    {
                        "id": "example.notify",
                        "handler": {"kind": "notification"},
                    }
                ]
            },
        )
    ) == ()
    assert local_filesystem_path_roles(
        request(
            "ui.commands.unregister",
            {
                "commands": [
                    {
                        "id": "example.program",
                        "handler": {
                            "kind": "program",
                            "program_path": "/remote/tool",
                        },
                    },
                    {
                        "id": "example.lua",
                        "handler": {
                            "kind": "lua_script",
                            "lua_script_path": "/remote/tool.lua",
                            "lua_module_directories": ["/remote/modules"],
                            "working_directory": "/remote/work",
                        },
                    },
                ]
            },
        )
    ) == (
        "arguments.commands[].handler.lua_module_directories",
        "arguments.commands[].handler.lua_script_path",
        "arguments.commands[].handler.program_path",
        "arguments.commands[].handler.working_directory",
    )
    assert local_filesystem_path_roles(request("ui.captureScreen", {})) == ()


def test_object_set_locality_is_conditional_on_recursive_import() -> None:
    assert local_filesystem_path_roles(
        request(
            "object.set",
            {
                "objects": [
                    {
                        "object": {"kind": "id", "value": "{TARGET}"},
                        "properties": [{"name": "Volume", "value": -3}],
                    }
                ]
            },
        )
    ) == ()
    assert local_filesystem_path_roles(
        request(
            "object.set",
            {
                "objects": [
                    {
                        "object": {"kind": "id", "value": "{TARGET}"},
                        "children": [
                            {
                                "type": "Sound",
                                "name": "Imported",
                                "import": {
                                    "files": [
                                        {
                                            "audio_file_base64": (
                                                "inline.wav|UklGRgAAAAAAV0FWRQ=="
                                            )
                                        }
                                    ]
                                },
                            }
                        ],
                    }
                ]
            },
            version="2023.1",
        )
    ) == (
        "arguments.objects[].recursive.import",
        "live_project_files",
    )


def test_waapi_call_locality_comes_only_from_isolated_execution_route() -> None:
    isolated = local_filesystem_path_roles(
        request(
            "waapi.call",
            {
                "api": "ak.wwise.debug.generateToneWAV",
                "args": {"path": "/remote/tone.wav"},
                "io_root": "/remote",
            },
        ),
        route_lookup=lambda version, uri: "isolated_transaction",
    )
    assert isolated == ("execution_contract.isolated_transaction",)

    for route in ("transaction", "managed_transaction", None):
        assert (
            local_filesystem_path_roles(
                request(
                    "waapi.call",
                    {
                        "api": "ak.wwise.core.project.save",
                        "args": {},
                    },
                ),
                route_lookup=lambda version, uri, selected=route: selected,
            )
            == ()
        )


def test_actual_five_version_contracts_keep_every_generic_isolated_call_local() -> None:
    registry = ExecutionContractRegistry()
    for version in ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"):
        entries = registry.entries(version)
        isolated_uris = {
            entry.uri
            for entry in entries
            if entry.route == "isolated_transaction"
        }
        assert isolated_uris
        for entry in entries:
            roles = local_filesystem_path_roles(
                request(
                    "waapi.call",
                    {
                        "api": entry.uri,
                        "args": {},
                        "io_root": "/remote",
                    },
                    version=version,
                )
            )
            assert bool(roles) is (entry.uri in isolated_uris)
            if roles:
                assert roles == (
                    "execution_contract.isolated_transaction",
                )
@pytest.mark.parametrize(
    ("host", "expected"),
    (
        ("localhost", True),
        ("LOCALHOST", True),
        ("127.0.0.1", True),
        ("127.23.45.67", True),
        ("::1", True),
        ("0:0:0:0:0:0:0:1", True),
        ("[::1]", True),
        ("[2001:db8::1]", False),
        ("localhost.localdomain", False),
        ("localhost.example.com", False),
        ("192.0.2.10", False),
        ("wwise-studio", False),
    ),
)
def test_loopback_host_contract_accepts_only_localhost_or_literal_loopback(
    host: str,
    expected: bool,
) -> None:
    assert is_loopback_waapi_host(host) is expected
