"""Durable, WAAPI-independent transaction preview artifacts.

The store implements the local half of a preview -> confirm -> execute ->
verify protocol.  It never imports a WAAPI client and never performs a Wwise
operation.  A preview is immutable and confirmation is bound to its canonical
SHA-256 hash.

Concurrency support intentionally has a clear platform boundary: the locking
backend uses ``fcntl.flock`` and therefore supports macOS and Linux.  Windows
callers receive :class:`FileLockUnavailable` rather than silently running
without a cross-process lock.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import shutil
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from .canonical import canonical_json_bytes, canonical_sha256

try:  # pragma: no branch - the absence is exercised by an explicit test hook.
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - exercised on Windows, not POSIX CI.
    _fcntl = None


STATE_DIRECTORY_ENV = "WAAPI_SKILL_STATE_DIR"
TRANSACTION_SCHEMA_VERSION = 1
_TRANSACTION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class TransactionError(RuntimeError):
    """Base class for durable transaction store failures."""


class StateDirectoryNotConfigured(TransactionError):
    """No explicit state directory or environment fallback was provided."""


class UnsafeTransactionId(TransactionError, ValueError):
    """A transaction id could escape or ambiguously address the state root."""


class TransactionNotFound(TransactionError, FileNotFoundError):
    """The requested transaction does not exist."""


class PreviewAlreadyExists(TransactionError, FileExistsError):
    """An immutable preview already exists for this transaction id."""


class InvalidTransition(TransactionError, ValueError):
    """The requested state transition is not part of the closed state graph."""


class StateConflict(TransactionError):
    """The caller's expected state did not match durable state."""


class ArtifactIntegrityError(TransactionError):
    """A preview, state record, or event no longer matches its stored hash."""


class StateCorruptionError(TransactionError):
    """Durable transaction metadata or its event journal is malformed."""


class FileLockUnavailable(TransactionError):
    """No supported cross-process file-lock implementation is available."""


class TransactionState(str, Enum):
    """Closed durable states for mutation transactions."""

    DRAFT = "draft"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    EXECUTING = "executing"
    EXECUTED_UNVERIFIED = "executed_unverified"
    VERIFIED = "verified"
    VERIFICATION_FAILED = "verification_failed"
    INDETERMINATE = "indeterminate"
    REPREVIEW_REQUIRED = "repreview_required"


ALLOWED_TRANSITIONS: Mapping[TransactionState, frozenset[TransactionState]] = {
    TransactionState.DRAFT: frozenset({TransactionState.AWAITING_CONFIRMATION}),
    TransactionState.AWAITING_CONFIRMATION: frozenset(
        {TransactionState.CONFIRMED, TransactionState.REJECTED}
    ),
    TransactionState.CONFIRMED: frozenset(
        {TransactionState.EXECUTING, TransactionState.REPREVIEW_REQUIRED}
    ),
    TransactionState.REJECTED: frozenset(),
    TransactionState.EXECUTING: frozenset(
        {TransactionState.EXECUTED_UNVERIFIED, TransactionState.INDETERMINATE}
    ),
    TransactionState.EXECUTED_UNVERIFIED: frozenset(
        {
            TransactionState.VERIFIED,
            TransactionState.VERIFICATION_FAILED,
            TransactionState.INDETERMINATE,
            TransactionState.REPREVIEW_REQUIRED,
        }
    ),
    TransactionState.VERIFIED: frozenset(),
    TransactionState.VERIFICATION_FAILED: frozenset(),
    TransactionState.INDETERMINATE: frozenset(),
    TransactionState.REPREVIEW_REQUIRED: frozenset(),
}


@dataclass(slots=True, frozen=True)
class PreviewArtifact:
    """One immutable preview and the hash to which confirmation is bound."""

    transaction_id: str
    artifact: Any
    artifact_hash: str
    created_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact,
            "artifact_hash": self.artifact_hash,
            "created_at": self.created_at,
            "schema_version": TRANSACTION_SCHEMA_VERSION,
            "transaction_id": self.transaction_id,
        }


