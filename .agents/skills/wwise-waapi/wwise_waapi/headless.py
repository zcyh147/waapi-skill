"""Bounded headless WwiseConsole lifecycle management."""

from __future__ import annotations

import os
import platform
import queue
import signal
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol, TextIO


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
DEFAULT_KILL_TIMEOUT = 3.0


class HeadlessLifecycleError(RuntimeError):
    """Base error for WwiseConsole lifecycle failures."""


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


def find_free_port(host: str = DEFAULT_HOST) -> int:
    """Ask the OS for an available TCP port."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def assert_port_free(host: str, port: int) -> None:
    """Fail fast when a caller-supplied WAAPI port is occupied."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError as exc:
            raise PortUnavailable(f"WAAPI port {host}:{port} is not available") from exc


def _run_with_timeout(
    func: Callable[[], Any],
    timeout: float,
    error: type[HeadlessLifecycleError],
    message: str,
    late_result_cleanup: Callable[[Any], None] | None = None,
) -> Any:
    result_queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

    def target() -> None:
        try:
            result_queue.put(("result", func()))
        except BaseException as exc:  # pragma: no cover - re-raised in caller thread
            result_queue.put(("error", exc))

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    try:
        kind, payload = result_queue.get(timeout=timeout)
    except queue.Empty as exc:
        if late_result_cleanup is not None:
            threading.Thread(
                target=_cleanup_late_result,
                args=(result_queue, late_result_cleanup),
                daemon=True,
            ).start()
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
    process: Any = field(init=False, default=None)
    output: ProcessOutput = field(init=False, default_factory=ProcessOutput)
    ready_result: Any = field(init=False, default=None)
    command: list[str] = field(init=False, default_factory=list)
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

        if self.process is not None and self._poll() is None:
            raise HeadlessLifecycleError("WwiseConsole process is already running")

        resolved_path = self.path_resolver.require_executable(self.console_path)
        selected_port = self.port or find_free_port(self.host)
        assert_port_free(self.host, selected_port)
        self.port = selected_port
        self.console_path = resolved_path
        project_args = [str(self.project_path)] if self.project_path is not None else []
        self.command = [str(resolved_path), "waapi-server", *project_args, "--wamp-port", str(selected_port), *self.command_extra_args]

        def start_process() -> Any:
            kwargs: dict[str, Any] = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
                "bufsize": 1,
            }
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
        except BaseException:
            self.shutdown(suppress_errors=True)
            raise

        self._drainer.start(getattr(self.process, "stdout", None), "stdout")
        self._drainer.start(getattr(self.process, "stderr", None), "stderr")

    def wait_ready(self) -> Any:
        """Probe WAAPI by calling ak.wwise.waapi.getFunctions until ready."""

        if self.process is None:
            raise HeadlessLifecycleError("Cannot probe readiness before launch")

        deadline = time.monotonic() + self.timeouts.readiness
        last_error: BaseException | None = None
        while time.monotonic() < deadline:
            returncode = self._poll()
            if returncode is not None:
                raise EarlyProcessExit(
                    f"WwiseConsole exited with {returncode} before WAAPI readiness\n{self.output.summary()}"
                )
            try:
                self.ready_result = self._probe_once()
                return self.ready_result
            except BaseException as exc:
                last_error = exc
                time.sleep(min(self.timeouts.probe_interval, max(0.0, deadline - time.monotonic())))

        self.shutdown(suppress_errors=True)
        detail = f"; last error: {last_error}" if last_error else ""
        raise ReadinessTimeout(f"WAAPI readiness exceeded {self.timeouts.readiness:.2f}s{detail}")

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
        try:
            if self._poll() is None:
                self._terminate(process)
                try:
                    process.wait(timeout=self.timeouts.shutdown)
                    completed = True
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
            self._drainer.join()
            if completed or self._poll() is not None:
                self.process = None

    def close(self) -> None:
        self.shutdown()

    def __enter__(self) -> HeadlessLifecycle:
        self.run_until_ready()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.shutdown(suppress_errors=True)

    def _probe_once(self) -> Any:
        def probe() -> Any:
            client = self.waapi_client_factory(self.waapi_url)
            try:
                return client.call("ak.wwise.waapi.getFunctions")
            finally:
                client.disconnect()

        return _run_with_timeout(
            probe,
            self.timeouts.probe,
            ReadinessTimeout,
            f"Single WAAPI probe exceeded {self.timeouts.probe:.2f}s",
        )

    def _poll(self) -> int | None:
        if self.process is None:
            return None
        poll = getattr(self.process, "poll", None)
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


__all__ = [
    "DEFAULT_HOST",
    "EarlyProcessExit",
    "HeadlessLifecycle",
    "HeadlessLifecycleError",
    "LifecycleTimeouts",
    "MACOS_WWISE_CONSOLE",
    "PortUnavailable",
    "ProcessOutput",
    "ReadinessTimeout",
    "ShutdownTimeout",
    "StartupTimeout",
    "WINDOWS_WWISE_CONSOLE_SUFFIX",
    "WaapiClientProtocol",
    "WwiseConsoleNotExecutable",
    "WwiseConsoleNotFound",
    "WwiseConsolePathResolver",
    "assert_port_free",
    "find_free_port",
]
