from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath

import pytest  # pyright: ignore[reportMissingImports]

from tests.semantic.support.codex_archive_paths import (
    ArchiveRelativePathError,
    archive_absolute_has_relative_suffix,
    archive_absolute_names_equal,
    archive_relative_from_absolute,
    parse_archive_absolute_path,
    parse_archive_relative_path,
)


@pytest.mark.parametrize(
    ("value", "flavor", "canonical"),
    (
        ("outputs/Windows/Bank.bnk", "posix", "outputs/Windows/Bank.bnk"),
        (r"outputs\Windows\Bank.bnk", "windows", "outputs/Windows/Bank.bnk"),
        ("~archive/Bank.bnk", "posix", "~archive/Bank.bnk"),
    ),
)
def test_archive_relative_path_has_one_portable_identity(
    value: str,
    flavor: str,
    canonical: str,
) -> None:
    parsed = parse_archive_relative_path(value)

    assert parsed.source_flavor == flavor
    assert parsed.canonical == canonical
    assert parsed.parts == tuple(canonical.split("/"))


@pytest.mark.parametrize(
    "value",
    (
        "",
        ".",
        "../Bank.bnk",
        r"..\Bank.bnk",
        "outputs//Bank.bnk",
        r"outputs\\Bank.bnk",
        "outputs/./Bank.bnk",
        r"outputs\..\Bank.bnk",
        r"outputs\bad:name.bnk",
        r"outputs\Windows/Bank.bnk",
        "outputs/bad:name.bnk",
        "outputs/bad*.bnk",
        "outputs/CON.txt",
        "outputs/lpt1",
        "outputs\\bad-name. ",
        "outputs/Bank.bnk/",
        "outputs/Bank.bnk ",
        "/outputs/Bank.bnk",
        r"C:\outputs\Bank.bnk",
        r"C:outputs\Bank.bnk",
        r"\\server\share\Bank.bnk",
    ),
)
def test_archive_relative_path_rejects_absolute_ambiguous_or_traversing_input(
    value: str,
) -> None:
    with pytest.raises(ArchiveRelativePathError):
        parse_archive_relative_path(value)


@pytest.mark.parametrize(
    ("value", "flavor", "expected"),
    (
        ("/campaign/output", "posix", PurePosixPath("/campaign/output")),
        (
            r"C:\Campaign\output",
            "windows",
            PureWindowsPath(r"C:\Campaign\output"),
        ),
        (
            r"\\StudioNas\Share\Campaign",
            "windows",
            PureWindowsPath(r"\\StudioNas\Share\Campaign"),
        ),
    ),
)
def test_archive_absolute_path_selects_explicit_source_flavor(
    value: str,
    flavor: str,
    expected: PurePosixPath | PureWindowsPath,
) -> None:
    parsed = parse_archive_absolute_path(value)

    assert parsed.source_flavor == flavor
    assert parsed.pure_path == expected


def test_absolute_archive_identity_and_basename_follow_source_case_semantics() -> None:
    windows_upper = parse_archive_absolute_path(r"C:\Campaign\Audio\Thunder.WAV")
    windows_lower = parse_archive_absolute_path(r"c:\campaign\audio\thunder.wav")
    unc_lower = parse_archive_absolute_path(r"\\server\share\audio\thunder.wav")
    posix_upper = parse_archive_absolute_path("/campaign/audio/Thunder.WAV")
    posix_lower = parse_archive_absolute_path("/campaign/audio/thunder.wav")

    assert windows_upper == windows_lower
    assert hash(windows_upper) == hash(windows_lower)
    assert posix_upper != posix_lower
    assert windows_upper.name == "Thunder.WAV"
    assert archive_absolute_names_equal(windows_upper.pure_path, posix_lower.pure_path)
    assert archive_absolute_names_equal(unc_lower.pure_path, posix_upper.pure_path)
    assert not archive_absolute_names_equal(posix_upper.pure_path, posix_lower.pure_path)


