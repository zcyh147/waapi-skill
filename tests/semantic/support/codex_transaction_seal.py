"""Runner-owned phase seals for preview/confirm Codex evaluations.

The fresh model used for phase B must not be able to substitute a different
transaction after phase A.  This module creates a compact, serializable seal
from the private transaction store and verifies that seal before, during, and
after the confirm/execute/verify sequence.

The production :class:`wwise_waapi.transactions.TransactionStore` remains the
authority for preview, state, and hash-chain integrity.  The seal adds runner-
owned byte and filesystem identity bindings which the production transaction
protocol deliberately does not persist (most importantly ``preview.json``
ctime, so write-then-restore is still observable).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from tests.semantic.support.codex_archive_paths import (
    ArchiveRelativePathError,
    parse_archive_relative_path,
)
from tests.semantic.support.codex_gateway_broker import (
    validate_transaction_show_confirmation_payload,
)
from tests.semantic.support.codex_filesystem_security import (
    binary_file_open_flags,
    path_is_link_or_reparse,
    same_regular_file_handle_snapshot,
    same_regular_file_path_handle_snapshot,
)
from wwise_waapi.canonical import canonical_json_bytes, canonical_sha256
from wwise_waapi.operation_registry import OperationContractError, parse_operation_request
from wwise_waapi.transaction_runtime import (
    PROJECT_GUARD_CONTRACT,
    RUNTIME_GUARD_CONTRACT,
    TRANSACTION_PREVIEW_CONTRACT,
)
from wwise_waapi.transactions import (
    ALLOWED_TRANSITIONS,
    TransactionError,
    TransactionRecord,
    TransactionState,
    TransactionStore,
    validate_transaction_id,
)


PREVIEW_SEAL_CONTRACT = "waapi-skill.codex-transaction-preview-seal/v1"
PREVIEW_SEAL_EVIDENCE_CONTRACT = "waapi-skill.codex-transaction-seal-evidence/v1"

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_PREVIEW_ENVELOPE_FIELDS = frozenset(
    {"artifact", "artifact_hash", "created_at", "schema_version", "transaction_id"}
)
_STATE_ENVELOPE_FIELDS = frozenset(
    {
        "artifact_hash",
        "created_at",
        "event_sequence",
        "last_event_hash",
        "schema_version",
        "state",
        "transaction_id",
        "updated_at",
    }
)
_EVENT_FIELDS = frozenset(
    {
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
)
_ARTIFACT_FIELDS = frozenset(
    {
        "contract",
        "request",
        "prepared_operation",
        "project_guard",
        "runtime_guard",
        "created_at",
        "expires_at",
        "execution_policy",
    }
)
_PROJECT_GUARD_FIELDS = frozenset(
    {"contract", "endpoint", "version", "wwise", "project", "fingerprint"}
)
_RUNTIME_GUARD_FIELDS = frozenset({"contract", "version", "files", "fingerprint"})
_EXECUTION_POLICY = {
    "requires_authorization": True,
    "accepted_authorization_modes": [
        "explicit_confirmation",
        "policy_authorization",
    ],
    "authorization_selected_at_preview": True,
    "automatic_retry_allowed": False,
    "revalidate_project_guard": True,
    "revalidate_runtime_guard": True,
    "revalidate_resolved_roles": True,
    "post_execution_verification_required": True,
}


class TransactionSealError(RuntimeError):
    """A transaction cannot be sealed or no longer matches its phase-A seal."""


@dataclass(frozen=True, slots=True)
class PreviewTransactionSeal:
    """Immutable phase-A binding passed to runner-owned phase-B orchestration."""

    contract: str
    state_directory: str
    transaction_id: str
    artifact_hash: str
    state: str
    preview_json_sha256: str
    preview_file_size: int
    preview_file_mode: int
    preview_file_ctime_ns: int
    preview_file_device: int
    preview_file_inode: int
    event_sequence: int
    last_event_hash: str
    events_jsonl_sha256: str
    events_file_size: int
    events_file_mode: int
    events_file_device: int
    events_file_inode: int
    project_guard_fingerprint: str
    runtime_guard_fingerprint: str
    request_canonical_sha256: str
    created_at: str
    expires_at: str

    def __post_init__(self) -> None:
        _validate_seal_values(self)

    def as_dict(self) -> dict[str, Any]:
        return {field: getattr(self, field) for field in _SEAL_FIELD_NAMES}

    def to_json(self) -> str:
        """Return canonical UTF-8-safe JSON for storage between fresh sessions."""

        return canonical_json_bytes(self.as_dict()).decode("utf-8")

    @classmethod
    def from_json(cls, payload: str | bytes | bytearray) -> "PreviewTransactionSeal":
        return parse_preview_seal(payload)


_SEAL_FIELD_NAMES = tuple(PreviewTransactionSeal.__dataclass_fields__)
_SEAL_FIELDS = frozenset(_SEAL_FIELD_NAMES)


@dataclass(frozen=True, slots=True)
class PreviewSealEvidence:
    """Current, integrity-checked state observed while verifying a seal."""

    contract: str
    transaction_id: str
    artifact_hash: str
    state: str
    event_sequence: int
    last_event_hash: str
    preview_json_sha256: str
    events_jsonl_sha256: str
    project_guard_fingerprint: str
    runtime_guard_fingerprint: str
    request_canonical_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": self.contract,
            "transaction_id": self.transaction_id,
            "artifact_hash": self.artifact_hash,
            "state": self.state,
            "event_sequence": self.event_sequence,
            "last_event_hash": self.last_event_hash,
            "preview_json_sha256": self.preview_json_sha256,
            "events_jsonl_sha256": self.events_jsonl_sha256,
            "project_guard_fingerprint": self.project_guard_fingerprint,
            "runtime_guard_fingerprint": self.runtime_guard_fingerprint,
            "request_canonical_sha256": self.request_canonical_sha256,
        }


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    path: Path
    data: bytes
    sha256: str
    size: int
    mode: int
    ctime_ns: int
    device: int
    inode: int


@dataclass(frozen=True, slots=True)
class _IntegritySnapshot:
    state_directory: Path
    record: TransactionRecord
    artifact: Mapping[str, Any]
    events: tuple[Mapping[str, Any], ...]
    preview_file: _FileSnapshot
    events_file: _FileSnapshot
    project_guard_fingerprint: str
    runtime_guard_fingerprint: str
    request_canonical_sha256: str
    created_at: str
    expires_at: str


def create_preview_seal(state_directory: Path, transaction_id: str) -> PreviewTransactionSeal:
    """Create a phase-A seal for an ``awaiting_confirmation`` transaction only."""

    snapshot = _load_integrity_snapshot(state_directory, transaction_id)
    if snapshot.record.state is not TransactionState.AWAITING_CONFIRMATION:
        raise TransactionSealError(
            "A preview seal can only be created in awaiting_confirmation; "
            f"transaction {transaction_id!r} is {snapshot.record.state.value!r}."
        )

    return PreviewTransactionSeal(
        contract=PREVIEW_SEAL_CONTRACT,
        state_directory=str(snapshot.state_directory),
        transaction_id=snapshot.record.transaction_id,
        artifact_hash=snapshot.record.artifact_hash,
        state=snapshot.record.state.value,
        preview_json_sha256=snapshot.preview_file.sha256,
        preview_file_size=snapshot.preview_file.size,
        preview_file_mode=snapshot.preview_file.mode,
        preview_file_ctime_ns=snapshot.preview_file.ctime_ns,
        preview_file_device=snapshot.preview_file.device,
        preview_file_inode=snapshot.preview_file.inode,
        event_sequence=snapshot.record.event_sequence,
        last_event_hash=snapshot.record.last_event_hash,
        events_jsonl_sha256=snapshot.events_file.sha256,
        events_file_size=snapshot.events_file.size,
        events_file_mode=snapshot.events_file.mode,
        events_file_device=snapshot.events_file.device,
        events_file_inode=snapshot.events_file.inode,
        project_guard_fingerprint=snapshot.project_guard_fingerprint,
        runtime_guard_fingerprint=snapshot.runtime_guard_fingerprint,
        request_canonical_sha256=snapshot.request_canonical_sha256,
        created_at=snapshot.created_at,
        expires_at=snapshot.expires_at,
    )


def verify_preview_seal(
    state_directory: Path,
    transaction_id: str,
    seal: PreviewTransactionSeal,
    *,
    allowed_states: Iterable[TransactionState | str],
) -> PreviewSealEvidence:
    """Verify immutable preview facts and an explicitly allowed current state.

    The event journal may only grow by valid state transitions.  Its exact
    phase-A byte prefix and file identity remain bound by the seal.
    """

    if not isinstance(seal, PreviewTransactionSeal):
        raise TransactionSealError("seal must be a PreviewTransactionSeal")
    expected_states = _coerce_allowed_states(allowed_states)
    supplied_id = _validated_transaction_id(transaction_id)
    if supplied_id != seal.transaction_id:
        raise TransactionSealError(
            f"Transaction id drift: seal binds {seal.transaction_id!r}, got {supplied_id!r}."
        )

    lexical_root = _absolute_lexical_path(state_directory)
    if str(lexical_root) != seal.state_directory:
        raise TransactionSealError(
            f"State-directory path drift: seal binds {seal.state_directory!r}, got {str(lexical_root)!r}."
        )
    snapshot = _load_integrity_snapshot(lexical_root, supplied_id)
    current = snapshot.record

    if current.state not in expected_states:
        allowed = ", ".join(sorted(state.value for state in expected_states))
        raise TransactionSealError(
            f"Transaction state {current.state.value!r} is not explicitly allowed; allowed: {allowed}."
        )

    _require_equal("artifact hash", seal.artifact_hash, current.artifact_hash)
    _require_equal("preview.json SHA-256", seal.preview_json_sha256, snapshot.preview_file.sha256)
    _require_equal("preview.json size", seal.preview_file_size, snapshot.preview_file.size)
    _require_equal("preview.json mode", seal.preview_file_mode, snapshot.preview_file.mode)
    _require_equal("preview.json ctime", seal.preview_file_ctime_ns, snapshot.preview_file.ctime_ns)
    _require_equal("preview.json device", seal.preview_file_device, snapshot.preview_file.device)
    _require_equal("preview.json inode", seal.preview_file_inode, snapshot.preview_file.inode)
    _require_equal(
        "project guard fingerprint",
        seal.project_guard_fingerprint,
        snapshot.project_guard_fingerprint,
    )
    _require_equal(
        "runtime guard fingerprint",
        seal.runtime_guard_fingerprint,
        snapshot.runtime_guard_fingerprint,
    )
    _require_equal(
        "request canonical SHA-256",
        seal.request_canonical_sha256,
        snapshot.request_canonical_sha256,
    )
    _require_equal("preview created_at", seal.created_at, snapshot.created_at)
    _require_equal("preview expires_at", seal.expires_at, snapshot.expires_at)

    _verify_journal_progression(seal, snapshot)
    return PreviewSealEvidence(
        contract=PREVIEW_SEAL_EVIDENCE_CONTRACT,
        transaction_id=current.transaction_id,
        artifact_hash=current.artifact_hash,
        state=current.state.value,
        event_sequence=current.event_sequence,
        last_event_hash=current.last_event_hash,
        preview_json_sha256=snapshot.preview_file.sha256,
        events_jsonl_sha256=snapshot.events_file.sha256,
        project_guard_fingerprint=snapshot.project_guard_fingerprint,
        runtime_guard_fingerprint=snapshot.runtime_guard_fingerprint,
        request_canonical_sha256=snapshot.request_canonical_sha256,
    )


def validate_transaction_show_confirmation_against_store(
    payload: Mapping[str, Any],
    state_directory: Path,
) -> dict[str, Any]:
    """Bind a complete show response to the production transaction journal.

    This works both while the transaction is awaiting confirmation and after
    later phases have extended the journal: the binding's event sequence must
    still identify the exact historical awaiting-confirmation event.
    """

    try:
        confirmation = validate_transaction_show_confirmation_payload(payload)
        transaction_id = str(payload["transaction_id"])
        artifact_hash = str(payload["artifact_hash"])
        binding = confirmation["binding"]
        event_sequence = int(binding["event_sequence"])
        last_event_hash = str(binding["last_event_hash"])
        store = TransactionStore(_absolute_lexical_path(state_directory))
        preview = store.load_preview(transaction_id)
        record = store.load(transaction_id)
        events = store.read_events(transaction_id)
    except (KeyError, TypeError, ValueError, TransactionError) as exc:
        raise TransactionSealError(
            f"Transaction-show confirmation cannot be bound to durable state: {exc}"
        ) from exc
    if (
        preview.transaction_id != transaction_id
        or preview.artifact_hash != artifact_hash
        or record.transaction_id != transaction_id
        or record.artifact_hash != artifact_hash
        or record.event_sequence < event_sequence
        or len(events) < event_sequence
    ):
        raise TransactionSealError(
            "Transaction-show confirmation differs from durable transaction identity."
        )
    event = events[event_sequence - 1]
    if (
        event.get("sequence") != event_sequence
        or event.get("event_hash") != last_event_hash
        or event.get("transaction_id") != transaction_id
        or event.get("artifact_hash") != artifact_hash
        or event.get("to_state") != TransactionState.AWAITING_CONFIRMATION.value
    ):
        raise TransactionSealError(
            "Transaction-show confirmation does not identify the durable "
            "awaiting-confirmation journal head."
        )
    return {
        "contract": str(confirmation["contract"]),
        "token": str(confirmation["token"]),
        "transaction_id": transaction_id,
        "artifact_hash": artifact_hash,
        "event_sequence": event_sequence,
        "last_event_hash": last_event_hash,
    }


def serialize_preview_seal(seal: PreviewTransactionSeal) -> str:
    if not isinstance(seal, PreviewTransactionSeal):
        raise TransactionSealError("seal must be a PreviewTransactionSeal")
    return seal.to_json()


def parse_preview_seal(payload: str | bytes | bytearray) -> PreviewTransactionSeal:
    """Parse a closed v1 seal; duplicate, missing, or unknown fields fail."""

    if isinstance(payload, bytearray):
        payload = bytes(payload)
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise TransactionSealError("Preview seal JSON must be valid UTF-8") from exc
    if not isinstance(payload, str):
        raise TransactionSealError("Preview seal JSON must be str or bytes")
    try:
        decoded = json.loads(
            payload,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise TransactionSealError(f"Invalid preview seal JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise TransactionSealError("Preview seal JSON must be an object")
    _require_exact_fields(decoded, _SEAL_FIELDS, context="preview seal")
    try:
        return PreviewTransactionSeal(**decoded)
    except TypeError as exc:
        raise TransactionSealError(f"Invalid preview seal fields: {exc}") from exc


def _load_integrity_snapshot(state_directory: Path, transaction_id: str) -> _IntegritySnapshot:
    transaction_id = _validated_transaction_id(transaction_id)
    root = _absolute_lexical_path(state_directory)
    _require_real_directory_tree(root)
    transactions_dir = root / "transactions"
    locks_dir = root / "locks"
    transaction_dir = transactions_dir / transaction_id
    for directory, label in (
        (transactions_dir, "transactions directory"),
        (locks_dir, "locks directory"),
        (transaction_dir, "transaction directory"),
    ):
        _require_plain_directory(directory, label=label)

    preview_path = transaction_dir / "preview.json"
    state_path = transaction_dir / "state.json"
    events_path = transaction_dir / "events.jsonl"
    for path, label in (
        (preview_path, "preview.json"),
        (state_path, "state.json"),
        (events_path, "events.jsonl"),
    ):
        _require_plain_file(path, label=label)

    try:
        store = TransactionStore(root)
        if store.state_dir != root:
            raise TransactionSealError(
                f"State-directory resolution drifted from {root} to {store.state_dir}."
            )
        first_record = store.load(transaction_id)
        preview = store.load_preview(transaction_id)
        events = store.read_events(transaction_id)
        second_record = store.load(transaction_id)
    except TransactionSealError:
        raise
    except (TransactionError, OSError, ValueError, TypeError) as exc:
        raise TransactionSealError(
            f"Production TransactionStore rejected transaction {transaction_id!r}: {exc}"
        ) from exc
    if first_record != second_record:
        raise TransactionSealError("Transaction changed while its integrity snapshot was being loaded")

    preview_file = _read_regular_file(preview_path, label="preview.json")
    state_file = _read_regular_file(state_path, label="state.json")
    events_file = _read_regular_file(events_path, label="events.jsonl")
    preview_payload = _decode_json_object(preview_file.data, context="preview.json")
    state_payload = _decode_json_object(state_file.data, context="state.json")
    event_payloads = _decode_json_lines(events_file.data, context="events.jsonl")

    _require_exact_fields(preview_payload, _PREVIEW_ENVELOPE_FIELDS, context="preview.json")
    _require_exact_fields(state_payload, _STATE_ENVELOPE_FIELDS, context="state.json")
    for index, event in enumerate(event_payloads, start=1):
        _require_exact_fields(event, _EVENT_FIELDS, context=f"events.jsonl line {index}")

    if preview_payload != preview.as_dict():
        raise TransactionSealError("preview.json changed after the production integrity load")
    if state_payload != second_record.as_dict():
        raise TransactionSealError("state.json changed after the production integrity load")
    if tuple(event_payloads) != tuple(events):
        raise TransactionSealError("events.jsonl changed after the production integrity load")
    if len(event_payloads) != second_record.event_sequence:
        raise TransactionSealError("Event count does not match the materialized event_sequence")
    _validate_legal_event_states(event_payloads)

    artifact = preview.artifact
    if not isinstance(artifact, Mapping):
        raise TransactionSealError("Transaction preview artifact must be an object")
    facts = _validate_artifact(artifact)
    return _IntegritySnapshot(
        state_directory=root,
        record=second_record,
        artifact=dict(artifact),
        events=tuple(events),
        preview_file=preview_file,
        events_file=events_file,
        project_guard_fingerprint=facts[0],
        runtime_guard_fingerprint=facts[1],
        request_canonical_sha256=facts[2],
        created_at=facts[3],
        expires_at=facts[4],
    )


def _validate_artifact(artifact: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    _require_exact_fields(artifact, _ARTIFACT_FIELDS, context="transaction preview artifact")
    if artifact.get("contract") != TRANSACTION_PREVIEW_CONTRACT:
        raise TransactionSealError("Unsupported transaction preview contract")
    if not isinstance(artifact.get("prepared_operation"), Mapping):
        raise TransactionSealError("Transaction preview prepared_operation must be an object")
    if artifact.get("execution_policy") != _EXECUTION_POLICY:
        raise TransactionSealError("Transaction preview execution_policy is missing or unsupported")

    request = artifact.get("request")
    project_guard = artifact.get("project_guard")
    runtime_guard = artifact.get("runtime_guard")
    if not isinstance(request, Mapping):
        raise TransactionSealError("Transaction preview request must be an object")
    if not isinstance(project_guard, Mapping) or not isinstance(runtime_guard, Mapping):
        raise TransactionSealError("Transaction preview project/runtime guards must be objects")

    project_fingerprint = _validate_guard(
        project_guard,
        contract=PROJECT_GUARD_CONTRACT,
        fields=_PROJECT_GUARD_FIELDS,
        body_fields=("endpoint", "version", "wwise", "project"),
        context="project_guard",
    )
    runtime_fingerprint = _validate_guard(
        runtime_guard,
        contract=RUNTIME_GUARD_CONTRACT,
        fields=_RUNTIME_GUARD_FIELDS,
        body_fields=("version", "files"),
        context="runtime_guard",
    )
    version = project_guard.get("version")
    if not isinstance(version, str) or runtime_guard.get("version") != version:
        raise TransactionSealError("Project/runtime guard versions do not match")
    try:
        parsed_request = parse_operation_request(request, expected_version=version)
    except OperationContractError as exc:
        raise TransactionSealError(f"Transaction preview request is invalid: {exc}") from exc

    created_at = _required_timestamp(artifact.get("created_at"), field="created_at")
    expires_at = _required_timestamp(artifact.get("expires_at"), field="expires_at")
    if _parse_timestamp(expires_at) <= _parse_timestamp(created_at):
        raise TransactionSealError("Transaction preview expires_at must be later than created_at")
    return (
        project_fingerprint,
        runtime_fingerprint,
        canonical_sha256(parsed_request.as_dict()),
        created_at,
        expires_at,
    )


def _validate_guard(
    guard: Mapping[str, Any],
    *,
    contract: str,
    fields: frozenset[str],
    body_fields: Sequence[str],
    context: str,
) -> str:
    _require_exact_fields(guard, fields, context=context)
    if guard.get("contract") != contract:
        raise TransactionSealError(f"Unsupported {context} contract")
    fingerprint = guard.get("fingerprint")
    _require_sha256(fingerprint, field=f"{context}.fingerprint")
    body = {field: guard.get(field) for field in body_fields}
    if not all(field in guard for field in body_fields):
        raise TransactionSealError(f"{context} body is incomplete")
    if canonical_sha256(body) != fingerprint:
        raise TransactionSealError(f"{context} fingerprint does not match its body")
    if context == "runtime_guard":
        files = guard.get("files")
        if not isinstance(files, Mapping) or not files:
            raise TransactionSealError("runtime_guard.files must be a non-empty object")
        for path, digest in files.items():
            try:
                relative = parse_archive_relative_path(path)
            except (ArchiveRelativePathError, TypeError) as exc:
                raise TransactionSealError(
                    "runtime_guard.files contains an unsafe relative path"
                ) from exc
            if relative.source_flavor != "posix" or relative.canonical != path:
                raise TransactionSealError(
                    "runtime_guard.files must use canonical POSIX relative paths"
                )
            _require_sha256(digest, field=f"runtime_guard.files[{path!r}]")
    return str(fingerprint)


def _verify_journal_progression(seal: PreviewTransactionSeal, snapshot: _IntegritySnapshot) -> None:
    record = snapshot.record
    events_file = snapshot.events_file
    _require_equal("events.jsonl mode", seal.events_file_mode, events_file.mode)
    _require_equal("events.jsonl device", seal.events_file_device, events_file.device)
    _require_equal("events.jsonl inode", seal.events_file_inode, events_file.inode)
    if record.event_sequence < seal.event_sequence:
        raise TransactionSealError("Event sequence moved backwards from the phase-A seal")
    if events_file.size < seal.events_file_size:
        raise TransactionSealError("events.jsonl was truncated after phase A")
    sealed_prefix = events_file.data[: seal.events_file_size]
    if hashlib.sha256(sealed_prefix).hexdigest() != seal.events_jsonl_sha256:
        raise TransactionSealError("The sealed events.jsonl prefix changed after phase A")
    if record.event_sequence == seal.event_sequence:
        _require_equal("transaction state", seal.state, record.state.value)
        _require_equal("last event hash", seal.last_event_hash, record.last_event_hash)
        _require_equal("events.jsonl size", seal.events_file_size, events_file.size)
        _require_equal("events.jsonl SHA-256", seal.events_jsonl_sha256, events_file.sha256)
    else:
        if events_file.size == seal.events_file_size:
            raise TransactionSealError("Event sequence advanced without an appended journal record")
        sealed_event = snapshot.events[seal.event_sequence - 1]
        _require_equal("sealed event hash", seal.last_event_hash, sealed_event.get("event_hash"))
        _require_equal("sealed event state", seal.state, sealed_event.get("to_state"))


def _validate_legal_event_states(events: Sequence[Mapping[str, Any]]) -> None:
    if not events:
        raise TransactionSealError("events.jsonl must contain at least one event")
    for index, event in enumerate(events):
        try:
            current = TransactionState(event.get("to_state"))
        except (TypeError, ValueError) as exc:
            raise TransactionSealError(f"events.jsonl line {index + 1} has an unknown state") from exc
        if index == 0:
            if event.get("from_state") is not None or current is not TransactionState.DRAFT:
                raise TransactionSealError("The transaction journal must start with null -> draft")
            continue
        try:
            previous = TransactionState(events[index - 1].get("to_state"))
        except (TypeError, ValueError) as exc:  # pragma: no cover - prior row checked above
            raise TransactionSealError("The transaction journal contains an unknown prior state") from exc
        if current not in ALLOWED_TRANSITIONS[previous]:
            raise TransactionSealError(
                f"Illegal journal state transition {previous.value!r} -> {current.value!r}"
            )


def _read_regular_file(path: Path, *, label: str) -> _FileSnapshot:
    _require_plain_file(path, label=label)
    flags = binary_file_open_flags(os.O_RDONLY)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise TransactionSealError(f"Could not safely open {label}: {exc}") from exc
    try:
        before = os.fstat(descriptor)
        _validate_file_stat(before, path=path, label=label)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if not same_regular_file_handle_snapshot(before, after):
        raise TransactionSealError(f"{label} changed while it was being read")
    try:
        final = os.lstat(path)
    except OSError as exc:
        raise TransactionSealError(f"{label} disappeared after it was read: {exc}") from exc
    if not same_regular_file_path_handle_snapshot(after, final):
        raise TransactionSealError(f"{label} path drifted while it was being read")
    data = b"".join(chunks)
    if len(data) != before.st_size:
        raise TransactionSealError(f"{label} byte count does not match its file size")
    return _FileSnapshot(
        path=path,
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        size=before.st_size,
        mode=stat.S_IMODE(before.st_mode),
        ctime_ns=before.st_ctime_ns,
        device=before.st_dev,
        inode=before.st_ino,
    )


def _validate_file_stat(value: os.stat_result, *, path: Path, label: str) -> None:
    if path_is_link_or_reparse(path, metadata=value) or not stat.S_ISREG(value.st_mode):
        raise TransactionSealError(f"{label} must be a regular file: {path}")
    if value.st_nlink != 1:
        raise TransactionSealError(f"{label} must not be hard-linked: {path}")


def _require_real_directory_tree(path: Path) -> None:
    if not path.is_absolute():  # pragma: no cover - normalized by caller
        raise TransactionSealError("State directory must be absolute")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            info = os.lstat(current)
        except OSError as exc:
            raise TransactionSealError(f"State-directory component is missing: {current}: {exc}") from exc
        if path_is_link_or_reparse(current, metadata=info):
            raise TransactionSealError(
                "State-directory link or reparse point is not allowed: "
                f"{current}"
            )
        if not stat.S_ISDIR(info.st_mode):
            raise TransactionSealError(f"State-directory component is not a directory: {current}")


def _require_plain_directory(path: Path, *, label: str) -> None:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise TransactionSealError(f"{label} is missing: {path}: {exc}") from exc
    if path_is_link_or_reparse(path, metadata=info):
        raise TransactionSealError(
            f"{label} cannot be a link or reparse point: {path}"
        )
    if not stat.S_ISDIR(info.st_mode):
        raise TransactionSealError(f"{label} must be a directory: {path}")


def _require_plain_file(path: Path, *, label: str) -> None:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise TransactionSealError(f"{label} is missing: {path}: {exc}") from exc
    if path_is_link_or_reparse(path, metadata=info):
        raise TransactionSealError(
            f"{label} cannot be a link or reparse point: {path}"
        )
    _validate_file_stat(info, path=path, label=label)


def _absolute_lexical_path(value: Path) -> Path:
    if not isinstance(value, Path):
        raise TransactionSealError("state_directory must be a pathlib.Path")
    expanded = value.expanduser()
    return Path(os.path.abspath(os.fspath(expanded)))


def _validated_transaction_id(value: str) -> str:
    try:
        return validate_transaction_id(value)
    except (TransactionError, TypeError, ValueError) as exc:
        raise TransactionSealError(f"Invalid transaction id: {exc}") from exc


def _decode_json_object(data: bytes, *, context: str) -> dict[str, Any]:
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise TransactionSealError(f"Invalid {context}: {exc}") from exc
    if not isinstance(value, dict):
        raise TransactionSealError(f"{context} must contain a JSON object")
    return value


def _decode_json_lines(data: bytes, *, context: str) -> list[dict[str, Any]]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TransactionSealError(f"Invalid UTF-8 in {context}: {exc}") from exc
    if not text.endswith("\n"):
        raise TransactionSealError(f"{context} must end with a newline")
    values: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line:
            raise TransactionSealError(f"Blank line in {context}:{line_number}")
        values.append(_decode_json_object(line.encode("utf-8"), context=f"{context}:{line_number}"))
    return values


def _object_without_duplicate_keys(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON number {value!r} is not allowed")


def _require_exact_fields(payload: Mapping[str, Any], fields: frozenset[str], *, context: str) -> None:
    actual = set(payload)
    missing = sorted(fields - actual)
    unknown = sorted(actual - fields)
    if missing or unknown:
        raise TransactionSealError(
            f"{context} does not match its closed field contract; "
            f"missing={missing}, unknown={unknown}."
        )


def _coerce_allowed_states(values: Iterable[TransactionState | str]) -> frozenset[TransactionState]:
    if isinstance(values, (str, bytes, bytearray)):
        raise TransactionSealError("allowed_states must be an iterable of states, not a string")
    try:
        raw_values = tuple(values)
    except TypeError as exc:
        raise TransactionSealError("allowed_states must be iterable") from exc
    if not raw_values:
        raise TransactionSealError("allowed_states must be non-empty and explicit")
    result: set[TransactionState] = set()
    for value in raw_values:
        try:
            result.add(value if isinstance(value, TransactionState) else TransactionState(value))
        except (TypeError, ValueError) as exc:
            raise TransactionSealError(f"Unknown allowed transaction state: {value!r}") from exc
    return frozenset(result)


def _require_equal(label: str, expected: Any, actual: Any) -> None:
    if expected != actual:
        raise TransactionSealError(f"{label} drift: expected {expected!r}, got {actual!r}")


def _require_sha256(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise TransactionSealError(f"{field} must be a lowercase SHA-256 hex digest")
    return value


def _required_timestamp(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise TransactionSealError(f"{field} must be a non-empty timestamp")
    _parse_timestamp(value)
    return value


def _parse_timestamp(value: str) -> datetime:
    if not value.endswith("Z"):
        raise TransactionSealError("Transaction timestamps must use an explicit UTC Z suffix")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise TransactionSealError(f"Invalid transaction timestamp {value!r}") from exc
    if parsed.tzinfo is None:
        raise TransactionSealError(f"Transaction timestamp lacks a timezone: {value!r}")
    return parsed


def _validate_seal_values(seal: PreviewTransactionSeal) -> None:
    if seal.contract != PREVIEW_SEAL_CONTRACT:
        raise TransactionSealError("Unsupported preview seal contract")
    if not isinstance(seal.state_directory, str) or not seal.state_directory:
        raise TransactionSealError("state_directory must be a non-empty string")
    bound_path = Path(seal.state_directory)
    if not bound_path.is_absolute() or Path(os.path.abspath(seal.state_directory)) != bound_path:
        raise TransactionSealError("state_directory must be a normalized absolute lexical path")
    _validated_transaction_id(seal.transaction_id)
    if seal.state != TransactionState.AWAITING_CONFIRMATION.value:
        raise TransactionSealError("A preview seal must bind awaiting_confirmation state")
    for field in (
        "artifact_hash",
        "preview_json_sha256",
        "last_event_hash",
        "events_jsonl_sha256",
        "project_guard_fingerprint",
        "runtime_guard_fingerprint",
        "request_canonical_sha256",
    ):
        _require_sha256(getattr(seal, field), field=field)
    for field in (
        "preview_file_size",
        "preview_file_ctime_ns",
        "preview_file_device",
        "preview_file_inode",
        "event_sequence",
        "events_file_size",
        "events_file_device",
        "events_file_inode",
    ):
        value = getattr(seal, field)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise TransactionSealError(f"{field} must be a positive integer")
    for field in ("preview_file_mode", "events_file_mode"):
        value = getattr(seal, field)
        if isinstance(value, bool) or not isinstance(value, int) or not (0 <= value <= 0o7777):
            raise TransactionSealError(f"{field} must be an integer file mode")
    created = _required_timestamp(seal.created_at, field="created_at")
    expires = _required_timestamp(seal.expires_at, field="expires_at")
    if _parse_timestamp(expires) <= _parse_timestamp(created):
        raise TransactionSealError("expires_at must be later than created_at")


# Backward-friendly descriptive alias for callers that prefer noun order.
TransactionPreviewSeal = PreviewTransactionSeal


__all__ = [
    "PREVIEW_SEAL_CONTRACT",
    "PREVIEW_SEAL_EVIDENCE_CONTRACT",
    "PreviewSealEvidence",
    "PreviewTransactionSeal",
    "TransactionPreviewSeal",
    "TransactionSealError",
    "create_preview_seal",
    "parse_preview_seal",
    "serialize_preview_seal",
    "validate_transaction_show_confirmation_against_store",
    "verify_preview_seal",
]
