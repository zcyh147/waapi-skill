"""Auditable SampleProject sandbox harness for live Wwise runs."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import tempfile
import time
import uuid
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

from wwise_waapi.headless import HeadlessLifecycle, LifecycleTimeouts  # pyright: ignore[reportMissingImports]
from .live_environment import (  # pyright: ignore[reportMissingImports]
    ENV_WWISE_FIXTURE_PROJECT,
    ENV_WWISE_SANDBOX_ROOT,
    ENV_WWISE_VERSION,
    LiveEnvironmentContract,
    LiveEnvironmentError,
    path_is_under,
    path_is_under_immutable_sample_source,
    path_is_under_org_fixture,
    path_overlaps_immutable_sample_source,
    require_destructive_environment,
    require_live_environment,
)

try:  # pragma: no branch - tests exercise the unavailable-backend seam.
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - fcntl is unavailable on Windows.
    _fcntl = None

try:  # pragma: no branch - tests exercise the unavailable-backend seam.
    import msvcrt as _msvcrt
except ImportError:  # pragma: no cover - msvcrt is unavailable on POSIX.
    _msvcrt = None


ENV_WWISE_SANDBOX_KEEP_ON_FAILURE = "WWISE_SANDBOX_KEEP_ON_FAILURE"
ENV_WWISE_STRICT_REAL = "WWISE_STRICT_REAL"
ENV_WWISE_REAL_LAUNCH_AUDIT_PATH = "WWISE_REAL_LAUNCH_AUDIT_PATH"
DEFAULT_SANDBOX_ROOT = Path(".waapi-skill-state") / "runtime" / "wwise-waapi-sandboxes"
KEEP_ON_FAILURE_ROOT = Path(".waapi-skill-state") / "evidence" / "wwise-waapi-live-sandbox-coverage"
LOCK_FILE_NAME = ".wwise-live-sandbox.lock"
REAL_LAUNCH_AUDIT_PATH = Path(".waapi-skill-state") / "evidence" / "waapi-test-remediation" / "real-wwise-launches.jsonl"
_LOCK_REGION_BYTES = 1
_WINDOWS_LOCK_RETRY_SECONDS = 0.05
_WINDOWS_LOCK_VIOLATION = 33


class SandboxFixtureError(RuntimeError):
    """Raised when a sandbox copy would be unsafe or incomplete."""


class _PosixLiveSandboxLockBackend:
    """Blocking whole-file advisory locking through ``fcntl.flock``."""

    def __init__(self, module: Any) -> None:
        self._module = module

    def acquire(self, handle: Any) -> None:
        try:
            self._module.flock(handle.fileno(), self._module.LOCK_EX)
        except OSError as exc:
            raise SandboxFixtureError(
                "LiveSandboxLock could not acquire its POSIX fcntl.flock lock."
            ) from exc

    def release(self, handle: Any) -> None:
        try:
            self._module.flock(handle.fileno(), self._module.LOCK_UN)
        except OSError as exc:
            raise SandboxFixtureError(
                "LiveSandboxLock could not release its POSIX fcntl.flock lock."
            ) from exc


class _WindowsLiveSandboxLockBackend:
    """Blocking one-byte region locking through ``msvcrt.locking``."""

    def __init__(self, module: Any) -> None:
        self._module = module

    @staticmethod
    def _seek_lock_region(handle: Any) -> None:
        try:
            handle.seek(0, os.SEEK_SET)
        except OSError as exc:
            raise SandboxFixtureError(
                "LiveSandboxLock could not seek to its Windows lock region."
            ) from exc

    def acquire(self, handle: Any) -> None:
        while True:
            self._seek_lock_region(handle)
            try:
                self._module.locking(
                    handle.fileno(),
                    self._module.LK_NBLCK,
                    _LOCK_REGION_BYTES,
                )
            except OSError as exc:
                if _is_windows_lock_contention(exc):
                    time.sleep(_WINDOWS_LOCK_RETRY_SECONDS)
                    continue
                raise SandboxFixtureError(
                    "LiveSandboxLock could not acquire its Windows msvcrt.locking lock."
                ) from exc
            return

    def release(self, handle: Any) -> None:
        self._seek_lock_region(handle)
        try:
            self._module.locking(
                handle.fileno(),
                self._module.LK_UNLCK,
                _LOCK_REGION_BYTES,
            )
        except OSError as exc:
            raise SandboxFixtureError(
                "LiveSandboxLock could not release its Windows msvcrt.locking lock."
            ) from exc


def _is_windows_lock_contention(exc: OSError) -> bool:
    """Return whether a Windows lock error means another process owns it."""

    return exc.errno in {errno.EACCES, errno.EDEADLK} or (
        getattr(exc, "winerror", None) == _WINDOWS_LOCK_VIOLATION
    )


def _select_live_sandbox_lock_backend(platform_name: str) -> Any:
    """Select a supported backend without permitting an unlocked live run."""

    if platform_name == "posix":
        if _fcntl is None or any(
            not hasattr(_fcntl, attribute)
            for attribute in ("flock", "LOCK_EX", "LOCK_UN")
        ):
            raise SandboxFixtureError(
                "LiveSandboxLock requires fcntl.flock on macOS/Linux and will not run unlocked."
            )
        return _PosixLiveSandboxLockBackend(_fcntl)
    if platform_name == "nt":
        if _msvcrt is None or any(
            not hasattr(_msvcrt, attribute)
            for attribute in ("locking", "LK_NBLCK", "LK_UNLCK")
        ):
            raise SandboxFixtureError(
                "LiveSandboxLock requires msvcrt.locking on Windows and will not run unlocked."
            )
        return _WindowsLiveSandboxLockBackend(_msvcrt)
    raise SandboxFixtureError(
        f"LiveSandboxLock has no cross-process lock backend for os.name={platform_name!r}; "
        "it will not run unlocked."
    )


def _lock_platform_name() -> str:
    """Return the standard-library platform discriminator for lock selection."""

    return os.name


@dataclass(slots=True)
class ProjectHash:
    """Content hash proof for a project tree."""

    algorithm: str
    strategy: str
    digest: str
    file_count: int
    bytes_hashed: int


@dataclass(slots=True)
class SandboxMetadata:
    """Audit record for a sandbox copy and optional WwiseConsole launch."""

    source_path: str
    source_root: str
    sandbox_path: str
    sandbox_project_path: str
    wwise_version: str
    copy_duration_seconds: float
    source_hash: ProjectHash
    sandbox_hash: ProjectHash
    source_mtime_before: float
    source_mtime_after: float | None = None
    selected_port: int | None = None
    command: list[str] | None = None
    process_pid: int | None = None
    wine_prefix_path: str | None = None
    launch_project_path: str | None = None
    ready_duration_seconds: float | None = None
    get_info_version: dict[str, Any] | None = None
    get_info_display_name: str | None = None
    process_cleanup_result: str | None = None
    process_cleanup_details: dict[str, Any] | None = None
    keep_decision: str = "pending"
    metadata_path: str | None = None
    expected_project_identity: str | None = None
    identity_verified: bool | None = None
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"


@dataclass(slots=True)
class SandboxProject:
    """Prepared sandbox project copy and its mutable audit metadata."""

    source_project: Path
    source_root: Path
    sandbox_root: Path
    sandbox_path: Path
    sandbox_project: Path
    metadata: SandboxMetadata

    @property
    def env(self) -> dict[str, str]:
        return {
            ENV_WWISE_FIXTURE_PROJECT: str(self.sandbox_project),
            ENV_WWISE_SANDBOX_ROOT: str(self.sandbox_root),
            "WINEPREFIX": str(self.wine_prefix_path),
        }

    @property
    def wine_prefix_path(self) -> Path:
        return self.sandbox_path / ".wine-prefix"

    def write_metadata(self) -> Path:
        metadata_path = self.sandbox_path / "sandbox-metadata.json"
        self.metadata.metadata_path = str(metadata_path)
        metadata_path.write_text(self.metadata.to_json(), encoding="utf-8")
        return metadata_path


class LiveSandboxLock(AbstractContextManager["LiveSandboxLock"]):
    """Cross-process lock that serializes live sandbox launches."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / LOCK_FILE_NAME
        self._handle = None
        self._backend = None

    def __enter__(self) -> "LiveSandboxLock":
        backend = _select_live_sandbox_lock_backend(_lock_platform_name())
        self.root.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(self.path, flags, 0o600)
        try:
            handle = os.fdopen(fd, "r+b", buffering=0, closefd=True)
        except BaseException:
            os.close(fd)
            raise
        try:
            # Windows region locking requires a real byte at offset zero. Two
            # first-time entrants may both write the same sentinel byte, but
            # because neither descriptor uses append mode the file remains one
            # byte and both subsequently contend on the identical region.
            if os.fstat(handle.fileno()).st_size < _LOCK_REGION_BYTES:
                handle.seek(0, os.SEEK_SET)
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
            backend.acquire(handle)
        except BaseException:
            handle.close()
            raise
        self._handle = handle
        self._backend = backend
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._handle is None:
            return
        handle = self._handle
        backend = self._backend
        cleanup_error: BaseException | None = None
        try:
            try:
                if backend is None:
                    raise SandboxFixtureError(
                        "LiveSandboxLock lost its selected backend before release."
                    )
                backend.release(handle)
            except BaseException as release_error:
                cleanup_error = release_error
        finally:
            try:
                handle.close()
            except BaseException as close_error:
                if cleanup_error is None:
                    cleanup_error = close_error
            self._handle = None
            self._backend = None
        # Preserve an exception from the protected live operation instead of
        # masking it with a secondary unlock/close failure.
        if cleanup_error is not None and exc_type is None:
            raise cleanup_error


