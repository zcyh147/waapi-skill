from __future__ import annotations

import io
import os
import socket
import subprocess
import sys
import time
import types
from pathlib import Path
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.headless import (  # pyright: ignore[reportMissingImports]
    CleanupReport,
    EarlyProcessExit,
    HeadlessLifecycle,
    HeadlessLifecycleError,
    LifecycleTimeouts,
    PipeDrainer,
    PortUnavailable,
    ProcessOutput,
    ReadinessTimeout,
    ResidualProcess,
    ShutdownTimeout,
    StartupTimeout,
    WwiseConsoleNotExecutable,
    WwiseConsoleNotFound,
    WwiseConsolePathResolver,
    assert_port_free,
    default_waapi_client_factory,
    find_free_port,
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
    if headless_module.os.name == "nt":
        assert resolver.require_executable(not_executable) == not_executable
    else:
        with pytest.raises(WwiseConsoleNotExecutable):
            resolver.require_executable(not_executable)


def test_occupied_port_is_rejected() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
        with pytest.raises(PortUnavailable):
            assert_port_free("127.0.0.1", port)


def test_port_probe_uses_wildcard_server_bind_without_reuse(monkeypatch: pytest.MonkeyPatch) -> None:
    bind_calls: list[tuple[str, int]] = []
    socket_options: list[tuple[int, int, int]] = []

    class RecordingSocket:
        def __enter__(self) -> RecordingSocket:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def bind(self, address: tuple[str, int]) -> None:
            bind_calls.append(address)

        def setsockopt(self, level: int, option: int, value: int) -> None:
            socket_options.append((level, option, value))

    monkeypatch.setattr(headless_module.socket, "socket", lambda *args, **kwargs: RecordingSocket())
    monkeypatch.setattr(headless_module.os, "name", "posix")

    assert_port_free("127.0.0.1", 31337)

    assert bind_calls == [("0.0.0.0", 31337)]
    assert socket_options == []


def test_windows_port_probe_requests_exclusive_address_use(monkeypatch: pytest.MonkeyPatch) -> None:
    socket_options: list[tuple[int, int, int]] = []

    class RecordingSocket:
        def __enter__(self) -> RecordingSocket:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def bind(self, address: tuple[str, int]) -> None:
            assert address == ("0.0.0.0", 31337)

        def setsockopt(self, level: int, option: int, value: int) -> None:
            socket_options.append((level, option, value))

    exclusive_address_use = 0x100
    monkeypatch.setattr(headless_module.socket, "socket", lambda *args, **kwargs: RecordingSocket())
    monkeypatch.setattr(headless_module.socket, "SO_EXCLUSIVEADDRUSE", exclusive_address_use, raising=False)
    monkeypatch.setattr(headless_module.os, "name", "nt")

    assert_port_free("127.0.0.1", 31337)

    assert socket_options == [(socket.SOL_SOCKET, exclusive_address_use, 1)]


def test_find_free_port_scans_safe_pool_from_random_start_and_skips_conflicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempted: list[tuple[str, int]] = []

    monkeypatch.setattr(headless_module.secrets, "randbelow", lambda size: 2)

    def reject_first_two(host: str, port: int) -> None:
        attempted.append((host, port))
        if len(attempted) <= 2:
            raise PortUnavailable("occupied")

    monkeypatch.setattr(headless_module, "assert_port_free", reject_first_two)

    selected = find_free_port("127.0.0.1")

    assert selected == headless_module.AUTO_WAAPI_PORT_FIRST + 4
    assert selected != 0
    assert attempted == [
        ("127.0.0.1", headless_module.AUTO_WAAPI_PORT_FIRST + 2),
        ("127.0.0.1", headless_module.AUTO_WAAPI_PORT_FIRST + 3),
        ("127.0.0.1", headless_module.AUTO_WAAPI_PORT_FIRST + 4),
    ]


def test_find_free_port_wraps_and_raises_when_safe_pool_is_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempted: list[int] = []
    pool_size = headless_module.AUTO_WAAPI_PORT_LAST - headless_module.AUTO_WAAPI_PORT_FIRST + 1
    monkeypatch.setattr(headless_module.secrets, "randbelow", lambda size: size - 1)

    def always_occupied(host: str, port: int) -> None:
        attempted.append(port)
        raise PortUnavailable("occupied")

    monkeypatch.setattr(headless_module, "assert_port_free", always_occupied)

    with pytest.raises(PortUnavailable, match=r"30000\.\.32767"):
        find_free_port("127.0.0.1")

    assert len(attempted) == pool_size
    assert attempted[:2] == [
        headless_module.AUTO_WAAPI_PORT_LAST,
        headless_module.AUTO_WAAPI_PORT_FIRST,
    ]
    assert set(attempted) == set(
        range(headless_module.AUTO_WAAPI_PORT_FIRST, headless_module.AUTO_WAAPI_PORT_LAST + 1)
    )


def test_launch_rejects_conflicting_explicit_port_without_replacement(tmp_path: Path) -> None:
    executable = make_executable(tmp_path)
    process_calls: list[list[str]] = []

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        selected_port = int(occupied.getsockname()[1])
        lifecycle = HeadlessLifecycle(
            console_path=executable,
            port=selected_port,
            process_factory=lambda command, **kwargs: process_calls.append(command) or FakeProcess(),
        )

        with pytest.raises(PortUnavailable):
            lifecycle.launch()

    assert lifecycle.port == selected_port
    assert process_calls == []


def test_launch_uses_argument_list_dynamic_port_and_drains_output(tmp_path: Path) -> None:
    executable = make_executable(tmp_path)
    fake_process = FakeProcess()
    commands: list[list[str]] = []
    seen_kwargs: list[dict[str, Any]] = []

    def process_factory(command: list[str], **kwargs: Any) -> FakeProcess:
        commands.append(command)
        seen_kwargs.append(kwargs)
        return fake_process

    lifecycle = HeadlessLifecycle(console_path=executable, process_factory=process_factory)
    lifecycle.launch()
    lifecycle._drainer.join()  # pyright: ignore[reportPrivateUsage]

    assert lifecycle.port is not None
    assert headless_module.AUTO_WAAPI_PORT_FIRST <= lifecycle.port <= headless_module.AUTO_WAAPI_PORT_LAST
    assert commands == [
        [str(executable), "waapi-server", "--wamp-port", str(lifecycle.port), "--http-port", "0"]
    ]
    assert "cwd" not in seen_kwargs[0]
    assert "stdout line" in "".join(lifecycle.output.stdout)
    assert "stderr line" in "".join(lifecycle.output.stderr)
    lifecycle.shutdown()
    if headless_module.os.name == "nt":
        assert lifecycle.process is None
    else:
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


def test_launch_decouples_long_absolute_project_from_short_explicit_cwd(
    tmp_path: Path,
) -> None:
    executable = make_executable(tmp_path)
    launch_cwd = tmp_path / "launch-cwd"
    launch_cwd.mkdir()
    project = (
        tmp_path
        / ("long-project-parent-" + "a" * 180)
        / ("nested-" + "b" * 80)
        / "SampleProject.wproj"
    ).resolve(strict=False)
    assert len(str(project)) > 260
    commands: list[list[str]] = []
    seen_kwargs: list[dict[str, Any]] = []

    def process_factory(command: list[str], **kwargs: Any) -> FakeProcess:
        commands.append(command)
        seen_kwargs.append(kwargs)
        return FakeProcess()

    lifecycle = HeadlessLifecycle(
        console_path=executable,
        project_path=project,
        launch_cwd_path=launch_cwd,
        process_factory=process_factory,
    )
    lifecycle.launch()

    assert commands[0][2] == str(project)
    assert seen_kwargs[0]["cwd"] == str(launch_cwd.resolve(strict=True))
    assert lifecycle.launch_cwd == launch_cwd.resolve(strict=True)
    assert lifecycle.launch_cwd != project.parent
    lifecycle.shutdown()


def test_launch_rejects_missing_explicit_cwd_before_process_creation(
    tmp_path: Path,
) -> None:
    executable = make_executable(tmp_path)
    process_calls: list[list[str]] = []
    lifecycle = HeadlessLifecycle(
        console_path=executable,
        launch_cwd_path=tmp_path / "missing",
        process_factory=lambda command, **kwargs: process_calls.append(command)
        or FakeProcess(),
    )

    with pytest.raises(HeadlessLifecycleError, match="launch_cwd_path does not exist"):
        lifecycle.launch()

    assert process_calls == []


def test_launch_rejects_explicit_cwd_symlink(
    tmp_path: Path,
) -> None:
    executable = make_executable(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")
    lifecycle = HeadlessLifecycle(
        console_path=executable,
        launch_cwd_path=alias,
        process_factory=lambda command, **kwargs: FakeProcess(),
    )

    with pytest.raises(HeadlessLifecycleError, match="symlink, junction, or reparse"):
        lifecycle.launch()


def test_launch_rejects_explicit_cwd_with_junction_ancestor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executable = make_executable(tmp_path)
    junction = tmp_path / "junction"
    launch_cwd = junction / "child"
    launch_cwd.mkdir(parents=True)
    real_is_junction = getattr(Path, "is_junction", lambda _self: False)
    monkeypatch.setattr(
        Path,
        "is_junction",
        lambda self: self == junction or real_is_junction(self),
        raising=False,
    )
    lifecycle = HeadlessLifecycle(
        console_path=executable,
        launch_cwd_path=launch_cwd,
        process_factory=lambda command, **kwargs: FakeProcess(),
    )

    with pytest.raises(HeadlessLifecycleError, match="launch_cwd_path contains"):
        lifecycle.launch()


def test_launch_passes_launch_env_to_process_factory(tmp_path: Path) -> None:
    executable = make_executable(tmp_path)
    seen_kwargs: list[dict[str, Any]] = []

    def process_factory(command: list[str], **kwargs: Any) -> FakeProcess:
        seen_kwargs.append(kwargs)
        return FakeProcess()

    lifecycle = HeadlessLifecycle(
        console_path=executable,
        launch_env={"PATH": "/usr/bin", "WINEPREFIX": str(tmp_path / ".wine-prefix")},
        process_factory=process_factory,
    )
    lifecycle.launch()

    assert seen_kwargs[0]["env"]["WINEPREFIX"] == str(tmp_path / ".wine-prefix")
    lifecycle.shutdown(suppress_errors=True)


def test_project_launch_normalizes_relative_project_path_cwd_and_diagnostics(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    executable = make_executable(tmp_path)
    project = Path("Fixture Project") / "Fixture Project.wproj"
    absolute_project = (tmp_path / project).resolve(strict=False)
    absolute_project.parent.mkdir()
    absolute_project.write_text("<WwiseDocument />", encoding="utf-8")
    seen_kwargs: list[dict[str, Any]] = []

    monkeypatch.chdir(tmp_path)

    def process_factory(command: list[str], **kwargs: Any) -> FakeProcess:
        seen_kwargs.append(kwargs)
        return FakeProcess()

    def failing_client_factory(url: str) -> FakeClient:
        raise OSError("not ready")

    lifecycle = HeadlessLifecycle(
        console_path=executable,
        project_path=project,
        process_factory=process_factory,
        waapi_client_factory=failing_client_factory,
        timeouts=LifecycleTimeouts(readiness=0.02, probe=0.01, probe_interval=0.001),
    )
    lifecycle.launch()

    assert lifecycle.port is not None
    assert seen_kwargs[0]["cwd"] == str(absolute_project.parent)
    assert lifecycle.command == [
        str(executable),
        "waapi-server",
        str(absolute_project),
        "--wamp-port",
        str(lifecycle.port),
        "--http-port",
        "0",
    ]
    with pytest.raises(ReadinessTimeout) as exc_info:
        lifecycle.wait_ready()
    assert exc_info.value.diagnostics["cwd"] == str(absolute_project.parent)


def test_no_project_launch_diagnostics_use_current_process_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    executable = make_executable(tmp_path)
    seen_kwargs: list[dict[str, Any]] = []

    def process_factory(command: list[str], **kwargs: Any) -> FakeProcess:
        seen_kwargs.append(kwargs)
        return FakeProcess()

    def failing_client_factory(url: str) -> FakeClient:
        raise OSError("not ready")

    monkeypatch.chdir(tmp_path)
    lifecycle = HeadlessLifecycle(
        console_path=executable,
        process_factory=process_factory,
        waapi_client_factory=failing_client_factory,
        timeouts=LifecycleTimeouts(readiness=0.02, probe=0.01, probe_interval=0.001),
    )
    lifecycle.launch()

    assert "cwd" not in seen_kwargs[0]
    with pytest.raises(ReadinessTimeout) as exc_info:
        lifecycle.wait_ready()
    assert exc_info.value.diagnostics["cwd"] == str(Path.cwd())


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
    assert diagnostics["pid"] == fake_process.pid
    assert diagnostics["process_state"] == "running"
    assert diagnostics["exit_code"] is None
    assert diagnostics["stdout_tail"] == "stdout line"
    assert diagnostics["stderr_tail"] == "stderr line"
    message = str(exc_info.value)
    assert f"port={lifecycle.port}" in message
    assert "last_exception_type=OSError" in message
    assert "stdout_tail='stdout line'" in message
    assert "stderr_tail='stderr line'" in message
    if headless_module.os.name == "nt":
        assert lifecycle.process is None
    else:
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
    assert diagnostics["argv"] == [
        str(executable),
        "waapi-server",
        "--wamp-port",
        str(lifecycle.port),
        "--http-port",
        "0",
    ]
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
    while not (fake_process.terminated or lifecycle.process is None) and time.monotonic() < deadline:
        time.sleep(0.001)
    if headless_module.os.name == "nt":
        assert lifecycle.process is None
    else:
        assert fake_process.terminated is True or fake_process.killed is True or lifecycle.process is None


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
    if headless_module.os.name == "nt":
        assert lifecycle.process is fake_process
    else:
        assert fake_process.terminated is True
        assert lifecycle.process is None


def test_close_alias_shuts_down_running_process(tmp_path: Path) -> None:
    executable = make_executable(tmp_path)
    fake_process = FakeProcess()
    lifecycle = HeadlessLifecycle(console_path=executable, process_factory=lambda command, **kwargs: fake_process)
    lifecycle.launch()
    lifecycle.close()
    if headless_module.os.name == "nt":
        assert lifecycle.process is None
    else:
        assert fake_process.terminated is True
    assert lifecycle.process is None


def test_shutdown_clears_process_that_already_exited(tmp_path: Path) -> None:
    executable = make_executable(tmp_path)
    lifecycle = HeadlessLifecycle(console_path=executable, process_factory=lambda command, **kwargs: FakeProcess(returncode=0))
    lifecycle.launch()
    lifecycle.shutdown()
    assert lifecycle.process is None


def test_shutdown_cleans_process_group_when_wrapper_already_exited(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    executable = make_executable(tmp_path)
    fake_process = FakeProcess(returncode=0)
    killpg_calls: list[tuple[int, int]] = []

    def fake_killpg(pid: int, sig: int) -> None:
        killpg_calls.append((pid, sig))

    lifecycle = HeadlessLifecycle(console_path=executable, process_factory=lambda command, **kwargs: fake_process)
    lifecycle.launch()
    monkeypatch.setattr(headless_module, "os", types.SimpleNamespace(name="posix", killpg=fake_killpg))
    lifecycle.shutdown()

    assert killpg_calls == [(fake_process.pid, headless_module.signal.SIGTERM)]
    assert lifecycle.process is None


def test_detached_waapi_server_scan_matches_only_wwise_waapi_selected_port(monkeypatch: pytest.MonkeyPatch) -> None:
    port = 57645
    ps_output = f"""
      101 /usr/bin/python WwiseConsole.exe waapi-server --wamp-port {port}
      200 /Applications/WwiseConsole.sh waapi-server /tmp/Sample Project/SampleProject.wproj --wamp-port {port} --http-port 0
      201 /Applications/WwiseConsole.sh waapi-server /tmp/SampleProject.wproj --wamp-port 1
      202 /Applications/WwiseConsole.sh profiler-server --wamp-port {port}
      203 /usr/bin/python waapi-server --wamp-port {port}
      204 C:/WwiseConsole.exe waapi-server C:/SampleProject.wproj --wamp-port={port} --http-port=0
      205 /Applications/WwiseConsole.sh waapi-server /tmp/SampleProject.wproj --wamp-port 1 --http-port {port}
      not-a-pid /Applications/WwiseConsole.sh waapi-server --wamp-port {port}
      malformed
    """

    def fake_run(command: list[str], **kwargs: Any) -> object:
        assert command == ["ps", "-axo", "pid=,command="]
        return types.SimpleNamespace(returncode=0, stdout=ps_output)

    monkeypatch.setattr(headless_module.subprocess, "run", fake_run)
    monkeypatch.setattr(headless_module.os, "getpid", lambda: 101)

    lifecycle = HeadlessLifecycle()
    assert lifecycle._detached_waapi_server_pids_for_port(port) == [200, 204]  # pyright: ignore[reportPrivateUsage]


def test_detached_waapi_server_scan_tolerates_unavailable_ps(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_run(command: list[str], **kwargs: Any) -> object:
        raise OSError("ps unavailable")

    monkeypatch.setattr(headless_module.subprocess, "run", failing_run)

    lifecycle = HeadlessLifecycle()
    assert lifecycle._detached_waapi_server_pids_for_port(57645) == []  # pyright: ignore[reportPrivateUsage]


def test_shutdown_detached_port_fallback_terminates_only_matching_ps_rows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    if headless_module.os.name == "nt":
        pytest.skip("detached ps/killpg fallback is POSIX-only")
    executable = make_executable(tmp_path)
    port = find_free_port("127.0.0.1")
    fake_process = FakeProcess(returncode=0)
    ps_output = f"""
      200 /Applications/WwiseConsole.sh waapi-server /tmp/SampleProject.wproj --wamp-port {port} --http-port 0
      201 /Applications/WwiseConsole.sh waapi-server /tmp/SampleProject.wproj --wamp-port 1
      202 /Applications/WwiseConsole.sh profiler-server --wamp-port {port}
      203 /usr/bin/python waapi-server --wamp-port {port}
    """
    signal_calls: list[tuple[int, int]] = []

    def fake_run(command: list[str], **kwargs: Any) -> object:
        return types.SimpleNamespace(returncode=0, stdout=ps_output)

    def fake_signal_pid(self: HeadlessLifecycle, pid: int, sig: int) -> bool:
        signal_calls.append((pid, sig))
        return True

    monkeypatch.setattr(headless_module.os, "killpg", lambda pid, sig: None)
    monkeypatch.setattr(headless_module.subprocess, "run", fake_run)
    monkeypatch.setattr(HeadlessLifecycle, "_signal_pid", fake_signal_pid)
    monkeypatch.setattr(HeadlessLifecycle, "_pid_exists", lambda self, pid: True)

    lifecycle = HeadlessLifecycle(
        console_path=executable,
        port=port,
        process_factory=lambda command, **kwargs: fake_process,
        timeouts=LifecycleTimeouts(kill=0.0),
    )
    lifecycle.launch()
    lifecycle.shutdown()

    assert signal_calls == [(200, headless_module.signal.SIGTERM), (200, 9)]
    assert lifecycle.process is None


def test_shutdown_records_prefix_scoped_residual_wine_processes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    if headless_module.os.name == "nt":
        pytest.skip("Wine prefix cleanup is POSIX-only")
    executable = make_executable(tmp_path)
    fake_process = FakeProcess(returncode=0)
    prefix = (tmp_path / ".wine-prefix").resolve(strict=False)
    ps_output = f"""
      200 /usr/bin/env WINEPREFIX={prefix} wineserver
      201 /usr/bin/env WINEPREFIX=/other/prefix wineserver
    """
    seen_commands: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> object:
        seen_commands.append(command)
        if command[:1] == ["ps"]:
            return types.SimpleNamespace(returncode=0, stdout=ps_output)
        return types.SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(headless_module.subprocess, "run", fake_run)
    monkeypatch.setattr(headless_module.os, "killpg", lambda pid, sig: None)
    monkeypatch.setattr(
        HeadlessLifecycle,
        "_wait_for_owned_wine_processes_to_exit",
        lambda self, scoped_prefix: False,
    )

    lifecycle = HeadlessLifecycle(
        console_path=executable,
        launch_env={"PATH": "/usr/bin", "WINEPREFIX": str(prefix)},
        process_factory=lambda command, **kwargs: fake_process,
    )
    lifecycle.launch()
    lifecycle.shutdown(suppress_errors=True)

    assert lifecycle.cleanup_report is not None
    assert lifecycle.cleanup_report.wineserver_commands == [
        ["wineserver", "-k"],
        ["wineserver", "-k9"],
    ]
    assert lifecycle.cleanup_report.residual_processes == [ResidualProcess(pid=200, command=f"/usr/bin/env WINEPREFIX={prefix} wineserver")]


def test_wineserver_cleanup_uses_explicit_executable_and_scoped_prefix(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    wineserver = make_executable(tmp_path, "wineserver")
    prefix = tmp_path / "owned prefix"
    seen: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run(command: list[str], **kwargs: Any) -> object:
        seen.append((command, kwargs))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(headless_module.subprocess, "run", fake_run)
    lifecycle = HeadlessLifecycle(
        launch_env={
            "PATH": "/untrusted",
            "WINESERVER": str(wineserver),
            "WINEPREFIX": str(prefix),
        }
    )

    command = lifecycle._run_wineserver(prefix, "-k")  # pyright: ignore[reportPrivateUsage]

    assert command == [str(wineserver.resolve()), "-k"]
    assert seen[0][0] == command
    assert seen[0][1]["env"]["WINEPREFIX"] == str(prefix)
    assert seen[0][1]["stdout"] is subprocess.DEVNULL
    assert seen[0][1]["stderr"] is subprocess.DEVNULL


def test_wineserver_cleanup_derives_binary_from_wwise_app_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    console_root = tmp_path / "Wwise.app" / "Contents" / "Tools"
    server_root = (
        tmp_path
        / "Wwise.app"
        / "Contents"
        / "SharedSupport"
        / "Wwise2019x64"
        / "bin"
    )
    console_root.mkdir(parents=True)
    server_root.mkdir(parents=True)
    console = make_executable(console_root, "WwiseConsole.sh")
    wineserver = make_executable(server_root, "wineserver")
    prefix = tmp_path / "prefix"
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> object:
        calls.append(command)
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(headless_module.subprocess, "run", fake_run)
    lifecycle = HeadlessLifecycle(
        console_path=console,
        launch_env={"WINEPREFIX": str(prefix)},
    )

    command = lifecycle._run_wineserver(prefix, "-k")  # pyright: ignore[reportPrivateUsage]

    assert command == [str(wineserver.resolve()), "-k"]
    assert calls == [command]


@pytest.mark.parametrize("configured", ["relative/wineserver", "/missing/wineserver"])
def test_wineserver_cleanup_does_not_fall_back_from_invalid_explicit_binary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    configured: str,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        headless_module.subprocess,
        "run",
        lambda command, **kwargs: calls.append(command),
    )
    prefix = tmp_path / "prefix"
    lifecycle = HeadlessLifecycle(
        launch_env={"WINESERVER": configured, "WINEPREFIX": str(prefix)}
    )

    assert lifecycle._run_wineserver(prefix, "-k") is None  # pyright: ignore[reportPrivateUsage]
    assert calls == []


@pytest.mark.skipif(os.name == "nt", reason="Wine prefix cleanup is POSIX-only")
def test_wineserver_cleanup_polls_before_escalating(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prefix = tmp_path / "prefix"
    commands: list[tuple[str, ...]] = []
    waits = iter((True,))

    def fake_run(self: HeadlessLifecycle, scoped_prefix: Path, *args: str) -> list[str]:
        assert scoped_prefix == prefix
        commands.append(args)
        return ["wineserver", *args]

    monkeypatch.setattr(HeadlessLifecycle, "_run_wineserver", fake_run)
    monkeypatch.setattr(
        HeadlessLifecycle,
        "_wait_for_owned_wine_processes_to_exit",
        lambda self, scoped_prefix: next(waits),
    )
    lifecycle = HeadlessLifecycle(launch_env={"WINEPREFIX": str(prefix)})

    completed = lifecycle._shutdown_owned_wineserver_prefix()  # pyright: ignore[reportPrivateUsage]

    assert commands == [("-k",)]
    assert completed == [["wineserver", "-k"]]


@pytest.mark.skipif(os.name == "nt", reason="Wine prefix cleanup is POSIX-only")
def test_wineserver_cleanup_escalates_after_bounded_poll(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prefix = tmp_path / "prefix"
    commands: list[tuple[str, ...]] = []
    waits = iter((False, True))

    def fake_run(self: HeadlessLifecycle, scoped_prefix: Path, *args: str) -> list[str]:
        assert scoped_prefix == prefix
        commands.append(args)
        return ["wineserver", *args]

    monkeypatch.setattr(HeadlessLifecycle, "_run_wineserver", fake_run)
    monkeypatch.setattr(
        HeadlessLifecycle,
        "_wait_for_owned_wine_processes_to_exit",
        lambda self, scoped_prefix: next(waits),
    )
    lifecycle = HeadlessLifecycle(launch_env={"WINEPREFIX": str(prefix)})

    completed = lifecycle._shutdown_owned_wineserver_prefix()  # pyright: ignore[reportPrivateUsage]

    assert commands == [("-k",), ("-k9",)]
    assert completed == [["wineserver", "-k"], ["wineserver", "-k9"]]


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
