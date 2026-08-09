"""Task-capability-bound, WAAPI-independent operation composition drafts.

An Operation Draft is mutable composition state, not an immutable transaction
Preview.  This module deliberately does not import a WAAPI client or reuse the
transaction state machine.  Access is authorized by a high-entropy capability
issued with the draft; caller-authored task identifiers are not an authority.
"""

from __future__ import annotations

import errno
import hmac
import json
import os
import re
import secrets
import stat
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from .canonical import canonical_json_bytes, canonical_sha256
from .filesystem_security import path_is_link_or_reparse

try:  # pragma: no branch - absence is exercised through the backend seam.
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - exercised on native Windows.
    _fcntl = None

try:  # pragma: no branch - absence is exercised through the backend seam.
    import msvcrt as _msvcrt
except ImportError:  # pragma: no cover - exercised on POSIX.
    _msvcrt = None


OPERATION_DRAFT_CONTRACT = "waapi-skill.operation-draft/v1"
OPERATION_DRAFT_AUTHORITY_CONTRACT = "waapi-skill.operation-draft-authority/v1"
OPERATION_DRAFT_AUDIT_EVENT_CONTRACT = (
    "waapi-skill.operation-draft-audit-event/v1"
)
OPERATION_DRAFT_RECORD_DIGEST_CONTRACT = (
    "waapi-skill.operation-draft-record-digest/v1"
)
OPERATION_DRAFT_SCHEMA_VERSION = 1
DEFAULT_OPERATION_DRAFT_TTL_SECONDS = 24 * 60 * 60
DEFAULT_OPERATION_DRAFT_TERMINAL_RETENTION_SECONDS = 24 * 60 * 60
DEFAULT_OPERATION_DRAFT_STALE_TEMP_SECONDS = 5 * 60
DEFAULT_OPERATION_DRAFT_LOCK_TIMEOUT_SECONDS = 5
MAX_ACTIVE_OPERATION_DRAFTS = 32
MAX_MANAGED_OPERATION_DRAFT_ENTRIES = 128
MAX_OPERATION_DRAFT_ACTIONS = 16_384
MAX_OPERATION_DRAFT_ROWS = 128
MAX_OPERATION_DRAFT_FIELDS_PER_ROW = 64
MAX_OPERATION_DRAFT_RECORD_BYTES = 1024 * 1024
MAX_OPERATION_DRAFT_EVIDENCE_BYTES = 256 * 1024
MAX_OPERATION_DRAFT_RESULT_BYTES = 256 * 1024
_DRAFT_ID_PATTERN = re.compile(r"^od1-[0-9a-f]{32}$")
_TASK_AUTHORITY_PATTERN = re.compile(r"^da1-[0-9a-f]{40}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP_PATTERN = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$"
)
_AUDIT_EVENT_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_RECORD_NAME_PATTERN = re.compile(r"^(od1-[0-9a-f]{32})\.json$")
_LOCK_NAME_PATTERN = re.compile(r"^(od1-[0-9a-f]{32})\.lock$")
_TEMP_NAME_PATTERN = re.compile(
    r"^\.od1-[0-9a-f]{32}\.json\.[0-9a-f]{16}\.tmp$"
)
_LOCK_REGION_BYTES = 1
_WINDOWS_LOCK_RETRY_SECONDS = 0.05
_WINDOWS_LOCK_VIOLATION = 33


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


class OperationDraftExpired(OperationDraftError):
    """The authorized draft reached its fixed lifetime boundary."""

    error_code = "OPERATION_DRAFT_EXPIRED"


class OperationDraftLockUnavailable(OperationDraftError):
    """No supported cross-process lock can protect one draft revision."""

    error_code = "OPERATION_DRAFT_LOCK_UNAVAILABLE"


class OperationDraftLimitExceeded(OperationDraftError):
    """One fixed Draft Store resource ceiling would be exceeded."""

    error_code = "OPERATION_DRAFT_LIMIT_EXCEEDED"


class OperationDraftStorageCorruption(OperationDraftError):
    """Managed Draft Store state cannot be trusted or safely classified."""

    error_code = "OPERATION_DRAFT_STORAGE_CORRUPTION"


class _OperationDraftDirectoryIdentityChanged(OperationDraftStorageCorruption):
    """One directory selected at Store initialization was substituted."""


class OperationDraftInvalidTransition(OperationDraftError):
    """The requested lifecycle transition is not available from this state."""

    error_code = "OPERATION_DRAFT_INVALID_TRANSITION"


class OperationDraftState(str, Enum):
    """Closed states in the initial editable-draft lifecycle."""

    EDITABLE = "editable"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class OperationDraftLimits:
    """Fixed, non-caller-configurable resource policy for every Draft."""

    active_drafts: int = MAX_ACTIVE_OPERATION_DRAFTS
    managed_entries: int = MAX_MANAGED_OPERATION_DRAFT_ENTRIES
    actions: int = MAX_OPERATION_DRAFT_ACTIONS
    rows: int = MAX_OPERATION_DRAFT_ROWS
    fields_per_row: int = MAX_OPERATION_DRAFT_FIELDS_PER_ROW
    record_bytes: int = MAX_OPERATION_DRAFT_RECORD_BYTES
    evidence_bytes: int = MAX_OPERATION_DRAFT_EVIDENCE_BYTES
    result_bytes: int = MAX_OPERATION_DRAFT_RESULT_BYTES
    ttl_seconds: int = DEFAULT_OPERATION_DRAFT_TTL_SECONDS
    terminal_retention_seconds: int = (
        DEFAULT_OPERATION_DRAFT_TERMINAL_RETENTION_SECONDS
    )
    stale_temp_seconds: int = DEFAULT_OPERATION_DRAFT_STALE_TEMP_SECONDS
    lock_timeout_seconds: int = DEFAULT_OPERATION_DRAFT_LOCK_TIMEOUT_SECONDS

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": "waapi-skill.operation-draft-limits/v1",
            "active_drafts": self.active_drafts,
            "managed_entries": self.managed_entries,
            "actions": self.actions,
            "rows": self.rows,
            "fields_per_row": self.fields_per_row,
            "record_bytes": self.record_bytes,
            "evidence_bytes": self.evidence_bytes,
            "result_bytes": self.result_bytes,
            "ttl_seconds": self.ttl_seconds,
            "terminal_retention_seconds": self.terminal_retention_seconds,
            "stale_temp_seconds": self.stale_temp_seconds,
            "lock_timeout_seconds": self.lock_timeout_seconds,
        }


OPERATION_DRAFT_LIMITS = OperationDraftLimits()
OPERATION_DRAFT_LIMITS_DIGEST = canonical_sha256(OPERATION_DRAFT_LIMITS.as_dict())