@pytest.mark.parametrize(
    "value",
    (
        "campaign/output",
        "/campaign//output",
        "/campaign/../output",
        "/campaign/output/",
        r"C:\Campaign\\output",
        r"C:\Campaign\..\output",
        r"C:\Campaign/output",
        "C:/Campaign/output/",
        r"\\?\C:\Campaign\output",
        r"\\.\C:\Campaign\output",
        r"\\server\\share\Campaign",
    ),
)
def test_archive_absolute_path_rejects_relative_or_normalizing_spelling(
    value: str,
) -> None:
    with pytest.raises(ArchiveRelativePathError):
        parse_archive_absolute_path(value)


@pytest.mark.parametrize(
    ("path", "root", "flavor", "canonical"),
    (
        (
            r"C:\Campaign\outputs\Windows\Bank.bnk",
            r"c:\campaign",
            "windows",
            "outputs/Windows/Bank.bnk",
        ),
        (
            r"\\StudioNas\Share\Campaign\Bank.bnk",
            r"//studionas/share/Campaign",
            "windows",
            "Bank.bnk",
        ),
        (
            "/campaign/outputs/Bank.bnk",
            "/campaign",
            "posix",
            "outputs/Bank.bnk",
        ),
    ),
)
def test_absolute_archive_path_derives_a_canonical_relative_identity(
    path: str,
    root: str,
    flavor: str,
    canonical: str,
) -> None:
    parsed = archive_relative_from_absolute(path, root)

    assert parsed.source_flavor == flavor
    assert parsed.canonical == canonical


@pytest.mark.parametrize(
    ("path", "root"),
    (
        (r"C:\other\Bank.bnk", r"C:\campaign"),
        (r"C:\campaign", r"C:\campaign"),
        (r"C:\campaign\..\other\Bank.bnk", r"C:\campaign"),
        (r"C:\campaign\\Bank.bnk", r"C:\campaign"),
        (r"C:\campaign\Bank.bnk", "/campaign"),
        ("/other/Bank.bnk", "/campaign"),
        ("/campaign", "/campaign"),
        ("/campaign/bad*.bnk", "/campaign"),
        ("/campaign/CON.txt", "/campaign"),
        (r"/campaign/name\with-backslash.bnk", "/campaign"),
    ),
)
def test_absolute_archive_path_rejects_escape_mismatch_and_normalizing_input(
    path: str,
    root: str,
) -> None:
    with pytest.raises(ArchiveRelativePathError):
        archive_relative_from_absolute(path, root)


@pytest.mark.parametrize(
    ("absolute", "relative", "expected"),
    (
        (
            r"C:\Campaign\Originals\SFX\Thunder.WAV",
            "Originals/SFX/thunder.wav",
            True,
        ),
        (
            r"\\StudioNas\Share\Campaign\Originals\SFX\Thunder.WAV",
            r"originals\sfx\thunder.wav",
            True,
        ),
        (
            "/campaign/Originals/SFX/Thunder.WAV",
            "Originals/SFX/Thunder.WAV",
            True,
        ),
        (
            "/campaign/Originals/SFX/Thunder.WAV",
            "Originals/SFX/thunder.wav",
            False,
        ),
        (
            r"C:\Campaign\Elsewhere\Thunder.wav",
            "Originals/SFX/Thunder.wav",
            False,
        ),
    ),
)
def test_absolute_archive_suffix_uses_the_absolute_path_flavor(
    absolute: str,
    relative: str,
    expected: bool,
) -> None:
    assert archive_absolute_has_relative_suffix(absolute, relative) is expected


@pytest.mark.parametrize(
    ("absolute", "relative"),
    (
        ("relative/Originals/test.wav", "Originals/test.wav"),
        (r"C:\Campaign\Originals\test.wav", "../test.wav"),
        (r"C:\Campaign\Originals\test.wav", r"Originals/SFX\test.wav"),
    ),
)
def test_absolute_archive_suffix_rejects_malformed_inputs(
    absolute: str,
    relative: str,
) -> None:
    with pytest.raises(ArchiveRelativePathError):
        archive_absolute_has_relative_suffix(absolute, relative)
