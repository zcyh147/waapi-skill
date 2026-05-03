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
VERSION = "2025.1"
BUILD = "2025.1.7.9143"
CONSOLE_PATH = "/Applications/Audiokinetic/Wwise2025.1.7.9143/Wwise.app/Contents/Tools/WwiseConsole.sh"
SAMPLE_PROJECT_PATH = (
    "/Applications/Audiokinetic/SampleProject2025.1.7.9143/SampleProject/SampleProject.wproj"
)
SOURCE_URIS = [
    "ak.wwise.waapi.getFunctions",
    "ak.wwise.waapi.getTopics",
    "ak.wwise.waapi.getSchema",
]
ADDED_FUNCTIONS = {
    "ak.wwise.core.mediaPool.get",
    "ak.wwise.core.mediaPool.getFields",
    "ak.wwise.core.profiler.moveCursor",
    "ak.wwise.core.profiler.setCursorTime",
    "ak.wwise.core.workUnit.load",
    "ak.wwise.core.workUnit.unload",
}
ADDED_TOPICS = {"ak.wwise.core.object.structureChanged"}


class GuardedManifestPath(type(Path())):
    def exists(self, *args: Any, **kwargs: Any) -> bool:
        self._reject_cross_version_fallback()
        return super().exists(*args, **kwargs)

    def read_text(self, *args: Any, **kwargs: Any) -> str:
        self._reject_cross_version_fallback()
        return super().read_text(*args, **kwargs)

    def _reject_cross_version_fallback(self) -> None:
        path = self.as_posix()
        forbidden_fragments = (
            "resources/manifest/2025/",
            "resources/manifest/2024.1",
            "resources/manifest/2023.1",
            "resources/manifest/2022.1",
        )
        for fragment in forbidden_fragments:
            if fragment in path:
                raise AssertionError(f"2025.1 manifest lookup touched fallback path: {self}")


def _load_split_file(filename: str) -> dict[str, Any]:
    return json.loads((RESOURCE_ROOT / VERSION / filename).read_text(encoding="utf-8"))


def test_2025_1_manifest_files_exist_and_metadata_records_live_provenance() -> None:
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
        assert metadata["inventory_source"] == "live-reflection-2025.1-sandbox-manifest"
        assert metadata["source_uris"] == SOURCE_URIS
        assert metadata["schema_source_uri"] == "ak.wwise.waapi.getSchema"
        assert metadata["schema_source_uris"] == ["ak.wwise.waapi.getSchema"]
        assert metadata["provenance"]["sample_project"] == {
            "name": "SampleProject",
            "path": SAMPLE_PROJECT_PATH,
        }

    audit = payloads["manifest.json"]["audit"]
    assert audit["counts_match"] is True
    assert audit["manifest_function_count"] == 154
    assert audit["reflected_function_count"] == 154
    assert audit["manifest_topic_count"] == 31
    assert audit["reflected_topic_count"] == 31
    assert audit["schema_count"] == 185
    assert audit["schema_failure_count"] == 0
    assert (audit["manifest_function_count"], audit["manifest_topic_count"], audit["schema_count"]) != (
        148,
        30,
        178,
    )
    assert payloads["functions.json"]["functions"]
    assert payloads["topics.json"]["topics"]
    assert payloads["schemas.json"]["schemas"]


def test_2025_1_manifest_store_loads_2025_1_only_without_generic_or_old_fallbacks() -> None:
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


def test_2025_1_manifest_reflection_payloads_do_not_expose_local_paths() -> None:
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


def test_2025_1_manifest_serialization_is_deterministic() -> None:
    writer = DeterministicJsonWriter()

    for filename in (
        "manifest.json",
        "functions.json",
        "topics.json",
        "schemas.json",
        "added-since-2024.1.json",
    ):
        path = RESOURCE_ROOT / VERSION / filename
        payload = json.loads(path.read_text(encoding="utf-8"))

        assert path.read_text(encoding="utf-8") == writer.dumps(payload)


def test_2025_1_added_since_2024_1_inventory_records_explicit_differences() -> None:
    payload = _load_split_file("added-since-2024.1.json")

    assert payload["metadata"]["baseline_version"] == "2024.1"
    assert payload["metadata"]["target_version"] == VERSION
    assert payload["metadata"]["target_wwise_build"] == BUILD
    assert payload["metadata"]["target_inventory_source"] == "live-reflection-2025.1-sandbox-manifest"
    assert payload["metadata"]["comparison_basis"] == "live-reflection-split-resources"
    assert payload["summary"]["target_audit"]["manifest_function_count"] == 154
    assert payload["summary"]["target_audit"]["manifest_topic_count"] == 31
    assert payload["summary"]["target_audit"]["schema_count"] == 185
    assert payload["summary"]["baseline_audit"]["manifest_function_count"] == 148

    added_functions = {entry["uri"] for entry in payload["functions"]["added"]}
    added_topics = {entry["uri"] for entry in payload["topics"]["added"]}
    assert added_functions == ADDED_FUNCTIONS
    assert added_topics == ADDED_TOPICS
    assert payload["functions"]["removed"] == []
    assert payload["topics"]["removed"] == []
    assert payload["functions"]["changed"]
    assert payload["topics"]["changed"]
    assert all(entry["schema_changed"] or entry["reflection_changed"] for entry in payload["functions"]["changed"])
    assert all(entry["schema_changed"] or entry["reflection_changed"] for entry in payload["topics"]["changed"])
