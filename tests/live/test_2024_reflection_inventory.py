from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.headless import default_waapi_client_factory  # pyright: ignore[reportMissingImports]
from wwise_waapi.manifest import ManifestStore, audit_manifest, build_manifest_from_caller  # pyright: ignore[reportMissingImports]
from tests.destructive.support.sandbox_fixture import (  # pyright: ignore[reportMissingImports]
    LiveSandboxLock,
    cleanup_sandbox,
    hash_project,
    launch_sandboxed_wwise,
    prepare_sample_project_sandbox,
    shutdown_sandboxed_wwise,
)

from tests.live.test_2024_live_prerequisites import (  # pyright: ignore[reportMissingImports]
    EXPECTED_SAMPLE_PROJECT,
    EXPECTED_WWISE_VERSION,
    require_2024_live_environment,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SANDBOX_ROOT = REPO_ROOT / ".waapi-skill-state" / "runtime" / "wwise-2024-live-smoke-sandboxes"
WWISE_BUILD = "2024.1.13.9056"


@pytest.mark.parametrize("display_name", ["2024.1", "2024.1.13", "v2024.1.13"])
def test_2024_version_display_name_accepts_expected_2024_1_shapes(display_name: str) -> None:
    _assert_2024_version_display_name(display_name)


@pytest.mark.parametrize("display_name", ["2022.1.14", "v2023.1.19", "2024.2.0", "v2025.1.0"])
def test_2024_version_display_name_rejects_wrong_major_minor(display_name: str) -> None:
    with pytest.raises(AssertionError):
        _assert_2024_version_display_name(display_name)


@pytest.mark.live
def test_2024_live_reflection_inventory_runs_against_sandbox(tmp_path: Path) -> None:
    contract = require_2024_live_environment()
    assert contract.sample_project_source == EXPECTED_SAMPLE_PROJECT

    env = dict(os.environ)
    sandbox = None
    lifecycle = None
    client = None
    failed = True

    with LiveSandboxLock(SANDBOX_ROOT):
        sandbox = prepare_sample_project_sandbox(env, sandbox_root=SANDBOX_ROOT, hash_strategy="bounded")
        source_mtime_before = sandbox.source_project.stat().st_mtime
        source_hash_before = hash_project(sandbox.source_root, preferred_strategy="bounded")
        try:
            lifecycle = launch_sandboxed_wwise(sandbox, env)
            assert str(sandbox.sandbox_project) in lifecycle.command
            assert str(EXPECTED_SAMPLE_PROJECT) not in lifecycle.command

            client = default_waapi_client_factory(lifecycle.waapi_url)
            info = _metadata(client.call("ak.wwise.core.getInfo"))
            _assert_2024_version_display_name(info["version"]["displayName"])
            assert info["isCommandLine"] is True

            manifest = build_manifest_from_caller(
                client,
                version=EXPECTED_WWISE_VERSION,
                inventory_source="live-reflection-2024.1-sandbox-smoke",
                wwise_build=WWISE_BUILD,
            )
            store = ManifestStore(root=tmp_path)
            store.write_manifest(manifest)
            loaded = store.load(EXPECTED_WWISE_VERSION)
            audit = audit_manifest(loaded)

            assert audit.counts_match is True
            assert audit.manifest_function_count == 148
            assert audit.manifest_topic_count == 30
            assert audit.schema_count == audit.manifest_function_count + audit.manifest_topic_count
            assert audit.schema_failure_count == 0
            manifest_text = (tmp_path / EXPECTED_WWISE_VERSION / "manifest.json").read_text(encoding="utf-8")
            assert "/Applications/Audiokinetic" not in manifest_text
            failed = False
        finally:
            if client is not None:
                client.disconnect()
            if lifecycle is not None:
                shutdown_sandboxed_wwise(lifecycle, sandbox)
            cleanup_sandbox(sandbox, failed=failed)

    assert sandbox.source_project.stat().st_mtime == source_mtime_before
    assert hash_project(sandbox.source_root, preferred_strategy="bounded").digest == source_hash_before.digest
    assert not sandbox.sandbox_path.exists()


def _metadata(result: Any) -> Mapping[str, Any]:
    assert isinstance(result, Mapping), f"getInfo result must be a mapping, got {type(result).__name__}"
    version = result.get("version")
    assert isinstance(version, Mapping), f"getInfo result must include version mapping, got {result!r}"
    return result


def _assert_2024_version_display_name(display_name: Any) -> None:
    assert isinstance(display_name, str), f"version displayName must be a string, got {type(display_name).__name__}"
    normalized = display_name.removeprefix("v")
    assert normalized == EXPECTED_WWISE_VERSION or normalized.startswith(f"{EXPECTED_WWISE_VERSION}."), (
        f"version displayName {display_name!r} must target {EXPECTED_WWISE_VERSION}"
    )
