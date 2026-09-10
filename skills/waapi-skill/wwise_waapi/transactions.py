"""Durable, WAAPI-independent transaction preview artifacts.

The store implements the local half of a preview -> authorize/confirm ->
execute -> verify protocol.  It never imports a WAAPI client and never performs
a Wwise operation.  A preview is immutable and explicit confirmation is bound
to its canonical SHA-256 hash; policy authorization is recorded as a distinct
durable state and journal event.

Concurrency support intentionally has a clear platform boundary: macOS and
Linux use ``fcntl.flock`` while Windows uses a one-byte ``msvcrt.locking``
region.  Unknown platforms and unavailable backends fail closed rather than
silently running without a cross-process lock.
"""

from __future__ import annotations

import errno
import hmac
import json
import os
import re
import secrets
import shutil
import stat
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from .canonical import canonical_json_bytes, canonical_sha256
from .filesystem_security import path_is_link_or_reparse

try:  # pragma: no branch - the absence is exercised by an explicit test hook.
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - exercised on Windows, not POSIX CI.
    _fcntl = None

try:  # pragma: no branch - the absence is exercised by an explicit test hook.
    import msvcrt as _msvcrt
except ImportError:  # pragma: no cover - exercised on POSIX, not Windows CI.
    _msvcrt = None