class _PosixDraftLockBackend:
    def __init__(self, module: Any) -> None:
        self._module = module

    def acquire(self, handle: Any) -> None:
        deadline = time.monotonic() + DEFAULT_OPERATION_DRAFT_LOCK_TIMEOUT_SECONDS
        while True:
            try:
                self._module.flock(
                    handle.fileno(),
                    self._module.LOCK_EX | self._module.LOCK_NB,
                )
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                    raise OperationDraftLockUnavailable(
                        "Operation Draft lock could not be acquired with fcntl.flock."
                    ) from exc
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise OperationDraftLockUnavailable(
                        "Operation Draft lock acquisition timed out.",
                        details={
                            "timeout_seconds": DEFAULT_OPERATION_DRAFT_LOCK_TIMEOUT_SECONDS
                        },
                    ) from exc
                time.sleep(min(_WINDOWS_LOCK_RETRY_SECONDS, remaining))
                continue
            return

    def release(self, handle: Any) -> None:
        try:
            self._module.flock(handle.fileno(), self._module.LOCK_UN)
        except OSError as exc:
            raise OperationDraftLockUnavailable(
                "Operation Draft lock could not be released with fcntl.flock."
            ) from exc


class _WindowsDraftLockBackend:
    def __init__(self, module: Any) -> None:
        self._module = module

    @staticmethod
    def _seek(handle: Any) -> None:
        try:
            handle.seek(0, os.SEEK_SET)
        except OSError as exc:
            raise OperationDraftLockUnavailable(
                "Operation Draft lock region could not be selected."
            ) from exc

    def acquire(self, handle: Any) -> None:
        deadline = time.monotonic() + DEFAULT_OPERATION_DRAFT_LOCK_TIMEOUT_SECONDS
        while True:
            self._seek(handle)
            try:
                self._module.locking(
                    handle.fileno(),
                    self._module.LK_NBLCK,
                    _LOCK_REGION_BYTES,
                )
            except OSError as exc:
                if _is_windows_lock_contention(exc):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise OperationDraftLockUnavailable(
                            "Operation Draft lock acquisition timed out.",
                            details={
                                "timeout_seconds": DEFAULT_OPERATION_DRAFT_LOCK_TIMEOUT_SECONDS
                            },
                        ) from exc
                    time.sleep(min(_WINDOWS_LOCK_RETRY_SECONDS, remaining))
                    continue
                raise OperationDraftLockUnavailable(
                    "Operation Draft lock could not be acquired with msvcrt.locking."
                ) from exc
            return

    def release(self, handle: Any) -> None:
        self._seek(handle)
        try:
            self._module.locking(
                handle.fileno(),
                self._module.LK_UNLCK,
                _LOCK_REGION_BYTES,
            )
        except OSError as exc:
            raise OperationDraftLockUnavailable(
                "Operation Draft lock could not be released with msvcrt.locking."
            ) from exc


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
    expires_at: str
    terminal_at: str | None
    audit: tuple[Mapping[str, Any], ...]
    limits_digest: str

    def as_digest_material_dict(self) -> dict[str, Any]:
        return {
            "audit": [dict(event) for event in self.audit],
            "authority_digest": self.authority_digest,
            "contract": OPERATION_DRAFT_CONTRACT,
            "created_at": self.created_at,
            "draft_id": self.draft_id,
            "expires_at": self.expires_at,
            "limits_digest": self.limits_digest,
            "operation": self.operation,
            "revision": self.revision,
            "schema_digest": self.schema_digest,
            "schema_version": OPERATION_DRAFT_SCHEMA_VERSION,
            "state": self.state.value,
            "terminal_at": self.terminal_at,
            "updated_at": self.updated_at,
            "version": self.version,
        }

    def as_durable_dict(self) -> dict[str, Any]:
        payload = self.as_digest_material_dict()
        payload["record_digest"] = _record_digest(payload)
        return payload


@dataclass(frozen=True, slots=True)
class OperationDraftStart:
    record: OperationDraftRecord
    task_authority: str

    @property
    def draft_id(self) -> str:
        return self.record.draft_id


@dataclass(frozen=True, slots=True)
class _ManagedDirectoryIdentity:
    path: Path
    metadata: os.stat_result
    require_private: bool


@dataclass(frozen=True, slots=True)
class _RegularFileRead:
    data: bytes
    metadata: os.stat_result


@dataclass(frozen=True, slots=True)
class _LoadedOperationDraft:
    record: OperationDraftRecord
    durable_bytes: bytes
    metadata: os.stat_result