@dataclass(slots=True, frozen=True)
class TransactionRecord:
    """Materialized transaction state backed by the append-only event journal."""

    transaction_id: str
    state: TransactionState
    artifact_hash: str
    created_at: str
    updated_at: str
    event_sequence: int
    last_event_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact_hash": self.artifact_hash,
            "created_at": self.created_at,
            "event_sequence": self.event_sequence,
            "last_event_hash": self.last_event_hash,
            "schema_version": TRANSACTION_SCHEMA_VERSION,
            "state": self.state.value,
            "transaction_id": self.transaction_id,
            "updated_at": self.updated_at,
        }


def resolve_state_directory(state_dir: Path | None = None) -> Path:
    """Resolve an explicit :class:`Path` or ``WAAPI_SKILL_STATE_DIR``.

    An explicit path always wins.  Requiring a ``Path`` for that branch makes
    accidental use of a transaction id or other free-form string less likely.
    """

    if state_dir is not None:
        if not isinstance(state_dir, Path):
            raise TypeError("state_dir must be a pathlib.Path or None")
        candidate = state_dir
    else:
        configured = os.environ.get(STATE_DIRECTORY_ENV, "").strip()
        if not configured:
            raise StateDirectoryNotConfigured(
                f"Pass state_dir=Path(...) or set {STATE_DIRECTORY_ENV}."
            )
        candidate = Path(configured)
    return candidate.expanduser().resolve()


def validate_transaction_id(transaction_id: str) -> str:
    """Return a safe transaction id or raise :class:`UnsafeTransactionId`."""

    if not isinstance(transaction_id, str) or not _TRANSACTION_ID_PATTERN.fullmatch(transaction_id):
        raise UnsafeTransactionId(
            "transaction_id must be 1-128 characters, start with an ASCII "
            "letter or digit, and contain only ASCII letters, digits, '.', '_' or '-'"
        )
    return transaction_id


