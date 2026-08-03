"""Typed conversion boundary for paths stored inside semantic archives.

Archive-relative paths are portable identities, not host filesystem paths and
not Wwise object hierarchy paths.  Windows producers may spell a relative path
with ``\\`` while the archive comparison contract uses POSIX ``/``.  This
module selects the source flavor with ``pathlib`` pure paths, rejects ambiguous
or traversing spellings before normalization, and exposes one canonical POSIX
identity to archive validators.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal


ArchivePathFlavor = Literal["posix", "windows"]
_WINDOWS_SEPARATOR = re.compile(r"[\\/]")
_WINDOWS_UNSAFE_COMPONENT = re.compile(r'[<>:"|?*]')
_WINDOWS_RESERVED_COMPONENTS = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)


class ArchiveRelativePathError(ValueError):
    """An archive path is absolute, empty, traversing, or ambiguous."""


@dataclass(frozen=True, slots=True)
class ArchiveRelativePath:
    """One validated relative path with a canonical portable identity."""

    source_flavor: ArchivePathFlavor
    parts: tuple[str, ...]

    @property
    def canonical(self) -> str:
        return PurePosixPath(*self.parts).as_posix()


@dataclass(frozen=True, slots=True)
class ArchiveAbsolutePath:
    """One validated host-absolute path with an explicit source flavor."""

    source_flavor: ArchivePathFlavor
    pure_path: PurePosixPath | PureWindowsPath

    @property
    def name(self) -> str:
        """Return the basename using the producer path's lexical flavor."""

        name = self.pure_path.name
        if not name:
            raise ArchiveRelativePathError(
                "archive host path must identify a named entry"
            )
        return name


def parse_archive_relative_path(value: object) -> ArchiveRelativePath:
    """Parse a Windows- or POSIX-spelled archive-relative path.

    A backslash selects Windows relative-path semantics.  Forward-slash-only
    input uses POSIX semantics.  Both spellings produce the same canonical
    POSIX archive identity.  Mixed separators are rejected so an archive never
    depends on platform-specific normalization rules.
    """

    text = _exact_text(value)
    windows = PureWindowsPath(text)
    posix = PurePosixPath(text)
    if windows.drive or windows.root or posix.is_absolute():
        raise ArchiveRelativePathError("archive path must be relative")

    if "\\" in text and "/" in text:
        raise ArchiveRelativePathError(
            "archive relative path cannot mix Windows and POSIX separators"
        )
    if "\\" in text:
        source_flavor: ArchivePathFlavor = "windows"
        parts = tuple(text.split("\\"))
    else:
        source_flavor = "posix"
        parts = tuple(text.split("/"))
    _validate_relative_parts(parts, flavor=source_flavor)
    return ArchiveRelativePath(source_flavor=source_flavor, parts=parts)


def parse_archive_absolute_path(
    value: str | os.PathLike[str],
) -> ArchiveAbsolutePath:
    """Parse a host-absolute archive path without using host OS semantics."""

    text = _exact_text(os.fspath(value))
    source_flavor, pure_path = _parse_absolute(text)
    return ArchiveAbsolutePath(
        source_flavor=source_flavor,
        pure_path=pure_path,
    )


def archive_relative_from_absolute(
    path: str | os.PathLike[str],
    root: str | os.PathLike[str],
) -> ArchiveRelativePath:
    """Derive one canonical archive identity from same-flavor absolute paths."""

    parsed_path = parse_archive_absolute_path(path)
    parsed_root = parse_archive_absolute_path(root)
    if (
        parsed_path.source_flavor != parsed_root.source_flavor
        or type(parsed_path.pure_path) is not type(parsed_root.pure_path)
    ):
        raise ArchiveRelativePathError(
            "archive path and root use different filesystem flavors"
        )
    try:
        relative = parsed_path.pure_path.relative_to(parsed_root.pure_path)
    except ValueError as exc:
        raise ArchiveRelativePathError("archive path is outside its root") from exc
    parts = tuple(relative.parts)
    _validate_relative_parts(parts, flavor=parsed_path.source_flavor)
    return ArchiveRelativePath(
        source_flavor=parsed_path.source_flavor,
        parts=parts,
    )


def archive_absolute_has_relative_suffix(
    path: str | os.PathLike[str],
    relative: object,
) -> bool:
    """Compare an absolute evidence path with one portable relative suffix.

    The absolute path selects the comparison flavor.  Windows drive and UNC
    suffixes therefore compare case-insensitively through
    :class:`PureWindowsPath`, while POSIX suffixes retain case-sensitive
    :class:`PurePosixPath` semantics.  Neither spelling is rewritten by hand.
    """

    parsed_path = parse_archive_absolute_path(path)
    parsed_relative = parse_archive_relative_path(relative)
    relative_parts = parsed_relative.parts
    absolute_parts = parsed_path.pure_path.parts
    if len(absolute_parts) < len(relative_parts):
        return False
    path_type = type(parsed_path.pure_path)
    return path_type(*absolute_parts[-len(relative_parts) :]) == path_type(
        *relative_parts
    )


def archive_absolute_names_equal(
    left: str | os.PathLike[str],
    right: str | os.PathLike[str],
) -> bool:
    """Compare basenames under the filesystem semantics that can own them.

    POSIX-to-POSIX comparisons remain case-sensitive.  A Windows drive or UNC
    participant makes the comparison case-insensitive, which also covers a
    Wine/Windows path being joined to the same file archived by a POSIX-side
    fixture collector.
    """

    parsed_left = parse_archive_absolute_path(left)
    parsed_right = parse_archive_absolute_path(right)
    left_name = parsed_left.name
    right_name = parsed_right.name
    if (
        parsed_left.source_flavor == "windows"
        or parsed_right.source_flavor == "windows"
    ):
        return left_name.casefold() == right_name.casefold()
    return left_name == right_name


