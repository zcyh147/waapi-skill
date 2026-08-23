"""Bounded headless WwiseConsole lifecycle management."""

from __future__ import annotations

import os
import platform
import queue
import secrets
import signal
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol, TextIO

from .filesystem_security import path_is_link_or_reparse  # pyright: ignore[reportMissingImports]
from .platform_paths import build_wwise_console_command  # pyright: ignore[reportMissingImports]


MACOS_WWISE_CONSOLE = Path(
    "/Applications/Audiokinetic/Wwise2022.1.19.8584/Wwise.app/Contents/Tools/WwiseConsole.sh"
)
WINDOWS_WWISE_CONSOLE_SUFFIX = Path("Authoring") / "x64" / "Release" / "bin" / "WwiseConsole.exe"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_STARTUP_TIMEOUT = 10.0
DEFAULT_READINESS_TIMEOUT = 60.0
DEFAULT_PROBE_INTERVAL = 0.25
DEFAULT_PROBE_TIMEOUT = 5.0
DEFAULT_SHUTDOWN_TIMEOUT = 10.0
DEFAULT_KILL_TIMEOUT = 10.0
AUTO_WAAPI_PORT_FIRST = 30000
AUTO_WAAPI_PORT_LAST = 32767
WWISE_SERVER_BIND_HOST = "0.0.0.0"


class HeadlessLifecycleError(RuntimeError):
    """Base error for WwiseConsole lifecycle failures."""

    def __init__(self, message: str = "", diagnostics: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics or {}


class WwiseConsoleNotFound(HeadlessLifecycleError):
    """Raised when no WwiseConsole executable can be resolved."""


class WwiseConsoleNotExecutable(HeadlessLifecycleError):
    """Raised when the resolved WwiseConsole path is not executable."""


class PortUnavailable(HeadlessLifecycleError):
    """Raised when the selected WAAPI port is already occupied."""


class StartupTimeout(HeadlessLifecycleError):
    """Raised when process startup does not return within the hard timeout."""


class ReadinessTimeout(HeadlessLifecycleError):
    """Raised when WAAPI readiness probing times out."""


class EarlyProcessExit(HeadlessLifecycleError):
    """Raised when WwiseConsole exits before WAAPI becomes ready."""


class ShutdownTimeout(HeadlessLifecycleError):
    """Raised when graceful and forced shutdown both exceed their timeouts."""


@dataclass(slots=True, frozen=True)
class ResidualProcess:
    """Residual process still owned by a launched Wine prefix."""

    pid: int
    command: str


@dataclass(slots=True)
class CleanupReport:
    """Structured cleanup result for a headless lifecycle shutdown."""

    launch_pid: int | None
    wine_prefix: str | None
    process_exited: bool
    detached_cleanup_pids: list[int] = field(default_factory=list)
    wineserver_commands: list[list[str]] = field(default_factory=list)
    residual_processes: list[ResidualProcess] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return self.process_exited and not self.residual_processes


class WaapiClientProtocol(Protocol):
    """Small WAAPI client surface needed by the lifecycle gate."""

    def call(self, uri: str, *args: Any, **kwargs: Any) -> Any:
        """Call a WAAPI URI."""

    def disconnect(self) -> None:
        """Disconnect the eager WAAPI client."""


WaapiClientFactory = Callable[[str], WaapiClientProtocol]
ProcessFactory = Callable[..., Any]


@dataclass(slots=True, frozen=True)
class WwiseConsolePathResolver:
    """Resolve platform-aware WwiseConsole paths without shell interpolation."""

    env: dict[str, str] | None = None
    system_name: str | None = None
    macos_default: Path = MACOS_WWISE_CONSOLE

    def resolve(self, explicit_path: Path | str | None = None) -> Path:
        if explicit_path is not None:
            return Path(explicit_path).expanduser()

        env = self.env if self.env is not None else os.environ
        system_name = self.system_name or platform.system()

        env_path = env.get("WWISE_CONSOLE") or env.get("WWISECONSOLE")
        if env_path:
            return Path(env_path).expanduser()

        if system_name == "Windows":
            root = env.get("WWISEROOT")
            if root:
                return Path(root) / WINDOWS_WWISE_CONSOLE_SUFFIX
        return self.macos_default

    def require_executable(self, explicit_path: Path | str | None = None) -> Path:
        path = self.resolve(explicit_path)
        if not path.exists():
            raise WwiseConsoleNotFound(f"WwiseConsole not found: {path}")
        if not path.is_file() or not os.access(path, os.X_OK):
            raise WwiseConsoleNotExecutable(f"WwiseConsole is not executable: {path}")
        return path


@dataclass(slots=True, frozen=True)
class LifecycleTimeouts:
    """Bounded timeouts for startup, readiness probes, and shutdown."""

    startup: float = DEFAULT_STARTUP_TIMEOUT
    readiness: float = DEFAULT_READINESS_TIMEOUT
    probe: float = DEFAULT_PROBE_TIMEOUT
    probe_interval: float = DEFAULT_PROBE_INTERVAL
    shutdown: float = DEFAULT_SHUTDOWN_TIMEOUT
    kill: float = DEFAULT_KILL_TIMEOUT


@dataclass(slots=True)
class ProcessOutput:
    """Captured process output drained from pipes by background threads."""

    stdout: list[str] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)

    def append(self, stream_name: str, line: str) -> None:
        if stream_name == "stdout":
            self.stdout.append(line)
        else:
            self.stderr.append(line)

    def summary(self, max_lines: int = 20) -> str:
        stdout = "".join(self.stdout[-max_lines:]).strip()
        stderr = "".join(self.stderr[-max_lines:]).strip()
        return f"stdout={stdout!r}\nstderr={stderr!r}"

    def tail(self, stream_name: str, max_lines: int = 20) -> str:
        lines = self.stdout if stream_name == "stdout" else self.stderr
        return "".join(lines[-max_lines:]).strip()


