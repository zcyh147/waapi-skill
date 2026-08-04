from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.semantic.support import codex_integration_fixture_tree_v2 as fixture_tree


def _fixture(root: Path) -> None:
    (root / "Work Units").mkdir(parents=True)
    (root / "Project.wproj").write_bytes(b"project\n")
    (root / "Work Units" / "Default Work Unit.wwu").write_bytes(b"work-unit\n")


def test_wwise_fixture_tree_digest_ignores_host_executable_bits(
    tmp_path: Path,
) -> None:
    root = tmp_path / "fixture"
    _fixture(root)
    before = fixture_tree.wwise_fixture_tree_sha256(root)

    if os.name == "posix":
        (root / "Project.wproj").chmod(0o755)
        (root / "Work Units").chmod(0o700)

    assert fixture_tree.wwise_fixture_tree_sha256(root) == before
    assert all(
        "executable" not in row
        for row in fixture_tree.wwise_fixture_tree_manifest(root)
    )


def test_wwise_fixture_tree_digest_binds_path_type_and_content(
    tmp_path: Path,
) -> None:
    root = tmp_path / "fixture"
    _fixture(root)
    original = fixture_tree.wwise_fixture_tree_sha256(root)

    project = root / "Project.wproj"
    project.write_bytes(b"changed\n")
    changed_content = fixture_tree.wwise_fixture_tree_sha256(root)
    assert changed_content != original

    project.rename(root / "Renamed.wproj")
    changed_path = fixture_tree.wwise_fixture_tree_sha256(root)
    assert changed_path not in {original, changed_content}

    renamed = root / "Renamed.wproj"
    renamed.unlink()
    renamed.mkdir()
    changed_type = fixture_tree.wwise_fixture_tree_sha256(root)
    assert changed_type not in {original, changed_content, changed_path}


def test_wwise_fixture_tree_digest_ignores_empty_directories(tmp_path: Path) -> None:
    root = tmp_path / "fixture"
    _fixture(root)
    before = fixture_tree.wwise_fixture_tree_sha256(root)

    (root / "Originals" / "Voices" / "English(US)").mkdir(parents=True)

    assert fixture_tree.wwise_fixture_tree_sha256(root) == before
    assert all(
        row["type"] == "file"
        for row in fixture_tree.wwise_fixture_tree_manifest(root)
    )


def test_wwise_fixture_tree_digest_binds_extra_regular_file(tmp_path: Path) -> None:
    root = tmp_path / "fixture"
    _fixture(root)
    before = fixture_tree.wwise_fixture_tree_sha256(root)

    (root / "unexpected.txt").write_bytes(b"unexpected\n")

    assert fixture_tree.wwise_fixture_tree_sha256(root) != before


def test_wwise_fixture_tree_rejects_link_or_reparse_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "fixture"
    _fixture(root)
    unsafe = root / "Project.wproj"
    original = fixture_tree.path_is_link_or_reparse
    monkeypatch.setattr(
        fixture_tree,
        "path_is_link_or_reparse",
        lambda path, *, metadata=None: path == unsafe
        or original(path, metadata=metadata),
    )

    with pytest.raises(
        fixture_tree.IntegrationFixtureTreeError,
        match="symlinks, junctions, or reparse points",
    ):
        fixture_tree.wwise_fixture_tree_manifest(root)


def test_wwise_fixture_tree_rejects_special_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "fixture"
    _fixture(root)
    monkeypatch.setattr(fixture_tree.stat, "S_ISREG", lambda _mode: False)

    with pytest.raises(
        fixture_tree.IntegrationFixtureTreeError,
        match="special filesystem entry",
    ):
        fixture_tree.wwise_fixture_tree_manifest(root)
