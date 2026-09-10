from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.host_paths import (  # pyright: ignore[reportMissingImports]
    HostPathError,
    host_path_comparison_key,
    localize_waapi_host_path,
    parse_absolute_host_path,
    parse_relative_host_path,
)
from tests.support.host_path_relatives import (  # pyright: ignore[reportMissingImports]
    relative_host_path,
)


def test_absolute_host_path_parser_keeps_pathlib_flavors_separate() -> None:
    posix = parse_absolute_host_path(r"/srv/audio/a\b.wav")
    drive = parse_absolute_host_path(r"C:\Audio/Mix.wav")
    unc = parse_absolute_host_path(r"\\StudioNas\Share/Mix.wav")

    assert posix.flavor == "posix"
    assert posix.pure_path == PurePosixPath(r"/srv/audio/a\b.wav")
    assert posix.components == ("srv", "audio", r"a\b.wav")
    assert drive.flavor == "drive"
    assert drive.pure_path == PureWindowsPath(r"C:\Audio\Mix.wav")
    assert drive.components == ("Audio", "Mix.wav")
    assert unc.flavor == "unc"
    assert unc.pure_path == PureWindowsPath(r"\\StudioNas\Share\Mix.wav")
    assert unc.components == ("StudioNas", "Share", "Mix.wav")


def test_host_path_keys_follow_the_source_filesystem_case_and_separator_rules() -> None:
    assert host_path_comparison_key(r"C:\Audio\Mix.wav") == (
        "drive",
        "c",
        "audio",
        "mix.wav",
    )
    assert host_path_comparison_key(r"C:\Audio\Mix.wav") == (
        host_path_comparison_key("c:/audio/MIX.WAV")
    )
    assert host_path_comparison_key(r"\\StudioNas\Share\Mix.wav") == (
        host_path_comparison_key("//studionas/share/MIX.WAV")
    )

    assert host_path_comparison_key("/srv/audio/Mix.wav") != (
        host_path_comparison_key("/srv/audio/mix.wav")
    )
    assert host_path_comparison_key(r"/srv/audio/a\b.wav") != (
        host_path_comparison_key("/srv/audio/a/b.wav")
    )


def test_waapi_host_path_localization_uses_pathlib_for_native_and_wine_paths() -> None:
    account_home = PurePosixPath("/Users/tester")
    assert localize_waapi_host_path(
        r"Y:\Projects\SampleProject.wproj",
        host_os_name="posix",
        account_home=account_home,
    ) == "/Users/tester/Projects/SampleProject.wproj"
    assert localize_waapi_host_path(
        r"Z:\Volumes\Projects\SampleProject.wproj",
        host_os_name="posix",
        account_home=account_home,
    ) == "/Volumes/Projects/SampleProject.wproj"
    assert localize_waapi_host_path(
        "Y:/",
        host_os_name="posix",
        account_home=account_home,
    ) == "/Users/tester"
    assert localize_waapi_host_path(
        "Z:\\",
        host_os_name="posix",
        account_home=account_home,
    ) == "/"
    assert localize_waapi_host_path(
        r"/srv/projects/name\with-backslash/SampleProject.wproj",
        host_os_name="posix",
        account_home=account_home,
    ) == r"/srv/projects/name\with-backslash/SampleProject.wproj"

    assert localize_waapi_host_path(
        "c:/Projects/SampleProject.wproj",
        host_os_name="nt",
    ) == r"C:\Projects\SampleProject.wproj"
    assert localize_waapi_host_path("C:/", host_os_name="nt") == "C:\\"
    assert localize_waapi_host_path(
        "//studionas/share/SampleProject.wproj",
        host_os_name="nt",
    ) == r"\\studionas\share\SampleProject.wproj"


@pytest.mark.parametrize(
    "value",
    (
        "relative/file.wav",
        r"C:file.wav",
        r"C:\Folder\..\file.wav",
        r"C:\Folder\\file.wav",
        "C:/Folder/file.wav/",
        r"\\server\share",
        r"\\?\C:\file.wav",
        r"C:\Audio\NUL.wav",
        r"C:\Audio\com1",
        r"\\server\share\LPT9.txt",
        "/srv/./file.wav",
        "/srv//file.wav",
    ),
)
def test_absolute_host_path_parser_rejects_ambiguous_or_normalizing_inputs(
    value: str,
) -> None:
    with pytest.raises(HostPathError):
        parse_absolute_host_path(value)