def _environment_summary(env: dict[str, str] | None = None) -> dict[str, Any]:
    source = env if env is not None else os.environ
    keys = ("WWISE_CONSOLE", "WWISECONSOLE", "WWISEROOT", "WWISE_LIVE", "WWISE_DESTRUCTIVE", "WINEPREFIX")
    summary: dict[str, Any] = {key: source.get(key) for key in keys if key in source}
    summary["PATH_present"] = bool(source.get("PATH"))
    return summary


def _exception_summary(exc: BaseException | None) -> dict[str, str] | None:
    if exc is None:
        return None
    return {"type": type(exc).__name__, "message": str(exc)}


class PipeDrainer:
    """Continuously drain process pipes so WwiseConsole cannot block on output."""

    def __init__(self, output: ProcessOutput) -> None:
        self.output = output
        self._threads: list[threading.Thread] = []

    def start(self, stream: TextIO | None, stream_name: str) -> None:
        if stream is None:
            return
        thread = threading.Thread(target=self._drain, args=(stream, stream_name), daemon=True)
        thread.start()
        self._threads.append(thread)

    def join(self, timeout: float = 0.2) -> None:
        deadline = time.monotonic() + timeout
        for thread in self._threads:
            remaining = max(0.0, deadline - time.monotonic())
            thread.join(remaining)

    def _drain(self, stream: TextIO, stream_name: str) -> None:
        try:
            for line in iter(stream.readline, ""):
                if line == "":
                    break
                self.output.append(stream_name, line)
        finally:
            try:
                stream.close()
            except OSError:
                pass


def default_waapi_client_factory(url: str) -> WaapiClientProtocol:
    """Create a waapi-client instance; guarded by caller-side probe timeout."""

    from waapi import WaapiClient  # type: ignore[import-not-found]

    return WaapiClient(url=url)


def _default_process_factory(command: list[str], **kwargs: Any) -> subprocess.Popen[str]:
    return subprocess.Popen(command, **kwargs)


