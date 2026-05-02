from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.manifest import (  # pyright: ignore[reportMissingImports]
    DeterministicJsonWriter,
    ManifestResourceMissingError,
    ManifestStore,
    audit_manifest,
)


RESOURCE_ROOT = Path("resources") / "manifest"
VERSION = "2021.1"
MANIFEST_PATH = RESOURCE_ROOT / VERSION / "manifest.json"
FORBIDDEN_FRAGMENTS = (
    "resources/manifest/2022.1",
    "resources/manifest/2023.1",
    "resources/manifest/2024.1",
    "resources/manifest/2025.1",
)


class GuardedManifestPath(type(Path())):
    def exists(self, *args: Any, **kwargs: Any) -> bool:
        self._reject_cross_version_fallback()
        return super().exists(*args, **kwargs)

    def read_text(self, *args: Any, **kwargs: Any) -> str:
        self._reject_cross_version_fallback()
        return super().read_text(*args, **kwargs)

    def _reject_cross_version_fallback(self) -> None:
        path = self.as_posix()
        for fragment in FORBIDDEN_FRAGMENTS:
            if fragment in path:
                raise AssertionError(f"2021.1 manifest lookup touched fallback path: {self}")


def _load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_2021_1_manifest_placeholder_is_explicitly_pending() -> None:
    payload = _load_manifest()

    assert payload["metadata"]["version_key"] == VERSION
    assert payload["metadata"]["wwise_version_target"] == VERSION
    assert payload["metadata"]["inventory_source"] == "source_pending"
    assert payload["metadata"]["source_status"] == "source_pending"
    assert payload["metadata"]["support_status"] == "non-support"
    assert payload["metadata"]["schema_source_uri"] == "source_pending"
    assert payload["metadata"]["source_uris"] == []
    assert payload["metadata"]["schema_source_uris"] == []
    assert payload["audit"]["counts_match"] is True
    assert payload["audit"]["manifest_function_count"] == 0
    assert payload["audit"]["manifest_topic_count"] == 0
    assert payload["audit"]["schema_count"] == 0


def test_2021_1_manifest_store_fails_closed_when_2021_1_resource_files_are_missing(tmp_path: Path) -> None:
    manifest_root = tmp_path / "resources" / "manifest"
    (manifest_root / VERSION).mkdir(parents=True)
    (manifest_root / VERSION / "manifest.json").write_text(MANIFEST_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    store = ManifestStore(root=manifest_root)

    with pytest.raises(ManifestResourceMissingError) as exc_info:
        store.load(VERSION)

    assert exc_info.value.version == VERSION
    assert exc_info.value.path == manifest_root / VERSION / "functions.json"


def test_2021_1_manifest_store_does_not_fall_back_to_newer_versions(tmp_path: Path) -> None:
    guarded_root = GuardedManifestPath(tmp_path / "resources" / "manifest")
    (guarded_root / VERSION).mkdir(parents=True)
    (guarded_root / VERSION / "manifest.json").write_text(MANIFEST_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    store = ManifestStore(root=guarded_root)

    with pytest.raises(ManifestResourceMissingError):
        store.load(VERSION)


def test_2021_1_manifest_serialization_is_deterministic() -> None:
    writer = DeterministicJsonWriter()
    payload = _load_manifest()

    assert MANIFEST_PATH.read_text(encoding="utf-8") == writer.dumps(payload)


def test_2021_1_manifest_source_code_contains_no_cross_version_loader_paths() -> None:
    source = Path("wwise_waapi") / "manifest.py"
    text = source.read_text(encoding="utf-8")

    for fragment in FORBIDDEN_FRAGMENTS:
        assert fragment not in text


def test_2021_1_loaded_manifest_audit_stays_fail_closed_when_recomputed() -> None:
    manifest = _load_manifest()
    audit = audit_manifest(manifest)

    assert audit.counts_match is True
    assert audit.manifest_function_count == 0
    assert audit.manifest_topic_count == 0
    assert audit.schema_count == 0
    assert audit.schema_failure_count == 0
