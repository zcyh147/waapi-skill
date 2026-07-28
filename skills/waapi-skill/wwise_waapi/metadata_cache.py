"""Bounded, session-scoped cache for live Wwise metadata.

The cache identity deliberately binds Wwise runtime, project, endpoint, and the
packaged metadata resource.  It is safe to reuse static type/property metadata
only while all of those facts remain unchanged.  Dynamic
``isPropertyEnabled`` results and project-state curves are never cacheable.
"""

from __future__ import annotations

import copy
import hmac
import json
import os
import re
import stat
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .canonical import canonical_json_bytes, canonical_sha256


GET_TYPES_URI = "ak.wwise.core.object.getTypes"
GET_PROPERTY_AND_REFERENCE_NAMES_URI = (
    "ak.wwise.core.object.getPropertyAndReferenceNames"
)
GET_PROPERTY_INFO_URI = "ak.wwise.core.object.getPropertyInfo"
IS_PROPERTY_ENABLED_URI = "ak.wwise.core.object.isPropertyEnabled"
GET_ATTENUATION_CURVE_URI = "ak.wwise.core.object.getAttenuationCurve"

CACHEABLE_METADATA_URIS = frozenset(
    {
        GET_TYPES_URI,
        GET_PROPERTY_AND_REFERENCE_NAMES_URI,
        GET_PROPERTY_INFO_URI,
    }
)
DYNAMIC_METADATA_URIS = frozenset(
    {
        IS_PROPERTY_ENABLED_URI,
        GET_ATTENUATION_CURVE_URI,
    }
)
DEFAULT_METADATA_CACHE_MAX_ENTRIES = 4096
DEFAULT_METADATA_CACHE_MAX_ENTRY_BYTES = 256 * 1024
DEFAULT_METADATA_CACHE_MAX_TOTAL_BYTES = 16 * 1024 * 1024
DEFAULT_DURABLE_METADATA_CACHE_MAX_FILE_BYTES = (
    DEFAULT_METADATA_CACHE_MAX_ENTRY_BYTES + 8 * 1024
)
DURABLE_METADATA_CACHE_CONTRACT = "waapi-skill.metadata-cache-entry/v1"
DURABLE_METADATA_CACHE_DIRECTORY = "metadata-cache-v1"
DURABLE_METADATA_CACHE_STALE_TEMP_SECONDS = 5 * 60
_DURABLE_ENTRY_NAME = re.compile(r"^[0-9a-f]{64}\.json$")
_DURABLE_TEMP_NAME = re.compile(
    r"^\.[0-9a-f]{64}\.[0-9a-f]{32}\.tmp$"
)


class MetadataCacheError(ValueError):
    """Raised when a cache identity, lookup, or value is unsafe."""


@dataclass(frozen=True, slots=True)
class MetadataSessionIdentity:
    """All runtime facts that must match before cached metadata is reused."""

    endpoint: str
    wwise_build: str
    schema_version: str
    session_id: str
    process_id: int
    project_id: str
    resource_digest: str

    def __post_init__(self) -> None:
        for field_name in (
            "endpoint",
            "wwise_build",
            "schema_version",
            "session_id",
            "project_id",
        ):
            value = getattr(self, field_name)
            object.__setattr__(
                self,
                field_name,
                _required_text(value, field_name=field_name),
            )
        if (
            not isinstance(self.process_id, int)
            or isinstance(self.process_id, bool)
            or self.process_id < 0
        ):
            raise MetadataCacheError(
                "process_id must be a non-negative integer"
            )
        digest = self.resource_digest
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise MetadataCacheError(
                "resource_digest must be a lowercase SHA-256"
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "endpoint": self.endpoint,
            "process_id": self.process_id,
            "project_id": self.project_id,
            "resource_digest": self.resource_digest,
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "wwise_build": self.wwise_build,
        }

    @classmethod
    def from_live_context(
        cls,
        *,
        endpoint: str,
        live_info: Mapping[str, Any],
        project: Mapping[str, Any],
        resource_digest: str,
    ) -> MetadataSessionIdentity:
        """Build a fail-closed identity from ``getInfo`` and project evidence."""

        if not isinstance(live_info, Mapping):
            raise MetadataCacheError("live_info must be an object")
        if not isinstance(project, Mapping):
            raise MetadataCacheError("project must be an object")
        version = live_info.get("version")
        if not isinstance(version, Mapping):
            raise MetadataCacheError(
                "live_info.version must be an object"
            )
        year = _required_non_negative_int(version.get("year"), field_name="version.year")
        major = _required_non_negative_int(
            version.get("major"),
            field_name="version.major",
        )
        minor = _required_non_negative_int(
            version.get("minor"),
            field_name="version.minor",
        )
        build_number = _required_non_negative_int(
            version.get("build"),
            field_name="version.build",
        )
        schema = _required_non_negative_int(
            version.get("schema"),
            field_name="version.schema",
        )
        process_id = _required_non_negative_int(
            live_info.get("processId"),
            field_name="processId",
        )
        return cls(
            endpoint=endpoint,
            wwise_build=f"{year}.{major}.{minor}.{build_number}",
            schema_version=str(schema),
            session_id=_required_text(
                live_info.get("sessionId"),
                field_name="sessionId",
            ),
            process_id=process_id,
            project_id=_required_text(
                project.get("id"),
                field_name="project.id",
            ),
            resource_digest=resource_digest,
        )


