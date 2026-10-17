"""Bind source-control file scopes to exact live object identities and accessors."""
from __future__ import annotations

from typing import Any, Callable, Mapping
from pathlib import Path

from .filesystem_security import path_is_link_or_reparse
from .host_paths import localize_waapi_host_path

from .business_declarations import normalize_live_object_identity
from .identity_limits import MULTI_IDENTITY_READ_MAX_IDS

MAX_SOURCE_CONTROL_OBJECT_SCOPES = min(64, MULTI_IDENTITY_READ_MAX_IDS)
GET = "ak.wwise.core.object.get"
SCOPES = {"containing-file": "filePath", "original-media": "originalFilePath"}
_FILE_URIS = frozenset("ak.wwise.core.sourceControl." + name for name in
                       ("add", "checkOut", "commit", "delete", "getStatus", "revert"))
Read = Callable[[str, Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]]


def validate_object_file_binding(operation: str, value: Any) -> list[dict[str, Any]]:
    if operation not in _FILE_URIS or not isinstance(value, Mapping) or set(value) != {"objects"}:
        raise ValueError("Object-file binding belongs only to disclosed source-control file actions")
    rows = value["objects"]
    keys = {"id", "name", "type", "path", "scope", "file_path"}
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_SOURCE_CONTROL_OBJECT_SCOPES:
        raise ValueError("Object-file binding requires a bounded nonempty object scope list")
    result = []
    seen = set()
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != keys or row.get("scope") not in SCOPES:
            raise ValueError("Object-file binding has unknown fields or scope")
        identity = normalize_live_object_identity(row)
        if row["scope"] == "original-media" and identity.object_type != "AudioFileSource":
            raise ValueError("Original-media scope requires one exact AudioFileSource; Sound source/language selection remains separate implementation work")
        path = row["file_path"]
        if not isinstance(path, str) or not path or "\x00" in path or len(path.encode("utf-8")) > 4096:
            raise ValueError("Object-file binding requires an observed bounded native file path")
        key = (identity.object_id, row["scope"])
        if key in seen:
            raise ValueError("Object-file scopes must be distinct")
        seen.add(key)
        result.append({**dict(row), "id": identity.object_id})
    return result


def observe_object_file_binding(operation: str, value: Any, *, read: Read) -> dict[str, Any]:
    expected = validate_object_file_binding(operation, value)
    unique_ids = list(dict.fromkeys(row["id"] for row in expected))
    fields = ["id", "name", "type", "path", *dict.fromkeys(SCOPES[row["scope"]] for row in expected)]
    result = read(GET, {"from": {"id": unique_ids}}, {"return": fields})
    rows = result.get("return") if isinstance(result, Mapping) else None
    if not isinstance(rows, list) or len(rows) != len(unique_ids):
        raise ValueError("Object-file readback must contain every exact GUID once")
    by_id = {}
    for row in rows:
        identity = normalize_live_object_identity(row)
        if identity.object_id not in unique_ids or identity.object_id in by_id:
            raise ValueError("Object-file readback contains duplicate or extra GUIDs")
        by_id[identity.object_id] = row
    observed = []
    for expected_row in expected:
        row = by_id[expected_row["id"]]
        accessor = SCOPES[expected_row["scope"]]
        if accessor not in row:
            raise ValueError("Object-file readback omitted its exact file accessor")
        observed.append({**{key: row[key] for key in ("id", "name", "type", "path")},
                         "id": normalize_live_object_identity(row).object_id,
                         "scope": expected_row["scope"], "file_path": row[accessor]})
    binding = {"objects": observed}
    validate_object_file_binding(operation, binding)
    return binding


def capture_object_file_binding(operation: str, session: Any, selections: Any, *, read: Read) -> dict[str, Any]:
    if not isinstance(selections, list) or not 1 <= len(selections) <= MAX_SOURCE_CONTROL_OBJECT_SCOPES:
        raise ValueError("Select between one and the disclosed maximum exact object-file scopes")
    expected = []
    for selection in selections:
        if not isinstance(selection, Mapping) or set(selection) != {"handle", "scope"}:
            raise ValueError("Select only a bound Object Handle and disclosed file scope")
        bound = session.handles.resolve_object(selection["handle"])
        expected.append({"id": bound.object_id, "name": bound.name, "type": bound.object_type, "path": bound.path,
                         "scope": selection["scope"], "file_path": "pending-live-read"})
    observed = observe_object_file_binding(operation, {"objects": expected}, read=read)
    for before, after in zip(expected, observed["objects"], strict=True):
        if any(before[key] != after[key] for key in ("id", "name", "type", "path")):
            raise ValueError("The selected Object Handle changed before its file scope was bound")
    return observed


def observe_bound_file_state(operation: str, binding: Any) -> list[dict[str, Any]]:
    """Bind ordinary local file identity; this does not prove provider state."""
    rows = validate_object_file_binding(operation, binding)
    result = []
    seen = set()
    for row in rows:
        candidate = Path(localize_waapi_host_path(row["file_path"]))
        if not candidate.is_absolute():
            raise ValueError("An observed source-control file must be absolute for this host")
        if any(path_is_link_or_reparse(path) for path in (candidate, *candidate.parents)):
            raise ValueError("The bound source-control file path contains a link or reparse point")
        path = candidate.resolve(strict=False)
        if str(path) in seen:
            continue
        seen.add(str(path))
        if not path.exists():
            result.append({"path": str(path), "exists": False})
            continue
        if not path.is_file():
            raise ValueError("The bound source-control path is not an ordinary file")
        stat = path.stat()
        result.append({"path": str(path), "exists": True, "device": stat.st_dev, "inode": stat.st_ino,
                       "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "mode": stat.st_mode})
    return result
