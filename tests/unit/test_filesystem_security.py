from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from wwise_waapi.filesystem_security import (
    metadata_is_link_or_reparse,
    path_is_link_or_reparse,
)


def test_windows_reparse_attribute_is_detected_off_host() -> None:
    metadata = SimpleNamespace(st_mode=0o100600, st_file_attributes=0x0400)

    assert metadata_is_link_or_reparse(metadata) is True
    assert path_is_link_or_reparse(Path("ordinary-name"), metadata=metadata) is True


def test_plain_regular_metadata_is_not_a_reparse_point() -> None:
    metadata = SimpleNamespace(st_mode=0o100600, st_file_attributes=0)

    assert metadata_is_link_or_reparse(metadata) is False