def _require_explicit_launch_cwd(value: Path) -> Path:
    """Resolve one real launch cwd without accepting a filesystem alias."""

    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        raise HeadlessLifecycleError(
            f"WwiseConsole launch_cwd_path must be absolute: {candidate}"
        )
    if any(component in {".", ".."} for component in candidate.parts[1:]):
        raise HeadlessLifecycleError(
            f"WwiseConsole launch_cwd_path must be normalized: {candidate}"
        )
    current = Path(candidate.anchor)
    chain = [current]
    for component in candidate.parts[1:]:
        current = current / component
        chain.append(current)
    leaf_metadata: Any | None = None
    for current in chain:
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise HeadlessLifecycleError(
                f"WwiseConsole launch_cwd_path does not exist: {candidate}"
            ) from exc
        if path_is_link_or_reparse(current, metadata=metadata):
            raise HeadlessLifecycleError(
                "WwiseConsole launch_cwd_path contains a symlink, junction, or "
                f"reparse point: {current}"
            )
        leaf_metadata = metadata
    if leaf_metadata is None or not candidate.is_dir():
        raise HeadlessLifecycleError(
            f"WwiseConsole launch_cwd_path is not a directory: {candidate}"
        )
    try:
        return candidate.resolve(strict=True)
    except OSError as exc:
        raise HeadlessLifecycleError(
            f"WwiseConsole launch_cwd_path cannot be resolved: {candidate}"
        ) from exc


def find_free_port(host: str = DEFAULT_HOST) -> int:
    """Select an available Wwise server port outside common ephemeral ranges."""

    pool_size = AUTO_WAAPI_PORT_LAST - AUTO_WAAPI_PORT_FIRST + 1
    start_offset = secrets.randbelow(pool_size)
    for offset in range(pool_size):
        candidate = AUTO_WAAPI_PORT_FIRST + ((start_offset + offset) % pool_size)
        try:
            assert_port_free(host, candidate)
        except PortUnavailable:
            continue
        return candidate
    raise PortUnavailable(
        f"No Wwise WAAPI port is available in {AUTO_WAAPI_PORT_FIRST}..{AUTO_WAAPI_PORT_LAST}"
    )


def _tcp_endpoint_accepting(host: str, port: int | None, *, timeout: float) -> bool:
    if port is None:
        return False
    try:
        with socket.create_connection((host, port), timeout=max(timeout, 0.01)):
            return True
    except OSError:
        return False


def assert_port_free(host: str, port: int) -> None:
    """Fail fast unless Wwise can bind the IPv4 port on every interface.

    ``host`` is the client connection host. WwiseConsole owns the server and
    binds more broadly, so checking only the client host can miss conflicts on
    another local interface.
    """

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        exclusive_address_use = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if os.name == "nt" and exclusive_address_use is not None:
            sock.setsockopt(socket.SOL_SOCKET, exclusive_address_use, 1)
        try:
            sock.bind((WWISE_SERVER_BIND_HOST, port))
        except OSError as exc:
            raise PortUnavailable(
                f"Wwise WAAPI server port {WWISE_SERVER_BIND_HOST}:{port} is not available "
                f"for client host {host}"
            ) from exc


def _run_with_timeout(
    func: Callable[[], Any],
    timeout: float,
    error: type[HeadlessLifecycleError],
    message: str,
    late_result_cleanup: Callable[[Any], None] | None = None,
) -> Any:
    result_queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)
    timed_out = threading.Event()

    def target() -> None:
        try:
            result = func()
            if timed_out.is_set() and late_result_cleanup is not None:
                late_result_cleanup(result)
                return
            result_queue.put(("result", result))
        except BaseException as exc:  # pragma: no cover - re-raised in caller thread
            result_queue.put(("error", exc))

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    try:
        kind, payload = result_queue.get(timeout=timeout)
    except queue.Empty as exc:
        timed_out.set()
        raise error(message) from exc
    if kind == "error":
        raise payload
    return payload


def _cleanup_late_result(result_queue: queue.Queue[tuple[str, Any]], cleanup: Callable[[Any], None]) -> None:
    kind, payload = result_queue.get()
    if kind == "result":
        cleanup(payload)


