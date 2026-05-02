"""2021.1 destructive sandbox helpers for live WAAPI tests."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from types import TracebackType
from typing import Any, Mapping

from .headless import HeadlessLifecycleError, default_waapi_client_factory
from .live_environment import (
    ENV_WWISE_DESTRUCTIVE,
    ENV_WWISE_LIVE,
    ENV_WWISE_SANDBOX_ROOT,
    ENV_WWISE_VERSION,
    LiveEnvironmentContract,
    LiveEnvironmentError,
    WWISE_2021_1_CONSOLE_PATH,
    WWISE_2021_1_SAMPLE_PROJECT_PATH,
    path_is_under,
    path_is_under_immutable_sample_source,
    path_is_under_org_fixture,
    path_overlaps_immutable_sample_source,
    require_destructive_environment,
    require_live_environment,
    resolve_sample_project_source,
)
from .sandbox_fixture import (
    LiveSandboxLock,
    SandboxFixtureError,
    SandboxProject,
    cleanup_sandbox,
    launch_sandboxed_wwise,
    prepare_sample_project_sandbox,
    shutdown_sandboxed_wwise,
)
from .versions import WWISE_2021_1_VERSION_KEY  # pyright: ignore[reportMissingImports]


DEFAULT_2021_DESTRUCTIVE_SANDBOX_ROOT = Path(".sisyphus") / "runtime" / "wwise-2021-destructive-sandboxes"
GENERATED_OUTPUT_DIR_NAMES = {
    ".cache",
    "GeneratedSoundBanks",
    "Originals",
    "Task2021GeneratedAudio",
    "Task2021SoundBankDefinitions",
}


class DestructiveSandboxUnavailable(RuntimeError):
    """Raised when an explicitly enabled destructive sandbox cannot be prepared safely."""


class Destructive2021SandboxRuntime:
    """Prepare, launch, and clean up a Wwise 2021.1 copied SampleProject sandbox."""

    def __init__(self, env: Mapping[str, str] | None = None, *, track_generated_outputs: bool = False) -> None:
        self.env = dict(env if env is not None else os.environ)
        self.track_generated_outputs = track_generated_outputs
        self.lock: LiveSandboxLock | None = None
        self.sandbox: SandboxProject | None = None
        self.lifecycle: Any = None
        self.client: Any = None
        self.destructive_contract: LiveEnvironmentContract | None = None
        self.failed = True
        self.source_mtime_before = 0.0
        self.source_project_files_hash_before: tuple[str, int, int] | None = None
        self.source_generated_snapshot_before: tuple[str, ...] = ()

    def __enter__(self) -> "Destructive2021SandboxRuntime":
        try:
            require_2021_live_destructive_prerequisites(self.env)
            self.lock = LiveSandboxLock(_safe_lock_root(self.env))
            self.lock.__enter__()
            cleanup_stale_2021_destructive_sandboxes(_configured_sandbox_root(self.env))
            self.sandbox = prepare_sample_project_sandbox(
                self.env,
                sandbox_root=_configured_sandbox_root(self.env),
                hash_strategy="bounded",
            )
            self.source_mtime_before = self.sandbox.source_project.stat().st_mtime
            self.source_project_files_hash_before = hash_mutation_bearing_project_files(self.sandbox.source_root)
            self.destructive_contract = require_2021_sandbox_copy_target(self.env, self.sandbox)
            self.assert_source_unchanged()
            if self.track_generated_outputs:
                self.source_generated_snapshot_before = generated_output_snapshot(self.sandbox.source_root)
            self.lifecycle = launch_sandboxed_wwise(self.sandbox, self.env)
            self.client = default_waapi_client_factory(self.lifecycle.waapi_url)
            return self
        except (LiveEnvironmentError, SandboxFixtureError, HeadlessLifecycleError, OSError) as exc:
            self._close_after_enter_failure(type(exc), exc, exc.__traceback__)
            raise DestructiveSandboxUnavailable(
                f"2021.1 destructive sandbox environment blocked execution: {type(exc).__name__}: {exc}"
            ) from exc

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        deferred_error: BaseException | None = None
        try:
            try:
                if self.client is not None:
                    self.client.disconnect()
            except BaseException as disconnect_error:  # noqa: BLE001 - cleanup must continue
                if exc_type is None:
                    deferred_error = disconnect_error
            try:
                if self.lifecycle is not None and self.sandbox is not None:
                    shutdown_sandboxed_wwise(self.lifecycle, self.sandbox)
            except BaseException as shutdown_error:  # noqa: BLE001 - cleanup must continue
                if exc_type is None and deferred_error is None:
                    deferred_error = shutdown_error
            if self.sandbox is not None:
                if self.source_project_files_hash_before is not None and deferred_error is None:
                    try:
                        self.assert_source_unchanged()
                        if exc_type is None:
                            self.failed = False
                    except AssertionError as assertion_error:
                        deferred_error = assertion_error
                try:
                    cleanup_sandbox(self.sandbox, failed=self.failed)
                except BaseException as cleanup_error:  # noqa: BLE001 - lock release must continue
                    if exc_type is None and deferred_error is None:
                        deferred_error = cleanup_error
        finally:
            if self.lock is not None:
                self.lock.__exit__(exc_type, exc, traceback)
                self.lock = None
        if deferred_error is not None and (exc_type is None or isinstance(deferred_error, AssertionError)):
            raise deferred_error

    def require_client(self) -> Any:
        if self.client is None:
            raise AssertionError("WAAPI client was not initialized")
        return self.client

    def require_sandbox(self) -> SandboxProject:
        if self.sandbox is None:
            raise AssertionError("sandbox was not initialized")
        return self.sandbox

    def assert_source_unchanged(self) -> None:
        sandbox = self.require_sandbox()
        assert self.source_project_files_hash_before is not None
        assert sandbox.source_project.stat().st_mtime == self.source_mtime_before
        assert hash_mutation_bearing_project_files(sandbox.source_root) == self.source_project_files_hash_before
        if self.track_generated_outputs:
            assert generated_output_snapshot(sandbox.source_root) == self.source_generated_snapshot_before

    def _close_after_enter_failure(
        self,
        exc_type: type[BaseException],
        exc: BaseException,
        traceback: TracebackType | None,
    ) -> None:
        try:
            self.__exit__(exc_type, exc, traceback)
        except BaseException:
            return


def require_2021_live_destructive_prerequisites(env: Mapping[str, str]) -> LiveEnvironmentContract:
    """Require live/destructive 2021.1 flags and exact installed Wwise paths."""

    if env.get(ENV_WWISE_LIVE) != "1" or env.get(ENV_WWISE_DESTRUCTIVE) != "1":
        raise LiveEnvironmentError("WWISE_LIVE=1 and WWISE_DESTRUCTIVE=1 are required")
    if env.get(ENV_WWISE_VERSION) != WWISE_2021_1_VERSION_KEY:
        raise LiveEnvironmentError("WWISE_VERSION=2021.1 is required for 2021.1 destructive sandbox tests")
    if not env.get(ENV_WWISE_SANDBOX_ROOT):
        raise LiveEnvironmentError("WWISE_SANDBOX_ROOT is required for 2021.1 destructive sandbox tests")
    contract = require_live_environment(env)
    if contract.console_path != WWISE_2021_1_CONSOLE_PATH:
        raise LiveEnvironmentError(
            f"{WWISE_2021_1_VERSION_KEY} destructive tests require exact WwiseConsole path "
            f"{WWISE_2021_1_CONSOLE_PATH}; got {contract.console_path}"
        )
    if contract.sample_project_source != WWISE_2021_1_SAMPLE_PROJECT_PATH:
        raise LiveEnvironmentError(
            f"{WWISE_2021_1_VERSION_KEY} destructive tests require exact SampleProject path "
            f"{WWISE_2021_1_SAMPLE_PROJECT_PATH}; got {contract.sample_project_source}"
        )
    return contract


def require_2021_sandbox_copy_target(env: Mapping[str, str], sandbox: SandboxProject) -> LiveEnvironmentContract:
    """Prove the active destructive project is the copied 2021.1 sandbox, not an immutable source."""

    target_env = dict(env)
    target_env.update(sandbox.env)
    target_env[ENV_WWISE_LIVE] = "1"
    target_env[ENV_WWISE_DESTRUCTIVE] = "1"
    target_env[ENV_WWISE_VERSION] = WWISE_2021_1_VERSION_KEY
    contract = require_destructive_environment(target_env)
    sandbox_project = sandbox.sandbox_project.resolve(strict=False)
    sandbox_root = sandbox.sandbox_root.resolve(strict=False)
    source_project = sandbox.source_project.resolve(strict=True)
    source_root = sandbox.source_root.resolve(strict=True)
    if source_project != WWISE_2021_1_SAMPLE_PROJECT_PATH.resolve(strict=False):
        raise SandboxFixtureError("2021.1 destructive tests must copy the exact installed 2021.1 SampleProject source")
    if contract.active_destructive_project != sandbox_project:
        raise SandboxFixtureError("active destructive project is not the copied sandbox project")
    if not path_is_under(sandbox_project, sandbox_root):
        raise SandboxFixtureError("active destructive project is outside WWISE_SANDBOX_ROOT")
    if sandbox_project == source_project or path_is_under(sandbox_project, source_root):
        raise SandboxFixtureError("active destructive project targets the installed SampleProject source")
    if path_is_under_immutable_sample_source(sandbox_project) or path_is_under_org_fixture(sandbox_project):
        raise SandboxFixtureError("active destructive project targets an immutable source path")
    _reject_hardlinked_project_files(source_root, sandbox.sandbox_path.resolve(strict=False))
    return contract


def hash_mutation_bearing_project_files(root: Path) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    bytes_hashed = 0
    files = [path for path in sorted(root.rglob("*")) if path.suffix.lower() in {".wproj", ".wwu"} and path.is_file()]
    for file_path in files:
        relative = file_path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        data = file_path.read_bytes()
        bytes_hashed += len(data)
        digest.update(data)
        digest.update(b"\0")
    return digest.hexdigest(), len(files), bytes_hashed


def generated_output_snapshot(root: Path) -> tuple[str, ...]:
    paths: list[str] = []
    for path in sorted(root.rglob("*")):
        if any(part in GENERATED_OUTPUT_DIR_NAMES for part in path.relative_to(root).parts):
            paths.append(path.relative_to(root).as_posix())
    return tuple(paths)


def cleanup_stale_2021_destructive_sandboxes(root: Path) -> None:
    """Remove interrupted 2021.1 destructive sandbox copies from the locked runtime root."""

    resolved_root = root.resolve(strict=False)
    if not resolved_root.exists():
        return
    for candidate in resolved_root.iterdir():
        if not candidate.is_dir() or not candidate.name.startswith("sample-project-"):
            continue
        metadata_path = candidate / "sandbox-metadata.json"
        if _is_stale_2021_destructive_sandbox(candidate, metadata_path):
            shutil.rmtree(candidate)


def _is_stale_2021_destructive_sandbox(candidate: Path, metadata_path: Path) -> bool:
    if not metadata_path.is_file():
        return False
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if metadata.get("keep_decision", "pending").startswith("kept:"):
        return False
    sandbox_path = Path(str(metadata.get("sandbox_path", ""))).resolve(strict=False)
    source_path = Path(str(metadata.get("source_path", ""))).resolve(strict=False)
    return (
        sandbox_path == candidate.resolve(strict=False)
        and source_path == WWISE_2021_1_SAMPLE_PROJECT_PATH.resolve(strict=False)
        and path_is_under(candidate.resolve(strict=False), candidate.parent.resolve(strict=False))
    )


def unique_2021_name(prefix: str, label: str) -> str:
    safe_label = "".join(character if character.isalnum() else "_" for character in label)
    return f"{prefix}{safe_label}_{uuid.uuid4().hex[:12]}"


def _configured_sandbox_root(env: Mapping[str, str]) -> Path:
    raw_root = env.get(ENV_WWISE_SANDBOX_ROOT)
    if raw_root:
        return Path(raw_root).expanduser().resolve(strict=False)
    return (Path.cwd() / DEFAULT_2021_DESTRUCTIVE_SANDBOX_ROOT).resolve(strict=False)


def _safe_lock_root(env: Mapping[str, str]) -> Path:
    root = _configured_sandbox_root(env)
    source_project = resolve_sample_project_source(env)
    if source_project is not None:
        source_root = source_project.parent.resolve(strict=False)
        if root == source_root or path_is_under(root, source_root) or path_is_under(source_root, root):
            raise SandboxFixtureError("sandbox lock root must not overlap the immutable SampleProject source")
    if path_is_under_org_fixture(root):
        raise SandboxFixtureError("sandbox lock root must not be under immutable tests/_org fixture sources")
    if path_overlaps_immutable_sample_source(root):
        raise SandboxFixtureError("sandbox lock root must not overlap immutable installed SampleProject sources")
    return root


def _reject_hardlinked_project_files(source_root: Path, sandbox_path: Path) -> None:
    if not sandbox_path.exists():
        return
    for source_file in sorted(source_root.rglob("*")):
        if source_file.suffix.lower() not in {".wproj", ".wwu"} or not source_file.is_file():
            continue
        target_file = sandbox_path / source_file.relative_to(source_root)
        if not target_file.exists() or not target_file.is_file():
            continue
        if source_file.resolve(strict=True) == target_file.resolve(strict=True):
            raise SandboxFixtureError("sandbox project file resolves to the installed SampleProject source")
        try:
            source_stat = source_file.stat()
            target_stat = target_file.stat()
        except OSError:
            continue
        if source_stat.st_dev == target_stat.st_dev and source_stat.st_ino == target_stat.st_ino:
            raise SandboxFixtureError("sandbox project files must not be hardlinks to the installed SampleProject source")


__all__ = [
    "DEFAULT_2021_DESTRUCTIVE_SANDBOX_ROOT",
    "Destructive2021SandboxRuntime",
    "DestructiveSandboxUnavailable",
    "cleanup_stale_2021_destructive_sandboxes",
    "generated_output_snapshot",
    "hash_mutation_bearing_project_files",
    "require_2021_live_destructive_prerequisites",
    "require_2021_sandbox_copy_target",
    "unique_2021_name",
]
