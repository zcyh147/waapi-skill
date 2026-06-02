from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from wwise_waapi.manifest import (  # pyright: ignore[reportMissingImports]
    DeterministicJsonWriter,
    ManifestStore,
    audit_manifest,
)

RESOURCE_ROOT = Path("skills") / "waapi-skill" / "resources" / "manifest"
VERSION = "2023.1"
BUILD = "2023.1.19.8928"
FORBIDDEN_RUNTIME_METADATA_FIELDS = {"wwise_console_path", "wwise_console_path_status"}


class GuardedManifestPath(type(Path())):
    def exists(self, *args: Any, **kwargs: Any) -> bool:
        self._reject_2022_fallback()
        return super().exists(*args, **kwargs)

    def read_text(self, *args: Any, **kwargs: Any) -> str:
        self._reject_2022_fallback()
        return super().read_text(*args, **kwargs)

    def _reject_2022_fallback(self) -> None:
        if "resources/manifest/2022.1" in self.as_posix():
            raise AssertionError(f"2023.1 manifest lookup touched 2022.1 fallback: {self}")


def _load_split_file(filename: str) -> dict[str, Any]:
    return json.loads((RESOURCE_ROOT / VERSION / filename).read_text(encoding="utf-8"))


def test_2023_manifest_files_exist_and_metadata_stays_runtime_focused() -> None:
    payloads = {
        filename: _load_split_file(filename)
        for filename in ("manifest.json", "functions.json", "topics.json", "schemas.json")
    }

    for payload in payloads.values():
        metadata = payload["metadata"]
        assert metadata["version_key"] == VERSION
        assert metadata["wwise_version_target"] == VERSION
        assert metadata["wwise_build"] == BUILD
        assert FORBIDDEN_RUNTIME_METADATA_FIELDS.isdisjoint(metadata)
        assert metadata["provenance"]["sample_project"] == {"name": "SampleProject"}

    assert payloads["manifest.json"]["audit"]["counts_match"] is True
    assert payloads["functions.json"]["functions"]
    assert payloads["topics.json"]["topics"]
    assert payloads["schemas.json"]["schemas"]


def test_2023_manifest_store_loads_2023_only() -> None:
    guarded_root = GuardedManifestPath(RESOURCE_ROOT)
    loaded = ManifestStore(root=guarded_root).load(VERSION)
    audit = audit_manifest(loaded)

    assert loaded["metadata"]["version_key"] == VERSION
    assert loaded["metadata"]["wwise_build"] == BUILD
    assert audit.counts_match is True
    assert audit.manifest_function_count == loaded["audit"]["manifest_function_count"]
    assert audit.manifest_topic_count == loaded["audit"]["manifest_topic_count"]
    assert audit.schema_count == audit.manifest_function_count + audit.manifest_topic_count
    assert all(entry["type"] == "function" for entry in loaded["functions"])
    assert all(entry["type"] == "topic" for entry in loaded["topics"])


def test_2023_manifest_serialization_is_deterministic() -> None:
    writer = DeterministicJsonWriter()

    for filename in ("manifest.json", "functions.json", "topics.json", "schemas.json"):
        path = RESOURCE_ROOT / VERSION / filename
        payload = json.loads(path.read_text(encoding="utf-8"))

        assert path.read_text(encoding="utf-8") == writer.dumps(payload)