def prepare_sample_project_sandbox(
    env: Mapping[str, str] | None = None,
    *,
    sandbox_root: Path | None = None,
    hash_strategy: str = "full",
) -> SandboxProject:
    """Copy the configured SampleProject into a unique safe sandbox."""

    env_map = env if env is not None else os.environ
    contract = require_live_environment(env_map)
    if contract.sample_project_source is None:
        raise SandboxFixtureError("WWISE_SAMPLE_PROJECT_PATH must resolve to an immutable .wproj source")

    source_project = contract.sample_project_source.expanduser().resolve(strict=True)
    if source_project.suffix != ".wproj":
        raise SandboxFixtureError(f"SampleProject source must resolve to a .wproj file; got {source_project}")
    source_root = source_project.parent.resolve(strict=True)
    root = resolve_safe_sandbox_root(env_map, sandbox_root=sandbox_root)

    root.mkdir(parents=True, exist_ok=True)
    sandbox_path = (root / f"sample-project-{uuid.uuid4().hex}").resolve(strict=False)
    source_mtime_before = source_project.stat().st_mtime
    source_hash = hash_project(source_root, preferred_strategy=hash_strategy)

    started = time.perf_counter()
    shutil.copytree(source_root, sandbox_path, symlinks=False)
    copy_duration = time.perf_counter() - started

    sandbox_project = sandbox_path / source_project.relative_to(source_root)
    if not sandbox_project.exists():
        raise SandboxFixtureError(f"copied sandbox is missing expected project file: {sandbox_project}")
    if source_project.resolve(strict=True) == sandbox_project.resolve(strict=True):
        raise SandboxFixtureError("sandbox project resolves to immutable source path")

    sandbox_hash = hash_project(sandbox_path, preferred_strategy=hash_strategy)
    metadata = SandboxMetadata(
        source_path=str(source_project),
        source_root=str(source_root),
        sandbox_path=str(sandbox_path),
        sandbox_project_path=str(sandbox_project),
        wwise_version=contract.version,
        copy_duration_seconds=copy_duration,
        source_hash=source_hash,
        sandbox_hash=sandbox_hash,
        source_mtime_before=source_mtime_before,
        source_mtime_after=source_project.stat().st_mtime,
        expected_project_identity=source_project.stem,
    )
    sandbox = SandboxProject(
        source_project=source_project,
        source_root=source_root,
        sandbox_root=root,
        sandbox_path=sandbox_path,
        sandbox_project=sandbox_project,
        metadata=metadata,
    )
    sandbox.write_metadata()
    return sandbox


