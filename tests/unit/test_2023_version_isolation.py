from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.common import (  # pyright: ignore[reportMissingImports]
    BuilderFamily,
    SemanticErrorCode,
    SemanticValidationError,
    require_source_note,
)
from wwise_waapi.builders.source_notes import SemanticSourceNoteChecker  # pyright: ignore[reportMissingImports]
from wwise_waapi.dispatcher import WwiseDispatcher  # pyright: ignore[reportMissingImports]
from wwise_waapi.manifest import ManifestResourceMissingError, ManifestStore  # pyright: ignore[reportMissingImports]


class GuardedPath(type(Path())):
    forbidden_tokens = ("2022.1", "semantic-builder-")

    def _check(self) -> None:
        path_text = self.as_posix()
        if any(token in path_text for token in self.forbidden_tokens):
            raise AssertionError(f"2023.1 lookup touched forbidden fallback path: {path_text}")

    def exists(self, *args: Any, **kwargs: Any) -> bool:
        self._check()
        return super().exists(*args, **kwargs)

    def read_text(self, *args: Any, **kwargs: Any) -> str:
        self._check()
        return super().read_text(*args, **kwargs)


def test_2023_resource_lookup_does_not_fallback_to_2022(tmp_path: Path) -> None:
    root = GuardedPath(tmp_path)
    store = ManifestStore(root=root)
    store.record("2022.1", {"functions": [{"uri": "ak.wwise.core.getInfo"}]})
    store.record("2023.1", {"functions": [{"uri": "ak.should.not.fallback"}]})

    with pytest.raises(ManifestResourceMissingError) as manifest_exc:
        store.load("2023.1")

    assert manifest_exc.value.path == tmp_path / "2023.1" / "manifest.json"

    status = require_source_note(
        SemanticSourceNoteChecker(notebook_id="wwise-2023.1-docs"),
        BuilderFamily.QUERY,
        version="2023.1",
    )

    assert status.allowed is True
    assert status.version == "2023.1"
    assert status.notebook_id == "wwise-2023.1-docs"


def test_manifest_store_explicit_2023_1_missing_manifest_fails_closed_without_2022_1_fallback(tmp_path: Path) -> None:
    root = GuardedPath(tmp_path)
    store = ManifestStore(root=root)
    store.record("2022.1", {"functions": [{"uri": "ak.wwise.core.getInfo"}]})
    store.record("2023.1", {"functions": [{"uri": "ak.should.not.fallback"}]})

    with pytest.raises(ManifestResourceMissingError) as exc:
        store.load("2023.1")

    assert exc.value.version == "2023.1"
    assert exc.value.path == tmp_path / "2023.1" / "manifest.json"


def test_manifest_store_explicit_2023_1_missing_split_files_fails_closed(tmp_path: Path) -> None:
    version_dir = tmp_path / "2023.1"
    version_dir.mkdir(parents=True)
    (version_dir / "manifest.json").write_text('{"audit": {}, "metadata": {}}\n', encoding="utf-8")

    with pytest.raises(ManifestResourceMissingError) as exc:
        ManifestStore(root=GuardedPath(tmp_path)).load("2023.1")

    assert exc.value.path == tmp_path / "2023.1" / "functions.json"


def test_dispatcher_explicit_2023_1_missing_manifest_reports_fail_closed_error(tmp_path: Path) -> None:
    result = WwiseDispatcher(manifest_store=ManifestStore(root=GuardedPath(tmp_path))).dispatch(
        "ak.wwise.core.getInfo",
        version="2023.1",
    )

    assert result["ok"] is False
    assert result["version"] == "2023.1"
    assert result["error_code"] == "MANIFEST_NOT_FOUND"
    assert "2023.1" in result["message"]
    assert "2022.1" not in result["message"]


def test_semantic_source_note_checker_explicit_2023_1_uses_2023_1_resource_path_without_reference_fallback() -> None:
    checker = SemanticSourceNoteChecker(notebook_id="wwise-2023.1-docs")

    status = require_source_note(checker, BuilderFamily.QUERY, version="2023.1")

    assert status.allowed is True
    assert status.version == "2023.1"
    assert status.notebook_id == "wwise-2023.1-docs"
