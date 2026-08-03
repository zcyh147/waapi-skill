"""Portable filesystem link and reparse-point detection.

`Path.is_symlink()` is not sufficient on Windows: directory junctions and
other reparse points can redirect an otherwise ordinary-looking path.  Keep
the platform check in one production module so every write/read boundary uses
the same `pathlib` and stat semantics.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any


def metadata_is_link_or_reparse(metadata: Any) -> bool:
    """Return whether one lstat result represents a link/reparse object."""

    if stat.S_ISLNK(metadata.st_mode):
        return True
    attributes = int(getattr(metadata, "st_file_attributes", 0) or 0)
    reparse_flag = int(
        getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
    )
    return bool(attributes & reparse_flag)


def path_is_link_or_reparse(
    value: str | os.PathLike[str],
    *,
    metadata: Any | None = None,
) -> bool:
    """Detect symlinks, junctions, and file reparse points without following."""

    path = Path(value)
    observed = path.lstat() if metadata is None else metadata
    if metadata_is_link_or_reparse(observed):
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction is not None and is_junction())


__all__ = ["metadata_is_link_or_reparse", "path_is_link_or_reparse"]