class OperationDraftStore:
    """Persist task-capability-bound drafts below one external state root."""

    def __init__(self, state_dir: Path) -> None:
        if not isinstance(state_dir, Path):
            raise TypeError("state_dir must be a pathlib.Path")
        self.state_dir = state_dir
        self.store_dir = state_dir / "operation-drafts-v1"
        self.records_dir = self.store_dir / "records"
        self.locks_dir = self.store_dir / "locks"
        _ensure_private_state_directory(self.state_dir, label="State directory")
        for directory in (self.store_dir, self.records_dir, self.locks_dir):
            _ensure_private_managed_directory(directory, label="Draft Store directory")
        self._directory_identities = _capture_managed_directory_identities(
            state_dir=self.state_dir,
            managed_directories=(self.store_dir, self.records_dir, self.locks_dir),
        )
        self._admission_lock_path = self.locks_dir / "store-admission.lock"
        self._admission_lock_identity = _ensure_admission_lock_file(
            self._admission_lock_path,
            attest_directories=self._attest_directory_identities,
        )

    def start(
        self,
        *,
        operation: str,
        version: str,
        schema_digest: str,
        now: datetime | None = None,
    ) -> OperationDraftStart:
        _require_binding(operation, version, schema_digest)
        created_datetime = _utc_datetime(now)
        created_at = _timestamp(created_datetime)
        expires_at = _timestamp(
            created_datetime
            + timedelta(seconds=DEFAULT_OPERATION_DRAFT_TTL_SECONDS)
        )
        with self._store_lock():
            active_drafts = self._collect_and_count_active(now=now)
            if active_drafts >= MAX_ACTIVE_OPERATION_DRAFTS:
                raise OperationDraftLimitExceeded(
                    "Operation Draft active-draft ceiling has been reached.",
                    details={
                        "active_drafts": active_drafts,
                        "limit": MAX_ACTIVE_OPERATION_DRAFTS,
                    },
                )
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
                    expires_at=expires_at,
                    terminal_at=None,
                    audit=(
                        _build_audit_event(
                            draft_id=draft_id,
                            sequence=1,
                            revision=1,
                            event_type="started",
                            from_state=None,
                            to_state=OperationDraftState.EDITABLE,
                            timestamp=created_at,
                            previous_event_hash="",
                        ),
                    ),
                    limits_digest=OPERATION_DRAFT_LIMITS_DIGEST,
                )
                try:
                    self._write_record(
                        self._record_path(draft_id),
                        record.as_durable_dict(),
                    )
                except FileExistsError:
                    continue
                return OperationDraftStart(
                    record=record,
                    task_authority=task_authority,
                )
        raise OperationDraftError("Could not allocate a unique Operation Draft id.")

    def inspect(
        self,
        draft_id: str,
        *,
        task_authority: str,
        now: datetime | None = None,
    ) -> OperationDraftRecord:
        if not isinstance(draft_id, str) or not _DRAFT_ID_PATTERN.fullmatch(draft_id):
            raise _not_available()
        current = _utc_datetime(now)
        with self._existing_draft_lock(draft_id):
            return self._inspect_unlocked(
                draft_id,
                task_authority=task_authority,
                now=current,
            ).record

    def _inspect_unlocked(
        self,
        draft_id: str,
        *,
        task_authority: str,
        now: datetime | None,
    ) -> _LoadedOperationDraft:
        loaded = self._load_available(draft_id)
        record = loaded.record
        if not _valid_task_authority(task_authority) or not hmac.compare_digest(
            record.authority_digest,
            _task_authority_digest(task_authority),
        ):
            raise _not_available()
        return self._require_unexpired(loaded, now=now)

    def cancel(
        self,
        draft_id: str,
        *,
        task_authority: str,
        expected_revision: int,
        now: datetime | None = None,
    ) -> OperationDraftRecord:
        if not isinstance(draft_id, str) or not _DRAFT_ID_PATTERN.fullmatch(draft_id):
            raise _not_available()
        current = _utc_datetime(now)
        with self._existing_draft_lock(draft_id):
            loaded = self._inspect_unlocked(
                draft_id,
                task_authority=task_authority,
                now=current,
            )
            record = loaded.record
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
            if record.state is not OperationDraftState.EDITABLE:
                raise OperationDraftInvalidTransition(
                    "Only an editable Operation Draft can be cancelled.",
                    details={"state": record.state.value},
                )
            cancelled_at = _timestamp(current)
            cancelled = OperationDraftRecord(
                draft_id=record.draft_id,
                state=OperationDraftState.CANCELLED,
                revision=record.revision + 1,
                operation=record.operation,
                version=record.version,
                schema_digest=record.schema_digest,
                authority_digest=record.authority_digest,
                created_at=record.created_at,
                updated_at=cancelled_at,
                expires_at=record.expires_at,
                terminal_at=cancelled_at,
                audit=(
                    *record.audit,
                    _build_audit_event(
                        draft_id=record.draft_id,
                        sequence=len(record.audit) + 1,
                        revision=record.revision + 1,
                        event_type="cancelled",
                        from_state=record.state,
                        to_state=OperationDraftState.CANCELLED,
                        timestamp=cancelled_at,
                        previous_event_hash=str(record.audit[-1]["event_hash"]),
                    ),
                ),
                limits_digest=record.limits_digest,
            )
            self._replace_record(
                self._record_path(draft_id),
                cancelled.as_durable_dict(),
                expected_previous=loaded,
            )
            return cancelled

    def _require_unexpired(
        self,
        loaded: _LoadedOperationDraft,
        *,
        now: datetime | None,
    ) -> _LoadedOperationDraft:
        record = loaded.record
        if record.state is OperationDraftState.EXPIRED:
            raise OperationDraftExpired(
                "Operation Draft expired and cannot be resumed."
            )
        if record.state is not OperationDraftState.EDITABLE:
            return loaded
        current = _utc_datetime(now)
        if current < _parse_timestamp(record.updated_at):
            raise OperationDraftStorageCorruption(
                "Operation Draft clock is before its immutable lifetime."
            )
        if current < _parse_timestamp(record.expires_at):
            return loaded
        expired = self._expired_record(record)
        self._replace_record(
            self._record_path(record.draft_id),
            expired.as_durable_dict(),
            expected_previous=loaded,
        )
        raise OperationDraftExpired("Operation Draft expired and cannot be resumed.")

    @staticmethod
    def _expired_record(record: OperationDraftRecord) -> OperationDraftRecord:
        return OperationDraftRecord(
            draft_id=record.draft_id,
            state=OperationDraftState.EXPIRED,
            revision=record.revision + 1,
            operation=record.operation,
            version=record.version,
            schema_digest=record.schema_digest,
            authority_digest=record.authority_digest,
            created_at=record.created_at,
            updated_at=record.expires_at,
            expires_at=record.expires_at,
            terminal_at=record.expires_at,
            audit=(
                *record.audit,
                _build_audit_event(
                    draft_id=record.draft_id,
                    sequence=len(record.audit) + 1,
                    revision=record.revision + 1,
                    event_type="expired",
                    from_state=record.state,
                    to_state=OperationDraftState.EXPIRED,
                    timestamp=record.expires_at,
                    previous_event_hash=str(record.audit[-1]["event_hash"]),
                ),
            ),
            limits_digest=record.limits_digest,
        )

    def _collect_and_count_active(self, *, now: datetime | None) -> int:
        current = _utc_datetime(now)
        entries = self._bounded_entries(
            self.records_dir,
            label="Operation Draft records directory",
        )
        lock_entries = self._bounded_entries(
            self.locks_dir,
            label="Operation Draft locks directory",
        )
        self._collect_orphan_locks(lock_entries)
        active = 0
        for entry in sorted(entries, key=lambda candidate: candidate.name):
            match = _RECORD_NAME_PATTERN.fullmatch(entry.name)
            if match is None:
                if _TEMP_NAME_PATTERN.fullmatch(entry.name):
                    self._collect_crash_temporary(entry, now=current)
                    continue
                raise OperationDraftStorageCorruption(
                    "Operation Draft records directory contains an unmanaged entry."
                )
            if not _lexists(entry):
                continue
            try:
                record_read = self._read_record_snapshot(entry)
                record = _parse_canonical_record_bytes(
                    record_read.data,
                    expected_draft_id=match.group(1),
                )
                loaded = _LoadedOperationDraft(
                    record=record,
                    durable_bytes=record_read.data,
                    metadata=record_read.metadata,
                )
            except (
                OSError,
                RecursionError,
                TypeError,
                UnicodeError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                raise OperationDraftStorageCorruption(
                    "Operation Draft record cannot be validated during cleanup."
                ) from exc
            if record.state is OperationDraftState.EDITABLE:
                expiry = _parse_timestamp(record.expires_at)
                if current < expiry:
                    active += 1
                    continue
                terminal_at = expiry
                if current < terminal_at + timedelta(
                    seconds=DEFAULT_OPERATION_DRAFT_TERMINAL_RETENTION_SECONDS
                ):
                    self._replace_record(
                        entry,
                        self._expired_record(record).as_durable_dict(),
                        expected_previous=loaded,
                    )
                    continue
            else:
                if record.terminal_at is None:
                    raise OperationDraftStorageCorruption(
                        "Terminal Operation Draft is missing terminal_at."
                    )
                terminal_at = _parse_timestamp(record.terminal_at)
            if current >= terminal_at + timedelta(
                seconds=DEFAULT_OPERATION_DRAFT_TERMINAL_RETENTION_SECONDS
            ):
                self._unlink_managed_file(
                    entry,
                    label="Operation Draft record",
                    expected_metadata=loaded.metadata,
                    expected_bytes=loaded.durable_bytes,
                )
        self._require_managed_entry_capacity(additional_entries=1)
        return active

    def _collect_crash_temporary(self, entry: Path, *, now: datetime) -> None:
        metadata = _require_private_regular_file(
            entry,
            label="Operation Draft temporary record",
        )
        if metadata.st_size > MAX_OPERATION_DRAFT_RECORD_BYTES:
            raise OperationDraftLimitExceeded(
                "Operation Draft temporary record exceeds its fixed byte ceiling.",
                details={"limit_bytes": MAX_OPERATION_DRAFT_RECORD_BYTES},
            )
        cutoff = now.timestamp() - DEFAULT_OPERATION_DRAFT_STALE_TEMP_SECONDS
        if metadata.st_mtime > cutoff:
            return
        current = _require_private_regular_file(
            entry,
            label="Operation Draft temporary record",
        )
        if not os.path.samestat(metadata, current) or current.st_mtime > cutoff:
            raise OperationDraftStorageCorruption(
                "Operation Draft temporary record changed during cleanup."
            )
        self._unlink_managed_file(
            entry,
            label="Operation Draft temporary record",
            expected_metadata=current,
        )

    def _load_available(self, draft_id: str) -> _LoadedOperationDraft:
        if not isinstance(draft_id, str) or not _DRAFT_ID_PATTERN.fullmatch(draft_id):
            raise _not_available()
        try:
            record_read = self._read_record_snapshot(self._record_path(draft_id))
            record = _parse_canonical_record_bytes(
                record_read.data,
                expected_draft_id=draft_id,
            )
            return _LoadedOperationDraft(
                record=record,
                durable_bytes=record_read.data,
                metadata=record_read.metadata,
            )
        except _OperationDraftDirectoryIdentityChanged:
            raise
        except (
            FileNotFoundError,
            OSError,
            RecursionError,
            UnicodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
            OperationDraftStorageCorruption,
        ):
            raise _not_available() from None

    def _record_path(self, draft_id: str) -> Path:
        return self.records_dir / f"{draft_id}.json"

    def _attest_directory_identities(self) -> None:
        _attest_managed_directory_identities(self._directory_identities)

    def _read_record(self, path: Path) -> bytes:
        return self._read_record_snapshot(path).data

    def _read_record_snapshot(self, path: Path) -> _RegularFileRead:
        self._attest_directory_identities()
        try:
            return _read_bounded_record_snapshot(
                path,
                attest_directories=self._attest_directory_identities,
            )
        finally:
            self._attest_directory_identities()

    def _write_record(self, path: Path, payload: Mapping[str, Any]) -> None:
        self._attest_directory_identities()
        expected_bytes = canonical_json_bytes(payload)
        try:
            written_metadata = _write_new(
                path,
                payload,
                attest_directories=self._attest_directory_identities,
            )
            written = self._read_record_snapshot(path)
            if (
                not os.path.samestat(written_metadata, written.metadata)
                or not hmac.compare_digest(expected_bytes, written.data)
            ):
                raise OperationDraftStorageCorruption(
                    "Operation Draft record changed during initial publish."
                )
        finally:
            self._attest_directory_identities()

    def _replace_record(
        self,
        path: Path,
        payload: Mapping[str, Any],
        *,
        expected_previous: _LoadedOperationDraft,
    ) -> None:
        self._attest_directory_identities()
        try:
            _replace(
                path,
                payload,
                expected_previous_bytes=expected_previous.durable_bytes,
                expected_previous_metadata=expected_previous.metadata,
                attest_directories=self._attest_directory_identities,
            )
        finally:
            self._attest_directory_identities()

    def _unlink_managed_file(
        self,
        path: Path,
        *,
        label: str,
        expected_metadata: os.stat_result,
        expected_bytes: bytes | None = None,
    ) -> None:
        self._attest_directory_identities()
        try:
            if not _lexists(path):
                raise FileNotFoundError(path)
            current = _require_private_regular_file(path, label=label)
            if not os.path.samestat(expected_metadata, current):
                raise OperationDraftStorageCorruption(
                    f"{label} identity changed before removal."
                )
            if expected_bytes is not None:
                current_read = self._read_record_snapshot(path)
                if (
                    not os.path.samestat(expected_metadata, current_read.metadata)
                    or not hmac.compare_digest(expected_bytes, current_read.data)
                ):
                    raise OperationDraftStorageCorruption(
                        f"{label} changed before removal."
                    )
            self._attest_directory_identities()
            path.unlink()
            _fsync_directory(path.parent)
        finally:
            self._attest_directory_identities()

    def _bounded_entries(
        self,
        path: Path,
        *,
        label: str,
    ) -> list[Path]:
        self._attest_directory_identities()
        try:
            return _bounded_managed_entries(
                path,
                label=label,
                attest_directories=self._attest_directory_identities,
            )
        finally:
            self._attest_directory_identities()

    def _collect_orphan_locks(
        self,
        entries: list[Path],
    ) -> None:
        admission_seen = False
        for entry in sorted(entries, key=lambda candidate: candidate.name):
            if entry.name == "store-admission.lock":
                if admission_seen:
                    raise OperationDraftStorageCorruption(
                        "Operation Draft locks directory contains duplicate admission state."
                    )
                admission_seen = True
                metadata = _require_private_regular_file(
                    entry,
                    label="Operation Draft admission lock",
                )
                if not os.path.samestat(self._admission_lock_identity, metadata):
                    raise OperationDraftStorageCorruption(
                        "Operation Draft admission lock identity changed."
                    )
                continue
            match = _LOCK_NAME_PATTERN.fullmatch(entry.name)
            if match is None:
                raise OperationDraftStorageCorruption(
                    "Operation Draft locks directory contains an unmanaged entry."
                )
            metadata = _require_private_regular_file(
                entry,
                label="Operation Draft lock",
            )
            self._unlink_managed_file(
                entry,
                label="Operation Draft obsolete lock",
                expected_metadata=metadata,
            )
        if not admission_seen:
            raise OperationDraftStorageCorruption(
                "Operation Draft admission lock disappeared during cleanup."
            )

    def _require_managed_entry_capacity(self, *, additional_entries: int) -> None:
        record_entries = self._bounded_entries(
            self.records_dir,
            label="Operation Draft records directory",
        )
        lock_entries = self._bounded_entries(
            self.locks_dir,
            label="Operation Draft locks directory",
        )
        current_entries = len(record_entries) + len(lock_entries)
        required_entries = current_entries + additional_entries
        if required_entries > MAX_MANAGED_OPERATION_DRAFT_ENTRIES:
            raise OperationDraftLimitExceeded(
                "Operation Draft managed-entry ceiling has been exceeded.",
                details={
                    "managed_entries_at_least": (
                        current_entries
                        if current_entries > MAX_MANAGED_OPERATION_DRAFT_ENTRIES
                        else required_entries
                    ),
                    "limit": MAX_MANAGED_OPERATION_DRAFT_ENTRIES,
                },
            )

    @contextmanager
    def _store_lock(self) -> Iterator[None]:
        self._attest_directory_identities()
        try:
            with self._file_lock(self._admission_lock_path):
                yield
        finally:
            self._attest_directory_identities()

    @contextmanager
    def _existing_draft_lock(self, draft_id: str) -> Iterator[None]:
        # One admission lock serializes every durable revision and cleanup.
        # It also lets missing-id probes fail without creating per-draft files.
        with self._store_lock():
            record_path = self._record_path(draft_id)
            if not _lexists(record_path):
                raise _not_available()
            try:
                _require_private_regular_file(
                    record_path,
                    label="Operation Draft record",
                )
            except OperationDraftStorageCorruption:
                raise _not_available() from None
            yield

    @contextmanager
    def _file_lock(self, lock_path: Path) -> Iterator[None]:
        self._attest_directory_identities()
        backend = _select_lock_backend(_lock_platform_name())
        if not _lexists(lock_path):
            raise OperationDraftStorageCorruption(
                "Operation Draft admission lock is unavailable."
            )
        lock_metadata = _require_private_regular_file(
            lock_path,
            label="Operation Draft lock",
        )
        if not os.path.samestat(self._admission_lock_identity, lock_metadata):
            raise OperationDraftStorageCorruption(
                "Operation Draft admission lock identity changed."
            )
        flags = os.O_RDWR | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(lock_path, flags)
        try:
            opened_lock_metadata = _require_opened_private_regular_file(
                lock_path,
                descriptor=descriptor,
                label="Operation Draft lock",
            )
            if not os.path.samestat(
                self._admission_lock_identity,
                opened_lock_metadata,
            ):
                raise OperationDraftStorageCorruption(
                    "Operation Draft admission lock identity changed."
                )
            handle = os.fdopen(descriptor, "r+b", buffering=0, closefd=True)
        except BaseException:
            os.close(descriptor)
            raise
        acquired = False
        try:
            backend.acquire(handle)
            acquired = True
            opened_lock_metadata = _require_opened_private_regular_file(
                lock_path,
                descriptor=handle.fileno(),
                label="Operation Draft lock",
            )
            if not os.path.samestat(
                self._admission_lock_identity,
                opened_lock_metadata,
            ):
                raise OperationDraftStorageCorruption(
                    "Operation Draft admission lock identity changed."
                )
            self._attest_directory_identities()
            yield
        finally:
            if acquired:
                try:
                    backend.release(handle)
                except BaseException:
                    # Closing the descriptor is the platform-independent final
                    # unlock fallback.  A committed body must not be reported
                    # as failed merely because the explicit unlock helper did.
                    pass
            try:
                handle.close()
            except BaseException:
                # The body has already committed or raised.  Reporting a new
                # cleanup exception here would make durable state disagree
                # with the caller-visible result; descriptor finalization is
                # still attempted by the runtime.
                pass
            self._attest_directory_identities()


def _not_available() -> OperationDraftNotAvailable:
    return OperationDraftNotAvailable(
        "No Operation Draft is available for that id and task authority."
    )


def _is_windows_lock_contention(exc: OSError) -> bool:
    return exc.errno in {errno.EACCES, errno.EDEADLK} or (
        getattr(exc, "winerror", None) == _WINDOWS_LOCK_VIOLATION
    )


def _select_lock_backend(platform_name: str) -> Any:
    if platform_name == "posix":
        if _fcntl is None or any(
            not hasattr(_fcntl, name)
            for name in ("flock", "LOCK_EX", "LOCK_NB", "LOCK_UN")
        ):
            raise OperationDraftLockUnavailable(
                "Operation Draft storage requires fcntl.flock and will not run unlocked."
            )
        return _PosixDraftLockBackend(_fcntl)
    if platform_name == "nt":
        if _msvcrt is None or any(
            not hasattr(_msvcrt, name)
            for name in ("locking", "LK_NBLCK", "LK_UNLCK")
        ):
            raise OperationDraftLockUnavailable(
                "Operation Draft storage requires msvcrt.locking and will not run unlocked."
            )
        return _WindowsDraftLockBackend(_msvcrt)
    raise OperationDraftLockUnavailable(
        f"Operation Draft storage has no lock backend for os.name={platform_name!r}."
    )


def _lock_platform_name() -> str:
    return os.name


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


def _parse_canonical_record_bytes(
    data: bytes,
    *,
    expected_draft_id: str,
) -> OperationDraftRecord:
    payload = json.loads(data.decode("utf-8"))
    record = _record_from_mapping(
        payload,
        expected_draft_id=expected_draft_id,
    )
    if not hmac.compare_digest(data, canonical_json_bytes(record.as_durable_dict())):
        raise ValueError("draft record bytes are not in canonical durable form")
    return record


def _record_from_mapping(
    payload: Any,
    *,
    expected_draft_id: str,
) -> OperationDraftRecord:
    if not isinstance(payload, Mapping):
        raise TypeError("draft record must be an object")
    expected = {
        "audit",
        "authority_digest",
        "contract",
        "created_at",
        "draft_id",
        "expires_at",
        "limits_digest",
        "operation",
        "record_digest",
        "revision",
        "schema_digest",
        "schema_version",
        "state",
        "terminal_at",
        "updated_at",
        "version",
    }
    if set(payload) != expected:
        raise ValueError("draft record fields are invalid")
    stored_record_digest = payload["record_digest"]
    if (
        not isinstance(stored_record_digest, str)
        or not _SHA256_PATTERN.fullmatch(stored_record_digest)
    ):
        raise ValueError("record digest is invalid")
    digest_material = dict(payload)
    del digest_material["record_digest"]
    if not hmac.compare_digest(
        stored_record_digest,
        _record_digest(digest_material),
    ):
        raise ValueError("record digest does not match")
    if payload["contract"] != OPERATION_DRAFT_CONTRACT:
        raise ValueError("draft contract is invalid")
    if payload["schema_version"] != OPERATION_DRAFT_SCHEMA_VERSION:
        raise ValueError("draft schema version is invalid")
    if payload["limits_digest"] != OPERATION_DRAFT_LIMITS_DIGEST:
        raise ValueError("draft limits digest is invalid")
    draft_id = payload["draft_id"]
    authority_digest = payload["authority_digest"]
    schema_digest = payload["schema_digest"]
    revision = payload["revision"]
    if not isinstance(draft_id, str) or not _DRAFT_ID_PATTERN.fullmatch(draft_id):
        raise ValueError("draft id is invalid")
    if draft_id != expected_draft_id:
        raise ValueError("draft id does not match its durable record path")
    if not isinstance(authority_digest, str) or not _SHA256_PATTERN.fullmatch(authority_digest):
        raise ValueError("authority digest is invalid")
    if not isinstance(schema_digest, str) or not _SHA256_PATTERN.fullmatch(schema_digest):
        raise ValueError("schema digest is invalid")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("revision is invalid")
    for field in ("operation", "version"):
        if not isinstance(payload[field], str) or not payload[field]:
            raise ValueError(f"{field} is invalid")
    for field in ("created_at", "updated_at", "expires_at"):
        if not isinstance(payload[field], str) or not payload[field]:
            raise ValueError(f"{field} is invalid")
        _parse_timestamp(payload[field])
    terminal_at = payload["terminal_at"]
    if terminal_at is not None:
        if not isinstance(terminal_at, str) or not terminal_at:
            raise ValueError("terminal_at is invalid")
        _parse_timestamp(terminal_at)
    state = OperationDraftState(payload["state"])
    created_at = _parse_timestamp(payload["created_at"])
    updated_at = _parse_timestamp(payload["updated_at"])
    expires_at = _parse_timestamp(payload["expires_at"])
    if expires_at != created_at + timedelta(
        seconds=DEFAULT_OPERATION_DRAFT_TTL_SECONDS
    ):
        raise ValueError("draft expiry does not match its fixed lifetime")
    if updated_at < created_at or updated_at > expires_at:
        raise ValueError("draft updated_at is outside its fixed lifetime")
    if state is OperationDraftState.EDITABLE:
        if terminal_at is not None or updated_at >= expires_at:
            raise ValueError("editable draft lifetime fields are invalid")
    elif terminal_at is None:
        raise ValueError("terminal draft is missing terminal_at")
    else:
        parsed_terminal_at = _parse_timestamp(terminal_at)
        if parsed_terminal_at != updated_at:
            raise ValueError("terminal draft timestamps disagree")
        if state is OperationDraftState.EXPIRED:
            if parsed_terminal_at != expires_at:
                raise ValueError("expired draft must terminate at expires_at")
        elif parsed_terminal_at >= expires_at:
            raise ValueError("cancelled draft must terminate before expires_at")
    audit = _validate_audit(
        payload["audit"],
        draft_id=draft_id,
        revision=revision,
        state=state,
        created_at=created_at,
        updated_at=updated_at,
    )
    return OperationDraftRecord(
        draft_id=draft_id,
        state=state,
        revision=revision,
        operation=payload["operation"],
        version=payload["version"],
        schema_digest=schema_digest,
        authority_digest=authority_digest,
        created_at=payload["created_at"],
        updated_at=payload["updated_at"],
        expires_at=payload["expires_at"],
        terminal_at=terminal_at,
        audit=audit,
        limits_digest=OPERATION_DRAFT_LIMITS_DIGEST,
    )


def _timestamp(now: datetime | None) -> str:
    current = _utc_datetime(now)

    return current.isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _utc_datetime(now: datetime | None) -> datetime:
    current = datetime.now(timezone.utc) if now is None else now
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not _TIMESTAMP_PATTERN.fullmatch(value):
        raise ValueError("timestamp must use the canonical UTC microsecond spelling")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("timestamp is not a valid UTC datetime") from exc
    return parsed.astimezone(timezone.utc)


def _record_digest(payload: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {
            "contract": OPERATION_DRAFT_RECORD_DIGEST_CONTRACT,
            "record": dict(payload),
        }
    )


def _build_audit_event(
    *,
    draft_id: str,
    sequence: int,
    revision: int,
    event_type: str,
    from_state: OperationDraftState | None,
    to_state: OperationDraftState,
    timestamp: str,
    previous_event_hash: str,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "contract": OPERATION_DRAFT_AUDIT_EVENT_CONTRACT,
        "draft_id": draft_id,
        "event_type": event_type,
        "from_state": None if from_state is None else from_state.value,
        "previous_event_hash": previous_event_hash,
        "revision": revision,
        "sequence": sequence,
        "timestamp": timestamp,
        "to_state": to_state.value,
    }
    event["event_hash"] = canonical_sha256(event)
    return event


def _validate_audit(
    value: Any,
    *,
    draft_id: str,
    revision: int,
    state: OperationDraftState,
    created_at: datetime,
    updated_at: datetime,
) -> tuple[Mapping[str, Any], ...]:
    if (
        not isinstance(value, list)
        or not value
        or len(value) > MAX_OPERATION_DRAFT_ACTIONS
    ):
        raise ValueError("draft audit is invalid or exceeds its fixed ceiling")
    events: list[Mapping[str, Any]] = []
    previous_hash = ""
    previous_state: str | None = None
    previous_timestamp: datetime | None = None
    expected_fields = {
        "contract",
        "draft_id",
        "event_hash",
        "event_type",
        "from_state",
        "previous_event_hash",
        "revision",
        "sequence",
        "timestamp",
        "to_state",
    }
    for sequence, raw_event in enumerate(value, start=1):
        if not isinstance(raw_event, Mapping) or set(raw_event) != expected_fields:
            raise ValueError("draft audit event fields are invalid")
        event = dict(raw_event)
        stored_hash = event.pop("event_hash")
        if (
            event["contract"] != OPERATION_DRAFT_AUDIT_EVENT_CONTRACT
            or event["draft_id"] != draft_id
            or isinstance(event["sequence"], bool)
            or not isinstance(event["sequence"], int)
            or event["sequence"] != sequence
            or isinstance(event["revision"], bool)
            or not isinstance(event["revision"], int)
            or event["revision"] != sequence
            or event["previous_event_hash"] != previous_hash
            or event["from_state"] != previous_state
            or not isinstance(stored_hash, str)
            or not _SHA256_PATTERN.fullmatch(stored_hash)
            or not hmac.compare_digest(stored_hash, canonical_sha256(event))
        ):
            raise ValueError("draft audit hash chain is invalid")
        event_timestamp = _parse_timestamp(event["timestamp"])
        if previous_timestamp is not None and event_timestamp < previous_timestamp:
            raise ValueError("draft audit timestamps are not monotonic")
        to_state = OperationDraftState(event["to_state"])
        if sequence == 1 and (
            event["event_type"] != "started"
            or event["from_state"] is not None
            or event["to_state"] != OperationDraftState.EDITABLE.value
            or event_timestamp != created_at
        ):
            raise ValueError("draft audit creation event is invalid")
        if (
            not isinstance(event["event_type"], str)
            or not _AUDIT_EVENT_TYPE_PATTERN.fullmatch(event["event_type"])
        ):
            raise ValueError("draft audit event type is invalid")
        if sequence > 1:
            if previous_state != OperationDraftState.EDITABLE.value:
                raise ValueError("draft audit cannot continue after a terminal state")
            if to_state is OperationDraftState.CANCELLED:
                if event["event_type"] != "cancelled" or sequence != len(value):
                    raise ValueError("draft audit cancellation event is invalid")
            elif to_state is OperationDraftState.EXPIRED:
                if event["event_type"] != "expired" or sequence != len(value):
                    raise ValueError("draft audit expiry event is invalid")
            elif to_state is not OperationDraftState.EDITABLE:
                raise ValueError("draft audit transition is invalid")
        previous_hash = stored_hash
        previous_state = event["to_state"]
        previous_timestamp = event_timestamp
        events.append(dict(raw_event))
    if (
        len(events) != revision
        or previous_state != state.value
        or previous_timestamp != updated_at
    ):
        raise ValueError("draft audit does not match current revision")
    return tuple(events)


def _read_bounded_record_snapshot(
    path: Path,
    *,
    attest_directories: Callable[[], None],
) -> _RegularFileRead:
    before = _require_private_regular_file(path, label="Operation Draft record")
    if before.st_size > MAX_OPERATION_DRAFT_RECORD_BYTES:
        raise ValueError("Operation Draft record exceeds its fixed byte ceiling")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        _require_opened_private_regular_file(
            path,
            descriptor=descriptor,
            label="Operation Draft record",
        )
        attest_directories()
        chunks: list[bytes] = []
        remaining = MAX_OPERATION_DRAFT_RECORD_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(descriptor)
        if not _same_regular_file_snapshot(before, after):
            raise OperationDraftStorageCorruption(
                "Operation Draft record changed while it was read."
            )
        if len(data) != after.st_size:
            raise OperationDraftStorageCorruption(
                "Operation Draft record could not be read completely."
            )
        _require_opened_private_regular_file(
            path,
            descriptor=descriptor,
            label="Operation Draft record",
        )
        attest_directories()
    finally:
        os.close(descriptor)
    if len(data) > MAX_OPERATION_DRAFT_RECORD_BYTES:
        raise ValueError("Operation Draft record exceeds its fixed byte ceiling")
    return _RegularFileRead(data=data, metadata=after)


def _write_new(
    path: Path,
    payload: Mapping[str, Any],
    *,
    attest_directories: Callable[[], None],
) -> os.stat_result:
    data = canonical_json_bytes(payload)
    if len(data) > MAX_OPERATION_DRAFT_RECORD_BYTES:
        raise OperationDraftLimitExceeded(
            "Operation Draft record exceeds its fixed byte ceiling.",
            details={"limit_bytes": MAX_OPERATION_DRAFT_RECORD_BYTES},
        )
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
    )
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    opened_metadata: os.stat_result | None = None
    try:
        opened_metadata = _require_opened_private_regular_file(
            path,
            descriptor=descriptor,
            label="Operation Draft record",
        )
        attest_directories()
        handle = os.fdopen(descriptor, "wb")
        descriptor = -1
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            opened_metadata = _require_opened_private_regular_file(
                path,
                descriptor=handle.fileno(),
                label="Operation Draft record",
            )
            attest_directories()
        _fsync_directory(path.parent)
        return opened_metadata
    except BaseException as exc:
        if descriptor >= 0:
            os.close(descriptor)
        if isinstance(exc, _OperationDraftDirectoryIdentityChanged):
            raise
        _unlink_created_file_if_same(
            path,
            expected_metadata=opened_metadata,
            attest_directories=attest_directories,
        )
        raise