@dataclass(frozen=True, slots=True)
class MetadataCacheLookup:
    """One closed cacheable metadata call shape."""

    uri: str
    class_id: int | None = None
    object_id: str | int | None = None
    property_name: str | None = None

    def __post_init__(self) -> None:
        if self.uri in DYNAMIC_METADATA_URIS:
            raise MetadataCacheError(
                f"{self.uri} is dynamic and must never be cached"
            )
        if self.uri not in CACHEABLE_METADATA_URIS:
            raise MetadataCacheError(
                f"Unsupported metadata cache URI: {self.uri!r}"
            )
        has_class = self.class_id is not None
        has_object = self.object_id is not None
        if self.uri == GET_TYPES_URI:
            if has_class or has_object or self.property_name is not None:
                raise MetadataCacheError(
                    "getTypes cache lookups do not accept a scope"
                )
            return
        if has_class == has_object:
            raise MetadataCacheError(
                "metadata cache lookups require exactly one class_id or "
                "object_id scope"
            )
        if has_class and not _is_uint32(self.class_id):
            raise MetadataCacheError("class_id must be a uint32 integer")
        if has_object:
            if isinstance(self.object_id, str):
                normalized = _required_text(
                    self.object_id,
                    field_name="object_id",
                )
                object.__setattr__(self, "object_id", normalized)
            elif not _is_uint32(self.object_id):
                raise MetadataCacheError(
                    "object_id must be a non-empty string or uint32 integer"
                )
        if self.uri == GET_PROPERTY_INFO_URI:
            object.__setattr__(
                self,
                "property_name",
                _required_text(
                    self.property_name,
                    field_name="property_name",
                ),
            )
        elif self.property_name is not None:
            raise MetadataCacheError(
                "property_name is accepted only for getPropertyInfo"
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "class_id": self.class_id,
            "object_id": self.object_id,
            "property_name": self.property_name,
            "uri": self.uri,
        }

    @property
    def durable_safe(self) -> bool:
        """Whether this lookup is immutable enough for cross-process reuse.

        Object-scoped calls can be addressed by a mutable name/path and can
        change after an object is replaced during the same Authoring session.
        Keep those in the single-preview memory layer.  Type and class-scoped
        metadata are safe to persist under the exact live-session identity.
        """

        return self.object_id is None

    @classmethod
    def types(cls) -> MetadataCacheLookup:
        return cls(GET_TYPES_URI)

    @classmethod
    def names(
        cls,
        *,
        class_id: int | None = None,
        object_id: str | int | None = None,
    ) -> MetadataCacheLookup:
        return cls(
            GET_PROPERTY_AND_REFERENCE_NAMES_URI,
            class_id=class_id,
            object_id=object_id,
        )

    @classmethod
    def property_info(
        cls,
        *,
        property_name: str,
        class_id: int | None = None,
        object_id: str | int | None = None,
    ) -> MetadataCacheLookup:
        return cls(
            GET_PROPERTY_INFO_URI,
            class_id=class_id,
            object_id=object_id,
            property_name=property_name,
        )


@dataclass(frozen=True, slots=True)
class MetadataCacheStats:
    entries: int
    total_bytes: int
    hits: int
    misses: int
    evictions: int

    def as_dict(self) -> dict[str, int]:
        return {
            "entries": self.entries,
            "evictions": self.evictions,
            "hits": self.hits,
            "misses": self.misses,
            "total_bytes": self.total_bytes,
        }


