from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.headless import default_waapi_client_factory  # pyright: ignore[reportMissingImports]
from wwise_waapi.live_environment import (  # pyright: ignore[reportMissingImports]
    ENV_WWISE_CONSOLE,
    ENV_WWISE_LIVE,
    ENV_WWISE_SAMPLE_PROJECT_PATH,
    ENV_WWISE_VERSION,
    LiveEnvironmentContract,
    LiveEnvironmentError,
    require_live_environment,
)
from wwise_waapi.sandbox_fixture import (  # pyright: ignore[reportMissingImports]
    LiveSandboxLock,
    cleanup_sandbox,
    hash_project,
    launch_sandboxed_wwise,
    prepare_sample_project_sandbox,
    shutdown_sandboxed_wwise,
)

from tests.live.test_2021_1_reflection_prerequisites import (  # pyright: ignore[reportMissingImports]
    EXPECTED_SAMPLE_PROJECT,
    EXPECTED_WWISE_BUILD,
    EXPECTED_WWISE_CONSOLE,
    EXPECTED_WWISE_VERSION,
    REFLECTION_TIMEOUTS,
    SANDBOX_ROOT,
    _assert_2021_1_exact_version,
    _metadata,
    _stable_get_info_summary,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = REPO_ROOT / ".sisyphus" / "evidence" / "wwise-2021-waapi-integration-coverage" / "live-read-only"
PREREQUISITE_EVIDENCE = EVIDENCE_ROOT / "prerequisites-unavailable.json"
TASK_PREREQUISITE_EVIDENCE = EVIDENCE_ROOT / "task-8-live-prerequisites.json"
EXPECTED_DISPLAY_NAME = "v2021.1.14"
EXPECTED_BRANCH = "wwise_v2021.1"
EXACT_LIVE_COMMAND = (
    f'{ENV_WWISE_VERSION}=2021.1 '
    f'{ENV_WWISE_CONSOLE}="{EXPECTED_WWISE_CONSOLE}" '
    f'{ENV_WWISE_SAMPLE_PROJECT_PATH}="{EXPECTED_SAMPLE_PROJECT}" '
    f'{ENV_WWISE_LIVE}=1 python -m pytest '
    "tests/live/test_2021_1_live_prerequisites.py tests/live/test_2021_1_object_get_matrix.py -q"
)
READ_ONLY_WAAPI_OPERATIONS = ["ak.wwise.core.getInfo"]
FOLLOW_ON_READ_ONLY_WAAPI_OPERATIONS = ["ak.wwise.core.object.get"]


def test_2021_1_missing_live_opt_in_skips_without_promoted_behavior_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    prerequisite_evidence = tmp_path / "prerequisites-unavailable.json"
    promoted_evidence = tmp_path / "task-8-live-prerequisites.json"
    _redirect_evidence(monkeypatch, prerequisite_evidence=prerequisite_evidence, promoted_evidence=promoted_evidence)
    monkeypatch.delenv(ENV_WWISE_LIVE, raising=False)
    monkeypatch.setenv(ENV_WWISE_VERSION, EXPECTED_WWISE_VERSION)
    monkeypatch.setenv(ENV_WWISE_CONSOLE, str(EXPECTED_WWISE_CONSOLE))
    monkeypatch.setenv(ENV_WWISE_SAMPLE_PROJECT_PATH, str(EXPECTED_SAMPLE_PROJECT))

    with pytest.raises(pytest.skip.Exception):
        require_2021_1_read_only_live_environment()

    payload = json.loads(prerequisite_evidence.read_text(encoding="utf-8"))
    assert payload["status"] == "skipped-before-live-launch"
    assert payload["reason"] == f"{ENV_WWISE_LIVE}=1 is required for 2021.1 live read-only prerequisite gates"
    assert payload["mutation_attempted"] is False
    assert payload["sandbox_copy_attempted"] is False
    assert payload["waapi_calls_attempted"] == []
    assert not promoted_evidence.exists()


@pytest.mark.parametrize(
    ("env_name", "bad_value", "expected_fragment"),
    [
        (ENV_WWISE_VERSION, "2024.1", f"{ENV_WWISE_VERSION}=2021.1 is required"),
        (ENV_WWISE_CONSOLE, "/tmp/wrong-2021/WwiseConsole.sh", f"{ENV_WWISE_CONSOLE} must be the exact 2021.1"),
        (
            ENV_WWISE_SAMPLE_PROJECT_PATH,
            "/tmp/wrong-2021/SampleProject.wproj",
            f"{ENV_WWISE_SAMPLE_PROJECT_PATH} must be the exact 2021.1",
        ),
    ],
)
def test_2021_1_version_and_path_mismatches_abort_before_live_launch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, env_name: str, bad_value: str, expected_fragment: str
) -> None:
    prerequisite_evidence = tmp_path / f"{env_name}-prerequisites-unavailable.json"
    promoted_evidence = tmp_path / f"{env_name}-task-8-live-prerequisites.json"
    _redirect_evidence(monkeypatch, prerequisite_evidence=prerequisite_evidence, promoted_evidence=promoted_evidence)
    monkeypatch.setenv(ENV_WWISE_LIVE, "1")
    monkeypatch.setenv(ENV_WWISE_VERSION, EXPECTED_WWISE_VERSION)
    monkeypatch.setenv(ENV_WWISE_CONSOLE, str(EXPECTED_WWISE_CONSOLE))
    monkeypatch.setenv(ENV_WWISE_SAMPLE_PROJECT_PATH, str(EXPECTED_SAMPLE_PROJECT))
    monkeypatch.setenv(env_name, bad_value)

    with pytest.raises(pytest.skip.Exception) as skipped:
        require_2021_1_read_only_live_environment()

    assert expected_fragment in str(skipped.value)
    payload = json.loads(prerequisite_evidence.read_text(encoding="utf-8"))
    assert payload["status"] == "skipped-before-live-launch"
    assert payload["waapi_calls_attempted"] == []
    assert payload["wwise_launch_attempted"] is False
    assert payload["mutation_attempted"] is False
    assert payload["sandbox_copy_attempted"] is False
    assert not promoted_evidence.exists()


