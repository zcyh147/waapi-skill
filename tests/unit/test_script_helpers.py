from __future__ import annotations

import importlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

script_config = importlib.import_module("scripts.config")
run_script = importlib.import_module("scripts.run")
setup_script = importlib.import_module("scripts.setup_environment")


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "waapi-skill"


class CompletedPopen:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return self.returncode

    def poll(self) -> int:
        return self.returncode


def test_script_config_exports_expected_paths_and_targets() -> None:
    assert script_config.SKILL_DIR == SKILL_ROOT
    assert script_config.VENV_DIR == script_config.SKILL_DIR / ".venv"
    assert script_config.PACKAGED_SCRIPT_ALLOWLIST == frozenset(
        {"gateway.py", "setup_environment.py"}
    )
    assert script_config.COVERAGE_MINIMUM == 85
    assert script_config.CORE_COVERAGE_TARGETS["manifest"] == 95


def test_run_main_without_script_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_script.main([]) == 0
    captured = capsys.readouterr()
    assert "Run Wwise WAAPI skill scripts" in captured.out


def test_run_process_rejects_direct_execution_when_codex_gateway_is_required() -> None:
    environment = dict(os.environ)
    environment[run_script.CODEX_GATEWAY_REQUIRED_ENV] = "1"

    result = subprocess.run(
        [sys.executable, str(SKILL_ROOT / "scripts" / "run.py"), "gateway.py", "status"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == run_script.CODEX_GATEWAY_REQUIRED_EXIT_CODE
    assert result.stdout == ""
    assert "Direct run.py execution is disabled" in result.stderr
    assert "authorized WAAPI gateway broker" in result.stderr


def test_run_main_executes_existing_script_when_bootstrap_is_stubbed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(run_script, "VENV_DIR", tmp_path / ".venv")
    run_script.VENV_DIR.mkdir(parents=True)
    monkeypatch.setattr(run_script, "bootstrap_if_needed", lambda: None)

    calls: list[list[str]] = []

    def fake_popen(cmd, **kwargs):
        del kwargs
        calls.append([str(part) for part in cmd])
        return CompletedPopen()

    monkeypatch.setattr(run_script.subprocess, "Popen", fake_popen)
    assert run_script.main(["setup_environment.py", "--check"]) == 0
    assert calls and calls[0][0].endswith(("python", "python.exe"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX SIGINT cleanup integration")
def test_run_main_returns_standard_interrupt_code_without_wrapper_traceback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    skill_root = tmp_path / "skill"
    scripts_root = skill_root / "scripts"
    scripts_root.mkdir(parents=True)
    marker = tmp_path / "cleanup-marker.txt"
    ready = tmp_path / "ready.txt"
    (scripts_root / "gateway.py").write_text(
        "\n".join(
            (
                "import signal",
                "import sys",
                "import time",
                "from pathlib import Path",
                "marker = Path(sys.argv[1])",
                "ready = Path(sys.argv[2])",
                "def cancel(signum, frame):",
                "    del signum, frame",
                "    time.sleep(0.35)",
                "    marker.write_text('cleaned', encoding='utf-8')",
                "    print('{\"status\":\"cancelled\"}', flush=True)",
                "    raise SystemExit(130)",
                "signal.signal(signal.SIGINT, cancel)",
                "ready.write_text('ready', encoding='utf-8')",
                "while True:",
                "    time.sleep(0.05)",
                "",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(run_script, "SKILL_DIR", skill_root)
    monkeypatch.setattr(run_script, "venv_python", lambda: Path(sys.executable))
    monkeypatch.setattr(run_script, "bootstrap_if_needed", lambda: None)
    real_popen = subprocess.Popen
    launched: list[InterruptingPopen] = []

    class InterruptingPopen:
        def __init__(self, command: list[str]) -> None:
            self.process = real_popen(command)
            self.initial_wait = True
            self.forwarded_signals: list[int] = []
            self.terminated = False
            self.killed = False

        def wait(self, timeout: float | None = None) -> int:
            if self.initial_wait:
                self.initial_wait = False
                deadline = time.monotonic() + 2.0
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert ready.exists(), "temporary gateway did not install its handler"
                self.process.send_signal(signal.SIGINT)
                raise KeyboardInterrupt
            return self.process.wait(timeout=timeout)

        def poll(self) -> int | None:
            return self.process.poll()

        def send_signal(self, requested_signal: int) -> None:
            self.forwarded_signals.append(requested_signal)
            self.process.send_signal(requested_signal)

        def terminate(self) -> None:
            self.terminated = True
            self.process.terminate()

        def kill(self) -> None:
            self.killed = True
            self.process.kill()

    def launch(command: list[str], **kwargs) -> InterruptingPopen:
        assert kwargs == {}
        process = InterruptingPopen(command)
        launched.append(process)
        return process

    monkeypatch.setattr(run_script.subprocess, "Popen", launch)

    assert run_script.main(["gateway.py", str(marker), str(ready)]) == 130
    assert marker.read_text(encoding="utf-8") == "cleaned"
    assert launched[0].forwarded_signals == []
    assert launched[0].terminated is False
    assert launched[0].killed is False


def test_run_main_escalates_and_reaps_child_that_ignores_interrupt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(run_script, "VENV_DIR", tmp_path / ".venv")
    run_script.VENV_DIR.mkdir(parents=True)
    monkeypatch.setattr(run_script, "bootstrap_if_needed", lambda: None)
    events: list[tuple[str, float | int | None]] = []

    class StuckPopen:
        def __init__(self) -> None:
            self.initial_wait = True
            self.killed = False

        def wait(self, timeout: float | None = None) -> int:
            if self.initial_wait:
                self.initial_wait = False
                raise KeyboardInterrupt
            events.append(("wait", timeout))
            if self.killed:
                return -signal.SIGKILL
            raise subprocess.TimeoutExpired(cmd=["gateway.py"], timeout=timeout)

        def poll(self) -> int | None:
            return -signal.SIGKILL if self.killed else None

        def send_signal(self, requested_signal: int) -> None:
            events.append(("signal", requested_signal))
            raise OSError("synthetic platform SIGINT rejection")

        def terminate(self) -> None:
            events.append(("terminate", None))

        def kill(self) -> None:
            events.append(("kill", None))
            self.killed = True

    process = StuckPopen()
    monkeypatch.setattr(run_script.subprocess, "Popen", lambda *args, **kwargs: process)

    assert run_script.main(["gateway.py", "wait-topic", "ak.test", "--no-timeout"]) == 130
    assert [event[0] for event in events] == [
        "wait",
        "signal",
        "wait",
        "terminate",
        "wait",
        "kill",
    ]
    assert events[0][1] == pytest.approx(
        run_script.INTERRUPTED_CHILD_CLEANUP_GRACE_SECONDS,
        abs=0.01,
    )
    assert events[1] == ("signal", signal.SIGINT)
    assert events[2][1] == pytest.approx(
        run_script.INTERRUPTED_CHILD_SIGNAL_GRACE_SECONDS,
        abs=0.01,
    )
    assert events[3] == ("terminate", None)
    assert events[4][1] == pytest.approx(
        run_script.INTERRUPTED_CHILD_TERMINATE_GRACE_SECONDS,
        abs=0.01,
    )
    assert events[5] == ("kill", None)


@pytest.mark.parametrize(
    "runner_selector",
    (
        ("--version", "2022.1"),
        ("--version=2022.1",),
        ("--wwise-version", "2022.1"),
        ("--wwise-version=2022.1",),
    ),
)
def test_run_main_normalizes_closed_version_selector_before_gateway_target(
    runner_selector: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(run_script, "VENV_DIR", tmp_path / ".venv")
    run_script.VENV_DIR.mkdir(parents=True)
    monkeypatch.setattr(run_script, "bootstrap_if_needed", lambda: None)
    calls: list[list[str]] = []

    def fake_popen(cmd, **kwargs):
        del kwargs
        calls.append([str(part) for part in cmd])
        return CompletedPopen()

    monkeypatch.setattr(run_script.subprocess, "Popen", fake_popen)

    assert run_script.main(
        [*runner_selector, "gateway.py", "operation-schema", "object.copy"]
    ) == 0
    assert calls == [
        [
            str(run_script.venv_python()),
            str(SKILL_ROOT / "scripts" / "gateway.py"),
            "--version",
            "2022.1",
            "operation-schema",
            "object.copy",
        ]
    ]


@pytest.mark.parametrize(
    "arguments",
    (
        ("--version", "2022.1", "setup_environment.py", "--check"),
        ("--version", "2022.1", "scripts/gateway.py", "status"),
        ("--version", "2022.1", "../gateway.py", "status"),
        ("--version", "2022.1", "gateway.py", "--version", "2022.1", "status"),
        ("--version", "2022.1", "gateway.py", "--wwise-version=2022.1", "status"),
        ("--version", "2022.1", "--wwise-version", "2022.1", "gateway.py", "status"),
        ("--version", "2030.1", "gateway.py", "status"),
        ("--ver", "2022.1", "gateway.py", "status"),
        ("--version",),
    ),
)
def test_run_main_rejects_unclosed_runner_version_selector_forms(
    arguments: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        run_script.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("rejected runner form must not execute"),
    )

    with pytest.raises(SystemExit):
        run_script.main(list(arguments))


def test_run_main_does_not_confuse_config_set_field_with_global_selector(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(run_script, "VENV_DIR", tmp_path / ".venv")
    run_script.VENV_DIR.mkdir(parents=True)
    monkeypatch.setattr(run_script, "bootstrap_if_needed", lambda: None)
    calls: list[list[str]] = []

    def fake_popen(cmd, **kwargs):
        del kwargs
        calls.append([str(part) for part in cmd])
        return CompletedPopen()

    monkeypatch.setattr(run_script.subprocess, "Popen", fake_popen)

    assert run_script.main(
        [
            "--version",
            "2022.1",
            "gateway.py",
            "config-set",
            "--wwise-version",
            "2023.1",
        ]
    ) == 0
    assert calls[0][2:] == [
        "--version",
        "2022.1",
        "config-set",
        "--wwise-version",
        "2023.1",
    ]


def test_run_bootstrap_if_needed_invokes_setup_when_venv_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(run_script, "VENV_DIR", tmp_path / ".venv")
    invoked: list[list[str]] = []

    def fake_run(cmd, check=True):
        invoked.append([str(part) for part in cmd])

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(run_script.subprocess, "run", fake_run)
    run_script.bootstrap_if_needed()
    assert invoked and invoked[0][0] == str(run_script.sys.executable)


@pytest.mark.parametrize("setup_state", ("missing", "symlink"))
def test_run_bootstrap_rejects_untrusted_setup_target_without_execution(
    setup_state: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    skill_root = tmp_path / "skill"
    scripts_root = skill_root / "scripts"
    scripts_root.mkdir(parents=True)
    (scripts_root / "gateway.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    if setup_state == "symlink":
        outside = tmp_path / "outside_setup.py"
        outside.write_text("raise SystemExit(0)\n", encoding="utf-8")
        (scripts_root / "setup_environment.py").symlink_to(outside)
    monkeypatch.setattr(run_script, "SKILL_DIR", skill_root)
    monkeypatch.setattr(run_script, "VENV_DIR", tmp_path / ".venv-missing")
    monkeypatch.setattr(
        run_script.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("untrusted bootstrap target must not execute"),
    )

    with pytest.raises(run_script.PackagedScriptError):
        run_script.bootstrap_if_needed()
    with pytest.raises(SystemExit):
        run_script.main(["gateway.py"])


def test_run_main_unknown_script_exits(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(run_script, "VENV_DIR", tmp_path / ".venv")
    run_script.VENV_DIR.mkdir(parents=True)
    with pytest.raises(SystemExit):
        run_script.main(["does-not-exist.py"])


def test_run_main_rejects_existing_script_outside_packaged_allowlist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    skill_root = tmp_path / "skill"
    scripts_root = skill_root / "scripts"
    scripts_root.mkdir(parents=True)
    (scripts_root / "temporary_helper.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    monkeypatch.setattr(run_script, "SKILL_DIR", skill_root)
    monkeypatch.setattr(run_script, "VENV_DIR", tmp_path / ".venv")
    run_script.VENV_DIR.mkdir(parents=True)

    with pytest.raises(SystemExit):
        run_script.main(["temporary_helper.py"])


@pytest.mark.parametrize(
    "script_name",
    (
        "../outside.py",
        "scripts/../outside.py",
        "scripts/nested/tool.py",
        r"..\outside.py",
        "/tmp/outside.py",
        "/tmp/gateway.py",
    ),
)
def test_run_main_rejects_script_path_traversal(
    script_name: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(run_script, "VENV_DIR", tmp_path / ".venv")
    run_script.VENV_DIR.mkdir(parents=True)

    with pytest.raises(SystemExit):
        run_script.main([script_name])


def test_run_main_rejects_symlinked_packaged_script(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    skill_root = tmp_path / "skill"
    scripts_root = skill_root / "scripts"
    scripts_root.mkdir(parents=True)
    outside = tmp_path / "outside.py"
    outside.write_text("raise SystemExit(0)\n", encoding="utf-8")
    (scripts_root / "gateway.py").symlink_to(outside)
    monkeypatch.setattr(run_script, "SKILL_DIR", skill_root)
    monkeypatch.setattr(run_script, "VENV_DIR", tmp_path / ".venv")
    run_script.VENV_DIR.mkdir(parents=True)

    with pytest.raises(SystemExit):
        run_script.main(["gateway.py"])


def test_packaged_script_resolver_rejects_symlinked_scripts_directory(tmp_path: Path) -> None:
    skill_root = tmp_path / "skill"
    skill_root.mkdir()
    outside_scripts = tmp_path / "outside-scripts"
    outside_scripts.mkdir()
    (outside_scripts / "gateway.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    (skill_root / "scripts").symlink_to(outside_scripts, target_is_directory=True)

    with pytest.raises(script_config.PackagedScriptError, match="outside the Skill root"):
        script_config.resolve_packaged_script(skill_root, "gateway.py")


def test_setup_environment_ensure_creates_venv_and_installs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(setup_script, "VENV_DIR", tmp_path / ".venv")
    monkeypatch.setattr(setup_script, "SKILL_DIR", SKILL_ROOT)

    created: list[Path] = []

    def fake_venv_create(path, with_pip=True):
        created.append(Path(path))
        (Path(path) / "bin").mkdir(parents=True, exist_ok=True)
        (Path(path) / "bin" / "python").write_text("#!/usr/bin/env python3\n")
        (Path(path) / "bin" / "pip").write_text("#!/usr/bin/env python3\n")

    installs: list[list[str]] = []

    def fake_run(cmd, check=True, capture_output=False, text=False):
        installs.append([str(part) for part in cmd])

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(setup_script.venv, "create", fake_venv_create)
    monkeypatch.setattr(setup_script.subprocess, "run", fake_run)

    env = setup_script.SkillEnvironment()
    assert env.ensure() is True
    assert created and created[0] == tmp_path / ".venv"
    assert installs and "install" in installs[0]


def test_setup_environment_ensure_without_requirements_skips_install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    skill_root = tmp_path / "skill"
    skill_root.mkdir()
    monkeypatch.setattr(setup_script, "SKILL_DIR", skill_root)
    monkeypatch.setattr(setup_script, "VENV_DIR", skill_root / ".venv")

    def fake_venv_create(path, with_pip=True):
        (Path(path) / "bin").mkdir(parents=True, exist_ok=True)
        (Path(path) / "bin" / "python").write_text("#!/usr/bin/env python3\n")
        (Path(path) / "bin" / "pip").write_text("#!/usr/bin/env python3\n")

    monkeypatch.setattr(setup_script.venv, "create", fake_venv_create)
    monkeypatch.setattr(setup_script.subprocess, "run", lambda *args, **kwargs: pytest.fail("install should be skipped"))

    env = setup_script.SkillEnvironment(skill_dir=skill_root)
    assert env.ensure() is True


def test_setup_environment_run_executes_allowlisted_script(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(setup_script, "VENV_DIR", tmp_path / ".venv")
    env = setup_script.SkillEnvironment()
    monkeypatch.setattr(setup_script.SkillEnvironment, "ensure", lambda self: True)

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append([str(part) for part in cmd])

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(setup_script.subprocess, "run", fake_run)
    assert env.run("setup_environment.py", ["--check"]) == 0
    assert calls and calls[0][1].endswith("setup_environment.py")


def test_setup_environment_run_missing_script_returns_one(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(setup_script, "VENV_DIR", tmp_path / ".venv")
    env = setup_script.SkillEnvironment()
    assert env.run("missing.py", []) == 1


def test_setup_environment_run_rejects_absolute_and_existing_temporary_scripts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    skill_root = tmp_path / "skill"
    scripts_root = skill_root / "scripts"
    scripts_root.mkdir(parents=True)
    helper = scripts_root / "temporary_helper.py"
    helper.write_text("raise SystemExit(0)\n", encoding="utf-8")
    outside = tmp_path / "gateway.py"
    outside.write_text("raise SystemExit(0)\n", encoding="utf-8")
    monkeypatch.setattr(setup_script, "VENV_DIR", tmp_path / ".venv")
    monkeypatch.setattr(
        setup_script.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("rejected setup --run target must not execute"),
    )
    env = setup_script.SkillEnvironment(skill_dir=skill_root)

    assert env.run("temporary_helper.py", []) == 1
    assert env.run(str(outside), []) == 1


def test_setup_environment_run_rejects_symlinked_allowlisted_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    skill_root = tmp_path / "skill"
    scripts_root = skill_root / "scripts"
    scripts_root.mkdir(parents=True)
    outside = tmp_path / "outside.py"
    outside.write_text("raise SystemExit(0)\n", encoding="utf-8")
    (scripts_root / "gateway.py").symlink_to(outside)
    monkeypatch.setattr(setup_script, "VENV_DIR", tmp_path / ".venv")
    env = setup_script.SkillEnvironment(skill_dir=skill_root)

    assert env.run("gateway.py", []) == 1


def test_setup_environment_main_check_branch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(setup_script, "VENV_DIR", tmp_path / ".venv")
    setup_script.VENV_DIR.mkdir(parents=True)
    assert setup_script.main(["--check"]) == 0


def test_setup_environment_parser_exists() -> None:
    parser = setup_script.build_parser()
    assert parser.description == "Prepare the Wwise WAAPI skill environment"


def test_setup_environment_main_run_branch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(setup_script, "VENV_DIR", tmp_path / ".venv")
    setup_script.VENV_DIR.mkdir(parents=True)
    env = setup_script.SkillEnvironment()
    original_class = setup_script.SkillEnvironment
    monkeypatch.setattr(original_class, "run", lambda self, script_name, args: 0)
    monkeypatch.setattr(setup_script, "SkillEnvironment", lambda: env)
    assert setup_script.main(["--run", "setup_environment.py", "--check"]) == 0
