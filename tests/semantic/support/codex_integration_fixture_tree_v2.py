"""Portable tree identity for committed integration-workflows-v2 fixtures.

The committed Wwise SampleProject sources are copied between native macOS and
Windows hosts.  Their identity therefore binds only portable relative paths,
entry kinds, and regular-file contents.  Host executable bits are deliberately
excluded.  Links, junctions, reparse points, and special files are rejected so
the digest never depends on host-specific traversal behavior.
"""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path, PurePosixPath
from typing import Any

from tests.semantic.support.codex_archive_paths import (
    ArchiveRelativePathError,
    parse_archive_relative_path,
)
from tests.semantic.support.codex_campaign import (
    CampaignEvidenceError,
    canonical_json_bytes,
    sha256_file,
)
from tests.semantic.support.codex_filesystem_security import path_is_link_or_reparse


class IntegrationFixtureTreeError(RuntimeError):
    """A committed Wwise fixture tree is not portable or safely traversable."""


def wwise_fixture_tree_manifest(root: Path) -> tuple[dict[str, Any], ...]:
    """Return the strict, host-independent manifest for one Wwise fixture."""

    tree = Path(root)
    try:
        root_metadata = tree.lstat()
    except OSError as exc:
        raise IntegrationFixtureTreeError(
            f"cannot inspect Wwise fixture root {tree}: {exc}"
        ) from exc
    if (
        path_is_link_or_reparse(tree, metadata=root_metadata)
        or not stat.S_ISDIR(root_metadata.st_mode)
    ):
        raise IntegrationFixtureTreeError(
            f"Wwise fixture root must be one real directory: {tree}"
        )

    rows: list[dict[str, Any]] = []

    def portable_relative(path: Path) -> str:
        try:
            parts = path.relative_to(tree).parts
        except ValueError as exc:
            raise IntegrationFixtureTreeError(
                f"Wwise fixture entry is outside its root: {path}"
            ) from exc
        relative = PurePosixPath(*parts).as_posix()
        try:
            parsed = parse_archive_relative_path(relative)
        except ArchiveRelativePathError as exc:
            raise IntegrationFixtureTreeError(
                f"Wwise fixture path is not portable: {path}: {exc}"
            ) from exc
        if parsed.source_flavor != "posix" or parsed.parts != tuple(parts):
            raise IntegrationFixtureTreeError(
                f"Wwise fixture path has an ambiguous portable identity: {path}"
            )
        return parsed.canonical

    def walk(directory: Path) -> None:
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as exc:
            raise IntegrationFixtureTreeError(
                f"cannot scan Wwise fixture directory {directory}: {exc}"
            ) from exc
        for entry in entries:
            path = Path(entry.path)
            relative = portable_relative(path)
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise IntegrationFixtureTreeError(
                    f"cannot inspect Wwise fixture entry {path}: {exc}"
                ) from exc
            if path_is_link_or_reparse(path, metadata=metadata):
                raise IntegrationFixtureTreeError(
                    "Wwise fixture may not contain symlinks, junctions, or "
                    f"reparse points: {path}"
                )
            if stat.S_ISDIR(metadata.st_mode):
                rows.append({"path": relative, "type": "directory"})
                walk(path)
            elif stat.S_ISREG(metadata.st_mode):
                try:
                    digest = sha256_file(path)
                except CampaignEvidenceError as exc:
                    raise IntegrationFixtureTreeError(
                        f"cannot hash Wwise fixture file {path}: {exc}"
                    ) from exc
                rows.append(
                    {
                        "path": relative,
                        "type": "file",
                        "sha256": digest,
                    }
                )
            else:
                raise IntegrationFixtureTreeError(
                    f"Wwise fixture contains a special filesystem entry: {path}"
                )

    walk(tree)
    rows.sort(key=lambda row: row["path"])
    return tuple(rows)


def wwise_fixture_tree_sha256(root: Path) -> str:
    """Hash a Wwise fixture without host permission metadata."""

    return hashlib.sha256(
        canonical_json_bytes(wwise_fixture_tree_manifest(root))
    ).hexdigest()


__all__ = [
    "IntegrationFixtureTreeError",
    "wwise_fixture_tree_manifest",
    "wwise_fixture_tree_sha256",
]
