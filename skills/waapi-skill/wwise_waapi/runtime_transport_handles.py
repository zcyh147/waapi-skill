"""Opaque, project-bound capabilities for live Authoring transports."""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .canonical import canonical_json_bytes, canonical_sha256


TRANSPORT_HANDLE_STORE_CONTRACT = "waapi-skill.runtime-transport-handle-store/v1"
TRANSPORT_HANDLE_RECORD_CONTRACT = "waapi-skill.runtime-transport-handle/v1"
_HANDLE = re.compile(r"^trh1-[0-9a-f]{32}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_RECORD_BYTES = 16 * 1024
_MAX_RECORDS = 1024


class RuntimeTransportHandleError(ValueError):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.error_code = error_code
        self.details = dict(details or {})
        super().__init__(message)


def _required_text(value: Any, *, field: str, maximum_bytes: int = 4096) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
        or len(value.encode("utf-8")) > maximum_bytes
    ):
        raise ValueError(f"{field} must be one bounded nonempty string")
    return value


@dataclass(frozen=True, slots=True)
class RuntimeTransportContext:
    endpoint_url: str
    project_id: str
    project_path: str
    wwise_version: str
    wwise_build: str

    def __post_init__(self) -> None:
        for field in (
            "endpoint_url",
            "project_id",
            "project_path",
            "wwise_version",
            "wwise_build",
        ):
            _required_text(getattr(self, field), field=field)

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RuntimeTransportHandle:
    handle: str
    transport_id: int
    context: RuntimeTransportContext
    source_transaction_id: str
    source_artifact_hash: str
    transport_row_sha256: str
    active: bool
    record_sha256: str

    def binding_dict(self) -> dict[str, Any]:
        return {
            "contract": TRANSPORT_HANDLE_RECORD_CONTRACT,
            "handle": self.handle,
            "transport_id": self.transport_id,
            "context": self.context.as_dict(),
            "source_transaction_id": self.source_transaction_id,
            "source_artifact_hash": self.source_artifact_hash,
            "transport_row_sha256": self.transport_row_sha256,
            "record_sha256": self.record_sha256,
        }


