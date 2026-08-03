"""Small cross-platform filesystem helpers used only by tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]


WINDOWS_SYMLINK_PRIVILEGE_ERROR = 1314


def is_windows_symlink_privilege_error(
    error: OSError,
    *,
    platform_name: str | None = None,
) -> bool:
    """Return true only for Windows' missing symlink-privilege failure."""

    current_platform = os.name if platform_name is None else platform_name
    return (
        current_platform == "nt"
        and getattr(error, "winerror", None) == WINDOWS_SYMLINK_PRIVILEGE_ERROR
    )


def create_symlink_or_skip(
    link: Path,
    target: str | Path,
    *,
    target_is_directory: bool = False,
) -> None:
    """Create a real symlink, skipping only when a Windows token forbids it."""

    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as exc:
        if is_windows_symlink_privilege_error(exc):
            pytest.skip("Windows token does not grant symlink privilege for this safety test")
        raise
