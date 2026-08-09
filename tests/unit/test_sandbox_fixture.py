from __future__ import annotations

import json
import multiprocessing
import os
import shutil
from pathlib import Path
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

import tests.destructive.support.live_environment as live_env  # pyright: ignore[reportMissingImports]
import tests.destructive.support.sandbox_fixture as sandbox_fixture  # pyright: ignore[reportMissingImports]
from tests.support.platform_filesystem import create_symlink_or_skip
from tests.destructive.support.sandbox_fixture import (  # pyright: ignore[reportMissingImports]
    ENV_WWISE_REAL_LAUNCH_AUDIT_PATH,
    ENV_WWISE_SANDBOX_KEEP_ON_FAILURE,
    ENV_WWISE_STRICT_REAL,
    KEEP_ON_FAILURE_ROOT,
    LiveSandboxLock,
    SandboxFixtureError,
    cleanup_sandbox,
    hash_project,
    launch_sandboxed_wwise,
    prepare_sample_project_sandbox,
    require_lifecycle_ready_proof,
    shutdown_sandboxed_wwise,
)
from tests.destructive.support.live_environment import LiveEnvironmentError, require_destructive_environment  # pyright: ignore[reportMissingImports]
from wwise_waapi.headless import CleanupReport, ResidualProcess  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
ORG_FIXTURE_ROOT = REPO_ROOT / "tests" / "_org" / "2022.1"
ORG_FIXTURE_2023_ROOT = REPO_ROOT / "tests" / "_org" / "2023.1"


def _hold_live_sandbox_lock(root: str, acquired: Any, release: Any, results: Any) -> None:
    try:
        with LiveSandboxLock(Path(root)):
            acquired.set()
            if not release.wait(timeout=10):
                raise TimeoutError("test did not release the live sandbox lock holder")
    except BaseException as exc:
        results.put(("error", type(exc).__name__, str(exc)))
    else:
        results.put(("released",))


def _cross_process_context() -> multiprocessing.context.BaseContext:
    return multiprocessing.get_context("spawn" if os.name == "nt" else "fork")


def make_console(tmp_path: Path) -> Path:
    console = tmp_path / "WwiseConsole.sh"
    console.write_text("#!/bin/sh\n", encoding="utf-8")
    console.chmod(0o755)
    return console


def make_sample_project(root: Path, name: str = "SampleProject.wproj") -> Path:
    project = root / name
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_text("<WwiseDocument><ProjectInfo Name='SampleProject'/></WwiseDocument>\n", encoding="utf-8")
    (root / "Actor-Mixer Hierarchy").mkdir(parents=True, exist_ok=True)
    (root / "Actor-Mixer Hierarchy" / "Default Work Unit.wwu").write_text("<WorkUnit/>\n", encoding="utf-8")
    return project


def base_env(console: Path, project: Path, sandbox_root: Path) -> dict[str, str]:
    return {
        "WWISE_LIVE": "1",
        "WWISE_CONSOLE": str(console),
        "WWISE_SAMPLE_PROJECT_PATH": str(project),
        "WWISE_SANDBOX_ROOT": str(sandbox_root),
    }


class FakeProcess:
    pid = 4242


@pytest.mark.parametrize(
    ("expected_version", "year"),
    [
        ("2021.1", 2021),
        ("2022.1", 2022),
        ("2023.1", 2023),
        ("2024.1", 2024),
        ("2025.1", 2025),
    ],
)
def test_ready_proof_accepts_only_the_requested_supported_version(
    expected_version: str,
    year: int,
) -> None:
    class ReadyLifecycle:
        ready_result = {
            "version": {
                "displayName": f"fake Wwise {expected_version}",
                "year": year,
                "major": 1,
            }
        }
        process = FakeProcess()
        port = 31337
        command = ["WwiseConsole", "waapi-server"]

    assert require_lifecycle_ready_proof(
        ReadyLifecycle(),
        expected_version=expected_version,
    ) == ReadyLifecycle.ready_result


def test_live_sandbox_lock_serializes_actual_host_processes(tmp_path: Path) -> None:
    context = _cross_process_context()
    first_acquired = context.Event()
    release_first = context.Event()
    second_acquired = context.Event()
    release_second = context.Event()
    results = context.Queue()
    first = context.Process(
        target=_hold_live_sandbox_lock,
        args=(str(tmp_path), first_acquired, release_first, results),
    )
    second = context.Process(
        target=_hold_live_sandbox_lock,
        args=(str(tmp_path), second_acquired, release_second, results),
    )

    first.start()
    assert first_acquired.wait(timeout=5), "first process did not acquire the live sandbox lock"
    second.start()
    assert not second_acquired.wait(timeout=0.25), (
        "second process acquired the live sandbox lock before the first released it"
    )

    release_first.set()
    assert second_acquired.wait(timeout=5), (
        "second process did not acquire the live sandbox lock after the first released it"
    )
    release_second.set()

    outcomes = [results.get(timeout=5) for _ in range(2)]
    for process in (first, second):
        process.join(timeout=5)
        assert process.exitcode == 0
    assert outcomes == [("released",), ("released",)]
    assert (tmp_path / sandbox_fixture.LOCK_FILE_NAME).read_bytes() == b"\0"


