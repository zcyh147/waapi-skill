from __future__ import annotations

import io
import socket
import subprocess
import sys
import time
import types
from pathlib import Path
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.headless import (  # pyright: ignore[reportMissingImports]
    EarlyProcessExit,
    HeadlessLifecycle,
    HeadlessLifecycleError,
    LifecycleTimeouts,
    PipeDrainer,
    PortUnavailable,
    ProcessOutput,
    ReadinessTimeout,
    ShutdownTimeout,
    StartupTimeout,
    WwiseConsoleNotExecutable,
    WwiseConsoleNotFound,
    WwiseConsolePathResolver,
    assert_port_free,
    default_waapi_client_factory,
)
import wwise_waapi.headless as headless_module  # pyright: ignore[reportMissingImports]


class FakeProcess:
    def __init__(self, returncode: int | None = None, wait_timeouts: int = 0) -> None:
        self.returncode = returncode
        self.pid = 999999
        self.stdout = io.StringIO("stdout line\n")
        self.stderr = io.StringIO("stderr line\n")
        self.terminated = False
        self.killed = False
        self.wait_timeouts = wait_timeouts

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.wait_timeouts > 0:
            self.wait_timeouts -= 1
            raise subprocess.TimeoutExpired("fake", timeout or 0.0)
        self.returncode = 0 if self.returncode is None else self.returncode
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class FakeClient:
    def __init__(self, calls: list[str], result: Any = None) -> None:
        self.calls = calls
        self.result = result if result is not None else {"version": {"displayName": "fake Wwise"}}
        self.disconnected = False

    def call(self, uri: str, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(uri)
        return self.result

    def disconnect(self) -> None:
        self.disconnected = True


def make_executable(tmp_path: Path, name: str = "Wwise Console.sh") -> Path:
    path = tmp_path / name
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_resolver_uses_macos_default_path() -> None:
    resolver = WwiseConsolePathResolver(env={}, system_name="Darwin")
    assert str(resolver.resolve()).endswith("WwiseConsole.sh")
    assert "Wwise2022.1.19.8584" in str(resolver.resolve())


def test_resolver_uses_windows_wwiseroot_strategy() -> None:
    resolver = WwiseConsolePathResolver(env={"WWISEROOT": "C:/Program Files/Audiokinetic/Wwise 2022.1"}, system_name="Windows")
    assert resolver.resolve() == Path("C:/Program Files/Audiokinetic/Wwise 2022.1") / "Authoring" / "x64" / "Release" / "bin" / "WwiseConsole.exe"


def test_windows_resolver_without_wwiseroot_falls_back_to_macos_default() -> None:
    resolver = WwiseConsolePathResolver(env={}, system_name="Windows")
    assert resolver.resolve() == resolver.macos_default


def test_resolver_prefers_explicit_wwise_console_env_vars(tmp_path: Path) -> None:
    wwise_console = make_executable(tmp_path, "From WWISE_CONSOLE.sh")
    legacy_console = make_executable(tmp_path, "From WWISECONSOLE.sh")

    resolver = WwiseConsolePathResolver(
        env={"WWISE_CONSOLE": str(wwise_console), "WWISECONSOLE": str(legacy_console)},
        system_name="Darwin",
    )
    assert resolver.resolve() == wwise_console
    assert resolver.require_executable() == wwise_console

    legacy_resolver = WwiseConsolePathResolver(env={"WWISECONSOLE": str(legacy_console)}, system_name="Darwin")
    assert legacy_resolver.resolve() == legacy_console


def test_missing_path_and_non_executable_path_are_rejected(tmp_path: Path) -> None:
    resolver = WwiseConsolePathResolver()
    with pytest.raises(WwiseConsoleNotFound):
        resolver.require_executable(tmp_path / "missing")

    not_executable = tmp_path / "WwiseConsole.sh"
    not_executable.write_text("#!/bin/sh\n", encoding="utf-8")
    not_executable.chmod(0o644)
    with pytest.raises(WwiseConsoleNotExecutable):
        resolver.require_executable(not_executable)


def test_occupied_port_is_rejected() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
        with pytest.raises(PortUnavailable):
            assert_port_free("127.0.0.1", port)


def test_launch_uses_argument_list_dynamic_port_and_drains_output(tmp_path: Path) -> None:
    executable = make_executable(tmp_path)
    fake_process = FakeProcess()
    commands: list[list[str]] = []

    def process_factory(command: list[str], **kwargs: Any) -> FakeProcess:
        commands.append(command)
        return fake_process

    lifecycle = HeadlessLifecycle(console_path=executable, process_factory=process_factory)
    lifecycle.launch()
    lifecycle._drainer.join()  # pyright: ignore[reportPrivateUsage]

    assert lifecycle.port is not None and lifecycle.port > 0
    assert commands == [[str(executable), "waapi-server", "--wamp-port", str(lifecycle.port)]]
    assert "stdout line" in "".join(lifecycle.output.stdout)
    assert "stderr line" in "".join(lifecycle.output.stderr)
    lifecycle.shutdown()
    assert fake_process.terminated is True


def test_launch_preserves_project_path_with_spaces_as_single_argument(tmp_path: Path) -> None:
    executable = make_executable(tmp_path)
    project = tmp_path / "Fixture Project" / "Fixture Project.wproj"
    project.parent.mkdir()
    project.write_text("<WwiseDocument />", encoding="utf-8")
    commands: list[list[str]] = []

    lifecycle = HeadlessLifecycle(
        console_path=executable,
        project_path=project,
        process_factory=lambda command, **kwargs: commands.append(command) or FakeProcess(),
    )
    lifecycle.launch()

    assert commands[0][0:3] == [str(executable), "waapi-server", str(project)]
    assert "--wamp-port" in commands[0]
    lifecycle.shutdown()


def test_launch_on_windows_omits_posix_session_kwarg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    executable = make_executable(tmp_path)
    original_os = headless_module.os
    seen_kwargs: list[dict[str, Any]] = []

    def process_factory(command: list[str], **kwargs: Any) -> FakeProcess:
        seen_kwargs.append(kwargs)
        return FakeProcess()

    monkeypatch.setattr(headless_module.subprocess, "run", lambda *args, **kwargs: object())
    monkeypatch.setattr(headless_module, "os", types.SimpleNamespace(name="nt", access=original_os.access, X_OK=original_os.X_OK))
    lifecycle = HeadlessLifecycle(console_path=executable, process_factory=process_factory)
    lifecycle.launch()

    assert "start_new_session" not in seen_kwargs[0]
    lifecycle.shutdown(suppress_errors=True)


def test_wait_ready_calls_get_info_before_reflection_inventory_and_disconnects(tmp_path: Path) -> None:
    executable = make_executable(tmp_path)
    calls: list[str] = []
    urls: list[str] = []

    def client_factory(url: str) -> FakeClient:
        urls.append(url)
        return FakeClient(calls)

    lifecycle = HeadlessLifecycle(
        console_path=executable,
        process_factory=lambda command, **kwargs: FakeProcess(),
        waapi_client_factory=client_factory,
    )
    lifecycle.launch()
    result = lifecycle.wait_ready()

    assert result == {"version": {"displayName": "fake Wwise"}}
    assert calls == ["ak.wwise.core.getInfo"]
    assert "ak.wwise.waapi.getFunctions" not in calls
    assert urls == [lifecycle.waapi_url]
    lifecycle.shutdown()


def test_pre_launch_errors_and_already_running_guard(tmp_path: Path) -> None:
    lifecycle = HeadlessLifecycle()
    with pytest.raises(HeadlessLifecycleError, match="port has not been selected"):
        _ = lifecycle.waapi_url
    with pytest.raises(HeadlessLifecycleError, match="before launch"):
        lifecycle.wait_ready()

    executable = make_executable(tmp_path)
    running = HeadlessLifecycle(console_path=executable, process_factory=lambda command, **kwargs: FakeProcess())
    running.launch()
    with pytest.raises(HeadlessLifecycleError, match="already running"):
        running.launch()
    running.shutdown()


def test_default_waapi_client_factory_imports_waapi_client(monkeypatch: pytest.MonkeyPatch) -> None:
    created_urls: list[str] = []

    class FakeWaapiClient:
        def __init__(self, url: str) -> None:
            created_urls.append(url)

    fake_module = types.SimpleNamespace(WaapiClient=FakeWaapiClient)
    monkeypatch.setitem(sys.modules, "waapi", fake_module)

    assert isinstance(default_waapi_client_factory("ws://127.0.0.1:1/waapi"), FakeWaapiClient)
    assert created_urls == ["ws://127.0.0.1:1/waapi"]


def test_readiness_timeout_cleans_up_process(tmp_path: Path) -> None:
    executable = make_executable(tmp_path)
    fake_process = FakeProcess()

    def failing_client_factory(url: str) -> FakeClient:
        raise OSError("not ready")

    lifecycle = HeadlessLifecycle(
        console_path=executable,
        process_factory=lambda command, **kwargs: fake_process,
        waapi_client_factory=failing_client_factory,
        timeouts=LifecycleTimeouts(readiness=0.02, probe=0.01, probe_interval=0.001),
    )
    lifecycle.launch()
    with pytest.raises(ReadinessTimeout) as exc_info:
        lifecycle.wait_ready()
    diagnostics = exc_info.value.diagnostics
    assert diagnostics["port"] == lifecycle.port
    assert diagnostics["argv"] == lifecycle.command
    assert diagnostics["cwd"]
    assert diagnostics["timeout"] == lifecycle.timeouts.readiness
    assert diagnostics["duration"] >= 0.0
    assert diagnostics["last_exception"] == {"type": "OSError", "message": "not ready"}
    assert diagnostics["stdout_tail"] == "stdout line"
    assert diagnostics["stderr_tail"] == "stderr line"
    message = str(exc_info.value)
    assert f"port={lifecycle.port}" in message
    assert "last_exception_type=OSError" in message
    assert "stdout_tail='stdout line'" in message
    assert "stderr_tail='stderr line'" in message
    assert fake_process.terminated is True
    assert lifecycle.process is None


def test_early_process_exit_reports_console_output(tmp_path: Path) -> None:
    executable = make_executable(tmp_path)
    lifecycle = HeadlessLifecycle(
        console_path=executable,
        process_factory=lambda command, **kwargs: FakeProcess(returncode=17),
        waapi_client_factory=lambda url: FakeClient([]),
    )
    lifecycle.launch()
    lifecycle._drainer.join()  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(EarlyProcessExit, match="stdout line") as exc_info:
        lifecycle.wait_ready()
    diagnostics = exc_info.value.diagnostics
    assert diagnostics["port"] == lifecycle.port
    assert diagnostics["process_state"] == "exited"
    assert diagnostics["exit_code"] == 17
    assert diagnostics["stdout_tail"] == "stdout line"
    assert diagnostics["stderr_tail"] == "stderr line"


def test_startup_timeout_cleans_up(tmp_path: Path) -> None:
    executable = make_executable(tmp_path)

    def slow_process_factory(command: list[str], **kwargs: Any) -> FakeProcess:
        time.sleep(0.05)
        return FakeProcess()

    lifecycle = HeadlessLifecycle(
        console_path=executable,
        process_factory=slow_process_factory,
        timeouts=LifecycleTimeouts(startup=0.005),
    )
    with pytest.raises(StartupTimeout) as exc_info:
        lifecycle.launch()
    diagnostics = exc_info.value.diagnostics
    assert diagnostics["port"] == lifecycle.port
    assert diagnostics["argv"] == [str(executable), "waapi-server", "--wamp-port", str(lifecycle.port)]
    assert diagnostics["cwd"]
    assert diagnostics["timeout"] == lifecycle.timeouts.startup
    assert diagnostics["duration"] >= lifecycle.timeouts.startup
    assert diagnostics["last_exception"] == {"type": "Empty", "message": ""}
    assert "PATH_present" in diagnostics["environment"]


def test_startup_timeout_cleans_up_late_created_process(tmp_path: Path) -> None:
    executable = make_executable(tmp_path)
    fake_process = FakeProcess()

    def slow_process_factory(command: list[str], **kwargs: Any) -> FakeProcess:
        time.sleep(0.02)
        return fake_process

    lifecycle = HeadlessLifecycle(
        console_path=executable,
        process_factory=slow_process_factory,
        timeouts=LifecycleTimeouts(startup=0.001, shutdown=0.001),
    )
    with pytest.raises(StartupTimeout):
        lifecycle.launch()

    deadline = time.monotonic() + 0.2
    while not fake_process.terminated and time.monotonic() < deadline:
        time.sleep(0.001)
    assert fake_process.terminated is True


def test_shutdown_timeout_raises_after_force_kill_timeout(tmp_path: Path) -> None:
    executable = make_executable(tmp_path)
    fake_process = FakeProcess(wait_timeouts=2)
    lifecycle = HeadlessLifecycle(
        console_path=executable,
        process_factory=lambda command, **kwargs: fake_process,
        timeouts=LifecycleTimeouts(shutdown=0.001, kill=0.001),
    )
    lifecycle.launch()
    with pytest.raises(ShutdownTimeout):
        lifecycle.shutdown()
    assert fake_process.terminated is True
    assert lifecycle.process is None


def test_close_alias_shuts_down_running_process(tmp_path: Path) -> None:
    executable = make_executable(tmp_path)
    fake_process = FakeProcess()
    lifecycle = HeadlessLifecycle(console_path=executable, process_factory=lambda command, **kwargs: fake_process)
    lifecycle.launch()
    lifecycle.close()
    assert fake_process.terminated is True
    assert lifecycle.process is None


def test_shutdown_clears_process_that_already_exited(tmp_path: Path) -> None:
    executable = make_executable(tmp_path)
    lifecycle = HeadlessLifecycle(console_path=executable, process_factory=lambda command, **kwargs: FakeProcess(returncode=0))
    lifecycle.launch()
    lifecycle.shutdown()
    assert lifecycle.process is None


def test_shutdown_handles_process_without_poll_or_terminate(tmp_path: Path) -> None:
    executable = make_executable(tmp_path)

    class MinimalProcess:
        stdout = None
        stderr = None

        def __init__(self) -> None:
            self.wait_calls = 0

        def wait(self, timeout: float | None = None) -> int:
            self.wait_calls += 1
            if self.wait_calls == 1:
                raise subprocess.TimeoutExpired("minimal", timeout or 0.0)
            return 0

    minimal = MinimalProcess()
    lifecycle = HeadlessLifecycle(console_path=executable, process_factory=lambda command, **kwargs: minimal)
    lifecycle.launch()
    lifecycle.shutdown(suppress_errors=True)

    assert minimal.wait_calls == 2
    assert lifecycle.process is None


def test_pipe_drainer_ignores_none_stream() -> None:
    output = ProcessOutput()
    drainer = PipeDrainer(output)
    drainer.start(None, "stdout")
    drainer.join()
    assert output.stdout == []
    assert output.stderr == []


def test_pipe_drainer_handles_empty_stream_and_close_errors() -> None:
    class CloseErrorStream(io.StringIO):
        def close(self) -> None:
            raise OSError("close failed")

    output = ProcessOutput()
    drainer = PipeDrainer(output)
    drainer.start(CloseErrorStream(""), "stderr")
    drainer.join()
    assert output.stderr == []


def test_force_kill_uses_windows_taskkill(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    executable = make_executable(tmp_path)
    fake_process = FakeProcess(wait_timeouts=1)
    commands: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> object:
        commands.append(command)
        fake_process.returncode = -9
        return object()

    monkeypatch.setattr(headless_module.subprocess, "run", fake_run)

    lifecycle = HeadlessLifecycle(
        console_path=executable,
        process_factory=lambda command, **kwargs: fake_process,
        timeouts=LifecycleTimeouts(shutdown=0.001, kill=0.001),
    )
    lifecycle.launch()
    monkeypatch.setattr(headless_module, "os", types.SimpleNamespace(name="nt"))
    lifecycle.shutdown()

    assert commands == [
        ["taskkill", "/PID", str(fake_process.pid), "/T"],
        ["taskkill", "/PID", str(fake_process.pid), "/T", "/F"],
    ]
    assert lifecycle.process is None


def test_force_kill_falls_back_to_process_kill_when_process_group_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    executable = make_executable(tmp_path)
    fake_process = FakeProcess(wait_timeouts=1)
    killpg_calls: list[tuple[int, int]] = []

    def fake_killpg(pid: int, sig: int) -> None:
        killpg_calls.append((pid, sig))
        raise OSError("no process group")

    lifecycle = HeadlessLifecycle(
        console_path=executable,
        process_factory=lambda command, **kwargs: fake_process,
        timeouts=LifecycleTimeouts(shutdown=0.001, kill=0.001),
    )
    lifecycle.launch()
    monkeypatch.setattr(headless_module, "os", types.SimpleNamespace(name="posix", killpg=fake_killpg))
    lifecycle.shutdown()

    assert killpg_calls == [(fake_process.pid, headless_module.signal.SIGTERM), (fake_process.pid, 9)]
    assert fake_process.killed is True
    assert lifecycle.process is None


def test_force_kill_falls_back_to_process_kill_without_pid(tmp_path: Path) -> None:
    executable = make_executable(tmp_path)
    fake_process = FakeProcess(wait_timeouts=1)
    del fake_process.pid

    lifecycle = HeadlessLifecycle(
        console_path=executable,
        process_factory=lambda command, **kwargs: fake_process,
        timeouts=LifecycleTimeouts(shutdown=0.001, kill=0.001),
    )
    lifecycle.launch()
    lifecycle.shutdown()

    assert fake_process.killed is True
    assert lifecycle.process is None


def test_context_manager_launches_and_suppresses_shutdown_errors(tmp_path: Path) -> None:
    executable = make_executable(tmp_path)
    calls: list[str] = []
    lifecycle = HeadlessLifecycle(
        console_path=executable,
        process_factory=lambda command, **kwargs: FakeProcess(wait_timeouts=2),
        waapi_client_factory=lambda url: FakeClient(calls),
        timeouts=LifecycleTimeouts(shutdown=0.001, kill=0.001),
    )
    with lifecycle as running:
        assert running.ready_result == {"version": {"displayName": "fake Wwise"}}
    assert calls == ["ak.wwise.core.getInfo"]