def resolve_safe_sandbox_root(
    env: Mapping[str, str] | None = None,
    *,
    sandbox_root: Path | None = None,
) -> Path:
    """Resolve and validate a sandbox root without creating any filesystem entry."""

    env_map = env if env is not None else os.environ
    contract = require_live_environment(env_map)
    if contract.sample_project_source is None:
        raise SandboxFixtureError(
            "WWISE_SAMPLE_PROJECT_PATH must resolve to an immutable .wproj source"
        )
    source_project = contract.sample_project_source.expanduser().resolve(strict=True)
    if source_project.suffix != ".wproj":
        raise SandboxFixtureError(
            f"SampleProject source must resolve to a .wproj file; got {source_project}"
        )
    root = _resolve_sandbox_root(env_map, sandbox_root)
    _reject_unsafe_root(source_project.parent.resolve(strict=True), root)
    return root


def launch_sandboxed_wwise(
    sandbox: SandboxProject,
    env: Mapping[str, str] | None = None,
    *,
    timeouts: LifecycleTimeouts | None = None,
    port: int | None = None,
    wine_prefix_path: Path | None = None,
    case_owned_root: Path | None = None,
) -> HeadlessLifecycle:
    """Launch WwiseConsole only against the sandbox copy."""

    env_map = dict(env if env is not None else os.environ)
    env_map.update(sandbox.env)
    launch_wine_prefix = sandbox.wine_prefix_path
    if wine_prefix_path is not None or case_owned_root is not None:
        launch_wine_prefix = _resolve_case_owned_wine_prefix(
            env_map,
            wine_prefix_path=wine_prefix_path,
            case_owned_root=case_owned_root,
        )
        # Sandbox-owned values win over caller environment first.  The one
        # explicit case-owned exception is then installed as the real prefix
        # passed to HeadlessLifecycle; validation never creates the prefix.
        env_map["WINEPREFIX"] = str(launch_wine_prefix)
    env_map["WWISE_LIVE"] = env_map.get("WWISE_LIVE", "1")
    env_map["WWISE_DESTRUCTIVE"] = env_map.get("WWISE_DESTRUCTIVE", "1")
    contract = require_destructive_environment(env_map)
    if contract.active_destructive_project != sandbox.sandbox_project.resolve(strict=False):
        raise SandboxFixtureError("destructive environment did not select the sandbox project")

    lifecycle = HeadlessLifecycle(
        console_path=contract.console_path,
        project_path=sandbox.sandbox_project,
        port=port,
        timeouts=timeouts or _timeouts_from_env(env_map),
        launch_env=env_map,
    )
    try:
        ready_started = time.perf_counter()
        lifecycle.run_until_ready()
        ready_duration = time.perf_counter() - ready_started
        ready_info = require_lifecycle_ready_proof(lifecycle)
        sandbox.metadata.selected_port = lifecycle.port
        sandbox.metadata.command = list(lifecycle.command)
        sandbox.metadata.process_pid = getattr(lifecycle.process, "pid", None)
        sandbox.metadata.wine_prefix_path = str(launch_wine_prefix)
        sandbox.metadata.launch_project_path = str(sandbox.sandbox_project)
        sandbox.metadata.ready_duration_seconds = ready_duration
        sandbox.metadata.get_info_version = dict(ready_info["version"])
        sandbox.metadata.get_info_display_name = _get_info_display_name(ready_info)
        sandbox.metadata.identity_verified = verify_project_identity(sandbox)
        return lifecycle
    except BaseException:
        process_pid_before_cleanup = getattr(lifecycle.process, "pid", None)
        cleanup_error: BaseException | None = None
        try:
            lifecycle.shutdown(suppress_errors=True)
        except BaseException as exc:
            # Preserve the launch/readiness failure even if best-effort cleanup
            # unexpectedly fails despite suppress_errors=True.
            cleanup_error = exc
        cleanup_report = lifecycle.cleanup_report
        sandbox.metadata.selected_port = lifecycle.port
        sandbox.metadata.command = list(lifecycle.command)
        sandbox.metadata.process_pid = (
            cleanup_report.launch_pid
            if cleanup_report is not None and cleanup_report.launch_pid is not None
            else process_pid_before_cleanup
        )
        sandbox.metadata.wine_prefix_path = str(launch_wine_prefix)
        sandbox.metadata.launch_project_path = str(sandbox.sandbox_project)
        sandbox.metadata.process_cleanup_details = asdict(cleanup_report) if cleanup_report is not None else None
        if cleanup_error is not None:
            sandbox.metadata.process_cleanup_result = (
                f"error:{type(cleanup_error).__name__}:{cleanup_error}"
            )
        else:
            sandbox.metadata.process_cleanup_result = (
                "cleaned" if cleanup_report is not None and cleanup_report.is_clean else "residual-processes"
            )
        raise
    finally:
        sandbox.write_metadata()