def _replace(
    path: Path,
    payload: Mapping[str, Any],
    *,
    expected_previous_bytes: bytes,
    expected_previous_metadata: os.stat_result,
    attest_directories: Callable[[], None],
) -> None:
    expected_bytes = canonical_json_bytes(payload)
    _require_private_regular_file(path, label="Operation Draft record")
    current_read = _read_bounded_record_snapshot(
        path,
        attest_directories=attest_directories,
    )
    if (
        not os.path.samestat(expected_previous_metadata, current_read.metadata)
        or not hmac.compare_digest(current_read.data, expected_previous_bytes)
    ):
        raise OperationDraftStorageCorruption(
            "Operation Draft record changed after its revision was validated."
        )
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    directory_identity_changed = False
    temporary_metadata: os.stat_result | None = None
    try:
        temporary_metadata = _write_new(
            temporary,
            payload,
            attest_directories=attest_directories,
        )
        _require_private_regular_file(path, label="Operation Draft record")
        current_read = _read_bounded_record_snapshot(
            path,
            attest_directories=attest_directories,
        )
        if (
            not os.path.samestat(expected_previous_metadata, current_read.metadata)
            or not hmac.compare_digest(current_read.data, expected_previous_bytes)
        ):
            raise OperationDraftStorageCorruption(
                "Operation Draft record changed before atomic revision publish."
            )
        temporary_read = _read_bounded_record_snapshot(
            temporary,
            attest_directories=attest_directories,
        )
        if (
            not os.path.samestat(temporary_metadata, temporary_read.metadata)
            or not hmac.compare_digest(expected_bytes, temporary_read.data)
        ):
            raise OperationDraftStorageCorruption(
                "Operation Draft temporary record changed before atomic publish."
            )
        attest_directories()
        os.replace(temporary, path)
        attest_directories()
        _require_private_regular_file(path, label="Operation Draft record")
        published_read = _read_bounded_record_snapshot(
            path,
            attest_directories=attest_directories,
        )
        if (
            not os.path.samestat(temporary_metadata, published_read.metadata)
            or not hmac.compare_digest(published_read.data, expected_bytes)
        ):
            raise OperationDraftStorageCorruption(
                "Operation Draft record changed during atomic publish."
            )
        _fsync_directory(path.parent)
    except _OperationDraftDirectoryIdentityChanged:
        directory_identity_changed = True
        raise
    except OperationDraftError:
        raise
    except OSError as exc:
        raise OperationDraftStorageCorruption(
            "Operation Draft record could not be published atomically."
        ) from exc
    finally:
        if not directory_identity_changed:
            _unlink_created_file_if_same(
                temporary,
                expected_metadata=temporary_metadata,
                attest_directories=attest_directories,
            )


