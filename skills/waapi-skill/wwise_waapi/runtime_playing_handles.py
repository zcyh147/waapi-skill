"""Durable opaque capabilities for SoundEngine playing IDs."""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .canonical import canonical_json_bytes, canonical_sha256
from .filesystem_security import path_is_link_or_reparse
from .runtime_game_object_handles import RuntimeGameObjectContext


RUNTIME_PLAYING_HANDLE_CONTRACT = "waapi-skill.soundengine-playing-handle/v1"
_HANDLE = re.compile(r"^plh1-[0-9a-f]{32}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_RECORD_BYTES = 16 * 1024
_MAX_RECORDS = 1024


class RuntimePlayingHandleError(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        self.error_code = error_code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class RuntimePlayingHandleRecord:
    handle: str
    playing_id: int
    event_id: str
    game_object_id: int | None
    context: RuntimeGameObjectContext
    source_transaction_id: str
    source_artifact_hash: str
    active: bool
    record_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "contract": RUNTIME_PLAYING_HANDLE_CONTRACT,
            "handle": self.handle,
            "playing_id": self.playing_id,
            "event_id": self.event_id,
            "game_object_id": self.game_object_id,
            "context": self.context.binding_dict(),
            "source_transaction_id": self.source_transaction_id,
            "source_artifact_hash": self.source_artifact_hash,
            "active": self.active,
            "record_sha256": self.record_sha256,
        }


class RuntimePlayingHandleStore:
    """A bounded capability table; native playing IDs never cross its public key."""

    def __init__(self, state_dir: Path) -> None:
        if not isinstance(state_dir, Path):
            raise TypeError("state_dir must be a pathlib.Path")
        self.root = state_dir / "soundengine-playing-handles-v1"
        self.records = self.root / "records"
        self._ensure_directory(state_dir)
        self._ensure_directory(self.root)
        self._ensure_directory(self.records)

    def issue(
        self,
        *,
        playing_id: int,
        event_id: str,
        game_object_id: int | None,
        context: RuntimeGameObjectContext,
        source_transaction_id: str,
        source_artifact_hash: str,
    ) -> RuntimePlayingHandleRecord:
        if (
            isinstance(playing_id, bool)
            or not isinstance(playing_id, int)
            or not 1 <= playing_id <= 0xFFFFFFFF
        ):
            raise RuntimePlayingHandleError(
                "PLAYING_HANDLE_NOT_STARTED",
                "SoundEngine did not return one valid nonzero playing ID.",
            )
        if not isinstance(event_id, str) or not event_id or "\x00" in event_id:
            raise RuntimePlayingHandleError(
                "PLAYING_HANDLE_INVALID", "Event identity is invalid."
            )
        if game_object_id is not None and (
            isinstance(game_object_id, bool)
            or not isinstance(game_object_id, int)
            or not 0 <= game_object_id <= 0xFFFFFFFFFFFFFFDF
        ):
            raise RuntimePlayingHandleError(
                "PLAYING_HANDLE_INVALID", "Game object identity is invalid."
            )
        if (
            not isinstance(source_transaction_id, str)
            or not source_transaction_id
            or len(source_transaction_id.encode("utf-8")) > 128
            or not isinstance(source_artifact_hash, str)
            or not _SHA256.fullmatch(source_artifact_hash)
        ):
            raise RuntimePlayingHandleError(
                "PLAYING_HANDLE_INVALID", "Playing handle provenance is invalid."
            )
        paths = self._record_paths()
        if len(paths) >= _MAX_RECORDS:
            self._prune_retired_records(reserve=1)
            paths = self._record_paths()
        if len(paths) >= _MAX_RECORDS:
            raise RuntimePlayingHandleError(
                "PLAYING_HANDLE_STORE_LIMIT",
                "Playing handle store reached its fixed active-record ceiling.",
            )
        for _ in range(8):
            handle = f"plh1-{secrets.token_hex(16)}"
            path = self.records / f"{handle}.json"
            if os.path.lexists(path):
                continue
            body = {
                "contract": RUNTIME_PLAYING_HANDLE_CONTRACT,
                "handle": handle,
                "playing_id": playing_id,
                "event_id": event_id,
                "game_object_id": game_object_id,
                "context": context.binding_dict(),
                "source_transaction_id": source_transaction_id,
                "source_artifact_hash": source_artifact_hash,
                "active": True,
            }
            payload = {**body, "record_sha256": canonical_sha256(body)}
            self._write_new(path, payload)
            return self._parse(payload)
        raise RuntimePlayingHandleError(
            "PLAYING_HANDLE_PERSISTENCE_FAILED",
            "Could not allocate a unique playing handle.",
        )

    def resolve(
        self,
        handle: object,
        *,
        context: RuntimeGameObjectContext,
    ) -> RuntimePlayingHandleRecord:
        validated = validate_runtime_playing_handle(handle)
        record = self._load(self.records / f"{validated}.json")
        if record.context != context:
            raise RuntimePlayingHandleError(
                "PLAYING_HANDLE_CONTEXT_DRIFT",
                "Playing handle belongs to a different endpoint, project, or Wwise build.",
            )
        if not record.active:
            raise RuntimePlayingHandleError(
                "PLAYING_HANDLE_RETIRED",
                "Playing handle was already retired and cannot be reused.",
            )
        return record

    def resolve_native_id(
        self,
        playing_id: int,
        *,
        context: RuntimeGameObjectContext,
    ) -> RuntimePlayingHandleRecord:
        matches = [
            record
            for record in self._active_records()
            if record.playing_id == playing_id and record.context == context
        ]
        if len(matches) != 1:
            raise RuntimePlayingHandleError(
                "PLAYING_HANDLE_NOT_AVAILABLE",
                "Native playing ID does not resolve to one active Gateway handle.",
            )
        return matches[0]

    def retire_native_id(
        self,
        playing_id: int,
        *,
        context: RuntimeGameObjectContext,
    ) -> tuple[str, ...]:
        retired: list[str] = []
        for record in self._active_records():
            if record.playing_id != playing_id or record.context != context:
                continue
            body = {
                key: value
                for key, value in record.as_dict().items()
                if key != "record_sha256"
            }
            body["active"] = False
            self._replace(
                self.records / f"{record.handle}.json",
                {**body, "record_sha256": canonical_sha256(body)},
            )
            retired.append(record.handle)
        return tuple(retired)

    def _active_records(self) -> tuple[RuntimePlayingHandleRecord, ...]:
        return tuple(
            record
            for path in self._record_paths()
            if (record := self._load(path)).active
        )

    def _record_paths(self) -> tuple[Path, ...]:
        paths = tuple(sorted(self.records.glob("plh1-*.json")))
        if len(paths) > _MAX_RECORDS:
            raise RuntimePlayingHandleError(
                "PLAYING_HANDLE_STORE_LIMIT",
                "Playing handle store exceeds its fixed record ceiling.",
            )
        return paths

    def _prune_retired_records(self, *, reserve: int) -> None:
        paths = tuple(sorted(self.records.glob("plh1-*.json")))
        remove_count = max(0, len(paths) + reserve - _MAX_RECORDS)
        for path in paths:
            if remove_count == 0:
                return
            if not self._load(path).active:
                path.unlink()
                remove_count -= 1

    def _load(self, path: Path) -> RuntimePlayingHandleRecord:
        if not os.path.lexists(path):
            raise RuntimePlayingHandleError(
                "PLAYING_HANDLE_NOT_AVAILABLE",
                "Playing handle was not issued by this Gateway state store.",
            )
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise RuntimePlayingHandleError(
                "PLAYING_HANDLE_STORE_CORRUPT",
                "Playing handle record cannot be inspected safely.",
            ) from exc
        if (
            not stat.S_ISREG(metadata.st_mode)
            or path_is_link_or_reparse(path, metadata=metadata)
            or metadata.st_size > _MAX_RECORD_BYTES
        ):
            raise RuntimePlayingHandleError(
                "PLAYING_HANDLE_STORE_CORRUPT",
                "Playing handle record is not one bounded regular file.",
            )
        try:
            return self._parse(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            if isinstance(exc, RuntimePlayingHandleError):
                raise
            raise RuntimePlayingHandleError(
                "PLAYING_HANDLE_STORE_CORRUPT",
                "Playing handle record is unreadable.",
            ) from exc

    @staticmethod
    def _parse(payload: object) -> RuntimePlayingHandleRecord:
        expected = {
            "contract",
            "handle",
            "playing_id",
            "event_id",
            "game_object_id",
            "context",
            "source_transaction_id",
            "source_artifact_hash",
            "active",
            "record_sha256",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise RuntimePlayingHandleError(
                "PLAYING_HANDLE_STORE_CORRUPT",
                "Playing handle record fields are invalid.",
            )
        seal = payload.get("record_sha256")
        body = {key: payload[key] for key in expected if key != "record_sha256"}
        if (
            payload.get("contract") != RUNTIME_PLAYING_HANDLE_CONTRACT
            or not isinstance(seal, str)
            or canonical_sha256(body) != seal
        ):
            raise RuntimePlayingHandleError(
                "PLAYING_HANDLE_STORE_CORRUPT",
                "Playing handle record seal is invalid.",
            )
        try:
            handle = validate_runtime_playing_handle(payload["handle"])
            context_payload = payload["context"]
            context = RuntimeGameObjectContext(**context_payload)
            playing_id = payload["playing_id"]
            game_object_id = payload["game_object_id"]
            if (
                isinstance(playing_id, bool)
                or not isinstance(playing_id, int)
                or not 1 <= playing_id <= 0xFFFFFFFF
                or not isinstance(payload["event_id"], str)
                or not payload["event_id"]
                or (
                    game_object_id is not None
                    and (
                        isinstance(game_object_id, bool)
                        or not isinstance(game_object_id, int)
                        or not 0 <= game_object_id <= 0xFFFFFFFFFFFFFFDF
                    )
                )
                or not isinstance(payload["source_transaction_id"], str)
                or not payload["source_transaction_id"]
                or not isinstance(payload["source_artifact_hash"], str)
                or not _SHA256.fullmatch(payload["source_artifact_hash"])
                or not isinstance(payload["active"], bool)
            ):
                raise ValueError("invalid playing handle values")
        except (TypeError, ValueError) as exc:
            if isinstance(exc, RuntimePlayingHandleError):
                raise
            raise RuntimePlayingHandleError(
                "PLAYING_HANDLE_STORE_CORRUPT",
                "Playing handle record values are invalid.",
            ) from exc
        return RuntimePlayingHandleRecord(
            handle=handle,
            playing_id=playing_id,
            event_id=payload["event_id"],
            game_object_id=game_object_id,
            context=context,
            source_transaction_id=payload["source_transaction_id"],
            source_artifact_hash=payload["source_artifact_hash"],
            active=payload["active"],
            record_sha256=seal,
        )

    @staticmethod
    def _ensure_directory(path: Path) -> None:
        if os.path.lexists(path):
            try:
                metadata = path.lstat()
            except OSError as exc:
                raise RuntimePlayingHandleError(
                    "PLAYING_HANDLE_STORE_CORRUPT",
                    "Playing handle state path cannot be inspected safely.",
                ) from exc
            if path_is_link_or_reparse(path, metadata=metadata) or not stat.S_ISDIR(
                metadata.st_mode
            ):
                raise RuntimePlayingHandleError(
                    "PLAYING_HANDLE_STORE_CORRUPT",
                    "Playing handle state path is not a real directory.",
                )
            return
        try:
            path.mkdir(mode=0o700)
        except OSError as exc:
            raise RuntimePlayingHandleError(
                "PLAYING_HANDLE_STORE_CORRUPT",
                "Playing handle state path cannot be created safely.",
            ) from exc

    @staticmethod
    def _write_new(path: Path, payload: Mapping[str, object]) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(canonical_json_bytes(payload) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _replace(path: Path, payload: Mapping[str, object]) -> None:
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        RuntimePlayingHandleStore._write_new(temporary, payload)
        os.replace(temporary, path)


def validate_runtime_playing_handle(value: object) -> str:
    if not isinstance(value, str) or not _HANDLE.fullmatch(value):
        raise RuntimePlayingHandleError(
            "PLAYING_HANDLE_INVALID",
            "Playing handle must be copied exactly from a Gateway result.",
        )
    return value


__all__ = [
    "RUNTIME_PLAYING_HANDLE_CONTRACT",
    "RuntimePlayingHandleError",
    "RuntimePlayingHandleRecord",
    "RuntimePlayingHandleStore",
    "validate_runtime_playing_handle",
]
