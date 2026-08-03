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


def _identity(metadata: Any) -> tuple[int, int]:
    return int(metadata.st_dev), int(metadata.st_ino)


def _stable_metadata(metadata: Any) -> tuple[int, int, int, int, int, int]:
    return (
        int(metadata.st_dev),
        int(metadata.st_ino),
        int(metadata.st_mode),
        int(metadata.st_nlink),
        int(metadata.st_size),
        int(metadata.st_mtime_ns),
    )


def _validate_regular_metadata(
    path: Path,
    metadata: Any,
    *,
    max_bytes: int,
    check_path_kind: bool,
) -> None:
    if (
        (check_path_kind and path_is_link_or_reparse(path, metadata=metadata))
        or metadata_is_reparse_point(metadata)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_size <= 0
        or metadata.st_size > max_bytes
        or not private_posix_mode_is_valid(metadata)
    ):
        raise CodexFileSecurityError(
            "evidence is not one bounded, exclusive, non-reparse regular file"
        )


def read_bounded_exclusive_regular_file(
    path: Path,
    *,
    max_bytes: int,
) -> BoundedRegularFile:
    """Read one stable file through a descriptor and revalidate its path identity."""

    candidate = Path(path)
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")

    try:
        initial = candidate.lstat()
        _validate_regular_metadata(
            candidate,
            initial,
            max_bytes=max_bytes,
            check_path_kind=True,
        )
    except CodexFileSecurityError:
        raise
    except OSError as exc:
        raise CodexFileSecurityError(f"evidence path cannot be inspected: {exc}") from exc

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
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
        )
        if _identity(initial) != _identity(before):
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
        )
        _validate_regular_metadata(
            candidate,
            final,
            max_bytes=max_bytes,
            check_path_kind=True,
        )
        if (
            _stable_metadata(before) != _stable_metadata(after)
            or _identity(after) != _identity(final)
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
