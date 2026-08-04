from __future__ import annotations

import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.semantic.support import codex_filesystem_security as filesystem


def _restrict_owner_only_on_posix(path: Path) -> None:
    if os.name == "posix":
        path.chmod(0o600)


def test_binary_file_open_flags_include_windows_binary_and_close_on_exec_bits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(filesystem.os, "O_BINARY", 0x8000, raising=False)
    monkeypatch.setattr(filesystem.os, "O_CLOEXEC", 0x80000, raising=False)

    assert filesystem.binary_file_open_flags(os.O_WRONLY, os.O_CREAT) == (
        os.O_WRONLY | os.O_CREAT | 0x8000 | 0x80000
    )


def test_binary_file_open_flags_reject_non_integer_flags() -> None:
    with pytest.raises(TypeError, match="must be integers"):
        filesystem.binary_file_open_flags("read-only")  # type: ignore[arg-type]


def test_utf8_archive_writer_keeps_explicit_lf_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "protocol.txt"
    monkeypatch.setattr(
        Path,
        "write_text",
        lambda *_args, **_kwargs: pytest.fail("text-mode writer was used"),
    )

    filesystem.write_utf8_text_bytes(path, "第一行\nsecond\n")

    assert path.read_bytes() == "第一行\nsecond\n".encode("utf-8")
    assert b"\r" not in path.read_bytes()


@pytest.mark.parametrize(
    ("platform_name", "mode", "expected"),
    (
        ("posix", stat.S_IFREG | 0o600, True),
        ("posix", stat.S_IFREG | 0o644, False),
        ("nt", stat.S_IFREG | 0o600, True),
        ("nt", stat.S_IFREG | 0o644, True),
    ),
)
def test_private_mode_policy_is_posix_only(
    platform_name: str,
    mode: int,
    expected: bool,
) -> None:
    metadata = SimpleNamespace(st_mode=mode)

    assert (
        filesystem.private_posix_mode_is_valid(
            metadata,
            platform_name=platform_name,
        )
        is expected
    )


