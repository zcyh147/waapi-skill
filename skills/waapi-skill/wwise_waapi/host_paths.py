"""Lexical host-filesystem path parsing, localization, and comparison.

Wwise can report native Windows paths, UNC paths, native POSIX paths, or the
``Y:``/``Z:`` drive paths exposed by Wine.  Those are operating-system paths,
not Wwise object hierarchy paths.  This module keeps the two domains separate
and selects a ``pathlib`` flavor before it creates a concrete host path.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal


HostPathFlavor = Literal["posix", "drive", "unc"]
RelativeHostPathFlavor = Literal["posix", "windows"]
HostPathKey = tuple[str, ...]

_WINDOWS_DRIVE_PREFIX = re.compile(r"^([A-Za-z]):")
_WINDOWS_COMPONENT_SEPARATOR = re.compile(r"[\\/]")
_WINDOWS_UNSAFE_COMPONENT = re.compile(r'[<>:"|?*]')
_WINDOWS_RESERVED_COMPONENTS = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)


class HostPathError(ValueError):
    """An absolute filesystem path is malformed or cannot map to this host."""

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        details: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class ParsedHostPath:
    """One validated absolute path with an explicit lexical path flavor."""

    flavor: HostPathFlavor
    pure_path: PurePosixPath | PureWindowsPath
    components: tuple[str, ...]
    drive: str | None = None

    def comparison_key(self) -> HostPathKey:
        """Return a flavor-aware key without applying host-dependent rules."""

        if self.flavor == "posix":
            # POSIX filenames are case-sensitive by contract here, and a
            # backslash is a legal literal character rather than a separator.
            return (self.flavor, *self.components)
        if self.flavor == "drive":
            assert self.drive is not None
            return (
                self.flavor,
                self.drive.casefold(),
                *(component.casefold() for component in self.components),
            )
        return (
            self.flavor,
            *(component.casefold() for component in self.components),
        )


@dataclass(frozen=True, slots=True)
class ParsedRelativeHostPath:
    """One validated relative filesystem path with an explicit source flavor."""

    flavor: RelativeHostPathFlavor
    pure_path: PurePosixPath | PureWindowsPath
    components: tuple[str, ...]


def parse_absolute_host_path(
    value: object,
    *,
    allow_trailing_separator: bool = False,
) -> ParsedHostPath:
    """Parse one exact absolute path without guessing its separator flavor.

    Windows drive and UNC paths accept either Windows-supported separator.
    POSIX paths split only on ``/`` so a literal ``\\`` remains part of the
    filename.  Repeated separators and traversal components are rejected
    before ``pathlib`` can normalize them away.
    """

    if not isinstance(value, str) or not value or value != value.strip():
        raise HostPathError(
            "INVALID_HOST_PATH",
            "expected a nonempty absolute path without outer whitespace",
        )
    if any(
        ord(character) < 32
        or ord(character) == 127
        or character in {"\u2028", "\u2029"}
        for character in value
    ):
        raise HostPathError(
            "INVALID_HOST_PATH",
            "path contains a control character",
        )

    if value.startswith(("\\\\", "//")):
        return _parse_unc_path(
            value,
            allow_trailing_separator=allow_trailing_separator,
        )

    drive_match = _WINDOWS_DRIVE_PREFIX.match(value)
    if drive_match is not None:
        if len(value) < 3 or value[2] not in {"\\", "/"}:
            raise HostPathError(
                "INVALID_HOST_PATH",
                "expected a drive-absolute path such as Y:/folder/file.wav",
            )
        components = _windows_components(
            value[3:],
            allow_trailing_separator=allow_trailing_separator,
        )
        drive = drive_match.group(1).upper()
        pure_path = PureWindowsPath(f"{drive}:\\", *components)
        if not pure_path.is_absolute():  # defensive guard around flavor rules
            raise HostPathError("INVALID_HOST_PATH", "path must be absolute")
        return ParsedHostPath(
            flavor="drive",
            pure_path=pure_path,
            components=components,
            drive=drive,
        )

    if value.startswith("/"):
        components = _posix_components(
            value[1:],
            allow_trailing_separator=allow_trailing_separator,
        )
        pure_path = PurePosixPath("/", *components)
        if not pure_path.is_absolute():  # defensive guard around flavor rules
            raise HostPathError("INVALID_HOST_PATH", "path must be absolute")
        return ParsedHostPath(
            flavor="posix",
            pure_path=pure_path,
            components=components,
        )

    if len(value) >= 2 and value[1] == ":":
        raise HostPathError(
            "INVALID_HOST_PATH",
            "expected a drive-absolute path such as Y:/folder/file.wav",
        )
    raise HostPathError(
        "INVALID_HOST_PATH",
        "expected an absolute POSIX, drive-qualified, or UNC path",
    )


def host_path_comparison_key(value: object) -> HostPathKey:
    """Return a stable key using the path's own filesystem flavor."""

    return parse_absolute_host_path(value).comparison_key()


