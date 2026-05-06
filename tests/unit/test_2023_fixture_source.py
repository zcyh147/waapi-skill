from __future__ import annotations

import fnmatch
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

import tests.destructive.support.live_environment as live_env  # pyright: ignore[reportMissingImports]
from tests.destructive.support.live_environment import (  # pyright: ignore[reportMissingImports]
    LiveEnvironmentError,
    require_destructive_environment,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
ORG_FIXTURE_ROOT = REPO_ROOT / "tests" / "_org" / "2023.1"
METADATA_PATH = ORG_FIXTURE_ROOT / "fixture-metadata.json"
MANIFEST_PATH = ORG_FIXTURE_ROOT / "fixture-manifest.json"
INSTALLED_SOURCE_PROJECT = live_env.WWISE_2023_1_SAMPLE_PROJECT_PATH
SOURCE_BUILD = "2023.1.19.8928"


def test_2023_org_fixture_metadata_and_hash_manifest() -> None:
    metadata = _read_json(METADATA_PATH)
    manifest = _read_json(MANIFEST_PATH)
    readme = (ORG_FIXTURE_ROOT / "README.md").read_text(encoding="utf-8")
    actual_paths = _committed_fixture_payload_paths()

    assert metadata["fixture_root"] == "tests/_org/2023.1"
    assert metadata["immutability"]["role"] == "committed immutable source fixture"
    assert "Never pass this directory" in metadata["immutability"]["mutation_policy"]
    assert metadata["provenance"]["source_path"] == manifest["source"]["path"]
    assert SOURCE_BUILD in metadata["provenance"]["source_path"]
    assert metadata["provenance"]["source_path"].replace("\\", "/").endswith("/SampleProject/SampleProject.wproj")
    assert metadata["provenance"]["source_build"] == SOURCE_BUILD
    assert metadata["wwise"] == {
        "build": SOURCE_BUILD,
        "source_build": "8928",
        "source_version": "v2023.1.19",
        "version": "2023.1",
    }
    assert SOURCE_BUILD in manifest["source"]["path"]
    assert manifest["source"]["path"].replace("\\", "/").endswith("/SampleProject/SampleProject.wproj")
    assert manifest["source"]["build"] == SOURCE_BUILD
    assert manifest["source"]["path"] in readme
    assert SOURCE_BUILD in readme
    assert metadata["hash_strategy"]["file_count"] == manifest["file_count"]
    assert metadata["hash_strategy"]["manifest_digest"] == manifest["digest"]
    assert manifest["root"] == "tests/_org/2023.1"
    assert manifest["algorithm"] == "sha256"
    assert manifest["strategy"] == "path-plus-content excluding fixture metadata/manifest bookkeeping files"
    _assert_manifest_matches_committed_payload(manifest, actual_paths)


def test_2023_fixture_manifest_hashes_match_committed_files() -> None:
    manifest = _read_json(MANIFEST_PATH)
    actual_paths = _committed_fixture_payload_paths()

    assert manifest["root"] == "tests/_org/2023.1"
    assert manifest["algorithm"] == "sha256"
    assert manifest["strategy"] == "path-plus-content excluding fixture metadata/manifest bookkeeping files"
    _assert_manifest_matches_committed_payload(manifest, actual_paths)


def _committed_fixture_payload_paths() -> list[str]:
    return sorted(
        path.relative_to(ORG_FIXTURE_ROOT).as_posix()
        for path in ORG_FIXTURE_ROOT.rglob("*")
        if path.is_file() and path.name not in {"fixture-manifest.json", "fixture-metadata.json"}
    )


def _assert_manifest_matches_committed_payload(manifest: dict[str, Any], actual_paths: list[str]) -> None:
    manifest_files = {entry["path"]: entry for entry in manifest["files"]}
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


def test_2023_fixture_contains_only_authored_project_source_files() -> None:
    metadata = _read_json(METADATA_PATH)
    allowed_patterns = metadata["allowed_committed_file_patterns"]
    excluded_patterns = metadata["excluded_generated_file_patterns"]
    excluded_dirs = tuple(part.strip("/") for part in metadata["excluded_generated_folders"])
    paths = [path for path in ORG_FIXTURE_ROOT.rglob("*") if path.is_file()]

    assert (ORG_FIXTURE_ROOT / "SampleProject.wproj").exists()
    assert any(path.suffix == ".wwu" for path in paths)
    for path in paths:
        rel = path.relative_to(ORG_FIXTURE_ROOT).as_posix()
        assert any(fnmatch.fnmatch(rel, pattern) for pattern in allowed_patterns), rel
        assert not any(fnmatch.fnmatch(path.name, pattern) or fnmatch.fnmatch(rel, pattern) for pattern in excluded_patterns), rel
        assert not any(part in excluded_dirs for part in path.relative_to(ORG_FIXTURE_ROOT).parts), rel


def test_2023_destructive_target_rejects_installed_and_org_fixture_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    console = tmp_path / "WwiseConsole.sh"
    console.write_text("#!/bin/sh\n", encoding="utf-8")
    console.chmod(0o755)
    installed_project = tmp_path / "installed" / "SampleProject" / "SampleProject.wproj"
    installed_project.parent.mkdir(parents=True)
    installed_project.write_text("<WwiseDocument />\n", encoding="utf-8")
    monkeypatch.setattr(live_env, "INSTALLED_SAMPLE_PROJECT_2023_1_ROOT", installed_project.parent)
    monkeypatch.setattr(
        live_env,
        "LIVE_VERSION_PATHS",
        {
            **live_env.LIVE_VERSION_PATHS,
            "2023.1": live_env._LiveVersionPaths(
                version="2023.1",
                console_path=console,
                sample_project_path=installed_project,
                require_exact_paths=True,
            ),
        },
    )
    installed_root = installed_project.parent
    installed_env = {
        "WWISE_LIVE": "1",
        "WWISE_DESTRUCTIVE": "1",
        "WWISE_VERSION": "2023.1",
        "WWISE_CONSOLE": str(console),
        "WWISE_FIXTURE_PROJECT": str(installed_project),
        "WWISE_SANDBOX_ROOT": str(installed_root),
    }
    org_fixture_env = {
        "WWISE_LIVE": "1",
        "WWISE_DESTRUCTIVE": "1",
        "WWISE_VERSION": "2023.1",
        "WWISE_CONSOLE": str(console),
        "WWISE_FIXTURE_PROJECT": str(ORG_FIXTURE_ROOT / "SampleProject.wproj"),
        "WWISE_SANDBOX_ROOT": str(ORG_FIXTURE_ROOT),
    }

    with pytest.raises(LiveEnvironmentError, match="immutable installed SampleProject"):
        require_destructive_environment(installed_env)
    with pytest.raises(LiveEnvironmentError, match="tests/_org"):
        require_destructive_environment(org_fixture_env)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        pytest.fail(f"missing fixture metadata file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_fixture_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    if path.suffix.lower() in {".md", ".json", ".txt", ".wwu", ".wproj", ".xml"}:
        return data.replace(b"\r\n", b"\n")
    return data
