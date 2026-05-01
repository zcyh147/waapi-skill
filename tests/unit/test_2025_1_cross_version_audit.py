from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.common import BuilderFamily, SemanticErrorCode  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.source_notes import SemanticSourceNoteChecker  # pyright: ignore[reportMissingImports]
from wwise_waapi.dispatcher import DEFAULT_WWISE_VERSION, WwiseDispatcher  # pyright: ignore[reportMissingImports]
from wwise_waapi.manifest import ManifestStore, audit_manifest  # pyright: ignore[reportMissingImports]


ROOT = Path(__file__).resolve().parents[2]
VERSION_2022 = "2022.1"
VERSION_2025 = "2025.1"
BUILD_2025 = "2025.1.7.9143"
NOTEBOOK_2025 = "wwise-2025.1-docs"
MANIFEST_ROOT = ROOT / "resources" / "manifest"
MANIFEST_2025 = MANIFEST_ROOT / VERSION_2025
ADDED_SINCE_2024 = MANIFEST_2025 / "added-since-2024.1.json"
GET_INFO_URI = "ak.wwise.core.getInfo"
EXPECTED_2025_AUDIT_COUNTS = (154, 31, 185, 0)
FORBIDDEN_2025_FALLBACK_FRAGMENTS = (
    "resources/manifest/2022.1",
    "resources/manifest/2023.1",
    "resources/manifest/2024.1",
    "resources/manifest/2025/",
    "resources/coverage/2022.1",
    "resources/coverage/2023.1",
    "resources/coverage/2024.1",
    "resources/coverage/2025/",
    "resources/deferred/2022.1",
    "resources/deferred/2023.1",
    "resources/deferred/2024.1",
    "resources/deferred/2025/",
    "resources/semantic/2022.1",
    "resources/semantic/2023.1",
    "resources/semantic/2024.1",
    "resources/semantic/2025/",
    "references/semantic/2022.1",
    "references/semantic/2023.1",
    "references/semantic/2024.1",
    "references/semantic/2025/",
    "references/semantic-builder-",
)


def _reject_forbidden_2025_fallback(path: Path) -> None:
    path_text = path.as_posix()
    for fragment in FORBIDDEN_2025_FALLBACK_FRAGMENTS:
        if fragment in path_text:
            raise AssertionError(f"Explicit 2025.1 audit touched forbidden fallback resource: {path_text}")


def test_default_dispatcher_remains_2022_1_and_explicit_2025_1_dispatch_succeeds() -> None:
    store = ManifestStore(root=MANIFEST_ROOT)
    manifest_2025 = store.load(VERSION_2025)
    audit = audit_manifest(manifest_2025)

    assert DEFAULT_WWISE_VERSION == VERSION_2022
    assert manifest_2025["metadata"]["version_key"] == VERSION_2025
    assert manifest_2025["metadata"]["wwise_version_target"] == VERSION_2025
    assert manifest_2025["metadata"]["wwise_build"] == BUILD_2025
    assert (
        audit.manifest_function_count,
        audit.manifest_topic_count,
        audit.schema_count,
        audit.schema_failure_count,
    ) == EXPECTED_2025_AUDIT_COUNTS

    dispatcher = WwiseDispatcher(manifest_store=store)
    default_result = dispatcher.dispatch(GET_INFO_URI, dry_run=True)
    explicit_2025_result = dispatcher.dispatch(GET_INFO_URI, version=VERSION_2025, dry_run=True)

    assert default_result["ok"] is True
    assert default_result["version"] == VERSION_2022
    assert explicit_2025_result["ok"] is True
    assert explicit_2025_result["version"] == VERSION_2025
    assert explicit_2025_result["result"]["dry_run"] is True


def test_explicit_2025_1_resource_lookups_never_read_prior_bare_or_global_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_exists: Callable[..., bool] = Path.exists
    original_read_text: Callable[..., str] = Path.read_text
    touched: list[str] = []

    def guarded_exists(path: Path, *args: Any, **kwargs: Any) -> bool:
        path_text = path.as_posix()
        touched.append(path_text)
        _reject_forbidden_2025_fallback(path)
        return original_exists(path, *args, **kwargs)

    def guarded_read_text(path: Path, *args: Any, **kwargs: Any) -> str:
        path_text = path.as_posix()
        touched.append(path_text)
        _reject_forbidden_2025_fallback(path)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", guarded_exists)
    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    store = ManifestStore(root=MANIFEST_ROOT)
    manifest = store.load(VERSION_2025)
    dispatch_result = WwiseDispatcher(manifest_store=store).dispatch(GET_INFO_URI, version=VERSION_2025, dry_run=True)
    added_inventory = _read_json(ADDED_SINCE_2024)
    source_note_status = SemanticSourceNoteChecker(notebook_id=NOTEBOOK_2025).check(
        BuilderFamily.QUERY.value,
        version=VERSION_2025,
    )

    assert manifest["metadata"]["version_key"] == VERSION_2025
    assert dispatch_result["ok"] is True
    assert dispatch_result["version"] == VERSION_2025
    assert added_inventory["metadata"]["target_version"] == VERSION_2025
    assert source_note_status.allowed is False
    assert source_note_status.version == VERSION_2025
    assert source_note_status.error_code == SemanticErrorCode.MISSING_SOURCE_NOTE
    assert "resources/semantic/2025.1/source_notes.json" in source_note_status.reason
    assert any("resources/manifest/2025.1/manifest.json" in path for path in touched)
    assert any("resources/manifest/2025.1/functions.json" in path for path in touched)
    assert any("resources/manifest/2025.1/topics.json" in path for path in touched)
    assert any("resources/manifest/2025.1/schemas.json" in path for path in touched)
    assert any("resources/manifest/2025.1/added-since-2024.1.json" in path for path in touched)
    assert any("resources/semantic/2025.1/source_notes.json" in path for path in touched)
    assert not any(
        any(fragment in path for fragment in FORBIDDEN_2025_FALLBACK_FRAGMENTS)
        for path in touched
    )


def test_bare_2025_manifest_placeholder_has_no_payload_files() -> None:
    bare_2025 = MANIFEST_ROOT / "2025"
    payloads = []
    if bare_2025.exists():
        payloads = [path for path in bare_2025.iterdir() if path.name != ".gitkeep"]

    assert payloads == []


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
