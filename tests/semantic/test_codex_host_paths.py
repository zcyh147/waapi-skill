from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath

import pytest

from tests.semantic.support.codex_host_paths import (
    ReflectedHostPathError,
    parse_posix_absolute_path,
    parse_windows_drive_path,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        (
            r"Y:\Documents\case\Originals\Voice.wav",
            PureWindowsPath(r"Y:\Documents\case\Originals\Voice.wav"),
        ),
        (
            "c:/Projects/SampleProject.wproj",
            PureWindowsPath(r"C:\Projects\SampleProject.wproj"),
        ),
        (
            r"D:\~archive\Voice.wav",
            PureWindowsPath(r"D:\~archive\Voice.wav"),
        ),
    ),
)
def test_windows_drive_parser_is_independent_of_the_host_flavour(
    value: str,
    expected: PureWindowsPath,
) -> None:
    parsed = parse_windows_drive_path(value)

    assert parsed is not None
    assert parsed.pure == expected
    assert parsed.drive == expected.drive[0].upper()
    assert parsed.relative_parts == expected.parts[1:]


@pytest.mark.parametrize(
    "value",
    (
        r"\\server\share\file.wav",
        r"Y:relative\file.wav",
        r"Y:\case\.\file.wav",
        r"Y:\case\..\file.wav",
        r"Y:\case\\file.wav",
        "Y:/case/file.wav/",
    ),
)
def test_windows_drive_parser_rejects_ambiguous_or_normalizing_spellings(
    value: str,
) -> None:
    with pytest.raises(ReflectedHostPathError):
        parse_windows_drive_path(value)


def test_posix_parser_is_independent_of_the_host_flavour() -> None:
    assert parse_posix_absolute_path(
        "/Users/test/Originals/Voice.wav"
    ) == PurePosixPath("/Users/test/Originals/Voice.wav")
    assert parse_posix_absolute_path(
        "/data/~archive/Voice.wav"
    ) == PurePosixPath("/data/~archive/Voice.wav")


@pytest.mark.parametrize(
    "value",
    (
        "relative/file.wav",
        "/case/./file.wav",
        "/case/../file.wav",
        "/case//file.wav",
        "/case/file.wav/",
        r"\case\file.wav",
    ),
)
def test_posix_parser_rejects_ambiguous_or_normalizing_spellings(
    value: str,
) -> None:
    with pytest.raises(ReflectedHostPathError):
        parse_posix_absolute_path(value)