def test_live_sandbox_lock_windows_backend_uses_materialized_byte_zero(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeMsvcrt:
        LK_NBLCK = 1
        LK_UNLCK = 2

        def __init__(self) -> None:
            self.calls: list[tuple[int, int, int, int]] = []

        def locking(self, fd: int, mode: int, byte_count: int) -> None:
            self.calls.append(
                (
                    mode,
                    byte_count,
                    os.lseek(fd, 0, os.SEEK_CUR),
                    os.fstat(fd).st_size,
                )
            )

    fake_msvcrt = FakeMsvcrt()
    monkeypatch.setattr(sandbox_fixture, "_msvcrt", fake_msvcrt)
    monkeypatch.setattr(sandbox_fixture, "_lock_platform_name", lambda: "nt")

    with LiveSandboxLock(tmp_path):
        assert (tmp_path / sandbox_fixture.LOCK_FILE_NAME).read_bytes() == b"\0"

    assert fake_msvcrt.calls == [
        (fake_msvcrt.LK_NBLCK, 1, 0, 1),
        (fake_msvcrt.LK_UNLCK, 1, 0, 1),
    ]


@pytest.mark.parametrize(
    ("platform_name", "module_name", "message"),
    [
        ("posix", "_fcntl", r"fcntl\.flock.*will not run unlocked"),
        ("nt", "_msvcrt", r"msvcrt\.locking.*will not run unlocked"),
        ("unsupported", None, r"no cross-process lock backend.*will not run unlocked"),
    ],
)
def test_live_sandbox_lock_missing_or_unknown_backend_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    platform_name: str,
    module_name: str | None,
    message: str,
) -> None:
    monkeypatch.setattr(sandbox_fixture, "_lock_platform_name", lambda: platform_name)
    if module_name is not None:
        monkeypatch.setattr(sandbox_fixture, module_name, None)

    with pytest.raises(SandboxFixtureError, match=message):
        with LiveSandboxLock(tmp_path):
            pytest.fail("an unsupported platform must never enter without a lock")

    assert not (tmp_path / sandbox_fixture.LOCK_FILE_NAME).exists()


def test_prepare_and_cleanup_success_preserves_source_immutability(tmp_path: Path) -> None:
    console = make_console(tmp_path)
    source_project = make_sample_project(tmp_path / "source SampleProject")
    sandbox_root = tmp_path / "runtime-sandboxes"
    before_mtime = source_project.stat().st_mtime
    before_hash = hash_project(source_project.parent)

    sandbox = prepare_sample_project_sandbox(base_env(console, source_project, sandbox_root))

    assert sandbox.sandbox_project.exists()
    assert sandbox.sandbox_project != source_project
    assert sandbox.sandbox_root == sandbox_root.resolve(strict=False)
    assert sandbox.env["WWISE_FIXTURE_PROJECT"] == str(sandbox.sandbox_project)
    metadata_path = sandbox.sandbox_path / "sandbox-metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["source_path"] == str(source_project.resolve(strict=True))
    assert metadata["sandbox_project_path"] == str(sandbox.sandbox_project)
    assert metadata["source_hash"]["digest"] == before_hash.digest
    assert metadata["sandbox_hash"]["digest"] == before_hash.digest
    assert metadata["source_mtime_before"] == before_mtime

    cleanup_sandbox(sandbox)

    assert not sandbox.sandbox_path.exists()
    assert source_project.stat().st_mtime == before_mtime
    assert hash_project(source_project.parent).digest == before_hash.digest


