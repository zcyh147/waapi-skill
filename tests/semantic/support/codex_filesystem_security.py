"""Cross-platform file-integrity primitives for Codex semantic evidence."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class CodexFileSecurityError(RuntimeError):
    """Raised when one evidence file cannot satisfy its integrity boundary."""


@dataclass(frozen=True)
class BoundedRegularFile:
    """One stable descriptor-backed snapshot of a bounded regular file."""

    raw: bytes
    metadata: os.stat_result


def binary_file_open_flags(*flags: int) -> int:
    """Return raw-file descriptor flags with portable binary byte semantics.

    Native Windows otherwise lets the CRT translate ``CRLF`` while
    :func:`os.read` and :func:`os.write` are operating on a descriptor.  That
    makes the byte count disagree with ``stat().st_size`` and invalidates the
    exact-byte integrity checks shared by the semantic harness.  POSIX defines
    neither translation nor ``O_BINARY``, so its zero fallback is a no-op.

    This helper is for regular files whose contents are consumed as bytes.  A
    directory descriptor has different platform semantics and must not use it.
    """

    result = getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    for flag in flags:
        if type(flag) is not int:
            raise TypeError("file-open flags must be integers")
        result |= flag
    return result


def write_utf8_text_bytes(path: Path, value: str) -> None:
    """Write exact UTF-8 archive bytes without platform newline translation."""

    if type(value) is not str:
        raise TypeError("archive text must be a string")
    Path(path).write_bytes(value.encode("utf-8"))


def _platform_name() -> str:
    """Return the standard-library platform discriminator through a test seam."""

    return os.name


def private_posix_mode_is_valid(
    metadata: Any,
    *,
    platform_name: str | None = None,
) -> bool:
    """Apply owner-only mode-bit policy only where POSIX mode bits are real."""

    active_platform = _platform_name() if platform_name is None else platform_name
    return active_platform != "posix" or stat.S_IMODE(metadata.st_mode) & 0o077 == 0


def metadata_is_reparse_point(metadata: Any) -> bool:
    """Recognize a Windows reparse point from ``stat`` metadata when present."""

    attributes = int(getattr(metadata, "st_file_attributes", 0))
    marker = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return bool(attributes & marker)


def path_is_link_or_reparse(
    path: Path,
    *,
    metadata: Any | None = None,
) -> bool:
    """Reject symlinks, junctions, and file reparse points without following them."""

    candidate = Path(path)
    observed = candidate.lstat() if metadata is None else metadata
    if stat.S_ISLNK(observed.st_mode) or metadata_is_reparse_point(observed):
        return True
    is_junction = getattr(candidate, "is_junction", None)
    return bool(is_junction is not None and is_junction())


def same_regular_file_identity(left: Any, right: Any) -> bool:
    """Return whether two stat observations identify the same file object."""

    try:
        return bool(os.path.samestat(left, right))
    except (AttributeError, OSError, TypeError):
        return False


def _portable_content_metadata(metadata: Any) -> tuple[int, int]:
    return (
        int(metadata.st_size),
        int(metadata.st_mtime_ns),
    )


def _portable_file_kind(metadata: Any) -> int:
    return int(stat.S_IFMT(int(metadata.st_mode)))


def _windows_file_attributes(metadata: Any) -> int | None:
    value = getattr(metadata, "st_file_attributes", None)
    return None if value is None else int(value)


def _posix_integrity_metadata(metadata: Any) -> tuple[int, int, int]:
    return (
        int(metadata.st_mode),
        int(metadata.st_nlink),
        int(metadata.st_ctime_ns),
    )


def same_regular_file_handle_snapshot(left: Any, right: Any) -> bool:
    """Compare two ``fstat`` observations around one descriptor read."""

    return (
        same_regular_file_identity(left, right)
        and _portable_content_metadata(left) == _portable_content_metadata(right)
        and _posix_integrity_metadata(left) == _posix_integrity_metadata(right)
    )


def same_regular_file_path_handle_snapshot(
    left: Any,
    right: Any,
    *,
    platform_name: str | None = None,
) -> bool:
    """Compare path and handle observations using their portable contract.

    Native Windows can expose mode, link count, and ctime differently through
    ``lstat`` and ``fstat`` for the unchanged file.  ``samestat``, byte size,
    and modification time are stable across those APIs.  POSIX retains its
    additional mode/link/ctime tamper checks.  Every caller still validates
    regular-file kind and rejects links, junctions, and reparse points before
    using this comparison.
    """

    active_platform = _platform_name() if platform_name is None else platform_name
    if (
        not same_regular_file_identity(left, right)
        or _portable_file_kind(left) != _portable_file_kind(right)
        or _portable_content_metadata(left) != _portable_content_metadata(right)
    ):
        return False
    if active_platform == "nt":
        return _windows_file_attributes(left) == _windows_file_attributes(right)
    return _posix_integrity_metadata(left) == _posix_integrity_metadata(right)


def _validate_regular_metadata(
    path: Path,
    metadata: Any,
    *,
    max_bytes: int,
    check_path_kind: bool,
    require_private_posix_mode: bool,
    allow_empty: bool,
) -> None:
    if (
        (check_path_kind and path_is_link_or_reparse(path, metadata=metadata))
        or metadata_is_reparse_point(metadata)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_size < 0
        or (metadata.st_size == 0 and not allow_empty)
        or metadata.st_size > max_bytes
        or (
            require_private_posix_mode
            and not private_posix_mode_is_valid(metadata)
        )
    ):
        raise CodexFileSecurityError(
            "evidence is not one bounded, exclusive, non-reparse regular file"
        )


def read_bounded_exclusive_regular_file(
    path: Path,
    *,
    max_bytes: int,
    require_private_posix_mode: bool = True,
    allow_empty: bool = False,
) -> BoundedRegularFile:
    """Read one stable file through a descriptor and revalidate its path identity.

    Private owner-only POSIX permissions remain the default for control-plane
    evidence.  Callers reading ordinary staged media may explicitly disable
    only that permission check; the size bound, non-empty/exclusive regular
    file policy, reparse rejection, and descriptor/path identity checks remain
    mandatory.  Empty files are rejected unless a caller explicitly opts in;
    this is intended for bounded output streams such as an empty stderr file.
    """

    candidate = Path(path)
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    if type(require_private_posix_mode) is not bool:
        raise TypeError("require_private_posix_mode must be a boolean")
    if type(allow_empty) is not bool:
        raise TypeError("allow_empty must be a boolean")

    try:
        initial = candidate.lstat()
        _validate_regular_metadata(
            candidate,
            initial,
            max_bytes=max_bytes,
            check_path_kind=True,
            require_private_posix_mode=require_private_posix_mode,
            allow_empty=allow_empty,
        )
    except CodexFileSecurityError:
        raise
    except OSError as exc:
        raise CodexFileSecurityError(f"evidence path cannot be inspected: {exc}") from exc

    flags = binary_file_open_flags(os.O_RDONLY)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(candidate, flags)
        before = os.fstat(descriptor)
        _validate_regular_metadata(
            candidate,
            before,
            max_bytes=max_bytes,
            check_path_kind=False,
            require_private_posix_mode=require_private_posix_mode,
            allow_empty=allow_empty,
        )
        if not same_regular_file_path_handle_snapshot(initial, before):
            raise CodexFileSecurityError(
                "evidence path changed while its descriptor was being opened"
            )

        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        final = candidate.lstat()
        _validate_regular_metadata(
            candidate,
            after,
            max_bytes=max_bytes,
            check_path_kind=False,
            require_private_posix_mode=require_private_posix_mode,
            allow_empty=allow_empty,
        )
        _validate_regular_metadata(
            candidate,
            final,
            max_bytes=max_bytes,
            check_path_kind=True,
            require_private_posix_mode=require_private_posix_mode,
            allow_empty=allow_empty,
        )
        if (
            not same_regular_file_handle_snapshot(before, after)
            or not same_regular_file_path_handle_snapshot(after, final)
            or after.st_size != len(raw)
            or final.st_size != len(raw)
        ):
            raise CodexFileSecurityError(
                "evidence or its path changed during the bounded descriptor read"
            )
        return BoundedRegularFile(raw=raw, metadata=after)
    except CodexFileSecurityError:
        raise
    except OSError as exc:
        raise CodexFileSecurityError(f"evidence cannot be read safely: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
