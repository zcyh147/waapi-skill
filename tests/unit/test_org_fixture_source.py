from __future__ import annotations

import fnmatch
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
ORG_FIXTURE_ROOT = REPO_ROOT / "tests" / "_org" / "2022.1"
METADATA_PATH = ORG_FIXTURE_ROOT / "fixture-metadata.json"
MANIFEST_PATH = ORG_FIXTURE_ROOT / "fixture-manifest.json"


def test_org_fixture_metadata_declares_immutable_source_contract() -> None:
    metadata = _read_json(METADATA_PATH)
    manifest = _read_json(MANIFEST_PATH)

    assert metadata["fixture_root"] == "tests/_org/2022.1"
    assert metadata["immutability"]["role"] == "committed immutable source fixture"
    assert "Never pass this directory" in metadata["immutability"]["mutation_policy"]
    assert metadata["wwise"] == {"source_build": "8584", "source_version": "v2022.1.19", "version": "2022.1"}
    assert metadata["provenance"]["type"] == "curated copy from local Audiokinetic SampleProject"
    assert "*.wav" in metadata["lfs_managed_asset_patterns"]
    assert "GeneratedSoundBanks/" in metadata["excluded_generated_folders"]
    assert "*.validationcache" in metadata["excluded_generated_file_patterns"]
    assert metadata["hash_strategy"]["algorithm"] == "sha256"
    assert metadata["hash_strategy"]["mode"] == (
        "path-plus-content over committed fixture payload files; excludes fixture-metadata.json "
        "and fixture-manifest.json bookkeeping files to avoid circular hashes"
    )
    assert metadata["hash_strategy"]["file_count"] == manifest["file_count"]
    assert metadata["hash_strategy"]["manifest_digest"] == manifest["digest"]
    assert metadata["fixture_update_procedure"]


def test_org_fixture_declares_required_authored_object_scenarios() -> None:
    metadata = _read_json(METADATA_PATH)
    scenarios = {entry["scenario"]: entry for entry in metadata["required_authored_objects"]}

    for required in {
        "object mutation roots",
        "property/reference targets",
        "SwitchContainer",
        "SwitchGroup/Switch",
        "SoundBank definition/process",
        "Event",
        "State",
        "RTPC",
        "listener/game-object",
        "profiler/soundengine",
    }:
        assert required in scenarios
        assert scenarios[required]["status"]
        sources = [source.strip() for source in scenarios[required]["source"].split(";")]
        for source in sources:
            if source.endswith(".wwu"):
                matches = list(ORG_FIXTURE_ROOT.glob(source)) if "*" in source else [ORG_FIXTURE_ROOT / source]
                assert any(path.exists() for path in matches)


def test_org_fixture_manifest_hashes_match_committed_files() -> None:
    manifest = _read_json(MANIFEST_PATH)
    manifest_files = {entry["path"]: entry for entry in manifest["files"]}
    actual_paths = sorted(
        path.relative_to(ORG_FIXTURE_ROOT).as_posix()
        for path in ORG_FIXTURE_ROOT.rglob("*")
        if path.is_file() and path.name not in {"fixture-manifest.json", "fixture-metadata.json"}
    )

    assert manifest["root"] == "tests/_org/2022.1"
    assert manifest["algorithm"] == "sha256"
    assert manifest["strategy"] == "path-plus-content excluding fixture metadata/manifest bookkeeping files"
    assert sorted(manifest_files) == actual_paths

    if os.name != "nt":
        digest = hashlib.sha256()
        for rel_path in actual_paths:
            data = _canonical_fixture_bytes(ORG_FIXTURE_ROOT / rel_path)
            assert manifest_files[rel_path]["bytes"] == len(data)
            assert manifest_files[rel_path]["sha256"] == hashlib.sha256(data).hexdigest()
            digest.update(rel_path.encode("utf-8"))
            digest.update(b"\0")
            digest.update(manifest_files[rel_path]["sha256"].encode("utf-8"))
            digest.update(b"\0")
        assert manifest["digest"] == digest.hexdigest()
    assert manifest["file_count"] == len(actual_paths)


def test_org_fixture_contains_only_allowed_source_patterns_and_no_generated_artifacts() -> None:
    metadata = _read_json(METADATA_PATH)
    allowed_patterns = metadata["allowed_committed_file_patterns"]
    excluded_patterns = metadata["excluded_generated_file_patterns"]
    excluded_dirs = tuple(part.strip("/") for part in metadata["excluded_generated_folders"])
    paths = [path for path in ORG_FIXTURE_ROOT.rglob("*") if path.is_file()]

    assert (ORG_FIXTURE_ROOT / "SampleProject.wproj").exists()
    assert any(path.suffix == ".wwu" for path in paths)
    assert any(path.suffix == ".wav" for path in paths)
    for path in paths:
        rel = path.relative_to(ORG_FIXTURE_ROOT).as_posix()
        assert any(fnmatch.fnmatch(rel, pattern) for pattern in allowed_patterns), rel
        assert not any(fnmatch.fnmatch(path.name, pattern) or fnmatch.fnmatch(rel, pattern) for pattern in excluded_patterns), rel
        assert not any(part in excluded_dirs for part in path.relative_to(ORG_FIXTURE_ROOT).parts), rel


def test_org_fixture_wav_assets_are_lfs_tracked_by_gitattributes() -> None:
    attributes = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    wav_files = list(ORG_FIXTURE_ROOT.rglob("*.wav"))

    assert wav_files
    assert "*.wav filter=lfs diff=lfs merge=lfs -text" in attributes


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        pytest.fail(f"missing fixture metadata file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_fixture_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    if path.suffix.lower() in {".md", ".json", ".txt", ".wwu", ".wproj", ".xml"}:
        return data.replace(b"\r\n", b"\n")
    return data
