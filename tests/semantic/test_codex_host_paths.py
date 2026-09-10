from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath

import pytest

from tests.semantic.support.codex_host_paths import (
    ReflectedHostPathError,
    parse_posix_absolute_path,
    parse_relative_host_path,
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
    ("value", "expected"),
    (
        (
            "Y:/Documents/case/GeneratedSoundBanks/",
            PureWindowsPath(r"Y:\Documents\case\GeneratedSoundBanks"),
        ),
        (
            "Y:\\Documents\\case\\GeneratedSoundBanks\\",
            PureWindowsPath(r"Y:\Documents\case\GeneratedSoundBanks"),
        ),
        (
            "y:/Harbor Mixed\\港口/Generated Banks\\",
            PureWindowsPath("y:/Harbor Mixed/港口/Generated Banks"),
        ),
        ("Y:\\", PureWindowsPath("Y:/")),
    ),
)
def test_windows_drive_parser_accepts_one_trailing_directory_separator_only_when_enabled(
    value: str,
    expected: PureWindowsPath,
) -> None:
    with pytest.raises(ReflectedHostPathError):
        parse_windows_drive_path(value)

    parsed = parse_windows_drive_path(value, allow_trailing_separator=True)

    assert parsed is not None
    assert parsed.pure == expected
    assert parsed.drive == expected.drive[0].upper()
    assert parsed.relative_parts == expected.parts[1:]


@pytest.mark.parametrize(
    "value",
    (
        "Y:/case/../outside/",
        "Y:/case//output/",
        "Y:/case/output//",
        "\\\\server\\share\\output\\",
    ),
)
def test_windows_directory_parser_still_rejects_traversal_repeats_and_unc(
    value: str,
) -> None:
    with pytest.raises(ReflectedHostPathError):
        parse_windows_drive_path(value, allow_trailing_separator=True)


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
    ("value", "expected"),
    (
        ("/Users/test/GeneratedSoundBanks/", "/Users/test/GeneratedSoundBanks"),
        ("/Users/测试/Harbor Builds/", "/Users/测试/Harbor Builds"),
        ("/", "/"),
    ),
)
def test_posix_parser_accepts_one_trailing_directory_separator_only_when_enabled(
    value: str,
    expected: str,
) -> None:
    with pytest.raises(ReflectedHostPathError):
        parse_posix_absolute_path(value)

    assert parse_posix_absolute_path(
        value,
        allow_trailing_separator=True,
    ) == PurePosixPath(expected)


@pytest.mark.parametrize(
    "value",
    (
        "/case/../outside/",
        "/case//output/",
        "/case/output//",
        "//",
        "//server/share/output/",
    ),
)
def test_posix_directory_parser_still_rejects_traversal_repeats_and_unc(
    value: str,
) -> None:
    with pytest.raises(ReflectedHostPathError):
        parse_posix_absolute_path(value, allow_trailing_separator=True)


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


def test_semantic_relative_parser_preserves_parent_segments_and_trailing_separator() -> None:
    parsed = parse_relative_host_path(
        "..\\..\\io\\soundbanks\\Windows\\",
        allow_parent_segments=True,
        allow_trailing_separator=True,
    )

    assert parsed.flavor == "windows"
    assert parsed.relative_parts == ("..", "..", "io", "soundbanks", "Windows")
    assert parsed.pure == PureWindowsPath(r"..\..\io\soundbanks\Windows")


@pytest.mark.parametrize(
    "value",
    (
        r"..\.\io\soundbanks",
        r"..\\io\soundbanks",
        r"C:\io\soundbanks",
        r"\\server\share\soundbanks",
        "..\\io\\soundbanks ",
        r"..\NUL\soundbanks",
    ),
)
def test_semantic_relative_parser_rejects_noncanonical_windows_spelling(
    value: str,
) -> None:
    with pytest.raises(ReflectedHostPathError):
        parse_relative_host_path(
            value,
            allow_parent_segments=True,
            allow_trailing_separator=True,
        )
