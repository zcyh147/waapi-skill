"""Local-host boundary for transactions that bind gateway filesystem state.

The immutable transaction artifact can prove only files and directories visible
to the gateway process. Those proofs are meaningful to Wwise only when WAAPI
is connected to the same machine. This module is the single classification
contract consumed before project reads, request path validation, or business
dispatch.

Dedicated operations are listed positively because their closed adapters read,
hash, parse, or materialize the named path roles. Generic ``waapi.call``
requests derive the decision from the versioned public execution contract:
every ``isolated_transaction`` route uses the isolated-I/O policy and is
therefore local-only.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Callable, Mapping, Sequence

from .execution_contracts import ExecutionContractError, ExecutionContractRegistry
from .endpoint_scope import is_loopback_waapi_host
from .operation_registry import (
    CONDITIONAL_LOCAL_FILESYSTEM_OPERATIONS,
    DYNAMIC_LOCAL_FILESYSTEM_OPERATIONS,
    LOCAL_FILESYSTEM_OPERATION_ROLES,
)


RouteLookup = Callable[[str, str], str | None]

_DEFAULT_EXECUTION_CONTRACTS = ExecutionContractRegistry()


@lru_cache(maxsize=1_024)
def execution_route(version: str, uri: str) -> str | None:
    """Return a packaged route, or ``None`` for an invalid/unreflected pair."""

    try:
        entries = _execution_routes(version)
    except ExecutionContractError:
        return None
    return entries.get(uri)


@lru_cache(maxsize=8)
def _execution_routes(version: str) -> Mapping[str, str]:
    entries = _DEFAULT_EXECUTION_CONTRACTS.entries(version)
    routes: dict[str, str] = {}
    for entry in entries:
        if entry.uri in routes:
            raise ExecutionContractError(
                f"WAAPI URI {entry.uri!r} is ambiguous in Wwise {version}"
            )
        routes[entry.uri] = entry.route
    return routes


def local_filesystem_path_roles(
    request_payload: Mapping[str, Any],
    *,
    route_lookup: RouteLookup = execution_route,
) -> tuple[str, ...]:
    """Return bounded local path roles for one transaction request.

    The result contains role labels only, never user paths. A non-empty result
    means that preview and every continuation phase require a loopback WAAPI
    endpoint.
    """

    operation = request_payload.get("operation")
    if not isinstance(operation, str):
        return ()

    dedicated = LOCAL_FILESYSTEM_OPERATION_ROLES.get(operation)
    if dedicated is not None:
        return dedicated

    arguments = request_payload.get("arguments")
    if not isinstance(arguments, Mapping):
        return ()

    if operation in CONDITIONAL_LOCAL_FILESYSTEM_OPERATIONS:
        if operation == "object.set":
            return (
                (
                    "arguments.objects[].recursive.import",
                    "live_project_files",
                )
                if _contains_object_import(arguments.get("objects"))
                else ()
            )
        if operation == "ui.commands.execute":
            return ("arguments.files",) if "files" in arguments else ()
        return _ui_command_descriptor_path_roles(arguments.get("commands"))

    if operation not in DYNAMIC_LOCAL_FILESYSTEM_OPERATIONS:
        return ()

    version = request_payload.get("version")
    uri = arguments.get("api")
    if not isinstance(version, str) or not isinstance(uri, str):
        return ()
    if route_lookup(version, uri) != "isolated_transaction":
        return ()
    return ("execution_contract.isolated_transaction",)


def _contains_object_import(value: Any) -> bool:
    if isinstance(value, Mapping):
        if "import" in value:
            return True
        return any(_contains_object_import(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return any(_contains_object_import(item) for item in value)
    return False


def _ui_command_descriptor_path_roles(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    roles: set[str] = set()
    for command in value:
        if not isinstance(command, Mapping):
            continue
        handler = command.get("handler")
        if not isinstance(handler, Mapping):
            continue
        kind = handler.get("kind")
        if kind == "program" or "program_path" in handler:
            roles.add("arguments.commands[].handler.program_path")
        if kind == "lua_script" or "lua_script_path" in handler:
            roles.add("arguments.commands[].handler.lua_script_path")
        if "lua_module_directories" in handler:
            roles.add(
                "arguments.commands[].handler.lua_module_directories"
            )
        if "working_directory" in handler:
            roles.add("arguments.commands[].handler.working_directory")
    return tuple(sorted(roles))


__all__ = [
    "execution_route",
    "is_loopback_waapi_host",
    "local_filesystem_path_roles",
]