def _unlink_created_file_if_same(
    path: Path,
    *,
    expected_metadata: os.stat_result | None,
    attest_directories: Callable[[], None],
) -> None:
    attest_directories()
    if not _lexists(path):
        return
    current = _require_private_regular_file(
        path,
        label="Operation Draft cleanup file",
    )
    if expected_metadata is None or not os.path.samestat(expected_metadata, current):
        raise OperationDraftStorageCorruption(
            "Operation Draft cleanup file identity changed before removal."
        )
    attest_directories()
    path.unlink()
    _fsync_directory(path.parent)


def _ensure_admission_lock_file(
    path: Path,
    *,
    attest_directories: Callable[[], None],
) -> os.stat_result:
    attest_directories()
    if _lexists(path):
        return _require_private_regular_file(
            path,
            label="Operation Draft admission lock",
        )
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        attest_directories()
        return _require_private_regular_file(
            path,
            label="Operation Draft admission lock",
        )
    try:
        metadata = _require_opened_private_regular_file(
            path,
            descriptor=descriptor,
            label="Operation Draft admission lock",
        )
        attest_directories()
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)
    attest_directories()
    return metadata


def _capture_managed_directory_identities(
    *,
    state_dir: Path,
    managed_directories: tuple[Path, ...],
) -> tuple[_ManagedDirectoryIdentity, ...]:
    identities: list[_ManagedDirectoryIdentity] = []
    seen: set[Path] = set()
    current = Path(state_dir.anchor)
    for component in state_dir.parts[1:]:
        current /= component
        if current in seen:
            continue
        require_private = current == state_dir
        identities.append(
            _ManagedDirectoryIdentity(
                path=current,
                metadata=_require_plain_directory(
                    current,
                    label="Operation Draft state directory",
                    require_private=require_private,
                ),
                require_private=require_private,
            )
        )
        seen.add(current)
    for directory in managed_directories:
        if directory in seen:
            continue
        identities.append(
            _ManagedDirectoryIdentity(
                path=directory,
                metadata=_require_plain_directory(
                    directory,
                    label="Operation Draft managed directory",
                    require_private=True,
                ),
                require_private=True,
            )
        )
        seen.add(directory)
    return tuple(identities)


