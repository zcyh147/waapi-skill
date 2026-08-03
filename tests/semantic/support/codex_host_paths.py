"""Host-independent parsing for filesystem paths reflected by Wwise.

Concrete :class:`pathlib.Path` objects use the runner's operating-system
flavour.  They must therefore not be used to decide whether a reflected value
is a Windows drive path, a Wine alias, or a POSIX absolute path.  This module
owns that lexical decision with ``PureWindowsPath`` and ``PurePosixPath``; each
runtime remains responsible for mapping reviewed Wine aliases and proving its
own filesystem containment boundary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath


class ReflectedHostPathError(ValueError):
    """A reflected host path has an ambiguous or unsafe lexical spelling."""


@dataclass(frozen=True, slots=True)
class WindowsDrivePath:
    """One validated drive-absolute Windows path with no host I/O."""

    pure: PureWindowsPath
    drive: str
    relative_parts: tuple[str, ...]


def parse_windows_drive_path(value: str) -> WindowsDrivePath | None:
    """Parse a local drive path independently of the current host flavour.

    ``None`` means that ``value`` has no Windows drive.  UNC paths, drive-
    relative spellings, empty components, repeated separators, dot traversal,
    and trailing separators fail closed instead of being normalized silently.
    """

    candidate = PureWindowsPath(value)
    if not candidate.drive:
        return None
    if candidate.drive.startswith("\\"):
        raise ReflectedHostPathError("UNC paths are unsupported")
    if (
        len(candidate.drive) != 2
        or candidate.drive[1] != ":"
        or candidate.root != "\\"
        or not candidate.is_absolute()
    ):
        raise ReflectedHostPathError("Windows path must be drive-absolute")
    suffix = value[2:]
    if (
        not suffix
        or suffix[0] not in {"\\", "/"}
        or len(suffix) == 1
        or suffix[1] in {"\\", "/"}
        or suffix[-1] in {"\\", "/"}
        or re.search(r"[\\/](?:\.{1,2})(?:[\\/]|$)", suffix)
        or re.search(r"[\\/]{2}", suffix)
    ):
        raise ReflectedHostPathError("Windows path has an unsafe component")
    parts = tuple(candidate.parts[1:])
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ReflectedHostPathError("Windows path has an unsafe component")
    return WindowsDrivePath(
        pure=candidate,
        drive=candidate.drive[0].upper(),
        relative_parts=parts,
    )


def parse_posix_absolute_path(value: str) -> PurePosixPath:
    """Parse one canonical POSIX absolute path without host I/O."""

    if "\\" in value:
        raise ReflectedHostPathError("POSIX path contains a Windows separator")
    if (
        value.endswith("/")
        or "//" in value
        or re.search(r"/(?:\.{1,2})(?:/|$)", value)
    ):
        raise ReflectedHostPathError("POSIX path has an unsafe component")
    candidate = PurePosixPath(value)
    if not candidate.is_absolute():
        raise ReflectedHostPathError("POSIX path must be absolute")
    if any(part in {"", ".", ".."} for part in candidate.parts):
        raise ReflectedHostPathError("POSIX path has an unsafe component")
    return candidate


__all__ = [
    "ReflectedHostPathError",
    "WindowsDrivePath",
    "parse_posix_absolute_path",
    "parse_windows_drive_path",
]