def test_keep_on_failure_preserves_under_evidence_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    console = make_console(tmp_path)
    source_project = make_sample_project(tmp_path / "source")
    sandbox = prepare_sample_project_sandbox(base_env(console, source_project, tmp_path / "sandbox-root"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(ENV_WWISE_SANDBOX_KEEP_ON_FAILURE, "1")

    preserved = cleanup_sandbox(sandbox, failed=True)

    assert preserved is not None
    assert preserved.exists()
    assert preserved.parent == (tmp_path / KEEP_ON_FAILURE_ROOT).resolve(strict=False)
    metadata = json.loads((preserved / "sandbox-metadata.json").read_text(encoding="utf-8"))
    assert metadata["keep_decision"].startswith("kept:")
    shutil.rmtree(preserved)


def test_rejects_sandbox_roots_that_overlap_source(tmp_path: Path) -> None:
    console = make_console(tmp_path)
    source_root = tmp_path / "source"
    source_project = make_sample_project(source_root)

    with pytest.raises(SandboxFixtureError, match="source root"):
        prepare_sample_project_sandbox(base_env(console, source_project, source_root))
    with pytest.raises(SandboxFixtureError, match="inside"):
        prepare_sample_project_sandbox(base_env(console, source_project, source_root / "child"))
    with pytest.raises(SandboxFixtureError, match="contain"):
        prepare_sample_project_sandbox(base_env(console, source_project, tmp_path))


@pytest.mark.parametrize("fixture_root", [ORG_FIXTURE_ROOT, ORG_FIXTURE_2023_ROOT])
def test_rejects_sandbox_roots_under_committed_org_fixture_source(fixture_root: Path, tmp_path: Path) -> None:
    console = make_console(tmp_path)
    source_project = make_sample_project(tmp_path / "source")

    with pytest.raises(SandboxFixtureError, match="tests/_org"):
        prepare_sample_project_sandbox(base_env(console, source_project, fixture_root / "runtime-sandbox"))


def test_rejects_sandbox_roots_under_installed_sample_project_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    console = make_console(tmp_path)
    source_project = make_sample_project(tmp_path / "source")
    installed_root = tmp_path / "Applications" / "Audiokinetic" / "SampleProject2023.1.19.8928" / "SampleProject"
    monkeypatch.setattr(live_env, "INSTALLED_SAMPLE_PROJECT_2023_1_ROOT", installed_root)

    with pytest.raises(SandboxFixtureError, match="installed SampleProject"):
        prepare_sample_project_sandbox(base_env(console, source_project, installed_root / "runtime-sandbox"))


def test_committed_org_fixture_source_is_copied_outside_source(tmp_path: Path) -> None:
    console = make_console(tmp_path)
    source_project = ORG_FIXTURE_ROOT / "SampleProject.wproj"
    sandbox_root = tmp_path / "sandbox-root"

    sandbox = prepare_sample_project_sandbox(base_env(console, source_project, sandbox_root))

    try:
        assert sandbox.source_root == ORG_FIXTURE_ROOT.resolve(strict=True)
        assert sandbox.sandbox_project.exists()
        assert ORG_FIXTURE_ROOT.resolve(strict=True) not in sandbox.sandbox_project.resolve(strict=True).parents
        assert sandbox.sandbox_root == sandbox_root.resolve(strict=False)
        assert sandbox.metadata.sandbox_hash.digest == sandbox.metadata.source_hash.digest
    finally:
        cleanup_sandbox(sandbox)


def test_destructive_environment_rejects_committed_org_fixture_targets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    console = make_console(tmp_path)
    source_project = ORG_FIXTURE_ROOT / "SampleProject.wproj"
    sandbox_root = ORG_FIXTURE_ROOT / "runtime-sandbox"
    monkeypatch.setenv("WWISE_LIVE", "1")
    monkeypatch.setenv("WWISE_DESTRUCTIVE", "1")
    monkeypatch.setenv("WWISE_CONSOLE", str(console))
    monkeypatch.setenv("WWISE_SAMPLE_PROJECT_PATH", str(source_project))
    monkeypatch.setenv("WWISE_FIXTURE_PROJECT", str(source_project))
    monkeypatch.setenv("WWISE_SANDBOX_ROOT", str(sandbox_root))

    with pytest.raises(LiveEnvironmentError, match="tests/_org"):
        require_destructive_environment()


def test_launch_uses_sandbox_project_and_records_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    console = make_console(tmp_path)
    source_project = make_sample_project(tmp_path / "source")
    env = base_env(console, source_project, tmp_path / "sandbox-root")
    env["WINEPREFIX"] = str(tmp_path / "caller-prefix-must-be-ignored")
    sandbox = prepare_sample_project_sandbox(env)
    seen_project_paths: list[Path] = []
    seen_ports: list[int | None] = []

    class FakeLifecycle:
        def __init__(self, **kwargs: Any) -> None:
            self.process = FakeProcess()
            self.port = kwargs["port"]
            seen_ports.append(self.port)
            self.project_path = kwargs["project_path"]
            self.launch_env = kwargs["launch_env"]
            self.launch_cwd = kwargs["launch_cwd_path"]
            self.command = [
                str(kwargs["console_path"]),
                "waapi-server",
                str(self.project_path),
                "--wamp-port",
                str(self.port),
                "--http-port",
                "0",
            ]
            self.ready_result: object = None
            self.cleanup_report: CleanupReport | None = None
            seen_project_paths.append(self.project_path)

        def run_until_ready(self) -> object:
            self.ready_result = {
                "version": {
                    "displayName": "fake Wwise 2022.1",
                    "year": 2022,
                    "major": 1,
                }
            }
            return self.ready_result

        def shutdown(self, suppress_errors: bool = True) -> None:
            self.process = None
            self.cleanup_report = CleanupReport(
                launch_pid=FakeProcess.pid,
                wine_prefix=self.launch_env.get("WINEPREFIX"),
                process_exited=True,
            )

    monkeypatch.setattr(sandbox_fixture, "HeadlessLifecycle", FakeLifecycle)

    lifecycle = launch_sandboxed_wwise(sandbox, env, port=31337)
    shutdown_sandboxed_wwise(lifecycle, sandbox)

    assert seen_project_paths == [sandbox.sandbox_project]
    assert seen_ports == [31337]
    assert str(source_project) not in " ".join(sandbox.metadata.command or [])
    assert sandbox.metadata.selected_port == 31337
    assert sandbox.metadata.launch_project_path == str(sandbox.sandbox_project)
    assert sandbox.metadata.launch_cwd_path == str(
        sandbox.sandbox_root.resolve(strict=True)
    )
    assert lifecycle.launch_cwd == sandbox.sandbox_root.resolve(strict=True)
    assert sandbox.metadata.ready_duration_seconds is not None
    assert sandbox.metadata.get_info_version == {
        "displayName": "fake Wwise 2022.1",
        "year": 2022,
        "major": 1,
    }
    assert sandbox.metadata.get_info_display_name == "fake Wwise 2022.1"
    assert sandbox.metadata.identity_verified is True
    assert sandbox.metadata.wine_prefix_path == str(sandbox.wine_prefix_path)
    assert lifecycle.launch_env["WINEPREFIX"] == str(sandbox.wine_prefix_path)
    assert sandbox.metadata.process_cleanup_result == "cleaned"
    assert seen_project_paths == [sandbox.sandbox_project]
    cleanup_sandbox(sandbox)


def test_launch_uses_fresh_case_owned_wine_prefix_without_precreating_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    console = make_console(tmp_path)
    source_project = make_sample_project(tmp_path / "source")
    env = base_env(console, source_project, tmp_path / "sandbox-root")
    case_owned_root = tmp_path / "case-owned"
    home = case_owned_root / "home"
    home.mkdir(parents=True)
    wine_prefix = home / "wine-prefix"
    env["HOME"] = str(home)
    env["WINEPREFIX"] = str(tmp_path / "caller-prefix-must-be-ignored")
    sandbox = prepare_sample_project_sandbox(env)
    prefix_exists_at_construction: list[bool] = []

    class FakeLifecycle:
        def __init__(self, **kwargs: Any) -> None:
            self.process = FakeProcess()
            self.port = 31341
            self.project_path = kwargs["project_path"]
            self.launch_env = kwargs["launch_env"]
            self.launch_cwd = kwargs["launch_cwd_path"]
            self.command = [str(kwargs["console_path"]), "waapi-server", str(self.project_path)]
            self.ready_result: object = None
            self.cleanup_report: CleanupReport | None = None
            prefix_exists_at_construction.append(wine_prefix.exists() or wine_prefix.is_symlink())

        def run_until_ready(self) -> object:
            self.ready_result = {
                "version": {
                    "displayName": "fake Wwise 2022.1",
                    "year": 2022,
                    "major": 1,
                }
            }
            return self.ready_result

        def shutdown(self, suppress_errors: bool = True) -> None:
            self.process = None
            self.cleanup_report = CleanupReport(
                launch_pid=FakeProcess.pid,
                wine_prefix=self.launch_env.get("WINEPREFIX"),
                process_exited=True,
            )

    monkeypatch.setattr(sandbox_fixture, "HeadlessLifecycle", FakeLifecycle)

    lifecycle = launch_sandboxed_wwise(
        sandbox,
        env,
        wine_prefix_path=wine_prefix,
        case_owned_root=case_owned_root,
    )

    assert prefix_exists_at_construction == [False]
    assert not wine_prefix.exists()
    assert lifecycle.launch_env["HOME"] == str(home.resolve(strict=True))
    assert lifecycle.launch_env["WINEPREFIX"] == str(wine_prefix.resolve(strict=False))
    assert sandbox.metadata.wine_prefix_path == str(wine_prefix.resolve(strict=False))
    persisted = json.loads((sandbox.sandbox_path / "sandbox-metadata.json").read_text(encoding="utf-8"))
    assert persisted["wine_prefix_path"] == str(wine_prefix.resolve(strict=False))

    shutdown_sandboxed_wwise(lifecycle, sandbox)

    assert sandbox.metadata.process_cleanup_result == "cleaned"
    assert sandbox.metadata.process_cleanup_details is not None
    assert sandbox.metadata.process_cleanup_details["wine_prefix"] == str(
        wine_prefix.resolve(strict=False)
    )
    cleanup_sandbox(sandbox)


def test_case_owned_wine_prefix_parameters_must_be_supplied_together(tmp_path: Path) -> None:
    console = make_console(tmp_path)
    source_project = make_sample_project(tmp_path / "source")
    env = base_env(console, source_project, tmp_path / "sandbox-root")
    case_owned_root = tmp_path / "case-owned"
    home = case_owned_root / "home"
    home.mkdir(parents=True)
    env["HOME"] = str(home)
    sandbox = prepare_sample_project_sandbox(env)

    try:
        with pytest.raises(SandboxFixtureError, match="provided together"):
            launch_sandboxed_wwise(
                sandbox,
                env,
                wine_prefix_path=home / "wine-prefix",
            )
        with pytest.raises(SandboxFixtureError, match="provided together"):
            launch_sandboxed_wwise(
                sandbox,
                env,
                case_owned_root=case_owned_root,
            )
    finally:
        cleanup_sandbox(sandbox, failed=True)


def test_case_owned_wine_prefix_rejects_invalid_home_existing_symlink_and_escape(
    tmp_path: Path,
) -> None:
    console = make_console(tmp_path)
    source_project = make_sample_project(tmp_path / "source")
    env = base_env(console, source_project, tmp_path / "sandbox-root")
    case_owned_root = tmp_path / "case-owned"
    home = case_owned_root / "home"
    home.mkdir(parents=True)
    sandbox = prepare_sample_project_sandbox(env)

    try:
        missing_home_env = dict(env)
        missing_home_env.pop("HOME", None)
        with pytest.raises(SandboxFixtureError, match="HOME must name"):
            launch_sandboxed_wwise(
                sandbox,
                missing_home_env,
                wine_prefix_path=home / "missing-home-prefix",
                case_owned_root=case_owned_root,
            )

        nonexistent_home_env = {**env, "HOME": str(case_owned_root / "missing-home")}
        with pytest.raises(SandboxFixtureError, match="HOME must be an existing real directory"):
            launch_sandboxed_wwise(
                sandbox,
                nonexistent_home_env,
                wine_prefix_path=case_owned_root / "missing-home" / "wine-prefix",
                case_owned_root=case_owned_root,
            )

        real_home = case_owned_root / "real-home"
        real_home.mkdir()
        symlink_home = case_owned_root / "symlink-home"
        create_symlink_or_skip(symlink_home, real_home, target_is_directory=True)
        symlink_home_env = {**env, "HOME": str(symlink_home)}
        with pytest.raises(SandboxFixtureError, match="HOME must be an existing real directory"):
            launch_sandboxed_wwise(
                sandbox,
                symlink_home_env,
                wine_prefix_path=symlink_home / "wine-prefix",
                case_owned_root=case_owned_root,
            )

        valid_env = {**env, "HOME": str(home)}
        existing_prefix = home / "existing-prefix"
        existing_prefix.mkdir()
        with pytest.raises(SandboxFixtureError, match="must not already exist .*existing path"):
            launch_sandboxed_wwise(
                sandbox,
                valid_env,
                wine_prefix_path=existing_prefix,
                case_owned_root=case_owned_root,
            )

        symlink_target = home / "symlink-target"
        symlink_target.mkdir()
        symlink_prefix = home / "symlink-prefix"
        create_symlink_or_skip(symlink_prefix, symlink_target, target_is_directory=True)
        with pytest.raises(SandboxFixtureError, match="must not already exist .*symlink"):
            launch_sandboxed_wwise(
                sandbox,
                valid_env,
                wine_prefix_path=symlink_prefix,
                case_owned_root=case_owned_root,
            )

        escaped_parent_target = tmp_path / "escaped-prefix-parent"
        escaped_parent_target.mkdir()
        symlink_parent = home / "linked-parent"
        create_symlink_or_skip(
            symlink_parent,
            escaped_parent_target,
            target_is_directory=True,
        )
        with pytest.raises(SandboxFixtureError, match="symlink parent"):
            launch_sandboxed_wwise(
                sandbox,
                valid_env,
                wine_prefix_path=symlink_parent / "wine-prefix",
                case_owned_root=case_owned_root,
            )

        with pytest.raises(SandboxFixtureError, match="strictly under HOME"):
            launch_sandboxed_wwise(
                sandbox,
                valid_env,
                wine_prefix_path=case_owned_root / "outside-home-prefix",
                case_owned_root=case_owned_root,
            )

        outside_home = tmp_path / "outside-home"
        outside_home.mkdir()
        outside_env = {**env, "HOME": str(outside_home)}
        with pytest.raises(SandboxFixtureError, match="HOME must be strictly under case_owned_root"):
            launch_sandboxed_wwise(
                sandbox,
                outside_env,
                wine_prefix_path=outside_home / "wine-prefix",
                case_owned_root=case_owned_root,
            )
    finally:
        cleanup_sandbox(sandbox, failed=True)


def test_strict_real_launch_audit_is_written_after_shutdown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    console = make_console(tmp_path)
    source_project = make_sample_project(tmp_path / "source")
    env = base_env(console, source_project, tmp_path / "sandbox-root")
    audit_path = tmp_path / "evidence" / "real-launches.jsonl"
    monkeypatch.setenv(ENV_WWISE_STRICT_REAL, "1")
    monkeypatch.setenv(ENV_WWISE_REAL_LAUNCH_AUDIT_PATH, str(audit_path))
    sandbox = prepare_sample_project_sandbox(env)

    class FakeLifecycle:
        def __init__(self, **kwargs: Any) -> None:
            self.process = FakeProcess()
            self.port = 31337
            self.project_path = kwargs["project_path"]
            self.launch_env = kwargs["launch_env"]
            self.launch_cwd = kwargs["launch_cwd_path"]
            self.command = [
                str(kwargs["console_path"]),
                "waapi-server",
                str(self.project_path),
                "--wamp-port",
                str(self.port),
                "--http-port",
                "0",
            ]
            self.ready_result: object = None
            self.cleanup_report: CleanupReport | None = None

        def run_until_ready(self) -> object:
            self.ready_result = {
                "version": {
                    "displayName": "fake Wwise 2022.1",
                    "year": 2022,
                    "major": 1,
                }
            }
            return self.ready_result

        def shutdown(self, suppress_errors: bool = True) -> None:
            self.process = None
            self.cleanup_report = CleanupReport(
                launch_pid=FakeProcess.pid,
                wine_prefix=self.launch_env.get("WINEPREFIX"),
                process_exited=True,
            )

    monkeypatch.setattr(sandbox_fixture, "HeadlessLifecycle", FakeLifecycle)

    lifecycle = launch_sandboxed_wwise(sandbox, env)
    shutdown_sandboxed_wwise(lifecycle, sandbox)

    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    record = records[0]
    assert record["wwise_version"] == "2022.1"
    assert record["pid"] == 4242
    assert record["port"] == 31337
    assert record["command"] == [
        str(console),
        "waapi-server",
        str(sandbox.sandbox_project),
        "--wamp-port",
        "31337",
        "--http-port",
        "0",
    ]
    assert record["wine_prefix_path"] == str(sandbox.wine_prefix_path)
    assert record["launch_project_path"] == str(sandbox.sandbox_project)
    assert record["launch_cwd_path"] == str(sandbox.sandbox_root.resolve(strict=True))
    assert record["sandbox_project_path"] == str(sandbox.sandbox_project)
    assert record["ready_duration_seconds"] >= 0
    assert record["get_info_version"] == {
        "displayName": "fake Wwise 2022.1",
        "year": 2022,
        "major": 1,
    }
    assert record["get_info_display_name"] == "fake Wwise 2022.1"
    assert record["cleanup_result"] == "cleaned"
    assert record["cleanup_details"]["wine_prefix"] == str(sandbox.wine_prefix_path)
    assert isinstance(record["recorded_at_unix"], int)
    cleanup_sandbox(sandbox)


def test_non_strict_launch_does_not_write_persistent_audit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    console = make_console(tmp_path)
    source_project = make_sample_project(tmp_path / "source")
    env = base_env(console, source_project, tmp_path / "sandbox-root")
    audit_path = tmp_path / "evidence" / "real-launches.jsonl"
    monkeypatch.delenv(ENV_WWISE_STRICT_REAL, raising=False)
    monkeypatch.setenv(ENV_WWISE_REAL_LAUNCH_AUDIT_PATH, str(audit_path))
    sandbox = prepare_sample_project_sandbox(env)

    class FakeLifecycle:
        def __init__(self, **kwargs: Any) -> None:
            self.process = FakeProcess()
            self.port = 31337
            self.project_path = kwargs["project_path"]
            self.launch_env = kwargs["launch_env"]
            self.launch_cwd = kwargs["launch_cwd_path"]
            self.command = [
                str(kwargs["console_path"]),
                "waapi-server",
                str(self.project_path),
                "--wamp-port",
                str(self.port),
                "--http-port",
                "0",
            ]
            self.ready_result: object = None
            self.cleanup_report: CleanupReport | None = None

        def run_until_ready(self) -> object:
            self.ready_result = {
                "version": {
                    "displayName": "fake Wwise 2022.1",
                    "year": 2022,
                    "major": 1,
                }
            }
            return self.ready_result

        def shutdown(self, suppress_errors: bool = True) -> None:
            self.process = None
            self.cleanup_report = CleanupReport(
                launch_pid=FakeProcess.pid,
                wine_prefix=self.launch_env.get("WINEPREFIX"),
                process_exited=True,
            )

    monkeypatch.setattr(sandbox_fixture, "HeadlessLifecycle", FakeLifecycle)

    lifecycle = launch_sandboxed_wwise(sandbox, env)
    shutdown_sandboxed_wwise(lifecycle, sandbox)

    assert not audit_path.exists()
    cleanup_sandbox(sandbox)


@pytest.mark.parametrize(
    ("ready_result", "error_pattern"),
    [
        ({"version": {}}, "displayName"),
        (
            {
                "version": {
                    "displayName": "fake Wwise 2021.1",
                    "year": 2021,
                    "major": 1,
                }
            },
            "version mismatch",
        ),
    ],
)
def test_launch_shuts_down_when_ready_proof_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    ready_result: dict[str, object],
    error_pattern: str,
) -> None:
    console = make_console(tmp_path)
    source_project = make_sample_project(tmp_path / "source")
    env = base_env(console, source_project, tmp_path / "sandbox-root")
    case_owned_root = tmp_path / "case-owned"
    home = case_owned_root / "home"
    home.mkdir(parents=True)
    wine_prefix = home / "wine-prefix"
    env["HOME"] = str(home)
    sandbox = prepare_sample_project_sandbox(env)
    shutdown_calls: list[bool] = []
    lifecycles: list[FakeLifecycle] = []
    metadata_writes: list[Path] = []
    prefix_exists_at_construction: list[bool] = []
    original_write_metadata = sandbox_fixture.SandboxProject.write_metadata

    def tracked_write_metadata(project: sandbox_fixture.SandboxProject) -> Path:
        metadata_writes.append(project.sandbox_path)
        return original_write_metadata(project)

    class FakeLifecycle:
        def __init__(self, **kwargs: Any) -> None:
            self.process = FakeProcess()
            self.port = 31338
            self.project_path = kwargs["project_path"]
            self.launch_env = kwargs["launch_env"]
            self.launch_cwd = kwargs["launch_cwd_path"]
            self.command = [
                str(kwargs["console_path"]),
                "waapi-server",
                str(self.project_path),
                "--wamp-port",
                str(self.port),
                "--http-port",
                "0",
            ]
            self.ready_result: object = None
            self.cleanup_report: CleanupReport | None = None
            lifecycles.append(self)
            prefix_exists_at_construction.append(wine_prefix.exists() or wine_prefix.is_symlink())

        def run_until_ready(self) -> object:
            self.ready_result = ready_result
            return self.ready_result

        def shutdown(self, suppress_errors: bool = True) -> None:
            shutdown_calls.append(suppress_errors)
            self.process = None
            self.cleanup_report = CleanupReport(
                launch_pid=FakeProcess.pid,
                wine_prefix=self.launch_env.get("WINEPREFIX"),
                process_exited=True,
            )

    monkeypatch.setattr(sandbox_fixture, "HeadlessLifecycle", FakeLifecycle)
    monkeypatch.setattr(sandbox_fixture.SandboxProject, "write_metadata", tracked_write_metadata)

    try:
        with pytest.raises(SandboxFixtureError, match=error_pattern):
            launch_sandboxed_wwise(
                sandbox,
                env,
                wine_prefix_path=wine_prefix,
                case_owned_root=case_owned_root,
            )
        assert shutdown_calls == [True]
        assert len(lifecycles) == 1
        assert prefix_exists_at_construction == [False]
        assert lifecycles[0].launch_env["WINEPREFIX"] == str(wine_prefix.resolve(strict=False))
        assert lifecycles[0].process is None
        assert metadata_writes == [sandbox.sandbox_path]
        persisted = json.loads((sandbox.sandbox_path / "sandbox-metadata.json").read_text(encoding="utf-8"))
        assert persisted["selected_port"] == 31338
        assert persisted["command"] == lifecycles[0].command
        assert persisted["process_pid"] == FakeProcess.pid
        assert persisted["wine_prefix_path"] == str(wine_prefix.resolve(strict=False))
        assert persisted["launch_project_path"] == str(sandbox.sandbox_project)
        assert persisted["launch_cwd_path"] == str(
            sandbox.sandbox_root.resolve(strict=True)
        )
        assert persisted["process_cleanup_result"] == "cleaned"
        assert persisted["process_cleanup_details"]["launch_pid"] == FakeProcess.pid
        assert persisted["process_cleanup_details"]["wine_prefix"] == str(
            wine_prefix.resolve(strict=False)
        )
        assert persisted["get_info_version"] is None
        assert persisted["get_info_display_name"] is None
        assert persisted["identity_verified"] is None
    finally:
        cleanup_sandbox(sandbox, failed=True)


@pytest.mark.parametrize(
    ("residual_processes", "expected_cleanup_result"),
    [
        ([], "cleaned"),
        ([ResidualProcess(pid=999, command="WINEPREFIX=/tmp/test wineserver")], "residual-processes"),
    ],
)
def test_launch_failure_records_existing_cleanup_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    residual_processes: list[ResidualProcess],
    expected_cleanup_result: str,
) -> None:
    console = make_console(tmp_path)
    source_project = make_sample_project(tmp_path / "source")
    env = base_env(console, source_project, tmp_path / "sandbox-root")
    sandbox = prepare_sample_project_sandbox(env)
    launch_error = RuntimeError("readiness failed after lifecycle cleanup")
    shutdown_calls: list[bool] = []
    lifecycles: list[FakeLifecycle] = []

    class FakeLifecycle:
        def __init__(self, **kwargs: Any) -> None:
            self.process = FakeProcess()
            self.port = 31339
            self.project_path = kwargs["project_path"]
            self.launch_env = kwargs["launch_env"]
            self.launch_cwd = kwargs["launch_cwd_path"]
            self.command = [
                str(kwargs["console_path"]),
                "waapi-server",
                str(self.project_path),
                "--wamp-port",
                str(self.port),
                "--http-port",
                "0",
            ]
            self.ready_result: object = None
            self.cleanup_report: CleanupReport | None = None
            lifecycles.append(self)

        def run_until_ready(self) -> object:
            self.process = None
            self.cleanup_report = CleanupReport(
                launch_pid=5151,
                wine_prefix=self.launch_env.get("WINEPREFIX"),
                process_exited=True,
                residual_processes=list(residual_processes),
            )
            raise launch_error

        def shutdown(self, suppress_errors: bool = True) -> None:
            shutdown_calls.append(suppress_errors)

    monkeypatch.setattr(sandbox_fixture, "HeadlessLifecycle", FakeLifecycle)

    try:
        with pytest.raises(RuntimeError, match="readiness failed after lifecycle cleanup") as exc_info:
            launch_sandboxed_wwise(sandbox, env)
        assert exc_info.value is launch_error
        assert shutdown_calls == [True]
        assert len(lifecycles) == 1
        persisted = json.loads((sandbox.sandbox_path / "sandbox-metadata.json").read_text(encoding="utf-8"))
        assert persisted["selected_port"] == 31339
        assert persisted["command"] == lifecycles[0].command
        assert persisted["process_pid"] == 5151
        assert persisted["wine_prefix_path"] == str(sandbox.wine_prefix_path)
        assert persisted["launch_project_path"] == str(sandbox.sandbox_project)
        assert persisted["launch_cwd_path"] == str(
            sandbox.sandbox_root.resolve(strict=True)
        )
        assert persisted["process_cleanup_result"] == expected_cleanup_result
        assert persisted["process_cleanup_details"]["launch_pid"] == 5151
        assert persisted["process_cleanup_details"]["residual_processes"] == [
            {"pid": process.pid, "command": process.command} for process in residual_processes
        ]
        assert persisted["get_info_version"] is None
        assert persisted["get_info_display_name"] is None
        assert persisted["identity_verified"] is None
    finally:
        cleanup_sandbox(sandbox, failed=True)