def _attest_managed_directory_identities(
    identities: tuple[_ManagedDirectoryIdentity, ...],
) -> None:
    for identity in identities:
        try:
            current = _require_plain_directory(
                identity.path,
                label="Operation Draft managed directory",
                require_private=identity.require_private,
            )
        except OperationDraftStorageCorruption as exc:
            raise _OperationDraftDirectoryIdentityChanged(
                "Operation Draft managed directory identity cannot be re-attested."
            ) from exc
        if not os.path.samestat(identity.metadata, current):
            raise _OperationDraftDirectoryIdentityChanged(
                "Operation Draft managed directory identity changed after initialization."
            )


def _ensure_private_state_directory(path: Path, *, label: str) -> None:
    if not path.is_absolute():
        raise OperationDraftStorageCorruption(f"{label} must be absolute.")
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        created = False
        if not _lexists(current):
            try:
                current.mkdir(mode=0o700, parents=False)
                created = True
            except FileExistsError:
                pass
            except OSError as exc:
                raise OperationDraftStorageCorruption(
                    f"{label} could not be created safely."
                ) from exc
        _require_plain_directory(current, label=label, require_private=False)
        if created and os.name == "posix":
            os.chmod(current, 0o700)
    _require_plain_directory(path, label=label, require_private=True)