@dataclass(frozen=True, slots=True)
class _MetadataCacheKey:
    identity: MetadataSessionIdentity
    lookup: MetadataCacheLookup


@dataclass(slots=True)
class _MetadataCacheEntry:
    value: Any
    size_bytes: int


@dataclass(slots=True)
class SessionMetadataCache:
    """Bounded in-memory LRU cache keyed by one exact Wwise session."""

    max_entries: int = DEFAULT_METADATA_CACHE_MAX_ENTRIES
    max_entry_bytes: int = DEFAULT_METADATA_CACHE_MAX_ENTRY_BYTES
    max_total_bytes: int = DEFAULT_METADATA_CACHE_MAX_TOTAL_BYTES
    _entries: OrderedDict[_MetadataCacheKey, _MetadataCacheEntry] = field(
        default_factory=OrderedDict,
        init=False,
        repr=False,
    )
    _total_bytes: int = field(default=0, init=False, repr=False)
    _hits: int = field(default=0, init=False, repr=False)
    _misses: int = field(default=0, init=False, repr=False)
    _evictions: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        for field_name in (
            "max_entries",
            "max_entry_bytes",
            "max_total_bytes",
        ):
            value = getattr(self, field_name)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
            ):
                raise MetadataCacheError(
                    f"{field_name} must be a positive integer"
                )
        if self.max_entry_bytes > self.max_total_bytes:
            raise MetadataCacheError(
                "max_entry_bytes cannot exceed max_total_bytes"
            )

    def get(
        self,
        identity: MetadataSessionIdentity,
        lookup: MetadataCacheLookup,
    ) -> Any | None:
        key = _MetadataCacheKey(identity=identity, lookup=lookup)
        entry = self._entries.get(key)
        if entry is None:
            self._misses += 1
            return None
        self._entries.move_to_end(key)
        self._hits += 1
        return copy.deepcopy(entry.value)

    def put(
        self,
        identity: MetadataSessionIdentity,
        lookup: MetadataCacheLookup,
        value: Any,
    ) -> None:
        """Store one JSON-compatible normalized metadata value."""

        try:
            size_bytes = len(canonical_json_bytes(value))
        except (TypeError, ValueError) as exc:
            raise MetadataCacheError(
                "metadata cache values must be canonical JSON-compatible"
            ) from exc
        if size_bytes > self.max_entry_bytes:
            raise MetadataCacheError(
                f"metadata cache value is {size_bytes} bytes; the per-entry "
                f"limit is {self.max_entry_bytes}"
            )
        key = _MetadataCacheKey(identity=identity, lookup=lookup)
        current = self._entries.pop(key, None)
        if current is not None:
            self._total_bytes -= current.size_bytes
        self._entries[key] = _MetadataCacheEntry(
            value=copy.deepcopy(value),
            size_bytes=size_bytes,
        )
        self._total_bytes += size_bytes
        self._evict_to_limits()

    def invalidate_session(self, identity: MetadataSessionIdentity) -> int:
        """Remove every entry bound to one exact session identity."""

        keys = [
            key for key in self._entries if key.identity == identity
        ]
        for key in keys:
            entry = self._entries.pop(key)
            self._total_bytes -= entry.size_bytes
        return len(keys)

    def clear(self) -> None:
        self._entries.clear()
        self._total_bytes = 0

    def stats(self) -> MetadataCacheStats:
        return MetadataCacheStats(
            entries=len(self._entries),
            total_bytes=self._total_bytes,
            hits=self._hits,
            misses=self._misses,
            evictions=self._evictions,
        )

    def _evict_to_limits(self) -> None:
        while (
            len(self._entries) > self.max_entries
            or self._total_bytes > self.max_total_bytes
        ):
            _, entry = self._entries.popitem(last=False)
            self._total_bytes -= entry.size_bytes
            self._evictions += 1


