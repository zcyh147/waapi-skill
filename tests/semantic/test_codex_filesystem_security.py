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