def _ensure_private_managed_directory(path: Path, *, label: str) -> None:
    if not _lexists(path):
        try:
            path.mkdir(mode=0o700, parents=False)
        except FileExistsError:
            pass
        except OSError as exc:
            raise OperationDraftStorageCorruption(
                f"{label} could not be created safely."
            ) from exc
        if os.name == "posix":
            os.chmod(path, 0o700)
    _require_plain_directory(path, label=label, require_private=True)


def _require_plain_directory(
    path: Path,
    *,
    label: str,
    require_private: bool,
) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise OperationDraftStorageCorruption(f"{label} is unavailable.") from exc
    if path_is_link_or_reparse(path, metadata=metadata):
        raise OperationDraftStorageCorruption(
            f"{label} cannot be a link, junction, or reparse point."
        )
    if not stat.S_ISDIR(metadata.st_mode):
        raise OperationDraftStorageCorruption(f"{label} must be a directory.")
    if require_private:
        _require_private_posix_metadata(metadata, label=label)
    return metadata


def _require_private_regular_file(path: Path, *, label: str) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise OperationDraftStorageCorruption(f"{label} is unavailable.") from exc
    if path_is_link_or_reparse(path, metadata=metadata):
        raise OperationDraftStorageCorruption(
            f"{label} cannot be a link, junction, or reparse point."
        )
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise OperationDraftStorageCorruption(
            f"{label} must be one non-hard-linked regular file."
        )
    _require_private_posix_metadata(metadata, label=label)
    return metadata