@dataclass(slots=True)
class DurableMetadataCache:
    """Best-effort cross-process metadata cache below transaction state.

    Each exact key owns one atomic JSON file.  No cache failure is surfaced to
    callers: an unsafe directory, symlink, malformed entry, concurrent removal,
    or I/O error simply behaves as a miss so the transaction performs a fresh
    WAAPI read.  Only class-scoped metadata is durable; object-scoped results
    remain in the in-memory hot layer.
    """

    state_dir: Path
    max_entries: int = DEFAULT_METADATA_CACHE_MAX_ENTRIES
    max_file_bytes: int = DEFAULT_DURABLE_METADATA_CACHE_MAX_FILE_BYTES
    max_total_bytes: int = DEFAULT_METADATA_CACHE_MAX_TOTAL_BYTES

    def __post_init__(self) -> None:
        if not isinstance(self.state_dir, Path) or not self.state_dir.is_absolute():
            raise MetadataCacheError(
                "durable metadata cache state_dir must be an absolute pathlib.Path"
            )
        for field_name in ("max_entries", "max_file_bytes", "max_total_bytes"):
            value = getattr(self, field_name)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
            ):
                raise MetadataCacheError(
                    f"{field_name} must be a positive integer"
                )
        if self.max_file_bytes > self.max_total_bytes:
            raise MetadataCacheError(
                "max_file_bytes cannot exceed max_total_bytes"
            )

    @property
    def directory(self) -> Path:
        return self.state_dir / DURABLE_METADATA_CACHE_DIRECTORY

    def get(
        self,
        identity: MetadataSessionIdentity,
        lookup: MetadataCacheLookup,
    ) -> Any | None:
        if not lookup.durable_safe:
            return None
        try:
            directory = self._safe_directory(create=False)
            if directory is None:
                return None
            key_sha256 = _durable_key_sha256(identity, lookup)
            path = directory / f"{key_sha256}.json"
            data = self._read_regular_file(path)
            if data is None:
                return None
            payload = json.loads(data.decode("utf-8"))
            if (
                not isinstance(payload, Mapping)
                or set(payload)
                != {
                    "contract",
                    "identity",
                    "key_sha256",
                    "lookup",
                    "value",
                    "value_sha256",
                }
                or payload.get("contract") != DURABLE_METADATA_CACHE_CONTRACT
                or payload.get("identity") != identity.as_dict()
                or payload.get("lookup") != lookup.as_dict()
                or payload.get("key_sha256") != key_sha256
            ):
                return None
            value = payload.get("value")
            if not isinstance(value, Mapping):
                return None
            expected_value_sha256 = payload.get("value_sha256")
            if (
                not isinstance(expected_value_sha256, str)
                or not hmac.compare_digest(
                    expected_value_sha256,
                    canonical_sha256(value),
                )
            ):
                return None
            return copy.deepcopy(value)
        except Exception:
            # Persistent caching is an optimization.  Corruption, concurrent
            # replacement, unsupported filesystem behavior, and resource
            # exhaustion must never block a transaction preview.
            return None

    def put(
        self,
        identity: MetadataSessionIdentity,
        lookup: MetadataCacheLookup,
        value: Any,
    ) -> bool:
        if not lookup.durable_safe or not isinstance(value, Mapping):
            return False
        try:
            # Reuse the in-memory value ceiling before adding the small durable
            # identity envelope.
            if len(canonical_json_bytes(value)) > DEFAULT_METADATA_CACHE_MAX_ENTRY_BYTES:
                return False
            directory = self._safe_directory(create=True)
            if directory is None:
                return False
            directory_identity = _directory_identity(directory)
            if directory_identity is None:
                return False
            key_sha256 = _durable_key_sha256(identity, lookup)
            payload = {
                "contract": DURABLE_METADATA_CACHE_CONTRACT,
                "identity": identity.as_dict(),
                "key_sha256": key_sha256,
                "lookup": lookup.as_dict(),
                "value": copy.deepcopy(value),
                "value_sha256": canonical_sha256(value),
            }
            data = canonical_json_bytes(payload) + b"\n"
            if len(data) > self.max_file_bytes:
                return False
            target = directory / f"{key_sha256}.json"
            if not self._prepare_directory_for_publish(
                directory,
                target=target,
                incoming_size=len(data),
            ):
                return False
            temporary = directory / f".{key_sha256}.{uuid.uuid4().hex}.tmp"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(temporary, flags, 0o600)
            try:
                handle = os.fdopen(fd, "wb", closefd=True)
                fd = -1
                with handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                # Recheck the cache directory immediately before publication.
                # os.replace replaces a symlink leaf rather than following it,
                # but an unsafe directory swap still causes this write to be
                # abandoned.
                if (
                    self._safe_directory(create=False) != directory
                    or _directory_identity(directory) != directory_identity
                ):
                    return False
                if not self._prepare_directory_for_publish(
                    directory,
                    target=target,
                    incoming_size=len(data),
                    own_temporary=temporary,
                ):
                    return False
                os.replace(temporary, target)
                _fsync_directory(directory)
            finally:
                if fd >= 0:
                    os.close(fd)
                if _lexists(temporary):
                    temporary.unlink()
            return self._prune_to_limits(directory, preserve=target)
        except Exception:
            return False

    def _safe_directory(self, *, create: bool) -> Path | None:
        try:
            state_stat = self.state_dir.lstat()
        except OSError:
            return None
        if (
            stat.S_ISLNK(state_stat.st_mode)
            or not stat.S_ISDIR(state_stat.st_mode)
        ):
            return None
        directory = self.directory
        try:
            directory_stat = directory.lstat()
        except FileNotFoundError:
            if not create:
                return None
            try:
                directory.mkdir(mode=0o700, parents=False, exist_ok=False)
            except FileExistsError:
                pass
            directory_stat = directory.lstat()
        except OSError:
            return None
        if (
            stat.S_ISLNK(directory_stat.st_mode)
            or not stat.S_ISDIR(directory_stat.st_mode)
        ):
            return None
        return directory

    def _read_regular_file(self, path: Path) -> bytes | None:
        try:
            before = path.lstat()
        except OSError:
            return None
        if (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(before.st_mode)
            or before.st_size > self.max_file_bytes
        ):
            return None
        flags = os.O_RDONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags)
        try:
            opened = os.fstat(fd)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_size > self.max_file_bytes
                or (
                    hasattr(before, "st_ino")
                    and hasattr(opened, "st_ino")
                    and (before.st_dev, before.st_ino)
                    != (opened.st_dev, opened.st_ino)
                )
            ):
                return None
            with os.fdopen(fd, "rb", closefd=True) as handle:
                fd = -1
                data = handle.read(self.max_file_bytes + 1)
            return data if len(data) <= self.max_file_bytes else None
        finally:
            if fd >= 0:
                os.close(fd)

    def _prepare_directory_for_publish(
        self,
        directory: Path,
        *,
        target: Path,
        incoming_size: int,
        own_temporary: Path | None = None,
    ) -> bool:
        """Fail safely unless one atomic publication can remain bounded.

        A recognized but unsafe entry disables the durable optimization before
        publication.  Stale regular temporary files from a crashed writer are
        removed, while fresh temporaries are treated as concurrent writers and
        bounded separately.
        """

        scanned = self._scan_managed_files(
            directory,
            cleanup_stale_temporaries=True,
        )
        if scanned is None:
            return False
        _entries, temporaries = scanned
        if own_temporary is None:
            projected_temporary_count = len(temporaries) + 1
            projected_temporary_bytes = (
                sum(size for _, size, _ in temporaries) + incoming_size
            )
        else:
            if not any(path == own_temporary for _, _, path in temporaries):
                return False
            projected_temporary_count = len(temporaries)
            projected_temporary_bytes = sum(
                size for _, size, _ in temporaries
            )
        if (
            projected_temporary_count > self.max_entries
            or projected_temporary_bytes > self.max_total_bytes
        ):
            return False
        return self._prune_to_limits(
            directory,
            preserve=target,
            replacement_target=target,
            replacement_size=incoming_size,
        )

    def _scan_managed_files(
        self,
        directory: Path,
        *,
        cleanup_stale_temporaries: bool,
    ) -> tuple[
        list[tuple[int, int, Path]],
        list[tuple[int, int, Path]],
    ] | None:
        entries: list[tuple[int, int, Path]] = []
        temporaries: list[tuple[int, int, Path]] = []
        stale_cutoff_ns = time.time_ns() - (
            DURABLE_METADATA_CACHE_STALE_TEMP_SECONDS * 1_000_000_000
        )
        for child in directory.iterdir():
            is_entry = bool(_DURABLE_ENTRY_NAME.fullmatch(child.name))
            is_temporary = bool(_DURABLE_TEMP_NAME.fullmatch(child.name))
            if not is_entry and not is_temporary:
                continue
            child_stat = child.lstat()
            if (
                stat.S_ISLNK(child_stat.st_mode)
                or not stat.S_ISREG(child_stat.st_mode)
            ):
                return None
            if is_entry:
                if child_stat.st_size > self.max_file_bytes:
                    return None
                entries.append(
                    (child_stat.st_mtime_ns, child_stat.st_size, child)
                )
                continue
            if (
                cleanup_stale_temporaries
                and child_stat.st_mtime_ns <= stale_cutoff_ns
            ):
                try:
                    current = child.lstat()
                    if (
                        not stat.S_ISREG(current.st_mode)
                        or stat.S_ISLNK(current.st_mode)
                        or (current.st_dev, current.st_ino)
                        != (child_stat.st_dev, child_stat.st_ino)
                        or current.st_mtime_ns > stale_cutoff_ns
                    ):
                        return None
                    child.unlink()
                except OSError:
                    return None
                continue
            if child_stat.st_size > self.max_file_bytes:
                return None
            temporaries.append(
                (child_stat.st_mtime_ns, child_stat.st_size, child)
            )
        return entries, temporaries

    def _prune_to_limits(
        self,
        directory: Path,
        *,
        preserve: Path,
        replacement_target: Path | None = None,
        replacement_size: int = 0,
    ) -> bool:
        scanned = self._scan_managed_files(
            directory,
            cleanup_stale_temporaries=False,
        )
        if scanned is None:
            return False
        rows, _temporaries = scanned
        total_bytes = sum(size for _, size, _ in rows)
        rows.sort(key=lambda item: (item[0], item[2].name))
        replacement_row = next(
            (
                row
                for row in rows
                if replacement_target is not None
                and row[2] == replacement_target
            ),
            None,
        )

        def projected_count() -> int:
            if replacement_target is None or replacement_row is not None:
                return len(rows)
            return len(rows) + 1

        def projected_bytes() -> int:
            replaced_size = (
                replacement_row[1]
                if replacement_row is not None
                else 0
            )
            return total_bytes - replaced_size + (
                replacement_size if replacement_target is not None else 0
            )

        while (
            projected_count() > self.max_entries
            or projected_bytes() > self.max_total_bytes
        ):
            removable_index = next(
                (
                    index
                    for index, (_, _, path) in enumerate(rows)
                    if path != preserve and path != replacement_target
                ),
                None,
            )
            if removable_index is None:
                return False
            _, size, path = rows.pop(removable_index)
            try:
                current = path.lstat()
                if stat.S_ISREG(current.st_mode) and not stat.S_ISLNK(
                    current.st_mode
                ):
                    path.unlink()
                    total_bytes -= size
            except OSError:
                return False
        _fsync_directory(directory)
        return True


