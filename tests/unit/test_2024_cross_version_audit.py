from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest  # pyright: ignore[reportMissingImports]
import json

from wwise_waapi.dispatcher import DEFAULT_WWISE_VERSION, WwiseDispatcher  # pyright: ignore[reportMissingImports]
from wwise_waapi.manifest import ManifestStore, audit_manifest  # pyright: ignore[reportMissingImports]


ROOT = Path(__file__).resolve().parents[2]
VERSION_2022 = "2022.1"
VERSION_2024 = "2024.1"
NOTEBOOK_2024 = "wwise-2024.1-docs"
MANIFEST_ROOT = Path("resources") / "manifest"
SEMANTIC_2024 = ROOT / "resources" / "semantic" / VERSION_2024 / "source_notes.json"
REFERENCES_2024 = ROOT / "references" / "semantic" / VERSION_2024
FIXTURE_2024 = ROOT / "tests" / "_org" / VERSION_2024
GET_INFO_URI = "ak.wwise.core.getInfo"
EXPECTED_2024_AUDIT_COUNTS = (148, 30, 178, 0)
FORBIDDEN_2024_FALLBACK_FRAGMENTS = (
    "resources/manifest/2022.1",
    "resources/manifest/2023.1",
    "resources/manifest/2024/",
    "resources/manifest/2025",
    "resources/coverage/2025",
    "resources/semantic/2022.1",
    "resources/semantic/2023.1",
    "resources/semantic/2024/",
    "resources/semantic/2025",
    "references/semantic/2022.1",
    "references/semantic/2023.1",
    "references/semantic/2024/",
    "references/semantic/2025",
    "references/semantic-builder-",
)
NO_2025_RESOURCE_ROOTS = (
    ROOT / "resources" / "manifest",
    ROOT / "resources" / "coverage",
    ROOT / "resources" / "semantic",
    ROOT / "references" / "semantic",
)


def _reject_forbidden_2024_fallback(path: Path) -> None:
    path_text = path.as_posix()
    for fragment in FORBIDDEN_2024_FALLBACK_FRAGMENTS:
        if fragment in path_text:
            raise AssertionError(f"Explicit 2024.1 audit touched forbidden fallback resource: {path_text}")


def test_default_dispatcher_remains_2022_1_and_explicit_2024_1_dispatch_succeeds() -> None:
    store = ManifestStore(root=MANIFEST_ROOT)
    manifest_2024 = store.load(VERSION_2024)
    audit = audit_manifest(manifest_2024)

    assert DEFAULT_WWISE_VERSION == VERSION_2022
    assert manifest_2024["metadata"]["version_key"] == VERSION_2024
    assert manifest_2024["metadata"]["wwise_version_target"] == VERSION_2024
    assert manifest_2024["metadata"]["wwise_build"] == "2024.1.13.9056"
    assert (
        audit.manifest_function_count,
        audit.manifest_topic_count,
        audit.schema_count,
        audit.schema_failure_count,
    ) == EXPECTED_2024_AUDIT_COUNTS
    assert (FIXTURE_2024 / "SampleProject.wproj").is_file()

    dispatcher = WwiseDispatcher(manifest_store=store)
    default_result = dispatcher.dispatch(GET_INFO_URI, dry_run=True)
    explicit_2024_result = dispatcher.dispatch(GET_INFO_URI, version=VERSION_2024, dry_run=True)

    assert default_result["ok"] is True
    assert default_result["version"] == VERSION_2022
    assert explicit_2024_result["ok"] is True
    assert explicit_2024_result["version"] == VERSION_2024


