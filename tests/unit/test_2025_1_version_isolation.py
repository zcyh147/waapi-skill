from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.common import BuilderFamily  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.source_notes import SemanticSourceNoteChecker  # pyright: ignore[reportMissingImports]
from wwise_waapi.dispatcher import WwiseDispatcher  # pyright: ignore[reportMissingImports]
from wwise_waapi.manifest import ManifestResourceMissingError, ManifestStore  # pyright: ignore[reportMissingImports]


VERSION_2025 = "2025.1"
NOTEBOOK_2025 = "wwise-2025.1-docs"
FORBIDDEN_2025_FALLBACK_TOKENS = (
    "2022.1",
    "2023.1",
    "2024.1",
    "resources/manifest/2025/",
    "resources/semantic/2025/",
    "references/semantic-builder-",
)


class GuardedPath(type(Path())):
    def _check(self) -> None:
        path_text = self.as_posix()
        if any(token in path_text for token in FORBIDDEN_2025_FALLBACK_TOKENS):
            raise AssertionError(f"2025.1 lookup touched forbidden fallback path: {path_text}")

    def exists(self, *args: Any, **kwargs: Any) -> bool:
        self._check()
        return super().exists(*args, **kwargs)

    def read_text(self, *args: Any, **kwargs: Any) -> str:
        self._check()
        return super().read_text(*args, **kwargs)


def test_2025_1_resource_lookup_does_not_fallback_to_older_or_bare_versions(tmp_path: Path) -> None:
    root = GuardedPath(tmp_path)
    store = ManifestStore(root=root)
    store.record("2022.1", {"functions": [{"uri": "ak.wwise.core.getInfo"}]})
    store.record("2023.1", {"functions": [{"uri": "ak.wwise.core.getInfo"}]})
    store.record("2024.1", {"functions": [{"uri": "ak.wwise.core.getInfo"}]})
    store.record("2025", {"functions": [{"uri": "ak.bare.should.not.fallback"}]})
    store.record(VERSION_2025, {"functions": [{"uri": "ak.should.not.fallback"}]})

    with pytest.raises(ManifestResourceMissingError) as manifest_exc:
        store.load(VERSION_2025)

    assert manifest_exc.value.version == VERSION_2025
    assert manifest_exc.value.path == tmp_path / VERSION_2025 / "manifest.json"


def test_manifest_store_explicit_2025_1_missing_manifest_fails_closed_without_older_or_bare_fallback(
    tmp_path: Path,
) -> None:
    root = GuardedPath(tmp_path)
    store = ManifestStore(root=root)
    store.record("2022.1", {"functions": [{"uri": "ak.wwise.core.getInfo"}]})
    store.record("2023.1", {"functions": [{"uri": "ak.wwise.core.getInfo"}]})
    store.record("2024.1", {"functions": [{"uri": "ak.wwise.core.getInfo"}]})
    store.record("2025", {"functions": [{"uri": "ak.bare.should.not.fallback"}]})
    store.record(VERSION_2025, {"functions": [{"uri": "ak.should.not.fallback"}]})

    with pytest.raises(ManifestResourceMissingError) as exc:
        store.load(VERSION_2025)

    assert exc.value.version == VERSION_2025
    assert exc.value.path == tmp_path / VERSION_2025 / "manifest.json"


def test_manifest_store_explicit_2025_1_missing_split_files_fails_closed(tmp_path: Path) -> None:
    version_dir = tmp_path / VERSION_2025
    version_dir.mkdir(parents=True)
    (version_dir / "manifest.json").write_text('{"audit": {}, "metadata": {}}\n', encoding="utf-8")

    with pytest.raises(ManifestResourceMissingError) as exc:
        ManifestStore(root=GuardedPath(tmp_path)).load(VERSION_2025)

    assert exc.value.version == VERSION_2025
    assert exc.value.path == tmp_path / VERSION_2025 / "functions.json"


def test_dispatcher_explicit_2025_1_missing_manifest_reports_fail_closed_error(tmp_path: Path) -> None:
    result = WwiseDispatcher(manifest_store=ManifestStore(root=GuardedPath(tmp_path))).dispatch(
        "ak.wwise.core.getInfo",
        version=VERSION_2025,
    )

    assert result["ok"] is False
    assert result["version"] == VERSION_2025
    assert result["error_code"] == "MANIFEST_NOT_FOUND"
    assert VERSION_2025 in result["message"]
    assert "2022.1" not in result["message"]
    assert "2023.1" not in result["message"]
    assert "2024.1" not in result["message"]
    assert "resources/manifest/2025/" not in result["message"]


def test_semantic_source_note_checker_explicit_2025_1_uses_2025_1_resource_path_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_exists: Callable[..., bool] = Path.exists
    original_read_text: Callable[..., str] = Path.read_text
    touched: list[str] = []

    def guarded_exists(path: Path, *args: Any, **kwargs: Any) -> bool:
        path_text = path.as_posix()
        touched.append(path_text)
        _reject_forbidden_fallback(path_text)
        return original_exists(path, *args, **kwargs)

    def guarded_read_text(path: Path, *args: Any, **kwargs: Any) -> str:
        path_text = path.as_posix()
        touched.append(path_text)
        _reject_forbidden_fallback(path_text)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", guarded_exists)
    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    status = SemanticSourceNoteChecker(notebook_id=NOTEBOOK_2025).check(
        BuilderFamily.QUERY.value,
        version=VERSION_2025,
    )

    assert status.allowed is True
    assert status.version == VERSION_2025
    assert status.error_code is None
    assert status.reason == "Semantic source note is grounded."
    assert any("resources/semantic/2025.1/source_notes.json" in path for path in touched)
    assert not any(any(token in path for token in FORBIDDEN_2025_FALLBACK_TOKENS) for path in touched)


def _reject_forbidden_fallback(path_text: str) -> None:
    if any(token in path_text for token in FORBIDDEN_2025_FALLBACK_TOKENS):
        raise AssertionError(f"2025.1 lookup touched forbidden fallback path: {path_text}")