def cleanup_sandbox(sandbox: SandboxProject, *, keep: bool = False, failed: bool = False) -> Path | None:
    """Delete or preserve a sandbox copy with a final metadata record."""

    sandbox.metadata.source_mtime_after = sandbox.source_project.stat().st_mtime
    if keep or (failed and os.getenv(ENV_WWISE_SANDBOX_KEEP_ON_FAILURE) == "1"):
        destination = _preserve_sandbox(sandbox)
        sandbox.metadata.keep_decision = f"kept:{destination}"
        sandbox.write_metadata()
        return destination

    sandbox.metadata.keep_decision = "deleted"
    sandbox.write_metadata()
    shutil.rmtree(sandbox.sandbox_path, ignore_errors=False)
    return None


def shutdown_sandboxed_wwise(
    lifecycle: HeadlessLifecycle,
    sandbox: SandboxProject,
    *,
    suppress_errors: bool = True,
) -> None:
    """Shut down a sandboxed lifecycle and record the cleanup result."""

    try:
        lifecycle.shutdown(suppress_errors=suppress_errors)
    except BaseException as exc:
        sandbox.metadata.process_cleanup_result = f"error:{type(exc).__name__}:{exc}"
        sandbox.write_metadata()
        _append_strict_real_launch_audit(sandbox)
        raise
    report = lifecycle.cleanup_report
    sandbox.metadata.process_cleanup_details = asdict(report) if report is not None else None
    sandbox.metadata.process_cleanup_result = "cleaned" if report is not None and report.is_clean else "residual-processes"
    sandbox.write_metadata()
    _append_strict_real_launch_audit(sandbox)
    if report is None:
        raise SandboxFixtureError("sandboxed Wwise shutdown did not produce a cleanup report")
    if not report.is_clean:
        residual_summary = ", ".join(f"{item.pid}:{item.command}" for item in report.residual_processes) or "process-not-exited"
        raise SandboxFixtureError(f"sandboxed Wwise cleanup left residual processes: {residual_summary}")