def test_reparse_attribute_is_rejected_independently_of_posix_mode(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ack.json"
    path.write_bytes(b"{}\n")
    metadata = SimpleNamespace(
        st_mode=stat.S_IFREG | 0o600,
        st_file_attributes=0x400,
    )

    assert filesystem.metadata_is_reparse_point(metadata) is True
    assert filesystem.path_is_link_or_reparse(path, metadata=metadata) is True


def _stat_observation(**overrides: int) -> SimpleNamespace:
    values = {
        "st_dev": 7,
        "st_ino": 11,
        "st_mode": stat.S_IFREG | 0o600,
        "st_nlink": 1,
        "st_size": 13,
        "st_mtime_ns": 17,
        "st_ctime_ns": 19,
        "st_file_attributes": 32,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_windows_path_handle_snapshot_ignores_unstable_cross_api_fields() -> None:
    path_observation = _stat_observation()
    handle_observation = _stat_observation(
        st_mode=stat.S_IFREG | 0o666,
        st_nlink=2,
        st_ctime_ns=23,
    )

    assert filesystem.same_regular_file_path_handle_snapshot(
        path_observation,
        handle_observation,
        platform_name="nt",
    )
    assert not filesystem.same_regular_file_path_handle_snapshot(
        path_observation,
        handle_observation,
        platform_name="posix",
    )


@pytest.mark.parametrize(
    "changed",
    (
        {"st_ino": 12},
        {"st_mode": stat.S_IFDIR | 0o600},
        {"st_size": 14},
        {"st_mtime_ns": 18},
        {"st_file_attributes": 33},
    ),
    ids=("identity", "file-kind", "size", "mtime", "file-attributes"),
)
def test_windows_path_handle_snapshot_keeps_portable_drift_checks(
    changed: dict[str, int],
) -> None:
    assert not filesystem.same_regular_file_path_handle_snapshot(
        _stat_observation(),
        _stat_observation(**changed),
        platform_name="nt",
    )


def test_handle_snapshot_keeps_full_metadata_checks_on_windows() -> None:
    assert not filesystem.same_regular_file_handle_snapshot(
        _stat_observation(),
        _stat_observation(st_ctime_ns=23),
    )


def test_bounded_reader_preserves_exact_bytes_and_descriptor_identity(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ack.json"
    path.write_bytes(b'{"ok":true}\n')
    _restrict_owner_only_on_posix(path)

    snapshot = filesystem.read_bounded_exclusive_regular_file(
        path,
        max_bytes=64,
    )

    assert snapshot.raw == b'{"ok":true}\n'
    assert stat.S_ISREG(snapshot.metadata.st_mode)
    assert snapshot.metadata.st_nlink == 1


def test_bounded_reader_windows_policy_keeps_integrity_checks_without_mode_bits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "ack.json"
    path.write_bytes(b'{"ok":true}\n')
    path.chmod(0o644)
    monkeypatch.setattr(filesystem, "_platform_name", lambda: "nt")

    snapshot = filesystem.read_bounded_exclusive_regular_file(
        path,
        max_bytes=64,
    )

    assert snapshot.raw == b'{"ok":true}\n'
    assert snapshot.metadata.st_nlink == 1


def test_bounded_reader_requires_explicit_opt_out_for_ordinary_posix_media(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "source.wav"
    path.write_bytes(b"RIFF-media")
    path.chmod(0o644)
    monkeypatch.setattr(
        filesystem,
        "private_posix_mode_is_valid",
        lambda _metadata: False,
    )

    with pytest.raises(filesystem.CodexFileSecurityError, match="exclusive"):
        filesystem.read_bounded_exclusive_regular_file(path, max_bytes=64)

    snapshot = filesystem.read_bounded_exclusive_regular_file(
        path,
        max_bytes=64,
        require_private_posix_mode=False,
    )

    assert snapshot.raw == b"RIFF-media"
    assert snapshot.metadata.st_nlink == 1


def test_bounded_reader_requires_explicit_opt_in_for_an_empty_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "stderr.txt"
    path.write_bytes(b"")
    _restrict_owner_only_on_posix(path)

    with pytest.raises(filesystem.CodexFileSecurityError, match="exclusive"):
        filesystem.read_bounded_exclusive_regular_file(path, max_bytes=64)

    snapshot = filesystem.read_bounded_exclusive_regular_file(
        path,
        max_bytes=64,
        allow_empty=True,
    )

    assert snapshot.raw == b""
    assert snapshot.metadata.st_size == 0
    assert snapshot.metadata.st_nlink == 1


def test_bounded_reader_rejects_multiple_hard_links(tmp_path: Path) -> None:
    path = tmp_path / "ack.json"
    path.write_bytes(b'{"ok":true}\n')
    _restrict_owner_only_on_posix(path)
    (tmp_path / "duplicate.json").hardlink_to(path)

    with pytest.raises(filesystem.CodexFileSecurityError, match="exclusive"):
        filesystem.read_bounded_exclusive_regular_file(path, max_bytes=64)


def test_bounded_reader_rejects_path_swap_during_descriptor_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "ack.json"
    replacement = tmp_path / "replacement.json"
    path.write_bytes(b'{"value":"original"}\n')
    replacement.write_bytes(b'{"value":"forged"}\n')
    _restrict_owner_only_on_posix(path)
    _restrict_owner_only_on_posix(replacement)
    real_open = filesystem.os.open
    swapped = False

    def swapping_open(candidate: Path, flags: int, mode: int = 0o777) -> int:
        nonlocal swapped
        if Path(candidate) == path and not swapped:
            replacement.replace(path)
            swapped = True
        return real_open(candidate, flags, mode)

    monkeypatch.setattr(filesystem.os, "open", swapping_open)

    with pytest.raises(filesystem.CodexFileSecurityError, match="descriptor"):
        filesystem.read_bounded_exclusive_regular_file(path, max_bytes=64)