class TransactionStore:
    """Filesystem store for immutable previews, state, and JSONL events."""

    def __init__(self, state_dir: Path | None = None) -> None:
        self.state_dir = resolve_state_directory(state_dir)
        self.transactions_dir = self.state_dir / "transactions"
        self.locks_dir = self.state_dir / "locks"
        self._ensure_store_directories()

    def create_preview(self, transaction_id: str, artifact: Any) -> TransactionRecord:
        """Atomically create a transaction and its write-once preview."""

        transaction_id = validate_transaction_id(transaction_id)
        # Round-tripping freezes tuples and custom integer keys into the exact
        # JSON value that is persisted and later re-hashed.
        normalized_artifact = json.loads(canonical_json_bytes(artifact).decode("utf-8"))
        artifact_hash = canonical_sha256(normalized_artifact)
        created_at = _utc_now()
        preview = PreviewArtifact(
            transaction_id=transaction_id,
            artifact=normalized_artifact,
            artifact_hash=artifact_hash,
            created_at=created_at,
        )

        with self._transaction_lock(transaction_id):
            transaction_dir = self._transaction_dir(transaction_id)
            if _lexists(transaction_dir):
                raise PreviewAlreadyExists(
                    f"Preview for transaction {transaction_id!r} already exists and is immutable."
                )

            event = _build_event(
                transaction_id=transaction_id,
                sequence=1,
                event_type="preview_created",
                from_state=None,
                to_state=TransactionState.DRAFT,
                artifact_hash=artifact_hash,
                previous_event_hash="",
                details={},
                timestamp=created_at,
            )
            record = TransactionRecord(
                transaction_id=transaction_id,
                state=TransactionState.DRAFT,
                artifact_hash=artifact_hash,
                created_at=created_at,
                updated_at=created_at,
                event_sequence=1,
                last_event_hash=event["event_hash"],
            )
            self._commit_new_transaction(transaction_dir, preview, record, event)
            return record

    def load_preview(self, transaction_id: str) -> PreviewArtifact:
        """Load and re-hash an immutable preview before returning it."""

        transaction_id = validate_transaction_id(transaction_id)
        with self._transaction_lock(transaction_id):
            return self._load_preview_unlocked(transaction_id)

    def load(self, transaction_id: str) -> TransactionRecord:
        """Load integrity-checked state, repairing a journal-ahead state view."""

        transaction_id = validate_transaction_id(transaction_id)
        with self._transaction_lock(transaction_id):
            preview = self._load_preview_unlocked(transaction_id)
            return self._load_record_unlocked(transaction_id, preview, repair=True)

    def read_events(self, transaction_id: str) -> tuple[Mapping[str, Any], ...]:
        """Return the validated, hash-chained event journal."""

        transaction_id = validate_transaction_id(transaction_id)
        with self._transaction_lock(transaction_id):
            preview = self._load_preview_unlocked(transaction_id)
            events = self._read_events_unlocked(transaction_id, preview.artifact_hash)
            return tuple(events)

    def verify_artifact(self, transaction_id: str) -> str:
        """Recompute and return the preview artifact hash.

        A mismatch raises :class:`ArtifactIntegrityError`.
        """

        return self.load_preview(transaction_id).artifact_hash

    def transition(
        self,
        transaction_id: str,
        to_state: TransactionState | str,
        *,
        expected_state: TransactionState | str | None = None,
        expected_artifact_hash: str | None = None,
        event_type: str = "state_transition",
        details: Mapping[str, Any] | None = None,
    ) -> TransactionRecord:
        """Apply one legal, integrity-checked, journaled state transition."""

        transaction_id = validate_transaction_id(transaction_id)
        target = _coerce_state(to_state, field="to_state")
        expected = None if expected_state is None else _coerce_state(expected_state, field="expected_state")
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("event_type must be a non-empty string")
        normalized_details = json.loads(canonical_json_bytes(dict(details or {})).decode("utf-8"))
        if expected_artifact_hash is not None and not isinstance(expected_artifact_hash, str):
            raise TypeError("expected_artifact_hash must be a string or None")

        with self._transaction_lock(transaction_id):
            preview = self._load_preview_unlocked(transaction_id)
            record = self._load_record_unlocked(transaction_id, preview, repair=True)
            if expected is not None and record.state is not expected:
                raise StateConflict(
                    f"Transaction {transaction_id!r} is {record.state.value!r}; "
                    f"caller expected {expected.value!r}."
                )
            if expected_artifact_hash is not None and not hmac.compare_digest(
                preview.artifact_hash, expected_artifact_hash
            ):
                raise ArtifactIntegrityError(
                    "The supplied artifact hash does not match the immutable preview; re-preview is required."
                )
            if target not in ALLOWED_TRANSITIONS[record.state]:
                allowed = sorted(state.value for state in ALLOWED_TRANSITIONS[record.state])
                suffix = f" Allowed: {', '.join(allowed)}." if allowed else " This state is terminal."
                raise InvalidTransition(
                    f"Illegal transaction transition {record.state.value!r} -> {target.value!r}.{suffix}"
                )

            timestamp = _utc_now()
            event = _build_event(
                transaction_id=transaction_id,
                sequence=record.event_sequence + 1,
                event_type=event_type.strip(),
                from_state=record.state,
                to_state=target,
                artifact_hash=preview.artifact_hash,
                previous_event_hash=record.last_event_hash,
                details=normalized_details,
                timestamp=timestamp,
            )
            updated = TransactionRecord(
                transaction_id=transaction_id,
                state=target,
                artifact_hash=preview.artifact_hash,
                created_at=record.created_at,
                updated_at=timestamp,
                event_sequence=event["sequence"],
                last_event_hash=event["event_hash"],
            )

            # The append-only journal is the source of truth.  If a process dies
            # after fsync here but before state.json is replaced, the next load
            # repairs the materialized state from the validated final event.
            self._append_event(self._events_path(transaction_id), event)
            _atomic_write_json(self._state_path(transaction_id), updated.as_dict())
            return updated

    def submit_for_confirmation(self, transaction_id: str) -> TransactionRecord:
        return self.transition(
            transaction_id,
            TransactionState.AWAITING_CONFIRMATION,
            expected_state=TransactionState.DRAFT,
            event_type="confirmation_requested",
        )

    def confirm(self, transaction_id: str, *, artifact_hash: str) -> TransactionRecord:
        """Confirm exactly the preview identified by *artifact_hash*."""

        if not isinstance(artifact_hash, str) or not artifact_hash:
            raise ValueError("artifact_hash must be a non-empty string")
        return self.transition(
            transaction_id,
            TransactionState.CONFIRMED,
            expected_state=TransactionState.AWAITING_CONFIRMATION,
            expected_artifact_hash=artifact_hash,
            event_type="confirmed",
        )

    def reject(self, transaction_id: str, *, details: Mapping[str, Any] | None = None) -> TransactionRecord:
        return self.transition(
            transaction_id,
            TransactionState.REJECTED,
            expected_state=TransactionState.AWAITING_CONFIRMATION,
            event_type="rejected",
            details=details,
        )

    def begin_execution(self, transaction_id: str) -> TransactionRecord:
        return self.transition(
            transaction_id,
            TransactionState.EXECUTING,
            expected_state=TransactionState.CONFIRMED,
            event_type="execution_started",
        )

    def mark_executed_unverified(
        self, transaction_id: str, *, details: Mapping[str, Any] | None = None
    ) -> TransactionRecord:
        return self.transition(
            transaction_id,
            TransactionState.EXECUTED_UNVERIFIED,
            expected_state=TransactionState.EXECUTING,
            event_type="execution_completed",
            details=details,
        )

    def record_verification(
        self,
        transaction_id: str,
        outcome: TransactionState | str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> TransactionRecord:
        target = _coerce_state(outcome, field="outcome")
        allowed = {
            TransactionState.VERIFIED,
            TransactionState.VERIFICATION_FAILED,
            TransactionState.INDETERMINATE,
            TransactionState.REPREVIEW_REQUIRED,
        }
        if target not in allowed:
            raise InvalidTransition(
                "verification outcome must be verified, verification_failed, indeterminate, or repreview_required"
            )
        return self.transition(
            transaction_id,
            target,
            expected_state=TransactionState.EXECUTED_UNVERIFIED,
            event_type="verification_recorded",
            details=details,
        )

    def mark_execution_indeterminate(
        self, transaction_id: str, *, details: Mapping[str, Any] | None = None
    ) -> TransactionRecord:
        return self.transition(
            transaction_id,
            TransactionState.INDETERMINATE,
            expected_state=TransactionState.EXECUTING,
            event_type="execution_indeterminate",
            details=details,
        )

    def require_repreview(
        self, transaction_id: str, *, details: Mapping[str, Any] | None = None
    ) -> TransactionRecord:
        return self.transition(
            transaction_id,
            TransactionState.REPREVIEW_REQUIRED,
            expected_state=TransactionState.CONFIRMED,
            event_type="repreview_required",
            details=details,
        )

    def _ensure_store_directories(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        for directory in (self.transactions_dir, self.locks_dir):
            if directory.is_symlink():
                raise StateCorruptionError(f"Store directory cannot be a symlink: {directory}")
            directory.mkdir(mode=0o700, parents=False, exist_ok=True)

    @contextmanager
    def _transaction_lock(self, transaction_id: str) -> Iterator[None]:
        if os.name == "nt" or _fcntl is None:
            raise FileLockUnavailable(
                "TransactionStore cross-process locking requires fcntl.flock on macOS/Linux. "
                "Windows needs a separate lock backend and is intentionally not run unlocked."
            )
        lock_path = self.locks_dir / f"{transaction_id}.lock"
        if lock_path.is_symlink():
            raise StateCorruptionError(f"Transaction lock cannot be a symlink: {lock_path}")
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(lock_path, flags, 0o600)
        handle = os.fdopen(fd, "a+b", closefd=True)
        try:
            _fcntl.flock(handle.fileno(), _fcntl.LOCK_EX)
            yield
        finally:
            try:
                _fcntl.flock(handle.fileno(), _fcntl.LOCK_UN)
            finally:
                handle.close()

    def _transaction_dir(self, transaction_id: str) -> Path:
        path = self.transactions_dir / transaction_id
        if path.is_symlink():
            raise StateCorruptionError(f"Transaction directory cannot be a symlink: {path}")
        return path

    def _preview_path(self, transaction_id: str) -> Path:
        return self._transaction_dir(transaction_id) / "preview.json"

    def _state_path(self, transaction_id: str) -> Path:
        return self._transaction_dir(transaction_id) / "state.json"

    def _events_path(self, transaction_id: str) -> Path:
        return self._transaction_dir(transaction_id) / "events.jsonl"

    def _commit_new_transaction(
        self,
        transaction_dir: Path,
        preview: PreviewArtifact,
        record: TransactionRecord,
        event: Mapping[str, Any],
    ) -> None:
        staging = self.transactions_dir / f".{transaction_dir.name}.{uuid.uuid4().hex}.tmp"
        staging.mkdir(mode=0o700)
        try:
            _atomic_write_json(staging / "preview.json", preview.as_dict())
            _atomic_write_json(staging / "state.json", record.as_dict())
            self._append_event(staging / "events.jsonl", event)
            os.replace(staging, transaction_dir)
            _fsync_directory(self.transactions_dir)
        except BaseException:
            if _lexists(staging):
                shutil.rmtree(staging, ignore_errors=True)
            raise

    def _load_preview_unlocked(self, transaction_id: str) -> PreviewArtifact:
        path = self._preview_path(transaction_id)
        payload = _read_json_object(path, transaction_id)
        if payload.get("schema_version") != TRANSACTION_SCHEMA_VERSION:
            raise StateCorruptionError(f"Unsupported preview schema in {path}")
        if payload.get("transaction_id") != transaction_id:
            raise ArtifactIntegrityError(f"Preview transaction id mismatch in {path}")
        if "artifact" not in payload or not isinstance(payload.get("artifact_hash"), str):
            raise StateCorruptionError(f"Preview artifact fields are missing in {path}")
        calculated_hash = canonical_sha256(payload["artifact"])
        stored_hash = payload["artifact_hash"]
        if not hmac.compare_digest(calculated_hash, stored_hash):
            raise ArtifactIntegrityError(
                f"Preview artifact hash mismatch for {transaction_id!r}: expected {stored_hash}, got {calculated_hash}"
            )
        created_at = payload.get("created_at")
        if not isinstance(created_at, str) or not created_at:
            raise StateCorruptionError(f"Preview created_at is missing in {path}")
        return PreviewArtifact(
            transaction_id=transaction_id,
            artifact=payload["artifact"],
            artifact_hash=stored_hash,
            created_at=created_at,
        )

    def _load_record_unlocked(
        self,
        transaction_id: str,
        preview: PreviewArtifact,
        *,
        repair: bool,
    ) -> TransactionRecord:
        payload = _read_json_object(self._state_path(transaction_id), transaction_id)
        record = _record_from_payload(payload, transaction_id)
        if not hmac.compare_digest(record.artifact_hash, preview.artifact_hash):
            raise ArtifactIntegrityError(
                f"State artifact hash does not match preview for transaction {transaction_id!r}"
            )
        events = self._read_events_unlocked(transaction_id, preview.artifact_hash)
        if not events:
            raise StateCorruptionError(f"Transaction {transaction_id!r} has no creation event")
        last = events[-1]
        if record.event_sequence > last["sequence"]:
            raise StateCorruptionError(
                f"State sequence is ahead of the event journal for transaction {transaction_id!r}"
            )
        if record.event_sequence < last["sequence"]:
            if not repair:
                raise StateCorruptionError(
                    f"State sequence is behind the event journal for transaction {transaction_id!r}"
                )
            state_at_record = events[record.event_sequence - 1]
            if (
                state_at_record["to_state"] != record.state.value
                or state_at_record["event_hash"] != record.last_event_hash
            ):
                raise StateCorruptionError(
                    f"State cannot be safely replayed from the event journal for transaction {transaction_id!r}"
                )
            record = TransactionRecord(
                transaction_id=transaction_id,
                state=_coerce_state(last["to_state"], field="event.to_state"),
                artifact_hash=preview.artifact_hash,
                created_at=record.created_at,
                updated_at=last["timestamp"],
                event_sequence=last["sequence"],
                last_event_hash=last["event_hash"],
            )
            _atomic_write_json(self._state_path(transaction_id), record.as_dict())
        elif record.state.value != last["to_state"] or record.last_event_hash != last["event_hash"]:
            raise StateCorruptionError(
                f"State does not match the final event for transaction {transaction_id!r}"
            )
        return record

    def _read_events_unlocked(self, transaction_id: str, artifact_hash: str) -> list[dict[str, Any]]:
        path = self._events_path(transaction_id)
        if not path.is_file():
            raise TransactionNotFound(f"Transaction {transaction_id!r} does not exist or has no events")
        events: list[dict[str, Any]] = []
        previous_event_hash = ""
        previous_state: str | None = None
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            raise TransactionError(f"Could not read transaction events from {path}: {error}") from error
        for line_number, line in enumerate(lines, start=1):
            if not line:
                raise StateCorruptionError(f"Blank event at {path}:{line_number}")
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                raise StateCorruptionError(f"Invalid event JSON at {path}:{line_number}: {error}") from error
            if not isinstance(event, dict):
                raise StateCorruptionError(f"Event must be an object at {path}:{line_number}")
            _validate_event(
                event,
                transaction_id=transaction_id,
                artifact_hash=artifact_hash,
                expected_sequence=line_number,
                expected_previous_hash=previous_event_hash,
                expected_from_state=previous_state,
                path=path,
            )
            events.append(event)
            previous_event_hash = event["event_hash"]
            previous_state = event["to_state"]
        return events

    @staticmethod
    def _append_event(path: Path, event: Mapping[str, Any]) -> None:
        payload = canonical_json_bytes(event) + b"\n"
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        fd = os.open(path, flags, 0o600)
        try:
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)


def _record_from_payload(payload: Mapping[str, Any], transaction_id: str) -> TransactionRecord:
    if payload.get("schema_version") != TRANSACTION_SCHEMA_VERSION:
        raise StateCorruptionError("Unsupported transaction state schema")
    if payload.get("transaction_id") != transaction_id:
        raise StateCorruptionError("Transaction state id does not match its directory")
    try:
        state = _coerce_state(payload.get("state"), field="state")
    except InvalidTransition as error:
        raise StateCorruptionError(str(error)) from error
    artifact_hash = payload.get("artifact_hash")
    created_at = payload.get("created_at")
    updated_at = payload.get("updated_at")
    event_sequence = payload.get("event_sequence")
    last_event_hash = payload.get("last_event_hash")
    if not isinstance(artifact_hash, str) or not artifact_hash:
        raise StateCorruptionError("Transaction state artifact_hash is missing")
    if not isinstance(created_at, str) or not created_at:
        raise StateCorruptionError("Transaction state created_at is missing")
    if not isinstance(updated_at, str) or not updated_at:
        raise StateCorruptionError("Transaction state updated_at is missing")
    if isinstance(event_sequence, bool) or not isinstance(event_sequence, int) or event_sequence < 1:
        raise StateCorruptionError("Transaction state event_sequence must be a positive integer")
    if not isinstance(last_event_hash, str) or not last_event_hash:
        raise StateCorruptionError("Transaction state last_event_hash is missing")
    return TransactionRecord(
        transaction_id=transaction_id,
        state=state,
        artifact_hash=artifact_hash,
        created_at=created_at,
        updated_at=updated_at,
        event_sequence=event_sequence,
        last_event_hash=last_event_hash,
    )


def _build_event(
    *,
    transaction_id: str,
    sequence: int,
    event_type: str,
    from_state: TransactionState | None,
    to_state: TransactionState,
    artifact_hash: str,
    previous_event_hash: str,
    details: Mapping[str, Any],
    timestamp: str,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "artifact_hash": artifact_hash,
        "details": dict(details),
        "event_type": event_type,
        "from_state": None if from_state is None else from_state.value,
        "previous_event_hash": previous_event_hash,
        "sequence": sequence,
        "timestamp": timestamp,
        "to_state": to_state.value,
        "transaction_id": transaction_id,
    }
    event["event_hash"] = canonical_sha256(event)
    return event


def _validate_event(
    event: Mapping[str, Any],
    *,
    transaction_id: str,
    artifact_hash: str,
    expected_sequence: int,
    expected_previous_hash: str,
    expected_from_state: str | None,
    path: Path,
) -> None:
    location = f"{path}:{expected_sequence}"
    if event.get("sequence") != expected_sequence:
        raise StateCorruptionError(f"Non-contiguous event sequence at {location}")
    if event.get("transaction_id") != transaction_id:
        raise StateCorruptionError(f"Event transaction id mismatch at {location}")
    if event.get("artifact_hash") != artifact_hash:
        raise ArtifactIntegrityError(f"Event artifact hash mismatch at {location}")
    if event.get("previous_event_hash") != expected_previous_hash:
        raise StateCorruptionError(f"Broken event hash chain at {location}")
    if event.get("from_state") != expected_from_state:
        raise StateCorruptionError(f"Broken event state chain at {location}")
    try:
        _coerce_state(event.get("to_state"), field="event.to_state")
    except InvalidTransition as error:
        raise StateCorruptionError(f"{error} at {location}") from error
    if not isinstance(event.get("event_type"), str) or not event["event_type"]:
        raise StateCorruptionError(f"Event type is missing at {location}")
    if not isinstance(event.get("timestamp"), str) or not event["timestamp"]:
        raise StateCorruptionError(f"Event timestamp is missing at {location}")
    if not isinstance(event.get("details"), dict):
        raise StateCorruptionError(f"Event details must be an object at {location}")
    stored_event_hash = event.get("event_hash")
    if not isinstance(stored_event_hash, str) or not stored_event_hash:
        raise StateCorruptionError(f"Event hash is missing at {location}")
    hash_payload = dict(event)
    del hash_payload["event_hash"]
    calculated_event_hash = canonical_sha256(hash_payload)
    if not hmac.compare_digest(stored_event_hash, calculated_event_hash):
        raise StateCorruptionError(f"Event hash mismatch at {location}")


def _coerce_state(value: TransactionState | str | Any, *, field: str) -> TransactionState:
    try:
        return value if isinstance(value, TransactionState) else TransactionState(value)
    except (TypeError, ValueError) as error:
        raise InvalidTransition(f"{field} is not a recognized transaction state: {value!r}") from error


def _read_json_object(path: Path, transaction_id: str) -> dict[str, Any]:
    if not path.is_file():
        raise TransactionNotFound(f"Transaction {transaction_id!r} does not exist or is incomplete")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise StateCorruptionError(f"Could not read durable JSON from {path}: {error}") from error
    if not isinstance(payload, dict):
        raise StateCorruptionError(f"Durable JSON must be an object: {path}")
    return payload


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    data = canonical_json_bytes(payload) + b"\n"
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(temporary, flags, 0o600)
    try:
        handle = os.fdopen(fd, "wb", closefd=True)
        fd = -1
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if fd >= 0:
            os.close(fd)
        if _lexists(temporary):
            temporary.unlink()


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        fd = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        # Some filesystems do not support directory fsync; file fsync and atomic
        # replace still provide the strongest available local guarantee.
        pass
    finally:
        os.close(fd)


def _lexists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