def _append_strict_real_launch_audit(sandbox: SandboxProject) -> None:
    if os.getenv(ENV_WWISE_STRICT_REAL) != "1":
        return
    payload = _strict_real_launch_audit_payload(sandbox)
    audit_path = _real_launch_audit_path()
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _strict_real_launch_audit_payload(sandbox: SandboxProject) -> dict[str, Any]:
    metadata = sandbox.metadata
    missing = [
        name
        for name, value in (
            ("process_pid", metadata.process_pid),
            ("selected_port", metadata.selected_port),
            ("command", metadata.command),
            ("launch_project_path", metadata.launch_project_path),
            ("ready_duration_seconds", metadata.ready_duration_seconds),
            ("get_info_version", metadata.get_info_version),
            ("get_info_display_name", metadata.get_info_display_name),
        )
        if value in (None, [], {})
    ]
    if missing:
        raise SandboxFixtureError(f"strict real launch audit missing proven field(s): {', '.join(missing)}")
    return {
        "recorded_at_unix": int(time.time()),
        "wwise_version": metadata.wwise_version,
        "pid": metadata.process_pid,
        "port": metadata.selected_port,
        "command": list(metadata.command or []),
        "wine_prefix_path": metadata.wine_prefix_path,
        "launch_project_path": metadata.launch_project_path,
        "sandbox_project_path": metadata.sandbox_project_path,
        "ready_duration_seconds": metadata.ready_duration_seconds,
        "get_info_version": metadata.get_info_version,
        "get_info_display_name": metadata.get_info_display_name,
        "cleanup_result": metadata.process_cleanup_result,
        "cleanup_details": metadata.process_cleanup_details,
        "metadata_path": metadata.metadata_path,
    }


def _real_launch_audit_path() -> Path:
    configured = os.getenv(ENV_WWISE_REAL_LAUNCH_AUDIT_PATH)
    if configured:
        return Path(configured).expanduser().resolve(strict=False)
    return (Path.cwd() / REAL_LAUNCH_AUDIT_PATH).resolve(strict=False)


def require_lifecycle_ready_proof(lifecycle: HeadlessLifecycle) -> Mapping[str, Any]:
    """Require real WwiseConsole WAAPI readiness proof from getInfo."""

    ready_result = lifecycle.ready_result
    if not isinstance(ready_result, Mapping):
        raise SandboxFixtureError(
            f"WwiseConsole readiness proof must be a getInfo mapping; got {type(ready_result).__name__}"
        )
    version = ready_result.get("version")
    if not isinstance(version, Mapping):
        raise SandboxFixtureError(f"WwiseConsole getInfo proof is missing version mapping: {ready_result!r}")
    display_name = _get_info_display_name(ready_result)
    if not display_name:
        raise SandboxFixtureError(f"WwiseConsole getInfo proof is missing displayName: {ready_result!r}")
    if lifecycle.process is None:
        raise SandboxFixtureError("WwiseConsole readiness proof requires a launched process")
    if lifecycle.port is None:
        raise SandboxFixtureError("WwiseConsole readiness proof requires a selected WAAPI port")
    if not lifecycle.command:
        raise SandboxFixtureError("WwiseConsole readiness proof requires the launch command")
    return ready_result


