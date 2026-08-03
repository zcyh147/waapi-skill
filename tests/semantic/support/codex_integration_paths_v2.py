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
import re
from pathlib import Path
from typing import Any

try:  # ``pwd`` is unavailable on native Windows.
    import pwd
except ImportError:  # pragma: no cover - native Windows uses native paths.
    pwd = None  # type: ignore[assignment]


_WINDOWS_DRIVE_PATH_RE = re.compile(r"^([A-Za-z]):/(.*)$")


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
    normalized = value.replace("\\", "/")
    if normalized.startswith("//"):
        raise IntegrationOriginalPathError(
            "copied Original uses an unsupported UNC path"
        )

    if os.name == "nt":  # pragma: no cover - native Windows path semantics
        candidate = Path(value)
        if not candidate.is_absolute():
            raise IntegrationOriginalPathError(
                "copied Original must be drive-absolute"
            )
        return candidate

    drive_match = _WINDOWS_DRIVE_PATH_RE.fullmatch(normalized)
    if re.match(r"^[A-Za-z]:", normalized):
        if drive_match is None:
            raise IntegrationOriginalPathError(
                "copied Original uses a malformed Wine drive path"
            )
        drive = drive_match.group(1).upper()
        suffix = drive_match.group(2)
        if drive == "Z":
            root = Path("/")
        elif drive == "Y":
            root = _resolved_account_home(account_home)
        else:
            raise IntegrationOriginalPathError(
                f"copied Original uses unsupported Wine drive {drive}:"
            )
    else:
        if not normalized.startswith("/"):
            raise IntegrationOriginalPathError(
                "copied Original must be absolute"
            )
        root = Path("/")
        suffix = normalized[1:]

    parts = suffix.split("/")
    if not suffix or any(
        part in {"", ".", ".."} or part.startswith("~") for part in parts
    ):
        raise IntegrationOriginalPathError(
            "copied Original contains an unsafe path component"
        )
    return root.joinpath(*parts)


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
