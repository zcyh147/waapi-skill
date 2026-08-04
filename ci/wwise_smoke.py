from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

# Direct execution sets sys.path[0] to ``ci`` rather than the repository root.
# Bind imports to this checkout before importing the test lifecycle package.
REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "waapi-skill"
for import_root in (SKILL_ROOT, REPO_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from tests.destructive.support.sandbox_fixture import (  # pyright: ignore[reportMissingImports]
    LiveSandboxLock,
    SandboxProject,
    cleanup_sandbox,
    hash_project,
    launch_sandboxed_wwise,
    prepare_sample_project_sandbox,
    require_lifecycle_ready_proof,
    resolve_safe_sandbox_root,
    shutdown_sandboxed_wwise,
)
from wwise_waapi.headless import HeadlessLifecycle  # pyright: ignore[reportMissingImports]
from wwise_waapi.versions import (  # pyright: ignore[reportMissingImports]
    WWISE_VERSION_CONTRACTS,
    version_key_from_get_info,
)


SMOKE_CONTRACT = "waapi-skill.real-smoke/v1"
SMOKE_SUCCESS_PREFIX = "smoke ok:"


class WwiseSmokeError(RuntimeError):
    """Raised when a real smoke run lacks its required business or cleanup proof."""


def _validate_console_get_info(
    result: Mapping[str, Any],
    *,
    expected_version: str,
) -> str:
    if result.get("isCommandLine") is not True:
        raise WwiseSmokeError(
            "smoke requires WwiseConsole getInfo with isCommandLine=true"
        )
    try:
        actual_version = version_key_from_get_info(result)
    except ValueError as exc:
        raise WwiseSmokeError(str(exc)) from exc
    if actual_version != expected_version:
        raise WwiseSmokeError(
            f"connected Wwise version is {actual_version}, expected {expected_version}"
        )

    version = result.get("version")
    assert isinstance(version, Mapping)
    values: list[int] = []
    for field_name in ("year", "major", "minor", "build"):
        value = version.get(field_name)
        if type(value) is not int:
            raise WwiseSmokeError(
                f"getInfo version.{field_name} must be an integer"
            )
        values.append(value)
    actual_build = ".".join(str(value) for value in values)
    expected_build = WWISE_VERSION_CONTRACTS[expected_version].build
    if actual_build != expected_build:
        raise WwiseSmokeError(
            f"connected Wwise build is {actual_build}, expected {expected_build}"
        )
    return actual_build


def _require_source_unchanged(
    sandbox: SandboxProject,
    *,
    source_mtime_ns_before: int,
) -> tuple[str, int]:
    final_hash = hash_project(sandbox.source_root, preferred_strategy="full")
    if final_hash != sandbox.metadata.source_hash:
        raise WwiseSmokeError("immutable source project full hash changed during smoke")
    final_mtime_ns = sandbox.source_project.stat().st_mtime_ns
    if final_mtime_ns != source_mtime_ns_before:
        raise WwiseSmokeError(
            "immutable source project mtime changed during smoke: "
            f"expected {source_mtime_ns_before}, got {final_mtime_ns}"
        )
    return final_hash.digest, final_mtime_ns


def _success_payload(
    sandbox: SandboxProject,
    *,
    build: str,
    source_sha256: str,
    source_mtime_ns: int,
) -> dict[str, Any]:
    metadata = sandbox.metadata
    command = metadata.command
    pid = metadata.process_pid
    port = metadata.selected_port
    ready_duration = metadata.ready_duration_seconds
    display_name = metadata.get_info_display_name
    sandbox_path = sandbox.sandbox_path
    if not isinstance(command, list) or not command:
        raise WwiseSmokeError("smoke launch command proof is missing")
    if type(pid) is not int or pid <= 0:
        raise WwiseSmokeError("smoke process pid proof is missing")
    if type(port) is not int or not 1 <= port <= 65535:
        raise WwiseSmokeError("smoke WAAPI port proof is missing")
    if type(ready_duration) not in {int, float} or ready_duration < 0:
        raise WwiseSmokeError("smoke readiness duration proof is missing")
    if not isinstance(display_name, str) or not display_name:
        raise WwiseSmokeError("smoke getInfo displayName proof is missing")
    if metadata.process_cleanup_result != "cleaned":
        raise WwiseSmokeError("smoke WwiseConsole cleanup is not proven clean")
    if os.path.lexists(sandbox_path):
        raise WwiseSmokeError(f"smoke sandbox was not deleted: {sandbox_path}")
    return {
        "argv": command,
        "build": build,
        "cleanup": "cleaned",
        "contract": SMOKE_CONTRACT,
        "display_name": display_name,
        "isCommandLine": True,
        "pid": pid,
        "port": port,
        "ready_duration_seconds": ready_duration,
        "sandbox_deleted": True,
        "sandbox_project": str(sandbox.sandbox_project),
        "source_mtime_ns": source_mtime_ns,
        "source_sha256": source_sha256,
        "version": metadata.wwise_version,
    }


def _best_effort_failure_cleanup(
    lifecycle: HeadlessLifecycle | None,
    sandbox: SandboxProject | None,
) -> list[str]:
    errors: list[str] = []
    cleanup_report = getattr(lifecycle, "cleanup_report", None)
    cleanup_is_clean = cleanup_report is not None and cleanup_report.is_clean
    if lifecycle is not None and sandbox is not None and not cleanup_is_clean:
        try:
            shutdown_sandboxed_wwise(lifecycle, sandbox, suppress_errors=True)
        except BaseException as exc:  # noqa: BLE001 - preserve cleanup diagnostics.
            errors.append(f"shutdown:{type(exc).__name__}:{exc}")
    if sandbox is not None and os.path.lexists(sandbox.sandbox_path):
        try:
            cleanup_sandbox(sandbox, failed=True)
        except BaseException as exc:  # noqa: BLE001 - preserve cleanup diagnostics.
            errors.append(f"sandbox:{type(exc).__name__}:{exc}")
    return errors


def _configured_port(env: Mapping[str, str]) -> int | None:
    raw = env.get("WWISE_WAAPI_PORT")
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw:
        raise WwiseSmokeError("WWISE_WAAPI_PORT must be a positive integer")
    try:
        port = int(raw, 10)
    except ValueError as exc:
        raise WwiseSmokeError(
            "WWISE_WAAPI_PORT must be a positive integer"
        ) from exc
    if not 1 <= port <= 65535:
        raise WwiseSmokeError("WWISE_WAAPI_PORT must be between 1 and 65535")
    return port


def run_smoke(environment: Mapping[str, str] | None = None) -> dict[str, Any]:
    env = dict(os.environ if environment is None else environment)
    expected_version = env.get("WWISE_VERSION")
    if (
        not isinstance(expected_version, str)
        or expected_version not in WWISE_VERSION_CONTRACTS
    ):
        raise WwiseSmokeError(
            f"WWISE_VERSION must be one supported version; got {expected_version!r}"
        )

    source_text = env.get("WWISE_SAMPLE_PROJECT_PATH")
    if not isinstance(source_text, str) or not source_text:
        raise WwiseSmokeError("WWISE_SAMPLE_PROJECT_PATH is required")
    source_project = Path(source_text).expanduser().resolve(strict=True)
    source_mtime_ns_before = source_project.stat().st_mtime_ns
    # Validate before LiveSandboxLock creates its sentinel file.  A bad root
    # must not mutate the immutable source even while failing closed.
    sandbox_root = resolve_safe_sandbox_root(env)

    with LiveSandboxLock(sandbox_root):
        return _run_smoke_locked(
            env,
            expected_version=expected_version,
            source_mtime_ns_before=source_mtime_ns_before,
        )


def _run_smoke_locked(
    env: Mapping[str, str],
    *,
    expected_version: str,
    source_mtime_ns_before: int,
) -> dict[str, Any]:

    sandbox: SandboxProject | None = None
    lifecycle: HeadlessLifecycle | None = None
    sandbox_deleted = False
    try:
        sandbox = prepare_sample_project_sandbox(env, hash_strategy="full")
        if sandbox.source_project.stat().st_mtime_ns != source_mtime_ns_before:
            raise WwiseSmokeError(
                "immutable source project mtime changed while preparing smoke sandbox"
            )

        launch_env = dict(env)
        launch_env["WWISE_LIVE"] = "1"
        launch_env["WWISE_DESTRUCTIVE"] = "0"
        lifecycle = launch_sandboxed_wwise(
            sandbox,
            launch_env,
            port=_configured_port(launch_env),
        )
        ready_info = require_lifecycle_ready_proof(lifecycle)
        build = _validate_console_get_info(
            ready_info,
            expected_version=expected_version,
        )

        metadata = sandbox.metadata
        print(f"smoke sandbox: {sandbox.sandbox_project}", flush=True)
        print(f"smoke argv: {metadata.command!r}", flush=True)
        print(f"smoke pid: {metadata.process_pid}", flush=True)
        print(f"smoke port: {metadata.selected_port}", flush=True)
        print(
            f"smoke ready_duration_seconds: {metadata.ready_duration_seconds}",
            flush=True,
        )

        shutdown_sandboxed_wwise(lifecycle, sandbox, suppress_errors=False)
        source_sha256, source_mtime_ns = _require_source_unchanged(
            sandbox,
            source_mtime_ns_before=source_mtime_ns_before,
        )
        cleanup_sandbox(sandbox, failed=False)
        sandbox_deleted = True
        return _success_payload(
            sandbox,
            build=build,
            source_sha256=source_sha256,
            source_mtime_ns=source_mtime_ns,
        )
    except BaseException as exc:
        cleanup_errors = _best_effort_failure_cleanup(
            lifecycle,
            sandbox,
        )
        if cleanup_errors:
            raise WwiseSmokeError(
                f"{type(exc).__name__}: {exc}; cleanup errors: {cleanup_errors!r}"
            ) from exc
        raise
    finally:
        if sandbox_deleted and sandbox is not None and os.path.lexists(
            sandbox.sandbox_path
        ):
            raise WwiseSmokeError(
                f"smoke sandbox reappeared after deletion: {sandbox.sandbox_path}"
            )


def main() -> int:
    payload = run_smoke()
    print(
        f"{SMOKE_SUCCESS_PREFIX}"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
