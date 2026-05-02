from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from wwise_waapi.manifest import (  # pyright: ignore[reportMissingImports]
    DeterministicJsonWriter,
    ManifestStore,
    audit_manifest,
)


RESOURCE_ROOT = Path("resources") / "manifest"
VERSION = "2021.1"
BUILD = "2021.1.14.8108"
CONSOLE_PATH = "/Applications/Audiokinetic/Wwise2021.1.14.8108/Wwise.app/Contents/Tools/WwiseConsole.sh"
SAMPLE_PROJECT_PATH = (
    "/Applications/Audiokinetic/SampleProject2021.1.14.8108/SampleProject/SampleProject.wproj"
)
SOURCE_URIS = [
    "ak.wwise.waapi.getFunctions",
    "ak.wwise.waapi.getTopics",
    "ak.wwise.waapi.getSchema",
]
FORBIDDEN_FRAGMENTS = (
    "resources/manifest/2021/",
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


def _load_split_file(filename: str) -> dict[str, Any]:
    return json.loads((RESOURCE_ROOT / VERSION / filename).read_text(encoding="utf-8"))


def test_2021_1_manifest_files_exist_and_metadata_records_live_provenance() -> None:
    payloads = {
        filename: _load_split_file(filename)
        for filename in ("manifest.json", "functions.json", "topics.json", "schemas.json")
    }

    for payload in payloads.values():
        metadata = payload["metadata"]
        assert metadata["version_key"] == VERSION
        assert metadata["wwise_version_target"] == VERSION
        assert metadata["wwise_build"] == BUILD
        assert metadata["wwise_console_path"] == CONSOLE_PATH
        assert metadata["inventory_source"] == "live-reflection-2021.1-sandbox-manifest"
        assert metadata["source_uris"] == SOURCE_URIS
        assert metadata["schema_source_uri"] == "ak.wwise.waapi.getSchema"
        assert metadata["schema_source_uris"] == ["ak.wwise.waapi.getSchema"]
        assert metadata["provenance"]["sample_project"] == {
            "name": "SampleProject",
            "path": SAMPLE_PROJECT_PATH,
        }
        get_info = metadata["provenance"]["get_info"]
        assert get_info["branch"] == "wwise_v2021.1"
        assert get_info["isCommandLine"] is True
        assert get_info["version"] == {
            "build": 8108,
            "displayName": "v2021.1.14",
            "major": 1,
            "minor": 14,
            "schema": 103,
            "year": 2021,
        }

    audit = payloads["manifest.json"]["audit"]
    assert audit["counts_match"] is True
    assert audit["manifest_function_count"] == 99
    assert audit["reflected_function_count"] == 99
    assert audit["manifest_topic_count"] == 27
    assert audit["reflected_topic_count"] == 27
    assert audit["schema_count"] == 126
    assert audit["schema_failure_count"] == 0
    assert (audit["manifest_function_count"], audit["manifest_topic_count"], audit["schema_count"]) != (
        112,
        32,
        144,
    )
    assert payloads["functions.json"]["functions"]
    assert payloads["topics.json"]["topics"]
    assert payloads["schemas.json"]["schemas"]


def test_2021_1_manifest_store_loads_2021_1_only_without_newer_fallbacks() -> None:
    guarded_root = GuardedManifestPath(RESOURCE_ROOT)
    loaded = ManifestStore(root=guarded_root).load(VERSION)
    audit = audit_manifest(loaded)

    assert loaded["metadata"]["version_key"] == VERSION
    assert loaded["metadata"]["wwise_build"] == BUILD
    assert audit.counts_match is True
    assert audit.manifest_function_count == loaded["audit"]["manifest_function_count"]
    assert audit.manifest_topic_count == loaded["audit"]["manifest_topic_count"]
    assert audit.schema_count == audit.manifest_function_count + audit.manifest_topic_count
    assert audit.schema_failure_count == loaded["audit"]["schema_failure_count"]
    assert all(entry["type"] == "function" for entry in loaded["functions"])
    assert all(entry["type"] == "topic" for entry in loaded["topics"])


def test_2021_1_manifest_reflection_payloads_do_not_expose_local_paths() -> None:
    reflected_payload = {
        "functions": _load_split_file("functions.json")["functions"],
        "topics": _load_split_file("topics.json")["topics"],
        "schemas": _load_split_file("schemas.json")["schemas"],
    }
    serialized = json.dumps(reflected_payload, sort_keys=True)

    assert "/Applications/Audiokinetic" not in serialized
    assert "/Users/" not in serialized
    assert "/Volumes/" not in serialized
    assert "/private/" not in serialized
    assert "C:\\\\Users" not in serialized
    assert "Z:\\\\Applications" not in serialized
    assert "Y:\\\\" not in serialized
    assert ".sisyphus/runtime" not in serialized
    assert SAMPLE_PROJECT_PATH not in serialized


def test_2021_1_manifest_serialization_is_deterministic() -> None:
    writer = DeterministicJsonWriter()

    for filename in ("manifest.json", "functions.json", "topics.json", "schemas.json"):
        path = RESOURCE_ROOT / VERSION / filename
        payload = json.loads(path.read_text(encoding="utf-8"))

        assert path.read_text(encoding="utf-8") == writer.dumps(payload)


def test_2021_1_manifest_source_code_contains_no_cross_version_loader_paths() -> None:
    source = Path("wwise_waapi") / "manifest.py"
    text = source.read_text(encoding="utf-8")

    for fragment in FORBIDDEN_FRAGMENTS:
        assert fragment not in text


def test_2021_1_loaded_manifest_audit_stays_fail_closed_when_recomputed() -> None:
    manifest = ManifestStore(root=RESOURCE_ROOT).load(VERSION)
    audit = audit_manifest(manifest)

    assert audit.counts_match is True
    assert audit.manifest_function_count == 99
    assert audit.manifest_topic_count == 27
    assert audit.schema_count == 126
    assert audit.schema_failure_count == 0
