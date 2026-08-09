"""Task-capability-bound, WAAPI-independent operation composition drafts.

An Operation Draft is mutable composition state, not an immutable transaction
Preview.  This module deliberately does not import a WAAPI client or reuse the
transaction state machine.  Access is authorized by a high-entropy capability
issued with the draft; caller-authored task identifiers are not an authority.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from .canonical import canonical_json_bytes, canonical_sha256


OPERATION_DRAFT_CONTRACT = "waapi-skill.operation-draft/v1"
OPERATION_DRAFT_AUTHORITY_CONTRACT = "waapi-skill.operation-draft-authority/v1"
OPERATION_DRAFT_SCHEMA_VERSION = 1
_DRAFT_ID_PATTERN = re.compile(r"^od1-[0-9a-f]{32}$")
_TASK_AUTHORITY_PATTERN = re.compile(r"^da1-[0-9a-f]{40}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class OperationDraftError(RuntimeError):
    """Base class for durable Operation Draft failures."""

    error_code = "OPERATION_DRAFT_ERROR"

    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = dict(details or {})

    def as_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": str(self),
            "details": dict(self.details),
        }


class OperationDraftNotAvailable(OperationDraftError):
    """The id/capability pair does not authorize one visible draft."""

    error_code = "OPERATION_DRAFT_NOT_AVAILABLE"


class OperationDraftRevisionConflict(OperationDraftError):
    """The caller did not bind its edit to the current durable revision."""

    error_code = "OPERATION_DRAFT_REVISION_CONFLICT"


class OperationDraftInvalidTransition(OperationDraftError):
    """The requested lifecycle transition is not available from this state."""

    error_code = "OPERATION_DRAFT_INVALID_TRANSITION"


class OperationDraftState(str, Enum):
    """Closed states in the initial editable-draft lifecycle."""

    EDITABLE = "editable"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class OperationDraftRecord:
    draft_id: str
    state: OperationDraftState
    revision: int
    operation: str
    version: str
    schema_digest: str
    authority_digest: str
    created_at: str
    updated_at: str

    def as_durable_dict(self) -> dict[str, Any]:
        return {
            "authority_digest": self.authority_digest,
            "contract": OPERATION_DRAFT_CONTRACT,
            "created_at": self.created_at,
            "draft_id": self.draft_id,
            "operation": self.operation,
            "revision": self.revision,
            "schema_digest": self.schema_digest,
            "schema_version": OPERATION_DRAFT_SCHEMA_VERSION,
            "state": self.state.value,
            "updated_at": self.updated_at,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class OperationDraftStart:
    record: OperationDraftRecord
    task_authority: str

    @property
    def draft_id(self) -> str:
        return self.record.draft_id


class OperationDraftStore:
    """Persist task-capability-bound drafts below one external state root."""

    def __init__(self, state_dir: Path) -> None:
        if not isinstance(state_dir, Path):
            raise TypeError("state_dir must be a pathlib.Path")
        self.state_dir = state_dir
        self.records_dir = state_dir / "operation-drafts-v1" / "records"
        self.records_dir.mkdir(mode=0o700, parents=True, exist_ok=True)

    def start(
        self,
        *,
        operation: str,
        version: str,
        schema_digest: str,
        now: datetime | None = None,
    ) -> OperationDraftStart:
        _require_binding(operation, version, schema_digest)
        created_at = _timestamp(now)
        for _attempt in range(16):
            draft_id = f"od1-{secrets.token_hex(16)}"
            task_authority = f"da1-{secrets.token_hex(20)}"
            record = OperationDraftRecord(
                draft_id=draft_id,
                state=OperationDraftState.EDITABLE,
                revision=1,
                operation=operation,
                version=version,
                schema_digest=schema_digest,
                authority_digest=_task_authority_digest(task_authority),
                created_at=created_at,
                updated_at=created_at,
            )
            try:
                _write_new(self._record_path(draft_id), record.as_durable_dict())
            except FileExistsError:
                continue
            return OperationDraftStart(record=record, task_authority=task_authority)
        raise OperationDraftError("Could not allocate a unique Operation Draft id.")

    def inspect(
        self,
        draft_id: str,
        *,
        task_authority: str,
    ) -> OperationDraftRecord:
        record = self._load_available(draft_id)
        if not _valid_task_authority(task_authority) or not hmac.compare_digest(
            record.authority_digest,
            _task_authority_digest(task_authority),
        ):
            raise _not_available()
        return record

    def cancel(
        self,
        draft_id: str,
        *,
        task_authority: str,
        expected_revision: int,
        now: datetime | None = None,
    ) -> OperationDraftRecord:
        record = self.inspect(draft_id, task_authority=task_authority)
        if record.state is not OperationDraftState.EDITABLE:
            raise OperationDraftInvalidTransition(
                "Only an editable Operation Draft can be cancelled.",
                details={"state": record.state.value},
            )
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 1
            or expected_revision != record.revision
        ):
            raise OperationDraftRevisionConflict(
                "Operation Draft revision no longer matches the requested edit.",
                details={
                    "expected_revision": expected_revision,
                    "actual_revision": record.revision,
                },
            )
        cancelled = OperationDraftRecord(
            draft_id=record.draft_id,
            state=OperationDraftState.CANCELLED,
            revision=record.revision + 1,
            operation=record.operation,
            version=record.version,
            schema_digest=record.schema_digest,
            authority_digest=record.authority_digest,
            created_at=record.created_at,
            updated_at=_timestamp(now),
        )
        _replace(self._record_path(draft_id), cancelled.as_durable_dict())
        return cancelled

    def _load_available(self, draft_id: str) -> OperationDraftRecord:
        if not isinstance(draft_id, str) or not _DRAFT_ID_PATTERN.fullmatch(draft_id):
            raise _not_available()
        try:
            payload = json.loads(self._record_path(draft_id).read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
            raise _not_available() from None
        try:
            return _record_from_mapping(payload)
        except (KeyError, TypeError, ValueError):
            raise _not_available() from None

    def _record_path(self, draft_id: str) -> Path:
        return self.records_dir / f"{draft_id}.json"


def _not_available() -> OperationDraftNotAvailable:
    return OperationDraftNotAvailable(
        "No Operation Draft is available for that id and task authority."
    )


def _task_authority_digest(task_authority: str) -> str:
    return canonical_sha256(
        {
            "contract": OPERATION_DRAFT_AUTHORITY_CONTRACT,
            "task_authority": task_authority,
        }
    )


def _valid_task_authority(task_authority: Any) -> bool:
    return isinstance(task_authority, str) and bool(
        _TASK_AUTHORITY_PATTERN.fullmatch(task_authority)
    )


def _require_binding(operation: str, version: str, schema_digest: str) -> None:
    if not isinstance(operation, str) or not operation:
        raise ValueError("operation must be a non-empty string")
    if not isinstance(version, str) or not version:
        raise ValueError("version must be a non-empty string")
    if not isinstance(schema_digest, str) or not _SHA256_PATTERN.fullmatch(schema_digest):
        raise ValueError("schema_digest must be a lowercase SHA-256 digest")


def _record_from_mapping(payload: Any) -> OperationDraftRecord:
    if not isinstance(payload, Mapping):
        raise TypeError("draft record must be an object")
    expected = {
        "authority_digest",
        "contract",
        "created_at",
        "draft_id",
        "operation",
        "revision",
        "schema_digest",
        "schema_version",
        "state",
        "updated_at",
        "version",
    }
    if set(payload) != expected:
        raise ValueError("draft record fields are invalid")
    if payload["contract"] != OPERATION_DRAFT_CONTRACT:
        raise ValueError("draft contract is invalid")
    if payload["schema_version"] != OPERATION_DRAFT_SCHEMA_VERSION:
        raise ValueError("draft schema version is invalid")
    draft_id = payload["draft_id"]
    authority_digest = payload["authority_digest"]
    schema_digest = payload["schema_digest"]
    revision = payload["revision"]
    if not isinstance(draft_id, str) or not _DRAFT_ID_PATTERN.fullmatch(draft_id):
        raise ValueError("draft id is invalid")
    if not isinstance(authority_digest, str) or not _SHA256_PATTERN.fullmatch(authority_digest):
        raise ValueError("authority digest is invalid")
    if not isinstance(schema_digest, str) or not _SHA256_PATTERN.fullmatch(schema_digest):
        raise ValueError("schema digest is invalid")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("revision is invalid")
    for field in ("operation", "version", "created_at", "updated_at"):
        if not isinstance(payload[field], str) or not payload[field]:
            raise ValueError(f"{field} is invalid")
    return OperationDraftRecord(
        draft_id=draft_id,
        state=OperationDraftState(payload["state"]),
        revision=revision,
        operation=payload["operation"],
        version=payload["version"],
        schema_digest=schema_digest,
        authority_digest=authority_digest,
        created_at=payload["created_at"],
        updated_at=payload["updated_at"],
    )


def _timestamp(now: datetime | None) -> str:
    current = datetime.now(timezone.utc) if now is None else now
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _write_new(path: Path, payload: Mapping[str, Any]) -> None:
    data = canonical_json_bytes(payload)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _replace(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        _write_new(temporary, payload)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


__all__ = [
    "OPERATION_DRAFT_CONTRACT",
    "OperationDraftError",
    "OperationDraftInvalidTransition",
    "OperationDraftNotAvailable",
    "OperationDraftRecord",
    "OperationDraftRevisionConflict",
    "OperationDraftStart",
    "OperationDraftState",
    "OperationDraftStore",
]