@pytest.mark.parametrize("display_name", ["2021.1.14", "2021.1.14.8108"])
def test_2021_1_live_get_info_rejects_non_exact_display_name(display_name: str) -> None:
    with pytest.raises(AssertionError):
        _assert_2021_1_exact_live_get_info(
            {
                "branch": EXPECTED_BRANCH,
                "isCommandLine": True,
                "version": {"build": 8108, "displayName": display_name, "major": 1, "minor": 14, "year": 2021},
            }
        )


def test_2021_1_live_get_info_requires_exact_branch_and_command_line() -> None:
    valid = {
        "branch": EXPECTED_BRANCH,
        "isCommandLine": True,
        "version": {"build": 8108, "displayName": EXPECTED_DISPLAY_NAME, "major": 1, "minor": 14, "year": 2021},
    }
    _assert_2021_1_exact_live_get_info(valid)

    for override in ({"branch": "wwise_v2021.1.14"}, {"isCommandLine": False}):
        candidate = dict(valid)
        candidate.update(override)
        with pytest.raises(AssertionError):
            _assert_2021_1_exact_live_get_info(candidate)


@pytest.mark.live
def test_2021_1_live_read_only_prerequisites_validate_exact_get_info_before_matrix() -> None:
    contract = require_2021_1_read_only_live_environment()
    assert contract.version == EXPECTED_WWISE_VERSION
    console_path = contract.console_path
    sample_project = contract.sample_project_source
    assert console_path is not None
    assert sample_project is not None
    assert console_path == EXPECTED_WWISE_CONSOLE
    assert sample_project == EXPECTED_SAMPLE_PROJECT
    assert console_path.exists()
    assert sample_project.exists()
    assert sample_project.suffix == ".wproj"

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
            _assert_2021_1_exact_live_get_info(info)
            _write_prerequisite_pass_evidence(info=info, sandbox_project=str(sandbox.sandbox_project))
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


def require_2021_1_read_only_live_environment() -> LiveEnvironmentContract:
    if os.getenv(ENV_WWISE_LIVE) != "1":
        _skip_with_prerequisite_evidence(
            f"{ENV_WWISE_LIVE}=1 is required for 2021.1 live read-only prerequisite gates"
        )
    if os.getenv(ENV_WWISE_VERSION) != EXPECTED_WWISE_VERSION:
        _skip_with_prerequisite_evidence(
            f"{ENV_WWISE_VERSION}=2021.1 is required for 2021.1 live read-only prerequisite gates"
        )

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