def _parse_absolute(
    text: str,
) -> tuple[ArchivePathFlavor, PurePosixPath | PureWindowsPath]:
    if text.startswith(("\\\\", "//")):
        _validate_raw_unc_absolute_text(text)
    windows = PureWindowsPath(text)
    if windows.is_absolute():
        _validate_windows_absolute_text(text, windows)
        return "windows", windows

    posix = PurePosixPath(text)
    if posix.is_absolute():
        _validate_posix_absolute_text(text)
        return "posix", posix
    raise ArchiveRelativePathError("archive host path must be absolute")


def _validate_raw_unc_absolute_text(text: str) -> None:
    """Reject UNC normalization before ``pathlib`` can absorb it into an anchor.

    Python 3.13 accepts some malformed UNC spellings that older releases leave
    relative, including an empty share component after a repeated separator.
    Archive identity must not depend on that interpreter-version distinction.
    """

    if text.startswith(("\\\\?\\", "\\\\.\\", "//?/", "//./")):
        raise ArchiveRelativePathError(
            "extended or device paths are outside the archive contract"
        )
    separator = "\\" if text.startswith("\\\\") else "/"
    other_separator = "/" if separator == "\\" else "\\"
    if other_separator in text:
        raise ArchiveRelativePathError(
            "archive host path cannot mix Windows separators"
        )
    parts = text[2:].split(separator)
    if parts and parts[-1] == "":
        # A canonical UNC share root may retain its anchor separator.  A named
        # entry may not use a trailing separator.
        if len(parts) != 3:
            raise ArchiveRelativePathError(
                "UNC archive path has a non-canonical trailing separator"
            )
        parts.pop()
    if len(parts) < 2:
        raise ArchiveRelativePathError(
            "UNC archive path requires nonempty server and share components"
        )
    _validate_relative_parts(tuple(parts), flavor="windows", portable=False)


def _validate_windows_absolute_text(
    text: str,
    path: PureWindowsPath,
) -> None:
    if text.startswith(("\\\\?\\", "\\\\.\\", "//?/", "//./")):
        raise ArchiveRelativePathError(
            "extended or device paths are outside the archive contract"
        )
    if "\\" in text and "/" in text:
        raise ArchiveRelativePathError(
            "archive host path cannot mix Windows separators"
        )
    anchor = path.anchor
    suffix = text[len(anchor) :] if text.startswith(anchor) else None
    if suffix is None:
        # ``PureWindowsPath`` normalizes forward separators in its anchor, so
        # derive the raw suffix without altering any path component.
        if path.drive.startswith("\\\\"):
            raw = text[2:]
            unc_parts = _WINDOWS_SEPARATOR.split(raw)
            if len(unc_parts) < 2 or any(not part for part in unc_parts[:2]):
                raise ArchiveRelativePathError("UNC archive path is malformed")
            suffix = _drop_windows_prefix(raw, 2)
        elif len(text) >= 3 and text[1] == ":" and text[2] in {"\\", "/"}:
            suffix = text[3:]
        else:
            raise ArchiveRelativePathError("Windows archive path is malformed")
    if not suffix:
        return
    parts = tuple(_WINDOWS_SEPARATOR.split(suffix))
    _validate_relative_parts(parts, flavor="windows", portable=False)


def _drop_windows_prefix(value: str, component_count: int) -> str:
    position = 0
    consumed = 0
    while position < len(value) and consumed < component_count:
        separator = _WINDOWS_SEPARATOR.search(value, position)
        if separator is None:
            return ""
        position = separator.end()
        consumed += 1
    return value[position:]


def _validate_posix_absolute_text(text: str) -> None:
    if text == "/":
        return
    parts = tuple(text[1:].split("/"))
    _validate_relative_parts(parts, flavor="posix", portable=False)


def _exact_text(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ArchiveRelativePathError(
            "archive path must be nonempty and have no outer whitespace"
        )
    if any(
        ord(character) < 32
        or ord(character) == 127
        or character in {"\u2028", "\u2029"}
        for character in value
    ):
        raise ArchiveRelativePathError("archive path contains a control character")
    return value


def _validate_relative_parts(
    parts: tuple[str, ...],
    *,
    flavor: ArchivePathFlavor,
    portable: bool = True,
) -> None:
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ArchiveRelativePathError(
            "archive path must use nonempty non-traversing components"
        )
    if (portable or flavor == "windows") and any(
        _WINDOWS_UNSAFE_COMPONENT.search(part) is not None
        or part.endswith((" ", "."))
        or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_COMPONENTS
        for part in parts
    ):
        raise ArchiveRelativePathError(
            "archive path contains a non-portable filename component"
        )
    if flavor == "posix" and any("\\" in part for part in parts):
        raise ArchiveRelativePathError(
            "POSIX archive paths cannot contain the portable Windows separator"
        )


__all__ = [
    "ArchiveAbsolutePath",
    "ArchiveRelativePath",
    "ArchiveRelativePathError",
    "archive_absolute_names_equal",
    "archive_absolute_has_relative_suffix",
    "archive_relative_from_absolute",
    "parse_archive_absolute_path",
    "parse_archive_relative_path",
]