class RuntimeTransportHandleStore:
    """Bounded local capability table; native IDs never cross its public key."""

    def __init__(
        self,
        state_dir: Path,
        *,
        token_bytes: Callable[[int], bytes] = secrets.token_bytes,
    ) -> None:
        if not isinstance(state_dir, Path):
            raise TypeError("state_dir must be a pathlib.Path")
        self.state_dir = state_dir
        self.root = state_dir / "runtime-transport-handles-v1"
        self.records = self.root / "records"
        self._token_bytes = token_bytes
        self._ensure_directory(self.state_dir)
        self._ensure_directory(self.root)
        self._ensure_directory(self.records)

    def issue(
        self,
        *,
        transport_id: int,
        context: RuntimeTransportContext,
        source_transaction_id: str,
        source_artifact_hash: str,
        transport_row_sha256: str,
    ) -> RuntimeTransportHandle:
        if (
            isinstance(transport_id, bool)
            or not isinstance(transport_id, int)
            or not 1 <= transport_id <= 0xFFFFFFFF
        ):
            raise ValueError("transport_id must be a non-zero uint32")
        if not isinstance(context, RuntimeTransportContext):
            raise TypeError("context must be RuntimeTransportContext")
        transaction_id = _required_text(
            source_transaction_id,
            field="source_transaction_id",
            maximum_bytes=128,
        )
        if not isinstance(source_artifact_hash, str) or not _SHA256.fullmatch(
            source_artifact_hash
        ):
            raise ValueError("source_artifact_hash must be lowercase SHA-256")
        if not isinstance(transport_row_sha256, str) or not _SHA256.fullmatch(
            transport_row_sha256
        ):
            raise ValueError("transport_row_sha256 must be lowercase SHA-256")
        token = self._token_bytes(16)
        if not isinstance(token, bytes) or len(token) != 16:
            raise ValueError("transport handle token source must return 16 bytes")
        handle = f"trh1-{token.hex()}"
        body = {
            "contract": TRANSPORT_HANDLE_RECORD_CONTRACT,
            "handle": handle,
            "transport_id": transport_id,
            "context": context.as_dict(),
            "source_transaction_id": transaction_id,
            "source_artifact_hash": source_artifact_hash,
            "transport_row_sha256": transport_row_sha256,
            "active": True,
        }
        payload = {**body, "record_sha256": canonical_sha256(body)}
        self._write_new(self._path(handle), payload)
        return self._parse(payload)

    def resolve(
        self,
        handle: str,
        *,
        context: RuntimeTransportContext,
    ) -> RuntimeTransportHandle:
        normalized = self._validate_handle(handle)
        record = self._load(self._path(normalized))
        if record.context != context:
            raise RuntimeTransportHandleError(
                "TRANSPORT_HANDLE_CONTEXT_DRIFT",
                "Transport handle belongs to a different Wwise runtime or project.",
            )
        if not record.active:
            raise RuntimeTransportHandleError(
                "TRANSPORT_HANDLE_RETIRED",
                "Transport handle was already retired and cannot be reused.",
            )
        return record

    def retire_native_id(
        self,
        transport_id: int,
        *,
        context: RuntimeTransportContext,
    ) -> tuple[str, ...]:
        paths = sorted(self.records.glob("trh1-*.json"))
        if len(paths) > _MAX_RECORDS:
            raise RuntimeTransportHandleError(
                "TRANSPORT_HANDLE_STORE_LIMIT",
                "Transport handle store exceeds its fixed record ceiling.",
            )
        retired: list[str] = []
        for path in paths:
            record = self._load(path)
            if (
                record.active
                and record.transport_id == transport_id
                and record.context == context
            ):
                body = {
                    "contract": TRANSPORT_HANDLE_RECORD_CONTRACT,
                    "handle": record.handle,
                    "transport_id": record.transport_id,
                    "context": record.context.as_dict(),
                    "source_transaction_id": record.source_transaction_id,
                    "source_artifact_hash": record.source_artifact_hash,
                    "transport_row_sha256": record.transport_row_sha256,
                    "active": False,
                }
                self._replace(
                    path,
                    {**body, "record_sha256": canonical_sha256(body)},
                )
                retired.append(record.handle)
        return tuple(retired)

    def resolve_native_id(
        self,
        transport_id: int,
        *,
        context: RuntimeTransportContext,
    ) -> RuntimeTransportHandle:
        matches = [
            record
            for record in self._active_records()
            if record.transport_id == transport_id and record.context == context
        ]
        if len(matches) != 1:
            raise RuntimeTransportHandleError(
                "TRANSPORT_HANDLE_NOT_BOUND",
                "Native transport ID is not bound to exactly one active Gateway handle.",
                details={"match_count": len(matches)},
            )
        return matches[0]

    @staticmethod
    def validate_live_row(
        record: RuntimeTransportHandle,
        row: Mapping[str, Any],
    ) -> None:
        if canonical_sha256(row) != record.transport_row_sha256:
            raise RuntimeTransportHandleError(
                "TRANSPORT_HANDLE_STALE",
                "Live transport identity differs from the row bound when the handle was issued.",
            )

    def _active_records(self) -> tuple[RuntimeTransportHandle, ...]:
        paths = sorted(self.records.glob("trh1-*.json"))
        if len(paths) > _MAX_RECORDS:
            raise RuntimeTransportHandleError(
                "TRANSPORT_HANDLE_STORE_LIMIT",
                "Transport handle store exceeds its fixed record ceiling.",
            )
        return tuple(record for path in paths if (record := self._load(path)).active)

    def _path(self, handle: str) -> Path:
        return self.records / f"{handle}.json"

    @staticmethod
    def _validate_handle(handle: Any) -> str:
        if not isinstance(handle, str) or not _HANDLE.fullmatch(handle):
            raise RuntimeTransportHandleError(
                "TRANSPORT_HANDLE_INVALID",
                "transport_handle must be copied exactly from a Gateway transport result",
            )
        return handle

    def _load(self, path: Path) -> RuntimeTransportHandle:
        if not path.exists():
            raise RuntimeTransportHandleError(
                "TRANSPORT_HANDLE_UNKNOWN",
                "Transport handle was not issued by this Gateway state store.",
            )
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
            raise RuntimeTransportHandleError(
                "TRANSPORT_HANDLE_STORE_CORRUPT",
                "Transport handle record is not a regular file.",
            )
        if metadata.st_size > _MAX_RECORD_BYTES:
            raise RuntimeTransportHandleError(
                "TRANSPORT_HANDLE_STORE_CORRUPT",
                "Transport handle record exceeds its fixed size ceiling.",
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeTransportHandleError(
                "TRANSPORT_HANDLE_STORE_CORRUPT",
                "Transport handle record is unreadable.",
            ) from exc
        return self._parse(payload)

    @staticmethod
    def _parse(payload: Any) -> RuntimeTransportHandle:
        expected = {
            "contract",
            "handle",
            "transport_id",
            "context",
            "source_transaction_id",
            "source_artifact_hash",
            "transport_row_sha256",
            "active",
            "record_sha256",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise RuntimeTransportHandleError(
                "TRANSPORT_HANDLE_STORE_CORRUPT",
                "Transport handle record fields are invalid.",
            )
        seal = payload.get("record_sha256")
        body = {key: payload[key] for key in expected if key != "record_sha256"}
        if (
            payload.get("contract") != TRANSPORT_HANDLE_RECORD_CONTRACT
            or not isinstance(seal, str)
            or canonical_sha256(body) != seal
        ):
            raise RuntimeTransportHandleError(
                "TRANSPORT_HANDLE_STORE_CORRUPT",
                "Transport handle record seal is invalid.",
            )
        try:
            context = RuntimeTransportContext(**payload["context"])
            handle = RuntimeTransportHandleStore._validate_handle(payload["handle"])
            transport_id = payload["transport_id"]
            if (
                isinstance(transport_id, bool)
                or not isinstance(transport_id, int)
                or not 1 <= transport_id <= 0xFFFFFFFF
                or not isinstance(payload["active"], bool)
                or not isinstance(payload["source_artifact_hash"], str)
                or not _SHA256.fullmatch(payload["source_artifact_hash"])
                or not isinstance(payload["transport_row_sha256"], str)
                or not _SHA256.fullmatch(payload["transport_row_sha256"])
            ):
                raise ValueError("invalid transport handle record values")
            source_transaction_id = _required_text(
                payload["source_transaction_id"],
                field="source_transaction_id",
                maximum_bytes=128,
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, RuntimeTransportHandleError):
                raise
            raise RuntimeTransportHandleError(
                "TRANSPORT_HANDLE_STORE_CORRUPT",
                "Transport handle record values are invalid.",
            ) from exc
        return RuntimeTransportHandle(
            handle=handle,
            transport_id=transport_id,
            context=context,
            source_transaction_id=source_transaction_id,
            source_artifact_hash=payload["source_artifact_hash"],
            transport_row_sha256=payload["transport_row_sha256"],
            active=payload["active"],
            record_sha256=seal,
        )

    @staticmethod
    def _ensure_directory(path: Path) -> None:
        if path.exists():
            if path.is_symlink() or not path.is_dir():
                raise RuntimeTransportHandleError(
                    "TRANSPORT_HANDLE_STORE_CORRUPT",
                    "Transport handle state path is not a real directory.",
                )
            return
        path.mkdir(mode=0o700)

    @staticmethod
    def _write_new(path: Path, payload: Mapping[str, Any]) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError as exc:
            raise RuntimeTransportHandleError(
                "TRANSPORT_HANDLE_COLLISION",
                "Generated transport handle already exists.",
            ) from exc
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(canonical_json_bytes(payload) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _replace(path: Path, payload: Mapping[str, Any]) -> None:
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        RuntimeTransportHandleStore._write_new(temporary, payload)
        os.replace(temporary, path)


__all__ = [
    "RuntimeTransportContext",
    "RuntimeTransportHandle",
    "RuntimeTransportHandleError",
    "RuntimeTransportHandleStore",
    "validate_runtime_transport_handle",
]


def validate_runtime_transport_handle(handle: Any) -> str:
    """Validate only the opaque public token shape; resolution stays stateful."""

    return RuntimeTransportHandleStore._validate_handle(handle)