def _assert_2021_1_exact_live_get_info(info: Mapping[str, Any]) -> None:
    _assert_2021_1_exact_version(info)
    version = info["version"]
    assert isinstance(version, Mapping)
    assert version.get("displayName") == EXPECTED_DISPLAY_NAME, (
        f"version displayName must be exact {EXPECTED_DISPLAY_NAME}, got {version.get('displayName')!r}"
    )
    assert info.get("branch") == EXPECTED_BRANCH, f"branch must be {EXPECTED_BRANCH}, got {info.get('branch')!r}"
    assert info.get("isCommandLine") is True, f"isCommandLine must be True, got {info.get('isCommandLine')!r}"


def _redirect_evidence(
    monkeypatch: pytest.MonkeyPatch, *, prerequisite_evidence: Path, promoted_evidence: Path
) -> None:
    module = sys.modules[__name__]
    monkeypatch.setattr(module, "PREREQUISITE_EVIDENCE", prerequisite_evidence)
    monkeypatch.setattr(module, "TASK_PREREQUISITE_EVIDENCE", promoted_evidence)


def _skip_with_prerequisite_evidence(reason: str) -> None:
    payload = {
        "status": "skipped-before-live-launch",
        "reason": reason,
        "expected": _expected_env(),
        "actual": {
            ENV_WWISE_VERSION: os.getenv(ENV_WWISE_VERSION),
            ENV_WWISE_CONSOLE: os.getenv(ENV_WWISE_CONSOLE),
            ENV_WWISE_SAMPLE_PROJECT_PATH: os.getenv(ENV_WWISE_SAMPLE_PROJECT_PATH),
            ENV_WWISE_LIVE: os.getenv(ENV_WWISE_LIVE),
        },
        "exact_command": EXACT_LIVE_COMMAND,
        "mutation_attempted": False,
        "sandbox_copy_attempted": False,
        "wwise_launch_attempted": False,
        "waapi_calls_attempted": [],
        "promoted_behavior_evidence_written": False,
        "read_only_waapi_operations": READ_ONLY_WAAPI_OPERATIONS,
        "recorded_at_unix": int(time.time()),
    }
    PREREQUISITE_EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    PREREQUISITE_EVIDENCE.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    pytest.skip(reason)


def _write_prerequisite_pass_evidence(*, info: Mapping[str, Any], sandbox_project: str) -> None:
    payload = {
        "status": "passed",
        "task": "8. Add 2021.1 live read-only prerequisites and exact-session evidence",
        "exact_command": EXACT_LIVE_COMMAND,
        "env": _expected_env(),
        "get_info": _stable_get_info_summary(info),
        "assertions": {
            "displayName": EXPECTED_DISPLAY_NAME,
            "build": 8108,
            "year": 2021,
            "branch": EXPECTED_BRANCH,
            "isCommandLine": True,
        },
        "sandbox_project": sandbox_project,
        "sandbox_required": True,
        "source_project_mutation_allowed": False,
        "mutation_attempted": False,
        "destructive_enabled": False,
        "read_only_waapi_operations": READ_ONLY_WAAPI_OPERATIONS,
        "follow_on_read_only_waapi_operations": FOLLOW_ON_READ_ONLY_WAAPI_OPERATIONS,
        "evidence_scope": "prerequisite getInfo exact-session proof before object.get matrix promotion",
        "recorded_at_unix": int(time.time()),
    }
    TASK_PREREQUISITE_EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    TASK_PREREQUISITE_EVIDENCE.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _expected_env() -> dict[str, str]:
    return {
        ENV_WWISE_VERSION: EXPECTED_WWISE_VERSION,
        ENV_WWISE_CONSOLE: str(EXPECTED_WWISE_CONSOLE),
        ENV_WWISE_SAMPLE_PROJECT_PATH: str(EXPECTED_SAMPLE_PROJECT),
        ENV_WWISE_LIVE: "1",
    }