def _get_info_display_name(info: Mapping[str, Any]) -> str | None:
    top_level_display_name = info.get("displayName")
    if isinstance(top_level_display_name, str) and top_level_display_name:
        return top_level_display_name
    version = info.get("version")
    if isinstance(version, Mapping):
        version_display_name = version.get("displayName")
        if isinstance(version_display_name, str) and version_display_name:
            return version_display_name
    return None


def hash_project(root: Path, *, preferred_strategy: str = "full") -> ProjectHash:
    """Hash project contents deterministically; large projects may use a bounded project-file proof."""

    resolved = root.expanduser().resolve(strict=True)
    files = [path for path in sorted(resolved.rglob("*")) if path.is_file()]
    strategy = preferred_strategy
    if preferred_strategy == "bounded" or (preferred_strategy == "auto" and len(files) > 20_000):
        project_files = [path for path in files if path.suffix == ".wproj"]
        files = project_files or files[:1_000]
        strategy = "bounded-wproj-files" if project_files else "bounded-first-1000-files"

    digest = hashlib.sha256()
    bytes_hashed = 0
    for path in files:
        relative = path.relative_to(resolved).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        data = path.read_bytes()
        bytes_hashed += len(data)
        digest.update(data)
        digest.update(b"\0")
    return ProjectHash(
        algorithm="sha256",
        strategy=strategy,
        digest=digest.hexdigest(),
        file_count=len(files),
        bytes_hashed=bytes_hashed,
    )


def verify_project_identity(sandbox: SandboxProject) -> bool:
    """Verify the copied project still looks like the expected source project when possible."""

    expected = sandbox.metadata.expected_project_identity
    if expected is None:
        sandbox.metadata.notes.append("identity verification skipped: no expected project identity")
        return False
    matches = sandbox.sandbox_project.stem == expected and sandbox.sandbox_project.exists()
    if not matches:
        sandbox.metadata.notes.append(
            f"identity mismatch: expected {expected!r}, got {sandbox.sandbox_project.stem!r}"
        )
    return matches