@pytest.mark.parametrize(
    "value",
    (
        r"C:\Projects\SampleProject.wproj",
        r"\\server\share\SampleProject.wproj",
    ),
)
def test_posix_localization_rejects_unproven_windows_namespaces(value: str) -> None:
    with pytest.raises(HostPathError):
        localize_waapi_host_path(
            value,
            host_os_name="posix",
            account_home="/Users/tester",
        )


def test_native_windows_localization_rejects_a_posix_path() -> None:
    with pytest.raises(HostPathError):
        localize_waapi_host_path(
            "/srv/projects/SampleProject.wproj",
            host_os_name="nt",
        )


def test_relative_host_path_parser_uses_explicit_pathlib_flavors() -> None:
    windows = parse_relative_host_path(r"GeneratedSoundBanks\Windows/Bank.bnk")
    posix = parse_relative_host_path("GeneratedSoundBanks/Linux/Bank.bnk")
    parent = parse_relative_host_path(
        r"..\GeneratedSoundBanks\Windows",
        allow_parent_segments=True,
    )
    current = parse_relative_host_path(".", allow_current_directory=True)

    assert windows.flavor == "windows"
    assert windows.pure_path == PureWindowsPath(
        r"GeneratedSoundBanks\Windows\Bank.bnk"
    )
    assert windows.components == ("GeneratedSoundBanks", "Windows", "Bank.bnk")
    assert posix.flavor == "posix"
    assert posix.pure_path == PurePosixPath("GeneratedSoundBanks/Linux/Bank.bnk")
    assert posix.components == ("GeneratedSoundBanks", "Linux", "Bank.bnk")
    assert parent.components == ("..", "GeneratedSoundBanks", "Windows")
    assert current.components == ()


def test_relative_host_path_preserves_posix_case_and_hostile_components() -> None:
    target = PurePosixPath("/Workspace/Owned/External Media/音频;$HOME&mix")
    base = PurePosixPath("/workspace/Owned/Sandbox/Project")

    assert relative_host_path(target, base).as_posix() == (
        "../../../../Workspace/Owned/External Media/音频;$HOME&mix"
    )


def test_relative_host_path_uses_windows_drive_case_and_mixed_separator_rules() -> None:
    target = PureWindowsPath(r"C:\Work/Owned\External Media/音频;$HOME&mix")
    base = PureWindowsPath(r"c:/work\owned/Sandbox/Project")

    assert relative_host_path(target, base).as_posix() == (
        "../../External Media/音频;$HOME&mix"
    )


def test_relative_host_path_uses_unc_share_case_semantics() -> None:
    target = PureWindowsPath(
        r"\\StudioNas\Release Share\Owned\External Media\音频;$HOME&mix"
    )
    base = PureWindowsPath(
        r"\\studionas\release share\Owned\Sandbox\Project"
    )

    assert relative_host_path(target, base).as_posix() == (
        "../../External Media/音频;$HOME&mix"
    )


@pytest.mark.parametrize(
    ("target", "base"),
    (
        (PureWindowsPath(r"C:\Media\file.wav"), PureWindowsPath(r"D:\Project")),
        (
            PureWindowsPath(r"\\server\share-a\Media\file.wav"),
            PureWindowsPath(r"\\server\share-b\Project"),
        ),
        (PurePosixPath("/srv/media/file.wav"), PureWindowsPath(r"C:\Project")),
    ),
)
def test_relative_host_path_rejects_cross_namespace_inputs(
    target: PurePosixPath | PureWindowsPath,
    base: PurePosixPath | PureWindowsPath,
) -> None:
    with pytest.raises(ValueError):
        relative_host_path(target, base)


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
        r"C:\outputs\Bank.bnk",
        r"C:outputs\Bank.bnk",
        r"\\server\share\Bank.bnk",
        "outputs/NUL.txt",
        "outputs/bad*.bnk",
        "outputs/Bank.bnk/",
    ),
)
def test_relative_host_path_parser_rejects_absolute_or_normalizing_input(
    value: str,
) -> None:
    with pytest.raises(HostPathError):
        parse_relative_host_path(value)


@pytest.mark.parametrize(
    ("value", "host_os_name"),
    (
        ("Y://", "posix"),
        (r"Z:\\", "posix"),
        ("C://", "nt"),
    ),
)
def test_localization_does_not_fold_repeated_root_separators(
    value: str,
    host_os_name: str,
) -> None:
    with pytest.raises(HostPathError):
        localize_waapi_host_path(
            value,
            host_os_name=host_os_name,
            account_home="/Users/tester",
        )