STATE_DIRECTORY_ENV = "WAAPI_SKILL_STATE_DIR"
TRANSACTION_SCHEMA_VERSION = 2
CONFIRMATION_TOKEN_MATERIAL_CONTRACT = (
    "waapi-skill.confirmation-token-material/v1"
)
_TRANSACTION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_COMPACT_TRANSACTION_ID_PREFIX = "tx1-"
_CROCKFORD_BASE32_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"
_COMPACT_TRANSACTION_ID_RANDOM_BITS = 100
_COMPACT_TRANSACTION_ID_LENGTH = 20
_COMPACT_TRANSACTION_ID_PATTERN = re.compile(
    rf"^{re.escape(_COMPACT_TRANSACTION_ID_PREFIX)}"
    rf"[{_CROCKFORD_BASE32_ALPHABET}]{{{_COMPACT_TRANSACTION_ID_LENGTH}}}$"
)
_CONFIRMATION_TOKEN_PREFIX = "ct1-"
_CONFIRMATION_TOKEN_BITS = 120
_CONFIRMATION_TOKEN_LENGTH = 24
_CONFIRMATION_TOKEN_PATTERN = re.compile(
    rf"^{re.escape(_CONFIRMATION_TOKEN_PREFIX)}"
    rf"[{_CROCKFORD_BASE32_ALPHABET}]{{{_CONFIRMATION_TOKEN_LENGTH}}}$"
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_LOCK_REGION_BYTES = 1
_WINDOWS_LOCK_RETRY_SECONDS = 0.05
_WINDOWS_LOCK_VIOLATION = 33
_DURABLE_READ_CHUNK_BYTES = 1024 * 1024
MAX_TRANSACTION_ARCHIVE_FILE_BYTES = 8 * 1024 * 1024
MAX_TRANSACTION_ARCHIVE_EVENTS = 4096


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


class ConfirmationTokenMismatch(TransactionError, ValueError):
    """A confirmation token is malformed or does not bind current durable state."""


class StateCorruptionError(TransactionError):
    """Durable transaction metadata or its event journal is malformed."""


class TransactionRecreateRequired(TransactionError):
    """A pre-cutover durable transaction cannot execute under current contracts."""

    error_code = "TRANSACTION_RECREATE_REQUIRED"


class FileLockUnavailable(TransactionError):
    """No supported cross-process file-lock implementation is available."""


class TransactionExecutionInProgress(TransactionError):
    """Another process owns the long-lived command lease for a transaction."""


class _PosixFileLockBackend:
    """Exclusive whole-file advisory locking through ``fcntl.flock``."""

    def __init__(self, module: Any) -> None:
        self._module = module

    def acquire(self, handle: Any) -> None:
        try:
            self._module.flock(handle.fileno(), self._module.LOCK_EX)
        except OSError as exc:
            raise FileLockUnavailable(
                "TransactionStore could not acquire its POSIX fcntl.flock lock."
            ) from exc

    def try_acquire(self, handle: Any) -> bool:
        try:
            self._module.flock(
                handle.fileno(),
                self._module.LOCK_EX | self._module.LOCK_NB,
            )
        except BlockingIOError:
            return False
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                return False
            raise FileLockUnavailable(
                "TransactionStore could not acquire its POSIX fcntl.flock execution lease."
            ) from exc
        return True

    def release(self, handle: Any) -> None:
        try:
            self._module.flock(handle.fileno(), self._module.LOCK_UN)
        except OSError as exc:
            raise FileLockUnavailable(
                "TransactionStore could not release its POSIX fcntl.flock lock."
            ) from exc


class _WindowsFileLockBackend:
    """Exclusive one-byte Windows locking through ``msvcrt.locking``."""

    def __init__(self, module: Any) -> None:
        self._module = module

    @staticmethod
    def _seek_lock_region(handle: Any) -> None:
        try:
            handle.seek(0, os.SEEK_SET)
        except OSError as exc:
            raise FileLockUnavailable(
                "TransactionStore could not seek to its Windows lock region."
            ) from exc

    def acquire(self, handle: Any) -> None:
        while True:
            self._seek_lock_region(handle)
            try:
                self._module.locking(
                    handle.fileno(),
                    self._module.LK_NBLCK,
                    _LOCK_REGION_BYTES,
                )
            except OSError as exc:
                if _is_windows_lock_contention(exc):
                    time.sleep(_WINDOWS_LOCK_RETRY_SECONDS)
                    continue
                raise FileLockUnavailable(
                    "TransactionStore could not acquire its Windows msvcrt lock."
                ) from exc
            return

    def try_acquire(self, handle: Any) -> bool:
        self._seek_lock_region(handle)
        try:
            self._module.locking(
                handle.fileno(),
                self._module.LK_NBLCK,
                _LOCK_REGION_BYTES,
            )
        except OSError as exc:
            if _is_windows_lock_contention(exc):
                return False
            raise FileLockUnavailable(
                "TransactionStore could not acquire its Windows msvcrt execution lease."
            ) from exc
        return True

    def release(self, handle: Any) -> None:
        self._seek_lock_region(handle)
        try:
            self._module.locking(
                handle.fileno(),
                self._module.LK_UNLCK,
                _LOCK_REGION_BYTES,
            )
        except OSError as exc:
            raise FileLockUnavailable(
                "TransactionStore could not release its Windows msvcrt lock."
            ) from exc


def _is_windows_lock_contention(exc: OSError) -> bool:
    """Return whether one Windows lock error means another process owns it."""

    return exc.errno in {errno.EACCES, errno.EDEADLK} or (
        getattr(exc, "winerror", None) == _WINDOWS_LOCK_VIOLATION
    )


def _select_file_lock_backend(platform_name: str) -> Any:
    """Select one supported lock backend without permitting an unlocked path."""

    if platform_name == "posix":
        if _fcntl is None or any(
            not hasattr(_fcntl, attribute)
            for attribute in ("flock", "LOCK_EX", "LOCK_NB", "LOCK_UN")
        ):
            raise FileLockUnavailable(
                "TransactionStore requires fcntl.flock on macOS/Linux and will not run unlocked."
            )
        return _PosixFileLockBackend(_fcntl)
    if platform_name == "nt":
        if _msvcrt is None or any(
            not hasattr(_msvcrt, attribute)
            for attribute in ("locking", "LK_NBLCK", "LK_UNLCK")
        ):
            raise FileLockUnavailable(
                "TransactionStore requires msvcrt.locking on Windows and will not run unlocked."
            )
        return _WindowsFileLockBackend(_msvcrt)
    raise FileLockUnavailable(
        f"TransactionStore has no cross-process lock backend for os.name={platform_name!r}; "
        "it will not run unlocked."
    )


def _lock_platform_name() -> str:
    """Return the platform discriminator used only by the lock backend seam."""

    return os.name


class TransactionState(str, Enum):
    """Closed durable states for mutation transactions."""

    DRAFT = "draft"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    POLICY_AUTHORIZED = "policy_authorized"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    EXECUTING = "executing"
    EXECUTION_CANCELLED = "execution_cancelled"
    EXECUTION_FAILED = "execution_failed"
    EXECUTED_UNVERIFIED = "executed_unverified"
    RESULT_SCHEMA_CHECKED = "result_schema_checked"
    VERIFIED = "verified"
    VERIFICATION_FAILED = "verification_failed"
    INDETERMINATE = "indeterminate"
    REPREVIEW_REQUIRED = "repreview_required"


ALLOWED_TRANSITIONS: Mapping[TransactionState, frozenset[TransactionState]] = {
    TransactionState.DRAFT: frozenset(
        {
            TransactionState.AWAITING_CONFIRMATION,
            TransactionState.POLICY_AUTHORIZED,
        }
    ),
    TransactionState.AWAITING_CONFIRMATION: frozenset(
        {TransactionState.CONFIRMED, TransactionState.REJECTED}
    ),
    TransactionState.POLICY_AUTHORIZED: frozenset(
        {TransactionState.EXECUTING, TransactionState.REPREVIEW_REQUIRED}
    ),
    TransactionState.CONFIRMED: frozenset(
        {TransactionState.EXECUTING, TransactionState.REPREVIEW_REQUIRED}
    ),
    TransactionState.REJECTED: frozenset(),
    TransactionState.EXECUTING: frozenset(
        {
            TransactionState.EXECUTION_CANCELLED,
            TransactionState.EXECUTION_FAILED,
            TransactionState.EXECUTED_UNVERIFIED,
            TransactionState.INDETERMINATE,
        }
    ),
    TransactionState.EXECUTION_CANCELLED: frozenset(),
    TransactionState.EXECUTION_FAILED: frozenset(),
    TransactionState.EXECUTED_UNVERIFIED: frozenset(
        {
            TransactionState.VERIFIED,
            TransactionState.RESULT_SCHEMA_CHECKED,
            TransactionState.VERIFICATION_FAILED,
            TransactionState.INDETERMINATE,
            TransactionState.REPREVIEW_REQUIRED,
        }
    ),
    TransactionState.VERIFIED: frozenset(),
    TransactionState.RESULT_SCHEMA_CHECKED: frozenset(),
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


@dataclass(slots=True, frozen=True)
class TransactionSnapshot:
    """One atomic integrity-checked view of preview, state, and journal."""

    preview: PreviewArtifact
    record: TransactionRecord
    events: tuple[Mapping[str, Any], ...]
    confirmation_token: str | None


def load_transaction_archive_snapshot(
    state_dir: Path,
    transaction_id: str,
) -> TransactionSnapshot:
    """Read one frozen transaction exactly, without creating or repairing state."""

    transaction_id = validate_transaction_id(transaction_id)
    root = resolve_state_directory(state_dir)
    transactions_dir = root / "transactions"
    transaction_dir = transactions_dir / transaction_id
    for path, label in (
        (root, "State directory"),
        (transactions_dir, "Transaction store directory"),
        (transaction_dir, "Transaction archive directory"),
    ):
        _require_plain_directory(path, label=label)
    try:
        names = {entry.name for entry in transaction_dir.iterdir()}
    except OSError as exc:
        raise StateCorruptionError(
            f"Transaction archive directory could not be read: {transaction_dir}: {exc}"
        ) from exc
    expected_names = {"preview.json", "state.json", "events.jsonl"}
    if names != expected_names:
        raise StateCorruptionError(
            f"Transaction archive files are invalid for {transaction_id!r}"
        )

    preview_path = transaction_dir / "preview.json"
    preview_payload, _preview_bytes = _read_canonical_archive_object(
        preview_path,
        label="Immutable transaction preview",
    )
    if set(preview_payload) != {
        "artifact",
        "artifact_hash",
        "created_at",
        "schema_version",
        "transaction_id",
    }:
        raise StateCorruptionError("Immutable transaction preview fields are invalid")
    if preview_payload.get("schema_version") != TRANSACTION_SCHEMA_VERSION:
        raise TransactionRecreateRequired(
            "This pre-cutover transaction Preview must be recreated through the typed Gateway."
        )
    if preview_payload.get("transaction_id") != transaction_id:
        raise ArtifactIntegrityError("Transaction preview id does not match its directory")
    artifact_hash = preview_payload.get("artifact_hash")
    if not isinstance(artifact_hash, str) or not _SHA256_PATTERN.fullmatch(artifact_hash):
        raise StateCorruptionError("Transaction preview artifact hash is invalid")
    if not hmac.compare_digest(
        artifact_hash,
        canonical_sha256(preview_payload.get("artifact")),
    ):
        raise ArtifactIntegrityError("Transaction preview artifact hash does not match")
    created_at = preview_payload.get("created_at")
    if not isinstance(created_at, str) or not created_at:
        raise StateCorruptionError("Transaction preview created_at is invalid")
    preview = PreviewArtifact(
        transaction_id=transaction_id,
        artifact=preview_payload["artifact"],
        artifact_hash=artifact_hash,
        created_at=created_at,
    )

    state_payload, _state_bytes = _read_canonical_archive_object(
        transaction_dir / "state.json",
        label="Materialized transaction state",
    )
    if set(state_payload) != {
        "artifact_hash",
        "created_at",
        "event_sequence",
        "last_event_hash",
        "schema_version",
        "state",
        "transaction_id",
        "updated_at",
    }:
        raise StateCorruptionError("Materialized transaction state fields are invalid")
    record = _record_from_payload(state_payload, transaction_id)
    if not hmac.compare_digest(record.artifact_hash, preview.artifact_hash):
        raise ArtifactIntegrityError("Transaction state artifact hash does not match preview")

    events_path = transaction_dir / "events.jsonl"
    events_bytes = _read_plain_regular_bytes_bounded(
        events_path,
        label="Transaction archive event journal",
        maximum_bytes=MAX_TRANSACTION_ARCHIVE_FILE_BYTES,
    )
    raw_lines = events_bytes.splitlines(keepends=True)
    if not raw_lines or len(raw_lines) > MAX_TRANSACTION_ARCHIVE_EVENTS:
        raise StateCorruptionError("Transaction archive event count is invalid")
    events: list[Mapping[str, Any]] = []
    previous_hash = ""
    previous_state: str | None = None
    expected_event_fields = {
        "artifact_hash",
        "details",
        "event_hash",
        "event_type",
        "from_state",
        "previous_event_hash",
        "sequence",
        "timestamp",
        "to_state",
        "transaction_id",
    }
    for sequence, raw_line in enumerate(raw_lines, start=1):
        if not raw_line.endswith(b"\n") or raw_line in {b"\n", b"\r\n"}:
            raise StateCorruptionError(
                f"Transaction archive event framing is invalid at {events_path}:{sequence}"
            )
        event_bytes = raw_line[:-1]
        try:
            event = json.loads(event_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
            raise StateCorruptionError(
                f"Transaction archive event JSON is invalid at {events_path}:{sequence}"
            ) from exc
        if not isinstance(event, dict) or set(event) != expected_event_fields:
            raise StateCorruptionError(
                f"Transaction archive event fields are invalid at {events_path}:{sequence}"
            )
        if event_bytes != canonical_json_bytes(event):
            raise StateCorruptionError(
                f"Transaction archive event is not canonical at {events_path}:{sequence}"
            )
        _validate_event(
            event,
            transaction_id=transaction_id,
            artifact_hash=artifact_hash,
            expected_sequence=sequence,
            expected_previous_hash=previous_hash,
            expected_from_state=previous_state,
            path=events_path,
        )
        to_state = _coerce_state(event["to_state"], field="event.to_state")
        if sequence == 1:
            if event["event_type"] != "preview_created" or to_state is not TransactionState.DRAFT:
                raise StateCorruptionError("Transaction archive creation event is invalid")
        else:
            from_state = _coerce_state(previous_state, field="event.from_state")
            if to_state not in ALLOWED_TRANSITIONS[from_state]:
                raise StateCorruptionError("Transaction archive contains an illegal transition")
        events.append(event)
        previous_hash = event["event_hash"]
        previous_state = event["to_state"]

    final_event = events[-1]
    first_event = events[0]
    if (
        record.created_at != preview.created_at
        or first_event["timestamp"] != preview.created_at
        or record.updated_at != final_event["timestamp"]
        or record.event_sequence != len(events)
        or record.last_event_hash != final_event["event_hash"]
        or record.state.value != final_event["to_state"]
    ):
        raise StateCorruptionError("Materialized transaction state does not match its journal")
    confirmation_token = (
        _confirmation_token_for_record(record, preview)
        if record.state is TransactionState.AWAITING_CONFIRMATION
        else None
    )
    return TransactionSnapshot(
        preview=preview,
        record=record,
        events=tuple(events),
        confirmation_token=confirmation_token,
    )


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
    # Keep the lexical path until the store has checked every existing parent.
    # `resolve()` would follow a Windows junction or POSIX symlink before the
    # write boundary had a chance to reject it.
    expanded = candidate.expanduser()
    absolute = expanded if expanded.is_absolute() else Path.cwd() / expanded
    if any(component == ".." for component in absolute.parts):
        raise StateCorruptionError(
            f"State directory must not contain parent traversal: {absolute}"
        )
    return absolute


def _encode_crockford(value: int, *, length: int) -> str:
    """Encode one non-negative integer into fixed-width lowercase Crockford."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("Crockford value must be a non-negative integer")
    if isinstance(length, bool) or not isinstance(length, int) or length < 1:
        raise ValueError("Crockford length must be a positive integer")
    if value >= 1 << (length * 5):
        raise ValueError("Crockford value does not fit the requested length")
    encoded = ["0"] * length
    for index in range(length - 1, -1, -1):
        encoded[index] = _CROCKFORD_BASE32_ALPHABET[value & 0x1F]
        value >>= 5
    return "".join(encoded)


def new_transaction_id() -> str:
    """Return a compact transaction id containing 100 random bits."""

    value = secrets.randbits(_COMPACT_TRANSACTION_ID_RANDOM_BITS)
    return (
        f"{_COMPACT_TRANSACTION_ID_PREFIX}"
        f"{_encode_crockford(value, length=_COMPACT_TRANSACTION_ID_LENGTH)}"
    )


def validate_transaction_id(transaction_id: str) -> str:
    """Return a safe compact or legacy transaction id."""

    if not isinstance(transaction_id, str):
        raise UnsafeTransactionId("transaction_id must be a string")
    if transaction_id.startswith(_COMPACT_TRANSACTION_ID_PREFIX):
        if not _COMPACT_TRANSACTION_ID_PATTERN.fullmatch(transaction_id):
            raise UnsafeTransactionId(
                "tx1 transaction_id must contain exactly 20 lowercase Crockford "
                "Base32 characters after 'tx1-'"
            )
        return transaction_id
    if not _TRANSACTION_ID_PATTERN.fullmatch(transaction_id):
        raise UnsafeTransactionId(
            "transaction_id must be 1-128 characters, start with an ASCII "
            "letter or digit, and contain only ASCII letters, digits, '.', '_' or '-'"
        )
    return transaction_id


def validate_confirmation_token(confirmation_token: str) -> str:
    """Return one strictly versioned 120-bit confirmation token."""

    if not isinstance(confirmation_token, str):
        raise ConfirmationTokenMismatch("confirmation_token must be a string")
    if not _CONFIRMATION_TOKEN_PATTERN.fullmatch(confirmation_token):
        raise ConfirmationTokenMismatch(
            "ct1 confirmation_token must contain exactly 24 lowercase Crockford "
            "Base32 characters after 'ct1-'"
        )
    return confirmation_token


def confirmation_token_for(
    *,
    transaction_id: str,
    artifact_hash: str,
    state: TransactionState | str,
    event_sequence: int,
    last_event_hash: str,
) -> str:
    """Derive the public short handle for one exact confirmation-state head."""

    transaction_id = validate_transaction_id(transaction_id)
    normalized_state = _coerce_state(state, field="state")
    if normalized_state is not TransactionState.AWAITING_CONFIRMATION:
        raise StateConflict(
            "A confirmation token exists only while a transaction is awaiting confirmation."
        )
    if not isinstance(artifact_hash, str) or not _SHA256_PATTERN.fullmatch(
        artifact_hash
    ):
        raise ValueError("artifact_hash must be exactly 64 lowercase hexadecimal characters")
    if (
        isinstance(event_sequence, bool)
        or not isinstance(event_sequence, int)
        or event_sequence < 1
    ):
        raise ValueError("event_sequence must be a positive integer")
    if not isinstance(last_event_hash, str) or not _SHA256_PATTERN.fullmatch(
        last_event_hash
    ):
        raise ValueError(
            "last_event_hash must be exactly 64 lowercase hexadecimal characters"
        )
    material = {
        "contract": CONFIRMATION_TOKEN_MATERIAL_CONTRACT,
        "transaction_id": transaction_id,
        "artifact_hash": artifact_hash,
        "state": normalized_state.value,
        "event_sequence": event_sequence,
        "last_event_hash": last_event_hash,
    }
    digest_prefix = canonical_sha256(material)[: _CONFIRMATION_TOKEN_BITS // 4]
    encoded = _encode_crockford(
        int(digest_prefix, 16),
        length=_CONFIRMATION_TOKEN_LENGTH,
    )
    return f"{_CONFIRMATION_TOKEN_PREFIX}{encoded}"


def _confirmation_token_for_record(
    record: TransactionRecord,
    preview: PreviewArtifact,
) -> str:
    if record.transaction_id != preview.transaction_id:
        raise ArtifactIntegrityError(
            "Transaction state and immutable preview identify different transactions."
        )
    if not hmac.compare_digest(record.artifact_hash, preview.artifact_hash):
        raise ArtifactIntegrityError(
            "Transaction state artifact hash does not match the immutable preview."
        )
    return confirmation_token_for(
        transaction_id=record.transaction_id,
        artifact_hash=preview.artifact_hash,
        state=record.state,
        event_sequence=record.event_sequence,
        last_event_hash=record.last_event_hash,
    )


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

    def load_snapshot(self, transaction_id: str) -> TransactionSnapshot:
        """Load one atomic integrity-checked view and its state-scoped token."""

        transaction_id = validate_transaction_id(transaction_id)
        with self._transaction_lock(transaction_id):
            preview = self._load_preview_unlocked(transaction_id)
            record = self._load_record_unlocked(
                transaction_id,
                preview,
                repair=True,
            )
            events = tuple(
                self._read_events_unlocked(transaction_id, preview.artifact_hash)
            )
            confirmation_token = (
                _confirmation_token_for_record(record, preview)
                if record.state is TransactionState.AWAITING_CONFIRMATION
                else None
            )
            return TransactionSnapshot(
                preview=preview,
                record=record,
                events=events,
                confirmation_token=confirmation_token,
            )

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
        expected_confirmation_token: str | None = None,
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
        if (
            expected_artifact_hash is not None
            and expected_confirmation_token is not None
        ):
            raise ValueError(
                "expected_artifact_hash and expected_confirmation_token are mutually exclusive"
            )
        if expected_confirmation_token is not None:
            expected_confirmation_token = validate_confirmation_token(
                expected_confirmation_token
            )

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
            if expected_confirmation_token is not None:
                current_confirmation_token = _confirmation_token_for_record(
                    record,
                    preview,
                )
                if not hmac.compare_digest(
                    current_confirmation_token,
                    expected_confirmation_token,
                ):
                    raise ConfirmationTokenMismatch(
                        "The supplied confirmation token does not match the current "
                        "immutable preview and transaction state."
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

    def authorize_by_policy(
        self,
        transaction_id: str,
        *,
        policy: str,
        authority: str,
    ) -> TransactionRecord:
        """Record a policy grant without misrepresenting it as confirmation."""

        policy = _validate_non_empty_string(policy, field="policy")
        authority = _validate_non_empty_string(authority, field="authority")
        return self.transition(
            transaction_id,
            TransactionState.POLICY_AUTHORIZED,
            expected_state=TransactionState.DRAFT,
            event_type="policy_authorized",
            details={
                "policy": policy,
                "authority": authority,
                "explicit_confirmation": False,
            },
        )

    def confirm(
        self,
        transaction_id: str,
        *,
        confirmation_token: str | None = None,
        artifact_hash: str | None = None,
    ) -> TransactionRecord:
        """Confirm through the public token or an internal artifact-hash seam."""

        if (confirmation_token is None) == (artifact_hash is None):
            raise ValueError(
                "exactly one of confirmation_token or artifact_hash is required"
            )
        if confirmation_token is not None:
            confirmation_token = validate_confirmation_token(confirmation_token)
        if artifact_hash is not None and (
            not isinstance(artifact_hash, str) or not artifact_hash
        ):
            raise ValueError("artifact_hash must be a non-empty string")
        return self.transition(
            transaction_id,
            TransactionState.CONFIRMED,
            expected_state=TransactionState.AWAITING_CONFIRMATION,
            expected_artifact_hash=artifact_hash,
            expected_confirmation_token=confirmation_token,
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

    def begin_execution(
        self,
        transaction_id: str,
        *,
        expected_authorization: TransactionState | str,
    ) -> TransactionRecord:
        """Atomically execute from one explicitly declared authorization state."""

        expected = _coerce_authorization_state(expected_authorization)
        return self.transition(
            transaction_id,
            TransactionState.EXECUTING,
            expected_state=expected,
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

    def mark_execution_cancelled(
        self, transaction_id: str, *, details: Mapping[str, Any] | None = None
    ) -> TransactionRecord:
        """Record a successful same-session cancel without claiming rollback proof."""

        return self.transition(
            transaction_id,
            TransactionState.EXECUTION_CANCELLED,
            expected_state=TransactionState.EXECUTING,
            event_type="execution_cancelled",
            details=details,
        )

    def mark_execution_failed(
        self, transaction_id: str, *, details: Mapping[str, Any] | None = None
    ) -> TransactionRecord:
        """Record one explicit non-OK dispatch result as a terminal failure."""

        return self.transition(
            transaction_id,
            TransactionState.EXECUTION_FAILED,
            expected_state=TransactionState.EXECUTING,
            event_type="execution_failed",
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
            TransactionState.RESULT_SCHEMA_CHECKED,
            TransactionState.VERIFICATION_FAILED,
            TransactionState.INDETERMINATE,
            TransactionState.REPREVIEW_REQUIRED,
        }
        if target not in allowed:
            raise InvalidTransition(
                "verification outcome must be verified, result_schema_checked, verification_failed, "
                "indeterminate, or repreview_required"
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
        self,
        transaction_id: str,
        *,
        expected_authorization: TransactionState | str = TransactionState.CONFIRMED,
        details: Mapping[str, Any] | None = None,
    ) -> TransactionRecord:
        expected = _coerce_authorization_state(expected_authorization)
        return self.transition(
            transaction_id,
            TransactionState.REPREVIEW_REQUIRED,
            expected_state=expected,
            event_type="repreview_required",
            details=details,
        )

    def _ensure_store_directories(self) -> None:
        _ensure_plain_directory_tree(self.state_dir, label="State directory")
        for directory in (self.transactions_dir, self.locks_dir):
            _ensure_plain_directory_tree(directory, label="Store directory")

    @contextmanager
    def execution_lease(self, transaction_id: str) -> Iterator[None]:
        """Hold one non-blocking cross-process lease across a live command.

        The durable state lock protects each journal transition.  This separate
        lease protects the interval between ``execution_started`` and the
        terminal execution result, including the external WAAPI call.  An
        abandoned OS lock is released by process exit, so an acquired lease
        together with durable ``executing`` state is proof of a stale owner.
        """

        transaction_id = validate_transaction_id(transaction_id)
        backend = _select_file_lock_backend(_lock_platform_name())
        lock_path = self.locks_dir / f"{transaction_id}.execution.lock"
        if _lexists(lock_path):
            _require_plain_regular_file(lock_path, label="Transaction execution lease")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(lock_path, flags, 0o600)
        try:
            _require_opened_plain_regular_file(
                lock_path,
                descriptor=fd,
                label="Transaction execution lease",
            )
            handle = os.fdopen(fd, "r+b", buffering=0, closefd=True)
        except BaseException:
            os.close(fd)
            raise

        acquired = False
        body_error: BaseException | None = None
        try:
            acquired = backend.try_acquire(handle)
            if not acquired:
                raise TransactionExecutionInProgress(
                    f"Transaction {transaction_id!r} already has a command in progress."
                )
            try:
                yield
            except BaseException as exc:
                body_error = exc
                raise
        finally:
            cleanup_error: BaseException | None = None
            if acquired:
                try:
                    backend.release(handle)
                except BaseException as exc:
                    cleanup_error = exc
            try:
                handle.close()
            except BaseException as exc:
                if cleanup_error is None:
                    cleanup_error = exc
            if cleanup_error is not None and body_error is None:
                raise cleanup_error

    @contextmanager
    def _transaction_lock(self, transaction_id: str) -> Iterator[None]:
        backend = _select_file_lock_backend(_lock_platform_name())
        lock_path = self.locks_dir / f"{transaction_id}.lock"
        if _lexists(lock_path):
            _require_plain_regular_file(lock_path, label="Transaction lock")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(lock_path, flags, 0o600)
        try:
            _require_opened_plain_regular_file(
                lock_path,
                descriptor=fd,
                label="Transaction lock",
            )
            # Windows byte-range locks may extend beyond EOF.  Keep a newly
            # created lock file empty so concurrent first users do not write
            # byte zero before either one has acquired the lock protecting it.
            handle = os.fdopen(fd, "r+b", buffering=0, closefd=True)
        except BaseException:
            os.close(fd)
            raise

        acquired = False
        body_error: BaseException | None = None
        try:
            backend.acquire(handle)
            acquired = True
            try:
                yield
            except BaseException as exc:
                body_error = exc
                raise
        finally:
            cleanup_error: BaseException | None = None
            if acquired:
                try:
                    backend.release(handle)
                except BaseException as exc:
                    cleanup_error = exc
            try:
                handle.close()
            except BaseException as exc:
                if cleanup_error is None:
                    cleanup_error = exc
            # Closing the descriptor is the final OS-level release fallback.
            # Preserve a transaction-body failure instead of replacing it with
            # a secondary cleanup exception.
            if cleanup_error is not None and body_error is None:
                raise cleanup_error

    def _transaction_dir(self, transaction_id: str) -> Path:
        path = self.transactions_dir / transaction_id
        if _lexists(path):
            _require_plain_directory(path, label="Transaction directory")
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
            raise TransactionRecreateRequired(
                "This pre-cutover transaction Preview must be recreated through the typed Gateway."
            )
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
        if not _lexists(path):
            raise TransactionNotFound(f"Transaction {transaction_id!r} does not exist or has no events")
        events: list[dict[str, Any]] = []
        previous_event_hash = ""
        previous_state: str | None = None
        try:
            lines = _read_plain_regular_bytes(
                path,
                label="Transaction event journal",
            ).decode("utf-8").splitlines()
        except UnicodeDecodeError as error:
            raise StateCorruptionError(
                f"Could not decode transaction events from {path}: {error}"
            ) from error
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
        # Raw ``os.write`` calls inherit the descriptor's text/binary mode on
        # Windows.  Open the journal in binary mode so its hash-chained JSONL
        # representation always contains the exact canonical LF byte.
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_APPEND
            | getattr(os, "O_BINARY", 0)
        )
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if _lexists(path):
            _require_plain_regular_file(path, label="Transaction event journal")
        try:
            fd = os.open(path, flags, 0o600)
        except OSError as exc:
            raise StateCorruptionError(
                f"Transaction event journal could not be opened safely: {path}: {exc}"
            ) from exc
        try:
            _require_opened_plain_regular_file(
                path,
                descriptor=fd,
                label="Transaction event journal",
            )
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise TransactionError(
                        f"Transaction event journal write made no progress: {path}"
                    )
                view = view[written:]
            os.fsync(fd)
            _require_opened_plain_regular_file(
                path,
                descriptor=fd,
                label="Transaction event journal",
            )
        finally:
            os.close(fd)


def _record_from_payload(payload: Mapping[str, Any], transaction_id: str) -> TransactionRecord:
    if payload.get("schema_version") != TRANSACTION_SCHEMA_VERSION:
        raise TransactionRecreateRequired(
            "This pre-cutover transaction state must be recreated through the typed Gateway."
        )
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


def _coerce_authorization_state(
    value: TransactionState | str | Any,
) -> TransactionState:
    state = _coerce_state(value, field="expected_authorization")
    if state not in {
        TransactionState.CONFIRMED,
        TransactionState.POLICY_AUTHORIZED,
    }:
        raise InvalidTransition(
            "expected_authorization must be 'confirmed' or 'policy_authorized'"
        )
    return state


def _validate_non_empty_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    if not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _read_json_object(path: Path, transaction_id: str) -> dict[str, Any]:
    if not _lexists(path):
        raise TransactionNotFound(f"Transaction {transaction_id!r} does not exist or is incomplete")
    try:
        payload = json.loads(
            _read_plain_regular_bytes(path, label="Durable transaction JSON").decode(
                "utf-8"
            )
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise StateCorruptionError(f"Could not read durable JSON from {path}: {error}") from error
    if not isinstance(payload, dict):
        raise StateCorruptionError(f"Durable JSON must be an object: {path}")
    return payload


def _read_plain_regular_bytes(path: Path, *, label: str) -> bytes:
    """Read one durable file without following or racing a path redirect."""

    _require_plain_regular_file(path, label=label)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise StateCorruptionError(
            f"{label} could not be opened safely: {path}: {exc}"
        ) from exc
    try:
        _require_opened_plain_regular_file(
            path,
            descriptor=descriptor,
            label=label,
        )
        before = os.fstat(descriptor)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, _DURABLE_READ_CHUNK_BYTES)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if not _same_regular_file_snapshot(before, after):
            raise StateCorruptionError(f"{label} changed while it was read: {path}")
        _require_opened_plain_regular_file(
            path,
            descriptor=descriptor,
            label=label,
        )
        return b"".join(chunks)
    except OSError as exc:
        raise StateCorruptionError(f"{label} could not be read: {path}: {exc}") from exc
    finally:
        os.close(descriptor)


def _read_plain_regular_bytes_bounded(
    path: Path,
    *,
    label: str,
    maximum_bytes: int,
) -> bytes:
    """Read one durable file through a descriptor with a hard byte ceiling."""

    if isinstance(maximum_bytes, bool) or not isinstance(maximum_bytes, int) or maximum_bytes < 1:
        raise ValueError("maximum_bytes must be a positive integer")
    _require_plain_regular_file(path, label=label)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise StateCorruptionError(
            f"{label} could not be opened safely: {path}: {exc}"
        ) from exc
    try:
        _require_opened_plain_regular_file(path, descriptor=descriptor, label=label)
        before = os.fstat(descriptor)
        if before.st_size > maximum_bytes:
            raise StateCorruptionError(f"{label} exceeds its fixed byte ceiling: {path}")
        chunks: list[bytes] = []
        remaining = maximum_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(_DURABLE_READ_CHUNK_BYTES, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > maximum_bytes:
            raise StateCorruptionError(f"{label} exceeds its fixed byte ceiling: {path}")
        after = os.fstat(descriptor)
        if not _same_regular_file_snapshot(before, after):
            raise StateCorruptionError(f"{label} changed while it was read: {path}")
        _require_opened_plain_regular_file(path, descriptor=descriptor, label=label)
        return data
    except OSError as exc:
        raise StateCorruptionError(f"{label} could not be read: {path}: {exc}") from exc
    finally:
        os.close(descriptor)


def _read_canonical_archive_object(
    path: Path,
    *,
    label: str,
) -> tuple[dict[str, Any], bytes]:
    data = _read_plain_regular_bytes_bounded(
        path,
        label=label,
        maximum_bytes=MAX_TRANSACTION_ARCHIVE_FILE_BYTES,
    )
    try:
        payload = json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
        raise StateCorruptionError(f"{label} is not strict JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise StateCorruptionError(f"{label} must be a JSON object: {path}")
    if data != canonical_json_bytes(payload) + b"\n":
        raise StateCorruptionError(f"{label} is not in canonical durable form: {path}")
    return payload, data


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


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    data = canonical_json_bytes(payload) + b"\n"
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
    )
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


def _ensure_plain_directory_tree(path: Path, *, label: str) -> None:
    """Create one directory tree without traversing a link/reparse component."""

    if not path.is_absolute():
        raise StateCorruptionError(f"{label} must be absolute: {path}")
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        if not _lexists(current):
            try:
                current.mkdir(mode=0o700, parents=False)
            except FileExistsError:
                # A concurrent creator won the race; attest what now exists.
                pass
            except OSError as exc:
                raise StateCorruptionError(
                    f"Could not create {label.lower()} component {current}: {exc}"
                ) from exc
        _require_plain_directory(current, label=label)


def _require_plain_directory(path: Path, *, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise StateCorruptionError(f"{label} is unavailable: {path}: {exc}") from exc
    if path_is_link_or_reparse(path, metadata=metadata):
        raise StateCorruptionError(
            f"{label} cannot be a link, junction, or reparse point: {path}"
        )
    if not stat.S_ISDIR(metadata.st_mode):
        raise StateCorruptionError(f"{label} must be a directory: {path}")


def _require_plain_regular_file(path: Path, *, label: str) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise StateCorruptionError(f"{label} is unavailable: {path}: {exc}") from exc
    if path_is_link_or_reparse(path, metadata=metadata):
        raise StateCorruptionError(
            f"{label} cannot be a link, junction, or reparse point: {path}"
        )
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise StateCorruptionError(
            f"{label} must be one non-hard-linked regular file: {path}"
        )
    return metadata


def _require_opened_plain_regular_file(
    path: Path,
    *,
    descriptor: int,
    label: str,
) -> None:
    path_metadata = _require_plain_regular_file(path, label=label)
    try:
        opened_metadata = os.fstat(descriptor)
    except OSError as exc:
        raise StateCorruptionError(
            f"Could not attest opened {label.lower()} {path}: {exc}"
        ) from exc
    if (
        not stat.S_ISREG(opened_metadata.st_mode)
        or opened_metadata.st_nlink != 1
        or not os.path.samestat(path_metadata, opened_metadata)
    ):
        raise StateCorruptionError(
            f"{label} path changed while it was being opened: {path}"
        )


def _lexists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