def test_launch_shuts_down_when_run_until_ready_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    console = make_console(tmp_path)
    source_project = make_sample_project(tmp_path / "source")
    env = base_env(console, source_project, tmp_path / "sandbox-root")
    sandbox = prepare_sample_project_sandbox(env)
    launch_error = RuntimeError("run_until_ready failed")
    shutdown_calls: list[bool] = []
    lifecycles: list[FakeLifecycle] = []
    metadata_writes: list[Path] = []
    original_write_metadata = sandbox_fixture.SandboxProject.write_metadata

    def tracked_write_metadata(project: sandbox_fixture.SandboxProject) -> Path:
        metadata_writes.append(project.sandbox_path)
        return original_write_metadata(project)

    class FakeLifecycle:
        def __init__(self, **kwargs: Any) -> None:
            self.process = FakeProcess()
            self.port = 31338
            self.project_path = kwargs["project_path"]
            self.launch_env = kwargs["launch_env"]
            self.launch_cwd = kwargs["launch_cwd_path"]
            self.command = [
                str(kwargs["console_path"]),
                "waapi-server",
                str(self.project_path),
                "--wamp-port",
                str(self.port),
                "--http-port",
                "0",
            ]
            self.ready_result: object = None
            self.cleanup_report: CleanupReport | None = None
            lifecycles.append(self)

        def run_until_ready(self) -> object:
            raise launch_error

        def shutdown(self, suppress_errors: bool = True) -> None:
            shutdown_calls.append(suppress_errors)
            self.process = None
            raise RuntimeError("cleanup failed")

    monkeypatch.setattr(sandbox_fixture, "HeadlessLifecycle", FakeLifecycle)
    monkeypatch.setattr(sandbox_fixture.SandboxProject, "write_metadata", tracked_write_metadata)

    try:
        with pytest.raises(RuntimeError, match="run_until_ready failed") as exc_info:
            launch_sandboxed_wwise(sandbox, env)
        assert exc_info.value is launch_error
        assert shutdown_calls == [True]
        assert len(lifecycles) == 1
        assert lifecycles[0].process is None
        assert metadata_writes == [sandbox.sandbox_path]
        persisted = json.loads((sandbox.sandbox_path / "sandbox-metadata.json").read_text(encoding="utf-8"))
        assert persisted["selected_port"] == 31338
        assert persisted["command"] == lifecycles[0].command
        assert persisted["process_pid"] == FakeProcess.pid
        assert persisted["wine_prefix_path"] == str(sandbox.wine_prefix_path)
        assert persisted["launch_project_path"] == str(sandbox.sandbox_project)
        assert persisted["launch_cwd_path"] == str(
            sandbox.sandbox_root.resolve(strict=True)
        )
        assert persisted["process_cleanup_details"] is None
        assert persisted["process_cleanup_result"] == "error:RuntimeError:cleanup failed"
        assert persisted["get_info_version"] is None
        assert persisted["get_info_display_name"] is None
        assert persisted["identity_verified"] is None
    finally:
        cleanup_sandbox(sandbox, failed=True)