def _durable_key_sha256(
    identity: MetadataSessionIdentity,
    lookup: MetadataCacheLookup,
) -> str:
    return canonical_sha256(
        {
            "contract": DURABLE_METADATA_CACHE_CONTRACT,
            "identity": identity.as_dict(),
            "lookup": lookup.as_dict(),
        }
    )


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
        pass
    finally:
        os.close(fd)


def _lexists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def _directory_identity(path: Path) -> tuple[int, int] | None:
    try:
        path_stat = path.lstat()
    except OSError:
        return None
    if (
        stat.S_ISLNK(path_stat.st_mode)
        or not stat.S_ISDIR(path_stat.st_mode)
    ):
        return None
    return path_stat.st_dev, path_stat.st_ino


def _required_non_negative_int(value: Any, *, field_name: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise MetadataCacheError(
            f"{field_name} must be a non-negative integer"
        )
    return value


def _required_text(value: Any, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\x00" in value
        or len(value) > 2048
    ):
        raise MetadataCacheError(
            f"{field_name} must be a non-empty bounded string"
        )
    return value.strip()


def _is_uint32(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= 0xFFFFFFFF
    )


__all__ = [
    "CACHEABLE_METADATA_URIS",
    "DEFAULT_DURABLE_METADATA_CACHE_MAX_FILE_BYTES",
    "DEFAULT_METADATA_CACHE_MAX_ENTRIES",
    "DEFAULT_METADATA_CACHE_MAX_ENTRY_BYTES",
    "DEFAULT_METADATA_CACHE_MAX_TOTAL_BYTES",
    "DURABLE_METADATA_CACHE_CONTRACT",
    "DURABLE_METADATA_CACHE_DIRECTORY",
    "DURABLE_METADATA_CACHE_STALE_TEMP_SECONDS",
    "DYNAMIC_METADATA_URIS",
    "DurableMetadataCache",
    "GET_ATTENUATION_CURVE_URI",
    "GET_PROPERTY_AND_REFERENCE_NAMES_URI",
    "GET_PROPERTY_INFO_URI",
    "GET_TYPES_URI",
    "IS_PROPERTY_ENABLED_URI",
    "MetadataCacheError",
    "MetadataCacheLookup",
    "MetadataCacheStats",
    "MetadataSessionIdentity",
    "SessionMetadataCache",
]
