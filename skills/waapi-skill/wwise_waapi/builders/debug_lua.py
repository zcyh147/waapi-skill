"""Closed helpers for private debug reads and explicitly supplied Lua.

These helpers do not execute WAAPI.  They normalize bounded read results and
seal caller-supplied Lua source evidence for the transaction layer.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any, Mapping


MAX_WAL_TREE_NODES = 256
MAX_LUA_SOURCE_BYTES = 64 * 1024
MAX_LUA_WA_ARGS_BYTES = 64 * 1024
MAX_LUA_WA_ARGS_KEYS = 64
MAX_WWISE_SHORT_ID = (1 << 32) - 1

LUA_SOURCE_AUTHORITY = "user_supplied_verbatim"
CORE_LUA_RESERVED_FIELDS = frozenset(
    {"luaScript", "luaString", "doFiles", "luaPaths", "requires"}
)
CLI_LUA_RESERVED_FIELDS = frozenset(
    {
        "allow-migration",
        "do-file",
        "lua-path",
        "lua-script",
        "no-color",
        "project",
        "require",
        "watchdog-timeout",
    }
)


class DebugLuaContractError(ValueError):
    """A debug/Lua request is outside the packaged closed boundary."""

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = dict(details or {})

    def as_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": str(self),
            "details": dict(self.details),
        }


def normalize_lua_wa_args(
    value: Any,
    *,
    reserved_fields: frozenset[str],
) -> dict[str, Any]:
    """Return one bounded custom ``wa_args`` mapping with reserved keys closed."""

    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise DebugLuaContractError(
            "INVALID_ARGUMENT",
            "Lua wa_args must be a JSON object.",
        )
    if len(value) > MAX_LUA_WA_ARGS_KEYS:
        raise DebugLuaContractError(
            "LIMIT_EXCEEDED",
            f"Lua wa_args accepts at most {MAX_LUA_WA_ARGS_KEYS} top-level keys.",
            details={"count": len(value), "limit": MAX_LUA_WA_ARGS_KEYS},
        )
    normalized: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key or len(key.encode("utf-8")) > 128:
            raise DebugLuaContractError(
                "INVALID_ARGUMENT",
                "Every Lua wa_args key must be a non-empty UTF-8 string of at most 128 bytes.",
            )
        if key in reserved_fields:
            raise DebugLuaContractError(
                "RESERVED_ARGUMENT",
                "Lua wa_args cannot replace a packaged source or loader field.",
                details={"field": key, "reserved_fields": sorted(reserved_fields)},
            )
        normalized[key] = item
    try:
        encoded = json.dumps(
            normalized,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise DebugLuaContractError(
            "INVALID_ARGUMENT",
            "Lua wa_args must be strict JSON.",
            details={"error": str(exc)},
        ) from exc
    if len(encoded) > MAX_LUA_WA_ARGS_BYTES:
        raise DebugLuaContractError(
            "LIMIT_EXCEEDED",
            f"Lua wa_args exceeds the {MAX_LUA_WA_ARGS_BYTES}-byte limit.",
            details={"size_bytes": len(encoded), "limit_bytes": MAX_LUA_WA_ARGS_BYTES},
        )
    return normalized


def seal_inline_lua_source(
    value: Any,
    *,
    io_root: Any,
    source_authority: Any,
) -> dict[str, Any]:
    """Seal one exact user-supplied inline Lua string without rewriting it."""

    _require_source_authority(source_authority)
    root = _canonical_directory(io_root, field="io_root")
    if not isinstance(value, str) or not value.strip():
        raise DebugLuaContractError(
            "INVALID_ARGUMENT",
            "Inline Lua must be a non-empty string copied verbatim from the user.",
        )
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise DebugLuaContractError(
            "INVALID_ARGUMENT",
            "Inline Lua must be valid UTF-8 text.",
        ) from exc
    if len(encoded) > MAX_LUA_SOURCE_BYTES:
        raise DebugLuaContractError(
            "LIMIT_EXCEEDED",
            f"Inline Lua exceeds the {MAX_LUA_SOURCE_BYTES}-byte limit.",
            details={"size_bytes": len(encoded), "limit_bytes": MAX_LUA_SOURCE_BYTES},
        )
    return {
        "authority": LUA_SOURCE_AUTHORITY,
        "kind": "inline",
        "io_root": str(root),
        "size_bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def seal_isolated_lua_file(
    script_file: Any,
    *,
    io_root: Any,
    source_authority: Any,
) -> dict[str, Any]:
    """Hash one regular ``.lua`` file contained by an existing isolated root."""

    _require_source_authority(source_authority)
    root = _canonical_directory(io_root, field="io_root")
    proof = _regular_file_proof(
        script_file,
        field="script_file",
        suffix=".lua",
        maximum_bytes=MAX_LUA_SOURCE_BYTES,
    )
    script = Path(proof["path"])
    try:
        script.relative_to(root)
    except ValueError as exc:
        raise DebugLuaContractError(
            "PATH_OUTSIDE_IO_ROOT",
            "The Lua script must be contained by io_root after canonical path resolution.",
            details={"script_file": str(script), "io_root": str(root)},
        ) from exc
    return {
        "authority": LUA_SOURCE_AUTHORITY,
        "kind": "file",
        "io_root": str(root),
        "file": proof,
    }


def verify_isolated_lua_file(proof: Any) -> dict[str, Any]:
    """Recompute one sealed Lua file proof at the final execution boundary."""

    if not isinstance(proof, Mapping):
        raise DebugLuaContractError(
            "INVALID_PREVIEW",
            "The immutable Lua file proof is malformed.",
        )
    file_proof = proof.get("file")
    if (
        proof.get("authority") != LUA_SOURCE_AUTHORITY
        or proof.get("kind") != "file"
        or not isinstance(file_proof, Mapping)
        or not isinstance(proof.get("io_root"), str)
        or not isinstance(file_proof.get("path"), str)
    ):
        raise DebugLuaContractError(
            "INVALID_PREVIEW",
            "The immutable Lua file proof lacks its source authority, root, or file evidence.",
        )
    actual = seal_isolated_lua_file(
        file_proof["path"],
        io_root=proof["io_root"],
        source_authority=LUA_SOURCE_AUTHORITY,
    )
    return {
        "passed": actual == dict(proof),
        "expected": dict(proof),
        "actual": actual,
    }


def normalize_wal_tree_result(value: Any, *, take: int) -> dict[str, Any]:
    """Project the private WAL node map into one deterministic bounded list."""

    if isinstance(take, bool) or not isinstance(take, int) or not 1 <= take <= MAX_WAL_TREE_NODES:
        raise DebugLuaContractError(
            "INVALID_ARGUMENT",
            f"debug-wal-tree take must be between 1 and {MAX_WAL_TREE_NODES}.",
        )
    if not isinstance(value, Mapping):
        raise DebugLuaContractError("INVALID_READBACK", "getWalTree result must be a JSON object.")
    returned = value.get("return")
    nodes = returned.get("nodes") if isinstance(returned, Mapping) else None
    if not isinstance(nodes, Mapping):
        raise DebugLuaContractError(
            "INVALID_READBACK",
            "getWalTree result must contain return.nodes as an object.",
        )
    if len(nodes) > MAX_WAL_TREE_NODES:
        raise DebugLuaContractError(
            "LIMIT_EXCEEDED",
            f"getWalTree returned more than {MAX_WAL_TREE_NODES} nodes; "
            "the gateway will not sort or project an unbounded private result.",
            details={
                "node_count": len(nodes),
                "limit": MAX_WAL_TREE_NODES,
            },
        )
    rows: list[dict[str, Any]] = []
    for key in sorted(nodes, key=str):
        node = nodes[key]
        if (
            not isinstance(key, str)
            or not isinstance(node, Mapping)
            or isinstance(node.get("id"), bool)
            or not isinstance(node.get("id"), int)
            or not 0 <= node["id"] <= MAX_WWISE_SHORT_ID
            or not isinstance(node.get("name"), str)
            or not isinstance(node.get("type"), str)
        ):
            raise DebugLuaContractError(
                "INVALID_READBACK",
                "Every WAL node must have one string key, a uint32 integer id, "
                "and string name/type.",
                details={
                    "key": str(key),
                    "id_type": (
                        type(node.get("id")).__name__
                        if isinstance(node, Mapping)
                        else type(node).__name__
                    ),
                    "id_range": [0, MAX_WWISE_SHORT_ID],
                },
            )
        rows.append(
            {
                "key": key,
                "id": node["id"],
                "name": node["name"],
                "type": node["type"],
            }
        )
    return {
        "nodes": rows[:take],
        "returned_count": min(len(rows), take),
        "total_count": len(rows),
        "possibly_truncated": len(rows) > take,
        "take": take,
    }


def _require_source_authority(value: Any) -> None:
    if value != LUA_SOURCE_AUTHORITY:
        raise DebugLuaContractError(
            "SOURCE_AUTHORITY_REQUIRED",
            "Lua execution accepts only source explicitly supplied verbatim by the user.",
            details={
                "required": LUA_SOURCE_AUTHORITY,
                "actual": value,
            },
        )


def _canonical_directory(value: Any, *, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise DebugLuaContractError("INVALID_PATH", f"{field} must be a non-empty absolute path.")
    path = Path(value)
    if not path.is_absolute():
        raise DebugLuaContractError(
            "INVALID_PATH",
            f"{field} must be an absolute path.",
            details={"path": value},
        )
    try:
        path_lstat = path.lstat()
    except OSError as exc:
        raise DebugLuaContractError(
            "INVALID_PATH",
            f"{field} is not accessible.",
            details={"path": value, "error": str(exc)},
        ) from exc
    if stat.S_ISLNK(path_lstat.st_mode) or not stat.S_ISDIR(path_lstat.st_mode):
        raise DebugLuaContractError(
            "INVALID_PATH",
            f"{field} must identify an existing non-symlink directory.",
            details={"path": value},
        )
    try:
        return path.resolve(strict=True)
    except OSError as exc:
        raise DebugLuaContractError(
            "INVALID_PATH",
            f"{field} could not be resolved.",
            details={"path": value, "error": str(exc)},
        ) from exc


def _regular_file_proof(
    value: Any,
    *,
    field: str,
    suffix: str,
    maximum_bytes: int,
) -> dict[str, Any]:
    if not isinstance(value, str) or not value:
        raise DebugLuaContractError("INVALID_FILE", f"{field} must be a non-empty absolute path.")
    path = Path(value)
    if not path.is_absolute():
        raise DebugLuaContractError(
            "INVALID_FILE",
            f"{field} must be an absolute path.",
            details={"path": value},
        )
    if path.suffix.casefold() != suffix.casefold():
        raise DebugLuaContractError(
            "INVALID_FILE",
            f"{field} must use the {suffix} extension.",
            details={"path": value},
        )
    try:
        path_lstat = path.lstat()
    except OSError as exc:
        raise DebugLuaContractError(
            "INVALID_FILE",
            f"{field} is not accessible.",
            details={"path": value, "error": str(exc)},
        ) from exc
    if stat.S_ISLNK(path_lstat.st_mode) or not stat.S_ISREG(path_lstat.st_mode):
        raise DebugLuaContractError(
            "INVALID_FILE",
            f"{field} must identify a regular non-symlink file.",
            details={"path": value},
        )
    if path_lstat.st_size > maximum_bytes:
        raise DebugLuaContractError(
            "LIMIT_EXCEEDED",
            f"{field} exceeds the {maximum_bytes}-byte source limit.",
            details={"size_bytes": path_lstat.st_size, "limit_bytes": maximum_bytes},
        )
    try:
        canonical = path.resolve(strict=True)
    except OSError as exc:
        raise DebugLuaContractError(
            "INVALID_FILE",
            f"{field} could not be resolved.",
            details={"path": value, "error": str(exc)},
        ) from exc
    digest = hashlib.sha256()
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(canonical, flags)
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > maximum_bytes:
                raise DebugLuaContractError(
                    "INVALID_FILE",
                    f"{field} changed type or size before hashing.",
                    details={"path": str(canonical)},
                )
            for chunk in iter(lambda: handle.read(64 * 1024), b""):
                digest.update(chunk)
            after = os.fstat(handle.fileno())
    except DebugLuaContractError:
        raise
    except OSError as exc:
        raise DebugLuaContractError(
            "INVALID_FILE",
            f"{field} could not be hashed.",
            details={"path": str(canonical), "error": str(exc)},
        ) from exc
    if (
        before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        raise DebugLuaContractError(
            "FILE_CHANGED",
            f"{field} changed while its immutable proof was captured.",
            details={"path": str(canonical)},
        )
    return {
        "path": str(canonical),
        "size": after.st_size,
        "sha256": digest.hexdigest(),
    }


__all__ = [
    "CLI_LUA_RESERVED_FIELDS",
    "CORE_LUA_RESERVED_FIELDS",
    "DebugLuaContractError",
    "LUA_SOURCE_AUTHORITY",
    "MAX_LUA_SOURCE_BYTES",
    "MAX_LUA_WA_ARGS_BYTES",
    "MAX_LUA_WA_ARGS_KEYS",
    "MAX_WAL_TREE_NODES",
    "MAX_WWISE_SHORT_ID",
    "normalize_lua_wa_args",
    "normalize_wal_tree_result",
    "seal_inline_lua_source",
    "seal_isolated_lua_file",
    "verify_isolated_lua_file",
]