@dataclass(slots=True)
class HeadlessLifecycle:
    """Launch, probe, and clean up a headless WwiseConsole WAAPI server."""

    console_path: Path | None = None
    project_path: Path | None = None
    port: int | None = None
    host: str = DEFAULT_HOST
    timeouts: LifecycleTimeouts = field(default_factory=LifecycleTimeouts)
    path_resolver: WwiseConsolePathResolver = field(default_factory=WwiseConsolePathResolver)
    waapi_client_factory: WaapiClientFactory = default_waapi_client_factory
    process_factory: ProcessFactory = _default_process_factory
    command_extra_args: list[str] = field(default_factory=list)
    launch_env: dict[str, str] | None = None
    launch_cwd_path: Path | None = None
    process: Any = field(init=False, default=None)
    output: ProcessOutput = field(init=False, default_factory=ProcessOutput)
    ready_result: Any = field(init=False, default=None)
    command: list[str] = field(init=False, default_factory=list)
    launch_cwd: Path | None = field(init=False, default=None)
    cleanup_report: CleanupReport | None = field(init=False, default=None)
    _drainer: PipeDrainer = field(init=False)

    def __post_init__(self) -> None:
        self._drainer = PipeDrainer(self.output)

    @property
    def waapi_url(self) -> str:
        if self.port is None:
            raise HeadlessLifecycleError("WAAPI port has not been selected")
        return f"ws://{self.host}:{self.port}/waapi"

    def launch(self) -> None:
        """Start WwiseConsole waapi-server with a dynamic or caller-supplied port."""

        started_at = time.monotonic()
        if self.process is not None and self._poll() is None:
            raise HeadlessLifecycleError("WwiseConsole process is already running")

        resolved_path = self.path_resolver.require_executable(self.console_path)
        selected_port = self.port or find_free_port(self.host)
        assert_port_free(self.host, selected_port)
        self.port = selected_port
        self.console_path = resolved_path
        launch_project_path = Path(self.project_path).expanduser().resolve(strict=False) if self.project_path is not None else None
        self.launch_cwd = (
            _require_explicit_launch_cwd(self.launch_cwd_path)
            if self.launch_cwd_path is not None
            else launch_project_path.parent
            if launch_project_path is not None
            else None
        )
        self.command = build_wwise_console_command(
            resolved_path,
            selected_port,
            project_path=launch_project_path,
            extra_args=self.command_extra_args,
        )

        def start_process() -> Any:
            kwargs: dict[str, Any] = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
                "bufsize": 1,
            }
            if self.launch_cwd is not None:
                kwargs["cwd"] = str(self.launch_cwd)
            if self.launch_env is not None:
                kwargs["env"] = dict(self.launch_env)
            if os.name != "nt":
                kwargs["start_new_session"] = True
            return self.process_factory(self.command, **kwargs)

        try:
            self.process = _run_with_timeout(
                start_process,
                self.timeouts.startup,
                StartupTimeout,
                f"WwiseConsole startup exceeded {self.timeouts.startup:.2f}s",
                self._cleanup_late_process,
            )
        except StartupTimeout as exc:
            diagnostics = self._failure_diagnostics(
                phase="startup",
                timeout=self.timeouts.startup,
                duration=time.monotonic() - started_at,
                last_error=exc.__cause__,
            )
            self.shutdown(suppress_errors=True)
            raise StartupTimeout(self._failure_message("WwiseConsole startup timed out", diagnostics), diagnostics) from exc
        except BaseException:
            self.shutdown(suppress_errors=True)
            raise

        self._drainer.start(getattr(self.process, "stdout", None), "stdout")
        self._drainer.start(getattr(self.process, "stderr", None), "stderr")

    def wait_ready(self) -> Any:
        """Probe WAAPI by calling ak.wwise.core.getInfo until ready."""

        if self.process is None:
            raise HeadlessLifecycleError("Cannot probe readiness before launch")

        started_at = time.monotonic()
        deadline = time.monotonic() + self.timeouts.readiness
        last_error: BaseException | None = None
        while time.monotonic() < deadline:
            returncode = self._poll()
            if returncode is not None:
                diagnostics = self._failure_diagnostics(
                    phase="readiness",
                    timeout=self.timeouts.readiness,
                    duration=time.monotonic() - started_at,
                    last_error=last_error,
                )
                raise EarlyProcessExit(self._failure_message("WwiseConsole exited before WAAPI readiness", diagnostics), diagnostics)
            try:
                self.ready_result = self._probe_once()
                return self.ready_result
            except BaseException as exc:
                last_error = exc
                time.sleep(min(self.timeouts.probe_interval, max(0.0, deadline - time.monotonic())))

        diagnostics = self._failure_diagnostics(
            phase="readiness",
            timeout=self.timeouts.readiness,
            duration=time.monotonic() - started_at,
            last_error=last_error,
        )
        self.shutdown(suppress_errors=True)
        raise ReadinessTimeout(self._failure_message("WAAPI readiness timed out", diagnostics), diagnostics)

    def run_until_ready(self) -> Any:
        """Launch WwiseConsole and block until WAAPI is ready."""

        self.launch()
        return self.wait_ready()

    def shutdown(self, suppress_errors: bool = False) -> None:
        """Terminate WwiseConsole gracefully, then force-kill best-effort on timeout."""

        process = self.process
        if process is None:
            return
        completed = False
        detached_cleanup_pids: list[int] = []
        try:
            self._terminate(process)
            try:
                process.wait(timeout=self.timeouts.shutdown)
                completed = True
            except AttributeError:
                completed = self._poll_process(process) is not None
            except subprocess.TimeoutExpired:
                self._force_kill(process)
                try:
                    process.wait(timeout=self.timeouts.kill)
                    completed = True
                except subprocess.TimeoutExpired as exc:
                    if not suppress_errors:
                        raise ShutdownTimeout(
                            f"WwiseConsole did not exit after terminate+kill timeouts; pid={getattr(process, 'pid', 'unknown')}"
                        ) from exc
        finally:
            detached_cleanup_pids = self._cleanup_detached_waapi_servers()
            wineserver_commands = self._shutdown_owned_wineserver_prefix()
            residual_processes = self._owned_wine_processes_for_prefix()
            self._drainer.join()
            process_exited = completed or self._poll_process(process) is not None
            self.cleanup_report = CleanupReport(
                launch_pid=getattr(process, "pid", None),
                wine_prefix=str(self._owned_wine_prefix()) if self._owned_wine_prefix() is not None else None,
                process_exited=process_exited,
                detached_cleanup_pids=detached_cleanup_pids,
                wineserver_commands=wineserver_commands,
                residual_processes=residual_processes,
            )
            if process_exited:
                self.process = None

    def close(self) -> None:
        self.shutdown()

    def __enter__(self) -> HeadlessLifecycle:
        self.run_until_ready()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.shutdown(suppress_errors=True)

    def _probe_once(self) -> Any:
        if self.waapi_client_factory is default_waapi_client_factory and not _tcp_endpoint_accepting(
            self.host,
            self.port,
            timeout=min(0.1, self.timeouts.probe),
        ):
            raise ConnectionRefusedError(f"WAAPI TCP endpoint is not accepting connections at {self.host}:{self.port}")

        def probe() -> Any:
            client = self.waapi_client_factory(self.waapi_url)
            try:
                return client.call("ak.wwise.core.getInfo")
            finally:
                client.disconnect()

        return _run_with_timeout(
            probe,
            self.timeouts.probe,
            ReadinessTimeout,
            f"Single WAAPI probe exceeded {self.timeouts.probe:.2f}s",
        )
    def _failure_diagnostics(
        self,
        *,
        phase: str,
        timeout: float | None,
        duration: float | None,
        last_error: BaseException | None,
    ) -> dict[str, Any]:
        process = self.process
        exit_code = self._poll_process(process)
        if process is None:
            process_state = "not-started"
        elif exit_code is None:
            process_state = "running"
        else:
            process_state = "exited"
        return {
            "phase": phase,
            "host": self.host,
            "port": self.port,
            "waapi_url": self.waapi_url if self.port is not None else None,
            "argv": list(self.command),
            "cwd": str(self.launch_cwd) if self.launch_cwd is not None else os.getcwd(),
            "environment": _environment_summary(self.launch_env),
            "pid": getattr(process, "pid", None),
            "process_state": process_state,
            "exit_code": exit_code,
            "timeout": timeout,
            "duration": duration,
            "last_exception": _exception_summary(last_error),
            "stdout_tail": self.output.tail("stdout"),
            "stderr_tail": self.output.tail("stderr"),
        }

    def _failure_message(self, headline: str, diagnostics: dict[str, Any]) -> str:
        last_exception = diagnostics.get("last_exception") or {}
        last_exception_type = last_exception.get("type", "none") if isinstance(last_exception, dict) else "none"
        return (
            f"{headline}; port={diagnostics.get('port')}; timeout={diagnostics.get('timeout')}; "
            f"duration={diagnostics.get('duration'):.3f}s; last_exception_type={last_exception_type}; "
            f"argv={diagnostics.get('argv')!r}; cwd={diagnostics.get('cwd')!r}; "
            f"pid={diagnostics.get('pid')}; process_state={diagnostics.get('process_state')}; "
            f"exit_code={diagnostics.get('exit_code')}; stdout_tail={diagnostics.get('stdout_tail')!r}; "
            f"stderr_tail={diagnostics.get('stderr_tail')!r}"
        )

    def _poll(self) -> int | None:
        return self._poll_process(self.process)

    def _poll_process(self, process: Any) -> int | None:
        if process is None:
            return None
        poll = getattr(process, "poll", None)
        if poll is None:
            return None
        return poll()

    def _terminate(self, process: Any) -> None:
        pid = getattr(process, "pid", None)
        if pid is not None and os.name != "nt":
            try:
                os.killpg(pid, signal.SIGTERM)
                return
            except OSError:
                pass
        if pid is not None and os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T"], capture_output=True, check=False)
            return
        terminate = getattr(process, "terminate", None)
        if terminate is not None:
            terminate()

    def _cleanup_late_process(self, process: Any) -> None:
        self._terminate(process)
        try:
            process.wait(timeout=self.timeouts.shutdown)
        except (AttributeError, subprocess.TimeoutExpired):
            self._force_kill(process)

    def _force_kill(self, process: Any) -> None:
        pid = getattr(process, "pid", None)
        if pid is not None and os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
            return
        if pid is not None and os.name != "nt":
            try:
                os.killpg(pid, 9)
                return
            except OSError:
                pass
        kill = getattr(process, "kill", None)
        if kill is not None:
            kill()

    def _cleanup_detached_waapi_servers(self) -> list[int]:
        if self.port is None or os.name == "nt" or getattr(os, "kill", None) is None:
            return []
        signaled: list[int] = []
        for pid in self._detached_waapi_server_pids_for_port(self.port):
            if not self._signal_pid(pid, signal.SIGTERM):
                continue
            signaled.append(pid)
            deadline = time.monotonic() + min(0.5, max(0.0, self.timeouts.kill))
            while self._pid_exists(pid) and time.monotonic() < deadline:
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
            if self._pid_exists(pid):
                self._signal_pid(pid, 9)
        return signaled

    def _owned_wine_prefix(self) -> Path | None:
        if self.launch_env is None:
            return None
        configured = self.launch_env.get("WINEPREFIX")
        if not configured:
            return None
        return Path(configured).expanduser().resolve(strict=False)

    def _shutdown_owned_wineserver_prefix(self) -> list[list[str]]:
        prefix = self._owned_wine_prefix()
        if prefix is None or os.name == "nt":
            return []
        commands: list[list[str]] = []
        command = self._run_wineserver(prefix, "-k")
        if command is not None:
            commands.append(command)
        if self._wait_for_owned_wine_processes_to_exit(prefix):
            return commands
        command = self._run_wineserver(prefix, "-k9")
        if command is not None:
            commands.append(command)
        self._wait_for_owned_wine_processes_to_exit(prefix)
        return commands

    def _run_wineserver(self, prefix: Path, *args: str) -> list[str] | None:
        env = dict(self.launch_env or os.environ)
        env["WINEPREFIX"] = str(prefix)
        executable = self._wineserver_executable(env)
        if executable is None:
            return None
        command = [executable, *args]
        try:
            result = subprocess.run(
                command,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=max(self.timeouts.kill, 0.5),
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if getattr(result, "returncode", 1) != 0:
            return None
        return command

    def _wineserver_executable(self, env: dict[str, str]) -> str | None:
        configured = env.get("WINESERVER")
        if configured:
            candidate = Path(configured).expanduser()
            if not candidate.is_absolute():
                return None
            return self._validated_executable(candidate)
        if self.console_path is not None:
            bundled = (
                Path(self.console_path).expanduser().parent.parent
                / "SharedSupport"
                / "Wwise2019x64"
                / "bin"
                / "wineserver"
            )
            resolved = self._validated_executable(bundled)
            if resolved is not None:
                return resolved
        return "wineserver"

    def _validated_executable(self, candidate: Path) -> str | None:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            return None
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            return None
        return str(resolved)

    def _wait_for_owned_wine_processes_to_exit(self, prefix: Path) -> bool:
        deadline = time.monotonic() + max(self.timeouts.kill, 0.5)
        while True:
            if not self._owned_wine_processes_for_prefix(prefix):
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.05, remaining))

    def _owned_wine_processes_for_prefix(self, prefix: Path | None = None) -> list[ResidualProcess]:
        owned_prefix = prefix or self._owned_wine_prefix()
        if owned_prefix is None or os.name == "nt":
            return []
        prefix_text = str(owned_prefix)
        current_pid = os.getpid() if getattr(os, "getpid", None) is not None else None
        residuals: list[ResidualProcess] = []
        for pid, command_line in self._process_rows(include_env=True):
            if current_pid is not None and pid == current_pid:
                continue
            if self._is_owned_wine_process_command(command_line, prefix_text):
                residuals.append(ResidualProcess(pid=pid, command=command_line))
        return residuals

    def _process_rows(self, *, include_env: bool) -> list[tuple[int, str]]:
        commands: list[list[str]] = []
        if include_env:
            commands.append(["ps", "eww", "-axo", "pid=,command="])
        commands.append(["ps", "-axo", "pid=,command="])
        for command in commands:
            try:
                result = subprocess.run(command, capture_output=True, text=True, check=False)
            except (OSError, subprocess.SubprocessError):
                continue
            if getattr(result, "returncode", 1) != 0:
                continue
            rows: list[tuple[int, str]] = []
            for line in (getattr(result, "stdout", "") or "").splitlines():
                pid_text, separator, command_line = line.strip().partition(" ")
                if not separator:
                    continue
                try:
                    pid = int(pid_text)
                except ValueError:
                    continue
                rows.append((pid, command_line))
            if rows:
                return rows
        return []

    def _is_owned_wine_process_command(self, command_line: str, prefix_text: str) -> bool:
        lowered = command_line.lower()
        if prefix_text not in command_line and f"WINEPREFIX={prefix_text}" not in command_line:
            return False
        return self._is_wine_process_marker(lowered)

    def _is_wine_process_marker(self, lowered_command: str) -> bool:
        markers = (
            "wineserver",
            "wine64-preloader",
            "winedevice.exe",
            "winedevice",
            "wwiseconsole.exe",
            "wine-preloader",
        )
        return any(marker in lowered_command for marker in markers)
    def _detached_waapi_server_pids_for_port(self, port: int) -> list[int]:
        try:
            result = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, check=False)
        except (OSError, subprocess.SubprocessError):
            return []
        if getattr(result, "returncode", 1) != 0:
            return []

        current_pid = os.getpid() if getattr(os, "getpid", None) is not None else None
        pids: list[int] = []
        for line in (getattr(result, "stdout", "") or "").splitlines():
            pid_text, separator, command_line = line.strip().partition(" ")
            if not separator:
                continue
            try:
                pid = int(pid_text)
            except ValueError:
                continue
            if current_pid is not None and pid == current_pid:
                continue
            if self._is_waapi_server_command_for_port(command_line, port):
                pids.append(pid)
        return pids

    def _is_waapi_server_command_for_port(self, command_line: str, port: int) -> bool:
        tokens = command_line.split()
        if "waapi-server" not in tokens:
            return False
        if not any("wwiseconsole" in token.lower() for token in tokens):
            return False

        port_text = str(port)
        for index, token in enumerate(tokens):
            if token == "--wamp-port" and index + 1 < len(tokens) and tokens[index + 1] == port_text:
                return True
            if token == f"--wamp-port={port_text}":
                return True
        return False

    def _signal_pid(self, pid: int, sig: int) -> bool:
        kill = getattr(os, "kill", None)
        if kill is None:
            return False
        try:
            kill(pid, sig)
            return True
        except ProcessLookupError:
            return False
        except OSError:
            return False

    def _pid_exists(self, pid: int) -> bool:
        kill = getattr(os, "kill", None)
        if kill is None:
            return False
        try:
            kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False


