"""Durable opaque handles for Gateway-registered SoundEngine game objects."""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
from dataclasses import asdict, dataclass
from pathlib import Path

from .canonical import canonical_json_bytes, canonical_sha256
from .filesystem_security import path_is_link_or_reparse


RUNTIME_GAME_OBJECT_HANDLE_CONTRACT = (
    "waapi-skill.soundengine-game-object-handle/v1"
)
_HANDLE = re.compile(r"^goh1-[0-9a-f]{32}$")
_RECORD_FILE = re.compile(r"^goh1-[0-9a-f]{32}\.json$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_RECORD_BYTES = 16 * 1024
_MAX_RECORDS = 1024


class RuntimeGameObjectHandleError(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        self.error_code = error_code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class RuntimeGameObjectContext:
    endpoint_url: str
    project_id: str
    project_path: str
    wwise_version: str
    wwise_build: str

    def binding_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RuntimeGameObjectHandleRecord:
    handle: str
    game_object_id: int
    game_object_name: str
    context: RuntimeGameObjectContext
    source_transaction_id: str
    source_artifact_hash: str
    binding_digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "contract": RUNTIME_GAME_OBJECT_HANDLE_CONTRACT,
            "handle": self.handle,
            "game_object_id": self.game_object_id,
            "game_object_name": self.game_object_name,
            "context": self.context.binding_dict(),
            "source_transaction_id": self.source_transaction_id,
            "source_artifact_hash": self.source_artifact_hash,
            "binding_digest": self.binding_digest,
        }


class RuntimeGameObjectHandleStore:
    def __init__(self, state_dir: Path) -> None:
        if not isinstance(state_dir, Path):
            raise TypeError("state_dir must be a pathlib.Path")
        self.state_dir = state_dir
        self.root = state_dir / "soundengine-game-object-handles-v1"
        self.records = self.root / "records"
        self.epochs = self.root / "epochs"
        self._ensure_storage_hierarchy()

    def issue(
        self,
        *,
        game_object_id: int,
        game_object_name: str,
        context: RuntimeGameObjectContext,
        source_transaction_id: str,
        source_artifact_hash: str,
        expected_registration_epoch: int | None = None,
    ) -> RuntimeGameObjectHandleRecord:
        if expected_registration_epoch is not None and (
            isinstance(expected_registration_epoch, bool)
            or not isinstance(expected_registration_epoch, int)
            or expected_registration_epoch != self.registration_epoch(context=context)
        ):
            raise RuntimeGameObjectHandleError(
                "GAME_OBJECT_REGISTRATION_RETIRED",
                "A later unregister-all consumed this pending registration; verification cannot republish it.",
            )
        if (
            isinstance(game_object_id, bool)
            or not isinstance(game_object_id, int)
            or not 0 <= game_object_id <= 0xFFFFFFFFFFFFFFDF
        ):
            raise RuntimeGameObjectHandleError(
                "GAME_OBJECT_HANDLE_INVALID",
                "SoundEngine game object ID is outside the reflected range.",
            )
        if (
            not isinstance(game_object_name, str)
            or not game_object_name
            or "\x00" in game_object_name
            or len(game_object_name.encode("utf-8")) > 512
        ):
            raise RuntimeGameObjectHandleError(
                "GAME_OBJECT_HANDLE_INVALID",
                "SoundEngine game object name is invalid.",
            )
        if not isinstance(source_artifact_hash, str) or not _SHA256.fullmatch(
            source_artifact_hash
        ):
            raise RuntimeGameObjectHandleError(
                "GAME_OBJECT_HANDLE_INVALID",
                "Source artifact hash is invalid.",
            )
        if (
            not isinstance(source_transaction_id, str)
            or not source_transaction_id
            or len(source_transaction_id.encode("utf-8")) > 128
        ):
            raise RuntimeGameObjectHandleError(
                "GAME_OBJECT_HANDLE_INVALID",
                "Source transaction identity is invalid.",
            )
        self._ensure_storage_hierarchy()
        if len(self._record_paths()) >= _MAX_RECORDS:
            raise RuntimeGameObjectHandleError(
                "GAME_OBJECT_HANDLE_STORE_LIMIT",
                "Game object handle store reached its fixed record ceiling.",
            )
        for _ in range(8):
            handle = f"goh1-{secrets.token_hex(16)}"
            path = self.records / f"{handle}.json"
            if path.exists():
                continue
            binding = {
                "game_object_id": game_object_id,
                "game_object_name": game_object_name,
                "context": context.binding_dict(),
                "source_transaction_id": source_transaction_id,
                "source_artifact_hash": source_artifact_hash,
            }
            record = RuntimeGameObjectHandleRecord(
                handle=handle,
                game_object_id=game_object_id,
                game_object_name=game_object_name,
                context=context,
                source_transaction_id=source_transaction_id,
                source_artifact_hash=source_artifact_hash,
                binding_digest=canonical_sha256(binding),
            )
            encoded = canonical_json_bytes(record.as_dict())
            if len(encoded) > _MAX_RECORD_BYTES:
                raise RuntimeGameObjectHandleError(
                    "GAME_OBJECT_HANDLE_INVALID",
                    "Game object handle record exceeds its fixed byte ceiling.",
                )
            temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
            try:
                with temporary.open("xb") as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
            return record
        raise RuntimeGameObjectHandleError(
            "GAME_OBJECT_HANDLE_PERSISTENCE_FAILED",
            "Could not allocate a unique SoundEngine game object handle.",
        )

    def resolve(
        self,
        handle: object,
        *,
        context: RuntimeGameObjectContext,
    ) -> RuntimeGameObjectHandleRecord:
        self._ensure_storage_hierarchy()
        validated = validate_runtime_game_object_handle(handle)
        path = self.records / f"{validated}.json"
        record = self._load(path)
        if record.context != context:
            raise RuntimeGameObjectHandleError(
                "GAME_OBJECT_HANDLE_CONTEXT_DRIFT",
                "Game object handle belongs to a different endpoint, project, or Wwise build.",
            )
        return record

    def resolve_native_id(
        self,
        game_object_id: int,
        *,
        context: RuntimeGameObjectContext,
    ) -> RuntimeGameObjectHandleRecord:
        self._ensure_storage_hierarchy()
        matches = [
            record
            for record in self._active_records()
            if record.game_object_id == game_object_id and record.context == context
        ]
        if len(matches) != 1:
            raise RuntimeGameObjectHandleError(
                "GAME_OBJECT_HANDLE_NOT_AVAILABLE",
                "Native game object ID does not resolve to one active Gateway handle.",
            )
        return matches[0]

    def retire_native_id(
        self,
        game_object_id: int,
        *,
        context: RuntimeGameObjectContext,
    ) -> tuple[str, ...]:
        self._ensure_storage_hierarchy()
        matches = [
            record
            for record in self._active_records()
            if record.game_object_id == game_object_id and record.context == context
        ]
        for record in matches:
            (self.records / f"{record.handle}.json").unlink(missing_ok=True)
        return tuple(record.handle for record in matches)

    def retire_all(self, *, context: RuntimeGameObjectContext) -> tuple[str, ...]:
        """Revoke registrations only in the exact live project/build context."""
        matches = [record for record in self._active_records() if record.context == context]
        epoch = self.registration_epoch(context=context, create=True)
        if epoch >= 0x7FFFFFFFFFFFFFFF:
            raise RuntimeGameObjectHandleError("GAME_OBJECT_HANDLE_STORE_LIMIT", "Registration epoch reached its fixed ceiling.")
        self._write_epoch(context=context, epoch=epoch + 1)
        for record in matches:
            (self.records / f"{record.handle}.json").unlink(missing_ok=True)
        return tuple(record.handle for record in matches)

    def registration_epoch(self, *, context: RuntimeGameObjectContext, create: bool = False) -> int:
        """Read the execution-order epoch for pending registrations in one context."""
        self._ensure_storage_hierarchy()
        path = self.epochs / (canonical_sha256(context.binding_dict()) + ".json")
        if not os.path.lexists(path):
            if not create:
                raise RuntimeGameObjectHandleError("GAME_OBJECT_REGISTRATION_EVIDENCE_MISSING", "Registration execution epoch is unavailable.")
            if sum(1 for _ in self.epochs.iterdir()) >= _MAX_RECORDS:
                raise RuntimeGameObjectHandleError("GAME_OBJECT_HANDLE_STORE_LIMIT", "Registration context store reached its fixed ceiling.")
            self._write_epoch(context=context, epoch=0)
            return 0
        try:
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or path_is_link_or_reparse(path, metadata=metadata) or metadata.st_size > _MAX_RECORD_BYTES:
                raise ValueError("Registration epoch is not a bounded regular file.")
            data = path.read_bytes()
            if len(data) > _MAX_RECORD_BYTES:
                raise ValueError("Registration epoch grew beyond its byte ceiling.")
            payload = json.loads(data)
            if not isinstance(payload, dict) or set(payload) != {"contract", "context", "epoch"} or payload["contract"] != "waapi-skill.soundengine-registration-epoch/v1" or payload["context"] != context.binding_dict():
                raise ValueError("Registration epoch context is invalid.")
            epoch = payload["epoch"]
            if isinstance(epoch, bool) or not isinstance(epoch, int) or not 0 <= epoch <= 0x7FFFFFFFFFFFFFFF:
                raise ValueError("Registration epoch is invalid.")
            return epoch
        except (OSError, ValueError, UnicodeError) as exc:
            raise RuntimeGameObjectHandleError("GAME_OBJECT_HANDLE_STORE_CORRUPT", "Registration epoch cannot be read safely.") from exc

    def _write_epoch(self, *, context: RuntimeGameObjectContext, epoch: int) -> None:
        from .transactions import _atomic_write_json

        path = self.epochs / (canonical_sha256(context.binding_dict()) + ".json")
        _atomic_write_json(path, {"contract": "waapi-skill.soundengine-registration-epoch/v1", "context": context.binding_dict(), "epoch": epoch})

    def _active_records(self) -> list[RuntimeGameObjectHandleRecord]:
        return [self._load(path) for path in self._record_paths()]

    def _record_paths(self) -> tuple[Path, ...]:
        self._ensure_storage_hierarchy()
        paths: list[Path] = []
        try:
            with os.scandir(self.records) as entries:
                for entry in entries:
                    if len(paths) >= _MAX_RECORDS:
                        raise RuntimeGameObjectHandleError(
                            "GAME_OBJECT_HANDLE_STORE_LIMIT",
                            "Game object handle store exceeds its fixed record ceiling.",
                        )
                    if (
                        _RECORD_FILE.fullmatch(entry.name) is None
                        or not entry.is_file(follow_symlinks=False)
                    ):
                        raise RuntimeGameObjectHandleError(
                            "GAME_OBJECT_HANDLE_STORE_CORRUPT",
                            "Game object handle store contains an invalid record path.",
                        )
                    paths.append(Path(entry.path))
        except OSError as exc:
            raise RuntimeGameObjectHandleError(
                "GAME_OBJECT_HANDLE_STORE_CORRUPT",
                "Game object handle store cannot be enumerated safely.",
            ) from exc
        return tuple(sorted(paths))

    def _load(self, path: Path) -> RuntimeGameObjectHandleRecord:
        self._ensure_storage_hierarchy()
        if not os.path.lexists(path):
            raise RuntimeGameObjectHandleError(
                "GAME_OBJECT_HANDLE_NOT_AVAILABLE",
                "Game object handle is unavailable or already retired.",
            )
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise RuntimeGameObjectHandleError(
                "GAME_OBJECT_HANDLE_STORE_CORRUPT",
                "Stored game object handle cannot be inspected safely.",
            ) from exc
        if (
            not stat.S_ISREG(metadata.st_mode)
            or path_is_link_or_reparse(path, metadata=metadata)
            or metadata.st_size > _MAX_RECORD_BYTES
        ):
            raise RuntimeGameObjectHandleError(
                "GAME_OBJECT_HANDLE_STORE_CORRUPT",
                "Stored game object handle is not one bounded regular file.",
            )
        try:
            data = path.read_bytes()
            if len(data) > _MAX_RECORD_BYTES:
                raise ValueError("record grew beyond its fixed byte ceiling")
            return self._record_from_payload(json.loads(data))
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise RuntimeGameObjectHandleError(
                "GAME_OBJECT_HANDLE_STORE_CORRUPT",
                "Stored game object handle is invalid.",
            ) from exc

    def _ensure_storage_hierarchy(self) -> None:
        for path in (self.state_dir, self.root, self.records, self.epochs):
            self._ensure_directory(path)

    @staticmethod
    def _ensure_directory(path: Path) -> None:
        if os.path.lexists(path):
            try:
                metadata = path.lstat()
            except OSError as exc:
                raise RuntimeGameObjectHandleError(
                    "GAME_OBJECT_HANDLE_STORE_CORRUPT",
                    "Game object handle state path cannot be inspected safely.",
                ) from exc
            if path_is_link_or_reparse(path, metadata=metadata) or not stat.S_ISDIR(
                metadata.st_mode
            ):
                raise RuntimeGameObjectHandleError(
                    "GAME_OBJECT_HANDLE_STORE_CORRUPT",
                    "Game object handle state path is not a real directory.",
                )
            return
        try:
            path.mkdir(mode=0o700)
        except OSError as exc:
            raise RuntimeGameObjectHandleError(
                "GAME_OBJECT_HANDLE_STORE_CORRUPT",
                "Game object handle state path cannot be created safely.",
            ) from exc

    @staticmethod
    def _record_from_payload(payload: object) -> RuntimeGameObjectHandleRecord:
        if not isinstance(payload, dict) or set(payload) != {
            "contract",
            "handle",
            "game_object_id",
            "game_object_name",
            "context",
            "source_transaction_id",
            "source_artifact_hash",
            "binding_digest",
        }:
            raise ValueError("game object handle record fields are invalid")
        if payload.get("contract") != RUNTIME_GAME_OBJECT_HANDLE_CONTRACT:
            raise ValueError("game object handle record contract is invalid")
        handle = validate_runtime_game_object_handle(payload.get("handle"))
        game_object_id = payload.get("game_object_id")
        game_object_name = payload.get("game_object_name")
        context_payload = payload.get("context")
        if (
            isinstance(game_object_id, bool)
            or not isinstance(game_object_id, int)
            or not 0 <= game_object_id <= 0xFFFFFFFFFFFFFFDF
            or not isinstance(game_object_name, str)
            or not game_object_name
            or not isinstance(context_payload, dict)
            or set(context_payload)
            != {
                "endpoint_url",
                "project_id",
                "project_path",
                "wwise_version",
                "wwise_build",
            }
        ):
            raise ValueError("game object handle binding is invalid")
        context = RuntimeGameObjectContext(**context_payload)
        source_transaction_id = payload.get("source_transaction_id")
        source_artifact_hash = payload.get("source_artifact_hash")
        binding_digest = payload.get("binding_digest")
        if (
            not isinstance(source_transaction_id, str)
            or not source_transaction_id
            or not isinstance(source_artifact_hash, str)
            or not _SHA256.fullmatch(source_artifact_hash)
            or not isinstance(binding_digest, str)
            or not _SHA256.fullmatch(binding_digest)
        ):
            raise ValueError("game object handle provenance is invalid")
        binding = {
            "game_object_id": game_object_id,
            "game_object_name": game_object_name,
            "context": context.binding_dict(),
            "source_transaction_id": source_transaction_id,
            "source_artifact_hash": source_artifact_hash,
        }
        if canonical_sha256(binding) != binding_digest:
            raise ValueError("game object handle digest does not match")
        return RuntimeGameObjectHandleRecord(
            handle=handle,
            game_object_id=game_object_id,
            game_object_name=game_object_name,
            context=context,
            source_transaction_id=source_transaction_id,
            source_artifact_hash=source_artifact_hash,
            binding_digest=binding_digest,
        )


def validate_runtime_game_object_handle(value: object) -> str:
    if not isinstance(value, str) or not _HANDLE.fullmatch(value):
        raise RuntimeGameObjectHandleError(
            "GAME_OBJECT_HANDLE_INVALID",
            "Game object handle must be copied exactly from a Gateway result.",
        )
    return value


__all__ = [
    "RUNTIME_GAME_OBJECT_HANDLE_CONTRACT",
    "RuntimeGameObjectContext",
    "RuntimeGameObjectHandleError",
    "RuntimeGameObjectHandleRecord",
    "RuntimeGameObjectHandleStore",
    "validate_runtime_game_object_handle",
]
