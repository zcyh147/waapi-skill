"""Durable opaque handles for Gateway-registered SoundEngine game objects."""

from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path

from .canonical import canonical_json_bytes, canonical_sha256


RUNTIME_GAME_OBJECT_HANDLE_CONTRACT = (
    "waapi-skill.soundengine-game-object-handle/v1"
)
_HANDLE = re.compile(r"^goh1-[0-9a-f]{32}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


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
        self.records = Path(state_dir) / "soundengine-game-object-handles-v1" / "records"

    def issue(
        self,
        *,
        game_object_id: int,
        game_object_name: str,
        context: RuntimeGameObjectContext,
        source_transaction_id: str,
        source_artifact_hash: str,
    ) -> RuntimeGameObjectHandleRecord:
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
        self.records.mkdir(parents=True, exist_ok=True)
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
            temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
            try:
                with temporary.open("xb") as stream:
                    stream.write(canonical_json_bytes(record.as_dict()))
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
        validated = validate_runtime_game_object_handle(handle)
        path = self.records / f"{validated}.json"
        if not path.is_file() or path.is_symlink():
            raise RuntimeGameObjectHandleError(
                "GAME_OBJECT_HANDLE_NOT_AVAILABLE",
                "Game object handle is unavailable or already retired.",
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            record = self._record_from_payload(payload)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise RuntimeGameObjectHandleError(
                "GAME_OBJECT_HANDLE_INVALID",
                "Stored game object handle is invalid.",
            ) from exc
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
        matches = [
            record
            for record in self._active_records()
            if record.game_object_id == game_object_id and record.context == context
        ]
        for record in matches:
            (self.records / f"{record.handle}.json").unlink(missing_ok=True)
        return tuple(record.handle for record in matches)

    def _active_records(self) -> list[RuntimeGameObjectHandleRecord]:
        if not self.records.is_dir():
            return []
        records: list[RuntimeGameObjectHandleRecord] = []
        for path in sorted(self.records.glob("goh1-*.json")):
            if path.is_symlink() or not path.is_file():
                raise RuntimeGameObjectHandleError(
                    "GAME_OBJECT_HANDLE_INVALID",
                    "Game object handle store contains an invalid record path.",
                )
            try:
                records.append(
                    self._record_from_payload(
                        json.loads(path.read_text(encoding="utf-8"))
                    )
                )
            except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                raise RuntimeGameObjectHandleError(
                    "GAME_OBJECT_HANDLE_INVALID",
                    "Game object handle store contains an invalid record.",
                ) from exc
        return records

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