def test_explicit_2024_1_resource_lookups_never_read_prior_generic_global_or_2025_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_read_text: Callable[..., str] = Path.read_text
    touched: list[str] = []

    def guarded_read_text(path: Path, *args: Any, **kwargs: Any) -> str:
        path_text = path.as_posix()
        touched.append(path_text)
        _reject_forbidden_2024_fallback(path)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    store = ManifestStore(root=MANIFEST_ROOT)
    manifest = store.load(VERSION_2024)
    dispatch_result = WwiseDispatcher(manifest_store=store).dispatch(GET_INFO_URI, version=VERSION_2024, dry_run=True)

    assert manifest["metadata"]["version_key"] == VERSION_2024
    assert dispatch_result["ok"] is True
    assert dispatch_result["version"] == VERSION_2024
    assert any("resources/manifest/2024.1/manifest.json" in path for path in touched)
    assert any("resources/manifest/2024.1/functions.json" in path for path in touched)
    assert any("resources/manifest/2024.1/topics.json" in path for path in touched)
    assert any("resources/manifest/2024.1/schemas.json" in path for path in touched)
    assert not any(
        any(fragment in path for fragment in FORBIDDEN_2024_FALLBACK_FRAGMENTS)
        for path in touched
    )


def test_no_2025_resource_payloads_were_introduced() -> None:
    discovered_2025_paths: list[Path] = []

    for root in NO_2025_RESOURCE_ROOTS:
        if not root.exists():
            continue
        for child in root.iterdir():
            if not child.name.startswith("2025"):
                continue
            candidates = [child] if child.is_file() else list(child.iterdir())
            discovered_2025_paths.extend(candidate for candidate in candidates if candidate.name != ".gitkeep")

    assert discovered_2025_paths == []

def test_2024_semantic_source_notes_use_2024_notebook_and_versioned_references() -> None:
    payload = json.loads(SEMANTIC_2024.read_text(encoding="utf-8"))

    assert payload["version"] == VERSION_2024
    assert payload["notebook_id"] == NOTEBOOK_2024
    assert payload["protocol"] == "references/semantic/2024.1/semantic-builder-protocol.md"

    for family, note in payload["notes"].items():
        assert note["status"] == "grounded"
        assert note["notebook_id"] == NOTEBOOK_2024
        assert note["version_target"] == VERSION_2024
        assert note["gate_evidence_path"] == "references/semantic/2024.1/semantic-builder-notebooklm-gate.md"
        assert set(note["required_fields"]) <= set(note["cited_required_fields"])
        for evidence_path in [note["gate_evidence_path"], *note["source_urls"]]:
            assert evidence_path.startswith("references/semantic/2024.1/"), evidence_path
            assert "references/semantic-builder-" not in evidence_path
            assert "2022.1" not in evidence_path
            assert "2023.1" not in evidence_path
        encoded_note = json.dumps(note, sort_keys=True)
        assert NOTEBOOK_2024 in encoded_note
        assert "wwise-2022.1-docs" not in encoded_note
        assert "wwise-2023.1-docs" not in encoded_note
        assert "resources/semantic/2024/" not in encoded_note

    for reference in REFERENCES_2024.glob("*.md"):
        text = reference.read_text(encoding="utf-8")
        assert "references/semantic-builder-" not in text
        assert "wwise-2022.1-docs" not in text
        assert "wwise-2023.1-docs" not in text
        assert "references/semantic/2022.1" not in text
        assert "references/semantic/2023.1" not in text


def test_2024_semantic_runtime_checks_read_local_files_only(monkeypatch: pytest.MonkeyPatch) -> None:
    original_read_text: Callable[..., str] = Path.read_text
    touched: list[str] = []

    def guarded_read_text(path: Path, *args: Any, **kwargs: Any) -> str:
        path_text = path.as_posix()
        touched.append(path_text)
        _reject_forbidden_2024_fallback(path)
        assert "scripts/run.py" not in path_text
        assert ".agents/skills/notebooklm" not in path_text
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    payload = json.loads(SEMANTIC_2024.read_text(encoding="utf-8"))
    gate_text = (REFERENCES_2024 / "semantic-builder-notebooklm-gate.md").read_text(encoding="utf-8")

    assert payload["notebook_id"] == NOTEBOOK_2024
    assert "Runtime builders must read versioned local source-note resources" in gate_text
    assert any("resources/semantic/2024.1/source_notes.json" in path for path in touched)
    assert any("references/semantic/2024.1/semantic-builder-notebooklm-gate.md" in path for path in touched)
    assert not any(any(fragment in path for fragment in FORBIDDEN_2024_FALLBACK_FRAGMENTS) for path in touched)

