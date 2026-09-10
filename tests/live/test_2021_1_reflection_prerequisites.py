from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from tests.support.active_gate_failures import skip_or_fail_strict_real  # pyright: ignore[reportMissingImports]
from wwise_waapi.headless import LifecycleTimeouts, default_waapi_client_factory  # pyright: ignore[reportMissingImports]
from tests.destructive.support.live_environment import (  # pyright: ignore[reportMissingImports]
    ENV_WWISE_CONSOLE,
    ENV_WWISE_LIVE,
    ENV_WWISE_SAMPLE_PROJECT_PATH,
    ENV_WWISE_VERSION,
    LiveEnvironmentContract,
    LiveEnvironmentError,
    WWISE_2021_1_CONSOLE_PATH,
    WWISE_2021_1_SAMPLE_PROJECT_PATH,
    require_live_environment,
)
from wwise_waapi.manifest import (  # pyright: ignore[reportMissingImports]
    DeterministicJsonWriter,
    ManifestStore,
    audit_manifest,
    build_manifest_from_caller,
)
from tests.destructive.support.sandbox_fixture import (  # pyright: ignore[reportMissingImports]
    LiveSandboxLock,
    cleanup_sandbox,
    hash_project,
    launch_sandboxed_wwise,
    prepare_sample_project_sandbox,
    shutdown_sandboxed_wwise,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_WWISE_VERSION = "2021.1"
EXPECTED_WWISE_BUILD = "2021.1.14.8108"
EXPECTED_DISPLAY_PREFIX = "2021.1.14"
EXPECTED_WWISE_CONSOLE = WWISE_2021_1_CONSOLE_PATH
EXPECTED_SAMPLE_PROJECT = WWISE_2021_1_SAMPLE_PROJECT_PATH
SOURCE_URIS = [
    "ak.wwise.waapi.getFunctions",
    "ak.wwise.waapi.getTopics",
    "ak.wwise.waapi.getSchema",
]
REDACTED_LOCAL_PATH = "<local-path-redacted>"
REFLECTION_TIMEOUTS = LifecycleTimeouts(readiness=180.0)
SANDBOX_ROOT = REPO_ROOT / ".waapi-skill-state" / "runtime" / "wwise-2021-live-read-only-sandboxes"
EVIDENCE_ROOT = REPO_ROOT / ".waapi-skill-state" / "evidence" / "wwise-2021-waapi-integration-coverage"
REFLECTION_EVIDENCE_ROOT = EVIDENCE_ROOT / "reflection"
TASK_REFLECTION_EVIDENCE = EVIDENCE_ROOT / "task-4-reflection.json"
PREREQUISITE_EVIDENCE = REFLECTION_EVIDENCE_ROOT / "prerequisites-unavailable.json"
LOCAL_PATH_PATTERN = re.compile(
    r"(?:/(?:Applications|Users|Volumes|private|tmp)/[^\n\r\t\"'<>]+)|(?:[A-Za-z]:\\[^\n\r\t\"'<>]+)"
)


@pytest.mark.parametrize("display_name", ["2021.1.14", "v2021.1.14", "2021.1.14.8108"])
def test_2021_1_version_display_name_accepts_exact_2021_1_14_shapes(display_name: str) -> None:
    _assert_2021_1_exact_version(
        {"version": {"build": 8108, "displayName": display_name, "major": 1, "minor": 14, "year": 2021}}
    )


@pytest.mark.parametrize("display_name", ["2021.1", "2021.1.13", "2022.1.14", "v2021.2.0"])
def test_2021_1_version_display_name_rejects_non_exact_2021_1_14_shapes(display_name: str) -> None:
    with pytest.raises(AssertionError):
        _assert_2021_1_exact_version({"version": {"displayName": display_name}})


@pytest.mark.live
def test_2021_1_live_reflection_prerequisites_and_resource_generation(
    tmp_path: Path,
) -> None:
    contract = require_2021_1_live_environment()
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
            lifecycle = launch_sandboxed_wwise(sandbox, env, timeouts=REFLECTION_TIMEOUTS)
            assert str(sandbox.sandbox_project) in lifecycle.command
            assert str(EXPECTED_SAMPLE_PROJECT) not in lifecycle.command

            client = default_waapi_client_factory(lifecycle.waapi_url)
            info = _metadata(client.call("ak.wwise.core.getInfo"))
            _assert_2021_1_exact_version(info)
            assert info["isCommandLine"] is True

            manifest = build_manifest_from_caller(
                client,
                version=EXPECTED_WWISE_VERSION,
                inventory_source="live-reflection-2021.1-sandbox-manifest",
                wwise_build=EXPECTED_WWISE_BUILD,
            )
            manifest.metadata.update(
                {
                    "version_key": EXPECTED_WWISE_VERSION,
                    "provenance": {
                        "sample_project": {
                            "name": EXPECTED_SAMPLE_PROJECT.stem,
                        },
                    },
                }
            )

            # Real validation must not rewrite the packaged source inventory.
            # Persist the freshly reflected candidate below the disposable
            # test root, then audit its exact round trip there.
            reflected_root = tmp_path / "reflected-manifest"
            store = ManifestStore(root=reflected_root)
            written = store.write_manifest(manifest)
            loaded = store.load(EXPECTED_WWISE_VERSION)
            audit = audit_manifest(loaded)

            assert {path.name for path in written} == {"manifest.json", "functions.json", "topics.json", "schemas.json"}
            assert audit.counts_match is True
            assert audit.manifest_function_count > 0
            assert audit.manifest_topic_count > 0
            assert audit.schema_count == audit.manifest_function_count + audit.manifest_topic_count
            assert audit.schema_failure_count == 0
            assert loaded["metadata"]["source_uris"] == SOURCE_URIS

            _write_reflection_evidence(info=info, manifest=loaded, sandbox_project=str(sandbox.sandbox_project))
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


def require_2021_1_live_environment() -> LiveEnvironmentContract:
    if os.getenv(ENV_WWISE_LIVE) != "1":
        _skip_with_prerequisite_evidence(f"{ENV_WWISE_LIVE}=1 is required for 2021.1 live reflection gates")
    if os.getenv(ENV_WWISE_VERSION) != EXPECTED_WWISE_VERSION:
        _skip_with_prerequisite_evidence(f"{ENV_WWISE_VERSION}=2021.1 is required for 2021.1 live reflection gates")

    try:
        contract = require_live_environment()
    except LiveEnvironmentError as exc:
        _skip_with_prerequisite_evidence(str(exc))
        raise AssertionError("unreachable after prerequisite skip")

    if contract.console_path != EXPECTED_WWISE_CONSOLE:
        _skip_with_prerequisite_evidence(
            f"{ENV_WWISE_CONSOLE} must be the exact 2021.1 WwiseConsole path "
            f"{EXPECTED_WWISE_CONSOLE}; got {contract.console_path}"
        )
    if contract.sample_project_source != EXPECTED_SAMPLE_PROJECT:
        _skip_with_prerequisite_evidence(
            f"{ENV_WWISE_SAMPLE_PROJECT_PATH} must be the exact 2021.1 SampleProject path "
            f"{EXPECTED_SAMPLE_PROJECT}; got {contract.sample_project_source}"
        )
    return contract


def _metadata(result: Any) -> Mapping[str, Any]:
    assert isinstance(result, Mapping), f"getInfo result must be a mapping, got {type(result).__name__}"
    version = result.get("version")
    assert isinstance(version, Mapping), f"getInfo result must include version mapping, got {result!r}"
    return result


def _assert_2021_1_exact_version(info: Mapping[str, Any]) -> None:
    version = info["version"]
    assert isinstance(version, Mapping), f"version must be a mapping, got {type(version).__name__}"
    display_name = version.get("displayName")
    assert isinstance(display_name, str), f"version displayName must be a string, got {type(display_name).__name__}"
    normalized = display_name.removeprefix("v")
    assert version.get("build") == 8108, f"version build must be 8108, got {version.get('build')!r}"
    assert version.get("year") == 2021, f"version year must be 2021, got {version.get('year')!r}"
    assert version.get("major") == 1, f"version major must be 1, got {version.get('major')!r}"
    assert version.get("minor") == 14, f"version minor must be 14, got {version.get('minor')!r}"
    assert normalized == EXPECTED_DISPLAY_PREFIX or normalized == EXPECTED_WWISE_BUILD, (
        f"version displayName {display_name!r} must be exact {EXPECTED_DISPLAY_PREFIX}/{EXPECTED_WWISE_BUILD}"
    )
    serialized = json.dumps(info, sort_keys=True)
    if EXPECTED_WWISE_BUILD in serialized:
        return
    assert normalized == EXPECTED_DISPLAY_PREFIX, f"getInfo did not report expected 2021.1.14-compatible version: {info!r}"


def _skip_with_prerequisite_evidence(reason: str) -> None:
    payload = {
        "status": "skipped-before-sandbox-copy",
        "reason": reason,
        "expected": {
            ENV_WWISE_VERSION: EXPECTED_WWISE_VERSION,
            ENV_WWISE_CONSOLE: REDACTED_LOCAL_PATH,
            ENV_WWISE_SAMPLE_PROJECT_PATH: REDACTED_LOCAL_PATH,
            ENV_WWISE_LIVE: "1",
        },
        "actual": {
            ENV_WWISE_VERSION: os.getenv(ENV_WWISE_VERSION),
            ENV_WWISE_CONSOLE: _scrub_local_paths(os.getenv(ENV_WWISE_CONSOLE)),
            ENV_WWISE_SAMPLE_PROJECT_PATH: _scrub_local_paths(os.getenv(ENV_WWISE_SAMPLE_PROJECT_PATH)),
            ENV_WWISE_LIVE: os.getenv(ENV_WWISE_LIVE),
        },
        "mutation_attempted": False,
        "sandbox_copy_attempted": False,
        "recorded_at_unix": int(time.time()),
    }
    PREREQUISITE_EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    PREREQUISITE_EVIDENCE.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    skip_or_fail_strict_real(reason)


def _write_reflection_evidence(*, info: Mapping[str, Any], manifest: Mapping[str, Any], sandbox_project: str) -> None:
    writer = DeterministicJsonWriter()
    audit = manifest["audit"]
    metadata = _scrub_local_paths(manifest["metadata"])
    stable_info = _stable_get_info_summary(info)
    summary = {
        "audit": audit,
        "get_info": stable_info,
        "metadata": metadata,
        "read_only_waapi_operations": ["ak.wwise.core.getInfo", *SOURCE_URIS],
        "sandbox_project": _scrub_local_paths(sandbox_project),
        "status": "reflected",
    }
    raw = {
        "functions": manifest["functions"],
        "get_info": stable_info,
        "schemas": manifest["schemas"],
        "topics": manifest["topics"],
    }
    REFLECTION_EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    (REFLECTION_EVIDENCE_ROOT / "raw-reflection.json").write_text(writer.dumps(raw), encoding="utf-8")
    TASK_REFLECTION_EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    TASK_REFLECTION_EVIDENCE.write_text(writer.dumps(summary), encoding="utf-8")


def _stable_get_info_summary(info: Mapping[str, Any]) -> dict[str, Any]:
    version = info["version"]
    assert isinstance(version, Mapping)
    return {
        "apiVersion": info.get("apiVersion"),
        "branch": info.get("branch"),
        "configuration": info.get("configuration"),
        "isCommandLine": info.get("isCommandLine"),
        "platform": info.get("platform"),
        "version": {
            "build": version.get("build"),
            "displayName": version.get("displayName"),
            "major": version.get("major"),
            "minor": version.get("minor"),
            "schema": version.get("schema"),
            "year": version.get("year"),
        },
    }


def _scrub_local_paths(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _scrub_local_paths(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_scrub_local_paths(item) for item in value]
    if isinstance(value, tuple):
        return [_scrub_local_paths(item) for item in value]
    if isinstance(value, str):
        return LOCAL_PATH_PATTERN.sub("<local-path-redacted>", value)
    return value
