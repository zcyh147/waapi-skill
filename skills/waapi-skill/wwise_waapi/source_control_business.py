"""Compile closed source-control declarations into exact WAAPI requests."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from .business_declaration_state import BusinessDeclarationSession
from .business_declarations import business_repair
from .filesystem_security import path_is_link_or_reparse
from .host_paths import (
    HostPathError,
    localize_waapi_host_path,
    parse_relative_host_path,
)
from .operation_registry import parse_operation_request
from .source_control_business_contracts import (
    SOURCE_CONTROL_ADD_URI,
    SOURCE_CONTROL_CHECK_OUT_URI,
    SOURCE_CONTROL_COMMIT_URI,
    SOURCE_CONTROL_DELETE_URI,
    SOURCE_CONTROL_GET_SOURCE_FILES_URI,
    SOURCE_CONTROL_GET_STATUS_URI,
    SOURCE_CONTROL_MOVE_URI,
    SOURCE_CONTROL_REVERT_URI,
    SOURCE_CONTROL_SET_PROVIDER_URI,
    source_control_business_contract_data,
)


MAX_SOURCE_CONTROL_FILES = 256
MAX_SOURCE_CONTROL_RESULTS = 1_000
MAX_SOURCE_CONTROL_PATH_BYTES = 4_096
MAX_SOURCE_CONTROL_MESSAGE_BYTES = 8_192

_FILE_OPERATIONS = frozenset(
    {
        SOURCE_CONTROL_ADD_URI,
        SOURCE_CONTROL_CHECK_OUT_URI,
        SOURCE_CONTROL_COMMIT_URI,
        SOURCE_CONTROL_DELETE_URI,
        SOURCE_CONTROL_GET_STATUS_URI,
        SOURCE_CONTROL_REVERT_URI,
    }
)
_MUTATIONS = frozenset(
    {
        SOURCE_CONTROL_ADD_URI,
        SOURCE_CONTROL_CHECK_OUT_URI,
        SOURCE_CONTROL_COMMIT_URI,
        SOURCE_CONTROL_DELETE_URI,
        SOURCE_CONTROL_MOVE_URI,
        SOURCE_CONTROL_REVERT_URI,
    }
)
_EXISTING_SOURCE_OPERATIONS = frozenset(
    {
        SOURCE_CONTROL_ADD_URI,
        SOURCE_CONTROL_CHECK_OUT_URI,
        SOURCE_CONTROL_COMMIT_URI,
        SOURCE_CONTROL_DELETE_URI,
        SOURCE_CONTROL_MOVE_URI,
    }
)


def _repair(error_code: str, *, field: str, action: str, **details: Any) -> Any:
    raise business_repair(error_code, field=field, action=action, **details)


def _settings(session: BusinessDeclarationSession) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    if set(session.settings) != {"source_control_roots", "source_control_plan"}:
        _repair(
            "SOURCE_CONTROL_PLAN_INCOMPLETE",
            field="source_control_plan",
            action="submit the one complete Gateway-disclosed source-control plan",
        )
    roots = session.settings["source_control_roots"]
    plan = session.settings["source_control_plan"]
    if not isinstance(roots, Mapping) or set(roots) != {"project", "originals"}:
        _repair(
            "SOURCE_CONTROL_ROOTS_INVALID",
            field="source_control_roots",
            action="restart from the live Gateway continuation",
        )
    if not isinstance(plan, Mapping):
        _repair(
            "SOURCE_CONTROL_PLAN_INVALID",
            field="source_control_plan",
            action="submit one closed source-control plan",
        )
    return roots, plan


def _native_absolute(value: Any, *, field: str) -> Path:
    try:
        localized = localize_waapi_host_path(value)
    except HostPathError as exc:
        _repair(
            "SOURCE_CONTROL_PATH_INVALID",
            field=field,
            action="provide one exact absolute path for this Gateway host",
            reason=str(exc),
        )
    path = Path(localized)
    if len(str(path).encode("utf-8")) > MAX_SOURCE_CONTROL_PATH_BYTES:
        _repair(
            "SOURCE_CONTROL_PATH_INVALID",
            field=field,
            action="provide a path within the fixed 4096-byte limit",
        )
    return path


def _root(value: Any, *, field: str) -> Path:
    path = _native_absolute(value, field=field)
    if not path.is_dir() or path_is_link_or_reparse(path):
        _repair(
            "SOURCE_CONTROL_ROOT_INVALID",
            field=field,
            action="use an existing ordinary directory without links or reparse points",
        )
    return path.resolve(strict=True)


def _relative(value: Any, *, field: str) -> tuple[str, ...]:
    try:
        parsed = parse_relative_host_path(value)
    except HostPathError as exc:
        _repair(
            "SOURCE_CONTROL_PATH_INVALID",
            field=field,
            action="provide one normalized relative path without traversal",
            reason=str(exc),
        )
    if len(str(parsed.pure_path).encode("utf-8")) > MAX_SOURCE_CONTROL_PATH_BYTES:
        _repair(
            "SOURCE_CONTROL_PATH_INVALID",
            field=field,
            action="provide a path within the fixed 4096-byte limit",
        )
    return parsed.components


def _assert_no_redirect(root: Path, candidate: Path, *, field: str) -> None:
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        _repair(
            "SOURCE_CONTROL_PATH_OUTSIDE_ROOT",
            field=field,
            action="choose a file inside its declared Gateway-owned root",
        )
    current = root
    for component in relative.parts:
        current = current / component
        if not current.exists() and not current.is_symlink():
            continue
        if path_is_link_or_reparse(current):
            _repair(
                "SOURCE_CONTROL_PATH_REDIRECTED",
                field=field,
                action="choose a path without symbolic links or Windows reparse points",
            )


def _locator_path(
    locator: Any,
    *,
    roots: Mapping[str, Path],
    io_root: Path | None,
    field: str,
) -> Path:
    if not isinstance(locator, Mapping) or set(locator) != {"scope", "path"}:
        _repair(
            "SOURCE_CONTROL_LOCATOR_INVALID",
            field=field,
            action="use one disclosed project, originals, or exact file locator",
        )
    scope = locator.get("scope")
    value = locator.get("path")
    if scope in {"project", "originals"}:
        root = roots[str(scope)]
        candidate = root.joinpath(*_relative(value, field=field))
        resolved = candidate.resolve(strict=False)
        _assert_no_redirect(root, candidate, field=field)
        try:
            resolved.relative_to(root)
        except ValueError:
            _repair(
                "SOURCE_CONTROL_PATH_OUTSIDE_ROOT",
                field=field,
                action="choose a file inside its declared Gateway-owned root",
            )
        return resolved
    if scope == "exact":
        if io_root is None:
            _repair(
                "SOURCE_CONTROL_IO_ROOT_REQUIRED",
                field="io_root",
                action="provide the exact approved root for every exact file path",
            )
        candidate = _native_absolute(value, field=field)
        resolved = candidate.resolve(strict=False)
        _assert_no_redirect(io_root, candidate, field=field)
        try:
            resolved.relative_to(io_root)
        except ValueError:
            _repair(
                "SOURCE_CONTROL_PATH_OUTSIDE_ROOT",
                field=field,
                action="choose a file inside the exact approved I/O root",
            )
        return resolved
    _repair(
        "SOURCE_CONTROL_LOCATOR_INVALID",
        field=field,
        action="choose locator scope project, originals, or exact",
    )


def _file_paths(
    value: Any,
    *,
    roots: Mapping[str, Path],
    io_root: Path | None,
    require_existing: bool,
    field: str = "files",
) -> list[Path]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or not 1 <= len(value) <= MAX_SOURCE_CONTROL_FILES
    ):
        _repair(
            "SOURCE_CONTROL_FILES_INVALID",
            field=field,
            action=f"provide between 1 and {MAX_SOURCE_CONTROL_FILES} file locators",
        )
    paths = [
        _locator_path(
            locator,
            roots=roots,
            io_root=io_root,
            field=f"{field}[{index}]",
        )
        for index, locator in enumerate(value)
    ]
    keys = [os.path.normcase(str(path)) for path in paths]
    if len(keys) != len(set(keys)):
        _repair(
            "SOURCE_CONTROL_FILES_DUPLICATE",
            field=field,
            action="remove duplicate file locators",
        )
    if require_existing:
        for index, path in enumerate(paths):
            if not path.is_file() or path_is_link_or_reparse(path):
                _repair(
                    "SOURCE_CONTROL_SOURCE_MISSING",
                    field=f"{field}[{index}]",
                    action="choose an existing ordinary file",
                )
    return paths


def _roots(raw: Mapping[str, Any]) -> dict[str, Path]:
    project = _root(raw.get("project"), field="source_control_roots.project")
    originals = _root(raw.get("originals"), field="source_control_roots.originals")
    try:
        originals.relative_to(project)
    except ValueError:
        # Wwise can configure a non-project Originals folder. It remains live
        # Gateway evidence and is therefore allowed as its own exact root.
        pass
    return {"project": project, "originals": originals}


def _io_root(plan: Mapping[str, Any]) -> Path | None:
    raw = plan.get("io_root")
    return None if raw is None else _root(raw, field="io_root")


def _mutation_io_root(
    *,
    roots: Mapping[str, Path],
    explicit: Path | None,
    paths: Sequence[Path],
) -> Path:
    authority = roots["project"] if explicit is None else explicit
    for path in paths:
        try:
            path.relative_to(authority)
        except ValueError:
            _repair(
                "SOURCE_CONTROL_PATH_OUTSIDE_ROOT",
                field="io_root",
                action="choose one approved I/O root containing every changed file",
            )
    return authority


def _get_source_files_request(
    plan: Mapping[str, Any],
    *,
    version: str,
) -> dict[str, Any]:
    allowed = {
        "usage_scope",
        "originals_folder",
        "recursive",
        "include_usage_objects",
        "max_results",
    }
    if set(plan) - allowed:
        _repair(
            "SOURCE_CONTROL_PLAN_FIELDS_INVALID",
            field="source_control_plan",
            action="submit only the disclosed source-file search fields",
        )
    usage_scope = plan.get("usage_scope", "all")
    if usage_scope not in {"all", "used", "unused"}:
        _repair(
            "SOURCE_CONTROL_USAGE_SCOPE_INVALID",
            field="usage_scope",
            action="choose all, used, or unused",
        )
    recursive = plan.get("recursive", True)
    include_usage = plan.get("include_usage_objects", False)
    max_results = plan.get("max_results", 100)
    if not isinstance(recursive, bool) or not isinstance(include_usage, bool):
        _repair(
            "SOURCE_CONTROL_PLAN_FIELDS_INVALID",
            field="source_control_plan",
            action="use booleans for recursive and include_usage_objects",
        )
    if (
        isinstance(max_results, bool)
        or not isinstance(max_results, int)
        or not 1 <= max_results <= MAX_SOURCE_CONTROL_RESULTS
    ):
        _repair(
            "SOURCE_CONTROL_RESULT_LIMIT_INVALID",
            field="max_results",
            action=f"choose an integer from 1 to {MAX_SOURCE_CONTROL_RESULTS}",
        )
    args: dict[str, Any] = {"filter": usage_scope, "recursive": recursive}
    if "originals_folder" in plan:
        args["folder"] = str(
            Path(*_relative(plan["originals_folder"], field="originals_folder"))
        )
    fields = ["file", "folder", "isUsed", "isMissing"]
    options: dict[str, Any] = {"return": fields}
    if include_usage:
        fields.append("usage")
        options["objectReturn"] = ["id", "name", "type", "path"]
    return parse_operation_request(
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": version,
            "operation": "waapi.call",
            "arguments": {
                "api": SOURCE_CONTROL_GET_SOURCE_FILES_URI,
                "args": args,
                "options": options,
                "result_projection": {
                    "kind": "source-control-files",
                    "max_results": max_results,
                },
            },
        },
        expected_version=version,
    ).as_dict()


def materialize_source_control_business_request(
    operation: str,
    session: BusinessDeclarationSession,
) -> dict[str, Any]:
    """Compile one closed source-control outcome without native path input."""

    if not isinstance(session, BusinessDeclarationSession):
        raise TypeError("session must be BusinessDeclarationSession")
    contract = source_control_business_contract_data(
        operation,
        session.context.wwise_version,
    )
    if operation == SOURCE_CONTROL_SET_PROVIDER_URI:
        _repair(
            "SOURCE_CONTROL_PROVIDER_CONFIGURATION_REQUIRED",
            field="provider",
            action="configure provider and credentials in human-owned Wwise settings",
        )
    raw_roots, plan = _settings(session)
    if operation == SOURCE_CONTROL_GET_SOURCE_FILES_URI:
        return _get_source_files_request(plan, version=session.context.wwise_version)
    roots = _roots(raw_roots)
    explicit_io_root = _io_root(plan)
    allowed = {"files", "io_root"}
    if operation == SOURCE_CONTROL_COMMIT_URI:
        allowed.add("commit_message")
    if operation == SOURCE_CONTROL_MOVE_URI:
        allowed = {"moves", "io_root"}
    if set(plan) != (allowed - {"io_root"}) and not (
        "io_root" in plan and set(plan) == allowed
    ):
        _repair(
            "SOURCE_CONTROL_PLAN_FIELDS_INVALID",
            field="source_control_plan",
            action="submit exactly the disclosed fields for this source-control action",
        )
    if operation in _FILE_OPERATIONS:
        paths = _file_paths(
            plan.get("files"),
            roots=roots,
            io_root=explicit_io_root,
            require_existing=operation in _EXISTING_SOURCE_OPERATIONS,
        )
        native_args: dict[str, Any] = {"files": [str(path) for path in paths]}
        if operation == SOURCE_CONTROL_COMMIT_URI:
            message = plan.get("commit_message")
            if (
                not isinstance(message, str)
                or not message
                or message != message.strip()
                or len(message.encode("utf-8")) > MAX_SOURCE_CONTROL_MESSAGE_BYTES
                or any(ord(character) < 32 and character not in {"\t", "\n"} for character in message)
            ):
                _repair(
                    "SOURCE_CONTROL_COMMIT_MESSAGE_INVALID",
                    field="commit_message",
                    action="provide one bounded nonempty exact commit message",
                )
            native_args["message"] = message
        all_paths = paths
    elif operation == SOURCE_CONTROL_MOVE_URI:
        moves = plan.get("moves")
        if (
            not isinstance(moves, Sequence)
            or isinstance(moves, (str, bytes, bytearray))
            or not 1 <= len(moves) <= MAX_SOURCE_CONTROL_FILES
        ):
            _repair(
                "SOURCE_CONTROL_MOVES_INVALID",
                field="moves",
                action=f"provide between 1 and {MAX_SOURCE_CONTROL_FILES} move pairs",
            )
        sources: list[Path] = []
        destinations: list[Path] = []
        for index, move in enumerate(moves):
            if not isinstance(move, Mapping) or set(move) != {"source", "destination"}:
                _repair(
                    "SOURCE_CONTROL_MOVES_INVALID",
                    field=f"moves[{index}]",
                    action="provide one source locator and one destination locator",
                )
            source = _locator_path(
                move["source"],
                roots=roots,
                io_root=explicit_io_root,
                field=f"moves[{index}].source",
            )
            destination = _locator_path(
                move["destination"],
                roots=roots,
                io_root=explicit_io_root,
                field=f"moves[{index}].destination",
            )
            if not source.is_file() or path_is_link_or_reparse(source):
                _repair(
                    "SOURCE_CONTROL_SOURCE_MISSING",
                    field=f"moves[{index}].source",
                    action="choose an existing ordinary source file",
                )
            if destination.exists() or destination.is_symlink():
                _repair(
                    "SOURCE_CONTROL_DESTINATION_EXISTS",
                    field=f"moves[{index}].destination",
                    action="choose a destination path that does not already exist",
                )
            if not destination.parent.is_dir():
                _repair(
                    "SOURCE_CONTROL_DESTINATION_PARENT_MISSING",
                    field=f"moves[{index}].destination",
                    action="choose a destination inside an existing ordinary directory",
                )
            sources.append(source)
            destinations.append(destination)
        native_args = {
            "files": [str(path) for path in sources],
            "newFiles": [str(path) for path in destinations],
        }
        all_paths = [*sources, *destinations]
    else:  # pragma: no cover - contract registry invariant
        raise ValueError("unsupported source-control business operation")
    arguments: dict[str, Any] = {
        "api": operation,
        "args": native_args,
        "options": {},
    }
    if operation in _MUTATIONS:
        arguments["io_root"] = str(
            _mutation_io_root(
                roots=roots,
                explicit=explicit_io_root,
                paths=all_paths,
            )
        )
    if contract["execution_shape"] == "bounded_read" and "io_root" in arguments:
        raise AssertionError("read-only source-control requests must not carry io_root")
    return parse_operation_request(
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": session.context.wwise_version,
            "operation": "waapi.call",
            "arguments": arguments,
        },
        expected_version=session.context.wwise_version,
    ).as_dict()


def normalize_source_control_result(
    operation: str,
    result: Mapping[str, Any],
    session: BusinessDeclarationSession,
) -> dict[str, Any]:
    """Apply the business result ceiling owned by a source-control read."""

    if operation != SOURCE_CONTROL_GET_SOURCE_FILES_URI:
        return dict(result)
    _roots_value, plan = _settings(session)
    maximum = plan.get("max_results", 100)
    return project_source_control_result(
        operation,
        result,
        {"kind": "source-control-files", "max_results": maximum},
    )


def project_source_control_result(
    operation: str,
    result: Mapping[str, Any],
    projection: Mapping[str, Any],
) -> dict[str, Any]:
    """Project a sealed full result through its Gateway-owned row ceiling."""

    if operation != SOURCE_CONTROL_GET_SOURCE_FILES_URI:
        return dict(result)
    if (
        set(projection) != {"kind", "max_results"}
        or projection.get("kind") != "source-control-files"
        or isinstance(projection.get("max_results"), bool)
        or not isinstance(projection.get("max_results"), int)
        or not 1 <= int(projection["max_results"]) <= MAX_SOURCE_CONTROL_RESULTS
    ):
        _repair(
            "SOURCE_CONTROL_RESULT_LIMIT_INVALID",
            field="result_projection",
            action="stop because the sealed result projection is invalid",
        )
    maximum = int(projection["max_results"])
    rows = result.get("return")
    if not isinstance(rows, list):
        _repair(
            "SOURCE_CONTROL_RESULT_INVALID",
            field="result.return",
            action="stop because Wwise returned an unexpected source-file result",
        )
    limited = rows[:maximum]
    return {
        "items": limited,
        "returned_count": len(limited),
        "total_count": len(rows),
        "truncated": len(rows) > len(limited),
        "max_results": maximum,
    }


__all__ = [
    "MAX_SOURCE_CONTROL_FILES",
    "MAX_SOURCE_CONTROL_RESULTS",
    "materialize_source_control_business_request",
    "normalize_source_control_result",
    "project_source_control_result",
]