def test_shutdown_raises_when_cleanup_report_has_residual_processes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    console = make_console(tmp_path)
    source_project = make_sample_project(tmp_path / "source")
    env = base_env(console, source_project, tmp_path / "sandbox-root")
    sandbox = prepare_sample_project_sandbox(env)

    class FakeLifecycle:
        def __init__(self, **kwargs: Any) -> None:
            self.process = FakeProcess()
            self.port = 31337
            self.project_path = kwargs["project_path"]
            self.launch_env = kwargs["launch_env"]
            self.launch_cwd = kwargs["launch_cwd_path"]
            self.command = [
                str(kwargs["console_path"]),
                "waapi-server",
                str(self.project_path),
                "--wamp-port",
                str(self.port),
                "--http-port",
                "0",
            ]
            self.ready_result: object = None
            self.cleanup_report: CleanupReport | None = None

        def run_until_ready(self) -> object:
            self.ready_result = {
                "version": {
                    "displayName": "fake Wwise 2022.1",
                    "year": 2022,
                    "major": 1,
                }
            }
            return self.ready_result

        def shutdown(self, suppress_errors: bool = True) -> None:
            self.process = None
            self.cleanup_report = CleanupReport(
                launch_pid=FakeProcess.pid,
                wine_prefix=self.launch_env.get("WINEPREFIX"),
                process_exited=True,
                residual_processes=[ResidualProcess(pid=999, command="WINEPREFIX=/tmp/test wineserver")],
            )

    monkeypatch.setattr(sandbox_fixture, "HeadlessLifecycle", FakeLifecycle)

    lifecycle = launch_sandboxed_wwise(sandbox, env)
    with pytest.raises(SandboxFixtureError, match="residual processes"):
        shutdown_sandboxed_wwise(lifecycle, sandbox)

    assert sandbox.metadata.process_cleanup_result == "residual-processes"
    assert sandbox.metadata.process_cleanup_details is not None
    cleanup_sandbox(sandbox, failed=True)


def test_missing_copied_wproj_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    console = make_console(tmp_path)
    source_project = make_sample_project(tmp_path / "source")

    def broken_copytree(source: Path, destination: Path, symlinks: bool = False) -> None:
        destination.mkdir(parents=True)
        (destination / "not-a-project.txt").write_text("missing wproj", encoding="utf-8")

    monkeypatch.setattr(sandbox_fixture.shutil, "copytree", broken_copytree)

    with pytest.raises(SandboxFixtureError, match="missing expected project file"):
        prepare_sample_project_sandbox(base_env(console, source_project, tmp_path / "sandbox-root"))
