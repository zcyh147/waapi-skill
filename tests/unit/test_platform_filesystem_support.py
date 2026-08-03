from __future__ import annotations

from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from tests.support.platform_filesystem import (
    create_symlink_or_skip,
    is_windows_symlink_privilege_error,
)


def _windows_error(code: int) -> OSError:
    error = OSError("synthetic Windows error")
    error.winerror = code  # type: ignore[attr-defined]
    return error


def test_symlink_privilege_classifier_is_exact_to_windows_1314() -> None:
    assert is_windows_symlink_privilege_error(_windows_error(1314), platform_name="nt")
    assert not is_windows_symlink_privilege_error(_windows_error(5), platform_name="nt")
    assert not is_windows_symlink_privilege_error(_windows_error(1314), platform_name="posix")


def test_symlink_helper_skips_only_windows_privilege_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    error = _windows_error(1314)

    def denied(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr(Path, "symlink_to", denied)
    monkeypatch.setattr("tests.support.platform_filesystem.os.name", "nt")

    with pytest.raises(pytest.skip.Exception):
        create_symlink_or_skip(tmp_path / "link", tmp_path / "target")


def test_symlink_helper_does_not_hide_other_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    error = _windows_error(5)

    def denied(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr(Path, "symlink_to", denied)
    monkeypatch.setattr("tests.support.platform_filesystem.os.name", "nt")

    with pytest.raises(OSError) as caught:
        create_symlink_or_skip(tmp_path / "link", tmp_path / "target")
    assert caught.value is error