def _require_private_posix_metadata(metadata: os.stat_result, *, label: str) -> None:
    if os.name != "posix":
        return
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise OperationDraftStorageCorruption(
            f"{label} must not grant group or other permissions."
        )
    getuid = getattr(os, "geteuid", None)
    if getuid is not None and metadata.st_uid != getuid():
        raise OperationDraftStorageCorruption(
            f"{label} must be owned by the current user."
        )


def _require_opened_private_regular_file(
    path: Path,
    *,
    descriptor: int,
    label: str,
) -> os.stat_result:
    path_metadata = _require_private_regular_file(path, label=label)
    try:
        opened_metadata = os.fstat(descriptor)
    except OSError as exc:
        raise OperationDraftStorageCorruption(
            f"{label} descriptor cannot be attested."
        ) from exc
    if (
        not stat.S_ISREG(opened_metadata.st_mode)
        or opened_metadata.st_nlink != 1
        or not os.path.samestat(path_metadata, opened_metadata)
    ):
        raise OperationDraftStorageCorruption(
            f"{label} path changed while it was opened."
        )
    _require_private_posix_metadata(opened_metadata, label=label)
    return opened_metadata


def _same_regular_file_snapshot(
    left: os.stat_result,
    right: os.stat_result,
) -> bool:
    return (
        stat.S_ISREG(left.st_mode)
        and stat.S_ISREG(right.st_mode)
        and os.path.samestat(left, right)
        and left.st_size == right.st_size
        and left.st_mtime_ns == right.st_mtime_ns
        and left.st_ctime_ns == right.st_ctime_ns
        and left.st_nlink == right.st_nlink == 1
    )


def _bounded_managed_entries(
    path: Path,
    *,
    label: str,
    attest_directories: Callable[[], None],
) -> list[Path]:
    before = _require_plain_directory(
        path,
        label=label,
        require_private=True,
    )
    entries: list[Path] = []
    try:
        with os.scandir(path) as iterator:
            attest_directories()
            for entry in iterator:
                entries.append(Path(entry.path))
                managed_entries = len(entries)
                if managed_entries > MAX_MANAGED_OPERATION_DRAFT_ENTRIES:
                    raise OperationDraftLimitExceeded(
                        "Operation Draft managed-entry ceiling has been exceeded.",
                        details={
                            "managed_entries_at_least": managed_entries,
                            "limit": MAX_MANAGED_OPERATION_DRAFT_ENTRIES,
                        },
                    )
    except OperationDraftError:
        raise
    except OSError as exc:
        raise OperationDraftStorageCorruption(
            "Operation Draft records directory cannot be scanned safely."
        ) from exc
    after = _require_plain_directory(
        path,
        label=label,
        require_private=True,
    )
    if not os.path.samestat(before, after):
        raise OperationDraftStorageCorruption(
            f"{label} changed during bounded scan."
        )
    attest_directories()
    return entries


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _lexists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


__all__ = [
    "OPERATION_DRAFT_CONTRACT",
    "DEFAULT_OPERATION_DRAFT_LOCK_TIMEOUT_SECONDS",
    "DEFAULT_OPERATION_DRAFT_TERMINAL_RETENTION_SECONDS",
    "DEFAULT_OPERATION_DRAFT_STALE_TEMP_SECONDS",
    "DEFAULT_OPERATION_DRAFT_TTL_SECONDS",
    "MAX_ACTIVE_OPERATION_DRAFTS",
    "MAX_MANAGED_OPERATION_DRAFT_ENTRIES",
    "MAX_OPERATION_DRAFT_ACTIONS",
    "MAX_OPERATION_DRAFT_EVIDENCE_BYTES",
    "MAX_OPERATION_DRAFT_FIELDS_PER_ROW",
    "MAX_OPERATION_DRAFT_RECORD_BYTES",
    "MAX_OPERATION_DRAFT_RESULT_BYTES",
    "MAX_OPERATION_DRAFT_ROWS",
    "OPERATION_DRAFT_LIMITS",
    "OPERATION_DRAFT_LIMITS_DIGEST",
    "OperationDraftError",
    "OperationDraftExpired",
    "OperationDraftInvalidTransition",
    "OperationDraftLockUnavailable",
    "OperationDraftLimitExceeded",
    "OperationDraftLimits",
    "OperationDraftNotAvailable",
    "OperationDraftRecord",
    "OperationDraftRevisionConflict",
    "OperationDraftStorageCorruption",
    "OperationDraftStart",
    "OperationDraftState",
    "OperationDraftStore",
]
