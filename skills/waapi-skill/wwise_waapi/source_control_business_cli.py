"""CLI declarations for the closed source-control business interface."""

from __future__ import annotations

import argparse
from typing import Any

from .source_control_business_contracts import (
    SOURCE_CONTROL_COMMIT_URI,
    SOURCE_CONTROL_GET_SOURCE_FILES_URI,
    SOURCE_CONTROL_MOVE_URI,
)


class SourceControlBusinessCliError(ValueError):
    """One CLI declaration does not match its operation-local contract."""


def add_source_control_arguments(
    parser: argparse.ArgumentParser,
    *,
    include_max_results: bool,
) -> None:
    parser.add_argument(
        "--project-file",
        action="append",
        default=[],
        help="Exact file path relative to the live Wwise project directory",
    )
    parser.add_argument(
        "--originals-file",
        action="append",
        default=[],
        help="Exact file path relative to the live Wwise Originals directory",
    )
    parser.add_argument(
        "--exact-file",
        action="append",
        default=[],
        help="Exact absolute caller-owned path under --io-root",
    )
    parser.add_argument("--io-root")
    parser.add_argument("--commit-message")
    parser.add_argument(
        "--move",
        action="append",
        nargs=4,
        default=[],
        metavar=("SOURCE_SCOPE", "SOURCE_PATH", "DESTINATION_SCOPE", "DESTINATION_PATH"),
    )
    parser.add_argument(
        "--usage-scope",
        choices=("all", "used", "unused"),
    )
    parser.add_argument("--originals-folder")
    recursive = parser.add_mutually_exclusive_group()
    recursive.add_argument("--recursive", dest="recursive", action="store_true")
    recursive.add_argument("--no-recursive", dest="recursive", action="store_false")
    usage = parser.add_mutually_exclusive_group()
    usage.add_argument(
        "--include-usage-objects",
        dest="include_usage_objects",
        action="store_true",
    )
    usage.add_argument(
        "--no-usage-objects",
        dest="include_usage_objects",
        action="store_false",
    )
    parser.set_defaults(recursive=None, include_usage_objects=None)
    if include_max_results:
        parser.add_argument("--max-results", type=int)


def source_control_fields_supplied(args: argparse.Namespace) -> bool:
    return any(
        getattr(args, name, None) is not None
        for name in (
            "io_root",
            "commit_message",
            "usage_scope",
            "originals_folder",
            "recursive",
            "include_usage_objects",
        )
    ) or any(
        bool(getattr(args, name, ()))
        for name in ("project_file", "originals_file", "exact_file", "move")
    )


def source_control_plan_from_namespace(
    args: argparse.Namespace,
    *,
    operation: str,
) -> dict[str, Any]:
    if operation == SOURCE_CONTROL_GET_SOURCE_FILES_URI:
        forbidden = _locator_fields_supplied(args) or any(
            getattr(args, name, None) is not None
            for name in ("io_root", "commit_message")
        ) or bool(getattr(args, "move", ()))
        if forbidden:
            raise SourceControlBusinessCliError(
                "getSourceFiles accepts only usage scope, Originals folder, recursion, usage projection, and result bound"
            )
        plan: dict[str, Any] = {}
        for name in (
            "usage_scope",
            "originals_folder",
            "recursive",
            "include_usage_objects",
            "max_results",
        ):
            value = getattr(args, name, None)
            if value is not None:
                plan[name] = value
        return plan
    files = _file_locators(args)
    if operation == SOURCE_CONTROL_MOVE_URI:
        if files or args.commit_message is not None:
            raise SourceControlBusinessCliError(
                "sourceControl.move accepts only --move pairs and optional --io-root"
            )
        moves = []
        for source_scope, source_path, destination_scope, destination_path in args.move:
            moves.append(
                {
                    "source": _locator(source_scope, source_path),
                    "destination": _locator(destination_scope, destination_path),
                }
            )
        plan = {"moves": moves}
    else:
        if args.move:
            raise SourceControlBusinessCliError(
                "Only sourceControl.move accepts --move pairs"
            )
        plan = {"files": files}
        if operation == SOURCE_CONTROL_COMMIT_URI:
            plan["commit_message"] = args.commit_message
        elif args.commit_message is not None:
            raise SourceControlBusinessCliError(
                "Only sourceControl.commit accepts --commit-message"
            )
    if args.io_root is not None:
        plan["io_root"] = args.io_root
    if any(
        getattr(args, name, None) is not None
        for name in (
            "usage_scope",
            "originals_folder",
            "recursive",
            "include_usage_objects",
        )
    ):
        raise SourceControlBusinessCliError(
            "File actions do not accept source-file search fields"
        )
    return plan


def _locator_fields_supplied(args: argparse.Namespace) -> bool:
    return any(
        bool(getattr(args, name, ()))
        for name in ("project_file", "originals_file", "exact_file")
    )


def _file_locators(args: argparse.Namespace) -> list[dict[str, str]]:
    return [
        *({"scope": "project", "path": path} for path in args.project_file),
        *({"scope": "originals", "path": path} for path in args.originals_file),
        *({"scope": "exact", "path": path} for path in args.exact_file),
    ]


def _locator(scope: str, path: str) -> dict[str, str]:
    if scope not in {"project", "originals", "exact"}:
        raise SourceControlBusinessCliError(
            "Move locator scopes must be project, originals, or exact"
        )
    return {"scope": scope, "path": path}


__all__ = [
    "SourceControlBusinessCliError",
    "add_source_control_arguments",
    "source_control_fields_supplied",
    "source_control_plan_from_namespace",
]