def parse_relative_host_path(
    value: object,
    *,
    allow_current_directory: bool = False,
    allow_parent_segments: bool = False,
    allow_trailing_separator: bool = False,
) -> ParsedRelativeHostPath:
    """Parse one portable host-relative path without host-OS guessing.

    A backslash selects Windows relative-path semantics; otherwise POSIX
    semantics are used.  Windows semantics accept either separator because
    those are the rules of that path flavor.  Raw components are validated
    before ``pathlib`` can collapse repeated separators or dot segments.
    """

    text = _exact_host_path_text(value)
    windows_path = PureWindowsPath(text)
    posix_path = PurePosixPath(text)
    if windows_path.drive or windows_path.root or posix_path.is_absolute():
        raise HostPathError(
            "INVALID_HOST_PATH",
            "expected a relative host filesystem path",
        )
    if text == ".":
        if not allow_current_directory:
            raise HostPathError(
                "INVALID_HOST_PATH",
                "the current-directory path is outside this contract",
            )
        return ParsedRelativeHostPath(
            flavor="windows" if "\\" in text else "posix",
            pure_path=PurePosixPath("."),
            components=(),
        )

    windows_flavor = "\\" in text
    if windows_flavor:
        suffix = text
        if allow_trailing_separator and suffix.endswith(("\\", "/")):
            suffix = suffix[:-1]
        components = tuple(_WINDOWS_COMPONENT_SEPARATOR.split(suffix))
        flavor: RelativeHostPathFlavor = "windows"
        pure_path: PurePosixPath | PureWindowsPath = PureWindowsPath(*components)
    else:
        suffix = text
        if allow_trailing_separator and suffix.endswith("/"):
            suffix = suffix[:-1]
        components = tuple(suffix.split("/"))
        flavor = "posix"
        pure_path = PurePosixPath(*components)

    if not components or any(component in {"", "."} for component in components):
        raise HostPathError(
            "INVALID_HOST_PATH",
            "relative path must use normalized nonempty components",
        )
    if not allow_parent_segments and ".." in components:
        raise HostPathError(
            "INVALID_HOST_PATH",
            "relative path must not contain parent traversal",
        )
    for component in components:
        if component == "..":
            continue
        _validate_portable_windows_component(component)
    return ParsedRelativeHostPath(
        flavor=flavor,
        pure_path=pure_path,
        components=components,
    )


def localize_waapi_host_path(
    value: object,
    *,
    host_os_name: str | None = None,
    account_home: str | os.PathLike[str] | None = None,
) -> str:
    """Map one WAAPI filesystem path to the current host's native namespace.

    Native Windows keeps drive and UNC paths unchanged apart from ``pathlib``
    separator normalization.  Native POSIX keeps POSIX paths exact and maps
    Wine ``Y:`` to the login account home and ``Z:`` to the POSIX root.  Other
    Windows drives and UNC paths cannot be proven local on POSIX and fail
    closed.
    """

    parsed = parse_absolute_host_path(value, allow_trailing_separator=True)
    effective_os_name = os.name if host_os_name is None else host_os_name
    if effective_os_name == "nt":
        if parsed.flavor == "posix":
            raise HostPathError(
                "HOST_PATH_FLAVOR_UNAVAILABLE",
                "a POSIX path cannot be localized on native Windows",
            )
        return str(parsed.pure_path)
    if effective_os_name != "posix":
        raise HostPathError(
            "HOST_PATH_FLAVOR_UNAVAILABLE",
            "the current operating-system path flavor is unsupported",
            details={"host_os_name": effective_os_name},
        )
    if parsed.flavor == "posix":
        return parsed.pure_path.as_posix()
    if parsed.flavor == "unc":
        raise HostPathError(
            "HOST_PATH_FLAVOR_UNAVAILABLE",
            "a UNC path cannot be mapped to the local POSIX filesystem",
        )

    assert parsed.drive is not None
    if parsed.drive == "Z":
        mapping_root = PurePosixPath("/")
    elif parsed.drive == "Y":
        mapping_root = _login_account_home(account_home)
    else:
        raise HostPathError(
            "HOST_PATH_DRIVE_UNAVAILABLE",
            "the WAAPI path uses an unmappable virtual drive",
            details={"drive": parsed.drive},
        )
    return str(mapping_root.joinpath(*parsed.components))