def emergency_cleanup_wwise_processes(prefix: Path | str | None = None, *, timeout: float = DEFAULT_KILL_TIMEOUT) -> CleanupReport:
    """Best-effort machine-protection cleanup for residual Wwise/Wine processes.

    This helper is intentionally separate from test success semantics. Callers may use
    it after failures to protect the local machine, but they must not treat its success
    as evidence that an individual test cleaned up correctly.
    """

    lifecycle = HeadlessLifecycle(
        timeouts=LifecycleTimeouts(shutdown=timeout, kill=timeout),
        launch_env={"WINEPREFIX": str(Path(prefix).expanduser().resolve(strict=False))} if prefix is not None else None,
    )
    if os.name == "nt":
        return CleanupReport(launch_pid=None, wine_prefix=None, process_exited=True)

    rows = lifecycle._process_rows(include_env=True)
    scoped_prefix = lifecycle._owned_wine_prefix()
    targets: list[ResidualProcess] = []
    for pid, command_line in rows:
        lowered = command_line.lower()
        if scoped_prefix is not None:
            if lifecycle._is_owned_wine_process_command(command_line, str(scoped_prefix)):
                targets.append(ResidualProcess(pid=pid, command=command_line))
            continue
        if lifecycle._is_wine_process_marker(lowered):
            targets.append(ResidualProcess(pid=pid, command=command_line))

    terminated: list[int] = []
    for target in targets:
        if lifecycle._signal_pid(target.pid, signal.SIGTERM):
            terminated.append(target.pid)
    deadline = time.monotonic() + max(timeout, 0.5)
    while any(lifecycle._pid_exists(pid) for pid in terminated) and time.monotonic() < deadline:
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
    for pid in terminated:
        if lifecycle._pid_exists(pid):
            lifecycle._signal_pid(pid, 9)

    wineserver_commands = lifecycle._shutdown_owned_wineserver_prefix()
    residual_processes = lifecycle._owned_wine_processes_for_prefix(scoped_prefix) if scoped_prefix is not None else [
        ResidualProcess(pid=pid, command=command_line)
        for pid, command_line in lifecycle._process_rows(include_env=True)
        if lifecycle._is_wine_process_marker(command_line.lower())
    ]
    return CleanupReport(
        launch_pid=None,
        wine_prefix=str(scoped_prefix) if scoped_prefix is not None else None,
        process_exited=True,
        detached_cleanup_pids=terminated,
        wineserver_commands=wineserver_commands,
        residual_processes=residual_processes,
    )


__all__ = [
    "CleanupReport",
    "DEFAULT_HOST",
    "EarlyProcessExit",
    "HeadlessLifecycle",
    "HeadlessLifecycleError",
    "LifecycleTimeouts",
    "MACOS_WWISE_CONSOLE",
    "PortUnavailable",
    "ProcessOutput",
    "ReadinessTimeout",
    "ResidualProcess",
    "ShutdownTimeout",
    "StartupTimeout",
    "WINDOWS_WWISE_CONSOLE_SUFFIX",
    "WaapiClientProtocol",
    "WwiseConsoleNotExecutable",
    "WwiseConsoleNotFound",
    "WwiseConsolePathResolver",
    "assert_port_free",
    "emergency_cleanup_wwise_processes",
    "find_free_port",
]
