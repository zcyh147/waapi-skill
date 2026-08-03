"""Shared, fail-closed path localization for integration-workflows-v2.

Older Wwise Authoring builds on macOS can expose local files through Wine
drive aliases.  ``Y:`` is the host account home and ``Z:`` is the filesystem
root.  Campaigns intentionally replace ``HOME``, so resolving ``Y:`` from the
process environment would point at the disposable Codex home instead of the
real project location.

This module performs only lexical localization.  Each runtime must still prove
that the resulting file is a real, non-symlinked descendant of its own copied
``sandbox/Originals`` tree before reading it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from tests.semantic.support.codex_host_paths import (
    ReflectedHostPathError,
    parse_posix_absolute_path,
    parse_windows_drive_path,
)

try:  # ``pwd`` is unavailable on native Windows.
    import pwd
except ImportError:  # pragma: no cover - native Windows uses native paths.
    pwd = None  # type: ignore[assignment]


class IntegrationOriginalPathError(ValueError):
    """A copied Original path cannot be mapped without weakening containment."""


def localize_copied_original_path(
    value: Any,
    *,
    account_home: Path | None = None,
) -> Path:
    """Map one native, Wine ``Y:``, or Wine ``Z:`` absolute path locally.

    On native Windows, drive paths retain native ``Path`` semantics.  On POSIX,
    only the two reviewed Wine aliases are accepted.  The optional
    ``account_home`` is a deterministic test seam; production callers resolve
    the OS account database rather than the mutable ``HOME`` environment.
    """

    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        raise IntegrationOriginalPathError(
            "copied Original requires one absolute path string"
        )
    try:
        windows = parse_windows_drive_path(value)
    except ReflectedHostPathError as exc:
        if value.startswith((r"\\", "//")):
            message = "copied Original uses an unsupported UNC path"
        elif len(value) >= 2 and value[0].isalpha() and value[1] == ":":
            message = (
                "copied Original contains an unsafe path component"
                if "unsafe component" in str(exc)
                else "copied Original uses a malformed Wine drive path"
            )
        else:
            message = "copied Original contains an unsafe path component"
        raise IntegrationOriginalPathError(message) from exc

    if windows is not None:
        if os.name == "nt":  # pragma: no cover - exercised on native Windows.
            return Path(windows.pure)
        if windows.drive == "Z":
            root = Path("/")
        elif windows.drive == "Y":
            root = _resolved_account_home(account_home)
        else:
            raise IntegrationOriginalPathError(
                f"copied Original uses unsupported Wine drive {windows.drive}:"
            )
        return root.joinpath(*windows.relative_parts)

    if os.name == "nt":  # pragma: no cover - exercised on native Windows.
        raise IntegrationOriginalPathError(
            "copied Original must be drive-absolute"
        )
    try:
        return Path(parse_posix_absolute_path(value))
    except ReflectedHostPathError as exc:
        message = (
            "copied Original must be absolute"
            if "must be absolute" in str(exc)
            else "copied Original contains an unsafe path component"
        )
        raise IntegrationOriginalPathError(message) from exc


def _resolved_account_home(value: Path | None) -> Path:
    home = value
    if home is None:
        if pwd is None:  # pragma: no cover - native Windows never maps Wine.
            raise IntegrationOriginalPathError(
                "copied Original cannot resolve the host account home"
            )
        try:
            home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        except (KeyError, OSError) as exc:
            raise IntegrationOriginalPathError(
                "copied Original cannot resolve the host account home"
            ) from exc
    try:
        resolved = Path(home).expanduser().resolve(strict=True)
    except OSError as exc:
        raise IntegrationOriginalPathError(
            "copied Original account home is unavailable"
        ) from exc
    if not resolved.is_dir():
        raise IntegrationOriginalPathError(
            "copied Original account home is not a directory"
        )
    return resolved