def _parse_unc_path(
    value: str,
    *,
    allow_trailing_separator: bool,
) -> ParsedHostPath:
    suffix = value[2:]
    if suffix.startswith(("?\\", "?/", ".\\", "./")):
        raise HostPathError(
            "INVALID_HOST_PATH",
            "extended or device UNC paths are outside this contract",
        )
    components = _windows_components(
        suffix,
        allow_trailing_separator=allow_trailing_separator,
    )
    minimum_components = 2 if allow_trailing_separator else 3
    if len(components) < minimum_components:
        raise HostPathError(
            "INVALID_HOST_PATH",
            "UNC paths require nonempty server, share, and file components",
        )
    if components[0] in {"?", "."}:
        raise HostPathError(
            "INVALID_HOST_PATH",
            "extended or device UNC paths are outside this contract",
        )
    pure_path = PureWindowsPath(
        f"\\\\{components[0]}\\{components[1]}\\",
        *components[2:],
    )
    if not pure_path.is_absolute():  # defensive guard around flavor rules
        raise HostPathError("INVALID_HOST_PATH", "UNC path must be absolute")
    return ParsedHostPath(
        flavor="unc",
        pure_path=pure_path,
        components=components,
    )


def _windows_components(
    suffix: str,
    *,
    allow_trailing_separator: bool,
) -> tuple[str, ...]:
    if allow_trailing_separator and suffix.endswith(("\\", "/")):
        suffix = suffix[:-1]
        if not suffix:
            return _raise_empty_components()
    if not suffix:
        return () if allow_trailing_separator else _raise_empty_components()
    components = tuple(_WINDOWS_COMPONENT_SEPARATOR.split(suffix))
    if not components or any(component in {"", ".", ".."} for component in components):
        raise HostPathError(
            "INVALID_HOST_PATH",
            "path must use normalized non-traversing components",
        )
    for component in components:
        _validate_portable_windows_component(component)
    return components


def _validate_portable_windows_component(component: str) -> None:
    if _WINDOWS_UNSAFE_COMPONENT.search(component) is not None:
        raise HostPathError(
            "INVALID_HOST_PATH",
            "path contains a character that is invalid in a portable filename component",
        )
    if component.endswith((" ", ".")):
        raise HostPathError(
            "INVALID_HOST_PATH",
            "portable path components cannot end with a space or period",
        )
    if component.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_COMPONENTS:
        raise HostPathError(
            "INVALID_HOST_PATH",
            "path contains a reserved Windows device-name component",
        )


def _posix_components(
    suffix: str,
    *,
    allow_trailing_separator: bool,
) -> tuple[str, ...]:
    if allow_trailing_separator and suffix.endswith("/"):
        suffix = suffix[:-1]
    if not suffix:
        return () if allow_trailing_separator else _raise_empty_components()
    components = tuple(suffix.split("/"))
    if not components or any(component in {"", ".", ".."} for component in components):
        raise HostPathError(
            "INVALID_HOST_PATH",
            "path must use normalized non-traversing components",
        )
    return components


def _raise_empty_components() -> tuple[str, ...]:
    raise HostPathError(
        "INVALID_HOST_PATH",
        "path must use normalized non-traversing components",
    )


def _exact_host_path_text(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise HostPathError(
            "INVALID_HOST_PATH",
            "expected a nonempty path without outer whitespace",
        )
    if any(
        ord(character) < 32
        or ord(character) == 127
        or character in {"\u2028", "\u2029"}
        for character in value
    ):
        raise HostPathError(
            "INVALID_HOST_PATH",
            "path contains a control character",
        )
    return value


def _login_account_home(
    value: str | os.PathLike[str] | None,
) -> PurePosixPath:
    if value is not None:
        candidate = PurePosixPath(os.fspath(value))
    else:
        try:
            import pwd

            candidate = PurePosixPath(pwd.getpwuid(os.getuid()).pw_dir)
        except (ImportError, KeyError, OSError) as exc:
            raise HostPathError(
                "HOST_ACCOUNT_HOME_UNAVAILABLE",
                "the login account home is unavailable for the WAAPI Y: mapping",
            ) from exc
    if not candidate.is_absolute():
        raise HostPathError(
            "HOST_ACCOUNT_HOME_UNAVAILABLE",
            "the login account home must be an absolute path",
            details={"account_home": str(candidate)},
        )
    return candidate
