"""CLI declarations for the closed source-control business interface."""

from __future__ import annotations

import argparse
from typing import Any

from .source_control_business_contracts import (
    SOURCE_CONTROL_COMMIT_URI,
    SOURCE_CONTROL_GET_SOURCE_FILES_URI,
    SOURCE_CONTROL_MOVE_URI,
    SOURCE_CONTROL_SET_PROVIDER_URI,
)


_MOVE_FIELDS = ("move_source_file", "move_source_object", "move_source_sound_active", "move_source_sound_language",
                "move_source_sound_source", "move_destination_file", "move_destination_object")


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
    parser.add_argument("--object-file", action="append", default=[], help="Containing file of an exact bound Object Handle")
    parser.add_argument("--original-media-object", action="append", default=[], help="Original file of an exact AudioFileSource Handle")
    parser.add_argument("--provider-profile", choices=("configured",))
    parser.add_argument("--sound-active-media", action="append", nargs=2, default=[], metavar=("SOUND_HANDLE", "LANGUAGE"))
    parser.add_argument("--sound-language-media", action="append", nargs=2, default=[], metavar=("SOUND_HANDLE", "LANGUAGE"))
    parser.add_argument("--sound-source-media", action="append", nargs=3, default=[], metavar=("SOUND_HANDLE", "SOURCE_HANDLE", "LANGUAGE"))
    for flag, fields in (
        ("move-source-file", ("ROW", "SCOPE", "PATH")),
        ("move-source-object", ("ROW", "HANDLE", "SCOPE")),
        ("move-source-sound-active", ("ROW", "SOUND_HANDLE", "LANGUAGE")),
        ("move-source-sound-language", ("ROW", "SOUND_HANDLE", "LANGUAGE")),
        ("move-source-sound-source", ("ROW", "SOUND_HANDLE", "SOURCE_HANDLE", "LANGUAGE")),
        ("move-destination-file", ("ROW", "SCOPE", "PATH")),
        ("move-destination-object", ("ROW", "HANDLE", "SCOPE", "BASENAME")),
    ):
        parser.add_argument("--" + flag, action="append", nargs=len(fields), default=[], metavar=fields)
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
    from .object_query_outputs import QUERY_BUSINESS_OUTPUTS
    parser.add_argument("--usage-output", action="append", default=[],
                        choices=tuple(QUERY_BUSINESS_OUTPUTS),
                        help="Disclosed business output for each usage object; repeat for several")
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
            "provider_profile",
            "io_root",
            "commit_message",
            "usage_scope",
            "originals_folder",
            "recursive",
            "include_usage_objects",
        )
    ) or any(
        bool(getattr(args, name, ()))
        for name in ("project_file", "originals_file", "exact_file", "move", "usage_output", "object_file", "original_media_object", "sound_active_media", "sound_language_media", "sound_source_media", *_MOVE_FIELDS)
    )


def source_control_plan_from_namespace(
    args: argparse.Namespace,
    *,
    operation: str,
) -> dict[str, Any]:
    selected = getattr(args, "provider_profile", None)
    if operation == SOURCE_CONTROL_SET_PROVIDER_URI:
        others = any(getattr(args, name, None) is not None for name in
            ("io_root", "commit_message", "usage_scope", "originals_folder", "recursive", "include_usage_objects", "max_results"))
        if selected != "configured" or others or _locator_fields_supplied(args) or args.move or args.usage_output:
            raise SourceControlBusinessCliError("Provider configuration accepts only --provider-profile configured; select its private file through config-set")
        return {"provider_profile": "configured"}
    if selected is not None:
        raise SourceControlBusinessCliError("Provider profile selection applies only to setProvider")
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
        if args.usage_output:
            plan["usage_outputs"] = list(args.usage_output)
        return plan
    files = _file_locators(args)
    object_files = [{"handle": handle, "scope": scope}
                    for name, scope in (("object_file", "containing-file"), ("original_media_object", "original-media"))
                    for handle in getattr(args, name, [])]
    object_files.extend({"handle": handle, "scope": "sound-original-media", "mode": "active", "language": language}
                        for handle, language in args.sound_active_media)
    object_files.extend({"handle": handle, "scope": "sound-original-media", "mode": "language", "language": language}
                        for handle, language in args.sound_language_media)
    object_files.extend({"handle": handle, "scope": "sound-original-media", "mode": "source",
                         "source_handle": source, "language": language}
                        for handle, source, language in args.sound_source_media)
    if operation == SOURCE_CONTROL_MOVE_URI:
        if files or object_files or args.commit_message is not None:
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
        rows = _move_rows(args)
        if rows:
            plan["object_moves"] = rows
    else:
        if args.move or any(getattr(args, name, ()) for name in _MOVE_FIELDS):
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
    if object_files:
        plan["object_files"] = object_files
    if args.io_root is not None:
        plan["io_root"] = args.io_root
    if bool(args.usage_output) or any(
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
        for name in ("project_file", "originals_file", "exact_file", "object_file", "original_media_object", "sound_active_media", "sound_language_media", "sound_source_media", *_MOVE_FIELDS)
    )


def _move_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for field in _MOVE_FIELDS:
        for row_id, *parts in getattr(args, field, ()):
            row = rows.setdefault(row_id, {"row_id": row_id})
            side = "source" if field.startswith("move_source_") else "destination"
            if side in row:
                raise SourceControlBusinessCliError("Each move row must select its source and destination exactly once")
            if field.endswith("_file"):
                endpoint = {"file": _locator(*parts)}
            elif field.endswith("_object"):
                handle, scope, *basename = parts
                if scope not in {"containing-file", "original-media"}:
                    raise SourceControlBusinessCliError("Object move scopes are containing-file or original-media")
                endpoint = {"object": {"handle": handle, "scope": scope}}
                if basename:
                    endpoint["basename"] = basename[0]
            else:
                mode = field.removeprefix("move_source_sound_")
                handle, *choice = parts
                selection = {"handle": handle, "scope": "sound-original-media", "mode": mode, "language": choice[-1]}
                if mode == "source":
                    selection["source_handle"] = choice[0]
                endpoint = {"object": selection}
            row[side] = endpoint
    if any(set(row) != {"row_id", "source", "destination"} for row in rows.values()):
        raise SourceControlBusinessCliError("Every move row label requires exactly one source and destination")
    return [rows[row_id] for row_id in sorted(rows)]


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
