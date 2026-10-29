"""Closed source-control move rows and their reusable object-file proofs."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Mapping

from .host_paths import localize_waapi_host_path, parse_relative_host_path

MOVE_URI = "ak.wwise.core.sourceControl.move"
MAX_MOVE_ROWS = 256
_ROW_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _row_id(value: Any) -> str:
    if not isinstance(value, str) or not _ROW_ID.fullmatch(value):
        raise ValueError("Move row labels require 1..64 letters, digits, periods, underscores or hyphens")
    return value


def _basename(value: Any) -> str:
    parts = parse_relative_host_path(value).components
    if len(parts) != 1 or len(value.encode("utf-8")) > 4096:
        raise ValueError("Move destination requires one bounded explicit filename, without a directory")
    return value


def _path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or len(value.encode("utf-8")) > 4096:
        raise ValueError("Move proof requires bounded absolute file paths")
    candidate = Path(localize_waapi_host_path(value))
    if not candidate.is_absolute():
        raise ValueError("Move proof requires an absolute file path")
    return str(candidate.resolve(strict=False))


def capture_move_inputs(operation: str, session: Any, moves: Any, *, read: Callable[..., Any]) -> dict[str, Any]:
    """Resolve public Handles once and keep explicit source/destination row associations."""
    from .source_control_object_files import capture_object_file_binding
    if operation != MOVE_URI or not isinstance(moves, list) or not 1 <= len(moves) <= MAX_MOVE_ROWS:
        raise ValueError("Select a bounded nonempty list of closed move rows")
    selections, prepared, seen = [], [], set()
    for move in moves:
        if not isinstance(move, Mapping) or set(move) != {"row_id", "source", "destination"}:
            raise ValueError("Move rows require a label and exactly one source and destination")
        row_id = _row_id(move["row_id"])
        if row_id in seen:
            raise ValueError("Move row labels must be distinct")
        seen.add(row_id)
        row = {"row_id": row_id}
        for side in ("source", "destination"):
            endpoint = move[side]
            if not isinstance(endpoint, Mapping):
                raise ValueError("Move endpoints require a disclosed file or object-file choice")
            if set(endpoint) == {"file"}:
                row[side] = {"file": dict(endpoint["file"])}
                continue
            expected = {"object"} if side == "source" else {"object", "basename"}
            if set(endpoint) != expected or not isinstance(endpoint["object"], Mapping):
                raise ValueError("Move object endpoints require a closed selection and destination filename")
            selection = dict(endpoint["object"])
            if selection not in selections:
                selections.append(selection)
            row[side] = {"object_index": selections.index(selection)}
            if side == "destination":
                row[side]["basename"] = _basename(endpoint["basename"])
        prepared.append(row)
    objects = capture_object_file_binding(operation, session, selections, read=read)["objects"] if selections else []
    return {"objects": objects, "rows": prepared}


def materialize_move_inputs(value: Mapping[str, Any], *, resolve_file: Callable[..., Path]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    objects, rows = value["objects"], value["rows"]
    moves, proof = [], []
    for row in rows:
        paths, indices = {}, {}
        for side in ("source", "destination"):
            endpoint = row[side]
            index = endpoint.get("object_index")
            if index is None:
                paths[side] = str(resolve_file(endpoint["file"], derived=False))
            else:
                path = Path(localize_waapi_host_path(objects[index]["file_path"]))
                if side == "destination":
                    path = path.parent / _basename(endpoint["basename"])
                paths[side] = str(resolve_file({"scope": "exact", "path": str(path)}, derived=True))
            indices[side] = index
        moves.append({side: {"scope": "exact", "path": paths[side]} for side in paths})
        proof.append({"row_id": row["row_id"], "source_index": indices["source"],
            "destination_index": indices["destination"], "basename": row["destination"].get("basename"),
            "source_path": paths["source"], "destination_path": paths["destination"]})
    binding = {"objects": objects, "moves": proof}
    validate_move_binding(binding, objects)
    return moves, binding


def validate_move_binding(binding: Mapping[str, Any], objects: list[dict[str, Any]]) -> list[tuple[str, str]]:
    rows = binding.get("moves")
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_MOVE_ROWS:
        raise ValueError("Bound moves require a bounded nonempty row list")
    seen, used, pairs = set(), set(), []
    fields = {"row_id", "source_index", "destination_index", "basename", "source_path", "destination_path"}
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != fields:
            raise ValueError("Bound moves require exact closed row fields")
        if row["row_id"] is None:
            if row["source_index"] is not None or row["destination_index"] is not None or row["basename"] is not None:
                raise ValueError("Unlabelled literal rows cannot refer to object endpoints")
        else:
            label = _row_id(row["row_id"])
            if label in seen:
                raise ValueError("Bound move labels must be distinct")
            seen.add(label)
        for side in ("source", "destination"):
            index, actual = row[side + "_index"], _path(row[side + "_path"])
            if index is None:
                if side == "destination" and row["basename"] is not None:
                    raise ValueError("Literal destinations cannot carry an object-directory filename")
                continue
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(objects):
                raise ValueError("Move row refers to an unknown object-file proof")
            used.add(index)
            expected = Path(localize_waapi_host_path(objects[index]["file_path"]))
            if side == "destination":
                expected = expected.parent / _basename(row["basename"])
            if _path(str(expected)) != actual:
                raise ValueError("Move row no longer matches its exact source or destination directory")
        pairs.append((_path(row["source_path"]), _path(row["destination_path"])))
    if used != set(range(len(objects))):
        raise ValueError("Every object-file proof must belong to a sealed move endpoint")
    return pairs