def _resolve_sandbox_root(env: Mapping[str, str], explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve(strict=False)
    configured = env.get(ENV_WWISE_SANDBOX_ROOT)
    if configured:
        return Path(configured).expanduser().resolve(strict=False)
    try:
        return (Path.cwd() / DEFAULT_SANDBOX_ROOT).resolve(strict=False)
    except OSError:
        return Path(tempfile.gettempdir()) / "wwise-waapi-sandboxes"


def _reject_unsafe_root(source_root: Path, sandbox_root: Path) -> None:
    source = source_root.expanduser().resolve(strict=True)
    sandbox = sandbox_root.expanduser().resolve(strict=False)
    if path_is_under_org_fixture(sandbox):
        raise SandboxFixtureError("sandbox root must not be inside immutable tests/_org fixture sources")
    if path_overlaps_immutable_sample_source(sandbox):
        raise SandboxFixtureError("sandbox root must not overlap immutable installed SampleProject sources")
    if source == sandbox:
        raise SandboxFixtureError("sandbox root must not be the SampleProject source root")
    if path_is_under(sandbox, source):
        raise SandboxFixtureError("sandbox root must not be inside the SampleProject source root")
    if path_is_under(source, sandbox):
        raise SandboxFixtureError("sandbox root must not contain the immutable SampleProject source")


def _timeouts_from_env(env: Mapping[str, str]) -> LifecycleTimeouts:
    return LifecycleTimeouts(
        startup=float(env.get("WWISE_STARTUP_TIMEOUT", "10")),
        readiness=float(env.get("WWISE_READINESS_TIMEOUT", "60")),
        probe=float(env.get("WWISE_PROBE_TIMEOUT", "5")),
        shutdown=float(env.get("WWISE_SHUTDOWN_TIMEOUT", "10")),
    )


def _resolve_case_owned_wine_prefix(
    env: Mapping[str, str],
    *,
    wine_prefix_path: Path | None,
    case_owned_root: Path | None,
) -> Path:
    """Validate one fresh Wine prefix under a real case-owned HOME/root."""

    if wine_prefix_path is None or case_owned_root is None:
        raise SandboxFixtureError(
            "wine_prefix_path and case_owned_root must be provided together"
        )

    root = Path(case_owned_root)
    if not root.is_absolute():
        raise SandboxFixtureError("case_owned_root must be an absolute path")
    if root.is_symlink() or not root.is_dir():
        raise SandboxFixtureError(
            f"case_owned_root must be an existing real directory: {root}"
        )
    root = root.resolve(strict=True)

    home_text = env.get("HOME")
    if not isinstance(home_text, str) or not home_text:
        raise SandboxFixtureError(
            "HOME must name an existing real directory for a case-owned Wine prefix"
        )
    home = Path(home_text)
    if not home.is_absolute():
        raise SandboxFixtureError("HOME must be an absolute path")
    if home.is_symlink() or not home.is_dir():
        raise SandboxFixtureError(
            f"HOME must be an existing real directory: {home}"
        )
    home = home.resolve(strict=True)
    if root not in home.parents:
        raise SandboxFixtureError(
            f"HOME must be strictly under case_owned_root: {home} outside {root}"
        )

    prefix = Path(wine_prefix_path)
    if not prefix.is_absolute():
        raise SandboxFixtureError("wine_prefix_path must be an absolute path")
    if os.path.lexists(prefix):
        kind = "symlink" if prefix.is_symlink() else "existing path"
        raise SandboxFixtureError(
            f"wine_prefix_path must not already exist ({kind}): {prefix}"
        )
    prefix = Path(os.path.abspath(os.path.normpath(str(prefix))))
    try:
        relative_prefix = prefix.relative_to(home)
    except ValueError as exc:
        raise SandboxFixtureError(
            f"wine_prefix_path must be strictly under HOME: {prefix} outside {home}"
        ) from exc
    if not relative_prefix.parts:
        raise SandboxFixtureError("wine_prefix_path must be strictly under HOME")
    current = home
    for component in relative_prefix.parts[:-1]:
        current /= component
        if not os.path.lexists(current):
            continue
        if current.is_symlink() or not current.is_dir():
            raise SandboxFixtureError(
                "wine_prefix_path contains a non-directory or symlink parent: "
                f"{current}"
            )
    prefix = prefix.resolve(strict=False)
    if home not in prefix.parents:
        raise SandboxFixtureError(
            f"wine_prefix_path must be strictly under HOME: {prefix} outside {home}"
        )
    if root not in prefix.parents:
        raise SandboxFixtureError(
            f"wine_prefix_path must be strictly under case_owned_root: {prefix} outside {root}"
        )
    return prefix


def _preserve_sandbox(sandbox: SandboxProject) -> Path:
    keep_root = (Path.cwd() / KEEP_ON_FAILURE_ROOT).resolve(strict=False)
    keep_root.mkdir(parents=True, exist_ok=True)
    destination = keep_root / sandbox.sandbox_path.name
    if sandbox.sandbox_path.resolve(strict=False) != destination.resolve(strict=False):
        if destination.exists():
            shutil.rmtree(destination)
        shutil.move(str(sandbox.sandbox_path), str(destination))
        sandbox.sandbox_path = destination
        sandbox.sandbox_project = destination / sandbox.sandbox_project.name
        sandbox.metadata.sandbox_path = str(destination)
        sandbox.metadata.sandbox_project_path = str(sandbox.sandbox_project)
    return destination


__all__ = [
    "DEFAULT_SANDBOX_ROOT",
    "ENV_WWISE_REAL_LAUNCH_AUDIT_PATH",
    "ENV_WWISE_SANDBOX_KEEP_ON_FAILURE",
    "ENV_WWISE_STRICT_REAL",
    "KEEP_ON_FAILURE_ROOT",
    "REAL_LAUNCH_AUDIT_PATH",
    "LiveSandboxLock",
    "ProjectHash",
    "SandboxFixtureError",
    "SandboxMetadata",
    "SandboxProject",
    "cleanup_sandbox",
    "hash_project",
    "launch_sandboxed_wwise",
    "prepare_sample_project_sandbox",
    "require_lifecycle_ready_proof",
    "resolve_safe_sandbox_root",
    "shutdown_sandboxed_wwise",
    "verify_project_identity",
]
